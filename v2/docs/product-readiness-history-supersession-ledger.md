# Product Readiness History Supersession Ledger

Generated: 2026-06-14

Purpose: identify historical status-history events whose wording has been superseded by later current-state evidence. This file does not rewrite history, does not prove validation, does not close blockers, and does not mark any route, phase, launch gate, admin security gate, `/trade`, `/market/:symbol`, paper/read-only release, or real live trading state complete.

Validation was not run after the latest guard/doc changes; conservative statuses remain authoritative.

Pending evidence key: `readiness_history_supersession_ledger_drift_guard_after_latest_changes`.

## Superseded history rows

| Historical event | Superseding event | Current evidence key | Current evidence status | Current interpretation |
|---|---|---|---|---|
| `trader_user_scope_enforcement` | `exchange_account_scope_requires_paper_account_hardened` | `trader_exchange_account_scope_normalization_after_latest_changes` | `PENDING` | Earlier wording that exchange-account metadata required trader scope is historical only; current exchange-account metadata must be scoped by both `trader_id` and `paper_account_id`, normalized read-only, and validation remains pending. |
