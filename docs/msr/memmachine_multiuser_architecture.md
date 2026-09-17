# MemMachine 다중 사용자 지원 방식과 구조

*작성 2026-08-19 · 기준 코드: upstream/main `a681abf` (메인라인 최신)*
*코드 실측 기반. 각 절 끝에 근거 파일:라인 표기.*

---

## 0. 한눈에 보기

```
                    클라이언트 (인증 없음)
                          │  POST /api/v2/memories { org_id, project_id, messages[] }
                          ▼
              ┌───────────────────────────────┐
              │  FastAPI  /api/v2  (v1 없음)   │   워커 기본 1개
              │  session_key = "org_id/project_id"
              └───────────────┬───────────────┘
                              ▼
              ┌───────────────────────────────┐
              │  MemMachine 파사드             │
              │  ① episode_store 에 원문 저장  │
              │  ② 메모리 백엔드에 인덱싱      │
              └───────┬───────────────┬───────┘
                      ▼               ▼
          ┌───────────────────┐  ┌──────────────────────┐
          │ 에피소딕 메모리    │  │ 시맨틱(프로필) 메모리 │
          │ 격리 = session_key │  │ 격리 = set_id        │
          │ (= org/project)    │  │ (org/project/user)   │
          │ EpisodicMemoryMgr  │  └──────────────────────┘
          │  LRU 100 + 세션락  │
          └─────────┬──────────┘
                    ▼
      벡터DB(Qdrant/Milvus/SQLite-vec) + Postgres + (Neo4j/Nebula)
```

**핵심 한 줄**: MemMachine에는 "사용자(user)"라는 1급 개념이 없다.
테넌트 단위는 **`org_id/project_id` 로 만든 `session_key` 문자열 하나**이고,
개별 사용자는 ① 프로젝트를 사용자마다 파는 방식 ② 에피소드의
`producer_id` 를 필터로 거는 방식 ③ 시맨틱 메모리의 `UserSet` — 셋 중
하나로 **애플리케이션이 알아서 표현**해야 한다.

---

## 1. API 표면 — v2 단일, 인증 없음

- 메인라인에는 **`/api/v2` 라우터 하나만** 마운트된다. 예전 v1
  (`group_id`/`agent_id[]`/`user_id[]`/`session_id`) 은 서버에서 사라졌다.
  (평가 유틸에 남아 있는 `memmachine_helper_restapiv1.py` 는 구버전 서버용
  클라이언트 잔재.)
- 미들웨어는 **액세스 로그와 메트릭뿐 — 인증·인가·레이트리밋 없음.**
  즉 `org_id`/`project_id` 는 **신뢰되는 입력**이고, 호출자가 남의
  `org_id` 를 넣으면 그대로 그 데이터에 접근한다.
  → 멀티테넌시는 "데이터 분리" 수준이며 **보안 경계가 아니다.**

> 근거: `server/app.py:107`, `api_v2/router.py:1090-1094`, `server/middleware.py`

---

## 2. 신원(identity) 모델 — 무엇이 "사용자"인가

### 2.1 테넌트 키: `session_key`

```python
@dataclass(frozen=True)
class _SessionData:
    org_id: str
    project_id: str

    @property
    def session_key(self) -> str:
        return f"{self.org_id}/{self.project_id}"
```

시스템 전체가 이 **문자열 하나**로 돌아간다. 세션 테이블의 PK,
메모리 인스턴스 캐시의 키, 스토리지 파티션 키가 전부 여기서 파생된다.

### 2.2 에피소드에 붙는 사람 정보

적재 시 메시지마다 다음이 따라 붙는다 (격리 키가 아니라 **속성**):

| 필드 | 뜻 |
|---|---|
| `producer_id` | 이 발화를 만든 주체 (사람 또는 에이전트) |
| `producer_role` | 역할 (user / assistant 등) |
| `produced_for_id` | 수신 대상 |

이 값들은 **필터 가능한 시스템 필드**로 색인된다
(`producer_id`, `producer_role`, `produced_for_id`, `session_key`,
`episode_type`, `created_at`, `sequence_num` …).
즉 **검색할 때 `producer_id` 로 걸러낼 수는 있지만, 자동으로 걸러지지는
않는다.**

### 2.3 ⚠ 두 개의 서로 다른 격리 축

이번 정독에서 가장 중요한 발견:

| | 에피소딕 메모리 (대화 기록) | 시맨틱 메모리 (프로필/사실) |
|---|---|---|
| 격리 단위 | **`session_key` = org/project** | **`set_id`** |
| 사용자 개념 | **없음** (producer_id는 필터용 속성) | **있음** — `UserSet` 타입 |
| set 종류 | — | `OrgSet` / `ProjectSet` / **`UserSet`(producer_id 기준)** / `OtherSet` |
| 사용자별 분리 | 애플리케이션 책임 | **프레임워크가 지원** |

시맨틱 쪽은 `set_id` 를 이렇게 만든다:

```
mem_<SetType>_org_<org_id>[_project_<project_id>]_<태그수>_<해시>__<태그들>
```

