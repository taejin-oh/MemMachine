import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from evaluation.retrieval_agent.cli_utils import positive_int  # noqa: E402

# MemMachine episodic_memory LongMemEval prompt body
# (`evaluation/episodic_memory/longmemeval_search.py:36-52`) applied to the
# retrieval_agent path. Satisfies LongMemEval's key prompt-side evaluation
# constraints — memory-only basis, Current Date field, no open-domain
# fallback, no length cap — but the body itself is NOT a verbatim copy of
# xiaowu0162/LongMemEval upstream. It additionally carries MemMachine's
# KNOWLEDGE UPDATES / PLANNED ACTIONS reasoning hints (originally adapted
# from Mastra OM); those reinforce the temporal-reasoning and
# knowledge-update LongMemEval task categories. For an upstream-template
# baseline, opt into _ANSWER_PROMPT_LME_ORIGIN instead.
_ANSWER_PROMPT_MEMMACHINE_ORIGINAL = """You are a helpful assistant with access to extensive conversation history.
When answering questions, carefully review the conversation history to identify and use any relevant user preferences, interests, or specific details they have mentioned.

<history>
{memories}
</history>

IMPORTANT: When responding, reference specific details from these observations. Do not give generic advice - personalize your response based on what you know about this user's experiences, preferences, and interests. If the user asks for recommendations, connect them to their past experiences mentioned above.

KNOWLEDGE UPDATES: When asked about current state (e.g., "where do I currently...", "what is my current..."), always prefer the MOST RECENT information. Observations include dates - if you see conflicting information, the newer observation supersedes the older one. Look for phrases like "will start", "is switching", "changed to", "moved to" as indicators that previous information has been updated.

PLANNED ACTIONS: If the user stated they planned to do something (e.g., "I'm going to...", "I'm looking forward to...", "I will...") and the date they planned to do it is now in the past (check the relative time like "3 weeks ago"), assume they completed the action unless there's evidence they didn't. For example, if someone said "I'll start my new diet on Monday" and that was 2 weeks ago, assume they started the diet.

Current date: {question_date}
Question: {question}
"""

# Verbatim copy of xiaowu0162/LongMemEval upstream
# (src/generation/run_generation.py: answer_prompt_template, no-merge no-CoT
# branch). Positional ``{}`` placeholders are replaced with named ones so the
# template plays nicely with ``str.format(**fmt_kwargs)``; no other text is
# altered. Use this policy when reproducing the upstream paper baseline
# without MemMachine's KNOWLEDGE UPDATES / PLANNED ACTIONS reasoning hints.
_ANSWER_PROMPT_LME_ORIGIN = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history."
    "\n\n\n"
    "History Chats:\n\n{memories}\n\n"
    "Current Date: {question_date}\n"
    "Question: {question}\n"
    "Answer:"
)

# Verbatim copy of xiaowu0162/LongMemEval upstream
# (src/generation/run_generation.py: answer_prompt_template, no-merge **CoT**
# branch). Same placeholder normalization rule as ``_ANSWER_PROMPT_LME_ORIGIN``
# — positional ``{}`` → named, body text unchanged. Differs from the no-CoT
# baseline by (a) a one-sentence CoT instruction inserted into the preamble
# and (b) the trailing ``Answer (step by step):`` cue. Use this when
# reproducing the upstream paper's CoT-on numbers; expect more output tokens
# and slightly higher latency than the no-CoT baseline.
_ANSWER_PROMPT_LME_ORIGIN_COT = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history. "
    "Answer the question step by step: first extract all the relevant "
    "information, and then reason over the information to get the answer."
    "\n\n\n"
    "History Chats:\n\n{memories}\n\n"
    "Current Date: {question_date}\n"
    "Question: {question}\n"
    "Answer (step by step):"
)

