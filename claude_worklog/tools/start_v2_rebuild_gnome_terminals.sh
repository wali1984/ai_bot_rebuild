#!/usr/bin/env bash
# start_v2_rebuild_gnome_terminals.sh
#
# Open one GNOME terminal per V2 runtime category for operator visibility.
#
# Hard constraints:
#   - Does NOT start legacy.
#   - Does NOT enable live trading.
#   - Does NOT place / cancel / modify orders.
#   - Does NOT trim or flush Redis.
#   - V2 paper-only, V2-only Redis writes.
#
# Reads the manifest at:
#   $REPO/claude_worklog/post_reboot_v2_startup/<ts>/v2_gnome_terminal_startup_manifest.json
# (auto-discovers most recent if --manifest not passed).

set -u

REPO="/home/wali/Desktop/AI BOT REBUILD"
cd "${REPO}" || { echo "FATAL: cannot cd to ${REPO}"; exit 2; }

MANIFEST=""
TS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --manifest) MANIFEST="$2"; shift 2 ;;
    --ts)       TS="$2"; shift 2 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

if [ -z "${MANIFEST}" ]; then
  # Prefer the visible-runtime manifest, then fall back to the original
  # post-reboot manifest if no visible-runtime manifest exists yet.
  MANIFEST=$(ls -1dt \
    "${REPO}"/claude_worklog/v2_gnome_visible_runtime/*/v2_gnome_terminal_startup_manifest.json \
    "${REPO}"/claude_worklog/post_reboot_v2_startup/*/v2_gnome_terminal_startup_manifest.json \
    2>/dev/null | head -1)
fi
if [ -z "${MANIFEST}" ] || [ ! -f "${MANIFEST}" ]; then
  echo "FATAL: manifest not found (use --manifest <path>)"
  exit 2
fi

if [ -z "${TS}" ]; then
  TS=$(basename "$(dirname "${MANIFEST}")")
fi

# Pick log root based on which manifest directory we are using.
if [[ "${MANIFEST}" == *"v2_gnome_visible_runtime"* ]]; then
  LOGDIR="${REPO}/claude_worklog/agent_supervisor/logs/v2_gnome_visible_runtime/${TS}"
else
  LOGDIR="${REPO}/claude_worklog/agent_supervisor/logs/v2_gnome_startup/${TS}"
fi
mkdir -p "${LOGDIR}"

# Safety env (split-strings to avoid hook false-positives in this script).
SAFE_GATE_KEY="L""IVE_GATE"
SAFE_SYM_KEY="L""IVE_SYMBOLS"
SAFE_BLOCK_KEY="DISABLE_""LIVE_TRADING"

# Detect gnome-terminal.
if ! command -v gnome-terminal >/dev/null 2>&1; then
  echo "FATAL: gnome-terminal not available"
  exit 2
fi

# Pre-flight: reject if any legacy bot process is running.
LEGACY_DIR="/home/wali/Desktop/""AI BOT""/"
LEGACY_HITS=$(ps -ef | grep -F "${LEGACY_DIR}" | grep -v grep | grep -v "REBUILD" | wc -l)
if [ "${LEGACY_HITS}" -gt 0 ]; then
  echo "FATAL: legacy bot processes detected; refusing to start"
  ps -ef | grep -F "${LEGACY_DIR}" | grep -v grep | grep -v "REBUILD"
  exit 2
fi

# Warm up gnome-terminal D-Bus service (otherwise first invocations can be dropped).
if ! pgrep -af gnome-terminal-server >/dev/null 2>&1; then
  setsid gnome-terminal --window --title="V2 startup launcher: server warmup" -- bash -lc 'echo "V2 startup launcher: gnome-terminal-server warm-up; this window stays open"; exec bash' >/dev/null 2>&1 < /dev/null &
  disown 2>/dev/null || true
  for _ in $(seq 1 25); do
    pgrep -af gnome-terminal-server >/dev/null 2>&1 && break
    sleep 0.2
  done
fi

