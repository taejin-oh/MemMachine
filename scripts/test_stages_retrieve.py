"""Tests for scripts/stages/retrieve.py LongMemEval answer-prompt policy
resolution + log-line emission (v0.6).

Run:
    pytest scripts/test_stages_retrieve.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
for extra in (
    REPO_ROOT / "packages" / "common" / "src",
    REPO_ROOT / "packages" / "server" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from scripts.stages import retrieve as retrieve_stage  # noqa: E402


def _write_minimal_cfg(path: Path, *, policy: str | None = None) -> None:
    """Materialize a Pydantic-valid configuration.yml for fallback tests."""
    sample = (
        REPO_ROOT / "sample_configs" / "episodic_memory_config.cpu.sample"
    ).read_text()
    base = yaml.safe_load(sample)
    if policy is not None:
        base.setdefault("retrieval_agent", {})["longmemeval_answer_prompt"] = policy
    path.write_text(yaml.safe_dump(base))


# ---------------------------------------------------------------------------
# _resolve_answer_prompt_policy: precedence + validation
# ---------------------------------------------------------------------------


def test_resolve_answer_prompt_policy_run_cfg_wins(tmp_path):
    """run_cfg.evaluation.longmemeval.answer_prompt overrides configuration.yml."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="memmachine_original")  # explicit non-default
    policy = retrieve_stage._resolve_answer_prompt_policy(
        {"evaluation": {"longmemeval": {"answer_prompt": "agent_lightning"}}},
        str(cfg_path),
    )
    assert policy == "agent_lightning"


def test_resolve_answer_prompt_policy_falls_back_to_config(tmp_path):
    """run_cfg unset → read retrieval_agent.longmemeval_answer_prompt from yaml."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="agent_lightning")
    policy = retrieve_stage._resolve_answer_prompt_policy({}, str(cfg_path))
    assert policy == "agent_lightning"


def test_resolve_answer_prompt_policy_default_when_unset(tmp_path):
    """Both unset → Pydantic default 'LME_origin_prompt' (upstream verbatim)."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path)
    policy = retrieve_stage._resolve_answer_prompt_policy({}, str(cfg_path))
    assert policy == "LME_origin_prompt"


def test_resolve_answer_prompt_policy_invalid_run_cfg_raises(tmp_path):
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path)
    with pytest.raises(ValueError, match=r"longmemeval_answer_prompt must be one of"):
        retrieve_stage._resolve_answer_prompt_policy(
            {"evaluation": {"longmemeval": {"answer_prompt": "typo"}}},
            str(cfg_path),
        )


# ---------------------------------------------------------------------------
# run() header log emits the policy for longmemeval benchmark
# ---------------------------------------------------------------------------


def test_run_header_logs_answer_prompt_policy_for_longmemeval(
    monkeypatch, tmp_path, capsys
):
    """`[retrieve] ... longmemeval_answer_prompt=...` must appear in stdout."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="agent_lightning")

    out_dir = tmp_path / "results" / "test_run"
    out_dir.mkdir(parents=True)

    monkeypatch.setattr(retrieve_stage.cm, "results_dir_for", lambda _cfg: out_dir)
    monkeypatch.setattr(
        retrieve_stage.cm, "resolve_config_path", lambda _cfg: str(cfg_path)
    )
    monkeypatch.setattr(retrieve_stage.cm, "session_id_for", lambda _cfg: "sid")
    monkeypatch.setattr(
        retrieve_stage.cm, "write_jsonl", lambda _path, _rows: None
    )

    # Short-circuit the actual cell loop — we only care about the header log.
    async def fake_lme_cell(*_a, **_kw):
        return []

    monkeypatch.setattr(retrieve_stage, "_run_longmemeval_cell", fake_lme_cell)

    retrieve_stage.run(
        {
            "run_name": "test_run",
            "configuration": {"generated_path": str(cfg_path)},
            "benchmark": {"name": "longmemeval", "length": 1, "split": "x"},
        }
    )
    out = capsys.readouterr().out
    assert "longmemeval_answer_prompt=agent_lightning" in out


def test_run_header_omits_answer_prompt_log_for_non_longmemeval(
    monkeypatch, tmp_path, capsys
):
    """Non-LongMemEval benchmarks do not trigger the policy log."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path)

    out_dir = tmp_path / "results" / "test_run"
    out_dir.mkdir(parents=True)

    monkeypatch.setattr(retrieve_stage.cm, "results_dir_for", lambda _cfg: out_dir)
    monkeypatch.setattr(
        retrieve_stage.cm, "resolve_config_path", lambda _cfg: str(cfg_path)
    )
    monkeypatch.setattr(retrieve_stage.cm, "session_id_for", lambda _cfg: "sid")
    monkeypatch.setattr(
        retrieve_stage.cm, "write_jsonl", lambda _path, _rows: None
    )

    async def fake_hotpot_cell(*_a, **_kw):
        return []

    monkeypatch.setattr(retrieve_stage, "_run_hotpot_cell", fake_hotpot_cell)

    retrieve_stage.run(
        {
            "run_name": "test_run",
            "configuration": {"generated_path": str(cfg_path)},
            "benchmark": {"name": "hotpot", "length": 1, "split": "x"},
        }
    )
    out = capsys.readouterr().out
    assert "longmemeval_answer_prompt=" not in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
