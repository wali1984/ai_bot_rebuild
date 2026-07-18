#!/usr/bin/env bash
# Reversibly quarantine the complete legacy native-trainer checkpoint root.
# The default mode is a read-only inventory. The apply path never stops or
# starts a service and never copies or upgrades an individual checkpoint.
set -Eeuo pipefail
umask 077

PERSISTENT_TRAINER_UNIT="ai-bot-v2-native-cuda-trainer-persistent.service"
CHECKPOINT_EVIDENCE_UNIT="ai-bot-v2-trainer-checkpoint-evidence.service"
MODEL_ROOT_REL=".local_models/v2_native_rl_masa_ppo"
QUARANTINE_PARENT_REL=".local_models/quarantine"
QUARANTINE_PREFIX="v2_native_rl_masa_ppo_legacy_"
ACTIVE_RECEIPT_NAME="v2_native_rl_masa_ppo_legacy_quarantine_active.receipt"
TRANSACTION_RESERVATION_NAME=".v2_native_rl_masa_ppo_legacy_quarantine.transaction"

usage() {
  cat <<'USAGE'
Usage:
  tools/quarantine_legacy_native_trainer_checkpoints.sh [--repo-root PATH]
  tools/quarantine_legacy_native_trainer_checkpoints.sh \
    --apply --ack-legacy-checkpoint-quarantine [--repo-root PATH]

Default: read-only dry-run. It inventories every regular checkpoint-root file
with SHA-256, byte size, and mtime, but changes no repository/checkpoint file.

--apply
    Permit the whole-root quarantine and fresh-root bootstrap transaction.
--ack-legacy-checkpoint-quarantine
    Acknowledge that the complete legacy checkpoint root will be atomically
    renamed out of service and that no legacy checkpoint will be migrated.
--repo-root PATH
    Override the repository root (intended for tests or a non-default clone).

Apply refuses unless both exact user services are loaded and inactive during
two observations and recursive lsof scans find no open handle under the model
root. The script never stops, starts, reloads, masks, or enables a service.
USAGE
}

APPLY=false
ACK_LEGACY_QUARANTINE=false
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT_INPUT=$(dirname -- "$SCRIPT_DIR")

