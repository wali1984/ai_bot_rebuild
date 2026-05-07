# Phase 2K.B — Shadow-Mode-Readiness Flag Assembler Service Spec

This document is the authoring spec for Phase 2K.B of REQ_0006 ∩ REQ_0017. Phase 2K.B is the second sub-phase of the `SHADOW_MODE_READINESS` milestone (REQ_0017 milestone 7). It builds a NEW services-layer package `v2/backend/app/services/shadow_mode_readiness/` whose only purpose is to define one pure assembler function plus one service-level error class:

1. `assemble_shadow_mode_readiness_flag(*, requested_state: str, now_ms_clock: Callable[[], int]) -> ShadowModeReadinessFlag` — takes a requested-state string in the 2-element allowed set and a `now_ms_clock` callable; returns a frozen `ShadowModeReadinessFlag` constructed under the typed boundary fixed by 2K.A.
2. `ShadowModeReadinessServiceError` — service-level error class for input-validation failures. Domain-level invariants are enforced by 2K.A `__post_init__` and surface as `ShadowModeReadinessDomainError`.

The package is a pure derivation surface. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. It does NOT introduce any new lineage ID at the service layer beyond the typed `ShadowModeReadinessFlag` already defined in 2K.A. It does NOT introduce a `shadow_decision_id` lineage row at the 2K.B layer. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The function MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2K.A domain Codex pass: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/09_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_GO_NO_GO.md`.
- 2K.A domain implementation pass: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/07_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO.md`.
- 2J.C composition-root Codex pass: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

If any of these is absent or different, the supervisor MUST NOT dispatch `158_shadow_mode_readiness_2kb_flag_assembler_service_implementation`.

## Module location decision

The new package is `v2/backend/app/services/shadow_mode_readiness/`. It is a sibling of `v2/backend/app/services/paper_mode/`, `v2/backend/app/services/paper_execution_ledger/`, `v2/backend/app/services/replay_backtest_runner/`, `v2/backend/app/services/risk_gateway/`, `v2/backend/app/services/orchestrator_decision/`, `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

The pre-existing `v2/backend/app/services/paper_loop.py` (one-line scaffold docstring placeholder) is NOT modified, NOT used, and NOT renamed by 2K.B. The pre-existing `v2/backend/app/services/replay_runner.py` placeholder is NOT modified, NOT used, and NOT renamed by 2K.B. There is NO `v2/backend/app/services/shadow_mode_readiness.py` flat-file placeholder created by 2K.B; the new surface lives only at the package directory above.

No 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, 2I.C, 2J.A, 2J.B, 2J.C, 2K.A, 2G.A, 2G.B, 2G.C, 2F.A, 2F.B, 2F.C, 2E1, 2E2, or 2E3 file is modified by this milestone.

## Scope (additive only)

Filesystem mutations performed by task `158`:

- create: `v2/backend/app/services/shadow_mode_readiness/__init__.py`
- create: `v2/backend/app/services/shadow_mode_readiness/errors.py`
- create: `v2/backend/app/services/shadow_mode_readiness/service.py`
- create: `v2/backend/tests/unit/services/shadow_mode_readiness/__init__.py` (zero bytes)
- create: 30 single-test files enumerated in `11_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md`.
- create: `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/14_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- create: `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/15_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md`

The existing `v2/backend/tests/unit/services/__init__.py` package marker is reused as-is and is NOT re-emitted by 2K.B.

## Public surface (exact `__all__`)

`v2/backend/app/services/shadow_mode_readiness/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `assemble_shadow_mode_readiness_flag`
2. `ShadowModeReadinessServiceError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the two re-exports. There is NO requested-state branch labeled `live`, `live_enabled`, `live_mode`, `production`, `prod`, or any other live-execution synonym at any layer of the 2K.B service. There is NO `SHADOW_MODE_LIVE` constant, NO `SHADOW_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, and NO `shadow_decision_id` lineage row introduced at the 2K.B layer.

## Requested-state constants

The 2-element allowed-state set is exactly `{SHADOW_MODE_NOT_READY, SHADOW_MODE_READY}` (the two readiness-state constants imported from 2K.A). The service does NOT define new state constants. The literal strings `"not_ready"` and `"ready"` are the only valid values for the `requested_state` parameter.

## ShadowModeReadinessServiceError

`errors.py` defines:

```
from __future__ import annotations


class ShadowModeReadinessServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "ShadowModeReadinessServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Function signature

`service.py` defines exactly one public function:

```
def assemble_shadow_mode_readiness_flag(
    *,
    requested_state: str,
    now_ms_clock: Callable[[], int],
) -> ShadowModeReadinessFlag:
    ...
```

