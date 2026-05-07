# Phase 2J.C — Paper Mode Runtime Flag Composition Root Spec

This document is the authoring spec for Phase 2J.C of REQ_0006 ∩ REQ_0017. It is the third and final sub-phase of the `PAPER_MODE_MVP` milestone. It builds a NEW composition package `v2/backend/app/composition/paper_mode/` whose only purpose is to expose a pure binder `build_paper_mode_runtime(...)` that captures the injected `now_ms_clock` at build time and returns a slotted `PaperModeRuntime` instance whose single attribute (`paper_mode_now`) is a keyword-only closure that adapts the 2J.B assembler-service surface to the captured-clock pattern.

The package is purely composition-surface oriented. It does NOT validate the requested mode (the 2J.B service is the single boundary that resolves the mirror taxonomy). It does NOT call a model. It does NOT touch I/O, files, Redis, or HTTP. It does NOT register any FastAPI surface. It does NOT compute PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted return. It does NOT introduce ledger or replay persistence (SQL, SQLite, JSON, Parquet, CSV, Redis, in-memory dict acting as a ledger). Importing the package MUST NOT cause the literal `red`+`is`, `red`+`is.asyncio`, `aio`+`red`+`is`, `hi`+`red`+`is`, `fast`+`api`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or the literal `url`+`_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The binder MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2J.B Codex review pass: `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
- 2J.B implementation pass: `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/15_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md`.
- 2J.A Codex review pass: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md`.
- 2J.A implementation pass: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/07_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO.md`.

If any marker is absent or different, the supervisor MUST NOT dispatch the 2J.C composition-root implementation task.

## Module location decision

The new package is `v2/backend/app/composition/paper_mode/`. It is a sibling of `v2/backend/app/composition/orchestrator_decision/`, `v2/backend/app/composition/risk_gateway/`, `v2/backend/app/composition/trainer_prediction_output/`, `v2/backend/app/composition/trainer_worker_health/`, `v2/backend/app/composition/trainer_parity/`, `v2/backend/app/composition/paper_execution_ledger/`, and `v2/backend/app/composition/replay_backtest_runner/`. It does NOT live inside any of those, because the paper-mode composition surface is a distinct REQ_0017 milestone-6 binder per `00_PHASE_2J_SUB_PHASE_BREAKDOWN.md`.

There is no `v2/backend/app/composition/paper_mode.py` flat-file placeholder at the time 2J.C opens. 2J.C creates the new package without deleting any existing composition-layer file. The package marker `v2/backend/app/composition/__init__.py` is reused as-is and is NOT re-emitted by this milestone. The pre-existing `v2/backend/app/services/paper_loop.py` placeholder remains untouched and unmodified. The pre-existing `v2/backend/app/services/replay_runner.py` placeholder remains untouched and unmodified. The pre-existing `v2/backend/app/domain/execution/` directory remains unpopulated.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, 2I.C, 2J.A, or 2J.B file is modified by 2J.C.

## Scope (additive only)

Files to create (exact set, no extras):

- `v2/backend/app/composition/paper_mode/__init__.py`
- `v2/backend/app/composition/paper_mode/errors.py`
- `v2/backend/app/composition/paper_mode/runtime.py`
- `v2/backend/tests/unit/composition/paper_mode/__init__.py`
- 22 sibling test files enumerated in `19_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/composition/paper_mode/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `build_paper_mode_runtime`
2. `PaperModeRuntime`
3. `PaperModeRuntimeCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## PaperModeRuntimeCompositionError

`errors.py` defines:

```
from __future__ import annotations


class PaperModeRuntimeCompositionError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "PaperModeRuntimeCompositionError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`field` is REQUIRED (no default). The class is a plain `Exception` subclass — NOT a `ValueError`. This intentionally differs from the 2J.B service `PaperModeServiceError(ValueError)` and from the 2J.A domain `PaperModeDomainError(ValueError)` so that callers can discriminate build-time misconfiguration of the binder from call-time service-layer rejection of inputs and from value-object rejection. `errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, the literal `red`+`is`, `aio`+`red`+`is`, `hi`+`red`+`is`, `red`+`is.asyncio`, the gamma.real factory, or `url`+`_env`.

## PaperModeRuntime slotted class

`runtime.py` defines a slotted final-shape class:

```
class PaperModeRuntime:
    __slots__ = ("paper_mode_now",)

    def __init__(
        self,
        *,
        paper_mode_now: Callable[..., PaperModeFlag],
    ) -> None:
        self.paper_mode_now = paper_mode_now
```

Hard invariants:

- `__slots__` is exactly the 1-tuple `("paper_mode_now",)` in that order.
- The class MUST NOT define `__dict__` (slotted instances reject foreign attribute attachment).
- The class MUST NOT declare `__weakref__` in `__slots__`.
- The class MUST NOT define any other method, classmethod, staticmethod, or property.
- The `__init__` parameter is keyword-only.
- `__init__` MUST NOT call the assembler at construction time.
- `__init__` MUST NOT validate that the supplied callable is a 2J.B service closure; the binder is the only producer in this codebase, and validation happens at the binder layer.
- The class MUST NOT subclass any other class beyond `object`.

The single attribute `paper_mode_now` is exposed as an instance attribute referencing a closure created by `build_paper_mode_runtime`. Consumers invoke `runtime.paper_mode_now(requested_mode=...)`. The invocation forwards to the 2J.B service with the captured clock injected by the binder.

## build_paper_mode_runtime

`runtime.py` defines a pure binder:

```
def build_paper_mode_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> PaperModeRuntime
```

All parameters are keyword-only. The binder takes ONLY `now_ms_clock`. There is no run-id parameter, no symbol filter, no requested-mode pre-binding parameter, no persistence handle, no storage adapter, no PnL/position-sizing parameter, and no expansion of any kind. The 2J.B assembler service is the single source of truth for the mirror taxonomy and for clock invocation; the binder only captures the clock and adapts the call surface.

Behavior contract, in this exact order:

1. If `now_ms_clock` is not callable (per the builtin `callable(...)` test), raise `PaperModeRuntimeCompositionError("must_be_callable", field="now_ms_clock")`. The clock is NOT invoked during this check.
2. Bind `_now_ms_clock = now_ms_clock` to a closure variable. Do NOT call `_now_ms_clock` at build time. Do NOT call the assembler service function at build time. Do NOT cache any value derived from the clock at build time. Do NOT log the clock identity.
3. Define an inner closure `_paper_mode_now(*, requested_mode: str) -> PaperModeFlag` whose body is exactly a single `return assemble_paper_mode_flag(requested_mode=requested_mode, now_ms_clock=_now_ms_clock)` statement. The inner closure MUST NOT mutate any caller-supplied input. The inner closure MUST NOT call `_now_ms_clock` directly; the assembler service is the single caller of the clock per the 2J.B contract.
4. Construct and return `PaperModeRuntime(paper_mode_now=_paper_mode_now)`.

Any `PaperModeServiceError` raised by the assembler propagates unchanged. Any `PaperModeDomainError` raised by the underlying value-object `__post_init__` propagates unchanged. The composition root does NOT catch, wrap, or rewrap service or domain errors; consumers catch the most specific class directly.

## Imports allowed in runtime.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.paper_mode import PaperModeFlag`
- `from v2.backend.app.services.paper_mode import assemble_paper_mode_flag`
- `from .errors import PaperModeRuntimeCompositionError`

No other import is permitted in `runtime.py`. No third-party import. No `typing` import. No `dataclasses` import. No `math` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `selectors` import. No literal `red`+`is*` import. No `httpx` import. No `requests` import. No `fast`+`api` import. No literal `url`+`_env` import. No factory import. No import of `v2.backend.app.services.trainer_worker_health`, `v2.backend.app.services.trainer_parity`, `v2.backend.app.services.trainer_prediction_output`, `v2.backend.app.services.orchestrator_decision`, `v2.backend.app.services.risk_gateway`, `v2.backend.app.services.paper_execution_ledger`, `v2.backend.app.services.replay_backtest_runner`, `v2.backend.app.composition.trainer_worker_health`, `v2.backend.app.composition.trainer_parity`, `v2.backend.app.composition.trainer_prediction_output`, `v2.backend.app.composition.orchestrator_decision`, `v2.backend.app.composition.risk_gateway`, `v2.backend.app.composition.paper_execution_ledger`, `v2.backend.app.composition.replay_backtest_runner`, `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.risk_gateway`, `v2.backend.app.domain.paper_execution_ledger`, `v2.backend.app.domain.replay_backtest_runner`, or any other `v2/backend/app/` subpackage. The only stdlib imports are `from __future__ import annotations` and `from collections.abc import Callable`.

