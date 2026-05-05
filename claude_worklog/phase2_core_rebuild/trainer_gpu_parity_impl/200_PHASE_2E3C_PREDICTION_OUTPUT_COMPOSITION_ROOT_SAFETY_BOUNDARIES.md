# Phase 2E3.C — Trainer Prediction Output Composition Root Safety Boundaries

This document is the safety-boundary contract for Phase 2E3.C. It binds the implementation task `115_trainer_parity_2e3c_prediction_output_composition_root_implementation` and the Codex review task `116_trainer_parity_2e3c_prediction_output_composition_root_codex_review`.

## Hard non-live boundaries

The 2E3.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT` in any way.
- read or write any Redis key at any layer (no `redis` import, no `redis.asyncio` import, no `aioredis` import, no `hiredis` import, no Redis command issued from any process spawned during the milestone).
- restart any live service (no `systemctl`, no `supervisorctl`, no PID-9 send).
- place or cancel any exchange order. Change leverage. Change margin. Enable live trading.
- ship to anywhere. Run any production migration.
- expose or commit any credential. The diff MUST contain no canonical secret-shaped string.
- approve the live gate. The live gate remains blocked.

## Authored-file-only modification

The 2E3.C implementation task MUST modify only the files listed in `required_output_files` of the 115 task definition. No prior-milestone byte content is modified. No 2E1, 2E2, or 2E3.A/2E3.B authored file is touched. No master planner prompt edit. No supervisor task edit. No requirements inbox edit.

## Cross-isolation paths (zero-line `git status -s` invariant)

After implementation, `git status -s` over the following paths MUST return zero lines:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/services/`
- `v2/backend/app/adapters/`
- `v2/backend/app/domain/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/__init__.py`
- `v2/backend/tests/unit/composition/__init__.py`
- `v2/backend/tests/unit/composition/trainer_parity/`
- `v2/backend/tests/unit/composition/trainer_worker_health/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`

## Redis-clean import invariant

When `v2.backend.app.composition.trainer_prediction_output` is imported in a fresh interpreter:

- No key starting with `red` + `is` enters `sys.modules`.
- No key containing `url` + `_env` enters `sys.modules`.
- No key starting with `fast` + `api` enters `sys.modules`.
- No `httpx`, `requests`, `aioredis`, `hiredis`, `asyncio`, `threading`, or `multiprocessing` key enters `sys.modules`.

## Forbidden module-scope behavior

The three authored source files (`__init__.py`, `errors.py`, `runtime.py`) MUST NOT execute any of the following at import time:

- A FastAPI lifespan, dependency, or router registration.
- A module-level singleton, cache, or lock construction.
- A wall-clock helper call (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`).
- A `_now_ms_clock` invocation.
- An assembler service invocation.
- A logging call or `print` call.
- An `os.environ` read.
- A `subprocess` invocation.
- A `socket` use.
- A URL-shaped, token-shaped, key-shaped, or credential-shaped string materialization.
- A background task or executor instantiation.

## Forbidden runtime behavior at evaluator-call time

The evaluator returned by `build_trainer_prediction_output_evaluator(...)` MUST NOT:

- mutate any caller-supplied input.
- log via `logging` or `print`.
- access `os.environ`.
- import any new module dynamically (`importlib`, `__import__`).
- call any wall-clock helper directly. The clock is invoked exactly once per call by the underlying assembler service, not by the evaluator.
- catch, wrap, or re-raise `TrainerPredictionOutputServiceError` or `TrainerPredictionDomainError`.

## Standalone harness framing token marker line

Every authored file under `v2/backend/app/composition/trainer_prediction_output/`, every authored test file under `v2/backend/tests/unit/composition/trainer_prediction_output/`, and the implementation report and GO/NO-GO files MUST NOT contain any standalone harness BEGIN/END framing token marker line in their bodies.

## Codex review constraints

The Codex review task 116 is read-only with respect to V2 source and test code. It MUST NOT modify any V2 source or test file. It MUST NOT modify any prior-milestone artifact. It MUST NOT modify the master planner prompt. It MUST NOT modify the supervisor task definitions. It writes only the Codex review report (204) and the Codex GO/NO-GO file (205) under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`.

## Stop conditions (any of these is an unconditional FAIL)

- Any live behavior.
- Any Redis access at any layer.
- Any Redis command at any time.
- Any legacy mutation under `/home/wali/Desktop/AI BOT`.
- Any release intent in any environment.
- Any modification of any prior-milestone source or test file.
- Any FastAPI startup hook, lifespan handler, dependency, or router registration in any authored 2E3.C file.
- Any module-level singleton, cache, or lock in any authored 2E3.C source file.
- Any wall-clock helper call in any authored 2E3.C source file.
- Any direct `redis`, `url_env`, or factory import in any authored 2E3.C source file.
- Any URL or credential leakage in the 2E3.C diff.
- Any REQ_0017 scope-cap violation: a checkpoint runner, a GPU runner, a model-loading subsystem, a FastAPI surface in 2E3.C, an adapter expansion in 2E3.C, or an evaluator parameter expansion beyond the 14 lineage inputs that the 2E3.B service already accepts.
- Any standalone harness BEGIN/END framing token marker line in any authored file body.

PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
