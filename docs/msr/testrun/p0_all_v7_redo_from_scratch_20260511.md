# p0_all_v7 재실행 가이드 — 처음부터 (ingest 1회로 #4 → #6 → #12 → #3)

- 작성일: 2026-05-11
- 브랜치: `eval_claude`
- 작성 목적: 이전 ingest 가 소실된 상황에서 **단일 ingest** 를 1회 수행한 뒤
  LongMemEval 4개 문제(#4 / #6 / #12 / #3)를 그 ingest 만으로 모두 처리하기 위함.
- 실행 주체: 사용자 PC의 Claude Code. 이 문서를 위에서부터 순차적으로 따라 수행.
- 사전 가이드: `docs/msr/testrun/p0_all_v7_run_plan_20260511.md` (배경/근거)

> **이 문서의 단 하나의 규칙**
> `run_name` 은 처음부터 끝까지 **`p0_all_v7`** 으로 고정한다.
> `session_id` 가 `run_name` 에서 결정되므로(`scripts/stages/_common.py:107`),
> 변경 시 ingest 데이터를 못 찾는다.

---

## Step 0. 사전 점검 (필수, 약 1분)

### 0.1 작업 경로 / 브랜치

```sh
cd /mnt/nvme0n1/tj/Workspace/eval_mm/MemMachine    # 사용자 실제 경로로 조정 가능
git status
git rev-parse --abbrev-ref HEAD                    # eval_claude 이어야 함
git pull origin eval_claude
```

기대: `On branch eval_claude` / `nothing to commit`.

### 0.2 프로파일 / 데이터

```sh
test -f configs/profiles/models/my_model.yaml || echo "MISSING: configs/profiles/models/my_model.yaml"
test -f configs/profiles/dbs/my_db.yaml       || echo "MISSING: configs/profiles/dbs/my_db.yaml"
test -f evaluation/data/longmemeval_s_cleaned.json || echo "MISSING: evaluation/data/longmemeval_s_cleaned.json"
```

세 줄 모두 출력이 없어야 통과.
누락 시 직전 ingest 와 동일 셋업을 복원할 때까지 멈춘다 (사용자에게 보고).

### 0.3 DB 연결 (Neo4j / Postgres)

`configs/profiles/dbs/my_db.yaml` 의 포트를 확인하고 살아 있는지 점검.
기존 run 설정에서 사용한 포트는:

```sh
nc -zv localhost 57687     # Neo4j (bolt)
nc -zv localhost 55432     # Postgres
```

둘 다 `succeeded` 가 떠야 한다. 실패 시 사용자에게 보고하고 멈춘다.

### 0.4 기존 잔여물 정리 (조심)

> 이전 ingest 가 "날아갔다"는 상황 가정. DB 자체가 비어있는지 한 번만 확인.
> **여기서 임의로 DB를 비우거나 results/ 를 지우지 말 것.** 단,
> 이전 `results/p0_all_v7/` 디렉토리가 남아 있다면 다음 단계가 ingest 를
> skip 해버리므로 **rename 만** 한다:

```sh
if [ -d results/p0_all_v7 ] && [ ! -L results/p0_all_v7 ]; then
  mv results/p0_all_v7 results/p0_all_v7__stale_$(date +%Y%m%d_%H%M%S)
fi
```

(symlink 인 경우는 살려둔다. 일반 디렉토리만 rename.)

---

## Step 1. Run config 생성 + Ingest 1회 (∼5h)

> 이 단계의 산출물(DB 적재 + `results/p0_all_v7/ingest.jsonl`)은
> 이후 #4 / #6 / #12 / #3 모두에서 재사용된다.

### 1.1 fixed override JSON 작성

`--problem 4` 가 자동으로 적용하는 `configs/problems/p4.yaml` 의 기본값 중
사용자 의도와 다른 두 항목(`prepend_user_prefix`, `test_target`) 및 추가
평가 옵션을 한 곳에서 일괄 오버라이드한다. `--from-json` 경로를 통해야
`scripts/generate_config.py:476-496` 의 `_apply_fixed_to_configuration` 가
호출되어 run yaml 과 generated configuration.yml 양쪽이 정합 상태가 된다.

```sh
mkdir -p /tmp/p0_all_v7
cat > /tmp/p0_all_v7/overrides.json <<'JSON'
{
  "fixed": {
    "prepend_user_prefix": false,
    "message_sentence_chunking": true,
    "test_target": "memmachine"
  },
  "description": "LongMemEval 500 — k sweep {10,20,30,50,100} (chunk=on, prefix=off)",
  "evaluation": {
    "exclude_abstention": true,
    "ingest_concurrency": 1,
    "search_concurrency": 1,
    "judge_concurrency": 1
  }
}
JSON
```

### 1.2 run config 생성

```sh
python scripts/generate_config.py \
  --problem 4 \
  --run-name p0_all_v7 \
  --model-profile my_model \
  --db-profile my_db \
  --length 500 \
  --k-list 10,20,30,50,100 \
  --longmemeval-answer-prompt LME_origin_cot_prompt \
  --longmemeval-yesno-policy lenient \
  --from-json /tmp/p0_all_v7/overrides.json
```

산출:
- `configs/runs/p0_all_v7.yaml`
- `configs/generated/p0_all_v7_configuration.yml`

### 1.3 생성 결과 정합성 검증

```sh
python - <<'PY'
import yaml, pathlib, sys
run = yaml.safe_load(pathlib.Path("configs/runs/p0_all_v7.yaml").read_text())
cfg = yaml.safe_load(pathlib.Path("configs/generated/p0_all_v7_configuration.yml").read_text())

assert run["run_name"] == "p0_all_v7", run["run_name"]
assert run["benchmark"]["length"] == 500, run["benchmark"]["length"]
assert run["sweep"]["search_limit"] == [10, 20, 30, 50, 100], run["sweep"]["search_limit"]
assert run["fixed"]["message_sentence_chunking"] is True
assert run["fixed"]["prepend_user_prefix"] is False
assert run["fixed"]["test_target"] == "memmachine"
assert run["evaluation"]["longmemeval"]["answer_prompt"] == "LME_origin_cot_prompt"
assert run["evaluation"]["exclude_abstention"] is True

# configuration.yml propagation (the part that actually drives ingest/retrieve)
assert cfg["episodic_memory"]["long_term_memory"]["message_sentence_chunking"] is True, \
    "chunking did not propagate to configuration.yml"
assert cfg["evaluation"]["longmemeval"]["prepend_user_prefix"] is False, \
    "prefix did not propagate to configuration.yml"
print("[ok] run yaml + configuration.yml consistent")
PY
```

위 어서션 중 하나라도 실패하면 **여기서 멈추고 사용자에게 보고**.

### 1.4 Ingest 실행 (장시간)

```sh
python scripts/run_pipeline.py \
  --config configs/runs/p0_all_v7.yaml \
  --stage ingest 2>&1 | tee results/_log_p0_all_v7_ingest.log
```

예상 소요: 약 5시간 (이전 run 기준 5h11m, 500문항).
중간에 끊지 말 것. 끊겼으면 **DB 상태를 사용자에게 보고**하고 어떻게 진행할지 묻는다.

### 1.5 Ingest 완료 검증

```sh
test -f results/p0_all_v7/ingest.jsonl && cat results/p0_all_v7/ingest.jsonl
```

기대 출력 (예):
```json
{"status": "ok", "started_at": "...", "finished_at": "...",
 "session_id": "eval_tool_longmemeval_p0_all_v7",
 "benchmark": "longmemeval", "num_questions": 500}
```

검증:
- `status == "ok"`
- `session_id == "eval_tool_longmemeval_p0_all_v7"`
- `num_questions == 500`

하나라도 다르면 **여기서 멈추고 사용자에게 보고**.

(선택) DB 직접 확인:
```sh
# Neo4j 가 cypher-shell 로 접근 가능하면
echo 'MATCH (n) WHERE n.session_id = "eval_tool_longmemeval_p0_all_v7" RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC;' \
  | cypher-shell -a bolt://localhost:57687 -u neo4j -p neo4j_password
```

---

## Step 2. #4 — k sweep {10, 20, 30, 50, 100}

> Step 1 의 ingest 결과만 사용. 재ingest 없음.

### 2.1 실행 (retrieve → generate → judge → analyze)

```sh
python scripts/run_pipeline.py \
  --config configs/runs/p0_all_v7.yaml \
  --stage retrieve,generate,judge,analyze 2>&1 | tee results/_log_p0_all_v7_p4.log
```

### 2.2 검증

```sh
ls results/p0_all_v7/
# 기대: ingest.jsonl  retrieve.jsonl  generate.jsonl  judge.jsonl  analyze.json

python - <<'PY'
import json, pathlib
d = json.loads(pathlib.Path("results/p0_all_v7/analyze.json").read_text())
cells = d.get("cells", [])
ks = sorted({c["params"]["search_limit"] for c in cells})
assert ks == [10, 20, 30, 50, 100], f"unexpected ks: {ks}"
print(f"[ok] cells={len(cells)} ks={ks}")
for c in cells:
    print(c["params"], "overall=", c.get("overall_llm_score"))
PY
```

judge 로그에 정책 라인이 찍혔는지 확인:
```sh
grep -m1 "longmemeval_answer_prompt" results/_log_p0_all_v7_p4.log
# 기대: [judge] longmemeval_answer_prompt=LME_origin_cot_prompt longmemeval_yesno_policy=lenient
```

### 2.3 #4 산출물 백업 (다음 단계 진행 전 필수)

> #3 단계에서 같은 `run_name` 으로 retrieve 를 다시 돌리면 동일 디렉토리에
> 결과가 쏟아진다. 백업 + symlink 로 보호한다.

```sh
mv results/p0_all_v7 results/p0_all_v7__p4_ksweep
ln -s p0_all_v7__p4_ksweep results/p0_all_v7
ls -l results/ | grep p0_all_v7
```

기대: `p0_all_v7 -> p0_all_v7__p4_ksweep` symlink + `p0_all_v7__p4_ksweep/` 실디렉토리.

---

## Step 3. #6 — multi-session 분해 (analyze-only)

### 3.1 신규 yaml 작성

```sh
python - <<'PY'
import yaml, pathlib
src = yaml.safe_load(pathlib.Path("configs/runs/p0_all_v7.yaml").read_text())
out = dict(src)
out["problem"] = 6
out["description"] = "#6 multi-session 분해 (#4 결과 후처리)"
out["sweep"] = {}
out["metrics"] = ["per_session_count_distribution", "accuracy_by_session_bucket"]
out["run_name"] = "p6_from_v7"
out["reuse_run"] = "p0_all_v7"
pathlib.Path("configs/runs/p6_from_v7.yaml").write_text(
    yaml.safe_dump(out, sort_keys=False, allow_unicode=True)
)
print("[ok] configs/runs/p6_from_v7.yaml")
PY
```

### 3.2 실행

```sh
python scripts/run_pipeline.py \
  --config configs/runs/p6_from_v7.yaml 2>&1 | tee results/_log_p6_from_v7.log
```

`scripts/run_pipeline.py:82-90` 의 분기에 의해, `reuse_run` 이 설정되어 있고
`--stage` 가 생략되면 자동으로 `--stage analyze` 만 실행된다.
로그 첫 줄에 다음이 떠야 한다:

```
[pipeline] reuse_run='p0_all_v7' detected -> restricting --stage to 'analyze' ...
[pipeline] run_name=p6_from_v7  stages=['analyze']
```

### 3.3 검증

```sh
test -f results/p6_from_v7/analyze.json && \
  python -c "import json; d=json.load(open('results/p6_from_v7/analyze.json')); print(list(d.keys())[:10])"
```

---

## Step 4. #12 — k vs (accuracy, tokens) Pareto (analyze-only)

### 4.1 신규 yaml 작성

```sh
python - <<'PY'
import yaml, pathlib
src = yaml.safe_load(pathlib.Path("configs/runs/p0_all_v7.yaml").read_text())
out = dict(src)
out["problem"] = 12
out["description"] = "#12 k vs accuracy/tokens Pareto (#4 결과 후처리)"
out["sweep"] = {}
out["metrics"] = ["accuracy_vs_k", "tokens_vs_k", "pareto_front"]
out["run_name"] = "p12_from_v7"
out["reuse_run"] = "p0_all_v7"
pathlib.Path("configs/runs/p12_from_v7.yaml").write_text(
    yaml.safe_dump(out, sort_keys=False, allow_unicode=True)
)
print("[ok] configs/runs/p12_from_v7.yaml")
PY
```

### 4.2 실행

```sh
python scripts/run_pipeline.py \
  --config configs/runs/p12_from_v7.yaml 2>&1 | tee results/_log_p12_from_v7.log
```

로그 첫 줄에 다음이 떠야 한다:

```
[pipeline] reuse_run='p0_all_v7' detected -> restricting --stage to 'analyze' ...
[pipeline] run_name=p12_from_v7  stages=['analyze']
```

### 4.3 검증

```sh
test -f results/p12_from_v7/analyze.json && \
  python -c "import json; d=json.load(open('results/p12_from_v7/analyze.json')); print(list(d.keys())[:10])"
```

---

## Step 5. #3 — prefix on/off

> Step 2 의 #4 결과는 `results/p0_all_v7__p4_ksweep/` 에 보존되어 있고,
> `results/p0_all_v7` 는 그쪽을 가리키는 symlink 이다.
> 이제 같은 `run_name` 으로 retrieve 를 다시 돌리되 prefix sweep 으로 변경.

### 5.1 ⚠️ 위험 단계 — symlink 제거 (실행 전 반드시 확인)

> `results_dir_for()` 는 `Path.mkdir(parents=True, exist_ok=True)` 로
> 디렉토리를 보장한다(`scripts/stages/_common.py:48-51`). symlink-to-dir
> 위에서도 mkdir 가 성공하므로, **symlink 를 남겨둔 채 5.3 의 retrieve 를
> 실행하면 #4 백업 디렉토리(`p0_all_v7__p4_ksweep/`)가 #3 결과로
> 덮어써져 영구 손실된다.** 이 5.1 단계를 절대로 건너뛰지 말 것.

다음 3개 명령을 정확히 이 순서로 실행한다. 한 줄이라도 OK 출력이 안
나오면 **즉시 멈추고 사용자에게 보고**.

```sh
test -L results/p0_all_v7 && rm results/p0_all_v7        || { echo "ABORT: not a symlink"; exit 1; }
test ! -e results/p0_all_v7 && echo "[ok] results/p0_all_v7 cleared (symlink only)"
test -d results/p0_all_v7__p4_ksweep && echo "[ok] p4 backup intact"
```

### 5.2 yaml 을 prefix sweep 형태로 갱신

```sh
python - <<'PY'
import yaml, pathlib
p = pathlib.Path("configs/runs/p0_all_v7.yaml")
d = yaml.safe_load(p.read_text())
d["description"] = "LongMemEval 500 — prefix on/off (chunk=on, k=50 고정)"
d["sweep"] = {
    "search_limit": [50],
    "prepend_user_prefix": [False, True],
}
fixed = d.setdefault("fixed", {})
fixed.pop("prepend_user_prefix", None)
fixed["message_sentence_chunking"] = True
fixed["test_target"] = "memmachine"
p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True))
print("[ok] p0_all_v7.yaml -> prefix sweep")
PY
```

확인:

```sh
python - <<'PY'
import yaml, pathlib
d = yaml.safe_load(pathlib.Path("configs/runs/p0_all_v7.yaml").read_text())
assert d["sweep"]["search_limit"] == [50]
assert d["sweep"]["prepend_user_prefix"] == [False, True]
assert "prepend_user_prefix" not in d["fixed"]
print("[ok] sweep configured for #3")
PY
```

> 본 step 은 retrieve-time 변수만 토글하므로 configuration.yml 재생성은
> 불필요하다. `scripts/stages/retrieve.py:89-103` 가 cell 마다
> `evaluation.longmemeval.prepend_user_prefix` 를 in-place 로 덮어쓴다.

### 5.3 실행

```sh
python scripts/run_pipeline.py \
  --config configs/runs/p0_all_v7.yaml \
  --stage retrieve,generate,judge,analyze 2>&1 | tee results/_log_p0_all_v7_p3.log
```

### 5.4 검증

```sh
python - <<'PY'
import json, pathlib
d = json.loads(pathlib.Path("results/p0_all_v7/analyze.json").read_text())
cells = d.get("cells", [])
pairs = sorted((c["params"].get("search_limit"), c["params"].get("prepend_user_prefix")) for c in cells)
assert pairs == [(50, False), (50, True)], f"unexpected cells: {pairs}"
for c in cells:
    print(c["params"], "overall=", c.get("overall_llm_score"))
PY
```

### 5.5 #3 산출물 rename + symlink 복원

```sh
mv results/p0_all_v7 results/p0_all_v7__p3_prefix
ln -s p0_all_v7__p4_ksweep results/p0_all_v7
ls -l results/ | grep p0_all_v7
```

기대 최종 상태:
```
p0_all_v7 -> p0_all_v7__p4_ksweep    (symlink, #6/#12 reuse 기본)
p0_all_v7__p4_ksweep/                (#4 산출)
p0_all_v7__p3_prefix/                (#3 산출)
p6_from_v7/                          (#6 분석)
p12_from_v7/                         (#12 분석)
```

---

## Step 6. 최종 보고

다음을 한 번에 출력해서 사용자에게 보고한다:

```sh
echo "=== ingest ==="
cat results/p0_all_v7__p4_ksweep/ingest.jsonl 2>/dev/null || cat results/p0_all_v7/ingest.jsonl

echo "=== #4 (k sweep) ==="
python - <<'PY'
import json, pathlib
d = json.loads(pathlib.Path("results/p0_all_v7__p4_ksweep/analyze.json").read_text())
for c in d.get("cells", []):
    print(c["params"], "overall=", c.get("overall_llm_score"))
PY

echo "=== #6 (multi-session 분해) ==="
python -c "import json; print(json.dumps(json.load(open('results/p6_from_v7/analyze.json')), indent=2, ensure_ascii=False)[:2000])"

echo "=== #12 (k Pareto) ==="
python -c "import json; print(json.dumps(json.load(open('results/p12_from_v7/analyze.json')), indent=2, ensure_ascii=False)[:2000])"

echo "=== #3 (prefix on/off) ==="
python - <<'PY'
import json, pathlib
d = json.loads(pathlib.Path("results/p0_all_v7__p3_prefix/analyze.json").read_text())
for c in d.get("cells", []):
    print(c["params"], "overall=", c.get("overall_llm_score"))
PY
```

추가 주석:
- self-judge (Qwen3.5-397B) 한계 → **논문 절대값과 비교 금지**, 변수 효과만 해석.
- `[judge] longmemeval_answer_prompt=...` 로그가 #4 / #3 양쪽 로그에 모두 찍혔는지 확인.

---

## 체크리스트 (수행 후 □ → ☑)

- [ ] Step 0 사전 점검 통과 (브랜치, 프로파일, DB 포트, 데이터 파일)
- [ ] Step 1.3 run yaml + configuration.yml 정합성 검증 통과
- [ ] Step 1.4 ingest 완료 (`status=ok`, num_questions=500)
- [ ] Step 1.5 session_id = `eval_tool_longmemeval_p0_all_v7`
- [ ] Step 2.2 #4 cells == 5개 (k=10,20,30,50,100)
- [ ] Step 2.3 `results/p0_all_v7__p4_ksweep/` 백업 + symlink 생성
- [ ] Step 3 #6 analyze.json 생성, 로그에 `stages=['analyze']`
- [ ] Step 4 #12 analyze.json 생성, 로그에 `stages=['analyze']`
- [ ] Step 5.1 symlink 만 제거 (실데이터 보존 확인)
- [ ] Step 5.4 #3 cells == 2개 (prefix off/on)
- [ ] Step 5.5 결과 rename + symlink 복원
- [ ] Step 6 최종 보고 출력

---

## 회피해야 할 함정

1. **`run_name` 절대 바꾸지 않는다**. session_id 가 거기서 결정됨.
2. **`results/p0_all_v7/` 를 직접 `rm -rf` 하지 않는다**. 항상 `mv` 또는
   `rm <symlink>` 만 사용. 특히 Step 5.1 의 symlink 제거는 #4 백업
   영구 손실을 막는 단 하나의 가드다.
3. **fixed 값을 run yaml 만 직접 수정하지 않는다**. `_apply_fixed_to_configuration`
   가 호출되지 않아 configuration.yml 과 drift 가 발생한다. 항상
   `--from-json` 으로 generate_config 를 통해 적용한다.
4. **`message_sentence_chunking` 을 sweep 에 넣지 않는다** (`scripts/stages/retrieve.py:32` 차단).
5. **judge 모델은 self-judge (Qwen3.5-397B)** — 보고서마다 명시.
6. **Step 1.4 ingest 도중 중단하지 않는다.** 끊겼으면 사용자에게 보고하고 멈춤.

---

## 비정상 종료 대응

| 증상 | 원인 | 조치 |
|------|------|------|
| `retrieve.jsonl` 비어 있음 | session_id 미스매치 | `run_name == "p0_all_v7"` 인지 yaml 확인 |
| `[retrieve] sweep keys ['message_sentence_chunking'] ...` | chunking 을 sweep 에 둠 | `fixed:` 로 이동 |
| analyze 가 빈 결과 / 즉시 종료 | `reuse_run` 가 가리키는 run 산출물 부재 | symlink 가 `p0_all_v7__p4_ksweep/` 를 올바로 가리키는지 확인 |
| `ingest.jsonl` 없는데 retrieve 실행 | Step 1 미수행 | Step 1 부터 재진행 |
| Step 1.3 어서션 실패 (configuration.yml drift) | `--from-json` 누락 또는 yaml 직접 수정 | Step 1 부터 재실행 (`--from-json` 포함) |
| `mv results/p0_all_v7 ...` 가 symlink 를 옮김 | 대상이 symlink | `rm results/p0_all_v7` 로만 제거 후 재구성 |
