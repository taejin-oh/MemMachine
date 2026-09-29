"""`serve` subcommand: pick the worker count, pin cores, hand the config to uvicorn (design doc §10)."""

from __future__ import annotations

import argparse
import logging
import math
import os
import socket
import sys

import uvicorn

from . import vecstream

log = logging.getLogger("mock_inference")


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
    if args.chunk < 1:
        raise ValueError("--chunk must be >= 1")
    _probe_bind(args.host, args.port)
    total, dim = vecstream.open_vectors(args.vectors).shape
    start, end = vecstream.parse_range(args.row_range, total)
    workers = worker_count(args)
    affinity = pin_cores(parse_cores(args.cores), workers) if args.cores else None
    if args.mode == "sequential":
        if args.reset:
            vecstream.reset_state(args.vectors, args.state_dir, start, end)
        vecstream.ensure_state(args.vectors, args.state_dir, start, end)

    os.environ.update(
        {
            "MOCKINF_VECTORS": str(args.vectors),
            "MOCKINF_MODE": args.mode,
            "MOCKINF_RANGE": f"{start}:{end}",
            "MOCKINF_CHUNK": str(args.chunk),
            "MOCKINF_STATE_DIR": str(args.state_dir) if args.state_dir else "",
            "MOCKINF_WORKERS": str(workers),
            "MOCKINF_AFFINITY": ",".join(str(core) for core in affinity) if affinity else "",
        }
    )
    log.info(
        "serving %s: %d rows x %d dims, range %d:%d, mode %s, workers %d, affinity %s",
        args.vectors, total, dim, start, end, args.mode, workers, affinity,
    )
    uvicorn.run(
        "mock_inference.app:app",
        host=args.host,
        port=args.port,
        workers=workers,
        loop="uvloop",
        http="httptools",
        lifespan="off",
        access_log=False,
        backlog=4096,
        timeout_keep_alive=75,
    )
    return 0


def _probe_bind(host: str, port: int) -> None:
    """Fail fast if (host, port) is already bound, before state is touched or workers start.

    Without this, `serve --reset` run by hand against a live server on the same
    port rewrites the shared state and only then fails to bind, silently
    rewinding the running service (design doc §17).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as e:
        raise RuntimeError(f"port already in use: {host}:{port}") from e
    finally:
        sock.close()


def worker_count(args: argparse.Namespace) -> int:
    """--workers wins; otherwise ceil(target_rps / rps_per_worker); otherwise 1."""
    if args.workers is not None and args.workers < 1:
        raise ValueError("--workers must be >= 1")
    if args.target_rps is not None and args.target_rps < 1:
        raise ValueError("--target-rps must be >= 1")
    if args.rps_per_worker < 1:
        raise ValueError("--rps-per-worker must be >= 1")
    if args.workers:
        return args.workers
    if args.target_rps:
        return math.ceil(args.target_rps / args.rps_per_worker)
    return 1


def parse_cores(text: str) -> list[int]:
    """"0-11" or "0,2,4" (or a mix of both) -> sorted core ids."""
    cores: set[int] = set()
    try:
        for part in text.split(","):
            low, _, high = part.partition("-")
            cores.update(range(int(low), int(high or low) + 1))
    except ValueError:
        raise ValueError(f"--cores must look like 0-11 or 0,2,4, got {text!r}") from None
    if not cores:
        raise ValueError(f"--cores {text!r} selects no core")
    return sorted(cores)


def pin_cores(cores: list[int], workers: int) -> list[int] | None:
    """Pin this process, and so the workers it spawns, to `cores`. Returns what was applied."""
    if not hasattr(os, "sched_setaffinity"):
        log.warning("core pinning is not supported on %s; ignoring --cores", sys.platform)
        return None
    if len(cores) < workers + 2:
        log.warning(
            "pinned to %d cores for %d workers; use at least workers + 2 so 2 cores stay free for kernel networking",
            len(cores), workers,
        )
    os.sched_setaffinity(0, cores)
    return cores
