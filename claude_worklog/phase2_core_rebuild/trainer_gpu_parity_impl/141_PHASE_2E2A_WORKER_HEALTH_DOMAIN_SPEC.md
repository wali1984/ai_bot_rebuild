# Phase 2E2.A — Trainer Worker Health Domain Spec

This document is the authoring spec for Phase 2E2.A of REQ_0006. It
is the first sub-phase of the trainer-prediction-worker-health
milestone group. It builds a NEW domain package
`v2/backend/app/domain/trainer_worker_health/` that consumes the
existing 2E1
`v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`
value object as a fixed external contract and produces a richer
per-snapshot health status with three severity bands plus a distinct
"no signals observed" bucket.

## Predecessor gates

- 2E1.E composition root (post-autofix Codex re-review):
  `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`
  (`trainer_gpu_parity_impl/139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`).

If the predecessor marker is absent, the supervisor MUST NOT dispatch
2E2.A. The implementation task `100` encodes the 2E1.E Codex pass as
its primary additional marker.

## Module location decision

Worker health domain files land under a NEW package:

- `v2/backend/app/domain/trainer_worker_health/__init__.py`
- `v2/backend/app/domain/trainer_worker_health/errors.py`
- `v2/backend/app/domain/trainer_worker_health/health_status.py`
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`
- `v2/backend/app/domain/trainer_worker_health/health_evaluator.py`

The new package is a sibling of the existing
`v2/backend/app/domain/trainer_liveness/` package. It does NOT live
inside `trainer_liveness/` because the worker-health model is a
distinct contract with its own status enumeration, threshold dataclass,
snapshot dataclass, and evaluator entry point. The new package
imports the existing `LivenessSignalSnapshot` symbol but does not
import any other 2E1 trainer-liveness symbol (no `LivenessAlert`, no
`LIVENESS_REASON_*` constants, no `evaluate_liveness`, no
`LivenessSLAConfig`).

No 2E1 file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/trainer_worker_health/__init__.py`
- `v2/backend/app/domain/trainer_worker_health/errors.py`
- `v2/backend/app/domain/trainer_worker_health/health_status.py`
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`
- `v2/backend/app/domain/trainer_worker_health/health_evaluator.py`
- `v2/backend/tests/unit/domain/trainer_worker_health/__init__.py`
- `v2/backend/tests/unit/domain/trainer_worker_health/` 24 test files
  enumerated in `142_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN.md`.

## Public surface (exact `__all__`)

`v2/backend/app/domain/trainer_worker_health/__init__.py` exposes
exactly the following names, in this order, in `__all__`:

1. `TrainerWorkerHealthDomainError`
2. `TrainerWorkerHealthThresholds`
3. `TrainerWorkerHealthSnapshot`
4. `evaluate_trainer_worker_health`
5. `HEALTH_STATUS_HEALTHY`
6. `HEALTH_STATUS_DEGRADED`
7. `HEALTH_STATUS_CRITICAL`
8. `HEALTH_STATUS_UNKNOWN`
9. `HEALTH_REASON_PREDICTION_AGE_DEGRADED`
10. `HEALTH_REASON_GPU_BATCH_AGE_DEGRADED`
11. `HEALTH_REASON_PROPOSAL_AGE_DEGRADED`
12. `HEALTH_REASON_PREDICTION_AGE_CRITICAL`
13. `HEALTH_REASON_GPU_BATCH_AGE_CRITICAL`
14. `HEALTH_REASON_PROPOSAL_AGE_CRITICAL`
15. `HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH`
16. `HEALTH_REASON_PREDICTION_WORKER_DEAD`
17. `HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED`
18. `HEALTH_REASON_NO_SIGNALS_OBSERVED`

## TrainerWorkerHealthDomainError

`errors.py` defines:

```
class TrainerWorkerHealthDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

Imports only the standard library. Imports nothing from `v2/`.
Imports nothing from `redis`, `aioredis`, `hiredis`, or
`redis.asyncio`.

## Status constants

`health_status.py` defines exactly four status string constants with
exact string values:

- `HEALTH_STATUS_HEALTHY = "HEALTHY"`
- `HEALTH_STATUS_DEGRADED = "DEGRADED"`
- `HEALTH_STATUS_CRITICAL = "CRITICAL"`
- `HEALTH_STATUS_UNKNOWN = "UNKNOWN"`

Plus the reason constants with exact string values:

- `HEALTH_REASON_PREDICTION_AGE_DEGRADED = "prediction_age_degraded"`
- `HEALTH_REASON_GPU_BATCH_AGE_DEGRADED = "gpu_batch_age_degraded"`
- `HEALTH_REASON_PROPOSAL_AGE_DEGRADED = "proposal_age_degraded"`
- `HEALTH_REASON_PREDICTION_AGE_CRITICAL = "prediction_age_critical"`
- `HEALTH_REASON_GPU_BATCH_AGE_CRITICAL = "gpu_batch_age_critical"`
- `HEALTH_REASON_PROPOSAL_AGE_CRITICAL = "proposal_age_critical"`
- `HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH = "prediction_stream_zero_growth"`
- `HEALTH_REASON_PREDICTION_WORKER_DEAD = "prediction_worker_dead"`
- `HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED = "fatal_log_signature_observed"`
- `HEALTH_REASON_NO_SIGNALS_OBSERVED = "no_signals_observed"`

The module also defines two frozenset module-level constants used by
the snapshot invariant check:

- `_ALLOWED_HEALTH_STATUSES = frozenset({HEALTH_STATUS_HEALTHY, HEALTH_STATUS_DEGRADED, HEALTH_STATUS_CRITICAL, HEALTH_STATUS_UNKNOWN})`
- `_ALLOWED_HEALTH_REASONS = frozenset({...all 10 reason constants above...})`

These two frozensets are module-private (leading underscore). They
are imported by `health_snapshot.py`.

`health_status.py` imports only the standard library. Imports nothing
from `v2/`. Imports nothing from `redis`, `aioredis`, `hiredis`, or
`redis.asyncio`.

## TrainerWorkerHealthThresholds

`health_thresholds.py` defines:

```
@dataclass(frozen=True, slots=True)
class TrainerWorkerHealthThresholds:
    prediction_age_degraded_ms: int
    prediction_age_critical_ms: int
    gpu_batch_age_degraded_ms: int
    gpu_batch_age_critical_ms: int
    proposal_age_degraded_ms: int
    proposal_age_critical_ms: int

    def __post_init__(self) -> None:
        # All six fields must be int and >= 1.
        # For each (degraded, critical) pair, degraded must be < critical.
```

Invariants enforced via `TrainerWorkerHealthDomainError`:

- Each of the six fields must be `int` (not `bool`); failing this
  raises with `field=<field_name>` and `reason="must_be_int"`.
- Each of the six fields must be `>= 1`; failing this raises with
  `field=<field_name>` and `reason="must_be_at_least_one"`.
- For each (degraded, critical) pair, `degraded_ms < critical_ms`;
  failing this raises with `field="<critical_field_name>"` and
  `reason="critical_must_be_greater_than_degraded"`.

Imports only the standard library and `errors.py`. Imports nothing
from `v2/` outside this package.

## TrainerWorkerHealthSnapshot

`health_snapshot.py` defines:

```
@dataclass(frozen=True, slots=True)
class TrainerWorkerHealthSnapshot:
    status: str
    reasons: tuple[str, ...]
    signal_snapshot: LivenessSignalSnapshot
    observation_ts_ms: int
```

Invariants enforced in `__post_init__` via
`TrainerWorkerHealthDomainError`:

- `status` MUST be in `_ALLOWED_HEALTH_STATUSES`. Otherwise
  `field="status"`, `reason="invalid_status"`.
- `reasons` MUST be a `tuple` (not list, not frozenset). Otherwise
  `field="reasons"`, `reason="must_be_tuple"`.
- Every element of `reasons` MUST be a `str` and MUST be in
  `_ALLOWED_HEALTH_REASONS`. Otherwise `field="reasons"`,
  `reason="unknown_reason"`.
- `reasons` MUST not contain duplicates. Otherwise `field="reasons"`,
  `reason="duplicate_reasons"`.
- `signal_snapshot` MUST be an instance of `LivenessSignalSnapshot`.
  Otherwise `field="signal_snapshot"`,
  `reason="must_be_liveness_signal_snapshot"`.
- `observation_ts_ms` MUST equal `signal_snapshot.observation_ts_ms`.
  Otherwise `field="observation_ts_ms"`,
  `reason="must_match_snapshot"`.
- If `status == HEALTH_STATUS_HEALTHY`, `reasons` MUST equal `()`.
  Otherwise `field="reasons"`, `reason="healthy_requires_empty_reasons"`.
- If `status == HEALTH_STATUS_UNKNOWN`, `reasons` MUST equal
  `(HEALTH_REASON_NO_SIGNALS_OBSERVED,)`. Otherwise
  `field="reasons"`, `reason="unknown_requires_no_signals_reason"`.
