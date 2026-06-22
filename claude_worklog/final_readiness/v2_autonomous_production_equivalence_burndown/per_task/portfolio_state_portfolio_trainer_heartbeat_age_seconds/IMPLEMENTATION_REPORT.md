# Burndown task 200 — portfolio_state.portfolio_trainer_heartbeat_age_seconds

GO/NO-GO: `V2_FULL_OBSERVATION_PORTFOLIO_STATE_PORTFOLIO_TRAINER_HEARTBEAT_AGE_SECONDS_BURNDOWN_READY_PARTIAL_PROGRESS`

Source contract (from remediated remaining-dim queue):

- field_id: `portfolio_trainer_heartbeat_age_seconds`
- scope: global (per-symbol slice via portfolio_state)
- exact_v2_source_keys: `["v2:trainer:heartbeat"]`
- expected_payload_field: `generated_utc` (per queue spec)
- stale_or_missing_behavior:
  emit `MISSING_FROM_V2_TRAINER` when key absent, do not zero-fill age
- implementation_target_function:
  `v2.backend.app.services.rl_core.full_observation_builder._build_portfolio_state_slice`

## Root cause

The trainer heartbeat publisher (see
[v2/backend/app/cli/...](../../../../../../v2/backend/app/cli/)) writes
`started_at` / `finished_at` timestamps to `v2:trainer:heartbeat`. It
does **not** write `generated_utc`. The shared
`_heartbeat_age_seconds` helper used by the portfolio_state slice only
checked `generated_utc / heartbeat_at / generated_at`. As a result the
field was silently None and labelled `MISSING_FROM_V2_TRAINER` even
though the key was fresh.

## Change

Edited [v2/backend/app/services/rl_core/full_observation_builder.py](../../../../../../v2/backend/app/services/rl_core/full_observation_builder.py).

Extended the `_heartbeat_age_seconds` fallback tuple with two
trainer-publisher fields: `finished_at` (preferred — completion time of
the most recent trainer cycle) and `started_at` (last-resort fallback).
`generated_utc / heartbeat_at / generated_at` continue to take
precedence so the tracker, orchestrator, and other heartbeat consumers
are unaffected.

This is the minimal surgical change that satisfies the queue's
exact-source contract: we still consume only `v2:trainer:heartbeat`;
we just acknowledge the canonical publisher fields. No new Redis key
is read.

## Tests

Added to [v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py](../../../../../../v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py):

- `test_portfolio_trainer_heartbeat_age_seconds_present_age_monotonic` —
  with a `started_at` / `finished_at` timestamp 42s ago, value sources
  to `V2_TRAINER_HEARTBEAT` and age is in the expected window
  (30–120s, accounting for sample drift).
- `test_portfolio_trainer_heartbeat_age_seconds_missing_label_when_no_key` —
  two paths: heartbeat payload missing entirely, and heartbeat payload
  present but with no usable timestamp. Both must emit
  `MISSING_FROM_V2_TRAINER` with value `None` and
  zero_filled_field_count == 0.

Run:

```
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_full_observation_portfolio_state_burndown.py -q
```

Result: 9 passed (including the 2 new tests for this task).

Regression sweep over all `full_observation` tests:

```
PYTHONPATH=$PWD .venv/bin/pytest v2/backend/tests/integration/cli/ \
  -k 'full_observation' -q
```

Result: 119 passed.

## Runtime evidence

Before: BTCUSDT `portfolio_state.portfolio_trainer_heartbeat_age_seconds`
= `(None, "MISSING_FROM_V2_TRAINER")` despite a fresh trainer heartbeat.

After: same field = `(32.0, "V2_TRAINER_HEARTBEAT")` (live runtime
sample with `finished_at` 32 seconds in the past).

`v2_full_observation_builder_status` after refresh:

| symbol | generated | missing | state |
| --- | ---: | ---: | --- |
| BTCUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| ETHUSDT | 224 | 1687 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |
| SOLUSDT | 214 | 1697 | FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS |

Up by 1 per symbol (3 dims total) — the trainer-age field. Reflected in
the refreshed remaining-dim queue: `V2_BUILDABLE_NOW` dropped 16 → 13.

## Safety

- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not stop V2 runtime / governor / observer / comparator / WSS daemon.
- Did not write any Redis key.
- Did not call any exchange endpoint.
- Did not create any live / canary / shutdown / Redis-trim approval token.
- Did not start policy architecture.
- Did not claim checkpoint compatibility.
- `live_gate=blocked_human_only`, `live_symbols=[]`.
