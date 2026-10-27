# CES 2027 데모 회사 실행서: git pull부터 검증 결과 push까지

- 작성일: 2026-10-27
- 대상: 회사에서 이 데모를 처음 올리는 사람, 그리고 그 사람 옆에서 명령을 대신 실행하는 Claude Code(작은 모델 포함)
- 범위: 브랜치를 받는 것부터 실제 vLLM 두 대로 올리고, 검사를 통과시키고, 결과 문서를 커밋해 push하는 것까지
- 함께 보는 문서: 왜 이렇게 만들었는지는 [설계 문서](design_2026-10-26.md), Mac에서 mock으로 통과한 기록은 [Mac 검증](verification_mac_2026-10-27.md), 부스로 옮기는 순서는 [이전 절차서](relocation_2026-10-27.md), 자주 바꾸는 값과 증상표는 [사용 가이드](guide_2026-10-27.md) 4장과 5장

## 1. 요약

이 문서 하나로 회사 검증을 끝낼 수 있게 썼다. 순서는 작업표 채우기(2장), 에이전트 규칙 읽기(3장), 코드 받기(4장), 서버마다 준비(5장), 역할 순서대로 올리기(6장), 화면과 시간 확인(7장), 결과 문서 커밋과 push(8장), 보고(9장)다. 문제가 생기면 10장의 증상표를 본다.

단계는 모두 같은 형식이다. **하는 일** 한 문장, **명령** 복사해 실행, **나와야 하는 것**, **다르면** 어떻게 할지. 나와야 하는 것이 안 나오면 다음 단계로 가지 않는다. 명령은 Linux 서버 기준이고, 경로는 모두 `~/ces2027/MemMachine` 아래에 clone이 있다고 가정한다. 다른 곳에 받았으면 그 경로로 바꿔 읽는다.

Claude Code가 수행할 때 한 가지를 특히 지킨다. 터미널 명령은 호출마다 새 셸에서 돌기 때문에 앞 명령에서 만든 변수는 다음 명령에 남지 않는다. 그래서 이 문서의 명령은 전부 절대 경로와 실제 값으로 쓰고, 값이 필요한 자리는 `<이렇게>` 표시해 두었다. 실행하기 전에 2장의 작업표 값으로 바꾼다.

## 2. 작업표

시작하기 전에 아래 두 표를 채운다. 빈칸이 하나라도 있으면 사람에게 물어서 채운 뒤에 시작한다. 이 표의 값이 5장의 `.env`에 그대로 들어간다.

### 2.1 서버와 역할

역할은 네 가지다. `db`(PostgreSQL과 Qdrant), `embed`(vLLM 임베딩 모델, 포트 8001), `llm`(vLLM 채팅 모델, 포트 8000), `app`(MemMachine과 Open WebUI). 한 서버에 역할을 여럿 둘 수 있다. 어느 경우든 각 역할의 주소에는 그 서버의 내부망 IP를 적는다. 같은 서버에 있어도 `127.0.0.1`이 아니라 내부망 IP를 적는다. 그래야 모든 서버의 `.env`가 같은 내용이 된다.

| 역할 | 서버 내부망 IP | 그 서버에서 올릴 프로필 | GPU |
|---|---|---|---|
| db | `<DB_IP>` | `db` | 없음 |
| embed | `<EMBED_IP>` | `embed` | H100 한 장, 번호 `<EMBED_GPU>` |
| llm | `<LLM_IP>` | `llm` | H100 한 장, 번호 `<LLM_GPU>` |
| app | `<APP_IP>` | `app` | 없음 |
| 시연 화면(브라우저) | 사람이 쓰는 PC | 없음 | 없음 |
| 이 Claude Code 세션이 도는 서버 | 위 역할 중 `<이 서버의 역할들>` | | `hostname -I`의 IP가 표의 어느 행인지로 안다 |
| 이미 있는 clone 경로 (4.2절을 쓸 때만) | `<기존 clone 경로>` | | 없으면 4.1절로 새로 받는다 |

Claude Code 세션 하나는 서버 한 대에서 돈다. 5장과 6장의 절 가운데 이 서버에 없는 역할의 절은 건너뛰고, 그 절은 사람이 그 서버에서 직접 하거나 그 서버에서 세션을 새로 열어 한다. 다른 서버로 `ssh`하지 않는다.

자주 있는 모양 세 가지를 예로 든다. 모양이 달라도 6장의 명령은 "그 역할이 있는 서버에서" 실행하면 되고, 바뀌는 것은 이 표의 IP뿐이다.

- 서버 네 대(부스와 같은 모양). 네 IP가 모두 다르다. GPU 번호는 둘 다 `0`이다.
- GPU 서버 한 대에 H100 두 장, 다른 서버 한 대에 `db`와 `app`. `EMBED_IP`와 `LLM_IP`가 같고, `DB_IP`와 `APP_IP`가 같다. GPU 번호는 `LLM_GPU=0`, `EMBED_GPU=1`이다.
- 서버 한 대에 전부. 네 IP가 모두 같다. H100이 두 장이면 `LLM_GPU=0`, `EMBED_GPU=1`, 한 장이면 둘 다 `0`이고 메모리 비율을 5.4절의 주석대로 나눈다.
- vLLM 두 대를 운영자가 compose 밖에서 이미 띄워 둔 경우(2026년 10월 회사 검증이 이 모양이었다). `<EMBED_IP>`와 `<LLM_IP>`는 그 서버의 IP이고, `embed`와 `llm` 프로필은 올리지 않는다. 운영자가 지켜야 할 조건은 2.4절에 있다.

### 2.2 모델

| 항목 | 값 | 어디서 얻나 |
|---|---|---|
| 채팅 모델 가중치 디렉터리 | `<LLM_MODEL_PATH>` | 사람. Hugging Face 형식 디렉터리이며 안에 `config.json`이 있어야 한다. 추천은 8B급 지시 모델 하나(예: Qwen3-8B, Llama-3.1-8B-Instruct). 생각(reasoning)을 먼저 출력하는 모델은 피한다 |
| 채팅 모델의 화면 이름 | `<LLM_MODEL_NAME>` | 사람. 짧고 보기 좋은 이름(예: `Qwen3-8B`). 공백 없이 |
| 임베딩 모델 가중치 디렉터리 | `<EMBED_MODEL_PATH>` | 사람. 추천은 `BAAI/bge-m3` |
| 임베딩 모델 이름 | `<EMBED_MODEL>` | `<EMBED_MODEL_PATH>`의 마지막 디렉터리 이름(예: `bge-m3`). 보고서와 커밋 메시지에만 쓴다 |
| 임베딩 차원 | `<DIM>` | 5.3절의 명령으로 가중치의 `config.json`에서 읽는다(`bge-m3`는 1024) |
| 오늘 날짜 | `<날짜>` | `date +%F`의 출력(예: `2026-11-03`). 파일 이름에 쓴다 |

### 2.3 계정

