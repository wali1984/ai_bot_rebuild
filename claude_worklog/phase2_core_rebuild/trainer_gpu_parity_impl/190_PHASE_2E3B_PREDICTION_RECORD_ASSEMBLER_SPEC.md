# Phase 2E3.B — Trainer Prediction Record Assembler Service Spec

This document is the authoring spec for Phase 2E3.B of REQ_0006 ∩
REQ_0017. It is the second sub-phase of the
`TRAINER_PREDICTION_OUTPUT_MVP` milestone. It builds a NEW service
package `v2/backend/app/services/trainer_prediction_output/` whose
only purpose is to expose a pure assembler function
`assemble_prediction_record(...)` that takes pre-validated lineage
inputs plus an injected clock and returns a
`TrainerPredictionRecord` value object authored in Phase 2E3.A.

The package is purely service-surface oriented. It does NOT compute
predictions. It does NOT call a model. It does NOT touch I/O, Redis,
files, or HTTP. Importing the package MUST NOT cause `redis`,
`redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`,
`httpx`, `requests`, `asyncio`, `threading`, or
`v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2E3.A Codex re-review pass:
  `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_PASS`
  at
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/189_2E3A_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_GO_NO_GO.md`.

If this marker is absent, the supervisor MUST NOT dispatch
`113_trainer_parity_2e3b_prediction_record_assembler_implementation`.

## Task numbering note

`178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md` projected the 2E3.B
implementation task as `112` and the 2E3.B Codex review task as
`113`. Task `112` was consumed by the 2E3.A Codex re-review after
the dirty-tree clean cycle. The actual task IDs for 2E3.B are
`113` (implementation) and `114` (Codex review). 178 is a
prior-milestone artifact and is not modified by this milestone.

## Module location decision

The new package is a sibling of the existing
`v2/backend/app/services/trainer_worker_health/` and
`v2/backend/app/services/trainer_parity/` packages. It does NOT
live inside any of those, because the prediction record assembler
is a distinct Stage A trainer output contract per
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`.

No 2E1, 2E2, or 2E3.A file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/services/trainer_prediction_output/__init__.py`
- `v2/backend/app/services/trainer_prediction_output/errors.py`
- `v2/backend/app/services/trainer_prediction_output/service.py`
- `v2/backend/tests/unit/services/trainer_prediction_output/__init__.py`
- 22 sibling test files enumerated in
  `191_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_TEST_PLAN.md`.

The existing `v2/backend/tests/unit/services/__init__.py` package
marker is reused as-is and is NOT re-emitted by this milestone.

## Public surface (exact `__all__`)

`v2/backend/app/services/trainer_prediction_output/__init__.py`
exposes exactly the following names, in this order, in `__all__`:

1. `assemble_prediction_record`
2. `TrainerPredictionOutputServiceError`

No other names are re-exported. The `__init__.py` MUST NOT introduce
any module-level globals beyond the two re-exports.

## TrainerPredictionOutputServiceError

`errors.py` defines:

```
class TrainerPredictionOutputServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "TrainerPredictionOutputServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
```

`errors.py` imports nothing beyond `from __future__ import
annotations`. It MUST NOT import any `v2/` module, `redis`,
`aioredis`, `hiredis`, `redis.asyncio`, the gamma.real factory, or
`url_env`.

## assemble_prediction_record

`service.py` defines a pure function:

```
def assemble_prediction_record(
    *,
    prediction_id: str,
    feature_snapshot_id: str,
    symbol: str,
    model_version: str,
    checkpoint_id: str,
    direction: str,
    confidence_raw: float,
    confidence_calibrated: float,
    worker_id: str,
    worker_health_status: str,
    freshness_flag: str,
    source_freshness_age_ms: int | None,
    top_positive_feature_codes: tuple[str, ...],
    top_negative_feature_codes: tuple[str, ...],
    now_ms_clock: Callable[[], int],
) -> TrainerPredictionRecord
```

All parameters are keyword-only.

Behavior contract, in this exact order:

1. If `now_ms_clock` is not callable, raise
   `TrainerPredictionOutputServiceError("must_be_callable", field="now_ms_clock")`.
2. Call `now_ms_clock()` exactly once and bind the result to
   `now_ms`.
3. If `type(now_ms)` is not exactly `int`, raise
   `TrainerPredictionOutputServiceError("must_be_int", field="now_ms_clock")`.
   Boolean values (where `type(value) is bool`) MUST be rejected by
   this check because `type(True) is not int`.
4. If `now_ms < 0`, raise
   `TrainerPredictionOutputServiceError("must_be_nonnegative", field="now_ms_clock")`.
