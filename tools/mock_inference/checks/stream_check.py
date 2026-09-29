"""Verification 3: many clients, many workers, no row served twice.

Clients hammer /v1/embeddings with 1..100 inputs each until `--total` vectors
have been received. Every vector is mapped back to its row: rows must be
unique, and the only rows missing from [start, next) are those a worker has
leased but not yet served (at most workers x chunk). With --after, every row
must lie beyond the previous run's maximum (restart continues the stream).

  python checks/stream_check.py --base http://127.0.0.1:8000 --vectors X.npy
      --clients 64 --total 100000 --out run1.json [--after run0.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import httpx

import _rows

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True, help="mock base URL, e.g. http://127.0.0.1:8000")
    p.add_argument("--vectors", type=Path, required=True, help=".npy the mock serves")
    p.add_argument("--clients", type=int, default=64, help="concurrent clients")
    p.add_argument("--total", type=int, default=100_000, help="vectors to receive in total")
    p.add_argument("--out", type=Path, required=True, help="write this run's summary JSON here")
    p.add_argument("--after", type=Path, help="summary JSON of the previous run (restart check)")
    p.add_argument("--rows", help=f"row window to index, START:END (default: first {_rows.DEFAULT_WINDOW})")
    return p.parse_args()


async def collect(base: str, clients: int, total: int, index: dict[int, int]) -> list[int | None]:
    """Receive `total` vectors over `clients` connections; return their row numbers."""
    remaining = total
    rows: list[int | None] = []

    async def one_client(http: httpx.AsyncClient) -> None:
        nonlocal remaining
        while remaining > 0:
            n = min(random.randint(1, 100), remaining)
            remaining -= n
            r = await http.post("/v1/embeddings", json={"input": ["x"] * n, "model": "mock-embed"})
            r.raise_for_status()
            data = r.json()["data"]
            if len(data) != n:
                raise RuntimeError(f"asked for {n} vectors, got {len(data)}")
            rows.extend(_rows.find_rows(index, (_rows.decode_base64(d["embedding"]) for d in data)))

    limits = httpx.Limits(max_connections=clients, max_keepalive_connections=clients)
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=60) as http:
        await asyncio.gather(*(one_client(http) for _ in range(clients)))
    return rows


async def main(args: argparse.Namespace) -> int:
    base = args.base.rstrip("/")
    vectors = _rows.open_vectors(args.vectors)
    start, end = _rows.resolve_window(args.rows, vectors)
    index = _rows.build_index(vectors, start, end)
    print(f"indexed rows {start}:{end} of {args.vectors}")

    # This run consumes [first, next): `first` is the stream position before it
    # (the file start on a fresh server, the persisted position after a restart).
    first = httpx.get(base + "/health").json()["next"]
    rows = await collect(base, args.clients, args.total, index)
    health = httpx.get(base + "/health").json()
    next_row, workers, chunk, wraps = health["next"], health["workers"], health["chunk"], health["wraps"]
    print(f"health: next {first} -> {next_row}, workers {workers}, chunk {chunk}, wraps {wraps}")

    known = [r for r in rows if r is not None]
    seen = set(known)
    lowest, highest = (min(seen), max(seen)) if seen else (None, None)
    duplicates = len(known) - len(seen)
    missing = sum(1 for r in range(first, next_row) if r not in seen)

    check("received all vectors", len(rows) == args.total, f"{len(rows)} of {args.total}")
    check("every vector is a row in the window", len(known) == len(rows), f"{len(rows) - len(known)} unknown")
    check("no row served twice", duplicates == 0, f"{duplicates} duplicates")
    check("stream did not wrap", wraps == 0, f"wraps {wraps}" + (" (larger file or smaller --total)" if wraps else ""))
    check("all rows in [first, next)", all(first <= r < next_row for r in seen))
    check("missing rows <= workers x chunk", missing <= workers * chunk, f"{missing} <= {workers * chunk}")

    if args.after:
        previous_max = json.loads(args.after.read_text())["indices_max"]
        check("restart: all rows beyond previous run", lowest is not None and lowest > previous_max,
              f"{lowest} > {previous_max}")

    summary = {"indices_max": highest, "count": len(rows), "duplicates": duplicates, "missing": missing}
    args.out.write_text(json.dumps(summary) + "\n")
    print(f"wrote {args.out}: {summary}")

    label = "stream_check (restart)" if args.after else "stream_check"
    if failures:
        print(f"FAIL {label}: {len(failures)} check(s) failed")
        return 1
    print(f"PASS {label}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