| 항목 | 값 | 비고 |
|---|---|---|
| 스태프 계정 비밀번호 | `<ADMIN_PASSWORD>` | 사람이 정한다. 따옴표, 역슬래시, 공백 없이. 보고서와 커밋에 적지 않는다. 스크립트만 쓴다 |
| 부스 계정 비밀번호 | `<BOOTH_PASSWORD>` | 같은 규칙. 7.1절의 화면 확인과 부스 화면이 이 계정(`visitor@demo.local`)으로 들어간다 |
| `WEBUI_SECRET_KEY` | 명령으로 생성 | 5.4절에서 `openssl`로 만들어 `.env`에만 넣는다. 화면에 출력하지 않는다 |

### 2.4 이미 떠 있는 vLLM을 쓸 때

운영자가 vLLM을 systemd 같은 것으로 상시 서빙하고 데모가 그것을 그대로 쓰는 모양이다. 데모 쪽 파일은 모델 서버의 포트와 이름을 고정값으로 쓰므로, 운영자의 서버가 아래 조건을 지켜야 한다. 조건이 어긋나면 데모 파일을 고치지 말고 운영자에게 서버 쪽을 맞춰 달라고 한다.

| 조건 | 왜 | 어긋나면 보이는 것 |
|---|---|---|
| 채팅 vLLM이 포트 8000에서 모델 ID `<LLM_MODEL_NAME>`으로 응답한다 | `.env`의 `LLM_MODEL_NAME`이 Open WebUI의 모델 ID가 된다 | 검사의 `both demo models listed` 또는 `chat model served` 줄이 `FAIL` |
| 임베딩 vLLM이 포트 8001에서 모델 ID `embed`로 응답하고 `--runner pooling`으로 떠 있다 | `memmachine.yml`이 `embed`라는 이름과 8001을 고정값으로 쓴다. `--served-model-name`은 이름을 여러 개 받으므로 별명으로 더하면 된다 | MemMachine 404, 적재 500, 검사의 `embedding server` 줄 끝이 `embed`가 아님 |
| 임베딩 서버가 `dimensions` 인자를 받아들인다 | 6.2절. 받지 않으면 첫 적재가 500으로 끝난다 | 6.2절의 마지막 `curl`이 오류 |
| 채팅 모델이 Qwen3 계열이면 `--default-chat-template-kwargs '{"enable_thinking": false}'`로 떠 있다 | 생각을 먼저 출력하면 왼쪽 카드가 답 직전까지 빈 채로 보인다 | 6.3절의 `REASONING yes` |
| 가능하면 채팅 vLLM에 `--enable-log-requests`가 있다 | 7.3절이 요청 로그로 내장 도구 차단을 확인한다 | 없으면 7.3절은 "미판정"으로 보고한다 |

이 모양에서는 5.2절과 5.3절의 llm, embed 명령, 6.2절과 6.3절의 `docker compose ... up` 명령을 건너뛰고 그 절의 `curl`만 실행한다. 작업표의 `<LLM_MODEL_PATH>`, `<EMBED_MODEL_PATH>`, `<LLM_GPU>`, `<EMBED_GPU>`는 compose 해석을 위해 아무 값이나 채운다(예: `/models/llm`, `0`). `<DIM>`은 6.2절의 `LEN`으로 정한다.

## 3. 에이전트 규칙

Claude Code가 이 문서를 수행할 때 지키는 규칙이다. 사람이 직접 할 때도 같은 규칙이 안전하다.

하지 않는 것.

- Open WebUI와 MemMachine의 소스를 고치지 않는다. 고칠 수 있는 파일은 `tools/ces2027_demo/` 아래와 `docs/msr/ces2027_demo/` 아래뿐이다.
- `tools/ces2027_demo/deploy/.env`를 커밋하지 않는다(gitignore에 있다). `git add -A`나 `git add .`을 쓰지 않고 파일 이름을 하나씩 적어 `git add`한다.
- `docker compose ... down -v`를 실행하지 않는다. 볼륨까지 지워져 적재한 기억과 채팅이 사라진다. 볼륨을 지우는 명령은 6.4절의 "다르면"에 있는 `docker volume rm deploy_openwebui_data` 하나뿐이며, 그것도 실행 전에 사람에게 알린다.
- `docker-compose.yml`과 `memmachine.yml`은 5.3절의 `dimensions` 한 줄 외에는 고치지 않는다.
- 작업표에 없는 서버에 접속하지 않는다. 자격 증명(git, Docker, ssh)을 새로 만들거나 설정하지 않는다.
- `sudo`가 필요한 명령은 이 문서에 없다. 어떤 단계가 `sudo`를 요구하면 멈추고 사람에게 말한다.

멈추고 사람에게 묻는 것.

- 작업표에 빈칸이 있다.
- 어떤 단계의 "나와야 하는 것"이 안 나오고, "다르면"과 10장의 증상표를 한 번 적용해도 같다. 같은 명령을 세 번 넘게 반복하지 않는다.
- `git push`가 거부된다(8.4절).
- 대본의 기대 문구가 검색 결과에 없어서 대본을 고쳐야 한다(6.4절의 "다르면"). 고칠 내용을 제안하고 사람이 고르게 한다.

보고하는 것. 끝나면 9장의 양식으로 보고한다. 중간에 멈출 때도 같은 양식으로 어디까지 됐는지 적는다.

## 4. 코드 받기

4.1과 4.2 중 하나만 한다. 어느 쪽인지 모르면 4.1을 한다.

### 4.1 새로 clone (기본)

**하는 일** 데모 브랜치만 얕게 받는다. 저장소 전체 역사는 1GB가 넘지만 이렇게 받으면 100MB 안팎이고 몇 초면 끝난다.

```bash
mkdir -p ~/ces2027 && cd ~/ces2027 && git clone --branch msr_ces2027_demo --single-branch --depth 1 https://github.com/taejin-oh/MemMachine.git
```

**나와야 하는 것** 마지막 줄이 `Resolving deltas: 100% ...`이거나 아무 오류 없이 끝나고, `~/ces2027/MemMachine`이 생긴다.

**다르면** `Repository not found`나 인증 요청이 나오면 저장소 접근 권한이 없는 것이다. 사람에게 GitHub 계정으로 `gh auth login` 또는 자격 증명 설정을 부탁한다. 이 문서는 자격 증명을 만들지 않는다.

### 4.2 이미 있는 clone을 쓸 때

**하는 일** 기존 clone에서 브랜치를 별도 worktree로 받는다. 기존 작업 디렉터리는 건드리지 않는다. 먼저 원격 목록을 본다.

```bash
cd <기존 clone 경로> && git remote -v
```

**나와야 하는 것** 원격 목록. `https://github.com/taejin-oh/MemMachine.git`이 보이면 그 줄 맨 앞의 이름(보통 `origin`)이 데모 원격이다. 보이면 첫 번째 명령을, 안 보이면 두 번째 명령을 실행한다.

데모 원격이 이미 있을 때(이름이 `origin`이 아니면 두 곳을 그 이름으로 바꾼다):

```bash
cd <기존 clone 경로> && git fetch origin msr_ces2027_demo && git worktree add ~/ces2027/MemMachine -b msr_ces2027_demo origin/msr_ces2027_demo
```

