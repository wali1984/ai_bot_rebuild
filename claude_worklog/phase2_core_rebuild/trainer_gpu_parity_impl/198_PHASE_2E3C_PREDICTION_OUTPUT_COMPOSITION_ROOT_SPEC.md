# Phase 2E3.C — Trainer Prediction Output Composition Root Spec

This document is the authoring spec for Phase 2E3.C of REQ_0006 ∩ REQ_0017. It is the third and final sub-phase of the `TRAINER_PREDICTION_OUTPUT_MVP` milestone. It builds a NEW composition package `v2/backend/app/composition/trainer_prediction_output/` whose only purpose is to expose a pure binder `build_trainer_prediction_output_evaluator(...)` that captures the injected clock at build time and returns a single-call evaluator callable that adapts the 2E3.B assembler service to a single keyword-argument call returning `TrainerPredictionRecord`.

The package is purely composition-surface oriented. It does NOT compute predictions. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT register any FastAPI surface. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2E3.B Codex review pass: `PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/197_2E3B_PREDICTION_RECORD_ASSEMBLER_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `115_trainer_parity_2e3c_prediction_output_composition_root_implementation`.

## 178 naming reconciliation

`178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md` projected the 2E3.B Codex pass marker as `PHASE2E3B_TRAINER_PREDICTION_OUTPUT_SERVICE_CODEX_PASS`. The actually-emitted marker is `PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_CODEX_PASS`. 178 is a prior-milestone artifact and is NOT modified. This spec uses the actually-emitted marker as authoritative.

`178` projected the 2E3.C implementation task as `114` and the 2E3.C Codex review task as `115`. Task IDs `113` and `114` were consumed by 2E3.B implementation and 2E3.B Codex review. The actual task IDs for 2E3.C are `115` (implementation) and `116` (Codex review).

## Module location decision

The new package is a sibling of the existing `v2/backend/app/composition/trainer_worker_health/` and `v2/backend/app/composition/trainer_parity/` packages. It does NOT live inside any of those, because the prediction output composition surface is a distinct Stage A trainer output binder per `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md` and `178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md`.

No 2E1, 2E2, or 2E3.A/2E3.B file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/composition/trainer_prediction_output/__init__.py`
- `v2/backend/app/composition/trainer_prediction_output/errors.py`
- `v2/backend/app/composition/trainer_prediction_output/runtime.py`
- `v2/backend/tests/unit/composition/trainer_prediction_output/__init__.py`
- 20 sibling test files enumerated in `199_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/composition/trainer_prediction_output/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `build_trainer_prediction_output_evaluator`
2. `TrainerPredictionOutputEvaluator`
3. `TrainerPredictionOutputCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## TrainerPredictionOutputCompositionError

`errors.py` defines:

```
class TrainerPredictionOutputCompositionError(Exception):
    def __init__(self, code: str, *, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.field is not None:
            return f"{self.code} ({self.field})"
        return self.code
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, the gamma.real factory, or `url_env`.

## TrainerPredictionOutputEvaluator type alias

`runtime.py` declares the evaluator type as a `Callable` returning `TrainerPredictionRecord`. The exact form is:

```
TrainerPredictionOutputEvaluator = Callable[..., TrainerPredictionRecord]
```

This intentionally widens the parameter slot to `...` because the evaluator forwards keyword-only arguments to the assembler service and Python does not yet have a stable way to express keyword-only-callable typing without third-party libraries. The runtime invariant (keyword-only forwarding, no positional acceptance, no mutation, single assembler invocation per call) is enforced by behavior tests, not by the type alias.

## build_trainer_prediction_output_evaluator

`runtime.py` defines a pure binder:

```
def build_trainer_prediction_output_evaluator(
    *,
    now_ms_clock: Callable[[], int],
) -> TrainerPredictionOutputEvaluator
```

All parameters are keyword-only.

Behavior contract, in this exact order:

1. If `now_ms_clock` is not callable (per the builtin `callable(...)` test), raise `TrainerPredictionOutputCompositionError("must_be_callable", field="now_ms_clock")`. The clock is NOT invoked during this check.
2. Bind `_now_ms_clock = now_ms_clock` to a closure variable. Do NOT call `_now_ms_clock` at build time. Do NOT cache any value derived from the clock at build time. Do NOT log the clock identity.
3. Define an inner function `_evaluator(*, prediction_id, feature_snapshot_id, symbol, model_version, checkpoint_id, direction, confidence_raw, confidence_calibrated, worker_id, worker_health_status, freshness_flag, source_freshness_age_ms, top_positive_feature_codes, top_negative_feature_codes) -> TrainerPredictionRecord` whose body is exactly a single `return assemble_prediction_record(prediction_id=prediction_id, feature_snapshot_id=feature_snapshot_id, symbol=symbol, model_version=model_version, checkpoint_id=checkpoint_id, direction=direction, confidence_raw=confidence_raw, confidence_calibrated=confidence_calibrated, worker_id=worker_id, worker_health_status=worker_health_status, freshness_flag=freshness_flag, source_freshness_age_ms=source_freshness_age_ms, top_positive_feature_codes=top_positive_feature_codes, top_negative_feature_codes=top_negative_feature_codes, now_ms_clock=_now_ms_clock)` statement. The inner function MUST NOT mutate any caller-supplied input. The inner function MUST NOT call `_now_ms_clock` directly; the assembler service is the single caller of the clock.
4. Return `_evaluator`.

Any `TrainerPredictionOutputServiceError` raised by the assembler propagates unchanged. Any `TrainerPredictionDomainError` raised by the underlying record `__post_init__` propagates unchanged. The composition root does NOT catch, wrap, or rewrap service or domain errors; consumers catch the most specific class directly.

## Imports allowed in runtime.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord`
- `from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record`
- `from .errors import TrainerPredictionOutputCompositionError`

No other import is permitted in `runtime.py`. No standard-library import beyond `__future__` and `collections.abc`. No `typing` import. No `dataclasses` import. No `math` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `redis*` import. No `httpx` import. No `requests` import. No `fastapi` import. No `url_env` import. No factory import. No import of `v2.backend.app.services.trainer_worker_health`, `v2.backend.app.services.trainer_parity`, `v2.backend.app.composition.trainer_worker_health`, `v2.backend.app.composition.trainer_parity`, or any other `v2/backend/app/` subpackage.

## Imports allowed in __init__.py

- `from .errors import TrainerPredictionOutputCompositionError`
- `from .runtime import TrainerPredictionOutputEvaluator, build_trainer_prediction_output_evaluator`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2E3.C composition root MUST preserve the redis-clean import invariant identical to Phase 2E1.E, 2E2.C, and 2E3.B:

- No direct `redis` import.
- No `redis.asyncio` import.
- No `aioredis` import.
- No `hiredis` import.
- No `httpx` import.
- No `requests` import.
- No `v2.backend.app.adapters.redis_v2.url_env` import.
- No transitive load of `redis`, `url_env`, the gamma.real factory, `fastapi`, or `uvicorn` when the composition package is imported, asserted by `sys.modules` guard tests.

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

NO exemption applies. The forbidden-token test file constructs each literal at runtime via string concatenation so the test file itself does NOT contain the bare token.

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

- The clock MUST NOT be invoked during `build_trainer_prediction_output_evaluator(...)`.
- The assembler service `assemble_prediction_record` MUST NOT be invoked during `build_trainer_prediction_output_evaluator(...)`.
- The evaluator returned by the binder MUST invoke the assembler exactly once per call. The binder closes over `_now_ms_clock` and forwards it on the single assembler call.
- The evaluator MUST NOT mutate any caller-supplied input. The 14 lineage parameters are passed through unchanged.
- The evaluator MUST raise `TrainerPredictionOutputServiceError` (from the 2E3.B service) and `TrainerPredictionDomainError` (from the 2E3.A domain) without wrapping; the binder defines no try/except around the assembler call.

## Cross-isolation invariants

Phase 2E3.C authors no file under any of the following paths and modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
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
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/179_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SPEC.md` and any prior 2E3.A artifact at 180-189
- any 2E3.B artifact at 190-197

## Hard stops

The 2E3.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, or 2E3.A/2E3.B.
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

PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_SPEC_READY
