# memmachine-test EDWIN Prompt 분석

**작성일:** 2026-04-30  
**목적:** memmachine-test 에서 EDWIN prompt 의 정의와 사용 방식 정리

---

## 1. EDWIN Prompt 정의 위치

**파일:** `/home/tj/Workspace/memmachine-test/benchmark/longmemeval/lmelib/prompt.py`

5 가지 answer 생성 prompt 가 정의되어 있음:

| Prompt 이름 | 변수명 | 용도 |
|-------------|--------|------|
| `simple` | `SIMPLE_ANSWER_PROMPT` | 기본형 (최소 지시문) |
| `cot` | `COT_ANSWER_PROMPT` | Chain-of-Thought (단계별 추론) |
| `edwin1` | `EDWIN1_ANSWER_PROMPT` | Episodic memory 최적화 (기본) |
| `edwin2` | `EDWIN2_ANSWER_PROMPT` | EDWIN1 + 모호성/불일치 처리 |
| `edwin3` | `EDWIN3_ANSWER_PROMPT` | 최신 정보 우선, 계획된 행동 추론 |

---

## 2. EDWIN Prompt 상세 내용

### 2.1 EDWIN1_ANSWER_PROMPT (라인 90-111)

**정확한 라인 범위:** 90-111 (22 줄)

```python
EDWIN1_ANSWER_PROMPT = """
You are asked to answer a question from a user based on your memories of a conversation between the user and an assistant.

<instructions>
1. Prioritize memories that answer the question directly. Be meticulous about recalling details.
2. When there may be multiple answers to the question, think hard to remember and list all possible answers. Do not become satisfied with just the first few answers you remember.
3. When asked to count items, carefully enumerate the items using numbers.
4. When asked about time intervals, the duration between events is computed by subtracting the start date from the end date in the chosen unit.
5. When asked for advice or suggestions, synthesize your memories of the user's interests, preferences, possessions, and problems to provide tailored recommendations.
6. Your memories are episodic, meaning that they consist of only your raw observations of what was said. You may need to reason about or guess what the memories imply in order to answer the question.
7. Your memories may include small or large jumps in time or context. You are not confused by this. You just did not bother to remember everything in between.
8. Your memories are ordered from earliest to latest. Prioritize the latest memories if anything has changed over time. Consider the question datetime when determining whether an event has actually occurred.
</instructions>

<memories>
{joined_history}
</memories>

Question timestamp: {question_timestamp}
Question: {question}
Your short response to the question without fluff (no more than a couple of sentences):
"""
```

**핵심 지시문:**
- 직접적인 메모리 우선
- 복수 정답 모두 나열
- 카운팅은 숫자로 열거
- 시간 간격은 빼기로 계산
- 사용자 맞춤형 추천
- episodic memory 특성 명시
- 시간/컨텍스트 점프 허용
- 최신 메모리 우선

---

### 2.2 EDWIN2_ANSWER_PROMPT (라인 114-137)

**정확한 라인 범위:** 114-137 (24 줄)

```python
EDWIN2_ANSWER_PROMPT = """
[EDWIN1 과 동일한 1-8 번 지시문]
9. If some detail in your recalled memories and the question does not match, assume that both the detail and the question are correct. Do not assume that you have enough information to answer the question.
</instructions>

<memories>
{joined_history}
</memories>

Question timestamp: {question_timestamp}
Question: {question}
Your short response to the question without fluff (no more than a couple of sentences):
"""
```

**EDWIN1 과 차이점:**
- **9 번 지시문 추가**: 메모리와 질문 불일치 시 둘 다 정확하다고 가정
- 불완전 정보 가정 금지

---

### 2.3 EDWIN3_ANSWER_PROMPT (라인 139-158)

**정확한 라인 범위:** 139-158 (20 줄)

```python
EDWIN3_ANSWER_PROMPT = """
You are a helpful assistant with access to extensive conversation history.
When answering questions, carefully review the conversation history to identify and use any relevant user preferences, interests, or specific details they have mentioned.

<history>
{joined_history}
</history>

IMPORTANT: When responding, reference specific details from these observations. Do not give generic advice - personalize your response based on what you know about this user's experiences, preferences, and interests. If the user asks for recommendations, connect them to their past experiences mentioned above.

KNOWLEDGE UPDATES: When asked about current state (e.g., "where do I currently...", "what is my current..."), always prefer the MOST RECENT information. Observations include dates - if you see conflicting information, the newer observation supersedes the older one. Look for phrases like "will start", "is switching", "changed to", "moved to" as indicators that previous information has been updated.

PLANNED ACTIONS: If the user stated they planned to do something (e.g., "I'm going to...", "I'm looking forward to...", "I will...") and the date they planned to do it is now in the past (check the relative time like "3 weeks ago"), assume they completed the action unless there's evidence they didn't. For example, if someone said "I'll start my new diet on Monday" and that was 2 weeks ago, assume they started the diet.

MOST RECENT USER INPUT: Treat the most recent user message as the highest-priority signal for what to do next. Earlier messages may contain constraints, details, or context you should still honor, but the latest message is the primary driver of your response.

Current date: {question_timestamp}
Question: {question}
"""
```

