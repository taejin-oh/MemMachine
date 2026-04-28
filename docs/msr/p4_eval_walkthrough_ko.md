# PR #7 평가 도구 — 문제4 예제 walkthrough (한국어)

> 세션 메모. 문제4(LongMemEval k sweep) 를 예시로 PR #7 평가 도구가 옵션을 어떻게 받아 어떻게 처리하는지 정리.

---


---

# Part 1 — 빠른 시작 (순서대로 따라가면 동작)

> 처음 도구를 쓰는 사람용. 0~5절을 순서대로 따라가면 첫 결과 (`results/.../analyze.json`) 가 나옵니다. 동작 원리는 Part 2, 응용/대체 옵션은 Part 3.

## 0단계: 사전 준비

본격 시작 전에 아래가 준비돼 있어야 합니다.

### DB 두 개 띄우기 (사용자 책임)

본 도구는 DB 를 안 띄웁니다. 본인이 Docker 등으로 먼저 띄우고 주소만 적습니다. repo 의 `docker-compose.yml` 또는 `deployments/helm/` 참고.

```sh
nc -zv localhost 7687    # Neo4j bolt
nc -zv localhost 5432    # Postgres
```
둘 다 succeeded 떠야 다음 단계 의미 있음.

### Python 환경

```sh
uv sync   # repo root 에서
```

### LongMemEval 데이터 위치 (4-C ingest 가 사용)

p3/p4 default 는 `evaluation/data/longmemeval_s_cleaned.json` 을 가리킴. 그 경로에 파일을 두면 wrapper 가 HF 호출 없이 직접 로드. 다른 위치/버전을 쓰거나 HF online 으로 돌리려면 **Part 3 — 옵션 C** 참고.

### LLM API key

다음 절 (4-A) 에서 `my_model.yaml` 의 placeholder 를 본인 키로 바꿉니다.

## 4단계: 너의 환경에서 p4 한 번 돌리기

양이 많아 4-A ~ 4-D 로 분할.
- 4-A: profile YAML 두 개 (model + db) 채우기
- 4-B: `generate_config.py` 한 번 돌려 산출물 검증 (다음 메모)
- 4-C: ingest 단계만 먼저 돌려 DB 적재 확인 (다음 메모)
- 4-D: retrieve / judge / analyze (다음 메모)

---

## 4-A: profile YAML 두 개 채우기

### 0) "configuration.yml" 이 뭐고 왜 중요한지

이 도구는 결국 **MemMachine 본체에 설정을 넘겨야** 동작. MemMachine 본체가 읽는 설정 파일은 딱 하나 — **`configuration.yml`** (생성 위치: `configs/generated/<run_name>_configuration.yml`).

이 파일은 메모리 저장소·embedder·LLM·reranker·DB 를 한 곳에 적어둔 통합 설정. 구조:

```yaml
# configs/generated/p4_pilot_configuration.yml (자동 생성됨)

# === 위쪽: 컴포넌트의 "사용처" — id 만 적음 ===
episode_store:
  database: my_postgres        # ← id 만, 정의는 아래 resources 에
episodic_memory:
  long_term_memory:
    embedder: my_embedder
    reranker: my_reranker
    vector_graph_store: my_neo4j
    message_sentence_chunking: true
retrieval_agent:
  llm_model: my_llm
  reranker: my_reranker

# === 아래쪽: 실제 정의 모음 ===
resources:
  databases:
    my_neo4j:
      provider: neo4j
      config: { uri: bolt://localhost:7687, user: neo4j, password: ... }
    my_postgres:
      provider: postgres
      config: { host: localhost, port: 5432, ... }
  embedders:
    my_embedder:
      provider: openai
      config: { api_key: sk-..., model: text-embedding-3-small, ... }
  language_models:
    my_llm:
      provider: openai-responses
      config: { api_key: sk-..., model: gpt-4o-mini }
  rerankers:
    my_reranker:
      provider: bm25
      config: { k1: 1.5, b: 0.75, ... }
```

**두 부분으로 나뉜 이유 — "이름표 + 정의" 분리**: 같은 reranker 가 retrieval_agent·long_term_memory 양쪽에서 쓰이고, 답변·judge LLM 도 보통 같은 한 entry 를 공유 (`judge_llm:` 블록을 따로 두면 두 entry 로 분리 가능 — `retrieval_agent.judge_llm_model` 이 가리킴). 변수 선언(`resources`)과 변수 사용(`retrieval_agent.llm_model` / `retrieval_agent.judge_llm_model`) 의 분리.

### 1) profile YAML → configuration.yml 매핑

profile YAML 의 (provider, config) 쌍이 → configuration.yml 의 `resources.<bucket>.<id>.{provider, config}` 위치로 그대로 복사돼. 그게 "박는다" 의 의미. 시각화:

```
configs/profiles/models/my_model.yaml          configs/generated/p4_pilot_configuration.yml
─────────────────────────────────────          ────────────────────────────────────────────
embedder:                                      resources:
  id: my_embedder            ───────┬────────►   embedders:
  provider: openai           ──┐    │              my_embedder:        ◄── id 가 키로
  config:                    ──┼─┐  │                provider: openai  ◄── 그대로 복사
    api_key: sk-...          ──┘ │  │                config:           ◄── 그대로 복사
    model: text-embedding-3      │  │                  api_key: sk-...
                                 │  │                  model: text-embedding-3
                                 │  └──────────►  episodic_memory:
                                 │                  long_term_memory:
                                 │                    embedder: my_embedder  ◄── id 만 참조
```

코드 근거 (`scripts/generate_config.py:201-206`):
```python
"embedders": {
    embedder["id"]: {                    # profile.embedder.id 가 key
        "provider": embedder["provider"], # profile.embedder.provider 그대로
        "config": embedder["config"],     # profile.embedder.config 통째로
    },
},
```

### 2) `provider` 문자열의 종착지 — 코드 if/elif 분기

MemMachine 본체가 이걸 보고 어떤 클라이언트 클래스를 띄울지 결정. 예: `packages/server/src/memmachine_server/common/resource_manager/embedder_manager.py:104-133`:

```python
if provider == "openai":
    embedder = OpenAIEmbedder(config)
elif provider == "amazon-bedrock":
    embedder = AmazonBedrockEmbedder(config)
elif provider == "sentence-transformer":
    embedder = SentenceTransformerEmbedder(config)
else:
    raise ValueError(f"Unknown embedder provider: {provider}")
```

**그래서 provider 값은 코드가 알아듣는 문자열만 가능.** 사용 가능 후보 (`evaluation/retrieval_agent/README.md:410-432`):

| 어디서 | 가능한 `provider` 값 |
|---|---|
| `language_models` | `openai-responses`, `openai-chat-completions`, `amazon-bedrock` |
| `embedders` | `openai`, `amazon-bedrock`, `sentence-transformer` |
| `rerankers` | `bm25`, `cohere`, `amazon-bedrock`, `cross-encoder`, `embedder`, `identity`, `rrf-hybrid` |
| `databases` | `neo4j` (vector_graph_store 자리), `postgres` (profile_storage 자리) |

> "사내에 OpenAI 호환 LLM gateway" 면 `provider: openai-chat-completions` + `config.base_url` 을 그쪽으로.

### 3) 어디 보고 `config` 안의 키들을 채우나 — 두 source

#### A. 실용 예시 (복붙용)
**`evaluation/retrieval_agent/README.md` 의 `## Configuration Samples` 섹션** — Sample 1~4 가 통째 yaml:
- **Sample 1** (line 57~) — OpenAI + AWS Bedrock reranker (기본)
- **Sample 2** (line 141~) — Ollama (로컬) + BM25
- **Sample 3** (line 224~) — AWS Bedrock end-to-end
- **Sample 4** (line 309~) — OpenAI 호환 endpoint (사내 gateway)

PR7 의 `_example.yaml` 값들은 **Sample 1 을 model/db 두 파일로 쪼갠 것**.

#### B. 정확한 필드 명세 (필수/선택/default)
**`packages/server/src/memmachine_server/common/configuration/*_conf.py`** 의 Pydantic 모델. 각 provider 별로 dataclass 가 있고 `Field(...)` 의 첫 인자가 `...` 이면 필수, 값이 적혀있으면 default.

| 컴포넌트 | 파일 | 어떤 클래스가 어떤 provider |
|---|---|---|
| embedder | `embedder_conf.py` | `OpenAIEmbedderConf` (=openai), `AmazonBedrockEmbedderConf` (=amazon-bedrock), `SentenceTransformerEmbedderConf` (=sentence-transformer) |
| reranker | `reranker_conf.py` | `BM25RerankerConf` (=bm25), `CohereRerankerConf` (=cohere), `AmazonBedrockRerankerConf` (=amazon-bedrock), `CrossEncoderRerankerConf` (=cross-encoder), `EmbedderRerankerConf` (=embedder), `IdentityRerankerConf` (=identity), `RRFHybridRerankerConf` (=rrf-hybrid) |
| LLM | `language_model_conf.py` | `OpenAIResponsesLanguageModelConf` (=openai-responses), `OpenAIChatCompletionsLanguageModelConf` (=openai-chat-completions), `AmazonBedrockLanguageModelConf` (=amazon-bedrock) |
| DB | `database_conf.py` | (같은 패턴 — neo4j, postgres) |

### 4) provider 별 config 키 — 자주 쓸 것 위주

#### Reranker

`provider: bm25` ← 너가 지금 쓰는 거
```yaml
config:
  k1: 1.5         # default
  b: 0.75         # default
  epsilon: 0.25   # default
  language: english  # default
  tokenizer: default # default
```
**전부 default.** `config: {}` 로 비워둬도 동작. API key 불필요, 가장 단순.

