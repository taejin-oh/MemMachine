"""Unit tests for evaluation/retrieval_agent/longmemeval_test.py answer-prompt
plumbing (v0.6 alignment with xiaowu0162/LongMemEval).

Run:
    pytest evaluation/retrieval_agent/test_longmemeval_test.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
for extra in (
    REPO_ROOT / "packages" / "common" / "src",
    REPO_ROOT / "packages" / "server" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from evaluation.retrieval_agent.longmemeval_test import (  # noqa: E402
    _ANSWER_PROMPT_AGENT_LIGHTNING,
    _ANSWER_PROMPT_BY_POLICY,
    _ANSWER_PROMPT_MEMMACHINE_ORIGINAL,
    ANSWER_PROMPT,
    _format_question_date,
    _resolve_answer_prompt_policy,
    _select_answer_prompt,
)

# ---------------------------------------------------------------------------
# _format_question_date
# ---------------------------------------------------------------------------


def test_format_question_date_iso_format():
    """Upstream LongMemEval format → human-readable English form."""
    out = _format_question_date("2023/04/10 (Mon) 23:07")
    assert out == "Monday, April 10, 2023 at 11:07 PM"


def test_format_question_date_empty_returns_empty():
    """Empty / missing input keeps Current Date: line renderable but blank."""
    assert _format_question_date("") == ""
    assert _format_question_date(None) == ""


def test_format_question_date_invalid_falls_through():
    """Unparseable strings return raw — never raise inside the prompt path."""
    out = _format_question_date("not-a-date")
    assert out == "not-a-date"


# ---------------------------------------------------------------------------
# Prompt body invariants (placeholders + structure)
# ---------------------------------------------------------------------------


def test_memmachine_original_prompt_renders_with_question_date():
    """Original-aligned prompt must format with memories+question+question_date."""
    prompt = _ANSWER_PROMPT_MEMMACHINE_ORIGINAL.format(
        memories="MEM",
        question="Q",
        question_date="Monday, April 10, 2023 at 11:07 PM",
    )
    assert "MEM" in prompt
    assert "Q" in prompt
    assert "Current date: Monday, April 10, 2023 at 11:07 PM" in prompt
    # Upstream LongMemEval prompt has no length cap / open-domain fallback.
    assert "max 2 sentences" not in prompt
    assert "Open-domain fallback" not in prompt


def test_agent_lightning_prompt_renders_without_question_date():
    """Legacy prompt must keep working with only memories+question (no extras)."""
    prompt = _ANSWER_PROMPT_AGENT_LIGHTNING.format(memories="MEM", question="Q")
    assert "MEM" in prompt
    assert "Q" in prompt
    assert "Open-domain fallback" in prompt  # the very behavior v0.6 removes
    assert "{question_date}" not in prompt  # no placeholder to format


def test_public_alias_points_to_default_policy():
    """ANSWER_PROMPT export must equal the default-policy body for backward import compat."""
    assert ANSWER_PROMPT is _ANSWER_PROMPT_MEMMACHINE_ORIGINAL


def test_policy_registry_keys():
    """Policy registry must list both bodies."""
    assert set(_ANSWER_PROMPT_BY_POLICY) == {"memmachine_original", "agent_lightning"}


# ---------------------------------------------------------------------------
# _select_answer_prompt
# ---------------------------------------------------------------------------


def test_select_answer_prompt_memmachine_original():
    assert _select_answer_prompt("memmachine_original") is (
        _ANSWER_PROMPT_MEMMACHINE_ORIGINAL
    )


def test_select_answer_prompt_agent_lightning():
    assert _select_answer_prompt("agent_lightning") is _ANSWER_PROMPT_AGENT_LIGHTNING


def test_select_answer_prompt_invalid_raises():
    with pytest.raises(ValueError, match=r"Unknown longmemeval_answer_prompt policy"):
        _select_answer_prompt("typo")


# ---------------------------------------------------------------------------
# _resolve_answer_prompt_policy (CLI > config > Pydantic default)
# ---------------------------------------------------------------------------


def _write_minimal_cfg(path: Path, *, policy: str | None = None) -> None:
    """Materialize a Pydantic-valid configuration.yml for fallback tests."""
    import yaml

    sample = (
        REPO_ROOT / "sample_configs" / "episodic_memory_config.cpu.sample"
    ).read_text()
    base = yaml.safe_load(sample)
    if policy is not None:
        base.setdefault("retrieval_agent", {})["longmemeval_answer_prompt"] = policy
    path.write_text(yaml.safe_dump(base))


def test_resolve_answer_prompt_policy_cli_wins(tmp_path):
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="agent_lightning")
    # CLI value 'memmachine_original' must beat config 'agent_lightning'.
    assert (
        _resolve_answer_prompt_policy("memmachine_original", str(cfg_path))
        == "memmachine_original"
    )


def test_resolve_answer_prompt_policy_falls_back_to_config(tmp_path):
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="agent_lightning")
    assert _resolve_answer_prompt_policy(None, str(cfg_path)) == "agent_lightning"


def test_resolve_answer_prompt_policy_default_when_unset(tmp_path):
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path)
    # Pydantic default = 'memmachine_original'.
    assert _resolve_answer_prompt_policy(None, str(cfg_path)) == "memmachine_original"


def test_resolve_answer_prompt_policy_missing_config_returns_default(tmp_path):
    """Defensive: missing configuration.yml falls through to in-process default."""
    missing = tmp_path / "does_not_exist.yml"
    assert _resolve_answer_prompt_policy(None, str(missing)) == "memmachine_original"


# ---------------------------------------------------------------------------
# Dataset normalization preserves question_date
# ---------------------------------------------------------------------------


def test_load_longmemeval_dataset_preserves_question_date(monkeypatch, tmp_path):
    """Local-fallback path must populate normalized_record['question_date']."""
    import json

    pytest.importorskip("datasets")
    pytest.importorskip("huggingface_hub")

    from evaluation.retrieval_agent import longmemeval_test as lme

    fake_records = [
        {
            "question_id": "qid_1",
            "question": "Q?",
            "answer": "A.",
            "question_type": "temporal-reasoning",
            "haystack_sessions": [],
            "question_date": "2023/04/10 (Mon) 23:07",
        },
        {
            "question_id": "qid_2",
            "question": "Q2",
            "answer": "A2",
            "question_type": "single-session-user",
            # missing question_date — defensive fallback
        },
    ]

    # Force the JSON-fallback path so we don't hit huggingface in CI.
    def fake_load_dataset(*_a, **_kw):
        raise RuntimeError("force fallback")

    fixture = tmp_path / "longmemeval_s_cleaned.json"
    fixture.write_text(json.dumps(fake_records))

    def fake_hf_hub_download(*_a, **_kw):
        return str(fixture)

    monkeypatch.setattr(
        "datasets.load_dataset", fake_load_dataset, raising=False
    )
    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download", fake_hf_hub_download, raising=False
    )

    out = lme.load_longmemeval_dataset(length=10, split="longmemeval_s_cleaned")
    assert out[0]["question_date"] == "2023/04/10 (Mon) 23:07"
    assert out[1]["question_date"] == ""  # defensive empty-string default


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
