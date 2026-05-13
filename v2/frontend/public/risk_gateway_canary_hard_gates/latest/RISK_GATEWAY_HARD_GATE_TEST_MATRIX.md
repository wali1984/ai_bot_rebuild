# Risk Gateway Hard Gate Test Matrix

Generated at: 2026-05-13T06:59:54.381Z

Command: PYTHONPATH=. .venv/bin/pytest v2/backend/tests/unit/composition/live_canary_blocker_guard/test_runtime.py

Result: 30 passed, 0 failed.

| Case | Expected blocker | Status |
| --- | --- | --- |
| missing_signal_id | missing_signal_id | PASS |
| missing_prediction_id | missing_prediction_id | PASS |
| missing_feature_snapshot_id | missing_feature_snapshot_id | PASS |
| missing_confidence | missing_confidence | PASS |
| missing_source_module | missing_source_module | PASS |
| stale_signal | stale_risk_add_signal | PASS |
| duplicate_exchange_order_id | duplicate_exchange_order_id | PASS |
| duplicate_execution_intent_id | duplicate_execution_intent_id | PASS |
| duplicate_signal_id | duplicate_signal_id | PASS |
| cross_margin | cross_margin_blocked_for_canary | PASS |
| isolated_margin_unknown | isolated_margin_not_verified | PASS |
| leverage_cap_unknown | leverage_cap_unknown | PASS |
| leverage_above_cap | leverage_above_cap | PASS |
| adjust_leverage | adjust_leverage_disabled_by_default | PASS |
| adjust_leverage_and_position | adjust_leverage_and_position_disabled_by_default | PASS |
| hedge | hedge_dca_disabled_initially | PASS |
| dca | hedge_dca_disabled_initially | PASS |
| missing_stop_policy | missing_stop_policy | PASS |
| kill_switch_unhealthy | kill_switch_unhealthy | PASS |
| daily_loss_gate_missing | daily_loss_gate_missing | PASS |
| weekly_loss_gate_missing | weekly_loss_gate_missing | PASS |
| market_feed_stale_or_missing | market_feed_stale_or_missing | PASS |
| feature_snapshot_stale_or_missing | feature_snapshot_stale_or_missing | PASS |
| missing_risk_config_version | missing_risk_config_version | PASS |
