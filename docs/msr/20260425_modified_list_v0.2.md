# 20260425 Modified List v0.2

- 작성일: 2026-04-25
- 기준 문서: `docs/msr/09_Reproduction_Code_Changes.md`
- 점검 범위: `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`, `packages/server/*`
- 목적: 09 문서 수정 항목의 **최신 구현 상태(v0.2)**를 반영

---

## 0) v0.1 대비 변경 요약

- ✅ `message_sentence_chunking` YAML 값이 retrieval_agent 평가 경로에서 실제로 반영되도록 wiring 완료
- ✅ `run_benchmark_matrix.sh`에 LongMemEval `chunk {off,on}` 축 추가
- ✅ `README_MSR.md`에 chunk 토글 동작 및 사용 주의사항 반영

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
| #4/#12 chunk on/off YAML 제어 | ✅ | `init_memmachine_params()`가 YAML `message_sentence_chunking` 값을 사용하도록 반영 |
| #4/#12 chunk on/off 매트릭스 실행 | ✅ | LongMemEval `chunk x prefix x k` 조합 실행 지원 |
| 공통: DB snapshot 동결/복원 스크립트 | ❌ | 구현 확인 안 됨 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ | 구현 확인 안 됨 |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | 구현 확인 안 됨 |
| #6 MS 재분해 전용 집계 스크립트 | ❌ | 구현 확인 안 됨 |
| #4/#12, #3 Edwin prompt 주입 (`mmai.lme_answer_prompt`) | ❌ | 주입 경로/주입 코드 미확인 |

---

## 2) 이번에 완료된 항목 상세

### A. chunk YAML wiring 완료

- `evaluation/utils/agent_utils.py:init_memmachine_params()`에서
  `message_sentence_chunking`을 `bool | None`으로 받고,
  `None`일 경우 `episodic_memory.long_term_memory.message_sentence_chunking`
  값을 사용하도록 반영됨.
- `packages/server/src/.../episodic_config.py`의
  `LongTermMemoryConfPartial`에 `message_sentence_chunking` 필드 추가로
  partial config/YAML 역직렬화 시 값 유실 방지.
- 관련 테스트(`test_episodic_config.py`)에 merge/round-trip/omit 케이스 추가.

### B. run_benchmark_matrix chunk 축 추가

- LongMemEval 매트릭스가
  `chunk {off,on} x prefix {off,on} x k {10,20,30,50,100}`로 확장됨.
- 스크립트 내부에서
  `episodic_memory.long_term_memory.message_sentence_chunking`를 조합별로 갱신.
- postfix에 chunk 상태 포함 (`lmes_chunkoff_*`, `lmes_chunkon_*`).

### C. README_MSR 업데이트

- 변경 사항에 chunk 토글 반영 내용 추가.
- run_benchmark_matrix 사용법/동작 방식에 chunk 설정 키 반영.
- `--skip-ingest` 사용 시 chunk 실험에 대한 주의사항 명시.

---

## 3) 전혀 구현되지 않은 항목 (상세)

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
