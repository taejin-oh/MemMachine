# LongMemEval 원본 vs MemMachine `evaluation/retrieval_agent` 차이 분석

작성일: 2026-04-30
대상 브랜치: `eval_claude`
비교 대상:
- 원본: https://github.com/xiaowu0162/LongMemEval (`src/evaluation/`, `src/generation/`)
- MemMachine: `evaluation/retrieval_agent/` (단, 같은 레포의 `evaluation/episodic_memory/` 와 비교 정보 포함)

---

## 1. Judge Prompt (정답 판정 프롬프트)

### 원본 (`src/evaluation/evaluate_qa.py:24-43`)
- **`question_type`별로 분기되는 6가지 템플릿** + abstention 전용 1가지:
  - `single-session-user / single-session-assistant / multi-session`
    : 정답 포함/등가/중간 단계 포함 시 yes, 부분 정보면 no
  - `temporal-reasoning`
    : 위와 동일하나 **"off-by-one 일수 오차는 정답으로 인정"** 예외 규정
  - `knowledge-update`
    : "이전 정보 + 갱신된 답변이 함께 있어도 갱신된 답이 맞으면 yes"
  - `single-session-preference`
    : rubric 기반, 모든 항목 만족할 필요 없음
  - **abstention(`_abs` 접미사 qid)**
    : "답할 수 없는 질문임을 모델이 정확히 식별했는지" 평가하는 별도 프롬프트
- 출력은 단순 `yes/no` 텍스트 (`max_tokens=10`).
- 채점 모델은 `gpt-4o-mini-2024-07-18`, `gpt-4o-2024-08-06`, `meta-llama/Meta-Llama-3.1-70B-Instruct` 중 선택.

### MemMachine `retrieval_agent` (`evaluation/retrieval_agent/llm_judge.py:17-41`)
- **단 하나의 통합 프롬프트(`ACCURACY_PROMPT`)** — 질문 유형 분기 없음.
- "be generous with your grading" 톤, 시간/날짜 포맷 동등성도 단일 프롬프트에서 처리.
- 출력은 `{"label": "CORRECT" | "WRONG"}` JSON 강제 (`json_repair`로 파싱, 2회 재시도).
- abstention/temporal/knowledge-update 같은 task별 특수 규칙이 **없음**.
- 출처: Mem0 judge 어댑트.

### MemMachine `episodic_memory` (참고: `evaluation/episodic_memory/longmemeval_evaluate.py:155`)
- 원본 `get_anscheck_prompt`를 **그대로 이식**해서 task별 분기 + abstention 분기 유지.
- 즉 MemMachine 내부에서 **충실 버전(episodic_memory)과 단순화 버전(retrieval_agent)이 공존**.

---

## 2. Answer Prompt (응답 생성 프롬프트)

### 원본 (`src/generation/run_generation.py:46-69`)
- 6가지 변형이 retriever_type / cot / merge_key_expansion 조합으로 동적으로 선택.
- 핵심 템플릿:
  ```
  I will give you several history chats between you and a user.
  Please answer the question based on the relevant chat history.

  History Chats:

  {history}

  Current Date: {date}
  Question: {question}
  Answer:
  ```
- **`Current Date`(질문 시점 날짜) 필드 포함** — temporal reasoning에 핵심.
- CoT 모드: "Answer step by step: first extract … then reason …"
- `useronly`, `history_format`(json/nl), `con`(읽기 노트) 등 풍부한 인자.
- 토큰 예산 truncation: `model_max_length - gen_length(500/800) - 1000`.
- 메모리에 답이 없을 때도 **무조건 답변 생성** (외부 지식 사용 금지가 암묵적 전제).

### MemMachine `retrieval_agent` (`longmemeval_test.py:22-56`)
- **Agent Lightning 논문(arXiv:2508.03680) 출처 단일 `ANSWER_PROMPT`**.
- 6단계 instruction (정규화 → 메모리 우선순위 → 불확실성 → 모호성 → 계산 → 출력 포맷).
- 메모리 우선순위:
  - (a) Memory-explicit
  - (b) Memory-determined inference
  - (c) **Open-domain fallback (general world knowledge 사용 허용)** ← 원본과 충돌
- "I don't know" 허용 / 답이 없으면 **명료화 질문 한 가지만 하라** ← 원본은 무조건 답변.
- **`Current Date` 필드 부재** → temporal-reasoning 컨텍스트 손실.
- 출력 길이 강제: **"max 2 sentences"** (필요 시 최대 4줄), 원본은 500~800 tokens.
- 플레이스홀더는 `{question}` / `{memories}` 둘 뿐.

---

## 3. 평가 지표 (Metrics)

### 원본 QA metrics (`src/evaluation/print_qa_metrics.py`)
- 채점 결과: `autoeval_label.label` (boolean).
- 보고 지표:
  - **Per question_type accuracy** (6 task)
  - **Task-averaged Accuracy** (6 task별 정확도의 macro 평균)
  - **Overall Accuracy** (전체 micro 평균)
  - **Abstention Accuracy** (`_abs` 접미사 qid에 대해서만 별도 산출)

### 원본 Retrieval metrics (`src/evaluation/print_retrieval_metrics.py`)
- 표준 IR 지표: `recall_all@5/10/50`, `ndcg_any@5/10/50` (session-level / turn-level).
- chunk-level gold relevance가 dataset에 포함되어야 가능 (`retrieval_results.metrics`).
- abstention 질문은 retrieval 평가에서 제외.

