"""Tests for scripts/stages/judge.py LongMemEval routing.

Run:
    pytest scripts/test_stages_judge.py -v

Verifies that ``scripts/stages/judge.run`` routes rows whose ``category`` is a
LongMemEval question_type to ``evaluate_llm_judge_longmemeval`` (and detects
abstention from ``_abs`` in ``question_id``), while non-LongMemEval rows keep
the existing JSON-mode ``evaluate_llm_judge`` path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
for extra in (
    REPO_ROOT / "packages" / "common" / "src",
    REPO_ROOT / "packages" / "server" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from scripts.stages import judge as judge_stage  # noqa: E402


def _write_rows(tmp_path: Path, rows: list[dict]) -> Path:
    """Materialize generate.jsonl + a stub run config; return run_cfg dict."""
    out_dir = tmp_path / "results" / "test_run"
    out_dir.mkdir(parents=True)
    gen_path = out_dir / "generate.jsonl"
    with gen_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return out_dir


def _patch_common(monkeypatch, tmp_path: Path, out_dir: Path):
    """Stub the cm helpers and a dummy config path."""
    monkeypatch.setattr(judge_stage.cm, "results_dir_for", lambda _cfg: out_dir)
    monkeypatch.setattr(
        judge_stage.cm, "resolve_config_path", lambda _cfg: str(tmp_path / "cfg.yml")
    )
    # _judge_config_path() reads the yaml to look up resources.language_models;
    # we stub it out entirely so tests don't need a real configuration.yml.
    monkeypatch.setattr(judge_stage, "_judge_config_path", lambda _r, p: p)
    # _resolve_yesno_policy() also reads yaml when run_cfg doesn't set the
    # policy. Stub it to a fixed default ("lenient") so tests that don't care
    # about policy resolution don't need a real configuration.yml. Tests that
    # specifically exercise policy resolution patch this themselves.
    monkeypatch.setattr(
        judge_stage,
        "_resolve_yesno_policy",
        lambda run_cfg, _path: (run_cfg.get("judge") or {}).get(
            "longmemeval_yesno_policy", "lenient"
        ),
    )


def test_run_routes_longmemeval_category_to_longmemeval_judge(monkeypatch, tmp_path):
    """A LongMemEval row uses evaluate_llm_judge_longmemeval, not the JSON judge."""
    out_dir = _write_rows(
        tmp_path,
        [
            {
                "question": "q",
                "category": "temporal-reasoning",
                "question_id": "qid_1",
                "golden_answer": "a",
                "model_answer": "yes",
            }
        ],
    )
    _patch_common(monkeypatch, tmp_path, out_dir)

    json_judge = MagicMock()
    text_judge = MagicMock()

    longmemeval_calls = []
    legacy_calls = []

    def fake_lme(
        question,
        gold_answer,
        generated_answer,
        question_type,
        question_id,
        call_fn,
        yesno_policy="lenient",
    ):
        longmemeval_calls.append(
            {
                "question_type": question_type,
                "question_id": question_id,
                "call_fn": call_fn,
                "yesno_policy": yesno_policy,
            }
        )
        return {
            "score": 1,
            "raw_response": "yes",
            "parsed_label": "yes",
            "attempts": 1,
        }

    def fake_legacy(question, gold_answer, generated_answer, call_fn):
        legacy_calls.append({"call_fn": call_fn})
        return {
            "score": 1,
            "raw_response": '{"label":"CORRECT"}',
            "parsed_label": "CORRECT",
            "attempts": 1,
        }

    # judge.run() imports from this module *inside* the function body,
    # so patches must target the source module — not judge_stage itself.
    import evaluation.retrieval_agent.llm_judge as lm

    monkeypatch.setattr(
        lm,
        "create_judge_fn",
        lambda _path, json_mode=True: json_judge if json_mode else text_judge,
    )
    monkeypatch.setattr(lm, "evaluate_llm_judge_longmemeval_with_details", fake_lme)
    monkeypatch.setattr(lm, "evaluate_llm_judge_with_details", fake_legacy)

    judge_stage.run({"run_name": "test_run", "configuration": {"generated_path": "x"}})

    assert len(longmemeval_calls) == 1
    assert longmemeval_calls[0]["question_type"] == "temporal-reasoning"
    assert longmemeval_calls[0]["question_id"] == "qid_1"
    assert longmemeval_calls[0]["yesno_policy"] == "lenient"
    # text-mode judge (json_mode=False) should be passed
    assert longmemeval_calls[0]["call_fn"] is text_judge
    assert legacy_calls == []


def test_run_routes_non_longmemeval_category_to_json_judge(monkeypatch, tmp_path):
    """LOCOMO/Wiki/HotpotQA-style categories keep the JSON ACCURACY_PROMPT path."""
    out_dir = _write_rows(
        tmp_path,
        [
            {
                "question": "q",
                "category": "1",  # LOCOMO-style numeric category
                "question_id": "any",
                "golden_answer": "a",
                "model_answer": "yes",
            },
            {
                "question": "q2",
                "category": "single_hop",  # HotpotQA/Wiki-style
                "question_id": "",
                "golden_answer": "a",
                "model_answer": "yes",
            },
        ],
    )
    _patch_common(monkeypatch, tmp_path, out_dir)

    json_judge = MagicMock()
    text_judge_calls = {"count": 0}

    def fake_create(_path, json_mode=True):
        if not json_mode:
            text_judge_calls["count"] += 1
        return json_judge if json_mode else MagicMock()

    legacy_calls = []
    longmemeval_calls = []

    import evaluation.retrieval_agent.llm_judge as lm

    monkeypatch.setattr(lm, "create_judge_fn", fake_create)

    def _fake_legacy_details(**kw):
        legacy_calls.append(kw)
        return {
            "score": 1,
            "raw_response": '{"label":"CORRECT"}',
            "parsed_label": "CORRECT",
            "attempts": 1,
        }

    def _fake_lme_details(**kw):
        longmemeval_calls.append(kw)
        return {
            "score": 1,
            "raw_response": "yes",
            "parsed_label": "yes",
            "attempts": 1,
        }

    monkeypatch.setattr(lm, "evaluate_llm_judge_with_details", _fake_legacy_details)
    monkeypatch.setattr(
        lm, "evaluate_llm_judge_longmemeval_with_details", _fake_lme_details
    )

    judge_stage.run({"run_name": "test_run", "configuration": {"generated_path": "x"}})

    assert len(legacy_calls) == 2
    assert legacy_calls[0]["call_fn"] is json_judge
    assert longmemeval_calls == []
    # text-mode judge must NOT have been built when no LongMemEval rows present.
    assert text_judge_calls["count"] == 0


def test_run_abstention_question_id_uses_abstention_prompt(monkeypatch, tmp_path):
    """``_abs`` in question_id must reach get_anscheck_prompt(..., abstention=True).

    We assert via the captured prompt text — abstention template contains the
    distinct phrase ``unanswerable question`` not present in any other template.
    """
    out_dir = _write_rows(
        tmp_path,
        [
            {
                "question": "q",
                "category": "single-session-user",
                "question_id": "qid_abs_42",
                "golden_answer": "explanation",
                "model_answer": "I cannot answer that",
            }
        ],
    )
    _patch_common(monkeypatch, tmp_path, out_dir)

    captured = {"prompt": None}

    def text_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "yes"

    def fake_create(_path, json_mode=True):
        return text_call if not json_mode else MagicMock()

    import evaluation.retrieval_agent.llm_judge as lm

    monkeypatch.setattr(lm, "create_judge_fn", fake_create)
    # Use the real evaluate_llm_judge_longmemeval so the abstention branch is
    # exercised end-to-end (prompt build → call_fn → yes/no parse).

    judge_stage.run({"run_name": "test_run", "configuration": {"generated_path": "x"}})

    assert captured["prompt"] is not None
    assert "unanswerable question" in captured["prompt"]


def test_run_persists_judge_raw_response_and_label(monkeypatch, tmp_path):
    """judge.jsonl must include raw judge reply + parsed label per row.

    Regression for the 'all-zeros judge run with no way to debug' case:
    without these fields, an operator who sees every llm_score=0 cannot tell
    whether the judge LLM returned malformed JSON, returned ``"WRONG"``, or
    returned text that the LongMemEval policy rejected.
    """
    out_dir = _write_rows(
        tmp_path,
        [
            # JSON judge path → expects judge_raw_response='garbage', label=None.
            {
                "question": "q1",
                "category": "1",
                "golden_answer": "a",
                "model_answer": "y",
            },
            # LongMemEval path → expects raw='yes', parsed_label='yes'.
            {
                "question": "q2",
                "category": "multi-session",
                "question_id": "qid_2",
                "golden_answer": "a",
                "model_answer": "y",
            },
        ],
    )
    _patch_common(monkeypatch, tmp_path, out_dir)

    import evaluation.retrieval_agent.llm_judge as lm

    monkeypatch.setattr(
        lm, "create_judge_fn", lambda _path, json_mode=True: lambda _p: "irrelevant"
    )
    monkeypatch.setattr(
        lm,
        "evaluate_llm_judge_with_details",
        lambda **_kw: {
            "score": 0,
            "raw_response": "garbage non-json reply",
            "parsed_label": None,
            "attempts": 2,
        },
    )
    monkeypatch.setattr(
        lm,
        "evaluate_llm_judge_longmemeval_with_details",
        lambda **_kw: {
            "score": 1,
            "raw_response": "yes",
            "parsed_label": "yes",
            "attempts": 1,
        },
    )

    judge_stage.run({"run_name": "test_run", "configuration": {"generated_path": "x"}})

    judged_path = out_dir / "judge.jsonl"
    with judged_path.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]

    assert rows[0]["llm_score"] == 0
    assert rows[0]["judge_raw_response"] == "garbage non-json reply"
    assert rows[0]["judge_parsed_label"] is None
    assert rows[0]["judge_attempts"] == 2

    assert rows[1]["llm_score"] == 1
    assert rows[1]["judge_raw_response"] == "yes"
    assert rows[1]["judge_parsed_label"] == "yes"
    assert rows[1]["judge_attempts"] == 1


def test_run_writes_judge_jsonl_with_llm_score(monkeypatch, tmp_path):
    """End-to-end smoke: judge.jsonl receives ``llm_score`` per row."""
    out_dir = _write_rows(
        tmp_path,
        [
            {
                "question": "q1",
                "category": "1",
                "golden_answer": "a",
                "model_answer": "y",
            },
            {
                "question": "q2",
                "category": "multi-session",
                "question_id": "qid_2",
                "golden_answer": "a",
                "model_answer": "y",
            },
        ],
    )
    _patch_common(monkeypatch, tmp_path, out_dir)

    import evaluation.retrieval_agent.llm_judge as lm

    monkeypatch.setattr(
        lm,
        "create_judge_fn",
        lambda _path, json_mode=True: lambda _p: "yes",
    )
    monkeypatch.setattr(
        lm,
        "evaluate_llm_judge_with_details",
        lambda **_kw: {
            "score": 0,
            "raw_response": '{"label":"WRONG"}',
            "parsed_label": "WRONG",
            "attempts": 1,
        },
    )
    monkeypatch.setattr(
        lm,
        "evaluate_llm_judge_longmemeval_with_details",
        lambda **_kw: {
            "score": 1,
            "raw_response": "yes",
            "parsed_label": "yes",
            "attempts": 1,
        },
    )

    judge_stage.run({"run_name": "test_run", "configuration": {"generated_path": "x"}})

    judged_path = out_dir / "judge.jsonl"
    assert judged_path.exists()
    with judged_path.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]
    assert [row["llm_score"] for row in rows] == [0, 1]


# ---------------------------------------------------------------------------
# _resolve_yesno_policy: precedence + log + validation
# ---------------------------------------------------------------------------


def _write_minimal_cfg(path: Path, *, policy: str | None = None) -> None:
    """Materialize a minimal configuration.yml that the Pydantic schema accepts."""
    import yaml

    REPO_ROOT_LOCAL = Path(__file__).resolve().parent.parent
    sample = (
        REPO_ROOT_LOCAL / "sample_configs" / "episodic_memory_config.cpu.sample"
    ).read_text()
    base = yaml.safe_load(sample)
    if policy is not None:
        base.setdefault("retrieval_agent", {})["longmemeval_yesno_policy"] = policy
    path.write_text(yaml.safe_dump(base))


def test_resolve_yesno_policy_run_cfg_wins(tmp_path):
    """run_cfg.judge.longmemeval_yesno_policy overrides configuration.yml."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="lenient")  # config says lenient
    policy = judge_stage._resolve_yesno_policy(
        {"judge": {"longmemeval_yesno_policy": "strict"}}, str(cfg_path)
    )
    assert policy == "strict"


