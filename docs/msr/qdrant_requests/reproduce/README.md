# MemMachine 저장소 계측 재현 가이드

이 문서 하나만 있으면 아무것도 모르는 상태에서 시작해 **MemMachine이 Qdrant와 임베딩 API를 몇 번 부르는지** 직접 측정할 수 있다. 명령을 위에서부터 그대로 붙여넣으면 된다.

- 대상 환경: **Ubuntu 24.04 LTS** (다른 배포판은 부록 C 참조)
- 필요 시간: 처음 한 번 약 20분, 이후 재측정은 약 3분
- 필요한 것: 인터넷이 되는 리눅스 서버, sudo 권한, 디스크 5GB
- **OpenAI API 키는 필요 없다.** 임베딩은 로컬 스텁으로 대체한다

이 가이드의 모든 명령은 Ubuntu 24.04 환경에서 실제로 실행해 검증했고, 문서를 쓴 사람이 아닌 다른 작업자가 이 문서만 보고 재현하는 검증도 따로 거쳤다. 검증 이력은 부록 E에 있다.

---

## 0. 무엇을 측정하는가

세 가지를 측정한다.

| 계측 | 무엇을 답하는가 | 소요 |
|---|---|---|
| **A. Qdrant 요청 트레이스** | 저장·검색 요청 1건이 Qdrant를 몇 번 부르는가 | 약 20초 |
| **B. 사용자 필터 검증** | 한 프로젝트에 여러 사용자를 넣었을 때 필터가 제대로 걸러내는가 | 약 10초 |
| **C. 임베딩 호출 트레이스** | 임베딩 API를 몇 번 부르고 언제 여러 건으로 갈라지는가 | 약 60초 |

측정 원리는 간단하다. MemMachine이 쓰는 HTTP 클라이언트의 전송 함수를 가로채 **실제로 나간 요청을 전부 기록**한다. 서버 코드는 고치지 않는다.

측정 결과의 해석은 같은 폴더 상위의 문서에 있다.

- `../qdrant_overview_2026-09-16.md` — 비전문가용 설명
- `../qdrant_report_2026-09-16.md` — 기술 분석과 결론
- `../qdrant_requests_by_state_2026-09-15.md` — 측정 기록

---

## 1. Docker 설치

먼저 `docker --version` 을 실행해 본다. 버전이 나오면 이 장을 건너뛰고 2장으로 간다. `command not found` 가 나오면 아래를 따른다.

**이 장의 목표는 `docker` 명령이 동작하게 만드는 것이다.** 2장부터는 계속 `docker` 를 쓰므로, 여기서 `docker run --rm hello-world` 가 성공하지 않으면 다음으로 넘어가지 않는다.

```bash
# 1-1. 사전 패키지
sudo apt update
sudo apt install -y ca-certificates curl

# 1-2. Docker 공식 GPG 키
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 1-3. 저장소 등록
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update

# 1-4. 설치
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 1-5. 확인
sudo docker run --rm hello-world
```

`sudo` 없이 쓰려면 다음을 실행하고 **로그아웃 후 다시 로그인**한다.

```bash
sudo usermod -aG docker $USER
```

이 가이드의 나머지 명령은 `docker`를 sudo 없이 쓸 수 있다고 가정한다. 안 된다면 `docker` 앞에 `sudo`를 붙이면 된다.

---

## 2. 저장소 두 개 기동

MemMachine은 벡터를 Qdrant에, 나머지를 PostgreSQL에 저장한다. 둘 다 컨테이너로 띄운다.

**포트를 기본값(6333, 5432)이 아니라 16333, 15432로 쓴다.** 그 서버에서 이미 돌고 있을 수 있는 Qdrant나 PostgreSQL과 충돌하지 않기 위해서다.

```bash
docker run -d --rm --name mm-qdrant \
  -p 16333:6333 -p 16334:6334 \
  qdrant/qdrant:v1.17.0

docker run -d --rm --name mm-pg \
  -p 15432:5432 -e POSTGRES_PASSWORD=mmtest \
  postgres:16-alpine
```

