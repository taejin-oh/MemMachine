# Qdrant 요청과 임베딩 호출 — 측정 기록

- 측정일: 2026-09-15 (Qdrant), 2026-09-16 (임베딩)
- 대상 코드: upstream `speedkick` `a8322a7` (2026-09-14)
- 이 문서의 역할: **무엇을 어떻게 재서 어떤 숫자가 나왔는지의 원본 기록**

---

# 0부. 이 문서의 역할과 범위

## 0.1 역할

이 폴더에는 문서가 셋 있고 역할이 다르다.

| 문서 | 역할 |
|---|---|
| `qdrant_overview_2026-09-16.md` | 비전문가용 설명 |
| `qdrant_report_2026-09-16.md` | 분석과 결론. 두 가지 사용자 분리 방식, 캐시 리뷰, 권고 |
| **이 문서** | **측정 기록.** 측정 방법, 구간별 원본 수치, 요청 본문 실측 |

따라서 이 문서는 **측정에서 직접 읽히는 사실만** 적는다. 구조 해설, 방식 비교, 비용 판단, 권고는 보고서에 있고 여기서는 참조만 한다.

## 0.2 범위

**센 것은 Qdrant 요청과 임베딩 API 호출 두 가지뿐이다.**

**PostgreSQL 호출은 측정하지 않았다.** 요청 경로에 PostgreSQL 호출이 여러 번 있지만 이 문서의 어떤 숫자에도 포함되지 않는다. 두 저장소를 한 표에 섞으면 어느 쪽이 병목인지 알 수 없기 때문이다. PostgreSQL까지 세려면 별도 측정이 필요하다.

## 0.3 용어

상위 문서와 같은 이름을 쓴다. 이전 판에서 쓰던 이름을 괄호에 병기한다.

| 이름 | 뜻 |
|---|---|
| **바로 처리** (이전: 웜) | 인스턴스가 캐시에 있다 |
| **재준비** (이전: 콜드 인스턴스) | 캐시에 없다. 세션은 Qdrant registry에 등록돼 있다 |
| **신규 등록** (이전: 콜드 세션) | 캐시에도 없고 registry에도 없다 |
| 논리 호출 | MemMachine 코드가 임베더를 부른 횟수 |
| 파생(derivative) | 임베딩할 텍스트 단위. Qdrant 포인트 1개가 파생 1개다 |

---

# 1부. 측정 환경과 방법

## 1.1 환경

- speedkick `a8322a7` worktree, `uv sync --package memmachine-server --extra qdrant`
- Qdrant 1.17.0, PostgreSQL 16 컨테이너. 측정 후 제거했다
- 실제 `EpisodicMemoryManager`와 세션 DB를 그대로 사용해 캐시 적중과 미스를 운영과 동일하게 재현했다

## 1.2 Qdrant 계측 방법

`qdrant_client.http.api_client.AsyncApiClient.send_inner`를 감싸 모든 REST 요청의 메서드, 경로, 본문 요약, 상태 코드, 소요 시간을 기록했다.

스텁은 임베더 하나뿐이다(64차원 해시). 단기 기억은 껐고 리랭커는 쓰지 않았다.

## 1.3 임베딩 계측 방법

OpenAI 호환 `/v1/embeddings` 스텁 서버를 로컬에 띄우고 임베더의 `base_url`을 그쪽으로 돌려, 실제로 나가는 HTTP 요청의 입력 개수와 총 길이를 셌다. 동시에 `Embedder.ingest_embed`와 `search_embed`를 감싸 논리 호출 수를 따로 셌다.

임베더 구현은 운영과 같은 `OpenAIEmbedder`다. 스텁은 임베딩 서버뿐이다.

## 1.4 클라이언트

qdrant-client 1.19.0의 `AsyncQdrantClient`를 REST로 썼다(`prefer_grpc` 기본 false). 클라이언트 생성 시 호환성 확인 스레드가 `GET /`로 서버 버전을 읽고, 서버 1.17.0에 대해 "minor 차이는 1까지"라는 경고를 냈다. 서버는 1.18 이상이어야 경고가 없다.

