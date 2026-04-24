# MemMachine Code Review

전체 리포 (server / common / client / ts-client / meta 패키지, 인프라, CI, 통합, 예제, 평가, 문서)를 대상으로 한 코드 품질·구조·버그 리뷰.
모든 발견 사항은 실제 파일을 직접 확인해 재현 가능성을 검증했습니다.

## Executive Summary

| 심각도 | 건수 | 핵심 영향 |
|---|---|---|
| CRITICAL | 2 | 신규 사용자 온보딩 실패 (README 문법 오류), async DB 헬퍼 런타임 크래시 |
| HIGH | 8 | 자원 정리 실패, 클라이언트 close 상태 미전파, 비밀 유출 리스크, Dockerfile 재현성 |
| MEDIUM | 10 | API 계약 모호, MCP identity spoofing 가능성, 부분 삭제, 스타일 비일관성 |
| LOW | 6 | CI 버전 불일치, 거대 클래스, 비활성 TODO 주석 |

권장 우선순위:
1. `README.md:49` 문법 오류 (1분 수정)
2. `database_manager.py`의 `asyncio.run()` 제거 (async 컨텍스트 충돌)
3. `Memory._client_closed` 상태 전파 수정
4. TypeScript catch 블록 타입 안전성 (`handleAPIError` 반환 타입 `never`)
5. Dockerfile/빌드 스크립트 보안·재현성

---

## 리포 구조 개요

```
packages/
  server/     FastAPI 서버, episodic/semantic/profile memory, MCP (stdio/http), resource manager
  common/     Pydantic API 스키마, 공유 모델
  client/     Python SDK (sync, requests 기반)
  ts-client/  TypeScript SDK (axios 기반)
  meta/       메타 패키지 (문서/버전)
integrations/ crewai, langchain, llamaindex, langgraph, aws_strands_agent_sdk, dify, fastgpt, n8n
examples/     v1, simple_chatbot, openai_agent, qwen_agent, ts_rest_client_demo
evaluation/   episodic_memory (LongMemEvalS, LoCoMo), retrieval_agent (LoCoMo, HotpotQA, WikiMultihop)
tools/        chatgpt2memmachine, migration (v0.1.x 덤프 스크립트)
```

패키지 의존 방향은 `common → client/ts-client`, `common → server` 단방향이며 순환 참조는 발견되지 않음.

---

## CRITICAL

### C1. `README.md` 퀵스타트 코드에 `SyntaxError`

- 파일: `README.md:49`
  ```python
  from memmachine_client import import MemMachineClient
  ```
- `import` 키워드가 중복됨. 복붙한 사용자는 즉시 `SyntaxError: invalid syntax`.
- `USAGE.md`와 `examples/`는 모두 `from memmachine_client import MemMachineClient`로 올바름 — README만 드리프트.
- 수정: 중복 `import` 제거.

### C2. 동기 래퍼가 `asyncio.run()`으로 비동기 초기화를 감쌈 — 이벤트 루프 내부 호출 시 크래시

- 파일: `packages/server/src/memmachine_server/common/resource_manager/database_manager.py:185, 283`
  ```python
  def get_neo4j_driver(self, name: str) -> AsyncDriver:
      return asyncio.run(self.async_get_neo4j_driver(name, validate=True))

  def get_sql_engine(self, name: str) -> AsyncEngine:
      return asyncio.run(self.async_get_sql_engine(name, validate=True))
  ```
- FastAPI 요청 핸들러처럼 이미 이벤트 루프 안에서 호출되면 `RuntimeError: asyncio.run() cannot be called from a running event loop`.
- 호출부를 `async def`로 바꾸고 `async_get_*`를 직접 `await`하거나, 별도 스레드/루프에서만 허용하도록 분리.

---

## HIGH

### H1. `Memory._client_closed` 플래그가 영구히 False

- 파일: `packages/client/src/memmachine_client/memory.py:138, 290…1482, 1814`
- `__init__`에서 `self._client_closed = False`로 초기화되고 모든 메서드가 체크하지만 **어디에서도 True로 설정되지 않음**.
  - `mark_client_closed()` 메서드(`memory.py:1814`)는 존재하지만 테스트(`test_memory.py:924`) 외에 호출 없음.
  - `MemMachineClient.close()` (`client.py:553`)는 Memory 인스턴스에 통지하지 않음.
- 결과: 클라이언트 `close()` 뒤에도 "client has been closed" 에러 대신 `requests.ConnectionError`가 터짐 → 설계된 안전장치가 무력화.
- 수정: `_client_closed` 체크를 `self.client.closed` 참조로 교체, 혹은 `MemMachineClient.close()`가 등록된 Memory들의 `mark_client_closed()`를 호출하도록 연결.

