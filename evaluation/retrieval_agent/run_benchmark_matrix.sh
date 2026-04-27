#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
RUN_TEST="${SCRIPT_DIR}/run_test.sh"
CONFIG_FILE="${SCRIPT_DIR}/configuration.yml"

DRY_RUN=false
SKIP_INGEST=false
SUMMARY_PATH=""
LONGMEM_LENGTH=500
LONGMEM_SPLIT="longmemeval_s_cleaned"
LONGMEM_TARGET="retrieval_agent"
LONGMEM_K_VALUES=(10 20 30 50 100)
LONGMEM_PREFIX_VALUES=(off on)
LONGMEM_CHUNK_VALUES=(off on)

HOTPOT_LENGTH=500
HOTPOT_SPLIT="validation"
HOTPOT_TARGET_VALUES=(memmachine retrieval_agent)

LOCOMO_LENGTH=10
LOCOMO_TARGET_VALUES=(memmachine retrieval_agent)

usage() {
    cat <<'EOF'
Usage: ./run_benchmark_matrix.sh [--dry-run] [--skip-ingest] [--summary-path PATH]

Runs the benchmark matrix in one command:
  - LongMemEvalS: chunk {off,on} x prefix {off,on} x k {10,20,30,50,100}, length=500
  - LoCoMo: mode {memmachine,retrieval_agent}, length=10
  - HotpotQA(validation): mode {memmachine,retrieval_agent}, length=500

Options:
  --dry-run            Print commands only; do not execute.
  --skip-ingest        Skip all ingest steps and run search only.
  --summary-path PATH  Write command execution summary to PATH.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-ingest)
            SKIP_INGEST=true
            shift
            ;;
        --summary-path)
            if [ "$#" -lt 2 ]; then
                echo "Error: --summary-path requires a value"
                exit 1
            fi
            SUMMARY_PATH="$2"
            shift 2
            ;;
        --summary-path=*)
            SUMMARY_PATH="${1#*=}"
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

if [ -z "$SUMMARY_PATH" ]; then
    mkdir -p "${SCRIPT_DIR}/result"
    SUMMARY_PATH="${SCRIPT_DIR}/result/matrix_run_$(date -u +%Y%m%dT%H%M%SZ).log"
fi

log_summary() {
    local line="$1"
    echo "$line" | tee -a "$SUMMARY_PATH"
}

run_cmd() {
    local cmd_str
    cmd_str="$(printf '%q ' "$@")"

    if [ "$DRY_RUN" = true ]; then
        log_summary "[DRY-RUN] ${cmd_str}"
        return 0
    fi

    log_summary "[RUN] ${cmd_str}"
    if "$@"; then
        log_summary "[OK]  ${cmd_str}"
    else
        log_summary "[FAIL] ${cmd_str}"
        return 1
    fi
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

set_longmemeval_chunking() {
    local chunk="$1"
    local enabled=false
    if [ "$chunk" = "on" ]; then
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

episodic_cfg = config.setdefault("episodic_memory", {})
if not isinstance(episodic_cfg, dict):
    episodic_cfg = {}
    config["episodic_memory"] = episodic_cfg

long_term_cfg = episodic_cfg.setdefault("long_term_memory", {})
if not isinstance(long_term_cfg, dict):
    long_term_cfg = {}
    episodic_cfg["long_term_memory"] = long_term_cfg

long_term_cfg["message_sentence_chunking"] = enabled

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

log_summary "=== LongMemEvalS matrix: chunk x prefix x k ==="
for chunk in "${LONGMEM_CHUNK_VALUES[@]}"; do
    if [ "$DRY_RUN" = true ]; then
        log_summary "[DRY-RUN] Set episodic_memory.long_term_memory.message_sentence_chunking=${chunk}"
    else
        set_longmemeval_chunking "$chunk"
        log_summary "[SET] episodic_memory.long_term_memory.message_sentence_chunking=${chunk}"
    fi

    for prefix in "${LONGMEM_PREFIX_VALUES[@]}"; do
        if [ "$DRY_RUN" = true ]; then
            log_summary "[DRY-RUN] Set evaluation.longmemeval.prepend_user_prefix=${prefix}"
        else
            set_longmemeval_prefix "$prefix"
            log_summary "[SET] evaluation.longmemeval.prepend_user_prefix=${prefix}"
        fi

        for k in "${LONGMEM_K_VALUES[@]}"; do
            postfix="lmes_chunk${chunk}_${prefix}_k${k}"
            if [ "$SKIP_INGEST" = false ]; then
                run_cmd "$RUN_TEST" longmemeval "$postfix" ingest "$LONGMEM_SPLIT" "$LONGMEM_TARGET" "$LONGMEM_LENGTH"
            else
                log_summary "[SKIP] ingest longmemeval ${postfix}"
            fi
            run_cmd "$RUN_TEST" longmemeval "$postfix" search "$LONGMEM_SPLIT" "$LONGMEM_TARGET" "$LONGMEM_LENGTH" --search-limit "$k"
        done
    done
done

log_summary "=== LoCoMo matrix: mode ==="
for mode in "${LOCOMO_TARGET_VALUES[@]}"; do
    postfix="locomo_${mode}"
    if [ "$SKIP_INGEST" = false ]; then
        run_cmd "$RUN_TEST" locomo "$postfix" ingest "$mode" "$LOCOMO_LENGTH"
    else
        log_summary "[SKIP] ingest locomo ${postfix}"
    fi
    run_cmd "$RUN_TEST" locomo "$postfix" search "$mode" "$LOCOMO_LENGTH"
done

log_summary "=== HotpotQA matrix: mode ==="
for mode in "${HOTPOT_TARGET_VALUES[@]}"; do
    postfix="hotpot_${mode}"
    if [ "$SKIP_INGEST" = false ]; then
        run_cmd "$RUN_TEST" hotpotqa "$postfix" ingest "$HOTPOT_SPLIT" "$mode" "$HOTPOT_LENGTH"
    else
        log_summary "[SKIP] ingest hotpotqa ${postfix}"
    fi
    run_cmd "$RUN_TEST" hotpotqa "$postfix" search "$HOTPOT_SPLIT" "$mode" "$HOTPOT_LENGTH"
done

log_summary "Done."
log_summary "Summary saved to: ${SUMMARY_PATH}"
