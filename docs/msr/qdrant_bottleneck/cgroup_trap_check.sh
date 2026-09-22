#!/usr/bin/env bash
#
# cgroup 메모리 과금 함정 검증
#
#   같은 파일을 "누가 먼저 읽었는지"만 바꿔 두 번 읽고, 컨테이너가 디스크를
#   실제로 읽었는지 비교한다.
#
#     조건 B (기준선)  캐시를 비우고 → 컨테이너가 먼저 읽는다
#     조건 A (함정)    캐시를 비우고 → 호스트가 먼저 읽은 뒤 → 컨테이너가 읽는다
#
#   두 조건의 결과가 다르면 함정이 실재한다.
#   절차 설명은 cgroup_trap_check_2026-09-21.md 에 있다.
#
# 사용법:
#   sudo ./cgroup_trap_check.sh
#   sudo SIZE_MB=32768 LIMIT=8g ./cgroup_trap_check.sh
#   sudo KEEP=1 ./cgroup_trap_check.sh        # 더미 파일을 남긴다
#
set -euo pipefail

F=${F:-/var/tmp/trap_test.bin}
SIZE_MB=${SIZE_MB:-16384}
LIMIT=${LIMIT:-4g}
IMG=${IMG:-alpine}
KEEP=${KEEP:-0}

GiB=1073741824

