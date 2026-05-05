# Phase 2G.A — Risk Gateway Domain Spec

This document is the authoring spec for Phase 2G.A of REQ_0006 ∩ REQ_0017. It is the first sub-phase of the `RISK_GATEWAY_DEFAULT_DENY_MVP` milestone. It builds a NEW domain package `v2/backend/app/domain/risk_gateway/` whose only purpose is to define the `RiskDecisionRecord` value object plus the risk-action and risk-reason constants that downstream risk gateway assembler service (2G.B), composition root (2G.C), and paper-execution-ledger (REQ_0017 milestone 4) milestones will consume.

The package is purely value-object oriented. It does NOT compute risk decisions. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2F.C composition root Codex pass: `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/25_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `126_risk_gateway_2ga_domain_implementation`.

## Module location decision

The new package is a sibling of `v2/backend/app/domain/orchestrator_decision/` and `v2/backend/app/domain/trainer_prediction_output/`. It is a NEW directory and does NOT live inside any other domain package. The pre-existing `v2/backend/app/domain/risk/` directory containing legacy-style scaffold files (`kill_switch.py`, `live_readiness_state.py`, `phases.py`, `policy_bundle.py`) is NOT modified, NOT used, and NOT renamed by 2G.A. The pre-existing empty `v2/backend/app/domain/decisions/` directory is NOT modified, NOT used, and NOT renamed by 2G.A.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, or 2F.C file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/risk_gateway/__init__.py`
- `v2/backend/app/domain/risk_gateway/errors.py`
- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/tests/unit/domain/risk_gateway/__init__.py`
- 31 sibling test files enumerated in `03_PHASE_2G_A_RISK_GATEWAY_DOMAIN_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/domain/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/domain/risk_gateway/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `RiskGatewayDomainError`
2. `RiskDecisionRecord`
3. `RISK_DECISION_ACTION_ALLOW`
4. `RISK_DECISION_ACTION_DENY`
5. `RISK_DECISION_REASON_ALLOW_PROCEED_LONG`
6. `RISK_DECISION_REASON_ALLOW_PROCEED_SHORT`
7. `RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED`
8. `RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD`
9. `RISK_DECISION_REASON_DENY_DEFAULT`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the nine re-exports.

## RiskGatewayDomainError

`errors.py` defines:

```
from __future__ import annotations


class RiskGatewayDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Risk action constants

`record.py` defines:

```
RISK_DECISION_ACTION_ALLOW = "allow"
RISK_DECISION_ACTION_DENY = "deny"
```

The two action values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-action frozenset enforced by `RiskDecisionRecord.__post_init__`.

## Risk reason constants

`record.py` defines:

```
RISK_DECISION_REASON_ALLOW_PROCEED_LONG = "allow_proceed_long"
RISK_DECISION_REASON_ALLOW_PROCEED_SHORT = "allow_proceed_short"
RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED = "deny_orchestrator_abstained"
RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD = "deny_orchestrator_held"
RISK_DECISION_REASON_DENY_DEFAULT = "deny_default"
```

The five reason values MUST be string literals, MUST be lowercase, MUST be unique, and MUST be the only members of the allowed-reason frozenset enforced by `RiskDecisionRecord.__post_init__`. Every `RISK_DECISION_REASON_ALLOW_*` value MUST start with the literal prefix `"allow_"`. Every `RISK_DECISION_REASON_DENY_*` value MUST start with the literal prefix `"deny_"`.

## RiskDecisionRecord

`record.py` defines:

```
@dataclass(frozen=True, slots=True)
class RiskDecisionRecord:
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    risk_decision_ts_ms: int
    risk_action: str
    risk_reason_code: str
    input_decision_action: str
    input_decision_reason_code: str
    live_blocked: bool

    def __post_init__(self) -> None:
        ...
