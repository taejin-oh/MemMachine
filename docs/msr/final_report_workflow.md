# Final Report — 6 조건 × 2 Subset 비교 워크플로

LongMemEval 위에서 **6 조건** 의 정확도를 **2 subset** 에서 비교한다.

**6 조건**:
| # | 코드명 | 설명 |
|---|---|---|
| 1 | `oracle_full` | Oracle has_answer T+F (정답 세션 전체 turn) |
| 2 | `oracle_facts` | Oracle has_answer=True 만 |
| 3 | `normal` | 실제 시스템 retrieve (search_limit=50) |
| 4 | `pos_front` | normal 의 supporting_facts 를 chunks_text 맨 앞으로 |
| 5 | `pos_middle` | 중간 |
| 6 | `pos_end` | 맨 뒤 |

**2 subset**:
- **Subset A** — normal 에서 실패 (`llm_score=0`) **AND** supporting_facts 가
  chunks_text 에 100% 들어있는 turn 만. 이 표본은 "retrieval 책임이 아닌
  answer LLM 한계" 가설을 테스트하는 데 쓰임.
- **Subset B** — 500 문항 전부.

각 subset 에서 6 조건 × answer LLM 호출 → judge → summarize → 비교. 결과
표는 12 셀 (= 6 × 2). 새 LLM 호출은 11 회 — B_normal 슬롯은 베이스라인
런을 그대로 재활용. compare_runs.py 가 N-run 한 표로 묶어줌.

---

## 0. 사전 준비

기존 가이드 ([`longmemeval_temporal_reasoning_quickstart.md`](longmemeval_temporal_reasoning_quickstart.md))
의 0~5 단계로 환경/DB/API 키 세팅 + 500-Q 베이스라인 풀 런 완료. 베이스라인
런은 search_limit=50 으로:

```bash
uv run python scripts/generate_config.py \
    --problem 0 \
    --run-name sclean_top50 \
    --model-profile main --db-profile main \
    --longmemeval-answer-prompt LME_origin_prompt \
    --k-list 50

uv run python scripts/run_pipeline.py --config configs/runs/sclean_top50.yaml
```

이 후 `results/sclean_top50/{retrieve,generate,judge}.jsonl + analyze.json`
가 존재한다고 가정.

오라클 데이터셋 (`evaluation/data/longmemeval_oracle.json`) 도
[`oracle_ceiling_quickstart.md`](oracle_ceiling_quickstart.md) 의 절차로
다운로드.

본 문서에서 `<baseline>` = `sclean_top50` 으로 표기하니, 다른 이름이면
치환.

---

## 1. Subset A 정의

normal 실패 + supporting_facts 100% 회수된 row 만:

```bash
uv run python scripts/filter_judge_failed.py \
    --retrieve results/<baseline>/retrieve.jsonl \
    --out      results/<baseline>/retrieve.failed.jsonl

uv run python scripts/filter_full_recall.py \
    --retrieve results/<baseline>/retrieve.failed.jsonl \
    --out      results/subset_a/retrieve.jsonl
```

`results/subset_a/retrieve.jsonl` 이 **Subset A 의 정의**다 — 이 JSONL 의
question_id 집합 = S_A.

---

## 2. Subset A 의 6 조건 retrieve.jsonl 빌드

| # | 조건 | retrieve.jsonl 빌드 |
|---|---|---|
| 1 | A_oracle_full | `build_oracle_retrieve.py --include-qids-from results/subset_a/retrieve.jsonl --out results/A_oracle_full/retrieve.jsonl` |
| 2 | A_oracle_facts | 같은 명령에 `--facts-only` 추가, `--out results/A_oracle_facts/retrieve.jsonl` |
| 3 | A_normal | `cp results/subset_a/retrieve.jsonl results/A_normal/retrieve.jsonl` (이미 보유 — 단 비결정성 측정을 위해 별 dir 로 복사) |
| 4–6 | A_pos_* | `permute_facts_position.py --retrieve results/subset_a/retrieve.jsonl --out-dir /tmp/A_pos` → `cp -r /tmp/A_pos/front results/A_pos_front; ...middle ...end` |

명령 묶음:

