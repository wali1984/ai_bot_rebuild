#!/usr/bin/env bash
# Prepare bounded journald/rsyslog policy without deleting logs or restarting
# services. Default mode is a read-only plan. Apply requires explicit operator
# acknowledgement and still leaves activation/rotation as separate manual steps.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage:
  tools/OPERATOR_crash_hardening_sudo.sh
  sudo tools/OPERATOR_crash_hardening_sudo.sh --apply --ack-log-policy-change

Default: metadata-only dry-run.

--apply                  Install validated configuration changes.
--ack-log-policy-change  Acknowledge that rate limiting can suppress repetitive
                         diagnostics and log retention policy will change.

Environment overrides for the operator-reviewed policy:
  JOURNAL_RUNTIME_MAX_USE   default 200M
  JOURNAL_RUNTIME_FILE_SIZE default 50M
  JOURNAL_RATE_INTERVAL     default 30s
  JOURNAL_RATE_BURST        default 2000
  SYSLOG_MAX_SIZE           default 1G
  SYSLOG_ROTATE_COUNT       default 7

The script never truncates a log, never forces rotation, and never restarts or
reloads a service. It prints those separately authorized operator steps.
USAGE
}

APPLY=false
ACK_LOG_POLICY_CHANGE=false

while (($#)); do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --ack-log-policy-change)
      ACK_LOG_POLICY_CHANGE=true
      shift
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

JOURNAL_RUNTIME_MAX_USE=${JOURNAL_RUNTIME_MAX_USE:-200M}
JOURNAL_RUNTIME_FILE_SIZE=${JOURNAL_RUNTIME_FILE_SIZE:-50M}
JOURNAL_RATE_INTERVAL=${JOURNAL_RATE_INTERVAL:-30s}
JOURNAL_RATE_BURST=${JOURNAL_RATE_BURST:-2000}
SYSLOG_MAX_SIZE=${SYSLOG_MAX_SIZE:-1G}
SYSLOG_ROTATE_COUNT=${SYSLOG_ROTATE_COUNT:-7}

byte_size_re='^[1-9][0-9]*[KMGTP]?$'
duration_re='^[1-9][0-9]*(us|ms|s|min|h|d|w)?$'
[[ "$JOURNAL_RUNTIME_MAX_USE" =~ $byte_size_re ]] || {
  echo "ERROR: invalid JOURNAL_RUNTIME_MAX_USE=$JOURNAL_RUNTIME_MAX_USE" >&2
  exit 65
}
[[ "$JOURNAL_RUNTIME_FILE_SIZE" =~ $byte_size_re ]] || {
  echo "ERROR: invalid JOURNAL_RUNTIME_FILE_SIZE=$JOURNAL_RUNTIME_FILE_SIZE" >&2
  exit 65
}
[[ "$JOURNAL_RATE_INTERVAL" =~ $duration_re ]] || {
  echo "ERROR: invalid JOURNAL_RATE_INTERVAL=$JOURNAL_RATE_INTERVAL" >&2
  exit 65
}
[[ "$JOURNAL_RATE_BURST" =~ ^[1-9][0-9]*$ ]] || {
  echo "ERROR: invalid JOURNAL_RATE_BURST=$JOURNAL_RATE_BURST" >&2
  exit 65
}
[[ "$SYSLOG_MAX_SIZE" =~ ^[1-9][0-9]*[kMGT]?$ ]] || {
  echo "ERROR: invalid SYSLOG_MAX_SIZE=$SYSLOG_MAX_SIZE" >&2
  exit 65
}
[[ "$SYSLOG_ROTATE_COUNT" =~ ^[1-9][0-9]*$ ]] || {
  echo "ERROR: invalid SYSLOG_ROTATE_COUNT=$SYSLOG_ROTATE_COUNT" >&2
  exit 65
}

SYSLOG_BYTES=0
[[ -e /var/log/syslog ]] && SYSLOG_BYTES=$(stat -c %s -- /var/log/syslog)
printf 'Crash-hardening metadata (no log contents read):\n'
printf '  /var/log/syslog bytes: %s\n' "$SYSLOG_BYTES"
if command -v journalctl >/dev/null 2>&1; then
  journalctl --disk-usage 2>/dev/null || true
fi
printf 'Proposed journald runtime cap: %s (file %s, %s/%s burst)\n' \
  "$JOURNAL_RUNTIME_MAX_USE" "$JOURNAL_RUNTIME_FILE_SIZE" \
  "$JOURNAL_RATE_BURST" "$JOURNAL_RATE_INTERVAL"
printf 'Proposed rsyslog rotation: daily, maxsize %s, retain %s rotations\n' \
  "$SYSLOG_MAX_SIZE" "$SYSLOG_ROTATE_COUNT"

if [[ "$APPLY" != true ]]; then
  cat <<'DRYRUN'
DRY RUN ONLY: no configuration or logs were changed.
Apply installs validated policy files only. It does not reclaim existing logs,
restart journald, reload rsyslog, force logrotate, or delete any archive.
DRYRUN
  exit 0
fi

((EUID == 0)) || {
  echo "REFUSING: --apply must be run as root (normally through sudo)." >&2
  exit 2
}
[[ "$ACK_LOG_POLICY_CHANGE" == true ]] || {
  echo "REFUSING: --apply also requires --ack-log-policy-change." >&2
  exit 3
}

for command in awk cmp cp date install logrotate mktemp mv systemd-analyze; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "REFUSING: required command is unavailable: $command" >&2
    exit 4
  }
done

RSYSLOG_CONFIG=/etc/logrotate.d/rsyslog
JOURNAL_DROPIN_DIR=/etc/systemd/journald.conf.d
JOURNAL_DROPIN=$JOURNAL_DROPIN_DIR/99-ai-bot-crash-hardening.conf
[[ -f "$RSYSLOG_CONFIG" ]] || {
  echo "REFUSING: expected rsyslog logrotate policy is missing: $RSYSLOG_CONFIG" >&2
  exit 5
}

WORK_DIR=$(mktemp -d /tmp/ai-bot-crash-hardening.XXXXXX)
cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

JOURNAL_CANDIDATE=$WORK_DIR/journald.conf
RSYSLOG_CANDIDATE=$WORK_DIR/rsyslog
printf '%s\n' \
  '[Journal]' \
  "RuntimeMaxUse=$JOURNAL_RUNTIME_MAX_USE" \
  "RuntimeMaxFileSize=$JOURNAL_RUNTIME_FILE_SIZE" \
  "RateLimitIntervalSec=$JOURNAL_RATE_INTERVAL" \
  "RateLimitBurst=$JOURNAL_RATE_BURST" \
  >"$JOURNAL_CANDIDATE"

# Preserve every unrecognized distro/operator directive. Replace only the first
# frequency/rotate/maxsize directive in the existing rsyslog stanza, inserting
# maxsize before its closing brace when the distro policy lacks one.
awk \
  -v rotate_count="$SYSLOG_ROTATE_COUNT" \
  -v max_size="$SYSLOG_MAX_SIZE" \
  '
  BEGIN { frequency_seen = 0; rotate_seen = 0; maxsize_seen = 0 }
  $1 ~ /^(hourly|daily|weekly|monthly|yearly)$/ && frequency_seen == 0 {
    print "\tdaily"
    frequency_seen = 1
    next
  }
  $1 == "rotate" && rotate_seen == 0 {
    print "\trotate " rotate_count
    rotate_seen = 1
    next
  }
  $1 == "maxsize" && maxsize_seen == 0 {
    print "\tmaxsize " max_size
    maxsize_seen = 1
    next
  }
  /^[[:space:]]*}[[:space:]]*$/ && maxsize_seen == 0 {
    print "\tmaxsize " max_size
    maxsize_seen = 1
  }
  { print }
  END {
    if (frequency_seen != 1 || rotate_seen != 1 || maxsize_seen != 1) {
      exit 42
    }
  }
  ' "$RSYSLOG_CONFIG" >"$RSYSLOG_CANDIDATE" || {
    echo "REFUSING: rsyslog policy shape was not recognized; nothing installed." >&2
    exit 6
  }

