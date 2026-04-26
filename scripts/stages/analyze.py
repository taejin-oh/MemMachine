"""Stage: analyze.

Reads judge.jsonl (or a re-used run's judge.jsonl per p6 / p12), aggregates
per-(sweep cell, category) accuracy / latency / num_episodes, and writes
analyze.json.

Options:
  - --decompose-multisession (#6): emits "ms_vs_others_gap" per sweep cell.
  - --pareto (#12): emits a token / accuracy curve sorted by sweep search_limit.
"""

from __future__ import annotations

import contextlib
import statistics
from pathlib import Path
from typing import Any

from . import _common as cm

# LongMemEval Multi-session category aliases (best-effort match — may need
# tuning once we see real labels in judge.jsonl).
_MS_KEYS = {"multi-session", "multi_session", "ms"}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells: dict[str, dict[str, Any]] = {}

    for r in rows:
        sweep = r.get("sweep", {}) or {}
        cell_key = ",".join(f"{k}={sweep[k]}" for k in sorted(sweep))
        cell = cells.setdefault(
            cell_key,
            {
                "sweep": sweep,
                "n": 0,
                "scores": [],
                "by_category": {},
                "latencies": [],
                "num_episodes": [],
            },
        )
        cell["n"] += 1
        if "llm_score" in r:
            cell["scores"].append(int(r["llm_score"]))
        cat = str(r.get("category", "unknown"))
        bucket = cell["by_category"].setdefault(cat, [])
        if "llm_score" in r:
            bucket.append(int(r["llm_score"]))
        if "llm_time" in r:
            with contextlib.suppress(TypeError, ValueError):
                cell["latencies"].append(float(r["llm_time"]))
        if "num_episodes_retrieved" in r:
            with contextlib.suppress(TypeError, ValueError):
                cell["num_episodes"].append(int(r["num_episodes_retrieved"]))

    summary: dict[str, Any] = {"cells": []}
    for cell_key, c in cells.items():
        scores = c["scores"]
        per_cat = {
            cat: {"n": len(s), "accuracy": (sum(s) / len(s)) if s else None}
            for cat, s in c["by_category"].items()
        }
        summary["cells"].append(
            {
                "cell": cell_key,
                "sweep": c["sweep"],
                "n": c["n"],
                "accuracy": (sum(scores) / len(scores)) if scores else None,
                "accuracy_std": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
                "mean_llm_time": (sum(c["latencies"]) / len(c["latencies"]))
                if c["latencies"]
                else None,
                "mean_num_episodes": (
                    sum(c["num_episodes"]) / len(c["num_episodes"])
                    if c["num_episodes"]
                    else None
                ),
                "by_category": per_cat,
            }
        )
    return summary


def _add_multisession_decomposition(summary: dict[str, Any]) -> None:
    for cell in summary["cells"]:
        per_cat = cell.get("by_category", {})
        ms_acc: float | None = None
        other_accs: list[float] = []
        for cat, info in per_cat.items():
            if info.get("accuracy") is None:
                continue
            if cat.lower() in _MS_KEYS:
                ms_acc = info["accuracy"]
            else:
                other_accs.append(info["accuracy"])
        if ms_acc is not None and other_accs:
            cell["ms_accuracy"] = ms_acc
            cell["others_mean_accuracy"] = sum(other_accs) / len(other_accs)
            cell["ms_vs_others_gap"] = ms_acc - cell["others_mean_accuracy"]


def _add_pareto(summary: dict[str, Any]) -> None:
    points: list[dict[str, Any]] = []
    for cell in summary["cells"]:
        sweep = cell.get("sweep", {})
        k = sweep.get("search_limit")
        if k is None:
            continue
        points.append(
            {
                "search_limit": int(k),
                "accuracy": cell.get("accuracy"),
                "mean_num_episodes": cell.get("mean_num_episodes"),
                "mean_llm_time": cell.get("mean_llm_time"),
                "n": cell.get("n"),
            }
        )
    points.sort(key=lambda p: p["search_limit"])
    summary["pareto"] = points


def run(
    run_cfg: dict[str, Any], decompose_multisession: bool = False, pareto: bool = False
) -> Path:
    out_dir = cm.results_dir_for(run_cfg)
    judge_path = out_dir / "judge.jsonl"

    # p6 / p12: reuse another run's judge.jsonl
    reuse = run_cfg.get("reuse_run")
    if reuse:
        reuse_path = (
            cm.REPO_ROOT / run_cfg.get("results_dir", "results") / reuse / "judge.jsonl"
        ).resolve()
        if not reuse_path.exists():
            raise FileNotFoundError(f"reuse_run judge.jsonl not found: {reuse_path}")
        judge_path = reuse_path
        print(f"[analyze] reusing {reuse_path}")

    if not judge_path.exists():
        raise FileNotFoundError(
            f"judge.jsonl missing: {judge_path} — run --stage judge first"
        )

    rows = cm.read_jsonl(judge_path)
    summary = _aggregate(rows)

    # Apply problem-yaml flags first, then CLI flags (CLI wins)
    p_flags = run_cfg.get("analyze", {}) or {}
    do_ms = decompose_multisession or bool(p_flags.get("decompose_multisession"))
    do_pareto = pareto or bool(p_flags.get("pareto"))

    if do_ms:
        _add_multisession_decomposition(summary)
    if do_pareto:
        _add_pareto(summary)

    summary["meta"] = {
        "run_name": run_cfg["run_name"],
        "problem": run_cfg.get("problem"),
        "benchmark": run_cfg.get("benchmark", {}).get("name"),
        "source_judge_path": str(judge_path),
        "total_rows": len(rows),
        "decompose_multisession": do_ms,
        "pareto": do_pareto,
    }

    out_path = out_dir / "analyze.json"
    cm.write_json(out_path, summary)
    print(f"[analyze] ok → {out_path}  cells={len(summary['cells'])}")
    return out_path