`provider: cohere`
```yaml
config:
  cohere_key: "<COHERE_API_KEY>"   # 필수
  model: rerank-english-v3.0       # default
  base_url: ...                    # 선택
```

`provider: amazon-bedrock`
```yaml
config:
  model_id: "..."                   # 필수
  region: us-east-1                 # 필수
  aws_access_key_id: "..."          # 필수
  aws_secret_access_key: "..."      # 필수
  aws_session_token: "..."          # 선택
```

`provider: cross-encoder` (로컬 모델)
```yaml
config:
  model_name: cross-encoder/qnli-electra-base   # default
  max_input_length: 512                          # 선택
```

`provider: rrf-hybrid` / `provider: embedder`: 다른 reranker/embedder id 를 가리켜 합성.

#### Embedder

`provider: openai` ← `_example.yaml` 이 쓰는 거
```yaml
config:
  api_key: "<OPENAI_API_KEY>"                  # 필수
  model: text-embedding-3-small                # default
  dimensions: 1536                             # default
  base_url: https://api.openai.com/v1          # 선택. 사내 gateway 면 변경
  max_input_length: 8191                       # 선택
  max_retry_interval_seconds: 120              # default
```
> `api_key` 는 `$OPENAI_API_KEY` 또는 `${OPENAI_API_KEY}` 문법으로 환경변수 참조 가능.

`provider: amazon-bedrock`
```yaml
config:
  region: us-east-1                            # 필수
  aws_access_key_id: "..."                     # 필수
  aws_secret_access_key: "..."                 # 필수
  model_id: amazon.titan-embed-text-v2:0       # default
```

`provider: sentence-transformer` (로컬, API key 불필요)
```yaml
config:
  model: BAAI/bge-small-en-v1.5                # 필수, HuggingFace 모델명
  max_input_length: 512                        # 선택
```

#### LLM

`provider: openai-responses` ← `_example.yaml` 이 쓰는 거
```yaml
config:
  api_key: "<OPENAI_API_KEY>"        # 필수
  model: gpt-4o-mini                 # default 는 gpt-5-nano. 명시 권장
  base_url: https://api.openai.com/v1 # 선택
```

`provider: openai-chat-completions` ← **사내 gateway / Ollama / vLLM**
```yaml
config:
  api_key: "<API_KEY>"               # 필수 (Ollama 라도 더미값 필요)
  model: gpt-4o-mini                 # 필수
  base_url: http://host.docker.internal:11434/v1   # 사내/로컬 endpoint
```
Ollama 기본 base_url 이 코드에 예시로 박혀있음 (`language_model_conf.py:19`).

`provider: amazon-bedrock`
```yaml
config:
  region: us-east-1                  # 필수
  aws_access_key_id: "..."           # 필수
  aws_secret_access_key: "..."       # 필수
  model_id: openai.gpt-oss-20b-1:0   # 필수 (default 가 임베딩 모델로 잘못 박혀있어 명시 필수)
```

### 5) 변형 cookbook — 자주 쓰는 3가지

#### 케이스 A: 가장 단순 "OpenAI + BM25" (`_example.yaml` 그대로)
`<OPENAI_API_KEY>` 만 본인 키로 바꾸면 끝.

#### 케이스 B: 사내 OpenAI 호환 gateway
```yaml
embedder:
  id: my_embedder
  provider: openai
  config:
    api_key: "<사내 토큰>"
    base_url: https://gw.your-corp.com/v1   # 변경
    model: <gateway 가 알아듣는 임베딩 모델>
    dimensions: <그 모델 차원>

llm_model:
  id: my_llm
  provider: openai-chat-completions   # responses 가 아니라 chat-completions
  config:
    api_key: "<사내 토큰>"
    base_url: https://gw.your-corp.com/v1
    model: <gateway 가 알아듣는 chat 모델>

rerankers:
  - id: my_reranker
    provider: bm25
    config: {}
# rerankers 가 1개면 primary_reranker 는 생략 가능 (첫 항목 자동 선택)
```

#### 케이스 C: 완전 오프라인 (로컬 GPU 가정)
```yaml
embedder:
  id: my_embedder
  provider: sentence-transformer
  config:
    model: BAAI/bge-small-en-v1.5     # 미리 HuggingFace 캐시
    max_input_length: 512

llm_model:
  id: my_llm
  provider: openai-chat-completions   # Ollama 로 띄움
  config:
    api_key: "ollama"                 # 더미
    base_url: http://localhost:11434/v1
    model: llama3.1                   # 미리 ollama pull

rerankers:
  - id: my_reranker
    provider: bm25
    config: {}
# rerankers 가 1개면 primary_reranker 는 생략 가능 (첫 항목 자동 선택)
```

### 5b) STM summarization 토글 (`summarization_enabled`) — **config-only**

`episodic_memory.short_term_memory.summarization_enabled` 가 generated configuration.yml 에 항상 박힘. **eval-tool 기본값 `false`** (`generate_config.py:build_configuration_yml` 가 의도적으로 false 를 emit). 서버 본체 default 도 `false` 로 통일되어 두 경로 방향이 일치 (eval_claude 후속 정책). 의미: STM `message_capacity` 초과 시 LLM 요약 호출 여부.

> **주의 — config-only knob** — eval wrapper 의 LongMemEval ingest/retrieve 는 `agent_utils.init_memmachine_params()` 가 STM 자체를 `None` 으로 만들어 (`agent_utils.py:461`) 이 토글이 평가 점수에 영향을 주지 않는다. **본체 서버를 generated yml 그대로 띄우는 경우에만** 동작에 영향. eval_claude 에서는 이 사실을 명시적으로 반영:
> - sweep 은 `_validate_sweep_keys` 로 차단 (모든 셀 점수가 동일해서 오해 유발)
> - CLI `--summarization on/off` 사용 시 stderr 경고 출력
> - fixed 는 그대로 허용 (configuration audit 용)

허용되는 2가지 길:

```sh
# 1. CLI shortcut (가장 간단, 1회용) — stderr 경고 1줄 출력됨
python scripts/generate_config.py --problem 4 --run-name p4_pilot \
    --model-profile my_model --db-profile my_db --summarization on

# 2. fixed (영구) — configs/problems/p4.yaml 또는 base.yaml 또는 run override JSON
fixed:
  prepend_user_prefix: true
  message_sentence_chunking: true
  summarization_enabled: true              # ◄── 추가
```

차단된 길:

```sh
# 3. sweep — 거부됨
sweep:
  summarization_enabled: [false, true]     # ✗ SystemExit("config-only ...")
```

두 허용 경로 모두 generated yml 의 `episodic_memory.short_term_memory.summarization_enabled` 한 줄을 갱신. CLI > JSON > problem yaml > base yaml 의 deep_merge 우선순위 그대로.

### 6) `my_db.yaml` — DB 두 개

본 도구는 DB 를 안 띄움. 본인이 Docker 등으로 먼저 띄우고 주소만 적음.

```yaml
vector_graph_store:    # episode 를 그래프로 + 벡터검색 (의미 검색)
  id: my_neo4j
  provider: neo4j
  config:
    uri: bolt://localhost:7687
    user: neo4j
    password: "<Neo4j 비번>"

profile_storage:       # 세션/메타데이터
  id: my_postgres
  provider: postgres
  config:
    dialect: postgresql
    driver: asyncpg
    host: localhost
    port: 5432
    user: memmachine
    password: "<Postgres 비번>"
    db_name: memmachine               # CREATE DATABASE 로 미리 만들어 둬야 함
```

repo 의 `docker-compose.yml` 또는 `deployments/helm/` 에 두 DB 동시에 띄우는 예제. 그걸 그대로 쓰면 host/port/user/db_name 거의 다 맞고 password 만 본인이 정하면 됨.

### 7) 채운 후 미리 보는 configuration.yml

`generate_config.py` 가 위 두 파일을 읽어 만드는 결과 (placeholder 채워졌다고 가정):

```yaml
episode_store:
  database: my_postgres                     # ◄── my_db.yaml 의 profile_storage.id
  with_count_cache: true
episodic_memory:
  long_term_memory:
    embedder: my_embedder                   # ◄── my_model.yaml 의 embedder.id
    reranker: my_reranker
    vector_graph_store: my_neo4j
    message_sentence_chunking: true         # ◄── p4.yaml 의 fixed
  short_term_memory:
    llm_model: my_llm
    ...
retrieval_agent:
  llm_model: my_llm
  reranker: my_reranker
session_manager:
  database: my_postgres
resources:
  databases:
    my_neo4j: { provider: neo4j, config: { uri: ..., user: ..., password: ... } }
    my_postgres: { provider: postgres, config: { host: ..., ... } }
  embedders:
    my_embedder: { provider: openai, config: { api_key: ..., model: ..., dimensions: 1536 } }
  language_models:
    my_llm: { provider: openai-responses, config: { api_key: ..., model: gpt-4o-mini } }
  rerankers:
    my_reranker: { provider: bm25, config: { k1: 1.5, b: 0.75, ... } }
evaluation:
  longmemeval:
    prepend_user_prefix: true               # ◄── p4.yaml 의 fixed
```

너가 적은 값 하나하나가 어디로 갔는지 추적 가능. 위쪽은 id 만, 아래쪽 `resources` 는 provider+config 통째로.

### 8) 채운 후 sanity check

#### DB 떠 있는지
```sh
nc -zv localhost 7687    # Neo4j bolt
nc -zv localhost 5432    # Postgres
```
둘 다 succeeded 떠야 다음 단계 의미 있음.

