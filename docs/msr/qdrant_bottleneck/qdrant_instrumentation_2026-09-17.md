# Qdrant가 기본 제공하는 계측 수단

- 작성일: 2026-09-17
- 대상: **v1.19.1** (최신 안정판). v1.17과 다른 곳은 따로 표시했다
- 근거: `qdrant/qdrant` 소스를 v1.17.0과 v1.19.1 양쪽 태그에서 대조 확인
- 관련 문서: `design_2026-09-17.md` 3부(측정 방법)

이 문서는 설계 문서 3부에서 쓰는 계측 수단을 하나씩 풀어 쓴 참고 자료다.

---

## 1. 한눈 요약

### 얻을 수 있는 것

| 얻는 것 | 수단 | 버전 |
|---|---|---|
| 검색이 **어느 경로로 처리됐는지**와 경로별 누적 시간 | `/telemetry?details_level=4` | v1.17+ |
| 요청 단위 지연 분포 (p50/p95/p99) | `/metrics` 의 히스토그램 | v1.17+ |
| 느린 요청을 **개별로** 식별 (요청 본문 포함) | `/profiler/slow_requests` | v1.16+ |
| **옵티마이저 작업의 단계별 소요 시간** | `/collections/{c}/optimizations` | v1.17+ |
| 저장 대기열이 밀린 정도 | `/collections/{c}` 의 `update_queue` | v1.17+ |
| 워킹셋이 RAM에 안 들어가는지 | `/collections/{c}/memory` | **v1.18+** |
| 디스크 접근 발생 여부 | `process_major_page_faults_total` | v1.16+ (Linux) |
| CPU를 어느 함수가 쓰는지 | `PATCH /debugger` → Pyroscope | CPU v1.17+, 힙 v1.18+ |

### 얻을 수 없는 것 — 중요

**검색과 저장 모두 내부 단계별 시간을 주지 않는다.**

```
검색:  필터 평가 / 그래프 순회 / 스코어링 / 병합
저장:  WAL 기록 / 벡터 저장 / payload 저장 / payload 인덱스 갱신
       ↑ 이 각각을 재는 타이머가 Qdrant 안에 없다
```

가장 세밀한 분해는 검색의 **경로 9칸**까지이고, 그 칸 안의 시간은 더 쪼개지지 않는다.

**그래서 소스에 계측 코드를 넣어 직접 얻기로 했다.** 어느 함수의 어느 줄에 넣을지는 v1.19.1 소스에서 이미 특정했다(검색 9개소, 저장 9개소). 목록과 근거 코드는 `stage_isolation_2026-09-18.md` 에 있다.

**분산 추적(OpenTelemetry / OTLP / Jaeger)을 지원하지 않는다.** v1.17.0과 v1.19.1 양쪽 `Cargo.lock`에 `opentelemetry` 문자열이 0회다. `src/tracing/`는 분산 추적이 아니라 로그 포맷·필터 모듈이다. `--features tracing`으로 빌드해도 계측 span이 0개인데, `docs/DEVELOPMENT.md`가 그 이유를 명시한다 — *"Qdrant code is **not** instrumented by default, so you'll have to manually add `#[tracing::instrument]`."*

**예외가 하나 있다.** 옵티마이저 작업만큼은 단계별 시간을 준다(4장). 우리 구성에서 저장의 무거운 일이 대부분 거기 있으므로 실질적 손실은 생각보다 작다.

---

## 2. `/telemetry` — 검색이 어느 방식으로 처리됐는지 아는 유일한 출처

### 2.1 무엇을 주는가

`details_level`은 0~4이고, **세그먼트 단위 통계는 Level4에서만 나온다.** (`From<usize>`가 `_ => Level4`이므로 5 이상은 4와 같다.)

```
GET /telemetry?details_level=4

.result.collections.collections[].shards[].local.segments[].vector_index_searches[]
    .unfiltered_plain            필터 없음 · 전수 스캔
    .unfiltered_hnsw             필터 없음 · 그래프 탐색
    .unfiltered_exact            필터 없음 · 정확 검색
    .unfiltered_sparse           필터 없음 · 희소 벡터
    .filtered_plain              필터 있음 · 전수 스캔
    .filtered_small_cardinality  필터 있음 · 통과 예상이 적어 전수 스캔
    .filtered_large_cardinality  필터 있음 · 통과 예상이 많아 그래프 탐색
    .filtered_exact              필터 있음 · 정확 검색
    .filtered_sparse             필터 있음 · 희소 벡터
```

