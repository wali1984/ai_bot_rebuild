# Phase 2E3.A — Trainer Prediction Output Domain Safety Boundaries

This document enumerates the cross-isolation guarantees for Phase
2E3.A of REQ_0006 ∩ REQ_0017. The implementation task `110` and the
Codex review task `111` both enforce these boundaries.

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
- No standalone `END_FILE` or `END_FILE_SENTINEL` marker leakage in
  any authored file.

## REQ_0017 scope cap

Phase 2E3.A MUST stay inside the
`TRAINER_PREDICTION_OUTPUT_MVP` envelope:

- No checkpoint runner subdomain.
- No GPU runner subdomain.
- No model-loading subsystem.
- No FastAPI route, lifespan, dependency, or startup handler.
- No service composition.
- No adapter (Redis-backed or otherwise).
- No composition root.
- No background task, no module-level singleton, no module-level
  cache, no module-level lock.

## Allowed paths to write (`110` only)

Implementation task `110` is allowed to write only inside these
prefixes:

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

Codex review task `111` is allowed to write only inside this prefix:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

## Forbidden output paths (cross-isolation)

The following paths MUST NOT be written, modified, or deleted by
`110` or `111`:

- `v2/backend/app/domain/__init__.py`
- `v2/backend/app/domain/trainer_liveness/`
- `v2/backend/app/domain/trainer_worker_health/`
- `v2/backend/app/domain/trainer_parity/`
- `v2/backend/app/services/`
- `v2/backend/app/composition/`
- `v2/backend/app/adapters/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/__init__.py`
- `v2/backend/tests/unit/domain/__init__.py`
- `v2/backend/tests/unit/domain/trainer_liveness/`
- `v2/backend/tests/unit/domain/trainer_worker_health/`
- `v2/backend/tests/unit/domain/trainer_parity/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/composition/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `legacy_reference/`

## Forbidden actions

`110` and `111` MUST NOT:

- modify `/home/wali/Desktop/AI BOT`
- read or write any Redis key
- invoke any Redis command
- import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`,
  `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`,
  `multiprocessing`, `subprocess` (in source files; the import-graph
  test is allowed to invoke `subprocess` from the TEST file only),
  `socket`, `selectors`, `pathlib`, `logging`
- import `v2.backend.app.adapters.redis_v2.factory`
- import `v2.backend.app.adapters.redis_v2.url_env`
- register any FastAPI startup hook, lifespan handler, dependency,
  router, or background task
- create any module-level singleton, cache, lock, or executor
- invoke any wall-clock helper (`time.time`, `time.monotonic`,
  `datetime.now`, etc.) in source files
- call `print(...)`, `logging.*`, or any I/O in source files
- modify any prior-milestone source, test, or validation file

## Import boundaries (source files)

The three authored source files have a strict import allowlist
enumerated in spec §"Import boundaries". `__init__.py` imports only
from `.errors` and `.record`. `errors.py` imports only
`from __future__ import annotations`. `record.py` imports only
`from __future__ import annotations`, `import math`, `from dataclasses
import dataclass`, and `from .errors import
TrainerPredictionDomainError`.

## Stop conditions

Any of the following triggers an immediate FAIL with no autofix path
and surfaces to human attention:

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
- secret leakage in the diff
- standalone `END_FILE` or `END_FILE_SENTINEL` marker line in any
  authored file body

PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_SAFETY_BOUNDARIES_READY
