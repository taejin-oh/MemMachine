# LongMemEval Judge Prompt 리팩토링 리뷰

**작성일:** 2026-04-30  
**리뷰어:** Claude Code  
**대상:** `evaluation/retrieval_agent/llm_judge.py` 및 `evaluate.py` 수정사항

---

## 📋 개요

원본 LongMemEval (`/home/tj/Workspace/LongMemEval`) 의 judge prompt 와 평가 방식을 `eval_mm/MemMachine` 에 적용한 수정사항에 대한 리뷰 결과입니다.

---

## ✅ 잘 적용된 항목

### 1. Judge Prompt 복사 (llm_judge.py 라인 44-90)

```python
# LongMemEval task-specific judge templates copied verbatim from
# https://github.com/xiaowu0162/LongMemEval (src/evaluation/evaluate_qa.py).
_LME_TEMPLATE_GENERAL = (...)
_LME_TEMPLATE_TEMPORAL = (...)  # off-by-one 오류 허용
_LME_TEMPLATE_KNOWLEDGE_UPDATE = (...)
_LME_TEMPLATE_PREFERENCE = (...)
_LME_TEMPLATE_ABSTENTION = (...)
```

**평가:** ✅ 원본과 완전히 동일하게 복사됨

---

### 2. Task 분류 (llm_judge.py 라인 92-119)

```python
_LME_GENERAL_TASKS = frozenset(
    {"single-session-user", "single-session-assistant", "multi-session"}
)

def get_anscheck_prompt(task, question, answer, response, abstention=False):
    if abstention:
        return _LME_TEMPLATE_ABSTENTION.format(...)
    if task in _LME_GENERAL_TASKS:
        return _LME_TEMPLATE_GENERAL.format(...)
    if task == "temporal-reasoning":
        return _LME_TEMPLATE_TEMPORAL.format(...)
    ...
```

**평가:** ✅ 6 가지 task 유형 모두 정확히 처리됨

| Task 유형 | 설명 |
|-----------|------|
| `single-session-user` | 단일 세션 사용자 질문 |
| `single-session-assistant` | 단일 세션 어시스턴트 질문 |
| `multi-session` | 다중 세션 질문 |
| `temporal-reasoning` | 시간 추론 (off-by-one 오류 허용) |
| `knowledge-update` | 지식 업데이트 (최신 정보 우선) |
| `single-session-preference` | 사용자 선호도 |

---

### 3. Yes/No 파싱 (llm_judge.py 라인 325-339)

```python
_YES_NO_RE = re.compile(r"\A\s*(yes|no)[\s.!?,]*\Z", re.IGNORECASE)

def _parse_yes_no(raw: str) -> int:
    match = _YES_NO_RE.match(raw or "")
    if match is None:
        return 0
    return 1 if match.group(1).lower() == "yes" else 0
```

**평가:** ✅ 원본보다 더 엄격한 파싱 (substring 매칭 방지)

| 원본 LongMemEval | 수정 후 |
|-----------------|---------|
| `'yes' in raw.lower()` (substring 매칭) | 정규식으로 정확히 `yes`/`no` 만 인식 |
| `yesterday` 도 `yes` 로 인식될 수 있음 | `yes` 단독일 때만 인식 |

---

### 4. LongMemEval 전용 평가 함수 (llm_judge.py 라인 342-362)

```python
def evaluate_llm_judge_longmemeval(
    question: str,
    gold_answer: str,
    generated_answer: str,
    question_type: str,
    question_id: str,
    call_fn: Callable[[str], str],
) -> int:
    abstention = "_abs" in question_id
    prompt = get_anscheck_prompt(...)
    return _parse_yes_no(call_fn(prompt) or "")
```

**평가:** ✅ Abstention 감지 (`_abs` substring) 완벽 구현

---

### 5. JSON 모드 전환 (llm_judge.py 라인 122-267)

```python
def create_judge_fn(config_path: str, json_mode: bool = True)
```

**평가:** ✅ 이중 용도 지원

| 모드 | 용도 | 출력 형식 |
|------|------|-----------|
| `json_mode=True` (기본값) | 기존 ACCURACY_PROMPT 용도 | JSON `{"label": "CORRECT"}` |
| `json_mode=False` | LongMemEval 용도 | 텍스트 `yes`/`no` |

---

### 6. Evaluate.py 라우팅 (evaluate.py 라인 52-62)

```python
if category in _LONGMEMEVAL_TASKS:
    llm_score = evaluate_llm_judge_longmemeval(
        question,
        locomo_answer,
        response,
        category,
        str(item.get("question_id", "")),
        get_text_call_fn(),
    )
else:
    llm_score = evaluate_llm_judge(question, locomo_answer, response, json_call_fn)
```

**평가:** ✅ Task 기반 자동 라우팅 완벽 구현

---

### 7. Thread-safe `json_mode=False` call_fn 생성 (evaluate.py 라인 128-137)

```python
text_call_fn = None
text_call_fn_lock = threading.Lock()

def get_text_call_fn():
    nonlocal text_call_fn
    if text_call_fn is None:
        with text_call_fn_lock:
            if text_call_fn is None:
                text_call_fn = create_judge_fn(args.config_path, json_mode=False)
    return text_call_fn
```

**평가:** ✅ Lock 으로 동시성 안전성 보장

---

## 📊 완성도 평가

| 항목 | 상태 | 비고 |
|------|------|------|
| **Judge Prompt 복사** | ✅ | 원본과 100% 동일 |
| **Task 분류** | ✅ | 6 가지 모두 처리 |
| **Yes/No 파싱** | ✅ | 더 엄격하게 개선 |
| **Abstention 감지** | ✅ | `_abs` substring |
| **JSON 모드 분리** | ✅ | `json_mode` 파라미터 |
| **Evaluate 라우팅** | ✅ | Task 기반 자동 선택 |
| **Thread Safety** | ✅ | Lock 으로 동시성 안전 |
| **하위 호환성** | ✅ | 기존 benchmark 도 계속 동작 |

---

## 🎯 적용 결과

### LongMemEval 데이터셋 사용 시:

- ✅ **자동으로 원본 Judge 적용** (task-specific prompt)
- ✅ **Yes/No 출력** (원본 방식)
- ✅ **Off-by-one 오류 허용** (temporal-reasoning)
- ✅ **Knowledge update 처리** (최신 정보 우선)

### 기타 데이터셋 (LoCoMo, HotpotQA, WikiMultiHop):

- ✅ **기존 ACCURACY_PROMPT 유지** (CORRECT/WRONG JSON)
- ✅ **하위 호환성 보장**

---

## 📈 비교 정리

### 수정 전:

```
모든 데이터셋 → ACCURACY_PROMPT (CORRECT/WRONG JSON)
```

### 수정 후:

```
LongMemEval → task-specific prompt (yes/no 텍스트)
기타 데이터셋 → ACCURACY_PROMPT (CORRECT/WRONG JSON)
```

---

## 🎉 결론

**완벽하게 수정되었습니다!**

원본 LongMemEval 의 평가 방식을 정확히 구현하면서도, 기존 benchmark 와의 하위 호환성도 유지한 훌륭한 구현입니다.

---

## 🔗 관련 파일

- `/home/tj/Workspace/eval_mm/MemMachine/evaluation/retrieval_agent/llm_judge.py`
- `/home/tj/Workspace/eval_mm/MemMachine/evaluation/retrieval_agent/evaluate.py`
- `/home/tj/Workspace/LongMemEval/src/evaluation/evaluate_qa.py` (원본)
