# 인수인계 — MemMachine 관측(Prometheus + Grafana) 구축·검증

*작성 2026-09-08 · 개정 2026-09-14 · 기준 `upstream/speedkick` `acb4f9a` · 경로 접두사 `packages/server/src/memmachine_server/`*

---

# ★ 1순위: MVP — 그라파나에 지표 띄우기

**목표를 한 줄로**: 현재 코드를 **고치지 않고**, 이미 들어있는 지표를 그라파나 화면에 띄운다.

**전제**: MemMachine 서버가 이미 뜬다(포트 8080). 안 뜨면 그것부터. 그 외 추가 개발은 없다.

**핵심 사실 두 가지만 알면 된다**:

1. 코드에 이미 계측이 들어 있고 `/api/v2/metrics`로 나온다. **켜는 설정은 필요 없다** (`metrics_factory_id` 기본값 = `"prometheus"`).
2. ⚠ **단계별 구간 지표(`event_memory_*_phase_seconds`)는 event 백엔드 프로젝트에서만 나온다.** 프로젝트 생성 시 `backend` 기본값은 `None`이다. 이때 `vector_store`/`segment_store`를 주면 event로 추론되지만, 아무것도 안 주면 **서버 설정을 따라간다** — 옛 설정이면 **declarative(Neo4j)** 가 되고 구간 지표가 하나도 안 생긴다 → **MVP 2단계에서 `backend: "event"`를 명시할 것.**

---

## MVP 0단계 — 지표가 나오는지부터 (5분)

```bash
curl -s localhost:8080/api/v2/metrics | head -20
```

> ⚠ 경로는 **`/api/v2/metrics`** 다. `/metrics`가 아니다 (`router.py:1107`에서 prefix `/api/v2`가 붙는다).

여기서 텍스트가 나오면 나머지는 배선일 뿐이다. 안 나오면 §MVP-트러블슈팅.

**단일 워커로 시작할 것.** `MEMMACHINE_WORKERS`를 설정하지 않으면 기본 1이고, MVP에서는 그게 맞다 (멀티워커는 §심화-1의 함정이 있다).

---

## MVP 1단계 — Prometheus + Grafana 2개만 띄운다 (15분)

`obs/` 디렉터리를 만들고 파일 2개.

**`obs/prometheus.yml`**
```yaml
global:
  scrape_interval: 5s          # MVP라 짧게. 운영은 15s
scrape_configs:
  - job_name: memmachine
    metrics_path: /api/v2/metrics
    static_configs:
      - targets: ['host.docker.internal:8080']   # Linux면 아래 주석 참고
```
> Linux에서 호스트의 8080에 붙으려면 `host.docker.internal` 대신
> compose에 `extra_hosts: ["host.docker.internal:host-gateway"]`를 넣거나,
> MemMachine도 같은 compose 네트워크에 넣고 서비스명으로 지정한다.

**`obs/docker-compose.yml`**
```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    extra_hosts: ["host.docker.internal:host-gateway"]

  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin      # MVP 편의. 운영에선 끌 것
    depends_on: [prometheus]
```

```bash
cd obs && docker compose up -d
```

- Prometheus `localhost:9090` → **Status → Targets** 에서 `memmachine` 이 **UP** 인지 확인
- Grafana `localhost:3000` → Connections → Data sources → Prometheus 추가, URL `http://prometheus:9090`

---

## MVP 2단계 — event 백엔드 프로젝트로 트래픽을 넣는다 (10분)

지표는 **호출이 있어야 생긴다.** 아무 요청도 없으면 그라파나가 비어 있는 게 정상이다.

**프로젝트는 event 백엔드로 만든다** (위 핵심 사실 2):

```json
POST /api/v2/projects
{
  "org_id": "...", "project_id": "...",
  "config": {
    "backend": "event",
    "vector_store": "<서버 설정의 VectorStore 리소스 id>",
    "segment_store": "<서버 설정의 SQL 엔진 리소스 id>",
    "embedder": "<임베더 리소스 id>"
  }
}
```

