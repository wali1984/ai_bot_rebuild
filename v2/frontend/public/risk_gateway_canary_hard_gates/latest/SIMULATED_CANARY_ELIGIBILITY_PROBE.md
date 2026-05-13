# Simulated Canary Eligibility Probe

Generated at: 2026-05-13T06:59:54.381Z

Classification: CANARY_ELIGIBILITY_PROBE_SAFE_BLOCKED

A valid hypothetical canary intent can reach human-consideration classification in the V2-only guard, but safe_for_live=false and automation_can_enable_live=false. With the approval token absent, live remains blocked. Unsafe variants block for the expected reason codes.

| Variant | Expected blocker | Result |
| --- | --- | --- |
| missing_signal_id | missing_signal_id | BLOCKED |
| missing_prediction_id | missing_prediction_id | BLOCKED |
| missing_feature_snapshot_id | missing_feature_snapshot_id | BLOCKED |
| missing_confidence | missing_confidence | BLOCKED |
| missing_source_module | missing_source_module | BLOCKED |
| stale_signal | stale_risk_add_signal | BLOCKED |
| duplicate_exchange_order_id | duplicate_exchange_order_id | BLOCKED |
| duplicate_execution_intent_id | duplicate_execution_intent_id | BLOCKED |
| duplicate_signal_id | duplicate_signal_id | BLOCKED |
| cross_margin | cross_margin_blocked_for_canary | BLOCKED |
| isolated_margin_unknown | isolated_margin_not_verified | BLOCKED |
| leverage_cap_unknown | leverage_cap_unknown | BLOCKED |
| leverage_above_cap | leverage_above_cap | BLOCKED |
| adjust_leverage | adjust_leverage_disabled_by_default | BLOCKED |
| adjust_leverage_and_position | adjust_leverage_and_position_disabled_by_default | BLOCKED |
| hedge | hedge_dca_disabled_initially | BLOCKED |
| dca | hedge_dca_disabled_initially | BLOCKED |
| missing_stop_policy | missing_stop_policy | BLOCKED |
| kill_switch_unhealthy | kill_switch_unhealthy | BLOCKED |
| daily_loss_gate_missing | daily_loss_gate_missing | BLOCKED |
| weekly_loss_gate_missing | weekly_loss_gate_missing | BLOCKED |
| market_feed_stale_or_missing | market_feed_stale_or_missing | BLOCKED |
| feature_snapshot_stale_or_missing | feature_snapshot_stale_or_missing | BLOCKED |
| missing_risk_config_version | missing_risk_config_version | BLOCKED |
