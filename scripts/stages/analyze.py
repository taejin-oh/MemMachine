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


_TOKEN_FIELDS = (
    "input_token",
    "output_token",
    "tool_select_input_token",
    "tool_select_output_token",
)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
                "by_tool": {},
                "latencies": [],
                "num_episodes": [],
                "tokens": {f: [] for f in _TOKEN_FIELDS},
                "recalls": [],
                "total_hits": 0,
                "total_facts": 0,
            },
        )
        cell["n"] += 1
        score = _coerce_int(r.get("llm_score"))
        if score is not None:
            cell["scores"].append(score)

        cat = str(r.get("category", "unknown"))
        cat_bucket = cell["by_category"].setdefault(cat, [])
        if score is not None:
            cat_bucket.append(score)

        tool = str(r.get("selected_tool") or r.get("agent") or "Unknown")
        tool_bucket = cell["by_tool"].setdefault(
            tool,
            {"scores": [], "input_tokens": [], "output_tokens": [], "latencies": []},
        )
        if score is not None:
            tool_bucket["scores"].append(score)
        for field, dest in (
            ("input_token", "input_tokens"),
            ("output_token", "output_tokens"),
        ):
            v = _coerce_int(r.get(field))
            if v is not None:
                tool_bucket[dest].append(v)
        with contextlib.suppress(TypeError, ValueError):
            if "llm_time" in r:
                tool_bucket["latencies"].append(float(r["llm_time"]))

        if "llm_time" in r:
            with contextlib.suppress(TypeError, ValueError):
                cell["latencies"].append(float(r["llm_time"]))
        ep = _coerce_int(r.get("num_episodes_retrieved"))
        if ep is not None:
            cell["num_episodes"].append(ep)

        for field in _TOKEN_FIELDS:
            v = _coerce_int(r.get(field))
            if v is not None:
                cell["tokens"][field].append(v)

        sf = r.get("supporting_facts") or []
        hits = r.get("fact_hits")
        if sf and isinstance(hits, list):
            cell["recalls"].append(len(hits) / len(sf))
            cell["total_hits"] += len(hits)
            cell["total_facts"] += len(sf)

    summary: dict[str, Any] = {"cells": []}
    for cell_key, c in cells.items():
        scores = c["scores"]
        per_cat = {
            cat: {"n": len(s), "accuracy": (sum(s) / len(s)) if s else None}
            for cat, s in c["by_category"].items()
        }
        per_tool: dict[str, dict[str, Any]] = {}
        for tool, t in c["by_tool"].items():
            t_scores = t["scores"]
            per_tool[tool] = {
                "n": len(t_scores),
                "accuracy": (sum(t_scores) / len(t_scores)) if t_scores else None,
                "mean_input_token": (
                    sum(t["input_tokens"]) / len(t["input_tokens"])
                    if t["input_tokens"]
                    else None
                ),
                "mean_output_token": (
                    sum(t["output_tokens"]) / len(t["output_tokens"])
                    if t["output_tokens"]
                    else None
                ),
                "mean_llm_time": (
                    sum(t["latencies"]) / len(t["latencies"])
                    if t["latencies"]
                    else None
                ),
            }

        token_means: dict[str, float | None] = {}
        for field in _TOKEN_FIELDS:
            vals = c["tokens"][field]
            token_means[f"mean_{field}"] = (sum(vals) / len(vals)) if vals else None
        # tokens_per_query = sum of all 4 token fields, averaged over questions
        per_q_totals = []
        for i in range(c["n"]):
            total = 0
            any_present = False
            for field in _TOKEN_FIELDS:
                vals = c["tokens"][field]
                if i < len(vals):
                    total += vals[i]
                    any_present = True
            if any_present:
                per_q_totals.append(total)
        mean_tokens_per_query = (
            sum(per_q_totals) / len(per_q_totals) if per_q_totals else None
        )

        recalls = c["recalls"]
        overall_recall = (
            c["total_hits"] / c["total_facts"] if c["total_facts"] else None
        )
        summary["cells"].append(
            {
                "cell": cell_key,
                "sweep": c["sweep"],
                "n": c["n"],
                "accuracy": (sum(scores) / len(scores)) if scores else None,
                "accuracy_std": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
                "mean_recall": (sum(recalls) / len(recalls)) if recalls else None,
                "overall_recall": overall_recall,
                "total_fact_hits": c["total_hits"],
                "total_supporting_facts": c["total_facts"],
                "mean_llm_time": (sum(c["latencies"]) / len(c["latencies"]))
                if c["latencies"]
                else None,
                "mean_num_episodes": (
                    sum(c["num_episodes"]) / len(c["num_episodes"])
                    if c["num_episodes"]
                    else None
                ),
                "mean_tokens_per_query": mean_tokens_per_query,
                **token_means,
                "by_category": per_cat,
                "by_tool": per_tool,
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
                "mean_recall": cell.get("mean_recall"),
                "overall_recall": cell.get("overall_recall"),
                "mean_tokens_per_query": cell.get("mean_tokens_per_query"),
                "mean_input_token": cell.get("mean_input_token"),
                "mean_output_token": cell.get("mean_output_token"),
                "mean_num_episodes": cell.get("mean_num_episodes"),
                "mean_llm_time": cell.get("mean_llm_time"),
                "n": cell.get("n"),
            }
        )
    points.sort(key=lambda p: p["search_limit"])
    summary["pareto"] = points


