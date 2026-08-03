#!/usr/bin/env bash
# Status of V2 production-replacement runtime processes + Redis namespaces.
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

PATTERNS=(
  v2_native_ingestors_live_loop
  v2_feature_pipeline_native_loop
  v2_rl_core_inference_loop
  v2_orchestrator_arbitration_loop
  v2_trade_management_paper_loop
  v2_production_payload_freshness_refresher
  v2_production_replacement_soak_observer
  v2_production_equivalence_comparator
  v2_legacy_log_intelligence_observer
  v2_continuous_legacy_log_to_rebuild_remediation
  v2_production_replacement_runtime_guard
  v2_legacy_v2_production_comparator
  v2_liquidation_wss_loop
)

echo "=== V2 production replacement processes ==="
for p in "${PATTERNS[@]}"; do
  if pgrep -fa "$p" >/dev/null 2>&1; then
    pgrep -fa "$p" | head -1
  else
    echo "MISSING: $p"
  fi
done

echo
echo "=== Redis v2:* namespace counts ==="
for pat in 'v2:*' 'v2:market:*' 'v2:features:*' 'v2:prediction:*' 'v2:trainer:*' 'v2:orchestrator:*' 'v2:signals:*' 'v2:paper:*' 'v2:risk:*'; do
  count=$(redis-cli --scan --pattern "$pat" 2>/dev/null | wc -l)
  printf '%-22s %s\n' "$pat" "$count"
done

echo
echo "=== Safety ==="
echo "live_gate: blocked_human_only"
echo "live_symbols: []"
echo "approves_live: false"
echo "approves_legacy_shutdown: false"
