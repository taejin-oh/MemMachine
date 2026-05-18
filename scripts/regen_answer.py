#!/usr/bin/env python3
"""Regenerate model_answer from an existing retrieve.jsonl.

Reads results/<run>/retrieve.jsonl + the LongMemEval dataset, calls the answer
LLM with the same prompt template that the retrieve stage would have used, and
writes a fresh results/<run>/generate.jsonl. The previous generate.jsonl is
preserved as generate.jsonl.bak (or .bak.<ts> if .bak already exists).

Two entry points:

    python scripts/regen_answer.py --run <name>

    python scripts/run_pipeline.py --config configs/runs/<name>.yaml \
        --stage regen_answer

The same configs/generated/<run>_configuration.yml + configs/runs/<run>.yaml
that retrieve used are read back; no extra config files are required.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.retrieval_agent.longmemeval_test import (  # noqa: E402
    _format_question_date,
    _select_answer_prompt,
    load_longmemeval_dataset,
)
from evaluation.utils import agent_utils  # noqa: E402
from scripts._merge import load_yaml  # noqa: E402
from scripts.stages import _common as cm  # noqa: E402
from scripts.stages import retrieve as retrieve_stage  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--run",
        required=True,
        help="Run name (configs/runs/<run>.yaml must exist)",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Explicit run YAML path (overrides configs/runs/<run>.yaml)",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight answer-LLM calls (default: 4)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N rows (smoke-test). Default: all rows.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip backup + LLM calls + write. Print one sample prompt only.",
    )
    return p.parse_args()


def _index_dataset(run_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Load LongMemEval dataset and index by question_id.

    Mirrors scripts/stages/retrieve.py:191-201 — local data_path wins; otherwise
    fall back to the HF download via longmemeval_test.load_longmemeval_dataset.
    """
    bench = run_cfg["benchmark"]
    if bench.get("data_path"):
        local = cm.resolve_data_path(
            bench, default_relative="evaluation/data/longmemeval_s_cleaned.json"
        )
        dataset = cm.load_longmemeval_local(
            local,
            length=int(bench["length"]),
            split=bench.get("split", "local"),
        )
    else:
        dataset = load_longmemeval_dataset(
            length=int(bench["length"]), split=bench["split"]
        )
    return {str(s.get("question_id", "")): s for s in dataset}


def _backup_generate(generate_path: Path) -> Path | None:
    """Move existing generate.jsonl to .bak (chain to .bak.<ts> if needed)."""
    if not generate_path.exists():
        return None
    bak = generate_path.with_suffix(generate_path.suffix + ".bak")
    if bak.exists():
        bak = generate_path.with_suffix(
            generate_path.suffix + f".bak.{int(time.time())}"
        )
    generate_path.replace(bak)
    return bak


