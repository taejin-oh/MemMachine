#!/usr/bin/env python3
"""Plot eval results as PNG charts. Two input formats:

    compare_runs.json   → grouped bar chart of N-run accuracy per category
                           (workflow A — oracle ceiling, workflow C — position)
    sclean_recall.json  → recall_A / recall_B per category bar chart
                           (workflow B — s_cleaned recall)

This file is intentionally short and flat — tweak the PLOT_CONFIG block at
the top, then run. No class hierarchies, no plugin system.

Usage:
    python scripts/plot_results.py --type compare \
        --input results/oracle_ceiling_compare.json \
        --out results/oracle_ceiling.png

    python scripts/plot_results.py --type recall \
        --input results/<run>/sclean_recall.json \
        --out results/<run>/recall.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# PLOT_CONFIG — edit these to restyle. Everything visual flows through here.
# ---------------------------------------------------------------------------
PLOT_CONFIG: dict[str, Any] = {
    "figsize": (12, 6),
    "dpi": 140,
    "bar_palette": [
        "#4C78A8",  # blue
        "#F58518",  # orange
        "#54A24B",  # green
        "#E45756",  # red
        "#72B7B2",  # teal
        "#B279A2",  # purple
    ],
    "category_order": [
        # LongMemEval 6 types — appears in this order on the x axis
        "single-session-user",
        "single-session-assistant",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
        "multi-session",
    ],
    "value_format": "{:.3f}",       # printed on top of each bar
    "value_fontsize": 8,
    "title_fontsize": 13,
    "axis_label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
    "y_lim": (0.0, 1.05),
    "y_grid": True,
}

# Recall plot uses a fixed 2-color palette (A vs B). Keep separate so changing
# bar_palette above doesn't ripple unexpectedly into the recall chart.
RECALL_COLORS = {
    "recall_A": "#4C78A8",   # all evidence-session turns
    "recall_B": "#F58518",   # has_answer=True turns only
}


def _ordered_categories(present: list[str]) -> list[str]:
    """Return categories in PLOT_CONFIG order; unknown ones tacked on at end."""
    order = PLOT_CONFIG["category_order"]
    ranked = [c for c in order if c in present]
    extras = [c for c in present if c not in order]
    return ranked + sorted(extras)


def _annotate_bars(ax: plt.Axes, bars, values: list[float | None]) -> None:
    fmt = PLOT_CONFIG["value_format"]
    fs = PLOT_CONFIG["value_fontsize"]
    for rect, v in zip(bars, values, strict=False):
        if v is None:
            continue
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            rect.get_height() + 0.01,
            fmt.format(v),
            ha="center",
            va="bottom",
            fontsize=fs,
        )


# ---------------------------------------------------------------------------
# Type 1: compare_runs.json — grouped bar chart per category
# ---------------------------------------------------------------------------
def plot_compare(data: dict[str, Any], out_path: Path) -> None:
    labels: list[str] = data["labels"]
    runs: list[dict[str, Any]] = data["runs"]
    palette = PLOT_CONFIG["bar_palette"]

    # Build category list: union of all by_category keys, ordered by config
    present_cats = sorted({c for r in runs for c in r["by_category_acc"]})
    categories = ["OVERALL", *_ordered_categories(present_cats)]
    x = np.arange(len(categories))
    width = 0.8 / len(labels)

    fig, ax = plt.subplots(figsize=PLOT_CONFIG["figsize"], dpi=PLOT_CONFIG["dpi"])

    for idx, (label, run) in enumerate(zip(labels, runs, strict=False)):
        values = []
        for cat in categories:
            if cat == "OVERALL":
                values.append(run.get("overall_accuracy"))
            else:
                values.append(run["by_category_acc"].get(cat))
        offsets = x + (idx - (len(labels) - 1) / 2) * width
        bars = ax.bar(
            offsets,
            [v if v is not None else 0 for v in values],
            width=width,
            label=label,
            color=palette[idx % len(palette)],
            edgecolor="white",
        )
        _annotate_bars(ax, bars, values)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=20, ha="right",
                       fontsize=PLOT_CONFIG["tick_fontsize"])
    ax.set_ylabel("Accuracy", fontsize=PLOT_CONFIG["axis_label_fontsize"])
    ax.set_ylim(*PLOT_CONFIG["y_lim"])
    if PLOT_CONFIG["y_grid"]:
        ax.yaxis.grid(True, linestyle=":", alpha=0.5)
        ax.set_axisbelow(True)
    ax.set_title(
        f"Accuracy comparison  ({' vs '.join(labels)})",
        fontsize=PLOT_CONFIG["title_fontsize"],
    )
    ax.legend(fontsize=PLOT_CONFIG["legend_fontsize"], frameon=False)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[plot_results] wrote {out_path}")


# ---------------------------------------------------------------------------
# Type 2: sclean_recall.json — recall A / B per category
# ---------------------------------------------------------------------------
def plot_recall(data: dict[str, Any], out_path: Path) -> None:
    summary = data["summary"]
    by_cat = summary.get("by_category", {})
    present_cats = list(by_cat.keys())
    categories = ["OVERALL", *_ordered_categories(present_cats)]
    x = np.arange(len(categories))
    width = 0.36

    a_vals: list[float | None] = []
    b_vals: list[float | None] = []
    for cat in categories:
        if cat == "OVERALL":
            a = summary["overall"]["recall_a"].get("mean")
            b = summary["overall"]["recall_b"].get("mean")
        else:
            a = by_cat.get(cat, {}).get("recall_a", {}).get("mean")
            b = by_cat.get(cat, {}).get("recall_b", {}).get("mean")
        a_vals.append(a)
        b_vals.append(b)

    fig, ax = plt.subplots(figsize=PLOT_CONFIG["figsize"], dpi=PLOT_CONFIG["dpi"])

    bars_a = ax.bar(
        x - width / 2,
        [v if v is not None else 0 for v in a_vals],
        width=width,
        label="Recall A (all evidence turns)",
        color=RECALL_COLORS["recall_A"],
        edgecolor="white",
    )
    bars_b = ax.bar(
        x + width / 2,
        [v if v is not None else 0 for v in b_vals],
        width=width,
        label="Recall B (has_answer=True only)",
        color=RECALL_COLORS["recall_B"],
        edgecolor="white",
    )
    _annotate_bars(ax, bars_a, a_vals)
    _annotate_bars(ax, bars_b, b_vals)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=20, ha="right",
                       fontsize=PLOT_CONFIG["tick_fontsize"])
    ax.set_ylabel("Mean recall", fontsize=PLOT_CONFIG["axis_label_fontsize"])
    ax.set_ylim(*PLOT_CONFIG["y_lim"])
    if PLOT_CONFIG["y_grid"]:
        ax.yaxis.grid(True, linestyle=":", alpha=0.5)
        ax.set_axisbelow(True)
    ax.set_title(
        "Retrieval recall vs oracle ground truth",
        fontsize=PLOT_CONFIG["title_fontsize"],
    )
    ax.legend(fontsize=PLOT_CONFIG["legend_fontsize"], frameon=False)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[plot_results] wrote {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--type",
        choices=("compare", "recall"),
        required=True,
        help="compare = compare_runs.json, recall = sclean_recall.json",
    )
    p.add_argument("--input", required=True, help="Input JSON path.")
    p.add_argument("--out", required=True, help="Output PNG path.")
    args = p.parse_args()

    with open(Path(args.input).resolve()) as f:
        data = json.load(f)
    out_path = Path(args.out).resolve()

    if args.type == "compare":
        plot_compare(data, out_path)
    else:
        plot_recall(data, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
