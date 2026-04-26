"""Stage: judge.

Reads generate.jsonl, calls evaluate_llm_judge() on each row, writes judge.jsonl
with an added `llm_score` (1=CORRECT, 0=WRONG) field.

If `judge.llm_model_id` is set in the run config, a temporary copy of the
configuration.yml is created with `retrieval_agent.llm_model` swapped to that
ID, so the judge LLM can differ from the answer LLM. The model ID must already
exist under `resources.language_models` in the configuration.yml (typically by
adding it to the model profile YAML before running generate_config.py).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml

from . import _common as cm


def _judge_config_path(run_cfg: dict[str, Any], base_config_path: str) -> str:
    """Return a configuration.yml path with retrieval_agent.llm_model swapped if requested."""
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

    cfg.setdefault("retrieval_agent", {})["llm_model"] = judge_id

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
    print(f"[judge] using swapped config (judge_llm={judge_id}) → {tmp.name}")
    return tmp.name


def run(run_cfg: dict[str, Any]) -> Path:
    from evaluation.retrieval_agent.llm_judge import create_judge_fn, evaluate_llm_judge

    out_dir = cm.results_dir_for(run_cfg)
    generate_path = out_dir / "generate.jsonl"
    judge_path = out_dir / "judge.jsonl"

    if not generate_path.exists():
        raise FileNotFoundError(
            f"generate.jsonl missing: {generate_path} — run --stage retrieve first"
        )

    config_path = cm.resolve_config_path(run_cfg)
    judge_config = _judge_config_path(run_cfg, config_path)
    rows = cm.read_jsonl(generate_path)
    print(f"[judge] {len(rows)} rows  config={judge_config}")

    call_fn = create_judge_fn(judge_config)

    judged: list[dict[str, Any]] = []
    correct = 0
    for i, row in enumerate(rows):
        score = evaluate_llm_judge(
            question=row.get("question", ""),
            gold_answer=row.get("golden_answer", ""),
            generated_answer=row.get("model_answer", ""),
            call_fn=call_fn,
        )
        correct += score
        judged.append({**row, "llm_score": int(score)})
        if (i + 1) % 50 == 0:
            print(f"[judge] {i + 1}/{len(rows)}  running acc={correct / (i + 1):.3f}")

    cm.write_jsonl(judge_path, judged)
    if rows:
        print(f"[judge] ok → {judge_path}  overall_accuracy={correct / len(rows):.4f}")
    else:
        print(f"[judge] ok → {judge_path}  (no rows)")
    return judge_path
