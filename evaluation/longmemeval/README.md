# `evaluation/longmemeval/` — LongMemEval, MemMachine 백엔드, per-question 격리

upstream LongMemEval (xiaowu0162/LongMemEval) 의 평가 방식을 MemMachine
스택 (Neo4j vector graph store + Postgres + 워크스페이스 패키지의
embedder/reranker) 위에서 재현. 각 질문이 자기 session_id 안에 격리되어
적재/검색되므로 cross-question contamination 없음 — upstream 의 매-entry
in-memory corpus 와 등가 의미론.

## 파일

| 파일 | 역할 |
|---|---|
| `_common.py` | MemMachine 부트스트랩 + upstream prompts (verbatim) |
| `ingest.py` | per-question delete + `add_memory_episodes` (idempotent) |
| `retrieve.py` | per-question `query_agent.do_query` → retrieve.jsonl |
| `generate.py` | retrieve.jsonl → answer LLM → generate.jsonl |
| `judge.py` | generate.jsonl → judge LLM → judge.jsonl + 카테고리별 정확도 요약 |
| `example_configuration.yml` | 워킹 configuration.yml 템플릿 (placeholder 만 채우면 됨) |

ingest → retrieve → generate → judge 네 단계가 본 디렉토리만으로 완결.

## 독립성

본 디렉토리는 `evaluation/longmemeval/` 자기 자신 + `memmachine_server.*`
(워크스페이스 패키지) **만** 의존:

```
$ grep -rE "^from evaluation\." evaluation/longmemeval/*.py | grep -v _common
(아무것도 안 나옴)
```

`evaluation/retrieval_agent/`, `evaluation/utils/`, `evaluation/episodic_memory/`,
`scripts/` 어느 것도 import 안 함. 외부 의존은 **워킹 configuration.yml 한 개**
(`example_configuration.yml` 베이스로 직접 작성).

## 사용 흐름

```bash
PREFIX=lme_iso          # 실험 이름 = --session-prefix = 결과 디렉토리
LIMIT_ARG="--limit 1"   # 스모크 1 문항. 풀 500 시 LIMIT_ARG=""
```

### 0. 사전 준비

- Python 3.12+, `uv sync` (워크스페이스 의존성 설치)
- Neo4j + Postgres docker 실행 (별도 도커 컴포즈 사용)
- LongMemEval 데이터셋 (`evaluation/data/longmemeval_s_cleaned.json`) —
  HuggingFace `xiaowu0162/longmemeval-cleaned` 에서 다운로드

### 1. 워킹 configuration.yml 작성

`example_configuration.yml` 복사 후 2 개 placeholder 만 채움 (DB 비번):

```bash
cp evaluation/longmemeval/example_configuration.yml \
   evaluation/longmemeval/configuration.yml
# 편집기로 열어 <NEO4J_PASSWORD> / <POSTGRES_PASSWORD> 채우기
```

embedder + LLM 은 default 로 **내부 OpenAI-호환 endpoint** (Qwen3-Embedding-4B
+ nvidia/Qwen3.5-397B-A17B-NVFP4) 를 가리킴. api_key 는 `"empty"` 로 두고
`base_url` 만 자기 환경의 endpoint 로 바꾸면 됨. 외부 OpenAI / Gemini 등을
쓰려면 `resources.embedders` / `resources.language_models` 의 `config` 블록
교체 (provider / api_key / base_url / model 한 묶음으로).

### 2. Ingest

```bash
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path evaluation/longmemeval/configuration.yml \
    --session-prefix $PREFIX \
    $LIMIT_ARG
```

매 질문 시작 시 `delete_session_episodes()` 가 먼저 도니까 같은 PREFIX 로
재실행해도 중복 적재 없음 (idempotent). 1 turn = 1 Episode.

### 3. Retrieve → retrieve.jsonl

```bash
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path evaluation/longmemeval/configuration.yml \
    --session-prefix $PREFIX \
    --top-k 50 \
    --out results/$PREFIX/retrieve.jsonl \
    $LIMIT_ARG
```

`--top-k` 만 바꿔 retrieve 만 다시 돌릴 수 있음 (재-ingest 불필요).

### 4. Generate → generate.jsonl

```bash
uv run python -m evaluation.longmemeval.generate \
    --retrieve results/$PREFIX/retrieve.jsonl \
    --config-path evaluation/longmemeval/configuration.yml \
    --out results/$PREFIX/generate.jsonl \
    $LIMIT_ARG
```

