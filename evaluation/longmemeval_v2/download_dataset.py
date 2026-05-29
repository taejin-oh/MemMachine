#!/usr/bin/env python3
"""LongMemEval-V2 데이터셋 다운로드 + 준비 + 검증 — 단일 스크립트.

upstream V2 저장소를 클론하거나 무거운 conda 환경을 깔 필요 없이, HuggingFace
에서 직접 받고 (`huggingface_hub.snapshot_download`) tar archive 도 자체적으로
풀어 `screenshots/` 디렉토리를 만든다.

기본 destination: `evaluation/data/longmemeval-v2/` (우리 repo 의 evaluation/data
아래). `run_eval.py --data-root` 와 정렬됨.

빠른 스모크: `--skip-screenshots` 로 ~수십 MB 텍스트만 받아 즉시 평가 가능
(MemMachine 어댑터는 screenshot path 만 metadata 에 저장하지 이미지 자체는
임베딩 안 함 — screenshots 없어도 검색 정확도 영향 0).

Usage:
    # 기본: 전체 다운로드 + tar 풀기 + small tier 검증
    uv run python -m evaluation.longmemeval_v2.download_dataset

    # 빠른 스모크용 (이미지 archive 제외, ~수십 MB)
    uv run python -m evaluation.longmemeval_v2.download_dataset \\
        --skip-screenshots --skip-validate

    # 다른 위치에 받기
    uv run python -m evaluation.longmemeval_v2.download_dataset \\
        --data-root /custom/path/lmev2

    # 기존 데이터 지우고 재다운로드
    uv run python -m evaluation.longmemeval_v2.download_dataset --force
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

# 우리 repo 의 evaluation/data/longmemeval-v2 가 기본 위치.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "evaluation" / "data" / "longmemeval-v2"
DEFAULT_REPO_ID = "xiaowu0162/longmemeval-v2"

# screenshot archive 들 — `--skip-screenshots` 일 때 제외 패턴.
SCREENSHOT_ARCHIVE_NAMES = (
    "web_screenshots",
    "enterprise_screenshots_base",
    "enterprise_screenshots_patch",
)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Download (huggingface_hub.snapshot_download)
# ---------------------------------------------------------------------------
def _download(
    *,
    data_root: Path,
    repo_id: str,
    revision: str | None,
    skip_screenshots: bool,
    force: bool,
) -> dict[str, Any]:
    if force and data_root.exists():
        print(f"[download] --force: removing existing {data_root}")
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True, exist_ok=True)

    if (data_root / "questions.jsonl").exists() and (
        data_root / "trajectories.jsonl"
    ).exists() and not force:
        print(f"[download] already present at {data_root} — skipping (use --force to redownload)")
        return {"status": "already_present", "data_root": str(data_root)}

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub 미설치. `uv pip install 'huggingface_hub[cli]>=0.24'` 후 재시도."
        ) from exc

    ignore_patterns: list[str] | None = None
    if skip_screenshots:
        # screenshots tar 들 + question 이미지 디렉토리 제외 (텍스트만)
        ignore_patterns = [
            f"trajectory_screenshots/{name}.tar.gz" for name in SCREENSHOT_ARCHIVE_NAMES
        ] + ["question_screenshots/**"]
        print(
            f"[download] --skip-screenshots: ignore patterns = {ignore_patterns}"
        )

    print(f"[download] snapshot_download repo_id={repo_id} → {data_root}")
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(data_root),
        ignore_patterns=ignore_patterns,
    )
    _require(
        (data_root / "questions.jsonl").exists(),
        f"download finished but {data_root / 'questions.jsonl'} 없음 — license 동의했나요?",
    )
    _require(
        (data_root / "trajectories.jsonl").exists(),
        f"download finished but {data_root / 'trajectories.jsonl'} 없음",
    )
    return {
        "status": "downloaded",
        "data_root": str(data_root),
        "repo_id": repo_id,
        "revision": revision,
        "skipped_screenshots": skip_screenshots,
    }


# ---------------------------------------------------------------------------
# Screenshot tar 풀기 + symlink (upstream prepare_data.py 와 동등)
# ---------------------------------------------------------------------------
def _safe_extract_tar(tar_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as archive:
        dest_resolved = destination.resolve()
        for member in archive.getmembers():
            member_target = (destination / member.name).resolve()
            _require(
                dest_resolved == member_target or dest_resolved in member_target.parents,
                f"unsafe archive member path: {member.name}",
            )
        archive.extractall(destination)


def _link_or_copy_dir(src: Path, dst: Path, *, mode: str) -> str:
    if dst.exists() or dst.is_symlink():
        return "skipped"
    if mode == "symlink":
        try:
            rel = os.path.relpath(src.resolve(), start=dst.parent)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(rel, target_is_directory=src.is_dir())
            return "symlinked"
        except OSError:
            shutil.copytree(src, dst)
            return "copied"
    shutil.copytree(src, dst)
    return "copied"


def _prepare_screenshots(data_root: Path, *, mode: str) -> dict[str, Any]:
    screenshot_root = data_root / "screenshots"
    sources_root = data_root / "trajectory_screenshots"

    if not sources_root.exists():
        print(f"[prepare] {sources_root} 없음 — screenshot 준비 스킵")
        return {"status": "no_sources", "screenshots_root": str(screenshot_root)}

    counts = {"symlinked": 0, "copied": 0, "skipped": 0, "no_archive": 0}
    source_dirs: list[Path] = []
    for name in SCREENSHOT_ARCHIVE_NAMES:
        source_dir = sources_root / name
        tar_path = sources_root / f"{name}.tar.gz"
        if not source_dir.exists() and tar_path.exists():
            print(f"[prepare] extracting {tar_path.name} → {source_dir}")
            _safe_extract_tar(tar_path, source_dir)
        if source_dir.exists() and source_dir.is_dir():
            source_dirs.append(source_dir)
        else:
            counts["no_archive"] += 1

    if not source_dirs:
        print("[prepare] 펼친 screenshot directory 0 개 — --skip-screenshots 로 받았거나 아카이브 없음")
        return {
            "status": "no_archives",
            "screenshots_root": str(screenshot_root),
            "counts": counts,
        }

    for source_dir in source_dirs:
        for trajectory_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            status = _link_or_copy_dir(
                trajectory_dir,
                screenshot_root / trajectory_dir.name,
                mode=mode,
            )
            counts[status] += 1
    print(f"[prepare] screenshots: {counts}")
    return {
        "status": "ok",
        "screenshots_root": str(screenshot_root),
        "source_dirs": [str(p) for p in source_dirs],
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# Validate (간단 무결성: haystack ↔ questions ↔ trajectories cross-ref)
# ---------------------------------------------------------------------------
def _validate(data_root: Path, *, tier: str, check_screenshots: bool) -> dict[str, Any]:  # noqa: C901
    _require(tier in {"small", "medium"}, "--tier must be small or medium")
    questions_path = data_root / "questions.jsonl"
    trajectories_path = data_root / "trajectories.jsonl"
    haystack_path = data_root / "haystacks" / f"lme_v2_{tier}.json"
    _require(haystack_path.exists(), f"missing haystack: {haystack_path}")

    question_ids: set[str] = set()
    n_questions = 0
    with questions_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qid = row.get("id")
            _require(isinstance(qid, str) and qid, f"invalid question id: {row}")
            question_ids.add(qid)
            n_questions += 1
            _require(
                row.get("domain") in {"web", "enterprise"},
                f"invalid question domain for {qid}: {row.get('domain')}",
            )

    trajectory_ids: set[str] = set()
    with trajectories_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            tid = row.get("id")
            _require(isinstance(tid, str) and tid, f"invalid trajectory id: {row}")
            _require(tid not in trajectory_ids, f"duplicate trajectory id: {tid}")
            trajectory_ids.add(tid)

    haystack = json.loads(haystack_path.read_text(encoding="utf-8"))
    _require(isinstance(haystack, dict), f"haystack must be an object: {haystack_path}")
    unknown_q = set(haystack) - question_ids
    _require(not unknown_q, f"haystack references unknown question ids: {sorted(unknown_q)[:5]}")
    missing_haystack = question_ids - set(haystack)
    if missing_haystack:
        print(
            f"[validate] WARN: {len(missing_haystack)} question(s) without haystack entry "
            f"(첫 5: {sorted(missing_haystack)[:5]})"
        )

    unknown_t = 0
    for tids in haystack.values():
        for tid in tids:
            if tid not in trajectory_ids:
                unknown_t += 1
    _require(unknown_t == 0, f"haystack references {unknown_t} unknown trajectory ids")

    missing_screenshots = 0
    if check_screenshots:
        # 간단 sanity — 첫 50 trajectory 만 체크 (전체는 너무 느림)
        sampled = 0
        with trajectories_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if sampled >= 50:
                    break
                row = json.loads(line)
                sampled += 1
                for state in row.get("states", []) or []:
                    sv = state.get("screenshot")
                    if isinstance(sv, str) and not (data_root / sv).exists():
                        missing_screenshots += 1
        if missing_screenshots:
            print(
                f"[validate] WARN: 첫 50 trajectory 샘플에서 {missing_screenshots}개 screenshot 누락 "
                "(--skip-screenshots 로 받았거나 prepare 미실행. 텍스트-only 평가엔 무해.)"
            )

    return {
        "tier": tier,
        "n_questions": n_questions,
        "n_trajectories": len(trajectory_ids),
        "n_haystack_entries": len(haystack),
        "missing_haystack_questions": len(missing_haystack),
        "sampled_missing_screenshots": missing_screenshots,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--data-root",
        default=str(DEFAULT_DATA_ROOT),
        help=f"다운로드 destination (기본: {DEFAULT_DATA_ROOT})",
    )
    p.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    p.add_argument("--revision", default=None)
    p.add_argument(
        "--force",
        action="store_true",
        help="기존 데이터 디렉토리 삭제 후 재다운로드",
    )
    p.add_argument(
        "--skip-screenshots",
        action="store_true",
        help="screenshot tar archive 제외 (텍스트-only, 빠른 스모크용 — 수십 MB)",
    )
    p.add_argument(
        "--skip-extract",
        action="store_true",
        help="screenshot tar 풀기 스킵 (다운로드만)",
    )
    p.add_argument(
        "--prepare-mode",
        default="symlink",
        choices=["symlink", "copy"],
        help="screenshot 디렉토리 배치 방식 (default: symlink, 디스크 절약)",
    )
    p.add_argument(
        "--skip-validate",
        action="store_true",
        help="무결성 검증 스킵",
    )
    p.add_argument(
        "--tier",
        default="small",
        choices=["small", "medium"],
        help="validate 시 검사할 haystack tier (default: small)",
    )
    args = p.parse_args()

    data_root = Path(args.data_root).expanduser().resolve()

    print("=" * 60)
    print("LongMemEval-V2 dataset downloader")
    print(f"  repo_id:   {args.repo_id}")
    print(f"  data_root: {data_root}")
    if args.skip_screenshots:
        print("  mode:      TEXT-ONLY (screenshot archive 제외)")
    print("=" * 60)

    summary: dict[str, Any] = {}
    summary["download"] = _download(
        data_root=data_root,
        repo_id=args.repo_id,
        revision=args.revision,
        skip_screenshots=args.skip_screenshots,
        force=args.force,
    )

    if args.skip_extract or args.skip_screenshots:
        print("[prepare] 스킵 (--skip-extract or --skip-screenshots)")
        summary["prepare"] = {"status": "skipped"}
    else:
        summary["prepare"] = _prepare_screenshots(data_root, mode=args.prepare_mode)

    if args.skip_validate:
        print("[validate] 스킵 (--skip-validate)")
        summary["validate"] = {"status": "skipped"}
    else:
        summary["validate"] = _validate(
            data_root,
            tier=args.tier,
            check_screenshots=not (args.skip_screenshots or args.skip_extract),
        )

    print("\n" + "=" * 60)
    print("완료")
    print("=" * 60)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(
        "\n다음 단계 — 일부만 평가 (스모크):\n"
        f"  uv run python -m evaluation.longmemeval_v2.run_eval \\\n"
        f"      --data-root {data_root} \\\n"
        f"      --domain web --tier {args.tier} \\\n"
        f"      --memmachine-configuration-path <PATH>/configuration.yml \\\n"
        f"      --output-dir results/lmev2_smoke \\\n"
        f"      --limit 2"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
