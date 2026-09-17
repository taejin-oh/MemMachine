"""event 백엔드 필터 검증 — 수정본을 전혀 사용하지 않는 순수 upstream 테스트.

- evaluation/ (우리가 수정한 평가 하네스)를 import 하지 않는다.
- memmachine_server 패키지만 사용하며, 서버(main/memmachine.py:680-720)와
  동일한 순서로 적재한다:
      ① episode_storage.add_episodes()   원문 저장 + uid 발급
      ② episodic.add_memory_episodes()   인덱싱
- 유일한 테스트 더블: 임베더 (네트워크/API 키 제거 목적).
  필터 로직과는 무관한 계층이다.
"""

import asyncio
import hashlib
import math
import sys
from pathlib import Path

SCRATCH = Path(__file__).parent

# ── upstream 서버 패키지만 import (evaluation/* 는 일절 사용하지 않음) ──
from memmachine_server.common.configuration import Configuration
from memmachine_server.common.configuration.episodic_config import (
    EpisodicMemoryConf,
    LongTermMemoryConfPartial,
)
from memmachine_server.common.data_types import SimilarityMetric
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

DIM = 64
SESSION = "org1/prj1"  # 서버에서 org_id/project_id 로 합성되는 값과 동일 형식


class HashEmbedder(Embedder):
    """결정적 해시 임베더 — 네트워크 없이 재현 가능하게 하기 위한 테스트 더블."""

    def __init__(self) -> None:
        super().__init__(batch_size=None)

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for tok in str(text).lower().split():
            h = int(hashlib.sha256(tok.encode()).hexdigest()[:8], 16)
            v[h % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def _ingest_embed(self, inputs, max_attempts=1):
        return [self._vec(i) for i in inputs]

    async def _search_embed(self, queries, max_attempts=1):
        return [self._vec(q) for q in queries]

    @property
    def model_id(self) -> str:
        return "hash"

    @property
    def dimensions(self) -> int:
        return DIM

    @property
    def similarity_metric(self) -> SimilarityMetric:
        return SimilarityMetric.COSINE


FACTS = [
    "I like vegetarian food and pasta",
    "My favorite database is postgres",
    "I work on storage systems",
    "I enjoy hiking on weekends",
]
QUERY = "what food do I like"


async def main() -> int:
    cfg = Configuration.load_yml_file(str(SCRATCH / "smoke_event.yml"))
    rm = ResourceManagerImpl(cfg)

    fake = HashEmbedder()

    async def _get_embedder(name, validate=False):  # noqa: ARG001
        return fake

    rm.get_embedder = _get_embedder  # 유일한 더블

    # ── 설정에서 EpisodicMemory 구성 (전부 upstream 타입/함수) ──
    # 단기 기억은 이 검증과 무관하므로 비활성화한다. 그 외 장기 기억 구성은
    # 서버와 동일하게 upstream 의 episodic_memory_params_from_config() 가 수행한다.
    ltm_conf = LongTermMemoryConfPartial(session_id=SESSION).merge(
        cfg.episodic_memory.long_term_memory
    )
    conf = EpisodicMemoryConf(
        session_key=SESSION,
        long_term_memory=ltm_conf,
        short_term_memory=None,
        long_term_memory_enabled=True,
        short_term_memory_enabled=False,
    )
    memory = EpisodicMemory(await episodic_memory_params_from_config(conf, rm))

    ltm = memory.long_term_memory
    assert getattr(ltm, "_event_memory", None) is not None, "event 백엔드가 아님"
    print(f"backend        : EventMemory (partition={ltm._partition_key})")  # noqa: SLF001
    print(f"vector store   : {type(ltm._vector_store).__name__}")  # noqa: SLF001

    episode_storage = await rm.get_episode_storage()

    # ── 서버(main/memmachine.py:700,720)와 동일한 순서로 적재 ──
    for uid in ("user_a", "user_b"):
        entries = [
            EpisodeEntry(
                content=f"[{uid}] {fact}",
                producer_id=uid,
                producer_role="user",
                metadata={"user_id": uid, "idx": i},  # 자유 metadata
            )
            for i, fact in enumerate(FACTS)
        ]
        episodes = await episode_storage.add_episodes(SESSION, entries)  # ①
        await memory.add_memory_episodes(episodes=episodes)  # ②
    print(f"ingested       : user_a {len(FACTS)}건 + user_b {len(FACTS)}건 (같은 파티션)\n")

    async def search(expr: str | None):
        f = parse_filter(expr) if expr else None
        resp = await memory.query_memory(QUERY, limit=10, property_filter=f)
        return [e.content for e in (resp.long_term_memory.episodes if resp else [])]

    ok = True

    r_all = await search(None)
    a_cnt = sum(1 for t in r_all if t.startswith("[user_a]"))
    b_cnt = sum(1 for t in r_all if t.startswith("[user_b]"))
    print(f"① 필터 없음                  : {len(r_all)}건 (user_a {a_cnt} / user_b {b_cnt})")
    if a_cnt == 0 or b_cnt == 0:
        print("   △ 두 사용자가 섞이지 않음 — 전제 미성립")
        ok = False

    for label, expr, want in (
        ("② m.user_id='user_a'        ", "m.user_id = 'user_a'", "[user_a]"),
        ("③ metadata.user_id='user_b' ", "metadata.user_id = 'user_b'", "[user_b]"),
        ("④ producer_id='user_a'      ", "producer_id = 'user_a'", "[user_a]"),
    ):
        res = await search(expr)
        leak = [t for t in res if not t.startswith(want)]
        mark = "✅" if (res and not leak) else "❌"
        print(f"{label}: {len(res)}건, 유출 {len(leak)}건  {mark}")
        if not res or leak:
            ok = False

    print()
    print("PASS — upstream 코드만으로 event 백엔드 필터 동작 확인" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
