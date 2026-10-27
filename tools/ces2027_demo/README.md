# CES 2027 MemMachine 비교 데모

Open WebUI의 모델 비교 화면에서 같은 질문에 대해 왼쪽은 MemMachine의 기억을 검색해 보여 주고 답하고, 오른쪽은 같은 LLM이 기억 없이 답하는 데모다. Open WebUI와 MemMachine 서버의 소스는 고치지 않는다. 설계와 근거는 [설계 문서](../../docs/msr/ces2027_demo/design_2026-10-26.md)에 있다. 전체 구조의 요약은 [아키텍처 문서](../../docs/msr/ces2027_demo/architecture_2026-10-27.md)에 있다.

## 구성

```
tools/ces2027_demo/
  deploy/docker-compose.yml   전체 스택. 프로필(local, db, app, llm, embed)로 장소와 서버를 고른다
  deploy/.env.example         장소별 값. .env로 복사해서 쓴다
  deploy/memmachine.yml       MemMachine 설정. 모든 장소에서 같다
  deploy/hosts.example        시연 화면 장비의 /etc/hosts 예시
  pipe/memmachine_pipe.py     Open WebUI Pipe 함수. 기억 검색, 목록 출력, 답변
  mock/                       개발용 LLM과 임베더 mock (Mac에서만 쓴다)
  scripts/setup_openwebui.py  스태프와 부스 계정, Pipe 설치, Valve, 두 모델의 표시 설정
  scripts/load_scenario.py    대본의 과거 세션을 Open WebUI와 MemMachine에 적재
  scripts/demo_check.py       전원을 켠 뒤 준비 상태를 한 번에 검사
  scripts/common.py           스크립트 공통 (.env 읽기, Open WebUI API 호출)
  scenario/script.json        부스 대본
  scenario/script.sample.json 대본 형식 예시
  assets/                     두 모델의 아바타 (SVG 원본과 PNG)
```

컨테이너는 다른 서버를 고정 이름 `db`, `llm`, `embed`로 부른다. 이름과 실제 주소의 대응은 `.env`에만 있으므로, 장소를 옮길 때 고치는 파일은 `.env` 하나다.

## Mac에서 올리기

Docker와 Python 3.10 이상이 있으면 된다. LLM과 임베더는 mock이 대신한다.

```bash
cd tools/ces2027_demo/deploy
cp .env.example .env            # 포트가 겹치면 OPENWEBUI_PORT, MEMMACHINE_PORT를 바꾼다
docker compose --profile local up -d --build
python3 ../scripts/setup_openwebui.py
```

이어서 대본의 과거 세션을 넣고 준비 상태를 검사한다.

```bash
python3 ../scripts/load_scenario.py ../scenario/script.sample.json
python3 ../scripts/demo_check.py ../scenario/script.sample.json
```

브라우저로 `http://127.0.0.1:3300`에 접속해 `.env`의 부스 계정(`BOOTH_EMAIL`)으로 들어가면 사이드바에 대본의 과거 채팅이 있고, 새 채팅에는 두 모델이 선택되어 있다. 대본의 질문을 보내면 왼쪽에 "Memories retrieved" 목록과 답이, 오른쪽에 기억 없는 답이 나온다.

적재 도구는 실행할 때마다 새 MemMachine 프로젝트를 만들고 채팅을 모두 지운 뒤 처음부터 넣는다. 대본을 고쳤으면 그냥 다시 실행한다. Pipe 코드나 `.env`를 고쳤으면 `setup_openwebui.py`를 다시 실행한다. 모든 것을 지우고 처음부터 하려면 `docker compose --profile local down -v`를 실행한다. MemMachine 이미지를 다른 계보로 바꿨을 때(예전에 브랜치에서 빌드한 이미지로 만든 볼륨이 남아 있을 때)도 이렇게 비워야 한다. 그대로 두면 적재가 `column "uid" of relation "episodestore" does not exist` 같은 스키마 오류로 500을 낸다.

## 회사와 부스에서 올리기

회사에서 처음 올리는 사람(또는 Claude Code)은 git clone부터 검증 결과 push까지 한 단계씩 적은 [회사 실행서](../../docs/msr/ces2027_demo/company_runbook_2026-10-27.md)를 따른다. 아래는 그 요약이다.

준비물은 서버마다 Docker와 Docker Compose(프로필을 지원하는 v2), GPU 서버에는 NVIDIA 드라이버와 NVIDIA Container Toolkit, 그리고 모델 가중치 디렉터리다. 브랜치를 pull한 뒤 서버마다 다음 순서로 한다.

