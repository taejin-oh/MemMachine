# MemMachine 평가 방식 비교 분석

**작성일:** 2026-04-30  
**작성자:** Taejin Oh  
**목적:** LongMemEval 원본, memmachine-test, eval_mm/MemMachine 의 평가 방식 비교

---

## 1. 개요

본 문서는 MemMachine 평가 환경 (`eval_mm/MemMachine`) 이 LongMemEval 원본 benchmark 및 memmachine-test 와 어떻게 다른지 비교 분석한다.

### 1.1 비교 대상

| 저장소 | 경로 | 용도 |
|--------|------|------|
| **LongMemEval (원본)** | `/home/tj/Workspace/LongMemEval` | 논문 공개 benchmark |
| **memmachine-test** | `/home/tj/Workspace/memmachine-test/benchmark/longmemeval` | MemVerge 내부 QA 평가용 |
| **eval_mm/MemMachine** | `/home/tj/Workspace/eval_mm/MemMachine/evaluation` | 논문 문제 재현 평가용 |

---

## 2. Judge Prompt 비교

### 2.1 원본 LongMemEval

**파일:** `src/evaluation/evaluate_qa.py`

```python
def get_anscheck_prompt(task, question, answer, response, abstention=False):
    if task in ['single-session-user', 'single-session-assistant', 'multi-session']:
        template = ("I will give you a question, a correct answer, and a response "
                    "from a model. Please answer yes if the response contains the "
                    "correct answer. Otherwise, answer no...")
```

**특징:**
- 출력: `yes` / `no` 텍스트
- 질문 유형별 다른 프롬프트 (6 가지: single-session-user, single-session-assistant, multi-session, temporal-reasoning, knowledge-update, single-session-preference)
- JSON 출력 없음
- Abstention 질문 처리 별도

### 2.2 memmachine-test

**파일:** `benchmark/longmemeval/memlib/common/judge.py`

**정확한 라인:** `get_judge_prompt()` 함수는 `lmelib/prompt.py` 에 정의됨 (라인 244-263), `memlib/common/judge.py` 에서 import 하여 사용

```python
def get_judge_prompt(task, question, answer, response, abstention=False):
    if not abstention:
        if task in ["single-session-user", "single-session-assistant", "multi-session"]:
            template = ("I will give you a question, a correct answer, and a response "
                        "from a model. Please answer yes if the response contains the "
                        "correct answer. Otherwise, answer no...")
```

**특징:**
- 원본과 **동일한 프롬프트**
- 출력: `yes` / `no` 텍스트
- 추가 메트릭: F1, BLEU, Latency, Token usage

### 2.3 eval_mm/MemMachine

**파일:** `evaluation/retrieval_agent/llm_judge.py`

```python
ACCURACY_PROMPT = """
Your task is to label an answer to a question as 'CORRECT' or 'WRONG'...

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""
```

**특징:**
- **완전히 다른 프롬프트** (Mem0 에서 어레인지)
- 출력: JSON `{"label": "CORRECT"}` 또는 `{"label": "WRONG"}`
- 재시도 로직 (최대 2 회)

### 2.4 Judge Prompt 비교 요약

| 항목 | LongMemEval | memmachine-test | eval_mm/MemMachine |
|------|-------------|-----------------|--------------------|
| **프롬프트 내용** | yes/no | yes/no (동일) | CORRECT/WRONG (JSON) |
| **출력 형식** | 텍스트 | 텍스트 | JSON |
| **질문 유형별 프롬프트** | ✅ 6 가지 | ✅ 6 가지 | ❌ 단일 |
| **재시도 로직** | ❌ | ❌ | ✅ (최대 2 회) |
| **추가 메트릭** | Accuracy 만 | F1, BLEU, Latency | Accuracy 만 |

---

## 3. Answer 생성 Prompt 비교

### 3.1 원본 LongMemEval

**파일:** `src/generation/run_generation.py`

```python
# CoT 사용 시
answer_prompt_template = ('I will give you several history chats between you and a user. '
    'Please answer the question based on the relevant chat history. '
    'Answer the question step by step: first extract all the relevant information, '
    'and then reason over the information to get the answer.')

# CoT 미사용 시
answer_prompt_template = ('I will give you several history chats between you and a user. '
    'Please answer the question based on the relevant chat history.')
```

**특징:**
- 단순 지시문
- CoT on/off 만 선택 가능

### 3.2 memmachine-test

**파일:** `benchmark/longmemeval/lmelib/prompt.py`

