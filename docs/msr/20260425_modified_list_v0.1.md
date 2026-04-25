# 20260425 Modified List v0.1

- 작성일: 2026-04-25
- 기준 문서: `docs/msr/09_Reproduction_Code_Changes.md`
- 점검 범위: `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`
- 목적: 09 문서에 정리된 수정 항목의 **현재 구현 상태**를 간결하게 기록

---

## 1) 구현 상태 요약

상태 표기:
- ✅ 구현 완료
- ❌ 미구현
- 제외: 이번 기준에서 미적용 정책

| 항목 (09 기준) | 상태 | 현재 구현 상태 |
|---|---:|---|
| #4/#12 LongMemEval `User:` prefix 삽입 | ✅ | `prepend_user_prefix` 토글로 on/off 운용 가능 |
| #4/#12 k sweep (10,20,30,50,100) | ✅ | `run_benchmark_matrix.sh`에 반영 |
| #3 C5/C6 운용 | ✅ | prefix on/off 조건으로 실행 가능 |
| #5 LoCoMo cat5 skip 포팅 | ✅ | `locomo_search.py`에 cat5 제외 로직 존재 |
| #5 LoCoMo 모드 sweep (Memory/Agent) | ✅ | 매트릭스 스크립트에 반영 |
| #2 HotpotQA 모드 sweep (Memory/Agent) | ✅ | 매트릭스 스크립트에 반영 |
| #2 HotpotQA 고정 랜덤 500 샘플 파일 생성/로드 | 제외 | `length=500` 정책 사용 |
| 공통: DB snapshot 동결/복원 스크립트 | ❌ | 구현 확인 안 됨 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ | 구현 확인 안 됨 |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | 구현 확인 안 됨 |
| #6 MS 재분해 전용 집계 스크립트 | ❌ | 구현 확인 안 됨 |
| #4/#12, #3 Edwin prompt 주입 (`mmai.lme_answer_prompt`) | ❌ | 주입 경로/주입 코드 미확인 |
| #4/#12, #3 chunk on/off를 YAML로 제어 | ❌ | 테스트 결과: config 값(True)과 실제 적용값(False) 불일치 |

---

## 2) 전혀 구현되지 않은 항목 (상세)

### A. DB snapshot 동결/복원 자동화

09 요구:
- PostgreSQL/Neo4j/SQLite 대상 snapshot 생성/복원
- snapshot ID 기록

현재:
- retrieval_agent 실행 스크립트 계열에서 snapshot 생성/복원 파이프라인 미확인

영향:
- 반복 실험 간 DB 상태 동일성 보장 자동화 부재

---

### B. 반복 실행 wrapper (파일럿 5회, N 자동결정)

09 요구:
- 파일럿 5회 수행 후 분산 추정
- 벤치별 반복 수 N 자동 결정
- mean±std 및 결합σ 자동 집계

현재:
- 조합 실행 스크립트는 있으나 반복 수 자동결정/파일럿 단계 로직 없음

영향:
- variance 관리 전략 도구화 미흡

---

### C. 자동 판정 스크립트 (성공/부분/실패)

09 요구:
- 두 조건 raw log 입력
- mean 차이 vs 결합σ×2 기준 자동 판정

현재:
- 해당 전용 판정 스크립트 미확인

영향:
- 판정 일관성/자동화 부족

---

### D. #6 Multi-session 재분해 전용 스크립트

09 요구:
- #4/#12 산출물을 재활용해 MS vs SSU/SSA 비교
- 결합σ×2 기준 자동 계산

현재:
- 전용 집계 스크립트 미확인

영향:
- #6 후처리 자동화 부재

---

### E. EDWIN prompt 주입 경로 구현

09 요구:
- #4/#12: `mmai.lme_answer_prompt = "EDWIN3"`
- #3: `mmai.lme_answer_prompt = "EDWIN1"`

현재:
- retrieval_agent 경로에서 위 속성 주입 코드/설정 경로 미확인

영향:
- #3/#4/#12 문서 기준 실험조건 완전 재현 불가

---

### F. chunk YAML 제어

09 요구:
- YAML `long_term_memory.message_sentence_chunking`로 chunk on/off 제어

검증:
- `init_memmachine_params()` 호출 경로를 더미 리소스 매니저로 실행해 확인
- 결과: `config_value=True`, `applied_value=False`

영향:
- 현재 retrieval_agent 경로에서 YAML chunk 설정이 실제 적용되지 않음
