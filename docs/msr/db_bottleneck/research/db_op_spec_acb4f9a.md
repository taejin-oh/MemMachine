# MemMachine DB 워크로드 에뮬레이터 충실도 명세 (upstream/speedkick @ acb4f9a)

## 0. 전제, 표기, 적용한 정정

**경로와 버전**
- 경로 기준은 `packages/server/src/memmachine_server/`입니다.
- 라이브러리 버전은 uv.lock 기준입니다: sqlalchemy 2.0.52, asyncpg 0.31.0, qdrant-client 1.19.0, httpx 0.28.1, uvicorn 0.52.4, prometheus-client 0.26.0.

**기본 설정 가정**
- LTM backend는 event이고 vector_store는 Qdrant(REST, `QdrantConf.host` 기본값 `localhost`)입니다. segment_store, episode_store, session_manager는 PostgreSQL(asyncpg)입니다.
- `types`를 생략하면 `[Episodic]`만 대상입니다(router.py:297, :315).
- STM은 꺼져 있습니다(episodic_config.py:405-412, :489-493).
- reranker는 없습니다. `default_long_term_memory_reranker`는 같은 `long_term_memory.reranker`를 다시 읽으므로 명시 설정이 없으면 None입니다(memmachine.py:187-191, configuration/__init__.py:512-516).
- `agent_mode=false`, `filter=""`, `top_k=10`, `expand_context=0`입니다(spec.py:557-622).
- `MEMMACHINE_WORKERS`를 설정하지 않으면 워커는 1개입니다(app.py:131-148).

**표기**
- RTT는 네트워크 왕복입니다. `BEGIN;`, `COMMIT;`, `ROLLBACK;`은 각각 simple-query 1 RTT입니다.
- prepared 문장은 커넥션 캐시 미스일 때 Parse/Describe 1 RTT가 추가됩니다.
- 모든 bind는 RENDER_CASTS로 `$n::TYPE` 형태가 됩니다.
- `PK = sha256(f"{org_id}/{project_id}".encode()).hexdigest()[:32]`입니다. session_key에 '/'가 들어가 `[a-z0-9_]+` 검증에 실패하므로 항상 해시됩니다(long_term_memory/service_locator.py:165-189, segment_store/utils.py:7-34).
- `REG = long_term_memory__registry`, `REG_ID = uuid5(UUID('a3c1f6d2-4b8e-4f2a-9c7d-1e5f8a0b3d6c'), PK)`입니다.
- `NATIVE = long_term_memory__<sha256(VectorStoreCollectionConfig.model_dump_json())>`입니다. D=1536이고 사용자 스키마가 없으면 `long_term_memory__2ce68ee6017ba19056b98b69453812e88da022d3d263347d978ad0a2aed91fcd`입니다. 이 값은 json.dumps로 재현해 계산했으므로 에뮬레이터에서 재계산해 확인해야 합니다.
- 엔진은 이름 단위로 캐시되고(database_manager.py:363-384), 같은 이름이면 풀 하나를 공유합니다. `E_ep = episode_store.database`, `E_sess = session_manager.database`, `E_seg = episodic_memory.long_term_memory.segment_store`.

**인벤토리 대비 적용한 정정**
1. add 정상 상태의 PG 왕복은 7이 아니라 8 RTT입니다.
2. P2 fallback 경로에 BEGIN이 빠져 있었습니다.
3. json/jsonb codec 등록은 SQL을 보내지 않습니다. 대신 `episode_type` enum introspection이 추가됩니다.
4. 삭제 세션 스캔은 REST 기동 때 항상 실행됩니다. `create_tables`는 memmachine.py:409에서 처음 실행됩니다.
5. 새 세션의 Qdrant 호출 수는 17+U입니다(분산 모드는 18+U).
6. payload의 시스템 키는 항상 11개입니다. `_produced_for_id=""`도 포함되고, metadata 값은 문자열만 옵니다.
7. query 벡터는 `{"nearest":[…]}`로 감싸서 전송됩니다(qdrant-client 1.19.0 async_qdrant_fastembed.py:145-146에서 직접 확인).
8. datetime 필터 값은 UTC로 변환되지 않습니다(common/utils.py:68-72).
9. STM이 꺼져 있으므로 LTM 검색을 단독으로 await합니다(episodic_memory.py:396-403).
10. `ResourceManagerImpl.build()`를 호출하는 곳이 없습니다. 따라서 SELECT 1 검증과 GET /collections 이중 호출이 없고, 엔진별 dialect initialize 쿼리가 대신 나갑니다.
11. S7(get_episodes)은 `episode_type`을 포함한 9개 컬럼을 읽습니다.
12. 읽기 세션 끝의 ROLLBACK은 풀 reset이 아니라 session close가 보냅니다.
13. `GET /` 호환성 검사는 daemon thread에서 돌기 때문에 이벤트 루프를 막지 않습니다(1.19.0 async_qdrant_remote.py:199-209).
14. event 경로의 Qdrant handle은 `open_collection`에서 만들어집니다(qdrant_vector_store.py:827-832). `DEFAULT_GRPC_TIMEOUT` 위치는 async_qdrant_remote.py:45입니다.

---

## 1. ADD 요청 타임라인 (POST /api/v2/memories, 캐시 히트, 기본 설정)

**A0 [연산]** 요청 수신부터 A1 직전까지
- uvicorn → `RequestMetricsMiddleware`(가장 바깥) → `AccessLogMiddleware` 순서로 통과합니다(app.py:97-98).
- FastAPI가 body를 읽고 `AddMemoriesSpec`/`MemoryMessage`를 검증합니다(spec.py:453-530). `timestamp` 기본값은 `datetime.now(UTC)`, `producer="user"`, `role=""`, `produced_for=""`, `metadata: dict[str,str]={}`입니다.
- `_add_messages_to`가 `EpisodeEntry` 목록을 만듭니다(service.py:59-70).
- `get_episode_storage()`는 캐시된 객체를 돌려줍니다(memmachine.py:754).
- `add_episodes`의 `@validate_call`이 타이머 바깥에서 실행됩니다(episode_sqlalchemy_store.py:191-192).
- 메트릭: 없음. http 잔차로만 볼 수 있습니다.

**A1 [DB: PG, E_ep, 트랜잭션 1개, 요청당 항상]** `SqlAlchemyEpisodeStore.add_episodes`
- 호출 경로: memmachine.py:755 → count_caching_episode_storage.py:64 → episode_sqlalchemy_store.py:193-238.
- 커넥션 checkout 후 `BEGIN;`을 보냅니다.
- [조건] 이 물리 커넥션에서 episode_type OID가 처음 등장하는 문장이면 asyncpg가 enum 타입을 introspection합니다(asyncpg connection.py:452-460, :505-545). search의 S7이 먼저 실행된 커넥션이라면 생략됩니다.
  - PG 11 이상이면 `SELECT current_setting('jit') AS cur, set_config('jit', 'off', false) AS new`를 보냅니다.
  - `$1=[episode_type oid]`로 introspection 쿼리를 보냅니다(PG 14 이상 `INTRO_LOOKUP_TYPES`, 그 미만 `_13`).
  - 이전 jit 값이 off가 아니었으면 `SELECT set_config('jit', $1, false)`를 보냅니다.
  - 이후 INSERT를 한 번 더 Parse할 수 있습니다.
- INSERT 문장:
  ```
  INSERT INTO episodestore (content, session_key, producer_id, producer_role, produced_for_id, episode_type, metadata, created_at)
  VALUES ($1::VARCHAR, $2::VARCHAR, $3::VARCHAR, $4::VARCHAR, $5::VARCHAR, $6::episode_type, $7::JSONB, $8::TIMESTAMP WITH TIME ZONE), (...), ...
  RETURNING episodestore.id, episodestore.content, episodestore.session_key, episodestore.producer_id, episodestore.producer_role, episodestore.produced_for_id, episodestore.episode_type, episodestore.metadata, episodestore.created_at
  ```
  - 메시지당 값: `content`, `session_key='{org}/{proj}'`, `producer_id`(기본 'user'), `producer_role`(기본 ''), `produced_for_id`(기본 '', NULL 아님), `episode_type='MESSAGE'`(enum NAME, Python default), `metadata`=message.metadata JSONB(기본 `{}`), `created_at`=message.timestamp를 UTC로 변환한 값.
  - ON CONFLICT는 없습니다. `id`는 serial입니다.
