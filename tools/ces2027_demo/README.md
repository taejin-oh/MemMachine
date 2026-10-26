# CES 2027 MemMachine 비교 데모

Open WebUI의 모델 비교 화면에서 같은 질문에 대해 왼쪽은 MemMachine의 기억을 검색해 보여 주고 답하고, 오른쪽은 같은 LLM이 기억 없이 답하는 데모다. Open WebUI와 MemMachine 서버의 소스는 고치지 않는다. 설계와 근거는 [설계 문서](../../docs/msr/ces2027_demo/design_2026-10-26.md)에 있다.

## 구성

```
tools/ces2027_demo/
  deploy/docker-compose.yml   전체 스택. 프로필(local, app, db)로 장소를 고른다
  deploy/.env.example         장소별 값. .env로 복사해서 쓴다
  deploy/memmachine.yml       MemMachine 설정. 모든 장소에서 같다
  pipe/memmachine_pipe.py     Open WebUI Pipe 함수. 기억 검색, 목록 출력, 답변
  mock/                       개발용 LLM과 임베더 mock (Mac에서만 쓴다)
  scripts/setup_openwebui.py  계정, Pipe 설치, Valve, 두 모델의 표시 설정
  scripts/common.py           스크립트 공통 (.env 읽기, Open WebUI API 호출)
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

브라우저로 `http://127.0.0.1:3300`에 접속해 `.env`의 계정으로 들어가면 새 채팅에 두 모델이 선택되어 있다. 질문을 보내면 왼쪽에 "Memories retrieved" 목록과 답이, 오른쪽에 기억 없는 답이 나온다. 아직 기억을 넣기 전이라 목록은 비어 있다.

Pipe 코드나 `.env`를 고쳤으면 `setup_openwebui.py`를 다시 실행한다. 모든 것을 지우고 처음부터 하려면 `docker compose --profile local down -v`를 실행한다.

## 회사와 부스에서 올리기

서버마다 `.env`에 다른 서버의 IP, 공개 포트(`OPENWEBUI_PORT=3000`, `MEMMACHINE_PORT=8080`), 시연 장비의 시간대(`TZ=America/Los_Angeles`), 모델 이름과 주소를 적고, 서버 역할에 맞는 프로필로 올린다. 앱 서버에서는 올린 뒤 세팅 스크립트를 한 번 실행한다. vLLM 서버용 프로필은 구현 3단계에서 추가한다.

```bash
docker compose --profile db up -d     # DB 서버: PostgreSQL + Qdrant
docker compose --profile app up -d    # 앱 서버: MemMachine + Open WebUI
python3 ../scripts/setup_openwebui.py # 앱 서버에서 한 번. 계정, Pipe, 두 모델 항목
```

임베딩 모델을 정하면 `deploy/memmachine.yml`의 `dimensions`를 그 모델의 차원으로 한 번 고친다. 그 뒤에는 바꾸지 않는다.
