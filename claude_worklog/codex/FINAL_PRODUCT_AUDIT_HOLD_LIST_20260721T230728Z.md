# FINAL PRODUCT AUDIT HOLD_LIST — 2026-07-21T23:07:28Z

## Enforcement

- Snapshot branch: `codex/pipeline-trust-refresh`
- Snapshot HEAD: `f06277824efacb58ac5f83f1d42eca4a56adabe8`
- Upstream: `origin/codex/pipeline-trust-refresh`
- Divergence: 0 ahead / 0 behind
- Pre-existing dirty paths: 155
- Evidenced publisher/native-ingestor paths: 35
- Other concurrent or owner-unproven paths: 120
- Edit rule: every path in the full snapshot below is held. No audit commit may stage or modify one unless ownership is separately resolved.
- Service rule: no service listed below may be restarted, enabled, disabled, masked, or unmasked during the independent web/API audit.
- Redis rule: no writer or destructive query is authorized. Patterns are ownership evidence only; no `KEYS` or unbounded `SCAN` was run.

## Evidenced publisher/native-ingestor hold paths (35)

```text
claude_worklog/codex/CODEX_PARALLEL_CHANGE_NOTICE_2026_07_19_COINGLASS_LIQUIDATION_ECHO.md
v2/backend/app/cli/symbol_universe_public_payload.py
v2/backend/app/cli/v2_coinank_intel_bridge.py
v2/backend/app/cli/v2_kucoin_ingestor_worker.py
v2/backend/app/cli/v2_liquidation_enhanced.py
v2/backend/app/cli/v2_liquidation_levels_engine.py
v2/backend/app/cli/v2_liquidation_wss_loop.py
v2/backend/app/cli/v2_native_ingestors_live_loop.py
v2/backend/app/services/adaptive_symbol_selection.py
v2/backend/app/services/adaptive_symbol_selection_runtime.py
v2/backend/app/services/altdata/coinank_scheduler.py
v2/backend/app/services/echo_forecast/__init__.py
v2/backend/app/services/echo_forecast/analog_forecaster.py
v2/backend/app/services/microstructure_trust/cascade_context.py
v2/backend/app/services/native_ingestors/kucoin.py
v2/backend/app/services/native_ingestors/liquidations_wss.py
v2/backend/app/services/operator_truth/trade_derivatives_runtime.py
v2/backend/app/services/v2_symbol_runtime_universe.py
v2/backend/tests/integration/cli/test_v2_coinank_intel_bridge_consumption.py
v2/backend/tests/integration/cli/test_v2_kucoin_ingestor_worker.py
v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py
v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py
v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py
v2/backend/tests/unit/cli/test_v2_kucoin_ingestor_worker.py
v2/backend/tests/unit/cli/test_v2_liquidation_enhanced_fail_closed.py
v2/backend/tests/unit/cli/test_v2_liquidation_levels_engine.py
v2/backend/tests/unit/cli/test_v2_native_ingestors_long_short_ratio.py
v2/backend/tests/unit/cli/test_v2_native_ingestors_partial_bundle.py
v2/backend/tests/unit/cli/test_v2_native_ingestors_source_freshness_contract.py
v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py
v2/backend/tests/unit/services/echo_forecast/test_analog_forecaster.py
v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py
v2/backend/tests/unit/services/test_adaptive_symbol_selection.py
v2/backend/tests/unit/services/test_adaptive_symbol_selection_runtime.py
v2/backend/tests/unit/services/test_trade_derivatives_runtime_payloads.py
```
## Redis ownership patterns (38)

```text
latest:coinank:open_interest:{symbol}:5m
latest:coinank:open_interest:{symbol}:1h
v2:market:prices:{symbol}
v2:market:funding:{symbol}
v2:market:open_interest:{symbol}
v2:market:long_short:{symbol}
v2:market:ohlcv:binance:{symbol}:{timeframe}
v2:market:ohlcv_closed:binance:{symbol}:{timeframe}
v2:market:orderbook:{symbol}
v2:market:orderbook:binance:{symbol}
v2:market:open_interest_hist:{symbol}:{period}
v2:market:mark_price:{symbol}
v2:orderbook:top:binance:{symbol}
v2:market:ingestor:heartbeat
v2:market:ohlcv:binance:heartbeat
v2:market:orderbook:binance:heartbeat
v2:market:ingestor:status
latest:coinank:*
latest:coinank:{family}:{symbol}:{timeframe}
latest:coinank_endpoint:*
latest:coinank_endpoint:{endpoint}:{symbol}:{timeframe}
latest:coinank_endpoint:{endpoint}:{variant}:{symbol}:{timeframe}
v2:coinank:symbol:{symbol}
v2:features:latest:{symbol}:1m
v2:liquidation:enhanced:{symbol}
v2:liquidation:enhanced:shadow:{symbol}
v2:liquidations:dedupe:{source_event_id_without_wss_prefix}
v2:liquidations:events:quarantine
v2:liquidations:levels:{symbol}:{timeframe}
v2:market:kucoin:coverage_ledger
v2:market:kucoin:rotation_cursor
v2:market:liquidations:latest:{symbol}
v2:market:liquidations:observed_aggregate:{symbol}
v2:market:orderbook:binance:{symbol}
v2:market:orderbook:{symbol}
v2:market:prices:{symbol}
v2:market:ohlcv_closed:binance:{symbol}:5m
v2:universe:coverage_census
```

