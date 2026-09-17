# MemMachine 멀티유저 평가 — 구조 조사 및 설계

*작성 2026-08-10 · 브랜치 `msr_multiuser` (upstream/main `a681abf` 기준)*

**목표**: 코드만 받아 다른 리눅스 서버에서 실행하는, 멀티유저 환경의
MemMachine + 하위 벡터DB 평가 하네스.
**1차 지표**: ① 확장성 + 병목 귀속 ② 스토리지 블록 I/O 특성
**비교 대상**: event 백엔드 고정 + VectorStore 3종 (Qdrant / Milvus / SQLite-vec)

---

## 1. 지금까지 한 것 (Phase A — 완료)

### 왜 필요했나

평가 하네스가 **declarative 백엔드(Neo4j)만 쓸 수 있게 박혀 있었다.**
Qdrant·Milvus·SQLite-vec은 전부 event 백엔드에 붙는데, 그 경로로는
진입 자체가 안 됐다. 즉 비교 실험을 시작조차 할 수 없는 상태였다.

### 구멍이 둘이었다

**구멍 ①  백엔드 하드코딩**

`agent_utils.init_memmachine_params()` 가 설정에서 `vector_graph_store` 를
직접 꺼내 `LongTermMemoryParams` 를 손으로 조립하고 있었다. 서버 본체는
`long_term_memory_params_from_config()` 라는 함수로 설정을 보고 백엔드를
고르는데, 하네스만 그걸 우회하고 declarative를 하드코딩한 셈.

→ 그 함수에 위임하도록 교체. 이제 설정의 `backend:` 값으로 갈린다.

**구멍 ②  에피소드 본문이 저장되지 않음** (파고들다 발견)

서버의 실제 적재 순서는 이렇다 (`main/memmachine.py:699-704`):

```
1. episode_storage.add_episodes()   ← 본문을 INSERT … RETURNING 하고 uid(정수 PK)를 수령
2. memory.add_memory_episodes()     ← 그 uid를 인덱싱
```

그런데 하네스는 1번을 건너뛰고 2번만 불렀다. **declarative는 본문이
그래프 노드에 같이 들어가서 티가 안 났지만**, event 백엔드는 벡터스토어에
본문 없이 uid 참조만 두고 검색할 때 본문을 episode_store에서 되찾는 구조다.
uid를 발급하는 주체가 관계형DB(정수 PK)이므로 1번을 건너뛰면 유효한 uid가
없고, 복원 시 `int(uid)` 캐스팅이 터져 **모든 검색이 `Invalid episode ID`
로 실패**했다.

→ `agent_utils.ingest_episodes()` 헬퍼를 추가해 서버와 같은 순서를 복원.

### 추가 측정 대상 — 문맥 확장 (`expand_context > 0`)

검색 경로에서 **사용자 조건이 물리적으로 가속되지 않는 유일한 구간**이다.
`segment_store_sg`에는 `(partition_key, timestamp, event_uuid, index, offset)`
정렬 인덱스만 있고 `properties`(사용자 키)에는 인덱스가 없어서, 정렬 인덱스를
역순으로 걸으며 행마다 JSON을 평가해 앞뒤 N개를 채운다. LATERAL이라 seed마다
× 앞뒤 2방향 반복된다.

- 스윕 축: 프로젝트 내 사용자 수(= 대상 발화 밀도) × `expand_context` 0/3/9
- 지표: 걷는 행 수(`EXPLAIN (ANALYZE, BUFFERS)`), 구간 지연
- 주의: `expand_context` 기본값은 **0**이다. 켜지 않으면 이 경로가 열리지 않으므로
  **평가 시나리오에서 켤 것인지부터 정해야 한다**
- `created_at`을 반드시 채울 것 — 미지정 시 동률 타이브레이크가 `event_uuid`(해시)
  순서라 삽입 순서가 보존되지 않는다

상세: `memmachine_vectordb_full_guide.md` §3.6 · §5.6

### 검증 결과

