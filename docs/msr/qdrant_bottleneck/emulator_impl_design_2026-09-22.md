# 에뮬레이터 구현 설계 (종합) — 2026-09-22

이 문서는 부하 도구(에뮬레이터)의 **제작 직전 종합 설계**다. 2026-09-21 판 초안(`emulator_impl_design_2026-09-21_draft.md`)을 요청 명세 부록과 speedkick 소스로 전수 대조해 고친 판이며, 장과 절 번호, 표 구조, 근거 표기와 인용 규약은 원문 그대로 두었다. 다만 §0 앞에 "기준 문서와 브랜치"와 "우리 저장소 대응 경로" 두 절을 새로 세웠다. 원문은 같은 내용을 머리말 불릿으로 처리했으나, 권위 순서가 바뀐 것이 이 판의 전제라 절로 올렸다. 무엇을 왜 고쳤는지는 §11 에 표로 있다.

## 기준 문서와 브랜치

**소스의 기준은 MemMachine speedkick 브랜치 HEAD `8d7b832`(2026-09-17)다.** 이 문서의 모든 `[C:]` 인용은 그 작업 트리의 줄 번호다.

권위 순서는 아래와 같다. 원문 머리말은 "SPEC 과 충돌하면 이 문서가 우선한다"고 적었으나, 2026-09-22 에 명세 본문이 speedkick 기준으로 갱신되고 요청 명세 부록이 추가되면서 그 선언은 더 이상 맞지 않는다.

| 순위 | 문서 | 무엇의 권위인가 |
|---|---|---|
| 1 | speedkick 소스 `8d7b832` | 최종 진실 |
| 2 | `emulator_request_spec_2026-09-22.md` (이하 **APX**) | **Qdrant 요청 모양과 기본값의 권위.** 소스를 qdrant-client 1.19.0 으로 실제 직렬화해 바이트 단위로 검증했다 |
| 3 | `emulator_spec_2026-09-21.md` (이하 **SPEC**) | 구조와 인터페이스의 권위. 3.1절과 3.4절과 7장과 9.2절은 APX 를 권위로 삼는다 |
| 4 | 이 문서 | 위 셋 아래의 **구현 판단**만 고정한다. 위와 충돌하면 이 문서가 틀린 것이다 |

**요청 모양에 한해서는 APX 가 이 문서보다 위다.** §4.3 의 템플릿은 APX 5.1절과 4.1절과 6장의 직렬화 본문을 옮겨 적은 것이며, 어긋나면 APX 가 맞다. 그 밖의 항목(구조, 설정 파일 분할, 제작 순서, 리스크)에서 이 문서가 SPEC 을 갱신한 지점은 §2 에 전량 명시한다.

## 우리 저장소 대응 경로

원문은 사용자 서버 기준의 경로 표기를 썼다. 표기는 그대로 두고 대응만 여기 한 번 적는다.

| 원문 표기 | 우리 저장소 |
|---|---|
| `/home/tj/Workspace/ltm/memmachine/MemMachine_src` | `/Users/taejin/Projects/MemMachine/mm_speedkick` |
| `docker_setup/emulator_spec_2026-09-21.md` (SPEC) | `repo/docs/msr/qdrant_bottleneck/emulator_spec_2026-09-21.md` |
| `emulator/emulator_spec_code_review_2026-09-21.md` (REV) | **우리에게 없음.** REV 근거는 전부 소스 근거로 바꾸었다(아래) |
| 설계서 4.4절, 5.1절 | `repo/docs/msr/qdrant_bottleneck/design_2026-09-17.md` |
| 수집문서 9.3절 | `repo/docs/msr/qdrant_bottleneck/metrics_collection_2026-09-21.md` |
| (신규) APX | `repo/docs/msr/qdrant_bottleneck/emulator_request_spec_2026-09-22.md` |
| (신규) 트레이스 | `repo/docs/msr/qdrant_requests/qdrant_request_trace.json` |

- 근거 표기: **[사실]** 코드나 git 이나 실측으로 확인 / **[추론]** 근거 있는 판단 / **[미결]** 확인 필요. §9 에 미결 총람.
- 인용 규약: `[S:절]`=SPEC, `[A:절]`=APX(신규), `[CH-n]`=SPEC 부록 변경로그, `[Bn]`=아래 실측, `[T:S1~S13]`=트레이스 스텝, `[D:날짜]`=사용자 결정, `[C:경로:행]`=MemMachine 코드.
- **`[C:]` 의 경로는 `packages/server/src/memmachine_server/` 아래를 생략한 파일명이고 줄 번호는 speedkick `8d7b832` 기준이다.** 그 밖의 위치는 `[C:spec.py:…]`(`packages/common/src/memmachine_common/api/spec.py`)와 `[C:qc:…]`(`.venv` 의 qdrant-client 1.19.0)로 구분한다. 이 규약은 APX 5행의 표기 규칙과 맞물린다.
- **`[R:§]`(REV) 인용은 이 판에서 전부 뺐다.** REV 문서가 우리 저장소에 없어 검증할 수 없기 때문이며, REV 를 근거로 들었던 주장은 모두 speedkick 소스에서 같은 사실이 확인되므로 `[C:]` 와 `[A:]` 로 바꾸어 달았다(§11 의 16번).

## 0. 실측 기록 (이 문서가 새로 추가한 사실)

| ID | 내용 | 조건 |
|---|---|---|
| [B1] | 검색 요청(768차원, limit=80, 방식 A 필터) JSON 본문 = **약 16.4KB**. 원문이 적은 **8,152바이트는 소수 7자리로 반올림한 벡터의 값**이다 [주1] | 측정 서버(344 vCPU), Python 3.12.3, 단일 코어. 벡터 정밀도 미기록 |
| [B1-t] | 같은 본문의 `json.dumps` 단일 코어 초당 7,596건 | 같음. **정밀도 미기록이라 재측정 대상** [주2] |
| [B2] | 검색 응답(limit=80, 포인트마다 `id`/`version`/`score` 뿐, 본문 약 6KB) `json.loads` 단일 코어 초당 34,625건 | 같음. 응답이 작은 이유는 `with_payload=false` 와 `with_vector=false` 다 [A:5.4] |
| [B3] | 저장 payload 는 **12키**다(항상 10키, 조건부 `_produced_for_id`, 색인 없는 사용자 키). 원문의 "11필드 442바이트"는 사용자 키를 빼고 센 값이며 442 라는 수를 정하는 것은 키 개수가 아니라 기록되지 않은 문자열 길이다 [주3] | 같음. 문자열 값 집합 미기록 |
| [B3-t] | 저장 배치(batch=4, 768차원) `json.dumps` 초당 3,393건. 이 배치의 본문은 **약 66.6KB**(전체 정밀도, 12키) | 같음. **[B1-t] 와 같은 정밀도로 재측정 대상** [주2] |
| [B4] | 벤치를 돌린 머신은 **측정 대상 서버(344 vCPU)** 다. 그 서버에 `orjson` 미설치. 다만 MemMachine 개발 가상환경에는 `orjson` 이 있어 직렬화 비교는 그곳에서 먼저 잴 수 있다 [주4] | 같음 |

[추론] 처리량 항목([B1-t], [B3-t], [B2])은 직렬화만 재고 asyncio 와 TCP 와 HTTP 오버헤드와 GC 꼬리를 못 재므로 **언어 확정 근거가 아니라 "Python이 불가능하지 않다"의 반증 근거**로만 쓴다. 확정은 M0(§8.0).

**[주1] 본문 크기는 벡터의 부동소수 정밀도에 두 배까지 좌우된다.** qdrant-client 1.19.0 으로 직접 직렬화해 재면, 768차원 정규화 임베딩을 전체 정밀도 `list[float]` 로 보낼 때 16,382바이트이고 균등난수면 15,328바이트이며 float32 원본을 파이썬 float 로 올려도 16,398바이트다. 같은 벡터를 소수 7자리로 반올림하면 8,161바이트, 6자리면 7,401바이트다. **곧 원문의 8,152 는 7자리 반올림 조건의 값이고 실제 요청은 그 두 배다.** 이 값이 §3 불변식 5 의 메모리 계산에 전파되어 있으므로 그쪽도 고쳤다(결론인 4GiB 는 바뀌지 않는다). [사실][C:qc:http/models/models.py:2478-2511]

**[주2] [B1-t] 와 [B3-t] 는 같은 조건에서 동시에 성립할 수 없다.** `json.dumps` 비용은 float 개수에 거의 정확히 비례하고 [B3-t] 의 본문은 float 이 4배(3,072개)인 데다 payload 가 4벌 더 붙는다. 이 Mac 에서 같은 두 본문의 처리량 비를 재니 3.95 로 이론값 4.0 과 맞았는데, 원문의 비는 7,596/3,393 = 2.24 다. 두 행 중 하나 또는 둘 다 다른 정밀도에서 잰 값이다. **M0 에서 driver 가 실제로 쓸 인터프리터로 두 값을 같은 정밀도로 다시 재고, 행마다 float 개수(768 과 3,072)를 함께 적는다.** 그러면 비가 4 에서 벗어나는 순간 바로 보인다. 재측정 전까지 §8.0 의 "Python 탈락 아님" 판정은 유보다.

**[주3] payload 키 개수와 색인 개수는 다른 수다.** 업서트 payload 에 항상 들어가는 키는 `sys-partition_key`, `_timestamp`, `_episode_uid`, `_session_key`, `_producer_id`, `_producer_role`, `_sequence_num`, `_episode_type`, `_content_type`, `_created_at` 의 10개이고, `produced_for_id` 가 `None` 이 아닐 때만 `_produced_for_id` 가 붙어 11개가 되며, 그 위에 `filterable_metadata` 의 색인 없는 사용자 키가 맨 이름 그대로 더 붙는다. 기존 트레이스 [T:S4] 와 [T:S5] 의 `payload_keys` 는 `user_id` 를 포함해 **12개** 다. 이 Mac 에서 uuid4 와 tz-aware ISO 로 채워 재면 11키 382바이트, 12키 401바이트이고 APX 4.1절의 짧은 값 예시는 318바이트다. 442 를 검증 가능한 수로 만들려면 **쓴 문자열 값 집합을 함께 적어야 한다.** [사실][C:long_term_memory.py:756-781][C:event_memory.py:326][C:qdrant_vector_store.py:252-268][A:4.2]

**[주4] 조건 칸의 "이 머신"은 측정 대상 서버다.** 설계서 4.1절이 단일 서버(344 vCPU, 1TB RAM)를 확정했고 준비 문서도 측정 서버를 344 vCPU 로 적으므로 [B4] 의 344 는 그 서버의 값이다. **이것을 측정 환경 오염으로 보지는 않는다.** 세 벤치는 단일 코어에 몇 초짜리 순수 CPU 작업이고 조건이 서기 전에 돌았으며, SPEC 2.2절과 8.3절이 요구하는 바닥 측정은 애초에 driver 가 돌 머신에서 재야 한다. 다만 준비 문서가 그 서버를 공용일 가능성이 높다고 경고했으므로 **조건 칸에 호스트와 동시 실행 부하 상태를 적어야 한다.** 인터프리터도 어긋나 있다. speedkick 클라이언트 스택은 Python 3.12.13 이고 원문 벤치는 3.12.3 이다. M0 은 driver 가 실제로 쓸 인터프리터로 돌린다. 덧붙여 이 벤치가 준비 문서 3.3절의 첫 합격 확인인 "CPU(s) 가 344"를 사실상 통과시켰는데 어디에도 보고되지 않았고, 환경 문서가 같은 날짜에 "서버에 접속하지 못해 어떤 명령도 실물로 확인하지 못했다"고 적어 두 문서의 상태가 어긋난 채 남아 있다. 그 기록의 갱신이 필요하다.

