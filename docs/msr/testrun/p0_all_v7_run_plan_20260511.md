# p0_all_v7 진행 계획 (#4 → #6/#12 → #3)

- 작성일: 2026-05-11
- 브랜치: `eval_claude`
- 대상 ingest: `eval_tool_longmemeval_p0_all_v7` (500문항, chunk=on, 2026-05-07 완료)
- 목적: 이미 완료된 ingest 를 재사용하여 LongMemEval 기반 문제 #4 → #6/#12 → #3 을 순차 수행한다.

---

## 0. 사전 사실관계 (확정)

| 항목 | 값 | 근거 |
|------|-----|------|
| `session_id` | `eval_tool_longmemeval_p0_all_v7` | `results/p0_all_v7/ingest.jsonl`, `scripts/stages/_common.py:107` |
| `length` | 500 | `configs/runs/p0_all_v7.yaml` |
| `message_sentence_chunking` | `true` (ingest-locked) | yaml + `configs/generated/p0_all_v7_configuration.yml` |
| `prepend_user_prefix` | `false` (retrieve-time 변수) | yaml |
| `answer_prompt` | `LME_origin_cot_prompt` | yaml |
| `exclude_abstention` | `true` | yaml |
| judge LLM | Qwen3.5-397B (생성기와 동일, self-judge) | configuration.yml |
| ingest 종료 | 2026-05-07 18:08 UTC (5h11m) | ingest.jsonl |

**해석 주의**
- self-judge 환경이므로 논문 baseline (GPT-4o judge, ~0.92) 과의 **절대값 비교는 부적절**.
- 본 run 의 의의는 **변수 효과 측정** (k 비단조성, prefix on/off, MS 분해, Pareto).

---

## 1. 진행 순서 개요

| 순서 | 문제 | 산출물 | 재ingest |
|------|------|--------|----------|
| 1 | **#4 k sweep** {10,20,30,50,100} | `results/p0_all_v7/` (cell 5개) | ❌ |
| 2 | **#6 MS 분해** (#4 후처리) | `results/p6_from_v7/` (analyze-only) | ❌ |
| 3 | **#12 k Pareto** (#4 후처리) | `results/p12_from_v7/` (analyze-only) | ❌ |
| 4 | **#3 prefix on/off** | `results/p0_all_v7/` (재사용, #4 결과 백업 후) | ❌ |

`session_id` 가 `run_name` 에서 결정되므로 (`scripts/stages/_common.py:107`), **#4 / #3 은 모두 `run_name: p0_all_v7` 을 유지**해야 ingest 데이터를 재활용할 수 있다.
→ #4 → #3 전환 시 `results/p0_all_v7/` 디렉토리를 백업해야 한다 (충돌 회피).

---

## 2. Step 1 — #4 k sweep

### 2.1 `configs/runs/p0_all_v7.yaml` 수정 diff

```diff
 problem: 0
 description: LongMemEval 500 — k sweep {10,20,30,50,100} (chunk=on, prefix=off)
 ...
 sweep:
   search_limit:
-  - 50
+  - 10
+  - 20
+  - 30
+  - 50
+  - 100
 fixed:
   prepend_user_prefix: false
   message_sentence_chunking: true
   test_target: memmachine
```

> `description` 의 기존 "prefix=on" 표기는 사실(`prepend_user_prefix: false`)과 어긋났던 것이라 "prefix=off" 로 정정.

### 2.2 실행

```sh
python scripts/run_pipeline.py \
  --config configs/runs/p0_all_v7.yaml \
  --stage retrieve,generate,judge,analyze
```

### 2.3 검증 포인트

- 콘솔 로그: `[pipeline] run_name=p0_all_v7 stages=[retrieve, generate, judge, analyze]`
- 콘솔 로그: `[judge] longmemeval_answer_prompt=LME_origin_cot_prompt longmemeval_yesno_policy=lenient` (정책 명시)
- 산출 디렉토리:
  ```
  results/p0_all_v7/
    retrieve.jsonl     (cell 5개 × 500문항)
    generate.jsonl
    judge.jsonl        (llm_raw_reply 포함)
    analyze.json       (cell별 overall + per-category)
  ```
- 정합성 점검:
  ```sh
  jq '.cells | length' results/p0_all_v7/analyze.json   # 5
  jq '.cells | map(.params.search_limit)' results/p0_all_v7/analyze.json  # [10,20,30,50,100]
  ```

---

## 3. Step 2 — #6 multi-session 분해

### 3.1 신규 yaml: `configs/runs/p6_from_v7.yaml`

```yaml
results_dir: results
prompts_dir: prompts
configuration:
  mode: profile
  model_profile: my_model
  db_profile: my_db
  generated_dir: configs/generated
  generated_path: /mnt/nvme0n1/tj/Workspace/eval_mm/MemMachine/configs/generated/p0_all_v7_configuration.yml
judge:
  llm_model_id: null
evaluation:
  exclude_abstention: true
  ingest_concurrency: 1
  search_concurrency: 1
  judge_concurrency: 1
  longmemeval:
    answer_prompt: LME_origin_cot_prompt
n_runs: 1
problem: 6
description: "#6 multi-session 분해 (#4 결과 후처리)"
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_s_cleaned
  data_path: /mnt/nvme0n1/tj/Workspace/eval_mm/MemMachine/evaluation/data/longmemeval_s_cleaned.json
sweep: {}
fixed:
  prepend_user_prefix: false
  message_sentence_chunking: true
  test_target: memmachine
metrics:
  - per_session_count_distribution
  - accuracy_by_session_bucket
run_name: p6_from_v7
reuse_run: p0_all_v7
```

### 3.2 실행

