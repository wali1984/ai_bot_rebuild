# 13 Audit Ledger and AI Change Governance

## AI governance levels
- L0 observe
- L1 docs/reports
- L2 safe V2 non-live config
- L3 operational non-trading
- L4 trading-impacting changes
- L5 dangerous live changes

## Mandatory AI change record
- `change_id`
- `actor`
- `reason`
- `evidence_pointers`
- `before_value`
- `after_value`
- `risk_level`
- `validation_result`
- `rollback_plan`
- `gui_explanation`
- `timestamp`
- `approval_state`

## Hard constraint
Level 5 is never autonomous.

## Ledger architecture
- Append-only audit model in DB.
- Cross-links to monitor packets, code/spec diffs, approvals, and rollback events.
- GUI transparency via AI Governance Console and Review Center.
