# Observation Gap Feature-Source Burndown

GO/NO-GO: V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_READY

Scoped Codex takeover completed the V2 liquidation observation wiring that the
Claude worker identified but could not edit through its permission prompt.

## Implemented

- Added `read_v2_liquidation_per_symbol_from(redis_client, symbol)` in
  `v2/backend/app/services/rl_core/liquidation_observation_aggregator.py`.
- Threaded per-symbol liquidation payloads through
  `full_observation_builder` into the `liquidations` subfamily.
- The four gap fields only fill from real V2 keys:
  `v2:market:liquidations:latest:{symbol}` and
  `v2:market:liquidations:aggregate:{symbol}`.
- If those keys are absent, fields remain explicit
  `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`; no zero-fill or fabrication is
  introduced.

## Validation

```text
python -m py_compile \
  v2/backend/app/services/rl_core/liquidation_observation_aggregator.py \
  v2/backend/app/services/rl_core/full_observation_builder.py \
  v2/backend/app/cli/v2_full_observation_builder_status.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_liquidation_observation_aggregator.py \
  v2/backend/tests/integration/cli/test_v2_full_observation_builder_status.py -q
```

Results: py_compile passed; focused tests passed `19/19`.

## Safety

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- old Redis writes = none
- exchange mutation = none
