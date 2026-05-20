# LongMemEval — per-question 격리 평가 (MemMachine 백엔드) 가이드

`evaluation/longmemeval/` 의 `ingest.py` + `retrieve.py` 사용. upstream
LongMemEval `src/retrieval/run_retrieval.py` 의 per-question 격리 패턴을
우리 MemMachine 스택 (Neo4j vector graph store + Postgres,
configuration.yml 의 embedder + reranker) 위에서 재현. 단일 session 적재
(`scripts/run_pipeline.py`) 경로의 recall ~50% 문제를 해결한다.

각 질문이 `session_id = <prefix>_<question_id>` 에 격리 적재되어 검색
공간이 ~246k turn → ~500 turn 으로 축소 (~500 배). upstream / Edwin /
main `evaluation/episodic_memory/` 와 동일한 의미론.

### 독립성

`evaluation/longmemeval/` 는 `memmachine_server.*` (워크스페이스 패키지)
외엔 어떤 evaluation/ 트리도 import 안 함. `evaluation/retrieval_agent/` /
`evaluation/utils/agent_utils.py` / `scripts/stages/` 를 main 브랜치 상태로
되돌리거나 삭제해도 step 5a / 5b 는 그대로 동작.

단계별 의존성:

| 단계 | evaluation/longmemeval/ 만으로 가능? | scripts/ 필요? |
|---|---|---|
| 4. `generate_config.py` (워킹 yml 생성) | ❌ | ✅ |
| 5a. ingest | ✅ | ❌ |
| 5b. retrieve | ✅ | ❌ |
| 6. generate (답변 LLM) | ✅ | ❌ |
| 7. judge + 요약 | ✅ | ❌ |

→ step 4 (config 생성) 외엔 전부 본 디렉토리 안에서 완결. `evaluation/` 의
다른 디렉토리 (`retrieval_agent/`, `utils/`, `episodic_memory/` …) 와
`scripts/{regen_answer,run_pipeline}` 은 import 하지 않음 — 통째로
main 브랜치 상태로 되돌려도 본 평가 흐름은 정상 동작.

## 0. 코드 받기 + 의존성

```bash
git pull origin eval_optimize
uv sync --all-extras
```

## 1. DB 띄우기

```bash
docker compose up -d neo4j postgres
docker compose ps     # neo4j + postgres = Up (healthy)
```

이미 떠 있으면 skip.

## 2. 인증 정보 (이미 했으면 skip)

