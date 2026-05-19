#!/usr/bin/env python3
"""Build 3 retrieve.jsonl variants that differ only in supporting_facts position.

Given a source retrieve.jsonl, identify which `chunks_text` lines carry the
supporting_facts (exact content match after whitespace normalization), then
re-emit three variants where the fact lines are pinned to:

    front   — all fact lines at the top (in original fact-list order)
    middle  — non-fact lines split in half; facts placed at the boundary
    end     — all fact lines at the bottom

Missing-fact injection: if a supporting_fact is not present in the source
chunks_text (i.e. the live retrieval missed it), the script synthesizes a
matching line in the oracle line format so all three variants carry the same
fact set. The synthetic timestamp is `last_observed_ts + N seconds` (or
`now() + N` if the source has no parseable timestamp). Toggle with
`--inject-missing` (default ON).

Output files:
    <out-dir>/front/retrieve.jsonl
    <out-dir>/middle/retrieve.jsonl
    <out-dir>/end/retrieve.jsonl

Downstream (manual):
    for pos in front middle end; do
        uv run python scripts/regen_answer.py \
            --run <name>_pos_$pos \
            --retrieve <out-dir>/$pos/retrieve.jsonl
        uv run python scripts/run_pipeline.py \
            --config configs/runs/<name>_pos_$pos.yaml \
            --stage judge,analyze
    done
    uv run python scripts/compare_runs.py \
        --runs <out-dir>/front <out-dir>/middle <out-dir>/end \
        --labels front middle end

Usage:
    python scripts/permute_facts_position.py \
        --retrieve results/sclean_full/retrieve.jsonl \
        --out-dir results/sclean_position
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.retrieval_agent.longmemeval_test import _split_chunks  # noqa: E402
from scripts.stages._common import read_jsonl, write_jsonl  # noqa: E402

_LINE_SEP = "] user: "
_ALT_SEP = "] assistant: "
_TS_FMT_DATE = "%A, %B %d, %Y"
_TS_FMT_TIME = "%I:%M %p"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_line(line: str) -> tuple[str | None, str | None]:
    """Return (content, producer) — None when line doesn't match the format."""
    for sep, producer in ((_LINE_SEP, "user"), (_ALT_SEP, "assistant")):
        idx = line.find(sep)
        if idx >= 0:
            try:
                return json.loads(line[idx + len(sep) :].strip()), producer
            except json.JSONDecodeError:
                return None, None
    return None, None


def _parse_timestamp(line: str) -> datetime | None:
    if not line.startswith("["):
        return None
    end = line.find("]")
    if end < 0:
        return None
    inner = line[1:end]
    if " at " not in inner:
        return None
    date_part, _, time_part = inner.partition(" at ")
    try:
        return datetime.strptime(
            f"{date_part} at {time_part}", f"{_TS_FMT_DATE} at {_TS_FMT_TIME}"
        ).replace(tzinfo=UTC)
    except ValueError:
        return None


def _synth_line(content: str, ts: datetime) -> str:
    return (
        f"[{ts.strftime(_TS_FMT_DATE)} at {ts.strftime(_TS_FMT_TIME)}] "
        f"user: {json.dumps(content)}\n"
    )


def _classify_lines(
    chunks_text: str, fact_norms: set[str]
) -> tuple[list[str], list[str], datetime | None]:
    """Split chunks_text lines into (fact_lines, other_lines, last_ts)."""
    fact_lines: list[str] = []
    other_lines: list[str] = []
    last_ts: datetime | None = None
    for raw in (chunks_text or "").split("\n"):
        if not raw.strip():
            continue
        content, _ = _parse_line(raw)
        line_with_nl = raw if raw.endswith("\n") else raw + "\n"
        ts = _parse_timestamp(raw)
        if ts is not None:
            last_ts = ts if last_ts is None or ts > last_ts else last_ts
        if content is not None and _norm(content) in fact_norms:
            fact_lines.append(line_with_nl)
        else:
            other_lines.append(line_with_nl)
    return fact_lines, other_lines, last_ts


def _inject_missing(
    fact_lines: list[str],
    supporting_facts: list[str],
    last_ts: datetime | None,
) -> tuple[list[str], int]:
    """Append synthetic lines for fact pieces not yet represented.

    supporting_facts are full turn contents; ingest splits >3000-char turns
    into multiple chunks (Episodes). To match how chunks_text is composed,
    inject one synthetic line per _split_chunks() piece of each fact.
    """
    present = set()
    for line in fact_lines:
        c, _ = _parse_line(line)
        if c is not None:
            present.add(_norm(c))
    base_ts = last_ts or datetime.now(UTC)
    out_lines = list(fact_lines)
    n_injected = 0
    for fact in supporting_facts:
        for piece in _split_chunks(fact):
            if _norm(piece) in present:
                continue
            n_injected += 1
            base_ts = base_ts + timedelta(seconds=1)
            out_lines.append(_synth_line(piece, base_ts))
            present.add(_norm(piece))
    return out_lines, n_injected


