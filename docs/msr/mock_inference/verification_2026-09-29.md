# mock_inference 로컬 드라이런 검증 (2026-09-29)

설계 문서 [design_2026-09-29.md](design_2026-09-29.md) §14의 D0에서 D8까지를 개발 머신에서 순서대로 실행한 기록이다. 코드는 `tools/mock_inference/`에 있다.

## 요약

D0에서 D8까지 모두 통과했다. 실행 중 검사 스크립트 하나의 버그를 고쳤고(`checks/stream_check.py`의 누락 행 계산 구간), 설계 문서의 D4가 20만 행 파일로는 성립하지 않아 100만 행 합성 파일로 바꿨다. 처리량 숫자는 서버와 `oha`를 같은 노트북에서 돌린 값이라 하드웨어와 네트워크가 다른 사내 환경을 대변하지 않으며, 이 문서에서는 모두 "로컬(참고)"으로 표시한다. 그래도 worker 3개로 임베딩 약 128,000 RPS, rerank(문서 80개) 약 50,000 RPS에 p99가 3ms 아래여서, 설계 §10.1이 보수적으로 잡은 프로세스당 1,000에서 3,000 RPS보다 한 자릿수 이상 여유가 있다는 것은 알 수 있다. 코드 리뷰 뒤 고친 것과 다시 돌린 결과는 마지막 절 "리뷰 반영"에 있다.

## 환경

| 항목 | 값 |
|---|---|
| 머신 | Apple M4(코어 10개, 성능 4 + 효율 6), 메모리 16GiB, macOS 26.4.1 |
| Python | 3.12.13, venv `~/mock_venv`, `pip install -e tools/mock_inference[checks]` |
| 서버 의존 | numpy 2.5.3, uvicorn 0.54.0, uvloop 0.22.1, httptools 0.8.0, orjson 3.12.0, xxhash 4.0.1, pyarrow 25.0.1 |
| 검사 의존 | openai 3.20.0, cohere 7.2.0, httpx 0.28.1, oha 1.16.0 |
| D7 venv | `~/Projects/MemMachine/mm_speedkick/.venv`(memmachine_server 포함) |
| 기타 | `ulimit -n` 1,048,576. 작업 디렉터리 `/tmp/mockinf`. 명령은 `tools/mock_inference/`에서 실행. `oha`와 서버가 같은 호스트(loopback). |

## 결과

| 단계 | 판정 | 비고 |
|---|---|---|
| D0 환경 | PASS | |
| D1 합성 벡터 | PASS | |
| D2 기동과 curl | PASS | |
| D3 SDK 왕복 | PASS | |
| D4 여러 worker 순서 | PASS | 100만 행 파일로 실행. 20만 행으로는 설계대로 실행해도 wrap 해서 실패한다(아래 설명). |
| D5 변환기 | PASS | 세 variant, 재개, `--verify-only` |
| D6 worker 계산과 처리량 명령 | PASS | 숫자는 로컬(참고) |
| D7 MemMachine 리소스 매니저 | PASS | `--workers 1 --reset` 서버 |
| D8 해시 모드와 range | PASS | |

단위 테스트 `tests/test_vecstream.py` 8건도 통과했다(`python -m unittest discover -s tools/mock_inference/tests`). 리뷰 반영 뒤에는 `tests/test_serve.py` 1건이 더해져 9건이다.

### D0 환경

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `python -m mock_inference --help` | subcommand `serve, convert, info, synth, synth-parquet` 5개 | PASS |
| `importlib.metadata`로 의존 버전 확인 | 위 환경 표의 버전. `oha 1.16.0` | PASS |

### D1 합성 벡터

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `synth --rows 200000 --dim 768 --seed 42 --out /tmp/mockinf/synth_768_200k.npy` | `wrote ...: 200000 rows x 768 dims`, 1.1초 | PASS |
| `info /tmp/mockinf/synth_768_200k.npy` | `rows 200000, dim 768, dtype <f4, data offset 128, data bytes 614400000, file size 614400128 (matches)`, 종료 코드 0 | PASS |
| 같은 명령으로 한 번 더 만들어 `cmp` | 종료 코드 0(바이트 단위 동일) | PASS |

