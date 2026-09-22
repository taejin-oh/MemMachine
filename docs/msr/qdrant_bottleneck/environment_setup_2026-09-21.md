# 측정 환경 구축 절차서 — 격리와 조건 전환

- 작성일: 2026-09-21
- 대상: Qdrant **v1.19.1** 계측 빌드. 컨테이너 CPU 16코어 고정, 메모리 한도 128 / 256 / 512GB. 양자화는 실험 범위에 없다
- 위치: 설계서 4.6절 작업 순서의 **1단계 Qdrant Docker 환경 준비** 가운데 **1.2 조건에 맞춰 띄우기**, **1.4 준비 완료 확인**, **1.5 조건 전환 스크립트와 잡음 제거와 코어 예약**이다. 1.3 함정 확인은 끝났고, 4단계 계측 코드는 4.2 계측 방법과 4.3 코드 삽입과 4.4 동작 확인까지 끝나 4.5 왜곡 검증만 남았으며(1단계와 3.3 부하기가 있어야 돌 수 있다), 이 문서와 3단계 부하 도구 제작이 지금 착수할 단계다. 옛 번호 체계(0~7번)는 폐기했으므로 이 문서의 단계 번호는 모두 새 구조의 것이다
- 산출물: 조건 하나를 세우는 단일 스크립트 `$RAW/bin/run_condition.sh` 와 그 안에 박힌 통과 조건 세 개
- 상태: **측정 서버에 접속하지 못한 채 작성했다.** 이 문서의 어떤 명령도 실물로 확인하지 못했다. Qdrant v1.19.1 소스에서 확인한 사실은 그 자리에 출처를 적었고, 확인하지 못한 것은 9장에 모았다

## 관련 문서

이 문서는 아래를 전제로 하며 같은 내용을 다시 적지 않는다.

| 문서 | 여기서 가져오는 것 |
|---|---|
| `design_2026-09-17.md` | 4.1절 호스트 구성, 4.2절 메모리 축, 4.3절 함정과 대책 네 가지, 4.6절 작업 순서 |
| `preparation_2026-09-21.md` | 서버 확인(3장), 도구 설치(4장), 경로 변수와 저장 공간 설계(1.3, 5.3, 5.4, 5.7), 공용 사용자 합의(6.3) |
| `cgroup_trap_check_2026-09-21.md` + `cgroup_trap_check.sh` | 함정의 실측 결과, 판정에 쓸 계수기, 시간을 판정에서 뺀 이유(6.1) |
| `metrics_collection_2026-09-21.md` + `collect_metrics.py` + `snapshot.sh` | 측정 항목 11개의 수집 주기와 저장 형식, 구간 경계 스냅샷, 조건별 통과 기준 |
| `emulator_spec_2026-09-21.md` | 제어기와 부하기와 적재기의 역할 분담(4.1, 4.5, 5.3, 5.4, 6.4). 5.4절이 받아 적은 제어기의 의무 네 가지의 출처다. 제어기는 새 구조 3.4 로 부하 도구의 산출물이다 |
| `instrumented_build_2026-09-21.md` | 계측 이미지 빌드, `GET /stage_timings` 와 `POST /stage_timings/reset` |
| `stage_isolation_2026-09-18.md` | 계측 지점 18개소의 명세와 8장의 해석 제약 |
| `qdrant_instrumentation_2026-09-17.md` | Qdrant 기본 관측 창구의 응답 구조와 한계 |
| `dataset_download_2026-09-21.md` | 데이터셋 확보 절차 |

---

## 1. 요약

새 단계 구조에서 이 문서는 세 항목에 해당한다. **1.2 조건에 맞춰 띄우기**는 3장과 4장이다. SSD 가 붙은 NUMA 노드를 먼저 확인하고 그 노드의 코어 열여섯 개와 메모리를 쓰며, DRAM 한도 128 / 256 / 512GB 와 컨테이너 단위 스왑 차단을 걸고, blktrace 를 준비한다. **1.4 준비 완료 확인**은 3장과 4장의 확인 창구와 5.6절과 5.7절의 게이트와 7.2절의 점검표다. 한도와 코어 고정과 스왑 차단과 NUMA 정합을 컨테이너 cgroup 파일에서 읽어 확인한다. **1.5 조건 전환 스크립트와 잡음 제거와 부하 도구 및 수집기 코어 예약**은 5장과 6.3절이다. 1.5 의 수집기 자체는 `metrics_collection_2026-09-21.md` 에 있다.

이 문서가 만드는 것은 컨테이너 하나가 아니라 **조건 하나를 세우는 절차 전체를 담은 스크립트 하나**다. 2026-09-21에 메모리 과금 함정이 실재하는 것으로 확인되면서, 조건을 바꾸는 일이 "한도를 바꾼다"에서 "폐기하고, 복원하고, 캐시를 비우고, 재생성하고, 검증한다"로 바뀌었기 때문이다. 이 다섯 가지는 순서가 정해져 있고 하나라도 건너뛰면 그 조건은 무효가 되는데, **무효라는 사실이 결과를 보아서는 드러나지 않는다.** 한도를 4GB로 걸어 놓고도 한도에 한 번도 부딪히지 않은 것이 함정 검증에서 실제로 관측된 모습이다. 그래서 손으로 하지 않고 스크립트로 묶으며, 각 단계 뒤에 통과 조건을 두어 조건이 제대로 서지 않으면 아예 측정에 들어가지 못하게 한다.

통과 조건은 셋이다. **게이트 A** 는 컨테이너를 만들기 직전에 작업본이 페이지 캐시에 남아 있지 않은지를 `fincore` 로 경로 단위로 묻는다. 1TB 장비에서 `/proc/meminfo` 의 전역 `Cached` 는 다른 작업의 캐시에 묻혀 판정 근거가 되지 못하므로 경로 단위 확인이 필요하다. **게이트 B** 는 한도와 cpuset 이 실제로 물렸는지를 `docker inspect` 가 아니라 호스트에서 읽은 cgroup 파일로 확인한다. `docker inspect` 는 요청값을 되돌려 줄 뿐이라 근거가 되지 않는다. **게이트 C** 는 적재와 예열이 끝난 뒤 그 데이터가 컨테이너 앞으로 과금되었는지를 `io.stat` 의 `rbytes` 와 `memory.current` 로 증명한다.

Qdrant v1.19.1 소스에서 두 가지를 확인했고 그것이 설계를 바꾸었다. 하나는 환경 변수 `QDRANT_NUM_CPUS` 가 스레드 풀 크기를 직접 고정한다는 것으로, 준비 문서 3.7절이 세 번째로 큰 공백으로 남긴 "컨테이너가 호스트의 344개를 읽어 스레드 수백 개를 만드는" 위험을 확정적으로 막을 수 있다. 다른 하나는 `low_memory_mode` 기본값이 `Disabled` 라 기동 시 mmap 예열이 돌아 컨테이너 자신이 전 페이지를 폴트한다는 것으로, 이 덕분에 준비 문서 5.7절의 마스터 복사 경로가 조건마다 1억 개를 재적재하지 않고도 과금 조건을 만족할 수 있다. 다만 이 두 번째 사실은 실물 서버에서 확인하지 못했으므로 게이트 C 가 매 조건마다 이를 증명하게 했다.

판정에 **읽기 소요 시간을 쓰지 않는다.** 함정 검증에서 디스크를 읽은 조건이 32GiB 를 4.2초에 읽어 초당 7.6GB 가 나왔는데, 이 값은 디스크 속도가 아니라 단일 스레드 `dd` 의 메모리 복사가 병목이라는 뜻이다. 캐시에서 읽은 조건도 같은 복사를 해야 하므로 빨라질 여지가 없었고 실제로 4.4초로 근소하게 더 느렸다. 그래서 시간으로는 캐시 적중과 디스크 읽기를 구분할 수 없고, 판정은 cgroup 계수기로만 한다. 근거는 `cgroup_trap_check_2026-09-21.md` 6.1절에 있다.

**이 문서가 끝나면 세 조건을 같은 절차로 반복해 세울 수 있고, 조건마다 그것이 유효한 조건인지를 측정에 들어가기 전에 판정할 수 있다.** 그다음은 3단계 부하 도구 제작이며, 3.3 부하기가 만들어지면 4.5 왜곡 검증까지 이어서 끝낼 수 있다.

---

## 2. 시작 전 조건

### 2.1 준비 문서가 끝나 있어야 한다

이 문서는 서버가 어떤 상태인지 이미 안다고 보고 시작한다. 서버 확인과 도구 설치와 저장 공간 설계는 `preparation_2026-09-21.md` 의 몫이며, 여기서 다시 적지 않는다. 특히 준비 문서 3.3절부터 3.8절까지를 돌려 값을 채우지 않은 상태에서 이 문서의 스크립트를 쓰면, 스크립트가 어디서 멈추는지는 보여도 왜 멈추는지는 알 수 없다.

| 준비 문서 | 여기서 필요한 결과 | 없으면 어떻게 되나 |
|---|---|---|
| 3.3 커널과 cgroup | cgroup v2 이고 memory, io, cpuset, cpu 가 컨테이너 계층까지 위임되어 있음 | io 가 없으면 게이트 C 의 첫 지표가 통째로 비고, cpuset 이 없으면 코어 고정 자체가 불가능하다 |
| 3.4 CPU 구성 | NUMA 노드 수와 노드당 메모리 용량, SMT 형제 배치, 인터럽트가 몰린 코어 번호 | 3.1절에서 코어 열여섯 개를 고를 수 없다 |
| 3.5 메모리 구성 | `MemAvailable`, zswap 과 zram 상태, THP, `vm.max_map_count` | 512GB 조건을 세울 수 있는지 모른 채 들어가게 된다 |
| 3.6 디스크 장치 | `$BENCH` 의 블록 장치와 `major:minor`, readahead, 파일시스템 종류 | 게이트 C 가 보는 `io.stat` 줄이 어느 장치인지 모르고, 3.1절이 그 장치의 NUMA 노드를 읽을 수 없다 |
| 3.7 Qdrant 컨테이너 동작 | 바인드 마운트 쓰기 가능 여부, 유휴 스레드 수 | 4장의 마운트 방식이 서버에서 통하는지 알 수 없다 |
| 3.8 격리 | 공동 사용자 유무, 주기 작업 목록, 한도 없는 다른 컨테이너 유무 | 6.3절의 측정 창 보호를 설계할 수 없다 |
| 4장 도구 설치 | `fincore`(util-linux-extra), `numfmt`(coreutils), `docker`, `curl`, `lscpu` | 게이트 A 가 `fincore` 에 직접 의존한다 |
| 5.3, 5.4 저장 공간 | `$RAW` 와 `$BENCH` 가 서로 다른 블록 장치에 있고 디렉터리가 만들어져 있음 | 수집 결과의 쓰기가 Qdrant 저장소 장치의 통계에 섞인다 |
| 6.3 공용 사용자 합의 | `drop_caches` 와 거버너 고정과 주기 작업 정지에 대한 합의 | 합의 없이 실행하면 같은 서버의 다른 작업을 직접 망가뜨린다 |

### 2.2 이 절차 고유의 요건

준비 문서에 없고 이 절차에서 처음 요구하는 것은 넷이다.

| 요건 | 내용 | 근거 |
|---|---|---|
| 계측 이미지가 빌드되어 있을 것 | `qdrant:1.19.1-stagetiming` 과 대조용 `qdrant:1.19.1-baseline`. 새 구조 1.1 에서 같은 소스와 같은 Dockerfile 로 `FEATURES` 스위치만 달리해 한 번에 둘 다 만든다 | `instrumented_build_2026-09-21.md` 5장 |
| 마스터 사본이 있을 것 | `$BENCH/qdrant/master` 에 적재를 마친 저장소 한 벌. 적재와 적재 완료 판정과 마스터 사본 생성은 새 구조 3.2 적재기의 몫이다 | 준비 문서 5.7절. 없으면 `RELOAD=ingest` 로만 돌 수 있다 |
| root 권한 | `drop_caches` 에 필요하다. 조건 전환 스크립트는 `sudo` 로 실행한다 | 설계서 4.3절 대책 2 |
| `fincore` | 게이트 A 가 `mincore(2)` 로 경로 단위 캐시 잔류를 묻는다 | 5.6절 |

`fincore` 는 util-linux 본 패키지가 아니라 util-linux-extra 패키지에 들어 있다. Debian 12 와 13, Ubuntu 24.04 에서 확인된 사실이다. 있는지 확인하는 한 줄은 다음과 같으며, 없으면 설치 안내만 출력하고 로그인 셸을 끊지 않는다.

```bash
if command -v fincore >/dev/null 2>&1; then
  echo "fincore 있음: $(command -v fincore)"
else
  echo "fincore 가 없다. sudo apt-get install -y util-linux-extra 로 설치한 뒤 다시 확인한다."
fi
```

### 2.3 이 문서에서 쓰는 변수

경로 변수 `$RAW` 와 `$BENCH` 는 준비 문서 1.3절과 5.4절에서 정한 것을 그대로 쓴다. 이 문서가 추가로 쓰는 변수는 아래 다섯이며, 세 조건 내내 같은 값이어야 한다.

| 변수 | 뜻 | 정하는 곳 |
|---|---|---|
| `CPUSET` | Qdrant 에 고정할 코어 열여섯 개. 쉼표로 이은 목록 | 3.1절 |
| `SIBLINGS` | 그 열여섯 개의 SMT 형제까지 포함한 집합. 부하 생성기와 수집기에서 제외할 대상 | 3.1절 |
| `NODE` | `$BENCH` 가 놓인 NVMe 가 붙어 있는 NUMA 노드 번호. 코어 열여섯 개를 이 노드에서 고르고, 노드 용량이 한도보다 클 때만 `--cpuset-mems` 로 메모리도 이 노드에 묶는다 | 3.1절 |
| `LIMIT` | 메모리 한도. `128g`, `256g`, `512g` 중 하나 | 3.3절 |
| `COLL` | 적재한 컬렉션 이름. 5.7절 게이트 C 의 교차 확인이 `/collections/$COLL/memory` 를 부르는 데 쓴다 | 수집 문서 11.1절의 `export COLL` 줄. 준비 문서 1.3절은 이름을 변수로 적기만 하고 값을 정하지 않는다 |

값이 비어 있는 셸에서 아래 블록들을 돌리면 안 되므로, 파괴적 명령이 들어간 블록에는 모두 빈 값 가드를 두었다.

### 2.4 이 단계가 끝났다는 것을 어떻게 아는가

다음 넷이 모두 참이면 시작할 수 있다. 첫째, 준비 문서 3.9절의 다섯 가지가 끝났다. 둘째, `docker images` 에 계측 이미지와 대조 이미지가 모두 보인다. 셋째, `command -v fincore numfmt docker curl lscpu` 가 다섯 줄을 모두 출력한다. 넷째, `echo "$RAW" "$BENCH"` 가 두 값을 모두 출력하고 `findmnt -no SOURCE "$RAW" "$BENCH"` 가 서로 다른 값을 낸다.

