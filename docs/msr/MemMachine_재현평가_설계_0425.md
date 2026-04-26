# MemMachine 6개 후보 정량 수치 정리

**작성일**: 2026-04-25
**목적**: Phase 1에서 선정된 6개 후보 문제에 대한 논문 정량 수치를 **재참조 가능한 형태**로 보존
**출처**: MemMachine 논문 (arXiv:2604.04853v1), `memmachine_diagnostic_v2.md`, `docs/msr/20260425_eval_code_review.md`, `docs/msr/20260425_modified_list_v0.2.md`
**원칙**: 논문에 명시된 수치만 기록. 추론·추정은 명시적으로 `[추정]` 태그.

---

## 0. 참고 구분 — 수치의 두 가지 유형

| 유형 | 의미 | 용도 |
|---|---|---|
| **현상(Symptom)** | 문제가 존재함을 보이는 수치 | Phase 1 문제 정의 근거 |
| **before/after** | 개선 전/후 대조 수치 | Phase 3 개선 효과 검증 근거 |
| **비교(Comparative)** | 타 시스템 또는 타 조건 대비 | Phase 1 심각도 판단 근거 |

→ **6개 후보 모두 현상 수치는 논문에 존재**. 본 과제 관점의 **개선책 before/after 대조(동일 시스템·다른 설정)는 #3·#4만** 논문 내 존재. #2 는 "Memory(before) vs Agent(after)" 수치가 있으나 Agent-only 해결책이라 본 과제 지향(Agent-free)과 다른 축.

**운영점 일탈 (v4 추가)**: 본 과제 운영점은 paper C12와 단일 변수 일치하지 않음 — JSON-str=**off** 가 본 과제 방침이므로, paper C5/C6/C12(JSON-str=on)와 직접 비교 불가. 따라서 §2 #3·#4·#12 결과는 "paper C{n} 직접 재현"이 아니라 "해당 변수(`user_q` / `k`) 효과의 외삽"으로 해석한다. 자세한 사유는 §5 "v4 추가 한계" 참조.

---

## 0.1 코드 구현 상태 요약 (v0.2 + PR #7 연동)

`docs/msr/20260425_modified_list_v0.2.md` (기존 evaluation 코드 기준) 와 PR #7 (eval-tool MVP) 의 양쪽 상태를 §2/§4 운영 가능성 관점에서 재정리.

