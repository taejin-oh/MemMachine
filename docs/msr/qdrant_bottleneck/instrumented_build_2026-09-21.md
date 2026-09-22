# 계측 빌드 제작과 측정 실행 절차

- 작성일: 2026-09-21
- 대상: Qdrant **v1.19.1**
- 단계 위치: 이 문서는 새 단계 구조의 **4번 계측 코드와 이미지**(4.2 계측 방법, 4.3 코드 삽입, 4.4 동작 확인, 4.5 왜곡 검증)와 **1.1 이미지 빌드**에 해당한다. 4.1 단계 묶음 정의는 8.1절에 있다. 문서 안의 장 번호(3장, 5장 등)는 이 문서의 절차 순서이지 단계 번호가 아니다.
- 관련 문서
  - `preparation_2026-09-21.md` — 이 절차에 들어가기 전의 사전 준비
  - `stage_isolation_2026-09-18.md` — 계측 지점 18개소 명세. **특히 8장의 제약을 읽지 않으면 결과를 오독한다**
  - `design_2026-09-17.md` 3.2절(계측 방법)과 4.6절(작업 순서)
  - `environment_setup_2026-09-21.md` — 7장의 왜곡 검증이 쓰는 조건 전환 스크립트 `run_condition.sh`(5.3절)와 코어 고정 방식(3.2절)
  - `stage_timing_v1.19.1.patch` — 이 절차가 적용하는 패치

---

## 1. 요약

Qdrant 소스에 계측 코드를 넣어, 검색과 저장의 **내부 단계별 소요 시간**을 얻는다. 이 두 항목은 Qdrant 기본 기능으로 확보할 수 없으며, 2단계의 핵심 질문인 "내부 어디서 막히는가"에 직접 답하는 정보다.

산출물은 이미지 두 개다. 하나는 계측을 켠 이미지이고, 다른 하나는 같은 소스와 같은 빌드 설정으로 계측만 끈 대조 이미지다. 두 이미지를 같은 부하로 비교해 **계측 자체가 결과를 바꾸지 않는다는 것**을 먼저 확인한 뒤에 본 측정에 들어간다.

| 장 | 내용 | 새 단계 구조에서의 위치 | 대략 소요 |
|---|---|---|---|
| 3 | 소스 확보 | 1.1 | 1분 |
| 4 | 패치 적용과 확인 | 1.1 (삽입 자체는 4.3, 완료) | 1분 |
| 5 | 이미지 두 개 빌드 | 1.1 | 첫 빌드 30~60분, 이후 재빌드는 짧다 |
| 6 | 동작 확인 | 4.4 (개발 빌드로 완료, 서버 빌드는 1.1에서) | 5분 |
| 7 | 왜곡 검증 | 4.5 (1번과 3.3이 있어야 한다) | 부하 시간에 따라 다르다 |
| 8 | 본 측정 | 5.1과 5.2 | 측정 계획에 따른다 |

계측값은 요청마다 남기지 않고 **단계별 총합과 호출 횟수만 누적한다.** 병목 지점을 가리는 데에는 총합이면 충분하고, 요청별 지연 분포는 Qdrant 기본 기능으로 이미 얻기 때문이다. 이 선택 덕분에 소스 변경이 14개 파일로 작게 끝났다.

---

## 2. 시작 전 준비

전체 준비 과정은 `preparation_2026-09-21.md` 에 있다. 이 절차만 놓고 보면 아래 네 가지가 갖춰져 있어야 한다.

| 필요한 것 | 확인 명령 | 합격 기준 |
|---|---|---|
| Docker | `docker version` | 클라이언트와 서버가 모두 응답한다 |
| git | `git --version` | 버전이 출력된다 |
| 디스크 여유 | `df -h .` | 빌드 산출물에 **20GB 이상** 필요하다 |
| 네트워크 | `curl -sI https://github.com \| head -1` | `HTTP/2 200` 이 나온다 |

빌드는 서버에서 직접 하는 편이 낫다. 다른 장비에서 만든 이미지는 아키텍처가 다르면 쓸 수 없고, 같더라도 CPU 최적화 설정이 달라질 수 있기 때문이다.