### H2. 리소스 정리 경로의 광범위 `except Exception` 스왈로우

- 파일: `packages/server/src/memmachine_server/common/resource_manager/database_manager.py:104, 112, 316`
  ```python
  except Exception as ex:
      logger.warning("Error closing Neo4j driver '%s': %s", name, ex)
  ```
- 종료 시 커넥션이 덜 닫혀도 경고 한 줄만 남고 진행. 장기 운영 시 누수 탐지 지연.

### H3. `semantic_ingestion.py`의 `ExceptionGroup` 처리 누락 가능성

- 파일: `packages/server/src/memmachine_server/semantic_memory/semantic_ingestion.py:120`
- `asyncio.TaskGroup`에서 예외 발생 시 `ExceptionGroup`으로 전파. 호출부(`server/api_v2/service.py` 등)가 일반 `Exception`만 잡으면 HTTP 500 대신 서버 크래시 가능.
- 수정: 호출부에 `except*` 또는 명시적 `ExceptionGroup` 핸들링 추가.

### H4. `semantic_ingestion.py:174-180` bare `except Exception` + 조건부 `raise`

```python
except Exception:
    logger.exception("Failed to delete messages...")
    if self._debug_fail_loudly:
        raise
```
- 기본 경로가 예외 삼킴. 디버그 플래그에만 의존해 관측성 저하.

### H5. 멀티워커 + 모듈 레벨 `app` 초기화 타이밍

- 파일: `packages/server/src/memmachine_server/server/app.py:92-107`
- `app` 객체를 모듈 임포트 시 생성하고, 설정 로드 후 "조건부"로 config 라우터를 추가. 워커마다 타이밍이 다르면 일부 워커에서 특정 라우트가 404 반환 가능.

### H6. TypeScript catch 블록이 `handleAPIError` 뒤 암묵적 `undefined` 반환

- 파일: `packages/ts-client/src/project/memmachine-project.ts:103-108, 122-127, 141-146, 160-165` (memory.ts 유사 패턴)
  ```typescript
  catch (error: unknown) {
    handleAPIError(error, `Failed ... payload: ${JSON.stringify(payload)}`)
    // 명시적 throw/return 없음
  }
  ```
- `handleAPIError`가 throw한다고 가정하지만 반환 타입이 `never`가 아니면 TS는 catch 정상 종료를 허용 → `Promise<T>` 선언이어도 실제로 `undefined` 반환 경로 생김.
- 수정: `handleAPIError` 시그니처를 `(...args): never`로 변경하거나 catch 끝에 `throw` 추가.

### H7. 에러 메시지에 요청 payload 전체 JSON이 들어감

- 파일: `packages/ts-client/src/project/memmachine-project.ts:107, 126, 145, 164` 등
  ```typescript
  handleAPIError(error, `Failed to create project with payload: ${JSON.stringify(payload)}`)
  ```
- `user_id`, metadata, 메모리 콘텐츠가 그대로 로그에 기록됨 — PII / 비밀 유출 리스크.

### H8. 빌드·배포 인프라 보안·재현성

- `Dockerfile:17` — `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/`. `:latest` 태그로 uv 업데이트에 따라 이미지 재현 불가.
- `Dockerfile` HEALTHCHECK 부재 — `EXPOSE 8080`만 있고 라이브니스 훅 없음. docker-compose에는 헬스체크가 있으나 plain Docker/k8s는 감지 불가.
- `build-docker.sh` — Docker 로그인 시 `--user`, `--token` CLI 인자 전달은 `ps aux` / 쉘 히스토리 / CI 로그에 노출. stdin 또는 env var로 전달해야 함.
- `memmachine-compose.sh:6` — `set -e`만 있고 `set -u` 누락. 변수명 오타가 빈 문자열로 통과.

---

## MEDIUM

### M1. `packages/common` 패키지가 API 모델을 재수출하지 않음

- 파일: `packages/common/src/memmachine_common/__init__.py` (도큐스트링만 존재)
- 사용자는 `from memmachine_common.api import ...`를 강제받음. `client` 패키지의 `__all__` 스타일과 불일치.

### M2. `memory.py`가 `builtins.list[...]` 비관용적 사용

- 파일: `packages/client/src/memmachine_client/memory.py:10, 260`
  ```python
  import builtins
  ...
  memory_types: builtins.list[MemoryType] | None = None
  ```
- Python 3.10+에서는 `list[MemoryType] | None`으로 충분. `builtins` 임포트 제거 가능.

### M3. `langgraph.py::add_memory` try/except/else가 동작은 하지만 파묻힘

