# 20260430 Modified List v0.4

- 작성일: 2026-04-30
- 기준 문서: `docs/msr/09_Reproduction_Code_Changes.md`
- 점검 범위: `scripts/*`, `configs/*`, `prompts/*`, `evaluation/retrieval_agent/*`, `evaluation/utils/agent_utils.py`, `packages/server/*`
- 기준 브랜치: `eval_claude` (HEAD `d55caf2`)
- 목적: v0.3 (HEAD `e0b9234`) 이후 PR #27 (`7468bdf` … `d55caf2`) 까지 반영한 **eval_claude 최신 상태(v0.4)**

> ℹ️ **관계 정리**
>
> - v0.0 / v0.1 / v0.2 (`docs/msr/20260425_modified_list_v0.{0,1,2}.md`) 는 historical 상태입니다.
> - v0.3 (`docs/msr/20260430_modified_list_v0.3.md`) 은 PR #7 이후 추가 commit 까지 반영한 시점입니다.
> - 본 v0.4 는 v0.3 이후 PR #27 (LongMemEval judge 정렬 + lazy init) 까지 반영한 단일 표 입니다. v0.3 본문을 변경하지 않고 §0' 에 v0.3 → v0.4 delta 만 추가, §1 표는 갱신해서 다시 적었습니다.

---

## 0') v0.3 → v0.4 delta (이번 update 핵심)

LongMemEval 데이터셋 한해 judge prompt / 채점 방식이 원본(`xiaowu0162/LongMemEval`)에 정렬됨. PR #27 의 3개 commit 가 누적된 결과.

- ✅ **LongMemEval judge 원본 prompt + yes/no 채점 정렬** (`684f1d6`)
  - `evaluation/retrieval_agent/llm_judge.py` 에 `get_anscheck_prompt(task, q, a, r, abstention)` (5 task + abstention 분기) + `evaluate_llm_judge_longmemeval(...)` 추가.
  - `create_judge_fn(config_path, json_mode: bool = True)` 매개변수 신설. `json_mode=False` 시 OpenAI 호출에서 `response_format` / `text.format` 제거 + `max_tokens=10` 추가. Bedrock 분기 no-op (json 강제가 원래 없음).
  - `evaluation/retrieval_agent/evaluate.py` 에 `_LONGMEMEVAL_TASKS` frozenset 6 task 추가, `process_sample` 에서 LongMemEval 카테고리만 새 judge 로 라우팅. 다른 데이터셋 (LOCOMO, Wiki, HotpotQA) 경로는 무수정.
  - `evaluation/retrieval_agent/test_llm_judge.py` 신규 테스트 8개 (yes/no/abstention/temporal/preference + chat-completions/responses 의 json/text mode kwargs 검증).
- ✅ **text-mode judge lazy init** (`465d8b8` → `d55caf2`)
  - 초안 (`465d8b8`): dataset pre-scan 후 LongMemEval 샘플 존재 시에만 text 모드 judge 생성. 회귀 안전판으로 `process_sample` 에 defensive guard 추가.
  - 최종 (`d55caf2`): pre-scan 제거하고 thread-safe **double-checked locking** 으로 진정한 on-demand init. 첫 LongMemEval 샘플 처리 시점에 한 번만 `create_judge_fn(config, json_mode=False)` 호출.
  - `evaluation/retrieval_agent/test_evaluate.py` 신규: text-mode judge 가 (a) 비-LongMemEval 만 있을 때 미생성, (b) LongMemEval 카테고리에서 생성 — 2 케이스.
