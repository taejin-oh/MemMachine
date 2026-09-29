"""convert: parquet -> .npy across vector-column schemas, plus the --verify-only CLI guard."""

from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mock_inference import convert, synth

FILES, ROWS_PER_FILE, DIM, SEED = 2, 50, 8, 7


def run_convert(parquet_glob: str | None, out: Path, **overrides) -> int:
    kwargs = dict(
        parquet_glob=parquet_glob,
        out=out,
        jobs=2,
        rows=None,
        vector_column=None,
        verify_only=False,
    )
    kwargs.update(overrides)
    args = argparse.Namespace(**kwargs)
    with contextlib.redirect_stdout(io.StringIO()):
        return convert.run(args)


class ConvertSchemaVariantsTest(unittest.TestCase):
    """Round-trip each parquet vector-column type through convert; compare against synth.write_npy."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def expected_npy(self) -> np.ndarray:
        expected = self.dir / "expected.npy"
        with contextlib.redirect_stdout(io.StringIO()):
            synth.write_npy(expected, FILES * ROWS_PER_FILE, DIM, SEED)
        return np.load(expected)

    def convert_variant(self, schema_variant: str) -> np.ndarray:
        parquet_dir = self.dir / schema_variant
        with contextlib.redirect_stdout(io.StringIO()):
            synth.write_parquet(
                parquet_dir,
                files=FILES,
                rows_per_file=ROWS_PER_FILE,
                dim=DIM,
                seed=SEED,
                row_group_size=17,
                schema_variant=schema_variant,
            )
        out = self.dir / f"{schema_variant}.npy"
        self.assertEqual(run_convert(str(parquet_dir / "*.parquet"), out), 0)
        return np.load(out)

    def test_largelist32(self) -> None:
        np.testing.assert_array_equal(self.convert_variant("largelist32"), self.expected_npy())

    def test_list32(self) -> None:
        np.testing.assert_array_equal(self.convert_variant("list32"), self.expected_npy())

    def test_largelist64(self) -> None:
        np.testing.assert_array_equal(self.convert_variant("largelist64"), self.expected_npy())

    def test_fixed_size_list(self) -> None:
        # synth.write_parquet only emits the Zilliz/laion (large_)list schemas, so build a
        # fixed_size_list<float32> parquet by hand to cover value_dtype's other branch.
        parquet_dir = self.dir / "fixedsize"
        parquet_dir.mkdir()
        schema = pa.schema([("id", pa.int64()), ("emb", pa.list_(pa.float32(), DIM))])
        for f in range(FILES):
            start, stop = f * ROWS_PER_FILE, (f + 1) * ROWS_PER_FILE
            vectors = np.concatenate([piece for _, piece in synth.rows(SEED, DIM, start, stop)])
            ids = pa.array(np.arange(start, stop, dtype=np.int64))
            values = pa.array(vectors.reshape(-1)).cast(pa.float32())
            emb = pa.FixedSizeListArray.from_arrays(values, DIM)
            table = pa.Table.from_arrays([ids, emb], schema=schema)
            pq.write_table(table, parquet_dir / f"synth-{f:02d}.parquet", row_group_size=17)

        out = self.dir / "fixedsize.npy"
        self.assertEqual(run_convert(str(parquet_dir / "*.parquet"), out), 0)
        np.testing.assert_array_equal(np.load(out), self.expected_npy())


class ConvertVerifyOnlyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.parquet_dir = self.dir / "src"
        with contextlib.redirect_stdout(io.StringIO()):
            synth.write_parquet(
                self.parquet_dir, files=1, rows_per_file=ROWS_PER_FILE, dim=DIM,
                seed=SEED, row_group_size=17, schema_variant="largelist32",
            )
        self.out = self.dir / "out.npy"
        self.assertEqual(run_convert(str(self.parquet_dir / "*.parquet"), self.out), 0)

    def test_verify_only_does_not_need_parquet_glob(self) -> None:
        self.assertEqual(run_convert(None, self.out, verify_only=True), 0)

    def test_missing_parquet_glob_is_a_clear_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            run_convert(None, self.dir / "other.npy")
        self.assertIn("--parquet-glob is required unless --verify-only", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
