"""Map float32 vectors back to row numbers of an .npy file.

Rows of a window are indexed by xxh64 of their raw bytes, so a vector the
server returned can be matched byte-exactly without scanning the file.
Shared by the check scripts.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable

import numpy as np
import xxhash

from mock_inference.vecstream import open_vectors, parse_range  # noqa: F401 (used by the check scripts)

_BLOCK_ROWS = 16_384

DEFAULT_WINDOW = 1_000_000


def resolve_window(rows_arg: str | None, vectors: np.ndarray) -> tuple[int, int]:
    """(start, end) from --rows, or the first DEFAULT_WINDOW rows when omitted."""
    if rows_arg:
        return parse_range(rows_arg, len(vectors))
    return 0, min(DEFAULT_WINDOW, len(vectors))


def build_index(vectors: np.ndarray, start: int, end: int) -> dict[int, int]:
    """xxh64(row bytes) -> row number for rows [start, end)."""
    index: dict[int, int] = {}
    for pos in range(start, end, _BLOCK_ROWS):
        block = np.ascontiguousarray(vectors[pos : min(pos + _BLOCK_ROWS, end)])
        for j in range(len(block)):
            index[xxhash.xxh64_intdigest(block[j].tobytes())] = pos + j
    return index


def find_rows(index: dict[int, int], vectors: Iterable[np.ndarray]) -> list[int | None]:
    """Row number of each float32 vector; None when it is not in the window."""
    rows: list[int | None] = []
    for v in vectors:
        raw = np.ascontiguousarray(v, dtype="<f4").tobytes()
        rows.append(index.get(xxhash.xxh64_intdigest(raw)))
    return rows


def build_norm_index(vectors: np.ndarray, start: int, end: int) -> np.ndarray:
    """L2-normalized float32 rows [start, end), computed blockwise.

    Qdrant normalizes vectors on upsert into a Cosine collection, so a point
    read back is compared by cosine similarity, not by byte equality.
    """
    window = np.empty((end - start, vectors.shape[1]), dtype=np.float32)
    for pos in range(start, end, _BLOCK_ROWS):
        block = np.asarray(vectors[pos : min(pos + _BLOCK_ROWS, end)], dtype=np.float32)
        window[pos - start : pos - start + len(block)] = block / np.linalg.norm(block, axis=1, keepdims=True)
    return window


def find_row_cosine(window_norm: np.ndarray, start: int, v: np.ndarray) -> tuple[int, float]:
    """Best-matching row (absolute row number) in a normalized window, and its 1 - cosine similarity."""
    sims = window_norm @ (v / np.linalg.norm(v))
    row = int(np.argmax(sims))
    return start + row, 1.0 - float(sims[row])


def decode_base64(text: str) -> np.ndarray:
    """Base64 of float32 little-endian bytes -> 1-D float32 array."""
    return np.frombuffer(base64.b64decode(text), dtype="<f4")
