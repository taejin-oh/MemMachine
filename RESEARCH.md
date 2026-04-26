# Phase 0 — 평가 코드 조사 보고서

작성일: 2026-04-26
범위: `evaluation/retrieval_agent/*`, `evaluation/utils/*`
목적: 6개 우선 문제(#2/#3/#4/#5/#6/#12) 재현 도구 MVP 설계 전 코드 실태 파악
원칙: 추측 금지. 모든 답변은 파일:라인 인용. 직접 확인하지 못한 항목은 `[unverified]` 태그.

---

## 0. 파일 인벤토리

### evaluation/retrieval_agent/

```
README.md
cli_utils.py
evaluate.py
generate_scores.py
hotpotQA_test.py
llm_judge.py
locomo_delete.py
locomo_ingest.py
locomo_search.py
longmemeval_test.py
preflight.py
requirements.txt
run_benchmark_matrix.sh
run_test.sh
test_benchmark_concurrency.py
test_llm_judge.py
test_locomo_search.py
test_preflight.py
test_run_test.py
wikimultihop_delete.py
wikimultihop_ingest.py
wikimultihop_search.py
```

### evaluation/utils/

```
agent_utils.py
atf_helper.py
memmachine_helper.py
memmachine_helper_base.py
memmachine_helper_db.py
memmachine_helper_restapiv1.py
memmachine_helper_restapiv2.py
```

---

## Q1. 5단계 (ingest / retrieve / generate / judge / analyze) 매핑

| 단계 | 함수 | 파일:라인 | 한 줄 설명 |
|---|---|---|---|
| ingest | `longmemeval_ingest()` | `evaluation/retrieval_agent/longmemeval_test.py:144` | LongMemEval 데이터셋 로드, chunk 분할, Episode 객체 생성, `memory.add_memory_episodes()` 호출 |
| ingest | `hotpotqa_ingest()` | `evaluation/retrieval_agent/hotpotQA_test.py:62` | HotpotQA context sentences 추출·shuffle·batch, `memory.add_memory_episodes()` |
| ingest | `process_conversation()` | `evaluation/retrieval_agent/locomo_ingest.py:58` | LoCoMo 세션별 대화 처리, speaker/timestamp 포함 episode 추가 |
| retrieve | `query_agent.do_query()` | 호출부 `evaluation/utils/agent_utils.py:79` | `(chunks, perf_metrics)` 반환 |
| generate | `answer_model.generate_response()` | 호출부 `evaluation/utils/agent_utils.py:99` | `(rsp_text, _)` 반환 |
| judge | `evaluate_llm_judge()` | `evaluation/retrieval_agent/llm_judge.py:139` | `ACCURACY_PROMPT` 로 LLM judge 호출, `1` (CORRECT) / `0` (WRONG) 반환 |
| judge | `evaluate.py` 메인 루프 | `evaluation/retrieval_agent/evaluate.py:25` | 결과 JSON 읽고 sample 별 `evaluate_llm_judge()` 호출, `llm_score` 필드 추가 |
| analyze | `update_final_attribute_matrix()` | `evaluation/utils/agent_utils.py:259` | recall/precision/token/timing 집계, per-tool breakdown 포함 |
| analyze | `generate_scores.py` | `evaluation/retrieval_agent/generate_scores.py:9` | category 별 평균 점수 출력 |

---

## Q2. retrieve 와 generate 결합 여부

**결론: 결합되어 있으나 분리 wrap 가능. `process_question()` 수정 불필요.**

`process_question()` (`evaluation/utils/agent_utils.py:57-129`) 안에서 두 호출이 차례로 발생:

- line 79-89: `chunks, perf_metrics = await query_agent.do_query(QueryPolicy(...), QueryParam(query=question, limit=search_limit, memory=memory))`
- line 99: `rsp_text, _ = await answer_model.generate_response(user_prompt=prompt)`

그러나 `query_agent` 와 `answer_model` 객체는 외부에서 주입되며, `init_memmachine_params()` (`evaluation/utils/agent_utils.py:383-469`) 가 `(memory, answer_model, query_agent)` 튜플을 반환한다. 따라서 우리 wrapper 가 두 메서드를 직접 따로 호출하면 분리 가능하다 — `process_question()` 자체는 read-only 로 두면 된다.

분리 시 새로 만들어야 하는 것: prompt 포맷팅 로직 (line 96 `answer_prompt.format(memories=..., question=...)`) 정도 — 약 10 줄. 큰 리팩터링 불필요.

---

## Q3. `run_benchmark_matrix.sh` 존재 여부 + chunk × prefix × k 매트릭스

**존재함**: `evaluation/retrieval_agent/run_benchmark_matrix.sh`

루프 구조 (line 201-227):

```bash
LONGMEM_K_VALUES=(10 20 30 50 100)        # line 15
LONGMEM_PREFIX_VALUES=(off on)             # line 16
LONGMEM_CHUNK_VALUES=(off on)              # line 17

for chunk in "${LONGMEM_CHUNK_VALUES[@]}"; do
    set_longmemeval_chunking "$chunk"
    for prefix in "${LONGMEM_PREFIX_VALUES[@]}"; do
        set_longmemeval_prefix "$prefix"
        for k in "${LONGMEM_K_VALUES[@]}"; do
            postfix="lmes_chunk${chunk}_${prefix}_k${k}"
            run_cmd "$RUN_TEST" longmemeval "$postfix" search "$LONGMEM_SPLIT" \
                    "$LONGMEM_TARGET" "$LONGMEM_LENGTH" --search-limit "$k"
        done
    done
done
```

LoCoMo / HotpotQA 도 line 229-249 에서 별도 sweep.

알려진 한계: chunk 잔류 버그 — LongMemEval 루프 종료 시 `chunk=on` 잔류 → 후속 LoCoMo/HotpotQA 가 chunk=on 조건에서 실행됨 (`docs/msr/MemMachine_재현평가_설계_0425.md` §5.0 #3 참조).

---

## Q4. `prepend_user_prefix` 토글

**YAML key**: `evaluation.longmemeval.prepend_user_prefix`

**읽는 곳** (`evaluation/retrieval_agent/longmemeval_test.py:62-82`):

```python
def _load_longmemeval_question_prefix_enabled(config_path: str) -> bool:
    config_file = Path(config_path)
    with config_file.open("r", encoding="utf-8") as file:
        raw_conf = yaml.safe_load(file) or {}
    evaluation_conf = raw_conf.get("evaluation", {})
    longmemeval_conf = evaluation_conf.get("longmemeval", {})
    return bool(longmemeval_conf.get("prepend_user_prefix", False))
```

**적용 곳** (`evaluation/retrieval_agent/longmemeval_test.py:224-231`):

```python
prepend_user_prefix = _load_longmemeval_question_prefix_enabled(config_path)
for sample in dataset:
    question = str(sample.get("question", "")).strip()
    if prepend_user_prefix:
        question = f"User: {question}"
```

**셸 스크립트에서 토글 변경** (`evaluation/retrieval_agent/run_benchmark_matrix.sh:113-147`): `set_longmemeval_prefix()` 가 `configuration.yml` 을 in-place 편집해 `evaluation.longmemeval.prepend_user_prefix: true|false` 갱신.

---

## Q5. HotpotQA `length=500` 선정 방식

**방식**: split 의 첫 N 개 (sequential, no random, no seed)

**코드 인용** (`evaluation/retrieval_agent/hotpotQA_test.py:209-216`):

```python
def load_hotpotqa_dataset(length: int, split: str) -> list[dict[str, any]]:
    from datasets import load_dataset
    dataset = load_dataset("hotpot_qa", "distractor", split=split)
    data = dataset.select(range(length)).to_list()  # <- 첫 length 개
    return data
```

`length=500` 은 `run_benchmark_matrix.sh:19` 의 `HOTPOT_LENGTH=500` 으로 설정되어 line 244 `--length "$HOTPOT_LENGTH"` 로 전달. seed 없음. paper 의 "hard 500" 과의 동일성은 v0.2 의 운영 결정으로 채택 (`docs/msr/20260425_modified_list_v0.2.md:33`).

---

## Q6. `evaluate.py` 와 `llm_judge.py` 의 입출력 JSON 스키마

### evaluate.py 가 읽는 입력 (search 단계 산출물)

`evaluation/retrieval_agent/evaluate.py:25-55` 기준:

```python
# 필수 입력 필드
{
    "question": str,
    "golden_answer": str,    # line 27
    "model_answer": str,     # line 28
    "category": str,
}
```

### evaluate.py 가 쓰는 출력 (judge 산출물)

```python
# 출력 (입력 필드 그대로 + 다음 추가)
{
    ...all input fields...,
    "llm_score": int,        # 1 (CORRECT) | 0 (WRONG), line 42
}
```

### llm_judge.py 내부

`evaluation/retrieval_agent/llm_judge.py:139-185` 의 `evaluate_llm_judge()` 가 LLM 호출:

- 입력 prompt: `ACCURACY_PROMPT.format(question=..., gold_answer=..., model_answer=...)`
- LLM 응답 파싱 (line 165-170): `{"label": "CORRECT" | "WRONG"}`
- 변환 (line 174): `1 if label == "CORRECT" else 0`

---

## 추가 발견 항목

### test_target 토글 — 이미 존재

`evaluation/retrieval_agent/longmemeval_test.py:369-372` (다른 *_test.py 도 동일 패턴):

```python
parser.add_argument(
    "--test-target",
    required=True,
    choices=["memmachine", "retrieval_agent", "llm"],
    help="Testing with memmachine(bypass agent), retrieval_agent, or pure llm",
)
```

agent 선택 (line 421-429):

```python
agent_name = (
    "MemMachineAgent" if args.test_target == "memmachine" else "ToolSelectAgent"
)
await longmemeval_search(..., agent_name, args.test_target == "llm", ...)
```

→ 우리 도구는 이 옵션을 그대로 노출하면 된다. 새 토글 정의 불필요.

### DB 연결 설정 위치

- `configuration.yml` 의 `episodic_memory.long_term_memory.vector_graph_store` 에 store ID
- ResourceManager (`memmachine_server/common/resource_manager/`) 가 ID → host/port 매핑 보유 — `[unverified]` 정확한 위치는 본 조사 범위 밖
- `init_memmachine_params()` 가 `resource_manager.get_vector_graph_store(id)` 로 인스턴스 획득 (`evaluation/utils/agent_utils.py:429-431`)

→ 우리 도구는 `configuration.yml` 의 vector_graph_store / embedder / reranker / llm_model ID 만 읽거나 생성하면 됨. 실제 호스트 값은 ResourceManager 가 처리.

### LLM / embedding / reranker 모델 ID 위치 (`configuration.yml` 키)

- Embedder: `episodic_memory.long_term_memory.embedder` (`agent_utils.py:408-412`)
- Reranker: `retrieval_agent.reranker` (fallback `episodic_memory.long_term_memory.reranker`) (`agent_utils.py:415-420`)
- LLM (agent + answer + judge 공유): `retrieval_agent.llm_model` (`agent_utils.py:433-435`, `llm_judge.py:60`)

### 결과 파일 경로 (기존 코드)

`evaluation/retrieval_agent/run_test.sh:415-419`:

```
result/{TEST}_{TEST_TARGET}_output_{RESULT_POSTFIX}.json
result/{TEST}_{TEST_TARGET}_evaluation_metrics_{RESULT_POSTFIX}.json
result/final_score/{TEST}_{TEST_TARGET}_{RESULT_POSTFIX}.result
result/ingest_status/{TEST}_{TEST_TARGET}_{RESULT_POSTFIX}.json
```

`run_benchmark_matrix.sh:87`: `result/matrix_run_{TIMESTAMP}.log`

→ 우리 도구는 별도 경로 `results/{run_name}/{stage}.jsonl` 사용 (기존 경로 충돌 회피).

### `--skip-ingest` 플래그

`run_benchmark_matrix.sh:10, 36, 47-50, 219-223` 에만 존재. `run_test.sh` 에는 없음.

```bash
if [ "$SKIP_INGEST" = false ]; then
    run_cmd "$RUN_TEST" longmemeval "$postfix" ingest ...
else
    log_summary "[SKIP] ingest longmemeval ${postfix}"
fi
```

→ 우리 도구는 동일 의미를 `--stage` 인자로 표현 (ingest 단계만 빼고 실행).

### 재현성 (seed) 파라미터

- Python 코드에 명시적 `random.seed()` / 명시적 dataset seed 호출 **없음**
- HotpotQA: `random.shuffle(all_content)` (`hotpotQA_test.py:89`) — unseeded
- LongMemEval: shuffle 없음, `dataset.select(range(n))`
- LoCoMo: `[unverified]` 별도 세부 조사 안 함

→ 본 도구가 새 seed 인자를 도입하더라도 기존 코드 호출 경로를 read-only 로 유지하려면 **기존 코드에 seed 주입 불가**. 단, `random.seed()` 를 stage 시작 시 monkey-call 은 할 수 있음 (process 전역 영향).

### sentence chunking 제어

- YAML key: `episodic_memory.long_term_memory.message_sentence_chunking` (`agent_utils.py:441`)
- kwarg override: `init_memmachine_params(..., message_sentence_chunking=...)` (`agent_utils.py:387-388`, `440-455`)
- 셸 토글: `set_longmemeval_chunking()` (`run_benchmark_matrix.sh:150-184`)

---

## 입력 문서 ↔ 코드 정합 결론

`docs/msr/20260425_modified_list_v0.2.md` 의 ✅ 6개 항목, ❌ 5개 항목 모두 코드 실태와 일치한다 (`docs/msr/20260425_eval_code_review.md` §0 의 코드 검증과 동일 결론).

두 입력 문서 (`MemMachine_재현평가_설계_0425.md`, `20260425_modified_list_v0.2.md`) 사이에 충돌 없음.

→ 추가 사용자 질문 사유 없음. 곧바로 설계 단계 진행.