def _retrieve_index(
    retrieve_rows: list[dict[str, Any]],
) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    """Index retrieve.jsonl rows by (cell_idx, question_id, question)."""
    return {
        (r.get("cell_idx"), r.get("question_id", ""), r.get("question", "")): r
        for r in retrieve_rows
    }


_CARRY_FIELDS = (
    "num_episodes_retrieved",
    "memory_retrieval_time",
    "memory_search_called",
    "agent",
    "selected_tool",
    "supporting_facts",
    "fact_hits",
    "fact_miss",
    "input_token",
    "output_token",
    "tool_select_input_token",
    "tool_select_output_token",
)


def _join_retrieve(
    judge_rows: list[dict[str, Any]],
    retrieve_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carry retrieval-stage fields onto judge rows by matching (cell, qid, question)."""
    if not retrieve_rows:
        return judge_rows
    idx = _retrieve_index(retrieve_rows)
    out: list[dict[str, Any]] = []
    for r in judge_rows:
        key = (r.get("cell_idx"), r.get("question_id", ""), r.get("question", ""))
        carry = idx.get(key, {})
        merged = dict(r)
        for field in _CARRY_FIELDS:
            if field not in merged and field in carry:
                merged[field] = carry[field]
        out.append(merged)
    return out


def run(
    run_cfg: dict[str, Any], decompose_multisession: bool = False, pareto: bool = False
) -> Path:
    out_dir = cm.results_dir_for(run_cfg)
    judge_path = out_dir / "judge.jsonl"
    retrieve_path = out_dir / "retrieve.jsonl"

    # p6 / p12: reuse another run's judge.jsonl + retrieve.jsonl
    reuse = run_cfg.get("reuse_run")
    if reuse:
        reuse_dir = (
            cm.REPO_ROOT / run_cfg.get("results_dir", "results") / reuse
        ).resolve()
        reuse_judge = reuse_dir / "judge.jsonl"
        if not reuse_judge.exists():
            raise FileNotFoundError(f"reuse_run judge.jsonl not found: {reuse_judge}")
        judge_path = reuse_judge
        retrieve_path = reuse_dir / "retrieve.jsonl"
        print(f"[analyze] reusing {reuse_judge}")

    if not judge_path.exists():
        raise FileNotFoundError(
            f"judge.jsonl missing: {judge_path} — run --stage judge first"
        )

    rows = cm.read_jsonl(judge_path)
    retrieve_rows = cm.read_jsonl(retrieve_path) if retrieve_path.exists() else []
    rows = _join_retrieve(rows, retrieve_rows)
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
        "source_retrieve_path": str(retrieve_path) if retrieve_path.exists() else None,
        "total_rows": len(rows),
        "joined_retrieve_rows": len(retrieve_rows),
        "decompose_multisession": do_ms,
        "pareto": do_pareto,
    }

    out_path = out_dir / "analyze.json"
    cm.write_json(out_path, summary)
    print(f"[analyze] ok → {out_path}  cells={len(summary['cells'])}")
    return out_path
