# Phase 2H.B — Paper Execution Ledger Assembler Service Spec

This document is the authoring spec for Phase 2H.B of REQ_0006 ∩ REQ_0017. Phase 2H.B is the second sub-phase of the `PAPER_EXECUTION_LEDGER_MVP` milestone. It builds a NEW services-layer package `v2/backend/app/services/paper_execution_ledger/` whose only purpose is to define a single pure assembler function `assemble_paper_execution_ledger_entry(...)` that takes a validated `RiskDecisionRecord` (from the Stage 2G.A risk gateway domain) plus a `now_ms_clock` callable, and returns a frozen `PaperExecutionLedgerEntry` constructed under the mirror taxonomy fixed by 2H.A.

The package is a pure derivation surface. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The function MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2H.A domain Codex pass: `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `136_paper_execution_ledger_2hb_assembler_service_implementation`.

## Module location decision

The new package is `v2/backend/app/services/paper_execution_ledger/`. It is a sibling of `v2/backend/app/services/risk_gateway/`, `v2/backend/app/services/orchestrator_decision/`, `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

There is NO pre-existing `v2/backend/app/services/paper_execution_ledger.py` placeholder file in the committed tree. 2H.B therefore does NOT include a placeholder-deletion step (in contrast to 2G.B which deleted `v2/backend/app/services/risk_gateway.py`).

No other `v2/backend/app/services/` package, no `v2/backend/app/composition/` package, no `v2/backend/app/adapters/` package, no `v2/backend/app/api/` package, no `v2/backend/app/cli/` package, no `v2/backend/app/jobs/` package, no `v2/backend/app/main.py`, no domain package, and no frontend file is modified by 2H.B.

## Scope (additive only)

Filesystem mutations performed by task `136`:

- create: `v2/backend/app/services/paper_execution_ledger/__init__.py`
- create: `v2/backend/app/services/paper_execution_ledger/errors.py`
- create: `v2/backend/app/services/paper_execution_ledger/service.py`
- create: `v2/backend/tests/unit/services/paper_execution_ledger/__init__.py`
- create: 28 sibling test files enumerated in `12_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_TEST_PLAN.md`.
- create: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- create: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md`

The existing `v2/backend/tests/unit/services/__init__.py` package marker is reused as-is and is NOT re-emitted by 2H.B.

## Public surface (exact `__all__`)

`v2/backend/app/services/paper_execution_ledger/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `assemble_paper_execution_ledger_entry`
2. `PaperExecutionLedgerServiceError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the two re-exports.

## PaperExecutionLedgerServiceError

`errors.py` defines:

```
from __future__ import annotations


class PaperExecutionLedgerServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "PaperExecutionLedgerServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Function signature

`service.py` defines exactly one public function:

```
def assemble_paper_execution_ledger_entry(
    *,
    decision: RiskDecisionRecord,
    now_ms_clock: Callable[[], int],
) -> PaperExecutionLedgerEntry:
    ...
```

The function is keyword-only (the leading `*` makes both parameters keyword-only). It has no default values for any parameter. It returns a `PaperExecutionLedgerEntry` value object (the same frozen dataclass authored by 2H.A).

The function MUST NOT capture or memoize any of the two parameters. It MUST NOT mutate any global state. It MUST NOT spawn threads, processes, or subprocesses. It MUST NOT log via `logging` or `print(`.

## Validation order in `assemble_paper_execution_ledger_entry`

The function performs the following ordered checks. The order is deterministic and is verified by tests. Each step raises `PaperExecutionLedgerServiceError(code, field=...)` with the specified `code` and `field`.

1. `decision` is an instance of `RiskDecisionRecord`. Otherwise raise `PaperExecutionLedgerServiceError("must_be_risk_decision_record", field="decision")`.
2. `now_ms_clock` is callable. Otherwise raise `PaperExecutionLedgerServiceError("must_be_callable", field="now_ms_clock")`.
3. Call `now_ms_clock()` exactly once. Bind the return value to `now_ms`.
4. `type(now_ms) is int` (and not `bool`). Otherwise raise `PaperExecutionLedgerServiceError("must_be_int", field="now_ms_clock")`.
5. `now_ms >= 0`. Otherwise raise `PaperExecutionLedgerServiceError("must_be_nonnegative", field="now_ms_clock")`.
6. `len(decision.risk_decision_id) <= 125`. Otherwise raise `PaperExecutionLedgerServiceError("risk_decision_id_too_long_for_paper_trade_id_derivation", field="decision.risk_decision_id")`. The 125-character cap keeps the derived `paper_trade_id` within the 128-character cap enforced by the 2H.A `PaperExecutionLedgerEntry.paper_trade_id` invariant (3 prefix characters + 125 body characters = 128).

After the six validation steps pass, the function performs the mirror derivation table below and returns a frozen `PaperExecutionLedgerEntry`.

## paper_trade_id derivation

`paper_trade_id = "pt_" + decision.risk_decision_id`. The derivation is deterministic and pure. The string `"pt_"` is a three-character literal. The maximum length of `paper_trade_id` is `3 + 125 = 128`, exactly the 2H.A invariant cap.

## Mirror derivation table (ordered)

The first matching condition wins. The order is fixed and is verified by tests. The five cases are exhaustive over the 2G.A `_ALLOWED_RISK_REASONS` frozenset.

