# Phase 2I.B — Replay/Backtest Runner Assembler Service Spec

This document is the authoring spec for Phase 2I.B of REQ_0006 ∩ REQ_0017. Phase 2I.B is the second sub-phase of the `REPLAY_BACKTEST_RUNNER_MVP` milestone. It builds a NEW services-layer package `v2/backend/app/services/replay_backtest_runner/` whose only purpose is to define two pure assembler functions plus one service-level error class:

1. `assemble_replay_backtest_step(*, paper_ledger_entry: PaperExecutionLedgerEntry, replay_run: ReplayBacktestRun, now_ms_clock: Callable[[], int]) -> ReplayBacktestStep` — takes a 2H-validated `PaperExecutionLedgerEntry`, a 2I.A-validated `ReplayBacktestRun`, and a `now_ms_clock` callable; returns a frozen `ReplayBacktestStep` constructed under the mirror taxonomy fixed by 2I.A.
2. `assemble_replay_backtest_summary(*, replay_run: ReplayBacktestRun, steps: tuple[ReplayBacktestStep, ...], now_ms_clock: Callable[[], int]) -> ReplayBacktestSummary` — takes a 2I.A-validated `ReplayBacktestRun`, a tuple of 2I.A-validated `ReplayBacktestStep` instances, and a `now_ms_clock` callable; returns a frozen `ReplayBacktestSummary` whose three partition-sum equalities hold by construction.
3. `ReplayBacktestRunnerServiceError` — service-level error class for input-validation failures. Domain-level invariants are enforced by 2I.A `__post_init__` and surface as `ReplayBacktestRunnerDomainError`.

The package is a pure derivation surface. It does NOT call a model. It does NOT touch I/O, Redis, files, or HTTP. It does NOT compute PnL, quantity, price, fees, or slippage. Importing the package MUST NOT cause `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`, `httpx`, `requests`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`. Importing the package MUST NOT register any FastAPI lifespan, dependency, or router. The functions MUST NOT introduce any module-level singleton, cache, or lock.

## Predecessor gates

- 2I.A domain Codex pass: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md`.
- 2I.A domain validation pass: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md`.

If either is absent or different, the supervisor MUST NOT dispatch `146_replay_backtest_runner_2ib_assembler_service_implementation`.

## Module location decision

The new package is `v2/backend/app/services/replay_backtest_runner/`. It is a sibling of `v2/backend/app/services/paper_execution_ledger/`, `v2/backend/app/services/risk_gateway/`, `v2/backend/app/services/orchestrator_decision/`, `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

The pre-existing `v2/backend/app/services/replay_runner.py` (one-line scaffold docstring placeholder) is NOT modified, NOT used, and NOT renamed by 2I.B. The pre-existing `v2/backend/app/services/paper_loop.py` placeholder is NOT modified, NOT used, and NOT renamed by 2I.B.

No 2H.A, 2H.B, 2H.C, 2I.A, 2G.A, 2G.B, 2G.C, 2F.A, 2F.B, 2F.C, 2E1, 2E2, or 2E3 file is modified by this milestone.

## Scope (additive only)

Filesystem mutations performed by task `146`:

- create: `v2/backend/app/services/replay_backtest_runner/__init__.py`
- create: `v2/backend/app/services/replay_backtest_runner/errors.py`
- create: `v2/backend/app/services/replay_backtest_runner/service.py`
- create: `v2/backend/tests/unit/services/replay_backtest_runner/__init__.py` (zero bytes)
- create: 40 single-test files enumerated in `11_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_TEST_PLAN.md`.
- create: `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/14_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- create: `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md`

The existing `v2/backend/tests/unit/services/__init__.py` package marker is reused as-is and is NOT re-emitted by 2I.B.

## Public surface (exact `__all__`)

`v2/backend/app/services/replay_backtest_runner/__init__.py` exposes exactly the following names, in this order, in `__all__`:

1. `assemble_replay_backtest_step`
2. `assemble_replay_backtest_summary`
3. `ReplayBacktestRunnerServiceError`

No other names are re-exported. The `__init__.py` MUST NOT introduce any module-level globals beyond the three re-exports.

## ReplayBacktestRunnerServiceError

`errors.py` defines:

```
from __future__ import annotations


class ReplayBacktestRunnerServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "ReplayBacktestRunnerServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`errors.py` imports nothing beyond `from __future__ import annotations`. It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`, `redis.asyncio`, `httpx`, `requests`, `fastapi`, the gamma.real factory, or `url_env`.

## Function signatures

`service.py` defines exactly two public functions:

```
def assemble_replay_backtest_step(
    *,
    paper_ledger_entry: PaperExecutionLedgerEntry,
    replay_run: ReplayBacktestRun,
    now_ms_clock: Callable[[], int],
) -> ReplayBacktestStep:
    ...


def assemble_replay_backtest_summary(
    *,
    replay_run: ReplayBacktestRun,
    steps: tuple[ReplayBacktestStep, ...],
    now_ms_clock: Callable[[], int],
) -> ReplayBacktestSummary:
    ...
```

Both functions are keyword-only (the leading `*` makes every parameter keyword-only). Neither function has default values for any parameter. Both functions return frozen value objects authored by 2I.A.

Both functions MUST NOT capture or memoize any of their parameters. Both MUST NOT mutate any global state. Both MUST NOT spawn threads, processes, or subprocesses. Both MUST NOT log via `logging` or `print(`.

## Validation order in `assemble_replay_backtest_step`

The function performs the following ordered checks. The order is deterministic and is verified by tests. Each step raises `ReplayBacktestRunnerServiceError(code, field=...)` with the specified `code` and `field`.

1. `paper_ledger_entry` is an instance of `PaperExecutionLedgerEntry`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_paper_execution_ledger_entry", field="paper_ledger_entry")`.
2. `replay_run` is an instance of `ReplayBacktestRun`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_replay_backtest_run", field="replay_run")`.
3. `now_ms_clock` is callable. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_callable", field="now_ms_clock")`.
4. Call `now_ms_clock()` exactly once. Bind the return value to `now_ms`.
5. `type(now_ms) is int` (and not `bool`). Otherwise raise `ReplayBacktestRunnerServiceError("must_be_int", field="now_ms_clock")`.
6. `now_ms >= 0`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_nonnegative", field="now_ms_clock")`.
7. `now_ms >= replay_run.run_started_ts_ms`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_at_or_after_run_started_ts_ms", field="now_ms_clock")`.
8. `paper_ledger_entry.symbol == replay_run.symbol`. Otherwise raise `ReplayBacktestRunnerServiceError("paper_ledger_entry_symbol_must_match_replay_run_symbol", field="paper_ledger_entry.symbol")`.
9. `len(paper_ledger_entry.paper_trade_id) <= 122`. Otherwise raise `ReplayBacktestRunnerServiceError("paper_trade_id_too_long_for_replay_step_id_derivation", field="paper_ledger_entry.paper_trade_id")`. The 122-character cap keeps the derived `replay_step_id` within the 128-character cap enforced by the 2I.A `ReplayBacktestStep.replay_step_id` invariant (6 prefix characters + 122 body characters = 128).

After the nine validation steps pass, the function performs the mirror derivation table below and returns a frozen `ReplayBacktestStep`.

## replay_step_id derivation

`replay_step_id = "rstep_" + paper_ledger_entry.paper_trade_id`. The derivation is deterministic and pure. The string `"rstep_"` is a six-character literal. The maximum length of `replay_step_id` is `6 + 122 = 128`, exactly the 2I.A invariant cap.

## Mirror derivation table for step (ordered)

The first matching condition wins. The order is fixed and is verified by tests. The five cases are exhaustive over the 2H.A `_ALLOWED_LEDGER_REASON_CODES` frozenset.

