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
    parser.add_argument(
        "--n-runs", type=int, help="Repeat count (only n_runs=1 supported)"
    )

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


def _validate_and_normalize_rerankers(
    model_profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Validate model profile rerankers and return (normalized_list, primary_id).

    Each normalized entry has 'id', 'provider', 'config' (defaulted to {}).
    Raises ValueError with actionable messages on schema/consistency issues.
    """
    if "reranker" in model_profile:
        if "rerankers" in model_profile:
            raise ValueError(
                "legacy 'reranker:' is no longer supported. Remove it and use "
                "only 'rerankers:' list."
            )
        raise ValueError(
            "model profile schema changed: use 'rerankers:' (list) instead of "
            "legacy 'reranker:' (dict). Wrap the existing block as a single-item "
            "list:\n  rerankers:\n    - <existing reranker fields>\n"
            "primary_reranker is optional (defaults to the first list item)."
        )
    raw_list = model_profile.get("rerankers")
    if raw_list is None:
        raise ValueError("model profile must define 'rerankers' as a non-empty list")
    if not isinstance(raw_list, list):
        raise ValueError(
            f"model profile 'rerankers' must be a list, got {type(raw_list).__name__}"
        )
    if not raw_list:
        raise ValueError(
            "model profile 'rerankers' must be a non-empty list of entries"
        )

    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw_list):
        if not isinstance(entry, dict):
            raise ValueError(
                f"rerankers[{idx}] must be a mapping, got {type(entry).__name__}"
            )
        rid = entry.get("id")
        provider = entry.get("provider")
        if not rid:
            raise ValueError(f"rerankers[{idx}] is missing required 'id'")
        if not provider:
            raise ValueError(
                f"rerankers[{idx}] (id={rid!r}) is missing required 'provider'"
            )
        if rid in seen_ids:
            raise ValueError(f"rerankers contains duplicate id: {rid!r}")
        config = entry.get("config")
        if config is None:
            config = {}
        elif not isinstance(config, dict):
            raise ValueError(
                f"rerankers[{idx}] (id={rid!r}) config must be a mapping, got "
                f"{type(config).__name__}"
            )
        seen_ids.add(rid)
        normalized.append({"id": rid, "provider": provider, "config": config})

    primary_id = model_profile.get("primary_reranker") or normalized[0]["id"]
    if primary_id not in seen_ids:
        raise ValueError(
            f"primary_reranker={primary_id!r} not found in rerankers ids "
            f"{sorted(seen_ids)}"
        )

    for entry in normalized:
        if entry["provider"] != "rrf-hybrid":
            continue
        cfg = entry["config"]
        ids = cfg.get("reranker_ids")
        if not ids:
            raise ValueError(
                f"rrf-hybrid reranker {entry['id']!r} requires non-empty "
                "config.reranker_ids"
            )
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise ValueError(
                f"rrf-hybrid reranker {entry['id']!r} config.reranker_ids must be "
                "a non-empty list of strings"
            )
        for ref in ids:
            if ref == entry["id"]:
                raise ValueError(
                    f"rrf-hybrid reranker {entry['id']!r} references itself in "
                    "reranker_ids"
                )
            if ref not in seen_ids:
                raise ValueError(
                    f"rrf-hybrid reranker {entry['id']!r} references unknown id "
                    f"{ref!r} (known: {sorted(seen_ids)})"
                )

    return normalized, primary_id


def build_configuration_yml(
    model_profile: dict[str, Any], db_profile: dict[str, Any]
) -> dict[str, Any]:
    """Combine model + db profile dicts into a full MemMachine configuration.yml dict.

    Mirrors the structure documented in evaluation/retrieval_agent/README.md (Sample 1).
    """
    embedder = model_profile["embedder"]
    rerankers_list, primary_reranker_id = _validate_and_normalize_rerankers(
        model_profile
    )
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
                "reranker": primary_reranker_id,
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
            "reranker": primary_reranker_id,
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
                r["id"]: {"provider": r["provider"], "config": r["config"]}
                for r in rerankers_list
            },
        },
        "session_manager": {"database": profile_db["id"]},
    }


def _apply_fixed_to_configuration(
    configuration: dict[str, Any], fixed: dict[str, Any]
) -> None:
    """Apply fixed values that affect ingest/dataset loading into configuration.yml.

    `message_sentence_chunking` changes Episode storage shape, so it MUST be set
    before ingest, not just toggled per sweep cell. `prepend_user_prefix` is read
    by longmemeval_test from configuration.yml at search time.
    """
    if "message_sentence_chunking" in fixed:
        configuration.setdefault("episodic_memory", {}).setdefault(
            "long_term_memory", {}
        )["message_sentence_chunking"] = bool(fixed["message_sentence_chunking"])
    if "prepend_user_prefix" in fixed:
        configuration.setdefault("evaluation", {}).setdefault("longmemeval", {})[
            "prepend_user_prefix"
        ] = bool(fixed["prepend_user_prefix"])


def maybe_generate_configuration_yml(run_cfg: dict[str, Any]) -> str:
    """Always produce a run-local working configuration.yml.

    For mode=profile: combine model + db profile YAMLs.
    For mode=existing: copy the user-supplied configuration.yml (so we never
        mutate the user's original) and then apply fixed values.

    Either way, fixed values that affect ingest are written into the working
    copy here so retrieve sweep toggles are consistent with ingest.
    """
    import shutil

    cfg = run_cfg.get("configuration", {})
    mode = cfg.get("mode", "profile")
    fixed = run_cfg.get("fixed", {}) or {}

    generated_dir = REPO_ROOT / cfg.get("generated_dir", "configs/generated")
    out_path = generated_dir / f"{run_cfg['run_name']}_configuration.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "existing":
        src = cfg.get("existing_path")
        if not src:
            raise ValueError(
                "configuration.mode=existing but configuration.existing_path is empty"
            )
        src_path = Path(src).expanduser().resolve()
        if not src_path.exists():
            raise FileNotFoundError(
                f"configuration.existing_path does not exist: {src_path}"
            )
        shutil.copy2(src_path, out_path)
        configuration = load_yaml(out_path)
        _apply_fixed_to_configuration(configuration, fixed)
        dump_yaml(configuration, out_path)
        return str(out_path)

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
    _apply_fixed_to_configuration(configuration, fixed)
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

    # Resolve benchmark.data_path to an absolute path so the run YAML is
    # cwd-independent (LoCoMo subprocess, future runs from arbitrary cwds, etc).
    bench = merged.get("benchmark") or {}
    data_path = bench.get("data_path")
    if data_path:
        p = Path(str(data_path)).expanduser()
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        merged["benchmark"]["data_path"] = str(p)

    # Always produce a run-local working configuration.yml (D-002 / round-2 fix).
    generated_path = maybe_generate_configuration_yml(merged)
    merged.setdefault("configuration", {})["generated_path"] = generated_path

    # Persist run config
    run_path = CONFIGS_DIR / "runs" / f"{merged['run_name']}.yaml"
    dump_yaml(merged, run_path)

    print(f"[ok] run config: {run_path}")
    print(f"[ok] working configuration.yml: {generated_path}")
    if merged.get("configuration", {}).get("mode") == "existing":
        print(
            f"      (copied from {merged['configuration']['existing_path']} — "
            "user original NOT modified)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
