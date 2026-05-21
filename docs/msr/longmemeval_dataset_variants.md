# LongMemEval 데이터셋 변종 비교 (`s_cleaned` / `m_cleaned` / `oracle`)

xiaowu0162/longmemeval-cleaned 의 세 가지 파일 비교 — 같은 500 질문 / 같은
정답 / 같은 evidence 세션을 공유하되, **distractor 세션 수만 다름**.

## 파일 크기

| 파일 | 디스크 |
|---|---|
| `longmemeval_oracle.json` | 15 MB |
| `longmemeval_s_cleaned.json` | 265 MB |
| `longmemeval_m_cleaned.json` | **2.5 GB** (~10× of s) |

세 파일 모두 HuggingFace `xiaowu0162/longmemeval-cleaned` 에서 다운로드.

## 스키마 — 셋 다 동일

```
top-level keys:
  question_id, question_type, question, answer, question_date,
  answer_session_ids,
  haystack_session_ids, haystack_dates, haystack_sessions

turn keys:
  role, content (+ has_answer 표시)
```

`evaluation/longmemeval/{ingest,retrieve}.py` 의 `--in-file` 로 어느 파일이든
그대로 받음 — 코드 변경 없음.

## 질문 / 정답 / Evidence — 셋 다 완전 동일

| 항목 | `oracle` vs `s_cleaned` | `s_cleaned` vs `m_cleaned` |
|---|---|---|
| 질문 ID 집합 | ✓ 500=500 | ✓ 500=500 |
| `question` 본문 | ✓ 500/500 일치 | ✓ 500/500 일치 |
| `answer` | ✓ 500/500 일치 | ✓ 500/500 일치 |
| `question_type` | ✓ 동일 | ✓ 동일 |
| `answer_session_ids` | ✓ 500/500 일치 | ✓ 500/500 일치 |
| `has_answer=True` turn 본문 | ✓ 500/500 일치 | ✓ 500/500 일치 |
| Evidence 세션 (answer_session_ids 가 가리키는 세션) | ✓ byte-equal | ✓ byte-equal |
| 카테고리 분포 | ✓ 동일 (mu=133, temp=133, ku=78, ssu=70, ssa=56, ssp=30) | ✓ 동일 |

→ **세 변종의 차이는 distractor 세션 (정답에 안 들어가는 일반 대화) 수만**.
평가 결과 직접 비교 가능 (같은 질문/정답 위에서 retrieval 난이도만 다름).

## 크기 차이 — distractor 세션 수

| 메트릭 | `oracle` | `s_cleaned` | `m_cleaned` |
|---|---|---|---|
| Q당 **세션 수** (haystack_sessions) | 평균 1.9 (1–6) | 평균 **47.7** (38–62) | 평균 **475.3** (460–490) |
| Q당 **turn 수** | 평균 **21.9** (2–72) | 평균 **493.5** (396–616) | 평균 **4,894** (4586–5229) |
| Q당 has_answer=True turn | 평균 1.79 | 평균 1.79 | 평균 1.79 |
| 데이터셋 전체 turn 합계 | ~11k | 246,750 | **2,446,993** |
| 데이터셋 전체 has_answer turn | 896 | 896 | 896 |
| 정답 turn 비율 | ~8.1% | ~0.36% | **~0.037%** |

→ m 의 Q당 turn 은 s 의 약 **10×**. 정답 turn 비율은 **~1/10** 로 낮아짐 —
retrieval 시스템에 더 가혹.

## Distractor 풀은 부분집합 아님 ⚠️

```
s.haystack_session_ids ⊆ m.haystack_session_ids:  0/500
```

→ m 은 s 의 단순 확장본이 **아님**. 같은 evidence 세션을 공유하되, distractor
는 **별개 풀에서 샘플링**됨. 즉:
- `oracle`: evidence 세션만 (distractor 0)
- `s_cleaned`: evidence + 약 ~46 개 distractor 세션 (한 풀에서)
- `m_cleaned`: evidence + 약 ~473 개 distractor 세션 (다른 풀에서)

