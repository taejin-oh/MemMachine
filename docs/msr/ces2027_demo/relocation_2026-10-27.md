# CES 2027 데모 이전 절차서

- 작성일: 2026-10-27
- 대상: 한국에서 세팅과 리허설을 마친 서버 네 대와 시연 화면 장비를 미국 부스로 옮겨 다시 켜는 사람
- 전제: [설계 문서](design_2026-10-26.md) 6장의 원칙(완전 오프라인, 고정 IP와 호스트 이름, 전원만 켜면 자동 기동, 볼륨과 백업으로 데이터 보존, 명령 하나로 준비 상태 확인)이 구현되어 있고, [가이드](guide_2026-10-27.md)대로 올린 상태에서 리허설까지 끝났다.

## 1. 요약

미국에서 해야 할 일은 배선 복구, 전원 켜기, 검사 스크립트 실행, 브라우저 열기 네 가지다. 설정은 한국에서 끝내고 디스크에 남겨 두므로 미국에서는 아무것도 고치지 않는다. 이 문서는 그 상태를 만들기 위해 한국에서 끄기 전에 할 일과, 미국에서 켠 뒤 확인할 순서를 적는다. 시계와 시간대는 미국에서 손대지 않는다. 사이드바의 날짜 묶음은 브라우저의 현재 시각 기준이므로 시연 장비의 시계만 맞으면 된다.

## 2. 한국에서 끄기 전에

1. 마지막 리허설을 끝낸 상태 그대로 둔다. 적재 도구를 다시 실행하지 않는다. 실행하면 새 프로젝트가 만들어지고 사이드바의 채팅이 지워졌다가 다시 들어가므로, 다시 실행했다면 검사 스크립트까지 다시 돌린다.
2. 앱 서버에서 `python3 scripts/demo_check.py scenario/script.json`이 전부 통과하는지 마지막으로 본다. 출력을 복사해 둔다.
3. USB 메모리에 복구 재료를 모은다. 각 서버의 `deploy/.env`와 `/etc/hosts`, 브랜치 clone 전체, 그리고 설계 6.3절대로 `docker save`로 뜬 이미지 tar(Open WebUI, pgvector, Qdrant, vLLM, 공개 MemMachine 이미지 `memmachine/memmachine:0.4.1-dev1`, 백업용 alpine)다. 인터넷이 없는 부스에서 서버를 교체하려면 이것이 전부 있어야 한다.
4. DB 서버에서 볼륨을 백업한다. `docker compose --profile db stop`으로 멈춘 뒤 `docker run --rm -v deploy_postgres_data:/d -v $PWD:/b alpine tar czf /b/postgres_data.tgz -C /d .`과 같은 명령으로 PostgreSQL과 Qdrant 볼륨을 tar로 떠서 USB 메모리에 둔다. 앱 서버의 `deploy_openwebui_data`도 같은 방법으로 뜬다. 백업이 끝나면 반드시 `docker compose --profile db up -d`(앱 서버는 `--profile app`)로 다시 올리고 `docker compose ps`에서 모두 `Up`인지 확인한다. 손으로 멈춘 컨테이너는 `restart: unless-stopped`가 부팅 때 되살리지 않으므로, 멈춘 채 끄면 미국에서 아무것도 올라오지 않는다. 적재는 몇 초면 다시 할 수 있지만, 볼륨을 되돌리는 쪽이 사이드바의 채팅 ID까지 그대로 유지한다.
5. 서버마다 `docker compose --profile <역할> down`이 아니라 운영체제 종료를 쓴다. `down`을 하면 컨테이너가 지워져 부팅 때 자동으로 올라오지 않는다. 정상 종료 순서는 앱 서버, LLM 서버, 임베더 서버, DB 서버다.
6. 전원을 끈 뒤 전원선과 네트워크선을 뽑고, 각 선과 포트에 서버 이름(`app`, `llm`, `embed`, `db`)을 적은 라벨을 붙인다. 스위치와 시연 장비도 함께 포장한다.
7. 서버마다 부팅 때 Docker 데몬이 시작되도록 되어 있는지(`systemctl is-enabled docker`가 `enabled`), 그리고 끄기 직전에 모든 컨테이너가 `Up`인지 다시 확인한다. 끈 뒤 한 번 켜서 저절로 올라오고 검사 스크립트가 통과하는 것까지 보는 것이 가장 확실하다.
8. 리허설 때 시연 장비의 시간대를 서울로 두었다면 앱 서버의 `.env`에서 `TZ=America/Los_Angeles`로 되돌리고 `docker compose --profile app up -d openwebui`를 실행한다. 목록의 날짜가 사이드바의 시각과 같은 시간대로 보여야 한다. 회사 검증 때 LLM 서버의 `.env`에 `LLM_EXTRA_ARGS=--enable-log-requests`를 넣었다면([회사 실행서](company_runbook_2026-10-27.md) 5.4절) 그 인자만 지우고(`--default-chat-template-kwargs ...`처럼 모델에 필요한 인자는 남긴다) `docker compose --profile llm up -d --force-recreate`로 LLM 서버를 다시 올린다. 프롬프트가 로그에 쌓이지 않게 하기 위해서다.