### D2 기동과 curl

서버: `serve --vectors /tmp/mockinf/synth_768_200k.npy --workers 2 --port 8000`. 상태 파일이 없는 상태에서 띄웠다.

| 요청 | 핵심 출력 | 판정 |
|---|---|---|
| `GET /health` | `dim 768, total 200000, mode sequential, range [0,200000], next 0, wraps 0, workers 2, chunk 20000, platform darwin, affinity null` | PASS |
| `GET /v1/models` | `mock-embed`, `mock-rerank` 두 항목 | PASS |
| 임베딩 `encoding_format: float` | 실수 768개, `usage {prompt_tokens 1, total_tokens 1}`, `model`은 요청값 그대로 | PASS |
| 임베딩 기본 | `embedding`이 길이 4,096인 base64 문자열. 복원하면 float32 768개, 노름 1.0000 | PASS |
| rerank 3건 (`/v2/rerank`) | `index 0, 1, 2`에 점수 `1.0, 0.6667, 0.3333` | PASS |
| `/v1/rerank`, `top_n 2`, `return_documents true` | 결과 2개, 각각 `document.text` 포함 | PASS |
| `/rerank`, 문서가 `{"text": ...}` 객체 | 결과 2개, 점수 `1.0, 0.5` | PASS |
| `dimensions: 1536` | HTTP 400, `{"error":{"message":"dimensions 1536 not supported; this mock serves 768-dim vectors","type":"invalid_request_error","param":null,"code":null}}` | PASS |
| JSON 아닌 본문, 빈 `input` | 각각 HTTP 400과 OpenAI 형식 오류 본문 | PASS |
| 토큰 id 리스트의 리스트 `[[1,2,3],[4,5]]` | 벡터 2개, `prompt_tokens 5` | PASS |
| `GET /nope`, `POST /health`, `GET /v1/embeddings` | 404 `{"message":"no route for /nope"}`, 405, 405 | PASS |
| 요청 뒤 `GET /health` | `next 20000` | PASS |

### D3 SDK 왕복

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `python checks/sdk_roundtrip.py --base http://127.0.0.1:8000 --vectors /tmp/mockinf/synth_768_200k.npy` | base64(`dimensions=768` 포함), float, SDK 기본의 벡터가 각각 행 `[4,5]`, `[6,7]`, `[8]`과 바이트 단위로 같음. rerank `index [0,1,2]`, 점수 내림차순, 검증 호출 `rerank("a", ["a","b"])` 통과. 마지막 줄 `PASS sdk_roundtrip`, 종료 코드 0 | PASS |

### D4 여러 worker 순서

먼저 설계 문서에 적힌 대로 20만 행 파일로 실행했다. 첫 실행부터 `wraps 1`이 되어 중복 3,161개가 나왔고 두 번째 실행은 `wraps 2`였다. 원인은 코드가 아니라 규모다. 연결이 worker 8개에 고르게 나뉘지 않아 첫 실행에 lease가 10회(200,000행) 필요했고, 재시작 뒤에는 worker마다 새 lease가 필요하므로 160,000행이 더 있어야 한다. 그래서 100만 행 파일을 만들어 다시 했다. 설계 문서 §14 D4와 §16을 그에 맞게 고쳤다.

