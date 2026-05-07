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
    _ANSWER_PROMPT_EDWIN1,
    _ANSWER_PROMPT_EDWIN3,
    _ANSWER_PROMPT_LME_ORIGIN,
    _ANSWER_PROMPT_LME_ORIGIN_COT,
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


def test_lme_origin_prompt_is_verbatim_upstream():
    """LME_origin_prompt must match xiaowu0162/LongMemEval upstream verbatim
    (src/generation/run_generation.py answer_prompt_template, no-merge no-CoT).

    Only positional ``{}`` placeholders are converted to named ones — no other
    text is altered.
    """
    expected = (
        "I will give you several history chats between you and a user. "
        "Please answer the question based on the relevant chat history."
        "\n\n\n"
        "History Chats:\n\n{memories}\n\n"
        "Current Date: {question_date}\n"
        "Question: {question}\n"
        "Answer:"
    )
    assert expected == _ANSWER_PROMPT_LME_ORIGIN


def test_lme_origin_prompt_renders_with_question_date():
    """Upstream-verbatim prompt must format with memories+question+question_date."""
    prompt = _ANSWER_PROMPT_LME_ORIGIN.format(
        memories="MEM",
        question="Q",
        question_date="Monday, April 10, 2023 at 11:07 PM",
    )
    assert "MEM" in prompt
    assert "Q" in prompt
    assert "Current Date: Monday, April 10, 2023 at 11:07 PM" in prompt
    # Upstream is intentionally minimal — no MemMachine reasoning guides.
    assert "KNOWLEDGE UPDATES" not in prompt
    assert "PLANNED ACTIONS" not in prompt
    # No length cap, no open-domain fallback.
    assert "max 2 sentences" not in prompt
    assert "Open-domain fallback" not in prompt


def test_public_alias_points_to_default_policy():
    """ANSWER_PROMPT export must equal the default-policy body for backward import compat."""
    assert ANSWER_PROMPT is _ANSWER_PROMPT_LME_ORIGIN


def test_policy_registry_keys():
    """Policy registry must list every supported policy body."""
    assert set(_ANSWER_PROMPT_BY_POLICY) == {
        "memmachine_original",
        "agent_lightning",
        "LME_origin_prompt",
        "LME_origin_cot_prompt",
        "edwin1",
        "edwin3",
    }


# ---------------------------------------------------------------------------
# LME_origin_cot_prompt (xiaowu0162/LongMemEval upstream CoT branch)
# ---------------------------------------------------------------------------


def test_lme_origin_cot_prompt_is_verbatim_upstream():
    """LME_origin_cot_prompt must match xiaowu0162/LongMemEval upstream verbatim
    (src/generation/run_generation.py answer_prompt_template, cot=True branch).

    Differs from LME_origin_prompt by exactly two changes:
      - one CoT instruction sentence inserted into the preamble, and
      - the trailing ``Answer (step by step):`` cue (vs. ``Answer:``).
    Only positional ``{}`` placeholders are converted to named ones — no
    other text is altered. This test guards against accidental drift.
    """
    expected = (
        "I will give you several history chats between you and a user. "
        "Please answer the question based on the relevant chat history. "
        "Answer the question step by step: first extract all the relevant "
        "information, and then reason over the information to get the answer."
        "\n\n\n"
        "History Chats:\n\n{memories}\n\n"
        "Current Date: {question_date}\n"
        "Question: {question}\n"
        "Answer (step by step):"
    )
    assert expected == _ANSWER_PROMPT_LME_ORIGIN_COT


def test_lme_origin_cot_prompt_renders_with_question_date():
    """CoT prompt must format with the same kwargs as every other policy."""
    prompt = _ANSWER_PROMPT_LME_ORIGIN_COT.format(
        memories="MEM",
        question="Q",
        question_date="Monday, April 10, 2023 at 11:07 PM",
    )
    assert "MEM" in prompt
    assert "Q" in prompt
    assert "Current Date: Monday, April 10, 2023 at 11:07 PM" in prompt
    # CoT-specific markers — present in cot=True, absent in no-CoT.
    assert "step by step" in prompt
    assert prompt.endswith("Answer (step by step):")


def test_lme_origin_cot_prompt_differs_from_no_cot():
    """The CoT and no-CoT bodies must be distinct (sanity guard).

    Both share the upstream framing — this test pins that the CoT-specific
    additions are present in CoT and absent in no-CoT.
    """
    assert _ANSWER_PROMPT_LME_ORIGIN_COT != _ANSWER_PROMPT_LME_ORIGIN
    assert "step by step" not in _ANSWER_PROMPT_LME_ORIGIN
    assert "step by step" in _ANSWER_PROMPT_LME_ORIGIN_COT


# ---------------------------------------------------------------------------
# edwin1 / edwin3 (docs/msr/edwin_prompt.md alternates)
# ---------------------------------------------------------------------------


