# 사용자 결정 누적 기록

작성 시작: 2026-04-26
용도: Plan 단계 + 구현 단계에서 사용자가 내린 결정을 timestamp 와 함께 보존

---

## 2026-04-26 — Phase 1 결정 (도구 MVP 설계)

### D-001: retrieve / generate 분리 깊이

**결정**: **5단계 분리** (ingest / retrieve / generate / judge / analyze)

근거 / 의미:
- retrieve 단계가 chunks 와 perf_metrics 를 `results/{run}/retrieve.jsonl` 에 저장
- generate 단계가 retrieve.jsonl 을 읽어 `answer_model.generate_response()` 만 호출
- generate 만 단독 재실행 가능 → token 절약 (예: prompt 만 바꿔 다시 답)
- EDWIN prompt 주입을 generate 단계에서 자연스럽게 처리할 hook 자리 마련
- `process_question()` (`evaluation/utils/agent_utils.py:57-129`) 은 read-only 유지

대안 (기각): 4단계 통합 (`process_question()` 한 번에 호출). 더 얇지만 EDWIN 주입과 단계 재사용이 깔끔하지 않음.

### D-002: `configuration.yml` 처리 방식

**결정**: **하이브리드** — base.yaml 이 두 모드 토글

모드 A: profile 조합 생성
- `configs/profiles/models/{name}.yaml` (embedder / reranker / llm_model ID)
- `configs/profiles/dbs/{name}.yaml` (vector_graph_store host / port / 인증)
- `generate_config.py` 가 두 profile 을 조합해 `configs/generated/{run_name}_configuration.yml` 생성
- 향후 모델 / DB 조합 swap 평가에 유리

모드 B: 기존 파일 사용
- `--use-existing-config /path/to/configuration.yml` 로 사용자가 이미 가진 파일 그대로 참조
- 가장 얇은 경로

근거: 사용자 답변 — "향후 모델 변경하면서 평가하는 테스트를 고려해서 base.yaml 생성하고 미리 저장 된 추가 설정 사용해서 평가시 만들거나 내가 넣은거 사용하거나 선택하게."

### D-003: EDWIN prompt 주입 — hook 만 만들고 실제 기능 제외

**결정**: generate 단계에 prompt 파일 경로 인자 자리만 두고, **현 단계에서는 EDWIN1/EDWIN3 텍스트가 없으므로 실제 로딩 / 적용 로직은 비워둔다**. fallback 으로 기본 ANSWER_PROMPT 사용.

근거: 사용자 plan 직접 편집 — "아직 edwin 정보가 없기 때문에 향후 추가 가능한 형태로만 만들고, 실제 기능은 제외".

향후 EDWIN 텍스트 확보 시: `prompts/EDWIN1.txt`, `prompts/EDWIN3.txt` 에 저장하고 generate 단계 prompt-file 인자로 경로 전달하면 자동 적용.

### D-004: 신규 파일 위치

**결정**: repo root 아래 `configs/`, `scripts/`, `prompts/`, `results/`, `docs/USAGE.md`. RESEARCH.md / DECISIONS.md 는 repo root.

근거: `evaluation/retrieval_agent/` 는 read-only 원칙. 새 디렉터리를 evaluation 안에 두면 read-only 경계가 흐려진다. results/ 는 `.gitignore` 추가 필요.

---

### D-005: retrieve / generate 단계 산출 — 한 loop 분리 저장

**결정**: D-001 의 5단계 분리는 **사용자 관점 구조**로 유지. 내부 구현은 retrieve 단계가 한 loop 안에서 chunks(`retrieve.jsonl`) + answer(`generate.jsonl`) 두 파일을 동시에 산출. generate.py 는 upstream 산출물 검증·통과 모듈로 시작.

**근거**:
- D-003 으로 EDWIN prompt 주입 기능을 비웠기 때문에, generate 단독 재실행의 주요 motivation (다른 prompt 로 재시도) 이 사라짐
- 기존 `process_question()` (`evaluation/utils/agent_utils.py:57-129`) 결과에 `conversation_memories` (retrieve) 와 `model_answer` (generate) 가 이미 분리 저장되어 있어, 한 loop 에서 두 jsonl 분리 저장이 자연스럽다
- 향후 EDWIN 텍스트 확보 시 generate.py 에 단독 실행 로직 추가 가능 (구조 변경 불필요)

**영향**: ingest / judge / analyze 는 단독 재실행 가능. search (retrieve + generate 통합) 도 단독 가능. generate.py 단독 재실행만 future work.

### D-006: benchmark 별 호출 방식

**결정**:
- LongMemEval / HotpotQA: 모듈 함수 직접 import 호출 (`longmemeval_test.longmemeval_ingest` 등)
- LoCoMo: subprocess 로 기존 CLI script 호출 (`locomo_ingest.py`, `locomo_search.py`)

**근거**: LoCoMo 는 multi-session conversation 구조가 복잡하고 (`locomo_search.py:run_locomo` 87-160+ 라인) `build_parser().parse_args()` 를 함수 내부에서 호출하므로, wrap 시 sys.argv 조작 필요 → subprocess 가 가장 안전하고 얇음. LongMemEval / HotpotQA 는 모듈 함수가 깔끔히 분리되어 있어 직접 import 가능.

---

## 향후 결정 기록 형식

각 결정은 `D-{NNN}` ID 부여. 결정 변경 시 새 ID 로 추가하고 이전 ID 에 `(superseded by D-{새 ID})` 표기.