---

## 3. 소스 확보

버전을 v1.19.1로 고정한다. 패치가 이 버전의 줄 위치를 기준으로 만들어졌으므로 다른 버전에는 그대로 적용되지 않는다.

```bash
git clone --depth 1 --branch v1.19.1 https://github.com/qdrant/qdrant.git
cd qdrant
git describe --tags
```

마지막 줄이 `v1.19.1` 을 출력해야 한다. 다른 값이 나오면 이후 단계를 진행하지 않는다.

---

## 4. 패치 적용

패치 파일을 소스 최상위에 두고 적용한다. 먼저 적용 가능한지만 확인하고, 통과하면 실제로 적용한다.

```bash
git apply --check stage_timing_v1.19.1.patch && echo "적용 가능"
git apply stage_timing_v1.19.1.patch
```

`적용 가능` 이 출력되지 않으면 버전이 다르거나 소스가 이미 수정된 것이다. 그대로 밀어붙이지 말고 3장부터 다시 한다.

### 4.1 적용 결과 확인

패치가 의도한 범위만 건드렸는지 확인한다.

```bash
git diff --stat | tail -3
```

**14개 파일, 약 498줄 추가, 41줄 삭제**가 나와야 한다. 파일 수가 더 많으면 원치 않는 변경이 섞인 것이다.

이어서 계측 지점이 18개 모두 들어갔는지 센다. 지점마다 정확히 한 곳씩이어야 한다.

```bash
grep -rn "Stage::" lib/ --include='*.rs' \
  | grep -v stage_timing.rs \
  | grep -oE "Stage::(SegmentReadLock|CardinalityEstimate|FilterEval|ScorerSetup|DistanceCalc|ResultCollect|PostProcess|SegmentMerge|Rerun|QueueReserve|WalWrite|WalFlush|GlobalWriteLock|SegmentHolderLock|SegmentSelect|VectorWrite|PayloadWrite|IndexUpdate)" \
  | sort | uniq -c
```

18줄이 나오고 모든 줄의 앞자리가 `1` 이어야 한다. 어느 하나가 `0` 이거나 빠져 있으면 그 단계의 시간이 측정되지 않는다.

`Stage::` 라는 문자열은 Qdrant 자체 코드에도 여러 번 나온다. 이름이 같은 다른 열거형이므로 위 명령이 이름을 지정해 세는 것이다.

---

## 5. 이미지 두 개 빌드

이 장은 새 단계 구조의 **1.1 소스 확보, 패치 적용, 이미지 빌드**에 해당한다. 3장과 4장을 서버에서 거친 뒤 여기서 **계측 이미지와 대조 이미지를 한 번에 둘 다 만든다.** 같은 소스, 같은 Dockerfile 이며 `FEATURES` 스위치만 다르다. 두 이미지를 따로 다른 시점에 만들면 소스나 빌드 설정이 달라질 여지가 생기므로 반드시 같은 자리에서 잇달아 만든다. 배포 프로파일 이미지에 대한 동작 확인, 곧 11장이 남겨 둔 서버 빌드 확인도 이미지를 만든 직후 6장의 절차를 다시 돌려 여기서 끝낸다.

Qdrant의 Dockerfile은 `FEATURES` 라는 빌드 인자로 cargo 기능을 넘길 수 있게 되어 있다. 따라서 **공식 빌드 설정을 그대로 두고 계측 스위치만 바꿔** 두 이미지를 만들 수 있다. 설계서 3.2절이 요구하는 대표성 조건이 이렇게 충족된다.

계측을 켠 이미지를 먼저 만든다.

```bash
docker build --build-arg FEATURES=stage-timing \
  -t qdrant:1.19.1-stagetiming .
```

이어서 대조용으로 계측을 끈 이미지를 만든다. 같은 소스, 같은 Dockerfile이며 `FEATURES` 만 주지 않는다.

```bash
docker build -t qdrant:1.19.1-baseline .
```

