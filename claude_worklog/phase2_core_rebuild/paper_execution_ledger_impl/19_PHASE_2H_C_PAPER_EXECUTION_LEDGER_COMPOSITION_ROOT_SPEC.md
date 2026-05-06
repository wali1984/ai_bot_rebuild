# Phase 2H.C — Paper Execution Ledger Composition Root Spec

This document is the authoring spec for Phase 2H.C of REQ_0006 ∩ REQ_0017. It is the third and final sub-phase of the `PAPER_EXECUTION_LEDGER_MVP` milestone. It builds a NEW composition package `v2/backend/app/composition/paper_execution_ledger/` whose only purpose is to expose a pure binder `build_paper_execution_ledger_recorder(...)` that captures the injected `now_ms_clock` at build time and returns a single-call recorder callable that adapts the 2H.B assembler service to a single keyword-argument call (`decision: RiskDecisionRecord`) returning `PaperExecutionLedgerEntry`.

The package is purely composition-surface oriented. It does NOT compute paper-ledger entries. It does NOT call a model. It does NOT touch I/O, files, Redis, or HTTP. It does NOT register any FastAPI surface. It does NOT compute PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted return. It does NOT introduce any ledger persistence (SQL, SQLite, JSON, Parquet, CSV, Redis, in-memory dict acting as a ledger). Importing the package MUST NOT cause the literal `red`+`is`, `red`+`is.asyncio`, `aio`+`red`+`is`, `hi`+`red`+`is`, `fast`+`api`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or the literal `url`+`_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The binder MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2H.B Codex review pass: `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
- 2H.B implementation pass: `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md`.

If either marker is absent or different, the supervisor MUST NOT dispatch the 2H.C composition-root implementation task.

## Module location decision

The new package is `v2/backend/app/composition/paper_execution_ledger/`. It is a sibling of `v2/backend/app/composition/orchestrator_decision/`, `v2/backend/app/composition/risk_gateway/`, `v2/backend/app/composition/trainer_prediction_output/`, `v2/backend/app/composition/trainer_worker_health/`, and `v2/backend/app/composition/trainer_parity/`. It does NOT live inside any of those, because the paper execution ledger composition surface is a distinct REQ_0017 milestone-4 binder per `00_PHASE_2H_SUB_PHASE_BREAKDOWN.md`.

There is no `v2/backend/app/composition/paper_execution_ledger.py` placeholder file at the time 2H.C opens. 2H.C creates the new package without deleting any existing composition-layer file. The package marker `v2/backend/app/composition/__init__.py` is reused as-is and is NOT re-emitted by this milestone. The pre-existing `v2/backend/app/services/paper_loop.py` placeholder remains untouched and unmodified.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, or 2H.B file is modified by 2H.C.

## Scope (additive only)

Files to create (exact set, no extras):

- `v2/backend/app/composition/paper_execution_ledger/__init__.py`
- `v2/backend/app/composition/paper_execution_ledger/errors.py`
- `v2/backend/app/composition/paper_execution_ledger/runtime.py`
- `v2/backend/tests/unit/composition/paper_execution_ledger/__init__.py`
- 25 sibling test files enumerated in `20_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/composition/paper_execution_ledger/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `build_paper_execution_ledger_recorder`
2. `PaperExecutionLedgerRecorder`
3. `PaperExecutionLedgerCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## PaperExecutionLedgerCompositionError

`errors.py` defines:

```
from __future__ import annotations


class PaperExecutionLedgerCompositionError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "PaperExecutionLedgerCompositionError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`field` is REQUIRED (no default). The class is a plain `Exception` subclass — NOT a `ValueError`. This intentionally differs from the 2H.B service `PaperExecutionLedgerServiceError(ValueError)` so that callers can distinguish build-time misconfiguration of the binder from call-time service-layer rejection of inputs. It also intentionally differs from the 2H.A domain `PaperExecutionLedgerDomainError(ValueError)`. `errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, the literal `red`+`is`, `aio`+`red`+`is`, `hi`+`red`+`is`, `red`+`is.asyncio`, the gamma.real factory, or `url`+`_env`.