```bash
# 1, 2: 오라클 조건들 (qid 필터)
uv run python scripts/build_oracle_retrieve.py \
    --include-qids-from results/subset_a/retrieve.jsonl \
    --out results/A_oracle_full/retrieve.jsonl

uv run python scripts/build_oracle_retrieve.py --facts-only \
    --include-qids-from results/subset_a/retrieve.jsonl \
    --out results/A_oracle_facts/retrieve.jsonl

# 3: 그대로 사용 (비결정성 재측정용으로 별 dir 로)
mkdir -p results/A_normal
cp results/subset_a/retrieve.jsonl results/A_normal/retrieve.jsonl

# 4-6: front / middle / end
uv run python scripts/permute_facts_position.py \
    --retrieve results/subset_a/retrieve.jsonl \
    --out-dir  results/_A_pos_tmp
for pos in front middle end; do
    mkdir -p results/A_pos_$pos
    mv results/_A_pos_tmp/$pos/retrieve.jsonl results/A_pos_$pos/retrieve.jsonl
done
rm -rf results/_A_pos_tmp
```

---

## 3. Subset B (전체 500) 의 6 조건 retrieve.jsonl 빌드

```bash
# 1, 2: 풀 500 오라클
uv run python scripts/build_oracle_retrieve.py \
    --out results/B_oracle_full/retrieve.jsonl
uv run python scripts/build_oracle_retrieve.py --facts-only \
    --out results/B_oracle_facts/retrieve.jsonl

# 3: 기존 베이스라인 — 별도 dir 로 복사하지 않아도 됨, sclean_top50 그대로 씀
#    (단, 별 dir 가 필요하면 cp 사용)

# 4-6: front / middle / end (전체 500 에 대해)
uv run python scripts/permute_facts_position.py \
    --retrieve results/<baseline>/retrieve.jsonl \
    --out-dir  results/_B_pos_tmp
for pos in front middle end; do
    mkdir -p results/B_pos_$pos
    mv results/_B_pos_tmp/$pos/retrieve.jsonl results/B_pos_$pos/retrieve.jsonl
done
rm -rf results/_B_pos_tmp
```

---

## 4. 각 조건마다 generate → judge

11 셀 (B_normal 제외) 동일 패턴. 모델/프롬프트 정책은 베이스라인과 똑같이.

```bash
# 조건별 run config 한 번씩 생성
for cond in A_oracle_full A_oracle_facts A_normal \
            A_pos_front A_pos_middle A_pos_end \
            B_oracle_full B_oracle_facts \
            B_pos_front B_pos_middle B_pos_end; do
    uv run python scripts/generate_config.py \
        --problem 0 --run-name "$cond" \
        --model-profile main --db-profile main \
        --longmemeval-answer-prompt LME_origin_prompt
done

# answer LLM + judge + analyze — 11 셀 (B_normal 은 sclean_top50 가 이미 가짐)
for cond in A_oracle_full A_oracle_facts A_normal \
            A_pos_front A_pos_middle A_pos_end \
            B_oracle_full B_oracle_facts \
            B_pos_front B_pos_middle B_pos_end; do
    uv run python scripts/regen_answer.py --run "$cond"
    uv run python scripts/run_pipeline.py \
        --config "configs/runs/$cond.yaml" --stage judge,analyze
done
```

> B_normal 은 `results/<baseline>/` 가 이미 generate+judge+analyze 를 가짐.
> 새로 regen 안 해도 비교에 그대로 쓸 수 있음.

---

## 5. 결과 비교

### Subset A — 6 조건 한 표로

```bash
uv run python scripts/compare_runs.py \
    --runs results/A_oracle_full results/A_oracle_facts results/A_normal \
           results/A_pos_front  results/A_pos_middle   results/A_pos_end \
    --labels "Oracle T+F" "Oracle T only" "Normal" \
             "Front" "Middle" "End" \
    --baseline 2 \
    --out results/A_compare.json
```

`--baseline 2` = `A_normal` 기준으로 Δ. Δ 가 양수면 그 조건이 normal 보다
잘 푼 것 — 즉 "retrieval 은 맞췄지만 LLM 이 못 푼" 표본에서도 다른 입력
형태로 주면 더 푼다는 신호.

### Subset B — 6 조건 한 표로