## 3. 미국에서 켜기

1. 라벨대로 스위치에 서버 네 대와 시연 장비를 연결한다. 인터넷은 연결하지 않는다.
2. 전원을 켜는 순서는 DB 서버, 임베더 서버, LLM 서버, 앱 서버다. 순서가 바뀌어도 `restart: unless-stopped` 정책 때문에 결국 올라오지만, 이 순서가 가장 빨리 안정된다.
3. vLLM 두 대는 모델을 적재하는 데 몇 분이 걸린다. GPU 서버에서 `docker compose ps`의 상태가 `healthy`가 될 때까지 기다린다. 10분이 지나도 `starting`이면 `docker compose logs llm`을 본다.
4. 시연 장비에서 터미널을 열고 앱 서버에 접속하거나, 시연 장비에 브랜치가 있으면 거기서 `python3 scripts/demo_check.py scenario/script.json`을 실행한다. 전부 `OK`여야 한다.
5. 브라우저로 `http://app:3000`을 열고 `.env`의 스태프 계정으로 들어간다. 사이드바에 과거 채팅 일곱 개가 11월과 12월로 묶여 있고, 새 채팅에 두 모델이 선택되어 있으면 준비가 끝난 것이다. 화면 왼쪽의 사이드바가 접혀 있으면 왼쪽 위 단추로 한 번 펼친다. 이 설정은 브라우저에 남는다.
6. 대본의 첫 질문을 한 번 보내 두 답이 수 초 안에 시작하는지 본다. 이 질문은 시연 중의 질문과 같으며 기억에 저장되지 않는다.

## 4. 문제가 생겼을 때

| 증상 | 확인 | 조치 |
|---|---|---|
| 검사 스크립트의 `LLM server` 또는 `embedding server`가 `FAIL` | 해당 서버의 전원과 네트워크선, `docker compose ps` | 올라오는 중이면 기다린다. `exited`면 `docker compose --profile llm up -d`로 다시 올린다 |
| `MemMachine`이 `FAIL` | 앱 서버의 `docker compose logs memmachine` | DB 서버가 늦게 켜졌으면 재시작 정책으로 몇 분 안에 올라온다. 안 되면 `docker compose --profile app restart memmachine` |
| `top-5 memories`가 `FAIL` | Pipe의 Valve `PROJECT_ID`가 마지막 적재의 프로젝트인지(검사 출력의 `retrieved from` 뒤) | DB 볼륨을 되돌렸다면 그때의 프로젝트 ID와 Valve가 맞는지 본다. 맞지 않으면 적재 도구를 다시 실행한다 |
| `record mode`가 `FAIL` | 관리자 화면의 Functions > MemMachine > Valves | `RECORD_MEMORY`를 끈다 |
| 브라우저에 모델이 "Model not found"로 나온다 | LLM 서버가 켜진 뒤 모델 목록이 아직 갱신되지 않았다 | 브라우저를 새로 고친다 |
| 왼쪽 카드에 `Memory search failed` | 앱 서버에서 MemMachine 로그 | DB 서버 연결을 본다. 검사 스크립트의 `PostgreSQL port`, `Qdrant port` |
| 왼쪽 카드에 `LLM call failed`, 오른쪽도 답이 없다 | LLM 서버 로그 | vLLM이 재시작 중이면 기다린다. 문맥 길이 오류면 `.env`의 `LLM_MAX_MODEL_LEN`을 늘리고 LLM 서버만 다시 올린다 |
| 서버 한 대가 켜지지 않는다 | 전원과 디스크 | 예비 장비에 USB 메모리의 `.env`, `/etc/hosts`, 볼륨 백업을 넣고 같은 역할의 프로필로 올린다. 브랜치는 앱 서버의 clone을 복사한다 |

## 5. 시연이 끝난 뒤

1. 녹음 Valve를 시연 중 켰다면 끈다.
2. 다음 시연 전에 사이드바에 시연 중의 질문 채팅이 쌓여 있으면 적재 도구를 다시 실행해 처음 상태로 돌린다. 적재 도구는 새 프로젝트를 만들고 채팅을 모두 지운 뒤 대본을 다시 넣는다. 그 뒤 검사 스크립트를 돌린다.
3. 철수할 때는 2장의 종료 순서를 따른다.
