"""Retrieval-agent configuration models."""

from typing import Literal

from pydantic import Field

from memmachine_server.common.configuration.mixin_confs import YamlSerializableMixin


class RetrievalAgentConf(YamlSerializableMixin):
    """Configuration for top-level retrieval-agent orchestration."""

    llm_model: str | None = Field(
        default=None,
        description="Default language model used by retrieval-agent strategies.",
    )
    reranker: str | None = Field(
        default=None,
        description="Default reranker used by retrieval-agent strategies.",
    )
    judge_llm_model: str | None = Field(
        default=None,
        description="LLM used by the eval judge. Falls back to llm_model when unset.",
    )
    longmemeval_yesno_policy: Literal["lenient", "strict"] = Field(
        default="lenient",
        description=(
            "Parser policy for LongMemEval judge yes/no replies. 'lenient' "
            "(default) matches xiaowu0162/LongMemEval upstream "
            "('yes' in lower(raw) substring). 'strict' requires whole-string "
            "match. CLI / run_cfg overrides take precedence over this field."
        ),
    )
    longmemeval_answer_prompt: Literal[
        "memmachine_original", "agent_lightning", "LME_origin_prompt"
    ] = Field(
        default="LME_origin_prompt",
        description=(
            "LongMemEval answer prompt body. 'LME_origin_prompt' (default) is "
            "a verbatim copy of xiaowu0162/LongMemEval upstream "
            "(src/generation/run_generation.py answer_prompt_template, "
            "no-merge no-CoT branch). Only the prompt template body is "
            "substituted; retrieval / memory formatting / generation pipeline "
            "still run through MemMachine's retrieval_agent path, so this is "
            "a prompt-template-isolation reference point, not a full "
            "upstream-baseline reproduction. 'memmachine_original' applies "
            "MemMachine's episodic_memory LongMemEval prompt body to the "
            "retrieval_agent path (hybrid) — satisfies LongMemEval's "
            "prompt-side evaluation constraints (memory-only basis, Current "
            "Date, no length cap) but body is not verbatim upstream. "
            "'agent_lightning' preserves the v0.5 prompt (Agent Lightning "
            "paper, arXiv:2508.03680) for v0.5 baseline reruns. "
            "CLI / run_cfg overrides take precedence."
        ),
    )
