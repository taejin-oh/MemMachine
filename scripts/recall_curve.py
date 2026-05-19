#!/usr/bin/env python3
"""Compute supporting_facts recall@k for each row, aggregated overall + per-category.

For each row of retrieve.jsonl, chunks_text contains up to N retrieved lines
(N = row's num_episodes_retrieved). The recall@k for k=1..N is computed
against the row's supporting_facts, where matching uses the piece-level
exact match (each supporting_fact is split via _split_chunks() and every
piece must appear as some parsed chunks_text line). Rows with empty
supporting_facts are skipped (no signal).

Aggregation: mean recall@k across rows for overall and each category.
When a row has fewer chunks than k, recall@k for that row is held at
recall@N (the curve plateaus once the row is exhausted).

Output JSON shape:
    {
      "max_k": int,
      "n_rows": int,
      "overall": [r1, r2, ..., r_maxk],
      "by_category": {"<cat>": [...], ...},
      "counts": {"overall": int, "by_category": {"<cat>": int, ...}}
    }

Usage:
    python scripts/recall_curve.py \
        --retrieve results/<my_run>/retrieve.jsonl \
        --out      results/<my_run>/recall_curve.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.retrieval_agent.longmemeval_test import _split_chunks  # noqa: E402
from scripts.stages._common import read_jsonl  # noqa: E402

_LINE_SEP = "] user: "
_ALT_SEP = "] assistant: "


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_chunk_content(line: str) -> str | None:
    for sep in (_LINE_SEP, _ALT_SEP):
        idx = line.find(sep)
        if idx >= 0:
            try:
                return json.loads(line[idx + len(sep) :].strip())
            except json.JSONDecodeError:
                return None
    return None


def _ordered_chunk_norms(chunks_text: str) -> list[str]:
    out: list[str] = []
    for line in (chunks_text or "").split("\n"):
        if not line.strip():
            continue
        c = _parse_chunk_content(line)
        if c is not None:
            out.append(_norm(c))
    return out


def _per_row_curve(
    chunks_text: str, supporting_facts: list[str]
) -> list[float] | None:
    """Return [recall@1, recall@2, ..., recall@N] for one row, or None to skip.

    Granularity is FACT-level (matches Edwin's turn-level recall): a fact is
    "recalled" iff at least one of its _split_chunks() pieces appears in
    chunks_text. A long fact split into multiple pieces still counts as 1
    recall hit when any piece is found.
    """
    if not supporting_facts:
        return None  # abstention or empty supporting_facts -> skip
    # piece -> fact_idx (first fact wins on duplicate piece strings)
    piece_to_fact: dict[str, int] = {}
    for idx, fact in enumerate(supporting_facts):
        for piece in _split_chunks(fact):
            piece_to_fact.setdefault(_norm(piece), idx)
    if not piece_to_fact:
        return None  # all facts blank
    n_facts = len(supporting_facts)
    ordered = _ordered_chunk_norms(chunks_text)
    hit_facts: set[int] = set()
    curve: list[float] = []
    for chunk in ordered:
        idx = piece_to_fact.get(chunk)
        if idx is not None:
            hit_facts.add(idx)
        curve.append(len(hit_facts) / n_facts)
    return curve


def _value_at_k(curve: list[float], k: int) -> float:
    """recall@k with plateau: if k > len(curve), use the last value."""
    if not curve:
        return 0.0
    if k <= len(curve):
        return curve[k - 1]
    return curve[-1]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--retrieve", required=True, help="Source retrieve.jsonl path.")
    p.add_argument(
        "--out",
        default=None,
        help="Output JSON path. Default: <retrieve dir>/recall_curve.json",
    )
    p.add_argument(
        "--max-k",
        type=int,
        default=None,
        help="Cap k at this value (default: max across rows).",
    )
    p.add_argument(
        "--include-categories",
        default=None,
        help="Comma-separated question_type values to keep. Default: keep all.",
    )
    args = p.parse_args()

    src = Path(args.retrieve).resolve()
    out_path = (
        Path(args.out).resolve()
        if args.out
        else src.parent / "recall_curve.json"
    )

    rows = read_jsonl(src)
    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(rows)
        rows = [r for r in rows if str(r.get("category", "")) in keep]
        print(
            f"[recall_curve] category filter {sorted(keep)}: "
            f"{before} -> {len(rows)} rows"
        )

    per_row: list[tuple[str, list[float]]] = []  # (category, curve)
    skipped_empty = 0
    for row in rows:
        sf = row.get("supporting_facts") or []
        curve = _per_row_curve(str(row.get("chunks_text", "")), sf)
        if curve is None:
            skipped_empty += 1
            continue
        per_row.append((str(row.get("category", "unknown")), curve))

    if not per_row:
        raise SystemExit("[recall_curve] no rows with supporting_facts after filter.")

    observed_max = max(len(c) for _, c in per_row)
    max_k = min(args.max_k, observed_max) if args.max_k else observed_max

    by_cat: dict[str, list[list[float]]] = defaultdict(list)
    for cat, curve in per_row:
        by_cat[cat].append(curve)

    def _aggregate(curves: list[list[float]]) -> list[float]:
        return [
            sum(_value_at_k(c, k) for c in curves) / len(curves)
            for k in range(1, max_k + 1)
        ]

    overall_curve = _aggregate([c for _, c in per_row])
    by_cat_curve = {cat: _aggregate(curves) for cat, curves in by_cat.items()}

    summary = {
        "retrieve": str(src),
        "max_k": max_k,
        "n_rows": len(per_row),
        "skipped_empty_supporting_facts": skipped_empty,
        "overall": overall_curve,
        "by_category": by_cat_curve,
        "counts": {
            "overall": len(per_row),
            "by_category": {cat: len(curves) for cat, curves in by_cat.items()},
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(
        f"[recall_curve] n={len(per_row)} rows  max_k={max_k}  "
        f"skipped_empty_sf={skipped_empty}"
    )
    print(
        f"[recall_curve] overall recall@1={overall_curve[0]:.3f}  "
        f"recall@5={_value_at_k(overall_curve, 5):.3f}  "
        f"recall@10={_value_at_k(overall_curve, 10):.3f}  "
        f"recall@{max_k}={overall_curve[-1]:.3f}"
    )
    print(f"[recall_curve] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
