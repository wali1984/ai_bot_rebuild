# Dashboard Payload Freshness Report

Generated at: 2026-05-12T23:05:32.391Z

- Payloads checked: 16
- Stale payloads: 13
- Static fixtures: 1
- Missing evidence rows: 1
- Public JSON files discovered: 168

Stale/static sources:

- master planner status: STALE / REALTIME_RUNTIME_EVIDENCE / age=95418 / claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json
- autonomous governor selection: STALE / RUNTIME_MONITOR_PAYLOAD / age=731 / claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json
- enterprise cockpit payload: STATIC_PROOF_FIXTURE / STATIC_PROOF_FIXTURE / age=255992 / v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json
- realtime legacy runtime sources: STALE / RUNTIME_MONITOR_PAYLOAD / age=141574 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/current_runtime_sources.json
- trainer prediction monitor status: STALE / RUNTIME_MONITOR_PAYLOAD / age=141574 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/trainer_prediction_monitor_status.json
- signal execution monitor status: STALE / RUNTIME_MONITOR_PAYLOAD / age=141574 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/signal_execution_monitor_status.json
- risk gateway observation status: STALE / RUNTIME_MONITOR_PAYLOAD / age=141574 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/risk_gateway_observation_status.json
- phase3c runtime monitor payload: STALE / RUNTIME_MONITOR_PAYLOAD / age=235736 / v2/frontend/public/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json
- v2 live observer shadow twin: STALE / REALTIME_RUNTIME_EVIDENCE / age=9465 / v2/frontend/public/operator_runtime/live_observer/latest/current_runtime_truth_payload.json
- legacy trainer restart runtime capture: STALE / RUNTIME_MONITOR_PAYLOAD / age=22519 / v2/frontend/public/legacy_trainer_restart_runtime/latest/operator_dashboard_payload.json
- orchestrator evidence reconciliation payload: STALE / V2_PROOF_ARTIFACT / age=88008 / v2/frontend/public/orchestrator_decision_evidence_reconciliation/latest/operator_dashboard_payload.json
- readonly market exchange data plane: STALE / V2_PROOF_ARTIFACT / age=255932 / v2/frontend/public/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json
- paper runtime status: STALE / V2_PROOF_ARTIFACT / age=268649 / v2/frontend/public/continuous_paper_shadow_runtime/latest/paper_runtime_status.json
- enterprise cockpit payload: STATIC_PROOF_FIXTURE / STATIC_PROOF_FIXTURE / age=255992 / v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json