메타데이터가 `{"producer_id": ...}` 뿐이면 자동으로 **UserSet** 으로 분류되고,
org 단위에 "User Profile" set type 이 자동 생성된다.

> 근거: `api_v2/service.py:39-47`, `common/api/spec.py:84-115`,
> `long_term_memory.py:78-96`, `semantic_session_manager.py:415-490`

---

## 3. 사용자를 구조에 매핑하는 3가지 방식

MemMachine이 "사용자"를 강제하지 않으므로, 멀티유저 서비스를 만들 때
설계자가 아래 중 하나(또는 조합)를 골라야 한다.

| 방식 | 매핑 | 격리 강도 | 대가 |
|---|---|---|---|
| **A. 사용자 = 프로젝트** | `project_id = user_123` | 강함 — 스토리지 파티션까지 분리 | 사용자 수만큼 세션·파티션·캐시 슬롯 소비 |
| **B. 공유 프로젝트 + 필터** | 한 프로젝트에 다수 사용자, 검색 시 `filter: producer_id = "user_123"` | 약함 — 필터 누락 시 그대로 유출 | 인덱스는 공유, 자원 효율 좋음 |
| **C. 시맨틱 UserSet** | `set_metadata={"producer_id": "user_123"}` | 중간 — 프레임워크가 set 단위로 분리 | 프로필 메모리에만 해당, 대화 원문은 아님 |

**평가에서는 A를 쓴다** — 사용자당 자원 고정비를 재는 것이 목적이고,
실제 서비스에서 사용자 간 데이터 분리를 보장하려면 A가 기본이기 때문.
(B는 자원 효율 시나리오로 2차 비교 가치가 있음.)

---

## 4. 요청 처리 흐름

### 4.1 적재 (`POST /api/v2/memories`)

```
1. session_key = org_id/project_id 조립
2. episode_storage.add_episodes(session_key, entries)
      → 대화 원문을 관계형 DB에 INSERT … RETURNING
      → uid 수령 (= episodestore.id, 자동증가 정수 PK)   ★ 진실의 원천
3. EpisodicMemoryManager.open_or_create_episodic_memory(session_key)
      → 세션 락(write) → LRU 캐시 조회 → 없으면 인스턴스 생성
4. episodic.add_memory_episodes(episodes)  → 벡터 인덱싱
   (병행) 시맨틱 메모리에 메시지 투입 → set_id 별 프로필 갱신
```

**주의**: 2번(원문 저장)과 4번(인덱싱)이 분리되어 있다. event 백엔드는
벡터스토어에 **원문 없이** 임베딩·속성·uid 참조만 넣고 검색 때 원문을
되찾는다. 게다가 uid를 발급하는 주체가 관계형 DB이므로 2번을 건너뛰면
uid 자체가 없고, 검색 마지막 단계의 `int(uid)` 캐스팅에서
`ResourceNotFoundError: Invalid episode ID`로 전부 실패한다.

### 4.2 검색 (`POST /api/v2/memories/search`)

```
1. session_key 로 메모리 인스턴스 확보 (LRU 히트 or 생성)
2. 장기 기억: 임베딩 → 벡터 검색 (세션 파티션/테넌트 필터 적용)
              → 선택적 filter 식(producer_id 등) 추가 적용
              → 리랭킹 → 히트 포인트의 payload에서 _episode_uid 수집
3. episode_store 에서 uid → 원문 복원 (WHERE id IN (…) PK 조회, 파티션 무관)
4. 시맨틱: set_metadata → set_id 해석 → 해당 set의 프로필 반환
```

> 근거: `main/memmachine.py:680-730`, `episodic_memory.py:352-400`,
> `long_term_memory.py:272-360`

---

## 5. 계층별 격리 메커니즘 — 세션 N개가 물리적으로 어떻게 되나

| 계층 | 격리 방식 | 사용자당 고정비 |
|---|---|---|
| **Qdrant** | 네이티브 컬렉션 **1개** 공유. `partition_key` payload 에 `is_tenant=True` 색인. HNSW `m=0, payload_m=16` → 테넌트별 서브그래프. 분산 시 세션별 custom shard key | 서브그래프 1개 (가벼움) |
| **Milvus** | 네이티브 컬렉션 **1개** 공유 + `partition_key` 필드 `is_partition_key=True`, 검색 시 `partition_key == "<세션>"` | 거의 없음 |
| **SQLite-vec** | 단일 파일, `(namespace, name)` 컬럼으로 행 구분 + 컬렉션별 ANN 인덱스 | 인덱스 조각 |
| **Neo4j / Nebula** (declarative) | 단일 그래프, 하나의 큰 벡터 인덱스 ANN 후 필터 | 없음 (대신 인덱스가 커짐) |
| **Postgres SegmentStore** | `postgresql_partition_by: LIST (partition_key)` → **세션마다 실제 테이블 파티션 1개** | **테이블 파티션 1개 (무거움)** ⚠ |
| **episode_store** | 공유 테이블 + `session_key` 컬럼 | 없음 |
| **sessions 테이블** | 세션당 행 1개 (`status`: active/delete) | 행 1개 |
| **앱 (메모리 인스턴스)** | 세션당 `EpisodicMemory` 객체, LRU 100개 | 캐시 슬롯 + 락 객체 |