# 진행 메시지는 모두 표준오류로 보낸다.
# 표준출력은 run_case 의 반환값 전용이라 섞이면 측정값이 깨진다.
say()  { printf '\n\033[1m%s\033[0m\n' "$*" >&2; }
note() { printf '    %s\n' "$*" >&2; }
die()  { printf '\n[중단] %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 사전 확인

say "0. 사전 확인"

[ "$(id -u)" -eq 0 ] || die "drop_caches 에 root 권한이 필요하다. sudo 로 다시 실행한다."

FSTYPE=$(stat -fc %T /sys/fs/cgroup/)
[ "$FSTYPE" = cgroup2fs ] || die "cgroup v2 가 아니다 (/sys/fs/cgroup = $FSTYPE). 이 절차는 v2 전용이다."
note "cgroup v2 확인"

command -v docker >/dev/null || die "docker 를 찾을 수 없다."

if grep -qw io /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null; then
    IO_OK=1; note "io 컨트롤러 활성 — 컨테이너별 디스크 읽기량을 직접 읽는다"
else
    IO_OK=0; note "io 컨트롤러 비활성 — 디스크 읽기량 없이 memory.current 와 한도 도달 횟수로만 판정한다"
fi

FREE_MB=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
NEED_MB=$((SIZE_MB + 4096))
[ "$FREE_MB" -ge "$NEED_MB" ] \
    || die "여유 메모리가 부족하다. 필요 ${NEED_MB}MB / 현재 ${FREE_MB}MB. SIZE_MB 를 줄인다."
note "여유 메모리 ${FREE_MB}MB (필요 ${NEED_MB}MB)"

# 이미지는 측정 전에 미리 받아 둔다.
# 캐시를 비운 뒤에 내려받으면 그 과정이 페이지 캐시를 오염시킨다.
if docker image inspect "$IMG" >/dev/null 2>&1; then
    note "이미지 $IMG 확인"
else
    note "이미지 $IMG 내려받는 중"
    docker pull -q "$IMG" >/dev/null
fi

# ---------------------------------------------------------------- 더미 파일

say "1. 더미 파일 준비  ($F, ${SIZE_MB}MB)"

ACTUAL_MB=0
[ -f "$F" ] && ACTUAL_MB=$(( $(stat -c %s "$F") / 1048576 ))

if [ "$ACTUAL_MB" -eq "$SIZE_MB" ]; then
    note "이미 있는 파일을 재사용한다"
else
    note "난수로 채운다. 1~3분 걸린다"
    dd if=/dev/urandom of="$F" bs=1M count="$SIZE_MB" status=progress
fi

# 희소 파일이면 읽어도 디스크에 가지 않아 실험이 무효가 된다
APPARENT=$(stat -c %s "$F")
ALLOCATED=$(( $(stat -c %b "$F") * $(stat -c %B "$F") ))
[ "$ALLOCATED" -ge $(( APPARENT * 9 / 10 )) ] \
    || die "희소 파일이다 (실제 할당 $((ALLOCATED/1048576))MB / 표시 $((APPARENT/1048576))MB). 압축 없는 파일시스템에서 다시 만든다."
note "실제 할당 $((ALLOCATED/1048576))MB — 희소 파일 아님"

# ---------------------------------------------------------------- 보조 함수

drop_caches() { sync; echo 3 > /proc/sys/vm/drop_caches; sleep 1; }

cached_mb() { awk '/^Cached:/{print int($2/1024)}' /proc/meminfo; }

cg_of() {
    local pid; pid=$(docker inspect -f '{{.State.Pid}}' "$1")
    echo "/sys/fs/cgroup$(grep '^0::' "/proc/$pid/cgroup" | cut -d: -f3)"
}

rbytes() {
    if [ "$IO_OK" -ne 1 ] || [ ! -r "$1/io.stat" ]; then echo 0; return; fi
    awk '{for(i=2;i<=NF;i++) if($i ~ /^rbytes=/){split($i,a,"="); s+=a[2]}} END{printf "%.0f\n", s}' "$1/io.stat"
}

# run_case <A|B>
#   표준출력으로 "소요초 디스크읽기바이트 memory.current 한도도달횟수" 한 줄만 낸다
run_case() {
    local mode=$1 cid cg r0 r1 t0 t1 mem maxev before after

    drop_caches

    if [ "$mode" = A ]; then
        before=$(cached_mb)
        dd if="$F" of=/dev/null bs=1M status=none
        after=$(cached_mb)
        note "호스트가 먼저 읽음 — 페이지 캐시 ${before}MB 에서 ${after}MB 로"
        [ $(( after - before )) -ge $(( SIZE_MB * 8 / 10 )) ] \
            || die "호스트 캐시가 충분히 차지 않았다. 조건 A 가 성립하지 않아 비교가 무의미하다."
    fi

    cid=$(docker run -d --memory="$LIMIT" --memory-swap="$LIMIT" \
                     -v "$F":/data/f:ro "$IMG" sleep 900)
    cg=$(cg_of "$cid")
    if [ ! -d "$cg" ]; then
        docker rm -f "$cid" >/dev/null
        die "컨테이너 cgroup 경로를 찾지 못했다: $cg"
    fi

    r0=$(rbytes "$cg")
    t0=$(date +%s.%N)
    docker exec "$cid" dd if=/data/f of=/dev/null bs=1M     # 요약은 표준오류로 나간다
    t1=$(date +%s.%N)
    r1=$(rbytes "$cg")

    mem=$(cat "$cg/memory.current")
    maxev=$(awk '/^max /{print $2}' "$cg/memory.events")
    docker rm -f "$cid" >/dev/null

    awk -v a="$t0" -v b="$t1" -v r="$(( r1 - r0 ))" -v m="$mem" -v e="${maxev:-0}" \
        'BEGIN{printf "%.1f %s %s %s\n", b-a, r, m, e}'
}

# ---------------------------------------------------------------- 측정

# die 는 서브셸만 끝내므로, 실패를 부모에서 다시 잡아 준다
say "2. 조건 B — 컨테이너가 먼저 읽는다 (기준선)"
B_OUT=$(run_case B) || exit 1
read -r B_SEC B_RB B_MEM B_MAX <<<"$B_OUT"
note "소요 ${B_SEC}초"

say "3. 조건 A — 호스트가 먼저 읽는다 (함정 조건)"
A_OUT=$(run_case A) || exit 1
read -r A_SEC A_RB A_MEM A_MAX <<<"$A_OUT"
note "소요 ${A_SEC}초"

# ---------------------------------------------------------------- 판정

say "4. 결과"

gib() { awk -v v="$1" -v g="$GiB" 'BEGIN{printf "%.2f", v/g}'; }

printf '\n    %-22s %14s %14s\n' "지표" "B (컨테이너)" "A (호스트)"
printf '    %-22s %14s %14s\n' "----------------------" "--------------" "--------------"
printf '    %-22s %13s초 %13s초\n' "읽기 소요 시간" "$B_SEC" "$A_SEC"
if [ "$IO_OK" -eq 1 ]; then
    printf '    %-22s %10s GiB %10s GiB\n' "컨테이너 디스크 읽기" "$(gib "$B_RB")" "$(gib "$A_RB")"
fi
printf '    %-22s %10s GiB %10s GiB\n' "memory.current" "$(gib "$B_MEM")" "$(gib "$A_MEM")"
printf '    %-22s %14s %14s\n' "한도 도달 횟수" "$B_MAX" "$A_MAX"

# 판정은 cgroup 계수기로만 한다.
#
# 읽기 소요 시간은 참고값일 뿐 판정에 쓰지 않는다. 디스크가 빠른 장비에서는
# 단일 스레드 dd 의 메모리 복사가 병목이 되어, 캐시에서 읽어도 시간이 줄지 않는다.
# 실측에서 디스크 읽기 32GiB 를 4.2초(초당 7.6GB)에 처리한 장비가 있었고,
# 그 장비에서는 캐시 적중(4.4초)이 오히려 근소하게 느렸다.
# 시간을 판정에 넣으면 이런 장비에서 함정을 놓친다.

# 조건 B 가 실제로 한도 압박을 받았는지 먼저 본다. 아니면 비교 자체가 성립하지 않는다.
B_PRESSURED=0
[ "${B_MAX:-0}" -gt 0 ] && B_PRESSURED=1
[ "$IO_OK" -eq 1 ] && [ "$(awk -v b="$B_RB" 'BEGIN{print (b>0)?1:0}')" -eq 1 ] && B_PRESSURED=1

# 세 가지 계수기 지표
SIG_IO=0
[ "$IO_OK" -eq 1 ] && SIG_IO=$(awk -v a="$A_RB" -v b="$B_RB" 'BEGIN{print (b > 0 && a*10 < b) ? 1 : 0}')
SIG_MAX=0
[ "${B_MAX:-0}" -gt 0 ] && [ "${A_MAX:-0}" -eq 0 ] && SIG_MAX=1
SIG_MEM=$(awk -v a="$A_MEM" -v b="$B_MEM" 'BEGIN{print (b > 0 && a*4 < b) ? 1 : 0}')

SIGNALS=$(( SIG_IO + SIG_MAX + SIG_MEM ))

echo
if [ "$B_PRESSURED" -eq 0 ]; then
    printf '\033[1m    판정 불가.\033[0m\n'
    echo "    기준선인 조건 B 가 한도에 부딪히지 않았다. 디스크 읽기도 한도 도달도 없다."
    echo "    파일이 한도보다 작거나 계수기를 못 읽은 것이다. SIZE_MB 와 LIMIT 을 확인한다."
elif [ "$SIGNALS" -ge 2 ]; then
    printf '\033[1m    판정: 함정이 실재한다.\033[0m  (계수기 지표 %d/3 일치)\n' "$SIGNALS"
    echo "    호스트가 먼저 읽은 데이터는 컨테이너 한도에 과금되지 않는다."
    echo "    설계서 4.3절 대책 네 가지를 본 실험 절차에 필수로 넣는다."
    echo "    특히 한도만 바꿔 재측정하는 방식은 금지한다."
    if [ "${A_MAX:-0}" -ne 0 ]; then
        echo "    다만 조건 A 에서도 한도 도달이 ${A_MAX}회 있었다. 부분적 과금 가능성을 함께 기록한다."
    fi
else
    printf '\033[1m    판정: 함정이 나타나지 않았다.\033[0m  (계수기 지표 %d/3 일치)\n' "$SIGNALS"
    echo "    조건 A 의 컨테이너가 조건 B 와 비슷하게 디스크를 읽고 한도에 부딪혔다."
    echo "    결론 전에 조건 A 의 호스트 캐시가 실제로 찼는지 위 로그를 다시 확인한다."
fi

echo
echo "    참고: 읽기 소요 시간은 판정에 쓰지 않았다. 디스크가 빠르면 캐시 적중과"
echo "          디스크 읽기의 시간 차이가 사라져 지표로 쓸 수 없기 때문이다."

# ---------------------------------------------------------------- 뒷정리

say "5. 뒷정리"
if [ "$KEEP" -eq 1 ]; then
    note "더미 파일을 남긴다: $F"
else
    rm -f "$F"; note "더미 파일 삭제"
fi
drop_caches
note "페이지 캐시 정리 완료"
echo