---

## 1. 목적과 비목적

**목적**: MemMachine 없이 Qdrant v1.19.1 에 MemMachine 과 동일 모양의 요청을, SPEC 3.2절 파라미터 전부를 실행 변수로 보내는 도구. 측정 대상은 Qdrant 내부(W2 와 W3 사각지대 포함). [S:1]

**비목적** (만들지 않음): 분산 실행, 검색과 저장의 분리 풀, 시각화, 조건 전환 자동화. [S:2.3] 조건 전환은 **작업 단계 1.5의 `run_condition.sh` 몫이며 제어기는 그 스크립트를 호출만 한다** [S:4.7]. 삭제 부하는 §2-4 결정으로 현 시점 비목적이고, `semantic_memory` 네임스페이스는 §2-10, 세션 생성 이벤트는 §2-11 결정으로 현 시점 비목적이다.

**제어기 `runner` 는 비목적이 아니라 이 문서의 산출물이다.** SPEC 1장과 4.7절, 환경 문서 5.4절, 설계서 4.4절과 4.6절 표가 모두 제어기를 부하 도구의 산출물(작업 단계 3.4)로 확정했다. 원문 §3 이 이를 범위 밖으로 돌렸던 것은 오류이며 §3 과 §7.1 에서 고쳤다.

---

## 2. SPEC을 갱신한 확정 결정 (11건 전수)

| # | 항목 | 확정 | 근거 |
|---|---|---|---|
| 1 | `with_payload` | **`false` 확정** (SPEC의 "잠정" 해소) | [사실][CH-1] 커밋 `abf92a3`(2026-09-09, "Answer with cosine scores and uuids, not vectors and stale properties")이 `return_properties` 와 `return_vector` 인자를 삭제해 최신 코드는 리터럴 고정 [C:qdrant_vector_store.py:361-362], 트레이스 [T:S6~S9,S11]와 일치 [A:5.4] |
| 2 | `wait=true` | 저장과 삭제 모두 **`?wait=true`** | [사실] 어댑터가 `wait` 를 넘기지 않음. 저장 [C:qdrant_vector_store.py:316-319], 삭제 [C:qdrant_vector_store.py:397-409] + qdrant-client 1.19.0 기본값 `wait: bool = True` (`upsert` [C:qc:async_qdrant_client.py:836], `delete` [C:qc:async_qdrant_client.py:1095]) [CH-2] + [T:S4,S5,S12,S13] |
| 3 | 저장 실패 절반 쪼개기 | **driver 재현 안 함**. 단순화 | [D:2026-09-21][CH-3]. 모양은 [사실] sleep 없는 즉시 재귀 [C:qdrant_vector_store.py:312-325]. **근거를 고쳤다.** "실패 유도 실험이 없다"가 아니라 "포화 구간에서 5초 타임아웃으로 재시도가 유발될 수 있음을 알고도 1차 구현에서는 재현하지 않고 `error_counts_by_class` 의 타임아웃 건수로 발생만 관측한다"이다. APX 11장도 이 항목을 닫지 않고 미정으로 두었다 [A:4.4]. 결정 흔적은 `run.json` 의 `driver_version` 에 남김. 재현하지 않아 생기는 편향은 §10 |
| 4 | 삭제 부하 | **보류** (`enabled:false` 유지). 재개 시 모양은 §4.3 의 두 JSON 으로 확정 | [D:2026-09-21][CH-4]. 모양은 [사실][C:qdrant_vector_store.py:397-409, 815-830]. **원문의 "트레이스 S12/S13 원문 미확인" 단서를 삭제했다.** 기존 트레이스는 삭제 요청만은 원문 JSON 을 그대로 기록하고 있어 [T:S12,S13] 으로 확정된다(§9.0, [A:6]) |
| 5 | payload 크기 | **두 겹**: 코드 확정분(12키 [B3])은 loader 고정 채움 + 미확인분만 옵션 `extra_payload_bytes`(기본 0) | [D:2026-09-21][CH-7]. 근거: 본문 텍스트는 SQL `LargeBinary` 컬럼이지 Qdrant payload 가 아님 [C:sqlalchemy_segment_store.py:170-171]. 사용자 properties 는 통째 복사 통과 [C:qdrant_vector_store.py:260-267]. **"11필드"를 "12키"로 고쳤다**([주3]) |
| 6 | 레지스트리 컬렉션 | **재현 안 함** + 대조 예외 | [D:2026-09-21][CH-6]. 1차원 컬렉션 생성 [C:qdrant_vector_store.py:547-567], 레지스트리 retrieve [C:qdrant_vector_store.py:569-600], 등록 업서트 [C:qdrant_vector_store.py:686-702]. **근거를 고쳤다.** 컬렉션 생성과 등록 업서트는 논리 컬렉션당 1회가 맞으나 **레지스트리 retrieve 는 `open_collection` 이 불릴 때마다 나간다** [C:qdrant_vector_store.py:766-784][T:S11]. 따라서 "부하 구간에 안 들어옴"이 아니라 **"세션을 여는 이벤트를 부하 모델에 넣지 않기로 했으므로 제외한다"** 이다. 세션 생성을 모델링하면 §2-11 이 적용된다 |
| 7 | 컬렉션 이름 | **평이명 유지** (`laion100m` 등). 실제는 `{namespace}__{sha256(차원과 색인 스키마를 담은 설정 JSON)}` [C:qdrant_vector_store.py:513-519] 이나 대조의 `<coll>` 정규화가 흡수 | [D:2026-09-21][CH-6]. **해시 입력을 고쳤다.** `VectorStoreCollectionConfig` 의 필드는 `vector_dimensions` 와 `indexed_properties_schema` 둘이므로 [C:data_types.py:17-31, 65-71] **`load.yaml` 의 `dim` 을 바꾸면 네이티브 컬렉션 이름도 바뀐다.** 768차원의 실제 이름은 `long_term_memory__721a83c6…d64e63` 이다 [A:3.1] |
| 8 | 프로토콜 | **REST 고정** (`protocol` 파라미터로 노출만). gRPC는 1회 차이 기록용 | [사실] `prefer_grpc` 기본 `False` [C:database_conf.py:247-250]. gRPC 는 서버 JSON 파싱 비용(측정 대상)을 제거해 대상이 바뀜 [S:4.6] |
| 9 | **M0 후보 셋** (신규) | SPEC 8.3절의 후보 셋에서 **`qdrant_client` 비동기를 뺀다**. 후보는 전송 축으로 파이썬 `httpx` 직접 조립과 Rust `reqwest` 둘이고, `orjson` 은 파이썬 후보 안의 직렬화기 변형으로 둔다 | [사실] SPEC 4.6절이 "Qdrant 공식 클라이언트를 쓰지 않는다"고 못박았으므로 [S:4.6] SPEC 8.3절의 첫 후보는 SPEC 4.6절과 그 자체로 충돌한다 [S:8.3]. 원문은 이 교체를 말없이 했고 충돌을 신고하지 않았다. 비교표 행은 파이썬+json, 파이썬+orjson, Rust 셋이 된다 |
| 10 | **`semantic_memory` 네임스페이스** (신규) | **재현 안 함** + 대조 예외 | [사실] `semantic_memory.storage_backend` 가 `vector_store` 일 때만 두 번째 네이티브 컬렉션이 생기며 기본값은 `auto` 라 pgvector 나 neo4j 로 간다 [C:configuration/__init__.py:89-96, 110-111]. 그 컬렉션은 스키마가 `str` 11개라 색인이 `sys-partition_key` 포함 **12개** 이고 12개 모두 `keyword` 이며 [C:semantic_manager.py:150-169], 업서트 payload 는 `sys-partition_key` 하나뿐이고 [C:vector_store_semantic_storage.py:231-253], 검색은 `limit` 이 상수 10000 에 필터가 파티션 하나뿐이다 [C:vector_store_semantic_storage.py:613-622]. 검색 1건당 Qdrant 질의 수가 그 세션의 `set_id` 개수만큼 늘어난다 [A:3.5, 5.5]. **대상 배포의 `storage_backend` 설정은 [미결 U6]** 이며, `vector_store` 로 확인되면 이 결정을 다시 연다 |
| 11 | **세션 생성 이벤트** (신규) | **부하 모델에 넣지 않음** | [사실] 커밋 `a2a1754` 이후 speedkick 은 컬렉션 생성과 색인 생성의 guard 를 분리해서, 네이티브 컬렉션이 이미 있어도(409) **새 세션이 등록될 때마다 `wait=true` 색인 PUT 11회가 나간다** [C:qdrant_vector_store.py:634-678][T:S2][A:3.6]. 새 세션 하나가 17요청이다. 넣기로 바꾸면 SPEC 4.4절 허용 API 목록과 SPEC 5장 워크로드 모델에 추가가 필요하고, 레지스트리 retrieve 도 따라온다(§2-6). 적재 구간의 세션 생성은 loader 몫이라 이 결정과 무관하다 |

---

## 3. 아키텍처 — 3 프로그램, 경계는 SPEC 그대로

```
[loader]  Python. 부하 구간 이전. 데이터 파일 읽기 권한 O.
          컬렉션 생성, 인덱스 11개, 세션 배정, 대량 upsert, verify, master
[driver]  M0에서 언어 확정. 부하 구간 동안만.
          데이터 파일 읽기 권한 X. Qdrant API 3개만.
[runner]  Python. 부하 구간 밖. 이 문서의 산출물 (작업 단계 3.4). §7.1
          run_condition.sh 호출, 적재기 호출, 마스터 사본 생성,
          구간 경계 스냅샷, 사다리, 저장 부하 뒤 마스터 복원
```

**범위 밖인 것은 제어기가 아니라 `run_condition.sh` 자체다.** 그 스크립트는 환경 문서 5.3절의 산출물이고 "조건이 섰다"를 출력하는 자리까지 책임지며, 제어기는 그 뒤를 잇는다 [S:1, 4.7]. 원문이 제어기를 범위 밖으로 돌린 탓에 제어기 순서 (1)부터 (7)까지와 환경 문서 5.4절의 의무 네 가지와 마스터 사본 생성과 `stage_groups.json` 묶음 파일이 통째로 빠져 있었다. §7.1 이 그 자리를 받는다.

**구조 불변식** (위반 시 실행 무효):
1. driver 컨테이너 마운트는 `$RUNDIR/load` 하나. `$RAW` 와 `$BENCH` 미마운트를 `docker inspect` 로 확인. [S:4.3, R1]
2. driver 허용 API는 `POST .../points/query/batch`, `PUT .../points?wait=`, `POST .../points/delete?wait=` 셋. 자체 카운트한 `endpoint_counts` 에 목록 밖 경로가 0이 아니면 무효. [S:4.4, R6] 삭제를 보내지 않는 것은 위반이 아니다. 목록은 상한이고 판정은 목록 밖 경로가 0인지를 보는 것이므로 `delete` 값이 0일 뿐이다.
   **이 불변식과 불변식 1의 데이터 파일 접근 금지는 driver 에만 걸린다.** 적재기와 제어기는 적용 대상이 아니다 [S:2.2]. 적재기는 데이터 파일을 읽어야 일을 하고, 제어기는 컬렉션 관리와 스냅샷 창구를 불러야 하기 때문이다. 함정 대책 3번이 막는 것은 **부하 구간에 데이터 파일을 먼저 만지는 것**이지 적재 자체가 아니다.
