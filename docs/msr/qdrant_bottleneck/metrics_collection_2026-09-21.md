# 측정 중 무엇을 어떻게 모으는가 — 수집 계획

- 작성일: 2026-09-21
- 대상: Qdrant **v1.19.1** 계측 빌드, 컨테이너 CPU 16코어 고정, 메모리 한도 128 / 256 / 512GB
- 위치: 설계서 4.6절 작업 순서의 **1단계 Qdrant Docker 환경 준비** 가운데 **1.5 수집기**다. 환경 구축의 나머지(1.2, 1.4, 1.5 의 조건 전환 스크립트와 잡음 제거와 코어 예약)는 `environment_setup_2026-09-21.md` 에 있다. 3단계 부하 도구, 그중 3.3 부하기가 무엇을 남겨야 하는지도 여기서 정한다. 옛 번호 체계(0~7번)는 폐기했으므로 이 문서의 단계 번호는 모두 새 구조의 것이다
- 동반 파일: `collect_metrics.py`(시계열 수집기), `snapshot.sh`(구간 경계 스냅샷). 이 문서와 같은 디렉터리에 있으며, 측정 서버의 작업 디렉터리로 복사한 뒤 `chmod +x snapshot.sh` 를 한 번 해 둔다. 이 문서의 명령은 두 파일이 현재 디렉터리에 있다고 보고 `./` 로 부른다

## 관련 문서

이 문서는 아래를 전제로 하며 같은 내용을 다시 적지 않는다.

| 문서 | 여기서 가져오는 것 |
|---|---|
| `design_2026-09-17.md` | 2부의 측정 항목 11개, 3.1절의 항목별 확보 수단, 3.3절의 측정 위생, 4.3절의 함정 |
| `qdrant_instrumentation_2026-09-17.md` | 각 창구의 응답 구조, 필드 의미, 버전별 차이, 함정 |
| `instrumented_build_2026-09-21.md` | `GET /stage_timings` 와 `POST /stage_timings/reset` 의 사용법과 출력 형식 |
| `stage_isolation_2026-09-18.md` | 계측 지점 18개소의 명세와 **8장의 해석 제약** |
| `cgroup_trap_check_2026-09-21.md` | 메모리 과금 함정의 실측 결과와 판정에 쓸 계수기 |
| `preparation_2026-09-21.md` | 경로 변수 `$RAW` 와 `$BENCH`(1.3, 5.4), 디스크 기준선(5.5), 조건 전환 절차(5.7) |

---

## 1. 요약

측정 항목 11개를 실제로 모으려면 **출처 네 갈래를 서로 다른 주기로 읽어야 한다.** 컨테이너 cgroup 계수기와 호스트 지표는 값이 싸므로 1초 주기로 계속 읽고, Qdrant의 가벼운 창구는 같은 주기로 읽으며, 전 세그먼트에 읽기 잠금을 거는 무거운 창구는 **구간 경계에서만** 한 번씩 읽는다. `/metrics` 읽기가 그 자체로 부하라는 점이 이 분리의 이유다.

11개 중 다섯 개가 **누적값**이다(항목 4, 5, 6, 9, 11. 4장의 표를 센 것이며 항목 10은 혼합이고 항목 8은 이벤트 목록이다). 누적값은 절대값에 의미가 없고 구간 차이만 의미가 있으므로, 구간이 시작하는 자리와 끝나는 자리에서 같은 창구를 두 번 찍어야 한다. 그래서 수집의 뼈대는 시계열이 아니라 **경계 스냅샷**이고, 시계열은 그 사이에서 값이 어떻게 움직였는지 보는 보조다.

조건 하나는 **컨테이너 생성, 적재, 부하, 폐기**의 네 구간으로 나뉜다. 컨테이너를 매번 새로 만들기 때문에 Qdrant 내부 누적값과 cgroup 계수기가 모두 0에서 시작하며, 이것이 초기화를 상당 부분 대신한다. 그러나 적재가 그 위에 값을 쌓으므로 **적재 종료 시점의 스냅샷이 반드시 필요하다.** 그 스냅샷 하나가 적재 구간의 결과이면서 동시에 부하 구간의 시작 기준이 된다.

값의 저장은 가공하지 않는 것을 원칙으로 한다. 응답 JSON과 cgroup 파일을 원본 그대로 조건별 디렉터리에 남기고, 파생 지표는 나중에 계산한다. 계산식을 고치는 일이 측정을 다시 하는 일보다 훨씬 자주 생기기 때문이다.

수집 자체가 측정을 흔들지 않게 하는 장치는 넷이다. 수집기를 Qdrant가 쓰는 16코어 밖에 고정하고, 수집 결과를 Qdrant 저장소와 다른 블록 장치에 쓰며, 무거운 창구를 부하 구간 안에서 읽지 않고, 수집기가 **데이터 파일을 절대 건드리지 않는다.** 마지막 항목은 설계서 4.3절 대책 3을 그대로 지키는 것이다.

---

## 2. 이 문서가 다루지 않는 것

**정확도(리콜)는 여기 없다.** 설계서 1.4절이 리콜을 병목 판정 축에서 분리했고 4.5.3절이 측정 구간까지 분리했다. 수집기는 리콜을 모으지 않으며, **부하 구간 안에 `exact: true` 질의가 한 건도 섞여서는 안 된다.** 섞이면 그 질의가 전수 스캔을 돌면서 `/telemetry` 의 `filtered_exact` 칸과 CPU 사용률을 동시에 오염시킨다.

부하 프로파일을 어떻게 설계할지, 동시 요청 수를 어떤 계단으로 올릴지도 여기서 정하지 않는다. 이 문서는 어떤 계단을 쓰든 **계단 하나가 하나의 구간이 된다**는 규칙만 정한다.

컨테이너를 어떻게 만들고 코어를 어떻게 고정하는지는 환경 구축 쪽의 몫이다. 이 문서는 그렇게 만들어진 컨테이너의 cgroup 경로를 받아서 쓴다.

---

## 3. 출처 네 갈래

| 갈래 | 창구 | 성질 |
|---|---|---|
| Qdrant 기본 기능 | `/telemetry`, `/metrics`, `/collections/{c}`, `/collections/{c}/optimizations`, `/collections/{c}/memory`, `/profiler/slow_requests` | HTTP. 일부는 전 세그먼트 잠금을 건다 |
| 계측 빌드 | `GET /stage_timings`, `POST /stage_timings/reset` | HTTP. 유일하게 초기화가 가능한 누적값 |
| 컨테이너 cgroup | `memory.current`, `memory.stat`, `memory.events`, `memory.pressure`, `io.stat`, `cpu.stat` | 호스트의 파일 읽기. Qdrant를 건드리지 않는다 |
| 호스트 지표 | `/proc/stat`, `/proc/meminfo`, `/proc/vmstat`, `/proc/diskstats`, `/proc/pressure/*` | 같음 |

**세 번째와 네 번째 갈래는 Qdrant에 아무 요청도 보내지 않는다.** 그래서 이 둘만 고빈도로 읽는다. 첫 번째 갈래는 창구마다 비용이 크게 다르므로 8장에서 따로 나눈다.

설계서 4.3절의 대책 3이 여기에도 걸린다. **수집기는 `$BENCH` 아래의 어떤 파일도 열지 않는다.** 수집기가 Qdrant 저장소 파일을 읽으면 그 페이지가 수집기 앞으로 과금되어, 컨테이너의 메모리 한도가 그만큼 헐거워진다. 디스크 사용량을 알고 싶으면 `du` 대신 cgroup의 `io.stat` 과 컬렉션 창구의 `disk_bytes` 를 쓴다.

---

## 4. 측정 항목 11개의 수집표

설계서 2부의 열한 개를 그대로 옮기고, 각각을 어느 창구에서 어떤 주기로 읽을지 붙였다.

### 4.1 ① 병목 조건을 판정하는 항목 — 2개

| # | 항목 | 창구 | 값의 성질 | 주기 |
|---|---|---|---|---|
| 1 | 초당 처리 건수 (QPS) | 부하 도구의 요청 로그 | 표본 | 요청마다 기록하고 사후에 1초 단위로 집계 |
| 2 | 요청별 지연 p50 / p95 / p99 | 같은 로그 | 표본 | 요청마다 기록. 도구 안에서 요약하지 않는다 |

**지연은 반드시 요청별 표본을 전부 남긴다.** 도구가 미리 백분위로 줄여 버리면 나중에 구간을 다시 자를 수 없고, 계단 경계에 걸친 요청을 어느 쪽으로 셀지도 정할 수 없다. 표본 수백만 건은 한 줄 한 요청으로 남겨도 수백 MB에 그치므로 용량이 문제가 되지 않는다.

