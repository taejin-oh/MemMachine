# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

MemMachine is an open-source long-term memory layer for AI agents (Episodic / Profile / Working memory). The repo is a Python-first **uv workspace** (`packages/client`, `packages/common`, `packages/server`) plus a TypeScript REST client and integration/example directories.

The `eval_optimize` branch (current default for evaluation work) adds a separate **LongMemEval reproduction-eval tool** on top: a 5-stage pipeline under `scripts/` that drives the existing `evaluation/retrieval_agent/` benchmark code through controlled variable sweeps. The two layers are independent — server changes here are minimal (3 Pydantic fields on `RetrievalAgentConf`); everything else lives outside `packages/`.

## Build / Lint / Test

All commands run from repo root. Python 3.12+ required (`pyproject.toml`).

```bash
uv sync                        # install (use --all-extras for optional deps)
uv run ruff check              # lint (autofix: --fix)
uv run ruff format             # format (check-only: --check)
uv run ty check packages       # type check
uv run pytest                  # full test suite (excludes integration by default)
uv run pytest -m integration   # integration tests only
uv run pytest -k "<keyword>"   # by name match
uv run pytest path/to/test_file.py::test_func  # single test
```

Pytest is configured (`pyproject.toml`) with `addopts = ["-m", "not integration"]` — integration tests are opt-in. Markers: `integration`, `slow`.

For the eval-tool (`scripts/`) and benchmark code (`evaluation/`), `per-file-ignores` in `pyproject.toml` relax docstring/path/print/SLF rules so research code can stay terse. When adding files there, check the existing ignore set before adding inline `# noqa:` comments.

The TypeScript REST client lives at `packages/ts-client/` with its own `npm install / npm run build / npm run lint / npm run test`. See [AGENTS.md](AGENTS.md) for full TS guidance.

## Running the Server

```bash
./memmachine-compose.sh start  # Docker compose: server + Neo4j + Postgres
```

## Architecture — Server (production code under `packages/`)

Three Python packages, all installed via `uv` workspace:

- **`packages/common/src/memmachine_common/`** — shared REST API surface, episode store contracts.
- **`packages/server/src/memmachine_server/`** — actual server. Subsystems:
  - `episodic_memory/` (long-term graph-based + short-term capacity-bounded; long-term store is Neo4j via `LongTermMemory` + `DeclarativeMemory`)
  - `semantic_memory/` (user facts in SQL; disabled by default in eval configs)
  - `retrieval_agent/` (LLM-orchestrated retrieval strategies; reads `RetrievalAgentConf`)
  - `common/configuration/` — **Pydantic-validated** config loaded from `configuration.yml`. Most components consume their config attribute-style after `Configuration.load_yml_file(path)`. Extras in YAML are silently ignored (Pydantic default).
- **`packages/client/`** — Python SDK, **`packages/ts-client/`** — TypeScript client.

`integrations/` and `examples/` are downstream demos (LangChain, CrewAI, etc.) and are not imported by server code.

## Architecture — Evaluation (LongMemEval reproduction)

Two coexisting layers; new work belongs in the second.

**Legacy** ([evaluation/retrieval_agent/](evaluation/retrieval_agent/)): direct CLI scripts driven by `run_test.sh`. Still used by sibling benchmarks (HotpotQA, WikiMultiHop, LoCoMo) and by the new pipeline as importable modules.

**Reproduction pipeline** ([scripts/](scripts/)): 5-stage orchestrator over a single run YAML.

```
scripts/run_pipeline.py
  └─ scripts/stages/ingest    → results/<run>/ingest.jsonl   (idempotent: status=ok skips re-ingest)
  └─ scripts/stages/retrieve  → results/<run>/retrieve.jsonl + generate.jsonl
                                (sweep cartesian × question, both emitted in one loop)
  └─ scripts/stages/generate  → verifier (retrieve emits generate.jsonl)
  └─ scripts/stages/judge     → results/<run>/judge.jsonl    (llm_score + raw_response + parsed_label)
  └─ scripts/stages/analyze   → results/<run>/analyze.json   (per-cell aggregates; --decompose-multisession, --pareto opts)
```

Config layering (deep-merged top-down by `scripts/_merge.py`):

```
configs/base.yaml                            # repo defaults
+ configs/problems/p{3,4,6,12}.yaml          # problem definition (sweep / fixed / metrics)
+ configs/profiles/models/<name>.yaml        # embedder + llm_model + judge_llm + reranker
+ configs/profiles/dbs/<name>.yaml           # Neo4j + Postgres profile
+ configs/runs/<run_name>.yaml               # the run config; gitignored
= configs/generated/<run_name>_configuration.yml  # working copy that stages mutate
```

`scripts/generate_config.py` builds the generated file. `scripts/stages/_common.update_yaml_in_place()` toggles between sweep cells. **Never edit `configs/generated/` by hand** — that's the stages' working copy.

### Critical invariants when extending the pipeline

