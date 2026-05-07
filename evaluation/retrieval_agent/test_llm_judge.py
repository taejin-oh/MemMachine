"""Unit tests for evaluate_llm_judge retry logic and create_judge_fn selection."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
for extra in (
    REPO_ROOT,
    REPO_ROOT / "packages" / "common" / "src",
    REPO_ROOT / "packages" / "server" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from evaluation.retrieval_agent.llm_judge import (  # noqa: E402
    _MAX_JUDGE_ATTEMPTS,
    _parse_yes_no,
    _parse_yes_no_with_label,
    create_judge_fn,
    evaluate_llm_judge,
    evaluate_llm_judge_longmemeval,
    evaluate_llm_judge_longmemeval_with_details,
    evaluate_llm_judge_with_details,
)


def _call_fn_returning(*responses: str):
    """Return a stub call_fn that yields each response in sequence."""
    mock = MagicMock(side_effect=list(responses))
    return mock


def test_correct_label_returns_1():
    call_fn = _call_fn_returning(json.dumps({"label": "CORRECT"}))
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 1


def test_wrong_label_returns_0():
    call_fn = _call_fn_returning(json.dumps({"label": "WRONG"}))
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 0


def test_unknown_label_retries_then_returns_0():
    call_fn = _call_fn_returning(
        json.dumps({"label": "MAYBE"}),
        json.dumps({"label": "MAYBE"}),
    )
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 0
    assert call_fn.call_count == _MAX_JUDGE_ATTEMPTS


def test_call_fn_called_once_on_success():
    call_fn = _call_fn_returning(json.dumps({"label": "CORRECT"}))
    evaluate_llm_judge("q", "gold", "gen", call_fn)
    assert call_fn.call_count == 1


def test_missing_label_retries_then_succeeds():
    call_fn = _call_fn_returning(
        json.dumps({}),
        json.dumps({"label": "CORRECT"}),
    )
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 1
    assert call_fn.call_count == 2


def test_missing_label_both_attempts_returns_0():
    call_fn = _call_fn_returning(
        json.dumps({}),
        json.dumps({}),
    )
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 0
    assert call_fn.call_count == _MAX_JUDGE_ATTEMPTS


def test_non_dict_response_retries_then_succeeds():
    call_fn = _call_fn_returning(
        "just plain text",
        json.dumps({"label": "WRONG"}),
    )
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 0
    assert call_fn.call_count == 2


def test_call_fn_called_twice_on_retry():
    call_fn = _call_fn_returning(
        json.dumps({"no_label": "oops"}),
        json.dumps({"label": "WRONG"}),
    )
    evaluate_llm_judge("q", "gold", "gen", call_fn)
    assert call_fn.call_count == 2


def test_non_dict_both_attempts_returns_0():
    call_fn = _call_fn_returning("text", "also text")
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 0
    assert call_fn.call_count == _MAX_JUDGE_ATTEMPTS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (json.dumps({"label": "CORRECT"}), 1),
        (json.dumps({"label": "WRONG"}), 0),
    ],
)
def test_label_values(raw, expected):
    call_fn = _call_fn_returning(raw)
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == expected


def test_non_string_label_retries():
    """Non-string label (e.g. numeric) is invalid and triggers retry."""
    call_fn = _call_fn_returning(
        json.dumps({"label": 123}),
        json.dumps({"label": "CORRECT"}),
    )
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 1
    assert call_fn.call_count == 2


def test_dict_label_retries():
    """Nested-dict label is invalid and triggers retry."""
    call_fn = _call_fn_returning(
        json.dumps({"label": {"nested": "x"}}),
        json.dumps({"label": "WRONG"}),
    )
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 0
    assert call_fn.call_count == 2


def test_label_with_whitespace_and_case_normalized():
    """Labels are stripped and upper-cased before matching."""
    call_fn = _call_fn_returning(json.dumps({"label": "  correct\n"}))
    assert evaluate_llm_judge("q", "gold", "gen", call_fn) == 1
    assert call_fn.call_count == 1


# ---------------------------------------------------------------------------
# evaluate_llm_judge_with_details — exposes raw reply + parsed label
# ---------------------------------------------------------------------------


def test_with_details_correct_label_payload():
    """First-try CORRECT: details dict carries raw reply, label, attempts=1."""
    raw = json.dumps({"label": "CORRECT"})
    call_fn = _call_fn_returning(raw)
    details = evaluate_llm_judge_with_details("q", "gold", "gen", call_fn)
    assert details == {
        "score": 1,
        "raw_response": raw,
        "parsed_label": "CORRECT",
        "attempts": 1,
    }


def test_with_details_retry_then_success_records_last_raw():
    """On retry → success, ``raw_response`` is the SUCCESSFUL attempt's reply.

    Documenting this so debug logs reflect what the judge ultimately said,
    not the (irrelevant) first-attempt failure text.
    """
    bad = "not json at all"
    good = json.dumps({"label": "WRONG"})
    call_fn = _call_fn_returning(bad, good)
    details = evaluate_llm_judge_with_details("q", "gold", "gen", call_fn)
    assert details["score"] == 0
    assert details["parsed_label"] == "WRONG"
    assert details["raw_response"] == good
    assert details["attempts"] == 2


def test_with_details_all_attempts_fail_returns_label_none():
    """Both attempts fail to parse → score=0, parsed_label=None, raw=last reply.

    This is the all-zeros debug path: the operator can read raw_response to
    see *what* the judge LLM actually returned.
    """
    last_raw = "still not json"
    call_fn = _call_fn_returning("first not json", last_raw)
    details = evaluate_llm_judge_with_details("q", "gold", "gen", call_fn)
    assert details == {
        "score": 0,
        "raw_response": last_raw,
        "parsed_label": None,
        "attempts": _MAX_JUDGE_ATTEMPTS,
    }


def test_with_details_call_fn_returning_none_yields_empty_raw():
    """call_fn returning None → raw_response coerced to '' (no TypeError downstream)."""
    call_fn = MagicMock(side_effect=[None, None])
    details = evaluate_llm_judge_with_details("q", "gold", "gen", call_fn)
    assert details["raw_response"] == ""
    assert details["parsed_label"] is None
    assert details["score"] == 0


# ---------------------------------------------------------------------------
# evaluate_llm_judge_longmemeval_with_details — raw reply + parsed yes/no
# ---------------------------------------------------------------------------


def test_lme_with_details_yes_lenient_payload():
    fn, _ = _capturing_call_fn("yes")
    details = evaluate_llm_judge_longmemeval_with_details(
        "q", "gold", "gen", "single-session-user", "qid_1", fn
    )
    assert details == {
        "score": 1,
        "raw_response": "yes",
        "parsed_label": "yes",
        "attempts": 1,
    }


def test_lme_with_details_lenient_yesterday_substring_trap_records_yes():
    """Lenient policy marks ``yesterday`` as 1 (substring trap) — details echo it.

    Pinning this so the all-zeros debug story stays clear: parsed_label='yes'
    plus raw_response='yesterday' tells the operator exactly which trap fired.
    """
    fn, _ = _capturing_call_fn("yesterday")
    details = evaluate_llm_judge_longmemeval_with_details(
        "q", "gold", "gen", "temporal-reasoning", "qid_1", fn
    )
    assert details["score"] == 1
    assert details["parsed_label"] == "yes"
    assert details["raw_response"] == "yesterday"


def test_lme_with_details_strict_unparseable_label_none():
    """Strict policy rejects ``not yes`` → score=0, parsed_label=None."""
    fn, _ = _capturing_call_fn("not yes")
    details = evaluate_llm_judge_longmemeval_with_details(
        "q", "gold", "gen", "single-session-user", "qid_1", fn, "strict"
    )
    assert details["score"] == 0
    assert details["parsed_label"] is None
    assert details["raw_response"] == "not yes"


def test_lme_with_details_call_fn_returning_none_yields_empty_raw():
    """call_fn returning None → raw='' and lenient parses to 'no'."""
    fn = MagicMock(return_value=None)
    details = evaluate_llm_judge_longmemeval_with_details(
        "q", "gold", "gen", "multi-session", "qid_1", fn
    )
    assert details["raw_response"] == ""
    assert details["parsed_label"] == "no"
    assert details["score"] == 0


# ---------------------------------------------------------------------------
# _parse_yes_no_with_label — distinguishes "no" from "unparseable"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("yes", (1, "yes")),
        ("Yes\n", (1, "yes")),
        ("no", (0, "no")),
        ("nope", (0, "no")),  # lenient: no 'yes' substring → "no"
        ("yesterday", (1, "yes")),  # lenient substring trap
        ("", (0, "no")),
    ],
)
def test_parse_yes_no_with_label_lenient(raw, expected):
    assert _parse_yes_no_with_label(raw, policy="lenient") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("yes", (1, "yes")),
        ("no", (0, "no")),
        ("Yes.", (1, "yes")),
        # Unparseable under strict → None (NOT "no") so callers can tell
        # "judge said no" from "judge said something we couldn't parse".
        ("yes and no", (0, None)),
        ("yesterday", (0, None)),
        ("", (0, None)),
        ("maybe", (0, None)),
    ],
)
def test_parse_yes_no_with_label_strict(raw, expected):
    assert _parse_yes_no_with_label(raw, policy="strict") == expected


def test_parse_yes_no_int_wrapper_matches_with_label():
    """The int-only ``_parse_yes_no`` returns the same score as ``_parse_yes_no_with_label``."""
    for raw in ("yes", "no", "yesterday", "not yes", "", "maybe"):
        for policy in ("lenient", "strict"):
            assert _parse_yes_no(raw, policy=policy) == (
                _parse_yes_no_with_label(raw, policy=policy)[0]
            )


# ---------------------------------------------------------------------------
# create_judge_fn selection / fallback (no real API calls — OpenAI stubbed)
# ---------------------------------------------------------------------------


_SAMPLE = REPO_ROOT / "sample_configs" / "episodic_memory_config.cpu.sample"


_ANSWER_URL = "https://answer.example/v1"
_JUDGE_URL = "https://judge.example/v1"


def _write_fixture(tmp_path, *, judge_llm_model, llm_model="openai_model"):
    """Build a configuration.yml fixture with two distinguishable LLM resources.

    The sample config defines `openai_model` (provider openai-responses) and
    `ollama_model` (provider openai-chat-completions). We overwrite their
    base_url to unambiguous unique values so the test can confirm exactly
    which entry create_judge_fn picked, regardless of whether the answer or
    judge role is assigned to either ID.
    """
    base = yaml.safe_load(_SAMPLE.read_text())
    lms = base["resources"]["language_models"]
    lms["openai_model"]["config"]["base_url"] = _ANSWER_URL
    lms["ollama_model"]["config"]["base_url"] = _JUDGE_URL
    base["retrieval_agent"]["llm_model"] = llm_model
    if judge_llm_model is not None:
        base["retrieval_agent"]["judge_llm_model"] = judge_llm_model
    elif "judge_llm_model" in base.get("retrieval_agent", {}):
        del base["retrieval_agent"]["judge_llm_model"]
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))
    return fixture


class _FakeOpenAI:
    """Stub OpenAI client capturing the (api_key, base_url) used to construct it."""

    last_init: dict | None = None

    def __init__(self, api_key=None, base_url=None, **kwargs):
        type(self).last_init = {"api_key": api_key, "base_url": base_url}
        self.responses = MagicMock()
        self.chat = MagicMock()


def test_create_judge_fn_picks_judge_llm_entry(tmp_path, monkeypatch):
    """When judge_llm_model is set, the judge resource (not llm_model) is used."""
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setattr(_FakeOpenAI, "last_init", None)

    fixture = _write_fixture(
        tmp_path, llm_model="openai_model", judge_llm_model="ollama_model"
    )
    create_judge_fn(str(fixture))

    assert _FakeOpenAI.last_init is not None
    assert _FakeOpenAI.last_init["base_url"] == _JUDGE_URL


def test_create_judge_fn_falls_back_to_answer_llm(tmp_path, monkeypatch):
    """Without judge_llm_model, create_judge_fn uses retrieval_agent.llm_model."""
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setattr(_FakeOpenAI, "last_init", None)

    fixture = _write_fixture(tmp_path, llm_model="ollama_model", judge_llm_model=None)
    create_judge_fn(str(fixture))

    assert _FakeOpenAI.last_init is not None
    assert _FakeOpenAI.last_init["base_url"] == _JUDGE_URL


def test_create_judge_fn_empty_string_judge_falls_back(tmp_path, monkeypatch):
    """An empty-string judge_llm_model is treated as unset and falls back to llm_model."""
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setattr(_FakeOpenAI, "last_init", None)

    fixture = _write_fixture(tmp_path, llm_model="ollama_model", judge_llm_model="")
    create_judge_fn(str(fixture))

    assert _FakeOpenAI.last_init is not None
    assert _FakeOpenAI.last_init["base_url"] == _JUDGE_URL


def test_create_judge_fn_raises_when_both_unset(tmp_path):
    """ValueError when neither judge_llm_model nor llm_model is set."""
    base = yaml.safe_load(_SAMPLE.read_text())
    base["retrieval_agent"] = {}
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    with pytest.raises(ValueError, match=r"judge LLM is not configured"):
        create_judge_fn(str(fixture))


def test_create_judge_fn_unknown_id_raises_not_defined(tmp_path):
    """An ID absent from resources.language_models gets the 'not defined' error."""
    base = yaml.safe_load(_SAMPLE.read_text())
    base["retrieval_agent"]["judge_llm_model"] = "ghost_model"
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    with pytest.raises(ValueError, match=r"is not defined under resources"):
        create_judge_fn(str(fixture))


# ---------------------------------------------------------------------------
# evaluate_llm_judge_longmemeval — task-specific prompt + yes/no parsing
# ---------------------------------------------------------------------------


def _capturing_call_fn(reply: str = "yes"):
    """call_fn stub that records the prompt it was invoked with."""
    captured = {"prompt": None}

    def _fn(prompt: str) -> str:
        captured["prompt"] = prompt
        return reply

    return _fn, captured


def test_longmemeval_yes_returns_1():
    fn, _ = _capturing_call_fn("yes\n")
    assert (
        evaluate_llm_judge_longmemeval(
            "q", "gold", "gen", "single-session-user", "qid_1", fn
        )
        == 1
    )


def test_longmemeval_no_returns_0():
    fn, _ = _capturing_call_fn("no")
    assert (
        evaluate_llm_judge_longmemeval(
            "q", "gold", "gen", "multi-session", "qid_1", fn
        )
        == 0
    )


def test_longmemeval_abstention_prompt_used():
    fn, captured = _capturing_call_fn("yes")
    evaluate_llm_judge_longmemeval(
        "q", "explanation", "gen", "single-session-user", "qid_abs_1", fn
    )
    assert "unanswerable question" in captured["prompt"]


def test_longmemeval_temporal_prompt_used():
    fn, captured = _capturing_call_fn("yes")
    evaluate_llm_judge_longmemeval(
        "q", "gold", "gen", "temporal-reasoning", "qid_1", fn
    )
    assert "off-by-one errors" in captured["prompt"]


def test_longmemeval_preference_prompt_used():
    fn, captured = _capturing_call_fn("yes")
    evaluate_llm_judge_longmemeval(
        "q", "rubric", "gen", "single-session-preference", "qid_1", fn
    )
    assert "rubric for desired personalized response" in captured["prompt"]


# ---------------------------------------------------------------------------
# _parse_yes_no — strict-policy regression tests
#
# All tests in this section pin ``policy="strict"`` because the default
# ``lenient`` policy preserves the original LongMemEval ``'yes' in lower(raw)``
# heuristic and would mark several of these inputs as 1 (e.g. ``yesterday`` /
# ``YES — the answer matches`` / ``I think yes`` all contain the substring
# ``yes``). These tests document the *strict-only* behavior — they are NOT
# assertions about the default policy.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Exact yes/no — the only accepted forms under strict policy:
        ("yes", 1),
        ("Yes", 1),
        ("YES", 1),
        ("Yes.", 1),
        ("yes!", 1),
        ("yes?", 1),
        ("yes,", 1),
        ("yes\n", 1),
        ("  yes  ", 1),
        ("no", 0),
        ("No", 0),
        ("No.", 0),
        ("no!", 0),
        # Verbose / ambiguous replies — all rejected under strict policy
        # (lenient would mark every line below containing "yes" as 1):
        ("yes and no", 0),
        ("YES — the answer matches", 0),
        ("No, off by two days", 0),
        ("not yes", 0),
        ("I think yes", 0),
        # Substring traps — rejected under strict; lenient marks them 1:
        ("yesterday", 0),
        ("nope", 0),
        # Empty / non-yes-no replies — rejected under strict:
        ("", 0),
        ("maybe", 0),
        ("I think so", 0),
    ],
)
def test_parse_yes_no_strict(raw, expected):
    assert _parse_yes_no(raw, policy="strict") == expected


def test_longmemeval_strict_rejects_yesterday_substring():
    """Under strict policy, ``yesterday`` is rejected (substring trap).

    Lenient policy would mark this 1 because the reply contains ``yes``.
    """
    fn, _ = _capturing_call_fn("yesterday")
    assert (
        evaluate_llm_judge_longmemeval(
            "q", "gold", "gen", "temporal-reasoning", "qid_1", fn, "strict"
        )
        == 0
    )


def test_longmemeval_strict_rejects_not_yes():
    """Under strict policy, ``not yes`` is rejected as ambiguous (0)."""
    fn, _ = _capturing_call_fn("not yes")
    assert (
        evaluate_llm_judge_longmemeval(
            "q", "gold", "gen", "single-session-user", "qid_1", fn, "strict"
        )
        == 0
    )


def test_longmemeval_strict_rejects_yes_and_no():
    """Under strict policy, ``yes and no`` is rejected as ambiguous (0)."""
    fn, _ = _capturing_call_fn("yes and no")
    assert (
        evaluate_llm_judge_longmemeval(
            "q", "gold", "gen", "multi-session", "qid_1", fn, "strict"
        )
        == 0
    )


def test_longmemeval_strict_rejects_i_think_yes():
    """Under strict policy, ``I think yes`` is rejected (extra text — 0)."""
    fn, _ = _capturing_call_fn("I think yes")
    assert (
        evaluate_llm_judge_longmemeval(
            "q", "gold", "gen", "single-session-user", "qid_1", fn, "strict"
        )
        == 0
    )


# ---------------------------------------------------------------------------
# create_judge_fn json_mode=False — verifies plain-text mode wiring
# ---------------------------------------------------------------------------


class _RecordingOpenAI:
    """OpenAI stub that lets tests inspect the kwargs passed to the API."""

    last_chat_kwargs: dict | None = None
    last_responses_kwargs: dict | None = None

    def __init__(self, api_key=None, base_url=None, **kwargs):
        cls = type(self)

        class _ChatCompletions:
            @staticmethod
            def create(**call_kwargs):
                cls.last_chat_kwargs = call_kwargs
                msg = MagicMock()
                msg.message.content = "yes"
                resp = MagicMock()
                resp.choices = [msg]
                return resp

        class _Chat:
            completions = _ChatCompletions()

        class _Responses:
            @staticmethod
            def create(**call_kwargs):
                cls.last_responses_kwargs = call_kwargs
                resp = MagicMock()
                resp.output_text = "yes"
                return resp

        self.chat = _Chat()
        self.responses = _Responses()


def test_create_judge_fn_chat_text_mode_kwargs(tmp_path, monkeypatch):
    """json_mode=False on chat-completions: no response_format, max_tokens=10, temperature=0."""
    monkeypatch.setattr("openai.OpenAI", _RecordingOpenAI)
    _RecordingOpenAI.last_chat_kwargs = None

    fixture = _write_fixture(
        tmp_path, llm_model="openai_model", judge_llm_model="ollama_model"
    )
    fn = create_judge_fn(str(fixture), json_mode=False)
    fn("test prompt")

    kwargs = _RecordingOpenAI.last_chat_kwargs
    assert kwargs is not None
    assert "response_format" not in kwargs
    assert kwargs.get("max_tokens") == 10
    assert kwargs.get("temperature") == 0


def test_create_judge_fn_chat_json_mode_kwargs(tmp_path, monkeypatch):
    """Default (json_mode=True) keeps response_format and omits max_tokens / temperature."""
    monkeypatch.setattr("openai.OpenAI", _RecordingOpenAI)
    _RecordingOpenAI.last_chat_kwargs = None

    fixture = _write_fixture(
        tmp_path, llm_model="openai_model", judge_llm_model="ollama_model"
    )
    fn = create_judge_fn(str(fixture))
    fn("test prompt")

    kwargs = _RecordingOpenAI.last_chat_kwargs
    assert kwargs is not None
    assert kwargs.get("response_format") == {"type": "json_object"}
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs


def test_create_judge_fn_responses_text_mode_kwargs(tmp_path, monkeypatch):
    """json_mode=False on openai-responses: no `text` arg, max_output_tokens=10.

    Responses API is intentionally NOT given ``temperature=0`` because some
    reasoning models reject it; the chat-completions branch is the only one
    that hard-codes determinism.
    """
    monkeypatch.setattr("openai.OpenAI", _RecordingOpenAI)
    _RecordingOpenAI.last_responses_kwargs = None

    # openai_model is openai-responses in the sample config.
    fixture = _write_fixture(
        tmp_path, llm_model="ollama_model", judge_llm_model="openai_model"
    )
    fn = create_judge_fn(str(fixture), json_mode=False)
    fn("test prompt")

    kwargs = _RecordingOpenAI.last_responses_kwargs
    assert kwargs is not None
    assert "text" not in kwargs
    assert kwargs.get("max_output_tokens") == 10
    assert "temperature" not in kwargs