The function is keyword-only (the leading `*` makes every parameter keyword-only). The function has no default values for any parameter. The function returns a frozen `ShadowModeReadinessFlag` value object authored by 2K.A.

The function MUST NOT capture or memoize any of its parameters. The function MUST NOT mutate any global state. The function MUST NOT spawn threads, processes, or subprocesses. The function MUST NOT log via `logging` or `print(`.

## Validation order in `assemble_shadow_mode_readiness_flag`

The function performs the following ordered checks. The order is deterministic and is verified by tests. Each step raises `ShadowModeReadinessServiceError(code, field=...)` with the specified `code` and `field`.

1. `type(requested_state) is str` (subclasses of `str` are NOT accepted; `bool` is rejected because `bool` is not a `str`). Otherwise raise `ShadowModeReadinessServiceError("must_be_str", field="requested_state")`.
2. `now_ms_clock` is callable. Otherwise raise `ShadowModeReadinessServiceError("must_be_callable", field="now_ms_clock")`.
3. `requested_state in _ALLOWED_REQUESTED_STATES` where `_ALLOWED_REQUESTED_STATES = frozenset({SHADOW_MODE_NOT_READY, SHADOW_MODE_READY})`. Otherwise raise `ShadowModeReadinessServiceError("shadow_mode_readiness_service_unrecognized_requested_state", field="requested_state")`. This rejects the literal strings `"live"`, `"live_enabled"`, `"NOT_READY"`, `"READY"`, `"production"`, `"prod"`, `""`, and any other non-not_ready / non-ready string.
4. Call `now_ms_clock()` exactly once. Bind the return value to `now_ms`.
5. `type(now_ms) is int` (and not `bool`). Otherwise raise `ShadowModeReadinessServiceError("must_be_int", field="now_ms_clock")`. The `bool` exclusion uses `isinstance(value, bool)` rejection before the `type(value) is int` check, identical to the prior-milestone pattern.
6. `now_ms >= 0`. Otherwise raise `ShadowModeReadinessServiceError("must_be_nonnegative", field="now_ms_clock")`.

After the six validation steps pass, the function performs the 2-row mirror dispatch table below and returns a frozen `ShadowModeReadinessFlag`.

## Mirror dispatch table (exhaustive over the 2-element allowed set)

The first matching condition wins. The order is fixed and is verified by tests. The two cases are exhaustive over the 2K.A `_ALLOWED_STATES` frozenset.

1. `requested_state == SHADOW_MODE_NOT_READY` → `flag_state = SHADOW_MODE_NOT_READY`.
2. `requested_state == SHADOW_MODE_READY` → `flag_state = SHADOW_MODE_READY`.
3. Defensive fallback (unreachable under step 3 of the validation pipeline): raise `ShadowModeReadinessServiceError("shadow_mode_readiness_service_unrecognized_requested_state", field="requested_state")`.

The function uses the imported domain-layer constants `SHADOW_MODE_NOT_READY` and `SHADOW_MODE_READY` from `v2.backend.app.domain.shadow_mode_readiness` for both the allowed-set comparison and the `flag_state` assignment. The literal strings above are documentation only; the source MUST NOT contain a bare literal `"live"` or `"live_enabled"` or `"NOT_READY"` or `"READY"` or `"production"` or `"prod"` outside the documented allowed-set comparison and the validation-order error code.

There is NO third row in the dispatch table. Any future requested-state addition is forbidden inside 2K.B and MUST be re-spec'd as a new sub-phase under REQ_0017 / REQ_0018 / REQ_0020 with planner authorship and a fresh Codex review.

## ShadowModeReadinessFlag construction

After dispatch, the function returns:

```
ShadowModeReadinessFlag(
    state=flag_state,
    flag_emitted_ts_ms=now_ms,
    live_blocked=True,
)
```

`live_blocked` is the literal Python boolean `True` at the call site. The function MUST NOT accept any caller-provided `live_blocked` value. The function MUST NOT construct any `ShadowModeReadinessFlag` with `live_blocked == False`; the 2K.A `__post_init__` would refuse the construction, but the service layer MUST NOT attempt it in any code path.

The `flag_emitted_ts_ms` is the unique value returned by the single `now_ms_clock()` call performed in step 4 of the validation pipeline. The service MUST NOT call the clock more than once per invocation.

## Imports allowed in service.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.shadow_mode_readiness import (SHADOW_MODE_NOT_READY, SHADOW_MODE_READY, ShadowModeReadinessFlag)`
- `from .errors import ShadowModeReadinessServiceError`

