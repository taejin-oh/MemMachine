# MemMachine Adaptive-k Retrieval & Position Bias — PPT 콘텐츠

> Branch `v0.3.9_msr` · 기술 발표용 슬라이드 원고
> 이 문서를 챗 Claude에게 전달하면 슬라이드로 렌더링할 수 있습니다.
> 내러티브는 한국어, 코드·식별자·기술 용어는 영어. 모든 코드/수치는 실제 구현(`v0.3.9_msr`)에서 검증됨.

**전달 시 한 줄 지시 예시:** "아래 마크다운을 14장짜리 기술 발표 슬라이드로 만들어줘. 각 슬라이드의 '내용'은 슬라이드 본문 bullet로, '발표 노트'는 speaker notes로 넣고, 코드 블록과 다이어그램/표는 그대로 살려줘. 톤은 엔지니어/연구자 대상."

---

## Slide 1 — 표지

**내용**
- **MemMachine Adaptive-k Retrieval & Position Bias**
- 부제: largest-gap 컷오프 + position-bias 가중으로 질문별 회수량을 자동 결정
- Branch: `v0.3.9_msr`
- 대상: engineers / researchers

**발표 노트**
이 발표는 MemMachine의 retrieval 단계에 도입된 adaptive-k 컷오프와 그 위에 얹은 position-bias 가중치를 다룹니다. 고정 top-k가 가진 구조적 한계를 짚고, largest-gap 휴리스틱을 어떻게 순수 파이썬으로 구현했는지, 그리고 strong reranker 환경에서 발생하는 병리를 bias 한 줄로 어떻게 완화했는지를 코드 수준에서 설명합니다. 모든 수치와 코드는 `v0.3.9_msr` 브랜치의 실제 구현에서 가져왔습니다.

---

## Slide 2 — 배경 / 문제: 고정 top-k의 한계

**내용**
- 질문마다 **필요한 근거(evidence) 수가 다르다**
  - factoid(단일 사실): 1~2개면 충분
  - aggregation / multi-hop: 여러 개의 근거가 흩어져 있음
- 고정 top-k의 딜레마:
  - k가 **크면** → noise 유입 + 토큰/latency 낭비
  - k가 **작으면** → 필요한 근거 누락 → **recall 손실**
- "올바른 k"는 query마다 다른데 고정값은 이를 반영 못 함

**발표 노트**
RAG/long-context QA에서 top-k는 보통 하나의 상수로 고정됩니다. 그러나 단일 사실을 묻는 질문과 여러 근거를 모아야 하는 aggregation 질문은 필요한 chunk 수가 본질적으로 다릅니다. k를 크게 잡으면 무관한 chunk가 reader 프롬프트를 오염시키고 토큰과 지연을 늘리며, 작게 잡으면 흩어진 근거를 놓쳐 recall이 무너집니다. 핵심은 "질문마다 최적 k가 다르다"는 점이고, 고정 top-k는 이를 원리적으로 맞출 수 없습니다.

---

## Slide 3 — 참조 연구 한눈에

**내용**
- **[1] Adaptive-k (Taguchi et al., EMNLP 2025)**
  - 정렬된 query–candidate 유사도의 **largest gap**에서 컷
  - single-pass · training-free · "no tuning, no iteration"
  - retriever/reader 변경 없이: **full-context 대비 최대 10× 적은 토큰**으로 관련 passage의 **~70% 회수**
  - arXiv:2506.08479 · code: github.com/megagonlabs/adaptive-k-retrieval · **BSD-3-Clause**
- **[2] CAR / Cluster-based Adaptive Retrieval (Xu et al., 2025, Coinbase)**
  - 정렬·정규화된 distance를 **clustering**(K-Means/DBSCAN/HDBSCAN)해서 경계 탐지
  - **gap 크기 + position penalty**를 결합한 composite score로 컷
  - 보고 수치: **token -60%, latency -22%, hallucination -10%** (CDP + MultiHop-RAG)
  - arXiv:2511.14769 · **공개 코드 없음**

