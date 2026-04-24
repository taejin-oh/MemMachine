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

- LongMemEvalS: `prefix {off,on}` × `k {10,20,30,50,100}` (length=500, target=retrieval_agent)
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
- 실행 종료 시 원래 `configuration.yml` 내용으로 자동 복구합니다.
- 기본적으로 실행 커맨드/상태를 `evaluation/retrieval_agent/result/matrix_run_<UTC시간>.log`에 저장합니다.
