# 2단계 측정 사전 준비 절차서

- 작성일: 2026-09-21
- 대상: Qdrant 병목 분석 2단계 (측정 서버 344 vCPU / 1TB RAM / 16TB 디스크 / GPU 보유)
- 관련 문서
  - `design_2026-09-17.md` — 2단계 설계서. 이 문서가 준비하는 대상이다
  - `cgroup_trap_check_2026-09-21.md` + `cgroup_trap_check.sh` — 1.3 함정 확인 [완료]
  - `dataset_download_2026-09-21.md` — 데이터셋 다운로드 런북
  - `instrumented_build_2026-09-21.md` — 계측 빌드 제작과 측정 실행
  - `environment_setup_2026-09-21.md` — 측정 환경 구축 절차서. 3.1절이 이 문서 3.6절의 NUMA 노드 확인 결과에서 출발한다
  - `stage_isolation_2026-09-18.md`, `qdrant_instrumentation_2026-09-17.md` — 계측 명세와 기본 관측 수단
  - `stage_timing_v1.19.1.patch` — 계측 지점 18개소를 넣는 패치. 8.1절에서 서버로 옮긴다
- 위치: 확정된 단계 구조에서 이 문서는 **1번 Qdrant Docker 환경 준비(특히 1.2 조건에 맞춰 띄우기와 1.4 준비 완료 확인)와 2번 데이터셋 받기의 선행 준비**다. 옛 "설계서 4.6절 N단계" 번호는 더 쓰지 않으며, 이 문서 안의 단계 번호는 모두 새 구조의 것이다. 제목의 "2단계"는 과제 전체의 2단계(병목 재현 측정)를 뜻하고 그 번호와는 무관하다
- 상태: **서버에 접속하지 못한 채 작성했다.** 모든 확인 명령은 표준 도구의 일반적인 출력 형식을 전제로 합격 기준을 적은 것이고, 서버에서 처음 돌릴 때 출력이 다르면 기준 문구부터 고쳐야 한다. 이 문서에서 실측으로 확인된 것과 확인되지 않은 것의 구분은 11장에 모았다

---

## 1. 요약

기존 문서 다섯 편은 모두 **"컨테이너를 띄운다" 또는 "파일을 받는다"에서 시작한다.** 그 앞에 서버가 어떤 상태여야 하는지, 어떤 도구가 깔려 있어야 하는지, 디스크를 어떻게 잡아야 하는지, 어떤 계정과 권한과 법무 확인이 선행되어야 하는지는 어느 문서에도 없다. 그 출발점을 다루는 것이 이 문서다.

그 앞선 준비를 조사한 결과 **설계를 직접 흔들 수 있는 공백이 넷** 나왔다. 첫째는 NUMA 노드별 메모리 용량이다. 노드당 메모리가 512GB 미만이면 메모리 축 128/256/512GB 가운데 512GB 조건에만 원격 메모리 접근이 섞여, 세 점이 같은 성격의 세 점이 아니게 된다. 둘째는 zswap과 zram이다. 이것이 켜져 있으면 스왑을 차단해도 메모리가 압축되어 남아 설계서 4.3절의 전제인 "메모리를 줄이면 디스크를 읽는다"가 무너진다. 셋째는 Qdrant가 컨테이너 안에서 호스트의 344개 코어를 그대로 읽을 가능성이며, 그렇게 되면 관측되는 것은 Qdrant의 병목이 아니라 스레드 경합이다. 넷째는 다운로드 가이드가 모든 경로를 홈 디렉터리 아래로 적어 둔 점으로, 홈이 작은 루트 파티션에 있으면 212.3GB를 받는 도중에 서버 전체가 멈춘다.

용량 자체는 제약이 아니다. 필수 경로에 약 2.44TB, 선택 데이터까지 모두 써도 약 4.70TB가 필요하므로 16TB의 각각 15.2%와 29.4%다. 그러나 **배치는 제약이다.** 파일시스템이 ext4나 xfs여야 하고, 원본 데이터와 Qdrant 저장소가 서로 다른 블록 장치에 있어야 한다. 이유는 5장에 있다.

실제로 착수를 막는 것은 기술이 아니라 **사람이다.** 서버 계정과 sudo 권한, 공동 사용자와의 독점 사용 창 합의, 사내 방화벽 허용, 데이터 용도에 대한 법무 회신, 동료의 1단계 인계 일정이 그것이다. 이 다섯 가지는 우리가 손을 놀려 끝낼 수 있는 일이 아니라 요청을 보내고 회신을 기다려야 하는 일이므로, **오늘 가장 먼저 보내야 한다.**

### 1.1 준비 단계와 그것이 막고 있는 것

단계 번호는 확정된 단계 구조의 것이다. 1.3 함정 확인은 이미 완료되어 표에서 뺐다.

| 준비 | 무엇을 하는가 | 이것이 끝나야 할 수 있는 일 | 선행 준비 | 남의 회신을 기다리나 |
|---|---|---|---|---|
| 0 | 시작 전 점검표 | 전체 | 없음 | 아니오 |
| 1 | 서버 확인 | 1.2 조건에 맞춰 띄우기, 1.4 준비 완료 확인 | 준비 4의 계정과 sudo | 아니오 |
| 2 | 도구 설치 | 1.2의 blktrace 준비, 1.5의 수집기, 이 문서의 모든 확인 명령 | 준비 1, 준비 5 | 패키지 저장소가 막혀 있으면 예 |
| 3 | 저장 공간 설계 | 2 데이터셋 받기, 3.2 적재기의 마스터 사본 생성, 5 측정 | 준비 1의 디스크 확인 | 디스크 증설이 필요하면 예 |
| 4 | 계정, 토큰, 라이선스 | 서버 접속 자체와 2.1 라이선스 확인 | 없음 | **예. 가장 오래 걸린다** |
| 5 | 네트워크 확인 | 8장 코드 받기, 9장 데이터 받기 | 준비 4의 방화벽 허용 | 방화벽 결재가 있으면 예 |
| 6 | 코드 받기와 빌드 환경 | 1.1 소스 확보, 패치 적용, 이미지 빌드 | 준비 2, 준비 5 | 아니오 |
| 7 | 데이터 받기 | 2.2 받기, 2.3 검증 | 준비 3, 준비 5, 준비 4의 법무 회신 | 법무 회신이 필요하면 예 |

### 1.2 의존 관계

```
[오늘 바로 보낸다]
사람에게 보내는 요청 (준비 4)
  ├─ 서버 계정과 sudo ─────┬─→ 준비 1 서버 확인 ──→ 준비 3 저장 공간 ─┐
  ├─ 공동 사용자 합의 ─────┘         │                                 │
  │                                   └─→ 준비 2 도구 설치 ──────────┐ │
  ├─ 방화벽 허용 ──────────→ 준비 5 네트워크 ─┬─→ 준비 6 코드 받기 ─┴─┤
  │                                            └─→ 준비 7 데이터 받기 ─┤
  ├─ 법무 회신 (데이터 용도) ───────────────────────────────────────── ┤
  └─ 동료의 1단계 인계 ───────────────────────────────────────────────┴─→ 5.2 본 측정
```

이 그림이 말하는 것은 하나다. **준비 4의 사람 항목이 나머지 전부의 앞에 있다.** 준비 1부터 7까지를 아무리 빨리 끝내도 법무 회신과 동료 인계가 늦으면 측정은 시작되지 않는다.

### 1.3 이 문서 전체에서 쓰는 경로 변수

명령을 그대로 붙여 넣을 수 있도록 경로를 변수로 둔다. 실제 값은 준비 3에서 정한다.

```bash
export RAW=/mnt/raw      # 원본 다운로드, 변환 산출물, 빌드, 로그, 결과
export BENCH=/mnt/bench  # Qdrant 저장소 전용. 다른 것을 두지 않는다
```

`dataset_download_2026-09-21.md` 의 모든 명령이 쓰는 `~/vecdata` 는 `$RAW` 로 바꿔 읽는다. 그 이유는 5.4절에 있다.

서버 이름이나 컬렉션 이름처럼 사람이 값을 채워 넣어야 하는 자리도 같은 이유로 `$SERVER` 와 `$COLL` 같은 변수로 적는다. **꺾쇠를 쓴 자리표시자는 셸이 `<` 를 입력 재지정으로 해석하므로 그대로 붙여 넣는 순간 구문 오류가 난다.**

---

## 2. 준비 0. 시작 전 점검표

아래를 위에서부터 훑는다. 각 항목의 상세는 괄호 안의 장에 있다. 굵게 표시한 것은 **어긋나면 측정 설계 자체를 고쳐야 하는 항목**이다.

**사람에게 보내는 요청 (6장)**

- [ ] 측정 서버 접속 계정을 받았다 (6.2)
- [ ] sudo 권한을 받았고 무암호 여부를 안다 (6.2)
- [ ] docker 그룹에 들어가 있다 (6.2)
- [ ] 서버를 누가 함께 쓰는지 확인했고 독점 사용 창을 합의했다 (6.3)
- [ ] 사내 방화벽 허용 목록에 필요한 호스트를 신청했다 (6.4, 7.1)
- [ ] 데이터 용도(사내 전용인가 외부 공개인가)에 대한 답을 문서로 받았다 (6.5)
- [ ] 라이선스 질의를 법무에 보냈다 (6.6)
- [ ] 동료의 1단계 인계 자료 형식과 일정을 합의했다 (6.10)

**서버 확인 (3장)**

- [ ] **서버 실물 사양이 설계 전제와 같다 (3.1)**
- [ ] cgroup v2 단독 모드이고 컨트롤러가 컨테이너 계층까지 위임된다 (3.3)
- [ ] 컨테이너 cgroup에서 네 계수기를 실제로 읽었다 (3.3)
- [ ] **NUMA 노드별 메모리 용량을 확인했다 (3.4)**
- [ ] **`$BENCH` 장치가 붙은 NUMA 노드를 확인했고 그 노드의 코어 목록을 적었다 (3.6)**
- [ ] SSD 가 붙은 노드의 코어 16개가 물리 코어인지 SMT 형제인지 확인했다 (3.4)
- [ ] `--cpuset-cpus` 가 실제로 먹힌다 (3.4)
- [ ] **zswap이 꺼져 있고 zram 장치가 없다 (3.5)**
- [ ] `vm.max_map_count` 를 확인했고 필요하면 올렸다 (3.5)
- [ ] `drop_caches` 가 실제로 듣는다 (3.5)
- [ ] 데이터 경로의 파일시스템이 ext4 또는 xfs이고 압축이 없다 (3.6)
- [ ] readahead 값을 기록했다 (3.6)
- [ ] **Qdrant 컨테이너가 코어 수를 16으로 인식한다 (3.7)**

**도구와 저장 공간 (4장, 5장)**

- [ ] 필수 명령줄 도구가 모두 있다 (4.1)
- [ ] blktrace 와 bcc 도구가 있거나 설치를 요청했다 (4.8)
- [ ] GNU coreutils다 (`date +%s.%N` 이 나노초를 준다) (4.3)
- [ ] Docker 이미지를 측정 전에 미리 받아 두었다 (4.5)
- [ ] 파이썬 가상환경을 만들고 pyarrow와 numpy를 넣었다 (4.6)
- [ ] `$RAW` 와 `$BENCH` 가 서로 다른 블록 장치다 (5.3)
- [ ] `$BENCH` 에 1.75TB 이상(여유를 포함해 1.8TB), `$RAW` 에 800GB 이상 여유가 있다 (5.1)
- [ ] **fio로 디스크 읽기 기준선 세 값을 재서 기록했다 (5.5)**
- [ ] 스왑 장치가 `$BENCH` 와 같은 장치에 있지 않다 (5.6)

**코드와 데이터 (8장, 9장)**

- [ ] Qdrant v1.19.1 소스를 받았고 태그를 확인했다 (8.1)
- [ ] `stage_timing_v1.19.1.patch` 를 소스 최상위로 옮겼고 `git apply --check` 가 통과했다 (8.1)
- [ ] 계측 빌드를 Docker로 할지 호스트로 할지 정했다 (8.2)
- [ ] 서버에서 실효 대역폭을 재서 소요 시간을 다시 계산했다 (7.3)
- [ ] 다운로드 가이드의 macOS 전용 명령을 리눅스 판으로 바꿨다 (9.3)

---

## 3. 준비 1. 서버 확인

`cgroup_trap_check_2026-09-21.md` 2장이 서버 조건으로 요구하는 것은 다섯 줄이고, 그 다섯 줄은 cgroup v2 여부와 여유 메모리와 파일시스템 종류와 Docker의 cgroup 버전만 본다. 이 장은 그 출발점을 마흔 개가 넘는 항목으로 넓힌 것이다.

확인 결과를 한곳에 모아 두면 뒤에서 되짚기 쉽다. 아래 명령으로 기록 파일을 만들어 두고, 이 장의 각 절에서 얻은 출력을 그 파일에 붙여 나간다.

```bash
mkdir -p ~/qdrant-prep && cd ~/qdrant-prep
LOG=~/qdrant-prep/server_check_$(date +%Y%m%d).txt
echo "# 서버 확인 $(date -u +%Y-%m-%dT%H:%M:%SZ) $(hostname)" > $LOG
echo "기록 파일: $LOG"
```

### 3.1 전제 대조 — 서버 실물 사양이 설계 전제와 같은가

설계서 4.1절과 4.5.5절, 그리고 다운로드 가이드 7.5절의 모든 계산이 344 vCPU, RAM 1TB, 디스크 16TB, GPU 보유를 전제로 한다. 이 네 값 중 하나라도 다르면 메모리 축 128/256/512GB와 데이터 규모 1억 개라는 전제부터 다시 잡아야 하므로, 다른 무엇보다 먼저 확인한다.

아래 명령은 CPU와 메모리와 블록 장치와 GPU를 한 번에 출력한다.

```bash
lscpu | grep -E '^(Architecture|Byte|CPU\(s\)|Thread|Core|Socket|Model name|NUMA node\(s\)|NUMA node[0-9])'
free -g | head -2
lsblk -d -o NAME,SIZE,ROTA,MODEL
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv 2>/dev/null \
  || echo 'GPU 없음 또는 드라이버 미설치'
```

기준은 다음과 같다. `CPU(s)` 가 344이고, `Mem total` 이 1000GB 근처이며, 블록 장치 용량의 합계가 16TB 근처이고, GPU가 한 장 이상 보여야 한다. 하나라도 어긋나면 그 값을 기록하고 **설계서 4.1절과 4.5.5절을 먼저 고친 뒤에** 이 문서의 나머지로 넘어간다.

### 3.2 접속과 권한

주 데이터 212.3GB 다운로드와 조건별 측정은 한 번에 수십 분에서 수 시간이 걸린다. 접속이 끊길 때 작업이 함께 죽으면 다운로드 가이드 부록 B의 백그라운드 절차가 성립하지 않는다.

```bash
SERVER=bench01.example.com   # 실제 호스트 이름이나 IP 로 바꾼다
ssh "$SERVER" 'hostname; whoami; id; uptime'
ssh "$SERVER" 'command -v tmux screen; echo rc=$?'
```

로그인이 성공하고 tmux 또는 screen 가운데 하나가 있어야 한다. 둘 다 없으면 `nohup` 으로 대신할 수 있으나 진행 상황을 되짚기 어려우므로 설치를 요청한다.

이어서 sudo를 본다. 페이지 캐시 비우기와 sysctl 조회와 변경과 마운트 옵션 확인이 모두 root 권한을 요구하고, `cgroup_trap_check.sh` 는 사전 확인의 `id -u` 검사에서 root가 아니면 `die` 로 즉시 중단하므로 1.3 함정 확인 절차 자체가 여기서 막힌다. 1.3은 완료되었지만 같은 권한이 1.2 이후의 모든 절차에 그대로 필요하다.

```bash
sudo -n true && echo 'NOPASSWD 사용 가능' || echo '비밀번호 입력 필요'
sudo -l | sed -n '1,30p'
sudo test -w /proc/sys/vm/drop_caches && echo 'drop_caches 쓰기 가능'
```

`sudo -l` 목록에 `(ALL)` 또는 최소한 sysctl과 tee와 sh와 docker가 보이고 마지막 줄이 출력되어야 한다. 무암호가 아니면 스크립트를 백그라운드로 돌릴 때 암호 입력에서 멈추므로 미리 알아 둔다.

마지막으로 Docker 데몬을 본다. 컨테이너를 만들고 지우고 cgroup 경로를 읽는 모든 절차가 docker 명령에 달려 있고, rootless 데몬이면 cpuset과 메모리 한도가 위임 설정에 따라 걸리지 않을 수 있다.

```bash
id -nG | tr ' ' '\n' | grep -x docker || echo 'docker 그룹 아님'
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
docker info --format 'cgroup={{.CgroupVersion}} driver={{.CgroupDriver}} storage={{.Driver}} root={{.DockerRootDir}} security={{.SecurityOptions}}'
docker info 2>&1 | grep -i -A3 'WARNING' || echo '경고 없음'
```

`cgroup=2` 와 `driver=systemd` 와 `storage=overlay2` 가 나오고 경고가 없어야 한다. `security` 항목에 `name=rootless` 가 보이면 rootful 데몬으로 바꾸거나 위임 설정을 따로 확인해야 한다. docker 그룹 소속은 사실상 root 권한과 같으므로 부여 사실을 서버 관리자와 공유한다.

### 3.3 커널과 cgroup

이번 측정이 기대는 cgroup v2 계수기와 madvise 계열 기능은 커널 버전에 따라 있고 없음이 갈린다. 먼저 버전을 적어 두고, 실제 유무는 뒤에서 실물로 확인한다.

```bash
uname -r
grep -E '^(NAME|VERSION)=' /etc/os-release
uname -a
```

커널 5.14 이상이면 이 장의 모든 항목이 무리 없이 성립한다. 5.9 미만이면 `memory.stat` 의 파일 refault 지표 이름이 다르고, 5.14 미만이면 Qdrant의 캐시 예열이 madvise 대신 다른 경로를 탄다. 어느 쪽이든 아래의 실물 확인이 판정 근거이고 버전은 참고값이다.

#### 왜 cgroup v2여야 하는가

`cgroup_trap_check_2026-09-21.md` 2장은 v2를 요구하면서 그 이유는 적지 않았다. 이번 측정이 v2를 요구하는 이유는 넷이다.

| 필요한 것 | v2가 주는 창구 | v1의 상태 |
|---|---|---|
| 페이지 캐시까지 한 축으로 묶은 메모리 한도 | `memory.max` | 메모리와 스왑을 `memsw` 로 묶어 걸어 한도 실험이 성립하지 않는다 |
| 한도에 실제로 닿은 횟수 | `memory.events` 의 `max` | 대응하는 창구가 없다 |
| 쫓겨났다 다시 읽은 횟수 | `memory.stat` 의 `workingset_refault_file` | 대응하는 창구가 없다 |
| 컨테이너별 진짜 디스크 읽기 | `io.stat` 의 `rbytes` | 대응하는 창구가 없다 |

이 네 값은 각각 설계서 3.1절의 표에서 "메모리 부족 판정", "쫓겨났다 다시 읽은 횟수", "디스크 읽은 양"에 대응한다. 즉 v1에서는 설계서 2.3절의 병목 원인 판정 세 항목 가운데 둘이 통째로 빈다.

```bash
stat -fc %T /sys/fs/cgroup
grep -E 'cgroup' /proc/mounts
cat /sys/fs/cgroup/cgroup.controllers
cat /sys/fs/cgroup/cgroup.subtree_control
```

첫 줄이 `cgroup2fs` 여야 한다. `/proc/mounts` 에 `cgroup2` 한 줄만 있어야 하고 v1 마운트가 함께 보이면 하이브리드 모드이므로 `systemd.unified_cgroup_hierarchy=1` 로 전환을 요청한다. `cgroup.controllers` 에 cpuset과 cpu와 io와 memory가 모두 있어야 한다.

#### 컨트롤러가 컨테이너 계층까지 위임되는가

루트에 컨트롤러가 있어도 하위 계층의 `subtree_control` 에 켜져 있지 않으면 컨테이너 cgroup에 해당 파일이 생기지 않는다. io가 빠져 있으면 `cgroup_trap_check.sh` 의 `IO_OK` 가 0이 되어 `rbytes()` 가 읽는 `io.stat` 의 `rbytes` 가 통째로 비어 나오고, cpuset이 빠져 있으면 설계서 4.1절의 코어 고정이 불가능하다.

```bash
cat /sys/fs/cgroup/cgroup.subtree_control
cat /sys/fs/cgroup/system.slice/cgroup.subtree_control 2>/dev/null || echo 'system.slice 없음'
ls /sys/fs/cgroup/docker 2>/dev/null && cat /sys/fs/cgroup/docker/cgroup.subtree_control
```

두 줄 모두에 memory와 io와 cpu와 cpuset이 보여야 한다. systemd 드라이버면 컨테이너가 `system.slice` 아래 `docker-<id>.scope` 로 생기므로 `system.slice` 줄이 판정 기준이고, cgroupfs 드라이버면 `/sys/fs/cgroup/docker` 줄이 기준이다. io가 없으면 `cgroup_trap_check_2026-09-21.md` 2장의 안내대로 `memory.current` 와 한도 도달 횟수로 판정하게 된다.

#### 컨테이너 계수기 실물 확인과 메모리 한도 강제

설계서 3.1절이 쓰는 지표 네 개가 이 서버의 이 커널에서 실제로 어떤 이름과 값으로 나오는지 확인하지 않으면, 본 측정에서 값을 못 읽고 나서야 알게 된다. 같은 컨테이너로 docker의 `--memory` 가 실제로 `memory.max` 에 반영되는지도 함께 확인된다.

```bash
CID=$(docker run -d --memory=1g --memory-swap=1g alpine sleep 60)
PID=$(docker inspect -f '{{.State.Pid}}' $CID)
CG=/sys/fs/cgroup$(grep '^0::' /proc/$PID/cgroup | cut -d: -f3)
echo "CG=$CG"
cat $CG/memory.max $CG/memory.swap.max
cat $CG/memory.events
grep -E '^(file|pgmajfault|workingset_refault|workingset_refault_file|workingset_activate_file) ' $CG/memory.stat
cat $CG/io.stat 2>/dev/null || echo 'io.stat 없음'
docker rm -f $CID
```

`memory.max` 가 1073741824이고 `memory.swap.max` 가 0으로 나와야 한다. `memory.events` 에 `max` 행이 있어야 하고, `memory.stat` 에 `workingset_refault_file` 이 있어야 한다. 이름이 `workingset_refault` 뿐이면 커널이 오래된 것이므로 **설계서 3.1절과 `cgroup_trap_check_2026-09-21.md` 부록 B의 지표 이름을 그 이름으로 고친다.** `io.stat` 이 비어 있으면 앞 항목의 위임 설정을 다시 본다.

#### PSI 압력 지표 (권장)

