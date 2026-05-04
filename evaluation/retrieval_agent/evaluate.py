# This is adapted from Mem0 (https://github.com/mem0ai/mem0/blob/main/evaluation/evals.py).
# It is modified to only report LLM judge scores.

import argparse
import concurrent.futures
import json
import sys
import threading
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from evaluation.retrieval_agent.cli_utils import positive_int  # noqa: E402
from evaluation.retrieval_agent.llm_judge import (  # noqa: E402
    create_judge_fn,
    evaluate_llm_judge,
    evaluate_llm_judge_longmemeval,
)

# LongMemEval question_type values (xiaowu0162/longmemeval-cleaned). When the
# input row's category matches one of these, we route to the original
# task-specific judge instead of the default ACCURACY_PROMPT path. Other
# datasets (LOCOMO, Wiki, HotpotQA) use unrelated category values and remain
# on the default path.
_LONGMEMEVAL_TASKS = frozenset(
    {
        "single-session-user",
        "single-session-assistant",
        "multi-session",
        "temporal-reasoning",
        "knowledge-update",
        "single-session-preference",
    }
)


def process_sample(
    group_key: str,
    item: dict,
    json_call_fn,
    get_text_call_fn,
    longmemeval_yesno_policy: str,
):
    question = str(item["question"])
    locomo_answer = str(item["golden_answer"])
    response = str(item["model_answer"])
    category = str(item["category"])

    # Skip category 5
    if category == "5":
        return group_key, None

    if category in _LONGMEMEVAL_TASKS:
        llm_score = evaluate_llm_judge_longmemeval(
            question,
            locomo_answer,
            response,
            category,
            str(item.get("question_id", "")),
            get_text_call_fn(),
            longmemeval_yesno_policy,
        )
    else:
        llm_score = evaluate_llm_judge(question, locomo_answer, response, json_call_fn)

    res = {
        "question": question,
        "answer": locomo_answer,
        "response": response,
        "category": category,
        "llm_score": llm_score,
    }
    for key, val in item.items():
        if key not in [
            "question",
            "golden_answer",
            "model_answer",
            "category",
        ]:
            if type(val) is float:
                val = round(val, 3)
            res[key] = val

    return group_key, res


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate results")
    parser.add_argument(
        "--data-path",
        type=str,
        default="results/rag_results_500_k1.json",
        help="Path to the input dataset file",
    )
    parser.add_argument(
        "--target-path",
        type=str,
        default="evaluation_metrics.json",
        help="Path to save the evaluation results",
    )
    parser.add_argument(
        "--max_workers",
        type=positive_int,
        default=30,
        help="Maximum number of worker threads",
    )
    parser.add_argument(
        "--config-path",
        type=str,
        required=True,
        help="Path to configuration.yml (used to select the judge LLM)",
    )
    parser.add_argument(
        "--longmemeval-yesno-policy",
        type=str,
        choices=["lenient", "strict"],
        default=None,
        help=(
            "Parser policy for LongMemEval yes/no judge replies. When unset, "
            "falls back to retrieval_agent.longmemeval_yesno_policy in "
            "configuration.yml (default: lenient)."
        ),
    )
    return parser


def _resolve_yesno_policy(args, config_path: str) -> str:
    """CLI flag wins; otherwise read configuration.yml's RetrievalAgentConf default."""
    if args.longmemeval_yesno_policy is not None:
        return args.longmemeval_yesno_policy
    from memmachine_server.common.configuration import Configuration

    conf = Configuration.load_yml_file(config_path)
    return conf.retrieval_agent.longmemeval_yesno_policy


def main():
    args = build_parser().parse_args()

    with open(args.data_path, "r") as f:
        data = json.load(f)

    json_call_fn = create_judge_fn(args.config_path)
    yesno_policy = _resolve_yesno_policy(args, args.config_path)
    print(f"[evaluate] longmemeval_yesno_policy={yesno_policy}")

    results = defaultdict(list)
    results_lock = threading.Lock()
    sample_tasks: list[tuple[str, dict]] = [
        (group_key, item) for group_key, items in data.items() for item in items
    ]

    text_call_fn = None
    text_call_fn_lock = threading.Lock()

    def get_text_call_fn():
        nonlocal text_call_fn
        if text_call_fn is None:
            with text_call_fn_lock:
                if text_call_fn is None:
                    text_call_fn = create_judge_fn(args.config_path, json_mode=False)
        return text_call_fn

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.max_workers
    ) as executor:
        futures = [
            executor.submit(
                process_sample,
                group_key,
                item,
                json_call_fn,
                get_text_call_fn,
                yesno_policy,
            )
            for group_key, item in sample_tasks
        ]

        for future in tqdm(
            concurrent.futures.as_completed(futures), total=len(futures)
        ):
            group_key, sample_result = future.result()
            if sample_result is None:
                continue
            with results_lock:
                results[group_key].append(sample_result)

            with open(args.target_path, "w") as f:
                json.dump(results, f, indent=4)

    print(f"Results saved to {args.target_path}")


if __name__ == "__main__":
    main()
