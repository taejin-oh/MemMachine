# Eval 브랜치 변경사항 검증 플레이북 (복붙 실행용)

작성일: 2026-04-27
대상: `eval` 브랜치 fork 이후 변경사항
목표: 변경 사항이 실제 환경에서 의도대로 적용되었는지 단계별 확인

---

## 0) 사전 준비

```bash
# 0-1. 저장소 진입
cd /workspace/MemMachine

# 0-2. 브랜치/원격 확인
if ! git remote | grep -q '^upstream$'; then
  git remote add upstream https://github.com/taejin-oh/MemMachine.git
fi

git fetch upstream --prune

git checkout work

# 0-3. eval 브랜치와 동일 커밋인지 확인 (원격 상황에 따라 해시가 달라질 수 있음)
git rev-parse --short HEAD
git rev-parse --short upstream/eval
```

성공 기준:
- `git fetch` 성공
- `HEAD` 와 `upstream/eval` 이 동일하거나, 최소한 비교 가능한 상태

---

## 1) 변경 범위 빠른 점검 (fork 이후)

```bash
cd /workspace/MemMachine

# 1-1. 분기점 확인
git merge-base upstream/main upstream/eval

# 1-2. eval 전용 커밋 목록
git log --oneline --reverse upstream/main..upstream/eval

# 1-3. 변경 파일 목록
git diff --name-only upstream/main..upstream/eval

# 1-4. retrieval_agent 하위 변경 파일만 추출
git diff --name-only upstream/main..upstream/eval -- evaluation/retrieval_agent
```

성공 기준:
- `evaluation/retrieval_agent` 아래 변경 파일이 다음 5개로 보임
  - `README.md`
  - `longmemeval_test.py`
  - `run_benchmark_matrix.sh`
  - `run_test.sh`
  - `test_run_test.py`

---

## 2) retrieval_agent 변경사항 검증

### 2-1. LongMemEval prefix 토글 + search-limit 옵션 존재 확인

```bash
cd /workspace/MemMachine

# 코드 레벨 확인
rg -n "prepend_user_prefix|search_limit|--search-limit" \
  evaluation/retrieval_agent/longmemeval_test.py \
  evaluation/retrieval_agent/run_test.sh

# 도움말 노출 확인
bash evaluation/retrieval_agent/run_test.sh longmemeval --help | sed -n '1,200p'
```

성공 기준:
- `longmemeval_test.py` 에서 `prepend_user_prefix` 로딩/적용 코드 확인
- `run_test.sh longmemeval --help` 출력에 `--search-limit` 포함

### 2-2. `--search-limit` 유효성 검증(에러 케이스)

```bash
cd /workspace/MemMachine

# longmemeval 이 아닌 테스트에서 search-limit 사용 시 거부되어야 함
bash evaluation/retrieval_agent/run_test.sh wikimultihop exp1 search retrieval_agent 10 --search-limit 20 || true
```

성공 기준:
- `--search-limit is only supported for longmemeval search runs` 메시지 출력

### 2-3. ingest 상태 마커(JSON) 생성 확인

> 주의: 실제 ingest 는 DB/모델 환경이 필요합니다. DB가 없으면 실패할 수 있습니다.
> 실패하더라도 `[INGEST_FAIL]` 로그와 status 파일 생성 여부를 먼저 확인하세요.

```bash
cd /workspace/MemMachine/evaluation/retrieval_agent

# 최소 준비
mkdir -p result/ingest_status

# (환경 준비된 경우) 실제 ingest 예시
bash run_test.sh hotpotqa smoke_ingest ingest validation memmachine 5 || true

# ingest 상태 파일 확인
ls -lah result/ingest_status | sed -n '1,120p'

# 가장 최근 파일 열람
LATEST_STATUS=$(ls -t result/ingest_status/*.json 2>/dev/null | head -n 1)
if [ -n "$LATEST_STATUS" ]; then
  echo "status file: $LATEST_STATUS"
  cat "$LATEST_STATUS"
else
  echo "status file not found"
fi
```

성공 기준:
- 콘솔에 `[INGEST_START]` 와 `[INGEST_OK]` 또는 `[INGEST_FAIL]` 출력
- `result/ingest_status/*.json` 파일 생성

### 2-4. 매트릭스 스크립트 동작 확인(dry-run)

```bash
cd /workspace/MemMachine/evaluation/retrieval_agent

bash run_benchmark_matrix.sh --dry-run --summary-path result/matrix_dryrun.log

echo "--- summary head ---"
sed -n '1,120p' result/matrix_dryrun.log
```

성공 기준:
- LongMemEval `chunk x prefix x k` 조합 커맨드가 로그에 출력
- LoCoMo/Hotpot mode 조합 커맨드도 출력

---

## 3) chunk YAML wiring 검증

### 3-1. 서버 설정 모델에 chunk 필드 존재 확인

```bash
cd /workspace/MemMachine

rg -n "message_sentence_chunking" \
  packages/server/src/memmachine_server/common/configuration/episodic_config.py \
  evaluation/utils/agent_utils.py \
  evaluation/retrieval_agent/run_benchmark_matrix.sh
```

성공 기준:
- 서버 config model + eval 경로 + matrix 스크립트 모두에서 해당 키 확인

### 3-2. 관련 테스트 실행

```bash
cd /workspace/MemMachine

# uv 환경 기준
uv run pytest \
  packages/server/server_tests/memmachine_server/common/configuration/test_episodic_config.py
```

성공 기준:
- 테스트 통과

---

## 4) STM summarization 토글 검증

### 4-1. 기본값/샘플/문서 값 확인

