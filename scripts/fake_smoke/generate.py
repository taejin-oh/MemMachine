"""Step 3 — generate verifier.

    uv run python -m scripts.fake_smoke.generate

진짜 동작 (가짜 없음):
- retrieve.jsonl + generate.jsonl 존재 + row count 확인.
- 본 stage 는 verifier — retrieve loop 가 이미 generate.jsonl 까지 emit 했음.

진짜 호출되는 베이스 함수:
- scripts.stages.generate.run(run_cfg)
"""

from __future__ import annotations

from scripts.fake_smoke import load_run_cfg


def main() -> int:
    run_cfg = load_run_cfg()
    from scripts.stages.generate import run

    out = run(run_cfg)
    print(f"[generate] verified → {out}")
    print()
    print("다음: uv run python -m scripts.fake_smoke.judge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