No other import is permitted in `service.py`. No `math` import. No `typing` import. No `time`, `datetime`, `logging`, `os`, `subprocess`, `socket`, `pathlib`, `multiprocessing`, `threading`, `asyncio`, `redis*`, `httpx`, `requests`, `fastapi`, `uvicorn`, `starlette`, `urllib`, `urllib3`, `url_env`, factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`, `v2.backend.app.main.*`, or any other `v2.backend.app.services.*` sibling. No import of any `v2.backend.app.domain.paper_mode`, `v2.backend.app.domain.paper_execution_ledger`, `v2.backend.app.domain.replay_backtest_runner`, `v2.backend.app.domain.risk_gateway`, `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, `v2.backend.app.domain.liveness_stream_growth`, `v2.backend.app.domain.replay`, or `v2.backend.app.domain.execution`.

## Imports allowed in __init__.py

- `from .service import assemble_shadow_mode_readiness_flag`
- `from .errors import ShadowModeReadinessServiceError`

`__all__` is defined explicitly with the two names in the public-surface order. No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Forbidden tokens in source files

The three authored source files MUST NOT contain any of the following literal substrings (case-sensitive):

- `redis`
- `Redis`
- `REDIS`
- `aioredis`
- `hiredis`
- `httpx`
- `requests`
- `fastapi`
- `FastAPI`
- `uvicorn`
- `starlette`
- `urllib`
- `subprocess`
- `socket`
- `os.environ`
- `os.getenv`
- `time.time`
- `time.monotonic`
- `time.sleep`
- `datetime.now`
- `datetime.utcnow`
- `datetime`
- `logging`
- `print(`
- `url_env`
- `URL_ENV`
- `gamma.real`
- `PaperModeFlag`
- `PaperExecutionLedgerEntry`
- `RiskDecisionRecord`
- `OrchestratorDecisionRecord`
- `ReplayBacktestRun`
- `ReplayBacktestStep`
- `ReplayBacktestSummary`
- `live_enabled`
- `LIVE_ENABLED`
- `SHADOW_MODE_LIVE_ENABLED`
- `shadow_decision_id`
- `sqlite`
- `sqlalchemy`
- `parquet`
- `BEGIN_FILE`
- `END_FILE`

The bare token `SHADOW_MODE_LIVE` MUST NOT appear in the source files at all (there is no full constant `SHADOW_MODE_LIVE_*` in the 2K.A or 2K.B surface; both `SHADOW_MODE_LIVE` and `SHADOW_MODE_LIVE_ENABLED` MUST return zero matches in the source files).

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The harness BEGIN/END framing token marker line is also forbidden in any authored file body.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/14_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST cite each of the following 10 behavior contract steps with a one-line evidence pointer to function and line range in `service.py`:

1. `assemble_shadow_mode_readiness_flag` enforces `type(requested_state) is str` BEFORE the callable check (subclasses of `str` rejected; `bool` rejected because `bool` is not a `str`).
2. `assemble_shadow_mode_readiness_flag` enforces `callable(now_ms_clock)` BEFORE the allowed-set membership check.
3. `assemble_shadow_mode_readiness_flag` enforces `requested_state in _ALLOWED_REQUESTED_STATES` BEFORE the clock is invoked. The literal strings `"live"`, `"live_enabled"`, `"NOT_READY"`, `"READY"`, `"production"`, `"prod"`, and `""` are explicitly rejected by this check with the documented `shadow_mode_readiness_service_unrecognized_requested_state` code.
4. `assemble_shadow_mode_readiness_flag` invokes the clock exactly once and validates type and non-negativity before use.
5. `assemble_shadow_mode_readiness_flag` runs the 2-row mirror dispatch table in the documented order and is exhaustive over the 2K.A `_ALLOWED_STATES` frozenset (any unreachable `requested_state` triggers the defensive fallback).
6. `assemble_shadow_mode_readiness_flag` constructs `ShadowModeReadinessFlag` with `live_blocked=True` as a literal boolean and propagates the dispatched `flag_state` and the single-call `now_ms` without modification.
7. The function MUST NOT cache, mutate global state, log, spawn threads or subprocesses, or interpose any I/O between input validation and value-object return.
8. The defensive fallback in the dispatch table is unreachable under step 3 of the validation pipeline; the test suite verifies the unreachability by direct `_ALLOWED_REQUESTED_STATES` membership inspection at module-import time.
9. The service layer MUST NOT introduce any new lineage ID; the returned `ShadowModeReadinessFlag` carries only the typed `state`, `flag_emitted_ts_ms`, and `live_blocked` fields defined in 2K.A. There is NO `shadow_decision_id` lineage row introduced at the 2K.B layer.
10. The forbidden-token scan over the three authored source files returns zero matches for every token enumerated in spec section "Forbidden tokens in source files"; both `SHADOW_MODE_LIVE` and `SHADOW_MODE_LIVE_ENABLED` return zero matches in the three source files.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/14_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/15_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md` (one of the markers documented in `13_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`).

PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_SPEC_READY