서버: `serve --vectors /tmp/mockinf/synth_768_1m.npy --workers 8 --port 8000`. 두 번째 실행 전에 Ctrl-C(SIGINT)로 죽이고 같은 명령으로 다시 띄웠다(`--reset` 없음).

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `synth --rows 1000000 --dim 768 --seed 42 --out /tmp/mockinf/synth_768_1m.npy` | 5.3초, `info` 크기 일치(3,072,000,128바이트) | PASS |
| 첫 실행 `stream_check.py --clients 64 --total 100000 --out /tmp/mockinf/run1.json` | `next 0 -> 240000`, 받은 벡터 100,000, 전부 파일 행과 일치, 중복 0, `wraps 0`, 누락 140,000 ≤ 160,000, 최대 행 223,262. `PASS stream_check` | PASS |
| 재시작 뒤 `/health` | `next 240000, wraps 0` | PASS |
| 두 번째 실행 `--after /tmp/mockinf/run1.json` | `next 240000 -> 460000`, 중복 0, `wraps 0`, 누락 120,000 ≤ 160,000, 최소 행 240,000 > 223,262. `PASS stream_check (restart)` | PASS |

### D5 변환기

기준 파일은 `synth --rows 30000 --dim 768 --seed 42 --out /tmp/mockinf/ref_768_30k.npy`다. variant마다 `--out-dir`과 `--out`을 달리 했다(`pq`/`conv_768.npy`, `pq_list32`/`conv_list32.npy`, `pq_largelist64`/`conv_largelist64.npy`). 같은 `--out`을 다시 쓰면 `.done` 표시 때문에 건너뛰기 때문이다.

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `synth-parquet --files 3 --rows-per-file 10000 --dim 768 --seed 42 --row-group-size 4000 --schema-variant largelist32 --out-dir /tmp/mockinf/pq` 후 `convert --parquet-glob "/tmp/mockinf/pq/*.parquet" --out /tmp/mockinf/conv_768.npy --jobs 3` | `plan: 3 files, 30000 rows x 768 dims, column 'emb' (float32)`, `write` 3건, 550MB/s, `verify PASS 100/100 rows, norm min 1.000000 max 1.000000 mean 1.000000`. `cmp` 종료 코드 0 | PASS |
| 같은 절차, `list32` | `column 'emb' (float32)`, `write` 3건, verify PASS, `cmp` 0 | PASS |
| 같은 절차, `largelist64` | `column 'emb' (float64)`, `write` 3건, verify PASS, `cmp` 0(float32로 되돌리면 동일) | PASS |
| parquet 스키마 확인 | `id: int64`, `emb: large_list<float>` / `list<float>` / `large_list<double>`, row group `[4000, 4000, 2000]`, 파일 01의 `id` 10000..19999 | PASS |
| `rm conv_768.npy.done/synth-01-of-03.parquet.ok` 후 같은 `convert` | `skip synth-00-of-03.parquet`, `skip synth-02-of-03.parquet`, `write synth-01-of-03.parquet rows=10000`, verify PASS, `cmp` 0 | PASS |
| `convert ... --out /tmp/mockinf/conv_768.npy --verify-only` | `verify PASS 100/100 rows`, 종료 코드 0 | PASS |
| (리뷰 반영 뒤 추가) 글롭을 `synth-0[01]-of-03.parquet`로 바꿔 같은 `--out`으로 `convert` | `<out>.plan.json differs from the new plan (files, rows or column changed); delete ... to start over`, 종료 코드 1. 계획이 같으면 전과 같이 `skip` 3건 | PASS(의도한 동작) |

### D6 worker 계산과 처리량 명령

서버: `serve --vectors /tmp/mockinf/synth_768_200k.npy --target-rps 3000 --cores 0-4`.

| 확인 | 핵심 출력 | 판정 |
|---|---|---|
| 시작 로그 | 첫 줄 `WARNING: core pinning is not supported on darwin; ignoring --cores`, 이어서 `serving ...: 200000 rows x 768 dims, range 0:200000, mode sequential, workers 3, affinity None` | PASS |
| `GET /health` | `workers 3, affinity null` | PASS |
| `oha` 두 명령 | 둘 다 정상 종료, 오류 응답 0, 상태 코드 전부 200 | PASS |
| `oha` 뒤 `/health` | `next 120000, wraps 21`. lease 총량 3,860,000행이 응답 수 3,839,342에 아직 안 준 최대 60,000행을 더한 범위 안에 있다 | PASS |

