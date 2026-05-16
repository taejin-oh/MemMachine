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
        "LME_origin_prompt",
        "LME_origin_cot_prompt",
        "memmachine_original",
        "edwin1",
        "edwin3",
    ] = Field(
        default="LME_origin_prompt",
        description=(
            "LongMemEval answer prompt body. 'LME_origin_prompt' (default) is "
            "a verbatim copy of xiaowu0162/LongMemEval upstream "
            "(src/generation/run_generation.py answer_prompt_template, "
            "no-merge no-CoT branch) — prompt-template-isolation reference "
            "point, not a full upstream-baseline reproduction. "
            "'LME_origin_cot_prompt' is the upstream CoT branch (cot=True): "
            "adds step-by-step reasoning instruction and an 'Answer (step by "
            "step):' cue. 'memmachine_original' applies MemMachine's "
            "episodic_memory LongMemEval prompt body to the retrieval_agent "
            "path (hybrid). 'edwin1' / 'edwin3' are opt-in alternates from "
            "docs/msr/edwin_prompt.md. CLI / run_cfg overrides take precedence."
        ),
    )