- `backend: "event"`면 `vector_store`와 `segment_store`가 **둘 다 필요**하다 (`memmachine_common/api/spec.py` `ProjectConfig`).
- 리소스 id는 지어내지 말고 **서버 설정 파일의 `resources` 항목에 있는 이름**을 그대로 쓴다.

그다음:

```
POST /api/v2/memories              적재 몇 건
POST /api/v2/memories/search       검색 몇 건
```

확인:

```bash
curl -s localhost:8080/api/v2/metrics | grep event_memory_encode_events_phase_seconds | head
curl -s localhost:8080/api/v2/metrics | grep event_memory_query_phase_seconds | head
```

---

## MVP 3단계 — 패널 2개만 만든다 (10분)

대시보드를 정교하게 만들 필요 없다. **이 둘이면 MVP 완료**다.

**패널 1 — 적재 구간별 지연 (p95)**
```promql
histogram_quantile(0.95,
  sum by (le, phase) (rate(event_memory_encode_events_phase_seconds_bucket[1m])))
```

**패널 2 — 검색 구간별 지연 (p95)**
```promql
histogram_quantile(0.95,
  sum by (le, phase) (rate(event_memory_query_phase_seconds_bucket[1m])))
```

`phase` 로 시리즈가 갈라져 나오면 성공이다.
- 적재 = `segmentation` `derivation` `embedding` `segment_store` `vector_store` (5개)
- 검색 = `embedding` `vector_query` `segment_query` `scoring` (4개)

> 스택(Stacked) 표시로 두면 "총 지연 중 어느 구간이 먹는지"가 한눈에 보인다.

---

## MVP 완료 기준

| # | 확인 | 기대 |
|---|---|---|
| 1 | `curl /api/v2/metrics` 200 + 본문 | ✅ |
| 2 | Prometheus Targets 에서 `memmachine` **UP** | ✅ |
| 3 | event 백엔드 프로젝트에 적재 1회 후 `phase` **5종** 모두 존재 | ✅ |
| 4 | 검색 1회 후 `phase` **4종** 모두 존재 | ✅ |
| 5 | 그라파나 패널 2개에 시계열이 그려짐 | ✅ |

**여기까지가 1순위다. 되면 스크린샷 남기고 보고.**

---

## MVP 트러블슈팅

### 먼저 확인 — 구간 지표가 통째로 없다

| 증상 | 원인 | 대응 |
|---|---|---|
| `event_memory_*` 지표가 하나도 없는데 `vector_graph_store_neo4j_latency_seconds`는 있다 | 프로젝트가 **declarative 백엔드** (`backend`·`vector_store`·`segment_store`를 안 줘서 서버 설정의 declarative를 따라감) | 프로젝트를 `backend: "event"` + `vector_store` + `segment_store`로 다시 만든다 |
| MemMachine 지표가 **전부** 없다 | `metrics_factory_id`를 설정에서 덮어썼을 수 있음 | 기본값 `"prometheus"` (`episodic_config.py:389`) |

### 값이 작거나 이상한데 정상인 경우

| 증상 | 이유 | 확인/대응 |
|---|---|---|
| `segmentation` 이 0에 가까움 | event 백엔드 기본 세그먼터가 **passthrough**(자르지 않음) | 정상. 분할은 `segmenter: type: text` 설정 시에만 |
| `derivation` 이 0에 가까움 | 기본 deriver가 문자열 포맷팅만 함 | 정상 |
| `scoring` 이 0에 가까움 | event 백엔드 리랭커 기본값이 **없음(None)** — 코사인 점수 정리만 측정됨 | 정상. 리랭커를 설정하면 값이 커짐 |
| `segment_query` 가 작다 | `expand_context` **기본값 0** — 앞뒤 문맥 walk는 안 일어남. 단 이 구간엔 derivative→segment 매핑 조회와 seed 조회가 항상 들어 있어 **0은 아니다** | walk 비용을 보려면 검색 요청에 `expand_context: 3` |

### 진짜 문제