처리량은 다음과 같다. 모두 **로컬(참고)** 값이다. `-z 30s -c 64 --no-tui`, worker 3개, 클라이언트와 서버가 같은 호스트다. "마감 중단"은 30초가 끝나는 순간 진행 중이던 요청으로 오류가 아니다.

| 경로 | 요청 수 | RPS | p50 | p99 | 최대 | 오류 |
|---|---|---|---|---|---|---|
| `POST /v1/embeddings`(입력 1개, 응답 4.16KiB) | 3,839,342 | 127,954 | 0.454ms | 1.355ms | 10.5ms | 0(마감 중단 55) |
| `POST /v2/rerank`(`checks/rerank80.json`, 문서 80개) | 1,511,654 | 50,383 | 1.184ms | 2.183ms | 4.7ms | 0(마감 중단 64) |

worker 하나로 나누면 임베딩 약 42,000 RPS, rerank 약 16,800 RPS다. 설계 §10.1의 추정(프로세스당 2,000에서 3,000 RPS와 700에서 1,000 RPS)보다 훨씬 높지만, 이 값은 M4 성능 코어와 loopback에서 나온 것이라 사내 C4 실측으로 바꿔야 한다. `--rps-per-worker` 기본값 1,000은 그대로 두었다.

### D7 MemMachine 리소스 매니저

서버: `serve --vectors /tmp/mockinf/synth_768_200k.npy --workers 1 --reset`. D6의 `oha`가 스트림을 여러 번 wrap 시켰으므로 새로 띄웠다. 설계 문서 §14 D7에 이 점을 적었다.

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `.venv/bin/python checks/mm_resource_check.py --config checks/mm_mock_config.yml --health http://127.0.0.1:8000/health` | 로그에 `Validating embedder 'mock_embedder' is working.`, `Embedder 'mock_embedder' is valid.`, `Validating reranker mock_reranker is working.`, `Reranker mock_reranker is working.` 네 줄. `ingest_embed` 결과 벡터 2개 길이 768, `score` 내림차순 `[1.0, 0.667, 0.333]`, `next 20000`(lease 1회). 마지막 줄 `PASS mm_resource_check`, 종료 코드 0 | PASS |
| 실행 뒤 `GET /health` | `next 20000, wraps 0` | PASS |

stderr에 `Decomposer import FAILED ... No module named 'spacy'` traceback이 먼저 찍히는데, 이것은 speedkick venv에서 `memmachine_server`를 import 하면 항상 나오는 기존 현상이다. 설정의 `logging.path` 때문에 실행 디렉터리에 `mm_resource_check.log`가 생기므로 실행 뒤 지웠다.

### D8 해시 모드와 range

| 명령 | 핵심 출력 | 판정 |
|---|---|---|
| `serve --vectors /tmp/mockinf/synth_768_200k.npy --mode hash`, 같은 텍스트 두 번 임베딩 | 두 base64 문자열이 같다. 다른 텍스트는 다르다. `/health`에 `mode hash`, `next`와 `wraps` 없음 | PASS |
| `serve --vectors /tmp/mockinf/synth_768_200k.npy --range 100000:200000 --reset`, `/health` | `range [100000,200000], next 100000` | PASS |
| 임베딩 요청 1건 뒤 `/health` | `next 120000`. 상태 파일 `{"next": 120000, "wraps": 0, "start": 100000, "end": 200000}` | PASS |
| (추가) 위 상태 파일을 둔 채 `--range` 없이 다시 기동 | `RuntimeError: /tmp/mockinf/synth_768_200k.state.json covers rows 100000:200000, not 0:200000; start with --reset to replace it`로 기동 거부. 처음 기록은 `--workers 1`이었다. 리뷰에서 worker 2개 이상이면 거부가 worker 안에서 일어나 uvicorn이 죽은 worker를 계속 다시 띄우는 문제가 발견되어 부모 프로세스가 먼저 확인하도록 고쳤고, `--workers 2`로 다시 돌려 1초 안에 종료 코드 1, worker 기동 없음, 포트 미점유를 확인했다 | PASS(의도한 동작) |

