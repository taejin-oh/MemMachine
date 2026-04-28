"""Shared helpers for stage modules.

Sets up sys.path so that `evaluation.*` and `memmachine_server.*` imports work,
plus utilities to resolve the configuration.yml path and write/read the per-run
results directory.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# Make `evaluation.*` and the bundled MemMachine packages importable when this
# script is invoked from anywhere.
for p in [
    REPO_ROOT,
    REPO_ROOT / "packages" / "common" / "src",
    REPO_ROOT / "packages" / "server" / "src",
    REPO_ROOT / "packages" / "client" / "src",
]:
    s = str(p)
    if s not in sys.path:
        sys.path.append(s)


def resolve_config_path(run_cfg: dict[str, Any]) -> str:
    """Return the absolute path of the run-local working configuration.yml.

    Both mode=profile and mode=existing produce a working copy at
    `configuration.generated_path` (set by scripts/generate_config.py); stage
    modules write to that copy and never touch the user's original.
    """
    cfg = run_cfg.get("configuration", {})
    generated = cfg.get("generated_path")
    if not generated:
        raise ValueError(
            "configuration.generated_path missing — run scripts/generate_config.py first"
        )
    return str(Path(generated).resolve())


def results_dir_for(run_cfg: dict[str, Any]) -> Path:
    base = REPO_ROOT / run_cfg.get("results_dir", "results")
    out = base / run_cfg["run_name"]
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def update_yaml_in_place(path: str | Path, updates: dict[str, Any]) -> None:
    """Apply a deep-merge of `updates` into the YAML at `path` (write back).

    Used to toggle `evaluation.longmemeval.prepend_user_prefix` /
    `episodic_memory.long_term_memory.message_sentence_chunking` between sweep
    cells without rewriting the whole file (mirrors run_benchmark_matrix.sh).
    """
    import yaml

    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        current = yaml.safe_load(f) or {}

    def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                _merge(a[k], v)
            else:
                a[k] = v
        return a

    _merge(current, updates)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(current, f, sort_keys=False, allow_unicode=True)


def session_id_for(run_cfg: dict[str, Any]) -> str:
    """Stable session id for the run (used by ingest/retrieve)."""
    bench = run_cfg.get("benchmark", {}).get("name", "unknown")
    return f"eval_tool_{bench}_{run_cfg['run_name']}"


def resolve_data_path(bench: dict[str, Any], default_relative: str) -> Path:
    """Resolve `benchmark.data_path` to an absolute Path under REPO_ROOT.

    Falls back to `default_relative` when missing. Relative paths resolve
    against REPO_ROOT. Raises FileNotFoundError if the resolved file is
    absent so the user gets the actual path that was searched.
    """
    raw = bench.get("data_path") or default_relative
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(
            f"benchmark.data_path not found: {candidate} "
            f"(set benchmark.data_path in run config or place file at default {default_relative})"
        )
    return candidate


def load_longmemeval_local(
    path: Path, length: int, split: str = "local"
) -> list[dict[str, Any]]:
    """Read a local LongMemEval JSON and apply the same minimal normalize as
    `evaluation/retrieval_agent/longmemeval_test.py:load_longmemeval_dataset()`.

    Mirrors that function's `min(length, len(records))` semantics and four-field
    normalize (question / answer / question_type / haystack_sessions / split)
    so downstream `_collect_supporting_facts` / `_collect_turn_contents` /
    `process_question` see the same shape regardless of source.
    """
    import json

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise TypeError(f"Expected list at top of {path}, got {type(raw).__name__}.")
    take = min(length, len(raw))
    out: list[dict[str, Any]] = []
    for record in raw[:take]:
        if not isinstance(record, dict):
            continue
        normalized = dict(record)
        normalized["question"] = str(normalized.get("question", ""))
        normalized["answer"] = str(normalized.get("answer", ""))
        normalized.setdefault("question_type", "unknown")
        normalized.setdefault("haystack_sessions", [])
        normalized["split"] = split
        out.append(normalized)
    return out


def env_with_repo_root() -> dict[str, str]:
    env = os.environ.copy()
    extra = [
        str(REPO_ROOT),
        str(REPO_ROOT / "packages" / "common" / "src"),
        str(REPO_ROOT / "packages" / "server" / "src"),
        str(REPO_ROOT / "packages" / "client" / "src"),
    ]
    env["PYTHONPATH"] = os.pathsep.join([*extra, env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    return env