```bash
cd /workspace/MemMachine

rg -n "summarization_enabled" \
  packages/server/src/memmachine_server/common/configuration/episodic_config.py \
  packages/server/src/memmachine_server/episodic_memory/short_term_memory/short_term_memory.py \
  packages/server/src/memmachine_server/episodic_memory/short_term_memory/service_locator.py \
  sample_configs/episodic_memory_config.cpu.sample \
  docs/open_source/configuration.mdx
```

성공 기준:
- 기본값이 `false`로 연결되어 있고, 샘플/문서와 일치

### 4-2. STM 관련 테스트 실행

```bash
cd /workspace/MemMachine

uv run pytest \
  packages/server/server_tests/memmachine_server/episodic_memory/short_term_memory/test_short_term_memory.py
```

성공 기준:
- 테스트 통과

---

## 5) PR #7 eval-tool(wrapper) 검증

### 5-1. run config 생성 검증

```bash
cd /workspace/MemMachine

python scripts/generate_config.py \
  --problem 4 \
  --run-name p4_verify_5q \
  --model-profile _example \
  --db-profile _example \
  --k-list 10,20 \
  --length 5

# 생성물 확인
ls -lah configs/runs/p4_verify_5q.yaml
ls -lah configs/generated/p4_verify_5q_configuration.yml
```

성공 기준:
- run yaml + working configuration.yml 둘 다 생성

### 5-2. 분석 단계 smoke 검증 (DB/LLM 없이)

```bash
cd /workspace/MemMachine

# 가짜 judge/retrieve 데이터 생성
mkdir -p results/p4_verify_5q

cat > results/p4_verify_5q/judge.jsonl <<'JSONL'
{"cell_idx":0,"question_id":"q1","question":"Q1","category":"ms","llm_score":1,"sweep":{"search_limit":10}}
{"cell_idx":0,"question_id":"q2","question":"Q2","category":"ssu","llm_score":0,"sweep":{"search_limit":10}}
{"cell_idx":1,"question_id":"q3","question":"Q3","category":"ms","llm_score":1,"sweep":{"search_limit":20}}
JSONL

cat > results/p4_verify_5q/retrieve.jsonl <<'JSONL'
{"cell_idx":0,"question_id":"q1","question":"Q1","selected_tool":"ToolSelectAgent","supporting_facts":["a","b"],"fact_hits":["a"],"input_token":10,"output_token":5,"tool_select_input_token":2,"tool_select_output_token":1,"num_episodes_retrieved":3,"llm_time":0.2}
{"cell_idx":0,"question_id":"q2","question":"Q2","selected_tool":"ToolSelectAgent","supporting_facts":["c"],"fact_hits":[],"input_token":12,"output_token":6,"tool_select_input_token":3,"tool_select_output_token":1,"num_episodes_retrieved":2,"llm_time":0.3}
{"cell_idx":1,"question_id":"q3","question":"Q3","selected_tool":"SplitQueryAgent","supporting_facts":["d","e"],"fact_hits":["d","e"],"input_token":20,"output_token":8,"tool_select_input_token":5,"tool_select_output_token":2,"num_episodes_retrieved":5,"llm_time":0.4}
JSONL

python scripts/run_pipeline.py \
  --config configs/runs/p4_verify_5q.yaml \
  --stage analyze \
  --decompose-multisession \
  --pareto

# 결과 확인
cat results/p4_verify_5q/analyze.json
```

성공 기준:
- `analyze.json` 생성
- `cells`, `by_tool`, `mean_recall`, `overall_recall`, `pareto`, `ms_vs_others_gap` 확인

### 5-3. `n_runs > 1` 방어 로직 검증

```bash
cd /workspace/MemMachine

python scripts/generate_config.py \
  --problem 4 \
  --run-name p4_verify_nruns \
  --model-profile _example \
  --db-profile _example \
  --k-list 10 \
  --length 1 \
  --n-runs 2

python scripts/run_pipeline.py --config configs/runs/p4_verify_nruns.yaml --stage analyze || true
```

성공 기준:
- `NotImplementedError` 메시지로 `n_runs=1` 제약 명시

---

## 6) 문서와 구현 정합성 점검

```bash
cd /workspace/MemMachine

# USAGE의 핵심 caveat 확인
rg -n "paper exact reproduction|n_runs|chunk on/off|start_index|search_limit|hotpotqa_group|group_" docs/USAGE.md

# PR #7 이후 남은 TODO 확인
rg -n "session isolation|start/end|search_limit|chunk" docs/msr/msr_eval_tool_todo_pr7.md
```

성공 기준:
- 문서에 실제 제한/주의사항이 분명히 기재되어 있음

---

## 7) 권장 최종 검증 커맨드 묶음

```bash
cd /workspace/MemMachine

# 7-1. Python lint/type (환경 구축 시)
uv run ruff check
uv run ty check packages

# 7-2. 핵심 테스트만
uv run pytest evaluation/retrieval_agent/test_run_test.py
uv run pytest packages/server/server_tests/memmachine_server/common/configuration/test_episodic_config.py
uv run pytest packages/server/server_tests/memmachine_server/episodic_memory/short_term_memory/test_short_term_memory.py
```

성공 기준:
- 위 커맨드들이 통과하면, 이번 변경의 주요 기능 경로가 정상 동작한다고 판단 가능

---

## 부록 A) 자주 걸리는 이슈

1. `configuration.yml not found`:
   - `evaluation/retrieval_agent/configuration.yml` 를 준비하거나
   - `scripts/generate_config.py` 로 working config를 먼저 생성

2. DB/LLM 미구성:
   - ingest/retrieve/judge는 외부 인프라가 필요
   - analyze stage는 로컬 jsonl만으로도 smoke 검증 가능

3. chunk on/off 비교 실험 오류:
   - 같은 run에서 retrieve만 반복하면 안 됨
   - chunk 값별 별도 run_name + ingest 재수행 필요

