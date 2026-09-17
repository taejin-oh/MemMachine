# MemMachine ↔ Qdrant 연계 구조

*2026-08-26 · 기준 `upstream/main` `2d28c1c` · event 백엔드 · 코드 확인*
경로 접두사: `packages/server/src/memmachine_server/`

---

## 1. 매핑 — 무엇이 무엇이 되는가

| MemMachine | Qdrant | 개수 |
|---|---|---|
| — | **네이티브 컬렉션** `long_term_memory__<sha256(차원+metric+스키마)>` | **스키마 조합당 1개** |
| — | registry 컬렉션 `long_term_memory__registry` (`size=1`, `m=0`, 장부용) | namespace당 1개 |
| `org_id/project_id` = `session_key` | `sys-partition_key` **payload 값** | 세션당 값 1개 (객체 생성 없음) |
| 에피소드 1건 | 포인트 1개 | |
| 시스템 필드 9종 + EventMemory 2종 | `_`접두 payload 필드 | 11개 |
| `properties_schema` 등록 키 | bare payload 필드 | 등록분 |

**핵심**: 사용자·프로젝트가 늘어도 **컬렉션은 안 늘어난다.** 파티션은 payload 값일 뿐.

---

## 2. 컬렉션 생성 — 첫 세션 시점, 설정 2개가 전부

기동 시가 아니라 **첫 org/project 적재 때** 생성 (`long_term_memory/service_locator.py` `_event_params()`).

```python
# common/vector_store/qdrant_vector_store.py:744-770
create_collection(
    vectors_config = VectorParams(size=차원, distance=metric),
    hnsw_config    = HnswConfigDiff(m=0, payload_m=16),   # ★ 전역 그래프 끔 / 값-그룹 엣지
    sharding_method= CUSTOM if is_distributed else None,
)
create_payload_index(_PAYLOAD_PARTITION_KEY,
    KeywordIndexParams(type=KEYWORD, is_tenant=True))     # ★ 테넌트 디스크 co-location

for name, type in indexed_properties_schema.items():      # ← _ 접두 필터 없음
    create_payload_index(name, PROPERTY_TYPE_TO_INDEX_TYPE[type])
```

**결과: 기본 상태에서 payload 인덱스 12개** (11 시스템 + 파티션 키).
`enable_hnsw` 는 지정하지 않음 → 전 필드 기본값(엣지 생성 활성).

| 설정 | 역할 |
|---|---|
| `m=0` | 전역 HNSW 링크 없음 |
| `payload_m=16` | **인덱스 있는 모든 필드**에 값-그룹 엣지 생성 |
| `is_tenant=True` | 그래프 아님. **디스크 인접 배치**(순차 읽기). 컬렉션당 1개 필드만 |

---

## 3. 적재 경로

```
POST /api/v2/memories
 → main/memmachine.py:700  episode_storage.add_episodes()      ★ 원문 INSERT … RETURNING
                             → uid = episodestore.id (자동증가 정수 PK) 수령 · 선행 필수
 → :720                    episodic.add_memory_episodes()
 → episodic_memory.py:221  metadata 중 스칼라만 → filterable_metadata
 → long_term_memory.py:632 _episode_to_event()
                             Event.uuid = uuid5(NS, episode.uid)  ※ 포인트 ID 아님
                             → segmenter → Segment(uuid4) → deriver → Derivative(uuid4)
                             → 포인트 ID = derivative.uuid  (event_memory.py:319-338)
                             에피소드 1 → 세그먼트 N → 포인트 M (1:1 아님)
                             시스템 → "_producer_id" 등 _ 접두
                             사용자 metadata → bare 키 (properties.update)
                             "_" 시작 사용자 키는 ValueError (사칭 방지)
 → qdrant_vector_store.py:255 _build_payload()  ← sys-partition_key 주입
 → upsert(shard_key_selector=self._shard_key)
```

포인트 payload 실제 모습:
```
{ "sys-partition_key": "<파티션>",   ← 벡터스토어가 주입 (필터에 사용)
  "_session_key":      "<같은 값>",   ← LTM이 주입 (필터에 미사용) ⚠ 중복
  "_producer_id": ..., "_created_at": ..., "user_id": ... }
```

---

## 4. 검색 경로

