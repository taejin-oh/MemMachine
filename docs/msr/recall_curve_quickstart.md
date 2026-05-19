# Recall@k 곡선 — 가이드

`retrieve.jsonl` 의 chunks_text 를 1 개, 2 개, ..., N 개 (= 한 row 의
chunk 수) 까지 잘라가며 supporting_facts recall 을 측정하고 선형 그래프
로 그린다.

스크립트 2 개:

| 스크립트 | 역할 |
|---|---|
| `scripts/recall_curve.py` | retrieve.jsonl → recall@k JSON |
| `scripts/plot_recall_curve.py` | JSON → PNG |

## 0. 사전 준비

- `uv sync` 가 끝나 있어 matplotlib 가 설치되어 있어야 한다 (`dev` 그룹).
- 분석 대상 `retrieve.jsonl` 이 있어야 한다. 보통 두 가지 출처:
  - 실제 시스템 풀 런 (`results/<baseline>/retrieve.jsonl`) — top-k = 그 런의
    search_limit (예: 50).
  - 오라클 데이터 (`scripts/build_oracle_retrieve.py` 출력) — top-k 가
    문항 별로 가변 (정답 세션 turn 수).

## 1. recall_curve.py — JSON 추출

```bash
uv run python scripts/recall_curve.py \
    --retrieve results/<my_run>/retrieve.jsonl \
    --out      results/<my_run>/recall_curve.json
```

각 row 별로:
- supporting_facts 의 각 fact 를 `_split_chunks` (3000 자 단위) 로 쪼개서
  piece → fact 인덱스 매핑 만듦
- chunks_text 의 line 을 **앞에서부터 순서대로** 훑으며 piece 가 hit 될
  때 그 piece 가 속한 fact 를 "회수됨" 으로 표시
- recall@k = (k 개 chunk 까지 봤을 때 회수된 fact 수) / (총 fact 수)
- 한 긴 fact 가 여러 piece 로 split 됐다면 piece 하나만 잡혀도 그 fact
  는 회수된 것으로 카운트 (Edwin 의 turn-level recall 과 동일 의미론).
- N = 해당 row 의 chunk 수 (`num_episodes_retrieved` 와 동일)

매칭은 `json.loads()` 한 본문에 대해 화이트스페이스 정규화 후 **정확
일치** — `fact_hits` 의 substring heuristic 은 쓰지 않는다 (앞선
filter_full_recall 와 같은 정책).

**X 축 범위** = 모든 row 의 N 의 최댓값. top-k=50 으로 retrieve 한 정상
런이라면 자연스럽게 `max_k=50`. 오라클의 경우 가변 → row 별 N 의 max
까지 (어떤 row 가 80 개 chunk 면 그 row 가 max_k 결정).

row 가 N 보다 적은 chunk 만 가진 경우 그 row 의 recall@k (k>N) 은
recall@N 으로 plateau 처리되어 평균 계산에 반영된다.

abstention 등 supporting_facts 가 비어있는 row 는 스킵
(`skipped_empty_supporting_facts` 카운트).

**옵션**:
- `--include-categories <comma>` — 카테고리 필터 (예:
  `temporal-reasoning,multi-session`)
- `--max-k <int>` — k 상한 설정. 미지정 시 row 별 N 의 max 자동 사용.

**출력 JSON** 구조:
```json
{
  "retrieve": "...",
  "max_k": 50,
  "n_rows": 479,
  "skipped_empty_supporting_facts": 21,
  "overall": [r1, r2, ..., r50],
  "by_category": {"single-session-user": [...], ...},
  "counts": {
    "overall": 479,
    "by_category": {"single-session-user": 70, ...}
  }
}
```

stdout 도 overall recall@{1,5,10,max_k} 요약 출력.

## 2. plot_recall_curve.py — PNG 생성

