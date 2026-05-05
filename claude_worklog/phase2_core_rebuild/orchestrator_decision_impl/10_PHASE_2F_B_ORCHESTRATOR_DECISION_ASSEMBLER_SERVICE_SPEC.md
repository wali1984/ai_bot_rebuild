# Phase 2F.B — Orchestrator Decision Assembler Service Spec

This document is the authoring spec for Phase 2F.B of REQ_0006 ∩ REQ_0017. Phase 2F.B is the second sub-phase of the `ORCHESTRATOR_DECISION_MVP` milestone. It builds a NEW services-layer package `v2/backend/app/services/orchestrator_decision/` whose only purpose is to define a single pure assembler function `assemble_orchestrator_decision_record(...)` that takes a validated `TrainerPredictionRecord` (from the Stage A trainer prediction output domain) plus a `low_confidence_threshold` and a `now_ms_clock` callable, and returns a frozen `OrchestratorDecisionRecord` constructed under the default-deny taxonomy fixed by 2F.A.

The package is a pure derivation surface. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The function MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2F.A domain Codex pass: `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/09_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `119_orchestrator_decision_2fb_assembler_service_implementation`.

## Module location decision

The new package is `v2/backend/app/services/orchestrator_decision/`. It is a sibling of `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

The existing one-line placeholder file `v2/backend/app/services/orchestrator_decision.py` (whose sole content is the docstring `"""Orchestrator decision service placeholder. No behavior in scaffold."""`) collides with this new package on the import path. Phase 2F.B opens by deleting that placeholder file in the same supervisor task that authors the new package. The placeholder file MUST NOT be reintroduced.

No other `v2/backend/app/services/` package, no `v2/backend/app/composition/` package, no `v2/backend/app/adapters/` package, no `v2/backend/app/api/` package, no `v2/backend/app/cli/` package, no `v2/backend/app/jobs/` package, no `v2/backend/app/main.py`, no domain package, and no frontend file is modified by 2F.B.

## Scope (additive only — except the placeholder deletion)

Filesystem mutations performed by task `119`:

- delete: `v2/backend/app/services/orchestrator_decision.py` (one-line placeholder)
- create: `v2/backend/app/services/orchestrator_decision/__init__.py`
- create: `v2/backend/app/services/orchestrator_decision/errors.py`
- create: `v2/backend/app/services/orchestrator_decision/service.py`
- create: `v2/backend/tests/unit/services/orchestrator_decision/__init__.py`
- create: 36 sibling test files enumerated in `11_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_TEST_PLAN.md`.
- create: `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/14_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- create: `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md`

The existing `v2/backend/tests/unit/services/__init__.py` package marker is reused as-is and is NOT re-emitted by 2F.B.

## Public surface (exact `__all__`)

`v2/backend/app/services/orchestrator_decision/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `assemble_orchestrator_decision_record`
2. `OrchestratorDecisionServiceError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the two re-exports.

## OrchestratorDecisionServiceError

`errors.py` defines:

```
from __future__ import annotations


class OrchestratorDecisionServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "OrchestratorDecisionServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Function signature

`service.py` defines exactly one public function:

```
def assemble_orchestrator_decision_record(
    *,
    prediction: TrainerPredictionRecord,
    low_confidence_threshold: float,
    now_ms_clock: Callable[[], int],
) -> OrchestratorDecisionRecord:
    ...
```

The function is keyword-only (the leading `*` makes all three parameters keyword-only). It has no default values for any parameter. It returns an `OrchestratorDecisionRecord` value object (the same frozen dataclass authored by 2F.A).

The function MUST NOT capture or memoize any of the three parameters. It MUST NOT mutate any global state. It MUST NOT spawn threads, processes, or subprocesses. It MUST NOT log via `logging` or `print(`.

## Validation order in `assemble_orchestrator_decision_record`

The function performs the following ordered checks. The order is deterministic and is verified by tests. Each step raises `OrchestratorDecisionServiceError(code, field=...)` with the specified `code` and `field`.

