# Phase 2E1.C.α — Trainer Liveness Domain Spec

This document is the authoring spec for Phase 2E1.C.α of REQ_0006.

It is non-live, non-Redis, non-subprocess, non-legacy-mutating, and
non-deploying. The domain layer authored here observes nothing on its
own; it is a pure-function evaluator over a pre-built snapshot.

## Predecessor gates

- Trainer GPU parity plan:
  `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS`
  (`trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md`).
- Liveness fix spec:
  `PHASE2_TRAINER_GPU_PARITY_PREDICTION_WORKER_LIVENESS_READY`
  (`trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`).
- Trainer worker supervision requirement:
  `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.
- 2E1.A subprocess adapter:
  `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- 2E1.B trainer output contract:
  `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`)
  AND `PHASE2E1B_LOCAL_VALIDATION_PASSED`
  (`trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md`).

## Surface to create

Package: `v2/backend/app/domain/trainer_liveness/`

Files (exact set, no extras):

- `__init__.py` — public surface only.
- `errors.py` — domain-specific exception types.
- `signal_snapshot.py` — `LivenessSignalSnapshot` value object.
- `sla_config.py` — `LivenessSLAConfig` value object.
- `alert.py` — `LivenessAlert` value object and reason constants.
- `evaluator.py` — pure function `evaluate_liveness`.

Tests live in `v2/backend/tests/unit/domain/trainer_liveness/`.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `LivenessSignalSnapshot`
2. `LivenessSLAConfig`
3. `LivenessAlert`
4. `evaluate_liveness`
5. `LivenessDomainError`
6. `LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA`
7. `LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA`
8. `LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA`
9. `LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH`
10. `LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED`

No other names are re-exported. No re-export of submodules. No
re-export of internal `_ALLOWED_*` sets.

## `LivenessSignalSnapshot` (`signal_snapshot.py`)

Dataclass `LivenessSignalSnapshot` (`@dataclass(frozen=True,
slots=True)`). Each field corresponds to one of the read-only signals
listed in `05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md` "Required signals"
section.

Field set, in this order, with these types:

- `trainer_pid: int | None` — `None` when the parent process is absent.
- `trainer_rss_bytes: int | None` — `None` when unavailable; otherwise
  `>= 0`.
- `trainer_heartbeat_ts_ms: int | None` — last heartbeat timestamp;
  `None` when never observed.
- `prediction_worker_pid: int | None`
- `prediction_worker_alive: bool`
- `last_prediction_ts_ms: int | None`
- `last_gpu_batch_ts_ms: int | None`
- `last_deconflict_ts_ms: int | None`
- `last_proposal_ts_ms: int | None`
- `prediction_stream_id_growth: int` — count of new stream IDs across
  the configured window. `>= 0`.
- `proposal_stream_id_growth: int` — `>= 0`.
- `fatal_log_signature_observed: bool`
- `observation_ts_ms: int` — when the snapshot was assembled. `>= 0`.

`__post_init__` invariants:

- `observation_ts_ms >= 0`.
- `prediction_stream_id_growth >= 0`.
- `proposal_stream_id_growth >= 0`.
- `trainer_rss_bytes` is either `None` or `>= 0`.
- All `*_ts_ms` fields are either `None` or `>= 0`.
- `trainer_pid` and `prediction_worker_pid` are either `None` or `> 0`.
- If `trainer_pid is None`, then `trainer_rss_bytes` MUST be `None`
  (cannot have RSS without a PID).
- `prediction_worker_alive` is bool. If `prediction_worker_pid is None`
  and `prediction_worker_alive is True`, that is a contradiction and
  must raise.

Violations raise `LivenessDomainError`.

## `LivenessSLAConfig` (`sla_config.py`)

Dataclass `LivenessSLAConfig` (`@dataclass(frozen=True, slots=True)`).
Holds the SLA thresholds the evaluator compares against.

Field set, in this order:

- `prediction_age_max_ms: int`
- `gpu_batch_age_max_ms: int`
- `proposal_age_max_ms: int`
- `prediction_stream_zero_growth_window_ms: int`

`__post_init__` invariants:

- All four fields are `>= 1` (zero or negative SLA is meaningless and
  would constantly trip the alert).

Violations raise `LivenessDomainError`.

The SLA does not include a deconflict-age threshold because
`05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md` "Required alert" does not
list a deconflict-driven trigger. Deconflict freshness is captured in
the snapshot for downstream observability but is not consulted by the
α evaluator.

## `LivenessAlert` (`alert.py`)

Module exports:

- Six string constants (closed set; module-level UPPER_SNAKE):
  - `LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA = "prediction_age_exceeds_sla"`
  - `LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA = "gpu_batch_age_exceeds_sla"`
  - `LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA = "proposal_age_exceeds_sla"`
  - `LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH = "prediction_stream_zero_growth"`
  - `LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED = "fatal_log_signature_observed"`
- A module-level constant `_ALLOWED_LIVENESS_REASONS` containing the
  five reason strings as a frozenset. Not exported.
