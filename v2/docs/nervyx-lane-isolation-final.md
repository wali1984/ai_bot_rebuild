# NERVYX Lane Isolation Final Evidence

- Generated at: `2026-06-23T19:49:38.527122+00:00`
- Current branch: `codex/pipeline-trust-refresh`
- Current HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Rebrand branch used for merge-base: `codex/nervyx-one-rebrand`
- Merge base: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`

## Required Final Status

- NERVYX ONE WEB REBRAND: IN PROGRESS
- REALTIME WEB DATA: IN PROGRESS / field-level validation pending
- ADMIN/SUPERADMIN COVERAGE: IN PROGRESS
- IOS SOURCE WIRING: IN PROGRESS
- NATIVE IOS VALIDATION: BLOCKED - MACOS/XCODE REQUIRED
- WATCHOS VALIDATION: BLOCKED - MACOS/XCODE REQUIRED
- TESTFLIGHT: BLOCKED
- LANE ISOLATION: UNPROVEN until protected hash diffs are diffed and justified
- DATA PRESERVATION: UNPROVEN until the parity matrix reaches 100%
- REAL LIVE EXECUTION: BLOCKED

## Worktrees

```text
/home/wali/Desktop/AI BOT REBUILD                                            5b0a4997da [codex/pipeline-trust-refresh]
/home/wali/Desktop/AI BOT REBUILD/.claude/worktrees/agent-a39550bb1950ba33d  4433301c24 [worktree-agent-a39550bb1950ba33d]
/home/wali/Desktop/AI BOT REBUILD/.claude/worktrees/agent-a990d4d5dc9180fbd  4433301c24 [worktree-agent-a990d4d5dc9180fbd]
/home/wali/Desktop/AI BOT REBUILD/.claude/worktrees/agent-ac74949e2d6d4f121  4433301c24 [worktree-agent-ac74949e2d6d4f121]
/home/wali/Desktop/AI BOT REBUILD/.claude/worktrees/agent-afeb952e1fe1b36e6  4433301c24 [worktree-agent-afeb952e1fe1b36e6]
```

## Git Status Excerpt

The complete tracked/untracked inventory is in `artifacts/nervyx-changed-file-inventory.jsonl.gz`.

```text
 M .gitignore
 M claude_worklog/agent_supervisor/tasks/claude_continuous_remediation_review_governor_blocker_fix.json
 M claude_worklog/agent_supervisor/tasks/claude_v2_production_replacement_runtime_loop_implementation.json
 M claude_worklog/agent_supervisor/tasks/claude_v2_runtime_soak_and_production_equivalence_remediation.json
 M claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/CODEX_SHUTDOWN_TAKEOVER_STATUS.md
 M claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json
 M claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_shutdown_takeover_status.json
 M claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/current_recommendation.json
 M claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/operator_dashboard_payload.json
 M claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/shutdown_readiness_state.json
 M claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json
 M claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_risk_gateway_runtime_worker_status.json
 M claude_worklog/final_readiness/legacy_runtime_gap_closure_20260603/latest/v2_trainer_checkpoint_evidence_status.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/LEGACY_V2_REALTIME_DECISION_OBSERVATORY_REPORT.md
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/NEXT_DECISION_IMPROVEMENT_TASKS.md
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/codex_legacy_v2_realtime_decision_observatory_status.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/decision_quality_scoreboard_status.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_runtime_observer_status.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_signal_outcome_observer_status.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/legacy_v2_decision_comparator_status.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/next_decision_improvement_tasks.json
 M claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/operator_dashboard_payload.json
 M claude_worklog/final_readiness/observatory_to_action_controller_patch/latest/OBSERVATORY_TO_ACTION_CONTROLLER_PATCH_REPORT.md
 M claude_worklog/final_readiness/observatory_to_action_controller_patch/latest/operator_dashboard_payload.json
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/PRODUCTION_URL_ROUTE_CRAWL_REPORT.md
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/ROUTE_FAILURE_CLASSIFICATION.md
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/production_route_matrix.json
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/production_route_matrix_before.json
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_audit-ledger_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_build-validation-status_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_claude-admin-ai_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_codex-review-center_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_config-admin_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_coverage-system-atlas_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_exchange-manager_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_execution-admin_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_executions_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_external-manual-position-quarantine_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_live-readiness_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_mission-control_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_mobile-iphone-readiness_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_monitor-center_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_ollama-local-assistant_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_operator-proof-dashboard_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_orchestrator-admin_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_paper-trading_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_positions_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_replay_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_risk-control_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_script-registry_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_signal-explainability_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_signals_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_strategy-admin_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_symbols_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_system-health_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_trainer-admin_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_admin_trainer-prediction-monitor_role_admin.png
 M claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/before/_landing.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/PRODUCTION_ROUTE_CRAWL_BEFORE_REPORT.md
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/production_route_matrix_before.json
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_audit-ledger_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_build-validation-status_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_claude-admin-ai_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_codex-review-center_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_config-admin_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_coverage-system-atlas_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_exchange-manager_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_execution-admin_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_executions_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_external-manual-position-quarantine_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_live-readiness_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_mission-control_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_mobile-iphone-readiness_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_monitor-center_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_ollama-local-assistant_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_operator-proof-dashboard_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_orchestrator-admin_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_paper-trading_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_positions_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_replay_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_risk-control_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_script-registry_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_signal-explainability_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_signals_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_strategy-admin_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_symbols_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_system-health_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_trainer-admin_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_admin_trainer-prediction-monitor_role_admin.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_landing.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_login.png
 M claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/_status.png
 M claude_worklog/final_readiness/symbol_universe_diff_buffer/latest/symbol_universe_diff_buffer_status.json
 M claude_worklog/final_readiness/symbol_universe_public_payload/latest/symbol_universe_status.json
 M claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/live_canary_executor_status.json
 M claude_worklog/final_readiness/v2_aicoin_whale_intel_free_tier_20260604/latest/V2_AICOIN_WHALE_INTEL_FREE_TIER_REPORT.md
 M claude_worklog/final_readiness/v2_aicoin_whale_intel_free_tier_20260604/latest/v2_aicoin_whale_intel_free_tier_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/V2_ALL_SYMBOL_ALL_TIMEFRAME_FEATURE_TRAINER_SIGNAL_GPU_PARITY_REPORT.md
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/V2_ALL_TIMEFRAME_PREDICTION_SIGNAL_PRICE_TARGET_PUBLISHER_REPORT.md
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_symbol_all_timeframe_backtest_edge_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_symbol_all_timeframe_cuda_prediction_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_prediction_publisher_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_signal_board_website_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_signal_lineage_completion_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_signal_lineage_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_signal_publisher_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/cuda_cpu_resource_utilization_upgrade_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/dynamic_symbol_full_pipeline_contract_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/expected_move_price_target_remediation_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/expected_move_telemetry_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/operator_dashboard_payload.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/price_target_all_tf_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/production_dashboard_all_tf_truth_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/unified_feature_field_coverage_matrix.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/unified_feature_parity_all_symbols_status.json
 M claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest/website_signal_grid_production_truth_status.json