- ✅ **review-fix: wrapper 경로 정렬** (`scripts/stages/judge.py`)
  - 리뷰 지적 — `evaluation/retrieval_agent/evaluate.py` 만 정렬되고 `scripts/run_pipeline.py --stage judge` (실제 main wrapper) 가 여전히 `evaluate_llm_judge` 만 호출 → wrapper 경로의 LongMemEval 점수가 legacy 와 불일치.
  - 조치: `scripts/stages/judge.py:run()` 에 `_LONGMEMEVAL_TASKS` frozenset + row-level routing 추가. 동일하게 lazy text-mode judge init.
  - `scripts/test_stages_judge.py` 신규: wrapper routing 4 케이스 (LongMemEval / non-LongMemEval / abstention `_abs` / e2e llm_score).
- ✅ **review-fix: yes/no parser 강화**
  - 리뷰 지적 — `"yes" in raw.lower()` 가 "yesterday" / "not yes" / "{ans: yes}" 등을 모두 1 로 처리.
  - 조치: `_parse_yes_no(raw)` 함수 분리, `\s*\W*(yes|no)\b` regex 로 leading word 매칭. "yesterday" / "not yes" / "" → 0. "yes" / "Yes." / "yes\n" → 1. "yes and no" 는 leading "yes" 가 winner (원본 LongMemEval 동작과 일치).
  - parser regression 테스트 16 (parametrized) + LongMemEval 통합 케이스 3 (yesterday/not-yes/yes-and-no).

테스트 검증: `python3.12 -m pytest evaluation/retrieval_agent/test_llm_judge.py evaluation/retrieval_agent/test_evaluate.py scripts/test_stages_judge.py -v` → **49/49 PASS**.

---

## 0) v0.2 § 4 (PR #7 직후) 대비 변경 요약 — v0.3 시점 (참고용 보존)

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