- A module-level constant
  `LIVENESS_ALERT_CODE = "TRAINER_INTERNAL_LIVENESS_CRITICAL"`.
  This is the alert code mandated by 05 spec "Required alert". It is
  NOT re-exported from `__init__.py` (it lives at module scope and is
  consulted only inside the evaluator and downstream service-layer
  emitters in 2E1.C.δ); test code reads it via
  `from v2.backend.app.domain.trainer_liveness.alert import
  LIVENESS_ALERT_CODE`.

Dataclass `LivenessAlert` (`@dataclass(frozen=True, slots=True)`).

Field set, in this order:

- `alert_code: str`
- `reasons: tuple[str, ...]`
- `observation_ts_ms: int`
- `snapshot: LivenessSignalSnapshot`

`__post_init__` invariants:

- `alert_code == LIVENESS_ALERT_CODE`. Any other value raises.
- `reasons` is a non-empty tuple.
- Reasons have no duplicates.
- Every reason string is in `_ALLOWED_LIVENESS_REASONS`.
- `observation_ts_ms == snapshot.observation_ts_ms`.

Violations raise `LivenessDomainError`.

## `evaluate_liveness` (`evaluator.py`)

Single pure function:

```
def evaluate_liveness(
    snapshot: LivenessSignalSnapshot,
    sla: LivenessSLAConfig,
    now_ms: int,
) -> LivenessAlert | None: ...
```

Behavior:

- `now_ms >= 0`. If not, raise `LivenessDomainError`.
- `now_ms >= snapshot.observation_ts_ms`. If not, raise
  `LivenessDomainError` with reason field
  `"now_before_observation"`. Snapshot must be from the past or now.
- Build a list of triggered reasons in this fixed evaluation order:
  1. If `snapshot.last_prediction_ts_ms is not None` and
     `(now_ms - snapshot.last_prediction_ts_ms) > sla.prediction_age_max_ms`,
     append `LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA`.
     (If `last_prediction_ts_ms is None`, the prediction worker has
     never produced a prediction; α treats this as **not yet
     evaluable** and does NOT trigger the prediction-age reason. The
     stream-zero-growth reason still triggers per rule 4 and covers the
     never-emitted case if growth is zero across the window AND the
     parent process is alive.)
  2. If `snapshot.last_gpu_batch_ts_ms is not None` and
     `(now_ms - snapshot.last_gpu_batch_ts_ms) > sla.gpu_batch_age_max_ms`,
     append `LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA`.
  3. If `snapshot.last_proposal_ts_ms is not None` and
     `(now_ms - snapshot.last_proposal_ts_ms) > sla.proposal_age_max_ms`,
     append `LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA`.
  4. If `snapshot.prediction_stream_id_growth == 0` AND
     `snapshot.trainer_pid is not None` AND
     `(snapshot.trainer_rss_bytes is not None and
       snapshot.trainer_rss_bytes > 0)`, append
     `LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH`.
     The "configured window" of 05 spec is the SLA field
     `prediction_stream_zero_growth_window_ms`; α treats the snapshot's
     `prediction_stream_id_growth` as already measured over that
     window. Window-correctness is the responsibility of the 2E1.C.β
     adapter that produces the snapshot.
  5. If `snapshot.fatal_log_signature_observed is True`, append
     `LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED`.
- If the resulting reasons list is empty, return `None`.
- Otherwise return a `LivenessAlert` with:
  - `alert_code = LIVENESS_ALERT_CODE`,
  - `reasons = tuple(reasons)` (deterministic order matching the
    evaluation order above),
  - `observation_ts_ms = snapshot.observation_ts_ms`,
  - `snapshot = snapshot`.

The function must:

- Be pure: no I/O, no clock read, no subprocess, no Redis, no network,
  no random.
- Not import legacy modules.
- Not write to mutable state outside the local frame.

## `errors.py`

Single exception:

- `LivenessDomainError(ValueError)`

It carries `reason: str` and `field: str | None` attributes. Constructor
signature is `__init__(self, reason: str, *, field: str | None = None)`.

## Hard exclusions for Phase 2E1.C.α

- No subprocess / shell calls.
- No file I/O.
- No network.
- No Redis import or client construction.
- No legacy module import.
- No environment variable reads.
- No reliance on the subprocess adapter from Phase 2E1.A.
- No live trainer call.
- No model loading or checkpoint loading.
- No GPU code.
- No async I/O. Domain layer is fully synchronous.
- No use of `time.time()` / `datetime.now()` / `datetime.utcnow()`
  inside the module (timestamps come in as int args).
- No `numpy.random` import (or any numpy import).
- No emission to V2 Redis namespace; the alert object is returned
  in-process only. V2 emission is a 2E1.C.δ concern.

## Cross-references

- Required-signals list and required-alert list:
  `trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`.
- Detection-class definition (`TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`):
  same file.
- Trainer worker supervision requirement source:
  `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.
- Authoring shape parallels:
  `trainer_gpu_parity_impl/26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`.
- Out-of-band requirements (no Redis write, no legacy restart, future
  V2_REDIS_PREFIX emission, stream-id growth not XLEN):
  `trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`
  "Out-of-band requirements".

PHASE2E1C_ALPHA_TRAINER_LIVENESS_DOMAIN_SPEC_READY
