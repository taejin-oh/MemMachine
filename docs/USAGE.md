# MemMachine 재현 평가 도구 사용법

PR #7 eval-tool 은 기존 `evaluation/retrieval_agent/*` 코드를 read-only 로 wrap 하는 **MVP 재현 평가 도구**입니다. 이 문서는 실행 절차만 다룹니다. 각 문제의 의미·판정 기준은 `docs/msr/MemMachine_재현평가_설계_0425.md` 참조.

> **이 도구의 범위 (요약)**
>
> - paper exact reproduction 이 아닙니다. JSON-str 등 일부 운영점은 paper 조건과 다르므로 결과는 **operational reproduction / extrapolation** 으로 해석.
> - **EDWIN1 / EDWIN3 prompt** 는 hook 자리만 있고 실제 적용 로직은 미구현 (`DECISIONS.md` D-003). 답변 prompt 는 기본 ANSWER_PROMPT 사용.
> - **n_runs** 는 1 만 지원. `n_runs > 1` 이면 `run_pipeline.py` 가 명시적으로 `NotImplementedError`. σ×2 자동 판정 / 파일럿 wrapper 는 future work.
> - **seed 옵션 없음**. 데이터셋 순서·shuffle 은 기존 코드 동작 그대로.
> - **DB / LLM** 인스턴스는 사용자가 직접 띄워야 합니다 (Postgres + Neo4j + LLM API key).
> - `mode=existing` 도 사용자 원본 `configuration.yml` 을 직접 수정하지 않고, run 마다 working copy 를 만들어 그것만 수정합니다.

---

## 1. 빠른 시작

```sh
# 0. (한 번만) 모델·DB profile placeholder 채우기
cp configs/profiles/models/_example.yaml configs/profiles/models/my_model.yaml
cp configs/profiles/dbs/_example.yaml     configs/profiles/dbs/my_db.yaml
# 두 파일의 <PLACEHOLDER> 를 본인 환경값으로 편집 (host/port/api_key 등)

# 1. run config 생성 — 예: 문제 #4, k=10/20 만 작은 dry-run
python scripts/generate_config.py \
    --problem 4 --run-name p4_pilot \
    --model-profile my_model --db-profile my_db \
    --k-list 10,20 --length 5

# 2. 전체 파이프라인 실행
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage all

# 3. 결과 확인
ls results/p4_pilot/
cat results/p4_pilot/analyze.json
```

---

## 2. 사전 준비

### 2.1 DB 인스턴스 (사용자 책임)

본 도구는 DB 를 띄우지 않습니다. Postgres + Neo4j 를 별도로 (Docker 등) 띄우고 host/port/계정을 profile YAML 에 적습니다. repo 의 `docker-compose.yml` 또는 `deployments/helm/` 참고.

### 2.2 모델·DB profile

| 복사 원본 | 복사 대상 | 필수 편집 |
|---|---|---|
| `configs/profiles/models/_example.yaml` | `configs/profiles/models/{이름}.yaml` | embedder / reranker / llm_model 의 `provider`·`config` |
| `configs/profiles/dbs/_example.yaml`    | `configs/profiles/dbs/{이름}.yaml`    | vector_graph_store / profile_storage 의 `config` |

`{이름}` 을 `--model-profile` / `--db-profile` 에 넘깁니다.

### 2.3 (선택) 기존 configuration.yml 재사용

자체 `configuration.yml` 이 있으면 profile 조합 대신 그걸 쓸 수 있습니다. 사용자 원본은 수정되지 않고 working copy 가 `configs/generated/{run}_configuration.yml` 에 만들어집니다.

```sh
python scripts/generate_config.py \
    --problem 4 --run-name p4_existing \
    --use-existing-config /path/to/your/configuration.yml \
    --k-list 10,20
```

---

## 3. 6개 문제별 실행 예시

각 명령은 placeholder profile (`my_model`, `my_db`) 을 본인 것으로 교체하세요.

