# Grouped burndown — v2:risk:decisions exact-source field group

GO/NO-GO: `V2_FULL_OBSERVATION_RISK_DECISION_EXACT_SOURCE_FIELD_GROUP_READY`

Six exact-source `V2_BUILDABLE_NOW` tasks (controller-emitted descriptors
202 / 204 / 206 / 208 / 210 / 212) implemented in one grouped patch
because they all consume the same exact V2 Redis key
**`v2:risk:decisions`**.

| Task descriptor | Field group | Field |
|---|---|---|
| 202 | portfolio_state | portfolio_symbol_risk_decision_present |
| 204 | portfolio_state | portfolio_symbol_pre_trade_allowed |
| 206 | portfolio_state | portfolio_symbol_fee_gate_allowed |
| 208 | portfolio_state | portfolio_symbol_churn_blocked |
| 210 | position_context | pre_trade_allowed |
| 212 | position_context | fee_gate_allowed |

(`position_context.churn_blocked` shares the same projection and is
covered by the same helper / tests for honesty consistency.)

## Change in [v2/backend/app/services/rl_core/full_observation_builder.py](../../../../../../v2/backend/app/services/rl_core/full_observation_builder.py)

1. New helper `_risk_field_source(...)` returns the explicit source
   label for each runtime state:
   - `MISSING_FROM_V2_RISK_DECISIONS` — Redis key absent (publisher off).
   - `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW` — payload present but
     no row whose `symbol` matches.
   - `MISSING_FROM_V2_RISK_DECISIONS_FIELD_<GATE>` — row matched but
     the per-field key is None / absent.
   - `V2_RISK_DECISIONS` — sourced.
2. `_build_portfolio_state_slice` switched its four risk-decision rows
   to use `_risk_field_source(risk_decisions=risk_decisions, …)` so the
   source label is correct in every state. Crucially, the helper
   receives the *raw* `risk_decisions` parameter (not the `rd or []`
   defaulted list) so the "Redis key absent" state is distinguishable
   from "Redis key present but list empty".
3. `_build_position_context_slice` switched its three risk-decision
   rows (`pre_trade_allowed`, `fee_gate_allowed`, `churn_blocked`) to
   the same helper.
4. `portfolio_symbol_risk_decision_present`: now emits 0.0 with source
   `V2_RISK_DECISIONS_NO_SYMBOL_ROW` when the publisher is up but has
   no row for this symbol (derivable evidence, not a fabricated gate).
   When the Redis key is absent entirely, the field stays `None` with
   `MISSING_FROM_V2_RISK_DECISIONS`.
5. No fallback to paper / orchestrator / trainer / prediction / legacy
   keys. No zero-fill. The helper never returns `0.0` for any of the
   per-gate fields; values stay `None` when the underlying truth is
   not on the payload.

## Change in [tools/v2_full_observation_remaining_dim_classifier.py](../../../../../../tools/v2_full_observation_remaining_dim_classifier.py)

Added entries to `SOURCE_TO_CATEGORY` so all four refined risk-decision
missing labels classify as `V2_BUILDABLE_NOW`:

- `MISSING_FROM_V2_RISK_DECISIONS`
- `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW`
- `MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED`
- `MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED`
- `MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED`

Aggregate total continues to reconcile to 5733; strict-source contract
pass remains True; queue GO/NO-GO remains
`V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`.

## Tests

Added to [v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py](../../../../../../v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py):

- `test_risk_decision_field_group_sources_only_from_v2_risk_decisions` —
  golden-path sourcing for all six fields.
- `test_risk_decision_field_group_payload_absent_emits_payload_missing_label` —
  payload-absent state: every per-gate field emits `MISSING_FROM_V2_RISK_DECISIONS`;
  `risk_decision_present` stays `None` with the same label.
- `test_risk_decision_field_group_no_symbol_row_emits_symbol_row_missing_label` —
  payload present but no matching row: `risk_decision_present` =
  `(0.0, "V2_RISK_DECISIONS_NO_SYMBOL_ROW")`; per-gate fields emit
  `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW`.
