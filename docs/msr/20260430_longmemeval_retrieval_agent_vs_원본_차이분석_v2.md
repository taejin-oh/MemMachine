# LongMemEval 원본 vs MemMachine `evaluation/retrieval_agent` 차이 분석 (v2)

작성일: 2026-04-30 (작성 기준 HEAD `d55caf2`)
최종 갱신: 2026-05-04 — v0.5 (commit `a919a67`) 의 `lenient` default 전환을 §1 표·각주에 반영. 기준 시점 자체는 작성일 그대로 두고, 후속 변경은 “v0.5 시점” 으로 명기.
대상 브랜치: `eval_claude`
v1 문서: [`20260430_longmemeval_retrieval_agent_vs_원본_차이분석.md`](20260430_longmemeval_retrieval_agent_vs_원본_차이분석.md)
연계 문서: [`20260504_modified_list_v0.5.md`](20260504_modified_list_v0.5.md) — v0.5 delta 의 단일 출처

> ⚠️ **본 v2 의 위치**
> v1 본문은 §3 **이하** 에 그대로 보존했다 (작성 시점의 사실 기록). v1 의 결론 일부는 후속 정렬 작업(PR #27 commit `684f1d6` / `465d8b8` / `d55caf2`, 그리고 v0.5 의 `5beb8f0` / `a919a67`)으로 사실과 어긋나게 됐고, v2 §1 ~ §2 가 그 갱신을 담는다. v1 의 §1 ~ §6 텍스트는 변경하지 않았다.

---

## 1. v1 → v2 갱신 요약 (post-fix delta)

### 1.1 무엇이 바뀌었나
PR #27 의 후속 commit (`684f1d6` / `465d8b8` / `d55caf2` + review-fix `c1`) 으로 **LongMemEval 데이터셋에 한해서** judge prompt / 채점 방식이 **두 진입 경로 모두에서** 원본에 정렬됨. answer prompt 와 metric 보고는 v1 시점과 동일하게 미정렬.

> **두 진입 경로 구분**
> - **Legacy 경로**: `evaluation/retrieval_agent/evaluate.py` — 단독 실행 진입점.
> - **Eval-tool 경로**: `scripts/run_pipeline.py --stage judge` → `scripts/stages/judge.py` — 새 wrapper 진입점. 양쪽 모두 같은 `llm_judge.py` 함수 사용.

| 영역 | v1 시점 결론 | v2 시점 사실 |
|---|---|---|
| Judge prompt — Legacy `evaluate.py` 경로 (LongMemEval) | 단일 `ACCURACY_PROMPT` (분기 없음) | **task별 6분기 + abstention 분기** (`get_anscheck_prompt` 이식) — `684f1d6` |
| Judge prompt — Wrapper `scripts/stages/judge.py` 경로 (LongMemEval) | 단일 `ACCURACY_PROMPT` (분기 없음) | **task별 6분기 + abstention 분기** — review-fix 에서 wrapper 도 동일 routing 적용 |
| Judge 출력 형식 (LongMemEval) | JSON `{label: CORRECT/WRONG}` 강제 | **plain-text yes/no** (`max_tokens=10`). yes/no 파싱은 `_parse_yes_no` 로 **default lenient (`'yes' in lower(raw)`, 원본 동일)** + 옵션 strict (whole-string). `retrieval_agent.longmemeval_yesno_policy` / `--longmemeval-yesno-policy` / `judge.longmemeval_yesno_policy` 로 전환 가능 — v0.5 |
| Judge prompt (LOCOMO/Wiki/HotpotQA) — 두 경로 모두 | 단일 `ACCURACY_PROMPT` | (변경 없음) 단일 `ACCURACY_PROMPT` 유지 |
| Answer prompt (LongMemEval) | Agent Lightning 식, Current Date 없음, open-domain fallback 허용 | **v0.6 (`20260504_modified_list_v0.6.md`) 에서 정렬** — `longmemeval_answer_prompt: Literal["memmachine_original", "agent_lightning"] = "memmachine_original"` 정책 도입. default 본문은 `evaluation/episodic_memory/longmemeval_search.py:36-52` 차용 (KNOWLEDGE UPDATES + PLANNED ACTIONS + `Current date: {question_date}`), open-domain fallback 제거, length cap 제거. `agent_lightning` 은 baseline rerun 옵트인 |
| Metric (LongMemEval) | task-averaged / abstention 미보고 | (변경 없음) v1 결론 그대로 — **여전히 미보고** |
| `generate_scores.py` 카테고리 매핑 dead code | dead code 존재 | (변경 없음) — 별도 PR 후보 |

### 1.2 코드 위치 (v2 시점)
- `evaluation/retrieval_agent/llm_judge.py`
  - `_LME_TEMPLATE_GENERAL / _TEMPORAL / _KNOWLEDGE_UPDATE / _PREFERENCE / _ABSTENTION` 5+1 상수
  - `get_anscheck_prompt(task, q, a, r, abstention=False) -> str`
  - `_parse_yes_no(raw, policy="lenient"|"strict")` — v0.5. `policy="lenient"` (기본, 원본 LongMemEval 일치) 는 `'yes' in lower(raw)` substring 매칭, `policy="strict"` 는 `\A\s*(yes|no)[\s.!?,]*\Z` whole-string 매칭. lenient 에선 `"yesterday"` 도 1 (substring trap, 원본과 동일).
  - `evaluate_llm_judge_longmemeval(question, gold, generated, question_type, question_id, call_fn, yesno_policy="lenient") -> int` — `_abs` 접미사 → abstention 분기, `_parse_yes_no` 로 응답 파싱
  - **Policy 전달 경로**: legacy `evaluate.py` 는 `--longmemeval-yesno-policy` CLI 플래그 (미지정 시 `retrieval_agent.longmemeval_yesno_policy` config 폴백); wrapper `judge.py` 는 `run_cfg.judge.longmemeval_yesno_policy` 우선, 미지정 시 동일 config 폴백. 두 경로 모두 실행 시점에 `[evaluate] longmemeval_yesno_policy=...` / `[judge] ... longmemeval_yesno_policy=...` 로그 출력.
  - `create_judge_fn(config_path, json_mode: bool = True)` — `json_mode=False` 시 OpenAI 호출에서 `response_format` / `text.format` 제거 + `max_tokens=10` 추가. Bedrock 분기 no-op.
- **Legacy 경로** — `evaluation/retrieval_agent/evaluate.py`
  - `_LONGMEMEVAL_TASKS` frozenset 6개 task name → 라우팅 키
  - `process_sample(..., json_call_fn, get_text_call_fn)` — text 모드 judge 는 **lazy + thread-safe double-checked locking** 으로 첫 LongMemEval 샘플 처리 시점에만 초기화 (`d55caf2` 후속 리팩터링)
- **Eval-tool 경로** — `scripts/stages/judge.py` (review-fix)
  - `_LONGMEMEVAL_TASKS` frozenset 6개 (legacy 경로와 동일 키, 의도적으로 module-local 복사 — wrapper stage 가 legacy evaluate.py 내부에 의존 안 하도록)
  - `run()` 의 row loop 에서 `category in _LONGMEMEVAL_TASKS` 일 때 `evaluate_llm_judge_longmemeval` 호출, 아닌 경우 기존 `evaluate_llm_judge` 호출
  - text-mode judge 는 동일하게 **lazy** — 첫 LongMemEval row 만나는 시점에 `create_judge_fn(json_mode=False)` 1회 호출
- `evaluation/retrieval_agent/test_llm_judge.py` — LongMemEval judge 5 + create_judge_fn json_mode kwargs 3 + parser regression 16 (parametrized) + yesterday/not-yes/yes-and-no 3 = 신규 테스트 27 건 (v0.4 doc 의 라인 수와 다른 이유: parser 강화 시점에 추가)
- `evaluation/retrieval_agent/test_evaluate.py` — text-mode judge 가 LongMemEval 카테고리에서만 초기화되는지 검증 2건
- `scripts/test_stages_judge.py` — review-fix 신규. wrapper routing 4건 (LongMemEval ↔ longmemeval judge / non-LongMemEval ↔ legacy judge / `_abs` ↔ abstention prompt / end-to-end llm_score 작성)

### 1.3 검증

- **v0.4 시점 (review-fix 포함, HEAD `d55caf2`)**: `python3.12 -m pytest evaluation/retrieval_agent/test_llm_judge.py evaluation/retrieval_agent/test_evaluate.py scripts/test_stages_judge.py -v` → **60/60 PASS**.
- **v0.5 시점 (HEAD `a919a67`)**: `lenient`/`strict` 정책화 + Pydantic schema + run_cfg/config 폴백 + generate_config CLI 매핑 등으로 테스트 13건 추가. `python3.12 -m pytest evaluation/retrieval_agent/ scripts/ -v` → **190/190 PASS** (자세한 내역은 [`20260504_modified_list_v0.5.md`](20260504_modified_list_v0.5.md)).
- LOCOMO/Wiki/HotpotQA 경로는 양쪽 진입점 모두 시그니처 호환 유지 (`create_judge_fn(...)` 기본값 `json_mode=True`).
- 출력 스키마 (`llm_score`: 0/1) 동일 → `generate_scores.py` 무수정.
- `ruff check` — `evaluate_llm_judge` 와 `create_judge_fn` 의 C901 complexity 경고 1건 존재. **본 review-fix 에서 도입된 항목 아님** (`684f1d6` 시점 도입). 별도 PR 후보.

### 1.4 v1 §5 핵심 시사점 재조정

| v1 시사점 | v2 갱신 |
|---|---|
| **Judge 충실도 손실** | ✅ **해결 (양쪽 경로)** — `evaluation/retrieval_agent/evaluate.py` (legacy) 와 `scripts/run_pipeline.py --stage judge` 두 진입점 모두 LongMemEval 한해 task별 분기 + abstention 평가 복원. yes/no 파싱은 v0.5 부터 **default lenient (원본 100% 일치)**, strict 는 옵트인. paper 수치 재현 가능 |
| **Answer prompt 평가 누수 위험** | ✅ **해결 (v0.6)** — `longmemeval_answer_prompt` 정책 도입 (default `memmachine_original`). open-domain fallback 제거, `Current date: {question_date}` 추가, length cap 제거. `agent_lightning` 옵트인으로 baseline rerun 가능 |
| **표준 지표 부재** | 🟥 미해결 — task-averaged / abstention accuracy / NDCG / recall@k 미보고 |
| **레포 내부에 충실 버전 존재** | 참고 사항으로 유효 — `episodic_memory/longmemeval_evaluate.py:155` 의 `get_anscheck_prompt` 와 `retrieval_agent/llm_judge.py` 의 신규 함수가 **본문이 동일한 두 정적 카피** 로 공존 (의도된 결정 — import 의존성 추가 회피) |

### 1.5 v1 §6 정렬 권장 작업 진행 상황

| 항목 | 상태 |
|---|---|
| `llm_judge.py` 의 task별 분기 도입 (`get_anscheck_prompt` + `_abs` 검출) | ✅ 완료 (PR #27 / commit `684f1d6`) |
| `ANSWER_PROMPT` 에 `{question_date}` 추가, 외부 지식 금지, 출력 길이 제약 완화 | ✅ **v0.6 완료** (`20260504_modified_list_v0.6.md`) — `longmemeval_answer_prompt` 정책 도입, default `memmachine_original` |
| `generate_scores.py` 에 macro task-averaged / abstention-only accuracy 추가 | ❌ 미진행 — **v2 잔여 항목** |
| dead code `categories` 매핑 제거 / LongMemEval task name 갱신 | ❌ 미진행 — **v2 잔여 항목** |
| chunk-level gold relevance 있을 때 NDCG/recall@k 추가 보고 | ❌ 미진행 (선택) |

---

## 2. 다음 단계 (v2 시점 잔여 작업)

우선순위 순:

1. ~~**Answer prompt 정렬**~~ — ✅ **v0.6 완료** (`20260504_modified_list_v0.6.md`):
   - `longmemeval_answer_prompt: Literal["memmachine_original", "agent_lightning"] = "memmachine_original"` 정책 도입.
   - default `memmachine_original` 본문은 `evaluation/episodic_memory/longmemeval_search.py:36-52` 의 본문 (KNOWLEDGE UPDATES / PLANNED ACTIONS 추론 가이드) + `Current date: {question_date}` placeholder.
   - `agent_utils.process_question(prompt_extra=...)` 시그니처 확장 — sibling benchmark (HotpotQA/LoCoMo/Wiki-MH) backward compat 유지.
   - `_format_question_date()` 가 LongMemEval upstream `"YYYY/MM/DD (Day) HH:MM"` → `"%A, %B %d, %Y at %I:%M %p"` 변환.
   - 두 entrypoint (legacy `longmemeval_test.py`, wrapper `scripts/stages/retrieve.py`) 모두 동일 정책 적용 + 실행 시점 로그 출력.

2. **Metric 보고 정렬** — `evaluation/retrieval_agent/generate_scores.py`:
   - macro task-averaged accuracy 추가 (6 task per-task acc 의 평균)
   - abstention-only accuracy 추가 (`_abs` qid subset 의 평균)
   - dead code 인 `categories` 매핑 제거 또는 LongMemEval task name 으로 교체

3. **(선택) NDCG/recall@k** — chunk-level gold relevance 가 있을 때만 보고. 본 평가는 fact 텍스트 매칭 기반 recall 을 쓰므로, 표준 IR 지표 도입은 데이터셋 schema 변경이 따라가야 함.

---

## 3. v1 본문 (보존)

> 아래는 [v1](20260430_longmemeval_retrieval_agent_vs_원본_차이분석.md) 의 본문을 변경 없이 옮긴 것이다. v2 갱신 사항은 §1 에 정리되어 있다.

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
