# Trainer Trader Monitor Continuation

Generated at: `2026-05-13T19:23:12Z`

| Field | Value |
| --- | --- |
| generated_at | 2026-05-13T19:23:12Z |
| source | read_only_process_and_redis_observation |
| processes | [" 251241 1011413   65791  5.8  0.5 python3 ingest/live_coinank.py", " 348836  348834   57809  3.0  0.5 python3 -u trading/trader.py", " 573824 1011413   42345  0.0  0.0 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30", " 573883 1011413   42340  0.0  0.0 bash -c while true; do python3 -m v2.backend.app.cli.paper_shadow_observation --write >> v2/runtime/paper_shadow_observation/latest/paper_shadow_observation.log 2>&1; sleep 300; done", "1042465 1011413  393300  0.4  0.4 python3 -m rl.orchestrator_worker", "3980694 1011413   98688 78.1  3.5 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features"] |
| recent_executed_signals_readonly | [{"action": "PARTIAL_CLOSE_SHORT", "action_category": "PROTECTIVE", "confidence": 0.7, "exchange_order_id_present": true, "executed": true, "id": "1778699984389-0", "leverage_before": 37.0, "margin_type_before": "cross", "signal_id_present": true, "source_module": "trader_partial_close", "symbol": "XRPUSDT"}, {"action": "INCREASE_SHORT", "action_category": "HEDGE", "confidence": 0.85, "exchange_order_id_present": true, "executed": true, "id": "1778699937361-0", "leverage_before": 20.0, "margin_type_before": "cross", "signal_id_present": true, "source_module": "graduated_kill_scale", "symbol": "FARTCOINUSDT"}, {"action": "PARTIAL_CLOSE_LONG", "action_category": "PER_LEG_ROI_KILL", "confidence": 1.0, "exchange_order_id_present": true, "executed": true, "id": "1778699853177-0", "leverage_before": 67.0, "margin_type_before": "cross", "signal_id_present": true, "source_module": "trader_partial_close", "symbol": "SOLUSDT"}, {"action": "INCREASE_SHORT", "action_category": "HEDGE", "confidence": 0.85, "exchange_order_id_present": true, "executed": true, "id": "1778699848563-0", "leverage_before": 20.0, "margin_type_before": "cross", "signal_id_present": true, "source_module": "graduated_kill_scale", "symbol": "FARTCOINUSDT"}, {"action": "INCREASE_SHORT", "action_category": "HEDGE", "confidence": 0.85, "exchange_order_id_present": true, "executed": true, "id": "1778699816852-0", "leverage_before": 37.0, "margin_type_before": "cross", "signal_id_present": true, "source_module": "graduated_kill_scale", "symbol": "XRPUSDT"}] |
| observed_risks | ["legacy_recent_hedge_actions_observed", "legacy_cross_margin_observed", "legacy_high_leverage_observed"] |
| stale_signal_age | not_computed_in_this_readonly_sample |
| duplicate_exchange_order_id | not_observed_in_count_5_sample |
| mutation_performed | False |
| restart_performed | False |