---

# 2부. Qdrant 요청 측정 결과

## 2.1 상태별 요청 수

| 상태 | 저장 1건 | 검색 1건 | 에피소드 삭제 | 세션 삭제 |
|---|---|---|---|---|
| 바로 처리 | 1 | 1 | 1 | 3 |
| 재준비 | 2 | 2 | 2 | 4 |
| 신규 등록 | 18 | 18 | 해당 없음 | 해당 없음 |
| 프로세스 시작 | `GET /collections` 1회, `GET /` 1회(별도 스레드) | | | |

재준비에서 더해지는 1회는 registry 포인트 조회다. 신규 등록의 17회는 2.3에 내역이 있다.

한 요청에 에피소드가 몇 개든 저장은 1회다. 에피소드 수는 포인트 수에만 반영된다.

## 2.2 구간별 트레이스 (S1~S13)

원본은 `trace_output.txt`, 구조화된 데이터는 `qdrant_request_trace.json`, 스크립트는 `trace_qdrant_requests.py`다.

| 구간 | 내용 | Qdrant 요청 |
|---|---|---|
| P0 | 프로세스 시작: `get_vector_store(validate=True)` | 1 (`GET /collections`) |
| S1 | 첫 세션 A 열기 (registry, native 모두 없음) | 17 |
| S2 | 두 번째 새 세션 B 열기 (native 있음, registry 엔트리 없음) | 17 |
| S3 | A 다시 열기 (캐시 적중) | 0 |
| S4 | A에 에피소드 4건 저장 | 1 (upsert, points=4) |
| S5 | A에 에피소드 2건 저장 | 1 (upsert, points=2) |
| S6 | 검색, 필터 없음, top_k 20 | 1 (limit 80) |
| S7 | 검색, OR 필터 | 1 (limit 80) |
| S8 | 검색, `m.user_id` 필터, `expand_context=4` | 1 (limit 80) |
| S9 | 검색, top_k 5, `score_threshold=0.1` | 1 (limit 20) |
| S10 | A를 캐시에서 제거 (`close_session`) | 0 |
| S11 | A 다시 열고 검색 1회 | 2 (registry 조회, query/batch) |
| S12 | 에피소드 1건 삭제 | 1 (delete) |
| S13 | 세션 B 삭제 (캐시에 없음) | 4 |

S6부터 S9까지가 보여주는 것은 **검색 옵션을 바꿔도 요청 수가 1회로 같다**는 점이다. 바뀌는 것은 요청 안의 `limit` 값뿐이다.

## 2.3 신규 등록 17회의 내역

`long_term_memory/service_locator.py`의 `_event_params`는 `open_collection`을 먼저 부르고, 없으면 `create_collection`을 부른 뒤 `open_collection`을 다시 부른다.

| 순서 | 요청 | 첫 세션(S1) | 두 번째 새 세션(S2) |
|---|---|---|---|
| 1 | `POST …__registry/points` (id 조회) | 404 | 200, 빈 결과 |
| 2 | `PUT /collections/long_term_memory__registry` | 200 | 409 |
| 3 | `POST …__registry/points` (id 조회) | 200, 빈 결과 | 200, 빈 결과 |
| 4 | `PUT /collections/long_term_memory__<hash>` | 200 | 409 |
| 5~15 | `PUT …__<hash>/index?wait=true` 11회 | 200 | 200 |
| 16 | `PUT …__registry/points?wait=true` (포인트 1개) | 200 | 200 |
| 17 | `POST …__registry/points` (id 조회) | 200 | 200 |

두 번째 세션부터는 2번과 4번이 409로 돌아오고 코드가 "이미 있음"으로 처리한다. 총 요청 수는 17회로 같다.

