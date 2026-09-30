# mock_inference 사내 서버 검증 (2026-09-29, sc)

M4 개발 머신의 `verification_2026-09-29.md`에 이은, **사내 Linux 서버(sc) 실측 기록**이다. 가이드 `guide_2026-09-29.md` §1~§5를 그대로 따랐고, guide에 없던 함정 5개를 발견해 반영했다(마지막 절). 설계 §15의 C 항목 기준으로 §2(로컬 드라이런)~§5(MemMachine 연결)까지가 이 문서의 범위다. 코드는 `88ef5a1` + 본 문서 하단의 검사 스크립트 수정 1건.

## 환경

| 항목 | 값 |
|---|---|
| 머신 | Linux x86_64, 344스레드(2소켓), NVMe 2개: nvme0n1(`/mnt/raw`, 데이터셋) / nvme1n1(`/mnt/bench`, 출력). NVMe는 NUMA node2(cpulist 86-128) |
| Python | 3.12.3, `tj_mm/.venv`(uv venv, pip 없음). `uv pip install --python .venv/bin/python -e "tools/mock_inference[checks]"` |
| 서버 의존 | pyarrow 25.0.1, uvloop 0.22.1, httptools 0.8.0 외 (numpy/uvicorn/orjson/xxhash는 기존) |
| mock 포트 | **8230** (8000/8001은 이 서버의 vLLM이 점유 중이라 회피) |
| Qdrant | 격리 컨테이너 `mockinf-qdrant` (qdrant:1.19.1-baseline, 호스트 6443→6333, `--ulimit nofile=65536:65536`, 볼륨 `mockinf_qdrant_data`). **공유 Qdrant(6333)와 qdrant-instr(6399)는 사용 안 함** |
| oha | 1.16.0 GitHub 릴리스 바이너리 → `~/.local/bin/oha`. 서버와 **같은 호스트** 측정(원칙은 다른 호스트라 수치는 보수적으로 해석) |
| 코어 고정 | mock은 node2 물리 코어(`--cores`), oha는 `taskset`으로 다른 노드(0-11) |
| 주의 | 시스템 CA 번들(`/etc/ssl/certs/ca-certificates.crt`)에 훼손 블록 2개 → TLS 쓰는 클라이언트(SDK/oha)는 매 터미널 `export SSL_CERT_FILE=$(certifi)` + `unset SSL_CERT_DIR` 필요 |

## §2 드라이런 (합성 데이터, 가이드 §2.1~§2.8)

전 단계 PASS. M4 문서와 다른 점은 포트 8230과 SSL 우회뿐이고 출력은 문서와 일치했다.

| 단계 | 확인 | 판정 |
|---|---|---|
| §2.1 synth/info | `200000 rows x 768 dims`, `(matches)` | PASS |
| §2.2 serve | workers 2, affinity null | PASS |
| §2.3 curl 5종 | float/base64/rerank/차원 400/`next` lease | PASS (값이 M4와 동일한 건 동일 시드 파일 때문) |
| §2.4 sdk_roundtrip | ok 8건, `rows [20000, 20001]` | PASS |
| §2.5 stream_check | 첫 실행 `PASS`(중복 0, 누락 80000≤160000), 재시작 `PASS (restart)`(180000 > 160274) | PASS |
| §2.6 convert+재개 | `cmp` SAME, `.ok` 삭제 후 `skip 2 + write 1` | PASS |
| §2.7 mm_resource_check | 검증 4줄 + `PASS` (다음으로 이 venv가 MemMachine venv를 겸함) | PASS |
| §2.8 hash / --range | 같은 문장 동일 벡터, `next 100000→120000` | PASS |

## §3 laion 실데이터 변환

```
plan: 100 files, 100000000 rows x 768 dims, column 'emb' (float32)
done: 100000000 rows x 768 dims, wrote 100000000 rows in 134.0s (2293 MB/s)
verify PASS 100/100 rows (seed 12345), norm min 0.999541 max 1.000475 mean 0.999994
```

- 출력 `/mnt/bench/vectors/laion_100m.npy` 307,200,000,128바이트, `info` 일치
- 읽기 nvme0n1 / 쓰기 nvme1n1 분리, `--jobs 12`. **쓰기 134초 + verify 260초**(verify는 표본 100행이지만 랜덤 위치의 parquet row group을 읽어 쓰기의 2배). 전체 약 6.5분
- 참고: 스키마 `id int64`, `emb large_list<float32>`, 파일당 100만 행

## §4 처리량 (laion_100m.npy, worker 1~2)

**§4.1 closed-loop 포화** (`-z 60s -c 512`, worker 1개, 코어 86-88, 같은 호스트라 보수치):

| 경로 | RPS | p50(평균) | 비고 |
|---|---|---|---|
| `/v1/embeddings` | 22,074 | 23.1ms(포화 대기) | 100% 200 |
| `/v2/rerank`(문서 80) | 7,584 | 67.4ms(포화 대기) | 100% 200 |

