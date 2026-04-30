# 20260425 Modified List v0.2

- 작성일: 2026-04-25
- 기준 문서: `docs/msr/09_Reproduction_Code_Changes.md`
- 점검 범위: `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`, `packages/server/*`
- 목적: 09 문서 수정 항목의 **최신 구현 상태(v0.2)** 를 반영

> ⚠️ **Historical note (2026-04-26)**
>
> 본 v0.2 표는 **기존 `evaluation/retrieval_agent` 코드** 기준 historical 상태입니다. PR #7 eval-tool (브랜치 `claude/memmachine-eval-tool-GIrVz`) 적용 후의 별도 상태는 본 문서 § "PR #7 eval-tool 반영 후 상태" 를 참조하세요. v0.2 표 자체는 변경하지 않습니다.

---

## 0) v0.1 대비 변경 요약

- ✅ `message_sentence_chunking` YAML 값이 retrieval_agent 평가 경로에서 실제로 반영되도록 wiring 완료
- ✅ `run_benchmark_matrix.sh`에 LongMemEval `chunk {off,on}` 축 추가
- ✅ `README_MSR.md`에 chunk 토글 동작 및 사용 주의사항 반영

---

## 1) 구현 상태 요약

상태 표기:
- ✅ 구현 완료
- ❌ 미구현
- 제외: 이번 기준에서 미적용 정책

| 항목 (09 기준) | 상태 | 현재 구현 상태 |
|---|---:|---|
| #4/#12 LongMemEval `User:` prefix 삽입 | ✅ | `prepend_user_prefix` 토글로 on/off 운용 가능 |
| #4/#12 k sweep (10,20,30,50,100) | ✅ | `run_benchmark_matrix.sh`에 반영 |
| #3 C5/C6 운용 | ✅ | prefix on/off 조건으로 실행 가능 |
| #5 LoCoMo cat5 skip 포팅 | ✅ | `locomo_search.py`에 cat5 제외 로직 존재 |
| #5 LoCoMo 모드 sweep (Memory/Agent) | ✅ | 매트릭스 스크립트에 반영 |
| #2 HotpotQA 모드 sweep (Memory/Agent) | ✅ | 매트릭스 스크립트에 반영 |
| #2 HotpotQA 고정 랜덤 500 샘플 파일 생성/로드 | 제외 | `length=500` 정책 사용 |
| #4/#12 chunk on/off YAML 제어 | ✅ | `init_memmachine_params()`가 YAML `message_sentence_chunking` 값을 사용하도록 반영 |
| #4/#12 chunk on/off 매트릭스 실행 | ✅ | LongMemEval `chunk x prefix x k` 조합 실행 지원 |
| 공통: DB snapshot 동결/복원 스크립트 | ❌ | 구현 확인 안 됨 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ | 구현 확인 안 됨 |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | 구현 확인 안 됨 |
| #6 MS 재분해 전용 집계 스크립트 | ❌ | 구현 확인 안 됨 |
| #4/#12, #3 Edwin prompt 주입 (`mmai.lme_answer_prompt`) | ❌ | 주입 경로/주입 코드 미확인 |

---

## 2) 이번에 완료된 항목 상세

### A. chunk YAML wiring 완료

- `evaluation/utils/agent_utils.py:init_memmachine_params()`에서
  `message_sentence_chunking`을 `bool | None`으로 받고,
  `None`일 경우 `episodic_memory.long_term_memory.message_sentence_chunking`
  값을 사용하도록 반영됨.
- `packages/server/src/.../episodic_config.py`의
  `LongTermMemoryConfPartial`에 `message_sentence_chunking` 필드 추가로
  partial config/YAML 역직렬화 시 값 유실 방지.
- 관련 테스트(`test_episodic_config.py`)에 merge/round-trip/omit 케이스 추가.

### B. run_benchmark_matrix chunk 축 추가

- LongMemEval 매트릭스가
  `chunk {off,on} x prefix {off,on} x k {10,20,30,50,100}`로 확장됨.
- 스크립트 내부에서
  `episodic_memory.long_term_memory.message_sentence_chunking`를 조합별로 갱신.
- postfix에 chunk 상태 포함 (`lmes_chunkoff_*`, `lmes_chunkon_*`).

### C. README_MSR 업데이트

- 변경 사항에 chunk 토글 반영 내용 추가.
- run_benchmark_matrix 사용법/동작 방식에 chunk 설정 키 반영.
- `--skip-ingest` 사용 시 chunk 실험에 대한 주의사항 명시.

