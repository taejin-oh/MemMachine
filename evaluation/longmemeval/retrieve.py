#!/usr/bin/env python3
"""LongMemEval retrieve — per-question session_id isolation (MemMachine backend).

Pairs with evaluation/longmemeval/ingest.py. For each question, opens a
MemMachine memory scoped to `<prefix>_<question_id>`, runs the retrieval
agent, and emits one retrieve.jsonl row in this branch's pipeline schema.
The retrieve.jsonl is consumed by every existing analysis tool
(scripts/recall_curve.py, scripts/plot_recall_curve.py, etc.) unchanged.

No answer-LLM call, no judge — pure retrieval. Run scripts/regen_answer.py
later if you want accuracy on top.

Usage:
    uv run python -m evaluation.longmemeval.retrieve \\
        --data-path evaluation/data/longmemeval_s_cleaned.json \\
        --config-path configs/generated/<run>_configuration.yml \\
        --top-k 50 \\
        --session-prefix lme_iso \\
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

from evaluation.retrieval_agent.longmemeval_test import (  # noqa: E402
    _collect_supporting_facts,
    _set_safe_embedder_request_limits,
)
from evaluation.utils import agent_utils  # noqa: E402


async def _retrieve_one(
    rm,
    sample: dict,
    session_prefix: str,
    top_k: int,
) -> dict[str, Any]:
    qid = str(sample.get("question_id", ""))
    session_id = f"{session_prefix}_{qid}"
    memory, _, query_agent = await agent_utils.init_memmachine_params(
        resource_manager=rm,
        session_id=session_id,
        agent_name="MemMachineAgent",
    )
    _set_safe_embedder_request_limits(memory)

    question = str(sample.get("question", "")).strip()
    t0 = time.perf_counter()
    chunks, perf_metrics = await query_agent.do_query(
        QueryPolicy(
            token_cost=10,
            time_cost=10,
            accuracy_score=10,
            confidence_score=10,
            max_attempts=3,
            max_return_len=10000,
        ),
        QueryParam(query=question, limit=top_k, memory=memory),
    )
    latency = time.perf_counter() - t0

    chunks_text = episodes_to_string(chunks)
    row = {
        "question": question,
        "question_id": qid,
        "category": str(sample.get("question_type", "")),
        "sweep": {},
        "cell_idx": 0,
        "chunks_text": chunks_text,
        "num_episodes_retrieved": len(chunks),
        "memory_retrieval_time": perf_metrics.get(
            "memory_retrieval_time", latency
        ),
        "memory_search_called": perf_metrics.get("memory_search_called", 1),
        "agent": perf_metrics.get("agent", "lme_iso"),
        "selected_tool": perf_metrics.get("selected_tool", "lme_iso"),
        "supporting_facts": _collect_supporting_facts(sample),
        "input_token": perf_metrics.get("input_token", 0),
        "output_token": perf_metrics.get("output_token", 0),
        "tool_select_input_token": perf_metrics.get(
            "tool_select_input_token", 0
        ),
        "tool_select_output_token": perf_metrics.get(
            "tool_select_output_token", 0
        ),
        "fact_hits": [],
        "fact_miss": [],
    }
    return row


async def _retrieve_all(
    data_path: str,
    config_path: str,
    session_prefix: str,
    top_k: int,
    out_path: Path,
    limit: int | None,
    include_categories: str | None,
    concurrency: int,
) -> None:
    with open(data_path) as f:
        dataset = json.load(f)
    if include_categories:
        keep = {c.strip() for c in include_categories.split(",") if c.strip()}
        before = len(dataset)
        dataset = [s for s in dataset if str(s.get("question_type", "")) in keep]
        print(
            f"[lme-retrieve] category filter {sorted(keep)}: "
            f"{before} -> {len(dataset)}"
        )
    if limit is not None:
        dataset = dataset[:limit]

    rm = agent_utils.load_eval_config(config_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    rows: list[dict[str, Any]] = [None] * len(dataset)  # preserve dataset order

    async def _one(sample, idx: int) -> None:
        async with sem:
            row = await _retrieve_one(rm, sample, session_prefix, top_k)
            rows[idx] = row
            print(
                f"[lme-retrieve] {idx + 1}/{len(dataset)}  "
                f"qid={sample.get('question_id', '')}  "
                f"chunks={row['num_episodes_retrieved']}  "
                f"t={row['memory_retrieval_time']:.2f}s"
            )

    await asyncio.gather(
        *[_one(sample, i) for i, sample in enumerate(dataset)]
    )

    with open(out_path, "w") as f:
        for row in rows:
            if row is not None:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[lme-retrieve] wrote {sum(r is not None for r in rows)} rows -> {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--data-path", required=True, help="longmemeval_*.json path")
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
    p.add_argument("--top-k", type=int, default=50)
    p.add_argument("--out", required=True, help="Output retrieve.jsonl path")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-categories", default=None)
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight question queries (default: 4).",
    )
    args = p.parse_args()

    asyncio.run(
        _retrieve_all(
            data_path=args.data_path,
            config_path=args.config_path,
            session_prefix=args.session_prefix,
            top_k=args.top_k,
            out_path=Path(args.out).resolve(),
            limit=args.limit,
            include_categories=args.include_categories,
            concurrency=args.concurrency,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