while (($#)); do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --ack-legacy-checkpoint-quarantine)
      ACK_LEGACY_QUARANTINE=true
      shift
      ;;
    --repo-root)
      (($# >= 2)) || {
        echo "ERROR: --repo-root requires a path" >&2
        exit 64
      }
      REPO_ROOT_INPUT=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

if [[ "$APPLY" == true && "$ACK_LEGACY_QUARANTINE" != true ]]; then
  echo "REFUSING: --apply also requires --ack-legacy-checkpoint-quarantine." >&2
  exit 2
fi
if [[ "$APPLY" != true && "$ACK_LEGACY_QUARANTINE" == true ]]; then
  echo "REFUSING: acknowledgement without --apply is not a valid operation." >&2
  exit 2
fi

for required_command in \
  awk cat chmod cmp date dirname find install lsof mkdir mktemp mv realpath rm \
  rmdir sha256sum sort stat sync systemctl; do
  command -v "$required_command" >/dev/null 2>&1 || {
    echo "REFUSING: required command is unavailable: $required_command" >&2
    exit 3
  }
done

REPO_ROOT=$(realpath -e -- "$REPO_ROOT_INPUT") || {
  echo "REFUSING: repository root does not exist: $REPO_ROOT_INPUT" >&2
  exit 4
}
[[ -d "$REPO_ROOT" ]] || {
  echo "REFUSING: repository root is not a directory: $REPO_ROOT" >&2
  exit 4
}

MODELS_PARENT="$REPO_ROOT/.local_models"
MODEL_ROOT="$REPO_ROOT/$MODEL_ROOT_REL"
QUARANTINE_PARENT="$REPO_ROOT/$QUARANTINE_PARENT_REL"
ACTIVE_RECEIPT="$QUARANTINE_PARENT/$ACTIVE_RECEIPT_NAME"
RESERVATION="$QUARANTINE_PARENT/$TRANSACTION_RESERVATION_NAME"

[[ -d "$MODELS_PARENT" && ! -L "$MODELS_PARENT" ]] || {
  echo "REFUSING: .local_models must be an existing, non-symlink directory: $MODELS_PARENT" >&2
  exit 5
}
[[ -d "$MODEL_ROOT" && ! -L "$MODEL_ROOT" ]] || {
  echo "REFUSING: checkpoint root must be an existing, non-symlink directory: $MODEL_ROOT" >&2
  exit 5
}
if [[ -e "$QUARANTINE_PARENT" && ( ! -d "$QUARANTINE_PARENT" || -L "$QUARANTINE_PARENT" ) ]]; then
  echo "REFUSING: quarantine parent exists but is not a non-symlink directory: $QUARANTINE_PARENT" >&2
  exit 5
fi
if [[ -e "$ACTIVE_RECEIPT" ]]; then
  echo "REFUSING: an active legacy-quarantine receipt already exists: $ACTIVE_RECEIPT" >&2
  exit 6
fi
if [[ -e "$RESERVATION" ]]; then
  echo "REFUSING: a prior quarantine transaction reservation requires manual review: $RESERVATION" >&2
  exit 6
fi

# A surviving destination without a receipt is a possible interrupted prior
# transaction. Never guess whether it is safe to quarantine another root.
if [[ -d "$QUARANTINE_PARENT" ]]; then
  shopt -s nullglob
  prior_quarantine_candidates=("$QUARANTINE_PARENT"/"$QUARANTINE_PREFIX"*)
  shopt -u nullglob
  for prior_candidate in "${prior_quarantine_candidates[@]}"; do
    if [[ -d "$prior_candidate" ]]; then
      echo "REFUSING: a prior legacy quarantine directory already exists: $prior_candidate" >&2
      exit 6
    fi
  done
fi

unsupported_entry=$(find -P "$MODEL_ROOT" -mindepth 1 ! -type d ! -type f -print -quit)
if [[ -n "$unsupported_entry" ]]; then
  echo "REFUSING: checkpoint root contains a symlink or special entry: $unsupported_entry" >&2
  exit 7
fi

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
[[ "$TIMESTAMP" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
  echo "REFUSING: UTC timestamp command returned an unsafe value: $TIMESTAMP" >&2
  exit 8
}
QUARANTINE_DEST="$QUARANTINE_PARENT/${QUARANTINE_PREFIX}${TIMESTAMP}"
INVENTORY_FINAL="${QUARANTINE_DEST}.inventory.tsv"

if [[ -e "$QUARANTINE_DEST" || -e "$INVENTORY_FINAL" ]]; then
  echo "REFUSING: timestamped quarantine output already exists; rerun with a new UTC second." >&2
  exit 8
fi

TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ai-bot-checkpoint-quarantine.XXXXXX")
INVENTORY_A="$TEMP_ROOT/inventory-a.tsv"
INVENTORY_B="$TEMP_ROOT/inventory-b.tsv"
INVENTORY_C="$TEMP_ROOT/inventory-c.tsv"
LSOF_OUTPUT="$TEMP_ROOT/lsof.out"

cleanup_temporary_files() {
  rm -rf -- "$TEMP_ROOT"
}
trap cleanup_temporary_files EXIT

INVENTORY_FILE_COUNT=0
build_inventory() {
  local root=$1
  local output=$2
  local file_list="$output.files"
  local path
  local relative_path
  local checksum
  local size_bytes
  local mtime
  local count=0

  find -P "$root" -type f -print0 >"$file_list"
  sort -z -o "$file_list" -- "$file_list"
  printf 'sha256\tbytes\tmtime\trelative_path\n' >"$output"
  while IFS= read -r -d '' path; do
    relative_path=${path#"$root"/}
    case "$relative_path" in
      *$'\n'*|*$'\t'*)
        echo "REFUSING: inventory path contains a tab or newline: $relative_path" >&2
        return 1
        ;;
    esac
    checksum=$(sha256sum -- "$path")
    checksum=${checksum%% *}
    [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] || {
      echo "REFUSING: SHA-256 failed for: $path" >&2
      return 1
    }
    size_bytes=$(stat -c '%s' -- "$path")
    mtime=$(stat -c '%y' -- "$path")
    [[ "$size_bytes" =~ ^[0-9]+$ ]] || {
      echo "REFUSING: invalid file size returned for: $path" >&2
      return 1
    }
    printf '%s\t%s\t%s\t%s\n' \
      "$checksum" "$size_bytes" "$mtime" "$relative_path" >>"$output"
    count=$((count + 1))
  done <"$file_list"
  rm -f -- "$file_list"
  INVENTORY_FILE_COUNT=$count
}

READINESS_SAFE=true
observe_service_gate() {
  local phase=$1
  local unit
  local output
  local load_state
  local active_state
  for unit in "$PERSISTENT_TRAINER_UNIT" "$CHECKPOINT_EVIDENCE_UNIT"; do
    if ! output=$(systemctl --user show "$unit" \
      --property=LoadState --property=ActiveState --no-pager 2>&1); then
      printf 'SERVICE GATE [%s] %s: QUERY_FAILED\n' "$phase" "$unit" >&2
      printf '%s\n' "$output" >&2
      READINESS_SAFE=false
      continue
    fi
    load_state=$(awk -F= '$1 == "LoadState" {print $2}' <<<"$output")
    active_state=$(awk -F= '$1 == "ActiveState" {print $2}' <<<"$output")
    printf 'SERVICE GATE [%s] %s: load=%s active=%s\n' \
      "$phase" "$unit" "${load_state:-UNKNOWN}" "${active_state:-UNKNOWN}"
    if [[ "$load_state" != "loaded" || "$active_state" != "inactive" ]]; then
      READINESS_SAFE=false
    fi
  done
}

observe_open_handle_gate() {
  local phase=$1
  local lsof_rc
  : >"$LSOF_OUTPUT"
  if lsof -nP -Fn +D "$MODEL_ROOT" >"$LSOF_OUTPUT" 2>&1; then
    lsof_rc=0
  else
    lsof_rc=$?
  fi
  case "$lsof_rc" in
    0)
      printf 'OPEN-HANDLE GATE [%s]: BLOCKED\n' "$phase" >&2
      awk 'NR <= 40 {print}' "$LSOF_OUTPUT" >&2
      READINESS_SAFE=false
      ;;
    1)
      if [[ -s "$LSOF_OUTPUT" ]]; then
        printf 'OPEN-HANDLE GATE [%s]: SCAN_INCOMPLETE\n' "$phase" >&2
        awk 'NR <= 40 {print}' "$LSOF_OUTPUT" >&2
        READINESS_SAFE=false
      else
        printf 'OPEN-HANDLE GATE [%s]: CLEAR\n' "$phase"
      fi
      ;;
    *)
      printf 'OPEN-HANDLE GATE [%s]: SCAN_FAILED rc=%s\n' \
        "$phase" "$lsof_rc" >&2
      awk 'NR <= 40 {print}' "$LSOF_OUTPUT" >&2
      READINESS_SAFE=false
      ;;
  esac
}

