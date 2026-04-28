# Retrieval-Agent Benchmark Configuration

All retrieval-agent benchmarks are driven by a single **`configuration.yml`** file
placed in this directory (`evaluation/retrieval_agent/configuration.yml`).

The file controls every component used during a run:

| Concern | Config section |
|---|---|
| Language model for the retrieval agent & answers | `retrieval_agent.llm_model` |
| Language model for the LLM judge (evaluation) | `retrieval_agent.judge_llm_model` (falls back to `retrieval_agent.llm_model`) |
| Embedder for long-term memory | `episodic_memory.long_term_memory.embedder` |
| Reranker | `retrieval_agent.reranker` or `episodic_memory.long_term_memory.reranker` |
| Vector graph store (Neo4j) | `episodic_memory.long_term_memory.vector_graph_store` |
| All resource definitions | `resources.embedders`, `resources.language_models`, `resources.rerankers`, `resources.databases` |

### Judge LLM configuration: three terms

The judge involves three distinct fields. They live in different files and play
different roles — keeping them straight avoids confusion:

| Term | Where | Role |
|---|---|---|
| `judge_llm:` block | model profile YAML (`configs/profiles/models/*.yaml`) | Defines the judge LLM **resource** (`id` / `provider` / `config`). Optional — omit to reuse `llm_model` for the judge. |
| `retrieval_agent.judge_llm_model` | generated `configuration.yml` | Pointer the judge runtime actually reads. `generate_config.py` populates it from the profile (or falls back to `llm_model.id`). |
| `judge.llm_model_id` / `--judge-model` | run config / CLI | Runtime override that swaps **only** the pointer to an ID already registered in `resources.language_models`. Never touches `retrieval_agent.llm_model`. |

`judge_llm.provider` must be one currently supported by
`evaluation/retrieval_agent/llm_judge.py`: `openai-responses`,
`openai-chat-completions`, or `amazon-bedrock`.

> **Current limitation**: `judge_llm:` is a single optional block, so a model
> profile can register at most one extra judge candidate alongside the answer
> LLM. Registering several judge candidates and selecting between them via
> `--judge-model` is out of scope for now and would require a list-shaped
> extension (e.g. `extra_language_models:`).

The legacy `evaluation/episodic_memory/llm_judge.py` (hardcoded to
`gpt-4o-mini`) is unrelated to this pipeline; the retrieval-agent runs use only
`evaluation/retrieval_agent/llm_judge.py`.

`run_test.sh` checks for the file at startup and exits with an error if it is
missing.

The MemMachine configuration schema also requires a `semantic_memory` section.
The samples below keep semantic memory disabled because these retrieval-agent
benchmarks do not use it directly, but `semantic_memory.config_database` must
still reference a valid SQL database ID.

---

## Quick Start

1. Copy one of the sample configurations below into
   `evaluation/retrieval_agent/configuration.yml`.
2. Fill in your API keys / connection details.
3. Install the benchmark dependencies:

```sh
cd evaluation/retrieval_agent
python -m pip install -r requirements.txt
```

`requirements.txt` installs the local MemMachine packages used by these
scripts plus `pandas` for `generate_scores.py`. `run_test.sh` checks for the
required modules before starting any search run.

Existing concurrency controls are exposed as named flags in `run_test.sh`:
`--ingest-concurrency`, `--search-concurrency`, and `--judge-concurrency`.
4. Run a benchmark:

```sh
cd evaluation/retrieval_agent
./run_test.sh wikimultihop exp1 ingest retrieval_agent 100
./run_test.sh wikimultihop exp1 search retrieval_agent 100
```

---

## Configuration Samples

### Sample 1 — OpenAI models + AWS Bedrock reranker (default setup)