- `test_risk_decision_field_group_per_field_missing_label_when_row_present_but_field_none` —
  row matched but gates are None: per-field MISSING labels are emitted
  per-field (FIELD_PRE_TRADE_ALLOWED / FIELD_FEE_GATE_ALLOWED /
  FIELD_CHURN_BLOCKED).
- `test_risk_decision_field_group_does_not_fall_back_to_paper_or_orchestrator` —
  even when paper / orchestrator / trainer / prediction payloads carry
  truthy gate values, the risk-decision fields must NOT borrow truth
  from them and must stay `(None, "MISSING_FROM_V2_RISK_DECISIONS")`.
- Six per-task named entry-point tests matching the supervisor task
  descriptors' `tests_required` lists:
  - `test_portfolio_symbol_risk_decision_present_true_when_row_present` /
    `…_missing_label_when_no_row`
  - `test_portfolio_symbol_pre_trade_allowed_truth_from_row` /
    `…_missing_label_when_no_row`
  - `test_portfolio_symbol_fee_gate_allowed_truth_from_row` /
    `…_missing_label_when_no_row`
  - `test_portfolio_symbol_churn_blocked_truth_from_row` /
    `…_missing_label_when_no_row`
  - `test_position_context_pre_trade_allowed_truth_from_row` /
    `…_missing_label_when_no_row`
  - `test_position_context_fee_gate_allowed_truth_from_row` /
    `…_missing_label_when_no_row`

Also extended the allowed-source set in
[test_v2_full_observation_position_history_tracker_only_consumption.py](../../../../../../v2/backend/tests/integration/cli/test_v2_full_observation_position_history_tracker_only_consumption.py)
so the new refined labels are explicitly in the canonical list.

Run:

```
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py -q
```

Result: **26 passed** (including the 4 grouped tests and the 12 per-task
named tests added for this group).

Regression sweep over all `full_observation` tests:

```
PYTHONPATH=$PWD .venv/bin/pytest v2/backend/tests/integration/cli/ \
  -k 'full_observation' -q
```

Result: **136 passed**.

## Runtime evidence

Per-symbol values after the patch (current Redis state):

| symbol | risk_decision_present | pre_trade_allowed | fee_gate_allowed | churn_blocked |
|---|---|---|---|---|
| BTC | (1.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) |
| ETH | (1.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) |
| SOL | (0.0, V2_RISK_DECISIONS_NO_SYMBOL_ROW) | (None, MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW) | (None, MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW) | (None, MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW) |

(`position_context.pre_trade_allowed` / `fee_gate_allowed` / `churn_blocked`
follow the same pattern.)

`full_observation_builder_status` after refresh:

| symbol | generated | missing | state |
|---|---:|---:|---|
| BTCUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| ETHUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| SOLUSDT | 215 | 1696 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |

SOL +1 generated dim — `portfolio_symbol_risk_decision_present` now
derives `0.0` honestly with the sourced "no symbol row" label.

Remaining-dim queue (refresh):

- aggregate_total_observed = 5733 (PASS)
- strict_source_contract_pass = True
- generic_source_hint_hits = 0
- portfolio_state_broad_bucket_emitted = False
- `V2_BUILDABLE_NOW` = 12 (was 13 before this patch)
- queue GO/NO-GO = `V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`.

## Safety

- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not stop V2 runtime / governor / observer / comparator / WSS daemon.
- Did not write any Redis key.
- Did not call any exchange endpoint.
- Did not create any live / canary / shutdown / Redis-trim approval token.
- Did not start policy architecture.
- Did not claim checkpoint compatibility.
- Did not claim policy architecture parity.
- `zero_filled_field_count` = 0 across all symbols.
- `live_gate` = `blocked_human_only`.
- `live_symbols` = `[]`.

## Follow-up

Per task instructions, the controller `--once` / `--loop` is NOT
invoked. The six paired Codex review descriptors
(`203`, `205`, `207`, `209`, `211`, `213`) remain pending under
`claude_worklog/agent_supervisor/tasks/` for Codex to verify exact-source
consumption, real generated-dim accounting, no-zero-fill, no claim
drift, and runtime safety.
