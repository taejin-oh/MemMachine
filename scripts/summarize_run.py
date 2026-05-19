#!/usr/bin/env python3
"""Single-run analysis from a judge.jsonl: overall + per-category accuracy.

Reads one judge.jsonl, computes:
    - overall accuracy (mean llm_score)
    - per-category accuracy + sample count
    - sample-count breakdown of correct / wrong

Prints a compact text table to stdout and (optionally) writes a JSON
summary. No comparison — for that use scripts/compare_runs.py.

Usage:
    python scripts/summarize_run.py \
        --judge results/sclean_gen_failed/judge.jsonl \
        --out   results/sclean_gen_failed/summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.stages._common import read_jsonl  # noqa: E402


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    correct = sum(1 for r in rows if int(r.get("llm_score", 0) or 0) == 1)
    by_cat: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        cat = str(r.get("category", "unknown"))
        by_cat[cat].append(int(r.get("llm_score", 0) or 0))
    per_cat: dict[str, dict[str, Any]] = {}
    for cat in sorted(by_cat):
        scores = by_cat[cat]
        per_cat[cat] = {
            "n": len(scores),
            "correct": sum(scores),
            "wrong": len(scores) - sum(scores),
            "accuracy": (sum(scores) / len(scores)) if scores else None,
        }
    return {
        "n": n,
        "correct": correct,
        "wrong": n - correct,
        "accuracy": (correct / n) if n else None,
        "by_category": per_cat,
    }


def _print_table(summary: dict[str, Any]) -> None:
    cat_names = list(summary["by_category"])
    cat_w = max([28, *(len(c) for c in cat_names)])
    print()
    print("=" * (cat_w + 38))
    print("Single-run summary")
    print("=" * (cat_w + 38))
    print(f"{'category':<{cat_w}}  {'n':>5}  {'correct':>7}  {'wrong':>5}  {'acc':>6}")
    print("-" * (cat_w + 38))
    acc = summary["accuracy"]
    acc_str = f"{acc:.3f}" if acc is not None else "  -  "
    print(
        f"{'OVERALL':<{cat_w}}  "
        f"{summary['n']:>5}  {summary['correct']:>7}  "
        f"{summary['wrong']:>5}  {acc_str:>6}"
    )
    print("-" * (cat_w + 38))
    for cat, info in summary["by_category"].items():
        a = info["accuracy"]
        a_str = f"{a:.3f}" if a is not None else "  -  "
        print(
            f"{cat:<{cat_w}}  "
            f"{info['n']:>5}  {info['correct']:>7}  "
            f"{info['wrong']:>5}  {a_str:>6}"
        )
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--judge", required=True, help="Path to judge.jsonl.")
    p.add_argument("--out", default=None, help="Optional JSON output path.")
    args = p.parse_args()

    judge_path = Path(args.judge).resolve()
    rows = read_jsonl(judge_path)
    summary = _aggregate(rows)
    _print_table(summary)

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(
                {"judge": str(judge_path), "summary": summary},
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"[summarize_run] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