설계서 1.3절은 병목 원인을 CPU와 메모리와 디스크 중 무엇인지로 판정하는데, 지금 근거는 사용률과 읽기 횟수뿐이다. PSI는 작업이 각 자원을 기다리느라 멈춘 시간의 비율을 직접 주므로 세 자원 가운데 무엇이 한계인지에 대한 가장 직접적인 근거가 되고, 컨테이너 단위로도 읽힌다. 기존 문서 어디에도 언급이 없는 항목이다.

```bash
cat /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory 2>/dev/null || echo 'PSI 비활성'
CID=$(docker run -d --memory=1g alpine sleep 30)
CG=/sys/fs/cgroup$(grep '^0::' /proc/$(docker inspect -f '{{.State.Pid}}' $CID)/cgroup | cut -d: -f3)
ls $CG | grep -E '^(cpu|io|memory)\.pressure' || echo 'cgroup PSI 파일 없음'
docker rm -f $CID
```

세 줄 모두 `some avg10 avg60 avg300 total` 형태로 출력되고 컨테이너 cgroup에도 `cpu.pressure` 와 `io.pressure` 와 `memory.pressure` 가 있어야 한다. 비활성이면 커널 부팅 인자에 `psi=1` 이 필요하며, 이는 재부팅을 요구하므로 재부팅 일정과 함께 판단한다. 실제로 측정 항목에 넣을지는 설계서 2.3절을 고치는 결정이 필요하다.

#### MADV_POPULATE_READ 지원 여부 (권장)

`qdrant_instrumentation_2026-09-17.md` 4.3절이 인용한 Qdrant 소스 주석에 따르면 mmap 기반 저장소의 캐시 예열이 `madvise` 의 `MADV_POPULATE_READ` 로 이루어진다. 이 기능은 비교적 최근 커널에 추가된 것이라 오래된 커널에서는 동작이 달라지고, 그러면 옵티마이저의 `populate_vector_storages` 단계의 소요 시간과 메모리 한도 실험의 해석이 함께 흔들린다.

```bash
grep -R 'POPULATE_READ' /usr/include/asm-generic/mman-common.h /usr/include/*/asm/mman.h 2>/dev/null
python3 - <<'PY'
import ctypes, mmap
# MADV_POPULATE_READ = 22. 지원하지 않는 커널은 EINVAL(22) 을 돌려준다.
libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.madvise.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
libc.madvise.restype = ctypes.c_int
buf = mmap.mmap(-1, 4096)                       # mmap 이라야 페이지 정렬이 보장된다
addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
rc = libc.madvise(addr, 4096, 22)
print("madvise rc=", rc, "errno=", ctypes.get_errno())
PY
```

헤더에 `#define MADV_POPULATE_READ 22` 가 보이고 `madvise rc= 0` 이 나와야 한다. `rc= -1` 이고 `errno= 22` 이면 이 커널은 지원하지 않는 것이다.

**이 판정이 성립하려면 스크립트의 두 가지 장치가 모두 있어야 한다.** 하나는 `libc.madvise.argtypes` 지정이다. 이것이 없으면 ctypes가 주소를 C의 `int` 로 보고 32비트로 잘라 넘기며, 잘린 주소는 매핑되지 않은 영역이라 `ENOMEM(12)` 이 돌아온다. 22가 아니라는 이유로 커널 지원 여부와 무관하게 통과해 버리므로 판정 자체가 무의미해진다. 다른 하나는 버퍼를 `mmap` 으로 잡는 것이다. `create_string_buffer` 는 페이지 정렬을 보장하지 않아 지원하는 커널에서도 `EINVAL(22)` 이 나고, 그러면 지원하는 커널을 미지원으로 오판한다.

지원하지 않으면 `qdrant_instrumentation_2026-09-17.md` 4.3절의 예열 설명이 이 서버에 그대로 적용되지 않는다는 사실을 측정 결과에 함께 적는다.

### 3.4 CPU 구성

#### SSD 가 붙은 노드의 코어 열여섯 개는 물리 코어인가 SMT 형제인가

Qdrant 에 주는 코어 열여섯 개는 3.6절에서 `$BENCH` 장치가 붙은 NUMA 노드를 확인한 뒤 그 노드의 CPU 목록에서 고른다. 그런데 고른 열여섯 개가 물리 코어 열여섯 개인지 물리 코어 여덟 개의 SMT 형제 열여섯 개인지에 따라 실효 연산 능력이 두 배 차이 난다. 형제 목록을 보지 않고 코어를 고르면 조건이 무엇인지 모르는 채로 측정하게 된다.

```bash
lscpu | grep -E 'Thread|Core|Socket|NUMA node\(s\)|Model name'
lscpu -e=CPU,NODE,SOCKET,CORE,ONLINE,MAXMHZ | head -40
# 번호는 예시다. 3.6절에서 정한 노드의 CPU 목록에서 고른 번호로 바꾼다
for c in 0 1 2 8 15 16; do
  printf 'cpu%-3s siblings=%s core_id=%s node=%s\n' "$c" \
    "$(cat /sys/devices/system/cpu/cpu$c/topology/thread_siblings_list 2>/dev/null)" \
    "$(cat /sys/devices/system/cpu/cpu$c/topology/core_id 2>/dev/null)" \
    "$(ls -d /sys/devices/system/node/node*/cpu$c 2>/dev/null | head -1)"
done
```

`thread_siblings_list` 의 출력으로 형제 쌍을 확인한다. `0-1` 처럼 인접 번호가 형제면 연속한 열여섯 개는 물리 코어 여덟 개이고, `0-172` 처럼 멀리 떨어진 번호가 형제면 연속한 열여섯 개는 물리 코어 열여섯 개다. 어느 쪽을 골랐는지 설계서 4.1절에 명시하고, 고른 열여섯 개가 모두 같은 NUMA 노드에 속하는지도 함께 기록한다.

#### NUMA 노드 수와 노드별 메모리 용량

**이것이 이번 조사에서 찾은 가장 큰 공백이다.** 메모리 한도 512GB는 노드 하나의 로컬 메모리가 512GB 이상일 때만 로컬 접근으로 채워진다. 노드당 메모리가 그보다 작으면 512GB 조건에만 원격 메모리 접근이 섞이게 되어, 128과 256과 512가 같은 성격의 세 점이 아니게 된다. 설계서 4.2절의 메모리 축 자체가 여기에 달려 있는데 기존 문서에 언급이 없다.

```bash
numactl -H 2>/dev/null || (echo 'numactl 없음. sysfs 로 확인한다'; \
  for n in /sys/devices/system/node/node*; do \
    printf '%s %s\n' "$n" "$(grep MemTotal $n/meminfo)"; done)
numactl --hardware 2>/dev/null | grep -E 'node [0-9]+ size|node distances' -A5
```

노드 수와 노드별 `MemTotal` 을 얻는다. 노드당 메모리가 512GB 이상이면 코어 열여섯 개와 메모리를 같은 노드에 묶고 docker 실행에 `--cpuset-mems` 를 함께 준다. 512GB 미만이면 512GB 조건이 여러 노드에 걸친다는 사실을 설계서 4.2절에 한계로 적고, 필요하면 메모리 축의 상한을 노드 용량 이하로 조정한다.

**어느 노드를 고를지는 메모리 용량이 아니라 `$BENCH` 장치가 붙은 노드가 출발점이다.** SSD가 붙은 NUMA 노드를 3.6절에서 먼저 확인하고, 이 절에서는 그 노드의 메모리가 512GB 이상인지를 본다. 그 노드의 코어 열여섯 개와 메모리를 Qdrant에 주고, 부하 도구와 수집기는 다른 노드의 코어를 쓴다. 이 순서가 `environment_setup_2026-09-21.md` 3.1절의 출발점이다.

#### 코어 고정이 실제로 먹히는가

설계서 4.1절이 개수 제한이 아니라 코어 고정을 쓰기로 했으므로, docker의 `--cpuset-cpus` 가 실제로 `cpuset.cpus.effective` 에 반영되고 컨테이너 안에서 보이는 코어 수가 열여섯 개로 줄어드는지 확인해야 한다.

```bash
# 0-15 와 --cpuset-mems=0 은 예시 값이다. 실제 코어와 노드는 3.6절에서 정한 노드의 것을 쓴다
docker run --rm --cpuset-cpus=0-15 alpine sh -c \
  'cat /sys/fs/cgroup/cpuset.cpus.effective; nproc; grep -c ^processor /proc/cpuinfo'
docker run --rm --cpuset-cpus=0-15 --cpuset-mems=0 alpine sh -c \
  'cat /sys/fs/cgroup/cpuset.mems.effective'
```

`0-15` 와 `--cpuset-mems=0` 은 예시 값이며, 실제 코어와 노드는 3.6절에서 정한 노드의 것을 쓴다. 첫 줄이 지정한 코어 범위 그대로, 둘째 줄이 `16` 으로 나와야 한다. 셋째 줄은 `/proc/cpuinfo` 가 호스트 값을 그대로 보여 주므로 344가 나오는 것이 정상이며, **이는 컨테이너 안 프로그램이 코어 수를 잘못 읽을 수 있다는 경고이기도 하다.** 그 경고가 실제로 Qdrant에 해당하는지는 3.7절에서 확인한다. `--cpuset-mems` 가 오류 없이 적용되면 NUMA 고정도 가능하다.

#### 주파수 거버너와 터보 (권장)

거버너가 powersave나 schedutil이면 같은 부하에서도 주파수가 오르내려 지연의 꼬리가 실제 병목이 아니라 주파수 변동 때문에 생긴다. 터보 부스트는 활성 코어 수에 따라 최대 주파수를 바꾸므로, 코어 열여섯 개만 쓰는 우리 조건에서 유리하게 작동해 조건 사이 비교를 흐린다.

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver 2>/dev/null
cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null
cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
cpupower frequency-info 2>/dev/null | head -20
grep -E 'model name|MHz' /proc/cpuinfo | head -4
```

거버너와 드라이버와 터보 상태를 기록한다. `performance` 로 고정하는 것이 가장 재현성이 좋으나 이는 호스트 전역 변경이라 공유 서버에서는 합의가 필요하다. 변경하지 않기로 했다면 측정 중 실제 주파수를 함께 남기기 위해 `turbostat` 또는 `/proc/cpuinfo` 의 MHz를 주기적으로 기록한다.

#### 부하 생성기 몫의 코어와 인터럽트 분산 (권장)

설계서 4.1절은 부하 생성기를 다른 코어에 두라고만 적었고 어느 코어인지는 정하지 않았다. 부하 생성기가 Qdrant와 같은 코어나 같은 SMT 형제를 쓰면 서로의 지연을 만들어 낸다. 네트워크 인터럽트 역시 특정 코어에 몰리므로 그 코어를 피해야 한다.

```bash
grep -E 'eth|ens|eno|enp|mlx|nvme' /proc/interrupts | awk '{print $1, $NF}' | head -20
systemctl is-active irqbalance 2>/dev/null
cat /proc/cmdline
```

인터럽트가 몰린 코어 번호를 확인하고 Qdrant 몫과 부하 생성기 몫 양쪽에서 제외한다. `cmdline` 에 `isolcpus` 가 있으면 그 범위도 함께 고려한다. 부하 생성기에 줄 코어 범위를 정해 설계서 4.1절에 적는다.

### 3.5 메모리 구성

#### 총량과 측정 시점의 여유

`cgroup_trap_check_2026-09-21.md` 2장이 함정 검증에만 20GB 이상의 여유를 요구하고, `cgroup_trap_check.sh` 는 `FREE_MB` 와 `NEED_MB` 의 비교로 같은 조건을 `MemAvailable` 로 직접 검사한다. 본 측정은 컨테이너 한도 512GB에 더해 데이터 적재와 부하 생성기 몫이 필요하다.

```bash
free -g
awk '/^(MemTotal|MemFree|MemAvailable|Cached|Buffers|Dirty|SwapTotal|SwapFree)/' /proc/meminfo
ps -eo pid,user,rss,comm --sort=-rss | head -10
```

`MemAvailable` 이 최대 조건인 512GB에 부하 생성기 몫과 여유를 더한 값 이상이어야 한다. 상위 프로세스 목록에 수백 GB를 쓰는 다른 작업이 있으면 그 작업의 주인과 일정을 조율한 뒤에 측정한다.

#### 스왑과 zswap과 zram

**이것이 두 번째로 큰 공백이다.** 설계서 4.3절의 대책 넷 가운데 하나가 스왑 차단인데, 압축 스왑인 zswap이나 zram이 켜져 있으면 스왑을 꺼도 메모리가 압축되어 남아 있어 디스크 읽기가 발생하지 않는다. 그러면 "메모리를 줄이면 디스크를 읽는다"는 실험 전제가 그대로 무너진다. 기존 문서에 이 경로에 대한 언급이 없다.

```bash
swapon --show
cat /proc/swaps
cat /sys/module/zswap/parameters/enabled 2>/dev/null
ls -d /sys/block/zram* 2>/dev/null || echo 'zram 장치 없음'
sysctl vm.swappiness
```

zswap이 `N` 이고 zram 장치가 없어야 한다. 스왑 파티션 자체는 있어도 된다. `cgroup_trap_check_2026-09-21.md` 4.2절의 설명대로 컨테이너마다 `--memory-swap` 을 `--memory` 와 같게 주면 그 컨테이너만 스왑이 막히므로 호스트 전역 설정을 건드릴 필요가 없다.

**`swapoff -a` 는 전용 서버임을 확인하기 전에는 쓰지 않는다.** 호스트의 모든 작업에 영향을 주고, 이미 스왑에 나가 있는 페이지를 메모리로 되돌리는 동안 메모리를 급격히 소모해 호스트 전체를 OOM으로 몰 수 있다. 스왑 장치의 위치에 대한 판단은 5.6절에 있다.

#### THP 설정 (권장)

THP가 `always` 이면 khugepaged가 뒤에서 페이지를 모으고 쪼개며 지연의 꼬리를 만든다. 우리 측정 대상이 바로 지연의 꼬리라서 이 변동이 병목으로 오인될 수 있다. 다만 Qdrant의 주 저장소는 파일 기반 mmap이라 THP의 영향이 익명 메모리만큼 크지 않을 수 있으므로, 값을 바꾸기보다 먼저 기록한다.

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/defrag
grep -E 'AnonHugePages|ShmemHugePages|FileHugePages' /proc/meminfo
```

`[always] madvise never` 형태로 현재 선택이 대괄호로 표시된다. 값을 기록하고 세 조건 내내 같은 값을 유지한다. 변경은 호스트 전역이므로 공유 서버에서는 합의가 필요하고, 변경했다면 측정 기록에 남긴다.

#### vm 계열 커널 파라미터 기록 (권장)

dirty 비율과 `min_free_kbytes` 와 `vfs_cache_pressure` 는 캐시 회수와 쓰기 몰림의 시점을 바꾼다. 조건을 바꿔 가며 재는 실험에서 이 값들이 도중에 달라지면 원인을 찾을 수 없게 된다.

```bash
sysctl vm.swappiness vm.overcommit_memory vm.overcommit_ratio \
       vm.dirty_ratio vm.dirty_background_ratio vm.dirty_expire_centisecs \
       vm.min_free_kbytes vm.vfs_cache_pressure vm.zone_reclaim_mode \
       vm.watermark_scale_factor vm.max_map_count
```

열한 줄이 모두 출력된다. 이 출력을 측정 기록의 부록에 그대로 붙여 둔다. 측정이 끝난 뒤 같은 명령을 다시 돌려 값이 바뀌지 않았음을 확인한다.

#### vm.max_map_count

Qdrant는 세그먼트마다 벡터와 payload와 색인 파일을 mmap으로 연다. 포인트 1억 개 규모에서는 매핑 수가 기본값 65530을 넘길 수 있고, 그러면 적재 도중 매핑 실패로 멈춘다. **다운로드까지 끝낸 뒤 적재에서 막히는 것이 가장 비싼 실패라 미리 올려 둔다.**

```bash
sysctl vm.max_map_count
# 부족하면 (호스트 전역 변경이다)
# sudo sysctl -w vm.max_map_count=1048576
# echo 'vm.max_map_count=1048576' | sudo tee /etc/sysctl.d/99-qdrant.conf
```

기본값 65530이면 1048576 정도로 올린다. 이미 262144 이상이면 그대로 두고 값을 기록한다. 이 값은 호스트 전역이지만 올리기만 하는 변경이라 다른 작업에 해를 주지 않는다.

#### drop_caches 실행 가능 여부와 그 파급

설계서 4.3절 대책 둘째와 3.3절 측정 위생이 조건을 바꿀 때마다 캐시를 비우도록 못 박았다. 이 명령은 호스트 전체의 페이지 캐시를 지우므로, 같은 서버에서 도는 다른 작업의 성능을 그 순간 크게 떨어뜨린다.

```bash
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
free -h
```

`free` 의 `buff/cache` 값이 실행 전보다 크게 줄어야 한다. 줄지 않으면 `cgroup_trap_check_2026-09-21.md` 4.1절의 경고대로 그 상태로 진행하면 안 된다. 공유 서버라면 이 명령이 다른 작업의 캐시까지 지운다는 점을 사전에 알리고 측정 시간대를 합의한다. 합의 절차는 6.3절에 있다.

#### OOM 이력과 커널 로그 (권장)

메모리 한도를 128GB로 낮춘 조건에서 Qdrant의 익명 메모리 사용이 한도를 넘으면 페이지 캐시 회수가 아니라 컨테이너 OOM 종료로 끝난다. 측정이 조용히 실패하는 대신 프로세스가 죽는 형태라, 기존 이력과 확인 방법을 미리 알아 두어야 원인을 빨리 특정한다.

**커널 로그 수집이 실패하면 그것을 "기록이 없다"로 읽으면 안 된다.** `kernel.dmesg_restrict` 가 1이면 비root의 `dmesg` 는 권한 오류로 끝나는데, 오류를 버리고 결과만 보면 아무 기록도 없는 상태와 구별되지 않는다. 그래서 sudo로 로그를 파일에 먼저 받고, 받기에 성공했는지를 확인한 뒤에 그 파일을 검색한다.

```bash
sysctl kernel.dmesg_restrict
sudo dmesg -T > ~/qdrant-prep/dmesg.txt || echo 'dmesg 수집 실패 — 권한을 확인한다'
sudo journalctl -k --since '-7 days' > ~/qdrant-prep/jkern.txt || echo 'journalctl -k 수집 실패'

grep -iE 'oom|killed process|page allocation failure' ~/qdrant-prep/dmesg.txt | tail -20
grep -i oom ~/qdrant-prep/jkern.txt | tail -20
grep -iE 'nvme|I/O error|medium error' ~/qdrant-prep/dmesg.txt | tail -10
```

두 수집 명령이 모두 실패 메시지 없이 끝나고, 그 뒤 세 검색에서 최근 OOM 기록과 디스크 오류 기록이 나오지 않아야 한다. 수집이 실패했다면 sudo를 받기 전까지 이 항목은 미확인으로 남긴다. 기록이 있으면 그 원인을 먼저 파악한다. 측정 중에는 컨테이너 cgroup의 `memory.events` 에서 `oom` 과 `oom_kill` 값을 함께 읽어 조건별로 기록한다.

### 3.6 디스크 장치와 파일시스템

이 절은 장치가 무엇인지 확인하는 데까지만 다룬다. 용량 계획과 장치 분리와 성능 기준선은 5장 저장 공간 설계에 있다.

이 절과 3.7절의 명령은 `$RAW` 와 `$BENCH` 를 쓴다. 두 경로는 5장에서 확정하지만, 여기서는 **후보 경로를 잠정으로 잡아 두고 검사한다.** 검사 결과가 5장의 요건에 맞지 않으면 후보를 바꿔 이 절을 다시 돌린다. 잠정 값은 `lsblk` 로 큰 장치를 찾아 정한다.

```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT | grep -v loop
export RAW=/mnt/raw      # 실제 마운트 지점으로 바꾼다
export BENCH=/mnt/bench
```

#### 장치 구성과 스케줄러와 readahead

설계서 1.3절의 디스크 판정과 2.3절의 읽기 발생 지표를 해석하려면 아래에 깔린 장치가 무엇인지 알아야 한다. 특히 **readahead 값은 주요 페이지 폴트 한 번에 커널이 실제로 읽어 오는 양을 정하므로, 이 값을 모르면 디스크 읽기량과 폴트 횟수의 관계를 해석할 수 없다.** 기존 문서에 readahead에 대한 언급이 없다.

장치 이름은 `lsblk` 의 `PKNAME`(상위 장치) 으로 얻는다. 장치 경로에서 숫자를 잘라 내는 방식은 `sda1` 에서만 맞고 NVMe에서는 깨진다. `/dev/nvme0n1` 은 `nvme0n` 이 되고 `/dev/nvme0n1p1` 은 `nvme0n1p` 가 되며, 장치 매퍼나 소프트웨어 RAID 경로에서도 엉뚱한 이름이 나온다. **이 절은 NVMe를 전제하므로 그 방식은 반드시 틀린다.**

```bash
lsblk -o NAME,SIZE,ROTA,TYPE,FSTYPE,MOUNTPOINT,MODEL
SRC=$(findmnt -T "$BENCH" -no SOURCE)          # -T 는 마운트 지점 아래 경로도 받는다
if [ -z "$SRC" ]; then
  echo "SRC 가 비어 있다. BENCH 가 마운트된 경로인지 확인한 뒤 이 블록을 다시 실행한다."
else
  DEV=$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1)
  [ -n "$DEV" ] || DEV=$(basename "$SRC")   # 파티션 없이 장치를 통째로 마운트한 경우
  echo "SRC=$SRC DEV=$DEV"
  for f in rotational scheduler read_ahead_kb nr_requests max_sectors_kb; do
    printf '%-16s %s\n' "$f" "$(cat /sys/block/$DEV/queue/$f)"
  done
  nvme list 2>/dev/null || echo 'nvme-cli 없음'
fi
```

**다섯 줄이 모두 값을 내는지 먼저 확인한다.** 이 절의 핵심 산출물은 `read_ahead_kb` 값이므로, `DEV` 를 잘못 잡아 `/sys/block/$DEV/queue` 가 없으면 다섯 줄이 모두 빈 채로 나오고 그것이 합격으로 읽힌다. 빈 줄이 하나라도 보이면 `lsblk -s "$SRC"` 로 장치 계층을 따라가 실제 블록 장치 이름을 다시 잡은 뒤 이 블록을 다시 돌린다.

값이 나왔으면 다음과 같이 읽는다. `rotational` 이 0이고 `scheduler` 가 `[none]` 또는 `[mq-deadline]` 이면 NVMe SSD로 본다. `read_ahead_kb` 값을 기록하고 세 조건 내내 같게 유지한다. `rotational` 이 1이면 회전 디스크이므로 설계서 4.2절의 디스크 읽기 해석을 전면 재검토해야 한다.

#### `$BENCH` 장치가 붙은 NUMA 노드

**NUMA 노드 선정은 이 값에서 출발한다.** Qdrant가 쓰는 코어와 메모리를 SSD가 붙은 노드에 두어야 디스크 읽기 경로에 노드 사이 전송이 섞이지 않는다. 그래서 코어를 먼저 고르고 노드를 맞추는 것이 아니라, `$BENCH` 가 놓인 NVMe가 어느 노드에 붙어 있는지를 먼저 보고 그 노드의 코어 열여섯 개와 메모리를 쓴다. 이 절의 `DEV` 를 그대로 쓴다.

