# Burndown Task 214 — position_context.churn_blocked

Generated: `2026-05-23T00:55:07Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_CONTEXT_CHURN_BLOCKED_BURNDOWN_READY_PARTIAL_PROGRESS`

Exact source: `v2:risk:decisions`.

The field was already implemented by the grouped risk-decision exact-source
patch. It is emitted from `_build_position_context_slice(...)` using only
the matched `risk_decisions` row for the current symbol and the shared
`_risk_field_source(...)` helper. Missing payload, missing symbol row, and
missing field states remain explicit. No paper, orchestrator, trainer,
prediction, tracker, or legacy fallback is used.

Validation:

- focused portfolio-state tests: `34 passed`
- full-observation regression sweep: `144 passed`
- `zero_filled_field_count=0`
- checkpoint compatibility: false
- policy architecture parity: false
- live gate: `blocked_human_only`
- live symbols: `[]`

