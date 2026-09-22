# 벡터 데이터 다운로드 실행 가이드

- 작성일: 2026-09-21
- 상태: **실행용 런북.** 이 문서는 선택을 마쳤고, 명령을 그대로 복사해 붙여 넣으면 받아지도록 쓴 것이다
- 관련 문서: `dataset_options_2026-09-17.md`(선택지 조사), `design_2026-09-17.md` 4.5절(데이터 준비), `emulator_spec_2026-09-21.md` 3.3절(세션 수와 세션 크기 분포 파라미터)
- 검증 시각: 2026-09-21. 이 문서의 **모든 URL과 바이트 수는 작성 당일 직접 요청해 확인**했으며, 확인하지 못한 것은 7장에 따로 모았다
- 단계 구조에서의 위치: 이 문서는 확정된 단계 구조의 **2번 "데이터셋 받기"(2.1 라이선스 확인, 2.2 받기, 2.3 검증)** 에 해당한다. 2.1 라이선스 확인은 7.1절이고 **2.2 받기보다 먼저 끝나야 한다.** 2.2 받기는 2장부터 5장까지이고, 2.3 검증은 6장이다. 세션 분할과 Qdrant 적재는 이 문서의 범위가 아니라 3번 부하 도구의 적재기(3.2) 몫이다

> 앞 문서(`dataset_options_2026-09-17.md`)는 스물다섯 가지 방법을 늘어놓기까지가 범위였고 선택을 하지 않았다. 이 문서는 그 조사 위에서 **하나를 고르고 받는 절차**만 남긴 것이다. 후보 비교가 다시 필요하면 앞 문서를 보면 된다.

---

## 1. 요약

**주 데이터는 Zilliz VectorDBBench의 `laion_large_100m`으로 정한다.** 이유는 세 가지다. 첫째, 목표 규모인 포인트 1억 개를 목표 차원 중 하나인 768차원으로 정확히 제공하면서 다운로드가 212.3GB에 그치는 유일한 후보이고, 계정도 토큰도 필요 없이 익명으로 받아진다. 둘째, 전수 비교로 구한 정답이 top-1000, top-100K, top-1M 세 폭으로 이미 들어 있고 필터 조건별 정답까지 함께 있어서 리콜 검증 코드를 우리가 정답을 만들지 않고도 바로 돌릴 수 있다. 셋째, 벡터가 이미 L2 정규화되어 있음을 이번에 직접 확인했고, 1억 개를 768차원 float32로 올리면 벡터만 307.2GB라 RAM 1TB 안에 HNSW 그래프와 payload를 얹을 여유가 남는데, 1536차원이나 2560차원을 1억 개로 가는 경로에는 이 여유가 없다.

**차원 스윕은 Zenodo Pes2o 2560차원으로 따로 돌린다.** 한 코퍼스에서 2560, 1536, 1024, 768을 MRL 절단으로 모두 만들 수 있는 경로이고, 39.7GB에 CC-BY-4.0으로 라이선스까지 명시된 유일한 후보다. 다만 규모가 829만 개라 1억 개 축에는 쓸 수 없으므로, **규모 축은 laion으로, 차원 축은 Pes2o로 나누어 보는 것**이 이 가이드의 기본 구도다.

| 용도 | 데이터셋 | 차원 | 포인트 | 다운로드 | 라이선스 | 정답 | 배포본 라벨 |
|---|---|---:|---:|---:|---|---|---|
| 스모크 | ann-benchmarks `sift-128-euclidean.hdf5` | 128 | 100만 | 525.1MB | 미확인 | 포함 | 없음 |
| 스모크(대안) | Zilliz `sift_small_500k` | 128 | 50만 | 95.5MB | 미명시 | 포함 | 없음 |
| **주 데이터** | **Zilliz `laion_large_100m`** | **768** | **1억** | **212.3GB** | **미명시** | **포함(3폭)** | **1억 전체 보유** |
| 차원 스윕 | Zenodo Pes2o `pes2o_corpus.npz` | 2560 | 829만 | 39.7GB | CC-BY-4.0 | 없음 | 없음 |
| 차원 스윕 1024차원 | Zilliz `bioasq_large_10m` | 1024 | 1000만 | 19.3GB | 미명시 | 포함 | scalar |
| 차원 스윕 1536차원 | Zilliz `openai_large_5m` | 1536 | 500만 | 44.9GB | 미명시 | 포함 | scalar |
| 테넌트 축(선택) | Zilliz `msmarco_v2_138M_parquet` | 1536 | 1억 3,836만 | 851.2GB | 미명시 | 포함(라벨별) | 10,025개 치우침 |
| 라벨 형식 참고 | Zilliz `cohere_large_10m/tenant_labels_1000x10k.parquet` | — | 1000만 | 47.6MB | 미명시 | — | 1,000 테넌트 균등 |

"배포본 라벨" 열은 **배포본 안에 라벨 파일이나 라벨 컬럼이 들어 있는가**만 뜻한다. 우리 실험의 세션 분할은 이 열과 무관하다. 세션 키는 부하 도구의 적재기(3.2)가 적재 시점에 배정하고, 세션 수와 세션 크기 분포는 `emulator_spec_2026-09-21.md` 3.3절의 파라미터다. 3.8절을 참조한다. 표의 용도 이름(스모크, 주 데이터, 차원 스윕)은 단계 구조의 2.2 받기에 적힌 이름과 같다.

스모크부터 차원 스윕까지 모두 받아도 원본 합계가 약 1.27TB이므로, 디스크 16TB에서는 Qdrant 색인 공간을 빼고도 여유가 크다.

**오늘 당장 할 일은 2장의 스모크 테스트를 돌리고, 3장의 주 데이터 다운로드를 백그라운드로 걸어 두는 것이다.**

---

## 2. 스모크 테스트용 소형 데이터

### 2.1 무엇을 왜 받는가

파이프라인 전체(다운로드, parquet 또는 HDF5 읽기, Qdrant 적재, 검색, 리콜 계산)를 몇 분 안에 한 바퀴 돌려 보기 위한 데이터다. 차원이 128이라 목표 차원과 맞지 않으므로 측정값 자체는 버리고, **코드가 끝까지 도는지만 확인하는 용도**다.

### 2.2 ann-benchmarks SIFT 받기

아래 명령은 표준 벤치마크 파일 하나를 받는다. base 벡터 100만 개, 질의 1만 개, 정답이 한 파일에 같이 들어 있다. 2026-09-21에 HTTP 200과 `content-length: 525128288`, `accept-ranges: bytes`를 직접 확인했고, 앞 8바이트가 HDF5 매직(`8948 4446 0d0a 1a0a`)임도 확인했다.

```bash
mkdir -p ~/vecdata/smoke && cd ~/vecdata/smoke

# 525,128,288 바이트. 100MB/s 기준 약 5초, 10MB/s 기준 약 1분.
curl -L --fail --retry 3 -C - -o sift-128-euclidean.hdf5 \
  "https://ann-benchmarks.com/sift-128-euclidean.hdf5"

ls -l sift-128-euclidean.hdf5   # 525128288 이 나와야 한다
```

받은 파일의 내용을 확인하는 명령이다. `train (1000000, 128)`, `test (10000, 128)`, `neighbors (10000, 100)`가 출력되면 정상이다.

```bash
python3 -m pip install --quiet h5py numpy
python3 - <<'PY'
import h5py, numpy as np
with h5py.File("sift-128-euclidean.hdf5") as f:
    for k in f.keys():
        print(k, f[k].shape, f[k].dtype)
    v = f["train"][:1000]
    print("L2 norm mean:", float(np.linalg.norm(v, axis=1).mean()))
PY
```

SIFT는 정규화되어 있지 않으므로 마지막 줄의 노름 평균은 1.0이 아니라 수백 대의 값이 나온다. 그것이 정상이다.

