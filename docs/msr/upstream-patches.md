# Upstream 적용용 패치 (docs/msr/*.patch)

`adaptive-k` 브랜치의 변경을 **upstream main 코드에 바로 적용**할 수 있게 만든
3 개의 `git diff` 패치. 모두 base = `main` (`6b1988b`) 기준으로 생성됐고,
깨끗한 main 트리에 적용되는지 검증 완료(아래 "드라이런 결과").

| 패치 | 내용 | main 기준 | 의존성 |
|---|---|---|---|
| `upstream-adaptive-k.patch` | adaptive-k 검색 동작 (코어 2 파일 **수정**) | 기존 파일 edit | — (자기완결) |
| `upstream-longmemeval.patch` | V1 LongMemEval 평가 도구 (디렉토리 **신규**) | `evaluation/longmemeval/` 9 파일 신규 | **adaptive-k 패치 필요** |
| `upstream-longmemeval-v2.patch` | V2 평가 도구 (디렉토리 **신규**) | `evaluation/longmemeval_v2/` 11 파일 신규 | 독립 |

## 무엇을 바꾸나

### 1. `upstream-adaptive-k.patch` — 코어 동작 변경 (필수 수정)
upstream main 에 **이미 존재하는** 2 파일만 수정. 새 파일·디렉토리·의존성 없음.
- `packages/server/src/memmachine_server/retrieval_agent/common/agent_api.py`
  → `adaptive_k_cutoff()` 함수 + `QueryParam` 필드 4 개(`adaptive_k`,
  `adaptive_k_min`, `adaptive_k_max`, `adaptive_k_bias`) 추가
- `packages/server/src/memmachine_server/retrieval_agent/agents/memmachine_retriever.py`
  → `do_query` 안에서 점수 gap 기반 cut 적용(`_apply_adaptive_k`)

전제: `EpisodeResponse.score` / `query_memory` 의 score 배선은 upstream main 에
**이미 있음**(확인함) → 추가로 가져올 파일 없음. 기본 `adaptive_k=False` 라 켜기
전엔 기존 동작과 100% 동일.

### 2. `upstream-longmemeval.patch` — V1 평가 도구 (디렉토리 신규)
`evaluation/longmemeval/` 전체(ingest/retrieve/generate/judge/…). `memmachine_server.*`
만 의존. **단, `retrieve.py` 가 `QueryParam.adaptive_k` 를 사용** → 이 패치를 쓰려면
`upstream-adaptive-k.patch` 를 **먼저** 적용해야 한다(순서 중요).

### 3. `upstream-longmemeval-v2.patch` — V2 평가 도구 (디렉토리 신규)
`evaluation/longmemeval_v2/` 전체(upstream V2 `Memory` ABC 위의 MemMachine 어댑터).
adaptive-k 와 **무관·독립** — 단독 적용 가능.

## 적용 방법

upstream MemMachine repo 루트에서:

```bash
# 0) 먼저 적용 가능한지 검사 (실제 변경 안 함)
git apply --check docs/msr/upstream-adaptive-k.patch

# 1) 코어 adaptive-k (필수)
git apply docs/msr/upstream-adaptive-k.patch

# 2) V1 평가 도구 (adaptive-k 다음에)
git apply docs/msr/upstream-longmemeval.patch

# 3) V2 평가 도구 (독립 — 순서 무관)
git apply docs/msr/upstream-longmemeval-v2.patch
```

> 패치 파일을 upstream repo 로 복사해서 쓰거나, 이 repo 의 경로를 절대경로로 지정:
> `git apply --check /path/to/docs/msr/upstream-adaptive-k.patch`

조합 예:
- **기능만** upstream 에 → `upstream-adaptive-k.patch` 하나면 끝.
- **V1 으로 검증까지** → adaptive-k → longmemeval.
- **V2 평가** → v2 단독(또는 adaptive-k 와 무관하게 함께).

## 드라이런 결과 (검증 완료)

깨끗한 `main`(`6b1988b`) 워크트리에서:

```
git apply --check upstream-adaptive-k.patch       → ✅ APPLIES CLEAN
git apply --check upstream-longmemeval.patch      → ✅ APPLIES CLEAN
git apply --check upstream-longmemeval-v2.patch   → ✅ APPLIES CLEAN
```

3 개 모두 실제 적용 후 핵심 파일 `py_compile` 통과(agent_api.py,
memmachine_retriever.py, longmemeval/retrieve.py, longmemeval_v2/run_eval.py,
memory_modules/memmachine.py). 적용된 agent_api.py 에 `adaptive_k_cutoff` +
`adaptive_k_bias` 존재 확인.

> 검증 범위: 패치가 **깨끗하게 적용되고 문법적으로 유효**함까지. 라이브 백엔드
> (Neo4j/Postgres) e2e 실행은 별도(사용자 환경).

## 재생성 방법 (base 갱신 시)

```bash
git diff main..adaptive-k -- \
  packages/server/src/memmachine_server/retrieval_agent/common/agent_api.py \
  packages/server/src/memmachine_server/retrieval_agent/agents/memmachine_retriever.py \
  > docs/msr/upstream-adaptive-k.patch
git diff main..adaptive-k -- evaluation/longmemeval/    > docs/msr/upstream-longmemeval.patch
git diff main..adaptive-k -- evaluation/longmemeval_v2/ > docs/msr/upstream-longmemeval-v2.patch
```
