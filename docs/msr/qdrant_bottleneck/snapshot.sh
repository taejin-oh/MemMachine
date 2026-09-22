#!/usr/bin/env bash
# Qdrant 병목 측정 2단계 — 구간 경계 스냅샷.
#
# 한 구간이 끝나는 자리에서 모든 누적 창구를 한 번에 찍는다. 무거운 창구
# (/metrics, /telemetry?details_level=4, /collections/{c}/memory)를 여기서만 읽고,
# 시계열 수집기는 읽지 않는다. 부하를 잠시 멈춘 상태에서 호출하는 것을 전제로 한다.
#
# 사용:
#   SNAP_RESET=1 ./snapshot.sh <출력_디렉터리> <스냅샷_이름>
#
# 환경 변수:
#   QURL        Qdrant 주소            기본 http://127.0.0.1:6333
#   COLL        컬렉션 이름            필수
#   CG          컨테이너 cgroup 경로   필수
#   SNAP_RESET  1이면 stage_timings 를 읽은 직후 초기화한다. 기본 0
#
# 이 스크립트는 파일을 쓰기만 하고 지우지 않는다.

set -u

QURL="${QURL:-http://127.0.0.1:6333}"
OUT="${1:-}"
NAME="${2:-}"
SNAP_RESET="${SNAP_RESET:-0}"

if [ -z "$OUT" ] || [ -z "$NAME" ]; then
  echo "사용법: SNAP_RESET=0|1 $0 <출력_디렉터리> <스냅샷_이름>" >&2
  exit 2
fi
if [ -z "${COLL:-}" ]; then
  echo "COLL 이 비어 있다. 컬렉션 이름을 export 한 뒤 다시 실행한다." >&2
  exit 2
fi
if [ -z "${CG:-}" ] || [ ! -d "$CG" ]; then
  echo "CG 가 비어 있거나 그런 디렉터리가 없다: '${CG:-}'" >&2
  exit 2
fi

D="$OUT/$NAME"
mkdir -p "$D/cgroup" "$D/host"

T0=$(date +%s.%N)

# 1. cgroup 계수기. 가장 싸므로 시점을 가장 정확히 고정할 수 있다.
for f in memory.current memory.max memory.peak memory.swap.current \
         memory.events memory.stat memory.numa_stat \
         cpu.stat io.stat pids.current cpuset.cpus.effective cpuset.mems.effective \
         memory.pressure io.pressure cpu.pressure; do
  if [ -r "$CG/$f" ]; then
    cp "$CG/$f" "$D/cgroup/$f" 2>/dev/null || true
  fi
done

# 2. 호스트 지표.
for f in meminfo vmstat stat diskstats loadavg pressure/io pressure/memory pressure/cpu; do
  if [ -r "/proc/$f" ]; then
    cp "/proc/$f" "$D/host/$(basename "$f")" 2>/dev/null || true
  fi
done

# 3. 가벼운 Qdrant 창구.
curl -s --max-time 10 "$QURL/collections/$COLL"                               > "$D/collection.json"
curl -s --max-time 30 "$QURL/collections/$COLL/optimizations?with=queued,completed,idle_segments" \
                                                                              > "$D/optimizations.json"

# 4. 계측 빌드의 단계별 시간. 읽자마자 초기화한다.
curl -s --max-time 10 "$QURL/stage_timings"                                   > "$D/stage_timings.json"
if [ "$SNAP_RESET" = "1" ]; then
  curl -s --max-time 10 -X POST "$QURL/stage_timings/reset"                   > "$D/stage_timings_reset.json"
  date +%s.%N                                                                 > "$D/stage_timings_reset_at"
fi

# 5. 무거운 창구. 전 세그먼트에 읽기 잠금을 걸거나 페이지 테이블을 훑는다.
curl -s --max-time 120 "$QURL/collections/$COLL/memory"                       > "$D/memory.json"
curl -s --max-time 120 "$QURL/telemetry?details_level=4"                      > "$D/telemetry.json"
curl -s --max-time 120 "$QURL/metrics"                                        > "$D/metrics.txt"
curl -s --max-time 30  "$QURL/profiler/slow_requests?limit=64"                > "$D/slow_requests.json"

T1=$(date +%s.%N)

# 6. 이 스냅샷 자체의 메타. 스냅샷에 걸린 시간도 측정값이다.
cat > "$D/snapshot_meta.json" <<EOF
{
  "name": "$NAME",
  "t_begin": $T0,
  "t_end": $T1,
  "duration_sec": $(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.3f", b-a}'),
  "collection": "$COLL",
  "cgroup": "$CG",
  "stage_timings_reset": $SNAP_RESET
}
EOF

echo "스냅샷 '$NAME' 완료. 소요 $(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.3f", b-a}')초. 위치 $D"

# 7. 최소 건전성 확인. 하나라도 비면 그 창구가 응답하지 않은 것이다.
for f in collection.json optimizations.json stage_timings.json memory.json \
         telemetry.json metrics.txt; do
  if [ ! -s "$D/$f" ]; then
    echo "  경고: $f 가 비어 있다" >&2
  fi
done
if [ ! -s "$D/cgroup/memory.current" ]; then
  echo "  경고: cgroup/memory.current 가 비어 있다. CG 경로를 확인한다" >&2
fi
