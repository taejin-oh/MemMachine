#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
RUN_TEST="${SCRIPT_DIR}/run_test.sh"
CONFIG_FILE="${SCRIPT_DIR}/configuration.yml"

DRY_RUN=false
LONGMEM_LENGTH=500
LONGMEM_SPLIT="longmemeval_s_cleaned"
LONGMEM_TARGET="retrieval_agent"
LONGMEM_K_VALUES=(10 20 30 50 100)
LONGMEM_PREFIX_VALUES=(off on)

HOTPOT_LENGTH=500
HOTPOT_SPLIT="validation"
HOTPOT_TARGET_VALUES=(memmachine retrieval_agent)

LOCOMO_TARGET_VALUES=(memmachine retrieval_agent)

usage() {
    cat <<'EOF'
Usage: ./run_benchmark_matrix.sh [--dry-run]

Runs the benchmark matrix in one command:
  - LongMemEvalS: prefix {off,on} x k {10,20,30,50,100}, length=500
  - LoCoMo: mode {memmachine,retrieval_agent}
  - HotpotQA(validation): mode {memmachine,retrieval_agent}, length=500

Options:
  --dry-run   Print commands only; do not execute.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [ ! -f "$RUN_TEST" ]; then
    echo "Error: run_test.sh not found at '${RUN_TEST}'"
    exit 1
fi

if [ "$DRY_RUN" = false ] && [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: configuration.yml not found at '${CONFIG_FILE}'"
    exit 1
fi

run_cmd() {
    if [ "$DRY_RUN" = true ]; then
        printf '[DRY-RUN] '
        printf '%q ' "$@"
        printf '\n'
        return 0
    fi

    "$@"
}

set_longmemeval_prefix() {
    local prefix="$1"
    local enabled=false
    if [ "$prefix" = "on" ]; then
        enabled=true
    fi

    python - "$CONFIG_FILE" "$enabled" <<'PY'
import sys
import yaml

config_path = sys.argv[1]
enabled = sys.argv[2].lower() == "true"

with open(config_path, "r", encoding="utf-8") as file:
    config = yaml.safe_load(file) or {}

if not isinstance(config, dict):
    config = {}

evaluation_cfg = config.setdefault("evaluation", {})
if not isinstance(evaluation_cfg, dict):
    evaluation_cfg = {}
    config["evaluation"] = evaluation_cfg

longmemeval_cfg = evaluation_cfg.setdefault("longmemeval", {})
if not isinstance(longmemeval_cfg, dict):
    longmemeval_cfg = {}
    evaluation_cfg["longmemeval"] = longmemeval_cfg

longmemeval_cfg["prepend_user_prefix"] = enabled

with open(config_path, "w", encoding="utf-8") as file:
    yaml.safe_dump(config, file, sort_keys=False)
PY
}

BACKUP_FILE=""
if [ "$DRY_RUN" = false ]; then
    BACKUP_FILE="$(mktemp "${SCRIPT_DIR}/configuration.yml.backup.XXXXXX")"
    cp "$CONFIG_FILE" "$BACKUP_FILE"
fi
restore_config() {
    if [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ]; then
        cp "$BACKUP_FILE" "$CONFIG_FILE"
        rm -f "$BACKUP_FILE"
    fi
}
trap restore_config EXIT

echo "=== LongMemEvalS matrix: prefix x k ==="
for prefix in "${LONGMEM_PREFIX_VALUES[@]}"; do
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY-RUN] Set evaluation.longmemeval.prepend_user_prefix=${prefix}"
    else
        set_longmemeval_prefix "$prefix"
    fi

    for k in "${LONGMEM_K_VALUES[@]}"; do
        postfix="lmes_${prefix}_k${k}"
        run_cmd "$RUN_TEST" longmemeval "$postfix" ingest "$LONGMEM_SPLIT" "$LONGMEM_TARGET" "$LONGMEM_LENGTH"
        run_cmd "$RUN_TEST" longmemeval "$postfix" search "$LONGMEM_SPLIT" "$LONGMEM_TARGET" "$LONGMEM_LENGTH" --search-limit "$k"
    done
done

echo "=== LoCoMo matrix: mode ==="
for mode in "${LOCOMO_TARGET_VALUES[@]}"; do
    postfix="locomo_${mode}"
    run_cmd "$RUN_TEST" locomo "$postfix" ingest "$mode"
    run_cmd "$RUN_TEST" locomo "$postfix" search "$mode"
done

echo "=== HotpotQA matrix: mode ==="
for mode in "${HOTPOT_TARGET_VALUES[@]}"; do
    postfix="hotpot_${mode}"
    run_cmd "$RUN_TEST" hotpotqa "$postfix" ingest "$HOTPOT_SPLIT" "$mode" "$HOTPOT_LENGTH"
    run_cmd "$RUN_TEST" hotpotqa "$postfix" search "$HOTPOT_SPLIT" "$mode" "$HOTPOT_LENGTH"
done

echo "Done."