**`/metrics` 의 히스토그램으로 p99를 구하지 않는다.** 버킷 최저 경계가 1ms인데 평상시 검색이 2ms 안팎이라 버킷 두세 개에 값이 몰린다(`qdrant_instrumentation_2026-09-17.md` 3.2절). 이 창구는 부하 도구의 값과 교차 확인하는 용도로만 경계에서 한 번씩 찍는다.

### 4.2 ② 병목 지점을 판정하는 항목 — 6개

| # | 항목 | 창구 | 값의 성질 | 주기 |
|---|---|---|---|---|
| 3 | 저장 요청 대기량 | `GET /collections/{c}` 의 `update_queue` | 순간값 | 1초 |
| 4 | 저장 내부 단계별 시간 | `GET /stage_timings` 의 W0~W8 | 누적값, 초기화 가능 | 구간 경계에서만 |
| 5 | 검색 방식별 처리 시간 | `GET /telemetry?details_level=4` 의 `vector_index_searches` 9칸 | 누적값, 초기화 불가 | 구간 경계에서만 |
| 6 | 검색 내부 단계별 시간 | `GET /stage_timings` 의 S0~S8 | 누적값, 초기화 가능 | 구간 경계에서만 |
| 7 | 정리 작업 대기량 | `GET /collections/{c}/optimizations` 의 `summary` | 순간값 | 5초 |
| 8 | 정리 작업 단계별 시간 | 같은 창구의 `completed[].progress` 의 `duration_sec` | 이벤트 목록 | 5초 |

**항목 3은 상한이 200이라는 것을 알고 봐야 한다.** v1.19에서 저장 대기열 기본 길이가 1,000,000에서 200으로 바뀌었으므로(설계서 0.6절), 200에 붙어 있는 시간의 비율이 곧 저장 포화의 직접 증거다. 순간값이라 놓치면 복구할 수 없으니 1초 주기로 계속 읽는다.

**항목 8은 이벤트 목록이라 놓치면 복구할 수 없다.** `completed` 배열의 보존 개수를 확인하지 못했으므로, 5초마다 통째로 받아 두고 사후에 `uuid` 로 중복을 제거해 합친다. 밀려나서 사라진 작업은 되찾을 방법이 없다.

**항목 4와 6은 같은 창구에서 한 번에 나온다.** `GET /stage_timings` 한 번이 저장 아홉 단계와 검색 아홉 단계를 모두 준다. 단 값이 전역 누적이므로 구간을 가르려면 경계에서 읽고 바로 초기화해야 한다.

### 4.3 ③ 병목 원인을 판정하는 항목 — 3개

| # | 항목 | 창구 | 값의 성질 | 주기 |
|---|---|---|---|---|
| 9 | CPU 사용률 (컨테이너 기준) | cgroup `cpu.stat` 의 `usage_usec`, 호스트 `/proc/stat` 의 코어별 줄 | 누적값 | 1초 |
| 10 | 메모리 적재 상태 | `GET /collections/{c}/memory` 의 `expected_cache_bytes` 대 `cached_bytes`, cgroup `memory.current` / `memory.stat` / `memory.events` / `memory.pressure` | 혼합 | HTTP는 경계에서만, cgroup은 1초 |
| 11 | 디스크 읽기 발생 | cgroup `io.stat` 의 `rbytes` 와 `rios`, `memory.stat` 의 `pgmajfault` 와 `workingset_refault_file`, `/metrics` 의 `collection_hardware_metric_*_io_read` | 누적값 | cgroup은 1초, `/metrics` 는 경계에서만 |

**항목 9에서 코어별 사용률이 총합보다 중요하다.** 저장은 샤드마다 업데이트 워커가 하나뿐이라 직렬화되므로, 코어 하나만 100%에 붙어 있고 나머지 열다섯이 노는 모습이 나오면 그것이 곧 직렬 구간이 병목이라는 직접 증거다. 총합만 보면 16코어 중 1코어이므로 6%로 보여 아무 일도 없는 것처럼 읽힌다.

**컨테이너를 `--cpuset-cpus` 로 묶었으므로 스로틀링 계수기는 쓸 수 없다.** `cpu.stat` 의 `nr_throttled` 와 `throttled_usec` 는 `cpu.max` 로 할당량을 준 경우에만 올라간다. 코어 고정만 한 구성에서는 CPU가 완전히 포화해도 이 값이 0으로 남으므로, **0이라는 이유로 "CPU에 여유가 있다"고 읽으면 안 된다.** 판정은 `usage_usec` 을 16코어로 정규화한 값으로 한다.

**항목 11의 판정에 읽기 소요 시간을 쓰지 않는다.** 2026-09-21 함정 검증에서 디스크를 읽은 조건이 32GiB를 4.2초에 읽어 초당 7.6GB가 나왔는데, 이 값은 디스크 속도가 아니라 단일 스레드 `dd` 의 메모리 복사가 병목이라는 뜻이다. 캐시에서 읽은 조건도 같은 복사를 해야 하므로 빨라질 여지가 없었고 실제로 근소하게 더 느렸다. 그래서 시간으로는 캐시 적중과 디스크 읽기를 구분할 수 없다(`cgroup_trap_check_2026-09-21.md` 6.1절). 판정은 `io.stat` 과 `memory.stat` 의 계수기로만 한다.

**항목 11의 `collection_hardware_metric_*` 계열은 켜야 나온다.** `service.hardware_reporting` 이 참이어야 하며, 꺼져 있으면 이 지표가 아예 렌더링되지 않는다. 이것이 벡터와 payload와 색인 중 무엇을 읽었는지 가르는 유일한 창구이므로, 켜졌는지 확인하는 절차를 7장의 점검표에 넣었다.

**항목 11의 보조 출처로 blktrace 를 둔다.** 계수기는 얼마나 읽었는지를 주지만 요청 하나하나의 크기와 위치와 장치 안에서의 소요 시간은 주지 않는다. `$BENCH` 장치에 블록 수준 I/O 추적을 걸면 그 장치가 Qdrant 저장소 전용이므로 그 장치의 I/O 가 곧 Qdrant 의 I/O 이고, 128GB 조건의 지연 꼬리가 4KiB 임의 읽기의 폭주인지 readahead 가 만든 큰 순차 읽기인지를 가를 수 있다. 다만 비용이 IOPS 에 비례해 커지므로 항상 켜지 않고, 5.1 예비 측정에서 비용을 잰 뒤 5.2 본 측정에서 켤 조건을 정한다. eBPF 계열(`biolatency`, `biosnoop`)이 비용이 낮은 대안이며 어느 쪽을 쓸지도 5.1 에서 정한다. 출력은 반드시 `$RAW` 아래 조건 디렉터리에 쓴다. `$BENCH` 에 쓰면 이 항목의 판정을 직접 오염시킨다. 켜고 끄는 명령과 파일 크기 계산은 환경 문서 6.7절에 있다. 이 문서의 수집기는 blktrace 를 띄우지 않으며, 켜고 끄는 주체는 새 구조 3.4 제어기다.

### 4.4 클라이언트 쪽 보조 항목 — 2개

| # | 항목 | 창구 | 값의 성질 | 주기 |
|---|---|---|---|---|
| 보조 1 | 요청별 응답 시간 | 부하 도구의 요청 로그 (항목 2와 같은 파일) | 표본 | 요청마다 |
| 보조 2 | 실패와 타임아웃 건수 | 같은 로그, 그리고 `/metrics` 의 `rest_responses_total` 의 `status` 레이블 | 표본과 누적값 | 요청마다, 경계에서 대조 |

**실패는 두 곳에서 세고 대조한다.** `/metrics` 는 상태 200인 요청만 타이밍 히스토그램에 넣으므로, 실패가 늘면 그쪽 지연 분포가 오히려 좋아 보이는 착시가 생긴다. 부하 도구가 센 실패 건수와 `rest_responses_total{status!="200"}` 의 구간 차가 같은 자릿수인지 확인해야 그 착시를 걸러낼 수 있다.

### 4.5 한 장으로 본 수집표

| 주기 | 읽는 것 | 왜 이 주기인가 |
|---|---|---|
| 요청마다 | 부하 도구 요청 로그 (항목 1, 2, 보조 1, 보조 2) | 백분위와 구간 재분할이 표본을 요구한다 |
| 1초 | cgroup `memory.*` / `io.stat` / `cpu.stat` / `*.pressure`, 호스트 `/proc/*`, `GET /collections/{c}` (항목 3, 9, 10 일부, 11 일부) | 순간값이라 놓치면 복구 불가. 읽기 비용이 Qdrant에 닿지 않는다 |
| 5초 | `GET /collections/{c}/optimizations` (항목 7, 8) | 정리 작업은 초에서 분 단위로 도는 일이라 5초면 충분하다 |
| 구간 경계 | `GET /stage_timings` 와 초기화 (항목 4, 6), `GET /telemetry?details_level=4` (항목 5), `GET /metrics` (항목 11 일부, 보조 2), `GET /collections/{c}/memory` (항목 10) | 전 세그먼트 잠금 또는 페이지 테이블 훑기. 부하 구간 안에서 읽으면 그 자체가 교란 변수가 된다 |