### 2.3 대안: Zilliz 계열로 스모크 테스트하기

주 데이터와 **완전히 같은 도구와 같은 parquet 스키마**로 연습하고 싶다면 Zilliz의 가장 작은 세트를 쓰는 편이 낫다. 3장의 명령을 그대로 축소한 것이라, 여기서 통과하면 주 데이터도 같은 코드로 통과한다. 두 파일의 바이트 수는 2026-09-21에 목록 조회로 확인했다.

```bash
mkdir -p ~/vecdata/smoke_zilliz && cd ~/vecdata/smoke_zilliz
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/sift_small_500k"

curl -L --fail -O "$B/train.parquet"   #  95,342,344 바이트
curl -L --fail -O "$B/test.parquet"    #     194,139 바이트
ls -l
```

---

## 3. 본 측정용 주 데이터 (Zilliz `laion_large_100m`)

### 3.1 이 데이터가 무엇인지

S3 버킷 `assets.zilliz.com`의 `benchmark/laion_large_100m/` 아래에 놓인 VectorDBBench의 LAION-100M 세트다. 인증이 필요 없고, 2026-09-21에 익명 목록 조회와 GET과 Range 요청이 모두 동작함을 확인했다.

이번에 직접 확인한 사실을 정리하면 다음과 같다. 프리픽스 전체는 객체 150개에 231,250,951,020바이트이고, 그중 base 벡터인 `train-00-of-100.parquet`부터 `train-99-of-100.parquet`까지 100개가 212,308,503,251바이트다. 샤드 하나를 열어 보니 행이 정확히 1,000,000개이고 row group이 3개이며 스키마가 `id: int64`와 `emb: large_list<float>`이고 첫 행의 `emb` 길이가 768이었다. 따라서 100개 샤드가 정확히 1억 개를 이룬다. 질의 파일 `test.parquet`는 2,117,238바이트에 768차원 벡터 1,000개이고, `neighbors.parquet`는 4,510,710바이트에 질의마다 top-1000 이웃 id를 담고 있다.

**정규화 상태를 이번에 직접 확인했다.** `test.parquet`의 벡터 1,000개를 모두 읽어 L2 노름을 계산한 결과 최소 0.999474, 최대 1.000519, 평균 0.999995였다. 즉 이 데이터는 **이미 L2 정규화되어 있으므로 전처리가 필요 없다.** 앞 문서가 여러 후보에 대해 미확인으로 남겨 둔 항목 하나가 여기서 해소된 것이다.

### 3.2 왜 이것을 골랐는가

요건과 하나씩 맞춰 보면 이렇다. 포인트 1억 개라는 목표를 다른 어떤 후보보다 싸게(212.3GB) 정확히 채우고, 768차원이라 목표 차원 네 가지 중 하나를 원본 그대로 만족한다. RAM 1TB 제약 아래에서 1억 개를 올릴 수 있는 차원은 사실상 768과 1024뿐인데(앞 문서 5장 기준 1억 개 float32 보관량이 768차원 307.2GB, 1024차원 409.6GB, 1536차원 614.4GB, 2560차원 1,024GB다), 그중 정답과 라벨이 함께 배포되는 것은 이 세트뿐이다. 그리고 정답을 우리가 만들지 않아도 되는 점이 일정에 직접 도움이 된다.

### 3.3 먼저 목록을 확인한다

무엇을 받을지 눈으로 보고 시작하는 것이 안전하다. 아래는 인증 없이 목록을 조회해 파일 이름과 바이트 수를 출력한다. `train-00-of-100.parquet`부터 99까지가 각각 21억 바이트대로 찍히면 정상이다.

```bash
curl -s "https://s3.us-west-2.amazonaws.com/assets.zilliz.com?list-type=2&prefix=benchmark/laion_large_100m/&max-keys=400" \
| python3 -c "
import sys, re
x = sys.stdin.read()
rows = re.findall(r'<Key>(.*?)</Key>.*?<Size>(\d+)</Size>', x, re.S)
tot = 0
for k, s in rows:
    tot += int(s)
    print(f'{int(s):>15,}  {k.split(\"/\")[-1]}')
print(f'--- {len(rows)} objects, {tot:,} bytes ({tot/1e9:.1f} GB)')
"
```

이 프리픽스에는 `README.md`(6,366바이트)가 들어 있고, 파일 목록과 필터별 정답의 구성, 그리고 large-top-K 산출물에 대한 SHA-256이 적혀 있다. 받기 전에 한 번 읽어 두면 좋다.

```bash
curl -s "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/README.md"
```

### 3.4 먼저 속도를 잰다

전체를 걸기 전에 샤드 하나만 받아 실제 대역폭을 재는 것이 중요하다. 이 값이 있어야 전체 소요 시간을 추정할 수 있다. 아래 명령은 첫 샤드(2,123,160,971바이트)를 받으면서 속도를 출력한다.

```bash
mkdir -p ~/vecdata/laion100m && cd ~/vecdata/laion100m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m"

curl -L --fail -o train-00-of-100.parquet "$B/train-00-of-100.parquet" \
  -w "bytes=%{size_download} time=%{time_total}s speed=%{speed_download} B/s\n"
```

출력된 `speed_download`를 아래 표에 대입하면 전체 시간이 나온다. 참고로 작성자의 맥북에서 잰 값은 약 2.7MB/s였으나, 이것은 노트북의 가정용 회선에서 잰 것이므로 **측정 서버의 값과는 무관하다.** 반드시 서버에서 다시 재야 한다.

| 대상 | 바이트 | 50MB/s | 200MB/s | 500MB/s |
|---|---:|---:|---:|---:|
| train 100개(1억 개 전체) | 212,308,503,251 | 약 1시간 11분 | 약 18분 | 약 7분 |
| train 10개(1000만 개) | 약 21,231,000,000 | 약 7분 | 약 2분 | 약 42초 |
| `scalar_labels.parquet` | 590,420,586 | 약 12초 | 약 3초 | 약 1초 |
| `test.parquet` + `neighbors.parquet` | 6,627,948 | 1초 미만 | 1초 미만 | 1초 미만 |

### 3.5 작은 것부터 받는다 (질의, 정답, 라벨)

벡터 본체를 받기 전에 질의와 정답과 라벨을 먼저 받는 편이 좋다. 아래 여섯 개의 합계가 674,353,243바이트라 1분 안에 끝나고, 이것만 있으면 적재 코드와 검증 코드를 미리 다 짜 둘 수 있다.

```bash
cd ~/vecdata/laion100m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m"

for f in README.md test.parquet neighbors.parquet test_nq200.parquet \
         neighbors_top100k_nq200.parquet scalar_labels.parquet ; do
  curl -L --fail --retry 3 -C - -o "$f" "$B/$f" \
    -w "%{http_code}  %{size_download} bytes  $f\n"
done
```

각 줄이 `200`으로 시작하고 바이트 수가 아래와 맞으면 정상이다. 이 값들은 2026-09-21에 목록 조회로 확인한 것이다.

| 파일 | 바이트 | 내용 |
|---|---:|---|
| `README.md` | 6,366 | 파일 목록과 SHA-256 |
| `test.parquet` | 2,117,238 | 질의 벡터 1,000개(768차원) |
| `neighbors.parquet` | 4,510,710 | 질의별 top-1000 정답 id |
| `test_nq200.parquet` | 337,550 | 질의 앞 200개 |
| `neighbors_top100k_nq200.parquet` | 76,960,793 | 질의 200개에 대한 top-100K 정답 |
| `scalar_labels.parquet` | 590,420,586 | 1억 개 전체의 라벨 |

### 3.6 본체 받기 — 방법 A: `aws` CLI (권장)