1. **`run_name` = `session_id`** ([scripts/stages/_common.py](scripts/stages/_common.py): `session_id_for()` → `eval_tool_<bench>_<run_name>`). Renaming a run disconnects retrieve from its ingest.
2. **`message_sentence_chunking` is ingest-affecting** — listed in `SWEEP_INGEST_AFFECTING_KEYS` in [scripts/stages/retrieve.py](scripts/stages/retrieve.py). It must be in `fixed:`, not `sweep:`; toggling it without re-ingest A/Bs over the same corpus.
3. **`reuse_run` forces analyze-only** ([scripts/run_pipeline.py](scripts/run_pipeline.py)). p6/p12 problem configs use this to post-process an earlier run's `judge.jsonl` without rerunning ingest/retrieve/generate/judge.
4. **`retrieval_agent.judge_llm_model` is swap-only** — [scripts/stages/judge.py](scripts/stages/judge.py)`._judge_config_path()` writes a temporary YAML; **never mutates `retrieval_agent.llm_model` (answer LLM)**. Tests in [scripts/test_stages_judge.py](scripts/test_stages_judge.py) enforce this.
5. **LongMemEval-only** on this branch. [scripts/stages/ingest.py](scripts/stages/ingest.py) and `retrieve.py` raise `ValueError` for other benchmark names. Sibling benchmarks still work via the legacy CLI.

### LongMemEval upstream alignment

[evaluation/retrieval_agent/llm_judge.py](evaluation/retrieval_agent/llm_judge.py) and [evaluation/retrieval_agent/longmemeval_test.py](evaluation/retrieval_agent/longmemeval_test.py) are aligned with `xiaowu0162/LongMemEval` upstream:

- **Judge templates** `_LME_TEMPLATE_{GENERAL,TEMPORAL,KNOWLEDGE_UPDATE,PREFERENCE,ABSTENTION}` are verbatim copies. `get_anscheck_prompt(task, ...)` routes per-task.
- **Yes/no parser** `_parse_yes_no(raw, policy)` — `lenient` (default, `'yes' in lower(raw)`) matches upstream; `strict` (whole-string) is opt-in.
- **Plain-text judge mode** `create_judge_fn(json_mode=False)` is used by the LongMemEval path. `temperature=0` is set on chat-completions text mode only (Responses API and Bedrock branches keep provider defaults — Responses rejects `temperature` on some reasoning models; Bedrock has a different shape).
- **Answer prompt policies** (5): `LME_origin_prompt` (default, upstream verbatim no-CoT), `LME_origin_cot_prompt` (upstream CoT branch), `memmachine_original` (hybrid with KNOWLEDGE UPDATES / PLANNED ACTIONS guides), `edwin1`, `edwin3`. The Pydantic `Literal[...]` in [packages/server/.../retrieval_config.py](packages/server/src/memmachine_server/common/configuration/retrieval_config.py) **must stay in sync** with `_ANSWER_PROMPT_BY_POLICY` in `longmemeval_test.py`; [test_longmemeval_test.py](evaluation/retrieval_agent/test_longmemeval_test.py)`::test_pydantic_literal_matches_policy_registry` guards drift.
- **Policy resolution precedence**: CLI > `run_cfg.evaluation.longmemeval.answer_prompt` > `configuration.yml retrieval_agent.longmemeval_answer_prompt` > Pydantic default.

## Configuration system

`packages/server/.../common/configuration/__init__.py:Configuration.load_yml_file(path)` is the single entry point. Pydantic validates known fields; unknown fields are silently ignored (no `extra="forbid"`). This means YAML keys that aren't on the schema can't be read attribute-style — if you add a new toggle the eval reads, add a field to the relevant `*Conf` class.

`retrieval_agent.longmemeval_yesno_policy` / `longmemeval_answer_prompt` / `judge_llm_model` are the eval-tool's only schema additions vs. main.

## Style / repo conventions

- See [AGENTS.md](AGENTS.md) for the full style guide (Python type hints everywhere, `pydantic` for structured I/O, `async def` consistency, snake_case modules / PascalCase classes / UPPER_SNAKE constants).
- See [DECISIONS.md](DECISIONS.md) for the design decisions behind the 5-stage split (D-001), profile/existing config modes (D-002), EDWIN prompt hook scope (D-003), file layout (D-004), and benchmark dispatch (D-006).
- See [STYLE_GUIDE.md](STYLE_GUIDE.md) for tool references.
- `docs/msr/` holds Korean reproduction-eval design docs and run plans (notably [docs/msr/testrun/](docs/msr/testrun/)). They are tracking docs, not code — but reflect intent when changing the eval pipeline.

## Workflow notes

- Avoid wide reformatting of legacy `evaluation/` code; per-file-ignores there are intentional.
- `results/`, `configs/generated/`, and `configs/runs/*.yaml` are gitignored — only `configs/runs/_example.json` is tracked.
- When `pytest` fails on a pre-commit hook, **never** `--amend`; the previous commit is what gets amended (the failed commit didn't land).