- `COMMIT;`
- 규모
  - N≤1000이면 multi-VALUES INSERT 1문(insertmanyvalues, 1000건 단위로 ceil(N/1000)문)입니다.
  - 일부 메시지만 `episode_type`을 지정하면 파라미터 키 집합이 달라져 INSERT가 분할됩니다.
  - SQL 텍스트가 N에 따라 달라지므로 N값마다 커넥션별 Parse가 따로 발생합니다.
  - 합계 3 RTT, 캐시 미스 시 +Parse입니다.
- 메트릭: `episode_store_sqlalchemy_latency_seconds{operation="add_episodes"}`. checkout, BEGIN, INSERT, COMMIT, `to_typed_model`을 포함합니다.
- CountCaching 래퍼는 메모리 카운트만 갱신하고 DB 작업은 없습니다.

**A2 [연산]** 인스턴스 열기
- `get_episodic_memory_manager()`는 캐시된 객체를 돌려줍니다.
- `_with_default_episodic_memory_conf`의 pydantic merge가 인자로 먼저 평가됩니다(memmachine.py:506-546, :770).
- `open_or_create_episodic_memory`가 close_lock read lock → 세션 read lock → `MemoryInstanceCache.get` 순서로 진행합니다. get은 ref_count+1, last_access=now를 설정합니다(episodic_memory_manager.py:250-254, instance_lru_cache.py:120-140).
- `add_memory_episodes` 코루틴을 만든 뒤 컨텍스트를 빠져나오며 `release_ref`로 ref를 풉니다(memmachine.py:774-775, episodic_memory_manager.py:286-289). 인코딩은 ref 해제 후 :788에서 시작합니다.
- 메트릭: 없음.

**A2m [조건부 DB: 인스턴스 캐시 미스]** A1과 A3 사이, 세션 write lock 안에서 §1-M 블록을 실행합니다.

**A3 [연산]** `asyncio.gather`(memmachine.py:788) → `add_memory_episodes`
- `filterable_metadata`를 만듭니다(episodic_memory.py:218-235).
- `LongTermMemory.add_episodes` → `_episode_to_event`로 메시지당 Event를 만듭니다: uuid5, properties dict, 예약 키 검사(long_term_memory.py:241-243, :766-825).
- 메트릭: `Ingestion_latency` − `event_memory_latency_seconds{operation="encode_events"}` (§5).

**A4 [연산]** segmentation과 derivation
- `_validate_events`를 거쳐 PassthroughSegmenter가 메시지당 1 segment(uuid4)를, WholeTextDeriver가 segment당 1 derivative(uuid4)를 만듭니다(event_memory.py:227-258).
- 메트릭: `event_memory_encode_events_phase_seconds{phase="segmentation"}` + `{phase="derivation"}`.

**A5 [외부 I/O, DB 아님]** 임베딩
- `embedder.ingest_embed(derivative_texts)`로 N개 텍스트를 한 번에 요청합니다(event_memory.py:260-270).
- embedder `batch_size`를 설정하면 ceil(N/batch_size)개 호출이 동시에 나갑니다(embedder.py:15-35).
- OpenAI embedder는 입력 2048개/75000자 단위 클러스터로 다시 나눠 동시에 호출합니다(openai_embedder.py:128-182). `max_attempts=1`입니다.
- 메트릭: `event_memory_encode_events_phase_seconds{phase="embedding"}`. API 호출 부분만은 `embedder_openai_latency_seconds{operation="ingest_embed"}`입니다.

**A6 [DB: PG, E_seg, 트랜잭션 1개, 요청당 1회]** `add_segments`(sqlalchemy_segment_store.py:333-396)
- 커넥션 checkout 후 `BEGIN;`
- `SELECT segment_store_pt.partition_key FROM segment_store_pt WHERE segment_store_pt.incarnation = $1::UUID FOR SHARE`
  - 이 row lock은 COMMIT까지 유지됩니다. 행이 없으면 `SegmentStorePartitionHandleStaleError`가 납니다.
- [연산] segment row dict를 만들고 context/block을 JSON으로 인코딩합니다.
- `INSERT INTO segment_store_sg (incarnation, uuid, event_uuid, index, "offset", timestamp, timestamp_timezone_offset, context, block, properties) VALUES ($1::UUID, $2::UUID, $3::UUID, $4::INTEGER, $5::INTEGER, $6::TIMESTAMP WITH TIME ZONE, $7::INTEGER, $8::BYTEA, $9::BYTEA, $10::JSONB)`
  - asyncpg `Connection.executemany`로 N행을 보냅니다. prepared 문장 1개, 원자적이며 RETURNING과 ON CONFLICT는 없습니다.
  - 값
    - `incarnation`: 파티션 incarnation
    - `uuid`: segment uuid4
    - `event_uuid`: `uuid5(UUID('8c2c0e0a-3a2f-4b9c-9d1f-9b6c2a3a4f7e'), str(episode.id))`
    - `index`, `offset`: 0
    - `timestamp`: created_at(UTC)
    - `timestamp_timezone_offset`: 0
    - `context`: `json.dumps({"context_type":"producer","producer":producer_id}).encode()`
    - `block`: `json.dumps({"block_type":"text","text":content}).encode()`
  - `properties` JSONB는 아래 순서입니다. user metadata가 비어 있지 않으면 키마다 `{"v":str,"t":"str"}`가 추가됩니다(long_term_memory.py:787-812).
    ```
    {"_episode_uid":{"v":"<id>","t":"str"}, "_session_key":{...}, "_producer_id":{...}, "_producer_role":{...},
     "_sequence_num":{"v":0,"t":"int"}, "_episode_type":{"v":"message","t":"str"}, "_content_type":{"v":"string","t":"str"},
     "_created_at":{"v":"<utc iso>","t":"datetime","tz":0}, "_produced_for_id":{"v":"","t":"str"}}
    ```
- `INSERT INTO segment_store_dv_ln (incarnation, uuid, segment_uuid) VALUES ($1::UUID, $2::UUID, $3::UUID)`
  - executemany로 N행을 보냅니다. `uuid`는 derivative uuid4로, Qdrant point id와 같은 값입니다. FK `(incarnation, segment_uuid)`→sg를 행마다 검사합니다.
- `COMMIT;`
- 규모: 기본 설정에서 행 수는 segment 수=derivative 수=N입니다. `segmenter.type='text'`면 청크 단위, `deriver.type='sentence_text'`면 문장 단위로 늘어납니다. 합계 5 RTT입니다.
- 메트릭: `segment_store_sqlalchemy_latency_seconds{operation="add_segments"}`. 이 값은 `event_memory_encode_events_phase_seconds{phase="segment_store"}` 안에 포함됩니다.

**A7 [연산]** Record 생성
- derivative마다 Record를 만듭니다: `_timestamp` + properties, `list(vector)` 복사(event_memory.py:280-287, :316-335).
- 메트릭: `phase="vector_store"` − `vector_store_qdrant_latency_seconds{operation="upsert"}`.

**A8 [DB: Qdrant, 요청당 1 HTTP, A6 COMMIT 이후]** 벡터 upsert
- 호출 경로: event_memory.py:289-290 → qdrant_vector_store.py:294-328.
- 요청: `PUT /collections/NATIVE/points?wait=true`
- body: `{"points":[{"id":"<derivative uuid4>","vector":[D floats],"payload":{...}}, ...]}`. N개 포인트를 한 번에 보내며 클라이언트 청킹은 없습니다.
- payload 키 순서는 고정입니다(qdrant_vector_store.py:254-270, event_memory.py:326-329, long_term_memory.py:787-798).
  - `sys-partition_key`: PK
  - `_timestamp`: ISO-8601
  - `_episode_uid`: str(id)
  - `_session_key`, `_producer_id`, `_producer_role`
  - `_sequence_num`: 0
  - `_episode_type`: "message"
  - `_content_type`: "string"
  - `_created_at`: `_timestamp`와 같은 시각
  - `_produced_for_id`: "" (항상 포함)
  - 이어서 bare user metadata 키(문자열 값)가 옵니다.
- `_segment_uuid` 키는 없습니다.
- REST 오류(`ResponseHandlingException`/`UnexpectedResponse`)가 나면 배치를 반으로 나눠 순차 재시도하고, 1개가 남으면 오류를 올립니다. sleep은 없습니다.
- `is_distributed=True`면 `"shard_key":PK`가 추가됩니다.
- 메트릭: `vector_store_qdrant_latency_seconds{operation="upsert"}`. PointStruct 생성, 직렬화, RTT를 포함합니다.

**A9 [연산]** 응답
- phase 히스토그램과 `Ingestion_latency`를 observe하고 gather가 반환됩니다.
- `AddMemoriesResponse`를 만들고 직렬화한 뒤 미들웨어를 거칩니다.
- 메트릭: 없음.

