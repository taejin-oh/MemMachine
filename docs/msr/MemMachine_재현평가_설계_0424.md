# MemMachine 6개 후보 정량 수치 정리

**작성일**: 2026-04-22
**목적**: Phase 1에서 선정된 6개 후보 문제에 대한 논문 정량 수치를 **재참조 가능한 형태**로 보존
**출처**: MemMachine 논문 (arXiv:2604.04853v1), `memmachine_diagnostic_v2.md`
**원칙**: 논문에 명시된 수치만 기록. 추론·추정은 명시적으로 `[추정]` 태그.

---

## 0. 참고 구분 — 수치의 두 가지 유형

| 유형 | 의미 | 용도 |
|---|---|---|
| **현상(Symptom)** | 문제가 존재함을 보이는 수치 | Phase 1 문제 정의 근거 |
| **before/after** | 개선 전/후 대조 수치 | Phase 3 개선 효과 검증 근거 |
| **비교(Comparative)** | 타 시스템 또는 타 조건 대비 | Phase 1 심각도 판단 근거 |

→ **6개 후보 모두 현상 수치는 논문에 존재**. 본 과제 관점의 **개선책 before/after 대조(동일 시스템·다른 설정)는 #3·#4만** 논문 내 존재. #2 는 "Memory(before) vs Agent(after)" 수치가 있으나 Agent-only 해결책이라 본 과제 지향(Agent-free)과 다른 축.

---

## 1. 논문 전체 성과 (Reference)

6개 후보 수치를 해석하는 데 필요한 배경.

| 항목 | 수치 | 조건 | 출처 |
|---|---|---|---|
| LoCoMo overall | 0.9169 | gpt-4.1-mini, Agent 모드 | §1 Table 1, §8.1 Table 10 |
| LoCoMo overall | 0.9123 | gpt-4.1-mini, Memory 모드 | §8.1 Table 10 |
| LoCoMo overall | 0.8812 | gpt-4o-mini, Agent 모드 | §8.1 Table 10 |
| LoCoMo overall | 0.8747 | gpt-4o-mini, Memory 모드 | §8.1 Table 10 |
| LongMemEvalS best | 0.930 | C15, GPT-5-mini, k=100 | §8.4, Table 12 |
| LongMemEvalS Pareto | 0.922 | C12, GPT-5-mini, k=20 | §8.4, Table 12 |
| HotpotQA hard | 0.932 | Retrieval Agent, gpt-5-mini | §5.6 Table 3, Table 4 |

---

## 2. 6개 후보별 수치

### #2 — Multi-hop retrieval failure (late binding)

**평가 방법 (논문 §5.6·§7.1)**:
- 벤치마크: HotpotQA hard set 500 문항 (§5.6 Table 3·4), WikiMultiHop 500 (§5.6 Table 3), LoCoMo multi-hop 카테고리 282 문항 (§8.1 Table 10)
- 비교 모드: MemMachine (Memory, baseline) vs Retrieval Agent
- Answer LLM: gpt-5-mini (HotpotQA·WikiMultiHop), gpt-4.1-mini / gpt-4o-mini (LoCoMo)
- 지표: LLM-judge accuracy, gold supporting fact recall
- Agent 구성: ToolSelectAgent → ChainOfQuery / SplitQuery / MemMachine 직접 (3-way 라우팅, §5.3 Query Routing)
- Judge-LLM: gpt-4o-mini (§7.3 Table 9)

| 항목 | 수치 | 조건 | 유형 | 출처 |
|---|---|---|---|---|
| HotpotQA hard — MemMachine (Memory) 정확도 | 91.2% | 현상 (before, Agent-free 한계) | Table 3 (본문 동일 §5.6) |
| HotpotQA hard — MemMachine (Memory) recall | 90.98% | 현상 (before) | §5.6 본문 |
| HotpotQA hard — Retrieval Agent 정확도 | 93.2% | Agent 해결 후 (after) | §5.6 Table 3·4, 본문 |
| HotpotQA hard — Retrieval Agent recall | 92.31% | Agent 해결 후 (after) | §5.6 Table 4·본문 |
| Agent vs Memory 개선 폭 | +2.0%p Acc, +1.3%p Recall | 모드 전환 효과 | §5.6 본문 |
| ChainOfQuery 구성 | 2,874 input + 1,614 output token | HotpotQA hard 평균 | 비용 | §5.7 Table 5 |
| 전체 Agent 오버헤드 (ChainOfQuery 경로) | ~5,732 token/query | 다중 hop 경로 전체 | 비용 | §5.7 |
| LoCoMo Multi-hop | 0.8759 | gpt-4o-mini, Memory 모드 | 현상 | §8.1 Table 10, §8.2 Table 11 |
| LoCoMo Multi-hop | 0.8830 | gpt-4.1-mini, Agent 모드 | 현상 | §8.1 Table 10 |
| LoCoMo Multi-hop | 0.8972 | gpt-4.1-mini, Memory 모드 | 현상 | §8.1 Table 10 |