AWS CLI는 `--no-sign-request`로 인증 없이 이 버킷을 읽을 수 있고, 재시도와 병렬 전송을 알아서 한다. 작성자의 맥에는 `aws`가 설치되어 있지 않았으므로 먼저 설치해야 한다.

```bash
# macOS
brew install awscli
# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y awscli
# 또는 공식 번들
# curl -sL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && unzip -q awscliv2.zip && sudo ./aws/install

aws --version
```

아래는 병렬 전송 폭을 넓힌 뒤 train 샤드만 통째로 받는다. `--exclude "*"`로 전부 끄고 `--include`로 필요한 것만 켜는 순서가 중요하다.

```bash
aws configure set default.s3.max_concurrent_requests 16
aws configure set default.s3.multipart_chunksize 64MB

cd ~/vecdata/laion100m
aws s3 cp --no-sign-request --recursive \
  s3://assets.zilliz.com/benchmark/laion_large_100m/ . \
  --exclude "*" --include "train-*-of-100.parquet"
```

**먼저 1000만 개만 받아 보고 싶다면** 샤드 10개로 범위를 좁힌다. 21.2GB라 훨씬 빨리 끝나고, 적재와 색인 절차를 전체 규모 전에 검증할 수 있다.

```bash
aws s3 cp --no-sign-request --recursive \
  s3://assets.zilliz.com/benchmark/laion_large_100m/ . \
  --exclude "*" --include "train-0[0-9]-of-100.parquet"
```

### 3.7 본체 받기 — 방법 B: `curl` + `xargs` 병렬 (설치 불필요)

`aws`를 설치할 수 없는 환경이라면 curl만으로도 된다. 아래는 8개를 동시에 받고, `-C -`로 중단 지점부터 이어받으며, 실패하면 재시도한다. 같은 명령을 다시 돌리면 이미 받은 파일은 건너뛰거나 이어받으므로 안전하게 반복할 수 있다.

```bash
cd ~/vecdata/laion100m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m"

seq -w 0 99 | xargs -P 8 -I{} sh -c \
  'curl -sL --fail --retry 5 --retry-delay 3 -C - \
     -o "train-{}-of-100.parquet" "'"$B"'/train-{}-of-100.parquet" \
   && echo "done {}" || echo "FAIL {}"'
```

`FAIL`이 찍힌 번호가 있으면 그 번호만 다시 돌리면 된다. 전부 끝난 뒤 파일 개수와 합계 바이트를 확인하는 명령이다. `100`과 `212308503251`이 나와야 한다.

```bash
ls train-*-of-100.parquet | wc -l
du -cb train-*-of-100.parquet | tail -1
# macOS에는 du -b 가 없으므로 아래를 쓴다
# stat -f%z train-*-of-100.parquet | awk '{s+=$1} END {print s}'
```

### 3.8 라벨을 어떻게 쓸 것인가

`scalar_labels.parquet`의 내부를 이번에 직접 열어 확인했다. 행이 100,000,000개이고 row group이 96개이며 스키마는 `id: int64`와 `labels: large_string`이다. 첫 row group(1,048,576행)을 복호해 보니 라벨이 74,928종이었고, 그 분포는 다음과 같았다.

| 라벨 | 첫 row group 내 비율 | 성격 |
|---|---:|---|
| `label_50p` | 49.933% | 선택도 50% |
| `label_20p` | 20.019% | 선택도 20% |
| `label_10p` | 10.036% | 선택도 10% |
| `label_5p` | 5.012% | 선택도 5% |
| `label_2p` | 2.004% | 선택도 2% |
| `label_1p` | 0.998% | 선택도 1% |
| `label_0.5p` | 0.493% | 선택도 0.5% |
| `label_0.2p` | 0.203% | 선택도 0.2% |
| `label_0.1p` | 0.102% | 선택도 0.1% |
| `filler_<숫자>` 다수 | 나머지 약 10% | 꼬리, 각각 포인트 수 극소 |

여기서 읽어야 할 것은 두 가지다. 첫째, 이름이 붙은 아홉 개 라벨은 **테넌트가 아니라 선택도(selectivity) 눈금**이다. 필터 선택도를 0.1%에서 50%까지 바꿔 가며 재는 실험에는 그대로 쓸 수 있고, 각 선택도마다 정답 파일(`neighbors_labels_label_*.parquet`)이 이미 있다. 둘째, `filler_` 라벨은 채움용이며, 서로 다른 row group에서 관측한 filler 번호가 0부터 2,715,626까지 흩어져 있었고 row group 사이 겹침이 적었으므로 전역 filler 종수는 수백만 규모로 보인다. 다만 **정확한 전역 종수는 세지 않았다.** 이 라벨들은 우리 실험의 세션 분할에 쓰지 않는다.

세션 수를 1개에서 10만 개까지 훑는 실험은 어느 공개 데이터로도 그대로 되지 않는다. 그래서 **세션 배정은 부하 도구의 적재기(3.2)가 적재 시점에 한다.** 적재기는 데이터 파일의 벡터를 Qdrant에 넣으면서 포인트마다 세션 키를 붙이고, 세션 수와 세션 크기 분포는 `emulator_spec_2026-09-21.md` 3.3절의 파라미터(`sessions`, `session_size_dist`)다. 기본 분포는 같은 문서의 zipf(s=1.0)다. **라벨 parquet 파일을 미리 만들어 두는 방식은 폐기했다.** 이 문서가 할 일은 벡터 본체와 질의와 정답을 받아 6장의 검증을 통과시키는 것까지이고, 세션 라벨 파일은 만들지 않는다.

Zilliz의 라벨 형식은 참고로만 확인해 두었다. `cohere_large_10m/tenant_labels_1000x10k.parquet`(47,585,198바이트)를 실제로 받아 열어 보니 행이 10,000,000개, row group이 82개, 스키마가 `id: int64`와 `labels: large_string`이었고, 테넌트가 정확히 1,000종에 각각 정확히 10,000개로 **완전히 균등**했으며 id는 섞여 있었다. 즉 이 파일은 치우친 세션 분포를 주지 않고, id 범위도 0부터 999만까지라 1억 개인 laion에 그대로 붙지 않는다. 적재기가 나중에 Zilliz 도구와 결과를 비교할 필요가 생기면 이 스키마를 따라 세션 키를 내보내면 된다.

---

## 4. 차원 스윕용 보조 데이터 (768 / 1024 / 1536 / 2560)

### 4.1 전체 구도

목표 차원 네 가지를 한 번에 만족하는 1억 개짜리 공개 데이터는 없다. 그래서 두 갈래로 나눈다. **규모 축(1억 개)은 3장의 laion 768차원으로 보고, 차원 축은 규모를 낮춰 네 차원을 모두 덮는다.** 차원 축에서 가장 깔끔한 것은 한 코퍼스에서 절단만으로 네 차원을 만드는 Pes2o다.

| 차원 | 데이터셋 | 포인트 | 다운로드 | 저장 형식 | 비고 |
|---:|---|---:|---:|---|---|
| 768 | Zilliz `laion_large_100m` | 1억 | 212.3GB | parquet float32 | 3장에서 이미 받음, 정규화 확인됨 |
| 1024 | Zilliz `bioasq_large_10m` | 1000만 | 19.3GB | parquet float32 | 같은 도구로 바로 받힘 |
| 1536 | Zilliz `openai_large_5m` | 500만 | 44.9GB | parquet **float64** | float32 변환 필요 |
| 2560 | Zenodo Pes2o | 829만 | 39.7GB | npz float32 | CC-BY-4.0 명시, MRL 절단 가능 |

### 4.2 1024차원: Zilliz `bioasq_large_10m`

