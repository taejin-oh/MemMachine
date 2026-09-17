# 오픈소스 LTM 솔루션의 다중 사용자 구조 조사

*작성 2026-08-19 · 소스 코드 실측 + 공식 문서 기반*
*조사 동기: "사용자별 인덱스 분리 → 사용자 아래 세션 구분 → 적합한 인덱스로 라우팅"
요구사항에 맞는 솔루션 탐색*

---

## 0. 결론 먼저

| 질문 | 답 |
|---|---|
| 요구사항을 그대로 만족하는 오픈 LTM이 있나? | **없다.** 조사한 전부가 "공유 저장소 + 필터" 구조 |
| 그럼 MemMachine이 특별히 나쁜가? | **아니다.** 오히려 벡터 검색 국한 방식은 MemMachine이 가장 앞서 있다 (Qdrant 테넌트 서브그래프) |
| MemMachine의 진짜 문제는? | ① 에피소딕에 **사용자 개념 자체가 없음** ② **사용자 아래 세션 계층이 없음** ③ Postgres가 세션마다 실제 파티션을 만듦 |
| ID 모델이 가장 잘 갖춰진 건? | **Mem0** (user / agent / run / actor 4축) |
| 사용자 중심 저장 설계가 가장 철저한 건? | **Memobase** (모든 인덱스가 user_id 선행, ANN 인덱스 아예 없음) |
| 시사점 | 요구사항을 만족하는 구조가 **업계에 아직 없다** → 우리 차별화·특허 기회 |

---

## 1. 요구사항 정형화

제시된 요구를 평가 기준 3개로 나눈다.

| # | 요구 | 판정 질문 |
|---|---|---|
| **R1** | 사용자별 인덱스 구분 | 검색이 그 사용자 데이터만 순회하는가? 남의 벡터를 안 훑는가? |
| **R2** | 사용자 아래 세션 구분 | 사용자 안에서 세션/스레드를 나누는 **계층**이 있는가? |
| **R3** | 적합한 인덱스로 라우팅 | 질의에 따라 어느 범위를 볼지 고를 수 있는가? |

### ⚠ 먼저 짚을 것 — "인덱스 분리"에는 3가지 층위가 있다

이 구분을 안 하면 조사 결과를 잘못 읽게 된다.

| 층위 | 방식 | 검색 시 남의 데이터를 훑나 | 사용자 수 확장 |
|---|---|---|---|
| **L-A. 물리 분리** | 사용자마다 별도 컬렉션/인덱스 객체 | 안 훑음 | ❌ **벤더가 금지**. Qdrant "수백 개 넘으면 확장 불가, Cloud 1,000개 제한", Milvus 확장성 순위 최하위권 |
| **L-B. 테넌트 서브그래프** | 한 컬렉션 안에서 **사용자별 ANN 하위 그래프** | 안 훑음 | ✅ 좋음 |
| **L-C. 키 선행 인덱스** | 공유 테이블, `(user_id, …)` 복합 인덱스로 범위 축소 후 정확 검색 | 안 훑음 | ✅ 좋음 (사용자당 데이터가 작을 때) |
| **L-D. 사후 필터** | 전역 인덱스에서 ANN 후 사용자 필터 | **훑음** | 사용자 수 늘수록 recall·지연 악화 |

**요구사항 R1의 본질은 "L-A"가 아니라 "L-D가 아닌 것"이다.** L-B나 L-C면 목적은 달성된다.
그리고 L-A는 실제로 하면 안 되는 선택지다.

