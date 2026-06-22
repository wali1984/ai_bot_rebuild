# Codex Review: 100_trainer_parity_2e2a_worker_health_domain_implementation

GO/NO-GO: `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Raw Output (tail)

```text
  `xpending`, `xrange`, `xtrim`, `xautoclaim`
- `pipeline`
- `execute_command`
- `pubsub`, `publish`, `subscribe`
- `client.set`, `client.get`, `client.hset`, `client.hget`,
  `client.delete`, `client.expire`

## Import boundaries

The six authored source files import:

- `errors.py`: only the Python standard library.
- `health_status.py`: only the Python standard library.
- `health_thresholds.py`: only the Python standard library and the
  in-package `errors.py`.
- `health_snapshot.py`: the Python standard library; the in-package
  `errors.py`; the in-package `health_status.py` (constants and the
  two module-private frozensets); and the absolute path
  `v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`.
- `health_evaluator.py`: the Python standard library; the in-package
  `errors.py`; the in-package `health_status.py`; the in-package
  `health_thresholds.py`; the in-package `health_snapshot.py`; and
  the absolute path
  `v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`.
- `__init__.py`: only the in-package modules listed above. No
  external imports beyond what `health_evaluator.py` transitively
  pulls.

The package import MUST NOT transitively load `redis`,
`v2.backend.app.adapters.redis_v2`, or
`v2.backend.app.adapters.redis_v2.url_env`. This invariant is
asserted in `test_worker_health_domain_does_not_import_redis.py` and
`test_worker_health_domain_does_not_import_url_env.py`.

## Determinism and frozen-dataclass discipline

- All public dataclasses (`TrainerWorkerHealthThresholds`,
  `TrainerWorkerHealthSnapshot`) MUST be `@dataclass(frozen=True,
  slots=True)`.
- The evaluator MUST be a pure function: same inputs → same outputs,
  no module-level state, no global counters, no class-level mutable
  default arguments.
- The evaluator MUST NOT mutate any field of `snapshot` or
  `thresholds`. It MUST NOT mutate any tuple it receives.

## Stop conditions for the implementation task

The implementation task `100` MUST emit `146` with marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_FAIL` and
stop on any of:

- predecessor marker missing or wrong
- any source file fails py_compile
- any test in the new suite fails
- any cross-isolation test suite (2E1.A through 2E1.E) regresses
- any cross-isolation `git status -s` returns at least one line
- any forbidden-token guard test fails
- any redis-import or url_env-import guard test fails
- any of the hard-stop list violations above is observed during
  authoring

## Stop conditions for the Codex review task

The Codex review task `101` MUST emit `148` with marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` and stop on any
hard-stop list violation, any forbidden-token violation, any
prior-milestone modification, or any safety-review row that is not
"none observed". Concrete non-safety blockers from `101` route to a
narrow REQ_0007 / REQ_0014 autofix task scoped to the six authored
source files plus the 24 new test files only; no autofix is
permitted on prior-milestone files.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_SAFETY_BOUNDARIES_READY
---liveness init---
from .alert import (
    LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
    LIVENESS_REASON_PREDICTION_WORKER_DEAD,
    LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
    LivenessAlert,
)
from .errors import LivenessDomainError
from .evaluator import evaluate_liveness
from .signal_snapshot import LivenessSignalSnapshot
from .sla_config import LivenessSLAConfig


__all__ = [
    "LivenessSignalSnapshot",
    "LivenessSLAConfig",
    "LivenessAlert",
    "evaluate_liveness",
    "LivenessDomainError",
    "LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA",
    "LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA",
    "LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA",
    "LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH",
    "LIVENESS_REASON_PREDICTION_WORKER_DEAD",
    "LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED",
]
---liveness signal_snapshot---
from __future__ import annotations

from dataclasses import dataclass

from .errors import LivenessDomainError


def _ensure_optional_nonnegative(value: int | None, field: str) -> None:
    if value is not None and value < 0:
        raise LivenessDomainError("must_be_nonnegative", field=field)


