# Retrieval-Agent Benchmark Judge 분석

**작성일:** 2026-04-30  
**목적:** evaluation/retrieval_agent 의 LLM Judge 사용 방식 분석

---

## 1. 개요

`evaluation/retrieval_agent/llm_judge.py` 는 retrieval-agent 기반 모든 benchmark 에서 **공통으로 사용되는 평가 모듈**입니다.

---

## 2. Judge 사용 흐름

### 2.1 전체 파이프라인

```
┌─────────────────────────────────────────────────────────┐
│ 1. Search 스크립트 실행                                   │
│    ├─ longmemeval_test.py                               │
│    ├─ hotpotQA_test.py                                  │
│    ├─ wikimultihop_search.py                            │
│    └─ locomo_search.py                                  │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. evaluate.py 실행 (공통)                                │
│    └─ llm_judge.py import                               │
│       ├─ create_judge_fn()                              │
│       └─ evaluate_llm_judge()                           │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. generate_scores.py 실행 (점수 집계)                    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 run_test.sh 에서의 호출

**라인 524** (`evaluation/retrieval_agent/run_test.sh`):

```bash
EVALUATE_CMD=("${PYTHON_CMD[@]}" "$SCRIPT_DIR/evaluate.py" \
  --data-path "$RESULT_FILE" \
  --target-path "$EVAL_FILE" \
  --config-path "$CONFIG_FILE")
