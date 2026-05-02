# Phase 2E1.C.α — Test Plan

Tests live under `v2/backend/tests/unit/domain/trainer_liveness/`.

All tests are pytest unit tests, fully synchronous, with zero I/O,
zero subprocess, zero Redis, zero network, zero clock reads, and zero
legacy imports.

## Test files (exact set, no extras)

- `__init__.py` — empty package marker (zero bytes or single newline).
- `conftest.py` — local fixtures only; must not introduce module-level
  state. May define helper builders for `LivenessSignalSnapshot` and
  `LivenessSLAConfig` to keep test bodies short.
- `test_signal_snapshot_invariants.py`
- `test_sla_config_invariants.py`
- `test_alert_invariants.py`
- `test_evaluator_no_alert.py`
- `test_evaluator_age_exceeds.py`
- `test_evaluator_zero_stream_growth.py`
- `test_evaluator_fatal_log_signature.py`
- `test_evaluator_multi_reason.py`
- `test_public_surface.py`

## Coverage matrix

### `test_signal_snapshot_invariants.py`

- Construct a fully-populated valid `LivenessSignalSnapshot`; assert all
  fields round-trip.
- Construct a snapshot with all `Optional[int]` fields set to `None`
  (modelling a never-observed trainer); assert it constructs without
  raising.
- Negative `observation_ts_ms` raises `LivenessDomainError`.
- Negative `prediction_stream_id_growth` raises.
- Negative `proposal_stream_id_growth` raises.
- Negative `trainer_rss_bytes` raises.
- `trainer_pid <= 0` raises.
- `prediction_worker_pid <= 0` raises.
- `trainer_pid is None` with non-`None` `trainer_rss_bytes` raises with
  field `"trainer_rss_bytes"`.
- `prediction_worker_pid is None` with `prediction_worker_alive=True`
  raises with field `"prediction_worker_alive"`.
- Negative `last_prediction_ts_ms` raises (and the same for the other
  three timestamp fields).

### `test_sla_config_invariants.py`

- Construct a valid `LivenessSLAConfig`; assert round-trip.
- Each of the four fields raises when set to `0`.
- Each of the four fields raises when set to `-1`.
- Each error carries the offending field name.

### `test_alert_invariants.py`

- Construct a valid `LivenessAlert` with one reason; assert round-trip.
- `alert_code != LIVENESS_ALERT_CODE` raises.
- Empty `reasons` tuple raises.
- Duplicate reasons raise.
- Unknown reason string raises.
- `observation_ts_ms != snapshot.observation_ts_ms` raises with field
  `"observation_ts_ms"`.

### `test_evaluator_no_alert.py`

- Snapshot that satisfies every SLA returns `None`.
- Snapshot with all `*_ts_ms` set to `None` and
  `prediction_stream_id_growth > 0` returns `None` (never-observed-yet
  case is not an error when growth is occurring).
- Snapshot with `prediction_stream_id_growth == 0` AND
  `trainer_pid is None` returns `None` (parent process not alive →
  zero-growth reason does not fire on its own).
- Snapshot with `prediction_stream_id_growth == 0` AND
  `trainer_pid is not None` AND `trainer_rss_bytes is None` returns
  `None` (RSS unknown is treated as parent-not-alive for α; see spec
  rule 4).

### `test_evaluator_age_exceeds.py`

- Prediction age exactly at SLA: returns `None` (strict `>` comparison).
- Prediction age exceeds SLA by 1 ms: returns alert with single reason
  `LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA`.
- GPU batch age exceeds SLA: returns alert with single reason
  `LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA`.
- Proposal age exceeds SLA: returns alert with single reason
  `LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA`.
- `last_prediction_ts_ms is None`: prediction-age reason does NOT fire
  even when `now_ms` is far past any SLA (never-emitted case).
- `now_ms < snapshot.observation_ts_ms`: raises `LivenessDomainError`
  with field `"now_before_observation"`.

### `test_evaluator_zero_stream_growth.py`

- Zero growth + parent alive (PID and RSS > 0) → alert with reason
  `LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH`.
- Zero growth + parent absent (PID None) → no zero-growth reason.
- Zero growth + RSS zero → no zero-growth reason.
- Non-zero growth + parent alive → no zero-growth reason regardless of
  freshness.

### `test_evaluator_fatal_log_signature.py`

- `fatal_log_signature_observed=True` → alert with reason
  `LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED` regardless of other
  fields.
- `fatal_log_signature_observed=False` and no other trigger → `None`.

### `test_evaluator_multi_reason.py`

- All five trigger conditions met simultaneously → single alert with
  five reasons, in this order:
  1. prediction_age,
  2. gpu_batch_age,
  3. proposal_age,
  4. zero_stream_growth,
  5. fatal_log_signature.
- Subset of three reasons (e.g. prediction_age + zero_growth +
  fatal_log) → alert with exactly those three reasons in evaluator
  order.
- `LivenessAlert` rejects re-construction with a permuted reason order
  if duplicate-detection is implemented purely as set comparison; this
  is asserted via direct `LivenessAlert(...)` construction with a
  duplicate input.

### `test_public_surface.py`

- `from v2.backend.app.domain.trainer_liveness import *` exposes
  exactly the ten names in `__all__` (the public-surface list).
- `__all__` is sorted? — assert exact set equality, not order.
- `LIVENESS_ALERT_CODE` is NOT in `__all__`; it must be reachable via
  `from v2.backend.app.domain.trainer_liveness.alert import
  LIVENESS_ALERT_CODE` and equal `"TRAINER_INTERNAL_LIVENESS_CRITICAL"`.
- The `errors` submodule is NOT in `__all__`.
- `__init__.py` does not import any forbidden module; the test asserts
  that `sys.modules` after the import does NOT include `redis`,
  `redis.asyncio`, `aioredis`, `subprocess`, `socket`, `urllib`,
  `requests`, `httpx`, `aiohttp`, `torch`, `tensorflow`, `numpy`,
  `legacy_reference`, or `v2.backend.app.adapters.trainer`.

## Forbidden token grep (validation step, not authoring step)

The local validation task (061) will grep the following tokens across
both `v2/backend/app/domain/trainer_liveness/` and
`v2/backend/tests/unit/domain/trainer_liveness/`. Every token must
return zero hits:

`redis`, `aioredis`, `redis.asyncio`, `subprocess`, `os.system`,
`os.popen`, `pty`, `socket`, `urllib`, `requests`, `httpx`, `aiohttp`,
`torch`, `tensorflow`, `numpy`, `numpy.random`, `cuda`,
`legacy_reference`, `/home/wali/Desktop/AI BOT`,
`v2.backend.app.adapters.trainer`, `os.environ`, `time.time`,
`datetime.now`, `datetime.utcnow`.

## Test invocation

From the repository root, using the V2 control-plane Python interpreter:

```
pytest v2/backend/tests/unit/domain/trainer_liveness/ -q
```

Expected outcome: zero failures, zero errors, zero warnings.

PHASE2E1C_ALPHA_TRAINER_LIVENESS_TEST_PLAN_READY
