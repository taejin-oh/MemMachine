#!/usr/bin/env python3
"""Measure how well a retrieve.jsonl recalls the oracle evidence per question.

For each question, two ground-truth fact sets are derived from
longmemeval_oracle.json:

    set A — all turns of every evidence session (has_answer True + False),
            passed through _split_chunks() for parity with ingest.
    set B — has_answer=True turns only (after the same chunk-splitting).

The system set is the bag of parsed line contents in `chunks_text` (one
`[<date> at <time>] <role>: <json.dumps(content)>` line per chunk). Matching
is **exact equality after whitespace normalization** on the parsed content
(no substring / token-overlap heuristics — those have known accuracy issues).

Outputs overall + per-category recall (A, B), plus distribution stats and a
per-question JSON record.

Usage:
    python scripts/analyze_sclean_recall.py \
        --retrieve results/sclean_full/retrieve.jsonl \
        --oracle evaluation/data/longmemeval_oracle.json \
        --out results/sclean_full/sclean_recall.json

    # Filter to specific question types
    python scripts/analyze_sclean_recall.py \
        --retrieve results/sclean_full/retrieve.jsonl \
        --include-categories temporal-reasoning,multi-session \
        --out results/sclean_full/sclean_recall_temporal_ms.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.retrieval_agent.longmemeval_test import (  # noqa: E402
    _collect_supporting_facts,
    _collect_turn_contents,
    _split_chunks,
)
from scripts.stages._common import read_jsonl  # noqa: E402

_LINE_SEP = "] user: "
_ALT_SEP = "] assistant: "


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_chunk_content(line: str) -> str | None:
    """Extract the post-`<role>: ` JSON-encoded content from one chunks_text line."""
    idx = line.find(_LINE_SEP)
    sep_len = len(_LINE_SEP)
    if idx < 0:
        idx = line.find(_ALT_SEP)
        sep_len = len(_ALT_SEP)
    if idx < 0:
        return None
    try:
        return json.loads(line[idx + sep_len :].strip())
    except json.JSONDecodeError:
        return None


def _system_contents(chunks_text: str) -> set[str]:
    out: set[str] = set()
    for line in (chunks_text or "").split("\n"):
        if not line.strip():
            continue
        content = _parse_chunk_content(line)
        if content is None:
            continue
        out.add(_norm(content))
    return out


def _oracle_facts_chunked(sample: dict[str, Any]) -> list[str]:
    """has_answer=True turn contents, _split_chunks-normalized for fairness."""
    out: list[str] = []
    for fact in _collect_supporting_facts(sample):
        out.extend(_split_chunks(fact))
    return out


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    vs = sorted(values)
    return {
        "n": len(vs),
        "mean": sum(vs) / len(vs),
        "min": vs[0],
        "p25": vs[max(0, int(0.25 * len(vs)) - 1)],
        "median": statistics.median(vs),
        "p75": vs[min(len(vs) - 1, int(0.75 * len(vs)))],
        "max": vs[-1],
    }


def _aggregate(per_q: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat_a: dict[str, list[float]] = defaultdict(list)
    by_cat_b: dict[str, list[float]] = defaultdict(list)
    all_a: list[float] = []
    all_b: list[float] = []
    skipped_a = 0
    skipped_b = 0
    for r in per_q:
        cat = r["category"]
        if r["recall_a"] is not None:
            by_cat_a[cat].append(r["recall_a"])
            all_a.append(r["recall_a"])
        else:
            skipped_a += 1
        if r["recall_b"] is not None:
            by_cat_b[cat].append(r["recall_b"])
            all_b.append(r["recall_b"])
        else:
            skipped_b += 1
    return {
        "overall": {
            "recall_a": _stats(all_a),
            "recall_b": _stats(all_b),
            "skipped_a_empty_gt": skipped_a,
            "skipped_b_empty_gt": skipped_b,
        },
        "by_category": {
            cat: {
                "recall_a": _stats(by_cat_a.get(cat, [])),
                "recall_b": _stats(by_cat_b.get(cat, [])),
            }
            for cat in sorted(set(by_cat_a) | set(by_cat_b))
        },
    }


def _print_summary(agg: dict[str, Any]) -> None:
    def _line(label: str, s: dict[str, float]) -> str:
        if s.get("n", 0) == 0:
            return f"{label:<32}  n=0"
        return (
            f"{label:<32}  n={s['n']:>3}  mean={s['mean']:.3f}  "
            f"min={s['min']:.3f}  p25={s['p25']:.3f}  med={s['median']:.3f}  "
            f"p75={s['p75']:.3f}  max={s['max']:.3f}"
        )

    print()
    print("=" * 110)
    print("Recall A (all evidence-session turns) — overall + per-category")
    print("=" * 110)
    print(_line("OVERALL", agg["overall"]["recall_a"]))
    print("-" * 110)
    for cat, info in agg["by_category"].items():
        print(_line(cat, info["recall_a"]))

    print()
    print("=" * 110)
    print("Recall B (has_answer=True turns only) — overall + per-category")
    print("=" * 110)
    print(_line("OVERALL", agg["overall"]["recall_b"]))
    print("-" * 110)
    for cat, info in agg["by_category"].items():
        print(_line(cat, info["recall_b"]))

    print()
    print(
        f"Note: questions with empty ground-truth fact set were skipped — "
        f"A: {agg['overall']['skipped_a_empty_gt']}, "
        f"B: {agg['overall']['skipped_b_empty_gt']}"
    )


def _per_question_recall(
    rows: list[dict[str, Any]], oracle_index: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        qid = str(row.get("question_id", ""))
        sample = oracle_index.get(qid)
        if sample is None:
            out.append(
                {
                    "question_id": qid,
                    "category": str(row.get("category", "unknown")),
                    "recall_a": None,
                    "recall_b": None,
                    "n_system_chunks": 0,
                    "skipped_reason": "qid_not_in_oracle",
                }
            )
            continue
        gt_a = {_norm(c) for c in _collect_turn_contents(sample)}
        gt_b = {_norm(c) for c in _oracle_facts_chunked(sample)}
        sys_set = _system_contents(str(row.get("chunks_text", "")))
        recall_a = (
            len(gt_a & sys_set) / len(gt_a) if gt_a else None
        )
        recall_b = (
            len(gt_b & sys_set) / len(gt_b) if gt_b else None
        )
        out.append(
            {
                "question_id": qid,
                "category": str(row.get("category", "unknown")),
                "recall_a": recall_a,
                "recall_b": recall_b,
                "n_gt_a": len(gt_a),
                "n_gt_b": len(gt_b),
                "n_system_chunks": len(sys_set),
                "n_hits_a": len(gt_a & sys_set),
                "n_hits_b": len(gt_b & sys_set),
            }
        )
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--retrieve",
        required=True,
        help="Path to retrieve.jsonl to analyze (typically a full s_cleaned run).",
    )
    p.add_argument(
        "--oracle",
        default="evaluation/data/longmemeval_oracle.json",
        help="Path to longmemeval_oracle.json (ground truth).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="JSON output path. Default: <retrieve dir>/sclean_recall.json",
    )
    p.add_argument(
        "--include-categories",
        default=None,
        help=(
            "Comma-separated question_type values to keep (e.g. "
            "'temporal-reasoning,multi-session'). Default: keep all."
        ),
    )
    args = p.parse_args()

    retrieve_path = Path(args.retrieve).resolve()
    oracle_path = Path(args.oracle).resolve()
    out_path = (
        Path(args.out).resolve()
        if args.out
        else retrieve_path.parent / "sclean_recall.json"
    )

    with open(oracle_path) as f:
        oracle = json.load(f)
    oracle_index = {str(x.get("question_id", "")): x for x in oracle}
    rows = read_jsonl(retrieve_path)

    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(rows)
        rows = [r for r in rows if str(r.get("category", "")) in keep]
        print(
            f"[analyze_sclean_recall] category filter "
            f"{sorted(keep)}: {before} -> {len(rows)} rows"
        )

    per_q = _per_question_recall(rows, oracle_index)
    agg = _aggregate(per_q)
    _print_summary(agg)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            {
                "retrieve": str(retrieve_path),
                "oracle": str(oracle_path),
                "n_questions": len(rows),
                "summary": agg,
                "per_question": per_q,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n[analyze_sclean_recall] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
