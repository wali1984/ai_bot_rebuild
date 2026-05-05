# Phase 2F.C — Orchestrator Decision Composition Root Spec

This document is the authoring spec for Phase 2F.C of REQ_0006 ∩ REQ_0017. It is the third and final sub-phase of the `ORCHESTRATOR_DECISION_MVP` milestone. It builds a NEW composition package `v2/backend/app/composition/orchestrator_decision/` whose only purpose is to expose a pure binder `build_orchestrator_decision_evaluator(...)` that captures the injected `low_confidence_threshold` and `now_ms_clock` at build time and returns a single-call evaluator callable that adapts the 2F.B assembler service to a single keyword-argument call (`prediction: TrainerPredictionRecord`) returning `OrchestratorDecisionRecord`.

The package is purely composition-surface oriented. It does NOT compute decisions. It does NOT call a model. It does NOT touch I/O, files, or HTTP. It does NOT register any FastAPI surface. Importing the package MUST NOT cause the literal `red` + `is`, `red` + `is.asyncio`, `aio` + `red` + `is`, `hi` + `red` + `is`, `fast` + `api`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or the literal `url` + `_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The binder MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2F.B Codex review pass: `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/17_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `124_orchestrator_decision_2fc_composition_root_implementation`.

## Module location decision

The new package is `v2/backend/app/composition/orchestrator_decision/`. It is a sibling of `v2/backend/app/composition/trainer_prediction_output/`, `v2/backend/app/composition/trainer_worker_health/`, and `v2/backend/app/composition/trainer_parity/`. It does NOT live inside any of those, because the orchestrator decision composition surface is a distinct REQ_0017 milestone-2 binder per `00_PHASE_2F_SUB_PHASE_BREAKDOWN.md`.

There is no `v2/backend/app/composition/orchestrator_decision.py` placeholder file at the time 2F.C opens (verified by the predecessor scope: 2F.B did not author or reference any composition-layer placeholder). 2F.C creates the new package without deleting any existing composition-layer file.

No 2E1, 2E2, 2E3.A/2E3.B/2E3.C, 2F.A, or 2F.B file is modified by 2F.C.

## Scope (additive only)

Files to create (exact set, no extras):

- `v2/backend/app/composition/orchestrator_decision/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/errors.py`
- `v2/backend/app/composition/orchestrator_decision/runtime.py`
- `v2/backend/tests/unit/composition/orchestrator_decision/__init__.py`
- 28 sibling test files enumerated in `19_PHASE_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/composition/orchestrator_decision/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `build_orchestrator_decision_evaluator`
2. `OrchestratorDecisionEvaluator`
3. `OrchestratorDecisionCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## OrchestratorDecisionCompositionError

`errors.py` defines:

```
from __future__ import annotations


class OrchestratorDecisionCompositionError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "OrchestratorDecisionCompositionError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`field` is REQUIRED (no default). The class is a plain `Exception` subclass — NOT a `ValueError`. This intentionally differs from the 2F.B service `OrchestratorDecisionServiceError(ValueError)` so that callers can distinguish build-time misconfiguration of the binder from call-time service-layer rejection of inputs. `errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, the literal `red` + `is`, `aio` + `red` + `is`, `hi` + `red` + `is`, `red` + `is.asyncio`, the gamma.real factory, or `url` + `_env`.

## OrchestratorDecisionEvaluator type alias

`runtime.py` declares the evaluator type as:

```
OrchestratorDecisionEvaluator = Callable[..., OrchestratorDecisionRecord]
```

This intentionally widens the parameter slot to `...` because the evaluator forwards a single keyword-only argument to the assembler service and Python does not yet have a stable way to express keyword-only-callable typing without third-party libraries. The runtime invariant (single keyword-only `prediction` parameter, no positional acceptance, no mutation, single assembler invocation per call, captured threshold and clock) is enforced by behavior tests, not by the type alias.

## build_orchestrator_decision_evaluator

`runtime.py` defines a pure binder:

```
def build_orchestrator_decision_evaluator(
    *,
    low_confidence_threshold: float,
    now_ms_clock: Callable[[], int],
) -> OrchestratorDecisionEvaluator
```

All parameters are keyword-only.

Behavior contract, in this exact order:

1. If `low_confidence_threshold` is not a `float` instance, or is a `bool`, raise `OrchestratorDecisionCompositionError("must_be_float", field="low_confidence_threshold")`. The clock is NOT invoked during this check.
2. If `low_confidence_threshold` is not finite (per `math.isfinite`), raise `OrchestratorDecisionCompositionError("must_be_finite", field="low_confidence_threshold")`.
3. If `low_confidence_threshold` is not in the closed unit interval `[0.0, 1.0]`, raise `OrchestratorDecisionCompositionError("must_be_in_unit_interval", field="low_confidence_threshold")`.
4. If `now_ms_clock` is not callable (per the builtin `callable(...)` test), raise `OrchestratorDecisionCompositionError("must_be_callable", field="now_ms_clock")`. The clock is NOT invoked during this check.
5. Bind `_low_confidence_threshold = low_confidence_threshold` and `_now_ms_clock = now_ms_clock` to closure variables. Do NOT call `_now_ms_clock` at build time. Do NOT call `assemble_orchestrator_decision_record` at build time. Do NOT cache any value derived from the clock at build time. Do NOT log the clock identity or the threshold value.
6. Define an inner function `_evaluator(*, prediction: TrainerPredictionRecord) -> OrchestratorDecisionRecord` whose body is exactly a single `return assemble_orchestrator_decision_record(prediction=prediction, low_confidence_threshold=_low_confidence_threshold, now_ms_clock=_now_ms_clock)` statement. The inner function MUST NOT mutate any caller-supplied input. The inner function MUST NOT call `_now_ms_clock` directly; the assembler service is the single caller of the clock. The inner function MUST NOT touch the threshold beyond forwarding the closure variable.
7. Return `_evaluator`.