```bash
cat /sys/block/$DEV/device/numa_node
lscpu | grep -E '^NUMA node[0-9]'
```

첫 줄이 노드 번호 하나를 출력해야 한다. `-1` 이 나오면 커널이 장치의 노드를 모르는 것이고, 그때는 `readlink -f /sys/block/$DEV/device` 로 PCI 장치 경로를 따라가 그 경로 위의 `numa_node` 파일을 읽는다. 둘째 줄은 노드별 CPU 목록이다. 첫 줄의 노드 번호에 해당하는 CPU 목록이 Qdrant 코어 열여섯 개를 뽑을 범위이고, 나머지 노드의 코어가 부하 도구와 수집기 몫이다. 이 노드 번호와 CPU 목록을 기록 파일에 적고 `environment_setup_2026-09-21.md` 3.1절에 넘긴다. 그 노드의 메모리가 512GB 이상인지는 3.4절에서 본다.

#### 파일시스템 종류와 마운트 옵션과 압축 여부

`cgroup_trap_check_2026-09-21.md` 2장이 btrfs와 zfs의 압축을 경고했는데, 그 경고는 더미 파일뿐 아니라 **Qdrant의 실제 데이터에도 그대로 적용된다.** 상세한 이유는 5.2절에 있다.

```bash
findmnt -T "$BENCH" -no SOURCE,FSTYPE,OPTIONS || echo "BENCH 의 마운트를 찾지 못했다"
findmnt -T "$RAW" -no SOURCE,FSTYPE,OPTIONS || echo "RAW 의 마운트를 찾지 못했다"
stat -fc '%T' $BENCH
mount | grep -E 'compress|zfs|btrfs' || echo '압축 마운트 옵션 없음'
zfs get compression 2>/dev/null | head -5
btrfs property get $BENCH compression 2>/dev/null
```

ext4 또는 xfs이고 압축 옵션이 없어야 한다. `noatime` 여부도 함께 기록한다.

#### 논리 볼륨 계층과 io.stat 귀속 (권장)

데이터 경로가 LVM이나 소프트웨어 RAID나 dm-crypt 위에 있으면, 컨테이너 cgroup의 `io.stat` 이 어느 장치 번호로 집계되는지가 달라지고 하위 물리 장치의 읽기와 일치하지 않을 수 있다. 설계서 3.1절이 `io.stat` 을 진짜 디스크 읽기의 근거로 삼고 있으므로 귀속이 흐려지면 그 근거가 약해진다.

```bash
SRC=$(findmnt -T "$BENCH" -no SOURCE)          # -T 는 마운트 지점 아래 경로도 받는다
if [ -z "$SRC" ]; then
  echo "SRC 가 비어 있다. BENCH 가 마운트된 경로인지 확인한 뒤 이 블록을 다시 실행한다."
else
  lsblk -s "$SRC"
  dmsetup ls 2>/dev/null || echo 'device-mapper 매핑 없음'
  cat /proc/mdstat 2>/dev/null
  PK=$(lsblk -no PKNAME "$SRC" 2>/dev/null | head -1)
  DISK=${PK:-$(basename "$SRC")}                 # 파티션이면 부모 디스크, 통짜 디스크면 자기 자신
  IODEV=$(lsblk -dno MAJ:MIN "/dev/$DISK")
  echo "SRC=$SRC DISK=$DISK IODEV=$IODEV"        # IODEV 를 io.stat 의 첫 열과 대조한다
fi
```

`io.stat` 의 첫 열에 나오는 `MAJ:MIN` 은 파티션이 아니라 그 파티션이 놓인 디스크의 `MAJ:MIN`, 즉 위의 `IODEV` 와 같아야 한다. cgroup v2 의 `io.stat` 은 파티션이 아니라 디스크(request_queue) 단위로 집계하기 때문이다. `$BENCH` 가 파티션 위에 마운트되어 있으면 `SRC` 의 번호가 아니라 부모 디스크의 번호를 쓴다. dm이나 LVM이나 md 위에 있는 경우에는 한 단계 위가 맞는 장치인지 확인하지 못했으므로, 그때는 `lsblk -s` 의 계층을 보고 실제로 `io.stat` 에 나타나는 번호와 대조한다. 계층이 여러 겹이면 컨테이너 읽기량을 `io.stat` 대신 주요 페이지 폴트 횟수와 Qdrant의 hardware metric으로 교차 확인하도록 측정 절차를 보강한다.

#### 파일 디스크립터와 프로세스 한도 (권장)

세그먼트가 많아지면 Qdrant가 여는 파일 수가 크게 늘어난다. 기본 한도인 1024로는 대규모 적재 중 파일 열기 실패가 난다. 호스트의 한도와 컨테이너에 실제로 적용되는 한도가 다르므로 양쪽을 모두 본다.

```bash
ulimit -n; ulimit -u
cat /proc/sys/fs/file-max
docker run --rm alpine sh -c 'ulimit -n'
sudo cat /etc/docker/daemon.json || echo '/etc/docker/daemon.json 없음 — 데몬 기본값을 쓴다'
```

마지막 줄이 호스트 쪽 창구다. **`docker info` 에는 데몬 기본 ulimit을 보여 주는 필드가 없어** `{{json .DefaultUlimits}}` 같은 서식은 평가 오류로 끝난다. 데몬이 컨테이너에 물려주는 기본 한도는 `/etc/docker/daemon.json` 의 `default-ulimits` 항목으로 확인하고, 그 항목이 없으면 데몬 자신의 프로세스 한도가 그대로 내려간다.

컨테이너 안 `ulimit -n` 이 65535 이상이어야 한다. 부족하면 `docker run` 에 `--ulimit nofile=65535:65535` 를 붙이고, 그 값을 측정 절차에 고정으로 적는다.

### 3.7 Qdrant 컨테이너의 실제 동작 확인

**이것이 세 번째로 큰 공백이다.** 컨테이너 안에서 `/proc/cpuinfo` 는 호스트의 344개를 그대로 보여 준다. Qdrant가 cgroup의 cpuset을 읽지 않고 이 값을 쓴다면 스레드를 수백 개 만들어 코어 열여섯 개 위에서 문맥 교환만 하게 되고, 그러면 우리가 관측하는 것은 Qdrant의 병목이 아니라 **과도한 스레드 경합**이 된다. 기존 문서 어디에도 이 확인이 없다.

바인드 마운트가 쓰기 가능한지도 같은 자리에서 확인한다. 컨테이너의 쓰기 계층에 데이터를 두면 overlay2를 거치게 되어 읽기 경로와 `io.stat` 귀속이 달라지고, 조건을 바꿀 때마다 컨테이너를 새로 만들라는 설계서 4.3절 대책 첫째를 따르면 데이터가 함께 사라진다.

```bash
if [ -z "$BENCH" ]; then
  echo "BENCH 가 비어 있다. 3.6절의 export 줄로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  mkdir -p "$BENCH/qdrant/work"
  findmnt -T "$BENCH/qdrant/work"

  # --cpuset-cpus=0-15 는 예시 값이다. 실제 코어는 3.6절에서 정한 노드의 것을 쓴다
  docker run -d --name qtest --cpuset-cpus=0-15 --memory=8g --memory-swap=8g \
    -p 6333:6333 -v "$BENCH/qdrant/work:/qdrant/storage" qdrant/qdrant:v1.19.1
  sleep 10
  docker exec qtest sh -c 'ls /proc/1/task | wc -l'
  docker logs qtest 2>&1 | head -30
  curl -s 'localhost:6333/telemetry?details_level=1' | head -c 800; echo
  docker rm -f qtest
fi
```

`findmnt` 가 앞서 확인한 데이터 파일시스템을 가리켜야 하고, 컨테이너가 오류 없이 떠야 한다. 권한 오류가 나면 디렉터리 소유자와 SELinux 라벨을 확인한다.

프로세스의 스레드 수가 수백 개가 아니라 **코어 수에 비례하는 수십 개**여야 한다. 수백 개가 나오면 Qdrant 설정에서 검색과 최적화의 스레드 수를 명시적으로 지정하고, 그 값을 설계서 4.1절에 적는다.

### 3.8 격리 — 서버를 누가 함께 쓰는가

설계서 4.3절의 대책과 이 문서의 여러 확인 명령이 호스트 전역에 영향을 준다. 특히 페이지 캐시 비우기와 스왑 끄기와 sysctl 변경은 같은 서버의 다른 작업을 직접 망가뜨린다. **전용인지 공유인지가 정해져야 어떤 명령을 써도 되는지가 정해진다.**

```bash
who; w
ps -eo pid,user,pcpu,rss,etime,comm --sort=-pcpu | head -15
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
systemd-cgtop -n 1 2>/dev/null | head -15
last -n 10
```

다른 사용자의 로그인과 다른 컨테이너가 없으면 전용으로 보고 전역 명령을 써도 된다. 있으면 주인을 찾아 측정 시간대를 합의하고, 그 전까지는 `drop_caches` 와 `swapoff` 와 sysctl 변경을 쓰지 않는다. 합의 절차는 6.3절에 있다.

이어서 주기 작업과 다른 컨테이너와 GPU와 포트와 시계를 본다. 백업과 파일 색인과 로그 정리 같은 주기 작업은 측정 도중에 디스크와 페이지 캐시를 휘저어 결과를 오염시킨다. 한도를 걸지 않은 다른 컨테이너가 있으면 그쪽이 페이지 캐시를 채우고 우리 컨테이너의 캐시를 밀어내어, 메모리 한도를 바꾸지 않았는데도 조건이 흔들린다.

```bash
systemctl list-timers --all | head -20
ls /etc/cron.d /etc/cron.daily /etc/cron.hourly 2>/dev/null
crontab -l 2>/dev/null || echo '개인 crontab 없음'
systemctl is-enabled unattended-upgrades 2>/dev/null
uptime -s; ls /etc/sysctl.d/

docker stats --no-stream
# cgroup 경로는 Docker 의 cgroup 드라이버에 따라 다르므로 /proc/<pid>/cgroup 에서 직접 읽는다.
# 경로를 박아 두면 드라이버가 다를 때 아무것도 찾지 못한 채로 통과한다.
for c in $(docker ps -q); do
  p="$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null)"
  g="/sys/fs/cgroup$(grep '^0::' "/proc/$p/cgroup" 2>/dev/null | cut -d: -f3)"
  if [ -r "$g/memory.max" ]; then
    printf '%s max=%s current=%s\n' "$(docker inspect -f '{{.Name}}' "$c")" \
      "$(cat "$g/memory.max")" "$(cat "$g/memory.current")"
  else
    printf '%s 판정불가 (cgroup 을 읽지 못함)\n' "$c"
  fi
done

nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
ss -lntp | grep -E ':(6333|6334|4040|9090)' || echo '해당 포트 비어 있음'
sysctl kernel.perf_event_paranoid kernel.kptr_restrict
cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null
timedatectl status
chronyc tracking 2>/dev/null || ntpq -p 2>/dev/null || echo 'NTP 클라이언트 없음'
getenforce 2>/dev/null || echo 'SELinux 없음'
if command -v aa-status >/dev/null; then aa-status | head -3; else echo 'AppArmor 없음'; fi
```

마지막 줄을 `aa-status | head -3 || echo ...` 로 적으면 안 된다. `||` 가 보는 것은 파이프라인의 마지막 명령인 `head` 의 종료 상태이고 `head` 는 언제나 0이라, AppArmor가 없어도 대체 출력이 나오지 않는다.

판정 기준은 다음과 같다.

| 확인 대상 | 합격 | 어긋날 때 |
|---|---|---|
| 주기 작업 타이머 | 측정 시간대와 겹치는 것이 없다 | `updatedb` 나 백업이나 `unattended-upgrades` 가 겹치면 시간대를 피하거나 일시 정지를 합의한다 |
| 다른 컨테이너 | 없거나 모두 메모리 한도가 걸려 있다 | 한도 없는 컨테이너가 있으면 멈추도록 합의하고, 어려우면 우리 컨테이너에 `memory.low` 를 설정해 최소한의 캐시를 보호한 뒤 그 사실을 기록한다 |
| GPU | 실행 중인 다른 프로세스가 없다 | 합성 데이터 생성 시간대를 분리하고, 부하 측정 중에는 GPU 작업을 돌리지 않는다 |
| 포트 6333, 6334, 4040, 9090 | 비어 있다 | 다른 포트로 바꾸고 절차 문서에 반영한다 |
| `perf_event_paranoid` | perf를 쓸 계획이면 1 이하 | `qdrant_instrumentation_2026-09-17.md` 9장이 컨테이너에서 perf를 붙이는 데 필요한 권한을 미확인으로 남겨 두었으므로 실제로 붙여 보고 결과를 그 문서에 채워 넣는다 |
| 시계 동기화 | `System clock synchronized: yes` | 동기화되지 않으면 측정 구간을 절대 시각이 아니라 단조 증가 시계 기준의 경과 시간으로 기록하도록 절차를 바꾼다 |
| SELinux | `Disabled` 또는 `Permissive` | `Enforcing` 이면 바인드 마운트에 `:z` 또는 `:Z` 가 필요할 수 있으므로 3.7절의 쓰기 확인을 반드시 통과시킨 뒤에 진행한다 |
| 재부팅 일정 | 측정 기간에 없다 | 바꾼 커널 파라미터는 `/etc/sysctl.d` 아래 파일로 남기고 그 사실을 측정 기록에 적는다 |

### 3.9 이 단계가 끝났다는 것을 어떻게 아는가

다음 여섯 가지가 모두 참이면 준비 1이 끝난 것이다.

1. `~/qdrant-prep/server_check_*.txt` 에 3.1절부터 3.8절까지의 출력이 모두 들어 있다.
2. 3.1절의 네 값이 설계 전제와 같거나, 다르다면 설계서 4.1절과 4.5.5절을 고쳤다.
3. 3.3절의 컨테이너 계수기 실물 확인에서 `memory.max` 와 `memory.events` 의 `max` 행과 `workingset_refault_file` 과 `io.stat` 을 모두 읽었다.
4. 3.4절에서 NUMA 노드당 메모리 용량을 알고, 512GB 조건이 노드 하나 안에서 성립하는지에 대한 답을 설계서 4.2절에 적었다.
5. 3.6절에서 `$BENCH` 장치가 붙은 NUMA 노드 번호와 그 노드의 CPU 목록을 기록했다.
6. 3.7절에서 Qdrant 컨테이너의 스레드 수를 세었고 그 값을 기록했다.

이 여섯이 끝나면 **1.2 조건에 맞춰 띄우기(`environment_setup_2026-09-21.md` 3장)에 바로 들어갈 수 있다.** 1.3 함정 확인은 이미 완료되어 있다.

---

## 4. 준비 2. 도구 설치

세 문서가 실제로 호출하는 외부 명령을 전부 뽑아 보면 종류가 많지 않다. **Docker와 curl과 python3와 GNU coreutils 네 가지가 사실상 전부다.** 다만 그 넷이 모두 GNU 리눅스 판이어야 한다는 조건이 붙는다.

진짜 결정이 필요한 준비 항목은 두 가지다. 하나는 계측 빌드를 호스트 Rust 툴체인으로 할지 Docker 빌드로 할지이며 이것은 8.2절에서 다룬다. 다른 하나는 파이썬 패키지를 시스템에 깔지 가상환경에 깔지이며 4.6절에서 다룬다.

### 4.1 필수 도구 한 줄 점검

이 문서의 확인 명령과 설계서의 측정 절차가 기대는 도구들이 서버에 없으면 그 자리에서 막힌다. 설치에는 패키지 관리자 권한이 필요하므로 부족한 것을 한 번에 묶어 요청하는 편이 낫다.

```bash
for c in curl jq python3 awk numactl fio lsblk findmnt ss iostat pidstat mpstat \
         tmux screen aws git perf cpupower turbostat nvme dmidecode unzip xargs \
         blktrace blkparse fincore; do
  printf '%-12s %s\n' "$c" "$(command -v $c 2>/dev/null || echo '없음')"
done
```

curl과 jq와 python3와 awk와 lsblk와 findmnt와 ss와 xargs는 **반드시** 있어야 한다. numactl과 fio와 sysstat 계열과 cpupower가 없으면 설치를 요청한다. blktrace 와 blkparse 는 5.1 예비 측정 전까지 있으면 되고, 상세는 4.8절에 있다. `fincore` 는 `environment_setup_2026-09-21.md` 의 게이트 A가 직접 의존하는 도구다. Debian 12/13 과 Ubuntu 24.04 에서는 `util-linux` 본체가 아니라 `util-linux-extra` 패키지에 들어 있으므로 4.2절의 설치 줄에 그 패키지를 포함했다.

### 4.2 한 번에 설치하기

데비안 계열이면 아래 두 묶음으로 부족한 것을 대부분 받는다. **한 줄로 합치면 안 된다.** `apt-get install` 은 전부 아니면 전무로 동작하므로, 목록에 그 배포판에 없는 패키지가 하나라도 섞이면 numactl과 fio와 sysstat까지 하나도 깔리지 않는다. `linux-tools-common` 과 `linux-tools-$(uname -r)` 는 우분투 전용이고, 우분투라도 배포판이 제공하지 않는 커널을 쓰고 있으면 `linux-tools-$(uname -r)` 가 없어 같은 방식으로 죽는다. 그래서 배포판과 무관한 것을 먼저 깔고, 커널 의존 패키지는 따로 시도한다.

```bash
sudo apt-get update
sudo apt-get install -y numactl fio sysstat nvme-cli jq gawk tmux unzip blktrace bpfcc-tools util-linux-extra
```

```bash
# 우분투이고 배포판 커널을 쓸 때
sudo apt-get install -y linux-tools-common "linux-tools-$(uname -r)"
# 데비안일 때
sudo apt-get install -y linux-perf linux-cpupower
# 두 계열 공통. bcc 도구가 실행 시점에 BPF 프로그램을 컴파일하므로 실행 중인 커널의 헤더가 필요하다
sudo apt-get install -y "linux-headers-$(uname -r)"
```

두 계열의 패키지 이름 차이는 다음과 같다.

| 도구 | Ubuntu | Debian |
|---|---|---|
| perf | `linux-tools-common` 과 `linux-tools-$(uname -r)` | `linux-perf` |
| cpupower | `linux-tools-common` 에 함께 들어 있다 | `linux-cpupower` |

레드햇 계열이면 `dnf install -y numactl fio sysstat nvme-cli jq gawk tmux unzip perf blktrace bcc-tools` 를 쓴다. blktrace 와 bcc 도구의 용도와 요구사항은 4.8절에 있다. 설치 후 4.1절의 점검을 다시 돌려 `없음` 이 남아 있지 않은지 확인한다. perf와 cpupower는 권장 도구이므로, 커널 의존 패키지가 끝내 깔리지 않아도 나머지 준비는 그대로 진행한다.

### 4.3 GNU coreutils 확인

`cgroup_trap_check.sh` 가 GNU 전용 옵션을 여럿 쓴다. `FSTYPE` 계산의 `stat -fc %T`, `ACTUAL_MB` 와 `APPARENT` 와 `ALLOCATED` 계산의 `stat -c %s` 와 `%b` 와 `%B`, 더미 파일 생성의 `dd ... status=progress`, `run_case()` 에서 `t0` 과 `t1` 을 재는 `date +%s.%N` 이 그것이다. 다운로드 가이드는 `seq -w 0 99` 와 `du -cb` 와 체크섬 확인을 쓴다. 이 옵션들은 전부 GNU 판 전용이라 BSD 판에서는 동작하지 않는다.

```bash
stat --version | head -1
dd --version | head -1
date +%s.%N
seq -w 0 3
sha256sum --version | head -1
md5sum --version | head -1
```

각 버전 줄에 `(GNU coreutils)` 가 붙어야 하고, `date +%s.%N` 이 소수점 아래 아홉 자리를 붙여 출력해야 한다. **`%N` 이 글자 그대로 나오면 GNU date가 아니므로 스크립트의 소요 시간 계산이 깨진다.**

텍스트 처리 유틸도 함께 본다. 스크립트가 `/proc/meminfo` 의 `MemAvailable` 과 `Cached` 를 awk로 읽고(`FREE_MB` 계산과 `cached_mb()`), `io.stat` 의 `rbytes` 를 awk로 합산하며(`rbytes()`), `memory.events` 의 `max` 값을 awk로 뽑고(`maxev`), 최종 판정식도 awk로 계산한다(`B_PRESSURED` 와 `SIG_IO` 와 `SIG_MEM`). 컨테이너 cgroup 경로는 `cg_of()` 가 `grep '^0::' /proc/$pid/cgroup | cut -d: -f3` 으로 얻는다. 스크립트가 고쳐질 때마다 줄이 밀리므로 줄 번호 대신 변수와 함수 이름으로 가리킨다.

```bash
{ awk --version 2>/dev/null || awk -W version 2>&1; } | head -1
grep --version | head -1
cut --version | head -1
```

첫 줄에서 중괄호로 묶은 이유가 있다. `awk --version | head -1 || awk -W version` 처럼 적으면 `||` 가 파이프라인의 마지막 명령인 `head` 의 종료 상태를 보게 되고 `head` 는 언제나 0이므로, `--version` 을 모르는 mawk에서도 대체 경로가 실행되지 않는다. 묶어 두어야 `awk` 자신의 실패가 `||` 에 전달된다.

세 명령이 모두 버전을 출력하면 된다. Debian 기본은 mawk다. Debian 12 의 mawk 는 2^31 을 넘는 정수를 `3.8552e+11` 같은 지수 표기로 출력해 그 값을 받은 bash 산술이 죽으므로, 스크립트의 `rbytes()` 합산은 `print s+0` 이 아니라 `printf "%.0f\n", s` 로 출력한다. 이 형식은 mawk 와 gawk 모두에서 정수 자릿수를 그대로 낸다. 그 밖의 문법은 POSIX awk 범위로 보이지만 mawk에서 전부 돌려 확인하지는 않았으므로, 불안하면 4.2절에 포함한 `gawk` 를 쓴다.

`free` 도 확인한다. `cgroup_trap_check_2026-09-21.md` 4.1절이 캐시를 비운 뒤 `free -h` 의 `buff/cache` 가 줄었는지 확인하라고 하고, 5.1절은 조건 A에서 `buff/cache` 가 16GB 이상 늘어야 한다고 못 박는다.

```bash
free -h
# 없으면: sudo apt-get install -y procps
```

### 4.4 Docker와 cgroup v2와 BuildKit

1.3 함정 확인과 1.2 조건에 맞춰 띄우기와 메모리 한도 스윕이 전부 Docker 컨테이너와 cgroup v2 계수기에 기대고 있다. 확인 명령은 3.2절과 3.3절에 있으므로 여기서는 빌드 쪽만 본다.

