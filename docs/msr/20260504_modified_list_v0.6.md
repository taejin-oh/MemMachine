# 20260504 Modified List v0.6

- 작성일: 2026-05-04
- 기준 브랜치: `claude/longmemeval-judge-prompt-alignment-Q6PUG`
- 직전 베이스라인: v0.5 (`docs/msr/20260504_modified_list_v0.5.md`)
- 목적: v0.5 이후 추가된 **retrieval_agent LongMemEval answer prompt 3-정책 도입** 을 단일 delta 로 기록 (default = `LME_origin_prompt` upstream verbatim, opt-in `memmachine_original` hybrid + `agent_lightning` v0.5 baseline)

---

## 0''') v0.5 → v0.6 delta

retrieval_agent 경로의 LongMemEval **answer prompt** 를 3-정책 시스템으로 재구성 (v0.5 의 `longmemeval_yesno_policy` 와 동일한 opt-in 패턴). LongMemEval 원본의 핵심 평가 제약(Current Date 제공, memory 기반 답변, open-domain fallback 제거, 출력 길이 제한 제거)이 모든 정책 또는 default 에 반영되며, 본문 출처는 정책별로 명시:

| 정책 | 본문 출처 | 평가 제약 충족 | 사용 시나리오 |
|---|---|---|---|
| `LME_origin_prompt` (**default**) | `xiaowu0162/LongMemEval` upstream verbatim 복사 (`src/generation/run_generation.py` `answer_prompt_template`, no-merge no-CoT 분기). 위치 `{}` 만 named placeholder 로 변환, 그 외 텍스트 비변경 | ✅ (verbatim) | upstream **prompt template 영향만 분리해서 측정** 하기 위한 기준점. retrieval / memory formatting / generation pipeline 은 MemMachine `retrieval_agent` 경로를 그대로 사용 — upstream baseline 전체 재현이 아님 |
| `memmachine_original` | **MemMachine episodic_memory LongMemEval prompt 본문을 retrieval_agent 경로에 적용** (`evaluation/episodic_memory/longmemeval_search.py:36-52` 차용, KNOWLEDGE UPDATES / PLANNED ACTIONS 추론 가이드 포함) + `Current date: {question_date}` placeholder | ✅ (구조적 속성 모두 만족, 단 본문은 verbatim 아님 — hybrid) | 두 진입점(`evaluation/episodic_memory/` 와 `evaluation/retrieval_agent/`) 모두에서 동일한 prompt 본문으로 비교가 필요할 때 |
| `agent_lightning` | v0.5 까지 사용한 Agent Lightning paper(arXiv:2508.03680) prompt 그대로 | ❌ (Current Date 없음, open-domain fallback 허용, "max 2 sentences" 제약) | v0.5 baseline 점수와 1:1 비교가 필요할 때 |

### 배경

v0.5 시점 잔여 항목 — `docs/msr/20260430_longmemeval_retrieval_agent_vs_원본_차이분석_v2.md` §1.5 / §2 의 "Answer prompt 정렬" — 이 v0.6 에서 해소됨. v0.5 까지 사용된 Agent Lightning paper(arXiv:2508.03680) 출처 prompt 는 다음 3가지에서 LongMemEval 원본 평가 제약과 어긋났음:

1. `{question_date}` 부재 — `temporal-reasoning` 카테고리에서 시간 컨텍스트 손실.
2. Open-domain fallback 허용 — 메모리 시스템 평가 본연의 목적(메모리 retrieval) 평가 누수 위험.
3. "max 2 sentences" 출력 제약 — 원본은 길이 cap 없음.