---

## 3. 코어와 메모리 격리

### 3.1 코어 열여섯 개를 고르는 기준

설계서 4.1절은 코어 열여섯 개를 `$BENCH` 의 SSD 가 붙은 NUMA 노드에서 고른다고 적었고, 준비 문서 3.4절은 그 열여섯 개가 물리 코어인지 SMT 형제인지에 따라 실효 연산 능력이 두 배 차이 난다는 점을 공백으로 남겨 두었다. 344 vCPU 장비에서 번호만 보고 고르면 조건이 무엇인지 모르는 채로 측정하게 된다.

**출발점은 코어가 아니라 SSD 의 위치다.** `$BENCH` 가 놓인 NVMe 가 어느 NUMA 노드에 붙어 있는지를 먼저 확인하고, 그 노드의 코어 열여섯 개와 그 노드의 메모리를 Qdrant 에 준다. 128GB 조건은 디스크를 많이 읽는 조건이라, 장치가 붙은 노드와 다른 노드에서 Qdrant 를 돌리면 그 읽기가 전부 소켓 사이 링크를 건너게 되어 메모리 축의 차이에 NUMA 거리의 차이가 섞인다. 부하 도구와 수집기는 이 노드가 아닌 다른 노드의 코어를 쓴다. 그 산출은 6.3절에 있다.

먼저 장치의 노드를 읽는다. 장치 이름은 준비 문서 3.6절이 정한 대로 `lsblk -no PKNAME` 으로 잡는다.

```bash
if [ -z "${BENCH:-}" ]; then
  echo "BENCH 가 비어 있다. preparation_2026-09-21.md 1.3절로 돌아간 뒤 이 블록을 다시 실행한다."
else
  SRC=$(findmnt -no SOURCE "$BENCH")
  DEV=$(lsblk -no PKNAME "$SRC" | head -1)
  [ -n "$DEV" ] || DEV=$(basename "$SRC")
  NODE=$(cat "/sys/block/$DEV/device/numa_node" 2>/dev/null)
  echo "BENCH 장치 = $DEV, numa_node = ${NODE:-<읽지 못함>}"
fi
```

`numa_node` 가 0 이상의 정수 하나로 나와야 한다. `-1` 이면 펌웨어가 장치의 노드를 알려 주지 않은 것이므로, 준비 문서 3.4절의 `numactl -H` 출력과 장치의 PCI 위치를 대조해 손으로 노드를 정하고 그 사실을 조건 명세에 적는다. 파일이 아예 없으면 `$DEV` 가 device-mapper 같은 논리 장치인 것이므로 `lsblk -s "$SRC"` 로 아래의 물리 장치를 찾아 그 이름으로 다시 읽는다.

다음은 메모리 축이다. **그 노드의 로컬 메모리가 512GB 미만이면 512GB 조건에만 원격 메모리 접근이 섞여 128과 256과 512가 같은 성격의 세 점이 아니게 된다.** 노드별 CPU 목록과 로컬 메모리 용량을 보고, `$NODE` 줄의 용량이 512GB 조건을 한 노드 안에서 세울 수 있는지를 읽는다.

```bash
for n in /sys/devices/system/node/node[0-9]*; do
  printf '%-8s mem=%6.0fGB cpus=%s\n' "$(basename "$n")" \
    "$(awk '/MemTotal/{print $4/1048576}' "$n/meminfo")" \
    "$(cat "$n/cpulist")"
done
lscpu | grep -E 'Thread|Core|Socket|NUMA node\(s\)|Model name'
```

노드마다 한 줄씩 나오고 각 줄에 메모리 용량과 CPU 목록이 보여야 한다. `$NODE` 의 용량이 512GB 이상이면 세 조건 모두 한 노드 안에서 성립하고 `--cpuset-mems=$NODE` 를 쓸 수 있다. 512GB 미만이면 그 사실을 설계서 4.2절에 한계로 적고 `--cpuset-mems` 를 쓰지 않되, 코어는 그래도 `$NODE` 에서 고른다. 장치가 붙은 노드를 두고 다른 노드를 고르지 않는다.

그다음 `$NODE` 에서 **서로 다른 물리 코어 열여섯 개**를 뽑는다. `lscpu -p` 의 CORE 열이 물리 코어 번호이므로, 그 값이 처음 나오는 CPU만 취하면 SMT 형제가 섞이지 않는다. `SKIP` 에는 준비 문서 3.4절에서 확인한 인터럽트 집중 코어와 0번을 적는다.

```bash
if [ -z "${NODE:-}" ]; then
  echo "NODE 가 비어 있다. 위의 numa_node 블록을 먼저 실행한다."
else
  SKIP="0"
  CPUSET=$(lscpu -p=CPU,CORE,NODE,ONLINE | grep -v '^#' \
    | awk -F, -v n="$NODE" -v skip=",$SKIP," \
        '$3==n && $4=="Y" && index(skip, ","$1",")==0 && !seen[$2]++ {print $1}' \
    | sort -n | head -16 | paste -sd, -)
  SIBLINGS=$(for c in $(echo "$CPUSET" | tr ',' ' '); do
               cat "/sys/devices/system/cpu/cpu$c/topology/thread_siblings_list"
             done | tr ',' '\n' | sort -n -u | paste -sd, -)
  echo "Qdrant 코어        = $CPUSET"
  echo "형제까지 포함하면  = $SIBLINGS"
fi
```

두 줄이 출력되어야 한다. 둘째 줄이 첫째 줄보다 넓으면 그 차집합이 형제 코어다. **형제 코어는 Qdrant cpuset 에 넣지 않고, 부하 생성기와 수집기에서도 함께 제외한다.** 형제가 남의 작업에 쓰이면 물리 코어의 실행 자원을 나눠 쓰게 되어 우리가 건 열여섯 개의 성능이 남의 부하에 따라 흔들린다.

고른 값은 세 조건 내내 같아야 한다. 조건 전환 스크립트에 환경 변수로 넘기고 조건 명세 파일에 남긴다.

**합격 기준.** `$NODE` 가 `$BENCH` 장치의 `numa_node` 와 같아야 한다. `echo "$CPUSET" | tr ',' '\n' | wc -l` 이 16이어야 한다. `lscpu -p=CPU,CORE,NODE` 로 그 열여섯 개를 되짚었을 때 NODE 가 모두 `$NODE` 이고 CORE 값이 열여섯 가지로 모두 달라야 한다. `$SIBLINGS` 의 개수가 16이면 SMT 가 꺼져 있거나 형제가 없는 것이고, 32이면 형제를 제대로 걸러낸 것이다.

### 3.2 CPU 고정은 cpuset 으로만 건다

준비 문서 3.7절이 "컨테이너 안에서 Qdrant 가 호스트의 344개를 그대로 읽으면 스레드 수백 개가 코어 열여섯 개 위에서 문맥 교환만 하게 된다"를 세 번째로 큰 공백으로 남겨 두었다. 이번에 v1.19.1 소스에서 확인한 결과 **그 위험은 실재하고, 동시에 확정적인 차단 수단도 소스에 이미 있다.**

`lib/common/common/src/cpu.rs` 의 `get_num_cpus()` 는 환경 변수 `QDRANT_NUM_CPUS` 를 먼저 읽고, 없거나 0 이하일 때만 `num_cpus::get()` 으로 떨어진다. 이 값이 그대로 스레드 풀 크기가 된다. 소스에서 확인한 풀별 계산은 다음과 같다.

| 풀 | 스레드 이름 | 크기 | 344로 읽혔을 때 |
|---|---|---|---:|
| 검색 CPU 풀 | `search-cpu-<n>` | `get_num_cpus()` | 344 |
| 검색 IO 풀 | `search-io-<n>` | `get_num_cpus() * 4` | 1,376 |
| 저장 풀 | `update-<n>` | `get_num_cpus()` | 344 |
| 범용 풀 | `general-<n>` | `max(get_num_cpus(), 2)` | 344 |

출처는 `lib/common/common/src/defaults.rs` 의 `search_thread_count()`(`CPU_OVERCOMMIT_FACTOR = 4`)와 `lib/storage/src/content_manager/toc/runtimes.rs` 의 네 생성 함수다. 검색 IO 풀 하나만으로 블로킹 스레드가 1,376개까지 늘어나면, 우리가 관측하는 것은 Qdrant 의 병목이 아니라 과도한 스레드 경합이다.

또 하나, CPU 를 개수 제한(`--cpus`, 즉 cgroup 의 `cpu.max`)으로 걸면 주기 앞부분에서 한도를 소진해 지연이 톱니처럼 튄다. 설계서 4.1절의 결정대로 cpuset 만 써야 한다.

따라서 실행 인자에 다음이 반드시 들어가야 하고, `--cpus` 계열은 들어가서는 안 된다.

```bash
# 컨테이너 실행 인자에 반드시 들어가야 하는 부분
#   --cpuset-cpus="$CPUSET"    코어 고정
#   -e QDRANT_NUM_CPUS=16      스레드 풀 크기를 고정
#   --cpus 와 --cpu-quota 와 --cpu-period 는 넣지 않는다
```

실제로 물렸는지는 호스트에서 컨테이너 cgroup 파일을 직접 읽어 확인한다. `docker inspect` 는 요청값을 되돌려 줄 뿐이라 근거가 되지 않는다.

```bash
if ! docker inspect qdrant-bench >/dev/null 2>&1; then
  echo "qdrant-bench 컨테이너가 없다. 5장의 조건 전환 스크립트를 먼저 돌린다."
else
  CG=/sys/fs/cgroup$(grep '^0::' "/proc/$(docker inspect -f '{{.State.Pid}}' qdrant-bench)/cgroup" | cut -d: -f3)
  printf 'cpu.max               = %s\n' "$(cat "$CG/cpu.max")"
  printf 'cpuset.cpus.effective = %s\n' "$(cat "$CG/cpuset.cpus.effective")"
  printf 'cpuset.mems.effective = %s\n' "$(cat "$CG/cpuset.mems.effective")"
fi
```

`cpu.max` 가 `max 100000` 이어야 한다. 숫자가 보이면 `--cpus` 가 섞여 들어간 것이므로 고친다. `cpuset.cpus.effective` 를 펼친 집합이 `$CPUSET` 과 정확히 같아야 한다.

스레드 풀이 실제로 줄었는지는 스레드 이름으로 센다. 위 표의 이름이 그대로 집계에 나오므로 이 집계가 바로 판정이 된다. **블로킹 풀은 필요할 때 늘어나므로 유휴 상태의 수는 근거가 되지 않는다. 부하를 건 상태에서 센다.**

```bash
docker exec qdrant-bench sh -c 'cat /proc/1/task/*/comm' \
  | sed 's/-[0-9]*$//' | sort | uniq -c | sort -rn
```

`QDRANT_NUM_CPUS` 판정에는 `search-cpu` 가 17 이하이고 `search-io` 가 65 이하인지만 쓴다. `update` 와 `general` 은 판정에서 뺀다. 두 런타임의 블로킹 풀 상한은 tokio 기본값인 512 라서 부하 중에 16 을 넘는 것이 정상이기 때문이다. **검색 두 풀의 합격선이 위 표의 풀 크기보다 하나씩 큰 데에는 이유가 있다.** tokio 의 `thread_name_fn` 이 블로킹 스레드와 async 워커에 같은 접두사를 붙이는데, `lib/storage/src/content_manager/toc/runtimes.rs` 의 `SEARCH_ASYNC_WORKERS = 1` 이 두 검색 런타임 각각에 async 워커를 하나씩 더 두기 때문이다. 그래서 `QDRANT_NUM_CPUS=16` 인 정상 상태의 최대치가 `search-io` 는 `64 + 1 = 65`, `search-cpu` 는 `16 + 1 = 17` 이 된다. `search-io` 가 수백 개로 나오면 `QDRANT_NUM_CPUS` 가 먹지 않은 것이고, 그 상태의 측정값은 버린다.

이 집계는 `docker exec` 를 쓰므로 4.2절의 금지 항목에 걸린다. **부하 상태에서 한 번만 찍고, 그 사실을 조건 명세에 적는다.** 주기적인 지표 수집에는 쓰지 않는다.

**기존 문서와 어긋나는 점 하나.** `instrumented_build_2026-09-21.md` 7장의 왜곡 검증 명령 두 줄이 `--cpus=16` 을 쓰고 있다. 설계서 4.1절의 코어 고정 결정과 어긋나므로, 남은 왜곡 검증에 들어가기 전에 이 문서의 실행 인자로 바꿔 다시 돌려야 한다. 그대로 두면 CFS 스로틀링이 만든 지연 변동을 계측 왜곡으로 오인할 수 있다.

### 3.3 메모리 한도 128 / 256 / 512GB

설계서 4.2절의 메모리 축 전체가 이 한도 하나에 걸려 있다. 그런데 `docker run --memory` 는 요청일 뿐이고, cgroup 위임이 덜 되어 있거나 다른 컨트롤러가 끼어들면 요청과 실제가 달라진다. 확인 창구를 조건마다 자동으로 통과시키지 않으면, 한도가 안 걸린 조건의 결과를 "메모리를 늘려도 달라지지 않았다"로 잘못 읽게 된다.

`memory.high` 가 함께 걸려 있는 경우도 반드시 배제해야 한다. `memory.high` 는 한도에 닿기 전에 회수 지연을 넣어 스로틀링하므로, 우리가 재려는 지연 꼬리에 원인이 다른 지연이 섞인다.

세 한도의 기대 바이트값은 다음과 같다. Docker 의 `g` 는 GiB 이므로 1024의 세제곱으로 환산한다.

| 조건 | `--memory` | `memory.max` 기대값 |
|---|---|---:|
| 128GB | `128g` | 137438953472 |
| 256GB | `256g` | 274877906944 |
| 512GB | `512g` | 549755813888 |

확인은 호스트에서 컨테이너 cgroup 파일을 직접 읽어서 한다. 한 번에 다섯 값과 `memory.events` 를 본다.

```bash
LIMIT=512g
if ! docker inspect qdrant-bench >/dev/null 2>&1; then
  echo "qdrant-bench 컨테이너가 없다. 5장의 조건 전환 스크립트를 먼저 돌린다."
else
  WANT=$(numfmt --from=iec "${LIMIT%g}G")
  CG=/sys/fs/cgroup$(grep '^0::' "/proc/$(docker inspect -f '{{.State.Pid}}' qdrant-bench)/cgroup" | cut -d: -f3)
  printf 'memory.max      = %s  (기대 %s)\n' "$(cat "$CG/memory.max")" "$WANT"
  printf 'memory.swap.max = %s\n' "$(cat "$CG/memory.swap.max")"
  printf 'memory.high     = %s\n' "$(cat "$CG/memory.high")"
  printf 'memory.current  = %s\n' "$(cat "$CG/memory.current")"
  cat "$CG/memory.events"
fi
```

