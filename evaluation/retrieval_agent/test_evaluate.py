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


def _run_main_with_data(monkeypatch, tmp_path: Path, data: dict, create_judge_fn):
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

    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate.py",
            "--data-path",
            str(data_path),
            "--target-path",
            str(target_path),
            "--config-path",
            "dummy-config.yml",
            "--max_workers",
            "1",
        ],
    )

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
