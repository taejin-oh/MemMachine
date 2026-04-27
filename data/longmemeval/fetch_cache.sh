#!/usr/bin/env bash
# Populate a Hugging Face cache for `xiaowu0162/longmemeval-cleaned` with the
# split files needed by `evaluation/retrieval_agent/longmemeval_test.py`.
#
# Usage:
#   bash data/longmemeval/fetch_cache.sh                  # populate ~/.cache/huggingface
#   HF_HOME=/some/path bash data/longmemeval/fetch_cache.sh
#
# After this script runs you can `export HF_HUB_OFFLINE=1` and the JSON
# fallback path in longmemeval_test.py will resolve `longmemeval_s.json`
# (and `longmemeval_oracle.json`, `longmemeval_m.json`) from the cache.
set -euo pipefail

REPO_ID="xiaowu0162/longmemeval-cleaned"
CACHE_NAME="datasets--xiaowu0162--longmemeval-cleaned"
HF_HOME_DEFAULT="${HF_HOME:-$HOME/.cache/huggingface}"
HF_HUB_DIR="$HF_HOME_DEFAULT/hub"

mkdir -p "$HF_HUB_DIR"

if ! python -c "import huggingface_hub" >/dev/null 2>&1; then
    echo "huggingface_hub not installed. Install with: pip install huggingface_hub" >&2
    exit 1
fi

HF_HOME="$HF_HOME_DEFAULT" python - <<'PY'
import os, time
from huggingface_hub import hf_hub_download
files = [
    "README.md",
    "longmemeval_oracle.json",
    "longmemeval_s_cleaned.json",
    "longmemeval_m_cleaned.json",
]
for f in files:
    last_err = None
    for attempt in range(1, 6):
        try:
            t0 = time.time()
            p = hf_hub_download(
                repo_id="xiaowu0162/longmemeval-cleaned",
                repo_type="dataset",
                filename=f,
            )
            print(f"OK {f}: {os.path.getsize(p)} bytes in {time.time()-t0:.1f}s")
            break
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            print(f"  attempt {attempt} for {f} failed: {type(e).__name__}; sleep {wait}s")
            time.sleep(wait)
    else:
        raise SystemExit(f"failed to fetch {f}: {last_err}")
PY

CACHE_ROOT="$HF_HUB_DIR/$CACHE_NAME"
SNAP_DIR=$(ls -d "$CACHE_ROOT"/snapshots/*/ | head -1)
SNAP_DIR="${SNAP_DIR%/}"

# Aliases so configs that keep `split: longmemeval_s` (or _m) resolve via
# the fallback path that requests filename=f"{split}.json".
for pair in "longmemeval_s_cleaned.json:longmemeval_s.json" \
            "longmemeval_m_cleaned.json:longmemeval_m.json"; do
    src="${pair%%:*}"
    dst="${pair##*:}"
    target="$(readlink "$SNAP_DIR/$src")"
    ln -sfn "$target" "$SNAP_DIR/$dst"
    echo "alias $dst -> $target"
done

echo
echo "Cache populated at: $CACHE_ROOT"
echo "Now: export HF_HUB_OFFLINE=1"