## 1) 구현 상태 요약 (eval_claude 최신, v0.4 시점)

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
| #4/#12 chunk on/off YAML 제어 | ✅ (sweep 차단 강화) | `p4.yaml` `fixed.message_sentence_chunking`. `scripts/stages/retrieve.py` 의 `SWEEP_INGEST_AFFECTING_KEYS` 가 sweep 키로 들어오면 SystemExit |
| #4/#12 chunk × prefix × k 조합 | 부분 (chunk 별도 run, validator 가 강제) | chunk 비교는 run yaml 분리 + 별도 ingest 필수. prefix × k 는 단일 run sweep 에서 가능 |
| 공통: DB snapshot 동결/복원 | ❌ | 본 도구 범위 밖 |
| 공통: 파일럿 5회 + 본실험 N 자동결정 wrapper | ❌ (`n_runs > 1` 명시 error) | `run_pipeline.py` |
| 공통: 성공/부분/실패 자동 판정 스크립트 | ❌ | future work — analyze 출력 raw 값 수기 판정 |
| #6 MS 재분해 전용 집계 | ✅ | `python scripts/run_pipeline.py … --stage analyze --decompose-multisession` |
| #4/#12 EDWIN prompt 주입 | ❌ (hook only) | `prompts/EDWIN{1,3}.txt` placeholder + `scripts/stages/generate.py` hook. 텍스트 미확보 + 실 적용 미구현 |
| #12 token/accuracy Pareto 자동화 | ✅ | `--stage analyze --pareto` 가 cell 별 token / recall / accuracy 산출 |
| 사용자 `configuration.yml` 보호 | ✅ | `mode=existing` 도 working copy 사용 |
| token / per-tool / fact_hits carry | ✅ | `retrieve.jsonl` 보존 + analyze join + by_tool breakdown |
| **추가**: `generate_config.py` problem CLI (p2/p3/p4/p5/p6/p12) + LENGTH | ✅ | `3fcce7e`. base.yaml + `configs/problems/p*.yaml` + profiles + `runs/_example.json` 머지. LoCoMo `--length` (default 10) → `benchmark.length` |
| **추가**: rerankers list 설정 가능 | ✅ | `d38f5e1`. **model profile** `rerankers:` list + 선택적 `primary_reranker`. `_validate_and_normalize_rerankers()` 가 schema/legacy 검증 + rrf-hybrid 참조 무결성 체크 후 working `configuration.yml` 의 `resources.rerankers` 와 `retrieval_agent.reranker`(=primary) 로 emit |
| **추가**: judge LLM 설정 가능 | ✅ | `d38f5e1`. `--judge-model` CLI 또는 `judge.llm_model_id` (run_cfg) → working `configuration.yml` 의 `retrieval_agent.judge_llm_model` 로 swap (`scripts/stages/judge.py:_swap_judge_llm_model`). model profile 의 optional `judge_llm` 블록은 `_validate_judge_llm()` 으로 검증, 미정의 시 answer `llm_model` 로 fallback |
| **추가**: STM `summarization_enabled` 토글 | ✅ (config-only) | `034a53d` + `ccc289e`. CLI `--summarization on/off` → `fixed.summarization_enabled`. **sweep 키로는 차단** (`SWEEP_CONFIG_ONLY_KEYS`) |
| **추가**: 서버측 STM/SemMem default 정렬 | ✅ | `b6c838d` → `00b4ad3` (#25). `ShortTermMemoryConf.summarization_enabled` default → False, `SemanticMemoryConf.enabled` default → False |
| **추가**: p6 / p12 analyze-only 보호 | ✅ | `8bda959`. `--stage` 미지정 시 reuse_run 인지 판단 → 부모 run 산출물 덮어쓰기 / `benchmark.data_path` 누락 실패 차단 |
| **추가**: LongMemEval split 일치화 | ✅ | `9c54bab`. `p3.yaml`/`p4.yaml` split 을 `longmemeval_s_cleaned` 로 통일 |
| **추가**: LongMemEval offline `data_path` | ✅ | `dc3a72d`. `benchmark.data_path` 가 set 이면 ingest/retrieve 가 HF 호출 우회 → `_common.load_longmemeval_local()` 가 `min(length, len(records))` cap + 4-field normalize |
| **추가**: MSR 한국어 docs / 5-min TLDR / Part1·2·3 walkthrough | ✅ | `de396e4`, `dfb01a3`, `7f98258`, `3847d2a`, `9b84554`, `e0b9234`. p4 walkthrough + 4-A/B/C/D meaning-driven 정리 + glossary 추가 |
| **🆕 v0.4**: LongMemEval judge prompt 원본 정렬 (task별 6분기 + abstention) | ✅ | `684f1d6`. `evaluation/retrieval_agent/llm_judge.py` 에 `get_anscheck_prompt` + `evaluate_llm_judge_longmemeval` 추가. `xiaowu0162/LongMemEval` `evaluate_qa.py:24-43` 동일 wording. `_abs` qid 자동 검출. LOCOMO/Wiki/HotpotQA 는 기존 `ACCURACY_PROMPT` 유지 |
| **🆕 v0.4**: judge 출력 plain-text yes/no 모드 | ✅ | `684f1d6`. `create_judge_fn(config, json_mode=False)` → OpenAI 호출에서 `response_format` 제거 + `max_tokens=10` (원본 fidelity). LongMemEval 만 사용. Bedrock 분기는 원래 JSON 강제가 없어 `json_mode` no-op |
| **🆕 v0.4**: `evaluate.py` LongMemEval 라우팅 | ✅ | `684f1d6`. `_LONGMEMEVAL_TASKS` frozenset 6 task → `process_sample` 에서 LongMemEval 카테고리만 새 judge 로 분기. 출력 스키마 (`llm_score`: 0/1) 동일 → `generate_scores.py` 무영향 |
| **🆕 v0.4**: text-mode judge lazy init | ✅ | `d55caf2` (앞서 `465d8b8` 의 pre-scan 방식을 폐기하고 진정한 on-demand 로 교체). `main()` closure 안에서 `threading.Lock` + double-checked locking. LOCOMO/Wiki/HotpotQA 만 돌릴 때 text-mode judge 생성 비용/실패 차단 |
| **🆕 v0.4 review-fix**: wrapper `scripts/stages/judge.py` LongMemEval routing | ✅ | review-fix. `_LONGMEMEVAL_TASKS` frozenset + row-level routing + lazy text-mode judge. `scripts/run_pipeline.py --stage judge` 가 legacy `evaluate.py` 와 동일한 routing 적용. `scripts/test_stages_judge.py` 4 case |
| **🆕 v0.4 review-fix**: yes/no parser strict word-boundary 매칭 | ✅ | review-fix. `_parse_yes_no(raw)` 분리, `\s*\W*(yes\|no)\b` regex 로 leading word 매칭. "yesterday" / "not yes" / "" 의 false positive 제거. parametrized regression test 16 + LongMemEval 통합 case 3 |
| **🆕 v0.4**: 신규 단위 테스트 | ✅ | `684f1d6` + `465d8b8` + review-fix. `test_llm_judge.py` (LongMemEval judge + json/text mode + parser regression), `test_evaluate.py` (legacy lazy init), `scripts/test_stages_judge.py` (wrapper routing) — 합계 49/49 PASS |

---

## 2) 잔여 미해결 항목

### A. DB snapshot 동결/복원 자동화 — 본 도구 범위 밖 (v0.3 동일)

### B. 반복 실행 wrapper (파일럿 5회, N 자동결정) — `n_runs > 1` 명시 error (v0.3 동일)

### C. 자동 판정 스크립트 (성공/부분/실패) — analyze raw 값 수기 판정 (v0.3 동일)

### D. EDWIN prompt 실 적용 — placeholder + hook 만 존재 (v0.3 동일)

### E. **🆕 v0.4 신규 잔여 항목 — LongMemEval 비-judge 미정렬**

`docs/msr/20260430_longmemeval_retrieval_agent_vs_원본_차이분석_v2.md` §1.5 / §2 와 동기화:

| 항목 | 상태 | 비고 |
|---|---|---|
| Answer prompt 정렬 (`ANSWER_PROMPT` 에 `{question_date}` 추가, open-domain fallback 제거, "max 2 sentences" 출력 제약 완화) | ❌ | LongMemEval 점수에 직접 영향 가능. 별도 PR 분리 권장 |
| Metric 보고 정렬 (`generate_scores.py` 에 macro task-averaged accuracy / abstention-only accuracy 추가, dead code `categories` 매핑 제거) | ❌ | 출력 스키마 호환 (추가 키만). 작은 변경이지만 LongMemEval 논문과 1:1 비교 위해 필요 |
| (선택) NDCG/recall@k retrieval metric | ❌ | chunk-level gold relevance schema 가 retrieve.jsonl 에 들어와야 가능 — dataset/pipeline 확장 필요 |

---

## 3) 안전장치 강화 (v0.3 → v0.4)

| 키 | 분류 | 동작 |
|---|---|---|
| `message_sentence_chunking` | `SWEEP_INGEST_AFFECTING_KEYS` | sweep 키로 들어오면 SystemExit. ingest 결과 Episode shape 를 바꾸므로 retrieve-stage cell toggle 만으로는 A/B 가 성립하지 않음 |
| `summarization_enabled` | `SWEEP_CONFIG_ONLY_KEYS` | sweep 키로 들어오면 SystemExit + CLI 경로에서도 stderr warning. eval 경로가 `short_term_memory=None` 으로 호출되어 LongMemEval 점수에 영향이 없으므로 silent A/A 매트릭스 방지 |
| **🆕 v0.4** text-mode judge lazy init | `evaluate.py:get_text_call_fn` (closure) | `threading.Lock` + double-checked locking. 비-LongMemEval 데이터셋만 돌릴 때 `create_judge_fn(json_mode=False)` 호출 자체를 회피 → config 가 plain-text mode 검증되지 않은 환경에서도 안전 |

→ silent score divergence / silent A/A 매트릭스 / unused-judge fail-fast 세 종류 모두 generator/validator/runtime 단계에서 차단.