**인덱스 11회는 컬렉션이 이미 있어도 매번 나간다.** 이는 낭비가 아니라 의도된 동작이다. 이전에는 컬렉션 생성과 인덱스 생성을 한 덩어리로 처리해서, 컬렉션이 이미 있으면 첫 호출에서 예외가 나며 **인덱스가 하나도 만들어지지 않았다.** 커밋 `a2a1754`가 둘을 분리하고 인덱스를 개별로 보내도록 고쳤다.

S1 상세 (상태 코드와 소요 시간은 로컬 Docker 기준):

```
[404   5.3ms] POST /collections/long_term_memory__registry/points  ids=1
[200  83.6ms] PUT  /collections/long_term_memory__registry  vectors size=1 cosine, hnsw m=0
[200   6.5ms] POST /collections/long_term_memory__registry/points  ids=1
[200  81.0ms] PUT  /collections/long_term_memory__<hash>  vectors size=64 cosine, hnsw m=0 payload_m=16
[200  88.2ms] PUT  …/index?wait=true  sys-partition_key keyword is_tenant=true
[200  72.5ms] PUT  …/index?wait=true  _timestamp datetime
[200  66.1ms] PUT  …/index?wait=true  _episode_uid keyword
[200  58.8ms] PUT  …/index?wait=true  _session_key keyword
[200  49.4ms] PUT  …/index?wait=true  _producer_id keyword
[200  53.1ms] PUT  …/index?wait=true  _producer_role keyword
[200  42.2ms] PUT  …/index?wait=true  _produced_for_id keyword
[200  73.9ms] PUT  …/index?wait=true  _sequence_num integer
[200  55.1ms] PUT  …/index?wait=true  _episode_type keyword
[200  75.7ms] PUT  …/index?wait=true  _content_type keyword
[200  32.1ms] PUT  …/index?wait=true  _created_at datetime
[200   3.3ms] PUT  /collections/long_term_memory__registry/points?wait=true  points=1 dim=1
[200   2.9ms] POST /collections/long_term_memory__registry/points  ids=1
```

첫 세션에서는 인덱스 생성이 각 32~88ms였고, 두 번째 새 세션에서는 각 3ms 안팎이었다. 17회는 전부 직렬로 나간다.

## 2.4 요청 본문 실측

### 저장 (S4)

```
PUT /collections/long_term_memory__<hash>/points?wait=true
  points=4 dim=64
  payload_keys=[_content_type, _created_at, _episode_type, _episode_uid, _produced_for_id,
                _producer_id, _producer_role, _sequence_num, _session_key, _timestamp,
                sys-partition_key, user_id]
```

`wait=true`는 qdrant-client의 기본값이고 MemMachine이 바꾸지 않는다. 요청이 실패하면 포인트 목록을 반으로 나눠 재시도하고, 1개까지 줄어도 실패하면 예외를 올린다.

### 검색 (S6, S7, S9)

```
POST /collections/long_term_memory__<hash>/points/query/batch
  searches=1  limit=80  with_payload=false  with_vector=false
  filter={"must":[{"key":"sys-partition_key","match":{"value":"bd36…"}}]}
```

```
(필터 producer_id = 'user_a' OR produced_for_id = 'user_a')
  searches=1  limit=80
  filter={"must":[
    {"must":[{"key":"sys-partition_key","match":{"value":"bd36…"}}]},
    {"should":[{"must":[{"key":"_producer_id","match":{"value":"user_a"}}]},
               {"must":[{"key":"_produced_for_id","match":{"value":"user_a"}}]}]}]}
```

```
(top_k=5, score_threshold=0.1)
  searches=1  limit=20   ← limit만 바뀌고 score_threshold는 요청에 없다
```

측정에서 직접 읽히는 세 가지다.

- `limit`은 top_k의 4배다
- `with_payload=false`, `with_vector=false`이므로 돌아오는 것은 포인트 id와 점수뿐이다
- `score_threshold`는 요청에 실리지 않는다

### 삭제 (S12, S13)

