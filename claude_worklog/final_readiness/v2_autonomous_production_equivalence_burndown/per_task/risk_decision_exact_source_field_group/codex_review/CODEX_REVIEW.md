# Codex Review: V2 Full-Observation Risk-Decision Exact-Source Field Group

Generated: `2026-05-22T17:07:54Z`

GO/NO-GO: `V2_FULL_OBSERVATION_RISK_DECISION_EXACT_SOURCE_FIELD_GROUP_CODEX_PASS`

## Decision

Codex passes the grouped risk-decision exact-source implementation for
tasks 203, 205, 207, 209, 211, and 213. All six reviewed fields consume
only the exact selected source key, `v2:risk:decisions`, keep missing
states explicit, do not fall back to paper/orchestrator/trainer/prediction
payloads, and do not zero-fill unknown gate values.

This review does not approve live trading, canary trading, exchange
mutation, leverage/margin changes, Redis trim, approval creation,
checkpoint compatibility, policy architecture parity, production
equivalence, or legacy shutdown.

## Task Decisions

| Task | Field | Decision |
| --- | --- | --- |
| `203` | `portfolio_state.portfolio_symbol_risk_decision_present` | `V2_FULL_OBSERVATION_PORTFOLIO_STATE_SYMBOL_RISK_DECISION_PRESENT_CODEX_PASS` |
| `205` | `portfolio_state.portfolio_symbol_pre_trade_allowed` | `V2_FULL_OBSERVATION_PORTFOLIO_STATE_SYMBOL_PRE_TRADE_ALLOWED_CODEX_PASS` |
| `207` | `portfolio_state.portfolio_symbol_fee_gate_allowed` | `V2_FULL_OBSERVATION_PORTFOLIO_STATE_SYMBOL_FEE_GATE_ALLOWED_CODEX_PASS` |
| `209` | `portfolio_state.portfolio_symbol_churn_blocked` | `V2_FULL_OBSERVATION_PORTFOLIO_STATE_SYMBOL_CHURN_BLOCKED_CODEX_PASS` |
| `211` | `position_context.pre_trade_allowed` | `V2_FULL_OBSERVATION_POSITION_CONTEXT_PRE_TRADE_ALLOWED_CODEX_PASS` |
| `213` | `position_context.fee_gate_allowed` | `V2_FULL_OBSERVATION_POSITION_CONTEXT_FEE_GATE_ALLOWED_CODEX_PASS` |

## Scope Reviewed

Reviewed:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py`
- `tools/v2_full_observation_remaining_dim_classifier.py`
- `claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/per_task/risk_decision_exact_source_field_group/IMPLEMENTATION_REPORT.md`
- task descriptors `202` through `213`
- refreshed full-observation builder status payloads
- refreshed remaining-dim execution queue artifacts

## Exact Source Boundary

The reviewed fields are sourced from the `risk_decisions` argument only.
The status path reads that argument from exactly:

- `v2:risk:decisions`

The helper `_risk_field_source(...)` distinguishes:

- `MISSING_FROM_V2_RISK_DECISIONS` when the payload is absent;
- `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW` when the payload exists but
  has no matching symbol row;
- `MISSING_FROM_V2_RISK_DECISIONS_FIELD_<FIELD>` when the row exists but
  the selected field is absent or `None`;
- `V2_RISK_DECISIONS` when the field is actually sourced.

`portfolio_symbol_risk_decision_present` is the only special case: when
the `v2:risk:decisions` payload exists but has no row for the current
symbol, it emits `0.0 / V2_RISK_DECISIONS_NO_SYMBOL_ROW`. That is a
derivable sourced fact from the selected payload, not a fallback or
zero-fill.

Codex found no fallback from these reviewed fields to paper positions,
paper ledger, paper intents, orchestrator decisions, trainer heartbeat,
prediction payloads, legacy Redis keys, or old production keys.

## Runtime Evidence

Current Redis has `v2:risk:decisions` with two symbol rows. Direct builder
proof showed:

| Symbol | Generated | Missing | Risk Source State |
| --- | ---: | ---: | --- |
| `BTCUSDT` | `224` | `1687` | six reviewed fields sourced from `V2_RISK_DECISIONS` |
| `ETHUSDT` | `224` | `1687` | six reviewed fields sourced from `V2_RISK_DECISIONS` |
| `SOLUSDT` | `215` | `1696` | `risk_decision_present=0.0 / V2_RISK_DECISIONS_NO_SYMBOL_ROW`; five reviewed gate fields explicitly missing with `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW` |

The only generated-dimension increase in the current status is real:
SOLUSDT increased by one because `portfolio_symbol_risk_decision_present`
became a sourced no-symbol-row fact. Missing gate fields remain missing.

The refreshed full-observation status remains:

- `state=FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

`FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.

## Queue State

After refreshing the remaining-dim classifier:

- `go_no_go=V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`
- aggregate total observed: `5733`
- aggregate total check: `PASS`
- `strict_source_contract_pass=true`
- `generic_source_hint_hits=0`
- `portfolio_state_broad_bucket_emitted=false`
- `V2_BUILDABLE_NOW=12`

The queue remains exact-source and reconciled after the grouped
implementation.

## Safety

Codex verified:

- no Redis write call in the reviewed full-observation builder path;
- no old Redis write path;
- no legacy Redis current-truth key used for these reviewed fields;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or
  test-order mutation path;
- no live/canary/shutdown/Redis-trim approval drift;
- no checkpoint compatibility claim;
- no policy architecture parity claim;
- no policy architecture implementation started;
- no raw credential exposure in reviewed source, tests, task descriptors,
  or payloads.

Source-scan hits for approval, order, and legacy terms are safety fields,
comments, or unrelated V2 feature names, not executable mutations for this
reviewed path.

## Validation

- Focused portfolio-state burndown tests: `26 passed`.
- Broader full-observation regression sweep: `136 passed`.
- `py_compile` for builder and remaining-dim classifier: PASS.
- Full-observation status refresh: PASS.
- Remaining-dim classifier refresh: PASS.
- Direct current-Redis field-source proof: PASS.
- Missing-state behavior proof: PASS.
- No-fallback regression proof: PASS.
- Zero-fill invariant: PASS.
- Partial-status invariant: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_FULL_OBSERVATION_RISK_DECISION_EXACT_SOURCE_FIELD_GROUP_CODEX_PASS`
