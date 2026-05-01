# Autonomous Decision Policy

Decision levels:
- L0 observe: automatic
- L1 docs/plans/reviews: automatic
- L2 rebuild-local non-live code: automatic after Codex/guardrail checks
- L3 local operational changes: require policy preapproval
- L4 trading-impacting/staged/live-adjacent: human approval
- L5 live exchange/trading/margin/leverage/order actions: human-only, never autonomous

Autonomous stop conditions:
- secrets detected
- unclear live impact
- missing gate
- Codex fail
- auth failure
- quota block
- legacy mutation risk

AUTONOMOUS_DECISION_POLICY_READY
