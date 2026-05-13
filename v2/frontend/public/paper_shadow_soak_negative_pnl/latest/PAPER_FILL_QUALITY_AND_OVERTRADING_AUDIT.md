# Paper Fill Quality And Overtrading Audit

Generated at: `2026-05-13T19:23:12Z`

| Field | Value |
| --- | --- |
| generated_at | 2026-05-13T19:23:12Z |
| classifications | ["CHURN_RISK_OBSERVED", "FEE_BLEED_OBSERVED", "FILL_RATE_TOO_HIGH", "LOW_CONFIDENCE_FILL_RISK", "OVERTRADING_RISK_OBSERVED"] |
| fills_per_minute | 1.619373 |
| fills_per_hour | 97.16238 |
| repeated_same_symbol_fills | {"BTCUSDT": 1168} |
| repeated_same_direction_fills | {"long": 555, "short": 613} |
| churn_flip_count | 91 |
| average_hold_time_seconds | MISSING_EVIDENCE_CURRENT_PAPER_ENGINE_HAS_NO_POSITION_LIFECYCLE |
| fee_slippage_per_fill | {"avg_fee_usdt": 0.01, "slippage_bps": 2.0} |
| pnl_per_fill_avg_usdt | -0.01003425 |
| pnl_by_confidence_bucket | {"0.58_to_0.65": -2.21, "0.65_to_0.75": -2.65, "0.75_plus": -6.86} |
| pnl_by_symbol | {"BTCUSDT": -11.72} |
| pnl_by_action | {"long": -5.55, "short": -6.17} |
| pnl_by_risk_decision | {"allow_proceed_long": -5.55, "allow_proceed_short": -6.17} |
| stricter_canary_profile_would_block_count | 486 |
| paper_engine_should_throttle_fills_for_canary_simulation | True |
| cooldown_should_be_tested | True |
