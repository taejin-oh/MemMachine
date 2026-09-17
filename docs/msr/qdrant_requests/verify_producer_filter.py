"""Verify on speedkick a8322a7 whether producer_id alone can scope a user's memories.

Uses only the upstream memmachine_server package. The only test double is a
deterministic hash embedder (no network). Stores: Qdrant 1.17.0 + PostgreSQL 16.
Ingestion follows the server order: episode_storage.add_episodes -> add_memory_episodes.
"""

import asyncio
import hashlib
import math
import os
from datetime import UTC, datetime, timedelta

from memmachine_server.common.configuration import Configuration
from memmachine_server.common.configuration.episodic_config import (
    EpisodicMemoryConf,
    LongTermMemoryConfPartial,
)
from memmachine_server.common.embedder.embedder import Embedder
from memmachine_server.common.episode_store import EpisodeEntry
from memmachine_server.common.filter.filter_parser import parse_filter
from memmachine_server.common.resource_manager.resource_manager import (
    ResourceManagerImpl,
)
from memmachine_server.episodic_memory.episodic_memory import EpisodicMemory
from memmachine_server.episodic_memory.service_locator import (
    episodic_memory_params_from_config,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION = "org1/prj1"  # one project shared by every user
QUERY = "hiking trip plan"
DIM = 64


class HashEmbedder(Embedder):
    def _vec(self, text: object) -> list[float]:
        v = [0.0] * DIM
        for tok in str(text).lower().replace('"', " ").split():
            v[int(hashlib.sha256(tok.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def _ingest_embed(self, inputs, max_attempts=1):
        return [self._vec(t) for t in inputs]

    async def _search_embed(self, queries, max_attempts=1):
        return [self._vec(q) for q in queries]

    @property
    def model_id(self) -> str:
        return "hash-64"

    @property
    def dimensions(self) -> int:
        return DIM


def build_entries() -> list[EpisodeEntry]:
    """Interleave users in time so context expansion would hit other users."""
    base = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    rows: list[tuple[str, str, str, str, dict]] = []
    for turn in range(2):
        for uid in ("user_a", "user_b"):
            # Rule-following client: assistant reply carries produced_for = user.
            rows.append((uid, "user", "assistant", f"[{uid}|user|t{turn}] hiking trip plan question", {"user_id": uid}))
            rows.append(("assistant", "assistant", uid, f"[{uid}|assistant|t{turn}] hiking trip plan answer", {"user_id": uid}))
        # API-default client: produced_for left as "" (MemoryMessage default), role "".
        rows.append(("user_c", "", "", f"[user_c|user|t{turn}] hiking trip plan question", {"user_id": "user_c"}))
        rows.append(("assistant", "", "", f"[user_c|assistant|t{turn}] hiking trip plan answer", {"user_id": "user_c"}))
    return [
        EpisodeEntry(
            content=content,
            producer_id=producer,
            producer_role=role,
            produced_for_id=produced_for,
            metadata=meta,
            created_at=base + timedelta(minutes=i),
        )
        for i, (producer, role, produced_for, content, meta) in enumerate(rows)
    ]


def owner(content: str) -> str:
    return content[1 : content.index("|")]


async def main() -> None:
    cfg = Configuration.load_yml_file(os.path.join(HERE, "config.yml"))
    rm = ResourceManagerImpl(cfg)
    embedder = HashEmbedder()

    async def _stub_embedder(name: str, validate: bool = False) -> Embedder:
        return embedder

    rm.get_embedder = _stub_embedder  # only test double

    ltm_conf = LongTermMemoryConfPartial(session_id=SESSION).merge(
        cfg.episodic_memory.long_term_memory
    )
    conf = EpisodicMemoryConf(
        session_key=SESSION,
        metrics_factory_id="prometheus",
        long_term_memory=ltm_conf,
        short_term_memory=None,
        long_term_memory_enabled=True,
        short_term_memory_enabled=False,
    )
    memory = EpisodicMemory(await episodic_memory_params_from_config(conf, rm))
    ltm = memory._long_term_memory
    print("backend        :", type(ltm._event_memory).__name__ if getattr(ltm, "_event_memory", None) else "NOT EVENT")
    print("partition key  :", ltm._partition_key)

    episode_storage = await rm.get_episode_storage()
    episodes = await episode_storage.add_episodes(SESSION, build_entries())
    await memory.add_memory_episodes(episodes=episodes)
    print(f"ingested       : {len(episodes)} episodes in ONE project (user_a, user_b rule-following; user_c API defaults)\n")

    cases = [
        ("no filter", None, 0),
        ("producer_id only", "producer_id = 'user_a'", 0),
        ("producer OR produced_for", "producer_id = 'user_a' OR produced_for_id = 'user_a'", 0),
        ("m.user_id", "m.user_id = 'user_a'", 0),
        ("producer OR produced_for (API defaults)", "producer_id = 'user_c' OR produced_for_id = 'user_c'", 0),
        ("m.user_id (API defaults)", "m.user_id = 'user_c'", 0),
        ("producer OR produced_for + expand_context=4", "producer_id = 'user_a' OR produced_for_id = 'user_a'", 4),
        ("no filter + expand_context=4 (control)", None, 4),
    ]
    for label, expr, expand in cases:
        f = parse_filter(expr) if expr else None
        resp = await memory.query_memory(QUERY, limit=50, expand_context=expand, property_filter=f)
        eps = resp.long_term_memory.episodes if resp and resp.long_term_memory else []
        contents = sorted(e.content.split("]")[0] + "]" for e in eps)
        target = None
        if expr and "'" in expr:
            target = expr.split("'")[1]
        leaked = [c for c in contents if target and owner(c) != target]
        own_user = [c for c in contents if target and owner(c) == target and "|user|" in c]
        own_asst = [c for c in contents if target and owner(c) == target and "|assistant|" in c]
        print(f"■ {label}")
        print(f"  filter={expr!r} expand_context={expand}")
        print(f"  returned={len(eps)}", end="")
        if target:
            print(f"  {target}: user msgs={len(own_user)}/2, assistant msgs={len(own_asst)}/2, other users leaked={len(leaked)}")
        else:
            print(f"  owners={sorted({owner(c) for c in contents})}")
        for c in contents:
            print("   ", c)
        print()


if __name__ == "__main__":
    asyncio.run(main())