def test_edwin1_prompt_renders_with_question_date():
    """EDWIN1 must format with memories+question+question_date (placeholders normalized)."""
    prompt = _ANSWER_PROMPT_EDWIN1.format(
        memories="MEM",
        question="Q",
        question_date="Monday, April 10, 2023 at 11:07 PM",
    )
    assert "MEM" in prompt
    assert "Q" in prompt
    # docs/msr/edwin_prompt.md uses the label "Question timestamp:" — the
    # label text is preserved verbatim, only the placeholder name is
    # normalized to {question_date}.
    assert "Question timestamp: Monday, April 10, 2023 at 11:07 PM" in prompt
    # 8-rule reasoning prompt: each numbered rule should be present.
    for n in range(1, 9):
        assert f"\n{n}. " in prompt
    # Length cue from EDWIN1 — pinning so future edits don't silently drop it.
    assert "no more than a couple of sentences" in prompt


def test_edwin1_prompt_has_no_unsubstituted_placeholders():
    """After format(), no ``{...}`` placeholder fragments should remain.

    Guards against accidental ``{joined_history}`` / ``{question_timestamp}``
    leftovers from the docs/msr source — those would break str.format() calls
    elsewhere in the pipeline.
    """
    prompt = _ANSWER_PROMPT_EDWIN1.format(
        memories="MEM", question="Q", question_date="DATE"
    )
    assert "{joined_history}" not in prompt
    assert "{question_timestamp}" not in prompt
    assert "{memories}" not in prompt
    assert "{question_date}" not in prompt


def test_edwin3_prompt_renders_with_question_date():
    """EDWIN3 must format with memories+question+question_date."""
    prompt = _ANSWER_PROMPT_EDWIN3.format(
        memories="MEM",
        question="Q",
        question_date="Monday, April 10, 2023 at 11:07 PM",
    )
    assert "MEM" in prompt
    assert "Q" in prompt
    assert "Current date: Monday, April 10, 2023 at 11:07 PM" in prompt
    # EDWIN3 distinguishing markers vs memmachine_original:
    assert "MOST RECENT USER INPUT" in prompt
    # KNOWLEDGE UPDATES / PLANNED ACTIONS guides preserved from the source.
    assert "KNOWLEDGE UPDATES" in prompt
    assert "PLANNED ACTIONS" in prompt
    # Unlike memmachine_original, EDWIN3 omits the <history>...</history> wrap.
    assert "<history>" not in prompt
    assert "</history>" not in prompt


def test_edwin3_prompt_has_no_unsubstituted_placeholders():
    """After format(), no ``{...}`` placeholder fragments should remain."""
    prompt = _ANSWER_PROMPT_EDWIN3.format(
        memories="MEM", question="Q", question_date="DATE"
    )
    assert "{joined_history}" not in prompt
    assert "{question_timestamp}" not in prompt
    assert "{memories}" not in prompt
    assert "{question_date}" not in prompt


def test_edwin3_distinct_from_memmachine_original():
    """EDWIN3 is closely related to memmachine_original but must not be identical.

    Pins the two distinguishing changes documented in the prompt body
    docstring: the MOST RECENT USER INPUT paragraph (added) and the absence
    of the ``<history>...</history>`` wrapper.
    """
    assert _ANSWER_PROMPT_EDWIN3 != _ANSWER_PROMPT_MEMMACHINE_ORIGINAL
    assert "MOST RECENT USER INPUT" in _ANSWER_PROMPT_EDWIN3
    assert "MOST RECENT USER INPUT" not in _ANSWER_PROMPT_MEMMACHINE_ORIGINAL
    assert "<history>" in _ANSWER_PROMPT_MEMMACHINE_ORIGINAL
    assert "<history>" not in _ANSWER_PROMPT_EDWIN3


# ---------------------------------------------------------------------------
# _select_answer_prompt
# ---------------------------------------------------------------------------


def test_select_answer_prompt_memmachine_original():
    assert _select_answer_prompt("memmachine_original") is (
        _ANSWER_PROMPT_MEMMACHINE_ORIGINAL
    )


def test_select_answer_prompt_agent_lightning():
    assert _select_answer_prompt("agent_lightning") is _ANSWER_PROMPT_AGENT_LIGHTNING


def test_select_answer_prompt_lme_origin():
    assert _select_answer_prompt("LME_origin_prompt") is _ANSWER_PROMPT_LME_ORIGIN


def test_select_answer_prompt_lme_origin_cot():
    assert _select_answer_prompt("LME_origin_cot_prompt") is (
        _ANSWER_PROMPT_LME_ORIGIN_COT
    )


def test_select_answer_prompt_edwin1():
    assert _select_answer_prompt("edwin1") is _ANSWER_PROMPT_EDWIN1


def test_select_answer_prompt_edwin3():
    assert _select_answer_prompt("edwin3") is _ANSWER_PROMPT_EDWIN3


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
    # Pydantic default = 'LME_origin_prompt' (upstream verbatim).
    assert _resolve_answer_prompt_policy(None, str(cfg_path)) == "LME_origin_prompt"


def test_resolve_answer_prompt_policy_missing_config_returns_default(tmp_path):
    """Defensive: missing configuration.yml falls through to in-process default."""
    missing = tmp_path / "does_not_exist.yml"
    assert _resolve_answer_prompt_policy(None, str(missing)) == "LME_origin_prompt"


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
