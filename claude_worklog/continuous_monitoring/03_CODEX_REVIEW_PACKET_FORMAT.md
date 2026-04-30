# 03 Codex Review Packet Format

## Purpose
Gate-oriented packet format for Codex to verify implementation and schema correctness.

## Packet schema (required)
- `review_packet_id`
- `gate_name`
- `generated_ts_utc`
- `input_packet_ids[]`
- `schema_checks[]`
- `lineage_checks[]`
- `threshold_checks[]`
- `contract_violations[]`
- `verification_commands[]`
- `evidence_pointer[]`
- `review_result` (`pass`, `conditional_pass`, `fail`)
- `confidence_level`

## Mandatory checks
- ID chain correctness (`feature_snapshot_id` -> `prediction_id` -> `signal_id` -> `decision_id` -> `risk_decision_id` -> `execution_intent_id`).
- Explainability field presence for confidence decisions.
- Heartbeat key-type compliance (no WRONGTYPE).
- Redis memory threshold policy classification consistency.
- Stream divergence checks (executions continue while signal stream appears empty).

## Gate timing
- Pre-release observability gate.
- Weekly schema drift gate.
- Incident-response gate on critical alerts.
