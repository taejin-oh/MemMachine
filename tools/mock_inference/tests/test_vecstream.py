"""vecstream: info, the multi-process lease protocol, wrap, hash mode, range parsing."""

from __future__ import annotations

import contextlib
import io
import multiprocessing
import os
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from mock_inference import synth, vecstream

ROWS, DIM, CHUNK = 1000, 8, 50


def make_vectors(directory: Path) -> Path:
    path = directory / "small.npy"
    with contextlib.redirect_stdout(io.StringIO()):  # write_npy prints a summary line
        synth.write_npy(path, ROWS, DIM, 42)
    return path


def serve_rows(vectors: str, quota: int, seed: int) -> tuple[int, np.ndarray]:
    """Worker: take random-sized batches from a fresh Stream until `quota` rows are served."""
    rng = random.Random(seed)
    stream = vecstream.Stream(Path(vectors), 0, ROWS, CHUNK, None)
    parts = []
    while sum(len(part) for part in parts) < quota:
        parts.append(stream.take(["k"] * rng.randint(1, 37)))
    return os.getpid(), np.concatenate(parts)


class StreamTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.vectors = make_vectors(self.dir)
        self.row_of = {row.tobytes(): i for i, row in enumerate(np.load(self.vectors))}

    def rows_of(self, served: np.ndarray) -> list[int]:
        """Row numbers of served vectors, found by byte comparison against the file."""
        return [self.row_of[vec.tobytes()] for vec in served]

    def test_four_processes_share_the_stream_without_duplicates(self) -> None:
        # Each worker serves at least 150 rows (at most 186), so at most 4 chunks
        # of 50 each: the pool leases at most 800 of the 1000 rows and never wraps.
        with multiprocessing.get_context("spawn").Pool(4) as pool:
            served = pool.starmap(serve_rows, [(str(self.vectors), 150, seed) for seed in range(4)])
        rows = [row for _, part in served for row in self.rows_of(part)]
        state = vecstream.Stream(self.vectors, 0, ROWS, CHUNK, None).health()

        self.assertEqual(len({pid for pid, _ in served}), 4, "expected four distinct worker processes")
        self.assertGreaterEqual(len(rows), 600)
        self.assertEqual(len(rows), len(set(rows)), "a row was served twice")
        self.assertLess(max(rows), state["next"])
        self.assertLessEqual(state["next"] - len(rows), 4 * CHUNK, "too many leased-but-unserved rows")
        self.assertEqual(state["wraps"], 0)

        # A restart continues after everything that was leased before.
        again = vecstream.Stream(self.vectors, 0, ROWS, CHUNK, None).take(["k"] * 100)
        self.assertGreater(min(self.rows_of(again)), max(rows))

    def test_reaching_end_wraps_to_start(self) -> None:
        stream = vecstream.Stream(self.vectors, 0, 100, CHUNK, None)
        self.assertEqual(self.rows_of(stream.take(["k"] * 100)), list(range(100)))
        self.assertEqual(stream.health(), {"next": 0, "wraps": 1, "start": 0, "end": 100})
        self.assertEqual(self.rows_of(stream.take(["k"] * 3)), [0, 1, 2])

    def test_state_file_from_another_range_is_refused(self) -> None:
        vecstream.reset_state(self.vectors, None, 0, 500)
        with self.assertRaises(RuntimeError):
            vecstream.Stream(self.vectors, 0, ROWS, CHUNK, None)

    def test_hash_mode_is_deterministic(self) -> None:
        stream = vecstream.HashStream(self.vectors, 100, 200)
        a = stream.take(["apple", "pear", "apple"])
        b = stream.take(["apple"])
        np.testing.assert_array_equal(a[0], a[2])
        np.testing.assert_array_equal(a[0], b[0])
        self.assertTrue(all(100 <= row < 200 for row in self.rows_of(a)))
        self.assertEqual(stream.health(), {"start": 100, "end": 200})

    def test_open_vectors_rejects_wrong_shape(self) -> None:
        bad = self.dir / "bad.npy"
        np.save(bad, np.zeros(10, dtype=np.float32))
        with self.assertRaises(ValueError):
            vecstream.open_vectors(bad)

    def test_chunk_below_one_is_rejected(self) -> None:
        for chunk in (0, -3):
            with self.subTest(chunk=chunk), self.assertRaises(ValueError):
                vecstream.Stream(self.vectors, 0, ROWS, chunk, None)

    def test_empty_state_file_is_refused(self) -> None:
        state_file, _ = vecstream.state_paths(self.vectors, None)
        state_file.write_text("")
        with self.assertRaises(RuntimeError) as cm:
            vecstream.Stream(self.vectors, 0, ROWS, CHUNK, None)
        self.assertIn("is missing or corrupt", str(cm.exception))

    def test_take_continues_after_lock_file_is_deleted(self) -> None:
        # The lock fd is opened once in __init__ (code-correctness#4), so a lock
        # file deleted between two takes must not break serving or raise.
        stream = vecstream.Stream(self.vectors, 0, ROWS, CHUNK, None)
        first = self.rows_of(stream.take(["k"] * 5))
        stream.lock_file.unlink()
        second = self.rows_of(stream.take(["k"] * 5))
        self.assertEqual(min(second), max(first) + 1)


class ParseRangeTest(unittest.TestCase):
    def test_valid(self) -> None:
        self.assertEqual(vecstream.parse_range(None, 1000), (0, 1000))
        self.assertEqual(vecstream.parse_range("", 1000), (0, 1000))
        self.assertEqual(vecstream.parse_range("10:20", 1000), (10, 20))

    def test_invalid(self) -> None:
        for text in ["abc", "10", "1:2:3", "20:10", "5:5", "-1:10", "0:1001"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                vecstream.parse_range(text, 1000)


class InfoTest(unittest.TestCase):
    def test_print_info(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vectors = make_vectors(Path(d))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = vecstream.print_info(vectors)
        self.assertEqual(code, 0)
        for expected in (f"rows:        {ROWS}", f"dim:         {DIM}", "<f4", str(ROWS * DIM * 4), "matches"):
            self.assertIn(expected, out.getvalue())


if __name__ == "__main__":
    unittest.main()
