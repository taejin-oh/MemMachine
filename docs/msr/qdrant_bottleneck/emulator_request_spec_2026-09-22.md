# 부하 도구 요청 명세 부록 (speedkick 8d7b832 기준)

`emulator_spec_2026-09-21.md`(부하 도구 명세)의 부록이다. 부하 도구가 Qdrant 에 보내야 하는 요청을 MemMachine 의 **speedkick 브랜치(upstream/speedkick, HEAD `8d7b832`, 2026-09-17)** 소스에서 확정한다. 이 문서만 읽고 트레이스 없이 요청을 바이트 단위로 재현할 수 있어야 한다는 것이 목표다. 명세 본문의 3.1절과 3.4절과 7장과 9.2절은 이 부록을 권위로 삼는다.

**줄 번호 표기 규칙.** 접두가 없는 경로는 전부 `/Users/taejin/Projects/MemMachine/mm_speedkick/packages/server/src/memmachine_server/` 아래이며 줄 번호는 커밋 `8d7b832` 의 작업 트리 기준이다. 그 밖의 경로는 접두로 구분한다.

| 접두 | 실제 위치 | 무엇인가 |
|---|---|---|
| (없음) | `mm_speedkick/packages/server/src/memmachine_server/` | MemMachine 서버 소스 |
| `spec.py` | `mm_speedkick/packages/common/src/memmachine_common/api/spec.py` | REST 요청 스키마(서버 패키지 밖) |
| `qc:` | `mm_speedkick/.venv/lib/python3.12/site-packages/qdrant_client/` | qdrant-client 1.19.0 (uv.lock 이 고정) |
| `httpx:` | `mm_speedkick/.venv/lib/python3.12/site-packages/httpx/` | httpx 0.28.1 |
| `옛:` | `/Users/taejin/Projects/MemMachine/repo/packages/server/src/memmachine_server/` | msr_multiuser(`89bec05`) 소스. 차이를 보일 때만 인용 |
| `trace:` | `/Users/taejin/Projects/MemMachine/repo/docs/msr/qdrant_requests/` | 기존 트레이스와 재현 도구 |

이 문서에 적힌 JSON 본문은 전부 speedkick 의 venv 에서 qdrant-client 1.19.0 의 `jsonable_encoder` 로 실제 직렬화해 얻은 것이다(2026-09-22, 검증 스크립트는 세션 scratchpad 의 `dump_bodies.py`). 직렬화 규칙은 `exclude_unset=True, exclude_none=True` 이므로(`qc:http/api/points_api.py:25-42`) 값이 `None` 인 필드는 본문에서 빠진다. 아래에서 "빠진다"고 적은 필드는 모두 이 규칙 때문이다.

---

## 1. 요약

### 1.1 기존 문서와 트레이스의 기준이 어긋나 있었다

**기존 문서는 두 브랜치를 섞어 읽고 있었다.** 부하 도구 명세 3.1절과 9.2절, 그리고 데이터셋 문서(`dataset_options_2026-09-17.md`) 2.3절이 인용한 소스 줄 번호(`qdrant_vector_store.py:373`, `long_term_memory.py:106` 과 `324`, `database_conf.py:246`, `event_memory.py:428` 등)는 전부 **msr_multiuser(`89bec05`)** 소스의 줄이다. 반면 그 문서들이 값의 출처로 삼은 트레이스 `qdrant_request_trace.json` 은 "msr_multiuser 기준"이라고 알려져 있었으나 **실제로는 speedkick `a8322a7`(2026-09-14) 에서 채취된 것이다.** 트레이스 스크립트 첫 줄이 `speedkick a8322a7` 을 적고 있고(`trace:trace_qdrant_requests.py:1`), 재현 안내가 그 커밋을 체크아웃하게 되어 있으며(`trace:reproduce/README.md:150-163`), 측정 기록 문서도 같은 커밋을 적는다(`trace:qdrant_requests_by_state_2026-09-15.md:4`, `trace:qdrant_report_2026-09-16.md:4`). 코드 증거로는, 트레이스의 모든 검색이 `with_payload=False` 인데 msr_multiuser 소스는 두 검색 경로 모두 `return_properties=True` 를 넘겨 `with_payload=true` 로 보내므로(`옛:common/vector_store/qdrant_vector_store.py:341-344, 372-374`, `옛:episodic_memory/event_memory/event_memory.py:427-428`, `옛:semantic_memory/storage/vector_store_semantic_storage.py:653-654`) 그 트레이스는 msr_multiuser 에서 나올 수 없다.

두 브랜치는 `a681abf`(2026-07-28) 에서 갈라졌다. `a8322a7` 은 speedkick HEAD `8d7b832` 의 조상이고(`git merge-base --is-ancestor` 확인), 그 사이에 서버 소스를 바꾼 커밋은 `779362c`(커스텀 샤딩 제거)와 `8d7b832`(SQL 필터 검증) 둘뿐이며 Qdrant 요청 본문을 바꾼 것은 없다. **따라서 기존 트레이스의 값은 speedkick HEAD 와 일치하고, 어긋나 있던 것은 문서의 줄 번호 인용과 "옛 코드로 보면 with_payload 가 true 여야 한다"는 9.2절의 추론이다.** 명세 9.2절이 "코드와 트레이스가 어긋난다"고 적은 문제는 msr_multiuser 코드와 speedkick 트레이스를 나란히 놓아 생긴 착오이며, speedkick 기준으로는 `with_payload=false` 가 코드에서도 트레이스에서도 확정값이다.

### 1.2 msr_multiuser 소스와 speedkick 소스에서 달라진 값

아래는 두 브랜치의 **소스**를 비교한 결과다. 기존 트레이스가 speedkick 값이므로 "기존 문서의 값이 틀렸다"가 아니라 "기존 문서가 인용한 옛 소스대로면 이렇게 달랐을 것"으로 읽어야 한다. 네 커밋에 차이가 집중된다. `abf92a3`(2026-09-09, 검색 응답을 uuid 와 점수만으로), `a2a1754`(2026-09-03, 컬렉션이 있어도 색인 생성), `a8322a7`(2026-09-14, 프로젝트별 사용자 속성 색인 제거), `779362c`(2026-09-16, 커스텀 샤딩 제거).

| 항목 | msr_multiuser(`89bec05`) 소스 | speedkick(`8d7b832`) | 근거(speedkick) |
|---|---|---|---|
| 검색 `with_payload` | 어댑터 인자 `return_properties` 기본 `True`, 두 검색 경로 모두 `True` 를 넘김 | 리터럴 `False` 고정. 인자 자체가 없음 | `common/vector_store/qdrant_vector_store.py:361-362`, `common/vector_store/vector_store.py:63-71` |
| 검색 `with_vector` | 어댑터 인자 `return_vector` | 리터럴 `False` 고정 | 같은 곳 |
| 데이터 컬렉션 `retrieve`(`POST /collections/{c}/points`) | `get()` 이 있어 시맨틱 `update_feature` 가 사용 | `get()` 이 인터페이스에서 제거되어 없음. `retrieve` 는 레지스트리 조회뿐 | `common/vector_store/vector_store.py:63-100`, `qdrant_vector_store.py:583-587` |
| `long_term_memory` payload 색인 개수 | 12개(`_segment_uuid` 추가) 더하기 `properties_schema` 의 사용자 필드 | **11개 고정.** 사용자 필드가 들어갈 경로가 없음 | `qdrant_vector_store.py:655-667`, `episodic_memory/event_memory/event_memory.py:110-127`, `episodic_memory/long_term_memory/long_term_memory.py:79-89`, `episodic_memory/long_term_memory/service_locator.py:111-117` |
| 네이티브 컬렉션이 이미 있을 때(409) 색인 PUT | 0회(컬렉션 생성과 색인 생성이 한 `try` 안) | 항상 `1 + len(schema)` 회(각각 독립 guard) | `qdrant_vector_store.py:634-678` |
| 업서트 payload 키 `_segment_uuid` | 있음 | 없음 | `event_memory.py:316-335` |
| 네이티브 컬렉션 이름의 해시 입력 | `similarity_metric` 과 `_segment_uuid` 포함 | 둘 다 없음. **같은 차원이라도 컬렉션 이름이 옛 브랜치와 다르다** | `qdrant_vector_store.py:513-519`, `common/vector_store/data_types.py:17-31` |
| 레지스트리 포인트 payload 키 | 4개(`similarity_metric` 포함) | 3개(`name`, `vector_dimensions`, `indexed_properties_schema`) | `qdrant_vector_store.py:686-702` |
| 거리 함수의 출처 | `config.similarity_metric` 을 매핑(COSINE, DOT, EUCLID, MANHATTAN) | 상수 `COSINE`. 설정으로 바꿀 수 없음 | `qdrant_vector_store.py:450, 633, 644` |
| 커스텀 샤딩(`is_distributed`, `shard_key`, `create_shard_key`, `delete_shard_key`, `sharding_method`) | 있음(기본값 `False` 라 본문은 같았음) | 전부 제거 | `common/configuration/database_conf.py:232-261`, `qdrant_vector_store.py:230-244, 641-650, 815-830` |
| 시맨틱 업서트 payload 와 포인트 id | 필드 11개와 metadata 를 payload 로, id 는 `uuid5(feature_id)` | payload 는 `sys-partition_key` 뿐, id 는 행에 저장한 `uuid4` | `semantic_memory/storage/vector_store_semantic_storage.py:231-253` |
| 시맨틱 삭제의 uuid 출처 | `uuid5` 계산 | PG 선조회(`_vector_uuids_for_features`) | 같은 파일 `585-602` |
| `QdrantConf` | `is_distributed` 있음 | `is_distributed` 없음, `MetricsFactoryIdMixin` 추가 | `database_conf.py:232` |
| qdrant-client | 1.18.0 | 1.19.0. 이 문서가 쓰는 메서드의 시그니처는 동일 | `mm_speedkick/uv.lock` |

