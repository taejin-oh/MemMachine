"""Stage: retrieve (+ generate emitted in same loop).

Iterates the sweep cells. For each (sweep cell × question):
- Toggles `evaluation.longmemeval.prepend_user_prefix` in the
  configuration.yml in-place between cells.
- Calls `agent_utils.process_question()` to run retrieve + generate
  in one shot, then splits the resulting record into two jsonl rows:
    - retrieve.jsonl: chunks + perf_metrics + sweep_params
    - generate.jsonl: model_answer + latency + sweep_params
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any

from . import _common as cm

# ---------------------------------------------------------------------------
# sweep expansion
# ---------------------------------------------------------------------------


# Keys that affect ingest output (Episode storage shape) and therefore cannot
# be swept from retrieve alone — toggling them here would A/B retrieval over
# the *same* ingested corpus, defeating the experiment's intent.
SWEEP_INGEST_AFFECTING_KEYS: set[str] = {"message_sentence_chunking"}


def _validate_sweep_keys(sweep: dict[str, Any]) -> None:
    ingest_bad = sorted(k for k in sweep if k in SWEEP_INGEST_AFFECTING_KEYS)
    if ingest_bad:
        raise SystemExit(
            "[retrieve] sweep keys "
            f"{ingest_bad} affect ingest output (Episode storage shape) and "
            "cannot be swept from the retrieve stage. Move them to `fixed:` "
            "and use a separate run + ingest per value, or split the problem "
            "yaml into per-value variants."
        )


def _expand_sweep(sweep: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Return one dict per cartesian-product cell of the sweep."""
    if not sweep:
        return [{}]
    _validate_sweep_keys(sweep)
    keys = list(sweep.keys())
    value_lists = [sweep[k] if isinstance(sweep[k], list) else [sweep[k]] for k in keys]
    return [
        dict(zip(keys, combo, strict=True)) for combo in itertools.product(*value_lists)
    ]


