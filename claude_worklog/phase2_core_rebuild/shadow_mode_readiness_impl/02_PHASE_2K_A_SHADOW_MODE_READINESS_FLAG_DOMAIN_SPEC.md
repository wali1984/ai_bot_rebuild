# Phase 2K.A — Shadow-Mode-Readiness Flag Domain Spec

This document is the authoring spec for Phase 2K.A of REQ_0006 ∩ REQ_0017. It is the first sub-phase of the `SHADOW_MODE_READINESS` milestone (REQ_0017 milestone 7). It builds a NEW domain package `v2/backend/app/domain/shadow_mode_readiness/` whose only purpose is to define the `ShadowModeReadinessFlag` value object plus the two readiness-state constants `SHADOW_MODE_NOT_READY` and `SHADOW_MODE_READY` that the downstream shadow-mode-readiness assembler service (2K.B), composition root (2K.C), and the future `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation turn will consume.

The package is purely value-object oriented. It does NOT compute shadow-mode entries. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. It does NOT produce a `shadow_decision_id` lineage row. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2J.C composition-root Codex pass: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS at HEAD 5565c25).

If this marker is absent or different from `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`, the supervisor MUST NOT dispatch `156_shadow_mode_readiness_2ka_flag_domain_implementation`.

## Module location decision

The new package is a sibling of `v2/backend/app/domain/paper_mode/`, `v2/backend/app/domain/paper_execution_ledger/`, `v2/backend/app/domain/replay_backtest_runner/`, `v2/backend/app/domain/risk_gateway/`, `v2/backend/app/domain/orchestrator_decision/`, and `v2/backend/app/domain/trainer_prediction_output/`. It is a NEW directory and does NOT live inside any other domain package.

The pre-existing `v2/backend/app/domain/execution/` directory (015A scaffold: zero-byte `__init__.py`, single-line docstring `intent.py`, single-line docstring `paper.py`) is NOT modified, NOT used, and NOT renamed by 2K.A. The pre-existing `v2/backend/app/domain/replay/` directory (015A scaffold) is NOT modified, NOT used, and NOT renamed by 2K.A. The pre-existing `v2/backend/app/services/paper_loop.py` (one-line docstring placeholder) is NOT modified, NOT used, and NOT renamed by 2K.A.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, 2I.C, 2J.A, 2J.B, or 2J.C file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/shadow_mode_readiness/__init__.py`
- `v2/backend/app/domain/shadow_mode_readiness/errors.py`
- `v2/backend/app/domain/shadow_mode_readiness/flag.py`
- `v2/backend/tests/unit/domain/shadow_mode_readiness/__init__.py` (zero bytes)
- 26 sibling test files enumerated in `03_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_TEST_PLAN.md`

The existing `v2/backend/tests/unit/domain/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/domain/shadow_mode_readiness/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `ShadowModeReadinessDomainError`
2. `ShadowModeReadinessFlag`
3. `SHADOW_MODE_NOT_READY`
4. `SHADOW_MODE_READY`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the four re-exports. There is NO `SHADOW_MODE_LIVE` constant, NO `SHADOW_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, and NO live-execution affordance at any layer of the 2K.A package.

## ShadowModeReadinessDomainError

`errors.py` defines:

```
from __future__ import annotations


class ShadowModeReadinessDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Readiness-state constants

`flag.py` defines:

```
SHADOW_MODE_NOT_READY = "not_ready"
SHADOW_MODE_READY = "ready"
```

The two readiness-state values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-state frozenset enforced by `ShadowModeReadinessFlag.__post_init__`.

There is NO third constant. The 2K.A surface declares shadow-mode-readiness posture by exhaustive case over exactly two values:

- `SHADOW_MODE_NOT_READY` is the default posture for the V2 runtime: live execution is hard-blocked at the V2 live-readiness gate AND the runtime has NOT asserted that all upstream MVP surfaces are ready for shadow-mode comparison.
- `SHADOW_MODE_READY` is the explicit readiness-asserted posture: live execution is hard-blocked at the V2 live-readiness gate AND the runtime is asserting that all upstream MVP surfaces are ready for shadow-mode comparison. `SHADOW_MODE_READY` is the typed name for the readiness-asserted posture so downstream consumers can pattern-match on the value without ever importing a shadow-execution surface; it is not a live-enable affordance and it is not a shadow-decision-record affordance.

In both cases `live_blocked == True`. There is NO branch in 2K.A, 2K.B, or 2K.C where `live_blocked` could be `False`.

## ShadowModeReadinessFlag

`flag.py` defines:

```
@dataclass(frozen=True, slots=True)
class ShadowModeReadinessFlag:
    state: str
    flag_emitted_ts_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field. All fields are positional-and-keyword, but the test plan constructs entries by keyword only.

