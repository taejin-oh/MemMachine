# 재현 평가 요약 — 5개 후보 한눈에 보기 [v5]

[← Executive Report](./00_Executive_Report_Outline.md) · [← 재현 평가 상세 설계](./06_Reproduction_Evaluation_Design.md) · [MemVerge 문의](./08_MemVerge_Info_Request.md)

**작성일**: 2026-04-22
**용도**: Phase 2 진입 직전 담당자 배포·공유용 요약판. 상세 설계는 `06_` 참조.

> **v5 변경점**:
> - Provider 는 사내 vLLM (`openai-chat-completions`), Temperature 조정 불가
> - Variance 관리: 반복 실행 + DB snapshot 동결 (Seed·Temperature 둘 다 통제 불가)
> - 재현 판정: **결합 표준편차 2배 초과** 기준
> - Phase 0 파일럿: 3 벤치마크 × 30문항 × 5회
> - 3 flag 제어 방식 확정 (chunk=YAML, user_q=소스, json_str=휴면)
> - MemVerge 필수 3건 확장

---

## §1 공통 전제

- **평가 원칙**: 절대 점수가 아닌 **문제 패턴** 재현
- **모델 4종** (Answer LLM / Judge LLM / Embedding / Reranker): 사내 오픈 모델 **TBD**, 6개 평가 전체에 동일 고정
- **Provider**: 사내 vLLM (`openai-chat-completions` provider + base_url)
- **결정성 통제 수단 0개**: Seed 부재, Temperature 전달 불가
- **Variance 관리**: 반복 실행 + DB snapshot 동결
- **반복 수**: 파일럿 결과에 따라 2~10회
- **판정 기준**: 대조 조건 간 차이가 **결합 표준편차의 2배 초과** 시에만 "유의" 판정
- **`expand_context`**: MemMachine 코드 기본값 그대로
- **JSON-str**: **off 상태로 진행** (MemVerge 공식 활성화 방법 수신 후 재평가)

---

## §2 5개 후보 평가 한눈 비교표

