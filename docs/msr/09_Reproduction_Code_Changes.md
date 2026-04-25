# 재현 평가 코드 수정 가이드 (Reproduction Code Changes) [v1]

**작성일**: 2026-04-24
**용도**: Phase 1에서 선정된 6개 후보 문제의 **재현 평가 실행**을 위해 MemMachine 리포에 가해야 할 모든 수정 사항을 **coding agent가 단독 수행 가능한 수준**으로 명세.
**전제 기준**
- MemMachine 리포 commit `15380b7` (2026-04-20)
- 평가 경로: **retrieval_agent** 신경로로 통일
- Provider: 사내 vLLM (`openai-chat-completions`)
- Edwin prompt 전문: 로컬 파일 `Edwin_prompt` 확인 완료 (L4-157)

**선행 문서**
- `06_Reproduction_Evaluation_Design.md` v5 — 실험 설계 원본
- `07_Reproduction_Summary.md` v5 — 요약판
- `08_MemVerge_Info_Request.md` v3 — 문의 항목
- `README_edwin.md` + `case{N}_*.txt` — 후보별 prompt 파일

---

## §1 핵심 표 — 후보별 수정 매트릭스

| 후보 | BM | 수정 대상 파일 | 수정 유형 | 핵심 내용 | 근거 |
|---|---|---|---|---|---|
| **#4/#12** Adaptive k | LongMemEvalS 500 | `evaluation/retrieval_agent/longmemeval_test.py` | 소스 패치 | L214 직전 `question = f"User: {question}"` 삽입 | [F10-user_q] |
| | | (YAML config) | YAML 설정 | `long_term_memory.message_sentence_chunking: true` | [F10-chunk] |
| | | `mmai` 객체 속성 | 설정 주입 | `mmai.lme_answer_prompt = "EDWIN3"` | Edwin_prompt L184-199 |
| | | 실행 스크립트 | 파라미터 sweep | k ∈ {10, 20, 30, 50, 100} | 06 §5.1 |
| **#3** User/Assistant bias | LongMemEvalS 500 | `evaluation/retrieval_agent/longmemeval_test.py` | 소스 패치 (2버전) | C5: 원본 / C6: L214 직전 prefix 삽입 | [F10-user_q] |
| | | (YAML config) | YAML 설정 | `message_sentence_chunking: false`, k=20 | [F10-chunk] |
| | | `mmai` 객체 속성 | 설정 주입 | `mmai.lme_answer_prompt = "EDWIN1"` | Edwin_prompt L194-195 |
| **#5** Temporal | LoCoMo 1,540 | `evaluation/retrieval_agent/locomo_search.py` | **신규 포팅** | `restapiv2_locomo_search.py:257-264` 의 cat5 skip 로직 이식 | [F7-LoCoMo] |
| | | 실행 스크립트 | 모드 sweep | Memory / Agent 모드 각 1회 | 06 §5.2 |
| | | `mmai` 객체 속성 | 설정 주입 | `lme_answer_prompt` 미설정 → 기본 "COT" 실행 | Edwin_prompt L188-189 |
| **#2** Multi-hop | HotpotQA 500 | `evaluation/retrieval_agent/hotpotQA_test.py` | 로직 교체 | L195-202 의 `[:500]` slice → 고정 샘플 로드 | [F7-HotpotQA] |
| | | **신규 스크립트** | 샘플 생성 | seed=42 로 validation 전체에서 500 인덱스 추출 → `hotpotqa_sample_500.json` | 직전 턴 사용자 결정 |
| | | 실행 스크립트 | 모드 sweep | Memory / Retrieval Agent 각 1회 | 06 §5.3 |
| | | `mmai` 객체 속성 | 설정 주입 | `lme_answer_prompt` 미설정 → 기본 "COT" 실행 | Edwin_prompt L188-189 |
| **#6** Multi-session | LongMemEvalS 500 | (없음) | 재분석만 | #4/#12 의 k sweep 산출물을 카테고리별 재분해 | 06 §5.4 |

---

## §2 공통 인프라 (모든 후보 공통)

### §2.1 Provider 설정