# EDWIN1 — opt-in alternative answer-prompt body. Eight numbered reasoning
# rules (multi-answer enumeration, item counting, time-interval subtraction,
# episodic-memory framing, latest-wins) + a "couple of sentences" length cap.
# Placeholder normalization: ``{joined_history}`` → ``{memories}`` and
# ``{question_timestamp}`` → ``{question_date}`` so the template renders with
# the same kwargs as every other policy in this registry; no other text is
# altered.
_ANSWER_PROMPT_EDWIN1 = """You are asked to answer a question from a user based on your memories of a conversation between the user and an assistant.


1. Prioritize memories that answer the question directly. Be meticulous about recalling details.
2. When there may be multiple answers to the question, think hard to remember and list all possible answers. Do not become satisfied with just the first few answers you remember.
3. When asked to count items, carefully enumerate the items using numbers.
4. When asked about time intervals, the duration between events is computed by subtracting the start date from the end date in the chosen unit.
5. When asked for advice or suggestions, synthesize your memories of the user's interests, preferences, possessions, and problems to provide tailored recommendations.
6. Your memories are episodic, meaning that they consist of only your raw observations of what was said. You may need to reason about or guess what the memories imply in order to answer the question.
7. Your memories may include small or large jumps in time or context. You are not confused by this. You just did not bother to remember everything in between.
8. Your memories are ordered from earliest to latest. Prioritize the latest memories if anything has changed over time. Consider the question datetime when determining whether an event has actually occurred.



{memories}


Question timestamp: {question_date}
Question: {question}
Your short response to the question without fluff (no more than a couple of sentences):
"""

# EDWIN3 — opt-in alternative answer-prompt body. Closely related to
# ``_ANSWER_PROMPT_MEMMACHINE_ORIGINAL`` (KNOWLEDGE UPDATES + PLANNED ACTIONS
# guides), but adds an explicit MOST RECENT USER INPUT priority paragraph and
# omits the ``<history>...</history>`` wrapping that ``memmachine_original``
# uses. Placeholder normalization: ``{joined_history}`` → ``{memories}`` and
# ``{question_timestamp}`` → ``{question_date}``; no other text is altered.
_ANSWER_PROMPT_EDWIN3 = """You are a helpful assistant with access to extensive conversation history.
When answering questions, carefully review the conversation history to identify and use any relevant user preferences, interests, or specific details they have mentioned.


{memories}


IMPORTANT: When responding, reference specific details from these observations. Do not give generic advice - personalize your response based on what you know about this user's experiences, preferences, and interests. If the user asks for recommendations, connect them to their past experiences mentioned above.

KNOWLEDGE UPDATES: When asked about current state (e.g., "where do I currently...", "what is my current..."), always prefer the MOST RECENT information. Observations include dates - if you see conflicting information, the newer observation supersedes the older one. Look for phrases like "will start", "is switching", "changed to", "moved to" as indicators that previous information has been updated.

PLANNED ACTIONS: If the user stated they planned to do something (e.g., "I'm going to...", "I'm looking forward to...", "I will...") and the date they planned to do it is now in the past (check the relative time like "3 weeks ago"), assume they completed the action unless there's evidence they didn't. For example, if someone said "I'll start my new diet on Monday" and that was 2 weeks ago, assume they started the diet.

MOST RECENT USER INPUT: Treat the most recent user message as the highest-priority signal for what to do next. Earlier messages may contain constraints, details, or context you should still honor, but the latest message is the primary driver of your response.

Current date: {question_date}
Question: {question}
"""

# Public alias — points to the default policy body (LME_origin_prompt =
# upstream verbatim). Importers keep working without changes; runtime
# selection between the prompts happens via `_select_answer_prompt()`.
ANSWER_PROMPT = _ANSWER_PROMPT_LME_ORIGIN

_ANSWER_PROMPT_BY_POLICY: dict[str, str] = {
    "memmachine_original": _ANSWER_PROMPT_MEMMACHINE_ORIGINAL,
    "LME_origin_prompt": _ANSWER_PROMPT_LME_ORIGIN,
    "LME_origin_cot_prompt": _ANSWER_PROMPT_LME_ORIGIN_COT,
    "edwin1": _ANSWER_PROMPT_EDWIN1,
    "edwin3": _ANSWER_PROMPT_EDWIN3,
}

DEFAULT_CONCURRENCY = 30
DEFAULT_SEARCH_LIMIT = 20


def _format_question_date(raw: str | None) -> str:
    """Format LongMemEval ``question_date`` for the answer prompt.

    Input format follows ``evaluation/episodic_memory/longmemeval_models.py``
    (``"YYYY/MM/DD (Day) HH:MM"``). Output is ``"%A, %B %d, %Y at %I:%M %p"``
    (e.g. ``"Monday, April 10, 2023 at 11:07 PM"``), matching
    ``evaluation/episodic_memory/longmemeval_search.py:175-177`` so both
    entrypoints render the field identically.

    Empty / missing inputs return an empty string so ``Current Date:`` stays
    renderable. Unparseable strings fall through to the raw value.
    """
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)
    except ValueError:
        return str(raw)
    return dt.strftime("%A, %B %d, %Y at %I:%M %p")


