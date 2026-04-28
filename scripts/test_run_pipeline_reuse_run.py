"""Tests for run_pipeline.main()'s reuse_run analyze-only protection.

p6/p12 problems set reuse_run to a sibling run name and expect only the
analyze stage to execute. Without the guard added in this fix,
`--stage all` (the default) would naively call ingest/retrieve/generate/
judge on the analyze-only run yaml, either failing or overwriting the
upstream run's outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_pipeline  # noqa: E402


def _write_run_cfg(tmp_path: Path, **extra) -> Path:
    cfg = {"run_name": "test_run", "n_runs": 1}
    cfg.update(extra)
    p = tmp_path / "run.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def _patch_stages():
    """Patch all 5 stage modules' run() functions and return the mocks."""
    return mock.patch.multiple(
        "scripts.stages.ingest", run=mock.DEFAULT
    ), mock.patch.multiple(
        "scripts.stages.retrieve", run=mock.DEFAULT
    ), mock.patch.multiple(
        "scripts.stages.generate", run=mock.DEFAULT
    ), mock.patch.multiple(
        "scripts.stages.judge", run=mock.DEFAULT
    ), mock.patch.multiple(
        "scripts.stages.analyze", run=mock.DEFAULT
    )


def test_reuse_run_default_stage_runs_only_analyze(tmp_path, capsys, monkeypatch):
    cfg_path = _write_run_cfg(tmp_path, reuse_run="p4_demo")
    monkeypatch.setattr(sys, "argv", ["run_pipeline", "--config", str(cfg_path)])

    with mock.patch("scripts.stages.ingest.run") as m_ingest, mock.patch(
        "scripts.stages.retrieve.run"
    ) as m_retrieve, mock.patch(
        "scripts.stages.generate.run"
    ) as m_generate, mock.patch(
        "scripts.stages.judge.run"
    ) as m_judge, mock.patch(
        "scripts.stages.analyze.run"
    ) as m_analyze:
        rc = run_pipeline.main()

    assert rc == 0
    m_ingest.assert_not_called()
    m_retrieve.assert_not_called()
    m_generate.assert_not_called()
    m_judge.assert_not_called()
    m_analyze.assert_called_once()

    captured = capsys.readouterr()
    assert "reuse_run='p4_demo'" in captured.err
    assert "['analyze']" in captured.out


def test_reuse_run_explicit_analyze_is_allowed(tmp_path, monkeypatch):
    cfg_path = _write_run_cfg(tmp_path, reuse_run="p4_demo")
    monkeypatch.setattr(
        sys, "argv", ["run_pipeline", "--config", str(cfg_path), "--stage", "analyze"]
    )

    with mock.patch("scripts.stages.ingest.run") as m_ingest, mock.patch(
        "scripts.stages.retrieve.run"
    ) as m_retrieve, mock.patch(
        "scripts.stages.generate.run"
    ) as m_generate, mock.patch(
        "scripts.stages.judge.run"
    ) as m_judge, mock.patch(
        "scripts.stages.analyze.run"
    ) as m_analyze:
        rc = run_pipeline.main()

    assert rc == 0
    m_analyze.assert_called_once()
    for m in (m_ingest, m_retrieve, m_generate, m_judge):
        m.assert_not_called()


@pytest.mark.parametrize(
    "stage_arg",
    ["ingest", "retrieve", "generate", "judge", "all", "ingest,retrieve", "judge,analyze"],
)
def test_reuse_run_with_non_analyze_stage_raises(tmp_path, monkeypatch, stage_arg):
    cfg_path = _write_run_cfg(tmp_path, reuse_run="p4_demo")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_pipeline", "--config", str(cfg_path), "--stage", stage_arg],
    )

    with pytest.raises(SystemExit) as excinfo:
        run_pipeline.main()

    msg = str(excinfo.value)
    assert "reuse_run='p4_demo'" in msg
    assert "analyze-only" in msg


def test_no_reuse_run_default_runs_all_stages(tmp_path, monkeypatch):
    cfg_path = _write_run_cfg(tmp_path)  # no reuse_run
    monkeypatch.setattr(sys, "argv", ["run_pipeline", "--config", str(cfg_path)])

    with mock.patch("scripts.stages.ingest.run") as m_ingest, mock.patch(
        "scripts.stages.retrieve.run"
    ) as m_retrieve, mock.patch(
        "scripts.stages.generate.run"
    ) as m_generate, mock.patch(
        "scripts.stages.judge.run"
    ) as m_judge, mock.patch(
        "scripts.stages.analyze.run"
    ) as m_analyze:
        rc = run_pipeline.main()

    assert rc == 0
    for m in (m_ingest, m_retrieve, m_generate, m_judge, m_analyze):
        m.assert_called_once()


def test_reuse_run_empty_string_treated_as_no_reuse(tmp_path, monkeypatch):
    """An explicit empty/null reuse_run must not trigger the guard."""
    cfg_path = _write_run_cfg(tmp_path, reuse_run="")
    monkeypatch.setattr(sys, "argv", ["run_pipeline", "--config", str(cfg_path)])

    with mock.patch("scripts.stages.ingest.run") as m_ingest, mock.patch(
        "scripts.stages.retrieve.run"
    ), mock.patch("scripts.stages.generate.run"), mock.patch(
        "scripts.stages.judge.run"
    ), mock.patch("scripts.stages.analyze.run") as m_analyze:
        rc = run_pipeline.main()

    assert rc == 0
    m_ingest.assert_called_once()
    m_analyze.assert_called_once()
