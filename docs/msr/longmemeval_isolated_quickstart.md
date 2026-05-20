# LongMemEval — per-question 격리 평가 (MemMachine 백엔드) 가이드

`evaluation/longmemeval/` 의 `ingest.py` + `retrieve.py` 사용. upstream
LongMemEval `src/retrieval/run_retrieval.py` 의 per-question 격리 패턴을
우리 MemMachine 스택 (Neo4j vector graph store + Postgres,
configuration.yml 의 embedder + reranker) 위에서 재현. 단일 session 적재
(`scripts/run_pipeline.py`) 경로의 recall ~50% 문제를 해결한다.

각 질문이 `session_id = <prefix>_<question_id>` 에 격리 적재되어 검색
공간이 ~246k turn → ~500 turn 으로 축소 (~500 배). upstream / Edwin /
main `evaluation/episodic_memory/` 와 동일한 의미론.

### 독립성

`evaluation/longmemeval/` 는 `memmachine_server.*` (워크스페이스 패키지)
외엔 어떤 evaluation/ 트리도 import 안 함. `evaluation/retrieval_agent/` /
`evaluation/utils/agent_utils.py` / `scripts/stages/` 를 main 브랜치 상태로
되돌리거나 삭제해도 step 5a / 5b 는 그대로 동작.

단계별 의존성:

| 단계 | evaluation/longmemeval/ 만으로 가능? | scripts/ 필요? |
|---|---|---|
| 4. `generate_config.py` (워킹 yml 생성) | ❌ | ✅ |
| 5a. ingest | ✅ | ❌ |
| 5b. retrieve | ✅ | ❌ |
| 6. generate (답변 LLM) | ✅ | ❌ |
| 7. judge + 요약 | ✅ | ❌ |

→ step 4 (config 생성) 외엔 전부 본 디렉토리 안에서 완결. `evaluation/` 의
다른 디렉토리 (`retrieval_agent/`, `utils/`, `episodic_memory/` …) 와
`scripts/{regen_answer,run_pipeline}` 은 import 하지 않음 — 통째로
main 브랜치 상태로 되돌려도 본 평가 흐름은 정상 동작.

### upstream / lme_updated 정렬 상태

| 항목 | upstream | lme_updated | 우리 |
|---|---|---|---|
| 격리 단위 | per-question in-memory corpus | per-question Qdrant collection | per-question Neo4j session_id |
| Ingest 단위 | 1 turn = 1 corpus item | 1 turn = 1 Event (segmenter 500자) | **1 turn = 1 Episode** (ff174d6 이후) |
| Recall 의미론 | turn-level binary | turn-level binary (segment 하나라도 hit → 1) | turn-level binary (fact piece 하나라도 hit → 1) |
| Answer prompt | LME_origin / LME_origin_cot | mastra-augmented (KNOWLEDGE UPDATES 등) | **upstream verbatim** |
| Judge prompt | `get_anscheck_prompt` (5종 + abstention) | 동일 (`evaluate_qa.py` verbatim 복사) | 동일 (`_common.py` verbatim 복사) |
| Yes/no parser | `'yes' in lower(raw)` | 동일 | 동일 |

알고리즘 단위 + 의미론은 정렬. 절대 점수 동일은 embedder/reranker/exact-cosine
3 가지가 추가로 정렬돼야 가능 — 자세히는 `evaluation/longmemeval/README.md`
의 "upstream 점수와 동일한 결과를 원하면" 섹션 참고.

## 0. 코드 받기 + 의존성

```bash
git pull origin eval_optimize
uv sync --all-extras
```

## 1. DB 띄우기

```bash
docker compose up -d neo4j postgres
docker compose ps     # neo4j + postgres = Up (healthy)
```

이미 떠 있으면 skip.

## 2. 인증 정보 (이미 했으면 skip)

