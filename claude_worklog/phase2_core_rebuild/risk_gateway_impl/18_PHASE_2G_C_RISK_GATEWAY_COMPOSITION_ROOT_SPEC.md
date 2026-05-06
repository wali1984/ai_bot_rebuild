# Phase 2G.C — Risk Gateway Composition Root Spec

This document is the authoring spec for Phase 2G.C of REQ_0006 ∩ REQ_0017. It is the third and final sub-phase of the `RISK_GATEWAY_DEFAULT_DENY_MVP` milestone. It builds a NEW composition package `v2/backend/app/composition/risk_gateway/` whose only purpose is to expose a pure binder `build_risk_decision_evaluator(...)` that captures the injected `now_ms_clock` at build time and returns a single-call evaluator callable that adapts the 2G.B assembler service to a single keyword-argument call (`decision: OrchestratorDecisionRecord`) returning `RiskDecisionRecord`.

The package is purely composition-surface oriented. It does NOT compute risk decisions. It does NOT call a model. It does NOT touch I/O, files, or HTTP. It does NOT register any FastAPI surface. Importing the package MUST NOT cause the literal `red` + `is`, `red` + `is.asyncio`, `aio` + `red` + `is`, `hi` + `red` + `is`, `fast` + `api`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or the literal `url` + `_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The binder MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2G.B Codex review pass: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
- 2G.B implementation pass: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`.

If either marker is absent or different, the supervisor MUST NOT dispatch `131_risk_gateway_2gc_composition_root_implementation`.

## Module location decision

The new package is `v2/backend/app/composition/risk_gateway/`. It is a sibling of `v2/backend/app/composition/orchestrator_decision/`, `v2/backend/app/composition/trainer_prediction_output/`, `v2/backend/app/composition/trainer_worker_health/`, and `v2/backend/app/composition/trainer_parity/`. It does NOT live inside any of those, because the risk gateway composition surface is a distinct REQ_0017 milestone-3 binder per `00_PHASE_2G_SUB_PHASE_BREAKDOWN.md`.

There is no `v2/backend/app/composition/risk_gateway.py` placeholder file at the time 2G.C opens (verified by inspecting `v2/backend/app/composition/`: only the empty `__init__.py` and the four sibling sub-packages exist). 2G.C creates the new package without deleting any existing composition-layer file. The package marker `v2/backend/app/composition/__init__.py` is reused as-is and is NOT re-emitted by this milestone.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, or 2G.B file is modified by 2G.C.

## Scope (additive only)

Files to create (exact set, no extras):

- `v2/backend/app/composition/risk_gateway/__init__.py`
- `v2/backend/app/composition/risk_gateway/errors.py`
- `v2/backend/app/composition/risk_gateway/runtime.py`
- `v2/backend/tests/unit/composition/risk_gateway/__init__.py`
- 24 sibling test files enumerated in `19_PHASE_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/composition/risk_gateway/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `build_risk_decision_evaluator`
2. `RiskDecisionEvaluator`
3. `RiskGatewayCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## RiskGatewayCompositionError

`errors.py` defines:

```
from __future__ import annotations


class RiskGatewayCompositionError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "RiskGatewayCompositionError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`field` is REQUIRED (no default). The class is a plain `Exception` subclass — NOT a `ValueError`. This intentionally differs from the 2G.B service `RiskGatewayServiceError(ValueError)` so that callers can distinguish build-time misconfiguration of the binder from call-time service-layer rejection of inputs. It also intentionally differs from the 2G.A domain `RiskGatewayDomainError(ValueError)`. `errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, the literal `red` + `is`, `aio` + `red` + `is`, `hi` + `red` + `is`, `red` + `is.asyncio`, the gamma.real factory, or `url` + `_env`.

## RiskDecisionEvaluator type alias

`runtime.py` declares the evaluator type as:

```
RiskDecisionEvaluator = Callable[..., RiskDecisionRecord]
```

This intentionally widens the parameter slot to `...` because the evaluator forwards a single keyword-only argument to the assembler service and Python does not yet have a stable way to express keyword-only-callable typing without third-party libraries. The runtime invariant (single keyword-only `decision` parameter, no positional acceptance, no mutation, single assembler invocation per call, captured clock) is enforced by behavior tests, not by the type alias.

## build_risk_decision_evaluator

`runtime.py` defines a pure binder:

```
def build_risk_decision_evaluator(
    *,
    now_ms_clock: Callable[[], int],
) -> RiskDecisionEvaluator
```

All parameters are keyword-only. The binder takes ONLY `now_ms_clock`. There is no threshold parameter. The risk gateway has no threshold knob; the default-deny taxonomy is exhaustive over the four orchestrator action branches authored in 2G.B and is the single source of truth.

Behavior contract, in this exact order:

1. If `now_ms_clock` is not callable (per the builtin `callable(...)` test), raise `RiskGatewayCompositionError("must_be_callable", field="now_ms_clock")`. The clock is NOT invoked during this check.
2. Bind `_now_ms_clock = now_ms_clock` to a closure variable. Do NOT call `_now_ms_clock` at build time. Do NOT call `assemble_risk_decision_record` at build time. Do NOT cache any value derived from the clock at build time. Do NOT log the clock identity.
3. Define an inner function `_evaluator(*, decision: OrchestratorDecisionRecord) -> RiskDecisionRecord` whose body is exactly a single `return assemble_risk_decision_record(decision=decision, now_ms_clock=_now_ms_clock)` statement. The inner function MUST NOT mutate any caller-supplied input. The inner function MUST NOT call `_now_ms_clock` directly; the assembler service is the single caller of the clock.
4. Return `_evaluator`.

Any `RiskGatewayServiceError` raised by the assembler propagates unchanged. Any `RiskGatewayDomainError` raised by the underlying record `__post_init__` propagates unchanged. The composition root does NOT catch, wrap, or rewrap service or domain errors; consumers catch the most specific class directly.

## Imports allowed in runtime.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord`
- `from v2.backend.app.domain.risk_gateway import RiskDecisionRecord`
- `from v2.backend.app.services.risk_gateway import assemble_risk_decision_record`
- `from .errors import RiskGatewayCompositionError`

No other import is permitted in `runtime.py`. No third-party import. No `typing` import. No `dataclasses` import. No `math` import (no numeric validation occurs in this binder). No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `selectors` import. No literal `red` + `is*` import. No `httpx` import. No `requests` import. No `fast` + `api` import. No literal `url` + `_env` import. No factory import. No import of `v2.backend.app.services.trainer_worker_health`, `v2.backend.app.services.trainer_parity`, `v2.backend.app.services.trainer_prediction_output`, `v2.backend.app.services.orchestrator_decision`, `v2.backend.app.composition.trainer_worker_health`, `v2.backend.app.composition.trainer_parity`, `v2.backend.app.composition.trainer_prediction_output`, `v2.backend.app.composition.orchestrator_decision`, or any other `v2/backend/app/` subpackage. The only stdlib imports are `from __future__ import annotations` and `from collections.abc import Callable`.

## Imports allowed in __init__.py

- `from .errors import RiskGatewayCompositionError`
- `from .runtime import RiskDecisionEvaluator, build_risk_decision_evaluator`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2G.C composition root MUST preserve the redis-clean import invariant identical to Phase 2E1.E, 2E2.C, 2E3.B, 2E3.C, 2F.B, 2F.C, 2G.A, and 2G.B:

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
- `RISK_DECISION_REASON_DENY_DEFAULT`
- `deny_default`

NO exemption applies. The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The two reserved 2G.A constants `RISK_DECISION_REASON_DENY_DEFAULT` and the literal value `deny_default` are added to the forbidden list because 2G.C MUST NOT introduce or re-export them at the composition layer; the 2G.B assembler service is the single boundary that may emit risk-reason codes, and that service does not emit `deny_default` in the four-branch default-deny mapping.

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

- The clock MUST NOT be invoked during `build_risk_decision_evaluator(...)`.
- The assembler service `assemble_risk_decision_record` MUST NOT be invoked during `build_risk_decision_evaluator(...)`.
- The callable check on `now_ms_clock` MUST be performed at build time per the single-step validation order documented above.
- The evaluator returned by the binder MUST invoke the assembler exactly once per call. The binder closes over `_now_ms_clock` and forwards it on the single assembler call.
- The evaluator MUST NOT mutate any caller-supplied input. The `decision` parameter is passed through unchanged.
- The evaluator MUST raise `RiskGatewayServiceError` (from the 2G.B service) and `RiskGatewayDomainError` (from the 2G.A domain) without wrapping; the binder defines no try/except around the assembler call.

## Cross-isolation invariants

Phase 2G.C authors no file under any of the following paths and modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
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
- `v2/backend/tests/unit/composition/orchestrator_decision/`
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
- any `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` artifact at 00-17 (prior 2G.A and 2G.B and the 2G.C planning artifacts at 18-21 themselves once written)
- any `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and `trainer_gpu_parity_impl/` artifact

## Hard stops

The 2G.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, or 2G.B.
- read or write any literal `red` + `is` key.
- invoke any literal `red` + `is` command.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit any credential.
- approve the live gate.
- emit a standalone marker line in any authored file body matching the harness BEGIN/END framing tokens.
- introduce any execution-side surface, paper executor, shadow executor, replay runner, paper ledger, or strategy library.
- introduce a FastAPI or HTTP surface.
- introduce an adapter or a service-layer expansion outside the existing 2G.B boundary.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `risk_decision_id` already derived inside the 2G.B service.
- import or emit the reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT` or the literal `deny_default`.

PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_SPEC_READY
