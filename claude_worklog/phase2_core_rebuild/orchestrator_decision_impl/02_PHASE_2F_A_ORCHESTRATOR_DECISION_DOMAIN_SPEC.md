# Phase 2F.A — Orchestrator Decision Domain Spec

This document is the authoring spec for Phase 2F.A of REQ_0006 ∩ REQ_0017. It is the first sub-phase of the `ORCHESTRATOR_DECISION_MVP` milestone. It builds a NEW domain package `v2/backend/app/domain/orchestrator_decision/` whose only purpose is to define the `OrchestratorDecisionRecord` value object plus the decision-action and decision-reason constants that downstream orchestrator decision service (2F.B), composition root (2F.C), and risk-gateway (REQ_0017 milestone 3) milestones will consume.

The package is purely value-object oriented. It does NOT compute decisions. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2E3.C composition root Codex pass: `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/205_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `117_orchestrator_decision_2fa_domain_implementation`.

## Module location decision

The new package is a sibling of `v2/backend/app/domain/trainer_prediction_output/`. It is a NEW directory and does NOT live inside any other domain package. The existing empty `v2/backend/app/domain/decisions/` directory is NOT modified, NOT used, and NOT renamed by 2F.A.

No 2E1, 2E2, 2E3, or earlier-phase file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/orchestrator_decision/__init__.py`
- `v2/backend/app/domain/orchestrator_decision/errors.py`
- `v2/backend/app/domain/orchestrator_decision/record.py`
- `v2/backend/tests/unit/domain/orchestrator_decision/__init__.py`
- 34 sibling test files enumerated in `03_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/domain/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/domain/orchestrator_decision/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `OrchestratorDecisionDomainError`
2. `OrchestratorDecisionRecord`
3. `DECISION_ACTION_OPEN_LONG`
4. `DECISION_ACTION_OPEN_SHORT`
5. `DECISION_ACTION_HOLD`
6. `DECISION_ACTION_ABSTAIN`
7. `DECISION_REASON_PROCEED_LONG`
8. `DECISION_REASON_PROCEED_SHORT`
9. `DECISION_REASON_HOLD_FLAT_DIRECTION`
10. `DECISION_REASON_ABSTAIN_LOW_CONFIDENCE`
11. `DECISION_REASON_ABSTAIN_FRESHNESS_STALE`
12. `DECISION_REASON_ABSTAIN_FRESHNESS_MISSING`
13. `DECISION_REASON_ABSTAIN_WORKER_DEGRADED`
14. `DECISION_REASON_ABSTAIN_WORKER_CRITICAL`
15. `DECISION_REASON_ABSTAIN_WORKER_UNKNOWN`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the fifteen re-exports.

## OrchestratorDecisionDomainError

`errors.py` defines:

```
from __future__ import annotations


class OrchestratorDecisionDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Decision action constants

`record.py` defines:

```
DECISION_ACTION_OPEN_LONG = "open_long"
DECISION_ACTION_OPEN_SHORT = "open_short"
DECISION_ACTION_HOLD = "hold"
DECISION_ACTION_ABSTAIN = "abstain"
```

The four action values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-action frozenset enforced by `OrchestratorDecisionRecord.__post_init__`.

## Decision reason constants

`record.py` defines:

```
DECISION_REASON_PROCEED_LONG = "proceed_long"
DECISION_REASON_PROCEED_SHORT = "proceed_short"
DECISION_REASON_HOLD_FLAT_DIRECTION = "hold_flat_direction"
DECISION_REASON_ABSTAIN_LOW_CONFIDENCE = "abstain_low_confidence"
DECISION_REASON_ABSTAIN_FRESHNESS_STALE = "abstain_freshness_stale"
DECISION_REASON_ABSTAIN_FRESHNESS_MISSING = "abstain_freshness_missing"
DECISION_REASON_ABSTAIN_WORKER_DEGRADED = "abstain_worker_degraded"
DECISION_REASON_ABSTAIN_WORKER_CRITICAL = "abstain_worker_critical"
DECISION_REASON_ABSTAIN_WORKER_UNKNOWN = "abstain_worker_unknown"
```

The eleven reason values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-reason frozenset enforced by `OrchestratorDecisionRecord.__post_init__`. Every `DECISION_REASON_ABSTAIN_*` value MUST start with the literal prefix `"abstain_"`. Every `DECISION_REASON_PROCEED_*` value MUST start with the literal prefix `"proceed_"`.

## OrchestratorDecisionRecord

`record.py` defines:

```
@dataclass(frozen=True, slots=True)
class OrchestratorDecisionRecord:
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    decision_ts_ms: int
    decision_action: str
    decision_reason_code: str
    input_prediction_direction: str
    input_prediction_confidence_calibrated: float
    input_prediction_freshness_flag: str
    input_worker_health_status: str
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field. All fields are positional-and-keyword, but the test plan constructs records by keyword only.

### Per-field invariants enforced in `__post_init__`

Field-level checks (each invariant raises `OrchestratorDecisionDomainError(reason, field=<field_name>)` with the field name set to the violating field):

- `decision_id`: type `str`; non-empty; no leading/trailing whitespace; no internal whitespace; length ≤ 128.
- `prediction_id`: same charset and length rules as `decision_id`.
- `feature_snapshot_id`: same charset and length rules as `decision_id`.
- `symbol`: type `str`; non-empty; no whitespace; length ≤ 32; equal to its own `.upper()`.
- `decision_ts_ms`: type `int` (and not `bool`); ≥ 0.
- `decision_action`: type `str`; member of `_ALLOWED_DECISION_ACTIONS`.
- `decision_reason_code`: type `str`; member of `_ALLOWED_DECISION_REASONS`.
- `input_prediction_direction`: type `str`; member of `_ALLOWED_INPUT_PREDICTION_DIRECTIONS = frozenset({"long", "short", "flat"})`.
- `input_prediction_confidence_calibrated`: type `float` (and not `bool`); finite (`math.isfinite`); within `[0.0, 1.0]` inclusive.
- `input_prediction_freshness_flag`: type `str`; member of `_ALLOWED_INPUT_PREDICTION_FRESHNESS = frozenset({"fresh", "stale", "missing"})`.
- `input_worker_health_status`: type `str`; member of `_ALLOWED_INPUT_WORKER_HEALTH_STATUSES = frozenset({"HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"})`.
- `live_blocked`: type `bool`; MUST be `True`.

### Cross-field invariants enforced in `__post_init__`

After per-field checks pass:

1. If `decision_action == DECISION_ACTION_OPEN_LONG`:
   - `decision_reason_code` MUST be `DECISION_REASON_PROCEED_LONG`. Otherwise raise `OrchestratorDecisionDomainError("open_long_requires_proceed_long_reason", field="decision_reason_code")`.
   - `input_prediction_direction` MUST be `"long"`. Otherwise raise `OrchestratorDecisionDomainError("open_long_requires_long_input_direction", field="input_prediction_direction")`.
2. If `decision_action == DECISION_ACTION_OPEN_SHORT`:
   - `decision_reason_code` MUST be `DECISION_REASON_PROCEED_SHORT`. Otherwise raise `OrchestratorDecisionDomainError("open_short_requires_proceed_short_reason", field="decision_reason_code")`.
   - `input_prediction_direction` MUST be `"short"`. Otherwise raise `OrchestratorDecisionDomainError("open_short_requires_short_input_direction", field="input_prediction_direction")`.
3. If `decision_action == DECISION_ACTION_HOLD`:
   - `decision_reason_code` MUST be `DECISION_REASON_HOLD_FLAT_DIRECTION`. Otherwise raise `OrchestratorDecisionDomainError("hold_requires_hold_flat_direction_reason", field="decision_reason_code")`.
   - `input_prediction_direction` MUST be `"flat"`. Otherwise raise `OrchestratorDecisionDomainError("hold_requires_flat_input_direction", field="input_prediction_direction")`.
4. If `decision_action == DECISION_ACTION_ABSTAIN`:
   - `decision_reason_code` MUST start with the literal `"abstain_"`. Otherwise raise `OrchestratorDecisionDomainError("abstain_requires_abstain_prefix_reason", field="decision_reason_code")`.

The cross-field checks run AFTER per-field checks. Order of checks within `__post_init__` is: id-charset checks, symbol checks, ts_ms check, action membership, reason membership, input direction membership, confidence type and range, freshness membership, worker health membership, live_blocked check, then cross-field checks. The order must be deterministic and is verified by tests.

## Imports allowed in record.py

- `from __future__ import annotations`
- `import math`
- `from dataclasses import dataclass`
- `from .errors import OrchestratorDecisionDomainError`

No other import is permitted in `record.py`. No `typing` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `redis*` import. No `httpx` import. No `requests` import. No `fastapi` import. No `url_env` import. No factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.services.*`, `v2.backend.app.composition.*`, or `v2.backend.app.api.*`.

## Imports allowed in __init__.py

- `from .errors import OrchestratorDecisionDomainError`
- `from .record import (OrchestratorDecisionRecord, DECISION_ACTION_OPEN_LONG, DECISION_ACTION_OPEN_SHORT, DECISION_ACTION_HOLD, DECISION_ACTION_ABSTAIN, DECISION_REASON_PROCEED_LONG, DECISION_REASON_PROCEED_SHORT, DECISION_REASON_HOLD_FLAT_DIRECTION, DECISION_REASON_ABSTAIN_LOW_CONFIDENCE, DECISION_REASON_ABSTAIN_FRESHNESS_STALE, DECISION_REASON_ABSTAIN_FRESHNESS_MISSING, DECISION_REASON_ABSTAIN_WORKER_DEGRADED, DECISION_REASON_ABSTAIN_WORKER_CRITICAL, DECISION_REASON_ABSTAIN_WORKER_UNKNOWN)`

`__all__` is defined explicitly with the fifteen names in the public-surface order. No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Forbidden tokens in source files

The three authored source files MUST NOT contain any of the following literal substrings (case sensitive):

- `redis`
- `Redis`
- `aioredis`
- `hiredis`
- `httpx`
- `requests`
- `fastapi`
- `FastAPI`
- `uvicorn`
- `subprocess`
- `socket`
- `os.environ`
- `os.getenv`
- `time.time`
- `time.monotonic`
- `datetime.now`
- `datetime.utcnow`
- `logging`
- `print(`
- `url_env`
- `gamma.real`
- `BEGIN_FILE`
- `END_FILE`

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/06_2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPLEMENTATION_REPORT.md` MUST cite each of the following 4 behavior contract steps with a one-line evidence pointer to function and line range in `record.py`:

1. Per-field charset and length invariants are enforced for the four id/symbol fields.
2. Per-field type, range, and membership invariants are enforced for the seven non-id fields.
3. `live_blocked` MUST be `True` and the check raises `OrchestratorDecisionDomainError("must_be_true", field="live_blocked")` on `False`.
4. Cross-field action/reason/direction invariants are enforced AFTER per-field checks.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/06_2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/07_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO.md` (one of the markers documented in `05_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO_REQUEST.md`).

PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC_READY