```
에피소드 삭제: POST …/points/delete?wait=true
  {"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"bd36…"}}]},
                     {"has_id":["e99d…"]}]}}

세션 삭제:     POST …__registry/points                      (열기)
              POST …__registry/points                      (delete_collection 안)
              POST …__<hash>/points/delete?wait=true       {"filter":{"must":[{파티션 조건}]}}
              POST …__registry/points/delete?wait=true     {"points":["c41b…"]}
```

세션 삭제 4회는 인스턴스가 캐시에 없어 열 때 registry 조회 1회가 더해진 값이다. 캐시에 있으면 3회다.

## 2.5 저장된 포인트의 모양 (실측)

- id: `derivative.uuid`(무작위 uuid4). 에피소드 uid와의 연결은 payload의 `_episode_uid`가 갖는다
- vector: 임베더 차원 (측정은 64차원 해시 임베더, 운영 구성은 1536)
- payload: 위 저장 요청의 12개 키. 사용자 metadata(`user_id`)는 접두사 없이 들어간다
- **본문 텍스트는 Qdrant에 저장하지 않는다**

파티션 키는 세션 키가 규칙에 맞으면 그대로, 아니면 `sha256[:32]`다. 실측에서 `orga/prja`는 `bd36dbe5eef78ec754963d978108ef7b`로 저장됐다.

---

# 3부. 임베딩 호출 측정 결과

## 3.1 구간별 (E1~E11)

원본은 `embed_trace_output.txt`, 구조화된 데이터는 `embedding_call_trace.json`, 스크립트는 `trace_embedding_calls.py`, 설정은 `config_embed.yml`이다.

| 구간 | 내용 | 논리 호출 | HTTP 요청 |
|---|---|---|---|
| E1 | 첫 세션 열기. 임베더를 `validate=True`로 생성 | 1 (`search_embed`) | 1 |
| E2 | 두 번째 새 세션. 임베더는 이미 캐시됨 | 0 | 0 |
| E3 | 에피소드 4건 저장 | 1 (`ingest_embed`) | 1 (입력 4개, 336자) |
| E4 | 에피소드 1건 저장 | 1 | 1 (입력 1개, 84자) |
| E5 | 검색, top_k 20 | 1 (`search_embed`) | 1 (입력 1개, 16자) |
| E6 | 검색, `expand_context=4`, top_k 5 | 1 | 1 |
| E7 | 16만 자 에피소드 1건 저장 | 1 | **3** (75,000 / 75,000 / 10,039자) |
| E8 | 에피소드 2,100건 저장 | 1 | **3** (854 / 836 / 410개) |
| E9 | `batch_size=2` 임베더로 5건 저장 | 2 (검증 1, 저장 1) | 4 (검증 1, 저장 3) |
| E10 | `sentence_text` 파생, 2건이 각 3문장 | 1 | 1 (입력 6개) |
| E11 | 인스턴스 캐시 제거 후 검색 | 1 | 1 |

E11이 보여주는 것은 **임베딩 논리 호출 수가 캐시 상태와 무관하다**는 점이다. 재준비 상태여도 검색 1회다.

E8에서는 개수 2,048 제한보다 총 75,000자 제한이 먼저 걸렸다.

## 3.2 분할 규칙

OpenAI 임베더가 논리 호출 1회를 HTTP 요청 여러 건으로 나누는 순서다.

1. `batch_size`가 설정돼 있으면 입력을 그 크기로 잘라 내부 함수를 동시에 부른다. 기본은 미설정이다
2. 입력 하나가 `max_input_length`(설정) 또는 75,000자를 넘으면 그 길이로 자른다
3. 잘린 조각을 요청 단위로 묶는다. 한 요청은 입력 2,048개 이하, 총 75,000자 이하다
4. 묶음마다 HTTP 요청을 만들어 동시에 보낸다
5. 입력 하나가 여러 조각이었으면 조각 임베딩을 길이로 가중 평균해 벡터 1개로 만든다

5번 때문에 **Qdrant 포인트 수는 조각 수와 무관하다.** E7은 HTTP 3건이었지만 Qdrant 포인트는 1개다.