첫 빌드는 의존 크레이트를 전부 컴파일하므로 30분에서 1시간이 걸린다. 두 번째는 cargo-chef가 의존성 계층을 재사용하므로 훨씬 짧다.

빌드가 끝나면 두 이미지가 모두 있는지 확인한다.

```bash
docker images | grep qdrant
```

---

## 6. 동작 확인

계측 이미지를 띄우고 계측이 실제로 켜졌는지, 값이 실제로 오르는지 확인한다. 이 확인을 건너뛰면 측정이 끝난 뒤에야 계측이 꺼져 있었다는 것을 알게 된다.

```bash
docker run -d --name qdrant-check -p 6333:6333 qdrant:1.19.1-stagetiming
sleep 5
curl -s localhost:6333/stage_timings | head -20
```

`"enabled": true` 가 나와야 한다. `false` 라면 `FEATURES` 인자가 전달되지 않은 것이므로 5장으로 돌아간다.

### 6.1 값을 보기 좋게 찍는 도구

아래를 `show.py` 로 저장해 둔다. 뒤의 모든 확인에서 쓴다.

```python
import json, sys
d = json.load(open(sys.argv[1]))
rows = [s for s in d["stages"] if s["count"]]
rows.sort(key=lambda s: -s["total_nanos"])
for s in rows:
    print("  %-26s %8d회  %12.1f us" % (s["stage"], s["count"], s["total_nanos"] / 1000.0))
missing = [s["stage"] for s in d["stages"] if not s["count"]]
print("  0회인 단계: " + (", ".join(missing) if missing else "없음"))
```

### 6.2 저장 경로 확인

컬렉션을 만들고 포인트를 두 건 넣은 뒤, 저장 단계의 호출 횟수가 0에서 올라가는지 본다.

```bash
curl -s -X PUT localhost:6333/collections/probe -H 'Content-Type: application/json' \
  -d '{"vectors":{"size":4,"distance":"Dot"}}'
curl -s -X PUT localhost:6333/collections/probe/index -H 'Content-Type: application/json' \
  -d '{"field_name":"s","field_schema":"keyword"}'

curl -s -X POST localhost:6333/stage_timings/reset
curl -s -X PUT 'localhost:6333/collections/probe/points?wait=true' \
  -H 'Content-Type: application/json' \
  -d '{"points":[{"id":1,"vector":[0.1,0.2,0.3,0.4],"payload":{"s":"a"}},
                 {"id":2,"vector":[0.2,0.1,0.4,0.3],"payload":{"s":"b"}}]}'

curl -s localhost:6333/stage_timings > st.json && python3 show.py st.json
```

**W0부터 W8까지 아홉 단계가 모두 0보다 커야 한다.** 실제로 확인했을 때 아래와 같이 나왔다. 값 자체는 표본이 두 건뿐이라 의미가 없고, 아홉 단계가 모두 잡혔다는 사실만 보면 된다.

```
  w2_wal_flush                      1회         423.5 us
  w7_payload_write                  2회          74.3 us
  w1_wal_write                      1회          64.6 us
  w8_index_update                   4회          55.5 us
  w3_global_write_lock              2회          21.0 us
  w6_vector_write                   2회          13.0 us
  w5_segment_select                 1회           5.9 us
  w0_queue_reserve                  1회           3.1 us
  w4_segment_holder_lock            2회           0.2 us
```

### 6.3 검색 경로 확인

**검색 확인은 반드시 색인이 만들어진 컬렉션에서 해야 한다.** 포인트 몇 건짜리 새 컬렉션에서는 색인이 아직 없어 계측 지점이 있는 경로를 타지 않으며, S1과 S2와 S3과 S6이 0으로 남는다. 이것을 계측 실패로 오해하기 쉽다.

아래 예시는 `hnsw_config`(`m=0`, `payload_m=16`)와 테넌트 색인 방식(`is_tenant: true` 인 keyword 색인)이 MemMachine 과 같고, `optimizers_config`(색인을 빨리 만들기 위함)와 필드명 `sid` 와 컬렉션 이름 `mm` 은 계측 확인용이다. MemMachine 의 실제 요청은 부록 `emulator_request_spec_2026-09-22.md` 3장에 있다.

