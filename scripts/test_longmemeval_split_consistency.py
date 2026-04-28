"""Tests guarding the LongMemEval split-name unification.

Before this fix, configs/problems/p3.yaml and p4.yaml used `split:
longmemeval_s` while the eval-tool default (longmemeval_test.py argparse
default) and run_benchmark_matrix.sh's LONGMEM_SPLIT both used
`longmemeval_s_cleaned`. The two paths therefore exercised different
HuggingFace datasets and silently produced divergent scores.

These tests pin the canonical split name across both yamls so a future
edit that re-introduces the divergence fails CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_LONGMEMEVAL_SPLIT = "longmemeval_s_cleaned"


@pytest.mark.parametrize("problem_yaml", ["p3.yaml", "p4.yaml"])
def test_longmemeval_problem_uses_canonical_split(problem_yaml):
    path = REPO_ROOT / "configs" / "problems" / problem_yaml
    cfg = yaml.safe_load(path.read_text())
    assert cfg["benchmark"]["name"] == "longmemeval"
    assert cfg["benchmark"]["split"] == CANONICAL_LONGMEMEVAL_SPLIT, (
        f"{problem_yaml} must use the canonical split name "
        f"{CANONICAL_LONGMEMEVAL_SPLIT!r} so the wrapper agrees with "
        "evaluation/retrieval_agent/longmemeval_test.py and "
        "evaluation/retrieval_agent/run_benchmark_matrix.sh "
        "(LONGMEM_SPLIT)."
    )


def test_run_benchmark_matrix_split_matches_canonical():
    matrix_sh = (
        REPO_ROOT / "evaluation" / "retrieval_agent" / "run_benchmark_matrix.sh"
    ).read_text()
    assert f'LONGMEM_SPLIT="{CANONICAL_LONGMEMEVAL_SPLIT}"' in matrix_sh, (
        "run_benchmark_matrix.sh must declare "
        f'LONGMEM_SPLIT="{CANONICAL_LONGMEMEVAL_SPLIT}".'
    )


def test_longmemeval_test_default_split_matches_canonical():
    src = (
        REPO_ROOT / "evaluation" / "retrieval_agent" / "longmemeval_test.py"
    ).read_text()
    assert f'default="{CANONICAL_LONGMEMEVAL_SPLIT}"' in src, (
        "longmemeval_test.py argparse default for --split must remain "
        f"{CANONICAL_LONGMEMEVAL_SPLIT!r}."
    )