async def _regen_one_row(
    row: dict[str, Any],
    sample: dict[str, Any] | None,
    answer_prompt: str,
    needs_qdate: bool,
    answer_model: Any,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """Regenerate one model_answer from a retrieve.jsonl row."""
    qid = row.get("question_id", "")
    out: dict[str, Any] = {
        "question": row.get("question", ""),
        "question_id": qid,
        "category": row.get("category", ""),
        "sweep": row.get("sweep", {}),
        "cell_idx": row.get("cell_idx", 0),
        "regen_source": "regen_answer",
    }
    if sample is None:
        out["golden_answer"] = ""
        out["model_answer"] = ""
        out["llm_time"] = 0.0
        out["regen_error"] = "qid_not_in_dataset"
        return out

    out["golden_answer"] = str(sample.get("answer", ""))

    fmt_kwargs: dict[str, Any] = {
        "memories": row.get("chunks_text", ""),
        "question": out["question"],
    }
    if needs_qdate:
        fmt_kwargs["question_date"] = _format_question_date(
            sample.get("question_date", "")
        )
    prompt = answer_prompt.format(**fmt_kwargs)

    t0 = time.time()
    async with sem:
        try:
            rsp_text, _ = await answer_model.generate_response(user_prompt=prompt)
        except Exception as err:
            out["model_answer"] = ""
            out["llm_time"] = time.time() - t0
            out["regen_error"] = f"{type(err).__name__}: {err}"
            return out
    out["model_answer"] = rsp_text
    out["llm_time"] = time.time() - t0
    return out


async def _regen_all(
    rows: list[dict[str, Any]],
    dataset_idx: dict[str, dict[str, Any]],
    answer_prompt: str,
    needs_qdate: bool,
    answer_model: Any,
    concurrency: int,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    tasks = [
        _regen_one_row(
            row,
            dataset_idx.get(str(row.get("question_id", ""))),
            answer_prompt,
            needs_qdate,
            answer_model,
            sem,
        )
        for row in rows
    ]
    return await asyncio.gather(*tasks)


async def _main_async(
    run_cfg: dict[str, Any],
    retrieve_path: Path,
    generate_path: Path,
    config_path: str,
    concurrency: int,
    limit: int | None,
    dry_run: bool,
) -> int:
    rm = agent_utils.load_eval_config(config_path)
    _, answer_model, _ = await agent_utils.init_memmachine_params(
        resource_manager=rm,
        session_id=cm.session_id_for(run_cfg),
        agent_name="ToolSelectAgent",
    )

    policy = retrieve_stage._resolve_answer_prompt_policy(  # noqa: SLF001
        run_cfg, config_path
    )
    answer_prompt = _select_answer_prompt(policy)
    needs_qdate = "{question_date}" in answer_prompt

    dataset_idx = _index_dataset(run_cfg)
    rows = cm.read_jsonl(retrieve_path)
    if limit is not None:
        rows = rows[:limit]

    print(
        f"[regen_answer] run={run_cfg.get('run_name')}  policy={policy}  "
        f"rows={len(rows)}  concurrency={concurrency}  dry_run={dry_run}"
    )

    if dry_run:
        # Sanity-check: render the first row's prompt and return without writing.
        for row in rows[:1]:
            sample = dataset_idx.get(str(row.get("question_id", "")))
            if sample is None:
                print(
                    f"[regen_answer][dry-run] qid={row.get('question_id')!r} "
                    "not in dataset; skipping prompt render"
                )
                continue
            fmt: dict[str, Any] = {
                "memories": row.get("chunks_text", ""),
                "question": row.get("question", ""),
            }
            if needs_qdate:
                fmt["question_date"] = _format_question_date(
                    sample.get("question_date", "")
                )
            print("[regen_answer][dry-run] sample prompt:")
            print(answer_prompt.format(**fmt))
        print("[regen_answer] dry-run: skipped backup + LLM calls + write")
        return 0

    bak = _backup_generate(generate_path)
    if bak is not None:
        print(f"[regen_answer] backed up existing generate.jsonl → {bak}")

    out_rows = await _regen_all(
        rows, dataset_idx, answer_prompt, needs_qdate, answer_model, concurrency
    )
    n_failed = sum(1 for r in out_rows if r.get("regen_error"))
    n_written = cm.write_jsonl(generate_path, out_rows)
    print(f"[regen_answer] ok → {generate_path} ({n_written} rows, {n_failed} failed)")
    return 0


def run(
    run_cfg: dict[str, Any],
    *,
    concurrency: int = 4,
    limit: int | None = None,
    dry_run: bool = False,
) -> Path:
    """Public entry. Called by both stand-alone CLI and run_pipeline.py.

    Resolves paths from run_cfg, runs the async regeneration, returns the
    written generate.jsonl path (or the would-be path under --dry-run).
    """
    out_dir = cm.results_dir_for(run_cfg)
    retrieve_path = out_dir / "retrieve.jsonl"
    generate_path = out_dir / "generate.jsonl"

    if not retrieve_path.exists():
        raise FileNotFoundError(
            f"retrieve.jsonl missing: {retrieve_path}\nRun --stage retrieve first."
        )

    config_path = cm.resolve_config_path(run_cfg)
    if not Path(config_path).exists():
        raise FileNotFoundError(f"configuration.yml not found: {config_path}")

    asyncio.run(
        _main_async(
            run_cfg,
            retrieve_path,
            generate_path,
            config_path,
            concurrency,
            limit,
            dry_run,
        )
    )
    return generate_path


def main() -> int:
    args = _parse_args()
    run_yaml_path = args.config or str(
        REPO_ROOT / "configs" / "runs" / f"{args.run}.yaml"
    )
    if not Path(run_yaml_path).exists():
        raise FileNotFoundError(f"run YAML not found: {run_yaml_path}")
    run_cfg = load_yaml(run_yaml_path)
    if "run_name" not in run_cfg:
        raise SystemExit(f"run YAML missing 'run_name': {run_yaml_path}")
    run(
        run_cfg,
        concurrency=args.concurrency,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