```bash
# combined: OVERALL + 카테고리 6 개를 한 그래프
uv run python scripts/plot_recall_curve.py \
    --input results/<my_run>/recall_curve.json \
    --out   results/<my_run>/recall_curve.png

# combined + 카테고리별 PNG 6 개 추가
uv run python scripts/plot_recall_curve.py \
    --input results/<my_run>/recall_curve.json \
    --out   results/<my_run>/recall_curve.png \
    --per-category
```

`--per-category` 사용 시 추가로 생성되는 파일:

```
recall_curve.png                               # combined
recall_curve_single-session-user.png
recall_curve_single-session-assistant.png
recall_curve_single-session-preference.png
recall_curve_temporal-reasoning.png
recall_curve_knowledge-update.png
recall_curve_multi-session.png
```

각 per-category PNG 는 비교 컨텍스트로 OVERALL 을 같이 표시한다.
카테고리 색은 combined 와 동일 (`PLOT_CONFIG.category_order` 인덱스
기반 — palette 인덱스 안정).

**X 축**: 1 ~ JSON 의 `max_k` (= retrieve 의 실제 top-k). 별도 옵션
없음 — 새로 그리고 싶으면 `recall_curve.py --max-k <N>` 로 JSON 자체를
좁히면 됨.

**Y 축**: 0 ~ 1.05 (mean recall).

## 3. PLOT_CONFIG 수정

`scripts/plot_recall_curve.py` 의 상단 `PLOT_CONFIG` dict 에서 한 곳 만
손대면 모든 시각 요소 변경 가능:

| 키 | 설명 |
|---|---|
| `figsize`, `dpi` | 그림 크기 / 해상도 |
| `overall_color`, `overall_linewidth` | OVERALL 선 색 / 두께 |
| `category_linewidth` | 카테고리 선 두께 |
| `category_palette` | 카테고리 색 (순서대로 사용) |
| `category_order` | 카테고리 정렬 순서 (= 색 매핑 인덱스) |
| `title`, `xlabel`, `ylabel` | 라벨 |
| `y_lim`, `y_grid` | Y 축 범위 / 그리드 |
| `*_fontsize` | 폰트 크기 |

색상이나 두께를 바꾼 뒤 `plot_recall_curve.py` 만 다시 돌리면 (JSON
재생성 불필요) PNG 새로 나옴.

## 4. 트러블슈팅

- **`max_k` 가 예상보다 큼 (예: top-50 retrieve 인데 84 나옴)**: 입력
  retrieve.jsonl 이 오라클 출력 (variable chunks per row) 일 가능성.
  일반 retrieve 인지 한 row 의 `num_episodes_retrieved` 직접 확인. 또는
  `recall_curve.py --max-k 50` 으로 상한 명시.
- **OVERALL 이 너무 빠르게 1.0 에 도달**: 입력이 오라클일 가능성 (정답
  chunk 만 있어서 추수 1~3 회 만에 다 회수). 일반 retrieve 라면 자연
  스러움.
- **카테고리 라인 중 하나만 다른 곡선**: 그 카테고리에 fact 가 길어
  여러 piece 로 split 되었을 가능성. piece 단위 매칭이라 piece 중
  일부만 회수돼도 부분 recall 로 누적됨.
- **그래프가 비어있음**: `n_rows=0`. supporting_facts 가 모두 비었거나
  `--include-categories` 가 너무 좁음. stdout 의 `skipped_empty_*` 카운트
  확인.
- **matplotlib 없음**: `uv sync` 한 번 다시 돌려서 `dev` 그룹의 새 의존성
  반영. `uv run python -c "import matplotlib; print(matplotlib.__version__)"`
  로 확인.

## 5. 파일 위치 요약

| 항목 | 경로 |
|---|---|
| 추출 스크립트 | `scripts/recall_curve.py` |
| 시각화 스크립트 | `scripts/plot_recall_curve.py` |
| JSON | `results/<run>/recall_curve.json` |
| Combined PNG | `results/<run>/recall_curve.png` |
| Per-category PNG | `results/<run>/recall_curve_<cat>.png` |
