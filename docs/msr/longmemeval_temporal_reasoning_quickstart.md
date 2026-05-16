# LongMemEval Temporal Reasoning 평가 — 초심자 가이드

처음 저장소를 받은 사람이 기본 설정으로 LongMemEval의 `temporal-reasoning`
카테고리만 평가하기 위한 단계별 절차. 분량 최소화.

## 0. 사전 준비

- Python 3.12+
- Docker (Neo4j + Postgres 용)
- OpenAI API key

## 1. 저장소 clone + 브랜치

```bash
git clone https://github.com/taejin-oh/MemMachine.git
cd MemMachine
git checkout eval_optimize
```

## 2. 의존성 설치

```bash
uv sync --all-extras
```

`--all-extras` 가 `sentence-transformers` (embedder) 까지 설치.

## 3. 데이터셋 다운로드 (~265MB)

```bash
uv run python -c "
from huggingface_hub import hf_hub_download
import shutil
src = hf_hub_download(
    repo_id='xiaowu0162/longmemeval-cleaned',
    repo_type='dataset',
    filename='longmemeval_s_cleaned.json',
)
shutil.copy2(src, 'evaluation/data/longmemeval_s_cleaned.json')
"
```

500 문항. 파일은 `.gitignore` 대상.

## 4. 비밀번호 / API 키 채우기

`configs/profiles/models/main.yaml` — `<OPENAI_API_KEY>` 교체.
`configs/profiles/dbs/main.yaml` — `<NEO4J_PASSWORD>`, `<POSTGRES_PASSWORD>` 교체.

## 5. 서버 + DB 띄우기

```bash
./memmachine-compose.sh start
```

Neo4j(`bolt://localhost:7687`) + Postgres(`localhost:5432`) + MemMachine 서버.

## 6. `configuration.yml` 빌드

```bash
uv run python - <<'PY'
from pathlib import Path
from scripts._merge import load_yaml, dump_yaml
from scripts.generate_config import (
    build_configuration_yml,
    _apply_fixed_to_configuration,
)

mp = load_yaml(Path("configs/profiles/models/main.yaml"))
dp = load_yaml(Path("configs/profiles/dbs/main.yaml"))
cfg = build_configuration_yml(mp, dp)
_apply_fixed_to_configuration(
    cfg,
    {"message_sentence_chunking": False, "prepend_user_prefix": False},
)
cfg.setdefault("retrieval_agent", {})["longmemeval_answer_prompt"] = "LME_origin_prompt"
cfg["retrieval_agent"]["longmemeval_yesno_policy"] = "lenient"

out = Path("configs/generated/temporal_test_configuration.yml").resolve()
out.parent.mkdir(parents=True, exist_ok=True)
dump_yaml(cfg, out)
print(f"wrote: {out}")
PY
```

## 7. Run config 작성

`configs/runs/temporal_test.yaml`:

```yaml
run_name: temporal_test
problem: 0
description: "LongMemEval temporal-reasoning baseline"

configuration:
  mode: existing
  generated_path: configs/generated/temporal_test_configuration.yml
  existing_path: configs/generated/temporal_test_configuration.yml

benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_s_cleaned
  data_path: evaluation/data/longmemeval_s_cleaned.json

sweep: {}

fixed:
  test_target: memmachine
  search_limit: 30
  prepend_user_prefix: false
  message_sentence_chunking: false

evaluation:
  exclude_abstention: true
  ingest_concurrency: 4
  search_concurrency: 4
  judge_concurrency: 4
  longmemeval:
    include_categories: ["temporal-reasoning"]

judge:
  llm_model_id: null
  longmemeval_yesno_policy: lenient

n_runs: 1
```

> `include_categories` 가 retrieve 단계만 좁힘. ingest 는 항상 500 문항
> haystack 전체 적재 (retrieval competition 보존).

## 8. 평가 실행

```bash
uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml
```

진행되는 단계 (모두 자동):

| Stage | 처리 |
|---|---|
| `ingest` | 500 문항 haystack 을 Neo4j 에 적재 (idempotent) |
| `retrieve` | `temporal-reasoning` 127 문항 검색 (abstention 6 제외) |
| `generate` | retrieve loop 에서 답변 생성 |
| `judge` | LongMemEval temporal template 으로 yes/no 채점 |
| `analyze` | accuracy 집계 |

## 9. 결과

```
results/temporal_test/
├── ingest.jsonl         # status=ok marker
├── retrieve.jsonl       # 검색된 episode + perf metrics
├── generate.jsonl       # 모델 답변
├── judge.jsonl          # llm_score + raw_response
└── analyze.json         # 카테고리별 정확도
```

요약 출력:

```bash
uv run python -c "
import json
d = json.load(open('results/temporal_test/analyze.json'))
for c in d['cells']:
    print(f\"n={c['n']}  accuracy={c['accuracy']:.4f}\")
    for cat, stats in c['by_category'].items():
        print(f\"  {cat}: {stats['accuracy']:.4f} (n={stats['n']})\")
"
```

## 10. 트러블슈팅

- **Neo4j connection refused** — `./memmachine-compose.sh status` 확인 후 `restart`.
- **OpenAI rate limit** — `search_concurrency` 를 1 로 낮춰서 재실행.
- **ingest 중단 후 재실행** — `results/temporal_test/ingest.jsonl` 삭제 후 다시.
- **모든 점수 0** — `judge.jsonl` 의 `judge_raw_response` 확인 (JSON 파싱 실패 / 빈 응답 등).
- **카테고리 바꿔 재평가** — `include_categories` 값만 바꿔 retrieve 부터 다시:
  ```bash
  uv run python scripts/run_pipeline.py --config configs/runs/temporal_test.yaml \
    --stage retrieve,generate,judge,analyze
  ```
  ingest 는 idempotent 라 skip.

## 다음 단계

- 다른 카테고리: `include_categories` 를 `["multi-session"]` 등으로 변경.
- k sweep: `sweep.search_limit: [10, 20, 30, 50, 100]`.
- prompt 비교: `evaluation.longmemeval.answer_prompt` 를 5 정책 중 선택.
- 전체 변수 목록은 `CLAUDE.md` 의 "Architecture — Evaluation" 섹션 참조.
