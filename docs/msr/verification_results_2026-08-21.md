# 확인 요청 5건 — 검증 결과

*2026-08-21 · 기준 `upstream/main` `2d28c1c` (무수정) · 코드 추적 + 실행 실증*
*요청: 박준혁 TL 실측 목록 / 회신: 오태진*

---

## 요약

| # | 항목 | 상태 | 결론 |
|---|---|---|---|
| **1** | session_key 조립 규칙 | ✅ **확정** | `org_id/project_id` **뿐**. 세션 식별자 없음 → **파티션 수 = 프로젝트 수** |
| **2** | properties_schema → indexed_properties_schema | ✅ **확정 (실증)** | 전달됨. `user_id` 색인 대상에 포함 |
| **3** | distributed shard_number 기본값 | 🔶 **코드로 좁힘** | MemMachine이 **미지정** → Qdrant 기본값. **2노드 실측 필요** |
| **4** | Milvus AUTOINDEX 실체 | 🔶 **코드로 좁힘** | `index_type="AUTOINDEX"` 명시, `num_partitions` 미지정. **실측 필요** |
| **5** | Postgres SegmentStore 동작 | ✅ **확정** | main에서 유효. 파티션당 테이블 2개 → 1번과 연동해 **2 × 프로젝트 수** |

> **1번이 확정되었으므로 실험 매트릭스와 v3 문서 확정 진행 가능.**
> 실측이 남은 것은 **3·4번뿐**(둘 다 라이브 서버 필요).

> ⚠️ **추가 발견**: 3종 스토어 간 **사용자 metadata 색인 비대칭** (→ §6).
> 3종 비교 설계에 영향을 주므로 확인 목록에 추가 필요.

---

## 1. session_key 조립 규칙 — ✅ 확정

### 결론

> **`session_key = f"{org_id}/{project_id}"` 뿐이다. 그 아래 별도 세션 식별자는 붙지 않는다.**
> 따라서 **파티션 수 = 프로젝트 수**이며, 대화 세션 수와 무관하다.

### 근거 ① — 조립 지점이 단 하나

```
api_v2/service.py:44    _SessionData.session_key  →  f"{org_id}/{project_id}"
router.py:908,936,964,990,1016,1042              →  동일 식 (전부 config 조회/설정 엔드포인트)
```

`main/memmachine.py:477` 의 `user_conf.session_key = session_key` 는
`_with_default_episodic_memory_conf()` 안에서 **같은 값을 설정으로 전파**할 뿐 가공하지 않는다.

### 근거 ② — 호출부 전수 (2곳, 둘 다 원본 그대로)

```python
# main/memmachine.py:712 (적재)  /  :771 (검색)
async with episodic_memory_manager.open_or_create_episodic_memory(
    session_key=session_data.session_key,          # ← 접미사·결합 없음
    description="",
    episodic_memory_config=self._with_default_episodic_memory_conf(
        session_key=session_data.session_key
    ),
    metadata={},
) as episodic_session:
```

`open_or_create_episodic_memory` / `_create_episodic_memory` 호출부를 전수 조사한 결과
서버 경로에서 session_key를 가공하는 지점은 없다.

### 근거 ③ — 런타임 해시 일치 (결정적)

```
sha256("org1/prj1")[:32]  =  baf1a5e6a767ce9f628b16fe0614a887
실제 실행에서 관측된 partition_key = baf1a5e6a767ce9f628b16fe0614a887   ✅ 완전 일치
```

`partition_key_for_session()` 은 `[a-z0-9_]+` 이고 32자 이하면 원본을 쓰고, 아니면 sha256 앞 32자를 쓴다.
`org1/prj1` 은 슬래시를 포함하므로 해시 경로를 탄다.
**관측값이 `sha256(정확히 "org1/prj1")` 과 일치**하므로, session_key에 아무것도 덧붙지 않음이 실측으로 증명된다.

### 근거 ④ — API 스펙에 세션 식별자 필드 자체가 없음

`packages/common/src/memmachine_common/api/spec.py` 에 `session_id` / `thread_id` /
`conversation_id` / `run_id` 필드 없음.

### 실험 설계에 미치는 영향

| 구성 | 프로젝트 수 | 파티션 수 | Postgres 테이블 |
|---|---|---|---|
| 프로젝트 1개 공용 | 1 | 1 | **2개** |
| 사용자당 프로젝트 (500명) | 500 | 500 | **1,000개** |

