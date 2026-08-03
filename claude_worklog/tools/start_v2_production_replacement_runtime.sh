#!/usr/bin/env bash
# Start the V2 production-replacement runtime as persistent services.
# Paper-only. No exchange mutation. V2 namespace only.
#
# Strategy: prefer systemd --user; fall back to nohup launcher if systemd
# unit linking is not approved on this host.
set -e

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

UNIT_DIR="$REPO/claude_worklog/systemd/user"
USER_SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

UNITS=(
  ai-bot-v2-native-ingestors-live-loop.service
  ai-bot-v2-feature-pipeline-native-loop.service
  ai-bot-v2-rl-core-inference-loop.service
  ai-bot-v2-orchestrator-arbitration-loop.service
  ai-bot-v2-trade-management-paper-loop.service
  ai-bot-v2-production-payload-freshness-refresher.service
  ai-bot-v2-production-replacement-runtime-guard.service
  ai-bot-v2-legacy-v2-production-comparator.service
  ai-bot-v2-liquidation-wss-paper-shadow.service
  ai-bot-v2-liquidation-levels-engine.service
  ai-bot-v2-coinapi-wsds-loop.service
)

mode="auto"
if [[ "${1:-}" == "--systemd" ]]; then mode=systemd; fi
if [[ "${1:-}" == "--nohup" ]]; then mode=nohup; fi

start_via_systemd() {
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl --user --version >/dev/null 2>&1 || return 1
  mkdir -p "$USER_SYSTEMD_DIR"
  for u in "${UNITS[@]}"; do
    src="$UNIT_DIR/$u"
    dst="$USER_SYSTEMD_DIR/$u"
    if [[ ! -L "$dst" || "$(readlink -f "$dst")" != "$src" ]]; then
      ln -sf "$src" "$dst"
    fi
  done
  systemctl --user daemon-reload
  for u in "${UNITS[@]}"; do
    systemctl --user enable --now "$u" >/dev/null 2>&1 \
      || systemctl --user restart "$u" || true
  done
  return 0
}

start_via_nohup() {
  bash "$REPO/v2/backend/scripts/start_v2_production_loops.sh"
  for tool in v2_production_replacement_runtime_guard v2_legacy_v2_production_comparator; do
    if ! pgrep -f "claude_worklog/tools/${tool}.py" >/dev/null 2>&1; then
      mkdir -p "$REPO/claude_worklog/agent_supervisor/logs/control_plane"
      PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" \
        "$REPO/claude_worklog/tools/${tool}.py" --loop --interval-seconds 120 \
        >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/${tool}.log" 2>&1 &
      echo "${tool}_pid=$!"
    fi
  done
  # Payload freshness refresher (paper-only, V2 namespace only).
  if ! pgrep -f "v2.backend.app.cli.v2_production_payload_freshness_refresher" >/dev/null 2>&1; then
    mkdir -p "$REPO/claude_worklog/agent_supervisor/logs/control_plane"
    PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_production_payload_freshness_refresher --loop --interval-seconds 60 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/v2_production_payload_freshness_refresher.log" 2>&1 &
    echo "v2_production_payload_freshness_refresher_pid=$!"
  fi
  # Soak observer (5-min cycle by default).
  if ! pgrep -f "v2.backend.app.cli.v2_production_replacement_soak_observer" >/dev/null 2>&1; then
    PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_production_replacement_soak_observer --loop --interval-seconds 300 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/v2_production_replacement_soak_observer.log" 2>&1 &
    echo "v2_production_replacement_soak_observer_pid=$!"
  fi
  # Production equivalence comparator (read-only, paper-only).
  if ! pgrep -f "v2.backend.app.cli.v2_production_equivalence_comparator" >/dev/null 2>&1; then
    PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_production_equivalence_comparator --loop --interval-seconds 300 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/v2_production_equivalence_comparator.log" 2>&1 &
    echo "v2_production_equivalence_comparator_pid=$!"
  fi
  # Legacy log intelligence observer (read-only legacy logs/scripts).
  if ! pgrep -f "v2.backend.app.cli.v2_legacy_log_intelligence_observer" >/dev/null 2>&1; then
    PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_legacy_log_intelligence_observer --loop --interval-seconds 60 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/legacy_log_intelligence_observer.log" 2>&1 &
    echo "v2_legacy_log_intelligence_observer_pid=$!"
  fi
  # Binance forced-liquidation WSS stream (public, read-only, V2 namespace only).
  if ! pgrep -f "v2.backend.app.cli.v2_liquidation_wss_loop" >/dev/null 2>&1; then
    mkdir -p "$REPO/claude_worklog/agent_supervisor/logs/control_plane"
    V2_LIQUIDATION_WSS_OPT_IN=true PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_liquidation_wss_loop --total-seconds 86400 --max-seconds-per-session 600 --max-events-per-session 1000 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/v2_liquidation_wss_loop.log" 2>&1 &
    echo "v2_liquidation_wss_loop_pid=$!"
  fi
  # Liquidation level engine consumes v2:liquidations:events and publishes all configured TFs.
  if ! pgrep -f "v2.backend.app.cli.v2_liquidation_levels_engine" >/dev/null 2>&1; then
    mkdir -p "$REPO/claude_worklog/agent_supervisor/logs/control_plane"
    PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_liquidation_levels_engine --timeframes 1m,5m,15m,1h,4h --ttl-seconds 900 --publish-heartbeat-sec 60 --symbol-refresh-sec 60 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/v2_liquidation_levels_engine.log" 2>&1 &
    echo "v2_liquidation_levels_engine_pid=$!"
  fi
  # CoinAPI WSDS read-only stream. The worker remains supervised and emits a blocked
  # status if the key/opt-in are missing; it never writes legacy msnap/metrics keys.
  if ! pgrep -f "v2.backend.app.cli.v2_coinapi_wsds_loop" >/dev/null 2>&1; then
    mkdir -p "$REPO/claude_worklog/agent_supervisor/logs/control_plane"
    V2_COINAPI_WSDS_OPT_IN=true PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" -m \
      v2.backend.app.cli.v2_coinapi_wsds_loop --loop --total-seconds 86400 --max-seconds-per-session 600 --max-messages-per-session 5000 --ttl-seconds 300 --heartbeat-interval-seconds 30 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-coinapi-wsds-loop.log" 2>&1 &
    echo "v2_coinapi_wsds_loop_pid=$!"
  fi
  # Continuous legacy-log -> rebuild remediation loop (narrow Claude+Codex tasks).
  if ! pgrep -f "v2_continuous_legacy_log_to_rebuild_remediation.py" >/dev/null 2>&1; then
    PYTHONPATH="$REPO" nohup "$REPO/.venv/bin/python3" \
      "$REPO/claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py" --loop --interval-seconds 300 \
      >> "$REPO/claude_worklog/agent_supervisor/logs/control_plane/v2_continuous_legacy_log_remediation.log" 2>&1 &
    echo "v2_continuous_legacy_log_remediation_pid=$!"
  fi
}

case "$mode" in
  systemd)
    start_via_systemd || { echo "systemd start failed; aborting"; exit 1; }
    ;;
  nohup)
    start_via_nohup
    ;;
  auto)
    if ! start_via_systemd; then
      echo "systemd --user not available; falling back to nohup"
      start_via_nohup
    fi
    ;;
esac
echo "V2 production replacement runtime start sequence complete."
