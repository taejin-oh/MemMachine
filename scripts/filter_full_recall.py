#!/usr/bin/env python3
"""Keep retrieve rows where every supporting_fact is present in chunks_text.

For each row in the input, parses chunks_text into per-line content
(`json.loads()` of the segment after `<role>: `), normalizes whitespace,
and checks that every `supporting_fact` (similarly normalized) appears in
that set. Rows with empty supporting_facts are dropped (no signal). Matching
is exact equality — the fact_hits substring + token-overlap heuristic is
NOT used.

Output rows are the same retrieve-shape JSONL the input had, suitable for
`regen_answer.py --retrieve <out>`.

Usage:
    python scripts/filter_full_recall.py \
        --retrieve results/sclean_full/retrieve.failed.jsonl \
        --out      results/sclean_full/retrieve.gen_failed.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.stages._common import read_jsonl, write_jsonl  # noqa: E402

_LINE_SEP = "] user: "
_ALT_SEP = "] assistant: "


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_chunk_content(line: str) -> str | None:
    for sep in (_LINE_SEP, _ALT_SEP):
        idx = line.find(sep)
        if idx >= 0:
            try:
                return json.loads(line[idx + len(sep) :].strip())
            except json.JSONDecodeError:
                return None
    return None


def _system_contents(chunks_text: str) -> set[str]:
    out: set[str] = set()
    for line in (chunks_text or "").split("\n"):
        if not line.strip():
            continue
        c = _parse_chunk_content(line)
        if c is not None:
            out.add(_norm(c))
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--retrieve", required=True, help="Source retrieve.jsonl.")
    p.add_argument(
        "--out",
        default=None,
        help="Output path. Default: <retrieve dir>/retrieve.gen_failed.jsonl",
    )
    args = p.parse_args()

    src = Path(args.retrieve).resolve()
    out_path = (
        Path(args.out).resolve()
        if args.out
        else src.parent / "retrieve.gen_failed.jsonl"
    )

    rows = read_jsonl(src)
    kept: list[dict] = []
    skipped_empty_sf = 0
    skipped_partial = 0
    for row in rows:
        sf = row.get("supporting_facts") or []
        if not sf:
            skipped_empty_sf += 1
            continue
        sys_set = _system_contents(str(row.get("chunks_text", "")))
        all_present = all(_norm(f) in sys_set for f in sf)
        if all_present:
            kept.append(row)
        else:
            skipped_partial += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_written = write_jsonl(out_path, kept)
    print(
        f"[filter_full_recall] {len(rows)} in; "
        f"{n_written} kept (100% supporting_facts present); "
        f"{skipped_partial} partial recall; "
        f"{skipped_empty_sf} empty supporting_facts -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