계측 빌드를 Docker로 만들 경우 buildx가 필요하다. Qdrant v1.19.1의 Dockerfile이 `FROM --platform=${BUILDPLATFORM:-linux/amd64}` 와 `COPY --from=xx / /` 를 쓰고 `ARG BUILDPLATFORM` 과 `ARG TARGETPLATFORM` 에 의존하므로 구형 빌더로는 빌드가 되지 않는다.

```bash
docker buildx version
docker info --format '{{.ClientInfo.Plugins}}'
# 없으면 Docker 공식 저장소에서: sudo apt-get install -y docker-buildx-plugin
```

`github.com/docker/buildx v...` 형태의 한 줄이 나와야 한다. BuildKit이 기본이 아닌 구버전이면 `DOCKER_BUILDKIT=1 docker build ...` 로 명시해서 쓴다.

### 4.5 컨테이너 이미지 사전 내려받기

`cgroup_trap_check.sh` 가 사전 확인의 `docker image inspect` 와 `docker pull` 단계에서 이미지를 측정 전에 미리 받아 두라고 명시하고 그 이유를 적어 두었다. **캐시를 비운 뒤에 내려받으면 그 과정이 페이지 캐시를 오염시켜 조건 A와 조건 B의 비교가 무의미해진다.** 빌드 베이스 이미지도 미리 받아 두면 빌드 시점에 네트워크가 막혀 있어도 진도가 나간다.

```bash
docker pull alpine
docker pull qdrant/qdrant:v1.19.1
docker pull lukemathwalker/cargo-chef:latest-rust-1.98.0-bookworm
docker pull tonistiigi/xx
docker pull debian:13-slim
docker image ls
docker image inspect qdrant/qdrant:v1.19.1 \
  --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Created}}'
```

다섯 이미지가 모두 목록에 보이고 아키텍처가 서버와 맞아야 한다. 베이스 이미지 이름은 Qdrant v1.19.1 Dockerfile에서 읽어 온 것이다. `v1.19.1` 태그가 없다고 나오면 실제 태그 목록을 확인해 설계서가 고정한 버전과 맞는 태그를 찾는다. **이 태그의 존재는 이번 세션에서 확인하지 못했다.**

`cgroup_trap_check_2026-09-21.md` 부록 B의 mmap 확인은 alpine 컨테이너 안에서 `apk add -q python3` 를 실행한다. 이는 컨테이너가 외부 망에 나갈 수 있어야 하고 그 설치 과정이 페이지 캐시에 영향을 줄 수 있다는 뜻이므로, python3가 미리 들어 있는 이미지를 만들어 두고 쓰는 편이 안전하다.

```bash
printf 'FROM alpine\nRUN apk add --no-cache python3\n' | docker build -t alpine-py -
docker run --rm alpine-py python3 -V
```

이 이미지를 쓰기로 했다면 부록 B의 명령에서 `apk add -q python3 &&` 를 빼고 이미지 이름을 `alpine-py` 로 바꾼다.

### 4.6 python3와 가상환경

S3 목록 XML 파싱(다운로드 가이드 3.3절), parquet footer 해석(5.2절), 행 수와 차원과 노름 확인(6.3절), 정답 범위 확인(6.4절), big-ann 헤더 고쳐 쓰기(5.3절)가 전부 python3다. 세션 라벨 parquet 를 미리 만드는 일은 없다. 세션 배정은 부하 도구의 적재기(3.2)가 적재 시점에 하며, 상세는 `emulator_spec_2026-09-21.md` 3.3절과 다운로드 가이드 3.8절에 있다. Debian 계열은 pip와 venv가 python3 본체와 별도 패키지다.

```bash
python3 --version
python3 -m pip --version
python3 -m venv --help >/dev/null && echo 'venv ok'
# 없으면: sudo apt-get install -y python3 python3-pip python3-venv
```

**여기서 결정이 하나 필요하다.** 다운로드 가이드 곳곳의 명령이 `python3 -m pip install --quiet pyarrow numpy` 처럼 시스템 파이썬에 바로 설치한다. 그런데 Debian 12 이상과 Ubuntu 23.04 이상에서는 시스템 파이썬이 externally-managed로 표시되어 이 명령이 거부되고, 문서를 그대로 따라가면 여기서 막힌다. 가상환경을 하나 만들어 두고 문서의 pip 명령을 그 안에서 돌리면 이 문제도 없고, 측정 서버의 배포판 도구를 파이썬 패키지로 깨뜨릴 위험도 피한다. 실험이 여러 주에 걸치므로 패키지 버전을 한곳에 묶어 두는 이점도 있다.

```bash
ls /usr/lib/python3*/EXTERNALLY-MANAGED 2>/dev/null && echo '시스템 pip 차단됨'

python3 -m venv ~/venv/qdrant-bench
~/venv/qdrant-bench/bin/python -m pip install --upgrade pip
~/venv/qdrant-bench/bin/pip install pyarrow numpy h5py
~/venv/qdrant-bench/bin/python -c \
  "import pyarrow, numpy, h5py; print(pyarrow.__version__, numpy.__version__, h5py.__version__)"
~/venv/qdrant-bench/bin/python -c \
  "import pyarrow; print('zstd:', pyarrow.Codec.is_available('zstd'))"
```

`EXTERNALLY-MANAGED` 파일이 보이면 가상환경이 사실상 필수다. 보이지 않더라도 가상환경을 권한다. 마지막 두 줄에서 세 버전과 `zstd: True` 가 나오면 통과다. zstd 확인은 원래 다운로드 가이드 3.8절의 세션 라벨 parquet 생성을 위한 것이었으나 그 방식은 폐기되었다. 원본 parquet 를 읽을 때 코덱이 없으면 읽기 자체가 실패하므로 확인은 그대로 둔다.

**가상환경을 쓰기로 했다면 이후 문서에 나오는 모든 `python3` 는 `~/venv/qdrant-bench/bin/python` 으로 바꿔 읽고, 문서를 고칠 때 이 치환을 함께 반영한다.** h5py는 다운로드 가이드 2.2절 SIFT 스모크 테스트의 HDF5 확인에만 쓰이므로, 스모크를 2.3절의 Zilliz parquet 쪽으로 하면 생략할 수 있다.

### 4.7 AWS CLI와 Hugging Face CLI (권장)

다운로드 가이드 3.6절이 본체 받기의 권장 경로로 `aws s3 cp --no-sign-request --recursive` 를 든다. 재시도와 병렬 전송을 알아서 처리하고, `aws configure set default.s3.max_concurrent_requests 16` 으로 동시 전송 폭을 조절한다. **익명 접근이므로 자격 증명이나 계정은 필요 없다.**

```bash
aws --version
# 없으면: sudo apt-get install -y awscli
# 또는 공식 번들:
# curl -sL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip \
#   && unzip -q awscliv2.zip && sudo ./aws/install
aws s3 ls --no-sign-request s3://assets.zilliz.com/benchmark/laion_large_100m/ | head -3
```

버전이 출력되고 목록 조회가 자격 증명 오류 없이 파일 이름과 크기를 돌려주어야 한다. apt로 깔면 v1, 공식 번들로 깔면 v2인데 어느 판이 깔릴지와 두 판의 동작 차이는 확인하지 못했다. 다운로드 가이드 3.7절의 curl 병렬 경로가 대안이므로 막히면 그쪽으로 간다.

Hugging Face CLI는 주 데이터 경로에서는 필요 없다. 라이선스 문제로 후보를 갈아탈 때만 필요하므로 6.7절에서 다룬다.

### 4.8 관측 도구 (나중에 필요하다)

Pyroscope와 Prometheus는 1단계(Qdrant Docker 환경 준비)에서는 없어도 된다. **병목 원인을 CPU 쪽으로 좁힌 뒤에야 필요하므로, 준비 단계에서는 이미지를 받아 두고 결정 사항만 적어 둔다.**

`qdrant_instrumentation_2026-09-17.md` 7.1절이 재빌드 없이 쓸 수 있는 유일한 프로파일러로 Pyroscope를 들고 있고, 설계서 3.1절도 "CPU를 어느 함수가 쓰나" 항목의 수단으로 지정한다. Qdrant 쪽은 `PATCH /debugger` 로 연결만 하면 되지만 받는 쪽 서버는 우리가 띄워야 한다.

```bash
docker pull grafana/pyroscope
docker pull prom/prometheus
```

Prometheus 쪽에는 결정해야 할 것이 하나 있다. 설계서 3.1절과 `qdrant_instrumentation_2026-09-17.md` 8장이 검색 p99를 `/metrics` 히스토그램에서 `histogram_quantile()` 로 계산한다고 적었는데 이는 PromQL 함수이므로 Prometheus 계열 수집기를 전제한다. 동시에 같은 문서 3.3절이 `/metrics` 스크레이프가 전 세그먼트에 읽기 잠금을 걸어 그 자체가 부하라고 경고하고, 설계서 3.3절이 스크레이프 주기를 고정하고 기록하라고 요구한다. **즉 수집기를 쓰든 직접 찍든 주기를 고정하는 장치가 필요하고, 그 주기 값을 준비 단계에서 정해 기록해야 한다.**

#### 블록 수준 I/O 추적 — blktrace 와 bcc 도구

`$BENCH` 장치에는 Qdrant 저장소만 있으므로(5.3절) 그 장치의 블록 I/O 는 곧 Qdrant 의 I/O 다. 이 장치에 블록 수준 추적을 걸면 요청 크기와 큐 깊이와 장치 지연을 요청 단위로 볼 수 있어, 계측 지점 18개소가 보여 주는 단계별 시간과 `io.stat` 의 읽기량 사이를 잇는 근거가 된다. 도구는 두 계열이다. `blktrace` 는 모든 블록 이벤트를 남기므로 정보가 가장 많지만 오버헤드가 IOPS 에 비례해 커진다. bcc 의 `biolatency` 와 `biosnoop` 은 eBPF 로 커널 안에서 집계하므로 오버헤드가 낮은 대안이다. **어느 쪽을 쓸지와 어느 조건에서 켤지는 5.1 예비 측정에서 비용을 재어 정하고, 5.2 본 측정에서 항상 켜지는 않는다.**

패키지 이름과 요구사항은 다음과 같다. 두 도구 모두 root 가 필요하다.

| 도구 | Debian / Ubuntu | 레드햇 계열 | 커널 쪽 요구사항 |
|---|---|---|---|
| blktrace, blkparse, btt | `blktrace` | `blktrace` | `CONFIG_BLK_DEV_IO_TRACE=y` 이고 `/sys/kernel/debug` 에 debugfs 가 마운트되어 있어야 한다 |
| biolatency, biosnoop | `bpfcc-tools` (실행 파일은 `biolatency-bpfcc` 처럼 `-bpfcc` 접미사가 붙는다) | `bcc-tools` (실행 파일은 `/usr/share/bcc/tools/` 아래에 있다) | `CONFIG_BPF_SYSCALL=y` 이고 실행 중인 커널의 헤더 패키지(`linux-headers-$(uname -r)`)가 있어야 실행 시점 컴파일이 된다 |

```bash
command -v blktrace blkparse btt
command -v biolatency-bpfcc biosnoop-bpfcc || ls /usr/share/bcc/tools/biolatency /usr/share/bcc/tools/biosnoop
grep -E 'CONFIG_BLK_DEV_IO_TRACE|CONFIG_BPF_SYSCALL' "/boot/config-$(uname -r)"
mount | grep -q debugfs && echo 'debugfs 마운트됨' || echo 'debugfs 없음. sudo mount -t debugfs none /sys/kernel/debug'
ls -d "/lib/modules/$(uname -r)/build" 2>/dev/null || echo '커널 헤더 없음. bcc 도구가 실행 시점 컴파일에 실패한다'
```

세 도구의 경로가 모두 나오고, 두 CONFIG 값이 `y` 이며, debugfs 가 마운트되어 있고, 커널 헤더 디렉터리가 있어야 한다. 커널 헤더가 끝내 없으면 bcc 계열은 쓸 수 없고 blktrace 만 남는다.

**출력은 반드시 `$RAW` 에 쓴다.** `blktrace -d /dev/$DEV -D $RAW/blktrace/...` 처럼 출력 디렉터리를 명시한다. `$BENCH` 에 쓰면 그 쓰기가 측정 항목 11(게이트 C 의 `rbytes`)이 보는 장치 통계에 섞여 판정을 오염시킨다. 용량은 5.1절에 있다.

### 4.9 이 단계가 끝났다는 것을 어떻게 아는가

1. 4.1절의 점검에서 필수 도구에 `없음` 이 남아 있지 않다.
2. 4.3절에서 `date +%s.%N` 이 나노초를 출력했다.
3. 4.5절의 다섯 이미지가 `docker image ls` 에 보인다.
4. 4.6절에서 pyarrow와 numpy의 버전이 출력되고 `zstd: True` 가 나왔다.
5. 파이썬을 시스템에 쓸지 가상환경에 쓸지 정했고, 가상환경을 택했다면 다운로드 가이드의 `python3` 치환 규칙을 적어 두었다.
6. 4.8절의 blktrace 와 bcc 도구가 있거나, 없으면 5.1 예비 측정 전까지 설치되도록 요청을 보냈다.

---

## 5. 준비 3. 저장 공간 설계

### 5.1 총 용량 계산

필요한 디스크는 필수 경로 기준 약 **2.44TB**이고 선택 데이터까지 모두 쓰면 약 **4.70TB**로, 16TB의 각각 15.2%와 29.4%다. 따라서 설계서 4.5.5절이 적은 대로 용량 자체는 제약이 아니다.

핵심 수치는 **laion 768차원 1억 개 컬렉션 한 벌이 약 385.52GB**라는 것이다. 산식은 다음과 같다.

```
벡터        = 포인트 수 × 차원 × 4바이트(float32)
            = 100,000,000 × 768 × 4 = 307,200,000,000 바이트 = 307.20GB   [확정]
payload     = 포인트 수 × 포인트당 payload 바이트
            = 100,000,000 × 500      =  50,000,000,000 바이트 =  50.00GB   [어림]
payload 색인 (long_term 11개 기준)                             =  13.60GB   [어림. 12개 항목 기준이라 11개로는 약간 준다. 11.3절]
payload_m=16 링크                                      0 ~       14.72GB   [어림, 상한]
------------------------------------------------------------------------
컬렉션 한 벌 (링크를 상한으로 잡았을 때)                      = 385.52GB
```

벡터 307.20GB가 전체의 79.7%를 차지하며 이 값만 확정값이다. 나머지 셋은 모두 어림값이고, 그 근거와 위험은 11.3절에 있다.

이 크기 덕분에 **설계서 4.2절의 메모리 사다리가 실제 기울기를 만든다.**

| 메모리 한도 | 상주하지 못하는 양 | 비율 |
|---:|---:|---:|
| 512GB | 0GB | 0% (전부 상주) |
| 256GB | 129.52GB | 33.6% |
| 128GB | 257.52GB | 66.8% |

즉 세 조건이 "전부 상주", "3분의 1이 디스크", "3분의 2가 디스크"로 깔끔하게 갈린다. **그래서 디스크 읽기 기준선을 데이터가 들어오기 전에 재 두지 않으면 설계서 1.3절의 원인 판정이 근거를 잃는다.** 기준선 측정은 5.5절에 있다.

필수 경로 2.44TB의 내역은 다음과 같다.

| 항목 | 용량 | 놓이는 곳 | 근거 |
|---|---:|---|---|
| 원본 다운로드 (필수 5종) | 318.18GB | `$RAW` | 다운로드 가이드 1장의 실측 바이트 |
| 변환과 전개 산출물 | 225.97GB | `$RAW` | Pes2o 전개 195.25GB를 포함한다 |
| laion 컬렉션 작업본 | 385.52GB | `$BENCH` | 위 산식 |
| laion 컬렉션 마스터 사본 | 385.52GB | `$BENCH` | 5.7절의 복원 전략 |
| Pes2o 4차원 컬렉션 작업본 | 209.97GB | `$BENCH` | 2560과 1536과 1024와 768 네 벌 |
| Pes2o 4차원 컬렉션 마스터 | 209.97GB | `$BENCH` | 같은 이유 |
| bioasq와 openai 컬렉션 | 156.68GB | `$BENCH` | |
| **최적화 일시 여유** | **385.52GB** | `$BENCH` | 5.8절. 상시 비워 둔다 |
| cargo target | 약 60GB | `$RAW` | 어림값. 체크아웃 한 벌 기준이다. 8.6절에서 실측한다 |
| 로그와 결과 | 약 100GB | `$RAW` | |
| **합계** | **2,437GB** | | 16TB의 15.2% |

**표의 cargo target 60GB는 체크아웃 한 벌 기준이다.** 8.6절이 계측 빌드와 대조 빌드를 위해 체크아웃을 둘로 나누기로 했으므로 실제로는 target 디렉터리가 둘이 되어 약 120GB가 들고, 그 구성을 택하면 필수 합계는 2,497GB가 된다. 16TB의 15.6%이므로 결론은 달라지지 않지만 `$RAW` 의 합격선은 이 값으로 잡아야 한다.

원본 318.18GB의 내역은 아래와 같다. 모든 바이트 수는 다운로드 가이드가 2026-09-21에 직접 요청해 확인한 값이다.

| 원본 | 바이트 | GB |
|---|---:|---:|
| ann-benchmarks SIFT (스모크) | 525,128,288 | 0.53 |
| laion train 100개 | 212,308,503,251 | 212.31 |
| laion `scalar_labels.parquet` | 590,420,586 | 0.59 |
| laion `test` + `neighbors` | 6,627,948 | 0.01 |
| bioasq train 10개 | 19,280,984,409 | 19.28 |
| bioasq 질의와 정답과 라벨 | 약 70,000,000 | 0.07 |
| openai 본체 10개 | 약 44,900,000,000 | 44.90 |
| Zenodo Pes2o `pes2o_corpus.npz` | 39,748,381,931 | 39.75 |
| **합계** | | **317.43** |

이 재계산은 조사가 쓴 318.18GB와 0.75GB 차이가 난다. 어느 작은 파일을 포함했는지의 차이로 보이며 결론을 바꾸지 않는다.

```bash
df -B1 --output=source,fstype,size,used,avail,target $RAW $BENCH
df -h $RAW $BENCH
```

`$BENCH` 의 `avail` 이 최소 1.75TB여야 한다. 그 장치에 들어가는 것은 laion 작업본 385.52GB와 마스터 385.52GB, Pes2o 네 벌의 작업본과 마스터 419.94GB, bioasq와 openai 156.68GB, 최적화 여유 385.52GB이고, 더하면 1,733.18GB 즉 약 1.73TB다. 여유를 두어 1.8TB를 확보하면 안전하다.

`$RAW` 쪽은 다음과 같이 계산한다.

```
원본 다운로드                318.18GB
변환과 전개 산출물           225.97GB
cargo target (두 벌)        약 120.00GB
로그와 결과                 약 100.00GB
--------------------------------------
합계                        약 764.15GB
```

따라서 `$RAW` 에는 최소 800GB를 잡는다. 체크아웃을 한 벌만 쓰기로 하면 cargo target이 60GB로 줄어 704.15GB가 되므로 700GB로도 되지만, 8.6절이 두 벌을 전제하므로 기본 합격선은 800GB로 둔다. 선택 데이터인 msmarco까지 쓸 계획이면 `$RAW` 쪽에 1.6TB를 더 잡는다.

위 표에는 4.8절의 blktrace 출력이 빠져 있다. 이 출력도 `$RAW` 에 쌓이며, 크기는 측정 중 IOPS 에 비례하므로 지금은 추정할 수 없다. **어림으로만 말하면** 이벤트 하나가 48바이트 헤더에 부가 정보를 더한 크기이고 I/O 하나에 이벤트가 여러 개 붙으므로 I/O 하나당 수백 바이트로 잡을 수 있고, 그 기준으로는 초당 10만 I/O 에서 한 시간에 100GB 안팎이 된다. 이 값은 실측이 아니므로 합격선에 넣지 않고, 5.1 예비 측정에서 한 조건분을 실측해 이 절의 표에 줄을 추가한다. 그 전까지는 blktrace 를 켠 실행마다 `$RAW` 의 `avail` 을 따로 본다.

### 5.2 파일시스템 요건 — ext4 또는 xfs여야 하고 zfs와 btrfs는 금지

설계서 3.1절이 병목 원인 판정 근거로 삼는 "디스크 읽은 양"은 컨테이너 cgroup의 `io.stat` 에서 읽는 `rbytes` 다. **btrfs나 zfs의 투명 압축을 켜면 디스크에 실제로 오가는 바이트가 논리 읽기량보다 작아져 이 값이 과소 계상된다.**

더 나쁜 것은 **압축률이 구성 요소마다 다르다**는 점이다. float32 벡터는 거의 압축되지 않지만 payload JSON과 색인은 잘 압축되므로, 설계서 2.3절이 요구하는 "벡터와 payload와 색인 중 무엇을 읽었는가"라는 판정이 구성 요소마다 다른 배율로 왜곡된다.

**가장 치명적인 것은 zfs다.** zfs의 ARC 캐시는 리눅스 페이지 캐시 바깥에 있어 cgroup 메모리 한도가 걸리지 않으므로, 설계서 4.2절의 메모리 축 실험 자체가 성립하지 않는다. `cgroup_trap_check_2026-09-21.md` 2장의 파일시스템 종류 항목이 같은 취지의 경고를 이미 담고 있으나 그 경고는 더미 파일에만 적용되어 있고 Qdrant 저장소 경로에는 적용되어 있지 않다.

확인 명령은 3.6절에 있다. 그런데 **파일시스템 이름만으로는 충분하지 않다.** 마운트 옵션이나 장치 계층(VDO, 압축 기능이 있는 하드웨어 RAID, 씬 프로비저닝 LVM)에서 압축이나 중복 제거가 걸려 있을 수 있고, 그러면 결과는 같다. 난수로 파일을 만들어 `ls` 가 보는 크기와 `du` 가 보는 크기를 직접 비교하는 것이 파일시스템 이름에 의존하지 않는 유일한 확인 방법이다.

```bash
if [ -z "$BENCH" ]; then
  echo "BENCH 가 비어 있다. 3.6절의 export 줄로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  dd if=/dev/urandom of="$BENCH/.fstest" bs=1M count=2048 status=none
  sync
  ls -l --block-size=1 "$BENCH/.fstest"
  du -B1 "$BENCH/.fstest"
  rm -f "$BENCH/.fstest"
fi
```

`ls` 가 보여 주는 크기와 `du` 가 보여 주는 크기가 둘 다 2,147,483,648 근처로 같아야 한다. `du` 쪽이 눈에 띄게 작으면 압축이나 중복 제거 또는 씬 프로비저닝이 걸려 있는 것이고, **그 경로에서는 디스크 읽기량 측정이 성립하지 않는다.** 압축이 없는 경로를 따로 마련하고, 불가능하면 그 사실을 설계서 4.3절에 한계로 적는다.

### 5.3 원본 데이터와 Qdrant 저장소를 서로 다른 블록 장치에 배치

이유가 셋이다.

