# MemMachine 필터 요소 정리

*2026-08-21 · 기준 `upstream/main` `2d28c1c` · event 백엔드 · 소스 코드 확인*

---

## 0. 한눈에 — 필터 요소는 3층

```
① 파티션 (org_id/project_id)      자동·강제. 지정 안 해도 매 검색에 걸림
② 시스템 필드 9종                  등록 불필요 + 색인 자동. 바로 필터 가능
③ 사용자 정의 metadata (m.<키>)    등록 없이도 동작하나, 등록해야 색인 생성
```

| | 등록 | 색인 | 오타 검증 | 필터 |
|---|---|---|---|---|
| ① 파티션 | — | 자동 | — | **자동 적용** |
| ② 시스템 필드 9종 | **불필요** | **자동** | **오류로 잡아줌** | 즉시 가능 |
| ③ 사용자 metadata | 필요 | 등록분만 | 미등록 시 **검증 생략** | 가능(느릴 수 있음) |

컬렉션 생성 시 색인 스키마가 이렇게 조립되기 때문이다:

```python
indexed_properties_schema = {
    **EventMemory.expected_vector_store_collection_schema(),
    **EVENT_BACKEND_SYSTEM_FIELDS,   # ← 9종, 항상 포함 (자동)
    **user_schema,                   # ← properties_schema 에서 온 것 (등록분)
}
```

---

## 1. 시스템 필드 9종 — 코드 고정, 자동 색인

| # | 필터명 (bare) | 저장 키 | 타입 | 값 | 실용도 |
|---|---|---|---|---|---|
| 1 | `episode_uid` | `_episode_uid` | str | 관계형DB `episodestore.id` = **자동증가 정수 PK**를 문자열화 | 특정 건 지정 |
| 2 | `session_key` | `_session_key` | str | `org_id/project_id` | 파티션과 중복 → 거의 안 씀 |
| 3 | **`producer_id`** | `_producer_id` | str | **발화 주체** (사람 또는 에이전트) | ★ 사용자 구분에 가장 근접 |
| 4 | **`producer_role`** | `_producer_role` | str | `user` / `assistant` / `system` 등 | ★ 발화자 유형 분리 |
| 5 | **`produced_for_id`** | `_produced_for_id` | str \| null | **수신 대상** | ★ 대화 상대 구분 |
| 6 | `sequence_num` | `_sequence_num` | int | 세션 내 순번 (기본 0) | 구간 자르기 |
| 7 | `episode_type` | `_episode_type` | str | 현재 `message` | 종류별 필터 |
| 8 | `content_type` | `_content_type` | str | 현재 `string` **하나뿐** | 사실상 무의미 |
| 9 | **`created_at`** | `_created_at` | datetime | 생성 시각 (별칭 `timestamp`) | ★ 기간 필터 |

**실질적으로 유효한 것은 5개**: `producer_id` · `producer_role` · `produced_for_id` · `created_at` · `sequence_num`
(`content_type` 은 값이 하나, `session_key` 는 파티션과 중복, `episode_uid` 는 단건 조회용)

> `episode_uid` 는 타입이 `str` 이라 **숫자 범위 비교로는 못 쓴다** (`"10" < "9"`).
> 값이 행마다 고유한 최고 카디널리티 필드라 색인 표는 N행이 되고 값-그룹은 크기 1이다.

### 시스템 필드의 3가지 이점

**① 등록 불필요 + 색인 자동**
`EVENT_BACKEND_SYSTEM_FIELDS` 에 하드코딩되어 컬렉션 생성 시 항상 색인된다.

**② 오타를 오류로 잡아준다**
```sql
producer_id = 'u1'    -- OK
producr_id  = 'u1'    -- ValueError: Unknown filter field 'producr_id'
```
9종 목록과 대조하므로 조용히 0건이 나오는 사고가 없다.
(사용자 metadata는 `properties_schema` 가 비어 있으면 이 검증을 건너뛴다.)

**③ 사칭 차단**
`metadata: {"_producer_id": "victim"}` 처럼 `_` 접두사 키를 넣으면 `ValueError` 로 거부한다.
시스템 필드를 위조해 타인 데이터에 접근하는 것을 막는 장치다.

---

## 2. ⚠ `producer_id` 로 사용자를 구분할 때의 함정

`producer_id` 는 등록 없이 색인이 붙어 있어 매력적이지만, 의미가 **"발화 주체"** 다.

