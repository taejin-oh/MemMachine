# README_MSR

## 변경 사항

- `evaluation/retrieval_agent/longmemeval_test.py`의
  `longmemeval_search()` 루프에서 질문 문자열을 읽은 뒤,
  YAML 설정값에 따라 `User: ` 접두어를 자동으로 붙일 수 있도록
  기능을 추가했습니다.
- 기본값은 `false`이며, 설정이 없거나 타입이 올바르지 않으면
  접두어를 붙이지 않습니다.
- `evaluation/retrieval_agent/longmemeval_test.py`에
  `--search-limit` 옵션을 추가했습니다.
  - 기본값은 `20`이며, 옵션 미입력 시 기존과 동일하게 동작합니다.
  - LongMemEval 검색 시 질문당 최대 retrieval episode 수(k)를 조절할 수 있습니다.
- `evaluation/retrieval_agent/run_test.sh`에
  `--search-limit` 전달 로직을 추가했습니다.
  - `longmemeval`의 `search` 실행에서만 허용됩니다.
  - 양의 정수만 허용합니다.
- `evaluation/retrieval_agent/run_benchmark_matrix.sh`에서
  LongMemEval 실행 시 chunk on/off 토글을 자동 반영하도록 확장했습니다.
  - 변경 대상 YAML 키:
    `episodic_memory.long_term_memory.message_sentence_chunking`
  - 기존 prefix 토글(`evaluation.longmemeval.prepend_user_prefix`)과 함께
    조합 매트릭스로 실행됩니다.

## 설정 방법

`configuration.yml`(또는 `--config-path`로 전달하는 YAML)에
아래 섹션을 추가하세요.

```yaml
evaluation:
  longmemeval:
    prepend_user_prefix: true
```

- `true`: 질문을 `User: {question}` 형태로 변환 후 검색/응답 처리
- `false`(기본): 기존과 동일하게 질문 원문을 그대로 사용

## 사용 예시

### 1) longmemeval_test.py 직접 실행

```bash
uv run python evaluation/retrieval_agent/longmemeval_test.py \
  --run-type search \
  --test-target retrieval_agent \
  --config-path /path/to/configuration.yml \
  --length 100 \
  --search-limit 50
```

위 실행에서 `prepend_user_prefix: true`로 설정하면,
각 샘플 질문은 내부적으로 `User: ` 접두어가 붙은 상태로
`process_question`에 전달됩니다.

또한 `--search-limit 50`을 지정하면 질문당 최대 50개 episode까지
retrieval 대상이 됩니다. (`--search-limit` 미지정 시 기본 20)

### 2) run_test.sh로 실행

```bash
cd evaluation/retrieval_agent
./run_test.sh longmemeval exp_k50 ingest longmemeval_s_cleaned retrieval_agent 500
./run_test.sh longmemeval exp_k50 search longmemeval_s_cleaned retrieval_agent 500 --search-limit 50
```

- 위 예시는 LongMemEval 500개를 대상으로 ingest/search를 수행하며,
  search 단계에서 k=50으로 실행합니다.
- k sweep은 `--search-limit` 값만 바꿔 반복 실행하면 됩니다.
  - 예: `10`, `20`, `30`, `50`, `100`

### 3) 전체 경우의 수를 한 번에 실행

아래 스크립트를 추가했습니다.

- `evaluation/retrieval_agent/run_benchmark_matrix.sh`

이 스크립트는 다음 매트릭스를 한 번에 실행합니다.

- LongMemEvalS: `chunk {off,on}` × `prefix {off,on}` × `k {10,20,30,50,100}` (length=500, target=retrieval_agent)
- LoCoMo: `mode {memmachine,retrieval_agent}`
- HotpotQA(validation): `mode {memmachine,retrieval_agent}` (length=500)

실행:

```bash
cd evaluation/retrieval_agent
./run_benchmark_matrix.sh
```

실행 전 커맨드 확인(실행 안 함):

```bash
cd evaluation/retrieval_agent
./run_benchmark_matrix.sh --dry-run
```

ingest 생략 후 search만 실행:

```bash
cd evaluation/retrieval_agent
./run_benchmark_matrix.sh --skip-ingest
```

요약 로그 파일 경로 지정:

```bash
cd evaluation/retrieval_agent
./run_benchmark_matrix.sh --summary-path ./result/my_matrix_run.log
```

동작 방식:

- 내부적으로 기존 `run_test.sh`를 그대로 재사용합니다.
- LongMemEval prefix on/off는 `configuration.yml`의
  `evaluation.longmemeval.prepend_user_prefix` 값을 스크립트가 변경해서 처리합니다.
