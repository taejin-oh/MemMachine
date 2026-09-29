"""serve: a stale state file is refused in the parent, before any worker starts."""

from __future__ import annotations

import argparse
import contextlib
import io
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mock_inference import serve, synth, vecstream


class ServeTest(unittest.TestCase):
    def test_chunk_below_one_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            serve.run(argparse.Namespace(chunk=0))

    def test_refuses_when_port_is_bound(self) -> None:
        # Probe-bind must run before state is touched, so `serve --reset` cannot
        # rewind a live server already on that port (ops#2).
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            port = held.getsockname()[1]
            with tempfile.TemporaryDirectory() as d:
                vectors = Path(d) / "small.npy"
                with contextlib.redirect_stdout(io.StringIO()):
                    synth.write_npy(vectors, 1000, 8, 42)
                proc = subprocess.run(
                    [
                        sys.executable, "-m", "mock_inference", "serve",
                        "--vectors", str(vectors), "--host", "127.0.0.1", "--port", str(port),
                    ],
                    capture_output=True, text=True, timeout=30,
                )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("port already in use", proc.stderr)

    def test_reset_subcommand_resets_next(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vectors = Path(d) / "small.npy"
            with contextlib.redirect_stdout(io.StringIO()):
                synth.write_npy(vectors, 1000, 8, 42)
            vecstream.Stream(vectors, 0, 1000, 50, None).take(["k"] * 120)
            proc = subprocess.run(
                [sys.executable, "-m", "mock_inference", "reset", "--vectors", str(vectors)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(vecstream.Stream(vectors, 0, 1000, 50, None).health()["next"], 0)

    def test_foreign_state_is_refused_with_two_workers(self) -> None:
        # With one worker the crash is visible; with two, uvicorn would respawn
        # crashing workers forever, so the parent has to refuse before uvicorn.run.
        with tempfile.TemporaryDirectory() as d:
            vectors = Path(d) / "small.npy"
            with contextlib.redirect_stdout(io.StringIO()):
                synth.write_npy(vectors, 1000, 8, 42)
            vecstream.reset_state(vectors, None, 0, 500)
            proc = subprocess.run(
                [sys.executable, "-m", "mock_inference", "serve", "--vectors", str(vectors), "--workers", "2", "--port", "0"],
                capture_output=True, text=True, timeout=30,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("covers rows 0:500, not 0:1000; start with --reset", proc.stderr)
        self.assertNotIn("Started server process", proc.stderr, "a worker was started")


if __name__ == "__main__":
    unittest.main()