```

모든 benchmark 가 동일한 `evaluate.py` 를 호출하며, 이 파일이 `llm_judge.py` 를 사용합니다.

---

## 3. llm_judge.py 상세 분석

### 3.1 파일 위치

```
evaluation/retrieval_agent/llm_judge.py
```

### 3.2 주요 함수

#### `create_judge_fn(config_path: str) -> Callable[[str], str]`

configuration.yml 에서 judge LLM 설정을 읽고, 실제로 LLM 을 호출하는 callable 을 반환합니다.

**지원하는 provider:**
- `openai-responses` (OpenAI Responses API)
- `openai-chat-completions` (OpenAI Chat Completions API, Ollama, vLLM 등)
- `amazon-bedrock` (AWS Bedrock Converse API)

#### `evaluate_llm_judge(question, gold_answer, generated_answer, call_fn) -> int`

질문, 정답, 모델 답변을 받아 CORRECT(1) 또는 WRONG(0) 으로 평가합니다.

**재시도 로직:**
- 최대 2 회 재시도 (`_MAX_JUDGE_ATTEMPTS = 2`)
- JSON 파싱 실패 시 재시도
- 모든 시도 실패 시 기본값 0 (WRONG) 반환

### 3.3 Judge Prompt

```python
ACCURACY_PROMPT = """
Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. 
You will be given the following data:
    (1) a question (posed by one user to another user),
    (2) a 'gold' (ground truth) answer,
    (3) a generated answer
which you will score as CORRECT/WRONG.

...

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""
```

**출력 형식:**
```json
{"label": "CORRECT"}
```
또는
```json
{"label": "WRONG"}
```

---

## 4. Configuration 통합

### 4.1 Judge LLM 설정

`configuration.yml` 에서 다음 두 필드로 judge LLM 을 설정합니다:

```yaml
retrieval_agent:
  llm_model: openai_model          # Answer 생성용 LLM
  judge_llm_model: judge_model     # Judge 용 LLM (선택, 생략 시 llm_model 사용)
```

### 4.2 Judge LLM 정의

`configs/profiles/models/*.yaml` 에서 judge_llm 블록으로 정의:

```yaml
llm_model:
  provider: openai-chat-completions
  config:
    api_key: sk-...
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini

judge_llm:
  id: my_judge
  provider: openai-chat-completions
  config:
    api_key: sk-...
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
```

### 4.3 3 가지 용어 정리

| 용어 | 위치 | 역할 |
|------|------|------|
| `judge_llm:` 블록 | model profile YAML (`configs/profiles/models/*.yaml`) | Judge LLM **리소스** 정의 (id/provider/config) |
| `retrieval_agent.judge_llm_model` | generated `configuration.yml` | Judge 가 실제로 읽는 포인터. `generate_config.py` 가 profile 에서 채움 |
| `--judge-model` | CLI 인자 | 실행 시 override. 이미 등록된 ID 만 지정 가능 |

---

## 5. Benchmark 별 사용 현황

### 5.1 llm_judge.py 를 사용하는 benchmark

| Benchmark | 스크립트 | Judge 사용 |
|-----------|----------|------------|
| **LongMemEval** | `longmemeval_test.py` | ✅ `evaluate.py` 통해 사용 |
| **HotpotQA** | `hotpotQA_test.py` | ✅ `evaluate.py` 통해 사용 |
| **WikiMultiHop** | `wikimultihop_search.py` | ✅ `evaluate.py` 통해 사용 |
| **LoCoMo** | `locomo_search.py` | ✅ `evaluate.py` 통해 사용 |

### 5.2 공통 evaluate.py 흐름

**파일:** `evaluation/retrieval_agent/evaluate.py`

```python
from evaluation.retrieval_agent.llm_judge import (
    create_judge_fn,
    evaluate_llm_judge,
)

def process_sample(group_key: str, item: dict, call_fn):
    question = str(item["question"])
    locomo_answer = str(item["golden_answer"])
    response = str(item["model_answer"])
    category = str(item["category"])

    # Skip category 5
    if category == "5":
        return group_key, None

    llm_score = evaluate_llm_judge(question, locomo_answer, response, call_fn)

    return group_key, {
        "question": question,
        "answer": locomo_answer,
        "response": response,
        "category": category,
        "llm_score": llm_score,  # 1 (CORRECT) or 0 (WRONG)
    }
```

---

## 6. 주의사항

### 6.1 episodic_memory 는 별개

`evaluation/episodic_memory/llm_judge.py` 는 **완전히 별개의 파일**입니다:

| 항목 | retrieval_agent | episodic_memory |
|------|-----------------|-----------------|
| **파일** | `evaluation/retrieval_agent/llm_judge.py` | `evaluation/episodic_memory/llm_judge.py` |
| **Judge Prompt** | CORRECT/WRONG (JSON) | CORRECT/WRONG (JSON) |
| **설정** | configuration.yml 지원 | Hardcoded (`gpt-4o-mini`) |
| **Provider** | openai-responses, openai-chat-completions, amazon-bedrock | OpenAI 만 |
| **재시도** | ✅ 최대 2 회 | ✅ 최대 2 회 |
| **사용처** | retrieval-agent benchmark | LoCoMo episodic memory 평가 |

**중요:** retrieval-agent benchmark 는 **오직** `evaluation/retrieval_agent/llm_judge.py` 만 사용합니다.

### 6.2 Category 5 제외

`evaluate.py` 에서 category 5 는 평가에서 제외됩니다:

```python
if category == "5":
    return group_key, None
```

이는 LongMemEval 의 abstention 질문 유형을 처리하기 위한 로직입니다.

### 6.3 병렬 처리

`evaluate.py` 는 `concurrent.futures.ThreadPoolExecutor` 를 사용하여 병렬 평가합니다:

```bash
# Judge concurrency 지정
./run_test.sh locomo exp1 search retrieval_agent 10 --judge-concurrency 4
```

---

## 7. 실행 예시

### 7.1 WikiMultiHop

```bash
cd evaluation/retrieval_agent

# Ingest
./run_test.sh wikimultihop exp1 ingest retrieval_agent 500

# Search + Eval (llm_judge.py 자동 실행)
./run_test.sh wikimultihop exp1 search retrieval_agent 500

# Search 만 수행하고 eval 은 수동
./run_test.sh wikimultihop exp1 search retrieval_agent 500 --skip-eval

# 수동 eval 실행
python evaluate.py \
  --data-path results/wikimultihop_search_results.json \
  --target-path results/wikimultihop_eval.json \
  --config-path configuration.yml
```

### 7.2 LongMemEval

```bash
cd evaluation/retrieval_agent

# Ingest
./run_test.sh longmemeval exp1 ingest retrieval_agent 100

# Search + Eval
./run_test.sh longmemeval exp1 search retrieval_agent 100

# Judge concurrency 조절
./run_test.sh longmemeval exp1 search retrieval_agent 100 \
  --judge-concurrency 8
```

### 7.3 LoCoMo

```bash
cd evaluation/retrieval_agent

# Ingest (10 conversations)
./run_test.sh locomo exp1 ingest retrieval_agent 10

# Search + Eval
./run_test.sh locomo exp1 search retrieval_agent 10 \
  --judge-concurrency 4
```

---

## 8. 출력 결과

### 8.1 evaluate.py 출력

`--target-path` 에 지정된 파일에 JSON 형식으로 저장:

```json
{
  "group_key_1": [
    {
      "question": "What did Alice buy last week?",
      "answer": "A book",
      "response": "Alice bought a book last week.",
      "category": "single-session-user",
      "llm_score": 1
    },
    {
      "question": "When did Bob move to LA?",
      "answer": "May 2023",
      "response": "Bob moved to LA in June 2023.",
      "category": "temporal-reasoning",
      "llm_score": 0
    }
  ]
}
```

### 8.2 generate_scores.py 출력

최종 점수 집계 (category 별 평균):

```
Mean Scores Per Category:
            llm_score  count
category
single-session-user    0.8500     20
single-session-assistant 0.7500     20
multi-session          0.6000     20
temporal-reasoning     0.5500     20
knowledge-update       0.7000     20

Overall Mean Scores:
llm_score    0.6900
```

---

## 9. 요약

### ✅ 핵심 결론

1. **단일 구현**: 모든 retrieval-agent benchmark 가 동일한 `llm_judge.py` 사용
2. **Configuration 기반**: `configuration.yml` 에서 judge LLM 설정
3. **다중 Provider 지원**: OpenAI, Ollama/vLLM, AWS Bedrock
4. **재시도 로직**: JSON 파싱 실패 시 최대 2 회 재시도
5. **병렬 처리**: `--judge-concurrency` 로 동시성 조절 가능

### ⚠️ 주의사항

1. **episodic_memory 와 혼동 금지**: 별개 파일, 별개 설정
2. **Category 5 제외**: abstention 질문은 평가에서 자동 제외
3. **Judge 일관성**: 동일 실험 내에서는 동일한 judge 설정 사용

### 📋 권장 사용법

1. **Judge 통일**: 외부 결과와 비교 시 동일한 judge 모델 사용
2. **Concurrency 조절**: 대규모 평가 시 `--judge-concurrency` 로 속도 개선
3. **설정 명시**: 모든 결과에 사용된 judge 모델 명시 (`configuration.yml` 사본 보관)

---

## 부록: 관련 파일 목록

```
evaluation/retrieval_agent/
├── llm_judge.py                      # Judge 로직 (CORRECT/WRONG)
├── evaluate.py                       # 평가 실행 (llm_judge.py 사용)
├── generate_scores.py                # 점수 집계
├── run_test.sh                       # 통합 실행 스크립트
├── longmemeval_test.py               # LongMemEval benchmark
├── hotpotQA_test.py                  # HotpotQA benchmark
├── wikimultihop_search.py            # WikiMultiHop benchmark
├── locomo_search.py                  # LoCoMo benchmark
└── README.md                         # 설정 가이드
```
