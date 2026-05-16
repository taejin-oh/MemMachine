"""Step 5 — analyze stage.

    uv run python -m scripts.fake_smoke.analyze

진짜 동작 (가짜 없음):
- judge.jsonl + retrieve.jsonl 로드 + 행 단위 join (cell_idx + question 키).
- sweep cell 별 accuracy / by_category / mean tokens / mean recall 등 집계.
- analyze.json 작성.

진짜 호출되는 베이스 함수:
- scripts.stages.analyze.run(run_cfg)
"""

from __future__ import annotations

import json

from scripts.fake_smoke import load_run_cfg


def main() -> int:
    run_cfg = load_run_cfg()
    from scripts.stages.analyze import run

    out = run(run_cfg)
    print(f"[analyze] analyze.json → {out}")

    d = json.loads(out.read_text())
    print(f"  cells={len(d['cells'])}")
    for cell in d["cells"]:
        print(
            f"  sweep={cell['sweep']}  n={cell['n']}  accuracy={cell['accuracy']:.4f}"
        )
        for cat, stats in cell.get("by_category", {}).items():
            print(f"    {cat}: {stats['accuracy']:.4f} (n={stats['n']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
