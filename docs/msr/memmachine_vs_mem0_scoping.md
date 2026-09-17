# MemMachine vs Mem0 — 사용자·프로젝트를 어떻게 구분하고, 검색 때 어떻게 골라내는가

*2026-08-21 · 기준: MemMachine `2d28c1c`(upstream/main) / Mem0 오픈소스 `main` — 양쪽 모두 소스 코드 직접 확인*
*Mem0 유료 서비스(Platform)는 비공개라 제외*

---

## 0. 결론 먼저 — 표 한 장

| | **MemMachine** | **Mem0 (오픈소스)** |
|---|---|---|
| 최상위 구분 | `org_id` + `project_id` | **없음** |
| 그 아래 사용자 | 개념 없음 (속성으로만 존재) | `user_id` |
| 그 아래 에이전트 | 개념 없음 (속성으로만 존재) | `agent_id` |
| 그 아래 세션/실행 | **개념 없음** | `run_id` |
| 발화 주체 | `producer_id` (속성) | `actor_id` (검색 전용) |
| **저장할 때 신원 지정** | 프로젝트만 필수 | **셋 중 하나 필수** (없으면 오류) |
| **검색할 때 신원 지정** | 프로젝트만 필수, **사용자 필터는 선택** | **필수** (없으면 오류) |
| 검색 공간이 물리적으로 나뉘는 단위 | **프로젝트** (전용 인덱스) | **없음** (전부 한 인덱스) |

**한 줄 요약**
> MemMachine은 **프로젝트를 물리적으로 나누지만 그 아래 사용자 구분은 선택 사항**이고,
> Mem0는 **물리적으로는 전혀 안 나누지만 사용자 지정을 강제**합니다.
> 서로 반대편의 안전장치를 갖고 있습니다.

---

## 1. 저장할 때 — 무엇으로 구분하나

### 1.1 API 호출을 나란히 놓고 보면

**MemMachine** (REST)
```jsonc
POST /api/v2/memories
{
  "org_id":     "sk-hynix",        // ← 필수
  "project_id": "chatbot-prod",    // ← 필수. 이 둘이 합쳐져 검색 공간이 됨
  "messages": [{
      "content":   "저는 채식주의자예요",
      "producer":  "user_123",     // ← 누가 말했나 (구분 키가 아니라 '속성')
      "role":      "user",
      "metadata":  { "user_id": "user_123", "session": "s42" }   // ← 자유 항목
  }]
}
```

**Mem0** (Python)
```python
m.add(
    messages = [{"role": "user", "content": "저는 채식주의자예요"}],
    user_id  = "user_123",     # ← 이 셋 중
    agent_id = "bot_a",        #    최소 하나는
    run_id   = "s42",          #    반드시 있어야 함
    metadata = {"topic": "food"},
)
```

없으면 오류가 납니다:
```python
raise Mem0ValidationError(
    "At least one of 'user_id', 'agent_id', or 'run_id' must be provided."
)
```

### 1.2 차이의 핵심

| | MemMachine | Mem0 |
|---|---|---|
| 반드시 있어야 하는 것 | **조직 + 프로젝트** | **사용자 또는 에이전트 또는 세션** |
| 사용자를 안 넣으면? | **그냥 저장됨** (프로젝트 전체에 섞임) | **오류로 거부됨** |

→ MemMachine에서 사용자를 구분하려면 **개발자가 스스로 `metadata`에 넣어야 합니다.**
   빠뜨려도 시스템이 알려주지 않습니다.

---

## 2. 저장된 데이터는 실제로 어떻게 생겼나

### 2.1 MemMachine — 3층으로 기록됩니다

```
① 검색 공간 (물리적 구획)
   session_key = "sk-hynix/chatbot-prod"
        → 이 값으로 전용 인덱스 구획이 만들어짐
        → 벡터DB 구획 + PostgreSQL 테이블 2개

② 시스템 속성 (자동으로 붙고, 검색 조건으로 쓸 수 있음)
   producer_id, producer_role, produced_for_id,
   episode_type, created_at, sequence_num, session_key

③ 사용자 정의 항목 (개발자가 넣은 metadata 중 단순 값만)
   metadata: {"user_id": "user_123", "session": "s42"}
        → 내부적으로 이름이 바뀌어 저장되고
        → 검색할 때는 m.user_id 또는 metadata.user_id 로 참조
```

**주의**: ③은 **문자·숫자 같은 단순 값만** 넘어갑니다.
목록이나 중첩 구조는 검색 조건으로 쓸 수 없습니다.

### 2.2 Mem0 — 2층으로 기록됩니다

```
① 저장소
   설정 파일에 적힌 이름 하나. 사용자가 늘어도 늘지 않음

② 딱지 (metadata)
   user_id, agent_id, run_id, actor_id + 개발자가 넣은 metadata
        → 전부 같은 층. 지위 차이가 없음
```