**정상 상태 합계 (add)**
- PG 8 RTT(A1 3 + A6 5)와 문장 캐시 미스 시 Parse, 트랜잭션 2개가 직렬로 실행됩니다.
- Qdrant는 HTTP 1회입니다.
- 순서는 episodestore COMMIT → 임베딩 → segment 트랜잭션 COMMIT → Qdrant upsert입니다. 저장소 간 트랜잭션은 없습니다.

### 1-M. 인스턴스 캐시 미스 블록 (add와 search 공통, 세션 write lock 안, 요청당 최대 1회)
경로: episodic_memory_manager.py:255-285 → episodic_memory/service_locator.py:19-50 → long_term_memory/service_locator.py:92-162.

- **M1 [PG, E_sess]** 세션 조회
  - `BEGIN; SELECT sessions.session_key, sessions.timestamp, sessions.configuration, sessions.param_data, sessions.description, sessions.user_metadata, sessions.status FROM sessions WHERE sessions.session_key = $1::VARCHAR; ROLLBACK;`
  - 3 RTT. LIMIT 없이 `.first()`로 읽습니다.
  - 행이 있고 status≠active면 `SessionDeletedError`입니다.
  - 메트릭: `session_store_sqlalchemy_latency_seconds{operation="get_session_info"}`. `EpisodicMemoryConf(**param_data)` 파싱이 포함됩니다.
  - 인스턴스는 저장된 param_data로 만들어집니다.
- **M2 [PG, E_sess, 조건: M1이 None]** 세션 생성
  - `BEGIN; SELECT <같은 7개 컬럼> FROM sessions WHERE sessions.session_key = $1::VARCHAR; INSERT INTO sessions (session_key, timestamp, configuration, param_data, description, user_metadata, status) VALUES ($1::VARCHAR, $2::INTEGER, $3::JSONB, $4::JSONB, $5::VARCHAR, $6::JSONB, $7::VARCHAR); COMMIT;`
  - 4 RTT. 값은 `timestamp=int(os.times()[4])`, `configuration={}`, `param_data=EpisodicMemoryConf.model_dump(mode='json')`(STM 프롬프트 포함, 수 KB), `description=''`, `user_metadata={}`, `status='active'`입니다.
  - ON CONFLICT가 없어서 PK 경합 시 IntegrityError가 나고 요청이 실패합니다.
  - 메트릭: `{operation="create_new_session_if_not_exist"}`(session_data_manager_sql_impl.py:230-274).
- **M3 [연산]** 리소스 조회(모두 캐시; `get_embedder(validate=True)`도 캐시가 있으면 검증 호출 없음, base_manager.py:103-104)와 PK 계산.
- **M4 [Qdrant]** 레지스트리 조회
  - `POST /collections/long_term_memory__registry/points`, body `{"ids":["REG_ID"],"with_payload":true,"with_vector":false}`.
  - 404이거나 payload `name`≠PK면 None으로 처리합니다.
  - 메트릭: 없음(open_collection에 tracker 없음).
- **M5 [Qdrant, 조건: M4가 None]** §3-3의 컬렉션 생성 시퀀스 C2–C7(15+U 호출)을 실행하고, C8에서 다시 retrieve합니다.
- **M6 [PG, E_seg]** 파티션 조회
  - `BEGIN; SELECT segment_store_pt.partition_key, segment_store_pt.incarnation, segment_store_pt.payload_codec_config FROM segment_store_pt WHERE segment_store_pt.partition_key = $1::VARCHAR; ROLLBACK;`
  - 3 RTT. 행이 있으면 config를 메모리에서 비교합니다(`{"type":"plaintext"}`).
  - 메트릭: `segment_store_sqlalchemy_latency_seconds{operation="open_or_create_partition"}`(M6–M7 전체 포함).
- **M7 [PG, E_seg, 조건: M6에 행 없음]** 파티션 생성
  - `BEGIN; INSERT INTO segment_store_pt (partition_key, incarnation, payload_codec_config) VALUES ($1::VARCHAR, $2::UUID, $3::JSONB); SELECT segment_store_gc.incarnation FROM segment_store_gc WHERE segment_store_gc.incarnation = $1::UUID FOR SHARE; COMMIT;`
  - 4 RTT. `incarnation=uuid4()`, `payload_codec_config={"type":"plaintext"}`입니다.
  - gc SELECT에서 행이 나오면 rollback 후 새 incarnation을 발급합니다.
  - IntegrityError면 ROLLBACK 후 새 세션으로 `BEGIN; SELECT segment_store_pt.* WHERE partition_key=$1; ROLLBACK;`을 보내고 M6부터 반복합니다. 최대 `_MAX_MINT_ATTEMPTS=10`(sqlalchemy_segment_store.py:1024-1176)입니다.
- **M8 [연산]** segmenter/deriver, `LongTermMemory`/`EventMemory`/`EpisodicMemory`를 초기화하고 `_instance_cache.add`를 호출합니다. 용량 100 초과 시 LRU를 축출하는데 close에는 DB I/O가 없습니다(instance_lru_cache.py:165-191). 메트릭: 없음.
- **합계**
  - 기존 세션: PG 6 RTT + Qdrant 1.
  - 새 세션: PG 14 RTT + Qdrant 17+U.
  - add에서는 A1 COMMIT 뒤, A3 전에 실행됩니다.

### 1-S. 조건부: `types`에 "semantic" 포함 (기본 아님)
- add 경로는 `semantic_memory.enabled`를 확인하지 않습니다(memmachine.py:777).
- semantic 리소스가 구성되어 있지 않으면 A1 COMMIT 후 :778-780에서 예외가 나고, A3–A8은 실행되지 않습니다.
- P1–P4는 A3–A8과 gather로 동시에 실행되고 메트릭은 없습니다. 메시지마다 TaskGroup으로 병렬 처리됩니다.

- **P1** set type 조회(org당 캐시 미스일 때, single-flight 아님, 메시지당 최대 2회)
  - `BEGIN; SELECT set_type.id, set_type.org_id, set_type.org_level_set, set_type.metadata_tags_sig, set_type.name, set_type.description FROM set_type WHERE set_type.org_id = $1::VARCHAR; ROLLBACK;`
  - 경로: semantic_session_manager.py:329-340, :478-479 → config_store_sqlalchemy.py:779-788.
- **P2** User Profile set type 생성(org당 1회)
  - `BEGIN; INSERT INTO set_type (org_id, org_level_set, metadata_tags_sig, name, description) VALUES ($1::VARCHAR, true, 'producer_id', 'User Profile', 'Semantic memory scoped to producer identifiers.') RETURNING set_type.id; COMMIT;`
  - `uq_org_level_tagsig` 위반 시 `ROLLBACK; BEGIN; SELECT set_type.id FROM set_type WHERE set_type.org_id = $1::VARCHAR AND set_type.org_level_set = true AND set_type.metadata_tags_sig = $2::VARCHAR; ROLLBACK;`(config_store_sqlalchemy.py:727-777).
  - 생성 후 set type 캐시가 무효화되어 P1이 다시 나갑니다.
- **P3** set_id 등록(프로세스 내 set_id당 1회)
  - `BEGIN; INSERT INTO semantic_config_setidresources_settype (set_id, set_type_id) VALUES ($1::VARCHAR, $2::INTEGER) ON CONFLICT (set_id) DO NOTHING; COMMIT;`(config_store_sqlalchemy.py:357-384).
- **P4** 메시지 × set_id 3개, 각각 독립 세션으로 동시 실행
  - `BEGIN; INSERT INTO set_ingested_history (set_id, history_id, ingested) VALUES ($1::VARCHAR, $2::VARCHAR, $3::BOOLEAN); COMMIT;`
  - checkout이 최대 3N개 동시에 발생하며 풀 5+10, 대기 30s로 제한됩니다(sqlalchemy_pgvector_semantic.py:496-505).
- **최초 사용**
  - `CREATE EXTENSION IF NOT EXISTS vector` + alembic upgrade head, config store `create_all`(×2)를 실행합니다(semantic_manager.py:217-263).
  - semantic 엔진 이름이 기존 엔진과 다르면 연결 후 `BEGIN; SELECT 1;` 검증과 ROLLBACK이 나갑니다(semantic_manager.py:95-114 → database_manager.py:391-398).

### 1-E. 순서 위험 (부분 기록)
- **A1 COMMIT 후 A3 전 예외:** episodic 비활성(memmachine.py:528-529), semantic 미구성, `_`로 시작하는 metadata 키(long_term_memory.py:799-811). episodestore 행만 남습니다.
- **A6 COMMIT 후 A8 전 예외:** metadata 키가 `[a-z0-9_]{1,32}`를 위반하면 Record 검증에서 실패합니다(vector_store/data_types.py:129-140). 이 경우 segment 행은 있고 벡터는 없습니다.

