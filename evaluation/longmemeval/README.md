# `evaluation/longmemeval/` — per-question 격리 평가 (MemMachine 백엔드)

LongMemEval 표준 격리 방식을 우리 MemMachine 스택 (Neo4j + Postgres,
configuration.yml 의 embedder + reranker) 위에서 그대로 적용. 각 질문이
자기 `session_id = <prefix>_<question_id>` 안에 격리 적재 → retrieval 도
그 session 안에서만.

`evaluation/retrieval_agent/` (모든 질문이 단일 session 에 적재 → cross-
question contamination, recall ~50%) 와의 유일한 차이는 **session_id 분리
하나**. backend / embedder / reranker / chunking 정책은 동일.

## 왜 필요한가

`scripts/run_pipeline.py --stage ingest,retrieve` (retrieval_agent 기반) 는
500 질문 × ~493 turn ≈ 246k turn 을 single session 에 적재 → 정답 turn
1~2 개를 거대 풀에서 찾아야 함 → recall ~50%.

upstream LongMemEval / Edwin / main `evaluation/episodic_memory/` 셋 다
per-question 격리. 본 디렉토리가 그 패턴을 우리 MemMachine 백엔드 + 우리
retrieve.jsonl 포맷에 맞춰 옮긴 것.

## 파일

| 파일 | 역할 |
|---|---|
| `ingest.py` | per-question session 으로 데이터 적재 (Neo4j) |
| `retrieve.py` | per-question session 에서 검색 → retrieve.jsonl 출력 |

답변 LLM / judge 호출 없음. 순수 retrieval. 정확도까지 보려면 그 다음에
`scripts/regen_answer.py` + `scripts/run_pipeline.py --stage judge,analyze`.

## 사전 준비

기존 평가 파이프라인과 동일한 환경 (`docs/msr/longmemeval_temporal_reasoning_quickstart.md`
의 0~5 단계). Neo4j + Postgres 뜨고, working configuration.yml 이 있어야 함:

```bash
uv run python scripts/generate_config.py \
    --problem 0 --run-name lme_iso \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt
```

→ `configs/generated/lme_iso_configuration.yml` 생성.

## 사용

```bash
# 1) per-question ingest
uv run python -m evaluation.longmemeval.ingest \
    --data-path evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso

# 2) per-question retrieve → retrieve.jsonl
uv run python -m evaluation.longmemeval.retrieve \
    --data-path evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl

# 3) 분석 (우리 도구 그대로)
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json

uv run python scripts/plot_recall_curve.py \
    --input results/lme_iso/recall_curve.json \
    --out   results/lme_iso/recall_curve.png \
    --per-category
```

`--session-prefix` 는 ingest 와 retrieve 에서 **같은 값** 이어야 함.
session_id 가 prefix 로 격리되니까 다른 prefix 로 ingest 해두면 별개의
실험으로 공존 가능 (Neo4j 안에 lme_iso_*, lme_v2_* 등 병렬 보유).

## 옵션

공통:
- `--limit N` — 처음 N 개 질문 (스모크).
- `--include-categories <list>` — comma-separated 카테고리 필터.
- `--concurrency N` — 병렬 처리 (default 4). 너무 높이면 Neo4j 부하 ↑.

retrieve 전용:
- `--top-k K` — 회수할 chunk 수 (default 50).

## 정리 (실험 끝났을 때)

session 별로 깨끗하게 지우려면 `evaluation/retrieval_agent/longmemeval_test.py`
의 `--run-type delete` 가 단일 session 만 지움. 모든 lme_iso_* 를 한 번에
지우려면 Neo4j Cypher 직접 사용 (또는 docker compose down -v 로 볼륨
삭제 후 재시작).
