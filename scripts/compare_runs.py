#!/usr/bin/env python3
"""Side-by-side comparison of N evaluation runs (accuracy + chunk stats).

Each run directory must contain:
    retrieve.jsonl   (rows with `category`, `num_episodes_retrieved`,
                      `supporting_facts`)
    analyze.json     (cells[0].accuracy + .by_category[cat].accuracy)

Reads accuracy from analyze.json (already aggregated by analyze stage) and
recomputes per-category chunk totals + has_answer counts from retrieve.jsonl.
Prints a side-by-side table with Δ-vs-baseline columns.

Use cases:
    - Oracle ceiling: compare full vs facts-only oracle runs.
    - Position experiment: compare front/middle/end variants.
    - Any N-way A/B over the eval pipeline.

Usage:
    python scripts/compare_runs.py \
        --runs results/oracle_full results/oracle_facts \
        --labels "Full (T+F)" "Facts only" \
        --out results/oracle_ceiling_compare.json

    python scripts/compare_runs.py \
        --runs results/run_front results/run_middle results/run_end \
        --labels front middle end \
        --baseline 0
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


def _load_analyze(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "analyze.json"
    if not path.exists():
        raise FileNotFoundError(f"missing analyze.json: {path}")
    with open(path) as f:
        data = json.load(f)
    cells = data.get("cells") or []
    if not cells:
        raise ValueError(f"analyze.json has no cells: {path}")
    return cells[0]


def _chunk_stats(retrieve_path: Path) -> dict[str, Any]:
    """Per-category mean chunks_total + mean has_answer=True count."""
    rows = read_jsonl(retrieve_path)
    if not rows:
        raise ValueError(f"empty retrieve.jsonl: {retrieve_path}")
    totals: dict[str, list[int]] = defaultdict(list)
    facts: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        cat = str(r.get("category", "unknown"))
        totals[cat].append(int(r.get("num_episodes_retrieved", 0) or 0))
        facts[cat].append(len(r.get("supporting_facts") or []))
    out: dict[str, Any] = {"n": len(rows), "by_category": {}}
    all_totals: list[int] = []
    all_facts: list[int] = []
    for cat in sorted(totals):
        ct = totals[cat]
        cf = facts[cat]
        out["by_category"][cat] = {
            "n": len(ct),
            "mean_chunks": sum(ct) / len(ct),
            "mean_supporting_facts": sum(cf) / len(cf),
        }
        all_totals.extend(ct)
        all_facts.extend(cf)
    out["overall"] = {
        "mean_chunks": sum(all_totals) / len(all_totals) if all_totals else 0.0,
        "mean_supporting_facts": sum(all_facts) / len(all_facts) if all_facts else 0.0,
    }
    return out


def _gather(run_dir: Path) -> dict[str, Any]:
    cell = _load_analyze(run_dir)
    chunks = _chunk_stats(run_dir / "retrieve.jsonl")
    return {
        "run_dir": str(run_dir),
        "n_judged": int(cell.get("n", 0)),
        "overall_accuracy": cell.get("accuracy"),
        "by_category_acc": {
            cat: info.get("accuracy")
            for cat, info in (cell.get("by_category") or {}).items()
        },
        "by_category_n": {
            cat: int(info.get("n", 0))
            for cat, info in (cell.get("by_category") or {}).items()
        },
        "chunks": chunks,
    }


def _fmt_acc(v: float | None) -> str:
    return "  -  " if v is None else f"{v:.3f}"


def _fmt_diff(v: float | None, base: float | None) -> str:
    if v is None or base is None:
        return "  -  "
    d = v - base
    sign = "+" if d >= 0 else "-"
    return f"{sign}{abs(d):.3f}"


def _print_table(reports: list[dict[str, Any]], labels: list[str], baseline: int) -> None:
    n = len(reports)
    base = reports[baseline]

    # categories: union of all by_category keys + overall
    cats = sorted({c for r in reports for c in r["by_category_acc"]})

    # column widths
    label_w = max(11, max(len(label) for label in labels))
    cat_w = max(28, max(len(c) for c in cats) if cats else 28)

    # Header
    print()
    print("=" * (cat_w + (label_w + 10) * n))
    print("Accuracy comparison")
    print("=" * (cat_w + (label_w + 10) * n))
    head = f"{'category':<{cat_w}}"
    for i, label in enumerate(labels):
        col = label if i == baseline else f"{label} (Δ)"
        head += f"  {col:>{label_w + 8}}"
    print(head)
    print("-" * (cat_w + (label_w + 10) * n))

    def _row(name: str, key: str, n_key: str | None = None) -> None:
        line = f"{name:<{cat_w}}"
        base_v = base["by_category_acc"].get(key) if key != "__overall__" else base["overall_accuracy"]
        for i, r in enumerate(reports):
            v = (
                r["overall_accuracy"]
                if key == "__overall__"
                else r["by_category_acc"].get(key)
            )
            n_disp = (
                r["n_judged"]
                if key == "__overall__"
                else r["by_category_n"].get(key, 0)
            )
            if i == baseline:
                cell_txt = f"{_fmt_acc(v)} (n={n_disp})"
            else:
                cell_txt = f"{_fmt_acc(v)} {_fmt_diff(v, base_v)}"
            line += f"  {cell_txt:>{label_w + 8}}"
        print(line)

    _row("OVERALL", "__overall__")
    print("-" * (cat_w + (label_w + 10) * n))
    for cat in cats:
        _row(cat, cat)

    # Chunk stats
    print()
    print("=" * (cat_w + (label_w + 10) * n))
    print("Chunks per question  (mean_chunks_total / mean_supporting_facts)")
    print("=" * (cat_w + (label_w + 10) * n))
    head = f"{'category':<{cat_w}}"
    for label in labels:
        head += f"  {label:>{label_w + 8}}"
    print(head)
    print("-" * (cat_w + (label_w + 10) * n))

    def _chunk_row(name: str, key: str) -> None:
        line = f"{name:<{cat_w}}"
        for r in reports:
            if key == "__overall__":
                t = r["chunks"]["overall"]["mean_chunks"]
                f = r["chunks"]["overall"]["mean_supporting_facts"]
            else:
                info = r["chunks"]["by_category"].get(key)
                if info is None:
                    line += f"  {'  -  ':>{label_w + 8}}"
                    continue
                t = info["mean_chunks"]
                f = info["mean_supporting_facts"]
            cell_txt = f"{t:5.1f} / {f:4.2f}"
            line += f"  {cell_txt:>{label_w + 8}}"
        print(line)

    _chunk_row("OVERALL", "__overall__")
    print("-" * (cat_w + (label_w + 10) * n))
    chunk_cats = sorted({c for r in reports for c in r["chunks"]["by_category"]})
    for cat in chunk_cats:
        _chunk_row(cat, cat)
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--runs",
        nargs="+",
        required=True,
        help="Run directories (each containing retrieve.jsonl + analyze.json).",
    )
    p.add_argument(
        "--labels",
        nargs="+",
        default=None,
        help="Column labels (default: directory basename).",
    )
    p.add_argument(
        "--baseline",
        type=int,
        default=0,
        help="Index of baseline run (Δ columns are relative to this). Default: 0.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Optional JSON output path for the comparison report.",
    )
    args = p.parse_args()

    run_dirs = [Path(d).resolve() for d in args.runs]
    labels = args.labels or [d.name for d in run_dirs]
    if len(labels) != len(run_dirs):
        raise SystemExit(
            f"--labels count ({len(labels)}) must equal --runs count ({len(run_dirs)})"
        )
    if not 0 <= args.baseline < len(run_dirs):
        raise SystemExit(f"--baseline {args.baseline} out of range")

    reports = [_gather(d) for d in run_dirs]
    _print_table(reports, labels, args.baseline)

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(
                {
                    "labels": labels,
                    "baseline_idx": args.baseline,
                    "runs": reports,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"[compare_runs] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
