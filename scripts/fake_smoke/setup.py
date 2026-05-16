"""Step 0 — write dataset + configuration.yml + run yaml.

    uv run python -m scripts.fake_smoke.setup
    uv run python -m scripts.fake_smoke.setup --real-dataset
    uv run python -m scripts.fake_smoke.setup --real-dataset \
        --length 50 --include-categories temporal-reasoning,multi-session

진짜 동작 (가짜 없음):
- 합성 5문항 JSON 작성 (기본) 또는 실제 LongMemEval-s cleaned 500문항
  로컬 파일 (--real-dataset) 을 가리킴.
- configs/profiles/{models,dbs}/main.yaml 머지 →
  configs/generated/fake_smoke_configuration.yml 빌드.
- Pydantic `Configuration.load_yml_file` 로 schema 검증.
- configs/runs/fake_smoke.yaml 작성.

옵션:
  --real-dataset            evaluation/data/longmemeval_s_cleaned.json 사용
                            (없으면 setup 실패; 다운로드는 quickstart 참조)
  --length N                benchmark.length override
                            (default: 합성=5, real=500)
  --include-categories CSV  evaluation.longmemeval.include_categories
                            (예: "multi-session,temporal-reasoning")

진짜 호출되는 베이스 함수:
- scripts._merge.load_yaml / dump_yaml
- scripts.generate_config.build_configuration_yml
- scripts.generate_config._apply_fixed_to_configuration
- memmachine_server.common.configuration.Configuration.load_yml_file
"""

from __future__ import annotations

import argparse
import json

from scripts.fake_smoke import (
    DATA_JSON,
    FAKE_DATASET,
    GEN_YML,
    REPO,
    RUN_DIR,
    RUN_NAME,
    RUN_YAML,
)

REAL_DATASET = REPO / "evaluation" / "data" / "longmemeval_s_cleaned.json"

VALID_CATEGORIES = {
    "single-session-user",
    "single-session-assistant",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
    "single-session-preference",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--real-dataset",
        action="store_true",
        help="Use evaluation/data/longmemeval_s_cleaned.json (~500 LongMemEval-s cleaned).",
    )
    p.add_argument("--length", type=int, help="Override benchmark.length.")
    p.add_argument(
        "--include-categories",
        default="",
        help='Comma-separated question_type filter. e.g. "multi-session,temporal-reasoning"',
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    # --- 1. dataset ---------------------------------------------------------
    if args.real_dataset:
        if not REAL_DATASET.exists():
            raise SystemExit(
                f"real dataset missing: {REAL_DATASET}\n"
                "Download via the HF snippet in "
                "docs/msr/longmemeval_temporal_reasoning_quickstart.md (step 3)."
            )
        data_path = REAL_DATASET
        default_length = 500
        n_label = "~500 real LongMemEval-s cleaned"
    else:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        DATA_JSON.write_text(json.dumps(FAKE_DATASET, indent=2, ensure_ascii=False))
        data_path = DATA_JSON
        default_length = len(FAKE_DATASET)
        n_label = f"{len(FAKE_DATASET)} synthetic"

    length = args.length or default_length
    print(f"[setup] dataset       → {data_path}  ({n_label}, length={length})")

    # --- 2. include_categories validation ----------------------------------
    cats: list[str] = []
    if args.include_categories.strip():
        cats = [c.strip() for c in args.include_categories.split(",") if c.strip()]
        bad = [c for c in cats if c not in VALID_CATEGORIES]
        if bad:
            raise SystemExit(
                f"invalid --include-categories: {bad}. "
                f"Valid: {sorted(VALID_CATEGORIES)}"
            )

    # --- 3. generated configuration.yml ------------------------------------
    from scripts._merge import dump_yaml, load_yaml
    from scripts.generate_config import (
        _apply_fixed_to_configuration,
        build_configuration_yml,
    )

    mp = load_yaml(REPO / "configs" / "profiles" / "models" / "main.yaml")
    dp = load_yaml(REPO / "configs" / "profiles" / "dbs" / "main.yaml")
    cfg = build_configuration_yml(mp, dp)
    _apply_fixed_to_configuration(
        cfg,
        {"message_sentence_chunking": False, "prepend_user_prefix": False},
    )
    GEN_YML.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml(cfg, GEN_YML.resolve())
    print(f"[setup] configuration → {GEN_YML}")

    # --- 4. Pydantic validation --------------------------------------------
    from memmachine_server.common.configuration import Configuration

    c = Configuration.load_yml_file(str(GEN_YML))
    ltm = c.episodic_memory.long_term_memory
    print(
        f"[setup] Pydantic OK   "
        f"llm={c.retrieval_agent.llm_model}  "
        f"embedder={ltm.embedder}  reranker={ltm.reranker}  "
        f"chunk={ltm.message_sentence_chunking}"
    )

    # --- 5. run yaml --------------------------------------------------------
    if cats:
        cats_yaml_value = "[" + ", ".join(f'"{c}"' for c in cats) + "]"
        cats_line = f"\n    include_categories: {cats_yaml_value}"
    else:
        cats_line = (
            "\n    # include_categories: null  → 모든 카테고리 (편집해서 좁힐 수 있음)"
        )

    split_label = "longmemeval_s_cleaned" if args.real_dataset else "fake"

    RUN_YAML.parent.mkdir(parents=True, exist_ok=True)
    RUN_YAML.write_text(
        f"""run_name: {RUN_NAME}
problem: 0
description: "manual fake-smoke walkthrough ({"real" if args.real_dataset else "synthetic"} dataset)"

configuration:
  mode: existing
  generated_path: {GEN_YML.resolve()}
  existing_path: {GEN_YML.resolve()}

benchmark:
  name: longmemeval
  length: {length}
  split: {split_label}
  data_path: {data_path.resolve()}

sweep: {{}}

fixed:
  test_target: memmachine
  search_limit: 5
  prepend_user_prefix: false
  message_sentence_chunking: false

evaluation:
  exclude_abstention: true
  ingest_concurrency: 1
  search_concurrency: 1
  judge_concurrency: 1
  longmemeval:
    answer_prompt: LME_origin_prompt{cats_line}

judge:
  llm_model_id: null
  longmemeval_yesno_policy: lenient

n_runs: 1
"""
    )
    print(f"[setup] run yaml      → {RUN_YAML}")
    print()
    print("다음: uv run python -m scripts.fake_smoke.ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