```sh
python scripts/run_pipeline.py --config configs/runs/p6_from_v7.yaml
# reuse_run 이 있으면 자동으로 --stage analyze 로 제한됨 (run_pipeline.py:82-90)
```

### 3.3 검증 포인트

- 로그: `[pipeline] reuse_run='p0_all_v7' detected -> ... analyze`
- 산출: `results/p6_from_v7/analyze.json` (세션 버킷별 정확도)

---

## 4. Step 3 — #12 k Pareto

### 4.1 신규 yaml: `configs/runs/p12_from_v7.yaml`

위 #6 yaml 에서 `problem`, `description`, `metrics`, `run_name` 만 변경:

```yaml
problem: 12
description: "#12 k vs accuracy/tokens Pareto (#4 결과 후처리)"
metrics:
  - accuracy_vs_k
  - tokens_vs_k
  - pareto_front
run_name: p12_from_v7
reuse_run: p0_all_v7
```

(나머지 필드는 #6 와 동일하게 복사)

### 4.2 실행 / 검증

```sh
python scripts/run_pipeline.py --config configs/runs/p12_from_v7.yaml
```

- 산출: `results/p12_from_v7/analyze.json` (k별 (acc, token) Pareto)

---

## 5. Step 4 — #3 prefix on/off

> **선결 조건**: #4 결과 보존을 위해 `results/p0_all_v7/` 디렉토리 백업.

### 5.1 #4 산출물 백업

```sh
mv results/p0_all_v7 results/p0_all_v7__p4_ksweep
```

이후 #6/#12 도 같은 결과를 다시 참조해야 하므로 `reuse_run` 값을 `p0_all_v7__p4_ksweep` 로 갱신하거나, 심볼릭 링크로 호환성을 유지:
```sh
ln -s p0_all_v7__p4_ksweep results/p0_all_v7
```
(symlink 권장 — #6/#12 yaml 변경 없음)

### 5.2 `configs/runs/p0_all_v7.yaml` 추가 수정 diff

```diff
 problem: 0
-description: LongMemEval 500 — k sweep {10,20,30,50,100} (chunk=on, prefix=off)
+description: LongMemEval 500 — prefix on/off (chunk=on, k=50 고정)
 ...
 sweep:
   search_limit:
-  - 10
-  - 20
-  - 30
-  - 50
-  - 100
+  - 50
+  prepend_user_prefix:
+  - false
+  - true
 fixed:
-  prepend_user_prefix: false
   message_sentence_chunking: true
   test_target: memmachine
```

> `prepend_user_prefix` 를 `fixed` 에서 빼고 `sweep` 으로 옮긴다. `scripts/stages/retrieve.py:91-94` 가 cell 별로 `evaluation.longmemeval.prepend_user_prefix` 를 갱신.

### 5.3 실행

심볼릭 링크가 있으면 retrieve 가 기존 결과를 덮어쓰지 않도록 먼저 정리:

```sh
rm results/p0_all_v7   # symlink 만 제거 (실데이터는 results/p0_all_v7__p4_ksweep 에 보존됨)

python scripts/run_pipeline.py \
  --config configs/runs/p0_all_v7.yaml \
  --stage retrieve,generate,judge,analyze
```

### 5.4 검증 포인트

- 산출: `results/p0_all_v7/analyze.json` (cell 2개: prefix off / on)
- 끝나면 `results/p0_all_v7` 를 `results/p0_all_v7__p3_prefix` 로 rename:
  ```sh
  mv results/p0_all_v7 results/p0_all_v7__p3_prefix
  ln -s p0_all_v7__p4_ksweep results/p0_all_v7   # #6/#12 reuse 기본 경로 복원
  ```

---

## 6. 최종 파일/디렉토리 레이아웃

```
configs/runs/
  p0_all_v7.yaml                # 현재 활성 실험 yaml (계속 재사용)
  p6_from_v7.yaml
  p12_from_v7.yaml

results/
  p0_all_v7              -> p0_all_v7__p4_ksweep   (symlink, reuse_run 기본)
  p0_all_v7__p4_ksweep/  # #4 산출
  p0_all_v7__p3_prefix/  # #3 산출
  p6_from_v7/            # #6 분석
  p12_from_v7/           # #12 분석
```

---

## 7. 체크리스트

- [ ] Step 1: `p0_all_v7.yaml` sweep 확장 + retrieve~analyze 실행 → `analyze.json` cell 5개 확인
- [ ] Step 2: `p6_from_v7.yaml` 작성 + analyze 실행
- [ ] Step 3: `p12_from_v7.yaml` 작성 + analyze 실행
- [ ] Step 4-a: `results/p0_all_v7` 백업 + symlink
- [ ] Step 4-b: yaml prefix sweep 으로 수정 + retrieve~analyze 실행
- [ ] Step 4-c: 결과 rename + symlink 복원
- [ ] judge 로그에 `longmemeval_answer_prompt=LME_origin_cot_prompt` 기록 확인
- [ ] self-judge 한계 명시한 보고서 작성 (논문 절대값 비교 금지)

---

## 8. 회피해야 할 함정

1. **`run_name` 변경 금지** — 변경 시 `session_id` 가 달라져 retrieve 가 빈 결과. (`scripts/stages/_common.py:107`)
2. **결과 디렉토리 덮어쓰기** — 동일 `run_name` 으로 retrieve 재실행 시 `results/p0_all_v7/` 가 덮어써짐. 단계 전환 시 반드시 백업.
3. **`message_sentence_chunking` 을 sweep 에 두지 말 것** — `scripts/stages/retrieve.py:32` 에서 ingest-affecting key 로 차단됨 (SystemExit).
4. **judge 모델 인지** — 본 run 은 self-judge (Qwen3.5-397B). 분석 보고서에 항상 명시.
