# Codex Review: V2 Full-Observation Risk-Decision Rate And Churn Context Field Group

Generated: `2026-05-23T01:07:30Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_CONTEXT_RISK_DECISION_RATE_AND_CHURN_CONTEXT_FIELD_GROUP_CODEX_PASS`

## Decision

Codex passes tasks `215`, `217`, `219`, and `221`. The reviewed
position-context fields now consume only the exact selected source key,
`v2:risk:decisions`, with explicit missing-row and missing-field labels.
No fallback to paper, orchestrator, trainer, legacy Redis, or old current
truth is used.

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

Reviewed implementation:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py`
- task descriptors `214` through `221`
- per-task implementation reports and Codex markers
- refreshed full-observation and remaining-dim queue payloads

The reviewed fields use only:

- `v2:risk:decisions`

`position_context.churn_blocked` is projected from the matching
per-symbol risk row via `_risk_field_source(...)`. It is not inferred
from held intents, paper-fill state, orchestrator state, trainer state,
or raw paper context.

The three rate fields use `_risk_rate(...)`, which computes a per-symbol
true-rate only from matching `v2:risk:decisions` rows:

- payload absent -> `None / MISSING_FROM_V2_RISK_DECISIONS`
- symbol row absent -> `None / MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW`
- field absent or `None` -> `None / MISSING_FROM_V2_RISK_DECISIONS_FIELD_<FIELD>`
- field present -> numeric rate / `V2_RISK_DECISIONS`

Rates are not fabricated when there is no denominator. Missing values are
not zero-filled.

## Runtime Evidence

Current `v2:risk:decisions` has BTCUSDT and ETHUSDT rows and no SOLUSDT
row. Direct builder proof showed:

- BTCUSDT and ETHUSDT:
  - `position_context.churn_blocked=0.0 / V2_RISK_DECISIONS`
  - `position_context.v2_pre_trade_allowed_rate=1.0 / V2_RISK_DECISIONS`
  - `position_context.v2_fee_gate_allowed_rate=1.0 / V2_RISK_DECISIONS`
  - `position_context.v2_churn_blocked_rate=0.0 / V2_RISK_DECISIONS`
- SOLUSDT:
  - all four reviewed fields are `None / MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW`

Refreshed full-observation status remains honest partial progress:

| Symbol | Generated | Missing |
| --- | ---: | ---: |
| `BTCUSDT` | `224` | `1687` |
| `ETHUSDT` | `224` | `1687` |
| `SOLUSDT` | `215` | `1696` |

`FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.

## Queue Follow-Up

Codex also corrected the remaining-dim classifier so already-implemented
risk-decision missing payload/row/field states are classified as
`V2_LANE_EXISTS_PAYLOAD_ABSENT`, not fresh `V2_BUILDABLE_NOW` code work.

After refresh:

- `V2_BUILDABLE_NOW=0`
- next-10 feature tasks: `[]`
- aggregate total still reconciles to `5733`

The autonomous controller now reports
`V2_OBSERVATION_BUILDABLE_QUEUE_EXHAUSTED_NEXT_GATE_READY`.

## Safety

Codex verified:

- no generic `v2:*` source hint in the reviewed implementation;
- no legacy current-truth key for these fields;
- no old Redis write path in the reviewed builder/controller path;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or
  test-order mutation path;
- no live/canary/shutdown/Redis-trim approval drift;
- `zero_filled_field_count=0`;
- `no_zero_fill_for_unknown_fields=true`;
- `checkpoint_compatibility_claimed=false`;
- `policy_architecture_parity_claimed=false`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`.

## Validation

- Focused portfolio-state tests: `40 passed`.
- Full-observation status refresh: PASS.
- Direct current-Redis risk-field proof: PASS.
- Remaining-dim classifier refresh: PASS, `V2_BUILDABLE_NOW=0`.
- Task descriptor JSON validation: PASS.
- Controller bounded loop: PASS, no new tasks emitted.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_FULL_OBSERVATION_POSITION_CONTEXT_RISK_DECISION_RATE_AND_CHURN_CONTEXT_FIELD_GROUP_CODEX_PASS`