```

The dataclass MUST be `frozen=True` AND `slots=True`. There MUST be no default values for any field. All fields are positional-and-keyword, but the test plan constructs records by keyword only.

### Per-field invariants enforced in `__post_init__`

Field-level checks (each invariant raises `RiskGatewayDomainError(reason, field=<field_name>)` with the field name set to the violating field):

- `risk_decision_id`: type `str`; non-empty; no leading/trailing whitespace; no internal whitespace; length ≤ 128.
- `decision_id`: same charset and length rules as `risk_decision_id`.
- `prediction_id`: same charset and length rules as `risk_decision_id`.
- `feature_snapshot_id`: same charset and length rules as `risk_decision_id`.
- `symbol`: type `str`; non-empty; no whitespace; length ≤ 32; equal to its own `.upper()`.
- `risk_decision_ts_ms`: type `int` (and not `bool`); ≥ 0.
- `risk_action`: type `str`; member of `_ALLOWED_RISK_ACTIONS = frozenset({"allow", "deny"})`.
- `risk_reason_code`: type `str`; member of `_ALLOWED_RISK_REASONS = frozenset({"allow_proceed_long", "allow_proceed_short", "deny_orchestrator_abstained", "deny_orchestrator_held", "deny_default"})`.
- `input_decision_action`: type `str`; member of `_ALLOWED_INPUT_DECISION_ACTIONS = frozenset({"open_long", "open_short", "hold", "abstain"})`.
- `input_decision_reason_code`: type `str`; member of `_ALLOWED_INPUT_DECISION_REASONS = frozenset({"proceed_long", "proceed_short", "hold_flat_direction", "abstain_low_confidence", "abstain_freshness_stale", "abstain_freshness_missing", "abstain_worker_degraded", "abstain_worker_critical", "abstain_worker_unknown"})`.
- `live_blocked`: type `bool`; MUST be `True`.

### Cross-field invariants enforced in `__post_init__`

After per-field checks pass:

1. If `risk_action == RISK_DECISION_ACTION_ALLOW`:
   - `risk_reason_code` MUST start with the literal `"allow_"`. Otherwise raise `RiskGatewayDomainError("allow_requires_allow_prefix_reason", field="risk_reason_code")`.
2. If `risk_action == RISK_DECISION_ACTION_DENY`:
   - `risk_reason_code` MUST start with the literal `"deny_"`. Otherwise raise `RiskGatewayDomainError("deny_requires_deny_prefix_reason", field="risk_reason_code")`.
3. If `risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_LONG`:
   - `input_decision_action` MUST be `"open_long"`. Otherwise raise `RiskGatewayDomainError("allow_proceed_long_requires_open_long_input", field="input_decision_action")`.
   - `input_decision_reason_code` MUST be `"proceed_long"`. Otherwise raise `RiskGatewayDomainError("allow_proceed_long_requires_proceed_long_input_reason", field="input_decision_reason_code")`.
4. If `risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_SHORT`:
   - `input_decision_action` MUST be `"open_short"`. Otherwise raise `RiskGatewayDomainError("allow_proceed_short_requires_open_short_input", field="input_decision_action")`.
   - `input_decision_reason_code` MUST be `"proceed_short"`. Otherwise raise `RiskGatewayDomainError("allow_proceed_short_requires_proceed_short_input_reason", field="input_decision_reason_code")`.
5. If `risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED`:
   - `input_decision_action` MUST be `"abstain"`. Otherwise raise `RiskGatewayDomainError("deny_orchestrator_abstained_requires_abstain_input", field="input_decision_action")`.
6. If `risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD`:
   - `input_decision_action` MUST be `"hold"`. Otherwise raise `RiskGatewayDomainError("deny_orchestrator_held_requires_hold_input", field="input_decision_action")`.
7. If `risk_reason_code == RISK_DECISION_REASON_DENY_DEFAULT`:
   - `input_decision_action` MUST be a member of `frozenset({"open_long", "open_short"})`. Otherwise raise `RiskGatewayDomainError("deny_default_requires_tradable_input", field="input_decision_action")`.

The cross-field checks run AFTER per-field checks. Order of checks within `__post_init__` is: id-charset checks, symbol checks, ts_ms check, risk_action membership, risk_reason_code membership, input_decision_action membership, input_decision_reason_code membership, live_blocked check, then cross-field checks 1 through 7 in the documented order. The order must be deterministic and is verified by tests.

## Imports allowed in record.py

- `from __future__ import annotations`
- `from dataclasses import dataclass`
- `from .errors import RiskGatewayDomainError`

No other import is permitted in `record.py`. No `math` import (no float fields). No `typing` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `redis*` import. No `httpx` import. No `requests` import. No `fastapi` import. No `url_env` import. No factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.services.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, or `v2.backend.app.domain.trainer_liveness`.

## Imports allowed in __init__.py

- `from .errors import RiskGatewayDomainError`
- `from .record import (RiskDecisionRecord, RISK_DECISION_ACTION_ALLOW, RISK_DECISION_ACTION_DENY, RISK_DECISION_REASON_ALLOW_PROCEED_LONG, RISK_DECISION_REASON_ALLOW_PROCEED_SHORT, RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED, RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD, RISK_DECISION_REASON_DENY_DEFAULT)`

`__all__` is defined explicitly with the nine names in the public-surface order. No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Forbidden tokens in source files

The three authored source files MUST NOT contain any of the following literal substrings (case sensitive):

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
- `BEGIN_FILE`
- `END_FILE`

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/risk_gateway_impl/06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md` MUST cite each of the following 4 behavior contract steps with a one-line evidence pointer to function and line range in `record.py`:

1. Per-field charset and length invariants are enforced for the four id and the symbol fields.
2. Per-field type, range, and membership invariants are enforced for the six non-id fields.
3. `live_blocked` MUST be `True` and the check raises `RiskGatewayDomainError("must_be_true", field="live_blocked")` on `False`.
4. Cross-field action/reason/input-action invariants are enforced AFTER per-field checks, in the order documented in this spec.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md` (one of the markers documented in `05_PHASE_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO_REQUEST.md`).

PHASE2G_A_RISK_GATEWAY_DOMAIN_SPEC_READY