- 파일: `packages/client/src/memmachine_client/langgraph.py:167-192`
- 로직 자체는 정상:
  - `results` truthy → try 내부 `return`
  - `results` falsy → try 정상 종료 → `else` → "Failed to add memory"
  - 예외 → `except` → "Error adding memory"
- 문제는 `except Exception:` 뒤 원인 로깅이 전혀 없어 실제 장애 시 디버깅이 막힘. `logger.exception(...)` 추가 권장.

### M4. `asyncio.gather(delete_episodes, delete_semantics)` — 부분 삭제 위험

- 파일: `packages/server/src/memmachine_server/server/api_v2/service.py:91` 부근
- 한쪽이 실패하면 `gather`가 즉시 예외 전파 → 다른 쪽이 취소되거나 실행 안 됨. 데이터 반(半) 삭제 상태 유발 가능.
- 수정: `return_exceptions=True` 후 개별 결과를 확인하고 로깅 → 재시도 정책.

### M5. MCP 서버의 env var 컨텍스트 오버라이드 (identity spoofing 소지)

- 파일: `packages/server/src/memmachine_server/server/api_v2/mcp.py:157-165, 282-284`
- `MM_ORG_ID`, `MM_PROJ_ID`, `MM_USER_ID` 환경변수가 요청별 컨텍스트 변수를 덮어씀. env var에 접근 가능한 주체(설정 파일, 컨테이너 런타임, 공유 호스트)가 임의 identity로 요청 가능.
- 수정: 사용 정책을 명시적으로 문서화하고, 프로덕션에서는 비활성화 가능한 토글 추가.

### M6. 검색 `limit` 시맨틱 미정의

- 파일: `packages/server/src/memmachine_server/main/memmachine.py:881`
  ```python
  # TODO: Define if limit is per memory or is global limit
  ```
- API 계약 모호 — 메모리 타입별인지 전역인지 결정 후 문서화 및 테스트.

### M7. SQL 엔진 `pool_pre_ping` 기본값 None

- 파일: `packages/server/src/memmachine_server/common/resource_manager/database_manager.py:260-273`
- 장수명 커넥션에서 stale 감지 지연. 프로덕션 기본값은 `True` 권장.

### M8. 마이그레이션 도구가 패스워드를 CLI 인자로 수용

- 파일: `tools/migration/dump_episodes_v0_1_x.py:141-154` — `--password`
- 프로세스 목록 / 쉘 히스토리 노출. `PGPASSWORD` 또는 `.pgpass` 권장.

### M9. `integrations/crewai/example.py`가 `os.environ`을 전역 변경

- 파일: `integrations/crewai/example.py:28-32`
- `OPENAI_API_KEY`, `OPENAI_BASE_URL` 등을 프로세스 환경에 직접 주입 — 같은 프로세스의 다른 라이브러리에 영향.
- 수정: LLM 생성자 파라미터로 전달.

### M10. Dify 플러그인 관련 이슈

- `integrations/dify/plugin/build_plugin.py:94` — `subprocess.CalledProcessError` 캡처만 하고 stderr/stdout 미전달. 빌드 실패 원인 은폐.
- `integrations/dify/plugin/tools/_memmachine.py:9` — `DEFAULT_BASE_URL = "https://api.memmachine.ai/v2"` 하드코딩. 셀프호스팅 환경에서 config 노출 필요.

---

## LOW

### L1. CI 액션 버전 불일치

- `.github/workflows/lint.yml:23, 26, 32` — `actions/checkout@v5`, `astral-sh/setup-uv@v6`
- 다른 워크플로는 `setup-uv@v4` 사용. 리포 전역 고정 권장.

### L2. Python 3.14 매트릭스

- `.github/workflows/lint.yml:62, 79`
- 프리릴리즈 버전 포함 → 정식 릴리즈 시 예기치 못한 CI 실패 가능. 현재 + 1 버전까지만 테스트하는 정책 권장.

### L3. `Config` 클래스의 `_check_closed()` 보일러플레이트

- 파일: `packages/client/src/memmachine_client/config.py`
- 모든 메서드가 동일한 체크를 반복. 데코레이터로 정리 가능.

### L4. `Record<string, unknown>` 남용

- 파일: `packages/ts-client/src/memory/memmachine-memory.types.ts`
- 메타데이터에 discriminated union 또는 제약된 타입 권장.

### L5. 예제 코드 중복

- `integrations/*/example.py` 파일들에 클라이언트 초기화, 프로젝트 생성 보일러플레이트 반복.

### L6. `delete_all()`의 비활성 TODO 주석

- 파일: `packages/server/src/memmachine_server/main/memmachine.py:1584`
- `# TODO: Add episodic memory deletion` 코멘트가 남아있지만 **1597줄에서 `episodic_store.delete_all()` 태스크가 이미 생성됨**. 구현은 완료, 주석만 오래됨. 주석 제거만 필요.

