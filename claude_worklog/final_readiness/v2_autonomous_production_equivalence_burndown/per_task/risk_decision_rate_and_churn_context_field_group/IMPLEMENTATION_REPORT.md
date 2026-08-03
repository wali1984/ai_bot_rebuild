# Grouped burndown — v2:risk:decisions rate-and-churn context field group

GO/NO-GO: `V2_FULL_OBSERVATION_RISK_DECISION_RATE_AND_CHURN_CONTEXT_FIELD_GROUP_READY`

Four exact-source `V2_BUILDABLE_NOW` tasks (descriptors 214 / 216 / 218 / 220)
implemented as one grouped patch. All four consume the same exact V2
Redis key **`v2:risk:decisions`**.

| Task descriptor | Field |
|---|---|
| 214 | position_context.churn_blocked |
| 216 | position_context.v2_pre_trade_allowed_rate |
| 218 | position_context.v2_fee_gate_allowed_rate |
| 220 | position_context.v2_churn_blocked_rate |

## Code state

The four fields already use only `v2:risk:decisions` via two
well-bounded helpers in
[v2/backend/app/services/rl_core/full_observation_builder.py](../../../../../../v2/backend/app/services/rl_core/full_observation_builder.py):

- `_risk_field_source(risk_decisions=…, symbol_row=…, field=…)`
  for `position_context.churn_blocked` (task 214). Returns:
  - `MISSING_FROM_V2_RISK_DECISIONS` when the Redis key is absent;
  - `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW` when payload is present
    but no row matches the symbol;
  - `MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED` when the row
    matches but `churn_blocked` is None;
  - `V2_RISK_DECISIONS` when sourced.
- `_risk_rate(field)` (inside `_extract_raw_paper_context_fields`) for
  the three rate fields (216 / 218 / 220). Iterates only the matched
  symbol rows of `v2:risk:decisions`. Returns:
  - `MISSING_FROM_V2_RISK_DECISIONS` when `risk_decisions is None`
    (Redis key absent);
  - `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW` when no row matches
    this symbol;
  - `MISSING_FROM_V2_RISK_DECISIONS_FIELD_<FIELD>` when row(s) match
    but no row has a non-None value for the field — explicitly NOT
    `0.0` (no fake rate);
  - `V2_RISK_DECISIONS` with `allowed / count` when at least one
    field-truth value exists.

No fallback to paper / orchestrator / trainer / prediction / legacy
keys. No zero-fill. The aggregator is called with empty
`paper_positions=[]`, `position_price_track=None`,
`position_history=None` so the rate fields cannot accidentally borrow
truth from tracker payloads.

## Tests

Added to [v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py](../../../../../../v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py):

- `test_rate_and_churn_context_payload_absent_emits_payload_missing_label`
  — all four fields stay `None` with `MISSING_FROM_V2_RISK_DECISIONS`.
- `test_rate_and_churn_context_no_symbol_row_emits_symbol_row_missing_label`
  — publisher has rows for ETH only; BTC fields stay
  `MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW`.
- `test_rate_and_churn_context_per_field_missing_label_when_field_none`
  — row matches but gates are None: per-field MISSING labels emitted.
- `test_rate_and_churn_context_does_not_fall_back_to_paper_or_orchestrator`
  — truthy paper / orchestrator / trainer / prediction / paper-intent
  signals do NOT cause the four fields to source.
- `test_rate_fields_do_not_fake_zero_when_no_field_truth` — the explicit
  "no fake 0.0 rate" assertion: per-field MISSING label, value `None`.
- `test_rate_fields_compute_real_rate_when_multiple_rows_present` —
  two rows for the same symbol, real rate computed (mean of truth
  values).

The pre-existing tests named per task descriptor are also still
covered:
`test_position_context_churn_blocked_truth_from_row`,
`test_position_context_churn_blocked_missing_label_when_no_row`,
`test_position_context_v2_pre_trade_allowed_rate_value_from_history`,
`test_position_context_v2_pre_trade_allowed_rate_missing_label_when_empty`,
`test_position_context_v2_fee_gate_allowed_rate_value_from_history`,
`test_position_context_v2_fee_gate_allowed_rate_missing_label_when_empty`,
`test_position_context_v2_churn_blocked_rate_value_from_history`,
`test_position_context_v2_churn_blocked_rate_missing_label_when_empty`.

Run:

```
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py -q
```

Result: **40 passed**.

Regression sweep over all `full_observation` tests:

```
PYTHONPATH=$PWD .venv/bin/pytest v2/backend/tests/integration/cli/ \
  -k 'full_observation' -q
```

Result: **150 passed**.

## Runtime evidence

Per-symbol values after refresh (current Redis state, which now
includes a SOLUSDT row in `v2:risk:decisions`):

| symbol | position_context.churn_blocked | v2_pre_trade_allowed_rate | v2_fee_gate_allowed_rate | v2_churn_blocked_rate |
|---|---|---|---|---|
| BTC | (0.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) |
| ETH | (0.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (1.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) |
| SOL | (0.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) | (0.0, V2_RISK_DECISIONS) |

`full_observation_builder_status` after refresh:

| symbol | generated | missing | state |
|---|---:|---:|---|
| BTCUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| ETHUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| SOLUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |

SOL gained +9 generated dims (215 → 224) because the
`v2:risk:decisions` publisher now emits a SOL row, so all risk-sourced
fields source cleanly for SOL via the helpers from the prior risk-decision
field-group implementation.

Remaining-dim queue (refresh):

- aggregate_total_observed = 5733 (PASS)
- strict_source_contract_pass = True
- generic_source_hint_hits = 0
- portfolio_state_broad_bucket_emitted = False
- `V2_BUILDABLE_NOW` = **3** (was 12 before this group's runtime refresh)
- queue GO/NO-GO = `V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`.

## Safety

- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not stop V2 runtime / continuous remediation / legacy log observer /
  V2-vs-legacy comparator / liquidation WSS daemon.
- Did not write any Redis key (read-only Redis access for tests).
- Did not call any exchange endpoint.
- Did not create live / canary / shutdown / Redis-trim approval tokens.
- Did not start policy architecture.
- Did not claim checkpoint compatibility.
- Did not claim policy architecture parity.
- Did not consume legacy current-truth keys.
- Did not consume `v2:paper:*` or `v2:orchestrator:*` for the four selected
  fields.
- `zero_filled_field_count` = 0 across all symbols.
- `live_gate` = `blocked_human_only`.
- `live_symbols` = `[]`.

## Follow-up

The paired Codex review descriptors `215`, `217`, `219`, `221` remain
pending under `claude_worklog/agent_supervisor/tasks/`. The autonomous
controller `--once` / `--loop` is intentionally NOT invoked. No new
task descriptors created.
