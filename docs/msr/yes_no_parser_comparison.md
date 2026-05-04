# Yes/No Parser 비교 분석

**작성일:** 2026-05-04  
**목적:** LongMemEval, memmachine-test, eval_mm/MemMachine 의 yes/no 파서 구현 비교

---

## 1. 구현체별 비교

### 1.1 Original LongMemEval

**파일:** `/home/tj/Workspace/LongMemEval/src/evaluation/evaluate_qa.py`  
**라인:** 113

```python
label = 'yes' in eval_response.lower()
```

**특징:**
- ✅ 대소문자 구분 없음 (`lower()`)
- ❌ **substring 매칭** — `"yesterday"` 도 `yes` 로 인식
- ❌ `"yes and no"` 도 `yes` 로 인식 (모호한 응답 처리 불가)
- ❌ `"not yes"` 도 `yes` 로 인식 (부정문 처리 불가)

---

### 1.2 memmachine-test

**파일:** `/home/tj/Workspace/memmachine-test/benchmark/longmemeval/memlib/common/judge.py`  
**라인:** 79

```python
llm_score = 1 if "yes" in answer else 0
```

**특징:**
- ❌ **대소문자 구분** — `"YES"` 인식 불가
- ❌ **substring 매칭** — `"yesterday"` 도 `yes` 로 인식
- ❌ `"yes and no"` 도 `yes` 로 인식 (모호한 응답 처리 불가)

---

### 1.3 eval_mm/MemMachine (수정 후)

**파일:** `/home/tj/Workspace/eval_mm/MemMachine/evaluation/retrieval_agent/llm_judge.py`  
**라인:** 325-339

```python
_YES_NO_RE = re.compile(r"\A\s*(yes|no)[\s.!?,]*\Z", re.IGNORECASE)

def _parse_yes_no(raw: str) -> int:
    match = _YES_NO_RE.match(raw or "")
    if match is None:
        return 0
    return 1 if match.group(1).lower() == "yes" else 0
```

**특징:**
- ✅ **전체 문자열 매칭** — substring 위조 방지
- ✅ 대소문자 구분 없음 (`re.IGNORECASE`)
- ✅ 선행/후행 공백 허용
- ✅ trailing punctuation 허용 (`.` `!` `?` `,`)
- ✅ `"yes and no"`, `"not yes"`, `"yesterday"` 모두 거부

---

## 2. 테스트 케이스별 동작 비교

| 입력 | LongMemEval | memmachine-test | eval_mm (수정 후) | 비고 |
|------|-------------|-----------------|-------------------|------|
| `"yes"` | ✅ 1 | ✅ 1 | ✅ 1 | 정상 |
| `"YES"` | ✅ 1 | ❌ 0 | ✅ 1 | 대소문자 |
| `"yes."` | ✅ 1 | ✅ 1 | ✅ 1 | punctuation |
| `"  yes  "` | ✅ 1 | ✅ 1 | ✅ 1 | whitespace |
| `"yesterday"` | ❌ 1 (FP) | ✅ 0 | ✅ 0 | **substring trap** |
| `"not yes"` | ❌ 1 (FP) | ❌ 1 (FP) | ✅ 0 | **부정문** |
| `"yes and no"` | ❌ 1 (FP) | ❌ 1 (FP) | ✅ 0 | **모호한 응답** |
| `"I think yes"` | ❌ 1 (FP) | ❌ 1 (FP) | ✅ 0 | **verbose** |
| `"no"` | ✅ 0 | ✅ 0 | ✅ 0 | 정상 |
| `"NO"` | ✅ 0 | ✅ 0 | ✅ 0 | 대소문자 |

**범례:**
- ✅ 1: 의도한 대로 `yes` 인식
- ✅ 0: 의도한 대로 `no` 인식
- ❌ 1 (FP): False Positive — `no` 여야 하지만 `yes` 로 인식

---

## 3. 정규식 상세 분석

### 3.1 `_YES_NO_RE` 구성 요소

```python
r"\A\s*(yes|no)[\s.!?,]*\Z"
```

| 구성 요소 | 의미 | 예시 |
|-----------|------|------|
| `\A` | 문자열 시작 | `^` 와 동일 |
| `\s*` | 0 개 이상의 공백 | `""`, `" "`, `"   "` |
| `(yes|no)` | `yes` 또는 `no` | `"yes"`, `"no"` |
| `[\s.!?,]*` | 공백/구두점 0 개 이상 | `""`, `"."`, `"  !"` |
| `\Z` | 문자열 종료 | `$` 와 동일 |
| `re.IGNORECASE` | 대소문자 무시 | `"YES"`, `"Yes"` 모두 매칭 |

---

### 3.2 매칭/비매칭 예시

**매칭되는 문자열:**
- `"yes"`, `"no"`
- `"YES"`, `"No"`, `"nO"`
- `"yes."`, `"no!"`, `"yes?"`, `"no,"`
- `"  yes  "`, `"   no   "`
- `"yes   ."`, `"no  !"`