`memory.max` 가 위 표의 값과 정확히 같고, `memory.swap.max` 가 0이며, `memory.high` 가 `max` 여야 한다. `memory.events` 에 `max` 행과 `oom` 행과 `oom_kill` 행이 모두 존재해야 한다. 값은 0으로 시작한다. 한도를 건 직후의 `memory.current` 는 수십 MiB 수준이어야 하고, 그 값이 이미 크면 앞 조건의 컨테이너가 남아 있거나 cgroup 을 잘못 잡은 것이다.

노드당 메모리가 한도보다 크다는 것을 3.1절에서 확인했을 때만 `--cpuset-mems=$NODE` 를 함께 준다. 노드 용량보다 큰 한도를 노드 하나에 묶으면 할당이 실패하거나 OOM 으로 끝난다.

측정 중에는 `memory.events` 의 `oom` 과 `oom_kill` 을 함께 기록한다. 128GB 조건에서 익명 메모리가 한도를 넘으면 페이지 캐시 회수가 아니라 컨테이너 종료로 끝나는데, 이때 측정은 조용히 실패하지 않고 프로세스가 죽는 형태라 원인을 빨리 특정할 수 있어야 한다.

**메모리 축이 성립했는지의 최종 판정은 세 조건을 모두 돌린 뒤에 한다.** 512GB 조건의 `memory.events` 의 `max` 가 0에 가깝고 128GB 조건의 `max` 가 크게 나와야 한다. 셋 다 0이면 한도가 물리지 않은 것이므로 측정값 전체를 버린다.

### 3.4 스왑 차단은 컨테이너 단위로 끝낸다

설계서 4.3절 대책 4는 "스왑을 차단한다"이고, 준비 문서 3.5절은 압축 스왑인 zswap 이나 zram 이 켜져 있으면 스왑을 꺼도 메모리가 압축되어 남아 실험 전제가 무너진다는 점을 두 번째로 큰 공백으로 지적했다.

이 둘을 한 번에 해소하는 방법이 있다. **cgroup v2 에서 `memory.swap.max` 를 0으로 만들면 그 cgroup 은 스왑 경로 자체에 들어가지 못하므로, 호스트에 zswap 이나 zram 이 켜져 있어도 우리 컨테이너에는 무관하다.** 그러면 호스트 전역 조작이 필요 없어지고, 준비 문서 6.3절의 공용 사용자 합의를 기다리지 않고 이 축을 진행할 수 있다.

컨테이너 단위 차단은 `--memory-swap` 을 `--memory` 와 같은 값으로 주는 것이다. 기법 자체는 `cgroup_trap_check_2026-09-21.md` 4.2절에서 이미 검증되었으므로 여기서는 본 측정용 확인 창구만 적는다.

```bash
if ! docker inspect qdrant-bench >/dev/null 2>&1; then
  echo "qdrant-bench 컨테이너가 없다. 5장의 조건 전환 스크립트를 먼저 돌린다."
else
  CG=/sys/fs/cgroup$(grep '^0::' "/proc/$(docker inspect -f '{{.State.Pid}}' qdrant-bench)/cgroup" | cut -d: -f3)
  cat "$CG/memory.swap.max" "$CG/memory.swap.current"
  cat "$CG/memory.swap.events" 2>/dev/null
  awk '/^(swapcached|zswap|zswapped) /' "$CG/memory.stat"
fi
```

`memory.swap.max` 가 0, `memory.swap.current` 가 0이어야 한다. `memory.stat` 에 `zswapped` 가 있다면 그 값도 0이어야 한다. 측정이 끝난 뒤에도 `memory.swap.current` 가 0이면 그 조건 내내 스왑으로 빠진 페이지가 없었다는 직접 증거가 된다.

호스트 전역 차단과의 차이와 위험은 다음과 같다.

| 방식 | 범위 | 위험 |
|---|---|---|
| `--memory-swap` 을 `--memory` 와 같게 | 우리 컨테이너만 | 없다. 다른 작업에 영향이 없고 되돌릴 것도 없다 |
| `swapoff -a` | 호스트 전체 | 이미 스왑에 나가 있는 페이지를 전부 메모리로 되돌리는 동안 여유 메모리를 급격히 소모해 호스트 전체를 OOM 으로 몰 수 있다. 되돌리는 데 수 분에서 수십 분이 걸리고 그 동안 모든 작업이 느려진다. 공용 서버에서는 합의 없이 쓸 수 없다 |

**`--memory-swappiness` 에 기대지 않는다.** 이 옵션은 cgroup v1 의 `memory.swappiness` 를 겨냥한 것이고 v2 에는 대응하는 per-cgroup 창구가 없다. 차단의 근거는 `memory.swap.max` 가 0이라는 사실 하나로 충분하다.

한 가지 남는 오염 경로가 있다. 호스트 스왑 장치가 `$BENCH` 와 같은 블록 장치에 있으면, 우리 컨테이너가 스왑을 못 쓰더라도 **다른 프로세스의 스왑 입출력이 그 장치 통계에 섞인다.** 준비 문서 5.6절이 이 점을 지적했다. `swapon --show` 로 본 호스트 스왑 장치가 `$BENCH` 와 같은 장치라면 그 사실을 조건 명세에 기록하되, 그것만으로 측정을 중단하지는 않는다. 측정 창 동안 장치 수준 통계와 컨테이너 `io.stat` 을 대조해 오염 여부를 남기는 방법은 6.3절에 있다.

### 3.5 주파수 거버너와 터보와 C-state

준비 문서 3.4절은 거버너와 터보를 기록하라고만 적었다. 이 실험에서는 기록으로 끝낼 수 없는 이유가 있다. **주파수 변동이 독립 변수와 상관되기 때문이다.** 128GB 조건은 512GB 조건보다 회수와 디스크 읽기가 훨씬 많아 커널 CPU 사용과 대기 패턴이 다르고, 344개 중 열여섯 개만 쓰는 구성에서는 터보가 활성 코어 수에 따라 최대 주파수를 바꾼다. 그러면 "메모리를 줄였더니 지연 꼬리가 무너졌다"의 일부가 실제로는 주파수와 C-state 진입 깊이의 차이일 수 있다. 우리가 재려는 것이 바로 지연의 꼬리라서 이 혼입을 그대로 둘 수 없다.

먼저 현재 상태를 기록한다. 이 출력은 조건 명세에 그대로 들어간다.

```bash
if [ -z "${CPUSET:-}" ]; then
  echo "CPUSET 이 비어 있다. 3.1절로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  FIRST=${CPUSET%%,*}
  for f in scaling_governor scaling_driver scaling_cur_freq; do
    printf '%-18s %s\n' "$f" "$(cat "/sys/devices/system/cpu/cpu$FIRST/cpufreq/$f" 2>/dev/null)"
  done
  cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || echo 'intel_pstate 아님'
  cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || echo 'boost 창구 없음'
  cat "/sys/devices/system/cpu/cpu$FIRST/cpuidle/state"*/name 2>/dev/null | paste -sd, -
fi
```

거버너와 드라이버와 현재 주파수, 터보 창구의 값, C-state 이름 목록이 나와야 한다.

공용 사용자 합의가 되면 아래 세 가지를 고정한다. 모두 호스트 전역 변경이며 되돌릴 수 있다. **합의 전에는 이 명령들을 쓰지 않고 위의 기록만 한다.**

```bash
# 1. 거버너를 performance 로
sudo cpupower frequency-set -g performance

# 2. 터보를 끈다. 플랫폼에 따라 창구가 다르므로 있는 쪽만 쓴다.
#    쓰기는 sudo tee 로 하므로 존재 여부만 본다. -w 로 보면 이 파일이 보통
#    root 소유 0644 라 일반 사용자에게 거짓이 되어 두 분기를 모두 건너뛴다
if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
  echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
elif [ -f /sys/devices/system/cpu/cpufreq/boost ]; then
  echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost
else
  echo '터보 창구가 없다. 주파수를 측정 중 기록하는 쪽으로 대응한다'
fi
```

세 번째는 C-state 다. 열여섯 코어만 쓰는 구성에서 128GB 조건은 디스크를 기다리며 유휴 시간이 길어지고, 그만큼 깊은 C-state 로 들어갔다 나오는 지연이 꼬리에 더해진다. `/dev/cpu_dma_latency` 를 0으로 잡아 두면 그 진입을 막을 수 있으며, **효과는 그 파일을 연 프로세스가 살아 있는 동안만 유지된다.** 그래서 측정 창 동안만 백그라운드로 띄운다.

```bash
sudo python3 -c "
import struct, signal
f = open('/dev/cpu_dma_latency', 'wb', buffering=0)
f.write(struct.pack('i', 0))
print('cpu_dma_latency=0 유지 중. 이 프로세스를 끝내면 해제된다', flush=True)
signal.pause()
" &
LATENCY_PID=$!
echo "측정이 끝나면 sudo kill $LATENCY_PID 로 해제한다"
```

**`sudo` 를 빼면 해제되지 않는다.** 여기서 `$!` 가 가리키는 것은 python 이 아니라 그것을 띄운 root 소유 `sudo` 프로세스의 PID 이므로, 비root 셸에서 그냥 `kill` 하면 권한 오류로 실패하고 `cpu_dma_latency` 가 0으로 물린 채 남는다. 끊은 뒤에는 `ps -p "$LATENCY_PID"` 가 아무것도 내지 않는 것으로 해제를 확인한다.

고정을 합의받지 못했다면 **측정 중 실제 주파수를 남겨 사후에 보정한다.** 열여섯 코어의 값을 5초마다 기록한다.

```bash
if [ -z "${CPUSET:-}" ] || [ -z "${OUT:-}" ]; then
  echo "CPUSET 또는 OUT 이 비어 있다. 3.1절과 5.3절로 돌아간 뒤 이 블록을 다시 실행한다."
else
  while :; do
    printf '%s' "$(date +%s)"
    for c in $(echo "$CPUSET" | tr ',' ' '); do
      printf ' %s' "$(cat "/sys/devices/system/cpu/cpu$c/cpufreq/scaling_cur_freq" 2>/dev/null)"
    done
    echo
    sleep 5
  done > "$OUT/freq.log" &
  echo "주파수 기록 시작. 끝내려면 kill $!"
fi
```

**합격 기준.** 고정한 경우 세 조건 모두에서 `scaling_governor` 가 `performance` 이고 터보 창구 값이 꺼짐으로 읽혀야 하며, 이 사실이 세 조건의 `manifest.txt` 에 동일하게 남아야 한다. 고정하지 못한 경우 `freq.log` 에서 계산한 열여섯 코어 평균 주파수가 세 조건 사이에서 3% 이내여야 한다. 3% 를 넘으면 지연을 초 단위로 조건 간 비교할 수 없으므로, 거버너 고정을 다시 합의하거나 지연을 사이클 기준으로 환산해 비교한다는 사실을 분석 문서에 적는다. C-state 를 막은 경우 조건 전후로 유지 프로세스가 살아 있었음을 기록하고, 측정이 끝나면 `sudo kill "$LATENCY_PID"` 로 반드시 해제한다.

### 3.6 이 단계가 끝났다는 것을 어떻게 아는가

다음 다섯이 모두 참이면 3장이 끝난 것이다.

1. `$NODE` 를 `$BENCH` 장치의 `numa_node` 에서 읽었고, `$CPUSET` 과 `$SIBLINGS` 를 그 노드에서 정했으며, 3.1절의 합격 기준 네 가지를 통과했다.
2. 512GB 조건을 그 노드 안에서 세울 수 있는지에 대한 답이 나왔고, 그 답을 설계서 4.2절에 반영할지 결정했다.
3. 컨테이너를 한 번 띄워 `cpu.max` 가 `max 100000` 이고 `cpuset.cpus.effective` 가 `$CPUSET` 과 같음을 cgroup 파일로 확인했다.
4. 부하를 건 상태에서 스레드 이름 집계를 찍어 `search-io` 가 65 이하임을 확인했다.
5. 거버너와 터보와 C-state 의 현재 상태를 기록했고, 고정할지 기록만 할지를 정했다.

---

## 4. 데이터 볼륨과 디스크 연결

### 4.1 바인드 마운트로 붙이고 `-v` 를 쓰지 않는다

함정의 실체는 "그 파일 페이지를 누가 먼저 폴트했는가"이므로, 저장소 경로를 호스트 프로세스가 한 번이라도 읽으면 그 조건은 무효가 된다. 따라서 볼륨을 어떻게 붙이느냐보다 **붙인 뒤 호스트가 그 경로에 무엇을 해도 되는지의 규칙이 더 중요하다.** 그 규칙은 4.2절에 있다.

붙이는 방법 자체에는 두 가지 결정이 있다. 첫째, 데이터를 컨테이너의 쓰기 계층에 두지 않는다. overlay2 를 거치게 되어 읽기 경로와 `io.stat` 귀속이 달라지고, 조건마다 컨테이너를 새로 만드는 순간 데이터가 함께 사라진다. 둘째, 바인드 마운트를 쓰되 `-v` 가 아니라 `--mount type=bind` 를 쓴다. `-v` 는 원본 경로가 없으면 디렉터리를 만들어 버려서, 복원이 실패한 상태를 빈 컬렉션으로 조용히 통과시킨다. `--mount` 는 원본이 없으면 실행 자체가 실패한다.

```bash
# 컨테이너 실행 인자
--mount type=bind,source="$BENCH/qdrant/work",target=/qdrant/storage
```

명명 볼륨과 tmpfs 는 쓰지 않는다. 명명 볼륨은 Docker data-root 에 생기므로 준비 문서 5.4절이 정한 장치 분리가 깨진다. 컨테이너 로그도 data-root 에 쌓이므로 크기를 묶어 둔다.

```bash
# 컨테이너 실행 인자
--log-driver=local --log-opt max-size=64m
```

붙인 결과는 아래로 확인한다.

```bash
if ! docker inspect qdrant-bench >/dev/null 2>&1 || [ -z "${BENCH:-}" ]; then
  echo "qdrant-bench 가 없거나 BENCH 가 비어 있다. 5장과 준비 문서 1.3절을 먼저 확인한다."
else
  docker inspect -f '{{json .Mounts}}' qdrant-bench
  findmnt -T "$BENCH/qdrant/work"
  CG=/sys/fs/cgroup$(grep '^0::' "/proc/$(docker inspect -f '{{.State.Pid}}' qdrant-bench)/cgroup" | cut -d: -f3)
  cat "$CG/io.stat"
fi
```