```
사용자 발화      → producer_id = "user_123",  produced_for_id = "assistant"
어시스턴트 응답  → producer_id = "assistant", produced_for_id = "user_123"
```

따라서:

| 필터 | 결과 |
|---|---|
| `producer_id = 'user_123'` | **그 사용자의 발화만.** 어시스턴트 응답은 빠짐 |
| `producer_id = 'user_123' OR produced_for_id = 'user_123'` | 양방향 대화 전체 |
| `m.user_id = 'user_123'` | 양쪽 에피소드에 모두 심어두면 한 번에 해결 |

**권장**: 사용자 단위 검색이 목적이면 `m.user_id` 를 양쪽 에피소드에 심고
`properties_schema` 에 등록한다. `producer_id` 는 **발화자 유형을 나눌 때** 쓴다.

```sql
-- 그 사용자의 대화 전체
m.user_id = 'user_123'
-- 그중 사용자 발화만
m.user_id = 'user_123' AND producer_role = 'user'
```

---

## 2.5 ⚠ 같은 필터가 문맥 확장에서는 인덱스를 못 탄다

`expand_context > 0`이면 같은 `filter` 식이 관계형 테이블 `segment_store_sg`에도
적용된다. 그런데 그쪽 인덱스는 둘뿐이다:

```
segment_store_sg__pk_ev            (partition_key, event_uuid)
segment_store_sg__pk_ts_ev_bk_ix   (partition_key, timestamp, event_uuid, index, offset)
```

| 필터명 | 세그먼트 테이블에서 | 인덱스 |
|---|---|---|
| **`timestamp`** | 실제 컬럼 | **✅** |
| `created_at` · 시스템 필드 8종 · `m.*` 사용자 metadata | `properties` **JSON** | ❌ |

- 의미는 정확하다 — 필터가 `LIMIT` 앞에 적용돼 **"그 사용자의 직전 N개"**가 나온다
- 대신 정렬 인덱스를 걸으며 **행마다 JSON 평가**한다. 비용은 대상의 **발화 밀도**에 반비례
- `properties_schema` 등록은 **도움이 안 된다** (벡터스토어 컬렉션에만 반영)
- `expand_context` 기본값 **0**에서는 이 경로가 열리지 않는다

> **`timestamp`와 `created_at`은 같은 값인데 비용이 다르다.**
> 기간 조건은 `timestamp`를 쓰는 편이 유리하다.

상세: `memmachine_vectordb_full_guide.md` §3.6

---

## 3. 연산자

```
비교      =   !=   <>   >   <   >=   <=
멤버십    IN (...)      NOT IN (...)
NULL      IS NULL       IS NOT NULL
논리      AND   OR   NOT   + 괄호 중첩
```

```sql
m.user_id = 'u1' AND created_at >= '2026-01-01'
episode_type IN ('message','summary') AND NOT m.archived = true
m.user_id = 'u1' AND (sequence_num > 100 OR m.pinned = true)
produced_for_id IS NOT NULL
```

**제약**: `IN` 목록은 int 또는 str만, 혼합 불가.
사용자 metadata는 **단순 값만**(str/int/float/bool/datetime) — 리스트·중첩 객체는 필터 불가.

---

## 4. Mem0와의 차이 (요점)

| | Mem0 | MemMachine |
|---|---|---|
| 강제 스코프 | **신원 ID 최소 1개** — 없으면 오류 | **파티션만** — 사용자 필터는 선택 |
| 필터 누락 시 | 오류로 거부 | **조용히 프로젝트 전체 반환** ⚠ |
| 표현력 | 딕셔너리 | **문자열 식 — 비교·IN·NULL·중첩 논리** |
| 색인 자동 생성 | user/agent/run/actor 4종 | **시스템 9종 + 등록한 metadata** |

> 표현력은 MemMachine이 강하고, **누락 방지 장치는 Mem0가 강하다.**

---

## 5. `properties_schema` 등록 — API만으로 가능

설정 파일 수정·서버 재시작 불필요. **프로젝트 생성 시** 함께 지정한다.

```bash
curl -X POST localhost:8080/api/v2/projects \
  -H 'Content-Type: application/json' -d '{
    "org_id": "sk-hynix", "project_id": "user_123", "description": "",
    "config": {
      "backend": "event",
      "embedder": "openai_embedder",
      "vector_store": "event_vector_store",
      "segment_store": "profile_storage",
      "properties_schema": { "user_id": "str", "session_id": "str" }
    }
  }'
```

