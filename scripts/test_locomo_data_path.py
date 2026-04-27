"""Tests for stage-level LoCoMo data_path resolution.

Run:
    pytest scripts/test_locomo_data_path.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.stages import _common as cm  # noqa: E402
from scripts.stages.ingest import _ingest_locomo  # noqa: E402
from scripts.stages.retrieve import _run_locomo_cell  # noqa: E402


def test_p5_yaml_declares_data_path_and_length():
    p5 = yaml.safe_load((REPO_ROOT / "configs" / "problems" / "p5.yaml").read_text())
    bench = p5["benchmark"]
    assert bench["name"] == "locomo"
    assert "data_path" in bench, "p5.yaml must declare benchmark.data_path"
    assert "length" in bench, "p5.yaml must declare benchmark.length"


def test_resolve_data_path_uses_default_when_missing():
    resolved = cm.resolve_data_path({}, "evaluation/data/locomo10.json")
    assert resolved == (REPO_ROOT / "evaluation" / "data" / "locomo10.json").resolve()


def test_resolve_data_path_resolves_relative_against_repo_root():
    resolved = cm.resolve_data_path(
        {"data_path": "evaluation/data/locomo10.json"},
        "fallback/should/not/be/used",
    )
    assert resolved == (REPO_ROOT / "evaluation" / "data" / "locomo10.json").resolve()


def test_resolve_data_path_raises_with_searched_path(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        cm.resolve_data_path(
            {"data_path": str(tmp_path / "missing.json")},
            "evaluation/data/locomo10.json",
        )
    assert "missing.json" in str(excinfo.value)


def _stub_subprocess(monkeypatch):
    captured: dict[str, list[str]] = {}

    class _Completed:
        returncode = 0

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return _Completed()

    monkeypatch.setattr("scripts.stages.ingest.subprocess.run", _fake_run)
    return captured


def test_ingest_locomo_passes_resolved_data_path_and_length(monkeypatch):
    captured = _stub_subprocess(monkeypatch)
    run_cfg = {
        "benchmark": {
            "name": "locomo",
            "data_path": "evaluation/data/locomo10.json",
            "length": 3,
        }
    }
    info = _ingest_locomo(run_cfg, "/tmp/conf.yml", "session-x")

    cmd = captured["cmd"]
    assert "--data-path" in cmd
    dp_idx = cmd.index("--data-path") + 1
    assert Path(cmd[dp_idx]).is_absolute()
    assert cmd[dp_idx].endswith("locomo10.json")
    assert "--length" in cmd
    assert cmd[cmd.index("--length") + 1] == "3"
    assert info["length"] == 3


def test_ingest_locomo_falls_back_to_default_data_path(monkeypatch):
    captured = _stub_subprocess(monkeypatch)
    info = _ingest_locomo({"benchmark": {"name": "locomo"}}, "/tmp/conf.yml", "x")

    cmd = captured["cmd"]
    dp = cmd[cmd.index("--data-path") + 1]
    assert dp.endswith("locomo10.json")
    assert info["length"] == 10


def test_ingest_locomo_raises_for_missing_data_file(monkeypatch, tmp_path):
    run_cfg = {
        "benchmark": {
            "name": "locomo",
            "data_path": str(tmp_path / "nope.json"),
        }
    }
    with pytest.raises(FileNotFoundError):
        _ingest_locomo(run_cfg, "/tmp/conf.yml", "x")


def _stub_retrieve_subprocess(monkeypatch, raw_payload: dict):
    """Patch subprocess.run to capture argv and write a stub raw JSON.

    `_run_locomo_cell` does `import subprocess` locally, so patch the
    cached `subprocess` module's `run` attribute (the local import
    returns the same object via sys.modules).

    The cell reads `cell_dir / "locomo_raw.json"` after the subprocess
    returns, so the fake must materialize that file.
    """
    import subprocess as _sp

    captured: dict[str, list[str]] = {}

    class _Completed:
        returncode = 0

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        idx = cmd.index("--eval-result-path") + 1
        Path(cmd[idx]).write_text(json.dumps(raw_payload), encoding="utf-8")
        return _Completed()

    monkeypatch.setattr(_sp, "run", _fake_run)
    return captured


def test_run_locomo_cell_passes_resolved_data_path_length_and_target(
    monkeypatch, tmp_path
):
    raw_payload = {
        "single_hop": [{"q": "a", "score": 1}, {"q": "b", "score": 0}],
        "temporal": [{"q": "c", "score": 1}],
        "skipped_string_field": "ignored",
    }
    captured = _stub_retrieve_subprocess(monkeypatch, raw_payload)

    run_cfg = {
        "benchmark": {
            "name": "locomo",
            "data_path": "evaluation/data/locomo10.json",
            "length": 3,
        }
    }
    cell_dir = tmp_path / "cell"
    cell_dir.mkdir()

    responses = _run_locomo_cell(
        run_cfg, "/tmp/conf.yml", "session-x", {"test_target": "memmachine"}, cell_dir
    )

    cmd = captured["cmd"]
    dp_idx = cmd.index("--data-path") + 1
    assert Path(cmd[dp_idx]).is_absolute()
    assert cmd[dp_idx].endswith("locomo10.json")
    assert cmd[cmd.index("--length") + 1] == "3"
    assert cmd[cmd.index("--test-target") + 1] == "memmachine"

    # responses should flatten the list-valued categories and skip the
    # non-list payload field.
    cats = sorted({c for c, _ in responses})
    assert cats == ["single_hop", "temporal"]
    assert len(responses) == 3


def test_run_locomo_cell_falls_back_to_default_data_path(monkeypatch, tmp_path):
    captured = _stub_retrieve_subprocess(monkeypatch, {})
    cell_dir = tmp_path / "cell"
    cell_dir.mkdir()

    _run_locomo_cell(
        {"benchmark": {"name": "locomo"}},
        "/tmp/conf.yml",
        "session-x",
        {},
        cell_dir,
    )

    cmd = captured["cmd"]
    assert cmd[cmd.index("--data-path") + 1].endswith("locomo10.json")
    assert cmd[cmd.index("--length") + 1] == "10"
    # default test_target falls back to "retrieval_agent"
    assert cmd[cmd.index("--test-target") + 1] == "retrieval_agent"
