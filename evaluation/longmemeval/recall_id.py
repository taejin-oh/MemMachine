#!/usr/bin/env python3
"""LongMemEval — ID-based recall analyzer (upstream-aligned).

retrieve.jsonl 의 `retrieved_turn_ids` (= 매 retrieved Episode 의 metadata
에서 뽑은 `<haystack_session_id>:<turn_idx>` 리스트) 와 `gold_turn_ids`
(= oracle 의 has_answer=True turn 들의 같은 형식 ID 집합) 으로:

    recall_per_q = |pred ∩ gold| / |gold|

를 질문별로 계산하고 overall + 카테고리별 평균 출력. 또한 recall@k
곡선 (k = 1..max_topk) 도 함께 계산 가능 — `--curve`.

`evaluation/episodic_memory/longmemeval_models.py:91` 의
`answer_turn_indices` 정의와 byte-equal 한 형식 (`f"{sid}:{idx}"`) 을
씀으로써 upstream 의 ID 기반 retrieval evaluation 와 정렬.

Usage:
    uv run python -m evaluation.longmemeval.recall_id \\
        --retrieve results/lme_iso/retrieve.jsonl \\
        --out      results/lme_iso/recall_id.json

    # recall@k 곡선까지:
    uv run python -m evaluation.longmemeval.recall_id \\
        --retrieve results/lme_iso/retrieve.jsonl \\
        --curve \\
        --max-k 50
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _per_q_recall(row: dict[str, Any]) -> float | None:
    gold = {x for x in row.get("gold_turn_ids", []) or [] if x}
    if not gold:
        return None
    pred = {x for x in row.get("retrieved_turn_ids", []) or [] if x}
    return len(pred & gold) / len(gold)


def _recall_at_k(pred_ordered: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return float("nan")
    seen = set(pred_ordered[:k])
    return len(seen & gold) / len(gold)


def _summarize(retrieve_path: Path, out_path: Path | None, curve: bool, max_k: int) -> None:
    rows = _read_jsonl(retrieve_path)
    if not rows:
        print(f"[recall-id] no rows in {retrieve_path}", file=sys.stderr)
        return

    per_q: list[tuple[str, str, float]] = []
    skipped_no_gold = 0
    for r in rows:
        v = _per_q_recall(r)
        if v is None:
            skipped_no_gold += 1
            continue
        per_q.append(
            (
                str(r.get("question_id", "")),
                str(r.get("category", "")),
                v,
            )
        )

    if not per_q:
        print(
            "[recall-id] all rows had empty gold_turn_ids. "
            "Did you pass --oracle to retrieve.py? "
            "(s_cleaned/m_cleaned have no has_answer flag — gold needs oracle.)",
            file=sys.stderr,
        )
        return

    overall = mean(v for _, _, v in per_q)
    by_cat: dict[str, list[float]] = defaultdict(list)
    for _qid, cat, v in per_q:
        by_cat[cat].append(v)

    summary: dict[str, Any] = {
        "n_rows": len(rows),
        "n_scored": len(per_q),
        "n_skipped_no_gold": skipped_no_gold,
        "overall_recall": overall,
        "by_category": {
            cat: {"n": len(vs), "recall": mean(vs)} for cat, vs in by_cat.items()
        },
    }

    if curve:
        # Recall@k curve: averaged over questions with non-empty gold.
        curve_avgs: list[float] = []
        for k in range(1, max_k + 1):
            ks_vals: list[float] = []
            for r in rows:
                gold = {x for x in r.get("gold_turn_ids", []) or [] if x}
                if not gold:
                    continue
                pred_ordered = list(r.get("retrieved_turn_ids", []) or [])
                ks_vals.append(_recall_at_k(pred_ordered, gold, k))
            curve_avgs.append(mean(ks_vals) if ks_vals else float("nan"))
        summary["recall_at_k_overall"] = curve_avgs

    # Print human summary.
    print(f"[recall-id] rows={summary['n_rows']}  scored={summary['n_scored']}  "
          f"skipped_no_gold={summary['n_skipped_no_gold']}")
    print(f"[recall-id] overall recall = {overall:.4f}")
    print("[recall-id] by category:")
    for cat in sorted(by_cat):
        vs = by_cat[cat]
        print(f"  {cat:32}  n={len(vs):4d}  recall={mean(vs):.4f}")
    if curve:
        print("[recall-id] recall@k curve:")
        for k, v in enumerate(summary["recall_at_k_overall"], 1):
            print(f"  k={k:3d}  recall={v:.4f}")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"[recall-id] wrote -> {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--retrieve",
        required=True,
        help="retrieve.jsonl from evaluation.longmemeval.retrieve",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output JSON path. Default: <retrieve dir>/recall_id.json",
    )
    p.add_argument(
        "--curve",
        action="store_true",
        help="Compute recall@k curve for k=1..max-k",
    )
    p.add_argument(
        "--max-k",
        type=int,
        default=50,
        help="Max k for recall@k curve (default: 50). Only used with --curve.",
    )
    args = p.parse_args()

    retrieve_path = Path(args.retrieve).resolve()
    if not retrieve_path.exists():
        print(f"[recall-id] not found: {retrieve_path}", file=sys.stderr)
        return 1

    out_path: Path | None
    if args.out:
        out_path = Path(args.out).resolve()
    else:
        out_path = retrieve_path.parent / "recall_id.json"

    _summarize(retrieve_path, out_path, args.curve, args.max_k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
