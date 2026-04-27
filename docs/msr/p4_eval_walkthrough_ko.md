# PR #7 평가 도구 — 문제4 예제 walkthrough (한국어)

> 세션 메모. 문제4(LongMemEval k sweep) 를 예시로 PR #7 평가 도구가 옵션을 어떻게 받아 어떻게 처리하는지 정리.

---

## 1단계: 기존 코드 vs PR7 추가 코드

PR7 은 **기존 평가 코드를 wrapping** 한 도구. 새로 만든 게 아니라 위에 한 겹 씌운 것.

### PR7 이전부터 있던 코드 (PR7이 안 건드림)

```
evaluation/retrieval_agent/
  ├─ longmemeval_test.py       ← LongMemEval 데이터셋 로딩 + ingest + search
  │     • load_longmemeval_dataset()
  │     • longmemeval_ingest()
  │     • longmemeval_search()
  ├─ hotpotQA_test.py
  ├─ locomo_ingest.py / locomo_search.py / locomo_delete.py
  └─ ...
evaluation/utils/
  └─ agent_utils.py            ← process_question(), 토큰/recall 집계
```

확인 방법: `git log --all --oneline -- evaluation/retrieval_agent/longmemeval_test.py` 의 모든 커밋이 PR7 머지(`8824f55`) 이전. PR7 의 `git diff --stat` 결과에도 `evaluation/` 경로가 한 줄도 없음.

**의미**: 데이터셋 로딩, ingest, search 같은 핵심 로직은 PR7 이전 코드 그대로. `length: 500`, `split: longmemeval_s` 의 의미와 동작도 기존 코드의 것이지 PR7 이 새로 정의한 게 아님.

### PR7 이 새로 만든 것 (총 32 파일, 본체)

```
scripts/                        ← 새 wrapper 도구 본체
  ├─ generate_config.py         ← 옵션 4-way merge → run YAML 생성
  ├─ run_pipeline.py            ← stage 순서대로 실행
  ├─ _merge.py                  ← deep_merge / yaml IO 유틸
  └─ stages/
      ├─ ingest.py              ← evaluation/retrieval_agent/*_ingest 함수를 호출
      ├─ retrieve.py            ← agent_utils.process_question 호출
      ├─ generate.py            ← (no-op, retrieve 가 같이 emit)
      ├─ judge.py               ← LLM 채점 호출
      └─ analyze.py             ← jsonl 합쳐 cell 별 집계
configs/                        ← 옵션 정의 (base/problems/profiles/runs)
prompts/EDWIN1.txt, EDWIN3.txt  ← placeholder
docs/USAGE.md, DECISIONS.md, RESEARCH.md
```

### 둘이 어떻게 만나나

PR7 wrapper 가 기존 코드를 부르는 방식은 두 가지:

1. **import 호출** — LongMemEval / HotpotQA. Python 함수를 그대로 import.
   - `scripts/stages/ingest.py:38-47`:
     ```python
     from evaluation.retrieval_agent.longmemeval_test import (
         load_longmemeval_dataset, longmemeval_ingest,
     )
     dataset = load_longmemeval_dataset(length=..., split=...)  # 기존 함수
     asyncio.run(longmemeval_ingest(dataset, config_path, session_id))
     ```
   - `scripts/stages/retrieve.py:121-135` 의 `agent_utils.process_question()` 도 기존 함수.

2. **subprocess 호출** — LoCoMo. CLI 형태로만 동작하게 짜인 기존 스크립트라 subprocess 로 띄움.
   - `scripts/stages/ingest.py:75-83`:
     ```python
     cmd = [sys.executable, ".../locomo_ingest.py", "--data-path", ..., "--config-path", ...]
     subprocess.run(cmd, ...)
     ```

### 한 줄 정리

| 무엇이 | 어디서 정의 | PR7 책임 범위 |
|---|---|---|
| `length`, `split` 의 동작 | 기존 `load_longmemeval_dataset` | 값을 넘겨주기만 |
| `prepend_user_prefix`, `message_sentence_chunking` | 기존 `longmemeval_test.py` 가 configuration.yml에서 읽음 | configuration.yml에 값을 써주기만 |
| `search_limit` | 기존 `process_question(search_limit=...)` 인자 | sweep cell 마다 그 인자로 넘기기만 |
| `test_target` 분기 (Memmachine/ToolSelect/llm) | 기존 agent 클래스들 | 어떤 클래스를 쓸지 분기만 |
| sweep / fixed / cell 개념 | (기존엔 없음) | **PR7 이 새로 도입** |
| 4-way merge / run YAML 박제 | (기존엔 없음) | **PR7 이 새로 도입** |
| stage 분리 / jsonl 산출 / analyze 집계 | (기존엔 일부만) | **PR7 이 새로 도입** |