이 프리픽스는 객체 32개에 19,587,025,008바이트이고, base 벡터는 `shuffle_train-00-of-10.parquet`부터 09까지 10개에 19,280,984,409바이트다(2026-09-21 확인). 샤드 하나를 열어 보니 행이 1,000,000개이고 스키마가 `id: int64`와 `emb: list<float>`였다. **이 프리픽스에는 `shuffle_train`만 있고 섞지 않은 `train`은 없다는 점**을 확인했으므로 파일 이름을 틀리지 않도록 주의해야 한다.

```bash
mkdir -p ~/vecdata/bioasq10m && cd ~/vecdata/bioasq10m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/bioasq_large_10m"

# 질의와 정답과 라벨 먼저 (합계 약 70MB)
for f in test.parquet neighbors.parquet scalar_labels.parquet ; do
  curl -sL --fail -O "$B/$f" && echo "ok $f"
done

# 본체 10개, 19.3GB. 200MB/s 기준 약 2분.
seq -w 0 9 | xargs -P 6 -I{} sh -c \
  'curl -sL --fail --retry 5 -C - -o "shuffle_train-{}-of-10.parquet" \
     "'"$B"'/shuffle_train-{}-of-10.parquet" && echo "done {}"'
```

### 4.3 1536차원: Zilliz `openai_large_5m`

이 프리픽스는 객체 55개에 90,042,426,177바이트다. train 계열이 20개인데, 섞지 않은 `train-00-of-10.parquet`부터 09까지 10개와 섞은 `shuffle_train-*` 10개가 따로 있고 각각 약 4.49GB다. **둘 다 받을 필요는 없으므로 한쪽만 받는다.**

샤드 하나를 열어 확인한 결과 행이 500,000개이고 스키마가 `id: int64`와 `emb: list<double>`이었다. 즉 **이 세트는 float64로 저장되어 있어 용량이 두 배**이고, Qdrant에 올리기 전에 float32로 바꾸는 편이 낫다. 500,000행에 파일이 4.49GB인 것도 float64 때문이다.

```bash
mkdir -p ~/vecdata/openai5m && cd ~/vecdata/openai5m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/openai_large_5m"

for f in test.parquet neighbors.parquet scalar_labels.parquet ; do
  curl -sL --fail -O "$B/$f" && echo "ok $f"
done

# 섞지 않은 본체 10개만. 약 44.9GB. 200MB/s 기준 약 4분.
seq -w 0 9 | xargs -P 6 -I{} sh -c \
  'curl -sL --fail --retry 5 -C - -o "train-{}-of-10.parquet" \
     "'"$B"'/train-{}-of-10.parquet" && echo "done {}"'
```

### 4.4 2560차원: Zenodo Pes2o (차원 스윕의 핵심)

Zenodo 레코드 17101276을 API로 조회해 2026-09-21에 확인한 내용이다. 라이선스가 `cc-by-4.0`으로 명시되어 있고, `pes2o_corpus.npz`가 39,748,381,931바이트에 MD5가 `f8c6c7e81facb8a4c8a6b2e9ee267f9f`다. 질의 파일은 `queries_v2.npz`가 94,836,415바이트, `queries_v1.npz`가 94,964,720바이트, `query_text.csv`가 2,089,719바이트다. Range 요청에 206을 돌려주는 것과 파일 앞 4바이트가 zip 매직(`504b 0304`)인 것도 확인했다.

이 데이터를 고른 이유는 **2560차원을 절단해 1536, 1024, 768을 같은 코퍼스에서 만들 수 있기 때문**이다. Qwen3-Embedding-4B가 32에서 2560까지 MRL을 지원한다는 점은 앞 문서 2.1절(방법 7)에 정리되어 있다. 다만 **이미 뽑아 둔 벡터를 잘라도 되는지는 여전히 검증되지 않은 가정**이므로 7장의 경고를 먼저 읽어야 한다.

먼저 메타데이터를 확인하는 명령이다. 파일 목록과 크기와 체크섬이 출력된다.

```bash
curl -s "https://zenodo.org/api/records/17101276" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('license:', d['metadata'].get('license'))
for f in d['files']:
    print(f\"{f['size']:>15,}  {f['key']}  {f.get('checksum')}\")
"
```

본체를 받는 명령이다. 39.7GB이므로 200MB/s 기준 약 3분 20초, 50MB/s 기준 약 13분이다.

```bash
mkdir -p ~/vecdata/pes2o && cd ~/vecdata/pes2o
Z="https://zenodo.org/records/17101276/files"

curl -L --fail --retry 3 -C - -o queries_v2.npz "$Z/queries_v2.npz?download=1"
curl -L --fail --retry 3 -C - -o query_text.csv "$Z/query_text.csv?download=1"
curl -L --fail --retry 3 -C - -o pes2o_corpus.npz "$Z/pes2o_corpus.npz?download=1" \
  -w "bytes=%{size_download} time=%{time_total}s\n"

md5 -q pes2o_corpus.npz 2>/dev/null || md5sum pes2o_corpus.npz
# f8c6c7e81facb8a4c8a6b2e9ee267f9f 이 나와야 한다
```

npz는 zip 컨테이너이므로 풀기 전에 내부 구성을 먼저 보는 것이 좋다. 앞 문서는 이 파일이 단일 deflate 멤버라 임의 행 접근이 안 된다고 적고 있으므로, 아래 출력으로 그 점을 직접 확인하게 된다.

```bash
python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("pes2o_corpus.npz")
for i in z.infolist():
    print(f"{i.filename:<30} compressed={i.compress_size:>15,} "
          f"raw={i.file_size:>15,} method={i.compress_type}")
PY
```

`method=0`이면 무압축이라 잘라 읽을 수 있고, `method=8`이면 deflate라 앞에서부터 순차로 풀어야 한다.

### 4.5 선택 사항: 1536차원을 1억 개 규모로 보려면

`msmarco_v2_138M_parquet`가 유일한 경로다. 2026-09-21에 확인한 값은 객체 299개에 852,018,132,378바이트이고, 그중 `msmarco_passage_*-*.parquet` 277개가 851,155,886,678바이트다. 이 숫자는 앞 문서가 적은 851,155,886,678과 정확히 일치한다.

이 프리픽스의 `README`를 직접 읽어 알아낸 것이 하나 있다. 이 세트는 행이 138,364,198개이고 파일당 500,000개이며 스키마가 `pk`, `label`(문자열), `float32_vector`인데, **`label`이 10,025종이고 분포가 의도적으로 치우쳐 있다.** 40%짜리 하나, 20%짜리 하나, 10%짜리 하나, 5%짜리 하나, 1%짜리 하나, 0.1%짜리 20개, 그리고 3,036개씩 들어 있는 작은 라벨 10,000개로 구성된다. 정답도 138M과 50M 두 규모에 대해 필터 없는 것과 라벨별로 나뉘어 제공된다.

즉 **테넌트 수가 1만 개 규모이면서 크기가 실제처럼 치우친 세션 구조를 합성 없이 얻을 수 있는 유일한 후보**다. 다만 852GB를 받아야 하고, 1억 개를 1536차원으로 올리면 벡터만 614.4GB라 RAM 1TB에서 여유가 크게 줄어든다. 일정상 지금 받을 것은 아니고, 세션 축을 실제 라벨로 보고 싶어질 때 꺼내 쓰는 카드로 남겨 둔다.

먼저 README만 읽어 보는 명령이다.

```bash
curl -s "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/msmarco_v2_138M_parquet/README"
```

일부만 받아 구조를 보려면 파일 두어 개와 정답만 받으면 된다. 합계 약 6GB다.

```bash
mkdir -p ~/vecdata/msmarco138m && cd ~/vecdata/msmarco138m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/msmarco_v2_138M_parquet"
curl -sL --fail -O "$B/query.npy"                 #  61,440,128 바이트, 질의 1만 개 x 1536
curl -sL --fail -O "$B/msmarco_passage_00-0.parquet"
curl -sL --fail -O "$B/msmarco_passage_00-1.parquet"
```

