# Claude/Codex Runtime Improvement Ledger

| improvement | classification | evidence | GUI visibility |
|---|---|---|---|
| CoinAnk Plan-3 remediation | runtime_operational | v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json | Market Intelligence / Monitor Center / Mission Control |
| always-on runner | control_plane_operational | claude_worklog/tools/always_on_objective_runner.py | Mission Control / Build Validation |
| non-drift lock | control_plane_operational | claude_worklog/final_readiness/non_drift_governor_lock/latest | Mission Control |
| canonical paper runtime truth bridge | runtime_operational | v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json | Mission Control / Paper Trading / Signals / Executions |
| risk gateway runtime expansion | runtime_operational | claude_worklog/final_readiness/risk_gateway_runtime_expansion/latest | Risk Control / Live Readiness |
| script migration backlog | backlog_only | claude_worklog/final_readiness/script_migration_backlog/latest/script_migration_backlog.json | Script Registry |
| P0 execution attribution normalizer | runtime_operational | v2/backend/app/composition/execution_attribution_normalizer/runtime.py | /admin/executions?role=admin |
| P1 current signal lineage adapter | runtime_operational | v2/backend/app/composition/current_signal_lineage_adapter/runtime.py | /admin/signal-explainability?role=admin |
| website current data repair | website_visibility_improved | v2/frontend/src/components/layout/PageShell.tsx | Signals / Executions / required routes |