**첫째, 입출력 경쟁이다.** 적재 중에는 원본 parquet 212.31GB를 읽는 입출력과 Qdrant가 세그먼트를 쓰는 입출력이 같은 장치 큐를 다투므로, 설계서 2.2절의 저장 처리량 측정이 변환 스크립트의 읽기에 오염된다.

**둘째이자 가장 중요한 것은 설계서 4.3절의 함정을 직접 유발한다는 점이다.** 호스트 프로세스가 원본을 읽으면 그 페이지 캐시가 호스트 cgroup 앞으로 과금되고, 동시에 컨테이너가 쓸 수 있는 호스트 여유 메모리를 212GB 규모로 잠식한다.

**셋째, 캐시 비우기 비용이다.** 4.3절 대책 둘째인 캐시 비우기는 `drop_caches` 라 전역으로 작동하므로, 같은 장치에 원본을 두면 조건을 바꿀 때마다 원본 캐시까지 함께 날아가 준비 시간이 매번 늘어난다.

장치를 나누면 세 문제가 한꺼번에 줄어들고, **Qdrant 저장소 장치에는 Qdrant 말고 아무것도 두지 않아 그 장치의 입출력 통계가 곧 Qdrant의 입출력이 된다.**

```bash
stat -c '%d  %n' $RAW $BENCH
for d in "$RAW" "$BENCH"; do
  findmnt -T "$d" -no SOURCE,TARGET || echo "$d 의 마운트를 찾지 못했다"
done
lsblk -o NAME,MOUNTPOINT,SIZE,MODEL
```

`stat` 이 출력하는 장치 번호(`%d`)가 두 경로에서 서로 달라야 한다. `findmnt` 의 `SOURCE` 도 서로 다른 블록 장치를 가리켜야 한다. 같은 값이 나오면 같은 파일시스템 위에 있는 것이고, 최소한 파일시스템을 나누되 가능하면 물리 장치를 나눈다.

### 5.4 디렉터리 구조와 경로 치환

`dataset_download_2026-09-21.md` 의 명령이 모두 홈 디렉터리 아래 `~/vecdata` 를 쓰도록 되어 있는데, **홈은 보통 루트 파일시스템에 있어 앞 절의 장치 분리와 충돌한다.** 더 나쁜 경우로 홈이 작은 루트 파티션에 있으면 212.3GB를 받는 도중에 루트가 가득 차 서버 전체가 멈춘다. 받기 시작하기 전에 경로를 정해 두지 않으면 318GB를 받은 뒤 옮겨야 한다.

또한 Qdrant 저장소를 마스터와 작업본으로 나누어 두어야 5.7절의 조건별 복원 전략이 성립한다.

```bash
if [ -z "$RAW" ] || [ -z "$BENCH" ]; then
  echo "RAW 또는 BENCH 가 비어 있다. 3.6절의 export 줄로 돌아가 두 변수를 모두 설정한 뒤 이 블록을 다시 실행한다."
else
  # 장치 A ($RAW): 원본과 변환 산출물과 빌드와 로그와 결과
  mkdir -p "$RAW"/{smoke,laion100m,bioasq10m,openai5m,pes2o}
  mkdir -p "$RAW/derived" "$RAW/logs" "$RAW/results" "$RAW/build/qdrant"

  # 장치 B ($BENCH): Qdrant 저장소만. 다른 것을 두지 않는다
  mkdir -p "$BENCH/qdrant/master" "$BENCH/qdrant/work" "$BENCH/snapshots"

  for d in "$RAW" "$BENCH"; do
    findmnt -T "$d" -no SOURCE || echo "$d 의 마운트를 찾지 못했다"
  done
  df -h ~ /var/lib/docker $RAW $BENCH
  df -i ~ $RAW $BENCH
fi
```

디렉터리가 만들어지고 `findmnt` 가 두 경로에 대해 서로 다른 `SOURCE` 를 출력해야 한다. `df -i` 로 inode 여유도 함께 본다.

Docker의 data-root도 여기서 본다. 컨테이너 이미지와 쓰기 계층이 data-root에 쌓이는데, 이것이 측정 대상 데이터와 같은 물리 장치에 있으면 이미지 내려받기나 로그 기록이 측정 중 디스크 경쟁을 만들고, 반대로 루트 파티션에 있으면 용량 부족으로 데몬이 멈춘다.

```bash
docker info --format '{{.DockerRootDir}}'
df -h $(docker info --format '{{.DockerRootDir}}')
findmnt -T "$(docker info --format '{{.DockerRootDir}}')" -no SOURCE,FSTYPE
docker system df
```

data-root가 놓인 파일시스템에 최소 수십 GB의 여유가 있어야 한다. 측정 데이터와 같은 장치라면 그 사실을 기록하고, **측정 중에는 이미지 내려받기와 빌드를 하지 않는다.**

**이후 다운로드 가이드의 모든 `~/vecdata` 는 `$RAW` 로 바꿔 쓴다.** 예를 들어 다운로드 가이드 3.4절의 `mkdir -p ~/vecdata/laion100m && cd ~/vecdata/laion100m` 은 `mkdir -p $RAW/laion100m && cd $RAW/laion100m` 이 된다.

### 5.5 디스크 읽기 성능 기준선 측정

설계서 1.3절이 병목 원인을 CPU와 메모리와 디스크 셋 중 하나로 판정한다. **"디스크가 한계다"라고 말하려면 그 장치가 낼 수 있는 최대치를 알아야 하는데, 기준선이 없으면 `io.stat` 이 보여 주는 초당 읽기 바이트가 큰 값인지 작은 값인지 판단할 근거가 없다.**

또 하나의 이유가 더 직접적이다. 5.1절의 표대로 메모리 사다리는 실제로 디스크 읽기 기울기를 만든다. 그때 늘어난 지연이 "읽는 양이 늘어서"인지 "장치가 느려서"인지 가르려면 읽은 양에 장치의 임의 읽기 지연을 곱해 예상 추가 시간을 계산하고 실측과 대조해야 하며, 그 계산에 기준선이 들어간다.

네 값 중 **4KiB 큐 깊이 1 임의 읽기 지연이 가장 중요하다.** mmap 페이지 폴트는 동기이고 한 번에 한 페이지씩 일어나므로 그 지연이 검색 지연에 그대로 더해진다.

먼저 테스트 파일을 한 번 만들어 둔다. 이 단계만 장치에 쓰기를 발생시킨다.

```bash
command -v fio || sudo apt-get install -y fio
if [ -z "$BENCH" ]; then
  echo "BENCH 가 비어 있다. 3.6절의 export 줄로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  F="$BENCH/.fiotest"
  fio --name=layout --filename="$F" --size=100G --rw=write --bs=1M \
      --direct=1 --ioengine=libaio --iodepth=32 --end_fsync=1 --group_reporting
fi
```

이어서 세 가지 읽기 프로파일을 잰다. 각 측정 전에 캐시를 비운다.

```bash
# 순차 읽기 대역폭. copy_data 와 populate_vector_storages 가 여기에 해당한다
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
fio --name=seq --filename="$F" --rw=read --bs=1M --direct=1 \
    --ioengine=libaio --iodepth=32 --runtime=60 --time_based --group_reporting

# 4KiB 임의 읽기 QD1. mmap 페이지 폴트가 여기에 해당한다. 가장 중요한 값이다
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
fio --name=rr1 --filename="$F" --rw=randread --bs=4k --direct=1 \
    --ioengine=libaio --iodepth=1 --runtime=60 --time_based --group_reporting

# 4KiB 임의 읽기 QD32 x 4잡. 동시 요청이 걸린 상태의 상한이다
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
fio --name=rr32 --filename="$F" --rw=randread --bs=4k --direct=1 \
    --ioengine=libaio --iodepth=32 --numjobs=4 --runtime=60 --time_based --group_reporting

rm -f "$F"
```

기록할 값은 순차 읽기의 `BW`, QD1 임의 읽기의 `clat` 평균과 99번째 백분위, QD32 임의 읽기의 `IOPS` 다. **절대 수치를 합격선으로 두지 않고, 이 값을 기준선으로 남기는 것 자체가 합격 조건이다.** 판정은 조건 사이의 비교로 한다.

**`--direct=1` 이 반드시 붙어야 한다.** 이것이 빠지면 1TB RAM의 페이지 캐시를 재게 되어 기준선이 통째로 틀린다. 100GB짜리 테스트 파일은 RAM보다 작아 캐시에 통째로 올라가므로, 이 옵션을 빠뜨리면 실제보다 수십 배 빠른 값이 나오고 이후의 디스크 병목 판정이 전부 무너진다.

100GB를 쓸 수 없는 사정이 있으면, `cgroup_trap_check.sh` 를 `KEEP=1` 로 돌려 남긴 16GB 난수 파일을 `--readonly` 로 재사용할 수 있다. `--readonly` 를 주면 파일에 쓰지 않으므로 안전하지만, **파일이 없으면 fio가 직접 만들면서 쓰기가 발생하므로 반드시 기존 파일을 지정한다.** 또한 그 파일은 `/var/tmp` 에 있어 `$BENCH` 와 다른 장치일 수 있으니, 경로를 확인한 뒤에 쓴다.

WAL의 동기 쓰기 지연도 여기서 함께 잰다. 설계서 0.3절이 지적한 대로 MemMachine은 `wait=true` 를 쓰므로 요청마다 WAL 확정이 일어나고, 이는 용량이 아니라 장치의 fsync 지연 문제다.

```bash
if [ -z "$BENCH" ]; then
  echo "BENCH 가 비어 있다. 3.6절의 export 줄로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  fio --name=sync --filename="$BENCH/.fsync" --size=1G --rw=write --bs=4k \
      --direct=1 --iodepth=1 --fsync=1 --ioengine=libaio --runtime=30 --time_based
  rm -f "$BENCH/.fsync"
fi
```

여기서 나온 `clat` 평균을 기록해 둔다. 이 값이 설계서 3.2절의 W2(WAL 확정) 계측 결과를 해석할 때 하한 기준이 된다.

### 5.6 스왑 장치의 위치

설계서 4.3절 대책 4가 스왑을 끄라고 적었으나 디스크 배치 관점에서 두 가지가 더 걸린다. 첫째, 스왑이 켜져 있으면 컨테이너가 메모리 한도를 넘었을 때 디스크를 다시 읽는 대신 스왑으로 빠지므로 설계서 4.2절이 관측하려는 현상 자체가 사라진다. 둘째, **스왑 파일이나 스왑 파티션이 `$BENCH` 와 같은 장치에 있으면 스왑 입출력이 그 장치의 통계에 섞여 들어가** 5.5절의 기준선과 실제 측정의 대조가 흐려진다.

```bash
swapon --show
lsblk -o NAME,MOUNTPOINT,SIZE $(swapon --show=NAME --noheadings 2>/dev/null | head -1) 2>/dev/null
findmnt -T "$BENCH" -no SOURCE || echo "BENCH 의 마운트를 찾지 못했다"
```

스왑 장치가 있으면 그것이 `$BENCH` 와 같은 장치인지 확인한다. 같은 장치라면 그 사실을 측정 기록에 남긴다. **호스트 전역 `swapoff -a` 는 3.5절의 경고대로 전용 서버임을 확인하기 전에는 쓰지 않고, 컨테이너마다 `--memory-swap` 을 `--memory` 와 같게 주는 방식으로 대신한다.**

### 5.7 조건별 재적재 대신 마스터 사본에서 복원한다

메모리 축 세 조건은 같은 데이터를 쓰므로 조건마다 1억 개를 다시 적재할 이유가 없다. 설계서 4.3절이 요구하는 것은 컨테이너 재생성과 캐시 비우기이지 재적재가 아니며, 저장소 디렉터리를 그대로 두고 컨테이너만 새로 만들면 두 대책이 모두 충족된다.

다만 쓰기 부하를 거는 조건은 시작 상태가 같아야 비교가 성립한다. 앞 조건에서 들어간 포인트와 세그먼트 배치가 남아 있으면 다음 조건의 옵티마이저 동작이 달라지기 때문이다. 그래서 **적재 직후 상태를 마스터로 떠 두고 조건마다 거기서 복사해 쓴다.** 이 때문에 laion 컬렉션 공간이 두 벌 필요하며, 이것이 5.1절의 용량 계산에서 laion이 두 번 계상된 이유다.

복사가 재적재보다 압도적으로 싸다. 385.52GB를 1GB/s로 복사하면 약 6분 26초인 반면, 1억 개 적재는 그보다 훨씬 오래 걸린다.

**역할과 원칙은 확정되어 있다.** 적재 완료 판정과 마스터 사본 생성은 부하 도구의 적재기(3.2)가 맡고, 조건마다 작업본을 복원하는 일은 `environment_setup_2026-09-21.md` 5.3절의 `run_condition.sh` 가 `RELOAD=copy` 기본값으로 맡는다. 지켜야 하는 원칙은 조건마다 컨테이너가 데이터 페이지를 처음 만져야 한다는 것이다. 방법은 호스트가 마스터 사본을 작업본으로 복사한 뒤 시스템 캐시를 비우고, 컨테이너를 새로 띄워 처음 읽게 하며, 게이트 A(캐시 잔류 없음)와 게이트 C(컨테이너 앞으로 디스크 읽기 과금)로 증명하는 것이다. 다시 적재하는 것은 마스터가 없을 때의 대안이며 같은 문서 5.5절이 두 경로의 선택 근거를 적고 있다. 아래 블록은 마스터를 뜨는 방법과 복사 비용을 손으로 확인하는 용도다.

```bash
if [ -z "$BENCH" ]; then
  echo "BENCH 가 비어 있다. 3.6절의 export 줄로 돌아가 값을 설정한 뒤 이 블록을 다시 실행한다."
else
  # 적재를 마친 직후 한 번만 마스터를 뜬다 (본 절차에서는 3.2 적재기가 이 일을 한다)
  du -sb "$BENCH/qdrant/work"
  time cp -a --reflink=never "$BENCH/qdrant/work/." "$BENCH/qdrant/master/"

  # 조건을 바꿀 때마다 (본 절차에서는 환경 문서 5.3절의 스크립트가 호스트에서 복사하고
  # 캐시를 비운 뒤 컨테이너를 새로 띄운다. 여기서는 복사 시간을 재는 용도로만 쓴다)
  rm -rf "$BENCH/qdrant/work" && mkdir -p "$BENCH/qdrant/work"
  time cp -a --reflink=never "$BENCH/qdrant/master/." "$BENCH/qdrant/work/"
  sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
fi
```

**이 블록은 새 셸에서 돌리기 쉬운 자리이므로 첫 줄의 가드를 반드시 남겨 둔다.** `$BENCH` 가 비어 있는 셸에서 인용 없이 `rm -rf $BENCH/qdrant/work` 를 돌리면 `rm -rf /qdrant/work` 가 되어 측정과 무관한 경로를 지운다.

`du -sb` 가 보여 주는 work 크기와 master 크기가 같아야 한다. **`--reflink=never` 가 반드시 붙어야 한다.** xfs는 reflink를 지원하므로 이 옵션이 없으면 블록을 공유하는 즉시 복사가 일어나, 겉보기에는 두 벌이지만 실제로는 한 벌을 공유하게 되어 조건 간 격리가 깨지고 디스크 읽기 패턴도 달라진다. 복사 시간을 기록해 두고 5.5절의 순차 읽기 대역폭과 대조해 장치가 기대대로 동작하는지 교차 확인한다.

### 5.8 세그먼트 최적화 일시 여유와 적재 중 감시

설계서 0.4절이 보여 주는 대로 최적화의 첫 단계인 `copy_data` 가 세그먼트 데이터를 새 세그먼트로 복사하므로, 그동안 원본 세그먼트와 사본이 디스크에 함께 존재한다. **얼마나 커질지 미리 못 박을 수 없다.** v1.19.1의 `config/config.yaml` 에서 확인한 바로는 `max_segment_size_kb` 가 기본 null이라 자동 선택되고 `default_segment_number` 도 0이라 CPU 수로 자동 결정되기 때문이다.

컨테이너를 16코어로 묶으므로 세그먼트가 16개면 세그먼트당 625만 개에 벡터만 19.20GB이고, 8개면 1,250만 개에 38.40GB다. 그런데 최초 대량 적재 직후의 전면 최적화에서는 사실상 컬렉션 전체가 한 번 다시 쓰이므로, 보수적으로 **컬렉션 크기 한 벌분인 385.52GB를 여유로 잡는 편이 안전하다.**

적재 도중 디스크가 차면 설계서 0.3절 ①의 디스크 여유 확인 단계에서 저장 요청이 거부되기 시작하고, 그 시점의 측정값은 병목이 아니라 디스크 고갈을 재고 있는 것이 된다.

```bash
# 적재를 거는 동안 다른 창에서
COLL=laion100m   # 실제 컬렉션 이름으로 바꾼다
watch -n 5 'df -B1 --output=avail,target '"$BENCH"' | tail -1; \
  curl -s localhost:6333/collections/'"$COLL"'/optimizations | python3 -m json.tool | head -40'
```

적재와 최적화가 도는 내내 `$BENCH` 의 `avail` 이 385GB 아래로 내려가지 않아야 한다. `optimizations` 창구의 `queued_segments` 와 `queued_points` 가 단조 증가만 하고 줄어들지 않으면 최적화가 밀리고 있는 것이며, 그 상태에서 `avail` 이 계속 줄면 적재를 멈추고 여유부터 확보한다. `duration_sec` 의 `copy_data` 값도 함께 기록해 두면 5.5절의 순차 읽기 기준선과 대조할 수 있다.

WAL은 전체 용량 계획에서 무시해도 좋은 크기다. v1.19.1의 `config/config.yaml` 에서 확인한 기본값은 `wal_capacity_mb` 가 32, `wal_segments_ahead` 가 0, `wal_retain_closed` 가 1이므로, 샤드 하나당 열린 세그먼트 하나와 보관하는 닫힌 세그먼트 하나를 합쳐 약 64MB이고 단일 노드 기본 샤드 수가 1이므로 100MB 미만이다.

```bash
grep -A6 '^  wal:' $RAW/build/qdrant/config/config.yaml
# 컨테이너가 이미 떠 있으면
# docker exec qdrant grep -A6 '^  wal:' /qdrant/config/config.yaml
```

세 값이 위와 같아야 한다. 다르면 샤드당 용량을 다시 계산한다.

### 5.9 1000만 개 규모로 먼저 적재해 계산을 검증한다

**이 항목이 5.1절 용량 계산 전체의 검증 장치다.** 벡터 307.20GB는 차원과 포인트 수와 4바이트만으로 정해지므로 확정값이지만, payload 50GB와 색인 13.60GB와 링크 14.72GB는 전부 어림값이다.

특히 링크는 0에서 14.72GB 사이 어디든 될 수 있다. 설계서 0.5절과 5.3.2절이 밝힌 대로 **포인트 수가 `full_scan_threshold` 를 넘는 payload 값에만 링크 블록이 만들어지기 때문이고,** 세션당 포인트 수 분포가 설계서 5.4절에서 아직 미정이기 때문이다. v1.19.1 `config.yaml` 의 `full_scan_threshold_kb` 가 10000이므로 차원별 경계는 다음과 같다.

| 차원 | 벡터 한 개의 바이트 | 링크가 만들어지는 경계 |
|---:|---:|---:|
| 768 | 3,072 | 3,333개 |
| 1024 | 4,096 | 2,500개 |
| 1536 | 6,144 | 1,666개 |
| 2560 | 10,240 | 1,000개 |

768차원의 3,333개는 설계서 5.3.2절의 값과 일치한다.

다운로드 가이드 3.6절이 샤드 10개만 받는 방법을 이미 제공하므로, **21.2GB만 받아 1000만 개를 적재하고 파일별 크기를 직접 재면 전체 계산을 열 배로 외삽해 검증할 수 있다.** 이것은 설계서 5.3.7절 실험 4("구성별 메모리 실측, 링크 파일 크기를 직접 잰다")와 같은 작업이므로 따로 드는 비용이 아니다.

```bash
COLL=laion10m   # 실제 컬렉션 이름으로 바꾼다
C="$BENCH/qdrant/work/collections/$COLL"
du -sb "$C"
du -sb "$C"/*/segments/*/* 2>/dev/null | sort -rn | head -20
find "$C" -type f -printf '%s\t%p\n' | sort -rn | head -30
curl -s "localhost:6333/collections/$COLL" | python3 -m json.tool | head -40
```

벡터 저장소 파일의 합계가 30,720,000,000바이트(1000만 × 768 × 4) 근처여야 한다. 이 값이 맞으면 나머지 구성 요소를 열 배 해서 1억 개 규모를 외삽하고, **5.1절의 payload 50GB와 색인 13.60GB와 링크 14.72GB를 실측값으로 바꿔 적는다.** 링크 파일이 아예 없으면 세션이 전부 3,333개 미만이라는 뜻이고, 그 경우 1억 개 규모에서도 링크 용량은 0으로 잡아야 한다.

### 5.10 이 단계가 끝났다는 것을 어떻게 아는가

1. `$RAW` 와 `$BENCH` 가 정해졌고 `stat -c %d` 가 서로 다른 장치 번호를 출력한다.
2. 두 경로의 파일시스템이 ext4 또는 xfs이고, 5.2절의 난수 파일 확인에서 `ls` 와 `du` 의 크기가 같았다.
3. `$BENCH` 에 1.75TB 이상(여유를 포함해 1.8TB), `$RAW` 에 800GB 이상 여유가 있다.
4. 5.5절의 fio 네 값(순차 BW, QD1 clat 평균, QD1 clat p99, QD32 IOPS)과 fsync clat 평균을 기록했다.
5. 5.4절의 디렉터리 구조가 만들어졌고, 다운로드 가이드의 `~/vecdata` 를 `$RAW` 로 바꾸는 치환 규칙을 적어 두었다.

---

## 6. 준비 4. 계정, 토큰, 라이선스

### 6.1 먼저 보내야 하는 것

**이 장이 이 문서에서 가장 먼저 착수해야 하는 부분이다.** 나머지 준비는 우리가 손을 놀려 끝낼 수 있지만, 이 장의 항목은 요청을 보내고 회신을 기다려야 한다.

| 보낼 곳 | 무엇을 | 이것이 막고 있는 것 | 절 |
|---|---|---|---|
| 서버 관리자 | 계정, sudo, docker 그룹 | 준비 1 전체와 1.2 조건에 맞춰 띄우기 | 6.2 |
| 서버 소유 부서 | 공동 사용자 확인과 독점 사용 창 | `drop_caches`, sysctl 변경, 측정 전체 | 6.3 |
| 네트워크 담당 | 방화벽 허용 목록과 대용량 전송 고지 | 준비 5, 6, 7 | 6.4 |
| TL과 상급자 | 데이터 용도(사내 전용인가 외부 공개인가) | 데이터셋 선택 확정 | 6.5 |
| 법무 | Zilliz 배포본 라이선스, CC-BY와 AGPL 의무 | 2.1 라이선스 확인과 2.2 받기 | 6.6 |
| 동료 | 1단계 인계 자료 형식과 일정 | 5.2 본 측정 | 6.10 |