**발표 노트**
두 논문 모두 "고정 top-k는 query 복잡도를 못 따라간다"는 동일한 문제의식에서 출발합니다. Adaptive-k는 점수 분포의 모양만 보고 가장 큰 낙폭에서 자르는 극단적으로 단순한 방법이고, 학습이나 추가 LLM 호출이 없다는 점이 핵심 주장입니다. CAR은 같은 문제를 clustering으로 풀되, gap 크기에 position penalty를 결합한 composite score로 경계를 정합니다. **MemMachine은 [1]을 직접 구현하고 [2]의 position penalty 직관만 빌려옵니다** — 자세한 관계는 Slide 10 참고.

---

## Slide 4 — Adaptive-k 원리: largest-gap

**내용**
- 입력: reranker relevance score 리스트, **내림차순 정렬**(높을수록 관련)
- **gap** = 인접 점수의 차이 = "여기서 자르면 떨어지는 절벽 높이"
  - `gap at k = score[k-1] - score[k]`
- **가장 큰 낙폭 바로 앞에서 컷** → 관련 cluster와 무관 cluster를 분리
- 논문은 `torch.diff` / `argmin` 사용 → MemMachine은 **순수 파이썬**으로 동일 결과 (torch/numpy 의존성 없음)

```
순위(k위치)   1     2     3     4     5
score       0.95  0.60  0.58  0.55  0.52
              └gap┘ └gap┘ └gap┘ └gap┘
gap at k:     0.35  0.02  0.03  0.03
              (k=1) (k=2) (k=3) (k=4)
                ↑ 최대 낙폭 → 여기서 컷
```

**발표 노트**
직관은 단순합니다. 점수를 내림차순으로 늘어놓고 인접한 두 점수의 차이(gap)를 보면, 가장 큰 gap이 "관련 있는 무리"와 "관련 없는 무리"의 경계입니다. 거기서 자르면 됩니다. factoid 질문은 1등이 압도적이라 앞에서, aggregation 질문은 여러 점수가 비슷하다 뒤에서 자연스럽게 잘립니다. 논문은 torch로 구현했지만 MemMachine은 의존성 없이 순수 파이썬 루프로 같은 결과를 냅니다.

---

## Slide 5 — MemMachine 파이프라인에서의 위치

**내용**
- 점수는 **RERANKER 점수**(벡터 유사도 아님)
- adaptive-k는 **리랭킹 후 후처리 컷** (upstream 작업량 불변)
- 최종 출력 순서는 **시간순 (timestamp, uid)**, 선택만 점수가 결정

```
[다이어그램: retrieval data flow]

query
  │ embed
  ▼
vector search  ─ limit = min(5 * max_num_episodes, 200)   ← 후보 풀
  │  (derivative nodes)
  ▼
source episodes → contextualize
  │
  ▼
RERANKER.score(query, context_strings)     ← 점수의 출처
  │  (정렬: score desc)
  ▼
_unify_...   선택 = score / 정렬 = (timestamp, uid)
  │
  ▼
query_memory → EpisodeResponse(score=score, ...)
  │   long_term_memory.episodes[i].score
  ▼
_apply_adaptive_k   ← e.score 읽어 largest-gap 컷 (POST-rerank)
  │
  ▼
survivors (시간순 유지) → answer LLM 프롬프트
```

**발표 노트**
중요한 사실 두 가지입니다. 첫째, adaptive-k가 읽는 점수는 벡터 거리(distance)가 아니라 reranker 점수입니다. reranker가 context 문자열을 채점한 값이 `long_term_memory.episodes[i].score`까지 그대로 흘러옵니다. 둘째, adaptive-k는 vector search(`limit=min(5*max_num_episodes, 200)`)와 전체 reranking이 끝난 뒤 이미 만들어진 결과의 prefix만 자르는 후처리입니다. 따라서 retrieve 단계 연산량은 변하지 않고, 줄어드는 것은 반환되는 episode 개수뿐입니다. 최종 정렬 키는 `(timestamp, uid)`라 출력은 항상 시간순입니다.

