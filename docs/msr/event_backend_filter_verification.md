# [검증] event 백엔드에서 user_id 필터가 동작하지 않는다는 주장에 대하여

*2026-08-21 · 기준 코드: `upstream/main` `2d28c1c` (수정본 아님)*
*검증 방법: 소스 코드 추적 + **실제 실행 테스트**(재현 절차 §6 수록)*

> ## ⚠ 검증 무결성 선언
>
> **본 검증은 우리가 수정한 코드를 일절 사용하지 않았습니다.**
>
> | 확인 항목 | 결과 |
> |---|---|
> | 우리 작업 트리에서 수정된 파일 | `evaluation/utils/agent_utils.py` **한 개뿐** (평가 하네스) |
> | 서버 패키지(`packages/`) 수정 여부 | **없음** — upstream 그대로 |
> | 필터 관련 파일이 `a681abf` ↔ `2d28c1c` 사이에 변경됐는지 | **전부 동일** (`long_term_memory.py`, `event_memory.py`, `episodic_memory.py`, `filter_parser.py`, `service_locator.py`) |
> | 테스트가 `evaluation/*` 를 import 하는지 | **하지 않음** — `memmachine_server` 패키지만 사용 |
> | 적재 방식 | 서버(`main/memmachine.py:700,720`)와 **동일한 순서**를 직접 재현 |
> | 유일한 테스트 더블 | 임베더 (네트워크·API 키 제거 목적, 필터 로직과 무관한 계층) |
>
> 확인 명령:
> ```bash
> git status --short | grep -v '^??'        # → M evaluation/utils/agent_utils.py 만
> git diff --stat a681abf -- packages/      # → 출력 없음 (서버 패키지 무수정)
> git diff --quiet a681abf 2d28c1c -- <필터 관련 파일>   # → 전부 동일
> ```

---

## 0. 결론

> ### 주장은 사실이 아닙니다. event 백엔드에서 `m.user_id` 필터는 정상 동작합니다.

제기된 주장:
> *"episodic store를 타면 user_id로 필터가 가능한데, event 쪽으로 저장되면
> filterable_metadata가 외부에 노출되지 않아 검색이 안 된다."*

실제로 실행해 확인한 결과, **세 가지 표기법 모두 동작하며 타 사용자 데이터 유출은 0건**입니다.

| 검색 조건 | 결과 |
|---|---|
| `m.user_id = 'user_a'` | ✅ 4건, 유출 0건 |
| `metadata.user_id = 'user_b'` | ✅ 4건, 유출 0건 |
| `producer_id = 'user_a'` (시스템 필드) | ✅ 4건, 유출 0건 |

다만 **"안 된다"고 관찰될 수 있는 실제 실패 조건이 3가지 존재**하며(§5),
그중 하나는 우리가 이미 발견해 수정한 버그입니다. 주장한 쪽이 실제로 실패를
겪었다면 그중 하나일 가능성이 높습니다.

---

## 1. 실행 테스트 결과

### 조건

- 저장 백엔드: **event** (VectorStore = SQLite-vec, SegmentStore = SQLite)
- **하나의 파티션(= 하나의 프로젝트)** 안에 두 사용자 데이터를 섞어서 적재
- 각 에피소드에 `metadata={"user_id": "user_a" 또는 "user_b", "idx": n}` 부여
- 코드: **upstream `memmachine_server` 패키지만 사용** (평가 하네스 미사용)

### 출력

```
backend        : EventMemory (partition=baf1a5e6a767ce9f628b16fe0614a887)
vector store   : SQLiteVectorStore
ingested       : user_a 4건 + user_b 4건 (같은 파티션)

① 필터 없음                  : 8건 (user_a 4 / user_b 4)
② m.user_id='user_a'        : 4건, 유출 0건  ✅
③ metadata.user_id='user_b' : 4건, 유출 0건  ✅
④ producer_id='user_a'      : 4건, 유출 0건  ✅

PASS — upstream 코드만으로 event 백엔드 필터 동작 확인
```

**①이 8건(두 사용자 혼재)으로 나온 것이 중요합니다.** 필터를 걸지 않으면 실제로
섞여 나온다는 뜻이고, 따라서 ②③④에서 4건만 나온 것은 **필터가 실제로 작동한
결과**이지 데이터가 원래 그것뿐이어서가 아닙니다.

---

## 2. 왜 이런 오해가 생기는가 — 두 백엔드의 저장 규칙이 다릅니다

이것이 오해의 핵심 원인입니다.

`LongTermMemory.add_episodes()` 는 백엔드에 따라 **완전히 다른 변환 함수**를 탑니다.

```python
# episodic_memory/long_term_memory/long_term_memory.py:233
async def add_episodes(self, episodes):
    if self._backend == "declarative":
        ... _declarative_memory_episode(e) ...     # ← 461행
        return
    events = [_episode_to_event(episode) ...]      # ← 632행  (event 경로)
```

