# 08 Risk Gateway and Live-Block Review

## Scope
Verify Risk Gateway is final authority and live trading is blocked by default.

## Inputs
- Architecture: 01, 05, 09, 10, 12, 17
- Requirements: 13, 14, 15, 17, 19, 20

## Final-authority guarantee
- Architecture 12: "Risk Gateway is final authority for execution allow/block."
- Architecture 12: "No trader/fleet/exchange path may bypass Risk Gateway."
- Architecture 10: "Risk Gateway remains final authority for allow/block of execution intents."
- Requirement 13: "Trader cannot bypass Risk Gateway."
- Requirement 14: "Risk Gateway enforces final trade allow/block regardless of rollout status."
- Requirement 17: "Risk Gateway remains final trade authority; bypass is non-compliant."
- Requirement 19: "Risk Gateway remains the final authority even after selection/admission."

The non-bypass guarantee is repeated in seven artifacts. Consistency is high.

## Mandatory controls
Architecture 12 enumerates the mandatory control set:
- stale signal block
- missing attribution block
- duplicate execution block
- leverage/margin block
- stop policy block
- daily/weekly loss gate
- kill switch
- position sizing
- reduceOnly enforcement
- live trading gate

These cover the high-risk failure modes identified in legacy forensic findings.

## Lineage prerequisite
Risk Gateway evaluates a `decision_id` and emits a `risk_decision_id`. Database schema 03 enforces this as FK from `risk_decisions` → `orchestrator_decisions`. Missing lineage is a hard validation failure (requirement 01).

## Live trading blocked-by-default
- Architecture 01: "Live trading blocked by default."
- Architecture 05: "Live mutation routes return blocked status by default until readiness gates pass."
- Architecture 09: live mutation methods (`create_order/cancel_order/set_leverage/set_margin_mode`) blocked until gates pass.
- Architecture 12: "live trading gate" is a mandatory control.
- Architecture 17: live mode is the last sequence step (O), only after explicit readiness GO + human approvals.
- Requirement 17: "Default state is live-disabled until explicit readiness GO + approvals."
- Requirement 20: L5 (enable live trading) is permanently non-autonomous.

The block is declared at API, connector, gateway, sequence, governance, and product-requirement layers. No autonomy override exists.

## Approval and audit linkage
- Live readiness page (06 + requirement 16) is the only path to live unlock; admin-only controls; all mandatory gates must pass.
- `approvals` table (03) records every required approval.
- `ai_action_changes.approval_state` blocks autonomous L5 actions.
- `audit_events` records every gate override.

## Risks and notes
- Architecture 12 is concise (25 lines). Build-phase must specify policy bundle schema, evaluation order, deterministic timeouts, and circuit-breaker behavior.
- Stale-signal definition (e.g., max age in ms) is not numerically fixed at architecture phase; this is acceptable but must be encoded as configurable risk policy with default = block.

## Verdict
Risk Gateway final authority and default-blocked live trading are firmly anchored across the architecture and requirement set. No bypass path exists in the documented design.