### 1.3 두 브랜치에서 같은 값

`m=0`, `payload_m=16`, 거리 `Cosine`, 테넌트 색인 `sys-partition_key`(`is_tenant=true`), 색인 11개의 이름과 순서, 색인 생성과 데이터 업서트와 삭제의 `?wait=true`(클라이언트 기본값), 검색 over-fetch 4배, 검색 엔드포인트 `points/query/batch` 와 `searches=1`, 필터 조립 규칙, 삭제 본문(파티션 필터 AND `has_id`), 레지스트리 컬렉션 생성과 조회 형태, 업서트 실패 시 절반 분할 재시도, 클라이언트 생성 인자. **기존 문서의 이 값들은 speedkick 에서도 그대로 옳다.**

---

## 2. 연결과 전송 방식

### 2.1 설정 항목

`QdrantConf` 의 필드는 아래가 전부다. 타임아웃, HNSW, 세그먼트, 차원에 관한 항목은 없다.

| 필드 | 기본값 | 근거 |
|---|---|---|
| `host` | `"localhost"` | `common/configuration/database_conf.py:235-238` |
| `port` | `6333` (REST) | `database_conf.py:239-242` |
| `grpc_port` | `6334` | `database_conf.py:243-246` |
| `prefer_grpc` | `False` | `database_conf.py:247-250` |
| `https` | `False` | `database_conf.py:251-254` |
| `registry_replication_factor` | `1` | `database_conf.py:255-261` |
| `api_key` | 비어 있음(`ApiKeyMixin`) | `database_conf.py:232` |
| `metrics_factory_id` | (`MetricsFactoryIdMixin`) 요청에 영향 없음 | `database_conf.py:232` |

### 2.2 클라이언트 생성과 실효값

`DatabaseManager` 는 `{host, port, grpc_port, prefer_grpc, https}` 에 `api_key` 가 비어 있지 않을 때만 `api_key` 를 더해 `AsyncQdrantClient(**client_kwargs)` 를 만든다(`common/resource_manager/database_manager.py:608-618`). `timeout` 을 넘기지 않으므로 아래 실효값은 qdrant-client 와 httpx 의 기본값이다.

| 항목 | 실효값 | 근거 |
|---|---|---|
| 전송 | REST, `http://localhost:6333` (설정값 `host`, `port` 로 조립) | `qc:async_qdrant_remote.py:168-170` |
| HTTP 버전 | HTTP/1.1 (`http2=False`) | `qc:async_qdrant_remote.py:118, 171` |
| 요청 타임아웃 | `timeout=None` 이라 httpx 기본값 `Timeout(timeout=5.0)`, 곧 connect, read, write, pool 각 5초 | `qc:async_qdrant_client.py:94` (timeout 기본 None), `qc:async_qdrant_remote.py:105, 174-178`, `httpx:_config.py:246` |
| gRPC 기본 타임아웃 | 5초(`DEFAULT_GRPC_TIMEOUT`). REST 경로에서는 쓰이지 않음 | `qc:async_qdrant_remote.py:45, 178` |
| 연결 풀 | `host` 가 `"localhost"` 또는 `"127.0.0.1"` 이면 `httpx.Limits(max_connections=None, max_keepalive_connections=0)`. **keep-alive 없이 요청마다 새 TCP 연결을 맺는다.** 그 밖의 호스트면 httpx 기본값(최대 100, keep-alive 20) | `qc:async_qdrant_remote.py:108-111` |
| 헤더 | `User-Agent: python-client/1.19.0 python/3.12.13`, `Content-Type: application/json`. `api-key` 는 설정했을 때만 | `qc:async_qdrant_remote.py:140-146`, `qc:http/api/search_api.py:77-79` |
| 호환성 검사 | `check_compatibility=True` 기본이라 클라이언트 생성 시 데몬 스레드가 **동기** `httpx.get(rest_uri)` 곧 `GET /` 를 1회 보낸다(타임아웃 5초) | `qc:async_qdrant_client.py:102`, `qc:async_qdrant_remote.py:199-208`, `qc:common/version_check.py:12-15` |

**부하 도구에 대한 함의.** 계측 환경의 MemMachine 설정이 `host: 127.0.0.1` 이면(재현 도구의 `trace:reproduce/config.yml` 이 그렇다) 실제 운영 클라이언트는 요청마다 TCP 연결을 새로 맺는다. 부하 도구가 이 연결 패턴을 흉내 낼지, 아니면 keep-alive 를 쓰는 다른 호스트명 기준으로 잡을지는 11장의 미확인 사항으로 남긴다. 어느 쪽이든 `run.json` 에 어느 패턴을 썼는지 적어야 한다.

### 2.3 연결 검증 요청

`get_vector_store()` 는 `async_get_qdrant_client(name, validate=True)` 를 부르고(`database_manager.py:858-862`), `validate=True` 면 `client.get_collections()` 를 1회 호출한다(`database_manager.py:620-621, 646-656`). 이것이 `GET /collections`(쿼리스트링 없음, 본문 없음)이며 기존 트레이스 P0 의 요청 1건이다. 서버 기동 시에는 `_warm_request_path` 가 같은 경로로 벡터 스토어를 미리 연다(`main/memmachine.py:425-466`).

---

## 3. 컬렉션과 색인 생성

### 3.1 이름 규칙

**네이티브(Qdrant 실제) 컬렉션은 세션마다 만들지 않는다.** 이름은 `f"{namespace}__{sha256(config.model_dump_json()).hexdigest()}"` 이며(`common/vector_store/qdrant_vector_store.py:513-519`), 같은 (namespace, `vector_dimensions`, `indexed_properties_schema`) 조합은 하나의 네이티브 컬렉션을 공유한다. 세션(논리 컬렉션)은 모든 포인트의 payload 에 붙는 `sys-partition_key` 값으로만 구분된다(`qdrant_vector_store.py:60-61, 257-259, 621`).

해시 입력은 `VectorStoreCollectionConfig` 의 JSON 이다. 필드는 `vector_dimensions` 와 `indexed_properties_schema` 둘뿐이고(`common/vector_store/data_types.py:17-31`), 스키마는 키를 정렬해 타입 이름(`bool`, `int`, `float`, `str`, `datetime`)으로 직렬화한다(`data_types.py:65-71`). 차원 768 의 입력은 정확히 아래 한 줄이다.

```json
{"vector_dimensions":768,"indexed_properties_schema":{"_content_type":"str","_created_at":"datetime","_episode_type":"str","_episode_uid":"str","_produced_for_id":"str","_producer_id":"str","_producer_role":"str","_sequence_num":"int","_session_key":"str","_timestamp":"datetime"}}
```

네임스페이스는 둘이다. 에피소드 메모리는 `long_term_memory`(`episodic_memory/long_term_memory/service_locator.py:51`), 시맨틱 메모리는 `semantic_memory`(`common/resource_manager/semantic_manager.py:50`)다. speedkick 코드 경로로 계산한 실제 이름은 아래와 같다. 부하 도구가 컬렉션 이름까지 재현하려면 이 값을 쓴다.

| 네임스페이스 | 차원 | 네이티브 컬렉션 이름 |
|---|---|---|
| `long_term_memory` | 64 | `long_term_memory__d9e60b369f55fa019b18eff48435dbb2e517fea223b410936f516275c81c9d51` |
| `long_term_memory` | 768 | `long_term_memory__721a83c6c374bf9a4798a728c6531a721eea8da0f803373577428fc46ad64e63` |
| `long_term_memory` | 1024 | `long_term_memory__dddff40caf3d4e41a17261c330d14f19cc7bab977da11aaa21edacc8657186e8` |
| `long_term_memory` | 1536 | `long_term_memory__2ce68ee6017ba19056b98b69453812e88da022d3d263347d978ad0a2aed91fcd` |
| `long_term_memory` | 2560 | `long_term_memory__316356a9b435d0f0860154e27c09d53d7528b0022af83cab2d55e7d015863889` |
| `semantic_memory` | 768 | `semantic_memory__7ef2476ed51b4cf45972b704a8606f5279f4f4b6940bd4a39b98a306566191db` |
| `semantic_memory` | 1536 | `semantic_memory__3ba7b16d33a29522630d350c7d1031948a5d8635a296cbd82b48e39c641ceba7` |

**논리 컬렉션 이름(파티션 키).** 에피소드 메모리는 세션마다 하나이며 `partition_key_for_session(session_id)` 가 정한다. `session_id` 가 `[a-z0-9_]+` 이고 32바이트 이하면 그대로, 아니면 `sha256(session_id).hexdigest()[:32]` 다(`service_locator.py:158-182`, `episodic_memory/event_memory/segment_store/utils.py:7-9, 19-25`). 기존 트레이스의 `bd36dbe5eef78ec754963d978108ef7b` 는 `orga/prja` 가 슬래시 때문에 해시된 값이다. 시맨틱 메모리는 논리 컬렉션이 `semantic_memory` 하나뿐이다(`semantic_manager.py:51`). 이 이름이 레지스트리 포인트의 id(`uuid5`)와 모든 포인트의 `sys-partition_key` 값이 된다.

### 3.2 레지스트리 컬렉션

네임스페이스마다 `{namespace}__registry` 컬렉션이 하나 있다(`qdrant_vector_store.py:463, 504-506`). 논리 컬렉션 하나가 포인트 하나다.