| 항목 | 결과 |
|---|---|
| 백엔드 해석 (legacy/declarative/event, 우선순위, 필드 누수) | 7종 통과 |
| event 백엔드 E2E (SQLite-vec, 오프라인 임베더, 인프라 0) | 적재→검색→세션 격리 통과 |
| 회귀 — `evaluation/retrieval_agent` | 45 passed |
| 회귀 — `episodic_memory` 서버 테스트 | 243 passed, 1 skipped |
| ruff check / format | 통과 |

변경 규모: `evaluation/utils/agent_utils.py` 한 파일, +48 / −21.

### 아직 남은 것

`beam_ingest` · `wikimultihop_ingest` · `hotpotQA_test` · `longmemeval_test` 의
적재 경로는 아직 구멍 ② 패턴을 그대로 쓴다. event 백엔드로 돌리려면
`ingest_episodes()` 로 옮겨야 한다. (`locomo_ingest` 를 멀티유저 드라이버로
쓸 계획이므로 그것부터.)

---

## 2. 조사 — 일반적인 멀티유저 지원 구조

### 2.1 큰 그림: 격리 수준 3패턴

SaaS 멀티테넌시의 고전적 분류. 벡터DB든 RDB든 결국 이 셋 중 하나다.

| 패턴 | 구조 | 격리 | 비용/확장성 |
|---|---|---|---|
| **Silo** | 테넌트마다 독립 인스턴스/DB | 최강 | 최악 — 테넌트 수만큼 자원 |
| **Pool** | 전원이 하나의 저장소를 공유, 식별자 컬럼으로 구분 | 논리적 (쿼리 필터 의존) | 최고 — 자원 공유 |
| **Bridge** | 공유 인스턴스 안에서 스키마/파티션/샤드만 분리 | 중간 | 중간 |

핵심 트레이드오프: **격리를 물리적으로 올릴수록 테넌트당 고정비(인덱스,
메타데이터, 파일 핸들, 커넥션)가 붙어서 테넌트 수 확장이 먼저 죽는다.**
멀티유저 평가란 결국 "이 고정비가 N 몇에서 터지는가"를 재는 일이다.

### 2.2 벡터DB 벤더의 공식 권장

**Qdrant** — 문서가 이례적으로 단호하다.

- 권장: **단일 컬렉션 + tenant payload index + 필터링** (= Pool)
- 명시적 경고: *"테넌트마다 컬렉션을 만들지 말 것. 수백 개를 넘기면
  확장이 안 되고 자원을 낭비한다."* Qdrant Cloud는 클러스터당 컬렉션
  1,000개로 제한.
- 규모별 가이드: ~10k 테넌트는 공유 컬렉션 + payload 필터, 100k+ 는
  테넌트ID 해시 기반 **custom sharding**, 크기 편차가 크면 **tiered
  multitenancy** (큰 테넌트만 전용 샤드로 승격).
- 성능 장치: 테넌트 필드에 `is_tenant=True` 를 주면 HNSW를 전역 그래프
  대신 **테넌트별 서브그래프**로 구성한다.

**Milvus** — 4단계를 제공하고 확장성 순위를 명시.

- Database / Collection / Partition / **Partition Key**
- 확장성 순위: **Partition Key > Partition > Collection > Database**
- Database 레벨은 기본 최대 64 테넌트. 컬렉션-per-테넌트는 격리는 좋으나
  세 번째 선택지.
- 백만 단위 테넌트를 노리면 Partition Key 를 쓰라고 안내.

→ **두 벤더 모두 "테넌트당 컬렉션"을 안티패턴으로 본다.**

### 2.3 에이전트 메모리 프레임워크의 스코프 모델

| 프레임워크 | 스코프 축 |
|---|---|
| **Mem0** | `user_id` (유저 영속) / `agent_id` (에이전트별) / `run_id`(=session) / `app_id`. 대화→세션→유저→조직 계층으로 사실을 승격 |
| **Zep** | 시간 지식그래프. 엔티티=노드, 사실=유효기간 붙은 엣지 |
| **Letta** | 편집 가능한 memory block + archival memory, 에이전트가 자기 컨텍스트를 관리 |

