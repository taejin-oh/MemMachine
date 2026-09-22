# 에뮬레이터 구현 설계 (종합) — 2026-09-21

이 문서는 부하 도구(에뮬레이터)의 **제작 직전 종합 설계**다. 요구 명세(`docker_setup/emulator_spec_2026-09-21.md`, 이하 **SPEC**)·코드 대조 리뷰(`emulator/emulator_spec_code_review_2026-09-21.md`, 이하 **REV**)·당일 결정(CH-20260921-*)·당일 실측(B1~B3)을 하나로 합쳐, **코드를 쓰기 시작했을 때의 정답**을 고정한다. SPEC과 충돌하면 이 문서가 우선한다 (충돌 지점은 §2에 전량 명시).

- 근거 표기: **[사실]** 코드·git·실측으로 확인 / **[추론]** 근거 있는 판단 / **[미결]** 확인 필요. §9에 미결 총람.
- 인용 규약: `[S:절]`=SPEC, `[R:§]`=REV, `[CH-n]`=SPEC 부록 변경로그, `[Bn]`=아래 실측, `[T:S1~S13]`=트레이스 스텝, `[D:날짜]`=사용자 결정, `[C:경로:행]`=MemMachine 코드 (`/home/tj/Workspace/ltm/memmachine/MemMachine_src`, HEAD `8d7b832` 2026-09-17)

## 0. 실측 기록 (이 문서가 새로 추가한 사실)

| ID | 내용 | 조건 |
|---|---|---|
| [B1] | 검색 요청(768차원, limit=80, 필터 1개) JSON 본문 = **8,152바이트**. `json.dumps` 단일 코어 **초당 7,596건** | Python 3.12.3, 이 머신 |
| [B2] | 검색 응답(limit=80) `json.loads` 단일 코어 **초당 34,625건** | 같음 |
| [B3] | 11필드 payload(uuid4·ISO tz-aware) JSON = **442바이트**. 저장 배치(batch=4, 768d) `json.dumps` 초당 3,393건 | 같음 |
| [B4] | 이 머신 코어 수 344. `orjson` 미설치 | 같음 |

[추론] [B1]~[B3]은 직렬화만 재고 asyncio·TCP·HTTP 오버헤드와 GC 꼬리를 못 재므로 **언어 확정 근거가 아니라 "Python이 불가능하지 않다"의 반증 근거**로만 쓴다. 확정은 0단계(§8.0).

---

## 1. 목적과 비목적

**목적**: MemMachine 없이 Qdrant v1.19.1에 MemMachine과 동일 모양의 요청을, SPEC 3.2절 파라미터 전부를 실행 변수로 보내는 도구. 측정 대상은 Qdrant 내부(W2·W3 사각지대 포함). [S:1]

**비목적** (만들지 않음): 분산 실행, 검색/저장 분리 풀, 시각화, 조건 전환 자동화(제어기 `run_condition.sh` 몫). [S:2.3] 삭제 부하는 §2-4 결정으로 현 시점 비목적.

---

## 2. SPEC을 갱신한 확정 결정 (8건 전수)

