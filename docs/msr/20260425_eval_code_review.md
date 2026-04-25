확인 끝났습니다. 두 문서를 논문(arXiv:2604.04853v1) 정합성과 실제 코드(`origin/eval`/현재 브랜치)와의 재현 정합성 두 축에서 상세 리뷰합니다.

---

# 종합 리뷰

## 0. 사전 사실 확인 (코드 vs v0.2 ✅ 주장)

| v0.2 ✅ 주장 | 코드 위치 | 정합 |
|---|---|---|
| `prepend_user_prefix` 토글 | `evaluation/retrieval_agent/longmemeval_test.py:62-82, 224-231` | ✓ |
| `locomo_search.py` cat5 skip | `evaluation/retrieval_agent/locomo_search.py:135` | ✓ |
| chunk YAML wiring | `evaluation/utils/agent_utils.py:387,440-455` (kwarg=None → YAML fallback) | ✓ |
| `LongTermMemoryConfPartial.message_sentence_chunking` | `packages/server/src/memmachine_server/common/configuration/episodic_config.py:130-149` | ✓ |
| matrix `chunk × prefix × k` | `run_benchmark_matrix.sh:15-17, 200-227` | ✓ |
| LongMemEval 호출이 YAML 값 사용 | `longmemeval_test.py:217-221` (kwarg 미전달) | ✓ |

→ v0.2가 ✅로 표시한 6개 항목은 모두 코드와 정합합니다.

---

## A. `MemMachine_재현평가_설계_0424.md` 리뷰