`configs/profiles/models/main.yaml` — `<GEMINI_API_KEY>` 를 실제 키로 교체
(발급: https://aistudio.google.com/apikey).

`configs/profiles/dbs/main.yaml` — `<NEO4J_PASSWORD>` → `neo4j_password`,
`<POSTGRES_PASSWORD>` → `memmachine_password` (docker compose 기본값).

세부사항: [longmemeval_temporal_reasoning_quickstart.md](longmemeval_temporal_reasoning_quickstart.md)
의 4 절.

## 3. 데이터셋 (이미 있으면 skip)

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

500 문항. `.gitignore` 대상.

## 4. Run config + working configuration.yml 생성

```bash
uv run python scripts/generate_config.py \
    --problem 0 \
    --run-name lme_iso \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt
```

산출:
- `configs/runs/lme_iso.yaml` — run config
- `configs/generated/lme_iso_configuration.yml` — working configuration.yml

다른 실험으로 분리하고 싶으면 `--run-name lme_iso_v2` 식으로 별 이름 사용.

## 5a. Ingest

```bash
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --limit 1
```

각 질문 시작 시 `delete_session_episodes()` 가 먼저 도니까 같은 prefix 로
재실행해도 중복 적재 없음 (idempotent).

stdout 에 `[lme-ingest] 1/1  qid=...  episodes=...  t=...s` 가 보이면 OK.

## 5b. Retrieve → retrieve.jsonl

```bash
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl \
    --limit 1
```

→ `results/lme_iso/retrieve.jsonl` (1 row).

stdout 에 `[lme-retrieve] 1/1  qid=...  chunks=...  t=...s` 가 보이면 OK.

`--session-prefix` 는 ingest 와 retrieve 가 **같은 값** 이어야 함. `--top-k`
만 바꿔 retrieve 만 여러 번 돌릴 수 있음 (재-ingest 비용 0).

`--limit` 빼면 500 문항 전부. CPU 환경에선 시간 걸림 (concurrency 4 기본,
질문 당 수 초~수십 초).

## 6. 답변 LLM 호출 → generate.jsonl

```bash
uv run python -m evaluation.longmemeval.generate \
    --retrieve results/lme_iso/retrieve.jsonl \
    --config-path configs/generated/lme_iso_configuration.yml \
    --out results/lme_iso/generate.jsonl \
    --limit 1
```

upstream `src/generation/run_generation.py` 의 `LME_origin_prompt` 를
verbatim 으로 사용. CoT 변종이 필요하면
`--answer-prompt LME_origin_cot_prompt`. answer LLM 은
`retrieval_agent.llm_model` (configuration.yml) 그대로.

> 답변 LLM 호출이 비싸/길어서 일단 skip 하고 recall 만 보려면 step 8 의
> "Recall-only 흐름" 참고.

## 7. Judge → judge.jsonl (+ 카테고리별 정확도 요약)

```bash
uv run python -m evaluation.longmemeval.judge \
    --generate results/lme_iso/generate.jsonl \
    --config-path configs/generated/lme_iso_configuration.yml \
    --out results/lme_iso/judge.jsonl \
    --limit 1
```

upstream `src/evaluation/evaluate_qa.py` 의 `get_anscheck_prompt` 와
yes/no lenient 파서 verbatim. 5종 task-별 prompt + abstention 별도 처리.
judge LLM 은 `retrieval_agent.judge_llm_model` 우선, 없으면 답변 LLM 재사용.

각 row 에 `llm_score` (1=correct, 0=wrong) + `judge_raw_response` +
`judge_parsed_label`. 마지막에 overall + 카테고리별 정확도 표 stdout 출력.

## 8. (선택) 추가 분석

step 7 의 stdout 에서 이미 overall + 카테고리별 정확도 표가 나오니 별도
요약 명령은 불필요. 더 깊이 보려면 `scripts/` 의 분석 도구도 같은
retrieve.jsonl / judge.jsonl 그대로 소비 가능:

```bash
# recall@k 곡선
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json

uv run python scripts/plot_recall_curve.py \
    --input results/lme_iso/recall_curve.json \
    --out   results/lme_iso/recall_curve.png \
    --per-category

# judge 요약 (judge.py stdout 의 표와 동일 내용, JSON 으로 저장)
uv run python scripts/summarize_run.py \
    --judge results/lme_iso/judge.jsonl \
    --out   results/lme_iso/summary.json
```

(이 step 만 `scripts/` 사용 — step 1~7 은 본 디렉토리만으로 완결.)

## Recall-only 흐름 (답변 LLM / judge 비용 0)

step 6~7 스킵하고 step 5 의 retrieve.jsonl 만 가지고:

```bash
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json
```

순수 retrieval 측정. 500 문항 풀로 돌리면 카테고리별 recall@k 곡선이
upstream / Edwin 의 ~95% 수치와 직접 비교 가능.

## 풀 500 문항 실행

step 5~7 에서 `--limit 1` 만 빼면 됨:

```bash
# 5a. ingest 풀 500
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso --concurrency 4

# 5b. retrieve 풀 500
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso --top-k 50 \
    --out results/lme_iso/retrieve.jsonl --concurrency 4

# 6. generate 풀 500
uv run python -m evaluation.longmemeval.generate \
    --retrieve results/lme_iso/retrieve.jsonl \
    --config-path configs/generated/lme_iso_configuration.yml \
    --out results/lme_iso/generate.jsonl --concurrency 4

# 7. judge 풀 500 + 카테고리별 정확도 요약
uv run python -m evaluation.longmemeval.judge \
    --generate results/lme_iso/generate.jsonl \
    --config-path configs/generated/lme_iso_configuration.yml \
    --out results/lme_iso/judge.jsonl --concurrency 4
```

- `--concurrency` 높이면 빠르지만 Neo4j (5a/5b) / LLM API rate (6/7) 부하 ↑.
- 같은 `--session-prefix` 로 ingest 재실행하면 자동 cleanup (idempotent).
- top-K 만 바꿔 retrieve 만 다시 돌리려면 5b 만 다시 실행 (ingest 스킵).
- 답변 prompt 만 바꿔 generate 만 다시 돌리려면 6 만 다시 실행
  (`--answer-prompt LME_origin_cot_prompt` 등).

## 다른 실험과 병행

`--session-prefix` 만 다르게 주면 같은 Neo4j 안에 여러 실험이 공존:

```bash
# experiment v1
uv run python -m evaluation.longmemeval.ingest   ... --session-prefix lme_iso
uv run python -m evaluation.longmemeval.retrieve ... --session-prefix lme_iso --out results/lme_iso/retrieve.jsonl

# experiment v2 (다른 chunking 등)
uv run python -m evaluation.longmemeval.ingest   ... --session-prefix lme_iso_v2
uv run python -m evaluation.longmemeval.retrieve ... --session-prefix lme_iso_v2 --out results/lme_iso_v2/retrieve.jsonl
```

Neo4j 에는 `lme_iso_<qid>*` 와 `lme_iso_v2_<qid>*` 가 별개 세션으로 공존.
하나 정리하려면 그 prefix 의 session 만 골라 delete (현재 별도 cleanup
스크립트 없음 — 필요하면 Cypher 직접).

## 비교 (기존 단일 session 경로 vs 격리)

같은 모델/같은 K 에서:

| 경로 | 적재 | 검색 공간 | 관측 recall |
|---|---|---|---|
| `scripts/run_pipeline.py --stage ingest,retrieve` (= `evaluation/retrieval_agent/`) | 모든 질문이 단일 session | ~246k turn | ~50% |
| `evaluation/longmemeval/{ingest,retrieve}.py` (본 가이드) | 질문 별 session | ~500 turn | ~95% 예상 |

격리 한 가지가 ~45 포인트 차이의 핵심 원인.

## 트러블슈팅

- **"configuration.yml not found"**: step 4 의 `generate_config.py` 가 안
  돌았거나 `--run-name` 이 다름. `configs/generated/<run_name>_configuration.yml`
  존재 확인.
- **Neo4j auth error**: step 2 의 패스워드 일치 여부. `configs/profiles/dbs/main.yaml`
  과 docker compose 의 `${NEO4J_PASSWORD}` 가 같은지 (.env 사용 시 양쪽 일치).
- **Gemini quota / rate limit**: free tier 라 분당 호출 제한. `--concurrency` 낮추거나
  유료 키로 교체.
- **`regen_answer.py` "retrieve.jsonl missing"**: step 5 의 `--out` 이 정확히
  `results/<run_name>/retrieve.jsonl` 인지 확인 (`<run_name>` = `--run-name`).
- **재실행 시 데이터 잔존 의심**: `ingest.py` 가 매 질문 시작 시
  `delete_session_episodes()` 호출하므로 중복 적재 걱정 없음. 그래도 모든
  데이터 날리고 재시작 하려면 `docker compose down -v` 후 step 1 부터.
- **풀 500 문항이 너무 느림**: GPU 가능하면 embedder 가 자동 활용. concurrency
  올려 보고, 그래도 느리면 `--limit` 로 카테고리 별 200~300 으로 우선 확인.

## 핵심 파일 위치

| 항목 | 경로 |
|---|---|
| Ingest | `evaluation/longmemeval/ingest.py` |
| Retrieve | `evaluation/longmemeval/retrieve.py` |
| Generate (answer LLM) | `evaluation/longmemeval/generate.py` |
| Judge | `evaluation/longmemeval/judge.py` |
| 공용 헬퍼 + upstream prompts | `evaluation/longmemeval/_common.py` |
| 디렉토리 README | `evaluation/longmemeval/README.md` |
| Run config | `configs/runs/<run_name>.yaml` |
| Working configuration.yml | `configs/generated/<run_name>_configuration.yml` |
| 산출물 | `results/<run_name>/{retrieve,generate,judge}.jsonl + summary.json` |
| 분석 도구 | `scripts/recall_curve.py`, `scripts/plot_recall_curve.py`, `scripts/summarize_run.py` |