worker 1개당 rerank 약 7,600이 병목. 10,000 RPS 목표 → `ceil(10000/(7600*0.8)) = 2` worker.

**§4.2/§4.3 open-loop 확인** (`-q 10000 -c 512 --latency-correction -z 60s`, worker 2, `--cores 86-89`, oha는 `taskset -c 0-7`):

| 경로 | Requests/sec | p50 | p99 | 오류 |
|---|---|---|---|---|
| embeddings | 9,999 | 0.618ms | **1.712ms** | 0 (마감 중단 2) |
| rerank80 | 10,000 | 1.096ms | **13.076ms** | 0 (마감 중단 6) |

합격(p99 ≤ 20ms, 목표 RPS 정확 달성). **단일 호스트 측정임을 반드시 명시** — 다른 호스트에서 재면 RPS 상한은 더 높게 나올 것이다. M4의 worker당 42k/17k는 이 서버에서 재현되지 않았다(코어 성능 차이 + loopback).

## §5 MemMachine 연결

- **§5.2** mm_resource_check laion 파일 대상 PASS. **첫 실행에서 FAIL 1건** → 검사 스크립트 결함으로 판정·수정(아래 "고친 것")
- **§5.3** DB 없는 이벤트 경로(guide에 추가한 sqlite+격리 Qdrant 방법)로 `memmachine-server` 기동 → `Starting server with 1 worker` + `Semantic memory is disabled` 확인. add 1건 → `{"results":[{"uid":"1"}]}`, search 1건 → `score 1.0`. `qdrant_row_check`: `point -> row 0 (1-cos -1.2e-07)`, `PASS`. 첫 add가 0번 행 = 문서와 일치
- **§5.4** `/api/v2/memories` add를 oha로 20 RPS × 60초 = **1,200건 100% 200** (p99 29.8ms), MemMachine 로그 오류 0(spacy traceback은 기동 시 기존 현상). mock `next`는 20000에서 안 뛰었지만 lease(20,000행) 안에서 소비됐기 때문으로 정상

## 오늘 고친 것 / 가이드 반영

| 것 | 내용 |
|---|---|
| `checks/mm_resource_check.py` | `next` 델타 검사가 "lease 1회 이상"을 요구해 **따뜻한 서버에서 오탐 FAIL**(검증 호출이 기존 lease 안에서 소화되면 델타 0이 정상). `0 <= leases <= workers`로 수정, 가이드 §5.2/§7 문구 반영. 2026-09-29 실측 |
| guide §1.2 | uv venv에는 pip이 없다 → `uv pip install --python .venv/bin/python -e ...` 안내 추가 |
| guide §2.2 | 포트 충돌 시 점유 확인 명령과 빈 포트 선택 안내 추가 |
| guide §5.3 | **postgres/neo4j 없이** 격리 Qdrant + sqlite로 §5.3을 수행하는 전체 설정 예 추가. Qdrant 컨테이너는 `--ulimit nofile` 필수(코어 많은 호스트에서 기동 panic — 실측) |
| guide §7 | SSL CA 번들 훼손(§1.2와 같은 원인)에 대한 SDK/oha 우회법 2줄 추가 |

## 재현 명령 요약

```bash
VENV=/home/tj/Workspace/ltm/memmachine/tj_mm/.venv
export SSL_CERT_FILE=$($VENV/bin/python -c "import certifi; print(certifi.where())"); unset SSL_CERT_DIR
ulimit -n 65536
# 변환된 데이터: /mnt/bench/vectors/laion_100m.npy (변환 로그 /tmp/mockinf/convert_laion.log)
$VENV/bin/python -m mock_inference serve --vectors /mnt/bench/vectors/laion_100m.npy \
  --workers 2 --port 8230 --cores 86-89            # 부하 전 --reset은 새 시험일 때만
~/.local/bin/oha -z 60s -c 512 -q 10000 --latency-correction --no-tui -m POST \
  -H 'content-type: application/json' -d '{"input":["hello"],"model":"m"}' http://127.0.0.1:8230/v1/embeddings
# §5.3: /tmp/mockinf/mm_server_mock_53.yml + MEMORY_CONFIG 로 memmachine-server 기동
# 격리 Qdrant: docker start mockinf-qdrant
```

## 남은 것 (사내 절차 기준)

- systemd 등록(guide §6) — 이 서버에서는 tmux/nohup 구간 그대로 둠. 등록 시 `--reset` 금지, `User=` 주의
- msmarco 1536 변환과 그 축의 측정 (`/mnt/raw/msmarco_v2_138M` 수신·검증은 09-28 완료, 794GB → .npy 850GB 변환 대기)
- 다른 호스트에서 재는 처리량(원칙 준수 측정)
- Qdrant/MemMachine 병목 측정 본판(5단계) — mock 트래픽과 측정 대상이 물리적으로 분리된 창에서
