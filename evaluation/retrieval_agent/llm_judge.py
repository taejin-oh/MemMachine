# This is adapted from Mem0 (https://github.com/mem0ai/mem0/blob/main/evaluation/metrics/llm_judge.py).
# It is modified to remove dependency on the Mem0 library and formatted.

import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Callable

import json_repair
import numpy as np

logger = logging.getLogger(__name__)

_MAX_JUDGE_ATTEMPTS = 2

ACCURACY_PROMPT = """
Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given the following data:
    (1) a question (posed by one user to another user),
    (2) a 'gold' (ground truth) answer,
    (3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic, for example:
Question: Do you remember what I got the last time I went to Hawaii?
Gold answer: A shell necklace
The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

Now it's time for the real question:
Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}

First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.
Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""

# LongMemEval task-specific judge templates copied verbatim from
# https://github.com/xiaowu0162/LongMemEval (src/evaluation/evaluate_qa.py).
_LME_TEMPLATE_GENERAL = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate "
    "steps to get the correct answer, you should also answer yes. If the response only "
    "contains a subset of the information required by the answer, answer no. "
    "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)
_LME_TEMPLATE_TEMPORAL = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate "
    "steps to get the correct answer, you should also answer yes. If the response only "
    "contains a subset of the information required by the answer, answer no. "
    "In addition, do not penalize off-by-one errors for the number of days. If the question "
    "asks for the number of days/weeks/months, etc., and the model makes off-by-one errors "
    "(e.g., predicting 19 days when the answer is 18), the model's response is still correct. "
    "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)
_LME_TEMPLATE_KNOWLEDGE_UPDATE = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response contains some previous information along with an updated answer, the "
    "response should be considered as correct as long as the updated answer is the required "
    "answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)
_LME_TEMPLATE_PREFERENCE = (
    "I will give you a question, a rubric for desired personalized response, and a response "
    "from a model. Please answer yes if the response satisfies the desired response. "
    "Otherwise, answer no. The model does not need to reflect all the points in the rubric. "
    "The response is correct as long as it recalls and utilizes the user's personal "
    "information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only."
)
_LME_TEMPLATE_ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. "
    "Please answer yes if the model correctly identifies the question as unanswerable. "
    "The model could say that the information is incomplete, or some other information is "
    "given but the asked information is not."
    "\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\n"
    "Does the model correctly identify the question as unanswerable? Answer yes or no only."
)

_LME_GENERAL_TASKS = frozenset(
    {"single-session-user", "single-session-assistant", "multi-session"}
)


def get_anscheck_prompt(
    task: str,
    question: str,
    answer: str,
    response: str,
    abstention: bool = False,
) -> str:
    """Build the LongMemEval task-specific judge prompt (original wording).

    Mirrors ``get_anscheck_prompt`` in LongMemEval's ``evaluate_qa.py``. Raises
    ``ValueError`` for unknown tasks so the caller can decide how to route.
    """
    if abstention:
        return _LME_TEMPLATE_ABSTENTION.format(question, answer, response)
    if task in _LME_GENERAL_TASKS:
        return _LME_TEMPLATE_GENERAL.format(question, answer, response)
    if task == "temporal-reasoning":
        return _LME_TEMPLATE_TEMPORAL.format(question, answer, response)
    if task == "knowledge-update":
        return _LME_TEMPLATE_KNOWLEDGE_UPDATE.format(question, answer, response)
    if task == "single-session-preference":
        return _LME_TEMPLATE_PREFERENCE.format(question, answer, response)
    raise ValueError(f"Unsupported LongMemEval task: {task!r}")


def create_judge_fn(
    config_path: str, json_mode: bool = True
) -> Callable[[str], str]:
    """Build a synchronous callable that sends a prompt to the configured judge LLM.

    Reads ``retrieval_agent.judge_llm_model`` first and falls back to
    ``retrieval_agent.llm_model`` so configurations without an explicit judge
    pointer continue to work. Supports providers: ``openai-responses``,
    ``openai-chat-completions``, and ``amazon-bedrock``.

    Args:
        config_path: Path to configuration.yml.

    Returns:
        A callable ``fn(prompt: str) -> str`` that returns the raw text reply.
    """
    from memmachine_server.common.configuration import Configuration

    config = Configuration.load_yml_file(config_path)
    lms = config.resources.language_models
    # `or` (not `is not None`) so that an empty-string judge_llm_model is
    # treated as unset and falls back to the answer llm_model — matches the
    # documented "unset → fallback" intent.
    llm_id = config.retrieval_agent.judge_llm_model or config.retrieval_agent.llm_model
    if not llm_id:
        raise ValueError(
            "judge LLM is not configured: set retrieval_agent.judge_llm_model "
            "or retrieval_agent.llm_model in configuration.yml"
        )

    if llm_id in lms.openai_responses_language_model_confs:
        from openai import OpenAI

        conf = lms.openai_responses_language_model_confs[llm_id]
        client = OpenAI(
            api_key=conf.api_key.get_secret_value(),
            base_url=conf.base_url,
        )
        model_name = conf.model

        if json_mode:

            def _call_responses(prompt: str) -> str:
                resp = client.responses.create(
                    model=model_name,
                    input=prompt,
                    text={"format": {"type": "json_object"}},
                )
                return resp.output_text or ""

        else:
            # Plain-text mode for LongMemEval: original judge expects a short
            # "yes"/"no" reply with no JSON wrapper. max_output_tokens mirrors
            # the original (evaluate_qa.py:109).
            def _call_responses(prompt: str) -> str:
                resp = client.responses.create(
                    model=model_name,
                    input=prompt,
                    max_output_tokens=10,
                )
                return resp.output_text or ""

        return _call_responses

    if llm_id in lms.openai_chat_completions_language_model_confs:
        from openai import OpenAI

        conf = lms.openai_chat_completions_language_model_confs[llm_id]
        client = OpenAI(
            api_key=conf.api_key.get_secret_value(),
            base_url=conf.base_url,
        )
        model_name = conf.model

        if json_mode:

            def _call_chat(prompt: str) -> str:
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content

        else:
            # Plain-text mode for LongMemEval (see _call_responses above).
            def _call_chat(prompt: str) -> str:
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=10,
                )
                return resp.choices[0].message.content

        return _call_chat

    if llm_id in lms.amazon_bedrock_language_model_confs:
        # Bedrock branch never imposed JSON, so json_mode is a no-op here.
        import boto3

        conf = lms.amazon_bedrock_language_model_confs[llm_id]
        bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=conf.region,
            aws_access_key_id=(
                conf.aws_access_key_id.get_secret_value()
                if conf.aws_access_key_id
                else None
            ),
            aws_secret_access_key=(
                conf.aws_secret_access_key.get_secret_value()
                if conf.aws_secret_access_key
                else None
            ),
        )
        model_id = conf.model_id

        def _call_bedrock(prompt: str) -> str:
            resp = bedrock_client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            return resp["output"]["message"]["content"][0]["text"]

        return _call_bedrock

    known_ids = (
        set(lms.openai_responses_language_model_confs)
        | set(lms.openai_chat_completions_language_model_confs)
        | set(lms.amazon_bedrock_language_model_confs)
    )
    if llm_id not in known_ids:
        raise ValueError(
            f"Judge LLM '{llm_id}' is not defined under resources.language_models. "
            f"Available IDs: {sorted(known_ids)}."
        )
    # Defense-in-depth: today LanguageModelsConf only knows about the three
    # provider tables we already iterated, so this branch is unreachable from
    # any Pydantic-validated configuration. Kept so future provider additions
    # at the schema layer surface as a clear judge-side error rather than a
    # silent miss.
    raise ValueError(
        f"Judge LLM '{llm_id}' is defined, but its provider is not supported "
        "by llm_judge.py. Supported judge providers: openai-responses, "
        "openai-chat-completions, amazon-bedrock."
    )


def evaluate_llm_judge(
    question: str,
    gold_answer: str,
    generated_answer: str,
    call_fn: Callable[[str], str],
) -> int:
    """Evaluate a generated answer against the gold answer using an LLM judge.

    Args:
        question: The question being evaluated.
        gold_answer: The ground-truth answer.
        generated_answer: The model-produced answer.
        call_fn: A synchronous callable returned by :func:`create_judge_fn`.

    Returns:
        1 if the answer is CORRECT, 0 if WRONG.
    """
    prompt = ACCURACY_PROMPT.format(
        question=question,
        gold_answer=gold_answer,
        generated_answer=generated_answer,
    )
    for attempt in range(1, _MAX_JUDGE_ATTEMPTS + 1):
        raw = call_fn(prompt)
        label: str | None = None
        try:
            result = json_repair.loads(raw)
            raw_label = result.get("label") if isinstance(result, dict) else None
            if isinstance(raw_label, str):
                normalized = raw_label.strip().upper()
                if normalized in {"CORRECT", "WRONG"}:
                    label = normalized
        except Exception:
            label = None
        if label is not None:
            return 1 if label == "CORRECT" else 0
        if attempt < _MAX_JUDGE_ATTEMPTS:
            logger.warning(
                "LLM judge missing or invalid 'label' on attempt %d/%d, retrying",
                attempt,
                _MAX_JUDGE_ATTEMPTS,
            )
    logger.error(
        "LLM judge failed to return a valid 'label' after %d attempts; defaulting to WRONG",
        _MAX_JUDGE_ATTEMPTS,
    )
    return 0


def evaluate_llm_judge_longmemeval(
    question: str,
    gold_answer: str,
    generated_answer: str,
    question_type: str,
    question_id: str,
    call_fn: Callable[[str], str],
) -> int:
    """LongMemEval judge: task-specific prompt + plain-text yes/no scoring.

    Mirrors the original ``evaluate_qa.py`` pipeline. Abstention is detected
    from the ``_abs`` substring in ``question_id``. ``call_fn`` should be built
    with ``create_judge_fn(..., json_mode=False)``.
    """
    abstention = "_abs" in question_id
    prompt = get_anscheck_prompt(
        question_type, question, gold_answer, generated_answer, abstention=abstention
    )
    raw = call_fn(prompt) or ""
    return 1 if "yes" in raw.lower() else 0


def main():
    """Main function to evaluate RAG results using LLM judge."""
    parser = argparse.ArgumentParser(description="Evaluate RAG results using LLM judge")
    parser.add_argument(
        "--input_file",
        type=str,
        default="results/default_run_v4_k30_new_graph.json",
        help="Path to the input dataset file",
    )
    parser.add_argument(
        "--config-path",
        type=str,
        required=True,
        help="Path to configuration.yml",
    )

    args = parser.parse_args()

    call_fn = create_judge_fn(args.config_path)
    dataset_path = args.input_file
    output_path = f"results/llm_judge_{dataset_path.split('/')[-1]}"

    with open(dataset_path, "r") as f:
        data = json.load(f)

    LLM_JUDGE = defaultdict(list)
    RESULTS = defaultdict(list)

    index = 0
    for k, v in data.items():
        for x in v:
            question = x["question"]
            gold_answer = x["answer"]
            generated_answer = x["response"]
            category = x["category"]

            if int(category) == 5:
                continue

            label = evaluate_llm_judge(question, gold_answer, generated_answer, call_fn)
            LLM_JUDGE[category].append(label)

            RESULTS[index].append(
                {
                    "question": question,
                    "gt_answer": gold_answer,
                    "response": generated_answer,
                    "category": category,
                    "llm_label": label,
                }
            )

            with open(output_path, "w") as f:
                json.dump(RESULTS, f, indent=4)

            print("All categories accuracy:")
            for cat, results in LLM_JUDGE.items():
                if results:
                    print(
                        f"  Category {cat}: {np.mean(results):.4f} "
                        f"({sum(results)}/{len(results)})"
                    )
            print("------------------------------------------")
        index += 1

    with open(output_path, "w") as f:
        json.dump(RESULTS, f, indent=4)

    print("PATH: ", dataset_path)
    print("------------------------------------------")
    for k, v in LLM_JUDGE.items():
        print(k, np.mean(v))


if __name__ == "__main__":
    main()
