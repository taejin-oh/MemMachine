# `evaluation/longmemeval_v2/` — LongMemEval-V2, MemMachine 백엔드

upstream [xiaowu0162/LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2)
의 plug-in 메모리 아키텍처 위에 MemMachine 어댑터 (`memory_modules/memmachine.py`)
를 얹은 평가 환경. trajectory 기반 long-term agent memory benchmark — V1
(대화 기반 long-term chat memory) 과는 입력 / 평가 의미론이 완전히 다름.

## V2 vs V1 한눈에

| 항목 | V1 (`longmemeval/`) | V2 (이 디렉토리) |
|---|---|---|
| 입력 단위 | 대화 turn | WebArena/ServiceNow agent trajectory state |
| 격리 단위 | per-question (`<prefix>_<question_id>`) | per-trajectory (`<prefix>_<traj_id>`) |
| 도메인 | (single) | web / enterprise |
| 카테고리 | 5 task type + abstention | static / dynamic / procedure / gotchas (+ abs) |
| 답 형식 | free-form text | `\boxed{...}` (UNKNOWN abstention 지원) |
| Backend 인터페이스 | 우리 `ingest.py` / `retrieve.py` 가 MemMachine 직접 사용 | upstream `Memory` ABC 를 `memmachine.py` 로 구현 |

## 파일

| 파일 | 역할 |
|---|---|
| `memory_modules/memory.py` | upstream `Memory` ABC + `@register_memory` (verbatim) |
| `memory_modules/no_retrieval.py` | upstream no-retrieval 베이스라인 (verbatim) |
| `memory_modules/memmachine.py` | **NEW** — MemMachine 어댑터. trajectory→Episode 변환 + per-trajectory session 격리 + 동기/비동기 브리지 |
| `memory_modules/__init__.py` | base API re-export (registry 부트스트랩 트리거) |
| `_common.py` | MemMachine 부트스트랩 + V2 도메인/카테고리/judge 프롬프트 |
| `run_eval.py` | end-to-end 파이프라인 (ingest → retrieve → generate → judge) |
| `download_dataset.py` | HuggingFace 에서 dataset 자체 다운로드 + tar 풀기 + 검증 |
| `example_configuration.yml` | MemMachine working configuration.yml 템플릿 |
| `example_memory_config.json` | V2 memory backend config (memmachine type) 예시 |

## V2 데이터 schema (실측)

HuggingFace [xiaowu0162/longmemeval-v2](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2)
직접 다운로드 후 verify 한 실제 필드명:

**questions.jsonl** (451 question — web 240 / enterprise 211):
```jsonc
{
  "id": "01307e07",
  "domain": "enterprise",                           // web | enterprise
  "environment": "workarena",
  "question_type": "dynamic-environment",           // ← V1 호환 키 (category 가 아님!)
  "question": "...\\boxed{} 안내 포함된 본문...",
  "image": null,                                    // 멀티모달 질문이면 경로
  "answer": "Incident Mobile, Incident Portal, ...",
  "eval_function": "norm_phrase_set_match|lower=true|..."  // upstream 정확 평가 spec
}
```

**question_type 분포** (전체 451):
| question_type | n | 우리 정규화 (`_common.CATEGORY_MAP`) |
|---|---:|---|
| `static-environment` | 134 | `static` |
| `dynamic-environment` | 86 | `dynamic` |
| `procedure` | 74 | `procedure` |
| `static-environment-abs` | 55 | `static-abs` |
| `dynamic-environment-abs` | 41 | `dynamic-abs` |
| `procedure-abs` | 32 | `procedure-abs` |
| `errors-gotchas` | 29 | `gotchas` |