### 6.2 측정 서버 접속 계정과 sudo 권한

1.3 함정 확인 절차가 사람의 권한에 통째로 막혀 있었고, 1.2 이후의 절차도 같은 권한을 요구한다. `cgroup_trap_check_2026-09-21.md` 3장의 더미 파일 생성과 4.1절의 캐시 비우기와 컨테이너 실행이 모두 sudo를 요구하고, `cgroup_trap_check.sh` 는 사전 확인의 `id -u` 검사에서 root가 아니면 `die` 로 즉시 중단한다. **어떤 단계가 "바로 착수 가능"이라는 것은 다른 단계에 막혀 있지 않다는 뜻이지 권한이 이미 있다는 뜻이 아니다.** 권한 신청에 며칠이 걸리는 조직이라면 이것이 실제 착수일을 결정한다.

확인 명령은 3.2절에 있다. 받아야 할 것을 요청서에 적을 때는 다음 네 가지를 명시한다. 첫째, 로그인 계정을 요청한다. 둘째, `sudo` 권한이 필요하며 가능하면 무암호로 설정해 달라고 적는다. 셋째, `docker` 그룹에 넣어 달라고 적는다. 넷째, `/proc/sys/vm/drop_caches` 쓰기가 필요하다는 사실과 그 이유를 함께 적는다. **docker 그룹 소속은 사실상 root 권한과 같으므로 그 사실을 요청서에 함께 적어 관리자가 알고 부여하게 한다.**

### 6.3 호스트 전역 조작에 대한 공동 사용자 고지와 독점 사용 창

설계서 4.3절의 대책과 1.3 함정 확인 절차가 서버 전체에 영향을 준다. 캐시 비우기 명령은 그 서버에서 도는 모든 프로세스의 페이지 캐시를 비우고, 스왑 끄기도 호스트 전역이다. 같은 서버를 쓰는 사람이 있으면 그 사람의 작업이 갑자기 느려지고, 반대로 그 사람의 부하 때문에 우리 측정값이 오염된다. **344 vCPU에 1TB RAM인 장비는 공용일 가능성이 높으므로 소유 부서를 먼저 찾아 확인해야 한다.**

확인 명령은 3.8절에 있다. 합의해야 할 것은 다음 네 가지다.

첫째, 이 서버가 전용인가 공유인가. 둘째, 공유라면 `drop_caches` 와 sysctl 변경을 언제 써도 되는가. 셋째, 측정 시간대에 다른 작업을 멈춰 줄 수 있는가. 넷째, 호스트 전역 설정 가운데 우리가 바꿔도 되는 것은 무엇인가. 마지막 항목의 후보는 THP 설정(3.5절), 주파수 거버너(3.4절), `vm.max_map_count`(3.5절) 셋이며, 이 중 `vm.max_map_count` 는 올리기만 하는 변경이라 위험이 낮고 나머지 둘은 다른 작업의 성능 특성을 바꾼다.

**Qdrant 소스 디렉터리를 동시에 편집 중인 작업이 있다는 점도 함께 확인한다.** 상세는 6.9절에 있다.

### 6.4 외부 통신 경로 허용

`dataset_download_2026-09-21.md` 의 모든 명령이 여기에 막힌다. 사내망이 프록시나 방화벽을 두고 있으면 런북의 어느 명령도 서버에서 동작하지 않는다. **노트북에서 되는 것은 서버에서도 된다는 근거가 되지 않으며, 다운로드 가이드가 검증한 URL도 모두 노트북에서 확인한 것이다.** 허용 신청에 결재가 걸리는 조직이라면 다운로드를 시작하는 날이 아니라 지금 신청해야 한다.

확인 명령과 허용 목록은 7.1절에 있다. 네트워크 담당에게 보낼 요청서에는 호스트 목록과 함께 용도를 적는다.

| 호스트 | 무엇에 쓰나 | 언제 필요한가 |
|---|---|---|
| `s3.us-west-2.amazonaws.com` | 주 데이터 laion 212.3GB | 항상 |
| `zenodo.org` | 차원 스윕용 Pes2o 39.7GB | 항상 |
| `ann-benchmarks.com` | 2.2 스모크 SIFT 525MB | 2.2 스모크 |
| `dl.fbaipublicfiles.com` | 1024차원 1억 개 경로(선택) | 그 경로를 열 때만 |
| `huggingface.co`, `cdn-lfs.huggingface.co` | 라이선스 문제로 후보를 갈아탈 때 | 6.6절 회신에 따라 |
| `registry-1.docker.io` | 컨테이너 이미지 | 항상 |
| `static.crates.io`, `github.com` | 계측 빌드 의존성 | 준비 6 |

### 6.5 데이터 용도 구분 확정 — 사내 전용인가 외부 공개 계획이 있는가

**이것이 라이선스 질문 전체의 분기점이고, 확정되기 전에는 데이터셋 선택을 마무리할 수 없다.** `dataset_download_2026-09-21.md` 7.1절은 사내 측정에 쓰고 결과 수치만 보고하는 것은 통상 문제가 되지 않지만, 데이터나 파생물을 재배포할 계획이 있다면 반드시 법무 확인을 먼저 받아야 한다고 적었다.

재배포나 외부 공개 계획이 있다면 **라이선스가 명시되지 않은 Zilliz 배포본을 주 데이터로 삼은 선택 자체를 되돌려야 하고,** 그 경우 대안은 같은 절이 정리한 CC-BY-4.0이나 CC0 후보들이다. 즉 이 답이 늦으면 2단계 데이터셋 받기 전체가 늦는다.

이 항목에는 확인 명령이 없다. **TL과 상급자에게 물어 문서로 남은 답을 받는다.** 물을 것은 다음 네 가지다.

1. 측정 결과를 사내 보고로만 쓰는가.
2. 블로그나 발표나 논문이나 업스트림 이슈로 외부에 공개할 계획이 있는가.
3. 내려받은 벡터나 그 파생물을 사내 밖으로 내보낼 계획이 있는가.
4. 이 측정이 상용 제품의 의사결정에 직접 쓰이는가.

넷째 항목의 답이 예이면 MS MARCO 계열의 비상업 연구 전용 조건이 우리에게 걸리는지를 법무에 따로 물어야 한다.

질의의 범위를 좁혀 회신을 빠르게 만드는 방법이 하나 있다. 설계서 4.5.4절은 정답을 데이터셋이 아니라 Qdrant의 `exact` 검색이 만들어 준다고 적었고 4.5.5절은 세션당 포인트 수 분포를 우리가 정해도 된다고 적었다. 따라서 **이번 측정은 원문 텍스트나 이미지를 한 번도 내려받지 않는다.** 이 사실을 먼저 문서로 확정해 두면 MS MARCO 텍스트의 비상업 연구 전용 조건처럼 원문 쪽에 걸린 제약이 우리에게 적용되는지를 법무가 판단하기 쉬워진다.

다만 **임베딩 벡터가 원본 저작물의 2차적 저작물에 해당하는지는 우리가 단독으로 판단할 문제가 아니다.** 질의에 다음 두 가지를 함께 넣는다. 첫째, 임베딩 벡터만 내려받아 사내에서 쓰는 것이 원문의 이용 조건에 걸리는가. 둘째, "벡터만 쓰니 안전하다"는 가정을 우리가 세워도 되는가. 후자를 우리가 단독으로 결론 내리지 않는 것이 핵심이다.

### 6.6 라이선스에 대한 법무 질의

**주 데이터의 이용 조건이 어디에도 명시되어 있지 않다는 것이 확인된 사실이다.** `dataset_download_2026-09-21.md` 7.1절에 따르면 `laion_large_100m` 의 README 전문에 라이선스 문장이 한 줄도 없었고 프리픽스에 LICENSE 파일도 없었으며, `cohere_large_10m` 과 `bioasq_large_10m` 과 `openai_large_5m` 과 `msmarco_v2_138M_parquet` 어디에도 없다. 원출처인 LAION이 CC-BY-4.0 계열로 알려져 있다는 것과 Zilliz 재배포본 자체의 조건은 별개 문제다.

아래 명령은 그 부재를 다시 확인해 법무에 제시할 근거를 만든다. **응답을 실제로 받아 온 상태에서 아무것도 걸리지 않는다는 것이 근거이지, 빈 출력 자체가 근거인 것은 아니다.** 그래서 두 명령 모두 응답 본문이 왔는지를 함께 확인한다.

```bash
curl -s "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/README.md" \
  -o /tmp/laion-readme.md -w 'http=%{http_code} bytes=%{size_download}\n'
grep -inE "licen|term|copyright|attribut" /tmp/laion-readme.md ; echo "grep exit=$?"

curl -s "https://s3.us-west-2.amazonaws.com/assets.zilliz.com?list-type=2&prefix=benchmark/laion_large_100m/&max-keys=400" \
  -o /tmp/laion-list.xml -w 'http=%{http_code} bytes=%{size_download}\n'
grep -o '<KeyCount>[0-9]*</KeyCount>' /tmp/laion-list.xml
grep -ic "LICENSE" /tmp/laion-list.xml
```

**목록 조회 URL에는 버킷 이름이 경로에 들어가야 한다.** `https://s3.us-west-2.amazonaws.com?list-type=2&...` 처럼 버킷을 빼면 HTTP 307에 본문 0바이트가 돌아오므로, 그때의 매치 0은 버킷 내용과 아무 관계가 없다. 또한 `grep` 의 `-o` 는 `-c` 와 함께 쓰면 무시되므로 `-c` 만 남긴다.

첫 명령은 README를 받아 온 뒤 아무것도 출력하지 않고 `grep exit=1` 이 나와야 한다. 둘째 명령은 목록 XML을 받아 `KeyCount` 가 0보다 큰 값으로 나오고 `LICENSE` 매치는 0이어야 한다. 작성자가 2026-09-21에 직접 실행해 목록 쪽에서 HTTP 200과 `KeyCount` 150과 매치 0을 확인했다.

라이선스가 있다고 해서 의무가 없는 것도 아니다. 차원 스윕의 주 데이터인 Zenodo Pes2o는 CC-BY-4.0이라 출처 표기 의무가 따르고, Caselaw 임베딩은 AGPL-3.0인데 데이터에 AGPL을 적용했을 때 어떤 의무가 생기는지가 `dataset_options_2026-09-17.md` 6장에서 미확인으로 남아 있다.

```bash
curl -s "https://zenodo.org/api/records/17101276" \
  | python3 -c "import json,sys; print('Pes2o license =', json.load(sys.stdin)['metadata'].get('license'))"

for r in laion/Caselaw_Access_Project_embeddings \
         CohereLabs/msmarco-v2.1-embed-english-v3 \
         Snowflake/msmarco-v2.1-snowflake-arctic-embed-m-v1.5 \
         VDBBench/multimodal-embedding-100M \
         andropar/relaion2b-natural-embeddings \
         colonelwatch/abstracts-embeddings ; do
  printf "%-62s " "$r"
  curl -s "https://huggingface.co/api/datasets/$r" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('gated=%s license=%s' % (d.get('gated'), [t.split(':',1)[1] for t in d.get('tags',[]) if t.startswith('license:')] or 'NONE'))"
done
```

작성자가 2026-09-21에 직접 실행해 얻은 값은 다음과 같다.

| 저장소 | 라이선스 | gated |
|---|---|---|
| Zenodo Pes2o (17101276) | `cc-by-4.0` | 해당 없음 |
| `laion/Caselaw_Access_Project_embeddings` | `agpl-3.0` | False |
| `CohereLabs/msmarco-v2.1-embed-english-v3` | **없음** | False |
| `Snowflake/msmarco-v2.1-snowflake-arctic-embed-m-v1.5` | **없음** | False |
| `VDBBench/multimodal-embedding-100M` | `cc-by-4.0` | False |
| `andropar/relaion2b-natural-embeddings` | `cc-by-4.0` | False |
| `colonelwatch/abstracts-embeddings` | `cc0-1.0` | False |

여섯 저장소 모두 `gated=False` 였으므로 접근 승인 절차는 필요하지 않다.

법무에 물을 것을 정리하면 다섯 가지다.

1. 라이선스 표기가 없는 재배포본을 사내 성능 측정에 쓸 수 있는가.
2. 원출처인 LAION의 조건이 재배포본에 그대로 승계된다고 보아야 하는가.
3. Zilliz에 직접 문의해 서면 답을 받아 두어야 하는가. **회신까지 시간이 걸릴 수 있으므로 필요하다는 답이 나오면 즉시 보낸다.**
4. CC-BY-4.0의 출처 표기를 사내 보고서에도 넣어야 하는가, 외부 공개물에만 넣으면 되는가.
5. 데이터에 적용된 AGPL-3.0이 실제로 어떤 의무를 발생시키는가.

### 6.7 주 데이터 경로의 익명 접근 — 계정이 필요 없다는 것을 먼저 확정한다

계정 발급을 기다리느라 착수가 밀리는 일을 막으려면 이것을 먼저 확정한다. **주 경로인 Zilliz `laion_large_100m` 과 차원 스윕용 Zenodo Pes2o는 계정도 토큰도 요구하지 않으므로 사람의 준비 없이 바로 시작할 수 있다.** `aws` CLI를 쓰는 경로도 `--no-sign-request` 로 동작하므로 AWS 계정이나 IAM 키는 필요하지 않다.

```bash
for u in \
  "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/README.md" \
  "https://zenodo.org/api/records/17101276" \
  "https://dl.fbaipublicfiles.com/large_objects/dino_vitl_10B/dino_vitl_1B_base.u8bin" \
  "https://ann-benchmarks.com/sift-128-euclidean.hdf5" \
  "https://huggingface.co/api/whoami-v2" ; do
  printf "%-62s " "$(echo "$u" | cut -d/ -f3)"
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 25 -r 0-0 "$u"
done
```

앞의 네 줄은 200 또는 206이 나오고 Hugging Face whoami만 401이 나와야 한다. **작성자가 2026-09-21에 직접 실행해 Zilliz S3 200, Zenodo 200, `dl.fbaipublicfiles.com` 200, `ann-benchmarks.com` 200, Hugging Face whoami 401을 확인했다.** 즉 익명으로 되지 않는 것은 Hugging Face의 계정 식별이 필요한 호출뿐이다.

따라서 **HF 계정과 `HF_TOKEN` 은 선행 조건이 아니라 예비 항목이다.** 6.6절의 법무 회신이 Zilliz 배포본 사용을 막을 때 대체 후보로 갈아타기 위해 필요하며, 대체 후보인 TreeOfLife와 colonelwatch abstracts와 ReLAION-natural과 VDBBench multimodal은 전부 Hugging Face에 있다. 이 저장소들이 모두 `gated=False` 라 원리적으로는 익명으로도 받아지지만, 다운로드 가이드 5.1절이 익명 다운로드에 rate limit이 걸린 사례가 있다고 적었으므로 샤드 수백 개를 연속으로 받는 상황에서는 토큰을 넣어 두는 편이 안전하다.

```bash
~/venv/qdrant-bench/bin/pip install --quiet "huggingface_hub[cli]"
~/venv/qdrant-bench/bin/hf version || ~/venv/qdrant-bench/bin/huggingface-cli version

# 발급은 브라우저에서 한다.
# huggingface.co 로그인 후 Settings 의 Access Tokens 에서
# read 권한만 가진 fine-grained 토큰을 만든다.
```

구버전 `huggingface_hub` 에서는 실행 파일 이름이 `huggingface-cli` 이므로 그때는 그 이름으로 쓴다. 팀에 정해 둘 것은 이 계정을 개인 명의로 둘지 팀 공용 계정으로 둘지, 그리고 담당자가 바뀔 때 토큰을 누가 회수할지다.

### 6.8 토큰과 자격증명을 문서에 남기지 않는 보관 방법

**토큰이 문서나 저장소나 셸 히스토리에 한 번 들어가면 그 자체가 사고이고, 이 저장소의 `docs` 디렉터리는 사내에 공유되는 문서라 더 위험하다.** 보관 방법을 먼저 정해 두지 않으면 다운로드를 급하게 시작하면서 명령줄에 토큰을 붙여 넣게 되고 그 순간 히스토리에 남는다.

```bash
# 1. 히스토리에 남지 않게 입력받아 권한 600 파일에 넣는다
umask 077
mkdir -p "$HOME/.config/hf"
printf 'HF token: '; stty -echo; read -r T; stty echo; echo
printf '%s' "$T" > "$HOME/.config/hf/token"; unset T
chmod 600 "$HOME/.config/hf/token"
ls -l "$HOME/.config/hf/token"

# 2. 쓸 때는 파일에서 읽어 환경변수로만 올린다
export HF_TOKEN="$(cat "$HOME/.config/hf/token")"

# 3. 어디에도 새지 않았는지 확인한다
grep -rn "hf_[A-Za-z0-9]" "$HOME/.zsh_history" "$HOME/.bash_history" 2>/dev/null
echo "history grep exit=$?"

# 이 저장소를 체크아웃한 디렉터리 안에서 실행한다
git grep -nI "hf_[A-Za-z0-9]" -- .
echo "repo grep exit=$?"
grep -rnI "hf_[A-Za-z0-9]" .
echo "tree grep exit=$?"
```

`ls` 결과가 `-rw-------` 로 나오고 세 grep 모두 아무것도 찾지 못해 `exit=1` 이 나와야 한다. **저장소 검사는 작업 기계의 절대 경로가 아니라 서버에서 체크아웃한 디렉터리 안에서 돌린다.** `git grep` 은 git이 추적하는 파일만 보므로 아직 커밋하지 않은 파일과 무시 목록에 든 파일은 걸리지 않고, 그래서 같은 디렉터리에 `grep -rnI` 를 한 번 더 돌려 추적하지 않는 파일까지 덮는다. 작성자가 2026-09-21에 확인한 바로는 작업 기계에 `~/.cache/huggingface/token` 파일이 존재하지 않고 `HF_TOKEN` 환경변수도 설정되어 있지 않다.

팀에 정해 둘 규칙은 셋이다. 첫째, 토큰 값을 이 저장소의 어떤 문서에도 적지 않는다. 둘째, `hf auth login` 이 만드는 `~/.cache/huggingface/token` 도 권한을 600으로 확인한다. 셋째, 셸에서 대화형으로 토큰을 다룰 때는 zsh의 `HIST_IGNORE_SPACE` 나 bash의 `HISTCONTROL=ignorespace` 를 켜 두고 명령 앞에 공백을 붙인다.

### 6.9 계측 빌드와 측정 결과의 취급 방침

확정된 단계 구조의 1.1과 설계서 3.2절이 v1.19.1 소스에 계측 지점 18개소를 넣은 빌드를 만들라고 적고 있다. 사내에서만 돌리고 버리는 것과 그 수정본이나 그 안에서 얻은 수치를 밖으로 내보내는 것은 성격이 다르므로 미리 정해 두어야 한다. 6.5절의 외부 공개 방침과 한 묶음으로 묻는 편이 효율적이다.

받아야 할 답은 다음과 같다.

**계측 빌드에 대해 세 가지를 묻는다.** 첫째, 사내 전용으로만 쓰는가, 아니면 업스트림에 기여하거나 외부에 공개할 계획이 있는가. 둘째, 공개한다면 원 프로젝트의 라이선스가 요구하는 고지 의무가 무엇인지 법무에 확인한다. 셋째, **`/Users/taejin/Projects/qdrant_v1.19.1` 을 누가 언제 어느 파일을 편집하는지 작업자끼리 합의한다. 이번 작업에서는 그 디렉터리를 건드리지 않는 것이 전제다.**

**측정 결과 공개에 대해 네 가지를 묻는다.** 첫째, 어디까지가 외부인가. 사내 위키와 전사 발표와 블로그와 학회 발표와 업스트림 저장소의 이슈나 PR이 각각 어느 쪽인지 선을 긋는다. 둘째, 제품명을 밝힌 벤치마크 수치를 공개하는 데 제약이 있는가. Qdrant 오픈소스판과 관리형 서비스의 약관이 다를 수 있으므로 우리가 단정하지 않고 확인한다. 셋째, 동료에게 받은 실제 세션 분포와 요청 기록을 공개물에 넣어도 되는가. **설계서 5.1절이 동료에게 받기로 한 실제 서비스의 세션 수와 세션당 포인트 수 분포는 사내 운영 정보이므로 그대로 공개하면 서비스 규모가 드러난다.** 넷째, 사용한 데이터셋의 출처 표기를 어느 형식으로 넣어야 하는가.

### 6.10 동료의 1단계 인계 자료 수령 일정

5.2 본 측정이 동료가 넘겨줄 병목 조건에 막혀 있는데, 설계서 5.4절이 동료의 1단계 합류 시점을 미정으로 남겨 두었다. **이것이 우리가 통제할 수 없는 유일한 blocker다.**

넘겨받을 것은 설계서 5.1절에 세 부류로 정리되어 있고, 그중 세션 수와 세션당 포인트 수 분포와 필터 통과 비율과 저장 배치 크기는 에뮬레이터에 그대로 들어가는 값이라 없으면 측정 조건을 만들 수 없다. 자료를 언제 어떤 형식으로 받을지가 정해지지 않으면 1단계부터 4단계까지를 다 끝내 놓고도 5.2 본 측정에서 멈춘다. 5.1 예비 측정은 인계 없이도 돌 수 있다.

동료와 합의해 일정으로 남길 것은 셋이다.

1. 설계서 5.1절 (가)의 값 열 개를 **병목 전과 꺾이는 지점과 병목 후 세 좌표로** 받기로 하고 전달 시점을 정한다.
2. (나)의 Qdrant 요청 기록과 응답 시간 분포와 `/telemetry` 스냅샷 두 벌을 받을 형식을 정한다.
3. (다)의 확인 항목 중 **동료가 쓴 Qdrant 버전을 먼저 확인한다.** 설계서 5.1절 (다)가 v1.17이면 저장 대기열 기본값이 1M 대 200이라 비교가 성립하지 않는다고 적었으므로, 이 확인만은 자료 수령 전에 미리 물어 두는 편이 좋다.

### 6.11 이 단계가 끝났다는 것을 어떻게 아는가

1. 서버에 로그인해 `sudo -n true` 가 성공했고 `docker` 그룹에 들어 있다.
2. 서버가 전용인지 공유인지 답을 받았고, 공유라면 `drop_caches` 를 쓸 수 있는 시간대를 합의했다.
3. 6.4절의 호스트 목록으로 방화벽 허용을 신청했고 신청 번호를 기록했다.
4. 6.5절의 네 가지 질문에 대한 답을 문서로 받았다.
5. 6.6절의 질의를 법무에 보냈다. 회신은 아직 없어도 준비 6과 7은 진행할 수 있으나, 외부 공개 계획이 있다고 나왔다면 데이터 받기를 회신 뒤로 미룬다.
6. 동료와 인계 자료의 형식과 시점을 합의했고, 동료가 쓴 Qdrant 버전을 확인했다.

---

## 7. 준비 5. 네트워크 확인과 소요 시간 추정

### 7.1 도달 확인

