"""Verification 1: round-trip through the openai and cohere SDKs.

Every embedding the mock returns must be byte-identical to some row of the
.npy file, and rerank must keep the input order with descending scores.

  python checks/sdk_roundtrip.py --base http://127.0.0.1:8000 --vectors X.npy
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import cohere
import numpy as np
import openai

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
    p.add_argument("--rows", help=f"row window to index, START:END (default: first {_rows.DEFAULT_WINDOW})")
    return p.parse_args()


async def main(args: argparse.Namespace) -> int:
    base = args.base.rstrip("/")
    vectors = _rows.open_vectors(args.vectors)
    dim = vectors.shape[1]
    start, end = _rows.resolve_window(args.rows, vectors)
    index = _rows.build_index(vectors, start, end)
    print(f"indexed rows {start}:{end} of {args.vectors} (dim {dim})")

    async with (
        openai.AsyncOpenAI(base_url=base + "/v1", api_key="x") as oa,
        cohere.AsyncClientV2(api_key="x", base_url=base) as co,
    ):
        # What MemMachine sends: base64 on the wire plus the dimensions parameter.
        r = await oa.embeddings.create(
            input=["a", "b"], model="mock-embed", dimensions=dim, encoding_format="base64"
        )
        vecs = [_rows.decode_base64(d.embedding) for d in r.data]
        rows = _rows.find_rows(index, vecs)
        check("embeddings base64: length", all(len(v) == dim for v in vecs), f"{[len(v) for v in vecs]}")
        check("embeddings base64: byte-identical rows", None not in rows, f"rows {rows}")

        r = await oa.embeddings.create(input=["a", "b"], model="mock-embed", encoding_format="float")
        vecs = [np.asarray(d.embedding, dtype="<f4") for d in r.data]
        rows = _rows.find_rows(index, vecs)
        check("embeddings float: length", all(len(v) == dim for v in vecs), f"{[len(v) for v in vecs]}")
        check("embeddings float: byte-identical rows", None not in rows, f"rows {rows}")

        # SDK default: it asks for base64 and decodes to floats itself.
        r = await oa.embeddings.create(input="a", model="mock-embed")
        rows = _rows.find_rows(index, [np.asarray(d.embedding, dtype="<f4") for d in r.data])
        check("embeddings default: byte-identical row", rows and None not in rows, f"rows {rows}")

        r = await co.rerank(model="mock-rerank", query="q", documents=["a", "b", "c"])
        order = [x.index for x in r.results]
        scores = [x.relevance_score for x in r.results]
        check("rerank: index == position", order == [0, 1, 2], f"index {order}")
        check("rerank: scores descending", all(a > b for a, b in zip(scores, scores[1:])), f"scores {scores}")

        # The exact call MemMachine's RerankerManager uses to validate a reranker.
        r = await co.rerank(model="mock-rerank", query="a", documents=["a", "b"])
        check("rerank: validation call", [x.index for x in r.results] == [0, 1])

    if failures:
        print(f"FAIL sdk_roundtrip: {len(failures)} check(s) failed")
        return 1
    print("PASS sdk_roundtrip")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