```bash
curl -s -X PUT localhost:6333/collections/mm -H 'Content-Type: application/json' -d '{
  "vectors": {"size": 64, "distance": "Cosine"},
  "hnsw_config": {"m": 0, "payload_m": 16},
  "optimizers_config": {"indexing_threshold": 1, "default_segment_number": 1}
}'
curl -s -X PUT localhost:6333/collections/mm/index -H 'Content-Type: application/json' \
  -d '{"field_name":"sid","field_schema":{"type":"keyword","is_tenant":true}}'
```

`hnsw_config.full_scan_threshold` 는 주지 않는다. 이 값은 **10 이상만 받으며**, 생략하면 기본값 10000KB가 된다. 세션당 수십에서 수백 건 규모는 그 아래이므로 전수 비교 경로를 타게 되고, 그 경로가 바로 계측 지점이 놓인 주 경로다.

포인트를 수천 건 넣고 색인이 완성될 때까지 기다린다.

```bash
# 포인트 4000건을 sid 50개 세션에 나누어 적재한 뒤
curl -s localhost:6333/collections/mm \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["result"]; print(d["status"], d["indexed_vectors_count"])'
```

`green` 과 적재한 건수가 함께 나와야 한다. `indexed_vectors_count` 가 0이면 색인이 아직 만들어지지 않은 것이므로 더 기다린다.

이제 세션 필터를 붙인 검색을 스무 번 보내고 값을 읽는다.

```bash
curl -s -X POST localhost:6333/stage_timings/reset
# 검색 20회 반복
curl -s localhost:6333/stage_timings > st.json && python3 show.py st.json
```

**S0부터 S7까지 여덟 단계가 모두 0보다 커야 한다.** 실제 확인 결과는 아래와 같았다.

```
  s2_filter_eval                   20회         957.3 us
  s4_distance_calc                 40회         600.3 us
  s7_segment_merge                 20회         477.0 us
  s3_scorer_setup                  20회         159.7 us
  s1_cardinality_estimate          20회          78.5 us
  s5_result_collect                40회          50.5 us
  s6_post_process                  20회          18.5 us
  s0_segment_read_lock             40회          17.7 us
  0회인 단계: s8_rerun
```

`s8_rerun` 이 0인 것은 정상이다. 재검색은 드물게 일어나며, 0이라는 값 자체가 "이번 측정에서는 재검색이 없었다"는 정보다.

### 6.4 초기화가 듣는지 확인

```bash
curl -s -X POST localhost:6333/stage_timings/reset
curl -s localhost:6333/stage_timings > st.json && python3 show.py st.json
```

모든 단계가 0회로 돌아가야 한다. 확인이 끝나면 컨테이너를 정리한다.

```bash
docker rm -f qdrant-check
```

---

## 7. 왜곡 검증

계측이 측정 대상을 바꾸지 않는다는 것을 먼저 보여야 한다. 설계서 3.2절이 이 확인을 요구한다. 새 단계 구조에서는 **4.5 왜곡 검증**이며, **1번 환경(특히 1.5의 조건 전환 스크립트)과 3.3 부하기가 있어야 할 수 있다.** 그 둘이 없으면 이 장은 건너뛰고 10장으로 간다.

두 이미지를 **같은 조건, 같은 부하**로 돌리고 전체 처리량과 지연을 비교한다. 비교 대상은 계측값이 아니라 Qdrant가 원래 내놓는 지표다.

실행 방법은 환경 문서 5.3절의 `run_condition.sh` 를 **`IMG` 만 바꿔 두 번 돌리는 것**이다. 이 스크립트가 앞 컨테이너 폐기, 작업본 복원, 페이지 캐시 비우기, 게이트 A, 컨테이너 재생성, 게이트 B와 C, 계측 초기화까지를 한 묶음으로 하므로 두 실행이 같은 출발점에 선다. 한도는 세 조건 중 어느 것이어도 되지만 두 실행에서 같아야 한다. 아래는 기준선인 512GB 조건을 예로 든 것이다. `RAW`, `BENCH`, `CPUSET`, `NODE` 는 환경 문서 2.3절과 3.1절에서 정한 값이다.