```bash
uv run python scripts/compare_runs.py \
    --runs results/B_oracle_full results/B_oracle_facts results/<baseline> \
           results/B_pos_front  results/B_pos_middle   results/B_pos_end \
    --labels "Oracle T+F" "Oracle T only" "Normal" \
             "Front" "Middle" "End" \
    --baseline 2 \
    --out results/B_compare.json
```

> `B_normal` 슬롯에 베이스라인 디렉토리 `results/<baseline>` 를 그대로
> 가리킴.

### 단일 셀 디테일

특정 조건의 카테고리별 분포를 더 깊이 보려면:

```bash
uv run python scripts/summarize_run.py \
    --judge results/A_oracle_full/judge.jsonl \
    --out   results/A_oracle_full/summary.json
```

---

## 6. 해석 가이드

**Subset A** 핵심 질문: "retrieval 은 fact 를 다 줬는데 LLM 이 못 맞춘"
표본에서, 입력 형태를 바꾸면 풀리는가?

- `Oracle T+F` ≫ `Normal` → normal 의 chunks_text 에 noise 가 많아 LLM 이
  답을 못 추출함. distractor 제거하니 잘 됨.
- `Oracle T only` ≈ `Oracle T+F` → 컨텍스트 turn 없어도 LLM 이 답 가능.
  반대로 ≪ 이면 컨텍스트 turn 이 필요한 케이스.
- `Front` > `Middle/End` → lost-in-the-middle. fact 위치만 바꿔도 정확도
  변동 ⇒ 답을 못 찾는 게 아니라 못 "보는" 케이스.

**Subset B** 핵심 질문: 전체 500 문항 에서 각 조건의 절대 정확도.

- `Oracle T+F` = retrieval ceiling. 시스템이 100% recall 일 때 LLM 이
  도달할 수 있는 상한.
- `Normal` 대비 갭 = retrieval 의 평균 손실분.
- `Pos_*` 비교 = position 효과 (lost-in-the-middle 등).

**카테고리별** 표는 같은 표 안에 있으니 어디 condition × category 에서
이상치가 크게 발생하는지 본다 (예: `temporal-reasoning` 만 facts-only 에서
크게 떨어지면 → 시간 추론은 컨텍스트 의존도가 높다는 신호).

---

## 7. 트러블슈팅

- **`A_*` 의 row 수가 너무 작다 (< 50)**: Subset A 자체가 작음. 베이스라인
  의 실패 + 100% recall 표본 자체가 작아서 통계 신뢰도가 낮을 수 있음.
  카테고리별 결합을 고려.
- **`Oracle T+F` 가 100% 안 나옴**: answer LLM 이 정답 세션을 다 봤는데도
  못 푼다는 뜻. LLM 한계 또는 judge noise. judge_raw_response 를 sample
  몇 개 직접 확인.
- **`Pos_*` 모두 비슷**: position 효과가 작거나, fact 가 너무 짧아 위치
  영향이 미미. `--no-inject-missing` 으로 끄고 다시 보거나, facts 가
  많은 카테고리 (`multi-session`, `temporal-reasoning`) 로 좁혀서 본다
  (`--include-categories`).
- **`generate_config.py` 가 매번 12 회 호출**: run_name 만 다르고 모델/프롬프트
  동일하니 한 번 만든 working configuration.yml 을 `--use-existing-config`
  로 재사용 가능.
- **compare_runs.py "analyze.json missing"**: 각 조건에 `--stage analyze` 가
  안 돌았음. step 4 의 `--stage judge,analyze` 가 둘 다 도는지 재확인.
  단일 셀만 빠르게 보고 싶으면 summarize_run.py 가 judge.jsonl 만 있어도
  동작.

---

## 8. 산출물 위치 요약

| 디렉토리 | 내용 |
|---|---|
| `results/<baseline>/` | 베이스라인 전체 — `retrieve,generate,judge.jsonl`, `analyze.json`, `retrieve.failed.jsonl` |
| `results/subset_a/` | Subset A 정의 (= filter_full_recall 출력) |
| `results/A_<cond>/` | A 의 6 조건 결과 |
| `results/B_<cond>/` | B 의 5 조건 결과 (B_normal 은 `<baseline>` 그대로) |
| `results/A_compare.json` / `B_compare.json` | 12 셀 비교 결과 |
