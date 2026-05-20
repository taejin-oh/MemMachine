#!/usr/bin/env python3
"""LongMemEval retrieval — upstream's run_retrieval.py structure on MemMachine storage.

Mirrors xiaowu0162/LongMemEval `src/retrieval/run_retrieval.py` exactly in
shape — one outer loop over entries, three inner steps per entry — and
only swaps the storage layer:

  upstream                        |  this script
  --------------------------------|------------------------------------
  for entry in entry_list:        |  for entry in entry_list:
    # step 1: build corpus        |    # step 1: build corpus + ingest
    corpus = [...]                |    episodes = build_corpus_episodes(entry)
                                  |    await memory.delete_session_episodes()
                                  |    await memory.add_memory_episodes(...)
    # step 2: run retrieval       |    # step 2: run retrieval
    rankings = retriever(query,   |    chunks, _ = await query_agent.do_query(
                          corpus) |        QueryParam(query, limit=top_k, memory))
    # step 3: record              |    # step 3: record (our retrieve.jsonl row)
    cur_results = {...}           |    rows.append({...})

Per-question session_id (`<prefix>_<question_id>`) gives the same isolation
upstream gets by rebuilding the corpus per entry. The MemMachine pieces
(embedder / vector_graph_store / reranker / query_agent) are pulled from
the working configuration.yml the same way evaluation/retrieval_agent/
uses them.

No answer-LLM call, no judge — pure retrieval. Output is retrieve.jsonl in
this branch's schema so the existing analysis tools work as-is.

Usage:
    uv run python -m evaluation.longmemeval.run_retrieval \\
        --in-file evaluation/data/longmemeval_s_cleaned.json \\
        --config-path configs/generated/<run>_configuration.yml \\
        --top-k 50 \\
        --out results/lme_iso/retrieve.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memmachine_server.common.episode_store import Episode  # noqa: E402
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
    _split_chunks,
)
from evaluation.utils import agent_utils  # noqa: E402


def _parse_session_dt(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


def _build_corpus_episodes(entry: dict, session_id: str) -> list[Episode]:
    """upstream `process_item_flat_index` 의 등가물 — entry 의 haystack_sessions
    만 훑어 (User/Assistant 라벨, session_date + turn_idx 초 timestamp) Episode
    리스트 반환. >3000 자 turn 은 _split_chunks 로 자름.
    """
    episodes: list[Episode] = []
    for sid, sess, sdate in zip(
        entry.get("haystack_session_ids", []) or [],
        entry.get("haystack_sessions", []) or [],
        entry.get("haystack_dates", []) or [],
        strict=False,
    ):
        try:
            base_dt = _parse_session_dt(sdate)
        except (TypeError, ValueError):
            base_dt = datetime.now(UTC)
        for i, turn in enumerate(sess or []):
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            role = str(turn.get("role", "user"))
            ts = base_dt + timedelta(seconds=i)
            for chunk in _split_chunks(content):
                episodes.append(
                    Episode(
                        uid=str(uuid4()),
                        content=chunk,
                        session_key=session_id,
                        created_at=ts,
                        producer_id="Assistant" if role == "assistant" else "User",
                        producer_role=role,
                    )
                )
    return episodes


async def _process_entry(
    rm: Any,
    entry: dict,
    session_prefix: str,
    top_k: int,
) -> dict[str, Any]:
    """Upstream's per-entry inner body — 3 steps, MemMachine storage."""
    qid = str(entry.get("question_id", ""))
    session_id = f"{session_prefix}_{qid}"
    memory, _, query_agent = await agent_utils.init_memmachine_params(
        resource_manager=rm,
        session_id=session_id,
        agent_name="MemMachineAgent",
    )
    _set_safe_embedder_request_limits(memory)

    # step 1: build corpus + ingest (delete-then-add → idempotent re-runs)
    await memory.delete_session_episodes()
    episodes = _build_corpus_episodes(entry, session_id)
    if episodes:
        await memory.add_memory_episodes(episodes=episodes)

    # step 2: run retrieval
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
        QueryParam(query=question, limit=top_k, memory=memory),
    )
    latency = time.perf_counter() - t0

    # step 3: record (this branch's retrieve.jsonl row)
    return {
        "question": question,
        "question_id": qid,
        "category": str(entry.get("question_type", "")),
        "sweep": {},
        "cell_idx": 0,
        "chunks_text": episodes_to_string(chunks),
        "num_episodes_retrieved": len(chunks),
        "memory_retrieval_time": perf.get("memory_retrieval_time", latency),
        "memory_search_called": perf.get("memory_search_called", 1),
        "agent": perf.get("agent", "lme_iso"),
        "selected_tool": perf.get("selected_tool", "lme_iso"),
        "supporting_facts": _collect_supporting_facts(entry),
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
            f"[lme] category filter {sorted(keep)}: {before} -> {len(entry_list)}"
        )
    if args.limit is not None:
        entry_list = entry_list[: args.limit]

    rm = agent_utils.load_eval_config(args.config_path)
    out_path = args.out_path  # resolved in main() before asyncio.run

    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict[str, Any] | None] = [None] * len(entry_list)

    async def _one(entry: dict, idx: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            rows[idx] = await _process_entry(
                rm, entry, args.session_prefix, args.top_k
            )
            dt = time.perf_counter() - t0
            print(
                f"[lme] {idx + 1}/{len(entry_list)}  "
                f"qid={entry.get('question_id', '')}  t={dt:.1f}s"
            )

    await asyncio.gather(
        *[_one(e, i) for i, e in enumerate(entry_list)]
    )

    with open(out_path, "w") as f:
        for row in rows:
            if row is not None:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        f"[lme] wrote {sum(r is not None for r in rows)} rows -> {out_path}"
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--in-file",
        required=True,
        help="longmemeval_*.json (upstream's --in_file)",
    )
    p.add_argument(
        "--config-path",
        required=True,
        help="Working configuration.yml (from scripts/generate_config.py)",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output retrieve.jsonl path (this branch's schema)",
    )
    p.add_argument(
        "--session-prefix",
        default="lme_iso",
        help="session_id prefix; final id = '<prefix>_<question_id>'. Default: lme_iso",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=50,
        help="Retrieved chunks per question (default: 50)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-categories", default=None)
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max questions processed in parallel (default: 4).",
    )
    args = p.parse_args()
    args.out_path = Path(args.out).resolve()
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