운영값으로 환산하면 메시지 평균 400자일 때 한 저장 요청에 약 187건이 넘어가면 HTTP 요청이 하나 더 생긴다.

## 3.3 호출 지점

| 경로 | 호출 | 입력 개수 |
|---|---|---|
| 저장 | `ingest_embed` 1회 | 파생 수. 기본 구성에서는 에피소드 수와 같다 |
| 검색 | `search_embed` 1회 | 1개(질의문) |
| 임베더 최초 생성 | `search_embed(["a"])` 1회 | 1개. 임베더 이름당 프로세스당 1회 |
| 리랭커가 임베더 기반일 때 | 검색마다 2회 | 측정 구성은 identity라 0회 |

단기 기억은 임베딩을 하지 않는다.

## 3.4 재시도

모든 호출부가 `max_attempts`를 넘기지 않아 기본값 1이 쓰인다. **429나 5xx를 받으면 재시도 없이 예외가 올라간다.** 임베더 안에 재시도 루프와 최대 120초 백오프가 있지만 `max_attempts=1`에서는 한 번도 돌지 않는다.

`dimensions` 파라미터는 항상 실어 보냈다(실측). 모델이 거부하면 그 요청만 파라미터 없이 한 번 더 보내고, 이후 그 인스턴스에서는 계속 빼고 보낸다.

---

# 4부. 측정하지 않고 코드로만 확인한 것

아래는 실행 트레이스에 나타나지 않았고 코드 기준으로만 정리한 항목이다. **숫자를 그대로 인용하기 전에 직접 측정할 필요가 있다.**

| 항목 | 코드 기준 내용 |
|---|---|
| 시맨틱 메모리의 `vector_store` 백엔드 | 측정 구성은 pgvector라 Qdrant 요청이 0회였다. `storage_backend: vector_store`로 바꾸면 시작 시 1~16회, 검색 시 set_id마다 limit 10,000짜리 검색 1회가 나간다 |
| 시맨틱 적재의 특징별 임베딩 | 백그라운드 루프가 기본 2초 간격으로 돌며, 미적재 5건 이상이거나 5분 초과인 set을 처리한다(OR). 특징 하나당 `ingest_embed` 1회이고 배치로 묶지 않는다. 시맨틱 기본값은 꺼짐이다 |
| `agent_mode=true` 검색 | 하위 질의마다 검색이 반복되어 Qdrant 요청이 2~22회가 된다 |
| 분산 모드 | 세션 생성 때 `create_shard_key` 1회가 추가되고 세션마다 샤드가 하나 생긴다. 세션 삭제는 포인트 삭제 대신 `delete_shard_key`를 부른다 |
| `GET /`(버전 확인) | 별도 스레드의 동기 요청이라 트레이스에 잡히지 않았다. 경고 문구로 발생을 확인했다 |
| Qdrant 서버 내부 처리 | 이전 소스 분석(v1.19.1) 인용이며 이번에 서버 내부를 계측하지 않았다. 카디널리티 추정과 하위 그래프 임계값은 보고서 7.3에 있다 |

---

# 5부. 한계

- **PostgreSQL 호출 수를 측정하지 않았다**(0.2). 이 문서의 숫자로 전체 부하를 추정할 수 없다
- 측정은 단일 프로세스, 단일 worker다. worker를 늘렸을 때의 배수는 코드 기준 추론이며 보고서 10부에 있다
- 실제 규모(사용자 수백 명, 세션당 수천 건)로 돌린 결과가 아니다. 하위 그래프 생성 임계값을 넘긴 상태의 검색은 측정하지 않았다
- 임베딩 측정의 서버는 스텁이므로 실제 API의 지연과 오류율은 반영되지 않는다

---

# 부록 A. 코드 근거

경로는 `packages/server/src/memmachine_server/` 기준, 커밋 `a8322a7`.