| 증상 | 원인 |
|---|---|
| Targets 가 DOWN | 네트워크. `host.docker.internal` / `extra_hosts` / 방화벽 |
| 404 | 경로를 `/metrics` 로 썼다. `/api/v2/metrics` 가 맞다 |
| 값이 들쭉날쭉·리셋됨 | 멀티워커인데 `PROMETHEUS_MULTIPROC_DIR` 미설정 (§심화-1) |

---
---

# 이후 작업 (MVP 완료 후)

## 심화-1. 멀티워커

```bash
export MEMMACHINE_WORKERS=4                  # app.py:139
export PROMETHEUS_MULTIPROC_DIR=/tmp/mmprom  # 반드시 함께
mkdir -p $PROMETHEUS_MULTIPROC_DIR
```

**둘은 세트다.** 워커마다 별도 레지스트리를 갖기 때문에, 디렉터리를 안 잡으면 스크레이프마다 **다른 워커가 응답**해 카운터가 리셋된 것처럼 보이고 rate·histogram이 전부 틀어진다 (`router.py:1082-1086` 주석에 명시).

## 심화-2. 외부 시스템 exporter 추가

**이게 실은 제일 중요한 부분이다.** 우리 가설이 *"부하는 외부(PostgreSQL·벡터DB)에 걸린다"* 이므로 앱 지표만으로는 검증이 안 된다.

- `postgres_exporter` (9187) — `pg_stat_activity` · `pg_locks` · 커넥션 수
- Qdrant — `/metrics` 기본 제공 (6333). **Qdrant 인덱스 빌드는 비동기라 앱 지표로는 안 보인다** — 여기서 봐야 한다

앱 지표와 **같은 시간축**에 올려야 "앱에서 느려진 그 순간 DB에 무슨 일이 있었나"가 맞춰진다.

## 심화-3. 나머지 패널

**컴포넌트 지연** — 전부 `{prefix}_latency_seconds{operation, status}` 형식이다 (`operation_tracker.py:31-35`).

| 지표 | 어디서 | 비고 |
|---|---|---|
| `event_memory_latency_seconds` | operation = `encode_events` · `query` · `forget_events` | 구간 지표를 감싸는 바깥 구간 |
| `episode_store_sqlalchemy_latency_seconds` | `add_episodes` · `get_episodes` 등 | 원문 저장·복원 |
| `segment_store_sqlalchemy_latency_seconds` | `add_segments` · `get_segment_contexts` · `open_or_create_partition` 등 | |
| `vector_store_qdrant_latency_seconds` / `vector_store_milvus_latency_seconds` | `upsert` · `query` · `create_collection` 등 | |
| `session_store_sqlalchemy_latency_seconds` | `get_session_info` 등 | 세션 캐시 miss 때만 |
| `embedder_openai_latency_seconds` | `ingest_embed` · `search_embed` | **OpenAI 임베더만.** Bedrock·SentenceTransformer는 없음 |
| `language_model_<provider>_latency_seconds` | `generate_parsed_response` 등 | provider = `openai_responses` · `openai_chat_completions` · `amazon_bedrock` · `litellm` |
| `reranker_amazon_bedrock_latency_seconds` | `score` | **Bedrock 리랭커만.** 나머지 리랭커는 없음 |
| `vector_graph_store_neo4j_latency_seconds` | | declarative 백엔드일 때 |

**요청 전체 단위** (단계 분리 불가):
- `http_request_duration_seconds{method, path, status}` — `server/middleware.py:61`
- `query_latency` / `Ingestion_latency` (Summary, 단위 ms) + `query_count` / `Ingestion_count` — `episodic_memory.py:132-145`

**그 밖에**: 토큰 Counter (임베딩·LLM) · 에러율(`status="error"`) · 처리량(`rate(..._count[1m])`)

## 심화-4. 대시보드 JSON export (재현 가능하게)

---
---

# 부록 A. 배경 — 왜 이걸 하는가

다중 사용자 환경에서 MemMachine과 하위 DB를 평가하려 한다. 코드를 읽어 확인한 결론:

> **MemMachine은 조율(orchestration) 계층이고, 무거운 연산은 전부 외부에 있다.**
> 임베딩(API) · 인덱스 구축/ANN 탐색(Qdrant·Milvus) · 원문/문맥 I/O(PostgreSQL) · LLM.
> 따라서 사용자가 늘 때 **부하는 외부 시스템에 걸릴 것으로 예상**된다.

