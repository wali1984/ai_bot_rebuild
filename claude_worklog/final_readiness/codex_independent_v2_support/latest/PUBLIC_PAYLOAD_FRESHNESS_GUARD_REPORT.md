# Public Payload Freshness Guard Report

Generated: 2026-05-15T18:02:40Z
Result: `BLOCKED`
Live gate: `blocked_human_only`
Payloads checked: 125
GO/NO-GO files checked: 100
Approval token created: `False`

Findings:
- `v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/active_autonomous_dispatch/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/always_on_claude_codex_runtime/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/autonomous_governor/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/autonomous_governor_manual_replacement/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/claude_automation_non_drift_governor_lock/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/claude_codex_rate_limit_handoff/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/claude_design_full_visual_implementation/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/claude_primary_handoff/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/claude_rate_limit_codex_takeover/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/codex_design_handoff_review_protocol/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/codex_env_repo_parity/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/codex_independent_v2_support/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/codex_parallel_audit_plan/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/control_plane_supervisor_persistence/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/current_data_migration_sprint/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/decision_explainability_lineage/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/emergency_v2_runtime_migration/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/enterprise_ui_polish/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/external_manual_position_quarantine/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/final_live_capital_gate/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/go_live_tonight_primary_focus/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/historical_30d_replay_and_paper_proof/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/legacy_based_worker_porting_enforcement/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/legacy_coinank_plan3_bridge/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/legacy_rl_risk_trainer_trader_closure/latest/operator_dashboard_payload.json`: READY_CLAIM_WITH_MISSING_EVIDENCE, STALE_PAYLOAD
- `v2/frontend/public/legacy_startup_baseline_v2_migration/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/legacy_trainer_gpu_parity/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/legacy_trainer_restart_runtime/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/live_blocker_burndown_trading_platform_ui/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/non_drift_governor_lock/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/observatory_to_action_controller_patch/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/online_readiness_control_plane/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json`: MISSING_GENERATED_AT
- `v2/frontend/public/operator_runtime/legacy_live_bridge/latest/current_runtime_truth_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/legacy_live_bridge/latest/legacy_live_bridge_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/audit_ledger_tail.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/current_runtime_truth_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/legacy_live_bridge_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/orchestrator_adapter_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/paper_shadow_ledger_tail.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/risk_gateway_shadow_decision.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/shadow_signal_twin.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/trainer_bridge_parity_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/live_observer/latest/v2_data_plane_bridge_status.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_binance_usdm_adapter/latest/v2_binance_usdm_adapter_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_config_admin_manager/latest/v2_config_admin_manager_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_default_blocked_execution_adapter/latest/v2_default_blocked_execution_adapter_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_feature_pipeline_and_ta_worker/latest/v2_feature_pipeline_and_ta_worker_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_replay_worker/latest/v2_replay_worker_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_script_monitor/latest/v2_script_monitor_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_runtime/v2_signal_publisher/latest/v2_signal_publisher_status.json`: STALE_PAYLOAD
- `v2/frontend/public/operator_truth_recovery/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/operator_ui_hard_fail_recovery/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/orchestrator_decision_evidence_reconciliation/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/paper_edge_post_filter_observation_window/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/paper_expected_move_coverage/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/paper_loss_attribution/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/paper_shadow_outcome_learning/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/paper_shadow_outcome_observer/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/paper_shadow_persistence_and_ports/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/paper_shadow_soak_negative_pnl/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/paper_strategy_edge_tightening/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/permanent_migration_runtime/latest/operator_dashboard_payload.json`: MISSING_GENERATED_AT, READY_CLAIM_WITH_MISSING_EVIDENCE
- `v2/frontend/public/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/production_dashboard_wajidali_us_repair/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/production_operator_webapp/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/production_truth_reconciliation/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/production_website_full_rebuild/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/production_website_public_route_rebuild/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/public_trading_platform_visual_parity/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/realtime_control_plane_recovery/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/realtime_control_plane_trainer_monitor_recovery/latest/operator_dashboard_payload.json`: MISSING_SOURCE
- `v2/frontend/public/realtime_legacy_monitoring_continuity/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/redis_export_capacity_remediation/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/redis_liquidations_full_export/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/redis_memory_human_approval/latest/operator_dashboard_payload.json`: STALE_PAYLOAD
- `v2/frontend/public/redis_memory_pressure_remediation/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/redis_safe_trim_packet/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/redis_trim_approval_hold/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/risk_gateway_canary_hard_gates/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/root_route_mission_control/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/root_route_redirect_to_v2_mission_control/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/system_atlas_gap_remediation/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/system_atlas_runtime_coverage/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/tonight_live_like_paper_shadow/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/trainer_derived_evidence_acceptance/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/v2_data_plane_independence/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/v2_live_observer_shadow_twin/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/v2_paper_online_recovery/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/v2_persistent_automation_service_layer/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD
- `v2/frontend/public/v2_production_truth_reconciliation/latest/operator_dashboard_payload.json`: MISSING_SOURCE, STALE_PAYLOAD

The guard is read-only and did not mutate public payloads.