**참고 (v2 정정)**: 논문 §5.6에 **Memory vs Agent 모드 대조 수치 존재**. 그러나 본 과제 관점에서는 "모드 전환 = Agent-only 해결책 사용" 이므로 개선책 before/after 가 아닌 "문제 존재 + Agent-only 해결" 관계로 해석. **Agent-free 전환 시 자체 baseline 재측정 필수**.

**논문 내부 수치 불일치 주의 (v2 추가)**: Table 3의 Retrieval Agent recall = 95.5% 이나 Table 4 per-tool 집계·§5.6 본문 = 92.31% — 2개 값 존재. 본문·Table 4 값(92.31%)을 표준으로 사용.

**재현 평가 방법 (본 과제 §5.3 우선순위 3)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | HotpotQA hard 500 |
| 독립변수 | 모드 ∈ {Memory, Retrieval Agent} |
| 고정변수 | Answer LLM (사내 오픈 LLM — TBD), embedding, reranker, DB snapshot |
| 종속변수 | Accuracy · Recall · 쿼리당 token · Per-tool breakdown (ToolSelect / ChainOfQuery / SplitQuery) |
| Agent 구성 | 기존 코드 기본값 (ToolSelectAgent / ChainOfQuery / SplitQuery) |
| Answer prompt | 기본값 COT (Edwin 미설정 fallback) — Multi-hop 성격상 적합 |
| 반복 | §4 전략 (파일럿 표준편차 기반 결정) |
| 판정 기준 | 성공: Agent > Memory 가 결합 σ 2배 초과 + Agent token > Memory token / 부분: 한쪽만 재현 / 실패: Memory ≥ Agent |
| 500 선정 방식 | **재조사 필요** — 06 §8.3 [F7-HotpotQA] 의 "`hotpotQA_test.py:195-202` `[:500]`" 이 사용자 확인에서 검증 안 됨 |

---

### #3 — User/Assistant retrieval bias

**평가 방법 (논문 §8.4.2)**:
- 벤치마크: LongMemEvalS 500 문항
- 비교 방식: **C5(baseline) vs C6(user-q on)** 단일 변수 대조 (ablation pair)
- Answer LLM: GPT-5
- 고정 설정: chunk=off, JSON-str=on, Prompt=Edwin1, k=20
- 독립변수: 검색 쿼리에 `"user:"` prefix 삽입 여부
- 지표: overall llm_score
- Judge-LLM: gpt-4o-mini, question-specific judge prompts (§7.2)

| 항목 | 수치 | 조건 | 유형 | 출처 |
|---|---|---|---|---|
| "user:" prefix 적용 전 (C5) | 0.855 | GPT-5, k=20, LongMemEvalS overall | **before** | §8.4.2, Table 12 |
| "user:" prefix 적용 후 (C6) | 0.870 | GPT-5, k=20, LongMemEvalS overall | **after** | §8.4.2, Table 12 |
| 개선 폭 | +1.4%p | — | **delta** | §8.4, Table 13 |

**참고**: 6개 후보 중 **명시적 before/after가 존재하는 두 개 중 하나**. 단, heuristic(쿼리 prefix)이므로 구조적 해결은 별개.

**재현 평가 방법 (본 과제 §5.5 우선순위 5)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 독립변수 | 평가 스크립트 소스 편집 여부 (C5: prefix 없음 / C6: prefix 삽입) |
| 고정변수 (논문 C5/C6 조합) | chunk=**off** / json_str=**off** (방침) / Prompt=**Edwin1** / k=20 / Answer LLM 사내 오픈 LLM |
| 종속변수 | overall `llm_score` |
| 소스 수정 | C6 적용 시 `longmemeval_test.py:214` 직전 `question = f"User: {question}"` 삽입 — 패치 파일로 2버전 관리 |
| Answer prompt 주입 | `mmai.lme_answer_prompt = "EDWIN1"` — 주입 경로 MemVerge Q1 대기 |
| 반복 | §4 전략 (파일럿 표준편차 기반 결정) |
| 판정 기준 | 성공: prefix on 에서 overall 상승이 결합 σ 2배 초과 / 부분: 방향 맞으나 σ 1~2배 / 실패: 방향 반대 |
| 주의 | JSON-str=off 상태이므로 논문 (on) 과 차이 있음. 재현 수치가 논문 +1.4%p 와 다를 수 있음을 사전 명시. User_q 구현 경로(legacy vs retrieval_agent) 논문 명시 없음 |
| 운영 결정 | `exclude_abstention = True` 로 통일 |