Mounts 의 Type 이 `bind` 이고 Source 가 `$BENCH/qdrant/work` 여야 한다. `findmnt` 가 준비 문서 3.6절에서 확인한 데이터 파일시스템을 가리켜야 한다. `io.stat` 첫 열의 `major:minor` 가 `$BENCH` 가 놓인 파티션이 아니라 그 파티션이 놓인 디스크의 MAJ:MIN 과 같아야 한다. cgroup v2 의 `io.stat` 은 파티션이 아니라 디스크 단위로 집계하기 때문이며, dm/LVM/md 위에 있는 경우는 한 단계 위가 맞는지 확인하지 못했다. 다르면 게이트 C 가 근거를 잃으므로 준비 문서 3.6절의 논리 볼륨 계층 확인으로 돌아간다.

### 4.2 측정 창 동안 호스트가 그 경로에 할 수 있는 일

**기준은 하나다. 파일 데이터 페이지를 폴트하는가.** 폴트하면 그 페이지가 호스트 앞으로 과금되고, 그 순간 조건이 무효가 된다.

| 허용 | 이유 |
|---|---|
| `stat`, `ls`, `du`, `find`, `findmnt` | 메타데이터만 읽고 파일 데이터 페이지를 건드리지 않는다 |
| `fincore` | `mincore` 로 잔류 여부만 묻는다. 페이지를 불러오지 않는다 |

| 금지 | 결과 |
|---|---|
| `cat`, `grep`, `md5sum`, `tar`, `rsync`, `cp` | 호스트 앞으로 과금되어 그 조건이 무효가 된다 |
| `fio`, 백업 에이전트, `updatedb` | 같다. 주기 작업은 6.3절에서 미리 막는다 |
| `docker exec` 로 하는 반복 지표 수집 | exec 한 프로세스가 컨테이너 cgroup 에 들어가므로 그 메모리와 CPU 가 측정 대상 앞으로 과금된다. 지표는 호스트에서 cgroup 파일을 직접 읽는다 |

마스터에서 작업본을 되살리는 `cp` 는 이 금지의 예외가 아니다. **복원 국면에만 허용되고 반드시 뒤에 캐시 비우기와 게이트 A 가 따라붙는다.** 상세는 5.3절의 2단계부터 4단계까지에 있다.

### 4.3 네트워크 연결 방식을 하나로 고정한다

`-p 6333:6333` 으로 공개하면 루프백 경로에 NAT 와 경우에 따라 docker-proxy 가 끼어들어 요청마다 변동이 더해지고, 그 변동이 우리가 재는 지연 안에 들어온다. `--network=host` 로 두면 그 경로가 사라진다. 어느 쪽을 택하든 세 조건에서 같아야 하며, 택한 값을 조건 명세에 남긴다. 이 문서의 스크립트는 `--network=host` 를 기본으로 쓴다.

`--network=host` 를 쓰면 포트가 호스트에 그대로 노출되므로, 준비 문서 3.8절에서 6333과 6334 포트가 비어 있음을 확인한 상태여야 한다.

### 4.4 이 단계가 끝났다는 것을 어떻게 아는가

다음 넷이 모두 참이면 4장이 끝난 것이다. 첫째, `docker inspect` 의 Mounts 가 bind 이고 Source 가 `$BENCH/qdrant/work` 다. 둘째, `findmnt -T` 가 준비 문서 3.6절의 데이터 파일시스템을 가리킨다. 셋째, 컨테이너 `io.stat` 의 첫 열이 `$BENCH` 의 파티션이 아니라 그 파티션이 놓인 디스크의 MAJ:MIN 과 같다. 넷째, 4.2절의 허용과 금지 목록을 측정에 참여하는 사람이 모두 읽었고, 네트워크 방식을 하나로 정해 조건 명세 양식에 적어 두었다.

---

## 5. 조건 전환 절차

**이 장이 이 문서의 핵심이다.**

### 5.1 왜 한 묶음이어야 하는가

함정이 실재하는 것으로 확인된 이상, 조건 하나를 세우는 일은 "한도를 바꾼다"가 아니라 **폐기와 복원과 캐시 비우기와 재생성과 검증을 순서대로 빠짐없이 수행하는 일**이 되었다.

손으로 하면 순서 하나를 건너뛴 조건이 섞여 들어가고, **그 조건은 결과를 보고도 무효인지 알 수 없다.** 함정 검증에서 관측된 조건 A 가 정확히 그 모습이었다. 한도를 4GB 로 걸었는데도 디스크를 한 번도 읽지 않았고, 한도에 한 번도 부딪히지 않았으며, 자기 앞으로 과금된 양이 한도의 400분의 1에 그쳤다. 결과만 보면 "메모리가 넉넉해서 디스크를 안 읽었다"로 읽힌다.

그래서 순서를 스크립트로 묶고 각 단계마다 통과 조건을 두어, 조건이 제대로 서지 않으면 아예 측정에 들어가지 못하게 만든다.

### 5.2 대책 네 가지가 절차 어디에 들어가고, 어기면 어떻게 드러나는가

설계서 4.3절의 대책 네 가지가 스크립트의 어느 단계에 녹아 있는지와, 그것을 어겼을 때 어느 지표에 나타나는지를 한 표로 둔다.

| 대책 | 스크립트 단계 | 어기면 어디에 나타나나 |
|---|---|---|
| 1. 조건을 바꿀 때마다 컨테이너를 새로 만든다 | 1단계 폐기, 5단계 재생성 | 직전 조건이 올린 캐시가 남아 새 한도가 물리지 않는다. `memory.events` 의 `max` 가 세 조건 모두 0으로 나온다 |
| 2. 새로 만들기 직전에 시스템 캐시를 비운다 | 3단계 `drop_caches`, 4단계 게이트 A | 게이트 A 에서 잔류 바이트가 작업본의 1% 를 넘어 멈춘다. 통과시키면 게이트 C 에서 `rbytes` 가 0에 가깝게 나온다 |
| 3. 부하 도구가 데이터 파일을 직접 만지지 않는다 | 4.2절의 금지 목록, 6.3절의 측정 창 보호 | 게이트 C 의 `rbytes` 가 작업본 크기에 못 미친다. 그만큼이 호스트나 부하 도구 앞으로 갔다는 뜻이다 |
| 4. 스왑을 차단한다 | 5단계 `--memory-swap`, 6단계 게이트 B | 게이트 B 가 보는 `memory.swap.max` 가 0이 아니어서 그 자리에서 멈춘다. 멈추지 않고 통과시키면 측정 중 `memory.swap.current` 가 0보다 커지고, 그 조건의 디스크 읽기량이 실제보다 작게 나온다 |

표의 오른쪽 열이 이 절차의 설계 의도를 그대로 보여 준다. **네 대책 모두 어겼을 때 측정이 멈추는 것이 아니라 값이 조용히 달라진다.** 그래서 게이트가 필요하다.

### 5.3 `run_condition.sh` — 조건 하나를 세우는 스크립트

아래 블록을 그대로 붙여 넣어 스크립트를 만든다. 바깥 블록은 대화형 셸에서 돌아가므로 `exit` 를 쓰지 않고 안내만 한다. 만들어지는 스크립트 자체는 별도 프로세스로 실행되므로 그 안에서는 `exit` 를 써도 로그인 셸에 영향이 없다.

```bash
if [ -z "${RAW:-}" ]; then
  echo "RAW 이 비어 있다. preparation_2026-09-21.md 1.3절의 export 줄로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  mkdir -p "$RAW/bin"
  cat > "$RAW/bin/run_condition.sh" <<'SH'
#!/usr/bin/env bash
# 조건 하나를 세운다. 폐기, 복원, 캐시 비우기, 과금 백지 확인, 재생성,
# 한도 확인, 적재 과금 확인까지가 한 묶음이다. 어느 하나라도 어긋나면 멈춘다.
set -euo pipefail

: "${RAW:?RAW 가 비어 있다}"
: "${BENCH:?BENCH 가 비어 있다}"
: "${CPUSET:?CPUSET 이 비어 있다}"
: "${LIMIT:?LIMIT 이 비어 있다}"
NAME=${NAME:-qdrant-bench}
IMG=${IMG:-qdrant:1.19.1-stagetiming}
NODE=${NODE:-}
RELOAD=${RELOAD:-copy}
WORK="$BENCH/qdrant/work"
MASTER="$BENCH/qdrant/master"
# 산출물은 $RAW 에 쓴다. $BENCH 는 Qdrant 저장소 전용이며, 항목 11 판정이
# $BENCH 장치의 읽기량을 보는 일이라 여기에 쓰면 판정에 직접 섞인다. 6.2절을 본다
OUT=${OUT:-$RAW/conditions/$(date +%Y%m%d-%H%M%S)-$LIMIT}
mkdir -p "$OUT"

log()  { printf '\n== %s\n' "$*" | tee -a "$OUT/condition.log"; }
note() { printf '   %s\n' "$*" | tee -a "$OUT/condition.log"; }
fail() { printf '\n[중단] %s\n' "$*" | tee -a "$OUT/condition.log"; exit 1; }
gib()  { awk -v v="$1" 'BEGIN{printf "%.2f", v/1073741824}'; }
cg_of(){ echo "/sys/fs/cgroup$(grep '^0::' "/proc/$(docker inspect -f '{{.State.Pid}}' "$1")/cgroup" | cut -d: -f3)"; }
# io.stat 은 장치마다 한 줄이고 컨테이너는 루트 오버레이 장치 줄도 갖는다.
# 전부 더하면 게이트 C 가 다른 장치의 읽기까지 세어 무효 조건을 통과시키므로
# $BENCH 의 major:minor 줄만 본다
rbytes(){ awk -v d="$IODEV" '$1==d{for(i=2;i<=NF;i++) if($i ~ /^rbytes=/){split($i,a,"="); s+=a[2]}} END{printf "%.0f\n", s}' "$1/io.stat"; }
resident(){ find "$1" -type f -print0 | xargs -0 -r fincore -b --noheadings --output RES 2>/dev/null \
              | awk '{s+=$1} END{printf "%.0f\n", s}'; }
expand(){ tr ',' '\n' | awk -F- '{ if (NF==2) for(i=$1;i<=$2;i++) print i; else print $1 }' | sort -n -u | paste -sd, -; }

[ "$(id -u)" -eq 0 ] || fail "drop_caches 에 root 가 필요하다. sudo 로 다시 실행한다."
command -v fincore >/dev/null || fail "fincore 가 없다. util-linux-extra 를 설치하거나 게이트 A 대체 수단을 쓴다."

if [ -z "${IODEV:-}" ]; then
    # cgroup v2 io.stat 은 파티션이 아니라 디스크(request_queue) 단위로 집계하므로
    # $BENCH 가 파티션 위에 있으면 파티션이 아니라 부모 디스크의 MAJ:MIN 을 쓴다.
    # dm/LVM/md 위에 있는 경우 한 단계 위가 맞는지는 미확인이다
    SRC=$(findmnt -T "$BENCH" -no SOURCE 2>/dev/null || true)      # -T 는 마운트 지점 아래 경로도 받는다
    PK=$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1 || true)
    DISK=${PK:-$(basename "$SRC")}                                   # 파티션이면 부모 디스크, 통짜 디스크면 자기 자신
    IODEV=$(lsblk -dno MAJ:MIN "/dev/$DISK" 2>/dev/null | tr -d ' ' || true)
fi
[ -n "$IODEV" ] || fail "\$BENCH 의 블록 장치 번호를 찾지 못했다. 수집 문서 11.1절로 IODEV 를 정해 넘긴 뒤 다시 실행한다."
note "io.stat 에서 볼 장치 = $IODEV"

log "1. 앞 조건 폐기"
docker rm -f "$NAME" >/dev/null 2>&1 || true
for _ in $(seq 60); do docker ps -a --format '{{.Names}}' | grep -qx "$NAME" || break; sleep 1; done
docker ps -a --format '{{.Names}}' | grep -qx "$NAME" && fail "앞 조건 컨테이너가 사라지지 않았다."

log "2. 작업본 복원 (방식 $RELOAD)"
if [ "$RELOAD" = copy ]; then
    # 마스터는 copy 경로에서만 필요하다. 바깥에서 막으면 RELOAD=ingest 로도 못 돈다
    [ -d "$MASTER" ] || fail "마스터 사본이 없다: $MASTER. RELOAD=ingest 로는 마스터 없이 돌 수 있다."
    [ -n "$WORK" ] || fail "WORK 가 비어 있다."
    rm -rf -- "$WORK"
    mkdir -p "$WORK"
    time cp -a --reflink=never "$MASTER/." "$WORK/"
    [ "$(du -sb "$WORK" | cut -f1)" = "$(du -sb "$MASTER" | cut -f1)" ] || fail "복원 크기가 마스터와 다르다."
else
    note "에뮬레이터가 적재할 빈 저장소를 만든다"
    [ -n "$WORK" ] || fail "WORK 가 비어 있다."
    rm -rf -- "$WORK"; mkdir -p "$WORK"
fi
SIZE=$(du -sb "$WORK" | cut -f1)
note "작업본 $(gib "$SIZE") GiB"

log "3. 페이지 캐시 비우기"
sync; echo 3 > /proc/sys/vm/drop_caches; sleep 2

log "4. 게이트 A — 작업본이 캐시에 남아 있지 않은가"
RES=$(resident "$WORK") || fail "fincore 로 캐시 잔류를 재지 못했다. 게이트 A 를 판정할 수 없으므로 멈춘다."
note "캐시 잔류 $(gib "$RES") GiB"
if [ "$SIZE" -gt 0 ]; then
  [ "$(awk -v r="$RES" -v s="$SIZE" 'BEGIN{print (r*100<=s)?1:0}')" -eq 1 ] \
    || fail "작업본이 캐시에 1% 넘게 남아 있다. 호스트에서 그 경로를 읽는 작업을 찾아 멈춘 뒤 다시 실행한다."
fi

log "5. 컨테이너 재생성 (한도 $LIMIT, 코어 $CPUSET)"
MEMS=""; [ -n "$NODE" ] && MEMS="--cpuset-mems=$NODE"
# shellcheck disable=SC2086
docker run -d --name "$NAME" \
  --cpuset-cpus="$CPUSET" $MEMS \
  --memory="$LIMIT" --memory-swap="$LIMIT" \
  --ulimit nofile=65535:65535 \
  --log-driver=local --log-opt max-size=64m \
  -e QDRANT_NUM_CPUS="$(echo "$CPUSET" | expand | tr ',' '\n' | wc -l)" \
  --mount type=bind,source="$WORK",target=/qdrant/storage \
  --network=host "$IMG" >/dev/null
CG=$(cg_of "$NAME"); [ -d "$CG" ] || fail "컨테이너 cgroup 을 찾지 못했다: $CG"

log "6. 게이트 B — 한도가 실제로 물렸는가"
WANT=$(numfmt --from=iec "${LIMIT%g}G")
{ printf 'memory.max=%s\nmemory.swap.max=%s\nmemory.high=%s\ncpu.max=%s\ncpuset.cpus.effective=%s\ncpuset.mems.effective=%s\n' \
    "$(cat "$CG/memory.max")" "$(cat "$CG/memory.swap.max")" "$(cat "$CG/memory.high")" \
    "$(cat "$CG/cpu.max")" "$(cat "$CG/cpuset.cpus.effective")" "$(cat "$CG/cpuset.mems.effective")"; } \
  | tee "$OUT/limits.txt"
[ "$(cat "$CG/memory.max")" = "$WANT" ]  || fail "memory.max 가 $WANT 이 아니다."
[ "$(cat "$CG/memory.swap.max")" = 0 ]   || fail "스왑이 열려 있다."
[ "$(cat "$CG/memory.high")" = max ]     || fail "memory.high 가 걸려 있어 한도의 의미가 달라진다."
[ "$(cat "$CG/cpu.max")" = "max 100000" ] || fail "cpu.max 가 걸려 있다. --cpus 계열을 빼고 cpuset 만 쓴다."
[ "$(echo "$CPUSET" | expand)" = "$(cat "$CG/cpuset.cpus.effective" | expand)" ] || fail "cpuset 이 요청과 다르다."

log "7. 기동과 mmap 예열 완료 대기"
for _ in $(seq 900); do curl -sf localhost:6333/readyz >/dev/null 2>&1 && break; sleep 2; done
curl -sf localhost:6333/readyz >/dev/null 2>&1 || fail "기동하지 못했다. docker logs $NAME 을 본다."
STABLE=0; LAST=$(rbytes "$CG")
for _ in $(seq 720); do
  sleep 10; NOW=$(rbytes "$CG")
  if [ "$(( NOW - LAST ))" -lt 67108864 ]; then STABLE=$((STABLE+1)); else STABLE=0; fi
  LAST=$NOW; [ "$STABLE" -ge 2 ] && break
done
note "예열 후 누적 디스크 읽기 $(gib "$LAST") GiB"

log "8. 게이트 C — 적재가 컨테이너 앞으로 과금되었는가"
RB=$(rbytes "$CG"); MC=$(cat "$CG/memory.current")
EXP=$(awk -v s="$SIZE" -v l="$WANT" 'BEGIN{print (s<l)?s:l}')
note "작업본 $(gib "$SIZE") / 디스크 읽기 $(gib "$RB") / memory.current $(gib "$MC") (기대 $(gib "$EXP") 이상)"
if [ "$RELOAD" = copy ]; then
  [ "$(awk -v r="$RB" -v s="$SIZE" 'BEGIN{print (r>=s*0.9)?1:0}')" -eq 1 ] \
    || fail "컨테이너가 디스크를 충분히 읽지 않았다. 호스트가 먼저 읽은 상태이며 이 조건은 무효다."
  [ "$(awk -v m="$MC" -v e="$EXP" 'BEGIN{print (m>=e*0.9)?1:0}')" -eq 1 ] \
    || fail "컨테이너 앞으로 과금된 양이 기대에 못 미친다."
fi
awk '/^max /{print "   한도 도달 횟수 =", $2}' "$CG/memory.events" | tee -a "$OUT/condition.log"
grep -E '^(oom|oom_kill) ' "$CG/memory.events" | tee -a "$OUT/condition.log" \
  || note "memory.events 에 oom 행이 없다. 커널 판이 다른 것이므로 OOM 판정 창구를 다시 정한다."

log "9. 조건 명세와 계수기 기준점 기록"
{ echo "date=$(date -Is)"; echo "limit=$LIMIT"; echo "cpuset=$CPUSET"; echo "node=$NODE";
  echo "image=$IMG"; echo "reload=$RELOAD"; echo "work_bytes=$SIZE";
  echo "governor=$(cat /sys/devices/system/cpu/cpu${CPUSET%%,*}/cpufreq/scaling_governor 2>/dev/null)";
  echo "thp=$(cat /sys/kernel/mm/transparent_hugepage/enabled)";
  sysctl vm.swappiness vm.dirty_ratio vm.min_free_kbytes vm.vfs_cache_pressure vm.max_map_count; } \
  > "$OUT/manifest.txt"
cp "$CG/memory.stat" "$OUT/memory.stat.t0"
cp "$CG/io.stat"     "$OUT/io.stat.t0"
curl -s -X POST localhost:6333/stage_timings/reset >/dev/null 2>&1 || true
log "조건이 섰다. 기록 위치 $OUT"
SH
  chmod +x "$RAW/bin/run_condition.sh"
  echo "작성 완료: $RAW/bin/run_condition.sh"
fi
```