3. 질의 벡터는 stdin으로만 수신 (경로 인자 없음). [S:5.4 — 마운트 0개 원칙 유지 + 함정 비적용 근거: 질의 파일은 `$BENCH` 밖]
4. 부하 직전 `pgrep -f 'loader load'` 가 비어 있어야. [S:4.5]
5. driver 컨테이너 memory/swap 4GiB. [S:4.3 — 근거 계산(질의집합 0.95GiB + 버퍼 0.1GiB)에 [B1] 본문 **약 16.4KB × 1000 = 약 16MB** 를 재확인. 4GiB 유지] **M0 바닥 측정에서 실제 상주 메모리를 재어 이 값을 조정하고 `query_set_rss_bytes` 로 남긴다** [S:4.3, 6.2].
6. **(신규)** 결과가 `$RAW` 에 떨어지고 `$BENCH` 에 쓰지 않는다. `findmnt -no SOURCE "$RAW" "$BENCH"` 가 서로 다른 값을 낸다. [S:2.1 R7, 수집문서 10장]

**loader 는 MemMachine 이 "만드는 것"만 재현하고 "운용 시 내는 부수 호출"(레지스트리)은 재현하지 않는다** (§2-6). 컬렉션 설정 본문은 [T:S1] 과 [C:qdrant_vector_store.py:641-650] 이 일치한다.

```json
{"vectors":{"size":<dim>,"distance":"Cosine"},"hnsw_config":{"m":0,"payload_m":16}}
```

거리는 상수 `_QDRANT_DISTANCE = COSINE` 이라 설정으로 바꿀 수 없고 [C:qdrant_vector_store.py:450], `payload_m` 은 생성자에서 16으로 하드코딩된다 [C:qdrant_vector_store.py:528]. 색인 루프까지 가리키려면 [C:qdrant_vector_store.py:641-678] 이 정확하다.

**인덱스 11개의 타입 내역** [C:long_term_memory.py:79-89][C:event_memory.py:117-127][C:service_locator.py:111-117]:

| 타입 | 개수 | 필드 |
|---|---|---|
| keyword (`is_tenant`) | 1 | `sys-partition_key` |
| datetime | 2 | `_timestamp`, `_created_at` |
| keyword (str) | **7** | `_episode_uid`, `_session_key`, `_producer_id`, `_producer_role`, `_produced_for_id`, `_episode_type`, `_content_type` |
| integer | 1 | `_sequence_num` |

**원문은 "str 8 + int 1"이라 적었는데 그러면 1+2+8+1 = 12 가 되어 같은 문장의 "11개"와 모순된다. 실제는 str 7 이다.** 생성 순서까지 필요하면 [A:3.4] 의 11행 표를 그대로 참조로 건다. 사용자 필드가 스키마에 들어갈 경로는 speedkick 에 없으므로 설정과 무관하게 항상 11개다 [C:qdrant_vector_store.py:655-667].

**대조 기준 커밋.** 기존 트레이스 `qdrant_request_trace.json` 은 speedkick `a8322a7`(2026-09-14)에서 채취된 것이고, `a8322a7` 은 HEAD `8d7b832` 의 조상이며 그 사이에 Qdrant 요청 본문을 바꾼 커밋이 없어 트레이스의 값은 `8d7b832` 와 일치한다 [A:1.1]. 원문이 [미결 M7]로 두었던 항목이며 §9.0 에서 닫았다.

---

## 4. 설정 파일 — 데이터 형상 / 부하 형상 분리 (SPEC 3.2 유지 + 확정값 반영)

### 4.1 load.yaml (데이터 형상 — 바꾸면 재적재)

```yaml
points: 100000000            # [S:3.3]
dim: 768                     # 허용 768|1024|1536|2560
                             # 주의: dim 을 바꾸면 네이티브 컬렉션 이름도 바뀐다 (§2-7, [A:3.1])
sessions: 100000             # 파티션 키 개수 [S:3.3]. 적재기가 sys-partition_key 로 배정한다
session_size_dist: {dist: zipf, s: 1.0}   # 실제 분포 미정 [미결 U1]
holdout: {enabled: true, fraction: 0.001} # 질의 집합과 겹치지 않게 적재에서 뺀 구간 [S:5.4]
                             # SPEC 3.3절에 없는 항목이라 SPEC 갱신 필요
payload_index_count: 11      # 자르기 시 sys-partition_key 상시 유지 [S:3.3]
                             # long_term 기준이다. 설계서 4.4절은 semantic 을 포함해 0~12 로 적었으나
                             # 시맨틱 네임스페이스는 §2-10 으로 범위 밖이라 여기서는 11 이 맞다
producer_dial_values: 100    # [S:3.3] 선택도 다이얼의 해상도. 허용 1~1000
extra_payload_bytes: 0       # [CH-7]. 0=코드 확정 12키만. >0=미색인 더미 필드로 채움
                             # SPEC 3.3절에 없는 항목이라 SPEC 갱신 필요
distance: Cosine             # [T:S1][C:qdrant_vector_store.py:450]
hnsw: {m: 0, payload_m: 16}  # 고정. [T:S1][C:qdrant_vector_store.py:528,646-649]
```

**세션 배정은 적재기가 한다.** 적재기가 포인트를 넣으면서 `sys-partition_key` 에 세션 키를 붙인다 [S:3.3, 4.1]. 데이터 문서 3.8절의 세션 라벨 parquet 사전 생성 방식은 폐기되었고 라벨 파일을 따로 만들거나 읽지 않는다.

**질의 집합은 적재한 포인트와 겹치지 않아야 한다** [S:5.4]. 데이터셋에 딸린 질의 파일을 쓰고 없으면 위 `holdout` 구간을 쓴다. 적재한 벡터를 그대로 질의로 쓰면 가장 가까운 이웃이 자기 자신이라 탐색이 즉시 끝난다.

**payload 필드 값 생성 규칙** — 키는 **12개** 다([주3], [A:4.2]). 원문은 9개만 열거해 `sys-partition_key` 와 `_session_key` 와 사용자 키를 빠뜨렸다.

| 키 | 생성 규칙 | 표기 |
|---|---|---|
| `sys-partition_key` | 그 포인트의 세션 키 문자열. **파티션 다이얼 그 자체** | [사실][C:qdrant_vector_store.py:257-259] |
| `_timestamp` | tz-aware ISO 8601, UTC 는 `"2026-09-01T12:00:00Z"` 형태 | [사실][C:qdrant_vector_store.py:260-267][C:common/utils.py:68-72] |
| `_episode_uid` | 부하 도구는 uuid4 로 채운다 | **[추론]** 코드에서는 클라이언트가 준 문자열이다. 실제 값 길이는 [미결 U1] |
| `_session_key` | 논리 세션 이름 문자열(예: `orga/prja`) | [사실][C:long_term_memory.py:758] |
| `_producer_id` | `p00` 부터 `producer_dial_values-1` 까지 균등, 세션 독립 [S:3.5] | [사실] 다이얼 축 |
| `_producer_role` | 그럴듯한 짧은 문자열(예: `user`) | [추론] |
| `_sequence_num` | int | [사실][C:long_term_memory.py:761] |
| `_episode_type` | enum 값 문자열(예: `message`) | [사실][C:long_term_memory.py:762] |
| `_content_type` | enum 값 문자열(예: `string`) | [사실][C:long_term_memory.py:763] |
| `_created_at` | tz-aware ISO 8601, 위와 같은 표기 | [사실][C:long_term_memory.py:764] |
| `_produced_for_id` | **조건부.** 부하 도구는 짧은 값(예: `assistant`)으로 채운다 | **[추론]** 원문은 uuid4 라 했으나 코드가 정한 사실이 아니고 트레이스 예시는 짧은 값이다 |
| 사용자 키(예: `user_id`) | **색인 없는 키를 반드시 1개 포함한다.** 트레이스 [T:S4] 가 관측한 모양이다 | [사실][C:long_term_memory.py:768-781] |

**payload 키의 출현 순서는 위 표의 순서 그대로가 규약이다.** 파이썬 dict 삽입 순서가 그대로 JSON 순서가 되므로 바이트 대조를 하려면 순서가 고정되어야 한다. **더미 필드는 색인 생성 금지** (인덱스 11개 불변 [S:3.5]).

### 4.2 cond.yaml (부하 형상 — 적재 없이 변경)

```yaml
condition_tag: mem256_c64
target:
  url: "http://127.0.0.1:6333"
  protocol: rest
  collection: laion100m
  timeout_ms: 5000           # MemMachine 실효값. 클라이언트가 timeout 을 넘기지 않아
                             # httpx 기본 5초가 그대로 적용된다 [A:8]
                             # 다른 값을 쓰면 run.json 에 표시한다
  connection_reuse: none     # none|keepalive. MemMachine 은 host 가 localhost/127.0.0.1 이면
                             # max_keepalive_connections=0 이라 요청마다 새 TCP 연결을 맺는다
                             # [C:qc:async_qdrant_remote.py:108-111][A:2.2]. 기본은 그 패턴을 흉내 낸다
                             # 쓴 값을 run.json 에 기록 [미결 U5]
workload:
  mode: closed               # 폐루프 기본 — 동시 요청 수가 입력이어야 포화 판정 성립 [S:5.1]
  concurrency: 64
  think_time_ms: 0
  search_write_ratio: [9, 1] # [미결 U1: 동료 (가) 값 대기]
  session_skew: {dist: zipf, s: 1.0}   # 검색 접근 치우침, 세션 크기 분포(적재기)와 다른 축 [S:5.2]
  search:
    top_k: 20
    # 20 은 파이썬 직접 호출 기본값 [C:episodic_memory.py:389] 이자 트레이스 관측값이다.
    # REST 기본값은 SearchMemoriesSpec.top_k 의 10 이라 그 경로의 Qdrant limit 은 40 이다
    # [C:spec.py:516-522]. 트레이스의 limit=80 은 기본값이 아니라 트레이스 스크립트가
    # limit=20 을 명시해 넘긴 값의 4배다 [A:5.2]
    over_fetch: 4            # limit=top_k×4. [사실] _EVENT_BACKEND_DEDUP_OVERFETCH=4
                             # [C:long_term_memory.py:107,310-313]
                             # 기본값에서 벗어나면 run.json 에 표시 [S:3.4]
    with_payload: false      # 확정 [CH-1][C:qdrant_vector_store.py:362]
    with_vector: false       # 확정 [T:S6~S9,S11][C:qdrant_vector_store.py:361]
    filter: partition_only   # A/B 전환 [S:3.5]
                             # 주의: A와 B는 파티션 조건의 중첩 깊이가 다르다 (§4.3)
    selectivity_pct: 1       # _producer_id 다이얼 k개. 모양은 §4.3 의 좌결합 중첩 should
                             # 검증 기준은 SPEC 3.5절: 1, 10, 50, 99 로 바꿨을 때
                             # /telemetry 의 경로별 호출 수가 전수 비교에서 그래프 탐색으로
                             # 옮겨 가는 지점이 보이고, payload 색인 개수는 네 조건 모두 11개일 것.
                             # 이 창구를 읽는 것은 제어기이며 driver 는 읽지 않는다(§3 불변식 2)
  write: {batch_size: 4, wait: true}    # batch 4=[T:S4] 관측값. wait=[CH-2] 확정
  delete: {enabled: false}              # [D:2026-09-21] 보류
duration: {warmup_sec: 60, measure_sec: 300}
```

