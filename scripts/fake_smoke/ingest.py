"""Step 1 — ingest stage.

    uv run python -m scripts.fake_smoke.ingest

진짜 동작:
- cm.load_longmemeval_local 이 _fake_dataset.json 5개 로드.
- ingest.jsonl 에 status=ok marker 1줄 작성 (재실행 시 skip 근거).

가짜 우회:
- longmemeval_ingest 본체 (Neo4j INSERT + embedder 임베딩) → no-op.

진짜 호출되는 베이스 함수:
- scripts.stages.ingest.run(run_cfg)
"""

from __future__ import annotations

import json
from unittest.mock import patch

from scripts.fake_smoke import fake_longmemeval_ingest, load_run_cfg


def main() -> int:
    run_cfg = load_run_cfg()
    with patch(
        "evaluation.retrieval_agent.longmemeval_test.longmemeval_ingest",
        side_effect=fake_longmemeval_ingest,
    ):
        from scripts.stages.ingest import run

        out = run(run_cfg)
    print(f"[ingest] ok → {out}")
    print(f"  marker: {json.loads(out.read_text().splitlines()[-1])}")
    print()
    print("다음: uv run python -m scripts.fake_smoke.retrieve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
