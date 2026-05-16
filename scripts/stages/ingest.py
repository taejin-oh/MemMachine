"""Stage: ingest.

Loads LongMemEval data into the configured MemMachine memory backend.

Idempotent: skips if results/{run}/ingest.jsonl already exists with status=ok.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from pathlib import Path
from typing import Any

from . import _common as cm


def _already_ingested(out_path: Path) -> bool:
    if not out_path.exists():
        return False
    try:
        rows = cm.read_jsonl(out_path)
    except Exception:
        return False
    return bool(rows) and rows[-1].get("status") == "ok"


def _ingest_longmemeval(
    run_cfg: dict[str, Any], config_path: str, session_id: str
) -> dict[str, Any]:
    from evaluation.retrieval_agent.longmemeval_test import (
        load_longmemeval_dataset,
        longmemeval_ingest,
    )

    bench = run_cfg["benchmark"]
    if bench.get("data_path"):
        # Local JSON wins over HF download.
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
    asyncio.run(longmemeval_ingest(dataset, config_path, session_id))
    return {"benchmark": "longmemeval", "num_questions": len(dataset)}


def run(run_cfg: dict[str, Any]) -> Path:
    out_dir = cm.results_dir_for(run_cfg)
    out_path = out_dir / "ingest.jsonl"

    if _already_ingested(out_path):
        print(f"[ingest] skip — {out_path} already marked ok")
        return out_path

    config_path = cm.resolve_config_path(run_cfg)
    session_id = cm.session_id_for(run_cfg)
    bench_name = run_cfg["benchmark"]["name"]

    if bench_name != "longmemeval":
        raise ValueError(
            f"Unsupported benchmark.name: {bench_name!r}. "
            "This eval-tool branch supports longmemeval only."
        )

    print(
        f"[ingest] benchmark={bench_name}  config={config_path}  session={session_id}"
    )
    started = _dt.datetime.now(_dt.UTC).isoformat()

    info = _ingest_longmemeval(run_cfg, config_path, session_id)

    finished = _dt.datetime.now(_dt.UTC).isoformat()
    cm.write_jsonl(
        out_path,
        [
            {
                "status": "ok",
                "started_at": started,
                "finished_at": finished,
                "session_id": session_id,
                **info,
            }
        ],
    )
    print(f"[ingest] ok → {out_path}")
    return out_path
