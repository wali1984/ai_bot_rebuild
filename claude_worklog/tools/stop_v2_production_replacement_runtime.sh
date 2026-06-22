#!/usr/bin/env bash
# Stop the V2 production-replacement runtime cleanly (paper-only).
# Does NOT touch legacy. Does NOT modify exchange state.
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

UNITS=(
  ai-bot-v2-native-ingestors-live-loop.service
  ai-bot-v2-feature-pipeline-native-loop.service
  ai-bot-v2-rl-core-inference-loop.service
  ai-bot-v2-orchestrator-arbitration-loop.service
  ai-bot-v2-trade-management-paper-loop.service
  ai-bot-v2-production-replacement-runtime-guard.service
  ai-bot-v2-legacy-v2-production-comparator.service
  ai-bot-v2-liquidation-wss-paper-shadow.service
  ai-bot-v2-liquidation-levels-engine.service
  ai-bot-v2-coinapi-wsds-loop.service
)

if command -v systemctl >/dev/null 2>&1 && systemctl --user --version >/dev/null 2>&1; then
  for u in "${UNITS[@]}"; do
    systemctl --user stop "$u" >/dev/null 2>&1 || true
    systemctl --user disable "$u" >/dev/null 2>&1 || true
  done
fi

# Fallback: kill any nohup-launched loops by pattern.
PATTERNS=(
  v2.backend.app.cli.v2_native_ingestors_live_loop
  v2.backend.app.cli.v2_feature_pipeline_native_loop
  v2.backend.app.cli.v2_rl_core_inference_loop
  v2.backend.app.cli.v2_orchestrator_arbitration_loop
  v2.backend.app.cli.v2_trade_management_paper_loop
  v2.backend.app.cli.v2_production_payload_freshness_refresher
  v2.backend.app.cli.v2_production_replacement_soak_observer
  v2.backend.app.cli.v2_production_equivalence_comparator
  v2.backend.app.cli.v2_legacy_log_intelligence_observer
  v2.backend.app.cli.v2_liquidation_levels_engine
  v2.backend.app.cli.v2_coinapi_wsds_loop
  claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py
  claude_worklog/tools/v2_production_replacement_runtime_guard.py
  claude_worklog/tools/v2_legacy_v2_production_comparator.py
  v2.backend.app.cli.v2_liquidation_wss_loop
)
for p in "${PATTERNS[@]}"; do
  pids=$(pgrep -f "$p" || true)
  if [[ -n "$pids" ]]; then
    for pid in $pids; do
      kill -TERM "$pid" 2>/dev/null || true
    done
  fi
done
sleep 1
echo "stop_v2_production_replacement_runtime: complete"
