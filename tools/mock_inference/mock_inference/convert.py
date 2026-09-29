"""Convert parquet vector files into one C-order float32 .npy file.

Design doc section 7: plan, preallocate, fill file-by-file in parallel,
verify a random sample. `<out>.plan.json` records the plan and
`<out>.done/<file>.ok` marks finished files so a rerun with the same plan
skips them.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import multiprocessing
import time
from functools import partial
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

log = logging.getLogger("mock_inference.convert")

BATCH_ROWS = 16_384  # ~300MB/job at 768 dims float32, not 1.2GB (see --jobs $(nproc) note)
SAMPLE_ROWS = 100
VALUE_DTYPES = {pa.float32(): "float32", pa.float64(): "float64"}


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.verify_only and not args.parquet_glob:
        raise SystemExit("--parquet-glob is required unless --verify-only")
    out: Path = args.out
    plan_path = out.with_name(out.name + ".plan.json")
    done_dir = out.with_name(out.name + ".done")

    if args.verify_only:
        if not plan_path.exists():
            raise SystemExit(f"{plan_path} not found; run convert without --verify-only first")
        return verify(json.loads(plan_path.read_text()), out)

    started = time.perf_counter()
    plan = make_plan(args.parquet_glob, args.vector_column, args.rows)
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        # Resume skips files by name, so a plan with different offsets would leave wrong rows behind.
        raise SystemExit(
            f"{plan_path} differs from the new plan (files, rows or column changed); "
            f"delete {out}, {done_dir} and {plan_path} to start over"
        )
    plan_path.write_text(json.dumps(plan, indent=1))
    log.info(
        "plan: %d files, %d rows x %d dims, column %r (%s)",
        len(plan["files"]), plan["rows"], plan["dim"], plan["vector_column"], plan["source_dtype"],
    )

    allocate(out, done_dir, plan["rows"], plan["dim"])
    done_dir.mkdir(exist_ok=True)
    written = fill(out, done_dir, plan, args.jobs)

    elapsed = time.perf_counter() - started
    mb = written * plan["dim"] * 4 / 1e6
    log.info(
        "done: %d rows x %d dims, wrote %d rows in %.1fs (%.0f MB/s)",
        plan["rows"], plan["dim"], written, elapsed, mb / elapsed,
    )
    return verify(plan, out)


# --- step 1: plan ---------------------------------------------------------


def make_plan(pattern: str, vector_column: str | None, max_rows: int | None) -> dict:
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no files match {pattern}")

    first = pq.ParquetFile(paths[0])
    column = vector_column or detect_vector_column(first.schema_arrow)
    if column not in first.schema_arrow.names:
        raise SystemExit(f"column {column!r} not in {first.schema_arrow.names}")
    column_type = first.schema_arrow.field(column).type
    source_dtype = value_dtype(column_type)
    if source_dtype is None:
        raise SystemExit(f"column {column!r} is not list<float32|float64>: {column_type}")
    dim = len(next(first.iter_batches(batch_size=1, columns=[column])).column(0)[0].values)

    files = []
    offset = 0
    for path in paths:
        rows = pq.ParquetFile(path).metadata.num_rows
        if max_rows is not None:
            rows = min(rows, max_rows - offset)
        if rows <= 0:
            break
        files.append({"path": path, "rows": rows, "offset": offset})
        offset += rows
    return {
        "dim": dim,
        "rows": offset,
        "vector_column": column,
        "source_dtype": source_dtype,
        "files": files,
    }


def detect_vector_column(schema: pa.Schema) -> str:
    """First column typed list<float32|float64> or large_list<float32|float64>."""
    for field in schema:
        if value_dtype(field.type) is not None:
            return field.name
    raise SystemExit(f"no list<float> column in {schema.names}; use --vector-column")


def value_dtype(t: pa.DataType) -> str | None:
    """numpy dtype name of a float list column's items, None for any other type."""
    if pa.types.is_list(t) or pa.types.is_large_list(t) or pa.types.is_fixed_size_list(t):
        return VALUE_DTYPES.get(t.value_type)
    return None


# --- step 2: preallocate ----------------------------------------------------