| # | 항목 | 확정 | 근거 |
|---|---|---|---|
| 1 | `with_payload` | **`false` 확정** (SPEC의 "잠정" 해소) | [사실][R:§1][CH-1] 커밋 `abf92a3`(2026-09-09)이 `return_properties` 경로 삭제 → 최신 코드는 `with_payload=False` 하드코딩 [C:qdrant_vector_store.py:361-362], 트레이스 [T:S6~S9,S11]와 일치 |
| 2 | `wait=true` | 저장·삭제 모두 **`?wait=true`** | [사실] 코드 미전달 [C:qdrant_vector_store.py:316-319] + qdrant-client 1.19.0(uv.lock) 기본값 `wait: bool = True` 시그니처 실측 [CH-2][R:§2.11] + [T:S4,S5] |
| 3 | 저장 실패 절반 쪼개기 | **driver 재현 안 함**. 단순화 | [D:2026-09-21][CH-3]. 근거: sleep 없는 즉시 재귀 [C:qdrant_vector_store.py:312-325]이고 저장 실패 유도 실험이 계획에 없음. 결정 흔적은 `run.json`의 `driver_version`에 남김 |
| 4 | 삭제 부하 | **보류** (`enabled:false` 유지). 구현 시 모양은 `must=[파티션, has_id(uuid들)]`로 고정 | [D:2026-09-21][CH-4]. 모양은 [사실][C:qdrant_vector_store.py:397-409]. 단 트레이스 S12/S13 원문 미확인 → [미결 M4] |
| 5 | payload 크기 | **두 겹**: 코드 확정분(11필드 ≈442B [B3])은 loader 고정 채움 + 미확인분만 옵션 `extra_payload_bytes`(기본 0) | [D:2026-09-21][CH-7]. 근거: 본문 텍스트는 SQL `LargeBinary` 컬럼이지 Qdrant payload가 아님 [C:sqlalchemy_segment_store.py:170-171][R:§2.11]. 사용자 properties는 통째 복사 통과 [C:qdrant_vector_store.py:260-267] |
| 6 | 레지스트리 컬렉션 | **재현 안 함** + 대조 예외 | [D:2026-09-21][CH-6]. 1차원 컬렉션·등록 호출은 세션 시작 시 1회성 [C:qdrant_vector_store.py:547-604,686-703]이라 부하 구간에 안 들어옴 [R:§3.1] |
| 7 | 컬렉션 이름 | **평이명 유지** (`laion100m` 등). 실제는 `{namespace}__{sha256(스키마)}` 해시명 [C:qdrant_vector_store.py:514-519]이나 대조의 `<coll>` 정규화가 흡수 | [D:2026-09-21][CH-6] |
| 8 | 프로토콜 | **REST 고정** (`protocol` 파라미터로 노출만). gRPC는 1회 차이 기록용 | [사실] `prefer_grpc` 기본 False [C:database_conf.py:247]. gRPC는 서버 JSON 파싱 비용(측정 대상)을 제거해 대상이 바뀜 [S:4.6] |

---

## 3. 아키텍처 — 3 프로그램, 경계는 SPEC 그대로

```
[loader]  Python. 부하 구간 이전. 데이터 파일 읽기 권한 O.
          컬렉션 생성 → 인덱스 11개 → 대량 upsert → verify
[driver]  0단계에서 언어 확정. 부하 구간 동안만.
          데이터 파일 읽기 권한 X. Qdrant API 3개만.
[runner]  이 문서 범위 밖 (environment_setup 5.3 run_condition.sh).
          사다리 순회·스냅샷·컨테이너 수명. driver 호출 계약만 §7.
```

**구조 불변식** (위반 시 실행 무효):
1. driver 컨테이너 마운트는 `$RUNDIR/load` 하나. `$RAW`·`$BENCH` 미마운트를 `docker inspect`로 확인. [S:4.3, R1]
2. driver 허용 API는 `POST .../points/query/batch`, `PUT .../points?wait=`, `POST .../points/delete?wait=` 셋. 자체 카운트한 `endpoint_counts`에 목록 밖 경로가 0이 아니면 무효. [S:4.4, R6]
3. 질의 벡터는 stdin으로만 수신 (경로 인자 없음). [S:5.4 — 마운트 0개 원칙 유지 + 함정 비적용 근거: 질의 파일은 $BENCH 밖]
4. 부하 직전 `pgrep -f 'loader load'`가 비어 있어야. [S:4.5]
5. driver 컨테이너 memory/swap 4GiB. [S:4.3 — 근거 계산(질의집합 0.95GiB + 버퍼 0.1GiB)에 [B1] 본문 8.1KB×1000 = 8MB를 재확인. 4GiB 유지]

**loader는 MemMachine이 "만드는 것"만 재현하고 "운용 시 내는 부수 호출"(레지스트리)은 재현하지 않는다** (§2-6). 컬렉션 설정 본문은 [T:S1]과 [C:qdrant_vector_store.py:641-674]가 일치: `{vectors:{size:dim,distance:"Cosine"}, hnsw_config:{m:0,payload_m:16}}` → 인덱스 11개(`sys-partition_key` keyword is_tenant + `_timestamp`/`_created_at` datetime + str 8 + int 1 [C:long_term_memory.py:79-89][C:event_memory.py:118-127]).

---

## 4. 설정 파일 — 데이터 형상 / 부하 형상 분리 (SPEC 3.2 유지 + 확정값 반영)

### 4.1 load.yaml (데이터 형상 — 바꾸면 재적재)

