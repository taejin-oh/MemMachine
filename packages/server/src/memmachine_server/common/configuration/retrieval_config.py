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
