#!/usr/bin/env python3
"""Filter a retrieve.jsonl down to rows the judge marked wrong (llm_score=0).

Reads retrieve.jsonl + judge.jsonl from the same (or specified) directory,
joins on (question_id, cell_idx), and writes a retrieve-shaped JSONL
containing only the failed rows. Other downstream stages
(regen_answer, judge, summarize_run) consume the output as a normal
retrieve.jsonl.

Usage:
    python scripts/filter_judge_failed.py \
        --retrieve results/sclean_full/retrieve.jsonl \
        --judge    results/sclean_full/judge.jsonl \
        --out      results/sclean_full/retrieve.failed.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.stages._common import read_jsonl, write_jsonl  # noqa: E402


def _key(row: dict) -> tuple[str, int]:
    return (str(row.get("question_id", "")), int(row.get("cell_idx", 0) or 0))


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--retrieve", required=True, help="Source retrieve.jsonl path.")
    p.add_argument(
        "--judge",
        default=None,
        help="judge.jsonl path. Default: <retrieve dir>/judge.jsonl",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path. Default: <retrieve dir>/retrieve.failed.jsonl",
    )
    args = p.parse_args()

    retrieve_path = Path(args.retrieve).resolve()
    judge_path = (
        Path(args.judge).resolve()
        if args.judge
        else retrieve_path.parent / "judge.jsonl"
    )
    out_path = (
        Path(args.out).resolve()
        if args.out
        else retrieve_path.parent / "retrieve.failed.jsonl"
    )
    if not judge_path.exists():
        raise SystemExit(f"judge.jsonl missing: {judge_path}")

    judge_rows = read_jsonl(judge_path)
    failed_keys = {_key(r) for r in judge_rows if int(r.get("llm_score", 0) or 0) == 0}

    retrieve_rows = read_jsonl(retrieve_path)
    kept = [r for r in retrieve_rows if _key(r) in failed_keys]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_written = write_jsonl(out_path, kept)
    print(
        f"[filter_judge_failed] {len(retrieve_rows)} retrieve rows; "
        f"{len(judge_rows)} judge rows; {len(failed_keys)} failed; "
        f"{n_written} kept -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
