"""End-to-end 5-stage pipeline smoke without DB / models.

Stubs out:
  - evaluation.retrieval_agent.longmemeval_test.longmemeval_ingest → no-op
  - evaluation.utils.agent_utils.load_eval_config                   → None
  - evaluation.utils.agent_utils.init_memmachine_params             → (None, None, None)
  - evaluation.utils.agent_utils.process_question                   → synthetic (category, dict)
  - evaluation.retrieval_agent.llm_judge.create_judge_fn            → deterministic yes/no callable

Synthesizes a 5-sample LongMemEval-shaped dataset, runs all 5 stages,
prints the analyze.json summary. Useful for validating wiring without
Docker / API credits.

Usage:
    uv run python scripts/fake_smoke_pipeline.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
for p in (
    REPO,
    REPO / "packages" / "common" / "src",
    REPO / "packages" / "server" / "src",
    REPO / "packages" / "client" / "src",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ---------------------------------------------------------------------------
# Synthetic dataset (5 samples, mixed categories incl. abstention)
# ---------------------------------------------------------------------------

FAKE_DATASET = [
    {
        "question_id": "fake_q1",
        "question": "When did the user move to Seoul?",
        "answer": "March 2023",
        "question_type": "temporal-reasoning",
        "haystack_sessions": [
            [
                {"content": "I moved to Seoul in March 2023.", "has_answer": True},
                {"content": "It's been busy at the new job.", "has_answer": False},
            ],
        ],
        "question_date": "2024/01/15 (Mon) 10:00",
    },
    {
        "question_id": "fake_q2",
        "question": "How long ago did the user start the new diet?",
        "answer": "Two weeks ago",
        "question_type": "temporal-reasoning",
        "haystack_sessions": [
            [{"content": "Started a new diet last week.", "has_answer": True}],
        ],
        "question_date": "2024/01/15 (Mon) 10:00",
    },
    {
        "question_id": "fake_q3",
        "question": "Where does the user currently work?",
        "answer": "Anthropic",
        "question_type": "knowledge-update",
        "haystack_sessions": [
            [
                {
                    "content": "I switched jobs to Anthropic last month.",
                    "has_answer": True,
                }
            ],
        ],
        "question_date": "2024/02/01 (Thu) 14:30",
    },
    {
        "question_id": "fake_q4_abs",
        "question": "What is the user's pet's name?",
        "answer": "(unanswerable)",
        "question_type": "single-session-user",
        "haystack_sessions": [
            [{"content": "Chatting about the weather.", "has_answer": False}],
        ],
        "question_date": "2024/02/01 (Thu) 14:30",
    },
    {
        "question_id": "fake_q5",
        "question": "What hobby does the user enjoy?",
        "answer": "Photography",
        "question_type": "single-session-preference",
        "haystack_sessions": [
            [{"content": "I love photography on weekends.", "has_answer": True}],
        ],
        "question_date": "2024/02/01 (Thu) 14:30",
    },
]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


async def fake_longmemeval_ingest(dataset, config_path, session_id):
    print(f"[FAKE_INGEST] {len(dataset)} questions → session={session_id}")


def fake_load_eval_config(config_path):
    return None


async def fake_init_memmachine_params(**_kwargs):
    return (None, None, None)


async def fake_process_question(**kwargs):
    q = kwargs["question"]
    return kwargs["category"], {
        "question": q,
        "category": kwargs["category"],
        "golden_answer": kwargs["answer"],
        "model_answer": f"[FAKE_ANSWER] echo: {q[:60]}",
        "conversation_memories": "FAKE_RETRIEVED_CONTEXT",
        "num_episodes_retrieved": 3,
        "memory_retrieval_time": 0.01,
        "memory_search_called": 1,
        "agent": "FakeAgent",
        "selected_tool": "FakeTool",
        "supporting_facts": kwargs["supporting_facts"],
        "input_token": 100,
        "output_token": 50,
        "tool_select_input_token": 10,
        "tool_select_output_token": 5,
        "llm_time": 0.02,
        "fact_hits": [],
        "fact_miss": [],
        "question_id": (kwargs.get("extra_attributes") or {}).get("question_id", ""),
    }


def fake_create_judge_fn(config_path, json_mode=True):
    """Deterministic yes/no callable for LongMemEval text mode.

    Hash-based alternation so different prompts produce a visible mix
    (otherwise analyze would show a single accuracy value).
    """

    def _call(prompt):
        return "yes" if abs(hash(prompt)) % 2 == 0 else "no"

    return _call


# ---------------------------------------------------------------------------
# Config materialization
# ---------------------------------------------------------------------------

RUN_NAME = "fake_smoke"
RUN_DIR = REPO / "results" / RUN_NAME
RUN_YAML = REPO / "configs" / "runs" / f"{RUN_NAME}.yaml"
GEN_YML = REPO / "configs" / "generated" / f"{RUN_NAME}_configuration.yml"
DATA_JSON = RUN_DIR / "_fake_dataset.json"


def setup_files():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    DATA_JSON.write_text(json.dumps(FAKE_DATASET, indent=2, ensure_ascii=False))

    if not GEN_YML.exists():
        from scripts._merge import dump_yaml, load_yaml
        from scripts.generate_config import (
            _apply_fixed_to_configuration,
            build_configuration_yml,
        )

        mp = load_yaml(REPO / "configs" / "profiles" / "models" / "main.yaml")
        dp = load_yaml(REPO / "configs" / "profiles" / "dbs" / "main.yaml")
        cfg = build_configuration_yml(mp, dp)
        _apply_fixed_to_configuration(
            cfg,
            {"message_sentence_chunking": False, "prepend_user_prefix": False},
        )
        GEN_YML.parent.mkdir(parents=True, exist_ok=True)
        dump_yaml(cfg, GEN_YML.resolve())

    RUN_YAML.parent.mkdir(parents=True, exist_ok=True)
    RUN_YAML.write_text(
        f"""run_name: {RUN_NAME}
