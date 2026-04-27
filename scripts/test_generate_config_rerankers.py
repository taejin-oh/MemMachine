"""Unit tests for model profile reranker validation in generate_config.

Run:
    pytest scripts/test_generate_config_rerankers.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_config import (  # noqa: E402
    _validate_and_normalize_rerankers,
    build_configuration_yml,
)

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
    "llm_model": {
        "id": "l",
        "provider": "openai-responses",
        "config": {"api_key": "x", "model": "gpt-4o-mini"},
    },
}


def _model(rerankers, primary=None):
    profile = dict(_BASE_MODEL)
    profile["rerankers"] = rerankers
    if primary is not None:
        profile["primary_reranker"] = primary
    return profile


def test_single_reranker_auto_primary():
    profile = _model([{"id": "my_bm25", "provider": "bm25", "config": {}}])
    cfg = build_configuration_yml(profile, _DB_PROFILE)
    assert cfg["episodic_memory"]["long_term_memory"]["reranker"] == "my_bm25"
    assert cfg["retrieval_agent"]["reranker"] == "my_bm25"
    assert list(cfg["resources"]["rerankers"]) == ["my_bm25"]
    assert cfg["resources"]["rerankers"]["my_bm25"] == {
        "provider": "bm25",
        "config": {},
    }


def test_explicit_primary_selects_id():
    profile = _model(
        [
            {"id": "my_bm25", "provider": "bm25", "config": {}},
            {"id": "my_identity", "provider": "identity", "config": {}},
            {
                "id": "my_hybrid",
                "provider": "rrf-hybrid",
                "config": {"reranker_ids": ["my_bm25", "my_identity"], "k": 60},
            },
        ],
        primary="my_hybrid",
    )
    cfg = build_configuration_yml(profile, _DB_PROFILE)
    assert cfg["episodic_memory"]["long_term_memory"]["reranker"] == "my_hybrid"
    assert cfg["retrieval_agent"]["reranker"] == "my_hybrid"
    assert sorted(cfg["resources"]["rerankers"]) == [
        "my_bm25",
        "my_hybrid",
        "my_identity",
    ]


def test_primary_not_in_rerankers_raises():
    profile = _model(
        [{"id": "my_bm25", "provider": "bm25", "config": {}}],
        primary="nonexistent",
    )
    with pytest.raises(ValueError, match="primary_reranker='nonexistent'"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_legacy_reranker_dict_migration_message():
    profile = dict(_BASE_MODEL)
    profile["reranker"] = {"id": "my_bm25", "provider": "bm25", "config": {}}
    with pytest.raises(ValueError, match=r"schema changed.*rerankers:"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_duplicate_reranker_id_raises():
    profile = _model(
        [
            {"id": "dup", "provider": "bm25", "config": {}},
            {"id": "dup", "provider": "identity", "config": {}},
        ]
    )
    with pytest.raises(ValueError, match="duplicate id"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_rrf_hybrid_unknown_ref_raises():
    profile = _model(
        [
            {"id": "my_bm25", "provider": "bm25", "config": {}},
            {
                "id": "my_hybrid",
                "provider": "rrf-hybrid",
                "config": {"reranker_ids": ["my_bm25", "ghost"]},
            },
        ],
        primary="my_hybrid",
    )
    with pytest.raises(ValueError, match="references unknown id 'ghost'"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_rrf_hybrid_self_reference_raises():
    profile = _model(
        [
            {"id": "my_bm25", "provider": "bm25", "config": {}},
            {
                "id": "my_hybrid",
                "provider": "rrf-hybrid",
                "config": {"reranker_ids": ["my_hybrid"]},
            },
        ],
        primary="my_hybrid",
    )
    with pytest.raises(ValueError, match="references itself"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_omitted_config_defaults_to_empty_dict():
    profile = _model([{"id": "my_bm25", "provider": "bm25"}])
    cfg = build_configuration_yml(profile, _DB_PROFILE)
    assert cfg["resources"]["rerankers"]["my_bm25"]["config"] == {}


def test_missing_id_or_provider_raises():
    with pytest.raises(ValueError, match="missing required 'id'"):
        _validate_and_normalize_rerankers(_model([{"provider": "bm25"}]))
    with pytest.raises(ValueError, match="missing required 'provider'"):
        _validate_and_normalize_rerankers(_model([{"id": "x"}]))


def test_empty_rerankers_raises():
    with pytest.raises(ValueError, match="non-empty list"):
        _validate_and_normalize_rerankers(_model([]))


def test_rrf_hybrid_empty_reranker_ids_raises():
    profile = _model(
        [
            {"id": "my_bm25", "provider": "bm25"},
            {
                "id": "my_hybrid",
                "provider": "rrf-hybrid",
                "config": {"reranker_ids": []},
            },
        ],
        primary="my_hybrid",
    )
    with pytest.raises(ValueError, match=r"non-empty config\.reranker_ids"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_rerankers_must_be_list():
    profile = dict(_BASE_MODEL)
    profile["rerankers"] = {"id": "my_bm25", "provider": "bm25"}
    with pytest.raises(ValueError, match=r"must be a list"):
        _validate_and_normalize_rerankers(profile)


def test_rerankers_none_raises():
    profile = dict(_BASE_MODEL)
    with pytest.raises(ValueError, match=r"must define 'rerankers'"):
        _validate_and_normalize_rerankers(profile)


def test_reranker_config_must_be_mapping():
    profile = _model([{"id": "my_bm25", "provider": "bm25", "config": "wrong"}])
    with pytest.raises(ValueError, match=r"config must be a mapping"):
        _validate_and_normalize_rerankers(profile)


def test_rrf_hybrid_reranker_ids_must_be_list_of_strings():
    profile = _model(
        [
            {"id": "my_bm25", "provider": "bm25"},
            {
                "id": "my_hybrid",
                "provider": "rrf-hybrid",
                "config": {"reranker_ids": "my_bm25"},
            },
        ],
        primary="my_hybrid",
    )
    with pytest.raises(ValueError, match=r"list of strings"):
        build_configuration_yml(profile, _DB_PROFILE)


def test_legacy_reranker_with_rerankers_present_raises():
    profile = dict(_BASE_MODEL)
    profile["reranker"] = {"id": "old", "provider": "bm25"}
    profile["rerankers"] = [{"id": "new", "provider": "bm25"}]
    with pytest.raises(ValueError, match=r"no longer supported"):
        _validate_and_normalize_rerankers(profile)


def test_summarization_default_false_in_generated_config():
    profile = _model([{"id": "my_bm25", "provider": "bm25", "config": {}}])
    cfg = build_configuration_yml(profile, _DB_PROFILE)
    stm = cfg["episodic_memory"]["short_term_memory"]
    assert stm["summarization_enabled"] is False


def test_summarization_fixed_override_true():
    from scripts.generate_config import _apply_fixed_to_configuration

    profile = _model([{"id": "my_bm25", "provider": "bm25", "config": {}}])
    cfg = build_configuration_yml(profile, _DB_PROFILE)
    _apply_fixed_to_configuration(cfg, {"summarization_enabled": True})
    assert cfg["episodic_memory"]["short_term_memory"]["summarization_enabled"] is True


def test_summarization_fixed_override_false_explicit():
    from scripts.generate_config import _apply_fixed_to_configuration

    profile = _model([{"id": "my_bm25", "provider": "bm25", "config": {}}])
    cfg = build_configuration_yml(profile, _DB_PROFILE)
    cfg["episodic_memory"]["short_term_memory"]["summarization_enabled"] = True
    _apply_fixed_to_configuration(cfg, {"summarization_enabled": False})
    assert cfg["episodic_memory"]["short_term_memory"]["summarization_enabled"] is False
