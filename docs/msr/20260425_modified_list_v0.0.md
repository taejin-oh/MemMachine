# 20260425 Modified List v0.0

- 작성일: 2026-04-25
- 기준 문서: `docs/msr/09_Reproduction_Code_Changes.md`
- 점검 범위: `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`
- 목적: 09 문서에서 "수정 예정"으로 정리된 항목의 **현재 구현 상태**를 한눈에 파악

---

## 1) 구현 상태 요약 (한눈에 보기)

상태 표기:
- ✅ 구현 완료
- ◑ 부분 구현 / 방식 차이
- ❌ 미구현

| 항목 (09 기준) | 현재 상태 | 비고 |
|---|---:|---|
| #4/#12 LongMemEval `User:` prefix 삽입 | ◑ | 직접 소스 2버전 패치 대신, config 기반 `prepend_user_prefix` 토글 방식으로 구현됨 |
| #4/#12 k sweep (10,20,30,50,100) | ✅ | `run_benchmark_matrix.sh`에 반영 |
| #3 C5/C6 2버전 운용 | ◑ | prefix on/off 자체는 가능하나, 문서의 "patch 적용/미적용 2버전" 방식과 다름 |
| #5 LoCoMo cat5 skip 포팅 | ✅ | `locomo_search.py`에 cat5 제외 로직 존재 |
| #5 LoCoMo 모드 sweep (Memory/Agent) | ✅ | 매트릭스 스크립트에 반영 |
| #2 HotpotQA 모드 sweep (Memory/Agent) | ✅ | 매트릭스 스크립트에 반영 |
| #2 HotpotQA 고정 랜덤 500 샘플 파일 생성/로드 | ❌ | 신규 스크립트/샘플 파일/로딩 교체 없음 |
| 공통: DB snapshot 동결/복원 스크립트 | ❌ | 09 요구사항 수준 구현 없음 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ | 반복 수 자동결정/파일럿 분산 추정 로직 없음 |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | 결합σ×2 기준 자동 판정 스크립트 없음 |
| #6 MS 재분해 전용 집계 스크립트 | ❌ | k sweep 결과 재분해용 전용 스크립트 없음 |
| #4/#12, #3 Edwin prompt 주입 (`mmai.lme_answer_prompt`) | ❌ | 주입 경로/주입 코드 미확인 (09에서도 블로커로 명시) |
| #4/#12, #3 chunk on/off를 YAML로 제어 | ◑ | 09 문서상 YAML 기준이지만, retrieval_agent 경로에서 실제 반영 여부는 불명확 |

---

## 2) 세부 점검 메모

### 2.1 이미 구현된 핵심 항목

1. LoCoMo cat5 제외
   - `qa["category"] == 5 or "5"` 문항 skip 로직 확인.

2. LongMemEval prefix on/off
   - `evaluation.longmemeval.prepend_user_prefix` 플래그를 읽어 `question = f"User: {question}"` 적용.

3. 실행 매트릭스
   - LongMemEval: prefix {off,on} × k {10,20,30,50,100}
   - LoCoMo: mode {memmachine,retrieval_agent}
   - HotpotQA: mode {memmachine,retrieval_agent}

---

## 3) 전혀 구현되지 않은 항목 (상세)

### A. HotpotQA 고정 랜덤 500 샘플 체계

09 요구:
- `generate_hotpotqa_sample.py` 신규 작성
- `hotpotqa_sample_500.json` 산출
- `hotpotQA_test.py`에서 `[:500]`/앞 N개 방식 대신 고정 인덱스 로드

현재:
- `load_hotpotqa_dataset()`는 `select(range(length))` 사용
- 고정 인덱스 파일 로드 로직 없음
- 샘플 생성 스크립트/산출 json 파일 없음

영향:
- 반복 실행 시 표본 고정 전략(09 권장) 미충족

---

### B. DB snapshot 동결/복원 자동화

09 요구:
- PostgreSQL/Neo4j/SQLite 대상 snapshot 생성/복원
- snapshot ID 기록

현재:
- retrieval_agent 실행 스크립트 계열에서 snapshot 생성/복원 파이프라인 미확인

영향:
- 반복 실험 간 DB 상태 동일성 보장 자동화 부재

---

### C. 반복 실행 wrapper (파일럿 5회, N 자동결정)

09 요구:
- 파일럿 5회 수행 후 분산 추정
- 벤치별 반복 수 N 자동 결정
- mean±std 및 결합σ 자동 집계

현재:
- 조합 실행 스크립트는 있으나 반복 수 자동결정/파일럿 단계 로직 없음

영향:
- 09의 variance 관리 전략을 도구 차원에서 재현하기 어려움

---

### D. 자동 판정 스크립트 (성공/부분/실패)

09 요구:
- 두 조건 raw log 입력
- mean 차이 vs 결합σ×2 기준으로 자동 판정

현재:
- 해당 전용 판정 스크립트 미확인

영향:
- 판정 일관성/자동화 부족

---

### E. #6 Multi-session 재분해 전용 스크립트

09 요구:
- #4/#12 산출물을 재활용해 MS vs SSU/SSA 비교
- 결합σ×2 기준 자동 계산

현재:
- 전용 집계 스크립트 미확인

영향:
- #6은 별도 실행 불필요 설계인데, 후처리 자동화가 없음

---

### F. EDWIN prompt 주입 경로 구현

09 요구:
- #4/#12: `mmai.lme_answer_prompt = "EDWIN3"`
- #3: `mmai.lme_answer_prompt = "EDWIN1"`

현재:
- retrieval_agent 경로에서 위 속성 주입 코드/설정 경로 미확인
- 09 문서에서도 Q1 블로커로 명시된 상태

영향:
- #3/#4/#12의 문서 기준 실험조건 완전 재현 불가

---

## 4) 부분 구현/불일치 항목 정리

1. user_q 적용 방식 불일치
   - 09: 소스 patch on/off 2버전 관리
   - 현재: config 토글 방식

2. chunk YAML 제어 불확실성
   - 09: YAML `long_term_memory.message_sentence_chunking` 명시
   - 현재: retrieval_agent 초기화에서 `message_sentence_chunking` 기본값 `False` 사용. 호출부에서 override 전달이 없어 실제 YAML 제어 반영이 불명확

---

## 5) 다음 버전(v0.1) 업데이트 제안 (문서 관리 관점)

- 항목별로 "코드 위치(파일:라인)"를 표에 직접 추가
- 상태를 `완료/부분/미구현/검증필요` 4단계로 세분화
- 0424 기준 필수/선택 항목 분리 컬럼 추가