#### config 키 검증 (선택)
`generate_config.py` 후 `*_conf.py` 의 Pydantic 모델로 parse 시켜 보면 잘못된 키를 미리 잡을 수 있음:
```sh
python -c "
import yaml
from memmachine_server.common.configuration.embedder_conf import EmbeddersConf
with open('configs/generated/p4_pilot_configuration.yml') as f:
    cfg = yaml.safe_load(f)
EmbeddersConf.parse({'embedders': cfg['resources']['embedders']})
print('embedders OK')
"
```

### 9) API key 평문 주의

profile YAML 두 개 모두 평문 key/password 가 들어감. `.gitignore` 에 본인 파일이 빠지는지 확인. PR7 이 `_example.yaml` 만 commit 되도록 패턴을 추가했지만 본인 파일명에 맞게 추가 검토.

---

---

## 4-B: `generate_config.py` 한 번 돌려 산출물 검증

목적: 4-A 에서 채운 두 profile YAML 이 실제로 어떻게 합쳐지는지 눈으로 확인. 아직 DB·LLM 호출 0, 디스크 IO 만.

### 1) 명령 한 줄 — 가장 작은 dry-run

```sh
python scripts/generate_config.py \
    --problem 4 --run-name p4_pilot \
    --model-profile my_model --db-profile my_db \
    --k-list 10,20 --length 5
```

각 인자 의미:
- `--problem 4` → `configs/problems/p4.yaml` 을 base 위에 얹음
- `--run-name p4_pilot` → 산출물 파일명·디렉토리명에 박힘
- `--model-profile my_model` → `configs/profiles/models/my_model.yaml` 읽음
- `--db-profile my_db` → `configs/profiles/dbs/my_db.yaml` 읽음
- `--k-list 10,20` → p4.yaml 의 `sweep.search_limit: [10,20,30,50,100]` 을 `[10,20]` 으로 덮음 (cell 5개 → 2개)
- `--length 5` → p4.yaml 의 `benchmark.length: 500` 을 `5` 로 덮음 (질문 500 → 5)

### 2) 성공하면 stdout

```
[ok] run config: configs/runs/p4_pilot.yaml
[ok] working configuration.yml: configs/generated/p4_pilot_configuration.yml
```

두 파일이 만들어짐:

| 파일 | 누가 읽나 | 역할 |
|---|---|---|
| `configs/runs/p4_pilot.yaml` | `run_pipeline.py` | run 의 모든 결정값 박제 |
| `configs/generated/p4_pilot_configuration.yml` | MemMachine 본체 | 실제 컴포넌트 띄울 때 읽는 통합 설정 |

### 3) 산출물 1: `configs/runs/p4_pilot.yaml` 1대1 추적

각 값이 어디서 왔는지 표시:

```yaml
# === configs/base.yaml 에서 옴 ===
results_dir: results
prompts_dir: prompts
n_runs: 1
evaluation:
  exclude_abstention: true
  ingest_concurrency: 4
  search_concurrency: 4
  judge_concurrency: 4
judge:
  llm_model_id: null

# === configs/problems/p4.yaml 에서 옴 ===
problem: 4
description: "LongMemEval 500 — k sweep ..."
benchmark:
  name: longmemeval
  length: 5                       # ← p4.yaml 은 500. CLI --length 5 가 덮음
  split: longmemeval_s_cleaned
sweep:
  search_limit: [10, 20]          # ← p4.yaml 은 [10,20,30,50,100]. CLI --k-list 가 덮음
fixed:
  prepend_user_prefix: true
  message_sentence_chunking: true
  test_target: retrieval_agent
prompts:
  generate_prompt_file: prompts/EDWIN3.txt
metrics:                          # 코드는 안 읽음 (메모성)
  - overall_llm_score
  - per_category_llm_score
  - tokens_per_query
  - latency_per_query

# === CLI 에서 옴 ===
run_name: p4_pilot
configuration:
  mode: profile                   # base.yaml default
  model_profile: my_model
  db_profile: my_db
  generated_dir: configs/generated
  generated_path: /home/user/MemMachine/configs/generated/p4_pilot_configuration.yml
                                  # ← generate_config 가 마지막에 추가
```

확인 포인트:
- `benchmark.length: 5` 인가
- `sweep.search_limit: [10, 20]` 인가
- `configuration.generated_path` 가 절대경로로 박혀 있는가
- `fixed.message_sentence_chunking: true` 그대로인가 (CLI 로 못 덮음)

### 4) 산출물 2: `configs/generated/p4_pilot_configuration.yml` 1대1 추적

profile YAML 두 개가 합쳐진 결과 (`_example.yaml` 로 채웠다고 가정):

```yaml
episode_store:
  database: my_postgres                     # ◄── my_db.yaml profile_storage.id
  with_count_cache: true
episodic_memory:
  enabled: true
  long_term_memory:
    embedder: my_embedder                   # ◄── my_model.yaml embedder.id
    reranker: my_reranker                   # ◄── primary_reranker (또는 rerankers[0].id)
    vector_graph_store: my_neo4j            # ◄── my_db.yaml vector_graph_store.id
    message_sentence_chunking: true         # ◄── p4.yaml fixed (_apply_fixed_to_configuration)
  long_term_memory_enabled: true
  short_term_memory:
    llm_model: my_llm
    message_capacity: 500
    summarization_enabled: false             # ◄── default. fixed/sweep/CLI(--summarization on/off) 로 토글
    summary_prompt_system: "You are an AI agent that summarizes episodes."
    summary_prompt_user: "Summarize: {summary}\n{episodes}\n..."
  short_term_memory_enabled: true
logging:
  level: INFO
retrieval_agent:
  llm_model: my_llm
  reranker: my_reranker
semantic_memory:
  enabled: false
  config_database: my_postgres
session_manager:
  database: my_postgres
resources:
  databases:
    my_neo4j:
      provider: neo4j                       # ◄── my_db.yaml vector_graph_store.provider
      config: { uri: bolt://localhost:7687, user: neo4j, password: ... }
    my_postgres:
      provider: postgres
      config: { dialect: postgresql, ... }
  embedders:
    my_embedder:
      provider: openai                      # ◄── my_model.yaml embedder.provider
      config: { api_key: ..., model: ..., dimensions: 1536 }
  language_models:
    my_llm:
      provider: openai-responses
      config: { api_key: ..., model: gpt-4o-mini }
  rerankers:
    my_reranker:
      provider: bm25                        # ◄── my_model.yaml rerankers[0].provider
      config: { k1: 1.5, b: 0.75, ... }
evaluation:
  longmemeval:
    prepend_user_prefix: true               # ◄── p4.yaml fixed
```

확인 포인트:
- `resources.embedders.my_embedder.config.api_key` 에 placeholder (`<OPENAI_API_KEY>`) 가 아니라 실키
- `resources.databases.my_neo4j.config.password` 가 본인 비번
- `episodic_memory.long_term_memory.message_sentence_chunking: true`
- `evaluation.longmemeval.prepend_user_prefix: true`
- 위쪽 id 참조와 아래쪽 `resources` 의 키 일치

### 5) 코드 근거

| 값 | 코드 위치 |
|---|---|
| reranker list 검증/정규화 (id/provider/config/primary/rrf-hybrid 참조) | `scripts/generate_config.py` `_validate_and_normalize_rerankers()` |
| `episode_store`, `episodic_memory`, `retrieval_agent`, `resources` 의 골격 | `scripts/generate_config.py` `build_configuration_yml()` |
| `message_sentence_chunking` / `prepend_user_prefix` / `summarization_enabled` 주입 | `scripts/generate_config.py` `_apply_fixed_to_configuration()` |
| sweep cell 별 토글 (위 3개) | `scripts/stages/retrieve.py` `_apply_cell_to_config()` |
| `--summarization` CLI shortcut → `fixed.summarization_enabled` | `scripts/generate_config.py` `cli_to_overrides()` |
| `benchmark.data_path` 절대경로 resolve (LoCoMo 등) | `scripts/generate_config.py` `main()` 안 data_path resolve block |
| 4-way merge (base + p4 + json + CLI) | `scripts/generate_config.py` `main()` 안 `deep_merge(...)` 호출 |
| `configuration.generated_path` 박는 곳 | `scripts/generate_config.py` `main()` 안 `maybe_generate_configuration_yml()` 직후 |

### 6) `--from-json` 으로 같은 결과 재현 (선택 검증)

```sh
cat > /tmp/p4_pilot.json <<'EOF'
{
  "problem": 4,
  "run_name": "p4_pilot_from_json",
  "configuration": {"model_profile": "my_model", "db_profile": "my_db"},
  "benchmark": {"length": 5},
  "sweep": {"search_limit": [10, 20]}
}
EOF
python scripts/generate_config.py --from-json /tmp/p4_pilot.json
diff configs/runs/p4_pilot.yaml configs/runs/p4_pilot_from_json.yaml
```
diff 가 `run_name` / `generated_path` 두 줄만 차이 나면 4-way merge 가 의도대로.

### 7) 흔한 실패 케이스

generate_config 단계에서 잡히는 에러 (모두 명시적 `ValueError`):

