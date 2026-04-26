"""Deep-merge utilities for layered YAML configs (base + problem + run).

Used by generate_config.py and run_pipeline.py.
Right-hand sides override left. Lists are replaced (not concatenated).
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def deep_merge(*layers: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge dicts left-to-right. Later layers override earlier ones.

    - dict + dict   → recursive merge
    - dict + scalar → scalar wins (later layer)
    - list + list   → later list wins (no concat)
    - any + None    → earlier value preserved (None means "unset")
    """
    out: dict[str, Any] = {}
    for layer in layers:
        if not layer:
            continue
        out = _merge_two(out, layer)
    return out


def _merge_two(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(a)
    for key, b_val in b.items():
        if b_val is None and key in result:
            continue
        a_val = result.get(key)
        if isinstance(a_val, dict) and isinstance(b_val, dict):
            result[key] = _merge_two(a_val, b_val)
        else:
            result[key] = deepcopy(b_val)
    return result


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Top-level YAML must be a mapping: {p}")
    return loaded


def dump_yaml(data: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
