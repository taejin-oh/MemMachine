"""Unit tests for model profile judge_llm validation in generate_config.

Run:
    pytest scripts/test_generate_config_judge.py -v
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

from scripts.generate_config import (  # noqa: E402
    _validate_judge_llm,
    build_configuration_yml,
)
from scripts.stages.judge import _judge_config_path  # noqa: E402

# Local fixtures (intentionally NOT imported from test_generate_config_rerankers.py
# to avoid coupling between test files; small enough to copy).
_DB_PROFILE = {
    "vector_graph_store": {
        "id": "n",
        "provider": "neo4j",
        "config": {"uri": "bolt://x", "user": "u", "password": "p"},
    },
    "profile_storage": {
        "id": "p",
        "provider": "postgres",
        "config": {
            "host": "x",
            "port": 5432,
            "user": "u",
            "password": "p",
            "db_name": "n",
        },
    },
}

_BASE_MODEL = {
    "embedder": {
        "id": "e",
        "provider": "openai",
        "config": {"api_key": "x", "model": "m", "dimensions": 1536},
    },
    "rerankers": [{"id": "r", "provider": "bm25", "config": {}}],
    "llm_model": {
        "id": "answer_llm",
        "provider": "openai-responses",
        "config": {"api_key": "x", "model": "gpt-4o-mini"},
    },
}


def _model(judge=None):
    profile = dict(_BASE_MODEL)
    if judge is not None:
        profile["judge_llm"] = judge
    return profile


# ---------------------------------------------------------------------------
# build_configuration_yml + _validate_judge_llm
# ---------------------------------------------------------------------------


def test_judge_llm_omitted_falls_back_to_answer_llm():
    cfg = build_configuration_yml(_model(), _DB_PROFILE)
    assert cfg["retrieval_agent"]["llm_model"] == "answer_llm"
    assert cfg["retrieval_agent"]["judge_llm_model"] == "answer_llm"
    assert list(cfg["resources"]["language_models"]) == ["answer_llm"]


def test_judge_llm_present_emits_separate_entry():
    judge = {
        "id": "judge_llm",
        "provider": "openai-chat-completions",
        "config": {"api_key": "y", "base_url": "https://judge", "model": "gpt-4o"},
    }
    cfg = build_configuration_yml(_model(judge), _DB_PROFILE)
    assert cfg["retrieval_agent"]["llm_model"] == "answer_llm"
    assert cfg["retrieval_agent"]["judge_llm_model"] == "judge_llm"
    assert sorted(cfg["resources"]["language_models"]) == ["answer_llm", "judge_llm"]
    assert cfg["resources"]["language_models"]["judge_llm"] == {
        "provider": "openai-chat-completions",
        "config": {"api_key": "y", "base_url": "https://judge", "model": "gpt-4o"},
    }


def test_judge_llm_same_id_same_config_no_double_insert():
    judge = {
        "id": "answer_llm",
        "provider": "openai-responses",
        "config": {"api_key": "x", "model": "gpt-4o-mini"},
    }
    cfg = build_configuration_yml(_model(judge), _DB_PROFILE)
    assert cfg["retrieval_agent"]["judge_llm_model"] == "answer_llm"
    assert list(cfg["resources"]["language_models"]) == ["answer_llm"]


def test_judge_llm_same_id_provider_mismatch_raises():
    judge = {
        "id": "answer_llm",
        "provider": "openai-chat-completions",
        "config": {"api_key": "x", "model": "gpt-4o-mini"},
    }
    with pytest.raises(ValueError, match=r"conflicts with llm_model id"):
        build_configuration_yml(_model(judge), _DB_PROFILE)


def test_judge_llm_same_id_config_mismatch_raises():
    judge = {
        "id": "answer_llm",
        "provider": "openai-responses",
        "config": {"api_key": "x", "model": "gpt-4o"},
    }
    with pytest.raises(ValueError, match=r"conflicts with llm_model id"):
        build_configuration_yml(_model(judge), _DB_PROFILE)


def test_judge_llm_missing_id_raises():
    with pytest.raises(ValueError, match=r"missing required 'id'"):
        _validate_judge_llm(
            _model({"provider": "openai-responses", "config": {}}),
            _BASE_MODEL["llm_model"],
        )


def test_judge_llm_missing_provider_raises():
    with pytest.raises(ValueError, match=r"missing required 'provider'"):
        _validate_judge_llm(_model({"id": "j"}), _BASE_MODEL["llm_model"])


def test_judge_llm_config_not_mapping_raises():
    with pytest.raises(ValueError, match=r"config must be a mapping"):
        _validate_judge_llm(
            _model({"id": "j", "provider": "openai-responses", "config": "no"}),
            _BASE_MODEL["llm_model"],
        )


def test_judge_llm_not_a_mapping_raises():
    with pytest.raises(ValueError, match=r"must be a mapping"):
        _validate_judge_llm(_model("plain-string"), _BASE_MODEL["llm_model"])


def test_judge_llm_omitted_returns_none():
    assert _validate_judge_llm(_model(), _BASE_MODEL["llm_model"]) is None


# ---------------------------------------------------------------------------
# _judge_config_path (regression-critical: never touches retrieval_agent.llm_model)
# ---------------------------------------------------------------------------


def _write_config(path: Path) -> None:
    cfg = {
        "retrieval_agent": {
            "llm_model": "answer_llm",
            "judge_llm_model": "judge_llm",
        },
        "resources": {
            "language_models": {
                "answer_llm": {"provider": "openai-responses", "config": {}},
                "judge_llm": {"provider": "openai-responses", "config": {}},
                "other_judge_llm": {"provider": "openai-responses", "config": {}},
            }
        },
    }
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def _run_cfg(tmp_path: Path, llm_model_id: str | None) -> dict:
    return {
        "run_name": "test_judge_run",
        "results_dir": str(tmp_path),
        "judge": {"llm_model_id": llm_model_id} if llm_model_id else {},
    }


def test_judge_stage_swap_target_is_judge_llm_model(tmp_path):
    base = tmp_path / "configuration.yml"
    _write_config(base)
    run_cfg = _run_cfg(tmp_path, "other_judge_llm")
    swapped_path = _judge_config_path(run_cfg, str(base))
    swapped = yaml.safe_load(Path(swapped_path).read_text())
    # Critical regression check: judge swap must NEVER touch the answer pointer.
    assert swapped["retrieval_agent"]["judge_llm_model"] == "other_judge_llm"
    assert swapped["retrieval_agent"]["llm_model"] == "answer_llm"


def test_judge_stage_swap_unknown_id_raises(tmp_path):
    base = tmp_path / "configuration.yml"
    _write_config(base)
    run_cfg = _run_cfg(tmp_path, "nonexistent")
    with pytest.raises(ValueError, match=r"is not defined under "):
        _judge_config_path(run_cfg, str(base))


def test_judge_stage_no_swap_when_unset(tmp_path):
    base = tmp_path / "configuration.yml"
    _write_config(base)
    run_cfg = _run_cfg(tmp_path, None)
    assert _judge_config_path(run_cfg, str(base)) == str(base)


# ---------------------------------------------------------------------------
# Configuration schema roundtrip (Pydantic accepts the new field)
# ---------------------------------------------------------------------------


def _sample_config_path() -> Path:
    return REPO_ROOT / "sample_configs" / "episodic_memory_config.cpu.sample"


def test_schema_roundtrip_judge_llm_model_parsed(tmp_path):
    """Configuration.load_yml_file() preserves retrieval_agent.judge_llm_model."""
    from memmachine_server.common.configuration import Configuration

    base = yaml.safe_load(_sample_config_path().read_text())
    base.setdefault("retrieval_agent", {})["judge_llm_model"] = "openai_model"
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.judge_llm_model == "openai_model"


def test_schema_roundtrip_answer_llm_model_preserved(tmp_path):
    """Setting judge_llm_model must not alter retrieval_agent.llm_model on parse."""
    from memmachine_server.common.configuration import Configuration

    base = yaml.safe_load(_sample_config_path().read_text())
    answer_id = base["retrieval_agent"]["llm_model"]
    base["retrieval_agent"]["judge_llm_model"] = "ollama_model"
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.llm_model == answer_id
    assert conf.retrieval_agent.judge_llm_model == "ollama_model"


def test_schema_roundtrip_judge_llm_model_default_none(tmp_path):
    """Existing configuration.yml without judge_llm_model parses with None default."""
    from memmachine_server.common.configuration import Configuration

    fixture = tmp_path / "configuration.yml"
    fixture.write_text(_sample_config_path().read_text())

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.judge_llm_model is None


# ---------------------------------------------------------------------------
# longmemeval_yesno_policy: schema roundtrip + generate_config CLI mapping
# ---------------------------------------------------------------------------


def test_schema_roundtrip_longmemeval_yesno_policy_default_lenient(tmp_path):
    """Sample config without the field defaults to 'lenient' (upstream behavior)."""
    from memmachine_server.common.configuration import Configuration

    fixture = tmp_path / "configuration.yml"
    fixture.write_text(_sample_config_path().read_text())

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.longmemeval_yesno_policy == "lenient"


def test_schema_roundtrip_longmemeval_yesno_policy_strict_preserved(tmp_path):
    from memmachine_server.common.configuration import Configuration

    base = yaml.safe_load(_sample_config_path().read_text())
    base.setdefault("retrieval_agent", {})["longmemeval_yesno_policy"] = "strict"
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.longmemeval_yesno_policy == "strict"


def test_schema_roundtrip_longmemeval_yesno_policy_invalid_raises(tmp_path):
    """Pydantic Literal rejects values outside {'lenient', 'strict'}."""
    from memmachine_server.common.configuration import Configuration

    base = yaml.safe_load(_sample_config_path().read_text())
    base.setdefault("retrieval_agent", {})["longmemeval_yesno_policy"] = "loose"
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    with pytest.raises(Exception):  # pydantic.ValidationError
        Configuration.load_yml_file(str(fixture))


def _parse_args(argv: list[str]):
    """Run scripts.generate_config.parse_args() with a custom argv."""
    import scripts.generate_config as gc

    saved = sys.argv
    sys.argv = ["generate_config.py", *argv]
    try:
        return gc.parse_args()
    finally:
        sys.argv = saved


def test_cli_longmemeval_yesno_policy_lenient_maps_to_run_cfg():
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(
        ["--problem", "4", "--run-name", "x", "--longmemeval-yesno-policy", "lenient"]
    )
    out = cli_to_overrides(args)
    assert out["judge"]["longmemeval_yesno_policy"] == "lenient"


def test_cli_longmemeval_yesno_policy_strict_maps_to_run_cfg():
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(
        ["--problem", "4", "--run-name", "x", "--longmemeval-yesno-policy", "strict"]
    )
    out = cli_to_overrides(args)
    assert out["judge"]["longmemeval_yesno_policy"] == "strict"


def test_cli_longmemeval_yesno_policy_unset_omits_key():
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(["--problem", "4", "--run-name", "x"])
    out = cli_to_overrides(args)
    assert "judge" not in out or "longmemeval_yesno_policy" not in out.get(
        "judge", {}
    )


def test_cli_judge_model_and_yesno_policy_share_judge_dict():
    """--judge-model and --longmemeval-yesno-policy must coexist under one judge dict."""
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(
        [
            "--problem",
            "4",
            "--run-name",
            "x",
            "--judge-model",
            "judge_llm",
            "--longmemeval-yesno-policy",
            "strict",
        ]
    )
    out = cli_to_overrides(args)
    assert out["judge"] == {
        "llm_model_id": "judge_llm",
        "longmemeval_yesno_policy": "strict",
    }


def test_cli_invalid_yesno_policy_rejected():
    """argparse choices=['lenient','strict'] must reject other values."""
    with pytest.raises(SystemExit):
        _parse_args(
            [
                "--problem",
                "4",
                "--run-name",
                "x",
                "--longmemeval-yesno-policy",
                "loose",
            ]
        )


# ---------------------------------------------------------------------------
# longmemeval_answer_prompt: schema roundtrip + generate_config CLI mapping (v0.6)
# ---------------------------------------------------------------------------


def test_schema_roundtrip_longmemeval_answer_prompt_default(tmp_path):
    """Sample config without the field defaults to 'memmachine_original' (upstream)."""
    from memmachine_server.common.configuration import Configuration

    fixture = tmp_path / "configuration.yml"
    fixture.write_text(_sample_config_path().read_text())

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.longmemeval_answer_prompt == "memmachine_original"


def test_schema_roundtrip_longmemeval_answer_prompt_agent_lightning_preserved(tmp_path):
    from memmachine_server.common.configuration import Configuration

    base = yaml.safe_load(_sample_config_path().read_text())
    base.setdefault("retrieval_agent", {})["longmemeval_answer_prompt"] = (
        "agent_lightning"
    )
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    conf = Configuration.load_yml_file(str(fixture))
    assert conf.retrieval_agent.longmemeval_answer_prompt == "agent_lightning"


def test_schema_roundtrip_longmemeval_answer_prompt_invalid_raises(tmp_path):
    """Pydantic Literal rejects values outside the registered set."""
    from pydantic import ValidationError

    from memmachine_server.common.configuration import Configuration

    base = yaml.safe_load(_sample_config_path().read_text())
    base.setdefault("retrieval_agent", {})["longmemeval_answer_prompt"] = "typo"
    fixture = tmp_path / "configuration.yml"
    fixture.write_text(yaml.safe_dump(base))

    with pytest.raises(ValidationError, match=r"longmemeval_answer_prompt"):
        Configuration.load_yml_file(str(fixture))


def test_cli_longmemeval_answer_prompt_memmachine_original_maps_to_run_cfg():
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(
        [
            "--problem",
            "4",
            "--run-name",
            "x",
            "--longmemeval-answer-prompt",
            "memmachine_original",
        ]
    )
    out = cli_to_overrides(args)
    assert out["evaluation"]["longmemeval"]["answer_prompt"] == "memmachine_original"


def test_cli_longmemeval_answer_prompt_agent_lightning_maps_to_run_cfg():
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(
        [
            "--problem",
            "4",
            "--run-name",
            "x",
            "--longmemeval-answer-prompt",
            "agent_lightning",
        ]
    )
    out = cli_to_overrides(args)
    assert out["evaluation"]["longmemeval"]["answer_prompt"] == "agent_lightning"


def test_cli_longmemeval_answer_prompt_unset_omits_key():
    from scripts.generate_config import cli_to_overrides

    args = _parse_args(["--problem", "4", "--run-name", "x"])
    out = cli_to_overrides(args)
    longmemeval = (out.get("evaluation") or {}).get("longmemeval") or {}
    assert "answer_prompt" not in longmemeval


def test_cli_invalid_answer_prompt_rejected():
    """argparse choices must reject unknown policies."""
    with pytest.raises(SystemExit):
        _parse_args(
            [
                "--problem",
                "4",
                "--run-name",
                "x",
                "--longmemeval-answer-prompt",
                "typo",
            ]
        )