데모 원격이 없을 때(`fork`라는 이름으로 더한다):

```bash
cd <기존 clone 경로> && git remote add fork https://github.com/taejin-oh/MemMachine.git && git fetch fork msr_ces2027_demo && git worktree add ~/ces2027/MemMachine -b msr_ces2027_demo fork/msr_ces2027_demo
```

**나와야 하는 것** `Preparing worktree (new branch 'msr_ces2027_demo')`와 `HEAD is now at ...`. 8장의 push에서 쓸 원격 이름(`origin` 또는 `fork`)을 적어 둔다.

**다르면** `a branch named 'msr_ces2027_demo' already exists`면 예전에 받은 것이다. `git worktree add ~/ces2027/MemMachine msr_ces2027_demo`로 worktree를 만든 뒤 `cd ~/ces2027/MemMachine && git pull --ff-only <원격 이름> msr_ces2027_demo`로 최신을 받는다. `fork`로 받았으면 8장의 `origin`을 `fork`로 읽는다.

### 4.3 받은 것 확인

**하는 일** 이 문서가 들어 있는 최신 브랜치인지 본다.

```bash
cd ~/ces2027/MemMachine && git log -1 --oneline && ls tools/ces2027_demo && test -f docs/msr/ces2027_demo/company_runbook_2026-10-27.md && echo runbook-present
```

**나와야 하는 것** 커밋 한 줄(보고서에 적는다), `README.md assets deploy mock pipe scenario scripts`(순서는 다를 수 있다), 그리고 `runbook-present`.

**다르면** `runbook-present`가 없으면 오래된 브랜치다. `cd ~/ces2027/MemMachine && git pull --ff-only`를 실행하고 다시 본다.

## 5. 서버마다 준비

5장은 역할이 있는 서버마다 한다. 서버가 한 대면 한 번, 네 대면 네 번이다. 서버마다 4장대로 clone을 두는 것이 가장 단순하다. GPU 서버는 compose 파일과 `.env`만 쓰고, 앱 서버는 스크립트와 대본도 쓴다. 어느 쪽이든 4.1절의 얕은 clone이면 충분하다.

### 5.1 프로그램 확인

**하는 일** Docker Compose v2와 Python 3.10 이상이 있고, 이 계정이 Docker를 쓸 수 있는지 본다.

```bash
docker --version && docker compose version && python3 --version && docker ps >/dev/null && echo docker-ok
```

**나와야 하는 것** `Docker Compose version v2.`로 시작하는 줄(또는 그 이상), `Python 3.10` 이상, 마지막에 `docker-ok`.

**다르면** 프로그램이 없으면 사람에게 설치를 부탁한다. Python 패키지는 필요 없다(스크립트는 표준 라이브러리만 쓴다). `permission denied while trying to connect to the Docker daemon socket`이면 이 계정이 `docker` 그룹에 없는 것이다. `sudo`로 돌리지 말고 멈춰서 사람에게 그룹 추가를 부탁한다.

### 5.2 GPU 확인 (embed, llm 역할 서버만. 운영자 서빙이면 건너뛴다)

**하는 일** 컨테이너에서 GPU가 보이는지 본다.

```bash
nvidia-smi -L && docker run --rm --gpus all --entrypoint nvidia-smi vllm/vllm-openai:v0.26.0 -L
```

**나와야 하는 것** 두 번 모두 `GPU 0: NVIDIA H100 ...` 같은 GPU 목록. 두 번째는 처음이면 이미지를 내려받느라 몇 분 걸린다(이미지는 10GB가 넘는다). vLLM 이미지의 entrypoint가 `vllm serve`라서 `--entrypoint`로 바꿔 실행한다.

**다르면** `could not select device driver "nvidia"`면 NVIDIA Container Toolkit이 없는 것이다. 사람에게 설치를 부탁한다. 첫 명령부터 실패하면 드라이버 문제다.

### 5.3 모델 가중치와 임베딩 차원

**하는 일** 가중치 디렉터리가 맞는지 보고, 임베딩 차원을 읽어 MemMachine 설정에 적는다. 역할마다 명령이 다르다. 이 서버에 없는 역할의 명령은 건너뛴다. 운영자 서빙(2.4절)이면 llm과 embed 명령을 건너뛰고 `<DIM>`은 6.2절의 `LEN`으로 정한 뒤 app 명령만 한다.

llm 역할 서버에서:

```bash
ls <LLM_MODEL_PATH>/config.json
```

**나와야 하는 것** 그 경로가 그대로 출력된다.

embed 역할 서버에서:

```bash
ls <EMBED_MODEL_PATH>/config.json && python3 -c "import json; print('DIM', json.load(open('<EMBED_MODEL_PATH>/config.json'))['hidden_size'])"
```

**나와야 하는 것** 경로와 `DIM <숫자>`. 이 숫자가 작업표의 `<DIM>`이다. `bge-m3`는 `DIM 1024`다.

**다르면** `No such file`이면 경로가 틀렸다. 사람에게 확인한다. `hidden_size`가 없으면 모델 카드의 embedding dimension을 사람에게 묻는다. 이 값은 6.2절에서 실제 출력 길이로 한 번 더 확인하므로 틀려도 그때 잡힌다.