def _assemble(
    fact_lines: list[str], other_lines: list[str], position: str
) -> str:
    if position == "front":
        return "".join(fact_lines + other_lines)
    if position == "end":
        return "".join(other_lines + fact_lines)
    if position == "middle":
        mid = len(other_lines) // 2
        return "".join(other_lines[:mid] + fact_lines + other_lines[mid:])
    raise ValueError(f"unknown position: {position}")


def _build_variant_row(
    row: dict[str, Any],
    fact_lines: list[str],
    other_lines: list[str],
    position: str,
) -> dict[str, Any]:
    chunks_text = _assemble(fact_lines, other_lines, position)
    n_lines = sum(1 for line in chunks_text.split("\n") if line.strip())
    new_row = dict(row)
    new_row["chunks_text"] = chunks_text
    new_row["num_episodes_retrieved"] = n_lines
    sweep = dict(new_row.get("sweep") or {})
    sweep["fact_position"] = position
    new_row["sweep"] = sweep
    new_row["fact_hits"] = []
    new_row["fact_miss"] = []
    return new_row


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--retrieve",
        required=True,
        help="Source retrieve.jsonl (typically the s_cleaned full run).",
    )
    p.add_argument(
        "--out-dir",
        required=True,
        help="Parent directory; <out-dir>/{front,middle,end}/retrieve.jsonl emitted.",
    )
    p.add_argument(
        "--inject-missing",
        dest="inject_missing",
        action="store_true",
        default=True,
        help="(default ON) Synthesize lines for supporting_facts not present "
        "in the source so all 3 variants share the same fact set.",
    )
    p.add_argument(
        "--no-inject-missing",
        dest="inject_missing",
        action="store_false",
        help="Only reorder facts already present; missing facts stay missing.",
    )
    p.add_argument(
        "--include-categories",
        default=None,
        help=(
            "Comma-separated question_type values to keep (e.g. "
            "'temporal-reasoning,multi-session'). Default: keep all."
        ),
    )
    args = p.parse_args()

    src_path = Path(args.retrieve).resolve()
    out_dir = Path(args.out_dir).resolve()
    rows = read_jsonl(src_path)

    if args.include_categories:
        keep = {c.strip() for c in args.include_categories.split(",") if c.strip()}
        before = len(rows)
        rows = [r for r in rows if str(r.get("category", "")) in keep]
        print(
            f"[permute] category filter "
            f"{sorted(keep)}: {before} -> {len(rows)} rows"
        )

    variants: dict[str, list[dict[str, Any]]] = {"front": [], "middle": [], "end": []}
    total_injected = 0
    rows_with_inject = 0
    rows_missing_facts = 0

    for row in rows:
        sf = list(row.get("supporting_facts") or [])
        # Match at piece-level: a chunks_text line is a "fact line" iff its
        # content equals any _split_chunks() piece of any supporting_fact.
        # (Whole-fact match misses long facts that ingest split across chunks.)
        sf_pieces: list[tuple[str, str]] = []  # (fact_index_label, piece)
        for idx, fact in enumerate(sf):
            for piece in _split_chunks(fact):
                sf_pieces.append((f"{idx}", piece))
        fact_norms = {_norm(p) for _, p in sf_pieces}
        fact_lines, other_lines, last_ts = _classify_lines(
            str(row.get("chunks_text", "")), fact_norms
        )
        if args.inject_missing and sf:
            fact_lines, n_inj = _inject_missing(fact_lines, sf, last_ts)
            if n_inj > 0:
                total_injected += n_inj
                rows_with_inject += 1
        # Re-order fact_lines so pieces appear in (fact-index, piece-index) order.
        norm_to_line: dict[str, str] = {}
        for line in fact_lines:
            c, _ = _parse_line(line)
            if c is not None:
                norm_to_line.setdefault(_norm(c), line)
        ordered_fact_lines: list[str] = []
        for _, piece in sf_pieces:
            line = norm_to_line.get(_norm(piece))
            if line is not None and line not in ordered_fact_lines:
                ordered_fact_lines.append(line)
        # Any leftover fact_lines (post-inject shouldn't exist) — keep at end.
        leftover = [line for line in fact_lines if line not in ordered_fact_lines]
        ordered_fact_lines.extend(leftover)
        if sf and not ordered_fact_lines:
            rows_missing_facts += 1

        for pos in ("front", "middle", "end"):
            variants[pos].append(
                _build_variant_row(row, ordered_fact_lines, other_lines, pos)
            )

    for pos, rows_out in variants.items():
        out_path = out_dir / pos / "retrieve.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(out_path, rows_out)
        print(f"[permute] wrote {len(rows_out)} rows -> {out_path}")

    print(
        f"[permute] injected {total_injected} synthetic lines across "
        f"{rows_with_inject} rows"
        f"{' (inject_missing=ON)' if args.inject_missing else ''}"
    )
    if rows_missing_facts:
        print(
            f"[permute] WARNING: {rows_missing_facts} rows had supporting_facts "
            f"but zero fact lines after classification (inject was OFF or content mismatch)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