| 항목 | 값 | 근거 |
|---|---|---|
| 요청 | `PUT /collections/{namespace}__registry`, 쿼리스트링 없음 | `qdrant_vector_store.py:552-564` |
| 본문 | 아래 JSON. `replication_factor` 와 `write_consistency_factor` 는 `registry_replication_factor`(기본 1) | `qdrant_vector_store.py:555-563`, `database_conf.py:255-261` |
| 실패 처리 | HTTP 409, gRPC `ALREADY_EXISTS`, 메시지에 "already exists" 가 든 `ValueError` 면 무시 | `qdrant_vector_store.py:481-490, 565-567` |
| 언제 | `create_collection` 은 항상 먼저, `open_or_create_collection` 은 레지스트리 항목이 없을 때만 | `qdrant_vector_store.py:725, 761` |

```json
{"vectors":{"size":1,"distance":"Cosine"},"replication_factor":1,"write_consistency_factor":1,"hnsw_config":{"m":0}}
```

### 3.3 네이티브 컬렉션

| 항목 | 값 | 근거 |
|---|---|---|
| 요청 | `PUT /collections/{native}`, 쿼리스트링 없음(`create_collection` 에는 `wait` 인자가 없음) | `qdrant_vector_store.py:640-650` |
| 본문 | 아래 JSON. `size` 는 `config.vector_dimensions` | `qdrant_vector_store.py:643-649` |
| 거리 | `_QDRANT_DISTANCE = COSINE` 상수. 설정과 임베더로 바꿀 수 없음 | `qdrant_vector_store.py:450, 633` |
| `hnsw_config` | `m=0`, `payload_m=self._hnsw_m` 이고 `_hnsw_m = 16` 은 생성자에 하드코딩 | `qdrant_vector_store.py:528, 646-649` |
| 넘기지 않는 것 | `ef_construct`, `full_scan_threshold`, `on_disk`, `optimizers_config`, `quantization_config`, `on_disk_payload`, `shard_number`, `sharding_method`, `replication_factor`, `write_consistency_factor`, `sparse_vectors_config` 전부. 본문에서 빠지므로 **Qdrant 서버 기본값이 적용된다** | `qdrant_vector_store.py:641-650`, `qc:http/api/points_api.py:25-42` |
| 실패 처리 | 3.2절과 같은 already-exists 판정이면 무시 | `qdrant_vector_store.py:651-653` |

```json
{"vectors":{"size":768,"distance":"Cosine"},"hnsw_config":{"m":0,"payload_m":16}}
```

계측 빌드 6.3절의 예시가 넣은 `optimizers_config: {indexing_threshold: 1, default_segment_number: 1}` 과 필드 이름 `sid` 는 MemMachine 요청에 없는 값이다. 그 예시는 계측 확인용이며 부하 도구의 기준이 아니다(10장).

### 3.4 payload 색인

색인마다 요청 하나를 보낸다. 컬렉션 생성 직후 순서대로 나가며, 각 요청이 독립된 `try` 로 감싸여 409 면 무시하고 다음 색인으로 진행한다(`qdrant_vector_store.py:669-678`).

| 항목 | 값 | 근거 |
|---|---|---|
| 요청 | `PUT /collections/{native}/index?wait=true` | `qdrant_vector_store.py:671-675` |
| `wait` | 어댑터가 넘기지 않고 `AsyncQdrantClient.create_payload_index` 의 기본값 `wait=True` 가 `"true"` 로 쿼리스트링에 붙는다. `ordering`, `timeout` 은 없음 | `qc:async_qdrant_client.py:1953-1959` |
| 첫 색인 본문 | `{"field_name":"sys-partition_key","field_schema":{"type":"keyword","is_tenant":true}}` | `qdrant_vector_store.py:655-663` |
| 나머지 본문 | `{"field_name":<key>,"field_schema":<타입 문자열>}` | `qdrant_vector_store.py:664-667` |
| 타입 사상 | `bool` 은 `"bool"`, `int` 는 `"integer"`, `float` 는 `"float"`, `str` 은 `"keyword"`, `datetime` 은 `"datetime"`. 사상에 없는 타입은 색인하지 않음 | `qdrant_vector_store.py:452-460, 665-667` |
| 개수 | `1 + len(config.indexed_properties_schema)` | `qdrant_vector_store.py:655-667` |

**`long_term_memory` 네임스페이스의 색인은 정확히 11개이며 순서는 아래와 같다.** 순서는 `{**EventMemory.expected_vector_store_collection_schema(), **EVENT_BACKEND_SYSTEM_FIELDS}` 의 dict 삽입 순서다(`service_locator.py:111-117`). 첫 dict 는 `_timestamp` 하나(`event_memory.py:110-127`), 둘째는 시스템 필드 9개(`long_term_memory.py:69-89`)다. 사용자 정의 필드가 스키마에 들어갈 경로는 없으므로 설정과 무관하게 항상 11개다. `user_id` 같은 사용자 payload 키는 포인트에는 저장되지만 색인되지 않는다.

| 순서 | `field_name` | `field_schema` | 파이썬 타입의 출처 |
|---|---|---|---|
| 1 | `sys-partition_key` | `{"type":"keyword","is_tenant":true}` | `qdrant_vector_store.py:657-662` |
| 2 | `_timestamp` | `"datetime"` | `event_memory.py:111, 125-127` |
| 3 | `_episode_uid` | `"keyword"` | `long_term_memory.py:69, 80` |
| 4 | `_session_key` | `"keyword"` | `long_term_memory.py:70, 81` |
| 5 | `_producer_id` | `"keyword"` | `long_term_memory.py:71, 82` |
| 6 | `_producer_role` | `"keyword"` | `long_term_memory.py:72, 83` |
| 7 | `_produced_for_id` | `"keyword"` | `long_term_memory.py:73, 84` |
| 8 | `_sequence_num` | `"integer"` | `long_term_memory.py:74, 85` |
| 9 | `_episode_type` | `"keyword"` | `long_term_memory.py:75, 86` |
| 10 | `_content_type` | `"keyword"` | `long_term_memory.py:76, 87` |
| 11 | `_created_at` | `"datetime"` | `long_term_memory.py:77, 88` |

### 3.5 `semantic_memory` 네임스페이스

시맨틱 메모리가 Qdrant 를 쓰는 것은 `semantic_memory.storage_backend` 가 `vector_store` 일 때뿐이다. 기본값은 `auto` 이며 그때는 pgvector 또는 neo4j 로 가고 Qdrant 컬렉션을 만들지 않는다(`common/configuration/__init__.py:89-96, 110-116`). 쓰는 경우 `open_or_create_collection` 으로 열며(`semantic_manager.py:150-169`), 스키마는 `str` 11개(`feature_id`, `set_id`, `set`, `semantic_category_id`, `category_name`, `category`, `tag_id`, `tag`, `feature`, `feature_name`, `value`)라 색인은 `sys-partition_key` 포함 **12개** 이고 12개 모두 `keyword` 다. 차원은 `semantic_memory.vector_dimensions` 설정값이고 없으면 기본 임베더의 `dimensions` 다(`semantic_manager.py:146-148`). 그런데 시맨틱 업서트는 payload 를 `sys-partition_key` 하나만 쓰므로(4.5절) 이 11개 색인에는 값이 한 번도 들어가지 않는다. 기존 문서와 트레이스는 이 네임스페이스를 다루지 않았다.

### 3.6 요청 순서와 횟수

에피소드 메모리는 세션을 열 때 `open_collection`(레지스트리 retrieve 1회)을 먼저 하고, 항목이 없을 때만 `create_collection` 을 부른 뒤 `open_collection` 을 한 번 더 부른다(`service_locator.py:104-131`). `create_collection` 은 (namespace, name) 잠금 안에서 레지스트리 컬렉션 PUT, 레지스트리 retrieve, 네이티브 컬렉션 PUT, 색인 PUT 11회, 레지스트리 업서트 순으로 진행한다(`qdrant_vector_store.py:704-729`).

| 상황 | 요청 순서 | 횟수 | 근거 |
|---|---|---|---|
| 새 세션, 네임스페이스에 첫 세션(트레이스 S1) | retrieve(404), PUT registry(200), retrieve(200, 빈 결과), PUT native(200), PUT index 11회(200), PUT registry points?wait=true(200), retrieve(200) | 17 | 위와 `trace:qdrant_request_trace.json` S1 |
| 새 세션, 네이티브 컬렉션은 이미 있음(트레이스 S2) | 같은 순서. PUT registry 와 PUT native 가 409, **색인 PUT 11회는 그대로 나가며 서버는 200 을 돌려줌** | 17 | `qdrant_vector_store.py:634-678`, 트레이스 S2 |
| 이미 있는 세션 다시 열기(인스턴스 캐시에 없음, S11) | retrieve 1회 | 1 | `qdrant_vector_store.py:766-784` |
| 이미 있는 세션, 인스턴스 캐시에 있음(S3) | 없음 | 0 | 트레이스 S3 |
| 시맨틱 컬렉션 처음 열기 | retrieve(404), PUT registry, PUT native, PUT index 12회, PUT registry points?wait=true | 16 | `qdrant_vector_store.py:732-764` |
| `startup`, `shutdown`, `close_collection` | 없음(no-op) | 0 | `qdrant_vector_store.py:539-545, 786-788` |

**옛 브랜치와 다른 점은 S2 다.** msr_multiuser 는 컬렉션 생성과 색인 생성이 하나의 `try` 안에 있어(`옛:common/vector_store/qdrant_vector_store.py:745-779`) 네이티브 컬렉션 PUT 이 409 를 내면 색인을 통째로 건너뛰었다. speedkick 은 `a2a1754` 에서 가드를 분리해 세션이 새로 등록될 때마다 색인 PUT 11회가 나간다. 부하 도구가 세션 생성 이벤트를 모델링한다면 세션당 `wait=true` 색인 PUT 11회가 포함되어야 한다. 잠금은 클라이언트 객체별 `asyncio.Lock` 이라 프로세스 안에서만 직렬화되고 uvicorn 워커 사이에는 잠금이 없다(`qdrant_vector_store.py:473-479, 535-537, 634-639`).

