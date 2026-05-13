# Runtime Canary Gate Status

Generated at: 2026-05-13T06:59:54.381Z

Live gate: blocked_human_only

| Gate | Status | Evidence | Impact |
| --- | --- | --- | --- |
| final_approval_token_absent_blocks_live | PASS | Approval token absent and live_gate_status remains blocked_human_only. | human approval still required |
| read_only_account_evidence_required | MISSING_EVIDENCE | No current V2 read-only exchange account payload was found. | blocks canary |
| trade_permission_known_required | MISSING_EVIDENCE | No current V2 trade-permission status payload was found. | blocks canary |
| cross_margin_blocks_canary | PASS | Runtime decision checks cross-margin block code; V2 unit tests cover cross margin intent blocker. | required for canary |
| isolated_margin_unknown_blocks_canary | PASS | V2 unit tests cover isolated-margin missing/unknown blocker. | required for canary |
| leverage_cap_unknown_blocks_canary | PASS | V2 unit tests cover missing cap and above-cap blockers. | required for canary |
| ADJUST_LEVERAGE_disabled_by_default | PASS | Runtime decision checks adjust-leverage block code; V2 unit tests cover adjust-leverage actions. | required for canary |
| hedge_dca_disabled_initially | PASS | V2 unit tests cover HEDGE and DCA default blockers. | required for canary |
| missing_signal_id_blocks | PASS | Runtime decision checks missing signal_id; V2 unit tests cover intent blocker. | required for canary |
| missing_prediction_id_blocks | PASS | Runtime decision checks missing prediction_id; V2 unit tests cover intent blocker. | required for canary |
| missing_feature_snapshot_id_blocks | PASS | Runtime decision checks missing feature_snapshot_id; V2 unit tests cover intent blocker. | required for canary |
| missing_confidence_blocks | PASS | Runtime decision checks missing confidence; V2 unit tests cover intent blocker. | required for canary |
| stale_risk_add_signal_blocks | PASS | Runtime decision checks stale signal; V2 unit tests cover >10s risk-add signal. | required for canary |
| duplicate_execution_dedupes_or_blocks | PASS | Runtime decision checks duplicate signal execution; V2 unit tests cover duplicate order, intent, signal IDs. | required for canary |
| mandatory_stop_policy_required | PASS | Runtime decision checks missing stop policy; V2 unit tests cover missing stop. | required for canary |
| kill_switch_required | PASS | Runtime decision checks disabled kill switch; V2 unit tests cover unhealthy switch. | required for canary |
| daily_loss_gate_required | PASS | Runtime decision checks daily-loss breach; V2 unit tests cover missing daily gate. | required for canary |
| weekly_loss_gate_required | MISSING_EVIDENCE | Current runtime decisions still do not list weekly_loss_breach; V2 unit tests cover missing weekly gate. | blocks canary evidence |
| market_and_feature_freshness_required | PASS | Market=CURRENT, feature=CURRENT. | required for canary |
| live_gate_remains_blocked_human_only | PASS | live_gate_status=blocked_human_only | hard stop |