v0.6 의 핵심 변경은 **단일 본문 교체가 아니라 정책 시스템 도입**:
- default `LME_origin_prompt` 는 upstream `answer_prompt_template` 의 no-merge no-CoT 분기 본문**만** verbatim 적용한 정책. retrieval / memory formatting / generation pipeline 은 MemMachine `retrieval_agent` 경로를 그대로 사용하므로, **upstream baseline 전체 재현이 아니라 prompt template 영향 분리용 기준점**. 이 정책에서 보고된 점수는 "본문은 upstream verbatim, 그 외 파이프라인은 MemMachine retrieval_agent" 로 해석해야 함.
- `memmachine_original` 정책은 **MemMachine 의 episodic_memory LongMemEval prompt 본문을 retrieval_agent 경로에 적용** 한 hybrid — 두 진입점 간 일관성이 필요할 때 옵트인.
- `agent_lightning` 정책은 v0.5 까지 사용한 prompt 를 그대로 보존 — v0.5 점수와 1:1 비교 baseline.

### 평가 대상 범위

`evaluation/retrieval_agent/` 경로의 LongMemEval 평가만:
- Legacy: `evaluation/retrieval_agent/longmemeval_test.py`
- Wrapper: `scripts/stages/retrieve.py` (`_run_longmemeval_cell`)

`evaluation/episodic_memory/` 는 별도 평가 경로로 본 변경 범위 외. 단 `longmemeval_search.py:36-52` 의 prompt 본문은 **본 변경의 reference source 로 텍스트 복사** (코드 의존성 없음). `evaluation/retrieval_agent/{hotpotQA_test.py,locomo_search.py,wikimultihop_search.py}` sibling benchmark 는 `process_question(prompt_extra=None)` default 로 backward compat 유지.

### 변경 내역

- ✅ **Pydantic schema** — `packages/server/src/memmachine_server/common/configuration/retrieval_config.py`
  - `RetrievalAgentConf.longmemeval_answer_prompt: Literal["memmachine_original", "agent_lightning", "LME_origin_prompt"] = "LME_origin_prompt"` 추가 (default = upstream verbatim).
- ✅ **Prompt 본문 분리** — `evaluation/retrieval_agent/longmemeval_test.py`
  - `_ANSWER_PROMPT_LME_ORIGIN` (**default** 정책 본문, xiaowu0162/LongMemEval upstream verbatim, no-merge no-CoT 분기. 위치 `{}` placeholder 만 named placeholder 로 변환).
  - `_ANSWER_PROMPT_MEMMACHINE_ORIGINAL` (하이브리드 옵션, KNOWLEDGE UPDATES / PLANNED ACTIONS 가이드 + `Current date: {question_date}` + `{question}`).
  - `_ANSWER_PROMPT_AGENT_LIGHTNING` (v0.5 본문 그대로 보존, baseline rerun 용).
  - `_ANSWER_PROMPT_BY_POLICY` 매핑 dict.
  - `ANSWER_PROMPT` 공개 alias → `_ANSWER_PROMPT_LME_ORIGIN` (default 와 일치, backward import 호환성 유지).
  - `ANSWER_PROMPT` 공개 alias → `_ANSWER_PROMPT_MEMMACHINE_ORIGINAL` (default 와 일치, `scripts/stages/retrieve.py:121` import 호환성 유지).
  - `_format_question_date(raw)` helper — `"YYYY/MM/DD (Day) HH:MM"` → `"%A, %B %d, %Y at %I:%M %p"` (e.g. "Monday, April 10, 2023 at 11:07 PM"). Empty/missing → `""` (graceful), 알 수 없는 포맷 → raw 반환.
  - `_select_answer_prompt(policy)` — 잘못된 정책은 `ValueError`.
  - `_resolve_answer_prompt_policy(cli_value, config_path)` — CLI > config > Pydantic default. config 누락 시 graceful fallback.
- ✅ **Dataset normalization** — `evaluation/retrieval_agent/longmemeval_test.py:325-340`
  - `normalized_record["question_date"] = str(... or "")` 명시적 보존 (defensive empty-string default).