| 항목 | 값 | 근거 |
|---|---|---|
| provider 타입 | `openai-chat-completions` | [F8] |
| `base_url` | 사내 vLLM endpoint — **TBD** | 환경 확정 후 |
| `api_key` | dummy 문자열 (필드 요구사항) | — |
| temperature / seed | 전달 불가 — vLLM 서버 기본값 의존 | [F8] |

### §2.2 DB snapshot 동결 스크립트 (신규 필요)

**목적**: Ingestion 을 1회만 수행 후 snapshot 을 보존, 모든 반복 run 이 동일 DB 상태에서 query 만 재실행 (06 §4.2 전략 1)

| 작업 | 대상 |
|---|---|
| Snapshot 생성 | PostgreSQL (pgvector 포함) + Neo4j + SQLite 3종 |
| Snapshot ID 기록 | 각 실험 결과에 명기 |
| 복원 스크립트 | 동일 snapshot 에서 반복 run 가능하도록 |

**주의**: `chunk on/off` 가 독립변수일 때는 별도 ingest 필요 (06 §4.2 전략 1 예외).

### §2.3 반복 실행 wrapper

| 기능 | 설명 |
|---|---|
| 파일럿 5회 실행 | 3 벤치마크 × 30문항 × 5회 = 450 query |
| 본 실험 N회 실행 | 파일럿 표준편차 → 반복 수 자동 결정 (06 §4.4) |
| 결과 aggregation | mean ± std 계산, 결합 표준편차 2배 기준선 자동 산출 |

### §2.4 판정 스크립트

- 입력: 두 조건의 raw 결과 log
- 출력: mean 차이 vs 결합 σ × 2 비교 → 성공 / 부분 / 실패 자동 판정 (06 §4.2 전략 3)

---

## §3 후보별 상세 수정 지시

### §3.1 #4/#12 Adaptive k (1순위)

**벤치마크**: LongMemEvalS 500 · **실행 스크립트**: `evaluation/retrieval_agent/longmemeval_test.py`

#### 수정 1 — user_q prefix 삽입 (소스 패치)

**위치**: `evaluation/retrieval_agent/longmemeval_test.py` L214 직전
**조건**: C12 조합의 `user_q = on` 재현용 [F10-user_q]

```python
# [수정 전] L214 근처 원본
# ... question 변수 사용 직전

# [수정 후] L214 직전에 한 줄 삽입
question = f"User: {question}"
```

패치 파일명 권장: `patches/user_q_on.patch` — git 관리

#### 수정 2 — YAML config (chunk on)

**파일**: 실행 시 사용하는 config YAML
**조건**: C12 조합의 `chunk = on` [F10-chunk]

```yaml
long_term_memory:
  message_sentence_chunking: true   # 기본값 false → true
```

#### 수정 3 — Edwin3 prompt 주입

**위치**: `mmai` 객체 초기화 시점 (경로는 MemVerge 답변 대기 — §5 참조)
**조건**: C12 조합의 `prompt = Edwin3` (06 §5.1)
**실행 값**: `mmai.lme_answer_prompt = "EDWIN3"` (대소문자 무관, Edwin_prompt L187 에서 `.upper()` 처리)
**Prompt 전문**: `case4_12_adaptive_k.txt` (EDWIN3_ANSWER_PROMPT 원문, Edwin_prompt L139-157)

#### 수정 4 — k sweep 실행

- 독립변수: k ∈ {10, 20, 30, 50, 100} — 5회 별도 run
- 각 k 값마다 반복 수 N 만큼 실행 (파일럿 기반 결정)

#### 측정 지표

- `llm_score` overall · 카테고리별 (6종: SSU, SSP, SSA, TR, KU, MS)
- 쿼리당 input/output token
- 쿼리당 latency (ms)

---

### §3.2 #3 User/Assistant bias (5순위)

**벤치마크**: LongMemEvalS 500 · **실행 스크립트**: `evaluation/retrieval_agent/longmemeval_test.py`

#### 수정 1 — 소스 2버전 관리

| 버전 | 파일 상태 | 대응 조건 |
|---|---|---|
| **C5** | 원본 그대로 (user_q off) | C5 조합 |
| **C6** | L214 직전 `question = f"User: {question}"` 삽입 | C6 조합 |

