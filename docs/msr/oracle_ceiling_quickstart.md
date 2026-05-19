# Oracle Ceiling & Supporting-Facts Position 실험 — 가이드

LongMemEval 위에서 **answer LLM의 한계 (= "100점")** 와 **supporting_facts 위치
효과**를 분리해 측정한다. 표준 retrieval 평가와는 별개의 워크플로다.

전체 흐름:

- **워크플로 A — Oracle ceiling** (W1 + W2)
  Oracle 데이터(증거 세션만 있는 LongMemEval 변종)로 retrieval 을 건너뛰고
  answer LLM 한계를 측정. `full` (has_answer T+F) vs `facts-only` (T만) 비교.
- **워크플로 B — s_cleaned recall** (W3)
  실제 시스템의 retrieve.jsonl 이 오라클 증거를 얼마나 회수했는지 진단.
- **워크플로 C — Position experiment** (W4 + W2)
  실 시스템 retrieve.jsonl 에서 supporting_facts 위치만 앞/중간/뒤로 바꿔
  정확도 차이를 본다. lost-in-the-middle 진단.

스크립트는 4 개 + 비교 도구 1 개:

| 스크립트 | 역할 |
|---|---|
| `scripts/build_oracle_retrieve.py` | 오라클 JSON → retrieve.jsonl (`--facts-only` 토글) |
| `scripts/regen_answer.py` | retrieve.jsonl → generate.jsonl (answer LLM 호출만) |
| `scripts/analyze_sclean_recall.py` | 시스템 retrieve.jsonl ↔ 오라클 회수율 |
| `scripts/permute_facts_position.py` | supporting_facts 위치 재배치 (front/middle/end) |
| `scripts/compare_runs.py` | N 개 런 정확도 + 청크 통계 비교 |

## 0. 사전 준비

기본 환경 세팅 (clone, `uv sync --all-extras`, Neo4j/Postgres 띄우기, API 키)
은 [`longmemeval_temporal_reasoning_quickstart.md`](longmemeval_temporal_reasoning_quickstart.md)
의 0~5 단계 그대로 한다.

추가로 **오라클 데이터셋 다운로드** (~15 MB):

```bash
uv run python -c "
from huggingface_hub import hf_hub_download
import shutil
src = hf_hub_download(
    repo_id='xiaowu0162/longmemeval-cleaned',
    repo_type='dataset',
    filename='longmemeval_oracle.json',
)
shutil.copy2(src, 'evaluation/data/longmemeval_oracle.json')
"
```

`.gitignore` 대상. 500 문항, `longmemeval_s_cleaned.json` 과 question_id /
question / answer 가 완전히 일치하며 distractor 세션만 제거된 변종.

## 1. Run config 만들기 (오라클 베이스라인용)

오라클 워크플로는 ingest / retrieve 단계를 안 쓰니까 DB 가 떠 있을 필요는
없지만, `regen_answer.py` / `judge` 단계가 working `configuration.yml` 을
요구하므로 보통 흐름대로 만든다.

```bash
uv run python scripts/generate_config.py \
    --problem 0 \
    --run-name oracle_full \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt
```

같은 식으로 `--run-name oracle_facts` 도 하나 더 만들어 둔다. 두 런은 모델
세팅이 같고 결과 디렉토리만 다르다.

> p0 의 `length=500` 기본값을 그대로 쓴다. `--include-categories` 는 평가
> 카테고리를 좁히고 싶을 때만 추가.

## 워크플로 A — Oracle Ceiling

### A-1. 두 종류의 retrieve.jsonl 빌드

```bash
# full: has_answer True + False 모두 (Q당 ~22 chunks, 정석 LongMemEval 오라클)
uv run python scripts/build_oracle_retrieve.py \
    --out results/oracle_full/retrieve.jsonl

# facts-only: has_answer=True turn 만 (Q당 ~1.79 chunks, 더 공격적인 ceiling)
uv run python scripts/build_oracle_retrieve.py --facts-only \
    --out results/oracle_facts/retrieve.jsonl
```

### A-2. 두 런 모두 answer LLM 호출 + judge + analyze

```bash
for name in oracle_full oracle_facts; do
    uv run python scripts/regen_answer.py --run $name
    uv run python scripts/run_pipeline.py \
        --config configs/runs/$name.yaml \
        --stage judge,analyze
done
```

`regen_answer.py` 는 `results/<run_name>/retrieve.jsonl` 을 읽어
`generate.jsonl` 을 같은 디렉토리에 쓴다. 그 다음 `judge` 와 `analyze` 가 거기서
이어서 실행된다.

### A-3. 두 런 비교 리포트

```bash
uv run python scripts/compare_runs.py \
    --runs results/oracle_full results/oracle_facts \
    --labels "Full(T+F)" "Facts only" \
    --out results/oracle_ceiling_compare.json
```

stdout 에 카테고리별 정확도 + Δ + Q당 청크/봉인 fact 평균 표.
`oracle_ceiling_compare.json` 은 머신 판독용.

**해석**: `Facts only` 가 `Full(T+F)` 보다 떨어지면 → answer LLM 이 주변
컨텍스트 turn 에 의존. 비슷하다면 → has_answer=True turn 만으로 충분.

## 워크플로 B — s_cleaned Recall

실제 시스템 retrieve 결과를 오라클 ground truth 와 비교. 시스템 retrieve.jsonl
이 이미 있다고 가정한다 (`scripts/run_pipeline.py --stage retrieve` 로 생성된
것).

