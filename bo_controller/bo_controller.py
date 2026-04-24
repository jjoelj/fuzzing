#!/usr/bin/env python3
# BO controller: tunes mutation operator weights + energy for the AFL++ custom
# mutator using a GP surrogate (SingleTaskGP, Matern-5/2) with EI acquisition.
# Writes bo_state/theta.txt each round; the mutator picks it up via mmap poll.
#
# Usage:
#   python3 bo_controller.py \
#       --fuzz-bin  /path/to/fuzz_main \
#       --fuzz-in   /path/to/fuzz_in/ \
#       --mutator-lib /path/to/libmutator.so \
#       [--fuzz-out bo_fuzz_out] [--theta-path bo_state/theta.txt] \
#       [--warmstart-n 10] [--warmstart-dur 120] [--bo-dur 300]

import argparse
import csv
import os
import subprocess
import sys
import threading
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from botorch.acquisition import LogExpectedImprovement
from botorch.exceptions import InputDataWarning
from botorch.fit import fit_gpytorch_mll
from botorch.models import SingleTaskGP
from botorch.optim import optimize_acqf
from gpytorch.mlls import ExactMarginalLogLikelihood

warnings.filterwarnings("ignore", category=InputDataWarning)

sys.path.insert(0, str(Path(__file__).parent))
from ilr import ilr_forward, ilr_inverse, sample_simplex

NUM_OPS   = 5
E_MIN     = 32
E_MAX     = 512
GP_WINDOW = 50                  # sliding history window for GP
ALPHA_RAMP_DURATION = 1800.0    # seconds over which alpha ramps 0.3 -> 1.0

# GP input bounds: 4 ILR dims in [-4, 4], 1 energy dim in [0, 1]
_ILR_BOUND = 4.0
GP_BOUNDS = torch.tensor(
    [[-_ILR_BOUND] * 4 + [0.0],
     [ _ILR_BOUND] * 4 + [1.0]],
    dtype=torch.double,
)

@dataclass
class Observation:
    label:       str
    wall_time:   float    # seconds since experiment start
    w:           np.ndarray
    energy:      int
    crashes:     int
    edges:       int
    alpha:       float
    objective:   float
    z:           np.ndarray = field(repr=False)   # GP input vector (R^5)


def alpha_at(elapsed: float) -> float:
    return min(1.0, 0.3 + 0.7 * elapsed / ALPHA_RAMP_DURATION)


def composite_objective(crashes: int, edges: int, alpha: float) -> float:
    # Scale coverage term so it's roughly comparable to crash counts.
    # 0.01 is intentionally conservative - sanitizer hits dominate quickly.
    return alpha * crashes + (1.0 - alpha) * edges * 0.01


def encode(w: np.ndarray, energy: int) -> np.ndarray:
    """(w, e) -> R^5 GP input."""
    e_norm = (energy - E_MIN) / (E_MAX - E_MIN)
    return np.append(ilr_forward(w), e_norm)


def decode(z: np.ndarray) -> tuple[np.ndarray, int]:
    """R^5 GP input -> (w, e)."""
    w = ilr_inverse(z[:4])
    e = int(round(float(z[4]) * (E_MAX - E_MIN) + E_MIN))
    return w, int(np.clip(e, E_MIN, E_MAX))


