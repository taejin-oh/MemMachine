"""Synthetic vectors for dataset-free dry runs.

Row i depends only on (seed, dim, i), never on the total row count. So an
.npy written by `write_npy` and a parquet set written by `write_parquet`
with the same seed are byte-identical after conversion. Design doc,
appendix C, is the specification.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

BLOCK = 65_536

EMB_TYPES = {
    "largelist32": pa.large_list(pa.float32()),  # laion schema
    "list32": pa.list_(pa.float32()),
    "largelist64": pa.large_list(pa.float64()),
}


def block(seed: int, dim: int, index: int) -> np.ndarray:
    """Unit vectors for block `index`: shape (BLOCK, dim), float32."""
    rng = np.random.default_rng([seed, index])
    v = rng.standard_normal((BLOCK, dim), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


def rows(seed: int, dim: int, start: int, stop: int) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (row_offset, vectors) pieces that together cover rows [start, stop)."""
    pos = start
    while pos < stop:
        index, offset = divmod(pos, BLOCK)
        piece = block(seed, dim, index)[offset : offset + (stop - pos)]
        yield pos, piece
        pos += len(piece)


def write_npy(out: Path, total_rows: int, dim: int, seed: int) -> None:
    """Write rows [0, total_rows) to `out` as a C-order float32 .npy file."""
    if total_rows < 1:
        raise ValueError(f"rows must be >= 1, got {total_rows}")
    if dim < 1:
        raise ValueError(f"dim must be >= 1, got {dim}")
    arr = np.lib.format.open_memmap(out, mode="w+", dtype="<f4", shape=(total_rows, dim))
    for pos, piece in rows(seed, dim, 0, total_rows):
        arr[pos : pos + len(piece)] = piece
    arr.flush()
    print(f"wrote {out}: {total_rows} rows x {dim} dims")


def write_parquet(
    out_dir: Path,
    *,
    files: int,
    rows_per_file: int,
    dim: int,
    seed: int,
    row_group_size: int,
    schema_variant: str,
) -> None:
    """Write rows [0, files * rows_per_file) as parquet files with the laion schema.

    File f holds rows [f * rows_per_file, (f + 1) * rows_per_file) and is built
    in memory, so keep rows_per_file modest.
    """
    if files < 1:
        raise ValueError(f"files must be >= 1, got {files}")
    if rows_per_file < 1:
        raise ValueError(f"rows_per_file must be >= 1, got {rows_per_file}")
    if dim < 1:
        raise ValueError(f"dim must be >= 1, got {dim}")
    schema = pa.schema([("id", pa.int64()), ("emb", EMB_TYPES[schema_variant])])
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in range(files):
        start, stop = f * rows_per_file, (f + 1) * rows_per_file
        vectors = np.concatenate([piece for _, piece in rows(seed, dim, start, stop)])
        ids = pa.array(np.arange(start, stop, dtype=np.int64))
        emb = list_array(vectors, schema.field("emb").type)
        table = pa.Table.from_arrays([ids, emb], schema=schema)
        path = out_dir / f"synth-{f:02d}-of-{files:02d}.parquet"
        pq.write_table(table, path, row_group_size=row_group_size)
        print(f"wrote {path}: rows {start}..{stop - 1}")


def list_array(vectors: np.ndarray, list_type: pa.DataType) -> pa.Array:
    """Pack a (n, dim) float32 matrix into one arrow array of `list_type`."""
    values = pa.array(vectors.reshape(-1)).cast(list_type.value_type)
    return pa.FixedSizeListArray.from_arrays(values, vectors.shape[1]).cast(list_type)