---

## 5. 누적값과 순간값

### 5.1 창구별 값의 성질

구간 차이를 내야 하는 값과 그대로 읽는 값을 섞으면 결과가 통째로 틀린다. 창구마다 다음과 같다.

| 창구와 필드 | 성질 | 초기화 수단 |
|---|---|---|
| `/stage_timings` 의 `count`, `total_nanos` | 누적 | `POST /stage_timings/reset` |
| `/telemetry` 9칸의 `count`, `total_duration_micros` | 누적 | 재시작뿐 |
| `/telemetry` 9칸의 `avg_duration_micros` | **최근 128회의 이중 평활값** | 해당 없음 |
| `/telemetry` 9칸의 `min`, `max` | 누적 극값 | 재시작뿐 |
| `/metrics` 의 `rest_responses_total`, `*_duration_seconds` 히스토그램 | 누적 | 재시작뿐 |
| `/metrics` 의 `rest_responses_avg/min/max_duration_seconds` | 게이지 | 해당 없음 |
| `/metrics` 의 `process_major_page_faults_total` | 누적 | 재시작뿐 |
| `/metrics` 의 `collection_hardware_metric_*_io_read` | 누적 | 재시작뿐 |
| `/metrics` 의 `collection_update_queue_length` | 게이지 | 해당 없음 |
| `/collections/{c}` 의 `update_queue` | 순간 | 해당 없음 |
| `/collections/{c}/optimizations` 의 `summary` | 순간 | 해당 없음 |
| `/collections/{c}/optimizations` 의 `completed[]` | 이벤트 목록 | 해당 없음 |
| `/collections/{c}/memory` 의 네 필드 | 순간 | 해당 없음 |
| `/profiler/slow_requests` | **근사 집계** | 해당 없음 |
| cgroup `memory.current` | 순간 | 해당 없음 |
| cgroup `memory.peak` | 누적 극값 | 커널이 지원하면 0을 써서 초기화 |
| cgroup `memory.stat` 의 `file`, `anon`, `file_mapped` | 순간 | 해당 없음 |
| cgroup `memory.stat` 의 `pgmajfault`, `workingset_refault_file`, `pgscan`, `pgsteal` | 누적 | 해당 없음 |
| cgroup `memory.events` 의 `max`, `oom` | 누적 | 해당 없음 |
| cgroup `io.stat` 의 `rbytes`, `rios`, `wbytes`, `wios` | 누적 | 해당 없음 |
| cgroup `cpu.stat` 의 `usage_usec` | 누적 | 해당 없음 |
| cgroup `*.pressure` 의 `total` | 누적 | 해당 없음 |
| cgroup `*.pressure` 의 `avg10`, `avg60`, `avg300` | 커널이 계산한 이동평균 | 해당 없음 |

**`memory.stat` 한 파일 안에 두 성질이 섞여 있다는 점이 가장 위험하다.** `file` 은 지금 이 순간 캐시에 올라 있는 바이트이고 `workingset_refault_file` 은 시작부터 누적된 횟수다. 파일을 통째로 차분하면 앞의 값이 음수가 되면서 의미를 잃는다. 수집기는 파일을 원본 그대로 남기므로, **차분은 사후 분석에서 필드 단위로 해야 한다.**

### 5.2 차분하면 안 되는 값 넷

| 값 | 이유 |
|---|---|
| `/telemetry` 의 `avg_duration_micros` | 누적 평균이 아니라 최근 128회의 이중 평활값이다. 두 스냅샷을 빼면 아무 의미 없는 수가 나온다. 구간 평균이 필요하면 `total_duration_micros` 의 차를 `count` 의 차로 나눈다 |
| `/profiler/slow_requests` 의 `approx_count` | `CountMinSketch64` 기반 근사이며 전송 큐가 넘치면 조용히 드롭된다. 폭주 구간에서 특히 빠진다. 개별 요청 본문을 보는 정성적 용도로만 쓴다 |
| `*.pressure` 의 `avg10` 계열 | 커널이 계산해 둔 이동평균이라 차분 대상이 아니다. 구간 정체 시간이 필요하면 `total` 의 차를 쓴다 |
| `memory.current`, `memory.stat` 의 `file` | 순간값이다. 구간 최대와 최소가 필요하면 1초 시계열에서 뽑는다 |

### 5.3 컨테이너 재생성이 초기화를 대신하는 부분

설계서 4.3절의 대책 1에 따라 조건을 바꿀 때마다 컨테이너를 새로 만든다. 그 결과 **다음이 모두 0에서 출발한다.**

- Qdrant 프로세스가 새로 뜨므로 `/telemetry` 의 9칸, `/metrics` 의 모든 누적 지표, `/profiler/slow_requests` 의 버퍼가 비어 있다
- cgroup이 새로 만들어지므로 `io.stat`, `cpu.stat`, `memory.events`, `memory.stat` 의 누적 필드가 0이다

**그러나 이것이 적재 구간의 값을 지워 주지는 않는다.** 적재는 컨테이너가 뜬 뒤에 일어나므로 부하가 시작될 때 이미 상당한 값이 쌓여 있다. 그래서 적재 종료 시점의 스냅샷이 반드시 필요하고, 그 스냅샷은 두 가지 일을 동시에 한다. 컨테이너 시작부터 그 시점까지의 값이 곧 **적재 구간의 결과**이고, 그 값이 곧 **부하 구간의 시작 기준**이다. 적재 구간 통계를 따로 얻으려고 추가로 할 일이 없다는 뜻이다.

---

## 6. 구간을 가르는 방법

### 6.1 조건 하나의 시간축

```
[준비]   캐시 비우기  →  컨테이너 생성  →  cgroup 경로와 장치 번호 확인
              │
              ├─ 시계열 수집기 시작 (여기서 끝까지 계속 돈다)
              │
         snap 00_start          컨테이너 직후. 모든 계수기가 0인지 확인하는 용도
              │
[적재]   데이터 적재  →  색인 완성 대기  →  정리 작업 소진 대기
              │
         snap 10_ingest_end     적재 구간의 결과이자 부하 구간의 기준. RESET=1
              │
[부하]   계단 1 (동시 요청 n1)
         snap 20_step_n1        RESET=1
         계단 2 (동시 요청 n2)
         snap 21_step_n2        RESET=1
              ...
              │
[꼬리]   부하 정지 후 정리 작업이 소진될 때까지 관찰
              │
         snap 90_tail_end       RESET=0
              │
         시계열 수집기 정지  →  컨테이너 폐기  →  결과 디렉터리 봉인
```

**경계 스냅샷은 부하를 멈춘 상태에서 찍는다.** 스냅샷이 `/telemetry` 와 `/metrics` 를 읽으면서 전 세그먼트에 읽기 잠금을 걸기 때문에, 부하가 도는 중에 찍으면 그 잠금이 바로 그 구간의 지연에 섞여 들어간다. 또 `GET /stage_timings` 와 `POST /stage_timings/reset` 사이에 도착한 요청은 어느 구간에도 들어가지 않으므로, 멈춘 상태여야 그 누락이 0이 된다.

**멈춤 구간의 길이를 고정하고 기록한다.** 멈춰 있는 동안 정리 작업이 진도를 나가고 캐시 상태가 변하므로 그 자체가 교란 변수이지만, 모든 조건에서 같은 길이로 멈추면 조건 간 비교는 성립한다. 기본값을 5초로 두고 `manifest.json` 에 적는다.

### 6.2 적재 완료 판정

적재가 끝났다는 것을 "요청을 다 보냈다"로 판정하면 안 된다. 저장 응답이 돌아온 뒤에도 옵티마이저가 뒤에서 세그먼트를 합치고 링크를 만드는 일이 한참 남아 있고(설계서 0.3절 ⑧), 그 작업이 도는 중에 부하를 걸면 부하 구간의 CPU와 디스크가 정리 작업의 것과 섞인다.

아래 네 조건이 **모두** 만족되고 그 상태가 연속 60초 유지될 때를 적재 완료로 본다. 60초는 옵티마이저가 잠깐 비었다가 다시 깨어나는 경우를 거르려고 정한 값이며, 실제 관측에 따라 조정하고 그 값을 `manifest.json` 에 적는다.

