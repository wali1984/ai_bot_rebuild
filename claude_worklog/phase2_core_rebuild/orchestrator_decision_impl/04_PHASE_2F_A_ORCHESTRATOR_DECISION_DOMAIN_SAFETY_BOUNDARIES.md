# Phase 2F.A — Orchestrator Decision Domain Safety Boundaries

This document enumerates hard safety invariants for Phase 2F.A. Codex review at task `118` MUST verify each invariant explicitly and cite evidence for each PASS row.

## Forbidden runtime behaviors (in any authored 2F.A source file)

- No `redis`, `redis.asyncio`, `aioredis`, `hiredis` import.
- No `httpx`, `requests` import.
- No `fastapi`, `uvicorn` import.
- No `asyncio`, `threading`, `multiprocessing` import.
- No `subprocess` invocation outside the single permitted test file (`test_orchestrator_decision_domain_does_not_import_redis.py`).
- No `socket` import.
- No `os.environ`, `os.getenv` access.
- No wall-clock helper call: `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`.
- No `logging` import. No `print(` invocation.
- No `url_env` import. No `gamma.real` factory import. No import of `v2.backend.app.adapters.*`, `v2.backend.app.services.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`.
- No URL, token, key, or credential-shaped string literal.
- No FastAPI lifespan, dependency, or router registration.
- No module-level singleton, cache, or lock.
- No mutation of any prior-milestone source or test file.
- No mutation of any task definition under `claude_worklog/agent_supervisor/tasks/`.
- No mutation of the master planner prompt.
- No standalone harness BEGIN_FILE / END_FILE marker line in any authored file body.

## Cross-isolation paths (must show zero git diff after authoring)

Codex review MUST run `git status -s` over the following paths and assert zero output lines:

- `v2/backend/app/composition/`
- `v2/backend/app/services/`
- `v2/backend/app/adapters/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/backend/app/domain/decisions/`
- `v2/backend/app/domain/trainer_liveness/`
- `v2/backend/app/domain/trainer_liveness_composition/`
- `v2/backend/app/domain/trainer_liveness_observation_collector/`
- `v2/backend/app/domain/trainer_parity/`
- `v2/backend/app/domain/trainer_worker_health/`
- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/domain/liveness_stream_growth/`
- `v2/backend/app/domain/connectors/`
- `v2/backend/app/domain/execution/`
- `v2/backend/app/domain/features/`
- `v2/backend/app/domain/governance/`
- `v2/backend/app/domain/hot_reload/`
- `v2/backend/app/domain/lineage/`
- `v2/backend/app/domain/monitor/`
- `v2/backend/app/domain/predictions/`
- `v2/backend/app/domain/replay/`
- `v2/backend/app/domain/risk/`
- `v2/backend/app/domain/signals/`
- `v2/backend/app/domain/symbols/`
- `v2/backend/app/domain/traders/`
- `v2/backend/app/domain/universe/`
- `v2/frontend/`
- `v2/backend/tests/unit/composition/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `v2/backend/tests/unit/domain/trainer_liveness/`
- `v2/backend/tests/unit/domain/trainer_liveness_composition/`
- `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`
- `v2/backend/tests/unit/domain/trainer_parity/`
- `v2/backend/tests/unit/domain/trainer_worker_health/`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/domain/liveness_stream_growth/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

## Hard safety stops

Stop and write the FAILED marker (no autofix in this task) on any of the following:

- Any live behavior, any Redis access at any layer, any Redis command at any time.
- Any legacy mutation, any release intent in any environment.
- Any modification of any prior-milestone source or test file.
- Any FastAPI lifespan or router or singleton or cache or wall-clock helper or `os.environ` or subprocess (outside the single permitted test file) or socket in any authored 2F.A source file.
- Any direct `redis`, `url_env`, or factory import in any authored 2F.A source file.
- Any URL or credential leakage.
- Any REQ_0017 scope-cap violation (no orchestrator service, no risk gateway, no execution surface, no FastAPI surface, no adapter expansion, no decision derivation logic at the value-object layer).

## Live gate

The live gate remains blocked. The 2F.A domain enforces `live_blocked is True` at construction time so any consumer constructing a record with `live_blocked == False` fails closed before the record is referenced anywhere downstream.

PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_SAFETY_BOUNDARIES_READY