### #2 — HotpotQA Memory vs Agent

```sh
python scripts/generate_config.py --problem 2 --run-name p2_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p2_full.yaml --stage all
```

### #3 — LongMemEval user prefix on/off

```sh
python scripts/generate_config.py --problem 3 --run-name p3_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p3_full.yaml --stage all
```

### #4 — LongMemEval k sweep

기본 k = 10/20/30/50/100:

```sh
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage all
```

> **주의 — chunk on/off 비교**: `message_sentence_chunking` 은 ingest 시 DB 에 적재되는 episode 구조에 영향을 줍니다. 따라서 chunk on/off 비교는 같은 run 에서 retrieve sweep 만 바꾸지 말고, **chunk 값별로 별도 `run_name` 을 사용해 ingest 부터 다시 실행**하세요. 기본 p4 run 은 chunk=on, prefix=on, k sweep 입니다.

### #5 — LoCoMo Memory vs Agent

LoCoMo 는 데이터 JSON 경로가 필요합니다 (subprocess 로 `locomo_search.py` 호출).
`p5.yaml` 에 `benchmark.data_path: evaluation/data/locomo10.json` 기본값이 들어있어
별도 수정 없이도 `--stage all` 이 바로 동작합니다 — 다른 위치의 LoCoMo JSON 을
쓰려면 run YAML 의 `benchmark.data_path` 만 절대경로 또는 repo-root 기준 상대경로로
덮어쓰면 됩니다.

```sh
python scripts/generate_config.py --problem 5 --run-name p5_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p5_full.yaml --stage all
```

> **참고 — p5 처리 범위**: `locomo_search.py` / `locomo_ingest.py` 는 `--length N` 옵션으로 처리할 conversation group 수를 받습니다. p5.yaml 의 `benchmark.length` (기본 10 — `locomo10.json` 전체) 를 통해 wrapper subprocess 가 자동으로 `--length` 를 전달하며, `python scripts/generate_config.py --length N` 으로 override 가능합니다.
>
> **주의 — p5 search_limit**: `locomo_search.py:207` 에서 `search_limit=20` 이 하드코드되어 있습니다. run YAML 의 `fixed.search_limit` 을 바꿔도 LoCoMo subprocess 경로에는 반영되지 않습니다.

### #6 — Multi-session 재분해 (#4 결과 재사용)

```sh
python scripts/generate_config.py --problem 6 --run-name p6_from_p4 \
    --model-profile my_model --db-profile my_db --reuse-run p4_full
python scripts/run_pipeline.py --config configs/runs/p6_from_p4.yaml \
    --stage analyze --decompose-multisession
```

### #12 — k 비용 vs 정확도 Pareto (#4 결과 재사용)

```sh
python scripts/generate_config.py --problem 12 --run-name p12_from_p4 \
    --model-profile my_model --db-profile my_db --reuse-run p4_full
python scripts/run_pipeline.py --config configs/runs/p12_from_p4.yaml \
    --stage analyze --pareto
```

`--pareto` 출력의 각 cell 에는 `accuracy / mean_recall / overall_recall / mean_tokens_per_query / mean_input_token / mean_output_token / mean_num_episodes / mean_llm_time` 가 포함됩니다.

---

## 4. 단계 단위 / 단계 조합

```sh
# ingest 만 (DB 적재 — 가장 비싼 단계, 한 번만 권장. ingest.jsonl 이 ok 면 자동 skip)
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage ingest

# retrieve + generate (한 loop 산출 — DECISIONS.md D-005)
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage retrieve

# judge / analyze 단독
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage judge
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage analyze

# 부분 조합
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage retrieve,judge,analyze
```

각 stage 산출:

| stage | 파일 | 비고 |
|---|---|---|
| ingest | `results/{run}/ingest.jsonl` | 한 줄 status. 이미 ok 면 skip |
| retrieve | `results/{run}/retrieve.jsonl` | 질문별 chunks + perf + token + fact_hits/miss |
| generate | `results/{run}/generate.jsonl` | 질문별 model_answer (retrieve 와 동일 loop 산출) |
| judge | `results/{run}/judge.jsonl` | generate.jsonl + `llm_score` |
| analyze | `results/{run}/analyze.json` | cell 별 accuracy / recall / token / per-tool / Pareto |