| 항목 | #4/#12 (1순위) | #5 (2순위) | #2 (3순위) | #6 (4순위) | #3 (5순위) |
|---|---|---|---|---|---|
| **문제명** | Adaptive k | Temporal | Multi-hop | Multi-session | User/Asst bias |
| **벤치마크** | LongMemEvalS 500 | LoCoMo 1,540 | HotpotQA hard 500 | LongMemEvalS 500 | LongMemEvalS 500 |
| **독립변수** | k ∈ {10,20,30,50,100} | 모드 {Memory, Agent} | 모드 {Memory, Agent} × 선정 {S1, S2} | 없음 (관찰) | 소스 편집 유무 |
| **종속변수** | overall·카테고리·token·latency | 카테고리별 점수 | Acc·Recall·token·tool breakdown | MS vs 타 카테고리 | overall 점수 |
| **고정 조합** | C12 조합 (Edwin3, chunk=on, user_q=on, json_str=off) | LoCoMo 기본 | HotpotQA 기본 | (#1과 공유) | C5/C6 조합 (Edwin1, chunk=off, json_str=off) |
| **수정 레이어** | YAML(chunk) + 소스(user_q) | cat5 필터 포팅 | (없음) | 재분석 | YAML(chunk) + 소스(user_q) |
| **별도 run?** | 예 (5개 k) | 예 (2모드) | 예 (4조합) | 아니오 | 예 (2소스 버전) |
| **필수 외부 자원** | Edwin3 + C12 YAML | — | — | — | Edwin1 + C5/C6 YAML |
| **재현 성공 기준** | k 에서 꺾임 또는 diminishing return, 결합 σ 2배 초과 | Temporal < Single-hop, 결합 σ 2배 초과 | Agent > Memory, S1/S2 양쪽 결합 σ 2배 초과 | 모든 k 에서 MS < SSU/SSA, 결합 σ 2배 초과 | prefix on 에서 유의 상승, 결합 σ 2배 초과 |

> **약어**: **C12**(논문 Table 12 의 12번 — 코드 라벨 아님) · **Edwin1/3**(MemMachine 내부 search prompt, **코드 부재**) · **결합 σ**(두 조건 표준편차 합성, 판정 임계선)
> **카테고리** (LongMemEvalS): SSU · SSP · SSA · TR · KU · MS

---

## §3 후보별 요약

### 1순위 — #4/#12 Adaptive k

**문제**: 검색 문서 수(k) 를 늘려도 정확도가 어느 지점부터 꺾이거나 비용만 증가

**재현 대상**: k 증가 시 정확도 비단조 + token 3.8× 대비 +0.8%p

**핵심 포인트**
- 5개 k 값 × 반복 수 별도 run
- YAML: `long_term_memory.message_sentence_chunking: true`
- 소스 패치: `longmemeval_test.py:214` 직전에 `question = f"User: {question}"` 삽입
- JSON-str 은 off 진행 (논문 on 과 차이 명시)
- **필요 외부 자원**: Edwin3 prompt, C12 YAML 예시

**담당자**: A / **라운드**: 1

---

### 2순위 — #5 Temporal Reasoning

**문제**: 시간 기반 질문에 메모리 시스템이 약함

**재현 대상**: Temporal < Single-hop 격차 (§8.2)

**핵심 포인트**
- LoCoMo 1,540 × 2 모드
- **착수 첫 작업**: cat5 skip 필터를 `evaluation/retrieval_agent/locomo_search.py` 에 포팅
- Judge 는 공통 `ACCURACY_PROMPT` (태스크 분기 없음)

**담당자**: B / **라운드**: 1

---

### 3순위 — #2 Multi-hop

**문제**: 2단계 이상 추론 질문에서 단일 검색 실패

**재현 대상**: Memory vs Agent 정확도·token 격차

**핵심 포인트**
- HotpotQA hard 500 × 2 모드 × 선정 방식 2개 (S1: 앞 500 순차 / S2: seed=42 무작위)
- Agent 구성 확인됨: ToolSelectAgent + ChainOfQuery + SplitQuery
- 이 단계는 문제 존재 확인만

**담당자**: C / **라운드**: 1

---

### 4순위 — #6 Multi-session Reasoning

**문제**: 여러 세션 통합 질문에서 성능 저하

**재현 대상**: MS 카테고리 < 다른 카테고리 (§8.4.7)

**핵심 포인트**
- **별도 run 불필요** — #4 의 k sweep 결과 재분석
- 분석·해석 작업

**담당자**: 2라운드 완료자 / **라운드**: 2

---

### 5순위 — #3 User/Assistant bias

**문제**: user/assistant 발화 편향 검색

**재현 대상**: `"user:"` prefix 적용 시 +1.4%p (C5 → C6)

**핵심 포인트**
- **논문 C5/C6 조합 — §5.1 의 C12 와 다름**: Edwin1 (Edwin3 아님), chunk **off**, k=20
- 소스 2버전 관리: C5 (원본), C6 (prefix 삽입 패치)
- JSON-str off 진행 → 논문 (on 상태) 과 비교 주의
- `exclude_abstention` = True 로 통일
- **필요 외부 자원**: Edwin1 prompt, C5/C6 YAML 예시

**담당자**: 2라운드 완료자 / **라운드**: 2

---

## §4 실행 순서 요약

```
[0라운드] 공통 파일럿 — 전원 공동
  ├─ 모델 슬롯 4종 확정 (Answer/Judge LLM, Embedding, Reranker)
  ├─ vLLM base_url 확정
  ├─ 담당 B: cat5 skip 필터 포팅 (retrieval_agent 경로)
  ├─ 3 벤치마크 × 30문항 × 5회 → variance 측정
  ├─ 벤치마크별 본 실험 반복 수 결정 (표 §4.4 기준)
  └─ DB snapshot 생성·저장

     ↓

[1라운드] 병렬 본 실험
  ├─ 담당 A: #4/#12 — LongMemEvalS k sweep 5개 × 반복 수
  ├─ 담당 B: #5 — LoCoMo Memory + Agent
  └─ 담당 C: #2 — HotpotQA (S1 + S2) × (Memory + Agent)

     ↓

[2라운드] 완료자부터
  ├─ #6 — 담당 A 산출물 재분석 (별도 run 없음)
  └─ #3 — LongMemEvalS C5/C6 재실행
```

---

## §5 담당자별 체크리스트

- [ ] 모델 슬롯 4종 확정 값 수신
- [ ] vLLM base_url 확인
- [ ] Edwin1 (담당 C) / Edwin3 (담당 A) prompt 수신 — MemVerge
- [ ] C5/C6/C12 YAML + 패치 수신 — MemVerge
- [ ] (담당 B) cat5 필터 포팅 완료
- [ ] 파일럿 결과로 본인 후보 반복 수 확정
- [ ] config YAML 작성
- [ ] 소스 패치 파일 (`.patch`) 관리
- [ ] DB snapshot ID 기록
- [ ] 재현 판정 기준 (결합 σ 2배) 숙지

**산출 의무**
1. config YAML + 소스 패치
2. raw 결과 log
3. 집계표 (논문 Table 대응 + 반복별 수치 + mean±std + 결합 σ 2배 기준선)
4. 재현 판정 리포트 (1~2페이지)

---

## §6 외부 자원 의존성

| 자원 | 어디서 | 누가 | 상태 |
|---|---|---|---|
| Edwin1 prompt | MemVerge 필수 1 | 담당 C (#3) | 요청 예정 |
| Edwin3 prompt | MemVerge 필수 1 | 담당 A (#4/#12) | 요청 예정 |
| C5, C6, C12 YAML + 패치 | MemVerge 필수 2 | 전원 | 요청 예정 |
| JSON-str 활성화 방법 | MemVerge 필수 3 | 전원 | 요청 예정 (없으면 off 진행) |
| `exclude_abstention` 적용값 | MemVerge 가벼운 확인 | 담당 C | True 로 진행, 사후 확인 |

→ 상세는 `08_MemVerge_Info_Request.md` 참조.

---

## §7 관련 문서

- `06_Reproduction_Evaluation_Design.md` — 본 요약의 원본 상세 설계
- `08_MemVerge_Info_Request.md` — MemVerge 문의 항목 및 메일 초안
- `02_Phase1_ProblemDefinition.md` — 6개 후보 선정 근거
- `memmachine_quant_metrics.md` — 논문 수치 재참조
- `00_Executive_Report_Outline.md` — 상위 과제 맥락

---

## 변경 이력

- **v5 (2026-04-22)**: Provider (vLLM) + Variance 관리 + 3 flag 제어 + 판정 보수화 + MemVerge 항목 3건 확장
- v4 (2026-04-22): `expand_context`·cat5 사내 결정 반영, MemVerge 5→2+1 축소
- v3 (2026-04-22): MemMachine 코드 조사 반영, Seed 포기
- v2 (2026-04-22): 용어 괄호 설명 추가
- v1 (2026-04-22): 초기 작성
