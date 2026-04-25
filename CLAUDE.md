# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

MemMachine is a **uv workspace** (see top-level `pyproject.toml`) composed of
three Python packages plus a TypeScript client:

- `packages/common/` — `memmachine_common`: shared REST API contracts and types.
- `packages/server/` — `memmachine_server`: server, memory layers, MCP servers,
  retrieval agent. This is the bulk of the code.
- `packages/client/` — `memmachine_client`: Python SDK.
- `packages/ts-client/` — TypeScript client (separate npm project).
- `evaluation/`, `integrations/`, `examples/`, `tools/` — non-shipped helpers.

`AGENTS.md` is the canonical command reference; `STYLE_GUIDE.md` covers tooling.
This file captures only what's non-obvious or easy to get wrong.

## Common Commands

Always run from the repo root unless noted.

```bash
# Install all workspace deps (creates .venv automatically)
uv sync                       # base deps
uv sync --all-extras          # include gpu / nebula extras

# Lint, format, type-check
uv run ruff check
uv run ruff format
uv run ty check packages      # NOTE: type checker is `ty` (Astral), not mypy

# Tests — `addopts` in pyproject.toml defaults to `-m "not integration"`
uv run pytest                 # unit tests only
uv run pytest -m integration  # integration tests (requires services)
uv run pytest -m slow
uv run pytest packages/server/server_tests/path/to/test_x.py::test_fn
uv run pytest -k "create_memory"

# Cyclomatic complexity gate (enforced separately, max=10 on src/)
uv run complexipy packages/server/src packages/client/src packages/common/src
```

TypeScript client (run inside `packages/ts-client/`):

```bash
npm install && npm run build
npm run lint && npm run format
npm run test -- -t "test name"
```

Server / MCP entry points (installed by `memmachine-server` package):
`memmachine-server`, `memmachine-mcp-stdio`, `memmachine-mcp-http`,
`memmachine-configure`, `memmachine-nltk-setup`. Defined in
`packages/server/pyproject.toml [project.scripts]`.

## Architecture

The server has three memory layers, each in its own subpackage under
`packages/server/src/memmachine_server/`:

- **`episodic_memory/`** — conversational long-term memory. Graph-backed
  (Neo4j or Nebula via `vector_graph_store`) plus `short_term_memory/` for
  in-session context and `declarative_memory/` for distilled facts. Public
  surface: `EpisodicMemory` + `EpisodicMemoryParams`,
  `LongTermMemory` + `LongTermMemoryParams`.
- **`semantic_memory/`** — profile memory (SQL-backed user facts/preferences).
- **`retrieval_agent/`** — three-way retrieval router. Agents in
  `retrieval_agent/agents/`: `ToolSelectAgent` (router) → `ChainOfQueryAgent`,
  `SplitQueryAgent`, `MemMachineAgent` (memory-only fallback).

Configuration is YAML-driven through
`packages/server/src/memmachine_server/common/configuration/episodic_config.py`.
Two parallel models matter: full configs (e.g. `LongTermMemoryConf`) and
*partial* configs (`*ConfPartial`) used for layered/merged YAML — when adding
a new field you must add it to **both** to avoid silent drops on round-trip.

`common/resource_manager/` is the dependency-injection seam: embedders,
rerankers, language models, vector graph stores are all resolved by ID from
`ResourceManagerImpl`. Evaluation code (`evaluation/utils/agent_utils.py`)
demonstrates the canonical wiring pattern.

Server entrypoint is `memmachine_server.server.app:main` (FastAPI). MCP
servers live alongside in `server/mcp_stdio.py` and `server/mcp_http.py`.

Sample configs that the server can boot from are in `sample_configs/`
(`episodic_memory_config.{cpu,gpu,nebula}.sample`, `server_config.sample`).
The runtime expects `configuration.yml` (gitignored).

## Evaluation Harness

`evaluation/retrieval_agent/` runs LongMemEval, LoCoMo, and HotpotQA against
the retrieval agent stack. Two scripts orchestrate everything:

- `run_test.sh` — one benchmark / one phase (ingest|search) at a time.
- `run_benchmark_matrix.sh` — sweeps the full matrix
  (`chunk × prefix × k` for LongMemEval, `mode` for LoCoMo/HotpotQA).

The matrix script **mutates `configuration.yml` in place during the run** to
toggle YAML keys (`evaluation.longmemeval.prepend_user_prefix`,
`episodic_memory.long_term_memory.message_sentence_chunking`) and restores it
on exit via a `trap`. Be aware that whatever value the inner LongMemEval loop
ends on remains set when LoCoMo/HotpotQA run afterward in the same invocation.
See `README_MSR.md` for the full toggle behavior, including why
`--skip-ingest` is unsafe across `chunk` changes (chunking affects ingest, not
just search).

The `evaluation/retrieval_skill/` directory is excluded from Ruff
(`pyproject.toml [tool.ruff].exclude`) — do not assume project-wide style
applies there.

## Conventions That Bite

- **Pytest default excludes integration tests** (`addopts = ["-m", "not
  integration"]` in root `pyproject.toml`). Write integration coverage with
  `@pytest.mark.integration` and run with `-m integration`.
- **Per-directory Ruff ignore lists** in `pyproject.toml [tool.ruff.lint.per-file-ignores]`
  are aggressive for `evaluation/`, `examples/`, `integrations/`, `tools/`,
  and tests. Production code (under `packages/*/src/`) gets the full ruleset
  including `D` (pydocstyle, Google convention) and `ANN` (annotations).
- **Type hints**: use built-in generics (`list[str]`, `dict[str, X]`). The
  type checker is `ty`, not mypy — some mypy idioms won't apply.
- **Async**: server modules are async-first. Don't mix blocking I/O into
  `async def` paths; reuse the existing `async_with` helper and the
  `ResourceManagerImpl` async getters.
- **Commits must be signed** (`git commit -sS`). CI rejects unsigned commits
  (`CONTRIBUTING-CORE.md §5`).
- **Don't add new top-level paths under `packages/`** — Ruff config comment
  enforces this convention.

## Branch-Specific Notes

If `README_MSR.md` is present, this branch carries the MSR (Mem Machine
Self-Reproduction) evaluation modifications: LongMemEval `User:` prefix
toggle, `--search-limit` k-sweep flag, and the `chunk` axis in
`run_benchmark_matrix.sh`. Status of those modifications versus the
reproduction design is tracked in `docs/msr/`.