**명령행 덮어쓰기는 `--concurrency` `--selectivity-pct` `--condition-tag` `--out` 4개만.** 그 외 인자 시도는 거부 메시지 출력. [S:3.4, 6.2 검증기준]

### 4.3 요청 본문 템플릿 (driver가 조립하는 것 — 클라이언트 라이브러리 미사용 [S:4.6])

**driver 가 라이브러리를 쓰지 않으므로 키 순서와 부동소수 표기가 손으로 맞춰야 할 규약이 된다.** 아래 본문은 전부 speedkick venv 의 qdrant-client 1.19.0 으로 실제 직렬화해 얻은 것이며 [A:5.1, 4.1, 6], 키 순서까지 그대로 조립한다. 숫자 `range` 는 정수를 넣어도 `{"gt":5.0}` 처럼 float 로 나가고 [C:qc:http/models/models.py:2624-2632], 벡터 원소는 전체 정밀도 파이썬 float 표기를 따른다. **§8.2 의 바이트 대조에서 정규화 대상은 벡터 값과 uuid 와 파티션 키 값과 `size` 뿐이다** [A:9.3].

**검색** — `POST /collections/<coll>/points/query/batch`, **쿼리스트링 없음** [C:qdrant_vector_store.py:367-370]. 최상위 키는 `searches` 하나이고 원소는 항상 1개다(두 호출자 모두 벡터 하나를 넘긴다) [C:event_memory.py:420-424]. 키 순서는 `query`, `filter`, (`score_threshold`), `limit`, `with_vector`, `with_payload` 이며 **`with_vector` 가 `with_payload` 보다 앞선다**.

**벡터 필드명은 `query` 로 확정이다.** `/points/query/batch` 는 범용 질의 API 이며 `QueryRequest` 모델에 `vector` 라는 필드 자체가 없다 [C:qdrant_vector_store.py:355-365][C:qc:http/models/models.py:2478-2511]. 원문이 [미결 M1]로 두고 두 변수를 만들어 두려 했던 항목이며 §9.0 에서 닫았다.

**`score_threshold` 는 어느 경로에서도 본문에 넣지 않는다.** 에피소드 경로가 `min_cosine_similarity` 를 넘기지 않아 `None` 이 되고 직렬화 규칙이 `exclude_none=True` 라 빠진다 [C:event_memory.py:420-424][C:qdrant_vector_store.py:359]. REST 의 `score_threshold` 는 응답을 받은 뒤 파이썬에서만 쓰인다 [A:5.2]. 트레이스 [T:S9] 가 `score_threshold=0.1` 로 질의했는데도 본문에 그 키가 없는 것이 실측 증거다. **구현자가 REST 파라미터를 보고 넣는 일이 없도록 명시해 둔다.**

**방식 A (`filter: partition_only`)** — 파티션 필터가 그대로 최상위가 되어 한 겹이다.
```json
{"searches":[{"query":[...768...],"filter":{"must":[{"key":"sys-partition_key","match":{"value":"<sess>"}}]},"limit":80,"with_vector":false,"with_payload":false}]}
```

**방식 B (`filter: partition_and_property`)** — 속성 필터가 붙는 순간 **파티션 조건이 자기 `Filter` 째로 한 겹 더 감싸인다.** 코드가 `models.Filter(must=[partition_key_filter, property_qdrant_filter])` 로 두 Filter 를 나란히 담고 하위 Filter 를 평탄화하지 않기 때문이다 [C:qdrant_vector_store.py:342-353, 64-73]. 기존 트레이스 [T:S7] 과 [T:S8] 의 실측 본문이 정확히 이 모양이다.

k=1 (`should` 가 아예 없다):
```json
{"searches":[{"query":[...768...],"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"<sess>"}}]},{"must":[{"key":"_producer_id","match":{"value":"p00"}}]}]},"limit":80,"with_vector":false,"with_payload":false}]}
```

k=2 (평평한 두 원소 배열은 이때뿐이다):
```json
{"searches":[{"query":[...768...],"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"<sess>"}}]},{"should":[{"must":[{"key":"_producer_id","match":{"value":"p00"}}]},{"must":[{"key":"_producer_id","match":{"value":"p01"}}]}]}]},"limit":80,"with_vector":false,"with_payload":false}]}
```

k=3 (`should` 안에 `should` 가 다시 들어간다):
```json
{"searches":[{"query":[...768...],"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"<sess>"}}]},{"should":[{"should":[{"must":[{"key":"_producer_id","match":{"value":"p00"}}]},{"must":[{"key":"_producer_id","match":{"value":"p01"}}]}]},{"must":[{"key":"_producer_id","match":{"value":"p02"}}]}]}]},"limit":80,"with_vector":false,"with_payload":false}]}
```

- **선택도 다이얼의 `should` 는 평평한 k원소 배열이 아니라 좌결합 이항 트리다.** 필터 파서의 `Or` 는 `left` 와 `right` 두 자리만 가진 이항 노드이고 파서 루프가 `expr = Or(left=expr, right=rhs)` 로 좌결합 누적을 한다 [C:filter_parser.py:207-226]. 어댑터는 `Or` 하나를 `models.Filter(should=[좌, 우])` 로 옮긴다 [C:qdrant_vector_store.py:103-106]. **곧 k개의 OR 는 `Or(Or(Or(a,b),c),d)` 꼴이라 `should` 가 깊이 k-1 로 중첩된다.** k=4 는 `{"should":[{"should":[{"should":[A,B]},C]},D]}` 다. 원문 §4.3 의 `... k개` 표기는 틀렸다 [A:5.3].
- **k개를 한 번에 거는 평평한 배열을 쓰려면 OR 이 아니라 `IN` 연산이어야 한다.** MemMachine 파서는 `field IN (a, b, c)` 를 `{"must":[{"key":"_producer_id","match":{"any":["p00","p01"]}}]}` 하나로 만든다 [C:qdrant_vector_store.py:185-193]. **부하 도구는 `IN` 이 아니라 OR 중첩을 택한다.** 근거는 SPEC 3.5절이 MemMachine 이 실제로 내는 모양을 흉내 내기로 했기 때문이며(트레이스 [T:S7] 이 그 모양이다), `IN` 은 MemMachine 이 내지 않는 별개 조건이라 카디널리티 추정 비용이 달라질 수 있다. **Qdrant 가 평평한 배열과 중첩 배열을 같은 비용으로 처리하는지는 미확인이다** [미결 U7].
- **방식 A 와 방식 B 는 파티션 조건의 중첩 깊이가 다르다.** A 는 한 겹, B 는 두 겹이다. `filter` 파라미터를 전환하면 필터 구조가 통째로 바뀐다. "평평하게 펴면 안 됨"이라는 원문의 주의는 방향이 맞았으나 원문 그림 자체가 그 주의를 어기고 있었다 [S:7.3-4].

**저장** — `PUT /collections/<coll>/points?wait=true`. 본문은 `PointsList` 직렬화이고 포인트의 키 순서는 `id`, `vector`, `payload` 다. `id` 는 파이썬 `UUID` 라 하이픈 포함 소문자 문자열로 나간다 [C:qdrant_vector_store.py:292-310, 316-319][A:4.1].
```json
{"points":[{"id":"e99d628c-8286-48b3-ba2b-8d234806da3b","vector":[...768...],"payload":{"sys-partition_key":"<sess>","_timestamp":"2026-09-01T12:00:00Z","_episode_uid":"...","_session_key":"orga/prja","_producer_id":"p00","_producer_role":"user","_sequence_num":0,"_episode_type":"message","_content_type":"string","_created_at":"2026-09-01T12:00:00Z","_produced_for_id":"assistant","user_id":"user_a"}}]}
```
벡터는 질의집합 벡터에 작은 섭동을 더해 쓴다. 합성 난수를 쓰지 않는 이유는 [S:5.3](군집 구조 소실). 저장 포인트는 별도 id 대역과 payload 표식을 갖는다 [S:5.3].

**삭제 (재개 시)** — 두 갈래이고 본문이 서로 다르다 [A:6].

레코드 삭제([T:S12]) `POST /collections/<coll>/points/delete?wait=true` [C:qdrant_vector_store.py:397-409]. 파티션이 한 겹 더 감싸인다. `has_id` 배열에 넘어온 uuid 전부가 한 요청에 담기며 분할이나 재시도가 없다.
```json
{"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"<sess>"}}]},{"has_id":["e99d628c-8286-48b3-ba2b-8d234806da3b"]}]}}
```

논리 컬렉션 삭제, 곧 세션 삭제([T:S13]) [C:qdrant_vector_store.py:815-830]. 파티션 필터만 걸고 `has_id` 가 없으며 **파티션이 감싸이지 않는다.** 뒤이어 레지스트리 포인트 삭제 1건이 따른다(레지스트리는 §2-6 으로 재현 안 함).
```json
{"filter":{"must":[{"key":"sys-partition_key","match":{"value":"<sess>"}}]}}
```

---

## 5. 워크로드 모델

- **폐루프 기본**: 워커 N개, `t_plan`(직전 응답 + think) 기록. 포화 판정은 `t_recv - t_plan`. [S:5.1, 수집문서 9.3]
- **개루프 보조** (`mode: open`): 포화 이후 대기열 관찰용. 어느 조건에서 돌릴지는 [미결 U4]. [S:9.4]
- **세션 접근**: zipf(`s` 파라미터) 워커 공통 분포. [S:5.2 — 치우침이 캐시 워킹셋 크기를 정하고 그게 메모리 축의 관찰 대상] **검증 기준**: `session_skew.s` 를 0 과 1.0 으로 바꿔 돌리면 같은 메모리 한도에서 `memory.stat` 의 `workingset_refault_file` 이 뚜렷이 달라진다 [S:5.2].
- **검색과 저장의 혼합**: 단일 워커 풀 + 요청별 가중 추첨. 달성 비율을 `run.json` 에 기록하며 의도와 달성의 괴리 자체가 저장 포화 신호다. [S:5.3]
- **질의 집합 홀드아웃**: 질의 벡터는 적재한 포인트와 겹치지 않아야 한다. 데이터셋 질의 파일을 쓰고 없으면 §4.1 의 `holdout` 구간을 쓴다. [S:5.4]
- **저장 부하 뒤 마스터 복원은 의무다**: 저장 부하가 섞인 실행 뒤에는 제어기가 반드시 마스터 복원을 수행한다. 실제 복원은 `run_condition.sh` 를 `RELOAD=copy` 로 다시 부르는 것이며 §7.1 순서 (7)에 있다. [S:5.3]
- **옵티마이저 구간 표시**: `queued_segments` 가 0이 아닌 단은 비교 대상이 아니다. 제어기 스냅샷으로 판정하며 driver 는 알 필요가 없다. [S:6.4]

## 6. 출력 (SPEC 6장 + 수집문서 9.3 유지, 값 확정)

```
$RUNDIR/load/
├── requests.tsv   t_plan t_send t_recv kind status n sess step   ← 스키마 수집문서 9.3 고정
├── load_config.json  유효 설정 전문 + sha256 → 재현 계약 [S:6.2, R5]
├── run.json       §6.1 필드 전수
├── series.csv     t_sec,op,sent,ok,err,timeout,inflight,p50_us,p95_us,p99_us,max_us (1초)
└── hist/search.hgrm, write.hgrm   HDR. 합치기 가능하고 임의 분위 재추출 가능 [S:6.1]
```