Mem0에서는 `user_id`도 `topic` 같은 임의 항목도 **저장 구조상 똑같은 딱지**입니다.

---

## 3. 검색할 때 — 어떻게 골라내나

### 3.1 API를 나란히 놓고 보면

**MemMachine**
```jsonc
POST /api/v2/memories/search
{
  "org_id":     "sk-hynix",
  "project_id": "chatbot-prod",     // ← 필수. 여기서 검색 공간이 정해짐
  "query":      "뭘 좋아하지?",
  "filter":     "m.user_id = 'user_123'"   // ← 선택. 기본값은 빈 문자열 ""
}
```

**Mem0**
```python
m.search(
    query   = "뭘 좋아하지?",
    filters = {"user_id": "user_123"},   # ← 필수. 없으면 오류
    top_k   = 20,
)
```

### 3.2 내부에서 실제로 벌어지는 일

**MemMachine — 2단계로 좁힙니다**

```
1단계 (자동·강제)  프로젝트 구획 안으로 진입
                   → 다른 프로젝트 데이터로 갈 경로가 아예 없음

2단계 (선택)       filter 문자열이 있으면 조건 추가
                   → 벡터DB에는 두 조건이 AND로 전달됨
                        구획 = 현재 프로젝트
                        AND  m.user_id = 'user_123'
```

`filter`를 비워두면 **1단계만 적용** → 그 프로젝트의 모든 사용자 데이터가 검색 대상이 됩니다.

**Mem0 — 1단계뿐입니다**

```
전체 저장소에서 검색
  → filters 조건으로 걸러냄 (조건은 필수)
```

물리적으로 좁혀지는 단계가 없어서, 검색은 **모든 사용자의 데이터가 섞인 인덱스를
훑고 나서** 결과를 걸러냅니다.

### 3.3 그림으로

```
MemMachine
┌─────────────── 벡터DB ───────────────┐
│ ┌ prj-A ┐  ┌ prj-B ┐  ┌ prj-C ┐      │
│ │ ●─●─● │  │ ●─●   │  │ ●─●─● │      │  ← 구획별 독립 인덱스
│ └───────┘  └───────┘  └───────┘      │     (서로 잇는 링크 없음)
└──────────────────────────────────────┘
   1단계: prj-B 안으로만 진입 (강제)
   2단계: 그 안에서 user_id로 거르기 (선택)

Mem0
┌─────────────── 벡터DB ───────────────┐
│  ●─●─●─●─●─●─●─●─●─●─●─●             │  ← 인덱스 하나
│  A B C A D B A C D A B C             │     모든 사용자 섞임
└──────────────────────────────────────┘
   전부 훑고 → user_id로 거르기 (필수)
```

---

## 4. 그 밖의 구분 수단

| | MemMachine | Mem0 |
|---|---|---|
| 시간 범위 | `created_at` 조건 | `reference_date`, 만료일(`expiration_date`) |
| 대화 종류 | `episode_type` 조건 | `memory_type` |
| 말한 사람 / 들은 사람 | `producer_id` / `produced_for_id` | `actor_id` (검색 시) |
| 자유 항목 | `m.<이름>` (단순 값만) | metadata 딕셔너리 |
| 검색 조건 표현 방식 | **문자열 식** `"m.user_id = 'u1' AND episode_type = 'message'"` | **딕셔너리** `{"user_id": "u1", "AND": [...]}` |
| 프로필/요약 기억의 구분 | 별도 체계 (`set_id` — 조직·프로젝트·**사용자** 단위 구분 존재) | 동일 체계 안에서 처리 |

**한 가지 흥미로운 점**: MemMachine의 **프로필 기억 쪽에는 사용자 개념이 있습니다**
(`UserSet` — 발화자 기준). 즉 같은 제품 안에서 대화 기억은 사용자 개념이 없고,
프로필 기억은 있는 상태입니다.

---

## 5. 성능에 직결되는 숨은 조건 — 검색 조건에 색인이 붙는가

여기가 실무에서 자주 놓치는 부분입니다.

### MemMachine

설정 파일의 `properties_schema`에 항목을 등록해야 그 항목에 **색인**이 만들어집니다.

```yaml
episodic_memory:
  long_term_memory:
    backend: event
    properties_schema:
      user_id: str      # ← 등록해야 색인 생성
```

| 등록 여부 | 검색 조건 사용 | 색인 | 결과 |
|---|---|---|---|
| 등록함 | 가능 | ✅ 생성됨 | 빠름 |
| **등록 안 함** | **가능** (값은 저장돼 있음) | ❌ 없음 | **느림 — 색인 없이 훑음** |

즉 **동작은 하지만 느린 상태**가 조용히 만들어질 수 있습니다.
"필터가 되니까 괜찮다"고 넘어가면 성능 문제가 나중에 드러납니다.

### Mem0

