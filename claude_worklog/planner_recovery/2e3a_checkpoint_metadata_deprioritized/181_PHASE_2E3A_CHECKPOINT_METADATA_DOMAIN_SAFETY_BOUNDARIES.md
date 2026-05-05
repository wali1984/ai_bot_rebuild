# Phase 2E3.A — Checkpoint Metadata Domain Safety Boundaries

This document binds the non-live safety boundaries Phase 2E3.A
must respect. Every boundary applies to both the implementation
task `110` and the Codex review task `111`.

## Hard stops (unconditional FAIL with no autofix path)

- Any modification to `/home/wali/Desktop/AI BOT`.
- Any read or write of any Redis key at any layer at any time.
- Any Redis command issued at import time, build time, or
  unit-test time.
- Any restart of any live service (trainer, trader, orchestrator,
  Redis, VPN, ingestor).
- Any exchange-side action (place order, cancel order, modify
  position).
- Any leverage or margin change.
- Any switch from non-live to live mode.
- Any deploy intent or production migration.
- Any credential-shaped string in the diff (no URL with embedded
  password, no API key, no signed cookie, no PEM block).
- Any modification of any prior-milestone file under
  `v2/backend/app/domain/trainer_liveness/`,
  `v2/backend/app/domain/trainer_liveness_composition/`,
  `v2/backend/app/domain/trainer_liveness_observation_collector/`,
  `v2/backend/app/domain/liveness_stream_growth/`,
  `v2/backend/app/domain/trainer_parity/`,
  `v2/backend/app/domain/trainer_worker_health/`,
  `v2/backend/app/services/trainer_parity/`,
  `v2/backend/app/services/trainer_worker_health/`,
  `v2/backend/app/composition/trainer_parity/`,
  `v2/backend/app/composition/trainer_worker_health/`,
  `v2/backend/app/adapters/`, or any other `v2/backend/app/`
  module outside the
  `v2/backend/app/domain/checkpoint_metadata/` subpackage.
- Any modification of any existing test file under
  `v2/backend/tests/unit/services/`,
  `v2/backend/tests/unit/adapters/`,
  `v2/backend/tests/unit/composition/`,
  `v2/backend/tests/unit/domain/trainer_liveness/`,
  `v2/backend/tests/unit/domain/trainer_liveness_composition/`,
  `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`,
  `v2/backend/tests/unit/domain/liveness_stream_growth/`,
  `v2/backend/tests/unit/domain/trainer_parity/`, or
  `v2/backend/tests/unit/domain/trainer_worker_health/`.
- Any FastAPI startup hook, lifespan handler, dependency, router
  registration, module-level singleton, module-level cache,
  module-level lock, or background task in any of the five
  authored source files.
- Any wall-clock helper call (`time.time`, `time.monotonic`,
  `datetime.now`, `datetime.utcnow`) in any of the five authored
  source files.
- Any logging call (`logging.*`), `print` call, `socket.socket`
  use, `subprocess` invocation, `os.environ` access, `httpx`
  import, or `requests` import in any of the five authored source
  files.
- Any direct `redis` import, `redis.asyncio` import, `aioredis`
  import, or `hiredis` import anywhere in this milestone.
- Any reading of a real legacy checkpoint file in unit tests.
  Tests must construct `CheckpointMetadata` instances inline.

## Cross-isolation paths

The implementation and Codex review tasks MUST run
`git status -s` over the following paths and assert zero lines:

- `v2/backend/app/services/`
- `v2/backend/app/adapters/`
- `v2/backend/app/composition/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/composition/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `v2/backend/app/domain/trainer_liveness/`
- `v2/backend/app/domain/trainer_liveness_composition/`
- `v2/backend/app/domain/trainer_liveness_observation_collector/`
- `v2/backend/app/domain/liveness_stream_growth/`
- `v2/backend/app/domain/trainer_parity/`
- `v2/backend/app/domain/trainer_worker_health/`
- `v2/backend/tests/unit/domain/trainer_liveness/`
- `v2/backend/tests/unit/domain/trainer_liveness_composition/`
- `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`
- `v2/backend/tests/unit/domain/liveness_stream_growth/`
- `v2/backend/tests/unit/domain/trainer_parity/`
- `v2/backend/tests/unit/domain/trainer_worker_health/`

## Forbidden tokens (verified by self-grep)

The implementation task `110` MUST run
`rg --fixed-strings --case-sensitive <token> v2/backend/app/domain/checkpoint_metadata/`
for every literal token enumerated in
`179_PHASE_2E3A_CHECKPOINT_METADATA_DOMAIN_SPEC.md` 'Forbidden
tokens'. Every (file, token) pair MUST report zero matches.

## Codex review boundaries

Codex review (task `111`) MUST NOT modify any source or test file
in this task. Codex review MAY run read-only `pytest`,
`py_compile`, `rg`, and `git status` commands. Concrete blockers
identified by Codex review MUST be enumerated in
`185_2E3A_CHECKPOINT_METADATA_DOMAIN_CODEX_REVIEW.md` and emitted
as a FAIL recommendation. The supervisor will dispatch a separate
REQ_0007 / REQ_0014 autofix task scoped to the five authored
source files plus the 20 new test files only. The autofix task
is not allowed to touch any prior-milestone file.

## Stop conditions for human attention

Surface to human attention (no autofix) on:

- Any hard-stop violation above.
- Any safety review row that is not 'none observed'.
- Any ambiguous strategy or live-trading decision (none expected
  in this milestone — the domain layer is offline-only).
- Any L4 / L5 action.

## Live gate

Final live trading approval remains human-only. Phase 2E3.A
introduces no live behavior. The checkpoint metadata domain is a
pure value-object package and cannot trigger any live action.

PHASE2E3A_TRAINER_CHECKPOINT_METADATA_DOMAIN_SAFETY_READY