s 의 distractor 가 m 안에 그대로 들어 있지 않음 — 다른 대화들로 구성.
다만 evidence 세션은 byte-equal 하니 정답 찾기 task 자체는 동일.

## 평가 의미

| 데이터셋 | retrieval 난이도 | 적합한 측정 대상 |
|---|---|---|
| **`oracle`** | 매우 쉬움 (정답 turn 비율 8%, distractor 0) | **answer LLM ceiling** — "이상적 retrieval 일 때 LLM 한계" |
| **`s_cleaned`** | 표준 (정답 turn 비율 0.36%) | **LongMemEval 표준 baseline** (논문 비교 점수) |
| **`m_cleaned`** | 매우 어려움 (정답 turn 비율 0.04%) | **retrieval stress-test** — 큰 검색 공간 처리 능력 |

## 우리 `evaluation/longmemeval/` 에서

세 파일 모두 `--in-file` 로 그대로 사용 가능. 코드 변경 없음.

```bash
# 표준 평가
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_s_cleaned.json \
    ...

# Stress test
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_m_cleaned.json \
    ...

# Ceiling test
uv run python -m evaluation.longmemeval.ingest \
    --in-file evaluation/data/longmemeval_oracle.json \
    ...
```

### `m_cleaned` 적재 시 인프라 부담

s 대비 약 10×:
- **Ingest 시간**: ~10× (500 질문 × 4894 turn = ~245만 Episode 적재)
- **Neo4j 디스크**: ~10× (Episode 수 비례)
- **Embedder 비용**: 245만 임베딩 (sentence-transformer 로컬은 시간만 들지만 OpenAI 임베더 쓰면 ~10× API 비용)
- **per-question 격리는 그대로 유효**: session_id 가 prefix_qid 라 다른 질문 noise 안 섞임. 단 그 질문 자체의 검색 공간이 4894 turn 으로 ~10× 커짐.

### 권장 시나리오

| 상황 | 데이터셋 |
|---|---|
| 개발 / smoke / 디버깅 | `oracle` 또는 `s_cleaned --limit N` |
| 표준 평가 (논문 비교) | `s_cleaned` 풀 500 |
| Retrieval 스트레스 / 강한 시스템 측정 | `m_cleaned` 풀 500 |
| Answer LLM ceiling 측정 | `oracle` 풀 500 |

## 검증 방법

요약 통계 재계산:

```python
import json, statistics
data = json.load(open('evaluation/data/longmemeval_<variant>.json'))
sess = [len(s['haystack_sessions']) for s in data]
turn = [sum(len(s) for s in d['haystack_sessions']) for d in data]
ha = [sum(1 for s in d['haystack_sessions'] for t in s if t.get('has_answer'))
      for d in data]
print(f"samples={len(data)}, sessions/Q mean={statistics.mean(sess):.1f}, "
      f"turns/Q mean={statistics.mean(turn):.1f}, "
      f"has_answer/Q mean={statistics.mean(ha):.2f}")
```

`s` ↔ `m` 의 evidence 세션 byte-equal 확인:

```python
qid = next(iter({x['question_id'] for x in s_data} & {x['question_id'] for x in m_data}))
sq = next(x for x in s_data if x['question_id']==qid)
mq = next(x for x in m_data if x['question_id']==qid)
for asid in sq['answer_session_ids']:
    si = sq['haystack_session_ids'].index(asid)
    mi = mq['haystack_session_ids'].index(asid)
    assert sq['haystack_sessions'][si] == mq['haystack_sessions'][mi]
```

## 한 줄 결론

같은 질문 / 정답 / evidence 위에서 distractor 규모만 다른 3 변종.
oracle 은 ceiling 측정, s_cleaned 는 표준 평가, m_cleaned 는 stress test.
세 파일 모두 `evaluation/longmemeval/` 코드가 그대로 받음.