각 칸은 `OperationDurationStatistics`이고 필드는 이렇다.

| 필드 | 의미 |
|---|---|
| `count` | 이 경로를 탄 횟수 (누적) |
| `total_duration_micros` | 이 경로에 쓴 총 시간 (누적) |
| `avg_duration_micros` | 최근 128회의 이중 평활값. **누적 평균이 아니다** |
| `min_duration_micros`, `max_duration_micros` | 최소·최대 |
| `fail_count` | 실패 횟수 |
| `last_responded` | 마지막 응답 시각 |

**이 구조체는 v1.17.0과 v1.19.1이 완전히 동일하다.**

### 2.2 어떻게 쓰는가

`count`와 `total_duration_micros`가 **누적값**이므로, 부하 전후로 두 번 찍어 **차이를 뺀다.**

```bash
curl -s 'localhost:6333/telemetry?details_level=4' > before.json
# ... 부하 실행 ...
curl -s 'localhost:6333/telemetry?details_level=4' > after.json
```

경로별 추출 예시다.

```bash
jq '[.result.collections.collections[]
     | .shards[]? | .local? | .segments[]?
     | .vector_index_searches[]?
     | to_entries[] | select(.value.count? > 0)
     | {path: .key, count: .value.count, micros: .value.total_duration_micros}]' after.json
```

### 2.3 읽는 법

| 관찰 | 뜻 |
|---|---|
| `filtered_small_cardinality` 에 시간이 몰린다 | 세그먼트가 `full_scan_threshold` 아래여서 전수 스캔 중이다 |
| `filtered_large_cardinality` 에 몰린다 | 그래프 탐색 중이다 |
| 두 칸 사이를 오간다 | 데이터가 늘며 임계를 넘나드는 중이다 |
| `unfiltered_hnsw` 에 카운트가 잡힌다 | **경보.** 우리 구성은 항상 파티션 필터를 붙이므로 여기 잡히면 안 된다 |

### 2.4 한계

- **히스토그램을 주지 않는다.** `/telemetry` 핸들러가 `histograms: false`를 하드코딩하고, `duration_micros_histogram`에 `#[serde(skip)]`이 붙어 있다(*"openapi-generator-cli crashes on this field"*). 어떤 `details_level`로도 얻을 수 없다
- **백분위(percentile) 필드가 없다.** p99가 필요하면 `/metrics` 히스토그램을 써야 한다
- 카운터는 **재시작으로만 초기화된다**

---

## 3. `/metrics` — 요청 단위 지연

### 3.1 노출되는 지표

응답 관련(v1.17+).

| 지표 | 타입 |
|---|---|
| `rest_responses_total` | COUNTER |
| `rest_responses_avg_duration_seconds` | GAUGE |
| `rest_responses_min_duration_seconds` | GAUGE |
| `rest_responses_max_duration_seconds` | GAUGE |
| `rest_responses_duration_seconds` | **HISTOGRAM** |
| `grpc_responses_*` (같은 5종) | 동일 |

저장·옵티마이저 관련.

| 지표 | 타입 | 의미 |
|---|---|---|
| `collection_update_queue_length` | GAUGE | 저장 대기열에 밀린 연산 수 |
| `collection_update_queue_deferred_points` | GAUGE | 인덱싱 대기로 검색에서 숨겨진 포인트 수 |
| `collection_running_optimizations` | GAUGE | 실행 중인 최적화 작업 수 (v1.16+) |

디스크·메모리 관련(Linux).

| 지표 | 의미 |
|---|---|
| `process_major_page_faults_total` | **mmap 페이지 부재로 디스크를 읽은 횟수** |
| `process_minor_page_faults_total` | 페이지 캐시에는 있었던 경우 |
| `collection_hardware_metric_vector_io_read` / `_write` | 벡터 I/O 양 |
| `collection_hardware_metric_payload_io_read` / `_write` | payload I/O 양 |
| `collection_hardware_metric_payload_index_io_read` / `_write` | payload 인덱스 I/O 양 |

`collection_hardware_metric_*` 계열은 `service.hardware_reporting: true` 를 켜야 나온다. **시간이 아니라 I/O 양**이다.

### 3.2 히스토그램 버킷

고정값이다.

