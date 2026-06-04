#!/usr/bin/env python3
"""LongMemEval ingest — per-question session_id 격리 (MemMachine 백엔드).

각 질문의 haystack 을 `session_id = <prefix>_<question_id>` 에 격리 적재.
ingest 후엔 같은 prefix 로 `retrieve.py` 를 부르면 그 session 안에서만 검색.

매 질문 시작 시 `delete_session_episodes()` 가 먼저 도니까 같은 prefix 로
재실행해도 중복 적재 없이 idempotent.

본 모듈은 `evaluation/longmemeval/_common.py` 와 `memmachine_server.*` 만
import — `evaluation/retrieval_agent/`, `evaluation/utils/` 의존 없음.

Usage:
    uv run python -m evaluation.longmemeval.ingest \\
        --in-file evaluation/data/longmemeval_s_cleaned.json \\
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
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memmachine_server.common.episode_store import Episode  # noqa: E402

from evaluation.longmemeval._common import (  # noqa: E402
    build_memory_and_agent,
    load_eval_config,
    parse_session_dt,
    set_safe_embedder_limits,
)


def _build_episodes(entry: dict, session_id: str) -> list[Episode]:
    """entry 의 haystack 을 Episode 리스트로 변환.

    **1 turn = 1 Episode** (upstream `run_retrieval.py --granularity turn`
    과 동일 단위). turn 길이 무관 — 긴 turn 도 자르지 않음. embedder 의
    max_input_length (e.g., bge-base = 512 token ≈ 2000자) 를 넘으면
    임베딩 단계에서 silently truncate 되는 건 upstream 도 동일.

    role 보존 (User/Assistant), session_date + turn_idx 초 timestamp.

    Episode.metadata 에 `lme_session_id` (haystack_session_ids 의 원본 ID,
    `session_key` 와 다름) + `lme_turn_idx` (그 session 안의 enumerate
    index) 를 저장. retrieve 가 이 둘을 묶어 `{sid}:{idx}` turn-ID 로
    내보내, oracle 의 has_answer=True turn 과 ID 교집합 기반 recall 계산
    가능. (`evaluation/episodic_memory/longmemeval_models.py:91` 의
    `answer_turn_indices = [f"{session_id}:{turn.index}"]` 와 같은 의미.)
    """
    episodes: list[Episode] = []
    for sid, sess, sdate in zip(
        entry.get("haystack_session_ids", []) or [],
        entry.get("haystack_sessions", []) or [],
        entry.get("haystack_dates", []) or [],
        strict=False,
    ):
        try:
            base_dt = parse_session_dt(sdate)
        except (TypeError, ValueError):
            base_dt = datetime.now(UTC)
        for i, turn in enumerate(sess or []):
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            role = str(turn.get("role", "user"))
            ts = base_dt + timedelta(seconds=i)
            episodes.append(
                Episode(
                    uid=str(uuid4()),
                    content=content,
                    session_key=session_id,
                    created_at=ts,
                    producer_id="Assistant" if role == "assistant" else "User",
                    producer_role=role,
                    metadata={
                        "lme_session_id": sid,
                        "lme_turn_idx": i,
                    },
                )
            )
    return episodes


async def _ingest_one(rm: Any, entry: dict, session_prefix: str) -> int:
    qid = str(entry.get("question_id", ""))
    session_id = f"{session_prefix}_{qid}"
    memory, _query_agent = await build_memory_and_agent(rm, session_id)
    set_safe_embedder_limits(memory)

    await memory.delete_session_episodes()
    episodes = _build_episodes(entry, session_id)
    if episodes:
        await memory.add_memory_episodes(episodes=episodes)
    return len(episodes)


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
            f"[lme-ingest] category filter {sorted(keep)}: "
            f"{before} -> {len(entry_list)}"
        )
    if args.limit is not None:
        entry_list = entry_list[: args.limit]

    rm = load_eval_config(args.config_path)
    sem = asyncio.Semaphore(args.concurrency)

    async def _one(entry: dict, idx: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            n = await _ingest_one(rm, entry, args.session_prefix)
            dt = time.perf_counter() - t0
            print(
                f"[lme-ingest] {idx + 1}/{len(entry_list)}  "
                f"qid={entry.get('question_id', '')}  episodes={n}  t={dt:.1f}s"
            )

    await asyncio.gather(
        *[_one(e, i) for i, e in enumerate(entry_list)]
    )
    print(f"[lme-ingest] done — {len(entry_list)} questions ingested.")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--in-file",
        required=True,
        help="longmemeval_*.json (e.g. evaluation/data/longmemeval_s_cleaned.json)",
    )
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
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