---

## 5. JSON override

복잡한 설정은 JSON 으로 한 번에. `configs/runs/_example.json` 시작점.

```sh
python scripts/generate_config.py --from-json configs/runs/_example.json
```

CLI 인자와 JSON 이 충돌하면 CLI 가 우선.

---

## 6. 자주 묻는 질문

**Q1. DB 주소를 바꿨어요.**
→ `configs/profiles/dbs/{이름}.yaml` 수정 후 `generate_config.py` 재실행. 새 working copy 가 `configs/generated/{run}_configuration.yml` 에 생성됨.

**Q2. 답변 LLM 만 바꾸고 싶어요.**
→ `configs/profiles/models/{이름}.yaml` 의 `llm_model` 섹션만 수정 후 새 profile 이름으로 저장 (예: `my_model_v2.yaml`), `generate_config.py --model-profile my_model_v2` 로 새 run 생성.

**Q3. ingest 결과를 다른 run 에서 재사용할 수 있나요?**
→ 같은 DB 인스턴스 + 같은 `session_id` 면 자동 재사용. session_id = `eval_tool_{benchmark}_{run_name}`. 같은 run_name 으로 재실행 시 `ingest.jsonl` 이 ok 면 ingest 자동 skip.

**Q4. EDWIN1 / EDWIN3 prompt 는 어떻게 적용하나요?**
→ 현 PR 에서는 placeholder + hook 자리만 있고 실제 적용 미구현 (`DECISIONS.md` D-003). 답변 prompt 는 기본 ANSWER_PROMPT 사용. EDWIN 텍스트 확보 시 `prompts/EDWIN{1,3}.txt` 에 저장하고 `scripts/stages/generate.py` 의 hook 에 적용 코드 추가하면 됩니다.

**Q5. judge LLM 을 답변 LLM 과 다르게 쓰고 싶어요.**
→ 두 가지 경로가 있습니다.

1. **별도 provider / base_url / api_key / model 로 judge 를 띄우려면** model profile 에 optional `judge_llm:` 블록을 추가하세요 (`configs/profiles/models/_example.yaml` 의 주석 처리된 예시 참고). `generate_config.py` 가 이를 `resources.language_models` 에 별도 entry 로 등록하고, working `configuration.yml` 의 `retrieval_agent.judge_llm_model` 에 그 ID 를 연결합니다. `judge_llm.provider` 는 `openai-responses` / `openai-chat-completions` / `amazon-bedrock` 중 하나여야 합니다.
2. **이미 등록된 다른 ID 로 pointer 만 swap 하려면** `generate_config.py --judge-model {ID}` 를 쓰세요 (또는 run YAML 에 `judge.llm_model_id` 를 직접 적어도 됩니다). judge 단계가 임시 사본에서 `retrieval_agent.judge_llm_model` 만 그 ID 로 바꾸며, `retrieval_agent.llm_model` (답변 LLM) 은 절대 건드리지 않습니다. 미정의 ID 면 명시적 에러.

`judge_llm:` 도 `--judge-model` 도 없으면 judge 는 `retrieval_agent.llm_model` 로 fallback 하므로 기존 프로파일은 그대로 동작합니다.

**Q6. 반복 실행 (N runs) / 자동 판정?**
→ 현재 `n_runs=1` 만 지원. `n_runs > 1` 면 `NotImplementedError`. σ×2 자동 판정 / 파일럿 wrapper 는 future work.

**Q7-1. LongMemEval answer prompt 정책을 어떻게 고르나?**
→ v0.6 부터 3가지 정책 중 선택 가능. **default 는 `LME_origin_prompt`** (xiaowu0162/LongMemEval upstream verbatim) — 별도 옵트인 없으면 이 정책이 사용됨:

| 정책 | 본문 | 사용 시점 |
|---|---|---|
| `LME_origin_prompt` (default) | xiaowu0162/LongMemEval upstream verbatim 본문 (no-merge no-CoT 분기, placeholder 만 named 로 변환) | **default**. upstream 논문 baseline 과 직접 비교 |
| `memmachine_original` | 하이브리드 — episodic_memory 변형 (KNOWLEDGE UPDATES + PLANNED ACTIONS 추론 가이드) + 원본 구조 정렬(memory-only / Current Date / no length cap) | MemMachine 의 추론 가이드를 활용한 평가 |
| `agent_lightning` | v0.5 까지 사용한 Agent Lightning paper(arXiv:2508.03680) prompt 그대로 | v0.5 baseline 과 1:1 비교 |

다른 정책으로 옵트인하는 방법 (예: `memmachine_original` 으로 하이브리드 본문 사용):

1. **CLI**: `python scripts/generate_config.py ... --longmemeval-answer-prompt memmachine_original`. `evaluation.longmemeval.answer_prompt` 가 run yaml 에 박힘.
2. **run yaml 직접 편집**: `evaluation: { longmemeval: { answer_prompt: memmachine_original } }`.
3. **configuration.yml 영구 변경**: `retrieval_agent.longmemeval_answer_prompt: memmachine_original`.

우선순위는 (run_cfg) > (configuration.yml) > (Pydantic default `LME_origin_prompt`). legacy 진입점 (`evaluation/retrieval_agent/longmemeval_test.py`) 도 `--longmemeval-answer-prompt` 플래그를 받으며 미지정 시 같은 폴백 체인을 따름. 두 진입점 모두 실행 시점에 `[longmemeval]/[retrieve] longmemeval_answer_prompt=...` 로그를 남깁니다.

**Q7. 같은 DB 에서 p2 / p5 를 여러 번 돌려도 되나요?**
→ 주의 필요. LongMemEval 은 PR #7 wrapper 의 `eval_tool_longmemeval_{run_name}` session_id 를 사용하므로 run 간 격리됩니다. 그러나 **HotpotQA (p2) 는 upstream 코드가 `hotpotqa_group` 으로 고정**, **LoCoMo (p5) 는 `group_{idx}` 로 고정**됩니다. 같은 DB 에서 p2 / p5 를 여러 번 실행하면 이전 run 의 episode 와 새 run 의 episode 가 섞일 수 있습니다. p2/p5 반복 시에는 HotpotQA 의 경우 `evaluation/retrieval_agent/hotpotQA_test.py --run-type delete --config-path <configuration.yml> --test-target memmachine` (또는 모듈 함수 `hotpotqa_delete(config_path)`) 를, LoCoMo 의 경우 `evaluation/retrieval_agent/locomo_delete.py` 를 호출해 정리하거나 별도 DB 를 사용하세요. `--test-target` 은 delete 동작 자체에 영향이 없지만 argparse 가 `required=True` 라 예시값을 지정합니다. 자동화는 `docs/msr/msr_eval_tool_todo_pr7.md` 의 future work.

---

## 7. 검증된 smoke (DB / LLM 없이 동작 확인)

```sh
# config 생성
python scripts/generate_config.py --problem 4 --run-name p4_pilot_5q \
    --model-profile _example --db-profile _example --k-list 10,20 --length 5
# → run config + working configuration.yml 생성 OK

# analyze 단계 (합성 judge.jsonl + retrieve.jsonl 로 검증)
python scripts/run_pipeline.py --config configs/runs/p4_pilot_5q.yaml \
    --stage analyze --decompose-multisession --pareto
# → cells / Pareto / per-tool breakdown 출력 OK
```

DB / LLM 환경이 준비된 사용자는 같은 절차로 `--stage all` 또는 단계 단위로 ingest / retrieve / judge 까지 실제 실행하면 됩니다.
