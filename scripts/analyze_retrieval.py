#!/usr/bin/env python3
"""Retrieval-quality analyzer for the LongMemEval eval pipeline.

Reads `results/{run}/retrieve.jsonl` + `judge.jsonl` and asks an LLM judge
whether the retrieved memory (`chunks_text`) contained enough information to
derive the gold answer. Two stages:

  Stage 1 (always):  ask the LLM to decompose the gold answer into atomic
    required facts AND mark each as present/absent in chunks_text. Emits a
    verdict in {sufficient, partial, insufficient}.

  Stage 2 (only when verdict != "sufficient"):  for each fact Stage 1 marked
    absent, walk the episode list (chunks_text split on '\\n') and ask the
    LLM whether that single episode contains the fact. Early-exits when
    found. A fact found in Stage 2 is logged as a Stage 1 false positive
    (LLM noise). A fact not found anywhere is truly_missing.

Output:
  results/{run}/retrieve_analysis.jsonl       (per-question record)
  results/{run}/retrieve_analysis_summary.json (aggregate)

LLM: reuses scripts/stages/judge.py's pattern — `create_judge_fn(config_path,
json_mode=True)` from evaluation/retrieval_agent/llm_judge.py. The judge LLM
is whatever the run's `configs/generated/{run}_configuration.yml` points at
(retrieval_agent.judge_llm_model → falls back to retrieval_agent.llm_model).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.stages import _common as cm  # noqa: E402

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_STAGE1_PROMPT = """You are evaluating whether a memory-retrieval system returned enough context to answer a question.

Question:
{question}

Reference answer:
{golden_answer}

Retrieved memory (each line is one episode, prefixed with [timestamp]):
{chunks_text}

Task:
1. Decompose the reference answer into atomic factual claims required to derive it. Each claim should be a single piece of information (a date, a name, a number, a relationship). Keep the list short — usually 1-5 claims.
2. For each claim, decide whether the retrieved memory clearly contains the information needed to derive it (present_in_context: true) or whether it is missing (false).
3. Give an overall verdict:
   - "sufficient": all required claims are present
   - "partial": some present, others missing
   - "insufficient": none or only minor claims are present

Respond with valid JSON only, in this exact schema (no markdown, no commentary):
{{
  "required_facts": [
    {{"fact": "<atomic claim>", "present_in_context": <bool>}}
  ],
  "verdict": "sufficient" | "partial" | "insufficient",
  "reasoning": "<one short sentence>"
}}
"""


_STAGE2_PROMPT = """Does this single memory episode contain the information described by the fact below?

Fact:
{fact}

Episode:
{episode}

