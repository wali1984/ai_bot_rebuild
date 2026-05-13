
# Website Current Data Blocker Fix Report

Generated: `2026-05-13T05:08:06Z`

Before this sprint, production-truth reconciliation reported `12` route data-truth blockers. After the shared runtime panel and route page repairs, this sprint crawl reports `0` blockers across `20` local/public route checks.

Key fixes:

- Signals and Executions no longer render the static proof panel as current runtime truth.
- Current `pred_paper_tick_*`, `sig_paper_tick_*`, `risk_paper_tick_*`, and `pei_paper_tick_*` IDs are visible on required routes.
- Live block text remains visible as `blocked_human_only` / `LIVE TRADING: BLOCKED`.
- CoinAnk panel now handles missing optional array fields without crashing the route.
- Static proof remains archive/collapsed context, not the current Signals/Executions surface.

| kind | route | status | current ids | static fixture visible | hist visible | live block | screenshot |
|---|---|---|---|---|---|---|---|
| local | /admin/mission-control?role=admin | PASS | True | True | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_mission-control_role_admin.png |
| local | /admin/trainer-prediction-monitor?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_trainer-prediction-monitor_role_admin.png |
| local | /admin/signal-explainability?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_signal-explainability_role_admin.png |
| local | /admin/signals?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_signals_role_admin.png |
| local | /admin/executions?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_executions_role_admin.png |
| local | /admin/paper-trading?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_paper-trading_role_admin.png |
| local | /admin/risk-control?role=admin | PASS | True | False | True | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_risk-control_role_admin.png |
| local | /admin/live-readiness?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_live-readiness_role_admin.png |
| local | /admin/script-registry?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_script-registry_role_admin.png |
| local | /admin/claude-admin-ai?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/local/local__admin_claude-admin-ai_role_admin.png |
| public | /admin/mission-control?role=admin | PASS | True | True | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_mission-control_role_admin.png |
| public | /admin/trainer-prediction-monitor?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_trainer-prediction-monitor_role_admin.png |
| public | /admin/signal-explainability?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_signal-explainability_role_admin.png |
| public | /admin/signals?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_signals_role_admin.png |
| public | /admin/executions?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_executions_role_admin.png |
| public | /admin/paper-trading?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_paper-trading_role_admin.png |
| public | /admin/risk-control?role=admin | PASS | True | False | True | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_risk-control_role_admin.png |
| public | /admin/live-readiness?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_live-readiness_role_admin.png |
| public | /admin/script-registry?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_script-registry_role_admin.png |
| public | /admin/claude-admin-ai?role=admin | PASS | True | False | False | True | claude_worklog/final_readiness/current_data_migration_sprint/latest/screenshots/public/public__admin_claude-admin-ai_role_admin.png |
