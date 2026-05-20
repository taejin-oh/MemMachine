# `evaluation/longmemeval/` — upstream `run_retrieval.py` 패턴 + MemMachine 저장소

xiaowu0162/LongMemEval `src/retrieval/run_retrieval.py` 의 구조를 그대로
보존하되 저장 레이어만 **in-memory numpy → MemMachine (Neo4j vector
graph store + Postgres)** 로 바꾼 것. 한 파일, 한 패스. per-question
session_id 격리.

## 흐름 (upstream 과 1:1 대응)

| upstream                                       | 우리 |
|---|---|
| `for entry in entry_list:`                     | `for entry in entry_list:` |
| **step 1: build corpus**                       | **step 1: build corpus + ingest** |
| `corpus = process_item_flat_index(...)`        | `episodes = _build_corpus_episodes(entry, session_id)` |
| (in-memory list)                               | `await memory.delete_session_episodes()` <br/> `await memory.add_memory_episodes(episodes)` |
| **step 2: run retrieval**                      | **step 2: run retrieval** |
| `rankings = retriever_master.run_flat_retrieval(query, args.retriever, corpus)` | `chunks, _ = await query_agent.do_query(QueryParam(query, limit, memory))` |
| **step 3: record**                             | **step 3: record** |
| `cur_results = {'retrieval_results': {'ranked_items': [...]}}` | `rows.append({'chunks_text': ..., 'supporting_facts': ..., ...})` |

upstream 이 매 entry 마다 새 corpus 를 빌드해서 격리하듯, 우리는 매 entry
마다 `session_id = <prefix>_<question_id>` 로 격리된 MemMachine 세션에
적재 → 그 세션에서만 검색.

retrieval 코어 호출 (`query_agent.do_query`), embedder / vector_graph_store /
reranker 는 `evaluation/retrieval_agent/` 와 동일한 configuration.yml 기반.
유일한 차이는 session_id 정책.

## 파일

| 파일 | 역할 |
|---|---|
| `run_retrieval.py` | per-question (delete → ingest → retrieve → record), retrieve.jsonl 출력 |

답변 LLM / judge 호출 없음. 정확도까지 보려면 다음에
`scripts/regen_answer.py` + `scripts/run_pipeline.py --stage judge,analyze`.

## 사용

### 사전 준비
기존 평가 환경과 동일 (`docs/msr/longmemeval_temporal_reasoning_quickstart.md`
의 0~5 단계). Neo4j + Postgres 뜨고:

```bash
uv run python scripts/generate_config.py \
    --problem 0 --run-name lme_iso \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt
```

→ `configs/generated/lme_iso_configuration.yml`.

### 실행

```bash
uv run python -m evaluation.longmemeval.run_retrieval \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/lme_iso_configuration.yml \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl

# 분석 (우리 도구 그대로)
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json

uv run python scripts/plot_recall_curve.py \
    --input results/lme_iso/recall_curve.json \
    --out   results/lme_iso/recall_curve.png \
    --per-category
```

## 옵션

| 옵션 | 의미 | upstream 대응 |
|---|---|---|
| `--in-file <path>` | 입력 데이터셋 | `--in_file` |
| `--config-path <yml>` | 워킹 configuration.yml | (upstream 은 모델 cli 인자) |
| `--out <path>` | 출력 retrieve.jsonl | `--out_dir` (우리는 단일 파일) |
| `--top-k N` | 회수 chunk 수 (default 50) | upstream 의 retrieval k |
| `--session-prefix <str>` | session_id 접두어 (default `lme_iso`) | (upstream 은 in-memory 라 불필요) |
| `--include-categories <list>` | 카테고리 필터 | — |
| `--limit N` | 처음 N 질문만 (스모크) | — |
| `--concurrency N` | 병렬 처리 (default 4) | upstream 의 num_workers |

`--session-prefix` 가 다르면 같은 Neo4j 안에서 별개의 실험 (lme_iso_*, lme_v2_* …)
이 공존 가능. 매 실행은 `delete_session_episodes()` 로 idempotent — 같은
prefix 로 두 번 돌려도 결과 동일.

## 정리 메모

- **upstream code 직접 import 안 함**: 그쪽은 BM25/contriever/stella/gte 의 in-memory
  retriever 가 핵심이라 우리 MemMachine 호출 패턴과 다름. **구조** (3-step 루프)만
  본떴고 호출은 우리 retrieval_agent 패턴 (`agent_utils.init_memmachine_params`,
  `query_agent.do_query`, `episodes_to_string`).
- **upstream 과 다른 점 한 가지**: upstream 은 매 entry 마다 corpus 를 새로 만들었다
  버림 — Neo4j 안엔 데이터 안 남음. 우리는 각 질문의 데이터가 그 question_id
  session 에 영구 저장됨. 다음 실행 때 `delete_session_episodes()` 로 정리.
  Neo4j 디스크 영향 신경 쓰이면 별도 clean-up 스크립트 추가 가능.
- **격리 효과**: 단일 session (`evaluation/retrieval_agent/`) 의 ~246k turn 검색
  공간 → 질문 별 ~500 turn 검색 공간 (~500 배 축소) → recall 50%→95% 의 핵심.