`configs/profiles/models/main.yaml` — `<GEMINI_API_KEY>` 를 실제 키로 교체
(발급: https://aistudio.google.com/apikey).

`configs/profiles/dbs/main.yaml` — `<NEO4J_PASSWORD>` → `neo4j_password`,
`<POSTGRES_PASSWORD>` → `memmachine_password` (docker compose 기본값).

세부사항: [longmemeval_temporal_reasoning_quickstart.md](longmemeval_temporal_reasoning_quickstart.md)
의 4 절.

## 3. 데이터셋 (이미 있으면 skip)

```bash
uv run python -c "
from huggingface_hub import hf_hub_download
import shutil
src = hf_hub_download(
    repo_id='xiaowu0162/longmemeval-cleaned',
    repo_type='dataset',
    filename='longmemeval_s_cleaned.json',
)
shutil.copy2(src, 'evaluation/data/longmemeval_s_cleaned.json')
"
```

500 문항. `.gitignore` 대상.

## 4. 실험 이름 (`PREFIX`) + 워킹 config 생성

본 가이드는 두 개의 shell 변수만 갈아끼면 **1 개 스모크 → 500 개 풀 런 →
다른 실험 병행** 까지 같은 명령으로 처리할 수 있게 구성돼 있음:

```bash
PREFIX=lme_iso          # 실험 이름 = --session-prefix = --run-name = 결과 디렉토리
LIMIT_ARG="--limit 1"   # 스모크 시 1 문항만; 풀 런 시 ""  (빈 문자열)
```

실험 이름이 바뀌면 (`PREFIX=lme_iso_v2` 같이) Neo4j 안에서 별개 session
집합으로 공존, 결과도 별개 디렉토리.

### 워킹 config 1 회 생성

```bash
uv run python scripts/generate_config.py \
    --problem 0 \
    --run-name $PREFIX \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt
```

산출:
- `configs/runs/${PREFIX}.yaml`
- `configs/generated/${PREFIX}_configuration.yml`

CoT 답변 prompt 를 쓰려면 `--longmemeval-answer-prompt LME_origin_cot_prompt`.
이 단계만 외부 (`scripts/`) 의존, 그 후 5~7 은 `evaluation/longmemeval/` 만.

## 5a. Ingest

```bash
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/${PREFIX}_configuration.yml \
    --session-prefix $PREFIX \
    $LIMIT_ARG
```

각 질문이 `session_id = ${PREFIX}_<question_id>` 로 Neo4j 에 격리 적재.
**1 turn = 1 Episode** (upstream `--granularity turn` 정렬).

각 질문 시작 시 `delete_session_episodes()` 가 먼저 돌아서 같은 PREFIX 로
재실행 시 idempotent. stdout: `[lme-ingest] N/N  qid=...  episodes=...`.

## 5b. Retrieve → retrieve.jsonl

```bash
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path configs/generated/${PREFIX}_configuration.yml \
    --session-prefix $PREFIX \
    --top-k 50 \
    --out results/${PREFIX}/retrieve.jsonl \
    $LIMIT_ARG
```

→ `results/${PREFIX}/retrieve.jsonl`. stdout: `[lme-retrieve] N/N  qid=...  chunks=...`.

`--top-k` 만 바꿔 retrieve 만 다시 돌릴 수 있음 (재-ingest 불필요). 같은
PREFIX 면 Neo4j 의 적재된 데이터 그대로 활용.

## 6. 답변 LLM 호출 → generate.jsonl

```bash
uv run python -m evaluation.longmemeval.generate \
    --retrieve results/${PREFIX}/retrieve.jsonl \
    --config-path configs/generated/${PREFIX}_configuration.yml \
    --out results/${PREFIX}/generate.jsonl \
    $LIMIT_ARG
```

upstream `src/generation/run_generation.py` 의 `LME_origin_prompt` 를
verbatim 으로 사용. CoT 원하면 `--answer-prompt LME_origin_cot_prompt`.
answer LLM 은 working YAML 의 `retrieval_agent.llm_model`.

> 답변 LLM 비용/시간 부담 크면 **step 6~7 스킵하고 recall 만** 보는 변종은
> 아래 "Recall-only 변종" 섹션.

## 7. Judge → judge.jsonl (+ 정확도 요약)

```bash
uv run python -m evaluation.longmemeval.judge \
    --generate results/${PREFIX}/generate.jsonl \
    --config-path configs/generated/${PREFIX}_configuration.yml \
    --out results/${PREFIX}/judge.jsonl \
    $LIMIT_ARG
```

upstream `src/evaluation/evaluate_qa.py` 의 `get_anscheck_prompt` (5 task
+ abstention) 와 lenient yes/no parser **verbatim**. judge LLM 은
`retrieval_agent.judge_llm_model` 우선, 없으면 answer LLM 재사용.

각 row: `llm_score` (1/0) + `judge_raw_response` + `judge_parsed_label`.
끝나면 stdout 에 overall + 카테고리별 정확도 표 자동 출력.

## 스모크 OK → 풀 500 문항

step 5a 가 잘 됐고 step 7 의 1 문항 표가 자연스럽게 나오면, 같은 shell 에서
**LIMIT_ARG 만 비우고 step 5a~7 그대로 재실행**:

```bash
LIMIT_ARG=""
# concurrency 도 같이 올리고 싶으면 각 명령 끝에 --concurrency 8 식으로 추가
```

같은 PREFIX 라면 Neo4j 의 1 문항 데이터는 ingest 가 자동 cleanup 후
재적재 → 결과 OK. retrieve.jsonl / generate.jsonl / judge.jsonl 도 새로
덮어씀.

- `--concurrency N`: Neo4j (5a/5b) / LLM API rate (6/7) 부하 ↑. 무난한 값:
  CPU 환경 4~8, GPU 환경 8~16. Gemini free-tier 는 15 RPM 이라 6~7 단계엔
  concurrency 너무 높이면 rate-limited.
- top-K 만 바꿔 retrieve 재실행: 5b 만 다시 (ingest 스킵).
- 답변 prompt 만 바꿔 비교: 6 만 `--answer-prompt LME_origin_cot_prompt` 로
  다시 실행 → judge 만 새로 돌리면 됨.

## 다른 실험과 병행

`PREFIX` 만 바꿔서 같은 Neo4j 안에 여러 실험을 공존시킬 수 있음. Neo4j
session_id 가 prefix 별로 격리되니까 retrieve 결과 절대 안 섞임.

```bash
# 첫 실험
PREFIX=lme_iso
LIMIT_ARG=""
# step 4 → step 5a → ... → step 7 (한 묶음)

# 두 번째 실험 (다른 prompt, 다른 top-K, 다른 chunking 등)
PREFIX=lme_iso_v2
LIMIT_ARG=""
# step 4 → step 5a → ... → step 7  다시 같은 흐름
```

Neo4j 에는 `lme_iso_<qid>*` 와 `lme_iso_v2_<qid>*` 가 별개 namespace 로 공존.
하나만 정리하려면 그 prefix 의 session 만 골라 delete (별도 cleanup 스크립트
없음 — Neo4j Cypher 직접 또는 `docker compose down -v` 로 전체 초기화).

## Recall-only 변종 (step 6~7 스킵)

답변 LLM / judge 호출 안 하고 retrieval recall 만 볼 때:

```bash
# step 5a/5b 까지만 수행 후
uv run python scripts/recall_curve.py \
    --retrieve results/${PREFIX}/retrieve.jsonl \
    --out      results/${PREFIX}/recall_curve.json

uv run python scripts/plot_recall_curve.py \
    --input results/${PREFIX}/recall_curve.json \
    --out   results/${PREFIX}/recall_curve.png \
    --per-category
```

`scripts/recall_curve.py` 의 매칭은 fact-level binary recall (= lme_updated
의 turn-level recall 과 동등 의미론). turn 단위 회수 측정. LLM 호출 0.

## (선택) 추가 분석

step 7 stdout 의 정확도 표를 JSON 으로도 저장하고 싶으면:

```bash
uv run python scripts/summarize_run.py \
    --judge results/${PREFIX}/judge.jsonl \
    --out   results/${PREFIX}/summary.json
```

이 명령들만 `scripts/` 의존 — step 4~7 본체 흐름은 `evaluation/longmemeval/`
디렉토리만으로 완결.

## 비교 (기존 단일 session 경로 vs 격리)

같은 모델/같은 K 에서:

| 경로 | 적재 | 검색 공간 | 관측 recall |
|---|---|---|---|
| `scripts/run_pipeline.py --stage ingest,retrieve` (= `evaluation/retrieval_agent/`) | 모든 질문이 단일 session | ~246k turn | ~50% |
| `evaluation/longmemeval/{ingest,retrieve}.py` (본 가이드) | 질문 별 session | ~500 turn | ~95% 예상 |

격리 한 가지가 ~45 포인트 차이의 핵심 원인.

## 트러블슈팅

- **"configuration.yml not found"**: step 4 의 `generate_config.py` 가 안
  돌았거나 `--run-name` 이 다름. `configs/generated/<run_name>_configuration.yml`
  존재 확인.
- **Neo4j auth error**: step 2 의 패스워드 일치 여부. `configs/profiles/dbs/main.yaml`
  과 docker compose 의 `${NEO4J_PASSWORD}` 가 같은지 (.env 사용 시 양쪽 일치).
- **Gemini quota / rate limit**: free tier 라 분당 호출 제한. `--concurrency` 낮추거나
  유료 키로 교체.
- **`regen_answer.py` "retrieve.jsonl missing"**: step 5 의 `--out` 이 정확히
  `results/<run_name>/retrieve.jsonl` 인지 확인 (`<run_name>` = `--run-name`).
- **재실행 시 데이터 잔존 의심**: `ingest.py` 가 매 질문 시작 시
  `delete_session_episodes()` 호출하므로 중복 적재 걱정 없음. 그래도 모든
  데이터 날리고 재시작 하려면 `docker compose down -v` 후 step 1 부터.
- **풀 500 문항이 너무 느림**: GPU 가능하면 embedder 가 자동 활용. concurrency
  올려 보고, 그래도 느리면 `--limit` 로 카테고리 별 200~300 으로 우선 확인.

## 핵심 파일 위치

| 항목 | 경로 |
|---|---|
| Ingest | `evaluation/longmemeval/ingest.py` |
| Retrieve | `evaluation/longmemeval/retrieve.py` |
| Generate (answer LLM) | `evaluation/longmemeval/generate.py` |
| Judge | `evaluation/longmemeval/judge.py` |
| 공용 헬퍼 + upstream prompts | `evaluation/longmemeval/_common.py` |
| 디렉토리 README | `evaluation/longmemeval/README.md` |
| Run config | `configs/runs/<run_name>.yaml` |
| Working configuration.yml | `configs/generated/<run_name>_configuration.yml` |
| 산출물 | `results/<run_name>/{retrieve,generate,judge}.jsonl + summary.json` |
| 분석 도구 | `scripts/recall_curve.py`, `scripts/plot_recall_curve.py`, `scripts/summarize_run.py` |