```python
SIMPLE_ANSWER_PROMPT = "..."      # 기본형
COT_ANSWER_PROMPT = "..."         # Chain-of-Thought
EDWIN1_ANSWER_PROMPT = "..."      # Episodic memory 최적화
EDWIN2_ANSWER_PROMPT = "..."      # EDWIN1 + 모호성 처리
EDWIN3_ANSWER_PROMPT = "..."      # 최신 정보 우선
```

**특징:**
- 5 가지 프롬프트 제공
- EDWIN 시리즈: episodic memory 활용 최적화
- `--answer-prompt` 옵션으로 선택 가능

### 3.3 eval_mm/MemMachine

**파일:** `evaluation/retrieval_agent/longmemeval_test.py`

```python
# Citation: Luo et al. (2025), "Agent Lightning: Train ANY AI Agents with
# Reinforcement Learning", arXiv:2508.03680.
ANSWER_PROMPT = """You are asked to answer `{question}` using `{memories}` as the only source of knowledge.

<instructions>
1. Normalize inputs before deciding anything...
2. Choose the evidence basis using this strict priority...
3. Uncertainty rule...
4. Ambiguity handling...
5. Computation and counting...
6. Output requirements (concise, auditable)...
</instructions>
"""
```

**특징:**
- Agent Lightning 논문 (Luo et al. 2025) 에서 가져옴
- 6 개 상세 지시문 포함
- 입력 정규화, 모호성 처리, 계산 명시 등 상세 가이드

### 3.4 Answer 생성 Prompt 비교 요약

| 항목 | LongMemEval | memmachine-test | eval_mm/MemMachine |
|------|-------------|-----------------|--------------------|
| **프롬프트 수** | 2 가지 (CoT on/off) | 5 가지 | 1 가지 |
| **이름** | CoT / Simple | SIMPLE, COT, EDWIN1-3 | Agent Lightning |
| **출처** | LongMemEval 원본 | MemVerge 내부 | Agent Lightning 논문 |
| **특징** | 단순 지시 | Episodic 최적화 | 상세 지시문 (6 개) |

---

## 4. 데이터셋 처리 비교

### 4.1 원본 LongMemEval

- 데이터셋: `xiaowu0162/longmemeval-cleaned`
- Split: `longmemeval_s_cleaned`, `longmemeval_m_cleaned`
- 로딩: HuggingFace datasets 또는 JSON 직접 다운로드

### 4.2 memmachine-test

- 데이터셋: `lmelib/data.py` 에서 관리
- Split: `LONGMEMEVAL_S`, `LONGMEMEVAL_M`, `LONGMEMEVAL_ORACLE`
- 로딩: HuggingFace (`mvbot/longmemeval-cleaned`) + 로컬 JSON 캐시
- URL: `https://huggingface.co/datasets/mvbot/longmemeval-cleaned/resolve/main/`

### 4.3 eval_mm/MemMachine

- 데이터셋: `xiaowu0162/longmemeval-cleaned`
- Split: `longmemeval_s_cleaned` (통일)
- 로딩: HuggingFace datasets + JSON fallback

### 4.4 데이터셋 비교 요약

| 항목 | LongMemEval | memmachine-test | eval_mm/MemMachine |
|------|-------------|-----------------|--------------------|
| **데이터소스** | HF datasets (`xiaowu0162/longmemeval-cleaned`) | HF datasets (`mvbot/longmemeval-cleaned`) | HF datasets (`xiaowu0162/longmemeval-cleaned`) |
| **Split 이름** | longmemeval_s_cleaned | LONGMEMEVAL_S | longmemeval_s_cleaned |
| **Fallback** | JSON 직접 다운로드 | 로컬 JSON 캐시 | JSON 직접 다운로드 |

---

## 5. 평가 실행 방식 비교

### 5.1 원본 LongMemEval

```bash
# 1. Answer 생성
python src/generation/run_generation.py \
  --in_file data/test.json \
  --out_dir results \
  --model_name gpt-4o \
  --retriever_type flat-turn \
  --topk_context 30 \
  --history_format json \
  --useronly false \
  --cot true

# 2. Judge 실행
python src/evaluation/evaluate_qa.py \
  gpt-4o-mini \
  results/test.json \
  data/test.json
```

### 5.2 memmachine-test

```bash
cd benchmark/longmemeval

# 1. Ingest
python main.py ingest \
  --ingest-prompt role \
  --context-prompt json-str \
  --search-prompt user-q \
  --answer-prompt edwin3

# 2. Search + Eval
python main.py search-eval \
  --limit 30 \
  --type memmachine \
  --ingest-prompt role \
  --context-prompt json-str \
  --search-prompt user-q \
  --answer-prompt edwin3 \
  --temperature 1.0

# 3. Judge
python main.py judge \
  --model gpt-4o-mini \
  --ingest-prompt role \
  --context-prompt json-str \
  --search-prompt user-q \
  --answer-prompt edwin3 \
  --input-file results/memmachine_search_eval_results.json \
  --output-file results/memmachine_scores.json
```

