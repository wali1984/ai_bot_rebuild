#!/usr/bin/env bash
# Reclaim Cursor AI-history state only after an explicit, reversible operator
# workflow. The default mode is metadata-only dry-run; it never changes Cursor.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage:
  tools/fix_cursor_state_bloat.sh [--db PATH]
  tools/fix_cursor_state_bloat.sh --apply --ack-delete-chat-history [--db PATH]

Default: metadata-only dry-run.

--apply                    Permit the maintenance transaction.
--ack-delete-chat-history  Acknowledge that Cursor AI/composer history is deleted
                           from the active database after a full backup succeeds.
--db PATH                  Override the Cursor state database path (testing or a
                           non-default Cursor profile).

Cursor must be fully closed. The apply path refuses to run if Cursor is active
or any process still has the database, WAL, or SHM file open.
USAGE
}

APPLY=false
ACK_DELETE_CHAT_HISTORY=false
CONFIG_ROOT="${XDG_CONFIG_HOME:-${HOME:?HOME is required}/.config}"
DB="${CURSOR_STATE_DB:-$CONFIG_ROOT/Cursor/User/globalStorage/state.vscdb}"

while (($#)); do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --ack-delete-chat-history)
      ACK_DELETE_CHAT_HISTORY=true
      shift
      ;;
    --db)
      (($# >= 2)) || { echo "ERROR: --db requires a path" >&2; exit 64; }
      DB=$2
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

[[ -f "$DB" ]] || { echo "ERROR: no state database at: $DB" >&2; exit 1; }
DB_DIR=$(dirname -- "$DB")
WAL="$DB-wal"
SHM="$DB-shm"

file_bytes() {
  local path=$1
  if [[ -e "$path" ]]; then
    stat -c %s -- "$path"
  else
    printf '0\n'
  fi
}

DB_BYTES=$(file_bytes "$DB")
WAL_BYTES=$(file_bytes "$WAL")
SHM_BYTES=$(file_bytes "$SHM")
TOTAL_BYTES=$((DB_BYTES + WAL_BYTES + SHM_BYTES))

printf 'Cursor state metadata (no database rows read):\n'
printf '  database: %s bytes\n' "$DB_BYTES"
printf '  WAL:      %s bytes\n' "$WAL_BYTES"
printf '  SHM:      %s bytes\n' "$SHM_BYTES"
printf '  combined: %s bytes\n' "$TOTAL_BYTES"
printf '  path:     %s\n' "$DB"

if [[ "$APPLY" != true ]]; then
  cat <<'DRYRUN'
DRY RUN ONLY: no files were changed.
Apply requires both --apply and --ack-delete-chat-history, a fully closed
Cursor process tree, no open database handles, and enough free space for a full
SQLite backup plus VACUUM working space.
DRYRUN
  exit 0
fi

[[ "$ACK_DELETE_CHAT_HISTORY" == true ]] || {
  echo "REFUSING: --apply also requires --ack-delete-chat-history" >&2
  exit 2
}

for command in sqlite3 fuser pgrep stat df awk date; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "REFUSING: required command is unavailable: $command" >&2
    exit 3
  }
done

if pgrep -ix cursor >/dev/null 2>&1; then
  echo "REFUSING: Cursor is still running. Use File > Quit and verify it exited." >&2
  exit 4
fi

open_files=("$DB")
[[ -e "$WAL" ]] && open_files+=("$WAL")
[[ -e "$SHM" ]] && open_files+=("$SHM")
if fuser "${open_files[@]}" >/dev/null 2>&1; then
  echo "REFUSING: a process still has Cursor state files open." >&2
  exit 5
fi

AVAILABLE_BYTES=$(df -Pk -- "$DB_DIR" | awk 'NR == 2 {printf "%.0f\n", $4 * 1024}')
# A consistent backup and SQLite VACUUM may each require roughly one logical
# database copy. Include the current WAL again as conservative recovery room.
REQUIRED_BYTES=$((DB_BYTES * 3 + WAL_BYTES * 2))
if ((AVAILABLE_BYTES < REQUIRED_BYTES)); then
  printf 'REFUSING: free bytes=%s; conservative required bytes=%s\n' \
    "$AVAILABLE_BYTES" "$REQUIRED_BYTES" >&2
  exit 6
fi

REQUIRED_TABLE_COUNT=$(sqlite3 -readonly "$DB" <<'SQL'
SELECT COUNT(*)
FROM sqlite_master
WHERE type = 'table'
  AND name IN ('ItemTable', 'cursorDiskKV', 'composerHeaders');
SQL
)
[[ "$REQUIRED_TABLE_COUNT" == "3" ]] || {
  echo "REFUSING: expected Cursor tables are missing; this Cursor schema is unsupported." >&2
  exit 7
}

HAS_TARGET_ROWS=$(sqlite3 -readonly "$DB" <<'SQL'
SELECT CASE
  WHEN EXISTS(SELECT 1 FROM cursorDiskKV LIMIT 1)
    OR EXISTS(SELECT 1 FROM composerHeaders LIMIT 1)
  THEN 1 ELSE 0 END;
SQL
)
FREE_PAGES=$(sqlite3 -readonly "$DB" 'PRAGMA freelist_count;')
if [[ "$HAS_TARGET_ROWS" == "0" && "$FREE_PAGES" == "0" ]]; then
  echo "Already clean: target history tables are empty and no free pages need compaction."
  exit 0
fi

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$DB_DIR/cursor-state-backup-$TIMESTAMP"
BACKUP_DB="$BACKUP_DIR/state.vscdb.full.sqlite"
ITEMTABLE_DUMP="$BACKUP_DIR/ItemTable.sql"
mkdir -m 0700 -- "$BACKUP_DIR"

case "$BACKUP_DB" in
  *"'"*|*'"'*|*$'\n'*)
    echo "REFUSING: backup path contains unsupported quoting characters." >&2
    exit 8
    ;;
esac

BACKUP_READY=false
on_error() {
  local rc=$?
  echo "FAILED: Cursor maintenance stopped with exit $rc." >&2
  if [[ "$BACKUP_READY" == true ]]; then
    echo "A validated full rollback database is preserved at: $BACKUP_DB" >&2
  else
    echo "No validated rollback backup was completed; the purge was not started." >&2
  fi
  exit "$rc"
}
trap on_error ERR

# Cursor is closed, so fold committed WAL pages into the main database first.
sqlite3 "$DB" <<'SQL' >/dev/null
.bail on
PRAGMA busy_timeout=15000;
PRAGMA wal_checkpoint(TRUNCATE);
SQL

# SQLite's backup API creates one consistent full copy containing settings and
# all history. This is the rollback artifact; ItemTable.sql is supplemental.
sqlite3 "$DB" ".backup '$BACKUP_DB'"
BACKUP_CHECK=$(sqlite3 -readonly "$BACKUP_DB" 'PRAGMA quick_check;')
[[ "$BACKUP_CHECK" == "ok" ]] || {
  echo "ERROR: full backup failed SQLite quick_check." >&2
  exit 9
}
sqlite3 -readonly "$DB" '.dump ItemTable' >"$ITEMTABLE_DUMP.tmp"
[[ -s "$ITEMTABLE_DUMP.tmp" ]] || {
  echo "ERROR: ItemTable supplemental dump is empty." >&2
  exit 10
}
mv -- "$ITEMTABLE_DUMP.tmp" "$ITEMTABLE_DUMP"
chmod 0600 -- "$BACKUP_DB" "$ITEMTABLE_DUMP"
BACKUP_READY=true

cat >"$BACKUP_DIR/README.txt" <<EOF
Created: $TIMESTAMP
Source: $DB
Purpose: full rollback copy made before deleting Cursor AI/composer history.
Validation: SQLite quick_check returned ok before active-database purge.
Keep this directory private; the database and ItemTable dump may contain
sensitive Cursor state.
EOF
chmod 0600 -- "$BACKUP_DIR/README.txt"

# Both deletes either commit together or roll back together. VACUUM starts only
# after the validated full backup exists and the transaction commits.
sqlite3 "$DB" <<'SQL' >/dev/null
.bail on
PRAGMA busy_timeout=15000;
BEGIN IMMEDIATE;
DELETE FROM cursorDiskKV;
DELETE FROM composerHeaders;
COMMIT;
PRAGMA wal_checkpoint(TRUNCATE);
VACUUM;
PRAGMA wal_checkpoint(TRUNCATE);
SQL

ACTIVE_CHECK=$(sqlite3 -readonly "$DB" 'PRAGMA quick_check;')
[[ "$ACTIVE_CHECK" == "ok" ]] || {
  echo "ERROR: compacted active database failed SQLite quick_check." >&2
  exit 11
}

AFTER_BYTES=$(( $(file_bytes "$DB") + $(file_bytes "$WAL") + $(file_bytes "$SHM") ))
printf 'Completed Cursor state maintenance.\n'
printf '  before combined bytes: %s\n' "$TOTAL_BYTES"
printf '  after combined bytes:  %s\n' "$AFTER_BYTES"
printf '  validated rollback:    %s\n' "$BACKUP_DB"
printf 'Cursor was not started; reopen it manually after reviewing this result.\n'