### 4.6 선택 사항: 1024차원을 1억 개 규모로 보려면

big-ann-benchmarks의 DINO가 유일하게 가볍다. uint8로 저장되어 있어 1억 개가 102.4GB에 그친다. **앞 문서에는 이 파일의 URL이 적혀 있지 않아 이번에 직접 찾았다.** 처음에 추측한 `comp21storage` 경로는 404를 돌려주었고, `big-ann-benchmarks`의 `benchmark/datasets.py` 1415행에서 실제 base URL이 `http://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/`임을 확인했다.

그 URL로 2026-09-21에 확인한 결과는 다음과 같다. `dino_vitl_1B_base.u8bin`이 HTTP 200에 1,024,000,000,008바이트이고 `Accept-Ranges: bytes`를 돌려준다. 앞 8바이트를 읽어 보니 개수가 1,000,000,000이고 차원이 1024였다. 질의 파일 `queries_clean.bvecs`는 102,800,000바이트이고, **1억 개 규모 전용 정답인 `gts_bin/gts_dino_patch_100000000_k100.bin`이 80,000,008바이트로 존재한다.** 반면 `dino_vitl_2B_base.u8bin`은 **오늘도 403**을 돌려주어 앞 문서의 관측이 그대로 유지된다.

부분 다운로드 명령은 5.3절에 있다.

---

## 5. 부분 다운로드 요령

전체를 받기 전에 일부만 받아 구조를 확인하는 것이 시간과 디스크를 가장 많이 아낀다. 형식마다 방법이 다르다.

### 5.1 Hugging Face parquet 샤드 단위로 받기

Hugging Face는 `hf download`(구 `huggingface-cli download`)의 `--include`로 원하는 샤드만 받을 수 있다. 작성자의 맥에는 설치되어 있지 않았으므로 먼저 설치한다. 익명 다운로드에 rate limit이 걸린 사례가 있으므로 토큰을 넣어 두는 편이 안전하다.

```bash
python3 -m pip install --quiet "huggingface_hub[cli]"
hf auth login    # 또는 export HF_TOKEN=hf_xxx
```

아래는 2026-09-21에 HF API로 공개 상태와 라이선스를 확인한 저장소들이다. 모두 `gated=False`였다.

| 저장소 | 라이선스(API 기준) | 비고 |
|---|---|---|
| `imageomics/TreeOfLife-200M-Embeddings` | `cc0-1.0` | 768과 1024가 행 단위 정렬 |
| `colonelwatch/abstracts-embeddings` | `cc0-1.0` | 1024차원 2억 680만 개 |
| `VDBBench/multimodal-embedding-100M` | `cc-by-4.0` | 4096차원 1억 개 |
| `andropar/relaion2b-natural-embeddings` | `cc-by-4.0` | 768차원 5억 1,400만 개 |
| `laion/Caselaw_Access_Project_embeddings` | `agpl-3.0` | 1536차원, 클러스터별 파일 |
| `CohereLabs/msmarco-v2.1-embed-english-v3` | **없음(`null`)** | 라이선스 필드가 비어 있다 |

샤드를 골라 받는 예시다. TreeOfLife의 768차원 config에서 앞 열 개만 받는다. 샤드 하나가 약 516MB이므로 합계 약 5.2GB다(`train-00000-of-00666.parquet`가 516,095,035바이트임을 API로 확인했다).

```bash
hf download imageomics/TreeOfLife-200M-Embeddings \
  --repo-type dataset --local-dir ~/vecdata/tol \
  --include "bioclip-2_float16/train-0000[0-9]-of-00666.parquet"
```

받기 전에 파일 목록과 크기만 보고 싶다면 API를 그대로 조회하면 된다.

```bash
curl -s "https://huggingface.co/api/datasets/colonelwatch/abstracts-embeddings/tree/main/data?limit=5" \
| python3 -c "
import json, sys
for e in json.load(sys.stdin):
    print(f\"{e.get('size',0):>15,}  {e['path']}\")
"
```

### 5.2 HTTP Range로 바이트 구간만 받기

Zilliz S3와 Hugging Face와 Zenodo 모두 Range 요청을 지원하는 것을 2026-09-21에 확인했다. 아래는 laion 샤드의 앞 1KiB만 받는 예시이고, 응답이 `206 Partial Content`와 `Content-Range: bytes 0-1023/2123160971`로 오는 것을 직접 확인했다.

```bash
curl -s --range 0-1023 -D - -o /dev/null \
  "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/train-00-of-100.parquet" \
| grep -iE "^HTTP|content-range|accept-ranges"
```

parquet는 메타데이터가 **파일 끝**에 있으므로, 행 수와 스키마만 알고 싶다면 뒤쪽만 받으면 된다. 아래 스크립트는 꼬리 4MB만 받아 footer를 해석한다. 파일 전체를 받지 않고도 행 수, row group 수, 컬럼 타입을 출력한다.

```bash
python3 -m pip install --quiet pyarrow
python3 - <<'PY'
import struct, io, urllib.request, sys
import pyarrow.parquet as pq

def footer_meta(url, tail=4_000_000):
    size = int(urllib.request.urlopen(
        urllib.request.Request(url, method="HEAD")).headers["Content-Length"])
    start = max(0, size - tail)
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{size-1}"})
    buf = urllib.request.urlopen(req).read()
    assert buf[-4:] == b"PAR1"
    flen = struct.unpack("<I", buf[-8:-4])[0]
    foot = buf[len(buf)-8-flen : len(buf)-8]
    blob = foot + struct.pack("<I", flen) + b"PAR1"
    return size, pq.read_metadata(io.BytesIO(blob))

B = "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/"
for name in ("train-00-of-100.parquet", "scalar_labels.parquet", "neighbors.parquet"):
    size, m = footer_meta(B + name)
    print(f"{name}: {size:,} bytes, rows={m.num_rows:,}, row_groups={m.num_row_groups}")
    print("   ", str(m.schema.to_arrow_schema()).replace("\n", "; "))
PY
```

이 스크립트를 실제로 돌려 얻은 출력은 다음과 같았고, 이 문서의 행 수와 스키마는 모두 여기서 나온 것이다.

```
train-00-of-100.parquet: 2,123,160,971 bytes, rows=1,000,000, row_groups=3
    id: int64; emb: large_list<item: float>;   child 0, item: float
scalar_labels.parquet: 590,420,586 bytes, rows=100,000,000, row_groups=96
    id: int64; labels: large_string
neighbors.parquet: 4,510,710 bytes, rows=1,000, row_groups=1
    id: int64; neighbors_id: large_list<item: int64>;   child 0, item: int64
```

### 5.3 big-ann `.bin` 헤더 잘라내기

big-ann 형식은 앞 8바이트가 개수(uint32)와 차원(uint32)이고 그 뒤로 벡터가 연속으로 놓인다. 따라서 **앞에서 N개만 받고 헤더의 개수만 다시 써 주면 그대로 유효한 파일**이 된다. big-ann 코드 자체가 이 방식으로 부분집합을 만든다.

먼저 헤더 8바이트만 읽어 개수와 차원을 확인한다. 아래 명령을 2026-09-21에 실행해 `npts=1,000,000,000 dim=1024`를 얻었다.

```bash
U="https://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/dino_vitl_1B_base.u8bin"
curl -s --range 0-7 "$U" | python3 -c "
import sys, struct
n, d = struct.unpack('<II', sys.stdin.buffer.read(8))
print(f'npts={n:,} dim={d}')
"
```

1억 개만 잘라 받는 명령이다. uint8이고 1024차원이므로 필요한 바이트는 헤더 8바이트에 100,000,000 × 1024를 더한 102,400,000,008바이트다. 받은 뒤 헤더의 개수를 1억으로 고쳐 쓴다.