1. `paper_ledger_entry.ledger_reason_code == "mirror_allow_proceed_long"` → `step_action = "step_record_allow"`, `step_reason_code = "step_mirror_allow_proceed_long"`.
2. `paper_ledger_entry.ledger_reason_code == "mirror_allow_proceed_short"` → `step_action = "step_record_allow"`, `step_reason_code = "step_mirror_allow_proceed_short"`.
3. `paper_ledger_entry.ledger_reason_code == "mirror_deny_orchestrator_held"` → `step_action = "step_record_deny"`, `step_reason_code = "step_mirror_deny_orchestrator_held"`.
4. `paper_ledger_entry.ledger_reason_code == "mirror_deny_orchestrator_abstained"` → `step_action = "step_record_deny"`, `step_reason_code = "step_mirror_deny_orchestrator_abstained"`.
5. `paper_ledger_entry.ledger_reason_code == "mirror_deny_default"` → `step_action = "step_record_deny"`, `step_reason_code = "step_mirror_deny_default"`.
6. Defensive fallback (unreachable under the 2H.A invariant): raise `ReplayBacktestRunnerServiceError("unrecognized_paper_ledger_reason_code", field="paper_ledger_entry.ledger_reason_code")`.

The function uses the imported domain-layer constants `STEP_ACTION_RECORD_*` and `STEP_REASON_MIRROR_*` from `v2.backend.app.domain.replay_backtest_runner` for the assignment and uses string-literal comparison against the 2H.A `PAPER_LEDGER_REASON_MIRROR_*` constants imported from `v2.backend.app.domain.paper_execution_ledger` for the table dispatch; the literal strings above are documentation only.

## ReplayBacktestStep construction

After derivation, the function returns:

```
ReplayBacktestStep(
    replay_step_id=replay_step_id,
    replay_run_id=replay_run.replay_run_id,
    paper_trade_id=paper_ledger_entry.paper_trade_id,
    risk_decision_id=paper_ledger_entry.risk_decision_id,
    decision_id=paper_ledger_entry.decision_id,
    prediction_id=paper_ledger_entry.prediction_id,
    feature_snapshot_id=paper_ledger_entry.feature_snapshot_id,
    symbol=paper_ledger_entry.symbol,
    step_ts_ms=now_ms,
    step_action=step_action,
    step_reason_code=step_reason_code,
    input_paper_action=paper_ledger_entry.ledger_action,
    input_paper_reason_code=paper_ledger_entry.ledger_reason_code,
    live_blocked=True,
)
```

`live_blocked` is the literal Python boolean `True` at the call site. The function MUST NOT accept any caller-provided `live_blocked` value.

The `paper_ledger_entry.ledger_action` is propagated unchanged into `input_paper_action`. The `paper_ledger_entry.ledger_reason_code` is propagated unchanged into `input_paper_reason_code`. The 2I.A value-object layer enforces membership in the 2-member `_ALLOWED_INPUT_PAPER_ACTIONS` frozenset and the 5-member `_ALLOWED_INPUT_PAPER_REASONS` frozenset, which exactly mirror the 2H.A `PAPER_LEDGER_ACTION_RECORD_*` and `PAPER_LEDGER_REASON_MIRROR_*` values, so any 2H-validated `PaperExecutionLedgerEntry` produces an `input_paper_action` and an `input_paper_reason_code` that the 2I.A invariants accept. The 2I.A cross-field invariants (step_record_allow ↔ step_mirror_allow_*, step_record_deny ↔ step_mirror_deny_*, one-to-one mapping between `step_reason_code` and `input_paper_reason_code`) are satisfied by the derivation table above by construction.

## Validation order in `assemble_replay_backtest_summary`

The function performs the following ordered checks. Each step raises `ReplayBacktestRunnerServiceError(code, field=...)`.

1. `replay_run` is an instance of `ReplayBacktestRun`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_replay_backtest_run", field="replay_run")`.
2. `type(steps) is tuple`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_tuple", field="steps")`.
3. For each `i` in `range(len(steps))`: `isinstance(steps[i], ReplayBacktestStep)`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_replay_backtest_step", field=f"steps[{i}]")`.
4. For each `i` in `range(len(steps))`: `steps[i].replay_run_id == replay_run.replay_run_id`. Otherwise raise `ReplayBacktestRunnerServiceError("step_replay_run_id_must_match_replay_run_id", field=f"steps[{i}].replay_run_id")`.
5. `now_ms_clock` is callable. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_callable", field="now_ms_clock")`.
6. Call `now_ms_clock()` exactly once. Bind to `now_ms`.
7. `type(now_ms) is int` (and not `bool`). Otherwise raise `ReplayBacktestRunnerServiceError("must_be_int", field="now_ms_clock")`.
8. `now_ms >= 0`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_nonnegative", field="now_ms_clock")`.
9. `now_ms >= replay_run.run_started_ts_ms`. Otherwise raise `ReplayBacktestRunnerServiceError("must_be_at_or_after_run_started_ts_ms", field="now_ms_clock")`.
10. `len(replay_run.replay_run_id) <= 123`. Otherwise raise `ReplayBacktestRunnerServiceError("replay_run_id_too_long_for_replay_summary_id_derivation", field="replay_run.replay_run_id")`. The 123-character cap keeps the derived `replay_summary_id` within the 128-character cap (5 prefix characters + 123 body characters = 128).