```bash
# 값을 읽기만 한다. 아무것도 바꾸지 않는다.
curl -s --max-time 30 "$QURL/collections/$COLL" | python3 -c '
import json,sys
d = json.load(sys.stdin)["result"]
print("status =", d.get("status"))
print("points_count =", d.get("points_count"))
print("indexed_vectors_count =", d.get("indexed_vectors_count"))
'
curl -s --max-time 30 "$QURL/collections/$COLL/optimizations?with=queued" | python3 -c '
import json,sys
s = json.load(sys.stdin)["result"]
print("summary =", s.get("summary"))
print("running =", len(s.get("running") or []))
'
```

| 판정 조건 | 합격 기준 |
|---|---|
| 컬렉션 상태 | `status` 가 `green` 이다. `yellow` 는 색인이 아직 도는 중이라는 뜻이다 |
| 색인 완성 | `indexed_vectors_count` 가 적재한 포인트 수와 같다 |
| 정리 작업 대기 | `summary.queued_optimizations` 와 `queued_segments` 가 모두 0이다 |
| 정리 작업 실행 | `running` 이 빈 배열이다 |

네 조건이 만족되지 않은 채로 부하에 들어가면 그 측정은 버린다. 조건이 오래 만족되지 않으면 그 사실 자체를 기록한다. 메모리 한도가 낮은 조건에서 정리 작업이 끝나지 않는 것은 결함이 아니라 관측 결과다.

### 6.3 경계 스냅샷

동반 파일 `snapshot.sh` 가 한 번의 호출로 모든 창구를 찍는다. 순서는 싼 것부터이며, `stage_timings` 를 읽은 직후에 초기화하고, 전 세그먼트 잠금을 거는 무거운 창구를 마지막에 둔다.

```bash
# 사전에 QURL, COLL, CG 를 export 해 둔다. 아래는 그 세 값을 확인만 한다.
echo "QURL=${QURL:-<비었음>} COLL=${COLL:-<비었음>} CG=${CG:-<비었음>}"
```

세 값이 모두 채워져 있으면 스냅샷을 찍는다. 첫 인자가 출력 디렉터리이고 둘째 인자가 스냅샷 이름이다.

```bash
if [ -z "${RUNDIR:-}" ]; then
  echo "RUNDIR 이 비어 있다. 9.1절의 export 줄로 돌아가 값을 설정한 뒤 다시 실행한다."
else
  SNAP_RESET=1 ./snapshot.sh "$RUNDIR/snap" 10_ingest_end
fi
```

**합격 기준.** `snapshot.sh` 가 경고를 한 줄도 내지 않고, `$RUNDIR/snap/10_ingest_end/` 아래에 `collection.json`, `optimizations.json`, `stage_timings.json`, `memory.json`, `telemetry.json`, `metrics.txt` 와 `cgroup/memory.current` 가 모두 비어 있지 않은 상태로 만들어져야 한다. `snapshot_meta.json` 의 `duration_sec` 이 그 스냅샷이 Qdrant를 붙잡고 있던 시간이며, 이 값이 멈춤 구간 길이보다 크면 멈춤 구간을 늘려야 한다.

### 6.4 계단식 부하에서의 경계

설계서 1.1절은 동시 요청 수를 1, 2, 4, 8, 16으로 올리며 포화점을 찾는다. **계단 하나가 구간 하나다.** 계단마다 경계 스냅샷을 찍고 `stage_timings` 를 초기화하면, 계단별 단계 시간과 계단별 검색 경로 분포를 따로 얻을 수 있다.

계단 전체를 합친 값이 필요하면 계단별 값을 더한다. 반대 방향은 불가능하다. 계단 전체를 한 구간으로 두고 나중에 쪼개는 일은 누적값의 성질상 할 수 없다. 그래서 **의심스러우면 더 잘게 자르는 쪽이 항상 옳다.**

`/telemetry` 는 초기화할 수 없으므로 계단마다 찍은 스냅샷을 이웃끼리 빼서 계단별 값을 만든다. `stage_timings` 는 초기화하므로 스냅샷에 담긴 값이 곧 직전 계단의 값이다. **두 창구의 차분 방식이 다르다는 점을 분석 코드에서 헷갈리면 안 된다.**

### 6.5 부하 종료 뒤의 꼬리 구간

부하를 멈추는 순간에 정리 작업이 밀려 있으면 그것이 결과다. 마지막 계단 스냅샷을 찍은 뒤 부하를 완전히 멈추고, 정리 작업이 소진될 때까지 시계열 수집기를 계속 돌린다. 소진 판정은 6.2절과 같다.

꼬리 구간에서 보는 것이 둘이다. 밀린 정리 작업이 **얼마나 걸려 소진되는가**와, 그동안 디스크 읽기와 CPU가 얼마나 드는가다. 메모리 한도가 낮은 조건에서 이 꼬리가 길어진다면, 그것은 `populate_vector_storages` 가 예열한 페이지가 곧바로 회수되어 `additional_links` 가 느려진 결과일 수 있다(`qdrant_instrumentation_2026-09-17.md` 4.3절).

### 6.6 적재 방식이 두 가지라는 점

준비 문서 5.7절은 조건마다 1억 개를 다시 적재하는 대신 **적재 직후 상태를 마스터로 떠 두고 조건마다 거기서 복사**하는 방식을 택했다. 수집 관점에서 두 방식의 차이는 하나뿐이다.

| 방식 | 적재 구간에서 얻는 것 |
|---|---|
| 재적재 | 저장 경로 W0~W8 이 대량으로 쌓인다. 적재 자체가 쓰기 부하 측정이 된다 |
| 마스터 복원 | Qdrant 안에서는 아무 일도 일어나지 않는다. W 단계가 전부 0이다 |

**마스터 복원 방식에서 W 단계가 0인 것은 정상이며 계측 실패가 아니다.** 쓰기 부하를 섞지 않은 검색 전용 조건에서는 부하 구간에서도 W 단계가 0으로 남는다.

**다만 마스터 복원 방식은 순서를 한 칸만 틀려도 설계서 4.3절의 함정이 그대로 재발한다.** 복사는 호스트가 하므로 복사한 페이지가 호스트 앞으로 과금되고, 그 상태에서 컨테이너를 띄우면 컨테이너는 자기 한도와 무관하게 그 캐시를 쓴다. 2026-09-21 실측이 정확히 그 모습이었다. 호스트가 먼저 읽은 조건에서 컨테이너의 디스크 읽기가 0, 한도 도달 횟수가 0회, `memory.current` 가 0.01GiB에 그쳤다. 따라서 **복사 다음에 반드시 캐시를 비우고, 그다음에 컨테이너를 만든다.** 준비 문서 5.7절의 블록이 이 순서를 지키고 있으며, 12장의 조건별 검사가 이 순서가 지켜졌는지를 매번 되짚는다.

---

## 7. 측정 시작 전 초기화 점검표

빠뜨리면 직전 조건이나 직전 구간의 값이 섞인다. 조건마다 위에서부터 훑는다.

| # | 초기화할 것 | 방법 | 빠뜨리면 |
|---|---|---|---|
| 1 | 시스템 페이지 캐시 | `sync; echo 3 > /proc/sys/vm/drop_caches` 를 **컨테이너 생성 직전에** | 직전 조건 또는 호스트 복사분이 그대로 남아 새 한도가 물리지 않는다 |
| 2 | Qdrant 내부 누적값 전체 | 컨테이너를 새로 만든다 | 한도만 바꾸는 방식은 금지다. 설계서 4.3절 |
| 3 | cgroup 계수기 | 같음. 컨테이너와 함께 cgroup이 새로 만들어진다 | 같음 |
| 4 | `stage_timings` | 적재 완료 직후와 계단마다 `POST /stage_timings/reset` | 적재 구간의 W 단계가 부하 구간에 섞인다 |
| 5 | 결과 디렉터리 | 조건마다 새 `$RUNDIR` 를 만든다. 기존 디렉터리에 덮어쓰지 않는다 | 계측기가 append 모드라 이전 실행과 뒤섞인다 |
| 6 | 부하 도구의 요청 로그 | 같음 | 같음 |
| 7 | 스왑 | 컨테이너에 `--memory-swap` 을 `--memory` 와 같게 준다 | 디스크 대신 스왑으로 빠져 항목 11이 통째로 오염된다 |

초기화가 **불가능한** 것이 하나 있다. `/profiler/slow_requests` 의 버퍼는 비우는 창구가 없고 비활성화도 안 된다. 컨테이너 재생성이 유일한 수단이며 이미 2번으로 충족된다.

아래는 조건을 시작하기 전에 한 번 확인하는 항목이다. 초기화가 아니라 전제다.

```bash
# 하드웨어 지표가 켜져 있는지. 이 지표가 벡터/payload/색인 중 무엇을 읽었는지 가른다.
curl -s --max-time 60 "$QURL/metrics" | grep -c '^collection_hardware_metric_'
```