## Service/timer boundaries referenced by the lane (23)

```text
ai-bot-v2-adaptive-capital-productivity.service
ai-bot-v2-binance-mark-price-wss-seeder.service
ai-bot-v2-coinank-global-aggregator-direct.service
ai-bot-v2-continuous-edge-guardian.service
ai-bot-v2-continuous-offline-gpu-trainer.service
ai-bot-v2-edge-replay-factory.service
ai-bot-v2-native-cuda-trainer-persistent.service
ai-bot-v2-native-ppo-masa-continuous-training-guard.service
ai-bot-v2-orchestrator-arbitration-loop.service
ai-bot-v2-risk-gateway-live-loop.service
ai-bot-v2-trade-management-paper-loop.service
ai-bot-v2-trainer-logrotate.service
ai-bot-v2-trainer-scheduled-pretrain.service
ai-bot-v2-native-ppo-masa-continuous-training-guard.timer
ai-bot-v2-trainer-logrotate.timer
ai-bot-v2-trainer-scheduled-pretrain.timer
ai-bot-v2-native-ingestors-live-loop.service
ai-bot-v2-profiled-base-feature-publisher.service
ai-bot-v2-coinglass-provider-loop.service
ai-bot-v2-altdata-confluence-loop.service
ai-bot-v2-cascade-context-publisher.service
ai-bot-v2-strategy-supply-publisher.service
ai-bot-v2-microstructure-feed-quality-monitor.service
```

## Release and hold commits

- Native-ingestor immutable release: `0f9b5c93b75b11b2f21f70663b9cc1ba34413423`
- Trainer-observer release: `9fc6c55ebdea7b79afa8bbe21a5043b8579463b6`
- Witnessed admission: `86e6e0c8d818982bdb18fab3a08145238716066c`
- Provider masking: `99b3f306811d8bd4f187a033c3101740a1ee644b`
- CoinGlass point-in-time repair: `3b6593cb601f033d4bff91c7831565fde53f16de`
- Confluence release: `b69383d336b2df0adb1573f506c6fc5337261d39`
- Explicit service holds: `04357a4215`, `650a032423`, `c894e0c6e0`
- Recent backend audit commits with Claude co-author evidence: `9a097c04322c46bd91dd1f63411e70e5f9997ffb`, `e96462f43d562e024e27220ef3fa67dc780dacb8`

## Full pre-existing dirty snapshot (155)

The two-character porcelain status is retained. This is the authoritative exclusion set for audit staging.