```
1ms · 5ms · 10ms · 20ms · 50ms · 100ms · 500ms · 1s · 5s · 10s · 50s
```

**최저 경계가 1ms**이므로 그 미만은 분해능이 없다. 우리 측정에서 평상시 검색이 2ms 안팎이라 버킷 두세 개 안에 몰린다는 뜻이다.

p99는 `histogram_quantile()`로 계산한다.

### 3.3 함정 네 가지

**① 스크레이프 자체가 무겁다.** `/metrics` 핸들러는 `DetailsLevel::Level4` + `histograms: true`를 하드코딩하므로 **매 스크레이프마다 전 세그먼트에 읽기 잠금**을 건다(`src/actix/api/service_api.rs`). 성능 측정에서 스크레이프 주기가 그대로 교란 변수가 된다. **주기를 고정하고 기록해야 한다.**

**② status 200만 타이밍이 잡힌다.** `REST_TIMINGS_FOR_STATUS = 200`이다. 실패한 요청의 지연은 히스토그램에 안 들어간다.

**③ 화이트리스트가 있다.** 아무 엔드포인트나 지표화되지 않는다. 다행히 우리가 쓰는 `/collections/{collection_name}/points/query/batch` 와 `/collections/{collection_name}/points` 는 포함되어 있다.

**④ `?per_collection=true` 는 추가가 아니라 치환이다.** (v1.18.0+) 켜면 레이블 없는 전역 지표가 아예 렌더링되지 않는다.

### 3.4 버전 간 파괴적 변경

| 변경 | 시점 |
|---|---|
| `rest_responses_fail_total` 삭제, `status` 레이블로 대체 | v1.17.0 |
| `endpoint` 레이블 템플릿 `{name}` → `{collection_name}` | v1.17.1 |
| `?per_collection=true` 추가 | v1.18.0 |

**공식 문서의 지표 표는 아직 `rest_responses_fail_total`을 싣고 있어 낡았다.** 문서보다 실제 엔드포인트를 믿어야 한다.

---

## 4. `/collections/{c}/optimizations` — 단계별 시간을 주는 유일한 곳

### 4.1 응답 구조

```
GET /collections/{c}/optimizations?with=queued,completed,idle_segments

{
  "summary": {
    "queued_optimizations": 정수,   대기 중인 최적화 작업 수
    "queued_segments":      정수,   최적화 대기 중인 세그먼트 수
    "queued_points":        정수,   그 세그먼트들의 포인트 수
    "idle_segments":        정수    최적화가 필요 없는 세그먼트 수
  },
  "running":       [ { "uuid", "optimizer", "status", "segments", "progress" } ],
  "queued":        [...],
  "completed":     [...],
  "idle_segments": [...]
}
```

`progress`는 `ProgressTree`이고 **재귀 구조**다.

| 필드 | 의미 |
|---|---|
| `name` | 단계 이름 |
| `started_at` / `finished_at` | 시작·종료 시각 |
| `duration_sec` | **그 단계에 실제로 쓴 시간(초)** |
| `done` / `total` | 진행률 |
| `children[]` | 하위 단계 |

### 4.2 우리 구성(`m=0`)에서 실제로 나오는 단계

```
Segment Optimizing
├── copy_data                 원본 세그먼트 데이터를 새 세그먼트로 복사   (디스크)
├── populate_vector_storages  벡터 파일을 미리 읽어 캐시에 올림           (디스크)
├── wait_cpu_permit           I/O 허가를 CPU 허가로 교체하며 대기
└── additional_links          payload 필드별 그래프 링크 생성            (CPU)
    └── "keyword:sys-partition_key"
```

`m > 0`이면 여기에 `migrate`와 `main_graph`가 더 붙는다. **`m=0`이라 둘 다 생성되지 않는다.**

### 4.3 `populate_vector_storages`가 채우는 캐시

소스 확인 결과 이렇다. `populate_vector_storages()` → 각 벡터 저장소의 `populate()` → 백엔드별 구현.

```rust
// lib/common/common/src/universal_io/traits/read.rs
/// Fill RAM cache with related data, if applicable for this implementation.
/// For example in MMAP-based files we do `madvise` with `MADV_POPULATE_READ`.
fn populate(&self) -> UioResult<()>;
```