**매칭되지 않는 문자열:**
- `"yesterday"` — `yes` 이후 추가 문자
- `"not yes"` — `yes` 이전에 추가 문자
- `"yes and no"` — `yes` 이후 추가 문자
- `"I think yes"` — `yes` 이전에 추가 문자
- `"yes no"` — 두 토큰 모두 존재
- `"yess"`, `"yesss"` — 철자 오류

---

## 4. 개선 효과

### 4.1 원본 LongMemEval 의 문제점

```python
# LongMemEval 원본 (line 113)
label = 'yes' in eval_response.lower()

# 문제 시나리오
eval_response = "The model said yesterday, not yes."
# 'yes' 가 포함되어 있으므로 1 로 처리됨 (False Positive)
```

### 4.2 수정 후 eval_mm

```python
# eval_mm 수정 후 (line 325-339)
match = _YES_NO_RE.match("The model said yesterday, not yes.")
# match is None → 0 반환 (올바른 처리)
```

---

## 5. Judge Prompt 와의 관계

### 5.1 LongMemEval 원본 prompt

```python
_LME_TEMPLATE_GENERAL = (
    "Is the model response correct? Answer yes or no only."
)
```

**의도:** `yes` 또는 `no` 만 출력

**현실:** LLM 이 때로 verbose 한 응답을 출력할 수 있음
- `"Yes, the model is correct."`
- `"I think yes."`
- `"The answer is yes."`

### 5.2 파싱 전략 비교

| 전략 | 장점 | 단점 |
|------|------|------|
| **Substring** (원본) | 간단함, verbose 응답도 처리 | FP 위험 높음 |
| **Full-string regex** (수정 후) | FP 방지, 엄격함 | LLM 이 verbose 하면 거부 |

### 5.3 절충안 (참고)

```python
# First char check + strict fallback
def _parse_yes_no_lenient(raw: str) -> int:
    raw = raw.strip().lower()
    if raw in ("yes", "no"):
        return 1 if raw == "yes" else 0
    # Fallback: first word
    first_word = raw.split()[0] if raw.split() else ""
    if first_word in ("yes", "no"):
        return 1 if first_word == "yes" else 0
    return 0  # Default to WRONG
```

**현재 선택:** 엄격한 풀스트링 매칭 (FP 방지 우선)

---

## 6. 실제 영향도

### 6.1 예상 FP율 (Original LongMemEval)

Tom.W 의 LongMemEval 원본 구현에서 substring 매칭은 다음과 같은 FP 를 발생시킬 수 있습니다:

- `"yesterday"` → `yes` (시간 관련 질문에서 빈번)
- `"eyes"` → `yes` (오타 시)
- `"convey"` → `yes` (드물지만 가능)

**예상 FP율:** 전체 샘플의 1-3% (추정)

### 6.2 eval_mm 수정 후

- FP: 0% (이론상)
- FN (False Negative): LLM 이 verbose 하면 발생 가능

**권장:** LLM 이 prompt 를 잘 따르는지 샘플 검사

---

## 7. 검증 체크리스트

| 항목 | LongMemEval | memmachine-test | eval_mm (수정 후) |
|------|-------------|-----------------|-------------------|
| **대소문자 처리** | ✅ `lower()` | ❌ case-sensitive | ✅ `re.IGNORECASE` |
| **Substring FP** | ❌ 발생 | ❌ 발생 | ✅ 방지 |
| **Whitespace 허용** | ✅ 암시적 | ✅ 암시적 | ✅ 명시적 |
| **Punctuation 허용** | ✅ 암시적 | ✅ 암시적 | ✅ 명시적 |
| **모호한 응답 거부** | ❌ | ❌ | ✅ |
| **부정문 처리** | ❌ | ❌ | ✅ |

---

## 8. 요약

### 8.1 세 구현체 비교

| 구현체 | 매칭 방식 | FP 위험 | 엄격도 |
|--------|-----------|---------|--------|
| **LongMemEval** | Substring (case-insensitive) | 높음 | 낮음 |
| **memmachine-test** | Substring (case-sensitive) | 높음 | 낮음 |
| **eval_mm** | Full-string regex | 없음 | 높음 |

### 8.2 권장 사항

1. **현재 구현 유지**: 엄격한 풀스트링 매칭이 FP 방지 측면에서 우수
2. **LLM 출력 모니터링**: verbose 응답이 빈번하면 prompt 조정 고려
3. **샘플 검사**: 실제 평가 결과에서 FP/FN 비율 확인 권장

### 8.3 향후 개선 방향

- **Hybrid 접근**: strict first, lenient fallback
- **LLM prompt 강화**: `"Return ONLY yes or no"` 강조
- **JSON mode 활용**: `{"answer": "yes"}` 형식 강제 (현재 `json_mode=False` 사용 중)

---

## 9. 관련 파일

- `/home/tj/Workspace/eval_mm/MemMachine/evaluation/retrieval_agent/llm_judge.py` (lines 325-339)
- `/home/tj/Workspace/LongMemEval/src/evaluation/evaluate_qa.py` (line 113)
- `/home/tj/Workspace/memmachine-test/benchmark/longmemeval/memlib/common/judge.py` (line 79)