```bash
uv run python scripts/analyze_sclean_recall.py \
    --retrieve results/<my_run>/retrieve.jsonl \
    --out results/<my_run>/sclean_recall.json
```

**출력 2 지표**:

- **Recall A** — 시스템 chunks 가 오라클 증거 세션 turn 전체를 얼마나
  회수했는가 (T + F).
- **Recall B** — has_answer=True turn 만의 회수율.

stdout 은 overall + 카테고리별, JSON 은 per-question 까지 포함.

> 매칭은 `chunks_text` 라인을 `json.loads()` 한 본문에 대해 화이트스페이스
> 정규화 후 **정확 일치**다. 오라클과 s_cleaned 의 증거 세션이 byte-equal 임이
> 검증되어 있어 가능. `fact_hits` 의 substring + token-overlap heuristic 은
> 쓰지 않는다.

**Sanity check**: A-1 의 `oracle_full` retrieve.jsonl 을 입력으로 넣으면
recall A = 1.000 이 나와야 한다 (자기 자신 회수).

## 워크플로 C — Position Experiment

실 시스템 retrieve.jsonl 에서 supporting_facts 위치만 바꾼 3 변종을 만들고
정확도를 비교.

### C-1. 3 변종 생성

```bash
uv run python scripts/permute_facts_position.py \
    --retrieve results/<my_run>/retrieve.jsonl \
    --out-dir results/position
```

산출:

- `results/position/front/retrieve.jsonl` — fact 가 맨 앞
- `results/position/middle/retrieve.jsonl` — fact 가 중간
- `results/position/end/retrieve.jsonl` — fact 가 맨 뒤

누락된 supporting_fact (시스템이 회수 못 한 것) 는 오라클 line 포맷으로
**합성 주입**되어 3 변종 모두 동일한 fact 집합을 갖는다. 끄려면
`--no-inject-missing`.

### C-2. 각 변종에 run config 만들기

```bash
for pos in front middle end; do
    uv run python scripts/generate_config.py \
        --problem 0 \
        --run-name pos_$pos \
        --model-profile main --db-profile main \
        --longmemeval-answer-prompt LME_origin_prompt
    # 빌드된 retrieve.jsonl 을 results/<run-name>/ 자리로 이동
    mkdir -p results/pos_$pos
    cp results/position/$pos/retrieve.jsonl results/pos_$pos/retrieve.jsonl
done
```

### C-3. 변종 3 개 모두 generate + judge + analyze

```bash
for pos in front middle end; do
    uv run python scripts/regen_answer.py --run pos_$pos
    uv run python scripts/run_pipeline.py \
        --config configs/runs/pos_$pos.yaml --stage judge,analyze
done
```

### C-4. 3-way 비교

```bash
uv run python scripts/compare_runs.py \
    --runs results/pos_front results/pos_middle results/pos_end \
    --labels front middle end \
    --baseline 0 \
    --out results/position_compare.json
```

**해석**: 같은 fact 집합을 가지는데 위치만 다른 세 변종의 정확도 차이 = 위치
효과. front 가 가장 높으면 lost-in-the-middle (또는 end-bias 부재) 진단.

## 트러블슈팅

- **`regen_answer.py` 가 "retrieve.jsonl missing"**: retrieve.jsonl 이
  `results/<run_name>/` 에 없다. `build_oracle_retrieve.py --out
  results/<run_name>/retrieve.jsonl` 로 직접 지정하거나, 외부 파일을
  `cp` 해 넣는다.
- **`compare_runs.py` 가 "analyze.json has no cells"**: `analyze` 단계가
  아직 안 돌았거나 실패. `run_pipeline.py --stage analyze` 단독으로 다시
  돌려서 확인.
- **`analyze_sclean_recall.py` recall = 0**: chunks_text 포맷이 다를 가능성
  (예: `assistant: ` line만 있는 경우). 스크립트는 `user: ` 와 `assistant: `
  둘 다 파싱하지만, 다른 producer label 이면 라인이 무시된다. `--retrieve`
  파일의 첫 row chunks_text 를 직접 확인.
- **`permute_facts_position.py` "rows had supporting_facts but zero fact
  lines"**: 시스템 chunks_text 에 fact 가 0 개 매칭됨 + `inject_missing=OFF`
  로 사용 중. 기본값 (ON) 으로 다시 돌리면 합성 주입으로 해결.
- **카테고리 키 매칭**: 6 종 LongMemEval 카테고리는 retrieve.jsonl 의
  `category` field 에서 온다 (= `question_type`). `compare_runs.py` /
  `analyze_sclean_recall.py` 모두 같은 키로 그룹핑하므로 추가 매핑 필요 없음.

## 핵심 파일 위치 요약

| 항목 | 경로 |
|---|---|
| 오라클 데이터셋 | `evaluation/data/longmemeval_oracle.json` |
| s_cleaned 데이터셋 | `evaluation/data/longmemeval_s_cleaned.json` |
| 빌더 / 분석 스크립트 | `scripts/build_oracle_retrieve.py`, `scripts/analyze_sclean_recall.py`, `scripts/permute_facts_position.py`, `scripts/compare_runs.py` |
| Answer-LLM 재생성 | `scripts/regen_answer.py` |
| 표준 파이프라인 stage | `scripts/run_pipeline.py --stage {judge,analyze}` |
| 결과 디렉토리 | `results/<run_name>/{retrieve,generate,judge}.jsonl + analyze.json` |
