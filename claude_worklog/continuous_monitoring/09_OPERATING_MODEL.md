# 09 Operating Model

## Roles
- Monitor process: produces raw facts and structured packets.
- Claude: reviews hourly/daily/alert packets and publishes operational interpretation.
- Codex: validates schema/implementation at defined gates.
- Human operator: approves any changes; enforces no-mutation safety boundary.

## Cadence
- Continuous local monitoring: 24/7, read-only.
- Hourly Claude packet review.
- Daily summary review and trend analysis.
- Immediate alert packet review on threshold breaches.
- Codex gate review on implementation/schema checkpoints.

## Escalation model
- WARN: monitor and annotate.
- HIGH: open evidence-backed incident note.
- CRITICAL: immediate triage with verification commands and freeze on non-essential change activity.

## Token-efficiency strategy
- Models consume compact packet summaries, not raw minute-level logs.
- Raw evidence is referenced by pointers and loaded only when anomaly justification is needed.

## Governance constraints
- No direct live-system mutation from monitoring workflow.
- No V2 build progression until remediation criteria pass.