---

## 구조 / 아키텍처 관찰

- **패키지 레이어링** 정상. `common`에 공용 Pydantic 모델, `client`/`ts-client`는 이를 소비. 순환 참조 없음.
- **버전 관리**: server API 버전은 v1/v2로 분기(`api_v1/`, `api_v2/`). 하지만 `client`, `ts-client`, `common`에는 API 버전 호환성 전략(지원 범위, deprecation 경로)이 명시되지 않음. 서버 변경 시 클라이언트가 조용히 깨질 리스크.
- **`MemMachine` 거대 클래스**: `packages/server/src/memmachine_server/main/memmachine.py`가 1597줄. 세션 관리 / 검색 오케스트레이션 / 메모리 구성이 한 클래스에 응집. 도메인별 분리로 테스트성과 리더빌리티 개선 여지.
- **리소스 초기화**: `resource_manager.py:94`에 "lazily when actually used"라는 TODO가 있고 대부분 eager 초기화됨. 기동 시간 및 테스트 격리에 불리.
- **에러 메시지 일관성 부족**: 일부 API 엔드포인트가 raw exception 문자열을 그대로 반환(정보 노출), 일부는 일반화된 메시지. 공용 에러 매퍼 권장.
- **서버/클라이언트 간 에러 규약** 부재. 서버가 반환하는 상세 오류 구조가 표준화되어 있지 않고, 클라이언트는 HTTP 상태와 body를 각자 파싱.

---

## 테스트 커버리지 관찰

- `packages/server/server_tests/` 86개 테스트 파일 존재. fixture 활용(Postgres, Neo4j 테스트 컨테이너) 양호.
- `packages/client/client_tests/` 및 `packages/ts-client/` 모두 단위 테스트 있음.
- 관찰된 공백:
  - 멀티워커 동시성 시나리오 통합 테스트 부재
  - 부분 삭제/롤백 경로 (M4) 테스트 미발견
  - `asyncio.run()` 동기 래퍼의 "루프 안에서 호출" 회귀 테스트 없음
  - 클라이언트 `close()` 후 Memory 메서드 호출 시나리오 — 현 코드에서는 올바른 에러가 아예 안 나므로 테스트 대신 버그(H1)가 묻혀 있음

---

## 검토 후 "버그 아님"으로 판정한 주장 (허위 양성 기록)

리뷰 에이전트들이 제기했지만 원문 확인 결과 실제 문제가 아닌 항목:

1. **`langgraph.py::add_memory`의 `else` 블록이 unreachable**
   - 파일: `packages/client/src/memmachine_client/langgraph.py:167-192`
   - Python `try/except/else` 규칙상 try가 예외 없이 정상 종료했고 `return`으로 빠져나가지 않았을 때 `else`가 실행됨. `if results:` 블록이 False이면 try가 정상 종료되고 `else`로 진입하므로 정상 동작.
   - (M3에는 별도 로깅 이슈만 유지)

2. **`database_manager.py:149-181`의 double-check lock이 race를 유발**
   - per-name 락을 외부 `self._lock` 안에서 `setdefault(name, Lock())`로 단일 생성 후 `async with self._neo4j_locks[name]`로 보호. `setdefault`는 원자적이므로 중복 초기화 경로 없음.

3. **`delete_all()`의 episodic 삭제 미구현** (CRITICAL로 잘못 분류되었음)
   - 주석(`main/memmachine.py:1584`)은 오래되었지만 실제로는 1597줄 `tg.create_task(episodic_store.delete_all())`로 수행됨. 주석 정리만 필요 (L6).

---

## 추천 우선순위

1. **5분 픽스**: `README.md:49` 문법 오류 수정, `delete_all()`의 L6 주석 제거.
2. **단기 (1일)**: `Memory._client_closed` 상태 전파(H1), TypeScript `handleAPIError` 반환 타입 `never`(H6), 에러 메시지에서 payload 제거(H7), `build-docker.sh` 크리덴셜 stdin화(H8), `memmachine-compose.sh`에 `set -u`(H8).
3. **중기 (1주)**: `asyncio.run` 동기 래퍼 제거(C2), `asyncio.gather` 부분 삭제 처리(M4), `semantic_ingestion`의 `ExceptionGroup` 대응(H3), Dockerfile uv 버전 고정 + HEALTHCHECK(H8), MCP env var 오버라이드 문서화/토글(M5).
4. **장기 (1개월)**: `MemMachine` 거대 클래스 분해, API 버전 호환성 전략 수립, 공용 에러 매퍼 도입, 멀티워커 동시성 통합 테스트 추가.
