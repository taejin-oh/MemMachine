"""Standalone helpers for `evaluation/longmemeval/`.

This module isolates the directory from the rest of the eval-tool tree:
nothing here imports from `evaluation/retrieval_agent/`,
`evaluation/utils/agent_utils.py`, or `scripts/`. The only dependency
is the workspace package `memmachine_server` (the server code itself).

That means `evaluation/longmemeval/` keeps working even if
`evaluation/retrieval_agent/` is reverted to main-branch state.

Helpers re-implemented (verbatim semantics) instead of imported:
  - load_eval_config        (was evaluation.utils.agent_utils.load_eval_config)
  - build_memory_and_agent  (was evaluation.utils.agent_utils.init_memmachine_params,
                              hardcoded to MemMachineAgent)
  - set_safe_embedder_limits (was longmemeval_test._set_safe_embedder_request_limits)
  - split_chunks            (was longmemeval_test._split_chunks)
  - collect_supporting_facts (was longmemeval_test._collect_supporting_facts)
  - parse_session_dt        (was longmemeval_test parsing helper)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memmachine_server.common.configuration import Configuration
from memmachine_server.common.metrics_factory import PrometheusMetricsFactory
from memmachine_server.common.resource_manager.resource_manager import (
    ResourceManagerImpl,
)
from memmachine_server.episodic_memory.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryParams,
)
from memmachine_server.episodic_memory.long_term_memory import (
    LongTermMemory,
    LongTermMemoryParams,
)
from memmachine_server.retrieval_agent.agents import MemMachineAgent
from memmachine_server.retrieval_agent.common.agent_api import (
    AgentToolBase,
    AgentToolBaseParam,
)


def load_eval_config(config_path: str) -> ResourceManagerImpl:
    """Load working configuration.yml → ResourceManagerImpl."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"configuration.yml not found at {config_path!r}. Run "
            "scripts/generate_config.py first or supply a hand-written yml."
        )
    config = Configuration.load_yml_file(str(config_file))
    return ResourceManagerImpl(config)


async def build_memory_and_agent(
    rm: ResourceManagerImpl, session_id: str
) -> tuple[EpisodicMemory, AgentToolBase]:
    """Per-session EpisodicMemory + MemMachineAgent.

    ResourceManagerImpl caches embedder / reranker / vector_graph_store
    resources internally, so calling this per question only creates new
    wrappers — no model re-loading.
    """
    conf = rm.config
    ltm_conf = conf.episodic_memory.long_term_memory
    if ltm_conf is None:
        raise ValueError(
            "episodic_memory.long_term_memory is not configured in configuration.yml"
        )
    if not ltm_conf.embedder:
        raise ValueError(
            "episodic_memory.long_term_memory.embedder is not set"
        )
    if not ltm_conf.vector_graph_store:
        raise ValueError(
            "episodic_memory.long_term_memory.vector_graph_store is not set"
        )

    embedder = await rm.get_embedder(ltm_conf.embedder)
    reranker_id = conf.retrieval_agent.reranker or ltm_conf.reranker
    if not reranker_id:
        raise ValueError(
            "No reranker configured "
            "(retrieval_agent.reranker or episodic_memory.long_term_memory.reranker)"
        )
    reranker = await rm.get_reranker(reranker_id)
    vector_graph_store = await rm.get_vector_graph_store(
        ltm_conf.vector_graph_store
    )

    chunking = getattr(ltm_conf, "message_sentence_chunking", None) or False

    long_term_memory = LongTermMemory(
        LongTermMemoryParams(
            session_id=session_id,
            vector_graph_store=vector_graph_store,
            embedder=embedder,
            reranker=reranker,
            message_sentence_chunking=chunking,
        )
    )
    memory = EpisodicMemory(
        EpisodicMemoryParams(
            session_key=session_id,
            metrics_factory=PrometheusMetricsFactory(),
            long_term_memory=long_term_memory,
            short_term_memory=None,
            enabled=True,
        ),
    )

    query_agent: AgentToolBase = MemMachineAgent(
        AgentToolBaseParam(
            model=None,
            children_tools=[],
            extra_params={},
            reranker=reranker,
        )
    )

    return memory, query_agent


def set_safe_embedder_limits(memory: EpisodicMemory) -> None:
    """Cap embedder request size below typical model token ceilings."""
    long_term_memory = getattr(memory, "long_term_memory", None)
    declarative_memory = (
        getattr(long_term_memory, "declarative_memory", None)
        if long_term_memory is not None
        else None
    )
    embedder = getattr(declarative_memory, "_embedder", None)
    if embedder is None:
        return
    if hasattr(embedder, "max_total_input_length_per_request"):
        embedder.max_total_input_length_per_request = 30000


def split_chunks(text: str, max_chars: int = 3000) -> list[str]:
    """Split text into ≤max_chars pieces at word boundaries when feasible."""
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    text_len = len(normalized)
    while start < text_len:
        end = min(start + max_chars, text_len)
        if end < text_len:
            split_at = normalized.rfind(" ", start, end)
            if split_at > start + (max_chars // 2):
                end = split_at
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def collect_supporting_facts(sample: dict[str, Any]) -> list[str]:
    """Return has_answer=True turn contents from a longmemeval sample."""
    facts: list[str] = []
    for session in sample.get("haystack_sessions", []) or []:
        for turn in session or []:
            if turn.get("has_answer"):
                content = str(turn.get("content", "")).strip()
                if content:
                    facts.append(content)
    return facts


def parse_session_dt(ts: str) -> datetime:
    """Parse a longmemeval session_date string ('2023/04/10 (Mon) 23:07')."""
    return datetime.strptime(ts, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)
