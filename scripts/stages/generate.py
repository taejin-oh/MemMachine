"""Stage: generate.

The retrieve stage emits generate.jsonl in the same loop (retrieve + generate
run together). This module is a verifier — it asserts the file exists and
reports its row count so `--stage generate` can be invoked standalone for a
quick sanity check after retrieve.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as cm


def run(run_cfg: dict[str, Any]) -> Path:
    out_dir = cm.results_dir_for(run_cfg)
    generate_path = out_dir / "generate.jsonl"
    retrieve_path = out_dir / "retrieve.jsonl"

    if not retrieve_path.exists():
        raise FileNotFoundError(
            f"retrieve.jsonl missing: {retrieve_path}\n"
            "Run --stage retrieve first (it emits generate.jsonl in the same loop)."
        )
    if not generate_path.exists():
        raise FileNotFoundError(
            f"generate.jsonl missing: {generate_path}\n"
            "Expected to be emitted by the retrieve stage."
        )

    rows = cm.read_jsonl(generate_path)
    print(f"[generate] ok — {generate_path} has {len(rows)} rows")
    return generate_path
