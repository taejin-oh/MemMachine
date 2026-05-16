"""Step 2 — retrieve stage (emits retrieve.jsonl + generate.jsonl).

    uv run python -m scripts.fake_smoke.retrieve

진짜 동작:
- dataset 5개 다시 로드.
- 카테고리 / abstention 필터 (5 → 4, fake_q4_abs 제외).
- sweep cell 1개 × 4 문항 = 4번 process_question 호출.
- update_results 로 fact_hits 계산 → retrieve.jsonl, generate.jsonl 분리 emit.

가짜 우회:
- load_eval_config → None (ResourceManager 미생성).
- init_memmachine_params → (None, None, None) (LongTermMemory + answer LLM + agent 미생성).
- process_question → 가짜 dict (embed + Neo4j query + answer LLM 우회).

진짜 호출되는 베이스 함수:
- scripts.stages.retrieve.run(run_cfg)
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.fake_smoke import (
    fake_init_memmachine_params,
    fake_load_eval_config,
    fake_process_question,
    load_run_cfg,
)


def main() -> int:
    run_cfg = load_run_cfg()
    with (
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
    ):
        from scripts.stages.retrieve import run

        retrieve_path, generate_path = run(run_cfg)
    print(f"[retrieve] retrieve.jsonl → {retrieve_path}")
    print(f"[retrieve] generate.jsonl → {generate_path}")
    print()
    print("다음: uv run python -m scripts.fake_smoke.generate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