기동 확인. 둘 다 아래처럼 나와야 한다.

```bash
curl -s localhost:16333/ ; echo
docker exec mm-pg pg_isready -U postgres
```

```
{"title":"qdrant - vector search engine","version":"1.17.0",...}
/var/run/postgresql:5432 - accepting connections
```

> `--rm`을 붙였으므로 컨테이너를 멈추면 데이터가 사라진다. 측정용이므로 이게 맞다.

---

## 3. 시스템 패키지 설치

```bash
sudo apt install -y git curl ca-certificates tzdata
```

**`tzdata`를 빼면 안 된다.** MemMachine은 불러오는 순간 시간대 정보를 찾는다. 없으면 다음 오류로 아무것도 실행되지 않는다.

```
zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key UTC'
```

---

## 4. uv 설치

uv는 파이썬 패키지 관리 도구다. MemMachine이 이것을 쓴다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

```
uv 0.12.15
```

**PATH 설정을 영구 적용해 두는 것을 권한다.** 이 가이드의 5장 이후 모든 명령이 `uv` 를 쓰는데, 위의 `export` 는 그 터미널에만 적용된다. 새 터미널을 열거나 재접속하면 `uv: command not found` 가 난다.

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
uv --version
```

> 접속이 끊겼다가 다시 붙었는데 `uv: command not found` 가 나면, 위 `export` 한 줄을 다시 실행하면 된다.

---

## 5. MemMachine 소스 받기

**브랜치가 아니라 커밋을 고정한다.** 측정 결과는 코드 버전에 딸린 값이고, `speedkick` 브랜치는 계속 움직이기 때문이다.

```bash
cd ~
git clone --branch speedkick https://github.com/MemMachine/MemMachine.git
cd MemMachine
git checkout a8322a790a1c0b50ac26b9faddfbee40fc20cadb
git log -1 --format='%h %s'
```

```
a8322a7 [vector store 1/13] Remove per-project filterable properties (speedkick) (#1606)
```

클론에 약 6초, 디스크 약 36MB가 든다.

**재측정 시 기준 커밋.** 위 체크아웃과 6장의 확인 출력은 2026-09-15 측정 당시의 기록이다. 다시 측정할 때의 기준은 speedkick `8d7b832`(`8d7b832a1357af7de018fce6ea76ad190a336e0f`)이며, 계측 A 는 `trace_qdrant_requests.py` 대신 요청과 응답의 원문을 함께 기록하는 `trace_qdrant_requests_raw.py`(같은 폴더)를 쓴다. 이 스크립트의 기록 항목과 실행 환경 요건과 기대 횟수는 `../../qdrant_bottleneck/emulator_request_spec_2026-09-22.md` 9장에 있다. `a8322a7` 부터 `8d7b832` 사이에 Qdrant 요청 본문을 바꾼 커밋이 없으므로 8장의 구간별 요청 수는 그대로여야 하고, 6장의 확인 출력(qdrant-client 1.19.0)도 같다.

---

## 6. 의존성 설치

```bash
uv sync --python 3.12 --package memmachine-server --extra qdrant
```

약 15초 걸린다.

**`--python 3.12`를 빼면 안 된다.** 프로젝트는 3.12 이상이면 되므로 uv가 더 최신 버전(3.14 등)을 받아 가는데, 그러면 이 문서의 측정값과 환경이 달라진다.

설치가 끝나면 확인한다.

```bash
uv run --python 3.12 --package memmachine-server python -c "
import memmachine_server, zoneinfo
from importlib.metadata import version
print('qdrant-client', version('qdrant-client'))
print('zoneinfo UTC ', zoneinfo.ZoneInfo('UTC'))
print('OK')
"
```

```
qdrant-client 1.19.0
zoneinfo UTC  zoneinfo.ZoneInfo(key='UTC')
OK
```

> `Decomposer import FAILED ... No module named 'spacy'` 메시지가 보여도 **정상이다.**
> 검색 에이전트의 선택적 기능이고 이 측정과 무관하다.

의존성 버전은 저장소에 커밋된 `uv.lock`이 고정하므로 누가 언제 설치해도 같다(qdrant-client 1.19.0, openai 2.54.0, sqlalchemy 2.0.52, pydantic 2.13.5).

---

## 7. 계측 파일 배치

계측 스크립트 5개를 작업 폴더에 모은다. 이 가이드와 같은 폴더에 있는 파일들이다.

```bash
mkdir -p ~/mm-measure
cd ~/mm-measure
# 아래 5개 파일을 이 폴더에 복사한다
#   config.yml
#   config_embed.yml
#   verify_producer_filter.py
#   trace_qdrant_requests.py
#   trace_embedding_calls.py
ls
```

**다섯 개가 같은 폴더에 있어야 한다.** `trace_qdrant_requests.py`가 `verify_producer_filter.py`의 임베더를 가져다 쓴다.

각 파일의 역할이다.

| 파일 | 역할 |
|---|---|
| `config.yml` | A와 B가 쓰는 설정. 저장소 주소와 포트 |
| `config_embed.yml` | C가 쓰는 설정. 임베더가 로컬 스텁 서버를 향한다 |
| `verify_producer_filter.py` | 계측 B. 결정적 해시 임베더도 여기 들어 있다 |
| `trace_qdrant_requests.py` | 계측 A |
| `trace_embedding_calls.py` | 계측 C. OpenAI 호환 스텁 서버를 스스로 띄운다 |

---

## 8. 계측 A — Qdrant 요청 트레이스

**빈 저장소에서 실행해야 한다.** 세션을 처음 만들 때의 요청 수를 재기 때문이다. 방금 2장에서 띄웠다면 그대로 진행한다. 이미 무언가 측정했다면 11장을 먼저 실행한다.

```bash
cd ~/mm-measure
uv run --project ~/MemMachine --python 3.12 --package memmachine-server \
  python trace_qdrant_requests.py
```

### 예상 출력

각 구간마다 Qdrant 요청 수가 나온다. 숫자가 아래와 같아야 한다.

| 구간 | 내용 | 요청 수 |
|---|---|---|
| P0 | 프로세스 시작 (연결 확인) | **1** |
| S1 | 첫 세션 열기 (저장소가 완전히 비어 있음) | **17** |
| S2 | 두 번째 새 세션 열기 | **17** |
| S3 | 같은 세션 다시 열기 (캐시에 있음) | **0** |
| S4 | 에피소드 4건 저장 | **1** |
| S5 | 에피소드 2건 저장 | **1** |
| S6~S9 | 검색 4가지 (필터·문맥·top_k·점수 기준을 바꿔가며) | **각 1** |
| S10 | 캐시에서 제거 | **0** |
| S11 | 제거 후 다시 열고 검색 | **2** |
| S12 | 에피소드 1건 삭제 | **1** |
| S13 | 세션 삭제 | **4** |

이 숫자가 뜻하는 것이다.

- **S4, S5가 각 1**: 한 요청에 에피소드가 몇 개든 저장은 1회다
- **S6~S9가 전부 1**: 검색 옵션을 어떻게 바꿔도 Qdrant 요청 수는 변하지 않는다
- **S3이 0, S11이 2**: 캐시에 있으면 준비 요청이 없고, 빠지면 확인 요청이 1회 더 붙는다
- **S1이 17**: 세션을 처음 만들 때 드는 비용. 이 중 11회가 색인 생성이다

상세 내역은 `qdrant_request_trace.json`에 저장된다.

---

## 9. 계측 B — 사용자 필터 검증

한 프로젝트에 사용자 3명의 대화를 넣고, 필터로 한 사람만 골라낼 수 있는지 본다.

```bash
cd ~/mm-measure
uv run --project ~/MemMachine --python 3.12 --package memmachine-server \
  python verify_producer_filter.py
```

### 예상 출력

| 필터 | 돌아온 개수 | 사용자 발화 | AI 응답 | 타인 유입 |
|---|---|---|---|---|
| 필터 없음 | 12 | — | — | 3명 전부 나옴 |
| `producer_id = 'user_a'` | **2** | 2/2 | **0/2** | 0 |
| `producer_id = 'user_a' OR produced_for_id = 'user_a'` | **4** | 2/2 | **2/2** | 0 |
| `m.user_id = 'user_a'` | **4** | 2/2 | 2/2 | 0 |
| user_c에 OR 필터 (API 기본값으로 넣은 경우) | **2** | 2/2 | **0/2** | 0 |

핵심은 두 줄이다.

- **`producer_id`만으로 거르면 AI 응답이 빠진다** (0/2). "말한 사람"이 AI이기 때문이다
- **OR 조건을 쓰면 대화가 온전해진다** (2/2). 단 저장할 때 `produced_for`에 사용자를 넣어야 한다. user_c는 그걸 비워 둔 경우이고, 그래서 OR를 써도 여전히 0/2다

타인 유입이 모든 경우에 0이라는 점도 확인된다.

---

## 10. 계측 C — 임베딩 호출 트레이스

### 10-1. 먼저 NLTK 데이터 받기 (한 번만)

```bash
cd ~/mm-measure
uv run --project ~/MemMachine --python 3.12 --package memmachine-server \
  python -c "import nltk; nltk.download('punkt_tab')"
```

이걸 빼면 마지막 구간(E10)에서 `Resource 'punkt_tab' not found` 오류가 난다. 문장 단위로 쪼개는 기능이 이 데이터를 쓴다.

### 10-2. 실행

```bash
uv run --project ~/MemMachine --python 3.12 --package memmachine-server \
  python trace_embedding_calls.py
```

약 1분 걸린다. 2,100건을 넣는 구간이 있기 때문이다.

이 스크립트는 **OpenAI 호환 스텁 서버를 스스로 띄운다**(127.0.0.1:18099). 진짜 OpenAI를 부르지 않으므로 API 키도 비용도 필요 없다. 대신 실제 요청이 몇 건 나가는지 셀 수 있다.

### 예상 출력

**논리 호출**은 MemMachine이 임베더를 부른 횟수, **HTTP 요청**은 실제로 나간 네트워크 요청 수다.

| 구간 | 내용 | 논리 호출 | HTTP 요청 |
|---|---|---|---|
| E1 | 첫 세션 열기 (임베더 생성 검증) | 1 | 1 |
| E2 | 두 번째 세션 (임베더는 이미 있음) | **0** | **0** |
| E3 | 에피소드 4건 저장 | 1 | 1 |
| E4 | 에피소드 1건 저장 | 1 | 1 |
| E5, E6 | 검색 | 각 1 | 각 1 |
| E7 | **16만 자짜리 1건** 저장 | 1 | **3** |
| E8 | **2,100건** 저장 | 1 | **3** |
| E9 | `batch_size=2` 설정으로 5건 저장 | 2 | **4** |
| E10 | 문장 단위 분할로 2건 저장 | 1 | 1 |
| E11 | 캐시에서 빠진 뒤 검색 | 1 | 1 |

핵심은 **E7, E8, E9에서 HTTP가 3~4건으로 갈라진다**는 점이다. 논리 호출은 1회인데 실제 요청은 여러 건이다. 한 요청에 담을 수 있는 양(입력 2,048개, 총 75,000자)에 상한이 있기 때문이다.

상세 내역은 `embedding_call_trace.json`에 저장된다.

---

## 11. 다시 측정하려면 — 저장소 초기화

계측 A는 **빈 저장소**를 전제로 한다. 두 번째부터는 반드시 초기화하고 시작한다.

```bash
docker rm -f mm-qdrant mm-pg
docker run -d --rm --name mm-qdrant -p 16333:6333 -p 16334:6334 qdrant/qdrant:v1.17.0
docker run -d --rm --name mm-pg -p 15432:5432 -e POSTGRES_PASSWORD=mmtest postgres:16-alpine
sleep 6
curl -s localhost:16333/collections ; echo
```

비었으면 이렇게 나온다.

```
{"result":{"collections":[]},"status":"ok","time":...}
```

같은 폴더의 `reset_stores.sh`를 쓰면 한 줄로 끝난다.

```bash
bash reset_stores.sh
```

**권장 실행 순서**는 초기화 → A → B → C다. A만 빈 저장소를 요구하고 B와 C는 순서를 타지 않는다.

---

## 12. 정리

측정이 끝나면 컨테이너를 지운다. `--rm`으로 띄웠으므로 데이터도 함께 사라진다.

```bash
docker rm -f mm-qdrant mm-pg
```

소스와 가상환경까지 지우려면 `rm -rf ~/MemMachine ~/mm-measure` 를 실행한다.

---

## 13. 문제가 생겼을 때

| 증상 | 원인과 해결 |
|---|---|
| `ZoneInfoNotFoundError: 'No time zone found with key UTC'` | `tzdata` 미설치. `sudo apt install -y tzdata` |
| `Resource 'punkt_tab' not found` | 10-1을 건너뜀. NLTK 데이터를 받는다 |
| `ModuleNotFoundError: No module named 'verify_producer_filter'` | 스크립트 5개가 한 폴더에 없음. 7장 확인 |
| `Connection refused` / `All connection attempts failed` | 저장소 컨테이너가 안 떠 있음. `docker ps`로 확인 후 2장 재실행 |
| S1이 17이 아니라 다른 값 | 저장소가 비어 있지 않음. 11장으로 초기화 |
| `port is already allocated` | 16333이나 15432를 이미 누가 씀. 포트를 바꾸고 `config.yml`·`config_embed.yml`도 같이 고친다 |
| 파이썬이 3.14로 잡힘 | `--python 3.12`를 빠뜨림 |
| `uv: command not found` | `export PATH="$HOME/.local/bin:$PATH"` 를 다시 실행 |

### 무시해도 되는 메시지 두 가지

```
Decomposer import FAILED ... No module named 'spacy'
```
검색 에이전트의 선택 기능이다. 이 측정과 무관하다.

```
UserWarning: Qdrant client version 1.19.0 is incompatible with server version 1.17.0.
```
이건 **관측 결과 중 하나**다. 클라이언트가 1.19.0인데 서버가 1.17.0이라 경고가 뜬다. 측정은 정상 진행된다. 운영에서는 서버를 1.18 이상으로 올리는 것이 맞다는 근거가 된다.

---

## 부록 A. 한 번에 실행하기

익숙해진 뒤 전체를 한 번에 돌리고 싶다면 이렇게 한다.

```bash
cd ~/mm-measure
bash reset_stores.sh
export PATH="$HOME/.local/bin:$PATH"
RUN="uv run --project $HOME/MemMachine --python 3.12 --package memmachine-server python"
$RUN trace_qdrant_requests.py   | tee A_qdrant.txt
$RUN verify_producer_filter.py  | tee B_filter.txt
$RUN trace_embedding_calls.py   | tee C_embedding.txt
```

## 부록 B. 측정이 만들어내는 파일

| 파일 | 내용 |
|---|---|
| `qdrant_request_trace.json` | 계측 A의 구간별 요청 전체 (메서드, 경로, 본문 요약, 상태 코드, 소요 시간) |
| `embedding_call_trace.json` | 계측 C의 구간별 논리 호출과 HTTP 요청 |
| `mm.log`, `mm_embed.log` | MemMachine 로그. 오류만 기록된다(정상이면 비어 있음) |

## 부록 C. 다른 리눅스 배포판에서

배포판에 의존하는 부분은 **3장의 패키지 설치 한 줄뿐**이다. 나머지는 모두 Docker와 uv로 처리하므로 그대로 쓸 수 있다.

| 배포판 | 3장 대체 명령 |
|---|---|
| Debian 12 | Ubuntu와 동일 (`apt install -y git curl ca-certificates tzdata`) |
| RHEL / Rocky / Alma 9 | `sudo dnf install -y git curl ca-certificates tzdata` |
| Fedora | `sudo dnf install -y git curl ca-certificates tzdata` |
| Arch | `sudo pacman -S --needed git curl ca-certificates tzdata` |

Docker 설치는 각 배포판의 공식 문서를 따른다. 1장은 Ubuntu 기준이다.

커널이나 배포판 버전에 의존하는 동작은 없다. x86_64와 arm64 모두 동작한다(검증은 arm64에서 했다).

## 부록 D. 컨테이너 안에서 실행하는 경우

서버에 직접 설치하지 않고 **컨테이너 안에서** 계측만 돌리고 싶을 때가 있다. 이때 한 가지만 다르다.

저장소(Qdrant, PostgreSQL)를 호스트에서 띄우고 계측만 컨테이너에서 돌리면, 컨테이너 입장에서 `127.0.0.1` 은 자기 자신이라 호스트의 저장소에 닿지 못한다. 컨테이너를 만들 때 호스트 주소를 넣어 주고 설정의 **DB 주소만** 바꾼다.

```bash
# 컨테이너 생성 시
docker run -d --name mm-measure --add-host=host.docker.internal:host-gateway ubuntu:24.04 sleep infinity

# 컨테이너 안에서, DB 주소만 치환
sed -i "/base_url/! s/127\.0\.0\.1/host.docker.internal/g" config.yml config_embed.yml
```

**`base_url` 줄은 반드시 제외한다.** 계측 C의 임베딩 스텁 서버는 컨테이너 안에서 뜨므로 `127.0.0.1` 로 남아야 한다. 이 줄까지 바꾸면 계측 C가 연결 실패로 죽는다.

서버에 직접 설치하는 일반적인 경우에는 저장소도 같은 장비에 있으므로 이 치환이 **필요 없다.**

## 부록 E. 이 가이드의 검증 이력

문서를 쓰고 끝낸 것이 아니라, **깨끗한 Ubuntu 24.04 환경에서 처음부터 실행해 확인**했다.

| 검증 항목 | 결과 |
|---|---|
| 환경 | `ubuntu:24.04` 컨테이너 (24.04.5 LTS, arm64) |
| 1~6장 설치 절차 | 전부 성공. 클론 5.7초, 의존성 설치 14초 |
| 계측 A | 14개 구간 전부 이 문서의 예상값과 일치 |
| 계측 B | 8개 경우 전부 일치 |
| 계측 C | E1~E11 전부 일치 |
| 저장소 초기화 | 약 3초, 빈 상태 확인 |

검증 과정에서 **세 가지 함정을 발견해 이 문서에 반영**했다. 모두 그냥 따라 하면 막히는 지점이다.

1. `tzdata`가 없으면 MemMachine을 불러오는 것 자체가 실패한다 (3장)
2. 파이썬 버전을 고정하지 않으면 3.14가 설치되어 환경이 달라진다 (6장)
3. NLTK `punkt_tab`이 없으면 마지막 구간에서 실패한다 (10-1장)

### 제3자 재현 검증

문서를 쓴 사람이 아닌 **다른 작업자가 이 문서만 보고** 처음부터 수행하는 검증을 따로 거쳤다. 새 컨테이너를 만들어 3장부터 10장까지 문서에 적힌 명령만 실행하게 했다.

| 항목 | 결과 |
|---|---|
| 3~10장 절차 | 8개 장 전부 성공, 오류 0건 |
| 계측 A | 14개 구간 전부 예상값과 일치 |
| 계측 B | 6개 시나리오 전부 일치 |
| 계측 C | 11개 구간 전부 일치 |
| 합계 | **31개 지표 전부 일치** |
| 판정 | "가이드만으로 재현 가능하다" |

이 검증에서 나온 지적을 받아 **PATH 설정 안내(4장)를 각주에서 본문으로 올리고, 1장의 진행 조건을 명확히 하고, 컨테이너 실행 시 주의사항(부록 D)을 추가**했다.