```bash
# 1회차. 대조 이미지. "조건이 섰다"가 찍히면 제어기(단계 3.4, 부하 도구 문서 4.7절)가 부하기를 부른다
sudo RAW="$RAW" BENCH="$BENCH" CPUSET="$CPUSET" NODE="${NODE:-}" LIMIT=512g \
  IMG=qdrant:1.19.1-baseline "$RAW/bin/run_condition.sh"
# (제어기가 부하기를 실행하고 결과를 기록한다)

# 2회차. 계측 이미지. IMG 만 다르고 나머지 변수는 1회차와 같다
sudo RAW="$RAW" BENCH="$BENCH" CPUSET="$CPUSET" NODE="${NODE:-}" LIMIT=512g \
  IMG=qdrant:1.19.1-stagetiming "$RAW/bin/run_condition.sh"
# (제어기가 같은 부하기를 같은 파라미터로 실행한다)
```

컨테이너 실행 인자는 스크립트 5단계가 정한 대로 `--cpuset-cpus="$CPUSET"`, `--cpuset-mems=$NODE`, `-e QDRANT_NUM_CPUS=16` 이며, `--cpus` 계열은 쓰지 않는다. 이 문서의 이전 판은 여기서 `--cpus=16` 을 썼는데, 그것은 cgroup 의 `cpu.max` 로 걸리는 개수 제한이라 주기 앞부분에서 한도를 소진해 지연이 톱니처럼 튀고, 그 변동을 계측 왜곡으로 오인하게 된다. 코어 고정 방식은 환경 문서 3.2절을 따르고, 어느 노드의 코어를 쓸지는 환경 문서 3.1절대로 `$BENCH` 가 놓인 NVMe 가 붙은 NUMA 노드에서 고른다.

두 실행 사이에 반드시 들어가야 하는 것이 두 가지다. **컨테이너를 새로 만드는 것**과 **그 직전에 페이지 캐시를 비우는 것**이다. 앞 실행의 컨테이너가 남아 있으면 cgroup 이 겹치고, 캐시를 비우지 않으면 앞 실행이 올린 페이지가 뒤 실행에 그대로 넘어가 두 실행의 조건이 달라진다. 이유는 설계서 4.3절의 메모리 과금 함정에 있으며, 실측 근거는 `cgroup_trap_check_2026-09-21.md` 에 있다. `run_condition.sh` 를 쓰면 이 두 가지가 1단계와 3단계로 자동으로 들어가고, 게이트 A 가 캐시 비우기가 실제로 들었는지를 증명한다.

두 결과의 처리량과 지연 분포가 의미 있게 다르면 계측 비용이 측정을 오염시키고 있는 것이다. 그때는 반복이 많은 구간의 계측 방식을 다시 본다.

---

## 8. 본 측정 절차

조건 하나를 측정하는 흐름은 언제나 같다.

```
작업본 복원(마스터 사본 복사)  →  캐시 비우기  →  컨테이너 새로 생성  →  예열  →  계측 초기화  →  부하 인가  →  계측 수집
```

앞의 다섯은 환경 문서 5.3절의 `run_condition.sh`(1.5)가 하고, 뒤의 둘은 부하 도구 문서의 제어기(3.4)가 한다. 조건마다 데이터를 다시 적재하지 않는다. 적재는 3.2 적재기가 한 번만 하고 마스터 사본을 남기며, 조건마다 그 사본을 복사한다. 재적재는 마스터가 없을 때의 대안(`RELOAD=ingest`)일 뿐이다. 근거는 환경 문서 5.5절에 있다.

계측 초기화를 빠뜨리면 예열과 복원 과정의 값이 부하 구간의 값에 섞인다. 마스터 사본에서 복원한 경우에는 `run_condition.sh` 9단계가 초기화를 이미 했다. 마스터가 없어 적재기로 적재한 경우에는 적재가 끝난 직후 제어기가 다시 초기화해야 한다.

