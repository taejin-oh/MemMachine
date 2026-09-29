"""Command line entry point: `python -m mock_inference <command>`.

Subcommand modules are imported lazily so that `synth` and `info` work in an
environment without the server dependencies.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mock-inference",
        description="Mock embedding and rerank server that serves real dataset vectors.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="serve /v1/embeddings and /v2/rerank from a .npy file")
    p.add_argument("--vectors", type=Path, required=True, help=".npy vector file")
    p.add_argument("--target-rps", type=int, help="pick worker count for this load")
    p.add_argument("--rps-per-worker", type=int, default=1000, help="assumed per-worker capacity")
    p.add_argument("--workers", type=int, help="worker count (overrides --target-rps)")
    p.add_argument("--cores", help="pin to cores, e.g. 0-11 or 0,2,4 (Linux only)")
    p.add_argument("--mode", choices=["sequential", "hash"], default="sequential")
    p.add_argument("--chunk", type=int, default=20_000, help="rows leased per worker at a time")
    p.add_argument("--range", dest="row_range", help="rows this host serves, START:END")
    p.add_argument("--state-dir", type=Path, help="where state.json lives (default: next to --vectors)")
    p.add_argument("--reset", action="store_true", help="restart the stream from START")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)

    p = sub.add_parser("reset", help="reset the stream position without starting a server")
    p.add_argument("--vectors", type=Path, required=True, help=".npy vector file")
    p.add_argument("--state-dir", type=Path, help="where state.json lives (default: next to --vectors)")
    p.add_argument("--range", dest="row_range", help="rows this host serves, START:END")

    p = sub.add_parser("convert", help="convert parquet files into one .npy file")
    p.add_argument("--parquet-glob")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--jobs", type=int, default=os.cpu_count(), help="parallel files")
    p.add_argument("--rows", type=int, help="convert only the first ROWS rows")
    p.add_argument("--vector-column", help="override auto-detected vector column")
    p.add_argument("--verify-only", action="store_true", help="only re-run the sample check")

    p = sub.add_parser("info", help="print .npy header and size check")
    p.add_argument("path", type=Path)

    p = sub.add_parser("synth", help="write a synthetic .npy file")
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("--dim", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser("synth-parquet", help="write synthetic parquet files (Zilliz schema)")
    p.add_argument("--files", type=int, required=True)
    p.add_argument("--rows-per-file", type=int, required=True)
    p.add_argument("--dim", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--row-group-size", type=int, default=4000)
    p.add_argument(
        "--schema-variant",
        choices=["largelist32", "list32", "largelist64"],
        default="largelist32",
    )
    p.add_argument("--out-dir", type=Path, required=True)

    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "serve":
        from . import serve

        return serve.run(args)
    if args.command == "reset":
        from . import vecstream

        total, _ = vecstream.open_vectors(args.vectors).shape
        start, end = vecstream.parse_range(args.row_range, total)
        vecstream.reset_state(args.vectors, args.state_dir, start, end)
        state_file, _ = vecstream.state_paths(args.vectors, args.state_dir)
        print(f"reset {state_file}: next={start}, start={start}, end={end}")
        return 0
    if args.command == "convert":
        from . import convert

        return convert.run(args)
    if args.command == "info":
        from . import vecstream

        return vecstream.print_info(args.path)
    if args.command == "synth":
        from . import synth

        synth.write_npy(args.out, args.rows, args.dim, args.seed)
        return 0
    if args.command == "synth-parquet":
        from . import synth

        synth.write_parquet(
            args.out_dir,
            files=args.files,
            rows_per_file=args.rows_per_file,
            dim=args.dim,
            seed=args.seed,
            row_group_size=args.row_group_size,
            schema_variant=args.schema_variant,
        )
        return 0
    raise AssertionError(args.command)