---

## 2. SEARCH 요청 타임라인 (POST /api/v2/memories/search, 캐시 히트, expand_context=0)

**Q0 [연산]** 요청 수신부터 인스턴스 열기까지
- 미들웨어와 `SearchMemoriesSpec` 검증을 거쳐 `_search_target_memories`로 들어갑니다(service.py:100-121, `score_threshold` None이면 `-inf`).
- `parse_filter`는 filter가 비어 있지 않을 때만 실행됩니다(memmachine.py:1037).
- `asyncio.create_task`(:1040) → `get_episodic_memory_manager` → conf merge → 캐시 get(:824-833) 순서입니다.
- 메트릭: 없음.

**Q0m [조건부]** 캐시 미스면 §1-M을 실행합니다. 모르는 org/project를 검색하면 세션, 컬렉션, 파티션이 생성됩니다.

**Q1 [연산]** 검색 준비
- `query_memory` 시작(episodic_memory.py:388)에서 `query_latency` 타이머가 시작됩니다.
- `_query_long_term_memory`(:396-403) → `_search_scored_event`에서 필터 필드를 검증하고 `expand = max(0, min(expand_context, top_k-1))`, `vector_search_limit = max(4*top_k, top_k)`를 계산합니다(long_term_memory.py:314-329). 기본값에서 limit은 40입니다.
- 필터 필드가 허용 목록 밖이면 ValueError → 422가 되고 DB 호출은 없습니다.

**Q2 [외부 I/O]** 질의 임베딩
- `search_embed([query])`로 벡터 1개를 받습니다(event_memory.py:404-410).
- 메트릭: `event_memory_query_phase_seconds{phase="embedding"}`. API 부분은 `embedder_openai_latency_seconds{operation="search_embed"}`입니다.

**Q3 [연산]** filter가 있을 때만 `map_filter_fields`를 실행합니다(event_memory.py:413-417).

**Q4 [DB: Qdrant, 검색당 정확히 1 HTTP]** 벡터 질의
- 경로: event_memory.py:420-424 → qdrant_vector_store.py:331-387.
- 요청: `POST /collections/NATIVE/points/query/batch`. consistency와 timeout query 파라미터는 없습니다.
- filter 없는 body:
  ```
  {"searches":[{"query":{"nearest":[D floats]},"filter":{"must":[{"key":"sys-partition_key","match":{"value":"PK"}}]},"limit":L,"with_vector":false,"with_payload":false}]}
  ```
  - L=40입니다. score_threshold, params, offset, shard_key는 보내지 않고 서버 기본값을 씁니다.
- 클라이언트가 요청을 deepcopy합니다.
- 응답에서는 `points[i].id`와 `score`만 사용합니다.
- 메트릭: `vector_store_qdrant_latency_seconds{operation="query"}`. `phase="vector_query"` 안에 포함됩니다.

**Q5 [DB: PG, E_seg, 독립 세션; 조건: 매치 1개 이상]** S2, derivative → segment 매핑
- `BEGIN;`
- `SELECT segment_store_dv_ln.uuid, segment_store_dv_ln.segment_uuid FROM segment_store_dv_ln WHERE segment_store_dv_ln.incarnation = $1::UUID AND segment_store_dv_ln.uuid IN ($3::UUID, …) AND (EXISTS (SELECT segment_store_pt.partition_key FROM segment_store_pt WHERE segment_store_pt.incarnation = $2::UUID))`
  - IN 길이는 매치된 id 수(40 이하)이고, 길이마다 SQL 텍스트가 다릅니다.
- [조건: 결과 0행] `SELECT segment_store_pt.partition_key FROM segment_store_pt WHERE segment_store_pt.incarnation = $1::UUID`(FOR SHARE 없음)
- `ROLLBACK;`
- 3 RTT(0행이면 4). 매치가 0개면 세션을 열지 않습니다(sqlalchemy_segment_store.py:768-794).
- 메트릭: `segment_store_sqlalchemy_latency_seconds{operation="get_segment_uuids_by_derivative_uuids"}`.

**Q6 [연산]** seed 중복 제거(첫 매치 점수 유지), backward/forward 창 크기 계산(event_memory.py:433-447).

**Q7 [DB: PG, E_seg, S2와 다른 새 세션; 조건: seed 1개 이상]** S3, seed segment 조회
- `BEGIN;`
- `SELECT segment_store_sg.incarnation, segment_store_sg.uuid, segment_store_sg.event_uuid, segment_store_sg.index, segment_store_sg."offset", segment_store_sg.timestamp, segment_store_sg.timestamp_timezone_offset, segment_store_sg.context, segment_store_sg.block, segment_store_sg.properties FROM segment_store_sg WHERE segment_store_sg.uuid IN (<seed uuids>::UUID…) AND segment_store_sg.incarnation = $::UUID AND (EXISTS (SELECT segment_store_pt.partition_key FROM segment_store_pt WHERE segment_store_pt.incarnation = $::UUID)) [AND <SQL 필터>]`
  - ORDER BY와 LIMIT은 없습니다.
- [조건: 결과 0행] 레지스트리 SELECT(Q5와 같은 형태)를 보내고 `{}`를 반환합니다.
- `ROLLBACK;`
- 3 RTT(0행이면 4). 행 decode(JSON loads, properties decode)는 tracker 안에서 일어납니다(sqlalchemy_segment_store.py:400-449).
- 메트릭: `{operation="get_segment_contexts"}` ⊂ `phase="segment_query"`.

**Q8 [연산]** 점수와 정렬
- reranker가 없으면 cosine 점수를 그대로 쓰고 점수 순으로 정렬합니다(event_memory.py:459-500).
- 메트릭: `phase="scoring"`. 정렬 시간은 phase 밖입니다.

**Q9 [연산]** threshold 필터, `_episode_uid` 기준 dedupe, top_k에서 중단(long_term_memory.py:348-367). uid가 0개면 Q10은 생략합니다.

**Q10 [DB: PG, E_ep, 독립 세션]** S7a, episode 조회
- `BEGIN;`
- [조건: 이 커넥션에서 episode_type이 처음 등장] A1과 같은 enum introspection(최대 3문 + 재Parse)
- `SELECT episodestore.id, episodestore.content, episodestore.session_key, episodestore.producer_id, episodestore.producer_role, episodestore.produced_for_id, episodestore.episode_type, episodestore.metadata, episodestore.created_at FROM episodestore WHERE episodestore.id IN ($1::INTEGER, …, $k::INTEGER)`
  - k는 top_k 이하입니다. ORDER BY와 session 필터는 없습니다.
- `ROLLBACK;`
- 3 RTT(episode_sqlalchemy_store.py:259-280).
- 메트릭: `episode_store_sqlalchemy_latency_seconds{operation="get_episodes"}`. event_memory phase 밖이고 `query_latency` 안입니다.

**Q11 [연산]** 응답
- 결과 순서 정리, 누락 로그, EpisodicMemory dedupe를 거쳐 `query_latency`를 observe합니다(episodic_memory.py:448-461).
- `EpisodeResponse` 생성, service의 `model_dump`, `SearchResult` 생성과 직렬화가 이어집니다.
- 메트릭: 없음.

**정상 상태 합계 (search, expand_context=0)**
- PG 9 RTT(Q5, Q7, Q10 각 3)와 문장 캐시 미스 시 Parse, 세션 3개가 직렬로 실행됩니다.
- Qdrant는 1 HTTP입니다.

**경계 조건**
- Qdrant 매치 0개: PG 0 RTT.
- S2 결과 0행: S2 세션 4 RTT만 발생합니다.
- S3 결과 0행: S2 3 RTT + S3 세션 4 RTT이고 S7은 생략합니다.
- 점수가 모두 threshold 미만: S7을 생략합니다.

### 2-X. expand_context > 0일 때 추가·변경
- `e = max(0, min(expand_context, top_k-1))`, `back = e//3`, `fwd = e - back`(long_term_memory.py:321, event_memory.py:446-447).
- Qdrant limit은 바뀌지 않습니다(4·top_k).
- Q7 세션 안에서 S3 결과가 1행 이상이면 S4–S6이 이어지고, 마지막에 `ROLLBACK;`이 나갑니다(sqlalchemy_segment_store.py:451-474, 489-621). 모두 `get_segment_contexts` tracker 안에 포함됩니다.