| 증상 | 원인 |
|---|---|
| `ERROR: --problem (or 'problem' in JSON) is required` | `--problem` 빠짐 |
| `mode=profile requires both configuration.model_profile and configuration.db_profile` | 두 인자 중 하나 누락 |
| `FileNotFoundError: configs/profiles/models/my_model.yaml` | 4-A 에서 파일 복사 안 함 또는 이름 오타 |
| `KeyError: 'embedder'` 또는 `KeyError: 'llm_model'` | profile YAML 의 들여쓰기/key 누락 |
| `legacy 'reranker:' is no longer supported. Remove it and use only 'rerankers:' list.` | profile YAML 에 새 `rerankers:` 와 옛 `reranker:` 가 동거 |
| `model profile schema changed: use 'rerankers:' (list) instead of legacy 'reranker:' (dict)` | profile YAML 이 옛 단일 dict 형식만 들고 있음 |
| `model profile must define 'rerankers' as a non-empty list` | `rerankers:` 키 자체가 없음 |
| `model profile 'rerankers' must be a list, got dict` | `rerankers:` 가 dict 로 적힘 (`-` 빠짐) |
| `model profile 'rerankers' must be a non-empty list of entries` | `rerankers: []` 빈 list |
| `rerankers[<idx>] is missing required 'id'` / `'provider'` | entry 의 필수 키 누락 |
| `rerankers[<idx>] (id='...') config must be a mapping, got <type>` | `config:` 가 dict 가 아닌 값 (문자열, list 등) |
| `rerankers contains duplicate id: '...'` | 같은 id 가 list 안에 두 번 |
| `primary_reranker='...' not found in rerankers ids [...]` | `primary_reranker` 가 가리키는 id 가 list 에 없음 (오타) |
| `rrf-hybrid reranker '...' requires non-empty config.reranker_ids` | hybrid 의 결합 대상 id 가 비어 있음 |
| `rrf-hybrid reranker '...' config.reranker_ids must be a non-empty list of strings` | `reranker_ids` 가 list[str] 이 아님 (문자열 단일 등) |
| `rrf-hybrid reranker '...' references unknown id '...'` | hybrid 가 가리키는 id 가 같은 list 안에 없음 |
| `rrf-hybrid reranker '...' references itself in reranker_ids` | hybrid 가 자기 자신을 결합 대상으로 |
| `pydantic.ValidationError: api_key Field required` (ingest 시점) | profile YAML 의 placeholder 안 바꿈 — wrapper 가 아니라 MemMachine 본체 `*_conf.py:parse()` 가 잡음 |

### 8) 산출 디렉토리

```
configs/
  runs/
    p4_pilot.yaml                        # ← run_pipeline 이 다음 단계에서 사용
  generated/
    p4_pilot_configuration.yml           # ← MemMachine 본체가 읽음
results/                                  # ← 아직 비어있음. 4-C 에서 채워짐
```

이 시점까지 **모든 게 로컬 파일 IO**. DB·LLM 호출 0. 인터넷·DB 없이도 4-B 까지는 smoke OK.

### 9) 4-C 가기 전 체크리스트

- [ ] `configs/runs/p4_pilot.yaml` 의 `benchmark.length`, `sweep.search_limit` 의도대로
- [ ] `configs/generated/p4_pilot_configuration.yml` 의 `api_key`/`password` 가 실값
- [ ] `nc -zv localhost 7687` / `nc -zv localhost 5432` 둘 다 succeeded
- [ ] LLM API 가 실제 호출 가능한지 간단한 curl

---

## 4-C: ingest 단독 실행 — DB 에 진짜 적재되는 단계

여기서부터 **DB 및 embedding provider 호출이 실제로 발생**. LLM 답변 생성 호출은 ingest 가 아니라 retrieve 단계에서 발생함. 4-B 까지는 로컬 파일만 만들었지만 4-C 는 외부 시스템에 영향이 가는 단계라 idempotency / 재시도 / 정리 정책이 중요.

### 1) 명령 한 줄

```sh
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage ingest
```

`--stage all` 이 아니라 `--stage ingest` 만. **가장 비싼 단계라 분리 실행 권장**.

### 2) 내부 흐름

`scripts/run_pipeline.py:89-91` → `scripts/stages/ingest.py:run()` 호출.

```python
# scripts/stages/ingest.py:91-131 (run 함수)
def run(run_cfg):
    out_dir = cm.results_dir_for(run_cfg)        # results/p4_pilot/
    out_path = out_dir / "ingest.jsonl"

    if _already_ingested(out_path):              # ◄── idempotency 체크
        print(f"[ingest] skip — {out_path} already marked ok")
        return out_path

    config_path = cm.resolve_config_path(run_cfg) # configs/generated/p4_pilot_configuration.yml
    session_id = cm.session_id_for(run_cfg)       # eval_tool_longmemeval_p4_pilot
    bench_name = run_cfg["benchmark"]["name"]     # longmemeval / hotpot / locomo

    if bench_name == "longmemeval":
        info = _ingest_longmemeval(run_cfg, config_path, session_id)
    elif bench_name == "hotpot":
        info = _ingest_hotpot(...)
    elif bench_name == "locomo":
        info = _ingest_locomo(...)

    cm.write_jsonl(out_path, [{"status": "ok", ...}])  # ◄── ok 마커 기록
```

LongMemEval 분기는 기존 코드를 직접 import 해서 `length`/`split` 만 넘김. LoCoMo 분기는 subprocess 로 `evaluation/retrieval_agent/locomo_ingest.py` 를 띄우면서 `--data-path` 를 넘김.

### 3) ingest 시 실제로 어디에 무엇이 저장되나 (LongMemEval 기준)

`length: 5` 라고 가정. 한 sample 안에 `haystack_sessions` (질문 답에 필요한 과거 대화 세션들) + `question`/`answer`/`supporting_facts` 가 있음. ingest 단계는 **질문은 안 건드리고 `haystack_sessions` 만 적재**.

각 sample 마다:
1. `_collect_turn_contents()` 가 해당 sample 의 모든 turn 을 episode content 로 변환 (긴 content 는 max_chars 기준으로 split → episode 자체 수가 늘어남)
2. 각 episode 에 `session_key=<session_id>` 가 박힘 (`agent_utils.py:458`)
3. `EpisodicMemory.add_memory_episodes()` 호출 — eval wrapper 는 `agent_utils.init_memmachine_params()` 에서 `short_term_memory=None` 으로 EpisodicMemory 를 만들기 때문에 (`agent_utils.py:461`) **long-term memory 만 사용**
4. `LongTermMemory` → `DeclarativeMemory` 가 episode 별로 derivative 를 만들어 embedding + Neo4j 노드 저장. `message_sentence_chunking=true` 이면 `_derive_derivatives()` 가 episode 본문을 sentence 단위로 쪼개 **검색용 derivative/embedding 수가 늘어남** (episode 자체는 그대로)

> **단정 금지** — configuration.yml 에 `profile_storage` (Postgres) 가 포함돼 있어도 **현재 eval wrapper 의 LongMemEval ingest 경로에서 Postgres session row 가 반드시 생성된다고 보장하지 않음**. 본체 동작은 환경/설정에 따라 다를 수 있어 확인용으로만 쓸 것.

### 4) `session_id` 의 격리 역할

`scripts/stages/_common.py:session_id_for()` 가 만드는 ID:
```
eval_tool_{benchmark}_{run_name}    # 예: eval_tool_longmemeval_p4_pilot
```

이 값이 EpisodicMemory 의 `session_key` 로 들어가고, declarative_memory 가 노드 저장 시 `mangle_property_key()` 를 적용해 **`filterable_session_key`** 라는 property name 으로 박음 (`packages/server/src/memmachine_server/episodic_memory/declarative_memory/data_types.py:87` + `declarative_memory.py:128-130`).

같은 DB 인스턴스에서 다른 `run_name` 으로 ingest 하면 `filterable_session_key` 가 달라서 episode 가 섞이지 않음. retrieve 도 같은 session_key 로만 검색.

> **주의** — 이건 LongMemEval 한정. **HotpotQA(p2) 는 upstream 코드가 `hotpotqa_group` 으로 session_id 하드코드** (`USAGE.md:200`). p2 를 같은 DB 에서 두 번 돌리면 episode 가 섞임. p5(LoCoMo) 는 `group_{idx}` 형식. p2/p5 반복 실행 시 공식 delete 경로 (5절) 로 정리 필요.

### 5) p5 (LoCoMo) 의 추가 흐름

LoCoMo 는 HuggingFace 가 아니라 **로컬 JSON 경로** 가 필요. PR #19 부터 `configs/problems/p5.yaml` 에 default 가 박혀있어서 첫 실행도 자동으로 동작:

```yaml
# configs/problems/p5.yaml
benchmark:
  name: locomo
  data_path: evaluation/data/locomo10.json   # repo-root 상대
```

PR #20 부터 `generate_config.py` 가 이 상대경로를 **절대경로로 resolve 해서 run YAML 에 박음**. `configs/runs/p5_pilot.yaml` 안에는 절대경로가 보임:

```yaml
benchmark:
  name: locomo
  data_path: /home/user/MemMachine/evaluation/data/locomo10.json
```

이 결과 LoCoMo subprocess (`locomo_ingest.py --data-path ...`) 는 cwd 와 무관하게 동일 파일을 가리킴. 다른 위치의 데이터를 쓰고 싶으면 JSON override 또는 직접 편집으로 절대경로를 덮어 쓰면 됨.

### 6) idempotency — 같은 run 으로 두 번 호출

`_already_ingested()` (`ingest.py:25-32`) 가 `results/{run_name}/ingest.jsonl` 마지막 줄을 보고 `status: "ok"` 면 skip:

```sh
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage ingest
# [ingest] benchmark=longmemeval  config=...  session=eval_tool_longmemeval_p4_pilot
# [ingest] ok → results/p4_pilot/ingest.jsonl

python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage ingest  # 두 번째
# [ingest] skip — results/p4_pilot/ingest.jsonl already marked ok
```

**중요**: skip 은 jsonl 파일 존재 여부로만 판단. **DB 자체는 안 봄.** jsonl 만 있고 DB 가 비었으면 (수동 정리, 다른 머신 등) skip 되어 retrieve 가 빈 검색만 함. 의심스러우면 jsonl 삭제 후 재시도.

### 7) 산출물 — `results/{run_name}/ingest.jsonl`