공통점: **유저 / 에이전트 / 세션이 서로 직교하는 축**이고, 멀티에이전트
공유 메모리에서 오염 방지가 핵심 설계 과제로 다뤄진다.

---

## 3. MemMachine은 실제로 어떤 구조인가 (코드 실측)

### 3.1 스코프 모델

- **API v2**: `org_id` + `project_id` → 하나의 `session_key` 로 합성
- **API v1**: `group_id` / `agent_id[]` / `user_id[]` / `session_id`
- 내부 공용 단위는 결국 **`session_key` 문자열 하나**. 그 아래 LTM이
  `partition_key_for_session()` 으로 파티션 키를 만든다
  (`[a-z0-9_]+` 이고 32자 이하면 그대로, 아니면 sha256 앞 32자).

즉 MemMachine의 테넌트 단위 = **session_key**.

### 3.2 계층별 물리 매핑 — 이 평가의 핵심 표

**주의**: LTM 코드가 세션마다 "logical collection"을 만드는 것은 맞지만,
그게 물리 구조로 어떻게 내려가는지는 **스토어마다 완전히 다르다.**
(처음엔 "N 유저 = N 컬렉션"이라 봤는데, 구현을 읽어 보니 아니었다.)

| 계층 | 세션 N개가 물리적으로 어떻게 되나 | 2.1 분류 |
|---|---|---|
| **Qdrant** | 네이티브 컬렉션은 **`long_term_memory__<스키마해시>` 하나**. 세션은 `partition_key` payload에 `is_tenant=True` 인덱스로 구분. 분산 모드면 세션마다 custom shard key. HNSW는 `m=0, payload_m=16` → 테넌트별 서브그래프 | **Pool** (벤더 권장과 일치) |
| **Milvus** | 네이티브 컬렉션 하나 + `partition_key` 필드에 `is_partition_key=True`. 검색은 `partition_key == "<session>"` 필터 | **Pool** (벤더 최고 확장성 티어) |
| **SQLite-vec** | 단일 SQLite 파일에 `(namespace, name)` 컬럼으로 행 구분 + 컬렉션별 ANN 인덱스 파일 | Pool + 인덱스는 Bridge |
| **SegmentStore (Postgres)** | `postgresql_partition_by: LIST (partition_key)` → **세션마다 진짜 테이블 파티션 1개** | **Bridge** ⚠ |
| **episode_store** | 공유 테이블 + `session_key` 컬럼 | Pool |
| **declarative (Neo4j)** | 단일 그래프에 전부. `db.index.vector.queryNodes` 로 하나의 큰 인덱스 ANN 후 필터 | Pool |

### 3.3 여기서 나오는 가설 (= 측정해서 확인할 것)

**H1. 벡터DB 쪽은 벤더 권장을 따르고 있으므로 테넌트 수 자체로는 잘 안 터진다.**
대신 문제는 다른 데 있을 가능성이 높다 → H2, H3.

**H2. 진짜 테넌트당 물리 객체가 늘어나는 곳은 Postgres SegmentStore다.**
세션마다 LIST 파티션이 하나씩 생긴다. Postgres는 파티션 수천 개를 넘기면
쿼리 플래닝 시간과 카탈로그 부하가 급격히 나빠지는 것으로 알려져 있다.
**→ N 유저 확장의 1차 벽이 벡터DB가 아니라 여기일 수 있다.**

**H3. 앱 계층 병목.** 서버는 세션별 `EpisodicMemory` 인스턴스를 LRU 캐시
(**기본 capacity 100**, idle 수명 600초)와 세션별 RW 락으로 관리한다.
동시 활성 세션이 100을 넘으면 인스턴스 thrash가 시작된다.
**→ N=100 부근에서 꺾이는지 확인.**