### 6.1 run.json 필수 필드

SPEC 6.2 목록 그대로: `condition_tag`, `effective_config_file/sha256`, `driver_version/commit/cpuset/peak_cpu_pct`, `started_at_utc/warmup_sec/measure_window_sec`, `achieved_search_write_ratio/total_requests/endpoint_counts`, `error_counts_by_class`(연결거절, 타임아웃, 4xx, 5xx 분리, **전수 카운트** [S:6.2]), `selectivity_pct/expected_matching_points`(비율과 절대건수 모두 — `full_scan_threshold` 갈림 판정용 [S:3.5]), `query_set_size/query_set_rss_bytes`, `requests_tsv_sampling`.

**APX 가 새로 요구한 네 항목을 더한다.**

| 필드 | 왜 필요한가 | 근거 |
|---|---|---|
| `connection_reuse` | APX 가 연결 재사용 방식을 미정으로 두면서 쓴 값을 기록하라고 요구했다 | [A:2.2, 8, 11] |
| `timeout_ms` | 기본 5000 에서 벗어나면 표시해야 한다 | [A:8] |
| `over_fetch` | 기본 4 에서 벗어나면 결과에 표시해야 한다 | [S:3.4] |
| `memmachine_ref_commit` | 제어기가 `manifest.json` 을 만들 때 부하 형상 항목을 `run.json` 에서 가져다 쓰므로 기준 커밋의 출처가 정해져야 한다. 값은 `speedkick 8d7b832` | 수집문서 9.2 |

### 6.2 requests.tsv 솎기

기본 전수. 첫 스모크에서 쓰기 비용이 측정을 방해하면 표본화(`requests_tsv_sampling` 에 비율 기록)하되 series 와 hist 와 `run.json` 총계는 전수 유지. [S:9.3, 미결 U3]

## 7. 명령행 계약 (SPEC 4.2 그대로 — 수정 없음)

```
loader load    --config load.yaml          # + [CH-5] 인덱스 11개와 payload 규칙 §4.1. 세션 배정도 여기
loader verify  --config load.yaml          # 아래 설명 [S:4.2][S:8.2-M1]
loader master  --config load.yaml          # verify 통과 뒤에만. 마스터가 있으면 덮어쓰지 않고 멈춘다
driver floor   --concurrency N --duration S --out DIR      # M0
driver run     --config cond.yaml [--concurrency|--selectivity-pct|--condition-tag] --out DIR
driver ladder  --config cond.yaml --rungs 1,2,4,8,16 --out DIR   # 스냅샷 불요 자리만 [S:6.4]
driver trace   --config cond.yaml --n 100 --out DIR        # 요약과 원본 본문 병기 [S:7.2]
driver recall  --config cond.yaml --queries 200 --out DIR  # 부하 구간 밖 전용 [S:8.5]
```

**원문은 `loader master` 한 줄을 빠뜨렸다.** 환경 문서 9.1절과 5.5절과 준비 문서 5.7절의 `RELOAD=copy` 기본값이 모두 이 명령에 걸려 있다. `loader master` 는 작업본을 마스터로 복사하고 `du -sb` 로 두 크기가 같은지 확인한다 [S:4.2].

**`loader verify` 의 본체는 적재 완료 판정이다.** 수집 문서 6.2절의 네 조건이 **연속 60초 유지되는지**를 관리 창구로 확인하고, 그 뒤에 포인트 수와 세션 수와 payload 인덱스 개수 11개가 `load.yaml` 과 같은지를 보고한다 [S:4.2]. "요청을 다 보냈다"와 "적재가 끝났다"는 다르다. 원문은 뒤의 보고만 적었다.

**`driver recall` 은 부하 워커를 띄우지 않는다.** 미리 정한 질의 집합으로 평소 검색과 `exact` 검색을 각각 한 번씩 돌려 비교만 한다 [S:8.5]. 설계서 4.5.3절은 측정점마다 부하를 멈추고 재라고 요구한다.

### 7.1 제어기 순서 (SPEC 4.7절) — 원문에 통째로 빠져 있던 절

조건 하나에 대해 제어기가 하는 일은 아래 순서다. 번호 (1)부터 (7)까지는 작업 단계 번호나 제작 순서 M0~M6 과 다른 것이다. [S:4.7]

```
(1) run_condition.sh 호출        RELOAD 기본값 copy, 마스터가 없으면 ingest.
                                 "조건이 섰다" 확인 뒤 CG, IODEV, DISKDEV 를 잡고
                                 결과 디렉터리를 만들고 수집기를 띄운다. snap 00_start
(2) 적재기 호출과 완료 대기       ingest 면 loader load 뒤 loader verify, copy 면 loader verify 만.
                                 끝나면 §3 불변식 4 대로 적재기 프로세스가 없는지 확인한다
(3) 마스터 사본 생성              마스터가 없을 때 한 번만 loader master. 그 뒤 RELOAD=copy 로
                                 (1)부터 다시 시작한다 (게이트 C 는 copy 경로에서만 실행된다)
(4) snap 10_ingest_end           SNAP_RESET=1
(5) 부하기 호출(사다리)           질의 파일을 읽어 표준 입력으로 흘려 넣고 단마다 driver run 을
                                 한 번씩 부른다. 호출 사이 부하가 멈춘 상태에서 snap 2N_step_<n>.
                                 올림 사다리 뒤에 내림 사다리. 스냅샷마다 묶음 파일을 곁들인다
(6) 꼬리 구간과 봉인              정리 작업 소진 대기, snap 90_tail_end 를 SNAP_RESET=0 으로,
                                 수집기 정지, 봉인
(7) 저장 부하 뒤 마스터 복원      저장 부하가 섞인 실행이었으면 다음 조건 전에 run_condition.sh 를
                                 RELOAD=copy 로 다시 부른다. 게이트 A 와 게이트 C 재통과가 그 안에 있다
```

**환경 문서 5.4절의 의무 네 가지를 여기서 받는다** [S:4.7]. 환경 문서 5.4절이 두 문서가 서로 미루던 상태를 이미 정리하면서 "`run_condition.sh` 는 제어기가 조건마다 sudo 로 호출하는 부품이지 제어기가 아니다"라고 못박았다.

| 의무 | 위 순서에서의 자리 |
|---|---|
| 1. 부하 직전에 적재기가 끝났는지 확인 | (2)의 끝 |
| 2. 질의 파일을 읽어 부하기의 표준 입력으로 흘려 넣기 | (5) |
| 3. 사다리를 제어기가 돌고 단 사이에 경계 스냅샷 | (5) |
| 4. 저장 부하가 섞인 실행 뒤 마스터 복원 | (7) |

**계측 값 묶음 파일 `stage_groups.json` 도 제어기 몫이다** [S:6.5]. driver 는 `/stage_timings` 를 읽지 않으므로(§3 불변식 2) 18개 지점을 여덟 묶음으로 묶어 스냅샷마다 곁들이는 일은 제어기가 한다. **18개 상세와 8묶음이 둘 다 남아야 한다.** 검증 기준은 각 묶음의 시간 합이 그 묶음에 속한 지점의 `total_nanos` 합과 같고, 검색 네 묶음의 합이 S0부터 S7까지의 합과 같으며 저장 네 묶음의 합이 W0부터 W8까지의 합과 같은 것이다.

**제어기는 부하 구간에 아무것도 하지 않는다.** 부하기가 도는 동안 `driver run` 의 종료만 기다린다. **검증 기준**은 `$RUNDIR` 아래에 수집 문서 9.1절의 디렉터리 구조와 `load/` 산출물과 `snap/` 의 경계 스냅샷이 모두 남고, 스냅샷 이름의 순서가 (4)부터 (6)까지와 같으며, 저장 부하가 섞인 실행 뒤 다음 조건의 `condition.log` 에 `RELOAD=copy` 복원과 게이트 A 와 게이트 C 통과가 찍혀 있는 것이다 [S:4.7].

## 8. 제작 순서와 각 단계의 검증 (SPEC 8장 + 금일 보강)

**제작 순서는 M0부터 M6까지로 부른다.** SPEC 8.1절이 설계서 4.6절의 작업 단계 번호(1부터 5까지와 그 아래 3.1 같은 소번호)와 혼동하지 않으려고 세운 규칙이다 [S:8.1]. **원문이 이를 "단계 0~6"으로 되돌린 것은 SPEC 이 피하려던 충돌을 되살린다.** 원문의 "1단계 loader", "2단계 최소 driver", "5단계 trace 대조"는 설계서의 작업 단계 1(Qdrant Docker 환경 준비), 2(데이터셋 받기), 5(측정)와 그대로 충돌한다. 이 판의 절 번호는 §8.0(M0), §8.1(M1부터 M6까지 묶음), §8.2(M5 대조의 기준과 예외) 셋이고, 본문에서는 M 표기를 쓴다.

### 8.0 M0 — 바닥 측정으로 언어 확정 (**여전히 열림**)

- **후보 셋**: 파이썬 `httpx` 직접 조립 + `json` / 파이썬 `httpx` 직접 조립 + `orjson` / Rust `reqwest`. **SPEC 8.3절의 첫 후보였던 `qdrant_client` 비동기를 뺀 것은 §2-9 의 충돌 신고다.**
- **대상**: 스모크 소형 컬렉션, 서버 지연이 거의 0. `driver floor` 로 c ∈ {1, 64, 256, 1000} 에 후보별 p50/p99/max 분포와 최대 QPS 표. [S:8.3]
- **합격 기준은 두 가지다** [S:2.2]. 바닥 지연의 p99 가 본 측정 대상 검색의 p50 보다 충분히 작아야 하고, 도구가 낼 수 있는 최대 QPS 가 본 측정에서 필요한 QPS 보다 넉넉히 커야 한다. **배수의 구체값은 [미결 U3]** 이다. 지금 정하면 지어낸 값이 된다.
- **결정 규칙**: **파이썬이 위 두 기준을 통과하면 파이썬을 쓴다** [S:8.3]. 통과하지 못하면 SPEC 4.6절의 권고대로 Rust 이고 차선이 Go 다(Go 는 준비 문서 4장의 설치 목록에 없어 추가 설치가 필요하다).
- **종료 조건**: 비교표가 나오고 그 표를 근거로 언어를 확정한 한 문단이 설계서 4.4절에 추가되는 것까지. [S:8.2-M0]
- **바이트 대조가 종료 조건에 함께 들어간다.** 처리량만 보는 비교표로는 요청 모양을 바꾸는 직렬화기를 걸러내지 못해 요구사항 R3 를 깬다. **후보가 만든 본문이 [A:5.1] 과 [A:4.1] 의 본문과 바이트 단위로 같아야 한다.**
- **`orjson` 에 대한 판정은 [추론, 벤치 필요] 에서 [추론, 방향 확인됨] 으로만 올린다.** `orjson` 은 이미 두 로컬 가상환경에 있어(repo 3.11.6, mm_speedkick 3.12.0) 설치 없이 잴 수 있었고, 같은 Mac 에서 세 번 재어 아래를 얻었다.

