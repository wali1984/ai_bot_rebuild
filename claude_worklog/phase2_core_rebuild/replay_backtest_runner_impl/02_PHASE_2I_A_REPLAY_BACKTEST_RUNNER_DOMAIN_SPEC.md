# Phase 2I.A — Replay/Backtest Runner Domain Spec

This document is the authoring spec for Phase 2I.A of REQ_0006 ∩ REQ_0017. It is the first sub-phase of the `REPLAY_BACKTEST_RUNNER_MVP` milestone. It builds a NEW domain package `v2/backend/app/domain/replay_backtest_runner/` whose only purpose is to define the `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary` value objects plus the run-mode, step-action, and step-reason constants that downstream replay/backtest assembler service (2I.B), composition root (2I.C), and `PAPER_MODE_MVP` / `SHADOW_MODE_READINESS` (REQ_0017 milestones 6/7) milestones will consume.

The package is purely value-object oriented. It does NOT compute replay/backtest entries. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2H.C composition-root Codex pass: `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`, reconciled per `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `143_replay_backtest_runner_2ia_domain_implementation`.

## Module location decision

The new package is a sibling of `v2/backend/app/domain/paper_execution_ledger/`, `v2/backend/app/domain/risk_gateway/`, `v2/backend/app/domain/orchestrator_decision/`, and `v2/backend/app/domain/trainer_prediction_output/`. It is a NEW directory and does NOT live inside any other domain package.

The pre-existing `v2/backend/app/domain/replay/` directory (zero-byte `__init__.py` and a one-line `deterministic.py` docstring; 015A scaffold) is NOT modified, NOT used, and NOT renamed by 2I.A. The pre-existing `v2/backend/app/domain/execution/` directory (015A scaffold) is NOT modified, NOT used, and NOT renamed by 2I.A. The pre-existing `v2/backend/app/services/replay_runner.py` (one-line docstring placeholder) is NOT modified, NOT used, and NOT renamed by 2I.A.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, or 2H.C file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/replay_backtest_runner/__init__.py`
- `v2/backend/app/domain/replay_backtest_runner/errors.py`
- `v2/backend/app/domain/replay_backtest_runner/run.py`
- `v2/backend/app/domain/replay_backtest_runner/step.py`
- `v2/backend/app/domain/replay_backtest_runner/summary.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/__init__.py` (zero bytes)
- 51 sibling test files enumerated in `03_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN.md`

The existing `v2/backend/tests/unit/domain/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/domain/replay_backtest_runner/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `ReplayBacktestRunnerDomainError`
2. `ReplayBacktestRun`
3. `ReplayBacktestStep`
4. `ReplayBacktestSummary`
5. `RUN_MODE_REPLAY`
6. `RUN_MODE_BACKTEST`
7. `STEP_ACTION_RECORD_ALLOW`
8. `STEP_ACTION_RECORD_DENY`
9. `STEP_REASON_MIRROR_ALLOW_PROCEED_LONG`
10. `STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT`
11. `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`
12. `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`
13. `STEP_REASON_MIRROR_DENY_DEFAULT`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the thirteen re-exports.

## ReplayBacktestRunnerDomainError

`errors.py` defines:

```
from __future__ import annotations


class ReplayBacktestRunnerDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Run-mode constants

`run.py` defines:

```
RUN_MODE_REPLAY = "replay"
RUN_MODE_BACKTEST = "backtest"
```

The two run-mode values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-mode frozenset enforced by `ReplayBacktestRun.__post_init__`.

## ReplayBacktestRun

`run.py` defines:

```
@dataclass(frozen=True, slots=True)
class ReplayBacktestRun:
    replay_run_id: str
    run_mode: str
    symbol: str
    run_started_ts_ms: int
    run_ended_ts_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field. All fields are positional-and-keyword, but the test plan constructs entries by keyword only.

### Per-field invariants enforced in `__post_init__`

Each invariant raises `ReplayBacktestRunnerDomainError(reason, field=<field_name>)` with the field name set to the violating field:

- `replay_run_id`: type `str`; non-empty; no leading/trailing whitespace; no internal whitespace; length ≤ 128.
- `run_mode`: type `str`; member of `_ALLOWED_RUN_MODES = frozenset({"replay", "backtest"})`.
- `symbol`: type `str`; non-empty; no whitespace; length ≤ 32; equal to its own `.upper()`.
- `run_started_ts_ms`: type `int` (and not `bool`); ≥ 0.
- `run_ended_ts_ms`: type `int` (and not `bool`); ≥ `run_started_ts_ms`. If less, raise `ReplayBacktestRunnerDomainError("run_ended_ts_ms_must_be_ge_run_started_ts_ms", field="run_ended_ts_ms")`.
- `live_blocked`: type `bool`; MUST be `True`. If `False`, raise `ReplayBacktestRunnerDomainError("replay_backtest_run_requires_live_blocked_true", field="live_blocked")`.

## Step-action and step-reason constants

`step.py` defines:

```
STEP_ACTION_RECORD_ALLOW = "step_record_allow"
STEP_ACTION_RECORD_DENY = "step_record_deny"