After the validation pipeline passes, the function performs the count aggregation below and returns a frozen `ReplayBacktestSummary`.

## replay_summary_id derivation

`replay_summary_id = "rsum_" + replay_run.replay_run_id`. The derivation is deterministic and pure. The string `"rsum_"` is a five-character literal. The maximum length of `replay_summary_id` is `5 + 123 = 128`, exactly the 2I.A invariant cap.

## Count aggregation (ordered)

After validation, the function computes the eight count fields by a single linear pass over `steps`:

- `total_steps_count = len(steps)`
- `record_allow_steps_count = number of steps with step_action == "step_record_allow"`
- `record_deny_steps_count = number of steps with step_action == "step_record_deny"`
- `mirror_allow_proceed_long_steps_count = number of steps with step_reason_code == "step_mirror_allow_proceed_long"`
- `mirror_allow_proceed_short_steps_count = number of steps with step_reason_code == "step_mirror_allow_proceed_short"`
- `mirror_deny_orchestrator_held_steps_count = number of steps with step_reason_code == "step_mirror_deny_orchestrator_held"`
- `mirror_deny_orchestrator_abstained_steps_count = number of steps with step_reason_code == "step_mirror_deny_orchestrator_abstained"`
- `mirror_deny_default_steps_count = number of steps with step_reason_code == "step_mirror_deny_default"`

The 2I.A `ReplayBacktestSummary.__post_init__` enforces three partition-sum equalities; they hold by construction here because:
- Action partition: every `ReplayBacktestStep` has `step_action ∈ {"step_record_allow", "step_record_deny"}` (2I.A invariant), so `record_allow_steps_count + record_deny_steps_count == total_steps_count`.
- Allow-subreason partition: any step with `step_action == "step_record_allow"` has `step_reason_code ∈ {"step_mirror_allow_proceed_long", "step_mirror_allow_proceed_short"}` (2I.A cross-field invariant), so `mirror_allow_proceed_long_steps_count + mirror_allow_proceed_short_steps_count == record_allow_steps_count`.
- Deny-subreason partition: any step with `step_action == "step_record_deny"` has `step_reason_code ∈ {"step_mirror_deny_orchestrator_held", "step_mirror_deny_orchestrator_abstained", "step_mirror_deny_default"}` (2I.A cross-field invariant), so `mirror_deny_orchestrator_held_steps_count + mirror_deny_orchestrator_abstained_steps_count + mirror_deny_default_steps_count == record_deny_steps_count`.

## ReplayBacktestSummary construction

After aggregation, the function returns:

```
ReplayBacktestSummary(
    replay_summary_id=replay_summary_id,
    replay_run_id=replay_run.replay_run_id,
    summary_emitted_ts_ms=now_ms,
    total_steps_count=total_steps_count,
    record_allow_steps_count=record_allow_steps_count,
    record_deny_steps_count=record_deny_steps_count,
    mirror_allow_proceed_long_steps_count=mirror_allow_proceed_long_steps_count,
    mirror_allow_proceed_short_steps_count=mirror_allow_proceed_short_steps_count,
    mirror_deny_orchestrator_held_steps_count=mirror_deny_orchestrator_held_steps_count,
    mirror_deny_orchestrator_abstained_steps_count=mirror_deny_orchestrator_abstained_steps_count,
    mirror_deny_default_steps_count=mirror_deny_default_steps_count,
    live_blocked=True,
)
```

`live_blocked` is the literal Python boolean `True` at the call site.