```yaml
points: 100000000            # [S:3.3]
dim: 768                     # 허용 768|1024|1536|2560
sessions: 100000             # 파티션 키 개수 [S:3.3]
session_size_dist: {dist: zipf, s: 1.0}   # 실제 분포 미정 [미결 M2]
payload_index_count: 11      # 자르기 시 sys-partition_key 상시 유지 [S:3.3]
extra_payload_bytes: 0       # [CH-7]. 0=11필드 442B 고정 채움. >0=미색인 더미 필드로 채움
distance: Cosine             # [T:S1][C:qdrant_vector_store.py:_QDRANT_DISTANCE]
hnsw: {m: 0, payload_m: 16}  # 고정. [T:S1][C:qdrant_vector_store.py:646-649]
```

payload 필드 값 생성 규칙 [사실 기반]: `_episode_uid`/`_produced_for_id`=uuid4, `_timestamp`/`_created_at`=tz-aware ISO, `_sequence_num`=int, `_producer_id`=`p00`~`p99` 균등(세션 독립) [S:3.5], `_producer_role`/`_episode_type`/`_content_type`=그럴듯한 문자열. **더미 필드는 색인 생성 금지** (인덱스 11개 불변 [S:3.5]).

### 4.2 cond.yaml (부하 형상 — 적재 없이 변경)

```yaml
condition_tag: mem256_c64
target: {url: "http://127.0.0.1:6333", protocol: rest, collection: laion100m, timeout_ms: 30000}
workload:
  mode: closed               # 폐루프 기본 — 동시 요청 수가 입력이어야 포화 판정 성립 [S:5.1]
  concurrency: 64
  think_time_ms: 0
  search_write_ratio: [9, 1] # [미결 M2: 동료 (가) 값 대기]
  session_skew: {dist: zipf, s: 1.0}   # 검색 접근 치우침 ≠ 세션 크기 분포(적재기) [S:5.2]
  search:
    top_k: 20
    over_fetch: 4            # limit=top_k×4. [사실][T:S6] _EVENT_BACKEND_DEDUP_OVERFETCH=4 [C:long_term_memory.py:107,310-313]
    with_payload: false      # 확정 [CH-1]
    with_vector: false       # [T:S6~S9,S11][C:qdrant_vector_store.py:361]
    filter: partition_only   # A/B 전환 [S:3.5]
    selectivity_pct: 1       # _producer_id 다이얼 k개 should [S:3.5]
  write: {batch_size: 4, wait: true}    # batch 4=[T:S4] 관측값. wait=[CH-2] 확정
  delete: {enabled: false}              # [D:2026-09-21] 보류
duration: {warmup_sec: 60, measure_sec: 300}
```

**명령행 덮어쓰기는 `--concurrency` `--selectivity-pct` `--condition-tag` `--out` 4개만.** 그 외 인자 시도는 거부 메시지 출력. [S:3.4, 6.2 검증기준]

### 4.3 요청 본문 템플릿 (driver가 조립하는 것 — 클라이언트 라이브러리 미사용 [S:4.6])

검색 ([T:S6~S9,S11] 구조, [C:qdrant_vector_store.py:349-365]과 동일형):
```json
POST /collections/<coll>/points/query/batch
{"searches":[{"query":[...768...],"filter":{"must":[
   {"key":"sys-partition_key","match":{"value":"<sess>"}},
   (B인 경우) {"should":[{"must":[{"key":"_producer_id","match":{"value":"pNN"}}]},... k개]}
 ]},"limit":<top_k×4>,"with_payload":false,"with_vector":false}]}
```
- 파티션이 `must[0]`, 사용자 조건은 **별도 must 항목으로 중첩**(평평하게 펴면 안 됨 — 카디널리티 추정 변화 [S:7.3-4], 코드 동일 [C:qdrant_vector_store.py:349-351]).
- 필드명 `query` vs `vector`: 트레이스가 요약본이라 원문 미확인 [미결 M1]. 재수집 트레이스 원본 본문으로 확정 전까지 두 변수로 만들어 재수집 후 한 줄 수정.
- 저장: `PUT /collections/<coll>/points?wait=true`, `{"points":[{"id":uuid,"vector":[±섭동된 질의집합 벡터],"payload":{...}}×batch]}` — 벡터 재사용+섭동 이유는 [S:5.3](합성 난수는 군집 구조 소실). 저장 포인트는 별도 id 대역+payload 표식 [S:5.3].
- 삭제(재개 시): `must=[파티션, has_id]` [§2-4].

