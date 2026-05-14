# Account Permission Contract Report

Generated: 2026-05-14T10:27:47Z
Live gate: `blocked_human_only`
Account evidence: `READONLY_ACCOUNT_EVIDENCE_PRESENT`
Trade permission: `TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY`
Margin evidence: `ISOLATED_MARGIN_EVIDENCE_PRESENT`
Leverage evidence: `LEVERAGE_CAP_EVIDENCE_PRESENT`
Mutation guard: `V2_ORDER_METHODS_FAIL_CLOSED`
Canary ready: `False`

Classifications:
- `READONLY_ACCOUNT_EVIDENCE_PRESENT`
- `TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY`
- `ISOLATED_MARGIN_EVIDENCE_PRESENT`
- `LEVERAGE_CAP_EVIDENCE_PRESENT`
- `V2_ORDER_METHODS_FAIL_CLOSED`
- `CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE`

Canary blockers:
- `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`
- `CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE`

Evidence sources:
- `claude_worklog/final_readiness/account_permission_and_soak/latest/operator_dashboard_payload.json`
- `v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json`
- `v2/frontend/public/operator_runtime/live_observer/latest/current_runtime_truth_payload.json`
- `v2/frontend/public/operator_runtime/paper_online/latest/risk_runtime_payload.json`
- `v2/frontend/public/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json`
- `v2/frontend/public/v2_live_observer_shadow_twin/latest/operator_dashboard_payload.json`

The checker reads public evidence only and does not call exchange mutation APIs.