**declarative 경로만 보고 판단하면 "event에는 metadata 처리가 없다"고 오인하기 쉽습니다.**
실제로는 event 경로에도 있고, 다만 **저장 키 규칙이 다릅니다.**

| | 사용자 metadata 저장 키 | 검색 시 변환 경로 |
|---|---|---|
| **declarative** | `metadata.user_id` (접두사 부착) | `m.user_id` → `metadata.user_id` |
| **event** | **`user_id` (접두사 없음)** | `m.user_id` → normalize → demangle → `user_id` |

### event 경로의 실제 코드

```python
# _episode_to_event()  (long_term_memory.py:632)
properties: dict[str, PropertyValue] = {
    _EPISODE_UID_FIELD:   episode.uid,        # 시스템 필드는 "_" 접두사
    _SESSION_KEY_FIELD:   episode.session_key,
    _PRODUCER_ID_FIELD:   episode.producer_id,
    ...
}
if episode.filterable_metadata is not None:
    reserved = sorted(k for k in episode.filterable_metadata if k.startswith("_"))
    if reserved:
        raise ValueError(...)                  # 시스템 필드 사칭 방지
    properties.update(episode.filterable_metadata)   # ← 사용자 metadata가 그대로 실림
```

이 함수의 docstring이 의도를 명시하고 있습니다:

> *"Properties: system fields stored with `_` prefix, **user filterable metadata stored bare**.
> Matches EventMemory's `_to_vector_record_property` translation so
> **the client-facing filter API (`producer_id`, `m.my_field`) Just Works.**"*

### 검색 쪽 변환이 정확히 맞물립니다

```python
# event_memory.py:341  _to_vector_record_property()
#   "producer_id"  →  "_producer_id"        (시스템 필드에 _ 부착)
#   "m.user_id"    →  "user_id"             (사용자 metadata는 접두사 제거)

internal_name, is_user_metadata = normalize_filter_field(field)
#   "m.user_id" → ("metadata.user_id", True)
if is_user_metadata:
    return demangle_user_metadata_key(internal_name)   # → "user_id"  (bare)
return f"_{field}"
```

**저장 시 bare, 검색 시 bare로 환원** → 일치. 그래서 동작합니다.

---

## 3. 전체 데이터 흐름 정리

```
[적재]
  REST  POST /api/v2/memories { org_id, project_id, messages[{ metadata: {...} }] }
    │
    ▼  MemMachine.add_episodes()                      main/memmachine.py:680
    │    ① episode_storage.add_episodes()  ← 원문 저장 + uid 발급  (필수 단계)
    │    ② episodic.add_memory_episodes()  ← 인덱싱
    ▼
  EpisodicMemory.add_memory_episodes()                episodic_memory.py
    │  metadata 중 단순 값만 → filterable_metadata 로 복사
    ▼
  LongTermMemory.add_episodes()                       long_term_memory.py:233
    │  backend == "event" 분기
    ▼
  _episode_to_event()                                 long_term_memory.py:632
    │  시스템 필드 → "_xxx"
    │  사용자 metadata → 그대로(bare)
    ▼
  EventMemory.encode_events() → VectorStore 저장

[검색]
  REST  POST /api/v2/memories/search { ..., filter: "m.user_id = 'user_a'" }
    │
    ▼  parse_filter(filter)                           main/memmachine.py query_search()
    │    filter 가 빈 문자열이면 None → 필터 없음(프로젝트 전체 검색)
    ▼
  EpisodicMemory.query_memory(property_filter=...)
    ▼
  LongTermMemory.search_scored()
    │  _validate_event_backend_filter()  ← 항목명 검증 (§5-③ 참조)
    ▼
  EventMemory._query()
    │  map_filter_fields(filter, _to_vector_record_property)
    │    "m.user_id" → "user_id"
    ▼
  VectorStore 검색:  파티션 조건  AND  user_id = 'user_a'
```

---

## 4. 정리 — 무엇이 되고 무엇이 안 되나

| 항목 | event 백엔드 | 비고 |
|---|---|---|
| `m.<키>` 필터 | ✅ 동작 | 실행 확인 |
| `metadata.<키>` 필터 | ✅ 동작 | 실행 확인 |
| 시스템 필드 필터 (`producer_id` 등) | ✅ 동작 | 실행 확인 |
| 목록·중첩 구조 metadata | ❌ 필터 불가 | 단순 값만 `filterable_metadata`로 복사됨 |
| `_` 로 시작하는 metadata 키 | ❌ 예외 발생 | 시스템 필드 사칭 방지 (의도된 동작) |
| 필터 생략 시 | ⚠ **프로젝트 전체 검색** | `filter` 기본값이 빈 문자열 |

---

