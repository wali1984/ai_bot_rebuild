# Phase 2I.A — Replay/Backtest Runner Domain Safety Boundaries

This document enumerates the safety boundaries Phase 2I.A MUST honor. Any violation triggers a stop with FAILED gate marker and surfaces to the supervisor.

## Live behavior

- MUST NOT enable live trading.
- MUST NOT register a live order route.
- MUST NOT place or cancel an exchange order.
- MUST NOT change leverage or margin.
- MUST NOT construct any `ReplayBacktestRun`, `ReplayBacktestStep`, or `ReplayBacktestSummary` with `live_blocked == False`.
- MUST NOT introduce any code path where `live_blocked` could default to `False`.

## Legacy

- MUST NOT modify `/home/wali/Desktop/AI BOT`.
- MUST NOT read or write any legacy Redis key.
- MUST NOT restart any legacy service.
- MUST NOT introduce any reference to a legacy module path.

## Redis / network

- MUST NOT import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `urllib`, `urllib3`, `socket`, or any HTTP client.
- MUST NOT import `v2.backend.app.adapters.redis_v2.factory`.
- MUST NOT import `v2.backend.app.adapters.redis_v2.url_env`.
- MUST NOT cause any of these modules to enter `sys.modules` when the package is imported.

## FastAPI / process

- MUST NOT import `fastapi`, `uvicorn`, or `starlette`.
- MUST NOT register any FastAPI lifespan, dependency, or router.
- MUST NOT introduce any module-level singleton, cache, or lock.
- MUST NOT call wall-clock helpers (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`) anywhere in the authored source.
- MUST NOT invoke `subprocess`, `os.environ`, or `os.getenv`.
- MUST NOT log via `logging` or stdout.

## Cross-milestone

- MUST NOT modify any prior-milestone source or test file (2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C).
- MUST NOT modify any 2I.A planning artifact at 00, 01, 02, 03, 04, 05.
- MUST NOT modify the master planner prompt.
- MUST NOT modify any task definition under `claude_worklog/agent_supervisor/tasks/`.
- MUST NOT modify the pre-existing placeholder `v2/backend/app/services/paper_loop.py`.
- MUST NOT modify the pre-existing placeholder `v2/backend/app/services/replay_runner.py`.
- MUST NOT modify or populate any file under `v2/backend/app/domain/replay/` (the 015A scaffold).
- MUST NOT modify or populate any file under `v2/backend/app/domain/execution/` (the 015A scaffold).
- MUST NOT modify or populate any file under `v2/backend/app/domain/paper_execution_ledger/` authored in 2H.A.
- MUST NOT create or modify any file under `v2/backend/app/services/`, `v2/backend/app/composition/`, `v2/backend/app/adapters/`, `v2/backend/app/api/`, `v2/backend/app/cli/`, `v2/backend/app/jobs/`, or `v2/frontend/`.
- MUST NOT create or modify any file under `v2/backend/tests/unit/services/`, `v2/backend/tests/unit/composition/`, `v2/backend/tests/unit/adapters/`, `v2/backend/tests/unit/feature_snapshots/`, or `v2/backend/tests/unit/symbol_universe/`.
- MUST NOT modify `v2/backend/tests/unit/__init__.py` or `v2/backend/tests/unit/domain/__init__.py`.

## Scope-cap (REQ_0017 milestone 5)

- MUST NOT add a replay engine, scheduler, or background loop.
- MUST NOT add a paper trader process or paper executor.
- MUST NOT add a shadow executor.
- MUST NOT add a strategy library.
- MUST NOT add PnL computation, position sizing, quantity, price, fees, slippage, or risk-adjusted return calculation.
- MUST NOT add ledger persistence (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis).
- MUST NOT add a service-layer assembler (deferred to 2I.B).
- MUST NOT add a composition-root binder (deferred to 2I.C).
- MUST NOT introduce any new lineage ID at the 2I.A value-object layer beyond `replay_run_id`, `replay_step_id`, and `replay_summary_id` plus the propagated `paper_trade_id` / `risk_decision_id` / `decision_id` / `prediction_id` / `feature_snapshot_id` chain.
- MUST NOT import `v2.backend.app.domain.paper_execution_ledger` at the value-object layer.
- MUST NOT import `v2.backend.app.domain.risk_gateway` at the value-object layer.
- MUST NOT import `v2.backend.app.domain.orchestrator_decision` at the value-object layer.
- MUST NOT import `v2.backend.app.domain.trainer_prediction_output` at the value-object layer.

## Forbidden runtime behaviors (each verified in 06 implementation report)

- redis import — MUST be "none observed"
- aioredis / hiredis / redis.asyncio import — MUST be "none observed"
- httpx / requests / urllib import — MUST be "none observed"
- fastapi / uvicorn / starlette import — MUST be "none observed"
- subprocess invocation outside permitted import-isolation test files — MUST be "none observed"
- socket import — MUST be "none observed"
- os.environ / os.getenv read — MUST be "none observed"
- wall-clock helper invocation in any authored 2I.A source file — MUST be "none observed"
- module-level singleton, cache, or lock — MUST be "none observed"
- logging or stdout emission — MUST be "none observed"
- URL, token, key, or credential-shaped string emission — MUST be "none observed"
- construction of `ReplayBacktestRun` / `ReplayBacktestStep` / `ReplayBacktestSummary` with `live_blocked == False` — MUST be "none observed"
- import of `v2.backend.app.domain.paper_execution_ledger` — MUST be "none observed"
- emission of token `PaperExecutionLedgerEntry` in any authored 2I.A source file — MUST be "none observed"
- emission of token `RiskDecisionRecord` or `OrchestratorDecisionRecord` in any authored 2I.A source file — MUST be "none observed"
- modification of `v2/backend/app/domain/replay/`, `v2/backend/app/domain/execution/`, or `v2/backend/app/services/replay_runner.py` — MUST be "none observed"
- modification of any pre-existing prior-milestone artifact — MUST be "none observed"

## Stop conditions

The implementing agent MUST stop and write the FAILED marker if any of the above is observed. Autofix is NOT permitted in this task; the supervisor will dispatch a separate REQ_0007 / REQ_0014 autofix task scoped to the five authored source files plus the 51 new test files only.

PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SAFETY_BOUNDARIES_READY