problem: 0
description: "fake-DB / fake-model end-to-end smoke"

configuration:
  mode: existing
  generated_path: {GEN_YML.resolve()}
  existing_path: {GEN_YML.resolve()}

benchmark:
  name: longmemeval
  length: 100
  split: fake
  data_path: {DATA_JSON.resolve()}

sweep: {{}}

fixed:
  test_target: memmachine
  search_limit: 5
  prepend_user_prefix: false
  message_sentence_chunking: false

evaluation:
  exclude_abstention: true
  ingest_concurrency: 1
  search_concurrency: 1
  judge_concurrency: 1
  longmemeval:
    answer_prompt: LME_origin_prompt
    # include_categories null → 모든 카테고리

judge:
  llm_model_id: null
  longmemeval_yesno_policy: lenient

n_runs: 1
"""
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def main():
    setup_files()
    print(f"[smoke] dataset    : {DATA_JSON} ({len(FAKE_DATASET)} samples)")
    print(f"[smoke] run yaml   : {RUN_YAML}")
    print(f"[smoke] generated  : {GEN_YML}")
    print()

    patches = [
        patch(
            "evaluation.retrieval_agent.longmemeval_test.longmemeval_ingest",
            side_effect=fake_longmemeval_ingest,
        ),
        patch(
            "evaluation.utils.agent_utils.load_eval_config",
            side_effect=fake_load_eval_config,
        ),
        patch(
            "evaluation.utils.agent_utils.init_memmachine_params",
            side_effect=fake_init_memmachine_params,
        ),
        patch(
            "evaluation.utils.agent_utils.process_question",
            side_effect=fake_process_question,
        ),
        patch(
            "evaluation.retrieval_agent.llm_judge.create_judge_fn",
            side_effect=fake_create_judge_fn,
        ),
    ]
    for p in patches:
        p.start()

    rc = 1
    try:
        from scripts.run_pipeline import main as run_main

        old_argv = sys.argv[:]
        sys.argv = ["run_pipeline.py", "--config", str(RUN_YAML)]
        try:
            rc = run_main() or 0
        finally:
            sys.argv = old_argv
    finally:
        for p in patches:
            p.stop()

    print()
    print(f"[smoke] pipeline rc={rc}")
    print()

    analyze_path = RUN_DIR / "analyze.json"
    if analyze_path.exists():
        d = json.loads(analyze_path.read_text())
        print(f"[smoke] analyze.json: cells={len(d['cells'])}")
        for cell in d["cells"]:
            print(
                f"  cell sweep={cell['sweep']} n={cell['n']} "
                f"accuracy={cell['accuracy']:.4f}"
            )
            for cat, stats in cell.get("by_category", {}).items():
                print(f"    {cat}: {stats['accuracy']:.4f} (n={stats['n']})")
        print()
        for fname in (
            "ingest.jsonl",
            "retrieve.jsonl",
            "generate.jsonl",
            "judge.jsonl",
        ):
            fp = RUN_DIR / fname
            if fp.exists():
                lines = fp.read_text().count("\n")
                print(f"  {fname:<18} {lines:>4} rows")
    return rc


if __name__ == "__main__":
    sys.exit(main())
