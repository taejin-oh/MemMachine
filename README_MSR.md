# README_MSR

## 변경 사항

- `evaluation/retrieval_agent/longmemeval_test.py`의
  `longmemeval_search()` 루프에서 질문 문자열을 읽은 뒤,
  YAML 설정값에 따라 `User: ` 접두어를 자동으로 붙일 수 있도록
  기능을 추가했습니다.
- 기본값은 `false`이며, 설정이 없거나 타입이 올바르지 않으면
  접두어를 붙이지 않습니다.

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

```bash
uv run python evaluation/retrieval_agent/longmemeval_test.py \
  --run-type search \
  --test-target retrieval_agent \
  --config-path /path/to/configuration.yml \
  --length 100
```

위 실행에서 `prepend_user_prefix: true`로 설정하면,
각 샘플 질문은 내부적으로 `User: ` 접두어가 붙은 상태로
`process_question`에 전달됩니다.
