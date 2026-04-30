# 08 Hot-Reload Pipeline Architecture

## State flow
`proposed -> validated -> approved -> applied -> verified`

## Propagation targets
Hot-reload updates must apply to:
- ingestors
- feature pipeline
- trainer adapter
- orchestrator
- risk gateway
- trader fleet
- monitor
- GUI

## Required event envelope
- `universe_version`
- `change_set`
- `requested_by`
- `approval_chain`
- `evidence_pointers`
- `created_ts_ms`

## Component acknowledgments
Each component returns:
- `component_id`
- `applied_version`
- `ack_ts_ms`
- `validation_status`
- `rollback_ready`

## Rollback architecture
- Immediate rollback to prior verified version.
- Rollback is versioned, audited, and re-verified.

## Validation evidence
- Pre-apply checks
- Post-apply checks
- Component health checks
- Diff and impact summaries

## Operational constraint
- No routine full restart allowed for universe updates.