---

## 3) 전혀 구현되지 않은 항목 (상세)

### A. DB snapshot 동결/복원 자동화

09 요구:
- PostgreSQL/Neo4j/SQLite 대상 snapshot 생성/복원
- snapshot ID 기록

현재:
- retrieval_agent 실행 스크립트 계열에서 snapshot 생성/복원 파이프라인 미확인

영향:
- 반복 실험 간 DB 상태 동일성 보장 자동화 부재

---

### B. 반복 실행 wrapper (파일럿 5회, N 자동결정)

09 요구:
- 파일럿 5회 수행 후 분산 추정
- 벤치별 반복 수 N 자동 결정
- mean±std 및 결합σ 자동 집계

현재:
- 조합 실행 스크립트는 있으나 반복 수 자동결정/파일럿 단계 로직 없음

영향:
- variance 관리 전략 도구화 미흡

---

### C. 자동 판정 스크립트 (성공/부분/실패)

09 요구:
- 두 조건 raw log 입력
- mean 차이 vs 결합σ×2 기준 자동 판정

현재:
- 해당 전용 판정 스크립트 미확인

영향:
- 판정 일관성/자동화 부족

---

### D. #6 Multi-session 재분해 전용 스크립트

09 요구:
- #4/#12 산출물을 재활용해 MS vs SSU/SSA 비교
- 결합σ×2 기준 자동 계산

현재:
- 전용 집계 스크립트 미확인

영향:
- #6 후처리 자동화 부재

---

### E. EDWIN prompt 주입 경로 구현

09 요구:
- #4/#12: `mmai.lme_answer_prompt = "EDWIN3"`
- #3: `mmai.lme_answer_prompt = "EDWIN1"`

현재:
- retrieval_agent 경로에서 위 속성 주입 코드/설정 경로 미확인

영향:
- #3/#4/#12 문서 기준 실험조건 완전 재현 불가

---

## 4) PR #7 eval-tool 반영 후 상태 (2026-04-26 추가)

PR #7 (브랜치 `claude/memmachine-eval-tool-GIrVz`) 가 추가한 `scripts/` + `configs/` wrapper 기준 상태. 위 §1 의 v0.2 표는 historical 로 유지하고, 본 표는 PR #7 머지 후의 상태만 반영합니다.

| 항목 (09 기준) | v0.2 상태 | PR #7 상태 | PR #7 처리 위치 |
|---|:---:|:---:|---|
| #4/#12 LongMemEval `User:` prefix 삽입 | ✅ | ✅ | `configs/problems/p3.yaml`/`p4.yaml` 의 `prepend_user_prefix` 토글, `generate_config.py` 가 working configuration.yml 에 반영 |
| #4/#12 k sweep (10,20,30,50,100) | ✅ | ✅ | `configs/problems/p4.yaml` `sweep.search_limit` |
| #3 C5/C6 운용 | ✅ | ✅ | `configs/problems/p3.yaml` `sweep.prepend_user_prefix: [false, true]` |
| #5 LoCoMo cat5 skip 포팅 | ✅ | ✅ (재사용) | `locomo_search.py` 그대로 호출 |
| #5 LoCoMo 모드 sweep (Memory/Agent) | ✅ | ✅ | `configs/problems/p5.yaml` `sweep.test_target` |
| #2 HotpotQA 모드 sweep (Memory/Agent) | ✅ | ✅ | `configs/problems/p2.yaml` `sweep.test_target` |
| #2 HotpotQA `length=500` 정책 + split | 제외 | ✅ (`split=validation`) | `p2.yaml` 명시 |
| #4/#12 chunk on/off YAML 제어 | ✅ | ✅ | `p4.yaml` `fixed.message_sentence_chunking`, ingest 전에 working configuration.yml 에 반영 |
| #4/#12 chunk × prefix × k 조합 | ✅ (`run_benchmark_matrix.sh`) | 부분 (chunk 별도 run 필요) | PR #7 기본 `p4.yaml` 은 chunk=on, prefix=on 고정 + k sweep. prefix × k 는 run YAML sweep 확장으로 단일 run 에서 가능. 단 `message_sentence_chunking` 은 ingest 결과 (Episode 저장 구조) 에 영향을 주므로 chunk on/off 비교는 chunk 값별로 별도 `run_name` + 별도 ingest 가 필요. 전체 chunk × prefix × k 매트릭스는 단일 run 기본 제공이 아님 |
| 공통: DB snapshot 동결/복원 | ❌ | ❌ | 본 도구 범위 밖 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ | ❌ (단 `n_runs > 1` 명시 error) | `run_pipeline.py` |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | ❌ | future work — analyze 출력 raw 값 수기 판정 |
| #6 MS 재분해 전용 집계 | ❌ | ✅ | `python scripts/run_pipeline.py … --stage analyze --decompose-multisession` |
| #4/#12 EDWIN prompt 주입 | ❌ | ❌ (hook only) | `prompts/EDWIN{1,3}.txt` placeholder + `scripts/stages/generate.py` hook. 텍스트 미확보 + 실 적용 미구현 |
| **추가**: #12 token/accuracy Pareto 자동화 | — | ✅ | `--stage analyze --pareto` 가 cell 별 token / recall / accuracy 산출 |
| **추가**: 사용자 `configuration.yml` 보호 | — | ✅ | `mode=existing` 도 working copy 사용 |
| **추가**: token / per-tool / fact_hits carry | — | ✅ | retrieve.jsonl 보존 + analyze join + by_tool breakdown |