`user_id`, `agent_id`, `run_id`, `actor_id` 네 가지에 **자동으로 색인을 만듭니다.**
다만 로컬 모드에서는 **색인 생성을 건너뜁니다**(미지원). 즉 자체 호스팅 소규모 구성에서는
색인 없이 동작합니다.

---

## 6. 실수했을 때 무슨 일이 벌어지나

| 상황 | MemMachine | Mem0 |
|---|---|---|
| 저장할 때 사용자 정보를 빠뜨림 | 조용히 저장됨 → 나중에 그 데이터는 사용자별로 걸러낼 수 없음 | **오류로 거부** |
| 검색할 때 사용자 조건을 빠뜨림 | **프로젝트 전체 결과 반환** (다른 사용자 기억 포함) | **오류로 거부** |
| 다른 프로젝트 데이터가 섞임 | **구조적으로 불가능** | 해당 개념 없음 |
| 항목 이름을 잘못 씀 (`m.usr_id`) | 등록된 항목이 있으면 **오류로 알려줌**, 없으면 조용히 0건 | 조용히 0건 |

**정리하면 안전장치의 위치가 서로 반대입니다.**

- **MemMachine**: 프로젝트 경계는 **구조가 지켜줌**. 사용자 경계는 **개발자 책임**.
- **Mem0**: 프로젝트 경계는 **없음**. 사용자 경계는 **API가 강제**(단 논리적 필터).

---

## 7. 그래서 실무적으로 어떻게 되나

### 사용자 = 프로젝트로 두면 (MemMachine에서만 가능)

```
project_id = "user_123"
```

| | 결과 |
|---|---|
| 검색 공간 | 사용자마다 전용 인덱스 ✅ — Mem0로는 불가능 |
| 안전성 | 사용자 경계가 **구조로 보장됨** (필터 빠뜨려도 안전) |
| **대가** | 사용자마다 PostgreSQL 테이블 2개 + 앱 작업공간 1개 ⚠ |

### 사용자를 프로젝트 안에 담으면 (양쪽 다 가능)

```
project_id = "chatbot-prod",  metadata.user_id = "user_123"
```

| | 결과 |
|---|---|
| 검색 공간 | 프로젝트 전체 (사용자 섞임) — **Mem0와 동일** |
| 안전성 | 필터 의존. MemMachine은 빠뜨리면 유출, Mem0는 강제라 그나마 나음 |
| 대가 | 없음 |

**→ 본 과제가 풀려는 문제가 바로 이 표의 "대가" 칸입니다.**
사용자별 전용 인덱스의 이점은 살리면서 테이블·작업공간 비용을 없애는 것.

---

## 8. 근거 위치

### MemMachine (`packages/server/src/memmachine_server/`)

| 내용 | 파일 · 심볼 |
|---|---|
| 조직+프로젝트 → 검색 공간 키 | `server/api_v2/service.py` · `_SessionData.session_key` |
| 검색 조건은 선택 (기본 빈 문자열) | `packages/common/.../api/spec.py` · `SearchMemoriesSpec.filter` |
| 조건 문자열 파싱 → 검색 전달 | `main/memmachine.py` · `query_search()` |
| 구획 + 조건을 AND로 결합 | `common/vector_store/qdrant_vector_store.py` · 검색부 |
| 자유 항목을 검색 가능 값으로 변환 (단순 값만) | `episodic_memory/episodic_memory.py` · `add_memory_episodes()` |
| 사용 가능한 시스템 항목 목록 | `episodic_memory/long_term_memory/long_term_memory.py` · `EVENT_BACKEND_SYSTEM_FIELDS` |
| 잘못된 항목명 검증 규칙 | 〃 · `_validate_event_backend_filter()` |
| 등록된 항목만 색인 생성 | `episodic_memory/long_term_memory/service_locator.py` · `_resolve_user_properties_schema()` |
| 프로필 기억의 사용자 구분 | `semantic_memory/semantic_session_manager.py` · `SetType.UserSet` |

### Mem0 오픈소스

| 내용 | 파일 · 심볼 |
|---|---|
| 저장·검색 파라미터 | `mem0/memory/main.py` · `add()`, `search()` |
| 신원 ID 필수 검증 | 〃 · `_build_filters_and_metadata()` — `Mem0ValidationError` |
| 저장소 이름이 설정값 하나 | 〃 · `self.collection_name` |
| 조직/프로젝트 개념 없음 | 〃 · 해당 문자열 0건 |
| 인덱스 설정 (구획별 인덱스 없음) | `mem0/vector_stores/qdrant.py` · `create_col()` |
| 4개 항목에 자동 색인, 로컬은 건너뜀 | 〃 · `_create_filter_indexes()` |

### 외부 문서

- [Mem0 — Organizations & Projects](https://docs.mem0.ai/api-reference/organizations-projects) (유료 서비스, 접근 권한 관점)
- [Qdrant — Multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/)
- [PostgreSQL — Table Partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)