- **S4 [조건: back > 0, 즉 e ≥ 3, top_k ≥ 4]** backward LATERAL, 모든 seed에 대해 1문
  ```
  SELECT seeds.seed_uuid, context.uuid, context.event_uuid, context.index, context."offset", context.timestamp, context.timestamp_timezone_offset, context.context, context.block, context.properties
  FROM (SELECT segment_store_sg.uuid AS seed_uuid, segment_store_sg.timestamp AS seed_timestamp, segment_store_sg.event_uuid AS seed_event_uuid, segment_store_sg.index AS seed_index, segment_store_sg."offset" AS seed_offset
        FROM segment_store_sg WHERE segment_store_sg.incarnation = $1::UUID AND segment_store_sg.uuid IN (<S3에서 찾은 seed>) AND (EXISTS (SELECT segment_store_pt.partition_key FROM segment_store_pt WHERE segment_store_pt.incarnation = $2::UUID))) AS seeds
  JOIN LATERAL (SELECT segment_store_sg.incarnation AS incarnation, segment_store_sg.uuid AS uuid, segment_store_sg.event_uuid AS event_uuid, segment_store_sg.index AS index, segment_store_sg."offset" AS "offset", segment_store_sg.timestamp AS timestamp, segment_store_sg.timestamp_timezone_offset AS timestamp_timezone_offset, segment_store_sg.context AS context, segment_store_sg.block AS block, segment_store_sg.properties AS properties
        FROM segment_store_sg WHERE segment_store_sg.incarnation = $3::UUID AND (segment_store_sg.timestamp, segment_store_sg.event_uuid, segment_store_sg.index, segment_store_sg."offset") < (seeds.seed_timestamp, seeds.seed_event_uuid, seeds.seed_index, seeds.seed_offset) [AND <SQL 필터>]
        ORDER BY segment_store_sg.timestamp DESC, segment_store_sg.event_uuid DESC, segment_store_sg.index DESC, segment_store_sg."offset" DESC LIMIT $n) AS context ON true
  ```
  - LIMIT은 back입니다. seeds 서브쿼리에는 필터가 붙지 않습니다.
  - 의도한 인덱스는 `segment_store_sg__in_ts_ev_ix_of`이고, 결과는 seed 수 × back 이하입니다.
- **S5 [조건: fwd > 0, 즉 e ≥ 1]** forward LATERAL
  - S4와 같고 비교는 `>`, 정렬은 ASC, LIMIT은 fwd입니다.
- **S6 [항상, LATERAL 분기일 때]** `SELECT segment_store_pt.partition_key FROM segment_store_pt WHERE segment_store_pt.incarnation = $1::UUID`
- **RTT 합계**
  - e=1–2: S2 3 + S3 세션 5(BEGIN, S3, S5, S6, ROLLBACK) + S7 3 = 11 RTT
  - e≥3: 12 RTT
- **Q9/Q10 변경**
  - `_unified_scored_event_episodes`(창 통합, 연산)로 바뀝니다(long_term_memory.py:630-665).
  - S7b는 S7a와 같은 9컬럼 SQL이고, id는 창에 속한 에피소드에서 top_k 이하로 뽑습니다. 결과는 `(created_at, uid)`로 정렬합니다.

### 2-F. filter가 비어 있지 않을 때
- **Qdrant filter**
  - 형태: `{"must":[{"must":[{"key":"sys-partition_key","match":{"value":PK}}]}, C]}`.
  - 필드 이름 변환: `m.x`/`metadata.x`→`x`, bare `f`→`_f`.
  - 연산자 변환
    - `=`(str/int/bool): `{"must":[{"key":k,"match":{"value":v}}]}`
    - `!=`: 같은 형태를 must_not으로
    - float `=`: range gte=lte
    - datetime: DatetimeRange. naive면 UTC를 붙이고, aware면 원래 offset을 유지합니다.
    - `> >= < <=`: range
    - `IN`: `match.any`
    - `IS NULL`: `is_empty`
    - NOT: `must_not`, AND: `must`, OR: `should`. 트리는 이진 중첩입니다(qdrant_vector_store.py:87-228).
- **SQL 필터(S3와 LATERAL 안쪽)**
  - `CAST(((segment_store_sg.properties -> '<key>') ->> 't') AS VARCHAR) = '<type>' AND CAST(((segment_store_sg.properties -> '<key>') ->> 'v') AS <VARCHAR|INTEGER|FLOAT|BOOLEAN>) <op> $v`
  - `timestamp` 필드는 컬럼과 직접 비교합니다. datetime은 UTC isoformat 문자열과 VARCHAR로 비교합니다(sql_filter_util.py:121-216).

---

## 3. 세션당·최초 사용·백그라운드 DB 작업

### 3-1. 워커 프로세스 기동 (워커마다 1회)
경로: mcp.py:378-383, :408 → memmachine.py:395-425. 실패는 로그만 남기고 삼키며, 해당 작업은 첫 요청으로 미뤄집니다(:467-475).

- **ST1** `get_session_data_manager`(memmachine.py:409 → resource_manager.py:236-252)
  - E_sess 엔진을 만듭니다. validate=False라 SELECT 1은 없습니다.
  - `create_tables`
    - `engine.begin()` 안에서 inspector `get_table_names`/`get_columns`를 2번(pickle, status 검사) 보내고 COMMIT합니다.
    - `engine.begin()` 안에서 `create_all`(sessions, short_term_memory_data를 checkfirst로) 후 COMMIT합니다.
    - 레거시 스키마면 ALTER가 추가됩니다.
  - 엔진의 첫 커넥션에서 dialect initialize를 보냅니다: `select pg_catalog.version()`, `select current_schema()`, `show transaction isolation level`, `show standard_conforming_strings`.
- **ST2** 삭제 세션 스캔(항상 실행)
  - `BEGIN; SELECT sessions.session_key FROM sessions WHERE sessions.status = $1::VARCHAR; ROLLBACK;`($1='deleted', memmachine.py:410-414). 메트릭은 없습니다.
  - 결과 키는 `_delete_session_worker`가 백그라운드에서 삭제하며, 그 SQL은 추적하지 않았습니다.
- **ST3 [조건: `semantic_memory.enabled`]** semantic service를 만들고 `start()`로 백그라운드 ingestion task를 띄웁니다(semantic_memory.py:148-156). SQL은 추적하지 않았습니다.
- **ST4** `get_episode_storage` → E_ep 엔진
  - `engine.begin()` 안에서 SAVEPOINT; `CREATE TYPE episode_type` checkfirst; RELEASE; `create_all`(episodestore와 인덱스 5개); COMMIT(episode_sqlalchemy_store.py:164-184). 메트릭은 없습니다.
- **ST5** `get_episodic_memory_manager`: DB 작업은 없고 2초 주기 janitor task를 띄웁니다.
- **ST6** embedder를 만들고 validate는 하지 않습니다. reranker는 설정되어 있을 때만 만듭니다.
- **ST7** `get_vector_store`
  - `AsyncQdrantClient` 생성자가 `GET http://{host}:{port}/`를 daemon thread에서 보냅니다(timeout 5, 비차단).
  - `validate_qdrant_client`가 `GET /collections`를 보냅니다(database_manager.py:608-657, :859-863). `QdrantVectorStore.startup()`은 no-op입니다. 메트릭은 없습니다.
- **ST8** `get_segment_store(E_seg)` → 엔진
  - `create_all`로 segment_store_pt, sg(인덱스 2), dv_ln(FK와 인덱스), gc(인덱스)를 만듭니다. 메트릭은 `segment_store_sqlalchemy_latency_seconds{operation="startup"}`입니다.
  - purge task를 생성하고, 첫 호출은 즉시 실행됩니다(resource_manager.py:190-215).

### 3-2. 커넥션·엔진·문장 단위
- **엔진당 1회(워커별):** 첫 물리 커넥션에서 dialect initialize 4문을 보냅니다. 메트릭은 없습니다.
- **물리 커넥션 생성마다**
  - asyncpg startup/auth가 필요합니다(connect timeout 10s).
  - json/jsonb codec 등록은 SQL을 보내지 않습니다.
  - episode_type 문장(A1 INSERT…RETURNING 또는 S7)을 처음 prepare할 때 enum introspection이 최대 3문 + 재Parse 발생하며, 해당 tracker 안에 포함됩니다.
  - 커넥션은 풀 성장이나 overflow 때 생깁니다. 기본 풀(pool_size 5)이 가득 찬 상태에서 반납되는 overflow 커넥션은 즉시 close됩니다. 따라서 동시 checkout이 5를 넘는 버스트마다 커넥션 생성과 introspection이 반복됩니다.