Respond with valid JSON only:
{{"contains_fact": <bool>, "reasoning": "<one short sentence>"}}
"""


# ---------------------------------------------------------------------------
# LLM call wrappers
# ---------------------------------------------------------------------------


def _parse_json_lenient(raw: str) -> dict[str, Any] | None:
    """Try strict json, then json_repair fallback. Returns None on total failure."""
    if not raw:
        return None
    raw = raw.strip()
    # Strip ```json fences if model added them
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        import json_repair

        repaired = json_repair.loads(raw)
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass
    return None


async def _call_llm_json(
    call_fn: Callable[[str], str], prompt: str
) -> tuple[dict[str, Any] | None, str]:
    """Run the sync judge call in a thread; return (parsed_json, raw_text)."""
    raw = await asyncio.to_thread(call_fn, prompt)
    return _parse_json_lenient(raw), raw or ""


# ---------------------------------------------------------------------------
# Stage logic
# ---------------------------------------------------------------------------


def _split_episodes(chunks_text: str) -> list[str]:
    """Split chunks_text into episodes on '\\n'. Empty / whitespace-only entries dropped."""
    if not chunks_text:
        return []
    parts = chunks_text.rstrip("\n").split("\n")
    return [p for p in parts if p.strip()]


async def _stage1(
    call_fn: Callable[[str], str],
    question: str,
    golden_answer: str,
    chunks_text: str,
) -> dict[str, Any]:
    prompt = _STAGE1_PROMPT.format(
        question=question,
        golden_answer=golden_answer,
        chunks_text=chunks_text,
    )
    parsed, raw = await _call_llm_json(call_fn, prompt)
    if parsed is None:
        return {
            "required_facts": [],
            "verdict": "parse_error",
            "reasoning": "",
            "raw_response": raw,
        }
    # Normalize
    verdict = str(parsed.get("verdict", "")).lower()
    if verdict not in {"sufficient", "partial", "insufficient"}:
        verdict = "parse_error"
    facts_raw = parsed.get("required_facts") or []
    facts: list[dict[str, Any]] = []
    if isinstance(facts_raw, list):
        for f in facts_raw:
            if not isinstance(f, dict):
                continue
            facts.append(
                {
                    "fact": str(f.get("fact", "")),
                    "present_in_context": bool(f.get("present_in_context", False)),
                }
            )
    return {
        "required_facts": facts,
        "verdict": verdict,
        "reasoning": str(parsed.get("reasoning", "")),
        "raw_response": raw,
    }


async def _stage2_one_fact(
    call_fn: Callable[[str], str],
    fact: str,
    episodes: list[str],
) -> dict[str, Any]:
    """Walk episodes, ask the LLM per episode. Early-exit on first 'contains_fact=true'."""
    for idx, ep in enumerate(episodes):
        prompt = _STAGE2_PROMPT.format(fact=fact, episode=ep)
        parsed, _raw = await _call_llm_json(call_fn, prompt)
        if parsed is None:
            # Parse error — treat as no signal, continue
            continue
        if bool(parsed.get("contains_fact", False)):
            return {
                "fact": fact,
                "found_in_chunk": idx,
                "stage1_false_positive": True,
                "truly_missing": False,
                "reasoning": str(parsed.get("reasoning", "")),
            }
    return {
        "fact": fact,
        "found_in_chunk": None,
        "stage1_false_positive": False,
        "truly_missing": True,
        "reasoning": "",
    }


async def _analyze_question(
    rrow: dict[str, Any],
    jrow: dict[str, Any] | None,
    call_fn: Callable[[str], str],
    skip_stage2: bool,
) -> dict[str, Any]:
    question = rrow.get("question", "")
    chunks_text = rrow.get("chunks_text", "")
    golden_answer = (jrow or {}).get("golden_answer", "")

    s1 = await _stage1(call_fn, question, golden_answer, chunks_text)

    stage2_results: list[dict[str, Any]] = []
    if s1["verdict"] in {"partial", "insufficient"} and not skip_stage2:
        missing = [f["fact"] for f in s1["required_facts"] if not f["present_in_context"]]
        episodes = _split_episodes(chunks_text)
        for fact in missing:
            res = await _stage2_one_fact(call_fn, fact, episodes)
            stage2_results.append(res)

    # Final verdict: if stage2 turned all stage1-missing into found, treat as sufficient.
    verdict_final = s1["verdict"]
    if stage2_results:
        all_found = all(r["found_in_chunk"] is not None for r in stage2_results)
        if all_found:
            verdict_final = "sufficient"

    return {
        "question_id": rrow.get("question_id", ""),
        "category": rrow.get("category", ""),
        "judge_score": int((jrow or {}).get("llm_score", -1)),
        "num_episodes_retrieved": int(rrow.get("num_episodes_retrieved", 0)),
        "stage1": {
            "verdict": s1["verdict"],
            "required_facts": s1["required_facts"],
            "reasoning": s1["reasoning"],
        },
        "stage2": stage2_results,
        "verdict_final": verdict_final,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    stage1_verdicts: Counter[str] = Counter(r["stage1"]["verdict"] for r in rows)
    final_verdicts: Counter[str] = Counter(r["verdict_final"] for r in rows)

    s2_entered = sum(1 for r in rows if r["stage2"])
    s2_facts_checked = sum(len(r["stage2"]) for r in rows)
    s2_false_pos = sum(
        sum(1 for f in r["stage2"] if f["stage1_false_positive"]) for r in rows
    )
    s2_truly_missing = sum(
        sum(1 for f in r["stage2"] if f["truly_missing"]) for r in rows
    )

    quad: Counter[str] = Counter()
    for r in rows:
        v = r["verdict_final"]
        if v == "parse_error":
            continue
        score = r["judge_score"]
        outcome = "correct" if score == 1 else ("wrong" if score == 0 else "unknown")
        quad[f"{v}_{outcome}"] += 1

    # Per-category
    by_cat: dict[str, dict[str, Any]] = {}
    cats = sorted({r["category"] for r in rows if r["category"]})
    for cat in cats:
        cat_rows = [r for r in rows if r["category"] == cat]
        cat_n = len(cat_rows)
        cat_correct = sum(1 for r in cat_rows if r["judge_score"] == 1)
        cat_verdicts: Counter[str] = Counter(r["verdict_final"] for r in cat_rows)
        suff_rows = [r for r in cat_rows if r["verdict_final"] == "sufficient"]
        ins_rows = [r for r in cat_rows if r["verdict_final"] == "insufficient"]
        by_cat[cat] = {
            "n": cat_n,
            "answer_correct_rate": (cat_correct / cat_n) if cat_n else 0.0,
            "final_verdict_dist": dict(cat_verdicts),
            "answer_correct_given_sufficient": (
                sum(1 for r in suff_rows if r["judge_score"] == 1) / len(suff_rows)
                if suff_rows
                else None
            ),
            "answer_correct_given_insufficient": (
                sum(1 for r in ins_rows if r["judge_score"] == 1) / len(ins_rows)
                if ins_rows
                else None
            ),
        }

    # Found-in-chunk rank distribution (across stage1-false-positive results)
    rank_dist: Counter[int] = Counter()
    for r in rows:
        for f in r["stage2"]:
            if f["found_in_chunk"] is not None:
                rank_dist[int(f["found_in_chunk"])] += 1

    return {
        "n_total": n,
        "stage1_verdict_dist": dict(stage1_verdicts),
        "final_verdict_dist": dict(final_verdicts),
        "stage2": {
            "n_questions_entered": s2_entered,
            "n_facts_checked": s2_facts_checked,
            "n_stage1_false_positives": s2_false_pos,
            "stage1_false_positive_rate": (
                (s2_false_pos / s2_facts_checked) if s2_facts_checked else 0.0
            ),
            "n_truly_missing_facts": s2_truly_missing,
            "found_in_chunk_rank_distribution": dict(sorted(rank_dist.items())),
        },
        "answer_x_retrieve_quadrant": dict(quad),
        "by_category": by_cat,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="Run name (results/{run}/ must exist)")
    p.add_argument(
        "--config",
        default=None,
        help="Explicit configuration.yml path (overrides configs/generated/{run}_configuration.yml)",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight LLM calls (default: 4)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Analyze only the first N questions (smoke-test). Default: all rows.",
    )
    p.add_argument(
        "--skip-stage2",
        action="store_true",
        help="Skip stage 2 (chunk-by-chunk re-check of missing facts).",
    )
    return p.parse_args()


async def _main_async(
    args: argparse.Namespace,
    retrieve_path: Path,
    judge_path: Path,
    config_path: str,
) -> int:
    retrieve_rows = cm.read_jsonl(retrieve_path)
    judge_rows = cm.read_jsonl(judge_path)
    results_dir = retrieve_path.parent
    judge_by_qid = {r.get("question_id", ""): r for r in judge_rows}

    if args.limit:
        retrieve_rows = retrieve_rows[: args.limit]

    print(
        f"[analyze_retrieval] run={args.run}  config={config_path}  "
        f"rows={len(retrieve_rows)}  concurrency={args.concurrency}  "
        f"skip_stage2={args.skip_stage2}"
    )

    from evaluation.retrieval_agent.llm_judge import create_judge_fn

    call_fn = create_judge_fn(config_path, json_mode=True)

    sem = asyncio.Semaphore(args.concurrency)

    async def _one(idx: int, rrow: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            qid = rrow.get("question_id", "")
            jrow = judge_by_qid.get(qid)
            out = await _analyze_question(rrow, jrow, call_fn, args.skip_stage2)
            print(
                f"[analyze_retrieval] {idx + 1}/{len(retrieve_rows)}  "
                f"qid={qid}  s1={out['stage1']['verdict']}  "
                f"final={out['verdict_final']}  "
                f"s2_facts={len(out['stage2'])}"
            )
            return out

    out_rows = await asyncio.gather(
        *[_one(i, r) for i, r in enumerate(retrieve_rows)]
    )

    out_jsonl = results_dir / "retrieve_analysis.jsonl"
    out_summary = results_dir / "retrieve_analysis_summary.json"
    cm.write_jsonl(out_jsonl, out_rows)
    summary = _aggregate(out_rows)
    summary["run_name"] = args.run
    cm.write_json(out_summary, summary)

    print(f"[analyze_retrieval] ok → {out_jsonl}")
    print(f"[analyze_retrieval] ok → {out_summary}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    args = _parse_args()

    results_dir = REPO_ROOT / "results" / args.run
    retrieve_path = results_dir / "retrieve.jsonl"
    judge_path = results_dir / "judge.jsonl"

    if not retrieve_path.exists():
        raise FileNotFoundError(f"retrieve.jsonl missing: {retrieve_path}")
    if not judge_path.exists():
        raise FileNotFoundError(f"judge.jsonl missing: {judge_path}")

    config_path = args.config or str(
        REPO_ROOT / "configs" / "generated" / f"{args.run}_configuration.yml"
    )
    if not Path(config_path).exists():
        raise FileNotFoundError(f"configuration.yml not found: {config_path}")

    return asyncio.run(_main_async(args, retrieve_path, judge_path, config_path))


if __name__ == "__main__":
    sys.exit(main())