## 실행 중 고친 것

`checks/stream_check.py`의 누락 행 계산이 재시작 실행에서 틀렸다. 누락을 `[start, next)` 전체에서 세어, 재시작 뒤 실행에서는 첫 실행이 소비한 행까지 누락으로 잡혀 `260000 <= 160000`으로 실패했다. 실행 직전에 `/health`의 `next`를 읽어 두고 이번 실행이 소비한 구간 `[실행 전 next, 실행 후 next)`에서만 세도록 고쳤다. 새 서버에서는 실행 전 `next`가 `start`라 첫 실행의 판정은 그대로다. 설계 문서 §13 검증 3의 문구도 같이 고쳤다.

서버, 변환기, 합성기 코드는 고칠 것이 없었다.

## 설계 문서와 코드가 다른 점, 문서 수정

아래는 코드가 설계 문서 초안과 다르게 된 곳이다. 모두 설계 문서 쪽을 최소로 고쳐 코드와 맞췄다.

| 절 | 코드의 동작 | 문서 수정 |
|---|---|---|
| §5 표 | `deploy/mock-inference.service`는 C9의 산출물 | `§15 C8`을 `§15 C9`로 |
| §7.2 1단계 | 이미 있는 `<out>.plan.json`이 새 계획과 다르면 끝낸다(리뷰 반영) | 그 문장을 더함 |
| §7.2 2단계 | 출력 파일이 이미 있으면 모양이 계획과 같을 때만 그대로 쓴다. 덮어쓰면 재개가 깨지기 때문 | 그 문장을 더함 |
| §7.2 4단계 | `--verify-only`는 `<out>.plan.json`을 읽는다 | 그 문구를 더함 |
| §8.1 | 상태 파일 이름이 `<npy 이름>.state.json`, `<npy 이름>.state.lock`. 없으면 시작 때 만든다 | 실제 이름을 적고, 문서의 `state.json`은 약칭이라고 밝힘 |
| §8.2 | 상태 파일의 `start:end`가 `--range`와 다르면 기동을 거부한다. 확인은 부모 프로세스가 worker를 띄우기 전에 한다(리뷰 반영) | 항목 하나를 더함 |
| §17 | `--reset`은 순차 모드에서만 상태 파일을 쓴다(리뷰 반영) | `--reset` 행에 괄호 설명 |
| §9.4 | 해시 모드의 `/health`에는 `next`, `wraps`가 없다 | 그 문장을 더함 |
| §10.2 | `uvicorn.run`에 `lifespan="off"`를 준다 | 인수를 더함 |
| §11 | `mm_mock_config.yml`에 파서가 요구하는 절(`logging.path`, `session_manager`, `episode_store`, `semantic_memory.config_database`)이 더 있다. `databases` 절은 필요 없다 | 그 설명을 더함 |
| §13 검증 3 | 누락은 이번 실행이 소비한 구간에서 센다 | `[start, next)`를 `[실행 전 next, 실행 후 next)`로 |
| §13 검증 6 | `next == start + CHUNK`는 `--workers 1`일 때 | 괄호 설명을 고침 |
| §14 D4 | 100만 행 합성 파일을 쓴다 | 명령과 이유를 적음 |
| §14 D7 | 서버를 `--workers 1 --reset`으로 새로 띄우고 `--health`를 준다 | 명령을 고침 |
| §16 | D4의 근거가 합성 100만 행 | `20만 행`을 `100만 행`으로 |

## 리뷰 반영

가독성 리뷰와 설계 준수 리뷰의 지적을 반영한 뒤 D2, D3, D4, D5(largelist32), D8을 포트 8020에서 `--reset`으로 다시 돌렸고 전부 PASS였다. 단위 테스트는 9건 통과다. 동작이 바뀐 것은 다음과 같다.

