import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for extra in (
    REPO_ROOT,
    REPO_ROOT / "packages" / "common" / "src",
    REPO_ROOT / "packages" / "server" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from evaluation.retrieval_agent import evaluate  # noqa: E402


class DummyFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class DummyExecutor:
    def __init__(self, *args, **kwargs):
        self._futures = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args):
        future = DummyFuture(fn(*args))
        self._futures.append(future)
        return future


def _run_main_with_data(
    monkeypatch,
    tmp_path: Path,
    data: dict,
    create_judge_fn,
    extra_argv: list[str] | None = None,
    yesno_policy_override: str | None = "lenient",
):
    data_path = tmp_path / "input.json"
    target_path = tmp_path / "output.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(evaluate, "create_judge_fn", create_judge_fn)
    monkeypatch.setattr(
        evaluate.concurrent.futures, "ThreadPoolExecutor", DummyExecutor
    )
    monkeypatch.setattr(
        evaluate.concurrent.futures, "as_completed", lambda futures: futures
    )
    monkeypatch.setattr(evaluate, "tqdm", lambda iterable, total: iterable)
    # Stub policy resolution so tests don't need a real configuration.yml.
    # Pass yesno_policy_override=None to exercise the real resolver.
    if yesno_policy_override is not None:
        monkeypatch.setattr(
            evaluate,
            "_resolve_yesno_policy",
            lambda _args, _path: yesno_policy_override,
        )

    argv = [
        "evaluate.py",
        "--data-path",
        str(data_path),
        "--target-path",
        str(target_path),
        "--config-path",
        "dummy-config.yml",
        "--max_workers",
        "1",
    ]
    if extra_argv:
        argv.extend(extra_argv)
    monkeypatch.setattr("sys.argv", argv)

    evaluate.main()


def test_main_skips_text_mode_judge_when_no_longmemeval(monkeypatch, tmp_path):
    calls = []

    def fake_create_judge_fn(config_path: str, json_mode: bool = True):
        calls.append((config_path, json_mode))
        return lambda _prompt: "1"

    data = {
        "group": [
            {
                "question": "q",
                "golden_answer": "a",
                "model_answer": "r",
                "category": "1",
            }
        ]
    }

    monkeypatch.setattr(evaluate, "evaluate_llm_judge", lambda *args: 1)
    _run_main_with_data(monkeypatch, tmp_path, data, fake_create_judge_fn)

    assert calls == [("dummy-config.yml", True)]


def test_main_initializes_text_mode_judge_for_longmemeval(monkeypatch, tmp_path):
    calls = []

    def fake_create_judge_fn(config_path: str, json_mode: bool = True):
        calls.append((config_path, json_mode))
        return lambda _prompt: "Yes"

    data = {
        "group": [
            {
                "question": "q",
                "golden_answer": "a",
                "model_answer": "r",
                "category": "temporal-reasoning",
            }
        ]
    }

    monkeypatch.setattr(evaluate, "evaluate_llm_judge_longmemeval", lambda *args: 1)
    _run_main_with_data(monkeypatch, tmp_path, data, fake_create_judge_fn)

    assert calls == [("dummy-config.yml", True), ("dummy-config.yml", False)]


# ---------------------------------------------------------------------------
# yesno policy: CLI override + config fallback
# ---------------------------------------------------------------------------


def _data_with_longmemeval():
    return {
        "group": [
            {
                "question": "q",
                "golden_answer": "a",
                "model_answer": "Yes, the answer matches",
                "category": "multi-session",
            }
        ]
    }


def test_main_passes_cli_yesno_policy_to_longmemeval_judge(monkeypatch, tmp_path):
    """--longmemeval-yesno-policy strict overrides the config default."""
    captured = {}

    def fake_lme(*args):
        # process_sample passes positional args; policy is the last one.
        captured["policy"] = args[-1]
        return 1

    monkeypatch.setattr(evaluate, "evaluate_llm_judge_longmemeval", fake_lme)
    _run_main_with_data(
        monkeypatch,
        tmp_path,
        _data_with_longmemeval(),
        lambda _p, json_mode=True: lambda _x: "Yes",
        extra_argv=["--longmemeval-yesno-policy", "strict"],
        # CLI override path: do NOT stub the resolver.
        yesno_policy_override=None,
    )
    assert captured["policy"] == "strict"


def test_main_falls_back_to_config_yesno_policy(monkeypatch, tmp_path):
    """When CLI flag is unset, retrieval_agent.longmemeval_yesno_policy is read."""
    import yaml

    sample = (
        REPO_ROOT / "sample_configs" / "episodic_memory_config.cpu.sample"
    ).read_text()
    base = yaml.safe_load(sample)
    base.setdefault("retrieval_agent", {})["longmemeval_yesno_policy"] = "strict"
    cfg_path = tmp_path / "configuration.yml"
    cfg_path.write_text(yaml.safe_dump(base))

    captured = {}

    def fake_lme(*args):
        captured["policy"] = args[-1]
        return 1

    monkeypatch.setattr(evaluate, "evaluate_llm_judge_longmemeval", fake_lme)

    # Replace the dummy --config-path with a real file.
    data_path = tmp_path / "input.json"
    target_path = tmp_path / "output.json"
    data_path.write_text(json.dumps(_data_with_longmemeval()), encoding="utf-8")

    monkeypatch.setattr(
        evaluate, "create_judge_fn", lambda _p, json_mode=True: lambda _x: "Yes"
    )
    monkeypatch.setattr(
        evaluate.concurrent.futures, "ThreadPoolExecutor", DummyExecutor
    )
    monkeypatch.setattr(
        evaluate.concurrent.futures, "as_completed", lambda futures: futures
    )
    monkeypatch.setattr(evaluate, "tqdm", lambda iterable, total: iterable)
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate.py",
            "--data-path",
            str(data_path),
            "--target-path",
            str(target_path),
            "--config-path",
            str(cfg_path),
            "--max_workers",
            "1",
        ],
    )

    evaluate.main()
    assert captured["policy"] == "strict"