# Parse the candidate without rotating files or updating logrotate state.
logrotate --debug "$RSYSLOG_CANDIDATE" >/dev/null

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=/var/backups/ai-bot-crash-hardening/$TIMESTAMP
mkdir -m 0700 -p -- "$BACKUP_DIR"
cp -a -- "$RSYSLOG_CONFIG" "$BACKUP_DIR/rsyslog.before"
if [[ -e "$JOURNAL_DROPIN" ]]; then
  cp -a -- "$JOURNAL_DROPIN" "$BACKUP_DIR/journald-dropin.before"
fi

install_atomic_if_changed() {
  local candidate=$1
  local target=$2
  local target_dir
  local staged
  target_dir=$(dirname -- "$target")
  mkdir -p -- "$target_dir"
  if [[ -e "$target" ]] && cmp -s -- "$candidate" "$target"; then
    printf 'Unchanged: %s\n' "$target"
    return 0
  fi
  staged="$target_dir/.${target##*/}.$$.tmp"
  install -m 0644 -- "$candidate" "$staged"
  mv -f -- "$staged" "$target"
  printf 'Installed: %s\n' "$target"
}

install_atomic_if_changed "$JOURNAL_CANDIDATE" "$JOURNAL_DROPIN"
install_atomic_if_changed "$RSYSLOG_CANDIDATE" "$RSYSLOG_CONFIG"
systemd-analyze cat-config systemd/journald.conf >/dev/null

cat <<EOF
Policy installation complete; existing logs were not changed.
Backup directory: $BACKUP_DIR

SEPARATE OPERATOR-ONLY ACTIVATION (not run by this script):
  1. Review: systemd-analyze cat-config systemd/journald.conf
  2. Activate journald policy in an approved window:
       sudo systemctl restart systemd-journald
  3. Validate rsyslog rotation without mutation:
       sudo logrotate --debug /etc/logrotate.d/rsyslog
  4. If immediate rotation is separately approved, ensure ample temporary disk
     and then run: sudo logrotate --force /etc/logrotate.d/rsyslog

Do not truncate /var/log/syslog. Forced compression of a very large archive can
consume substantial CPU, disk I/O, and temporary space.
EOF
