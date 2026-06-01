# Adaptive-k cut 기준 리포트 — bias 적용 전 vs 후

MemMachine retrieval 의 adaptive-k 가 "몇 개를 회수할지(k)" 를 어떻게 정하는지,
**bias 도입 전(plain largest-gap)** 과 **도입 후(position-weighted gap)** 를
코드 + 숫자 예제로 비교한다.

대상 코드: `packages/server/src/memmachine_server/retrieval_agent/common/agent_api.py`
의 `adaptive_k_cutoff()`.

---

## 0. 공통 전제 — 입력이 뭐고 "gap" 이 뭔가

adaptive-k 는 검색된 후보들의 **관련도 점수(score)** 를 받는다. 점수는 reranker 가
매긴 "질문과 이 chunk 가 얼마나 관련 있나" 값이고, **높을수록 관련** 이다.

cutoff 함수에 들어올 땐 이미 **내림차순 정렬** 돼 있다:

```
순위(k위치)   1     2     3     4     5
score       0.95  0.60  0.58  0.55  0.52
```

**gap** = 인접한 두 점수의 차이. "여기서 자르면 떨어지는 낙차" 다.

```
score:  0.95   0.60   0.58   0.55   0.52
          └─gap─┘ └gap┘ └gap┘ └gap┘
gap at k:  0.35   0.02   0.03   0.03
           (k=1)  (k=2)  (k=3)  (k=4)
```

- `gap at k` = "상위 **k** 개만 남기고 자를 때" 생기는 낙차
  = `score[k-1] - score[k]` (0-index 기준).
- adaptive-k 의 아이디어: **가장 큰 낙차(절벽) 앞에서 자르면**, 관련 있는 무리와
  관련 없는 무리의 경계를 잡을 수 있다 (Taguchi et al., EMNLP 2025).

이 "어느 gap 에서 자를까" 의 **기준** 이 bias 전/후의 차이다.

---

## 1. [전] plain largest-gap — "무조건 제일 큰 gap"

### 코드

```python
def adaptive_k_cutoff(scores_desc, min_k, max_k):
    n = len(scores_desc)
    min_k = max(1, min_k)
    if n <= min_k:
        return n
    upper = min(max_k, n) if max_k > 0 else n   # 회수 상한 (0이면 풀 전체)
    last = min(upper, n - 1)
    best_k = upper
    best_gap = -1.0
    for k in range(min_k, last + 1):            # 자를 수 있는 모든 위치를 본다
        gap = scores_desc[k - 1] - scores_desc[k]   # 그 위치의 낙차
        if gap > best_gap:                      # ← 기준: 낙차가 제일 크면
            best_gap = gap
            best_k = k                          #         거기서 자른다
    return best_k                               # 상위 best_k 개 회수
```

### 한 줄 요약

> **모든 gap 중 값이 가장 큰 곳에서 자른다.** (위치는 신경 안 씀)

### 숫자로 따라가기 — `[0.95, 0.60, 0.58, 0.55, 0.52]`, min_k=1, max_k=0

| 자르는 위치 k | 남기는 개수 | gap (낙차) | 제일 큰가? |
|:---:|:---:|:---:|:---:|
| k=1 | 1개 | **0.35** | ✅ 최대 |
| k=2 | 2개 | 0.02 | |
| k=3 | 3개 | 0.03 | |
| k=4 | 4개 | 0.03 | |

→ 최대 gap 은 **k=1 의 0.35** → **상위 1개만 회수**.

```
0.95 ██████████████████████  ←★ 여기서 컷 (gap 0.35 가 압도적)
─────────────────────────────  ✂  k=1
0.60 ██████████████          ┐
0.58 █████████████▌          │  이 4개는 서로 비슷한데
0.55 █████████████           │  통째로 버려짐 → recall 손해
0.52 ████████████▌           ┘
```

### 문제점

