# Phase 2M — Typed Input Fixture Spec

## Fixture module

Path: `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py`.

The fixture module is test-only Python that exposes pure-function builders for the five REQ_0022 outcome variants. It imports only `PaperExecutionLedgerEntry` and the `PAPER_LEDGER_*` constants from `v2.backend.app.domain.paper_execution_ledger`, `ReplayBacktestRun` from `v2.backend.app.domain.replay_backtest_runner`, and standard library types. It does NOT import any service, composition, adapter, API, CLI, jobs, or main module. It does NOT call any wall-clock helper.

## Deterministic identifier convention

For each outcome variant, fixture identifiers follow the pattern:

- `replay_run_id` = `replay_run_lab_hedge_unwind_{outcome_slug}`.
- `replay_step_id` = `replay_step_lab_hedge_unwind_{outcome_slug}_{step_idx_zero_padded_3}` (only used by the `ReplayBacktestStep`; `paper_trade_id` is the carried identifier on the input `PaperExecutionLedgerEntry`).
- `paper_trade_id` = `paper_trade_lab_hedge_unwind_{outcome_slug}_{step_idx_zero_padded_3}`.
- `risk_decision_id` = `risk_decision_lab_hedge_unwind_{outcome_slug}_{step_idx_zero_padded_3}`.
- `decision_id` = `decision_lab_hedge_unwind_{outcome_slug}_{step_idx_zero_padded_3}`.
- `prediction_id` = `prediction_lab_hedge_unwind_{outcome_slug}_{step_idx_zero_padded_3}`.
- `feature_snapshot_id` = `feature_snapshot_lab_hedge_unwind_{outcome_slug}_{step_idx_zero_padded_3}`.

Outcome slugs:

- outcome 1 → `legacy`.
- outcome 2 → `keep_hedge`.
- outcome 3 → `close_short`.
- outcome 4 → `reduce_short`.
- outcome 5 → `block_hedge_close`.

## Deterministic timestamp convention

`run_started_ts_ms` per outcome is `1_700_000_000_000` (a fixed reference point, deterministic, no wall-clock derivation). `run_ended_ts_ms` per outcome is `run_started_ts_ms + 3_000` (three seconds, allowing one second per step). `ledger_entry_ts_ms` per step is `run_started_ts_ms + step_idx_zero_based * 1_000`.

The pytest harness builds `ReplayBacktestRunner` with a deterministic monotonic test clock that starts at `run_started_ts_ms + 10` and advances by `1_000` on each call. The clock implementation is a simple closure over a list-of-one mutable counter; no `time.monotonic`, no `time.time`, no `datetime.now`, no `datetime.utcnow` is invoked.

## Universal fixture invariants

For every `PaperExecutionLedgerEntry`:

- `symbol` = `LABUSDT` (uppercase, no whitespace, length 7).
- `live_blocked = True` (enforced by `PaperExecutionLedgerEntry.__post_init__`; mirrored by `ReplayBacktestStep.__post_init__` and `ReplayBacktestRun.__post_init__`).
- `ledger_action` and `ledger_reason_code` follow the pairing rules in `PaperExecutionLedgerEntry.__post_init__`.
- `input_risk_action` and `input_risk_reason_code` follow the cross-validation rules in `PaperExecutionLedgerEntry.__post_init__`.

For every `ReplayBacktestRun`:

- `run_mode` = `RUN_MODE_REPLAY` for all five outcomes (this is replay-case authoring, not a backtest sweep).
- `live_blocked = True`.
- `symbol` = `LABUSDT`.

## Public fixture API

The fixture module exposes the following public callables. Each is a pure function with no side effects:

- `build_legacy_outcome() -> tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]`.
- `build_keep_hedge_outcome() -> tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]`.
- `build_close_short_outcome() -> tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]`.
- `build_reduce_short_outcome() -> tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]`.
- `build_block_hedge_close_outcome() -> tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]`.
- `build_test_clock(start_ms: int, step_ms: int) -> Callable[[], int]` — returns a deterministic monotonic test clock closure.

The fixture module does NOT export a `now_ms_clock` instance directly; the pytest module instantiates the clock per test via `build_test_clock(...)`.

## Forbidden fixture content

- No `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow` import or call.
- No file I/O (`open`, `Path.read_text`, `Path.write_text`, `pathlib.Path` reads / writes, etc.).
- No network call (`socket`, `requests`, `httpx`, `urllib`, etc.).
- No environment variable read (`os.environ`, `os.getenv`).
- No Redis client import (`redis`, `aioredis`, etc.).
- No CCXT or exchange SDK import.
- No torch / numpy / pandas / scikit-learn import (test fixtures must remain stdlib + V2 domain types only).
- No FastAPI / Starlette / pydantic import.
- No mock / patch / monkeypatch usage in the fixture module itself (the fixture builders are pure constructors; mocking belongs in the pytest module if needed, but at Phase 2M no mock is needed).
- No `print(...)` or logging emission.
- No `paper_trade_id` collision across outcomes (each outcome's identifiers are namespaced by outcome slug to keep the global identifier set unique across the entire test session).

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_FIXTURE_SPEC_READY