---

### #4 — k 비단조성 (Non-monotonicity)

**평가 방법 (논문 §8.4.1·§8.4.6)**:
- 벤치마크: LongMemEvalS 500 문항
- 독립변수: retrieval depth **k ∈ {20, 30, 50, 100}**
- Answer LLM 2종으로 sweep:
  - **GPT-5** 계열: C6(k=20), C7(k=30), C8(k=50), C16(k=30), C17(k=50)
  - **GPT-5-mini** 계열: C12(k=20), C13(k=30), C14(k=50), C15(k=100)
- 고정 설정 (C12 이후): user_q=on, chunk=on, JSON-str=on, Prompt=Edwin3
- 지표: overall llm_score
- Judge-LLM: gpt-4o-mini (§7.3 Table 9)

| 항목 | 수치 | 조건 | 유형 | 출처 |
|---|---|---|---|---|
| k=20 (C6) | 0.870 | GPT-5 | **before** | §8.4.1, Table 12 |
| k=30 (C7) | 0.912 | GPT-5 | **after (증가)** | §8.4.1, Table 12 |
| k=50 (C8) | 0.890 | GPT-5 | **after (하락)** | §8.4.1, Table 12 |
| 비단조성 증거 | k=30 → k=50 시 −2.2%p 하락 | GPT-5 | 현상 | §8.4.1 |
| 대조: GPT-5-mini k=20 (C12) | 0.922 | GPT-5-mini | 비교 (단조) | §8.4.1·§8.4.6, Table 12 |
| 대조: GPT-5-mini k=30 (C13) | 0.916 | GPT-5-mini | 비교 (단조) | §8.4.6 본문·Table 12 |
| 대조: GPT-5-mini k=50 (C14) | 0.928 | GPT-5-mini | 비교 (단조) | §8.4.1, Table 12 |
| 대조: GPT-5-mini k=100 (C15) | 0.930 | GPT-5-mini | 비교 (단조) | §8.4.1, Table 12 |

**참고**: 6개 후보 중 **명시적 before/after가 존재하는 두 개 중 하나**. k 민감도가 **모델 의존적**임이 논문에서 확인됨(GPT-5는 비단조, GPT-5-mini는 단조).

**논문이 지목한 원인 메커니즘 (§8.4.1 본문, v2 추가)**:
> "additional episodes introduce irrelevant context that degrades reading comprehension, consistent with the 'lost in the middle' phenomenon [13]"

→ k=50에서 성능 하락의 논문 원인 설명: **distractor context 로 인한 "lost in the middle"**. Phase 2 원인 가설 검증 시 이 메커니즘을 원인 지표 후보로 활용 가능.

**재현 평가 방법 (본 과제 §5.1 우선순위 1)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 독립변수 | k ∈ {10, 20, 30, 50, 100} |
| 고정변수 (논문 C12 조합) | chunk=**on** / user_q=**on** / json_str=**off** (방침) / Prompt=**Edwin3** / `expand_context`=코드 기본값 / Answer LLM 사내 오픈 LLM |
| 종속변수 | `llm_score` overall · 카테고리별 6종 (SSU/SSP/SSA/TR/KU/MS) · 쿼리당 input token · 쿼리당 latency |
| YAML 설정 | `long_term_memory.message_sentence_chunking: true` |
| 소스 수정 | `longmemeval_test.py:214` 직전 `question = f"User: {question}"` 삽입 |
| Answer prompt 주입 | `mmai.lme_answer_prompt = "EDWIN3"` — 주입 경로 MemVerge Q1 대기 |
| 반복 | §4 전략 (파일럿 표준편차 기반 결정) |
| 판정 기준 | 성공: k 를 늘리는 동안 정확도 상승 둔화·꺾임이 결합 σ 2배 초과 관찰 / 부분: σ 1~2배 / 실패: k 무관 또는 비례 증가 |
| 전제 | Edwin3 prompt 전문은 로컬 파일 확보 완료, 주입 경로 확정 필요 |

