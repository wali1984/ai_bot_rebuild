# Claude / Codex Improvement Ledger

Generated: 2026-05-13T04:43:38.228869Z

This ledger separates runtime-operational changes from documentation, visibility, and backlog work.

| Improvement | Class | Commit | Validation | Runtime effect |
| --- | --- | --- | --- | --- |
| CoinAnk Plan-3 remediation | runtime_operational | 4cb00e0 | COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_CODEX_PASS | V2 market intelligence can read current LIVE_COINANK_READONLY payloads. |
| Always-on runner | control_plane_operational | 40d46fd | ALWAYS_ON_CLAUDE_CODEX_RUNTIME_CODEX_PASS | Selects non-live tasks after final live gate instead of live dispatch. |
| Non-drift governor lock | control_plane_operational | 1af9dd5 | CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_CODEX_PASS | Primary chain remains V2 paper/shadow, bridge, risk, trainer, migration. |
| Canonical paper runtime truth bridge | runtime_operational | 6714e00 | paper runtime payload current in this reconciliation | Current pred/fs/sig/risk/intent IDs are available as runtime truth. |
| Supervisor persistence and active dispatch proof | control_plane_operational | f1f0632 | ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_CODEX_PASS | Idle cause is classified and dispatch lanes are explicit. |
| Risk gateway runtime expansion | paper_shadow_only | 56103a7 | RISK_GATEWAY_RUNTIME_EXPANSION_TESTS_READY | Paper runtime checks missing lineage, stale signals, leverage, stop policy, kill switch. |
| Script migration backlog | backlog_only | f1f0632 | SCRIPT_MIGRATION_BACKLOG_READY | Creates migration inventory but not actual migration completion. |
| Public hosting telemetry bridge | website_visibility_improved | 56103a7 | PUBLIC_HOSTING_AND_TELEMETRY_BRIDGE_READY | Public dashboard is reachable, but current-data visibility still requires repair. |
| Final approval packet | documentation_only | 56103a7 | FINAL_LIVE_CAPITAL_GATE_CODEX_PASS | Human-only tiny canary packet exists, approval token absent. |