```bash
curl -s -X POST localhost:6333/stage_timings/reset
# 여기서 부하를 건다
curl -s localhost:6333/stage_timings > result_<조건이름>.json
```

수집한 값을 보기 좋게 정리하려면 아래를 쓴다. 총 시간이 큰 순서로 정렬해 어느 단계가 지배적인지 바로 드러낸다.

```bash
python3 - result_<조건이름>.json <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"계측 활성: {d['enabled']}")
rows = [s for s in d["stages"] if s["count"]]
rows.sort(key=lambda s: -s["total_nanos"])
total = sum(s["total_nanos"] for s in rows) or 1
print(f"{'단계':<26}{'호출':>12}{'총 ms':>14}{'평균 us':>12}{'비중':>8}")
for s in rows:
    print(f"{s['stage']:<26}{s['count']:>12,}{s['total_nanos']/1e6:>14,.1f}"
          f"{s['mean_nanos']/1e3:>12,.1f}{s['total_nanos']/total*100:>7.1f}%")
PY
```

### 8.1 읽기 묶음 — 18개 지점을 8묶음으로 본다

새 단계 구조의 **4.1 단계 묶음 정의**다. 코드의 계측 지점 18개는 그대로 두고, 결과를 읽고 보고할 때는 아래 여덟 묶음으로 본다. 정의는 `stage_isolation_2026-09-18.md` 8.6절과 같다.

| 경로 | 묶음 | 포함 지점 | 읽을 때 주의 |
|---|---|---|---|
| 검색 | 잠금 대기 | S0 | 세그먼트 읽기 잠금을 기다린 시간이다 |
| 검색 | 후보 고르기 | S1 + S2 | 카디널리티 추정과 필터 평가다. 필터가 무거우면 여기가 커진다 |
| 검색 | 거리 계산 | S3 + S4 + S5 + S6 | 스코어러 준비, 거리 계산, 결과 수집, 후처리다. 전수 비교 경로의 본체다 |
| 검색 | 결과 합치기 | S7 | 세그먼트별 결과 병합이다. S8 재검색은 시간이 아니라 **횟수**로 따로 본다 |
| 저장 | 대기열 | W0 | 대기열 자리를 기다린 시간이다. 대기가 포함되는 것이 의도다 |
| 저장 | WAL 기록과 확정 | W1 + W2 | W1에 실행기 대기가 섞이므로 이 묶음을 디스크 쓰기 비용으로 읽지 않는다 |
| 저장 | 락 대기 | W3 + W4 | 전역 쓰기 락과 세그먼트 홀더 락이다. 저장이 줄을 서는 곳이다 |
| 저장 | 세그먼트 쓰기 | W5 + W6 + W7 + W8 | 세그먼트 선택, 벡터 저장, payload 저장, 색인 갱신이다. **색인 갱신 W8은 따로 볼 수 있게 별도로 찍는다** |

**왜 코드는 18개를 유지하고 보고만 묶는가.** 병목 지점을 처음 가리는 단계에서는 여덟 묶음이면 충분하고, 18개를 한 줄씩 놓으면 어느 것이 큰지보다 목록의 길이가 먼저 눈에 들어온다. 그러나 묶음에서 이상이 보이면 그 안의 어느 지점인지 파고들어야 하고, 그때 18개 상세가 필요하다. 코드에서 묶어 버리면 그 길이 막히며, 계측 지점을 다시 나누려면 패치를 고치고 이미지를 다시 만들어 왜곡 검증까지 되풀이해야 한다. 그래서 코드는 18개를 그대로 두고 읽는 쪽에서만 묶는다.

6.1의 `show.py` 를 아래로 바꿔 둔다. 앞부분은 6.1과 같아서 18개 지점을 그대로 찍고, 뒤에 여덟 묶음의 합산과 경로 안 비중을 이어서 찍는다. 6.2와 6.3의 예시 출력은 앞부분에 그대로 남으므로 대조에 지장이 없다. 8장 첫머리의 정리 스크립트는 18개 상세를 볼 때 그대로 쓴다.

