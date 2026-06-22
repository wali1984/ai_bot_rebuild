# Burndown Task 218 — position_context.v2_fee_gate_allowed_rate

Generated: `2026-05-23T00:55:07Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_CONTEXT_V2_FEE_GATE_ALLOWED_RATE_BURNDOWN_READY_PARTIAL_PROGRESS`

Exact source: `v2:risk:decisions`.

The field now computes the per-symbol true-rate for `fee_gate_allowed`
from matching rows in `v2:risk:decisions`. It no longer consumes raw
paper-intent history. Missing payload, missing symbol row, and missing
field states are explicit via `MISSING_FROM_V2_RISK_DECISIONS*` labels.
No paper, orchestrator, trainer, prediction, tracker, or legacy fallback is
used.

Validation:

- focused portfolio-state tests: `34 passed`
- full-observation regression sweep: `144 passed`
- `zero_filled_field_count=0`
- checkpoint compatibility: false
- policy architecture parity: false
- live gate: `blocked_human_only`
- live symbols: `[]`

