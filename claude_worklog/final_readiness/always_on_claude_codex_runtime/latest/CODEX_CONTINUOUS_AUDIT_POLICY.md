# Codex Continuous Audit Policy

Generated: 2026-05-13T03:04:28.450818+00:00

## Lanes
- codex_audit_no_live_side_effects
- codex_audit_current_runtime_truth
- codex_audit_risk_gateway_fail_closed
- codex_audit_trainer_parity_truth
- codex_audit_legacy_bridge_readonly
- codex_audit_public_dashboard_truth
- codex_audit_script_migration_coverage
- codex_audit_v2_data_plane_independence
- codex_audit_documentation_completeness
- codex_audit_coinank_bridge_contract
- codex_audit_config_admin_dangerous_controls
- codex_audit_paper_shadow_performance

## Codex May
- Audit current runtime truth and safety.
- Create remediation task recommendations.
- Autofix V2 non-live code with tests when scoped and safe.
- Validate artifacts, payloads, data truth, risk fail-closed behavior, and website support visibility.

## Codex May Not
- Enable live trading.
- Mutate the legacy bot.
- Write old Redis.
- Place or cancel orders.
- Change leverage or margin.
- Approve final live/capital gate.
