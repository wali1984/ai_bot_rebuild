# Dashboard Payload Freshness Report

Generated at: 2026-05-12T02:32:59.471Z

- Payloads checked: 13
- Stale payloads: 12
- Static fixtures: 1
- Missing evidence rows: 3
- Public JSON files discovered: 83

Stale/static sources:

- supervisor current status: STALE / REALTIME_RUNTIME_EVIDENCE / age=749 / claude_worklog/agent_supervisor/status/current_status.json
- supervisor queue status: STALE / REALTIME_RUNTIME_EVIDENCE / age=749 / claude_worklog/agent_supervisor/status/queue_status.json
- master planner status: STALE / REALTIME_RUNTIME_EVIDENCE / age=21465 / claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json
- autonomous governor selection: STALE / RUNTIME_MONITOR_PAYLOAD / age=67621 / claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json
- enterprise cockpit payload: STATIC_PROOF_FIXTURE / STATIC_PROOF_FIXTURE / age=182039 / v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json
- realtime legacy runtime sources: STALE / RUNTIME_MONITOR_PAYLOAD / age=67621 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/current_runtime_sources.json
- trainer prediction monitor status: STALE / RUNTIME_MONITOR_PAYLOAD / age=67621 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/trainer_prediction_monitor_status.json
- signal execution monitor status: STALE / RUNTIME_MONITOR_PAYLOAD / age=67621 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/signal_execution_monitor_status.json
- risk gateway observation status: STALE / RUNTIME_MONITOR_PAYLOAD / age=67621 / v2/frontend/public/realtime_legacy_monitoring_continuity/latest/risk_gateway_observation_status.json
- phase3c runtime monitor payload: STALE / RUNTIME_MONITOR_PAYLOAD / age=161783 / v2/frontend/public/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json
- readonly market exchange data plane: STALE / V2_PROOF_ARTIFACT / age=181979 / v2/frontend/public/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json
- paper runtime status: STALE / V2_PROOF_ARTIFACT / age=194696 / v2/frontend/public/continuous_paper_shadow_runtime/latest/paper_runtime_status.json
- enterprise cockpit payload: STATIC_PROOF_FIXTURE / STATIC_PROOF_FIXTURE / age=182039 / v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json