5. Construct and return
   `TrainerPredictionRecord(prediction_id=prediction_id,
   feature_snapshot_id=feature_snapshot_id, symbol=symbol,
   model_version=model_version, checkpoint_id=checkpoint_id,
   prediction_ts_ms=now_ms, direction=direction,
   confidence_raw=confidence_raw,
   confidence_calibrated=confidence_calibrated,
   worker_id=worker_id, worker_health_status=worker_health_status,
   freshness_flag=freshness_flag,
   source_freshness_age_ms=source_freshness_age_ms,
   top_positive_feature_codes=top_positive_feature_codes,
   top_negative_feature_codes=top_negative_feature_codes)`.

Any `TrainerPredictionDomainError` raised by
`TrainerPredictionRecord.__post_init__` propagates unchanged. The
service does NOT catch, wrap, or rewrap domain errors; consumers
catch the most specific class directly.

The service MUST NOT mutate any caller-supplied input. The clock
MUST be called exactly once per invocation.

## Imports allowed in service.py

- `from __future__ import annotations`
- `from collections.abc import Callable`
- `from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord`
- `from .errors import TrainerPredictionOutputServiceError`

No other import is permitted in `service.py`. No standard-library
import beyond `__future__` and `collections.abc`. No `typing`
import. No `dataclasses` import. No `math` import. No `time`
import. No `datetime` import. No `logging` import. No `os`
import. No `subprocess` import. No `socket` import. No `pathlib`
import. No `multiprocessing` import. No `threading` import. No
`asyncio` import. No `redis*` import. No `httpx` import. No
`requests` import. No `fastapi` import. No `url_env` import. No
factory import. No import of any other `v2/backend/app/`
subpackage.

## Imports allowed in __init__.py

- `from .errors import TrainerPredictionOutputServiceError`
- `from .service import assemble_prediction_record`

No other import is permitted in `__init__.py`.

## Imports allowed in errors.py

- `from __future__ import annotations`

No other import is permitted in `errors.py`.

## Redis-clean invariant

The 2E3.B service MUST preserve the redis-clean import invariant
identical to Phase 2E1.D, 2E2.B, and 2E3.A:

- No direct `redis` import.
- No `redis.asyncio` import.
- No `aioredis` import.
- No `hiredis` import.
- No `httpx` import.
- No `requests` import.
- No `v2.backend.app.adapters.redis_v2.url_env` import.
- No transitive load of `redis`, `url_env`, the gamma.real factory,
  `fastapi`, or `uvicorn` when the service package is imported,
  asserted by sys.modules guard tests.

## Forbidden tokens in source files

The three authored source files (`__init__.py`, `errors.py`,
`service.py`) MUST NOT contain any of the following literal
substrings, verified by `rg --fixed-strings --case-sensitive`:

- `redis`
- `Redis`
- `REDIS`
- `aioredis`
- `hiredis`
- `httpx`
- `requests`
- `url_env`
- `URL_ENV`
- `os.environ`
- `getenv`
- `subprocess`
- `socket`
- `selectors`
- `pathlib`
- `time.time`
- `time.monotonic`
- `time.sleep`
- `datetime.now`
- `datetime.utcnow`
- `datetime`
- `print(`
- `logging.`
- `logging`
- `FastAPI`
- `fastapi`
- `APIRouter`
- `lifespan`
- `Depends`
- `BackgroundTasks`
- `lru_cache`
- `cached_property`
- `threading`
- `multiprocessing`
- `asyncio`
- `eval(`
- `exec(`
- `compile(`
- `pickle`
- `marshal`
- `__import__`
- `importlib`

NO exemption applies. The forbidden-token test file constructs
each literal at runtime via string concatenation so the test file
itself does NOT contain the bare token.

## Module-level invariants

The three authored source files MUST NOT contain any of the
following at module scope:

- A FastAPI startup hook, lifespan handler, dependency, or router
  registration.
- A module-level singleton, cache, or lock.
- A wall-clock helper call (`time.time`, `time.monotonic`,
  `datetime.now`, `datetime.utcnow`).
- A logging call or stdout call.
- An `os.environ` read.
- A `subprocess` invocation or a `socket` use.
- A URL string, a token-shaped string, a key-shaped string, or any
  credential-shaped string.
- A background task or executor.

## Cross-isolation invariants

Phase 2E3.B authors no file under any of the following paths and
modifies no byte of any prior-milestone file:

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

## Hard stops

The 2E3.B milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, or 2E3.A.
- read or write any Redis key.
- invoke any Redis command.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit any credential.
- approve the live gate.
- emit a standalone marker line in any authored file body matching
  the harness BEGIN/END framing tokens.

PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_SPEC_READY
