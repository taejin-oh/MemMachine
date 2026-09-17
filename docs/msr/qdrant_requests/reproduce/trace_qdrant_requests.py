"""Trace every Qdrant HTTP request MemMachine (speedkick a8322a7) makes, per scenario.

Hooks qdrant-client's AsyncApiClient.send_inner so each REST call is logged with
method, path, body summary, status and latency. Drives the real
EpisodicMemoryManager (instance LRU cache + session DB) so cache hits/misses are
the production ones. Only test double: the hash embedder.
"""

import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from qdrant_client.http.api_client import AsyncApiClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_producer_filter import HashEmbedder  # noqa: E402

from memmachine_server.common.configuration import Configuration  # noqa: E402
from memmachine_server.common.configuration.episodic_config import (  # noqa: E402
    EpisodicMemoryConf,
    LongTermMemoryConfPartial,
)
from memmachine_server.common.episode_store import EpisodeEntry  # noqa: E402
from memmachine_server.common.filter.filter_parser import parse_filter  # noqa: E402
from memmachine_server.common.resource_manager.resource_manager import (  # noqa: E402
    ResourceManagerImpl,
)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG: list[dict] = []
SECTIONS: list[tuple[str, list[dict]]] = []
_HASH = re.compile(r"__[0-9a-f]{64}")


def _compact(obj: object, limit: int = 420) -> str:
    s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _summarize(method: str, path: str, body: bytes) -> str:
    if not body:
        return ""
    try:
        b = json.loads(body)
    except Exception:
        return f"<{len(body)} bytes>"
    if path.endswith("/points/query/batch"):
        parts = []
        for s in b.get("searches", []):
            parts.append(
                f"limit={s.get('limit')} with_payload={s.get('with_payload')} "
                f"with_vector={s.get('with_vector')} filter={_compact(s.get('filter'))}"
            )
        return f"searches={len(b.get('searches', []))}; " + " | ".join(parts)
    if path.endswith("/points/delete"):
        return _compact({k: v for k, v in b.items()})
    if path.endswith("/points") and method == "PUT":
        pts = b.get("points", [])
        keys = sorted(pts[0].get("payload", {}).keys()) if pts else []
        dim = len(pts[0].get("vector", [])) if pts else 0
        return f"points={len(pts)} dim={dim} payload_keys={keys}"
    if path.endswith("/points") and method == "POST":
        return f"ids={len(b.get('ids', []))} with_payload={b.get('with_payload')}"
    if path.endswith("/index"):
        return _compact(b)
    if method == "PUT" and "/collections/" in path:
        return _compact(
            {k: b[k] for k in ("vectors", "hnsw_config", "sharding_method",
                               "replication_factor", "write_consistency_factor") if k in b}
        )
    return _compact(b)


_orig_send_inner = AsyncApiClient.send_inner


async def _traced_send_inner(self, request):
    t0 = time.perf_counter()
    resp = await _orig_send_inner(self, request)
    ms = (time.perf_counter() - t0) * 1000
    path = _HASH.sub("__<hash>", request.url.path)
    LOG.append(
        {
            "method": request.method,
            "path": path,
            "query": request.url.query.decode() if request.url.query else "",
            "status": resp.status_code,
            "ms": round(ms, 1),
            "body": _summarize(request.method, request.url.path, request.content),
        }
    )
    return resp


AsyncApiClient.send_inner = _traced_send_inner


def section(title: str) -> None:
    entries = list(LOG)
    LOG.clear()
    SECTIONS.append((title, entries))
    counts = Counter(f"{e['method']} {e['path']}{'?' + e['query'] if e['query'] else ''}" for e in entries)
    print(f"\n■ {title}  -> {len(entries)} Qdrant request(s)")
    for key, n in counts.items():
        print(f"   {n:>3} x {key}")
    for e in entries:
        q = f"?{e['query']}" if e["query"] else ""
        print(f"     [{e['status']} {e['ms']:>6.1f}ms] {e['method']} {e['path']}{q}  {e['body']}")