STEP_REASON_MIRROR_ALLOW_PROCEED_LONG = "step_mirror_allow_proceed_long"
STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT = "step_mirror_allow_proceed_short"
STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD = "step_mirror_deny_orchestrator_held"
STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED = "step_mirror_deny_orchestrator_abstained"
STEP_REASON_MIRROR_DENY_DEFAULT = "step_mirror_deny_default"
```

The two action values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-action frozenset enforced by `ReplayBacktestStep.__post_init__`. The five step-reason values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-reason frozenset enforced by `ReplayBacktestStep.__post_init__`. Every `STEP_REASON_MIRROR_ALLOW_*` value MUST start with the literal prefix `"step_mirror_allow_"`. Every `STEP_REASON_MIRROR_DENY_*` value MUST start with the literal prefix `"step_mirror_deny_"`.

## ReplayBacktestStep

`step.py` defines:

```
@dataclass(frozen=True, slots=True)
class ReplayBacktestStep:
    replay_step_id: str
    replay_run_id: str
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    step_ts_ms: int
    step_action: str
    step_reason_code: str
    input_paper_action: str
    input_paper_reason_code: str
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field.

### Per-field invariants enforced in `__post_init__`

Each invariant raises `ReplayBacktestRunnerDomainError(reason, field=<field_name>)`:

- `replay_step_id`: type `str`; non-empty; no whitespace; length ≤ 128.
- `replay_run_id`: same charset and length rules as `replay_step_id`.
- `paper_trade_id`: same charset and length rules.
- `risk_decision_id`: same charset and length rules.
- `decision_id`: same charset and length rules.
- `prediction_id`: same charset and length rules.
- `feature_snapshot_id`: same charset and length rules.
- `symbol`: type `str`; non-empty; no whitespace; length ≤ 32; equal to its own `.upper()`.
- `step_ts_ms`: type `int` (and not `bool`); ≥ 0.
- `step_action`: type `str`; member of `_ALLOWED_STEP_ACTIONS = frozenset({"step_record_allow", "step_record_deny"})`.
- `step_reason_code`: type `str`; member of `_ALLOWED_STEP_REASONS = frozenset({"step_mirror_allow_proceed_long", "step_mirror_allow_proceed_short", "step_mirror_deny_orchestrator_held", "step_mirror_deny_orchestrator_abstained", "step_mirror_deny_default"})`.
- `input_paper_action`: type `str`; member of `_ALLOWED_INPUT_PAPER_ACTIONS = frozenset({"record_allow", "record_deny"})`.
- `input_paper_reason_code`: type `str`; member of `_ALLOWED_INPUT_PAPER_REASONS = frozenset({"mirror_allow_proceed_long", "mirror_allow_proceed_short", "mirror_deny_orchestrator_held", "mirror_deny_orchestrator_abstained", "mirror_deny_default"})`.
- `live_blocked`: type `bool`; MUST be `True`. If `False`, raise `ReplayBacktestRunnerDomainError("replay_backtest_step_requires_live_blocked_true", field="live_blocked")`.

### Cross-field invariants enforced in `__post_init__`

After per-field checks pass:

1. If `step_action == STEP_ACTION_RECORD_ALLOW`:
   - `step_reason_code` MUST start with the literal `"step_mirror_allow_"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_record_allow_requires_step_mirror_allow_prefix_reason", field="step_reason_code")`.
   - `input_paper_action` MUST be `"record_allow"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_record_allow_requires_record_allow_input_paper_action", field="input_paper_action")`.
2. If `step_action == STEP_ACTION_RECORD_DENY`:
   - `step_reason_code` MUST start with the literal `"step_mirror_deny_"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_record_deny_requires_step_mirror_deny_prefix_reason", field="step_reason_code")`.
   - `input_paper_action` MUST be `"record_deny"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_record_deny_requires_record_deny_input_paper_action", field="input_paper_action")`.
3. If `step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_LONG`:
   - `input_paper_reason_code` MUST be `"mirror_allow_proceed_long"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_mirror_allow_proceed_long_requires_mirror_allow_proceed_long_input_reason", field="input_paper_reason_code")`.
4. If `step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT`:
   - `input_paper_reason_code` MUST be `"mirror_allow_proceed_short"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_mirror_allow_proceed_short_requires_mirror_allow_proceed_short_input_reason", field="input_paper_reason_code")`.