**핵심 지시문 (EDWIN1/2 와 완전히 다른 구조):**
- 구체적 세부사항 참조 (일반적 조언 금지)
- **최신 정보 우선**: 충돌 시 새로운 정보가 덮어씀
- **계획된 행동 추론**: 과거에 계획한 일이 현재 시점에서 지났으면 완료된 것으로 가정
- **최신 사용자 입력 최우선**

---

## 3. EDWIN Prompt 사용 방식

### 3.1 CLI 옵션 정의

**파일:** `main.py` (라인 94-96)

```python
common_parser.add_argument(
    "--answer-prompt", help="[simple | cot | edwin1] def=cot"
)
```

**주의:** Help 메시지는 `edwin1` 까지만 표기되어 있으나, 실제로는 `edwin2`, `edwin3` 도 사용 가능합니다.

**사용 예:**
```bash
python main.py search-eval \
  --answer-prompt edwin3 \
  ...
```

---

### 3.2 Prompt 선택 로직

**파일:** `lmelib/prompt.py` (라인 183-201)

**정확한 라인 범위:** 183-201 (19 줄)

**참고:** 실제 prompt 선택은 `qa_eval()` 함수에서 수행됨 (라인 164-241)

```python
answer_prompt = None
if mmai:
    answer_prompt = mmai.lme_answer_prompt
if answer_prompt:
    answer_prompt = answer_prompt.upper()
else:
    answer_prompt = 'COT'

if answer_prompt == 'SIMPLE':
    prompt = SIMPLE_ANSWER_PROMPT
elif answer_prompt == 'COT':
    prompt = COT_ANSWER_PROMPT
elif answer_prompt == 'EDWIN1':
    prompt = EDWIN1_ANSWER_PROMPT
elif answer_prompt == 'EDWIN2':
    prompt = EDWIN2_ANSWER_PROMPT
elif answer_prompt == 'EDWIN3':
    prompt = EDWIN3_ANSWER_PROMPT
else:
    raise AssertionError(f'ERROR: unknown prompt name={answer_prompt}')
```

**동작 방식:**
1. `mmai.lme_answer_prompt` 에서 값 읽기
2. 대문자로 변환 (`edwin3` → `EDWIN3`)
3. 기본값: `COT`
4. 해당 prompt 템플릿 선택

---

### 3.3 환경 변수 설정

**파일:** `main.py`
- Ingest: 라인 240-245
- Search-Eval: 라인 293-299
- Judge: 라인 346-352

```python
# Ingest 단계
mmai.lme_ingest_prompt = args.ingest_prompt
mmai.lme_context_prompt = args.context_prompt
mmai.lme_search_prompt = args.search_prompt
mmai.lme_answer_prompt = args.answer_prompt
mmai.lme_temperature = args.temperature

# Search-Eval 단계
mmai.lme_ingest_prompt = args.ingest_prompt
mmai.lme_context_prompt = args.context_prompt
mmai.lme_search_prompt = args.search_prompt
mmai.lme_answer_prompt = args.answer_prompt
mmai.lme_temperature = args.temperature

# Judge 단계
mmai.lme_ingest_prompt = args.ingest_prompt
mmai.lme_context_prompt = args.context_prompt
mmai.lme_search_prompt = args.search_prompt
mmai.lme_answer_prompt = args.answer_prompt
mmai.lme_temperature = args.temperature
```

**특징:**
- 모든 단계 (ingest, search-eval, judge) 에서 동일한 answer_prompt 사용
- `mmai` (MemmachineHelper) 객체에 저장되어 전역적으로 참조됨

**주의:** `ingest` 단계에서는 answer_prompt 가 실제로 사용되지 않음 (ingest 는 데이터 적재만 수행).
Answer prompt 는 `search-eval` 단계의 answer 생성 시에만 사용됨.

---

## 4. EDWIN Prompt 활용 예시

### 4.1 기본 실험 (EDWIN3 사용)

```bash
cd /home/tj/Workspace/memmachine-test/benchmark/longmemeval

# Ingest
python main.py ingest \
  --ingest-prompt role \
  --context-prompt json-str \
  --search-prompt user-q \
  --answer-prompt edwin3

# Search-Eval
python main.py search-eval \
  --limit 30 \
  --type memmachine \
  --ingest-prompt role \
  --context-prompt json-str \
  --search-prompt user-q \
  --answer-prompt edwin3 \
  --temperature 1.0

# Judge
python main.py judge \
  --model gpt-4o-mini \
  --ingest-prompt role \
  --context-prompt json-str \
  --search-prompt user-q \
  --answer-prompt edwin3 \
  --input-file results/memmachine_search_eval_results.json \
  --output-file results/memmachine_scores.json
```