upstream `speedkick` 은 실서비스 규모 산정 도구(`tools/sizing`)와 부하 테스트 중 발견한 버그 수정이 올라간 브랜치다. 병목이 실제로 외부(PostgreSQL)에서 관측된 사례가 있다 — `#1546`:

- **현상**: 파티션 316개인 세그먼트 스토어에서, 캐시된 generic plan이 실행마다 **모든 자식 파티션에 락**을 걸었다. 락 테이블이 고갈되며 HTTP 500(`out of shared memory`)이 나고, PostgreSQL은 CPU 상한에 고정됐다.
- **중간 수정**: 자식 테이블을 직접 지정하는 DML로 바꾸자 락 수 1276 → 4, 128 동시 요청 처리량이 약 +20~30% 올랐다. 다만 FK 트리거 락 급증과 deadlock은 남았다.
- **최종**: 같은 PR `#1548`(`7752e4c`)이 파티션 구조 자체를 없애고 **공유 테이블 + incarnation 키**로 교체했다. `acb4f9a`에는 자식 테이블 코드가 없다.

> 즉 "+20~30%"는 **중간 수정의 측정치**이고, 지금 코드의 성능 수치가 아니다. 근거는 `7752e4c` 커밋 본문과 `design/segment_store_shared_tables.md`.

# 부록 B. 이 계측으로 되는 것 / 안 되는 것

**된다**: 단일 요청을 따라가며 **어느 구간이 느린지**. 구간이 이미 잘려 있다(적재 5 / 검색 4, event 백엔드).

**안 된다**: 다수 요청이 몰릴 때 **왜 느린지**. 지금 지표는 전부 **지연 히스토그램**이라 지연 안에 섞인 *대기 시간*과 *처리 시간*이 구분되지 않는다.
`MetricsFactory` 에 `Gauge` 가 정의만 되어 있고 **사용처가 0건**이라, 동시 실행 수 · 락 대기 · 커넥션 풀 상태 · LRU 캐시 hit/miss 가 안 보인다.

단계별로 무엇이 이미 측정되고 무엇이 없는지는 `docs/msr/memmachine_workload.pptx` 2장에 정리했다.

→ 이건 **이번 범위가 아니다.** 별도 과제(계측 추가 + 부하 드라이버)로 다룬다. 이번 작업에서 코드를 고치지 말 것.

# 부록 C. 근거 위치 (`acb4f9a`)

| 내용 | 파일 · 라인 |
|---|---|
| metrics 엔드포인트 | `server/api_v2/router.py:1064, 1080` (prefix `:1107`) |
| 멀티워커 주의 주석 | 〃 `:1082-1086` |
| 구간 타이머 정의 (`phase_durations`) | `episodic_memory/event_memory/event_memory.py:293`(적재) `:502`(검색) |
| 구간 히스토그램 등록 | 〃 `:166-175` |
| 컴포넌트 지연 래퍼 | `common/metrics_factory/operation_tracker.py:37` · `timed.py:32` |
| metrics factory 기본값 `"prometheus"` | `common/configuration/episodic_config.py:389` |
| 백엔드 추론 (`vector_store`/`segment_store` 있으면 event, 없으면 declarative) | 〃 `:320-342` |
| 프로젝트 `backend` 필드 (기본 `None`) | `packages/common/src/memmachine_common/api/spec.py` `ProjectConfig` |
| 프로젝트 config → LTM 설정 | `server/api_v2/router.py:105` `_ltm_partial_from_project_config` |
| 워커 수 `MEMMACHINE_WORKERS` | `server/app.py:131-142` |
| HTTP 요청 지연 히스토그램 | `server/middleware.py:61` |
| 규모 산정 도구(참고) | `tools/sizing/README.md` |

전체 구조 분석: `docs/msr/memmachine_vectordb_full_guide.md`
작업 부하 · 계측 현황 · 코드 위치(장표 3장): `docs/msr/memmachine_workload.pptx`
