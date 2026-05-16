# LongMemEval Temporal Reasoning 평가 — 초심자 가이드

처음 저장소를 받은 사람이 기본 설정으로 LongMemEval의 `temporal-reasoning`
카테고리만 평가하기 위한 단계별 절차. 분량 최소화.

## 0. 사전 준비

- Python 3.12+
- Docker (Neo4j + Postgres 용)
- OpenAI API key

## 1. 저장소 clone + 브랜치

```bash
git clone https://github.com/taejin-oh/MemMachine.git
cd MemMachine
git checkout eval_optimize
```

## 2. 의존성 설치

```bash
uv sync --all-extras
```

`--all-extras` 가 `sentence-transformers` (embedder) 까지 설치.

## 3. 데이터셋 다운로드 (~265MB)

```bash
uv run python -c "
from huggingface_hub import hf_hub_download
import shutil
src = hf_hub_download(
    repo_id='xiaowu0162/longmemeval-cleaned',
    repo_type='dataset',
    filename='longmemeval_s_cleaned.json',
)
shutil.copy2(src, 'evaluation/data/longmemeval_s_cleaned.json')
"
```

500 문항. 파일은 `.gitignore` 대상.

## 4. 비밀번호 / API 키 채우기

eval pipeline 은 docker 의 MemMachine 서버 컨테이너를 사용하지 않음 —
`packages/server` 코드를 in-process 로 import 해서 Neo4j/Postgres 에 직접
붙음. 그래서 DB 만 띄우면 충분하고, 손볼 설정도 두 개로 줄어듦.

**(필수) `configs/profiles/models/main.yaml`** — `<GEMINI_API_KEY>` 를
실제 키로 교체. 발급: https://aistudio.google.com/apikey
- embedder 는 로컬 `sentence-transformer` (`BAAI/bge-base-en-v1.5`) — API 키 없음.

**(필수) `configs/profiles/dbs/main.yaml`** — `<NEO4J_PASSWORD>`,
`<POSTGRES_PASSWORD>` 를 docker compose 의 DB password 와 일치시켜야 함.
기본값을 그대로 쓸 거면:
- `<NEO4J_PASSWORD>` → `neo4j_password`
- `<POSTGRES_PASSWORD>` → `memmachine_password`

`.env` 는 선택. 만들 거면 `cp sample_configs/env.dockercompose .env` —
하지만 docker-compose.yml 이 `${VAR:-default}` 형태라 `.env` 없어도 위
기본값으로 DB 가 뜸. 운영 환경이면 `.env` 와 `configs/profiles/dbs/main.yaml`
양쪽 다 강한 값으로 바꾸되 **반드시 일치**.

## 5. DB 띄우기

eval 만 할 거면 `memmachine` 서비스는 생략 — 이미지 pull (수 GB) 도 스킵
되어 훨씬 빠름:

```bash
docker compose up -d neo4j postgres
```

확인:

```bash
docker compose ps              # neo4j + postgres = Up (healthy)
docker compose logs neo4j      # 'Started.' 나오면 ready
```

Neo4j (`bolt://localhost:7687`) + Postgres (`localhost:5432`).

> MemMachine 서버 컨테이너까지 같이 띄우려면 `./memmachine-compose.sh start`
> — interactive prompt (CPU/GPU, provider) 와 root `configuration.yml`
> 생성이 같이 수행됨. eval pipeline 에는 불필요.

## 6. Run config + configuration.yml 생성

`scripts/generate_config.py` 가 `configs/problems/p0.yaml` (baseline) + `main`
profiles 를 merge 해서 run config + working configuration.yml 을 한 번에 만듦.

```bash
uv run python scripts/generate_config.py \
    --problem 0 \
    --run-name temporal_test \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt \
    --include-categories temporal-reasoning
```

산출:

- `configs/runs/temporal_test.yaml` — run config
- `configs/generated/temporal_test_configuration.yml` — working configuration.yml

> p0 default 와 차이는 두 가지:
> - `answer_prompt`: `edwin3` → `LME_origin_prompt` (xiaowu0162 upstream 그대로)
> - `include_categories`: 6 카테고리 → `temporal-reasoning` 만
>
> 나머지 (`search_limit=30`, `prefix=off`, `chunk=off`, `lenient`) 는 p0
> default 그대로. `include_categories` 는 retrieve/generate/judge/analyze 만
> 좁힘 — ingest 는 항상 500 문항 haystack 전체 적재 (retrieval competition 보존).

## 7. 평가 실행

```bash
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml
```

진행되는 단계 (모두 자동):

| Stage | 처리 |
|---|---|
| `ingest` | 500 문항 haystack 을 Neo4j 에 적재 (idempotent) |
| `retrieve` | `temporal-reasoning` 127 문항 검색 (abstention 6 제외) |
| `generate` | retrieve loop 에서 답변 생성 |
| `judge` | LongMemEval temporal template 으로 yes/no 채점 |
| `analyze` | accuracy 집계 |