```json
{"status": "ok", "started_at": "...", "finished_at": "...", "session_id": "eval_tool_longmemeval_p4_pilot", "benchmark": "longmemeval", "num_questions": 5}
```
한 줄짜리 마커. `num_questions` 가 요청 `length` 와 **대체로** 일치하는지 확인. `load_longmemeval_dataset()` 이 `min(length, len(dataset))` 만큼 로드하므로 `length` 가 dataset 크기보다 크면 실제 dataset 크기까지만 로드되어 `num_questions < length` 가 정상.

### 8) DB 직접 확인 (옵션, 탐색용)

#### Neo4j — 정확 쿼리
```cypher
MATCH (n)
WHERE n.filterable_session_key = 'eval_tool_longmemeval_p4_pilot'
RETURN labels(n), count(n);
```
property name 은 `filterable_<original key>` 형식. `original key` 는 declarative_memory 가 episode 의 `session_key` 를 그대로 박은 값 (`long_term_memory.py:108`).

#### Neo4j — 탐색용 (schema 가 다를 때 안전)
```cypher
MATCH (n)
WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS 'eval_tool_longmemeval_p4_pilot')
RETURN labels(n), keys(n), count(n)
LIMIT 5;
```
실제 노드의 라벨/속성을 한 번 보고 위 정확 쿼리의 property name 을 확정하는 데 사용.

#### Postgres
환경/본체 설정에 따라 row 가 생길 수 있으나 **현재 eval wrapper 경로에서는 필수 확인 항목이 아님**. 디버깅 시 `\dt` 로 schema 본 후 추정.

### 9) 흔한 실패 케이스

| 증상 | 원인 |
|---|---|
| `ConnectionError: bolt://localhost:7687` | Neo4j 안 떠 있음. `nc -zv localhost 7687` 부터 |
| `OSError: connection refused` (Postgres) | Postgres 안 떠 있음 (eval wrapper 경로에선 필수는 아니지만 본체가 초기화 단계에서 연결을 시도할 수 있음) |
| `pydantic.ValidationError: api_key Field required` | profile YAML 의 `<OPENAI_API_KEY>` placeholder 그대로 |
| `huggingface_hub.errors.RepositoryNotFoundError` 등 (LongMemEval) | dataset 다운 실패 — 3단계 옵션 A (HF 캐시 옮기기) 참고 |
| `benchmark.data_path is required for locomo` | p5.yaml 에서 `data_path` 가 빠짐. PR #19 이후 default 박힘 — 그래도 빠지면 사용자 override 가 덮은 것 |
| `FileNotFoundError: ...locomo10.json` | data_path 가 가리키는 파일이 없음. PR #20 이후 절대경로로 resolve 되므로 그 절대경로 확인 |
| ingest 가 도중에 멈춤 | embedder rate-limit. `evaluation.ingest_concurrency` 줄이거나 (`base.yaml:31`) `max_retry_interval_seconds` 조정 |
| ingest OK 끝났는데 episode 0개 | `haystack_sessions` 가 빈 dataset, 또는 `_collect_turn_contents()` 가 빈 content 로 처리 |

### 10) 중간에 죽었을 때 복구

ingest.jsonl 이 안 만들어졌으면 (= status ok 마커 없음):
- 재실행 시 처음부터 다시 함
- 그런데 이전 시도에서 일부 episode 는 이미 DB 에 들어가있어 → **중복 ingest** 가능

대응 — **공식 delete 경로를 우선** 사용:

#### LongMemEval — `longmemeval_delete()` (권장)
```sh
python evaluation/retrieval_agent/longmemeval_test.py \
    --run-type delete \
    --test-target memmachine \
    --session-id eval_tool_longmemeval_p4_pilot \
    --config-path configs/generated/p4_pilot_configuration.yml
```

#### HotpotQA
```sh
python evaluation/retrieval_agent/hotpotQA_test.py \
    --run-type delete \
    --test-target memmachine \
    --config-path configs/generated/p2_pilot_configuration.yml
```

#### LoCoMo
```sh
python evaluation/retrieval_agent/locomo_delete.py \
    --data-path /abs/path/locomo10.json \
    --config-path configs/generated/p5_pilot_configuration.yml
```

공식 경로로도 남는 데이터가 있거나 schema 확인이 필요하면 마지막 수단으로 8절의 탐색용 cypher 로 확인 후 Neo4j 수동 정리.

### 11) 4-D 가기 전 체크리스트

- [ ] `results/{run_name}/ingest.jsonl` 존재 + `status: ok` + `num_questions` 가 요청 `length` 와 대체로 일치 (dataset 크기에 따라 작을 수 있음)
- [ ] (옵션) Neo4j 에서 `filterable_session_key` 기준 노드 count > 0
- [ ] stderr 에 retry / rate-limit warning 이 없거나 적음

---

## 4-D: retrieve → generate → judge → analyze

### 1) 명령

```sh
# 단계별 (실패 시 그 stage 만 재실행 가능)
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage retrieve
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage generate
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage judge
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage analyze

# 한 번에 묶어서
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage retrieve,generate,judge,analyze
```

각 stage 의 산출물이 다음 stage 의 입력이 되고, 같은 `results/{run_name}/` 안에 누적.

### 2) 내부 흐름

`scripts/run_pipeline.py:run()` 이 stage list 를 canonical 순서로 정렬해서 호출. 4-D 의 4개 stage 가 어떻게 연결되는지:

```
retrieve (D-005: generate.jsonl 도 같이 emit)
  ├─ retrieve.jsonl   ─┐
  └─ generate.jsonl   ─┤
                       ├─→ judge → judge.jsonl
                       │           │
                       │     analyze (judge.jsonl + retrieve.jsonl 합쳐 cell 집계)
                       │           │
                       └───────────┴─→ analyze.json
generate stage 자체는 no-op verify (D-005)
```

### 3) retrieve — sweep cell 펼침 + cell 별 process_question

`scripts/stages/retrieve.py:run()` 핵심:

```python
sweep_cells = _expand_sweep(run_cfg.get("sweep", {}))
# ↑ 내부에서 _validate_sweep_keys() 가 위험 키 차단

for cell_idx, cell in enumerate(sweep_cells):
    params = _resolved_params(run_cfg, cell)   # fixed + cell, sweep wins
    _apply_cell_to_config(config_path, params) # cell-only toggle in-place

    if bench_name == "longmemeval":
        responses = await _run_longmemeval_cell(...)   # process_question N 개 비동기
    elif bench_name == "hotpot":
        responses = await _run_hotpot_cell(...)
    elif bench_name == "locomo":
        responses = _run_locomo_cell(...)              # subprocess

    for category, record in responses:
        r_row, g_row = _split_response(category, record, params)
        retrieve_rows.append(r_row); generate_rows.append(g_row)
```

#### sweep validation (eval_claude 신규)

`_validate_sweep_keys()` (`retrieve.py:41-62`) 가 두 부류를 명시적 `SystemExit` 으로 차단:

```python
SWEEP_INGEST_AFFECTING_KEYS = {"message_sentence_chunking"}
SWEEP_CONFIG_ONLY_KEYS      = {"summarization_enabled"}
```

| sweep 에 넣으면 | 메시지 핵심 |
|---|---|
| `message_sentence_chunking: [false, true]` | "affects ingest output (Episode storage shape) and cannot be swept from the retrieve stage. Move them to `fixed:` and use a separate run + ingest per value." |
| `summarization_enabled: [false, true]` | "are config-only for the current eval path (`agent_utils.py:461` constructs EpisodicMemory with `short_term_memory=None`). Sweeping them would emit a matrix where every cell scores identically." |

즉 chunk on/off 비교는 **두 개의 별도 run** 으로 (USAGE.md 의 안내 그대로). summarization 은 config-only knob 이라 sweep 무의미.

#### cell 별 in-place 토글 (eval_claude 에서 단순화됨)

`_apply_cell_to_config()` 가 cell 마다 호출되지만 **`prepend_user_prefix` 한 가지만** in-place 갱신. `message_sentence_chunking` / `summarization_enabled` 는 fixed-only 라 generate_config 시점에 박혔고 cell 마다 재적용할 필요가 없어졌어 (single source-of-truth).

`search_limit` 은 configuration.yml 에 안 박힘. `params["search_limit"]` 에서 직접 읽어 `process_question(search_limit=...)` 인자로 전달.

#### process_question — LongMemEval 케이스

`_run_longmemeval_cell()`:
- `agent_utils.load_eval_config(config_path)` → ResourceManager
- `agent_utils.init_memmachine_params(rm, session_id, agent_name)` → `(memory, answer_model, query_agent)`
  - `agent_name` 은 `params["test_target"]` 에 따라 `MemMachineAgent` / `ToolSelectAgent`
- 각 sample (질문) 마다 `agent_utils.process_question()` — 검색 + 답변 한 번에
- `concurrency = run_cfg.evaluation.search_concurrency` (default 4) 만큼 묶어 `asyncio.gather`
- **HF vs 로컬**: `bench.get("data_path")` 가 있으면 `_common.load_longmemeval_local()` 으로 로컬 JSON 직접 로드 (HF 호출 0). 없으면 기존 HF path. ingest 와 동일 분기.

#### 산출물 split (`_split_response()`)

한 응답 record 가 두 jsonl 행으로:

```
retrieve.jsonl 행:
  question, category, sweep, question_id,
  chunks_text, num_episodes_retrieved, memory_retrieval_time,
  memory_search_called, agent, selected_tool, supporting_facts,
  input_token, output_token,
  tool_select_input_token, tool_select_output_token,
  fact_hits, fact_miss

generate.jsonl 행:
  question, category, sweep, question_id,
  golden_answer, model_answer, llm_time
```