def _select_answer_prompt(policy: str) -> str:
    """Return the prompt body for ``policy``. Raises ``ValueError`` if invalid."""
    try:
        return _ANSWER_PROMPT_BY_POLICY[policy]
    except KeyError as err:
        valid = sorted(_ANSWER_PROMPT_BY_POLICY)
        raise ValueError(
            f"Unknown longmemeval_answer_prompt policy: {policy!r}. "
            f"Expected one of {valid}."
        ) from err


def _resolve_answer_prompt_policy(
    cli_value: str | None, config_path: str | None
) -> str:
    """Resolve answer-prompt policy: CLI > config > Pydantic default.

    ``cli_value`` is ``None`` when the operator did not pass
    ``--longmemeval-answer-prompt``. Falls back to
    ``retrieval_agent.longmemeval_answer_prompt`` from ``config_path``
    (Pydantic default = ``"LME_origin_prompt"`` — verbatim upstream).
    """
    if cli_value is not None:
        return cli_value
    if config_path is not None:
        from memmachine_server.common.configuration import Configuration

        try:
            config = Configuration.load_yml_file(config_path)
        except FileNotFoundError:
            return "LME_origin_prompt"
        return config.retrieval_agent.longmemeval_answer_prompt
    return "LME_origin_prompt"


def _load_longmemeval_question_prefix_enabled(config_path: str) -> bool:
    """Return whether to prepend ``User: `` to LongMemEval questions."""
    config_file = Path(config_path)
    if not config_file.exists():
        return False

    with config_file.open("r", encoding="utf-8") as file:
        raw_conf = yaml.safe_load(file) or {}

    if not isinstance(raw_conf, dict):
        return False

    evaluation_conf = raw_conf.get("evaluation", {})
    if not isinstance(evaluation_conf, dict):
        return False

    longmemeval_conf = evaluation_conf.get("longmemeval", {})
    if not isinstance(longmemeval_conf, dict):
        return False

    return bool(longmemeval_conf.get("prepend_user_prefix", False))