아홉 단계가 하는 일을 순서대로 적으면 다음과 같다.

| 단계 | 하는 일 | 왜 이 자리인가 |
|---|---|---|
| 1 | 앞 조건 컨테이너를 지우고 사라질 때까지 기다린다 | 대책 1. 지워지기 전에 다음 단계로 가면 cgroup 이 겹친다 |
| 2 | 마스터에서 작업본을 복원하거나 빈 저장소를 만든다 | 준비 문서 5.7절. 조건마다 같은 시작 상태를 만든다 |
| 3 | 페이지 캐시를 비운다 | 대책 2. 복사가 호스트 앞으로 올린 페이지를 여기서 없앤다 |
| 4 | 게이트 A. 작업본이 캐시에 남아 있지 않은지 경로 단위로 묻는다 | 3단계가 실제로 들었는지를 증명한다 |
| 5 | 컨테이너를 만든다. 한도, cpuset, 스왑 차단, 스레드 수, 마운트, 로그 한도를 모두 여기서 건다 | 대책 1과 4 |
| 6 | 게이트 B. 한도와 cpuset 이 물렸는지 cgroup 파일로 확인한다 | 요청과 실제가 다를 수 있다 |
| 7 | 기동과 mmap 예열이 끝날 때까지 기다린다 | 예열 중에 측정을 시작하면 부하 구간에 예열 읽기가 섞인다 |
| 8 | 게이트 C. 그 데이터가 컨테이너 앞으로 과금되었는지 증명한다 | 대책 2와 3이 실제로 지켜졌는지의 최종 확인 |
| 9 | 조건 명세와 계수기 기준점을 남기고 계측을 초기화한다 | 조건 간 비교가 성립하는지를 사후에 확인할 수 있게 한다 |

7단계의 예열 대기는 "10초 동안 디스크 읽기 증가가 64MiB 미만인 상태가 두 번 연속"으로 판정한다. **이 임계값은 실측이 아니라 임의로 정한 값이다.** 첫 조건을 돌리면서 실제 예열 곡선을 보고 고쳐야 한다.

### 5.4 세 조건을 도는 방법

한 조건이 서면 부하를 걸고 지표를 수집한 뒤 다음 조건으로 넘어간다. **큰 한도부터 도는 것이 좋다.** 512GB 조건이 기준선이므로 그것이 먼저 서야 뒤 조건의 값을 비교할 대상이 생기고, 128GB 조건에서 OOM 이 나면 그 시점에 앞 두 조건의 값은 이미 손에 있다.

```bash
if [ -z "${RAW:-}" ] || [ -z "${BENCH:-}" ] || [ -z "${CPUSET:-}" ]; then
  echo "RAW, BENCH, CPUSET 중 비어 있는 것이 있다. 2.3절과 3.1절로 돌아간 뒤 다시 실행한다."
else
  for L in 512g 256g 128g; do
    sudo RAW="$RAW" BENCH="$BENCH" CPUSET="$CPUSET" NODE="${NODE:-}" LIMIT="$L" \
      "$RAW/bin/run_condition.sh"
    # 여기서부터는 새 구조 3.4 제어기의 몫이다. 아래 표를 본다
  done
fi
```

조건 사이에 사람이 개입해야 하므로 실제로는 한 줄씩 나누어 돌리는 편이 낫다. 위 반복문은 순서를 보여 주는 용도이며, 본 측정에서는 이 호출 자체를 제어기가 한다.

**`run_condition.sh` 이 9단계를 마치고 "조건이 섰다"를 출력하는 자리가 책임 경계다.** 여기까지가 이 문서의 몫이다. 그 뒤의 일, 곧 적재기 호출과 부하기 호출과 구간 경계 스냅샷과 저장 부하 뒤의 마스터 복원은 **새 구조 3.4 제어기**가 하며, 제어기는 부하 도구의 산출물이다. 구조와 명령행 계약은 `emulator_spec_2026-09-21.md` 4.1절과 4.2절에 있다. 부하 도구 문서 4.1절이 "제어기는 환경 구축의 산출물이고 그 실체는 `run_condition.sh` 다"라고 적었고 이 문서가 "그 뒤는 부하 도구 문서의 제어기가 한다"고 적어 서로 상대 것이라 하던 것을 이렇게 정리한다. `run_condition.sh` 는 제어기가 조건마다 `sudo` 로 호출하는 부품이지 제어기가 아니며, "조건이 섰다"가 찍히지 않은 조건에는 제어기가 부하를 걸지 않는다.

경계가 두 문서 어디에도 없으면 부하가 걸리기 전에 해야 할 확인이 통째로 빠지므로, 제어기가 조건 하나당 지는 의무 네 가지를 여기에 받아 적는다. 소유는 부하 도구이고, 이 표는 환경 쪽이 제어기에 기대하는 것을 적은 것이다. 근거는 모두 `emulator_spec_2026-09-21.md` 에 있고 이 문서가 새로 정하는 것은 없다.

| 순서 | 제어기가 하는 일 | 근거 | 빠지면 어떻게 되나 |
|---|---|---|---|
| 1 | 마스터가 없어 `RELOAD=ingest` 로 세운 조건에서는 `loader load` 뒤에 `loader verify` 를 부르고, 마스터가 없을 때 한 번만 `loader master` 로 마스터 사본을 뜬 뒤 `RELOAD=copy` 로 조건을 다시 세운다. `RELOAD=copy` 조건에서는 스크립트 2단계의 복사가 적재를 대신하므로 `loader load` 는 부르지 않되, 복원된 작업본이 수집 문서 6.2절의 네 조건을 만족하는지를 관리 창구로 확인하는 `loader verify`(읽기 전용 확인)는 부른다. 세 명령 모두 새 구조 3.2 적재기의 몫이다. 어느 쪽이든 부하를 걸기 직전에 적재기 프로세스가 남아 있지 않은지 확인하고, 아직 돌고 있으면 끝날 때까지 기다린다 | 부하 도구 문서 4.1절, 4.5절, 4.7절 | 적재기 프로세스가 데이터 파일을 읽어 페이지 캐시를 자기 앞으로 과금하므로 함정이 그대로 재발한다 |
| 2 | 질의 파일을 읽어 부하기 컨테이너의 표준 입력으로 흘려 넣는다 | 부하 도구 문서 5.4절 | 부하기가 직접 파일을 열게 되어 4.2절의 데이터 파일 접근 금지와 설계서 4.3절 대책 3을 깬다 |
| 3 | 동시 요청 수 사다리를 제어기가 돈다. 단마다 `driver run` 을 한 번씩 부르고, 호출 사이에 구간 경계 스냅샷을 찍는다 | 부하 도구 문서 6.4절, 수집 문서 6.4절 | 부하기는 계측 창구를 읽지 않으므로 단 경계의 누적값을 아무도 찍지 않아 단별로 구간을 가를 수 없다 |
| 4 | 저장 부하가 섞인 실행이 끝나면 준비 문서 5.7절의 마스터 복원을 수행한다 | 부하 도구 문서 5.3절 | 저장 부하가 넣은 포인트가 작업본에 남아 다음 실행의 데이터가 앞 실행과 달라진다 |

3번의 사다리는 Qdrant 컨테이너를 그대로 둔 채 부하기 프로세스만 단마다 새로 띄운다. 컨테이너를 다시 만드는 것은 메모리 한도를 바꿀 때뿐이며, 그때 제어기가 다시 `run_condition.sh` 부터 부른다. 4번의 복원을 한 뒤에는 작업본이 바뀌었으므로 게이트 A 와 게이트 C 를 다시 통과해야 하고, 그것도 제어기가 `run_condition.sh` 를 다시 부르는 것으로 한다. 복원 자체가 스크립트의 2단계이므로 제어기가 따로 복사할 것은 없다.

### 5.5 복원 방식 두 가지와 그 선택

`RELOAD=copy` 는 준비 문서 5.7절의 마스터 복사를 쓰고, `RELOAD=ingest` 는 빈 저장소를 만들어 에뮬레이터가 적재하게 한다. **두 경로 모두 지켜야 하는 불변식은 같다. 컨테이너가 데이터 페이지를 처음 만지는 주체여야 한다.**

`ingest` 는 컨테이너가 직접 쓰므로 그 불변식이 자동으로 성립한다. `copy` 는 호스트가 복사하므로 성립이 자동이 아니고, 3단계의 캐시 비우기와 4단계의 게이트 A, 8단계의 게이트 C 를 모두 통과해야만 성립한다. 게이트가 그 성립을 조건마다 증명하므로, **통과하는 한 `copy` 를 쓰는 것이 옳다.** 385.52GB 복사는 1GB/s 기준 약 6분 26초인 반면 1억 개 적재는 그보다 훨씬 오래 걸린다. 이 두 값은 준비 문서 5.7절에서 가져온 것이다.

`copy` 가 성립한다는 판단의 근거는 Qdrant v1.19.1 소스에 있다. `lib/common/common/src/low_memory.rs` 의 `LowMemoryMode` 기본값이 `Disabled` 이고, mmap 예열을 건너뛰게 하는 `skip_populate()` 는 `NoPopulate` 일 때만 참이다. 즉 **기본 설정에서는 기동 시 원본 벡터와 HNSW 그래프와 payload 저장소에 대해 mmap 예열이 돌아 컨테이너 자신이 전 페이지를 폴트한다.** 그래서 마스터에서 복사한 작업본이라도 컨테이너가 처음 만지는 주체가 되고, 그 사실이 계수기로 그대로 드러난다. 다만 이 동작을 실물 서버에서 확인하지 못했으므로 게이트 C 가 매 조건마다 증명하게 했다.

게이트가 실패한 조건은 측정에 쓰지 않는다. `RELOAD=ingest` 는 마스터가 없을 때 마스터를 다시 뜨는 용도이며, 측정은 게이트를 통과한 `copy` 조건에서만 한다(부하 도구 문서 4.7절).