**즉**: "무엇을 평가할지(데이터셋 로딩 + 실제 검색/답변)는 기존 코드, 어떻게 옵션을 묶고 반복할지(sweep + cell + jsonl)는 PR7" 가 구분선.

---

## 2단계: `longmemeval_oracle` 써도 동작하나?

**결론**: 코드는 동작함. 평가 의미가 달라져서 p4 의 목적엔 안 맞음.

### 코드 관점 — 동작함

`split` 값이 코드에서 흐르는 경로 (`evaluation/retrieval_agent/longmemeval_test.py:294-303`):

```python
def load_longmemeval_dataset(length: int, split: str):
    split_file = split if split.endswith(".json") else f"{split}.json"
    try:
        dataset = load_dataset("xiaowu0162/longmemeval-cleaned", split=split)  # 그대로 전달
        num_rows = min(length, len(dataset))
        records = dataset.select(range(num_rows)).to_list()
    except Exception:
        # fallback: f"{split}.json" 파일명으로 직접 다운로드
        ...
```

핵심: split 이름은 **유효성 검사 없이** 그대로 HuggingFace 에 넘겨짐. PR7 wrapper 도 이름을 검증 안 함. `xiaowu0162/longmemeval-cleaned` repo 에 그 이름의 split 이 존재하기만 하면 동작. 일반적으로:

| split 이름 | 파일명 | 약 sample 수 |
|---|---|---|
| `longmemeval_s` | longmemeval_s.json | ~500 (small haystack) |
| `longmemeval_m` | longmemeval_m.json | ~500 (medium haystack, 더 긴 history) |
| `longmemeval_oracle` | longmemeval_oracle.json | ~500 (정답에 필요한 dialog만) |

`load_longmemeval_dataset()` 이후 normalize 코드 (`longmemeval_test.py:325-336`) 가 `question` / `answer` / `question_type` / `haystack_sessions` 만 사용. oracle 도 이 4 필드 구조가 같아서 ingest/retrieve/judge 다 통과.

### 바꾸는 방법 — `--split` CLI 가 없어 우회

`generate_config.py` 의 CLI 인자(`scripts/generate_config.py:49-83`)에 `--split` 없음. 세 가지 길:

**방법 A — p4.yaml 직접 수정 (영구)**
```yaml
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_oracle
```

**방법 B — JSON override (일회성, 권장)**
```json
{
  "problem": 4,
  "run_name": "p4_oracle",
  "configuration": {"model_profile": "my_model", "db_profile": "my_db"},
  "benchmark": {"split": "longmemeval_oracle"},
  "sweep": {"search_limit": [10, 20]}
}
```
```sh
python scripts/generate_config.py --from-json configs/runs/oracle_override.json
```

**방법 C — 생성된 run YAML 직접 편집**

세 방법 모두 deep_merge 가 받아주고 stage 진행에 영향 없음.

### 평가 의미 관점 — p4 의도와 안 맞음

- **`longmemeval_s`/`longmemeval_m`**: haystack 안에 정답과 무관한 잡담이 잔뜩. retrieve 가 잡음 속에서 정답을 골라내야 함 → retrieve 능력 + answer LLM 능력 둘 다 측정.
- **`longmemeval_oracle`**: haystack 에 정답에 진짜 필요한 dialog 만. retrieve 가 별로 안 중요 → answer LLM 능력만 측정.

p4 목적은 "k(=search_limit) 늘릴 때 정확도가 단조증가하는가, 비단조인가" 인데 oracle 에선:
- haystack 자체가 작아 k=10 만으로도 거의 다 retrieve 됨
- k 늘려도 더 가져올 게 없음
- cell 5개 accuracy 차이가 거의 없어 신호 안 잡힘

**즉**:
- ✅ 도구 정상 작동 빠른 smoke 테스트용으로 좋음 (HF 다운만 되면)
- ✅ "answer LLM 자체 baseline" 측정용으론 좋음
- ❌ p4 의 "k sweep 비단조성" 검증엔 부적합. 이걸 보려면 `longmemeval_s` 그대로.

---

## 3단계: 웹 접속 없는 환경에서 LongMemEval 쓰기

### 현재 코드 한계

기존 함수 `load_longmemeval_dataset` (`evaluation/retrieval_agent/longmemeval_test.py:294-323`) 는 인터넷을 두 번 시도:

```python
try:
    dataset = load_dataset("xiaowu0162/longmemeval-cleaned", split=split)
    # HuggingFace datasets 라이브러리: 캐시 없으면 인터넷
except Exception:
    data_path = hf_hub_download(repo_id="xiaowu0162/longmemeval-cleaned",
                                repo_type="dataset", filename=split_file)
    # HuggingFace Hub: 캐시 없으면 인터넷
```