**H4. SQLite-vec은 single-writer라 동시 적재에서 직렬화된다.**
공식 설정 샘플도 "multi-process 서버 배포에는 비권장"이라 적어 놨다.
예상된 결과지만, **블록 I/O가 가장 깨끗하게 보이는 구성**이기도 하다
(별도 서버 프로세스 없이 로컬 파일이라 I/O 귀속이 1:1).

**H5. Qdrant의 `m=0, payload_m=16` 설정은 테넌트 수가 많을수록 유리하지만,
테넌트 하나가 커질수록 불리할 수 있다.** 유저 수 × 유저당 데이터량의
2차원 스윕이 필요한 이유.

---

## 4. 평가 구조 정의 단계

### Step 1. 멀티유저 워크로드의 정의 (先 정의, 後 구현)

측정 전에 "유저"를 숫자로 확정해야 한다.

| 파라미터 | 정해야 할 것 | 현재 가용 자원 |
|---|---|---|
| **N** (동시 유저 수) | 스윕 범위. 1 / 10 / 50 / 100 / 200 | locomo10은 대화 10개뿐 → **session_id 복제로 합성 확장 필요** |
| **유저당 데이터량** | 세션당 에피소드 수 | locomo 대화당 세션 ~19개; longmemeval_m(2.7GB)로 대용량 확장 가능 |
| **읽기:쓰기 비율** | 적재 단계와 질의 단계를 분리할지 혼합할지 | locomo ingest/search 스크립트가 이미 분리돼 있음 |
| **동시성 형태** | 유저가 균등한가, 소수가 무거운가 (tiered) | Qdrant의 tiered multitenancy 가정을 검증하려면 편차 시나리오 필요 |
| **활성 유저 비율** | 전체 N 중 동시에 활성인 비율 | H3(LRU 100) 검증의 핵심 변수 |

**이미 있는 것**: `locomo_ingest.py` 는 대화별 `group_{idx}` 를 session_id로
쓰고 `asyncio.Semaphore(--concurrency)` (기본 10) 로 **동시 적재**한다.
멀티세션 동시 드라이버의 뼈대는 이미 존재한다. 검색 쪽도 `--concurrency`
가 있다(기본 1).
**부족한 것**: N을 데이터셋 크기 너머로 늘리는 합성 확장, 단계별 지연
히스토그램, 유저 편차 시나리오.

### Step 2. 측정 항목 확정

| 층 | 지표 | 수집 방법 |
|---|---|---|
| 클라이언트 | throughput, p50/p95/p99, 에러율 | 드라이버에 히스토그램 추가 |
| MemMachine 앱 | 단계별 지연(임베딩/검색/리랭킹), LRU 히트율, 세션 락 대기 | 기존 `PrometheusMetricsFactory` 는 **카운터만** 있음 → 지연 계측 추가 필요 |
| DB (컨테이너) | CPU/메모리/IOPS/대역폭 | cgroup v2 `io.stat`, `docker stats` |
| SSD | 처리량·지연·큐뎁스 / LBA 패턴 / 호스트 write량·WAF | `iostat`, `blktrace`·`biosnoop`, `nvme smart-log` |

### Step 3. 실행 환경 확정 — 하이브리드

```
네이티브   MemMachine 서버 코드 + 평가 하네스 (editable install)
           → 코드 수정이 즉시 반영, 이미지 재빌드 없음
Docker     Qdrant / Milvus / Postgres 만
           → 버전 고정, 볼륨을 대상 SSD에 bind-mount,
             cgroup v2 io.stat 으로 DB별 I/O 귀속
로컬 파일  SQLite-vec (대상 SSD 위)
```

리눅스에서 Docker는 호스트 커널을 그대로 쓰므로 블록 I/O 왜곡이 없다.
(맥의 OrbStack은 리눅스 VM이 껴서 불가 — 그래서 이 맥은 작성 전용.)

**필수 주의 2가지**
1. 컨테이너 데이터는 반드시 **bind-mount 볼륨**에. overlayfs 위에 쓰면
   write amplification이 섞인다.
