"""Stage: judge.

Reads generate.jsonl, calls evaluate_llm_judge() on each row, writes judge.jsonl
with an added `llm_score` (1=CORRECT, 0=WRONG) field.

If `judge.llm_model_id` is set in the run config, a temporary copy of the
configuration.yml is created with `retrieval_agent.judge_llm_model` swapped to
that ID. `retrieval_agent.llm_model` (answer LLM pointer) is never touched here.
The model ID must already exist under `resources.language_models` in the
configuration.yml (typically by adding `judge_llm:` to the model profile YAML
before running generate_config.py).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from . import _common as cm


def _judge_config_path(run_cfg: dict[str, Any], base_config_path: str) -> str:
    """Return a configuration.yml path with retrieval_agent.judge_llm_model swapped if requested.

    When run_cfg.judge.llm_model_id is unset, returns base_config_path unchanged
    so create_judge_fn() reads whatever judge_llm_model the model profile baked
    in (or falls back to retrieval_agent.llm_model). Never mutates
    retrieval_agent.llm_model — the answer LLM pointer is preserved end-to-end.
    """
    judge_id = (run_cfg.get("judge") or {}).get("llm_model_id")
    if not judge_id:
        return base_config_path

    with Path(base_config_path).open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    available = (cfg.get("resources") or {}).get("language_models") or {}
    if judge_id not in available:
        raise ValueError(
            f"judge.llm_model_id={judge_id!r} is not defined under "
            f"resources.language_models in {base_config_path}. Available IDs: "
            f"{sorted(available.keys())}. Add it to the model profile YAML."
        )

    cfg.setdefault("retrieval_agent", {})["judge_llm_model"] = judge_id

    out_dir = cm.results_dir_for(run_cfg)
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        "w",
        suffix=".yml",
        prefix=f"{run_cfg['run_name']}_judge_",
        dir=str(out_dir),
        delete=False,
        encoding="utf-8",
    )
    try:
        yaml.safe_dump(cfg, tmp, sort_keys=False, allow_unicode=True)
    finally:
        tmp.close()
    print(f"[judge] using swapped config (judge_llm_model={judge_id}) → {tmp.name}")
    return tmp.name


# LongMemEval question_type values (xiaowu0162/longmemeval-cleaned). Same
# routing key as evaluation/retrieval_agent/evaluate.py: when the row's
# category matches, route to the original task-specific judge instead of the
# default ACCURACY_PROMPT path. Kept as a local constant rather than imported
# to avoid coupling the wrapper stage to legacy evaluate.py internals.
_LONGMEMEVAL_TASKS = frozenset(
    {
        "single-session-user",
        "single-session-assistant",
        "multi-session",
        "temporal-reasoning",
        "knowledge-update",
        "single-session-preference",
    }
)


def _resolve_yesno_policy(run_cfg: dict[str, Any], config_path: str) -> str:
    """Decide LongMemEval yes/no policy. run_cfg.judge.longmemeval_yesno_policy
    wins; otherwise read retrieval_agent.longmemeval_yesno_policy from the
    (possibly swapped) configuration.yml. Validates the final value.
    """
    policy = (run_cfg.get("judge") or {}).get("longmemeval_yesno_policy")
    if policy is None:
        from memmachine_server.common.configuration import Configuration

        conf = Configuration.load_yml_file(config_path)
        policy = conf.retrieval_agent.longmemeval_yesno_policy
    if policy not in {"lenient", "strict"}:
        raise ValueError(
            f"longmemeval_yesno_policy must be 'lenient' or 'strict', got {policy!r}"
        )
    return policy


def run(run_cfg: dict[str, Any]) -> Path:
    from evaluation.retrieval_agent.llm_judge import (
        create_judge_fn,
        evaluate_llm_judge_longmemeval_with_details,
        evaluate_llm_judge_with_details,
    )

    out_dir = cm.results_dir_for(run_cfg)
    generate_path = out_dir / "generate.jsonl"
    judge_path = out_dir / "judge.jsonl"

    if not generate_path.exists():
        raise FileNotFoundError(
            f"generate.jsonl missing: {generate_path} — run --stage retrieve first"
        )

    config_path = cm.resolve_config_path(run_cfg)
    judge_config = _judge_config_path(run_cfg, config_path)
    yesno_policy = _resolve_yesno_policy(run_cfg, judge_config)
    rows = cm.read_jsonl(generate_path)
    print(
        f"[judge] {len(rows)} rows  config={judge_config}  "
        f"longmemeval_yesno_policy={yesno_policy}"
    )

    json_call_fn = create_judge_fn(judge_config)
    text_call_fn: Callable[[str], str] | None = None

    judged: list[dict[str, Any]] = []
    correct = 0
    for i, row in enumerate(rows):
        category = str(row.get("category", ""))
        if category in _LONGMEMEVAL_TASKS:
            if text_call_fn is None:
                # Lazy: only build the plain-text judge when the run actually
                # contains LongMemEval rows. Mirrors the lazy init in
                # evaluation/retrieval_agent/evaluate.py:get_text_call_fn.
                text_call_fn = create_judge_fn(judge_config, json_mode=False)
            details = evaluate_llm_judge_longmemeval_with_details(
                question=row.get("question", ""),
                gold_answer=row.get("golden_answer", ""),
                generated_answer=row.get("model_answer", ""),
                question_type=category,
                question_id=str(row.get("question_id", "")),
                call_fn=text_call_fn,
                yesno_policy=yesno_policy,
            )
        else:
            details = evaluate_llm_judge_with_details(
                question=row.get("question", ""),
                gold_answer=row.get("golden_answer", ""),
                generated_answer=row.get("model_answer", ""),
                call_fn=json_call_fn,
            )
        score = details["score"]
        correct += score
        judged.append(
            {
                **row,
                "llm_score": int(score),
                # Persist raw judge LLM reply + parsed label so all-zeros runs
                # can be diagnosed without re-running judge. parsed_label is
                # "CORRECT"/"WRONG" for the JSON judge, "yes"/"no" for the
                # LongMemEval judge, or null when parsing failed.
                "judge_raw_response": details["raw_response"],
                "judge_parsed_label": details["parsed_label"],
                "judge_attempts": details["attempts"],
            }
        )
        if (i + 1) % 50 == 0:
            print(f"[judge] {i + 1}/{len(rows)}  running acc={correct / (i + 1):.3f}")

    cm.write_jsonl(judge_path, judged)
    if rows:
        print(f"[judge] ok → {judge_path}  overall_accuracy={correct / len(rows):.4f}")
    else:
        print(f"[judge] ok → {judge_path}  (no rows)")
    return judge_path