---

## Slide 6 — 핵심 코드 ① `adaptive_k_cutoff`

**내용**
- 위치: `agent_api.py:24-61`
- 시그니처: `adaptive_k_cutoff(scores_desc, min_k, max_k, bias=0.0) -> int`
- 반환: 유지할 top item 개수 `k` (`[min_k, max_k]`로 clamp)

```python
def adaptive_k_cutoff(
    scores_desc: list[float], min_k: int, max_k: int, bias: float = 0.0
) -> int:
    n = len(scores_desc)
    min_k = max(1, min_k)                      # 하한은 1 미만 불가
    if n <= min_k:
        return n                               # 풀이 하한 이하면 전부 반환
    upper = min(max_k, n) if max_k > 0 else n  # max_k<=0 → 풀 크기가 상한
    last = min(upper, n - 1)                    # gap 잴 수 있는 최대 컷
    best_k = upper
    best_score = -1.0
    for k in range(min_k, last + 1):
        gap = scores_desc[k - 1] - scores_desc[k]
        weighted = gap * (k**bias)             # 핵심: 위치 가중
        if weighted > best_score:              # strict > → 동점이면 작은 k
            best_score = weighted
            best_k = k
    return best_k
```

**발표 노트**
함수는 내림차순 점수 리스트를 받아 "몇 개를 남길지"를 정수로 돌려줍니다. 루프는 `min_k`부터 `last`까지 각 컷 위치 k의 gap을 계산하고, `gap * k**bias`가 최대인 k를 고릅니다. `bias=0.0`이면 `k**0 = 1`이라 정확히 plain largest-gap입니다. 비교가 strict `>`라 동점일 때는 더 작은(앞쪽) k가 유지됩니다. `min_k`는 하한 floor, `max_k<=0`은 상한 해제(풀 크기가 천장)로 동작합니다.

---

## Slide 7 — 핵심 코드 ② `_apply_adaptive_k`

**내용**
- 위치: `memmachine_retriever.py:100-144` (`@staticmethod`)
- 흐름: **점수 정렬 → 컷 → 원(시간)순 복원 → info dict**
- survivor는 **원래 `scored` 순서(시간순)** 그대로 유지 (membership test만)

```python
ranked = sorted(scored,
    key=lambda e: e.score if e.score is not None else float("-inf"),
    reverse=True)
scores_desc = [e.score for e in ranked if e.score is not None]
if not scores_desc:
    return scored, {"adaptive_k": True, "adaptive_pool": len(scored)}
keep = adaptive_k_cutoff(scores_desc,
    query.adaptive_k_min, query.adaptive_k_max, query.adaptive_k_bias)
kept_uids = {e.uid for e in ranked[:keep]}
info = {
    "adaptive_k": True, "adaptive_pool": len(scores_desc),
    "adaptive_kept": keep, "adaptive_bias": query.adaptive_k_bias,
    "adaptive_score_hi": round(scores_desc[0], 6),
    "adaptive_score_cut": round(scores_desc[keep - 1], 6),
}
return [e for e in scored if e.uid in kept_uids], info
```

호출부 (`do_query`, lines 75-77):
```python
if query.adaptive_k and scored:
    scored, ak_info = self._apply_adaptive_k(scored, query)
    perf_metrics.update(ak_info)
```

**발표 노트**
`scored`는 `query_response.long_term_memory.episodes` 리스트(시간순)입니다. 이 함수는 복사본을 점수 내림차순으로 정렬해 `scores_desc`를 만들고(None 점수는 `-inf`로 가라앉아 제외), `adaptive_k_cutoff`로 `keep`을 얻습니다. 그다음 상위 `keep`개의 uid 집합을 만들고, **원래 `scored`를 순회**하면서 그 집합에 속한 항목만 남깁니다 — membership test는 순서와 무관하므로 시간순이 보존됩니다. 반환되는 info dict는 `perf_metrics`에 merge되어 per-query k를 기록합니다.

