# LongMemEval — per-question 격리 평가 (MemMachine 백엔드) 가이드

`evaluation/longmemeval/run_retrieval.py` 사용. upstream `run_retrieval.py`
의 per-question 격리 패턴을 우리 MemMachine 스택 (Neo4j vector graph
store + Postgres, configuration.yml 의 embedder + reranker) 위에서
재현. 단일 session 적재 (`scripts/run_pipeline.py`) 경로의 recall ~50%
문제를 해결한다.

각 질문이 `session_id = <prefix>_<question_id>` 에 격리 적재되어 검색
공간이 ~246k turn → ~500 turn 으로 축소 (~500 배). upstream / Edwin /
main `evaluation/episodic_memory/` 와 동일한 의미론.

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
uv run python scripts/regen_answer.py --run lme_iso
```

`results/lme_iso/retrieve.jsonl` 읽어 answer LLM 호출 후
`results/lme_iso/generate.jsonl` 작성. 기존 generate.jsonl 있으면
`.bak` 으로 백업.

> 답변 LLM 호출이 비싸/길어서 일단 skip 하고 recall 만 보려면 step 8 의
> "Recall-only 흐름" 참고.

## 7. Judge → judge.jsonl

```bash
uv run python scripts/run_pipeline.py \
    --config configs/runs/lme_iso.yaml \
    --stage judge
```

`results/lme_iso/judge.jsonl` 작성. 각 row 에 `llm_score` (1=correct, 0=wrong)
+ judge raw response.

## 8. 결과 요약

```bash
uv run python scripts/summarize_run.py \
    --judge results/lme_iso/judge.jsonl \
    --out   results/lme_iso/summary.json
```

stdout 에 overall + 카테고리별 정확도 표. JSON 도 같이 저장.

비교용으로 recall@k 곡선도:

```bash
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json

uv run python scripts/plot_recall_curve.py \
    --input results/lme_iso/recall_curve.json \
    --out   results/lme_iso/recall_curve.png \
    --per-category
```

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

step 5a / 5b 에서 `--limit 1` 만 빼면 됨:

```bash
# ingest 풀 500
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --concurrency 4

# retrieve 풀 500
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl \
    --concurrency 4
```

- `--concurrency` 높이면 빠르지만 Neo4j 부하 ↑. CPU 환경 4~8, GPU 환경
  8~16 정도가 무난.
- 같은 `--session-prefix` 로 재실행하면 자동 cleanup → 결과 동일 (idempotent).
- top-K 만 바꿔 retrieve 만 다시 돌리려면 5b 만 다시 실행 (ingest 스킵).

이후 step 6~8 동일.

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
| `evaluation/longmemeval/run_retrieval.py` (본 가이드) | 질문 별 session | ~500 turn | ~95% 예상 |

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
- **재실행 시 데이터 잔존 의심**: `run_retrieval.py` 가 매 질문 시작 시
  `delete_session_episodes()` 호출하므로 중복 적재 걱정 없음. 그래도 모든
  데이터 날리고 재시작 하려면 `docker compose down -v` 후 step 1 부터.
- **풀 500 문항이 너무 느림**: GPU 가능하면 embedder 가 자동 활용. concurrency
  올려 보고, 그래도 느리면 `--limit` 로 카테고리 별 200~300 으로 우선 확인.

## 핵심 파일 위치

| 항목 | 경로 |
|---|---|
| Ingest 스크립트 | `evaluation/longmemeval/ingest.py` |
| Retrieve 스크립트 | `evaluation/longmemeval/retrieve.py` |
| 디렉토리 README | `evaluation/longmemeval/README.md` |
| Run config | `configs/runs/<run_name>.yaml` |
| Working configuration.yml | `configs/generated/<run_name>_configuration.yml` |
| 산출물 | `results/<run_name>/{retrieve,generate,judge}.jsonl + summary.json` |
| 분석 도구 | `scripts/recall_curve.py`, `scripts/plot_recall_curve.py`, `scripts/summarize_run.py` |
