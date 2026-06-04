"""Memory-retrieval agent that queries episodic memory long-term context."""

import datetime
import logging
import time
from typing import Any

from memmachine_server.common.episode_store import Episode, EpisodeType
from memmachine_server.episodic_memory import EpisodicMemory
from memmachine_server.retrieval_agent.common.agent_api import (
    AgentToolBase,
    AgentToolBaseParam,
    QueryParam,
    QueryPolicy,
    adaptive_k_cutoff,
)

logger = logging.getLogger(__name__)


class MemMachineAgent(AgentToolBase):
    """Agent that runs long-term episodic memory search without rewriting."""

    def __init__(self, param: AgentToolBaseParam) -> None:
        """Initialize retrieval behavior and shared dependencies."""
        super().__init__(param)

    @property
    def agent_name(self) -> str:
        return "MemMachineAgent"

    @property
    def agent_description(self) -> str:
        return "This agent retrieve data from MemMachine memory directly"

    @property
    def accuracy_score(self) -> int:
        return 0

    @property
    def token_cost(self) -> int:
        return 0

    @property
    def time_cost(self) -> int:
        return 0

    async def do_query(
        self,
        policy: QueryPolicy,
        query: QueryParam,
    ) -> tuple[list[Episode], dict[str, Any]]:
        _ = policy
        logger.info("CALLING %s with query: %s", self.agent_name, query.query)

        perf_metrics: dict[str, Any] = {
            "memory_search_called": 0,
            "memory_retrieval_time": 0.0,
            "agent": self.agent_name,
        }
        mem_retrieval_start = time.time()
        query_response = await query.memory.query_memory(
            query=query.query,
            limit=query.limit,
            expand_context=query.expand_context,
            score_threshold=query.score_threshold,
            property_filter=query.property_filter,
            mode=EpisodicMemory.QueryMode.LONG_TERM_ONLY,
        )
        if query_response is None:
            scored = []
        else:
            scored = list(query_response.long_term_memory.episodes)

        if query.adaptive_k and scored:
            scored, ak_info = self._apply_adaptive_k(scored, query)
            perf_metrics.update(ak_info)

        episodes = [
            Episode(
                uid=episode.uid,
                content=episode.content,
                session_key=query.memory.session_key,
                created_at=episode.created_at
                or datetime.datetime.now(tz=datetime.UTC),
                producer_id=episode.producer_id,
                producer_role=episode.producer_role,
                produced_for_id=episode.produced_for_id,
                episode_type=episode.episode_type or EpisodeType.MESSAGE,
                metadata=episode.metadata,
            )
            for episode in scored
        ]

        perf_metrics["memory_search_called"] += 1
        perf_metrics["memory_retrieval_time"] += time.time() - mem_retrieval_start

        return episodes, perf_metrics

    @staticmethod
    def _apply_adaptive_k(
        scored: list[Any], query: QueryParam
    ) -> tuple[list[Any], dict[str, Any]]:
        """Keep only the prefix before the largest score gap.

        ``scored`` is the candidate pool (size <= ``query.limit``) in
        query_memory's order. We rank a copy by score, find the adaptive cut,
        then return the survivors in their original order so downstream
        formatting is unchanged apart from the count. The returned info dict
        (pool size, kept k, score bounds) is merged into ``perf_metrics`` so
        callers can record the per-query k.
        """
        ranked = sorted(
            scored,
            key=lambda e: e.score if e.score is not None else float("-inf"),
            reverse=True,
        )
        scores_desc = [e.score for e in ranked if e.score is not None]
        if not scores_desc:
            return scored, {"adaptive_k": True, "adaptive_pool": len(scored)}
        keep = adaptive_k_cutoff(
            scores_desc,
            query.adaptive_k_min,
            query.adaptive_k_max,
            query.adaptive_k_bias,
        )
        kept_uids = {e.uid for e in ranked[:keep]}
        info = {
            "adaptive_k": True,
            "adaptive_pool": len(scores_desc),
            "adaptive_kept": keep,
            "adaptive_bias": query.adaptive_k_bias,
            "adaptive_score_hi": round(scores_desc[0], 6),
            "adaptive_score_cut": round(scores_desc[keep - 1], 6),
        }
        logger.info(
            "adaptive_k: pool=%d kept=%d bias=%.2f (score %.4f..%.4f)",
            len(scores_desc),
            keep,
            query.adaptive_k_bias,
            scores_desc[0],
            scores_desc[keep - 1],
        )
        return [e for e in scored if e.uid in kept_uids], info