def _resolved_params(run_cfg: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    """Merge fixed + sweep cell. Sweep wins."""
    out = dict(run_cfg.get("fixed", {}))
    out.update(cell)
    return out


# ---------------------------------------------------------------------------
# config.yml in-place toggles
# ---------------------------------------------------------------------------


def _apply_cell_to_config(config_path: str, params: dict[str, Any]) -> None:
    updates: dict[str, Any] = {}
    if "prepend_user_prefix" in params:
        updates.setdefault("evaluation", {}).setdefault("longmemeval", {})[
            "prepend_user_prefix"
        ] = bool(params["prepend_user_prefix"])
    # message_sentence_chunking is intentionally not reapplied per cell: it's
    # ingest-affecting (fixed-only after _validate_sweep_keys) and the fixed
    # value is already written at generate time by build_configuration_yml +
    # _apply_fixed_to_configuration.
    if updates:
        cm.update_yaml_in_place(config_path, updates)


# ---------------------------------------------------------------------------
# benchmark dispatch
# ---------------------------------------------------------------------------


def _resolve_answer_prompt_policy(run_cfg: dict[str, Any], config_path: str) -> str:
    """Decide LongMemEval answer prompt policy.

    Priority: ``run_cfg.evaluation.longmemeval.answer_prompt`` (run-yaml override)
    wins; otherwise read ``retrieval_agent.longmemeval_answer_prompt`` from the
    working configuration.yml. Validates the final value against the bodies
    registered in ``longmemeval_test._ANSWER_PROMPT_BY_POLICY``.
    """
    from evaluation.retrieval_agent.longmemeval_test import (
        _ANSWER_PROMPT_BY_POLICY,
    )

    policy = ((run_cfg.get("evaluation") or {}).get("longmemeval") or {}).get(
        "answer_prompt"
    )
    if policy is None:
        from memmachine_server.common.configuration import Configuration

        conf = Configuration.load_yml_file(config_path)
        policy = conf.retrieval_agent.longmemeval_answer_prompt
    valid = sorted(_ANSWER_PROMPT_BY_POLICY)
    if policy not in _ANSWER_PROMPT_BY_POLICY:
        raise ValueError(
            f"longmemeval_answer_prompt must be one of {valid}, got {policy!r}"
        )
    return policy


async def _run_longmemeval_cell(
    run_cfg: dict[str, Any],
    config_path: str,
    session_id: str,
    params: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    # Reuse the same supporting-fact / turn-content collectors as the upstream
    # longmemeval_search() so recall numbers stay comparable. These helpers are
    # private-prefixed but stable; SLF001 is allowed for scripts/.
    from evaluation.retrieval_agent.longmemeval_test import (
        _collect_supporting_facts,
        _collect_turn_contents,
        _format_question_date,
        _select_answer_prompt,
        load_longmemeval_dataset,
    )
    from evaluation.utils import agent_utils

    bench = run_cfg["benchmark"]
    if bench.get("data_path"):
        local = cm.resolve_data_path(
            bench, default_relative="evaluation/data/longmemeval_s_cleaned.json"
        )
        dataset = cm.load_longmemeval_local(
            local, length=int(bench["length"]), split=bench.get("split", "local")
        )
    else:
        dataset = load_longmemeval_dataset(
            length=int(bench["length"]), split=bench["split"]
        )

    rm = agent_utils.load_eval_config(config_path)
    test_target = params.get("test_target", "retrieval_agent")
    agent_name = "MemMachineAgent" if test_target == "memmachine" else "ToolSelectAgent"

    memory, answer_model, query_agent = await agent_utils.init_memmachine_params(
        resource_manager=rm,
        session_id=session_id,
        agent_name=agent_name,
    )

    prepend = bool(params.get("prepend_user_prefix", False))
    search_limit = int(params.get("search_limit", 20))
    pure_llm = test_target == "llm"

    answer_prompt_policy = _resolve_answer_prompt_policy(run_cfg, config_path)
    answer_prompt = _select_answer_prompt(answer_prompt_policy)
    needs_question_date = "{question_date}" in answer_prompt

    tasks = []
    concurrency = int(run_cfg.get("evaluation", {}).get("search_concurrency", 4))
    responses: list[tuple[str, dict[str, Any]]] = []

    for sample in dataset:
        question = str(sample.get("question", "")).strip()
        if not question:
            continue
        if prepend:
            question = f"User: {question}"
        answer = str(sample.get("answer", "")).strip()
        supporting_facts = _collect_supporting_facts(sample)
        all_content = _collect_turn_contents(sample)
        full_content = "\n".join(all_content)

        prompt_extra: dict[str, str] | None = None
        if needs_question_date:
            prompt_extra = {
                "question_date": _format_question_date(sample.get("question_date", ""))
            }

        tasks.append(
            agent_utils.process_question(
                answer_prompt=answer_prompt,
                query_agent=query_agent,
                memory=memory,
                answer_model=answer_model,
                question=question,
                answer=answer,
                category=str(sample.get("question_type", "unknown")),
                supporting_facts=supporting_facts,
                search_limit=search_limit,
                full_content=full_content if pure_llm else None,
                extra_attributes={"question_id": sample.get("question_id", "")},
                prompt_extra=prompt_extra,
            )
        )
        if len(tasks) >= concurrency or sample is dataset[-1]:
            responses.extend(await asyncio.gather(*tasks))
            tasks = []
    return responses


# ---------------------------------------------------------------------------
# row split
# ---------------------------------------------------------------------------


def _split_response(
    category: str,
    record: dict[str, Any],
    sweep_params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a process_question record into retrieve / generate rows."""
    common = {
        "question": record.get("question"),
        "category": category,
        "sweep": sweep_params,
        "question_id": record.get("question_id", ""),
    }
    retrieve_row = {
        **common,
        "chunks_text": record.get("conversation_memories", ""),
        "num_episodes_retrieved": record.get("num_episodes_retrieved", 0),
        "memory_retrieval_time": record.get("memory_retrieval_time", 0),
        "memory_search_called": record.get("memory_search_called", 0),
        "agent": record.get("agent", ""),
        "selected_tool": record.get("selected_tool", ""),
        "supporting_facts": record.get("supporting_facts", []),
        # Token + recall fields produced by query_agent.do_query() / agent_utils
        # (see evaluation/utils/agent_utils.py:202-245). These flow into the
        # process_question record via res.update(perf_metrics) at line 126.
        "input_token": record.get("input_token", 0),
        "output_token": record.get("output_token", 0),
        "tool_select_input_token": record.get("tool_select_input_token", 0),
        "tool_select_output_token": record.get("tool_select_output_token", 0),
        "fact_hits": record.get("fact_hits", []),
        "fact_miss": record.get("fact_miss", []),
    }
    generate_row = {
        **common,
        "golden_answer": record.get("golden_answer", ""),
        "model_answer": record.get("model_answer", ""),
        "llm_time": record.get("llm_time", 0),
    }
    return retrieve_row, generate_row


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


def run(run_cfg: dict[str, Any]) -> tuple[Path, Path]:
    out_dir = cm.results_dir_for(run_cfg)
    retrieve_path = out_dir / "retrieve.jsonl"
    generate_path = out_dir / "generate.jsonl"

    config_path = cm.resolve_config_path(run_cfg)
    session_id = cm.session_id_for(run_cfg)
    bench_name = run_cfg["benchmark"]["name"]

    sweep_cells = _expand_sweep(run_cfg.get("sweep", {}))
    header = (
        f"[retrieve] benchmark={bench_name}  cells={len(sweep_cells)}  "
        f"config={config_path}"
    )
    if bench_name == "longmemeval":
        header += (
            "  longmemeval_answer_prompt="
            f"{_resolve_answer_prompt_policy(run_cfg, config_path)}"
        )
    print(header)

    retrieve_rows: list[dict[str, Any]] = []
    generate_rows: list[dict[str, Any]] = []

    for cell_idx, cell in enumerate(sweep_cells):
        params = _resolved_params(run_cfg, cell)
        print(f"[retrieve] cell {cell_idx + 1}/{len(sweep_cells)}: {params}")
        _apply_cell_to_config(config_path, params)

        cell_dir = out_dir / "_cells" / f"cell_{cell_idx:03d}"
        cell_dir.mkdir(parents=True, exist_ok=True)

        if bench_name == "longmemeval":
            responses = asyncio.run(
                _run_longmemeval_cell(run_cfg, config_path, session_id, params)
            )
        else:
            raise ValueError(
                f"Unsupported benchmark.name: {bench_name!r}. "
                "This eval-tool branch supports longmemeval only."
            )

        # Annotate fact_hits / fact_miss on each response in-place. process_question()
        # itself does not produce these — they're computed by agent_utils.update_results
        # by comparing supporting_facts against conversation_memories. Without this call
        # all retrieve.jsonl rows would have empty fact_hits and analyze's mean_recall
        # would always be 0.
        from evaluation.utils import agent_utils

        attribute_matrix = agent_utils.init_attribute_matrix()
        agent_utils.update_results(responses, attribute_matrix, {})

        for category, record in responses:
            r_row, g_row = _split_response(category, record, params)
            r_row["cell_idx"] = cell_idx
            g_row["cell_idx"] = cell_idx
            retrieve_rows.append(r_row)
            generate_rows.append(g_row)

    cm.write_jsonl(retrieve_path, retrieve_rows)
    cm.write_jsonl(generate_path, generate_rows)
    print(f"[retrieve] ok → {retrieve_path} ({len(retrieve_rows)} rows)")
    print(
        f"[generate] ok → {generate_path} ({len(generate_rows)} rows)  [emitted by retrieve loop]"
    )
    return retrieve_path, generate_path