1. `prediction` is an instance of `TrainerPredictionRecord`. Otherwise raise `OrchestratorDecisionServiceError("must_be_trainer_prediction_record", field="prediction")`.
2. `low_confidence_threshold` is `float` and not `bool`. Otherwise raise `OrchestratorDecisionServiceError("must_be_float", field="low_confidence_threshold")`.
3. `low_confidence_threshold` is finite (`math.isfinite`). Otherwise raise `OrchestratorDecisionServiceError("must_be_finite", field="low_confidence_threshold")`.
4. `low_confidence_threshold` is in `[0.0, 1.0]` inclusive. Otherwise raise `OrchestratorDecisionServiceError("must_be_in_unit_interval", field="low_confidence_threshold")`.
5. `now_ms_clock` is callable. Otherwise raise `OrchestratorDecisionServiceError("must_be_callable", field="now_ms_clock")`.
6. Call `now_ms_clock()` exactly once. Bind the return value to `now_ms`.
7. `type(now_ms) is int` (and not `bool`). Otherwise raise `OrchestratorDecisionServiceError("must_be_int", field="now_ms_clock")`.
8. `now_ms >= 0`. Otherwise raise `OrchestratorDecisionServiceError("must_be_nonnegative", field="now_ms_clock")`.
9. `len(prediction.prediction_id) <= 124`. Otherwise raise `OrchestratorDecisionServiceError("prediction_id_too_long_for_decision_id_derivation", field="prediction.prediction_id")`. The 124-character cap keeps the derived `decision_id` within the 128-character cap enforced by the 2F.A `OrchestratorDecisionRecord.decision_id` invariant.

After the nine validation steps pass, the function performs the default-deny derivation table below and returns a frozen `OrchestratorDecisionRecord`.

## decision_id derivation

`decision_id = "dec_" + prediction.prediction_id`. The derivation is deterministic and pure. The string `"dec_"` is a four-character literal. The maximum length of `decision_id` is `4 + 124 = 128`, exactly the 2F.A invariant cap.

## Default-deny derivation table (ordered)

The first matching condition wins. The order is fixed and is verified by tests.

1. `prediction.freshness_flag == "missing"` → `decision_action = "abstain"`, `decision_reason_code = "abstain_freshness_missing"`.
2. `prediction.freshness_flag == "stale"` → `decision_action = "abstain"`, `decision_reason_code = "abstain_freshness_stale"`.
3. `prediction.worker_health_status == "CRITICAL"` → `decision_action = "abstain"`, `decision_reason_code = "abstain_worker_critical"`.
4. `prediction.worker_health_status == "DEGRADED"` → `decision_action = "abstain"`, `decision_reason_code = "abstain_worker_degraded"`.
5. `prediction.worker_health_status == "UNKNOWN"` → `decision_action = "abstain"`, `decision_reason_code = "abstain_worker_unknown"`.
6. `prediction.confidence_calibrated < low_confidence_threshold` → `decision_action = "abstain"`, `decision_reason_code = "abstain_low_confidence"`. The boundary value `prediction.confidence_calibrated == low_confidence_threshold` is NOT abstain-low-confidence; it falls through to the action-by-direction branches.
7. `prediction.direction == "flat"` → `decision_action = "hold"`, `decision_reason_code = "hold_flat_direction"`.
8. `prediction.direction == "long"` → `decision_action = "open_long"`, `decision_reason_code = "proceed_long"`.
9. `prediction.direction == "short"` → `decision_action = "open_short"`, `decision_reason_code = "proceed_short"`.

The function uses the imported domain-layer constants `DECISION_ACTION_*` and `DECISION_REASON_*` from `v2.backend.app.domain.orchestrator_decision` and `PREDICTION_DIRECTION_*` and `PREDICTION_FRESHNESS_*` from `v2.backend.app.domain.trainer_prediction_output` for these literal comparisons; the literal strings above are documentation only.

The four worker-health literal strings `"CRITICAL"`, `"DEGRADED"`, `"UNKNOWN"`, `"HEALTHY"` appear inline as string comparisons; the trainer prediction output domain does NOT export public worker-health constants and 2F.B does NOT introduce them.

## OrchestratorDecisionRecord construction

After derivation, the function returns:

```
OrchestratorDecisionRecord(
    decision_id=decision_id,
    prediction_id=prediction.prediction_id,
    feature_snapshot_id=prediction.feature_snapshot_id,
    symbol=prediction.symbol,
    decision_ts_ms=now_ms,
    decision_action=decision_action,
    decision_reason_code=decision_reason_code,
    input_prediction_direction=prediction.direction,
    input_prediction_confidence_calibrated=prediction.confidence_calibrated,
    input_prediction_freshness_flag=prediction.freshness_flag,
    input_worker_health_status=prediction.worker_health_status,
    live_blocked=True,
)
```

`live_blocked` is the literal Python boolean `True` at every call site. The function MUST NOT accept any caller-provided `live_blocked` value.

## Imports allowed in service.py

- `from __future__ import annotations`
- `import math`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.orchestrator_decision import (DECISION_ACTION_ABSTAIN, DECISION_ACTION_HOLD, DECISION_ACTION_OPEN_LONG, DECISION_ACTION_OPEN_SHORT, DECISION_REASON_ABSTAIN_FRESHNESS_MISSING, DECISION_REASON_ABSTAIN_FRESHNESS_STALE, DECISION_REASON_ABSTAIN_LOW_CONFIDENCE, DECISION_REASON_ABSTAIN_WORKER_CRITICAL, DECISION_REASON_ABSTAIN_WORKER_DEGRADED, DECISION_REASON_ABSTAIN_WORKER_UNKNOWN, DECISION_REASON_HOLD_FLAT_DIRECTION, DECISION_REASON_PROCEED_LONG, DECISION_REASON_PROCEED_SHORT, OrchestratorDecisionRecord)`
- `from v2.backend.app.domain.trainer_prediction_output import (PREDICTION_DIRECTION_FLAT, PREDICTION_DIRECTION_LONG, PREDICTION_DIRECTION_SHORT, PREDICTION_FRESHNESS_MISSING, PREDICTION_FRESHNESS_STALE, TrainerPredictionRecord)`
- `from .errors import OrchestratorDecisionServiceError`

No other import is permitted in `service.py`. No `typing` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `redis*` import. No `httpx` import. No `requests` import. No `fastapi` import. No `url_env` import. No factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, or any other `v2.backend.app.services.*` sibling.

## Imports allowed in __init__.py

- `from .service import assemble_orchestrator_decision_record`
- `from .errors import OrchestratorDecisionServiceError`

`__all__` is defined explicitly with the two names in the public-surface order. No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Forbidden tokens in source files

The three authored source files MUST NOT contain any of the following literal substrings (case sensitive):

- `redis`
- `Redis`
- `aioredis`
- `hiredis`
- `httpx`
- `requests`
- `fastapi`
- `FastAPI`
- `uvicorn`
- `subprocess`
- `socket`
- `os.environ`
- `os.getenv`
- `time.time`
- `time.monotonic`
- `datetime.now`
- `datetime.utcnow`
- `logging`
- `print(`
- `url_env`
- `gamma.real`

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The harness BEGIN/END framing token marker line is also forbidden in any authored file body.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/14_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST cite each of the following 6 behavior contract steps with a one-line evidence pointer to function and line range in `service.py`:

1. The five up-front validation steps (prediction instance, threshold type, threshold finite, threshold range, clock callable) run BEFORE the clock is invoked.
2. The clock is invoked exactly once and its return value is bound to `now_ms` and validated for type and non-negativity before use.
3. The 124-character cap on `prediction.prediction_id` is enforced before `decision_id` is derived and only depends on the prediction value, not on the threshold or the clock.
4. The default-deny derivation table runs in the order documented in `10_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SPEC.md` 'Default-deny derivation table (ordered)'.
5. The `OrchestratorDecisionRecord` is constructed with `live_blocked=True` as a literal boolean and propagates `prediction.prediction_id`, `prediction.feature_snapshot_id`, `prediction.symbol`, `prediction.direction`, `prediction.confidence_calibrated`, `prediction.freshness_flag`, and `prediction.worker_health_status` without modification.
6. The function returns the `OrchestratorDecisionRecord` value object directly; no caching, side effect, logging, or telemetry hop is interposed between construction and return.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/14_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md` (one of the markers documented in `13_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`).

PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SPEC_READY
