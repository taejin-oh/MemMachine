"""Stage: ingest.

Loads benchmark data into the configured MemMachine memory backend.

- LongMemEval / HotpotQA: invoke the existing async functions directly
  (longmemeval_test.longmemeval_ingest, hotpotQA_test.hotpotqa_ingest).
- LoCoMo: subprocess to evaluation/retrieval_agent/locomo_ingest.py with
  the constructed argv (DECISIONS.md D-006).

Idempotent: skips if results/{run}/ingest.jsonl already exists with status=ok.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import subprocess
import sys
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
    dataset = load_longmemeval_dataset(
        length=int(bench["length"]), split=bench["split"]
    )
    asyncio.run(longmemeval_ingest(dataset, config_path, session_id))
    return {"benchmark": "longmemeval", "num_questions": len(dataset)}


def _ingest_hotpot(
    run_cfg: dict[str, Any], config_path: str, _session_id: str
) -> dict[str, Any]:
    from evaluation.retrieval_agent.hotpotQA_test import (
        hotpotqa_ingest,
        load_hotpotqa_dataset,
    )

    bench = run_cfg["benchmark"]
    dataset = load_hotpotqa_dataset(length=int(bench["length"]), split=bench["split"])
    asyncio.run(hotpotqa_ingest(dataset, config_path))
    return {"benchmark": "hotpot", "num_questions": len(dataset)}


def _ingest_locomo(
    run_cfg: dict[str, Any], config_path: str, _session_id: str
) -> dict[str, Any]:
    bench = run_cfg["benchmark"]
    data_path = bench.get("data_path")
    if not data_path:
        raise ValueError(
            "benchmark.data_path is required for locomo (path to LoCoMo source JSON)"
        )

    cmd = [
        sys.executable,
        str(cm.REPO_ROOT / "evaluation" / "retrieval_agent" / "locomo_ingest.py"),
        "--data-path",
        str(data_path),
        "--config-path",
        config_path,
    ]
    completed = subprocess.run(cmd, env=cm.env_with_repo_root(), check=True)
    return {
        "benchmark": "locomo",
        "data_path": str(data_path),
        "subprocess_rc": completed.returncode,
    }


def run(run_cfg: dict[str, Any]) -> Path:
    out_dir = cm.results_dir_for(run_cfg)
    out_path = out_dir / "ingest.jsonl"

    if _already_ingested(out_path):
        print(f"[ingest] skip — {out_path} already marked ok")
        return out_path

    config_path = cm.resolve_config_path(run_cfg)
    session_id = cm.session_id_for(run_cfg)
    bench_name = run_cfg["benchmark"]["name"]

    print(
        f"[ingest] benchmark={bench_name}  config={config_path}  session={session_id}"
    )
    started = _dt.datetime.now(_dt.UTC).isoformat()

    if bench_name == "longmemeval":
        info = _ingest_longmemeval(run_cfg, config_path, session_id)
    elif bench_name == "hotpot":
        info = _ingest_hotpot(run_cfg, config_path, session_id)
    elif bench_name == "locomo":
        info = _ingest_locomo(run_cfg, config_path, session_id)
    else:
        raise ValueError(f"Unknown benchmark.name: {bench_name!r}")

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
