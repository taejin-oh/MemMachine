"""Standalone helpers for `evaluation/longmemeval/`.

This module isolates the directory from the rest of the eval-tool tree:
nothing here imports from `evaluation/retrieval_agent/`,
`evaluation/utils/agent_utils.py`, or `scripts/`. The only dependency
is the workspace package `memmachine_server` (the server code itself).

That means `evaluation/longmemeval/` keeps working even if
`evaluation/retrieval_agent/` is reverted to main-branch state.

Helpers:
  - load_eval_config            ResourceManager from configuration.yml
  - build_memory_and_agent      EpisodicMemory + MemMachineAgent per session
  - get_answer_llm / get_judge_llm  LanguageModel from RM
  - set_safe_embedder_limits    embedder request-size cap
  - collect_supporting_facts    has_answer=True turn contents
  - parse_session_dt            longmemeval session_date parser

Upstream-aligned prompts (verbatim from xiaowu0162/LongMemEval):
  - ANSWER_PROMPTS              {LME_origin_prompt, LME_origin_cot_prompt}
                                from src/generation/run_generation.py
  - get_anscheck_prompt         from src/evaluation/evaluate_qa.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memmachine_server.common.configuration import Configuration
from memmachine_server.common.language_model.language_model import LanguageModel
from memmachine_server.common.metrics_factory import PrometheusMetricsFactory
from memmachine_server.common.resource_manager.resource_manager import (
    ResourceManagerImpl,
)
from memmachine_server.episodic_memory.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryParams,
)
from memmachine_server.episodic_memory.long_term_memory import (
    LongTermMemory,
    LongTermMemoryParams,
)
from memmachine_server.retrieval_agent.agents import MemMachineAgent
from memmachine_server.retrieval_agent.common.agent_api import (
    AgentToolBase,
    AgentToolBaseParam,
)


def load_eval_config(config_path: str) -> ResourceManagerImpl:
    """Load working configuration.yml → ResourceManagerImpl."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"configuration.yml not found at {config_path!r}. Run "
            "scripts/generate_config.py first or supply a hand-written yml."
        )
    config = Configuration.load_yml_file(str(config_file))
    return ResourceManagerImpl(config)


async def build_memory_and_agent(
    rm: ResourceManagerImpl, session_id: str
) -> tuple[EpisodicMemory, AgentToolBase]:
    """Per-session EpisodicMemory + MemMachineAgent.

    ResourceManagerImpl caches embedder / reranker / vector_graph_store
    resources internally, so calling this per question only creates new
    wrappers — no model re-loading.
    """
    conf = rm.config
    ltm_conf = conf.episodic_memory.long_term_memory
    if ltm_conf is None:
        raise ValueError(
            "episodic_memory.long_term_memory is not configured in configuration.yml"
        )
    if not ltm_conf.embedder:
        raise ValueError(
            "episodic_memory.long_term_memory.embedder is not set"
        )
    if not ltm_conf.vector_graph_store:
        raise ValueError(
            "episodic_memory.long_term_memory.vector_graph_store is not set"
        )

    embedder = await rm.get_embedder(ltm_conf.embedder)
    reranker_id = conf.retrieval_agent.reranker or ltm_conf.reranker
    if not reranker_id:
        raise ValueError(
            "No reranker configured "
            "(retrieval_agent.reranker or episodic_memory.long_term_memory.reranker)"
        )
    reranker = await rm.get_reranker(reranker_id)
    vector_graph_store = await rm.get_vector_graph_store(
        ltm_conf.vector_graph_store
    )

    chunking = getattr(ltm_conf, "message_sentence_chunking", None) or False

    long_term_memory = LongTermMemory(
        LongTermMemoryParams(
            session_id=session_id,
            vector_graph_store=vector_graph_store,
            embedder=embedder,
            reranker=reranker,
            message_sentence_chunking=chunking,
        )
    )
    memory = EpisodicMemory(
        EpisodicMemoryParams(
            session_key=session_id,
            metrics_factory=PrometheusMetricsFactory(),
            long_term_memory=long_term_memory,
            short_term_memory=None,
            enabled=True,
        ),
    )

    query_agent: AgentToolBase = MemMachineAgent(
        AgentToolBaseParam(
            model=None,
            children_tools=[],
            extra_params={},
            reranker=reranker,
        )
    )

    return memory, query_agent


def set_safe_embedder_limits(memory: EpisodicMemory) -> None:
    """Cap embedder request size below typical model token ceilings."""
    long_term_memory = getattr(memory, "long_term_memory", None)
    declarative_memory = (
        getattr(long_term_memory, "declarative_memory", None)
        if long_term_memory is not None
        else None
    )
    embedder = getattr(declarative_memory, "_embedder", None)
    if embedder is None:
        return
    if hasattr(embedder, "max_total_input_length_per_request"):
        embedder.max_total_input_length_per_request = 30000


def collect_supporting_facts(sample: dict[str, Any]) -> list[str]:
    """Return has_answer=True turn contents from a longmemeval sample."""
    facts: list[str] = []
    for session in sample.get("haystack_sessions", []) or []:
        for turn in session or []:
            if turn.get("has_answer"):
                content = str(turn.get("content", "")).strip()
                if content:
                    facts.append(content)
    return facts