## 5. "안 된다"고 관찰될 수 있는 실제 조건 3가지

주장한 쪽이 실제로 실패를 겪었다면 아래 중 하나일 가능성이 높습니다.

### ① 적재 시 `episode_storage`를 거치지 않은 경우 ★ 가장 유력

event 백엔드는 벡터스토어에 **원문 없이** 임베딩·속성·uid 참조(payload
`_episode_uid`)만 저장하고, 검색 시 원문을 episode store에서 되찾습니다.
게다가 그 uid는 관계형DB가 `INSERT … RETURNING`으로 발급하는 **자동증가 정수
PK**여서, 원문 저장을 건너뛰면 uid 자체가 없습니다. 복원 단계의 `int(uid)`
캐스팅이 실패해 **모든 검색이 실패**합니다.

```
ResourceNotFoundError: Invalid episode ID
```

**이것은 우리가 이미 발견해 수정한 버그입니다.** MemMachine 평가 하네스
(`evaluation/utils/agent_utils.py`)가 `EpisodicMemory.add_memory_episodes()`를
직접 호출하며 원문 저장 단계를 건너뛰고 있었습니다. declarative 백엔드는 원문이
그래프에 함께 저장되어 증상이 나타나지 않아, **event 백엔드에서만 "검색이 안 되는"
것처럼 보입니다.** → 주장의 증상과 정확히 일치합니다.

*(수정 내용: `agent_utils.ingest_episodes()` 헬퍼 추가 — 서버와 동일한
"원문 저장 → 인덱싱" 순서 복원)*

### ② `_` 접두사 키를 metadata에 넣은 경우

```
ValueError: Episode filterable_metadata contains reserved `_`-prefixed keys
            (event backend only): ['_user_id']
```
의도된 거부입니다. `_producer_id`, `_session_key` 등 시스템 필드를 사칭해
타 사용자 데이터에 접근하는 것을 막기 위한 장치입니다.

### ③ `properties_schema` 설정과 필터 키가 어긋난 경우

```python
# _validate_event_backend_filter()  (long_term_memory.py:575)
if self._user_property_keys and key not in self._user_property_keys:
    raise ValueError(f"Unknown user-metadata filter field {field!r}. ...")
```

| `properties_schema` 상태 | `m.user_id` 필터 | 색인 |
|---|---|---|
| 비어 있음 (기본값) | ✅ 동작 (검증 자체를 건너뜀) | ❌ 없음 → **느림** |
| `user_id: str` 등록 | ✅ 동작 | ✅ 생성됨 → 빠름 |
| 다른 키만 등록 | ❌ **오류** | — |

⚠ **성능 함정**: 등록하지 않아도 필터는 동작하기 때문에, 색인 없이 느리게
도는 상태가 조용히 만들어질 수 있습니다. 평가 환경 구성 시 반드시
`properties_schema`에 `user_id`를 등록해야 합니다.

---

## 6. 재현 방법

### 6.1 설정 파일 (`smoke_event.yml`) — 외부 서비스 불필요

```yaml
episode_store:
  database: sqlite_test

episodic_memory:
  long_term_memory:
    backend: event                    # ← event 백엔드
    embedder: openai_embedder
    vector_store: event_vector_store
    segment_store: sqlite_test
  short_term_memory:
    llm_model: openai_model
    message_capacity: 500

retrieval_agent:
  llm_model: openai_model
  reranker: my_reranker_id

semantic_memory:
  llm_model: openai_model
  embedding_model: openai_embedder
  database: sqlite_test
  config_database: sqlite_test

session_manager:
  database: sqlite_test

prompt:
  default_project_categories: [profile_prompt]

resources:
  databases:
    sqlite_test:
      provider: sqlite
      config: { path: /tmp/smoke_seg.db }
    event_vector_store:
      provider: sqlite_vector_store
      config:
        path: /tmp/smoke_vectors.db
        vector_search_engine: usearch
  embedders:
    openai_embedder:
      provider: openai
      config:
        model: "text-embedding-3-small"
        api_key: "unused-stubbed-in-test"
        base_url: "https://api.openai.com/v1"
        dimensions: 1536
  language_models:
    openai_model:
      provider: openai-responses
      config:
        model: "gpt-4o-mini"
        api_key: "unused-stubbed-in-test"
        base_url: "https://api.openai.com/v1"
  rerankers:
    my_reranker_id:
      provider: "identity"
```

### 6.2 테스트 스크립트 핵심부 — upstream 패키지만 사용

`evaluation/*` 를 전혀 import 하지 않습니다. 임베딩 API 호출을 없애기 위해
결정적 해시 임베더만 주입합니다(필터 로직과 무관한 계층).

