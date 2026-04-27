# MemMachine eval 브랜치 변경사항 임원용 분해 문서 (v6 최종)

## 0. 배경 — 왜 이 fork 가 필요한가

MemMachine 원본 논문(arXiv:2604.04853v1)과 본 fork 의 `docs/msr` 설계 문서에서 평가 대상으로 정리한 6 개 후보(#2 다중-hop 검색 / #3 사용자-편향 검색 / #4 검색 깊이 비단조성 / #5 LoCoMo / #6 Multi-session 재분해 / #12 비용-정확도 Pareto)를 사내 평가 환경에서 변수 효과를 외삽 검증할 수 있어야 하는데, 원본 코드는 이 6 개 실험을 위한 토글·sweep 경로가 부족했습니다. 본 fork 는 (1) 기존 평가 코드를 최소만 수정하고, (2) 그 위에 read-only wrapper 를 얹고, (3) 설계·결정·검증 상태를 문서로 남기는 세 갈래로 구성됩니다.

> 본 fork 의 결과는 **paper exact reproduction 이 아닙니다**. JSON-str=off 운영 방침과 EDWIN prompt 미적용 때문에 **operational reproduction / 변수 효과 외삽 (extrapolation)** 으로 해석되어야 합니다.

| 영역 | 파일 | 추가 | 삭제 |
| --- | ---: | ---: | ---: |
| 기존 평가 코드 수정 (`evaluation/retrieval_agent/{longmemeval_test.py, run_test.sh, README.md, test_run_test.py}` + `evaluation/utils/agent_utils.py`) | 5 | +237 | -7 |
| 신규 매트릭스 스크립트 (`evaluation/retrieval_agent/run_benchmark_matrix.sh`) | 1 | +252 | 0 |
| 서버 설정/동작 코어 변경 (`episodic_config.py` + `short_term_memory.py` + `service_locator.py`) | 3 | +20 | -1 |
| 서버 설정 회귀 테스트 보강 (`packages/server/server_tests/...` 기존 파일 2 종) | 2 | +86 | 0 |
| 신규 wrapper (`scripts/` + `configs/` + `prompts/`) | 23 | +1,933 | 0 |
| 신규 문서 (`docs/msr/*` + `docs/USAGE.md` + `README_MSR.md` + `RESEARCH.md` + `DECISIONS.md`) | 13 | +2,299 | 0 |
| 기타 (`.gitignore` / `pyproject.toml` / `sample_configs/*.sample` / `docs/open_source/configuration.mdx`) | 6 | +26 | 0 |
| **합계** | **53** | **+4,853** | **-8** |

검증 메모:
- fork 시작점: upstream `6b1988b`
- 이후 커밋 수: 46 (`git rev-list --count 6b1988b..HEAD`)
- 전체 numstat: 53 files / +4853 / -8 (`git diff --numstat 6b1988b..HEAD`)

---

## A. 평가 코드 직접 수정 (4건)

### A1. LongMemEval 질문 앞 `User:` prefix 토글

- 위치: `evaluation/retrieval_agent/longmemeval_test.py`
- 핵심: `_load_longmemeval_question_prefix_enabled()` 추가, `longmemeval_search()`에서 조건부 접두어 적용
- 설정:

```yaml
evaluation:
  longmemeval:
    prepend_user_prefix: true
```

- 목적: 논문 §8.4.2 C5/C6 축(user_q) 효과를 사내 조건에서 토글 가능하게 만들기 위함
- 구현 특성: 키 누락/파싱 실패/타입 mismatch 시 `False` 안전 fallback

### A2. LongMemEval 검색 깊이 `k` (`--search-limit`) 외부 파라미터화

- 위치: `evaluation/retrieval_agent/longmemeval_test.py`, `evaluation/retrieval_agent/run_test.sh`
- 핵심: `DEFAULT_SEARCH_LIMIT`, CLI `--search-limit`, `positive_int` 검증
- 가드: LongMemEval search 이외 실행에 `--search-limit` 전달 시 즉시 에러
- 목적: `{10,20,30,50,100}` sweep 자동화로 #4 비단조성 효과 외삽 검증

### A3. legacy `run_test.sh` ingest 상태 마커 추가

- 위치: `evaluation/retrieval_agent/run_test.sh`
- 핵심: `[INGEST_START] / [INGEST_OK] / [INGEST_FAIL]` 표준 로그 + `result/ingest_status/*.json` 기록
- 목적: 매트릭스 대량 실행 시 ingest 실패 셀을 사후 즉시 식별
- 주의: 이 마커는 legacy 경로 전용이며, wrapper(`scripts/stages/ingest.py`)의 idempotent skip 과 별개

### A4. 매트릭스 실행기 `run_benchmark_matrix.sh` 추가

- 위치: `evaluation/retrieval_agent/run_benchmark_matrix.sh`
- 핵심:
  - `chunk × prefix × k = 20` (LongMemEval) + LoCoMo/HotpotQA까지 일괄 실행
  - `--dry-run`, `--skip-ingest` 지원
  - `configuration.yml` 토글 후 `trap restore_config EXIT` 복원
- 알려진 한계:
  - LoCoMo/HotpotQA 진입 시 chunk 값 잔류 이슈(문서화됨)
  - `kill -9` 같은 강제 종료는 trap 복원 미보장

---

## B. 서버 설정/동작 확장 (3건)

### B1. partial config round-trip에서 chunk 필드 유실 회귀 수정

- 위치: `packages/server/src/memmachine_server/common/configuration/episodic_config.py`
- 핵심: `LongTermMemoryConfPartial`에 `message_sentence_chunking: bool | None` 추가
- 의미: chunk 축이 침묵 무효화되는 회귀 해소

### B2. 평가 경로에서 chunk 우선순위 정립 (kwarg > YAML > default)

- 위치: `evaluation/utils/agent_utils.py:init_memmachine_params`
- 핵심: `message_sentence_chunking` default를 `None`으로 변경하고, 미전달 시 YAML fallback
- 의미: 기존 호출 호환 유지 + YAML 단일 진실 원천 보장

### B3. STM eviction 시 LLM 요약 생성 토글 추가

- 위치:
  - schema: `episodic_config.py` (`summarization_enabled`)
  - 적용: `short_term_memory.py` (`_do_evict()` 분기)
  - 전달: `service_locator.py`
- 핵심:

```yaml
episodic_memory:
  short_term_memory:
    summarization_enabled: false
```

- 목적: 반복 평가 시 요약 LLM 비용/지연 절감
- 운영 주의: 기본값이 false 이므로 운영 환경 의도값 명시 필요

---

## C. PR #7 read-only wrapper 확장 (10건)

### C1. wrapper 전용 디렉터리 신설

`configs/`, `scripts/`, `prompts/`, `results/`, `docs/USAGE.md`, `DECISIONS.md`, `RESEARCH.md` 등으로 기존 평가 코드를 감싸는 독립 레이어 구축.

### C2. 5-stage 파이프라인 분리

ingest → retrieve → generate → judge → analyze 단계로 분리.

| stage | 파일 | 의미 |
| --- | --- | --- |
| ingest | `results/{run}/ingest.jsonl` | 마지막 row `status=ok`면 자동 skip |
| retrieve | `results/{run}/retrieve.jsonl` | 질문별 retrieval 산출 |
| generate | `results/{run}/generate.jsonl` | 질문별 answer 산출 |
| judge | `results/{run}/judge.jsonl` | llm_score 포함 |
| analyze | `results/{run}/analyze.json` | 집계/분해/Pareto |

### C3. 문제별 기본 YAML (`p2,p3,p4,p5,p6,p12`)

- `--problem N` 선택으로 sweep/fixed 자동 구성
- 확인된 차이: legacy matrix는 `longmemeval_s_cleaned`, wrapper p3/p4는 `longmemeval_s`

### C4. 모델/DB profile 분리

- `configs/profiles/models/*.yaml`, `configs/profiles/dbs/*.yaml`
- 모델 비교 실험 시 설정 재사용성 개선

### C5. 사용자 `configuration.yml` 원본 보호

- working copy(`configs/generated/{run}_configuration.yml`)만 수정
- mode=existing도 동일 원칙

### C6. #6 Multi-session 재분해 자동 집계

- `scripts/stages/analyze.py:_add_multisession_decomposition`
- 산출: `ms_accuracy`, `others_mean_accuracy`, `ms_vs_others_gap`

### C7. #12 Pareto 자동 집계

- `scripts/stages/analyze.py:_add_pareto`
- 정확도/토큰/시간 계열을 `search_limit` 오름차순으로 정리

### C8. EDWIN hook only (실제 swap 미구현)

- 위치: `prompts/EDWIN{1,3}.txt`, `scripts/stages/generate.py:_check_prompt_hook`
- 현재 동작: 파일 유무/비어있음 확인만 수행, 실제 generate-time prompt 적용 없음
- 의미: paper C5/C6/C12 exact 비교 불가, 외삽 해석 필요

### C9. session_id 생성 vs 실제 적용 범위 차이

- 생성 자체는 모든 benchmark에서 수행 (`session_id_for`)
- 실제 격리 적용:
  - ✅ LongMemEval: wrapper session_id 전달
  - ⚠️ HotpotQA: upstream `hotpotqa_group` 고정
  - ⚠️ LoCoMo: upstream `group_{idx}` 고정

### C10. silent 무효 차단 가드 현황

| 가드 항목 | 현재 상태 | 위치 |
| --- | --- | --- |
| `n_runs > 1` 차단 | ✅ 적용 | `scripts/run_pipeline.py` |
| 비-LongMemEval `--search-limit` 차단 | ✅ 적용 | `evaluation/retrieval_agent/run_test.sh` |
| `sweep.message_sentence_chunking` 차단 | ❌ 미적용(후속 권장) | `scripts/stages/retrieve.py` |
| LoCoMo `search_limit` 무시 차단 | ❌ 미적용(후속 권장) | `scripts/stages/retrieve.py` + upstream locomo argparse |

---

## D. 문서화 산출물 (6건)

### D1. 6개 후보 정량 설계서

- `docs/msr/MemMachine_재현평가_설계_0424.md` → `..._0425.md`
- 운영점 일탈(JSON-str off / EDWIN 미구현)과 해석 경계 명시

### D2. 구현 상태 진척표 버전 관리

- `docs/msr/20260425_modified_list_v0.0.md`
- `docs/msr/20260425_modified_list_v0.1.md`
- `docs/msr/20260425_modified_list_v0.2.md`

### D3. 설계·진척·코드 3중 정합 리뷰

- `docs/msr/20260425_eval_code_review.md`
- paper 정합/코드 정합 기준으로 미해결 리스크 정리

### D4. PR #7 후속 TODO 5건

- `docs/msr/msr_eval_tool_todo_pr7.md`
- session 격리, LoCoMo 파라미터화, chunk sweep guard 등 우선순위화

### D5. 결정 로그

- `DECISIONS.md` (D-001~D-006)
- 설계 선택과 기각안의 근거 보존

### D6. 사용자 가이드

- `README_MSR.md`: legacy 변경 + STM summary 토글 요약
- `docs/USAGE.md`: wrapper 실행/FAQ

---

## E. 임원 관점 핵심 3가지

1. **정확한 표현은 operational reproduction / extrapolation**
   - JSON-str=off + EDWIN 미적용으로 paper exact 재현은 아님
2. **실험 자동화 기반은 크게 강화됨**
   - chunk/prefix/k 토글, 5-stage 재실행, Pareto/MS 분해, config 보호 확보
3. **다음 PR 우선순위가 명확함**
   - 최우선: HotpotQA/LoCoMo session isolation
   - 동급: chunk sweep guard + LoCoMo search_limit 인자화 + matrix chunk 잔류 버그

본 branch 의 실질적 성과는 “논문 수치 복제 도구”보다 **사내 환경에서 변수 효과를 반복 가능하게 검증하는 평가 자동화 기반** 구축에 있습니다.
