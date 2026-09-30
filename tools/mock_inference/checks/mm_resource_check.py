"""Verification 6: MemMachine's ResourceManagerImpl builds the mock embedder
and reranker, their validate calls pass, and no database is involved.

Needs memmachine_server, so run it with the speedkick venv:

  .venv/bin/python checks/mm_resource_check.py --config checks/mm_mock_config.yml
      [--health http://127.0.0.1:8000/health]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from memmachine_server.common.configuration import Configuration
from memmachine_server.common.resource_manager.resource_manager import ResourceManagerImpl

EMBEDDER = "mock_embedder"
RERANKER = "mock_reranker"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True, help="MemMachine YAML with mock_embedder and mock_reranker")
    p.add_argument("--health", help="the mock's /health URL; checks that next advanced by whole leases")
    return p.parse_args()


async def main(args: argparse.Namespace) -> int:
    cfg = Configuration.load_yml_file(args.config)
    dim = cfg.resources.embedders.openai[EMBEDDER].dimensions
    before = httpx.get(args.health).json() if args.health else None

    rm = ResourceManagerImpl(cfg)
    try:
        embedder = await rm.get_embedder(EMBEDDER, validate=True)
        reranker = await rm.get_reranker(RERANKER, validate=True)
        vecs = await embedder.ingest_embed(["a", "b"])
        scores = await reranker.score("q", ["a", "b", "c"])
    finally:
        await rm.close()

    print("ok   embedder and reranker validated")
    check("ingest_embed: 2 vectors of dim", len(vecs) == 2 and all(len(v) == dim for v in vecs),
          f"{len(vecs)} vectors, lengths {[len(v) for v in vecs]}, dim {dim}")
    check("score: descending", all(a > b for a, b in zip(scores, scores[1:])), f"scores {scores}")

    if args.health:
        after = httpx.get(args.health).json()
        leases, rest = divmod(after["next"] - before["next"], after["chunk"])
        # 0 is normal on a warm server: validation rows can come out of leases taken earlier.
        check("health: next advanced by <=workers whole leases", rest == 0 and 0 <= leases <= after["workers"],
              f"next {before['next']} -> {after['next']}, chunk {after['chunk']}, workers {after['workers']}"
              + (" (0 = served from existing leases)" if leases == 0 else ""))

    if failures:
        print(f"FAIL mm_resource_check: {len(failures)} check(s) failed")
        return 1
    print("PASS mm_resource_check")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
