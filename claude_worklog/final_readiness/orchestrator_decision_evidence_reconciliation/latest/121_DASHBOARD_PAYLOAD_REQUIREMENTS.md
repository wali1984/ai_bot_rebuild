# 121 Dashboard Payload Requirements

Dashboard consumers must show:

- 121 status: `READY`
- supervised source task: `121_orchestrator_decision_2fb_evidence_reconciliation`
- source marker: `PHASE2F_B_EVIDENCE_RECONCILIATION_PASSED`
- orchestrator/risk boundary: orchestrator proposes; Risk Gateway is final authority
- full runtime chain gaps with exact text: `Evidence missing — cannot explain without guessing.`
- carried blockers:
  - `CODEX_RISK_GATEWAY_DEGRADED_STATE_FAIL`
  - `CODEX_REALTIME_MONITOR_COVERAGE_FAIL`
  - `CODEX_V2_DATA_PLANE_INDEPENDENCE_FAIL`
- Redis trim: `deferred_non_blocking`
- live gate: `blocked_human_only`
- human input required: `false_unless_final_live_capital_gate`

Do not label missing runtime chain evidence as live-ready.