## Imports allowed in service.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.paper_execution_ledger import (PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT, PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, PaperExecutionLedgerEntry)`
- `from v2.backend.app.domain.replay_backtest_runner import (STEP_ACTION_RECORD_ALLOW, STEP_ACTION_RECORD_DENY, STEP_REASON_MIRROR_ALLOW_PROCEED_LONG, STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT, STEP_REASON_MIRROR_DENY_DEFAULT, STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED, STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, ReplayBacktestRun, ReplayBacktestStep, ReplayBacktestSummary)`
- `from .errors import ReplayBacktestRunnerServiceError`

No other import is permitted in `service.py`. No `math` import. No `typing` import. No `time`, `datetime`, `logging`, `os`, `subprocess`, `socket`, `pathlib`, `multiprocessing`, `threading`, `asyncio`, `redis*`, `httpx`, `requests`, `fastapi`, `uvicorn`, `starlette`, `urllib`, `urllib3`, `url_env`, factory import. No import of any `v2.backend.app.adapters.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`, `v2.backend.app.main.*`, or any other `v2.backend.app.services.*` sibling. No import of any `v2.backend.app.domain.risk_gateway`, `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, `v2.backend.app.domain.liveness_stream_growth`, `v2.backend.app.domain.replay`, or `v2.backend.app.domain.execution`.

## Imports allowed in __init__.py

- `from .service import assemble_replay_backtest_step, assemble_replay_backtest_summary`
- `from .errors import ReplayBacktestRunnerServiceError`

`__all__` is defined explicitly with the three names in the public-surface order. No other import is permitted in `__init__.py`.

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
- `RiskDecisionRecord`
- `OrchestratorDecisionRecord`
- `sqlite`
- `sqlalchemy`
- `parquet`
- `BEGIN_FILE`
- `END_FILE`

The forbidden-token test file constructs each literal at runtime via string concatenation so the test source file does not contain the bare token. The harness BEGIN/END framing token marker line is also forbidden in any authored file body.

## Behavior contract steps to be cited in the implementation report

The implementation report `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/14_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST cite each of the following 12 behavior contract steps with a one-line evidence pointer to function and line range in `service.py`:

1. `assemble_replay_backtest_step` performs the three up-front instance/callable validation steps BEFORE the clock is invoked.
2. `assemble_replay_backtest_step` invokes the clock exactly once and validates type and non-negativity and the `>= run_started_ts_ms` guard before use.
3. `assemble_replay_backtest_step` enforces `paper_ledger_entry.symbol == replay_run.symbol` BEFORE deriving `replay_step_id`.
4. `assemble_replay_backtest_step` enforces the 122-character cap on `paper_ledger_entry.paper_trade_id` BEFORE `replay_step_id` is derived.
5. `assemble_replay_backtest_step` runs the 5-row mirror derivation table in the documented order and is exhaustive over the 2H.A `_ALLOWED_LEDGER_REASON_CODES` frozenset (any unrecognized reason triggers the defensive fallback).
6. `assemble_replay_backtest_step` constructs `ReplayBacktestStep` with `live_blocked=True` as a literal boolean and propagates `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `ledger_action`, and `ledger_reason_code` without modification.
7. `assemble_replay_backtest_summary` performs the four up-front instance/tuple/element/run-id-match validation steps BEFORE the clock is invoked.
8. `assemble_replay_backtest_summary` invokes the clock exactly once and validates type and non-negativity and the `>= run_started_ts_ms` guard before use.
9. `assemble_replay_backtest_summary` enforces the 123-character cap on `replay_run.replay_run_id` BEFORE `replay_summary_id` is derived.
10. `assemble_replay_backtest_summary` performs a single linear pass over `steps` to compute the eight count fields and returns the frozen `ReplayBacktestSummary` with `live_blocked=True`.
11. The 2I.A summary partition-sum equalities (action, allow-subreason, deny-subreason) hold by construction for every input step tuple consistent with 2I.A invariants.
12. Neither function caches, mutates global state, logs, spawns threads or subprocesses, or interposes any I/O between input validation and value-object return.

## Reports to emit

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/14_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md` (one of the markers documented in `13_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`).

PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC_READY