```text
 M docs/MASTER_SYSTEM_DOC.md
 M docs/system_audit_2026_master/AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md
 M docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md
 M docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md
 M docs/system_audit_2026_master/REBUILD_BLUEPRINT.md
 M docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md
 M docs/system_audit_2026_master/components/DATA_TEMPORAL_LINEAGE_AND_FEATURES.md
 M docs/system_audit_2026_master/components/DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md
 M docs/system_audit_2026_master/components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md
 M scripts/guardian_phase10_rare_event_tests.py
 M scripts/verify_claude_guardian_completion.py
 M tools/orderbook_replay_rollover.py
 M v2/backend/app/cli/run_real_inference_paper_batch.py
 M v2/backend/app/cli/symbol_universe_public_payload.py
 M v2/backend/app/cli/v2_binance_mark_price_wss_seeder.py
 M v2/backend/app/cli/v2_clean_3000_session_edge_recovery.py
 M v2/backend/app/cli/v2_coinank_intel_bridge.py
 M v2/backend/app/cli/v2_kucoin_ingestor_worker.py
 M v2/backend/app/cli/v2_liquidation_enhanced.py
 M v2/backend/app/cli/v2_liquidation_levels_engine.py
 M v2/backend/app/cli/v2_liquidation_wss_loop.py
 M v2/backend/app/cli/v2_native_ingestors_live_loop.py
 M v2/backend/app/cli/v2_out_of_sample_reverify_evidence_producer.py
 M v2/backend/app/cli/v2_portfolio_cascade_guard_loop.py
 M v2/backend/app/cli/v2_portfolio_state_publisher.py
 M v2/backend/app/cli/v2_trade_management_paper_loop.py
 M v2/backend/app/cli/v2_trainer_offline_hyperparameter_sweep.py
 M v2/backend/app/services/a_plus_trade_gate/service.py
 M v2/backend/app/services/adaptive_capital_allocator/allocator.py
 M v2/backend/app/services/adaptive_capital_allocator/contracts.py
 M v2/backend/app/services/adaptive_capital_allocator/counterfactual.py
 M v2/backend/app/services/adaptive_capital_allocator/sizing_model.py
 M v2/backend/app/services/continuous_edge_guardian/guardian.py
 M v2/backend/app/services/echo_forecast/__init__.py
 M v2/backend/app/services/echo_forecast/analog_forecaster.py
 M v2/backend/app/services/microstructure_trust/cascade_context.py
 M v2/backend/app/services/native_ingestors/kucoin.py
 M v2/backend/app/services/native_ingestors/liquidations_wss.py
 M v2/backend/app/services/operator_truth/trade_derivatives_runtime.py
 M v2/backend/app/services/paper_accounting/mark_to_market.py
 M v2/backend/app/services/paper_trade_management/adaptive_cost_model.py
 M v2/backend/app/services/paper_trade_management/entry_gate.py
 M v2/backend/app/services/paper_trade_management/lifecycle.py
 M v2/backend/app/services/paper_trade_management/outcome_memory.py
 M v2/backend/app/services/paper_trade_management/outcome_memory_updater.py
 M v2/backend/app/services/paper_trade_management/position_state.py
 M v2/backend/app/services/preemptive_edge_control/__init__.py
 M v2/backend/app/services/preemptive_edge_control/bucket_health.py
 M v2/backend/app/services/preemptive_edge_control/candidate_loss_risk.py
 M v2/backend/app/services/preemptive_edge_control/decision.py
 M v2/backend/app/services/preemptive_edge_control/service.py
 M v2/backend/app/services/risk/cross_margin_liquidation.py
 M v2/backend/app/services/v2_symbol_runtime_universe.py
 M v2/backend/tests/integration/cli/test_v2_coinank_intel_bridge_consumption.py
 M v2/backend/tests/integration/cli/test_v2_kucoin_ingestor_worker.py
 M v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py
 M v2/backend/tests/integration/cli/test_v2_paper_fill_gate_block_reason_passthrough.py
 M v2/backend/tests/integration/cli/test_v2_trade_management_paper_strategy_router.py
 M v2/backend/tests/unit/cli/test_run_real_inference_paper_batch.py
 M v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py
 M v2/backend/tests/unit/cli/test_v2_adaptive_capital_productivity_status.py
 M v2/backend/tests/unit/cli/test_v2_binance_mark_price_wss_seeder.py
 M v2/backend/tests/unit/cli/test_v2_clean_3000_session_edge_recovery.py
 M v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py
 M v2/backend/tests/unit/cli/test_v2_kucoin_ingestor_worker.py
 M v2/backend/tests/unit/cli/test_v2_native_ingestors_long_short_ratio.py
 M v2/backend/tests/unit/cli/test_v2_native_ingestors_partial_bundle.py
 M v2/backend/tests/unit/cli/test_v2_out_of_sample_reverify_evidence_producer.py
 M v2/backend/tests/unit/cli/test_v2_paper_outcome_memory_rebuild.py
 M v2/backend/tests/unit/cli/test_v2_portfolio_state_publisher_equity.py
 M v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
 M v2/backend/tests/unit/cli/test_v2_trainer_offline_hyperparameter_sweep.py
 M v2/backend/tests/unit/services/a_plus_trade_gate/test_context_loader.py
 M v2/backend/tests/unit/services/adaptive_capital_allocator/test_adaptive_leverage_margin_ramp.py
 M v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py
 M v2/backend/tests/unit/services/adaptive_capital_allocator/test_counterfactual.py
 M v2/backend/tests/unit/services/adaptive_capital_allocator/test_go_live_fixture_matrix.py
 M v2/backend/tests/unit/services/adaptive_capital_allocator/test_phase6_status.py
 M v2/backend/tests/unit/services/allocator/test_allocator_simulation.py
 M v2/backend/tests/unit/services/continuous_edge_guardian/test_guardian.py
 M v2/backend/tests/unit/services/echo_forecast/test_analog_forecaster.py
 M v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py
 M v2/backend/tests/unit/services/native_trainer/test_authenticated_sampling_plan_archive.py
 M v2/backend/tests/unit/services/paper_trade_management/test_adaptive_cost_model.py
 M v2/backend/tests/unit/services/paper_trade_management/test_adaptive_hedging.py
 M v2/backend/tests/unit/services/paper_trade_management/test_hourly_monitor_loss_recovery.py
 M v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
 M v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py
 M v2/backend/tests/unit/services/paper_trade_management/test_phase2_3_4_gates.py
 M v2/backend/tests/unit/services/risk/test_cross_margin_liquidation.py
 M v2/backend/tests/unit/services/test_trade_derivatives_runtime_payloads.py
 M v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py
 M v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
 D v2/package-lock.json
?? claude_worklog/ATR_STOP_CEILING_ACTIVATION_READY.md
?? claude_worklog/G10_CAPITAL_INVARIANT_REPAIR_READY.md
?? claude_worklog/codex/CODEX_PARALLEL_CHANGE_NOTICE_2026_07_19_COINGLASS_LIQUIDATION_ECHO.md
?? claude_worklog/guardian_runtime_validation/CG_F049_F050_RUNTIME_VALIDATION_2026_07_21.md
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784226256.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784231518.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784236919.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784242318.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784247718.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784253249.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784258645.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784264460.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784269864.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784275255.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784286610.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784296675.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784302319.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784308205.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784313573.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784318937.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784323713.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784329100.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784334555.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784339869.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784342993.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784348165.json
?? claude_worklog/trainer_atlas/scheduled_pretrain_1784353540.json
?? docs/system_audit_2026_master/ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md
?? docs/system_audit_2026_master/ADAPTIVE_GATE_LOW_LEVEL_AUDIT_AND_CHANGE_IMPACT_2026-07-18.md
?? docs/system_audit_2026_master/COMMAND_LEDGER_2026-07-17.md
?? docs/system_audit_2026_master/OPERATOR_VALIDATION_AND_MONITORING_RUNBOOK_2026-07-17.md
?? tools/g10_capital_invariant_repair.py
?? tools/systemd_units/ai-bot-v2-binance-mark-price-wss-seeder.service
?? v2/backend/app/services/adaptive_symbol_selection.py
?? v2/backend/app/services/adaptive_symbol_selection_runtime.py
?? v2/backend/app/services/altdata/coinank_scheduler.py
?? v2/backend/app/services/paper_trade_management/cycle_reservation.py
?? v2/backend/app/services/paper_trade_management/exact_on_policy_entry_outbox.py
?? v2/backend/tests/unit/cli/test_v2_liquidation_enhanced_fail_closed.py
?? v2/backend/tests/unit/cli/test_v2_liquidation_levels_engine.py
?? v2/backend/tests/unit/cli/test_v2_native_ingestors_source_freshness_contract.py
?? v2/backend/tests/unit/cli/test_v2_paper_partial_restart_state_persistence.py
?? v2/backend/tests/unit/cli/test_v2_portfolio_cascade_guard_loop.py
?? v2/backend/tests/unit/cli/test_v2_trade_management_lifecycle_envelope.py
?? v2/backend/tests/unit/cli/test_v2_trade_management_ordinary_paper_admission.py
?? v2/backend/tests/unit/cli/test_v2_trade_management_reduced_allocation_contract.py
?? v2/backend/tests/unit/cli/test_v2_trade_management_side_performance_lineage.py
?? v2/backend/tests/unit/services/adaptive_capital_allocator/growth_receipt_test_utils.py
?? v2/backend/tests/unit/services/adaptive_capital_allocator/test_paper_quality_sizing_invariant.py
?? v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py
?? v2/backend/tests/unit/services/paper_trade_management/test_cycle_reservation.py
?? v2/backend/tests/unit/services/paper_trade_management/test_entry_gate_preloaded_evidence.py
?? v2/backend/tests/unit/services/paper_trade_management/test_exact_on_policy_entry_outbox.py
?? v2/backend/tests/unit/services/preemptive_edge_control/test_bucket_health.py
?? v2/backend/tests/unit/services/preemptive_edge_control/test_decision_snapshot_contract.py
?? v2/backend/tests/unit/services/risk/test_cross_margin_input_normalization.py
?? v2/backend/tests/unit/services/test_adaptive_symbol_selection.py
?? v2/backend/tests/unit/services/test_adaptive_symbol_selection_runtime.py
?? v2/mobile/Sources/AIBotV2/ViewModels/DerivativesViewModel.swift
?? v2/mobile/Sources/AIBotV2/ViewModels/MarketsViewModel.swift
?? v2/mobile/Sources/AIBotV2/Views/Markets/MarketSymbolDetailView.swift
```