**trajectories.jsonl** (1,870 trajectory — 텍스트만 1.2 GB):
```jsonc
{
  "id": "00332982",
  "domain": "enterprise",
  "environment": "workarena",
  "goal": "...task 본문...",
  "outcome": "...",
  "start_url": "https://...",
  "states": [
    {
      "state_index": 0,
      "step": 0,
      "url": "https://...",
      "action": null,                  // 첫 state 는 보통 null
      "thought": "I will use ...",     // ← 단수형 (V1 의 'thoughts' 아님!)
      "accessibility_tree": "...",     // ← 텍스트 본문 (rendered DOM, 1~13KB)
      "screenshot": "screenshots/<traj_id>/0.png"
    },
    ...
  ]
}
```

**eval_function** (upstream V2 의 채점 함수, 상위 6 종):
| eval_function | n |
|---|---:|
| `norm_phrase_set_match` | 200 |
| `llm_abstention_checker` | 128 |
| `mc_choice_match` | 68 |
| `llm_gotchas_checker` | 28 |
| `norm_phrase_set_match_ordered` | 26 |
| `mc_choice_set_match` | 1 |

> **우리 judge 단순화**: `run_eval.py` 의 judge stage 는 위 6종을 무시하고
> **단일 LLM-as-judge yes/no** 만 사용 (`_common.build_judge_messages` —
> default / abstention / gotchas 3 system prompt). upstream 점수표와의
> bit-exact 비교가 목적이면 upstream `evaluation/qa_eval_metrics.py` 를
> 직접 사용 (우리 `memmachine.py` 어댑터는 upstream `memory_modules/` 에
> 그대로 떨어뜨릴 수 있음 — 본 README 끝 "drop-in 방법" 참고).

## 의존성

```
이 디렉토리 ── memmachine_server.*  (워크스페이스 패키지)
            └─ upstream V2 코드 (`memory_modules/memory.py`, `no_retrieval.py`
                                  만 vendored — 우리 디렉토리에 직접 복사됨)
```

`evaluation/longmemeval/` (V1), `evaluation/retrieval_agent/`,
`evaluation/utils/`, `scripts/` 어디도 import 안 함.

## 데이터 준비

LongMemEval-V2 데이터셋은 우리 저장소에 포함되지 **않습니다** — 수십 MB
(텍스트만) ~ 수 GB (멀티모달 스크린샷 포함) + HuggingFace license 동의 필요.
**자체 다운로드 스크립트** (`download_dataset.py`) 가 upstream V2 클론 / 별도
conda 환경 없이 한 방에 받아주니, upstream 저장소를 따로 clone 할 필요 없음.

### 1. HuggingFace 인증 (license 동의)

데이터셋 페이지 [xiaowu0162/longmemeval-v2](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2)
에서 "Agree and access repository" 한 번 클릭 후:

```bash
uv pip install "huggingface_hub[cli]>=0.24"
huggingface-cli login          # https://huggingface.co/settings/tokens 의 read 토큰
```

### 2. 데이터 다운로드 + 풀기 + 검증 (한 방에)

```bash
# 전체 (텍스트 + 스크린샷, ~수 GB) — 기본 destination: evaluation/data/longmemeval-v2/
uv run python -m evaluation.longmemeval_v2.download_dataset

# 빠른 스모크용 — 스크린샷 archive 제외 (~수십 MB)
uv run python -m evaluation.longmemeval_v2.download_dataset \
    --skip-screenshots --skip-validate

# 다른 위치에 받기
uv run python -m evaluation.longmemeval_v2.download_dataset \
    --data-root /custom/path/lmev2

# 기존 데이터 지우고 재다운로드
uv run python -m evaluation.longmemeval_v2.download_dataset --force
```

스크립트가 자동으로:
1. HuggingFace 에서 dataset snapshot 다운로드
   (`--skip-screenshots` 면 `*_screenshots*.tar.gz` 와 `question_screenshots/` 제외)
2. `trajectory_screenshots/*.tar.gz` 풀어 `screenshots/<traj_id>/<step>.png` 배치
   (default `--prepare-mode symlink`, 원본 archive 보존)
