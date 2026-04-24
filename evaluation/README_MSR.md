# MSR 재현 설정 가이드 (message_sentence_chunking on/off)

이 문서는 재현 평가에서 `message_sentence_chunking` 값을 YAML로
on/off 제어하는 방법을 설명합니다.

## 1) 무엇이 바뀌었나

`evaluation/utils/agent_utils.py`의 `init_memmachine_params()`가
`message_sentence_chunking` 값을 다음 우선순위로 해석합니다.

1. 함수 인자로 명시 전달된 값 (`True`/`False`)
2. 인자가 없으면 `configuration.yml`의  
   `episodic_memory.long_term_memory.message_sentence_chunking`

즉, 기본 실행에서는 YAML 값으로 제어할 수 있습니다.

## 2) 설정 위치

`evaluation/retrieval_agent/configuration.yml`에서 아래 키를 사용합니다.

```yaml
episodic_memory:
  long_term_memory:
    message_sentence_chunking: true  # 또는 false
```

## 3) 후보별 권장값 예시

- #4/#12 (Adaptive k): `true`
- #3 (User/Assistant bias): `false` (기본값 유지)

## 4) 실행 예시

`evaluation/retrieval_agent/` 경로에서:

```bash
./run_test.sh locomo exp1 ingest retrieval_agent
./run_test.sh locomo exp1 search retrieval_agent
```

위 실행 시 `message_sentence_chunking`은 YAML 값을 따릅니다.

## 5) 참고

- 특정 실험에서 코드에서 인자를 명시 전달하면 YAML보다 우선합니다.
- 값 비교 실험 시 다른 조건(k, 모델, 데이터 길이)을 고정한 뒤
  `message_sentence_chunking`만 바꿔서 실행하세요.