**Qdrant 호출 계층**
- `common/vector_store/qdrant_vector_store.py:64-73` 파티션 필터. `:87-108` 필터 변환. `:294-328` `upsert`와 반분 재시도. `:331-387` `query`. `:390-414` `delete`. `:483-492` registry 상수. `:494-500, 557-559` 프로세스 내 이름 잠금. `:550` `_hnsw_m = 16`. `:569-589` registry 컬렉션 생성. `:591-622` registry 조회. `:649-704` native 컬렉션과 인덱스 생성(`m=0, payload_m=16`은 `:669-672`). `:743-772` `create_collection`. `:775-812` `open_or_create_collection`. `:815-832` `open_collection`. `:839-887` `delete_collection`.
- `common/resource_manager/database_manager.py:590-644` 클라이언트와 스토어 생성. `:647-657` 연결 확인. `:859-872` `get_vector_store`.

**장기 기억 이벤트 백엔드**
- `episodic_memory/long_term_memory/service_locator.py:51` 네임스페이스. `:88-155` 열기와 생성 순서(`:106, 118, 123`). `:158-182` 파티션 키 규칙.
- `episodic_memory/long_term_memory/long_term_memory.py:79-89` 시스템 필드 인덱스 스키마. `:107` 4배 여유분. `:310-313` limit 계산. `:340` 점수 컷. `:387-424` 세션 파티션 삭제. `:735-794` 에피소드를 이벤트로 변환.
- `episodic_memory/event_memory/event_memory.py:221-314` 저장 단계(`:269` 임베딩, `:290` upsert). `:395-522` 검색 단계(`:406` 임베딩, `:420` Qdrant 검색, `:450` 문맥 조회). `:678-712` 삭제.
- `common/configuration/episodic_config.py` 세그먼터 기본 passthrough, 파생기 기본 whole_text.

**캐시와 수명**
- `episodic_memory/episodic_memory_manager.py:43-52` 용량 100과 유휴 600초 기본값. `:103-106` 2초 주기 청소. `:137-165` 열기 경로. `:228-289` `open_or_create_episodic_memory`.
- `episodic_memory/instance_lru_cache.py:128` `get`이 전역 쓰기 잠금을 잡음. `:174-185` 용량 초과 시 제거. `:206-219` 유휴 제거.
- `common/resource_manager/resource_manager.py:254-266` 매니저를 기본값으로 생성. **주입하는 곳이 없어 항상 기본값이다**(설정 항목이 아니라 미주입 기본값).
- `main/memmachine.py:427-475` 시작 시 예열. `:735-788` 저장 흐름. `:797-849` 검색 흐름. `:1002-1073` `query_search`. `:1186-1219` 에피소드 삭제.

**임베딩**
- `common/embedder/embedder.py:15-57` `batch_size` 분할과 동시 호출, `max_attempts` 기본값 1.
- `common/embedder/openai_embedder.py:70-73` 요청당 상한. `:137-146` 청크 분할과 클러스터 구성. `:171-182` 동시 전송. `:193-209` 길이 가중 평균. `:236-253` `dimensions` 처리. `:260-` 재시도 루프(실행되지 않음).
- `common/utils.py:119-134` `chunk_text`. `:224-272` `cluster_texts`.
- `common/resource_manager/embedder_manager.py:57-66` 이름별 캐시. `:134-143` `validate`가 `search_embed(["a"])` 1회.
- `common/reranker/identity_reranker.py:9-13` 측정 구성의 리랭커는 호출이 없음.

**시맨틱과 에이전트 (측정 안 함)**
- `common/resource_manager/semantic_manager.py:126-172` `vector_store` 백엔드 컬렉션 열기.
- `semantic_memory/storage/vector_store_semantic_storage.py:55` limit 10,000. `:604-648` 벡터 검색.
- `semantic_memory/semantic_memory.py:98-101` 백그라운드 기본값. `:430-468` 임베더별 1회. `:783-838` 백그라운드 루프.
- `retrieval_agent/agents/rarag_query_agent.py:194-196` 하위 검색 limit. `:252-306` 겹침당 검색과 상한 20.

