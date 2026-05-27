"""Shared helpers for `evaluation/longmemeval_v2/`.

Mirrors `evaluation/longmemeval/_common.py` (V1) but tailored to V2:

- V2 task categories: static / dynamic / procedure / gotchas (+ -abs
  abstention variants).
- V2 domains: web / enterprise. Each domain has its own system prompt.
- Answer extraction uses `\\boxed{...}` (V2 convention) — falls back to the
  full response when no boxed answer is present.

Only depends on `memmachine_server.*` (no `evaluation/retrieval_agent/`,
`evaluation/utils/` reach-in). Keeps the directory standalone — same
principle as V1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from memmachine_server.common.configuration import Configuration
from memmachine_server.common.language_model.language_model import LanguageModel
from memmachine_server.common.resource_manager.resource_manager import (
    ResourceManagerImpl,
)

# ---------------------------------------------------------------------------
# Domain system prompts (upstream xiaowu0162/LongMemEval-V2
# evaluation/harness.py:46-68 — verbatim wording).
# ---------------------------------------------------------------------------
DOMAIN_SYSTEM_PROMPTS: dict[str, str] = {
    "web": (
        "You are an experienced colleague in a web browsing environment that has "
        "a customized magento-based shopping website, a customized magento-based "
        "shopping admin cms website, as well as a customized forum website based "
        "on reddit/postmill. Answer based on your memory of the environment. "
        "If you do not know the answer, output exactly \\boxed{UNKNOWN}. "
        "Do not guess. Never attempt to guess an answer if you are not sure. "
        "If you believe the question's construction/premise is wrong, provide an "
        "explanation in \\boxed{} explaining why the question is flawed."
    ),
    "enterprise": (
        "You are an experienced colleague working in a customized ServiceNow "
        "environment. Answer based on your memory of the environment. "
        "If you do not know the answer, output exactly \\boxed{UNKNOWN}. "
        "Do not guess. Never attempt to guess an answer if you are not sure. "
        "If you believe the question's construction/premise is wrong, provide an "
        "explanation in \\boxed{} explaining why the question is flawed."
    ),
}


# ---------------------------------------------------------------------------
# Category map — upstream evaluation/harness.py:30-44.
# ---------------------------------------------------------------------------
CATEGORY_MAP: dict[str, str] = {
    "static-environment": "static",
    "static-environment-abs": "static-abs",
    "dynamic-environment": "dynamic",
    "dynamic-environment-abs": "dynamic-abs",
    "procedure": "procedure",
    "procedure-abs": "procedure-abs",
    "errors-gotchas": "gotchas",
}

NON_ABSTENTION_CATEGORIES = ("static", "dynamic", "procedure", "gotchas")
ABSTENTION_CATEGORIES = ("static-abs", "dynamic-abs", "procedure-abs")


def normalize_category(raw: str | None) -> str:
    """Map raw question category to its harness short name (or pass-through)."""
    if not raw:
        return "unknown"
    return CATEGORY_MAP.get(raw, raw)


# ---------------------------------------------------------------------------
# Boxed-answer extraction (upstream qa_eval_metrics.py:218-235 — verbatim).
# ---------------------------------------------------------------------------
def extract_boxed_answer(text: str) -> str:
    """Return the contents of the LAST `\\boxed{...}` (depth-aware)."""
    marker = "\\boxed{"
    idx = text.rfind(marker)
    if idx == -1:
        return text.strip()
    i = idx + len(marker)
    depth = 1
    out: list[str] = []
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
            out.append(ch)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip()


_UNKNOWN_RE = re.compile(r"^\s*unknown\s*$", re.IGNORECASE)


def is_unknown(boxed: str) -> bool:
    """True iff the boxed answer is literally `UNKNOWN` (case-insensitive)."""
    return bool(_UNKNOWN_RE.match(boxed or ""))


# ---------------------------------------------------------------------------
# Eval-config bootstrap (same shape as V1 _common.load_eval_config).
# ---------------------------------------------------------------------------
def load_eval_config(config_path: str) -> ResourceManagerImpl:
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"MemMachine configuration.yml not found at {config_path!r}. "
            "Copy example_configuration.yml and fill in DB credentials."
        )
    config = Configuration.load_yml_file(str(config_file))
    return ResourceManagerImpl(config)


# ---------------------------------------------------------------------------
# Reader + judge LLM helpers (same fallback chain as V1).
# ---------------------------------------------------------------------------
async def get_answer_llm(rm: ResourceManagerImpl) -> LanguageModel:
    rac = rm.config.retrieval_agent
    model_id = getattr(rac, "answer_llm_model", None) or rac.llm_model
    if not model_id:
        raise ValueError(
            "Neither retrieval_agent.answer_llm_model nor "
            "retrieval_agent.llm_model is set in configuration.yml"
        )
    return await rm.get_language_model(model_id)


async def get_judge_llm(rm: ResourceManagerImpl) -> LanguageModel:
    judge_id = getattr(rm.config.retrieval_agent, "judge_llm_model", None)
    if judge_id:
        return await rm.get_language_model(judge_id)
    return await get_answer_llm(rm)


# ---------------------------------------------------------------------------
# Answer prompt — V2-flavored (uses retrieved memory context + system prompt).
# Memory context is rendered by `memory.query()` (list of MemoryContextItem
# strings); we just concatenate the text values here.
# ---------------------------------------------------------------------------
def build_reader_messages(
    *,
    domain: str,
    memory_context_texts: list[str],
    question: str,
) -> list[dict[str, str]]:
    system = DOMAIN_SYSTEM_PROMPTS.get(domain)
    if system is None:
        raise ValueError(
            f"Unsupported domain {domain!r}; expected one of {sorted(DOMAIN_SYSTEM_PROMPTS)}"
        )
    if memory_context_texts:
        memory_block = "\n\n--- Memory ---\n" + "\n\n".join(memory_context_texts)
    else:
        memory_block = "\n\n--- Memory ---\n(empty)"
    user = (
        f"{memory_block}\n\n"
        "Answer the following question. Put the final answer in \\boxed{...}.\n\n"
        f"Question: {question}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Judge prompts (LLM-as-a-judge, simplified vs upstream V2's per-category
# heuristics + LLM checkers — we use a single yes/no judge per category and
# a dedicated abstention judge. Aligned in spirit with upstream's
# `_ABSTENTION_JUDGE_SYSTEM_PROMPT` and `_GOTCHAS_JUDGE_SYSTEM_PROMPT`.)
# ---------------------------------------------------------------------------
_JUDGE_SYS_DEFAULT = (
    "You are a strict grader for QA over a customized environment. "
    "Output exactly 'yes' if the model response contains the information "
    "expressed by the reference answer (paraphrases allowed). "
    "Output exactly 'no' otherwise."
)

_JUDGE_SYS_ABSTENTION = (
    "You are a strict grader for flawed-premise (abstention) questions. "
    "Output 'yes' iff the model correctly identifies that the question's "
    "premise is wrong, consistent with the reference. If the model gives a "
    "concrete answer that follows the flawed premise, output 'no'. If the "
    "model says UNKNOWN without identifying the flaw, output 'no'."
)

_JUDGE_SYS_GOTCHAS = (
    "You are a strict grader for gotchas-style insight questions. The "
    "reference describes key insight(s). Output 'yes' iff the model response "
    "includes at least one correct insight point from the reference "
    "(paraphrase allowed) and does not contradict any reference point. "
    "Otherwise output 'no'."
)


def judge_system_prompt(category: str) -> str:
    if category in ABSTENTION_CATEGORIES:
        return _JUDGE_SYS_ABSTENTION
    if category == "gotchas":
        return _JUDGE_SYS_GOTCHAS
    return _JUDGE_SYS_DEFAULT


def build_judge_messages(
    *,
    category: str,
    question: str,
    reference_answer: str,
    model_response: str,
) -> list[dict[str, str]]:
    system = judge_system_prompt(category)
    user = (
        f"Question: {question}\n\n"
        f"Reference Answer: {reference_answer}\n\n"
        f"Model Response: {model_response}\n\n"
        "Reply with 'yes' or 'no' only."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_yes_no_lenient(raw: str) -> bool:
    """Lenient yes-parser: `'yes' in raw.lower()` (matches V1)."""
    return "yes" in (raw or "").lower()


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------
def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    import json as _json

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing JSONL file: {p}")
    out: list[dict[str, Any]] = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(_json.loads(line))
    return out


def load_json(path: str | Path) -> Any:
    import json as _json

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing JSON file: {p}")
    return _json.loads(p.read_text(encoding="utf-8"))


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    import json as _json

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for row in rows:
            f.write(_json.dumps(row, ensure_ascii=False) + "\n")
