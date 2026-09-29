"""Verification 4 (in-house): map vectors stored in Qdrant back to .npy rows.

Scrolls one page of points with their vectors through Qdrant's REST API and
matches each by cosine similarity against the window: MemMachine creates
Qdrant collections with Distance.COSINE, and Qdrant re-normalizes vectors on
upsert, so byte equality does not hold. Plain httpx, so it runs in the mock
venv without qdrant-client.

  python checks/qdrant_row_check.py --qdrant http://QDRANT:6333 --collection NAME
      --vectors laion_100m.npy [--rows 0:1000000] [--limit 100]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
import numpy as np

import _rows

COS_TOL = 1e-6


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--qdrant", required=True, help="Qdrant REST URL, e.g. http://127.0.0.1:6333")
    p.add_argument("--collection", required=True)
    p.add_argument("--vectors", type=Path, required=True, help=".npy the mock serves")
    p.add_argument("--rows", help=f"row window to index, START:END (default: first {_rows.DEFAULT_WINDOW})")
    p.add_argument("--limit", type=int, default=100, help="points to scroll")
    return p.parse_args()


def named_vectors(vector: list | dict) -> list[tuple[str, list[float]]]:
    """Qdrant returns a plain list for the default vector, a dict for named ones."""
    if isinstance(vector, dict):
        return list(vector.items())
    return [("", vector)]


def main(args: argparse.Namespace) -> int:
    vectors = _rows.open_vectors(args.vectors)
    start, end = _rows.resolve_window(args.rows, vectors)
    window_norm = _rows.build_norm_index(vectors, start, end)

    r = httpx.post(
        f"{args.qdrant}/collections/{args.collection}/points/scroll",
        json={"limit": args.limit, "with_vector": True, "with_payload": False},
        timeout=60,
    )
    r.raise_for_status()
    points = r.json()["result"]["points"]
    print(f"{len(points)} point(s) in {args.collection}; rows {start}:{end} of {args.vectors}")

    n, unmatched = 0, 0
    for p in points:
        for name, vec in named_vectors(p["vector"]):
            n += 1
            row, one_minus_cos = _rows.find_row_cosine(window_norm, start, np.asarray(vec, dtype=np.float32))
            label = f"{p['id']} ({name})" if name else str(p["id"])
            if one_minus_cos <= COS_TOL:
                print(f"{label} -> row {row} (1-cos {one_minus_cos:.1e})")
            else:
                unmatched += 1
                print(f"{label} -> no match (best row {row}, 1-cos {one_minus_cos:.1e})")

    if unmatched:
        print(f"FAIL qdrant_row_check: {unmatched} of {n} unmatched")
        return 1
    print("PASS qdrant_row_check")
    return 0


if __name__ == "__main__":
    sys.exit(main(parse_args()))
