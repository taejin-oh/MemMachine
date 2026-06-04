#!/usr/bin/env python3
"""LongMemEval-V2 end-to-end runner with the MemMachine backend.

Pipeline (single process, blocking — V2-flavored, MemMachine-backed):

  1. Load V2 dataset (questions.jsonl, trajectories.jsonl, haystacks/<tier>.json)
  2. Build memory module from `--memory-config-path`
       (default: memmachine config from `--memmachine-configuration-path`)
  3. **Ingest stage** — for each trajectory referenced by selected questions'
       haystacks, call memory.insert(trajectory). Skippable with `--skip-ingest`
       (use when Neo4j already has the trajectories from a prior run).
  4. **Retrieve stage** — for each question:
       - memory.set_query_context(haystack=[trajectory_ids])
       - memory.query(question_text)
       Output: results/<run>/retrieve.jsonl
       Re-runnable with `--skip-ingest` to vary top_k without re-ingest.
  5. **Generate stage** — reader LLM consumes the retrieved context + the V2
       domain system prompt, returns a response with `\\boxed{...}` answer.
       Output: results/<run>/generate.jsonl
  6. **Judge stage** — LLM-as-a-judge per category (default / abstention /
       gotchas system prompts). Output: results/<run>/judge.jsonl +
       summary.json (overall + per-category accuracy).

Mirrors V1 (`evaluation/longmemeval/{ingest,retrieve,generate,judge}.py`)
structurally but collapses into one script because the V2 memory module
already encapsulates ingest+retrieve behind one interface.

Usage:
    uv run python -m evaluation.longmemeval_v2.run_eval \\
        --data-root /path/to/longmemeval-v2 \\
        --domain web \\
        --tier small \\
        --memmachine-configuration-path evaluation/longmemeval_v2/configuration.yml \\
        --output-dir results/lmev2_smoke \\
        --limit 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.longmemeval_v2._common import (  # noqa: E402
    DOMAIN_SYSTEM_PROMPTS,
    build_judge_messages,
    build_reader_messages,
    extract_boxed_answer,
    get_answer_llm,
    get_judge_llm,
    load_eval_config,
    load_json,
    load_jsonl,
    normalize_category,
    parse_yes_no_lenient,
    write_jsonl,
)
from evaluation.longmemeval_v2.memory_modules import (  # noqa: E402
    build_memory,
    load_memory_config,
)


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def _load_dataset(
    data_root: Path,
    *,
    domain: str,
    tier: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
    questions_path = data_root / "questions.jsonl"
    trajectories_path = data_root / "trajectories.jsonl"
    haystack_path = data_root / "haystacks" / f"lme_v2_{tier}.json"
    for p in (questions_path, trajectories_path, haystack_path):
        if not p.exists():
            raise FileNotFoundError(f"Missing dataset file: {p}")

    questions = [
        q for q in load_jsonl(questions_path) if str(q.get("domain")) == domain
    ]
    if not questions:
        raise RuntimeError(
            f"No questions found for domain={domain!r} in {questions_path}"
        )
    trajectories = {
        str(t["id"]): t for t in load_jsonl(trajectories_path) if t.get("id")
    }
    haystack = load_json(haystack_path)
    if not isinstance(haystack, dict):
        raise TypeError(f"haystack JSON must be an object: {haystack_path}")
    return questions, trajectories, {str(k): list(v) for k, v in haystack.items()}


def _parse_csv_list(values: list[str] | None) -> list[str] | None:
    """Accept either space-separated nargs or comma-separated entries."""
    if not values:
        return None
    out: list[str] = []
    for raw in values:
        for item in str(raw).split(","):
            s = item.strip()
            if s:
                out.append(s)
    return out or None


def _select_questions(
    questions: list[dict[str, Any]],
    *,
    question_ids: list[str] | None,
    question_types: list[str] | None,
    offset: int,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Apply filters in order: ids → types → offset → limit.

    File order is preserved within each filtered subset, so `--offset` /
    `--limit` give a stable "N번째 ~ M번째" slice of (type-filtered) questions.
    """
    if question_ids:
        keep_ids = set(question_ids)
        questions = [q for q in questions if str(q.get("id")) in keep_ids]
    if question_types:
        keep_types = set(question_types)
        questions = [
            q for q in questions if str(q.get("question_type", "")) in keep_types
        ]
    if offset:
        if offset < 0:
            raise ValueError(f"--offset must be >= 0, got {offset}")
        questions = questions[offset:]
    if limit is not None:
        if limit < 0:
            raise ValueError(f"--limit must be >= 0, got {limit}")
        questions = questions[:limit]
    return questions