0이 나오면 `service.hardware_reporting` 이 꺼져 있는 것이다. 이 경우 항목 11에서 "무엇을 읽었는가"를 얻지 못하고 "얼마나 읽었는가"만 남으므로, 컨테이너 설정을 고쳐 다시 만든다.

```bash
# 계측이 켜진 빌드인지. false 면 단계별 시간이 전부 비어 나온다.
curl -s --max-time 10 "$QURL/stage_timings" | python3 -c 'import json,sys; print("enabled =", json.load(sys.stdin).get("enabled"))'
```

`enabled = True` 여야 한다. `False` 면 계측을 끈 대조 이미지가 떠 있는 것이므로 `instrumented_build_2026-09-21.md` 5장으로 돌아간다.

---

## 8. 수집 주기

### 8.1 창구를 비용으로 나눈다

| 등급 | 창구 | 비용의 근거 |
|---|---|---|
| **거의 공짜** | cgroup 파일, `/proc/*` | 호스트의 파일 읽기다. Qdrant에 요청이 가지 않는다 |
| **가벼움(확인 필요)** | `GET /collections/{c}`, `GET /collections/{c}/optimizations` | 세그먼트 통계를 훑지 않는 것으로 보이나 직접 재지 않았다 |
| **무거움** | `GET /metrics` | 핸들러가 `DetailsLevel::Level4` 와 `histograms: true` 를 하드코딩해 **매 스크레이프마다 전 세그먼트에 읽기 잠금**을 건다 |
| **무거움** | `GET /telemetry?details_level=4` | 세그먼트 단위 통계를 모으므로 같은 성격이다 |
| **비용 미상** | `GET /collections/{c}/memory` | `mincore(2)` 기반이라 매핑된 영역의 페이지 테이블을 훑는다. 385GB 규모에서 얼마나 걸리는지 확인하지 못했다 |

**무거움 등급과 비용 미상 등급은 구간 경계에서만 읽는다.** 이것이 설계서 3.3절이 요구한 "지표를 읽어가는 주기를 고정하고 기록한다"를 지키는 가장 단순한 방법이다. 주기를 고정하는 대신 아예 부하 구간 밖으로 빼면, 고정된 주기가 조건마다 다른 영향을 주는 가능성 자체가 사라진다.

### 8.2 주기 기본값과 그 근거를 확정하는 측정

아래 값은 **정한 값이지 잰 값이 아니다.** 첫 조건을 돌리기 전에 아래 세 측정으로 근거를 만들고, 필요하면 고친 뒤 `manifest.json` 에 적는다.

| 대상 | 기본 주기 | 고를 때 본 것 |
|---|---|---|
| cgroup과 호스트 | 1초 | `memory.stat` 읽기가 cgroup 통계 플러시를 일으키므로 344코어 서버에서 더 짧게 하면 비용이 보일 수 있다 |
| `GET /collections/{c}` | 1초 | 대기열 길이가 순간값이라 놓치면 복구할 수 없다 |
| `GET /collections/{c}/optimizations` | 5초 | 정리 작업 하나가 초에서 분 단위로 돈다 |
| `GET /collections/{c}/memory` | 경계에서만 | 비용을 확인하지 못했다 |

첫 측정은 무거운 창구 하나하나가 실제로 얼마나 걸리는지 재는 것이다. 부하를 걸지 않은 적재 완료 상태에서 세 번씩 재고 값을 기록한다.

```bash
for ep in "/collections/$COLL" "/collections/$COLL/optimizations" "/collections/$COLL/memory" "/telemetry?details_level=4" "/metrics"; do
  for i in 1 2 3; do
    printf '%-46s ' "$ep"
    curl -s -o /dev/null -w '%{time_total}s  %{size_download} bytes\n' --max-time 300 "$QURL$ep"
  done
done
```

**합격 기준.** `/collections/{c}` 와 `/collections/{c}/optimizations` 가 1초 주기에 여유 있게 들어가야 한다. 목표는 한 번 읽기가 0.1초 미만이며, 넘으면 주기를 늘리거나 그 창구를 경계 전용으로 내린다. `/collections/{c}/memory` 와 `/telemetry` 와 `/metrics` 는 합격선을 두지 않고 **값을 기록하는 것 자체가 합격 조건**이다. 이 값이 6.1절의 멈춤 구간 길이를 정한다.

두 번째 측정은 cgroup 읽기 비용이다. 부하 없는 상태에서 수집기를 60초 돌리고 자기 자원 사용량을 보게 한다. `--cores` 에 넘기는 `$CPUSET` 은 환경 문서 3.1절에서 SSD 가 붙은 NUMA 노드 기준으로 정한 Qdrant 코어 열여섯 개다.

```bash
if [ -z "${RUNDIR:-}" ] || [ -z "${CG:-}" ] || [ -z "${CPUSET:-}" ]; then
  echo "RUNDIR 또는 CG 또는 CPUSET 이 비어 있다. 9.1절과 11.1절의 export 줄과 환경 문서 3.1절로 돌아간 뒤 다시 실행한다."
else
  python3 ./collect_metrics.py --cgroup "$CG" --collection "$COLL" \
    --out "$RUNDIR/probe" --cores "$CPUSET" &
  COLLECTOR_PID=$!
  sleep 65
  kill -TERM "$COLLECTOR_PID"
  wait "$COLLECTOR_PID" 2>/dev/null
  cat "$RUNDIR/probe/collector.log"
fi
```

**합격 기준.** `collector.log` 의 `late` 가 0이어야 한다. 0이 아니면 수집기가 주기를 못 지킨 것이므로 표본 간격이 균일하지 않다. 그리고 60초 동안의 `cpu_user` 와 `cpu_sys` 의 합이 1초 미만이어야 한다. 넘으면 수집 자체가 1.7% 이상의 코어를 상시 쓰고 있다는 뜻이므로 주기를 늘린다.

세 번째 측정은 10장에 있다. 수집기를 켠 경우와 끈 경우의 처리량 차이를 본다.

---

## 9. 저장 형식

### 9.1 디렉터리

조건 하나가 디렉터리 하나다. 조건을 다시 돌리면 새 디렉터리를 만들고 기존 것을 건드리지 않는다.

```bash
export RUN_ID="$(date +%Y%m%dT%H%M%S)_mem${MEMLIMIT:-unset}_${PROFILE:-unset}_r${REP:-1}"
if [ -z "${RAW:-}" ]; then
  echo "RAW 가 비어 있다. preparation 문서 1.3절의 export 줄로 돌아간 뒤 다시 실행한다."
else
  export RUNDIR="$RAW/results/$RUN_ID"
  mkdir -p "$RUNDIR/snap" "$RUNDIR/series" "$RUNDIR/load"
  echo "$RUNDIR"
fi
```

**결과는 `$RAW` 에 쓰고 `$BENCH` 에는 쓰지 않는다.** 준비 문서 5.3절이 두 경로를 서로 다른 블록 장치에 두었으므로, 이렇게 해야 수집기의 쓰기가 Qdrant 저장소가 있는 장치의 통계에 섞이지 않는다. 항목 11의 판정이 바로 그 장치의 읽기량을 보는 일이라 이 분리가 판정에 직접 걸린다.

디렉터리 안은 이렇게 생긴다.

```
$RAW/results/<RUN_ID>/
├── manifest.json              조건 메타. 9.2절
├── events.jsonl               구간 마커. 한 줄이 한 사건
├── snap/
│   ├── 00_start/              cgroup/, host/, *.json, metrics.txt, snapshot_meta.json
│   ├── 10_ingest_end/
│   ├── 20_step_1/ ... 2n_step_k/
│   └── 90_tail_end/
├── series/
│   ├── cgroup.jsonl           1초
│   ├── host.jsonl             1초
│   ├── qdrant.jsonl           1초
│   ├── optimizations.jsonl    5초
│   └── collector.log          수집기 자신의 비용
├── blktrace/                  켠 조건에서만. 환경 문서 6.7절
└── load/
    ├── requests.tsv           요청 한 건이 한 줄. 9.3절
    └── load_config.json       부하 도구에 넣은 파라미터 전부
```

**응답을 가공하지 않고 원본 그대로 남긴다.** JSON은 받은 그대로, cgroup 파일은 복사본으로 둔다. 파생 지표는 사후에 계산하며, 계산식을 고치는 일이 측정을 다시 하는 일보다 훨씬 자주 생긴다.

### 9.2 `manifest.json` 에 반드시 들어가야 할 것

조건을 비교하려면 무엇이 달랐는지 알아야 하고, 무엇이 같았는지도 알아야 한다. 아래가 빠지면 나중에 그 조건을 재현할 수 없다.

