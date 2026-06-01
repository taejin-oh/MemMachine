"""Shared interfaces and base implementation for retrieval-agent tools."""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, InstanceOf

from memmachine_server.common.episode_store import Episode
from memmachine_server.common.episode_store.episode_model import episodes_to_string
from memmachine_server.common.filter.filter_parser import (
    FilterExpr,
)
from memmachine_server.common.language_model.language_model import LanguageModel
from memmachine_server.common.reranker.reranker import Reranker
from memmachine_server.episodic_memory import EpisodicMemory

logger = logging.getLogger(__name__)


def adaptive_k_cutoff(
    scores_desc: list[float], min_k: int, max_k: int, bias: float = 0.0
) -> int:
    """Largest-gap cutoff for descending-sorted relevance scores.

    Returns how many top items to keep: cut just before the biggest drop in
    score, clamped to ``[min_k, max_k]``. Mirrors Adaptive-k (Taguchi et al.,
    "No Tuning, No Iteration, Just Adaptive-k", EMNLP 2025): locate the largest
    consecutive gap in the sorted similarities and cut there. Pure-Python — the
    paper uses ``torch.diff``/``argmin``; this is the same result with no
    torch/numpy dependency.

    ``bias`` tunes how aggressively we cut. Each candidate gap is weighted by
    ``k ** bias`` (k = items kept at that cut), so a higher bias favours later
    cuts — keeping more chunks, trading a larger k for higher recall. The plain
    largest-gap rule (``bias=0.0``, the default) is the most aggressive: when
    the top hit scores far above the rest the first gap dominates and it cuts
    to k=1. Raise ``bias`` (e.g. 0.5-2.0) so a dominant top gap no longer wins
    outright. ``bias=0.0`` reproduces the un-weighted behaviour exactly.

    ``max_k <= 0`` means no extra ceiling (the candidate pool itself bounds it);
    ``min_k`` is a hard floor — the surest recall lever when gaps are unhelpful.
    """
    n = len(scores_desc)
    min_k = max(1, min_k)
    if n <= min_k:
        return n
    upper = min(max_k, n) if max_k > 0 else n
    last = min(upper, n - 1)  # largest cut that still has a dropped item
    best_k = upper
    best_score = -1.0
    for k in range(min_k, last + 1):
        gap = scores_desc[k - 1] - scores_desc[k]
        weighted = gap * (k**bias)
        if weighted > best_score:
            best_score = weighted
            best_k = k
    return best_k


class QueryPolicy(BaseModel):
    """Scoring and budget policy used by retrieval-agent tools."""

    token_cost: int
    time_cost: int
    accuracy_score: float
    confidence_score: float
    max_attempts: int = 5
    max_return_len: int = 100000


class QueryParam(BaseModel):
    """Input parameters for a retrieval-agent query."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    query: str
    limit: int = 0
    expand_context: int = 0
    score_threshold: float = -float("inf")
    property_filter: FilterExpr | None = None
    memory: InstanceOf[EpisodicMemory]
    # Adaptive-k: when True, treat ``limit`` as a candidate pool and keep only
    # the prefix before the largest score gap instead of a fixed ``limit``.
    adaptive_k: bool = False
    adaptive_k_min: int = 1
    adaptive_k_max: int = 0  # <=0 → bounded only by the candidate pool
    adaptive_k_bias: float = 0.0  # higher → cut later (keep more, higher recall)


class AgentToolBaseParam(BaseModel):
    """Dependency bundle used to construct an agent tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    model: InstanceOf[LanguageModel] | None = None
    children_tools: list[InstanceOf[AgentToolBase]] | None = None
    extra_params: dict[str, Any] | None = None
    reranker: InstanceOf[Reranker] | None = None


class AgentToolBase:
    """Base class for retrieval-agent tool implementations."""

    def __init__(self, param: AgentToolBaseParam) -> None:
        """Initialize tool dependencies and aggregate child costs."""
        super().__init__()
        self._model = param.model
        self._children_tools = param.children_tools or []
        self._reranker = param.reranker
        self._child_token_cost = 0
        self._child_time_cost = 0
        for tool in self._children_tools:
            self._child_token_cost += tool.token_cost
            self._child_time_cost += tool.time_cost

    @property
    @abstractmethod
    def agent_name(self) -> str:
        pass

    @property
    @abstractmethod
    def agent_description(self) -> str:
        pass

    def _update_perf_metrics(
        self,
        source: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any]:
        for key, value in source.items():
            if key not in target:
                target[key] = value
            else:
                if isinstance(value, int | float):
                    target[key] += value
                elif isinstance(value, list):
                    target[key].extend(value)
        return target

    async def _do_rerank(
        self, query: QueryParam, episodes: list[Episode]
    ) -> list[Episode]:
        if query.limit <= 0:
            return sorted(episodes, key=lambda x: x.created_at)

        if len(episodes) <= query.limit or self._reranker is None:
            if len(episodes) == 0:
                return episodes
            return sorted(episodes[: query.limit], key=lambda x: x.created_at)

        contents = [episodes_to_string([episode]) for episode in episodes]
        success = False
        max_retry = 60
        scores = []
        while not success:
            try:
                scores = await self._reranker.score(query.query, contents)
                success = True
            except Exception as e:
                max_retry -= 1
                if max_retry == 0:
                    logger.exception("Reranker failed after maximum retries.")
                    raise
                if "ThrottlingException" in str(e):
                    logger.warning(
                        "Reranker throttling exception, retrying after 5 seconds..."
                    )
                    await asyncio.sleep(5)
                else:
                    raise

        result = sorted(
            zip(episodes, scores, strict=True),
            key=lambda x: x[1],  # sort by score
            reverse=True,  # highest score first
        )

        result = result[: query.limit] if query.limit > 0 else result
        res = [r[0] for r in result]
        return sorted(res, key=lambda x: x.created_at)

    async def do_query(
        self, policy: QueryPolicy, query: QueryParam
    ) -> tuple[list[Episode], dict[str, Any]]:
        if len(self._children_tools) == 0:
            raise RuntimeError("No child tool to call")
        tasks = []
        for tool in self._children_tools:
            task = tool.do_query(policy, query)
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        data: list[Episode] = []
        perf_metrics: dict[str, Any] = {}
        for res, p_metric in results:
            if res is None:
                continue
            data.extend(res)
            perf_metrics = self._update_perf_metrics(perf_metrics, p_metric)
        return data, perf_metrics

    @property
    @abstractmethod
    def accuracy_score(self) -> int:
        pass

    @property
    @abstractmethod
    def token_cost(self) -> int:
        pass

    @property
    @abstractmethod
    def time_cost(self) -> int:
        pass

    def agent_tools(self) -> list[AgentToolBase]:
        return self._children_tools