**원칙과 방법을 확정한다.** 조건마다 지켜야 하는 원칙은 "컨테이너가 데이터를 처음 만져야 한다"이고, 방법은 마스터 사본을 복사하는 것이다. 이 스크립트에서는 호스트가 복사한 뒤 3단계의 캐시 비우기와 4단계의 게이트 A 로 복사가 올린 페이지를 없애고, 7단계의 mmap 예열로 컨테이너가 그 페이지를 처음 만지게 하며, 8단계의 게이트 C 가 그 사실을 증명한다. 재적재는 수 시간이 들고 복사는 약 6분이다(385.52GB 를 1GB/s 로 복사해 6분 26초, 준비 문서 5.7절). 재적재는 마스터가 없을 때의 대안일 뿐이며, 마스터 사본은 새 구조 3.2 적재기가 적재를 마친 직후 만든다. `cgroup_trap_check_2026-09-21.md` 7.1절과 설계서 4.6.1절의 "조건마다 적재를 다시 해야 한다"는 서술은 틀린 것으로 확정되었고, 두 문서는 이미 이 원칙으로 고쳐졌다.

### 5.6 게이트 A — 컨테이너를 만들기 직전

**묻는 것.** 작업본이 페이지 캐시에 남아 있지 않은가.

함정 검증에 없던 조건이 본 측정에 하나 더 있다. 조건을 세우기 전에 "작업본이 정말로 캐시에서 비워졌는가"를 확인해야 하는데, **전역 `Cached` 값은 1TB 장비에서 다른 작업의 캐시에 묻혀 판정 근거가 되지 못한다.** 그래서 경로 단위로 잔류를 직접 묻는다.

`fincore` 는 `mincore` 로 파일별 상주 바이트만 묻고 페이지를 불러오지 않으므로, 이 확인 자체가 캐시를 오염시키지 않는다.

```bash
if [ -z "${BENCH:-}" ]; then
  echo "BENCH 가 비어 있다. preparation_2026-09-21.md 1.3절로 돌아간 뒤 다시 실행한다."
else
  find "$BENCH/qdrant/work" -type f -print0 \
    | xargs -0 -r fincore -b --noheadings --output RES,SIZE,FILE \
    | awk '{r+=$1; s+=$2} END{printf "잔류 %.2f GiB / 전체 %.2f GiB\n", r/2^30, s/2^30}'
fi
```

한 줄이 나오고 잔류가 전체의 1% 이하여야 한다. 이상적인 값은 0이며, 0이 아니라면 그 순간 그 경로를 읽고 있는 호스트 작업이 있다는 뜻이므로 찾아서 멈춘다.

### 5.7 게이트 C — 적재와 예열이 끝난 뒤

**묻는 것.** 그 데이터가 컨테이너 앞으로 과금되었는가.

```bash
if ! docker inspect qdrant-bench >/dev/null 2>&1 || [ -z "${BENCH:-}" ] || [ -z "${COLL:-}" ]; then
  echo "qdrant-bench 가 없거나 BENCH 또는 COLL 이 비어 있다. BENCH 는 준비 문서 1.3절, COLL 은 수집 문서 11.1절, 컨테이너는 5.3절을 본다."
else
  CG=/sys/fs/cgroup$(grep '^0::' "/proc/$(docker inspect -f '{{.State.Pid}}' qdrant-bench)/cgroup" | cut -d: -f3)
  SIZE=$(du -sb "$BENCH/qdrant/work" | cut -f1)
  # io.stat 은 장치마다 한 줄이므로 $BENCH 의 major:minor 줄만 센다.
  # 전부 더하면 루트 오버레이 장치의 읽기까지 섞여 판정이 느슨해진다.
  # cgroup v2 io.stat 은 파티션이 아니라 디스크 단위로 집계하므로 부모 디스크의 MAJ:MIN 을 쓴다
  SRC=$(findmnt -T "$BENCH" -no SOURCE)
  PK=$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1)
  DISK=${PK:-$(basename "$SRC")}
  IODEV=$(lsblk -dno MAJ:MIN "/dev/$DISK" | tr -d ' ')
  echo "io.stat 에서 볼 장치 = $IODEV"
  awk -v d="$IODEV" '$1==d{for(i=2;i<=NF;i++) if($i ~ /^rbytes=/){split($i,a,"="); s+=a[2]}} END{printf "디스크 읽기 %.2f GiB\n", s/2^30}' "$CG/io.stat"
  awk -v s="$SIZE" '{printf "memory.current %.2f GiB (작업본 %.2f GiB)\n", $1/2^30, s/2^30}' "$CG/memory.current"
  awk '/^(max|oom|oom_kill) /' "$CG/memory.events"
  grep -E '^(file|pgmajfault|workingset_refault_file) ' "$CG/memory.stat"
  curl -s "localhost:6333/collections/$COLL/memory" | python3 -m json.tool
fi
```

마지막 줄은 Qdrant 자신의 관점으로 하는 교차 확인이다. `lib/collection/src/common/memory_reporter.rs` 가 `cached_bytes` 와 `expected_cache_bytes` 를 내놓으므로, cgroup 이 보는 값과 Qdrant 가 보는 값이 같은 방향을 가리키는지 볼 수 있다.

판정선은 다음과 같다.

| 지표 | 합격 | 어긋날 때의 의미 |
|---|---|---|
| 컨테이너 `io.stat` 의 `rbytes` | 작업본 크기의 90% 이상 | 0에 가까우면 호스트가 먼저 읽은 것이다. 함정에 빠졌다 |
| `memory.current` | `min(작업본, 한도)` 의 90% 이상 | 한참 못 미치면 과금이 다른 cgroup 앞으로 갔다 |
| `memory.events` 의 `max` | 512GB 조건은 0에 가깝고 128GB 조건은 크다 | 셋 다 0이면 한도가 물리지 않았다 |
| `memory.events` 의 `oom_kill` | 0 | 0이 아니면 익명 메모리가 한도를 넘은 것이므로 결과가 아니라 실패다 |
| `memory.stat` 의 `workingset_refault_file` | 128GB 조건에서 크게 증가 | 한도가 실제로 회수를 일으켰다는 가장 직접적인 증거다 |

**읽기 소요 시간은 어느 게이트에도 넣지 않는다.** 함정 검증에서 나온 초당 7.6GB 는 디스크 속도가 아니라 단일 스레드 `dd` 의 메모리 복사가 병목이라는 뜻이고, 캐시에서 읽은 조건이 오히려 근소하게 더 느렸다. 그래서 이 서버에서는 캐시 적중과 디스크 읽기를 시간으로 구분할 수 없다. 근거는 `cgroup_trap_check_2026-09-21.md` 6.1절에 있다.

게이트 C 가 실패한 조건의 측정값은 기록만 남기고 분석에 쓰지 않는다.

### 5.8 이 단계가 끝났다는 것을 어떻게 아는가

스크립트가 9단계를 모두 지나 "조건이 섰다"를 출력하고, `$OUT` 에 `condition.log` 와 `limits.txt` 와 `manifest.txt` 와 `memory.stat.t0` 와 `io.stat.t0` 다섯 파일이 남아야 한다. 어느 게이트에서든 멈추면 그 조건의 측정에 들어가지 않는다.

세 조건을 모두 세운 뒤에는 `manifest.txt` 를 서로 비교한다.

```bash
if [ -z "${RAW:-}" ]; then
  echo "RAW 이 비어 있다. preparation_2026-09-21.md 1.3절로 돌아간 뒤 다시 실행한다."
else
  ls -d "$RAW/conditions/"*/ 2>/dev/null
  echo "위 목록에서 두 조건의 manifest.txt 를 골라 diff 로 비교한다"
fi
```

`limit` 과 `date` 와 `work_bytes` 외에는 차이가 없어야 한다. 차이가 더 있으면 조건이 메모리 말고도 달라진 것이므로 그 비교는 성립하지 않는다.

그리고 세 조건의 `memory.events` 의 `max` 가 512GB 에서 128GB 로 갈수록 단조 증가하고 `workingset_refault_file` 도 같은 방향으로 커져야 메모리 축이 실제로 작동한 것이다.

---

## 6. 지표 수집 체계

### 6.1 수집 계획은 별도 문서에 있다

설계서 2부의 측정 항목 11개를 어느 창구에서 어떤 주기로 읽고 어떻게 구간을 갈라 저장하는지는 `metrics_collection_2026-09-21.md` 에 있다. 동반 스크립트도 같은 디렉터리에 있다. 여기서 다시 적지 않고, **환경 구축 쪽이 수집 쪽에 무엇을 넘겨야 하는지만 정한다.**

수집 계획의 핵심만 옮기면 다음과 같다. 창구를 비용으로 나누어, cgroup 과 호스트 지표는 1초 주기로 계속 읽고, 전 세그먼트에 읽기 잠금을 거는 `/metrics` 와 `/telemetry?details_level=4` 와 비용을 확인하지 못한 `/collections/{c}/memory` 는 구간 경계에서만 읽는다. 항목 11개 중 다섯 개가 누적값이라 수집의 뼈대는 시계열이 아니라 경계 스냅샷이다.

### 6.2 환경 구축이 수집에 넘겨야 하는 것

수집기는 이 문서가 만든 컨테이너의 cgroup 경로를 받아서 쓴다. 조건 하나가 선 직후에 아래 넷이 정해져 있어야 수집을 시작할 수 있다.

| 넘기는 값 | 어디서 나오나 | 수집 쪽에서 쓰는 곳 |
|---|---|---|
| cgroup 경로 `$CG` | 5.3절 스크립트의 `cg_of` | `collect_metrics.py --cgroup` |
| `$BENCH` 의 `major:minor` 와 `KNAME` | 4.1절의 `io.stat` 확인, 수집 문서 11.1절 | `--io-dev`, `--disk-dev` |
| Qdrant 코어 목록 `$CPUSET` | 3.1절 | `--cores`. 코어별 사용률을 남기는 데 쓴다 |
| 조건 명세 `manifest.txt` | 5.3절 9단계 | 수집 문서 9.2절의 `manifest.json` 에 합친다 |

수집 결과는 `$RAW` 에 쓰고 `$BENCH` 에는 쓰지 않는다. 준비 문서 5.3절이 두 경로를 서로 다른 블록 장치에 두었고, 항목 11의 판정이 바로 `$BENCH` 장치의 읽기량을 보는 일이라 이 분리가 판정에 직접 걸린다.

### 6.3 측정 창을 보호한다

메모리 한도를 바꿔 가며 재는 실험에서 조건 밖의 변화는 전부 원인 후보가 된다. 준비 문서 3.8절이 무엇을 확인할지를 정했으므로, 이 절은 확인이 아니라 **측정 창 동안 실제로 막는 방법과 측정 후에 막혔는지를 증명하는 방법**을 정한다. 특히 한도를 걸지 않은 다른 컨테이너가 있으면 그쪽이 페이지 캐시를 채우고 우리 컨테이너의 캐시를 밀어내어, 한도를 바꾸지 않았는데도 조건이 흔들린다.

측정 창을 열기 전에 다음을 확인한다.

```bash
# 한도 없는 컨테이너를 찾는다. 있으면 측정에 들어가지 않는다.
# cgroup 경로는 Docker 의 cgroup 드라이버에 따라 다르므로 글롭으로 찾지 않고
# 5.3절 스크립트의 cg_of 와 같은 방식으로 /proc/<pid>/cgroup 에서 읽는다.
# 글롭으로 찾으면 cgroupfs 드라이버에서 아무것도 매치하지 않아
# "검사하지 못한 상태"가 "한도 없는 컨테이너가 없음"으로 읽힌다
for c in $(docker ps -q); do
  n=$(docker inspect -f '{{.Name}}' "$c" | sed 's#^/##')
  p=$(docker inspect -f '{{.State.Pid}}' "$c")
  g=""
  [ "${p:-0}" -gt 0 ] && g="/sys/fs/cgroup$(grep '^0::' "/proc/$p/cgroup" 2>/dev/null | cut -d: -f3)"
  m=$(cat "$g/memory.max" 2>/dev/null) || m="UNREADABLE"
  if [ "$m" = max ] || [ "$m" = UNREADABLE ]; then
    printf '%-14s %-32s memory.max=%s\n' "$c" "$n" "$m"
  fi
done
echo "위에 한 줄도 나오지 않아야 한다"

# 측정 창과 겹치는 주기 작업을 본다
systemctl list-timers --all --no-pager | head -20

# 여유 메모리가 최대 조건보다 충분히 큰지 본다
awk '/^MemAvailable:/{printf "MemAvailable %.0f GB\n", $2/1048576}' /proc/meminfo
```

한도 없는 컨테이너 목록이 비어 있어야 하고, `MemAvailable` 이 최대 조건인 512GB 에 부하 생성기 몫과 여유를 더한 값 이상이어야 한다. `UNREADABLE` 이 찍힌 줄은 합격이 아니라 **판정하지 못한 것**이므로, 그 컨테이너의 cgroup 경로를 손으로 찾아 한도를 확인한 뒤에 측정에 들어간다. 부하 생성기와 수집기 컨테이너도 이 검사의 대상이므로 아래 셋째 항목대로 자기 한도를 걸어 두어야 여기에 걸리지 않는다.

준비 문서 6.3절의 합의가 된 경우에만 아래로 주기 작업을 멈춘다. 각 줄이 없는 유닛에 대해서도 로그인 셸을 끊지 않도록 조건문으로 감쌌다.

```bash
for u in man-db.timer updatedb.timer mlocate.timer fstrim.timer logrotate.timer apt-daily.timer apt-daily-upgrade.timer; do
  if systemctl list-unit-files --no-pager | grep -q "^$u"; then
    sudo systemctl stop "$u" && echo "정지: $u"
  else
    echo "없음: $u"
  fi
done
```

측정 중 지표 수집 자체가 부하가 되지 않게 세 가지를 지킨다.

첫째, cgroup 계수기는 **호스트에서 파일을 직접 읽는다.** `docker exec` 로 읽으면 그 프로세스가 컨테이너 cgroup 에 들어가 메모리와 CPU 가 측정 대상 앞으로 과금된다. `docker stats` 도 같은 이유로 쓰지 않는다.

둘째, Qdrant 창구를 읽는 주기를 고정하고 기록한다. `/metrics` 가 모든 세그먼트에 읽기 잠금을 건다는 점은 설계서 3.3절에 있다. 조건 사이에 주기가 달라지면 그 차이가 지연 차이로 보인다.

셋째, 부하 생성기와 수집기는 Qdrant 코어와 그 SMT 형제를 모두 뺀 코어에 고정하되, 3.1절이 정한 대로 **`$NODE` 가 아닌 다른 노드의 코어**를 쓴다. 자신의 메모리 한도를 따로 걸며, 데이터 파일에는 접근하지 않는다.

```bash
if [ -z "${SIBLINGS:-}" ] || [ -z "${NODE:-}" ]; then
  echo "SIBLINGS 또는 NODE 가 비어 있다. 3.1절로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  LOADGEN_CPUS=$(lscpu -p=CPU,NODE,ONLINE | grep -v '^#' \
    | awk -F, -v n="$NODE" '$3=="Y" && $2!=n {print $1}' \
    | grep -vxF -f <(echo "$SIBLINGS" | tr ',' '\n') | head -32 | paste -sd, -)
  echo "부하 생성기 코어 = $LOADGEN_CPUS"
fi
```

