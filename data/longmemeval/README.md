# LongMemEval cache

Hugging Face cache scaffold for the
[`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
dataset. Lets the retrieval-agent benchmarks run on machines with no
outbound internet, after one priming download on a connected machine.

## What's vendored

The repository tracks a partial Hugging Face Hub cache for the dataset
under `hf_cache/` (laid out as `~/.cache/huggingface/hub/datasets--xiaowu0162--longmemeval-cleaned/`):

```
hf_cache/
├── blobs/
│   ├── 4f9ea7d143...       # README.md (626 B)
│   └── 821a2034d2...       # longmemeval_oracle.json (15 MB)
├── refs/main               # commit 98d7416c... pinning the snapshot
└── snapshots/98d7416c.../
    ├── README.md           # symlink → blob
    └── longmemeval_oracle.json  # symlink → blob
```

Only **`longmemeval_oracle.json`** (15 MB) is vendored in-tree.
`longmemeval_s_cleaned.json` (~265 MB) and `longmemeval_m_cleaned.json`
(~2.6 GB) **exceed GitHub's 100 MB hard per-file limit** and the LFS
endpoint is not reachable from this fork's hosting environment, so they
must be fetched once on a connected machine via `fetch_cache.sh` (below).

After running the script the cache also gains alias snapshots
`longmemeval_s.json` and `longmemeval_m.json` that point at the same blobs
as their `_cleaned` siblings, so the JSON fallback in
`evaluation/retrieval_agent/longmemeval_test.py:312-316`
(`hf_hub_download(..., filename=f"{split}.json")`) resolves successfully
when `configs/problems/p[34].yaml` keeps `split: longmemeval_s`.

## Priming the cache (connected machine)

```bash
pip install huggingface_hub
bash data/longmemeval/fetch_cache.sh
```

The script downloads all four files (oracle, s_cleaned, m_cleaned, README)
into `${HF_HOME:-$HOME/.cache/huggingface}/hub/datasets--xiaowu0162--longmemeval-cleaned/`
via `huggingface_hub.hf_hub_download` (the same call the eval tool makes)
and adds the `longmemeval_s.json` / `longmemeval_m.json` aliases.

To prime an in-repo cache instead of the user-level one:

```bash
HF_HOME="$(pwd)/data/longmemeval/hf_cache_home" \
    bash data/longmemeval/fetch_cache.sh
```

## Using the cache offline

Once primed, set `HF_HUB_OFFLINE=1` and run the eval normally:

```bash
export HF_HUB_OFFLINE=1
# (or HF_HOME=/path/to/your/cache_home if you primed a non-default location)
python evaluation/retrieval_agent/longmemeval_test.py ingest --config configs/problems/p4.yaml
```

The fallback path resolves `longmemeval_s.json` from disk; no HF call is
needed. `configs/problems/p[34].yaml` can keep `split: longmemeval_s`
unchanged.

If you only need the **oracle** split, the in-tree `hf_cache/` is
self-sufficient — copy it into the HF cache root and you're done:

```bash
mkdir -p ~/.cache/huggingface/hub
cp -a data/longmemeval/hf_cache ~/.cache/huggingface/hub/datasets--xiaowu0162--longmemeval-cleaned
export HF_HUB_OFFLINE=1
```

Use `cp -a` (or `cp -aL` on filesystems without symlink support) to
preserve the `snapshots/` symlinks.

## Source and license

- **Source:** Hugging Face dataset
  [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
  (commit `98d7416c24c778c2fee6e6f3006e7a073259d48f`).
- **License:** MIT (per the dataset card).
- **Upstream benchmark:** [LongMemEval](https://github.com/xiaowu0162/LongMemEval).

The vendored file is redistributed unchanged under MIT.