### Per-field invariants enforced in `__post_init__`

Each invariant raises `ShadowModeReadinessDomainError(reason, field=<field_name>)` with the field name set to the violating field:

- `state`: type `str`; member of `_ALLOWED_STATES = frozenset({"not_ready", "ready"})`. Otherwise raise `ShadowModeReadinessDomainError("shadow_mode_readiness_flag_unknown_state", field="state")`.
- `flag_emitted_ts_ms`: type `int` (and not `bool`); ≥ 0. Otherwise raise `ShadowModeReadinessDomainError("shadow_mode_readiness_flag_emitted_ts_ms_must_be_non_negative_int", field="flag_emitted_ts_ms")`. The `bool` exclusion uses `isinstance(value, bool)` rejection before the `isinstance(value, int)` check, identical to the prior-milestone pattern.
- `live_blocked`: type `bool`; MUST be `True`. If `False`, raise `ShadowModeReadinessDomainError("shadow_mode_readiness_flag_requires_live_blocked_true", field="live_blocked")`. There is NO code path in 2K.A where this invariant can be bypassed.

### Cross-field invariants enforced in `__post_init__`

After per-field checks pass, no additional cross-field invariants are enforced at the 2K.A layer. The two-element `state` set is exhaustive, and `live_blocked == True` is required for both values. The 2K.B service layer is responsible for translating a requested-state string into the typed flag; the 2K.C composition root is responsible for binding a wall-clock callable at build time and adapting the 2K.B service unchanged.

## Forbidden imports in source files

`__init__.py`, `errors.py`, and `flag.py` MUST NOT import any of:

- `redis`, `redis.asyncio`, `aioredis`, `hiredis`
- `fastapi`, `uvicorn`, `starlette`
- `httpx`, `requests`, `urllib`, `urllib3`
- `asyncio`, `threading`, `multiprocessing`
- `os` (no `os.environ`, no `os.getenv`)
- `socket`, `subprocess`
- `time`, `datetime` (no wall-clock helper invocation)
- `logging`
- `v2.backend.app.adapters.*`
- `v2.backend.app.services.*`
- `v2.backend.app.composition.*`
- `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`
- `v2.backend.app.domain.paper_mode.*`
- `v2.backend.app.domain.paper_execution_ledger.*`
- `v2.backend.app.domain.replay_backtest_runner.*`
- `v2.backend.app.domain.risk_gateway.*`
- `v2.backend.app.domain.orchestrator_decision.*`
- `v2.backend.app.domain.trainer_prediction_output.*`
- `v2.backend.app.domain.replay.*`
- `v2.backend.app.domain.execution.*`

The only allowed imports across all three source files are:

- `from __future__ import annotations`
- `from dataclasses import dataclass`
- `from .errors import ShadowModeReadinessDomainError` (in `flag.py`)
- `from .errors import ShadowModeReadinessDomainError` and `from .flag import (...)` (in `__init__.py`)

## Forbidden tokens in source files

None of the three authored source files may contain any of the following literal substrings (case-sensitive):

- `redis`
- `aioredis`
- `hiredis`
- `fastapi`
- `uvicorn`
- `starlette`
- `httpx`
- `requests`
- `getenv`
- `environ`
- `subprocess`
- `socket`
- `logging`
- `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`
- `PaperModeFlag`
- `PaperExecutionLedgerEntry`
- `RiskDecisionRecord`
- `OrchestratorDecisionRecord`
- `ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`
- `live_enabled`
- `LIVE_ENABLED`
- `SHADOW_MODE_LIVE` (must NOT appear as a literal anywhere in the source files; the 2K.A surface contains no live-prefix readiness-state constant)
- `shadow_decision_id`
- `sqlite`
- `sqlalchemy`
- `parquet`

The authored test files MAY reference the forbidden tokens via runtime string concatenation when verifying the forbidden-token scan. The forbidden-token-scan test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

## Default constructor value commitment

The 2K.A surface establishes the V2-wide default shadow-mode-readiness posture as `SHADOW_MODE_NOT_READY`. Any 2K.B service path that receives a non-not_ready / non-ready requested-state string MUST raise a service error before producing a flag. There is NO requested-state branch labeled `live`, `live_enabled`, `live_mode`, `production`, `prod`, or any other live-execution synonym at any layer of the 2K.A, 2K.B, or 2K.C package set. There is NO `shadow_decision_id` lineage row introduced at any layer of the 2K.A, 2K.B, or 2K.C package set; that lineage row is a downstream consumer concern materialized after `V2_BACKTEST_AND_PAPER_MVP_READY`.

PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_SPEC_READY