def test_resolve_yesno_policy_falls_back_to_config(tmp_path):
    """run_cfg unset → read retrieval_agent.longmemeval_yesno_policy from yaml."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path, policy="strict")
    policy = judge_stage._resolve_yesno_policy({}, str(cfg_path))
    assert policy == "strict"


def test_resolve_yesno_policy_default_lenient_when_unset(tmp_path):
    """Both unset → Pydantic default 'lenient'."""
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path)  # no policy field
    policy = judge_stage._resolve_yesno_policy({}, str(cfg_path))
    assert policy == "lenient"


def test_resolve_yesno_policy_invalid_run_cfg_raises(tmp_path):
    cfg_path = tmp_path / "cfg.yml"
    _write_minimal_cfg(cfg_path)
    with pytest.raises(ValueError, match=r"must be 'lenient' or 'strict'"):
        judge_stage._resolve_yesno_policy(
            {"judge": {"longmemeval_yesno_policy": "loose"}}, str(cfg_path)
        )


def test_run_logs_yesno_policy(monkeypatch, tmp_path, capsys):
    """`[judge] ... longmemeval_yesno_policy=...` must appear in stdout."""
    out_dir = _write_rows(
        tmp_path,
        [
            {
                "question": "q",
                "category": "multi-session",
                "question_id": "qid_1",
                "golden_answer": "a",
                "model_answer": "yes",
            }
        ],
    )
    _patch_common(monkeypatch, tmp_path, out_dir)

    import evaluation.retrieval_agent.llm_judge as lm

    monkeypatch.setattr(
        lm, "create_judge_fn", lambda _path, json_mode=True: lambda _p: "yes"
    )
    monkeypatch.setattr(
        lm,
        "evaluate_llm_judge_longmemeval_with_details",
        lambda **_kw: {
            "score": 1,
            "raw_response": "yes",
            "parsed_label": "yes",
            "attempts": 1,
        },
    )
    monkeypatch.setattr(
        lm,
        "evaluate_llm_judge_with_details",
        lambda **_kw: {
            "score": 0,
            "raw_response": '{"label":"WRONG"}',
            "parsed_label": "WRONG",
            "attempts": 1,
        },
    )

    judge_stage.run(
        {
            "run_name": "test_run",
            "configuration": {"generated_path": "x"},
            "judge": {"longmemeval_yesno_policy": "strict"},
        }
    )

    out = capsys.readouterr().out
    assert "longmemeval_yesno_policy=strict" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