```python
import json, sys
d = json.load(open(sys.argv[1]))
rows = [s for s in d["stages"] if s["count"]]
rows.sort(key=lambda s: -s["total_nanos"])
for s in rows:
    print("  %-26s %8d회  %12.1f us" % (s["stage"], s["count"], s["total_nanos"] / 1000.0))
missing = [s["stage"] for s in d["stages"] if not s["count"]]
print("  0회인 단계: " + (", ".join(missing) if missing else "없음"))

# 여기부터 8묶음. 지점 이름은 패치의 18개 식별자 그대로다
by_name = {s["stage"]: s for s in d["stages"]}
GROUPS = [
    ("검색", "잠금 대기",       ["s0_segment_read_lock"]),
    ("검색", "후보 고르기",     ["s1_cardinality_estimate", "s2_filter_eval"]),
    ("검색", "거리 계산",       ["s3_scorer_setup", "s4_distance_calc",
                                "s5_result_collect", "s6_post_process"]),
    ("검색", "결과 합치기",     ["s7_segment_merge"]),
    ("저장", "대기열",          ["w0_queue_reserve"]),
    ("저장", "WAL 기록과 확정", ["w1_wal_write", "w2_wal_flush"]),
    ("저장", "락 대기",         ["w3_global_write_lock", "w4_segment_holder_lock"]),
    ("저장", "세그먼트 쓰기",   ["w5_segment_select", "w6_vector_write",
                                "w7_payload_write", "w8_index_update"]),
]
def nanos(name):
    return by_name[name]["total_nanos"] if name in by_name else 0
path_total = {}
for path, _, names in GROUPS:
    path_total[path] = path_total.get(path, 0) + sum(nanos(n) for n in names)
print()
print("  %-4s %-16s %14s %8s" % ("경로", "묶음", "합계 us", "비중"))
for path, label, names in GROUPS:
    t = sum(nanos(n) for n in names)
    share = t * 100.0 / path_total[path] if path_total[path] else 0.0
    print("  %-4s %-16s %14.1f %7.1f%%" % (path, label, t / 1000.0, share))
print("  %-4s %-16s %14.1f" % ("저장", "  그중 색인 갱신 W8", nanos("w8_index_update") / 1000.0))
rerun = by_name["s8_rerun"]["count"] if "s8_rerun" in by_name else 0
print("  %-4s %-16s %8d회" % ("검색", "재검색 S8", rerun))
```

비중은 같은 경로 안에서의 비중이다. 검색 네 묶음의 합을 100으로, 저장 네 묶음의 합을 100으로 놓는다. 검색과 저장을 서로 비교하지 않는 것은 9장 첫 문단과 같은 이유다. 여러 스레드가 동시에 누적하므로 절대값의 합은 경과 시간이 아니다.

---

## 9. 값을 읽을 때 주의할 것

**단계별 시간의 합을 요청 전체 시간과 비교하지 않는다.** 여러 스레드가 동시에 누적하므로 합이 실제 경과 시간을 넘는 것이 정상이다. 이 값으로 답할 수 있는 질문은 "어느 단계가 상대적으로 무거운가"이지 "요청 시간이 어떻게 쪼개지는가"가 아니다.

**호출 횟수가 0인 단계를 먼저 본다.** 0이라는 것은 그 경로를 타지 않았다는 뜻이며, 그 자체가 정보다. 예를 들어 그래프 경로로 검색이 처리되면 전수 비교 경로의 단계들이 0으로 남는다.

**W1과 S8은 값에 대기 시간이 섞인다.** 두 지점은 비동기 구간을 걸치므로 실행기의 대기 시간이 포함된다. W1을 디스크 쓰기 비용으로 읽으면 안 된다. 상세는 `stage_isolation_2026-09-18.md` 8.3절에 있다.

**계측되지 않은 경로가 있다.** 필터 없는 전수 비교, `peek_top_visible` 가 쓰는 경로, 덧붙이기 전용 저장 경로는 계측하지 않았다. 해당 단계가 비어 있을 때 이 목록을 먼저 확인한다. 상세는 같은 문서 8.4절에 있다.

