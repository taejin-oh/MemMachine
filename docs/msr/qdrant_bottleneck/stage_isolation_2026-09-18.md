# 검색·저장 내부 단계와 계측 지점

- 작성일: 2026-09-18
- 대상: Qdrant **v1.19.1** (로컬 소스 직접 확인)
- 관련: `design_2026-09-17.md` 3.2절(측정 방법), `weekly_report_draft_2026-09-18.md` 3.3절

---

## 1. 요약

- 검색·저장의 내부 단계를 **소스에서 함수 단위로 확정**하고, 계측 코드를 넣을 지점을 특정함
- **검색** — 9개 지점. 세그먼트 안이 6개(S1~S6), 세그먼트 밖이 3개(S0, S7, S8)다. 그래프 경로는 단계가 순회 중 섞여 분리 불가
- **저장** — 9개 지점(W0~W8). 전 단계가 분리 가능함
- 계측 방식은 두 가지로 갈림
  - **전후 시각차** — 호출이 요청당 1회인 구간
  - **누적 카운터** — 루프 안에서 수백만 번 도는 구간. 호출마다 재면 계측이 측정 대상을 초과함

---

## 2. 기존 타이머가 감싸는 범위

- Qdrant에 이미 있는 검색 타이머는 `dispatch.rs`에서 시작되는 스코프 가드임

```rust
// lib/segment/src/index/hnsw_index/hnsw/read_view/dispatch.rs
let _timer = ScopeDurationMeasurer::new(&self.searches_telemetry.filtered_plain);
return self.search_vectors_plain(vectors, query_filter, top, params_ref, query_context);
```

- **경계**

```
타이머 밖 (앞)   세그먼트 읽기 잠금 대기 · 샘플링 한도 계산
타이머 안        카디널리티 추정 · 필터 평가 · 거리 계산 · 후처리
타이머 밖 (뒤)   세그먼트 결과 병합 · 재검색 · 응답 직렬화
```

- 저장 타이머는 `update_worker.rs`의 `Instant::now()`이며, **WAL flush는 그보다 앞에 있어 측정에서 빠짐**

---

## 3. 검색 — 단계와 계측 지점

### 3.1 전수 비교 경로 (현재 구성의 주 경로)

| # | 단계 | 위치 | 계측 방식 |
|---|---|---|---|
| S0 | 세그먼트 읽기 잠금 대기 | `segments_searcher.rs` · `execute_batch_search`<br>`locked_segment.try_read_for(timeout)` | 전후 시각차 |
| S1 | 카디널리티 추정 | `read_view/search.rs` · `search_vectors_plain`<br>`payload_index.estimate_cardinality(filter, ..)` | 전후 시각차 |
| S2 | **필터 평가** | 같은 함수<br>`payload_index.iter_filtered_points(..).collect()` | 전후 시각차 |
| S3 | 스코어러 준비 | `read_view/search.rs` · `search_plain_batched`<br>`construct_plain_batch_searcher(..)` | 전후 시각차 |
| S4 | **거리 계산** | `point_scorer.rs` · `peek_top_iter`<br>`raw_scorer.score_points(&chunk[..], &mut scores_buffer[..])` | **누적 카운터** |
| S5 | **결과 수집·정렬** | 같은 루프<br>`top_k.push(ScoredPointOffset { .. })` | **누적 카운터** |
| S6 | 후처리 | `search_plain_batched`<br>`postprocess_plain_batch(..)` | 전후 시각차 |
| S7 | **세그먼트 결과 병합** | `segments_searcher.rs` · `process_search_result_step1` | 전후 시각차 |
| S8 | 재검색 발생 | `segments_searcher.rs` · `searches_to_rerun` 처리 블록 | 발생 횟수 + 시각차 |

- **S2와 S4가 명확히 갈림.** `search_vectors_plain`이 후보 목록을 먼저 모으고 그 목록만 채점기에 넘기는 구조이므로, 두 줄 사이에 경계가 있음

```rust
let filtered_points: Vec<PointOffsetType> = self.payload_index
    .iter_filtered_points(filter, &query_cardinality, ..)     // ← S2 끝
    .map(|it| it.collect())?;
self.search_plain_batched(vectors, filtered_points.into_iter(), top, ..)   // ← S3부터
```

- **S4·S5는 같은 루프 안에 있음.** `peek_top_iter`가 청크 단위로 수집·채점·삽입을 반복하므로 루프 바깥을 감싸면 셋이 뭉침. 각 호출 전후 시각을 **누적 변수에 더하는 방식**이어야 함

```rust
loop {
    for point_id in &mut points { if !self.filters.check_vector(point_id) { continue } .. }  // 청크 수집
    for BatchSearch { raw_scorer, top_k } in &mut self.scorer_batch {
        raw_scorer.score_points(&chunk[..chunk_size], &mut scores_buffer[..chunk_size]);      // ← S4
        for i in 0..chunk_size { top_k.push(..) }                                             // ← S5
    }
}
```