observe_service_gate "before_inventory"
observe_open_handle_gate "before_inventory"
build_inventory "$MODEL_ROOT" "$INVENTORY_A"
FILE_COUNT_A=$INVENTORY_FILE_COUNT
((FILE_COUNT_A > 0)) || {
  echo "REFUSING: checkpoint root contains no regular files." >&2
  exit 9
}

# Hash every file twice. This detects a changing size, mtime, path set, or
# content even when a short-lived writer evades one point-in-time lsof scan.
build_inventory "$MODEL_ROOT" "$INVENTORY_B"
FILE_COUNT_B=$INVENTORY_FILE_COUNT
if [[ "$FILE_COUNT_A" != "$FILE_COUNT_B" ]] || ! cmp -s -- "$INVENTORY_A" "$INVENTORY_B"; then
  echo "REFUSING: checkpoint inventory changed between consecutive observations." >&2
  exit 10
fi
observe_service_gate "after_inventory"
observe_open_handle_gate "after_inventory"

printf 'Stable checkpoint inventory (%s files):\n' "$FILE_COUNT_A"
cat -- "$INVENTORY_A"
printf 'Planned atomic quarantine: %s -> %s\n' "$MODEL_ROOT" "$QUARANTINE_DEST"
printf 'Planned fresh checkpoint root mode: 0775\n'

