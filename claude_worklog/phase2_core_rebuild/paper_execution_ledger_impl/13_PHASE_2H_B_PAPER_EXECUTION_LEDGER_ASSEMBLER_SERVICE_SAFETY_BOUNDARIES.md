# Phase 2H.B — Paper Execution Ledger Assembler Service Safety Boundaries

## Hard non-live boundaries

The 2H.B implementation MUST NOT:

- modify any file under `/home/wali/Desktop/AI BOT`.
- read or write any Redis key.
- invoke any Redis command.
- import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `starlette`.
- import `v2.backend.app.adapters.redis_v2.factory`.
- import `v2.backend.app.adapters.redis_v2.url_env`.
- import `v2.backend.app.composition` anywhere.
- import any other `v2.backend.app.services` sibling package (the new `paper_execution_ledger` package may not import `risk_gateway`, `orchestrator_decision`, `trainer_prediction_output`, `trainer_worker_health`, `trainer_parity`, `feature_snapshots`, `symbol_universe`, or any other sibling).
- import `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`.
- import `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, or `v2.backend.app.domain.liveness_stream_growth`.
- read `os.environ` or `os.getenv`.
- invoke `subprocess` outside the three permitted import-isolation test files (`test_assembler_service_does_not_import_redis.py`, `test_assembler_service_does_not_import_url_env.py`, `test_assembler_service_does_not_register_fastapi_lifespan.py`).
- invoke `socket`.
- call wall-clock helpers (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`) in any authored 2H.B source file.
- register a FastAPI lifespan, dependency, or router.
- introduce a module-level singleton, cache, or lock.
- log via `logging` or `print(`.
- emit URL, token, key, or credential-shaped strings.
- modify any prior-milestone artifact byte content.
- modify any 2H.A authored source or test file under `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/tests/unit/domain/paper_execution_ledger/`.
- modify any 2G.A, 2G.B, 2G.C, 2F.A, 2F.B, 2F.C, 2E1, 2E2, or 2E3 source or test file.
- modify the master planner prompt.
- modify any task definition under `claude_worklog/agent_supervisor/tasks/`.
- modify the planner-emitted 00–10 docs at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`.
- modify the planner-emitted 11–14 docs at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` (this 13 doc and its 11/12/14 siblings).
- restart any live service.
- place or cancel exchange orders.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run a migration in any environment.
- approve the live gate.
- emit a standalone harness `BEGIN_FILE` or `END_FILE` framing token marker line in any authored file body.
- create `v2/backend/app/services/paper_execution_ledger.py` as a single file (the package directory is the only allowed shape).
- introduce or compute PnL, position sizing, quantity, price, fees, or slippage in any authored file.
- introduce ledger persistence (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis) in any authored file.
- introduce a paper executor, shadow executor, replay runner, or paper trader process in any authored file.

## Cross-isolation paths (zero `git status -s` lines outside scope)

After 2H.B closes, `git status -s` over the dispatch worktree MUST show only paths under:

- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/tests/unit/services/paper_execution_ledger/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md`

Any other path appearing in `git status -s` is a scope violation that triggers a FAILED 16 marker and prevents Codex review dispatch.

## Forbidden runtime behaviors

The implementation report `15` MUST list each of the following forbidden runtime behaviors with `none observed` or `observed: <evidence>`:

1. Redis access at any layer.
2. URL or credential leakage in any authored file.
3. FastAPI lifespan, dependency, or router registration.
4. Module-level singleton, cache, or lock.
5. Wall-clock helper invocation in any authored source file.
6. `os.environ` or `os.getenv` read.
7. `subprocess` invocation in any authored source file.
8. `socket` invocation in any authored source file.
9. Logging or stdout output.
10. Live service restart.
11. Exchange action.
12. Leverage or margin change.
13. Production migration.
14. Deployment.
15. Final live gate approval.
16. PnL, position sizing, quantity, price, fees, or slippage computation.
17. Ledger persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis).
18. Paper executor, shadow executor, replay runner, or paper trader process.
19. Reserved deny_default branch silently dropped (the assembler must emit `mirror_deny_default` for `deny_default` input; the regression test enforces this).

## Stop conditions

If any of the following is true, write `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED` to `16` and stop without autofix:

- Any forbidden runtime behavior is observed.
- Any forbidden import is observed.
- Any forbidden token is observed in `__init__.py`, `errors.py`, or `service.py`.
- Any cross-isolation path appears in `git status -s` outside the documented scope.
- The 2H.A predecessor marker `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` is missing or different.
- Any pytest suite returns a non-zero exit code.
- Any `py_compile` returns a non-zero exit code.
- Any test asserts the assembler emits a value that violates a 2H.A cross-field invariant.

PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES_READY
