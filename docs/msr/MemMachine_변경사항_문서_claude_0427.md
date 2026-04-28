## MemMachine 변경사항 분해 문서

### 0. 배경 — 왜 이 fork 가 필요한가

MemMachine 평가 대상으로 정리한 6 개 후보(#2 다중-hop 검색 / #3 사용자-편향 검색 / #4 검색 깊이 비단조성 / #5 LoCoMo / #6 Multi-session 재분해 / #12 비용-정확도 Pareto)를 **사내 평가 환경에서 변수 효과를 외삽 검증** 할 수 있어야 하는데, 원본 코드는 이 6 개 실험을 위한 토글·sweep 경로가 부족했습니다. 현재 코드는 (1) 기존 평가 코드를 최소만 손대고, (2) 그 위에 read-only wrapper 를 얹고, (3) 설계·결정·검증 상태를 문서로 남기는 세 갈래로 나뉩니다.

> 본 fork 의 결과는 **paper exact reproduction 이 아닙니다**. JSON-str=off 운영 방침과 EDWIN prompt 미적용 때문에 **operational reproduction / 변수 효과 외삽 (extrapolation)** 으로만 해석되어야 합니다 (`docs/msr/MemMachine_재현평가_설계_0425.md` §0 / §5).

| 영역                                                         |   파일 |       추가 |   삭제 |
| ------------------------------------------------------------ | -----: | ---------: | -----: |
| 기존 평가 코드 수정 (`evaluation/retrieval_agent/{longmemeval_test.py, run_test.sh, README.md, test_run_test.py}` + `evaluation/utils/agent_utils.py`) |      5 |       +237 |     -7 |
| 신규 매트릭스 스크립트 (`evaluation/retrieval_agent/run_benchmark_matrix.sh`) |      1 |       +252 |      0 |
| 서버 설정/동작 코어 변경 (`episodic_config.py` + `short_term_memory.py` + `service_locator.py`) |      3 |        +20 |     -1 |
| 서버 설정 회귀 테스트 보강 (`packages/server/server_tests/...` 기존 파일 2 종) |      2 |        +86 |      0 |
| 신규 wrapper (`scripts/` + `configs/` + `prompts/`)          |     23 |     +1,933 |      0 |
| 신규 문서 (`docs/msr/*` + `docs/USAGE.md` + `README_MSR.md` + `RESEARCH.md` + `DECISIONS.md`) |     13 |     +2,299 |      0 |
| 기타 (`.gitignore` / `pyproject.toml` / `sample_configs/*.sample` / `docs/open_source/configuration.mdx`) |      6 |        +26 |      0 |
| **합계**                                                     | **53** | **+4,853** | **-8** |

> [개발자 코멘트] fork 시작점은 upstream `6b1988b` (#1358 stale-issues workflow). 그 이후 46 commits. 기존 평가 코드 5 file 의 per-file numstat (additions / deletions) — `README.md (+13/0)`, `longmemeval_test.py (+41/-2)`, `run_test.sh (+69/-1)`, `test_run_test.py (+102/-1)`, `agent_utils.py (+12/-3)`. 서버 회귀 테스트 두 파일(`test_episodic_config.py`, `test_short_term_memory.py`)은 upstream 에 이미 존재하던 파일에 케이스를 추가한 것 — 신규 파일 아님.

---

### A. 평가 코드 직접 수정 (4 건)

#### A1. LongMemEval 질문 앞에 "User: " 라벨을 켜고/끌 수 있게 함

**한 줄 요약**: 논문 §8.4.2 의 사용자-편향 ablation(C5/C6) 의 변수 효과를 사내 평가 환경에서 외삽 검증할 수 있도록, 질문에 `User:` 라벨을 붙일지 말지를 설정 파일 한 줄로 켤 수 있게 했습니다.

**위치**: `evaluation/retrieval_agent/longmemeval_test.py` (신규 함수 `_load_longmemeval_question_prefix_enabled`, `longmemeval_search()` 루프 안에서 사용)

**이전**:

```python
question = str(sample.get("question", "")).strip()
# 질문은 항상 원문 그대로 사용
```

**이후**:

```python
prepend_user_prefix = _load_longmemeval_question_prefix_enabled(config_path)
...
if prepend_user_prefix:
    question = f"User: {question}"
```

`configuration.yml` 에:

```yaml
evaluation:
  longmemeval:
    prepend_user_prefix: true # 또는 false (기본값)
```

**왜**: 논문 C5 vs C6 단일 변수 비교의 동일 변수 축을 사내 평가 환경에서 켜고 끌 수단이 없었음. 다만 paper C5/C6 는 JSON-str=on 조건이라 본 fork 에서는 **C5/C6 직접 재현이 아닌 "user_q 토글 효과의 외삽"** 으로 해석.

> [개발자 코멘트] 새 helper 는 YAML 파싱 실패 / 키 누락 / 타입 mismatch 에 모두 `False` 로 안전 fallback. `prepend_user_prefix` 를 명시하지 않은 기존 실행 경로는 기존과 동일하게 동작. 매 search 호출마다 YAML 1 회 읽음 — 큰 비용 아님.

---

#### A2. LongMemEval 검색 깊이 (k) 를 외부에서 조절 가능

**한 줄 요약**: 한 질문당 검색해서 가져올 문서 수(k)를 명령줄에서 바꿀 수 있게 했습니다. 논문이 보고한 "k 가 늘어나면 정확도가 오르다가 다시 떨어지는" 현상(#4)의 변수 효과를 외삽 검증하기 위함.

**위치**: `evaluation/retrieval_agent/longmemeval_test.py` (`DEFAULT_SEARCH_LIMIT` 상수, `longmemeval_search()` 시그니처, `build_parser()`), `evaluation/retrieval_agent/run_test.sh`

**이전**:

```python
search_limit=20, # 코드에 박힌 고정값
```

**이후**:

```python
parser.add_argument("--search-limit", type=positive_int, default=DEFAULT_SEARCH_LIMIT)
...
search_limit=search_limit, # CLI 에서 받은 값
```

사용 예:

```bash
./run_test.sh longmemeval exp_k50 search longmemeval_s_cleaned retrieval_agent 500 --search-limit 50
```

**왜**: 논문 §8.4.1 의 비단조성 실험과 동일 k 값 sweep `{10, 20, 30, 50, 100}` 을 사내 평가 환경에서 구성하려면 외부 파라미터화가 필요.

> [개발자 코멘트] `positive_int` 는 `evaluation/retrieval_agent/cli_utils.py` 에서 import. `run_test.sh` 가 `--search-limit` 을 longmemeval search 외 명령에 쓰면 명시적 에러("`--search-limit is only supported for longmemeval search runs`"). silent ignore 대신 즉시 실패시켜 사용자 오해를 차단.

---

#### A3. legacy `run_test.sh` ingest 의 표준 로그 + 상태 마커

**한 줄 요약**: `run_test.sh` 기반의 매트릭스 실행에서 ingest 가 부분 실패해도 발견할 수 있도록, 각 ingest 의 시작·종료·상태가 정해진 형식의 로그와 파일로 남게 했습니다.

**위치**: `evaluation/retrieval_agent/run_test.sh` (ingest 분기), `evaluation/retrieval_agent/result/ingest_status/<test>_<target>_<postfix>.json`

> 본 마커는 **legacy `run_test.sh` 실행 경로 전용** 입니다. 뒤에 나오는 PR #7 wrapper(`scripts/stages/ingest.py`) 의 idempotent skip 은 다른 메커니즘(C2 참조)으로 동작하며 두 시스템은 서로 사용하지 않습니다.

**이전**:

```bash
"${INGEST_CMD[@]}" # 그냥 실행. 실패하면 종료. 성공/실패가 별도로 기록되지 않음.
```

**이후** (요지):

```bash
echo "[INGEST_START] test=... target=... postfix=... session_id=... started_at=..."
if "${INGEST_CMD[@]}"; then
    echo "[INGEST_OK] ..."
    cat > "${INGEST_STATUS_FILE}" <<EOF
{ "status": "ok", ... }
EOF
else
    echo "[INGEST_FAIL] ..."
    cat > "${INGEST_STATUS_FILE}" <<EOF
{ "status": "fail", ... }
EOF
    exit 1
fi
```

**왜 (실측 매트릭스 동작 기준)**: `run_benchmark_matrix.sh` 한 사이클에서 LongMemEval 은 `chunk × prefix × k = 20` 개 셀을 실행하며, **현재 스크립트 구조상 `--skip-ingest` 를 주지 않으면 ingest 도 각 셀마다 수행** 됩니다. 그 20 회 중 한 둘이 실패해도 사후에 `result/ingest_status/` 만 보면 어느 셀이 깨졌는지 즉시 식별 가능.

> [개발자 코멘트] 시간은 모두 UTC ISO-8601. `INGEST_START / INGEST_OK / INGEST_FAIL` prefix 는 grep 후처리 가능한 표준 형식. **분석 시에는 k 별 ingest 반복으로 인한 실행 시간 중복과 retrieve/search 단계의 성능 지표를 분리해서 해석해야 한다. k 는 search 단계 변수이므로, 동일 chunk/prefix 조건에서 k 별 ingest 가 반복되는 것은 실행 비용 측면에서는 중복이다.**

---

#### A4. 매트릭스 실행 스크립트 신규 추가 (`run_benchmark_matrix.sh`)

**한 줄 요약**: 매트릭스 한 번에 실행. LongMemEval 의 chunk × prefix × k = 20 셀 + LoCoMo / HotpotQA 까지 한 명령으로.

**위치**: `evaluation/retrieval_agent/run_benchmark_matrix.sh` (신규)

**이전**: 사용자가 직접 5 개 k 값마다 명령을 손으로 5 번씩 4 회(prefix on/off × chunk on/off) = 20 번 실행. 각 실행 사이 `configuration.yml` 두 키도 직접 편집.

**이후**:

```bash
./run_benchmark_matrix.sh # 전체 매트릭스
./run_benchmark_matrix.sh --dry-run # 명령만 미리보기
./run_benchmark_matrix.sh --skip-ingest # search 만
```

스크립트가 자동으로:

- `configuration.yml` 의 `evaluation.longmemeval.prepend_user_prefix` 토글
- `episodic_memory.long_term_memory.message_sentence_chunking` 토글
- 각 조합에 대해 ingest + search + judge + scoring 실행
- 종료 시 `trap restore_config EXIT` 가 백업으로 복원

**왜**: 손으로 실행하면 반드시 토글을 빼먹거나 sweep 한 칸을 누락. 실험 재현성의 가장 큰 위협 제거.

> [개발자 코멘트] 매트릭스 후보값 — `LONGMEM_K_VALUES=(10 20 30 50 100)`, `*_PREFIX_VALUES=(off on)`, `*_CHUNK_VALUES=(off on)`, `LONGMEM_SPLIT="longmemeval_s_cleaned"`. **FIXED in eval_claude** — PR #7 의 `configs/problems/p{3,4}.yaml` 도 `split: longmemeval_s_cleaned` 로 통일됨. 두 경로 split 일치. 인-플레이스 YAML 토글은 Python(yaml.safe_load → mutate → yaml.safe_dump). **`mktemp` 백업 + EXIT trap 으로 일반 에러나 Ctrl-C 종료 시 원본을 복원한다. 단, `kill -9` 처럼 trap 이 실행되지 않는 강제 종료에서는 복원되지 않을 수 있다.** 알려진 한계 — LoCoMo / HotpotQA 셀 진입 시 chunk 값이 LongMemEval 루프 마지막값(`on`)으로 잔류 (`docs/msr/20260425_eval_code_review.md` § B-1).

---

### B. 서버 설정/동작 확장 (3 건)

#### B1. chunk on/off YAML 값이 partial config round-trip 에서 사라지던 버그 수정

**한 줄 요약**: 설정 파일에 `message_sentence_chunking: true` 라고 적어도 partial → full 머지 단계에서 누락되어 default `false` 로 덮어씌워지던 회귀를 고쳤습니다 (v0.0 검증에서 발견).

**위치**: `packages/server/src/memmachine_server/common/configuration/episodic_config.py` (`LongTermMemoryConfPartial` 클래스)

**이전**: `LongTermMemoryConf` (full) 는 이 필드를 갖고 있었으나, partial 모델에 같은 필드가 없어 머지 단계에서 흘리지 못함.

**이후**:

```python
class LongTermMemoryConfPartial(BaseModel):
    ...
    message_sentence_chunking: bool | None = Field(
        default=None,
        description="Whether to chunk message episodes into sentences for embedding",
    )
```

**왜**: 이 필드가 누락되어 있으면 `chunk × prefix × k` 매트릭스에서 chunk 축이 침묵 무효 — 사용자는 두 케이스를 비교했다고 생각하지만 실은 둘 다 `chunk=off`. 모든 chunk-관련 결론이 무효가 됨.

> [개발자 코멘트] Pydantic partial 패턴 — `bool | None`(default=None) 으로 "지정 안 됨" 과 "False 로 명시" 를 구분. `merge()` 에서 `None` 이면 base 값 유지. 회귀 테스트는 `packages/server/server_tests/memmachine_server/common/configuration/test_episodic_config.py` 에 51 라인 보강.

---

#### B2. chunk 토글의 평가 측 적용 (kwarg vs YAML 우선순위)

**한 줄 요약**: 평가 코드가 `init_memmachine_params(message_sentence_chunking=...)` 인자를 받지 않아도, 설정 파일의 값을 자동으로 사용하도록 했습니다.

**위치**: `evaluation/utils/agent_utils.py:init_memmachine_params`

**이전**:

```python
async def init_memmachine_params(
    ...,
    message_sentence_chunking: bool = False, # 명시적 인자 없으면 무조건 False
)
```

**이후**:

```python
async def init_memmachine_params(
    ...,
    message_sentence_chunking: bool | None = None,
)
...
if message_sentence_chunking is None:
    resolved_chunking = getattr(ltm_conf, "message_sentence_chunking", None)
else:
    resolved_chunking = message_sentence_chunking
if resolved_chunking is None:
    resolved_chunking = False
```

**왜**: B1 만으로는 부족. 평가 진입점이 인자를 안 넘기면 여전히 `False` 가 됨. **인자 우선 / YAML fallback / 둘 다 없으면 False** 의 3-단계 우선순위가 세워짐.

> [개발자 코멘트] 시그니처 변경은 호환적(`bool` → `bool | None`, default 만 변경). **명시적으로 `message_sentence_chunking` kwarg 를 넘기던 기존 호출자는 영향이 없다. 다만 YAML 에 `message_sentence_chunking: true` 가 설정되어 있던 실행은 이제 의도대로 `true` 가 반영된다 (B1 와 결합되어 침묵 무효 회귀가 해소됨).** `longmemeval_test.py` 는 의도적으로 kwarg 미전달 — YAML 단일 진실 원천 유지.

---

#### B3. STM 메모리 정리 시 LLM 요약 생성을 끌 수 있게 함

**한 줄 요약**: 단기 메모리(STM)가 가득 찼을 때 오래된 메시지는 정리하되, 비싼 LLM 요약 생성은 생략할 수 있는 토글을 추가. 평가 매트릭스 비용 절감 목적.

**위치**:

- 설정 schema: `packages/server/src/memmachine_server/common/configuration/episodic_config.py` (`ShortTermMemoryConf` + `ShortTermMemoryConfPartial`)
- 적용: `packages/server/src/memmachine_server/episodic_memory/short_term_memory/short_term_memory.py` (필드 정의, 인스턴스 변수, **`_do_evict()` 메서드 안에서 분기**)
- params carry: `packages/server/src/memmachine_server/episodic_memory/short_term_memory/service_locator.py`

**이전** (`ShortTermMemory._do_evict()` 안):

```python
result = list(self._memory)
self._current_episode_count = 0
await self._consolidator.summarize(result) # 항상 LLM 호출
```

**이후**:

```yaml
episodic_memory:
  short_term_memory:
    summarization_enabled: false # 신규 키, 기본값 false
```

```python
result = list(self._memory)
self._current_episode_count = 0
if self._summarization_enabled:
    await self._consolidator.summarize(result)
```

**왜**: 평가 매트릭스를 반복 실행할 때 STM 요약 LLM 호출이 비용 / 지연 / 외부 의존성을 키움.

> ⚠️ **운영 영향 — 운영 환경 확인 필요**: 신규 키의 기본값이 `false` 라, 사용자가 키를 명시하지 않으면 STM 요약 생성이 꺼진 상태로 동작할 수 있습니다. 운영 환경에서는 의도한 값이 명시되어 있는지 사전 확인 필요.

> [개발자 코멘트] 메모리 evict 자체(`while ... popleft()`)는 계속 동작 — STM 이 무한정 커지지는 않음. 회귀 테스트는 `packages/server/server_tests/memmachine_server/episodic_memory/short_term_memory/test_short_term_memory.py` 에 35 라인 보강.

---

### C. PR #7 — read-only MVP wrapper (10 건)

> 핵심 원칙: **PR #7 wrapper 는 기존 `evaluation/retrieval_agent/*` 코드를 추가로 크게 바꾸지 않고, repo root 의 `scripts/`, `configs/`, `prompts/` 에서 기존 평가 코드를 감싸는 것을 목표로 합니다.** 다만 본 branch 전체에는 §A 의 LongMemEval / `run_test.sh` 관련 직접 수정이 별도로 포함되어 있습니다 — 두 작업은 시기와 PR 단위가 다릅니다.

#### C1. 신규 디렉터리 구조

**한 줄 요약**: 기존 평가 코드를 손대지 않고 그 위에 얹는 별도 도구 영역을 만들었습니다.

**위치**:

```text
configs/ # 사용자 입력 (YAML)
  base.yaml
  problems/{p2,p3,p4,p5,p6,p12}.yaml
  profiles/{models,dbs}/_example.yaml
  runs/_example.json
scripts/ # 실행 로직
  generate_config.py
  run_pipeline.py
  stages/{ingest,retrieve,generate,judge,analyze,_common}.py
prompts/ # EDWIN1.txt, EDWIN3.txt (placeholder)
results/ # 산출물 (.gitignore)
docs/USAGE.md # 사용자 가이드
RESEARCH.md, DECISIONS.md # 설계 / 결정 기록 (repo root)
```

**왜**: `evaluation/retrieval_agent/*` 는 upstream 코드. 그 안에 새 도구 코드를 섞으면 upstream merge 충돌이 빈번해지고, "어디까지가 논문 코드/어디부터가 본인 코드인지" 경계가 흐려짐.

> [개발자 코멘트] `D-004` 의 결정. `results/` 는 `.gitignore` 추가됨. wrapper 는 upstream 함수를 import 또는 subprocess 로 호출만 하고 수정 금지(`D-006`).

---

#### C2. 평가를 5 단계로 분리 (ingest → retrieve → generate → judge → analyze)

**한 줄 요약**: 한 번에 끝까지 도는 단일 명령 대신, 5 개 작은 단계로 쪼개서 비싼 단계는 캐시하고 값싼 단계만 다시 돌릴 수 있게 했습니다.

**위치**: `scripts/stages/{ingest,retrieve,generate,judge,analyze}.py`, `scripts/run_pipeline.py`

**이전**: `run_test.sh` 가 한 호출로 ingest+search+judge+scoring 을 묶음 실행. 중간 단계만 재실행하려면 명령 손으로 나눠야 함.

**이후**:

```bash
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage all
# 또는
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage ingest
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage retrieve
python scripts/run_pipeline.py --config configs/runs/p4_full.yaml --stage retrieve,judge,analyze
```

각 stage 의 산출:

| stage    | 파일                           | 의미                                                         |
| -------- | ------------------------------ | ------------------------------------------------------------ |
| ingest   | `results/{run}/ingest.jsonl`   | 한 줄 status. 마지막 row 가 `status=ok` 면 다음 실행 시 자동 skip (`scripts/stages/ingest.py:_already_ingested`) |
| retrieve | `results/{run}/retrieve.jsonl` | 질문별 chunks + perf + token + fact_hits                     |
| generate | `results/{run}/generate.jsonl` | 질문별 model_answer (retrieve 와 같은 loop 산출 — D-005)     |
| judge    | `results/{run}/judge.jsonl`    | + llm_score                                                  |
| analyze  | `results/{run}/analyze.json`   | cell 별 accuracy / recall / token / per-tool / Pareto        |

**왜**: ingest 는 DB 적재라 가장 비싸고 반복 안전. judge 는 LLM 호출이라 비용 큼. 분리해서 부분 재실행 가능해야 실험 회전이 빨라짐.

> 본 wrapper 의 idempotent skip 은 A3 의 legacy `result/ingest_status/*.json` 마커와 별개 — wrapper 는 자체 산출물 `results/{run}/ingest.jsonl` 만 본다.

> [개발자 코멘트] `D-001` + `D-005`. retrieve 와 generate 는 한 loop 로 산출. ingest skip 판정은 `_already_ingested(out_path)` — `out_path` 가 존재하고 마지막 JSONL row 의 `status` 가 `"ok"` 일 때만 skip.

---

#### C3. 6 개 문제별 기본 sweep / fixed 설정 YAML

**한 줄 요약**: 어느 문제를 재현하려는지 한 줄 옵션(`--problem 4`)으로 고르면, 해당 실험에 필요한 sweep 축이 자동으로 채워집니다.

**위치**: `configs/problems/p{2,3,4,5,6,12}.yaml`, `configs/base.yaml`

**예시 — p4.yaml** (논문 #4 LongMemEval k sweep, 실측):

```yaml
problem: 4
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_s_cleaned # ← eval_claude 에서 통일된 이름. 이전엔 'longmemeval_s'
sweep:
  search_limit: [10, 20, 30, 50, 100]
fixed:
  prepend_user_prefix: true
  message_sentence_chunking: true # chunk=on
  test_target: retrieval_agent
prompts:
  generate_prompt_file: prompts/EDWIN3.txt # placeholder, 실제 swap 미수행
```

**예시 — p2.yaml** (논문 #2 HotpotQA Memory vs Agent, 실측):

```yaml
problem: 2
benchmark:
  name: hotpot # ← 'hotpot', 'hotpotqa' 아님
  length: 500
  split: validation
sweep:
  test_target: [memmachine, retrieval_agent]
fixed:
  search_limit: 20
```

**왜**: 6 개 문제마다 어떤 변수를 sweep 할지가 다름. 문서로만 적어두면 사용자가 손으로 입력하다 실수. YAML 로 박아두면 재현성↑.

> [개발자 코멘트] `generate_config.py` 가 `base.yaml + problems/p{N}.yaml + profiles/{model,db}` 를 머지(`scripts/_merge.py`) 해서 `configs/runs/{run_name}.yaml` 과 working `configuration.yml` 을 함께 생성. ~~A4 의 `run_benchmark_matrix.sh` 는 `longmemeval_s_cleaned` 를 사용해 둘이 다름~~ **FIXED in eval_claude**: p3/p4 yaml 도 `longmemeval_s_cleaned` 로 통일했으므로 두 경로 split 일치.

---

#### C4. 모델 / DB profile 분리

**한 줄 요약**: 모델(LLM·embedder·reranker)과 DB(Postgres·Neo4j) 설정을 별도 파일로 분리해, 모델만 바꿔서 비교 실험할 수 있게 했습니다.

**위치**: `configs/profiles/models/_example.yaml`, `configs/profiles/dbs/_example.yaml`

**이전**: 모델·DB가 하나의 `configuration.yml` 에 섞여 있어, "모델만 바꿔서 비교" 가 매번 거대한 YAML 한 덩이를 복사·편집하는 일.

**이후**:

```bash
cp configs/profiles/models/_example.yaml configs/profiles/models/my_model.yaml
cp configs/profiles/dbs/_example.yaml configs/profiles/dbs/my_db.yaml

python scripts/generate_config.py --problem 4 --run-name p4_pilot \
    --model-profile my_model --db-profile my_db
```

**왜**: 사용자 답변(`D-002`) — "향후 모델 변경하면서 평가하는 테스트를 고려해서 base.yaml 생성하고 미리 저장 된 추가 설정 사용해서 평가시 만들거나 내가 넣은거 사용하거나 선택하게."

> [개발자 코멘트] 하이브리드 — 모드 A(profile 조합) / 모드 B(`--use-existing-config /path/to/configuration.yml` 로 기존 파일 사용). 모드 B 도 working copy 만들어 원본 보호.

---

#### C5. 사용자 `configuration.yml` 원본 보호 (working copy)

**한 줄 요약**: 도구가 실행 중에 사용자의 설정 파일을 직접 수정하지 않습니다. 항상 사본을 만들어 그것만 수정.

**위치**: `scripts/generate_config.py:maybe_generate_configuration_yml`

**이전**: `run_benchmark_matrix.sh` (A4) 는 `configuration.yml` 을 직접 in-place 수정. 종료 시 trap 으로 복원하지만, 강제 종료(`kill -9`) 시 복원 실패 가능.

**이후**:

```text
configs/generated/{run_name}_configuration.yml # 도구가 만드는 working copy
                                                 # 사용자 원본은 read-only
```

`mode=existing` (사용자 기존 파일 사용) 도 working copy 를 만든 뒤 그것만 수정.

**왜**: 사용자 입장에서 "내 파일이 멋대로 바뀌어 있다" 가 가장 무서운 사고. 자동 매트릭스 실행에서 발생하면 디버깅 비용↑. 원본 무결성을 도구 차원에서 보장.

> [개발자 코멘트] PR #7 round-2 review 에서 추가된 항목. 기존 `run_benchmark_matrix.sh` 의 in-place 수정 + trap 패턴보다 안전.

---

#### C6. #6 Multi-session 재분해 자동 집계

**한 줄 요약**: 한 번 돌린 #4 결과를 가지고, 별도 실행 없이 #6 (다중 세션 질문이 단일 세션 질문보다 정확도가 떨어지는 정도) 까지 자동으로 계산.

**위치**: `scripts/stages/analyze.py:_add_multisession_decomposition`, `configs/problems/p6.yaml`

**사용**:

```bash
python scripts/run_pipeline.py --config configs/runs/p6_from_p4.yaml \
    --stage analyze --decompose-multisession
```

**산출 (실측 필드명, cell 별)**:

- `ms_accuracy` — multi-session 질문만의 정확도
- `others_mean_accuracy` — 나머지 카테고리 평균
- `ms_vs_others_gap` — 두 값의 차이

**왜**: 논문 §8.2 의 #6 은 별도 실험이 아니라 #4 의 산출을 재해석하는 후처리. 수기로 카테고리별로 잘라보는 것은 오류 가능성↑. 자동화하면 #4 한번 돌리고 끝.

> [개발자 코멘트] 입력은 `judge.jsonl` + `retrieve.jsonl` 이며, **LongMemEval 의 `question_type` 은 wrapper 의 retrieve 단계에서 row 의 `category` 필드로 저장**(`scripts/stages/retrieve.py:_run_longmemeval_cell` 안 `category=str(sample.get("question_type", "unknown"))`). analyze 단계는 이 `category` 값을 기준으로 `_MS_KEYS = {"multi-session", "multi_session", "ms"}` lower-case 매칭으로 MS 카테고리를 분리.

---

#### C7. #12 비용 vs 정확도 Pareto 자동 집계

**한 줄 요약**: k 값이 커질수록 정확도는 오르지만 토큰 비용도 오릅니다. 이 trade-off 를 한 표로 자동 출력.

**위치**: `scripts/stages/analyze.py:_add_pareto`

**사용**:

```bash
python scripts/run_pipeline.py --config configs/runs/p12_from_p4.yaml \
    --stage analyze --pareto
```

**산출 (실측 필드명, cell 별)**: `accuracy / mean_recall / overall_recall / mean_tokens_per_query / mean_input_token / mean_output_token / mean_num_episodes / mean_llm_time / n` 한 행씩, `search_limit` 오름차순 정렬.

**왜**: 임원·운영 입장에서 "정확도 +X% 를 위해 비용 +Y%" 를 한 시야에 보여줘야 의사결정 가능. 논문 #12 가 이 trade-off 의 단조성을 다룬 항목.

> [개발자 코멘트] retrieve.jsonl 에 token / per-tool / fact_hits 가 carry-over 되어야 동작. 그 carry-over 자체가 PR #7 round-3 review 에서 추가된 항목.

---

#### C8. EDWIN1 / EDWIN3 prompt — placeholder + hook only, **실제 swap 미수행**

**한 줄 요약**: 논문이 제안한 답변용 프롬프트(EDWIN1 / EDWIN3)를 나중에 끼워 넣을 자리는 만들었지만, **실제 텍스트가 확보되지 않아 hook 은 prompt 파일 존재·비어있지 않음만 검증할 뿐, 실 적용은 명시적으로 미구현 상태**입니다.

**위치**: `prompts/EDWIN1.txt`, `prompts/EDWIN3.txt` (placeholder), `scripts/stages/generate.py:_check_prompt_hook`

**검증된 현재 동작** (`scripts/stages/generate.py` 실측):

```python
def _check_prompt_hook(run_cfg):
    prompt_file = run_cfg.get("prompts", {}).get("generate_prompt_file")
    if not prompt_file:
        return "fallback (no prompt file configured — using built-in ANSWER_PROMPT)"
    p = (cm.REPO_ROOT / prompt_file).resolve()
    if not p.exists():
        return f"fallback (prompt file missing: {p})"
    body = _strip_comments(p.read_text(encoding="utf-8"))
    if not body:
        return f"fallback (prompt file empty after stripping comments: {p})"
    # Future work: actually inject this prompt. See DECISIONS.md D-003.
    return f"prompt loaded but NOT yet applied (future work): {p}"
```

→ hook 의 마지막 줄은 "loaded but **NOT yet applied**" 메시지를 반환.

**실제 답변 prompt — benchmark 별 built-in 사용**:

- LongMemEval 경로 — `evaluation/retrieval_agent/longmemeval_test.py` 의 built-in `ANSWER_PROMPT`
- HotpotQA 경로 — `evaluation/retrieval_agent/hotpotQA_test.py` 의 built-in `ANSWER_PROMPT` (별도 정의)
- LoCoMo 경로 — `evaluation/retrieval_agent/locomo_search.py` 의 built-in `ANSWER_PROMPT` (별도 정의)
- 세 경로 모두 EDWIN prompt swap 은 아직 적용되지 않았다.

**왜 미완**: `D-003` — "아직 edwin 정보가 없기 때문에 향후 추가 가능한 형태로만 만들고, 실제 기능은 제외".

**의미**: 이 항목 미해결 = 논문 C5 / C6 / C12 와 단일 변수 비교 불가 → 본 fork 의 결과는 **paper exact reproduction 이 아닌 변수 효과 외삽 (extrapolation)** 으로 해석. `docs/msr/MemMachine_재현평가_설계_0425.md` §5 "v4 추가 한계" 첫 단락에 명시.

> [개발자 코멘트] EDWIN 텍스트 확보 시 작업: (1) 두 .txt 에 실 prompt 저장, (2) `scripts/stages/generate.py` 의 hook 마지막 단계에서 prompt swap 코드 추가, (3) `mmai.lme_answer_prompt = "EDWIN3"` 식으로 평가 진입점 연결. benchmark 별 ANSWER_PROMPT 가 분리되어 있으므로 swap 로직도 benchmark 분기 필요.

---

#### C9. session_id 자동 생성 — **모든 benchmark 에 대해 생성하나, 실제 격리 적용은 LongMemEval ingest/retrieve 경로만**

**한 줄 요약**: 같은 DB 에서 같은 실험을 여러 번 돌려도 데이터가 섞이지 않도록 실행 이름에서 자동으로 격리 식별자를 만들지만, **HotpotQA / LoCoMo 는 wrapper 가 만든 식별자를 무시하고 upstream 의 고정 session_id 를 사용해 격리 보장이 안 됩니다**.

**위치 (실측)**:

- 생성: `scripts/stages/_common.py:session_id_for(run_cfg) = f"eval_tool_{bench}_{run_cfg['run_name']}"` — bench 무관 모두 생성
- LongMemEval — **ingest 와 retrieve 모두** wrapper 가 받은 `session_id` 를 그대로 `longmemeval_ingest(...)` / `init_memmachine_params(session_id=...)` 에 전달 → run_name 기준 격리 가능
- HotpotQA — wrapper 의 `_ingest_hotpot(_session_id)` / `_run_hotpot_cell(_session_id)` 가 인자명 underscore 처리하고 무시. retrieve 시 `init_memmachine_params(session_id="hotpotqa_group", ...)` 하드코드
- LoCoMo — subprocess 호출이 `session_id` 를 LoCoMo CLI 에 전달하지 않음. upstream `evaluation/retrieval_agent/locomo_ingest.py`, `locomo_search.py` 가 `group_id = f"group_{idx}"` 사용

**같은 DB 반복 실행 시**:

- ✅ LongMemEval — ingest 와 retrieve 모두 `eval_tool_longmemeval_{run_name}` 기반 session_id 를 사용하므로 run_name 기준 격리 가능
- ⚠️ HotpotQA — wrapper 에서 session_id 를 만들기는 하지만 upstream 코드가 `hotpotqa_group` 고정 session_id 를 사용하므로 실제 격리는 보장되지 않음
- ⚠️ LoCoMo — wrapper 에서 session_id 를 만들기는 하지만 upstream 코드가 `group_{idx}` 고정 session_id 를 사용하므로 실제 격리는 보장되지 않음

**왜 미해결**: 이 두 항목 수정은 `evaluation/retrieval_agent/` 의 read-only 경계를 깸 → 별도 PR 로 분리 (`docs/msr/msr_eval_tool_todo_pr7.md` #1, #2 — High 우선순위).

> [개발자 코멘트] 우회책 — p2 / p5 반복 시 (1) `hotpotQA_test.py --run-type delete` 또는 `locomo_delete.py` 로 직접 정리하거나 (2) 별도 DB 사용. `docs/USAGE.md` Q7 에 명시.

---

#### C10. silent 무효 차단 가드 — 일부 적용 / 일부는 향후 권장

**한 줄 요약**: 도구가 지원하지 않는 옵션을 받으면 silent 로 무시하는 대신 즉시 명시적으로 거부 — 적용된 항목과 향후 권장 항목으로 갈림.

**위치 / 검증된 현재 상태**:

| 가드 항목                              | 현재 상태                | 위치                                                         |
| -------------------------------------- | ------------------------ | ------------------------------------------------------------ |
| `n_runs > 1` 명시적 차단               | ✅ 적용됨                 | `scripts/run_pipeline.py` 가 `n_runs != 1` 시 `NotImplementedError` |
| `--search-limit` 비-LongMemEval 거부   | ✅ 적용됨                 | `evaluation/retrieval_agent/run_test.sh` 의 `validate_args`  |
| `sweep.message_sentence_chunking` 차단 | ❌ 향후 권장 (적용 안 됨) | `scripts/stages/retrieve.py:_apply_cell_to_config` 가 `params` 에 들어오면 그대로 적용 — ingest 결과가 어긋나도 silent. `scripts/generate_config.py:_apply_fixed_to_configuration` 의 docstring 만 "MUST be set before ingest, not just toggled per sweep cell" 경고 |
| LoCoMo `search_limit` 무시 차단        | ❌ 향후 권장 (적용 안 됨) | LoCoMo subprocess 가 `--search-limit` 을 전달하지 않음. p5 YAML 의 `fixed.search_limit` 값은 무시됨 (silent) |

**왜**: 사용자가 옵션을 넣었는데 도구가 그걸 무시하면, 결과만 보고는 알 수 없음. silent 무효는 평가 도구에서 가장 위험한 패턴. 일부는 적용되었고, 일부(chunk sweep / LoCoMo search_limit)는 `msr_eval_tool_todo_pr7.md` #4, #5 로 후속 PR 분리.

> [개발자 코멘트] 권장 후속 PR — (A) chunk sweep guard: `run_pipeline.py` 가 `sweep` 에 `message_sentence_chunking` 키가 보이면 `NotImplementedError`. (B) LoCoMo `--search-limit` 인자 추가: upstream `locomo_search.py` argparse + wrapper subprocess cmd 양쪽 수정.

---

### D. 문서 (6 건)

#### D1. 논문 6 후보 정량 수치 설계서

**위치**: `docs/msr/MemMachine_재현평가_설계_0424.md` → `..._0425.md`

**역할**: 6 개 후보 각각의 paper 인용(§·Table·페이지), 본 과제 운영 조건, 종속변수, 판정 기준을 한 표로 정리. 실험 시작 전 기준 문서.

> [개발자 코멘트] 0424 = v3, 0425 = v4 (코드 리뷰 결과 반영). v4 추가 한계 첫 단락에 "JSON-str=off 일탈 + EDWIN 미구현으로 paper C{n} exact reproduction 이 아닌 변수 효과 외삽" 명시.

---

#### D2. 항목별 구현 상태 진척표 (3 버전)

**위치**: `docs/msr/20260425_modified_list_v0.{0,1,2}.md`

**역할**: **외부 사전 정리 문서(`09_Reproduction_Code_Changes.md`)** 에서 정의한 13 개 수정 예정 항목 각각의 ✅ / ❌ / 제외 상태를 시점별로 기록.

| 버전 | 작성 시점                   | 핵심 변화                                                 |
| ---- | --------------------------- | --------------------------------------------------------- |
| v0.0 | 04/25                       | chunk YAML 검증에서 `applied_value=False` 회귀 발견       |
| v0.1 | 04/25                       | 표를 ✅ / ❌ 두 단계로 단순화                               |
| v0.2 | 04/25 (PR #7 후 절은 04/26) | chunk wiring 완료(B1+B2) 반영. PR #7 후 상태 별도 절 추가 |

> [개발자 코멘트] history 보존을 위해 v0.0 / v0.1 도 삭제하지 않고 그대로 둠. 최신 상태는 v0.2 의 § "PR #7 eval-tool 반영 후 상태" 표. **`09_Reproduction_Code_Changes.md` 는 현재 eval branch 에는 포함되어 있지 않으며, 외부 사전 정리 문서로만 참조한다.**

---

#### D3. 0424 + v0.2 + 코드 3중 정합 리뷰

**위치**: `docs/msr/20260425_eval_code_review.md`

**역할**: 두 문서(설계서 + 진척표)와 실제 코드의 정합성을 paper 정합 + 코드 정합 두 축으로 검증한 리뷰. 6 개 ✅ 항목은 코드와 정합, 5 개 ❌ 항목 중 EDWIN 은 blocker 격상 권고, JSON-str=off 일탈을 §0/§5 로 끌어올릴 것 권고 등.

> [개발자 코멘트] 본 검토에서 발견된 매트릭스 chunk 잔류 버그(LongMemEval 루프 종료 후 LoCoMo / HotpotQA 진입 시 chunk=on 잔류)는 아직 미수정 — 알려진 한계.

---

#### D4. PR #7 후 남은 코드 수정 5 건

**위치**: `docs/msr/msr_eval_tool_todo_pr7.md`

**역할**: PR #7 머지 후에도 남는 5 건의 upstream 시그니처 수정 항목을 현상→위험→개선후보→우선순위로 정리.

|    # | 항목                                                         | 우선순위 |
| ---: | ------------------------------------------------------------ | :------: |
|    1 | HotpotQA session isolation (`hotpotqa_group` 하드코드)       |   High   |
|    2 | LoCoMo session isolation (`group_{idx}` 하드코드)            |   High   |
|    3 | ~~LoCoMo `start_index=0 / end_index=20` 외부 파라미터화~~ → **DONE** (`--length` + `benchmark.length`) |  Medium → DONE  |
|    4 | LoCoMo `search_limit=20` 외부 파라미터화                     |  Medium  |
|    5 | chunk on/off 비교 자동화 (multi-run generator / sweep silent 차단) |  Medium  |

> [개발자 코멘트] 권장 후속 PR 분할 — PR-A: 5번 (wrapper-only) / PR-B: 1, 2번 (upstream 시그니처 + wrapper 동시) / PR-C: 3, 4번 (upstream argparse + wrapper 전달).

---

#### D5. 결정 기록 (DECISIONS.md, D-001 ~ D-006)

**위치**: `DECISIONS.md` (repo root)

**역할**: PR #7 설계 단계에서 사용자가 내린 6 개 결정을 timestamp 와 함께 보존:

- D-001: 5 단계 분리
- D-002: configuration.yml 하이브리드
- D-003: EDWIN hook only
- D-004: 신규 파일 위치 (repo root)
- D-005: retrieve / generate 한 loop 산출
- D-006: benchmark 별 호출 방식 (LongMemEval/HotpotQA 직접 import vs LoCoMo subprocess)

> [개발자 코멘트] 향후 결정 변경 시 새 ID 추가 + 이전 ID 에 `(superseded by D-{N})` 표기 규칙.

---

#### D6. 사용자 가이드 2 종

**위치**: `README_MSR.md` (repo root), `docs/USAGE.md` (PR #7 도구 사용법)

**역할**:

- `README_MSR.md` — legacy 평가 코드 변경과 STM summary 토글 사용 예시를 한눈에 정리한 페이지
- `docs/USAGE.md` — PR #7 wrapper 사용법. 6 개 문제별 1줄 명령. 자주 묻는 질문(EDWIN 미적용 / n_runs / session 격리).

> [개발자 코멘트] 두 문서 모두 한국어. 영문화 미수행.

---

### E. 종합 — 임원이 알면 좋은 3 가지

1. **Operational reproduction ≠ paper exact reproduction**. JSON-str=off 와 EDWIN prompt 미적용 때문에 paper Table 12 의 C5 / C6 / C12 와 단일 변수 비교가 불가능. 본 fork 결과는 "operational reproduction / 변수 효과 외삽 (extrapolation)" 으로 해석되어야 함.
2. **대표적으로 해결·개선된 항목 6 개 / 남은 핵심 미해결 항목 4 개**. ✅ chunk 토글 / k sweep / prefix 토글 / Pareto / MS 분해 / config 보호. ❌ EDWIN 실 적용 / DB snapshot / 반복 wrapper / 자동 σ×2 판정.
3. **다음 PR 분할 권장 3 종**. (A) chunk sweep guard / LoCoMo search_limit 자동화 / (B) HotpotQA·LoCoMo session 격리 (upstream 시그니처 수정) / (C) 매트릭스 chunk 잔류 버그 수정. 우선순위 — B > A ≈ C.

> 본 fork 는 MemMachine 논문 기반 문제 후보를 paper-exact 로 재현하는 도구가 아니라, **사내 평가 환경에서 변수 효과를 operational reproduction / extrapolation 관점으로 검증하기 위한 평가 자동화 기반** 입니다.

---

# 2. 반영한 포맷 수정 요약

|    # | 항목                                                         | 적용                                                         |
| ---: | ------------------------------------------------------------ | ------------------------------------------------------------ |
|    1 | B 섹션 제목                                                  | "B. 서버 설정 schema 확장 (3 건)" → "B. 서버 설정/동작 확장 (3 건)" — B3 의 `short_term_memory.py` 동작 변경 포함 범위 반영 |
|    2 | §0 변경량 표                                                 | Markdown 표 헤더(영역/파일/추가/삭제) + 정렬 지정자(`---:`) 적용. 행 8 개(7 영역 + 합계) 모두 셀 단위로 분리. 숫자·내용 무변경 |
|    3 | C2 stage 산출물 표                                           | Markdown 표로 정리. stage / 파일 / 의미 3 컬럼               |
|    4 | C10 silent 무효 차단 가드 표                                 | Markdown 표로 정리. 가드 항목 / 현재 상태 / 위치 3 컬럼      |
|    5 | D2 진척표                                                    | Markdown 표로 정리. 버전 / 작성 시점 / 핵심 변화 3 컬럼      |
|    6 | D4 후속 5 건 표                                              | Markdown 표로 정리. # / 항목 / 우선순위 3 컬럼 (우선순위는 가운데 정렬) |
|    7 | "이번 마지막 수정 사항 요약" / "코드 재검증" / "남은 확인 필요 항목" 표 | 모두 Markdown 표로 일관성 정리                               |
|    8 | 코드 예시 fenced code block + 언어 태그                      | Python (`python`), YAML (`yaml`), Bash (`bash`), 디렉터리·경로 트리·텍스트 (`text`) 로 명시. A3 의 `cat > ... <<EOF` heredoc 도 줄바꿈 정리 |
|    9 | bullet list / 단락 분리                                      | A4 / B3 / C1 / C5 / C6 / C8 / C9 / D5 / D6 의 항목성 기술을 명시적 `-` bullet 로 정리 |
|   10 | D6 README_MSR 설명                                           | "A1~A4 + B3 사용 예시. fork 의 평가-측 변경을 한 시선으로 모은 페이지" → "legacy 평가 코드 변경과 STM summary 토글 사용 예시를 한눈에 정리한 페이지" 로 완화 |

---

# 3. 내용 변경 여부 확인

본 작업은 **포맷 정리 위주** 이며, 의미·수치·파일명·함수명·구현 상태에 대한 새로운 사실 추가나 변경은 없습니다.

| 점검 항목                                                    | 결과                                                  |
| ------------------------------------------------------------ | ----------------------------------------------------- |
| 변경량 표의 모든 숫자 (53 / +4,853 / -8 / 영역별 numstat)    | 무변경                                                |
| 함수명·파일명 (예: `_do_evict()`, `session_id_for`, `_apply_cell_to_config`, `init_memmachine_params`) | 무변경                                                |
| 구현 상태 (✅ / ❌ / 적용됨 / 향후 권장)                       | 무변경                                                |
| paper exact reproduction / operational reproduction / extrapolation 표현 구분 | 무변경                                                |
| §0 paper exact reproduction 아님 / JSON-str=off / EDWIN 한계 | 무변경                                                |
| A3 legacy marker vs C2 wrapper skip 구분                     | 무변경                                                |
| A4 `kill -9` 예외 표현                                       | 무변경                                                |
| B2 `message_sentence_chunking` 영향 표현                     | 무변경                                                |
| B3 `_do_evict()` + `summarization_enabled` 운영 확인 필요 표현 | 무변경                                                |
| C 섹션 read-only wrapper 표현 보완                           | 무변경                                                |
| C6 `question_type` → `category` 흐름                         | 무변경                                                |
| C8 benchmark 별 built-in `ANSWER_PROMPT` 사용                | 무변경                                                |
| C9 LongMemEval vs HotpotQA / LoCoMo session isolation 차이   | 무변경                                                |
| C10 silent 무효 항목 적용/미적용 구분                        | 무변경                                                |
| D2 `09_Reproduction_Code_Changes.md` 가 현재 eval branch 미포함 표현 | 무변경                                                |
| 남은 확인 필요 항목 (8 건)                                   | 무변경                                                |
| §E 마무리 한 줄 방향성                                       | 무변경                                                |
| 의미적 변경 — B 제목 (서버 설정/동작) + D6 README_MSR 설명 완화 | **표현 명확화 차원의 미세 수정만 적용** (사용자 지시) |