```
POST /api/v2/memories/search { filter: "m.user_id = 'u1'" }
 → main/memmachine.py:984   parse_filter(filter) if filter else None   ← 기본값 "" → 필터 없음
 → long_term_memory.py:575  _validate_event_backend_filter()
                              bare → 시스템 필드 목록 대조
                              m.<키> → user_property_keys 대조 (비면 통과)
 → event_memory.py:341      _to_vector_record_property()
                              "producer_id" → "_producer_id"
                              "m.user_id"   → "user_id" (bare 환원)
 → qdrant_vector_store.py:352
      Filter(must=[ sys-partition_key == <파티션>, <사용자 필터> ])   ★ 파티션은 항상 AND
 → long_term_memory.py:346  seed 세그먼트의 payload._episode_uid 수집
                             (포인트 ID는 derivative의 uuid4 — 랜덤이라 사용 불가)
 → long_term_memory.py:357  episode_storage.get_episodes(uids)  ← int 캐스팅 → WHERE id IN (…)
                             원문 테이블은 파티션 없는 전역 공유 테이블 (복원은 파티션 무관)
```

**탐색 동작**: 쿼리 플래너가 세그먼트마다 카디널리티를 추정해
`인덱스 명단 직행` / `필터드 그래프 탐색`을 선택. 걷기일 때는 **AND 전체를 만족하는 노드만 방문**하고,
이동에는 **모든 필드의 값-그룹 엣지**를 사용.

---

## 5. 확정된 구조적 사실 5가지

| # | 사실 | 근거 |
|---|---|---|
| 1 | `session_key = org_id/project_id` 뿐. 하위 세션 식별자 없음 | `sha256("org1/prj1")[:32]` = 런타임 관측 partition 값 일치 |
| 2 | 검색은 파티션에 **바인딩**. 크로스 파티션 검색 API 없음 | 컬렉션 객체가 `self._partition_key` 보유, 필터 하드코딩 |
| 3 | 파티션을 가로지르는 엣지(`_producer_role` 등)는 **생성되나 사용 불가** | 파티션 필터가 항상 AND |
| 4 | `_session_key` 인덱스·엣지는 **순수 중복** (필터는 `sys-partition_key`만 사용) | payload 구성 + 검색 필터 대조 |
| 5 | `properties_schema` 는 컬렉션 이름 해시에 포함 → **프로젝트별로 다르면 컬렉션이 갈라짐** | `_build_native_collection_name()` |

---

## 6. 개선 후보 (실측 검증 대상)

| # | 내용 | 기대 효과 |
|---|---|---|
| 1 | **`enable_hnsw=false` 선별 적용** — `_session_key`(중복), `_episode_uid`, `_content_type`(값 1종), `_segment_uuid` 등 | 불필요 엣지 제거. qdrant-client 1.17.0 지원 확인됨. 현재 미사용 |
| 2 | **파티션 바인딩 해제 경로 신설** (구성 C) | 사용자 축 횡단 검색. 데이터 변경 0, 코드 3지점 |
| 3 | `_session_key` 인덱스 제거 | 중복 해소 |
| 4 | 인덱싱 필드 선택 설정 노출 | 현재 스키마에 있으면 무조건 인덱스 |

**주의**: 저카디널리티 필드(`_producer_role`, `_episode_type`)가 엣지를 가장 많이 만든다
(값-그룹이 크므로). 고카디널리티(`_episode_uid`, `_created_at`)는 그룹이 1~2개라 엣지 ≈ 0.
[메커니즘 추론 — 실측 확인 필요]

---

## 7. 운영 필수 사항

| # | |
|---|---|
| 1 | `properties_schema` 는 **첫 프로젝트 생성 시 확정**. 이후 추가해도 색인 안 생김 |
| 2 | **모든 프로젝트에 동일 스키마** 사용 (다르면 컬렉션 분리) |
| 3 | 검색 `filter` 는 선택 사항 — 누락 시 **프로젝트 전체 반환**. 클라이언트에서 강제 필요 |
| 4 | 측정 전 `indexed_vectors_count` 확인. 0이면 미인덱싱(전수 스캔) 상태 |

```bash
curl -s localhost:6333/collections | jq '.result.collections[].name'
curl -s localhost:6333/collections/<이름> | jq '.result | {points_count, indexed_vectors_count, segments_count}'
curl -s localhost:6333/collections/<이름> | jq '.result.payload_schema'   # 인덱스 12개 확인
```