---

## 4. 저장(upsert)

### 4.1 요청과 본문

| 항목 | 값 | 근거 |
|---|---|---|
| 요청 | `PUT /collections/{native}/points?wait=true` | `qdrant_vector_store.py:316-319` |
| `wait` | 어댑터가 넘기지 않고 `AsyncQdrantClient.upsert` 의 기본값 `wait=True` 가 `"true"` 로 붙는다. `ordering`, `timeout` 은 없음 | `qc:async_qdrant_client.py:832-836`, `qc:http/api/points_api.py:530-532` |
| 본문 | `PointsList` 직렬화. `shard_key`, `update_filter`, `update_mode` 는 `None` 이라 빠짐 | `qdrant_vector_store.py:299-308` |
| 포인트 id | `record.uuid` (에피소드 경로는 derivative 의 `uuid4`) | `qdrant_vector_store.py:304`, `episodic_memory/event_memory/deriver/text_deriver.py:56-68` |
| 벡터 | `record.vector` 그대로(`list[float]`, 필수) | `qdrant_vector_store.py:305`, `data_types.py:106-126` |
| 빈 목록 | 요청을 보내지 않음 | `qdrant_vector_store.py:309-310` |

에피소드 1건이 포인트 1개일 때의 본문은 아래 모양이다. 벡터 값과 uuid 와 시각은 예시다.

```json
{"points":[{"id":"e99d628c-8286-48b3-ba2b-8d234806da3b","vector":[0.1,0.2],"payload":{"sys-partition_key":"sess_a","_timestamp":"2026-09-01T12:00:00Z","_episode_uid":"ep1","_session_key":"orga/prja","_producer_id":"user_a","_producer_role":"user","_sequence_num":0,"_episode_type":"message","_content_type":"string","_created_at":"2026-09-01T12:00:00Z","_produced_for_id":"assistant","user_id":"user_a"}}]}
```

### 4.2 payload 키 전체

| 키 | 값과 타입 | 언제 들어가나 | 근거 |
|---|---|---|---|
| `sys-partition_key` | 파티션 키(문자열) | 항상. 어댑터가 넣는다 | `qdrant_vector_store.py:257-259` |
| `_timestamp` | `derivative.timestamp` (datetime, 곧 `episode.created_at`) | 항상 | `event_memory.py:326` |
| `_episode_uid` | `episode.uid` (str) | 항상 | `long_term_memory.py:757` |
| `_session_key` | `episode.session_key` (str) | 항상 | `long_term_memory.py:758` |
| `_producer_id` | `episode.producer_id` (str) | 항상 | `long_term_memory.py:759` |
| `_producer_role` | `episode.producer_role` (str) | 항상 | `long_term_memory.py:760` |
| `_sequence_num` | `episode.sequence_num` (int) | 항상 | `long_term_memory.py:761` |
| `_episode_type` | enum 값(str) | 항상 | `long_term_memory.py:762` |
| `_content_type` | enum 값(str) | 항상 | `long_term_memory.py:763` |
| `_created_at` | `episode.created_at` (datetime) | 항상 | `long_term_memory.py:764` |
| `_produced_for_id` | `episode.produced_for_id` (str) | `None` 이 아닐 때만 | `long_term_memory.py:766-767` |
| 사용자 키(예: `user_id`) | `episode.filterable_metadata` 의 키가 맨 이름 그대로 | REST `metadata` 중 `bool`, `int`, `float`, `str`, `datetime` 값만 복사된다. `_` 로 시작하면 `ValueError` | `long_term_memory.py:768-781`, `episodic_memory/episodic_memory.py:223-228` |

값이 `None` 인 속성은 어댑터가 버리고, `datetime` 은 naive 면 UTC 를 붙여 ISO 8601(UTC 는 `"2026-09-01T12:00:00Z"` 형태)로 나간다(`qdrant_vector_store.py:260-267`, `common/utils.py:68-72`). 모든 속성 키는 `[a-z0-9_]+` 이고 32바이트 이하여야 하며 아니면 `Record` 검증에서 `ValueError` 가 나 업서트 자체가 실행되지 않는다(`data_types.py:129-140`, `common/vector_store/utils.py:27-36`). 기존 트레이스 S4 의 `payload_keys` 12개(이 표의 12개와 같고 `_segment_uuid` 없음)는 이 규칙과 일치한다.

### 4.3 배치 크기

**어댑터에는 상한이 없다.** 호출자가 넘긴 `records` 전부가 한 요청이 된다(`qdrant_vector_store.py:299-310`). 에피소드 경로는 `encode_events` 1회당 업서트 1회이며 그 호출에 들어온 모든 이벤트의 모든 derivative 를 한 요청에 담는다(`event_memory.py:280-290`). 포인트 수는 `한 add 호출의 에피소드 수 × 에피소드당 세그먼트 수 × 세그먼트당 derivative 수` 다. 기본 설정은 `PassthroughSegmenter` 와 `WholeTextDeriver` 이고(`common/configuration/episodic_config.py:231-236`, `service_locator.py:185-206`), 패스스루 세그멘터는 블록마다 세그먼트 1개(`episodic_memory/event_memory/segmenter/passthrough_segmenter.py:26-38`), 에피소드는 `TextBlock` 1개라 **기본 설정에서는 에피소드 1개당 포인트 1개** 다. `TextSegmenter` 를 쓰면 `max_chunk_length`(기본 500)로 나눈 청크 수만큼 늘어난다(`episodic_memory/event_memory/segmenter/text_segmenter.py:22`). 기존 트레이스 S4 와 S5 의 4건과 2건은 각각 에피소드 4개와 2개를 한 번에 넣은 값이다.

### 4.4 실패 시 분할 재시도

`_upsert_with_backoff` 는 `ResponseHandlingException` 과 `UnexpectedResponse` 를 잡아, 포인트가 1개 이하면 그대로 raise 하고 아니면 앞 절반과 뒤 절반을 순차 재귀 호출한다(`qdrant_vector_store.py:312-325`). 대기 시간이 없고 횟수 상한이 없으며(깊이는 log2 n) 서버 상태를 확인하지 않고 즉시 재전송한다. n 개가 끝까지 실패하면 최대 `2n-1` 요청이 나간다.

| 예외 | 언제 나는가 | 분할 재시도 |
|---|---|---|
| `ResponseHandlingException` | httpx 전송 중 발생한 모든 예외(연결 실패, 5초 `ReadTimeout` 등)와 응답 파싱 `ValidationError` | 한다 (`qc:http/api_client.py:224-228, 220-221`) |
| `UnexpectedResponse` | 상태 코드가 200, 201, 202 가 아닐 때 | 한다 (`qc:http/api_client.py:217, 222`, `qc:http/exceptions.py:13-27`) |
| `ResourceExhaustedResponse` | 429 에 `Retry-After` 헤더가 있을 때. `QdrantException` 계열이라 위 둘이 아님 | 하지 않고 그대로 전파 (`qc:http/api_client.py:206-215`, `qc:common/client_exceptions.py:5-9`) |
| `grpc.aio.AioRpcError` | `prefer_grpc=True` 일 때 | 하지 않음 |

**부하 모델에 대한 함의.** 클라이언트 read timeout 이 5초이므로 `wait=true` 저장이 5초를 넘기면 서버가 이미 적용한 쓰기를 절반씩 다시 보내게 된다. 업서트라 결과는 멱등이지만 요청 수는 늘어난다. 부하 도구가 이를 흉내 낼지는 11장의 미확인 사항이다.

### 4.5 시맨틱 메모리의 업서트

| 경로 | 요청 | 포인트 | payload | 근거 |
|---|---|---|---|---|
| `add_feature` | `PUT /collections/{semantic native}/points?wait=true` 1회 | 1개. id 는 새로 만든 `uuid4` 를 PG `vector_semantic_feature.vector_uuid` 에 먼저 저장한 값 | `sys-partition_key: "semantic_memory"` 뿐(`properties` 를 넘기지 않음) | `vector_store_semantic_storage.py:231-253` |
| `update_feature` | `embedding` 이 주어질 때만 같은 요청 1회. 값 변경이 없으면 0회 | 1개, 기존 `vector_uuid` 덮어쓰기 | 같음 | `vector_store_semantic_storage.py:297-303` |

---

## 5. 검색(query)

### 5.1 요청과 본문

| 항목 | 값 | 근거 |
|---|---|---|
| 요청 | `POST /collections/{native}/points/query/batch`, 쿼리스트링 없음(`consistency`, `timeout` 모두 `None`) | `qdrant_vector_store.py:367-370`, `qc:http/api/search_api.py:69-73` |
| 본문 | `{"searches":[<QueryRequest>, ...]}`. `query_vectors` 원소마다 `QueryRequest` 하나 | `qdrant_vector_store.py:355-365`, `qc:async_qdrant_remote.py:544-550` |
| `searches` 길이 | 두 호출자 모두 벡터 1개를 넘기므로 **1** | `event_memory.py:420-424`, `vector_store_semantic_storage.py:618-622` |
| `query` | 질의 벡터(`list[float]`) | `qdrant_vector_store.py:357` |
| `filter` | 항상 있음. 5.3절 | `qdrant_vector_store.py:342-353, 358` |
| `score_threshold` | `min_cosine_similarity` 가 `None` 이 아닐 때만 들어감 | `qdrant_vector_store.py:359` |
| `limit` | 호출자 값 그대로. 5.2절 | `qdrant_vector_store.py:360` |
| `with_vector` | **리터럴 `false`** | `qdrant_vector_store.py:361` |
| `with_payload` | **리터럴 `false`** | `qdrant_vector_store.py:362` |
| 없는 것 | `params`(`hnsw_ef`, `exact`), `offset`, `using`, `prefetch`, `shard_key` | 같은 곳 |
| 빈 `query_vectors` | 요청 없이 `[]` 반환 | `qdrant_vector_store.py:339-340` |
| 응답 처리 | `point.score` 와 `point.id` 만 읽어 `QueryMatch(cosine_similarity, record_uuid)` 로 만든다 | `qdrant_vector_store.py:372-381`, `data_types.py:147-160` |