3. (default) `--tier small` 무결성 검증 — questions ↔ trajectories ↔ haystack
   cross-reference + 첫 50 trajectory 의 screenshot 존재 sanity

### 3. 결과 디렉토리 구조

```
<data_root>/                       # 기본: evaluation/data/longmemeval-v2/
  questions.jsonl                  # {id, domain, category, question, answer, ...}
  trajectories.jsonl               # {id, goal, start_url, actions, states[]}
  haystacks/
    lme_v2_small.json              # question_id → [trajectory_id, ...]
    lme_v2_medium.json
  question_screenshots/            # 질문이 멀티모달일 때 참조 이미지
  trajectory_screenshots/          # 다운받은 원본 .tar.gz (prepare 후 보존)
  screenshots/                     # prepare 가 만든 trajectory step PNG (or symlink)
    <traj_id>/0000.png ...
```

크기 (대략):
- `questions.jsonl`: ~1 MB (451 question)
- `trajectories.jsonl`: ~수십 MB (1,870 trajectory, 텍스트만)
- `screenshots/`: ~수 GB (멀티모달 평가 시 필요. **텍스트-only 회수**만
  쓸 거면 `--skip-screenshots` 로 받아도 우리 어댑터는 동작 — Episode
  metadata 의 screenshot 경로가 빈 값일 뿐 검색 자체엔 영향 없음)

### 트러블슈팅 (데이터 다운로드)

- **`401 Unauthorized` / `gated dataset`** → HF license 미동의. 위 1단계
  웹 페이지 클릭 + `huggingface-cli login` 재확인.
- **`No space left on device`** → `--skip-screenshots` 로 텍스트만 받기,
  또는 `--data-root /external/disk/...` 로 destination 옮기기.
- **`screenshots/.../0000.png` 없음** → `--skip-screenshots` / `--skip-extract`
  로 받음. 우리 어댑터는 metadata 경로만 저장하니 검색 자체엔 영향 없음.
- **다운로드 멈춤** → `HF_HUB_ENABLE_HF_TRANSFER=1` 환경변수로 가속
  (`uv pip install hf_transfer` 먼저).

## MemMachine 구성

`example_configuration.yml` 복사 후 placeholder 채우기:

```bash
cp evaluation/longmemeval_v2/example_configuration.yml \
   evaluation/longmemeval_v2/configuration.yml
# <NEO4J_PASSWORD>, <POSTGRES_PASSWORD> 채움
```

embedder + LLM 은 V1 과 동일하게 default 내부 OpenAI-호환 endpoint. 외부
모델 (cloud OpenAI / Gemini / Anthropic via LiteLLM / Bedrock) 으로 바꾸는
법은 V1 의 `example_configuration.yml` "옵션 예시 모음" 그대로.

## 사용 흐름

```bash
PREFIX=lmev2_smoke                              # 실험 이름 = session_prefix = 결과 dir
DATA=evaluation/data/longmemeval-v2             # download_dataset.py 기본 위치
CFG=evaluation/longmemeval_v2/configuration.yml # MemMachine 설정 (직접 생성)
LIMIT="--limit 2"                               # 스모크 2 문항. 풀 런 시 LIMIT=""
```

### 단일 명령 (ingest → retrieve → generate → judge)

```bash
uv run python -m evaluation.longmemeval_v2.run_eval \
    --data-root $DATA \
    --domain web \
    --tier small \
    --memmachine-configuration-path $CFG \
    --session-prefix $PREFIX \
    --top-k 50 \
    --output-dir results/$PREFIX \
    $LIMIT
```

### 일부만 평가 — 4 가지 필터

| 옵션 | 효과 | 예시 |
|---|---|---|
| `--limit N` | 선택된 도메인의 첫 N 질문만 ingest + 평가 | `--limit 2` |
| `--question-ids ID1 ID2 ...` | 특정 question_id 만 (공백 구분) | `--question-ids q_web_001 q_web_005` |
| `--domain web` / `enterprise` | 도메인 단위 (필수 인자) | — |
| `--tier small` / `medium` | haystack 난이도 (small: trajectory pool 작음) | — |