- **S8은 시간보다 발생 횟수가 중요함.** 소스 주석이 드물게 발생한다고 적고 있으나 텔레메트리에 표시가 없어(`// TODO notify telemetry of failing sampling`) 현재로서는 발생 여부 자체를 알 수 없음

### 3.2 그래프 경로 — 분리 불가

- `search_with_graph`는 순회 중 필터 확인과 거리 계산이 섞임
- ACORN 판정 과정에서 카디널리티 추정이 한 번 더 발생함
- **따라서 이 경로에서는 S1~S6을 분리할 수 없고, 경로 전체 시간만 얻음**
- 현재 구성은 세션 필터를 항상 붙이고 세션 대부분이 임계 미만이므로 **전수 비교 경로가 주 경로임.** 그래프 경로 비중은 텔레메트리 경로별 카운터로 확인함

---

## 4. 저장 — 단계와 계측 지점

| # | 단계 | 위치 | 계측 방식 |
|---|---|---|---|
| W0 | 대기열 자리 확보 | `shard_ops.rs` · `append_and_dispatch`<br>`update_sender.reserve().await` | 전후 시각차 |
| W1 | WAL 기록 | 같은 함수<br>`wal.lock_and_write(&mut operation)` | 전후 시각차 |
| W2 | **WAL 확정 (wait 시)** | `update_worker.rs` · `update_worker_internal`<br>`wal.blocking_lock().flush()` | 전후 시각차 |
| W3 | **전역 쓰기 락 대기** | `collection_updater.rs` · `update`<br>`update_operation_lock.blocking_write()` | 전후 시각차 |
| W4 | 세그먼트 홀더 락 | 같은 함수<br>`segments.acquire_updates_lock()` | 전후 시각차 |
| W5 | 대상 세그먼트 선택 | `update/points/upsert.rs` · `upsert_points_impl`<br>`apply_points_with_conditional_move` / `smallest_appendable_segment` | 전후 시각차 |
| W6 | **벡터 저장** | `segment_ops.rs` · `write_point_parts`<br>`vector_index.update_vector(internal_id, ..)` | 전후 시각차 |
| W7 | **payload 저장** | `struct_payload_index/payload_index.rs` · `overwrite_payload`<br>`payload.borrow_mut().overwrite(point_id, ..)` | 전후 시각차 |
| W8 | **색인 갱신** | 같은 함수<br>`for (field, field_index) in &mut self.field_indexes { .. add_point(..) }` | 필드별 누적 |

- **W2가 현재 완전히 사각지대임.** 기존 타이머가 그 뒤에서 시작하므로 느린 요청 기록에도 잡히지 않음. 현재 설정이 요청마다 확정을 기다리므로 **저장 지연의 상당 부분이 여기일 가능성이 있으나 확인할 수단이 없음**
- **W3은 전역 쓰기 락이라 저장 요청 전체가 여기서 줄을 섬.** 저장이 밀릴 때 락 대기인지 실제 작업인지 구분하려면 반드시 필요함
- **W7과 W8이 갈림.** `overwrite_payload`가 payload 저장 후 필드별 색인 루프를 도는 구조이므로 두 구간 사이에 경계가 있음

```rust
self.payload.borrow_mut().overwrite(point_id, payload, hw_counter)?;   // ← W7

for (field, field_index) in &mut self.field_indexes {                   // ← W8
    let field_value = payload.get_value(field);
    for index in field_index { index.add_point(point_id, &field_value, hw_counter)?; }
}
```

- **W8은 필드별로 누적하면 색인 하나당 비용이 나옴.** 현재 색인이 11개이므로 어느 필드가 비싼지까지 확인 가능함

---

## 5. 계측 방식

| 방식 | 대상 | 방법 |
|---|---|---|
| **전후 시각차** | 요청당 1회 호출되는 구간 (S0~S3, S6~S8, W0~W7) | 호출 전후 시각을 재어 차이를 기록 |
| **누적 카운터** | 루프 안에서 반복 호출되는 구간 (S4, S5, W8) | 호출마다 시각차를 누적 변수에 더하고, 요청 종료 시 총합을 기록 |

- **누적 카운터가 필요한 이유** — S4는 청크(수백 개) 단위로 수백~수만 번 반복됨. 호출마다 기록하면 계측 비용이 측정 대상을 초과함
- **계측 자체의 왜곡을 확인해야 함** — 계측 유무 빌드를 같은 부하로 돌려 전체 시간에 차이가 없음을 확인함

---

## 6. 확보되는 것과 남는 것

