# mock_inference

OpenAI 임베딩 API(`/v1/embeddings`)와 Cohere/vLLM rerank API(`/v2/rerank`, `/v1/rerank`, `/rerank`) 형식으로 응답하는 mock 서버다. 모델 대신 미리 변환해 둔 데이터셋 벡터(`.npy`)를 순서대로 내주므로, 부하 시험에서 임베더와 리랭커를 GPU 없이 대체한다. 처음 쓰는 사람은 명령을 하나씩 따라가는 [사용 가이드](../../docs/msr/mock_inference/guide_2026-09-29.md)부터 본다. 설계와 판단 근거는 [설계 문서](../../docs/msr/mock_inference/design_2026-09-29.md), 로컬 드라이런 결과는 [검증 문서](../../docs/msr/mock_inference/verification_2026-09-29.md)에 있다.

## 설치

```bash
python3 -m venv ~/mock_venv && . ~/mock_venv/bin/activate
pip install -e "tools/mock_inference[checks]"   # 서버만 쓰면 [checks] 없이
ulimit -n 65536
python -m mock_inference --help                 # convert, serve, info, synth, synth-parquet
```

## 변환: parquet를 `.npy` 하나로

```bash
python -m mock_inference convert \
  --parquet-glob "/data/laion_large_100m/train-*-of-100.parquet" \
  --out /data/vectors/laion_100m.npy --jobs 10
python -m mock_inference info /data/vectors/laion_100m.npy
```

벡터 열은 자동으로 찾는다(`list<float32|float64>`인 첫 열). 중단 후 같은 명령을 다시 실행하면 끝난 파일은 건너뛰고, 끝나면 표본 100행을 원본과 대조한다. 처음부터 다시 하려면 `<out>`, `<out>.done/`, `<out>.plan.json`을 지운다(글롭이나 `--rows`가 바뀌어 계획이 달라지면 변환기가 이를 요구한다).

## 실행

```bash
python -m mock_inference serve --vectors /data/vectors/laion_100m.npy --target-rps 10000 --cores 0-11
curl -s http://MOCK_HOST:8000/health
```

- worker 수는 `--target-rps`에서 계산하거나 `--workers`로 직접 준다. `--cores`는 Linux에서만 적용된다.
- 진행 위치는 `.npy` 옆의 `<이름>.state.json`, `<이름>.state.lock`에 남고(`--state-dir`로 옮길 수 있다) 재시작해도 이어진다. 이 파일들을 쓸 수 있는 디렉터리인지 미리 확인한다(서비스 계정으로 돌릴 때는 특히). **새 시험 전에는 서버를 멈추고 `python -m mock_inference reset --vectors ...`를 실행해** 처음 행부터 다시 내주게 한다.
- 같은 텍스트에 항상 같은 벡터가 필요하면 `--mode hash`, 호스트를 여럿 두면 `--range START:END`.
- MemMachine 쪽 설정은 `checks/mm_mock_config.yml`을 참고한다. 임베더 `base_url`은 `/v1`까지, 리랭커 `base_url`은 호스트까지만 적는다.

## 검사

```bash
python checks/sdk_roundtrip.py --base http://MOCK_HOST:8000 --vectors VECTORS.npy
python checks/stream_check.py --base http://MOCK_HOST:8000 --vectors VECTORS.npy --clients 64 --total 100000 --out run1.json
<speedkick venv>/bin/python checks/mm_resource_check.py --config checks/mm_mock_config.yml --health http://MOCK_HOST:8000/health
```

`sdk_roundtrip`은 openai와 cohere SDK로 왕복해 받은 벡터가 `.npy`의 행과 바이트 단위로 같은지, `stream_check`는 여러 worker가 한 행을 두 번 주지 않는지(`--after 이전결과.json`이면 재시작 뒤 이어가는지), `mm_resource_check`는 MemMachine의 리소스 매니저가 DB 없이 mock 임베더와 리랭커를 검증하는지 본다. 처리량은 `oha`로 잰다(설계 문서 §13). systemd 배포는 `deploy/mock-inference.service`를 쓴다.
