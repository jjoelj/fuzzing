# BO-guided AFL++ fuzzing

This is a research prototype that uses Bayesian optimisation to tune AFL++'s mutation strategy while fuzzing is running. The idea: instead of fixed mutation operator weights, a GP+EI loop periodically re-samples them based on what's actually producing crashes and coverage.

The target is a small SQLite driver with two planted bugs. It's not a real vulnerability -- it's there so we can measure how fast different strategies find known-hard conditions.

## How it works

AFL++ runs with a custom mutator (`mutator/mutator.cpp`) that applies one of five structure-aware operators -- add, modify, delete, swap, splice -- to a protobuf-encoded command sequence. The mutator reads its operator weights and energy budget from `bo_state/theta.txt`.

The BO controller (`bo_controller/bo_controller.py`) runs in a separate process. Every N seconds it kills AFL++, reads `fuzzer_stats` + crash count, fits a `SingleTaskGP` on the sliding observation window, maximises `LogExpectedImprovement` to get the next theta, writes it to disk, and restarts AFL++. Because the five operator weights must always sum to 1, they can't be treated as independent variables -- changing one forces the others to shift. The GP can't handle that directly, so the weights are converted to an unconstrained coordinate space first (via ILR transform), the GP runs there, and the result is converted back before writing `theta.txt`.

The objective is `alpha*crashes + (1-alpha)*edges`, where alpha ramps from 0.3 to 1.0 over 30 minutes -- coverage-first early on, crash-focused later.

## Setup

The easiest path is the dev container. Open in VS Code and reopen in container -- the Dockerfile handles everything. If you want to run it directly:

```bash
docker build -t bo-afl .devcontainer/
docker run --privileged -it -v $(pwd):/workspace bo-afl bash
```

`--privileged` is needed for AFL++'s CPU frequency scaling. Without it you'll get warnings and possibly wrong exec/s counts.

### SQLite

The build needs `sqlite/sqlite3.c` and `sqlite/sqlite3.h`. Grab the amalgamation zip from sqlite.org and drop those two files into `sqlite/` before running cmake.

### Building

The mutator is a cmake sub-project (it needs to build without AFL's compiler wrappers), so there's a two-pass build:

```bash
mkdir build && cd build
cmake .. -GNinja -DCMAKE_BUILD_TYPE=Release

# build the mutator sub-project first - this generates the protobuf headers
cmake --build . --target proto_lib_ep -- -j$(nproc)

# re-run cmake so it can find proto_lib, then build everything else
cmake ..
cmake --build . -j$(nproc)
```

You end up with `build/fuzz_main` (the instrumented target), `build/mutator/libmutator.so` (the custom mutator), and `build/main` (a plain driver for testing inputs by hand).

## Running

```bash
python3 bo_controller/bo_controller.py \
    --fuzz-bin    build/fuzz_main \
    --fuzz-in     fuzz_in/ \
    --mutator-lib build/mutator/libmutator.so \
    --warmstart-n   10 \
    --warmstart-dur 120 \
    --bo-dur        300
```

The warm-start phase runs 10 random configurations (120s each) before the GP has enough data to be useful. After that the BO loop runs indefinitely -- Ctrl-C to stop.

Each window prints:

```
[BO] bo_0001   w=[0.31, 0.18, 0.22, 0.14, 0.15]  e= 256  alpha=0.62  crashes=3  edges=1847  f=3.185
```

To run the random-search baseline instead (same setup, no GP):

```bash
python3 bo_controller/bo_controller.py \
    --fuzz-bin build/fuzz_main --fuzz-in fuzz_in/ \
    --mutator-lib build/mutator/libmutator.so \
    --random-search
```

## Target bugs

`main.cpp` feeds parsed command sequences into an in-memory SQLite table (`CREATE TABLE t(val INTEGER)`) and checks after each sequence:

- `SUM(val) == 42 AND COUNT(*) >= 3` -> abort
- `SUM(val*val) % 1000 == 133 AND COUNT(*) >= 4` -> abort

Both are `SIGABRT`, which AFL++ picks up as crashes.

## Outputs

- `bo_fuzz_out/observations.csv` -- one row per evaluation window (weights, energy, crashes, edges, objective)
- `bo_fuzz_out/timeseries.csv` -- AFL++ stats polled every 30s throughout the run
- `bo_state/theta.txt` -- current theta written by the controller, read by the mutator
- `bo_fuzz_out/<label>/default/crashes/` -- crash inputs from each window

## Dependencies

All C++ deps are pinned and built in the container: AFL++ v4.31c, abseil 20240116.0, protobuf v29.3, libprotobuf-mutator v1.5. Python side: PyTorch (CPU build), BoTorch, GPyTorch, scipy, numpy -- installed into `/opt/bo_venv`.
