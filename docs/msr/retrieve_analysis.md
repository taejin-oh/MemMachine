# Retrieval-Quality Analyzer

`scripts/analyze_retrieval.py` — LongMemEval 한 run 의 retrieve 결과가 정답
도출에 충분한 정보를 담았는지 LLM 으로 판정.

## 왜?

LongMemEval 의 최종 accuracy = retrieval × answer-LLM (두 stage 의 곱).
이 곱 하나만 보면 "retrieval 이 부족했나" vs "answer-LLM 이 부족했나"
구분 불가. 이 도구는 retrieved memory (`chunks_text`) 가 gold answer 를
도출할 만큼의 정보를 담았는지 별도로 판정 — answer-LLM 의 영향을 격리.

## 입력 / 출력

`scripts/run_pipeline.py` 가 끝난 run 의 두 산출물을 읽음 (question_id 로 join):

| 입력 | |
|---|---|
| `results/{run}/retrieve.jsonl` | `question`, `chunks_text`, `category`, `supporting_facts`, `question_id` |
| `results/{run}/judge.jsonl` | `golden_answer`, `llm_score` (0/1) |

산출 (`results/{run}/` 아래):

| 출력 | 용도 |
|---|---|
| `retrieve_analysis.jsonl` | per-question 상세 (Stage 1 + Stage 2 raw) |
| `retrieve_analysis_summary.json` | 집계 (기계 읽기) |
| `retrieve_analysis_report.md` | 집계 (사람 읽기, 표 + 해석) |

## 동작 — 2 단계

### Stage 1 (항상)

LLM 에게 JSON 응답 한 번으로 두 가지:

1. golden answer 를 atomic fact 들로 분해 (보통 1-5 개)
2. 각 fact 가 `chunks_text` 전체에 있는지 yes/no

→ `required_facts: [{fact, present_in_context}]` + `verdict ∈ {sufficient, partial, insufficient}`.

### Stage 2 (조건부)

기본: Stage 1 verdict 가 `partial` / `insufficient` 일 때, **누락 (`present_in_context: false`) fact 만** 대상. `--pin-all-facts` 면 모든 fact.

각 대상 fact 마다 `chunks_text.split('\n')` 으로 episode 분리 → episode 한 줄씩 LLM 에 "이 fact 있나?" 물음 → 첫 발견에서 early-exit.

결과 분류:
- Stage 1 absent + Stage 2 found → `stage1_false_positive: true` (Stage 1 의 LLM noise)
- Stage 1 absent + Stage 2 not found → `truly_missing: true` (진짜 retrieval 누락)
- Stage 1 present + Stage 2 found → 확인됨 (chunk index 기록만)
- Stage 1 present + Stage 2 not found → Stage 1 의 false positive of "present" claim (chunk index null)

## CLI

```bash
uv run python scripts/analyze_retrieval.py --run <run_name>
```

옵션:

| flag | 기본 | 효과 |
|---|---|---|
| `--config <path>` | `configs/generated/{run}_configuration.yml` | judge LLM 설정 |
| `--concurrency N` | 4 | 동시 LLM 호출 수 |
| `--limit N` | 전체 | 첫 N rows 만 (smoke test) |
| `--skip-stage2` | off | Stage 1 만 — Stage 2 chunk 매칭 생략 |
| `--pin-all-facts` | off | Stage 2 를 **모든** required_fact 에 — cost 약 2배, 모든 fact 의 chunk 위치 확보 |

## Judge LLM 설정

`evaluation/retrieval_agent/llm_judge.py:create_judge_fn` 재사용 → `retrieval_agent.judge_llm_model` 우선, 없으면 `retrieval_agent.llm_model`. 즉:

- **기본**: run 에서 쓴 answer LLM 과 동일 모델로 분석
- **swap**: model profile 에 `judge_llm` 블록 추가하거나 `--config` 로 다른 configuration.yml 지정

⚠️ **소형 모델 (3B 이하) 비추.** Stage 1 의 "전체 chunks_text 보고 분해 + presence check" 가 multi-step 추론이라 작은 모델은 보수적으로 false 찍음 → Stage 2 가 다 뒤집어서 false positive rate 가 ~100% 됨. signal 이 사라짐. **Gemini 2.5 Flash / GPT-4o-mini 권장.**

