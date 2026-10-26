# CES 2027 데모 Mac 검증 기록

- 날짜: 2026-10-27
- 환경: MacBook(16GB, Docker VM 8GB, immich 등 다른 컨테이너 동작 중), Docker 29.4, Compose v5.1, Python 3.14. LLM과 임베더는 `mock/`의 가짜 서버.
- 대상 커밋: `msr_ces2027_demo` 브랜치의 `c3a33300`까지.
- 방법: [사용 가이드](guide_2026-10-27.md) 2장을 처음부터 그대로 따랐다. `docker compose --profile local down -v`로 볼륨까지 지운 뒤 올렸다.

## 1. 요약

가이드 2장의 명령이 순서대로 모두 통과했다. 볼륨 삭제부터 검사 통과까지 1분이 걸렸다(이미지는 미리 받아 둔 상태). 비교 화면에 왼쪽 목록과 답, 오른쪽 기억 없는 답이 설계 시안대로 나오고, 사이드바의 과거 채팅을 열면 대본의 질문과 답과 시각이 그대로 있다. Mac에서 확인할 수 없는 것은 실제 임베더의 검색 품질(기대 문구가 top-5에 드는지)과 vLLM 두 대의 기동이며, 이 둘은 회사 검증 항목이다(README의 체크리스트).

## 2. 명령과 출력

### 2.1 스택 올리기

```
== 00:25:01 down -v
 Volume deploy_qdrant_data Removed
 Volume deploy_openwebui_data Removed
== 00:25:11 up --build --wait
 Container deploy-mock-1 Healthy
 Container deploy-qdrant-1 Healthy
 Container deploy-memmachine-1 Healthy
 Container deploy-postgres-1 Healthy
 Container deploy-openwebui-1 Healthy
SERVICE      STATUS
memmachine   Up 15 seconds (healthy)
mock         Up 15 seconds
openwebui    Up 15 seconds (healthy)
postgres     Up 15 seconds (healthy)
qdrant       Up 15 seconds
```

### 2.2 세팅, 적재, 검사

```
== 00:25:46 setup
signed in as staff@demo.local (admin)
function memmachine_pipe: created
function memmachine_pipe: enabled
model memmachine_pipe.mock-llm-a: created as 'MemMachine + mock-llm-a'
model mock-llm-a: created as 'mock-llm-a (no memory)'
account settings: release notes off, personal system prompt empty
done
== 00:25:47 load
project ces-20261027-002547: Pipe valve set, previous chats deleted
session 'Peanut allergy and school lunches': 6 turns, chat ce470a8f-...
session 'Planning Mia's 7th birthday': 6 turns, chat 821f8e39-...
session 'Weekend hosting and the family': 6 turns, chat 27bcb22e-...
session 'Half marathon training plan': 6 turns, chat a8285a20-...
session 'Tokyo work trip in January': 6 turns, chat 22b10618-...
session 'Learning Spanish for Rosa': 6 turns, chat ab751eaa-...
session 'Home office and back pain': 4 turns, chat ac906fbb-...
done. Reload the browser to see the chats.
== 00:25:49 check
OK   LLM server http://127.0.0.1:8000/v1: mock-llm-a, mock-llm-b
OK   embedding server http://127.0.0.1:8001/v1: mock-llm-a, mock-llm-b
OK   MemMachine: {"status": "healthy", "service": "memmachine", "version": "0.0.0"}
OK   Open WebUI: {"status": true}
OK   PostgreSQL port: 127.0.0.1:5432
OK   Qdrant port: 127.0.0.1:6333
OK   sign in to Open WebUI: staff@demo.local
OK   both demo models listed in Open WebUI: memmachine_pipe.mock-llm-a, mock-llm-a
OK   chat model served by the LLM server: mock-llm-a
WARN top-5 memories for 'Can you plan the menu for Mia's birthday party thi': missing ['dinosaurs', 'vegetarian'] among 5 retrieved
OK   top-5 memories for 'I am in Tokyo next week. How do I keep my training': 5 retrieved
WARN top-5 memories for 'What gifts should I bring for Kenji and for Rosa?': missing ['whisky', 'gardening'] among 5 retrieved
WARN top-5 memories for 'My right knee was sore again after yesterday's lon': missing ['kettlebell'] among 5 retrieved
     (mock embedder: expected phrases are matched by word overlap only; verify with the real embedder)
OK   record mode (RECORD_MEMORY) is off
OK   answer from the Pipe model: (mock, with memory) Using 5 memories. The first one says: [Nov 23, 2026 | Half m
all checks passed
```

