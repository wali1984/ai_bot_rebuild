# Burndown task 198 — portfolio_state.v2_orchestrator_keys_written_count

GO/NO-GO: `V2_FULL_OBSERVATION_PORTFOLIO_STATE_V2_ORCHESTRATOR_KEYS_WRITTEN_COUNT_BURNDOWN_READY_PARTIAL_PROGRESS`

Source contract (from remediated remaining-dim queue):

- field_id: `v2_orchestrator_keys_written_count`
- scope: global (per-symbol slice via portfolio_state)
- exact_v2_source_keys: `["v2:orchestrator:decisions"]`
- expected_payload_field: `v2_orchestrator_keys_written_count`
- stale_or_missing_behavior:
  emit `MISSING_FROM_V2_ORCHESTRATOR` when key absent or field not
  present in payload
- implementation_target_function:
  `v2.backend.app.services.rl_core.full_observation_builder._build_portfolio_state_slice (orchestrator projection)`

## Change

Edited [v2/backend/app/services/rl_core/full_observation_builder.py](../../../../../../v2/backend/app/services/rl_core/full_observation_builder.py)
at the portfolio_state orchestrator projection (around line 1543).

Before: the row emitted `V2_ORCHESTRATOR_DECISIONS` whenever the
`v2:orchestrator:decisions` key existed, regardless of whether the
`v2_orchestrator_keys_written_count` payload field was actually present.
That was a labelling defect: when the publisher's payload omits the
field (current production state — the arbitration loop publishes the
count to `v2:orchestrator:heartbeat`, not into `v2:orchestrator:decisions`),
the builder was silently labelling a `None` value with
`V2_ORCHESTRATOR_DECISIONS`. That looked like "sourced from V2" while
the value was missing.

After: when `od is None`, or `od` has no `v2_orchestrator_keys_written_count`
field, or `_coerce_float` cannot parse the field, the row emits
`(None, "MISSING_FROM_V2_ORCHESTRATOR")` honestly. When the field IS
present and parseable, the row emits the value with
`V2_ORCHESTRATOR_DECISIONS`.

No legacy Redis key is read. No exchange call. No checkpoint or
policy claim is touched. `zero_filled_field_count` remains 0.

## Tests

Added to [v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py](../../../../../../v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py):

- `test_v2_orchestrator_keys_written_count_present_from_payload` —
  when `orchestrator_decisions` includes the field, value is parsed
  and source is `V2_ORCHESTRATOR_DECISIONS`.
- `test_v2_orchestrator_keys_written_count_missing_label_when_no_key` —
  two paths: payload present but field absent, and payload entirely
  missing. Both must emit `MISSING_FROM_V2_ORCHESTRATOR` with value
  `None` and zero_filled_field_count == 0.

Run:

```
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py -q
```

Result: 9 passed (including the 2 new tests for this task).

## Runtime evidence

Before: BTCUSDT `portfolio_state.v2_orchestrator_keys_written_count` =
`(None, "V2_ORCHESTRATOR_DECISIONS")` — misleading source label.

After: same field = `(None, "MISSING_FROM_V2_ORCHESTRATOR")` — honest.

generated_full_observation_dim per symbol: 224 / 224 / 214
(BTC / ETH / SOL; up from 223/223/213 because of the paired trainer-age
fix, not from this orchestrator labelling fix).

aggregate_total still 5733. classifier GO_NO_GO still
`V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`.

## Safety

- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not stop V2 runtime / governor / observer / comparator / WSS daemon.
- Did not write any Redis key.
- Did not call any exchange endpoint.
- Did not create any live / canary / shutdown / Redis-trim approval token.
- Did not start policy architecture.
- Did not claim checkpoint compatibility.
- `live_gate=blocked_human_only`, `live_symbols=[]`.

## Follow-up note (for operator, not auto-actioned)

The arbitration loop publishes `v2_orchestrator_keys_written_count` to
`v2:orchestrator:heartbeat`, not `v2:orchestrator:decisions`. If you
want the portfolio_state field to actually source, either:

1. extend the queue's exact source binding for this field to include
   `v2:orchestrator:heartbeat`, or
2. have the orchestrator publisher add `v2_orchestrator_keys_written_count`
   to the decisions payload too.

This is an operator/scheduler decision; the autonomous controller
will not change the queue's source binding on its own.