다운로드 가이드가 쓰는 네 곳과 Docker 레지스트리와 계측 빌드가 쓰는 crates.io가 모두 막혀 있지 않아야 한다. 사내 방화벽이나 프록시가 있으면 각 도구에 프록시 설정을 따로 넣어야 하므로 먼저 확인한다.

```bash
for u in https://s3.us-west-2.amazonaws.com/assets.zilliz.com \
         https://zenodo.org https://huggingface.co \
         https://cdn-lfs.huggingface.co \
         https://dl.fbaipublicfiles.com https://ann-benchmarks.com \
         https://registry-1.docker.io/v2/ https://static.crates.io \
         https://github.com ; do
  printf '%-52s ' "$u"
  curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' --max-time 10 -I "$u"
done
env | grep -i -E 'proxy|no_proxy' || echo '프록시 환경변수 없음'
getent hosts s3.us-west-2.amazonaws.com
```

**모든 줄의 상태 코드가 000이 아니어야 한다.** 401이나 403도 연결 자체는 된 것이므로 통과로 본다. 000이나 타임아웃이 하나라도 있으면 그 호스트를 6.4절의 허용 목록에 넣어 달라고 요청한다. 407이 나오면 프록시 인증이 필요하다는 뜻이다.

S3의 Range 지원도 함께 확인한다. 212GB를 중간에 끊겼다 다시 받을 때 이어받기(`curl -C -`)가 유일한 대책이고 그것이 Range에 기댄다.

```bash
curl -sI "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/test.parquet" | head -5
```

`HTTP/1.1 200` 과 `accept-ranges: bytes` 를 돌려주어야 한다. 다운로드 가이드가 2026-09-21에 이 두 값을 확인해 두었으므로, 서버에서 같은 결과가 나오면 외부 망 접근까지 한 번에 확인되는 셈이다.

### 7.2 프록시가 있을 때

프록시 환경변수가 잡혀 있으면 curl은 자동으로 따르지만 다른 도구는 따로 설정해야 한다. 최소한 아래 셋을 확인한다.

| 도구 | 설정 위치 |
|---|---|
| Docker 데몬 (이미지 내려받기) | `/etc/systemd/system/docker.service.d/http-proxy.conf` 에 `HTTP_PROXY` 와 `HTTPS_PROXY` 와 `NO_PROXY` |
| Docker 빌드 (빌드 중 네트워크) | `docker build --build-arg HTTP_PROXY=... --build-arg HTTPS_PROXY=...` |
| cargo (crates.io) | `~/.cargo/config.toml` 의 `[http] proxy` |

프록시가 없으면 이 절은 건너뛴다.

### 7.3 실효 대역폭 측정과 소요 시간 재계산

**다운로드 가이드 3.4절이 전체 소요 시간 표를 가정 대역폭으로만 채워 두었고, 작성자가 잰 약 2.7MB/s는 노트북의 가정용 회선 값이라 서버와 무관하다고 7.4절에 명시해 두었다.** 서버에서 다시 재지 않으면 212.3GB가 7분에 끝날지 하루가 걸릴지 알 수 없다.

```bash
mkdir -p "$RAW/laion100m" && cd "$RAW/laion100m"
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m"
curl -L --fail -o train-00-of-100.parquet "$B/train-00-of-100.parquet" \
  -w "bytes=%{size_download} time=%{time_total}s speed=%{speed_download} B/s\n"
```

`bytes` 가 **2,123,160,971** 로 나와야 한다. 출력된 `speed_download` 를 기록하고, 아래 표에 대입해 전체 소요 시간을 다시 계산한 뒤 다운로드 가이드 3.4절 표에 **실측값임을 밝혀** 적는다. 이 샤드는 버리지 않고 그대로 두면 나머지 99개만 더 받으면 된다.

| 대상 | 바이트 | 50MB/s | 200MB/s | 500MB/s |
|---|---:|---:|---:|---:|
| laion train 100개 (1억 개 전체) | 212,308,503,251 | 약 1시간 11분 | 약 18분 | 약 7분 |
| laion train 10개 (1000만 개) | 약 21,231,000,000 | 약 7분 | 약 2분 | 약 42초 |
| Zenodo Pes2o | 39,748,381,931 | 약 13분 | 약 3분 | 약 1분 20초 |
| 필수 원본 전체 | 약 318,000,000,000 | 약 1시간 46분 | 약 27분 | 약 11분 |

이 표의 앞 두 행은 다운로드 가이드 3.4절에서 가져온 것이고, 뒤 두 행은 같은 방식으로 이번에 계산했다.

### 7.4 네트워크 담당 사전 고지

주 데이터만 212,308,503,251바이트이고 차원 스윕용 Pes2o가 39,748,381,931바이트이며, 다운로드 가이드의 선택 사항까지 모두 받으면 약 1.27TB다. 런북은 curl을 8개 병렬로 돌리거나 `aws` CLI의 동시 요청 수를 16으로 올리라고 적고 있는데, **이 정도 지속 전송은 사내 모니터링에서 이상 트래픽으로 잡힐 수 있고 중간에 차단되면 수십 GB를 다시 받아야 한다.** 사전에 알려 두면 차단 대신 속도 조절로 협의할 여지가 생긴다.

네트워크 담당에게 전달할 것은 출발지 호스트, 목적지 서버와 경로, 총 전송량, 병렬 연결 수, 예상 시작 시각과 7.3절로 계산한 소요 시간, 그리고 문제가 생겼을 때 연락할 담당자 이름이다.

### 7.5 이 단계가 끝났다는 것을 어떻게 아는가

1. 7.1절의 아홉 줄 모두 상태 코드가 000이 아니다.
2. `accept-ranges: bytes` 를 확인했다.
3. 7.3절에서 샤드 하나를 받아 `bytes=2123160971` 을 확인했고 실측 대역폭을 기록했다.
4. 그 값으로 전체 소요 시간을 다시 계산해 다운로드 가이드 3.4절에 반영했다.
5. 네트워크 담당에게 대용량 전송을 고지했다.

---

## 8. 준비 6. 코드 받기

이 장은 Qdrant v1.19.1 소스를 확보하고 계측 빌드를 만들 수 있는 상태까지 간다. **패치 적용과 빌드와 동작 확인의 실제 절차는 `instrumented_build_2026-09-21.md` 에 있고, 이 장은 그 문서에 들어가기 전에 갖춰야 할 것만 다룬다.**

### 8.1 소스 확보

계측 빌드는 v1.19.1 소스에 18개소를 삽입하는 작업이라 태그를 고정한 체크아웃과 패치 관리가 필요하다. 설계서 3.2절이 대상 버전을 v1.19.1로 고정한다고 적고 있다.

```bash
git --version
# 없으면: sudo apt-get install -y git

cd $RAW/build
git clone --depth 1 --branch v1.19.1 https://github.com/qdrant/qdrant.git qdrant
cd qdrant
git describe --tags
grep '^version' Cargo.toml | head -1
```

`git describe --tags` 가 `v1.19.1` 을 출력하고 `Cargo.toml` 이 `version = "1.19.1"` 을 돌려주어야 한다. 다른 값이 나오면 이후 단계를 진행하지 않는다.

작업용 로컬 사본(`/Users/taejin/Projects/qdrant_v1.19.1`)이 `github.com/qdrant/qdrant.git` 의 태그 v1.19.1 체크아웃이며 HEAD가 커밋 `6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de` 임을 사전 조사가 확인했다. 서버에서 받은 체크아웃의 HEAD가 같은지 대조해 두면 패치가 그대로 붙는다.

```bash
git rev-parse HEAD
# 6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de 가 나와야 한다
```

또 하나 대조할 것이 있다. **4.5절에서 받은 `qdrant/qdrant:v1.19.1` 이미지 태그와 이 소스 태그가 정확히 같은 것을 가리키는지 첫 확인 때 대조해야 한다.** 설계서가 버전을 v1.19.1로 고정했기 때문이다.

#### 계측 패치를 서버로 옮긴다

계측 지점 18개소는 손으로 넣는 것이 아니라 패치 파일로 들어간다. 패치는 이 문서와 같은 디렉터리의 `stage_timing_v1.19.1.patch` 이고, `instrumented_build_2026-09-21.md` 4장이 그 파일이 소스 최상위에 있다고 전제하므로 **소스를 받은 직후 같은 자리에서 패치 파일도 옮겨 둔다.** 이 단계를 빼면 다음 문서의 첫 명령에서 파일을 찾지 못해 멈춘다.

```bash
# 작업 기계에서 (문서 저장소를 체크아웃한 디렉터리 안에서 실행한다)
scp docs/msr/qdrant_bottleneck/stage_timing_v1.19.1.patch \
    "$SERVER:/mnt/raw/build/qdrant/"   # 경로는 서버에서 정한 $RAW 값으로 바꾼다

# 서버에서
cd $RAW/build/qdrant
git apply --check stage_timing_v1.19.1.patch && echo '적용 가능'
```

`적용 가능` 이 나오면 소스와 패치가 맞물린 것이다. 실제 적용과 계측 지점 18개소 확인은 `instrumented_build_2026-09-21.md` 4장에서 이어서 한다. 서버가 폐쇄망이면 8.5절의 반입 절차에 이 패치 파일도 함께 넣는다.

### 8.2 빌드 경로를 먼저 정한다

**도구를 깔기 전에 이 결정을 해야 한다.** 확정된 단계 구조의 1.1이 소스를 고쳐 다시 빌드하는 작업이므로, 빌드를 호스트에서 할지 Docker로 할지에 따라 깔아야 할 것이 완전히 달라진다.

| | Docker 빌드 | 호스트 빌드 |
|---|---|---|
| 대표성 (설계서 3.2절) | 공식 이미지와 같은 빌드 설정을 그대로 써 **자동으로 만족한다** | 빌드 설정이 공식 이미지와 달라질 위험이 있다 |
| 호스트에 깔 것 | 없다 | Rust 툴체인과 네이티브 의존 패키지 여럿 |
| 반복 주기 | 느리다. 수정할 때마다 이미지 빌드를 거친다 | 빠르다. incremental 빌드가 든다 |
| 캐시 | cargo-chef 계층 캐시가 깨지면 전체 재빌드 | cargo target 재사용 |
| 측정과의 간섭 | 컨테이너 자원 제한으로 묶을 수 있다 | 344 vCPU를 cargo가 모두 점유할 수 있다 |

**절충안이 있다.** 계측 지점을 반복 수정하는 초반에는 호스트 빌드로 돌리고, 측정에 실제로 투입하는 최종 빌드만 Docker로 만든다. 이렇게 하면 반복 속도와 대표성을 모두 얻는다.

어느 쪽을 골랐는지 기록하고 아래 두 절 중 해당하는 쪽만 따른다.

### 8.3 Docker 빌드를 택했을 때

필요한 것은 buildx(4.4절)와 베이스 이미지(4.5절)와 빌드 시점 네트워크다.

```bash
docker build --help >/dev/null && echo 'docker build 사용 가능'
docker buildx version
curl -s -o /dev/null -w 'crates.io %{http_code}\n' -I https://static.crates.io
curl -s -o /dev/null -w 'github %{http_code}\n' -I https://github.com/qdrant/qdrant
df -h $(docker info --format '{{.DockerRootDir}}') | tail -1
nproc
```

`docker build` 가 동작하고 crates.io와 github에 접근되며 data-root에 수십 GB의 여유가 있어야 한다. 이 조건이 맞으면 `instrumented_build_2026-09-21.md` 4장(패치 적용)을 거쳐 5장(이미지 두 개 빌드)으로 넘어갈 수 있다. 계측 이미지와 대조 이미지는 1.1에서 같은 소스와 같은 Dockerfile 로 FEATURES 스위치만 달리해 한 번에 둘 다 만든다.

**빌드 도중 외부 망을 쓴다는 점에 주의한다.** cargo-chef 베이스 이미지, crates.io 의존성, mold 2.41.0 tarball, `cargo install cargo-sbom`, `tools/sync-web-ui.sh` 가 받는 `dist-qdrant.zip` 이 모두 빌드 시점 네트워크를 요구한다. 폐쇄망이면 이 경로가 통째로 막히므로 8.5절을 본다.

### 8.4 호스트 빌드를 택했을 때

Qdrant v1.19.1의 `Cargo.toml` 은 `rust-version = "1.97"` 과 `edition = "2024"` 를 요구하고, 공식 Dockerfile은 Rust 1.98.0 베이스로 빌드한다. **공식 이미지와 같은 조건을 맞추려면 1.98.0을 쓴다.** 이 세 값은 사전 조사가 소스에서 읽어 확인한 것이다.

```bash
rustc --version
cargo --version
# 없으면:
# curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
# rustup component add rustfmt
```

네이티브 의존 패키지도 필요하다. Qdrant v1.19.1 Dockerfile의 builder 단계가 `clang lld cmake protobuf-compiler jq` 를 설치하고 `rustup component add rustfmt` 와 `cargo install cargo-sbom` 을 하며, xx-apt-get으로 `pkg-config gcc g++ libc6-dev libunwind-dev` 를 더 설치한다. 링커는 mold 2.41.0을 tarball로 받아 쓰고, `docs/DEVELOPMENT.md` 는 protoc를 22.2 버전으로 소스 설치하라고 안내한다. 웹 UI 동기화 스크립트(`tools/sync-web-ui.sh`)는 wget 또는 curl과 unzip을 쓴다.

```bash
sudo apt-get update && sudo apt-get install -y \
  clang lld cmake protobuf-compiler jq pkg-config gcc g++ \
  libc6-dev libunwind-dev curl unzip
protoc --version
clang --version | head -1
cmake --version | head -1
```

네 명령이 모두 경로에서 찾아져야 한다. protoc가 apt 판이고 버전이 22.2보다 낮아 빌드가 실패하면 `docs/DEVELOPMENT.md` 의 소스 설치 절차를 따른다. mold는 선택이고, 없으면 `LINKER=` 를 비워 기본 링커로 빌드한다.

**빌드가 측정과 CPU를 다투지 않게 묶는다.** 빌드는 CPU를 많이 쓰므로 측정 중에는 돌리지 않고, 돌려야 한다면 3.6절에서 Qdrant 에 준 노드의 코어 열여섯 개를 피해 별도 코어에 고정한다.

```bash
# 16-79 는 예시 값이다. Qdrant 몫이 아닌 다른 노드의 코어 범위로 바꾼다
taskset -c 16-79 cargo build --release
```

### 8.5 폐쇄망일 때

7.1절에서 crates.io나 github이 000으로 나왔다면 두 빌드 경로가 모두 막힌다. 그때는 **계측 빌드를 외부 망이 되는 곳에서 만들어 이미지로 반입하는 방식을 미리 정해 두어야 한다.**

```bash
# 외부 망이 되는 기계에서
docker save qdrant:1.19.1-stagetiming qdrant:1.19.1-baseline -o qdrant-images.tar
# 측정 서버에서
docker load -i qdrant-images.tar
```

**아키텍처가 서버와 같아야 한다.** 다른 장비에서 만든 이미지는 아키텍처가 다르면 쓸 수 없고, 같더라도 CPU 최적화 설정이 달라질 수 있다는 점을 `instrumented_build_2026-09-21.md` 2장이 지적하고 있다. 파이썬 패키지도 같은 문제를 겪으므로 폐쇄망이면 휠 파일을 미리 반입해야 한다.

### 8.6 빌드 공간과 두 벌 체크아웃

설계서 3.2절이 "계측을 넣은 빌드와 넣지 않은 빌드를 같은 부하로 돌려 전체 시간이 달라지지 않음을 확인한다"고 요구하므로 바이너리가 두 개 필요하다. 한 체크아웃에서 소스를 고쳐 가며 번갈아 빌드하면 매번 전체 재빌드가 일어나 시간이 크게 든다. **체크아웃을 둘로 나누면 target 디렉터리도 둘이 되어 공간은 두 배지만 빌드 시간은 크게 준다.** 16TB에서 120GB는 0.75%라 나눌 가치가 충분하다.

**빌드 산출물은 `$BENCH` 에 두면 안 된다.** 빌드 중 입출력이 5.3절에서 분리해 둔 장치 통계를 오염시키기 때문이다.

```bash
df -B1 --output=avail $RAW/build
# 첫 빌드를 마친 뒤 반드시 실측해 5.1절의 수치를 고친다
du -sh $RAW/build/qdrant/target ~/.cargo/registry
```

빌드 전 `$RAW/build` 의 `avail` 이 최소 130GB여야 한다. 체크아웃 두 벌의 target이 한 벌당 약 60GB로 120GB이고, 여기에 cargo 레지스트리와 중간 산출물의 여유를 더한 값이다. **60GB라는 한 벌당 값은 근거를 확인하지 못한 어림값이다.** 기존 소스 트리의 `target` 이 0바이트라 한 번도 빌드된 적이 없어 실측할 수 없었으므로, 첫 빌드를 마치는 즉시 `du -sh` 로 재어 5.1절의 수치를 실측값으로 바꿔 적는다. 한 벌만 쓰기로 했다면 이 합격선은 70GB로 내려간다.

### 8.7 이 단계가 끝났다는 것을 어떻게 아는가

1. `$RAW/build/qdrant` 에 소스가 있고 `git describe --tags` 가 `v1.19.1` 을 출력한다.
2. HEAD 커밋이 `6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de` 와 같다.
3. Docker 빌드와 호스트 빌드 중 어느 쪽을 쓸지 정했고, 해당 경로의 도구가 모두 갖춰졌다.
4. `$RAW/build` 에 130GB 이상 여유가 있다.
5. 폐쇄망이면 이미지 반입 방식을 정했다.
6. `stage_timing_v1.19.1.patch` 를 소스 최상위에 두었고 `git apply --check` 가 통과했다.

이 여섯이 끝나면 **`instrumented_build_2026-09-21.md` 4장(패치 적용)으로 바로 들어간다.**

---

## 9. 준비 7. 데이터 받기

**상세 절차는 `dataset_download_2026-09-21.md` 에 있다. 이 장은 그 문서에 들어가기 전에 확인할 것과 서버에서 바꿔 써야 하는 부분만 다룬다.**

### 9.1 들어가기 전에 확인할 네 가지

| 확인 | 어디서 | 왜 |
|---|---|---|
| 용도와 라이선스에 대한 답을 받았다 | 6.5절, 6.6절 | 외부 공개 계획이 있으면 주 데이터 선택 자체가 바뀐다 |
| `$RAW` 가 정해졌고 800GB 이상 여유가 있다 | 5.1절, 5.4절 | 홈이 루트 파티션이면 212.3GB에서 서버가 멈춘다 |
| 실효 대역폭을 재서 소요 시간을 다시 계산했다 | 7.3절 | 212.3GB가 7분에 끝날지 하루가 걸릴지 모른 채 시작하지 않는다 |
| 가상환경에 pyarrow와 numpy가 들어 있다 | 4.6절 | 검증 절차가 전부 여기에 의존한다 |

### 9.2 경로 치환

다운로드 가이드의 모든 `~/vecdata` 를 `$RAW` 로 바꿔 읽는다. 이유는 5.4절에 있다. 예를 들어 다운로드 가이드 부록 B의 3번은 다음과 같이 바뀐다.

```bash
mkdir -p "$RAW/laion100m" && cd "$RAW/laion100m"
B="https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m"
for f in README.md test.parquet neighbors.parquet scalar_labels.parquet; do
  curl -sL --fail -O "$B/$f"; done
```

### 9.3 macOS 전용 명령을 리눅스 판으로 바꾼다

다운로드 가이드에는 작성자의 맥북에서 쓴 명령이 섞여 있어 리눅스 서버에서 그대로 복사해 쓰면 어긋난다. **받은 뒤 검증 단계에서 막히는 것이 가장 허무한 실패이므로 미리 바꿔 둔다.**

| 다운로드 가이드의 명령 | 위치 | 리눅스 서버에서 |
|---|---|---|
| `shasum -a 256` | 6.2절 | `sha256sum` |
| `md5 -q` | 6.2절 | `md5sum` |
| `stat -f%z` | 3.7절 주석 | `stat -c %s` 또는 `du -cb` |
| `vm_stat` | 7.5절 | `free -g` |

### 9.4 파이썬 호출 치환

4.6절에서 가상환경을 쓰기로 했다면 다운로드 가이드의 모든 `python3` 를 가상환경의 인터프리터로 바꾼다. `python3 -m pip install ...` 로 시작하는 줄은 이미 설치를 마쳤으므로 통째로 건너뛴다.

```bash
PY=~/venv/qdrant-bench/bin/python
$PY -c "import pyarrow, numpy; print(pyarrow.__version__, numpy.__version__)"
```

### 9.5 스모크부터 시작한다

파이프라인 전체(다운로드, parquet 또는 HDF5 읽기, Qdrant 적재, 검색, 리콜 계산)를 몇 분 안에 한 바퀴 돌려 보는 것이 첫 단계다. 525MB짜리 파일 하나로 끝나므로 본체를 걸기 전에 반드시 통과시킨다.

```bash
mkdir -p "$RAW/smoke" && cd "$RAW/smoke"
curl -L --fail --retry 3 -C - -o sift-128-euclidean.hdf5 \
  "https://ann-benchmarks.com/sift-128-euclidean.hdf5"
ls -l sift-128-euclidean.hdf5   # 525128288 이 나와야 한다
```

이후 절차는 `dataset_download_2026-09-21.md` 2.2절부터 그대로 따른다. **주 데이터와 완전히 같은 도구와 같은 parquet 스키마로 연습하고 싶다면 같은 문서 2.3절의 Zilliz 계열 스모크가 낫다.**

### 9.6 본체는 백그라운드로 건다

212.3GB는 한 번에 수십 분에서 수 시간이 걸리므로 tmux 안에서 `nohup` 으로 건다. 상세 명령은 `dataset_download_2026-09-21.md` 부록 B에 있고, 경로만 `$RAW` 로 바꾼다.

```bash
tmux new -s dl
cd "$RAW/laion100m"
nohup sh -c 'seq -w 1 99 | xargs -P 8 -I{} curl -sL --fail --retry 5 -C - \
  -o "train-{}-of-100.parquet" \
  "https://s3.us-west-2.amazonaws.com/assets.zilliz.com/benchmark/laion_large_100m/train-{}-of-100.parquet"' \
  > $RAW/logs/download.log 2>&1 &
```

`-P 8` 의 병렬 수는 7.4절에서 네트워크 담당과 합의한 값으로 맞춘다. 받는 동안 진행 상황은 아래로 본다.

```bash
watch -n 30 'ls -l '"$RAW"'/laion100m/train-*.parquet | wc -l; du -cb '"$RAW"'/laion100m/train-*.parquet | tail -1'
```

파일이 100개가 되고 합계가 212,308,503,251바이트여야 한다. 확인 절차의 상세는 `dataset_download_2026-09-21.md` 6장에 있다.

### 9.7 이 단계가 끝났다는 것을 어떻게 아는가

1. 스모크 테스트가 다운로드부터 리콜 계산까지 한 바퀴 돌았다.
2. laion train 100개의 바이트 합계가 212,308,503,251이다.
3. 9.3절의 macOS 명령 치환을 다운로드 가이드에 반영했다.
4. `dataset_download_2026-09-21.md` 6장의 확인 절차를 통과했다.