필터가 파티션 키뿐일 때(트레이스의 방식 A)와 속성 필터가 더해질 때(방식 B)의 본문은 아래와 같다. 방식 B 예시에는 `score_threshold` 가 있을 때의 위치도 함께 보였다.

```json
{"searches":[{"query":[0.1,0.2],"filter":{"must":[{"key":"sys-partition_key","match":{"value":"sess_a"}}]},"limit":80,"with_vector":false,"with_payload":false}]}
```

```json
{"searches":[{"query":[0.1,0.2],"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"sess_a"}}]},{"must":[{"key":"_producer_id","match":{"value":"p00"}}]}]},"score_threshold":0.1,"limit":80,"with_vector":false,"with_payload":false}]}
```

### 5.2 `limit` 의 산출

| 경로 | 식 | 기본값에서의 결과 | 근거 |
|---|---|---|---|
| 에피소드(이벤트 백엔드) | `max(num_episodes_limit × 4, num_episodes_limit)`. 상수 `_EVENT_BACKEND_DEDUP_OVERFETCH = 4` | `num_episodes_limit` 은 `EpisodicMemory.query_memory` 의 `limit` 이고 `None` 이면 20 | `long_term_memory.py:107, 310-313`, `episodic_memory/episodic_memory.py:389` |
| 같은 경로, REST 로 들어올 때 | `SearchMemoriesSpec.top_k` 기본 **10** 이 `limit` 이 되므로 Qdrant `limit` 은 **40** | REST 기본 검색 | `spec.py:516-522`, `server/api_v2/service.py:100-115` |
| 같은 경로, 파이썬 직접 호출 | `limit` 을 넘기지 않으면 `None` 이 20 으로 채워져 **80**. 기존 트레이스의 80 은 이 기본값이 아니라 트레이스 스크립트가 `limit=20` 을 명시해 넘긴 값의 4배이며, 명시값이 기본값과 같아 결과가 일치할 뿐이다 | 트레이스 S6, S7, S8, S11 | `episodic_memory.py:389`(기본값 20), `trace:reproduce/trace_qdrant_requests.py:182`(`limit=20` 명시) |
| 시맨틱 | `max(10000, offset + page_size)`. 상수 `_DEFAULT_VECTOR_QUERY_LIMIT = 10_000`, `page_num` 을 넘기지 않아 `offset` 은 0 | `top_k` 가 10,000 을 넘지 않는 한 항상 **10000** | `vector_store_semantic_storage.py:55, 613-617`, `semantic_memory/semantic_memory.py:170-192` |

**기존 문서와 트레이스가 적은 80 은 어느 브랜치의 REST 기본값도 아니다.** 명세 3.4절의 `top_k: 20` 과 `over_fetch: 4` 로 80 을 만드는 것은 그 자체로는 문제가 없지만, REST 기본 검색의 `limit` 은 40 이라는 점을 함께 알고 있어야 한다. 부하 도구의 `top_k` 는 파라미터이므로 값을 바꾸면 된다.

`score_threshold` 는 어느 경로에서도 Qdrant 로 가지 않는다. 에피소드 경로는 `min_cosine_similarity` 를 넘기지 않고(`event_memory.py:420-424`) REST 의 `score_threshold` 는 응답을 받은 뒤 파이썬에서 `score >= threshold` 로만 쓰인다(`long_term_memory.py:431-440`). 시맨틱 경로는 `min_distance` 가 API 에서 연결되지 않아 항상 `None` 이다(`main/memmachine.py:1058-1064`, `semantic_memory/semantic_session_manager.py:154-161`).

### 5.3 필터 조립 규칙

**모든 검색에 파티션 필터가 들어간다.** `{"must":[{"key":"sys-partition_key","match":{"value":<name>}}]}` 이다(`qdrant_vector_store.py:64-73`). `property_filter` 가 있으면 `validate_filter` 로 모든 필드 이름이 `[a-z0-9_]{1,32}` 인지 검사한 뒤 `{"must":[<파티션 Filter>, <속성 Filter>]}` 로 한 단계 더 감싼다(`qdrant_vector_store.py:342-353`, `common/vector_store/utils.py:38-47`). 하위 Filter 는 평탄화하지 않고 중첩 객체로 남는다. 그래서 파티션 필터가 `must` 의 첫 항목에 다시 `must` 로 감싸여 들어간다(위 방식 B 본문).

에피소드 경로에서는 어댑터에 넘기기 전에 `event_memory` 가 필드 이름을 바꾼다(`event_memory.py:413-417, 337-348`). 맨 이름 `foo` 는 `_foo` 로(예: `producer_id` 는 `_producer_id`), `m.foo` 와 `metadata.foo` 는 `foo` 로(예: `m.user_id` 는 `user_id`). 맨 이름은 시스템 필드 집합에 있어야 하며 아니면 `ValueError` 다(`long_term_memory.py:95-97`). 그래서 `m.user_id` 필터는 색인 없는 `user_id` 키로 그대로 Qdrant 에 간다(트레이스 S8).

| 연산 | 값 타입 | Qdrant Filter | 직렬화 예 | 근거 |
|---|---|---|---|---|
| `=` | str, int, bool | `must:[FieldCondition.match.value]` | `{"must":[{"key":"a","match":{"value":1}}]}` | `qdrant_vector_store.py:117-129, 145-157` |
| `!=` | str, int, bool | 위와 같되 `must_not` | `{"must_not":[{"key":"a","match":{"value":1}}]}` | 같은 곳 |
| `=`, `!=` | float | `range` 에 `gte=lte=값` | `{"must":[{"key":"f","range":{"gte":1.5,"lte":1.5}}]}` | `qdrant_vector_store.py:160-168` |
| `=`, `!=` | datetime | `DatetimeRange` 에 `gte=lte=값`(naive 는 UTC 부여, ISO 문자열) | `{"must":[{"key":"d","range":{"gte":"2026-09-01T12:00:00Z","lte":"2026-09-01T12:00:00Z"}}]}` | `qdrant_vector_store.py:171-182` |
| `>`, `>=`, `<`, `<=` | 숫자 | `range` 에 `gt`, `gte`, `lt`, `lte` 한 키 | `{"must":[{"key":"n","range":{"gt":5.0}}]}`, `{"must":[{"key":"n","range":{"gte":5.0}}]}`, `{"must":[{"key":"n","range":{"lt":5.0}}]}`, `{"must":[{"key":"n","range":{"lte":5.0}}]}` | `qdrant_vector_store.py:79-84, 130-139, 196-219` |
| `>`, `>=`, `<`, `<=` | datetime | `DatetimeRange` 에 한 키 | `{"must":[{"key":"_created_at","range":{"gte":"2026-09-01T12:00:00Z"}}]}` | 같은 곳 |
| `IN` | list | `match.any` | `{"must":[{"key":"_producer_id","match":{"any":["p00","p01"]}}]}` | `qdrant_vector_store.py:185-193` |
| `IS NULL` | 없음 | `is_empty` | `{"must":[{"is_empty":{"key":"f"}}]}` | `qdrant_vector_store.py:222-228` |
| `NOT` | 하위 식 | `must_not:[하위 Filter]` | `{"must_not":[{"must":[{"key":"a","match":{"value":1}}]}]}` | `qdrant_vector_store.py:95-98` |
| `AND` | 두 식 | `must:[좌 Filter, 우 Filter]` | `{"must":[{"must":[...]},{"must":[...]}]}` | `qdrant_vector_store.py:99-102` |
| `OR` | 두 식 | `should:[좌 Filter, 우 Filter]` | `{"should":[{"must":[{"key":"a","match":{"value":1}}]},{"must":[{"key":"b","match":{"value":true}}]}]}` | `qdrant_vector_store.py:103-106` |

숫자 `range` 의 값이 정수 5 를 넘겨도 `5.0` 으로 나가는 이유는 `models.Range` 의 `gt`, `gte`, `lt`, `lte` 가 모두 `Optional[float]` 이라 pydantic 이 float 로 바꿔 직렬화하기 때문이다(`qc:http/models/models.py:2624-2632`).

명세 3.5절의 선택도 다이얼(`_producer_id` k 개의 OR)은 이 규칙으로 아래처럼 나간다. k=2 일 때의 실제 직렬화 결과다. 파서가 이항 트리를 만들므로 k 가 3 이상이면 `should` 안에 `should` 가 다시 중첩되며, 평평한 `should` 배열 하나가 아니다. 부하 도구는 이 중첩 모양을 그대로 만든다(명세 3.5절). Qdrant 가 평평한 배열과 같은 비용으로 처리하는지는 11장에 남긴다.

```json
{"searches":[{"query":[0.1,0.2],"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"sess_a"}}]},{"should":[{"must":[{"key":"_producer_id","match":{"value":"p00"}}]},{"must":[{"key":"_producer_id","match":{"value":"p01"}}]}]}]},"limit":80,"with_vector":false,"with_payload":false}]}
```

### 5.4 경로별 `with_payload` 확정값