1 등 점수가 나머지보다 **유독 높을 때**(검색에서 흔함), 첫 gap 이 가장 커서
**k=1 로 잘린다**. aggregation / multi-hop 처럼 **여러 근거가 필요한 질문** 은
나머지 4개에 정답 근거가 흩어져 있어도 다 버려 → **recall 급락**.

이게 "지금 너무 공격적으로 잘려서 recall 이 크게 줄었다" 의 정체다.

---

## 2. [후] position-weighted gap — "위치까지 고려한 gap"

### 코드 (바뀐 줄만 ◀)

```python
def adaptive_k_cutoff(scores_desc, min_k, max_k, bias=0.0):   # ◀ bias 추가
    n = len(scores_desc)
    min_k = max(1, min_k)
    if n <= min_k:
        return n
    upper = min(max_k, n) if max_k > 0 else n
    last = min(upper, n - 1)
    best_k = upper
    best_score = -1.0
    for k in range(min_k, last + 1):
        gap = scores_desc[k - 1] - scores_desc[k]
        weighted = gap * (k ** bias)            # ◀ 핵심: 위치 가중
        if weighted > best_score:               # ◀ 기준: "가중된 gap" 이 최대면
            best_score = weighted
            best_k = k
    return best_k
```

### 한 줄 요약

> gap 을 그냥 비교하지 않고, **`gap × k^bias`** 로 비교한다.
> k(남기는 개수)가 클수록 가중치가 커지므로 **뒤쪽(많이 남기는) 컷을 선호** 한다.
> `bias=0` 이면 `k^0 = 1` 이라 **예전과 완전히 동일** (후방호환).

### 왜 이게 "공격성 조절" 인가

- 앞쪽 컷(k 작음) = 가중치 작음 → 손해
- 뒤쪽 컷(k 큼) = 가중치 큼 → 이득
- 그래서 **앞쪽의 큰 gap 이 뒤쪽의 작은 gap 을 이기려면, bias 가 높을수록 더 압도적
  이어야** 한다. bias 를 올릴수록 "어지간한 1등 낙차로는 k=1 로 못 자른다".

### 같은 숫자로 따라가기 — `[0.95, 0.60, 0.58, 0.55, 0.52]`

`weighted = gap × k^bias`. bias 를 0 → 2 로 올려본다:

| k | 남김 | gap | `×k^0`(bias0) | `×k^1`(bias1) | `×k^2`(bias2) |
|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | 1개 | 0.35 | **0.35** ✅ | **0.35** ✅ | 0.35 |
| 2 | 2개 | 0.02 | 0.02 | 0.04 | 0.08 |
| 3 | 3개 | 0.03 | 0.03 | 0.09 | 0.27 |
| 4 | 4개 | 0.03 | 0.03 | 0.12 | **0.48** ✅ |
| **선택 k** | | | **1** | **1** | **4** |

- **bias 0**: k=1 (예전과 동일, 공격적)
- **bias 1**: 아직 0.35 가 너무 압도적 → k=1
- **bias 2**: k=4 의 가중 gap 0.48 이 0.35 를 추월 → **상위 4개 회수** (recall 회복)

```
bias=2 일 때:
0.95 ██████████████████████   ← 1등은 여전히 특별
0.60 ██████████████          ┐
0.58 █████████████▌          │  비슷한 무리를 함께 유지
0.55 █████████████           │
0.52 ████████████▌           ┘
──────────────────────────────  ✂  k=4 (여기서 컷)
```

### 진짜 절벽은 bias 와 무관하게 그대로 잘린다 — `[0.9, 0.88, 0.85, 0.2, 0.18]`

| k | gap | bias0 | bias1 | bias2 |
|:--:|:--:|:--:|:--:|:--:|
| 1 | 0.02 | 0.02 | 0.02 | 0.02 |
| 2 | 0.03 | 0.03 | 0.06 | 0.12 |
| 3 | **0.65** | **0.65** ✅ | **1.95** ✅ | **5.85** ✅ |
| 4 | 0.02 | 0.02 | 0.08 | 0.32 |
| **선택 k** | | **3** | **3** | **3** |