### 잘 된 점
- 6개 후보 모두 paper 섹션 refs(§5.6/§8.1/§8.2/§8.4 + Table 3·4·10·11·12·13·14·15)까지 추적 가능하게 인용.
- v2 정정에서 **"Memory vs Agent ≠ before/after"** 라는 본 과제 관점 제약 명시(§0, §2 #2). Agent-only 해결은 본 과제 지향(Agent-free)과 다른 축이라는 구분이 핵심.
- **Table 3(95.5%) vs Table 4·본문(92.31%) 논문 내부 불일치 경고**(§2 #2) — 재현 시 표준값 선정 근거 보존.
- §8.4.1의 "lost in the middle" 메커니즘을 #4 원인 가설 검증 지표 후보로 끌어온 점.
- §5(한계) — eval-LLM·Edwin 버전·provider 업데이트·C1~C4 subset 사용 등 paper §9.7 명시 한계 충실 반영.

### 논문 정합 관점에서 짚어둘 결함

1. **C5/C6 운영 조합의 JSON-str 일탈**(§2 #3)
   - 논문 §8.4.2: C5/C6 모두 **JSON-str=on**.
   - 본 과제 운영표: `json_str=off (방침)`.
   - 주의 칼럼에 "재현 수치가 +1.4%p와 다를 수 있음"은 적었으나, **off로 가는 운영 근거가 본 문서에 없음**. ablation 단계별 기여도 표(§3)에서 JSON-str=+2.0%p가 user_q=+1.4%p보다 크므로, off 상태에서 user_q on/off만 보는 것은 사실상 다른 운용점에서의 효과 측정이 됨.

2. **C12 (#4) 운영 조합도 같은 일탈**(§2 #4)
   - 논문 C12: chunk=on, user_q=on, **JSON-str=on**, Edwin3.
   - 본 과제: chunk=on, user_q=on, **JSON-str=off**, Edwin3.
   - 즉 #4 비단조성 재현은 "C12 재현"이 아닌 "JSON-str off 조건에서 k sweep". 결과를 paper §8.4.1과 직접 대조하기 어려움. 이 사실을 §5(한계)로 끌어올려 첫 단락에 두는 것이 맞음.

3. **EDWIN prompt 주입 미해결이 #3·#4·#12·#5 전부의 근간을 흔듦**(§2 모든 후보)
   - 본 문서가 명시한 "Edwin1/Edwin3 주입 경로 MemVerge Q1 대기"가 풀리지 않으면, 답변 LLM의 prompt가 paper와 다른 단일 하드코드(`longmemeval_test.py:22 ANSWER_PROMPT`, Agent Lightning 인용 prompt)로 동작.
   - 본 문서의 판정 기준(σ×2)은 prompt가 통제됐을 때만 의미가 있음 → **이 항목은 #3·#4·#12·#5의 사전조건이지 옵션이 아님**.

4. **HotpotQA "hard 500" 선정 방식**(§2 #2)
   - 본 문서: "재조사 필요"로 보류.
   - 코드 실제: `hotpotQA_test.py:215` `dataset.select(range(length))` — split 첫 500. 무작위 sampling/seed 없음.
   - 논문이 "hard set" subset을 명시한 셈이라면 split 자체가 hard라면 OK이나, **이 가정 검증 없이 v0.2가 "제외 / length=500 정책"으로 결정**. 본 문서가 v3.x 갱신 시 운영 결정에 맞춰 표현 통일 필요(현재 두 문서 간 톤 차이).

5. **#5 LoCoMo Multi-hop(282) 단위 운영 절차 누락**
   - §2 #2 표에는 "LoCoMo Multi-hop 0.8759/0.8830/0.8972" paper 수치 인용은 있으나, **본 과제 재현 운영표 §5 #2는 HotpotQA 500만 다룸**. LoCoMo cat2(multi-hop) 추출 절차가 본 문서에 없음 — 코드에는 cat5 skip만 존재(`locomo_search.py:135`)이므로 cat2-only slicing 추가 필요.
   - 만약 본 과제가 LoCoMo multi-hop 재현은 paper 인용으로만 쓰고 자체 측정은 HotpotQA로만 한다는 결정이라면, 이 결정을 §2 #2에 명시해야 함.

6. **#5 운영표의 코드 수정 인용 정합 문제**
   - "`restapiv2_locomo_search.py:257-264` 의 cat5 skip 로직을 `evaluation/retrieval_agent/locomo_search.py` 에 포팅" — `restapiv2_locomo_search.py`는 현재 점검 범위에 없음(이미 정리됨), 포팅 결과는 `locomo_search.py:135`에 반영 완료. 이 인용은 v3.x 갱신 시 "포팅 완료" 상태 표기로 변경 필요.

7. **#2 판정 기준의 통계적 가능성**
   - "Agent > Memory + 결합σ 2배 초과 + Agent token > Memory token"
   - paper 차이폭: Acc +2.0%p, Recall +1.3%p. N=500에서 σ가 0.7%p 수준이면 결합σ×2 ≈ 2%p로 경계선. 본 문서가 "파일럿 표준편차 기반 결정"으로 미정 → 파일럿 wrapper(§4)가 v0.2에서 ❌인 점과 결합되면 사실상 판정 불능. **§4 wrapper 미구현이 §2 판정 기준의 작동 전제와 충돌**.

8. **§3 Ablation 기여도 표의 누계 적용 위험**
   - 표는 "C{n} vs C{n+1}" 단계별 기여도. 본 과제가 **운영점이 paper의 어느 C{n}에 매핑되는지 표가 없음**. 단계 비교 시 어느 baseline 기준의 +x%p인지 혼동 가능 → §3에 "본 과제 운영점 ≈ C? (JSON-str off로 인한 일탈)" 매핑 컬럼 추가 권고.

---

## B. `20260425_modified_list_v0.2.md` 리뷰

### 잘 된 점
- v0.0 → v0.1 → v0.2 변천 추적 명확. v0.0의 chunk 검증 ("config_value=True, applied_value=False")이 v0.2에서 정확히 그 항목만 ✅로 전환됨 — 실제 PR(`74e73c0`, `ba06f9c`)와 일치.
- ❌ 5개 항목(snapshot/wrapper/판정/MS집계/EDWIN)을 "솔직하게" 미구현 명시. 09 문서와 직접 대응.

### 논문 재현 관점에서 보강해야 할 점

1. **chunk 축의 cross-benchmark side-effect (미언급)**
   - `run_benchmark_matrix.sh:200-227`은 LongMemEval 루프 안에서 YAML chunk를 토글하지만, 루프 종료 후 LoCoMo/HotpotQA 실행 시 chunk 값이 **마지막 순회값(`on`)으로 잔류**.
   - LoCoMo / HotpotQA가 chunk=on 조건에서 측정됨. paper §8.1·§5.6은 LoCoMo/HotpotQA의 chunk 옵션을 따로 명시하지 않거나 default(off)로 측정된 것으로 보임.
   - **권고: 매트릭스 스크립트가 LongMemEval 루프 종료 시 chunk를 명시적 default로 reset, 또는 v0.2에 "LoCoMo/HotpotQA는 chunk=last(on)에서 측정됨"을 알려진 한계로 명시**.

2. **`--skip-ingest` 사용 시 chunk on/off mismatch 위험**
   - chunk=on으로 ingest된 스토리지에 chunk=off로 검색하면 인덱싱과 검색의 chunk 정의가 다름. v0.2 §C "주의사항 명시"가 README에 들어갔다고만 했는데, 본문에 "어떤 케이스에서 무효화되는지"를 한 줄로 인용해 두면 좋음.

3. **EDWIN(❌) 항목의 의미 가중치 부족**
   - v0.2 §E는 "주입 경로/주입 코드 미확인"으로 ❌만 표시. 그러나 이 항목 미해결은 **다른 ✅ 항목 모두의 해석을 흔드는 사전조건**(0424 #3·#4·#12·#5의 prompt 축이 통제 안 됨). 별표/우선순위 표기 권장(예: ❌-blocker).

4. **#3 C5/C6 운영 ✅의 한정성**
   - "prefix on/off 조건으로 실행 가능 ✅" — 코드상은 OK. 그러나 paper의 C5/C6는 prefix만 다른 게 아니라 **다른 모든 변수(Edwin1, JSON-str=on, chunk=off, k=20)가 동일**한 단일 변수 ablation pair. 본 과제 운영점이 그 동치 조건을 갖추지 않으면 "user_q 효과의 재현 (C5/C6 외삽)"이지 "C5/C6 재현"이 아님. v0.2가 그 한정성을 명시하지 않음.

5. **점검 범위 협소**
   - v0.2 §0: `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`, `packages/server/*`. 그러나 `evaluation/utils/`에는 `memmachine_helper_db.py`, `memmachine_helper_restapiv1/2.py`, `atf_helper.py`도 존재. 기존 평가 경로(예: restapiv2_*)가 아직 일부 경로에서 호출될 가능성 점검 누락.

6. **DB snapshot ❌의 우회책 부재**
   - "구현 확인 안 됨"만 적힘. 실제 운영에서는 매 반복 fresh ingest + 결정적 seed 사용 등 우회책이 가능 — v0.3에 "최소 운영 권고: 매 반복 ingest 재실행, embedder 결정성 확인" 한 줄 추가 권장.

7. **반복 wrapper ❌의 회피책 부재**
   - 0424 §4 "파일럿 5회 + N 자동결정"이 미구현. 그러면 0424의 σ×2 판정이 작동 불능 → v0.3에 "임시 운영: 모든 후보 N=3 고정, σ는 후처리 계산" 같은 fallback 명시 권장.

8. **자동 판정/MS 집계 ❌**
   - `generate_scores.py` / `llm_judge.py` 등이 이미 카테고리별 집계를 일부 수행할 가능성. v0.2가 "구현 확인 안 됨"만 적었는데, **무엇을 점검했는지(파일·grep 키워드)** 메타정보가 없어 재점검 비용이 큼. v0.3에서 점검 출처 노트 권장.

---

## C. 두 문서 간 정합성

| 항목 | 0424 | v0.2 | 정합 여부 |
|---|---|---|---|
| EDWIN 주입 | "MemVerge Q1 대기" | ❌ | 합치 ✓ |
| chunk YAML | "YAML 설정 `message_sentence_chunking: true`" (단일 운영점) | sweep `{off,on}` | **불합치** — 0424 갱신 필요 |
| HotpotQA 500 선정 | "재조사 필요" | "제외 / length=500 정책" | **불합치** — 0424 갱신 필요 |
| cat5 skip 포팅 | "포팅 작업 필요" | ✅ 완료 | **불합치** — 0424 표현 갱신 필요 |
| 반복 wrapper / 판정 | §4 σ×2 의존 | ❌ | 의존 깨짐 — 0424 §4 fallback 추가 필요 |

---

## D. 우선순위 권고 (현재 문제 재현 관점)

1. **EDWIN1/EDWIN3 주입 경로 확정** — 미해결 시 0424 §2 #3·#4·#12·#5의 모든 판정이 무의미. 0424·v0.2 모두 이 항목을 별도 blocker 마커로 격상.
2. **JSON-str off 운영 결정의 근거를 0424 §0/§5 한계로 명시** — paper C5/C6/C12 직접 비교 불가 사실을 본문 첫 단락에 두기.
3. **`run_benchmark_matrix.sh` chunk 잔류 버그** — LongMemEval 루프 종료 후 LoCoMo/HotpotQA 진입 전 chunk를 명시적 default로 reset 또는 v0.2에 한계로 기록.
4. **HotpotQA 500 선정 방식**을 0424가 v0.2 운영 결정에 맞춰 갱신("코드 `dataset.select(range(500))` = split 앞 500이며, paper 'hard 500'과 동일성 검증 미완").
5. **반복 N 결정 fallback** — 파일럿 wrapper 미구현 동안 임시 N=3 + 후처리 σ 계산 운영 규약을 두 문서에 합의 형태로 추가.
6. **0424 §5 #5에 cat2(multi-hop) slicing 절차** 추가 — 현 코드는 cat5 skip만 함.
7. **0424 §3 ablation 표에 본 과제 운영점 매핑 컬럼** 추가.
8. v0.2 §0 점검 범위 확장 — `evaluation/utils/memmachine_helper_*.py`, `atf_helper.py`도 호출 그래프 확인.

---

요약: v0.2의 ✅ 6항목은 코드 정합 측면에서 정확합니다. 그러나 ❌ 5항목(특히 EDWIN과 반복 wrapper)이 미해결인 한, 0424가 정의한 σ×2 판정 체계는 작동하지 않으며, JSON-str off 일탈로 인해 paper C5/C6/C12 직접 비교 자체가 성립하지 않습니다. 두 문서의 다음 갱신은 (1) blocker 마킹, (2) JSON-str 일탈 명시, (3) HotpotQA 500/chunk 잔류 등 코드-문서 정합 정정에 집중하는 것이 효과적입니다.