def _split_chunks(text: str, max_chars: int = 3000) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    text_len = len(normalized)
    while start < text_len:
        end = min(start + max_chars, text_len)
        if end < text_len:
            split_at = normalized.rfind(" ", start, end)
            if split_at > start + (max_chars // 2):
                end = split_at
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def _collect_turn_contents(sample: dict[str, Any]) -> list[str]:
    turns: list[str] = []
    for session in sample.get("haystack_sessions", []) or []:
        for turn in session or []:
            content = str(turn.get("content", "")).strip()
            if content:
                turns.extend(_split_chunks(content))
    return turns


def _collect_supporting_facts(sample: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    for session in sample.get("haystack_sessions", []) or []:
        for turn in session or []:
            if turn.get("has_answer"):
                content = str(turn.get("content", "")).strip()
                if content:
                    facts.append(content)
    return facts


def _set_safe_embedder_request_limits(memory: Any) -> None:
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
        # Keep cluster size below model token ceiling for embedding requests.
        embedder.max_total_input_length_per_request = 30000


async def longmemeval_ingest(
    dataset: list[dict[str, Any]],
    config_path: str,
    session_id: str,
):
    from memmachine_server.common.episode_store import Episode

    from evaluation.utils import agent_utils

    t1 = datetime.now(UTC)
    added_content = 0
    per_batch = 1000

    resource_manager = agent_utils.load_eval_config(config_path)
    memory, _, _ = await agent_utils.init_memmachine_params(
        resource_manager=resource_manager,
        session_id=session_id,
    )
    _set_safe_embedder_request_limits(memory)

    all_content: list[str] = []
    for sample in dataset:
        all_content.extend(_collect_turn_contents(sample))

    episodes: list[Episode] = []
    for content in all_content:
        added_content += 1
        ts = t1 + timedelta(seconds=added_content)
        episodes.append(
            Episode(
                uid=str(uuid4()),
                content=content,
                session_key=session_id,
                created_at=ts,
                producer_id="user",
                producer_role="user",
            )
        )

        if added_content % per_batch == 0 or content == all_content[-1]:
            print(f"Adding batch of {len(episodes)} episodes...")
            t = time.perf_counter()
            await memory.add_memory_episodes(episodes=episodes)
            print(
                f"Gathered and added {len(episodes)} episodes in {(time.perf_counter() - t):.3f}s"
            )
            print(f"Total added episodes: {added_content}")
            print(f"Total episodes processed: {added_content}/{len(all_content)}")
            episodes = []

    print(
        f"Completed LongMemEval ingestion, added {len(dataset)} questions, {added_content} episodes."
    )


async def longmemeval_search(
    dataset: list[dict[str, Any]],
    config_path: str,
    session_id: str,
    eval_result_path: str | None = None,
    agent_name: str = "ToolSelectAgent",
    pure_llm: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    search_limit: int = DEFAULT_SEARCH_LIMIT,
    answer_prompt_policy: str = "LME_origin_prompt",
):
    from evaluation.utils import agent_utils

    tasks = []
    attribute_matrix = agent_utils.init_attribute_matrix()
    responses: list[tuple[str, dict[str, Any]]] = []
    num_searched = 0

    resource_manager = agent_utils.load_eval_config(config_path)
    memory, answer_model, query_agent = await agent_utils.init_memmachine_params(
        resource_manager=resource_manager,
        session_id=session_id,
        agent_name=agent_name,
    )
    _set_safe_embedder_request_limits(memory)

    prepend_user_prefix = _load_longmemeval_question_prefix_enabled(config_path)
    answer_prompt = _select_answer_prompt(answer_prompt_policy)
    needs_question_date = "{question_date}" in answer_prompt

    for sample in dataset:
        question = str(sample.get("question", "")).strip()
        if not question:
            continue
        if prepend_user_prefix:
            question = f"User: {question}"

        answer = str(sample.get("answer", "")).strip()

        supporting_facts = _collect_supporting_facts(sample)
        all_content = _collect_turn_contents(sample)
        full_content = "\n".join(all_content)

        prompt_extra: dict[str, str] | None = None
        if needs_question_date:
            prompt_extra = {
                "question_date": _format_question_date(sample.get("question_date", ""))
            }

        tasks.append(
            agent_utils.process_question(
                answer_prompt=answer_prompt,
                query_agent=query_agent,
                memory=memory,
                answer_model=answer_model,
                question=question,
                answer=answer,
                category=str(sample.get("question_type", "unknown")),
                supporting_facts=supporting_facts,
                search_limit=search_limit,
                full_content=full_content if pure_llm else None,
                extra_attributes={
                    "question_id": sample.get("question_id", ""),
                    "split": sample.get("split", ""),
                },
                prompt_extra=prompt_extra,
            )
        )

        if len(tasks) >= concurrency or sample == dataset[-1]:
            responses.extend(await asyncio.gather(*tasks))
            num_searched += len(tasks)
            print(
                f"Completed LongMemEval searching {num_searched}/{len(dataset)} questions..."
            )
            tasks = []

    results: dict[str, Any] = {}
    agent_utils.update_results(responses, attribute_matrix, results)
    agent_utils.update_final_attribute_matrix(
        "longmemeval",
        attribute_matrix,
        results,
    )

    if eval_result_path is not None:
        with open(eval_result_path, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=4)


async def longmemeval_delete(config_path: str, session_id: str):
    from evaluation.utils import agent_utils

    resource_manager = agent_utils.load_eval_config(config_path)
    memory, _, _ = await agent_utils.init_memmachine_params(
        resource_manager=resource_manager,
        session_id=session_id,
    )
    _set_safe_embedder_request_limits(memory)

    print(f"Deleting episodes for session_id='{session_id}'...")
    await memory.delete_session_episodes()
    print("Completed LongMemEval delete.")


def load_longmemeval_dataset(length: int, split: str) -> list[dict[str, Any]]:
    split_file = split if split.endswith(".json") else f"{split}.json"

    records: list[dict[str, Any]] | None = None

    # Primary path: use datasets for consistency with existing benchmark scripts.
    try:
        from datasets import load_dataset

        dataset = load_dataset("xiaowu0162/longmemeval-cleaned", split=split)
        num_rows = min(length, len(dataset))
        records = dataset.select(range(num_rows)).to_list()
    except Exception as err:
        # Fallback path: download split JSON directly when datasets loader
        # hits schema incompatibilities.
        print(f"datasets loader failed ({type(err).__name__}), using JSON fallback...")
        from huggingface_hub import hf_hub_download

        data_path = hf_hub_download(
            repo_id="xiaowu0162/longmemeval-cleaned",
            repo_type="dataset",
            filename=split_file,
        )
        with open(data_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)
        if not isinstance(raw_data, list):
            raise TypeError(
                f"Expected list data in {split_file}, got {type(raw_data).__name__}."
            ) from err
        records = raw_data[:length]

    normalized_records: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue

        normalized_record = dict(record)
        normalized_record["question"] = str(normalized_record.get("question", ""))
        normalized_record["answer"] = str(normalized_record.get("answer", ""))
        normalized_record.setdefault("question_type", "unknown")
        normalized_record.setdefault("haystack_sessions", [])
        # ``question_date`` feeds the answer prompt's ``Current Date:`` line
        # via ``_format_question_date()`` (used by both LME_origin_prompt
        # default and the memmachine_original opt-in body). Defensive default
        # keeps the prompt renderable on synthetic fixtures.
        normalized_record["question_date"] = str(
            normalized_record.get("question_date", "") or ""
        )
        normalized_record["split"] = split
        normalized_records.append(normalized_record)

    return normalized_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--eval-result-path",
        required=False,
        help="Path to save evaluation results",
        default=None,
    )
    parser.add_argument(
        "--run-type",
        required=False,
        help="Type of run: ingest, search, or delete",
        default="search",
    )
    parser.add_argument(
        "--length",
        required=False,
        help="Number of records to run",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--split-name",
        required=False,
        help="Dataset split name from xiaowu0162/longmemeval-cleaned",
        default="longmemeval_s_cleaned",
    )
    parser.add_argument(
        "--test-target",
        required=True,
        help="Testing with memmachine(bypass agent), retrieval_agent, or pure llm",
        choices=["memmachine", "retrieval_agent", "llm"],
    )
    parser.add_argument(
        "--session-id",
        required=False,
        help="Session id used for both ingestion and retrieval",
        default="longmemeval_group",
    )
    parser.add_argument(
        "--config-path",
        required=True,
        help="Path to configuration.yml",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=DEFAULT_CONCURRENCY,
        help="Maximum number of concurrent LongMemEval search requests",
    )
    parser.add_argument(
        "--search-limit",
        type=positive_int,
        default=DEFAULT_SEARCH_LIMIT,
        help="Maximum number of episodes to retrieve per question",
    )
    parser.add_argument(
        "--longmemeval-answer-prompt",
        choices=sorted(_ANSWER_PROMPT_BY_POLICY),
        default=None,
        help=(
            "LongMemEval answer prompt body. 'LME_origin_prompt' (default) "
            "is a verbatim copy of xiaowu0162/LongMemEval upstream no-CoT; "
            "'LME_origin_cot_prompt' is the upstream CoT branch (step-by-step "
            "reasoning, more output tokens); 'memmachine_original' is a "
            "hybrid with MemMachine reasoning guides; 'edwin1' is an 8-rule "
            "reasoning prompt; 'edwin3' is a KNOWLEDGE UPDATES + PLANNED "
            "ACTIONS + MOST RECENT USER INPUT priority variant. When omitted, "
            "falls back to "
            "retrieval_agent.longmemeval_answer_prompt from configuration.yml."
        ),
    )
    return parser


async def main():
    args = build_parser().parse_args()

    if args.run_type == "delete":
        await longmemeval_delete(args.config_path, args.session_id)
        return

    dataset = load_longmemeval_dataset(args.length, args.split_name)

    if args.run_type == "ingest":
        await longmemeval_ingest(dataset, args.config_path, args.session_id)
    elif args.run_type == "search":
        answer_prompt_policy = _resolve_answer_prompt_policy(
            args.longmemeval_answer_prompt, args.config_path
        )

        print("Starting LongMemEval test...")
        print(f"Evaluation result path: {args.eval_result_path}")
        print(f"Length: {args.length}")
        print(f"Dataset split: {args.split_name}")
        print(f"Test target: {args.test_target}")
        print(f"Concurrency: {args.concurrency}")
        print(f"Search limit: {args.search_limit}")
        print(f"[longmemeval] longmemeval_answer_prompt={answer_prompt_policy}")

        agent_name = (
            "MemMachineAgent" if args.test_target == "memmachine" else "ToolSelectAgent"
        )
        await longmemeval_search(
            dataset,
            args.config_path,
            args.session_id,
            args.eval_result_path,
            agent_name,
            args.test_target == "llm",
            args.concurrency,
            args.search_limit,
            answer_prompt_policy=answer_prompt_policy,
        )
    else:
        raise ValueError(
            f"Unknown run type: {args.run_type}, please use 'ingest', 'search', or 'delete'."
        )


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