| 백엔드 | 채우는 대상 |
|---|---|
| **mmap** | **OS 페이지 캐시.** `madvise(MADV_POPULATE_READ)` 로 커널에 미리 읽게 한다 |
| **disk_cache** | **Qdrant 자체 캐시.** 16KiB 블록 단위 사용자 공간 캐시 계층 |

`LowMemoryMode::NoPopulate` 로 띄우면 이 예열을 건너뛴다(`skip_populate()`).

**메모리 한도 실험에서 이 단계가 직접 영향을 받는다.** 한도가 낮으면 예열한 페이지가 곧바로 회수되어 이 단계의 효과가 사라지고, 뒤이은 `additional_links` 가 느려진다.

---

## 5. `/profiler/slow_requests` — 개별 느린 요청

```
GET /profiler/slow_requests?limit=10&request=<부분문자열>
```

- v1.16.0+, **임계값 50ms 하드코딩**(변경 불가)
- 요청 종류별 32건 유지, 등장 횟수는 `CountMinSketch64`로 근사
- 응답 필드: `duration`, `request_name`, `approx_count`, **`cpu_usage_ratio`**, **`request_body` 전문**
- `request_body`는 벡터 값과 payload 값이 제거된 형태로 남는다
- `manage` 전역 권한 필요, **OpenAPI 미등재**, 메모리 상주, 비활성화 불가
- 전송 큐(용량 64)가 넘치면 **조용히 드롭**된다. 폭주 구간에서는 누락이 생긴다

**`cpu_usage_ratio` 가 특히 유용하다.** 그 요청이 CPU를 쓰다 느렸는지 I/O를 기다리다 느렸는지 구분해 준다.

### 저장 요청의 경우

`request_name`이 `"points-update"`다. 여기 기록되는 `duration`의 성질을 정확히 알아야 한다.

| | |
|---|---|
| **포함** | 락 획득, 세그먼트 적용, 벡터 저장, payload 저장, payload 인덱스 갱신 |
| **제외** | HTTP 파싱, **대기열 대기 시간**, **WAL 기록과 WAL 확정(flush)**, 응답 직렬화 |

**WAL 확정이 제외라는 점에 주의해야 한다.** `update_worker.rs` 에서 `wal.blocking_lock().flush()` 가 `let start_time = Instant::now()` 보다 **앞에** 있다. 즉 `wait=true` 로 요청마다 치르는 디스크 확정 비용이 이 `duration` 에 들어오지 않는다. **앞선 정리에서 "포함"으로 적었던 것을 v1.19.1 소스 확인으로 바로잡았다.**

`/telemetry` 의 REST 응답 시간(= HTTP 전체)과 이 값의 차이가 **"대기열 대기 + WAL 기록 + WAL 확정 + HTTP 처리"** 의 근사치다. 넷이 뭉쳐 있어 이 창구만으로는 분해되지 않고, 50ms 초과분만 모은 집계라 정밀하지도 않다. **분해하려면 계측을 넣어야 한다**(`stage_isolation_2026-09-18.md` 의 W0~W3).

---

## 6. `/collections/{c}/memory` — 워킹셋 판정 (v1.18+)

컴포넌트별로 이 넷을 준다.

| 필드 | 의미 |
|---|---|
| `disk_bytes` | 디스크에 있는 크기 |
| `ram_bytes` | RAM에 올라간 크기 |
| `cached_bytes` | 실제로 캐시된 크기 |
| `expected_cache_bytes` | 캐시되어 있어야 할 크기 |

**`expected_cache_bytes` 대비 `cached_bytes` 의 격차가 "워킹셋이 RAM에 안 들어감"의 판정 근거다.** `mincore(2)` 기반이며 RAM은 10~15% 과소 추정된다.

**v1.17에는 이 엔드포인트가 없다.** 라우트와 `memory_reporter.rs` 모두 부재를 확인했다.

---

## 7. 프로파일링과 로그

### 7.1 Pyroscope — 재빌드 없이 쓸 수 있는 유일한 프로파일러

```bash
curl -X PATCH localhost:6333/debugger -H 'Content-Type: application/json' \
  -d '{"pyroscope":{"url":"http://localhost:4040","identifier":"qdrant-local"}}'
```

Linux 전용, `manage` 권한 필요. `GET`/`PATCH /debugger` 둘 다 v1.17.0에도 있다.