| 곳 | 전 | 후 |
|---|---|---|
| `serve` 기동 | 상태 파일의 구간이 `--range`와 다르면 worker 안에서 실패했다. worker 2개 이상이면 uvicorn이 죽은 worker를 계속 다시 띄워 포트가 잡힌 채 응답이 없었다 | 부모 프로세스가 `vecstream.ensure_state`로 먼저 확인하고 종료 코드 1로 끝낸다. `--state-dir`이 없는 디렉터리일 때도 같다 |
| `serve --mode hash --reset` | 해시 모드인데도 상태 파일을 썼다 | 순차 모드에서만 `--reset`과 상태 확인을 한다 |
| `serve` 옵션 | `--workers 0`, `--rps-per-worker 0`, `--cores 3-1`이 조용히 넘어가거나 원인 없는 오류를 냈다 | 각각 `ValueError`로 옵션 이름과 조건을 말한다 |
| `convert` 재개 | 글롭이 바뀌어 파일의 시작 행이 달라져도 이름이 같은 파일을 건너뛰었다. 표본 검증이 잡지 못할 수 있다 | 기존 `<out>.plan.json`이 새 계획과 다르면 지우고 다시 시작하라는 메시지로 끝낸다 |
| `convert` 오류 | `--vector-column nope`, 계획 없는 `--verify-only`가 traceback이었다 | 열 목록 또는 다음 할 일을 말하는 한 줄 메시지 |
| `/v1/embeddings` | `encoding_format: ""`가 base64로 통과했고, `[true,false]`, `[[]]`, `[[1.5]]`가 토큰 id로 통과했다 | 모두 400. `top_n: true`도 400 |

검사 스크립트와 테스트는 동작이 아니라 구조만 바뀌었다. `checks/_rows.py`는 `open_vectors`, `parse_range`를 `mock_inference.vecstream`에서 가져오고, `tests/test_vecstream.py`의 `info` 테스트는 `/tmp/mockinf` 파일 대신 테스트가 만드는 파일을 쓴다.

## 남은 것

- 코어 고정(`affinity`), 10,000 RPS와 p99, MemMachine 실사용(Qdrant 저장 벡터 대조), systemd 배포는 설계 §16대로 사내 Linux에서만 확인할 수 있다. §15의 C0부터 C10을 따른다.
- `checks/qdrant_row_check.py`는 Qdrant가 없어 인수 파싱과 `.npy` 해시 색인만 확인했다(설계 §18 K7).

## 부록 A. `oha` 원문(로컬, 참고)

임베딩:

```
Summary:
  Success rate:	100.00%
  Total:	30005.9556 ms
  Slowest:	10.5098 ms
  Fastest:	0.0536 ms
  Average:	0.4988 ms
  Requests/sec:	127954.4985

  Total data:	15.22 GiB
  Size/request:	4.16 KiB
  Size/sec:	519.34 MiB

Response time distribution:
  10.00% in 0.3309 ms
  25.00% in 0.3757 ms
  50.00% in 0.4541 ms
  75.00% in 0.5507 ms
  90.00% in 0.7018 ms
  95.00% in 0.8588 ms
  99.00% in 1.3553 ms
  99.90% in 2.1807 ms
  99.99% in 3.2211 ms

Status code distribution:
  [200] 3839342 responses

Error distribution:
  [55] aborted due to deadline
```

rerank(`checks/rerank80.json`):

```
Summary:
  Success rate:	100.00%
  Total:	30004.7506 ms
  Slowest:	4.6728 ms
  Fastest:	0.2061 ms
  Average:	1.2687 ms
  Requests/sec:	50382.6218

  Total data:	4.78 GiB
  Size/request:	3.31 KiB
  Size/sec:	163.02 MiB

Response time distribution:
  10.00% in 1.0578 ms
  25.00% in 1.1033 ms
  50.00% in 1.1837 ms
  75.00% in 1.4177 ms
  90.00% in 1.5111 ms
  95.00% in 1.6054 ms
  99.00% in 2.1831 ms
  99.90% in 3.0605 ms
  99.99% in 3.6933 ms

Status code distribution:
  [200] 1511654 responses

Error distribution:
  [64] aborted due to deadline
```

