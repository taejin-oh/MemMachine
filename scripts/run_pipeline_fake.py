"""Drop-in wrapper around scripts.run_pipeline with fake DB / model patches.

Same CLI as run_pipeline.py — use it with any existing run yaml in
configs/runs/*.yaml. The 5-stage pipeline is invoked unmodified; only
the deepest external boundaries (Neo4j INSERT, embedder call, answer
LLM, judge LLM) are stubbed.

Examples:

    # 전체 파이프라인 (기존 test_run_001.yaml 그대로)
    uv run python scripts/run_pipeline_fake.py \\
        --config configs/runs/test_run_001.yaml

    # 단일 stage 만
    uv run python scripts/run_pipeline_fake.py \\
        --config configs/runs/test_run_001.yaml --stage retrieve

    # 콤마 결합
    uv run python scripts/run_pipeline_fake.py \\
        --config configs/runs/test_run_001.yaml --stage ingest,retrieve

    # p6/p12 analyze-only
    uv run python scripts/run_pipeline_fake.py --config configs/runs/p6_from_v7.yaml

Patches (`scripts.fake_smoke.__init__` 에서 재사용):
- longmemeval_ingest        → no-op
- load_eval_config          → None
- init_memmachine_params    → (None, None, None)
- process_question          → 합성 (category, dict)
- create_judge_fn           → hash 기반 yes/no callable

점수는 무의미 (hash 기반). 검증되는 것 = pipeline wiring + 카테고리 필터 +
analyze 집계가 진짜 dataset shape 으로 정상 통과하는가.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
for _p in (
    REPO,
    REPO / "packages" / "common" / "src",
    REPO / "packages" / "server" / "src",
    REPO / "packages" / "client" / "src",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.fake_smoke import (  # noqa: E402
    fake_create_judge_fn,
    fake_init_memmachine_params,
    fake_load_eval_config,
    fake_longmemeval_ingest,
    fake_process_question,
)


def main() -> int:
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
    try:
        from scripts.run_pipeline import main as real_main

        return real_main() or 0
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    raise SystemExit(main())