```yaml
episode_store:
  database: profile_storage
  with_count_cache: true

episodic_memory:
  enabled: true
  long_term_memory:
    embedder: openai_embedder
    reranker: aws_reranker_id
    vector_graph_store: my_storage_id
  long_term_memory_enabled: true
  short_term_memory:
    llm_model: openai_model
    message_capacity: 500
    summary_prompt_system: "You are an AI agent that can make summary for a list of episodes."
    summary_prompt_user: "Summarize: {summary}\n{episodes}\nYour summary (under {max_length} words):"
  short_term_memory_enabled: true

logging:
  level: INFO

retrieval_agent:
  llm_model: openai_model
  reranker: aws_reranker_id

semantic_memory:
  enabled: false
  config_database: profile_storage

resources:
  databases:
    my_storage_id:
      provider: neo4j
      config:
        uri: bolt://localhost:7687
        user: neo4j
        password: neo4j_password

    profile_storage:
      provider: postgres
      config:
        dialect: postgresql
        driver: asyncpg
        host: localhost
        port: 5432
        user: memmachine
        password: memmachine_password
        db_name: memmachine

  embedders:
    openai_embedder:
      provider: openai
      config:
        api_key: sk-...
        base_url: https://api.openai.com/v1
        model: text-embedding-3-small
        dimensions: 1536

  language_models:
    openai_model:
      provider: openai-responses
      config:
        api_key: sk-...
        base_url: https://api.openai.com/v1
        model: gpt-4o-mini

  rerankers:
    aws_reranker_id:
      provider: amazon-bedrock
      config:
        region: us-west-2
        aws_access_key_id: AKIA...
        aws_secret_access_key: ...
        model_id: amazon.rerank-v1:0

session_manager:
  database: profile_storage
```

---

### Sample 2 — Ollama (local) models + BM25 reranker

