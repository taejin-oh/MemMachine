# 20260430 Modified List v0.3

- 작성일: 2026-04-30
- 기준 문서: `docs/msr/09_Reproduction_Code_Changes.md`
- 점검 범위: `scripts/*`, `configs/*`, `prompts/*`, `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`, `packages/server/*`
- 기준 브랜치: `eval_claude` (HEAD `e0b9234`)
- 목적: PR #7 (foundation `09ff952`) 이후 `claude/memmachine-eval-tool-GIrVz` 계열 후속 commit (`3fcce7e` … `dc3a72d`) 까지 반영한 **eval_claude 최신 상태(v0.3)**

> ℹ️ **관계 정리**
>
> - v0.0 / v0.1 / v0.2 (`docs/msr/20260425_modified_list_v0.{0,1,2}.md`) 는 historical 상태입니다. v0.2 의 §1 표는 기존 `evaluation/retrieval_agent` 경로 기준, §4 표는 PR #7 머지 직후 기준입니다.
> - 본 v0.3 은 PR #7 이후 추가 commit 까지 반영한 시점의 단일 표 입니다. 이전 표들과 중복되는 항목은 같은 기준으로 다시 작성했습니다.

---

## 0) v0.2 § 4 (PR #7 직후) 대비 변경 요약

- ✅ `generate_config.py` 가 `--problem` choices `[2,3,4,5,6,12]` 와 `--length` 를 노출 (`3fcce7e`)
- ✅ rerankers 가 model profile `rerankers:` list + `primary_reranker` 로 일급화 (`d38f5e1`)
- ✅ judge LLM 이 `--judge-model` / `judge.llm_model_id` 로 swap 가능 (`d38f5e1`)
- ✅ STM `summarization_enabled` 토글 노출, **config-only** 로 sweep 차단 (`034a53d` + `ccc289e`)
- ✅ 서버측 `summarization_enabled` / `semantic_memory.enabled` default = false 로 정렬 (`b6c838d` → `00b4ad3` / #25)
- ✅ p6 / p12 analyze-only run 의 ingest 사고 차단 (`8bda959`)
- ✅ LongMemEval split 을 `longmemeval_s_cleaned` 로 통일 (`9c54bab`)
- ✅ LongMemEval offline `benchmark.data_path` 지원 (`dc3a72d`)
- ✅ `SWEEP_INGEST_AFFECTING_KEYS` (chunk) + `SWEEP_CONFIG_ONLY_KEYS` (summarization) sweep 차단으로 silent A/A 매트릭스 방지

---

## 1) 구현 상태 요약 (eval_claude 최신)

상태 표기:
- ✅ 구현 완료
- ❌ 미구현
- 제외: 이번 기준에서 미적용 정책

| 항목 (09 기준) | 상태 | 처리 위치 / 비고 |
|---|:---:|---|
| #4/#12 LongMemEval `User:` prefix 삽입 | ✅ | `configs/problems/p3.yaml` sweep / `p4.yaml` fixed `prepend_user_prefix`, `generate_config.py` 가 working `configuration.yml` 에 반영 |
| #4/#12 k sweep (10,20,30,50,100) | ✅ | `configs/problems/p4.yaml` `sweep.search_limit` |
| #3 C5/C6 운용 | ✅ | `configs/problems/p3.yaml` `sweep.prepend_user_prefix: [false, true]` |
| #5 LoCoMo cat5 skip 포팅 | ✅ | `locomo_search.py` 그대로 호출 |
| #5 LoCoMo 모드 sweep (Memory/Agent) | ✅ | `configs/problems/p5.yaml` `sweep.test_target` |
| #2 HotpotQA 모드 sweep (Memory/Agent) | ✅ | `configs/problems/p2.yaml` `sweep.test_target` |
| #2 HotpotQA `length=500` 정책 + split | ✅ | `p2.yaml` 명시 |
| #4/#12 chunk on/off YAML 제어 | ✅ (sweep 차단 강화) | `p4.yaml` `fixed.message_sentence_chunking`. `scripts/stages/retrieve.py` 의 `SWEEP_INGEST_AFFECTING_KEYS` 가 sweep 키로 들어오면 SystemExit (ingest 결과 Episode shape 가 고정되어 retrieve-stage cell toggle 만으로는 진정한 A/B 가 불가능) |
| #4/#12 chunk × prefix × k 조합 | 부분 (chunk 별도 run, validator 가 강제) | chunk 비교는 run yaml 분리 + 별도 ingest 필수. prefix × k 는 단일 run sweep 에서 가능 |
| 공통: DB snapshot 동결/복원 | ❌ | 본 도구 범위 밖 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ (`n_runs > 1` 명시 error) | `run_pipeline.py` |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | future work — analyze 출력 raw 값 수기 판정 |
| #6 MS 재분해 전용 집계 | ✅ | `python scripts/run_pipeline.py … --stage analyze --decompose-multisession` |
| #4/#12 EDWIN prompt 주입 | ❌ (hook only) | `prompts/EDWIN{1,3}.txt` placeholder + `scripts/stages/generate.py` hook. 텍스트 미확보 + 실 적용 미구현 |
| #12 token/accuracy Pareto 자동화 | ✅ | `--stage analyze --pareto` 가 cell 별 token / recall / accuracy 산출 |
| 사용자 `configuration.yml` 보호 | ✅ | `mode=existing` 도 working copy 사용 |
| token / per-tool / fact_hits carry | ✅ | `retrieve.jsonl` 보존 + analyze join + by_tool breakdown |
| **추가**: `generate_config.py` problem CLI (p2/p3/p4/p5/p6/p12) + LENGTH | ✅ | `3fcce7e`. `--problem` choices=`[2,3,4,5,6,12]` (`scripts/generate_config.py:50`). base.yaml + `configs/problems/p*.yaml` + profiles + `runs/_example.json` 머지. LoCoMo `--length` (default 10) → `benchmark.length`. `scripts/stages/generate.py` 추가 |
| **추가**: rerankers list 설정 가능 | ✅ | `d38f5e1`. **model profile** 에서 `rerankers:` list + 선택적 `primary_reranker` 설정 (`configs/profiles/models/_example.yaml`). `_validate_and_normalize_rerankers()` 가 schema/legacy 검증 + rrf-hybrid 참조 무결성 체크 후 working `configuration.yml` 의 `resources.rerankers` 와 `retrieval_agent.reranker`(=primary) 로 emit. retrieve-stage sweep wiring 은 없음 |
| **추가**: judge LLM 설정 가능 | ✅ | `d38f5e1`. `--judge-model` CLI 또는 `judge.llm_model_id` (run_cfg) → working `configuration.yml` 의 `retrieval_agent.judge_llm_model` 로 swap (`scripts/stages/judge.py:_swap_judge_llm_model`). model profile 의 optional `judge_llm` 블록은 `_validate_judge_llm()` 으로 검증, 미정의 시 answer `llm_model` 로 fallback. `evaluation/retrieval_agent/llm_judge.py` / `scripts/stages/judge.py` 가 런타임에서 사용 |
| **추가**: STM `summarization_enabled` 토글 | ✅ (config-only) | `034a53d` + `ccc289e`. CLI `--summarization on/off` → `fixed.summarization_enabled`. **sweep 키로는 차단** (`SWEEP_CONFIG_ONLY_KEYS`): eval 경로가 `EpisodicMemory(short_term_memory=None)` (`agent_utils.py:461`) 로 호출되어 LongMemEval 점수에 영향 없음. CLI 사용 시 stderr warning |
| **추가**: 서버측 STM/SemMem default 정렬 | ✅ | `b6c838d` → `00b4ad3` (#25). `ShortTermMemoryConf.summarization_enabled` default → False, `SemanticMemoryConf.enabled` default → False. eval-tool 이 emit 하는 `configuration.yml` 과 서버 default 가 일치 |
| **추가**: p6 / p12 analyze-only 보호 | ✅ | `8bda959`. `--stage` 미지정 시 reuse_run 인지 판단 → 부모 run 산출물 덮어쓰기 / `benchmark.data_path` 누락 실패 차단 |
| **추가**: LongMemEval split 일치화 | ✅ | `9c54bab`. `p3.yaml`/`p4.yaml` split 을 `longmemeval_s_cleaned` 로 통일 (이전: `longmemeval_s` ↔ matrix runner 와 silent 점수 분기). `scripts/test_longmemeval_split_consistency.py` 4 케이스로 회귀 차단 |
| **추가**: LongMemEval offline `data_path` | ✅ | `dc3a72d`. `benchmark.data_path` 가 set 이면 ingest/retrieve 가 HF 호출 우회 → `_common.load_longmemeval_local()` 가 `min(length, len(records))` cap + 4-field normalize. p3/p4 default = `evaluation/data/longmemeval_s_cleaned.json`, generate 시 절대경로로 resolve (cwd 독립). HF 사용 원하면 `data_path` 줄 제거 |
| **추가**: MSR 한국어 docs / 5-min TLDR / Part1·2·3 walkthrough | ✅ | `de396e4`, `dfb01a3`, `7f98258`, `3847d2a`, `9b84554`, `e0b9234`. p4 walkthrough + 4-A/B/C/D meaning-driven 정리 + glossary 추가 |

---

## 2) 잔여 미해결 항목 (변동 없음)

### A. DB snapshot 동결/복원 자동화

09 요구:
- PostgreSQL/Neo4j/SQLite 대상 snapshot 생성/복원
- snapshot ID 기록

현재:
- 본 도구 범위 밖. eval_claude 에서도 미구현

영향:
- 반복 실험 간 DB 상태 동일성 보장 자동화 부재

---

### B. 반복 실행 wrapper (파일럿 5회, N 자동결정)

09 요구:
- 파일럿 5회 수행 후 분산 추정
- 벤치별 반복 수 N 자동 결정
- mean±std 및 결합σ 자동 집계

현재:
- `run_pipeline.py` 가 `n_runs > 1` 일 때 명시적 error. 자동 결정 로직 없음

영향:
- variance 관리 전략 도구화 미흡

---

### C. 자동 판정 스크립트 (성공/부분/실패)

09 요구:
- 두 조건 raw log 입력
- mean 차이 vs 결합σ×2 기준 자동 판정

현재:
- 미구현. analyze 출력 raw 값 기반 수기 판정

영향:
- 판정 일관성/자동화 부족

---

### D. EDWIN prompt 실 적용

09 요구:
- #4/#12: `mmai.lme_answer_prompt = "EDWIN3"`
- #3: `mmai.lme_answer_prompt = "EDWIN1"`

현재:
- `prompts/EDWIN{1,3}.txt` placeholder + `scripts/stages/generate.py` hook 만 존재. 텍스트 미확보 / 실 주입 경로 미구현

영향:
- #3/#4/#12 문서 기준 실험조건 완전 재현 불가

---

## 3) 안전장치 강화 (PR #7 직후 → eval_claude 최신)

| 키 | 분류 | 동작 |
|---|---|---|
| `message_sentence_chunking` | `SWEEP_INGEST_AFFECTING_KEYS` | sweep 키로 들어오면 SystemExit. ingest 결과 Episode shape 를 바꾸므로 retrieve-stage cell toggle 만으로는 A/B 가 성립하지 않음. 비교는 chunk 값별 별도 run + 별도 ingest 로 강제 |
| `summarization_enabled` | `SWEEP_CONFIG_ONLY_KEYS` | sweep 키로 들어오면 SystemExit + CLI 경로에서도 stderr warning. eval 경로가 `short_term_memory=None` 으로 호출되어 LongMemEval 점수에 영향이 없으므로 silent A/A 매트릭스 방지 |

→ silent score divergence / silent A/A 매트릭스 두 종류 모두 generator/validator 단계에서 차단.