upstream `src/generation/run_generation.py` 의 `LME_origin_prompt` 를 verbatim
으로 사용. CoT 원하면 `--answer-prompt LME_origin_cot_prompt`.

### 5. Judge → judge.jsonl + 정확도 요약

```bash
uv run python -m evaluation.longmemeval.judge \
    --generate results/$PREFIX/generate.jsonl \
    --config-path evaluation/longmemeval/configuration.yml \
    --out results/$PREFIX/judge.jsonl \
    $LIMIT_ARG
```

upstream `src/evaluation/evaluate_qa.py` 의 `get_anscheck_prompt` (5 task +
abstention) + lenient yes/no parser **verbatim**. 끝나면 overall + 카테고리별
정확도 표 stdout 자동 출력.

### 스모크 → 풀 런

step 2~5 가 `--limit 1` 로 통과하면 `LIMIT_ARG=""` 로 같은 명령 재실행 →
500 문항 풀. `--concurrency N` 으로 가속 가능 (Neo4j / LLM API rate 부하 ↑).

### 다른 실험 병행

`PREFIX` 만 바꿔서 같은 Neo4j 안에서 별개 실험 공존. session_id 가 prefix
별로 격리되어 cross-experiment contamination 0.

## upstream / lme_updated 정렬 상태

| 항목 | upstream | lme_updated | 우리 |
|---|---|---|---|
| 격리 단위 | per-question in-memory corpus | per-question Qdrant collection | per-question Neo4j session_id |
| Ingest 단위 | 1 turn = 1 corpus item | 1 turn = 1 Event → segmenter(500자) | 1 turn = 1 Episode |
| Recall 의미론 | turn-level binary | turn-level binary | turn-level binary (fact-piece hit = turn recalled) |
| Answer prompt | LME_origin / LME_origin_cot | mastra-augmented | **upstream verbatim** |
| Judge prompt + yes/no parser | `get_anscheck_prompt` + lenient | 동일 (verbatim) | 동일 (verbatim) |

algorithmic 단위 + 의미론 정렬됨. recall 절대값까지 동일 재현 원하면
embedder / reranker / exact-cosine 추가 정렬 필요 — `_common.py` 위 doc 의
"upstream 점수와 동일한 결과를 원하면" 섹션 참고.

## 정리 메모

- **idempotent re-run**: 같은 prefix 로 ingest 재실행 시 매 질문 시작 시
  `delete_session_episodes()` 가 먼저 돌아 중복 적재 없음.
- **상위 디렉토리 정리**: 다른 prefix 로 옮기거나 모든 lme_iso_* 한 번에
  지우는 cleanup 스크립트는 없음. 필요하면 Neo4j Cypher 직접 또는
  `docker compose down -v` 로 전체 초기화.
- **LLM 모델 분리 (3 필드)**: upstream RetrievalAgentConf 는 세 필드 지원
  — `llm_model` (retrieval / planning default), `answer_llm_model` (답변 전용),
  `judge_llm_model` (judge 전용). 우리 `_common.get_answer_llm` 은
  `answer_llm_model` → `llm_model`, `get_judge_llm` 은 `judge_llm_model` →
  답변 LLM 순으로 fallback. 셋 다 같은 모델이면 `llm_model` 만 두면 됨.

## upstream 점수와 동일한 결과를 원하면

algorithmic 단위는 이미 정렬. **완전 동일 (bit-for-bit)** 까지 가려면
profile / DB 차원 3 가지 추가 정렬:

1. **Reranker 제거** — upstream 은 flat retrieval. 현재 default 는
   `rrf-hybrid([bm25, identity])`. configuration.yml 에서 reranker 를
   `identity` 단일로.
2. **같은 embedder** — upstream 은 contriever / stella / gte. configuration.yml
   의 embedder 만 swap (resources.embedders 에 ID 추가 후 long_term_memory.embedder
   가 그걸 가리키게).
3. **Exact cosine search** — Neo4j 의 HNSW ANN 은 근사. 정확 일치 원하면
   ANN 인덱스 끄거나 fallback 조건 강화.

위 셋 없이도 alignment 충분. **시스템 평가**가 목적이면 default OK,
**upstream 점수표 재현**이 목적이면 추가 정렬 권장.