## PaperExecutionLedgerRecorder type alias

`runtime.py` declares the recorder type as:

```
PaperExecutionLedgerRecorder = Callable[..., PaperExecutionLedgerEntry]
```

This intentionally widens the parameter slot to `...` because the recorder forwards a single keyword-only argument to the assembler service and Python does not yet have a stable way to express keyword-only-callable typing without third-party libraries. The runtime invariant (single keyword-only `decision` parameter, no positional acceptance, no mutation, single assembler invocation per call, captured clock) is enforced by behavior tests, not by the type alias.

## build_paper_execution_ledger_recorder

`runtime.py` defines a pure binder:

```
def build_paper_execution_ledger_recorder(
    *,
    now_ms_clock: Callable[[], int],
) -> PaperExecutionLedgerRecorder
```

All parameters are keyword-only. The binder takes ONLY `now_ms_clock`. There is no threshold parameter, no persistence handle, no storage adapter, no symbol filter, no PnL/position-sizing parameter, and no replay-mode flag. The paper execution ledger has no threshold knob at the composition layer; the mirror taxonomy is exhaustive over the five risk-reason branches authored in 2H.B and is the single source of truth.

Behavior contract, in this exact order:

1. If `now_ms_clock` is not callable (per the builtin `callable(...)` test), raise `PaperExecutionLedgerCompositionError("must_be_callable", field="now_ms_clock")`. The clock is NOT invoked during this check.
2. Bind `_now_ms_clock = now_ms_clock` to a closure variable. Do NOT call `_now_ms_clock` at build time. Do NOT call `assemble_paper_execution_ledger_entry` at build time. Do NOT cache any value derived from the clock at build time. Do NOT log the clock identity.
3. Define an inner function `_recorder(*, decision: RiskDecisionRecord) -> PaperExecutionLedgerEntry` whose body is exactly a single `return assemble_paper_execution_ledger_entry(decision=decision, now_ms_clock=_now_ms_clock)` statement. The inner function MUST NOT mutate any caller-supplied input. The inner function MUST NOT call `_now_ms_clock` directly; the assembler service is the single caller of the clock per the 2H.B contract.
4. Return `_recorder`.

Any `PaperExecutionLedgerServiceError` raised by the assembler propagates unchanged. Any `PaperExecutionLedgerDomainError` raised by the underlying record `__post_init__` propagates unchanged. The composition root does NOT catch, wrap, or rewrap service or domain errors; consumers catch the most specific class directly.

## Imports allowed in runtime.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry`
- `from v2.backend.app.domain.risk_gateway import RiskDecisionRecord`
- `from v2.backend.app.services.paper_execution_ledger import assemble_paper_execution_ledger_entry`
- `from .errors import PaperExecutionLedgerCompositionError`

No other import is permitted in `runtime.py`. No third-party import. No `typing` import. No `dataclasses` import. No `math` import (no numeric validation occurs in this binder). No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `selectors` import. No literal `red`+`is*` import. No `httpx` import. No `requests` import. No `fast`+`api` import. No literal `url`+`_env` import. No factory import. No import of `v2.backend.app.services.trainer_worker_health`, `v2.backend.app.services.trainer_parity`, `v2.backend.app.services.trainer_prediction_output`, `v2.backend.app.services.orchestrator_decision`, `v2.backend.app.services.risk_gateway`, `v2.backend.app.composition.trainer_worker_health`, `v2.backend.app.composition.trainer_parity`, `v2.backend.app.composition.trainer_prediction_output`, `v2.backend.app.composition.orchestrator_decision`, `v2.backend.app.composition.risk_gateway`, `v2.backend.app.domain.orchestrator_decision`, or any other `v2/backend/app/` subpackage. The only stdlib imports are `from __future__ import annotations` and `from collections.abc import Callable`.

## Imports allowed in __init__.py