---

## Slide 8 — Bias 도입 동기: strong-reranker × largest-gap 병리

**내용**
- plain largest-gap = "gap이 가장 큰 곳에서 컷" (위치 무시)
- **strong/confident reranker**는 1등 점수가 유난히 높음 → **첫 gap(k=1)이 최대** → **k=1로 과도 컷**
- aggregation / multi-hop은 근거가 여러 후보에 흩어짐 → 전부 버려짐 → **recall collapse**

수치 예시: `[0.95, 0.60, 0.58, 0.55, 0.52]`, `min_k=1, max_k=0`

| 자르는 위치 k | 남기는 개수 | gap (낙차) | 제일 큰가? |
|:---:|:---:|:---:|:---:|
| k=1 | 1개 | **0.35** | ✅ 최대 |
| k=2 | 2개 | 0.02 | |
| k=3 | 3개 | 0.03 | |
| k=4 | 4개 | 0.03 | |

```
0.95 ██████████████████████  ←★ 여기서 컷 (gap 0.35 가 압도적)
─────────────────────────────  ✂  k=1
0.60 ██████████████          ┐
0.58 █████████████▌          │  이 4개는 서로 비슷한데
0.55 █████████████           │  통째로 버려짐 → recall 손해
0.52 ████████████▌           ┘
```

**발표 노트**
plain largest-gap의 약점은 "위치를 보지 않는다"는 것입니다. weak reranker라면 점수가 완만해 문제없지만, strong reranker는 정답 1개에 매우 높은 점수를 주는 경향이 있어 첫 번째 gap이 압도적으로 커집니다. 그러면 알고리즘은 무조건 k=1로 자릅니다. 단일 사실 질문엔 맞지만, 여러 근거를 모아야 하는 질문에서는 나머지 비슷한 점수의 후보가 통째로 버려져 recall이 급락합니다. 위 예시에서 0.35라는 첫 gap이 0.02~0.03을 압도해 top-1만 남깁니다.

---

## Slide 9 — Bias 정의와 효과: `gap * k**bias`

**내용**
- 컷 기준을 `max(gap)` → `max(gap × k^bias)`로 변경
- k(남기는 수)가 뒤로 갈수록 weight ↑ → **늦은(더 많이 남기는) 컷 선호**
- `bias=0` → `k^0=1` → **plain largest-gap과 완전 동일**(backward compatible)
- 높일수록 → keep more → **recall ↑**

동일 점수 `[0.95, 0.60, 0.58, 0.55, 0.52]`, bias 0 → 2:

| k | 남김 | gap | `×k^0` | `×k^1` | `×k^2` |
|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | 1개 | 0.35 | **0.35**✅ | **0.35**✅ | 0.35 |
| 2 | 2개 | 0.02 | 0.02 | 0.04 | 0.08 |
| 3 | 3개 | 0.03 | 0.03 | 0.09 | 0.27 |
| 4 | 4개 | 0.03 | 0.03 | 0.12 | **0.48**✅ |
| **선택 k** | | | **1** | **1** | **4** |

명확한 절벽 `[0.9, 0.88, 0.85, 0.2, 0.18]` → bias 0/1/2 **모두 k=3** (경계 존중)

```python
s = [0.95, 0.60, 0.58, 0.55, 0.52]
for b in (0.0, 1.0, 2.0):
    print(f"bias={b} -> keep {adaptive_k_cutoff(s, 1, 0, b)}")
# bias=0.0 -> keep 1
# bias=1.0 -> keep 1
# bias=2.0 -> keep 4
```

**Pre/Post 요약**