app 역할 서버에서(작업표의 `<DIM>`이 채워진 뒤) MemMachine 설정의 차원을 고친다. 임베딩 모델을 바꾸면 기억을 다시 넣어야 하므로 한 번 정하고 고정한다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && sed -i 's/dimensions: [0-9]*/dimensions: <DIM>/' memmachine.yml && grep -n 'dimensions:' memmachine.yml
```

**나와야 하는 것** `dimensions: <DIM>` 한 줄. 이 변경은 8장에서 커밋한다.

### 5.4 `.env` 쓰기

**하는 일** 장소별 값을 한 파일에 적는다. 모든 서버에서 같은 내용이어야 한다. 아래 블록의 `<...>`를 작업표 값으로 바꾼 뒤 통째로 실행한다. 회사 검증 동안에는 시간대를 서울로 두고 LLM 서버의 요청 로그를 켠다. 두 값은 부스로 가기 전에 [이전 절차서](relocation_2026-10-27.md) 2장대로 되돌린다.

```bash
cat > ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env <<'EOF'
# Company verification values. Same content on every server. See .env.example for what each key means.
DB_HOST=<DB_IP>
LLM_HOST=<LLM_IP>
EMBED_HOST=<EMBED_IP>
APP_HOST=<APP_IP>
OPENWEBUI_PORT=3000
MEMMACHINE_PORT=8080
LLM_MODEL_NAME=<LLM_MODEL_NAME>
LLM_BASE_URLS=http://llm:8000/v1
TZ=Asia/Seoul
VLLM_IMAGE=vllm/vllm-openai:v0.26.0
LLM_MODEL_PATH=<LLM_MODEL_PATH>
EMBED_MODEL_PATH=<EMBED_MODEL_PATH>
LLM_GPU=<LLM_GPU>
EMBED_GPU=<EMBED_GPU>
# Two GPUs: 0.90 and 0.20. Both vLLMs on one GPU: 0.70 and 0.20.
LLM_GPU_MEMORY=0.90
EMBED_GPU_MEMORY=0.20
LLM_MAX_MODEL_LEN=8192
# Request logging for the company check (section 7.3). Clear it for the booth.
LLM_EXTRA_ARGS=--enable-log-requests
EMBED_EXTRA_ARGS=
ADMIN_NAME=Demo Staff
ADMIN_EMAIL=staff@demo.local
ADMIN_PASSWORD=<ADMIN_PASSWORD>
BOOTH_NAME=Visitor
BOOTH_EMAIL=visitor@demo.local
BOOTH_PASSWORD=<BOOTH_PASSWORD>
WEBUI_SECRET_KEY=GENERATE
DEMO_DATE=2027-01-06
BASE_SYSTEM_PROMPT=You are a helpful assistant. Answer briefly and concretely.
POSTGRES_PASSWORD=memmachine
EOF
sed -i "s|^WEBUI_SECRET_KEY=GENERATE|WEBUI_SECRET_KEY=$(openssl rand -hex 32)|" ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env && (grep -n '<' ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env || echo env-ok)
```

**나와야 하는 것** 마지막 줄이 `env-ok`다(`<`가 남아 있지 않다는 뜻). 서버마다 이 블록을 그대로 실행한다. `WEBUI_SECRET_KEY`와 계정은 앱 서버에서만 쓰이므로 다른 서버에서는 값이 달라도 된다.

**다르면** `env-ok` 대신 줄 번호와 함께 바꾸지 않은 `<...>`가 나온다. 그 줄을 고치고 괄호 안의 `grep` 명령만 다시 실행한다. 이 블록 전체를 다시 실행하지 않는다(비밀 키가 또 바뀌어 로그인이 풀린다). 나중에 값 하나를 고칠 때도 아래 꼴로 그 줄만 바꾼다.

```bash
sed -i 's/^LLM_MAX_MODEL_LEN=.*/LLM_MAX_MODEL_LEN=4096/' ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env && grep -n '^LLM_MAX_MODEL_LEN=' ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env
```

채팅 모델이 Qwen3 계열이면(이름에 `Qwen3`가 들어가면) 생각(thinking)을 끄는 인자를 더한다. 끄지 않으면 6.3절에서 `REASONING yes`가 나오고 왼쪽 카드가 답 직전까지 비어 보인다.

```bash
sed -i "s|^LLM_EXTRA_ARGS=.*|LLM_EXTRA_ARGS=--enable-log-requests --default-chat-template-kwargs '{\"enable_thinking\": false}'|" ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env && grep -n '^LLM_EXTRA_ARGS=' ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env
```

**나와야 하는 것** `LLM_EXTRA_ARGS=--enable-log-requests --default-chat-template-kwargs '{"enable_thinking": false}'` 한 줄.

### 5.5 compose 문법 확인

**하는 일** `.env`의 값으로 compose가 해석되는지 본다. 어느 프로필이든 같은 `.env`를 읽으므로 모든 서버에서 `app`으로 확인하면 된다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile app config --quiet && echo compose-ok
```

**나와야 하는 것** `compose-ok`만 나온다.

**다르면** 비어 있는 변수 이름이 나온다. `.env`에서 그 줄을 채운다. `WARN` 줄은 무시해도 된다.

## 6. 올리기

순서는 `db`, `embed`, `llm`, `app`이다. 각 절은 그 역할이 있는 서버에서 실행한다. 한 서버에 여러 역할이 있으면 그 서버에서 절을 이어서 한다. 운영자 서빙(2.4절)이면 6.2절과 6.3절의 `docker compose ... up` 명령을 건너뛰고 `curl`부터 한다. `curl`은 IP로 부르므로 어느 서버에서 실행해도 된다.

### 6.1 db

**하는 일** PostgreSQL과 Qdrant를 올린다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile db up -d --wait && docker compose --profile db ps --format 'table {{.Service}}\t{{.Status}}'
```

**나와야 하는 것** `postgres`가 `Up ... (healthy)`, `qdrant`가 `Up ...`(Qdrant 이미지에는 healthcheck가 없다).

**다르면** `port is already allocated`면 5432, 6333, 6334 중 하나를 다른 프로그램이 쓴다. 사람에게 그 프로그램을 멈춰도 되는지 묻는다. 포트는 고정이라 `.env`로 바꿀 수 없다.

### 6.2 embed

**하는 일** 임베딩 모델을 vLLM으로 올리고 출력 길이가 `<DIM>`과 같은지 본다. 모델 적재에 몇 분 걸린다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile embed up -d --wait --wait-timeout 900 && curl -s http://<EMBED_IP>:8001/v1/models | python3 -c "import json,sys; print('models', [m['id'] for m in json.load(sys.stdin)['data']])"
```

**나와야 하는 것** `models ['embed']`.

**다르면** 15분이 지나도 안 뜨면 `cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose logs --tail 100 embed`를 본다. 로그에 `is not a pooling model`, `does not support embeddings`, `Runner` 같은 말이 있으면 다음으로 `.env`를 고치고 다시 올린다. `CUDA out of memory`면 `EMBED_GPU`가 다른 vLLM과 겹치는지 본다.

```bash
sed -i 's/^EMBED_EXTRA_ARGS=.*/EMBED_EXTRA_ARGS=--convert embed/' ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env && cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile embed up -d --force-recreate --wait --wait-timeout 900
```

이어서 길이를 확인한다.

```bash
curl -s http://<EMBED_IP>:8001/v1/embeddings -H 'Content-Type: application/json' -d '{"model":"embed","input":"hello"}' | python3 -c "import json,sys; print('LEN', len(json.load(sys.stdin)['data'][0]['embedding']))"
```

**나와야 하는 것** `LEN <DIM>`. 5.3절의 `<DIM>`과 같아야 한다. 운영자 서빙이라 `<DIM>`이 아직 없으면 이 숫자가 `<DIM>`이다.

**다르면** 숫자가 다르면 이 숫자가 맞는 값이다. 앱 서버에서 5.3절의 `sed` 명령을 이 숫자로 다시 실행한다.

마지막으로 `dimensions` 인자를 붙인 요청이 성공하는지 본다. 이것은 통과 조건이다. MemMachine은 벡터 컬렉션을 설정의 `dimensions`로 만들고 임베딩 요청마다 같은 값을 `dimensions`로 붙인다. 서버가 그 인자를 거절하면 MemMachine은 인자 없이 조용히 다시 보내는데, 그 결과는 모델 기본 길이라서 설정값과 다르면 첫 적재가 `dimensionality ... does not match`로 실패한다. vLLM은 모델 `config.json`에 `is_matryoshka`나 `matryoshka_dimensions`가 있을 때만 이 인자를 받는다(Qwen3-Embedding에는 없다).

```bash
curl -s http://<EMBED_IP>:8001/v1/embeddings -H 'Content-Type: application/json' -d '{"model":"embed","input":"hello","dimensions":<DIM>}' | python3 -c "import json,sys; r=json.load(sys.stdin); print('DIM-OK', len(r['data'][0]['embedding'])) if 'data' in r else print('DIM-REJECTED', str(r)[:200])"
```

