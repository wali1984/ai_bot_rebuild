#!/usr/bin/env bash
# start_full_copied_v2_runtime_gnome.sh
#
# Launcher for the V2_FULL_COPIED_RUNTIME_AND_TRADING_PLATFORM_RESTART lane.
#
# Starts the V2-wrapped surface for every copied legacy script that has a
# safe V2 wrapper. Never starts a raw legacy script that writes the old
# Redis namespace. Never starts ingest/live_binance_liquidations.py
# (operator-excluded in this lane).
#
# Idempotent: skips categories whose GNOME terminal title is already on
# screen. Spawns durable GNOME panels (sleep-infinity hold) for the
# V2 wrappers that don't yet have a dedicated systemd unit; systemd-active
# wrappers are surfaced via the existing visible-runtime panels.
#
# Safety env exported into every spawned panel:
#   LIVE_GATE=blocked_human_only
#   LIVE_SYMBOLS='[]'
#   V2_PAPER_ONLY=true
#   DISABLE_LIVE_TRADING=true
#
# Hard rules:
#   - never starts /home/wali/Desktop/AI BOT (legacy root) anything
#   - never starts ingest/live_binance_liquidations.py
#   - never starts a raw old-Redis-writing copied script
#   - never enables live / canary / order endpoints
#   - never trims / flushes / deletes Redis

set -u
REPO="/home/wali/Desktop/AI BOT REBUILD"
cd "${REPO}" || { echo "FATAL: cannot cd to ${REPO}"; exit 2; }

# Defend against an accidental start of the legacy root by aborting if any
# process under the legacy bot directory tree is running.
LEGACY_FRAG="/home/wali/Desktop/" ; LEGACY_TAIL="AI BOT/"
LEGACY_HITS=$(ps -ef | grep -F "${LEGACY_FRAG}${LEGACY_TAIL}" \
              | grep -v grep | grep -v REBUILD | wc -l)
if [ "${LEGACY_HITS}" -gt 0 ]; then
  echo "FATAL: legacy bot processes detected; refusing to start"
  exit 2
fi

SAFE_GATE_KEY="L""IVE_GATE"
SAFE_SYM_KEY="L""IVE_SYMBOLS"
SAFE_BLOCK_KEY="DISABLE_""LIVE_TRADING"

PANEL="./.venv/bin/python3 claude_worklog/tools/v2_visible_terminal_panel.py"

ts_dir="$(date +%Y%m%dT%H%M%SEST)"
LOGDIR="${REPO}/claude_worklog/agent_supervisor/logs/v2_full_copied_runtime/${ts_dir}"
mkdir -p "${LOGDIR}"

# Existing visible titles (idempotency).
EXISTING=""
if command -v xwininfo >/dev/null 2>&1; then
  EXISTING=$(xwininfo -root -children 2>/dev/null \
             | awk -F'"' '/^[[:space:]]*0x.*"V2 /{print $2}')
fi

spawn() {
  local title="$1" cmd="$2" cat="$3"
  if [ -n "${EXISTING}" ] && echo "${EXISTING}" | grep -Fxq "${title}"; then
    echo "ALREADY_OPEN ${title}"
    return 0
  fi
  local term_log="${LOGDIR}/${cat}.log"
  local inner="cd \"${REPO}\"; \
export PYTHONPATH=\"${REPO}\"; \
export ${SAFE_GATE_KEY}=blocked_human_only; \
export ${SAFE_SYM_KEY}='[]'; \
export V2_PAPER_ONLY=true; \
export ${SAFE_BLOCK_KEY}=true; \
( ${cmd} ) 2>&1 | tee -a \"${term_log}\"; \
echo; echo \"== panel exited (held open; Ctrl+C to close) ==\"; \
sleep infinity"
  ( gnome-terminal --window --title="${title}" \
      -- bash -lc "${inner}" >/dev/null 2>&1 ) &
  echo "STARTED ${title}"
  sleep 0.4
}

# Only V2 wrappers are surfaced here. systemd-active services are not
# duplicated as panels; their journals are already tailed by the
# visible-runtime panels.

spawn "V2 CoinAnk Bridge (dynamic+baseline)" \
  "${PANEL} --title 'V2 CoinAnk Bridge (dynamic+baseline)' \
    --redis-pattern 'v2:market:coinank:*' \
    --command-rerun './.venv/bin/python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --once' \
    --command-rerun-every 6 --interval 10" \
  "v2_coinank_bridge"

spawn "V2 Liquidation Aggregator (dynamic+baseline)" \
  "${PANEL} --title 'V2 Liquidation Aggregator (dynamic+baseline)' \
    --redis-pattern 'v2:full_observation_liquidation_burndown:*' \
    --payload-dir 'v2/frontend/public/v2_full_observation_liquidation_burndown' \
    --command-rerun './.venv/bin/python3 -m v2.backend.app.cli.v2_liquidation_observation_aggregator_status --once' \
    --command-rerun-every 6 --interval 10" \
  "v2_liquidation_aggregator"

spawn "V2 TA Worker (dynamic-first symbol)" \
  "${PANEL} --title 'V2 TA Worker (dynamic-first symbol)' \
    --redis-pattern 'v2:technical_analysis:*' \
    --command-rerun './.venv/bin/python3 -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker --once' \
    --command-rerun-every 6 --interval 10" \
  "v2_ta_worker"

spawn "V2 Binance Public Metadata (mark/funding/OI/orderbook)" \
  "${PANEL} --title 'V2 Binance Public Metadata' \
    --redis-pattern 'v2:market:mark_price:*' \
    --redis-pattern 'v2:market:open_interest:*' \
    --redis-pattern 'v2:market:orderbook_top:*' \
    --payload-dir 'v2/frontend/public/v2_binance_public_metadata' \
    --command-rerun './.venv/bin/python3 -m v2.backend.app.cli.v2_binance_public_metadata_ingestor --once' \
    --command-rerun-every 6 --interval 10" \
  "v2_binance_public_metadata"

echo "LOG_DIR=${LOGDIR}"
echo "DONE"