# ---------------------------------------------------------------------------
# Memory config loading (default: build a memmachine config inline)
# ---------------------------------------------------------------------------
def _build_default_memory_config(
    memmachine_config_path: Path,
    *,
    session_prefix: str,
    top_k: int,
) -> dict[str, object]:
    return {
        "memory_type": "memmachine",
        "memory_params": {
            "configuration_path": str(memmachine_config_path.resolve()),
            "session_prefix": session_prefix,
            "top_k": top_k,
        },
    }


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def _stage_ingest(
    *,
    memory: Any,
    trajectories: dict[str, dict[str, Any]],
    selected_traj_ids: set[str],
) -> int:
    inserted = 0
    total = len(selected_traj_ids)
    for i, traj_id in enumerate(sorted(selected_traj_ids), start=1):
        traj = trajectories.get(traj_id)
        if traj is None:
            print(f"[ingest] {i}/{total}  WARN: trajectory id not found: {traj_id}")
            continue
        t0 = time.perf_counter()
        memory.insert(traj)
        dt = time.perf_counter() - t0
        states = len(traj.get("states") or [])
        print(
            f"[ingest] {i}/{total}  traj_id={traj_id}  states={states}  t={dt:.1f}s"
        )
        inserted += 1
    return inserted


def _stage_retrieve(
    *,
    memory: Any,
    selected_questions: list[dict[str, Any]],
    haystack: dict[str, list[str]],
    output_path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(selected_questions)
    for i, q in enumerate(selected_questions, start=1):
        qid = str(q.get("id", ""))
        question_text = str(q.get("question", ""))
        traj_ids = haystack.get(qid, [])
        if not traj_ids:
            print(f"[retrieve] {i}/{total}  qid={qid}  WARN: empty haystack")
            continue
        memory.set_query_context(haystack=traj_ids)
        try:
            t0 = time.perf_counter()
            ctx_items = memory.query(question_text, query_image=q.get("question_image"))
            dt = time.perf_counter() - t0
        finally:
            memory.clear_query_context()
        ctx_texts = [
            item["value"] for item in ctx_items if item.get("type") == "text"
        ]
        n_chars = sum(len(t) for t in ctx_texts)
        print(
            f"[retrieve] {i}/{total}  qid={qid}  haystack={len(traj_ids)}  "
            f"ctx_items={len(ctx_items)} chars={n_chars}  t={dt:.1f}s"
        )
        # V2 uses `question_type` (V1-compatible naming). Some downstream
        # tools may add a `category` alias later; check both.
        category_raw = q.get("question_type") or q.get("category") or ""
        rows.append(
            {
                "question_id": qid,
                "domain": str(q.get("domain", "")),
                "category_raw": str(category_raw),
                "category": normalize_category(category_raw),
                "eval_function": str(q.get("eval_function", "")),
                "question": question_text,
                "reference_answer": str(q.get("answer", "")),
                "haystack_trajectory_ids": list(traj_ids),
                "memory_context_texts": ctx_texts,
                "memory_context_chars": n_chars,
                "retrieve_seconds": dt,
            }
        )
    write_jsonl(output_path, rows)
    print(f"[retrieve] wrote {len(rows)} rows -> {output_path}")
    return rows


async def _stage_generate(
    *,
    rm: Any,
    retrieve_rows: list[dict[str, Any]],
    domain: str,
    output_path: Path,
    concurrency: int,
) -> list[dict[str, Any]]:
    reader = await get_answer_llm(rm)
    sem = asyncio.Semaphore(concurrency)
    out_rows: list[dict[str, Any] | None] = [None] * len(retrieve_rows)

    async def _one(idx: int, row: dict[str, Any]) -> None:
        async with sem:
            messages = build_reader_messages(
                domain=domain,
                memory_context_texts=row.get("memory_context_texts", []),
                question=row["question"],
            )
            t0 = time.perf_counter()
            response = await reader.generate(messages)
            dt = time.perf_counter() - t0
            response_text = _extract_text(response)
            boxed = extract_boxed_answer(response_text)
            out_rows[idx] = {
                **row,
                "model_response": response_text,
                "boxed_answer": boxed,
                "generate_seconds": dt,
            }
            print(
                f"[generate] {idx + 1}/{len(retrieve_rows)}  qid={row['question_id']}  "
                f"boxed={boxed[:60]!r}  t={dt:.1f}s"
            )

    await asyncio.gather(*(_one(i, r) for i, r in enumerate(retrieve_rows)))
    finals = [r for r in out_rows if r is not None]
    write_jsonl(output_path, finals)
    print(f"[generate] wrote {len(finals)} rows -> {output_path}")
    return finals


async def _stage_judge(
    *,
    rm: Any,
    generate_rows: list[dict[str, Any]],
    output_path: Path,
    summary_path: Path,
    concurrency: int,
) -> dict[str, Any]:
    judge = await get_judge_llm(rm)
    sem = asyncio.Semaphore(concurrency)
    out_rows: list[dict[str, Any] | None] = [None] * len(generate_rows)

    async def _one(idx: int, row: dict[str, Any]) -> None:
        async with sem:
            messages = build_judge_messages(
                category=row["category"],
                question=row["question"],
                reference_answer=row["reference_answer"],
                model_response=row.get("boxed_answer") or row.get("model_response", ""),
            )
            t0 = time.perf_counter()
            verdict_raw = await judge.generate(messages)
            dt = time.perf_counter() - t0
            verdict_text = _extract_text(verdict_raw)
            is_correct = parse_yes_no_lenient(verdict_text)
            out_rows[idx] = {
                **row,
                "judge_verdict_raw": verdict_text,
                "is_correct": is_correct,
                "judge_seconds": dt,
            }
            print(
                f"[judge] {idx + 1}/{len(generate_rows)}  qid={row['question_id']}  "
                f"verdict={'YES' if is_correct else 'no '}  t={dt:.1f}s"
            )

    await asyncio.gather(*(_one(i, r) for i, r in enumerate(generate_rows)))
    finals = [r for r in out_rows if r is not None]
    write_jsonl(output_path, finals)

    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in finals:
        by_cat[r["category"]].append(bool(r["is_correct"]))
    n_total = len(finals)
    n_correct = sum(1 for r in finals if r["is_correct"])
    summary = {
        "n_questions": n_total,
        "n_correct": n_correct,
        "accuracy": (n_correct / n_total) if n_total else 0.0,
        "by_category": {
            cat: {
                "n": len(verdicts),
                "correct": sum(verdicts),
                "accuracy": (sum(verdicts) / len(verdicts)) if verdicts else 0.0,
            }
            for cat, verdicts in sorted(by_cat.items())
        },
    }
    summary_path.write_text(  # noqa: ASYNC240
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"[judge] wrote {n_total} rows -> {output_path}\n"
        f"[judge] overall accuracy: {summary['accuracy']:.3%} ({n_correct}/{n_total})"
    )
    for cat, st in summary["by_category"].items():
        print(f"  {cat}: {st['accuracy']:.3%} ({st['correct']}/{st['n']})")
    return summary


# ---------------------------------------------------------------------------
# LLM-response shape compatibility
# ---------------------------------------------------------------------------
def _extract_text(response: Any) -> str:
    """MemMachine LanguageModel.generate() returns vary across versions —
    accept str, list of strings, or objects with .content/.text fields."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, (list, tuple)):
        parts = [_extract_text(item) for item in response]
        return "\n".join(p for p in parts if p)
    for attr in ("content", "text", "message"):
        val = getattr(response, attr, None)
        if val is not None:
            return _extract_text(val)
    if isinstance(response, dict):
        for key in ("content", "text", "message"):
            if key in response:
                return _extract_text(response[key])
    return str(response)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--data-root",
        required=True,
        help="Root dir with questions.jsonl, trajectories.jsonl, haystacks/lme_v2_*.json",
    )
    p.add_argument(
        "--domain",
        required=True,
        choices=sorted(DOMAIN_SYSTEM_PROMPTS),
        help="Which V2 domain to evaluate",
    )
    p.add_argument(
        "--tier",
        default="small",
        choices=["small", "medium"],
        help="Haystack tier (lme_v2_small.json vs lme_v2_medium.json)",
    )
    p.add_argument(
        "--memmachine-configuration-path",
        default=None,
        help=(
            "MemMachine working configuration.yml. Used to build a default "
            "memmachine memory config when --memory-config-path is not given."
        ),
    )
    p.add_argument(
        "--memory-config-path",
        default=None,
        help=(
            "Explicit V2 memory_config.json. Takes precedence over "
            "--memmachine-configuration-path."
        ),
    )
    p.add_argument(
        "--session-prefix",
        default="lmev2",
        help="MemMachine session_id prefix (default: lmev2)",
    )
    p.add_argument("--top-k", type=int, default=50)
    p.add_argument(
        "--output-dir",
        required=True,
        help="Destination for retrieve/generate/judge.jsonl + summary.json",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Keep at most this many questions after type-filter + offset (default: all)",
    )
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "Skip the first N questions after type-filter (default: 0). "
            "Combine with --question-types and --limit for a stable "
            "'<type> N번째 ~ M번째' slice."
        ),
    )
    p.add_argument(
        "--question-ids",
        nargs="*",
        default=None,
        help="Restrict to these question ids (space- or comma-separated)",
    )
    p.add_argument(
        "--question-types",
        nargs="*",
        default=None,
        help=(
            "Filter by question_type (space- or comma-separated). Valid values: "
            "static-environment, static-environment-abs, dynamic-environment, "
            "dynamic-environment-abs, procedure, procedure-abs, errors-gotchas. "
            "See README for per-type counts."
        ),
    )
    p.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Assume Neo4j already has the trajectories — skip memory.insert()",
    )
    p.add_argument(
        "--skip-generate",
        action="store_true",
        help="Stop after retrieve.jsonl",
    )
    p.add_argument(
        "--skip-judge",
        action="store_true",
        help="Stop after generate.jsonl (no LLM judging)",
    )
    p.add_argument("--generate-concurrency", type=int, default=4)
    p.add_argument("--judge-concurrency", type=int, default=4)
    args = p.parse_args()

    data_root = Path(args.data_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Memory config ----
    if args.memory_config_path:
        memory_config = load_memory_config(args.memory_config_path)
    else:
        if not args.memmachine_configuration_path:
            raise SystemExit(
                "Either --memory-config-path or --memmachine-configuration-path is required."
            )
        memory_config = _build_default_memory_config(
            Path(args.memmachine_configuration_path).expanduser().resolve(),
            session_prefix=args.session_prefix,
            top_k=args.top_k,
        )

    # Persist resolved memory config for reproducibility.
    (output_dir / "memory_config.json").write_text(
        json.dumps(memory_config, indent=2) + "\n", encoding="utf-8"
    )

    # ---- Dataset ----
    questions, trajectories, haystack = _load_dataset(
        data_root, domain=args.domain, tier=args.tier
    )
    print(
        f"[main] dataset: {len(questions)} questions (domain={args.domain}), "
        f"{len(trajectories)} trajectories, haystack tier={args.tier}"
    )
    question_ids_parsed = _parse_csv_list(args.question_ids)
    question_types_parsed = _parse_csv_list(args.question_types)
    selected = _select_questions(
        questions,
        question_ids=question_ids_parsed,
        question_types=question_types_parsed,
        offset=args.offset,
        limit=args.limit,
    )
    print(
        f"[main] selected: {len(selected)} questions "
        f"(question_types={question_types_parsed}, offset={args.offset}, "
        f"limit={args.limit}, question_ids={question_ids_parsed})"
    )

    selected_traj_ids: set[str] = set()
    for q in selected:
        for tid in haystack.get(str(q.get("id", "")), []):
            selected_traj_ids.add(str(tid))
    print(f"[main] haystack covers {len(selected_traj_ids)} trajectories")

    # ---- Build memory ----
    memory = build_memory(memory_config)
    print(f"[main] built memory backend: {memory.memory_type}")

    # ---- Ingest ----
    if not args.skip_ingest:
        n = _stage_ingest(
            memory=memory,
            trajectories=trajectories,
            selected_traj_ids=selected_traj_ids,
        )
        print(f"[main] ingested {n} trajectories")
    else:
        print("[main] skip-ingest: trusting existing backend state")

    # ---- Retrieve ----
    retrieve_path = output_dir / "retrieve.jsonl"
    retrieve_rows = _stage_retrieve(
        memory=memory,
        selected_questions=selected,
        haystack=haystack,
        output_path=retrieve_path,
    )

    if args.skip_generate:
        return 0

    # ---- Generate ----
    if args.memory_config_path:
        raise SystemExit(
            "Generate/judge stages need a MemMachine configuration.yml for "
            "reader+judge LLMs. Pass --memmachine-configuration-path even "
            "when using --memory-config-path."
        ) if not args.memmachine_configuration_path else None
    rm = load_eval_config(args.memmachine_configuration_path)
    generate_path = output_dir / "generate.jsonl"
    generate_rows = asyncio.run(
        _stage_generate(
            rm=rm,
            retrieve_rows=retrieve_rows,
            domain=args.domain,
            output_path=generate_path,
            concurrency=args.generate_concurrency,
        )
    )

    if args.skip_judge:
        return 0

    # ---- Judge ----
    judge_path = output_dir / "judge.jsonl"
    summary_path = output_dir / "summary.json"
    asyncio.run(
        _stage_judge(
            rm=rm,
            generate_rows=generate_rows,
            output_path=judge_path,
            summary_path=summary_path,
            concurrency=args.judge_concurrency,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
