#!/usr/bin/env python3
"""
plot_results.py — visualise one experiment run.

Usage:
    python3 plot_results.py results/20260419_100248
    python3 plot_results.py results/20260419_100248 --out figures/

Produces:
    edges_over_time.png      — edge coverage vs wall-clock time (all 4 conditions)
    crashes_over_time.png    — cumulative unique crashes vs time
    execs_per_sec.png        — fuzzer throughput vs time
    corpus_size.png          — corpus count vs time
    bo_weights.png           — BO/random-search mutation-weight evolution over windows
    bo_objective.png         — BO objective value per evaluation window
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ── Style ──────────────────────────────────────────────────────────────────────
COLORS = {
    "bo":            "#1f77b4",   # blue
    "random_search": "#ff7f0e",   # orange
    "afl_uniform":   "#2ca02c",   # green
    "afl_default":   "#d62728",   # red
}
LABELS = {
    "bo":            "BO (GP-EI)",
    "random_search": "Random search",
    "afl_uniform":   "AFL++ uniform θ",
    "afl_default":   "AFL++ default",
}
OP_NAMES = ["ADD", "MODIFY", "DELETE", "SWAP", "SPLICE"]

plt.rcParams.update({
    "figure.dpi": 150,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
})


# ── Data loading ───────────────────────────────────────────────────────────────

def load_timeseries(results_dir: Path, condition: str) -> pd.DataFrame | None:
    csv = results_dir / condition / "timeseries.csv"
    if not csv.exists():
        return None
    df = pd.read_csv(csv)
    df["wall_min"] = df["wall_time"] / 60.0
    return df


def load_observations(results_dir: Path, condition: str) -> pd.DataFrame | None:
    # observations.csv lives directly in the condition dir (symlinked from afl_runs/)
    for p in [
        results_dir / condition / "observations.csv",
        results_dir / condition / "afl_runs" / "observations.csv",
    ]:
        if p.exists():
            df = pd.read_csv(p)
            df["wall_min"] = df["wall_time"] / 60.0
            return df
    return None


def load_config(results_dir: Path) -> dict:
    cfg_path = results_dir / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    return {}


# ── Plot helpers ───────────────────────────────────────────────────────────────

def _save(fig, path: Path, name: str) -> None:
    out = path / name
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out}")


def _minutes_formatter(x, _):
    h, m = divmod(int(x), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _apply_time_axis(ax, budget_min: float) -> None:
    ax.set_xlabel("Wall time")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_minutes_formatter))
    ax.set_xlim(0, budget_min)


# ── Individual plots ───────────────────────────────────────────────────────────

# Map from observations.csv column → timeseries.csv column
_OBS_METRIC_MAP = {
    "edges_found":   "edges",
    "saved_crashes": "crashes",
    "corpus_count":  None,        # not in observations
    "execs_per_sec": None,        # not in observations
}


def plot_timeseries_metric(
    results_dir: Path, out_dir: Path, cfg: dict,
    metric: str, ylabel: str, title: str, fname: str,
    cumulative: bool = False,
) -> None:
    budget_min = cfg.get("budget_s", 5400) / 60.0
    fig, ax = plt.subplots(figsize=(9, 5))

    plotted = 0
    for cond in ["bo", "random_search", "afl_uniform", "afl_default"]:
        df = load_timeseries(results_dir, cond)
        if df is not None and metric in df.columns:
            y = df[metric].cummax() if cumulative else df[metric]
            ax.plot(df["wall_min"], y,
                    label=LABELS[cond], color=COLORS[cond], linewidth=1.8)
            plotted += 1
            continue

        # Fall back to observations.csv for bo/random_search
        obs_col = _OBS_METRIC_MAP.get(metric)
        if obs_col is None:
            continue
        obs = load_observations(results_dir, cond)
        if obs is None or obs_col not in obs.columns:
            continue
        y = obs[obs_col].cummax() if cumulative else obs[obs_col]
        ax.scatter(obs["wall_min"], y,
                   label=LABELS[cond], color=COLORS[cond],
                   s=40, zorder=3)
        ax.plot(obs["wall_min"], y,
                color=COLORS[cond], linewidth=1.0, linestyle="--", alpha=0.5)
        plotted += 1

    if not plotted:
        plt.close(fig)
        print(f"  skipped {fname} (no data)")
        return

    ax.set_ylabel(ylabel)
    ax.set_title(title)
    _apply_time_axis(ax, budget_min)
    ax.legend(framealpha=0.5)
    _save(fig, out_dir, fname)


def plot_bo_weights(results_dir: Path, out_dir: Path) -> None:
    for cond in ["bo", "random_search"]:
        df = load_observations(results_dir, cond)
        if df is None:
            continue

        w_cols = [c for c in df.columns if c.startswith("w") and c != "wall_time"]
        if len(w_cols) < 5:
            continue

        fig, ax = plt.subplots(figsize=(9, 5))
        for i, (col, name) in enumerate(zip(w_cols[:5], OP_NAMES)):
            ax.plot(df["wall_min"], df[col], label=name, linewidth=1.5)

        ax.set_ylabel("Mutation weight")
        ax.set_title(f"Mutation weight evolution — {LABELS[cond]}")
        ax.set_xlabel("Wall time (min)")
        ax.set_ylim(0, 1)
        ax.legend(ncol=3, framealpha=0.5)
        _save(fig, out_dir, f"bo_weights_{cond}.png")


def plot_bo_objective(results_dir: Path, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    plotted = 0
    for cond in ["bo", "random_search"]:
        df = load_observations(results_dir, cond)
        if df is None or "objective" not in df.columns:
            continue
        # cumulative best
        ax.plot(df["wall_min"], df["objective"].cummax(),
                label=f"{LABELS[cond]} (best so far)",
                color=COLORS[cond], linewidth=2)
        ax.scatter(df["wall_min"], df["objective"],
                   color=COLORS[cond], alpha=0.35, s=20, zorder=3)
        plotted += 1

    if not plotted:
        plt.close(fig)
        print("  skipped bo_objective.png (no data)")
        return

    ax.set_ylabel("Objective (α·crashes + (1−α)·Δedges·0.01)")
    ax.set_title("BO vs random-search: objective per evaluation window")
    ax.set_xlabel("Wall time (min)")
    ax.legend(framealpha=0.5)
    _save(fig, out_dir, "bo_objective.png")


def plot_energy(results_dir: Path, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    plotted = 0
    for cond in ["bo", "random_search"]:
        df = load_observations(results_dir, cond)
        if df is None or "energy" not in df.columns:
            continue
        ax.step(df["wall_min"], df["energy"],
                where="post", label=LABELS[cond],
                color=COLORS[cond], linewidth=1.5)
        plotted += 1

    if not plotted:
        plt.close(fig)
        return

    ax.set_ylabel("Mutation energy (mutations/seed)")
    ax.set_title("Energy parameter chosen per window")
    ax.set_xlabel("Wall time (min)")
    ax.legend(framealpha=0.5)
    _save(fig, out_dir, "bo_energy.png")


def plot_summary_bar(results_dir: Path, out_dir: Path, cfg: dict) -> None:
    """Bar chart of final edge count and total crashes for all conditions."""
    records = []
    for cond in ["bo", "random_search", "afl_uniform", "afl_default"]:
        df = load_timeseries(results_dir, cond)
        if df is None or df.empty:
            continue
        last = df.iloc[-1]
        records.append({
            "condition": LABELS[cond],
            "color":     COLORS[cond],
            "edges":     last["edges_found"],
            "crashes":   last["saved_crashes"],
        })

    if not records:
        print("  skipped summary bar (no data)")
        return

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, metric, ylabel in zip(
        axes,
        ["edges", "crashes"],
        ["Edges found (final)", "Unique crashes (final)"],
    ):
        vals   = [r[metric] for r in records]
        labels = [r["condition"] for r in records]
        colors = [r["color"] for r in records]
        bars = ax.bar(labels, vals, color=colors, edgecolor="white", width=0.5)
        ax.bar_label(bars, fmt="%d", padding=3, fontsize=10)
        ax.set_ylabel(ylabel)
        ax.set_title(ylabel)
        ax.tick_params(axis="x", labelrotation=15)

    fig.suptitle("Final results after {:.0f} min per condition".format(
        cfg.get("budget_s", 5400) / 60))
    fig.tight_layout()
    _save(fig, out_dir, "summary_bar.png")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Plot AFL++ BO experiment results")
    ap.add_argument("results_dir", help="Path to timestamped results directory")
    ap.add_argument("--out", default=None,
                    help="Output directory for figures (default: <results_dir>/figures)")
    args = ap.parse_args()

    results_dir = Path(args.results_dir).resolve()
    if not results_dir.is_dir():
        sys.exit(f"Not a directory: {results_dir}")

    out_dir = Path(args.out) if args.out else results_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(results_dir)
    budget_min = cfg.get("budget_s", 5400) / 60.0

    print(f"Results : {results_dir}")
    print(f"Figures : {out_dir}")
    print(f"Budget  : {budget_min:.0f} min per condition")
    print()

    plot_timeseries_metric(
        results_dir, out_dir, cfg,
        metric="edges_found", ylabel="Edges found",
        title="Edge coverage over time", fname="edges_over_time.png",
    )
    plot_timeseries_metric(
        results_dir, out_dir, cfg,
        metric="saved_crashes", ylabel="Unique crashes (cumulative)",
        title="Crash discovery over time", fname="crashes_over_time.png",
        cumulative=True,
    )
    plot_timeseries_metric(
        results_dir, out_dir, cfg,
        metric="execs_per_sec", ylabel="Executions / second",
        title="Fuzzer throughput over time", fname="execs_per_sec.png",
    )
    plot_timeseries_metric(
        results_dir, out_dir, cfg,
        metric="corpus_count", ylabel="Corpus size",
        title="Corpus growth over time", fname="corpus_size.png",
    )

    plot_bo_weights(results_dir, out_dir)
    plot_bo_objective(results_dir, out_dir)
    plot_energy(results_dir, out_dir)
    plot_summary_bar(results_dir, out_dir, cfg)

    print("\nDone.")


if __name__ == "__main__":
    main()