### MemMachine `retrieval_agent` (`generate_scores.py` + `agent_utils.py`)
- 채점 결과: `llm_score` (0/1).
- 보고 지표:
  - 카테고리별 mean `llm_score`
  - Overall mean
  - **Task-averaged Accuracy(macro 평균) 없음**
  - **Abstention Accuracy 별도 산출 없음** (`evaluate.py:32`에서 `category=="5"`만 스킵 — LOCOMO용)
- 추가 지표 (원본 QA 평가에는 없는 항목):
  - **Recall** = `num_hits / num_facts` ← supporting_facts 텍스트가 retrieved memory 본문에 토큰 overlap으로 포함되는지 (`_fact_in_mem`: 정확 substring 또는 5+ token 중 60% overlap 휴리스틱)
  - **Precision** = `num_hits / num_episodes_retrieved`
  - Tool별 호출/적중/입출력 토큰 통계 (ToolSelectAgent 등)
  - 평균 메모리 검색 시간 / LLM 시간

> **주의**: 원본의 retrieval metric(NDCG/recall@k)과 MemMachine의 recall/precision은 **이름은 같지만 정의가 다른 지표**다. 원본은 chunk-level gold relevance 기반 표준 IR 지표, MemMachine은 fact 텍스트의 토큰 overlap 기반 휴리스틱 매칭.

### `generate_scores.py` 카테고리 매핑 dead code
- `categories` 리스트(라인 13-23)는 LOCOMO/HotpotQA용 이름(`multi_hop`, `single_hop`, `bridge_comparison` 등)이고 LongMemEval `question_type`(`single-session-user`, `temporal-reasoning` 등)과 매핑 안 됨.
- `result.index.map(...)` 코드는 `isinstance(result.index, int)` 조건 안에 있어 **절대 실행되지 않음** (pandas Index는 int가 아님).
- 결과적으로 LongMemEval task name이 그대로 출력되고 그룹핑은 정상.

---

## 4. 요약 표

| 영역 | LongMemEval 원본 | MemMachine `retrieval_agent` |
|---|---|---|
| Judge | 6 task + abstention별 분기 프롬프트, yes/no 텍스트, max_tokens=10 | 단일 통합 프롬프트, JSON `{label}`, "관대한" 채점 |
| Answer | history + **Current Date** 필수, CoT/JSON/NL 등 옵션 다양, 외부 지식 금지, 500~800 tokens | Agent Lightning 식 6단계 지시, **외부 지식 fallback 허용**, "max 2 sentences" 강제, Current Date 없음 |
| QA Metric | per-task acc, **task-averaged acc**, **abstention acc** 별도 | overall + per-category mean만, abstention/macro 평균 미보고 |
| Retrieval Metric | recall_all@k / ndcg_any@k (session/turn level) | fact 텍스트 token-overlap 기반 recall/precision (정의 다름) |

---

## 5. 핵심 시사점

1. **Judge 충실도 손실**
   `retrieval_agent`의 judge는 task 특성을 무시 — 특히 temporal off-by-one 인정, knowledge-update 누적 답안 인정, abstention 식별 평가가 **모두 빠짐**. 같은 응답에 대해서도 원본과 다른 채점 결과가 나올 수 있음.

2. **Answer prompt의 평가 누수 위험**
   "Open-domain fallback"이 허용되어 retrieval 품질과 무관하게 LLM의 사전 지식만으로 답을 맞히는 경우가 발생 가능. 이는 메모리 시스템 평가 본연의 목적(메모리에서 정답을 끌어왔는지)을 흐림. `Current Date` 부재로 temporal-reasoning 정확도가 시스템 성능과 무관하게 떨어질 수 있음.

3. **표준 지표 부재**
   LongMemEval 논문 결과와 직접 비교하려면 task-averaged accuracy / abstention accuracy / recall_all@k / ndcg_any@k가 필요한데 모두 미보고. 현재 `retrieval_agent`의 출력만으로는 원본 리더보드와 1:1 비교 불가.

4. **레포 내부에 충실 버전이 이미 존재**
   `evaluation/episodic_memory/longmemeval_evaluate.py`는 원본의 task별 judge prompt를 그대로 이식. 정렬이 필요하면 이 코드 패턴을 `retrieval_agent`로 옮기는 방식이 가장 빠름.

---

## 6. 정렬을 위한 권장 작업 (참고)

- `llm_judge.py`의 `ACCURACY_PROMPT`를 `episodic_memory/longmemeval_evaluate.py:155`의 `get_anscheck_prompt(task, ..., abstention)` 분기 함수로 교체. `category` → `question_type` 매핑 + `_abs` qid 검출 로직 필요.
- `ANSWER_PROMPT`에 `{question_date}` 필드 추가, 메모리 외 외부 지식 사용 금지 문구 추가, 출력 길이 제약 완화.
- `generate_scores.py`에 macro task-averaged accuracy / abstention-only accuracy 추가, dead code된 `categories` 매핑 제거 또는 LongMemEval task name으로 갱신.
- (선택) chunk-level gold relevance가 있을 때만 NDCG/recall@k 추가 보고.