---

### 4.2 EDWIN 비교 실험

```bash
# EDWIN1 테스트
python main.py search-eval \
  --answer-prompt edwin1 \
  --output-file results/edwin1_results.json

# EDWIN2 테스트
python main.py search-eval \
  --answer-prompt edwin2 \
  --output-file results/edwin2_results.json

# EDWIN3 테스트
python main.py search-eval \
  --answer-prompt edwin3 \
  --output-file results/edwin3_results.json
```

---

## 5. EDWIN Prompt 진화 배경

### 5.1 이름 유래

**EDWIN** 의 정확한 유래는 문서화되어 있지 않음.

추정:
- **Ed** (에피소딕 메모리) + **Win** (승리/최적화)
- 또는 사람 이름 "Edwin" 차용

MemVerge 내부에서 episodic memory 활용을 위해 개발된 프롬프트 시리즈.

---

### 5.2 버전별 개선 포인트

| 버전 | 개선 사항 |
|------|-----------|
| **EDWIN1** | 기본 episodic memory 활용, 8 개 지시문 |
| **EDWIN2** | 불일치 처리 추가 (9 번 지시문) |
| **EDWIN3** | 구조 변경, 최신 정보 우선, 계획 추론 추가. **실제 권장 버전** |

### 5.3 실제 사용 권장사항

Tom.W 의 이메일에 따르면, **EDWIN3** 가 기본 권장 프롬프트입니다:

> "edwin3" is the default answer prompt used for most QA benchmark experiments.

이유:
- 최신 정보 우선 처리 (지식 업데이트)
- 계획된 행동에 대한 추론 (과거 계획 → 완료 가정)
- 사용자 입력의 시간적 우선순위 반영

---

## 6. eval_mm/MemMachine 과 비교

| 항목 | memmachine-test | eval_mm/MemMachine |
|------|-----------------|--------------------|
| **Prompt 수** | 5 가지 (SIMPLE, COT, EDWIN1-3) | 1 가지 (Agent Lightning) |
| **CLI 옵션** | `--answer-prompt` | 고정 |
| **출처** | MemVerge 내부 | Agent Lightning 논문 |
| **특징** | Episodic memory 최적화 | 상세 지시문 (6 개) |

---

## 7. 요약

### EDWIN Prompt 위치
- **정의:** `lmelib/prompt.py` (라인 90-158)
- **사용:** `main.py` CLI 옵션 → `mmai.lme_answer_prompt` → `qa_eval()` 함수 (라인 164-241)

### EDWIN Prompt 특징
1. **Episodic memory 활용 최적화**: 메모리 기반 추론에 특화된 지시문
2. **버전 관리**: EDWIN1 → EDWIN2 → EDWIN3 점진적 개선
3. **CLI 선택 가능**: `--answer-prompt edwin3` 형식
4. **전역 설정**: ingest/search/judge 모든 단계에서 동일 prompt 사용

### 권장 사용법
- **기본 실험:** `edwin3` (최신 정보 우선, 계획 추론) - **Tom.W 권장**
- **불일치 분석:** `edwin2` (메모리 - 질문 불일치 허용)
- **기본 추론:** `cot` (단계별 추론)

### 주의사항
1. **CLI help 메시지는 outdated**: `edwin1` 까지만 표기되어 있으나 `edwin2`, `edwin3` 도 사용 가능
2. **Ingest 단계에서는 무시**: answer_prompt 는 search-eval 에서만 사용됨
3. **온도 설정**: `--temperature 1.0` 이 기본값 (창의성 증가)
4. **기본값은 COT**: `--answer-prompt` 미지정 시 `COT` 사용됨

---

## 8. 검증 체크리스트

| 항목 | 문서 내용 | 소스 코드 | 상태 |
|------|-----------|-----------|------|
| **파일 위치** | `lmelib/prompt.py` | `lmelib/prompt.py` | ✅ |
| **프롬프트 수** | 5 가지 | 5 가지 (SIMPLE, COT, EDWIN1-3) | ✅ |
| **EDWIN1 라인** | 90-111 | 90-111 | ✅ |
| **EDWIN2 라인** | 114-137 | 114-137 | ✅ |
| **EDWIN3 라인** | 139-158 | 139-158 | ✅ |
| **CLI 옵션** | `--answer-prompt` | `main.py:95` | ✅ |
| **기본값** | `COT` | `prompt.py:189` | ✅ |
| **대문자 변환** | `answer_prompt.upper()` | `prompt.py:187` | ✅ |
| **qa_eval 함수** | 라인 164-241 | 라인 164-241 | ✅ |
