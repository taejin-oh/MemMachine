#!/usr/bin/env python3
"""Pipeline orchestrator for the MemMachine reproduction-eval tool.

Loads a single run-config YAML (produced by scripts/generate_config.py) and
runs the requested stage(s) in order:
    ingest → retrieve → generate → judge → analyze

Stages can be invoked individually or comma-combined; `all` runs the full
pipeline. Each stage is idempotent in the sense that downstream stages will
skip work whose outputs already exist (see each stage module for details).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._merge import load_yaml  # noqa: E402

STAGE_ORDER = ["ingest", "retrieve", "generate", "judge", "analyze"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config", required=True, help="Path to run YAML (configs/runs/{name}.yaml)"
    )
    parser.add_argument(
        "--stage",
        default="all",
        help='Comma-separated stages or "all". Allowed: '
        + ",".join(STAGE_ORDER)
        + ",all",
    )
    parser.add_argument(
        "--decompose-multisession",
        action="store_true",
        help="analyze: emit MS vs others gap (#6)",
    )
    parser.add_argument(
        "--pareto",
        action="store_true",
        help="analyze: emit token/accuracy Pareto curve (#12)",
    )
    return parser.parse_args()


def resolve_stages(arg: str) -> list[str]:
    if arg.strip().lower() == "all":
        return list(STAGE_ORDER)
    parts = [s.strip() for s in arg.split(",") if s.strip()]
    bad = [s for s in parts if s not in STAGE_ORDER]
    if bad:
        raise SystemExit(f"Unknown stage(s): {bad}. Allowed: {[*STAGE_ORDER, 'all']}")
    # Preserve canonical order
    return [s for s in STAGE_ORDER if s in parts]


def main() -> int:
    args = parse_args()
    run_cfg = load_yaml(args.config)
    if "run_name" not in run_cfg:
        raise SystemExit(f"run YAML is missing 'run_name': {args.config}")

    n_runs = int(run_cfg.get("n_runs", 1) or 1)
    if n_runs != 1:
        raise NotImplementedError(
            f"n_runs={n_runs} is not yet supported (MVP runs each stage once). "
            "Set n_runs=1 in the run YAML or omit --n-runs. "
            "Repeated-run wrapper is tracked as future work in DECISIONS.md."
        )

    stages = resolve_stages(args.stage)
    print(f"[pipeline] run_name={run_cfg['run_name']}  stages={stages}")

    from scripts.stages import analyze as stage_analyze
    from scripts.stages import generate as stage_generate
    from scripts.stages import ingest as stage_ingest
    from scripts.stages import judge as stage_judge
    from scripts.stages import retrieve as stage_retrieve

    for stage in stages:
        if stage == "ingest":
            stage_ingest.run(run_cfg)
        elif stage == "retrieve":
            stage_retrieve.run(run_cfg)
        elif stage == "generate":
            stage_generate.run(run_cfg)
        elif stage == "judge":
            stage_judge.run(run_cfg)
        elif stage == "analyze":
            stage_analyze.run(
                run_cfg,
                decompose_multisession=args.decompose_multisession,
                pareto=args.pareto,
            )

    print("[pipeline] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