---

## 10. 다음 단계

이 문서의 3장부터 6장까지가 끝나면 새 단계 구조의 4.2(계측 방법), 4.3(코드 삽입), 4.4(동작 확인)가 끝난 것이다. 4.4는 개발 빌드로 확인한 상태이며, 배포 프로파일 이미지에 대한 확인은 1.1로 넘겼다. 남은 것은 두 가지이고, 둘 다 다른 단계에 기댄다.

- **1.1 이미지 빌드.** 5장의 절차를 서버에서 수행해 계측 이미지와 대조 이미지를 한 번에 만든다. 11장의 서버 빌드 확인이 여기에 딸린다. 서버 접근(준비 문서)만 있으면 되고 다른 단계에 기대지 않는다.
- **4.5 왜곡 검증.** 7장의 절차다. 조건을 세울 1번 환경(특히 1.5의 조건 전환 스크립트)과 부하를 걸 3.3 부하기가 있어야 하므로, 그 둘이 끝나기 전에는 할 수 없다. 1.3 함정 확인은 이미 끝났고 그 결과가 7장의 캐시 비우기와 컨테이너 재생성 요구로 반영되어 있다.

4.5까지 끝나고 2번 데이터와 3번 부하 도구가 갖춰지면 5.1 예비 측정으로 들어간다. 8장의 절차는 그때 쓴다.

---

## 11. 미확인 사항과 위험

**검증한 것과 하지 않은 것을 구분해야 한다.** 아래까지는 실제로 확인했다.

| 확인한 것 | 결과 |
|---|---|
| 계측 켠 빌드와 끈 빌드가 모두 컴파일되는가 | 통과 |
| 계측 모듈 단위 테스트 | 2건 통과 |
| clippy 지적 | 0건 |
| 서버가 기동하고 `enabled` 가 true 인가 | 통과 |
| 저장 9개 단계가 실제로 값을 올리는가 | **9개 전부 확인** |
| 검색 단계가 실제로 값을 올리는가 | **S0부터 S7까지 8개 확인.** S8은 드물게 발생하는 지점이라 0 |
| 초기화가 듣는가 | 통과 |

**다만 확인은 개발 프로파일(`cargo build`) 바이너리로, 포인트 4,000건 규모에서 했다.** 배포 프로파일로 빌드한 이미지에서의 확인, 곧 서버 빌드 확인은 새 단계 구조의 **1.1에서 수행한다.** 서버에서 5장의 이미지를 만든 직후 6장의 절차를 다시 돌리면 된다. 대규모 데이터에서도 같은 경로를 타는지는 5.1 예비 측정에서 본다. 특히 데이터가 커져 `full_scan_threshold` 를 넘으면 그래프 경로로 바뀌고, 그때는 S1부터 S6이 0으로 남는다. 이것은 결함이 아니라 `stage_isolation_2026-09-18.md` 3.2절에 적은 구조적 한계다.

**계측 비용을 아직 재지 않았다.** 7장의 왜곡 검증(새 구조 4.5)이 그 답을 준다. 특히 반복이 많은 S4와 S5가 우려 지점이다.

**W5의 범위를 명세서와 다르게 좁혔다.** 명세서가 지목한 `apply_points_with_conditional_move` 는 내부에서 벡터 저장과 payload 저장과 색인 갱신을 모두 실행하므로, 그대로 재면 단계가 겹쳐 비교가 무의미해진다. 판단 근거는 `stage_isolation_2026-09-18.md` 8.2절에 적었다.

**패치는 v1.19.1 전용이다.** 상위 버전에 적용하면 줄 위치가 어긋나 실패하거나, 더 나쁘게는 엉뚱한 곳에 붙는다. 버전을 올릴 일이 생기면 패치를 다시 만든다.

**엔드포인트에 접근 제어가 없다.** `/stage_timings` 는 인증을 요구하지 않는다. 실험용 빌드를 전제로 한 선택이므로, 외부에서 닿는 망에 띄우지 않는다.