---

## 10. 다음 단계로

준비가 끝나면 확정된 단계 구조로 돌아간다. 준비 단계와 그 구조의 대응은 다음과 같다. 옛 "설계서 4.6절 N단계" 번호는 쓰지 않는다.

| 단계 | 무엇을 하는가 | 필요한 준비 | 들어갈 문서 |
|---|---|---|---|
| 1.1 | 소스 확보, 패치 적용, 이미지 빌드. 계측 이미지와 대조 이미지를 한 번에 둘 다 만든다 | 준비 2, 5, 6 | `instrumented_build_2026-09-21.md` 4장부터 |
| 1.2 | 조건에 맞춰 띄우기. `$BENCH` 가 붙은 NUMA 노드의 코어 16개와 메모리, 한도 128/256/512GB, 컨테이너 단위 스왑 차단, blktrace 준비 | 준비 1, 2, 3 | `environment_setup_2026-09-21.md` 3장과 4장. 3.6절의 NUMA 노드와 3.7절의 스레드 수 확인 결과를 반영한다 |
| 1.3 | 함정 확인 [완료] | 준비 1, 2 | `cgroup_trap_check_2026-09-21.md`. 결과는 6.2절 |
| 1.4 | 준비 완료 확인. 한도, 코어 고정, 스왑 차단, NUMA 정합을 컨테이너의 cgroup 값에서 읽어 확인 | 1.2 | `environment_setup_2026-09-21.md` 7장 |
| 1.5 | 조건 전환 스크립트, 잡음 제거, 부하 도구와 수집기 코어 예약, 수집기 | 1.2 | `environment_setup_2026-09-21.md` 5장과 6장, `metrics_collection_2026-09-21.md` |
| 2 | 데이터셋 받기. 2.1 라이선스 확인, 2.2 받기, 2.3 검증 | 준비 3, 4, 5, 7 | `dataset_download_2026-09-21.md` |
| 3 | 부하 도구 제작. 3.2 적재기가 세션 배정과 마스터 사본 생성까지 맡고, 3.4 제어기가 조건이 선 뒤의 적재와 부하와 수집을 순서대로 수행한다 | 준비 2 | `emulator_spec_2026-09-21.md`. 언어는 같은 문서 4.6절이 권고했고 제작 순서의 바닥 측정으로 확정한다 |
| 4 | 계측 코드와 이미지. 4.2 계측 방법, 4.3 코드 삽입, 4.4 동작 확인은 개발 빌드로 완료. 4.5 왜곡 검증은 1번과 3.3이 있어야 한다 | 준비 2, 6 | `stage_isolation_2026-09-18.md`, `instrumented_build_2026-09-21.md` 7장 |
| 5 | 측정. 5.1 예비 측정(1,000만 건, 세 조건 한 바퀴), 5.2 본 측정(1억 건, 포화점), 5.3 분석 | 1, 2, 3, 4와 동료 인계(5.2) | `instrumented_build_2026-09-21.md` 8장, `metrics_collection_2026-09-21.md` |

**1번과 2번과 3번과 4번은 서로 독립이라 동시에 진행할 수 있다.** 준비가 끝나는 대로 넷을 나란히 시작하면 된다. 다만 4.5 왜곡 검증은 1번과 3.3 부하기가 있어야 하고, 5.2 본 측정은 동료의 1단계 인계가 있어야 한다.

준비 과정에서 얻은 값 가운데 다른 문서로 되돌려 적어야 하는 것이 일곱 있다.

| 얻은 값 | 어디에 적나 |
|---|---|
| 서버 실물 사양이 전제와 다를 때 그 값 (3.1) | 설계서 4.1절, 4.5.5절 |
| SSD 가 붙은 노드의 코어 16개가 물리 코어인지 SMT 형제인지 (3.4) | 설계서 4.1절 |
| NUMA 노드당 메모리와 512GB 조건의 성립 여부 (3.4) | 설계서 4.2절 |
| `$BENCH` 장치가 붙은 NUMA 노드 번호와 그 노드의 CPU 목록 (3.6) | `environment_setup_2026-09-21.md` 3.1절 |
| 커널의 refault 지표 이름이 다를 때 (3.3) | 설계서 3.1절, `cgroup_trap_check_2026-09-21.md` 부록 B |
| 실측 대역폭과 재계산한 소요 시간 (7.3) | `dataset_download_2026-09-21.md` 3.4절 |
| 1000만 개 실측으로 고친 payload와 색인과 링크 용량 (5.9) | 이 문서 5.1절 |

---

## 11. 미확인 사항과 위험

### 11.1 이 문서 전체에 걸린 가장 큰 제약

**측정 서버에 직접 접속해 확인한 항목이 하나도 없다.** sudo 권한 유무, cgroup 버전, 프록시 유무, 디스크 파일시스템 종류와 여유, 다른 사용자 존재 여부, 실제 대역폭을 하나도 확인하지 못했다. 이 문서의 서버 관련 항목은 전부 "확인해야 할 것"이지 "확인된 것"이 아니며, 붙여 둔 명령은 서버에서 실행해 답을 채워야 한다. 데이터 경로와 서버 이름과 컬렉션 이름은 확인 전이라 `$RAW` 와 `$BENCH` 와 `$SERVER` 와 `$COLL` 이라는 셸 변수로 남겼고, 값은 서버에서 정해 채운다.

### 11.2 설계를 직접 흔드는 공백

**NUMA 노드별 메모리 용량을 모른다.** 노드당 메모리가 512GB 미만이면 512GB 조건에만 원격 메모리 접근이 섞여 128과 256과 512가 같은 성격의 세 점이 아니게 되고, 설계서 4.2절의 메모리 축 해석이 달라진다. **이것이 이번에 찾은 공백 중 가장 크다.**

**Qdrant가 cgroup의 cpuset을 읽어 스레드 수를 맞추는지 확인하지 못했다.** 소스를 직접 읽는 것이 가장 빠른 확인이지만 `/Users/taejin/Projects/qdrant_v1.19.1` 을 다른 작업이 편집 중이라 열지 않았다. 3.7절은 실행 후 스레드 수를 세는 방식으로 우회해 두었다.

**`io.stat` 의 `rbytes` 가 LVM이나 소프트웨어 RAID나 dm-crypt 위에서 어느 장치로 귀속되는지 확인하지 못했다.** 설계서 3.1절이 이 값을 진짜 디스크 읽기의 근거로 삼고 있으므로, 계층이 겹쳐 있으면 주요 페이지 폴트 횟수와 Qdrant의 hardware metric으로 교차 확인하는 절차를 추가해야 한다.

**커널 버전 경계를 검증하지 못했다.** `MADV_POPULATE_READ` 지원과 `memory.stat` 의 `workingset_refault_file` 분리는 모두 특정 커널 버전 이후에 생긴 것으로 알고 있으나, 그 경계 버전을 확인할 수단이 없었다. 그래서 두 항목 모두 버전을 근거로 판정하지 않고 서버에서 실물을 확인하는 명령으로 바꿔 적었다.

**PSI 압력 지표는 설계서 1.3절의 자원 판정을 크게 보강할 수 있지만 기존 설계에 들어 있지 않다.** 3.3절에 사용 가능 여부 확인만 넣었고, 실제로 측정 항목에 넣을지는 설계서 2.3절을 고치는 결정이 필요하다.

### 11.3 용량 계산의 어림값

**payload 용량 500바이트/포인트는 어림값이다.** MemMachine 소스에서 색인 대상 11개 필드를 확인해 JSON으로 조립하면 약 452바이트가 나오므로 500바이트는 그 위의 여유를 둔 값이다. 그러나 **설계서 4.4절의 에뮬레이터 제어 파라미터 목록에 payload 크기가 빠져 있어,** 에뮬레이터가 본문 텍스트까지 저장하도록 만들면 이 값이 몇 배로 늘고 laion 컬렉션 크기가 385.52GB를 크게 넘을 수 있다. 에뮬레이터 설계에 payload 바이트 수를 파라미터로 추가해야 한다.

**색인 합계 13.60GB는 long_term 색인 11개 기준 어림값이다.** keyword 포스팅을 포인트당 u32 4바이트로, 고카디널리티 필드(`_episode_uid`)의 값 사전을 36자 UUID 1억 개로 잡았다. 이 숫자는 옛 브랜치(msr_multiuser `89bec05`)에 있던 `_segment_uuid` 색인까지 넣은 12개 항목 기준이었으며, 기준 브랜치 speedkick `8d7b832` 에는 그 색인이 없어(부록 `emulator_request_spec_2026-09-22.md` 3장) 11개 기준으로는 약간 줄어든다. 다시 계산할 근거를 세우지 않았으므로 숫자는 그대로 둔다. Qdrant의 실제 payload 색인 파일 형식을 소스에서 확인하지 않았으므로 두 배 이상 틀릴 수 있다. 설계서 5.3.7절 실험 4가 이 값을 실측하도록 되어 있으니 그 결과로 대체한다.

**`payload_m=16` 링크 용량은 0GB에서 14.72GB 사이 어디든 될 수 있고 어느 쪽인지 지금은 알 수 없다.** 세션당 포인트 수 분포가 설계서 5.4절에서 미정이라 이 값이 정해지지 않는다. 5.9절의 1000만 개 실측이 이 위험을 먼저 잡아낸다.

**메모리 축 사다리가 laion 768차원 1억 개에서 잘 작동한다는 것은 계산으로 확인했다.** 다만 payload와 색인 어림값이 틀려 컬렉션이 512GB를 넘으면 "전부 상주하는 기준선"이 사라져 메모리 축의 위쪽 끝이 무너진다.

**세그먼트 최적화 일시 여유를 "컬렉션 한 벌분"으로 잡은 것은 보수적 규칙이며 Qdrant 문서나 소스에서 근거를 확인한 값이 아니다.** `config.yaml` 에서 확인한 것은 `max_segment_size_kb` 가 기본 null이고 `default_segment_number` 도 0이라 둘 다 CPU 수로 자동 결정된다는 사실까지다. 실제 최대 여유는 최초 전면 최적화에서 몇 개의 최적화 작업이 동시에 도는지(`max_optimization_threads` 기본 null, 무제한)에 달려 있어 확인되지 않았다.

**cargo target 60GB는 근거 없는 어림값이고 그나마 체크아웃 한 벌 기준이다.** 기존 소스 트리의 `target` 이 0바이트라 한 번도 빌드된 적이 없어 실측할 수 없었다. 8.6절대로 체크아웃을 둘로 나누면 약 120GB가 들어 필수 합계가 2,497GB가 되므로, 첫 빌드 후 반드시 실측해 5.1절과 8.6절의 두 수치를 함께 고쳐야 한다.

**선택 데이터까지 포함한 4.70TB의 내역을 항목별로 다시 세우지 않았다.** 필수 경로 2,437GB는 5.1절의 표대로 검산했으나, 선택 데이터(msmarco 원본 약 851GB, DINO 원본 약 103GB, 그리고 msmarco를 적재했을 때의 컬렉션)를 더한 총계는 조사가 계산한 값을 그대로 옮긴 것이다.

**필수 원본 합계를 재계산하면 317.43GB로 조사의 318.18GB와 0.75GB 차이가 난다.** 어느 작은 파일을 포함했는지의 차이로 보이며 결론을 바꾸지 않는다.

**다운로드 가이드 32행과 7.5절이 적은 "스모크부터 차원 스윕까지 모두 받아도 원본 합계가 약 1.27TB"는 선택 사항까지 포함한 값이다.** 필수 경로는 318.18GB이고, 여기에 4.5절의 선택 사항인 msmarco 851.22GB와 4.6절의 선택 사항인 DINO 102.58GB를 더해야 1,271.98GB가 되어 문서의 1.27TB와 일치한다. **즉 필수 다운로드량이 실제의 네 배로 읽힐 수 있다.** 이 수치를 근거로 대역폭이나 일정을 잡으면 과대 추정이 된다.

**Pes2o는 39.75GB로 받지만 2560차원 float32로 전개하면 84.89GB가 되어 두 배 이상 커진다.** 그리고 다운로드 가이드 7.4절이 적은 대로 npz 내부 압축 방식이 아직 확인되지 않아, deflate가 아니라 무압축이면 전개 후 크기가 달라질 수 있다. MRL 절단으로 1536과 1024와 768을 모두 만들면 110.36GB가 더 붙어 Pes2o 한 데이터셋만으로 195.25GB를 차지한다.

### 11.4 도구와 버전의 미확인

**Docker의 버전 하한을 확인하지 못했다.** cgroup v2 드라이버 지원과 BuildKit 기본 활성화가 어느 버전부터인지 검증하지 않았으므로, 버전 숫자로 판단하지 말고 `docker info` 출력과 `docker buildx version` 결과로만 판정한다.

**curl과 awk와 xargs와 git과 jq와 unzip의 버전 하한을 확인하지 못했다.** 문서가 쓰는 옵션이 오래전부터 있던 것들이라 문제가 될 가능성은 낮아 보이지만 검증한 바는 없다.

**Debian 12 의 mawk 는 2^31 을 넘는 정수를 지수 표기로 출력하므로 `cgroup_trap_check.sh` 의 `rbytes()` 는 `printf "%.0f\n"` 로 출력한다.** 그 밖의 awk 구문이 mawk에서 전부 도는지는 실제로 돌려 보지 않았으므로, 확인 전까지는 gawk를 깔아 두는 편이 안전하다.

**AWS CLI가 apt로 깔리면 v1, 공식 번들로 깔면 v2인데 어느 쪽이 깔릴지와 v1에서 `default.s3.max_concurrent_requests` 조정이 v2와 같은 효과를 내는지 확인하지 못했다.**

**`huggingface_hub` 의 실행 파일 이름이 `huggingface-cli` 에서 `hf` 로 바뀐 하한 버전을 확인하지 못했다.** 설치 후 어느 이름이 생기는지 직접 보고 문서를 맞춘다.

**pyarrow와 numpy와 h5py의 하한 버전을 확인하지 못했다.** 더 큰 문제는 서버의 외부 망 접근 정책을 확인하지 못했다는 점인데, 폐쇄망이면 pip 설치 자체가 불가능해 휠 파일을 미리 반입해야 한다.

**PEP 668로 시스템 pip가 막혀 있는지는 배포판에 달렸고 실제 서버에서 확인하지 않았다.** `/usr/lib/python3*/EXTERNALLY-MANAGED` 존재 여부로 즉시 판정할 수 있으므로 준비 첫날에 확인한다.

**`qdrant/qdrant:v1.19.1` 태그가 실제로 존재하는지 확인하지 못했다.** 설계서가 버전을 v1.19.1로 고정했으므로 이미지 태그와 소스 태그가 정확히 같은 것을 가리키는지 첫 확인 때 대조해야 한다.

**Qdrant v1.19.1의 `Cargo.toml` 과 Dockerfile과 `config/config.yaml` 에서 읽었다고 적은 값들을 이번 세션에서 다시 확인하지 않았다.** `rust-version = "1.97"`, `edition = "2024"`, Rust 1.98.0 베이스, `wal_capacity_mb: 32`, `wal_segments_ahead: 0`, `wal_retain_closed: 1`, `full_scan_threshold_kb: 10000`, `max_segment_size_kb: null`, `default_segment_number: 0` 이 그것이다. 이 값들은 사전 조사가 소스를 읽어 확인한 것이며, **`/Users/taejin/Projects/qdrant_v1.19.1` 을 다른 작업이 편집 중이라 이번에 열지 않았다.** 8.1절의 체크아웃을 마친 뒤 서버 쪽 소스에서 다시 대조한다.

**컨테이너 안에서 perf를 붙이는 데 필요한 capability는 Qdrant 문서와 소스 어디에도 근거가 없다고 `qdrant_instrumentation_2026-09-17.md` 9장이 적고 있다.** perf를 쓸 계획이라면 도구 설치와 별개로 직접 실험해 확인해야 한다.

**Pyroscope와 Prometheus는 설계서가 쓴다고만 적고 어떤 이미지와 태그로 무엇을 어떻게 띄울지 정해 두지 않았다.** 스크레이프 주기는 `qdrant_instrumentation_2026-09-17.md` 3.3절 때문에 교란 변수이므로 값을 정하고 기록하는 규칙까지 준비 단계에서 확정해야 한다.

**3.3절의 `MADV_POPULATE_READ` 탐지 스크립트를 리눅스에서 실제로 돌려 보지 않았다.** 주소가 잘리지 않도록 `argtypes` 를 지정하고 버퍼를 `mmap` 으로 잡도록 고쳤으나, 지원하는 커널에서 `rc=0` 이, 지원하지 않는 커널에서 `errno=22` 가 나오는 것까지 확인하지는 못했다. 첫 실행에서 두 값 중 어느 쪽도 아닌 결과가 나오면 판정 문구부터 고쳐야 한다.

**측정 서버의 배포판과 커널 출처를 몰라 perf와 cpupower가 실제로 깔릴지 알 수 없다.** `linux-tools-common` 과 `linux-tools-$(uname -r)` 는 우분투 전용이고 데비안에는 `linux-perf` 와 `linux-cpupower` 가 있으며, 우분투라도 배포판이 제공하지 않는 커널을 쓰고 있으면 `linux-tools-$(uname -r)` 가 없다. 4.2절은 커널 의존 패키지를 별도 명령으로 분리해 나머지 설치가 함께 실패하지 않게 해 두었으나, 두 도구가 끝내 없을 가능성은 남아 있다.

**`$BENCH` 아래의 블록 장치 이름을 얻는 방법이 장치 구성에 따라 달라진다.** 3.6절은 `lsblk -no PKNAME` 으로 상위 장치를 얻도록 했으나, 파티션 없이 장치를 통째로 마운트했거나 LVM이나 소프트웨어 RAID가 겹쳐 있으면 빈 값이나 매퍼 이름이 나온다. readahead 값이 그 절의 핵심 산출물이므로, 다섯 줄이 모두 값을 내는지 확인하지 않으면 장치를 잘못 잡은 상태가 합격으로 읽힌다.

**`kernel.dmesg_restrict` 값을 모른다.** 1이면 비root의 `dmesg` 가 실패하므로 3.5절은 sudo로 커널 로그를 파일에 받아 그 파일을 검색하도록 고쳤다. sudo를 받기 전에는 OOM 이력과 디스크 오류 이력 확인 자체가 불가능하며, 그 상태에서 "기록이 없다"고 적으면 안 된다.

### 11.5 아직 정해지지 않은 결정

**부하 생성기와 에뮬레이터를 어떤 언어로 만들지 설계서 4.4절이 정하지 않았다.** `emulator_spec_2026-09-21.md` 4.6절이 부하기는 Rust, 적재기와 제어기는 파이썬으로 권고했으나 제작 순서의 바닥 측정으로 확정하기 전까지는 확정으로 쓰지 않는다. 파이썬이면 그쪽 패키지가, Rust면 호스트 툴체인이 추가로 필요해지므로 이 선택이 확정되기 전에는 그쪽 도구 목록을 확정할 수 없다.

**계측 빌드를 호스트에서 할지 Docker로 할지 정하지 않았다.** 8.2절이 비교표와 절충안을 제시했으나 선택은 남아 있다. 호스트에서 cargo로 빌드하면 344 vCPU를 cargo가 모두 점유해 같은 서버에서 도는 측정과 간섭할 수 있으므로, 빌드와 측정을 같은 시간대에 돌리지 않거나 빌드 쪽 코어를 고정해야 한다.

**파이썬 패키지를 시스템에 깔지 가상환경에 깔지 정하지 않았다.** 4.6절이 가상환경을 권했으나 선택은 남아 있고, 선택에 따라 다운로드 가이드의 `python3` 치환 범위가 달라진다.

**Prometheus 수집기를 띄울지 스크립트로 고정 주기 수집하고 백분위를 직접 계산할지 정하지 않았다.** 측정 시작 전에 정해야 한다.

### 11.6 사람과 조직에 대한 미확인

**서버가 전용인지 공유인지 모른다.** 공유라면 `drop_caches` 와 sysctl 변경은 다른 작업의 성능을 즉시 떨어뜨리고, `swapoff -a` 는 이미 스왑에 나가 있는 페이지를 메모리로 되돌리면서 호스트 전체를 OOM으로 몰 수 있다. 스왑은 호스트 전역을 끄는 대신 컨테이너마다 `--memory-swap` 을 `--memory` 와 같게 주는 방식으로 충분하며, `cgroup_trap_check_2026-09-21.md` 4.2절도 같은 판단을 적어 두었다.

**사내 조직 구조를 모른다.** 법무와 네트워크 담당과 서버 소유 부서가 각각 누구인지 확인하지 못했으므로 6장은 역할 이름으로만 적었다. **실제 담당자 이름을 채우는 것은 TL이 해야 할 일이다.**

**Hugging Face 익명 다운로드의 rate limit을 재현해 보지 않았다.** 다운로드 가이드 5.1절이 걸린 사례가 있다고 적었을 뿐이고, 샤드를 연속으로 받아 실제로 걸리는지 시험하지 않았다. 따라서 대체 경로에서 토큰이 반드시 필요한지 편의 항목인지는 확정되지 않았다.

**임베딩 벡터가 원본 저작물의 2차적 저작물에 해당하는지는 법적 판단이 필요하고 이 문서가 답할 수 없다.** "벡터만 쓰니 안전하다"는 가정을 우리가 단독으로 세우면 안 되며, 그 판단을 요청하는 것까지가 6.5절의 범위다.

**Qdrant가 Apache-2.0이라는 것은 널리 알려져 있으나 이번에 라이선스 파일을 직접 확인하지 않았다.** 제품명을 밝힌 벤치마크 결과 공개를 제한하는 조항이 상용 배포판이나 관리형 서비스 약관에 있는지도 확인하지 않았으므로, 6.9절은 단정하지 않고 확인 항목으로만 적었다.

**Zilliz 배포본의 라이선스 부재는 2026-09-21에 직접 확인한 사실이지만, Zilliz에 문의했을 때 답이 올지와 얼마나 걸릴지는 알 수 없다.** 6.5절에서 외부 공개 계획이 있다고 나오는 경우 이 회신 지연이 곧 일정 위험이 된다.

**동료의 1단계 합류 시점이 설계서 5.4절에서 미정으로 남아 있다.** 6.10절을 막고 있는 것은 우리 쪽 준비가 아니라 남의 일정이므로, **우리가 통제할 수 없는 유일한 blocker다.**

### 11.7 판정 기준을 절대 수치로 정하지 않은 것

**디스크 읽기 성능의 합격 기준을 절대 수치로 정하지 않았다.** 서버의 장치를 모르는 상태에서 숫자를 적으면 지어낸 값이 되므로, 기준선을 재서 기록하는 것 자체를 합격 조건으로 두었다. 판정은 조건 사이의 비교로 한다.

**3.1절부터 3.8절까지의 합격 기준은 표준 도구의 일반적인 출력 형식에 기대어 적은 것이다.** 이 서버에서 처음 돌릴 때 출력이 다르면 기준 문구부터 고쳐야 한다.
