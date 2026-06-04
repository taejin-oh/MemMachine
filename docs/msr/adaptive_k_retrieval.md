# Adaptive-k retrieval 사용 가이드 (MemMachine)

질문마다 고정 top-k 대신 **점수 분포의 가장 큰 gap** 앞까지만 회수하는 MemMachine
retrieval 옵션. 고정 k 가 적으면 근거 누락, 많으면 노이즈 + 토큰 낭비 — adaptive-k 는
질문별로 적정 개수를 자동 선택한다 (factoid 는 적게, aggregation 은 많게).

근거: Taguchi et al., *"No Tuning, No Iteration, Just Adaptive-k"* (EMNLP 2025),
largest-gap 휴리스틱. 구현은 순수 Python (torch/numpy 의존 없음).

## 어디에 들어가 있나

`MemMachineAgent.do_query` **자체** 에 들어가 있다 (벤치마크 어댑터가 아니라
MemMachine 서버 retrieval 동작). 따라서 이 agent 를 쓰는 모든 경로 —
`evaluation/longmemeval/` (V1), `evaluation/longmemeval_v2/`, 서버 API — 에서
`QueryParam(adaptive_k=True)` 한 줄로 켤 수 있다.

| 위치 | 파일 |
|---|---|
| cutoff 함수 + `QueryParam` 필드 | `packages/server/src/memmachine_server/retrieval_agent/common/agent_api.py` |
| do_query 적용 | `packages/server/src/memmachine_server/retrieval_agent/agents/memmachine_retriever.py` |
| V1 eval CLI | `evaluation/longmemeval/retrieve.py` |

**기본값은 OFF** — 켜지 않으면 기존 고정 top-k 동작과 byte-identical.

## 켜고 끄는 법

### A. V1 LongMemEval 평가 (`evaluation/longmemeval/retrieve.py`)

```bash
# OFF (기본) — 고정 top-k 50
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path evaluation/longmemeval/configuration.yml \
    --session-prefix $PREFIX --top-k 50 \
    --out results/$PREFIX/retrieve_fixed.jsonl

# ON — top-k 50 을 "후보 풀" 로 보고 gap 앞까지만 회수
uv run python -m evaluation.longmemeval.retrieve \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    --config-path evaluation/longmemeval/configuration.yml \
    --session-prefix $PREFIX --top-k 50 --adaptive-k \
    --out results/$PREFIX/retrieve_adaptive.jsonl
```

ingest 는 재사용 (재-ingest 불필요) — retrieve 단계만 두 번 돌려 A/B 한다.

### B. 코드/서버에서 직접

```python
from memmachine_server.retrieval_agent.common.agent_api import QueryParam, QueryPolicy

chunks, perf = await query_agent.do_query(
    QueryPolicy(token_cost=10, time_cost=10, accuracy_score=10, confidence_score=10),
    QueryParam(
        query=question,
        limit=50,            # 후보 풀 크기
        memory=memory,
        adaptive_k=True,     # ← 켜기
        adaptive_k_min=1,    # 최소 회수 수
        adaptive_k_max=0,    # 0 = 후보 풀 전체가 상한
    ),
)
```

## 파라미터

| QueryParam | CLI (V1) | 기본 | 의미 |
|---|---|---|---|
| `adaptive_k` | `--adaptive-k` | `False` | 켜기/끄기 |
| `limit` | `--top-k` | `50` | **후보 풀** 크기. gap 은 이 안에서 선택 |
| `adaptive_k_min` | `--adaptive-min-k` | `1` | 회수 하한 (점수가 급락해도 최소 이만큼은 유지) |
| `adaptive_k_max` | `--adaptive-max-k` | `0` | 회수 상한. `0` = 후보 풀(`limit`) 전체 |
| `adaptive_k_bias` | `--adaptive-bias` | `0.0` | **cut 공격성**. 0 = plain largest-gap(가장 공격적), 높일수록 늦게 자름 → 더 많이 유지(recall↑) |

- **`limit`(top-k)** 은 adaptive-k ON 일 때 "최종 개수" 가 아니라 "후보 풀" 이다.
  풀이 작으면 gap 을 찾을 여지가 적으니, 후보를 넉넉히(예: 50) 주고 cut 에 맡긴다.
- **`adaptive_k_max`** 는 reader context 폭발을 막는 하드 실링. 풀은 크게 두되
  "아무리 많아도 N 개" 로 제한하고 싶을 때 사용.
- **`adaptive_k_min`** 은 under-retrieval 방지. 점수가 1 등 직후 급락하는 질문에서
  최소 회수 수를 보장.
- **`adaptive_k_bias`** 는 "얼마나 공격적으로 자를지". largest-gap 은 1 등 점수가
  나머지보다 크게 높으면 **첫 gap(k=1)** 이 최대가 돼 k=1 로 잘리는 경향이 있다
  (recall 급락). 각 gap 을 `k**bias` 로 가중해 늦은 cut 을 선호하게 만든다.
  `0` = 무가중(가장 공격적), `0.5~2.0` 으로 올리면 지배적 top gap 이 더 이상 단독
  우승하지 못해 비슷한 점수의 cluster 를 함께 유지. 단, **진짜 cliff** (예: 상위 3 개
  뒤 큰 낙차) 는 bias 와 무관하게 그대로 잘린다.

### recall 이 너무 떨어질 때 (k 가 과하게 작을 때)

