# Negative Paper Pnl Diagnosis

Generated at: `2026-05-13T19:23:12Z`

| Field | Value |
| --- | --- |
| generated_at | 2026-05-13T19:23:12Z |
| classifications | ["PAPER_PNL_DIAGNOSIS_BLOCKS_CANARY", "PAPER_PNL_DIAGNOSIS_INSUFFICIENT_WINDOW", "PAPER_PNL_NEGATIVE_EARLY_WINDOW", "PAPER_PNL_NEGATIVE_FEES_SLIPPAGE_DRAG", "PAPER_PNL_NEGATIVE_OVERTRADING", "PAPER_PNL_NEGATIVE_PAPER_ENGINE_ASSUMPTION", "PAPER_PNL_NEGATIVE_SIGNAL_EDGE_WEAK"] |
| total_events | 1287 |
| simulated_fills | 1168 |
| blocked_intents | 119 |
| paper_pnl_current_usdt | -38.09 |
| paper_pnl_delta_usdt | -11.72 |
| gross_pnl_if_fees_added_back_usdt | -0.04 |
| fees_usdt | 11.68 |
| slippage_assumption_bps | 2.0 |
| funding_assumption | zero_until_funding_feed_adapter_current |
| symbols_traded | {"BTCUSDT": 1168} |
| action_distribution | {"long": 555, "short": 613} |
| long_vs_short_distribution | {"long": 555, "short": 613} |
| confidence_bucket_distribution | {"0.58_to_0.65": 221, "0.65_to_0.75": 265, "0.75_plus": 682} |
| risk_decision_distribution | {"allow_proceed_long": 555, "allow_proceed_short": 613, "deny_low_confidence": 78, "deny_orchestrator_held": 41} |
| top_loss_symbols | {"BTCUSDT": -11.72} |
| top_loss_action_types | {"long": -5.55, "short": -6.17} |
| average_win_usdt | 0.0 |
| average_loss_usdt | -0.01004284 |
| win_rate | 0.0 |
| profit_factor | 0.0 |
| largest_loss_usdt | -0.06 |
| drawdown_proxy_usdt | -38.09 |
| latency_bucket | MISSING_EVIDENCE |
| fills_are_too_frequent | True |
| fee_slippage_bleed | True |
| low_confidence_fill_count | 221 |
| paper_engine_assumption | Current paper engine realizes fee-only PnL per fill and does not model exit edge; negative PnL is not profitability proof. |
| trainer_edge_status | UNPROVEN_OR_WEAK_UNTIL_6H_24H_AND_GROSS_PNL_MODEL_COMPLETE |
| risk_gateway_allowed_too_many_unsafe_paper_intents | True |