- If `status == HEALTH_STATUS_DEGRADED`, every reason in `reasons`
  MUST be a degraded-band reason (one of
  `HEALTH_REASON_PREDICTION_AGE_DEGRADED`,
  `HEALTH_REASON_GPU_BATCH_AGE_DEGRADED`,
  `HEALTH_REASON_PROPOSAL_AGE_DEGRADED`) AND `reasons` MUST NOT be
  empty. Otherwise `field="reasons"`,
  `reason="degraded_reasons_must_be_degraded_band"` or
  `reason="degraded_requires_at_least_one_reason"`.
- If `status == HEALTH_STATUS_CRITICAL`, `reasons` MUST contain at
  least one critical-band reason (one of
  `HEALTH_REASON_PREDICTION_AGE_CRITICAL`,
  `HEALTH_REASON_GPU_BATCH_AGE_CRITICAL`,
  `HEALTH_REASON_PROPOSAL_AGE_CRITICAL`,
  `HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH`,
  `HEALTH_REASON_PREDICTION_WORKER_DEAD`,
  `HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED`). Otherwise
  `field="reasons"`,
  `reason="critical_requires_at_least_one_critical_reason"`.

Imports: standard library; `errors.py`; `health_status.py` (the
status and reason constants and the two frozenset module-private
constants); the existing
`v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`
symbol via the absolute path. Imports nothing else.

## evaluate_trainer_worker_health

`health_evaluator.py` defines:

```
def evaluate_trainer_worker_health(
    snapshot: LivenessSignalSnapshot,
    thresholds: TrainerWorkerHealthThresholds,
    now_ms: int,
) -> TrainerWorkerHealthSnapshot:
    ...
```

Behavior contract — implement in this exact order:

1. Validate `snapshot` is a `LivenessSignalSnapshot` instance.
   Otherwise raise `TrainerWorkerHealthDomainError("must_be_liveness_signal_snapshot", field="snapshot")`.
2. Validate `thresholds` is a `TrainerWorkerHealthThresholds`
   instance. Otherwise raise
   `TrainerWorkerHealthDomainError("must_be_worker_health_thresholds", field="thresholds")`.
3. Validate `type(now_ms) is int` (reject `bool`). Otherwise raise
   `TrainerWorkerHealthDomainError("must_be_int", field="now_ms")`.
4. Validate `now_ms >= 0`. Otherwise raise
   `TrainerWorkerHealthDomainError("must_be_nonnegative", field="now_ms")`.
5. Validate `now_ms >= snapshot.observation_ts_ms`. Otherwise raise
   `TrainerWorkerHealthDomainError("now_before_observation", field="now_ms")`.
6. Compute the `no_signals` predicate. It is `True` exactly when ALL
   of the following hold on the snapshot:
   - `trainer_pid is None`
   - `trainer_rss_bytes is None`
   - `trainer_heartbeat_ts_ms is None`
   - `prediction_worker_pid is None`
   - `prediction_worker_alive is False`
   - `last_prediction_ts_ms is None`
   - `last_gpu_batch_ts_ms is None`
   - `last_deconflict_ts_ms is None`
   - `last_proposal_ts_ms is None`
   - `prediction_stream_id_growth == 0`
   - `proposal_stream_id_growth == 0`
   - `fatal_log_signature_observed is False`
   If `no_signals` is `True`, return
   `TrainerWorkerHealthSnapshot(status=HEALTH_STATUS_UNKNOWN,
   reasons=(HEALTH_REASON_NO_SIGNALS_OBSERVED,),
   signal_snapshot=snapshot,
   observation_ts_ms=snapshot.observation_ts_ms)` and stop.
7. Compute the critical reasons list, in this exact order:
   - If `snapshot.last_prediction_ts_ms is not None` and
     `now_ms - snapshot.last_prediction_ts_ms > thresholds.prediction_age_critical_ms`,
     append `HEALTH_REASON_PREDICTION_AGE_CRITICAL`.
   - If `snapshot.last_gpu_batch_ts_ms is not None` and
     `now_ms - snapshot.last_gpu_batch_ts_ms > thresholds.gpu_batch_age_critical_ms`,
     append `HEALTH_REASON_GPU_BATCH_AGE_CRITICAL`.
   - If `snapshot.last_proposal_ts_ms is not None` and
     `now_ms - snapshot.last_proposal_ts_ms > thresholds.proposal_age_critical_ms`,
     append `HEALTH_REASON_PROPOSAL_AGE_CRITICAL`.
   - If `snapshot.prediction_stream_id_growth == 0` AND
     `snapshot.trainer_pid is not None` AND
     `snapshot.trainer_rss_bytes is not None` AND
     `snapshot.trainer_rss_bytes > 0`, append
     `HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH`.
   - If `snapshot.prediction_worker_alive is False` AND
     `snapshot.prediction_worker_pid is not None`, append
     `HEALTH_REASON_PREDICTION_WORKER_DEAD`.
   - If `snapshot.fatal_log_signature_observed is True`, append
     `HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED`.