cell 5 sample × 2 sweep cell = 10 행씩 두 jsonl 에 누적.

### 4) generate — no-op verify + EDWIN hook

`scripts/stages/generate.py:run()` 는 retrieve 가 이미 emit 한 `generate.jsonl` 을 검증만:
- 파일 존재 + 행 수 보고
- EDWIN prompt hook 상태 보고 (D-003 — 현재는 fallback 또는 "loaded but NOT yet applied")

따라서 `--stage generate` 는 사실상 sanity check. retrieve 후 자동 통과.

### 5) judge — generate.jsonl + llm_score

`scripts/stages/judge.py:run()` 가 `generate.jsonl` 의 각 행에 `evaluate_llm_judge()` 호출해 0/1 점수 매김:

```python
judged.append({**row, "llm_score": int(score)})
# 50 행마다 진행 로그 + running accuracy 출력
```

#### judge LLM swap (eval_claude 신규)

`_judge_config_path()` (`judge.py:25-64`) 가 `run_cfg.judge.llm_model_id` 가 설정돼 있으면 임시 configuration.yml 을 만들어 **`retrieval_agent.judge_llm_model`** 만 그 ID 로 swap. **`retrieval_agent.llm_model` (답변 LLM) 은 절대 안 건드림** — 답변과 채점이 분리.

ID 가 `resources.language_models` 에 없으면 명시적 ValueError. 보통 model profile 에 `judge_llm` 블록을 미리 박아두는 패턴 (`configs/profiles/models/_example.yaml` 의 주석 처리 블록 참고):

```yaml
# my_model.yaml (선택)
judge_llm:
  id: my_judge
  provider: openai-chat-completions
  config:
    api_key: "..."
    model: gpt-4o
```

CLI:
```sh
python scripts/generate_config.py --problem 4 --run-name p4_pilot \
    --judge-model my_judge ...
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml \
    --stage judge,analyze
```

### 6) analyze — cell 별 집계

`scripts/stages/analyze.py:run()` 가 `judge.jsonl` + `retrieve.jsonl` 을 join 해서 cell 마다 dict 한 개:

```json
{
  "cells": [
    {
      "cell": "search_limit=10",
      "sweep": {"search_limit": 10},
      "n": 5,
      "accuracy": 0.6,
      "accuracy_std": 0.49,
      "mean_recall": 0.55,
      "overall_recall": 0.5,
      "total_fact_hits": 8,
      "total_supporting_facts": 16,
      "mean_llm_time": 1.23,
      "mean_num_episodes": 9.4,
      "mean_tokens_per_query": 4523.0,
      "mean_input_token": 4321.0,
      "mean_output_token": 202.0,
      "by_category": {"single-session-user": {...}, ...},
      "by_tool": {"ToolSelectAgent": {...}, ...}
    }
  ]
}
```

#### 옵션 플래그 두 개

