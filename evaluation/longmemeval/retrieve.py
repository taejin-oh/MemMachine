#!/usr/bin/env python3
"""LongMemEval — per-question isolated retrieval, upstream-style.

Mirrors xiaowu0162/LongMemEval `src/retrieval/run_retrieval.py`: each
question gets a fresh in-memory corpus built only from its own
`haystack_sessions`, indexed and queried in isolation. No persistent DB,
no cross-question contamination — same setup the upstream benchmark and
its leaderboard numbers are computed under.

Outputs retrieve.jsonl in this branch's pipeline schema so the existing
analysis tools (scripts/recall_curve.py, scripts/plot_recall_curve.py,
scripts/filter_full_recall.py, etc.) consume it as-is.

Retriever: dense (sentence-transformers / HuggingFace AutoModel-backed).
Corpus granularity: 'turn' (each user/assistant message is a corpus item) —
matches our piece-level recall measurement.

Usage:
    uv run python -m evaluation.longmemeval.retrieve \\
        --data-path evaluation/data/longmemeval_s_cleaned.json \\
        --model BAAI/bge-base-en-v1.5 \\
        --top-k 50 \\
        --out results/lme_iso_bge/retrieve.jsonl

    # match upstream's flat-contriever / flat-stella / flat-gte by swapping
    # --model to facebook/contriever, Alibaba-NLP/gte-Qwen2-7B-instruct, etc.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DATE_FMT = "%A, %B %d, %Y"
_TIME_FMT = "%I:%M %p"


def _format_line(role: str, content: str, ts: datetime) -> str:
    return (
        f"[{ts.strftime(_DATE_FMT)} at {ts.strftime(_TIME_FMT)}] "
        f"{role}: {json.dumps(content)}\n"
    )


def _parse_session_dt(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


def _collect_supporting_facts(sample: dict) -> list[str]:
    facts: list[str] = []
    for session in sample.get("haystack_sessions", []) or []:
        for turn in session or []:
            if turn.get("has_answer"):
                content = str(turn.get("content", "")).strip()
                if content:
                    facts.append(content)
    return facts


def _build_corpus(sample: dict) -> list[dict]:
    """Per-question corpus, granularity='turn'.

    Each turn is one corpus item. Timestamp = session_date + (turn_idx
    seconds), the same convention as main's evaluation/episodic_memory/
    longmemeval_models.py uses.
    """
    items: list[dict] = []
    for sid, sess, sdate in zip(
        sample.get("haystack_session_ids", []) or [],
        sample.get("haystack_sessions", []) or [],
        sample.get("haystack_dates", []) or [],
        strict=False,
    ):
        try:
            base_dt = _parse_session_dt(sdate)
        except (TypeError, ValueError):
            base_dt = datetime.now(UTC)
        for i, turn in enumerate(sess or []):
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            items.append(
                {
                    "text": content,
                    "role": str(turn.get("role", "user")),
                    "ts": base_dt + timedelta(seconds=i),
                    "session_id": sid,
                    "turn_idx": i,
                    "has_answer": bool(turn.get("has_answer")),
                }
            )
    return items


def _retrieve_one(
    model: SentenceTransformer,
    query: str,
    corpus: list[dict],
    top_k: int,
    batch_size: int,
) -> tuple[list[dict], float]:
    if not corpus:
        return [], 0.0
    texts = [it["text"] for it in corpus]
    t0 = time.time()
    corpus_vecs = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
        batch_size=batch_size,
    )
    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )[0]
    scores = corpus_vecs @ query_vec  # cosine similarity (both normalized)
    top_idx = np.argsort(-scores)[:top_k]
    latency = time.time() - t0
    return [corpus[int(i)] for i in top_idx], latency


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--data-path",
        required=True,
        help="Path to longmemeval_*.json (e.g. evaluation/data/longmemeval_s_cleaned.json)",
    )
    p.add_argument(
        "--model",
        default="BAAI/bge-base-en-v1.5",
        help="HuggingFace model id for dense retrieval (default: BAAI/bge-base-en-v1.5)",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=50,
        help="Retrieved turns per question (default: 50)",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output retrieve.jsonl path (this-branch schema)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N questions (smoke-test).",
    )
    p.add_argument(
        "--include-categories",
        default=None,
        help="Comma-separated question_type filter. Default: keep all.",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Encoding batch size (default: 64).",
    )
    args = p.parse_args()

    out_path = Path(args.out).resolve()
    with open(args.data_path) as f:
        dataset = json.load(f)

    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(dataset)
        dataset = [s for s in dataset if str(s.get("question_type", "")) in keep]
        print(
            f"[lme] category filter {sorted(keep)}: "
            f"{before} -> {len(dataset)} samples"
        )
    if args.limit is not None:
        dataset = dataset[: args.limit]

    print(f"[lme] loading model {args.model}...")
    model = SentenceTransformer(args.model)
    print(
        f"[lme] loaded; dim={model.get_sentence_embedding_dimension()}  "
        f"n_questions={len(dataset)}  top_k={args.top_k}"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_written = 0
    with open(out_path, "w") as f:
        for sample in dataset:
            qid = str(sample.get("question_id", ""))
            question = str(sample.get("question", "")).strip()
            if not question:
                continue
            corpus = _build_corpus(sample)
            top, latency = _retrieve_one(
                model, question, corpus, args.top_k, args.batch_size
            )
            chunks_text = "".join(
                _format_line(it["role"], it["text"], it["ts"]) for it in top
            )
            row = {
                "question": question,
                "question_id": qid,
                "category": str(sample.get("question_type", "")),
                "sweep": {},
                "cell_idx": 0,
                "chunks_text": chunks_text,
                "num_episodes_retrieved": len(top),
                "memory_retrieval_time": latency,
                "memory_search_called": 1,
                "agent": "lme_upstream",
                "selected_tool": "lme_upstream",
                "supporting_facts": _collect_supporting_facts(sample),
                "input_token": 0,
                "output_token": 0,
                "tool_select_input_token": 0,
                "tool_select_output_token": 0,
                "fact_hits": [],
                "fact_miss": [],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_written += 1
            print(
                f"[lme] {n_written}/{len(dataset)}  qid={qid}  "
                f"corpus={len(corpus)}  ret={len(top)}  t={latency:.2f}s"
            )

    print(f"[lme] wrote {n_written} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