- LongMemEval chunk on/off는 `configuration.yml`의
  `episodic_memory.long_term_memory.message_sentence_chunking` 값을 스크립트가 변경해서 처리합니다.
- 실행 종료 시 원래 `configuration.yml` 내용으로 자동 복구합니다.
- 기본적으로 실행 커맨드/상태를 `evaluation/retrieval_agent/result/matrix_run_<UTC시간>.log`에 저장합니다.

### chunk 토글 사용 시 주의사항

- `message_sentence_chunking` 값이 바뀌면 ingest 결과가 달라집니다.
  따라서 `chunk=off`와 `chunk=on` 비교를 할 때는 ingest를 각각 수행해야 합니다.
- `--skip-ingest` 옵션은 동일한 ingest 상태를 재사용할 때만 사용하세요.
  chunk 값을 바꾸는 실험에서는 `--skip-ingest`를 권장하지 않습니다.

---

## STM 요약 생성 선택적 비활성화 (`summarization_enabled`)

STM(Short-Term Memory)을 끄지 않고, **용량 초과 시 LLM 요약 생성만**
선택적으로 끌 수 있도록 설정 키를 추가했습니다.

- 설정 키: `episodic_memory.short_term_memory.summarization_enabled`
- **서버 기본값: `true`** (`packages/server/.../episodic_config.py`,
  `short_term_memory.py`). 기존(pre-toggle) 동작 — 용량 초과 시 LLM 요약 생성 —
  을 그대로 보존하기 위함. 운영 서버에서 이 키를 명시하지 않으면 종전과 동일하게
  동작합니다.
- **eval-tool generated `configuration.yml` 의 emit 값: `false`**
  (`scripts/generate_config.py:build_configuration_yml`). 평가 비용/결정성을 위해
  eval-tool 이 명시적으로 `false` 를 yml 에 적습니다. 즉, eval-tool 로 생성한
  yml 을 서버가 그대로 읽으면 요약은 꺼진 상태로 시작합니다.
- 효과:
  - `false`: STM 용량 초과 시 오래된 메시지 evict는 계속 수행(메모리 bounded 유지),
    단 LLM 요약 생성은 수행하지 않음
  - `true`: 기존처럼 evict + 비동기 요약 생성 수행

### 두 default 의 관계 — 한 줄 요약

| 경로 | default | 의도 |
|---|---|---|
| 운영 서버 (직접 작성한 `configuration.yml`) | `true` | 기존 동작 보존 |
| eval-tool 이 생성하는 `configuration.yml` | `false` (명시 emit) | 평가 비용 절감 |

운영자가 직접 yml 을 쓰면 키 미지정 → 서버 default `true` 적용. eval-tool 로
생성하면 yml 에 `false` 가 명시되어 서버 default 와 무관하게 꺼짐. 두 경로가
같은 "default" 를 보지 않을 수 있다는 점만 인지하면 충돌 없음.

### 설정 예시 — 평가용 (요약 끔)

```yaml
episodic_memory:
  short_term_memory:
    llm_model: openai_model
    message_capacity: 500
    summarization_enabled: false   # 평가 시 비용 절감
```

### 설정 예시 — 운영 서버 (기존 동작 유지)

```yaml
episodic_memory:
  short_term_memory:
    llm_model: openai_model
    message_capacity: 500
    # summarization_enabled 미지정 → 서버 default true 적용
```

### 언제 false 가 맞나

- LLM 호출 비용을 줄이고 싶을 때 (평가 default)
- 요약 생성 지연/외부 의존성 없이 STM 최신 컨텍스트만 유지하고 싶을 때
- 메모리 제한은 유지하되(summary 없이) 빠른 evict 동작만 원할 때

### eval-tool 사용 시 주의

- eval-tool 의 LongMemEval 평가 경로는 `agent_utils.init_memmachine_params()`
  가 STM 자체를 `None` 으로 만들기 때문에 (`agent_utils.py:461`), 이 토글이
  LongMemEval 점수에는 영향이 없습니다. **본체 서버를 generated yml 그대로
  띄우는 경우에만** 토글이 실제 동작을 결정합니다.
- 따라서 eval-tool 의 `--summarization`, `fixed.summarization_enabled` 는
  config-only 로 분류되어 sweep 에서는 거부됩니다 (자세한 내용:
  `docs/msr/p4_eval_walkthrough_ko.md` §5b).

### 참고

- `summarization_enabled: false` 여도 STM 은 capacity 기반으로 계속 정리됩니다.
- 요약이 비활성화된 상태에서는 summary 컨텍스트가 비어 있게 됩니다.
