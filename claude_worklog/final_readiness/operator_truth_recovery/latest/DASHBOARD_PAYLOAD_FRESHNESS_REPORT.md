# Dashboard Payload Freshness Report

Generated at: 2026-05-12T02:06:27.241Z

- Payloads checked: 13
- Stale payloads: 10
- Static fixtures: 1
- Missing evidence rows: 3
- Public JSON files discovered: 78

Stale/static sources:

- master planner status: STALE_PAYLOAD / REALTIME_RUNTIME_EVIDENCE / age=19873 / claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json
- autonomous governor selection: STALE_PAYLOAD / RUNTIME_MONITOR_PAYLOAD / age=66029 / claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json
- enterprise cockpit payload: STATIC_PROOF_FIXTURE / STATIC_PROOF_FIXTURE / age=180447 / v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json
- realtime legacy runtime sources: STALE_PAYLOAD / RUNTIME_MONITOR_PAYLOAD / age=66029 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/current_runtime_sources.json
- trainer prediction monitor status: STALE_PAYLOAD / RUNTIME_MONITOR_PAYLOAD / age=66029 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/trainer_prediction_monitor_status.json
- signal execution monitor status: STALE_PAYLOAD / RUNTIME_MONITOR_PAYLOAD / age=66029 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/signal_execution_monitor_status.json
- risk gateway observation status: STALE_PAYLOAD / RUNTIME_MONITOR_PAYLOAD / age=66029 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/risk_gateway_observation_status.json
- phase3c runtime monitor payload: STALE_PAYLOAD / RUNTIME_MONITOR_PAYLOAD / age=160191 / v2/frontend/public/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json
- readonly market exchange data plane: STALE_PAYLOAD / V2_PROOF_ARTIFACT / age=180387 / v2/frontend/public/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json
- paper runtime status: STALE_PAYLOAD / V2_PROOF_ARTIFACT / age=193104 / v2/frontend/public/continuous_paper_shadow_runtime/latest/paper_runtime_status.json
- enterprise cockpit payload: STATIC_PROOF_FIXTURE / STATIC_PROOF_FIXTURE / age=180447 / v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json