if [[ "$APPLY" != true ]]; then
  if [[ "$READINESS_SAFE" == true ]]; then
    echo "APPLY READINESS: READY (apply was not requested)."
  else
    echo "APPLY READINESS: BLOCKED (service/open-handle gates are not all clear)."
  fi
  cat <<'DRYRUN'
DRY RUN ONLY: no repository, checkpoint, service, or Redis state was changed.
Re-run only after separately placing both named services into inactive/dead
state and reviewing the complete inventory above.
DRYRUN
  exit 0
fi

if [[ "$READINESS_SAFE" != true ]]; then
  echo "REFUSING: --apply requires both service gates and all open-handle scans to be clear." >&2
  exit 11
fi

TRANSACTION_RENAMED=false
FRESH_ROOT_CREATED=false
INVENTORY_INSTALLED=false
RECEIPT_INSTALLED=false
RESERVATION_CREATED=false

rollback_internal_failure() {
  local rc=$?
  local fresh_entry=""
  trap - ERR
  set +e
  echo "FAILED: quarantine transaction stopped with exit $rc." >&2

  if [[ "$FRESH_ROOT_CREATED" == true && -d "$MODEL_ROOT" ]]; then
    fresh_entry=$(find -P "$MODEL_ROOT" -mindepth 1 -print -quit)
    if [[ -z "$fresh_entry" ]]; then
      rmdir -- "$MODEL_ROOT"
      FRESH_ROOT_CREATED=false
    else
      echo "ROLLBACK NOT ATTEMPTED: fresh root is no longer empty: $MODEL_ROOT" >&2
    fi
  fi

  if [[ "$TRANSACTION_RENAMED" == true && ! -e "$MODEL_ROOT" && -d "$QUARANTINE_DEST" ]]; then
    if mv --no-copy -T -- "$QUARANTINE_DEST" "$MODEL_ROOT"; then
      TRANSACTION_RENAMED=false
      echo "Automatic rollback restored the original checkpoint root." >&2
    else
      echo "AUTOMATIC ROLLBACK FAILED; preserve both paths and escalate." >&2
    fi
  fi

  if [[ "$TRANSACTION_RENAMED" != true ]]; then
    [[ "$RECEIPT_INSTALLED" != true ]] || rm -f -- "$ACTIVE_RECEIPT"
    [[ "$INVENTORY_INSTALLED" != true ]] || rm -f -- "$INVENTORY_FINAL"
  fi
  [[ "$RESERVATION_CREATED" != true ]] || rmdir -- "$RESERVATION" 2>/dev/null
  exit "$rc"
}
trap rollback_internal_failure ERR

# This is the first persistent mutation. A directory reservation makes two
# concurrent invocations unable to target the same UTC destination.
install -d -m 0775 -- "$QUARANTINE_PARENT"
SOURCE_DEVICE=$(stat -c '%d' -- "$MODEL_ROOT")
DESTINATION_DEVICE=$(stat -c '%d' -- "$QUARANTINE_PARENT")
[[ "$SOURCE_DEVICE" == "$DESTINATION_DEVICE" ]] || {
  echo "REFUSING: source and quarantine parent are on different filesystems." >&2
  exit 12
}
mkdir -m 0700 -- "$RESERVATION"
RESERVATION_CREATED=true

# Recheck immediately before the rename. mv --no-copy makes a cross-device or
# otherwise non-rename fallback fail instead of copying and deleting the root.
READINESS_SAFE=true
observe_service_gate "pre_rename"
observe_open_handle_gate "pre_rename"
[[ "$READINESS_SAFE" == true ]] || {
  echo "REFUSING: a pre-rename safety gate changed after inventory." >&2
  exit 13
}
build_inventory "$MODEL_ROOT" "$INVENTORY_B"
[[ "$INVENTORY_FILE_COUNT" == "$FILE_COUNT_A" ]] && cmp -s -- "$INVENTORY_A" "$INVENTORY_B" || {
  echo "REFUSING: checkpoint inventory changed immediately before rename." >&2
  exit 13
}