| | |
|---|---|
| **확보** | 전수 비교 경로의 검색 9단계, 저장 9단계, 각 단계의 요청당 소요 시간 |
| **부분 확보** | 재검색 발생 여부 (현재 지표 없음, 계측으로 신설) |
| **미확보** | 그래프 경로의 내부 단계. 경로 전체 시간만 얻음 |

---

## 7. 앞선 정리에서 정정한 사항

- 소스 확인 과정에서 기존 정리 네 곳을 바로잡음

| 이전 서술 | 정정 |
|---|---|
| 카디널리티 추정은 타이머 밖 | **전수 비교 경로에서는 타이머 안.** `search_vectors_plain` 내부에 다시 있음 |
| 느린 요청 기록의 duration에 WAL 확정이 포함됨 | **포함되지 않음.** 확정이 타이머 시작보다 앞에 있음 |
| payload 저장과 색인 갱신은 한 함수라 분리 어려움 | **분리 가능.** `overwrite_payload` 안에서 두 구간이 명확히 갈림 |
| 저장은 5단계 | **9단계.** 대기열 자리 확보, 락 대기 두 곳 등이 누락되어 있었음 |

- 아울러 **세그먼트 읽기 잠금 대기(S0)** 가 기존 정리에 없었음. 타이머 밖이고 경합 시 병목이 될 수 있어 계측 지점에 추가함

---

## 8. 실제 삽입 결과와 알려진 공백

2026-09-21에 v1.19.1 소스에 18개 지점을 실제로 삽입했다. 삽입해 보니 문서만으로는 드러나지 않던 제약이 몇 가지 나왔다. 측정 결과를 해석할 때 이 절을 함께 읽어야 한다.

### 8.1 구현 방식

계측값은 요청마다 따로 남기지 않고 **단계별 총합과 호출 횟수만 누적한다.** 병목 지점을 가리는 데에는 총합이면 충분하고, 요청별 지연 분포는 Qdrant 기본 기능으로 이미 얻기 때문이다. 요청 단위로 묶지 않으므로 호출 스택에 문맥을 실어 나를 필요가 없고, 그만큼 소스 변경이 작아진다.

반복이 많은 구간은 지역 변수에 누적한 뒤 루프를 빠져나올 때 한 번만 반영한다. 호출마다 원자적 연산을 하면 계측 비용이 측정 대상을 넘어서기 때문이다.

`stage-timing` 이라는 빌드 기능으로 켜고 끈다. 끄면 계측 호출이 빈 코드로 컴파일되므로, 계측 유무 빌드를 같은 부하로 비교해 왜곡을 확인할 수 있다. 값은 `GET /stage_timings` 로 읽고 `POST /stage_timings/reset` 으로 초기화한다.

패치는 `stage_timing_v1.19.1.patch` 로 떠 두었고, 깨끗한 v1.19.1 클론에 적용해 계측 지점 18개가 그대로 나오는 것까지 확인했다. 빌드와 실행 절차는 `instrumented_build_2026-09-21.md` 에 있다.

### 8.1.1 실제로 동작하는지 확인한 결과

서버를 띄워 저장과 검색을 보내고 값이 오르는지 확인했다. **저장은 아홉 단계가 모두 올라왔고, 검색은 S0부터 S7까지 여덟 단계가 올라왔다.** S8은 재검색이 드물게 일어나는 지점이라 0이었으며, 이는 정상이다.

확인 과정에서 주의할 점이 하나 드러났다. **포인트 몇 건짜리 새 컬렉션에서는 S1, S2, S3, S6이 0으로 남는다.** 색인이 아직 만들어지지 않아 계측 지점이 놓인 경로를 타지 않기 때문이다. 계측이 실패한 것으로 오해하기 쉬우므로, 검색 쪽 확인은 반드시 색인이 완성된 컬렉션에서 해야 한다.

표본이 작아 값 자체에 의미를 둘 수는 없으나, 두 경로 모두에서 **가장 큰 단계가 예상과 맞았다.** 저장에서는 W2(WAL 확정)가, 검색에서는 S2(필터 평가)가 가장 컸다. 특히 W2는 기존 어떤 지표에도 잡히지 않던 사각지대이므로, 이 지점을 계측 대상으로 고른 판단의 근거가 된다.

### 8.2 W5의 범위를 좁혔다

3장과 4장의 표는 W5의 위치로 `apply_points_with_conditional_move` 와 `smallest_appendable_segment` 둘을 함께 적었다. 그런데 앞의 것은 **넘겨받은 클로저 안에서 `upsert_into` 를 실행하므로 W6, W7, W8을 통째로 품는다.** 거기에 계측을 걸면 단계별 합이 전체를 넘고 W5가 언제나 최대값으로 나와, 병목 지점 판정이 무너진다.

그래서 **W5는 `smallest_appendable_segment` 만 재도록 좁혔다.** 기존 포인트를 갱신하는 경로의 전체 시간은 따로 재지 않으며, 그 구간의 내역은 W6, W7, W8로 드러난다.

