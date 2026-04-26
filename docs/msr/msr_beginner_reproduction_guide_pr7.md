# MSR Beginner Reproduction Guide for PR #7

작성일: 2026-04-26  
대상: PR #7 eval-tool (`scripts/` + `configs/` 기반 MVP wrapper)  
목적: MemMachine을 처음 써보는 사용자도 6개 재현 평가(#2/#3/#4/#5/#6/#12)를 실행하고, 각 동작의 의미를 이해할 수 있도록 안내한다.

---

## 0. 이 문서의 위치와 역할

이 문서는 다음 문서들을 초보자 관점으로 다시 묶은 실행 가이드다.

- 실행 명령: `docs/USAGE.md`
- 평가 설계/수치/해석 기준: `docs/msr/MemMachine_재현평가_설계_0425.md`
- 구현 상태: `docs/msr/20260425_modified_list_v0.2.md`
- 후속 코드 수정 TODO: `docs/msr/msr_eval_tool_todo_pr7.md`

이 문서는 “논문 결과를 100% 동일하게 재현하는 방법”이 아니다. PR #7 도구는 기존 `evaluation/retrieval_agent/*` 코드를 read-only로 감싼 MVP 평가 도구이며, 결과는 **paper exact reproduction**이 아니라 **operational reproduction / extrapolation**으로 해석해야 한다.

---

## 1. 먼저 알아야 할 용어

| 용어 | 쉬운 설명 |
|---|---|
| LLM | 질문을 읽고 답변을 생성하는 언어 모델. 예: GPT 계열, 사내 오픈 LLM 등 |
| Embedding | 문장/메모리를 숫자 벡터로 바꿔 비슷한 내용을 찾을 수 있게 하는 과정 |
| Reranker | 검색된 후보 중 더 관련 있는 것을 다시 정렬하는 모델 |
| DB | MemMachine이 memory episode와 vector/graph 정보를 저장하는 저장소. 이 도구에서는 Postgres + Neo4j 사용 |
| Episode | MemMachine에 저장되는 한 조각의 대화/문서 기억 |
| Ingest | 데이터셋을 읽어서 MemMachine DB에 episode로 적재하는 단계 |
| Retrieve | 질문을 넣고 관련 memory episode를 검색하는 단계 |
| Generate | 검색된 memory를 바탕으로 답변을 생성하는 단계. PR #7에서는 retrieve와 같은 loop에서 같이 수행됨 |
| Judge | 생성된 답변이 정답과 맞는지 LLM judge로 채점하는 단계 |
| Analyze | judge/retrieve 결과를 모아 accuracy, recall, token, latency 등을 집계하는 단계 |
| k / search_limit | 질문당 몇 개의 memory episode를 가져올지 정하는 값. k가 클수록 더 많이 가져오지만 잡음도 늘 수 있음 |
| Token | LLM이 읽고 쓰는 텍스트 단위. token이 많을수록 비용/latency가 증가할 수 있음 |
| session_id | DB 안에서 실험 데이터를 구분하는 이름. 같은 session_id를 쓰면 데이터가 섞일 수 있음 |

---

## 2. 전체 실행 흐름

PR #7 평가 도구는 아래 5단계 pipeline을 사용한다.

```text
1. ingest   → 데이터셋을 DB에 넣음
2. retrieve → 질문별로 관련 memory를 검색함
3. generate → 검색 결과를 바탕으로 답변을 생성함
4. judge    → 답변을 정답과 비교해 점수를 매김
5. analyze  → 결과를 cell별/문제별로 집계함
```

실제 명령은 보통 아래 두 단계로 진행한다.

```sh
# 1) run config 생성
python scripts/generate_config.py --problem <문제번호> --run-name <run_name> \
    --model-profile <model_profile> --db-profile <db_profile>

# 2) pipeline 실행
python scripts/run_pipeline.py --config configs/runs/<run_name>.yaml --stage all
```

결과는 아래 위치에 생성된다.

```text
results/<run_name>/
  ingest.jsonl
  retrieve.jsonl
  generate.jsonl
  judge.jsonl
  analyze.json
```

---

## 3. 최초 1회 준비

### 3.1 모델 profile 준비

`configs/profiles/models/_example.yaml`을 복사해서 본인 환경에 맞게 수정한다.

```sh
cp configs/profiles/models/_example.yaml configs/profiles/models/my_model.yaml
```

수정해야 할 대표 항목:

```text
- embedder provider/config
- reranker provider/config
- llm_model provider/config
- API key 또는 endpoint
```

의미:

- embedder는 memory를 벡터로 바꾸는 역할
- reranker는 검색 후보를 다시 정렬하는 역할
- llm_model은 답변 생성과 agent 판단에 쓰이는 모델

### 3.2 DB profile 준비

`configs/profiles/dbs/_example.yaml`을 복사해서 Postgres/Neo4j 접속 정보를 채운다.

```sh
cp configs/profiles/dbs/_example.yaml configs/profiles/dbs/my_db.yaml
```

수정해야 할 대표 항목:

```text
- Postgres host / port / user / password / database
- Neo4j host / port / user / password
```

주의:

- 이 도구는 DB를 자동으로 띄우지 않는다.
- Postgres + Neo4j는 사용자가 Docker 등으로 먼저 띄워야 한다.
- 같은 DB를 여러 실험에 재사용할 때는 session isolation 주의가 필요하다. 특히 p2/p5는 아래 주의사항을 반드시 확인한다.

---

## 4. 문제별 재현 가이드

## #2 — HotpotQA Multi-hop retrieval failure

### 무엇을 보려는 평가인가?

한 번의 단순 검색으로 답하기 어려운 multi-hop 질문에서, 일반 Memory 모드와 Retrieval Agent 모드의 차이를 본다.

쉽게 말하면:

```text
질문 하나를 답하려면 여러 단서를 이어야 한다.
Memory만으로도 잘 찾는가?
아니면 Agent가 query를 나누거나 다시 검색해야 더 잘 찾는가?
```

### 실행 방법

```sh
python scripts/generate_config.py --problem 2 --run-name p2_full \
    --model-profile my_model --db-profile my_db

python scripts/run_pipeline.py --config configs/runs/p2_full.yaml --stage all
```

### 결과 확인

```sh
cat results/p2_full/analyze.json
```

주로 볼 항목:

```text
accuracy
mean_recall / overall_recall
tokens_per_query
by_tool breakdown
```

### 결과 해석

- Retrieval Agent가 Memory보다 accuracy/recall이 높으면 multi-hop 검색 보조 효과가 있다는 뜻
- token이 크게 늘면, 성능은 좋아져도 비용/latency가 증가할 수 있다는 뜻
- by_tool에서 ChainOfQuery/SplitQuery 사용 비중을 보면 어떤 agent 경로가 기여했는지 볼 수 있음

### 주의사항

HotpotQA는 기존 upstream 코드에서 `hotpotqa_group` session_id를 고정 사용한다. 따라서 같은 DB에서 p2를 여러 번 실행하면 데이터가 섞일 수 있다.

권장 운영:

```text
- p2는 fresh DB에서 실행하거나
- 실행 전 HotpotQA delete 경로로 기존 데이터를 지운 뒤 실행하거나
- 실험별로 별도 DB를 사용한다.
```

HotpotQA delete 예시:

```sh
python evaluation/retrieval_agent/hotpotQA_test.py \
    --run-type delete \
    --config-path <configuration.yml> \
    --test-target memmachine
```

`--test-target`은 delete 동작 자체에는 중요하지 않지만, argparse에서 required라 예시값을 넣는다.

---

## #3 — LongMemEval User/Assistant retrieval bias

### 무엇을 보려는 평가인가?

LongMemEval 질문 앞에 `User:` prefix를 붙이면 검색 품질이 달라지는지 본다.

쉽게 말하면:

```text
질문을 그냥 넣는 것보다
“User: 질문”처럼 말한 사람의 역할을 알려주면
MemMachine이 더 관련 있는 기억을 잘 찾는가?
```

### 실행 방법

```sh
python scripts/generate_config.py --problem 3 --run-name p3_full \
    --model-profile my_model --db-profile my_db

python scripts/run_pipeline.py --config configs/runs/p3_full.yaml --stage all
```

### 이 run에서 비교되는 조건

```text
prepend_user_prefix = false
prepend_user_prefix = true
```

### 결과 확인

```sh
cat results/p3_full/analyze.json
```

### 결과 해석

- prefix=true cell의 accuracy가 높으면, 질문 역할 정보가 retrieval에 도움이 된다는 뜻
- 차이가 작거나 반대면, 현재 환경에서는 prefix 효과가 약하거나 모델/데이터 조건이 논문과 다르다는 뜻

### 주의사항

논문 조건과 완전히 같지는 않다.

```text
- EDWIN1 prompt 실제 적용 없음
- JSON-str 조건 다름
- 따라서 C5/C6 exact reproduction이 아니라 user_q 효과 외삽 실험으로 해석
```

---

## #4 — LongMemEval k sweep / non-monotonicity

### 무엇을 보려는 평가인가?

검색 개수 k를 늘렸을 때 정확도가 계속 좋아지는지, 아니면 어느 순간 잡음 때문에 떨어지는지 본다.

쉽게 말하면:

```text
memory를 많이 가져오면 항상 좋은가?
아니면 너무 많이 가져오면 LLM이 헷갈리는가?
```

### 실행 방법

기본 k는 10/20/30/50/100이다.

```sh
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --model-profile my_model --db-profile my_db

python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage all
```

작은 dry-run 예시:

```sh
python scripts/generate_config.py --problem 4 --run-name p4_pilot_5q \
    --model-profile my_model --db-profile my_db \
    --k-list 10,20 --length 5

python scripts/run_pipeline.py --config configs/runs/p4_pilot_5q.yaml --stage all
```

### 결과 확인

```sh
cat results/p4_full/analyze.json
```

주로 볼 항목:

```text
cell별 accuracy
cell별 mean_recall / overall_recall
cell별 mean_tokens_per_query
cell별 mean_num_episodes
cell별 mean_llm_time
```

### 결과 해석

- k가 커질수록 accuracy가 증가하면, 더 많은 memory가 도움이 된다는 뜻
- k가 커져도 accuracy가 정체되면, retrieval depth 확장의 효율이 낮다는 뜻
- k가 커질수록 accuracy가 떨어지면, irrelevant context / lost-in-the-middle 문제가 의심됨
- token/latency가 증가하면, 성능 이득 대비 비용이 커지는지 같이 판단해야 함

### chunk on/off 주의

`message_sentence_chunking`은 retrieve 옵션이 아니라 ingest 때 DB에 저장되는 episode 구조에 영향을 준다.

따라서 chunk on/off를 비교하려면 아래처럼 별도 run으로 나눠야 한다.

```text
p4_chunk_on  → chunk=on config로 ingest부터 실행
p4_chunk_off → chunk=off config로 ingest부터 실행
```

같은 run에서 retrieve 단계만 chunk on/off로 바꾸면 올바른 비교가 아니다.

---

## #5 — LoCoMo Temporal reasoning weakness

### 무엇을 보려는 평가인가?

시간 추론 질문에서 MemMachine이 약한지 본다.

쉽게 말하면:

```text
“언제?”, “얼마나 지난 뒤?”, “먼저/나중에 무엇을 했나?” 같은 질문에서
Memory 모드와 Agent 모드가 어떻게 다른가?
Temporal category가 Single-hop보다 약한가?
```

### 실행 방법

LoCoMo는 데이터 JSON 경로가 필요하다.

```sh
python scripts/generate_config.py --problem 5 --run-name p5_full \
    --model-profile my_model --db-profile my_db
```

생성된 run YAML에 data_path를 추가한다.

```yaml
benchmark:
  name: locomo
  data_path: /absolute/path/to/locomo10.json
```

그 다음 실행한다.

```sh
python scripts/run_pipeline.py --config configs/runs/p5_full.yaml --stage all
```

### 결과 확인

```sh
cat results/p5_full/analyze.json
```

주로 볼 항목:

```text
category별 score
Temporal category score
Single-hop category score
Memory vs Retrieval Agent 차이
```

### 결과 해석

- Temporal 점수가 Single-hop보다 낮으면 시간 추론이 상대적으로 약하다는 뜻
- Retrieval Agent가 Memory보다 높으면 agent 경로가 시간 추론에도 도움이 될 수 있다는 뜻
- 차이가 작으면 현재 subset/model 조건에서는 시간 추론 약점이 뚜렷하지 않을 수 있음

### 주의사항

PR #7 p5는 기존 `locomo_search.py`를 subprocess로 호출한다. 따라서 upstream 코드의 제한을 그대로 따른다.

```text
- start_index=0 / end_index=20 제한을 따름
- cat5 제외 전체 1094 문항을 항상 보장하지 않음
- search_limit은 20으로 하드코드되어 있음
- run YAML에서 fixed.search_limit을 바꿔도 LoCoMo subprocess 경로에는 반영되지 않음
```

또한 LoCoMo는 `group_{idx}` session_id를 고정 사용하므로, 같은 DB에서 반복 실행하면 데이터가 섞일 수 있다. p5는 fresh DB, delete 후 실행, 또는 별도 DB 사용을 권장한다.

---

## #6 — Multi-session reasoning 재분해

### 무엇을 보려는 평가인가?

LongMemEval 안에서 Multi-session(MS) 질문이 다른 질문 유형보다 어려운지 본다.

쉽게 말하면:

```text
한 세션 안의 단순 질문보다
여러 세션에 흩어진 정보를 합쳐야 하는 질문이 더 어려운가?
```

### 실행 방법

#6은 별도 ingest/retrieve를 새로 하지 않고, #4 결과를 재분석한다.

먼저 #4를 실행한다.

```sh
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --model-profile my_model --db-profile my_db

python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage all
```

그 다음 #6 run config를 만든다.

```sh
python scripts/generate_config.py --problem 6 --run-name p6_from_p4 \
    --model-profile my_model --db-profile my_db \
    --reuse-run p4_full
```

분석만 실행한다.

```sh
python scripts/run_pipeline.py --config configs/runs/p6_from_p4.yaml \
    --stage analyze --decompose-multisession
```

### 결과 해석

`analyze.json`에서 아래를 본다.

```text
ms_accuracy
others_mean_accuracy
ms_vs_others_gap
```

해석:

- MS accuracy가 others보다 낮으면 multi-session 질문이 더 어렵다는 뜻
- gap이 클수록 여러 세션 정보 결합이 약점일 가능성이 큼
- k를 늘려도 MS가 계속 낮으면 단순 retrieval depth 증가만으로 해결이 어렵다는 뜻

---

## #12 — k 비용 vs 정확도 Pareto

### 무엇을 보려는 평가인가?

k를 늘렸을 때 정확도 이득 대비 token/latency 비용이 얼마나 늘어나는지 본다.

쉽게 말하면:

```text
정확도를 조금 올리려고 memory를 더 많이 가져왔는데,
그만큼 token 비용과 시간도 많이 늘어나는가?
가장 효율 좋은 k는 어디인가?
```

### 실행 방법

#12도 #4 결과를 재사용한다.

먼저 #4를 실행한다.

```sh
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --model-profile my_model --db-profile my_db

python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage all
```

그 다음 #12 run config를 만든다.

```sh
python scripts/generate_config.py --problem 12 --run-name p12_from_p4 \
    --model-profile my_model --db-profile my_db \
    --reuse-run p4_full
```

Pareto 분석만 실행한다.

```sh
python scripts/run_pipeline.py --config configs/runs/p12_from_p4.yaml \
    --stage analyze --pareto
```

### 결과 해석

`analyze.json`에서 아래를 본다.

```text
accuracy
mean_recall / overall_recall
mean_tokens_per_query
mean_input_token
mean_output_token
mean_num_episodes
mean_llm_time
```

해석:

- accuracy가 오르는데 token도 크게 오르면 비용 대비 효과를 봐야 함
- accuracy가 거의 안 오르는데 token만 늘면 비효율적인 k
- accuracy와 token 사이에서 가장 균형 좋은 지점이 Pareto 후보

예시 해석:

```text
k=20: accuracy 0.86, token 4k
k=50: accuracy 0.87, token 9k
```

이 경우 k=50은 정확도 +0.01을 위해 token이 크게 늘었으므로, k=20이 더 실용적인 운영점일 수 있다.

---

## 5. 실행 후 결과 파일 보는 법

### retrieve.jsonl

검색 결과와 성능 metric이 들어 있다.

주요 필드:

| 필드 | 의미 |
|---|---|
| chunks_text | 검색된 memory 내용 |
| num_episodes_retrieved | 가져온 episode 수 |
| memory_retrieval_time | memory 검색 시간 |
| selected_tool | Agent가 선택한 tool |
| input_token / output_token | 답변 생성에 들어간/나온 token |
| tool_select_input_token / tool_select_output_token | tool 선택 단계 token |
| fact_hits / fact_miss | supporting fact를 검색 결과에서 찾았는지 여부 |

### generate.jsonl

질문별 생성 답변이 들어 있다.

주요 필드:

| 필드 | 의미 |
|---|---|
| golden_answer | 정답 |
| model_answer | 모델이 생성한 답 |
| llm_time | 답변 생성 시간 |

### judge.jsonl

생성 답변에 대한 judge 결과가 들어 있다.

주요 필드:

| 필드 | 의미 |
|---|---|
| llm_score | judge가 매긴 정답 여부/점수 |

### analyze.json

최종 집계 결과가 들어 있다.

주요 필드:

| 필드 | 의미 |
|---|---|
| cells | sweep cell별 집계 |
| accuracy | 평균 정답률 |
| mean_recall | query별 recall 평균 |
| overall_recall | 전체 supporting fact 기준 recall |
| mean_tokens_per_query | 쿼리당 평균 token |
| by_tool | tool별 accuracy/token/latency breakdown |
| pareto | #12용 token/accuracy curve |
| multisession_decomposition | #6용 MS vs others 비교 |

---

## 6. 초보자용 추천 실행 순서

처음에는 전체 데이터 500개를 바로 돌리지 말고 작은 dry-run부터 한다.

### Step 1. #4 small run

```sh
python scripts/generate_config.py --problem 4 --run-name p4_pilot_5q \
    --model-profile my_model --db-profile my_db \
    --k-list 10,20 --length 5

python scripts/run_pipeline.py --config configs/runs/p4_pilot_5q.yaml --stage all
```

확인:

```sh
ls results/p4_pilot_5q/
cat results/p4_pilot_5q/analyze.json
```

### Step 2. #12 Pareto 분석 확인

```sh
python scripts/generate_config.py --problem 12 --run-name p12_from_p4_pilot \
    --model-profile my_model --db-profile my_db \
    --reuse-run p4_pilot_5q

python scripts/run_pipeline.py --config configs/runs/p12_from_p4_pilot.yaml \
    --stage analyze --pareto
```

### Step 3. #6 Multi-session 분석 확인

```sh
python scripts/generate_config.py --problem 6 --run-name p6_from_p4_pilot \
    --model-profile my_model --db-profile my_db \
    --reuse-run p4_pilot_5q

python scripts/run_pipeline.py --config configs/runs/p6_from_p4_pilot.yaml \
    --stage analyze --decompose-multisession
```

### Step 4. #3 prefix 비교 실행

```sh
python scripts/generate_config.py --problem 3 --run-name p3_pilot_5q \
    --model-profile my_model --db-profile my_db \
    --length 5

python scripts/run_pipeline.py --config configs/runs/p3_pilot_5q.yaml --stage all
```

### Step 5. p2/p5 실행

p2/p5는 같은 DB 반복 실행 시 데이터가 섞일 수 있으므로, fresh DB 또는 delete 후 실행을 권장한다.

---

## 7. 이 PR로 가능한 것과 아직 아닌 것

### 가능

```text
- #3 prefix on/off 비교
- #4 k sweep
- #6 MS category 재분해
- #12 token/accuracy Pareto
- #2 HotpotQA Memory vs Agent 비교 (fresh DB 또는 delete 권장)
- #5 LoCoMo Memory vs Agent 비교 (upstream 처리 범위 기준)
```

### 아직 아님

```text
- 논문 Table과 1:1 exact reproduction
- EDWIN1/EDWIN3 prompt 완전 적용
- JSON-str 조건까지 논문과 동일하게 맞춘 비교
- 자동 반복 실험 n_runs > 1
- σ×2 자동 성공/부분/실패 판정
- DB snapshot 동결/복원 자동화
- LoCoMo 전체 범위 / search_limit parameterization
- HotpotQA/LoCoMo run_name 기반 session isolation
```

후속 코드 수정 항목은 `docs/msr/msr_eval_tool_todo_pr7.md`를 참조한다.

---

## 8. 문제 발생 시 먼저 확인할 것

| 증상 | 먼저 볼 것 |
|---|---|
| DB 연결 실패 | `configs/profiles/dbs/{이름}.yaml` host/port/user/password |
| LLM 호출 실패 | `configs/profiles/models/{이름}.yaml` provider/config/API key |
| 결과 파일이 없음 | 어느 stage까지 실행됐는지 `results/{run}/` 확인 |
| analyze 실패 | `judge.jsonl`과 `retrieve.jsonl`이 있는지 확인 |
| p6/p12 결과가 없음 | `--reuse-run`으로 지정한 #4 run 결과가 있는지 확인 |
| p2/p5 결과가 이상함 | 같은 DB에서 이전 run 데이터가 남아 있는지 확인 |
| chunk on/off 결과가 이상함 | chunk 조건별로 ingest를 다시 했는지 확인 |

---

## 9. 최종 요약

이 도구의 가장 안전한 사용 순서는 다음과 같다.

```text
1. DB/LLM profile 준비
2. #4 small pilot 실행
3. #12 Pareto / #6 MS 분석 확인
4. #3 prefix 비교 실행
5. p2/p5는 fresh DB 또는 delete 후 실행
6. 결과는 paper exact reproduction이 아니라 operational reproduction으로 해석
```

한 줄로 요약하면:

```text
PR #7은 “MemMachine 재현 평가를 처음 실행할 수 있게 해주는 MVP wrapper”이며,
LongMemEval 계열(#3/#4/#6/#12)을 먼저 돌려보고,
HotpotQA/LoCoMo(#2/#5)는 DB 격리 주의사항을 지키며 실행하는 것이 안전하다.
```
