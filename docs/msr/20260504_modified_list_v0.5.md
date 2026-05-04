# 20260504 Modified List v0.5

- 작성일: 2026-05-04
- 기준 브랜치: `eval_claude`
- 직전 베이스라인: v0.4 (`docs/msr/20260430_modified_list_v0.4.md`)
- 목적: v0.4 이후 추가된 **LongMemEval yes/no 파서 정책 (lenient / strict) 옵션화**를 단일 delta 로 기록

---

## 0') v0.4 → v0.5 delta

v0.4 시점의 strict whole-string 파서가 **default = lenient (원본 LongMemEval `'yes' in lower(raw)` 그대로)** 로 전환되고, strict 는 옵트인.

### 배경

- 원본 (`xiaowu0162/LongMemEval/src/evaluation/evaluate_qa.py`) 채점은 `'yes' in eval_response.lower()` substring 매칭.
- v0.4 의 strict whole-string 매칭은 verbose 응답 ("Yes, the answer matches") / substring trap (`yesterday`) 을 모두 0 으로 처리 → paper 수치 대비 underestimate, 약한 judge 모델 (Llama 8B / Mistral 7B 등) 에선 채점 정확도가 아닌 *format 순응도*를 측정.
- v0.5: 파서 자체에 `policy: Literal["lenient", "strict"]` 인자 추가, default `lenient` 로 paper 와 100% 일치 동작 복원. strict 는 명시적으로 선택 가능.

### 변경 내역

- ✅ **Pydantic schema** — `packages/server/src/memmachine_server/common/configuration/retrieval_config.py`
  - `RetrievalAgentConf.longmemeval_yesno_policy: Literal["lenient", "strict"] = "lenient"` 추가.
- ✅ **`_parse_yes_no(raw, policy)`** — `evaluation/retrieval_agent/llm_judge.py`
  - `policy="lenient"` (기본): `1 if "yes" in (raw or "").lower() else 0` (원본 그대로).
  - `policy="strict"`: 기존 v0.4 의 `\A\s*(yes|no)[\s.!?,]*\Z` whole-string 매칭.
  - 알 수 없는 정책은 `ValueError`.
  - `evaluate_llm_judge_longmemeval(..., yesno_policy="lenient")` 인자 추가, `_parse_yes_no` 에 그대로 전달.
- ✅ **레거시 진입점 정렬** — `evaluation/retrieval_agent/evaluate.py`
  - `--longmemeval-yesno-policy {lenient,strict}` CLI 플래그. **default 는 None** — 미지정 시 `_resolve_yesno_policy(args, config_path)` 가 `Configuration.load_yml_file(...).retrieval_agent.longmemeval_yesno_policy` 로 폴백.
  - `process_sample(..., longmemeval_yesno_policy)` 시그니처 확장.
  - `main()` 시작 직후 `[evaluate] longmemeval_yesno_policy=...` 로그.
- ✅ **Wrapper 진입점 정렬** — `scripts/stages/judge.py`
  - 새 helper `_resolve_yesno_policy(run_cfg, config_path)`: `run_cfg.judge.longmemeval_yesno_policy` 우선, 미지정 시 `Configuration.load_yml_file(...).retrieval_agent.longmemeval_yesno_policy` 폴백, 잘못된 값은 `ValueError`.
  - `run()` 의 `[judge]` 헤더 로그에 `longmemeval_yesno_policy=...` 항상 포함.
  - LongMemEval 분기에서 `evaluate_llm_judge_longmemeval(..., yesno_policy=...)` 로 전달.
- ✅ **eval-tool CLI** — `scripts/generate_config.py`
  - `--longmemeval-yesno-policy {lenient,strict}` CLI 플래그 추가 (`--judge-model` 옆).
  - `cli_to_overrides()` 가 `out["judge"]["longmemeval_yesno_policy"] = ...` 로 매핑. `--judge-model` 과 동일 dict 공유 (`setdefault("judge", {})`).
- ✅ **테스트 추가** (총 +13건, 190/190 PASS)
  - `evaluation/retrieval_agent/test_llm_judge.py` — 기존 strict 테스트 4개 호출부에 `policy="strict"` 명시.
  - `evaluation/retrieval_agent/test_evaluate.py` — `--longmemeval-yesno-policy` CLI 우선, 미지정 시 config 폴백 검증 (2건).
  - `scripts/test_stages_judge.py` — `_resolve_yesno_policy` 정밀 테스트 4건 (run_cfg 우선 / config 폴백 / Pydantic default / invalid 거부) + log 출력 검증 1건.
  - `scripts/test_generate_config_judge.py` — schema roundtrip 3건 (default / strict 보존 / invalid 거부) + CLI 매핑 5건.
  - `scripts/test_generate_config_rerankers.py::_ns` — 신규 attribute 추가.

### 결정 사유 (사용자 합의)

| 결정 항목 | 채택 | 사유 |
|---|---|---|
| Lenient 파서 구현 | 원본 그대로 `'yes' in lower(raw)` | paper 수치 100% 재현. substring trap (`yesterday` → 1) 도 그대로 — 원본의 알려진 동작 |
| Default | `lenient` | 원본 일치가 우선. strict 는 false-positive 회피용으로 옵트인 |
| Run-time 로그 | 항상 출력 | 결과 jsonl 옆에 정책 추적 가능 |

### 검증

```bash
/usr/bin/python3.12 -m pytest evaluation/retrieval_agent/ scripts/ -v
# → 190 passed
```

### Out of scope

- Answer prompt 정렬 (v2 §2 잔여 항목) 그대로 미해결.
- `generate_scores.py` macro / abstention metric 추가 미진행.
- `create_judge_fn` C901 complexity 경고 미해결.