## 8. 결과

```
results/temporal_test/
├── ingest.jsonl         # status=ok marker
├── retrieve.jsonl       # 검색된 episode + perf metrics
├── generate.jsonl       # 모델 답변
├── judge.jsonl          # llm_score + raw_response
└── analyze.json         # 카테고리별 정확도
```

요약 출력:

```bash
uv run python -c "
import json
d = json.load(open('results/temporal_test/analyze.json'))
for c in d['cells']:
    print(f\"n={c['n']}  accuracy={c['accuracy']:.4f}\")
    for cat, stats in c['by_category'].items():
        print(f\"  {cat}: {stats['accuracy']:.4f} (n={stats['n']})\")
"
```

## 9. 단계 선택 / Ingest 재사용

### `--stage` 로 일부 단계만 실행

순서: `ingest → retrieve → generate → judge → analyze` (쉼표 결합 가능).

```bash
# ingest 만
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml \
    --stage ingest

# 카테고리/k/prompt 바꿔 retrieve 부터 다시 (ingest skip)
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml \
    --stage retrieve,generate,judge,analyze

# 채점만 다시 (judge model 또는 yesno_policy 변경)
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml \
    --stage judge,analyze
```

각 stage 는 `results/{run_name}/{stage}.jsonl` 을 덮어씀. ingest 만 예외 —
`status=ok` 마커가 있으면 자동 skip.

### Ingest 재사용 (다른 problem 에서 동일 corpus 사용)

핵심: `session_id = eval_tool_longmemeval_{run_name}` — `run_name` 을
유지하면 Neo4j 의 ingest 가 그대로 재사용됨.

예: p0 baseline 으로 ingest 끝낸 뒤 p3 (prefix sweep) 로 동일 corpus 평가
(둘 다 `message_sentence_chunking: false` 라 호환):

```bash
# 1. baseline (p0) — ingest 포함 full pipeline
uv run python scripts/generate_config.py \
    --problem 0 --run-name temporal_test \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt \
    --include-categories temporal-reasoning
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml

# 2. prefix sweep (p3) — 같은 --run-name 으로 재생성
uv run python scripts/generate_config.py \
    --problem 3 --run-name temporal_test \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt \
    --include-categories temporal-reasoning
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml
# → ingest skip (results/temporal_test/ingest.jsonl status=ok 유지),
#   Neo4j 의 동일 session 재사용. retrieve 부터 새 sweep 으로 다시.
```

**제약**:

- **Ingest-affecting field 가 동일해야 함** — 현재 `message_sentence_chunking`
  하나. p0(off) ↔ p3(off) 호환, p0(off) ↔ p4(on) 비호환. 다르게 가려면 Neo4j
  비우고 (`docker compose down -v && docker compose up -d neo4j postgres`)
  새 ingest, 또는 다른 `--run-name` 사용.
- **다운스트림 파일 덮어쓰기** — 같은 `run_name` 재실행 시 `retrieve.jsonl` /
  `judge.jsonl` 등이 덮어써짐. 비교용으로 보존하려면 미리 백업:
  `cp -r results/temporal_test results/temporal_test_p0`.

### Analyze 만 재실행 (p6 / p12)

p6 (MS vs others 분해), p12 (token/accuracy Pareto) 는 다른 run 의
`judge.jsonl` 을 재해석하는 analyze-only problem. `--reuse-run` 으로 지정:

```bash
uv run python scripts/generate_config.py \
    --problem 6 --run-name temporal_p6 \
    --model-profile main --db-profile main \
    --reuse-run temporal_test
uv run python scripts/run_pipeline.py --config configs/runs/temporal_p6.yaml
```

`reuse_run` 이 세팅되면 `--stage` 가 자동으로 `analyze` 로 제한됨.

## 10. 트러블슈팅

- **Neo4j connection refused** — `docker compose ps` 확인 후 `docker compose restart neo4j`.
- **OpenAI rate limit** — `search_concurrency` 를 1 로 낮춰서 재실행.
- **ingest 중단 후 재실행** — `results/temporal_test/ingest.jsonl` 삭제 후 다시.
- **모든 점수 0** — `judge.jsonl` 의 `judge_raw_response` 확인 (JSON 파싱 실패 / 빈 응답 등).

## 다음 단계

- 다른 카테고리: `include_categories` 를 `["multi-session"]` 등으로 변경.
- k sweep: `sweep.search_limit: [10, 20, 30, 50, 100]`.
- prompt 비교: `evaluation.longmemeval.answer_prompt` 를 5 정책 중 선택.
- 전체 변수 목록은 `CLAUDE.md` 의 "Architecture — Evaluation" 섹션 참조.