스모크 흐름:

```bash
# 1. 텍스트만 받기 (수십 MB, ~수 분)
uv run python -m evaluation.longmemeval_v2.download_dataset \
    --skip-screenshots --skip-validate

# 2. 2 문항만 한 사이클 돌려 동작 확인 (~수 분, LLM API 호출 적음)
uv run python -m evaluation.longmemeval_v2.run_eval \
    --data-root $DATA \
    --domain web --tier small \
    --memmachine-configuration-path $CFG \
    --output-dir results/lmev2_smoke \
    --limit 2

# 3. 결과 확인
cat results/lmev2_smoke/summary.json
```

`--limit` 가 가리키는 N 질문이 참조하는 trajectory 만 ingest 되므로,
Neo4j 적재 비용이 N 에 비례. 풀 런 (`LIMIT=""`) 시엔 도메인 전체 (web ~수백,
enterprise ~수백) 가 한 번에 ingest 되니 시간/디스크 미리 가늠.

결과:
```
results/lmev2_smoke/
  memory_config.json   # 재현용 (어떤 backend / param 으로 돌렸는지)
  retrieve.jsonl       # per-question 회수 chunk
  generate.jsonl       # reader LLM 답변 (+ \boxed{...})
  judge.jsonl          # judge LLM 판정
  summary.json         # overall + 카테고리별 정확도
```

### 단계 스킵 (재실행 가속)

| 옵션 | 효과 |
|---|---|
| `--skip-ingest` | Neo4j 에 이미 있는 trajectory 재사용 (top-k 만 바꿔 retrieve 재실행) |
| `--skip-generate` | retrieve.jsonl 까지만 (회수율 분석용) |
| `--skip-judge` | generate.jsonl 까지만 (judge LLM 비용 절약) |

```bash
# 같은 prefix 로 top-k 만 바꿔 retrieve 재실행:
uv run python -m evaluation.longmemeval_v2.run_eval \
    --data-root $DATA --domain web --tier small \
    --memmachine-configuration-path evaluation/longmemeval_v2/configuration.yml \
    --session-prefix lmev2_smoke --top-k 100 \
    --output-dir results/lmev2_smoke_topk100 \
    --skip-ingest \
    $LIMIT
```

### question 단위 필터

```bash
# 특정 질문만:
--question-ids q_web_001 q_web_005

# domain enterprise + tier medium 풀 런:
--domain enterprise --tier medium
```

## MemMachine 어댑터 동작 요약

`memory_modules/memmachine.py`:

1. **Insert** (`memory.insert(trajectory)`)
   - `session_id = f"{prefix}_{trajectory['id']}"`
   - 매번 `delete_session_episodes()` 후 재적재 (idempotent)
   - trajectory header (goal/start_url/outcome) 1 Episode + 각 state 1 Episode
   - Episode.metadata 에 `lmev2_session_id` / `lmev2_traj_id` / `lmev2_state_index`
     + screenshot 경로 (멀티모달 embedding 은 아직 미사용)

2. **Query** (`memory.query(query)`)
   - `set_query_context(haystack=[trajectory_ids])` 로 받은 ID 들 →
     각각의 session 에서 `query_agent.do_query()` 병렬 실행
   - 결과를 `episodes_to_string()` 으로 텍스트 직렬화 후
     `[{"type": "text", "value": ...}]` 리스트 반환

3. **Async 브리지**: V2 `Memory` 인터페이스는 동기. MemMachine API 는
   async. 백그라운드 이벤트 루프 한 개를 lazy 하게 띄우고
   `run_coroutine_threadsafe(...).result()` 로 동기화.
   `asyncio.run()` 을 매 호출마다 부르지 않으니 ResourceManager 캐시 유지.

## 알려진 제약