---

## 5. 워크로드 모델

- **폐루프 기본**: 워커 N개, t_plan(직전 응답+think) 기록. 포화 판정은 `t_recv - t_plan`. [S:5.1, 수집문서 9.3]
- **개루프 보조** (`mode: open`): 포화 이후 대기열 관찰용. 어느 조건에서 돌릴지는 [미결 M6]. [S:9.4]
- **세션 접근**: zipf(s 파라미터) 워커 공통 분포. [S:5.2 — 치우침이 캐시 워킹셋 크기를 정하고 그게 메모리 축의 관찰 대상]
- **검색:저장 혼합**: 단일 워커 풀 + 요청별 가중 추첨. 달성 비율을 `run.json`에 기록 — 의도/달성 괴리 자체가 저장 포화 신호. [S:5.3]
- **옵티마이저 구간 표시**: `queued_segments`가 0이 아닌 단은 비교 대상 아님 — 제어기 스냅샷으로 판정, driver는 알 필요 없음. [S:6.4]

## 6. 출력 (SPEC 6장 + 수집문서 9.3 유지, 값 확정)

```
$RUNDIR/load/
├── requests.tsv   t_plan t_send t_recv kind status n sess step   ← 스키마 수집문서 9.3 고정
├── load_config.json  유효 설정 전문 + sha256 → 재현 계약 [S:6.2, R5]
├── run.json       §6.1 필드 전수
├── series.csv     t_sec,op,sent,ok,err,timeout,inflight,p50_us,p95_us,p99_us,max_us (1초)
└── hist/search.hgrm, write.hgrm   HDR. 합치기 가능·임의 분위 재추출 [S:6.1]
```

### 6.1 run.json 필수 필드
SPEC 6.2 목록 그대로: `condition_tag`, `effective_config_file/sha256`, `driver_version/commit/cpuset/peak_cpu_pct`, `started_at_utc/warmup_sec/measure_window_sec`, `achieved_search_write_ratio/total_requests/endpoint_counts`, `error_counts_by_class`(연결거절·타임아웃·4xx·5xx 분리, **전수 카운트** [S:6.2]), `selectivity_pct/expected_matching_points`(비율+절대건수 모두 — full_scan_threshold 갈림 판정용 [S:3.5]), `query_set_size/query_set_rss_bytes`, `requests_tsv_sampling`.

### 6.2 requests.tsv 솎기
기본 전수. 첫 스모크에서 쓰기 비용이 측정가장을 넘으면 표본화(`requests_tsv_sampling`에 비율 기록) — series/hist/run.json 총계는 전수 유지. [S:9.3, 미결 M5]

## 7. 제어기 계약 (SPEC 4.2 그대로 — 수정 없음)

```
loader load    --config load.yaml          # + [CH-5] 인덱스 11개·payload 규칙 §4.1
loader verify  --config load.yaml          # 포인트수/세션수/인덱스 11개 보고 [S:8.2-1]
driver floor   --concurrency N --duration S --out DIR      # 0단계
driver run     --config cond.yaml [--concurrency|--selectivity-pct|--condition-tag] --out DIR
driver ladder  --config cond.yaml --rungs 1,2,4,8,16 --out DIR   # 스냅샷 불요 자리만 [S:6.4]
driver trace   --config cond.yaml --n 100 --out DIR        # 요약+원본 본문 병기 [S:7.2]
driver recall  --config cond.yaml --queries 200 --out DIR  # 부하 구간 밖 전용 [S:8.5]
```

사다리는 제어기가 `driver run` 반복 호출 + 구간마다 스냅샷. 올림+내림 한 벌. [S:6.4]

## 8. 제작 순서와 각 단계의 검증 (SPEC 8장 + 금일 보강)