**나와야 하는 것** `DIM-OK <DIM>`.

**다르면** `DIM-REJECTED`면 둘 중 하나를 한다. 모델 카드가 출력 차원을 줄여도 된다고 하면(Qwen3-Embedding은 32에서 4096까지 된다) 임베딩 서버에 `--hf-overrides '{"is_matryoshka": true}'`를 더한다. compose로 띄웠으면 아래 명령이고, 운영자 서빙이면 운영자에게 부탁한다. 그렇지 않은 모델이면 `<DIM>`을 바로 위 `LEN`의 숫자로 바꾸고 5.3절의 `sed`를 다시 한다. 어느 쪽이든 이 `curl`을 다시 실행해 `DIM-OK`를 본 뒤 넘어간다. 기억을 이미 넣은 뒤에는 바꿀 수 없다.

```bash
sed -i "s|^EMBED_EXTRA_ARGS=.*|EMBED_EXTRA_ARGS=--hf-overrides '{\"is_matryoshka\": true}'|" ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env && cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile embed up -d --force-recreate --wait --wait-timeout 900
```

### 6.3 llm

**하는 일** 채팅 모델을 vLLM으로 올리고 한 문장 답을 받아 본다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile llm up -d --wait --wait-timeout 900 && curl -s http://<LLM_IP>:8000/v1/models | python3 -c "import json,sys; print('models', [m['id'] for m in json.load(sys.stdin)['data']])"
```

**나와야 하는 것** `models ['<LLM_MODEL_NAME>']`.

**다르면** `cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose logs --tail 100 llm`을 본다. `CUDA out of memory`나 `KV cache`가 부족하다는 말이면 다음으로 `LLM_MAX_MODEL_LEN`을 줄이고 다시 올린다(그래도 부족하면 같은 꼴로 `LLM_GPU_MEMORY`를 낮춘다). 모델 형식 오류면 사람에게 모델을 확인한다.

```bash
sed -i 's/^LLM_MAX_MODEL_LEN=.*/LLM_MAX_MODEL_LEN=4096/' ~/ces2027/MemMachine/tools/ces2027_demo/deploy/.env && cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile llm up -d --force-recreate --wait --wait-timeout 900
```

이어서 답을 받아 본다.

```bash
curl -s http://<LLM_IP>:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"<LLM_MODEL_NAME>","messages":[{"role":"user","content":"Say hello in one short sentence."}],"max_tokens":64}' | python3 -c "import json,sys; m=json.load(sys.stdin)['choices'][0]['message']; print('CONTENT', repr(m.get('content'))); print('REASONING', 'yes' if m.get('reasoning_content') else 'no')"
```

**나와야 하는 것** `CONTENT '...'`에 인사 문장, `REASONING no`.

**다르면** `REASONING yes`이거나 `CONTENT`가 비어 있으면 생각(reasoning)을 먼저 출력하는 모델이다. 그대로 두면 왼쪽 카드가 답 직전까지 비어 보인다. Qwen3 계열이면 5.4절 끝의 `sed`로 thinking을 끄고 아래 명령으로 다시 올린 뒤 이 `curl`을 다시 한다(운영자 서빙이면 2.4절의 인자를 운영자에게 부탁한다). 다른 모델이면 사람에게 알리고 모델을 바꿀지 정하게 한다. 바꾸지 않기로 하면 보고서에 적는다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile llm up -d --force-recreate --wait --wait-timeout 900
```

### 6.4 app

**하는 일** MemMachine과 Open WebUI를 올리고, 계정과 Pipe와 두 모델을 만들고, 대본을 적재하고, 검사한다. MemMachine은 브랜치에서 빌드하지 않고 공개 이미지 `memmachine/memmachine:0.4.1-dev1`을 쓴다. 처음에는 이미지 둘을 내려받으므로 인터넷이 필요하고 몇 분 걸린다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile app up -d --wait && docker compose --profile app ps --format 'table {{.Service}}\t{{.Status}}' && docker inspect --format '{{index .RepoDigests 0}}' memmachine/memmachine:0.4.1-dev1
```

**나와야 하는 것** `memmachine`과 `openwebui`가 `Up ... (healthy)`, 마지막 줄에 `memmachine/memmachine@sha256:...`. 이 digest를 보고서에 적는다. 이미지를 받을 수 없어 다른 방법으로 넣었으면(USB 메모리의 tar를 `docker load` 등) 태그가 같으면 그대로 쓰인다.

**다르면** `memmachine`이 `unhealthy`나 재시작을 반복하면 `cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose logs --tail 100 memmachine`을 본다. `connection refused`나 `could not connect`가 DB 주소와 함께 나오면 `.env`의 `DB_HOST`와 6.1절을 본다. `dimension`이 들어간 오류면 5.3절의 값이 6.2절의 `LEN`과 다른 것이다. 고친 뒤 MemMachine만 다시 올린다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile app up -d --force-recreate --wait memmachine
```

이어서 세 스크립트를 순서대로 실행한다. 각 스크립트는 실행마다 한 번 로그인하므로 3분에 15번을 넘기지 않는다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo && python3 scripts/setup_openwebui.py
```

**나와야 하는 것**

```
signed in as staff@demo.local (admin)
function memmachine_pipe: created
function memmachine_pipe: enabled
model memmachine_pipe.<LLM_MODEL_NAME>: created as 'MemMachine + <LLM_MODEL_NAME>'
model <LLM_MODEL_NAME>: created as '<LLM_MODEL_NAME> (no memory)'
account settings: release notes off, personal system prompt empty
done
```

두 번째 실행부터는 `created`가 `updated`로 바뀐다.

**다르면** `sign-in failed ... HTTP 429`면 3분 기다린다. `this account is not an admin`이면 다른 계정이 먼저 가입한 것이다. 이때만 Open WebUI의 데이터 볼륨을 지우고 다시 올린 뒤 세 스크립트를 처음부터 다시 한다. 기억이 든 DB는 건드리지 않는다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose --profile app stop openwebui && docker compose --profile app rm -f openwebui && docker volume rm deploy_openwebui_data && docker compose --profile app up -d --wait openwebui
```

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo && python3 scripts/load_scenario.py scenario/script.json
```

**나와야 하는 것** `project ces-<날짜>-<시각>: Pipe valve set, previous chats deleted`, 세션 일곱 줄(`session '...': N turns, chat ...`), `done. Reload the browser to see the chats.`

**다르면** HTTP 500이면 `cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && docker compose logs --tail 100 memmachine`에서 임베딩 오류를 본다. `dimension`이 들어 있으면 5.3절과 6.2절의 값이 다른 것이고, `connection`이 들어 있으면 `EMBED_HOST`가 틀린 것이다. 고친 뒤 바로 위의 MemMachine 다시 올리기 명령을 실행하고 적재를 다시 실행한다. 적재는 매번 처음부터 다시 한다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo && python3 scripts/demo_check.py scenario/script.json
```