- ✅ **`longmemeval_search()` 시그니처 확장** — `evaluation/retrieval_agent/longmemeval_test.py:198-`
  - `answer_prompt_policy: str = "LME_origin_prompt"` 추가 (Pydantic default 와 일치).
  - sample 처리 루프에서 prompt body 내 `{question_date}` placeholder 존재 시에만 `prompt_extra={"question_date": _format_question_date(...)}` 전달.
- ✅ **CLI 플래그** — `evaluation/retrieval_agent/longmemeval_test.py:build_parser()`
  - `--longmemeval-answer-prompt {LME_origin_prompt,agent_lightning,memmachine_original}` (default `None` → config 폴백; choices 는 `sorted(_ANSWER_PROMPT_BY_POLICY)` 자동 갱신).
  - `main()` 시작 직후 `[longmemeval] longmemeval_answer_prompt=...` 로그 출력.
- ✅ **`agent_utils.process_question()` 시그니처 확장** — `evaluation/utils/agent_utils.py:57-`
  - `prompt_extra: dict[str, str] | None = None` 추가. line 96 부근에서 `fmt_kwargs = {"memories": ..., "question": ...}; if prompt_extra: fmt_kwargs.update(prompt_extra); prompt = answer_prompt.format(**fmt_kwargs)` 로 변경.
  - **Backward compat**: HotpotQA / LoCoMo / Wiki-Multihop 호출부는 `prompt_extra` 미전달 → 동작 비트-동일.
- ✅ **Wrapper 진입점 정렬** — `scripts/stages/retrieve.py`
  - 새 helper `_resolve_answer_prompt_policy(run_cfg, config_path)`: `run_cfg.evaluation.longmemeval.answer_prompt` 우선, 미지정 시 `Configuration.load_yml_file(...).retrieval_agent.longmemeval_answer_prompt` 폴백, 잘못된 값은 `ValueError`.
  - `_run_longmemeval_cell()` 내부에서 정책 resolve → prompt body 선택 → `prompt_extra` 채워서 `process_question()` 호출.
  - `run()` 의 `[retrieve]` 헤더 로그에 `longmemeval_answer_prompt=...` 항상 포함 (LongMemEval benchmark 일 때만).
- ✅ **eval-tool CLI** — `scripts/generate_config.py`
  - `--longmemeval-answer-prompt {memmachine_original,agent_lightning,LME_origin_prompt}` CLI 플래그 (`--longmemeval-yesno-policy` 옆).
  - `cli_to_overrides()` 가 `out["evaluation"]["longmemeval"]["answer_prompt"] = ...` 로 매핑.
- ✅ **테스트 추가** (v0.5 의 190 PASS → v0.6 최종 220 PASS, +30건; LME_origin_prompt 추가로 +3건)
  - `evaluation/retrieval_agent/test_longmemeval_test.py` (신규) — `_format_question_date` 3건, prompt 본문 invariant 6건 (memmachine_original / agent_lightning / **LME_origin_prompt verbatim 검증 + 렌더링 + reasoning guides 부재 검증**), `_select_answer_prompt` 4건, `_resolve_answer_prompt_policy` 4건, dataset normalization 1건 (`pytest.importorskip` 가드).
  - `scripts/test_stages_retrieve.py` (신규) — `_resolve_answer_prompt_policy` 4건 (run_cfg 우선 / config 폴백 / Pydantic default / invalid 거부) + 헤더 로그 검증 2건 (longmemeval / non-longmemeval).
  - `scripts/test_generate_config_judge.py` (확장) — schema roundtrip 4건 (default / agent_lightning 보존 / **LME_origin_prompt 보존** / invalid 거부) + CLI 매핑 5건 (포함 **LME_origin_prompt 매핑**).
  - `scripts/test_generate_config_rerankers.py::_ns` — namespace stub 에 `longmemeval_answer_prompt` attribute 추가.

### 결정 사유 (사용자 합의)