허용 타입: `"bool" "int" "float" "str" "datetime"` 5종.

확인:
```bash
curl -X POST localhost:8080/api/v2/projects/get -H 'Content-Type: application/json' \
  -d '{"org_id":"sk-hynix","project_id":"user_123"}'
```

---

## 6. ⚠ 함정 3가지

### ① 등록 안 해도 필터는 "동작한다" — 대신 느리다

| 등록 여부 | 필터 | 색인 | 결과 |
|---|---|---|---|
| 등록함 | ✅ | ✅ | 정상 |
| **미등록** | **✅ 동작** | ❌ | **전수 스캔 — 조용히 느려짐** |

오류가 나지 않으므로 성능 문제로만 뒤늦게 드러난다.
(시스템 필드 9종은 이 문제가 없다 — 항상 색인됨)

### ② 프로젝트마다 스키마가 다르면 컬렉션이 갈라진다

컬렉션 이름 = `sha256(차원 + metric + indexed_properties_schema)`

```
프로젝트 A: {user_id: str}             → 컬렉션 X
프로젝트 B: {user_id: str, dept: str}  → 컬렉션 Y   ← 별개 컬렉션
```

사용자당 프로젝트로 가면서 스키마를 제각각 주면 **사용자마다 컬렉션이 생겨**
벤더가 금지한 안티패턴에 그대로 빠진다.

### ③ 나중에 추가할 수 없다

```python
collection = await vector_store.open_collection(...)
if collection is None:        # 이미 있으면 스키마를 다시 보지 않음
    create_collection(...)
```

데이터가 들어간 뒤 키를 추가하면 값은 저장되나 **색인이 생기지 않는다**(=①의 상태).
바꾸려면 컬렉션을 새로 만들어야 한다.

---

## 7. 운영 규칙 (평가 환경 구성용)

| # | 규칙 |
|---|---|
| 1 | `properties_schema` 는 **첫 프로젝트 생성 시점에 확정**한다 |
| 2 | **모든 프로젝트에 동일한 스키마**를 사용한다 (구성 스크립트에 상수로 고정) |
| 3 | 최소 `user_id: str` 등록. 세션 구분이 필요하면 `session_id: str` 추가 |
| 4 | 사용자 단위 검색은 `m.user_id` 사용. `producer_id` 는 발화자 유형 분리용 |
| 5 | 클라이언트에서 **`filter` 누락 방지 장치**를 둔다 (서버가 강제하지 않음) |
| 6 | 측정 전 `indexed_vectors_count` 확인 — 0이면 전수 스캔 중이라 비교 무의미 |

```bash
curl -s localhost:6333/collections/<이름> \
  | jq '.result | {points_count, indexed_vectors_count, segments_count}'
```

---

## 8. 근거 위치

경로: `packages/server/src/memmachine_server/`

| 내용 | 파일 · 심볼 |
|---|---|
| **시스템 필드 9종 정의** | `episodic_memory/long_term_memory/long_term_memory.py` · `EVENT_BACKEND_SYSTEM_FIELDS` |
| bare 이름 목록 + `timestamp` 별칭 | 〃 · `_EVENT_BACKEND_SYSTEM_FIELD_CLIENT_NAMES` |
| 필터 문법·연산자 | `common/filter/filter_parser.py` |
| 필터 검증 규칙 (오타·미등록 키) | `long_term_memory.py` · `_validate_event_backend_filter()` |
| `_` 접두사 사칭 차단 | 〃 · `_episode_to_event()` |
| 파티션 조건 항상 적용 | `common/vector_store/qdrant_vector_store.py` · 검색부 `must=[partition_key_filter, ...]` |
| 색인 스키마 조립 (9종 + 등록분) | `episodic_memory/long_term_memory/service_locator.py` · `_event_params()` |
| 기존 컬렉션이면 스키마 재적용 안 함 | 〃 |
| 프로젝트 config → LTM 설정 | `server/api_v2/router.py` · `_ltm_partial_from_project_config()` |
| `properties_schema` 스펙·타입 검증 | `packages/common/.../api/spec.py` · `ProjectConfig.properties_schema` |
| 스키마 → 컬렉션 이름 해시 | `qdrant_vector_store.py` · `_build_native_collection_name()` |
| Episode 필드 원본 | `common/episode_store/episode_model.py` · `class Episode` |
