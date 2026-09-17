"""[2] properties_schema -> indexed_properties_schema 전달 여부 실증 (upstream 코드만)."""
import asyncio, hashlib, math, sys
from pathlib import Path
S = Path(__file__).parent

from memmachine_server.common.configuration import Configuration
from memmachine_server.common.configuration.episodic_config import (
    EpisodicMemoryConf, LongTermMemoryConfPartial)
from memmachine_server.common.data_types import SimilarityMetric
from memmachine_server.common.embedder.embedder import Embedder
from memmachine_server.common.resource_manager.resource_manager import ResourceManagerImpl
from memmachine_server.episodic_memory.episodic_memory import EpisodicMemory
from memmachine_server.episodic_memory.service_locator import episodic_memory_params_from_config

DIM = 64
class H(Embedder):
    def __init__(self): super().__init__(batch_size=None)
    def _v(self,t):
        v=[0.0]*DIM
        for tok in str(t).lower().split():
            v[int(hashlib.sha256(tok.encode()).hexdigest()[:8],16)%DIM]+=1.0
        n=math.sqrt(sum(x*x for x in v)) or 1.0
        return [x/n for x in v]
    async def _ingest_embed(self,i,max_attempts=1): return [self._v(x) for x in i]
    async def _search_embed(self,q,max_attempts=1): return [self._v(x) for x in q]
    @property
    def model_id(self): return "h"
    @property
    def dimensions(self): return DIM
    @property
    def similarity_metric(self): return SimilarityMetric.COSINE

async def main():
    cfg = Configuration.load_yml_file(str(S/"smoke_schema.yml"))
    rm = ResourceManagerImpl(cfg)
    fake=H()
    async def ge(name, validate=False): return fake
    rm.get_embedder = ge

    print("설정의 properties_schema :", cfg.episodic_memory.long_term_memory.properties_schema)

    SESSION="org1/prj1"
    ltm = LongTermMemoryConfPartial(session_id=SESSION).merge(cfg.episodic_memory.long_term_memory)
    print("병합 후 conf 타입        :", type(ltm).__name__)
    print("병합 후 properties_schema:", ltm.properties_schema)

    conf = EpisodicMemoryConf(session_key=SESSION, long_term_memory=ltm,
        short_term_memory=None, long_term_memory_enabled=True, short_term_memory_enabled=False)
    mem = EpisodicMemory(await episodic_memory_params_from_config(conf, rm))
    coll = mem.long_term_memory._event_memory._vector_store_collection

    schema = coll.config.indexed_properties_schema
    print("\n=== 컬렉션 indexed_properties_schema ===")
    sys_f = sorted(k for k in schema if k.startswith("_"))
    usr_f = sorted(k for k in schema if not k.startswith("_"))
    print("시스템/내부 키 :", sys_f)
    print("사용자 키      :", usr_f)
    for k in ("user_id","session_id"):
        print(f"  {k:12} 색인 대상 포함? ->", "✅ 예" if k in schema else "❌ 아니오")
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