| 갈래 | 항목 |
|---|---|
| 이미지 | 태그와 **다이제스트**, `FEATURES` 인자, 계측 활성 여부 |
| 컨테이너 | `--cpuset-cpus`, `--memory`, `--memory-swap`, 볼륨 경로, cgroup 경로 |
| 컬렉션 | `m`, `payload_m`, `full_scan_threshold`, payload 인덱스 목록, `is_tenant` 여부, 벡터 차원과 거리 함수, 세그먼트 설정 |
| 데이터 | 데이터셋 이름과 출처, 포인트 수, 세션 수, 세션당 포인트 수 분포, 적재 방식(재적재인지 마스터 복원인지) |
| 부하 | 계단 목록, 계단별 동시 요청 수와 길이, 검색 대 저장 비율, `top_k`, 필터 통과 비율, 필터 조합, 저장 배치 크기, `wait` |
| MemMachine 기준 커밋 | 부하 도구가 재현한 요청 모양의 근거가 되는 MemMachine 브랜치와 커밋. 값 예시는 `speedkick 8d7b832` |
| 수집 | 이 문서에서 쓴 모든 주기, 멈춤 구간 길이, 적재 완료 판정의 유지 시간 |
| 환경 | 커널 버전, Docker 버전, `$BENCH` 의 파일시스템과 readahead, 스왑 상태, 준비 문서 5.5절의 디스크 기준선 네 값 |
| 절차 | `drop_caches` 를 언제 실행했는지, 컨테이너 생성 시각, 각 구간의 시작과 끝 |

**이미지 다이제스트를 태그 대신 적는 이유가 있다.** 같은 태그로 다시 빌드하면 내용이 달라지는데 태그만으로는 그것을 알 수 없다. 왜곡 검증에서 계측 이미지와 대조 이미지를 비교할 때 특히 중요하다.

### 9.3 부하 도구가 남겨야 할 요청 로그

항목 1, 2, 보조 1, 보조 2가 전부 이 파일 하나에서 나온다. 한 줄이 한 요청이며 탭으로 구분한다.

| 칼럼 | 뜻 |
|---|---|
| `t_plan` | 이 요청을 **보내기로 예정했던** 시각. 에폭 초, 소수점 이하 여섯 자리 |
| `t_send` | 실제로 보낸 시각 |
| `t_recv` | 응답을 다 받은 시각 |
| `kind` | `search` 또는 `upsert` |
| `status` | HTTP 상태 코드. 연결 실패는 0, 타임아웃은 -1 |
| `n` | 저장이면 배치 크기, 검색이면 `top_k` |
| `sess` | 필터에 쓴 세션 값 |
| `step` | 그 시점의 계단 번호 |

**`t_plan` 과 `t_send` 를 따로 남기는 것이 핵심이다.** 폐루프 부하 도구는 응답이 늦으면 다음 요청도 늦게 보내므로, 포화 구간에서 지연이 실제보다 작게 나온다. 서비스 지연은 `t_recv - t_send` 이지만 사용자가 겪는 지연은 `t_recv - t_plan` 이고, 포화 판정은 뒤의 값으로 해야 한다. 두 값을 모두 남겨야 나중에 어느 쪽으로도 볼 수 있다.

`sess` 를 남기는 이유는 설계서 5.3.2절 때문이다. 세션 크기가 `full_scan_threshold` 를 넘느냐에 따라 전수 스캔과 그래프 탐색이 갈리므로, 지연 분포를 세션 크기 구간별로 다시 묶어 볼 수 있어야 한다.

---

## 10. 수집이 측정을 방해하지 않게 하는 방법

| # | 장치 | 방법 | 확인 |
|---|---|---|---|
| 1 | 수집기를 Qdrant 코어 밖에 둔다 | `taskset -c` 로 16코어 밖에 고정한다 | `taskset -cp <pid>` 가 지정한 범위를 돌려준다 |
| 2 | 수집기의 쓰기를 다른 장치로 보낸다 | 결과를 `$RAW` 에 쓴다 | `findmnt -no SOURCE "$RAW" "$BENCH"` 가 서로 다른 값을 낸다 |
| 3 | 무거운 창구를 부하 구간 밖으로 뺀다 | `/metrics`, `/telemetry?details_level=4`, `/collections/{c}/memory` 를 경계에서만 읽는다 | 수집기 소스에 그 세 경로가 기본으로 들어 있지 않다 |
| 4 | 데이터 파일을 만지지 않는다 | 수집기가 cgroup과 `/proc` 과 HTTP만 연다 | `ls -l /proc/<pid>/fd` 에 `$BENCH` 아래 경로가 없다 |
| 5 | 프로세스를 매번 띄우지 않는다 | 한 프로세스가 계속 돌며 파일 핸들을 유지한다 | `collector.log` 의 `cpu_user` 가 8.2절의 합격선 안이다 |
| 6 | 매 표본마다 디스크에 확정하지 않는다 | 버퍼에 쌓고 60초마다 한 번 비운다 | 같음 |
| 7 | 수집 주기를 모든 조건에서 같게 둔다 | `manifest.json` 에 적고 조건 간 대조한다 | 조건 디렉터리의 주기 값이 전부 같다 |

네 번째 항목이 가장 중요하다. **수집기가 `$BENCH` 아래 파일을 한 번이라도 읽으면 그 페이지가 수집기 앞으로 과금되어 컨테이너의 메모리 한도가 그만큼 헐거워진다.** 2026-09-21 실측이 보여 준 것이 정확히 그 실패 형태다. 4GB 한도를 건 컨테이너가 호스트가 먼저 읽은 16GB 파일을 한도에 한 번도 부딪히지 않고 다 읽었다. 그래서 디스크 사용량을 알고 싶을 때도 `du` 를 쓰지 않는다.

수집 자체의 비용을 실측하는 절차는 한 번만 한다. 같은 조건과 같은 부하를 수집기 없이 한 번, 수집기를 켜고 한 번 돌린다.

```bash
# 수집기 없이 한 번 돌리고 처리량을 기록한다. 그다음 수집기를 켜고 같은 부하를 돌린다.
# 두 실행 모두 컨테이너를 새로 만들고 캐시를 비우고 시작한다.
```

**합격 기준.** 두 실행의 QPS 차이가 1% 이내이고 p99 지연 차이가 5% 이내여야 한다. 넘으면 1초 주기를 2초로 늘리거나 호스트 지표 수집을 줄인다. 이 검증은 계측 빌드의 왜곡 검증(`instrumented_build_2026-09-21.md` 7장)과 같은 부하로 함께 돌리면 한 번에 끝난다.

---

## 11. 실행

### 11.1 준비

컨테이너를 만든 뒤 cgroup 경로와 장치 번호를 찾는다. 이 둘이 없으면 항목 9, 10, 11을 하나도 얻지 못한다.

```bash
export QURL="${QURL:-http://127.0.0.1:6333}"
export COLL="${COLL:-laion100m}"
export QNAME="${QNAME:-qdrant-bench}"
CID="$(docker inspect -f '{{.Id}}' "$QNAME" 2>/dev/null)"
if [ -z "$CID" ]; then
  echo "$QNAME 컨테이너를 찾지 못했다. QNAME 을 실제 이름으로 설정한 뒤 다시 실행한다."
else
  PID="$(docker inspect -f '{{.State.Pid}}' "$CID")"
  export CG="/sys/fs/cgroup$(grep '^0::' "/proc/$PID/cgroup" | cut -d: -f3)"
  echo "CG=$CG"
  ls "$CG/memory.current" "$CG/io.stat" "$CG/cpu.stat"
fi
```

기본 이름 `qdrant-bench` 는 환경 문서 5.3절의 `run_condition.sh` 가 만드는 이름이다. 다른 이름으로 띄웠다면 `QNAME` 에 그 이름을 넣는다.

**합격 기준.** `CG` 가 경로 하나를 출력하고 세 파일이 모두 존재해야 한다. 경로 모양은 Docker의 cgroup 드라이버에 따라 다르다. systemd 드라이버면 `/sys/fs/cgroup/system.slice/docker-<id>.scope` 이고 cgroupfs 드라이버면 `/sys/fs/cgroup/docker/<id>` 이며, 둘 다 정상이다. 위 블록은 `/proc/<pid>/cgroup` 을 읽으므로 어느 쪽이든 올바른 경로를 얻는다. 파일이 없으면 cgroup 컨트롤러가 컨테이너 계층까지 위임되지 않은 것이므로 준비 문서 3.3절로 돌아간다.

