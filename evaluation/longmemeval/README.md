# `evaluation/longmemeval/` — per-question 격리 평가 (MemMachine 백엔드, 단계 분리)

LongMemEval 표준 격리 패턴 (xiaowu0162/LongMemEval `src/retrieval/run_retrieval.py`,
main `evaluation/episodic_memory/`) 을 우리 MemMachine 스택 (Neo4j vector
graph store + Postgres, configuration.yml 의 embedder + reranker) 위에서
재현. 각 질문이 `session_id = <prefix>_<question_id>` 에 격리 적재됨.

`evaluation/retrieval_agent/` 의 단일 session 적재 (recall ~50%) 와 유일한
차이는 session_id 정책. 검색 공간이 ~246k → ~500 turn (질문 별) 으로
축소되어 recall ~95% 수준 도달.

## 파일

| 파일 | 역할 |
|---|---|
| `ingest.py` | per-question delete + `add_memory_episodes` (idempotent) |
| `retrieve.py` | per-question `query_agent.do_query` → retrieve.jsonl |

`ingest` 와 `retrieve` 가 분리되어 있어 같은 데이터로 `--top-k` 만 바꿔
retrieve 만 여러 번 돌릴 수 있다 (재-ingest 비용 0). 답변 LLM / judge 호출
없음 — 정확도까지 보려면 다음에 `scripts/regen_answer.py` +
`scripts/run_pipeline.py --stage judge`.

## 사용

```bash
# 1) ingest
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso

# 2) retrieve
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl

# 3) 분석 (우리 도구 그대로)
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json
```

`--session-prefix` 는 ingest 와 retrieve 가 **같은 값** 이어야 함. 다른 prefix
로 ingest 해두면 같은 Neo4j 안에서 별개 실험 (lme_iso_*, lme_v2_* …) 으로
공존 가능.

## 옵션

공통:
- `--limit N` — 처음 N 개 질문 (스모크)
- `--include-categories <list>` — comma-separated 카테고리 필터
- `--concurrency N` — 병렬 처리 (default 4)

retrieve 전용:
- `--top-k K` — 회수 chunk 수 (default 50)

## 호출 패턴 (수정 불필요 — 검증됨)

ingest 측:
```python
memory, _, _ = await agent_utils.init_memmachine_params(
    rm, session_id=session_id, agent_name="MemMachineAgent")
_set_safe_embedder_request_limits(memory)
await memory.delete_session_episodes()             # idempotent re-run
await memory.add_memory_episodes(episodes=episodes)
```

retrieve 측:
```python
memory, _, query_agent = await agent_utils.init_memmachine_params(
    rm, session_id=session_id, agent_name="MemMachineAgent")
chunks, perf = await query_agent.do_query(
    QueryPolicy(token_cost=10, time_cost=10, accuracy_score=10,
                confidence_score=10, max_attempts=3, max_return_len=10000),
    QueryParam(query=question, limit=top_k, memory=memory),
)
```

→ `evaluation/retrieval_agent/longmemeval_test._async_ingest` /
`_async_search` 의 호출 패턴과 동일. session_id 만 per-question.

## 정리 메모

- **idempotent re-run**: 같은 prefix 로 ingest 재실행 시 매 질문 시작 시
  `delete_session_episodes()` 가 먼저 도니까 중복 적재 없음.
- **상위 디렉토리 정리**: 다른 prefix 로 옮기거나 모든 lme_iso_* 를 한 번에
  지우는 별도 cleanup 스크립트는 현재 없음. 필요하면 Neo4j Cypher 직접 또는
  `docker compose down -v` 로 전체 초기화.
- **격리 효과**: 단일 session (`scripts/run_pipeline.py`) 의 ~246k turn 검색
  공간 → 질문 별 ~500 turn (~500 배 축소) → recall 50%→95% 의 핵심 원인.
