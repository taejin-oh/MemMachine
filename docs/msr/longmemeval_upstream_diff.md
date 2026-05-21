# `evaluation/longmemeval/` vs upstream LongMemEval — 차이점 정리

xiaowu0162/LongMemEval (이하 upstream) 의 평가 코드와 우리 본 디렉토리의
일대일 대조. 알고리즘 / prompt / 격리 의미론은 정렬, 백엔드 / embedder /
reranker / 출력 schema 만 우리 환경에 맞게 변경.

기준 upstream:
- `src/retrieval/run_retrieval.py` — retrieval
- `src/generation/run_generation.py` — answer LLM
- `src/evaluation/evaluate_qa.py` — judge

기준 우리:
- `evaluation/longmemeval/{ingest,retrieve,generate,judge}.py`
- `evaluation/longmemeval/_common.py` — 헬퍼 + upstream prompts (verbatim)

---

## ✅ 완전 동일 (verbatim / byte-equal)

| 항목 | upstream 위치 | 우리 위치 |
|---|---|---|
| Answer prompt — `LME_origin_prompt` | `run_generation.py:57` | `_common.py:_ANSWER_PROMPT_PLAIN` |
| Answer prompt — `LME_origin_cot_prompt` | `run_generation.py:55` | `_common.py:_ANSWER_PROMPT_COT` |
| Judge prompt — 5 task templates + abstention | `evaluate_qa.py:24-43` | `_common.py:get_anscheck_prompt()` |
| Yes/no parser (lenient) | `evaluate_qa.py:113` | `_common.py:parse_yes_no_lenient` |
| 6 카테고리 정의 | LongMemEval data schema | `category` 필드 그대로 |
| Abstention 라우팅 | `qid.endswith('_abs')` | 동일 (`judge.py`) |
| Ground truth | `has_answer=True` turn content | `_common.collect_supporting_facts` |
| 데이터셋 | longmemeval_*.json (HF) | 같은 파일 |

### byte-level 검증

prompt 본문은 placeholder 만 `bare {}` → `{memories}`/`{question_date}`/`{question}`
명명형으로 바꿈. 그 외 한 글자, 한 줄바꿈, 한 공백도 안 바뀜:

```python
upstream_plain.format(h, d, q) == our_plain.format(memories=h, question_date=d, question=q)
# → True (byte-equal)
```

`LME_origin_prompt` 184 byte / `LME_origin_cot_prompt` 333 byte 정확히 일치.

---

## ⚠️ 구조 동일, 메커니즘 다름 (의미론 동등)

| 항목 | upstream | 우리 |
|---|---|---|
| 질문 별 격리 | per-entry in-memory corpus (numpy/list) | per-question Neo4j `session_id = <prefix>_<qid>` (Cypher `WHERE n.session_key=?`) |
| Ingest 단위 | 1 turn = 1 corpus item (`--granularity turn`) | 1 turn = 1 Episode |
| Per-turn timestamp | `session_date + i seconds` | 동일 |
| Recall semantics | turn-level binary (segment 하나라도 hit) | turn-level binary (fact-piece 하나라도 hit) |
| Role | turn['role'] 보존 (user/assistant) | producer_id "Assistant"/"User" 보존 |

→ 알고리즘 의미는 동등. 격리 효과 = 검색 공간이 그 질문의 ~500 turn 으로
제한됨, 동일.

---

## ❌ 실제 차이 (의도된 deviation)

### 백엔드 / 모델 / 인덱스

| 항목 | upstream | 우리 default |
|---|---|---|
| 저장소 | in-memory (numpy / `rank_bm25`) | Neo4j vector graph store + Postgres |
| Embedder | `flat-{bm25, contriever, stella, gte}` | `BAAI/bge-base-en-v1.5` (configurable via YAML) |
| Reranker | 없음 (flat retrieval) | `rrf-hybrid([bm25, identity])` (configurable) |
| Search algorithm | exact cosine (in-memory dot-product) | Neo4j HNSW ANN (근사, 부족 시 exact fallback) |
| Vector dim | 모델별 (e.g., 768/1024) | 768 (bge-base default) |

### 출력 schema

| 항목 | upstream | 우리 |
|---|---|---|
| Retrieve 출력 | `retrieval_results.ranked_items[{corpus_id, text, timestamp}]` 리스트 | `chunks_text` 단일 직렬화 문자열 + 메타 필드 |
| chunks_text 직렬화 | `--history_format {json,nl}` 별 다양 | `episodes_to_string`: `[<date> at <time>] <role>: "<json content>"\n` |
| Generate 필드명 | `hypothesis` | `model_answer` |
| Judge 필드명 | `autoeval_label = {model, label: bool}` | `llm_score: 0/1` + `judge_raw_response` + `judge_parsed_label` |
| 공통 필드명 | `question_type`, `answer` | `category`, `golden_answer` |
| 메타 필드 (우리만) | — | `sweep`, `cell_idx`, `supporting_facts`, `fact_hits`, `fact_miss` |

upstream 출력은 그대로 score 계산에 들어가는 형식. 우리는 본 브랜치의
분석 도구 (`scripts/recall_curve.py` 등) 호환 schema. 둘 간 1:1 변환 가능.

### LLM 파라미터

| 항목 | upstream | 우리 |
|---|---|---|
| Judge LLM temperature | **하드코딩 `temperature=0`** | YAML 프로필 의존 (보장 안 됨) |
| Judge LLM max_tokens | **하드코딩 10** | YAML 프로필 의존 |
| Answer LLM 파라미터 | CLI 옵션 (`--gen_length` 등) | YAML 프로필 |