| 측정 회차 | 검색 본문 직렬화 | 저장 배치 직렬화 | 응답 역직렬화 | 6자리 반올림 본문 |
|---|---|---|---|---|
| 1회 | 17.5배 | 17.4배 | 2.8배 | 4.3배 |
| 2회 | 12.0배 | 11.9배 | 2.8배 | 4.3배 |
| 3회 | 14.0배 | 11.7배 | 3.5배 | 7.7배 |

  **세 회차가 서로 맞지 않으므로 배수를 소수 첫째 자리까지 확정값으로 쓰지 않는다.** 벡터 난수와 문자열 값 집합에 좌우되고 단일 코어 측정이라 흔들린다. 세 회차 모두에서 유지되는 것은 방향뿐이다. **전체 정밀도 요청에서 `orjson` 이 표준 `json` 보다 열 배 이상 빠르므로, 원문의 "3~5배"는 과소평가다.** 6자리 반올림에서도 4배에서 8배 사이라 원문 범위를 벗어난다. 확정 배수가 필요하면 M0 에서 측정 서버의 실제 조건으로 다시 잰다.
- **다만 `orjson` 채택은 처리량만 보고 정할 수 없다.** `orjson` 의 numpy 빠른 경로(`OPT_SERIALIZE_NUMPY`)에 float32 ndarray 를 넘기면 처리량이 더 오르지만 **같은 벡터의 본문 크기가 달라진다.** 단정밀도 최단 표기를 쓰기 때문이다. 바이트 수가 달라지면 서버 쪽 JSON 파싱 비용이 달라지는데 그것이 바로 측정 대상이다. SPEC 7.3절은 차원 차이만 대조 예외로 허용했고 정밀도 차이는 예외가 아니다. **`orjson` 을 쓰더라도 벡터는 전체 정밀도 `list[float]` 로 넘기고 numpy 빠른 경로는 쓰지 않는다.**
- [B1-t] 와 [B3-t] 의 사전 근거로 "Python 탈락 아님"을 말하려면 [주2] 의 재측정이 먼저다. 꼬리 지연(GC, GIL)은 벤치로 재는 것 자체가 불가능하므로 M0 실측이 판정한다. [S:2.2]

### 8.1 M1부터 M6까지 — SPEC 8.1 표 유지. 종료 판정 기준도 SPEC 8.2 그대로.

**M1 착수 조건이 있다** [S:10]. APX 9장의 트레이스 검증 1회다. `docs/msr/qdrant_requests/reproduce/` 에서 `reset_stores.sh` 로 저장소를 비우고 `trace_qdrant_requests_raw.py` 를 한 번 돌려, 구간별 요청 수(P0=1, S1=17, S2=17, S3=0, S4=1, S5=1, S6부터 S9 각 1, S10=0, S11=2, S12=1, S13=4)가 맞고 `request_body` 가 [A:9.3] 의 표를 통과해야 적재기 제작을 시작한다. 결과 파일과 그때 쓴 Qdrant 서버 이미지 태그를 함께 남긴다.

적용되는 갱신은 아래와 같다.

- **M1 (loader)**: §4.1 payload 규칙(12키)과 세션 배정과 레지스트리 미재현. `loader master` 포함. 종료 판정에 "`loader master` 가 만든 마스터의 `du -sb` 가 작업본과 같다"가 들어간다 [S:8.2-M1].
- **M2 (검색 전용 최소 driver)**: 완료 시 계측 빌드 왜곡 검증이 열리고 작업 단계 4.5 가 닫힌다 [S:8.1, 8.4].
- **M3 (제어기와 양방향 사다리)**: §7.1 의 제어기, 계수기 연동, `stage_groups.json` 묶음 파일. 종료 판정은 SPEC 4.7절 검증 기준과 6.4절의 올림과 내림 사다리 일치 확인 통과다 [S:8.1, 8.2-M3]. **원문은 §3 에서 runner 를 범위 밖으로 돌린 탓에 M3 에 해당하는 산출물이 아예 없었다.**
- **M5 (trace 대조)**: 아래 §8.2.

### 8.2 M5 충실도 대조의 기준과 예외

**대조 기준은 §4.3 템플릿이 아니다.** SPEC 7.2절과 APX 9장이 speedkick `8d7b832` 에서 새로 뜨는 원문 트레이스 `qdrant_request_trace_raw.json` 을 기준으로 삼고, 그 전에는 APX 의 직렬화 본문을 임시 기준으로 삼으라고 적었다 [S:7.2]. **driver `trace` 모드는 요약본과 원본 본문을 둘 다 남긴다.** 원본은 원문 트레이스와 대조하고 요약본은 옛 트레이스와의 연속성 확인에 쓴다.

**정규화 표 다섯 행** [S:7.3]: 메서드와 경로(컬렉션 이름을 `<coll>` 로), 쿼리스트링(`wait=true` 가 붙는지), 본문의 최상위 키 집합, 필터 트리의 구조(`must`/`should`/`must_not` 의 중첩 모양과 잎의 키 이름), 옵션 값(`with_payload`, `with_vector`, `limit` 과 `top_k` 의 비율은 값까지).

**합격 기준 다섯 개** [S:7.3]: `limit` 이 `top_k` 의 4배, 저장에 `wait=true`, 검색이 `points/query/batch` 이고 `searches=1`, 파티션 필터가 별도 `must` 항목으로 중첩(§4.3 의 방식 B), 검색의 `with_payload` 와 `with_vector` 가 모두 `false`. **검증 기준은 불일치 0건이다.**

**예외는 네 건이다.** 앞 둘은 SPEC 이 정한 것이고 뒤 둘은 이 문서가 더한 것이다. **원문은 SPEC 의 두 건을 빠뜨리고 자기가 더한 두 건만 적었다.**

| # | 예외 | 출처 |
|---|---|---|
| 1 | 차원 차이. 트레이스는 64차원, 본 측정은 768부터 2560까지 | [S:7.3] |
| 2 | 방식 B 필터의 잎 키 이름. 트레이스 [T:S8] 은 색인 없는 `user_id`, 부하기는 색인된 `_producer_id`. 구조는 같고 잎 이름만 다르다 | [S:7.3] |
| 3 | 레지스트리 미재현 | 이 문서 §2-6 |
| 4 | 컬렉션 이름 평이명(`<coll>` 정규화가 흡수) | 이 문서 §2-7 |

## 9. 미결 총람

### 9.0 이번 판에서 닫은 것

| 원문 ID | 미결이었던 것 | 확정값 | 근거 |
|---|---|---|---|
| M1 | 질의 벡터 필드명이 `query` 인가 `vector` 인가 | **`query` 확정.** `QueryRequest` 모델에 `vector` 필드 자체가 없다(`extra="forbid"`). 두 변수를 둘 필요가 없고 M5 를 막던 차단 사유도 사라진다 | [C:qdrant_vector_store.py:355-365][C:qc:http/models/models.py:2478-2511][A:5.1] |
| M4 | 트레이스 S12/S13 삭제 본문 미확인 | **확정.** 기존 트레이스는 삭제 요청만은 요약 문자열이 아니라 원문 JSON 을 그대로 기록한다. 본문 두 갈래는 §4.3 에 옮겨 적었다. 재수집을 기다릴 필요가 없다 | [T:S12,S13][A:6] |
| M7 | 트레이스 채취 시점 MemMachine 커밋 | **speedkick `a8322a7`(2026-09-14) 확정.** `8d7b832` 의 조상이고 그 사이 Qdrant 요청 본문을 바꾼 커밋이 없어 트레이스 값은 HEAD 와 일치한다. 대조 기준 커밋은 §3 에 적었다 | [A:1.1] |

원문의 M1 이 저장 본문 원문까지 묶어 두었던 부분도 [A:4.1] 과 [A:4.2] 로 닫혀 §4.1 과 §4.3 에 확정값으로 들어갔다.

### 9.1 남은 미결 (닫는 조건 명기)

**미결 ID 를 `U1`~`U8` 로 바꾸었다.** 원문은 `M1`~`M7` 을 썼는데 `M0`~`M6` 은 SPEC 8장이 제작 순서에 이미 쓰는 기호라 같은 글자가 두 뜻을 갖고 있었다(원문 §9 의 "M1"은 질의 본문 미확인, SPEC 의 "M1"은 적재기 제작).

| ID | 미결 | 닫는 방법 | 차단하는 것 |
|---|---|---|---|
| U1 | 세션 수, 세션 크기 분포, 검색 대 저장 비율, 통과 비율, payload 문자열 값 길이의 실제값 | 동료 인계(설계서 5.1(가)). 기본값은 zipf 1.0 과 9:1 로 돌아가되 본 측정 조건값은 아님 | M3 이후의 조건 설정 |
| U2 | `_producer_id` 실카디널리티 | 동료 자료. 균등 100개 배정이 실제와 다르면 loader 기본 분포 수정 | M4 |
| U3 | 바닥 p99 배수, 사다리 일치 오차, CPU 포화 임계, tsv 솎기 비율 | 첫 스모크 실측. 지금 정하면 지어내는 것 [S:9.3] | 본 측정 판정 |
| U4 | 개루프 모드 운용 조건과 `t_plan`/`t_send` 의 나란한 해석 | 첫 포화 관측 후 [S:9.4] | 없음(보조) |
| U5 | **(신규)** 부하 도구의 연결 재사용 방식 | 계측 환경의 MemMachine 호스트명 확인. `localhost`/`127.0.0.1` 이면 keep-alive 0 을 흉내 낸다. 쓴 값은 `run.json` 에 기록 [A:2.2, 11] | 없음(기록 의무) |
| U6 | **(신규)** 대상 배포의 `semantic_memory.storage_backend` | 배포 설정 확인. `vector_store` 면 §2-10 결정을 다시 연다. 시맨틱 검색 1건이 몇 개 `set_id` 로 풀리는지도 세션 설정에 달렸다 [A:3.5, 11] | 시맨틱 모델링 여부 |
| U7 | **(신규)** Qdrant 가 평평한 `should` 배열과 좌결합 중첩을 같은 비용으로 처리하는가 | Qdrant v1.19.1 소스의 `StructPayloadIndex::estimate_cardinality` 확인 또는 실측. 소스가 이 머신에 체크아웃되어 있지 않다 [A:11] | 선택도 축 해석 |
| U8 | **(신규)** `exact: true` 리콜 측정의 비용 | 1억 개 전수 스캔의 질의당 소요를 M6 에서 실측. 설계서 4.5.3절이 측정점마다 재라고 요구하므로 총 소요가 일정에 크게 들어올 수 있다 [S:9.3] | M6 일정 |

## 10. 리스크 (SPEC 9.4 + 신규)