PR7 wrapper 는 이걸 손대지 않고 그대로 부름. "미리 받은 JSON 경로를 직접 지정한다" 는 옵션이 코드에 없음. 두 우회로 중 하나 필요.

### 옵션 A: HF 캐시 옮기기 (코드 수정 0줄, 추천)

위 두 함수는 **같은 캐시 디렉토리** 를 봄. 인터넷 머신에서 캐시 채운 뒤 통째로 오프라인 머신에 복사하고 오프라인 모드 켜면 끝.

#### 1. 인터넷 머신에서 캐시 채우기
```sh
pip install datasets huggingface_hub
python - <<'EOF'
from huggingface_hub import hf_hub_download
for fn in ["longmemeval_s.json", "longmemeval_oracle.json"]:
    p = hf_hub_download(
        repo_id="xiaowu0162/longmemeval-cleaned",
        repo_type="dataset",
        filename=fn,
    )
    print("got:", p)
EOF
```

캐시 위치:
```
~/.cache/huggingface/hub/
  datasets--xiaowu0162--longmemeval-cleaned/
    blobs/<sha>...
    snapshots/<commit_hash>/
        longmemeval_s.json -> ../../blobs/<sha>
        longmemeval_oracle.json -> ../../blobs/<sha>
    refs/main
```

> primary path(`load_dataset`)도 함께 캐시하고 싶으면:
> ```python
> from datasets import load_dataset
> load_dataset("xiaowu0162/longmemeval-cleaned", split="longmemeval_s")
> ```
> `~/.cache/huggingface/datasets/` 도 채워짐. 하지만 fallback 만 있어도 PR7 도구는 동작.

#### 2. 오프라인 머신으로 캐시 통째 복사
```sh
# 인터넷 머신
tar czf hf_cache.tgz -C ~ .cache/huggingface
# 오프라인 머신
tar xzf hf_cache.tgz -C ~
```

또는 `HF_HOME` 환경변수로 캐시 위치를 repo 내부로 옮기는 것도 가능.

#### 3. 오프라인 머신에서 환경변수 켜고 실행
```sh
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1   # primary path까지 캐시한 경우만
python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage ingest
```

**장점**: PR7/기존 코드 0줄 수정. p4.yaml 의 `split` 만 캐시한 split 이름으로.
**단점**: 캐시 디렉토리 구조가 낯섦. snapshot symlink 끊기지 않게 tar 통째 복사.

### 옵션 B: 짧은 wrapper 패치 (직관적, ~15줄)

p4.yaml 에 `benchmark.local_path` 추가 가능하게 PR7 wrapper 수정.

`scripts/stages/ingest.py` 의 `_ingest_longmemeval` 패치 예시:
```python
def _ingest_longmemeval(run_cfg, config_path, session_id):
    from evaluation.retrieval_agent.longmemeval_test import (
        load_longmemeval_dataset, longmemeval_ingest,
    )
    bench = run_cfg["benchmark"]

    local_path = bench.get("local_path")
    if local_path:
        import json
        with open(local_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        dataset = raw[: int(bench["length"])]
        for r in dataset:
            r.setdefault("question_type", "unknown")
            r.setdefault("haystack_sessions", [])
            r["split"] = bench.get("split", "local")
    else:
        dataset = load_longmemeval_dataset(
            length=int(bench["length"]), split=bench["split"]
        )

    asyncio.run(longmemeval_ingest(dataset, config_path, session_id))
    return {"benchmark": "longmemeval", "num_questions": len(dataset)}
```

`retrieve.py:88-90` 의 `_run_longmemeval_cell` 도 같은 분기 추가. 두 곳 다 해야 함 (ingest 와 retrieve 가 같은 dataset 을 따로 로드).

p4.yaml:
```yaml
benchmark:
  name: longmemeval
  length: 500
  split: longmemeval_s
  local_path: /home/user/data/longmemeval_s.json
```

**장점**: 캐시 구조 신경 안 쓰고 평범한 JSON 한 개만 두면 됨.
**단점**: PR7 코드 수정 필요. 후속 PR.

### 어느 쪽?

| 상황 | 추천 |
|---|---|
| 일회성 평가 | 옵션 A (캐시 통째 복사 + `HF_HUB_OFFLINE=1`) |
| 팀이 계속 사용, 데이터 경로 명시적 | 옵션 B (wrapper 패치) |
| HotpotQA(p2) 도 오프라인 | 둘 다 비슷하게 적용. p5(LoCoMo)는 이미 `data_path` 인자 있어 오프라인 친화 |