mv --no-copy -T -- "$MODEL_ROOT" "$QUARANTINE_DEST"
TRANSACTION_RENAMED=true
rmdir -- "$RESERVATION"
RESERVATION_CREATED=false
sync -d -- "$QUARANTINE_PARENT"

build_inventory "$QUARANTINE_DEST" "$INVENTORY_C"
[[ "$INVENTORY_FILE_COUNT" == "$FILE_COUNT_A" ]] && cmp -s -- "$INVENTORY_A" "$INVENTORY_C" || {
  echo "ERROR: quarantined tree does not match the pre-rename inventory." >&2
  exit 14
}

INVENTORY_STAGE=$(mktemp "$QUARANTINE_PARENT/.legacy-inventory.XXXXXX")
install -m 0640 -- "$INVENTORY_A" "$INVENTORY_STAGE"
sync -d -- "$INVENTORY_STAGE"
mv --no-copy -T -- "$INVENTORY_STAGE" "$INVENTORY_FINAL"
INVENTORY_INSTALLED=true
sync -d -- "$QUARANTINE_PARENT"

install -d -m 0775 -- "$MODEL_ROOT"
FRESH_ROOT_CREATED=true
[[ "$(stat -c '%a' -- "$MODEL_ROOT")" == "775" ]] || {
  echo "ERROR: fresh checkpoint root does not have required mode 0775." >&2
  exit 15
}
[[ -z "$(find -P "$MODEL_ROOT" -mindepth 1 -print -quit)" ]] || {
  echo "ERROR: fresh checkpoint root is not empty." >&2
  exit 15
}
sync -d -- "$MODELS_PARENT"

INVENTORY_SHA256=$(sha256sum -- "$INVENTORY_FINAL")
INVENTORY_SHA256=${INVENTORY_SHA256%% *}
RECEIPT_STAGE=$(mktemp "$QUARANTINE_PARENT/.legacy-receipt.XXXXXX")
{
  printf 'schema=v2_native_trainer_legacy_checkpoint_quarantine_v1\n'
  printf 'applied_utc=%s\n' "$TIMESTAMP"
  printf 'source_root=%s\n' "$MODEL_ROOT"
  printf 'quarantine_root=%s\n' "$QUARANTINE_DEST"
  printf 'inventory_path=%s\n' "$INVENTORY_FINAL"
  printf 'inventory_sha256=%s\n' "$INVENTORY_SHA256"
  printf 'inventory_file_count=%s\n' "$FILE_COUNT_A"
  printf 'fresh_root_mode=0775\n'
  printf 'legacy_checkpoint_migration=NONE\n'
} >"$RECEIPT_STAGE"
chmod 0640 -- "$RECEIPT_STAGE"
sync -d -- "$RECEIPT_STAGE"
mv --no-copy -T -- "$RECEIPT_STAGE" "$ACTIVE_RECEIPT"
RECEIPT_INSTALLED=true
sync -d -- "$QUARANTINE_PARENT"

trap - ERR
TRANSACTION_RENAMED=false

printf 'Completed reversible whole-root legacy checkpoint quarantine.\n'
printf '  quarantined root: %s\n' "$QUARANTINE_DEST"
printf '  immutable-at-capture inventory: %s\n' "$INVENTORY_FINAL"
printf '  inventory SHA-256: %s\n' "$INVENTORY_SHA256"
printf '  fresh empty root: %s (mode 0775)\n' "$MODEL_ROOT"
printf 'No service, Redis key, or individual checkpoint was started, changed, migrated, or synthesized.\n'

printf '\nROLLBACK INSTRUCTIONS (printed only; never executed by this tool):\n'
printf '  1. Keep both services inactive and verify no open handles beneath either root.\n'
printf '  2. Verify the fresh root contains no new checkpoint data. Preserve it instead of deleting it if nonempty.\n'
printf '  3. If it is empty, run: rmdir -- %q\n' "$MODEL_ROOT"
printf '  4. Restore atomically on the same filesystem: mv --no-copy -T -- %q %q\n' \
  "$QUARANTINE_DEST" "$MODEL_ROOT"
printf '  5. Re-hash every restored file and compare it to: %q\n' "$INVENTORY_FINAL"
printf '  6. Remove the active receipt only after the restored inventory is verified: %q\n' "$ACTIVE_RECEIPT"
