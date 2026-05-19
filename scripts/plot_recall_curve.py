#!/usr/bin/env python3
"""Plot recall@k curves from recall_curve.json.

X axis: k (1..max_k). Y axis: mean recall (0..1).
One thick black line for overall, distinct colored lines per category.

Tweak PLOT_CONFIG at the top of the file — palette, fontsizes, line widths,
y-axis range, etc. — to restyle.

Usage:
    python scripts/plot_recall_curve.py \
        --input results/<my_run>/recall_curve.json \
        --out   results/<my_run>/recall_curve.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# PLOT_CONFIG — edit these to restyle.
# ---------------------------------------------------------------------------
PLOT_CONFIG: dict[str, Any] = {
    "figsize": (12, 6),
    "dpi": 140,
    "overall_color": "#000000",
    "overall_linewidth": 2.4,
    "category_linewidth": 1.4,
    "category_palette": [
        "#4C78A8",  # blue
        "#F58518",  # orange
        "#54A24B",  # green
        "#E45756",  # red
        "#72B7B2",  # teal
        "#B279A2",  # purple
        "#FF9DA6",  # pink
        "#9D755D",  # brown
    ],
    "category_order": [
        # LongMemEval 6 types in fixed order so colors are stable across runs
        "single-session-user",
        "single-session-assistant",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
        "multi-session",
    ],
    "title": "Recall@k vs k",
    "xlabel": "k (top-k chunks)",
    "ylabel": "Mean recall",
    "y_lim": (0.0, 1.05),
    "y_grid": True,
    "title_fontsize": 13,
    "axis_label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 9,
}


def _ordered_categories(present: list[str]) -> list[str]:
    order = PLOT_CONFIG["category_order"]
    ranked = [c for c in order if c in present]
    extras = [c for c in present if c not in order]
    return ranked + sorted(extras)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", required=True, help="recall_curve.json from recall_curve.py")
    p.add_argument("--out", required=True, help="Output PNG path.")
    args = p.parse_args()

    with open(Path(args.input).resolve()) as f:
        data = json.load(f)

    max_k = int(data["max_k"])
    xs = list(range(1, max_k + 1))
    overall = data["overall"]
    by_cat = data["by_category"]
    counts = data.get("counts", {})

    fig, ax = plt.subplots(figsize=PLOT_CONFIG["figsize"], dpi=PLOT_CONFIG["dpi"])

    # Per-category lines first so OVERALL sits on top.
    cats = _ordered_categories(list(by_cat.keys()))
    palette = PLOT_CONFIG["category_palette"]
    for i, cat in enumerate(cats):
        n_cat = counts.get("by_category", {}).get(cat, len(by_cat[cat]))
        ax.plot(
            xs,
            by_cat[cat],
            label=f"{cat} (n={n_cat})",
            color=palette[i % len(palette)],
            linewidth=PLOT_CONFIG["category_linewidth"],
        )

    # OVERALL on top, thick black.
    n_overall = counts.get("overall", len(overall))
    ax.plot(
        xs,
        overall,
        label=f"OVERALL (n={n_overall})",
        color=PLOT_CONFIG["overall_color"],
        linewidth=PLOT_CONFIG["overall_linewidth"],
    )

    ax.set_xlabel(PLOT_CONFIG["xlabel"], fontsize=PLOT_CONFIG["axis_label_fontsize"])
    ax.set_ylabel(PLOT_CONFIG["ylabel"], fontsize=PLOT_CONFIG["axis_label_fontsize"])
    ax.set_ylim(*PLOT_CONFIG["y_lim"])
    ax.set_xlim(1, max_k)
    ax.tick_params(labelsize=PLOT_CONFIG["tick_fontsize"])
    if PLOT_CONFIG["y_grid"]:
        ax.yaxis.grid(True, linestyle=":", alpha=0.5)
        ax.set_axisbelow(True)
    ax.set_title(PLOT_CONFIG["title"], fontsize=PLOT_CONFIG["title_fontsize"])
    ax.legend(
        fontsize=PLOT_CONFIG["legend_fontsize"],
        loc="lower right",
        frameon=False,
    )

    fig.tight_layout()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[plot_recall_curve] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
