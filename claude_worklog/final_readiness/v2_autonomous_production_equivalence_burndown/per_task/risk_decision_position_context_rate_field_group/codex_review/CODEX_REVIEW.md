# Codex Review: V2 Full-Observation Position-Context Risk-Decision Rate Field Group

Generated: `2026-05-23T00:55:07Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_CONTEXT_RISK_DECISION_RATE_FIELD_GROUP_CODEX_PASS`

## Decision

Codex passes tasks 215, 217, 219, and 221. The pending implementation
stall was real: the controller had emitted task descriptors, but no worker
had consumed them. Codex took over the exact-source work, fixed the
remaining field boundary, and reviewed the result.

The three `v2_*_rate` fields now consume only `v2:risk:decisions`. They no
longer use the raw-paper history aggregator. `position_context.churn_blocked`
was already covered by the grouped risk-decision helper and remains
exact-source.

This review does not approve live trading, canary trading, exchange
mutation, leverage/margin changes, Redis trim, approval creation,
checkpoint compatibility, policy architecture parity, production
equivalence, or legacy shutdown.

## Task Decisions

| Task | Field | Decision |
| --- | --- | --- |
| `215` | `position_context.churn_blocked` | `V2_FULL_OBSERVATION_POSITION_CONTEXT_CHURN_BLOCKED_CODEX_PASS` |
| `217` | `position_context.v2_pre_trade_allowed_rate` | `V2_FULL_OBSERVATION_POSITION_CONTEXT_V2_PRE_TRADE_ALLOWED_RATE_CODEX_PASS` |
| `219` | `position_context.v2_fee_gate_allowed_rate` | `V2_FULL_OBSERVATION_POSITION_CONTEXT_V2_FEE_GATE_ALLOWED_RATE_CODEX_PASS` |
| `221` | `position_context.v2_churn_blocked_rate` | `V2_FULL_OBSERVATION_POSITION_CONTEXT_V2_CHURN_BLOCKED_RATE_CODEX_PASS` |

## Exact Source Boundary

Reviewed fields consume only:

- `v2:risk:decisions`

The `_risk_rate(...)` path computes per-symbol rates from matching
risk-decision rows and emits:

- `V2_RISK_DECISIONS` when sourced;
- `MISSING_FROM_V2_RISK_DECISIONS` when the payload is absent;
- `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW` when no row exists for the
  symbol;
- `MISSING_FROM_V2_RISK_DECISIONS_FIELD_<FIELD>` when the row exists but
  the requested field is absent or `None`.

The raw-paper context field list was corrected so the three `v2_*_rate`
fields are no longer classified as raw paper context. Raw paper
block-reason counters remain separate.

## Runtime Evidence

Current `v2:risk:decisions` contains BTCUSDT, ETHUSDT, and SOLUSDT rows.
Direct builder proof showed all reviewed fields sourced from
`V2_RISK_DECISIONS`:

- `position_context.churn_blocked=0.0`
- `position_context.v2_pre_trade_allowed_rate=1.0`
- `position_context.v2_fee_gate_allowed_rate=1.0`
- `position_context.v2_churn_blocked_rate=0.0`

for each current symbol.

Refreshed status:

- BTCUSDT: `224 / 1687`
- ETHUSDT: `224 / 1687`
- SOLUSDT: `224 / 1687`
- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

`FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.

## Validation

- Focused portfolio-state tests: `34 passed`.
- Focused portfolio-state plus tracker-only tests: `44 passed`.
- Full-observation regression sweep: `144 passed`.
- Full-observation status refresh: PASS.
- Remaining-dim queue refresh: PASS, aggregate reconciles to `5733`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_FULL_OBSERVATION_POSITION_CONTEXT_RISK_DECISION_RATE_FIELD_GROUP_CODEX_PASS`

