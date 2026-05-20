# `evaluation/longmemeval/` — upstream-style per-question isolated retrieval

LongMemEval 표준 평가 방식. xiaowu0162/LongMemEval `src/retrieval/run_retrieval.py`
의 디자인을 그대로 옮긴 것:

- **각 질문 별로 corpus 를 매번 새로 build** (그 질문의 `haystack_sessions` 만)
- **In-memory dense retrieval** — 영구 DB 없음, 임베딩 인덱스도 매 질문마다 새로
- **No cross-question contamination** — 격리된 검색 공간이 LongMemEval 의 설계 의도

## 왜 따로 만들었나

본 브랜치의 `scripts/run_pipeline.py --stage ingest,retrieve` 경로 (=
`evaluation/retrieval_agent/longmemeval_test.py` 확장) 는 **모든 질문을 단일
session_id 에 적재** 하는 구조 — 검색 공간이 ~246k turn 인데 정답 turn 은
1~2 개라 recall 이 크게 떨어진다 (관측: ~50%). upstream 과 비교 가능한
숫자를 얻으려면 격리가 필요.

## 사용

```bash
uv sync --extra gpu          # sentence-transformers 설치 (BAAI/bge-base-en-v1.5 로컬 모델용)

uv run python -m evaluation.longmemeval.retrieve \
    --data-path evaluation/data/longmemeval_s_cleaned.json \
    --model BAAI/bge-base-en-v1.5 \
    --top-k 50 \
    --out results/lme_iso/retrieve.jsonl
```

옵션:
- `--model <hf-id>` — HuggingFace 모델 id. upstream 의 `flat-contriever` /
  `flat-stella` / `flat-gte` 와 호환 (`facebook/contriever`,
  `Alibaba-NLP/gte-Qwen2-7B-instruct` 등 swap 가능).
- `--top-k N` — 질문 당 회수할 turn 수 (default 50).
- `--include-categories <list>` — comma-separated 카테고리 필터.
- `--limit N` — 처음 N 개 질문만 (스모크).
- `--batch-size N` — 임베딩 batch (default 64).

## 출력

본 브랜치 `retrieve.jsonl` 스키마 그대로:
- `question`, `question_id`, `category`, `sweep={}`, `cell_idx=0`
- `chunks_text` — top-K 회수된 turn 을 `[<date> at <time>] <role>: "<content>"\n`
  로 직렬화 (역할은 `user`/`assistant` 보존)
- `supporting_facts` — has_answer=True turn 의 content list
- `num_episodes_retrieved`, `memory_retrieval_time`, `agent=lme_upstream` 등

→ 기존 분석 도구가 그대로 동작:

```bash
uv run python scripts/recall_curve.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/recall_curve.json

uv run python scripts/plot_recall_curve.py \
    --input results/lme_iso/recall_curve.json \
    --out   results/lme_iso/recall_curve.png \
    --per-category

uv run python scripts/analyze_sclean_recall.py \
    --retrieve results/lme_iso/retrieve.jsonl \
    --out      results/lme_iso/sclean_recall.json
```

이후 `scripts/regen_answer.py` + judge stage 로 정확도 평가까지 이어갈 수도 있음
(retrieve.jsonl 만 있으면 됨).

## 설계 메모

- **Corpus granularity = turn**. upstream 도 `--granularity turn|session` 선택지를
  주는데, 우리 분석 도구 (recall_curve.py 등) 가 piece-level (= turn-level)
  매칭이라 turn 단위가 자연. 필요하면 session 단위 옵션 추가 가능.
- **Timestamp** — session_date + (turn_idx 초) 로 합성. main 의
  `evaluation/episodic_memory/longmemeval_models.py` 규약과 동일.
- **Reranker 없음** — upstream 원본도 reranker 없이 dense retrieval 만. 이게
  의미 있는 베이스라인. reranker 영향을 보려면 별도 패스 필요.
- **답변 LLM / judge 호출 없음** — pure retrieval. 비용 0.

## 스모크 결과 예시

```
[lme] 1/2  qid=e47becba  corpus=550  ret=50  t=13.81s
[lme] 2/2  qid=118b2229  corpus=485  ret=50  t=11.75s

[recall_curve] n=2 rows  max_k=50  skipped_empty_sf=0
[recall_curve] overall recall@1=0.750  recall@5=0.750  recall@10=1.000  recall@50=1.000
```

2 문항 만으로 통계 의미는 없지만, 단일 session 적재 (`scripts/run_pipeline.py
--stage retrieve`) 와 동일 모델 / 동일 K 에서의 recall (~50%) 과 격차를 확인
가능. 풀 500 문항 돌리면 upstream 표준 수치와 비교 가능한 베이스라인 나옴.

## 성능 메모

- CPU 기준: 질문 1 개 = 평균 ~12 초 (550 turn 의 embedding + 검색).
- 500 문항: ~100 분 예상 (싱글 스레드 CPU).
- GPU / MPS 자동 활용 (sentence-transformers default).
- 임베딩 캐시 안 함 (질문 별 corpus 가 달라 캐시 의미 없음).
