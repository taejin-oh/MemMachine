"""Stage: retrieve (+ generate emitted in same loop — DECISIONS.md D-005).

Iterates the sweep cells. For each (sweep cell × question):
- Toggles `evaluation.longmemeval.prepend_user_prefix` and
  `episodic_memory.long_term_memory.message_sentence_chunking` in the
  configuration.yml in-place (mirrors run_benchmark_matrix.sh).
- Calls `agent_utils.process_question()` to run retrieve + generate
  in one shot, then splits the resulting record into two jsonl rows:
    - retrieve.jsonl: chunks + perf_metrics + sweep_params
    - generate.jsonl: model_answer + latency + sweep_params
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from pathlib import Path
from typing import Any

from . import _common as cm

# ---------------------------------------------------------------------------
# sweep expansion
# ---------------------------------------------------------------------------


def _expand_sweep(sweep: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Return one dict per cartesian-product cell of the sweep."""
    if not sweep:
        return [{}]
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
    if "message_sentence_chunking" in params:
        updates.setdefault("episodic_memory", {}).setdefault("long_term_memory", {})[
            "message_sentence_chunking"
        ] = bool(params["message_sentence_chunking"])
    if updates:
        cm.update_yaml_in_place(config_path, updates)


# ---------------------------------------------------------------------------
# benchmark dispatch
# ---------------------------------------------------------------------------


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
        ANSWER_PROMPT,
        _collect_supporting_facts,
        _collect_turn_contents,
        load_longmemeval_dataset,
    )
    from evaluation.utils import agent_utils

    bench = run_cfg["benchmark"]
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

        tasks.append(
            agent_utils.process_question(
                answer_prompt=ANSWER_PROMPT,
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
            )
        )
        if len(tasks) >= concurrency or sample is dataset[-1]:
            responses.extend(await asyncio.gather(*tasks))
            tasks = []
    return responses


async def _run_hotpot_cell(
    run_cfg: dict[str, Any],
    config_path: str,
    _session_id: str,
    params: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    from evaluation.retrieval_agent.hotpotQA_test import (
        ANSWER_PROMPT,
        load_hotpotqa_dataset,
    )
    from evaluation.utils import agent_utils

    bench = run_cfg["benchmark"]
    dataset = load_hotpotqa_dataset(length=int(bench["length"]), split=bench["split"])

    rm = agent_utils.load_eval_config(config_path)
    test_target = params.get("test_target", "retrieval_agent")
    agent_name = "MemMachineAgent" if test_target == "memmachine" else "ToolSelectAgent"

    memory, answer_model, query_agent = await agent_utils.init_memmachine_params(
        resource_manager=rm,
        session_id="hotpotqa_group",
        agent_name=agent_name,
    )

    search_limit = int(params.get("search_limit", 20))
    pure_llm = test_target == "llm"
    tasks = []
    concurrency = int(run_cfg.get("evaluation", {}).get("search_concurrency", 4))
    responses: list[tuple[str, dict[str, Any]]] = []

    for data in dataset:
        ctx = data["context"]
        sentences = ctx["sentences"]
        full_content_str = "\n".join(s for sl in sentences for s in sl)
        sf_facts: list[str] = []
        sf = data.get("supporting_facts", {})
        for title, sid in zip(sf.get("title", []), sf.get("sent_id", []), strict=True):
            with contextlib.suppress(ValueError, IndexError):
                sf_facts.append(sentences[ctx["title"].index(title)][sid])

        tasks.append(
            agent_utils.process_question(
                answer_prompt=ANSWER_PROMPT,
                query_agent=query_agent,
                memory=memory,
                answer_model=answer_model,
                question=data["question"],
                answer=data["answer"],
                category=data.get("type", "unknown"),
                supporting_facts=sf_facts,
                search_limit=search_limit,
                full_content=full_content_str if pure_llm else None,
                extra_attributes={"level": data.get("level")},
            )
        )
        if len(tasks) >= concurrency or data is dataset[-1]:
            responses.extend(await asyncio.gather(*tasks))
            tasks = []
    return responses


def _run_locomo_cell(
    run_cfg: dict[str, Any],
    config_path: str,
    _session_id: str,
    params: dict[str, Any],
    cell_dir: Path,
) -> list[tuple[str, dict[str, Any]]]:
    """Subprocess-call locomo_search.py and re-load its result JSON."""
    import json
    import subprocess
    import sys

    bench = run_cfg["benchmark"]
    data_path = bench.get("data_path")
    if not data_path:
        raise ValueError("benchmark.data_path is required for locomo")
    length = int(bench.get("length", 10))

    out_json = cell_dir / "locomo_raw.json"
    test_target = params.get("test_target", "retrieval_agent")
    cmd = [
        sys.executable,
        str(cm.REPO_ROOT / "evaluation" / "retrieval_agent" / "locomo_search.py"),
        "--data-path",
        str(data_path),
        "--eval-result-path",
        str(out_json),
        "--test-target",
        test_target,
        "--config-path",
        config_path,
        "--length",
        str(length),
    ]
    subprocess.run(cmd, env=cm.env_with_repo_root(), check=True)

    with out_json.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    responses: list[tuple[str, dict[str, Any]]] = []
    for category, items in raw.items():
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict):
                responses.append((str(category), it))
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
    print(
        f"[retrieve] benchmark={bench_name}  cells={len(sweep_cells)}  config={config_path}"
    )

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
        elif bench_name == "hotpot":
            responses = asyncio.run(
                _run_hotpot_cell(run_cfg, config_path, session_id, params)
            )
        elif bench_name == "locomo":
            responses = _run_locomo_cell(
                run_cfg, config_path, session_id, params, cell_dir
            )
        else:
            raise ValueError(f"Unknown benchmark.name: {bench_name!r}")

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