## per-row 스키마 (`retrieve_analysis.jsonl`)

```json
{
  "question_id": "abc123",
  "category": "temporal-reasoning",
  "judge_score": 1,
  "num_episodes_retrieved": 10,
  "stage1": {
    "verdict": "partial",
    "required_facts": [
      {"fact": "User's degree field", "present_in_context": true},
      {"fact": "Graduation year", "present_in_context": false}
    ],
    "reasoning": "..."
  },
  "stage2": [
    {
      "fact": "Graduation year",
      "stage1_present_in_context": false,
      "found_in_chunk": 3,
      "found_in_chunk_text": "[timestamp] user: \"...graduated in 2012...\"",
      "stage1_false_positive": true,
      "truly_missing": false,
      "reasoning": "Episode mentions year 2012"
    }
  ],
  "verdict_final": "sufficient"
}
```

`verdict_final` 계산: required_fact 마다 "실제로 present" 여부 결정 (Stage 2 가 돌았으면 그 결과, 아니면 Stage 1 claim) → 모두 present 면 `sufficient`, 일부면 `partial`, 0 이면 `insufficient`.

## Summary 핵심 지표 (`retrieve_analysis_summary.json`)

| 키 | 의미 |
|---|---|
| `stage1_verdict_dist` | Stage 1 단독 verdict 분포 |
| `final_verdict_dist` | Stage 2 보정 후 분포 |
| `stage2.stage1_false_positive_rate` | Stage 1 noise (= Stage 2 가 뒤집은 비율, stage1-absent fact 만 분모) |
| `stage2.n_truly_missing_facts` | 진짜 retrieval 누락 fact 개수 |
| `stage2.found_in_chunk_rank_distribution` | 정답 정보가 top-k 중 몇 번째 episode 에 있는지 — ranking 진단용 |
| `answer_x_retrieve_quadrant` | 4 분면 분류 |
| `by_category` | 카테고리별 위 지표 |

## 4 분면 해석

|  | answer correct | answer wrong |
|---|---|---|
| **retrieve sufficient** | ✅ 정상 | ⚠️ **answer-LLM 약점** — retrieve 충분했는데 답 못 뽑음 |
| **retrieve partial** | 부분 추론 성공 | 부분 정보 부족 |
| **retrieve insufficient** | lucky guess | ⚠️ **retrieval 약점** — 필요 정보 부재 |

- `sufficient × wrong` 비중이 크면 → answer prompt / answer LLM 개선 여지
- `insufficient × wrong` 비중이 크면 → chunking / embedding / k 튜닝 대상
- `truly_missing_facts` 가 많으면 → ingest 단의 정보 손실

## 비용 예상

500 문항 기준 LLM call 수:

| 모드 | Stage 1 | Stage 2 | 합계 |
|---|---|---|---|
| default | 500 | ~3000 (40% × 3 fact × ~5 chunk early-exit) | ~3500 |
| `--skip-stage2` | 500 | 0 | 500 |
| `--pin-all-facts` | 500 | ~7500 (모든 fact × ~5 chunk) | ~8000 |

Gemini 2.5 Flash free tier (15 RPM) 기준 default ~4 시간, pin-all ~9 시간.
`--concurrency` 와 `evaluation.judge_concurrency` 로 조절.

## 제약 / 주의

- Stage 1 의 fact decomposition 은 LLM 일관성에 의존 — 같은 question 두 번 돌리면 분해가 다를 수 있음. `temperature=0` 으로 일부 완화.
- Stage 2 의 paraphrase 인식도 LLM 의존. small/quantized 모델은 표현 차이를 놓침.
- episode 경계 분리: `chunks_text` 의 `\n` (single newline) 기준. retrieve.py 가 timestamp-prefixed utterance 들을 `\n` 으로 join 한 결과.
- `--skip-stage2` 거나 Stage 1 verdict=`sufficient` 일 때: chunk pinning 정보 없음. 모든 fact 의 chunk 위치 원하면 `--pin-all-facts`.
- 기존 LongMemEval 의 `supporting_facts` 는 dataset annotation noise 가 있어 ground truth 로 안 씀. LLM 의 직접 판정을 신호로 사용.
