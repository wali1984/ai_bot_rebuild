# 13 Multi-Trader Fleet Requirements

## Requirement ID
V2-TRADER-FLEET-001

## Objective
Support many trader instances based on system capacity while preserving centralized safety authority.

## Fleet model requirements
- Trader fleet must be dynamically scalable (add/remove trader instances).
- Assignment and orchestration must support per-trader symbol scope and strategy profile.
- Risk Gateway remains final authority for allow/block decisions.

## Mandatory trader instance fields
- `trader_id`
- `account_id`
- `exchange_id`
- `strategy_profile`
- `symbol_scope`
- `risk_profile`
- `paper_live_mode`
- `assigned_symbols`
- `heartbeat`
- `pnl`
- `attribution_completeness`

## Fleet control requirements
1. Capacity-aware expansion
- Add traders based on CPU/memory/network and connector limits.

2. Assignment controls
- Symbol sharding and overlap policy.
- Manual and policy-driven rebalancing.

3. Mode controls
- Per-trader paper/live mode with default safe mode = paper/blocked.

4. Health and supervision
- Heartbeat SLA, stale detection, quarantine, recovery workflow.

5. Attribution and audit
- Per-trader attribution completeness score and lineage visibility.
- Full action audit trail per trader instance.

## Safety controls
- Trader cannot bypass Risk Gateway.
- Dangerous actions (live mode, leverage/margin policy changes) require admin approvals and gate checks.

## Pre-architecture acceptance
- Trader entity schema includes all mandatory fields.
- Fleet scaling and assignment policy documented.
- Risk Gateway authority rule is explicit and non-bypassable.
