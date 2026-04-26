# MSR Eval Tool TODO after PR #7

작성일: 2026-04-26
대상: PR #7 (`claude/memmachine-eval-tool-GIrVz`, head `b6d83ad` 시점) 머지 후 남은 코드 수정 항목.
원칙: PR #7 자체는 `evaluation/retrieval_agent/*` 와 `evaluation/utils/*` 를 read-only 로 두는 MVP wrapper 다. 본 문서의 항목들은 그 read-only 경계 또는 upstream 파라미터 표면을 넓혀야 하므로 **별도 PR** 에서 처리한다.

각 항목은 현상 → 위험 → 개선 후보 → 우선순위 형식.

---

## 1. HotpotQA session isolation

**현상**
- `evaluation/retrieval_agent/hotpotQA_test.py:76, 98, 137, 201, 204` 가 `session_id="hotpotqa_group"` 와 `session_key="hotpotqa_group"` 를 하드코드.
- PR #7 wrapper 의 `session_id_for(run_cfg) = "eval_tool_{benchmark}_{run_name}"` 은 LongMemEval 에만 적용된다 (`scripts/stages/ingest.py:_ingest_longmemeval` / `scripts/stages/retrieve.py:_run_hotpot_cell` 가 직접 init 시 `session_id="hotpotqa_group"` 사용).

**위험**
- 같은 DB 인스턴스에서 p2 를 여러 `run_name` 으로 반복 실행하면 episode 가 단일 session 에 계속 누적되어 이전 run 의 데이터와 새 run 의 데이터가 섞인다.
- 측정 결과의 사이클 간 비교 가능성을 잃는다.

**개선 후보**
- A. p2 ingest 직전에 HotpotQA delete 경로 (`evaluation/retrieval_agent/hotpotQA_test.py --run-type delete --config-path <configuration.yml> --test-target memmachine` — argparse 에서 `--config-path` 와 `--test-target` 이 `required=True`, `hotpotQA_test.py:247-256` — 또는 모듈 함수 `hotpotqa_delete(config_path)` — `hotpotQA_test.py:195`) 를 호출하는 clean option 을 wrapper 에 추가
- B. `hotpotqa_ingest()` / `hotpotqa_search()` 의 `session_id` 를 인자로 받도록 upstream 시그니처 확장 (read-only 경계 확장)
- C. 운영 가이드에 "p2 반복 시 별도 DB 사용 권장" 만 명시 (현 상태)

**우선순위**: High

---

## 2. LoCoMo session isolation

**현상**
- `evaluation/retrieval_agent/locomo_ingest.py:70` 와 `locomo_search.py:141` 가 `group_id = f"group_{idx}"` 형태로 session_id 를 결정.
- run_name 정보가 LoCoMo subprocess 경로에 흐르지 않는다.

**위험**
- 같은 DB 인스턴스에서 p5 를 여러 번 돌리면 동일 `group_idx` session 에 episode 가 중복 적재되거나 이전 run 결과와 섞일 수 있다.

**개선 후보**
- A. p5 ingest 전 `locomo_delete.py` clean option 자동 호출
- B. `locomo_ingest.py` / `locomo_search.py` 에 session prefix 인자 추가 (예: `--session-prefix`) 로 wrapper 의 run_name 을 흘려 `eval_tool_locomo_{run_name}_group_{idx}` 형태로
- C. 운영 가이드만으로 격리 (별도 DB / 수동 delete)

**우선순위**: High

---

## 3. LoCoMo 처리 범위 제어

**현상**
- `locomo_search.py:115-117` 에 `start_index = 0`, `end_index = 20` 이 하드코드되어 있다 → 최대 21 개 conversation group 만 처리.
- PR #7 wrapper 는 이 범위를 외부에서 제어하지 않는다.
- 결과적으로 `docs/msr/MemMachine_재현평가_설계_0425.md` §2 #5 의 "cat5 제외 잔여 1,094 문항" 은 **PR #7 의 실제 실행에서는 보장되지 않는다**.

**위험**
- 문서 표현과 실제 실행 범위가 어긋나 결과 해석 오류.
- 사용자가 paper 와 다른 데이터셋 부분집합으로 평가하고 있다는 사실을 인지하지 못할 수 있음.

