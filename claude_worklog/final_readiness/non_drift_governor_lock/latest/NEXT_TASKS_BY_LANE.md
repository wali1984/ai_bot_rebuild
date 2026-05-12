# Next Tasks By Lane

Generated: 2026-05-12T22:13:28.364526+00:00

Primary Claude lane:

- Selected task: `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK`
- Why: Website rebuild passed; primary chain still has trainer runtime/parity and legacy execution containment blockers.
- Autonomous: yes
- Human approval: no, unless final live/capital gate.

Codex parallel lane:

- Selected audits: `codex_audit_no_live_side_effects, codex_audit_current_runtime_truth, codex_audit_risk_gateway_fail_closed, codex_audit_trainer_parity_truth, codex_audit_public_dashboard_truth, codex_audit_legacy_bridge_readonly`
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
