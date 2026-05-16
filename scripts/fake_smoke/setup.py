"""Step 0 — synthesize dataset + build configuration.yml + write run yaml.

    uv run python -m scripts.fake_smoke.setup

진짜 동작 (가짜 없음):
- results/fake_smoke/_fake_dataset.json (5 samples) 작성.
- configs/profiles/{models,dbs}/main.yaml 머지 →
  configs/generated/fake_smoke_configuration.yml 빌드.
- Pydantic `Configuration.load_yml_file` 로 schema 검증.
- configs/runs/fake_smoke.yaml 작성.

진짜 호출되는 베이스 함수:
- scripts._merge.load_yaml / dump_yaml
- scripts.generate_config.build_configuration_yml
- scripts.generate_config._apply_fixed_to_configuration
- memmachine_server.common.configuration.Configuration.load_yml_file
"""

from __future__ import annotations

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


def main() -> int:
    # --- 1. synthetic dataset ----------------------------------------------
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    DATA_JSON.write_text(json.dumps(FAKE_DATASET, indent=2, ensure_ascii=False))
    print(f"[setup] dataset       → {DATA_JSON}  ({len(FAKE_DATASET)} samples)")

    # --- 2. generated configuration.yml ------------------------------------
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

    # --- 3. Pydantic validation --------------------------------------------
    from memmachine_server.common.configuration import Configuration

    c = Configuration.load_yml_file(str(GEN_YML))
    ltm = c.episodic_memory.long_term_memory
    print(
        f"[setup] Pydantic OK   "
        f"llm={c.retrieval_agent.llm_model}  "
        f"embedder={ltm.embedder}  reranker={ltm.reranker}  "
        f"chunk={ltm.message_sentence_chunking}"
    )

    # --- 4. run yaml --------------------------------------------------------
    RUN_YAML.parent.mkdir(parents=True, exist_ok=True)
    RUN_YAML.write_text(
        f"""run_name: {RUN_NAME}
problem: 0
description: "manual fake-smoke walkthrough"

configuration:
  mode: existing
  generated_path: {GEN_YML.resolve()}
  existing_path: {GEN_YML.resolve()}

benchmark:
  name: longmemeval
  length: 100
  split: fake
  data_path: {DATA_JSON.resolve()}

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
    answer_prompt: LME_origin_prompt
    # include_categories null → 모든 카테고리 (편집해서 좁힐 수 있음)

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
