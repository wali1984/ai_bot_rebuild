# 2X External Manual Position Quarantine

- marker: `2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_READY`
- generated_at: `2026-05-09T00:00:00Z`
- live_gate_status: `blocked_human_only`
- classification_count: 7
- manual_external_count: 2
- quarantined_count: 5
- unattributed_execution_count: 1
- duplicate_accounting_candidate_count: 2

## Operator Interpretation

V2 must not assume ownership of manual, exchange-side protective, unknown, or
duplicate-accounted positions. Those rows are quarantined and restricted to
monitor-only state until explicit human reconciliation exists.

## Required Artifacts

- `2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_REPORT.md`
- `GO_NO_GO.md`
- `ownership_classification_schema.json`
- `manual_external_positions.json`
- `quarantined_positions.json`
- `unattributed_executions.json`
- `duplicate_accounting_candidates.json`
- `risk_gateway_quarantine_rules.md`
- `operator_dashboard_payload.json`
- `evidence_manifest.json`
- `data_gaps.md`
