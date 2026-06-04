#!/usr/bin/env python3
"""LongMemEval retrieve — per-question session 검색 (MemMachine 백엔드).

`evaluation/longmemeval/ingest.py` 가 먼저 돌아 `<prefix>_<question_id>`
session 에 데이터가 적재된 상태에서, 각 질문 별로 그 session 안에서 top-K
검색 → retrieve.jsonl (이 브랜치 schema) 출력.

ingest 와 분리되어 있어서 같은 데이터로 `--top-k` 만 바꿔 여러 번 돌릴 수
있다 (재-ingest 비용 0). 답변 LLM / judge 호출 없음.

본 모듈은 `evaluation/longmemeval/_common.py` 와 `memmachine_server.*` 만
import — `evaluation/retrieval_agent/`, `evaluation/utils/` 의존 없음.

Usage:
    uv run python -m evaluation.longmemeval.retrieve \\
        --in-file evaluation/data/longmemeval_s_cleaned.json \\
        --config-path configs/generated/<run>_configuration.yml \\
        --session-prefix lme_iso \\
        --top-k 50 \\
        --out results/lme_iso/retrieve.jsonl
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

from memmachine_server.common.episode_store.episode_model import (  # noqa: E402
    episodes_to_string,
)
from memmachine_server.retrieval_agent.common.agent_api import (  # noqa: E402
    QueryParam,
    QueryPolicy,
)

from evaluation.longmemeval._common import (  # noqa: E402
    build_memory_and_agent,
    collect_gold_turn_ids,
    collect_supporting_facts,
    load_eval_config,
    retrieved_turn_ids,
    set_safe_embedder_limits,
)


async def _retrieve_one(
    rm: Any,
    entry: dict,
    session_prefix: str,
    top_k: int,
    adaptive_k: bool = False,
    adaptive_min_k: int = 1,
    adaptive_max_k: int = 0,
    adaptive_bias: float = 0.0,
    expand_context: int = 0,
) -> dict[str, Any]:
    qid = str(entry.get("question_id", ""))
    session_id = f"{session_prefix}_{qid}"
    memory, query_agent = await build_memory_and_agent(rm, session_id)
    set_safe_embedder_limits(memory)

    question = str(entry.get("question", "")).strip()
    t0 = time.perf_counter()
    chunks, perf = await query_agent.do_query(
        QueryPolicy(
            token_cost=10,
            time_cost=10,
            accuracy_score=10,
            confidence_score=10,
            max_attempts=3,
            max_return_len=10000,
        ),
        QueryParam(
            query=question,
            limit=top_k,
            memory=memory,
            expand_context=expand_context,
            adaptive_k=adaptive_k,
            adaptive_k_min=adaptive_min_k,
            adaptive_k_max=adaptive_max_k,
            adaptive_k_bias=adaptive_bias,
        ),
    )
    latency = time.perf_counter() - t0

    gold_ids = collect_gold_turn_ids(entry)
    pred_ids = retrieved_turn_ids(chunks)

    return {
        "question": question,
        "question_id": qid,
        "category": str(entry.get("question_type", "")),
        "question_date": str(entry.get("question_date", "")),
        "golden_answer": str(entry.get("answer", "")),
        "sweep": {},
        "cell_idx": 0,
        "chunks_text": episodes_to_string(chunks),
        "num_episodes_retrieved": len(chunks),
        "expand_context": expand_context,
        "adaptive_k": perf.get("adaptive_k", False),
        "adaptive_pool": perf.get("adaptive_pool", 0),
        "adaptive_kept": perf.get("adaptive_kept", len(chunks)),
        "adaptive_bias": perf.get("adaptive_bias", 0.0),
        "adaptive_score_hi": perf.get("adaptive_score_hi"),
        "adaptive_score_cut": perf.get("adaptive_score_cut"),
        "retrieved_turn_ids": pred_ids,
        "gold_turn_ids": sorted(gold_ids),
        "memory_retrieval_time": perf.get("memory_retrieval_time", latency),
        "memory_search_called": perf.get("memory_search_called", 1),
        "agent": perf.get("agent", "lme_iso"),
        "selected_tool": perf.get("selected_tool", "lme_iso"),
        "supporting_facts": collect_supporting_facts(entry),
        "input_token": perf.get("input_token", 0),
        "output_token": perf.get("output_token", 0),
        "tool_select_input_token": perf.get("tool_select_input_token", 0),
        "tool_select_output_token": perf.get("tool_select_output_token", 0),
        "fact_hits": [],
        "fact_miss": [],
    }


async def _run(args: argparse.Namespace) -> None:
    with open(args.in_file) as f:
        entry_list = json.load(f)

    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(entry_list)
        entry_list = [
            e for e in entry_list if str(e.get("question_type", "")) in keep
        ]
        print(
            f"[lme-retrieve] category filter {sorted(keep)}: "
            f"{before} -> {len(entry_list)}"
        )
    if args.limit is not None:
        entry_list = entry_list[: args.limit]

    rm = load_eval_config(args.config_path)
    out_path = args.out_path  # resolved in main() before asyncio.run

    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict[str, Any] | None] = [None] * len(entry_list)

    async def _one(entry: dict, idx: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            rows[idx] = await _retrieve_one(
                rm,
                entry,
                args.session_prefix,
                args.top_k,
                adaptive_k=args.adaptive_k,
                adaptive_min_k=args.adaptive_min_k,
                adaptive_max_k=args.adaptive_max_k,
                adaptive_bias=args.adaptive_bias,
                expand_context=args.expand_context,
            )
            dt = time.perf_counter() - t0
            print(
                f"[lme-retrieve] {idx + 1}/{len(entry_list)}  "
                f"qid={entry.get('question_id', '')}  "
                f"chunks={rows[idx]['num_episodes_retrieved']}  t={dt:.1f}s"
            )

    await asyncio.gather(
        *[_one(e, i) for i, e in enumerate(entry_list)]
    )

    with open(out_path, "w") as f:
        for row in rows:
            if row is not None:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        f"[lme-retrieve] wrote {sum(r is not None for r in rows)} rows -> {out_path}"
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--in-file", required=True, help="longmemeval_*.json")
    p.add_argument(
        "--config-path",
        required=True,
        help="Working configuration.yml (from scripts/generate_config.py)",
    )
    p.add_argument(
        "--session-prefix",
        default="lme_iso",
        help="Must match the prefix used at ingest. Default: lme_iso",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=50,
        help=(
            "Retrieved chunks per question (default: 50). With --adaptive-k"
            " this is the candidate pool the gap-cut chooses from."
        ),
    )
    p.add_argument(
        "--adaptive-k",
        action="store_true",
        help=(
            "Enable Adaptive-k retrieval: keep only the prefix before the"
            " largest score gap in the top-k candidate pool, instead of a"
            " fixed top-k (Taguchi et al., EMNLP 2025)."
        ),
    )
    p.add_argument(
        "--adaptive-min-k",
        type=int,
        default=1,
        help="Adaptive-k floor on chunks kept (default: 1).",
    )
    p.add_argument(
        "--adaptive-max-k",
        type=int,
        default=0,
        help="Adaptive-k ceiling on chunks kept (default: 0 = top-k pool).",
    )
    p.add_argument(
        "--adaptive-bias",
        type=float,
        default=0.0,
        help=(
            "Adaptive-k cut aggressiveness (default: 0.0 = plain largest-gap,"
            " most aggressive). Higher (e.g. 0.5-2.0) weights gaps by k**bias"
            " so the cut happens later — keeps more chunks, higher recall."
        ),
    )
    p.add_argument(
        "--expand-context",
        type=int,
        default=0,
        help=(
            "Pull neighbour turns around each matched turn (default: 0 = none)."
            " Split ~1/3 backward, ~2/3 forward: e.g. 3 -> 1 before + 2 after."
            " Neighbours count against --top-k (the candidate pool)."
        ),
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output retrieve.jsonl path (this-branch schema)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-categories", default=None)
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight question queries (default: 4).",
    )
    args = p.parse_args()
    args.out_path = Path(args.out).resolve()
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
