"""Count embedding API calls per add / per search on speedkick a8322a7.

Runs a local OpenAI-compatible /v1/embeddings stub so every HTTP request the
OpenAIEmbedder actually makes is logged (inputs per request, total chars).
Also wraps Embedder.ingest_embed / search_embed to separate the logical call
count from the HTTP request count (batch_size splitting, chunk clustering).

Real EpisodicMemoryManager + real Qdrant/PG, so cache hits/misses match prod.
"""

import asyncio
import json
import os
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from memmachine_server.common.configuration import Configuration
from memmachine_server.common.configuration.episodic_config import (
    EpisodicMemoryConf,
    LongTermMemoryConfPartial,
)
from memmachine_server.common.configuration.episodic_config import (
    SentenceTextDeriverConf,
)
from memmachine_server.common.embedder.embedder import Embedder
from memmachine_server.common.episode_store import EpisodeEntry
from memmachine_server.common.resource_manager.resource_manager import (
    ResourceManagerImpl,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18099

HTTP_LOG: list[dict] = []
CALL_LOG: list[dict] = []
SECTIONS: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        inputs = body.get("input") or []
        if isinstance(inputs, str):
            inputs = [inputs]
        dims = body.get("dimensions") or 1536
        HTTP_LOG.append(
            {
                "path": self.path,
                "n_inputs": len(inputs),
                "total_chars": sum(len(t) for t in inputs),
                "max_chars": max((len(t) for t in inputs), default=0),
                "dimensions_param": "dimensions" in body,
            }
        )
        out = {
            "object": "list",
            "model": body.get("model", "stub"),
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.0] * (dims - 1) + [1.0]}
                for i in range(len(inputs))
            ],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
        payload = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:  # silence
        return


_orig_ingest = Embedder.ingest_embed
_orig_search = Embedder.search_embed


async def _traced_ingest(self, inputs, max_attempts=1):
    inputs = list(inputs)
    CALL_LOG.append({"kind": "ingest_embed", "n_inputs": len(inputs),
                     "total_chars": sum(len(str(t)) for t in inputs),
                     "batch_size": self.batch_size, "max_attempts": max_attempts})
    return await _orig_ingest(self, inputs, max_attempts)


async def _traced_search(self, queries, max_attempts=1):
    queries = list(queries)
    CALL_LOG.append({"kind": "search_embed", "n_inputs": len(queries),
                     "total_chars": sum(len(str(q)) for q in queries),
                     "batch_size": self.batch_size, "max_attempts": max_attempts})
    return await _orig_search(self, queries, max_attempts)


Embedder.ingest_embed = _traced_ingest
Embedder.search_embed = _traced_search


def section(title: str) -> None:
    calls, https = list(CALL_LOG), list(HTTP_LOG)
    CALL_LOG.clear()
    HTTP_LOG.clear()
    SECTIONS.append({"section": title, "calls": calls, "http": https})
    kinds = Counter(c["kind"] for c in calls)
    print(f"\n■ {title}")
    print(f"   embedder calls = {len(calls)} {dict(kinds)}   ->   HTTP /v1/embeddings = {len(https)}")
    for c in calls:
        print(f"     call  {c['kind']:<13} inputs={c['n_inputs']:<5} chars={c['total_chars']:<8} batch_size={c['batch_size']}")
    for h in https:
        print(f"     HTTP  inputs={h['n_inputs']:<5} chars={h['total_chars']:<8} max_chars={h['max_chars']:<7} dims_param={h['dimensions_param']}")


def entries(uid: str, n: int, base: datetime, text: str | None = None) -> list[EpisodeEntry]:
    return [
        EpisodeEntry(
            content=text or f"[{uid}|t{i}] hiking trip plan message number {i}",
            producer_id=uid, producer_role="user", produced_for_id="assistant",
            metadata={"user_id": uid}, created_at=base + timedelta(seconds=i),
        )
        for i in range(n)
    ]


async def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    cfg = Configuration.load_yml_file(os.path.join(HERE, "config_embed.yml"))
    rm = ResourceManagerImpl(cfg)

    def conf(session_key: str, **over) -> EpisodicMemoryConf:
        partial = LongTermMemoryConfPartial(session_id=session_key, **over)
        ltm = partial.merge(cfg.episodic_memory.long_term_memory)
        return EpisodicMemoryConf(
            session_key=session_key, metrics_factory_id="prometheus",
            long_term_memory=ltm, short_term_memory=None,
            long_term_memory_enabled=True, short_term_memory_enabled=False,
        )

    mgr = await rm.get_episodic_memory_manager()
    store = await rm.get_episode_storage()
    base = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    A, B, C = "orge/prja", "orge/prjb", "orge/prjc"

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}):
        pass
    section("E1 first session open: embedder built with validate=True")

    async with mgr.open_or_create_episodic_memory(B, conf(B), "", {}):
        pass
    section("E2 second new session: embedder already cached in this process")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        eps = await store.add_episodes(A, entries("user_a", 4, base))
        await mem.add_memory_episodes(eps)
    section("E3 add: 4 episodes in one request (passthrough + whole_text)")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        e1 = await store.add_episodes(A, entries("user_a", 1, base + timedelta(hours=1)))
        await mem.add_memory_episodes(e1)
    section("E4 add: 1 episode")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory("hiking trip plan", limit=20)
    section("E5 search: no filter, top_k=20")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory("hiking trip plan", limit=5, expand_context=4)
    section("E6 search: expand_context=4, top_k=5")

    long_text = "가" * 160_000
    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        el = await store.add_episodes(A, entries("user_a", 1, base + timedelta(hours=2), text=long_text))
        await mem.add_memory_episodes(el)
    section("E7 add: 1 very long episode (160k chars -> chunk_text at 75k)")

    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        many = await store.add_episodes(A, entries("user_a", 2100, base + timedelta(hours=3)))
        await mem.add_memory_episodes(many)
    section("E8 add: 2100 episodes in one request (max 2048 inputs per API request)")

    async with mgr.open_or_create_episodic_memory(C, conf(C, embedder="stub_embedder_batch2"), "", {}) as mem:
        eb = await store.add_episodes(C, entries("user_c", 5, base + timedelta(hours=4)))
        await mem.add_memory_episodes(eb)
    section("E9 add: 5 episodes, embedder configured with batch_size=2")

    D = "orge/prjd"
    async with mgr.open_or_create_episodic_memory(
        D, conf(D, deriver=SentenceTextDeriverConf()), "", {}
    ) as mem:
        sent = await store.add_episodes(
            D, entries("user_d", 2, base + timedelta(hours=5),
                       text="First sentence here. Second sentence here. Third sentence here."),
        )
        await mem.add_memory_episodes(sent)
    section("E10 add: 2 episodes with sentence_text deriver (3 sentences each)")

    await mgr.close_session(A)
    async with mgr.open_or_create_episodic_memory(A, conf(A), "", {}) as mem:
        await mem.query_memory("hiking trip plan", limit=20)
    section("E11 search after instance-cache eviction (cold instance)")

    out = os.path.join(HERE, "embedding_call_trace.json")
    with open(out, "w") as f:
        json.dump(SECTIONS, f, indent=1, ensure_ascii=False)
    print(f"\nwrote {out}")
    await rm.close()
    server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
