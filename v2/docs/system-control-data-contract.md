# System Control Data Contract

Generated: 2026-06-04

Every important frontend number should carry or derive evidence:

- `source`
- `source_type`
- `endpoint`
- `ingestor_id` or `service_id`
- `timestamp` or `generated_at`
- `received_at` when available
- `lag_ms` or derived age
- stale/error state
- calculation or formula when computed
- `model_version`, `run_id`, or `job_id` where applicable
- `strategy_id` where applicable
- `order_id` or `trade_id` where applicable
- `audit_id` for actions

Frontend behavior:

- Missing fields render as `missing source`, `missing endpoint`, or `missing telemetry field`.
- Historical/static proof artifacts are not rendered as current truth.
- Frontend-only fake controls are not allowed.
- Disabled controls must state the missing backend endpoint or authorization/audit reason.

System action contract before enabling any control:

- Role authorization.
- Confirmation for destructive or capital-affecting actions.
- Operator reason/comment.
- Dry-run preview when supported.
- Typed backend request/response.
- Audit-ledger write with action, actor, reason, result, and source payload IDs.

Current unsupported controls:

- Live trading enablement.
- Canary approval.
- Exchange order submit/cancel/modify.
- Leverage or margin mutation.
- Flatten/cancel-all against a real account.
- Legacy restart or old Redis mutation.

These remain unavailable until backend endpoints and audit contracts exist and the live gate changes through a separate human approval process.
