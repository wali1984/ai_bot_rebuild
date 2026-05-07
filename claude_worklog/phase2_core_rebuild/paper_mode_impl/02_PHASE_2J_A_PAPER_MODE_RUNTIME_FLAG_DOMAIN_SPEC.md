# Phase 2J.A — Paper-Mode Runtime-Flag Domain Spec

This document is the authoring spec for Phase 2J.A of REQ_0006 ∩ REQ_0017. It is the first sub-phase of the `PAPER_MODE_MVP` milestone (REQ_0017 milestone 6). It builds a NEW domain package `v2/backend/app/domain/paper_mode/` whose only purpose is to define the `PaperModeFlag` value object plus the two run-mode constants `PAPER_MODE_PAPER` and `PAPER_MODE_LIVE_BLOCKED` that downstream paper-mode assembler service (2J.B), composition root (2J.C), and `SHADOW_MODE_READINESS` (REQ_0017 milestone 7) milestones will consume.

The package is purely value-object oriented. It does NOT compute paper-mode entries. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2I.C composition-root Codex pass: `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`. Reconciliation precedent applies per the 2H.C / 2I.C addendum pattern; an addendum at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` may be the artifact that flips the marker body.

If this marker is absent or different from `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`, the supervisor MUST NOT dispatch `150_paper_mode_2ja_runtime_flag_domain_implementation`.

## Module location decision

The new package is a sibling of `v2/backend/app/domain/paper_execution_ledger/`, `v2/backend/app/domain/replay_backtest_runner/`, `v2/backend/app/domain/risk_gateway/`, `v2/backend/app/domain/orchestrator_decision/`, and `v2/backend/app/domain/trainer_prediction_output/`. It is a NEW directory and does NOT live inside any other domain package.

The pre-existing `v2/backend/app/domain/execution/` directory (015A scaffold: zero-byte `__init__.py`, single-line docstring `intent.py`, single-line docstring `paper.py`) is NOT modified, NOT used, and NOT renamed by 2J.A. The pre-existing `v2/backend/app/domain/replay/` directory (015A scaffold) is NOT modified, NOT used, and NOT renamed by 2J.A. The pre-existing `v2/backend/app/services/paper_loop.py` (one-line docstring placeholder) is NOT modified, NOT used, and NOT renamed by 2J.A.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, or 2I.C file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/paper_mode/__init__.py`
- `v2/backend/app/domain/paper_mode/errors.py`
- `v2/backend/app/domain/paper_mode/flag.py`
- `v2/backend/tests/unit/domain/paper_mode/__init__.py` (zero bytes)
- 26 sibling test files enumerated in `03_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_TEST_PLAN.md`

The existing `v2/backend/tests/unit/domain/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/domain/paper_mode/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `PaperModeDomainError`
2. `PaperModeFlag`
3. `PAPER_MODE_PAPER`
4. `PAPER_MODE_LIVE_BLOCKED`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the four re-exports. There is NO `PAPER_MODE_LIVE` constant, NO `PAPER_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, and NO live-execution affordance at any layer of the 2J.A package.

## PaperModeDomainError

`errors.py` defines:

```
from __future__ import annotations


class PaperModeDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Run-mode constants

`flag.py` defines:

```
PAPER_MODE_PAPER = "paper"
PAPER_MODE_LIVE_BLOCKED = "live_blocked"
```

The two run-mode values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-mode frozenset enforced by `PaperModeFlag.__post_init__`.

There is NO third constant. The 2J.A surface declares paper-mode posture by exhaustive case over exactly two values:

- `PAPER_MODE_PAPER` is the default posture for the V2 runtime: live execution is hard-blocked at the V2 live-readiness gate AND the runtime is operating in paper mode.
- `PAPER_MODE_LIVE_BLOCKED` is the explicit live-blocked posture: live execution is hard-blocked at the V2 live-readiness gate AND the runtime is asserting that it is NOT in paper mode but is also NOT in live mode (held for the live-readiness gate).

In both cases `live_blocked == True`. There is NO branch in 2J.A, 2J.B, or 2J.C where `live_blocked` could be `False`.

## PaperModeFlag

`flag.py` defines:

```
@dataclass(frozen=True, slots=True)
class PaperModeFlag:
    mode: str
    flag_emitted_ts_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field. All fields are positional-and-keyword, but the test plan constructs entries by keyword only.

### Per-field invariants enforced in `__post_init__`

Each invariant raises `PaperModeDomainError(reason, field=<field_name>)` with the field name set to the violating field:

- `mode`: type `str`; member of `_ALLOWED_MODES = frozenset({"paper", "live_blocked"})`. Otherwise raise `PaperModeDomainError("paper_mode_flag_unknown_mode", field="mode")`.
- `flag_emitted_ts_ms`: type `int` (and not `bool`); ≥ 0. Otherwise raise `PaperModeDomainError("paper_mode_flag_emitted_ts_ms_must_be_non_negative_int", field="flag_emitted_ts_ms")`. The `bool` exclusion uses `isinstance(value, bool)` rejection before the `isinstance(value, int)` check, identical to the prior-milestone pattern.
- `live_blocked`: type `bool`; MUST be `True`. If `False`, raise `PaperModeDomainError("paper_mode_flag_requires_live_blocked_true", field="live_blocked")`. There is NO code path in 2J.A where this invariant can be bypassed.

### Cross-field invariants enforced in `__post_init__`

After per-field checks pass, no additional cross-field invariants are enforced at the 2J.A layer. The two-element `mode` set is exhaustive, and `live_blocked == True` is required for both values. The 2J.B service layer is responsible for translating a requested-mode string into the typed flag; the 2J.C composition root is responsible for binding a wall-clock callable at build time and adapting the 2J.B service unchanged.

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
- `from .errors import PaperModeDomainError` (in `flag.py`)
- `from .errors import PaperModeDomainError` and `from .flag import (...)` (in `__init__.py`)

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
- `PaperExecutionLedgerEntry`
- `RiskDecisionRecord`
- `OrchestratorDecisionRecord`
- `ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`
- `live_enabled`
- `LIVE_ENABLED`
- `PAPER_MODE_LIVE` (must NOT appear as a bare literal; the only allowed live-prefix literal in the source files is `PAPER_MODE_LIVE_BLOCKED`)
- `sqlite`
- `sqlalchemy`
- `parquet`

The authored test files MAY reference the forbidden tokens via runtime string concatenation when verifying the forbidden-token scan. The forbidden-token-scan test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

## Default constructor value commitment

The 2J.A surface establishes the V2-wide default paper-mode posture as `PAPER_MODE_PAPER`. Any 2J.B service path that receives a non-paper / non-live_blocked requested-mode string MUST raise a service error before producing a flag. There is NO requested-mode branch labeled `live`, `live_enabled`, `live_mode`, `production`, `prod`, or any other live-execution synonym at any layer of the 2J.A, 2J.B, or 2J.C package set.

PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_SPEC_READY
