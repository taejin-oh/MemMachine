# Judge 실패 + Retrieval 성공 케이스 분석 — 가이드

LongMemEval 풀 런 (`results/<run>/retrieve.jsonl` + `judge.jsonl`) 결과에서
**retrieval 은 supporting_facts 를 모두 가져왔는데 answer LLM 이 답을 못
맞춘 케이스**만 골라, 같은 입력으로 answer LLM 을 다시 호출해 결과를
카테고리별로 본다. 목적: "이건 retrieval 문제가 아니라 LLM 한계" 라고
주장할 수 있는 표본을 분리해서 모델/프롬프트 개선의 기준선으로 삼는 것.

전체 흐름:

1. `filter_judge_failed.py` 로 judge 실패 (`llm_score=0`) row 만 추출
2. `filter_full_recall.py` 로 supporting_facts 100% 회수된 row 만 필터
3. `regen_answer.py` 로 answer LLM 재호출 → 새 `generate.jsonl`
4. `run_pipeline.py --stage judge` 로 다시 판정
5. `summarize_run.py` 로 overall + 카테고리별 정확도 출력

스크립트:

| 스크립트 | 역할 |
|---|---|
| `scripts/filter_judge_failed.py` | retrieve.jsonl + judge.jsonl → retrieve.failed.jsonl |
| `scripts/filter_full_recall.py` | retrieve.failed.jsonl → retrieve.gen_failed.jsonl (supporting_facts 100%) |
| `scripts/regen_answer.py` | retrieve.gen_failed.jsonl → generate.jsonl (answer LLM 재호출) |
| `scripts/run_pipeline.py --stage judge` | generate.jsonl → judge.jsonl |
| `scripts/summarize_run.py` | judge.jsonl → overall + per-category 표 |

## 0. 사전 준비

기본 환경 세팅과 풀 런 결과 (`results/<my_run>/retrieve.jsonl` +
`judge.jsonl`) 가 이미 있다고 가정.

## 1. judge 실패 row 추출

```bash
uv run python scripts/filter_judge_failed.py \
    --retrieve results/<my_run>/retrieve.jsonl \
    --out      results/<my_run>/retrieve.failed.jsonl
```

`--judge` 미지정 시 `results/<my_run>/judge.jsonl` 자동 사용. (question_id,
cell_idx) 매칭으로 `llm_score=0` 만 보존. 다른 필드는 retrieve.jsonl 그대로.

stdout 예:
```
[filter_judge_failed] 500 retrieve rows; 500 judge rows; 213 failed; 213 kept -> .../retrieve.failed.jsonl
```

## 2. supporting_facts 100% 회수된 row 만 → 새 run dir

새 run 디렉토리에 바로 `retrieve.jsonl` 로 출력해서 뒤의 cp 단계를 없앤다.

```bash
uv run python scripts/filter_full_recall.py \
    --retrieve results/<my_run>/retrieve.failed.jsonl \
    --out      results/<my_run>_gen_failed/retrieve.jsonl
```

각 row 의 chunks_text 를 라인 단위로 `json.loads()` 해서 본문을 정확
일치로 supporting_facts 와 매칭. 모든 fact 가 들어있는 row 만 keep.

> "fact 가 들어있다" 의 정의 = 그 fact 의 `_split_chunks` piece 중 **최소
> 한 개** 가 chunks_text 의 어떤 line 과 정확 일치 (whitespace 정규화
> 후). Edwin 의 turn-level recall 과 동일 — 긴 turn 이 여러 segment 로
> split 됐어도 segment 하나만 잡히면 그 turn 은 회수된 것으로 본다.
> `fact_hits` 의 substring + token-overlap heuristic 은 쓰지 않는다.

stdout 예:
```
[filter_full_recall] 213 in; 87 kept (100% supporting_facts present);
                     126 partial recall; 0 empty supporting_facts -> .../retrieve.gen_failed.jsonl
```

## 3. Answer LLM 재실행 → generate.jsonl

새 run 의 config 를 만든다 (모델·프롬프트 정책 동일):

```bash
uv run python scripts/generate_config.py \
    --problem 0 \
    --run-name <my_run>_gen_failed \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt
```

step 2 에서 이미 `results/<my_run>_gen_failed/retrieve.jsonl` 이 있으므로
바로 재실행:

```bash
uv run python scripts/regen_answer.py --run <my_run>_gen_failed
```

`generate.jsonl` 이 같은 디렉토리에 생성된다.

## 4. Judge 다시 돌리기

```bash
uv run python scripts/run_pipeline.py \
    --config configs/runs/<my_run>_gen_failed.yaml \
    --stage judge
```

`judge.jsonl` 이 같은 디렉토리에 생성됨.

## 5. 분석

```bash
uv run python scripts/summarize_run.py \
    --judge results/<my_run>_gen_failed/judge.jsonl \
    --out   results/<my_run>_gen_failed/summary.json
```

stdout 표:
```
category                          n  correct  wrong     acc
OVERALL                          87       12     75   0.138
single-session-user              25        5     20   0.200
temporal-reasoning               19        2     17   0.105
multi-session                    18        1     17   0.056
...
```

JSON 출력은 머신 판독용 — overall + per-category n/correct/wrong/accuracy.

**해석**:
- 이 표본은 "retrieval 은 정답 fact 를 다 줬는데도 LLM 이 실패한" 케이스만
  모은 것. 여기서 새로 측정한 정확도 = answer LLM 한계의 추정치.
- 카테고리별로 어디서 특히 실패가 몰리는지 본다 (예: temporal-reasoning,
  multi-session 에 몰리면 추론 능력 제약).
- 재실행 정확도가 0 에 가깝지 않다면 → original judge 가 일부 답을 잘못
  WRONG 처리했거나 (judge noise), LLM 의 비결정성으로 재실행 시 맞춘 것.

## 트러블슈팅

- **"judge.jsonl missing"**: `--judge` 명시하거나 retrieve.jsonl 옆에
  judge.jsonl 이 있는지 확인.
- **filter_full_recall keep = 0**: chunks_text 포맷 파싱 실패 가능. 첫 row
  의 chunks_text 첫 줄을 확인해 `[<date> at <time>] user: "<content>"`
  포맷인지 확인. 다른 producer label 있으면 `_LINE_SEP` / `_ALT_SEP` 만
  추가하면 됨.
- **regen_answer 가 같은 답을 냄**: 온도 0 / 결정적 모델이라면 정상. 모델
  비결정성 보고 싶으면 run config 의 model temperature 를 조정.
- **카테고리 수 부족**: gen_failed 표본이 작아 카테고리별 표본 < 10 일 수
  있음. 풀 런 사이즈를 늘리거나, 카테고리 결합으로 본다.

## 핵심 파일 위치

| 항목 | 경로 |
|---|---|
| 신규 필터 | `scripts/filter_judge_failed.py`, `scripts/filter_full_recall.py` |
| 단일 런 분석 | `scripts/summarize_run.py` |
| 재활용 | `scripts/regen_answer.py`, `scripts/run_pipeline.py --stage judge` |
| 중간 산출물 | `results/<my_run>/retrieve.failed.jsonl`, `retrieve.gen_failed.jsonl` |
| 최종 산출물 | `results/<my_run>_gen_failed/{generate,judge}.jsonl + summary.json` |