```bash
mkdir -p ~/vecdata/dino && cd ~/vecdata/dino
U="https://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/dino_vitl_1B_base.u8bin"
OUT="dino_100M.u8bin"
N=100000000
END=$(( 8 + N * 1024 - 1 ))          # 102,400,000,007

# 102.4GB. 200MB/s 기준 약 9분. 처음 받을 때만 이 명령을 쓴다. -C - 는 붙이지 않는다.
curl -L --fail --retry 5 --range "0-$END" -o "$OUT" "$U" \
  -w "bytes=%{size_download}\n"

# 헤더의 개수 필드를 1억으로 고쳐 쓴다
python3 - <<PY
import struct
with open("$OUT", "r+b") as f:
    f.seek(0); f.write(struct.pack("<I", $N))
    f.seek(0); print("header now:", struct.unpack("<II", f.read(8)))
PY

# 질의와 1억 개 전용 정답도 받는다
BASE="https://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B"
curl -sL --fail -O "$BASE/queries_clean.bvecs"                      # 102,800,000 바이트
curl -sL --fail -o gts_dino_patch_100000000_k100.bin \
  "$BASE/gts_bin/gts_dino_patch_100000000_k100.bin"                 #  80,000,008 바이트
```

**`-C -`와 `--range`를 함께 쓰면 안 된다.** 둘을 같이 주면 curl은 `--range`의 구간을 버리고 현재 파일 크기를 시작점으로 한 끝이 없는 구간(`Range: bytes=<현재 크기>-`)을 보내므로, 1억 개에서 멈추지 않고 1TB 파일 끝까지 받게 된다. 그래서 위 명령에는 `-C -`를 붙이지 않았다. 중간에 끊겼다면 아래처럼 현재 파일 크기를 시작점으로 명시해 남은 구간만 받아 파일 뒤에 붙이고, 끝난 뒤 위 블록의 헤더 고쳐 쓰기부터 다시 실행한다. 파일이 없거나 크기를 읽지 못하면 아무것도 받지 않도록 가드를 두었고, 이어받기 도중 다시 끊기면 같은 블록을 한 번 더 돌리면 된다(`--retry`는 표준 출력에 덧붙이는 방식과 맞지 않아 일부러 뺐다).

```bash
cd ~/vecdata/dino
U="https://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/dino_vitl_1B_base.u8bin"
OUT="dino_100M.u8bin"
N=100000000
END=$(( 8 + N * 1024 - 1 ))          # 102,400,000,007

HAVE=$(stat -c %s "$OUT" 2>/dev/null)   # macOS 는 stat -f %z "$OUT"
if [ -z "$HAVE" ]; then
  echo "$OUT 이 없다. 처음 받는 명령을 쓴다"
elif [ "$HAVE" -gt "$END" ]; then
  echo "$OUT 은 이미 다 받았다 ($HAVE 바이트)"
else
  curl -L --fail --range "$HAVE-$END" "$U" >> "$OUT"
  ls -l "$OUT"                          # 102400000008 이 나와야 한다
fi
```

---

## 6. 받은 뒤 확인

이 장이 단계 구조의 **2.3 검증(행 수, 차원, 정규화, 체크섬)** 에 해당한다. 다운로드가 끝났다고 데이터가 멀쩡한 것은 아니다. 아래 네 가지를 순서대로 확인한다. 이 장을 통과해야 3번 부하 도구의 적재기(3.2)에 데이터를 넘길 수 있다.

### 6.1 바이트 수와 파일 개수

가장 먼저 볼 것이다. 잘린 파일은 parquet 읽기에서 엉뚱한 오류로 나타나므로 여기서 걸러 내는 편이 빠르다. 아래는 laion 100M 기준이며, `100 212308503251`이 나와야 한다.

```bash
cd ~/vecdata/laion100m
ls train-*-of-100.parquet | wc -l
python3 -c "
import glob, os
fs = sorted(glob.glob('train-*-of-100.parquet'))
print(len(fs), sum(os.path.getsize(f) for f in fs))
"
```

서버 쪽 바이트 수와 한 번에 대조하고 싶다면 목록 조회 결과와 로컬 파일을 직접 비교한다. 불일치 파일 이름이 출력되면 그 파일만 다시 받으면 된다.

```bash
curl -s "https://s3.us-west-2.amazonaws.com/assets.zilliz.com?list-type=2&prefix=benchmark/laion_large_100m/&max-keys=400" \
| python3 -c "
import sys, re, os
remote = {k.split('/')[-1]: int(s)
          for k, s in re.findall(r'<Key>(.*?)</Key>.*?<Size>(\d+)</Size>', sys.stdin.read(), re.S)}
bad = 0
for name, size in sorted(remote.items()):
    if not os.path.exists(name):
        continue
    local = os.path.getsize(name)
    if local != size:
        print(f'MISMATCH {name}: local={local:,} remote={size:,}'); bad += 1
print('mismatched files:', bad)
"
```

### 6.2 체크섬

laion 프리픽스의 `README.md`에는 SHA-256이 실려 있다. **다만 그 표가 덮는 것은 large-top-K 산출물과 생성 스크립트뿐이고, train 샤드 100개의 해시는 들어 있지 않다는 점을 확인했다.** 따라서 train 샤드는 바이트 수 대조와 parquet 읽기 성공 여부로 확인할 수밖에 없다.

README가 해시를 제공하는 파일들은 아래처럼 검증한다.

```bash
cd ~/vecdata/laion100m
shasum -a 256 test_nq200.parquet neighbors_top100k_nq200.parquet
# 기대값 (README.md 에 적힌 값)
# 80376447e111f0e304fb67ecb233603996ba0583c1c6279a994523db4d4a17c7  test_nq200.parquet
# 55ac377d2997295e144efd255c0c0cc587171abd54f7cbfc57efef1e2e99684e  neighbors_top100k_nq200.parquet
```

Zenodo는 API가 MD5를 준다. 4.4절의 명령으로 이미 받았다면 아래로 검증한다.

```bash
cd ~/vecdata/pes2o
md5 -q pes2o_corpus.npz 2>/dev/null || md5sum pes2o_corpus.npz
# f8c6c7e81facb8a4c8a6b2e9ee267f9f
```

### 6.3 행 수와 차원과 정규화 여부

핵심 검증이다. 아래 스크립트는 샤드마다 행 수를 세고, 표본 벡터의 차원과 L2 노름을 계산한다. laion 기준으로 기대 출력은 샤드마다 `rows=1,000,000 dim=768`이고, 노름이 1.0 근처(약 0.9995에서 1.0005 사이)로 나오는 것이다. 작성자가 `test.parquet` 1,000개로 잰 실측값은 최소 0.999474, 최대 1.000519, 평균 0.999995였다.

```bash
python3 -m pip install --quiet pyarrow numpy
python3 - <<'PY'
import glob, numpy as np, pyarrow.parquet as pq

files = sorted(glob.glob("train-*-of-100.parquet"))
total = 0
for i, f in enumerate(files):
    pf = pq.ParquetFile(f)
    n = pf.metadata.num_rows
    total += n
    if i < 3 or i == len(files) - 1:
        t = pf.read_row_group(0).slice(0, 256)
        v = np.array(t.column("emb").to_pylist(), dtype=np.float32)
        nm = np.linalg.norm(v, axis=1)
        print(f"{f}: rows={n:,} dim={v.shape[1]} "
              f"norm[min={nm.min():.6f} max={nm.max():.6f} mean={nm.mean():.6f}]")
print(f"TOTAL rows = {total:,}   (expected 100,000,000)")
PY
```

노름이 1.0이 아니라면 그 데이터는 정규화되지 않은 것이다. Qdrant는 컬렉션 거리 척도가 Cosine이면 업로드 시점에 자동으로 정규화하므로 순위에는 영향이 없지만, 다른 척도나 양자화를 쓸 계획이라면 미리 정규화해 두어야 한다. 특히 **4.3절의 `openai_large_5m`은 float64로 저장되어 있으므로** 아래처럼 먼저 float32로 낮추고 노름을 확인하는 편이 좋다.

