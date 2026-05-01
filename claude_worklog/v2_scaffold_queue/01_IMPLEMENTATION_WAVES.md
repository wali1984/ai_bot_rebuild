# 01 — V2 Scaffold Implementation Waves

This file is normative for wave sequencing. It is consumed by the
supervisor wave dispatcher and by Codex during queue review. All 015X
tasks remain `blocked_approval` until both remediation gates read green
**and** an authorized human approver flips the task status.

Wave order is derived from
`../v2_architecture/17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md`:
foundation → audit ledger → risk gateway → orchestrator → monitor / GUI.

## Waves

### W1 — Foundation
- **Members:** 015a (V2 foundation scaffold)
- **Requires:** —
- **Forbidden_until:** —
- **Exit gate:** 015a `audit_evidence.confidence ∈ {high, medium}`,
  `gate_evidence_ref` length == 8, `observability.summary_json_required = true`.

### W2 — Control plane + Audit ledger (parallel)
- **Members:** 015b (control-plane API scaffold), 015c (audit ledger scaffold)
- **Requires:** W1 exit gate green
- **Forbidden_until:** `015a.status == "merged"` and
  `015a.audit_evidence.confidence != "low"`
- **Exit gate:** 015b and 015c each satisfy the eight-item
  `gate_evidence_ref` floor and the canonical `audit_evidence` schema in
  `03_SCAFFOLD_BUILD_GUARDRAILS.md`.

### W3 — Risk gateway
- **Members:** 015d (risk gateway scaffold)
- **Requires:** 015a, 015b, 015c (audit-ledger green)
- **Forbidden_until:** `015c.audit_evidence.confidence != "low"`
  *(B4 fix: no risk-gateway scaffold lands without an audit-ledger sink.)*
- **Exit gate:** 015d eight-item `gate_evidence_ref`, normalized
  `audit_evidence`, and observability `summary.json` produced.

### W4 — Monitor + GUI shell (parallel)
- **Members:** 015e (monitor center scaffold), 015f (GUI shell scaffold)
- **Requires:** 015a, 015b, 015c, 015d
- **Forbidden_until:** `015d.audit_evidence.confidence != "low"`
- **Exit gate:** Both tasks satisfy the canonical schemas; Monitor Center
  shell ingests `summary.json` from 015a–015d.

## B2 / B4 sequencing remediation summary

- B2: 015a strictly precedes any consumer of foundation scaffolds. Wave
  membership and `forbidden_until` rules in W2 enforce this.
- B4: Audit-ledger scaffold (015c) is a hard predecessor of risk-gateway
  scaffold (015d). W3 `forbidden_until` rule enforces this.

## Out of scope for this file

- Implementation work under `v2/**` (none authored in this remediation cycle).
- Status transitions for 015A–015F (remain `blocked_approval`).
