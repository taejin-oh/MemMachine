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
import contextlib
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
        default=None,
        help='Comma-separated stages or "all". Allowed: '
        + ",".join(STAGE_ORDER)
        + ',all. Default: "all", or "analyze" if run YAML has a non-empty '
        "reuse_run (analyze-only problems p6/p12).",
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
        "--fake-backends",
        action="store_true",
        help=(
            "Stub Neo4j ingest / embedder / answer LLM / judge LLM with "
            "deterministic fakes from scripts.fake_smoke. Exercises pipeline "
            "wiring (filter, jsonl emit, analyze aggregation) on any run "
            "yaml without Docker / API credits. Scores are meaningless."
        ),
    )
    return parser.parse_args()


@contextlib.contextmanager
def _maybe_fake_backends(enabled: bool):
    """Install scripts.fake_smoke patches for the duration of the pipeline run.

    Imports are lazy so the regular (real-backend) path does not pull in
    unittest.mock or the fake_smoke package at all.
    """
    if not enabled:
        yield
        return

    from unittest.mock import patch

    from scripts.fake_smoke import (
        fake_create_judge_fn,
        fake_init_memmachine_params,
        fake_load_eval_config,
        fake_longmemeval_ingest,
        fake_process_question,
    )

    patches = [
        patch(
            "evaluation.retrieval_agent.longmemeval_test.longmemeval_ingest",
            side_effect=fake_longmemeval_ingest,
        ),
        patch(
            "evaluation.utils.agent_utils.load_eval_config",
            side_effect=fake_load_eval_config,
        ),
        patch(
            "evaluation.utils.agent_utils.init_memmachine_params",
            side_effect=fake_init_memmachine_params,
        ),
        patch(
            "evaluation.utils.agent_utils.process_question",
            side_effect=fake_process_question,
        ),
        patch(
            "evaluation.retrieval_agent.llm_judge.create_judge_fn",
            side_effect=fake_create_judge_fn,
        ),
    ]
    for p in patches:
        p.start()
    print(
        "[pipeline] --fake-backends ACTIVE — scores are meaningless, "
        "only wiring is validated",
        file=sys.stderr,
    )
    try:
        yield
    finally:
        for p in patches:
            p.stop()


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

    with _maybe_fake_backends(args.fake_backends):
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