```bash
python3 - <<'PY'
import pyarrow.parquet as pq, numpy as np
t = pq.ParquetFile("train-00-of-10.parquet").read_row_group(0).slice(0, 256)
v = np.array(t.column("emb").to_pylist())
print("stored dtype:", v.dtype, "dim:", v.shape[1])
v32 = v.astype(np.float32)
nm = np.linalg.norm(v32, axis=1)
print(f"norm min={nm.min():.6f} max={nm.max():.6f} mean={nm.mean():.6f}")
PY
```

### 6.4 정답 파일이 실제로 맞는지

정답을 믿고 리콜을 재기 전에, 정답 id가 실제 데이터 범위 안에 있는지 한 번 확인한다. laion 기준으로 id는 0부터 99,999,999 사이여야 하고, 질의마다 이웃이 1,000개여야 한다.

```bash
python3 - <<'PY'
import pyarrow.parquet as pq, numpy as np
gt = pq.read_table("neighbors.parquet")
q  = pq.read_table("test.parquet")
ids = np.array(gt.column("neighbors_id").to_pylist())
print("queries:", q.num_rows, "gt rows:", gt.num_rows, "k:", ids.shape[1])
print("neighbor id range:", ids.min(), "-", ids.max(), "(expected 0 - 99,999,999)")
qv = np.array(q.column("emb").to_pylist(), dtype=np.float32)
print("query dim:", qv.shape[1], "norm mean:", float(np.linalg.norm(qv, axis=1).mean()))
PY
```

작성자가 이 확인을 원격으로 수행했을 때 `neighbors.parquet`의 첫 행 이웃 id가 `[77430879, 67293908, 44729742, 72322121, ...]`로 1억 미만 범위에 있었고 개수가 1,000개였다.

---

## 7. 미확인 사항과 위험

### 7.1 라이선스 — 가장 큰 위험

이 절이 단계 구조의 **2.1 라이선스 확인**이며, 2.2 받기보다 먼저 끝나야 한다. 부록 B의 명령도 이 확인을 마친 뒤에 실행한다.

**주 데이터로 고른 Zilliz 배포본은 라이선스가 어디에도 명시되어 있지 않다.** 이번에 `laion_large_100m/README.md` 전문을 읽었으나 라이선스나 이용 조건에 대한 문장이 한 줄도 없었고, 프리픽스 목록에도 LICENSE 파일이 없었다. `cohere_large_10m`, `bioasq_large_10m`, `openai_large_5m`, `msmarco_v2_138M_parquet` 어디에도 없다. 원출처인 LAION은 CC-BY-4.0 계열로 알려져 있으나 **Zilliz 재배포본 자체의 조건은 확인되지 않았다.**

실무적으로 이것이 뜻하는 바는 다음과 같다. 사내 측정에 쓰고 결과 수치만 보고하는 것은 통상 문제가 되지 않지만, **데이터나 파생물을 재배포할 계획이 있다면 반드시 법무 확인을 먼저 받아야 한다.** 재배포 계획이 있다면 라이선스가 명시된 후보로 갈아타는 것이 안전하고, 그 경우 대안은 Zenodo Pes2o(CC-BY-4.0), `andropar/relaion2b-natural-embeddings`(CC-BY-4.0), `VDBBench/multimodal-embedding-100M`(CC-BY-4.0), `imageomics/TreeOfLife-200M-Embeddings`(CC0-1.0), `colonelwatch/abstracts-embeddings`(CC0-1.0)이다. 라이선스 값은 모두 2026-09-21에 HF API로 직접 확인했다.

한 가지 더 확인한 것이 있다. `CohereLabs/msmarco-v2.1-embed-english-v3`는 HF API의 라이선스 필드가 비어 있다(`null`). 앞 문서가 Snowflake 쪽 라이선스 부재를 지적했는데, **Cohere 쪽도 마찬가지**라는 점이 이번에 확인되었다. MS MARCO 텍스트 자체가 비상업 연구 전용이라는 점과 겹치므로 이 계열은 더 조심해야 한다.

### 7.2 앞 문서의 바이트 수 오류를 정정한다

`dataset_options_2026-09-17.md` 2.1절 방법 4에 실린 Zilliz 파일 크기 중 두 개가 다른 파일의 값과 뒤바뀌어 있다. 이번에 목록 조회로 확인한 실제 값은 다음과 같다.

| 파일 | 앞 문서의 값 | 2026-09-21 실측 | 앞 문서 값의 실제 주인 |
|---|---:|---:|---|
| `cohere_large_10m/tenant_labels_1000x10k.parquet` | 3,132,648 | **47,585,198** | `cohere_large_10m/test.parquet` |
| `cohere_large_10m/scalar_labels_2kb.parquet` | 4,716,629,630 | **52,561,451** | `cohere_large_10m/shuffle_train-00-of-10.parquet` |

같은 절의 다른 값들은 이번 실측과 일치했다. `cohere_large_10m`의 train 10개 합계는 31.3GB가 맞고(실측 31,326,939,213바이트), `scalar_labels.parquet`는 13,246,476바이트가 맞으며, `msmarco_v2_138M_parquet`의 parquet 277개 합계 851,155,886,678바이트도 정확히 일치했다.

### 7.3 앞 문서에 없던 URL 정보

big-ann DINO 파일의 URL이 앞 문서에 적혀 있지 않아 이번에 찾았다. 실제 위치는 `https://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/`이며, 이는 `big-ann-benchmarks`의 `benchmark/datasets.py` 1415행에서 확인한 것이다. 흔히 추측하는 `comp21storage` 경로는 404를 돌려주므로 주의해야 한다. 한편 `dino_vitl_2B_base.u8bin`은 **오늘도 403**이어서, 앞 문서가 남긴 "403이 일시적인지 영구적인지 미확인" 항목은 최소한 나흘째 같은 상태로 유지되고 있다.

### 7.4 여전히 검증되지 않은 가정

**MRL 절단이 성립하는지가 4.4절 차원 스윕의 전제다.** 모델 카드가 보증하는 것은 출력 차원을 지정할 수 있다는 것이지, 이미 뽑아 둔 2560차원 벡터를 앞에서 잘라 써도 된다는 것이 아니다. 앞 문서 5장이 지적한 그대로이며 이번에도 검증하지 못했다. **본 측정을 돌리기 전에 소규모로 반드시 확인해야 한다.** 확인 방법은 Pes2o에서 수만 개만 뽑아 2560차원 그대로의 리콜과 1536차원으로 절단하고 재정규화한 뒤의 리콜을 비교하는 것이다. 차이가 크면 차원 축은 절단이 아니라 서로 다른 데이터셋으로 가야 하고, 그 경우 4.2절과 4.3절의 조합이 대안이 된다.

**laion `scalar_labels.parquet`의 전역 라벨 종수를 세지 않았다.** 첫 row group 1,048,576행에서 74,928종을 확인했고 filler 번호가 0부터 2,715,626까지 흩어져 있음을 관측했지만, 96개 row group 전체를 복호해 세지는 않았다. 세션 분할은 적재기가 하므로(3.8절) 이 값은 세션 실험에 필요 없고, 배포본 라벨을 필터 선택도 눈금으로 쓰기로 할 때만 전체를 한 번 훑으면 된다.

**`msmarco_v2_138M`의 임베딩 모델명이 여전히 어디에도 적혀 있지 않다.** README를 전문 읽었으나 차원(1536)과 거리(L2)만 적혀 있고 모델 이름이 없다. 앞 문서의 지적이 그대로 유지된다.