### 8.0 단계 0 — 바닥 측정으로 언어 확정 (**여전히 열림**)
- 후보: Python async(httpx 직접 조립) / Python+`orjson` / Rust reqwest. `orjson`을 후보에 넣은 근거: 저장 직렬화가 [B3]로 Python 후보 중 최약 지점이고 orjson이 이를 3~5배 완화 [추론, 벤치 필요], 도입 비용은 pip 한 줄.
- 대상: 스모크 소형 컬렉션, 서버 지연≈0. `driver floor`로 c∈{1,64,256,1000} × 후보별 p50/p99/max 분포 + 최대 QPS 표.
- 합격 기준의 배수는 [미결 M5 — 첫 스모크 후]. 단 비교표가 나오면 언어 확정 문단을 설계 4.4절에 추가하는 것까지가 단계 종료 조건. [S:8.2-0]
- [B1]~[B4]의 사전 근거로 "Python 탈락 아님"은 확인됨. 꼬리 지연(GC·GIL)은 벤치로 재는 것 자체가 불가능 → 0단계 실측이 판정. [S:2.2]

### 8.1~8.6 단계 1~6 — SPEC 8.1 표 유지. 종료 판정 기준도 SPEC 8.2 그대로.
적용되는 갱신: 1단계 loader는 §4.1 payload 규칙·레지스트리 미재현. 2단계(검색 전용 최소 driver) 완료 시 계측 빌드 왜곡 검증 개방 [S:8.1]. 5단계 trace 대조는 §4.3 템플릿 + 예외 2건(레지스트리·이름 정규화) + 합격기준 5개(with_payload=false 포함) [S:7.3][CH-1].

## 9. 미결 총람 (이 설계로도 못 닫은 것 — 닫는 조건 명기)

| ID | 미결 | 닫는 방법 | 차단하는 단계 |
|---|---|---|---|
| M1 | 검색/저장 요청 본문의 원본 JSON (요약 문자열 공백. `query`/`vector` 필드명 포함) | 재수집 트레이스(요구사항은 설계 5.1(나)에 추가 완료) | 단계 5의 완전성만. 2단계는 템플릿 재현으로 진행 가능 |
| M2 | 세션 수/세션 크기 분포/검색:저장 비율/통과 비율의 실제값 | 동료 인계(설계 5.1(가)) — 기본값은 zipf 1.0/9:1로 돌아가되 본 측정 조건값은 아님 | 단계 3 이후의 조건 설정 |
| M3 | `_producer_id` 실카디널리티 | 동료 자료. 균등 100개 배정이 실제와 다르면 로더 기본 분포 수정 | 단계 4 |
| M4 | 트레이스 S12/S13 삭제 본문(§2-4 가정 검증) | 재수집 시 삭제 원문 포함 요구(5.1(나) 반영済) | 삭제 부하 재개 |
| M5 | 바닥 p99 배수·사다리 일치 오차·CPU 포화 임계·tsv 솎기 비율 | 첫 스모크 실측. 지금 정하면 지어내는 것 [S:9.3] | 본 측정 판정 |
| M6 | 개루프 모드 운용 조건 | 첫 포화 관측 후 | 없음(보조) |
| M7 | 트레이스 채취 시점 MemMachine 커밋 | 5.1(다)에 확인 항목 추가済. CH-1 확정과 무관하게 대조 기준 보강용 | 단계 5 해석 |

## 10. 리스크 (SPEC 9.4 + 신규)

- 폐루프의 조정된 누락: `t_plan/t_send` 분리 기록으로 완화 [S:9.4]. 완전 해소 아님.
- 루프백 통신: 단일 서버 확정[S:4.1]이라 기록만.
- [신규·추론] Python 채택 시 저장 직렬화 병목([B3]): 저장 위주 조건에서 driver CPU 선점 가능. 완화: orjson, 필요시 저장 워커만 멀티프로세스(단 꼬리 왜곡 검토 후). `driver_peak_cpu_pct`가 감시자 [S:6.2].
- payload 더미 필드가 실제 분포와 다른 카디널리티를 만들 수 있음 — 단 더미는 **미색인**이라 옵티마이저 카디널리티 추정에 안 잡힘 [사실: 인덱스된 필드만 추정 대상]. 더미 값은 상수 1개로 두고 payload 크기 실험 전용임을 주석. [추론]

---
**이 문서의 근거 원본**: SPEC 본문·부록 CH 표 / REV §1~§4 / 설계서 4.4·5.1 / 수집문서 9.3 / MemMachine 코드 HEAD `8d7b832` 실측 / 벤치 [B1]~[B4](§0 조건) / 결정 [D:2026-09-21] 5건.