```

## Changed File Inventory

- Complete tracked/untracked status record count: `471957`
- Compressed inventory: `artifacts/nervyx-changed-file-inventory.jsonl.gz`
- Inventory checksum: `07f3b30844d3b1cca9882b008f97d73baaa632754636eaf52140c062b2716b2b`
- Inventory checksum file: `artifacts/nervyx-changed-file-inventory.sha256`
- Classification summary: `artifacts/nervyx-changed-file-classification-summary.json`

## Commits Created Since Rebrand Merge Base

- `d36df906b7` fix: bump iOS build version to 5 (4 already uploaded to TestFlight)
- `bfaa3af2f9` chore: sync full working tree — task logs, V2 runtime artifacts, gitignore cleanup
- `4a3e6d7e18` feat: NerVyx Midnight Neural theme + real data alignment across iOS app
- `75b80990b4` fix: pre-publish audit — data alignment, string sanitization, signals limit
- `eb2510a890` test(mobile): add WS stream integrity and NerVyx copy-safety tests
- `e37eea1f6b` fix(mobile): escape Swift keyword 'guard' in NervyxModule and NervyxTokens
- `dead0f0e21` fix(mobile): remove duplicate Color(hex:) extension from NervyxBrand
- `a684e1e1fa` Wire realtime trading UI and align navigation
- `570b5bc1ad` fix(mobile): explicitly link WatchConnectivity.framework in xcodegen config
- `d425c612b2` fix(accounting): deduplicate closed_trades by close_id before Redis write
- `5b0a4997da` fix(ios): remove alpha channel from all app icons to fix App Store Error 90717

## Protected Lane Hash Result

- Base protected file hashes: `155`
- Current protected file hashes: `324`
- Protected hash mismatches/additions/deletions: `180`
- Diff status counts: `{'added': 169, 'modified': 11}`
- Review classification counts: `{'API_SURFACE_REQUIRES_REVIEW': 3, 'CLI_OR_PUBLISHER_REQUIRES_REVIEW': 59, 'DECISION_COMPOSITION_REQUIRES_REVIEW': 4, 'SERVICE_LOGIC_REQUIRES_REVIEW': 114}`
- Base hash file: `docs/nervyx-protected-lanes-base.sha256`
- Current hash file: `docs/nervyx-protected-lanes-current.sha256`
- Base hash file checksum: `ec6d130a54648aa7f56beaf00819833ad2fe811a184b16a93f6d5fc7a366fbc9`
- Current hash file checksum: `5518d36a14314f2c0b5b53d208bc1073a81007a398478a5e5c31cc8288b99db9`
- Diff artifact: `artifacts/nervyx-protected-lane-hash-diff.json`
- Diff artifact checksum: `eede6067e32aa18af2514813e667ad531b5edf7177590126581bd388b794c858`
- Modified protected diff patch: `artifacts/nervyx-protected-lane-modified-diffs.patch`
- Modified protected diff patch checksum: `6a0e7315c7c1e9a614ccd41db7a746c5f60de328d831f0e9aae21c76bed045fc`

The protected hash set intentionally over-includes adjacent backend API, CLI, composition/domain, service, repository, exchange, Redis, trainer, risk, execution, and migration-adjacent surfaces so protected-lane risk is visible instead of hidden.

## Isolation Verdict

UNPROVEN. The current protected hash set shows `180` protected-lane diffs from the rebrand merge base. Completion still requires every protected diff to be identified, diffed, justified as presentation/read-only only where applicable, and separately tested. The modified protected files are diffed in `artifacts/nervyx-protected-lane-modified-diffs.patch`; added protected files remain identified in `artifacts/nervyx-protected-lane-hash-diff.json` and require owner review before isolation can be claimed.

Current first-diff sample:

| Status | Review Classification | Path |
|---|---|---|
| `added` | `API_SURFACE_REQUIRES_REVIEW` | `v2/backend/app/api/v1/live_gate.py` |
| `added` | `API_SURFACE_REQUIRES_REVIEW` | `v2/backend/app/api/v2/live_gate_status.py` |
| `modified` | `API_SURFACE_REQUIRES_REVIEW` | `v2/backend/app/api/v2/trainer.py` |
| `modified` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/readonly_market_exchange_data_plane.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/run_runtime_alpha_decision_chain_remediation.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/run_trusted_prediction_publisher_once.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_all_timeframe_prediction_signal_price_target_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_coinank_direct_runtime_status_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_cuda_trainer_false_negative_reduction_actionability.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_derivatives_runtime_payload_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_dynamic_93_edge_recovery_signal_quality_burndown.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_exchange_filter_risk_profile_alignment_and_min_order_execution.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_final_live_gate_blocker_burndown_and_operator_enable_packet.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_ingestors_status_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_liquidation_bridge_status_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_liquidation_runtime_status_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_log_errors_status_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_market_chart_payload_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_misc_state_keys_publisher.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_model_state_ai_predictions_signals_runtime_truth_semantic_repair.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_cuda_trainer_edge_calibration_outcome_burn_in.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_cuda_trainer_runtime_signal_burn_in_live_gate.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_dynamic_runtime_and_trainer_bridge_exit_execution.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_hybrid_trainer_full_function_parity_and_paper_reverify.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_ppo_masa_continuous_training_guard.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_rl_masa_ppo_cuda_trainer_loop.py` |
| `added` | `CLI_OR_PUBLISHER_REQUIRES_REVIEW` | `v2/backend/app/cli/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py` |