상위 3개 뒤에 **0.65 라는 분명한 절벽** 이 있으면, bias 를 올려도 k=3 으로 동일.
즉 bias 는 "신호가 애매할 때만" 뒤쪽을 밀어주고, **명확한 경계는 존중** 한다.
(과하게 많이 남기지 않음)

---

## 3. 전 vs 후 한눈에

| | [전] plain largest-gap | [후] weighted gap |
|---|---|---|
| 자르는 기준 | `max(gap)` | `max(gap × k^bias)` |
| 위치 고려 | ❌ | ✅ (뒤쪽 컷 선호) |
| 외부 조절 | min_k / max_k 만 | **+ bias (공격성)** |
| 1등 지배 시 | k=1 로 잘림 (recall↓) | bias 로 완화 가능 |
| 명확한 절벽 | 그대로 컷 | 그대로 컷 (동일) |
| 기본값 동작 | — | `bias=0` = 전과 **완전 동일** |

조절 파라미터 (QueryParam ↔ V1 CLI):

| 파라미터 | CLI | 역할 | recall 관점 |
|---|---|---|---|
| `adaptive_k_bias` | `--adaptive-bias` | 컷 공격성(소프트) | 올리면 늦게 컷 → 더 많이 유지 |
| `adaptive_k_min` | `--adaptive-min-k` | 회수 하한(하드) | **가장 확실한 recall 바닥** |
| `adaptive_k_max` | `--adaptive-max-k` | 회수 상한 | 토큰 폭발 방지 |

> **튜닝 전략**: recall 이 급하면 `min_k` 로 바닥을 깔고(무조건 N개 보장),
> 토큰을 더 아끼며 모양만 다듬으려면 `bias` 를 0.5 → 2.0 으로 sweep.
> 선택된 `kept` / `bias` 는 `retrieve.jsonl` 의 `adaptive_kept` / `adaptive_bias`
> 필드와 로그(`adaptive_k: pool=.. kept=.. bias=..`)에 질문마다 기록된다.

---

## 4. 직접 돌려보기

```python
def adaptive_k_cutoff(scores_desc, min_k, max_k, bias=0.0):
    n = len(scores_desc)
    min_k = max(1, min_k)
    if n <= min_k:
        return n
    upper = min(max_k, n) if max_k > 0 else n
    last = min(upper, n - 1)
    best_k, best = upper, -1.0
    for k in range(min_k, last + 1):
        w = (scores_desc[k - 1] - scores_desc[k]) * (k ** bias)
        if w > best:
            best, best_k = w, k
    return best_k

s = [0.95, 0.60, 0.58, 0.55, 0.52]
for b in (0.0, 1.0, 2.0):
    print(f"bias={b} -> keep {adaptive_k_cutoff(s, 1, 0, b)}")
# bias=0.0 -> keep 1
# bias=1.0 -> keep 1
# bias=2.0 -> keep 4
```

실제 평가에서:

```bash
# 같은 ingest 로 bias sweep (recall vs k 트레이드오프 관찰)
for b in 0 0.5 1 1.5 2; do
  uv run python -m evaluation.longmemeval.retrieve \
      --in-file evaluation/data/longmemeval_s_cleaned.json \
      --config-path evaluation/longmemeval/configuration.yml \
      --session-prefix $PREFIX --top-k 50 --adaptive-k --adaptive-bias $b \
      --out results/$PREFIX/retrieve_bias$b.jsonl
done

# 카테고리별 평균 k 보기
jq -s 'group_by(.category)[] |
       {category: .[0].category, mean_k: (map(.adaptive_kept)|add/length)}' \
   results/$PREFIX/retrieve_bias1.jsonl
```

자세한 사용법은 `docs/msr/adaptive_k_retrieval.md`.