이어서 `$BENCH` 가 놓인 블록 장치의 번호를 찾는다. `io.stat` 은 장치마다 한 줄이라 어느 줄을 볼지 정해야 한다. cgroup v2 의 `io.stat` 은 파티션이 아니라 디스크(request_queue) 단위로 집계하므로, `$BENCH` 가 파티션 위에 마운트되어 있으면 파티션의 MAJ:MIN 이 아니라 그 파티션이 놓인 부모 디스크의 MAJ:MIN 을 써야 한다. dm/LVM/md 위에 있는 경우는 한 단계 위가 맞는지 확인하지 못했다.

```bash
if [ -z "${BENCH:-}" ]; then
  echo "BENCH 가 비어 있다. preparation 문서 1.3절의 export 줄로 돌아간 뒤 다시 실행한다."
else
  SRC="$(findmnt -T "$BENCH" -no SOURCE)"          # -T 는 마운트 지점 아래 경로도 받는다
  PK="$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1)"
  DISK="${PK:-$(basename "$SRC")}"                  # 파티션이면 부모 디스크, 통짜 디스크면 자기 자신
  export IODEV="$(lsblk -dno MAJ:MIN "/dev/$DISK" | tr -d ' ')"
  export DISKDEV="$DISK"
  echo "SRC=$SRC DISK=$DISK IODEV=$IODEV DISKDEV=$DISKDEV"
  grep -F "$IODEV" "$CG/io.stat" || echo "  주의: io.stat 에 그 장치 줄이 아직 없다"
fi
```

**합격 기준.** 적재를 조금 진행한 뒤 이 명령을 다시 돌렸을 때 `io.stat` 에 해당 장치 줄이 나타나고 `wbytes` 가 0보다 커야 한다. 나타나지 않으면 장치 번호가 틀렸거나 `io` 컨트롤러가 위임되지 않은 것이다. LVM이나 device-mapper 위에 있으면 상위 장치와 하위 장치 중 어느 쪽에 잡히는지가 달라질 수 있으므로, **적재 중에 반드시 한 번 확인하고 그 결과를 `manifest.json` 에 적는다.**

### 11.2 조건 하나를 도는 전체 흐름

아래는 붙여 넣어 쓰는 순서다. 각 줄이 무엇을 하는지는 앞 장에 있다. 본 측정에서 이 흐름을 도는 주체는 새 구조 3.4 제어기이며(환경 문서 5.4절), 1번은 환경 문서 5.3절의 `run_condition.sh` 가 "조건이 섰다"까지 책임진다.

```bash
# 1. 캐시를 비우고 컨테이너를 새로 만든다. (환경 문서 5.3절 run_condition.sh)
# 2. 11.1절로 CG, IODEV, DISKDEV 를 잡는다.
# 3. 결과 디렉터리를 만든다. (9.1절)
```

수집기를 띄운다. 16코어 밖의 코어에 고정하고 배경으로 돌린다. 아래의 `320-323` 은 자리를 보여 주는 예시이며, 실제 값은 환경 문서 3.1절의 `$NODE`(SSD 가 붙은 노드)가 아닌 노드에서 6.3절의 `$LOADGEN_CPUS` 와 겹치지 않게 고른다. `--cores` 에 넘기는 `$CPUSET` 은 환경 문서 3.1절에서 SSD 가 붙은 노드 기준으로 정한 Qdrant 코어 열여섯 개다.

```bash
if [ -z "${RUNDIR:-}" ] || [ -z "${CG:-}" ] || [ -z "${CPUSET:-}" ]; then
  echo "RUNDIR 또는 CG 또는 CPUSET 이 비어 있다. 9.1절과 11.1절과 환경 문서 3.1절로 돌아간 뒤 다시 실행한다."
else
  taskset -c 320-323 python3 ./collect_metrics.py \
    --cgroup "$CG" --collection "$COLL" --url "$QURL" \
    --out "$RUNDIR/series" --cores "$CPUSET" \
    --io-dev "${IODEV:-}" --disk-dev "${DISKDEV:-}" \
    --period 1 --opt-period 5 &
  echo "$!" > "$RUNDIR/collector.pid"
  sleep 3
  tail -2 "$RUNDIR/series/collector.log"
fi
```

**합격 기준.** `collector.log` 에 `started` 줄이 찍히고, 3초 뒤 `series/cgroup.jsonl` 에 세 줄 안팎이 들어 있어야 한다. 비어 있으면 cgroup 경로가 틀린 것이다.

구간 경계마다 스냅샷을 찍는다. 적재 직후와 계단마다 `SNAP_RESET=1` 을 준다.

```bash
SNAP_RESET=0 ./snapshot.sh "$RUNDIR/snap" 00_start
# ... 적재 ...
# ... 6.2절의 적재 완료 판정 ...
SNAP_RESET=1 ./snapshot.sh "$RUNDIR/snap" 10_ingest_end
# ... 계단 1 부하 ...  (부하를 멈춘 뒤에 찍는다)
SNAP_RESET=1 ./snapshot.sh "$RUNDIR/snap" 20_step_1
# ... 계단 2 부하 ...
SNAP_RESET=1 ./snapshot.sh "$RUNDIR/snap" 21_step_2
# ... 꼬리 구간 소진 대기 ...
SNAP_RESET=0 ./snapshot.sh "$RUNDIR/snap" 90_tail_end
```

수집기를 멈추고 결과를 봉인한다. 컨테이너를 지우기 **전에** 수집기를 멈춰야 마지막 표본까지 남는다.

```bash
if [ -z "${RUNDIR:-}" ] || [ ! -s "$RUNDIR/collector.pid" ]; then
  echo "RUNDIR 이 비었거나 collector.pid 가 없다. 수집기 프로세스를 직접 찾아 종료한다."
else
  kill -TERM "$(cat "$RUNDIR/collector.pid")"
  sleep 2
  tail -2 "$RUNDIR/series/collector.log"
  chmod -R a-w "$RUNDIR" 2>/dev/null || true
fi
```

**합격 기준.** `collector.log` 의 마지막 줄이 `stopped` 로 시작하고 `late=0` 이어야 한다. 그리고 `samples` 가 구간 전체 길이를 초 단위로 센 값과 비슷해야 한다. 크게 모자라면 수집기가 중간에 밀린 것이다.

### 11.3 조건이 끝난 뒤의 최소 확인

컨테이너를 지우기 전에 아래 셋을 본다. 셋 다 나중에는 확인할 수 없는 것들이다.

```bash
if [ -z "${CG:-}" ]; then
  echo "CG 가 비어 있다. 11.1절로 돌아간다."
else
  awk '{printf "memory.current = %.2f GiB\n", $1/1073741824}' "$CG/memory.current"
  awk '/^max /{print "한도 도달 횟수 =", $2}' "$CG/memory.events"
  grep -E '^(pgmajfault|workingset_refault_file|file) ' "$CG/memory.stat"
fi
```

이 값이 12장의 조건별 검사에 그대로 들어간다.

---

## 12. 판정 계산식과 합격 기준

### 12.1 계산식

모든 Δ는 두 경계 스냅샷 사이의 차이다. Δt는 두 스냅샷의 `snapshot_meta.json` 에 적힌 시각의 차이다.

| 판정 | 식 |
|---|---|
| 컨테이너 CPU 사용률 | `Δcpu.stat.usage_usec / (Δt_초 × 1e6 × 16) × 100` |
| 코어별 CPU 사용률 | `/proc/stat` 의 코어 줄에서 유휴 항목의 증가분을 뺀 비율 |
| 컨테이너 디스크 읽기량 | `Δio.stat[IODEV].rbytes` |
| 컨테이너 디스크 읽기 횟수 | `Δio.stat[IODEV].rios` |
| mmap 페이지 부재 | `Δmemory.stat.pgmajfault` |
| 캐시에서 쫓겨났다 다시 읽은 횟수 | `Δmemory.stat.workingset_refault_file` |
| 메모리 한도 도달 횟수 | `Δmemory.events.max` |
| 메모리 정체 비율 | `Δmemory.pressure.some.total / (Δt_초 × 1e6) × 100` |
| 워킹셋 격차 | `1 - cached_bytes / expected_cache_bytes` |
| 검색 경로별 평균 | `Δtotal_duration_micros / Δcount` (칸마다 따로) |
| QPS | 요청 로그에서 그 구간의 `status == 200` 건수 / Δt |
| p50 / p95 / p99 | 요청 로그의 `t_recv - t_plan` 을 정렬해 뽑는다 |
| 단계별 비중 | `stage_timings` 의 `total_nanos` 를 단계 합으로 나눈다 |

### 12.2 해석할 때 지켜야 할 제약

**단계별 시간의 합을 요청 전체 시간과 비교하지 않는다.** 여러 스레드가 동시에 누적하므로 합이 실제 경과 시간을 넘는 것이 정상이다. 이 값으로 답할 수 있는 질문은 "어느 단계가 상대적으로 무거운가"이지 "요청 시간이 어떻게 쪼개지는가"가 아니다.