Use this when you run models locally via [Ollama](https://ollama.com/).

```yaml
episode_store:
  database: sqlite_db
  with_count_cache: true

episodic_memory:
  enabled: true
  long_term_memory:
    embedder: ollama_embedder
    reranker: bm25_reranker
    vector_graph_store: my_storage_id
  long_term_memory_enabled: true
  short_term_memory:
    llm_model: ollama_model
    message_capacity: 500
    summary_prompt_system: "You are an AI agent that summarizes episodes."
    summary_prompt_user: "Summarize: {summary}\n{episodes}\nYour summary (under {max_length} words):"
  short_term_memory_enabled: true

logging:
  level: INFO

retrieval_agent:
  llm_model: ollama_model
  reranker: bm25_reranker

semantic_memory:
  enabled: false
  config_database: sqlite_db

resources:
  databases:
    my_storage_id:
      provider: neo4j
      config:
        uri: bolt://localhost:7687
        user: neo4j
        password: neo4j_password

    sqlite_db:
      provider: sqlite
      config:
        dialect: sqlite
        driver: aiosqlite
        path: evaluation_session.db

  embedders:
    ollama_embedder:
      provider: openai          # Ollama exposes an OpenAI-compatible endpoint
      config:
        api_key: EMPTY
        base_url: http://localhost:11434/v1
        model: nomic-embed-text
        dimensions: 768

  language_models:
    ollama_model:
      provider: openai-chat-completions
      config:
        api_key: EMPTY
        base_url: http://localhost:11434/v1
        model: llama3.2

  rerankers:
    bm25_reranker:
      provider: bm25
      config:
        k1: 1.5
        b: 0.75
        epsilon: 0.25
        language: english
        tokenizer: default

session_manager:
  database: sqlite_db
```

---

### Sample 3 — AWS Bedrock (end-to-end)

```yaml
episode_store:
  database: profile_storage
  with_count_cache: true

episodic_memory:
  enabled: true
  long_term_memory:
    embedder: aws_embedder
    reranker: aws_reranker_id
    vector_graph_store: my_storage_id
  long_term_memory_enabled: true
  short_term_memory:
    llm_model: aws_model
    message_capacity: 500
    summary_prompt_system: "You are an AI agent that summarizes episodes."
    summary_prompt_user: "Summarize: {summary}\n{episodes}\nYour summary (under {max_length} words):"
  short_term_memory_enabled: true

logging:
  level: INFO

retrieval_agent:
  llm_model: aws_model
  reranker: aws_reranker_id

semantic_memory:
  enabled: false
  config_database: profile_storage

resources:
  databases:
    my_storage_id:
      provider: neo4j
      config:
        uri: bolt://localhost:7687
        user: neo4j
        password: neo4j_password

    profile_storage:
      provider: postgres
      config:
        dialect: postgresql
        driver: asyncpg
        host: localhost
        port: 5432
        user: memmachine
        password: memmachine_password
        db_name: memmachine

  embedders:
    aws_embedder:
      provider: amazon-bedrock
      config:
        region: us-west-2
        aws_access_key_id: AKIA...
        aws_secret_access_key: ...
        model_id: amazon.titan-embed-text-v2:0

  language_models:
    aws_model:
      provider: amazon-bedrock
      config:
        region: us-west-2
        aws_access_key_id: AKIA...
        aws_secret_access_key: ...
        model_id: anthropic.claude-3-5-sonnet-20241022-v2:0

  rerankers:
    aws_reranker_id:
      provider: amazon-bedrock
      config:
        region: us-west-2
        aws_access_key_id: AKIA...
        aws_secret_access_key: ...
        model_id: amazon.rerank-v1:0

session_manager:
  database: profile_storage
```

---

### Sample 4 — OpenAI-compatible endpoint (vLLM / any provider)

Works with any server that speaks the OpenAI Chat Completions protocol.

```yaml
episode_store:
  database: sqlite_db
  with_count_cache: true

episodic_memory:
  enabled: true
  long_term_memory:
    embedder: custom_embedder
    reranker: bm25_reranker
    vector_graph_store: my_storage_id
  long_term_memory_enabled: true
  short_term_memory:
    llm_model: custom_model
    message_capacity: 500
    summary_prompt_system: "You are an AI agent that summarizes episodes."
    summary_prompt_user: "Summarize: {summary}\n{episodes}\nYour summary (under {max_length} words):"
  short_term_memory_enabled: true

logging:
  level: INFO

retrieval_agent:
  llm_model: custom_model
  reranker: bm25_reranker

semantic_memory:
  enabled: false
  config_database: sqlite_db

resources:
  databases:
    my_storage_id:
      provider: neo4j
      config:
        uri: bolt://localhost:7687
        user: neo4j
        password: neo4j_password

    sqlite_db:
      provider: sqlite
      config:
        dialect: sqlite
        driver: aiosqlite
        path: evaluation_session.db

  embedders:
    custom_embedder:
      provider: openai
      config:
        api_key: your-api-key
        base_url: http://your-vllm-host:8000/v1
        model: your-embedding-model
        dimensions: 1536

  language_models:
    custom_model:
      provider: openai-chat-completions
      config:
        api_key: your-api-key
        base_url: http://your-vllm-host:8000/v1
        model: your-chat-model

  rerankers:
    bm25_reranker:
      provider: bm25
      config:
        k1: 1.5
        b: 0.75
        epsilon: 0.25
        language: english
        tokenizer: default

session_manager:
  database: sqlite_db
```

---

## Key Fields Reference

### `retrieval_agent`

| Field | Description |
|---|---|
| `llm_model` | ID of the language model used by the retrieval agent and answer generation. Must match a key under `resources.language_models`. |
| `judge_llm_model` | (Optional) ID of the language model used by the LLM judge during evaluation. Falls back to `llm_model` when unset. Must match a key under `resources.language_models`. Populated from the model profile's optional `judge_llm:` block. |
| `reranker` | ID of the reranker used by the retrieval agent. Overrides `episodic_memory.long_term_memory.reranker` when set. |

### `episodic_memory.long_term_memory`

| Field | Description |
|---|---|
| `embedder` | ID of the embedder used to index and search episodes. |
| `reranker` | Fallback reranker if `retrieval_agent.reranker` is not set. |
| `vector_graph_store` | ID of the Neo4j database used as the vector store. |
| `message_sentence_chunking` | If `true`, message episodes are chunked into sentences before embedding. Default: `false`. |

### `resources.language_models` — provider options

| Provider | Notes |
|---|---|
| `openai-responses` | OpenAI Responses API (gpt-4o, gpt-4o-mini, etc.) |
| `openai-chat-completions` | OpenAI Chat Completions API; also works with Ollama, vLLM, and any OpenAI-compatible endpoint |
| `amazon-bedrock` | AWS Bedrock Converse API |

### `resources.embedders` — provider options

| Provider | Notes |
|---|---|
| `openai` | OpenAI embeddings; also compatible with Ollama (`nomic-embed-text`, etc.) and other OpenAI-compatible endpoints |
| `amazon-bedrock` | AWS Bedrock embeddings |

### `resources.rerankers` — provider options

| Provider | Notes |
|---|---|
| `amazon-bedrock` | AWS Bedrock reranker |
| `bm25` | Local BM25 reranker, no external service needed |
| `cohere` | Cohere reranker (requires `cohere_key`) |
| `rrf-hybrid` | Reciprocal Rank Fusion combining multiple rerankers |

---

## Running Benchmarks

From `evaluation/retrieval_agent/`:

```sh
# WikiMultiHop — ingest then search 500 questions
./run_test.sh wikimultihop exp1 ingest retrieval_agent 500
./run_test.sh wikimultihop exp1 search retrieval_agent 500
./run_test.sh wikimultihop exp1 search retrieval_agent 500 --search-concurrency 2 --judge-concurrency 4

# HotpotQA validation set — 200 questions
./run_test.sh hotpotqa exp1 ingest validation retrieval_agent 200
./run_test.sh hotpotqa exp1 search validation retrieval_agent 200

# LoCoMo (default data file has 10 conversations; LENGTH is a positive integer
# capped by the data file size)
./run_test.sh locomo exp1 ingest retrieval_agent 10
./run_test.sh locomo exp1 ingest retrieval_agent 10 --ingest-concurrency 2
./run_test.sh locomo exp1 search retrieval_agent 10
./run_test.sh locomo exp1 search retrieval_agent 10 --search-concurrency 1 --judge-concurrency 4
```

Ingest runs print standardized lifecycle logs:

- `[INGEST_START] ...`
- `[INGEST_OK] ...` on success
- `[INGEST_FAIL] ...` on failure

Each ingest run also writes a status marker JSON file:

```sh
evaluation/retrieval_agent/result/ingest_status/<test>_<target>_<result_postfix>.json
```

For the full argument reference run:

```sh
./run_test.sh --help
./run_test.sh wikimultihop --help
```

---

## Deleting Ingested Data

`run_test.sh delete` removes all episodes a prior `ingest` wrote to the configured
long-term memory store for each benchmark's session key(s). Use it between runs to
reuse the same `RESULT_POSTFIX` without double-counting earlier data.

```sh
# From evaluation/retrieval_agent/
./run_test.sh locomo       exp1 delete retrieval_agent
./run_test.sh wikimultihop exp1 delete retrieval_agent
./run_test.sh hotpotqa     exp1 delete retrieval_agent
./run_test.sh longmemeval  exp1 delete retrieval_agent
```

Notes:

- `delete` ignores `SPLIT_NAME` and `LENGTH` — only `RESULT_POSTFIX` and
  `TEST_TARGET` are needed. `TEST_TARGET` is accepted for argument symmetry with
  `ingest`/`search` but is unused by the delete path.
- For LoCoMo the delete iterates all 10 conversation groups (`group_0` … `group_9`),
  since ingestion uses one session per conversation.
- For WikiMultiHop / HotpotQA the delete clears the single fixed session_id used
  by ingestion (`group1` and `hotpotqa_group` respectively).
- For LongMemEval the session_id is derived from `RESULT_POSTFIX`
  (`longmemeval_<RESULT_POSTFIX>`), matching the ingest-time session.
- Concurrency flags (`--ingest-concurrency`, `--search-concurrency`,
  `--judge-concurrency`) are rejected with `delete`.
