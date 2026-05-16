"""Shared paths + fakes + dataset for the manual fake-smoke walkthrough.

Each step is its own runnable module — run them in order, one command
each, inspecting outputs between steps:

    uv run python -m scripts.fake_smoke.setup       # 0
    uv run python -m scripts.fake_smoke.ingest      # 1
    uv run python -m scripts.fake_smoke.retrieve    # 2
    uv run python -m scripts.fake_smoke.generate    # 3
    uv run python -m scripts.fake_smoke.judge       # 4
    uv run python -m scripts.fake_smoke.analyze     # 5

Each step module imports its required fakes from here and calls the
actual stage's `run(run_cfg)` directly — so the wiring it exercises is
the real pipeline, not a wrapper.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (
    REPO,
    REPO / "packages" / "common" / "src",
    REPO / "packages" / "server" / "src",
    REPO / "packages" / "client" / "src",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


RUN_NAME = "fake_smoke"
RUN_DIR = REPO / "results" / RUN_NAME
RUN_YAML = REPO / "configs" / "runs" / f"{RUN_NAME}.yaml"
GEN_YML = REPO / "configs" / "generated" / f"{RUN_NAME}_configuration.yml"
DATA_JSON = RUN_DIR / "_fake_dataset.json"


# ---------------------------------------------------------------------------
# Synthetic dataset — 5 LongMemEval-shaped rows covering 4 categories +
# one abstention question (`_abs` suffix in question_id triggers the
# abstention path even though its question_type is single-session-user).
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
# Fakes — applied per-stage, only where needed
# ---------------------------------------------------------------------------


async def fake_longmemeval_ingest(dataset, config_path, session_id):
    """Replaces the real Neo4j INSERT + embedder loop in ingest stage."""
    print(
        f"[FAKE] longmemeval_ingest no-op "
        f"({len(dataset)} questions → session={session_id})"
    )


def fake_load_eval_config(config_path):
    """Replaces ResourceManager creation (which would open Neo4j / OpenAI / Postgres clients)."""
    return


async def fake_init_memmachine_params(**_kwargs):
    """Replaces (EpisodicMemory, answer LLM, QueryAgent) instantiation."""
    return (None, None, None)


async def fake_process_question(**kwargs):
    """Replaces embed → Neo4j query → rerank → answer LLM round-trip with a canned dict."""
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
    """Replaces the OpenAI/Bedrock judge client builder.

    Returns a deterministic yes/no callable based on the prompt hash so
    analyze sees a visible mix of CORRECT/WRONG instead of a single
    value (which would obscure per-category aggregation).
    """

    def _call(prompt):
        return "yes" if abs(hash(prompt)) % 2 == 0 else "no"

    return _call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_run_cfg() -> dict:
    """Load the fake_smoke run yaml produced by the setup step."""
    from scripts._merge import load_yaml

    if not RUN_YAML.exists():
        raise SystemExit(
            f"run yaml missing: {RUN_YAML}\n"
            "Run `uv run python -m scripts.fake_smoke.setup` first."
        )
    return load_yaml(RUN_YAML)


__all__ = [
    "DATA_JSON",
    "FAKE_DATASET",
    "GEN_YML",
    "REPO",
    "RUN_DIR",
    "RUN_NAME",
    "RUN_YAML",
    "fake_create_judge_fn",
    "fake_init_memmachine_params",
    "fake_load_eval_config",
    "fake_longmemeval_ingest",
    "fake_process_question",
    "load_run_cfg",
]