- **텍스트만**: 현재 어댑터는 trajectory state.text 만 임베딩 / 검색. 스크린샷
  (multimodal embedding) 은 metadata 에 경로만 저장. V2 의 멀티모달 질문에선
  upstream RAG 대비 회수율이 떨어질 수 있음.
- **per-trajectory 격리**: 한 question 의 haystack 에 여러 trajectory 가 들어가면
  각 trajectory session 에서 top-k 따로 회수 후 concat. cross-trajectory rerank
  없음 (V2 upstream `rag_query_to_slice` 와 다른 점).
- **Judge 단순화**: upstream `qa_eval_metrics.py` 는 카테고리별로 mc_choice_match
  / norm_phrase_set_match / LLM checker 등 8 종 평가 함수를 분기 사용. 이 디렉토리
  는 LLM-as-a-judge yes/no 3 가지 system prompt (default / abstention / gotchas)
  로 단순화. **upstream 점수와 bit-exact 비교가 목적이면 upstream 의 본격
  qa_eval_metrics.py 를 직접 사용** — 우리 메모리 모듈을 upstream `memory_modules/`
  에 그대로 옮기면 됨 (`memory.py` 가 verbatim 이라 호환).

## upstream V2 와의 정렬

| 항목 | upstream V2 | 우리 |
|---|---|---|
| 메모리 인터페이스 | `Memory` ABC | **verbatim** (`memory_modules/memory.py`) |
| 격리 단위 | (backend 별 다름) | per-trajectory session_id |
| 시스템 프롬프트 | web / enterprise | **verbatim** (`_common.DOMAIN_SYSTEM_PROMPTS`) |
| 답 추출 | `\boxed{...}` depth-aware | **verbatim** (`_common.extract_boxed_answer`) |
| 카테고리 정규화 | `CATEGORY_MAP` | **verbatim** (`_common.CATEGORY_MAP`) |
| Judge | 카테고리별 8 종 평가 (LLM + 정확 일치 + MC + …) | LLM yes/no 3 종 (default / abstention / gotchas) |

## upstream `memory_modules/` 에 우리 어댑터를 그대로 옮기는 법

`memory.py` 는 upstream 과 byte-equal 이라 `memmachine.py` 만 복사하면 됨:

```bash
cp evaluation/longmemeval_v2/memory_modules/memmachine.py \
   /path/to/LongMemEval-V2/memory_modules/

# memory_modules/__init__.py 의 trailing import 블록에 한 줄 추가:
#   from .memmachine import MemMachineMemory  # noqa: E402,F401
# (upstream memory.py 끝에 추가하거나 별도 모듈에서 import)

# memory_config.json:
{
  "memory_type": "memmachine",
  "memory_params": { ... }   # example_memory_config.json 참고
}

# upstream harness:
python -m evaluation.harness \
    --memory-config-path /tmp/memmachine.json \
    --domain web --tier small ...
```

upstream `MEMORY_TYPES` 레지스트리에 `memmachine` 이 등록되어 자동 인식.

## 트러블슈팅

- `Missing JSONL file: <data_root>/questions.jsonl` → `--data-root` 경로 오타,
  혹은 upstream `data/download_data.py` + `prepare_data.py` 미실행.
- `No questions found for domain=web` → 데이터셋이 enterprise 전용일 수 있음.
  `--domain enterprise` 시도.
- `MemMachineMemory.query requires set_query_context(haystack=...)` →
  haystack 파일 (`haystacks/lme_v2_<tier>.json`) 에 해당 question_id 가
  없음. 데이터셋 일관성 확인.
- Neo4j 적재 후 다른 실험과 충돌 → `--session-prefix` 만 바꾸면 같은 Neo4j
  안에서 격리 공존. cleanup 은 `MATCH (n {session_id: "<prefix>_*"}) DETACH DELETE n`
  Cypher 직접 실행하거나 `docker compose down -v` 로 전체 초기화.
