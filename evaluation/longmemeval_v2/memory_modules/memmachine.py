"""MemMachine backend for LongMemEval-V2.

Implements the upstream `Memory` interface (see `memory.py`) using
MemMachine's `EpisodicMemory` + `LongTermMemory` (Neo4j vector graph store)
+ `MemMachineAgent` retrieval stack.

Storage model
-------------
- 1 LongMemEval-V2 trajectory  → 1 MemMachine session
  (`session_id = f"{session_prefix}_{trajectory['id']}"`).
  Per-trajectory isolation mirrors what `evaluation/longmemeval/`
  does for V1 (per-question session). It avoids cross-trajectory
  contamination at retrieval time and lets us pre-ingest the entire
  trajectory pool once.
- 1 trajectory state → 1 Episode. The state's url, action, thoughts,
  and rendered text are concatenated into the Episode content.
  Screenshots are referenced in `Episode.metadata["screenshot_path"]`
  but are **not** multimodally embedded — this adapter is text-only
  for now (V2 supports multimodal questions but text-only retrieval
  is a reasonable first cut and matches the `rag_query_to_slice`
  baseline's behavior).

Query scoping
-------------
The V2 harness should call `memory.set_query_context(haystack=[traj_id, ...])`
before each `query()`, listing the trajectory ids in the question's haystack.
This adapter queries each haystack session and merges the top-K results.
If no haystack is set, we error out — explicit scoping is required to avoid
silently retrieving from unrelated trajectories.

Async/sync bridge
-----------------
MemMachine's API is async; the V2 `Memory` interface is sync. We bridge with
a single dedicated background event-loop thread (created lazily). All async
calls are submitted to that loop and awaited via `concurrent.futures`.
This avoids `asyncio.run()` per call (which would tear down + rebuild
the event loop, losing ResourceManager caches indirectly via lost
contextvars).
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

# Imports from MemMachine workspace package — same shim as V1 _common.py
# for the DeclarativeBackendParams rename across upstream commits.
from memmachine_server.common.configuration import Configuration
from memmachine_server.common.episode_store import Episode
from memmachine_server.common.episode_store.episode_model import (
    episodes_to_string,
)
from memmachine_server.common.metrics_factory import PrometheusMetricsFactory
from memmachine_server.common.resource_manager.resource_manager import (
    ResourceManagerImpl,
)
from memmachine_server.episodic_memory.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryParams,
)
from memmachine_server.episodic_memory.long_term_memory import LongTermMemory

from .memory import Memory, MemoryContextItem, register_memory, require

try:
    from memmachine_server.episodic_memory.long_term_memory import (
        DeclarativeBackendParams as _DeclarativeParams,
    )
except ImportError:  # origin/main (pre-PR-1395)
    from memmachine_server.episodic_memory.long_term_memory import (
        LongTermMemoryParams as _DeclarativeParams,
    )

from memmachine_server.retrieval_agent.agents import MemMachineAgent
from memmachine_server.retrieval_agent.common.agent_api import (
    AgentToolBase,
    AgentToolBaseParam,
    QueryParam,
    QueryPolicy,
)


# ---------------------------------------------------------------------------
# Dedicated event loop (one per process)
# ---------------------------------------------------------------------------
class _LoopThread:
    """Background thread that runs a single asyncio event loop forever."""

    _instance: _LoopThread | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, name="memmachine-loop", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    @classmethod
    def get(cls) -> _LoopThread:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def submit(self, coro: Any) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


def _run_async(coro: Any, timeout: float | None = None) -> Any:
    return _LoopThread.get().submit(coro).result(timeout=timeout)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _render_state_text(state: dict[str, Any]) -> str:
    """Concatenate URL + action + thought + accessibility_tree into Episode content.

    Field names match the actual V2 trajectory schema (verified against
    xiaowu0162/longmemeval-v2 on HuggingFace):
      - `accessibility_tree` (rendered DOM/AX dump, 1~13KB per state)
      - `thought` (singular — the agent's reasoning for the step)
      - `action`, `url`, `step`, `state_index`

    Falls back to legacy keys (`text`, `thoughts`) if present, so the
    adapter survives a future upstream rename without re-edit.
    """
    parts: list[str] = []
    url = state.get("url")
    if isinstance(url, str) and url.strip():
        parts.append(f"URL: {url.strip()}")
    step = state.get("step")
    state_index = state.get("state_index")
    if isinstance(step, int) and isinstance(state_index, int):
        parts.append(f"Step: {step} (state_index={state_index})")
    action = state.get("action")
    if isinstance(action, str) and action.strip():
        parts.append(f"Action: {action.strip()}")
    thought = state.get("thought") or state.get("thoughts")
    if isinstance(thought, str) and thought.strip():
        parts.append(f"Thought: {thought.strip()}")
    observation = state.get("accessibility_tree") or state.get("text")
    if isinstance(observation, str) and observation.strip():
        parts.append(f"Observation:\n{observation.strip()}")
    return "\n".join(parts)


def _trajectory_session_id(prefix: str, trajectory_id: str) -> str:
    return f"{prefix}_{trajectory_id}"


# ---------------------------------------------------------------------------
# MemMachine backend
# ---------------------------------------------------------------------------
@register_memory
class MemMachineMemory(Memory):
    """MemMachine-backed memory module for LongMemEval-V2.

    memory_params:
      configuration_path: str  — path to MemMachine working configuration.yml
      session_prefix:     str  — prefix for session ids (default "lmev2")
      top_k:              int  — chunks returned per query (default 50)
      max_attempts:       int  — QueryPolicy.max_attempts  (default 3)
      max_return_len:     int  — QueryPolicy.max_return_len (default 10000)
      include_thoughts:   bool — include state.thoughts in Episode text
      embedder_max_input_length: int — cap embedder request size (default 30000)
    """

    memory_type = "memmachine"

    def __init__(self, memory_params: dict[str, object]) -> None:
        super().__init__(memory_params)

        config_path_obj = memory_params.get("configuration_path")
        require(
            isinstance(config_path_obj, str) and config_path_obj,
            "memmachine memory_params.configuration_path must be a non-empty string",
        )
        self._configuration_path = str(config_path_obj)
        config_path = Path(self._configuration_path)
        require(
            config_path.exists(),
            f"MemMachine configuration.yml not found at {config_path}",
        )

        self._session_prefix = str(memory_params.get("session_prefix", "lmev2"))
        self._top_k = int(memory_params.get("top_k", 50))
        self._max_attempts = int(memory_params.get("max_attempts", 3))
        self._max_return_len = int(memory_params.get("max_return_len", 10000))
        self._include_thoughts = bool(memory_params.get("include_thoughts", True))
        self._embedder_max_input_length = int(
            memory_params.get("embedder_max_input_length", 30000)
        )

        # Lazy-built: ResourceManagerImpl + per-session EpisodicMemory cache.
        self._rm: ResourceManagerImpl | None = None
        self._sessions: dict[str, tuple[EpisodicMemory, AgentToolBase]] = {}
        self._sessions_lock = threading.Lock()
        self._inserted_trajectories: set[str] = set()

    # ---- ResourceManager bootstrap ----
    def _ensure_resource_manager(self) -> ResourceManagerImpl:
        if self._rm is not None:
            return self._rm
        cfg = Configuration.load_yml_file(self._configuration_path)
        self._rm = ResourceManagerImpl(cfg)
        return self._rm

    async def _build_memory_and_agent_async(
        self, session_id: str
    ) -> tuple[EpisodicMemory, AgentToolBase]:
        rm = self._ensure_resource_manager()
        conf = rm.config
        ltm_conf = conf.episodic_memory.long_term_memory
        require(ltm_conf is not None, "configuration.yml: episodic_memory.long_term_memory missing")
        require(bool(ltm_conf.embedder), "long_term_memory.embedder not set")
        require(
            bool(ltm_conf.vector_graph_store),
            "long_term_memory.vector_graph_store not set",
        )

        embedder = await rm.get_embedder(ltm_conf.embedder)
        reranker_id = conf.retrieval_agent.reranker or ltm_conf.reranker
        require(
            bool(reranker_id),
            "No reranker configured (retrieval_agent.reranker or long_term_memory.reranker)",
        )
        reranker = await rm.get_reranker(reranker_id)
        vector_graph_store = await rm.get_vector_graph_store(ltm_conf.vector_graph_store)
        chunking = getattr(ltm_conf, "message_sentence_chunking", None) or False

        long_term_memory = LongTermMemory(
            _DeclarativeParams(
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
        # Cap embedder request size to avoid OOM/over-limit on long pages.
        declarative_memory = getattr(long_term_memory, "declarative_memory", None)
        if declarative_memory is not None:
            embedder_obj = getattr(declarative_memory, "_embedder", None)
            if embedder_obj is not None and hasattr(
                embedder_obj, "max_total_input_length_per_request"
            ):
                embedder_obj.max_total_input_length_per_request = (
                    self._embedder_max_input_length
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

    def _get_session(
        self, session_id: str
    ) -> tuple[EpisodicMemory, AgentToolBase]:
        with self._sessions_lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                return entry
        # Build outside the lock (async work).
        memory, agent = _run_async(self._build_memory_and_agent_async(session_id))
        with self._sessions_lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                self._sessions[session_id] = (memory, agent)
                entry = (memory, agent)
        return entry

    # ---- Insert ----
    async def _insert_trajectory_async(self, trajectory: dict[str, Any]) -> None:  # noqa: C901
        traj_id_obj = trajectory.get("id")
        require(
            isinstance(traj_id_obj, str) and traj_id_obj,
            "trajectory.id must be a non-empty string",
        )
        traj_id = str(traj_id_obj)
        session_id = _trajectory_session_id(self._session_prefix, traj_id)

        memory, _agent = await self._build_memory_and_agent_async(session_id)
        # Cache for later queries
        with self._sessions_lock:
            self._sessions[session_id] = (memory, _agent)

        # Idempotent re-ingest: clear prior episodes for this session first.
        await memory.delete_session_episodes()

        states_obj = trajectory.get("states")
        require(
            isinstance(states_obj, list),
            f"trajectory.states must be a list for {traj_id}",
        )
        base_dt = datetime.now(UTC)
        episodes: list[Episode] = []
        goal = trajectory.get("goal")
        start_url = trajectory.get("start_url")
        outcome = trajectory.get("outcome")
        header_parts: list[str] = []
        if isinstance(goal, str) and goal.strip():
            header_parts.append(f"Goal: {goal.strip()}")
        if isinstance(start_url, str) and start_url.strip():
            header_parts.append(f"Start URL: {start_url.strip()}")
        if isinstance(outcome, str) and outcome.strip():
            header_parts.append(f"Outcome: {outcome.strip()}")
        if header_parts:
            episodes.append(
                _make_episode(
                    content="\n".join(header_parts),
                    session_id=session_id,
                    traj_id=traj_id,
                    state_index=-1,
                    extras={"role": "task_header"},
                    timestamp=base_dt,
                )
            )
        for i, state in enumerate(states_obj):
            if not isinstance(state, dict):
                continue
            state = dict(state)
            if not self._include_thoughts:
                state["thoughts"] = None
            text = _render_state_text(state)
            if not text:
                continue
            screenshot = state.get("screenshot")
            extras: dict[str, Any] = {}
            if isinstance(screenshot, str) and screenshot.strip():
                extras["screenshot_path"] = screenshot.strip()
            episodes.append(
                _make_episode(
                    content=text,
                    session_id=session_id,
                    traj_id=traj_id,
                    state_index=int(state.get("state_index", i)),
                    extras=extras,
                    timestamp=base_dt + timedelta(seconds=i + 1),
                )
            )

        if episodes:
            await memory.add_memory_episodes(episodes=episodes)
        self._inserted_trajectories.add(traj_id)

    def insert(self, trajectory: dict[str, object]) -> None:
        _run_async(self._insert_trajectory_async(trajectory))

    # ---- Query ----
    async def _query_session_async(
        self, session_id: str, query_text: str
    ) -> tuple[list[Any], dict[str, Any]]:
        memory, agent = await self._build_memory_and_agent_async(session_id)
        # Cache it
        with self._sessions_lock:
            self._sessions.setdefault(session_id, (memory, agent))
        chunks, perf = await agent.do_query(
            QueryPolicy(
                token_cost=10,
                time_cost=10,
                accuracy_score=10,
                confidence_score=10,
                max_attempts=self._max_attempts,
                max_return_len=self._max_return_len,
            ),
            QueryParam(query=query_text, limit=self._top_k, memory=memory),
        )
        return chunks, perf

    def query(
        self,
        query: str,
        query_image: str | None = None,
    ) -> list[MemoryContextItem]:
        ctx = self.get_query_context()
        haystack = ctx.get("haystack")
        require(
            isinstance(haystack, (list, tuple)) and haystack,
            (
                "MemMachineMemory.query requires set_query_context(haystack=[...])"
                f" with the trajectory ids to retrieve from. Got: {haystack!r}"
            ),
        )

        session_ids = [
            _trajectory_session_id(self._session_prefix, str(t)) for t in haystack
        ]

        async def _gather() -> list[MemoryContextItem]:
            tasks = [self._query_session_async(sid, query) for sid in session_ids]
            results = await asyncio.gather(*tasks)
            merged: list[MemoryContextItem] = []
            for chunks, _perf in results:
                rendered = episodes_to_string(chunks)
                if rendered:
                    merged.append({"type": "text", "value": rendered})
            return merged

        return _run_async(_gather())

    # ---- Save/load are no-ops: state lives in Neo4j/Postgres. ----
    def _save_backend(self, output_dir: Path) -> None:
        # We only persist the list of trajectories that were inserted, so a
        # re-load can sanity-check the live backend matches.
        manifest = sorted(self._inserted_trajectories)
        (output_dir / "inserted_trajectories.json").write_text(
            "[\n" + ",\n".join(f"  {t!r}" for t in manifest) + "\n]\n",
            encoding="utf-8",
        )

    def _load_backend(self, input_dir: Path) -> None:
        manifest_path = input_dir / "inserted_trajectories.json"
        if not manifest_path.exists():
            return
        import json as _json

        try:
            self._inserted_trajectories = set(
                _json.loads(manifest_path.read_text(encoding="utf-8"))
            )
        except Exception:
            self._inserted_trajectories = set()


# ---------------------------------------------------------------------------
# Episode construction
# ---------------------------------------------------------------------------
def _make_episode(
    *,
    content: str,
    session_id: str,
    traj_id: str,
    state_index: int,
    extras: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> Episode:
    """Build a MemMachine Episode with our standard metadata.

    The metadata fields (`lmev2_traj_id`, `lmev2_state_index`) let downstream
    analysis link a retrieved Episode back to its source trajectory state —
    same pattern as `evaluation/longmemeval/ingest.py` uses for V1.
    """
    metadata: dict[str, Any] = {
        "lmev2_session_id": session_id,
        "lmev2_traj_id": traj_id,
        "lmev2_state_index": state_index,
    }
    if extras:
        metadata.update(extras)
    return Episode(
        uid=str(uuid4()),
        content=content,
        session_key=session_id,
        created_at=timestamp or datetime.now(UTC),
        producer_id="Agent",
        producer_role="agent",
        metadata=metadata,
    )