- `from .errors import PaperExecutionLedgerCompositionError`
- `from .runtime import PaperExecutionLedgerRecorder, build_paper_execution_ledger_recorder`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2H.C composition root MUST preserve the redis-clean import invariant identical to Phase 2E1.E, 2E2.C, 2E3.B, 2E3.C, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, and 2H.B:

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
- `OrchestratorDecisionRecord`
- `sqlite`
- `sqlalchemy`
- `parquet`
- `RISK_DECISION_REASON_DENY_DEFAULT`
- `deny_default`

NO exemption applies. The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The `OrchestratorDecisionRecord` token is on the forbidden list because 2H.C MUST NOT import the upstream orchestrator-decision domain symbol; it imports the `RiskDecisionRecord` type from `v2.backend.app.domain.risk_gateway` and forwards it to the 2H.B service. The `sqlite`, `sqlalchemy`, and `parquet` tokens are on the forbidden list to prevent any accidental introduction of ledger persistence at the composition layer. The reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT` and the literal lowercase `deny_default` are forbidden in the three authored source files because the composition root forwards the record reference unchanged to the 2H.B assembler service; the service is the single boundary that resolves the mirror taxonomy.

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
- A direct construction of `PaperExecutionLedgerEntry`. The composition root MUST NOT construct entries; it forwards through the 2H.B assembler service which is the single boundary that constructs entries with `live_blocked=True`.

## Build-time vs call-time invariants

- The clock MUST NOT be invoked during `build_paper_execution_ledger_recorder(...)`.
- The assembler service `assemble_paper_execution_ledger_entry` MUST NOT be invoked during `build_paper_execution_ledger_recorder(...)`.
- The callable check on `now_ms_clock` MUST be performed at build time per the single-step validation order documented above.
- The recorder returned by the binder MUST invoke the assembler exactly once per call. The binder closes over `_now_ms_clock` and forwards it on the single assembler call.
- The recorder MUST NOT mutate any caller-supplied input. The `decision` parameter is passed through unchanged.
- The recorder MUST raise `PaperExecutionLedgerServiceError` (from the 2H.B service) and `PaperExecutionLedgerDomainError` (from the 2H.A domain) without wrapping; the binder defines no try/except around the assembler call.
- The recorder MUST NOT persist the entry. Persistence (if any) is the responsibility of a future REQ_0017 milestone-5 replay/backtest runner; 2H.C returns the entry to its caller.

## Cross-isolation invariants

Phase 2H.C authors no file under any of the following paths and modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/composition/risk_gateway/`
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
- `v2/backend/tests/unit/composition/risk_gateway/`
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
- any `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and `trainer_gpu_parity_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/decision_explainability/` artifact
- any `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` artifact at 00-22 (prior 2H.A, 2H.B, and the 2H.C planning artifacts at 19-22 themselves once written)

## Hard stops

The 2H.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, or 2H.B.
- read or write any literal `red`+`is` key.
- invoke any literal `red`+`is` command.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit any credential.
- approve the live gate.
- emit a standalone marker line in any authored file body matching the harness BEGIN/END framing tokens.
- introduce any execution-side surface beyond the existing 2H.A / 2H.B / 2H.C ledger boundary, paper executor, shadow executor, replay runner, or strategy library.
- introduce a FastAPI or HTTP surface.
- introduce an adapter or a service-layer expansion outside the existing 2H.B boundary.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `paper_trade_id` already derived inside the 2H.B service.
- import or emit `OrchestratorDecisionRecord`, the reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT`, or the literal lowercase `deny_default` in any authored 2H.C source file.
- introduce ledger persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger).
- introduce PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted-return computation.
- modify `v2/backend/app/services/paper_loop.py`.
- populate `v2/backend/app/domain/execution/`.
- introduce a `v2/backend/app/composition/paper_execution_ledger.py` flat-file placeholder.
- successfully construct any `PaperExecutionLedgerEntry` with `live_blocked == False`.

PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC_READY