→ 우리 judge 가 결정적이려면 model profile 에 `temperature: 0` 명시 권장.
upstream 은 yes/no 한 토큰만 받으므로 `max_tokens=10` 으로 응답 짧게 강제.

### 기능

| 항목 | upstream | 우리 |
|---|---|---|
| `--granularity` | `turn` / `session` 선택 | turn 만 (코드 수정 없이는) |
| Index expansion | `--index_expansion_method`: session-summ, session-keyphrase, session-userfact, turn-keyphrase, turn-userfact | **없음** |
| Query agent overlay | embedder 직접 호출 | `query_agent.do_query(QueryPolicy, QueryParam)` 경유 (MemMachineAgent) |
| 답변 prompt | `--cot true/false` 로 분기 (2 종) | `--answer-prompt LME_origin_{prompt,cot_prompt}` (2 종, 동일 본문) |

---

## 우리만 추가한 것 (upstream 에 없음)

| 항목 | 출처 |
|---|---|
| MemMachine 부트스트랩 (`build_memory_and_agent`) | 우리 (`_common.py`) |
| `set_safe_embedder_limits` (embedder request-size cap) | 우리 |
| ResourceManager 기반 LLM/embedder/reranker 획득 | 우리 |
| `--session-prefix` (실험 병행 — 같은 Neo4j 안에 N 개 실험 공존) | 우리 |
| `--include-categories` / `--limit` / `--concurrency` | 우리 |
| asyncio 동시성 + per-question Semaphore | 우리 |
| Idempotent re-run (매 질문 ingest 시작 시 `delete_session_episodes()`) | 우리 |
| Judge 단계의 카테고리별 정확도 stdout 표 | 우리 |

---

## 평가 결과 영향

| 차이 영역 | recall 절대값 영향 | 알고리즘 / 의미론 영향 |
|---|---|---|
| 격리 단위 (upstream / 우리 모두 per-question) | 동일 | 동일 |
| Prompt / parser / category 정의 | 동일 | 동일 |
| Embedder + Reranker (우리만 다름) | **있음** — 다른 embedding/순위 → 다른 top-K | 같은 retrieval task 의미 |
| Search algorithm (ANN vs exact) | 미세 (~99% 일치) | 동일 |
| 출력 schema | 없음 (분석 layer 의 형식) | 동일 |
| LLM 파라미터 (temperature) | judge 의 결정성 | 동일 (yes/no 의미는 같음) |

→ **알고리즘 단위 / 의미론은 100% 정렬**. recall 절대값은 embedder/reranker
차이로 약간 다를 수 있음.

---

## upstream 점수 재현하고 싶다면

코드는 손댈 게 없음. **model profile (YAML) 만 조정**:

1. **Reranker 제거** — `resources.rerankers` 에 `identity` 단일, `retrieval_agent.reranker: identity`
2. **같은 embedder** — `resources.embedders` 에 upstream 의 모델 (`facebook/contriever`,
   `Alibaba-NLP/gte-Qwen2-7B-instruct` 등) 등록 후 `episodic_memory.long_term_memory.embedder` 가
   그걸 가리키게
3. **Exact cosine search 강제** — Neo4j HNSW ANN 끄고 exact 사용 (현재 코드는 fallback
   매커니즘이 있어 후보 부족 시 자동 exact, 일반적으로 ANN recall 99% 이상이라 영향 작음)

위 셋 없이도 algorithmic correctness 보장. **시스템 평가 용도면 default OK**.

---

## 검증 방법

prompt 동일성 byte-level 검증:

```python
from evaluation.longmemeval._common import ANSWER_PROMPTS, get_anscheck_prompt

upstream_plain = 'I will give you several history chats between you and a user. Please answer the question based on the relevant chat history.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:'
ours = ANSWER_PROMPTS["LME_origin_prompt"]
ours_norm = ours.replace("{memories}", "{}").replace("{question_date}", "{}").replace("{question}", "{}")
assert ours_norm == upstream_plain     # ← True
```

independence 검증:

```bash
grep -rE "^from evaluation\.|^from scripts\." evaluation/longmemeval/*.py | grep -v _common
# → 출력 없음. 외부 evaluation/ / scripts/ 의존 0.
```

CLI smoke (DB 없이 import + help):

```bash
for cmd in ingest retrieve generate judge; do
    uv run python -m evaluation.longmemeval.$cmd --help
done
```

---

## 핵심 파일 위치

| 항목 | 파일 |
|---|---|
| upstream prompt 본문 (verbatim) | `evaluation/longmemeval/_common.py` |
| MemMachine 부트스트랩 | 같은 파일 (`build_memory_and_agent`) |
| Ingest (per-question session 적재) | `evaluation/longmemeval/ingest.py` |
| Retrieve (per-question query → retrieve.jsonl) | `evaluation/longmemeval/retrieve.py` |
| Generate (answer LLM with upstream prompt) | `evaluation/longmemeval/generate.py` |
| Judge (upstream `get_anscheck_prompt`) + 정확도 요약 | `evaluation/longmemeval/judge.py` |
| 실행 가이드 | `docs/msr/longmemeval_isolated_quickstart.md` |

---

## 한 줄 결론

알고리즘 / prompt / 격리 의미론은 upstream 과 100% 정렬. 백엔드 (Neo4j +
embedder + reranker) 와 출력 schema 만 우리 환경에 맞게 변경. recall 절대값을
upstream 점수와 1:1 비교하려면 model profile (embedder/reranker) 정렬 필요,
algorithmic correctness 만 보장하면 default OK.
