# V2 Dynamic 93 Edge Recovery And Signal Quality Burndown

Generated EST: 2026-06-21T19:36:10-04:00

GO/NO-GO: `V2_DYNAMIC_93_EDGE_RECOVERY_AND_SIGNAL_QUALITY_BURNDOWN_BLOCKED`

## Summary

- symbol_count: `86`
- classification_counts: `{'DATA_STALE': 39, 'RISK_BLOCK_DOMINANT': 43, 'INSUFFICIENT_SAMPLE': 4}`
- after_quality_fixes_expectancy_bps: `None`
- after_quality_fixes_ci_lower_bps: `None`
- pre_filter_after_cost_expectancy_bps: `-7.9849593590174015`
- pre_filter_after_cost_ci_lower_bps: `-10.546501713933516`
- primary_live_recommendation: `BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY`
- website_sync_status: `WEBSITE_SYNC_BLOCKED`
- next_automatic_action: `Continue paper/shadow outcome mining with quality overlay; do not enable execution.`

## Blockers

- `SYMBOL_COUNT_NOT_93`: symbol_count=86
- `PAPER_BACKTEST_EDGE_NOT_PROVEN_AFTER_QUALITY_FIXES`: BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY
- `WEBSITE_SYNC_BLOCKED`: one or more requested pages are not wired

## Safety

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- writes_legacy_redis: `false`
- writes_exchange_orders: `false`
- exchange mutation: `false`
- quality overlay scope: `paper/shadow only`
