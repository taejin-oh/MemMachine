"""Stage: judge.

Reads generate.jsonl, calls evaluate_llm_judge() on each row, writes judge.jsonl
with an added `llm_score` (1=CORRECT, 0=WRONG) field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as cm


def run(run_cfg: dict[str, Any]) -> Path:
    from evaluation.retrieval_agent.llm_judge import create_judge_fn, evaluate_llm_judge

    out_dir = cm.results_dir_for(run_cfg)
    generate_path = out_dir / "generate.jsonl"
    judge_path = out_dir / "judge.jsonl"

    if not generate_path.exists():
        raise FileNotFoundError(f"generate.jsonl missing: {generate_path} — run --stage retrieve first")

    config_path = cm.resolve_config_path(run_cfg)
    rows = cm.read_jsonl(generate_path)
    print(f"[judge] {len(rows)} rows  config={config_path}")

    call_fn = create_judge_fn(config_path)

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