def parse_session_dt(ts: str) -> datetime:
    """Parse a longmemeval session_date string ('2023/04/10 (Mon) 23:07')."""
    return datetime.strptime(ts, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Language-model helpers (answer + judge)
# ---------------------------------------------------------------------------
async def get_answer_llm(rm: ResourceManagerImpl) -> LanguageModel:
    """LanguageModel for the answer step (retrieval_agent.llm_model)."""
    model_id = rm.config.retrieval_agent.llm_model
    if not model_id:
        raise ValueError(
            "retrieval_agent.llm_model is not set in configuration.yml"
        )
    return await rm.get_language_model(model_id)


async def get_judge_llm(rm: ResourceManagerImpl) -> LanguageModel:
    """LanguageModel for the judge step.

    Prefers `retrieval_agent.judge_llm_model` if set, falls back to the
    answer LLM (`retrieval_agent.llm_model`) — same policy as our
    scripts/stages/judge.py.
    """
    judge_id = getattr(rm.config.retrieval_agent, "judge_llm_model", None)
    if judge_id:
        return await rm.get_language_model(judge_id)
    return await get_answer_llm(rm)


# ---------------------------------------------------------------------------
# Upstream-verbatim answer prompts
# (from xiaowu0162/LongMemEval src/generation/run_generation.py:54-57)
# ---------------------------------------------------------------------------
_ANSWER_PROMPT_PLAIN = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history.\n\n\n"
    "History Chats:\n\n{memories}\n\nCurrent Date: {question_date}\n"
    "Question: {question}\nAnswer:"
)

_ANSWER_PROMPT_COT = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history. "
    "Answer the question step by step: first extract all the relevant "
    "information, and then reason over the information to get the "
    "answer.\n\n\nHistory Chats:\n\n{memories}\n\nCurrent Date: "
    "{question_date}\nQuestion: {question}\nAnswer (step by step):"
)

ANSWER_PROMPTS: dict[str, str] = {
    "LME_origin_prompt": _ANSWER_PROMPT_PLAIN,
    "LME_origin_cot_prompt": _ANSWER_PROMPT_COT,
}


# ---------------------------------------------------------------------------
# Upstream-verbatim judge prompts
# (from xiaowu0162/LongMemEval src/evaluation/evaluate_qa.py:24-43)
# ---------------------------------------------------------------------------
def get_anscheck_prompt(
    task: str,
    question: str,
    answer: str,
    response: str,
    abstention: bool = False,
) -> str:
    """Verbatim port of upstream `get_anscheck_prompt`. Picks one of 5
    templates by question_type; abstention has its own template.
    """
    if not abstention:
        if task in (
            "single-session-user",
            "single-session-assistant",
            "multi-session",
        ):
            template = (
                "I will give you a question, a correct answer, and a response "
                "from a model. Please answer yes if the response contains the "
                "correct answer. Otherwise, answer no. If the response is "
                "equivalent to the correct answer or contains all the "
                "intermediate steps to get the correct answer, you should "
                "also answer yes. If the response only contains a subset of "
                "the information required by the answer, answer no. \n\n"
                "Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
        elif task == "temporal-reasoning":
            template = (
                "I will give you a question, a correct answer, and a response "
                "from a model. Please answer yes if the response contains the "
                "correct answer. Otherwise, answer no. If the response is "
                "equivalent to the correct answer or contains all the "
                "intermediate steps to get the correct answer, you should "
                "also answer yes. If the response only contains a subset of "
                "the information required by the answer, answer no. In "
                "addition, do not penalize off-by-one errors for the number "
                "of days. If the question asks for the number of "
                "days/weeks/months, etc., and the model makes off-by-one "
                "errors (e.g., predicting 19 days when the answer is 18), "
                "the model's response is still correct. \n\nQuestion: {}\n\n"
                "Correct Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
        elif task == "knowledge-update":
            template = (
                "I will give you a question, a correct answer, and a response "
                "from a model. Please answer yes if the response contains the "
                "correct answer. Otherwise, answer no. If the response "
                "contains some previous information along with an updated "
                "answer, the response should be considered as correct as "
                "long as the updated answer is the required answer.\n\n"
                "Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
        elif task == "single-session-preference":
            template = (
                "I will give you a question, a rubric for desired "
                "personalized response, and a response from a model. Please "
                "answer yes if the response satisfies the desired response. "
                "Otherwise, answer no. The model does not need to reflect "
                "all the points in the rubric. The response is correct as "
                "long as it recalls and utilizes the user's personal "
                "information correctly.\n\nQuestion: {}\n\nRubric: {}\n\n"
                "Model Response: {}\n\nIs the model response correct? "
                "Answer yes or no only."
            )
        else:
            raise NotImplementedError(f"Unknown task type: {task!r}")
    else:
        template = (
            "I will give you an unanswerable question, an explanation, and a "
            "response from a model. Please answer yes if the model correctly "
            "identifies the question as unanswerable. The model could say "
            "that the information is incomplete, or some other information "
            "is given but the asked information is not.\n\nQuestion: {}\n\n"
            "Explanation: {}\n\nModel Response: {}\n\nDoes the model "
            "correctly identify the question as unanswerable? Answer yes or "
            "no only."
        )
    return template.format(question, answer, response)


def parse_yes_no_lenient(raw: str) -> bool:
    """Upstream's lenient parser: ``'yes' in raw.lower()``."""
    return "yes" in (raw or "").lower()
