# Phase 2H.A — Paper Execution Ledger Domain Spec

This document is the authoring spec for Phase 2H.A of REQ_0006 ∩ REQ_0017. It is the first sub-phase of the `PAPER_EXECUTION_LEDGER_MVP` milestone. It builds a NEW domain package `v2/backend/app/domain/paper_execution_ledger/` whose only purpose is to define the `PaperExecutionLedgerEntry` value object plus the ledger-action and ledger-reason constants that downstream paper execution ledger assembler service (2H.B), composition root (2H.C), and replay/backtest runner (REQ_0017 milestone 5) milestones will consume.

The package is purely value-object oriented. It does NOT compute paper-ledger entries. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2G.C composition root Codex pass: `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `133_paper_execution_ledger_2ha_domain_implementation`.

## Module location decision

The new package is a sibling of `v2/backend/app/domain/risk_gateway/`, `v2/backend/app/domain/orchestrator_decision/`, and `v2/backend/app/domain/trainer_prediction_output/`. It is a NEW directory and does NOT live inside any other domain package. The pre-existing empty `v2/backend/app/domain/execution/` directory is NOT modified, NOT used, and NOT renamed by 2H.A. The pre-existing `v2/backend/app/domain/decisions/` directory is NOT modified.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, or 2G.C file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/paper_execution_ledger/__init__.py`
- `v2/backend/app/domain/paper_execution_ledger/errors.py`
- `v2/backend/app/domain/paper_execution_ledger/record.py`
- `v2/backend/tests/unit/domain/paper_execution_ledger/__init__.py`
- 30 sibling test files enumerated in `03_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/domain/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/domain/paper_execution_ledger/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `PaperExecutionLedgerDomainError`
2. `PaperExecutionLedgerEntry`
3. `PAPER_LEDGER_ACTION_RECORD_ALLOW`
4. `PAPER_LEDGER_ACTION_RECORD_DENY`
5. `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG`
6. `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT`
7. `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`
8. `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`
9. `PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the nine re-exports.

## PaperExecutionLedgerDomainError

`errors.py` defines:

```
from __future__ import annotations


class PaperExecutionLedgerDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Ledger action constants

`record.py` defines:

```
PAPER_LEDGER_ACTION_RECORD_ALLOW = "record_allow"
PAPER_LEDGER_ACTION_RECORD_DENY = "record_deny"
```

The two action values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-action frozenset enforced by `PaperExecutionLedgerEntry.__post_init__`.

## Ledger reason constants

`record.py` defines:

```
PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG = "mirror_allow_proceed_long"
PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT = "mirror_allow_proceed_short"
PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED = "mirror_deny_orchestrator_abstained"
PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD = "mirror_deny_orchestrator_held"
PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT = "mirror_deny_default"
```

The five reason values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-reason frozenset enforced by `PaperExecutionLedgerEntry.__post_init__`. Every `PAPER_LEDGER_REASON_MIRROR_ALLOW_*` value MUST start with the literal prefix `"mirror_allow_"`. Every `PAPER_LEDGER_REASON_MIRROR_DENY_*` value MUST start with the literal prefix `"mirror_deny_"`.

## PaperExecutionLedgerEntry

`record.py` defines:

```
@dataclass(frozen=True, slots=True)
class PaperExecutionLedgerEntry:
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    ledger_entry_ts_ms: int
    ledger_action: str
    ledger_reason_code: str
    input_risk_action: str
    input_risk_reason_code: str
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field. All fields are positional-and-keyword, but the test plan constructs entries by keyword only.

### Per-field invariants enforced in `__post_init__`

Each invariant raises `PaperExecutionLedgerDomainError(reason, field=<field_name>)` with the field name set to the violating field:

- `paper_trade_id`: type `str`; non-empty; no leading/trailing whitespace; no internal whitespace; length ≤ 128.
- `risk_decision_id`: same charset and length rules as `paper_trade_id`.
- `decision_id`: same charset and length rules as `paper_trade_id`.
- `prediction_id`: same charset and length rules as `paper_trade_id`.
- `feature_snapshot_id`: same charset and length rules as `paper_trade_id`.
- `symbol`: type `str`; non-empty; no whitespace; length ≤ 32; equal to its own `.upper()`.
- `ledger_entry_ts_ms`: type `int` (and not `bool`); ≥ 0.
- `ledger_action`: type `str`; member of `_ALLOWED_LEDGER_ACTIONS = frozenset({"record_allow", "record_deny"})`.
- `ledger_reason_code`: type `str`; member of `_ALLOWED_LEDGER_REASONS = frozenset({"mirror_allow_proceed_long", "mirror_allow_proceed_short", "mirror_deny_orchestrator_abstained", "mirror_deny_orchestrator_held", "mirror_deny_default"})`.
- `input_risk_action`: type `str`; member of `_ALLOWED_INPUT_RISK_ACTIONS = frozenset({"allow", "deny"})`.
- `input_risk_reason_code`: type `str`; member of `_ALLOWED_INPUT_RISK_REASONS = frozenset({"allow_proceed_long", "allow_proceed_short", "deny_orchestrator_abstained", "deny_orchestrator_held", "deny_default"})`.
- `live_blocked`: type `bool`; MUST be `True`. If `False`, raise `PaperExecutionLedgerDomainError("paper_ledger_requires_live_blocked_true", field="live_blocked")`.

### Cross-field invariants enforced in `__post_init__`

After per-field checks pass:

1. If `ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW`:
   - `ledger_reason_code` MUST start with the literal `"mirror_allow_"`. Otherwise raise `PaperExecutionLedgerDomainError("record_allow_requires_mirror_allow_prefix_reason", field="ledger_reason_code")`.
   - `input_risk_action` MUST be `"allow"`. Otherwise raise `PaperExecutionLedgerDomainError("record_allow_requires_allow_input_risk_action", field="input_risk_action")`.
2. If `ledger_action == PAPER_LEDGER_ACTION_RECORD_DENY`:
   - `ledger_reason_code` MUST start with the literal `"mirror_deny_"`. Otherwise raise `PaperExecutionLedgerDomainError("record_deny_requires_mirror_deny_prefix_reason", field="ledger_reason_code")`.
   - `input_risk_action` MUST be `"deny"`. Otherwise raise `PaperExecutionLedgerDomainError("record_deny_requires_deny_input_risk_action", field="input_risk_action")`.
3. If `ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG`:
   - `input_risk_reason_code` MUST be `"allow_proceed_long"`. Otherwise raise `PaperExecutionLedgerDomainError("mirror_allow_proceed_long_requires_allow_proceed_long_input_reason", field="input_risk_reason_code")`.
4. If `ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT`:
   - `input_risk_reason_code` MUST be `"allow_proceed_short"`. Otherwise raise `PaperExecutionLedgerDomainError("mirror_allow_proceed_short_requires_allow_proceed_short_input_reason", field="input_risk_reason_code")`.
5. If `ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`:
   - `input_risk_reason_code` MUST be `"deny_orchestrator_abstained"`. Otherwise raise `PaperExecutionLedgerDomainError("mirror_deny_orchestrator_abstained_requires_deny_orchestrator_abstained_input_reason", field="input_risk_reason_code")`.
6. If `ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`:
   - `input_risk_reason_code` MUST be `"deny_orchestrator_held"`. Otherwise raise `PaperExecutionLedgerDomainError("mirror_deny_orchestrator_held_requires_deny_orchestrator_held_input_reason", field="input_risk_reason_code")`.
7. If `ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT`:
   - `input_risk_reason_code` MUST be `"deny_default"`. Otherwise raise `PaperExecutionLedgerDomainError("mirror_deny_default_requires_deny_default_input_reason", field="input_risk_reason_code")`.

The cross-field rules collectively enforce a one-to-one mapping between `ledger_reason_code` and `input_risk_reason_code`, and a one-to-one mapping between `ledger_action` and `input_risk_action`. There is no ambiguity and no defaulting.

## Forbidden imports in source files

`__init__.py`, `errors.py`, and `record.py` MUST NOT import any of:
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
- `v2.backend.app.domain.risk_gateway.*` (the input risk action and reason are validated as plain strings via membership in frozensets; the risk_gateway domain is consumed at the 2H.B service layer)
- `v2.backend.app.domain.orchestrator_decision.*`
- `v2.backend.app.domain.trainer_prediction_output.*`

The only allowed imports across all three source files are:
- `from __future__ import annotations`
- `from dataclasses import dataclass`
- `from .errors import PaperExecutionLedgerDomainError` (in `record.py`)
- `from .errors import PaperExecutionLedgerDomainError` and `from .record import (...)` (in `__init__.py`)

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
- `RiskDecisionRecord`
- `OrchestratorDecisionRecord`

The authored test files MAY reference the forbidden tokens via runtime string concatenation when verifying the forbidden-token scan. The forbidden-token-scan test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md