| 경로 | `with_payload` | `with_vector` | 호출자가 바꿀 수 있나 | 근거 |
|---|---|---|---|---|
| S-1 에피소드 메모리 검색(이벤트 백엔드) | `false` | `false` | 없음 | `qdrant_vector_store.py:361-362`, `event_memory.py:420-424` |
| S-2 시맨틱 메모리 벡터 검색 | `false` | `false` | 없음 | 같은 곳, `vector_store_semantic_storage.py:618-622` |
| 레지스트리 조회(검색 아님, `retrieve`) | `true` | `false` | 코드가 명시 | `qdrant_vector_store.py:583-587` |

**두 검색 경로 모두 호출자가 값을 고를 수 없다.** `VectorStoreCollection.query` 의 인자는 `query_vectors`, `limit`, `min_cosine_similarity`, `property_filter` 넷뿐이고 독스트링이 "저장된 속성은 필터에만 쓰이고 절대 반환하지 않는다"고 못박는다(`common/vector_store/vector_store.py:63-79`). `QueryMatch` 도 `cosine_similarity` 와 `record_uuid` 두 필드뿐이라 payload 를 받을 자리가 없다(`data_types.py:147-160`). 에피소드 검색은 uuid 를 세그먼트 저장소(PG)의 `get_segment_uuids_by_derivative_uuids` 로 되돌리고(`event_memory.py:427-431`), 시맨틱 검색은 PG `vector_uuid` 컬럼으로 feature id 를 되찾는다(`vector_store_semantic_storage.py:623-640`). **명세 3.4절의 `with_payload: false` 는 잠정값이 아니라 확정값이다.** 부하 도구는 응답으로 id 와 score 만 받는다고 가정하면 된다.

### 5.5 시맨틱 검색의 모양

`SemanticMemory.search` 는 `set_id` 마다 `_set_id_search` 를 병렬로 돌리므로 검색 요청 1건당 Qdrant 질의 수는 그 세션에서 풀리는 `set_id` 개수와 같다(`semantic_memory/semantic_memory.py:212-226`). 질의마다 필터는 파티션 필터(`sys-partition_key = "semantic_memory"`) 하나뿐이고 `set_id` 와 사용자 필터는 Qdrant 응답을 받은 뒤 PG 에서 건다(`vector_store_semantic_storage.py:618-622, 641-645`). `limit` 은 5.2절대로 10,000 이다.

---

## 6. 삭제

### 6.1 레코드 삭제

| 항목 | 값 | 근거 |
|---|---|---|
| 요청 | `POST /collections/{native}/points/delete?wait=true`. `wait` 는 클라이언트 기본값 | `qdrant_vector_store.py:397-409`, `qc:async_qdrant_client.py:1091-1095` |
| 본문 | `FilterSelector`. 파티션 필터와 `has_id` 를 `must` 로 묶음 | `qdrant_vector_store.py:399-408` |
| 분할, 재시도 | 없음. 넘어온 uuid 전부가 한 요청 | 같은 곳 |
| 빈 목록 | 요청을 보내지 않음 | `qdrant_vector_store.py:393-395` |

```json
{"filter":{"must":[{"must":[{"key":"sys-partition_key","match":{"value":"sess_a"}}]},{"has_id":["e99d628c-8286-48b3-ba2b-8d234806da3b"]}]}}
```

에피소드 삭제(`forget_events`)는 Qdrant 요청 전에 PG 에서 event uuid 로 segment uuid 를, segment uuid 로 derivative uuid 를 두 번 조회한 뒤 이 요청을 1회 보내고, 그 뒤 세그먼트 저장소 삭제가 따른다(`event_memory.py:669-712`). 시맨틱의 `delete_features`, `delete_feature_set`, `delete_all` 도 PG 에서 `vector_uuid` 를 먼저 읽은 뒤 같은 모양의 요청을 호출당 최대 1회 보낸다(`vector_store_semantic_storage.py:207-215, 363-394, 585-602`).

### 6.2 논리 컬렉션 삭제(`delete_collection`, 세션 삭제)

레지스트리 retrieve 1회 뒤 두 요청을 순서대로 보낸다(`qdrant_vector_store.py:791-830`). 레지스트리 항목이 없으면 아무 요청도 보내지 않는다. 기존 트레이스 S13 의 4건(retrieve 2회는 `close_session` 과 `delete_episodic_session` 경로가 각각 연 것)과 같다.

| 순서 | 요청 | 본문 | 근거 |
|---|---|---|---|
| 1 | `POST /collections/{native}/points/delete?wait=true` (기본값) | `{"filter":{"must":[{"key":"sys-partition_key","match":{"value":"sess_a"}}]}}` | `qdrant_vector_store.py:815-820` |
| 2 | `POST /collections/{namespace}__registry/points/delete?wait=true` (829행에서 명시) | `{"points":["<uuid5>"]}` | `qdrant_vector_store.py:824-830` |

---

## 7. 그 밖의 요청

| 요청 | 언제 | 본문 | 근거 |
|---|---|---|---|
| `GET /` | 클라이언트 생성 시 데몬 스레드에서 1회(동기 httpx). **비동기 클라이언트를 훅하는 트레이스 도구에는 잡히지 않는다** | 없음 | `qc:async_qdrant_remote.py:199-208`, `qc:common/version_check.py:12-15` |
| `GET /collections` | 벡터 스토어를 처음 열 때 1회(validate) | 없음 | `database_manager.py:646-656` |
| `POST /collections/{namespace}__registry/points` (retrieve) | `open_or_create_collection`, `open_collection`, `create_collection`, `delete_collection` 이 각 1회 | `{"ids":["<uuid5>"],"with_payload":true,"with_vector":false}`. `with_vector` 는 클라이언트 기본 `False` 가 `PointRequest` 에 실려 나감 | `qdrant_vector_store.py:583-587`, `qc:async_qdrant_client.py:1034-1039` |
| `PUT /collections/{namespace}__registry/points?wait=true` (등록) | 논리 컬렉션 생성 끝에 1회. 701행에서 `wait=True` 명시 | 아래 | `qdrant_vector_store.py:686-702` |

레지스트리 포인트의 id 는 `uuid5(UUID("a3c1f6d2-4b8e-4f2a-9c7d-1e5f8a0b3d6c"), name)` 이고(`qdrant_vector_store.py:469-471, 508-511`), 본문은 아래와 같다(이름 `sess_a`, 768차원 예시).

```json
{"points":[{"id":"66cc41dd-ef5a-5678-96b0-740bf51a2d92","vector":[0.0],"payload":{"name":"sess_a","vector_dimensions":768,"indexed_properties_schema":{"_content_type":"str","_created_at":"datetime","_episode_type":"str","_episode_uid":"str","_produced_for_id":"str","_producer_id":"str","_producer_role":"str","_sequence_num":"int","_session_key":"str","_timestamp":"datetime"}}}]}
```

`prefer_grpc=True` 면 같은 메서드들이 gRPC 포트 6334 로 나가며 어댑터의 409 와 404 판정은 `AioRpcError` 의 코드로 처리되지만(`qdrant_vector_store.py:486-487, 497-498`) 업서트 분할 재시도는 동작하지 않는다(4.4절). 기본값이 `False` 라 부하 도구 범위 밖이며 gRPC 메시지 형태는 확인하지 않았다.

---

## 8. 부하 도구 기본값 표

부하 도구 명세 3.3절과 3.4절의 기본값을 이 표로 확정한다. "MemMachine 실효값" 은 speedkick 이 실제로 보내는 값이고, 부하 도구 기본값이 그것과 다를 때는 이유를 적었다.