| | [전] plain largest-gap | [후] weighted gap |
|---|---|---|
| 자르는 기준 | `max(gap)` | `max(gap × k^bias)` |
| 위치 고려 | ❌ | ✅ (뒤쪽 컷 선호) |
| 1등 지배 시 | k=1 (recall↓) | bias로 완화 |
| 명확한 절벽 | 그대로 컷 | 그대로 컷 (동일) |
| 기본값 동작 | — | `bias=0` = 전과 완전 동일 |

**발표 노트**
해법은 raw gap 대신 `gap × k^bias`를 비교하는 것입니다. k는 뒤로 갈수록 커지므로 `k^bias`가 뒤쪽 컷에 가중치를 주고, 앞쪽 큰 gap이 이기려면 bias가 높을수록 더 압도적이어야 합니다. 예시에서 bias=2일 때 k=4의 weighted gap 0.48이 0.35를 넘어 top-4를 유지해 recall이 회복됩니다. 중요한 점은 `[0.9, 0.88, 0.85, 0.2, 0.18]`처럼 0.65짜리 진짜 절벽이 있으면 bias를 올려도 여전히 k=3이라는 것 — bias는 신호가 애매할 때만 뒤를 밀고 명확한 경계는 존중합니다. `bias=0`은 기존 동작과 완전히 동일해 하위 호환됩니다.

---

## Slide 10 — CAR와의 관계: 차용한 것 vs 안 한 것

**내용**
- **차용**: CAR의 **position penalty 직관** — "gap 크기만이 아니라 위치도 컷에 영향" → `k**bias` 한 줄
- **미채용**: CAR의 **clustering 기구 전부**
  - ❌ K-Means / DBSCAN / HDBSCAN
  - ❌ normalized-distance clustering
  - ❌ composite cluster-boundary scoring
- 결론: **MemMachine bias는 CAR가 아니다**
  - = Adaptive-k(largest-gap) + 단조 증가 position weight 한 줄
  - CAR 아이디어에 대한 가벼운 오마주이지 CAR 구현이 아님

```
Adaptive-k (largest-gap)  ──직접 구현──▶  adaptive_k_cutoff (pure Python)
CAR (clustering+position) ──직관만 차용─▶  + gap × k**bias  (clustering 없음)
```

**발표 노트**
혼동을 막기 위한 슬라이드입니다. MemMachine은 Adaptive-k의 largest-gap 규칙을 그대로 구현하고, CAR에서는 오직 "위치가 컷에 영향을 줘야 한다"는 직관 하나만 빌려 `k**bias` 가중으로 표현했습니다. CAR의 핵심인 clustering 알고리즘(K-Means/DBSCAN/HDBSCAN), 정규화 거리 클러스터링, composite scoring은 전혀 들어가 있지 않습니다. 따라서 "bias = CAR"라고 말하면 안 됩니다. 정확히는 largest-gap에 한 줄짜리 단조 position weight를 더한 경량 변형입니다.

---

## Slide 11 — 파라미터 & 사용법

**내용**
- 기본값 **OFF** — 끄면 fixed top-k와 byte-identical
- `QueryParam` 필드 (`agent_api.py:81, 85-90`):

```python
expand_context: int = 0       # 매칭 episode 주변 추가 episode 수 (context 확장)
adaptive_k: bool = False
adaptive_k_min: int = 1
adaptive_k_max: int = 0       # <=0 → 후보 풀이 천장
adaptive_k_bias: float = 0.0  # 높을수록 늦게 컷 (keep more, recall↑)
```

| QueryParam | CLI (V1 longmemeval) | 기본 | 의미 |
|---|---|---|---|
| `adaptive_k` | `--adaptive-k` | `False` | 켜기/끄기 |
| `limit` | `--top-k` | `50` | **후보 풀** 크기 (gap은 이 안에서) |
| `adaptive_k_min` | `--adaptive-min-k` | `1` | 회수 하한 (급락해도 최소 유지) |
| `adaptive_k_max` | `--adaptive-max-k` | `0` | 회수 상한, `0`=풀 전체 |
| `adaptive_k_bias` | `--adaptive-bias` | `0.0` | cut 공격성 (0=가장 공격적) |