부하 생성기 코어 목록이 `$SIBLINGS` 와 한 개도 겹치지 않아야 하고, `lscpu -p=CPU,NODE` 로 되짚었을 때 NODE 가 모두 `$NODE` 와 달라야 한다. 노드가 하나뿐인 장비라면 목록이 비어 나오므로, 그때는 `$2!=n` 조건을 빼고 형제 제외만 적용하고 그 사실을 조건 명세에 적는다. 수집기 코어도 이 목록 안에서 부하 생성기와 겹치지 않게 고른다.

측정이 끝난 뒤에는 **끼어든 부하가 없었음을 증명한다.** 장치 수준 읽기량과 컨테이너 읽기량을 대조하면 된다. 측정 창의 앞뒤로 두 번 찍어 뺀다.

```bash
if [ -z "${BENCH:-}" ]; then
  echo "BENCH 가 비어 있다. preparation_2026-09-21.md 1.3절로 돌아간 뒤 다시 실행한다."
else
  DEV=$(lsblk -no PKNAME "$(findmnt -no SOURCE "$BENCH")" | head -1)
  [ -n "$DEV" ] || DEV=$(basename "$(findmnt -no SOURCE "$BENCH")")
  awk '{printf "장치 누적 읽기 %.2f GiB\n", $3*512/2^30}' "/sys/block/$DEV/stat"
fi
```

측정 후 장치 누적 읽기의 증가분과 컨테이너 `io.stat` 의 `rbytes` 증가분의 차이가 10% 이내여야 한다. 차이가 그보다 크면 같은 장치를 쓰는 다른 작업이 끼어든 것이므로 그 조건은 다시 잰다. 측정 창의 경고 로그도 함께 본다.

```bash
if [ -z "${START:-}" ] || [ -z "${END:-}" ]; then
  echo "START 또는 END 가 비어 있다. 측정 창의 시작과 끝 시각을 두 변수에 넣은 뒤 다시 실행한다."
else
  journalctl --since "$START" --until "$END" -p warning --no-pager | head -20
fi
```

측정 창에 주기 작업이 실행된 기록이 없어야 한다.

### 6.4 cpuset 구성에서는 CPU 스로틀 계수기를 쓸 수 없다

설계서 4.1절이 개수 제한 대신 코어 고정을 택했으므로, `cpu.stat` 의 `nr_throttled` 와 `throttled_usec` 가 CPU 포화 상태에서도 0으로 남는다. **0을 "CPU에 여유가 있다"로 읽으면 병목 원인 판정이 통째로 틀린다.**

판정은 `Δcpu.stat.usage_usec / (Δt_초 × 1e6 × 16) × 100` 으로 16코어에 정규화해서 한다. 더 중요한 것은 코어별 사용률이다. 저장은 샤드당 업데이트 워커가 하나라 직렬화되므로, 코어 하나만 100%이고 나머지 열다섯이 노는 모습이 곧 직렬 구간 병목의 직접 증거인데 총합으로 보면 6%로 보인다. 수집기가 `/proc/stat` 의 해당 코어 줄을 1초마다 남긴다. 상세는 수집 문서에 있다.

### 6.5 부하 도구가 남겨야 할 요청 로그

3단계 부하 도구 제작, 그중 3.3 부하기가 이 요건을 모르고 시작하면 나중에 포화 판정을 다시 할 수 없으므로 여기에 한 번 더 적는다. 한 줄이 한 요청이고 칼럼은 `t_plan`, `t_send`, `t_recv`, `kind`, `status`, `n`, `sess`, `step` 이다. 도구 안에서 백분위로 줄이지 않고 표본을 전부 남긴다.

**`t_plan` 과 `t_send` 를 반드시 따로 남긴다.** 폐루프 도구는 응답이 늦으면 다음 발사도 늦어 포화 구간의 지연을 실제보다 작게 잰다. 서비스 지연은 `t_recv - t_send`, 포화 판정용 체감 지연은 `t_recv - t_plan` 이며 둘 다 계산할 수 있어야 한다. 상세와 형식은 수집 문서 9.3절에 있다.

### 6.6 이 단계가 끝났다는 것을 어떻게 아는가

다음 넷이 모두 참이면 6장이 끝난 것이다. 첫째, 한도 없는 컨테이너가 없고 `MemAvailable` 이 기준을 넘는다. 둘째, 부하 생성기와 수집기 코어 목록이 `$SIBLINGS` 와 겹치지 않고 `$NODE` 가 아닌 노드에 있다. 셋째, `ls -l /proc/<수집기pid>/fd` 에 `$BENCH` 아래 경로가 한 건도 없다. 넷째, 수집기를 60초 돌렸을 때 `collector.log` 의 `late` 가 0이고 CPU 사용이 1초 미만이다. 6.7절의 blktrace 는 켤지 말지를 5.1 예비 측정에서 정하므로 이 판정에 넣지 않는다.

### 6.7 `$BENCH` 장치의 블록 수준 I/O 추적 (blktrace)

측정 항목 11(디스크 읽기 발생)의 주 출처는 컨테이너 `io.stat` 과 `memory.stat` 의 계수기이고, 이 절은 그 위에 얹는 **보조 출처**다. 계수기는 얼마나 읽었는지를 주지만 요청 하나하나의 크기와 위치와 장치 안에서의 소요 시간은 주지 않는다. `blktrace` 는 블록 계층에서 요청이 장치로 내려가고(issue) 완료되는(complete) 사건을 요청 단위로 남기므로, 128GB 조건에서 지연 꼬리가 무너질 때 그것이 4KiB 임의 읽기의 폭주인지 readahead 가 만든 큰 순차 읽기인지를 가를 수 있다.

**대상은 `$BENCH` 가 놓인 블록 장치 하나다.** 준비 문서 5.3절이 Qdrant 저장소를 전용 장치에 두었고 6.3절이 측정 창 동안 그 장치에 다른 작업이 끼어들지 않았음을 증명하므로, 그 장치의 I/O 는 곧 Qdrant 의 I/O 다. 장치 이름은 수집 문서 11.1절의 `$DISKDEV` 를 그대로 쓴다.

**출력은 반드시 `$RAW` 에 쓴다.** 트레이스 파일을 `$BENCH` 에 쓰면 그 쓰기가 같은 장치의 통계에 들어가 항목 11의 판정을 직접 오염시킨다. 아래 블록은 수집 문서 9.1절의 조건 디렉터리 `$RUNDIR` 아래 `blktrace/` 에 쓴다.

**항상 켜지 않는다.** blktrace 는 사건 하나마다 커널이 CPU 별 relay 버퍼에 기록을 남기고 사용자 공간의 CPU 별 읽기 스레드가 이를 파일로 옮기므로 비용이 IOPS 에 비례해 커지고, 읽기 스레드가 CPU 마다 하나씩 고정되므로 Qdrant 코어 위에도 얹혀 `taskset` 으로 밖에 둘 수 없다. 디스크를 가장 많이 읽는 128GB 조건, 곧 우리가 가장 정확히 재야 하는 조건에서 비용이 가장 크다는 뜻이다. 그래서 **5.1 예비 측정에서 같은 부하를 켜고 끄고 한 번씩 돌려 QPS 와 p99 차이를 재고, 그 결과로 5.2 본 측정에서 어느 조건에 켤지를 정한다.** 합격선은 수집기 비용과 같은 기준을 쓴다(수집 문서 10장, QPS 차이 1% 이내, p99 차이 5% 이내). 넘으면 그 조건에서는 끄고 계수기만으로 판정한다.

**eBPF 계열이 비용이 낮은 대안이다.** BCC 의 `biolatency` 는 장치별 I/O 소요 시간 히스토그램을 커널 안에서 집계해 요약만 올리므로 사건마다 복사하는 blktrace 보다 비용이 낮지만 요청 단위 기록이 없어 크기 분포를 잃고, `biosnoop` 은 요청 단위로 남기는 대신 출력이 다시 IOPS 에 비례한다. 어느 쪽을 쓸지는 5.1 예비 측정에서 세 도구의 비용을 같은 부하로 재고 정한다. 설치 여부(bcc-tools 패키지와 커널 BTF)는 준비 문서 4.8절의 관측 도구 확인에 함께 넣는다.

**켜는 명령.** root 가 필요하다. `-a` 로 사건 종류를 발행(issue)과 완료(complete)로 좁히면 파일 크기와 비용이 함께 줄어든다. `-b` 는 KiB 단위의 버퍼 크기이고 `-n` 은 버퍼 개수이며, 기본값(512KiB 넷)보다 키워 둔 이유는 IOPS 가 높을 때 사건이 버려지는 것을 막기 위해서다.

```bash
if [ -z "${RUNDIR:-}" ] || [ -z "${DISKDEV:-}" ]; then
  echo "RUNDIR 또는 DISKDEV 가 비어 있다. 수집 문서 9.1절과 11.1절로 돌아간 뒤 이 블록을 다시 실행한다."
else
  mkdir -p "$RUNDIR/blktrace"
  sudo blktrace -d "/dev/$DISKDEV" -D "$RUNDIR/blktrace" -a issue -a complete -b 1024 -n 8 &
  BLKTRACE_PID=$!
  echo "blktrace 시작. 끝내려면 sudo kill -INT $BLKTRACE_PID"
fi
```

**끄는 명령.** `SIGINT` 로 끝내야 버퍼에 남은 사건을 마저 쓰고 나간다. 3.5절의 `cpu_dma_latency` 와 같은 이유로 `sudo` 를 빼면 권한 오류로 끝나지 않는다. 끝날 때 blktrace 가 CPU 별 사건 수와 함께 버려진 사건 수(dropped)를 출력하는데, **그 값이 0이 아니면 그 구간의 트레이스는 불완전하므로 `-b` 와 `-n` 을 키워 다시 잰다.**

```bash
if [ -z "${BLKTRACE_PID:-}" ] || [ -z "${RUNDIR:-}" ] || [ -z "${DISKDEV:-}" ]; then
  echo "BLKTRACE_PID 또는 RUNDIR 또는 DISKDEV 가 비어 있다. 켜는 블록을 먼저 실행한다."
else
  sudo kill -INT "$BLKTRACE_PID"
  wait "$BLKTRACE_PID" 2>/dev/null
  ls -l "$RUNDIR/blktrace/"
  du -sh "$RUNDIR/blktrace"
  # CPU 별 파일을 하나로 합쳐 둔다. 분석은 사후에 이 파일로 한다
  blkparse -D "$RUNDIR/blktrace" -i "$DISKDEV" -d "$RUNDIR/blktrace/$DISKDEV.merged.bin" -o /dev/null
  blkparse -D "$RUNDIR/blktrace" -i "$DISKDEV" | head -5
fi
```

`$RUNDIR/blktrace/` 아래에 `<장치>.blktrace.<cpu>` 파일이 CPU 수만큼 생기고, 합친 파일이 하나 더 생기며, 마지막 다섯 줄에 시각과 섹터와 크기가 찍힌 사건이 보여야 한다.

**트레이스 파일 크기는 미리 계산한다.** 사건 기록 하나는 헤더가 48바이트이고 사건 종류에 따라 부가 데이터가 조금 붙는다. `-a issue -a complete` 로 좁히면 요청 하나에 사건 둘이므로 크기는 대략 `초당 요청 수 × 구간 길이(초) × 2 × 48바이트` 다. 예시로 초당 10만 건이 10분 이어지면 `100000 × 600 × 2 × 48` 로 약 5.8GB 다. 초당 10만 건은 계산을 보이기 위한 가정값이며, 실제 값은 5.1 예비 측정에서 `io.stat` 의 `rios` 증가 속도로 얻어 이 식에 넣고 `$RAW` 여유와 비교한다. 사건 종류를 좁히지 않으면 요청 하나에 대여섯 사건이 붙어 그만큼 커진다.

이 절의 명령도 이 문서의 다른 명령과 마찬가지로 실물 서버에서 확인하지 못했다. 9.3절에 적었다.

---

## 7. 환경 검증

### 7.1 먼저 작은 규모로 한 번 예행한다

**1억 개 규모로 처음 돌리지 않는다.** 스크립트의 아홉 단계와 게이트 셋은 서버에서 한 번도 돌려 본 적이 없으므로, 작은 컬렉션으로 한 바퀴 돌려 각 단계가 기대한 출력을 내는지 먼저 본다. 준비 문서 5.9절이 1000만 개 규모로 계산을 검증하라고 한 것과 같은 취지이며, 새 구조에서는 이것이 **5.1 예비 측정**(1,000만 건, 세 조건 한 바퀴)이다. 이 문서의 추정값과 임의값, 곧 7단계의 예열 임계값과 3단계의 대기 시간과 6.7절의 blktrace 비용도 거기서 실측으로 교정한다.

예행에서 확인할 것은 값의 크기가 아니라 **절차가 도는가**이다. 게이트 A 가 잔류를 0으로 보고하는가, 게이트 B 가 세 한도의 기대 바이트값과 정확히 일치하는가, 게이트 C 가 작은 작업본에 대해서도 `rbytes` 를 작업본 크기 가까이 보고하는가, 7단계의 예열 대기가 무한히 돌지 않고 끝나는가. 이 넷이 예행의 점검표다.

동시에 수집 문서 11.2절의 흐름을 빈 컬렉션으로 한 번 예행하고, 같은 문서 8.2절의 창구 비용 측정을 돌려 주기의 근거를 실측으로 바꾼다.

### 7.2 구축이 끝났음을 확인하는 점검표

