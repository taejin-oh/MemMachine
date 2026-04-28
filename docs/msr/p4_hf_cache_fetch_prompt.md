# 다른 세션용 prompt — HuggingFace 캐시를 받아 repo 에 올리기

> **시나리오**: 오프라인 머신에서 PR #7 평가 도구의 LongMemEval 평가를 돌리고 싶다. HuggingFace 인터넷 접속이 안 되는 환경이므로, **인터넷 되는 다른 환경의 Claude Code 세션** 에 데이터를 받아 이 repo 에 올리는 일을 시키고, 오프라인 머신에서는 그 repo 를 pull 만 받으면 되도록 한다.

---

## 다른 세션에 그대로 붙여넣을 prompt

````
이 repo 는 MemMachine fork 이고, 평가 도구가 HuggingFace `xiaowu0162/longmemeval-cleaned`
데이터셋의 split JSON 파일을 필요로 한다. 이 머신은 인터넷이 되니까, 그 데이터셋을
다운로드해서 repo 안의 `data/longmemeval/hf_cache/` 디렉토리에 박아넣고 커밋/푸시해 줘.

요구사항:
1. 작업 브랜치: `claude/longmemeval-hf-cache` (없으면 새로 생성, 있으면 그 위에서 계속)
2. 다운로드할 split:
     - longmemeval_s.json       (필수)
     - longmemeval_oracle.json  (선택, smoke test 용 — 작아서 같이 받자)
     - longmemeval_m.json       (받지 말 것 — 너무 큼)
3. 받는 방법은 `huggingface_hub.hf_hub_download` 사용. 이유: PR7 평가 도구의
   fallback 경로(`evaluation/retrieval_agent/longmemeval_test.py:310-316`)가 정확히
   이 함수를 부르고, 캐시 구조(blobs/snapshots/refs)가 그 호출과 호환돼야 한다.
4. 받은 파일을 repo 에 박아넣을 위치: `data/longmemeval/hf_cache/`
   `~/.cache/huggingface/hub/datasets--xiaowu0162--longmemeval-cleaned/` 의 내용을
   그 디렉토리로 통째로 복사. snapshots/ 의 symlink 가 깨지지 않도록 `cp -aL` 또는
   `cp -a` 로. (오프라인 머신에서 같은 구조를 바로 쓰는 게 목적)
5. 파일 크기 확인: 각 split 파일이 100MB 를 넘으면 **GitHub 단일 파일 제한**에 걸리므로,
   넘는 파일은 Git LFS 로 등록 (`git lfs install && git lfs track "data/longmemeval/hf_cache/**/*.json"`).
   100MB 이하면 LFS 없이 그대로 커밋. 파일 크기는 `du -h` 로 보고만 해 줘.
6. `.gitattributes` 가 LFS 트래킹을 위해 수정되면 그것도 같이 커밋.
7. 사용 방법을 짧게 적은 `data/longmemeval/README.md` 를 같이 만든다. 내용:
     - 어디서 받았는지 (`xiaowu0162/longmemeval-cleaned`)
     - 오프라인 머신에서 어떻게 쓰는지:
         export HF_HOME=$(pwd)/data/longmemeval/hf_cache_home
         mkdir -p $HF_HOME/hub
         cp -a data/longmemeval/hf_cache $HF_HOME/hub/datasets--xiaowu0162--longmemeval-cleaned
         export HF_HUB_OFFLINE=1
       또는 더 단순하게, `~/.cache/huggingface/hub/` 에 `data/longmemeval/hf_cache/`
       내용을 `datasets--xiaowu0162--longmemeval-cleaned` 라는 이름으로 그대로 복사하고
       `HF_HUB_OFFLINE=1` 만 export.
     - p4.yaml 의 `split: longmemeval_s` 를 그대로 둬도 fallback 경로가 캐시에서 찾음.
8. 라이센스: LongMemEval 은 공개 데이터셋이지만, 이 repo 가 public 이라면 원본 라이센스를
   확인하고 LICENSE 또는 README 에 출처/라이센스 한 줄 추가. private repo 라면 출처만.

