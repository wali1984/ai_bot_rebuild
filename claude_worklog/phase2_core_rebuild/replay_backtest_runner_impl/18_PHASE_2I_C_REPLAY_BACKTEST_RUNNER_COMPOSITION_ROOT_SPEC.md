# Phase 2I.C — Replay/Backtest Runner Composition Root Spec

This document is the authoring spec for Phase 2I.C of REQ_0006 ∩ REQ_0017. It is the third and final sub-phase of the `REPLAY_BACKTEST_RUNNER_MVP` milestone. It builds a NEW composition package `v2/backend/app/composition/replay_backtest_runner/` whose only purpose is to expose a pure binder `build_replay_backtest_runner(...)` that captures the injected `now_ms_clock` at build time and returns a slotted `ReplayBacktestRunner` instance whose two attributes (`assemble_step`, `assemble_summary`) are keyword-only closures that adapt the 2I.B assembler-service surface to the captured-clock pattern.

The package is purely composition-surface oriented. It does NOT compute replay/backtest steps or summaries. It does NOT call a model. It does NOT touch I/O, files, Redis, or HTTP. It does NOT register any FastAPI surface. It does NOT compute PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted return. It does NOT introduce ledger or replay persistence (SQL, SQLite, JSON, Parquet, CSV, Redis, in-memory dict acting as a ledger). Importing the package MUST NOT cause the literal `red`+`is`, `red`+`is.asyncio`, `aio`+`red`+`is`, `hi`+`red`+`is`, `fast`+`api`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or the literal `url`+`_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The binder MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2I.B Codex review pass: `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/17_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
- 2I.B implementation pass: `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md`.
- 2I.A Codex review pass: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md`.
- 2I.A implementation pass: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md`.

If any marker is absent or different, the supervisor MUST NOT dispatch the 2I.C composition-root implementation task.

## Module location decision

The new package is `v2/backend/app/composition/replay_backtest_runner/`. It is a sibling of `v2/backend/app/composition/orchestrator_decision/`, `v2/backend/app/composition/risk_gateway/`, `v2/backend/app/composition/trainer_prediction_output/`, `v2/backend/app/composition/trainer_worker_health/`, `v2/backend/app/composition/trainer_parity/`, and `v2/backend/app/composition/paper_execution_ledger/`. It does NOT live inside any of those, because the replay/backtest runner composition surface is a distinct REQ_0017 milestone-5 binder per `00_PHASE_2I_SUB_PHASE_BREAKDOWN.md`.

There is no `v2/backend/app/composition/replay_backtest_runner.py` flat-file placeholder at the time 2I.C opens. 2I.C creates the new package without deleting any existing composition-layer file. The package marker `v2/backend/app/composition/__init__.py` is reused as-is and is NOT re-emitted by this milestone. The pre-existing `v2/backend/app/services/replay_runner.py` placeholder remains untouched and unmodified. The pre-existing `v2/backend/app/services/paper_loop.py` placeholder remains untouched and unmodified. The pre-existing `v2/backend/app/domain/execution/` directory remains unpopulated.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, or 2I.B file is modified by 2I.C.

## Scope (additive only)

Files to create (exact set, no extras):

- `v2/backend/app/composition/replay_backtest_runner/__init__.py`
- `v2/backend/app/composition/replay_backtest_runner/errors.py`
- `v2/backend/app/composition/replay_backtest_runner/runtime.py`
- `v2/backend/tests/unit/composition/replay_backtest_runner/__init__.py`
- 35 sibling test files enumerated in `19_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/composition/replay_backtest_runner/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `build_replay_backtest_runner`
2. `ReplayBacktestRunner`
3. `ReplayBacktestRunnerCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## ReplayBacktestRunnerCompositionError

`errors.py` defines:

```
from __future__ import annotations


class ReplayBacktestRunnerCompositionError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "ReplayBacktestRunnerCompositionError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`field` is REQUIRED (no default). The class is a plain `Exception` subclass — NOT a `ValueError`. This intentionally differs from the 2I.B service `ReplayBacktestRunnerServiceError(ValueError)` and from the 2I.A domain `ReplayBacktestRunnerDomainError(ValueError)` so that callers can discriminate build-time misconfiguration of the binder from call-time service-layer rejection of inputs and from value-object rejection. `errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, the literal `red`+`is`, `aio`+`red`+`is`, `hi`+`red`+`is`, `red`+`is.asyncio`, the gamma.real factory, or `url`+`_env`.

## ReplayBacktestRunner slotted class

`runtime.py` defines a slotted final-shape class:

```
class ReplayBacktestRunner:
    __slots__ = ("assemble_step", "assemble_summary")

    def __init__(
        self,
        *,
        assemble_step: Callable[..., ReplayBacktestStep],
        assemble_summary: Callable[..., ReplayBacktestSummary],
    ) -> None:
        self.assemble_step = assemble_step
        self.assemble_summary = assemble_summary
```

Hard invariants:

- `__slots__` is exactly the 2-tuple `("assemble_step", "assemble_summary")` in that order.
- The class MUST NOT define `__dict__` (slotted instances reject foreign attribute attachment).
- The class MUST NOT define `__weakref__` in `__slots__`.
- The class MUST NOT define any other method, classmethod, staticmethod, or property.
- Both `__init__` parameters are keyword-only.
- `__init__` MUST NOT call either assembler at construction time.
- `__init__` MUST NOT validate that the supplied callables are 2I.B service closures; the binder is the only producer in this codebase, and validation happens at the binder layer.
- The class MUST NOT subclass any other class beyond `object`.

The two attributes `assemble_step` and `assemble_summary` are exposed as instance attributes referencing closures created by `build_replay_backtest_runner`. Consumers invoke `runner.assemble_step(paper_ledger_entry=..., replay_run=...)` and `runner.assemble_summary(replay_run=..., steps=...)`. Both invocations forward to the 2I.B service with the captured clock injected by the binder.

## build_replay_backtest_runner

`runtime.py` defines a pure binder:

```
def build_replay_backtest_runner(
    *,
    now_ms_clock: Callable[[], int],
) -> ReplayBacktestRunner
```

All parameters are keyword-only. The binder takes ONLY `now_ms_clock`. There is no run-id parameter, no symbol filter, no replay-mode flag, no persistence handle, no storage adapter, no PnL/position-sizing parameter, and no expansion of any kind. The 2I.B assembler service is the single source of truth for the mirror taxonomy and for clock invocation; the binder only captures the clock and adapts the call surface.

Behavior contract, in this exact order:

1. If `now_ms_clock` is not callable (per the builtin `callable(...)` test), raise `ReplayBacktestRunnerCompositionError("must_be_callable", field="now_ms_clock")`. The clock is NOT invoked during this check.
2. Bind `_now_ms_clock = now_ms_clock` to a closure variable. Do NOT call `_now_ms_clock` at build time. Do NOT call either assembler service function at build time. Do NOT cache any value derived from the clock at build time. Do NOT log the clock identity.
3. Define an inner closure `_assemble_step(*, paper_ledger_entry: PaperExecutionLedgerEntry, replay_run: ReplayBacktestRun) -> ReplayBacktestStep` whose body is exactly a single `return assemble_replay_backtest_step(paper_ledger_entry=paper_ledger_entry, replay_run=replay_run, now_ms_clock=_now_ms_clock)` statement. The inner closure MUST NOT mutate any caller-supplied input. The inner closure MUST NOT call `_now_ms_clock` directly; the assembler service is the single caller of the clock per the 2I.B contract.
4. Define an inner closure `_assemble_summary(*, replay_run: ReplayBacktestRun, steps: tuple[ReplayBacktestStep, ...]) -> ReplayBacktestSummary` whose body is exactly a single `return assemble_replay_backtest_summary(replay_run=replay_run, steps=steps, now_ms_clock=_now_ms_clock)` statement. The inner closure MUST NOT mutate any caller-supplied input. The inner closure MUST NOT call `_now_ms_clock` directly.
5. Construct and return `ReplayBacktestRunner(assemble_step=_assemble_step, assemble_summary=_assemble_summary)`.

Both inner closures MUST share the same captured `_now_ms_clock` closure cell; the test corpus asserts clock-identity equality across the two attribute invocations. Any `ReplayBacktestRunnerServiceError` raised by either assembler propagates unchanged. Any `ReplayBacktestRunnerDomainError` raised by the underlying value-object `__post_init__` propagates unchanged. The composition root does NOT catch, wrap, or rewrap service or domain errors; consumers catch the most specific class directly.

## Imports allowed in runtime.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry`
- `from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestStep, ReplayBacktestSummary`
- `from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step, assemble_replay_backtest_summary`
- `from .errors import ReplayBacktestRunnerCompositionError`

No other import is permitted in `runtime.py`. No third-party import. No `typing` import. No `dataclasses` import. No `math` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `selectors` import. No literal `red`+`is*` import. No `httpx` import. No `requests` import. No `fast`+`api` import. No literal `url`+`_env` import. No factory import. No import of `v2.backend.app.services.trainer_worker_health`, `v2.backend.app.services.trainer_parity`, `v2.backend.app.services.trainer_prediction_output`, `v2.backend.app.services.orchestrator_decision`, `v2.backend.app.services.risk_gateway`, `v2.backend.app.services.paper_execution_ledger`, `v2.backend.app.composition.trainer_worker_health`, `v2.backend.app.composition.trainer_parity`, `v2.backend.app.composition.trainer_prediction_output`, `v2.backend.app.composition.orchestrator_decision`, `v2.backend.app.composition.risk_gateway`, `v2.backend.app.composition.paper_execution_ledger`, `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.risk_gateway`, or any other `v2/backend/app/` subpackage. The only stdlib imports are `from __future__ import annotations` and `from collections.abc import Callable`.

The annotations on the inner closures and the slotted-class `__init__` parameters reference `PaperExecutionLedgerEntry`, `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary`. With `from __future__ import annotations`, these references are evaluated lazily as strings; the imports are required for static analysis and explicit dependency declaration but do NOT cause the symbols to be invoked at module load.