## 부록 B. D4를 20만 행 파일로 실행한 기록

설계 문서 초안대로 `synth_768_200k.npy`, `--workers 8`, `--total 100000`으로 실행한 결과다. D2, D3 뒤라 시작 `next`는 20,000이었다.

```
첫 실행:  health: next 40000, workers 8, chunk 20000, wraps 1
          FAIL no row served twice: 3161 duplicates
          FAIL stream did not wrap: wraps 1
두 번째:  health: next 60000, workers 8, chunk 20000, wraps 2
          FAIL restart: all rows beyond previous run: 0 > 199999
```

중복은 wrap 뒤 같은 행을 다시 준 것이며, wrap이 없는 100만 행 실행에서는 중복이 0이다.

## 2차 수정 검증

코드 리뷰에서 나온 지적을 고친 뒤, 그 수정이 실제로 맞는지 다시 확인한 기록이다. 단위 테스트 21건이 모두 통과했고, `guide_2026-09-29.md` §2.1부터 §2.8까지를 포트 8230에서 격리된 `--state-dir`로 그대로 따라 해 전부 문서와 같은 출력을 확인했다. 막혔던 지적 6건을 개별로 다시 확인했고 전부 의도한 대로 동작했다. 그 과정에서 설계 문서 §17이 코드와 어긋난 곳을 발견해 고쳤다(아래 "문서 불일치" 참고).

| 확인 | 결과 |
|---|---|
| 단위 테스트(`unittest discover`, 21건) | PASS |
| `compileall` | PASS |
| 가이드 §2.1–§2.8(포트 8230) | 전부 PASS, 문서와 실제 출력 일치 |
| `--chunk 0` 거부 | PASS: `error: --chunk must be >= 1`, exit 2 |
| 서비스 중 상태 파일 삭제 | PASS: 503 JSON, 로그에 요청당 한 줄 `ERROR` |
| 이미 점유된 포트로 기동 | PASS: `error: port already in use: ...`, exit 2 |
| `python -m mock_inference reset` | PASS: `next`가 20000에서 0으로 |
| `fixed_size_list` parquet 변환 | PASS(`test_convert.py::test_fixed_size_list`) |
| `qdrant_row_check` 코사인 매처 | PASS: 스케일된 행은 `1-cos 0.0`, 무작위 잡음은 `1-cos 0.89` |

### 문서 불일치, 고친 것

- 설계 문서 §17: "상태를 처음부터 다시 시작하는 것은 더 이상 `serve`의 옵션이 아니다"와 "exit 3"이 코드와 달랐다. `serve --reset`은 여전히 동작하고(가이드 전체가 그렇게 쓴다), 포트 충돌 시 종료 코드는 2다. 문단을 고치고 옵션 표에 `--reset` 행을 더했다.
- 설계 문서 §17: `--chunk` 0 이하일 때 "worker가 응답 없이 멈춘다"는 옛 설명이었다. 지금은 기동 시점에 `error: --chunk must be >= 1`로 바로 거부한다. 문구를 고쳤다.
- 설계 문서 §7.2 1단계: 벡터 열 자동 인식이 `list<float>`, `large_list<float>`만 적혀 있었다. 코드와 가이드 §3.3 모두 `fixed_size_list<float>`도 받으므로 그 타입을 더했다.
- 가이드 §2.6(두 곳): 변환기의 `verify PASS` 줄이 이제 `(seed 12345)`를 포함하는데 예시 출력에는 빠져 있었다. 두 곳 모두 추가했다.

`RSS`/`RssFile`/`RssAnon`, `-q 10000 --latency-correction`, `MEMORY_CONFIG`는 설계 문서와 가이드 모두 코드/MemMachine 동작과 일치해 고칠 것이 없었다.