힙 프로파일링은 `tikv-jemallocator`의 `profiling` feature가 v1.17.0에 없어 **v1.18.0부터** 동작하며 `MALLOC_CONF="prof:true,prof_active:true"` 가 필요하다.

**`/debug/pprof/*` 같은 pprof 엔드포인트는 없다.** `GET /stacktrace` 는 공식 Docker 이미지가 `--features=stacktrace` 로 빌드되어 바로 쓸 수 있다.

### 7.2 로그

```
QDRANT__LOGGER__LOG_LEVEL=debug
```

- **`RUST_LOG` 은 읽지 않는다.** 설정 문자열만 파싱한다
- 억제 필터가 상시 선주입된다: `hyper=INFO, h2=ERROR, tower=WARN, rustls=INFO, wal=WARN, raft=WARN`
- 재시작 없이 바꾸려면 `GET`/`POST /logger`
- **단계별 타이밍은 로그로 얻을 수 없다.** 계측 span이 없기 때문이다

### 7.3 빌드 타임 opt-in

`tracy`, `console`(tokio-console, `--cfg tokio_unstable` 필요), `dial9`(v1.19.0+, Tokio 런타임 텔레메트리). **공식 Docker 이미지는 `--features=stacktrace` 하나만 켜서 빌드되므로 전부 커스텀 빌드가 필요하다.**

---

## 8. 우리 실험에서 무엇을 쓰는가

설계 문서 3부의 측정 대상을 이 문서의 수단에 대응시킨 것이다.

| 측정 대상 | 수단 | 방식 |
|---|---|---|
| 검색 처리량·지연 | 부하 생성기 자체 기록 | 가장 신뢰할 수 있다 |
| 검색 p99 | `/metrics` 히스토그램 | `histogram_quantile()` |
| 검색 방식별 처리 시간 | `/telemetry?details_level=4` | **두 스냅샷 차이** |
| 정확도(리콜) | 같은 질의를 `exact: true` 로 재실행 | Qdrant가 정답을 만들어 준다 |
| 저장 대기열 포화 | `/collections/{c}` 의 `update_queue.length` | v1.19 상한 200 |
| 옵티마이저 밀림 | `/collections/{c}/optimizations` 의 `summary` | 추세로 본다 |
| 옵티마이저 단계별 시간 | 같은 창구의 `duration_sec` | |
| **검색 내부 단계별 시간** | **소스 계측** | 기본 기능 아님. `stage_isolation_2026-09-18.md` 3장 |
| **저장 내부 단계별 시간** | **소스 계측** | 기본 기능 아님. 같은 문서 4장 |
| 느린 요청 개별 | `/profiler/slow_requests` | 50ms 초과만 |
| 메모리 부족 | `/collections/{c}/memory` | `expected` 대 `cached` |
| 디스크 접근 | `process_major_page_faults_total` + `*_io_read` | 두 스냅샷 차이 |
| CPU를 어느 함수가 쓰는지 | `PATCH /debugger` → Pyroscope | 필요할 때만 |

### 측정 위생 두 가지

**모든 누적값은 두 번 찍어 뺀다.** 재시작으로만 초기화되므로 절대값은 의미가 없다.

**스크레이프 주기를 고정하고 기록한다.** `/metrics` 읽기가 전 세그먼트에 읽기 잠금을 걸어 그 자체가 부하다.

---

## 9. 확인하지 못한 것

| 항목 | 확인 방법 |
|---|---|
| `/telemetry` 실물 JSON의 정확한 필드 경로 | 구조체 정의에서 유도했다. `serde`의 `skip_serializing_if` 때문에 값이 없으면 필드 자체가 빠진다. 실제 인스턴스에 `GET /telemetry?details_level=5` 로 대조해야 한다 |
| WAL flush의 정확한 syscall (`msync` vs `fsync`) | `lib/wal/src/mmap_view_sync.rs` 를 읽거나 `strace -f -e trace=msync,fsync,fdatasync` |
| 컨테이너에서 `perf` 부착에 필요한 capability | Qdrant 문서·소스에 근거 전무. 직접 실험 필요 |
| `QDRANT__STORAGE__MMAP_ADVICE` 의 성능 영향 | 소스에 실재하나(기본 `random`) 문서화가 없다. 직접 A/B |
| 우리 벡터 차원에서의 `full_scan_threshold` 실제 경계 | `GET /collections/{c}` 의 `config.params.vectors.size` 확인 후 계산 |
