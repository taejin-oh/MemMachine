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

from scripts.stages import retrieve as stage_retrieve  # noqa: E402


def test_chunking_in_sweep_raises_systemexit():
    sweep = {"message_sentence_chunking": [True, False]}
    with pytest.raises(SystemExit) as excinfo:
        stage_retrieve._expand_sweep(sweep)
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
        stage_retrieve._expand_sweep(sweep)
    assert "message_sentence_chunking" in str(excinfo.value)


def test_legit_sweep_keys_pass_validation():
    sweep = {
        "search_limit": [10, 20, 30],
        "prepend_user_prefix": [False, True],
    }
    cells = stage_retrieve._expand_sweep(sweep)
    assert len(cells) == 6  # 3 x 2 cartesian


def test_summarization_enabled_in_sweep_is_allowed_by_validator():
    """summarization_enabled is config-only (eval path uses STM=None) but the
    *validator* itself does not reject it; Fix 5 handles it via warning +
    optional removal at the CLI/generation layer."""
    sweep = {"summarization_enabled": [True, False]}
    cells = stage_retrieve._expand_sweep(sweep)
    assert len(cells) == 2


def test_empty_sweep_returns_single_empty_cell():
    assert stage_retrieve._expand_sweep({}) == [{}]


def test_apply_cell_to_config_no_longer_writes_chunking(tmp_path, monkeypatch):
    """Chunking from `fixed` is written once at generate time; per-cell apply
    must not reapply it (would be a no-op but obscures the contract)."""
    from scripts.stages import _common as cm

    written: list[dict] = []

    def fake_update_yaml_in_place(path, updates):
        written.append(updates)

    monkeypatch.setattr(cm, "update_yaml_in_place", fake_update_yaml_in_place)

    # Simulate fixed.message_sentence_chunking flowing into params via
    # _resolved_params. _apply_cell_to_config must not touch the long_term_memory
    # block on this account.
    stage_retrieve._apply_cell_to_config(
        "/dev/null",
        {"message_sentence_chunking": True, "prepend_user_prefix": True},
    )
    assert len(written) == 1
    assert "long_term_memory" not in written[0].get("episodic_memory", {})
    assert (
        written[0]["evaluation"]["longmemeval"]["prepend_user_prefix"] is True
    )