8. Compute the degraded reasons list. A degraded reason for a given
   age signal fires if and only if the age is strictly greater than
   the degraded threshold AND less than or equal to the critical
   threshold. Per the precedence rule, an age signal contributes
   AT MOST one reason: the critical reason if it fired in step 7,
   otherwise the degraded reason if the degraded condition holds.
   In this exact order:
   - If `snapshot.last_prediction_ts_ms is not None` AND
     `HEALTH_REASON_PREDICTION_AGE_CRITICAL` is NOT in the critical
     reasons list AND
     `now_ms - snapshot.last_prediction_ts_ms > thresholds.prediction_age_degraded_ms`,
     append `HEALTH_REASON_PREDICTION_AGE_DEGRADED`.
   - Same pattern for GPU batch.
   - Same pattern for proposal.
9. If the critical reasons list is non-empty, return
   `TrainerWorkerHealthSnapshot(status=HEALTH_STATUS_CRITICAL,
   reasons=tuple(critical_reasons + degraded_reasons),
   signal_snapshot=snapshot,
   observation_ts_ms=snapshot.observation_ts_ms)`. The reasons
   tuple includes both critical and degraded reasons in the order
   they were appended (critical first, then degraded), with no
   sorting.
10. If the critical reasons list is empty AND the degraded reasons
    list is non-empty, return
    `TrainerWorkerHealthSnapshot(status=HEALTH_STATUS_DEGRADED,
    reasons=tuple(degraded_reasons),
    signal_snapshot=snapshot,
    observation_ts_ms=snapshot.observation_ts_ms)`.
11. Otherwise return
    `TrainerWorkerHealthSnapshot(status=HEALTH_STATUS_HEALTHY,
    reasons=(),
    signal_snapshot=snapshot,
    observation_ts_ms=snapshot.observation_ts_ms)`.

Imports: standard library; `errors.py`; `health_status.py`
(constants); `health_thresholds.py` (the dataclass);
`health_snapshot.py` (the dataclass); the existing
`v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`
symbol via the absolute path. Imports nothing else.

The evaluator does NOT log, print, mutate inputs, install singletons,
register lifespan hooks, call wall-clock helpers, open sockets, run
subprocesses, read `os.environ`, or import the redis adapter, the
url_env, or any other adapter / service / composition module.

## Forbidden tokens

The forbidden-token guard tests
(`test_worker_health_domain_does_not_import_redis.py` and
`test_worker_health_domain_does_not_import_url_env.py`) MUST scan
the six authored source files. The following literals are forbidden
absolutely (zero matches in any source file in this milestone):

- `import redis`
- `from redis`
- `redis.asyncio`
- `hiredis`
- `aioredis`
- `xrevrange`
- `xadd`
- `xread`
- `xlen`
- `pipeline`
- `from v2.backend.app.adapters`
- `url_env`
- `os.environ`
- `subprocess`
- `socket.socket`
- `time.time(`
- `time.monotonic(`
- `datetime.now(`
- `datetime.utcnow(`
- `print(`
- `logging.`
- `httpx`
- `requests`
- `from v2.backend.app.services`
- `from v2.backend.app.composition`
- `from v2.backend.app.adapters.redis_v2`

The literals are constructed at runtime in the guard tests via string
concatenation to avoid the forbidden-token guard scanning its own
source.

## Deferred items (NOT in 2E2.A)

- Service composition (deferred to 2E2.B).
- Composition root and Redis-backed factory wiring (deferred to
  2E2.C).
- Streaming aggregation across multiple snapshots (future).
- Per-worker history (future).
- Public API exposure / REST endpoints (deferred to a later phase).
- Frontend rendering of HEALTHY / DEGRADED / CRITICAL / UNKNOWN
  (deferred to REQ_0008 frontend milestone).

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_SPEC_READY
