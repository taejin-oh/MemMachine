#!/usr/bin/env python3
"""Qdrant 병목 측정 2단계 — 시계열 수집기.

컨테이너 cgroup 계수기와 호스트 지표, 그리고 가벼운 Qdrant 창구만 주기적으로 읽는다.
전 세그먼트에 읽기 잠금을 거는 무거운 창구(`/metrics`, `/telemetry?details_level=4`,
`/collections/{c}/memory`)는 이 수집기가 읽지 않는다. 그 셋은 구간 경계에서
`snapshot.sh` 가 한 번씩만 읽는다. 예외는 `--mem-period` 를 0보다 크게 주었을 때의
`/collections/{c}/memory` 뿐이며, 기본값은 0(읽지 않음)이다.

표준 라이브러리만 쓴다. 파이썬 3.8 이상이면 돈다.

사용 예:

    python3 collect_metrics.py \
        --cgroup /sys/fs/cgroup/system.slice/docker-<id>.scope \
        --collection laion100m \
        --out "$RAW/results/<run_id>/series" \
        --cores "$CPUSET" --io-dev 259:0 --disk-dev nvme0n1
    # CPUSET 은 환경 문서 3.1절에서 SSD 가 붙은 NUMA 노드 기준으로 정한 값이다.
    # --cores 를 빠뜨리면 실행되지 않는다. 기본값으로 엉뚱한 코어를 재는 일을 막기 위해서다.

출력(JSON Lines, 한 줄이 한 표본):

    cgroup.jsonl         컨테이너 cgroup 계수기            --period 주기
    host.jsonl           호스트 CPU/메모리/디스크           --period 주기
    qdrant.jsonl         GET /collections/{c}              --period 주기
    optimizations.jsonl  GET /collections/{c}/optimizations --opt-period 주기
    memory.jsonl         GET /collections/{c}/memory        --mem-period 주기(기본 꺼짐)
    collector.log        수집기 자신의 오류와 자원 사용량
"""

import argparse
import json
import os
import resource
import signal
import sys
import time
import urllib.request

RUNNING = True


def _stop(signum, frame):
    global RUNNING
    RUNNING = False