**대화 세션 수로는 늘지 않는다.** 우려했던 "세션 수만큼 파티션 폭발"은 발생하지 않음.

### 직접 확인

```bash
SRV=packages/server/src/memmachine_server
sed -n '39,46p' $SRV/server/api_v2/service.py
grep -rn "session_key = \|def session_key" $SRV/server $SRV/main | grep -v __pycache__
sed -n '705,725p' $SRV/main/memmachine.py
python3 -c "import hashlib; print(hashlib.sha256(b'org1/prj1').hexdigest()[:32])"
```

---

## 2. properties_schema → indexed_properties_schema — ✅ 확정 (실증)

### 결론

> **전달된다.** `properties_schema` 의 키가 컬렉션의 `indexed_properties_schema` 에
> **bare 키 그대로** 포함된다.

### 실행 결과

설정:
```yaml
episodic_memory:
  long_term_memory:
    backend: event
    properties_schema:
      user_id: str
      session_id: str
```

출력:
```
설정의 properties_schema : {'user_id': 'str', 'session_id': 'str'}
병합 후 conf 타입        : EventLongTermMemoryConf
병합 후 properties_schema: {'user_id': 'str', 'session_id': 'str'}

=== 컬렉션 indexed_properties_schema ===
시스템/내부 키 : _content_type _created_at _episode_type _episode_uid _produced_for_id
                 _producer_id _producer_role _segment_uuid _sequence_num _session_key _timestamp
사용자 키      : session_id, user_id
  user_id      색인 대상 포함? -> ✅ 예
  session_id   색인 대상 포함? -> ✅ 예
```

### 경로

```
ProjectConfig.properties_schema  (또는 설정 파일)
  → LongTermMemoryConfPartial.properties_schema
  → EventLongTermMemoryConf.properties_schema
  → service_locator.py  _resolve_user_properties_schema()
  → VectorStoreCollectionConfig.indexed_properties_schema
       = { **EventMemory.expected_vector_store_collection_schema(),
           **EVENT_BACKEND_SYSTEM_FIELDS,      # 9종
           **user_schema }                     # ← 등록분
```

### 부수 확인

내부 키는 9종이 아니라 **11종**이다.
`EVENT_BACKEND_SYSTEM_FIELDS` 9종 + EventMemory 자체 필드 `_segment_uuid`, `_timestamp`.

### ⚠ 단, 이것이 곧 "색인 생성"을 뜻하지는 않는다

`indexed_properties_schema` 에 들어간다는 것과, 스토어가 **실제로 색인을 만드는지**는 별개다.
스토어별 차이는 §6 참조.

---

## 3. distributed 시 shard_number — 🔶 코드로 좁힘 · 실측 필요

### 코드에서 확인된 것

| 항목 | 상태 |
|---|---|
| `shard_number` | **지정하지 않음** → Qdrant 기본값 적용 |
| `sharding_method` | `CUSTOM` (단, `is_distributed=True` 일 때만) |
| 세션별 샤드 키 | `_ensure_shard_key(native_collection, name)` — 세션마다 `create_shard_key` 호출 |
| 검색 시 | `shard_key_selector=self._shard_key` 로 해당 샤드만 조회 |
| `is_distributed` | 설정값 (`database_conf.py:254`), **기본 false** |

```python
# qdrant_vector_store.py:755
sharding_method=(models.ShardingMethod.CUSTOM if self._is_distributed else None)
# :847, :886
if self._is_distributed:
    await self._ensure_shard_key(native_collection_name, name)
```

→ **"미지정 = 노드 수"라는 문서상 서술을 custom 모드에 적용한 것이라 [추정] 상태**라는 지적이 맞다.
코드가 값을 주지 않으므로 실제 동작은 Qdrant 버전·클러스터 구성에 달려 있다.

### 실측 절차 (2노드 환경)

```bash
# 1) 컬렉션 클러스터 정보 — 실제 샤드 수와 노드 배치
curl -s localhost:6333/collections/<컬렉션명>/cluster | jq

# 2) 샤드 키 목록 (custom sharding 시)
curl -s localhost:6333/collections/<컬렉션명> | jq '.result.config.params'

# 3) 파티션 키 하나가 몇 개 샤드로 갈리는지
#    프로젝트 여러 개 생성 후 위 1) 재확인
```

