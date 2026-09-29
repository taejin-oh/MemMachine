"""Vector file access and row-number distribution (design doc §6 and §8).

This module does not depend on the server, so other tools can import it.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import xxhash


def open_vectors(path: Path) -> np.memmap:
    """Memory-map a C-order float32 (N, dim) .npy file."""
    arr = np.load(path, mmap_mode="r")
    if arr.ndim != 2 or arr.dtype != np.float32 or not arr.flags.c_contiguous:
        raise ValueError(f"{path}: expected a C-order float32 (N, dim) array, got {arr.dtype} {arr.shape}")
    return arr


def print_info(path: Path) -> int:
    """Print the .npy header and check the file size against it. Returns the exit code."""
    arr = np.load(path, mmap_mode="r")
    if arr.ndim != 2:
        print(f"{path}: expected a 2-D array, got shape {arr.shape}")
        return 1
    rows, dim = arr.shape
    data_bytes = rows * dim * arr.dtype.itemsize
    expected = arr.offset + data_bytes
    actual = path.stat().st_size
    dtype_ok = arr.dtype.str == "<f4"
    size_ok = actual == expected
    print(f"rows:        {rows}")
    print(f"dim:         {dim}")
    print(f"dtype:       {arr.dtype.str}" + ("" if dtype_ok else "  (expected <f4)"))
    print(f"data offset: {arr.offset}")
    print(f"data bytes:  {data_bytes}")
    print(f"file size:   {actual}" + ("  (matches)" if size_ok else f"  (MISMATCH: expected {expected})"))
    return 0 if dtype_ok and size_ok else 1


def parse_range(text: str | None, total: int) -> tuple[int, int]:
    """"START:END" -> (start, end) with 0 <= start < end <= total. Empty means the whole file."""
    if not text:
        return 0, total
    try:
        start, end = (int(part) for part in text.split(":"))
    except ValueError:
        raise ValueError(f"range must be START:END, got {text!r}") from None
    if not 0 <= start < end <= total:
        raise ValueError(f"range {text} is outside 0 <= START < END <= {total}")
    return start, end


def state_paths(vectors: Path, state_dir: Path | None) -> tuple[Path, Path]:
    """(state.json, state.lock) for `vectors`, next to it unless `state_dir` is given."""
    directory = state_dir or vectors.parent
    return directory / f"{vectors.stem}.state.json", directory / f"{vectors.stem}.state.lock"


def reset_state(vectors: Path, state_dir: Path | None, start: int, end: int) -> None:
    """Start the stream over from `start`, discarding any previous position."""
    state_file, lock_file = state_paths(vectors, state_dir)
    with _locked(lock_file):
        _write_state(state_file, _fresh_state(start, end))


def ensure_state(vectors: Path, state_dir: Path | None, start: int, end: int) -> None:
    """Create the state file on first start; refuse one left over from another range.

    `serve` calls this in the parent before starting workers, so a stale file
    fails the command instead of crashing every worker uvicorn respawns.
    """
    state_file, lock_file = state_paths(vectors, state_dir)
    with _locked(lock_file):
        if not state_file.exists():
            _write_state(state_file, _fresh_state(start, end))
            return
        state = _read_state(state_file)
    if (state["start"], state["end"]) != (start, end):
        raise RuntimeError(
            f"{state_file} covers rows {state['start']}:{state['end']}, "
            f"not {start}:{end}; start with --reset to replace it"
        )
    if not start <= state["next"] < end:
        raise RuntimeError(
            f"{state_file} is missing or corrupt; stop the server, then delete it (same as reset) or restore it"
        )


def _fresh_state(start: int, end: int) -> dict:
    return {"next": start, "wraps": 0, "start": start, "end": end}


@contextmanager
def _locked(lock_file: Path) -> Iterator[None]:
    """Hold an exclusive flock on `lock_file` (created if missing) for the block."""
    with open(lock_file, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _read_state(state_file: Path) -> dict:
    try:
        state = json.loads(state_file.read_bytes())
        state["start"], state["end"], state["next"], state["wraps"]  # validate shape
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RuntimeError(
            f"{state_file} is missing or corrupt; stop the server, then delete it (same as reset) or restore it"
        ) from e
    return state


def _write_state(state_file: Path, state: dict) -> None:
    """Write via a temporary file and rename, so readers never see a partial file."""
    tmp = state_file.with_name(f"{state_file.name}.tmp.{os.getpid()}")
    with open(tmp, "w") as f:
        f.write(json.dumps(state))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state_file)


class Stream:
    """Sequential mode: rows in file order, leased `chunk` at a time across worker processes.

    One instance per worker process. `take` touches the shared state only when
    it needs a new chunk, so workers lock once per `chunk` rows (design §8.2).
    """

    def __init__(self, vectors: Path, start: int, end: int, chunk: int, state_dir: Path | None) -> None:
        if chunk < 1:
            raise ValueError(f"chunk must be >= 1, got {chunk}")
        self.vecs = open_vectors(vectors)
        self.start, self.end, self.chunk = start, end, chunk
        self.state_file, self.lock_file = state_paths(vectors, state_dir)
        self.cur = self.lim = 0  # leased rows [cur, lim); empty until the first take
        ensure_state(vectors, state_dir, start, end)
        self._lock_fd = open(self.lock_file, "a")  # held for the process lifetime, see _lease

    def take(self, keys: Sequence[str]) -> np.ndarray:
        """The next len(keys) rows as a fresh (n, dim) float32 array. Keys are ignored."""
        n = len(keys)
        parts = []
        while n > 0:
            if self.cur == self.lim:
                self.cur, self.lim = self._lease()
            k = min(n, self.lim - self.cur)
            parts.append(self.vecs[self.cur : self.cur + k])
            self.cur += k
            n -= k
        if not parts:
            return np.empty((0, self.vecs.shape[1]), dtype=np.float32)
        return np.concatenate(parts)

    def health(self) -> dict:
        """The shared position {"next", "wraps", "start", "end"}, read without the lock."""
        return _read_state(self.state_file)

    def _lease(self) -> tuple[int, int]:
        """Reserve the next chunk under the inter-process lock; wrap to `start` at `end`.

        Locks the fd opened once in __init__ rather than reopening `lock_file` by
        path, so a lock file deleted out from under a running worker (e.g. by an
        operator cleaning up) does not break mutual exclusion (design §8.2).
        """
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        try:
            state = _read_state(self.state_file)
            a = state["next"]
            b = min(a + self.chunk, state["end"])
            if b == state["end"]:
                state["next"] = state["start"]
                state["wraps"] += 1
            else:
                state["next"] = b
            _write_state(self.state_file, state)
        finally:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        return a, b


class HashStream:
    """Hash mode: row = start + xxh64(key) mod (end - start). Same key, same vector; no state file."""

    def __init__(self, vectors: Path, start: int, end: int) -> None:
        self.vecs = open_vectors(vectors)
        self.start, self.end = start, end

    def take(self, keys: Sequence[str]) -> np.ndarray:
        span = self.end - self.start
        rows = [self.start + xxhash.xxh64_intdigest(key.encode()) % span for key in keys]
        return self.vecs[rows]

    def health(self) -> dict:
        return {"start": self.start, "end": self.end}
