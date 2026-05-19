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
AUX_STAGES = ["regen_answer"]  # not included in "all"; explicit invocation only
ALL_ALLOWED = STAGE_ORDER + AUX_STAGES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config", required=True, help="Path to run YAML (configs/runs/{name}.yaml)"
    )
    parser.add_argument(
        "--stage",
        default=None,
        help='Comma-separated stages or "all". Allowed: '
        + ",".join(ALL_ALLOWED)
        + ',all. Default: "all", or "analyze" if run YAML has a non-empty '
        "reuse_run (analyze-only problems p6/p12). Aux stages "
        f"({','.join(AUX_STAGES)}) require explicit invocation; they are "
        'not included in "all".',
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
    parser.add_argument(
        "--skip-answer-llm",
        action="store_true",
        help=(
            "retrieve: skip the answer-LLM call per question. Only retrieve.jsonl "
            "is written (generate.jsonl is omitted). Use this for recall-only "
            "experiments where the answer LLM + judge are not needed; run "
            "scripts/regen_answer.py later if you change your mind."
        ),
    )
    return parser.parse_args()


def resolve_stages(arg: str) -> list[str]:
    if arg.strip().lower() == "all":
        return list(STAGE_ORDER)  # aux stages excluded from "all"
    parts = [s.strip() for s in arg.split(",") if s.strip()]
    bad = [s for s in parts if s not in ALL_ALLOWED]
    if bad:
        raise SystemExit(f"Unknown stage(s): {bad}. Allowed: {[*ALL_ALLOWED, 'all']}")
    # Canonical pipeline order first, then aux in user-provided order.
    canonical = [s for s in STAGE_ORDER if s in parts]
    aux = [s for s in parts if s in AUX_STAGES]
    return canonical + aux


def main() -> int:
    args = parse_args()
    run_cfg = load_yaml(args.config)
    if "run_name" not in run_cfg:
        raise SystemExit(f"run YAML is missing 'run_name': {args.config}")

    n_runs = int(run_cfg.get("n_runs", 1) or 1)
    if n_runs != 1:
        raise NotImplementedError(
            f"n_runs={n_runs} is not yet supported (MVP runs each stage once). "
            "Set n_runs=1 in the run YAML or omit --n-runs."
        )

    reuse_run = run_cfg.get("reuse_run")
    if args.stage is None:
        stage_arg = "analyze" if reuse_run else "all"
        if reuse_run:
            print(
                f"[pipeline] reuse_run={reuse_run!r} detected -> "
                "restricting --stage to 'analyze' (analyze-only problem; "
                "pass --stage explicitly to override, but ingest/retrieve/"
                "generate/judge will be rejected).",
                file=sys.stderr,
            )
    else:
        stage_arg = args.stage

    stages = resolve_stages(stage_arg)

    if reuse_run:
        non_analyze = [s for s in stages if s != "analyze"]
        if non_analyze:
            raise SystemExit(
                f"reuse_run={reuse_run!r} is set; analyze-only problems "
                f"(p6/p12) reject --stage {','.join(non_analyze)}. "
                "Use --stage analyze or omit --stage."
            )

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
            stage_retrieve.run(run_cfg, skip_answer_llm=args.skip_answer_llm)
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
        elif stage == "regen_answer":
            from scripts import regen_answer as regen_tool

            regen_tool.run(run_cfg)

    print("[pipeline] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