def _ensure_optional_positive(value: int | None, field: str) -> None:
    if value is not None and value <= 0:
        raise LivenessDomainError("must_be_positive", field=field)


@dataclass(frozen=True, slots=True)
class LivenessSignalSnapshot:
    trainer_pid: int | None
    trainer_rss_bytes: int | None
    trainer_heartbeat_ts_ms: int | None
    prediction_worker_pid: int | None
    prediction_worker_alive: bool
    last_prediction_ts_ms: int | None
    last_gpu_batch_ts_ms: int | None
    # Captured for lineage/explainability; alpha liveness does not alert on deconflict freshness.
    last_deconflict_ts_ms: int | None
    last_proposal_ts_ms: int | None
    prediction_stream_id_growth: int
    proposal_stream_id_growth: int
    fatal_log_signature_observed: bool
    observation_ts_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.prediction_worker_alive, bool):
            raise LivenessDomainError("must_be_bool", field="prediction_worker_alive")
        if not isinstance(self.fatal_log_signature_observed, bool):
            raise LivenessDomainError("must_be_bool", field="fatal_log_signature_observed")
        if self.observation_ts_ms < 0:
            raise LivenessDomainError("must_be_nonnegative", field="observation_ts_ms")
        if self.prediction_stream_id_growth < 0:
            raise LivenessDomainError("must_be_nonnegative", field="prediction_stream_id_growth")
        if self.proposal_stream_id_growth < 0:
            raise LivenessDomainError("must_be_nonnegative", field="proposal_stream_id_growth")

        _ensure_optional_positive(self.trainer_pid, "trainer_pid")
        _ensure_optional_positive(self.prediction_worker_pid, "prediction_worker_pid")
        _ensure_optional_nonnegative(self.trainer_rss_bytes, "trainer_rss_bytes")
        _ensure_optional_nonnegative(self.trainer_heartbeat_ts_ms, "trainer_heartbeat_ts_ms")
        _ensure_optional_nonnegative(self.last_prediction_ts_ms, "last_prediction_ts_ms")
        _ensure_optional_nonnegative(self.last_gpu_batch_ts_ms, "last_gpu_batch_ts_ms")
        _ensure_optional_nonnegative(self.last_deconflict_ts_ms, "last_deconflict_ts_ms")
        _ensure_optional_nonnegative(self.last_proposal_ts_ms, "last_proposal_ts_ms")

        if self.trainer_pid is None and self.trainer_rss_bytes is not None:
            raise LivenessDomainError("rss_requires_trainer_pid", field="trainer_rss_bytes")
        if self.prediction_worker_pid is None and self.prediction_worker_alive is True:
            raise LivenessDomainError("alive_requires_worker_pid", field="prediction_worker_alive")
---liveness errors---
class LivenessDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)

exec
/bin/bash -lc "cat > claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/145_2E2A_WORKER_HEALTH_DOMAIN_IMPLEMENTATION_REPORT.md <<'EOF'
# Phase 2E2.A Worker Health Domain Implementation Report

## Predecessor gate result

FAIL: "'`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md` did not contain exactly `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`.

Observed content: `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_FAIL`

Per the Phase 2E2.A dispatch rule, no source files or test files were authored and validation commands were not run.
EOF
printf '"'%s\\n' 'PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_FAIL' > claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/146_2E2A_WORKER_HEALTH_DOMAIN_GO_NO_GO.md
" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
codex
Predecessor gate failed: observed `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_FAIL`, expected `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`.

Emitted only:
- `145_2E2A_WORKER_HEALTH_DOMAIN_IMPLEMENTATION_REPORT.md`
- `146_2E2A_WORKER_HEALTH_DOMAIN_GO_NO_GO.md`

No source/test files authored; validation commands not run.
Predecessor gate failed: observed `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_FAIL`, expected `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`.

Emitted only:
- `145_2E2A_WORKER_HEALTH_DOMAIN_IMPLEMENTATION_REPORT.md`
- `146_2E2A_WORKER_HEALTH_DOMAIN_GO_NO_GO.md`

No source/test files authored; validation commands not run.
```