def read_text(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return None


def parse_kv(text):
    """'키 값' 형식의 cgroup 파일을 딕셔너리로 만든다."""
    out = {}
    if not text:
        return out
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            out[parts[0]] = int(parts[1])
        except ValueError:
            out[parts[0]] = parts[1]
    return out


def parse_scalar(text):
    if text is None:
        return None
    t = text.strip()
    if t == "max":
        return "max"
    try:
        return int(t)
    except ValueError:
        return None


def parse_psi(text):
    """PSI 파일은 'some avg10=.. avg60=.. avg300=.. total=..' 두 줄이다.

    total 은 누적 정체 시간(마이크로초)이고 avg 계열은 커널이 계산한 순간값이다.
    판정에는 total 의 구간 차를 쓴다.
    """
    out = {}
    if not text:
        return out
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        kind = parts[0]
        vals = {}
        for p in parts[1:]:
            if "=" not in p:
                continue
            k, v = p.split("=", 1)
            try:
                vals[k] = float(v) if "." in v else int(v)
            except ValueError:
                pass
        out[kind] = vals
    return out


def parse_io_stat(text, want_dev):
    """io.stat 은 장치마다 한 줄이고 'MAJ:MIN k=v k=v ...' 형식이다."""
    out = {}
    if not text:
        return out
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        dev = parts[0]
        if want_dev and dev != want_dev:
            continue
        vals = {}
        for p in parts[1:]:
            if "=" not in p:
                continue
            k, v = p.split("=", 1)
            try:
                vals[k] = int(v)
            except ValueError:
                pass
        out[dev] = vals
    return out


def parse_cores(spec):
    """'0-15' 또는 '0-15,300-303' 을 정수 집합으로 바꾼다."""
    cores = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            cores.update(range(int(a), int(b) + 1))
        else:
            cores.add(int(chunk))
    return cores


def sample_cgroup(cg, io_dev):
    return {
        "memory_current": parse_scalar(read_text(os.path.join(cg, "memory.current"))),
        "memory_max": parse_scalar(read_text(os.path.join(cg, "memory.max"))),
        "memory_peak": parse_scalar(read_text(os.path.join(cg, "memory.peak"))),
        "memory_swap_current": parse_scalar(
            read_text(os.path.join(cg, "memory.swap.current"))
        ),
        "memory_events": parse_kv(read_text(os.path.join(cg, "memory.events"))),
        "memory_stat": parse_kv(read_text(os.path.join(cg, "memory.stat"))),
        "cpu_stat": parse_kv(read_text(os.path.join(cg, "cpu.stat"))),
        "io_stat": parse_io_stat(read_text(os.path.join(cg, "io.stat")), io_dev),
        "pids_current": parse_scalar(read_text(os.path.join(cg, "pids.current"))),
        "memory_pressure": parse_psi(read_text(os.path.join(cg, "memory.pressure"))),
        "io_pressure": parse_psi(read_text(os.path.join(cg, "io.pressure"))),
        "cpu_pressure": parse_psi(read_text(os.path.join(cg, "cpu.pressure"))),
    }


def sample_host(cores, disk_devs):
    cpu = {}
    stat = read_text("/proc/stat") or ""
    for line in stat.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        label = parts[0]
        if label == "cpu":
            cpu["total"] = [int(x) for x in parts[1:]]
            continue
        try:
            idx = int(label[3:])
        except ValueError:
            continue
        if idx in cores:
            cpu[str(idx)] = [int(x) for x in parts[1:]]

    meminfo = {}
    for line in (read_text("/proc/meminfo") or "").splitlines():
        parts = line.replace(":", "").split()
        if len(parts) >= 2 and parts[0] in (
            "MemTotal", "MemFree", "MemAvailable", "Cached",
            "Dirty", "Writeback", "SwapFree", "SwapTotal", "Mapped",
        ):
            try:
                meminfo[parts[0]] = int(parts[1])
            except ValueError:
                pass

    vm = {}
    for line in (read_text("/proc/vmstat") or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in (
            "pgmajfault", "pgpgin", "pgpgout", "pswpin", "pswpout",
            "workingset_refault_file", "workingset_activate_file",
            "pgscan_kswapd", "pgscan_direct", "pgsteal_kswapd", "pgsteal_direct",
        ):
            try:
                vm[parts[0]] = int(parts[1])
            except ValueError:
                pass

    disks = {}
    if disk_devs:
        for line in (read_text("/proc/diskstats") or "").splitlines():
            parts = line.split()
            if len(parts) < 14:
                continue
            if parts[2] in disk_devs:
                disks[parts[2]] = [int(x) for x in parts[3:14]]

    return {"cpu": cpu, "meminfo_kb": meminfo, "vmstat": vm, "diskstats": disks}


def http_json(url, timeout):
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "cost_ms": (time.monotonic() - t0) * 1000.0, "body": body}
    except Exception as exc:  # 수집기는 어떤 이유로도 멈추면 안 된다
        return {
            "ok": False,
            "cost_ms": (time.monotonic() - t0) * 1000.0,
            "error": "%s: %s" % (type(exc).__name__, exc),
        }


class Writer:
    def __init__(self, path):
        self.f = open(path, "a", buffering=1024 * 64)
        self.n = 0

    def write(self, obj):
        self.f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
        self.f.write("\n")
        self.n += 1

    def flush(self):
        self.f.flush()

    def close(self):
        try:
            self.f.flush()
            os.fsync(self.f.fileno())
        except OSError:
            pass
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cgroup", required=True, help="컨테이너 cgroup 디렉터리")
    ap.add_argument("--out", required=True, help="출력 디렉터리")
    ap.add_argument("--collection", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:6333")
    ap.add_argument("--cores", required=True,
                    help="Qdrant 에 고정한 코어. 환경 문서 3.1절의 $CPUSET 값을 넘긴다. 기본값 없음")
    ap.add_argument("--io-dev", default="", help="cgroup io.stat 에서 볼 MAJ:MIN")
    ap.add_argument("--disk-dev", default="", help="/proc/diskstats 장치 이름, 쉼표 구분")
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--opt-period", type=float, default=5.0)
    ap.add_argument("--mem-period", type=float, default=0.0,
                    help="0보다 크면 /collections/{c}/memory 를 이 주기로 읽는다. 기본 0(안 읽음)")
    ap.add_argument("--http-timeout", type=float, default=2.0)
    args = ap.parse_args()

    if not os.path.isdir(args.cgroup):
        sys.stderr.write("cgroup 디렉터리가 없다: %s\n" % args.cgroup)
        return 2
    os.makedirs(args.out, exist_ok=True)

    cores = parse_cores(args.cores)
    disk_devs = set(d for d in args.disk_dev.split(",") if d)
    coll_url = "%s/collections/%s" % (args.url.rstrip("/"), args.collection)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    w_cg = Writer(os.path.join(args.out, "cgroup.jsonl"))
    w_host = Writer(os.path.join(args.out, "host.jsonl"))
    w_q = Writer(os.path.join(args.out, "qdrant.jsonl"))
    w_opt = Writer(os.path.join(args.out, "optimizations.jsonl"))
    w_mem = Writer(os.path.join(args.out, "memory.jsonl"))
    log = open(os.path.join(args.out, "collector.log"), "a", buffering=1)

    log.write("started epoch=%.6f argv=%s\n" % (time.time(), " ".join(sys.argv[1:])))

    start_mono = time.monotonic()
    next_tick = start_mono
    next_opt = start_mono
    next_mem = start_mono if args.mem_period > 0 else float("inf")
    next_report = start_mono + 60.0
    late = 0

    while RUNNING:
        now_mono = time.monotonic()
        if now_mono < next_tick:
            time.sleep(min(0.05, next_tick - now_mono))
            continue
        if now_mono - next_tick > args.period:
            late += 1  # 주기를 못 지킨 횟수. 수집기가 밀리면 표본 간격이 틀어진다
        ts = time.time()

        w_cg.write({"t": ts, **sample_cgroup(args.cgroup, args.io_dev)})
        w_host.write({"t": ts, **sample_host(cores, disk_devs)})
        w_q.write({"t": ts, **http_json(coll_url, args.http_timeout)})

        if now_mono >= next_opt:
            w_opt.write({"t": ts, **http_json(
                coll_url + "/optimizations?with=queued,completed,idle_segments",
                args.http_timeout)})
            next_opt += args.opt_period
            while next_opt <= now_mono:
                next_opt += args.opt_period

        if now_mono >= next_mem:
            w_mem.write({"t": ts, **http_json(coll_url + "/memory", args.http_timeout)})
            next_mem += args.mem_period
            while next_mem <= now_mono:
                next_mem += args.mem_period

        if now_mono >= next_report:
            ru = resource.getrusage(resource.RUSAGE_SELF)
            log.write("epoch=%.3f cpu_user=%.2fs cpu_sys=%.2fs maxrss_kb=%d "
                      "samples=%d late=%d\n"
                      % (ts, ru.ru_utime, ru.ru_stime, ru.ru_maxrss, w_cg.n, late))
            for w in (w_cg, w_host, w_q, w_opt, w_mem):
                w.flush()
            next_report += 60.0

        next_tick += args.period
        while next_tick <= now_mono:
            next_tick += args.period

    ru = resource.getrusage(resource.RUSAGE_SELF)
    log.write("stopped epoch=%.6f samples=%d late=%d cpu_user=%.2fs cpu_sys=%.2fs\n"
              % (time.time(), w_cg.n, late, ru.ru_utime, ru.ru_stime))
    log.close()
    for w in (w_cg, w_host, w_q, w_opt, w_mem):
        w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
