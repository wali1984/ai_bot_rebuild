# Next Tasks By Lane

Generated: 2026-05-12T23:07:37.561845+00:00

Primary Claude lane:

- Selected task: `SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX`
- Why: Website rebuild passed; legacy execution containment proof exists; trainer runtime/parity remains the active primary blocker.
- Autonomous: yes
- Human approval: no, unless final live/capital gate.

Codex parallel lane:

- Selected audits: `codex_audit_no_live_side_effects, codex_audit_current_runtime_truth, codex_audit_risk_gateway_fail_closed, codex_audit_trainer_parity_truth, codex_audit_legacy_bridge_readonly, codex_audit_public_dashboard_truth, codex_audit_script_migration_coverage, codex_audit_v2_data_plane_independence`
- Autonomous: yes
- Human approval: no.

Website support lane:

- Selected task: `none_unless_regression`
- Why: public/local crawl already passed.
- Autonomous: no UI-only work while primary chain is incomplete.

Blocked decision packets:

- Redis trim approval: deferred/non-blocking.
- Final live/capital approval: blocked_human_only.
- Legacy trader containment action: decision packet if action required.