```bash
# OFF (기본) — fixed top-k 50
... --top-k 50 --out results/$PREFIX/retrieve_fixed.jsonl
# ON — top-k 50을 후보 풀로 쓰고 gap까지만 keep
... --top-k 50 --adaptive-k --out results/$PREFIX/retrieve_adaptive.jsonl
```

**per-question k 확인** — `adaptive_kept` = 실제 회수 k

```bash
jq -s 'map(.adaptive_kept) | {min:min, max:max, mean:(add/length), n:length}' "$OUT"
# log line:  adaptive_k: pool=50 kept=7 bias=0.00 (score 0.8123..0.5440)
```

**발표 노트**
기본값은 OFF이고, 끈 상태에서는 고정 top-k와 완전히 동일하게 동작합니다. 켜면 `limit`(top-k)는 최종 개수가 아니라 후보 풀 크기가 되므로 넉넉하게(예: 50) 주고 컷이 결정하게 둡니다. ingest는 재사용하고 retrieve만 두 번 돌려 fixed vs adaptive를 A/B 비교합니다. per-question으로 선택된 k는 `retrieve.jsonl`의 `adaptive_kept` 필드나 로그 라인으로 확인하며(로그에는 `pool / kept / bias / score 범위`가 함께 찍힘), jq로 분포(min/mean/max)나 카테고리별 평균 k를 바로 뽑을 수 있습니다. `expand_context`는 매칭 episode 주변 episode를 추가하는 context 확장 파라미터입니다.

---

## Slide 12 — 관측 & 트레이드오프

**내용**
- **탐색 latency ≈ 동일**: adaptive-k는 후처리라 reranking 양 불변 (`limit=min(5*max_num_episodes,200)` 풀·reranker 채점 수 그대로)
- **생성 단계 절감**: 반환 episode 수(`adaptive_kept`)만 줄어 → answer-LLM 프롬프트 토큰·latency ↓
- **recall vs k 트레이드오프**: 적게 남기면 토큰↓ 그러나 근거 누락 위험
- **expand_context 상호작용 주의**: 이웃 turn이 **동일 점수 상속** → 인접 점수가 평평해져 **gap(낙폭) 왜곡** 가능

**recall 낮을 때 처방**

| 증상 | 처방 |
|---|---|
| 대부분 `adaptive_kept=1~2`로 잘림 | `--adaptive-bias 1.0`(→1.5, 2.0)로 공격성 완화 |
| aggregation/multi-hop만 recall 낮음 | `--adaptive-min-k`를 근거 수만큼 ↑ (가장 확실한 하한) |
| 한두 질문만 과소 회수 | `--adaptive-min-k 2~3`로 전역 하한만 살짝 |

**발표 노트**
가장 자주 오해하는 지점입니다 — adaptive-k는 retrieve 연산을 줄이지 않습니다. embed·vector search·contextualize·rerank는 이미 다 끝난 뒤에 prefix만 자르므로 탐색 latency는 사실상 동일합니다. 절감은 전적으로 downstream, 즉 answer-LLM 프롬프트 크기에서 발생합니다. 튜닝은 recall이 급하면 `min_k`로 하드 floor를 깔고, 토큰을 줄이며 모양만 다듬으려면 bias를 0.5→2.0으로 sweep합니다. 주의할 점은 `expand_context`로 추가된 이웃 turn이 동일 점수를 상속하면 인접 점수가 평평해져 gap 신호가 왜곡될 수 있다는 것입니다.

---

## Slide 13 — 한계 & 향후

**내용**
- 현재 구현은 **largest-gap + 한 줄 position weight**까지 (clustering 없음)
- 향후 확장 여지:
  - **진짜 CAR 구현**: clustering(K-Means/DBSCAN/HDBSCAN) + silhouette 기반 경계 탐지
  - **풀 자체를 줄이는 변형**: 지금은 후처리라 탐색 비용 불변 → vector search/reranker 입력 단계에서 컷해 **탐색까지 빠르게**
