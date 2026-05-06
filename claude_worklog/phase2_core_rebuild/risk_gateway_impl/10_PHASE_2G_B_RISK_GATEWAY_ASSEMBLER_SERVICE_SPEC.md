# Phase 2G.B — Risk Gateway Assembler Service Spec

This document is the authoring spec for Phase 2G.B of REQ_0006 ∩ REQ_0017. Phase 2G.B is the second sub-phase of the `RISK_GATEWAY_DEFAULT_DENY_MVP` milestone. It builds a NEW services-layer package `v2/backend/app/services/risk_gateway/` whose only purpose is to define a single pure assembler function `assemble_risk_decision_record(...)` that takes a validated `OrchestratorDecisionRecord` (from the Stage 2F.A orchestrator decision domain) plus a `now_ms_clock` callable, and returns a frozen `RiskDecisionRecord` constructed under the default-deny taxonomy fixed by 2G.A.

The package is a pure derivation surface. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The function MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2G.A domain Codex pass: `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`.

If this marker is absent or different, the supervisor MUST NOT dispatch `128_risk_gateway_2gb_assembler_service_implementation`.

## Module location decision

The new package is `v2/backend/app/services/risk_gateway/`. It is a sibling of `v2/backend/app/services/orchestrator_decision/`, `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

The existing one-line placeholder file `v2/backend/app/services/risk_gateway.py` (whose sole content is a docstring beginning with `"""Risk gateway service placeholder. No behavior in scaffold.`) collides with this new package on the import path. Phase 2G.B opens by deleting that placeholder file in the same supervisor task that authors the new package. The placeholder file MUST NOT be reintroduced.

No other `v2/backend/app/services/` package, no `v2/backend/app/composition/` package, no `v2/backend/app/adapters/` package, no `v2/backend/app/api/` package, no `v2/backend/app/cli/` package, no `v2/backend/app/jobs/` package, no `v2/backend/app/main.py`, no domain package, and no frontend file is modified by 2G.B.

## Scope (additive only — except the placeholder deletion)

Filesystem mutations performed by task `128`:

- delete: `v2/backend/app/services/risk_gateway.py` (one-line placeholder)
- create: `v2/backend/app/services/risk_gateway/__init__.py`
- create: `v2/backend/app/services/risk_gateway/errors.py`
- create: `v2/backend/app/services/risk_gateway/service.py`
- create: `v2/backend/tests/unit/services/risk_gateway/__init__.py`
- create: 29 sibling test files enumerated in `11_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_TEST_PLAN.md`.
- create: `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- create: `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`

The existing `v2/backend/tests/unit/services/__init__.py` package marker is reused as-is and is NOT re-emitted by 2G.B.

## Public surface (exact `__all__`)

`v2/backend/app/services/risk_gateway/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `assemble_risk_decision_record`
2. `RiskGatewayServiceError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the two re-exports.

## RiskGatewayServiceError

`errors.py` defines:

```
from __future__ import annotations


class RiskGatewayServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "RiskGatewayServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Function signature

`service.py` defines exactly one public function:

```
def assemble_risk_decision_record(
    *,
    decision: OrchestratorDecisionRecord,
    now_ms_clock: Callable[[], int],
) -> RiskDecisionRecord:
    ...
```

The function is keyword-only (the leading `*` makes both parameters keyword-only). It has no default values for any parameter. It returns a `RiskDecisionRecord` value object (the same frozen dataclass authored by 2G.A).

The function MUST NOT capture or memoize any of the two parameters. It MUST NOT mutate any global state. It MUST NOT spawn threads, processes, or subprocesses. It MUST NOT log via `logging` or `print(`.

## Validation order in `assemble_risk_decision_record`

The function performs the following ordered checks. The order is deterministic and is verified by tests. Each step raises `RiskGatewayServiceError(code, field=...)` with the specified `code` and `field`.

1. `decision` is an instance of `OrchestratorDecisionRecord`. Otherwise raise `RiskGatewayServiceError("must_be_orchestrator_decision_record", field="decision")`.
2. `now_ms_clock` is callable. Otherwise raise `RiskGatewayServiceError("must_be_callable", field="now_ms_clock")`.
3. Call `now_ms_clock()` exactly once. Bind the return value to `now_ms`.
4. `type(now_ms) is int` (and not `bool`). Otherwise raise `RiskGatewayServiceError("must_be_int", field="now_ms_clock")`.
5. `now_ms >= 0`. Otherwise raise `RiskGatewayServiceError("must_be_nonnegative", field="now_ms_clock")`.
6. `len(decision.decision_id) <= 125`. Otherwise raise `RiskGatewayServiceError("decision_id_too_long_for_risk_decision_id_derivation", field="decision.decision_id")`. The 125-character cap keeps the derived `risk_decision_id` within the 128-character cap enforced by the 2G.A `RiskDecisionRecord.risk_decision_id` invariant (3 prefix characters + 125 body characters = 128).

After the six validation steps pass, the function performs the default-deny derivation table below and returns a frozen `RiskDecisionRecord`.

## risk_decision_id derivation

`risk_decision_id = "rd_" + decision.decision_id`. The derivation is deterministic and pure. The string `"rd_"` is a three-character literal. The maximum length of `risk_decision_id` is `3 + 125 = 128`, exactly the 2G.A invariant cap.

## Default-deny derivation table (ordered)

The first matching condition wins. The order is fixed and is verified by tests. The four cases are exhaustive over the 2F.A `_ALLOWED_DECISION_ACTIONS` frozenset.

1. `decision.decision_action == "open_long"` → `risk_action = "allow"`, `risk_reason_code = "allow_proceed_long"`.
2. `decision.decision_action == "open_short"` → `risk_action = "allow"`, `risk_reason_code = "allow_proceed_short"`.
3. `decision.decision_action == "hold"` → `risk_action = "deny"`, `risk_reason_code = "deny_orchestrator_held"`.
4. `decision.decision_action == "abstain"` → `risk_action = "deny"`, `risk_reason_code = "deny_orchestrator_abstained"`.
5. Defensive fallback (unreachable under the 2F.A invariant): raise `RiskGatewayServiceError("unrecognized_decision_action", field="decision.decision_action")`.

The function uses the imported domain-layer constants `RISK_DECISION_ACTION_*`, `RISK_DECISION_REASON_ALLOW_*`, `RISK_DECISION_REASON_DENY_ORCHESTRATOR_*` from `v2.backend.app.domain.risk_gateway` and `DECISION_ACTION_OPEN_LONG`, `DECISION_ACTION_OPEN_SHORT`, `DECISION_ACTION_HOLD`, `DECISION_ACTION_ABSTAIN` from `v2.backend.app.domain.orchestrator_decision` for these literal comparisons; the literal strings above are documentation only.

The 2G.A reserved constant `RISK_DECISION_REASON_DENY_DEFAULT` is NOT imported and is NOT emitted by 2G.B. A regression test enumerated in 11 confirms that the assembler never emits `deny_default` for any orchestrator-decision input under the 2F.A invariant.

## RiskDecisionRecord construction

After derivation, the function returns:

```
RiskDecisionRecord(
    risk_decision_id=risk_decision_id,
    decision_id=decision.decision_id,
    prediction_id=decision.prediction_id,
    feature_snapshot_id=decision.feature_snapshot_id,
    symbol=decision.symbol,
    risk_decision_ts_ms=now_ms,
    risk_action=risk_action,
    risk_reason_code=risk_reason_code,
    input_decision_action=decision.decision_action,
    input_decision_reason_code=decision.decision_reason_code,
    live_blocked=True,
)
```

`live_blocked` is the literal Python boolean `True` at every call site. The function MUST NOT accept any caller-provided `live_blocked` value.

The `decision.decision_reason_code` is propagated unchanged into `input_decision_reason_code`. The 2G.A value-object layer enforces membership in the 9-member `_ALLOWED_INPUT_DECISION_REASONS` frozenset, which is exactly the union of the 2F.A `DECISION_REASON_*` values, so any 2F.A-validated `OrchestratorDecisionRecord` produces an `input_decision_reason_code` that the 2G.A invariants accept.

## Imports allowed in service.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.orchestrator_decision import (DECISION_ACTION_ABSTAIN, DECISION_ACTION_HOLD, DECISION_ACTION_OPEN_LONG, DECISION_ACTION_OPEN_SHORT, OrchestratorDecisionRecord)`
- `from v2.backend.app.domain.risk_gateway import (RISK_DECISION_ACTION_ALLOW, RISK_DECISION_ACTION_DENY, RISK_DECISION_REASON_ALLOW_PROCEED_LONG, RISK_DECISION_REASON_ALLOW_PROCEED_SHORT, RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED, RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD, RiskDecisionRecord)`
- `from .errors import RiskGatewayServiceError`

No other import is permitted in `service.py`. No `math` import (no float fields). No `typing` import. No `time` import. No `datetime` import. No `logging` import. No `os` import. No `subprocess` import. No `socket` import. No `pathlib` import. No `multiprocessing` import. No `threading` import. No `asyncio` import. No `redis*` import. No `httpx` import. No `requests` import. No `fastapi` import. No `url_env` import. No factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`, `v2.backend.app.main.*`, or any other `v2.backend.app.services.*` sibling. No import of any `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, or `v2.backend.app.domain.liveness_stream_growth`. No import of `RISK_DECISION_REASON_DENY_DEFAULT`.

## Imports allowed in __init__.py

- `from .service import assemble_risk_decision_record`
- `from .errors import RiskGatewayServiceError`

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
- `RISK_DECISION_REASON_DENY_DEFAULT`
- `deny_default`
- `BEGIN_FILE`
- `END_FILE`

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The harness BEGIN/END framing token marker line is also forbidden in any authored file body.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST cite each of the following 6 behavior contract steps with a one-line evidence pointer to function and line range in `service.py`:

1. The two up-front validation steps (decision instance, clock callable) run BEFORE the clock is invoked.
2. The clock is invoked exactly once and its return value is bound to `now_ms` and validated for type and non-negativity before use.
3. The 125-character cap on `decision.decision_id` is enforced before `risk_decision_id` is derived and only depends on the decision value, not on the clock.
4. The default-deny derivation table runs in the order documented in `10_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC.md` 'Default-deny derivation table (ordered)' and is exhaustive over the 2F.A `_ALLOWED_DECISION_ACTIONS` frozenset (any unrecognized action triggers the defensive fallback).
5. The `RiskDecisionRecord` is constructed with `live_blocked=True` as a literal boolean and propagates `decision.decision_id`, `decision.prediction_id`, `decision.feature_snapshot_id`, `decision.symbol`, `decision.decision_action`, and `decision.decision_reason_code` without modification.
6. The function returns the `RiskDecisionRecord` value object directly; no caching, side effect, logging, or telemetry hop is interposed between construction and return; the reserved `RISK_DECISION_REASON_DENY_DEFAULT` member is never emitted.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md` (one of the markers documented in `13_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`).

PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC_READY
