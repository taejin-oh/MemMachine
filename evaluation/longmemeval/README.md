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
| `_common.py` | MemMachine 부트스트랩 + upstream prompt + helper (standalone) |
| `ingest.py` | per-question delete + `add_memory_episodes` (idempotent) |
| `retrieve.py` | per-question `query_agent.do_query` → retrieve.jsonl |
| `generate.py` | retrieve.jsonl → answer LLM (upstream prompt) → generate.jsonl |
| `judge.py` | generate.jsonl → judge LLM (upstream `get_anscheck_prompt`) → judge.jsonl + 요약 |

ingest → retrieve → generate → judge 네 단계가 모두 본 디렉토리 안에서
완결. 같은 데이터로 `--top-k` / `--answer-prompt` 만 바꿔 generate 만 다시
돌리는 식으로 단계 별 재실행 가능.

## 독립성

본 디렉토리는 `evaluation/longmemeval/_common.py` + `memmachine_server.*`
(워크스페이스 패키지) **만** 의존. `evaluation/retrieval_agent/`,
`evaluation/utils/`, `scripts/{regen_answer,run_pipeline,stages/*}` 어느
것도 import 안 함.

→ `evaluation/` 의 다른 디렉토리를 main 브랜치 상태로 되돌리거나 통째로
삭제해도 본 디렉토리만으로 ingest → retrieve → generate → judge 모두
실행 가능. 외부 의존은 `scripts/generate_config.py` (워킹 yml 생성) 한 곳.

`_common.py` 의 inline 내용:

| 헬퍼 | 원본 |
|---|---|
| `load_eval_config` | agent_utils.load_eval_config |
| `build_memory_and_agent` | agent_utils.init_memmachine_params (MemMachineAgent 분기만) |
| `get_answer_llm` / `get_judge_llm` | retrieval_agent.llm_model / .judge_llm_model 에서 LM 획득 |
| `set_safe_embedder_limits` | longmemeval_test._set_safe_embedder_request_limits |
| `collect_supporting_facts` | longmemeval_test._collect_supporting_facts |
| `parse_session_dt` | longmemeval session_date 파서 |
| `ANSWER_PROMPTS` | **upstream verbatim** — `src/generation/run_generation.py:54-57` |
| `get_anscheck_prompt` | **upstream verbatim** — `src/evaluation/evaluate_qa.py:24-43` |
| `parse_yes_no_lenient` | upstream `'yes' in eval_response.lower()` |

## 사용

```bash
# 1) ingest
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso

# 2) retrieve → retrieve.jsonl (question_date / golden_answer 도 포함)
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --session-prefix lme_iso \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl

# 3) generate → generate.jsonl (upstream LME_origin_prompt 기본, --answer-prompt 로 변경)
uv run python -m evaluation.longmemeval.generate \
    --retrieve results/lme_iso/retrieve.jsonl \
    --config-path configs/generated/lme_iso_configuration.yml \
    --out results/lme_iso/generate.jsonl

# 4) judge → judge.jsonl + 카테고리별 정확도 요약 출력
uv run python -m evaluation.longmemeval.judge \
    --generate results/lme_iso/generate.jsonl \
    --config-path configs/generated/lme_iso_configuration.yml \
    --out results/lme_iso/judge.jsonl
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

## Ingest 단위 — turn (upstream 정렬)

**1 turn = 1 Episode** (upstream `run_retrieval.py --granularity turn` 과
동일). turn 길이와 무관하게 추가 split 안 함. 긴 turn 이 embedder 의
`max_input_length` (bge-base = 512 token ≈ 2000자) 를 넘으면 임베딩 단계에서
silently truncate — upstream 도 동일한 거동.

이전엔 `_split_chunks(max_chars=3000)` 로 긴 turn 을 piece 로 쪼개서
별도 Episode 로 적재했지만 (= chunking unit 이 upstream 과 다름), upstream
재현을 위해 제거. 짧은 turn (96%) 은 어차피 1 chunk = 1 turn 이라 결과
변동 거의 없음. 긴 turn 3.8% 만 회수 방식이 바뀜 (여러 piece → 1 turn).

## 호출 패턴 (수정 불필요 — 검증됨)

ingest 측:
```python
memory, _query_agent = await build_memory_and_agent(rm, session_id)
set_safe_embedder_limits(memory)
await memory.delete_session_episodes()             # idempotent re-run
await memory.add_memory_episodes(episodes=episodes)
```

retrieve 측:
```python
memory, query_agent = await build_memory_and_agent(rm, session_id)
chunks, perf = await query_agent.do_query(
    QueryPolicy(token_cost=10, time_cost=10, accuracy_score=10,
                confidence_score=10, max_attempts=3, max_return_len=10000),
    QueryParam(query=question, limit=top_k, memory=memory),
)
```

`build_memory_and_agent` 가 ResourceManager → embedder/reranker/vector_graph_store
획득 + LongTermMemory + EpisodicMemory + MemMachineAgent 까지 한 번에 만듦.
agent_utils.init_memmachine_params 의 MemMachineAgent 분기만 그대로 옮긴 것.

## 정리 메모

- **idempotent re-run**: 같은 prefix 로 ingest 재실행 시 매 질문 시작 시
  `delete_session_episodes()` 가 먼저 도니까 중복 적재 없음.
- **상위 디렉토리 정리**: 다른 prefix 로 옮기거나 모든 lme_iso_* 를 한 번에
  지우는 별도 cleanup 스크립트는 현재 없음. 필요하면 Neo4j Cypher 직접 또는
  `docker compose down -v` 로 전체 초기화.
- **격리 효과**: 단일 session (`scripts/run_pipeline.py`) 의 ~246k turn 검색
  공간 → 질문 별 ~500 turn (~500 배 축소) → recall 50%→95% 의 핵심 원인.

## upstream 점수와 "동일한" 결과를 원하면

알고리즘 단위는 이제 정렬됨 (turn = corpus item = Episode). 그러나
**완전 동일 (bit-for-bit) recall 재현** 은 backend 차이로 어려움. 다음 3가지를
추가 정렬해야 진짜 동일에 가까워짐:

1. **Reranker 제거** — upstream 의 flat retrieval 은 reranker 없음.
   현재 우리는 `rrf-hybrid([bm25, identity])`. 동일 재현 원하면 model
   profile 의 `rerankers` 를 `identity` 단일로 바꾸거나, 별도
   `configs/profiles/models/upstream_aligned.yaml` 만들어 사용.

2. **같은 embedder** — upstream 은 contriever / stella / gte / bm25 등.
   같은 모델 ID 로 main.yaml 의 `embedder` 만 swap. 우리 default 인
   `BAAI/bge-base-en-v1.5` 와 upstream 의 default 가 다르면 임베딩이
   다르므로 top-K 가 달라짐.

3. **Exact cosine search 강제** — Neo4j 의 HNSW ANN 은 근사. upstream 의
   in-memory 는 exact. ANN 의 recall 은 99%+ 이라 영향 작지만 0 은 아님.
   완전 동일 원하면 Neo4j vector index 의 ANN 옵션 끄거나, 후보 부족 시
   `_exact_similarity_search_fallback_threshold` 의 fallback 항상 타도록
   유도.

→ 위 3 가지 추가 정렬 없이도 algorithmic flow 와 단위는 upstream 과 일치.
**시스템 평가 용도라면 현재 setup OK**, **upstream 점수표 직접 재현 용도면**
1+2+3 추가 정렬 권장. 우리 evaluation/longmemeval/ 의 코드만 보면 더
이상 손댈 게 없음 (profile / db 차원의 문제).