Any `OrchestratorDecisionServiceError` raised by the assembler propagates unchanged. Any `OrchestratorDecisionDomainError` raised by the underlying record `__post_init__` propagates unchanged. The composition root does NOT catch, wrap, or rewrap service or domain errors; consumers catch the most specific class directly.

## Imports allowed in runtime.py

- `from __future__ import annotations`
- `import math`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord`
- `from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord`
- `from v2.backend.app.services.orchestrator_decision import assemble_orchestrator_decision_record`
- `from .errors import OrchestratorDecisionCompositionError`

No other import is permitted in `runtime.py`. No third-party import. No `typing` import. No `dataclasses` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `selectors` import. No literal `red` + `is*` import. No `httpx` import. No `requests` import. No `fast` + `api` import. No literal `url` + `_env` import. No factory import. No import of `v2.backend.app.services.trainer_worker_health`, `v2.backend.app.services.trainer_parity`, `v2.backend.app.services.trainer_prediction_output`, `v2.backend.app.composition.trainer_worker_health`, `v2.backend.app.composition.trainer_parity`, `v2.backend.app.composition.trainer_prediction_output`, or any other `v2/backend/app/` subpackage. The only stdlib imports are `from __future__ import annotations`, `import math`, and `from collections.abc import Callable`.

## Imports allowed in __init__.py

- `from .errors import OrchestratorDecisionCompositionError`
- `from .runtime import OrchestratorDecisionEvaluator, build_orchestrator_decision_evaluator`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2F.C composition root MUST preserve the redis-clean import invariant identical to Phase 2E1.E, 2E2.C, 2E3.B, 2E3.C, and 2F.B:

- No direct literal-`red` + `is` import.
- No `red` + `is.asyncio` import.
- No `aio` + `red` + `is` import.
- No `hi` + `red` + `is` import.
- No `httpx` import.
- No `requests` import.
- No `v2.backend.app.adapters.redis_v2.url_env` import.
- No transitive load of literal `red` + `is`, `url` + `_env`, the gamma.real factory, `fast` + `api`, or `uvicorn` when the composition package is imported, asserted by `sys.modules` guard tests run in fresh subprocesses.

## Forbidden tokens in source files

The three authored source files (`__init__.py`, `errors.py`, `runtime.py`) MUST NOT contain any of the following literal substrings, verified by `rg --fixed-strings --case-sensitive`:

- `redis`
- `Redis`
- `REDIS`
- `aioredis`
- `hiredis`
- `httpx`
- `requests`
- `url_env`
- `URL_ENV`
- `os.environ`
- `getenv`
- `subprocess`
- `socket`
- `selectors`
- `pathlib`
- `time.time`
- `time.monotonic`
- `time.sleep`
- `datetime.now`
- `datetime.utcnow`
- `datetime`
- `print(`
- `logging.`
- `logging`
- `FastAPI`
- `fastapi`
- `APIRouter`
- `lifespan`
- `Depends`
- `BackgroundTasks`
- `lru_cache`
- `cached_property`
- `threading`
- `multiprocessing`
- `asyncio`
- `eval(`
- `exec(`
- `compile(`
- `pickle`
- `marshal`
- `__import__`
- `importlib`

NO exemption applies. The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

## Module-level invariants

The three authored source files MUST NOT contain any of the following at module scope:

- A FastAPI startup hook, lifespan handler, dependency, or router registration.
- A module-level singleton, cache, or lock.
- A module-level call to `_now_ms_clock`, the assembler service, or any wall-clock helper.
- A wall-clock helper call (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`).
- A logging call or stdout call.
- An `os.environ` read.
- A `subprocess` invocation or a `socket` use.
- A URL string, a token-shaped string, a key-shaped string, or any credential-shaped string.
- A background task or executor.

## Build-time vs call-time invariants

- The clock MUST NOT be invoked during `build_orchestrator_decision_evaluator(...)`.
- The assembler service `assemble_orchestrator_decision_record` MUST NOT be invoked during `build_orchestrator_decision_evaluator(...)`.
- The threshold MUST be validated at build time per the four-step validation order documented above (float / not bool, finite, range, then the callable check on the clock).
- The evaluator returned by the binder MUST invoke the assembler exactly once per call. The binder closes over `_low_confidence_threshold` and `_now_ms_clock` and forwards both on the single assembler call.
- The evaluator MUST NOT mutate any caller-supplied input. The `prediction` parameter is passed through unchanged.
- The evaluator MUST raise `OrchestratorDecisionServiceError` (from the 2F.B service) and `OrchestratorDecisionDomainError` (from the 2F.A domain) without wrapping; the binder defines no try/except around the assembler call.

## Cross-isolation invariants

Phase 2F.C authors no file under any of the following paths and modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/services/`
- `v2/backend/app/adapters/`
- `v2/backend/app/domain/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/__init__.py`
- `v2/backend/tests/unit/composition/__init__.py`
- `v2/backend/tests/unit/composition/trainer_parity/`
- `v2/backend/tests/unit/composition/trainer_worker_health/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- any `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` artifact at 00-17 (prior 2F.A/2F.B and the 2F.C planning artifacts at 18-21 themselves once written)
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and `trainer_gpu_parity_impl/` artifact

## Hard stops

The 2F.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, 2E3.A/2E3.B/2E3.C, 2F.A, or 2F.B.
- read or write any Redis key.
- invoke any Redis command.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit any credential.
- approve the live gate.
- emit a standalone marker line in any authored file body matching the harness BEGIN/END framing tokens.

PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_SPEC_READY
