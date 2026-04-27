import pytest

from evaluation.retrieval_agent.locomo_search import (
    DEFAULT_CONCURRENCY,
    DEFAULT_LENGTH,
    build_parser,
)

BASE_ARGS = [
    "--data-path",
    "data.json",
    "--eval-result-path",
    "results.json",
    "--test-target",
    "retrieval_agent",
    "--config-path",
    "configuration.yml",
]


def test_locomo_search_concurrency_defaults_to_one():
    args = build_parser().parse_args(BASE_ARGS)

    assert args.concurrency == DEFAULT_CONCURRENCY == 1


def test_locomo_search_accepts_explicit_concurrency():
    args = build_parser().parse_args(BASE_ARGS + ["--concurrency", "3"])

    assert args.concurrency == 3


def test_locomo_search_rejects_non_positive_concurrency():
    with pytest.raises(SystemExit):
        build_parser().parse_args(BASE_ARGS + ["--concurrency", "0"])


def test_locomo_search_length_defaults_to_ten():
    args = build_parser().parse_args(BASE_ARGS)

    assert args.length == DEFAULT_LENGTH == 10


def test_locomo_search_accepts_explicit_length():
    args = build_parser().parse_args(BASE_ARGS + ["--length", "3"])

    assert args.length == 3


def test_locomo_search_rejects_non_positive_length():
    with pytest.raises(SystemExit):
        build_parser().parse_args(BASE_ARGS + ["--length", "0"])