→ **`#4/#12 수정 1`과 동일 패치**, 적용/미적용 2회 실행

#### 수정 2 — YAML config (chunk off) + k=20

```yaml
long_term_memory:
  message_sentence_chunking: false   # 기본값 유지
```

- `chunk` YAML key 는 확정 ([F10-chunk])
- `k=20` 설정 key 는 **확인 필요** — MemMachine YAML 내 k 파라미터 정확한 key 이름·위치는 코드 조사에서 미확인 [추정]. 실행 시 CLI 인자 또는 별도 key 에서 주입 가능성. → MemVerge Q1(필수 2 YAML 예시)에 포함되어 있음
- **주의**: #4/#12 와 config 값이 다름. 반드시 별도 config 파일로 관리

#### 수정 3 — Edwin1 prompt 주입

**실행 값**: `mmai.lme_answer_prompt = "EDWIN1"`
**Prompt 전문**: `case3_user_bias.txt` (EDWIN1_ANSWER_PROMPT 원문, Edwin_prompt L90-111)

#### 실행

- 독립변수: 소스 버전 (C5 / C6) — 2회 별도 run
- 각각 반복 수 N 만큼 실행

#### 측정 지표

- `llm_score` overall
- 비교 대상: C5 vs C6 overall 차이 (논문 +1.4%p 재현 여부)

#### 주의

- `exclude_abstention = True` 로 통일 (06 §5.5)
- JSON-str off 진행 — 논문 (on) 과 차이 있음. 재현 수치가 논문 +1.4%p 와 다를 수 있음을 사전 명시
- **User_q 구현 경로 불명** — 논문이 legacy 경로 (`longmemeval_search.py:161`) vs retrieval_agent 경로 중 어느 쪽으로 C5/C6 을 측정했는지 확인 불가 [F10-user_q, 06 §8.2]. 본 평가는 retrieval_agent 경로로 통일 → 논문과 경로 차이 있을 수 있음을 사전 명시

---

### §3.3 #5 Temporal Reasoning (2순위)

**벤치마크**: LoCoMo 1,540 · **실행 스크립트**: `evaluation/retrieval_agent/locomo_search.py`, `locomo_ingest.py`

#### 수정 1 — cat5 필터 포팅 (신규 구현) ★ 담당 B 첫 작업

**원본 로직 위치**: `restapiv2_locomo_search.py:257-264`
**이식 대상**: `evaluation/retrieval_agent/locomo_search.py` (동일 위치 또는 쿼리 루프 진입 직전)
**목적**: LoCoMo adversarial cat5 (446 문항) 제외 필터를 retrieval_agent 경로에 이식 [F7-LoCoMo]

```python
# restapiv2_locomo_search.py:257-264 의 skip 로직을 그대로 이식
if question.get("category") == 5:
    continue   # adversarial 문항 제외
```

(실제 원본 코드 구조에 맞게 변수명·키 조정 필요)

#### 수정 2 — 모드 sweep 실행

- 독립변수: 모드 ∈ {Memory, Agent} — 2회 별도 run
- 각각 반복 수 N 만큼 실행

#### 수정 3 — Edwin prompt (주입 경로 확정 시)

**현재 상태**: `lme_answer_prompt` 미설정 → Edwin_prompt L188-189 에 따라 **기본값 COT 자동 적용**
**설계 문서 지정 prompt 없음**: 06 §5.2 에 명시적 지정 없음 → 기본값 진행 가능
**[추정] 권장값**: MemVerge 답변 수신 시 EDWIN3 로 교체 검토 (KNOWLEDGE UPDATE·시간 처리 내장)
**Prompt 전문**: `case5_temporal.txt` (EDWIN3 원문 — 교체 시 사용)

#### 측정 지표

- `llm_score` 카테고리별
- 주목 카테고리: Temporal vs Single-hop

#### 주의

- Judge prompt 는 공통 `ACCURACY_PROMPT` — 태스크 분기 없음 ([F3])

---

### §3.4 #2 Multi-hop (3순위)

**벤치마크**: HotpotQA 500 · **실행 스크립트**: `evaluation/retrieval_agent/hotpotQA_test.py`