- `--decompose-multisession` (#6) → cell 마다 `ms_accuracy`, `others_mean_accuracy`, `ms_vs_others_gap` 추가
- `--pareto` (#12) → 별도 `pareto` key 에 `(search_limit, accuracy, mean_tokens_per_query)` 점들 search_limit 오름차순 정렬

#### reuse-run (#6, #12)

`run_cfg.reuse_run` 이 설정돼 있으면 다른 run 의 `judge.jsonl` 을 읽어 새 분석. ingest/retrieve/judge 재실행 불필요 — 같은 데이터에 대한 후처리만.

```sh
python scripts/generate_config.py --problem 6 --run-name p6_from_p4 \
    --reuse-run p4_pilot --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p6_from_p4.yaml \
    --stage analyze --decompose-multisession
```

### 7) 산출 디렉토리

```
results/p4_pilot/
  ingest.jsonl                        # 4-C 산출
  retrieve.jsonl                      # cell × question, chunks + tokens + recall
  generate.jsonl                      # cell × question, model_answer
  judge.jsonl                         # generate.jsonl + llm_score
  analyze.json                        # cells / pareto / meta
  _cells/cell_000/locomo_raw.json     # LoCoMo subprocess raw output
  p4_pilot_judge_*.yml                # judge swap 임시 configuration (자동 생성)
```

### 8) 흔한 실패 케이스

| 증상 | 원인 |
|---|---|
| `[retrieve] sweep keys ['message_sentence_chunking'] affect ingest output ...` | sweep 에 chunking 넣음 → fixed 로 옮기고 chunk 별로 별도 run |
| `[retrieve] sweep keys ['summarization_enabled'] are config-only ...` | sweep 에 summarization 넣음 → fixed 로 옮기거나 제거 |
| `judge.llm_model_id=... is not defined under resources.language_models` | profile 에 `judge_llm` 블록 안 넣고 `--judge-model` 로 미정의 ID 지정 |
| `retrieve.jsonl missing` (generate stage) | retrieve 가 도중에 죽었거나 안 돌림 → retrieve 재실행 |
| `generate.jsonl missing` (judge stage) | retrieve 가 generate.jsonl 도 emit 한다는 D-005 패턴 기억 — retrieve 재실행 |
| `judge.jsonl missing` (analyze stage) | judge stage 안 돌림 / 도중 사망 |
| `accuracy: null` for some cell | 그 cell 의 모든 행 `llm_score` 가 None — judge call 실패 (rate-limit, key 오류 등) |
| LoCoMo subprocess timeout | `locomo_search.py` 본체 옵션. wrapper 손 못 댐 |

### 9) cell 단위 재실행 정책

retrieve 부터는 **idempotency 마커가 없음** (ingest 와 다름). retrieve 가 도중에 죽으면 재실행 시 모든 cell 처음부터.

**부분 재실행 패턴**:

#### 패턴 A — 작은 sweep 으로 검증 → 큰 sweep 으로 본 실행
```sh
# 작게 (k=10 만, length=5)
python scripts/generate_config.py --problem 4 --run-name p4_smoke \
    --k-list 10 --length 5 --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p4_smoke.yaml \
    --stage retrieve,judge,analyze

# 본 실행 (k 5개 × 500 question)
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml \
    --stage retrieve,judge,analyze
```

#### 패턴 B — judge 만 재실행 (retrieve 비용 절감)
generate.jsonl 까지 만들어졌으면 judge LLM 만 바꿔:
```sh
python scripts/generate_config.py --problem 4 --run-name p4_full \
    --judge-model my_judge_v2 --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml \
    --stage judge,analyze
```

#### 패턴 C — analyze 만 (#6 / #12 reuse-run)
이미 있는 다른 run 의 judge.jsonl 을 새 분석으로:
```sh
python scripts/generate_config.py --problem 12 --run-name p12_from_p4 \
    --reuse-run p4_full --model-profile my_model --db-profile my_db
python scripts/run_pipeline.py --config configs/runs/p12_from_p4.yaml \
    --stage analyze --pareto
```

### 10) 전체 흐름 한눈에

```
generate_config (4-A/4-B)         configs/runs/{name}.yaml
  ↓                               configs/generated/{name}_configuration.yml
ingest (4-C)                      results/{name}/ingest.jsonl  (idempotent)
  ↓
retrieve (4-D 3)                  results/{name}/retrieve.jsonl
                                  results/{name}/generate.jsonl   (D-005)
  ↓
generate (4-D 4) — verify only
  ↓
judge (4-D 5)                     results/{name}/judge.jsonl
  ↓
analyze (4-D 6)                   results/{name}/analyze.json
                                  (cells / pareto / by_category / by_tool)
```

### 11) 다음 단계 (이 문서 범위 외)

- **반복 실행 (N runs)**: `n_runs > 1` 은 현재 `NotImplementedError`. σ×2 자동 판정 / 파일럿 wrapper 는 future work (`docs/msr/msr_eval_tool_todo_pr7.md`).
- **chunk on/off 자동화**: 현재는 `--run-name` 두 개로 수동 분리. 자동화 wrapper 는 future work.
- **EDWIN1/EDWIN3 prompt 적용**: hook 자리만 있고 실제 적용 미구현 (D-003).

---

# Part 2 — 도구 동작 원리

> 응용 / 디버깅 시점에 펼쳐봅니다. 첫 실행만 할 거면 안 봐도 됩니다.

## 1단계: 기존 코드 vs PR7 추가 코드

PR7 은 **기존 평가 코드를 wrapping** 한 도구. 새로 만든 게 아니라 위에 한 겹 씌운 것.

### PR7 이전부터 있던 코드 (PR7이 안 건드림)

```
evaluation/retrieval_agent/
  ├─ longmemeval_test.py       ← LongMemEval 데이터셋 로딩 + ingest + search
  │     • load_longmemeval_dataset()
  │     • longmemeval_ingest()
  │     • longmemeval_search()
  ├─ hotpotQA_test.py
  ├─ locomo_ingest.py / locomo_search.py / locomo_delete.py
  └─ ...
evaluation/utils/
  └─ agent_utils.py            ← process_question(), 토큰/recall 집계
```

확인 방법: `git log --all --oneline -- evaluation/retrieval_agent/longmemeval_test.py` 의 모든 커밋이 PR7 머지(`8824f55`) 이전. PR7 의 `git diff --stat` 결과에도 `evaluation/` 경로가 한 줄도 없음.

**의미**: 데이터셋 로딩, ingest, search 같은 핵심 로직은 PR7 이전 코드 그대로. `length: 500`, `split: longmemeval_s_cleaned` (eval_claude 에서 통일됨; 이전엔 `longmemeval_s`) 의 의미와 동작도 기존 코드의 것이지 PR7 이 새로 정의한 게 아님.

### PR7 이 새로 만든 것 (총 32 파일, 본체)

```
scripts/                        ← 새 wrapper 도구 본체
  ├─ generate_config.py         ← 옵션 4-way merge → run YAML 생성
  ├─ run_pipeline.py            ← stage 순서대로 실행
  ├─ _merge.py                  ← deep_merge / yaml IO 유틸
  └─ stages/
      ├─ ingest.py              ← evaluation/retrieval_agent/*_ingest 함수를 호출
      ├─ retrieve.py            ← agent_utils.process_question 호출
      ├─ generate.py            ← (no-op, retrieve 가 같이 emit)
      ├─ judge.py               ← LLM 채점 호출
      └─ analyze.py             ← jsonl 합쳐 cell 별 집계
configs/                        ← 옵션 정의 (base/problems/profiles/runs)
prompts/EDWIN1.txt, EDWIN3.txt  ← placeholder
docs/USAGE.md, DECISIONS.md, RESEARCH.md
```

### 둘이 어떻게 만나나

PR7 wrapper 가 기존 코드를 부르는 방식은 두 가지:

1. **import 호출** — LongMemEval / HotpotQA. Python 함수를 그대로 import.
   - `scripts/stages/ingest.py:38-47`:
     ```python
     from evaluation.retrieval_agent.longmemeval_test import (
         load_longmemeval_dataset, longmemeval_ingest,
     )
     dataset = load_longmemeval_dataset(length=..., split=...)  # 기존 함수
     asyncio.run(longmemeval_ingest(dataset, config_path, session_id))
     ```
   - `scripts/stages/retrieve.py:121-135` 의 `agent_utils.process_question()` 도 기존 함수.

2. **subprocess 호출** — LoCoMo. CLI 형태로만 동작하게 짜인 기존 스크립트라 subprocess 로 띄움.
   - `scripts/stages/ingest.py:75-83`:
     ```python
     cmd = [sys.executable, ".../locomo_ingest.py", "--data-path", ..., "--config-path", ...]
     subprocess.run(cmd, ...)
     ```

### 한 줄 정리

| 무엇이 | 어디서 정의 | PR7 책임 범위 |
|---|---|---|
| `length`, `split` 의 동작 | 기존 `load_longmemeval_dataset` | 값을 넘겨주기만 |
| `prepend_user_prefix`, `message_sentence_chunking` | 기존 `longmemeval_test.py` 가 configuration.yml에서 읽음 | configuration.yml에 값을 써주기만 |
| `search_limit` | 기존 `process_question(search_limit=...)` 인자 | sweep cell 마다 그 인자로 넘기기만 |
| `test_target` 분기 (Memmachine/ToolSelect/llm) | 기존 agent 클래스들 | 어떤 클래스를 쓸지 분기만 |
| sweep / fixed / cell 개념 | (기존엔 없음) | **PR7 이 새로 도입** |
| 4-way merge / run YAML 박제 | (기존엔 없음) | **PR7 이 새로 도입** |
| stage 분리 / jsonl 산출 / analyze 집계 | (기존엔 일부만) | **PR7 이 새로 도입** |

**즉**: "무엇을 평가할지(데이터셋 로딩 + 실제 검색/답변)는 기존 코드, 어떻게 옵션을 묶고 반복할지(sweep + cell + jsonl)는 PR7" 가 구분선.

---


---

# Part 3 — Advanced / 부록

> 특수 케이스. 필요할 때만 펼쳐봅니다.

## 2단계: `longmemeval_oracle` 써도 동작하나?

**결론**: 코드는 동작함. 평가 의미가 달라져서 p4 의 목적엔 안 맞음.

### 코드 관점 — 동작함

`split` 값이 코드에서 흐르는 경로 (`evaluation/retrieval_agent/longmemeval_test.py:294-303`):

```python
def load_longmemeval_dataset(length: int, split: str):
    split_file = split if split.endswith(".json") else f"{split}.json"
    try:
        dataset = load_dataset("xiaowu0162/longmemeval-cleaned", split=split)  # 그대로 전달
        num_rows = min(length, len(dataset))
        records = dataset.select(range(num_rows)).to_list()
    except Exception:
        # fallback: f"{split}.json" 파일명으로 직접 다운로드
        ...
```

핵심: split 이름은 **유효성 검사 없이** 그대로 HuggingFace 에 넘겨짐. PR7 wrapper 도 이름을 검증 안 함. `xiaowu0162/longmemeval-cleaned` repo 에 그 이름의 split 이 존재하기만 하면 동작. 일반적으로:

| split 이름 | 파일명 | 약 sample 수 |
|---|---|---|
| `longmemeval_s` | longmemeval_s.json | ~500 (small haystack) |
| `longmemeval_m` | longmemeval_m.json | ~500 (medium haystack, 더 긴 history) |
| `longmemeval_oracle` | longmemeval_oracle.json | ~500 (정답에 필요한 dialog만) |

`load_longmemeval_dataset()` 이후 normalize 코드 (`longmemeval_test.py:325-336`) 가 `question` / `answer` / `question_type` / `haystack_sessions` 만 사용. oracle 도 이 4 필드 구조가 같아서 ingest/retrieve/judge 다 통과.

### 바꾸는 방법 — `--split` CLI 가 없어 우회

`generate_config.py` 의 CLI 인자(`scripts/generate_config.py:49-83`)에 `--split` 없음. 세 가지 길:

**방법 A — p4.yaml 직접 수정 (영구)**
```yaml
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_oracle
```

**방법 B — JSON override (일회성, 권장)**
```json
{
  "problem": 4,
  "run_name": "p4_oracle",
  "configuration": {"model_profile": "my_model", "db_profile": "my_db"},
  "benchmark": {"split": "longmemeval_oracle"},
  "sweep": {"search_limit": [10, 20]}
}
```
```sh
python scripts/generate_config.py --from-json configs/runs/oracle_override.json
```

**방법 C — 생성된 run YAML 직접 편집**

세 방법 모두 deep_merge 가 받아주고 stage 진행에 영향 없음.

### 평가 의미 관점 — p4 의도와 안 맞음

- **`longmemeval_s`/`longmemeval_m`**: haystack 안에 정답과 무관한 잡담이 잔뜩. retrieve 가 잡음 속에서 정답을 골라내야 함 → retrieve 능력 + answer LLM 능력 둘 다 측정.
- **`longmemeval_oracle`**: haystack 에 정답에 진짜 필요한 dialog 만. retrieve 가 별로 안 중요 → answer LLM 능력만 측정.

p4 목적은 "k(=search_limit) 늘릴 때 정확도가 단조증가하는가, 비단조인가" 인데 oracle 에선:
- haystack 자체가 작아 k=10 만으로도 거의 다 retrieve 됨
- k 늘려도 더 가져올 게 없음
- cell 5개 accuracy 차이가 거의 없어 신호 안 잡힘

**즉**:
- ✅ 도구 정상 작동 빠른 smoke 테스트용으로 좋음 (HF 다운만 되면)
- ✅ "answer LLM 자체 baseline" 측정용으론 좋음
- ❌ p4 의 "k sweep 비단조성" 검증엔 부적합. 이걸 보려면 `longmemeval_s` 그대로.

---

## 3단계: 웹 접속 없는 환경에서 LongMemEval 쓰기

### 현재 코드 한계

기존 함수 `load_longmemeval_dataset` (`evaluation/retrieval_agent/longmemeval_test.py:294-323`) 는 인터넷을 두 번 시도:

```python
try:
    dataset = load_dataset("xiaowu0162/longmemeval-cleaned", split=split)
    # HuggingFace datasets 라이브러리: 캐시 없으면 인터넷
except Exception:
    data_path = hf_hub_download(repo_id="xiaowu0162/longmemeval-cleaned",
                                repo_type="dataset", filename=split_file)
    # HuggingFace Hub: 캐시 없으면 인터넷
```

PR7 wrapper 는 이걸 손대지 않고 그대로 부름. "미리 받은 JSON 경로를 직접 지정한다" 는 옵션이 코드에 없음. 두 우회로 중 하나 필요.

### 옵션 A: HF 캐시 옮기기 (코드 수정 0줄, 추천)

위 두 함수는 **같은 캐시 디렉토리** 를 봄. 인터넷 머신에서 캐시 채운 뒤 통째로 오프라인 머신에 복사하고 오프라인 모드 켜면 끝.

#### 1. 인터넷 머신에서 캐시 채우기
```sh
pip install datasets huggingface_hub
python - <<'EOF'
from huggingface_hub import hf_hub_download
for fn in ["longmemeval_s.json", "longmemeval_oracle.json"]:
    p = hf_hub_download(
        repo_id="xiaowu0162/longmemeval-cleaned",
        repo_type="dataset",
        filename=fn,
    )
    print("got:", p)
EOF
```

캐시 위치:
```
~/.cache/huggingface/hub/
  datasets--xiaowu0162--longmemeval-cleaned/
    blobs/<sha>...
    snapshots/<commit_hash>/
        longmemeval_s.json -> ../../blobs/<sha>
        longmemeval_oracle.json -> ../../blobs/<sha>
    refs/main
```

> primary path(`load_dataset`)도 함께 캐시하고 싶으면:
> ```python
> from datasets import load_dataset
> load_dataset("xiaowu0162/longmemeval-cleaned", split="longmemeval_s")
> ```
> `~/.cache/huggingface/datasets/` 도 채워짐. 하지만 fallback 만 있어도 PR7 도구는 동작.

#### 2. 오프라인 머신으로 캐시 통째 복사
```sh
# 인터넷 머신
tar czf hf_cache.tgz -C ~ .cache/huggingface
# 오프라인 머신
tar xzf hf_cache.tgz -C ~
```

또는 `HF_HOME` 환경변수로 캐시 위치를 repo 내부로 옮기는 것도 가능.

#### 3. 오프라인 머신에서 환경변수 켜고 실행
```sh
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1   # primary path까지 캐시한 경우만
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage ingest
```

**장점**: PR7/기존 코드 0줄 수정. p4.yaml 의 `split` 만 캐시한 split 이름으로.
**단점**: 캐시 디렉토리 구조가 낯섦. snapshot symlink 끊기지 않게 tar 통째 복사.

### 옵션 B: 짧은 wrapper 패치 (직관적, ~15줄)

p4.yaml 에 `benchmark.local_path` 추가 가능하게 PR7 wrapper 수정.

`scripts/stages/ingest.py` 의 `_ingest_longmemeval` 패치 예시:
```python
def _ingest_longmemeval(run_cfg, config_path, session_id):
    from evaluation.retrieval_agent.longmemeval_test import (
        load_longmemeval_dataset, longmemeval_ingest,
    )
    bench = run_cfg["benchmark"]

    local_path = bench.get("local_path")
    if local_path:
        import json
        with open(local_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        dataset = raw[: int(bench["length"])]
        for r in dataset:
            r.setdefault("question_type", "unknown")
            r.setdefault("haystack_sessions", [])
            r["split"] = bench.get("split", "local")
    else:
        dataset = load_longmemeval_dataset(
            length=int(bench["length"]), split=bench["split"]
        )

    asyncio.run(longmemeval_ingest(dataset, config_path, session_id))
    return {"benchmark": "longmemeval", "num_questions": len(dataset)}
```

`retrieve.py:88-90` 의 `_run_longmemeval_cell` 도 같은 분기 추가. 두 곳 다 해야 함 (ingest 와 retrieve 가 같은 dataset 을 따로 로드).

p4.yaml:
```yaml
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_s_cleaned
  local_path: /home/user/data/longmemeval_s_cleaned.json
```

**장점**: 캐시 구조 신경 안 쓰고 평범한 JSON 한 개만 두면 됨.
**단점**: PR7 코드 수정 필요. 후속 PR.

### 옵션 C: `benchmark.data_path` 로 wrapper 가 직접 로드 (eval_claude 신규, 채택됨)

eval_claude 에서 옵션 B 의 아이디어가 본체에 머지됨. p3 / p4 problem yaml 이 default 로:

```yaml
# configs/problems/p4.yaml
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_s_cleaned
  data_path: evaluation/data/longmemeval_s_cleaned.json
```

그 경로에 파일을 두면 wrapper 가 HF 호출 없이 바로 읽음 (`scripts/stages/_common.py:load_longmemeval_local`). `_ingest_longmemeval` / `_run_longmemeval_cell` 양쪽이 자동 분기 — `bench.get("data_path")` 가 있으면 local, 없으면 기존 HF path.

다른 위치/파일을 쓰려면:
```yaml
benchmark:
  data_path: /abs/path/longmemeval_oracle_cleaned.json   # 절대경로
```
또는 problem yaml 의 그 줄을 주석 처리하면 HF online 으로 fallback.

generate_config 시점에 상대경로는 절대경로로 resolve 됨 (PR #20 흐름). 파일이 없으면 ingest 진입 시 명시적 `FileNotFoundError`(찾은 절대경로 포함).

### 어느 쪽?

| 상황 | 추천 |
|---|---|
| 단순 / repo 안에 파일 둠 | **옵션 C** (zero-config, 기본 동작) |
| 파일을 외부에 두거나 split 여러 개 자주 교체 | 옵션 C 의 `data_path` 를 절대경로로 override |
| HF 그대로 쓰고 싶음 (인터넷 가능) | problem yaml 의 `data_path:` 한 줄 주석 처리 → 옵션 A 또는 native HF |
| 캐시 구조까지 그대로 미러 (다른 도구도 같이 쓸 때) | 옵션 A (캐시 통째 복사 + `HF_HUB_OFFLINE=1`) |
| 팀이 계속 쓰는 wrapper 확장 | 옵션 B (eval_claude 가 이미 구현 — 옵션 C) |
| HotpotQA(p2) 도 오프라인 | 같은 패턴 가능 (HotpotQA 도 `data_path` 추가 필요. 현재 p2.yaml 엔 없음 — 후속 작업) |

---

## 4-B 부록: rrf-hybrid (bm25 + identity) 쓰기

### 시나리오와 한계

`my_model.yaml` 에서 reranker 로 `rrf-hybrid` 를 쓰고 싶다. rrf-hybrid 는 **여러 reranker 를 RRF 로 결합** 하는 메타 reranker 라 `resources.rerankers` 에 결합 대상 + hybrid 자체가 동시에 등록돼 있어야 함 (`reranker_conf.py:112-120` `RRFHybridRerankerConf.reranker_ids: list[str]` 필수).

PR7 초기 wrapper 는 `model_profile["reranker"]` (단일) 만 받아 한 항목만 등록했음. 후속 패치로 **`rerankers` (list) + `primary_reranker` (선택)** 형식을 받게 변경. 이로써 동일 profile 안에서 여러 reranker 등록 + hybrid 결합이 가능해짐.

### identity + bm25 의 의미

- identity = 원래 retrieval (벡터 유사도) 순서를 그대로
- bm25 = 어휘 매칭 점수
- rrf-hybrid = 두 순위를 RRF (Reciprocal Rank Fusion) 로 결합

즉 "의미적 검색 + 어휘 매칭 보강" 패턴. 합리적.

### `my_model.yaml` 새 형식 — rrf-hybrid 케이스

```yaml
embedder:
  id: my_embedder
  provider: openai
  config:
    api_key: "<OPENAI_API_KEY>"
    base_url: https://api.openai.com/v1
    model: text-embedding-3-small
    dimensions: 1536

rerankers:
  - id: my_bm25                        # ◄── 첫 축
    provider: bm25
    config:
      k1: 1.5
      b: 0.75
      epsilon: 0.25
      language: english
      tokenizer: default
  - id: my_identity                    # ◄── 두 번째 축
    provider: identity
    config: {}                         # IdentityRerankerConf 는 키 0개
  - id: my_hybrid                      # ◄── 둘을 RRF 로 결합
    provider: rrf-hybrid
    config:
      reranker_ids: [my_bm25, my_identity]
      k: 60                            # default 60. RRF 의 k 파라미터

primary_reranker: my_hybrid            # ◄── 위쪽 (episodic_memory / retrieval_agent) 이 가리킬 id

llm_model:
  id: my_llm
  provider: openai-responses
  config:
    api_key: "<OPENAI_API_KEY>"
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
```

### 생성될 configuration.yml 의 reranker 부분

```yaml
episodic_memory:
  long_term_memory:
    reranker: my_hybrid                # ◄── primary_reranker
retrieval_agent:
  reranker: my_hybrid                  # ◄── primary_reranker
resources:
  rerankers:
    my_bm25:
      provider: bm25
      config: { k1: 1.5, b: 0.75, ... }
    my_identity:
      provider: identity
      config: {}
    my_hybrid:
      provider: rrf-hybrid
      config:
        reranker_ids: [my_bm25, my_identity]
        k: 60
```

### 단일 reranker 도 새 형식

기존 `reranker:` (dict) 는 더 이상 받지 않음. 단일도 list 1개 항목으로 적어야 함. `primary_reranker` 는 생략 가능 (없으면 첫 항목 자동 선택):

```yaml
rerankers:
  - id: my_reranker
    provider: bm25
    config: { ... }
# primary_reranker 생략 → my_reranker 가 자동 선택됨
```

### 다른 hybrid 조합 cookbook

- bm25 + cross-encoder: 어휘 + 의미 cross-encoder 결합
  ```yaml
  rerankers:
    - id: my_bm25
      provider: bm25
      config: {}
    - id: my_ce
      provider: cross-encoder
      config: { model_name: cross-encoder/qnli-electra-base }
    - id: my_hybrid
      provider: rrf-hybrid
      config: { reranker_ids: [my_bm25, my_ce], k: 60 }
  primary_reranker: my_hybrid
  ```
- bm25 + cohere (Cohere reranker)
  ```yaml
  rerankers:
    - id: my_bm25
      provider: bm25
      config: {}
    - id: my_cohere
      provider: cohere
      config:
        cohere_key: "<COHERE_API_KEY>"
        model: rerank-english-v3.0
    - id: my_hybrid
      provider: rrf-hybrid
      config: { reranker_ids: [my_bm25, my_cohere], k: 60 }
  primary_reranker: my_hybrid
  ```

### 검증

`generate_config.py` 의 `_validate_and_normalize_rerankers()` 가 generate 시점에 명시적 `ValueError` 로 잡는 항목:
- legacy `reranker:` (단일 dict) 또는 `reranker:` 와 `rerankers:` 동거
- `rerankers:` 누락 / dict 로 적힘 / 빈 list
- entry 의 `id` 또는 `provider` 누락 / 중복 `id`
- `config:` 가 mapping 이 아님
- `primary_reranker` 가 list 안에 없음
- rrf-hybrid 의 `reranker_ids` 가 비어있음 / list[str] 아님 / 미지의 id 참조 / 자기 참조

전체 메시지 표는 4-B (7) 흔한 실패 케이스 참고. 이외 (provider 별 config 필드 검증, api_key 필수 등) 는 ingest 시점에 MemMachine 본체 `RerankersConf.parse()` (`reranker_conf.py:189-237`) 와 `*_conf.py` 의 Pydantic 모델이 잡음.

`scripts/test_generate_config_rerankers.py` 에 위 16 케이스가 unit test 로 박혀 있음:
```sh
uv run pytest scripts/test_generate_config_rerankers.py -v
```

---