**나와야 하는 것** 아래 모양으로 모든 줄이 `OK`이고 마지막이 `all checks passed`. 실제 임베더이므로 Mac과 달리 `WARN`은 나오지 않는다. 이 출력 전체를 보고서에 붙인다.

```
OK   LLM server http://<LLM_IP>:8000/v1: <LLM_MODEL_NAME>
OK   embedding server http://<EMBED_IP>:8001/v1: embed
OK   MemMachine: {"status": "healthy", ...}
OK   Open WebUI: {"status": true}
OK   PostgreSQL port: <DB_IP>:5432
OK   Qdrant port: <DB_IP>:6333
OK   sign in to Open WebUI: staff@demo.local
OK   sign in as the booth account: visitor@demo.local
OK   both demo models visible to the booth account: memmachine_pipe.<LLM_MODEL_NAME>, <LLM_MODEL_NAME>
OK   chat model served by the LLM server: <LLM_MODEL_NAME>
OK   top-5 memories for 'Can you plan the menu for Mia's birthday party thi': 5 retrieved from ces-...
OK   top-5 memories for 'I am in Tokyo next week. How do I keep my training': 5 retrieved from ces-...
OK   top-5 memories for 'What gifts should I bring for Kenji and for Rosa?': 5 retrieved from ces-...
OK   top-5 memories for 'My right knee was sore again after Sunday's long r': 5 retrieved from ces-...
OK   record mode (RECORD_MEMORY) is off
OK   answer from the Pipe model: ...

all checks passed
```

**다르면** `FAIL` 줄의 끝에 이유가 있다. 앞쪽 서버 줄이 `FAIL`이면 6.1절에서 6.3절의 해당 서버를 본다. `top-5 memories` 줄이 `FAIL ... missing ['문구'] among 5 retrieved from ces-...`이면 그 질문의 기대 문구가 실제 임베더의 top-5에 없는 것이다. 이때는 대본을 바로 고치지 말고 먼저 무엇이 검색됐는지 본다.

질문에 작은따옴표(`Mia's`)가 있으므로 JSON은 heredoc으로 넘긴다. 아래 세 줄을 통째로 실행한다.

```bash
curl -s http://<APP_IP>:8080/api/v2/memories/search -H 'Content-Type: application/json' --data-binary @- <<'EOF' | python3 -c "import json,sys; [print('-', e['content'][:160]) for e in json.load(sys.stdin)['content']['episodic_memory']['long_term_memory']['episodes']]"
{"project_id":"<FAIL 줄의 ces-...>","query":"<그 질문 전문>","top_k":5}
EOF
```

검색된 다섯 문장을 사람에게 보여 주고 둘 중 하나를 고르게 한다. 빠진 사실이 다른 문장으로 검색됐으면 `scenario/script.json`의 그 질문 `expected`에서 빠진 문구를 검색된 문장 안에 실제로 있는 단어로 바꾼다. 그 세션이 아예 검색되지 않았으면 질문 문장에 그 세션의 핵심 단어를 더 넣는다. 고친 뒤 `load_scenario.py`와 `demo_check.py`를 다시 실행한다. 기대 문구는 Mac에서 mock으로 정한 것이라 바뀌는 것이 정상이며, 바뀐 내용을 보고서에 적는다.

## 7. 화면과 시간 확인

### 7.1 브라우저

**하는 일** 관객이 보는 화면을 사람이 확인한다. 사람이 쓰는 PC의 브라우저로 `http://<APP_IP>:3000`을 열고 `visitor@demo.local`과 작업표의 부스 계정 비밀번호로 들어간다. 스태프 계정으로 들어가면 Open WebUI가 관리자에게는 기능을 숨기지 않아 첨부와 마이크 단추가 보이므로, 화면 확인은 부스 계정으로 한다. 사이드바가 접혀 있으면 왼쪽 위 단추로 펼친다.

**나와야 하는 것** 사이드바에 과거 채팅 일곱 개. 새 채팅에 아바타 둘과 `<LLM_MODEL_NAME> (no memory)` 이름. 입력창에는 보내기 단추만 있고 첨부, 마이크, 음성 통화, 컨트롤 단추가 없다. 모델 목록에 두 모델만 있다. 대본의 네 질문을 차례로 보내면(아래 목록) 왼쪽에 "Retrieved 5 memories"와 날짜, 세션 제목이 붙은 목록 다음에 답이, 오른쪽에 기억 없는 답이 나온다. 질문마다 왼쪽 답이 과거 사실을 쓰고 오른쪽 답이 일반론에 그치는지 사람이 보고 한 줄씩 적는다.

1. Can you plan the menu for Mia's birthday party this Saturday?
2. I am in Tokyo next week. How do I keep my training on track while I am there?
3. What gifts should I bring for Kenji and for Rosa?
4. My right knee was sore again after Sunday's long run. What should I change this week?

오늘이 대본 날짜(2026년 11월과 12월)보다 앞서면 사이드바 묶음이 "Previous 7 days"나 "in a month"로 보이고 읽지 않음 점이 찍힌다. 브라우저 시각 기준이라 그렇고 시연 날짜(2027년 1월)에는 월별로 묶인다. 정상이다.

**다르면** 모델이 하나만 선택되어 있거나 "Model not found"가 보이면 브라우저를 새로 고친다. 오른쪽 답에 과거 사실(Mia, 땅콩, 공룡 등)이 들어가면 내장 도구 차단이 풀린 것이므로 7.3절을 본다.

사람이 캡처를 남기려면 `~/ces2027/MemMachine/docs/msr/ces2027_demo/img/` 아래에 `company_01_new_chat.png`, `company_02_comparison.png`, `company_03_past_chat.png`로 저장한다. 8장에서 함께 커밋한다. 없으면 보고서에 "캡처 없음"으로 적는다.

### 7.2 시간 재기