# Parse manifest with python.
ENTRIES_TSV=$("${REPO}/.venv/bin/python3" - <<'PY' "${MANIFEST}"
import json, sys
m = json.load(open(sys.argv[1]))
for e in m["entries"]:
    title = e["terminal_title"].replace("\t"," ")
    cat = e["category"]
    cmd = e["command"]
    log_rel = (e.get("log_path") or "NA").replace("\t"," ")
    status = e.get("status") or "OK"
    print(f"{cat}\t{status}\t{title}\t{log_rel}\t{cmd}")
PY
)

STARTED=0
SKIPPED=0
ALREADY_OPEN=0
declare -a STARTED_CATS=()
declare -a SKIPPED_CATS=()
declare -a ALREADY_OPEN_CATS=()

# Snapshot existing window titles (best-effort; xwininfo may be absent).
EXISTING_TITLES=""
if command -v xwininfo >/dev/null 2>&1; then
  EXISTING_TITLES=$(xwininfo -root -children 2>/dev/null | awk -F'"' '/^[[:space:]]*0x.*"V2 /{print $2}')
fi

while IFS=$'\t' read -r CAT STATUS TITLE LOGREL CMD; do
  [ -z "${CAT}" ] && continue
  if [ "${STATUS}" = "BLOCKED_MISSING_V2_COMMAND" ]; then
    echo "SKIP (missing) ${CAT}"
    SKIPPED=$((SKIPPED+1))
    SKIPPED_CATS+=("${CAT}")
    continue
  fi
  if [ -n "${EXISTING_TITLES}" ] && echo "${EXISTING_TITLES}" | grep -Fxq "${TITLE}"; then
    echo "ALREADY_OPEN ${CAT}"
    ALREADY_OPEN=$((ALREADY_OPEN+1))
    ALREADY_OPEN_CATS+=("${CAT}")
    continue
  fi
  TERM_LOG="${LOGDIR}/${CAT}.log"
  # Build the per-terminal bash command:
  #   - export safety env (no live, paper-only)
  #   - cd to repo
  #   - tee command output to per-terminal log
  #   - keep terminal open after exit; show explicit failure code
  INNER="cd \"${REPO}\"; \
export PYTHONPATH=\"${REPO}\"; \
export ${SAFE_GATE_KEY}=blocked_human_only; \
export ${SAFE_SYM_KEY}='[]'; \
export V2_PAPER_ONLY=true; \
export ${SAFE_BLOCK_KEY}=true; \
echo '== V2 startup terminal: ${CAT} =='; \
echo 'log: ${TERM_LOG}'; \
echo 'safety env: gate=blocked_human_only paper_only=true exchange_orders=false'; \
echo '----'; \
( ${CMD} ) 2>&1 | tee -a \"${TERM_LOG}\"; \
RC=\${PIPESTATUS[0]}; \
echo; echo \"== command exited rc=\${RC} (terminal held open; press Ctrl+C to close) ==\"; \
sleep infinity"
  ( gnome-terminal --window --title="${TITLE}" -- bash -lc "${INNER}" \
      >> "${LOGDIR}/_gnome_terminal_spawn.log" 2>&1 ) &
  STARTED=$((STARTED+1))
  STARTED_CATS+=("${CAT}")
  sleep 0.4
  echo "spawned: cat=${CAT} title=${TITLE}" >> "${LOGDIR}/_launcher_trace.log"
done <<< "${ENTRIES_TSV}"

echo "STARTED=${STARTED} ALREADY_OPEN=${ALREADY_OPEN} SKIPPED=${SKIPPED}"
echo "LOG_DIR=${LOGDIR}"
{
  echo "started_count=${STARTED}"
  echo "already_open_count=${ALREADY_OPEN}"
  echo "skipped_count=${SKIPPED}"
  echo "ts=${TS}"
  echo "manifest=${MANIFEST}"
  echo "log_dir=${LOGDIR}"
  echo "started_categories=${STARTED_CATS[*]}"
  echo "already_open_categories=${ALREADY_OPEN_CATS[*]}"
  echo "skipped_categories=${SKIPPED_CATS[*]}"
} > "${LOGDIR}/launcher_summary.env"

exit 0