1. `deploy/.env.example`을 `.env`로 복사하고 부스 값을 적는다. 다른 서버의 IP(`DB_HOST`, `LLM_HOST`, `EMBED_HOST`, `APP_HOST`), 공개 포트(`OPENWEBUI_PORT=3000`, `MEMMACHINE_PORT=8080`), 시연 장비의 시간대(`TZ=America/Los_Angeles`), 모델 이름(`LLM_MODEL_NAME`), vLLM 이미지와 가중치 경로, GPU 번호와 메모리 비율이다. 회사 검증에서 H100 두 장이 한 서버에 있으면 `LLM_GPU=0`, `EMBED_GPU=1`로 두고 두 프로필을 같은 서버에서 올린다.
2. 임베딩 모델을 정했으면 `deploy/memmachine.yml`의 `dimensions`를 그 모델의 차원으로 고친다. 기억을 넣은 뒤에는 바꾸지 않는다.
3. 시연 화면 장비의 `/etc/hosts`에 `deploy/hosts.example`의 줄을 넣는다. 브라우저가 `http://app:3000`을 찾기 위해서이며, 스크립트는 `.env`의 IP를 쓴다.
4. 서버 역할에 맞는 프로필로 올린다. MemMachine은 공개 이미지 `memmachine/memmachine:0.4.1-dev1`을 내려받아 쓰고 브랜치에서 빌드하지 않는다. vLLM 두 대를 운영자가 이미 띄워 둔 곳에서는 `llm`, `embed` 프로필을 올리지 않고 실행서 2.4절의 조건을 운영자와 맞춘다.

```bash
cd tools/ces2027_demo/deploy
docker compose --profile db up -d            # DB 서버: PostgreSQL + Qdrant
docker compose --profile llm up -d           # LLM 서버: vLLM 채팅 모델 (8000)
docker compose --profile embed up -d         # 임베더 서버: vLLM 임베딩 모델 (8001)
docker compose --profile app up -d           # 앱 서버: MemMachine + Open WebUI
python3 ../scripts/setup_openwebui.py        # 앱 서버에서 한 번. 계정, Pipe, 두 모델 항목
python3 ../scripts/load_scenario.py ../scenario/script.json   # 실제 대본
python3 ../scripts/demo_check.py ../scenario/script.json
```

vLLM은 모델 적재에 몇 분이 걸린다. `docker compose ps`의 상태가 healthy가 된 뒤 세팅 스크립트를 실행한다. 전원을 다시 켜면 모든 컨테이너가 스스로 올라오므로 그 뒤에는 검사 스크립트만 돌리면 된다.

## 회사에서 확인할 것

Mac에서는 mock으로만 확인했다. 실제 vLLM으로 처음 올릴 때 다음을 보고, 결과를 `docs/msr/ces2027_demo/verification_company_<날짜>.md`에 적어 커밋한다(틀은 실행서 8.1절).

- [ ] `llm`과 `embed` 프로필이 뜨고 `curl http://llm:8000/v1/models`, `curl http://embed:8001/v1/models`가 모델을 보여 준다. 임베딩 모델이 자동 변환되지 않으면 `EMBED_EXTRA_ARGS=--convert embed`를 준다.
- [ ] `dimensions`를 붙인 임베딩 요청이 성공한다(실행서 6.2절의 `DIM-OK`). 거절되면 MemMachine이 인자 없이 다시 보내지만 그 결과는 모델 기본 길이라 설정값과 다르면 첫 적재가 500으로 끝난다. 모델 설정에 Matryoshka 표시가 없으면(Qwen3-Embedding) `EMBED_EXTRA_ARGS=--hf-overrides '{"is_matryoshka": true}'`를 주거나 `dimensions`를 기본 길이로 맞춘다.
- [ ] 첫 적재(`load_scenario.py`)가 성공한다.
- [ ] `demo_check.py`가 전부 통과한다.
- [ ] 비교 화면에서 왼쪽에 목록과 답, 오른쪽에 기억 없는 답이 나오고, 답이 수 초 안에 시작한다. 걸린 시간을 적는다.
- [ ] vLLM 로그에 `tools`가 들어간 요청이 없고, 채팅 화면에 `ask_user` 같은 도구 블록이 뜨지 않는다. 운영자 vLLM에 요청 로그가 없으면 "미판정"으로 적는다. 있으면 세팅 도구의 항목이 없는 모델로 채팅한 것이다(세팅 도구 실행 전이거나, 항목이 없는 다른 모델을 고른 경우). 세팅 도구를 다시 실행하고 부스 계정으로 들어가 두 모델만 쓴다. 부스 계정에는 그 두 모델만 보인다(설계 5.3절).
- [ ] 부스 계정으로 들어간 화면의 입력창에 첨부, 마이크, 음성 통화, 컨트롤 단추가 없고, 모델 목록에 두 모델만 있다.
- [ ] 모델 드롭다운에서 `MemMachine + <모델>`과 `<모델> (no memory)`가 보이고, 모델을 두 개 띄웠다면 둘 사이의 전환이 된다.
- [ ] 생각(reasoning) 모델이면 `reasoning_content`가 먼저 흐르는 동안 카드가 비어 보인다. Qwen3 계열은 `LLM_EXTRA_ARGS=--default-chat-template-kwargs '{"enable_thinking": false}'`로 끈다(실행서 5.4절). 다른 모델이면 모델을 바꾼다.