def entries(uid: str, n_turns: int, base: datetime) -> list[EpisodeEntry]:
    rows = []
    for t in range(n_turns):
        rows.append(("user", uid, "assistant", f"[{uid}|user|t{t}] hiking trip plan question"))
        rows.append(("assistant", "assistant", uid, f"[{uid}|assistant|t{t}] hiking trip plan answer"))
    return [
        EpisodeEntry(
            content=c, producer_id=p, producer_role=r, produced_for_id=pf,
            metadata={"user_id": uid}, created_at=base + timedelta(minutes=i),
        )
        for i, (r, p, pf, c) in enumerate(rows)
    ]


async def main() -> None:
    cfg = Configuration.load_yml_file(os.path.join(HERE, "config.yml"))
    rm = ResourceManagerImpl(cfg)
    embedder = HashEmbedder()

    async def _stub_embedder(name, validate=False):
        return embedder

    rm.get_embedder = _stub_embedder

    def conf(session_key: str) -> EpisodicMemoryConf:
        ltm = LongTermMemoryConfPartial(session_id=session_key).merge(
            cfg.episodic_memory.long_term_memory
        )
        return EpisodicMemoryConf(
            session_key=session_key, metrics_factory_id="prometheus",
            long_term_memory=ltm, short_term_memory=None,
            long_term_memory_enabled=True, short_term_memory_enabled=False,
        )

    # P0: what the server does at startup (_warm_request_path -> get_vector_store).
    await rm.get_vector_store("event_vector_store")
    section("P0 process start: get_vector_store(validate=True)")

    mgr = await rm.get_episodic_memory_manager()
    store = await rm.get_episode_storage()
    A, B = "orga/prja", "orgb/prjb"

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}):
        pass
    section("S1 cold: first session ever in this Qdrant (registry + native collection do not exist)")

    async with mgr.open_or_create_episodic_memory(B, conf(B), "", {}):
        pass
    section("S2 cold: second new session (native collection exists, registry entry missing)")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}):
        pass
    section("S3 warm: reopen A while instance is in the LRU cache (no memory op)")

    base = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        eps = await store.add_episodes(A, entries("user_a", 2, base))
        await mem.add_memory_episodes(eps)
    section("S4 warm: add 4 episodes in one request (instance cached)")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        eps1 = await store.add_episodes(A, entries("user_b", 1, base + timedelta(hours=1)))
        await mem.add_memory_episodes(eps1)
    section("S5 warm: add 2 episodes in one request")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory("hiking trip plan", limit=20)
    section("S6 warm: search, no filter, limit=20 (default), expand_context=0")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory(
            "hiking trip plan", limit=20,
            property_filter=parse_filter("producer_id = 'user_a' OR produced_for_id = 'user_a'"),
        )
    section("S7 warm: search with OR filter, limit=20")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory(
            "hiking trip plan", limit=20, expand_context=4,
            property_filter=parse_filter("m.user_id = 'user_a'"),
        )
    section("S8 warm: search with m.user_id filter, expand_context=4")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory("hiking trip plan", limit=5, score_threshold=0.1)
    section("S9 warm: search limit=5, score_threshold=0.1")

    await mgr.close_session(A)
    section("S10 evict A from the instance cache (close_session)")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory("hiking trip plan", limit=20)
    section("S11 cold instance / warm Qdrant: reopen A after eviction, then one search")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.delete_episodes([eps[0].uid])
    section("S12 warm: delete 1 episode")

    await mgr.close_session(B)
    await mgr.delete_episodic_session(B)
    section("S13 delete session B (drop_session_partition)")

    out = os.path.join(HERE, "qdrant_request_trace.json")
    with open(out, "w") as f:
        json.dump([{"section": t, "requests": e} for t, e in SECTIONS], f, indent=1, ensure_ascii=False)
    print(f"\nwrote {out}")
    await rm.close()


if __name__ == "__main__":
    asyncio.run(main())