**확인할 것**: ① 샤드 총 개수 ② 파티션 키 1개 → 샤드 몇 개 ③ 노드별 배치 균형

---

## 4. Milvus AUTOINDEX 실체 — 🔶 코드로 좁힘 · 실측 필요

### 코드에서 확인된 것

```python
# milvus_vector_store.py:691-698
index_params = self._client.prepare_index_params()
index_params.add_index(
    field_name=_VECTOR_FIELD,
    index_type="AUTOINDEX",                      # ← 명시적으로 AUTOINDEX 요청
    metric_type=self._SIMILARITY_METRIC_TO_MILVUS_METRIC[config.similarity_metric],
)
```

| 항목 | 상태 |
|---|---|
| 벡터 인덱스 타입 | `"AUTOINDEX"` **명시** → 실제 타입은 Milvus가 결정 |
| `num_partitions` | **지정하지 않음** → Milvus 기본값 |
| 파티션 키 | `_PARTITION_KEY_FIELD` 에 `is_partition_key=True` |
| 사용자 속성 저장 | `_PROPERTIES_FIELD` — **`DataType.JSON` 단일 필드** |
| 속성 색인 | **`add_index` 는 벡터 필드에만 호출** → 스칼라/JSON 색인 없음 |

### 실측 절차

```python
from pymilvus import MilvusClient
c = MilvusClient(uri="http://localhost:19530")

# 실제 선택된 인덱스 타입
print(c.describe_index(collection_name="<이름>", index_name="<벡터필드>"))

# 실제 물리 파티션 수 (기본 64 여부 확인)
print(len(c.list_partitions(collection_name="<이름>")))

# 컬렉션 스키마에서 partition key 필드 및 num_partitions
print(c.describe_collection(collection_name="<이름>"))
```

**확인할 것**: ① AUTOINDEX가 실제로 무엇으로 해석되었는지 ② 물리 파티션 수(기본값) ③ 파티션 키 필드 반영 여부

---

## 5. Postgres SegmentStore — ✅ 확정 (main 기준 유효)

### 결론

> main 기준으로도 **`partition_key` 마다 자식 테이블 2개**가 생성된다.
> 1번 결과와 연동하면 **테이블 수 = 2 × 프로젝트 수**.

### 근거

```python
# sqlalchemy_segment_store.py:1045  _create_pg_child_tables()
CREATE TABLE "segment_store_sg_p_<partition_key>"     PARTITION OF segment_store_sg     ...
CREATE TABLE "segment_store_dv_ln_p_<partition_key>"  PARTITION OF segment_store_dv_ln  ...
```

```python
# :166, :194  테이블 정의
{"postgresql_partition_by": "LIST (partition_key)"}
# :801  생성 전 잠금
LOCK TABLE segment_store_pt IN SHARE ROW EXCLUSIVE MODE     # 자기충돌 → 전역 직렬화
```

### 규모

| 구성 | 프로젝트 수 | 자식 테이블 수 |
|---|---|---|
| 프로젝트 1개 공용 | 1 | **2** |
| 사용자당 프로젝트 (100명) | 100 | **200** |
| 사용자당 프로젝트 (500명) | 500 | **1,000** |

**세션 단위가 아니라 프로젝트 단위**이므로, 우려했던 폭발 규모는 아니다.
다만 사용자당 프로젝트 구성에서는 여전히 500명 = 1,000개다.

### 실측 절차

```bash
psql -c "SELECT count(*) FROM pg_class WHERE relispartition;"
psql -c "\d+ segment_store_sg"
psql -c "SELECT relname FROM pg_class WHERE relname LIKE 'segment_store_sg_p_%' LIMIT 5;"
# 동시 신규 프로젝트 생성 시 DDL 대기 관찰
psql -c "SELECT * FROM pg_locks WHERE mode = 'ShareRowExclusiveLock';"
```

---

## 6. ⚠ 추가 발견 — 3종 스토어의 사용자 metadata 색인 비대칭

### 문제

`indexed_properties_schema` 에 `user_id` 가 들어가더라도(§2), **실제로 색인을 만드는 것은 Qdrant뿐**이다.

| 스토어 | `indexed_properties_schema` 사용 방식 | 사용자 metadata 색인 |
|---|---|---|
| **Qdrant** | `:767` 스키마를 순회하며 `create_payload_index()` 호출 | ✅ **생성됨** |
| **Milvus** | 레지스트리 기록/속성 추출용으로만 참조 | ❌ **없음** (속성은 JSON 필드, 벡터 색인만 생성) |
| **SQLite-vec** | **참조 0건** | ❌ 없음 |

