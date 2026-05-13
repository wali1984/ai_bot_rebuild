# Live Blocker Burn-Down Report

Generated: `2026-05-13T05:46:26Z`

Full live remains `blocked_human_only`. This matrix burns down evidence blockers without creating live approval.

| blocker | status | evidence | GUI route | owner | next action |
|---|---|---|---|---|---|
| script migration incomplete | BLOCKED | claude_worklog/final_readiness/script_migration_backlog/latest/script_migration_backlog.json | /admin/script-registry?role=admin | primary_migration | Continue P0/P1 wrappers and ports. |
| trainer parity not fully proven | BLOCKED | claude_worklog/final_readiness/production_truth_reconciliation/latest/live_readiness_truth.json | /admin/trainer-prediction-monitor?role=admin | primary_trainer_parity | Prove legacy PPO/MASA parity through V2 bridge. |
| legacy still owns live execution | BLOCKED | operator runtime process snapshot / legacy bridge | /admin/executions?role=admin | primary_migration | Keep legacy read-only observed while V2 execution remains paper-only. |
| paper/shadow 6h/24h profitability proof missing | MISSING_EVIDENCE | v2/frontend/public/operator_runtime/paper_online/latest | /admin/paper-trading?role=admin | primary_paper_shadow | Persist 1h/6h/24h paper-shadow performance windows. |
| website current-data completeness | PASS | claude_worklog/final_readiness/current_data_migration_sprint/latest/website_current_data_matrix.json | /admin/mission-control?role=admin | support_ui | Keep route crawl/data-truth checks green. |
| read-only account verification missing | MISSING_EVIDENCE | final canary checklist | /admin/exchange-manager?role=admin | primary_live_gate | Add read-only account status payload before canary. |
| exchange trade permission unknown | MISSING_EVIDENCE | final canary checklist | /admin/exchange-manager?role=admin | primary_live_gate | Confirm trade permission state manually/read-only. |
| isolated margin verification missing | PASS | final canary profile + live canary blocker guard | /admin/live-readiness?role=admin | primary_risk | Keep isolated-only policy in guard. |
| leverage cap verification missing | PASS | final canary profile + live canary blocker guard | /admin/live-readiness?role=admin | primary_risk | Keep 1x cap unless human approval changes it. |
| stop/kill switch runtime proof | PASS | paper runtime current_risk_decision.required_blocks_checked | /admin/risk-control?role=admin | primary_risk | Continue runtime assertions. |
| daily/weekly loss gate runtime proof | MISSING_EVIDENCE | live canary blocker guard | /admin/risk-control?role=admin | primary_risk | Add weekly loss gate runtime evidence. |
| Admin AI cannot enable live | PASS | Claude Admin AI safety contract | /admin/claude-admin-ai?role=admin | support_ui | Keep Admin AI read-only/non-live. |
| dangerous controls disabled | PASS | browser audit and DangerousControlPanel | /admin/config-admin?role=admin | support_ui | Continue browser audits. |
| stale signal blocks | PASS | paper runtime risk required_blocks_checked | /admin/risk-control?role=admin | primary_risk | Keep stale-signal runtime tests. |
| missing attribution blocks | PASS | paper runtime risk required_blocks_checked | /admin/risk-control?role=admin | primary_risk | Continue attribution blocker tests. |
| duplicate execution dedupe | PASS | paper runtime risk required_blocks_checked + execution attribution normalizer | /admin/executions?role=admin | primary_migration | Feed dedupe state into V2 data plane. |
| old Redis write isolation | PASS | paper_runtime_status.json | /admin/build-validation-status?role=admin | primary_safety | Keep legacy Redis write ban. |
| V2 data-plane independence | BLOCKED | production truth reconciliation / live observer blockers | /admin/build-validation-status?role=admin | primary_data_plane | Enable V2 durable DB/bounded Redis only after safe config. |