| 항목 | v0.2 상태 | PR #7 상태 | 본 문서 영향 |
|---|:---:|:---:|---|
| `prepend_user_prefix` 토글 (#3·#4·#12) | ✅ | ✅ (config 토글) | §2 #3·#4 운영 가능 |
| `k` sweep `{10,20,30,50,100}` (#4·#12) | ✅ | ✅ (`sweep.search_limit`) | §2 #4·#12 운영 가능 |
| `chunk` YAML wiring (`message_sentence_chunking`) | ✅ | ✅ (ingest 전 반영) | §2 #4 chunk=on 정상 |
| `chunk × prefix × k` 매트릭스 | ✅ (`run_benchmark_matrix.sh`) | 확장 가능 | PR #7 기본 `p4.yaml` 은 chunk=on / prefix=on / k sweep. 전체 매트릭스는 run YAML 의 `sweep` / `fixed` 를 사용자가 확장하면 가능 (기본 제공 아님) |
| LoCoMo cat5 skip 포팅 | ✅ | ✅ | §2 #5 운영 가능 (`evaluation/retrieval_agent/locomo_search.py:135`) |
| HotpotQA `length=500` 정책 | ✅ | ✅ (`split=validation`) | §2 #2 표 갱신 (선정 방식 명시) |
| EDWIN1/EDWIN3 prompt 주입 | ❌ | ❌ (hook only) | EDWIN 텍스트 미확보 → 외삽 해석 |
| DB snapshot 동결/복원 | ❌ | ❌ | 본 작업 범위 밖 |
| 파일럿 5회 + N 자동결정 wrapper | ❌ | ❌ (`n_runs>1` 명시 error) | §3.5 fallback (N=1) |
| 자동 판정 스크립트 (σ×2) | ❌ | ❌ | §2 판정 기준 수기 운영 |
| #6 MS 재분해 집계 스크립트 | ❌ | ✅ (`analyze --decompose-multisession`) | §2 #6 자동화됨 |
| #12 token/accuracy Pareto | ❌ | ✅ (`analyze --pareto`) | §2 #12 자동화됨 |
| `configuration.yml` 원본 보호 | — | ✅ (run-local working copy) | mode=existing 도 안전 |
| token / per-tool / recall metric carry | ❌ | ✅ | analyze 가 mean_recall / overall_recall / by_tool / mean_tokens_per_query 산출 |

→ PR #7 이후로 #6 / #12 / config 보호 / metric carry 4 항목이 추가 해결됨. 남은 미해결: EDWIN 실 prompt 적용, DB snapshot, 반복 wrapper, 자동 σ×2 판정 — 본 도구 범위 밖 (§3.5 fallback 운영).

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
| 반복 | PR #7 MVP 는 `n_runs=1` 고정. `n_runs>1` 은 `NotImplementedError`. 파일럿 5회 / N 자동결정 / σ×2 자동 판정은 future work |
| 판정 기준 | 성공: Agent > Memory 가 결합 σ 2배 초과 + Agent token > Memory token / 부분: 한쪽만 재현 / 실패: Memory ≥ Agent (analyze 출력값 기준 수기 판단) |
| 500 선정 방식 | 코드 `evaluation/retrieval_agent/hotpotQA_test.py:215 dataset.select(range(length))` = split 앞 500 (무작위 sampling/seed 없음). paper "hard 500" 과의 동일성 미검증. v0.2 운영 결정에 따라 `length=500` 정책 사용 |

**LoCoMo Multi-hop(282) 측정 운영 결정 (v4 추가)**: 본 과제는 LoCoMo cat2(multi-hop) 자체 측정을 수행하지 않는다. 위 표의 LoCoMo Multi-hop 0.8759/0.8830/0.8972 수치는 paper §8.1 Table 10 인용으로만 사용한다. 자체 측정은 HotpotQA 500 으로 한정 (`evaluation/retrieval_agent/locomo_search.py:135` 의 cat5 skip 은 cat2-only slicing 이 아님 — 별도 slicing 미구현).

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

**한정성 명시 (v4 추가)**: 본 과제 운영점은 paper C5/C6 의 단일 변수 ablation 동치 조건(JSON-str=on, chunk=off, Edwin1, k=20)을 갖추지 않음 — 본 과제는 JSON-str=**off**, chunk 별도 sweep. 따라서 본 후보 결과는 "C5/C6 직접 재현"이 아닌 **"user_q 효과의 재현 (C5/C6 외삽)"** 으로 해석한다.

**재현 평가 방법 (본 과제 §5.5 우선순위 5)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 독립변수 | `evaluation.longmemeval.prepend_user_prefix` 토글 (C5: false / C6: true) |
| 고정변수 (논문 C5/C6 조합) | chunk=**off** / json_str=**off** (방침) / Prompt=**Edwin1** / k=20 / Answer LLM 사내 오픈 LLM |
| 종속변수 | overall `llm_score` |
| 토글 방식 | PR #7 eval-tool 의 `configs/problems/p3.yaml` 의 `sweep.prepend_user_prefix: [false, true]` 로 처리. 소스 패치 불필요 |
| Answer prompt | EDWIN1 텍스트 미확보 → PR #7 은 prompt placeholder/hook 만 제공. 실제 적용은 future work. 본 후보 결과는 default ANSWER_PROMPT 기반 외삽 (paper EDWIN1 exact reproduction 아님) |
| 반복 | PR #7 MVP 는 `n_runs=1` 고정. `n_runs>1` 은 `NotImplementedError`. 파일럿 5회 / N 자동결정 / σ×2 자동 판정은 future work |
| 판정 기준 | 성공: prefix on 에서 overall 상승이 결합 σ 2배 초과 / 부분: 방향 맞으나 σ 1~2배 / 실패: 방향 반대 (analyze 출력값 기준 수기 판단) |
| 주의 | JSON-str=off 상태이므로 논문 (on) 과 차이 있음. 재현 수치가 논문 +1.4%p 와 다를 수 있음을 사전 명시. JSON-str off 운영점에서는 §3 ablation 기여도 누계가 paper(C4↔C5 +2.0%p, C5↔C6 +1.4%p) 와 일치하지 않음. User_q 구현 경로(legacy vs retrieval_agent) 논문 명시 없음 |
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

**C12 직접 재현 불가 (v4 추가)**: 본 과제 운영점은 chunk=on, user_q=on, **JSON-str=off**, Edwin3 — paper C12(JSON-str=on)와 단일 변수 일치하지 않음. 본 후보 결과는 "C12 재현"이 아닌 **"JSON-str off 조건에서의 k sweep"** 이며, paper §8.4.1 "lost in the middle" 메커니즘과 직접 대조 불가. 한계 격상 — §5 v4 한계 참조.

**재현 평가 방법 (본 과제 §5.1 우선순위 1)**:

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 독립변수 | k ∈ {10, 20, 30, 50, 100} |
| 고정변수 (논문 C12 조합) | chunk=**on** / user_q=**on** / json_str=**off** (방침) / Prompt=**Edwin3** / `expand_context`=코드 기본값 / Answer LLM 사내 오픈 LLM |
| 종속변수 | `llm_score` overall · 카테고리별 6종 (SSU/SSP/SSA/TR/KU/MS) · 쿼리당 input token · 쿼리당 latency |
| YAML 설정 | PR #7 eval-tool 의 `configs/problems/p4.yaml` 이 `fixed.message_sentence_chunking: true` + `fixed.prepend_user_prefix: true` 를 working configuration.yml 에 ingest 전 반영 |
| 토글 방식 | k sweep 은 `sweep.search_limit`, prefix/chunk 는 `fixed`. 소스 패치 불필요 |
| Answer prompt | EDWIN3 텍스트 미확보 → PR #7 은 prompt placeholder/hook 만 제공. 실제 적용은 future work. 본 후보 결과는 default ANSWER_PROMPT 기반 외삽 (paper EDWIN3 exact reproduction 아님) |
| 반복 | PR #7 MVP 는 `n_runs=1` 고정. `n_runs>1` 은 `NotImplementedError`. 파일럿 5회 / N 자동결정 / σ×2 자동 판정은 future work |
| 판정 기준 | 성공: k 를 늘리는 동안 정확도 상승 둔화·꺾임이 결합 σ 2배 초과 관찰 / 부분: σ 1~2배 / 실패: k 무관 또는 비례 증가 (analyze 출력값 기준 수기 판단) |

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
| 코드 수정 | **포팅 완료** — cat5 skip 로직이 `evaluation/retrieval_agent/locomo_search.py:135` 에 반영됨 (v0.2 §1 ✅). 추가 코드 수정 없음 |
| Answer prompt | 기본값 COT (Edwin 미설정 fallback) — MemVerge 답변 후 EDWIN3 재실행 여지 |
| 반복 | PR #7 MVP 는 `n_runs=1` 고정. `n_runs>1` 은 `NotImplementedError`. 파일럿 5회 / N 자동결정 / σ×2 자동 판정은 future work |
| 판정 기준 | 성공: Temporal 이 Single-hop 대비 결합 σ 2배 초과 낮음 / 부분: σ 1~2배 / 실패: Temporal ≥ Single-hop (analyze 출력값 기준 수기 판단) |
| Judge prompt | 공통 `ACCURACY_PROMPT` (태스크 분기 없음) |

**LoCoMo cat2(multi-hop) 측정 범위 (v4 추가)**: 본 과제는 LoCoMo cat2(multi-hop) 자체 측정을 수행하지 않는다. #2 의 LoCoMo Multi-hop 인용으로 대체 (§2 #2 "LoCoMo Multi-hop 측정 운영 결정" 참조). 본 후보(#5)는 cat5 adversarial 446 제외 후 잔여 1,094 문항의 카테고리별 점수에서 Temporal vs Single-hop 비교에 집중.

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
| 자동화 | PR #7 의 `python scripts/run_pipeline.py --config p6_*.yaml --stage analyze --decompose-multisession` 가 MS vs 타 카테고리 gap 산출 (`ms_accuracy / others_mean_accuracy / ms_vs_others_gap` per cell). 결합 σ×2 자동 판정은 future work — 현재는 raw 값을 수기 비교 |
| 반복 | PR #7 MVP 는 `n_runs=1` 고정. `n_runs>1` 은 `NotImplementedError`. 파일럿 5회 / N 자동결정 / σ×2 자동 판정은 future work. #4/#12 가 만든 산출물을 그대로 재사용 |
| 판정 기준 | 성공: 모든 k 값에서 MS < SSU/SSA 가 결합 σ 2배 초과 / 부분: 일부 k / 실패: MS 가 타 카테고리와 비슷하거나 높음 (analyze 출력값 기준 수기 판단) |

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
| 종속변수 (추가) | 쿼리당 input/output token · accuracy/recall Pareto |
| 자동화 | PR #7 의 `python scripts/run_pipeline.py --config p12_*.yaml --stage analyze --pareto` 가 k 별 `mean_tokens_per_query / mean_input_token / mean_output_token / mean_num_episodes / mean_recall / overall_recall` 출력 |
| 반복 | PR #7 MVP 는 `n_runs=1` 고정. `n_runs>1` 은 `NotImplementedError`. 파일럿 5회 / N 자동결정 / σ×2 자동 판정은 future work. #4 산출물 재사용 |
| 판정 기준 | 성공: k=20→k=100 시 token ≥3× 증가 대비 accuracy 증가가 결합 σ 2배 이내 (논문 +0.8%p 대응) / 실패: 고 k 에서 accuracy 선형 증가 (analyze 출력값 기준 수기 판단) |

---

## 3. Ablation 단계별 기여도 (참고)

6개 후보와 직접 연결되는 최적화 기여도 (§8.4 Table 13).

| 최적화 | 개선 폭 | 비교 config | 연결된 후보 | 본 과제 운영점 적용 가능성 (v4 추가) |
|---|---|---|---|---|
| Retrieval depth (k: 20→30) | +4.2% | C6 vs C7 | #4 | paper C6/C7 = GPT-5 + JSON-str=on. 본 과제 = GPT-5-mini + JSON-str=off → **별도 baseline 필요**. 절대 +4.2%p 재현 기대 불가 |
| Context formatting (JSON-str) | +2.0% | C4 vs C5 | — | JSON-str=off 방침이므로 **본 과제에서 측정 불가** (C4/C5 동치 검증 자체 불가) |
| Search prompt (Edwin1→3) | +1.8% | C9 vs C11 | — | EDWIN 주입 ❌ (v0.2 §E) → **측정 불가** until BLOCKER 해소 |
| COT → simple prompt | +1.6% | C1 vs C4 | — | 본 과제 운영점은 단일 prompt 고정. 별도 측정 안 함 |
| User-query bias correction | +1.4% | C5 vs C6 | #3 | JSON-str=off 환경에서 **재측정 필요** (paper +1.4%p 와 절대값 불일치 가능) |
| Sentence chunking | +0.8% | C6 vs C9 | — | v0.2 chunk×prefix×k 매트릭스로 본 과제 환경에서 **직접 측정 가능 (✅)** |
| GPT-5 → GPT-5-mini | +2.6% | C11 vs C12 | (모델 선택) | 본 과제는 사내 오픈 LLM 단일 — paper 모델 비교는 외삽으로만 사용 |

**적용 가능성 표기 의미**: "측정 불가/필요"는 paper 와 동일 단일 변수 ablation 이 성립하지 않는다는 뜻. 본 과제는 운영점에서의 절대 효과만 확인 가능하며, paper 의 +x%p 와 직접 합산하지 않는다.

---

## 3.5 반복 전략 임시 운영 규약 (PR #7 MVP 기준)

§2 각 후보 표의 "반복" 칸이 인용하는 **본 과제 §4 (파일럿 5회 + N 자동결정 wrapper)** 는 PR #7 eval-tool MVP 에서도 미구현이다. PR #7 은 n_runs 안전장치만 제공한다.

- **반복 수**: PR #7 은 `n_runs=1` 고정 — `run_pipeline.py` 가 `n_runs > 1` 시 명시적 `NotImplementedError`. 파일럿 5회 / N 자동결정은 future work
- **σ 산출**: `analyze` 단계가 cell 별 `accuracy_std` 만 자동 계산. 더 복잡한 결합 σ 는 raw `judge.jsonl` / `retrieve.jsonl` 후처리에서 사용자가 산출
- **σ×2 판정**: 자동 판정 도구 미구현 → **수기 판정** — 각 후보 §2 표의 "판정 기준" 을 사람이 읽고 결정
- **부분 결과 기록**: PR #7 의 `results/{run}/{stage}.jsonl` 가 모든 raw row 를 보존하므로 wrapper 구현 후 재집계 가능

→ 파일럿 5회 / N 자동결정 / σ×2 자동 집계 wrapper 구현 시 본 §3.5 는 후속 갱신에서 제거 예정.

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

### 5.0 v4 추가 한계 (코드↔문서 정합)

본 과제 운영점이 paper 와 단일 변수 일치하지 않거나, σ×2 판정 체계 작동 전제가 무너진 4개 항목. **paper §9.7 한계보다 본 과제 결과 해석에 직접적 영향**.

1. **EDWIN1/EDWIN3 prompt 적용 미구현 (PR #7 hook only)**
   - PR #7 eval-tool 은 `prompts/EDWIN{1,3}.txt` placeholder + `scripts/stages/generate.py` 의 prompt-file hook 만 제공. EDWIN 텍스트 미확보 + 실제 generate-time 적용 로직은 future work (DECISIONS.md D-003)
   - 따라서 §2 #3·#4·#12·#5 결과는 **paper EDWIN exact reproduction 이 아님** → 답변 prompt = `longmemeval_test.py:22 ANSWER_PROMPT` (default)
   - 결과는 "EDWIN 외삽 / default prompt 기반 operational reproduction" 으로 해석. §2 판정 기준 (σ×2) 도 default prompt 통제 하의 비교

2. **JSON-str off 운영 결정의 영향**
   - 본 과제 방침: `json_str=off` (§2 #3·#4 표 고정변수). paper C5/C6/C12 는 모두 JSON-str=on (§8.4.2)
   - **paper C5/C6/C12 직접 비교 불가** → §2 #3 = "user_q 효과 외삽", §2 #4 = "JSON-str off 조건의 k sweep"
   - §3 ablation 기여도 누계도 paper 와 다름 (§3 운영점 적용 가능성 컬럼 참조)

3. **`run_benchmark_matrix.sh` chunk 잔류**
   - `LONGMEM_CHUNK_VALUES=(off on)` (`evaluation/retrieval_agent/run_benchmark_matrix.sh:17`) 루프 종료 시 마지막 순회값 = `on` 잔류
   - `restore_config` trap 은 EXIT 에서만 발화 → LongMemEval 루프 종료 후 LoCoMo/HotpotQA 단계 진입 시 chunk=on 잔류 조건에서 측정됨 (`run_benchmark_matrix.sh:200-227`)
   - paper §8.1·§5.6 은 LoCoMo/HotpotQA chunk 를 명시하지 않거나 default(off) 가정 → **본 과제 LoCoMo/HotpotQA 결과는 "chunk=on 잔류" 조건의 측정값**임을 한계로 명시

4. **`--skip-ingest` 사용 시 chunk on/off mismatch 위험**
   - chunk=on 으로 ingest 된 스토리지에 chunk=off 로 검색 → 인덱싱과 검색의 chunk 정의가 다름
   - chunk 축 sweep 중 `--skip-ingest` 활성화 시 일부 셀 결과 **무효** (README_MSR `--skip-ingest` 주의사항 절 참조, v0.2 §C)

### 5.1 paper §9.7 명시 한계

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
| 반복 전략 임시 운영 규약 | §3.5 |
| 토큰·비용 | §4 |
| 수치 신뢰성 한계 | §5 |
| 코드↔문서 정합 한계 (BLOCKER 포함) | §5.0 |
| v0.2 코드 구현 상태 요약 | §0.1 |
| v4 우선순위 권고 | §6.1 |

---

## 6.1 v4 우선순위 권고 (현재 문제 재현 관점)

`20260425_eval_code_review.md` §D 권고 8개 중 본 문서 §2~§5 에 직접 영향이 있는 5개를 추출.

1. **EDWIN 주입 경로 확정 (BLOCKER)** — 미해결 시 §2 #3·#4·#12·#5 모든 판정이 무의미. §0.1, §5.0 #1
2. **JSON-str off 일탈 본문 격상** — paper C5/C6/C12 직접 비교 불가 사실을 §0 운영점 일탈 단락 / §5.0 #2 에 격상 (적용 완료)
3. **chunk 잔류** — 매트릭스 스크립트가 LongMemEval 루프 종료 시 chunk 를 명시적 default 로 reset (코드 수정 후속) 또는 본 문서에 한계 기록 (§5.0 #3 채택). 권고: 둘 다 적용
4. **HotpotQA 500 선정 방식 갱신** — §2 #2 표에서 코드 인용으로 표현 통일 (적용 완료)
5. **반복 N fallback** — §3.5 임시 운영 규약 (적용 완료). wrapper 구현 시 0426 갱신에서 제거

---

## 업데이트 이력

- 2026-04-25 v4: `20260425_eval_code_review.md` / `20260425_modified_list_v0.2.md` 반영
  - §0 에 "운영점 일탈" 단락 추가 (JSON-str=off 본 과제 방침 → paper C5/C6/C12 직접 비교 불가)
  - §0.1 신규 — v0.2 코드 구현 상태 요약 (✅ 6 / ❌ 5) + 본 문서 영향 매핑
  - §2 #2 — HotpotQA 500 선정 방식을 "재조사 필요" → 코드 `dataset.select(range(500))` 인용. LoCoMo Multi-hop 282 자체 측정 미수행 결정 명시
  - §2 #3 — C5/C6 한정성 명시 단락 추가 ("user_q 효과 외삽"). 주의 칸에 ablation 누계 불일치 사유 보강
  - §2 #4 — "C12 직접 재현 불가" 단락 첫 위치 격상
  - §2 #5 — cat5 skip 포팅 "필요" → "완료 (`locomo_search.py:135`)" 갱신. cat2 측정 범위 명시
  - §3 — 운영점 적용 가능성 컬럼 추가 (paper Cn ↔ 본 과제 운영점 매핑)
  - §3.5 신규 — 반복 전략 임시 운영 규약 (N=3 고정, σ 후처리, 수기 판정)
  - §5.0 신규 — v4 추가 한계 4건 (EDWIN BLOCKER / JSON-str off / chunk 잔류 / `--skip-ingest` mismatch)
  - §6.1 신규 — v4 우선순위 권고 5건
  - §6 인덱스에 신규 섹션 5건 추가
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