def write_theta(path: Path, w: np.ndarray, energy: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(" ".join(f"{x:.8f}" for x in w) + f" {energy}\n")


def start_afl(fuzz_bin: str, fuzz_in: Path, output_dir: Path,
              mutator_lib: str, theta_path: Path) -> subprocess.Popen:
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "AFL_CUSTOM_MUTATOR_LIBRARY": mutator_lib,
        "AFL_CUSTOM_MUTATOR_ONLY":    "1",
        "BO_THETA_PATH":              str(theta_path),
        # Crash detection: SIGABRT on sanitizer trigger
        "ASAN_OPTIONS":  "abort_on_error=1:detect_leaks=0:symbolize=0",
        "UBSAN_OPTIONS": "abort_on_error=1",
    })
    cmd = [
        "afl-fuzz",
        "-i", str(fuzz_in),
        "-o", str(output_dir),
        "-t", "1000",      # 1 s per-testcase timeout
        "--",
        fuzz_bin,
    ]
    return subprocess.Popen(cmd, env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def collect_stats(output_dir: Path) -> tuple[int, int]:
    """Return (n_unique_crashes, edges_found) from an AFL++ output dir."""
    crashes_dir = output_dir / "default" / "crashes"
    n_crashes = 0
    if crashes_dir.exists():
        n_crashes = sum(
            1 for f in crashes_dir.iterdir() if f.name.startswith("id:")
        )

    edges = 0
    stats_file = output_dir / "default" / "fuzzer_stats"
    if stats_file.exists():
        for line in stats_file.read_text().splitlines():
            if line.startswith("edges_found"):
                try:
                    edges = int(line.split(":")[1].strip())
                except ValueError:
                    pass
                break

    return n_crashes, edges


def ensure_seed(fuzz_in: Path) -> None:
    """AFL++ needs at least one seed file.  Create a minimal one if absent."""
    seeds = list(fuzz_in.glob("*"))
    if not any(f.is_file() for f in seeds):
        fuzz_in.mkdir(parents=True, exist_ok=True)
        # Empty protobuf Sequence serialises to 0 bytes - valid for our target
        (fuzz_in / "seed0").write_bytes(b"")
        print("[BO] Created minimal seed in", fuzz_in)


SAMPLE_INTERVAL = 30   # seconds between fuzzer_stats polls for timeseries


def _parse_stats(stats_file: Path) -> dict:
    """Read key-value pairs from a fuzzer_stats file."""
    result = {}
    for line in stats_file.read_text().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def _sampler_thread(afl_out: Path, timeseries_csv: Path,
                    t0: float, stop: threading.Event) -> None:
    """Background thread: poll fuzzer_stats every SAMPLE_INTERVAL seconds."""
    write_header = not timeseries_csv.exists()
    while not stop.wait(SAMPLE_INTERVAL):
        stats_file = afl_out / "default" / "fuzzer_stats"
        if not stats_file.exists():
            continue
        try:
            s = _parse_stats(stats_file)
            row = {
                "wall_time":    int(time.time() - t0),
                "edges_found":  s.get("edges_found",  "0"),
                "execs_done":   s.get("execs_done",   "0"),
                "execs_per_sec": s.get("execs_per_sec", "0"),
                "saved_crashes": s.get("saved_crashes", "0"),
                "corpus_count": s.get("corpus_count",  "0"),
            }
            with open(timeseries_csv, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                if write_header:
                    writer.writeheader()
                    write_header = False
                writer.writerow(row)
        except Exception:
            pass


def run_evaluation(w: np.ndarray, energy: int,
                   output_dir: Path, duration: int,
                   fuzz_bin: str, fuzz_in: Path,
                   mutator_lib: str, theta_path: Path,
                   timeseries_csv: Path | None = None,
                   t0: float = 0.0) -> tuple[int, int]:
    """Write theta, run AFL++ for `duration` seconds, return stats."""
    write_theta(theta_path, w, energy)
    proc = start_afl(fuzz_bin, fuzz_in, output_dir, mutator_lib, theta_path)

    stop_event = threading.Event()
    if timeseries_csv is not None:
        sampler = threading.Thread(
            target=_sampler_thread,
            args=(output_dir, timeseries_csv, t0, stop_event),
            daemon=True,
        )
        sampler.start()

    try:
        time.sleep(duration)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stop_event.set()

    time.sleep(1)   # let AFL++ finish flushing fuzzer_stats
    return collect_stats(output_dir)


def fit_gp(observations: list[Observation]):
    """Fit a SingleTaskGP (Matern-5/2) on the sliding window."""
    window = observations[-GP_WINDOW:]
    X = torch.tensor(np.array([o.z for o in window]), dtype=torch.double)
    Y_raw = torch.tensor([[o.objective] for o in window], dtype=torch.double)

    # Standardise Y so the GP prior is calibrated
    mu, sigma = Y_raw.mean(), Y_raw.std().clamp(min=1e-6)
    Y = (Y_raw - mu) / sigma

    model = SingleTaskGP(X, Y)
    mll   = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)

    best_f = Y.max().item()
    return model, best_f


def next_theta_ei(model, best_f: float) -> tuple[np.ndarray, int]:
    """Maximise Log Expected Improvement -> next (w, e)."""
    acq = LogExpectedImprovement(model=model, best_f=best_f)
    candidate, _ = optimize_acqf(
        acq_function=acq,
        bounds=GP_BOUNDS,
        q=1,
        num_restarts=10,
        raw_samples=256,
    )
    z = candidate.squeeze(0).detach().numpy()
    return decode(z)


_CSV_HEADER = [
    "label", "wall_time", "alpha",
    "w0", "w1", "w2", "w3", "w4", "energy",
    "crashes", "edges", "objective",
]


def log_observation(log_path: Path, obs: Observation) -> None:
    write_header = not log_path.exists()
    with open(log_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(_CSV_HEADER)
        writer.writerow([
            obs.label,
            f"{obs.wall_time:.1f}",
            f"{obs.alpha:.3f}",
            *[f"{x:.6f}" for x in obs.w],
            obs.energy,
            obs.crashes,
            obs.edges,
            f"{obs.objective:.5f}",
        ])


class BOController:
    def __init__(self, fuzz_bin: str, fuzz_in: Path, fuzz_out_base: Path,
                 theta_path: Path, mutator_lib: str,
                 warmstart_n: int, warmstart_dur: int, bo_dur: int,
                 random_search: bool = False):
        self.fuzz_bin      = fuzz_bin
        self.fuzz_in       = fuzz_in
        self.fuzz_out_base = fuzz_out_base
        self.theta_path    = theta_path
        self.mutator_lib   = mutator_lib
        self.warmstart_n   = warmstart_n
        self.warmstart_dur = warmstart_dur
        self.bo_dur        = bo_dur
        self.random_search = random_search   # baseline: skip GP, sample theta uniformly

        self.observations: list[Observation] = []
        self.start_time: float = 0.0
        self.rng = np.random.default_rng(42)
        self.log_path = fuzz_out_base / "observations.csv"

        fuzz_out_base.mkdir(parents=True, exist_ok=True)
        ensure_seed(fuzz_in)

    def _record(self, label: str, w: np.ndarray, energy: int,
                crashes: int, edges: int) -> Observation:
        elapsed = time.time() - self.start_time
        alpha   = alpha_at(elapsed)
        obj     = composite_objective(crashes, edges, alpha)
        z       = encode(w, energy)
        obs = Observation(label=label, wall_time=elapsed, w=w.copy(),
                          energy=energy, crashes=crashes, edges=edges,
                          alpha=alpha, objective=obj, z=z)
        self.observations.append(obs)
        log_observation(self.log_path, obs)
        return obs

    def _eval(self, w: np.ndarray, energy: int,
              label: str, duration: int) -> Observation:
        out_dir = self.fuzz_out_base / label
        crashes, edges = run_evaluation(
            w, energy, out_dir, duration,
            self.fuzz_bin, self.fuzz_in,
            self.mutator_lib, self.theta_path,
            timeseries_csv=self.fuzz_out_base / "timeseries.csv",
            t0=self.start_time,
        )
        obs = self._record(label, w, energy, crashes, edges)
        total = sum(o.crashes for o in self.observations)
        print(f"[BO] {label:20s}  w=[{', '.join(f'{x:.2f}' for x in w)}]"
              f"  e={energy:4d}  alpha={obs.alpha:.2f}"
              f"  crashes={crashes}  edges={edges}"
              f"  f={obs.objective:.3f}  total_crashes={total}")
        return obs

    def warmstart(self) -> None:
        print(f"\n[BO] === Warm-start: {self.warmstart_n} random configs "
              f"x {self.warmstart_dur}s ===")
        for i in range(self.warmstart_n):
            w      = sample_simplex(NUM_OPS, self.rng)
            energy = int(self.rng.integers(E_MIN, E_MAX + 1))
            self._eval(w, energy, f"warmstart_{i:02d}", self.warmstart_dur)

    def bo_loop(self) -> None:
        mode = "random-search" if self.random_search else "BO"
        print(f"\n[BO] === {mode} loop ({self.bo_dur}s windows) - Ctrl-C to stop ===")
        iteration = 0
        while True:
            if self.random_search:
                # Baseline: uniform random sampling over theta - no GP, no EI
                w      = sample_simplex(NUM_OPS, self.rng)
                energy = int(self.rng.integers(E_MIN, E_MAX + 1))
            else:
                # Fit GP on sliding window, maximise EI
                try:
                    model, best_f = fit_gp(self.observations)
                    w, energy = next_theta_ei(model, best_f)
                except Exception as exc:
                    print(f"[BO] GP/EI failed ({exc}), sampling randomly")
                    w      = sample_simplex(NUM_OPS, self.rng)
                    energy = int(self.rng.integers(E_MIN, E_MAX + 1))

            self._eval(w, energy, f"bo_{iteration:04d}", self.bo_dur)
            iteration += 1

    def run(self) -> None:
        self.start_time = time.time()
        try:
            self.warmstart()
            self.bo_loop()
        except KeyboardInterrupt:
            print("\n[BO] Interrupted.  Observations saved to", self.log_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bayesian Optimisation controller for AFL++ mutation strategy"
    )
    parser.add_argument("--fuzz-bin",     required=True,
                        help="Path to the AFL++-instrumented target binary")
    parser.add_argument("--fuzz-in",      required=True,
                        help="AFL++ input corpus directory")
    parser.add_argument("--mutator-lib",  required=True,
                        help="Path to libmutator.so")
    parser.add_argument("--fuzz-out",     default="bo_fuzz_out",
                        help="Base directory for AFL++ output dirs")
    parser.add_argument("--theta-path",   default="bo_state/theta.txt",
                        help="Path for the theta file (read by the mutator)")
    parser.add_argument("--warmstart-n",  type=int, default=10,
                        help="Number of random warm-start evaluations")
    parser.add_argument("--warmstart-dur", type=int, default=120,
                        help="Seconds per warm-start evaluation")
    parser.add_argument("--bo-dur",        type=int, default=300,
                        help="Seconds per BO evaluation window")
    parser.add_argument("--random-search", action="store_true",
                        help="Baseline mode: sample theta uniformly instead of using GP-EI")
    args = parser.parse_args()

    ctrl = BOController(
        fuzz_bin      = args.fuzz_bin,
        fuzz_in       = Path(args.fuzz_in),
        fuzz_out_base = Path(args.fuzz_out),
        theta_path    = Path(args.theta_path),
        mutator_lib   = args.mutator_lib,
        warmstart_n   = args.warmstart_n,
        warmstart_dur = args.warmstart_dur,
        bo_dur        = args.bo_dur,
        random_search = args.random_search,
    )
    ctrl.run()


if __name__ == "__main__":
    main()
