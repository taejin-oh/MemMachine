"""Tests for sweep-key validation in scripts/stages/retrieve.py.

`message_sentence_chunking` affects how episodes are stored at ingest time
(see packages/server/.../declarative_memory.py). Toggling it per sweep cell
without re-ingest produces A/B comparisons over the same chunked corpus,
which is meaningless. The validator must reject such sweeps with a clear,
actionable error before any cell runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.stages.retrieve import (  # noqa: E402
    _apply_cell_to_config,
    _expand_sweep,
    _resolved_params,
)


def test_chunking_in_sweep_raises_systemexit():
    sweep = {"message_sentence_chunking": [True, False]}
    with pytest.raises(SystemExit) as excinfo:
        _expand_sweep(sweep)
    msg = str(excinfo.value)
    assert "message_sentence_chunking" in msg
    assert "ingest" in msg.lower()
    assert "fixed" in msg.lower()


def test_chunking_in_sweep_alongside_legit_keys_still_raises():
    sweep = {
        "search_limit": [10, 20],
        "message_sentence_chunking": [True, False],
    }
    with pytest.raises(SystemExit) as excinfo:
        _expand_sweep(sweep)
    assert "message_sentence_chunking" in str(excinfo.value)


def test_legit_sweep_keys_pass_validation():
    sweep = {
        "search_limit": [10, 20, 30],
        "prepend_user_prefix": [False, True],
    }
    cells = _expand_sweep(sweep)
    assert len(cells) == 6  # 3 x 2 cartesian


def test_summarization_enabled_in_sweep_raises_systemexit():
    """summarization_enabled is config-only -- the eval path runs
    short_term_memory=None so toggling it produces no score change. The
    validator rejects it from sweep so operators do not generate a
    misleading identical-cell matrix; fixed: is still allowed."""
    sweep = {"summarization_enabled": [True, False]}
    with pytest.raises(SystemExit) as excinfo:
        _expand_sweep(sweep)
    msg = str(excinfo.value)
    assert "summarization_enabled" in msg
    assert "config-only" in msg.lower()


def test_summarization_enabled_in_fixed_remains_supported():
    """Sanity: validator scope is sweep keys only; fixed.summarization_enabled
    still flows through _resolved_params + _apply_cell_to_config."""
    cells = _expand_sweep({})
    fixed_cfg = {"fixed": {"summarization_enabled": True}}
    params = _resolved_params(fixed_cfg, cells[0])
    assert params == {"summarization_enabled": True}


def test_empty_sweep_returns_single_empty_cell():
    assert _expand_sweep({}) == [{}]


def test_apply_cell_to_config_no_longer_writes_fixed_only_keys(tmp_path, monkeypatch):
    """Fixed-only keys (chunking, summarization_enabled) are written once at
    generate time; per-cell apply must not reapply them (would be a no-op
    but obscures the contract)."""
    from scripts.stages import _common as cm

    written: list[dict] = []

    def fake_update_yaml_in_place(path, updates):
        written.append(updates)

    monkeypatch.setattr(cm, "update_yaml_in_place", fake_update_yaml_in_place)

    # Simulate fixed.message_sentence_chunking + fixed.summarization_enabled
    # flowing into params via _resolved_params. Neither must touch
    # episodic_memory in the per-cell update.
    _apply_cell_to_config(
        "/dev/null",
        {
            "message_sentence_chunking": True,
            "summarization_enabled": True,
            "prepend_user_prefix": True,
        },
    )
    assert len(written) == 1
    assert "episodic_memory" not in written[0]
    assert written[0]["evaluation"]["longmemeval"]["prepend_user_prefix"] is True
