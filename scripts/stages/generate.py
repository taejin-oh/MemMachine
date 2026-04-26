"""Stage: generate.

Per DECISIONS.md D-005, the retrieve stage already emits generate.jsonl in the
same loop. This module verifies that file exists and reports row count. It also
hosts the EDWIN prompt-loading hook (DECISIONS.md D-003) for future use:
right now the hook only validates the prompt file exists and is non-empty
(comments stripped). Actual prompt application is intentionally not implemented
until EDWIN texts are provided.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as cm


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")).strip()


def _check_prompt_hook(run_cfg: dict[str, Any]) -> str:
    prompt_file = run_cfg.get("prompts", {}).get("generate_prompt_file")
    if not prompt_file:
        return "fallback (no prompt file configured — using built-in ANSWER_PROMPT)"
    p = (cm.REPO_ROOT / prompt_file).resolve()
    if not p.exists():
        return f"fallback (prompt file missing: {p})"
    body = _strip_comments(p.read_text(encoding="utf-8"))
    if not body:
        return f"fallback (prompt file empty after stripping comments: {p})"
    # Future work: actually inject this prompt. See DECISIONS.md D-003.
    return f"prompt loaded but NOT yet applied (future work): {p}"


def run(run_cfg: dict[str, Any]) -> Path:
    out_dir = cm.results_dir_for(run_cfg)
    generate_path = out_dir / "generate.jsonl"
    retrieve_path = out_dir / "retrieve.jsonl"

    if not retrieve_path.exists():
        raise FileNotFoundError(
            f"retrieve.jsonl missing: {retrieve_path}\n"
            "Run --stage retrieve first (it emits generate.jsonl in the same loop)."
        )
    if not generate_path.exists():
        raise FileNotFoundError(
            f"generate.jsonl missing: {generate_path}\n"
            "Expected to be emitted by the retrieve stage. See DECISIONS.md D-005."
        )

    rows = cm.read_jsonl(generate_path)
    print(f"[generate] ok — {generate_path} has {len(rows)} rows")
    print(f"[generate] EDWIN prompt hook: {_check_prompt_hook(run_cfg)}")
    return generate_path