1. `decision.risk_reason_code == "allow_proceed_long"` → `ledger_action = "record_allow"`, `ledger_reason_code = "mirror_allow_proceed_long"`.
2. `decision.risk_reason_code == "allow_proceed_short"` → `ledger_action = "record_allow"`, `ledger_reason_code = "mirror_allow_proceed_short"`.
3. `decision.risk_reason_code == "deny_orchestrator_held"` → `ledger_action = "record_deny"`, `ledger_reason_code = "mirror_deny_orchestrator_held"`.
4. `decision.risk_reason_code == "deny_orchestrator_abstained"` → `ledger_action = "record_deny"`, `ledger_reason_code = "mirror_deny_orchestrator_abstained"`.
5. `decision.risk_reason_code == "deny_default"` → `ledger_action = "record_deny"`, `ledger_reason_code = "mirror_deny_default"`.
6. Defensive fallback (unreachable under the 2G.A invariant): raise `PaperExecutionLedgerServiceError("unrecognized_risk_reason_code", field="decision.risk_reason_code")`.

The function uses the imported domain-layer constants `PAPER_LEDGER_ACTION_RECORD_*` and `PAPER_LEDGER_REASON_MIRROR_*` from `v2.backend.app.domain.paper_execution_ledger` and `RISK_DECISION_REASON_*` from `v2.backend.app.domain.risk_gateway` for these literal comparisons; the literal strings above are documentation only.

## PaperExecutionLedgerEntry construction

After derivation, the function returns:

```
PaperExecutionLedgerEntry(
    paper_trade_id=paper_trade_id,
    risk_decision_id=decision.risk_decision_id,
    decision_id=decision.decision_id,
    prediction_id=decision.prediction_id,
    feature_snapshot_id=decision.feature_snapshot_id,
    symbol=decision.symbol,
    ledger_entry_ts_ms=now_ms,
    ledger_action=ledger_action,
    ledger_reason_code=ledger_reason_code,
    input_risk_action=decision.risk_action,
    input_risk_reason_code=decision.risk_reason_code,
    live_blocked=True,
)
```

`live_blocked` is the literal Python boolean `True` at every call site. The function MUST NOT accept any caller-provided `live_blocked` value.

The `decision.risk_action` is propagated unchanged into `input_risk_action`. The `decision.risk_reason_code` is propagated unchanged into `input_risk_reason_code`. The 2H.A value-object layer enforces membership in the 5-member `_ALLOWED_INPUT_RISK_REASONS` frozenset, which is exactly the union of the 2G.A `RISK_DECISION_REASON_*` values, so any 2G-validated `RiskDecisionRecord` produces an `input_risk_reason_code` that the 2H.A invariants accept. The 2H.A cross-field invariants (record_allow ↔ mirror_allow_*, record_deny ↔ mirror_deny_*, one-to-one mapping between `ledger_reason_code` and `input_risk_reason_code`) are satisfied by the derivation table above by construction.

## Imports allowed in service.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.paper_execution_ledger import (PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT, PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, PaperExecutionLedgerEntry)`
- `from v2.backend.app.domain.risk_gateway import (RISK_DECISION_REASON_ALLOW_PROCEED_LONG, RISK_DECISION_REASON_ALLOW_PROCEED_SHORT, RISK_DECISION_REASON_DENY_DEFAULT, RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED, RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD, RiskDecisionRecord)`
- `from .errors import PaperExecutionLedgerServiceError`

No other import is permitted in `service.py`. No `math` import (no float fields). No `typing` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `redis*` import. No `httpx` import. No `requests` import. No `fastapi` import. No `url_env` import. No factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`, `v2.backend.app.main.*`, or any other `v2.backend.app.services.*` sibling. No import of any `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, or `v2.backend.app.domain.liveness_stream_growth`.

## Imports allowed in __init__.py

- `from .service import assemble_paper_execution_ledger_entry`
- `from .errors import PaperExecutionLedgerServiceError`

`__all__` is defined explicitly with the two names in the public-surface order. No other import is permitted in `__init__.py`.

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
- `OrchestratorDecisionRecord`
- `BEGIN_FILE`
- `END_FILE`

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The harness BEGIN/END framing token marker line is also forbidden in any authored file body.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST cite each of the following 6 behavior contract steps with a one-line evidence pointer to function and line range in `service.py`:

1. The two up-front validation steps (decision instance, clock callable) run BEFORE the clock is invoked.
2. The clock is invoked exactly once and its return value is bound to `now_ms` and validated for type and non-negativity before use.
3. The 125-character cap on `decision.risk_decision_id` is enforced before `paper_trade_id` is derived and only depends on the decision value, not on the clock.
4. The mirror derivation table runs in the order documented in `11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md` 'Mirror derivation table (ordered)' and is exhaustive over the 2G.A `_ALLOWED_RISK_REASONS` frozenset (any unrecognized reason triggers the defensive fallback).
5. The `PaperExecutionLedgerEntry` is constructed with `live_blocked=True` as a literal boolean and propagates `decision.risk_decision_id`, `decision.decision_id`, `decision.prediction_id`, `decision.feature_snapshot_id`, `decision.symbol`, `decision.risk_action`, and `decision.risk_reason_code` without modification.
6. The function returns the `PaperExecutionLedgerEntry` value object directly; no caching, side effect, logging, or telemetry hop is interposed between construction and return; the 2H.A cross-field invariants (record_allow ↔ mirror_allow_*, record_deny ↔ mirror_deny_*, one-to-one mapping between `ledger_reason_code` and `input_risk_reason_code`, one-to-one mapping between `ledger_action` and `input_risk_action`) hold by construction for every row of the table.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md` (one of the markers documented in `14_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`).

PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC_READY
