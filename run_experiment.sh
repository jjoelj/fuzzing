#!/usr/bin/env bash
# run_experiment.sh — overnight BO-fuzzing experiment
#
# Runs 4 conditions sequentially, each for BUDGET_S seconds:
#   bo            — GP-EI guided mutation weights   (main condition)
#   random_search — uniform-random weights per window (ablation: no GP)
#   afl_uniform   — custom mutator, fixed uniform weights (ablation: no adaptation)
#   afl_default   — AFL++ built-in mutations, no custom mutator (reference)
#
# Output layout:
#   results/<timestamp>/
#     config.json
#     experiment.log
#     bo/            observations.csv  controller.log  theta.txt  afl_runs/
#     random_search/ observations.csv  controller.log  theta.txt  afl_runs/
#     afl_uniform/   timeseries.csv    final_stats.txt  theta.txt  fuzz_out/
#     afl_default/   timeseries.csv    final_stats.txt  fuzz_out/
#     summary/       (written by analyze.py)
#
# Usage:
#   bash run_experiment.sh
#   bash run_experiment.sh --budget-s 3600   # 1-hour windows instead of 90 min
set -euo pipefail

# ── Tunables ──────────────────────────────────────────────────────────────────
BUDGET_S=${BUDGET_S:-5400}   # seconds per condition (default 90 min)
WINDOW_S=${WINDOW_S:-300}    # seconds per BO/random evaluation window
WARMSTART_N=5                # number of random warm-start evaluations
SAMPLE_INTERVAL=30           # seconds between fuzzer_stats polls

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --budget-s) BUDGET_S="$2"; shift 2 ;;
        --window-s) WINDOW_S="$2"; shift 2 ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FUZZ_BIN="$SCRIPT_DIR/build/fuzz_main"
FUZZ_IN="$SCRIPT_DIR/fuzz_in"
MUTATOR="$SCRIPT_DIR/build/mutator/libmutator.so"
RESULTS="$SCRIPT_DIR/results/$(date +%Y%m%d_%H%M%S)"

for f in "$FUZZ_BIN" "$FUZZ_IN" "$MUTATOR"; do
    [[ -e "$f" ]] || { echo "Missing: $f — rebuild first."; exit 1; }
done

mkdir -p "$RESULTS"

# ── Environment ───────────────────────────────────────────────────────────────
export AFL_SKIP_CPUFREQ=1
export AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1
export AFL_NO_UI=1

# ── Logging ───────────────────────────────────────────────────────────────────
LOG="$RESULTS/experiment.log"
log() {
    local msg="[$(date '+%H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG"
}

# ── Save config ───────────────────────────────────────────────────────────────
cat > "$RESULTS/config.json" <<EOF
{
  "budget_s":        $BUDGET_S,
  "window_s":        $WINDOW_S,
  "warmstart_n":     $WARMSTART_N,
  "sample_interval": $SAMPLE_INTERVAL,
  "fuzz_bin":        "$FUZZ_BIN",
  "fuzz_in":         "$FUZZ_IN",
  "mutator":         "$MUTATOR",
  "started_at":      "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "conditions":      ["bo","random_search","afl_uniform","afl_default"]
}
EOF

WARMSTART_S=$(( WARMSTART_N * WINDOW_S ))
TOTAL_S=$(( BUDGET_S * 4 ))
log "Results directory : $RESULTS"
log "Budget per cond   : ${BUDGET_S}s ($(( BUDGET_S / 60 )) min)"
log "Window / warmstart: ${WINDOW_S}s / ${WARMSTART_N} × ${WINDOW_S}s = ${WARMSTART_S}s"
log "Total wall time   : ~$(( TOTAL_S / 3600 ))h $(( TOTAL_S % 3600 / 60 ))m"
log "Starting..."

# ── fuzzer_stats sampler ──────────────────────────────────────────────────────
# Writes a CSV row every SAMPLE_INTERVAL seconds.
# Call as a background function; kill with SAMPLER_PID when done.
_sampler() {
    local afl_out="$1" csv="$2" t0="$3"
    printf 'wall_time,edges_found,execs_done,execs_per_sec,saved_crashes,corpus_count\n' > "$csv"
    while true; do
        local stats="$afl_out/default/fuzzer_stats"
        if [[ -f "$stats" ]]; then
            local now=$(( $(date +%s) - t0 ))
            local edges execs eps crashes corpus
            edges=$(awk  -F' *: *' '/^edges_found/{print $2}' "$stats")
            execs=$(awk  -F' *: *' '/^execs_done/{print $2}'  "$stats")
            eps=$(awk    -F' *: *' '/^execs_per_sec/{print $2}' "$stats")
            crashes=$(awk -F' *: *' '/^saved_crashes/{print $2}' "$stats")
            corpus=$(awk  -F' *: *' '/^corpus_count/{print $2}'  "$stats")
            printf '%d,%s,%s,%s,%s,%s\n' \
                "$now" "${edges:-0}" "${execs:-0}" \
                "${eps:-0}" "${crashes:-0}" "${corpus:-0}" >> "$csv"
        fi
        sleep "$SAMPLE_INTERVAL"
    done
}

# ── Condition runners ─────────────────────────────────────────────────────────

