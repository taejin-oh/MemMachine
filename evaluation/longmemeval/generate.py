#!/usr/bin/env python3
"""LongMemEval generate — answer LLM 호출 (upstream-aligned prompt).

`retrieve.jsonl` 의 각 row 에 대해 upstream LongMemEval 의 답변 prompt
(LME_origin_prompt 또는 LME_origin_cot_prompt) 를 그대로 사용해 answer
LLM 을 호출하고 `generate.jsonl` 을 출력.

본 모듈은 `evaluation/longmemeval/_common.py` 와 `memmachine_server.*` 만
import — `evaluation/retrieval_agent/`, `evaluation/utils/`, `scripts/` 의존 없음.

Upstream 의 prompt 는 `_common.ANSWER_PROMPTS` 에 verbatim 으로 들어가
있고, 기본은 `LME_origin_prompt`. CoT 변종을 쓰려면
`--answer-prompt LME_origin_cot_prompt`.

Usage:
    uv run python -m evaluation.longmemeval.generate \\
        --retrieve results/lme_iso/retrieve.jsonl \\
        --config-path configs/generated/<run>_configuration.yml \\
        --out results/lme_iso/generate.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.longmemeval._common import (  # noqa: E402
    ANSWER_PROMPTS,
    get_answer_llm,
    load_eval_config,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


async def _generate_one(
    row: dict[str, Any],
    answer_llm: Any,
    prompt_template: str,
) -> dict[str, Any]:
    question = str(row.get("question", "")).strip()
    chunks_text = str(row.get("chunks_text", ""))
    question_date = str(row.get("question_date", ""))
    prompt = prompt_template.format(
        memories=chunks_text,
        question_date=question_date,
        question=question,
    )
    t0 = time.perf_counter()
    rsp_text, _ = await answer_llm.generate_response(user_prompt=prompt)
    latency = time.perf_counter() - t0
    return {
        "question": question,
        "question_id": str(row.get("question_id", "")),
        "category": str(row.get("category", "")),
        "question_date": question_date,
        "sweep": row.get("sweep", {}),
        "cell_idx": row.get("cell_idx", 0),
        "golden_answer": str(row.get("golden_answer", "")),
        "model_answer": rsp_text,
        "llm_time": latency,
    }


async def _run(args: argparse.Namespace) -> None:
    if args.answer_prompt not in ANSWER_PROMPTS:
        raise SystemExit(
            f"Unknown --answer-prompt {args.answer_prompt!r}. "
            f"Available: {sorted(ANSWER_PROMPTS)}"
        )
    prompt_template = ANSWER_PROMPTS[args.answer_prompt]

    rows = _read_jsonl(Path(args.retrieve))
    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(rows)
        rows = [r for r in rows if str(r.get("category", "")) in keep]
        print(
            f"[lme-generate] category filter {sorted(keep)}: "
            f"{before} -> {len(rows)}"
        )
    if args.limit is not None:
        rows = rows[: args.limit]

    rm = load_eval_config(args.config_path)
    answer_llm = await get_answer_llm(rm)
    print(
        f"[lme-generate] policy={args.answer_prompt}  n={len(rows)}  "
        f"concurrency={args.concurrency}"
    )

    sem = asyncio.Semaphore(args.concurrency)
    out_rows: list[dict[str, Any] | None] = [None] * len(rows)

    async def _one(row: dict[str, Any], idx: int) -> None:
        async with sem:
            out_rows[idx] = await _generate_one(row, answer_llm, prompt_template)
            print(
                f"[lme-generate] {idx + 1}/{len(rows)}  "
                f"qid={row.get('question_id', '')}  "
                f"t={out_rows[idx]['llm_time']:.1f}s"
            )

    await asyncio.gather(*[_one(r, i) for i, r in enumerate(rows)])

    out_path = args.out_path
    with open(out_path, "w") as f:
        for r in out_rows:
            if r is not None:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(
        f"[lme-generate] wrote {sum(r is not None for r in out_rows)} rows -> {out_path}"
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--retrieve", required=True, help="retrieve.jsonl from retrieve.py")
    p.add_argument(
        "--config-path",
        required=True,
        help="Working configuration.yml (from scripts/generate_config.py)",
    )
    p.add_argument("--out", required=True, help="Output generate.jsonl path")
    p.add_argument(
        "--answer-prompt",
        default="LME_origin_prompt",
        choices=sorted(ANSWER_PROMPTS),
        help=(
            "Upstream prompt variant (default: LME_origin_prompt). "
            "Use LME_origin_cot_prompt for chain-of-thought."
        ),
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-categories", default=None)
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight answer-LLM calls (default: 4).",
    )
    args = p.parse_args()
    args.out_path = Path(args.out).resolve()
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