### 5.3 eval_mm/MemMachine

```bash
cd evaluation/retrieval_agent

# 1. Ingest
python longmemeval_test.py \
  --run-type ingest \
  --config-path configuration.yml \
  --session-id longmemeval_group \
  --length 100 \
  --split-name longmemeval_s_cleaned

# 2. Search
python longmemeval_test.py \
  --run-type search \
  --test-target memmachine \
  --config-path configuration.yml \
  --session-id longmemeval_group \
  --length 100 \
  --split-name longmemeval_s_cleaned \
  --search-limit 30 \
  --eval-result-path results/search_results.json

# 3. Judge
python evaluate.py \
  --config-path configuration.yml \
  --data-path results/search_results.json
```

### 5.4 실행 방식 비교 요약

| 항목 | LongMemEval | memmachine-test | eval_mm/MemMachine |
|------|-------------|-----------------|--------------------|
| **단계 분리** | 2 단계 (generate, judge) | 3 단계 (ingest, search-eval, judge) | 3 단계 (ingest, search, judge) |
| **Ingest 별도** | ❌ | ✅ | ✅ |
| **Retrieval Agent** | ❌ | ✅ | ✅ |
| **병렬 처리** | ❌ | ✅ (async) | ✅ (async) |
| **설정 파일** | CLI 인자 | CLI 인자 + .env | configuration.yml |

---

## 6. 주요 차이점 요약

### 6.1 Judge 방식

| 차이 | 설명 |
|------|------|
| **프롬프트** | eval_mm 은 CORRECT/WRONG (JSON), 원본/테스트는 yes/no (텍스트) |
| **출력 파싱** | eval_mm 은 JSON 파싱 필요, 원본/테스트는 텍스트 검색 |
| **재시도** | eval_mm 만 재시도 로직 있음 |
| **메트릭** | memmachine-test 만 F1, BLEU 추가 제공 |

### 6.2 Answer 생성 방식

| 차이 | 설명 |
|------|------|
| **프롬프트 수** | 원본 (2), 테스트 (5), eval_mm (1) |
| **최적화** | 테스트는 episodic memory 최적화 (EDWIN), eval_mm 은 Agent Lightning 기반 |
| **지시문 상세도** | eval_mm 이 가장 상세 (6 개 지시문) |

### 6.3 데이터셋 처리

| 차이 | 설명 |
|------|------|
| **Split 이름** | eval_mm 은 `longmemeval_s_cleaned` 로 통일 |
| **Fallback** | 원본/eval_mm 은 JSON 직접 다운로드 지원 |

### 6.4 실행 구조

| 차이 | 설명 |
|------|------|
| **Ingest 분리** | memmachine-test/eval_mm 은 ingest 별도 수행 |
| **설정 관리** | eval_mm 은 configuration.yml 사용 |
| **병렬 처리** | memmachine-test/eval_mm 은 async 병렬 처리 |

---

## 7. 평가 결과 비교 가능성

### 7.1 동일한 조건에서 비교 가능한 경우

✅ **내부 비교** (동일 평가 환경 내):
- eval_mm 내에서 k 값 변경 비교 (k=10 vs k=30 vs k=100)
- eval_mm 내에서 chunk on/off 비교
- eval_mm 내에서 agent vs memory 직접 검색 비교

✅ **원본 vs memmachine-test**:
- Judge prompt 동일
- Answer prompt 는 EDWIN 사용 시 다름

### 7.2 직접 비교 어려운 경우

❌ **eval_mm vs 원본/테스트**:
- Judge prompt 가 다름 (CORRECT/WRONG vs yes/no)
- Answer prompt 가 다름 (Agent Lightning vs EDWIN/Simple)
- 점수 스케일이 직접 비교 불가

❌ **절대 점수 비교**:
- 다른 judge 는 다른 점수 분포 생성
- 논문 결과와 eval_mm 결과 직접 비교 불가

### 7.3 권장 비교 방식

1. **상대 비교만 수행**: 동일 환경 내 조건 변경 비교
2. **Judge 통일**: 외부 결과와 비교 시 동일한 judge 사용
3. **조건 명시**: 모든 결과에 사용된 prompt/설정 명시

---

## 8. 결론 및 권장사항

### 8.1 현재 eval_mm/MemMachine 의 위치