| 파라미터 | MemMachine 실효값 | 부하 도구 기본값 | 근거(파일:줄) |
|---|---|---|---|
| `target.protocol` | REST | `rest` | `database_conf.py:247-250` |
| `target.url` | `http://localhost:6333` | `http://127.0.0.1:6333` | `database_conf.py:235-242`, `qc:async_qdrant_remote.py:168-170` |
| HTTP 버전 | HTTP/1.1 | HTTP/1.1 | `qc:async_qdrant_remote.py:118` |
| `target.timeout_ms` | 5000 (httpx 기본) | **5000 확정.** MemMachine 기본값을 따르는 것이 충실도 원칙에 맞고, 포화 시 타임아웃이 나는 것 자체가 MemMachine 이 겪는 현상이다. 다른 값을 쓰면 `run.json` 에 표시 | `httpx:_config.py:246`, `qc:async_qdrant_remote.py:105, 174-178`, 명세 3.1절 전송 방식 행 |
| 연결 재사용 | `localhost`/`127.0.0.1` 대상이면 keep-alive 0(요청마다 새 연결) | 미정(11장). 쓴 값을 `run.json` 에 기록 | `qc:async_qdrant_remote.py:108-111` |
| 요청 헤더 | `Content-Type: application/json`, `User-Agent: python-client/1.19.0 python/3.12.13` | `Content-Type` 은 같게. `User-Agent` 는 도구 이름 | `qc:http/api/search_api.py:77-79`, `qc:async_qdrant_remote.py:144-146` |
| `distance` | `Cosine` (상수) | `Cosine` | `qdrant_vector_store.py:450, 644` |
| `hnsw.m` | 0 | 0 | `qdrant_vector_store.py:647` |
| `hnsw.payload_m` | 16 (`_hnsw_m` 하드코딩) | 16 | `qdrant_vector_store.py:528, 648` |
| 컬렉션 생성의 그 밖의 필드 | 없음(서버 기본값) | 없음. `optimizers_config` 등을 넣지 않는다 | `qdrant_vector_store.py:641-650` |
| 테넌트 색인 | `sys-partition_key`, `{"type":"keyword","is_tenant":true}` | 같음 | `qdrant_vector_store.py:657-662` |
| `payload_index_count` | 11 (이름과 순서는 3.4절) | 11 | `qdrant_vector_store.py:655-667`, `service_locator.py:111-117` |
| 색인 생성 `wait` | `true` (클라이언트 기본) | `true` | `qc:async_qdrant_client.py:1959` |
| 검색 엔드포인트 | `POST .../points/query/batch`, 쿼리스트링 없음 | 같음 | `qdrant_vector_store.py:367-370` |
| `searches` 길이 | 1 | 1 | `event_memory.py:420-424` |
| `search.over_fetch` | 4 | 4 | `long_term_memory.py:107, 310-313` |
| `search.top_k` | REST 기본 10 (Qdrant `limit` 40), 파이썬 기본 20 (`limit` 80) | 20 유지. REST 기본이 아님을 명세에 적음 | `spec.py:516-522`, `episodic_memory.py:389` |
| `search.with_payload` | `false` (리터럴) | `false` **확정** | `qdrant_vector_store.py:362` |
| `search.with_vector` | `false` (리터럴) | `false` | `qdrant_vector_store.py:361` |
| `score_threshold` | 본문에 없음 | 보내지 않음 | `event_memory.py:420-424`, `qdrant_vector_store.py:359` |
| `search.filter = partition_only` | `{"must":[{"key":"sys-partition_key","match":{"value":...}}]}` | 같음 | `qdrant_vector_store.py:64-73` |
| `search.filter = partition_and_property` | `{"must":[{"must":[파티션]},<속성 Filter>]}` | 같음. 다이얼은 5.3절의 OR 모양 | `qdrant_vector_store.py:349-351` |
| 저장 엔드포인트 | `PUT .../points?wait=true` | 같음 | `qdrant_vector_store.py:316-319` |
| `write.wait` | `true` (클라이언트 기본) | `true` | `qc:async_qdrant_client.py:836`, `qc:http/api/points_api.py:531-532` |
| `write.batch_size` | 상한 없음. 기본 설정에서 add 호출의 에피소드 수 | 4 (트레이스 S4 관측값). 실제 분포는 동료 자료로 확인 | `qdrant_vector_store.py:299-310`, `event_memory.py:280-290` |
| 저장 payload 키 | 4.2절의 12개(`_produced_for_id` 는 조건부) | 같은 키 집합 | `long_term_memory.py:756-781`, `event_memory.py:326` |
| 저장 실패 처리 | 절반 분할 재귀, 대기 없음 | 미정(11장) | `qdrant_vector_store.py:312-325` |
| 삭제 엔드포인트 | `POST .../points/delete?wait=true` | 같음 | `qdrant_vector_store.py:397-409`, `qc:async_qdrant_client.py:1095` |
| 삭제 본문 | 파티션 필터 AND `has_id` | 같음 | `qdrant_vector_store.py:399-408` |

---

## 9. 트레이스로 검증하는 방법

### 9.1 도구

`trace:reproduce/trace_qdrant_requests_raw.py` 는 기존 `trace_qdrant_requests.py` 와 같은 훅(`qc:http/api_client.py:224` 의 `AsyncApiClient.send_inner`)과 같은 시나리오 P0 부터 S13 까지를 쓰되, 요청마다 `path_raw`(실제 컬렉션 이름), `request_headers`(`api-key` 와 `authorization` 은 마스킹), `request_bytes`, `request_body`(원문 JSON), `response_bytes`, `response_body`(원문 JSON)를 기존 요약 문자열 `body` 와 함께 기록한다(`trace:reproduce/trace_qdrant_requests_raw.py:117-142`). 요약 문자열을 만드는 두 함수 중 `_compact` 는 글자 하나 바꾸지 않았고 `_summarize` 는 독스트링 한 줄만 추가되었을 뿐 로직과 출력이 같으므로 `body` 열은 기존 `qdrant_request_trace.json` 과 그대로 diff 할 수 있다(같은 파일 `56-93`). 출력은 `qdrant_request_trace_raw.json` 이며 기존 파일을 덮지 않는다(같은 파일 `263`). 이 스크립트는 `py_compile` 만 통과했고 아직 실행하지 않았다.

### 9.2 실행 환경 요건

| 요건 | 값 | 근거 |
|---|---|---|
| MemMachine 소스 | speedkick `8d7b832` 작업 트리 `/Users/taejin/Projects/MemMachine/mm_speedkick` | 스크립트 docstring 1행 |
| 파이썬 환경 | `mm_speedkick/.venv` (Python 3.12.13, qdrant-client 1.19.0, httpx 0.28.1, editable 설치가 `mm_speedkick/packages/server/src` 를 가리킴) | `.venv` 확인 |
| Qdrant | REST `127.0.0.1:16333`(gRPC 16334), **비어 있어야 함**. 재현 안내는 `qdrant/qdrant:v1.17.0` 을 썼고 클라이언트 1.19.0 이 버전 경고를 낸다 | `trace:reproduce/config.yml:53-60`, `trace:reproduce/README.md:78-106`, `trace:trace_output.txt:1` |
| PostgreSQL | `127.0.0.1:15432`, `postgres`/`mmtest`, 비어 있어야 함 | `trace:reproduce/config.yml:45-52` |
| 초기화 | `bash reset_stores.sh` (Docker 필요) | `trace:reproduce/reset_stores.sh` |
| `prefer_grpc` | `false` 여야 함. 훅이 REST 만 잡는다 | `trace:reproduce/config.yml:59` |
| 실행 위치 | `trace:reproduce/` 디렉터리에서. `mm.log` 가 상대 경로로 생긴다 | `trace:reproduce/config.yml:10-11` |

```bash
cd /Users/taejin/Projects/MemMachine/repo/docs/msr/qdrant_requests/reproduce
bash reset_stores.sh
/Users/taejin/Projects/MemMachine/mm_speedkick/.venv/bin/python trace_qdrant_requests_raw.py
```

### 9.3 기대 횟수와 비교 기준

`a8322a7` 부터 `8d7b832` 사이에 요청 본문을 바꾼 커밋이 없으므로 구간별 요청 수는 기존 트레이스와 같아야 한다. P0=1, S1=17, S2=17, S3=0, S4=1, S5=1, S6 부터 S9 각 1, S10=0, S11=2, S12=1, S13=4 (`trace:reproduce/README.md:251-263`, 3.6절). 횟수가 같으면 `request_body` 를 이 문서와 대조한다.

| 검사 | 기준 | 이 문서의 절 |
|---|---|---|
| 레지스트리 컬렉션 PUT 본문 | 3.2절 JSON 과 바이트 일치 | 3.2 |
| 네이티브 컬렉션 PUT 본문 | 3.3절 JSON 에서 `size` 만 64 로 바꾼 것과 바이트 일치 | 3.3 |
| 색인 PUT 11회 | 3.4절 표의 `field_name` 과 `field_schema` 가 그 순서대로, 쿼리스트링 `wait=true` | 3.4 |
| S2 의 409 뒤 색인 PUT | 11회가 그대로 나가고 응답이 200 | 3.6 |
| 업서트 본문 | `points` 길이 4 와 2, 각 포인트의 payload 키가 4.2절의 12개(`user_id` 포함) 또는 11개(`_produced_for_id` 가 `None` 인 경우), `wait=true` | 4.1, 4.2 |
| 검색 본문 | `with_payload`, `with_vector` 가 `false`, `score_threshold` 키가 없음(S9 포함), `limit` 이 80 과 20, 필터가 5.3절 모양 | 5.1, 5.2, 5.3 |
| 삭제 본문 | S12 는 6.1절, S13 은 6.2절의 두 본문 | 6 |
| 레지스트리 retrieve 와 업서트 본문 | 7장의 두 JSON(값은 `name` 과 uuid 만 다름) | 7 |
| 컬렉션 이름 | `path_raw` 의 해시가 3.1절의 64차원 값 `d9e60b36...` 과 일치 | 3.1 |

**부하 도구 쪽 대조.** 부하기의 `driver trace` 가 남기는 원문 본문을 위 원문 트레이스와 대조하되, 벡터 값과 uuid 와 파티션 키 값과 `size` 는 값의 차이이므로 정규화한 뒤 비교하고 그 밖의 키 집합과 값과 구조는 바이트 단위로 같아야 한다. 명세 7.2절이 적었던 "요약 문자열이라 바이트 대조가 불가능하다"는 제약은 원문 트레이스가 생기면 사라진다.

**함께 기록할 것.** Qdrant 서버 버전은 트레이스에 남지 않고(`GET /` 는 훅에 잡히지 않는다) 클라이언트 경고 한 줄로만 드러나므로 실행 시 서버 이미지 태그를 별도로 적는다.

---

## 10. msr_multiuser 기준 문서와 트레이스와의 불일치

"옛 값" 은 msr_multiuser 소스가 만들었을 값 또는 기존 문서의 서술이다. 영향받는 문서 열(`emulator_spec`, `design`, `instrumented_build`, `preparation`, `dataset_options`, `metrics_collection`, `trace:reproduce/README.md`)은 2026-09-22 에 모두 갱신했다. 아래 표의 "영향받는 문서" 는 어디가 왜 바뀌었는지의 기록이다.