| # | 확인 | 합격 | 어긋날 때 |
|---|---|---|---|
| 1 | `$CPUSET` 열여섯 개가 `$BENCH` 장치가 붙은 노드의 서로 다른 물리 코어인가 | NODE 가 모두 장치의 `numa_node` 와 같고 CORE 값이 열여섯 가지 | 3.1절로 돌아간다 |
| 2 | `cpu.max` | `max 100000` | `--cpus` 계열을 뺀다 |
| 3 | `cpuset.cpus.effective` | `$CPUSET` 과 같음 | cpuset 위임을 준비 문서 3.3절로 확인한다 |
| 4 | `memory.max` | 3.3절 표의 기대값과 정확히 일치 | 게이트 B 가 잡는다 |
| 5 | `memory.swap.max` 와 `memory.swap.current` | 둘 다 0 | 3.4절로 돌아간다 |
| 6 | `memory.high` | `max` | 다른 컨트롤러가 끼어든 것이다 |
| 7 | 부하 상태의 `search-io` 스레드 수 | 65 이하 (블로킹 64 + async 워커 1) | `QDRANT_NUM_CPUS` 가 먹지 않았다. 그 측정값은 버린다 |
| 8 | 마운트 Type 과 Source | `bind`, `$BENCH/qdrant/work` | 4.1절로 돌아간다 |
| 9 | `io.stat` 첫 열의 `major:minor` | `$BENCH` 의 파티션이 아니라 그 파티션이 놓인 디스크의 MAJ:MIN 과 같음 | 준비 문서 3.6절의 논리 볼륨 계층 확인으로 돌아간다 |
| 10 | 게이트 A 의 잔류 | 작업본의 1% 이하 | 그 경로를 읽는 호스트 작업을 찾아 멈춘다 |
| 11 | 게이트 C 의 `rbytes` | 작업본의 90% 이상 | 그 조건은 무효이며 측정에 쓰지 않는다. 측정은 게이트를 통과한 `copy` 조건에서만 한다 |
| 12 | 게이트 C 의 `oom_kill` | 0 | 결과가 아니라 실패로 취급한다 |
| 13 | 세 조건의 `manifest.txt` 차이 | `limit`, `date`, `work_bytes` 만 다름 | 조건이 메모리 말고도 달라진 것이다 |
| 14 | 세 조건의 `memory.events` 의 `max` | 512에서 128로 갈수록 단조 증가 | 셋 다 0이면 한도가 물리지 않았다. 전체를 버린다 |
| 15 | 수집기의 열린 파일 목록 | `$BENCH` 아래 경로가 없음 | 수집기 설정을 고친다 |

1번부터 12번까지는 조건 하나를 세울 때마다 확인하고, 15번은 조건마다 수집기를 띄운 직후에 확인하며, 13번과 14번은 세 조건을 모두 돌린 뒤에 확인한다.

### 7.3 이 단계가 끝났다는 것을 어떻게 아는가

작은 규모로 세 조건을 한 바퀴 돌려 7.2절의 열다섯 항목을 모두 통과했고, 그 과정에서 7단계 예열 임계값과 수집 주기를 실측값으로 고쳤다면 환경 구축이 끝난 것이다. 이때 세 조건의 `condition.log` 와 `manifest.txt` 가 남아 있어야 하며, 그것이 본 측정에서 같은 절차가 돌았음을 보이는 근거가 된다.

---

## 8. 다음 단계로

환경 구축이 끝나면 아래 순서로 이어진다.

단계 번호는 모두 새 구조의 것이다.

| 다음 | 무엇을 하나 | 이 문서가 넘기는 것 |
|---|---|---|
| 3단계 부하 도구 제작 (3.2 적재기, 3.3 부하기, 3.4 제어기) | 적재기와 부하기와 제어기를 만든다. 세션 배정과 마스터 사본 생성은 3.2 적재기, 사다리와 스냅샷과 조건 전환 호출은 3.4 제어기의 몫이다 | 6.5절의 요청 로그 형식, 6.3절의 부하 생성기 코어 고정 규칙과 코어 범위, 4.2절의 데이터 파일 접근 금지, 5.4절이 받아 적은 제어기의 의무 네 가지와 `run_condition.sh` 의 환경 변수 계약 |
| 4.5 왜곡 검증 | 계측 이미지와 대조 이미지를 같은 부하로 비교한다. 1단계와 3.3 부하기가 있어야 돌 수 있다 | 5.3절의 실행 인자. `instrumented_build_2026-09-21.md` 7장의 `--cpus=16` 을 이 인자로 바꾼 뒤에 돌린다 |
| 2단계 데이터셋 받기와 3.2 적재기 | 데이터를 받아 검증하고, 적재하고, 적재 완료를 판정하고, 마스터 사본을 만든다 | 5.5절의 `RELOAD=copy` 전제. 마스터가 있어야 복사 경로를 쓸 수 있다 |
| 5.1 예비 측정 | 1,000만 건으로 세 조건을 한 바퀴 돌려 이 문서의 추정값을 실측으로 교정한다 | `run_condition.sh` 와 게이트 셋, 7단계 예열 임계값과 3단계 대기 시간의 교정 대상, 6.7절 blktrace 의 비용 측정 |
| 5.2 본 측정 | 1억 건, 세 조건, 포화점. 1단계 동료 인계가 필요하다 | `run_condition.sh` 와 게이트 셋, 6.2절이 수집에 넘기는 네 값, 5.1 에서 정한 blktrace 적용 조건 |

**문서 간 정리는 끝났다.** 설계서 4.6절의 관련 문서 목록과 4.6.1절 진행 상황에 이 문서와 `metrics_collection_2026-09-21.md` 가 들어가 있다. `cgroup_trap_check_2026-09-21.md` 7.1절과 설계서 4.6.1절의 "조건마다 적재를 다시 해야 한다"는 문구는 틀린 것으로 확정되었고, 두 문서는 이미 5.5절의 원칙("컨테이너가 데이터를 처음 만져야 한다", 방법은 마스터 사본 복사)으로 고쳐졌다.

---

## 9. 미확인 사항과 위험

### 9.1 이 문서 전체에 걸린 가장 큰 제약

**서버에 접속하지 못해 이 문서의 어떤 명령도 실물로 확인하지 못했다.** 특히 다음 여덟 가지는 전부 미확인이다. NUMA 노드 수와 노드당 메모리 용량, 344 vCPU 의 SMT 배치, 인터럽트가 몰린 코어 번호, cpuset 과 io 컨트롤러가 컨테이너 계층까지 위임되어 있는지, `fincore`(util-linux-extra) 설치 여부, Docker 의 cgroup 드라이버, SELinux 와 AppArmor 상태, 터보 창구가 `intel_pstate` 쪽인지 `cpufreq/boost` 쪽인지. **준비 문서 3.3절부터 3.8절까지를 먼저 돌려 이 값들을 채운 뒤에 이 문서의 스크립트를 쓴다.**

### 9.2 설계를 직접 흔드는 공백

**노드당 로컬 메모리가 512GB 미만일 가능성.** 그러면 512GB 조건만 여러 노드에 걸치게 되어 128과 256과 512가 같은 성격의 세 점이 아니게 된다. 준비 문서 3.4절이 이미 이 공백을 지적했고 이 문서도 해소하지 못했다. 확인 결과에 따라 메모리 축의 상한을 노드 용량 이하로 조정할지, 설계서 4.2절에 한계로 적을지를 먼저 정해야 한다.

**게이트 C 가 `io.stat` 의 `rbytes` 에 의존한다.** 준비 문서 3.6절이 지적한 대로 데이터 경로가 LVM 이나 소프트웨어 RAID 나 dm-crypt 위에 있으면 `io.stat` 이 어느 장치 번호로 집계되는지가 달라져 귀속이 흐려질 수 있다. 그 경우 게이트 C 의 첫 지표가 근거를 잃으므로, `memory.current` 와 `pgmajfault` 와 `workingset_refault_file` 로 판정을 옮기고 그 사실을 기록해야 한다. **장치 계층 확인이 이 문서의 자동화보다 먼저다.**

**mmap 페이지 폴트가 cgroup `io.stat` 에 잡히는지 확인하지 못했다.** 2026-09-21 함정 검증은 `dd` 즉 `read()` 경로로 했고, mmap 경로는 `cgroup_trap_check_2026-09-21.md` 부록 B 에 절차만 있고 실행하지 않았다. Qdrant 는 벡터 저장소를 mmap 으로 열므로, `io.stat` 에 안 잡히면 게이트 C 의 첫 지표와 설계서 2.3절 항목 11의 주 근거가 함께 `memory.stat` 의 `pgmajfault` 와 `workingset_refault_file` 로 넘어간다. **부록 B 를 한 번 돌려 둘이 함께 오르는지 확인해야 한다.**

### 9.3 이 문서가 택한 판단에 딸린 위험

**`QDRANT_NUM_CPUS` 우회의 확정성.** `num_cpus` 크레이트 1.17.0 이 `sched_getaffinity` 를 읽어 cpuset 을 반영하는지 소스로 확인하지 못했다. 로컬에 크레이트 소스가 없다. 이 문서는 `QDRANT_NUM_CPUS` 를 명시하는 방식으로 우회하지만, 그 환경 변수가 실제로 먹는지는 3.2절의 스레드 이름 집계로 부하 상태에서 확인해야 확정된다. 블로킹 스레드는 필요할 때 늘어나므로 유휴 상태의 집계는 근거가 되지 않는다.

**마스터 복사 경로가 재적재를 대체할 수 있다는 판단.** 이 판단은 v1.19.1 소스에서 `low_memory_mode` 기본값이 `Disabled` 이고 기동 시 mmap 예열이 돈다는 사실에 근거한다. **이 동작을 실물 서버에서 확인하지 못했다.** 게이트 C 가 매 조건마다 이를 증명하므로 잘못된 결과가 분석에 들어가지는 않지만, 실패하면 조건당 소요 시간이 복사 6분 26초에서 1억 개 적재 시간으로 크게 늘어난다. 일정을 세울 때 그 가능성을 비용으로 잡아 둔다.

**`drop_caches` 가 385GB 규모의 작업본을 한 번에 완전히 비우는지 확인하지 못했다.** 매핑 중이거나 아직 더티인 페이지는 남는다. 게이트 A 가 이를 잡아 주지만, 반복적으로 실패하면 컨테이너 폐기 후 대기 시간을 늘리거나 `sync` 를 여러 번 돌리는 보강이 필요할 수 있다. **스크립트 3단계의 2초 대기는 근거 있는 값이 아니라 임의값이다.**

**7단계의 예열 완료 판정 임계값도 임의값이다.** "10초 동안 디스크 읽기 증가가 64MiB 미만인 상태가 두 번 연속"은 실측이 아니다. 첫 조건을 돌리면서 실제 예열 곡선을 보고 고쳐야 한다.

**128GB 조건에서 기동 시 mmap 예열이 OOM 을 유발할 가능성을 배제하지 못했다.** 예열 대상이 파일 기반 페이지 캐시라면 회수 가능하므로 OOM 이 나지 않아야 하지만, HNSW 그래프가 익명 메모리로 올라가는 비중을 확인하지 못했다. 게이트 C 에서 `memory.events` 의 `oom_kill` 을 반드시 읽고, 0이 아니면 그 조건은 결과가 아니라 실패로 취급한다.

**`--memory-swappiness` 가 cgroup v2 에서 어떻게 동작하는지 확인하지 못했다.** 이 문서는 그 옵션에 기대지 않고 `--memory-swap` 만으로 스왑을 막지만, 다른 문서나 스크립트에 그 옵션이 남아 있으면 Docker 가 오류를 내며 컨테이너 생성이 실패할 수 있다.

**`/sys/block/<dev>/device/numa_node` 창구와 blktrace 의 비용은 실물로 확인하지 못했다.** 3.1절은 그 창구가 0 이상의 정수를 준다고 보고 절차를 세웠으나, 펌웨어가 `-1` 을 주면 손으로 노드를 정해야 한다. 6.7절의 blktrace 는 비용이 IOPS 에 비례한다는 성질만 알고 이 서버에서의 크기는 모르므로, 5.1 예비 측정에서 재기 전에는 어느 조건에서도 켜 둔 채 본 측정에 들어가지 않는다.

**`cpuset.cpus.partition` 을 `root` 로 만들어 배타 파티션을 구성하는 방법은 채택하지 않았다.** 그렇게 하면 다른 작업이 우리 코어에 아예 들어오지 못하게 할 수 있으나, systemd 와 Docker 의 cgroup 관리와 충돌할 수 있다. 코어 격리를 더 강하게 걸어야 할 필요가 드러나면 별도로 검증해야 한다.

### 9.4 사람과 합의에 걸린 것

**거버너 고정, 터보 차단, 주기 작업 정지, `drop_caches` 는 모두 호스트 전역 조작이라 준비 문서 6.3절의 공용 사용자 합의가 선행되어야 한다.** 합의 전에는 3.5절의 고정 명령과 6.3절의 주기 작업 정지를 쓰지 않고 기록만 한다. 합의 없이 실행하면 같은 서버의 다른 작업을 직접 망가뜨린다.

`drop_caches` 는 조건 전환 스크립트의 3단계에 들어 있으므로, **합의 없이는 이 스크립트 자체를 돌릴 수 없다.** 이것이 이 문서에서 사람에게 가장 먼저 막히는 지점이다.

### 9.5 기존 문서와 어긋나거나 손대지 않은 것

**`instrumented_build_2026-09-21.md` 7장의 왜곡 검증 명령 두 줄이 `--cpus=16` 을 쓰고 있다.** 설계서 4.1절의 코어 고정 결정과 어긋난다. 그 상태로 검증하면 CFS 스로틀링이 만든 지연 변동을 계측 왜곡으로 오인할 수 있다. 4.5 왜곡 검증에 들어가기 전에 이 문서의 실행 인자로 바꿔야 한다. 같은 문서의 "서버 빌드 확인"은 새 구조 1.1 로 넘어갔으며, 거기서 계측 이미지와 대조 이미지를 한 번에 둘 다 만든다.

**`cgroup_trap_check_2026-09-21.md` 7.1절과 설계서 4.6.1절의 "조건마다 적재를 다시 해야 한다"는 서술은 틀린 것으로 확정되었다.** 원칙은 5.5절의 "컨테이너가 데이터를 처음 만져야 한다"이고 방법은 마스터 사본 복사이며, 재적재는 마스터가 없을 때의 대안일 뿐이다. 두 문서는 이미 고쳐졌다.

**설계서 4.6절과 4.6.1절은 이 문서를 가리키도록 갱신되었다.** 앞선 판에서 "추가가 필요하다"고 적었던 항목이며, 지금은 해소되었다.

### 9.6 수집 쪽에서 넘어온 위험

아래는 `metrics_collection_2026-09-21.md` 13장에 있는 것 가운데 **환경 구축의 판단에 직접 걸리는 것만** 옮긴 것이다. 나머지는 그 문서에 있다.

- 동반 스크립트 `collect_metrics.py` 와 `snapshot.sh` 를 측정 서버에서 실행하지 않았다. 구문 검사와 파싱 함수 단위 확인만 했다. 첫 조건 전에 빈 컬렉션으로 한 번 예행해야 한다.
- `GET /collections/{c}/memory` 의 비용을 확인하지 못했다. `mincore(2)` 기반이라 385GB 매핑의 페이지 테이블을 훑는데, 이 값이 경계에서 부하를 멈추는 시간의 하한을 정한다. 게이트 C 의 교차 확인도 이 창구를 쓰므로 비용이 크면 조건당 한 번으로 줄여야 한다.
- 적재 중에 `io.stat` 의 `wbytes` 가 0보다 큰지 반드시 한 번 확인하고 결과를 `manifest` 에 적어야 한다. 틀린 장치를 보고 있으면 디스크 판정이 통째로 0이 된다.
- `memory.peak` 은 커널 버전에 따라 없을 수 있다. 없을 때는 1초 시계열의 `memory.current` 최대로 대신해야 하며, 1초 사이의 뾰족한 최대를 놓칠 수 있다.