- 운영 제약 (적용 전 점검):
  - **reranker 필요**: 점수 방향이 "높을수록 관련"이어야 gap 방향이 맞음 (raw euclidean distance는 부적합)
  - **작은 풀**은 자를 게 없음 → 넉넉한 `--top-k`
  - **flat 점수** → gap 신호 약함 → `adaptive_k_min`으로 떨어짐

**발표 노트**
현재는 의도적으로 가장 단순한 형태(largest-gap + 단조 position weight)에 머물러 있습니다. 자연스러운 다음 단계는 CAR을 실제로 구현하는 것 — clustering과 silhouette로 경계를 찾는 방식 — 이지만 비용 대비 효과는 검증이 필요합니다. 또 하나는 후처리가 아니라 vector search나 reranker 입력 단계에서 풀 자체를 줄여 탐색 연산까지 절감하는 변형입니다. 운영상으로는 reranker(또는 cosine/dot embedder)가 필수이며, 풀이 너무 작거나 점수가 평평하면 효과가 약하다는 점을 적용 전에 확인해야 합니다.

---

## Slide 14 — 참고문헌

**내용**

> **[1]** Chihiro Taguchi, Seiji Maekawa, Nikita Bhutani (Megagon Labs).
> *Efficient Context Selection for Long-Context QA: No Tuning, No Iteration, Just Adaptive-k.*
> EMNLP 2025 (Main). **arXiv:2506.08479** (submitted 2025-06-10).
> Code: https://github.com/megagonlabs/adaptive-k-retrieval — **BSD-3-Clause**.
> 핵심 결과: full-context 대비 최대 10× 적은 토큰으로 관련 passage의 ~70% 회수.

> **[2]** Yifan Xu, Vipul Gupta, Rohit Aggarwal, Varsha Mahadevan, Bhaskar Krishnamachari (Coinbase).
> *Cluster-based Adaptive Retrieval: Dynamic Context Selection for RAG Applications.*
> **arXiv:2511.14769**, 2025. **공개 코드 없음**.
> 보고 수치: LLM token -60%, latency -22%, hallucination -10%, Coinbase 배포 후 user engagement +200% (CDP 코퍼스 + MultiHop-RAG 벤치마크).

- 인용 메모: [1]의 본제목은 "Efficient Context Selection for Long-Context QA", 부제가 "No Tuning, No Iteration, Just Adaptive-k". [2]는 arXiv 식별자 `2511`이 2025년 11월 접수를 뜻하므로 연도는 **2025**로 표기.

**구현 소스 (branch `v0.3.9_msr`)**
- `packages/server/src/memmachine_server/retrieval_agent/common/agent_api.py` — `adaptive_k_cutoff`, `QueryParam`
- `packages/server/src/memmachine_server/retrieval_agent/agents/memmachine_retriever.py` — `_apply_adaptive_k`, `do_query`
- data flow: `episodic_memory.py`(`query_memory`), `declarative_memory.py`(`search_scored`, `_unify_scored_anchored_episode_contexts`)
- docs: `docs/msr/adaptive_k_retrieval.md`(사용 가이드), `docs/msr/adaptive_k_cut_criterion_report.md`(pre/post-bias 리포트)

**발표 노트**
인용 시 두 가지를 정확히 하세요. [1]의 정식 본제목은 "Efficient Context Selection for Long-Context QA"이고 "No Tuning, No Iteration, Just Adaptive-k"는 부제입니다. 코드는 Megagon Labs가 BSD-3-Clause로 공개했습니다. [2] CAR은 Coinbase 연구로 저자가 확인됐으나 공개 코드는 없으며, arXiv 식별자가 2511로 시작하므로 접수 연도는 2025년으로 표기합니다. CAR의 -60%/-22%/-10% 수치는 논문 abstract에서 확인된 값입니다.
