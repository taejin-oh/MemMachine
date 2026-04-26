# MemMachine 재현 평가 도구 사용법

작성일: 2026-04-26
대상: MemMachine 논문 6개 우선 문제(#2/#3/#4/#5/#6/#12) 재현 평가

이 문서는 도구 자체의 사용법만 다룹니다. 각 문제의 의미와 판정 기준은 `docs/msr/MemMachine_재현평가_설계_0425.md` 를 참조하세요.

---

## 1. 빠른 시작

```sh
# 0. (한 번만) 모델·DB profile placeholder 채우기
cp configs/profiles/models/_example.yaml configs/profiles/models/my_model.yaml
cp configs/profiles/dbs/_example.yaml     configs/profiles/dbs/my_db.yaml
# my_model.yaml / my_db.yaml 의 <PLACEHOLDER> 를 실제 값으로 편집

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

본 도구는 DB 인스턴스를 띄우지 않습니다. Postgres + Neo4j 를 별도로 (Docker 등으로) 띄운 뒤, 그 host/port/계정을 profile YAML 에 적습니다.

repo 의 `docker-compose.yml` 또는 `deployments/helm/` 을 참고할 수 있습니다.

### 2.2 모델·DB profile 채우기

두 placeholder 파일을 복사해 본인 환경값으로 채웁니다:

| 복사 원본 | 복사 대상 | 필수 편집 항목 |
|---|---|---|
| `configs/profiles/models/_example.yaml` | `configs/profiles/models/{이름}.yaml` | embedder/reranker/llm_model 의 `provider`·`config` |
| `configs/profiles/dbs/_example.yaml`    | `configs/profiles/dbs/{이름}.yaml`    | vector_graph_store / profile_storage 의 `config` |

이 `{이름}` 을 `--model-profile` / `--db-profile` 인자에 넘깁니다.

### 2.3 (선택) 기존 configuration.yml 재사용

이미 자체 `configuration.yml` 이 있다면 profile 조합 대신 그 파일을 그대로 쓸 수 있습니다:

```sh
python scripts/generate_config.py \
    --problem 4 --run-name p4_existing \
    --use-existing-config /path/to/your/configuration.yml \
    --k-list 10,20
```

---

## 3. 6개 문제별 실행 예시

각 명령은 placeholder profile 이름 (`my_model`, `my_db`) 를 본인 것으로 교체하세요.

### #2 — Multi-hop retrieval failure (HotpotQA Memory vs Agent)

```sh
python scripts/generate_config.py --problem 2 --run-name p2_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p2_full.yaml --stage all
```

### #3 — User prefix 효과 (LongMemEval)

```sh
python scripts/generate_config.py --problem 3 --run-name p3_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p3_full.yaml --stage all
```

### #4 — k 비단조성 (LongMemEval k sweep)

기본 k 셋 (10/20/30/50/100) 그대로:

```sh
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage all
```

### #5 — Temporal reasoning (LoCoMo)

LoCoMo 는 데이터 파일 경로가 필요합니다. `run_pipeline.py` 가 subprocess 로 `locomo_search.py` 를 호출하므로, run YAML 의 `benchmark.data_path` 를 채워주세요.

```sh
python scripts/generate_config.py --problem 5 --run-name p5_full \
    --model-profile my_model --db-profile my_db
# 그런 다음 configs/runs/p5_full.yaml 을 열어 benchmark 섹션에
# data_path: /path/to/locomo10.json 추가
python scripts/run_pipeline.py --config configs/runs/p5_full.yaml --stage all
```

### #6 — Multi-session 재분해 (#4 산출물 재사용)

```sh
python scripts/generate_config.py --problem 6 --run-name p6_from_p4 \
    --model-profile my_model --db-profile my_db --reuse-run p4_full
python scripts/run_pipeline.py --config configs/runs/p6_from_p4.yaml \
    --stage analyze --decompose-multisession
```

### #12 — k 비용 vs 정확도 Pareto (#4 산출물 재사용)

```sh
python scripts/generate_config.py --problem 12 --run-name p12_from_p4 \
    --model-profile my_model --db-profile my_db --reuse-run p4_full
python scripts/run_pipeline.py --config configs/runs/p12_from_p4.yaml \
    --stage analyze --pareto
```

---

## 4. 단계 단위 / 단계 조합 실행

`--stage` 인자에 콤마로 stage 를 묶을 수 있습니다.

```sh
# ingest 만 (DB 적재. 가장 비싼 단계 — 한 번만 돌리는 게 좋음)
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage ingest

# retrieve + generate (한 loop 에서 함께 산출 — DECISIONS.md D-005 참조)
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage retrieve

# judge 만 (LLM judge 재호출)
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage judge

# 부분 조합
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage retrieve,judge,analyze
```

각 stage 의 산출 파일:

| stage | 산출 파일 | 비고 |
|---|---|---|
| ingest | `results/{run}/ingest.jsonl` | 한 줄 status. 이미 있으면 skip |
| retrieve | `results/{run}/retrieve.jsonl` | 질문별 chunks + perf |
| generate | `results/{run}/generate.jsonl` | 질문별 model_answer (retrieve 와 동일 loop 산출) |
| judge | `results/{run}/judge.jsonl` | generate.jsonl + `llm_score` |
| analyze | `results/{run}/analyze.json` | sweep cell 별 mean / std / category breakdown |

---

## 5. JSON override 사용

복잡한 설정을 JSON 으로 한 번에 줄 수 있습니다. `configs/runs/_example.json` 가 시작점입니다.

```sh
python scripts/generate_config.py --from-json configs/runs/_example.json
```

CLI 인자와 JSON 인자가 충돌하면 CLI 가 이깁니다.

---

## 6. 자주 묻는 질문

**Q1. DB 주소를 바꿨어요.**
→ `configs/profiles/dbs/{이름}.yaml` 의 `config` 섹션을 수정한 뒤 `generate_config.py` 를 다시 호출하세요. 새 `configs/generated/{run}_configuration.yml` 이 생성됩니다.

**Q2. 답변 LLM 만 바꾸고 싶어요.**
→ `configs/profiles/models/{이름}.yaml` 의 `llm_model` 섹션만 수정하고 새 profile 이름으로 저장 (예: `my_model_v2.yaml`), `generate_config.py --model-profile my_model_v2` 로 새 run 생성.

**Q3. ingest 결과를 다른 run 에서 재사용할 수 있나요?**
→ 같은 DB 인스턴스를 보고 같은 `session_id` 를 쓰면 자동 재사용됩니다. `session_id` 는 `eval_tool_{benchmark}_{run_name}` 으로 결정되므로, run_name 이 다르면 다른 session 입니다. 같은 run_name 으로 재실행하면 `ingest.jsonl` 이 이미 ok 상태이면 ingest 단계가 skip 됩니다.

**Q4. EDWIN1 / EDWIN3 prompt 는 어떻게 적용하나요?**
→ 현재는 자리만 마련해 두었고 실제 적용 로직은 비활성 상태입니다 (`DECISIONS.md` D-003). EDWIN 텍스트가 확보되면 `prompts/EDWIN1.txt` 또는 `prompts/EDWIN3.txt` 에 저장하고, `scripts/stages/generate.py` 에 prompt 적용 코드를 추가하면 됩니다.

**Q5. judge LLM 을 답변 LLM 과 다르게 쓰고 싶어요.**
→ 두 단계:
1. 모델 profile YAML (`configs/profiles/models/{이름}.yaml`) 의 `resources.language_models` 에 judge 모델을 ID 로 추가 — 본 도구의 profile YAML 은 단일 `llm_model` 만 갖지만, judge LLM 을 별도로 등록하려면 `mode: existing` 으로 직접 만든 `configuration.yml` 을 사용하시거나, 또는 profile 의 `llm_model` ID 와 별도로 `judge_llm` 을 추가하는 식으로 사용자가 `configuration.yml` 을 수정해야 합니다 (현 placeholder profile 은 model 1개 기준).
2. `--judge-model {그 ID}` 인자를 `generate_config.py` 에 넘기면, judge 단계에서 `retrieval_agent.llm_model` 을 그 ID 로 swap 한 임시 `configuration.yml` 을 생성해 사용합니다. ID 가 `resources.language_models` 에 없으면 명시적으로 에러를 냅니다.

**Q6. 반복 실행 (N runs) 은요?**
→ run YAML 의 `n_runs` 키가 있지만 현재 stage 모듈은 1회 실행만 수행합니다 (DECISIONS.md D-001 / 설계 §3.5 fallback). σ×2 자동 판정과 wrapper 는 향후 작업입니다.

---

## 7. 검증된 명령 (이 문서 작성 시 실제 실행)

다음 명령들은 작성 시점에 실제 실행되어 동작이 확인되었습니다 (DB / LLM 이 필요한 단계는 가짜 데이터로 검증):

```sh
# config 생성 — 동작 확인
python scripts/generate_config.py --problem 4 --run-name p4_pilot_5q \
    --model-profile _example --db-profile _example --k-list 10,20 --length 5
# 출력:
#   [ok] run config: configs/runs/p4_pilot_5q.yaml
#   [ok] configuration.yml: configs/generated/p4_pilot_5q_configuration.yml

# analyze 단계 (가짜 judge.jsonl 로 검증) — 동작 확인
python scripts/run_pipeline.py --config configs/runs/p4_pilot_5q.yaml \
    --stage analyze --decompose-multisession --pareto
# 출력:
#   [analyze] ok → results/p4_pilot_5q/analyze.json  cells=2
```

DB / LLM 이 실제 환경에 있는 사용자는 동일 절차로 ingest / retrieve / judge 단계를 추가 실행하면 됩니다.