- **문장 Parse:** (커넥션, 고유 SQL 텍스트) 조합마다 1회입니다. 커넥션당 LRU 100을 넘으면 다시 Parse합니다. 고유 텍스트가 생기는 원인은 다음과 같습니다.
  - add_episodes의 N값
  - S2 IN 길이(1–40)
  - S3 IN 길이
  - LATERAL seeds IN 길이
  - S7 IN 길이(1–top_k)

### 3-3. 새 세션 최초 사용 (org/project당 클러스터 전역 1회, add와 search 모두 트리거 가능)
- **PG:** M1(None) → M2 → (Qdrant) → M6(없음) → M7. 합계 14 RTT입니다.
- **Qdrant:** 17+U 호출(분산 모드 18+U), U=`len(properties_schema)`(기본 0).
  - **C1** retrieve REG: M4와 같고 결과는 None입니다.
  - **C2** 레지스트리 컬렉션 생성
    - `PUT /collections/long_term_memory__registry` body `{"vectors":{"size":1,"distance":"Cosine"},"hnsw_config":{"m":0},"replication_factor":R,"write_consistency_factor":R}`. R=`registry_replication_factor`, 기본 1.
    - 이미 있으면 409를 삼킵니다(qdrant_vector_store.py:569-589). 두 번째 세션부터는 항상 409입니다.
  - **C3** retrieve REG 재확인
    - 이번에 발견되면 `VectorStoreCollectionAlreadyExistsError`가 나고 요청이 실패합니다. 다중 워커 경합에서 발생합니다.
  - **C4** native 컬렉션 생성
    - `PUT /collections/NATIVE` body `{"vectors":{"size":D,"distance":"Cosine"},"hnsw_config":{"m":0,"payload_m":16}}`. 분산 모드면 `"sharding_method":"custom"`이 추가됩니다.
    - 존재 확인 없이 매번 보내고 409를 삼킵니다.
  - **C5** payload index를 순차로 11+U회 생성(qdrant_vector_store.py:681-704)
    - 요청: `PUT /collections/NATIVE/index?wait=true`
    - 필드 순서
      1. `{"field_name":"sys-partition_key","field_schema":{"type":"keyword","is_tenant":true}}`
      2. `_timestamp` datetime
      3. `_episode_uid` keyword
      4. `_session_key` keyword
      5. `_producer_id` keyword
      6. `_producer_role` keyword
      7. `_produced_for_id` keyword
      8. `_sequence_num` integer
      9. `_episode_type` keyword
      10. `_content_type` keyword
      11. `_created_at` datetime
      12. 이후 사용자 스키마(config 순서)
    - 새 세션마다 다시 보냅니다.
  - **C6 [분산 모드]** `PUT /collections/NATIVE/shards` body `{"shard_key":PK}`
  - **C7** 레지스트리 포인트 upsert
    - `PUT /collections/long_term_memory__registry/points?wait=true` body `{"points":[{"id":"REG_ID","vector":[0.0],"payload":{"name":PK,"vector_dimensions":D,"indexed_properties_schema":{<키 정렬, 'str'|'int'|'float'|'bool'|'datetime'>}}}]}`
    - shard_key는 없습니다.
  - **C8** retrieve REG. None이면 RuntimeError입니다.
  - C2–C7은 프로세스 로컬 `asyncio.Lock[(namespace, PK)]` 안에서 실행되고, 메트릭은 `vector_store_qdrant_latency_seconds{operation="create_collection"}`입니다. C1과 C8은 메트릭이 없습니다.

### 3-4. 워커 인스턴스 캐시 미스 (기존 세션)
- 비용은 PG 6 RTT(M1, M6)와 Qdrant 1(M4)입니다.
- 캐시 설정은 `instance_cache_size=100`, `max_life_time=600`s, janitor 2s 주기이고 코드에 하드코딩되어 있습니다(episodic_memory_manager.py:43-52, :103-106; resource_manager.py:260-263).

### 3-5. POST /api/v2/projects (선택: 세션 사전 생성)
- `create_new_session_if_not_exist`(M2와 같은 4 RTT) 후 `get_session_info`(M1과 같은 3 RTT, status active 필터는 Python에서)를 실행합니다(router.py:161-200, memmachine.py:560-616).
- Qdrant나 segment_store_pt 작업은 없고 인스턴스 캐시도 채우지 않습니다.
- 따라서 이후 첫 add/search에서 M1(행 있음) + C1–C8 + M6 + M7이 실행됩니다.

### 3-6. 백그라운드 (요청과 무관)
- **B1 purge 루프**(워커 × segment store 이름마다; resource_manager.py:63-91, sqlalchemy_segment_store.py:1237-1345)
  - 한가할 때: `BEGIN; SELECT segment_store_gc.incarnation FROM segment_store_gc ORDER BY segment_store_gc.enqueued_at LIMIT $1::INTEGER FOR UPDATE SKIP LOCKED; COMMIT;`($1=1). 기동 즉시 1회, 이후 60s마다 실행합니다.
  - 적체가 있을 때(1s 주기): claim한 incarnation마다 한 트랜잭션 안에서 아래를 실행합니다. 호출당 최대 10000 segment, 100 partition입니다.
    - `DELETE FROM segment_store_sg WHERE incarnation=$ AND uuid IN (SELECT uuid … LIMIT remaining)`
    - `DELETE FROM segment_store_dv_ln …` 같은 형태
    - `DELETE FROM segment_store_gc WHERE incarnation=$`
  - 메트릭: `{operation="purge_deleted_partitions"}`. 같은 엔진 풀을 요청과 공유합니다.
- **B2 인스턴스 janitor:** 2s 주기이고 DB 작업은 없습니다. 축출 시 close도 DB I/O가 없습니다.
- **B3 semantic ingestion:** `semantic_memory.enabled=True`일 때만 동작합니다(기본 False). SQL은 추적하지 않았습니다.
- **B4 세션 삭제 워커:** ST2에서 삭제된 세션이 나왔을 때만 동작합니다. 추적하지 않았습니다.

### 3-7. 사용자(세션) 수 N, 워커 수 W에 따른 빈도
- **워커 기동(ST1–ST8):** W회. N과 무관합니다.
- **엔진 초기화:** 엔진 이름 수(1–3) × W. N과 무관합니다.
- **새 세션 생성(3-3):** 클러스터 전체에서 N회입니다.
  - 레지스트리 포인트는 N개로 늘어납니다.
  - 컬렉션은 REG 1개와 (D, 스키마) 조합당 NATIVE 1개로 N과 무관합니다.
  - 그래도 C2/C4(409)와 C5(11+U) 요청은 세션마다 다시 나갑니다.
- **캐시 미스(3-4)**
  - 세션 × 워커 최초 방문으로 최대 N×W회입니다. uvicorn은 커널 accept 분배를 쓰므로 세션이 특정 워커에 고정되지 않습니다.
  - 세션의 요청 간격이 600s(+최대 2s)를 넘으면 다음 요청마다 미스입니다.
  - 워커에 도달하는 활성 세션 수 N_w가 100을 넘으면 LRU 축출이 일어납니다. 균등 무작위 접근(IRM)에서는 적중률이 100/N_w이므로 요청당 미스 확률은 1−100/N_w입니다. N이 100보다 훨씬 크면 거의 모든 요청이 PG 6 RTT + Qdrant 1을 추가로 냅니다.
  - 사용 중(ref_count>0) 노드는 축출되지 않으므로 용량은 soft limit입니다.
- **커넥션 생성과 introspection:** N보다 요청 동시성 C의 함수입니다. C가 5를 넘는 버스트에서 반복됩니다.
- **백그라운드 B1:** 1/60s × W × store 수. N과 무관합니다.
- **semantic 요청 시:** P1/P2는 org 수, P3는 (org, producer) 수에 비례하고, P4는 요청당 3N_msg 트랜잭션입니다.

---

## 4. 에뮬레이터가 재현해야 할 클라이언트 동작

### 4-1. 프로세스와 동시성
- **워커 구조**
  - `uvicorn.run("memmachine_server.server.app:app", workers=MEMMACHINE_WORKERS(기본 1))`로 실행됩니다(app.py:101-128).
  - 워커는 독립 프로세스이고, 각자 이벤트 루프 1개, SQL 엔진·풀, Qdrant 클라이언트, 인스턴스 캐시, semantic 캐시, purge task를 따로 가집니다.
- **미들웨어:** `BaseHTTPMiddleware` 2개입니다.
- **요청 안의 DB 호출은 모두 순차 await입니다.**
  - 동시성은 add의 episodic과 semantic gather, search의 episodic/semantic task, semantic P4 fan-out뿐입니다.
  - 요청 간 배칭은 없습니다.