- **LongMemEval 원본 기반**하지만 상당 부분 수정됨
- **memmachine-test 와는 별개** 발전 경로
- **Agent Lightning 논문** 의 프롬프트 채택 (answer generation)
- **Mem0 의 judge 로직** 차용 (ACCURACY_PROMPT, CORRECT/WRONG JSON 출력)
- **이중 구조**: retrieval_agent 와 episodic_memory 에 각각 별도 judge 구현 (둘 다 CORRECT/WRONG)

### 8.2 평가 결과 해석 가이드

1. **eval_mm 내 비교는 유효함**: 동일 judge, 동일 answer prompt 사용
2. **원본/테스트와 절대 점수 비교 불가**: 다른 judge/answer 사용
3. **상대적 개선/악화만 해석**: "k=30 이 k=10 보다 15%p 개선" 등

### 8.3 향후 작업

1. **Judge 통일 검토**: 원본과 동일한 judge 사용 여부 결정
2. **Answer prompt 비교 실험**: EDWIN vs Agent Lightning 성능 비교
3. **결과 재현성 검증**: 원본 benchmark 로 cross-validation

---

## 부록 A. 파일 위치 정리

### LongMemEval (원본)

```
/home/tj/Workspace/LongMemEval/
├── src/
│   ├── generation/run_generation.py      # Answer 생성
│   └── evaluation/evaluate_qa.py         # Judge 실행
└── data/
```

### memmachine-test

```
/home/tj/Workspace/memmachine-test/benchmark/longmemeval/
├── main.py                               # 통합 실행
├── lmelib/
│   ├── prompt.py                         # Answer prompts (5 가지: SIMPLE, COT, EDWIN1-3)
│   ├── data.py                           # 데이터셋 로딩 (HF: mvbot/longmemeval-cleaned)
│   └── helper.py                         # JSON load/save helpers
└── memlib/
    ├── common/
    │   ├── judge.py                      # Judge 실행 (yes/no, F1/BLEU 계산)
    │   ├── helper.py                     # BLEU/IQR 계산
    │   └── interface.py                  # ingest/search/judge 인터페이스
    └── core/
        ├── ingest.py                     # MemMachine ingest
        └── search.py                     # MemMachine search
```

### eval_mm/MemMachine

```
/home/tj/Workspace/eval_mm/MemMachine/evaluation/
├── retrieval_agent/
│   ├── longmemeval_test.py               # Ingest/Search (Agent Lightning prompt)
│   ├── llm_judge.py                      # Judge (CORRECT/WRONG, JSON 출력, 2 회 재시도)
│   ├── evaluate.py                       # 평가 실행 (Mem0 기반)
│   ├── cli_utils.py                      # CLI 유틸리티
│   └── preflight.py                      # 사전 점검
├── episodic_memory/                      # Legacy LoCoMo 평가
│   ├── longmemeval_ingest.py
│   ├── longmemeval_search.py
│   └── llm_judge.py                      # 별개 Judge (yes/no)
└── utils/
    ├── agent_utils.py                    # MemMachine 유틸리티
    ├── memmachine_helper.py              # MemMachine helper factory
    └── memmachine_helper_restapiv2.py    # REST API v2 helper
```

---

## 부록 B. 프롬프트 전문

### B.1 Judge Prompt 비교

**LongMemEval / memmachine-test:**
```
I will give you a question, a correct answer, and a response from a model. 
Please answer yes if the response contains the correct answer. Otherwise, answer no. 
If the response is equivalent to the correct answer or contains all the intermediate 
steps to get the correct answer, you should also answer yes.
```

**eval_mm/MemMachine:**
```
Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. 
You will be given the following data:
    (1) a question (posed by one user to another user),
    (2) a 'gold' (ground truth) answer,
    (3) a generated answer
...
Just return the label CORRECT or WRONG in a json format with the key as "label".
```

### B.2 Answer Prompt 비교

**LongMemEval (CoT):**
```
I will give you several history chats between you and a user. 
Please answer the question based on the relevant chat history. 
Answer the question step by step: first extract all the relevant information, 
and then reason over the information to get the answer.
```

**memmachine-test (EDWIN3):**
```
You are a helpful assistant with access to extensive conversation history.
When answering questions, carefully review the conversation history to identify 
and use any relevant user preferences, interests, or specific details they have mentioned.
...
```

**eval_mm/MemMachine (Agent Lightning):**
```
You are asked to answer `{question}` using `{memories}` as the only source of knowledge.

<instructions>
1. Normalize inputs before deciding anything...
2. Choose the evidence basis using this strict priority...
3. Uncertainty rule...
4. Ambiguity handling...
5. Computation and counting...
6. Output requirements (concise, auditable)...
</instructions>
```
