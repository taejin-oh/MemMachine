# Edwin Prompt 사용 가이드 (README_edwin)

**목적**: Phase 1에서 선정된 6개 후보 문제의 **재현 평가**(Reproduction Evaluation) 시 각 후보별로 적용할 answer-side prompt를 표준화하여 관리한다.

**원본 출처**: `/mnt/project/Edwin_prompt` (L4-157) — MemMachine 평가 파이프라인의 `qa_eval()` 함수가 `mmai.lme_answer_prompt` 값으로 분기 선택하는 5종 prompt 중 3종(EDWIN1, EDWIN3, COT)을 후보별로 매핑.

---

## 1. 파일 목록 및 매핑

| 후보 (#) | 문제 | 적용 Prompt 템플릿 | 파일명 | 근거 |
|---|---|---|---|---|
| #4/#12 | Adaptive k (k 비단조·scaling 비효율) | EDWIN3 | `case4_12_adaptive_k.txt` | `06_Reproduction_Evaluation_Design.md` §5.1 명시 |
| #3 | User/Assistant retrieval bias | EDWIN1 | `case3_user_bias.txt` | `06_Reproduction_Evaluation_Design.md` §5.5 명시 |
| #5 | Temporal reasoning 약함 | EDWIN3 [추정] | `case5_temporal.txt` | 설계 문서 미지정 — KNOWLEDGE UPDATE·시간 처리 지시 내장된 EDWIN3 권장 |
| #2 | Multi-hop retrieval failure | COT [추정] | `case2_multihop.txt` | 설계 문서 미지정 — HotpotQA는 episodic 전제 아님, 7단계 교차 추론 구조가 적합 |
| #6 | Multi-session reasoning | EDWIN3 | `case6_multisession.txt` | #4/#12 산출물 재분석 기반 — 동일 세팅 계승 |

---

## 2. 템플릿 3종 특성 요약

| 템플릿 | 성격 | 원본 라인 | 핵심 특징 |
|---|---|---|---|
| EDWIN1 | 기본 episodic QA | L90-111 | 8 instruction, 시간순 정렬, 최신 우선, 간결 답변 |
| EDWIN3 | observations 스타일 | L139-157 | KNOWLEDGE UPDATE(최신 우선), PLANNED ACTIONS(과거 계획=완료 가정), MOST RECENT USER INPUT(최근 메시지 최우선) |
| COT | 7단계 Chain-of-Thought | L15-87 | 메모리 추출→정보 식별→교차 연결→시간 계산→모순 확인→체크→답변, multi-hop·multi-entity 용 |

---

## 3. 실행 시 적용 방법

### 3.1 `lme_answer_prompt` 값 지정
`Edwin_prompt` L190-201에 따라 `mmai.lme_answer_prompt` 값(대문자)으로 분기됨:

| 파일 | 대응 값 |
|---|---|
| `case4_12_adaptive_k.txt` | `'EDWIN3'` |
| `case3_user_bias.txt` | `'EDWIN1'` |
| `case5_temporal.txt` | `'EDWIN3'` |
| `case2_multihop.txt` | `'COT'` |
| `case6_multisession.txt` | `'EDWIN3'` |

### 3.2 Placeholder 유지
각 파일 내 `{joined_history}`, `{question_timestamp}`, `{question}` 3개 placeholder는 **그대로 유지**. `qa_eval()` 함수가 `.format()`으로 치환.

### 3.3 재현 실행 순서
1. DB snapshot 1회 ingest (후보 전체가 동일 snapshot 재사용)
2. 각 후보 실행 직전 `mmai.lme_answer_prompt` 값 설정
3. 독립변수(k, chunk, user_q 등)만 sweep — prompt는 후보당 고정
4. 동일 후보 내에서는 prompt 절대 교체하지 않음 (variance 분리 목적)

---

## 4. 주의사항

- **#5, #2는 [추정]**: 논문이 실제 사용한 prompt 미명시. 본 문서의 권장값은 템플릿 특성에 근거한 것이며, MemVerge 공식 답변 수신 후 변경 가능.
- **#4/#12, #6 동일 prompt**: EDWIN3로 동일하지만 후보별 파일을 각각 유지 — 실행 추적성·버전 관리 일관성 확보 목적.
- **`06_Reproduction_Evaluation_Design.md` §8.1 "MemVerge 필수 1" 항목은 해결됨**: 본 디렉토리 파일로 대체 가능.

---

## 5. MemVerge 확인 대기 항목

1. `mmai.lme_answer_prompt` 값이 YAML·환경변수 등 어느 경로로 주입되는지 (`Edwin_prompt` L184 "if mmai: answer_prompt = mmai.lme_answer_prompt"에서 `mmai` 객체 설정 경로 미확인)
2. 논문 §5·§8.2 에서 #2(Multi-hop), #5(Temporal) 재현 시 실제 사용한 prompt 이름

상세는 `08_MemVerge_Info_Request.md` 참조.

---

## 6. 변경 이력

- **v1 (2026-04-24)**: 초기 작성. `Edwin_prompt` 파일 전문 확인 후 5개 case 파일 + README 구성.

---

## 출처

- 원본 prompt 정의: `/mnt/project/Edwin_prompt` L4-157
- 후보별 prompt 지정: `/mnt/project/06_Reproduction_Evaluation_Design.md` v5 §5.1(#4/#12)·§5.5(#3)
- 후보 선정 근거: `/mnt/project/02_Phase1_ProblemDefinition.md` v2 §4.5