- **락**
  - 세션 RW lock은 캐시 미스에서만 write lock을 잡습니다. 같은 세션의 동시 미스는 이 락으로 직렬화됩니다.
  - 컬렉션 생성 lock은 (namespace, PK) 단위이고 프로세스 로컬입니다.
  - 동시 add는 segment_store_pt 행에 FOR SHARE(서로 호환)를 잡습니다.
- **연산 구간 모델링:** pydantic 처리, JSON 인코딩, Record/PointStruct 생성, numpy 평균, 행 decode는 이벤트 루프를 점유합니다. 동시 부하에서 루프 큐잉을 재현하려면 이 구간은 `asyncio.sleep`이 아니라 CPU 점유로 모델링해야 합니다. 외부 임베딩 API 호출만 await 지연으로 모델링합니다.

### 4-2. PostgreSQL 클라이언트
- **엔진 생성**
  - `create_async_engine(uri, echo=False, future=True, connect_args={"command_timeout": 60.0, "timeout": 10.0})`(database_manager.py:72-96, :379).
  - `pool_size`/`max_overflow`/`pool_timeout`/`pool_recycle`/`pool_pre_ping`는 미설정이라 SQLAlchemy 기본값이 적용됩니다: AsyncAdaptedQueuePool 5/10, 대기 30s, recycle -1, pre_ping False(checkout마다 SELECT 1 없음).
  - 엔진은 설정된 DB 이름 단위로 만들어집니다. E_ep, E_sess, E_seg 이름이 다르면 같은 서버라도 풀이 따로 생깁니다.
- **트랜잭션**
  - op마다 `AsyncSession` 1개와 checkout 1회를 씁니다.
  - 첫 문장 전에 asyncpg가 `BEGIN;`을 보냅니다. 격리 수준 절이 없어 서버 기본 READ COMMITTED가 적용됩니다.
  - 읽기 전용 세션은 close할 때 `ROLLBACK;`을 보내고, 쓰기는 `COMMIT;`으로 끝납니다.
  - 풀 reset-on-return은 추가 트래픽이 없습니다.
- **문장 실행**
  - SQLAlchemy asyncpg 어댑터가 `connection.prepare()`로 명명 prepared statement를 만들고 bind/execute합니다. 커넥션당 LRU `prepared_statement_cache_size=100`입니다.
  - bind 캐스트는 RENDER_CASTS로 붙습니다. IN 목록은 POSTCOMPILE로 원소마다 bind 1개로 펼쳐집니다.
- **벌크 INSERT**
  - RETURNING이 없는 경우(sg, dv_ln)는 asyncpg `executemany`를 씁니다.
  - RETURNING이 있는 경우(episodestore)는 insertmanyvalues로 multi-VALUES 1문을 보냅니다. 페이지 크기 1000, 정렬 sentinel은 없습니다.
- **연결 시점**
  - json/jsonb codec(`schema='pg_catalog'`)은 SQL을 보내지 않습니다.
  - 커스텀 enum `episode_type`만 커넥션별 introspection이 필요합니다.
  - 엔진 첫 연결에서 dialect initialize 4문이 나갑니다.

### 4-3. Qdrant 클라이언트
- **생성:** `AsyncQdrantClient(host, port=6333, grpc_port=6334, prefer_grpc=False, https=False[, api_key])`(database_manager.py:608-618). `check_compatibility` 기본값 True로 daemon thread에서 `GET /`를 보냅니다.
- **REST 전송**
  - httpx `AsyncClient`, HTTP/1.1(http2=False).
  - 헤더: `User-Agent: python-client/1.19.0 python/<ver>`, 설정 시 `api-key`.
  - body는 pydantic JSON이고 exclude_none/exclude_unset이 적용됩니다.
- **연결 한도(async_qdrant_remote.py:105-115)**
  - host가 `localhost`/`127.0.0.1`이면 `Limits(max_connections=None, max_keepalive_connections=0)`입니다. keep-alive가 없어 요청마다 새 TCP 연결을 맺습니다.
  - 그 외 host는 httpx 기본값입니다: max_connections=100, max_keepalive_connections=20, keepalive_expiry=5s.
- **타임아웃:** 설정하지 않으므로 httpx 기본 5s입니다(async_qdrant_remote.py:171-178, http/api_client.py:161).
- **메서드별 기본값**
  - `upsert` wait=true(async_qdrant_client.py:836), `create_payload_index` wait=true(:1959).
  - `retrieve`는 with_payload=True, with_vectors=False(:1038-1039).
  - `query_batch_points`는 요청을 deepcopy하고 list query를 `NearestQuery`로 감쌉니다.
- **재시도:** upsert의 반분할 재시도(REST 예외에서만) 외에는 없습니다.
- **변형 설정**
  - `prefer_grpc=True`: 호출별 deadline 5s(`DEFAULT_GRPC_TIMEOUT`, :45), upsert 분할 없음. 호환성 검사 `GET /`는 여전히 REST로 나갑니다.
  - `is_distributed=True`: query/upsert에 `shard_key=PK`가 붙고 C6이 실행됩니다.

### 4-4. 스키마와 데이터 사전 조건 (MemMachine ORM `create_all` 사용 권장)
- **episodestore**(episode_sqlalchemy_store.py:68-125)
  - 컬럼: id serial PK, content, session_key, producer_id, producer_role, produced_for_id(nullable), episode_type ENUM `episode_type`(EpisodeType NAME), metadata JSONB, created_at timestamptz default now().
  - 인덱스: `idx_session_key`, `idx_producer_id`, `idx_producer_role`, `idx_session_key_producer_id`, `idx_session_key_producer_id_producer_role_produced_for_id`.
- **sessions**: session_key PK, timestamp int, configuration/param_data/user_metadata JSONB, description, status default 'active'. 추가로 short_term_memory_data(FK)가 있습니다(session_data_manager_sql_impl.py:67-98).
- **segment_store_pt**: partition_key varchar(255) PK, incarnation uuid UNIQUE, payload_codec_config JSONB.
- **segment_store_sg**: PK (incarnation, uuid), 인덱스 `segment_store_sg__in_ev`와 `segment_store_sg__in_ts_ev_ix_of`. pt로 가는 FK는 없습니다.
- **segment_store_dv_ln**: PK (incarnation, uuid), FK (incarnation, segment_uuid)→sg ON DELETE CASCADE, 인덱스 `segment_store_dv_ln__in_su`.
- **segment_store_gc**: incarnation PK, 인덱스 `segment_store_gc__ea`(sqlalchemy_segment_store.py:140-240).
- **Qdrant**: §3-3의 C2/C4/C5 레이아웃을 그대로 재현해야 합니다. 테넌트 분리는 payload로 하고 `m=0`, `payload_m=16`을 씁니다.
- **데이터**: 실제 임베딩(D차원)과 실제 timestamp 분포를 써야 LATERAL 경로와 HNSW 지연이 재현됩니다.

---

## 5. 모델링 지연을 Prometheus에서 얻는 방법

**공통 정의**
- 모든 이름에 접두사가 없습니다(prometheus_metrics_factory.py:126-158).
- 히스토그램은 prometheus_client 기본 버킷(0.005–10s)을 씁니다. Summary(`Ingestion_latency`, `query_latency`, 단위 ms)는 `_sum`/`_count`만 노출하고 라벨이 없습니다.
- tracker 라벨은 `{operation, status}`이며 `status="ok"`만 사용합니다.
- 워커가 여러 개면 `PROMETHEUS_MULTIPROC_DIR`로 집계됩니다(app.py:151-201).
- `r(X{…}) = sum(rate(X_sum{…}[w]))`, `c(X{…}) = sum(rate(X_count{…}[w]))`, `m(X) = r(X)/c(X)`로 씁니다.
- 자식 op가 생략되거나 여러 번 호출될 수 있으므로 잔차는 항상 `(r(부모) − Σ r(자식)) / c(부모)` 형태로 계산합니다.
- ms Summary는 r을 1000으로 나눕니다.
- http 라벨은 `path="/api/v2/memories"`, `path="/api/v2/memories/search"`입니다(router.py:1107, middleware.py:81-82).
- **보정 방식:** DB tracker 안에 섞인 연산은 메트릭으로 분리할 수 없습니다. 에뮬레이터가 같은 DB에서 같은 형태의 op를 재생해 잰 시간 T_emu를 해당 tracker 평균에서 빼서 추정합니다.

