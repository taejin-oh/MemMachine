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


def _ns(**overrides):
    """Build an argparse.Namespace with all parse_args attrs defaulting to None."""
    import argparse

    defaults = {
        "problem": None,
        "run_name": None,
        "model_profile": None,
        "db_profile": None,
        "use_existing_config": None,
        "k_list": None,
        "judge_model": None,
        "longmemeval_yesno_policy": None,
        "longmemeval_answer_prompt": None,
        "length": None,
        "n_runs": None,
        "reuse_run": None,
        "from_json": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_load_longmemeval_local_normalizes_and_truncates(tmp_path):
    """Local JSON loader respects min(length, len(records)) and applies the
    same normalize as longmemeval_test.load_longmemeval_dataset()."""
    import json

    from scripts.stages._common import load_longmemeval_local

    fixture = [
        {"question": "q1", "answer": "a1", "haystack_sessions": [["s1"]]},
        # missing haystack_sessions / question_type → must be filled in
        {"question": "q2", "answer": "a2"},
        # third row cut by length=2
        {"question": "q3", "answer": "a3"},
    ]
    fp = tmp_path / "lme.json"
    fp.write_text(json.dumps(fixture))

    out = load_longmemeval_local(fp, length=2, split="myslice")
    assert len(out) == 2
    assert out[0]["question"] == "q1"
    assert out[0]["question_type"] == "unknown"
    assert out[0]["split"] == "myslice"
    assert out[1]["haystack_sessions"] == []
    assert out[1]["question_type"] == "unknown"


def test_load_longmemeval_local_rejects_non_list(tmp_path):
    import json

    from scripts.stages._common import load_longmemeval_local

    fp = tmp_path / "bad.json"
    fp.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(TypeError, match=r"Expected list"):
        load_longmemeval_local(fp, length=1)


def test_load_longmemeval_local_length_exceeds_returns_all(tmp_path):
    import json

    from scripts.stages._common import load_longmemeval_local

    fp = tmp_path / "small.json"
    fp.write_text(json.dumps([{"question": "q", "answer": "a"}]))
    out = load_longmemeval_local(fp, length=999)
    assert len(out) == 1


def test_load_longmemeval_local_preserves_question_date(tmp_path):
    """Local loader must keep question_date verbatim — both LME_origin_prompt
    and memmachine_original answer-prompt policies render this into the
    'Current date:' line via _format_question_date(). Parity with
    evaluation/retrieval_agent/longmemeval_test.py:load_longmemeval_dataset()
    normalization."""
    import json

    from scripts.stages._common import load_longmemeval_local

    fp = tmp_path / "with_date.json"
    fp.write_text(
        json.dumps(
            [
                {
                    "question": "q",
                    "answer": "a",
                    "question_date": "2023/04/10 (Mon) 23:07",
                }
            ]
        )
    )
    out = load_longmemeval_local(fp, length=1)
    assert out[0]["question_date"] == "2023/04/10 (Mon) 23:07"


def test_load_longmemeval_local_question_date_missing_defaults_empty(tmp_path):
    """Synthetic fixtures often omit question_date. Local loader must default
    to '' so the answer prompt's 'Current date:' line stays renderable
    (str.format won't KeyError)."""
    import json

    from scripts.stages._common import load_longmemeval_local

    fp = tmp_path / "no_date.json"
    fp.write_text(json.dumps([{"question": "q", "answer": "a"}]))
    out = load_longmemeval_local(fp, length=1)
    assert out[0]["question_date"] == ""


def test_load_longmemeval_local_question_date_none_normalizes_to_empty(tmp_path):
    """When the JSON contains ``question_date: null`` (HF cleaned dump occasionally
    has this), the loader must coerce it to '' instead of leaving the literal
    None — otherwise format() would render the string 'None' as the date."""
    import json

    from scripts.stages._common import load_longmemeval_local

    fp = tmp_path / "null_date.json"
    fp.write_text(json.dumps([{"question": "q", "answer": "a", "question_date": None}]))
    out = load_longmemeval_local(fp, length=1)
    assert out[0]["question_date"] == ""