### 8.3 비동기 구간을 걸치는 계측이 셋 있다

세 지점은 `await` 를 사이에 두고 측정되므로, 측정값에 실제 작업 시간뿐 아니라 **실행기의 대기 시간이 함께 들어간다.**

| 지점 | 판단 |
|---|---|
| W0 대기열 자리 확보 | **의도한 대로다.** 대기열이 밀리는 시간을 재는 것이 목적이므로 대기 시간이 포함되어야 맞다 |
| W1 WAL 기록 | 표에는 전후 시각차로 적었으나 실제 호출이 비동기다. 실행기 대기 시간이 섞이므로 **W1 단독으로 디스크 쓰기 비용이라고 읽으면 안 된다** |
| S8 재검색 | 시간에는 대기가 섞이지만 **발생 횟수는 정확하다.** S8은 원래 횟수가 중요한 지점이므로 목적에는 지장이 없다 |

### 8.4 계측되지 않은 경로

아래 경로를 타는 요청은 해당 단계의 시간이 비어 있다. 현재 구성의 주 경로가 아니라고 판단해 넣지 않았으나, 측정 중 호출 횟수가 0이 아닌 단계와 0인 단계를 대조할 때 이 목록을 참고해야 한다.

| 계측 안 된 곳 | 빠지는 단계 |
|---|---|
| `search_plain_unfiltered_batched` (필터 없는 전수 비교) | S3, S6 |
| `peek_top_visible` 가 쓰는 `score_chunk` | S4, S5 |
| `update_vector_raw` (덧붙이기 전용 저장 경로) | W6 |
| 그래프 경로 전체 | S1부터 S6까지. 3.2절에 적은 구조적 한계로 애초에 분리 불가 |

### 8.5 범위를 넓힌 것

W8은 표에 적힌 `add_point` 뿐 아니라 **값이 빈 필드를 처리하는 `remove_point` 까지 포함한다.** 둘 다 같은 색인 갱신 작업이므로, `add_point` 만 재면 색인 갱신 비용을 실제보다 적게 잡는다.

### 8.6 읽을 때의 묶음 — 검색 4묶음과 저장 4묶음

새 단계 구조의 **4.1 단계 묶음 정의**다. 코드의 계측 지점 18개는 3장과 4장의 표 그대로 두고, 결과를 읽고 보고할 때는 아래 여덟 묶음으로 본다. 18개 상세는 묶음에서 이상이 보일 때 파고드는 용도다. 묶음별 합산을 찍는 스크립트는 `instrumented_build_2026-09-21.md` 8.1절에 있으며, 정의는 두 문서가 같다.

| 경로 | 묶음 | 포함 지점 | 읽을 때 주의 |
|---|---|---|---|
| 검색 | 잠금 대기 | S0 | 세그먼트 읽기 잠금 대기다. 타이머 밖에 있어 기존 지표에는 없던 값이다 |
| 검색 | 후보 고르기 | S1 + S2 | 카디널리티 추정과 필터 평가다 |
| 검색 | 거리 계산 | S3 + S4 + S5 + S6 | 스코어러 준비, 거리 계산, 결과 수집, 후처리다. S4와 S5는 누적 카운터 값이다 |
| 검색 | 결과 합치기 | S7 | 세그먼트 결과 병합이다. S8 재검색은 시간이 아니라 **횟수**로 따로 본다. 8.3절대로 시간에는 대기가 섞인다 |
| 저장 | 대기열 | W0 | 대기열 자리 확보다. 8.3절대로 대기 시간이 포함되는 것이 의도다 |
| 저장 | WAL 기록과 확정 | W1 + W2 | 8.3절대로 W1에 실행기 대기가 섞이므로 이 묶음을 디스크 쓰기 비용으로 읽지 않는다 |
| 저장 | 락 대기 | W3 + W4 | 전역 쓰기 락과 세그먼트 홀더 락이다 |
| 저장 | 세그먼트 쓰기 | W5 + W6 + W7 + W8 | 세그먼트 선택(8.2절대로 `smallest_appendable_segment` 만), 벡터 저장, payload 저장, 색인 갱신이다. **색인 갱신 W8은 따로 볼 수 있게 별도로 찍는다** |

묶음을 코드가 아니라 읽는 쪽에서 하는 이유는 하나다. 코드에서 묶으면 묶음 안의 어느 지점이 문제인지 다시 나눌 길이 없고, 나누려면 패치와 이미지와 왜곡 검증을 모두 되풀이해야 한다. 그래서 18개 지점은 그대로 두고 보고할 때만 묶는다. 8.4절의 계측되지 않은 경로에 해당하는 요청은 그 묶음의 값이 실제보다 작게 나오므로, 묶음 값을 읽을 때도 그 표를 함께 본다.
