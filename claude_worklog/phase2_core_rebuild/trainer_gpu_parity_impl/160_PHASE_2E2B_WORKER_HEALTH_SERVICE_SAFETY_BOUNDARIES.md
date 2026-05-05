# Phase 2E2.B — Worker Health Service Safety Boundaries

## Authored paths in this milestone

- `v2/backend/app/services/trainer_worker_health/__init__.py`
- `v2/backend/app/services/trainer_worker_health/errors.py`
- `v2/backend/app/services/trainer_worker_health/service.py`
- `v2/backend/tests/unit/services/trainer_worker_health/__init__.py`
- 22 test files under
  `v2/backend/tests/unit/services/trainer_worker_health/`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/162_2E2B_WORKER_HEALTH_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/163_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO.md`

## Cross-isolation paths

The implementation task must not write or modify any path under:

- `v2/backend/app/services/__init__.py`
- `v2/backend/app/services/agent_supervisor_reader.py`
- `v2/backend/app/services/audit_writer.py`
- `v2/backend/app/services/discovery_runner.py`
- `v2/backend/app/services/execution_router.py`
- `v2/backend/app/services/feature_assembly.py`
- `v2/backend/app/services/feature_snapshots/`
- `v2/backend/app/services/hot_reload_orchestrator.py`
- `v2/backend/app/services/monitor_runner.py`
- `v2/backend/app/services/orchestrator_decision.py`
- `v2/backend/app/services/paper_loop.py`
- `v2/backend/app/services/prediction_ingest.py`
- `v2/backend/app/services/replay_runner.py`
- `v2/backend/app/services/risk_gateway.py`
- `v2/backend/app/services/selection_runner.py`
- `v2/backend/app/services/signal_publisher.py`
- `v2/backend/app/services/symbol_universe/`
- `v2/backend/app/services/trainer_parity/`
- `v2/backend/app/adapters/`
- `v2/backend/app/composition/`
- `v2/backend/app/domain/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/__init__.py`
- `v2/backend/tests/unit/services/__init__.py`
- `v2/backend/tests/unit/services/trainer_parity/`
- `v2/backend/tests/unit/composition/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- any path under `/home/wali/Desktop/AI BOT`

`git status -s` over these cross-isolation paths must return zero
lines at the end of 2E2.B.

## Forbidden tokens

The three authored source files must not contain any of the
literal tokens listed in
`158_PHASE_2E2B_WORKER_HEALTH_SERVICE_SPEC.md` "Forbidden tokens
in source files". Verified by `rg --fixed-strings --case-sensitive`
for each token.

## Forbidden runtime behavior

The 2E2.B milestone must not:

- read or write any Redis key.
- invoke any Redis command at any layer.
- import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`,
  or `requests`.
- import `v2.backend.app.adapters.redis_v2.url_env`.
- read or set `os.environ`.
- invoke any `subprocess` or `socket`.
- log to stdout, stderr, or the `logging` module.
- call any wall-clock helper such as `time.time`,
  `time.monotonic`, `datetime.now`, or `datetime.utcnow`.
- register any FastAPI lifespan, dependency, or router.
- introduce any module-level singleton, cache, or lock.
- emit any URL, token, key, or credential-shaped string.
- modify `/home/wali/Desktop/AI BOT`.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship anywhere.
- run any production migration.
- approve the live gate.

## Verification checklist for the implementation report

The implementation report `162_2E2B_WORKER_HEALTH_SERVICE_IMPLEMENTATION_REPORT.md`
must include each of the following with command and exit code:

- `.venv/bin/python -m py_compile v2/backend/app/services/trainer_worker_health/__init__.py v2/backend/app/services/trainer_worker_health/errors.py v2/backend/app/services/trainer_worker_health/service.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_worker_health/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_worker_health/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q`
- `git status -s` over the cross-isolation paths above (must show
  zero lines).
- `rg --fixed-strings --case-sensitive <token>` for each forbidden
  token from the spec across the three authored source files (each
  must show zero matches).

## Marker policy

- `163_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO.md` must contain exactly
  one line:
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_PASSED`
  on success, or a single line FAIL marker
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_FAILED`
  on failure.
- Neither file may contain any trailing
  `END_FILE: <path>` literal in its body. Bare `END_FILE` is the
  only emission terminator.

PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_SAFETY_BOUNDARIES_READY
