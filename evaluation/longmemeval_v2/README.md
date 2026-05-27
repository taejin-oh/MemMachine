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
| `example_configuration.yml` | MemMachine working configuration.yml 템플릿 |
| `example_memory_config.json` | V2 memory backend config (memmachine type) 예시 |

## 의존성

```
이 디렉토리 ── memmachine_server.*  (워크스페이스 패키지)
            └─ upstream V2 코드 (`memory_modules/memory.py`, `no_retrieval.py`
                                  만 vendored — 우리 디렉토리에 직접 복사됨)
```

`evaluation/longmemeval/` (V1), `evaluation/retrieval_agent/`,
`evaluation/utils/`, `scripts/` 어디도 import 안 함.

## 데이터 준비

LongMemEval-V2 데이터셋은 [HuggingFace](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2)
에서 받음 (V2 upstream README 참고):

```bash
# upstream V2 의 data/download_data.py 를 직접 사용 (이 저장소엔 vendor 안 함)
git clone https://github.com/xiaowu0162/LongMemEval-V2 /tmp/lmev2
python /tmp/lmev2/data/download_data.py --data-root /tmp/lmev2-data
python /tmp/lmev2/data/prepare_data.py --data-root /tmp/lmev2-data --mode symlink

# 이후 우리 코드의 --data-root 에 /tmp/lmev2-data 를 전달
```

데이터 구조 (준비 후):
```
<data_root>/
  questions.jsonl              # {id, domain, category, question, answer, ...}
  trajectories.jsonl           # {id, goal, start_url, actions, states[]}
  haystacks/
    lme_v2_small.json          # question_id → [trajectory_id, ...]
    lme_v2_medium.json
  screenshots/<traj_id>/<step>.png  # multimodal (현재 텍스트만 사용)
```

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
PREFIX=lmev2_smoke              # 실험 이름 = session_prefix = 결과 dir
DATA=/tmp/lmev2-data            # 위에서 준비한 V2 dataset 경로
LIMIT="--limit 2"               # 스모크 2 문항. 풀 런 시 LIMIT=""
```

### 단일 명령 (ingest → retrieve → generate → judge)

```bash
uv run python -m evaluation.longmemeval_v2.run_eval \
    --data-root $DATA \
    --domain web \
    --tier small \
    --memmachine-configuration-path evaluation/longmemeval_v2/configuration.yml \
    --session-prefix $PREFIX \
    --top-k 50 \
    --output-dir results/$PREFIX \
    $LIMIT
```

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
