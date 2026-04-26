#!/usr/bin/env python3
"""Generate a single run-config YAML by merging base + problem + CLI/JSON overrides.

Two modes for the underlying configuration.yml:

  * mode=profile  — combine configs/profiles/models/{name}.yaml +
                    configs/profiles/dbs/{name}.yaml into
                    configs/generated/{run_name}_configuration.yml.
  * mode=existing — point at a configuration.yml the user already has.

Examples (see docs/USAGE.md):

  python scripts/generate_config.py \
      --problem 4 --run-name p4_pilot \
      --model-profile _example --db-profile _example \
      --k-list 10,20

  python scripts/generate_config.py --from-json configs/runs/_example.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._merge import deep_merge, dump_yaml, load_yaml  # noqa: E402

CONFIGS_DIR = REPO_ROOT / "configs"


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--problem", type=int, choices=[2, 3, 4, 5, 6, 12], help="Problem number"
    )
    parser.add_argument(
        "--run-name", help="Output run name (used in filename and results/ dir)"
    )

    # configuration.yml mode
    parser.add_argument("--model-profile", help="configs/profiles/models/{name}.yaml")
    parser.add_argument("--db-profile", help="configs/profiles/dbs/{name}.yaml")
    parser.add_argument(
        "--use-existing-config",
        help="Path to an existing configuration.yml. If set, mode becomes 'existing'.",
    )

    # Sweep / fixed override (most common)
    parser.add_argument(
        "--k-list", help="Comma-separated search_limit list. Ex: 10,20,30"
    )
    parser.add_argument("--judge-model", help="judge.llm_model_id override")
    parser.add_argument(
        "--length", type=int, help="benchmark.length override (dataset slice)"
    )
    parser.add_argument("--n-runs", type=int, help="Repeat count")
    parser.add_argument("--seed", type=int, help="Random seed")

    # #6 / #12 reuse-run
    parser.add_argument(
        "--reuse-run", help="For p6/p12: name of an earlier run to analyze"
    )

    # Bulk JSON override (highest precedence)
    parser.add_argument("--from-json", help="Path to JSON file with overrides")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Override builders
# ---------------------------------------------------------------------------


def cli_to_overrides(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}

    if args.problem is not None:
        out["problem"] = args.problem
    if args.run_name:
        out["run_name"] = args.run_name

    cfg: dict[str, Any] = {}
    if args.use_existing_config:
        cfg["mode"] = "existing"
        cfg["existing_path"] = args.use_existing_config
    else:
        if args.model_profile:
            cfg["model_profile"] = args.model_profile
        if args.db_profile:
            cfg["db_profile"] = args.db_profile
    if cfg:
        out["configuration"] = cfg

    if args.k_list:
        out.setdefault("sweep", {})["search_limit"] = [
            int(x) for x in args.k_list.split(",")
        ]

    if args.judge_model:
        out["judge"] = {"llm_model_id": args.judge_model}

    if args.length is not None:
        out.setdefault("benchmark", {})["length"] = args.length

    if args.n_runs is not None:
        out["n_runs"] = args.n_runs
    if args.seed is not None:
        out["seed"] = args.seed

    if args.reuse_run:
        out["reuse_run"] = args.reuse_run

    return out


def load_json_overrides(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop("_comment", None)
    return data


# ---------------------------------------------------------------------------
# configuration.yml generation (mode=profile)
# ---------------------------------------------------------------------------


def build_configuration_yml(
    model_profile: dict[str, Any], db_profile: dict[str, Any]
) -> dict[str, Any]:
    """Combine model + db profile dicts into a full MemMachine configuration.yml dict.

    Mirrors the structure documented in evaluation/retrieval_agent/README.md (Sample 1).
    """
    embedder = model_profile["embedder"]
    reranker = model_profile["reranker"]
    llm_model = model_profile["llm_model"]
    vgs = db_profile["vector_graph_store"]
    profile_db = db_profile["profile_storage"]

    return {
        "episode_store": {
            "database": profile_db["id"],
            "with_count_cache": True,
        },
        "episodic_memory": {
            "enabled": True,
            "long_term_memory": {
                "embedder": embedder["id"],
                "reranker": reranker["id"],
                "vector_graph_store": vgs["id"],
                # message_sentence_chunking 은 run_pipeline 이 sweep 별로 in-place 갱신
                "message_sentence_chunking": False,
            },
            "long_term_memory_enabled": True,
            "short_term_memory": {
                "llm_model": llm_model["id"],
                "message_capacity": 500,
                "summary_prompt_system": "You are an AI agent that summarizes episodes.",
                "summary_prompt_user": (
                    "Summarize: {summary}\n{episodes}\nYour summary (under {max_length} words):"
                ),
            },
            "short_term_memory_enabled": True,
        },
        "logging": {"level": "INFO"},
        "retrieval_agent": {
            "llm_model": llm_model["id"],
            "reranker": reranker["id"],
        },
        "semantic_memory": {
            "enabled": False,
            "config_database": profile_db["id"],
        },
        "resources": {
            "databases": {
                vgs["id"]: {"provider": vgs["provider"], "config": vgs["config"]},
                profile_db["id"]: {
                    "provider": profile_db["provider"],
                    "config": profile_db["config"],
                },
            },
            "embedders": {
                embedder["id"]: {
                    "provider": embedder["provider"],
                    "config": embedder["config"],
                },
            },
            "language_models": {
                llm_model["id"]: {
                    "provider": llm_model["provider"],
                    "config": llm_model["config"],
                },
            },
            "rerankers": {
                reranker["id"]: {
                    "provider": reranker["provider"],
                    "config": reranker["config"],
                },
            },
        },
        "session_manager": {"database": profile_db["id"]},
        # 평가 토글 (run_pipeline 이 sweep 별로 in-place 갱신할 수 있음)
        "evaluation": {"longmemeval": {"prepend_user_prefix": False}},
    }


def maybe_generate_configuration_yml(run_cfg: dict[str, Any]) -> str | None:
    """If mode=profile, generate configs/generated/{run_name}_configuration.yml.

    Returns the absolute path of the generated file, or None for mode=existing.
    """
    cfg = run_cfg.get("configuration", {})
    mode = cfg.get("mode", "profile")

    if mode == "existing":
        path = cfg.get("existing_path")
        if not path:
            raise ValueError(
                "configuration.mode=existing but configuration.existing_path is empty"
            )
        return None

    if mode != "profile":
        raise ValueError(f"Unknown configuration.mode: {mode!r}")

    model_name = cfg.get("model_profile")
    db_name = cfg.get("db_profile")
    if not model_name or not db_name:
        raise ValueError(
            "mode=profile requires both configuration.model_profile and configuration.db_profile"
        )

    model_profile = load_yaml(
        CONFIGS_DIR / "profiles" / "models" / f"{model_name}.yaml"
    )
    db_profile = load_yaml(CONFIGS_DIR / "profiles" / "dbs" / f"{db_name}.yaml")
    configuration = build_configuration_yml(model_profile, db_profile)

    generated_dir = REPO_ROOT / cfg.get("generated_dir", "configs/generated")
    out_path = generated_dir / f"{run_cfg['run_name']}_configuration.yml"
    dump_yaml(configuration, out_path)
    return str(out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_")


def main() -> int:
    args = parse_args()

    base = load_yaml(CONFIGS_DIR / "base.yaml")
    json_overrides = load_json_overrides(args.from_json)
    cli_overrides = cli_to_overrides(args)

    # Determine problem (CLI > JSON > error)
    problem = cli_overrides.get("problem") or json_overrides.get("problem")
    if problem is None:
        print("ERROR: --problem (or 'problem' in JSON) is required", file=sys.stderr)
        return 2
    problem_path = CONFIGS_DIR / "problems" / f"p{problem}.yaml"
    if not problem_path.exists():
        print(f"ERROR: problem yaml not found: {problem_path}", file=sys.stderr)
        return 2
    problem_yaml = load_yaml(problem_path)

    merged = deep_merge(base, problem_yaml, json_overrides, cli_overrides)

    # Auto-derive run_name if missing
    if not merged.get("run_name"):
        merged["run_name"] = slugify(f"p{problem}_run")

    # Generate configuration.yml if mode=profile
    generated_path = maybe_generate_configuration_yml(merged)
    if generated_path:
        merged.setdefault("configuration", {})["generated_path"] = generated_path

    # Persist run config
    run_path = CONFIGS_DIR / "runs" / f"{merged['run_name']}.yaml"
    dump_yaml(merged, run_path)

    print(f"[ok] run config: {run_path}")
    if generated_path:
        print(f"[ok] configuration.yml: {generated_path}")
    elif merged.get("configuration", {}).get("mode") == "existing":
        print(
            f"[ok] using existing configuration: {merged['configuration']['existing_path']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
