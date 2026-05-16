"""Step 4 — judge stage.

    uv run python -m scripts.fake_smoke.judge

진짜 동작:
- generate.jsonl 4 행 로드.
- _resolve_yesno_policy (lenient) / _judge_config_path 실행.
- 각 행 category 가 _LONGMEMEVAL_TASKS 에 속함 → LongMemEval text judge 라우팅.
- get_anscheck_prompt 가 task 별 verbatim template 으로 prompt 생성.
- _parse_yes_no_with_label(raw, "lenient") 가 진짜로 채점.
- judge.jsonl 에 llm_score + judge_raw_response + judge_parsed_label + judge_attempts 작성.

가짜 우회:
- create_judge_fn → hash 기반 yes/no callable (OpenAI/Bedrock 호출 우회).

진짜 호출되는 베이스 함수:
- scripts.stages.judge.run(run_cfg)
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.fake_smoke import fake_create_judge_fn, load_run_cfg


def main() -> int:
    run_cfg = load_run_cfg()
    with patch(
        "evaluation.retrieval_agent.llm_judge.create_judge_fn",
        side_effect=fake_create_judge_fn,
    ):
        from scripts.stages.judge import run

        out = run(run_cfg)
    print(f"[judge] judge.jsonl → {out}")
    print()
    print("다음: uv run python -m scripts.fake_smoke.analyze")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