| # | 항목 | 옛 값 | speedkick 값 | 영향받는 문서 |
|---|---|---|---|---|
| 1 | 트레이스의 기준 커밋 | 문서 서술은 "msr_multiuser(`89bec05`) 기준" | 실제 채취 커밋은 speedkick `a8322a7`, HEAD `8d7b832` 와 요청 동일 | `emulator_spec` 3.1, 7.2, 9.2; `design` 4.4(충실도 검증이 `qdrant_request_trace.json` 을 가리킴); `trace:reproduce/README.md` 5장(재측정 시 `8d7b832` 로) |
| 2 | 검색 `with_payload` | 옛 소스대로면 `true`(`옛:qdrant_vector_store.py:341-344, 372-374`) | `false` 고정(`361-362`) | `emulator_spec` 3.1, 3.4, 7.3, 9.2 |
| 3 | 인용 줄 번호 | `qdrant_vector_store.py:373`, `:359`; `long_term_memory.py:106`, `:324`; `database_conf.py:246`; `event_memory.py:428`; `vector_store_semantic_storage.py:649-655`(654행 `return_properties=True`. 옛 문서가 적었던 `:622` 는 `get()` 호출이지 검색 경로가 아니다) | 각각 `361-362`, `349-351`; `107`, `310-313`; `247-250`; `420-424`; `618-622` | `emulator_spec` 3.1, 7.3, 9.2; `dataset_options` 2.3절(`data_types.py:32`, `qdrant_vector_store.py:664` 는 옛 줄. speedkick 은 `similarity_metric` 필드가 없고 거리는 `qdrant_vector_store.py:450`) |
| 4 | `long_term_memory` 색인 개수 | 옛 소스는 12개 더하기 사용자 스키마(`옛:event_memory.py:111-115`) | 11개 고정. 값은 기존 문서와 같음 | 값 변경 없음. `preparation` 11.3절이 고카디널리티 필드로 `_segment_uuid` 를 들었는데 speedkick 에는 그 색인이 없어 13.60GB 어림의 전제가 하나 빠짐. `design` 0.3절과 5.1절(다), `stage_isolation` 117행, `dataset_options` 2.2절의 "11개" 는 그대로 옳음 |
| 5 | 네이티브 컬렉션이 있을 때 색인 PUT | 0회 | 세션마다 11회(`wait=true`) | 기존 문서 어디에도 세션 생성 비용이 모델에 없음. 부하 도구가 세션 생성을 흉내 낸다면 `emulator_spec` 4.4절의 허용 API 목록과 5장 워크로드 모델에 추가 필요 |
| 6 | 업서트 payload `_segment_uuid` | 있음 | 없음 | `preparation` 11.3절(4번과 같은 어림) |
| 7 | 네이티브 컬렉션 이름 해시 | `similarity_metric` 포함 | 미포함. 3.1절의 이름표 | 기존 문서는 이름을 직접 쓰지 않음(`emulator_spec` 은 `collection: laion100m`, `instrumented_build` 6.3절은 `mm`). 옛 Qdrant 데이터를 speedkick 이 읽으면 다른 이름의 컬렉션으로 요청이 갈 수 있으므로 실험 환경은 빈 Qdrant 에서 시작 |
| 8 | 레지스트리 payload 키 | 4개 | 3개 | 없음(트레이스와 일치) |
| 9 | 거리 함수 출처 | 임베더 `similarity_metric` 매핑 | 상수 `COSINE` | `dataset_options` 2.3절의 인용 줄(3번) |
| 10 | 계측 빌드의 컬렉션 설정 예시 | `optimizers_config: {indexing_threshold: 1, default_segment_number: 1}`, 필드 `sid` | MemMachine 요청에 `optimizers_config` 없음, 테넌트 필드는 `sys-partition_key` | `instrumented_build` 6.3절에 "계측 확인용이며 MemMachine 요청과 다르다" 는 단서를 달았음 |
| 11 | REST 기본 검색 `limit` | 문서와 트레이스 80 | REST 기본 `top_k=10` 이라 40. 80 은 트레이스 스크립트가 명시한 `limit=20` 의 4배이며, 파이썬 직접 호출의 기본값도 20 이다(5.2절) | `emulator_spec` 3.1, 3.4(`top_k: 20` 을 쓰는 이유 명시) |
| 12 | 커스텀 샤딩 | 옛 소스에 있음(기본값에서 본문 동일) | 제거 | 없음 |
| 13 | `semantic_memory` 네임스페이스 | 기존 문서와 트레이스 미언급 | 12개 색인 컬렉션이 `storage_backend: vector_store` 일 때 생김 | `emulator_spec` 3.3절 `payload_index_count` 범위(0부터 11), `design` 4.4절 파라미터 목록. 대상 배포 설정에 따라 두 번째 컬렉션 모델링 여부 결정 |
| 14 | 클라이언트 타임아웃 | `emulator_spec` 2026-09-21 판 3.4절 `timeout_ms: 30000` | MemMachine 실효 5초 | `emulator_spec` 3.4절과 이 문서 8장을 모두 5000 으로 확정 |
| 15 | 연결 재사용 | 기존 문서 미언급 | `localhost` 대상이면 keep-alive 0 | `emulator_spec` 3.1절 전송 방식 행에 적음. 부하 도구의 연결 모델은 11장 미확인 |
| 16 | 클라이언트 생성 시 `GET /` | 트레이스에 없음 | 데몬 스레드가 1회 보냄(훅에 안 잡힘) | `emulator_spec` 10장과 이 문서 9.3절의 P0=1 (실제 요청 수는 2회이며 훅에 잡히는 1회만 센 값이다) |

---

## 11. 미확인 사항

- **원문 트레이스를 아직 뜨지 않았다.** `trace_qdrant_requests_raw.py` 는 `py_compile` 만 통과했다. 실행에는 빈 Qdrant 와 PostgreSQL 이 필요하고 `reset_stores.sh` 는 Docker 를 전제로 하는데 이 Mac 에서 Docker 또는 OrbStack 이 동작하는지 확인하지 않았다. 9.3절의 대조는 실행 뒤에 한다.
- **`trace:reproduce/README.md` 5장의 옛 절차는 `a8322a7` 체크아웃을 그대로 두었고, 그 아래에 `8d7b832` 재측정 문단을 덧붙였다.** 기존 스크립트(`trace_qdrant_requests.py`)는 건드리지 않았고, 원문 기록판은 별도 파일이다. 재측정 뒤 6장의 확인 출력이 달라지면 그때 맞춘다.
- **옛 브랜치에서 트레이스를 다시 뜨지는 않았다.** 10장의 "옛 값" 은 소스에서 유도한 것이다. 특히 옛 브랜치의 기본 거리 함수가 Cosine 인지는 임베더의 `similarity_metric` 구현을 읽지 않아 코드로 확정하지 못했다.
- **기존 색인을 다시 PUT 했을 때 Qdrant 가 200 을 돌려주고 재색인을 하지 않는다는 것은 트레이스 S2 의 관측이지 Qdrant 소스로 확인한 것이 아니다.** 계측 대상 v1.19.1 에서도 같은지, 그리고 서버가 그 요청을 무비용으로 처리하는지는 실측이 필요하다.
- **요청에서 생략된 `hnsw_config` 필드(`full_scan_threshold`, `ef_construct`, `on_disk` 등)와 `optimizers_config` 와 세그먼트 수의 실제 값은 Qdrant 서버 기본값이며 MemMachine 소스에는 없다.** 계측 빌드 6.3절이 적은 `full_scan_threshold` 기본 10000KB 는 이번에 Qdrant 소스로 다시 확인하지 않았다.
- **`semantic_memory` 네임스페이스를 부하 도구가 모델링해야 하는지는 대상 배포의 `storage_backend` 설정에 달렸다.** 소스가 아니라 배포 설정의 문제라 여기서 확정하지 못했다. 시맨틱 검색 1건이 몇 개의 `set_id` 로 풀리는지도 세션 설정에 달려 있어 코드만으로 정하지 못했고, 시맨틱 경로의 실측 트레이스는 없다.
- **`agent_mode=True` 검색에서 검색 에이전트가 `query_memory` 를 몇 번 부르는지(`main/memmachine.py:935` 의 `max_attempts=3`, `1039` 의 `agent_mode` 분기) 추적하지 않았다.** 부하 도구가 `agent_mode` 를 흉내 낸다면 별도 계측이 필요하다.
- **httpx 타임아웃 5초는 클라이언트 객체에서 읽은 실효값이며 서버를 상대로 관측한 것은 아니다.** 부하 도구가 5초를 넘는 응답을 재현할 때 MemMachine 쪽은 `ReadTimeout` 뒤 절반 분할 재전송을 한다는 점을 부하 모델에 넣을지 결정이 필요하다.
- **연결 재사용 방식을 정하지 않았다.** 계측 환경의 MemMachine 이 Qdrant 를 `localhost` 나 `127.0.0.1` 로 가리키면 keep-alive 0 이고, 다른 호스트명이면 keep-alive 20 이다. 부하 도구가 어느 쪽을 기준으로 삼을지는 계측 환경의 호스트명에 따라 정한다.
- **클라이언트 생성 시의 `GET /` 는 트레이스 도구가 잡지 못한다.** 동기 httpx 를 데몬 스레드에서 쓰기 때문이다. 부하 도구의 P0 모델에 넣을지는 사소하지만 결정이 필요하다.
- **선택도 다이얼의 OR 모양.** 명세 3.5절은 MemMachine 의 파서가 만드는 이항 중첩 `should` 모양으로 맞추었다(5.3절). Qdrant 가 평평한 `should` 배열 하나와 그 중첩 모양을 같은 비용으로 처리하는지는 확인하지 않았다.
- **네이티브 컬렉션 이름은 speedkick 코드 경로(venv 의 pydantic 직렬화)로 계산했고 서버가 실제로 만든 이름과 대조하는 실측은 하지 않았다.** 9.3절의 컬렉션 이름 검사가 이를 닫는다.
- **gRPC 경로(`prefer_grpc=True`)의 메시지 형태는 확인하지 않았다.** 기본값이 `False` 라 부하 도구 범위 밖으로 두었다.
- **`_producer_id` 의 실제 카디널리티와 색인 없는 필드(`m.<key>`)로 거르는 비중은 여전히 모른다.** 명세 9.2절의 두 항목이며 동료에게 받는 자료로 확인한다.