`WARN` 세 줄은 mock 임베더가 단어 겹침으로만 검색하기 때문이며 실패로 세지 않는다. 형식 예시 대본(`script.sample.json`, 세션 셋)으로는 같은 검사가 전부 `OK`였다.

### 2.3 메모리

| 컨테이너 | 사용량 | 상한 |
|---|---|---|
| openwebui | 1.05GiB | 1.5GiB |
| memmachine | 267MiB | 1GiB |
| postgres | 86MiB | 512MiB |
| qdrant | 74MiB | 512MiB |
| mock | 33MiB | 256MiB |

## 3. 화면

headless Chromium(Playwright)으로 1600x1000에서 찍었다. Chrome 확장이 연결되지 않아 사람이 보는 브라우저 대신 썼다.

새 채팅 화면. 두 모델이 선택되어 있고(아바타 둘), 추천 프롬프트가 없다. 사이드바는 날짜를 석 달 당긴 대본 복사본으로 찍어 부스 시점처럼 월별로 묶인 모습이다. 실제 대본 날짜(11월과 12월)는 오늘 기준으로 미래라 "Previous 7 days"와 읽지 않음 점으로 보인다(설계 부록 A.22).

![새 채팅](img/01_new_chat.png)

비교 화면. 왼쪽은 "Retrieved 5 memories" 상태와 날짜, 세션 제목이 붙은 목록 뒤에 mock의 "with memory" 답, 오른쪽은 기억 없는 답이다.

![비교 화면](img/02_comparison.png)

사이드바의 과거 채팅을 연 화면. 대본의 질문과 답이 그대로 있고, 메시지에 마우스를 올리면 시각이 보인다(브라우저의 시간대 기준).

![과거 채팅](img/03_past_chat.png)

## 4. 추가로 확인한 것

- LLM 서버를 끄면 모델 목록 조회가 1초 안에 끝나고 드롭다운에 `MemMachine pipe: cannot reach ...` 항목이 뜬다. 켜면 브라우저 새로 고침 뒤 복구된다.
- mock에 `[llm-error]`를 보내면 왼쪽 카드에 `LLM call failed: HTTP 500 ...`가 보인다.
- `RECORD_MEMORY`를 켜고 검사하면 `FAIL` 두 줄과 종료 코드 1이 나온다.
- 시간대: `.env`의 `TZ`를 서울로 두면 목록의 날짜가 서울 기준으로, LA로 두면 LA 기준으로 바뀐다.
- MemMachine 로그의 `No module named 'spacy'`는 쓰지 않는 retrieval agent의 선택 모듈이며 동작에 영향이 없다.
- 두 번 실행해도 결과가 같다. 세팅 스크립트는 `updated`를, 적재 도구는 새 프로젝트 ID를 찍는다.

## 5. 회사에서 확인할 것

README의 "회사에서 확인할 것" 목록 그대로다. 실제 임베더로 적재했을 때 네 질문의 기대 문구가 top-5에 드는지, vLLM 두 대가 뜨고 `dimensions` 재시도가 동작하는지, 답이 수 초 안에 시작하는지, vLLM 로그에 `tools`가 없는지를 보고 `verification_<날짜>.md`로 남긴다.