> 출처: [Qdrant Multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/),
> [Milvus Multi-tenancy](https://milvus.io/docs/multi_tenancy.md)

---

## 2. 솔루션별 조사 결과

### 2.1 Mem0 — ID 모델은 최강, 저장은 사후 필터

**확인 방법**: 소스 직접 확인 (`mem0/memory/main.py`)

```python
self.collection_name = self.config.vector_store.config.collection_name   # 설정에서 온 단 하나
...
def _build_filters_and_metadata(*, user_id, agent_id, run_id, actor_id, ...):
    #  쓰기 → metadata 에 심고
    #  읽기 → effective_query_filters 로 필터
```

- **스코프 축 4개**: `user_id`(사용자 영속) / `agent_id`(에이전트) / `run_id`(세션·실행) /
  `actor_id`(발화 주체, 질의 시 필터). 조사 대상 중 **가장 풍부한 ID 모델**.
- **저장은 단일 컬렉션.** `collection_name`은 설정값 하나이고 사용자별로 안 늘어난다.
  격리는 전적으로 메타데이터 필터.
- 그래프 메모리는 `{collection}_entities` 로 **또 하나의 공유 컬렉션**.
- 참고로 소스에 이런 주석이 있다 — 자유 메타데이터로 남의 스코프에 메모리를 심을 수
  있던 버그(issue #6655)를 막으려 식별자 키를 강제로 벗겨낸다.
  **필터 기반 격리가 구조적으로 깨지기 쉽다는 증거.**

| R1 인덱스 분리 | R2 세션 계층 | R3 라우팅 |
|---|---|---|
| ❌ L-D (사후 필터) | ✅ user > agent > run > actor | ✅ 필터 조합으로 가능 |

> 출처: [mem0ai/mem0 소스](https://github.com/mem0ai/mem0), [Mem0 오픈소스 개요](https://docs.mem0.ai/open-source/overview)

### 2.2 Zep / Graphiti — group_id 네임스페이스 = 그래프 속성 필터

- 모든 노드·엣지에 **`group_id`** 를 붙이고, 같은 `group_id` 끼리 논리적으로 하나의
  그래프를 이룬다. 질의 시 `group_id` 로 검색 공간을 제한.
- 공식 문서상 **별도 DB/그래프 인스턴스가 아니라 속성 기반 필터링**. 문서는
  "데이터 격리 / 관리 단순화 / 검색 공간 축소"를 이점으로 들지만, 물리 분리는 아니다.
- 사용자·세션 계층에 대한 설명이 **문서에 없다** — `group_id` 하나를 어떻게 쓸지는
  전적으로 애플리케이션 몫. (상위 제품 Zep은 user/thread 개념을 제공하지만,
  OSS 코어인 Graphiti 레벨에서는 `group_id` 단일 축.)
- 강점은 다른 데 있다: **시간 지식그래프** — 사실마다 유효기간이 붙어 사실 변화를 추적.

| R1 | R2 | R3 |
|---|---|---|
| △ 그래프 필터 (L-D 계열) | ❌ 단일 축 | ✅ group_id 선택 |

> 출처: [Graph Namespacing | Zep](https://help.getzep.com/graphiti/core-concepts/graph-namespacing)

### 2.3 Letta (MemGPT 계열) — 에이전트 스코프

- 메모리가 **에이전트 단위**로 묶인다: core(항상 컨텍스트) / recall(전체 메시지 로그,
  관계형) / archival(무한 장기, pgvector).
- 사용자가 1급 개념이 아니라 **"에이전트 = 사용자"로 쓰는 모델**. 2026년 4월
  Conversations API가 추가되며 병렬 세션 간 공유 메모리를 다루기 시작.
- 저장은 Postgres + pgvector 공유 테이블에 에이전트 식별자로 스코프.

| R1 | R2 | R3 |
|---|---|---|
| ❌ 필터 계열 | △ 에이전트 > 대화 | ✅ 메모리 계층 선택(core/recall/archival) |

> 출처: [Agent Memory at Scale 2026 비교](https://agentmarketcap.ai/blog/2026/04/10/agent-memory-vendor-landscape-2026-letta-zep-mem0-langmem)
> — 문서 수준 확인 (소스 미검증)

### 2.4 Memobase — ★ 요구사항에 가장 근접

**확인 방법**: 소스 직접 확인 (`src/server/api/memobase_server/models/database.py`, `build_init_sql.py`)

스키마가 **철저히 사용자 중심**이다.

```
projects (테넌트)
  └─ users  (PK: id + project_id)
       ├─ general_blobs     원본 대화 blob
       ├─ buffer_zones      사용자별 배치 버퍼   ← 사용자마다 독립 버퍼
       ├─ user_profiles     구조화 프로필
       ├─ user_events       이벤트 타임라인 (+ embedding)
       ├─ user_event_gists  이벤트 요약     (+ embedding)
       └─ user_statuses
```

핵심 두 가지:

1. **모든 인덱스가 `user_id, project_id` 를 선행 컬럼으로 갖는다.**
   `idx_user_profiles_user_id_project_id`, `idx_user_events_user_id_project_id`,
   `idx_user_event_gists_user_id_project_id` … 전부.
2. **ANN 인덱스가 아예 없다.** `pgvector`의 `Vector` 컬럼은 쓰지만
   HNSW/IVFFlat 인덱스를 만들지 않는다 (`build_init_sql.py`가 내보내는 인덱스는
   전부 B-tree). → **B-tree로 그 사용자 행 범위로 좁힌 뒤 그 안에서만 정확 벡터 계산.**

즉 **L-C 방식**. 전역 ANN 그래프 자체가 없으므로 남의 데이터를 훑을 일이 원천적으로 없다.
사용자 수가 늘어도 다른 사용자 검색에 영향이 없다.
대신 사용자당 데이터가 커지면 선형으로 느려진다 — 그래서 **원문 전체가 아니라 프로필과
이벤트 요약(gist)만 벡터화**하는 설계와 짝을 이룬다.

| R1 | R2 | R3 |
|---|---|---|
| ✅ **L-C — 요구 충족** | △ 세션보다 blob/event 축 | △ 프로필 vs 이벤트 선택 |

> 출처: [memodb-io/memobase 소스](https://github.com/memodb-io/memobase)

### 2.5 그 외 (문서 수준)

| 솔루션 | 요약 |
|---|---|
| **Cognee** | 그래프 네이티브 ECL 파이프라인, 14종 검색 모드, 저장 백엔드 교체 가능. 기능 폭은 최대이나 사용자 스코프는 일반적인 필터 모델 |
| **LangMem** | LangGraph 생태계 전용. user / thread / namespace 레벨 스코프 제공 — **계층 개념은 있음**. 다만 LangGraph 밖에서는 활용도 낮음 |
| **Supermemory** | 개인·앱 메모리 API. 범용 메모리 레이어 지향, 최소 설정 |

> 출처: [Cognee 오픈소스 메모리 툴 비교](https://www.cognee.ai/blog/guides/best-open-source-ai-memory-tools-for-llm-agents-and-developers),
> [8개 프레임워크 비교](https://vectorize.io/articles/best-ai-agent-memory-systems)

### 2.6 MemMachine (비교 기준)

**확인 방법**: 소스 직접 확인 (메인라인 `a681abf`)

- 에피소딕 격리 단위 = `session_key` (= `org_id/project_id`). **사용자 개념 없음.**
  `producer_id`는 격리 키가 아니라 필터용 속성.
- 시맨틱(프로필)만 `set_id`에 `UserSet`(producer_id 기준, org 레벨)이 있다.
- 벡터층은 오히려 앞서 있다:
  - **Qdrant**: 단일 컬렉션 + `is_tenant=True` payload 인덱스 + HNSW `m=0, payload_m=16`
    → **전역 그래프를 끄고 테넌트별 하위 그래프만 사용** = **L-B**
  - **Milvus**: partition key 방식
- 문제는 관계형 쪽: **Postgres SegmentStore가 세션마다 실제 LIST 파티션을 생성** (L-A!) —
  유일하게 안티패턴에 해당하는 지점.

| R1 | R2 | R3 |
|---|---|---|
| ✅ **L-B — 벡터층은 요구 충족** | ❌ 세션 하위 계층 없음 | △ 파티션 지정 + 필터 |

---

## 3. 요구사항 대비 매트릭스

| | **R1** 사용자별 인덱스 국한 | **R2** 사용자 아래 세션 계층 | **R3** 인덱스 라우팅 | 검증 |
|---|---|---|---|---|
| **Mem0** | ❌ L-D 사후 필터 | ✅✅ user/agent/run/actor | ✅ | 소스 |
| **Zep / Graphiti** | △ 그래프 속성 필터 | ❌ group_id 단일 축 | ✅ | 문서 |
| **Letta** | ❌ 필터 | △ 에이전트>대화 | ✅ 메모리 계층 | 문서 |
| **Memobase** | ✅✅ **L-C** | △ 약함 | △ | 소스 |
| **Cognee / LangMem / Supermemory** | ❌ 필터 | △ (LangMem은 3단 스코프) | ✅ | 문서 |
| **MemMachine** | ✅ **L-B** (벡터층) / ❌ **L-A** (Postgres) | ❌ 없음 | △ | 소스 |

**어느 것도 R1 + R2를 동시에 만족하지 않는다.**
- R1을 만족하는 둘(Memobase, MemMachine)은 **세션 계층이 없다.**
- R2를 만족하는 Mem0는 **저장이 사후 필터**다.

---

## 4. 해석 — MemMachine이 "안 맞다"는 판단에 대해

절반은 맞고 절반은 틀리다.

**맞는 부분**
- 에피소딕에 사용자라는 1급 개념이 **없다.** `org/project` 문자열 하나가 전부.
- **사용자 아래 세션이라는 계층이 없다.** 세션이 곧 최상위 격리 단위라서
  "사용자 → 그 아래 세션들"을 표현하려면 메타데이터+필터로 흉내내야 한다.
- Postgres가 세션마다 실제 DDL 객체를 만드는 것은 **조사한 어느 솔루션도 안 하는**
  방식이고, 확장 한계가 여기서 먼저 온다.

**틀린 부분**
- "인덱스가 사용자별로 안 나뉜다"는 우려는 **벡터층에는 해당하지 않는다.**
  MemMachine의 Qdrant 경로는 전역 HNSW를 끄고(`m=0`) 테넌트별 하위 그래프만
  쓰도록 이미 구성돼 있다 — Mem0·Zep·Letta보다 이 점에선 앞선다.
- 사용자를 프로젝트에 매핑하면(user = project) R1은 자동 충족된다.
  남는 문제는 R2(세션 계층)와 Postgres 파티션 비용이다.

---

## 5. 그래서 무엇을 할 것인가

### 5.1 이건 문제가 아니라 기회다

요구사항 **R1 + R2 + R3를 동시에 만족하는 오픈 LTM이 존재하지 않는다.**
"사용자 우선 인덱스 계층 + 그 아래 세션 라우팅"은 **업계 미해결 영역**이다.

과제 목표(차별화 LTM 확보, 특허 발굴)와 정확히 맞물린다:
- 1단계는 정확도에서 문제를 찾아 adaptive-k로 해결했다.
- 2단계는 **구조에서 문제를 찾았다** — 이번엔 측정 전에 이미 찾았다.

### 5.2 설계 방향 3안

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. MemMachine 확장** | 사용자 계층을 추가하고(user > session), 벡터는 L-B 유지, Postgres 파티션은 사용자 단위로 올려 파티션 수를 세션→사용자로 축소 | 기존 자산 유지, 변경 국소적, upstream 기여 가능 | 코어 수정 필요 |
| **B. Memobase형 하이브리드** | 프로필·요약은 L-C(사용자 키 선행, ANN 없음), 원문 검색은 L-B(테넌트 서브그래프) | 두 방식의 장점 결합, 사용자당 데이터 커져도 견딤 | 두 경로 관리 |
| **C. Mem0형 ID 모델 이식** | user/agent/session/actor 4축을 MemMachine에 도입하되 저장은 L-B 유지 | R2 해결, 사후 필터 약점은 피함 | ID 모델 재설계 |

**추천: A를 뼈대로 B의 아이디어를 얹는 것.**
사용자 계층 도입(A)이 R2를 풀고, 프로필/원문 이원화(B)가 사용자당 데이터 증가에 대비한다.

### 5.3 즉시 검증할 것 — 기존 계획과의 접점

이번 조사로 **가설 순위가 바뀌었다.**

- 원래 1순위였던 "Postgres 세션당 파티션"은 이제 **가설이 아니라 확정된 설계 결함**에
  가깝다 (다른 어떤 솔루션도 이렇게 하지 않음). 남은 건 **몇 명에서 터지는지 숫자**뿐.
- 새로 추가할 측정: **사용자 수를 늘렸을 때 Qdrant 테넌트 서브그래프 방식이 실제로
  방어해 주는가.** 이게 확인되면 "벡터층은 그대로 두고 관계형만 고치면 된다"는
  개선 방향이 수치로 뒷받침된다.

→ 준혁 TL의 T1(실측 조사) 체크리스트는 그대로 유효하고, **결과 해석의 틀이 명확해졌다.**

---

## 참고 자료

- [Qdrant — Multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/)
- [Qdrant — Multitenancy and Custom Sharding](https://qdrant.tech/articles/multitenancy/)
- [Qdrant 1.16 — Tiered Multitenancy](https://qdrant.tech/blog/qdrant-1.16.x/)
- [Milvus — Implement Multi-tenancy](https://milvus.io/docs/multi_tenancy.md)
- [Zep — Graph Namespacing](https://help.getzep.com/graphiti/core-concepts/graph-namespacing)
- [mem0ai/mem0](https://github.com/mem0ai/mem0) · [Mem0 오픈소스 개요](https://docs.mem0.ai/open-source/overview)
- [memodb-io/memobase](https://github.com/memodb-io/memobase)
- [Agent Memory at Scale 2026 (Letta·Zep·Mem0·LangMem)](https://agentmarketcap.ai/blog/2026/04/10/agent-memory-vendor-landscape-2026-letta-zep-mem0-langmem)
- [Cognee — 오픈소스 AI 메모리 툴 비교](https://www.cognee.ai/blog/guides/best-open-source-ai-memory-tools-for-llm-agents-and-developers)
- [8개 에이전트 메모리 프레임워크 비교](https://vectorize.io/articles/best-ai-agent-memory-systems)
