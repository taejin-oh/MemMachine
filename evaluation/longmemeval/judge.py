#!/usr/bin/env python3
"""LongMemEval judge — upstream-verbatim `get_anscheck_prompt`.

`generate.jsonl` 의 각 row 에 대해 upstream LongMemEval 의 task-별
judge prompt 5종 (single-session-{user,assistant,preference},
temporal-reasoning, knowledge-update, multi-session + abstention) 을
그대로 사용해 judge LLM 호출 → 'yes' 포함 여부 (lenient) 로 llm_score
판정 → `judge.jsonl` 출력 + 마지막에 overall + 카테고리별 정확도 요약.

본 모듈은 `evaluation/longmemeval/_common.py` 와 stdlib 만 import —
`evaluation/retrieval_agent/`, `evaluation/utils/`, `scripts/` 의존 없음.

Usage:
    uv run python -m evaluation.longmemeval.judge \\
        --generate results/lme_iso/generate.jsonl \\
        --config-path configs/generated/<run>_configuration.yml \\
        --out results/lme_iso/judge.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.longmemeval._common import (  # noqa: E402
    get_anscheck_prompt,
    get_judge_llm,
    load_eval_config,
    parse_yes_no_lenient,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


async def _judge_one(row: dict[str, Any], judge_llm: Any) -> dict[str, Any]:
    qid = str(row.get("question_id", ""))
    qtype = str(row.get("category", "")) or "unknown"
    abstention = qid.endswith("_abs")
    prompt = get_anscheck_prompt(
        qtype,
        str(row.get("question", "")),
        str(row.get("golden_answer", "")),
        str(row.get("model_answer", "")),
        abstention=abstention,
    )
    t0 = time.perf_counter()
    rsp_text, _ = await judge_llm.generate_response(user_prompt=prompt)
    dt = time.perf_counter() - t0
    label = parse_yes_no_lenient(rsp_text)
    out = dict(row)
    out["llm_score"] = 1 if label else 0
    out["judge_raw_response"] = rsp_text
    out["judge_parsed_label"] = "yes" if label else "no"
    out["judge_time"] = dt
    return out


def _print_summary(rows: list[dict[str, Any]]) -> None:
    n = len(rows)
    if n == 0:
        print("[lme-judge] no rows.")
        return
    correct = sum(1 for r in rows if int(r.get("llm_score", 0) or 0) == 1)
    by_cat: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        cat = str(r.get("category", "")) or "unknown"
        by_cat[cat].append(int(r.get("llm_score", 0) or 0))
    cat_w = max(28, *(len(c) for c in by_cat))
    print()
    print("=" * (cat_w + 38))
    print("Judge summary")
    print("=" * (cat_w + 38))
    print(
        f"{'category':<{cat_w}}  {'n':>5}  {'correct':>7}  {'wrong':>5}  {'acc':>6}"
    )
    print("-" * (cat_w + 38))
    print(
        f"{'OVERALL':<{cat_w}}  {n:>5}  {correct:>7}  "
        f"{n - correct:>5}  {correct / n:>6.3f}"
    )
    print("-" * (cat_w + 38))
    for cat in sorted(by_cat):
        scores = by_cat[cat]
        acc = statistics.mean(scores) if scores else 0.0
        print(
            f"{cat:<{cat_w}}  {len(scores):>5}  {sum(scores):>7}  "
            f"{len(scores) - sum(scores):>5}  {acc:>6.3f}"
        )
    print()


async def _run(args: argparse.Namespace) -> None:
    rows = _read_jsonl(Path(args.generate))
    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(rows)
        rows = [r for r in rows if str(r.get("category", "")) in keep]
        print(
            f"[lme-judge] category filter {sorted(keep)}: "
            f"{before} -> {len(rows)}"
        )
    if args.limit is not None:
        rows = rows[: args.limit]

    rm = load_eval_config(args.config_path)
    judge_llm = await get_judge_llm(rm)
    print(f"[lme-judge] n={len(rows)}  concurrency={args.concurrency}")

    sem = asyncio.Semaphore(args.concurrency)
    out_rows: list[dict[str, Any] | None] = [None] * len(rows)

    async def _one(row: dict[str, Any], idx: int) -> None:
        async with sem:
            out_rows[idx] = await _judge_one(row, judge_llm)
            print(
                f"[lme-judge] {idx + 1}/{len(rows)}  "
                f"qid={row.get('question_id', '')}  "
                f"score={out_rows[idx]['llm_score']}  "
                f"t={out_rows[idx]['judge_time']:.1f}s"
            )

    await asyncio.gather(*[_one(r, i) for i, r in enumerate(rows)])

    out_path = args.out_path
    written = [r for r in out_rows if r is not None]
    with open(out_path, "w") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in written)
    print(f"[lme-judge] wrote {len(written)} rows -> {out_path}")

    _print_summary(written)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--generate", required=True, help="generate.jsonl from generate.py")
    p.add_argument(
        "--config-path",
        required=True,
        help="Working configuration.yml (from scripts/generate_config.py)",
    )
    p.add_argument("--out", required=True, help="Output judge.jsonl path")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-categories", default=None)
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight judge-LLM calls (default: 4).",
    )
    args = p.parse_args()
    args.out_path = Path(args.out).resolve()
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