### ADD (add 전용 부하에서 측정)
- **A0+A2+A9 (HTTP, 파싱, conf merge, 캐시 조회, 응답)**
  - `[r(http_request_duration_seconds{method="POST",path="/api/v2/memories"}) − r(episode_store_sqlalchemy_latency_seconds{operation="add_episodes"}) − r(Ingestion_latency)/1000 − r(session_store_sqlalchemy_latency_seconds{operation=~"get_session_info|create_new_session_if_not_exist"}) − r(segment_store_sqlalchemy_latency_seconds{operation="open_or_create_partition"}) − r(vector_store_qdrant_latency_seconds{operation="create_collection"})] / c(http_add)`
  - 잔차에는 미스 인스턴스 구성과 C1/M4 retrieve가 섞입니다. 미스가 없는 구간(`c(get_session_info)≈0`)에서 측정합니다.
- **A3:** `[r(Ingestion_latency)/1000 − r(event_memory_latency_seconds{operation="encode_events"})] / c(Ingestion_latency)`
- **A4:** `m(event_memory_encode_events_phase_seconds{phase="segmentation"}) + m(…{phase="derivation"})`
- **A5:** `m(…{phase="embedding"})`
  - 외부 API 부분은 `r(embedder_openai_latency_seconds{operation="ingest_embed"})/c(phase embedding)`입니다.
  - OpenAI embedder에만 있고, batch_size 분할 시 동시 호출 합이 벽시계 시간보다 커지므로 phase 값을 우선합니다.
- **A6–A7 경계:** `[r(phase segment_store) − r(segment_store…{operation="add_segments"})]/c`는 약 0입니다.
- **A7:** `[r(phase vector_store) − r(vector_store_qdrant_latency_seconds{operation="upsert"})] / c(phase vector_store)`
- **tracker 내부 연산(메트릭 없음, T_emu로 보정):** A1의 `to_typed_model`, A6의 row dict·JSON 인코딩, A8의 PointStruct 생성과 N×D float JSON 직렬화.

### SEARCH (search 전용 부하에서 측정)
- **Q0+Q11:** `[r(http{path="/api/v2/memories/search"}) − r(query_latency)/1000 − (위와 같은 미스 tracker 합)] / c(http_search)`
- **Q1+Q9+후처리:** `[r(query_latency)/1000 − r(event_memory_latency_seconds{operation="query"}) − r(episode_store_sqlalchemy_latency_seconds{operation="get_episodes"})] / c(query_latency)`
- **Q2:** `m(event_memory_query_phase_seconds{phase="embedding"})`. API 부분은 `embedder_openai_latency_seconds{operation="search_embed"}`입니다.
- **Q3:** `[r(phase vector_query) − r(vector_store_qdrant_latency_seconds{operation="query"})] / c(phase vector_query)`
- **Q6:** `[r(phase segment_query) − r(segment_store…{operation="get_segment_uuids_by_derivative_uuids"}) − r(…{operation="get_segment_contexts"})] / c(phase segment_query)`
- **Q8:** `m(phase scoring) + [r(event_memory_latency_seconds{operation="query"}) − Σ_phase r(event_memory_query_phase_seconds{phase})] / c(event_memory query)`(뒤쪽 항이 정렬)
- **tracker 내부 연산(T_emu로 보정):** Qdrant query의 필터 컴파일·deepcopy·응답 파싱, `get_segment_contexts`의 행 decode, `get_episodes`의 `to_typed_model`.
- phase 히스토그램은 성공 시에만 observe되고 tracker는 오류도 기록합니다. 따라서 오류가 없는 구간에서 측정합니다.

### 현재 메트릭이 없는 지연
1. HTTP 수신부터 핸들러까지(미들웨어 2개, body read, pydantic 검증, `@validate_call`)와 응답 직렬화. http 잔차로만 볼 수 있습니다.
2. `_with_default_episodic_memory_conf` merge, 인스턴스 캐시 조회와 RW lock.
3. 캐시 미스 인스턴스 구성(M3, M8)과 untracked `open_collection` retrieve(M4, C1, C8).
4. 모든 DB tracker 안의 연산(위 목록, `get_session_info`의 `EpisodicMemoryConf` 파싱 포함).
5. 풀 checkout 대기와 이벤트 루프 지연. tracker 값 안에 섞여 분리할 수 없습니다.
6. semantic 경로 전체(P1–P4, DDL).
7. 기동 작업: ST1, ST2, ST4, ST7(`GET /`, `GET /collections`), dialect initialize, enum introspection 단독 시간. ST8 startup만 계측됩니다.
8. 지연 분포: Summary는 평균만 제공하고, 기본 버킷 최저가 5ms라 sub-ms 연산 분포는 복원할 수 없습니다.

---

## 6. 에뮬레이터 충실도 관련 미해결 질문과 위험

1. **라이브러리 버전 차이:** SQL 텍스트는 SQLAlchemy 2.0.46/2.0.49로 컴파일했고 lock은 2.0.52입니다. search 경로 Qdrant 와이어 형식은 1.17.0에서 검증했고, 1.19.0에서는 NearestQuery·timeout·limits만 다시 확인했습니다. 에뮬레이터는 2.0.52로 재컴파일해 텍스트와 bind 순서를 맞춰야 합니다. S3의 정확한 bind 번호는 아직 확보하지 못했습니다.
   - 스크립트: `.../scratchpad/compile_add_sql.py`, `compile_sql.py`, `compile_asyncpg.py`, `refute_sp/c.py`
2. **dialect initialize 문장 세트**는 2.0.49 기준이라 2.0.52에서는 확인하지 않았습니다. asyncpg introspection SQL은 PG 서버 버전(14 이상인지)과 jit 설정에 따라 달라집니다.
3. **중복 `create_payload_index`에 대한 Qdrant 응답을 확인하지 않았습니다.** 에러가 오면 두 번째 새 세션 생성이 실패하고, 200이 오면 서버 측 작업량이 달라집니다.
4. **add 경로의 ref 해제 후 인코딩(memmachine.py:767-788)**: 워커당 활성 세션이 100을 넘으면 인코딩 전에 인스턴스가 축출·close되어 `RuntimeError("Memory is closed …")`(episodic_memory.py:220-221)가 날 수 있습니다. 이 경우 episodestore 행만 남습니다. 가능성은 있어 보이지만(PLAUSIBLE) disposal 큐 처리 시점을 추적하지 않았고 재현하지 않았습니다.
5. **다중 워커 최초 사용 경합:** sessions INSERT에 ON CONFLICT가 없어 IntegrityError로 요청이 실패합니다. Qdrant C3에서도 AlreadyExists로 실패합니다. segment_store_pt만 재시도합니다. 에뮬레이터에서 세션을 사전 생성할지(§3-5), 경합 실패를 재현할지 정해야 합니다.
6. **부분 기록 시나리오(§1-E)** 때문에 저장소 간 불일치가 생기며, 이후 search 형태가 달라집니다(S2 결과 0행 경로 등).
7. **임베딩 호출 수**는 `batch_size`와 입력 길이(OpenAI 클러스터링)에 따라 달라집니다. embedder 구현마다 메트릭 존재 여부가 다르고, `embedder_openai_*`는 OpenAI embedder에만 있습니다.
8. **데이터 의존성:** Qdrant 지연은 테넌트 수, 테넌트당 포인트 수, 옵티마이저 인덱싱 상태, 실제 벡터 분포(`m=0`/`payload_m=16`)에 따라 달라집니다. PG LATERAL/IN 성능은 세션당 segment 수와 timestamp 분포에 따라 달라집니다.
9. **Qdrant host:** 운영 host가 localhost가 아니면 keep-alive 풀이 생깁니다. 에뮬레이터 host가 운영과 다르면 TCP 핸드셰이크 비용이 달라집니다.
10. **메트릭 한계:** tracker에 풀 대기와 루프 지연이 섞이고, 캐시 미스 요청을 구분하는 라벨이 없습니다. `get_episodes`와 segment tracker는 delete/list 경로와 공유됩니다. 연산 보정은 저동시성·단일 경로 부하에서 해야 합니다.
11. **datetime ISO 직렬화 형식**(pydantic의 `Z`와 `+00:00` 중 무엇인지)을 확인하지 않았습니다. 바이트 단위 동일성이 필요하면 확인해야 합니다.
12. **추적하지 않은 범위:** semantic 백그라운드 SQL(B3), semantic search SQL과 `storage_backend="vector_store"` 경로, set_id 수 산출, STM 활성 경로(`ShortTermMemory.create`의 `create_tables` + `get_short_term_memory`, `save_short_term_memory`, LLM), 삭제 워커(B4). 모두 기본 설정 밖입니다.
13. **conf merge 결과:** `_with_default_episodic_memory_conf`는 새 세션의 param_data에만 쓰입니다. 기존 세션은 저장된 param_data로 인스턴스를 만들므로, POST /projects로 다른 embedder/스키마를 지정하면 NATIVE 이름과 D가 달라집니다.