- **폐루프의 조정된 누락**: `t_plan`/`t_send` 분리 기록으로 완화 [S:9.4]. 완전 해소는 아니다.
- **루프백 통신**: 단일 서버 확정이라 기록만 한다. **[설계서 4.1][S:9.4]** — 원문은 이를 `[S:4.1]` 로 인용했으나 SPEC 4.1절은 "세 프로그램으로 나눈다"이고 단일 서버와 무관하다. 단일 서버를 확정한 것은 설계서 4.1절 호스트 구성이며 SPEC 자신도 두 곳에서 설계서 4.1절로 귀속한다.
- **[신규, 추론] Python 채택 시 저장 직렬화 병목**([B3-t], 배치 본문 약 66.6KB): 저장 위주 조건에서 driver CPU 선점 가능. 완화는 `orjson` 이고 필요하면 저장 워커만 멀티프로세스로 하되 **꼬리 왜곡 검토 후** 다 **[S:4.6]** — SPEC 4.6절이 "프로세스를 여러 개로 나누면 처리량은 늘지만 프로세스마다 다른 시점에 가비지 수집이 일어나 꼬리가 오히려 지저분해진다"고 이미 경고했다. `driver_peak_cpu_pct` 가 감시자 [S:6.2].
- **payload 더미 필드**: 안전한 진술은 **"더미 키는 어떤 필터 조건에도 들어가지 않으므로(선택도 다이얼은 색인된 `_producer_id` 에 건다) 카디널리티 추정에 영향이 없다"** 이며 Qdrant 내부 동작에 대한 주장이 필요 없다. **원문의 "[사실: 인덱스된 필드만 추정 대상]" 표기는 지웠다.** 지시받은 어느 문서에도 그 진술의 근거가 없고, `estimate_cardinality` 가 받는 것은 payload 가 아니라 filter 이며, 색인 없는 필드를 Qdrant v1.19.1 이 어떻게 추정하는지는 이 머신에서 확인할 수 없다(Qdrant 소스 미체크아웃, [미결 U7]). 참고로 실제 MemMachine 트래픽은 색인 없는 `user_id` 로도 거른다 [T:S8][A:5.3].
- **[신규] `extra_payload_bytes` 가 메모리 축 워킹셋을 바꾼다**: 더미가 키우는 것은 색인이 아니라 payload 저장소다. 계측 구간으로는 W7(payload 저장)만 무거워지고 W8(색인 갱신)은 그대로라 그 분리 자체는 의도한 것이나, **payload 저장소가 차지하는 디스크와 페이지 캐시가 메모리 축 128/256/512GB 조건의 워킹셋을 바꾼다.** `with_payload=false` 라 검색 경로에서 payload 를 한 번도 읽지 않는데도 그렇다 [A:5.4]. **따라서 메모리 축 비교에 쓰는 조건들 사이에서는 이 값을 고정하고, 값을 바꾸는 실행은 메모리 축 비교 대상에서 뺀다.**
- **[신규] 5초 타임아웃과 절반 분할 재시도의 상호작용**: §2-3 이 분할을 재현하지 않기로 했으나, 실제 MemMachine 은 `wait=true` 저장이 5초를 넘기면 `ReadTimeout` 뒤 이미 적용된 쓰기를 절반씩 다시 보낸다 [A:4.4]. **재현하지 않으면 포화 이후의 요청량이 실제보다 적게 나온다.** 업서트라 결과는 멱등이지만 요청 수는 늘어난다.
- **[신규] 본문 크기 외삽의 공백**: SPEC 9.4절이 "트레이스는 64차원으로 기록되었고 768부터 2560차원에서의 요청 본문 크기와 그에 따른 서버 측 JSON 파싱 비용은 외삽이며 실측이 아니다"라고 적었다. [B1] 이 이 공백을 메우려던 측정인데 원문 값이 절반이라 오히려 잘못 메운다([주1]). 2560차원에서는 본문이 약 54KB 로, 원문 값에서 외삽한 약 27KB 의 두 배다. 이 비용은 Qdrant 의 16코어 예산 안에서 발생하므로 무시할 수 없다.
- **[신규] 선택도 다이얼이 MemMachine 의 실제 필터 모양 하나를 재현하지 않는다**: [A:5.3] 은 `m.user_id` 필터가 색인 없는 `user_id` 키로 그대로 Qdrant 에 간다고 적었으나([T:S8]) §4.2 의 `filter` 파라미터는 `partition_only` 와 색인된 `_producer_id` 다이얼 둘뿐이다. 실제 운영이 색인 없는 필드로 거르는 비중이 크다면 그 경로를 따로 재야 한다 [S:9.2].

---

## 11. 원문 대비 변경 목록

원문 `emulator_impl_design_2026-09-21_draft.md` 와 대조할 수 있도록 무엇을 왜 고쳤는지 적는다. 판정은 speedkick `8d7b832` 소스와 APX 와 기존 트레이스로 했다.

