# LongMemEval Judge (원본 기반) 변경사항/동작/사용 주의사항 정리

## 0) 이 문서의 목적

이 문서는 MemMachine 저장소의 LongMemEval 관련 judge 경로가
원본 LongMemEval 코드 대비 어떻게 바뀌었는지, 현재 실제로 어떤 규칙으로
채점되는지, 그리고 실험/해석 시 무엇을 주의해야 하는지를 한 번에 정리한다.

대상 독자는 “코드를 처음 읽는 사람”이며, 재현평가 운영 문맥에서
바로 참고할 수 있게 작성했다.

---

## 1) 어디가 실제 judge 진입점인가

LongMemEval 채점은 현재 **두 진입점**이 있다.

1. 레거시 경로: `evaluation/retrieval_agent/evaluate.py`
2. eval wrapper(stage) 경로: `scripts/stages/judge.py`

두 경로 모두 공통으로 `evaluation/retrieval_agent/llm_judge.py` 의 함수를 사용하며,
LongMemEval task(`question_type`)이면 task-specific judge 로 라우팅한다.

---

## 2) 원본 LongMemEval 기반으로 무엇이 수정되었나

핵심은 아래 3가지다.

### 2.1 task-specific judge prompt 복원

`llm_judge.py`에 LongMemEval 원본 템플릿이 정적 문자열로 들어가 있으며,
`get_anscheck_prompt()`가 task별로 분기한다.

- general: `single-session-user`, `single-session-assistant`, `multi-session`
- temporal-reasoning: off-by-one day/week/month 오차 허용 문구 포함
- knowledge-update: 과거 정보가 섞여도 최신 정답이 있으면 정답 가능
- single-session-preference: rubric 기반 개인화 평가
- abstention: unanswerable 질문 판단용 프롬프트

즉, “한 장짜리 generic ACCURACY_PROMPT”만 쓰던 상태에서,
LongMemEval에 한해서는 원본 의도(문항 타입별 판정 지침)를 복원한 구조다.

### 2.2 abstention 판정 복원

`evaluate_llm_judge_longmemeval()`에서 `question_id`에 `"_abs"`가 포함되면
abstention prompt로 자동 전환한다.

즉, 원본 LongMemEval의 “답할 수 없는 문항을 맞게 거절했는지” 축이
다시 활성화된다.

### 2.3 yes/no 파싱을 더 엄격하게 변경

원본은 대체로 `'yes' in lower(text)` 류의 느슨한 해석이었는데,
현재는 `_parse_yes_no()`가 정규식으로 **전체 문자열이 yes/no 인지**를 본다.

허용 예: `yes`, `no`, `yes.`
비허용 예: `yes and no`, `not yes`, `yesterday`, `I think yes`

이건 원본 대비 보수적 변경이며, 모호한 출력을 오답(0) 처리하는 방향이다.

---

## 3) 실제 동작 플로우 (현재 코드 기준)

## 3.1 Judge LLM 선택

`create_judge_fn()`는 아래 우선순위로 모델 포인터를 고른다.

1. `retrieval_agent.judge_llm_model`
2. 없으면 `retrieval_agent.llm_model` fallback

지원 provider:
- `openai-responses`
- `openai-chat-completions`
- `amazon-bedrock`

ID가 `resources.language_models`에 없으면 명시적 `ValueError`를 낸다.

## 3.2 JSON judge vs Plain-text judge

- 일반 데이터셋 경로: JSON 모드 (`{"label": "CORRECT|WRONG"}`)
- LongMemEval 경로: plain-text 모드 (`yes|no` 기대)

`scripts/stages/judge.py`는 category가 LongMemEval task 집합에 들어오면
`evaluate_llm_judge_longmemeval()`로, 아니면 `evaluate_llm_judge()`로 라우팅한다.

## 3.3 LongMemEval 라우팅 키

라우팅은 row의 `category` 문자열 매칭으로 결정된다.
허용 task 집합:

- `single-session-user`
- `single-session-assistant`
- `multi-session`
- `temporal-reasoning`
- `knowledge-update`
- `single-session-preference`

이 값이 어긋나면 LongMemEval여도 generic judge 경로로 빠질 수 있으므로,
retrieve/generate 산출물의 `category` 정합성 확인이 중요하다.

---

## 4) 사용할 때 반드시 인지해야 할 점

### 4.1 “원본과 완전 동일”은 아님

프롬프트 분기와 abstention은 원본 의도를 복원했지만,
yes/no 파싱은 원본보다 엄격하다.
따라서 동일 응답이라도 원본과 점수가 달라질 수 있다.

### 4.2 Judge 모델 출력 스타일에 민감

LongMemEval 경로는 strict yes/no 파싱이므로,
judge 모델이 설명문을 붙이면 오답 처리될 수 있다.

권장:
- judge 전용 모델을 분리 (`judge_llm_model`)
- 짧은 지시 추종이 좋은 모델/세팅 사용
- 샘플 몇 개를 먼저 돌려 raw judge reply 형태 점검

### 4.3 category/question_id 품질이 곧 채점 품질

- `category` 오기입 → 잘못된 judge prompt 적용
- `question_id`에 `_abs` 누락/오탐 → abstention 채점 오류

즉, LongMemEval 재현성은 “모델 성능”뿐 아니라
입력 메타데이터 품질에 크게 의존한다.

### 4.4 비교 실험 시 judge 경로를 고정해야 함

A/B 실험에서 다음 중 하나라도 바뀌면 점수 비교가 흐려진다.

- judge 모델 ID
- provider 경로 (responses/chat/bedrock)
- LongMemEval 라우팅 여부(category)
- yes/no 출력 형식 준수율

실험 노트에 위 4개를 항상 같이 기록하는 것을 권장한다.

---

## 5) 운영 체크리스트 (실무용)

실행 전에 아래를 점검하면 대부분의 해석 오류를 줄일 수 있다.

1. `configuration.yml`에 judge 모델 ID가 실제 등록되어 있는가
2. `judge_llm_model`을 쓸지 fallback(`llm_model`)을 쓸지 명시했는가
3. `generate.jsonl`의 `category`가 LongMemEval task 이름과 정확히 일치하는가
4. abstention 문항의 `question_id`에 `_abs`가 일관되게 들어가는가
5. judge raw 출력이 `yes/no` 단답 위주인지 샘플링 확인했는가
6. 레거시 `evaluate.py`와 wrapper `scripts/stages/judge.py` 중 어떤 경로로
   채점했는지 결과 문서에 기록했는가

---

## 6) 코드 포인터

- LongMemEval task prompt 및 파싱:
  `evaluation/retrieval_agent/llm_judge.py`
- 레거시 채점 진입점:
  `evaluation/retrieval_agent/evaluate.py`
- eval wrapper judge stage 진입점:
  `scripts/stages/judge.py`

