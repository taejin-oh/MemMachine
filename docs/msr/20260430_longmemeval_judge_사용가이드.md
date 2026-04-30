# LongMemEval Judge 슈퍼리뷰 가이드 (원본 대비 변경점 + 운영 주의사항)

## TL;DR (먼저 이것만)

- MemMachine의 LongMemEval judge는 **원본 LongMemEval의 task별 프롬프트/abstention 분기**를
  복원했지만, **yes/no 파싱은 더 엄격**하다.
- 그래서 같은 모델 응답이어도 원본 스크립트와 점수가 달라질 수 있다.
- 재현 실험에서는 반드시 아래 4개를 고정/기록해야 한다.
  1) judge 모델 ID, 2) provider 경로, 3) category 값, 4) `question_id`의 `_abs` 유무.

---

## 1) 이 문서의 범위

이 문서는 “LongMemEval judge 관련 코드만” 대상으로 한다.

- 공통 judge 구현: `evaluation/retrieval_agent/llm_judge.py`
- 레거시 진입점: `evaluation/retrieval_agent/evaluate.py`
- 파이프라인 진입점: `scripts/stages/judge.py`

질문 의도는 다음 3개다.

1. 원본 LongMemEval 기반으로 무엇이 수정되었는가?
2. 지금 코드가 실제로 어떻게 동작하는가?
3. 사용할 때 어떤 점을 조심해야 하는가?

---

## 2) 원본 LongMemEval 대비 변경사항 (핵심)

## 2.1 Task-specific judge prompt 복원 (LongMemEval 전용)

`llm_judge.py:get_anscheck_prompt()`가 LongMemEval task별 템플릿으로 분기한다.

- General: `single-session-user`, `single-session-assistant`, `multi-session`
- Temporal: `temporal-reasoning` (off-by-one 허용 지침 포함)
- Knowledge update: `knowledge-update` (과거+최신 정보 공존 허용)
- Preference: `single-session-preference` (rubric 기반)
- Abstention: unanswerable 판정 템플릿

즉, LongMemEval 행(row)에 대해서는 generic `ACCURACY_PROMPT`가 아니라
원본 계열의 task-aware 프롬프트를 사용한다.

## 2.2 Abstention 판정 복원 (`_abs` 기반)

`evaluate_llm_judge_longmemeval()`는 `question_id`에 `"_abs"`가 포함되면
abstention 프롬프트로 전환한다.

의미:
- unanswerable 문항을 “모델이 적절히 답변 거절/정보불충분 판단했는지”를
  별도 지침으로 평가한다.

## 2.3 yes/no 판정 규칙을 원본보다 엄격화

현재 `_parse_yes_no()`는 reply 전체 문자열이 사실상 `yes` 또는 `no`
(공백/일부 문장부호 허용)일 때만 정답(1/0)으로 해석한다.

- 허용: `yes`, `no`, `yes.`
- 불허: `yes and no`, `not yes`, `yesterday`, `I think yes`

이건 원본의 느슨한 substring 계열 해석보다 보수적이다.
따라서 **점수 드리프트 가능성**이 생긴다.

---

## 3) 런타임 동작 (실제 호출 흐름)

## 3.1 Judge LLM 선택 규칙

`create_judge_fn(config_path, json_mode=...)`의 모델 선택 우선순위:

1. `retrieval_agent.judge_llm_model`
2. unset/empty면 `retrieval_agent.llm_model` fallback

지원 provider:
- `openai-responses`
- `openai-chat-completions`
- `amazon-bedrock`

모델 ID가 설정에 없으면 `ValueError`로 즉시 실패한다.

## 3.2 LongMemEval 라우팅 규칙 (category 기반)

judge 단계는 row의 `category` 문자열을 보고 LongMemEval 전용 judge로
보낼지 결정한다. 허용 task key:

- `single-session-user`
- `single-session-assistant`
- `multi-session`
- `temporal-reasoning`
- `knowledge-update`
- `single-session-preference`

여기서 값이 다르면 LongMemEval 데이터라도 generic judge 경로로 빠진다.

## 3.3 JSON judge vs Plain-text judge