**네트워크 속도를 측정 서버에서 재지 않았다.** 이 문서의 시간 추정은 모두 가정 대역폭에 대한 산술이고, 작성자가 실제로 잰 2.7MB/s는 노트북의 가정용 회선 값이라 서버와 무관하다. 3.4절의 명령으로 서버에서 먼저 재야 한다.

**Pes2o npz의 내부 압축 방식을 확인하지 않았다.** 앞 문서는 단일 deflate 멤버라 임의 행 접근이 안 된다고 적고 있으나, 이번에는 파일 앞 4바이트가 zip 매직이라는 것과 Range 요청에 206을 돌려준다는 것만 확인했다. 4.4절 마지막 명령으로 받은 뒤 직접 확인하면 된다.

### 7.5 용량과 메모리 점검

받기 전에 서버에서 아래를 확인한다. 주 데이터와 차원 스윕 데이터를 모두 받으면 원본만 약 1.27TB이고, Qdrant에 적재하면 여기에 색인과 WAL과 세그먼트 사본이 더해진다.

```bash
df -h            # Qdrant 데이터 경로가 속한 파일시스템의 여유
free -g          # RAM (macOS 라면 vm_stat)
nvidia-smi       # GPU 유무. 합성 데이터 경로를 열어 둘지 판단용
```

1억 개를 float32로 올렸을 때의 벡터 점유량은 앞 문서 5장 기준으로 768차원 307.2GB, 1024차원 409.6GB, 1536차원 614.4GB, 2560차원 1,024GB다. **2560차원 1억 개는 벡터만으로 RAM 1TB를 다 쓰므로 성립하지 않는다.** 이 가이드가 차원 축을 829만 개 규모의 Pes2o로 내려 잡은 이유가 여기에 있다.

---

## 부록 A. 오늘 실제로 확인한 것과 확인하지 못한 것

문서 본문의 근거를 한곳에 모은다. "확인함"은 작성자가 2026-09-21에 직접 요청을 보내 응답을 본 것이고, "앞 문서 인용"은 `dataset_options_2026-09-17.md`에서 가져온 것이다.

### 확인함

| 대상 | 결과 |
|---|---|
| Zilliz S3 익명 목록 조회 | HTTP 200, `benchmark/` 아래 프리픽스 28개와 파일 2개 |
| `laion_large_100m` 전체 | 객체 150개, 231,250,951,020바이트 |
| `laion_large_100m` train 100개 | 212,308,503,251바이트, 샤드 하나 2,123,160,971바이트 |
| `train-00-of-100.parquet` | 1,000,000행, row group 3개, `id: int64` + `emb: large_list<float>`, 첫 행 emb 길이 768 |
| `test.parquet` | 2,117,238바이트, 1,000행 768차원, **L2 노름 0.999474~1.000519 (정규화됨)** |
| `neighbors.parquet` | 4,510,710바이트, 1,000행, `neighbors_id` 길이 1,000 |
| `scalar_labels.parquet` | 590,420,586바이트, 100,000,000행, row group 96개, 첫 row group에 라벨 74,928종 |
| `laion_large_100m/README.md` | 전문 확인. 파일 목록과 SHA-256 있음, **라이선스 문장 없음** |
| S3 Range 요청 | `206 Partial Content`, `Content-Range: bytes 0-1023/2123160971` |
| `cohere_large_10m/tenant_labels_1000x10k.parquet` | 47,585,198바이트를 실제로 받아 열었다. 10,000,000행, 테넌트 정확히 1,000종 × 각 10,000개(완전 균등) |
| `cohere_large_10m/train-00-of-10.parquet` | 1,000,000행, `emb: large_list<float>`, 768차원 |
| `bioasq_large_10m` | 객체 32개, train 10개 19,280,984,409바이트, 1,000,000행, 1024차원 float32, **`shuffle_train`만 존재** |
| `openai_large_5m` | 객체 55개 90,042,426,177바이트, train 계열 20개, 500,000행, **`emb: list<double>` (float64)**, 1536차원 |
| `msmarco_v2_138M_parquet` | 객체 299개 852,018,132,378바이트, parquet 277개 851,155,886,678바이트. README에서 138,364,198행과 라벨 10,025종의 치우친 분포 확인. `query.npy` 61,440,128바이트 |
| ann-benchmarks 3종 | sift 525,128,288 / glove-100 485,413,888 / gist-960 3,844,648,288바이트, 모두 `accept-ranges: bytes`, sift 앞 8바이트 HDF5 매직 |
| Zenodo 17101276 | HTTP 200, 라이선스 `cc-by-4.0`, `pes2o_corpus.npz` 39,748,381,931바이트 MD5 `f8c6c7e81facb8a4c8a6b2e9ee267f9f`, Range 206 |
| big-ann DINO 1B | `dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/`에서 HTTP 200, 1,024,000,000,008바이트, 헤더 읽어 `npts=1,000,000,000 dim=1024` |
| big-ann DINO GT | `gts_bin/gts_dino_patch_100000000_k100.bin` 80,000,008바이트, `queries_clean.bvecs` 102,800,000바이트 |
| big-ann wiki-cohere-35M | `wikipedia_base.bin` 107,520,000,008바이트, `accept-ranges: bytes` |
| HF API 6개 저장소 | 전부 `gated=False`. 라이선스는 5.1절 표 참조 |

### 확인하지 못함

| 대상 | 상태 |
|---|---|
| `dino_vitl_2B_base.u8bin` | **403**. 앞 문서와 동일하며 원인 불명 |
| `comp21storage` 계열 DINO 경로 | **404**. 올바른 경로는 `dl.fbaipublicfiles.com` |
| Zilliz 배포본 라이선스 | 어느 프리픽스에도 명시 없음 |
| train 샤드의 공식 해시 | README의 SHA-256 표에 train 샤드가 없음 |
| `scalar_labels.parquet` 전역 라벨 종수 | 첫 row group만 복호함 |
| MRL 절단의 유효성 | 검증하지 않음. 7.4절 참조 |
| `msmarco_v2_138M` 임베딩 모델명 | README에 없음 |
| Pes2o npz 내부 압축 방식 | 받은 뒤 확인 필요 |
| 측정 서버의 실제 대역폭 | 서버에서 재지 않음 |

## 부록 B. 오늘 바로 실행할 순서

2.1 라이선스 확인(7.1절)을 마친 뒤에 실행한다.

```bash
# 1. 스모크 테스트 (약 5분)
mkdir -p ~/vecdata/smoke && cd ~/vecdata/smoke
curl -L --fail -O "https://ann-benchmarks.com/sift-128-euclidean.hdf5"

# 2. 서버 여유 확인
df -h; free -g

# 3. laion 질의/정답/라벨 먼저 (약 1분, 597MB)
mkdir -p ~/vecdata/laion100m && cd ~/vecdata/laion100m
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m"
for f in README.md test.parquet neighbors.parquet scalar_labels.parquet; do
  curl -sL --fail -O "$B/$f"; done

# 4. 샤드 하나로 속도 측정
curl -L --fail -o train-00-of-100.parquet "$B/train-00-of-100.parquet" \
  -w "speed=%{speed_download} B/s\n"

# 5. 나머지 99개를 백그라운드로 (212GB)
nohup sh -c 'seq -w 1 99 | xargs -P 8 -I{} curl -sL --fail --retry 5 -C - \
  -o "train-{}-of-100.parquet" \
  "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/train-{}-of-100.parquet"' \
  > download.log 2>&1 &

# 6. 받는 동안 2560차원 차원 스윕 데이터도 (39.7GB)
mkdir -p ~/vecdata/pes2o && cd ~/vecdata/pes2o
nohup curl -L --fail -C - -o pes2o_corpus.npz \
  "https://zenodo.org/records/17101276/files/pes2o_corpus.npz?download=1" \
  > pes2o.log 2>&1 &
```