def allocate(out: Path, done_dir: Path, rows: int, dim: int) -> None:
    """Create the sparse output file, or keep an existing one of the right shape (resume)."""
    if out.exists():
        shape = np.load(out, mmap_mode="r").shape
        if shape != (rows, dim):
            raise SystemExit(
                f"{out} has shape {shape}, plan needs {(rows, dim)}; "
                f"delete it and {done_dir} to start over"
            )
        return
    np.lib.format.open_memmap(out, mode="w+", dtype="<f4", shape=(rows, dim)).flush()


# --- step 3: fill in parallel -----------------------------------------------


def fill(out: Path, done_dir: Path, plan: dict, jobs: int) -> int:
    """Copy every planned file into `out`; return the number of rows written (skips excluded)."""
    job = partial(fill_file, out, done_dir, plan["vector_column"], plan["dim"])
    written = 0
    with multiprocessing.Pool(min(jobs, len(plan["files"]))) as pool:
        for name, rows in pool.imap_unordered(job, plan["files"]):
            if rows is None:
                log.info("skip %s", name)
            else:
                log.info("write %s rows=%d", name, rows)
                written += rows
    return written


def fill_file(
    out: Path, done_dir: Path, column: str, dim: int, entry: dict
) -> tuple[str, int | None]:
    """Pool worker: write one parquet file into its row range.

    Returns (name, rows written), or (name, None) when the file was already done.
    """
    path = Path(entry["path"])
    marker = done_dir / (path.name + ".ok")
    if marker.exists():
        return path.name, None

    target = np.load(out, mmap_mode="r+")
    pos, end = entry["offset"], entry["offset"] + entry["rows"]
    for batch in pq.ParquetFile(path).iter_batches(batch_size=BATCH_ROWS, columns=[column]):
        vectors = flatten(batch.column(0), dim, pos)[: end - pos]
        target[pos : pos + len(vectors)] = vectors
        pos += len(vectors)
        if pos == end:
            break
    if pos != end:
        read = pos - entry["offset"]
        raise ValueError(f"{path.name}: read {read} rows, metadata promised {entry['rows']}")

    target.flush()
    marker.touch()
    return path.name, entry["rows"]


def flatten(column: pa.Array, dim: int, first_row: int) -> np.ndarray:
    """List array -> (n, dim) float32 matrix. Fails if any list is not exactly `dim` long."""
    lengths = pc.list_value_length(column).to_numpy(zero_copy_only=False)
    bad = np.flatnonzero(lengths != dim)
    if bad.size:
        raise ValueError(f"row {first_row + bad[0]}: list length {lengths[bad[0]]} != dim {dim}")
    flat = pc.list_flatten(column).to_numpy()
    return flat.astype("<f4", copy=False).reshape(-1, dim)


# --- step 4: verify ---------------------------------------------------------


def verify(plan: dict, out: Path) -> int:
    """Byte-compare a random sample of rows against the parquet source; print norm stats."""
    target = np.load(out, mmap_mode="r")
    if target.shape != (plan["rows"], plan["dim"]):
        raise SystemExit(f"{out} has shape {target.shape}, plan says {(plan['rows'], plan['dim'])}")

    seed = 12345  # fixed so a FAIL line's row number is reproducible
    count = min(SAMPLE_ROWS, plan["rows"])
    sample = np.sort(np.random.default_rng(seed).choice(plan["rows"], size=count, replace=False))
    norms = []
    for row in sample:
        expected = read_row(plan, int(row))
        if expected.tobytes() != target[row].tobytes():
            print(f"verify FAIL row {row} (seed {seed}): parquet {expected[:4]}... != npy {target[row][:4]}...")
            return 1
        norms.append(float(np.linalg.norm(target[row])))
    print(
        f"verify PASS {count}/{count} rows (seed {seed}), "
        f"norm min {min(norms):.6f} max {max(norms):.6f} mean {sum(norms) / len(norms):.6f}"
    )
    return 0


def read_row(plan: dict, row: int) -> np.ndarray:
    """Read one vector back from the parquet row group that holds global row `row`."""
    entry = next(f for f in plan["files"] if f["offset"] <= row < f["offset"] + f["rows"])
    local = row - entry["offset"]
    reader = pq.ParquetFile(entry["path"])
    for group in range(reader.metadata.num_row_groups):
        size = reader.metadata.row_group(group).num_rows
        if local < size:
            column = reader.read_row_group(group, columns=[plan["vector_column"]]).column(0)
            return column[local].values.to_numpy().astype("<f4", copy=False)
        local -= size
    raise ValueError(f"{entry['path']}: row {row} is past the last row group")