- Generic 경로: JSON 응답(`{"label": "CORRECT|WRONG"}`) 기대
- LongMemEval 경로: plain text(`yes/no`) 기대

`scripts/stages/judge.py`는 LongMemEval category를 만나면 lazy하게
`create_judge_fn(..., json_mode=False)`를 생성해 사용한다.

---

## 4) 슈퍼리뷰 관점의 리스크 맵

## 4.1 재현성 리스크 (가장 큼)

같은 모델/같은 데이터라도 아래가 바뀌면 점수 비교가 흔들린다.

- judge 모델 ID 변경
- provider 경로 변경(responses/chat/bedrock)
- `category` 오염으로 라우팅 변경
- `_abs` 태깅 누락/오탐
- judge reply 스타일 변화(단답 vs 설명문)

## 4.2 해석 리스크

LongMemEval 성능 저하가 retrieval 문제인지, judge strict parsing 문제인지
분리되지 않은 채 섞여 보일 수 있다.

권장:
- 실패 샘플 일부를 수동 감사해 “실제 오답 vs parser 오탐” 분리
- 같은 결과를 원본 judge 스크립트와 소량 교차검증

## 4.3 운영 리스크

`judge_llm_model`이 정의되지 않았는데도 fallback으로 돌아가면
실험자는 “분리 judge를 썼다”고 착각할 수 있다.

권장:
- 런 메타에 `judge_model_resolved_id`를 별도 기록
- 결과 폴더마다 사용 config snapshot 보관

---

## 5) 실전 체크리스트 (실험 전/중/후)

## 5.1 실험 전

- [ ] `configuration.yml`의 `resources.language_models`에 judge ID가 존재하는가?
- [ ] `retrieval_agent.judge_llm_model`를 의도적으로 쓸지 fallback을 쓸지 명시했는가?
- [ ] 입력 row의 `category`가 LongMemEval task key와 정확히 일치하는가?
- [ ] abstention 문항의 `question_id`에 `_abs`가 일관되게 들어있는가?

## 5.2 실험 중

- [ ] judge raw reply 샘플 20개 이상에서 yes/no 단답 준수율을 확인했는가?
- [ ] 설명형 reply가 빈번하면 모델/온도/프롬프트 설정을 조정했는가?

## 5.3 실험 후

- [ ] score 하위 샘플에서 parser 영향(형식 실패)을 분리 분석했는가?
- [ ] 실험 로그에 judge 모델/provider/category 규칙/_abs 규칙을 함께 남겼는가?

---

## 6) 추천 운영 패턴

1. **Small pilot**: 30~50문항으로 judge 응답 형식 안정화 확인
2. **Fixed judge**: 본 실험 동안 judge 모델 ID/provider를 절대 고정
3. **Route audit**: `category` 분포 및 out-of-set 키 여부 사전 검사
4. **Abstention audit**: `_abs` 문항 샘플링 점검
5. **Cross-check**: 최종 리포트 전 원본 judge와 소량 교차 검증

---

## 7) 코드 포인터 (빠른 추적용)

- `evaluation/retrieval_agent/llm_judge.py`
  - `get_anscheck_prompt()`
  - `create_judge_fn()`
  - `_parse_yes_no()`
  - `evaluate_llm_judge_longmemeval()`
- `evaluation/retrieval_agent/evaluate.py`
  - `_LONGMEMEVAL_TASKS` 분기 및 legacy 평가 루프
- `scripts/stages/judge.py`
  - `_LONGMEMEVAL_TASKS` 분기
  - `_judge_config_path()` judge 모델 swap
  - stage run 루프의 LongMemEval 라우팅

---

## 8) 결론

현재 MemMachine의 LongMemEval judge는 “원본 의도 복원 + 운영 안전성 강화”
사이의 절충안이다.

- 장점: task-aware prompt/abstention 복원으로 의미적 정합성 향상
- 주의: strict yes/no 파싱으로 형식 민감도 증가

따라서 이 judge를 사용할 때의 핵심은 **모델 성능 측정**과 **채점 형식 안정성**을
분리해 관리하는 것이다.