---

### #5 — Temporal reasoning 약함

**평가 방법 (논문 §8.1·§8.2·§7.1)**:
- 벤치마크: **LoCoMo Temporal 카테고리 321 문항** (전체 1,540 중 adversarial 446 제외 후)
- 두 종류 비교:
  - **Table 10**: MemMachine 자체 설정별 (gpt-4o-mini / gpt-4.1-mini × Memory / Agent 모드)
  - **Table 11**: **gpt-4o-mini + Memory 모드** 고정 → 타 시스템(Memobase, Zep, Mem0, LangMem, OpenAI)과 cross-system 비교
- 지표: 카테고리별 llm_score (Temporal)
- Judge-LLM: gpt-4o-mini (Mem0 평가 프레임워크 기반, §7.1)

| 항목 | 수치 | 조건 | 유형 | 출처 |
|---|---|---|---|---|
| MemMachine Temporal | 0.7352 | gpt-4o-mini, Memory 모드 | 현상 | §8.2 Table 11 |
| Memobase Temporal | 0.8505 | 비교 대상 | 비교 | §8.2 Table 11 |
| 격차 | −11.53%p | MemMachine vs Memobase | 비교 | §8.2 Table 11 (계산) |
| MemMachine Temporal (상위 조건) | 0.9159 | gpt-4.1-mini, Agent 모드 | 현상 | §8.1 Table 10 |
| MemMachine Temporal (상위 조건) | 0.8910 | gpt-4.1-mini, Memory 모드 | 현상 | §8.1 Table 10 |

**참고**: 경쟁 시스템 대비 가장 큰 격차 영역. 모델 업그레이드(gpt-4o-mini→gpt-4.1-mini)로 크게 개선되므로 **모델 의존성 큼**(§8.2 논문 명시).

**재현 평가 방법 (본 과제 §5.2 우선순위 2)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LoCoMo 1,540 (cat5 adversarial 446 제외 → 실질 1,094 문항) |
| 독립변수 | 모드 ∈ {Memory, Agent} |
| 고정변수 | Answer LLM (사내 오픈 LLM — TBD), embedding, reranker, DB snapshot |
| 종속변수 | 카테고리별 `llm_score` (주목: Temporal vs Single-hop) |
| 코드 수정 | `restapiv2_locomo_search.py:257-264` 의 cat5 skip 로직을 `evaluation/retrieval_agent/locomo_search.py` 에 포팅 (담당 B 선행 작업) |
| Answer prompt | 기본값 COT (Edwin 미설정 fallback) — MemVerge 답변 후 EDWIN3 재실행 여지 |
| 반복 | §4 전략 (파일럿 표준편차 기반 결정) |
| 판정 기준 | 성공: Temporal 이 Single-hop 대비 결합 σ 2배 초과 낮음 / 부분: σ 1~2배 / 실패: Temporal ≥ Single-hop |
| Judge prompt | 공통 `ACCURACY_PROMPT` (태스크 분기 없음) |

---

### #6 — Multi-session reasoning 어려움

**평가 방법 (논문 §8.4.7)**:
- 벤치마크: LongMemEvalS 500 문항 중 **Multi-session(MS) 카테고리**
- 비교 대상: 6개 configuration 에서 MS 점수를 관찰
  - C5 (GPT-5 baseline), C6 (user-q), C7 (k=30)
  - C12 (GPT-5-mini, k=20), C14 (k=50), C15 (k=100)
- 지표: MS 카테고리 llm_score + 타 카테고리 (SSU, SSP, SSA, TR, KU) 대비 상대적 수준
- Judge-LLM: gpt-4o-mini, question-specific judge prompts (§7.2)
- 성격: 별도 독립변수 sweep 이 아닌 **ablation 조합 전체 걸쳐 카테고리 관찰 분석**

| 항목 | 수치 | 조건 | 유형 | 출처 |
|---|---|---|---|---|
| MS 최고 점수 | 0.872 | GPT-5-mini, k=100 (C15) | 현상 | §8.4.7 Table 14 |
| MS (C5 baseline) | 0.797 | GPT-5 | 현상 | §8.4.7 Table 14 |
| MS (C6 user-q) | 0.835 | GPT-5 | 현상 | §8.4.7 Table 14 |
| MS (C7 k=30) | 0.850 | GPT-5 | 현상 | §8.4.7 Table 14 |
| MS (C12 mini, k=20) | 0.850 | GPT-5-mini | 현상 | §8.4.7 Table 14 |
| MS (C14 mini, k=50) | 0.842 | GPT-5-mini | 현상 | §8.4.7 Table 14 |
| 정성 기술 | "most challenging category" | — | 정성 | §8.4.7 |