→ PR #7 후 신규 해결: #6 / #12 / config 보호 / metric carry 4건. 잔여 미해결: EDWIN 실 적용 / DB snapshot / 반복 wrapper / 자동 σ×2 판정.

---

## 5) 최신 eval_claude 반영 후 상태 (2026-04-30 추가)

PR #7 (foundation, `09ff952`) 머지 후 `claude/memmachine-eval-tool-GIrVz` 계열에서 진행된 후속 commit (`3fcce7e` … `dc3a72d`) 까지 반영한 상태. 위 §1 의 v0.2 표와 §4 의 PR #7 표는 historical 로 유지하고, 본 표는 현재 시점 eval_claude 의 상태만 반영합니다.

| 항목 (09 기준) | PR #7 상태 | 최신 상태 | 최신 처리 위치 / 비고 |
|---|:---:|:---:|---|
| #4/#12 LongMemEval `User:` prefix 삽입 | ✅ | ✅ | `p3.yaml` sweep / `p4.yaml` fixed `prepend_user_prefix`, `generate_config.py` → working `configuration.yml` |
| #4/#12 k sweep (10,20,30,50,100) | ✅ | ✅ | `p4.yaml` `sweep.search_limit` |
| #3 C5/C6 운용 | ✅ | ✅ | `p3.yaml` `sweep.prepend_user_prefix: [false, true]` |
| #5 LoCoMo cat5 skip 포팅 | ✅ | ✅ | `locomo_search.py` 그대로 호출 |
| #5 LoCoMo 모드 sweep (Memory/Agent) | ✅ | ✅ | `p5.yaml` `sweep.test_target` |
| #2 HotpotQA 모드 sweep (Memory/Agent) | ✅ | ✅ | `p2.yaml` `sweep.test_target` |
| #2 HotpotQA `length=500` 정책 + split | ✅ | ✅ | `p2.yaml` 명시 |
| #4/#12 chunk on/off YAML 제어 | ✅ | ✅ (sweep 차단 강화) | `p4.yaml` `fixed.message_sentence_chunking`. `scripts/stages/retrieve.py` 의 `SWEEP_INGEST_AFFECTING_KEYS` 가 `message_sentence_chunking` 을 sweep 키로 받으면 SystemExit (ingest 결과 Episode shape 가 고정되어 있어 retrieve-stage cell toggle 만으로는 진정한 A/B 가 불가능) |
| #4/#12 chunk × prefix × k 조합 | 부분 (chunk 별도 run) | 부분 (chunk 별도 run, validator 가 강제) | chunk 비교는 run yaml 분리 + 별도 ingest 필수. prefix × k 는 단일 run sweep 에서 가능 |
| 공통: DB snapshot 동결/복원 | ❌ | ❌ | 본 도구 범위 밖 (변동 없음) |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ (`n_runs > 1` error) | ❌ (`n_runs > 1` error) | `run_pipeline.py` 동일 |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | ❌ | future work — analyze 출력 raw 값 수기 판정 |
| #6 MS 재분해 전용 집계 | ✅ | ✅ | `python scripts/run_pipeline.py … --stage analyze --decompose-multisession` |
| #4/#12 EDWIN prompt 주입 | ❌ (hook only) | ❌ (hook only) | `prompts/EDWIN{1,3}.txt` placeholder + `scripts/stages/generate.py` hook. 텍스트 미확보 + 실 적용 미구현 (변동 없음) |
| #12 token/accuracy Pareto 자동화 | ✅ | ✅ | `--stage analyze --pareto` 가 cell 별 token / recall / accuracy 산출 |
| 사용자 `configuration.yml` 보호 | ✅ | ✅ | `mode=existing` 도 working copy 사용 |
| token / per-tool / fact_hits carry | ✅ | ✅ | `retrieve.jsonl` 보존 + analyze join + by_tool breakdown |
| **추가**: `generate_config.py` p1..p6 problem CLI + LENGTH | — | ✅ | `3fcce7e`. base.yaml + `configs/problems/p*.yaml` + profiles + `runs/_example.json` 머지. LoCoMo `--length` (default 10) → `benchmark.length`. `scripts/stages/generate.py` 추가 |
| **추가**: rerankers list 설정 가능 | — | ✅ | `d38f5e1`. 하드코딩 LongMemEval default 제거. problem yaml + sweep 에서 rerankers list 수용. model example yaml 검증 강화 |
| **추가**: judge LLM 설정 가능 | — | ✅ | `d38f5e1`. `--judge-llm` CLI 또는 `judge_llm_model` (run_cfg) → `retrieval_agent.judge_llm_model` 로 run yaml 에 반영. `evaluation/retrieval_agent/llm_judge.py` / `scripts/stages/judge.py` 가 런타임에서 사용 |
| **추가**: STM `summarization_enabled` 토글 | — | ✅ (config-only) | `034a53d` + `ccc289e`. CLI `--summarization on/off` → `fixed.summarization_enabled`. **sweep 키로는 차단** (`SWEEP_CONFIG_ONLY_KEYS`): eval 경로가 `EpisodicMemory(short_term_memory=None)` (`agent_utils.py:461`) 로 호출되어 LongMemEval 점수에 영향 없음. CLI 사용 시 stderr warning |
| **추가**: 서버측 STM/SemMem default 정렬 | — | ✅ | `b6c838d` → `00b4ad3` (#25). `ShortTermMemoryConf.summarization_enabled` default → False, `SemanticMemoryConf.enabled` default → False. eval-tool 이 emit 하는 `configuration.yml` 과 서버 default 가 일치 |
| **추가**: p6 / p12 analyze-only 보호 | — | ✅ | `8bda959`. `--stage` 미지정 시 reuse_run 인지 판단 → 부모 run 산출물 덮어쓰기 / `benchmark.data_path` 누락 실패 차단 |
| **추가**: LongMemEval split 일치화 | — | ✅ | `9c54bab`. `p3.yaml`/`p4.yaml` split 을 `longmemeval_s_cleaned` 로 통일 (이전: `longmemeval_s` ↔ matrix runner 와 silent 점수 분기). `scripts/test_longmemeval_split_consistency.py` 4 케이스로 회귀 차단 |
| **추가**: LongMemEval offline `data_path` | — | ✅ | `dc3a72d`. `benchmark.data_path` 가 set 이면 ingest/retrieve 가 HF 호출 우회 → `_common.load_longmemeval_local()` 가 `min(length, len(records))` cap + 4-field normalize. p3/p4 default = `evaluation/data/longmemeval_s_cleaned.json`, generate 시 절대경로로 resolve (cwd 독립). HF 사용 원하면 `data_path` 줄 제거 |
| **추가**: MSR 한국어 docs / 5-min TLDR / Part1·2·3 walkthrough | — | ✅ | `de396e4`, `dfb01a3`, `7f98258`, `3847d2a`, `9b84554`, `e0b9234`. p4 walkthrough + 4-A/B/C/D meaning-driven 정리 + glossary 추가 |

### 5.1) v0.2 / PR #7 표 대비 변동 요약

- 신규 ✅ : `generate_config.py` p1..p6 CLI / rerankers list / judge LLM 설정 / STM summarization 토글 / 서버 default 정렬 / p6·p12 ingest 보호 / split 통일 / `data_path` offline / 한국어 docs (총 9 항목)
- 안전장치 강화: `SWEEP_INGEST_AFFECTING_KEYS` (chunk) + `SWEEP_CONFIG_ONLY_KEYS` (summarization) 의 sweep 차단으로 silent A/A 매트릭스 방지
- 잔여 미해결 (변동 없음): EDWIN 실 적용 / DB snapshot 자동화 / 파일럿 5회 + N 자동결정 wrapper / 성공·부분·실패 자동 σ×2 판정