```
Qdrant  : qdrant_vector_store.py:281, 767, 811  (색인 생성에 사용)
Milvus  : milvus_vector_store.py:193, 454, 629, 730  (기록/추출용)
SQLite  : sqlite_vector_store.py  — 검색 결과 없음
```

### 영향

**3종 비교에서 `m.user_id` 필터 성능이 등가가 아니다.**
Qdrant만 payload 색인을 갖고, Milvus·SQLite-vec은 색인 없이 평가된다.
이 상태로 측정하면 "Qdrant가 빠르다"는 결과가 나오지만, 그것은 **벡터 검색 성능 차이가 아니라
색인 유무 차이**다.

### 대응 (택 1)

| 안 | 내용 |
|---|---|
| **A. 보정** | 사용자 필터를 쓰지 않는 시나리오로 비교하거나, Milvus 쪽에 수동으로 색인을 추가해 조건을 맞춘다 |
| **B. 결과로 보고** | "이 비대칭 자체가 MemMachine의 스토어 지원 성숙도 차이"로 기록하고, 필터 유/무 두 조건 모두 측정 |

**권장: B + A 병행** — 필터 없는 조건(등가)과 필터 있는 조건(비대칭 노출)을 모두 측정하면
비대칭의 크기 자체가 데이터가 된다.

---

## 부록 A. 검증 재현

### 1번 (session_key)

```bash
cd /Users/taejin/Projects/MemMachine/repo
SRV=packages/server/src/memmachine_server
sed -n '39,46p' $SRV/server/api_v2/service.py
grep -rn "session_key = \|def session_key" $SRV/server $SRV/main | grep -v __pycache__
grep -rn "open_or_create_episodic_memory" $SRV | grep -v __pycache__ | grep -v "def "
python3 -c "import hashlib; print(hashlib.sha256(b'org1/prj1').hexdigest()[:32])"
```

### 2번 (properties_schema)

`docs/msr/verify/smoke_event.yml` 의 `long_term_memory` 블록에 아래를 추가한 뒤
`docs/msr/verify/verify_schema.py` 실행:

```yaml
    properties_schema:
      user_id: str
      session_id: str
```

### 5번 (Postgres)

```bash
grep -n "postgresql_partition_by" \
  $SRV/episodic_memory/event_memory/segment_store/sqlalchemy_segment_store.py
sed -n '1045,1062p' $SRV/episodic_memory/event_memory/segment_store/sqlalchemy_segment_store.py
sed -n '799,804p' $SRV/episodic_memory/event_memory/segment_store/sqlalchemy_segment_store.py
```

### 6번 (색인 비대칭)

```bash
for f in qdrant milvus sqlite; do
  echo "--- $f"
  grep -c "indexed_properties_schema" $SRV/common/vector_store/${f}_vector_store.py 2>/dev/null \
    || echo 0
done
grep -n "create_payload_index" $SRV/common/vector_store/qdrant_vector_store.py
grep -n "add_index" $SRV/common/vector_store/milvus_vector_store.py
```

## 부록 B. 근거 코드 위치

경로: `packages/server/src/memmachine_server/`

| 내용 | 파일 · 심볼 |
|---|---|
| session_key 조립 | `server/api_v2/service.py` · `_SessionData.session_key` |
| 세션 인스턴스 획득 (2곳) | `main/memmachine.py:712, 771` · `open_or_create_episodic_memory()` |
| 설정 전파 | `main/memmachine.py:477` · `_with_default_episodic_memory_conf()` |
| 세션 → 파티션 키 | `episodic_memory/long_term_memory/service_locator.py` · `partition_key_for_session()` |
| 색인 스키마 조립 | 〃 · `_event_params()`, `_resolve_user_properties_schema()` |
| Qdrant 샤딩·payload 색인 | `common/vector_store/qdrant_vector_store.py` · `_create_native_collection()`, `_ensure_shard_key()` |
| Milvus 스키마·인덱스 | `common/vector_store/milvus_vector_store.py` · 컬렉션 생성부 |
| Postgres 파티션 DDL·잠금 | `episodic_memory/event_memory/segment_store/sqlalchemy_segment_store.py` · `_create_pg_child_tables()`, `_PG_LOCK_PARTITIONS_TABLE` |
