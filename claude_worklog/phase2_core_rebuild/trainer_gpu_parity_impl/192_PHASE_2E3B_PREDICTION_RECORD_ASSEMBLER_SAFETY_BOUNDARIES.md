# Phase 2E3.B — Trainer Prediction Record Assembler Safety Boundaries

This document enumerates the cross-isolation guarantees for Phase
2E3.B of REQ_0006 ∩ REQ_0017. The implementation task `113` and
the Codex review task `114` both enforce these boundaries.

## Hard non-live boundaries (project-wide)

- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis read or write at any layer.
- No Redis command of any kind.
- No live service restart.
- No order placement or cancellation.
- No leverage or margin change.
- No live trading enablement.
- No shipping anywhere.
- No migration in any environment.
- No credential exposure.
- No live-gate approval.
- No standalone harness BEGIN/END framing token leakage in any
  authored file body.

## REQ_0017 scope cap

Phase 2E3.B MUST stay inside the
`TRAINER_PREDICTION_OUTPUT_MVP` envelope:

- No checkpoint runner subdomain.
- No GPU runner subdomain.
- No model-loading subsystem.
- No FastAPI route, lifespan, dependency, or startup handler.
- No composition root.
- No adapter (Redis-backed or otherwise).
- No background task, no module-level singleton, no module-level
  cache, no module-level lock.
- No expansion of the assembler beyond the 14 lineage inputs plus
  the injected clock declared in spec §"assemble_prediction_record".

## Allowed paths to write (`113` only)

Implementation task `113` is allowed to write only inside these
prefixes:

- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/tests/unit/services/trainer_prediction_output/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

Codex review task `114` is allowed to write only inside this
prefix:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

## Forbidden output paths (cross-isolation)

The following paths MUST NOT be written, modified, or deleted by
`113` or `114`:

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
- `v2/backend/app/services/trainer_worker_health/`
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
- `v2/backend/tests/unit/services/trainer_worker_health/`
- `v2/backend/tests/unit/composition/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `legacy_reference/`

## Forbidden actions

`113` and `114` MUST NOT:

- modify `/home/wali/Desktop/AI BOT`
- read or write any Redis key
- invoke any Redis command
- import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`,
  `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`,
  `multiprocessing`, `subprocess` (in source files; the
  import-graph tests are allowed to invoke `subprocess` from the
  TEST file only), `socket`, `selectors`, `pathlib`, `logging`,
  `datetime`, `os`, `time` in any authored source file
- import `v2.backend.app.adapters.redis_v2.factory`
- import `v2.backend.app.adapters.redis_v2.url_env`
- import `v2.backend.app.domain.trainer_worker_health` in any
  authored source file
- import `v2.backend.app.domain.trainer_liveness` in any authored
  source file
- import `v2.backend.app.domain.trainer_parity` in any authored
  source file
- import any other `v2/backend/app/services/` sibling subpackage
  in any authored source file
- register any FastAPI startup hook, lifespan handler, dependency,
  router, or background task
- create any module-level singleton, cache, lock, or executor
- invoke any wall-clock helper (`time.time`, `time.monotonic`,
  `datetime.now`, etc.) in source files
- call `print(...)`, `logging.*`, or any I/O in source files
- modify any prior-milestone source, test, or validation file

## Import boundaries (source files)

The three authored source files have a strict import allowlist
enumerated in spec §"Imports allowed in __init__.py", §"Imports
allowed in errors.py", and §"Imports allowed in service.py".

`__init__.py` imports only from `.errors` and `.service`.

`errors.py` imports only `from __future__ import annotations`.

`service.py` imports only `from __future__ import annotations`,
`from collections.abc import Callable`, `from
v2.backend.app.domain.trainer_prediction_output import
TrainerPredictionRecord`, and `from .errors import
TrainerPredictionOutputServiceError`.

## Stop conditions

Any of the following triggers an immediate FAIL with no autofix
path and surfaces to human attention:

- live behavior of any kind
- Redis access at construction or import time
- legacy mutation
- release intent
- modification of any prior-milestone file
- FastAPI startup hook / lifespan registration
- module-level singleton or cache
- wall-clock helper call in source files
- direct `redis` import
- direct `url_env` import
- direct gamma.real factory import
- direct `trainer_worker_health` import in any source file
- direct `trainer_liveness` import in any source file
- direct `trainer_parity` import in any source file
- secret leakage in the diff
- standalone harness BEGIN/END framing token leakage in any
  authored file body
- expansion of the assembler beyond the 14 lineage inputs plus
  the injected clock

PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_SAFETY_BOUNDARIES_READY
