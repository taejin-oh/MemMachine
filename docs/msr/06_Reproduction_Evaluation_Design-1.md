# 재현 평가 설계 (Reproduction Evaluation Design) [v5]

[← Executive Report](./00_Executive_Report_Outline.md)

**작성일**: 2026-04-22
**위치**: Phase 2 진입 직전 — Phase 1에서 선정된 6개 후보 문제가 우리 환경에서 실제로 재현되는지 확인하는 세부 실행 설계
**선행 문서**: `02_Phase1_ProblemDefinition.md` (6개 후보 선정), `memmachine_quant_metrics.md` (논문 수치)

> **실험 용어가 처음이라면** [부록 A — 실험 용어 기초](#부록-a--실험-용어-기초) 를 먼저 읽어주세요.

> **v5 주요 변경점**:
> - **Provider**: Bedrock 표현 제거, 사내 vLLM 환경(`openai-chat-completions` + base_url) 확정. Temperature 조정 불가
> - **Seed 전략**: "variance 관리 전략" 으로 개명. Temperature=0 도 포기, 반복 실행 + DB snapshot 동결이 유일한 수단
> - **재현 판정 기준**: 표준편차 **2배 초과** (보수적) 로 통일
> - **Phase 0 파일럿**: 3개 벤치마크 × 30문항 × 5회 (벤치마크별 variance 차이 파악)
> - **3개 flag 제어 방식** (코덱스 Q1~Q4 반영): chunk=YAML / user_q=소스 1줄 / json_str=휴면 플래그 (MemVerge 문의 대상)
> - **LoCoMo cat5 필터**: retrieval_agent 경로에 우리가 직접 포팅

---

## §1 목적

Phase 1 에서 선정된 6개 후보 문제에 대해, **논문이 지적한 현상이 우리 환경에서도 나타나는지** 확인한다. 본 재현이 완료되어야 Phase 2 원인 가설 검증 단계로 안전하게 진입할 수 있다.

---

## §2 평가 원칙 — 문제 패턴 재현

**원칙**: 절대 점수가 아닌 **문제 패턴(problem pattern)** 재현을 목표로 한다.

**배경**
- 논문 §9.7: "점수는 eval-model 선택, prompt 템플릿, provider 업데이트에 민감"
- 우리 환경은 **3중 변동 요인** 있음:
  - Answer LLM 이 사내 오픈 LLM (Llama/Qwen 계열) 으로 교체됨
  - Provider(vLLM) 에 **seed 파라미터 없음** (코드 확정)
  - Provider 에 **temperature 파라미터도 전달 불가** (openai-chat-completions 제약)
- 따라서 절대 점수 직접 비교 구조적으로 불가능

**실무적 정의**
- **재현 성공**: 논문이 보고한 현상의 형태(shape) 가 우리 환경에서도 관찰되며, 차이가 **결합 표준편차의 2배 초과**
- **부분**: 방향은 같으나 차이가 표준편차의 1~2배 사이
- **실패**: 방향이 반대거나 차이가 표준편차 이하

이 경우에도 "우리 환경에서는 해당 문제가 다른 양상" 이라는 유의미한 정보로 남음.

---

## §3 공통 환경

### 3.1 MemMachine

| 항목 | 설정 | 근거 |
|---|---|---|
| 버전 | v0.3.x (논문 Table 9 준거) · pyproject.toml 에 version 필드 없음 [추정 v0.3.x] | [F2] |
| 설치 형태 | 자사 실제 인스턴스 (D1 확정) | — |
| DB | PostgreSQL + pgvector + Neo4j + SQLite (논문 §4) | — |
| Agent 모드 | 필요 시 enable (#2 평가에서 사용) | — |
| STM capacity | **64000 char (episode 개수 아님)** — 논문 §4.3 서술과 단위 다름 | `short_term_memory.py:81` [F4] |
| Contextualization | `expand_context` 값에 따라 backward = `expand_context // 3`, forward = 나머지. **MemMachine 코드 기본값 그대로 사용** | `declarative_memory.py:398-400` [F5] |
| Sentence chunking | NLTK Punkt 기본 영어, 크기/오버랩 로직 없음 | `utils.py:154-181` [F6] |

### 3.2 Provider 및 모델 슬롯 (v5 수정)

**Provider 확정**: 사내 vLLM

| 항목 | 값 | 근거·제약 |
|---|---|---|
| MemMachine provider 타입 | `openai-chat-completions` | vLLM 은 OpenAI 호환 endpoint 제공 |
| `base_url` | 사내 vLLM endpoint URL | 환경 확정 후 TBD |
| `api_key` | dummy 문자열 (vLLM 에선 불필요하나 필드 요구) | — |
| temperature 파라미터 | **전달 불가** (MemMachine 의 openai-chat-completions provider 가 파라미터 미노출) | [F8] |
| seed 파라미터 | **전 provider 부재** | [F8] |

**모델 슬롯**

| 역할 | 확정 |
|---|---|
| Answer LLM | 사내 오픈 LLM (Llama/Qwen 계열) — **TBD** |
| Judge LLM | Answer LLM 과 다른 모델 — **TBD** |
| Embedding | `text-embedding-3-small` 대체 오픈 모델 — **TBD** |
| Reranker | Cohere rerank-v3-5 대체 오픈 모델 — **TBD** |

### 3.3 평가 벤치마크 및 실행 스크립트 (v4 유지)

| 벤치마크 | 실행 스크립트 | 비고 |
|---|---|---|
| LongMemEvalS 500 | `evaluation/retrieval_agent/longmemeval_test.py` + `run_test.sh` | **retrieval_agent 경로 사용** |
| LoCoMo 1,540 | `evaluation/retrieval_agent/locomo_{ingest,search}.py` | cat5 필터 포팅 필요 |
| HotpotQA (hard) | `evaluation/retrieval_agent/hotpotQA_test.py` | S1·S2 병행 |

**경로 선택 원칙**: 본 평가 전체에서 **retrieval_agent 신경로로 통일**. legacy 경로와 신경로는 3개 flag 기본값이 다르므로 경로 혼용 시 결과 비교 불가.

### 3.4 측정 지표 (3축)

| 축 | 지표 | 산출 방법 |
|---|---|---|
| Accuracy | `llm_score` (LLM Judge) | LongMemEval 은 **태스크별 judge prompt** (7종), LoCoMo/HotpotQA 는 공통 `ACCURACY_PROMPT` — [F3] |
| Cost | 쿼리당 input/output token | MemMachine 로그 |
| Latency | 쿼리당 ms | MemMachine 측정 |

### 3.5 Judge prompt 구성

| 벤치마크 | Judge 파일 | 특이사항 |
|---|---|---|
| LoCoMo / HotpotQA / WikiMultiHop | `evaluation/*/llm_judge.py` 의 `ACCURACY_PROMPT` | 관대한 매칭 |
| LongMemEvalS | `longmemeval_evaluate.py:155-174` `get_anscheck_prompt()` | **태스크별 7종 분기** |

**LongMemEval 태스크별 특이사항**: temporal-reasoning 은 "do not penalize off-by-one errors" (#5 재현 판정 기준에 반영), knowledge-update 는 "previous+updated answer" 허용, single-session-preference 는 Rubric 기반, abstention 은 "unanswerable 식별".

### 3.6 3개 Configuration Flag 의 제어 방식 (v5 신규 — 코덱스 Q1~Q4 반영)

논문 Table 12 의 3개 flag 가 실제로 어떻게 제어되는지가 코드 조사로 확정됨:

| Flag | 제어 레이어 | 기본값 | 우리가 할 일 |
|---|---|---|---|
| **chunk** | YAML key `long_term_memory.message_sentence_chunking` | False | YAML 한 줄 명시 |
| **user_q** | 평가 스크립트 1줄 편집 | retrieval_agent 경로에서 off | `longmemeval_test.py:214` 직전에 prefix 삽입 여부 |
| **json_str** | 휴면 플래그 (리포 내 True 세팅 0 hit) | None (off) | **MemVerge 공식 방법 확인 대기 — 없으면 off 상태로 진행** |

**JSON-str 진행 방침 (옵션 C 결정)**
- 현재 코드로는 on 상태 구현 방법 불명확
- 본 평가는 **JSON-str = off 상태로 진행**
- MemVerge 답변 수신 후 필요 시 재실험

---

## §4 Variance 관리 전략 (v5 근본 수정)

> 배경: Seed 와 Temperature 모두 통제 불가 환경. 결정성 통제 수단 0개.
> 기본 개념은 [부록 A1](#a1-seed-가-뭔가) · [A2](#a2-왜-반복-실행이-필요한가) · [A3](#a3-temperature--seed-와-별도-장치) 참조.

### 4.1 제약 사항 최종 확정

| 요소 | 우리 환경 | 영향 |
|---|---|---|
| Seed | 전 provider 부재 [F8] | 완전 결정성 확보 불가 |
| Temperature | openai-chat-completions provider 에서 전달 불가 | 보조 결정성 확보도 불가 |
| Provider | vLLM (고정) | 변경 없음 |

→ **결정성 통제 수단 0개**. Variance 는 오로지 "반복 실행 평균" 으로만 관리.

### 4.2 Variance 관리 전략 — 3단계

**전략 1 — DB snapshot 동결**
- Ingestion 을 1회 수행하여 DB 상태 확정
- 모든 반복 실험이 **동일 DB snapshot** 에서 query 만 재실행
- 효과: Ingestion-side variance 완전 제거
- 예외: chunk on/off 가 독립변수일 때는 별도 ingest

**전략 2 — 반복 실행 + 평균**
- 동일 설정에서 다회 반복 run
- 평균 + 표준편차 보고
- 반복 수는 파일럿 결과로 결정 (§4.3)

**전략 3 — 판정 기준 보수화 (v5 신규)**
- "유의한 차이" 기준: **결합 표준편차의 2배 초과**
- 이유: Seed·Temperature 둘 다 통제 불가한 환경에서 variance 가 클 것으로 예상. 작은 차이는 우연으로 판단

### 4.3 Phase 0 파일럿 (v5 수정)

**목적**: 본 실험 반복 수 결정 + 벤치마크별 variance 특성 파악

| 구분 | 값 |
|---|---|
| 대상 | 3개 벤치마크 (LongMemEvalS, LoCoMo, HotpotQA) |
| 샘플 | 각 벤치마크 30문항 무작위 부분집합 |
| 반복 | 동일 설정 5회 |
| 총 실행 | 3 × 30 × 5 = 450 query |
| 산출 | 벤치마크별 평균·표준편차·변동계수 |

### 4.4 본 실험 반복 수 결정

| 파일럿 표준편차 | 본 실험 반복 수 |
|---|---|
| < 0.5%p | 2회 (최소 보장) |
| 0.5 ~ 1.5%p | 3회 |
| 1.5 ~ 3.0%p | 5회 |
| > 3.0%p | 7~10회 + variance 원인 분석 |

벤치마크별 variance 가 다를 수 있으므로 **후보별로 다른 반복 수 허용** (예: #2 는 3회, #5 는 5회).

### 4.5 보고 형식

```
세팅: [구체 configuration]
Provider: vLLM (openai-chat-completions, base_url: ...)
Answer LLM: [모델명]
Judge LLM: [모델명]
Temperature/Seed: 제어 불가 (모델 기본값)
DB snapshot: [ingestion 완료 시점 기록]
반복: 5회
결과:
  overall: 0.875 ± 0.012 (mean ± std)
  개별 run: [0.875, 0.881, 0.869, 0.872, 0.878]
  변동계수(CV): 0.014
  결합 표준편차 2배: 0.024
  → 재현 판정: 대조 조건과 차이 > 0.024 시에만 '유의' 판정
```

---

## §5 후보별 평가 설계

### §5.1 후보 1 — #4/#12 Adaptive k (우선순위 1)

**재현 대상**
- k 증가 시 정확도 비단조 (§8.4.1, C6→C7→C8: 0.870→0.912→0.890)
- token 3.8× 증가 대비 accuracy +0.8%p (§8.4.8)

**실험 설계**

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 독립변수 | k ∈ {10, 20, 30, 50, 100} |
| 고정변수 (논문 C12 조합) | chunk=on / user_q=on / json_str=**off** (방침) / prompt=**Edwin3** / `expand_context`=코드 기본값 / Answer LLM=사내 오픈 |
| 종속변수 | `llm_score` overall · 카테고리별 · input token · 쿼리당 latency |
| 반복 | §4 전략 적용 |

**YAML + 소스 수정 방식**
```yaml
# C12 YAML 예시 (MemVerge 확인 후 확정)
long_term_memory:
  message_sentence_chunking: true   # chunk on
```

소스 수정:
```python
# longmemeval_test.py:214 직전 삽입 (user_q on)
question = f"User: {question}"
```

**필수 선행 조건**
- Edwin3 prompt 전문 — MemVerge 필수 1
- C12 YAML 예시 — MemVerge 필수 2
- json_str off 상태 기록 (MemVerge 필수 3 답변 수신 후 on 으로 재실행 고려)

**판정 기준 (v5 보수화)**
- **성공**: k 를 늘려가는 동안 어느 k 에서 정확도 상승이 둔화되거나 꺾임이 **결합 표준편차 2배 초과** 수준에서 관찰
- **부분**: 방향은 같으나 격차가 표준편차 1~2배 사이
- **실패**: 정확도가 k 와 무관하거나 k 에 계속 비례 증가

### §5.2 후보 2 — #5 Temporal Reasoning (우선순위 2)

**재현 대상**: Temporal 카테고리가 Single-hop 대비 낮음 (§8.2 Table 11)

**실험 설계**

| 구분 | 값 |
|---|---|
| 벤치마크 | LoCoMo 1,540 |
| 독립변수 | 모드 ∈ {Memory, Agent} |
| 고정변수 | Answer LLM, embedding, reranker |
| 종속변수 | 카테고리별 `llm_score` |
| 반복 | §4 전략 적용 |

**필터 적용 (v4 결정 유지)**
- LoCoMo cat5 (adversarial 446) 제외 필터를 **retrieval_agent 경로에 우리가 직접 포팅**
- 구현: `restapiv2_locomo_search.py:257-264` 의 cat5 skip 로직을 `evaluation/retrieval_agent/locomo_search.py` 에 동일하게 이식
- 담당 B 가 착수 첫 작업

**판정 기준 (v5 보수화)**
- **성공**: Temporal 점수가 Single-hop 보다 **결합 표준편차 2배 초과** 낮음
- **부분**: 격차가 표준편차 1~2배
- **실패**: Temporal 이 Single-hop 과 비슷하거나 더 높음

### §5.3 후보 3 — #2 Multi-hop (우선순위 3)

**재현 대상**: Memory vs Agent 정확도·token 격차 (§5.6 Table 3)

**실험 설계**

| 구분 | 값 |
|---|---|
| 벤치마크 | HotpotQA hard 500 |
| 독립변수 | 모드 ∈ {Memory, Retrieval Agent} × 선정 {S1, S2} |
| 고정변수 | Answer LLM, embedding, reranker |
| 종속변수 | Accuracy · Recall · 쿼리당 token · Per-tool breakdown |
| 반복 | §4 전략 적용 |

**"Hard 500" 선정 방식**

| 방식 | 기준 | 목적 |
|---|---|---|
| **S1** | `validation` split 앞 500개 순차 (코드 방식) | 코드 그대로 재현 |
| **S2** | seed=42 무작위 500 | 순서 민감성 배제 |

Agent 구성 (확인됨): ToolSelectAgent / ChainOfQuery / SplitQuery

**판정 기준 (v5 보수화)**
- **성공**: S1·S2 양쪽에서 Agent > Memory 가 **결합 표준편차 2배 초과** 재현 + Agent token > Memory token
- **부분**: 한쪽만 재현, 또는 정확도 격차만 / token 격차만
- **실패**: Memory ≥ Agent

### §5.4 후보 4 — #6 Multi-session Reasoning (우선순위 4)

**재현 대상**: MS 카테고리가 다른 카테고리보다 낮음 (§8.4.7 Table 14)

**실험 설계**

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 (§5.1 과 동일) |
| 실행 방식 | §5.1 k sweep run 재분석 — **별도 run 불필요** |
| 독립변수 | 없음 (관찰 분석) |
| 종속변수 | MS vs 타 카테고리 점수 |

**판정 기준**
- **성공**: 모든 k 값에서 MS 가 SSU/SSA 대비 **결합 표준편차 2배 초과** 낮음
- **부분**: 일부 k 에서만 격차
- **실패**: MS 가 타 카테고리와 비슷하거나 높음

### §5.5 후보 5 — #3 User/Assistant bias (우선순위 5)

**재현 대상**: `"user:"` prefix 적용 시 overall +1.4%p (C5: 0.855 → C6: 0.870)

**실험 설계**

| 구분 | 값 |
|---|---|
| 벤치마크 | LongMemEvalS 500 |
| 독립변수 | 평가 스크립트 소스 편집 여부 (C5: prefix 없음 / C6: prefix 삽입) |
| 고정변수 (논문 C5/C6 조합) | chunk=**off** / user_q=조건별 / json_str=**off** (방침) / prompt=**Edwin1** / k=20 |
| 종속변수 | overall `llm_score` |
| 반복 | §4 전략 적용 |

**C5/C6 재현 방법 (v5 구체화)**
- 경로: retrieval_agent 통일
- C5: `longmemeval_test.py` 원본 그대로 (user_q off)
- C6: `longmemeval_test.py:214` 직전에 `question = f"User: {question}"` 한 줄 삽입 (user_q on)
- 두 버전을 **소스 패치 파일** 로 버전 관리

**필수 선행 조건**
- Edwin1 prompt — MemVerge 필수 1
- C5, C6 YAML 예시 — MemVerge 필수 2
- **주의**: JSON-str 상태가 논문(on) 과 다름(off) → 재현 수치가 논문 +1.4%p 와 다를 수 있음을 사전 명시

**운영 결정**
- `exclude_abstention` = True 로 통일 실행
- MemVerge 공식 답변은 가벼운 확인 용도

**판정 기준 (v5 보수화)**
- **성공**: prefix on 에서 overall 점수 상승이 **결합 표준편차 2배 초과**
- **부분**: 방향은 맞으나 격차가 표준편차 1~2배
- **실패**: prefix on 에서 점수 하락 또는 방향이 다름

---

## §6 실행 순서 (D3 반영: 3명 병렬)

**0라운드 — 공통 파일럿 (v5 확장)**

- 모델 슬롯 TBD 확정 후 수행
- **담당 B: retrieval_agent 경로에 cat5 skip 필터 포팅** 병행
- 각 벤치마크 30문항 × 5회 → variance 측정
- 벤치마크별 반복 수 결정
- DB snapshot 생성·저장

**1라운드 — 병렬 본 실험**

| 담당자 | 후보 | 소요 예상 |
|---|---|---|
| A | #4/#12 (§5.1) — k sweep 5개 × 반복 수 | 가장 큼 |
| B | #5 (§5.2) — LoCoMo Memory + Agent | 중 |
| C | #2 (§5.3) — HotpotQA S1+S2 × Memory+Agent | 중·상 |

**2라운드 — 완료자부터**
- #6 (§5.4): A 산출물 재분석
- #3 (§5.5): LongMemEvalS C5/C6 재실행

---

## §7 산출물

각 담당자:
1. **실험 config YAML** — 모델, provider, k, prompt 버전(Edwin1/3), chunk 설정, DB snapshot 식별자
2. **소스 패치** (user_q on 버전 등) — `.patch` 파일로 버전 관리
3. **Raw 결과 log** — 문항별 판정·token·latency
4. **집계 결과표** — 논문 Table 대응 + 반복별 수치 + mean±std + 결합 표준편차 2배 기준선
5. **재현 판정 리포트** (1~2페이지) — 성공/부분/실패, 근거, 관찰 차이

---

## §8 불확실성 및 한계

### 8.1 MemVerge 문의 필요 항목 (v5 확장)

| 우선순위 | 항목 | 이유 |
|---|---|---|
| **필수 1** | Edwin1, Edwin3 prompt 전문 | 1·5순위 실행 전제, 코드 부재 |
| **필수 2** | C5, C6, C12 YAML 예시 + 패치 | 3개 flag 의 제어 레이어 확인 후 종합 세팅 필요 |
| **필수 3** | retrieval_agent 경로에서 JSON-str 활성화 방법 | 휴면 플래그 상태, 우리 환경 재현 방법 불명 |
| **가벼운 확인** | `exclude_abstention` 적용값 | 해석 정확도 향상 |

상세는 `08_MemVerge_Info_Request.md` v2 참조.

### 8.2 알려진 한계

- Eval-LLM / prompt / provider 업데이트에 점수 민감 — **반복 평균 + 판정 기준 보수화** 로 완화
- **Seed + Temperature 둘 다 통제 불가** — Variance 완전 통제 불가, 파일럿에서 환경 안정성 먼저 평가
- **JSON-str off 상태 진행** — 논문 구성 (on) 과 상이, 수치 직접 비교 어려움
- **User-Q 구현 방식 불명 가능성** — 논문이 어느 경로(legacy/retrieval_agent)로 C5/C6 을 측정했는지 불명 [불확실]
- 오픈 LLM 한정 — 상용 LLM 환경 재현은 효과 검증 후 MemVerge 에 요청
- STM capacity 단위 차이 (char vs episode) — 재현 시 구현 단위 준수

### 8.3 코드 조사로 확정된 사실

MemMachine commit `15380b7` (2026-04-20) 기준.

| ID | 항목 | 상태 | 위치 |
|---|---|---|---|
| [F1] | Edwin1/2/3 prompt | 미발견 (코드 부재) | — |
| [F2] | MemMachine version | 미부여 | — |
| [F3] | Judge prompt 분기 | LoCoMo/HotpotQA 공통 / LongMemEval 태스크별 7종 | `evaluation/*/llm_judge.py`, `longmemeval_evaluate.py:155-174` |
| [F4] | STM capacity | 64000 char (episode 아님) | `short_term_memory.py:81` |
| [F5] | Contextualization | backward = `expand_context // 3`, forward = 나머지 | `declarative_memory.py:398-400` |
| [F6] | Sentence chunking | NLTK Punkt 영어 기본 | `utils.py:154-181` |
| [F7-LME] | LongMemEval abstention | `_abs` 접미사, 기본값 불일치 | `longmemeval_models.py:68`, `longmemeval_evaluate.py:41-62, 200-203` |
| [F7-LoCoMo] | LoCoMo cat5 skip | `restapiv2_locomo_search.py:257-264` 에만 명시 | — |
| [F7-HotpotQA] | HotpotQA 500 | validation split 앞 500 slice | `hotpotQA_test.py:195-202` |
| [F8] | Provider 파라미터 | seed 전 부재, temp 는 Bedrock 만 (vLLM 은 `openai-chat-completions` 에 속해 전달 불가) | `*_language_model.py` |
| [F9] | C1~C17 라벨 | 코드 부재, YAML 수동 조합 | — |
| [F10-chunk] | chunk flag 제어 | YAML `long_term_memory.message_sentence_chunking` (기본 False) | `episodic_config.py:116-119`, `declarative_memory.py:228-254` |
| [F10-user_q] | user_q flag 제어 | 평가 스크립트 1줄 편집 — legacy 기본 on / retrieval_agent 기본 off | `longmemeval_search.py:161` (legacy), `longmemeval_test.py:214` 근처 (신경로) |
| [F10-json_str] | json_str flag | **휴면 플래그**, 리포 전체 True 세팅 0 hit | `memmachine_helper_base.py:140-196`, `restapiv2_locomo_search.py:91,98` |

---

## §9 Phase 2 진입 조건 (Gate)

- [ ] 0라운드 파일럿 완료 및 본 실험 반복 수 확정
- [ ] MemVerge 필수 1·2·3 수신 (또는 대체 방침 확정)
- [ ] LoCoMo retrieval_agent 경로에 cat5 skip 필터 포팅 완료
- [ ] 최소 우선순위 1~3 후보 재현 판정 완료 (결합 표준편차 2배 기준)

---

# 부록 A — 실험 용어 기초

## A1. Seed 가 뭔가

**한 줄 정의**: LLM 답변의 무작위성 출발점이 되는 숫자. 같은 seed 를 주면 같은 답이 나오도록 제어.

**본 연구 상황 (v5)**: MemMachine provider 에 seed 파라미터 부재 [F8]. 우리 vLLM 환경에서는 seed 기반 결정성 확보 포기.

## A2. 왜 반복 실행이 필요한가

**한 줄 정의**: 한 번 측정한 점수는 "실력" 인지 "흔들림" 인지 구분 불가. 여러 번 반복하여 흔들림 크기를 함께 보고.

**v5 변경**: Seed·Temperature 둘 다 통제 불가 → variance 가 예상보다 클 수 있음. 파일럿에서 **벤치마크별로 variance 를 먼저 측정** 하여 본 실험 반복 수 결정.

## A3. Temperature — Seed 와 별도 장치

**한 줄 정의**: LLM 답변의 다양성 조절값. 0 = 가장 확률 높은 답만 선택.

**본 연구 상황 (v5)**: MemMachine 의 `openai-chat-completions` provider 에서 Temperature 파라미터 전달 경로 없음. vLLM 서버 측 기본값에 의존. 결정성 통제 수단 0개.

## A4. 결합 표준편차 2배 기준 (v5 신규)

**왜 "2배"인가**: Variance 통제 수단이 0개이므로 보통의 실험보다 점수 흔들림이 클 가능성. "표준편차 초과" 기준은 너무 느슨하여 우연한 차이를 재현으로 오판할 위험. 2배 기준은 실무에서 흔히 쓰이는 **대략 95% 신뢰구간** 수준.

**결합 표준편차**: 두 조건 A·B 를 비교할 때, 각 조건의 표준편차 σ_A 와 σ_B 를 합쳐서 계산 — `√(σ_A² + σ_B²)`. 우리 판정 기준은 **mean 차이 > 결합 표준편차 × 2**.

## A5. 왜 파일럿을 먼저 하나

**한 줄 정의**: 본 실험 반복 수 결정을 위해 소규모로 흔들림 먼저 측정.

**v5 파일럿 범위**: 3개 벤치마크 각 30문항 × 5회 = 450 query. 벤치마크별로 variance 가 다를 가능성 반영.

## A6. 독립변수 · 종속변수 · 고정변수

- **독립변수**: 바꿔가며 실험하는 것
- **종속변수**: 결과로 측정하는 것
- **고정변수**: 실험 내내 동일하게 유지하는 것

**본 평가 예시**

| 후보 | 독립변수 | 종속변수 | 고정변수 |
|---|---|---|---|
| #4 Adaptive k | k 값 5개 | 정확도·token·latency | Answer LLM, embedding, prompt (Edwin3), chunk 등 |
| #3 User prefix | 스크립트 소스 편집 유무 | overall 점수 | Edwin1, k=20, chunk off 등 |
| #5 Temporal | 모드 2개 | 카테고리별 점수 | Answer LLM, embedding, reranker |
| #2 Multi-hop | 모드 2 × 선정 2 | Accuracy·Recall·token | Answer LLM, embedding, reranker |

---

## 변경 이력

- **v5 (2026-04-22)**: Provider·Variance·3개 flag 제어·판정 기준 전면 수정
  - Provider: 사내 vLLM (`openai-chat-completions`) 확정
  - Seed+Temperature 둘 다 통제 불가 → variance 관리 전략 재설계
  - 판정 기준: 결합 표준편차 2배 초과 (보수적)
  - Phase 0 파일럿: 3 벤치마크 × 30문항 × 5회
  - 3 flag 제어 방식 확정 (chunk=YAML, user_q=소스, json_str=휴면 플래그)
  - MemVerge 필수 항목 3건 확장
- v4 (2026-04-22): expand_context·cat5 필터 사내 결정으로 해결, MemVerge 항목 축소
- v3 (2026-04-22): MemMachine 코드 조사 결과 반영. Seed 포기.
- v2 (2026-04-22): 부록 A 추가
- v1 (2026-04-22): 초기 작성