5. If `step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`:
   - `input_paper_reason_code` MUST be `"mirror_deny_orchestrator_held"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_mirror_deny_orchestrator_held_requires_mirror_deny_orchestrator_held_input_reason", field="input_paper_reason_code")`.
6. If `step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`:
   - `input_paper_reason_code` MUST be `"mirror_deny_orchestrator_abstained"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_mirror_deny_orchestrator_abstained_requires_mirror_deny_orchestrator_abstained_input_reason", field="input_paper_reason_code")`.
7. If `step_reason_code == STEP_REASON_MIRROR_DENY_DEFAULT`:
   - `input_paper_reason_code` MUST be `"mirror_deny_default"`. Otherwise raise `ReplayBacktestRunnerDomainError("step_mirror_deny_default_requires_mirror_deny_default_input_reason", field="input_paper_reason_code")`.

The cross-field rules collectively enforce a one-to-one mapping between `step_reason_code` and `input_paper_reason_code`, and a one-to-one mapping between `step_action` and `input_paper_action`. There is no ambiguity and no defaulting.

## ReplayBacktestSummary

`summary.py` defines:

```
@dataclass(frozen=True, slots=True)
class ReplayBacktestSummary:
    replay_summary_id: str
    replay_run_id: str
    summary_emitted_ts_ms: int
    total_steps_count: int
    record_allow_steps_count: int
    record_deny_steps_count: int
    mirror_allow_proceed_long_steps_count: int
    mirror_allow_proceed_short_steps_count: int
    mirror_deny_orchestrator_held_steps_count: int
    mirror_deny_orchestrator_abstained_steps_count: int
    mirror_deny_default_steps_count: int
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field.

### Per-field invariants enforced in `__post_init__`

Each invariant raises `ReplayBacktestRunnerDomainError(reason, field=<field_name>)`:

- `replay_summary_id`: type `str`; non-empty; no whitespace; length ≤ 128.
- `replay_run_id`: same charset and length rules.
- `summary_emitted_ts_ms`: type `int` (and not `bool`); ≥ 0.
- Every `*_steps_count` field: type `int` (and not `bool`); ≥ 0.
- `live_blocked`: type `bool`; MUST be `True`. If `False`, raise `ReplayBacktestRunnerDomainError("replay_backtest_summary_requires_live_blocked_true", field="live_blocked")`.

### Cross-field partition-sum invariants enforced in `__post_init__`

After per-field checks pass, three partition-sum equalities MUST hold; any failure raises `ReplayBacktestRunnerDomainError(reason, field=<field_name>)`:

1. Action partition: `record_allow_steps_count + record_deny_steps_count == total_steps_count`. Otherwise raise `ReplayBacktestRunnerDomainError("action_partition_sum_must_equal_total_steps_count", field="total_steps_count")`.
2. Allow-subreason partition: `mirror_allow_proceed_long_steps_count + mirror_allow_proceed_short_steps_count == record_allow_steps_count`. Otherwise raise `ReplayBacktestRunnerDomainError("allow_subreason_partition_sum_must_equal_record_allow_steps_count", field="record_allow_steps_count")`.
3. Deny-subreason partition: `mirror_deny_orchestrator_held_steps_count + mirror_deny_orchestrator_abstained_steps_count + mirror_deny_default_steps_count == record_deny_steps_count`. Otherwise raise `ReplayBacktestRunnerDomainError("deny_subreason_partition_sum_must_equal_record_deny_steps_count", field="record_deny_steps_count")`.

## Forbidden imports in source files

`__init__.py`, `errors.py`, `run.py`, `step.py`, and `summary.py` MUST NOT import any of:

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
- `v2.backend.app.domain.paper_execution_ledger.*` (the input paper-ledger action and reason are validated as plain strings via membership in frozensets; the paper-ledger domain is consumed at the 2I.B service layer)
- `v2.backend.app.domain.risk_gateway.*`
- `v2.backend.app.domain.orchestrator_decision.*`
- `v2.backend.app.domain.trainer_prediction_output.*`
- `v2.backend.app.domain.replay.*`
- `v2.backend.app.domain.execution.*`

The only allowed imports across all five source files are:

- `from __future__ import annotations`
- `from dataclasses import dataclass`
- `from .errors import ReplayBacktestRunnerDomainError` (in `run.py`, `step.py`, `summary.py`)
- `from .errors import ReplayBacktestRunnerDomainError` and `from .run import (...)`, `from .step import (...)`, `from .summary import (...)` (in `__init__.py`)

## Forbidden tokens in source files

None of the five authored source files may contain any of the following literal substrings (case-sensitive):

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
- `sqlite`
- `sqlalchemy`
- `parquet`

The authored test files MAY reference the forbidden tokens via runtime string concatenation when verifying the forbidden-token scan. The forbidden-token-scan test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC_READY