```python
# ── upstream 서버 패키지만 import ──
from memmachine_server.common.configuration import Configuration
from memmachine_server.common.configuration.episodic_config import (
    EpisodicMemoryConf, LongTermMemoryConfPartial,
)
from memmachine_server.common.episode_store import EpisodeEntry
from memmachine_server.common.filter.filter_parser import parse_filter
from memmachine_server.common.resource_manager.resource_manager import ResourceManagerImpl
from memmachine_server.episodic_memory.episodic_memory import EpisodicMemory
from memmachine_server.episodic_memory.service_locator import (
    episodic_memory_params_from_config,
)

SESSION = "org1/prj1"        # 서버가 org_id/project_id 로 만드는 값과 동일 형식

cfg = Configuration.load_yml_file("smoke_event.yml")
rm  = ResourceManagerImpl(cfg)
rm.get_embedder = _stub_embedder          # 유일한 테스트 더블

# 설정 → EpisodicMemory (upstream service_locator 사용)
ltm_conf = LongTermMemoryConfPartial(session_id=SESSION).merge(
    cfg.episodic_memory.long_term_memory
)
conf = EpisodicMemoryConf(
    session_key=SESSION, long_term_memory=ltm_conf, short_term_memory=None,
    long_term_memory_enabled=True, short_term_memory_enabled=False,
)
memory = EpisodicMemory(await episodic_memory_params_from_config(conf, rm))
assert memory.long_term_memory._event_memory is not None      # event 백엔드 확인

# ── 서버(main/memmachine.py:700,720)와 동일한 순서로 적재 ──
episode_storage = await rm.get_episode_storage()
for uid in ("user_a", "user_b"):
    entries = [
        EpisodeEntry(
            content=f"[{uid}] {fact}",
            producer_id=uid, producer_role="user",
            metadata={"user_id": uid, "idx": i},      # ← 자유 metadata
        )
        for i, fact in enumerate(FACTS)
    ]
    episodes = await episode_storage.add_episodes(SESSION, entries)   # ① 원문 저장
    await memory.add_memory_episodes(episodes=episodes)               # ② 인덱싱

# ── 검색 ──
async def search(expr):
    f = parse_filter(expr) if expr else None
    resp = await memory.query_memory(QUERY, limit=10, property_filter=f)
    return [e.content for e in (resp.long_term_memory.episodes if resp else [])]

await search(None)                             # ① 전제 확인: 두 사용자가 섞여 나오는가
await search("m.user_id = 'user_a'")           # ②
await search("metadata.user_id = 'user_b'")    # ③
await search("producer_id = 'user_a'")         # ④
```

### 6.3 실행

```bash
cd /Users/taejin/Projects/MemMachine/repo
rm -f /tmp/smoke_seg.db /tmp/smoke_vectors.db
.venv/bin/python <스크립트 경로>
```

### 6.4 서버 모드로 확인하려면

```bash
# event 백엔드 설정으로 서버 기동 후
curl -X POST localhost:8080/api/v2/memories/search -H 'Content-Type: application/json' -d '{
  "org_id": "org1", "project_id": "prj1",
  "query": "what food do I like",
  "filter": "m.user_id = '\''user_a'\''"
}'
```

---

## 7. 문서 반영 사항

| 문서 | 조치 |
|---|---|
| `memmachine_vs_mem0_scoping.md` | **수정 불필요** — "event 백엔드에서 `m.<키>` 필터 가능"으로 이미 정확히 기술됨 |
| 전체 | **추가**: 두 백엔드의 metadata 저장 키 규칙 차이(§2)와 본 실증 결과를 근거로 인용 |

## 8. 근거 코드 위치

경로: `packages/server/src/memmachine_server/`

| 내용 | 파일 · 심볼 | 줄 |
|---|---|---|
| 백엔드별 분기 | `episodic_memory/long_term_memory/long_term_memory.py` · `add_episodes()` | 233 |
| declarative 변환 (오해의 원인) | 〃 · `_declarative_memory_episode()` | 461 |
| **event 변환 — metadata를 그대로 실음** | 〃 · `_episode_to_event()` | 632 |
| 필터 항목명 검증 | 〃 · `_validate_event_backend_filter()` | 575 |
| 검색 시 항목명 변환 | `episodic_memory/event_memory/event_memory.py` · `_to_vector_record_property()` | 341 |
| 필터를 벡터 검색에 전달 | 〃 · `_query()` | 398~ |
| 표기법 정규화 | `common/filter/filter_parser.py` · `normalize_filter_field()`, `demangle_user_metadata_key()` | 307, 326 |
| metadata → filterable_metadata (단순 값만) | `episodic_memory/episodic_memory.py` · `add_memory_episodes()` | 221~ |
| 등록 항목만 색인 생성 | `episodic_memory/long_term_memory/service_locator.py` · `_resolve_user_properties_schema()` | 190 |
| 서버의 적재 순서 (원문 → 인덱싱) | `main/memmachine.py` · `add_episodes()` | 680, 700, 720 |
