# PR #7 평가 도구 — 문제4 예제 walkthrough (한국어)

> 세션 메모. 문제4(LongMemEval k sweep) 를 예시로 PR #7 평가 도구가 옵션을 어떻게 받아 어떻게 처리하는지 정리.

---

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

**의미**: 데이터셋 로딩, ingest, search 같은 핵심 로직은 PR7 이전 코드 그대로. `length: 500`, `split: longmemeval_s` 의 의미와 동작도 기존 코드의 것이지 PR7 이 새로 정의한 게 아님.

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
  split: longmemeval_s
  local_path: /home/user/data/longmemeval_s.json
```

**장점**: 캐시 구조 신경 안 쓰고 평범한 JSON 한 개만 두면 됨.
**단점**: PR7 코드 수정 필요. 후속 PR.

### 어느 쪽?

| 상황 | 추천 |
|---|---|
| 일회성 평가 | 옵션 A (캐시 통째 복사 + `HF_HUB_OFFLINE=1`) |
| 팀이 계속 사용, 데이터 경로 명시적 | 옵션 B (wrapper 패치) |
| HotpotQA(p2) 도 오프라인 | 둘 다 비슷하게 적용. p5(LoCoMo)는 이미 `data_path` 인자 있어 오프라인 친화 |

---

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

**두 부분으로 나뉜 이유 — "이름표 + 정의" 분리**: 같은 LLM 이 답변·judge 둘 다, 같은 reranker 가 retrieval_agent·long_term_memory 양쪽에서 쓰임. 변수 선언(`resources`)과 변수 사용(`retrieval_agent.llm_model`) 의 분리.

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

reranker:
  id: my_reranker
  provider: bm25
  config: {}
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

reranker:
  id: my_reranker
  provider: bm25
  config: {}
```

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
  split: longmemeval_s
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
| `episode_store`, `episodic_memory`, `retrieval_agent`, `resources` 의 골격 | `scripts/generate_config.py:159-223` `build_configuration_yml()` |
| reranker list → resources.rerankers + primary_reranker 처리 | `scripts/generate_config.py:154-165` |
| `message_sentence_chunking`, `prepend_user_prefix` 주입 | `scripts/generate_config.py:226-242` `_apply_fixed_to_configuration()` |
| 4-way merge (base + p4 + json + CLI) | `scripts/generate_config.py:329` `deep_merge(...)` |
| `configuration.generated_path` 박는 곳 | `scripts/generate_config.py:336-337` |

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

| 증상 | 원인 |
|---|---|
| `ERROR: --problem (or 'problem' in JSON) is required` | `--problem` 빠짐 |
| `mode=profile requires both configuration.model_profile and configuration.db_profile` | 두 인자 중 하나 누락 |
| `FileNotFoundError: configs/profiles/models/my_model.yaml` | 4-A 에서 파일 복사 안 함 또는 이름 오타 |
| `KeyError: 'embedder'` 또는 `KeyError: 'rerankers'` | profile YAML 의 yaml 들여쓰기/key 누락 |
| `model profile 'rerankers' must contain at least one entry` | rerankers 가 빈 list |
| `primary_reranker=... not found in rerankers ids ...` | `primary_reranker` 가 가리키는 id 가 rerankers 안에 없음 (오타) |
| `pydantic.ValidationError: api_key Field required` (ingest 시점) | profile YAML 의 placeholder 안 바꿈 |

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

`generate_config.py` 가 다음 두 에러를 미리 잡음:
- `model profile 'rerankers' must contain at least one entry` — list 가 빈 경우
- `primary_reranker=... not found in rerankers ids [...]` — primary 가 가리키는 id 가 rerankers 에 없는 경우 (오타 등)

이외는 ingest 단계에서 `RerankersConf.parse()` (`reranker_conf.py:189-237`) 가 잘못된 provider/필드를 잡아냄.

---

다음 메모:
- **4-C**: ingest 단독 실행, DB 적재 확인
- **4-D**: retrieve / judge / analyze