**보고할 때는 18개 지점을 묶어서 본다.** 코드의 18개 지점은 그대로 두고, 새 구조 4.1 의 단계 묶음으로 읽는다. 검색은 잠금 대기(S0), 후보 고르기(S1+S2), 거리 계산(S3+S4+S5+S6), 결과 합치기(S7, S8은 횟수)의 네 묶음이고, 저장은 대기열(W0), WAL 기록과 확정(W1+W2), 락 대기(W3+W4), 세그먼트 쓰기(W5+W6+W7+W8, 색인 W8은 따로 볼 수 있게)의 네 묶음이다. 18개 상세는 묶음에서 이상이 보일 때 파고드는 용도다. 수집은 이 묶음과 무관하게 18개를 그대로 남긴다.

**호출 횟수가 0인 단계를 먼저 본다.** 0은 그 경로를 타지 않았다는 정보다. 데이터가 커져 `full_scan_threshold` 를 넘으면 그래프 경로로 바뀌면서 S1부터 S6이 0으로 남는데, 이것은 결함이 아니라 설계서 3.2절에 적은 구조적 한계다. 어느 경로를 탔는지는 `/telemetry` 9칸으로 확인한다.

**W1과 S8의 값에는 실행기 대기 시간이 섞인다.** W1을 디스크 쓰기 비용으로 읽으면 안 된다. S8은 시간보다 발생 횟수가 정확하다. 상세는 `stage_isolation_2026-09-18.md` 8.3절에 있다.

**계측되지 않은 경로가 넷 있다.** 해당 단계가 비어 있을 때는 같은 문서 8.4절의 목록을 먼저 확인한다.

**`/telemetry` 의 `unfiltered_hnsw` 에 카운트가 잡히면 경보다.** 우리 구성은 항상 파티션 필터를 붙이므로 여기 값이 잡힐 수 없다. 잡혔다면 부하 도구가 필터를 빠뜨린 요청을 보내고 있는 것이다.

### 12.3 조건마다 반드시 통과해야 하는 검사

함정은 2026-09-21에 실재하는 것으로 확인되었으므로, 조건을 하나 돌릴 때마다 **함정이 재발하지 않았음을 확인해야 한다.** 재발한 채로 진행한 측정은 전부 버려야 하고, 나중에는 되살릴 수 없다.

| 조건 | 검사 | 통과 기준 | 실패하면 |
|---|---|---|---|
| 메모리 512GB (데이터가 다 올라가는 기준선) | 부하 구간의 `Δio.stat.rbytes` | 0에 가깝다 | 데이터가 한도보다 크거나 다른 프로세스가 메모리를 먹고 있다 |
| 메모리 512GB | 부하 구간의 `Δmemory.events.max` | 0이다 | 같음 |
| 메모리 128GB | `Δmemory.events.max` | 0보다 크다 | **과금 함정이 재발했다.** 캐시 비우기와 컨테이너 재생성 순서를 다시 본다 |
| 메모리 128GB | 구간 중 `memory.current` 의 최대 | 한도에 근접한다 | 같음 |
| 메모리 128GB | `Δio.stat.rbytes` | 512GB 조건보다 뚜렷하게 크다 | 같음 |
| 모든 조건 | `memory.swap.current` | 0이다 | 스왑이 열려 있다. 항목 11이 오염된다 |
| 모든 조건 | `cpuset.cpus.effective` | 16개 코어를 가리킨다 | 코어 고정이 먹지 않았다 |
| 모든 조건 | `stage_timings` 의 `enabled` | 참이다 | 대조 이미지가 떠 있다 |
| 모든 조건 | 검색 단계 `count` 의 합 대 부하 도구가 보낸 검색 건수 | 같은 자릿수다 | 계측 경로와 실제 경로가 다르다 |
| 모든 조건 | `collector.log` 의 `late` | 0이다 | 표본 간격이 균일하지 않다 |

**128GB 조건의 세 검사가 이 실험 전체의 안전장치다.** 이 셋이 통과하지 않으면 "메모리를 줄이면 디스크를 읽는다"는 전제 자체가 관측되지 않은 것이므로, 그 조건에서 나온 모든 수치는 병목이 아니라 다른 무언가를 재고 있다.

---

## 13. 확인하지 못한 것과 위험

| 항목 | 상태 | 어떻게 해소하나 |
|---|---|---|
| `GET /collections/{c}/memory` 의 비용 | **미확인.** `mincore(2)` 기반이라 385GB 규모에서 페이지 테이블을 훑는 시간이 얼마인지 모른다 | 8.2절의 첫 측정으로 잰다. 경계에서도 감당이 안 되면 조건마다 한 번으로 줄이고 판정을 cgroup 계수기로 옮긴다 |
| `GET /collections/{c}` 와 `/optimizations` 의 비용 | **미확인.** 가벼울 것으로 보았으나 직접 재지 않았다 | 같은 측정 |
| `/collections/{c}/optimizations` 의 `completed` 보존 개수 | **미확인.** 밀려나서 사라지면 항목 8을 복구할 수 없다 | 5초 주기로 모아 `uuid` 로 합친다. 적재 구간에서 작업이 많이 생기므로 그때 보존 개수를 관측한다 |
| `io.stat` 이 어느 장치 번호로 잡히는지 | **미확인.** LVM이나 device-mapper 위에 있으면 상위와 하위 중 어느 쪽인지 달라진다 | 11.1절의 확인을 적재 중에 실행하고 결과를 `manifest.json` 에 적는다 |
| mmap 페이지 폴트가 `io.stat` 에 잡히는지 | **부분 확인.** `read()` 경로로는 잡히는 것을 2026-09-21에 확인했으나 mmap 경로는 확인하지 않았다 | 함정 검증 문서 부록 B의 mmap 판을 한 번 돌려 `io.stat` 과 `pgmajfault` 가 함께 오르는지 본다 |
| `service.hardware_reporting` 을 켜는 설정 이름 | **미확인.** 설정 항목의 존재는 확인했으나 환경 변수 표기를 직접 검증하지 않았다 | 7장의 `grep -c '^collection_hardware_metric_'` 으로 결과만 확인한다. 0이면 설정 파일 쪽으로 넣는다 |
| `memory.peak` 의 존재 | **커널에 달렸다.** 오래된 커널에는 없다 | 수집기가 없으면 `null` 로 남기므로 측정이 멈추지는 않는다. 없으면 1초 시계열의 `memory.current` 최대로 대신한다 |
| 1초 주기가 충분한지 | **미확인.** 대기열 길이처럼 빠르게 변하는 순간값은 1초 사이에 200에 붙었다 떨어질 수 있다 | 첫 조건에서 대기열 길이 시계열을 보고 값이 0과 200 사이를 계단 없이 오가면 주기를 0.5초로 줄인다. 그때 8.2절의 비용 측정을 다시 한다 |
| 멈춤 구간 5초가 결과를 얼마나 바꾸는지 | **미확인.** 멈추는 동안 정리 작업이 진도를 나가고 캐시가 변한다 | 모든 조건에서 같은 길이로 멈추어 조건 간 비교만 성립시킨다. 절대값 해석에는 쓰지 않는다 |
| 동반 스크립트 두 개 | **측정 서버에서 실행하지 않았다.** 창구의 문서화된 응답 모양을 보고 작성했고, 구문 검사와 파싱 함수 단위 확인만 했다 | 첫 조건을 돌리기 전에 11.2절을 비어 있는 컬렉션으로 한 번 예행한다. 각 단계의 합격 기준이 그 예행의 점검표다 |
| 적재 방식 | **확정되었다.** 원칙은 "컨테이너가 데이터를 처음 만져야 한다"이고 방법은 마스터 사본 복사다(환경 문서 5.5절, `RELOAD=copy` 기본값). 재적재는 마스터가 없을 때의 대안일 뿐이며, 마스터 사본은 새 구조 3.2 적재기가 만든다 | 6.6절에 두 방식의 수집 차이를 적었다. 어느 쪽으로 세웠는지를 `manifest.json` 에 적는다. 마스터 복원에서는 복사 다음에 반드시 캐시를 비우며, 환경 문서 5.3절의 스크립트가 그 순서를 게이트로 강제한다 |

**가장 큰 위험은 함정의 재발을 늦게 알아차리는 것이다.** 조건 하나를 돌리는 데 적재와 부하와 꼬리를 합쳐 긴 시간이 드는데, 그 조건의 메모리 한도가 실제로 물리지 않았다는 사실은 12.3절의 검사를 돌리기 전에는 드러나지 않는다. 그래서 **12.3절의 검사를 조건이 끝난 직후, 컨테이너를 지우기 전에** 돌린다. 지운 뒤에는 cgroup 디렉터리가 사라져 확인할 방법이 없다.