#### 수정 1 — 고정 랜덤 500 샘플 생성 (신규 스크립트)

**목적**: 반복 실행마다 동일 샘플 재사용으로 sample 변동 노이즈 제거 (직전 턴 사용자 결정)

**전제 [확인 필요]**: 기존 `hotpotQA_test.py:195-202` 에서 dataset 로딩 시 "hard" 필터가 어떻게 적용되는지 (코드 자체에서 `level=="hard"` 필터링 vs 데이터셋 자체가 hard 만 포함) 는 코드 조사 결과에 명시 없음. 샘플 생성 스크립트는 **기존 로딩 파이프라인 결과 전체** 에 대해 random sampling 수행.

**신규 스크립트 `generate_hotpotqa_sample.py`** (개념):

```python
import random
import json
# 기존 hotpotQA_test.py 와 동일한 dataset 로딩 로직 재사용
from hotpotQA_test import load_dataset_like_original   # 기존 함수 재사용 권장

def generate_fixed_sample(seed=42, n=500, output_path="hotpotqa_sample_500.json"):
    dataset = load_dataset_like_original()   # 기존 hard 필터 파이프라인 그대로
    all_indices = list(range(len(dataset)))
    random.seed(seed)
    sample_indices = sorted(random.sample(all_indices, n))
    with open(output_path, "w") as f:
        json.dump(sample_indices, f)
    return sample_indices

if __name__ == "__main__":
    generate_fixed_sample()
```

**주의**: 실제 구현 시 `hotpotQA_test.py` 의 데이터 로딩 함수를 그대로 import 해서 사용 — 데이터셋 필터 조건(hard 여부 포함)이 본 실험과 기존 코드에서 완전히 일치해야 함.

**산출물**: `hotpotqa_sample_500.json` (500개 인덱스 리스트) — **실험 내내 불변**

#### 수정 2 — `hotpotQA_test.py` 샘플 로드 교체

**위치**: `hotpotQA_test.py:195-202` [F7-HotpotQA]
**수정 내용**: 기존 `[:500]` slice 방식을 고정 샘플 파일 로드로 교체

```python
# [수정 전] L195-202 부근 (정확한 라인은 리포 확인 후)
# sample = dataset[:500]   # 앞 500개 순차 slice

# [수정 후]
import json
with open("hotpotqa_sample_500.json") as f:
    fixed_indices = json.load(f)
sample = [dataset[i] for i in fixed_indices]   # 고정 인덱스 기반 선택
```

#### 수정 3 — 모드 sweep 실행

- 독립변수: 모드 ∈ {Memory, Retrieval Agent} — 2회 별도 run
- Agent 구성 (확인됨): ToolSelectAgent + ChainOfQuery + SplitQuery
- 각 모드마다 반복 수 N 만큼 실행

> **변경**: 06 §5.3 의 S1(앞 500) + S2(seed=42 무작위) 병행 설계는 **폐기**. 고정 랜덤 500 1세트로 단일화.

#### 수정 4 — Edwin prompt (현재 상태)

**현재 상태**: `lme_answer_prompt` 미설정 → 기본값 COT 자동 적용
**권장값**: COT (Multi-hop 에 적합한 7단계 추론 구조) — 설계 문서 미지정이나 기본값과 일치 → **그대로 진행**
**Prompt 전문**: `case2_multihop.txt` (COT_ANSWER_PROMPT 원문, Edwin_prompt L15-87)

#### 측정 지표

- Accuracy · Recall
- 쿼리당 token
- Per-tool breakdown (ToolSelectAgent / ChainOfQuery / SplitQuery 각각의 token·호출 횟수)

#### 주의

- Judge prompt 는 공통 `ACCURACY_PROMPT` ([F3])

---

### §3.5 #6 Multi-session Reasoning (4순위)