## Imports allowed in __init__.py

- `from .errors import ReplayBacktestRunnerCompositionError`
- `from .runtime import ReplayBacktestRunner, build_replay_backtest_runner`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2I.C composition root MUST preserve the redis-clean import invariant identical to Phase 2E1.E, 2E2.C, 2E3.B, 2E3.C, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, and 2I.B:

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
- `sqlite`
- `sqlalchemy`
- `parquet`
- `ReplayBacktestStep(`
- `ReplayBacktestSummary(`
- `PaperExecutionLedgerEntry(`
- `ReplayBacktestRun(`
- `BEGIN_FILE`
- `END_FILE`

NO exemption applies. The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The `RiskDecisionRecord` and `OrchestratorDecisionRecord` tokens are on the forbidden list because 2I.C MUST NOT import or reference upstream risk-gateway or orchestrator-decision domain symbols. The reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, and the literal `mirror_deny_default` are forbidden in the three authored source files because the composition root forwards records and entries unchanged to the 2I.B assembler service; the service is the single boundary that resolves the mirror taxonomy. The four call-form tokens `ReplayBacktestStep(`, `ReplayBacktestSummary(`, `PaperExecutionLedgerEntry(`, and `ReplayBacktestRun(` are forbidden in the three authored source files because the composition root MUST NOT directly construct any value object; entries and value objects flow through unchanged from the 2I.B service. The `sqlite`, `sqlalchemy`, and `parquet` tokens are on the forbidden list to prevent any accidental introduction of replay or ledger persistence at the composition layer.

## Module-level invariants

The three authored source files MUST NOT contain any of the following at module scope:

- A FastAPI startup hook, lifespan handler, dependency, or router registration.
- A module-level singleton, cache, or lock.
- A module-level call to `_now_ms_clock`, either assembler service function, or any wall-clock helper.
- A wall-clock helper call (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`).
- A logging call or stdout call.
- An `os.environ` read.
- A `subprocess` invocation or a `socket` use.
- A URL string, a token-shaped string, a key-shaped string, or any credential-shaped string.
- A background task or executor.
- A direct call-form construction of `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun`. The composition root MUST NOT construct value objects; it forwards through the 2I.B assembler service which is the single boundary that constructs the value objects with `live_blocked=True`.

## Build-time vs call-time invariants

- The clock MUST NOT be invoked during `build_replay_backtest_runner(...)`.
- Neither `assemble_replay_backtest_step` nor `assemble_replay_backtest_summary` MUST be invoked during `build_replay_backtest_runner(...)`.
- The callable check on `now_ms_clock` MUST be performed at build time per the single-step validation order documented above.
- Both inner closures returned by the binder MUST share the same captured `_now_ms_clock` closure cell. The test corpus asserts clock-identity equality across step and summary calls.
- Each inner closure MUST invoke its corresponding 2I.B service function exactly once per call. The binder closes over `_now_ms_clock` and forwards it on the single assembler call.
- The inner closures MUST NOT mutate any caller-supplied input. The `paper_ledger_entry`, `replay_run`, and `steps` parameters are passed through unchanged.
- The inner closures MUST raise `ReplayBacktestRunnerServiceError` (from the 2I.B service) and `ReplayBacktestRunnerDomainError` (from the 2I.A domain) without wrapping; the binder defines no try/except around either assembler call.
- The inner closures MUST NOT persist any value object. Persistence (if any) is the responsibility of a future REQ_0017 milestone-6 paper-mode runtime; 2I.C returns the value object to its caller.

## Cross-isolation invariants

Phase 2I.C authors no file under any of the following paths and modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/composition/paper_execution_ledger/`
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
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
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
- any `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/` artifact at 00-21 (prior 2I.A, 2I.B, and the 2I.C planning artifacts at 18-21 themselves once written)

## Hard stops

The 2I.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, or 2I.B.
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
- introduce any execution-side surface beyond the existing 2H.A / 2H.B / 2H.C ledger boundary plus the 2I.A / 2I.B / 2I.C replay/backtest runner boundary, paper executor, shadow executor, replay engine, scheduler, background loop, paper trader process, or strategy library.
- introduce a FastAPI or HTTP surface.
- introduce an adapter or a service-layer expansion outside the existing 2I.B boundary.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `replay_step_id` and `replay_summary_id` already derived inside the 2I.B service.
- import or reference `RiskDecisionRecord`, `OrchestratorDecisionRecord`, the reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, or the literal `mirror_deny_default` in any authored 2I.C source file.
- introduce ledger or replay persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger).
- introduce PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted-return computation.
- modify `v2/backend/app/services/replay_runner.py`.
- modify `v2/backend/app/services/paper_loop.py`.
- populate `v2/backend/app/domain/execution/`.
- introduce a `v2/backend/app/composition/replay_backtest_runner.py` flat-file placeholder.
- successfully construct any `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` with `live_blocked == False`.
- directly construct any `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` in any authored 2I.C source file.

PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC_READY