| # | 원문 위치 | 판정 | 무엇을 고쳤나 | 왜 |
|---|---|---|---|---|
| 1 | 머리말 3행 | 틀림 | "SPEC 과 충돌하면 이 문서가 우선한다"를 권위 순서 표로 교체 | 2026-09-22 에 SPEC 이 speedkick 기준으로 갱신되고 APX 가 추가되어 요청 모양의 권위가 APX 로 옮겨졌다 (SPEC 머리말) |
| 2 | 인용 규약 6행 | 보강 | `[A:절]` 신설, `[C:]` 의 경로 생략 규칙과 기준 커밋 명시, `[R:§]` 삭제 | REV 가 우리 저장소에 없어 검증 불가. 같은 주장이 모두 소스로 확인되므로 `[C:]`/`[A:]` 로 대체 |
| 3 | §0 [B1] | 틀림 | 8,152바이트를 "약 16.4KB, 원문 값은 7자리 반올림 조건"으로. 주1 신설 | qdrant-client 1.19.0 직접 직렬화로 전체 정밀도 15.3~16.4KB, 7자리 8,161바이트 확인 |
| 4 | §0 [B1]/[B3] 처리량 | 틀림 | 두 값을 [B1-t]/[B3-t] 로 분리하고 재측정 대상으로 표시. 주2 신설 | float 개수 비가 4인데 원문 비는 2.24. 같은 정밀도에서 동시 성립 불가 |
| 5 | §0 [B2] | 맞음(보강) | 값 유지, 조건 칸에 응답 모양(포인트 80건, `id`/`version`/`score`, 약 6KB) 추가 | 이 수가 큰 이유가 `with_payload=false` 인데 표에 전제가 없었다 [A:5.4] |
| 6 | §0 [B3] | 부정확 | "11필드 payload"를 "12키"로. 배치 본문 약 66.6KB 추가. 442바이트는 확인불가로 표시. 주3 신설 | 트레이스 [T:S4,S5] 의 `payload_keys` 가 12개. 442 를 정하는 것은 키 개수가 아니라 미기록 문자열 길이 |
| 7 | §0 [B4], 조건 칸 | 부정확 | "이 머신"을 측정 서버(344 vCPU)로 명시. 주4 신설 | 어느 머신인지 표기가 없어 공용 서버 여부와 동시 부하가 가려졌다. 오염 판정은 아니다 |
| 8 | §0 조건 칸 | 누락 | 벡터 부동소수 정밀도를 반드시 적도록 요구 | 표의 네 행이 전부 이 한 조건에 달려 있다 |
| 9 | §1 비목적 25행 | 부정확 | "제어기 `run_condition.sh` 몫"을 "작업 단계 1.5의 `run_condition.sh` 몫이며 제어기는 호출만 한다"로 | 제어기와 스크립트는 다른 것이다 [S:2.3, 4.7] |
| 10 | §2 표 3번 | 부정확 | 결정 유지, 근거 교체("실패 유도 실험 없음"에서 "포화 시 5초 타임아웃이 재시도를 유발함을 알고도 재현 안 함"으로) | APX 4.4절이 `ReadTimeout` 경로를 적었고 8장이 타임아웃을 5000 으로 확정해 포화 탐색 자체가 재시도 경로를 밟는다. APX 11장은 이 항목을 미정으로 남겼다 |
| 11 | §2 표 4번 | 틀림 | "트레이스 S12/S13 원문 미확인" 단서 삭제, 삭제 본문을 확정값으로 §4.3 에 이동 | 기존 트레이스가 삭제 본문을 원문 JSON 으로 기록하고 있다 |
| 12 | §2 표 6번 | 부정확 | 근거를 "부하 구간에 안 들어옴"에서 "세션 여는 이벤트를 부하 모델에 넣지 않기로 했으므로 제외"로. 줄 번호를 세 구간으로 분할 | 레지스트리 retrieve 는 `open_collection` 마다 나간다 [T:S11][C:qdrant_vector_store.py:766-784] |
| 13 | §2 표 7번 | 부정확 | "sha256(스키마)"를 "sha256(차원과 색인 스키마를 담은 설정 JSON)"으로. `dim` 변경이 이름을 바꾼다는 단서 추가 | 해시 입력에 `vector_dimensions` 가 함께 들어간다 [C:data_types.py:17-31] |
| 14 | §2 표 2번, 8번 | 맞음(보강) | 2번 근거에 삭제 경로와 클라이언트 `delete` 기본값 추가. 8번을 `247-250` 으로 | 원문은 저장 경로만 가리켰다. `prefer_grpc` 기본값은 248행이다 |
| 15 | §2 표 | 누락 | 결정 9(M0 후보 셋), 10(semantic 네임스페이스), 11(세션 생성 이벤트) 신설 | 원문이 SPEC 8.3절과의 충돌을 말없이 처리했고, APX 3.5절과 3.6절이 요구한 두 결정이 없었다 |
| 16 | §2, §10 의 `[R:§]` | 맞음(표기 변경) | REV 인용을 소스와 APX 인용으로 교체 | REV 의 주장은 모두 소스로 확인되나 문서 자체가 우리에게 없어 검증할 수 없다 |
| 17 | §3 runner 상자 51-52행 | 틀림 | 제어기를 범위 밖에서 산출물로 되돌리고 §7.1 신설 | SPEC 1장과 4.7절, 환경 문서 5.4절, 설계서 4.4절과 4.6절이 제어기를 작업 단계 3.4로 확정했다 |
| 18 | §3 불변식 | 부정확 | 불변식 6(R7, `findmnt` 로 `$RAW` 와 `$BENCH` 가 다른 장치) 추가 | SPEC 2.1절 요구사항 일곱 개 중 R7 이 빠져 있었다 |
| 19 | §3 불변식 5 | 틀림(전파) | "8.1KB×1000 = 8MB"를 "약 16.4KB×1000 = 약 16MB"로. M0 실측 조정 절차 추가 | [B1] 정정의 전파. 4GiB 결론은 바뀌지 않는다 [S:4.3] |
| 20 | §3 색인 내역 62행 | 틀림 | "str 8 + int 1"을 "str 7 + int 1"로. 표로 분해 | 1+2+8+1 = 12 가 되어 같은 문장의 11과 모순. `EVENT_BACKEND_SYSTEM_FIELDS` 는 str 7, int 1, datetime 1 |
| 21 | §3 | 누락 | 대조 기준 커밋(speedkick `a8322a7` 채취, HEAD `8d7b832` 와 동일) 추가 | 원문 [미결 M7] 을 닫은 자리 |
| 22 | §4.1 | 누락 | `producer_dial_values` 와 `holdout` 추가, 세션 배정 주체 명시 | SPEC 3.3절 파라미터를 원문이 상수로 되돌렸고, SPEC 5.4절의 홀드아웃 요건이 빠져 있었다 |
| 23 | §4.1 payload 규칙 81행 | 틀림 | 9개 열거를 12키 표로 교체. `sys-partition_key` 와 `_session_key` 와 사용자 키 추가. 키 순서 규약 추가 | 열거가 두 키 모자라고 사용자 키가 빠졌다 [A:4.2][T:S4] |
| 24 | §4.1 uuid4 표기 | 부정확 | `_episode_uid` 와 `_produced_for_id` 의 uuid4 채움에 [사실] 대신 [추론] | 코드에서 둘은 클라이언트가 준 문자열이고 트레이스의 `_produced_for_id` 는 짧은 값이다 |
| 25 | §4.2 `timeout_ms` | 틀림 | 30000 을 **5000** 으로. 주석에 근거와 표시 의무 | 클라이언트가 `timeout` 을 넘기지 않아 httpx 기본 5초가 실효값 [A:8][C:database_manager.py:608-618] |
| 26 | §4.2 `top_k` | 부정확 | 값 20 유지, `[T:S6]` 근거 표기 삭제, REST 기본 10과 트레이스 80의 출처를 주석으로 | 20 은 파이썬 직접 호출 기본값이고 트레이스 80 은 스크립트가 명시한 값의 4배다 [A:5.2] |
| 27 | §4.2 | 누락 | `connection_reuse` 항목 신설 | APX 2.2절이 `localhost` 대상 keep-alive 0 을 확정하고 기록을 요구했다 |
| 28 | §4.3 방식 B 파티션 위치 | 틀림 | 파티션을 맨 `FieldCondition` 에서 한 겹 감싼 `Filter` 로. 방식 A 와 B 를 두 벌로 분리 | 코드가 하위 Filter 를 평탄화하지 않는다 [C:qdrant_vector_store.py:342-353][T:S7,S8] |
| 29 | §4.3 `should` 배열 | 틀림 | 평평한 k원소 배열을 좌결합 이항 중첩으로. k=1, 2, 3 본문 제시 | 파서가 `Or(left, right)` 이항 트리를 만든다 [C:filter_parser.py:207-226] |
| 30 | §4.3 k=1 | 틀림 | k=1 은 `should` 가 아예 없음을 명시 | 원소 1개짜리 `should` 를 보내면 MemMachine 이 내지 않는 모양이 되어 M5 바이트 대조가 실패한다 |
| 31 | §4.3 필드명 119행 | 이미해소 | [미결 M1] 문단 삭제, `query` 확정 | `QueryRequest` 에 `vector` 필드 자체가 없다 |
| 32 | §4.3 키 순서 | 부정확 | `query`, `filter`, `limit`, `with_vector`, `with_payload` 로 정정 | pydantic 이 선언 순서대로 직렬화한다. `with_vector` 가 앞선다 |
| 33 | §4.3 | 누락 | `score_threshold` 부재의 근거 한 문단 추가 | 근거가 없어 나중에 다시 열릴 수 있었다 [T:S9] |
| 34 | §4.3 | 누락 | 바이트 조립 규약(키 순서, float 표기, 정규화 대상) 추가 | 라이브러리 미사용 전제 때문에 손으로 맞춰야 하는데 규약이 없었다 |
| 35 | §4.3 삭제 121행 | 부정확 | 레코드 삭제와 논리 컬렉션 삭제를 두 갈래로 분리, 각각 JSON 제시 | 세션 삭제는 파티션이 감싸이지 않는 별개 모양이다 [A:6.2][T:S13] |
| 36 | §5 | 누락 | 질의 집합 홀드아웃, 저장 부하 뒤 마스터 복원 의무, `session_skew` 검증 기준 추가 | SPEC 5.2절과 5.3절과 5.4절의 요건이 빠져 있었다 |
| 37 | §6.1 | 부정확 | `connection_reuse`, `timeout_ms`, `over_fetch`, `memmachine_ref_commit` 추가 | APX 와 SPEC 3.4절과 수집 문서 9.2절이 새로 요구한 항목 |
| 38 | §7 절 제목 150행 | 틀림 | "제어기 계약 (SPEC 4.2)"을 "명령행 계약 (SPEC 4.2)"으로 | SPEC 4.2절은 적재기와 부하기의 명령행 계약이고 제어기 계약은 4.7절이다 |
| 39 | §7 목록 | 틀림 | `loader master` 한 줄 추가, `loader verify` 설명에 적재 완료 판정 네 조건 연속 60초 추가 | SPEC 4.2절의 여덟 줄 중 하나가 빠졌고 verify 의 본체가 빠졌다 |
| 40 | §7 | 누락 | §7.1 제어기 순서 (1)~(7), 의무 네 가지, `stage_groups.json` 신설 | 제어기를 범위 밖으로 둔 탓에 통째로 빠져 있었다 |
| 41 | §8 단계 번호 | 틀림 | "단계 0~6"을 "M0~M6"으로 | SPEC 8.1절이 설계서 작업 단계 번호와의 혼동을 피하려고 정한 규칙을 되살린다 |
| 42 | §8.0 후보 셋 167행 | 틀림 | 전송 축(파이썬 httpx, Rust reqwest) + `orjson` 변형으로 재구성, 충돌을 §2-9 에 신고 | SPEC 8.3절 첫 후보가 SPEC 4.6절과 충돌하는데 원문이 말없이 교체했다 |
| 43 | §8.0 orjson 167행 | 틀림 | "3~5배 [추론, 벤치 필요]"를 실측 "직렬화 12.0배, 역직렬화 2.8배 [사실]"로. 측정 조건 명기 | 로컬 가상환경에 orjson 이 있어 잴 수 있었다. 3~5배는 6자리 반올림 벡터에서만 나온다 |
| 44 | §8.0 | 누락 | SPEC 2.2절 합격 기준 둘, SPEC 8.3절 결정 규칙, 바이트 대조 종료 조건, numpy 빠른 경로 금지 추가 | 무엇을 통과해야 하는지와 무승부일 때 무엇을 고르는지가 없었다 |
| 45 | §8.1 173행 | 틀림 | 대조 기준을 §4.3 템플릿에서 원문 트레이스(없으면 APX 본문)로. 예외를 네 건으로 재편. §8.2 신설 | SPEC 7.3절의 예외는 차원 차이와 방식 B 잎 키 이름이고 원문의 두 건은 이 문서가 더한 것이다 |
| 46 | §8.1 | 누락 | M1 착수 조건(APX 9장 트레이스 검증 1회) 추가 | SPEC 10장이 못박은 전제 조건이 없었다 |
| 47 | §8.1 | 누락 | M3 산출물(제어기, 양방향 사다리, 묶음 파일)과 종료 판정 추가 | 원문에 M3 에 해당하는 산출물이 없었다 |
| 48 | §9 ID 체계 | 틀림 | `M1`~`M7` 을 `U1`~`U8` 로 | `M0`~`M6` 은 SPEC 8장이 제작 순서에 이미 쓰는 기호다 |
| 49 | §9 | 이미해소 | M1, M4, M7 을 §9.0 표로 이관 | 셋 다 소스와 트레이스로 닫혔다 |
| 50 | §9 | 누락 | U5(연결 재사용), U6(semantic 배포 설정), U7(Qdrant 의 중첩 should 비용), U8(exact 리콜 비용) 신설 | APX 11장과 SPEC 9.3절이 남긴 미확인 사항 |
| 51 | §10 루프백 190행 | 부정확 | `[S:4.1]` 을 `[설계서 4.1][S:9.4]` 로 | SPEC 4.1절은 "세 프로그램으로 나눈다"이고 단일 서버와 무관하다 |
| 52 | §10 멀티프로세스 191행 | 맞음(보강) | "꼬리 왜곡 검토 후" 뒤에 `[S:4.6]` 추가 | SPEC 4.6절이 이미 멀티프로세스의 꼬리 악화를 경고했다 |
| 53 | §10 더미 필드 192행 | 틀림 | "[사실: 인덱스된 필드만 추정 대상]" 표기 삭제, 진술을 "더미 키는 어떤 필터에도 없다"로 교체 | 근거 없는 [사실] 표기였고 논점이 어긋났다. `estimate_cardinality` 가 받는 것은 filter 다 |
| 54 | §10 | 누락 | `extra_payload_bytes` 의 워킹셋 오염, 5초 타임아웃과 분할 재시도, 본문 크기 외삽 공백, 선택도 다이얼의 미재현 모양 추가 | 원문이 놓친 실제 위험 넷 |
| 55 | 머리말 3행 | 보정 | "구조와 문체와 인용 규약은 원문 그대로"에 새 절 두 개를 세운 사실을 덧붙임 | 자기 서술과 실제 구조가 어긋나 있었다 |
| 56 | §3 불변식 2 | 누락 | "적재기와 제어기는 이 불변식과 불변식 1의 적용을 받지 않는다" 추가 | SPEC 2.2절이 명시한 예외인데 원문과 앞 판 모두 빠뜨렸다 |
| 57 | §4.2 `selectivity_pct` | 누락 | SPEC 3.5절 검증 기준(`/telemetry` 경로 전환 관측, 색인 11개 유지) 추가 | 앞 판이 옮긴 절별 검증 기준 여섯 중 3.5절만 빠져 있었다 |
| 58 | §4.1 `payload_index_count` | 누락 | 설계서 4.4절의 0~12 와 SPEC 3.3절의 0~11 이 갈리는 이유(시맨틱 포함 여부)를 주석으로 | 두 문서를 함께 읽는 사람이 모순으로 볼 수 있었다 |
| 59 | §4.1 `holdout` | 누락 | `extra_payload_bytes` 와 같은 "SPEC 갱신 필요" 표시 추가 | 같은 처지인데 표시가 한쪽에만 있었다 |
| 60 | §0 [주2], §8.0 orjson | 부정확 | 배수를 [사실] 확정값에서 세 회차 측정표와 방향 판정으로 격하 | 세 측정(17.5/12.0/14.0배, 6자리 4.3/4.3/7.7배)이 서로 맞지 않는다. 방향(열 배 이상, 원문 3~5배는 과소평가)만 유지 |
| 61 | §0 50행, §8.0 | 부정확 | "[B1]~[B3]"과 "[B1-t]~[B3-t]" 범위 표기를 실제 ID 집합으로 | ID 분리 뒤 [B2-t] 가 없어 범위 표기가 성립하지 않았다 |
| 62 | §2-10 | 부정확 | `configuration/__init__.py:89-96` 에 기본값 줄 `110-111` 추가 | 89-96 은 enum 선언이고 `default=AUTO` 는 111행이다 |
| 63 | §3 컬렉션 JSON | 부정확 | `"size":768` 을 `"size":<dim>` 로 | `[T:S1]` 은 64차원이다. 원문의 `size:dim` 자리표시자를 되살렸다 |
| 64 | §8 절 번호 | 틀림 | §8.0, §8.1(M1~M6), §8.2(M5 대조)로 연속화. §8.5 참조 세 곳 갱신 | "§8.0부터 §8.6까지"라 선언했으나 실제 표제는 셋뿐이고 §8.5 가 §8.1~8.6 안에 다시 나타났다 |
| 65 | §11 1번 | 부정확 | `[S:5]` 를 "SPEC 머리말"로 | 인용 규약상 `[S:5]` 는 SPEC 5장(워크로드 모델)로 읽힌다 |
| 66 | §11 5번 | 부정확 | "조건 칸에 추가"를 "[B2] 내용 칸에 추가"로 | 실제로는 내용 칸에 들어갔다 |
| 67 | §11 16번 | 부정확 | "§2, §10 의 `[R:§]`" 에서 §10 을 뺌 | 원문의 `[R:§]` 는 §2 와 인용 규약에만 있었다 |
| 68 | §11 | 누락 | §3 불변식 2 설명 문장, §7 `driver recall` 문단, §3 컬렉션 JSON 분리, 경로 대응 절 신설을 변경 목록에 추가 | 실제로 한 변경이 목록에 없었다 |

---
**이 문서의 근거 원본**: SPEC 본문과 부록 CH 표 / **APX `emulator_request_spec_2026-09-22.md`(요청 모양의 권위)** / 설계서 4.1, 4.4, 5.1 / 수집문서 9.1~9.3 / 환경문서 5.3~5.5 / 준비문서 5.7 / MemMachine 코드 speedkick HEAD `8d7b832` 실측 / 기존 트레이스 `qdrant_request_trace.json`(speedkick `a8322a7` 채취) / 벤치 [B1]~[B4](§0 조건과 주1~주4) / 결정 [D:2026-09-21] 5건.