**qdrant-client 1.19.0**
- `async_qdrant_remote.py:199-232` 버전 확인 스레드와 경고 문구.
- `async_qdrant_client.py` `upsert`, `delete`, `create_payload_index`의 `wait` 기본값 True.

**Qdrant 서버 소스** (`scratchpad/qdrant_src/`)
- `v1.19.1/hnsw/read_view/dispatch.rs:113-170` 카디널리티에 따른 경로 판단.
- `v1.19.1/hnsw/read_view/search.rs:43-45`, `v1.19.1/more/graph_layers.rs:525` `ef = max(ef, top)`.
- `v1.19.1/config.yaml` `full_scan_threshold_kb`, `indexing_threshold_kb` 기본 10000.

# 부록 B. 클라이언트 메서드와 REST 요청 대응

| 클라이언트 메서드 | REST 요청 | 쓰이는 곳 |
|---|---|---|
| `get_collections()` | `GET /collections` | 연결 확인(프로세스당 1회) |
| (생성자) | `GET /` | 버전 확인 스레드 |
| `retrieve(ids=[uuid5])` | `POST /collections/{registry}/points` | 컬렉션 열기, 생성, 삭제 |
| `create_collection()` | `PUT /collections/{name}` | 세션 생성(registry, native) |
| `create_payload_index()` | `PUT /collections/{name}/index?wait=true` | 세션 생성 11회 |
| `upsert(points, wait=True)` | `PUT /collections/{name}/points?wait=true` | 저장, registry 등록 |
| `query_batch_points()` | `POST /collections/{name}/points/query/batch` | 검색 |
| `delete(points_selector, wait=True)` | `POST /collections/{name}/points/delete?wait=true` | 에피소드 삭제, 세션 삭제 |
| `create_shard_key()`, `delete_shard_key()` | `PUT …/shards`, `POST …/shards/delete` | 분산 모드에서만 |

# 부록 C. 근거 파일

| 파일 | 내용 |
|---|---|
| `trace_output.txt` | Qdrant 요청 트레이스 원본 |
| `qdrant_request_trace.json` | 같은 내용의 구조화 데이터 |
| `trace_qdrant_requests.py` | Qdrant 계측 스크립트 |
| `embed_trace_output.txt` | 임베딩 호출 트레이스 원본 |
| `embedding_call_trace.json` | 같은 내용의 구조화 데이터 |
| `trace_embedding_calls.py`, `config_embed.yml` | 임베딩 계측 스크립트와 설정 |
| `verify_producer_filter.py` | 사용자 필터 회수율 검증 스크립트 |

# 부록 D. 이전 판에서 정정한 내용

| 이전 서술 | 정정 |
|---|---|
| 용량 100과 유휴 600초는 "설정 파일로 바꿀 수 없다", "YAML로 바꿀 수 없다" | 주입 가능하지만 아무도 주입하지 않는 기본값이다. 조정 수단이 없다는 결론은 같다 |
| 인덱스 11회는 이미 있는 것을 다시 만드는 요청 | 사실이나 이유가 빠졌다. 인덱스 누락 결함을 고치기 위한 의도된 동작이다(`a2a1754`) |
| "워커가 N개면 콜드 비용도 N배다" | 부정확하다. 재준비 비용은 worker 수에 비례하지만, **신규 등록 17회는 worker 수와 무관하고 새 세션 수에 비례한다** |
| 검색 옵션 표에 PostgreSQL 문맥 조회가 섞여 있었다 | 이 문서는 Qdrant와 임베딩만 센다. PostgreSQL은 측정하지 않았다(0.2) |
| 8장 "비용 관점에서 눈에 띄는 점" 11개 항목 | 분석과 판단이라 보고서로 옮겼다. 이 문서는 측정 기록으로 좁혔다 |
| 용어 웜 / 콜드 인스턴스 / 콜드 세션 | 바로 처리 / 재준비 / 신규 등록으로 통일했다(0.3) |