**요지**: 벡터DB 3종은 모두 벤더 권장인 "한 통 + 테넌트 딱지" 방식이라
사용자 수 증가에 강하다. 반면 **Postgres SegmentStore만 사용자마다 실제
DDL 객체를 만든다** — 확장 한계가 여기서 먼저 올 가능성이 높다.

> 근거: `qdrant_vector_store.py:620,759-766`, `milvus_vector_store.py:59,679`,
> `sqlalchemy_segment_store.py:166,194`, `neo4j_vector_graph_store.py:511`,
> `session_data_manager_sql_impl.py:64`

---

## 6. 동시성과 수명 관리 (앱 계층)

`EpisodicMemoryManager` 가 세션별 메모리 인스턴스를 관리한다.

| 장치 | 값/동작 | 멀티유저 함의 |
|---|---|---|
| 인스턴스 LRU 캐시 | **기본 100개** | 동시 활성 세션 > 100 이면 인스턴스 축출·재생성 반복(thrash) |
| 유휴 수명 | **600초** | 10분 안 쓰면 정리 |
| 세션별 RW 락 | `defaultdict[str, AsyncRWLock]` | 같은 세션 동시 요청 직렬화. 다른 세션끼리는 간섭 없음 |
| 참조 카운트 | 사용 중 인스턴스는 축출 보류 | 활성 세션이 많으면 LRU가 실질적으로 무력화될 수 있음 |
| **락 딕셔너리 정리** | **종료 시에만 `clear()`** | 접촉한 세션 수만큼 락 객체가 계속 쌓임 — 소규모지만 무한 증가 |
| **uvicorn 워커 수** | **기본 1** (`MEMMACHINE_WORKERS`) | 단일 프로세스·단일 이벤트 루프. 워커를 늘리면 **워커마다 LRU와 락이 따로** 생기고 세션 affinity가 없어 캐시 중복·적중률 저하 |

> 근거: `episodic_memory_manager.py:42-51,82,89,141,373`, `server/app.py:113-138`

---

## 7. 지금 없는 것 (설계 시 직접 채워야 함)

| 없는 것 | 영향 |
|---|---|
| 인증·인가 | org/project 는 자기 신고. 게이트웨이에서 검증해야 함 |
| 테넌트별 쿼터·레이트리밋 | 한 사용자가 전체 자원을 잠식 가능 (noisy neighbor) |
| 사용자 단위 1급 개념(에피소딕) | §3의 A/B/C 중 선택해 애플리케이션이 구현 |
| 검색 시 사용자 필터 자동 적용 | `filter` 를 호출자가 매번 명시해야 함 — 누락 시 유출 |
| 테넌트별 사용량 계측 | 메트릭은 전역 카운터 위주, 세션별 분해 없음 |
| 크로스 테넌트 검색 방지 장치 | 구조적 차단이 아니라 파라미터 의존 |

---

## 8. 평가 관점 함의 (본 과제와의 연결)

1. **사용자 = 프로젝트(방식 A) 로 매핑**해 부하를 측정한다.
   사용자당 고정비가 가장 잘 드러나고, 실제 서비스 구성과도 맞는다.
2. **1순위 확인 대상은 Postgres SegmentStore** — 유일하게 사용자마다
   실제 DDL 객체(LIST 파티션)를 만든다. 파티션 수 증가에 따른
   플래닝 시간·카탈로그 부하, 동시 첫 적재 시 DDL 직렬화를 본다.
3. **2순위는 앱 계층** — LRU 100 경계, 세션 락, 워커 1개 구성.
   이 층은 **서버 모드(REST)에서만** 관측된다.
4. **벡터DB 3종 비교는 상대적으로 안전지대일 것** — 전부 벤더 권장
   구조라 사용자 수보다 *데이터 총량*에 민감할 것으로 예상.
   → 스윕을 "사용자 수 × 사용자당 데이터량" 2차원으로 잡아야 하는 이유.
5. **격리 검증도 측정 항목에 포함** — 필터 의존 구조이므로, 사용자 A의
   검색 결과에 B의 데이터가 섞이는지 자동 판정한다
   (longmemeval은 세션 ID가 붙어 있어 판정이 가능).

---

## 부록. 용어 대응표

| 이 문서 | MemMachine 내부 | 비고 |
|---|---|---|
| 테넌트 / 사용자 | `session_key` (`org_id/project_id`) | 문자열 1개 |
| 사용자 발화 주체 | `producer_id` | 격리 키 아님, 필터용 속성 |
| 스토리지 파티션 | `partition_key` | `session_key` → 32자 이하면 그대로, 아니면 sha256 앞 32자 |
| 프로필 묶음 | `set_id` (`UserSet` 등) | 시맨틱 메모리 전용 격리 단위 |
| 대화 원문 저장소 | `episode_store` | 공유 테이블 + `session_key` 컬럼 |
| 파생·임베딩 저장소 | VectorStore / VectorGraphStore | 백엔드 교체 가능 |
