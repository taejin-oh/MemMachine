from typing import Any

import pytest
import yaml

from memmachine_server.common.configuration.episodic_config import (
    EpisodicMemoryConfPartial,
    LongTermMemoryConfPartial,
)


@pytest.fixture
def episodic_memory_conf() -> dict[str, Any]:
    return {
        "long_term_memory": {
            "embedder": "my_embedder",
            "reranker": "my_reranker",
            "vector_graph_store": "my_neo4j",
        },
        "short_term_memory": {
            "llm_model": "my_model",
            "message_capacity": 500,
        },
    }


def test_episodic_config_to_yaml(episodic_memory_conf):
    conf = EpisodicMemoryConfPartial(**episodic_memory_conf)
    yaml_str = conf.to_yaml()
    conf_cp = EpisodicMemoryConfPartial(**yaml.safe_load(yaml_str))
    assert conf_cp == conf
    assert conf_cp.long_term_memory == conf.long_term_memory
    assert conf_cp.short_term_memory is not None
    assert conf_cp.short_term_memory == conf.short_term_memory
    assert conf_cp.short_term_memory.llm_model == "my_model"


def _ltm_partial(**overrides: Any) -> LongTermMemoryConfPartial:
    base: dict[str, Any] = {
        "session_id": "s",
        "vector_graph_store": "v",
        "embedder": "e",
        "reranker": "r",
    }
    base.update(overrides)
    return LongTermMemoryConfPartial(**base)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, False),
        ({"message_sentence_chunking": False}, False),
        ({"message_sentence_chunking": True}, True),
    ],
)
def test_message_sentence_chunking_merges_into_full_conf(overrides, expected):
    full = _ltm_partial(**overrides).merge(LongTermMemoryConfPartial())
    assert full.message_sentence_chunking is expected


def test_message_sentence_chunking_round_trips_through_yaml():
    conf = EpisodicMemoryConfPartial(
        long_term_memory={
            "embedder": "my_embedder",
            "reranker": "my_reranker",
            "vector_graph_store": "my_neo4j",
            "message_sentence_chunking": True,
        }
    )
    reloaded = EpisodicMemoryConfPartial(**yaml.safe_load(conf.to_yaml()))
    assert reloaded.long_term_memory is not None
    assert reloaded.long_term_memory.message_sentence_chunking is True


def test_message_sentence_chunking_omitted_yaml_is_none_in_partial():
    conf = EpisodicMemoryConfPartial(
        long_term_memory={
            "embedder": "my_embedder",
            "reranker": "my_reranker",
            "vector_graph_store": "my_neo4j",
        }
    )
    assert conf.long_term_memory is not None
    assert conf.long_term_memory.message_sentence_chunking is None


def _stm_partial(**overrides: Any):
    from memmachine_server.common.configuration.episodic_config import (
        ShortTermMemoryConfPartial,
    )

    base: dict[str, Any] = {
        "session_key": "s",
        "llm_model": "m",
        "summary_prompt_system": "sys",
        "summary_prompt_user": "user {episodes} {summary} {max_length}",
    }
    base.update(overrides)
    return ShortTermMemoryConfPartial(**base)


def test_summarization_enabled_defaults_to_true_after_merge():
    """Regression guard: default must preserve original always-on behavior."""
    from memmachine_server.common.configuration.episodic_config import (
        ShortTermMemoryConfPartial,
    )

    full = _stm_partial().merge(ShortTermMemoryConfPartial())
    assert full.summarization_enabled is True


def test_summarization_enabled_false_overrides_default():
    from memmachine_server.common.configuration.episodic_config import (
        ShortTermMemoryConfPartial,
    )

    full = _stm_partial(summarization_enabled=False).merge(
        ShortTermMemoryConfPartial()
    )
    assert full.summarization_enabled is False


def test_summarization_enabled_partial_omitted_is_none():
    conf = _stm_partial()
    assert conf.summarization_enabled is None