| 결정 항목 | 채택 | 사유 |
|---|---|---|
| **Default 정책** | **`LME_origin_prompt`** — xiaowu0162/LongMemEval upstream `answer_prompt_template` no-merge no-CoT 분기 verbatim 복사 | default 점수가 어떤 prompt template 본문에서 나왔는지를 모호함 없이 전달. **prompt template 만 upstream verbatim, retrieval / memory formatting / generation pipeline 은 MemMachine `retrieval_agent` 경로 그대로** — upstream baseline 전체 재현이 아니라 prompt template 영향 분리용 기준점 |
| Hybrid 정책 (`memmachine_original`) | MemMachine episodic_memory LongMemEval prompt 본문을 retrieval_agent 경로에 적용 (`evaluation/episodic_memory/longmemeval_search.py:36-52` 본문 차용) | 두 진입점(`episodic_memory/` 와 `retrieval_agent/`) 모두에서 동일한 prompt 본문으로 평가 비교가 필요한 경우 |
| v0.5 baseline 정책 (`agent_lightning`) | Agent Lightning paper prompt 그대로 보존 | v0.5 점수와 1:1 비교 |
| Date 포맷 | `"%A, %B %d, %Y at %I:%M %p"` (e.g. "Monday, April 10, 2023 at 11:07 PM") | `episodic_memory/longmemeval_search.py:175-177` 와 동일 → 두 entrypoint 간 일치 |
| 정책 게이팅 | opt-in 정책 필드, default = `LME_origin_prompt` | v0.5 의 `longmemeval_yesno_policy` 패턴 미러. CLI > run_cfg > configuration.yml > Pydantic default 폴백 체인 |

### 검증

```bash
# 단위 + 통합 회귀
/home/user/MemMachine/.venv/bin/python -m pytest evaluation/retrieval_agent/ scripts/ -v
# → 220 passed, 1 skipped (v0.5 baseline 190 + 30 신규 [LME_origin_prompt 정책 추가])

# Schema roundtrip
/home/user/MemMachine/.venv/bin/python -c "from memmachine_server.common.configuration.retrieval_config import RetrievalAgentConf; print(RetrievalAgentConf().longmemeval_answer_prompt)"
# → LME_origin_prompt

# Prompt smoke (LME_origin_prompt — default, upstream verbatim)
/home/user/MemMachine/.venv/bin/python -c "
from evaluation.retrieval_agent.longmemeval_test import _ANSWER_PROMPT_LME_ORIGIN, _format_question_date
print(_ANSWER_PROMPT_LME_ORIGIN.format(
    memories='M', question_date=_format_question_date('2023/04/10 (Mon) 23:07'), question='Q?'))
"
# → "I will give you several history chats ...\nHistory Chats:\n\nM\n\nCurrent Date: Monday, April 10, 2023 at 11:07 PM\nQuestion: Q?\nAnswer:"
```

### 위험 / 사이드이펙트

1. **점수 변화 폭**: open-domain fallback 제거 + Current Date 추가 + length cap 제거 동시 적용 → 카테고리별 ±5pp 변동 예상. Mitigation: `agent_lightning` 옵트인으로 v0.5 baseline 재실행 가능.
2. **Backward compat (sibling benchmarks)**: `process_question(prompt_extra=None)` default 로 HotpotQA / LoCoMo / Wiki-MH 호출부 비트-동일. 단일 `answer_prompt.format` site (= line 96) 만 변경됨.
3. **Missing question_date**: `xiaowu0162/longmemeval-cleaned` HF dataset 은 항상 채움. defensive empty-string fallback 으로 합성 fixture 안전.

### Out of scope

- `generate_scores.py` macro task-averaged accuracy / abstention-only accuracy 추가 — 미진행 (v2 분석 §1.5 잔여).
- dead code `categories` 매핑 제거 / LongMemEval task name 갱신 — 미진행.
- (선택) NDCG/recall@k retrieval metric — chunk-level gold relevance schema 필요.

---

## 0''') v0.6 후속 (추가 예정)

본 문서 작성 시점에는 추가 후속 항목 없음. 잔여 작업은 위 "Out of scope" 참조.