The annotation on the inner closure and the slotted-class `__init__` parameter references `PaperModeFlag`. With `from __future__ import annotations`, the reference is evaluated lazily as a string; the import is required for static analysis and explicit dependency declaration but does NOT cause the symbol to be invoked at module load.

## Imports allowed in __init__.py

- `from .errors import PaperModeRuntimeCompositionError`
- `from .runtime import PaperModeRuntime, build_paper_mode_runtime`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2J.C composition root MUST preserve the redis-clean import invariant identical to Phase 2E1.E, 2E2.C, 2E3.B, 2E3.C, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, 2I.C, 2J.A, and 2J.B:

- No direct literal-`red`+`is` import.
- No `red`+`is.asyncio` import.
- No `aio`+`red`+`is` import.
- No `hi`+`red`+`is` import.
- No `httpx` import.
- No `requests` import.
- No `v2.backend.app.adapters.redis_v2.url_env` import.
- No transitive load of literal `red`+`is`, `url`+`_env`, the gamma.real factory, `fast`+`api`, or `uvicorn` when the composition package is imported, asserted by `sys.modules` guard tests run in fresh subprocesses.

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
- `RiskDecisionRecord`
- `OrchestratorDecisionRecord`
- `RISK_DECISION_REASON_DENY_DEFAULT`
- `deny_default`
- `mirror_deny_default`
- `PaperExecutionLedgerEntry`
- `ReplayBacktestStep`
- `ReplayBacktestSummary`
- `ReplayBacktestRun`
- `sqlite`
- `sqlalchemy`
- `parquet`
- `PaperModeFlag(`
- `BEGIN_FILE`
- `END_FILE`

NO exemption applies. The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary`, and `ReplayBacktestRun` tokens are on the forbidden list because 2J.C MUST NOT import or reference upstream domain symbols that are unrelated to the paper-mode flag boundary. The reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, and the literal `mirror_deny_default` are forbidden in the three authored source files because the composition root forwards records and inputs unchanged to the 2J.B assembler service; the service is the single boundary that resolves the mode mirror taxonomy. The call-form token `PaperModeFlag(` is forbidden in the three authored source files because the composition root MUST NOT directly construct any value object; the value object flows through unchanged from the 2J.B service. The `sqlite`, `sqlalchemy`, and `parquet` tokens are on the forbidden list to prevent any accidental introduction of replay or ledger persistence at the composition layer.

## Module-level invariants

The three authored source files MUST NOT contain any of the following at module scope:

- A FastAPI startup hook, lifespan handler, dependency, or router registration.
- A module-level singleton, cache, or lock.
- A module-level call to `_now_ms_clock`, the assembler service function, or any wall-clock helper.
- A wall-clock helper call (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`).
- A logging call or stdout call.
- An `os.environ` read.
- A `subprocess` invocation or a `socket` use.
- A URL string, a token-shaped string, a key-shaped string, or any credential-shaped string.
- A background task or executor.
- A direct call-form construction of `PaperModeFlag`. The composition root MUST NOT construct the value object; it forwards through the 2J.B assembler service which is the single boundary that constructs the value object with `live_blocked=True`.

## Build-time vs call-time invariants

- The clock MUST NOT be invoked during `build_paper_mode_runtime(...)`.
- The 2J.B assembler service function MUST NOT be invoked during `build_paper_mode_runtime(...)`.
- The callable check on `now_ms_clock` MUST be performed at build time per the single-step validation order documented above.
- The inner closure returned by the binder MUST close over the same `_now_ms_clock` reference passed to the binder. The test corpus asserts clock-identity equality across paper_mode_now invocations.
- The inner closure MUST invoke the 2J.B service function exactly once per call. The binder closes over `_now_ms_clock` and forwards it on the single assembler call.
- The inner closure MUST NOT mutate any caller-supplied input. The `requested_mode` parameter is passed through unchanged.
- The inner closure MUST raise `PaperModeServiceError` (from the 2J.B service) and `PaperModeDomainError` (from the 2J.A domain) without wrapping; the binder defines no try/except around the assembler call.
- The inner closure MUST NOT persist the value object. Persistence (if any) is the responsibility of a future REQ_0017 milestone-7 shadow-mode runtime; 2J.C returns the value object to its caller.

PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_SPEC_READY