**참고**: k 확대만으로 개선 한계 있음. 논문은 SplitQuery(Agent 보조)로 일부 대응.

**재현 평가 방법 (본 과제 §5.4 우선순위 4)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 (#4/#12 과 동일) |
| 실행 방식 | **#4/#12 k sweep run 재분석** — 별도 run 불필요 |
| 독립변수 | 없음 (관찰 분석) |
| 종속변수 | MS 카테고리 점수 vs 타 카테고리 (SSU/SSP/SSA/TR/KU) 점수 |
| 추가 코드 | MS 집계 전용 스크립트 (카테고리별 결합 σ 2배 기준선 자동 계산) |
| 반복 | #4/#12 반복 결과 재사용 |
| 판정 기준 | 성공: 모든 k 값에서 MS < SSU/SSA 가 결합 σ 2배 초과 / 부분: 일부 k / 실패: MS 가 타 카테고리와 비슷하거나 높음 |

---

### #12 — k scaling 비효율

**평가 방법 (논문 §8.4.8)**:
- 벤치마크: LongMemEvalS 500 문항
- 비교 방식: **정확도 vs 입력 token (Pareto)** 분석 — #4와 동일 k sweep 이나 비용 축을 주로 봄
- Answer LLM: GPT-5 (C6-C8), GPT-5-mini (C12, C14, C15)
- 독립변수: k ∈ {20, 30, 50, 100}
- 지표:
  - overall llm_score
  - **Input token per 500-question run** (M 단위, Table 15)
- 관점: Pareto-optimal config 식별 — C12(k=20) 가 2.58M token 으로 0.922 달성 → 최적점

| 항목 | 수치 | 조건 | 유형 | 출처 |
|---|---|---|---|---|
| k=20 overall (C12) | 0.922 | GPT-5-mini, 2.58M input token | 현상 (Pareto) | §8.4.8 Table 15 |
| k=50 overall (C14) | 0.928 | GPT-5-mini, 5.97M input token | 현상 | §8.4.8 Table 15 |
| k=100 overall (C15) | 0.930 | GPT-5-mini, 9.79M input token | 현상 | §8.4.8 Table 15 |
| token 증가율 (k=20→k=100) | 3.79× | 2.58M → 9.79M | 비교 | §8.4.8 (계산) |
| 정확도 증가 (k=20→k=100) | +0.8%p | 0.922 → 0.930 | 비교 | §8.4.8 (계산) |

**참고**: #4와 동일 메커니즘의 비용 측면. 동일 솔루션(Adaptive k)으로 동시 해결 가능.

**재현 평가 방법 (본 과제 §5.1 우선순위 1 — #4와 통합)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 실행 방식 | **#4 k sweep 과 동일 run 공유** — 별도 run 불필요 |
| 독립변수 | k ∈ {10, 20, 30, 50, 100} (#4와 동일) |
| 고정변수 | #4 와 동일 (C12 조합) |
| 종속변수 (추가) | 쿼리당 input token (M 단위) · token/accuracy Pareto 분석 |
| 관점 | Pareto-optimal k 식별 — token 증가 대비 accuracy 한계효용 측정 |
| 판정 기준 | 성공: k=20→k=100 시 token ≥3× 증가 대비 accuracy 증가가 결합 σ 2배 이내 (논문 +0.8%p 대응) / 실패: 고 k 에서 accuracy 선형 증가 |

---

## 3. Ablation 단계별 기여도 (참고)

6개 후보와 직접 연결되는 최적화 기여도 (§8.4 Table 13).

| 최적화 | 개선 폭 | 비교 config | 연결된 후보 |
|---|---|---|---|
| Retrieval depth (k: 20→30) | +4.2% | C6 vs C7 | #4 |
| Context formatting (JSON-str) | +2.0% | C4 vs C5 | — |
| Search prompt (Edwin1→3) | +1.8% | C9 vs C11 | — |
| COT → simple prompt | +1.6% | C1 vs C4 | — |
| User-query bias correction | +1.4% | C5 vs C6 | #3 |
| Sentence chunking | +0.8% | C6 vs C9 | — |
| GPT-5 → GPT-5-mini | +2.6% | C11 vs C12 | (모델 선택) |

---

## 4. 비용·토큰 관련 수치 (참고)

| 항목 | 수치 | 조건 | 출처 |
|---|---|---|---|
| MemMachine (Memory) input token | 4.20M | LoCoMo 1540 questions, gpt-4.1-mini | §6.3 Table 8 |
| MemMachine (Agent) input token | 8.57M | LoCoMo, gpt-4.1-mini | §6.3 Table 8 |
| Mem0 input token | 19.21M | LoCoMo, main/HEAD | §6.3 Table 8 |
| MemMachine vs Mem0 input token 감소율 | ~78% | Memory 모드 기준 | §6.3 (계산·§8.3 "~80%") |
| ToolSelect 라우팅 평균 | 1,049 input + 195 output token | HotpotQA hard | §5.7 Table 5 |
| SplitQuery 평균 | 1,229 input + 435 output token | HotpotQA hard | §5.7 Table 5 |

---

## 5. 수치의 한계 (논문 §9.7 명시)

재측정·재현 시 반드시 고려해야 하는 요인:

- **eval-LLM 민감도**: 동일 시스템이라도 평가 모델 달라지면 점수 변동
- **prompt 템플릿 민감도**: Edwin1/2/3 버전에 따라 ±1~2%p 변동 관찰
- **model provider 업데이트**: API 측 모델 업그레이드에 따라 수치 변동 가능
- **cross-system 비교 혼합**: Mem0/Zep 등은 재실행 결과와 공개 수치 혼용
- **C1~C4 configs**: 부분 question subset으로 측정 후 전체 500개로 확장 — 직접 비교 시 주의
- **ablation dimension 간 interaction 미검증** — 2개 이상 변경의 공동 효과는 논문이 검증하지 않음

→ **6개 후보 전부 자체 baseline 재측정 필수**.

---

## 6. 재참조용 인덱스 (빠른 조회)

| 찾는 내용 | 섹션 |
|---|---|
| 특정 후보 수치 | §2 (각 후보 subsection) |
| 배경 전체 점수 | §1 |
| 개선 기여도 비율 | §3 |
| 토큰·비용 | §4 |
| 수치 신뢰성 한계 | §5 |

---

## 업데이트 이력

- 2026-04-22 v1: 초기 작성 — 6개 후보 집중 정리
- 2026-04-24 v2: 논문 PDF 직접 교차검증 후 보완
  - #4 섹션: GPT-5-mini k=30 (0.916) 값 추가 (§8.4.6 본문 인용)
  - #4 섹션: "lost in the middle" 원인 메커니즘 인용 추가 (§8.4.1)
  - #2 섹션: Memory(91.2%/90.98%) vs Agent(93.2%/92.31%) 대조 수치 명시 (§5.6 본문)
  - #2 섹션: Table 3(95.5%) vs Table 4/본문(92.31%) 불일치 경고 추가
  - §0 문구 정확도 개선: "#3·#4만 before/after" 의 "본 과제 관점" 제약 명시
- 2026-04-24 v3: 중복 삽입 교정 + 논문 전수 대조 검증
  - v2 에 이미 존재하던 "재현 평가 방법" 표 형식 블록 6개 유지
  - 중복으로 잘못 추가했던 list 형식 블록 6개 제거 (실질 내용 변경 없음)
  - 논문 §5·§7·§8, Table 3·4·5·9·10·11·12·13·14·15 전수 대조 완료 → **수치·서술 모두 논문과 일치**
  - 미세 개선: #2 섹션의 "3-way 라우팅" 인용 §5.2 → §5.3 (Query Routing) 로 정정
  - 유지된 주의 사항: Table 3(95.5%) vs Table 4·본문(92.31%) 논문 내부 불일치 — 본문·Table 4 값 사용
- 2026-04-24 v3: 6개 후보 전 섹션에 **재현 평가 방법** 하위 표 추가 (본 과제 §5 연동)
  - 벤치마크 / 독립변수 / 고정변수 / 종속변수 / 코드·YAML 수정 / 판정 기준 일관 형식
  - #2: HotpotQA 500 선정 방식 재조사 필요 주석 포함
  - #5: cat5 filter 포팅 요구사항 반영
  - #6·#12: 독립 run 없음 — #4와 산출물 공유 명시
- 2026-04-24 v2.1: §2 각 6개 후보별 평가 방법 블록 추가
  - 논문 §5.6·§7.1·§7.2·§8.4 본문 기반
  - 각 후보의 벤치마크·비교 방식·Answer LLM·고정 설정·지표·Judge-LLM 명시