작업 흐름:
  1) 환경 확인: `pip show huggingface_hub` (없으면 설치)
  2) 새 브랜치 생성 또는 체크아웃
  3) 다운로드 스크립트 1회 실행
  4) repo 안으로 복사, 크기 확인, 필요 시 LFS 셋업
  5) `data/longmemeval/README.md` 작성
  6) commit, push, PR 생성 (draft)

작업 끝나면 PR URL 과 받은 파일들의 크기를 보고해 줘.
````

---

## 사용자가 이 prompt 를 다른 세션에 넘기기 전에 확인할 점

1. **public/private repo 정책**: LongMemEval 데이터를 repo 에 올려도 되는지 본인 조직 정책으로 한 번 확인. 보통 공개 학술 데이터셋은 OK 지만, 회사 정책이 외부 데이터의 사내 repo 미러링을 막는 경우도 있음.
2. **저장 위치 변경 의사**: 위 prompt 는 `data/longmemeval/hf_cache/` 를 쓰는데, 다른 위치를 원하면 prompt 의 경로 부분만 바꿔서 전달.
3. **LFS 비용/사용량**: GitHub LFS 는 무료 quota 가 작음 (월 1GB bandwidth, 1GB storage). LongMemEval `s` split 이 100MB 안 넘으면 그냥 커밋이 깔끔. 넘으면 Git LFS 또는 외부 스토리지(S3 등) 고려.
4. **인터넷 머신의 보안**: 그 머신이 회사 git 에 push 권한 있는지, SSO 토큰 만료 안 됐는지 미리 확인.

---

## 받은 후 본 머신(오프라인) 에서 할 일

1. `git pull origin claude/longmemeval-hf-cache` (또는 머지된 브랜치)
2. 캐시 위치 동기화 — 두 옵션 중 택1:
   - **HF 기본 캐시 위치 사용**:
     ```sh
     mkdir -p ~/.cache/huggingface/hub
     cp -a data/longmemeval/hf_cache ~/.cache/huggingface/hub/datasets--xiaowu0162--longmemeval-cleaned
     export HF_HUB_OFFLINE=1
     ```
   - **HF_HOME 을 repo 내로 지정**:
     ```sh
     export HF_HOME=$(pwd)/.hf_home
     mkdir -p $HF_HOME/hub
     cp -a data/longmemeval/hf_cache $HF_HOME/hub/datasets--xiaowu0162--longmemeval-cleaned
     export HF_HUB_OFFLINE=1
     ```
3. 평가 도구 실행 (PR7 도구 그대로):
   ```sh
   python scripts/generate_config.py --problem 4 --run-name p4_pilot \
       --model-profile my_model --db-profile my_db \
       --k-list 10,20 --length 5
   python scripts/run_pipeline.py --config configs/runs/p4_pilot.yaml --stage ingest
   ```
   `_ingest_longmemeval` → `load_longmemeval_dataset` → primary path 가 오프라인 모드에서 실패하면 fallback 의 `hf_hub_download` 가 캐시에서 hit. 인터넷 없이 ingest 가 시작됨.

---

## 디버깅 힌트

- 캐시 hit 안 되면: `ls ~/.cache/huggingface/hub/datasets--xiaowu0162--longmemeval-cleaned/snapshots/*/` 에 split JSON symlink 가 있는지, blobs/ 에 실파일이 있는지 확인.
- `OSError: Cannot find 'longmemeval_s.json'` 류 에러는 보통 `HF_HUB_OFFLINE=1` 인데 캐시에 그 split 이 없을 때. 인터넷 머신에서 그 split 을 안 받았으면 다시 받아서 동기화.
- snapshots symlink 가 끊겨 있으면 (cp 시 `-L` 없이 dereference 못 한 경우 등) `hf_hub_download` 가 못 찾음. `-a` (archive, symlink 보존) 로 복사하면 안전.