**개선 후보**
- `locomo_search.py` (그리고 필요 시 `locomo_ingest.py`) 에 `--start-index` / `--end-index` / `--length` 옵션 추가
- `configs/problems/p5.yaml` 에 명시적 `benchmark.start_index` / `benchmark.end_index` 필드 추가
- `_run_locomo_cell()` 가 위 값들을 subprocess 인자로 전달

**우선순위**: Medium

---

## 4. LoCoMo `search_limit` override 적용

**현상**
- `locomo_search.py:197-209` 의 `process_question()` 호출이 7번째 positional argument 로 `20` 을 하드코드 (`search_limit=20` 고정).
- `configs/problems/p5.yaml` 의 `fixed.search_limit: 20` 또는 sweep 값을 사용자가 변경해도 LoCoMo subprocess 경로에는 반영되지 않는다.

**위험**
- 사용자가 p5 의 k 를 바꾸려 해도 무시된다 — 침묵 무효.

**개선 후보**
- `locomo_search.py` 에 `--search-limit` argparse 옵션 추가, 그 값을 `process_question(..., search_limit=args.search_limit, ...)` 로 전달
- `_run_locomo_cell()` 가 `params["search_limit"]` 를 subprocess 인자로 전달

**우선순위**: Medium

---

## 5. chunk on/off 비교 자동화

**현상**
- `episodic_memory.long_term_memory.message_sentence_chunking` 은 ingest 시 Episode 저장 구조에 영향을 주므로, 단일 run 안에서 `sweep.message_sentence_chunking: [false, true]` 같은 형태로 비교하면 ingest 와 retrieve 의 chunking 정의가 어긋난다.
- 현재 PR #7 의 권장 운영은 chunk 값별 `run_name` + 별도 ingest 분리 (수동).

**위험**
- 사용자가 "chunk 도 sweep 에 넣을 수 있다" 라고 오해하면 의미 없는 결과를 얻는다.

**개선 후보**
- chunk 비교 전용 multi-run generator 추가: `scripts/generate_config.py` 에 `--chunk-list off,on` 같은 인자 → 자동으로 두 개의 `run_name` 분리, 각각 ingest 부터 실행하는 helper 또는 shell wrapper
- 또는 `scripts/run_pipeline.py` 가 sweep 의 `message_sentence_chunking` 키를 보면 명시적으로 `NotImplementedError` (현재는 silent 위험)

**우선순위**: Medium

---

## 6. 우선순위 정렬 (참고)

| 항목 | 우선순위 | 위험 정도 | 코드 변경 범위 |
|---|:---:|:---:|:---:|
| 1. HotpotQA session isolation | High | 결과 섞임 | upstream 시그니처 또는 delete 호출 |
| 2. LoCoMo session isolation | High | 결과 섞임 | upstream 시그니처 또는 delete 호출 |
| 3. LoCoMo start/end 인덱스 | Medium | 데이터셋 범위 어긋남 | upstream argparse + wrapper 전달 |
| 4. LoCoMo search_limit | Medium | 침묵 무효 | upstream argparse + wrapper 전달 |
| 5. chunk 비교 자동화 | Medium | 사용자 오해 | wrapper 만 (upstream 무관) |

---

## 7. 후속 PR 가이드

- 1, 2 항은 **`evaluation/retrieval_agent/*` 의 함수 시그니처 변경** 또는 **delete script 호출 추가** 가 필요하므로 read-only 경계가 깨진다 — 본 PR (#7) 에서는 적용하지 않는다.
- 3, 4 항도 동일하게 `locomo_search.py` 의 argparse 확장이 필요하다.
- 5 항만이 `scripts/` 안에서 자체 해결 가능 (upstream 무관).

따라서 권장 후속 PR 분할:
- PR-A: 5 항 (chunk 자동화) — wrapper-only
- PR-B: 1, 2 항 (session isolation) — upstream 시그니처 + wrapper 동시
- PR-C: 3, 4 항 (LoCoMo parameterization) — upstream argparse + wrapper 전달

PR-A 가 가장 빠르게 머지 가능, PR-B / PR-C 는 upstream 변경에 대한 검토 필요.
