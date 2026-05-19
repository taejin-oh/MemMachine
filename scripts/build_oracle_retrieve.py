#!/usr/bin/env python3
"""Build retrieve.jsonl from longmemeval_oracle.json (skip memmachine ingest).

Output rows mirror scripts/stages/retrieve.py:_split_record() so that
regen_answer.py + judge + analyze stages consume the file unchanged.
chunks_text matches the live format from
common.episode_store.episode_model.episodes_to_string(), with synthetic
"now + N seconds" timestamps mirroring longmemeval_test._async_ingest()
(producer_id is "user" for every turn, matching real ingest).

Usage:
    python scripts/build_oracle_retrieve.py \
        --oracle evaluation/data/longmemeval_oracle.json \
        --out results/oracle_run/retrieve.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.retrieval_agent.longmemeval_test import (  # noqa: E402
    _collect_supporting_facts,
    _split_chunks,
)


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%A, %B %d, %Y")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p")


def _build_chunks_text(sample: dict[str, Any], start_dt: datetime) -> tuple[str, int]:
    lines: list[str] = []
    n = 0
    for session in sample.get("haystack_sessions", []) or []:
        for turn in session or []:
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            for chunk in _split_chunks(content):
                n += 1
                ts = start_dt + timedelta(seconds=n)
                lines.append(
                    f"[{_fmt_date(ts)} at {_fmt_time(ts)}] "
                    f"user: {json.dumps(chunk)}\n"
                )
    return "".join(lines), n


def _row_for_sample(sample: dict[str, Any], start_dt: datetime) -> dict[str, Any]:
    chunks_text, n = _build_chunks_text(sample, start_dt)
    return {
        "question": str(sample.get("question", "")),
        "category": str(sample.get("question_type", "")),
        "sweep": {},
        "question_id": str(sample.get("question_id", "")),
        "chunks_text": chunks_text,
        "num_episodes_retrieved": n,
        "memory_retrieval_time": 0.0,
        "memory_search_called": 0,
        "agent": "oracle",
        "selected_tool": "oracle",
        "supporting_facts": _collect_supporting_facts(sample),
        "input_token": 0,
        "output_token": 0,
        "tool_select_input_token": 0,
        "tool_select_output_token": 0,
        "fact_hits": [],
        "fact_miss": [],
        "cell_idx": 0,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--oracle",
        default="evaluation/data/longmemeval_oracle.json",
        help="Path to longmemeval_oracle.json.",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output retrieve.jsonl path (parent dirs are created).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N samples (smoke-test).",
    )
    args = p.parse_args()

    oracle_path = Path(args.oracle).resolve()
    out_path = Path(args.out).resolve()

    with open(oracle_path) as f:
        dataset = json.load(f)
    if args.limit is not None:
        dataset = dataset[: args.limit]

    start_dt = datetime.now(UTC)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    with open(out_path, "w") as f:
        for sample in dataset:
            row = _row_for_sample(sample, start_dt)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"[build_oracle_retrieve] wrote {n_written} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
