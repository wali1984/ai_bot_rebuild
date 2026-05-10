```
# Phase 2Z — Degraded-State Fail-Closed Gates Spec

## Module-level constants

```
DEGRADED_SOURCE_OK = "DEGRADED_SOURCE_OK"
DEGRADED_SOURCE_STALE = "DEGRADED_SOURCE_STALE"
DEGRADED_SOURCE_MISSING = "DEGRADED_SOURCE_MISSING"
DEGRADED_SOURCE_UNUSED = "DEGRADED_SOURCE_UNUSED"
```

## DegradedStateRecord (domain)

`@dataclass(frozen=True, slots=True)` with fields:

- `degraded_state_id: str`
- `smc_state: str`
- `smc_age_ms: int`
- `liq_state: str`
- `liq_age_ms: int`
- `oi_state: str`
- `oi_age_ms: int`
- `orderbook_state: str`
- `orderbook_age_ms: int`
- `fail_closed: bool`
- `decision_id: str`
- `prediction_id: str`
- `feature_snapshot_id: str`
- `risk_decision_id: str`
- `model_version: str`
- `checkpoint_id: str`
- `confidence_raw: float`
- `confidence_calibrated: float`
- `trainer_worker_liveness: str`
- `live_blocked: bool`

`__post_init__` validation:

- `degraded_state_id` is `str`, non-empty, no whitespace, at most 128 chars.
- Each per-source state is `str` in
  `{DEGRADED_SOURCE_OK, DEGRADED_SOURCE_STALE, DEGRADED_SOURCE_MISSING,
  DEGRADED_SOURCE_UNUSED}`.
- Each per-source `age_ms` is `int` (not `bool`) and nonnegative.
- `fail_closed` is `bool`.
- `fail_closed` must equal `True` iff any per-source state is
  `DEGRADED_SOURCE_STALE` or `DEGRADED_SOURCE_MISSING` (and `False`
  otherwise). Constructing a record with an inconsistent `fail_closed`
  value raises `DegradedStateFailClosedGatesDomainError`.
- Each lineage id (`decision_id`, `prediction_id`,
  `feature_snapshot_id`, `risk_decision_id`) is `str`, non-empty,
  no whitespace, at most 128 chars.
- `model_version` and `checkpoint_id` are `str` and non-empty.
- `confidence_raw` and `confidence_calibrated` are `float` (not `bool`)
  in `[0.0, 1.0]`.
- `trainer_worker_liveness` is `str` in `{"alive", "degraded",
  "worker_dead"}`.
- `live_blocked` is `True`.

## assemble_degraded_state_record (service)

Pure function with the signature:

```
def assemble_degraded_state_record(
    *,
    upstream_record: RiskDecisionRecord,
    smc_state: str,
    smc_age_ms: int,
    liq_state: str,
    liq_age_ms: int,
    oi_state: str,
    oi_age_ms: int,
    orderbook_state: str,
    orderbook_age_ms: int,
    trainer_model_version: str,
    trainer_checkpoint_id: str,
    trainer_confidence_raw: float,
    trainer_confidence_calibrated: float,
    trainer_worker_liveness: str,
) -> DegradedStateRecord
```

Behavior:

- Validates `upstream_record` is `RiskDecisionRecord`; otherwise raises
  `DegradedStateFailClosedGatesServiceError(
  "must_be_risk_decision_record", field="upstream_record")`.
- Mirrors the four lineage IDs `decision_id`, `prediction_id`,
  `feature_snapshot_id`, `risk_decision_id` from `upstream_record`.
- Accepts the five Phase 2V trainer-parity fields via dedicated
  keyword-only arguments because `RiskDecisionRecord` does not carry
  them today.
- Derives `degraded_state_id` deterministically as
  `f"degraded_state:{upstream_record.decision_id}"[:128]`.
- Derives `fail_closed` as `True` iff any per-source state is
  `DEGRADED_SOURCE_STALE` or `DEGRADED_SOURCE_MISSING`.
- Sets `live_blocked=True`.
- Re-raises domain construction failures as
  `DegradedStateFailClosedGatesServiceError(
  "invalid_degraded_state_record", field="upstream_record")` to
  preserve the service-error contract.

## build_degraded_state_fail_closed_gates_runtime (composition)

Factory with the signature:

```
def build_degraded_state_fail_closed_gates_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> DegradedStateFailClosedGatesRuntime
```

Behavior:

- Validates `now_ms_clock` is callable; otherwise raises
  `DegradedStateFailClosedGatesRuntimeCompositionError(
  "must_be_callable", field="now_ms_clock")`.
- Never invokes `now_ms_clock` at build time.
- Returns an instance whose `degraded_state_now(...)` closure delegates
  to `assemble_degraded_state_record(...)`.
- The closure invokes the captured `now_ms_clock` zero times per call;
  the typed record carries its own per-source `*_age_ms` fields and a
  decision-id-derived `degraded_state_id`. The clock is reserved for a
  future Phase 2Z-follow-up where the runtime emits its own typed
  timestamp. This mirrors the Phase 2X.B / 2Y reconciled clock policy.

## Module / import constraints

- No module under `v2/backend/app/{domain,services,composition}/
  degraded_state_fail_closed_gates/` may import `redis`, `aioredis`, or
  `redis.asyncio`.
- No module under those paths may import `fastapi` or `starlette`.
- No `__init__.py` may register a FastAPI lifespan.

PHASE_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_SPEC_READY
```