# run_afl <label> [extra_afl_flags...]
# Runs plain afl-fuzz (or with extra flags) for BUDGET_S seconds.
# Samples fuzzer_stats into timeseries.csv.
run_afl() {
    local label="$1"; shift
    local extra_flags=("$@")
    local out_dir="$RESULTS/$label"
    mkdir -p "$out_dir"
    log "[$label] starting (budget=${BUDGET_S}s)..."

    local t0; t0=$(date +%s)
    afl-fuzz -i "$FUZZ_IN" -o "$out_dir/fuzz_out" -t 2000 \
        "${extra_flags[@]}" -- "$FUZZ_BIN" \
        >"$out_dir/afl.stdout" 2>"$out_dir/afl.stderr" &
    local afl_pid=$!

    _sampler "$out_dir/fuzz_out" "$out_dir/timeseries.csv" "$t0" &
    local sampler_pid=$!

    sleep "$BUDGET_S"

    kill "$afl_pid"    2>/dev/null || true
    wait "$afl_pid"    2>/dev/null || true
    kill "$sampler_pid" 2>/dev/null || true
    wait "$sampler_pid" 2>/dev/null || true

    cp "$out_dir/fuzz_out/default/fuzzer_stats" "$out_dir/final_stats.txt" 2>/dev/null || true
    local last; last=$(tail -1 "$out_dir/timeseries.csv")
    log "[$label] done — final row: $last"
}

# run_afl_with_mutator <label> <theta_values>
# Like run_afl but injects the custom mutator with a fixed theta.
# theta_values: "w0 w1 w2 w3 w4 energy"
run_afl_with_mutator() {
    local label="$1" theta="$2"
    local out_dir="$RESULTS/$label"
    mkdir -p "$out_dir"
    printf '%s\n' "$theta" > "$out_dir/theta.txt"
    log "[$label] starting with fixed theta: $theta (budget=${BUDGET_S}s)..."

    local t0; t0=$(date +%s)
    AFL_CUSTOM_MUTATOR_LIBRARY="$MUTATOR" \
    AFL_CUSTOM_MUTATOR_ONLY=1 \
    BO_THETA_PATH="$out_dir/theta.txt" \
    afl-fuzz -i "$FUZZ_IN" -o "$out_dir/fuzz_out" -t 2000 \
        -- "$FUZZ_BIN" \
        >"$out_dir/afl.stdout" 2>"$out_dir/afl.stderr" &
    local afl_pid=$!

    _sampler "$out_dir/fuzz_out" "$out_dir/timeseries.csv" "$t0" &
    local sampler_pid=$!

    sleep "$BUDGET_S"

    kill "$afl_pid"    2>/dev/null || true
    wait "$afl_pid"    2>/dev/null || true
    kill "$sampler_pid" 2>/dev/null || true
    wait "$sampler_pid" 2>/dev/null || true

    cp "$out_dir/fuzz_out/default/fuzzer_stats" "$out_dir/final_stats.txt" 2>/dev/null || true
    local last; last=$(tail -1 "$out_dir/timeseries.csv")
    log "[$label] done — final row: $last"
}

# run_bo <label> [--random-search]
# Runs the BO controller for BUDGET_S seconds.
# The controller itself manages AFL++ sub-processes; observations go to
# $out_dir/afl_runs/observations.csv (which we link to $out_dir/).
run_bo() {
    local label="$1"; shift
    local extra_flags=("$@")   # e.g. --random-search
    local out_dir="$RESULTS/$label"
    mkdir -p "$out_dir/afl_runs"
    log "[$label] starting (budget=${BUDGET_S}s, window=${WINDOW_S}s × warmup=${WARMSTART_N})..."

    timeout --signal=INT "$BUDGET_S" \
        python3 bo_controller/bo_controller.py \
            --fuzz-bin    "$FUZZ_BIN" \
            --fuzz-in     "$FUZZ_IN" \
            --mutator-lib "$MUTATOR" \
            --fuzz-out    "$out_dir/afl_runs" \
            --theta-path  "$out_dir/theta.txt" \
            --warmstart-n  "$WARMSTART_N" \
            --warmstart-dur "$WINDOW_S" \
            --bo-dur        "$WINDOW_S" \
            "${extra_flags[@]}" \
        2>&1 | tee "$out_dir/controller.log" || true

    # Symlink observations.csv to the condition root for easy access
    ln -sf "afl_runs/observations.csv" "$out_dir/observations.csv" 2>/dev/null || true

    local nrows=0
    [[ -f "$out_dir/afl_runs/observations.csv" ]] && \
        nrows=$(( $(wc -l < "$out_dir/afl_runs/observations.csv") - 1 ))
    log "[$label] done — $nrows observations written"
}

# ── Run all conditions ─────────────────────────────────────────────────────────
# Order: cheapest/fastest first so if anything goes wrong you see it early.

log "=== Condition 1/4: afl_default ==="
run_afl "afl_default"

log "=== Condition 2/4: afl_uniform (custom mutator, fixed equal weights) ==="
run_afl_with_mutator "afl_uniform" "0.20000000 0.20000000 0.20000000 0.20000000 0.20000000 128"

log "=== Condition 3/4: random_search ==="
run_bo "random_search" --random-search

log "=== Condition 4/4: bo (GP-EI) ==="
run_bo "bo"

# ── Done ──────────────────────────────────────────────────────────────────────
log "All conditions complete."
log "Run analysis:  python3 analyze.py $RESULTS"
log "Results dir:   $RESULTS"