**하는 일** 왼쪽 목록이 뜨기까지와 오른쪽 답이 시작되기까지의 시간을 API로 잰다. 비밀번호는 `.env`에서 읽으므로 명령에 적지 않는다. 로그인 한 번이 쓰인다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo && TOKEN=$(curl -s http://<APP_IP>:3000/api/v1/auths/signin -H 'Content-Type: application/json' -d "{\"email\":\"staff@demo.local\",\"password\":\"$(grep '^ADMIN_PASSWORD=' deploy/.env | cut -d= -f2-)\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])') && for m in memmachine_pipe.<LLM_MODEL_NAME> <LLM_MODEL_NAME>; do curl -s -N -o /dev/null -w "$m: first byte %{time_starttransfer}s, total %{time_total}s\n" http://<APP_IP>:3000/api/chat/completions -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "{\"model\":\"$m\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Can you plan the menu for Mia's birthday party this Saturday?\"}]}"; done
```

**나와야 하는 것** 두 줄. 첫 줄의 `first byte`는 기억 검색이 끝나고 목록이 나오기까지, 둘째 줄의 `first byte`는 LLM의 첫 토큰까지다. 왼쪽 답의 시작은 대략 두 값의 합이다. 둘 다 수 초 안이어야 한다. 두 줄을 보고서에 적는다.

**다르면** 이 측정이 실패해도 멈추지 않는다. 사람이 브라우저에서 초를 재서 적는다. 이 질문은 기억에 저장되지 않는다(`RECORD_MEMORY`가 꺼져 있다).

### 7.3 vLLM 요청 로그

**하는 일** 두 모델 항목이 내장 도구를 보내지 않는지, 왼쪽 프롬프트에만 기억이 들어가는지 LLM 서버의 요청 로그로 본다. 5.4절에서 켠 `--enable-log-requests` 덕에 프롬프트가 로그에 남는다. LLM 역할 서버에서 실행한다. 운영자 서빙(2.4절)이면 운영자 vLLM에 `--enable-log-requests`가 있는지 묻고, 있으면 그 로그 파일이나 `journalctl -u <유닛 이름>` 출력에 아래와 같은 `grep`을 건다. 없으면 이 절은 판정할 수 없다. 보고서 4장에 "미판정: 운영자 vLLM에 요청 로그 없음"이라 적고, 대신 7.1절에서 오른쪽 답에 과거 사실이 없고 채팅 화면에 `ask_user` 같은 도구 블록이 뜨지 않는 것으로 간접 확인한 결과를 적는다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && echo "tools $(docker compose logs llm 2>&1 | grep -c -E 'search_chats|view_chat|ask_user')" && echo "memory-block $(docker compose logs llm 2>&1 | grep -c 'memories retrieved from the user')"
```

**나와야 하는 것** `tools 0`과 `memory-block 1` 이상(6.4절 검사의 질문 하나와 7.1절, 7.2절에서 왼쪽 모델로 보낸 질문 수의 합).

**다르면** `tools`가 0이 아니면 Open WebUI의 내장 도구(`search_chats`, `view_chat`, `ask_user` 등)가 모델까지 간 것이다. 채팅 화면에 "ask_user 결과 보기" 같은 도구 블록이 보이는 것도 같은 증상이다. 세팅 도구가 만든 항목이 적용된 모델에는 도구가 갈 수 없으므로(설계 5.3절), 항목이 없는 모델로 채팅했거나 세팅 도구가 실행되기 전이었던 것이다. 세팅 도구를 다시 실행하고 부스 계정으로 두 모델만 쓴 뒤 7.2절의 측정을 한 번 더 돌리고, 그 뒤의 로그만 센다. 로그는 지난 줄을 계속 가지고 있으므로 전체를 다시 세면 0이 되지 않는다.

```bash
cd ~/ces2027/MemMachine/tools/ces2027_demo/deploy && echo "tools-recent $(docker compose logs --since 5m llm 2>&1 | grep -c -E 'search_chats|view_chat|ask_user')"
```

`tools-recent 0`이면 통과다. `memory-block`이 0이면 7.1절에서 왼쪽 모델로 질문을 보냈는지 본다. 문자열 `memories retrieved from the user`는 Pipe가 왼쪽 프롬프트에 넣는 기억 블록 머리글의 일부다(`pipe/memmachine_pipe.py`의 `MEMORY_BLOCK_HEADER`).

## 8. 결과 남기기

8장은 앱 역할 서버의 clone에서 한다.

### 8.1 검증 문서 쓰기

**하는 일** `docs/msr/ces2027_demo/verification_company_<날짜>.md`를 만든다(`<날짜>`는 `date +%F`). 아래 틀을 그대로 쓰고 `<...>`를 채운다. 6.4절의 검사 출력 전체, 7.2절의 두 줄, 7.3절의 두 줄을 붙인다. 비밀번호와 `WEBUI_SECRET_KEY`는 적지 않는다.

````markdown
# CES 2027 데모 회사 검증 기록

- 날짜: <날짜>
- 환경: <서버 수와 모양(2.1절 중 어느 것), GPU 종류와 장수, OS, Docker와 Compose 버전>
- 모델: 채팅 <LLM_MODEL_NAME> (<LLM_MODEL_PATH>), 임베딩 <EMBED_MODEL> (<EMBED_MODEL_PATH>, 차원 <DIM>, dimensions 인자 <그대로 통과 | is_matryoshka override로 통과 | 기본 길이를 DIM으로>)
- 서빙: <compose의 llm, embed 프로필 | 운영자 서빙(2.4절), 채팅 인자 <있으면 enable_thinking, 요청 로그 여부>>
- 브랜치 커밋: `msr_ces2027_demo`의 `<4.3절의 해시>` (데모 도구와 문서)
- MemMachine 이미지: `memmachine/memmachine:0.4.1-dev1` (`<6.4절의 digest>`)
- 방법: [회사 실행서](company_runbook_2026-10-27.md) 4장부터 7장까지 순서대로 따랐다.

## 1. 요약

<통과했는지 한 문단. 걸린 시간. 고친 것이 있으면 무엇을 왜 고쳤는지.>

## 2. 검사 출력

```
<6.4절 demo_check.py 출력 전체>
```

## 3. 시간

```
<7.2절의 두 줄>
```

## 4. 요청 로그

```
<7.3절의 두 줄 | 미판정: 운영자 vLLM에 요청 로그 없음. 간접 확인 결과 한 줄>
```

## 5. 화면

<질문 넷에 대해 왼쪽과 오른쪽 답이 어떻게 달랐는지 한 줄씩. 캡처가 있으면 ![설명](img/company_02_comparison.png) 형식으로 넣는다. 없으면 "캡처 없음".>

## 6. 남은 일

<모델을 바꿀지, 기대 문구를 더 고칠지, 부스 장비가 이 서버와 다른지 등 사람이 정할 것.>
````

### 8.2 커밋할 파일 확인

**하는 일** 바뀐 파일이 허용된 것뿐인지 본다.

```bash
cd ~/ces2027/MemMachine && git status --short
```

**나와야 하는 것** 다음 중에서만 나온다. `docs/msr/ces2027_demo/verification_company_<날짜>.md`(새 파일), `docs/msr/ces2027_demo/img/company_*.png`(있으면), `tools/ces2027_demo/deploy/memmachine.yml`(차원), `tools/ces2027_demo/scenario/script.json`(기대 문구를 고쳤으면), `tools/ces2027_demo/scripts/setup_openwebui.py`(7.3절의 대안을 썼으면). `.env`는 나오지 않는다(gitignore).

**다르면** 그 밖의 파일이 보이면 사람에게 묻는다. `.env`가 보이면 절대 add하지 않는다.

### 8.3 커밋

**하는 일** 8.2절의 `git status`에 보인 파일을 모두 이름으로 적어 add하고 커밋한다. 아래 명령은 다섯 파일을 모두 적은 예이며, `git status`에 없는 파일은 명령에서 뺀다. 제목은 영어 한 줄, 본문은 한국어 한 문단 뒤에 영어 한 문단이다.

```bash
cd ~/ces2027/MemMachine && git add docs/msr/ces2027_demo/verification_company_<날짜>.md docs/msr/ces2027_demo/img/company_01_new_chat.png docs/msr/ces2027_demo/img/company_02_comparison.png docs/msr/ces2027_demo/img/company_03_past_chat.png tools/ces2027_demo/deploy/memmachine.yml tools/ces2027_demo/scenario/script.json tools/ces2027_demo/scripts/setup_openwebui.py && git commit -m "Docs: Add the company verification record for the CES 2027 demo" -m "회사에서 실제 vLLM(<LLM_MODEL_NAME>, <EMBED_MODEL>)로 올려 검사 스크립트가 통과한 기록이다. 임베딩 차원을 <DIM>으로 고정했다. <고친 것이 있으면 한 문장>." -m "Verification record from the company run with real vLLM servers (<LLM_MODEL_NAME>, <EMBED_MODEL>); every check passed. The embedding dimension is fixed at <DIM>. <One sentence per other change, if any>."
```

**나와야 하는 것** `[msr_ces2027_demo <해시>] Docs: Add the company verification record ...`와 바뀐 파일 수.

**다르면** `Please tell me who you are`가 나오면 이 서버에 git 사용자 이름과 이메일이 없는 것이다. 멈추고 사람에게 `git config user.name`과 `git config user.email` 설정을 부탁한 뒤 커밋 명령만 다시 실행한다. `pathspec ... did not match`면 없는 파일을 적은 것이므로 그 이름을 빼고 다시 실행한다.

### 8.4 push

**하는 일** Mac에서 pull해 볼 수 있게 같은 브랜치에 올린다. 4.2절로 받았으면 `origin`을 `fork`로 바꾼다.

```bash
cd ~/ces2027/MemMachine && git push origin msr_ces2027_demo
```

**나와야 하는 것** `<이전 해시>..<새 해시>  msr_ces2027_demo -> msr_ces2027_demo`.

**다르면** `rejected ... fetch first`면 Mac 쪽에서 먼저 올린 커밋이 있다. `git pull --rebase origin msr_ces2027_demo`를 실행하고 충돌이 없으면 push를 다시 한다. 충돌이 나거나 `Authentication failed`, `Permission denied`가 나오면 멈추고 사람에게 말한다. 커밋은 로컬에 남아 있으므로 잃지 않는다.

## 9. 보고 양식

끝났을 때, 또는 멈췄을 때 사람에게 이 양식으로 보고한다.

```
결과: <통과 | 어느 절에서 멈춤>
브랜치 커밋: 시작 <4.3절 해시>, push한 커밋 <8.4절 해시 | push 안 함>
환경: <2.1절의 모양, GPU, 모델 이름과 차원>
검사: <all checks passed | FAIL 줄 그대로>
시간: <7.2절 두 줄>
요청 로그: <7.3절 두 줄 | 미판정과 이유>
고친 것: <없음 | 파일과 한 줄 이유>
사람이 정할 것: <없음 | 항목>
```

## 10. 문제 찾기

[사용 가이드](guide_2026-10-27.md) 5장의 표에 더해 회사에서 처음 겪을 수 있는 것들이다.

| 증상 | 원인 | 조치 |
|---|---|---|
| `git clone`에 `Repository not found` | 저장소 접근 권한 없음 | 사람에게 GitHub 자격 증명을 부탁한다 |
| `could not select device driver "nvidia"` | NVIDIA Container Toolkit 없음 | 사람에게 설치를 부탁한다 |
| vLLM 로그 `CUDA out of memory` | 같은 GPU에 다른 프로세스, 또는 메모리 비율 합이 1을 넘음 | `nvidia-smi`로 점유를 보고 5.4절의 `sed` 꼴로 `LLM_GPU`, `EMBED_GPU`, 메모리 비율을 고친 뒤 6.2절 또는 6.3절의 `--force-recreate` 명령으로 다시 올린다 |
| 임베더 로그에 pooling 또는 runner 관련 오류 | 모델이 임베딩 모델로 자동 인식되지 않음 | 6.2절 "다르면"의 `--convert embed` 명령 |
| 적재 중 MemMachine 500, 로그에 `column ... does not exist` | PostgreSQL 볼륨에 다른 MemMachine 이미지(예: 브랜치에서 빌드한 것)가 만든 테이블이 남아 있음 | 멈추고 사람에게 알린다. 사람이 db 역할 서버에서 `docker compose --profile db down -v`로 볼륨을 비우고 6.1절부터 다시 한다. 에이전트는 볼륨을 지우지 않는다(3장) |
| 적재 중 MemMachine 500, 로그에 `dimensionality ... does not match` | `memmachine.yml`의 `dimensions`가 실제 출력 길이와 다름 | 6.2절의 `LEN` 값으로 5.3절의 `sed`를 다시 하고 6.4절의 MemMachine 다시 올리기 명령 뒤 적재를 다시 한다 |
| 검사의 `embedding server` 줄 끝이 `embed`가 아니다 | compose가 아닌 다른 vLLM이 8001을 쓰고 있거나, 운영자 서빙에 `embed` 별명이 없음 | 전자면 그 프로세스를 멈추고 6.2절을 다시 한다. 후자면 운영자에게 2.4절의 별명을 부탁한다 |
| 6.2절 마지막 `curl`이 `DIM-REJECTED` | 모델 설정에 Matryoshka 표시가 없어 vLLM이 `dimensions`를 거절 | 6.2절 "다르면"의 두 방법 중 하나. 그냥 두면 첫 적재가 500으로 끝난다 |
| `docker compose --profile app up`이 이미지 내려받기에서 실패 | 앱 서버에 인터넷이 없거나 프록시 필요 | 사람에게 네트워크를 확인한다. 다른 곳에서 `docker save`로 뜬 tar를 `docker load`해도 된다. 부스용 오프라인 준비물은 [이전 절차서](relocation_2026-10-27.md) 2장 |
| 채팅 화면에 "ask_user 결과 보기" 같은 도구 블록이 뜬다 | 세팅 도구의 항목이 없는 모델로 채팅함 | 세팅 도구를 다시 실행하고 부스 계정으로 두 모델만 쓴다(7.3절) |
| 왼쪽 카드에 `LLM call failed: HTTP 400 ... maximum context length` | 프롬프트가 `LLM_MAX_MODEL_LEN`을 넘음 | 5.4절의 `sed` 꼴로 값을 늘리고 6.3절의 `--force-recreate` 명령으로 LLM 서버만 다시 올린다 |
| `sign-in failed ... HTTP 429` | 3분에 15번 넘게 로그인 | 3분 기다린다 |
| 오른쪽 답에 과거 사실이 들어감 | 내장 도구 차단이 풀림 | 세팅 도구를 다시 실행하고 부스 계정으로 두 모델만 쓴다(7.3절) |
| 왼쪽 카드가 답 직전까지 비어 있다 | 생각(thinking)을 먼저 출력하는 모델 | 5.4절 끝의 `sed`로 thinking을 끄고 6.3절의 `--force-recreate` 명령. 운영자 서빙이면 2.4절 |
| 사이드바에 "in a month", 읽지 않음 점 | 대본 날짜가 오늘보다 미래 | 정상. 시연 날짜에는 월별로 묶인다 |
| MemMachine 로그의 `No module named 'spacy'` | 쓰지 않는 선택 모듈 | 무시한다 |