**벤치마크**: LongMemEvalS 500 (#4/#12 와 동일 run 재사용) · **실행 스크립트 수정 없음**

#### 수정 내용

- **별도 run 불필요**: #4/#12 의 k sweep 산출물(각 k 에서의 raw 결과 log)을 MS 카테고리 중심으로 **재분해·재집계**만 수행
- 신규 스크립트 (집계용): MS vs SSU/SSA 카테고리별 점수 추출 + 결합 σ 2배 기준선 자동 계산

#### 측정 지표

- 각 k 값에서 MS vs SSU, SSA 카테고리 점수 차이

---

## §4 실행 순서 (의존성 그래프)

```
[Phase 0: 기반 준비]
  │
  ├─ 모델 슬롯 4종 확정 (TBD) ·········· 전제 조건
  ├─ vLLM base_url 확정 ···················· 전제 조건
  │
  ├─ MemVerge 문의 답변 수신 (Q1~Q4)
  │    ├─ lme_answer_prompt 주입 경로 → #4/#12·#3 실행 가능
  │    └─ 나머지는 미수신 시에도 진행 가능 (기본값 or off 방침)
  │
  ├─ [공통] DB snapshot 스크립트 구현 ······ 공통 인프라
  ├─ [공통] 반복 실행 wrapper 구현 ········· 공통 인프라
  ├─ [공통] 판정 스크립트 구현 ············· 공통 인프라
  │
  ├─ [담당 B] cat5 skip 필터 포팅 (#5 선행)
  ├─ [담당 C] HotpotQA 고정 랜덤 500 샘플 생성 (#2 선행)
  ├─ [담당 A] user_q prefix 소스 패치 작성 (#4/#12 용, 2라운드 #3 에서도 재사용)
  │
  ▼

[Phase 1: 파일럿 — 전원 공동]
  │
  ├─ 3 벤치마크 × 30문항 × 5회 → variance 측정
  ├─ 벤치마크별 본 실험 반복 수 결정 (06 §4.4)
  └─ DB snapshot 생성·저장
  │
  ▼

[Phase 2: 본 실험 1라운드 — 병렬]
  │
  ├─ 담당 A: #4/#12  (LongMemEvalS, k sweep 5개 × N)
  ├─ 담당 B: #5      (LoCoMo, Memory + Agent × N)
  └─ 담당 C: #2      (HotpotQA, Memory + Agent × N)
  │
  ▼

[Phase 2: 본 실험 2라운드 — 완료자부터]
  │
  ├─ #6 (담당 A 산출물 재분석 — 별도 run 없음)
  └─ #3 (LongMemEvalS C5/C6 재실행)
```

---

## §5 미확정 항목 (MemVerge 답변 대기)

| ID | 항목 | 영향 | 미수신 시 방침 |
|---|---|---|---|
| Q1 | `lme_answer_prompt` 주입 경로 (`mmai` 객체 설정 방법) | #4/#12·#3 실행 불가 | **블로커** — 반드시 수신 필요 |
| Q2 | `user:` prefix 구현 방식 논문 일치 확인 | 확인용, 실행 가능 | 위 `§3.1 수정 1` 방식으로 진행 |
| Q3 | JSON-str 활성화 방법 | 논문 구성과 차이 발생 | off 상태로 진행 + 차이 명시 |
| Q4 | `exclude_abstention` 논문 적용값 | 해석 정밀도 | True 로 진행 |

**Q1 상세 질문 (08 문서 Q1 갱신 필요)**:
- Edwin prompt 전문은 수신 완료 — Q1의 "prompt 파일 공유 요청" 부분은 **해결됨**
- 남은 Q1: `mmai.lme_answer_prompt` 속성을 실제 실행 시 **어떤 경로(YAML key? CLI? 코드 내 세팅?)** 로 주입하는지 확인 필요

---

## §6 신뢰성 검토 체크리스트

본 문서 사실 정합성 내부 검증 결과:

| 검증 항목 | 결과 | 근거 |
|---|---|---|
| Edwin_prompt 라인 범위 | ✓ L4-12 SIMPLE, L15-87 COT, L90-111 EDWIN1, L114-136 EDWIN2, L139-157 EDWIN3 | 직접 확인 |
| `qa_eval()` L164-241 정의 + L184-201 분기 로직 | ✓ `mmai.lme_answer_prompt` → `.upper()` → 5종 분기 | 직접 확인 |
| 기본값 COT fallback | ✓ L186-189: answer_prompt 없으면 'COT' | 직접 확인 |
| `mmai` 객체 정의 위치 | ✗ 파일 내 미발견 (외부 주입) → MemVerge 문의 필요 | Edwin_prompt L171-172 주석 "TOM1" |
| `longmemeval_test.py:214` user_q 삽입 위치 | ✓ [F10-user_q] | 06 §8.3 |
| `restapiv2_locomo_search.py:257-264` cat5 skip | ✓ [F7-LoCoMo] | 06 §8.3 |
| `hotpotQA_test.py:195-202` 500 slice | ✓ [F7-HotpotQA] | 06 §8.3 |
| `hotpotQA_test.py` 의 "hard" 필터 적용 위치 | ✗ 코드 조사 결과에 명시 없음 — 기존 로딩 파이프라인 그대로 사용 | 추정 → §3.4 주의 반영 |
| chunk flag YAML key | ✓ `long_term_memory.message_sentence_chunking` | [F10-chunk], 06 §8.3 |
| k 설정 YAML key | ✗ 미확인 → §3.2 수정 2 [추정] 태그 반영 | MemVerge Q1(필수 2) 대기 |
| Provider 파라미터 (seed/temp 전달 불가) | ✓ [F8] | 06 §8.3 |
| #4/#12 prompt = EDWIN3 | ✓ 06 §5.1 명시 | 06 문서 |
| #3 prompt = EDWIN1 | ✓ 06 §5.5 명시 | 06 문서 |
| #5, #2 prompt 지정 없음 → 기본값 COT | ✓ 06 §5.2, §5.3 미지정 + Edwin_prompt L188-189 | 추론 일관 |
| HotpotQA 고정 랜덤 500 (S1/S2 폐기) | ✓ 직전 턴 사용자 결정 반영 | 대화 기록 |
| User_q 논문 사용 경로 (legacy vs retrieval_agent) | ✗ 논문 명시 없음 → §3.2 주의에 반영 | 06 §8.2 |
| 06 §8.1 "MemVerge 필수 1 Edwin prompt" 해결 상태 | ⚠ 부분 — prompt 전문은 수신, 주입 경로는 미수신 | 본 문서 §5 |
| 담당자 역할 (1라운드 A/B/C, 2라운드 #6/#3) | ✓ 07 §4 다이어그램 일치 | 07 §4 |

**발견된 기존 문서 갱신 필요 항목** (본 가이드와 별개로 후속 작업):
1. `08_MemVerge_Info_Request.md` Q1 — "prompt 전문 공유" → "`mmai.lme_answer_prompt` 주입 경로" 로 변경
2. `06_Reproduction_Evaluation_Design.md` §5.3 — S1/S2 병행 설계 → 고정 랜덤 500 1세트로 단일화
3. `07_Reproduction_Summary.md` §2 표 — #2 독립변수 "모드 × 선정{S1,S2}" → "모드만"

---

## §7 산출물 요구사항

각 담당자 제출물:

1. **실험 config YAML** — 모델, provider, k, prompt 값, chunk 설정, DB snapshot ID
2. **소스 패치** — `.patch` 파일 (`user_q_on.patch` 등)
3. **Raw 결과 log** — 문항별 판정·token·latency
4. **집계 결과표** — 논문 Table 대응 + 반복별 수치 + mean±std + 결합 σ 2배 기준선
5. **재현 판정 리포트** (1~2 페이지) — 성공/부분/실패 판정 + 근거 + 관찰 차이

---

## 변경 이력

- **v1 (2026-04-24)**: 초기 작성. 06/07/08 문서 + Edwin_prompt 파일 전수 검증 후 agent-ready 수준으로 통합.

---

## 출처

- `/mnt/project/06_Reproduction_Evaluation_Design.md` v5 §3·§4·§5·§8
- `/mnt/project/07_Reproduction_Summary.md` v5 §2
- `/mnt/project/08_MemVerge_Info_Request.md` v3 Q1-Q4
- `/mnt/project/Edwin_prompt` L4-241
- `/mnt/project/02_Phase1_ProblemDefinition.md` v2 §4.5
- 대화 기록: HotpotQA 고정 랜덤 500 결정, Edwin prompt 주입 경로 질문 재구성