| 증상 | 처방 |
|---|---|
| 대부분 질문이 `adaptive_kept=1~2` 로 잘림 | `--adaptive-bias 1.0` (안 되면 1.5, 2.0) 으로 공격성 완화 |
| 특정 카테고리(aggregation/multi-hop) recall 만 낮음 | `--adaptive-min-k` 를 그 카테고리 근거 수만큼 올림 (가장 확실한 recall 하한) |
| 한두 질문만 과소 회수 | `--adaptive-min-k 2~3` 로 전역 하한만 살짝 |

> `bias` 는 "점수 모양 기반 소프트 조정", `min_k` 는 "무조건 보장 하한". recall 이
> 급하면 `min_k` 로 바닥을 깔고, 토큰을 더 아끼려면 `bias` 로 모양을 다듬는다.
> `adaptive_bias` 값은 retrieve.jsonl 의 `adaptive_bias` 필드와 로그(`bias=..`)에
> 기록되므로 sweep 결과를 추적할 수 있다.

## 각 질문마다 선택된 k 확인

ON 으로 돌리면 `retrieve.jsonl` 의 **각 row** 에 다음 필드가 추가된다:

| 필드 | 의미 |
|---|---|
| `adaptive_k` | 이 질문에 adaptive-k 가 적용됐는지 (`true`/`false`) |
| `adaptive_pool` | 후보 풀 크기 (점수 있는 후보 수) |
| `adaptive_kept` | **선택된 k** (실제 회수 chunk 수) |
| `adaptive_score_hi` | 풀 내 최고 점수 |
| `adaptive_score_cut` | cut 지점(마지막으로 유지된) 점수 |
| `num_episodes_retrieved` | 회수 chunk 수 (= `adaptive_kept`) |

### jq 로 보기

```bash
OUT=results/$PREFIX/retrieve_adaptive.jsonl

# 질문별 선택된 k (질문ID, 카테고리, pool→kept, 점수 hi..cut)
jq -r '[.question_id, .category, .adaptive_pool, .adaptive_kept,
        .adaptive_score_hi, .adaptive_score_cut] | @tsv' "$OUT"

# k 분포 요약 (min / 평균 / max)
jq -s 'map(.adaptive_kept) | {min:min, max:max, mean:(add/length), n:length}' "$OUT"

# 카테고리별 평균 k
jq -s 'group_by(.category)[] |
       {category: .[0].category, mean_k: (map(.adaptive_kept)|add/length), n: length}' "$OUT"
```

### 로그로 보기

retrieve 실행 중 질문마다 한 줄씩 찍힌다 (`logging.INFO`):

```
adaptive_k: pool=50 kept=7 (score 0.8123..0.5440)
```

`kept` 이 선택된 k, 괄호는 최고 점수와 cut 지점 점수.

## A/B 비교 (fixed vs adaptive)

```bash
# 1) 같은 ingest 로 두 retrieve 생성 (위 A 섹션)
# 2) 각각 generate → judge
for tag in fixed adaptive; do
  uv run python -m evaluation.longmemeval.generate \
      --retrieve results/$PREFIX/retrieve_$tag.jsonl \
      --config-path evaluation/longmemeval/configuration.yml \
      --out results/$PREFIX/generate_$tag.jsonl
  uv run python -m evaluation.longmemeval.judge \
      --generate results/$PREFIX/generate_$tag.jsonl \
      --config-path evaluation/longmemeval/configuration.yml \
      --out results/$PREFIX/judge_$tag.jsonl
done
```

보는 지표:
- **정확도** (judge yes 비율) — adaptive 가 fixed 50 대비 유지/개선되는지
- **평균 k** (`adaptive_kept`) — 토큰/노이즈를 얼마나 줄였는지
- **recall** — `recall_id.py` 로 gold turn 회수율이 떨어지지 않는지 (회수 수를 줄이는
  옵션이라 recall 하락 여부가 핵심 체크)

## 동작 원리 (요약)

1. `query_memory(limit=후보 풀)` 로 점수 달린 후보를 받는다.
   (declarative search 가 score 내림차순 정렬 후 풀 크기로 truncate)
2. 후보를 score 내림차순 정렬 → 연속한 두 점수 차(gap)가 가장 큰 지점을 찾는다.
3. 그 지점 앞까지 유지 (`[adaptive_k_min, adaptive_k_max]` 로 clamp).
4. 생존자는 **원래(시간) 순서** 로 되돌려 반환 → 다운스트림 포맷/ID 추출은 개수만 달라짐.

## 주의 / 제약

- **reranker 필요**: 점수가 "높을수록 관련" 이어야 gap 방향이 맞다. configuration.yml 에
  reranker (또는 cosine/dot embedder) 가 설정돼 있어야 한다. raw euclidean(리랭커 없음)
  은 방향이 반대라 부적합.
- **풀이 작으면 효과 제한**: 후보가 2~3 개뿐이면 자를 여지가 적다. `--top-k` 를 넉넉히.
- **점수가 평평하면** (모두 비슷) gap 신호가 약해 `adaptive_k_min` 로 떨어진다. 이때
  under-retrieval 이 걱정되면 `--adaptive-min-k` 를 올린다.
- **튜닝은 데이터 보고**: 먼저 ON 으로 돌려 `adaptive_kept` 분포를 본 뒤
  `--adaptive-max-k`(상한) / `--adaptive-min-k`(하한) 를 조정한다.