2. 측정 전 `drop_caches` + 컨테이너 메모리 제한. 안 그러면 워킹셋이
   페이지 캐시에 다 들어가 SSD까지 I/O가 안 내려간다.

**LLM/임베더**: 사내 프록시 엔드포인트를 `provider: openai` + `base_url`
로 설정. 단, **임베딩 API 지연이 DB 성능 차이를 덮을 수 있다** — 3종
비교 구간에서는 임베딩을 사전 계산해 캐시하거나 로컬 임베더로 고정할 것.

### Step 4. 구성 등가성 검증 (측정 전 반드시)

3종을 비교하려면 "같은 조건"임을 먼저 증명해야 한다.

- N=1, 동일 데이터로 **recall이 3종 모두 일치**하는지
- ANN 파라미터가 등가인지 (Qdrant HNSW m/ef ↔ Milvus IVF nlist/nprobe 또는
  HNSW ↔ SQLite-vec usearch) — **여기가 안 맞으면 이후 수치는 전부 무의미**
- 같은 임베딩 벡터를 쓰는지

### Step 5. 스윕 실행

```
2차원 스윕:  N(동시 유저) × 유저당 데이터량
각 점에서:   적재 단계 / 검색 단계 분리 측정
비교 축:     Qdrant / Milvus / SQLite-vec
가설 확인:   H2(Postgres 파티션 벽), H3(LRU 100), H4(SQLite 직렬화)
```

### Step 6. 병목 귀속

포화점에서 어느 층이 먼저 막히는지 분리:
앱(LRU thrash·락 대기) / 벡터DB / Postgres SegmentStore / SSD.
H2가 맞다면 **벡터DB를 바꿔도 벽이 그대로**일 것이므로, 3종 비교보다
SegmentStore 설계가 더 큰 결론이 된다.

---

## 5. 근거 코드 위치

| 내용 | 위치 |
|---|---|
| 백엔드 선택 (설정 → declarative/event) | `episodic_memory/long_term_memory/service_locator.py:58` |
| 세션 → 파티션 키 변환 | 같은 파일 `:165` `partition_key_for_session()` |
| 서버의 적재 순서 (본문 저장 → 인덱싱) | `main/memmachine.py:699-704` |
| Qdrant 단일 컬렉션 + tenant payload index | `common/vector_store/qdrant_vector_store.py:620, 759-766` |
| Milvus partition key | `common/vector_store/milvus_vector_store.py:59, 679, 251` |
| Postgres 세션당 LIST 파티션 | `event_memory/segment_store/sqlalchemy_segment_store.py:166, 194` |
| 세션 인스턴스 LRU (기본 100 / 600초) | `episodic_memory/episodic_memory_manager.py:42-51, 82` |
| 세션별 RW 락 | 같은 파일 `:141` |
| Neo4j 단일 인덱스 ANN | `common/vector_graph_store/neo4j_vector_graph_store.py:511` |
| 멀티세션 동시 적재 드라이버 | `evaluation/retrieval_agent/locomo_ingest.py:70, 132` |
| 이번에 고친 하네스 | `evaluation/utils/agent_utils.py` |

## 참고 자료

- [Qdrant — Multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/)
- [Qdrant — How to Implement Multitenancy and Custom Sharding](https://qdrant.tech/articles/multitenancy/)
- [Qdrant 1.16 — Tiered Multitenancy & Disk-Efficient Vector Search](https://qdrant.tech/blog/qdrant-1.16.x/)
- [Milvus — Implement Multi-tenancy](https://milvus.io/docs/multi_tenancy.md)
- [Milvus — Designing Multi-Tenancy RAG: Best Practices](https://milvus.io/blog/build-multi-tenancy-rag-with-milvus-best-practices-part-one.md)
- [Mem0 — How to Design Multi-Agent Memory Systems for Production](https://mem0.ai/blog/multi-agent-memory-systems)
