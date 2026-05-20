#!/usr/bin/env python3
"""LongMemEval ingest — per-question session_id isolation.

Same MemMachine stack (Neo4j vector_graph_store + Postgres, embedder +
reranker from configuration.yml) that `evaluation/retrieval_agent/`
uses, BUT each question gets its own session_id = `<prefix>_<question_id>`.
That's the LongMemEval-standard setup (matches upstream xiaowu0162 +
main's evaluation/episodic_memory/) and avoids the cross-question
contamination that hurts recall in the single-session pipeline.

Each turn becomes one or more Episodes via _split_chunks (≤3000 chars),
same convention as evaluation/retrieval_agent/longmemeval_test._async_ingest.
Role is preserved (`User` / `Assistant` producer_id, vs retrieval_agent
which forces `user` everywhere).

Usage:
    uv run python -m evaluation.longmemeval.ingest \\
        --data-path evaluation/data/longmemeval_s_cleaned.json \\
        --config-path configs/generated/<run>_configuration.yml \\
        --session-prefix lme_iso
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.retrieval_agent.longmemeval_test import (  # noqa: E402
    _set_safe_embedder_request_limits,
    _split_chunks,
)
from evaluation.utils import agent_utils  # noqa: E402


def _parse_session_dt(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


async def _ingest_one(rm, sample: dict, session_prefix: str) -> int:
    from memmachine_server.common.episode_store import Episode

    qid = str(sample.get("question_id", ""))
    session_id = f"{session_prefix}_{qid}"
    memory, _, _ = await agent_utils.init_memmachine_params(
        resource_manager=rm,
        session_id=session_id,
    )
    _set_safe_embedder_request_limits(memory)

    episodes: list[Episode] = []
    for sid, sess, sdate in zip(
        sample.get("haystack_session_ids", []) or [],
        sample.get("haystack_sessions", []) or [],
        sample.get("haystack_dates", []) or [],
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

    if episodes:
        await memory.add_memory_episodes(episodes=episodes)
    return len(episodes)


async def _ingest_all(
    data_path: str,
    config_path: str,
    session_prefix: str,
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
            f"[lme-ingest] category filter {sorted(keep)}: "
            f"{before} -> {len(dataset)}"
        )
    if limit is not None:
        dataset = dataset[:limit]

    rm = agent_utils.load_eval_config(config_path)

    sem = asyncio.Semaphore(concurrency)

    async def _one(sample, idx: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            n = await _ingest_one(rm, sample, session_prefix)
            dt = time.perf_counter() - t0
            print(
                f"[lme-ingest] {idx + 1}/{len(dataset)}  "
                f"qid={sample.get('question_id', '')}  "
                f"episodes={n}  t={dt:.2f}s"
            )

    await asyncio.gather(
        *[_one(sample, i) for i, sample in enumerate(dataset)]
    )
    print(f"[lme-ingest] done — {len(dataset)} questions ingested.")


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
        help="session_id prefix; final id = '<prefix>_<question_id>'. Default: lme_iso",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-categories", default=None)
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max questions ingested in parallel (default: 4).",
    )
    args = p.parse_args()

    asyncio.run(
        _ingest_all(
            data_path=args.data_path,
            config_path=args.config_path,
            session_prefix=args.session_prefix,
            limit=args.limit,
            include_categories=args.include_categories,
            concurrency=args.concurrency,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
