# Phase 2E3.A — Checkpoint Metadata Domain Spec

This document is the authoring spec for Phase 2E3.A of REQ_0006.
It is the first sub-phase of the trainer GPU/checkpoint runner
milestone group. It builds a NEW domain package
`v2/backend/app/domain/checkpoint_metadata/` that encodes the
V2-side checkpoint observation contract bound by
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md`
into a frozen value object plus an explicit standalone validator
entry point. The domain package is import-isolated: it does not
import from any prior 2E1 / 2E2 V2 module, the redis adapter, the
url_env, the subprocess adapter, the audit emitter, or any
service / composition module.

## Predecessor gates

- 2E1.E composition root post-autofix Codex re-review:
  `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`
  (`trainer_gpu_parity_impl/139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`).
- 2E2.A worker health domain Codex PASS:
  `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS`
  (`trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md`).
- 2E2.B worker health service post-autofix Codex re-review:
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS`
  (`trainer_gpu_parity_impl/169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`).
- 2E2.C worker health composition Codex PASS:
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS`
  (`trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent or different, the supervisor
MUST NOT dispatch 2E3.A. The implementation task `110` encodes the
2E2.C Codex pass as its primary additional marker.

## Module location decision

Checkpoint metadata domain files land under a NEW package:

- `v2/backend/app/domain/checkpoint_metadata/__init__.py`
- `v2/backend/app/domain/checkpoint_metadata/errors.py`
- `v2/backend/app/domain/checkpoint_metadata/promotion_status.py`
- `v2/backend/app/domain/checkpoint_metadata/checkpoint_metadata.py`
- `v2/backend/app/domain/checkpoint_metadata/checkpoint_validators.py`

The new package is a sibling of the existing
`v2/backend/app/domain/trainer_liveness/`,
`v2/backend/app/domain/trainer_worker_health/`, and
`v2/backend/app/domain/trainer_parity/` packages. It does NOT live
inside any of those because the checkpoint contract is a distinct
record shape with its own status enumeration, dataclass, and
validator. The new package imports nothing from `v2/`.

No 2E1 file is modified by this milestone. No 2E2 file is modified
by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/checkpoint_metadata/__init__.py`
- `v2/backend/app/domain/checkpoint_metadata/errors.py`
- `v2/backend/app/domain/checkpoint_metadata/promotion_status.py`
- `v2/backend/app/domain/checkpoint_metadata/checkpoint_metadata.py`
- `v2/backend/app/domain/checkpoint_metadata/checkpoint_validators.py`
- `v2/backend/tests/unit/domain/checkpoint_metadata/__init__.py`
- `v2/backend/tests/unit/domain/checkpoint_metadata/` 20 test
  files enumerated in
  `180_PHASE_2E3A_CHECKPOINT_METADATA_DOMAIN_TEST_PLAN.md`.

## Public surface (exact `__all__`)

`v2/backend/app/domain/checkpoint_metadata/__init__.py` exposes
exactly the following names, in this order, in `__all__`:

1. `CheckpointMetadataDomainError`
2. `CheckpointMetadata`
3. `validate_checkpoint_metadata`
4. `PROMOTION_STATUS_NOT_PROMOTED`
5. `PROMOTION_STATUS_PROMOTED`
6. `PROMOTION_STATUS_UNKNOWN`

The module performs no side effects beyond imports. No
module-level singletons. No module-level cache. No module-level
lock. No background task. No FastAPI startup hook, lifespan
handler, dependency, or router registration.

## CheckpointMetadataDomainError

`errors.py` defines:

```
class CheckpointMetadataDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

Imports only the standard library (`from __future__ import
annotations` only). Imports nothing from `v2/`. Imports nothing
from `redis`, `aioredis`, `hiredis`, or `redis.asyncio`.

## Promotion status constants

`promotion_status.py` defines exactly three status string
constants with exact string values:

- `PROMOTION_STATUS_NOT_PROMOTED = "NOT_PROMOTED"`
- `PROMOTION_STATUS_PROMOTED = "PROMOTED"`
- `PROMOTION_STATUS_UNKNOWN = "UNKNOWN"`

The module also defines one frozenset module-level constant used
by the dataclass invariant check:

- `_ALLOWED_PROMOTION_STATUSES = frozenset({PROMOTION_STATUS_NOT_PROMOTED, PROMOTION_STATUS_PROMOTED, PROMOTION_STATUS_UNKNOWN})`

The frozenset is module-private (leading underscore). It is
imported by `checkpoint_metadata.py`.

`promotion_status.py` imports only the standard library
(`from __future__ import annotations` only). Imports nothing from
`v2/`. Imports nothing from `redis`, `aioredis`, `hiredis`, or
`redis.asyncio`.

## CheckpointMetadata

`checkpoint_metadata.py` defines:

```
@dataclass(frozen=True, slots=True)
class CheckpointMetadata:
    checkpoint_id: str
    model_version: str
    created_ts_ms: int
    promotion_status: str
    promotion_ts_ms: int | None
    legacy_checkpoint_path: str
    legacy_metadata_hash: str
```

Invariants enforced in `__post_init__` via
`CheckpointMetadataDomainError`. The checks fire in this exact
order so the first violation is the one reported:

- `checkpoint_id` MUST be a `str`. Otherwise `field="checkpoint_id"`,
  `reason="must_be_str"`.
- `checkpoint_id` MUST be non-empty. Otherwise
  `field="checkpoint_id"`, `reason="must_be_non_empty"`.
- `model_version` MUST be a `str`. Otherwise
  `field="model_version"`, `reason="must_be_str"`.
- `model_version` MUST be non-empty. Otherwise
  `field="model_version"`, `reason="must_be_non_empty"`.
- `type(created_ts_ms) is int` (reject `bool`). Otherwise
  `field="created_ts_ms"`, `reason="must_be_int"`.
- `created_ts_ms >= 0`. Otherwise `field="created_ts_ms"`,
  `reason="must_be_non_negative"`.
- `promotion_status` MUST be in `_ALLOWED_PROMOTION_STATUSES`.
  Otherwise `field="promotion_status"`,
  `reason="invalid_promotion_status"`.
- `legacy_checkpoint_path` MUST be a `str`. Otherwise
  `field="legacy_checkpoint_path"`, `reason="must_be_str"`.
- `legacy_checkpoint_path` MUST be non-empty. Otherwise
  `field="legacy_checkpoint_path"`, `reason="must_be_non_empty"`.
- `legacy_checkpoint_path` MUST start with `"/"` (POSIX
  absolute). Otherwise `field="legacy_checkpoint_path"`,
  `reason="must_be_absolute"`.
- `legacy_metadata_hash` MUST be a `str`. Otherwise
  `field="legacy_metadata_hash"`, `reason="must_be_str"`.
- `legacy_metadata_hash` length MUST equal 64. Otherwise
  `field="legacy_metadata_hash"`, `reason="must_be_64_chars"`.
- `legacy_metadata_hash` MUST consist exclusively of lowercase
  hexadecimal digits (`0-9` and `a-f`). Verified by checking that
  every character is in the module-private string constant
  `"0123456789abcdef"`. Otherwise
  `field="legacy_metadata_hash"`, `reason="must_be_lowercase_hex"`.
- If `promotion_status == PROMOTION_STATUS_PROMOTED`,
  `promotion_ts_ms` MUST NOT be `None`. Otherwise
  `field="promotion_ts_ms"`,
  `reason="promoted_requires_promotion_ts"`.
- If `promotion_status == PROMOTION_STATUS_NOT_PROMOTED`,
  `promotion_ts_ms` MUST be `None`. Otherwise
  `field="promotion_ts_ms"`,
  `reason="not_promoted_requires_no_promotion_ts"`.
- If `promotion_status == PROMOTION_STATUS_UNKNOWN`,
  `promotion_ts_ms` MUST be `None`. Otherwise
  `field="promotion_ts_ms"`,
  `reason="unknown_requires_no_promotion_ts"`.
- If `promotion_ts_ms` is not `None`,
  `type(promotion_ts_ms) is int` (reject `bool`). Otherwise
  `field="promotion_ts_ms"`, `reason="must_be_int"`.
- If `promotion_ts_ms` is not `None`, `promotion_ts_ms >= 0`.
  Otherwise `field="promotion_ts_ms"`,
  `reason="must_be_non_negative"`.

Imports: standard library only (`from __future__ import
annotations`, `from dataclasses import dataclass`); the in-package
`errors.py` and `promotion_status.py` modules. Imports nothing
else.

## validate_checkpoint_metadata

`checkpoint_validators.py` defines:

```
def validate_checkpoint_metadata(
    metadata: CheckpointMetadata,
) -> CheckpointMetadata:
    ...
```

Behavior contract — implement in this exact order:

1. Validate `metadata` is a `CheckpointMetadata` instance.
   Otherwise raise `CheckpointMetadataDomainError("must_be_checkpoint_metadata", field="metadata")`.
2. Re-run the dataclass invariants by constructing a new
   `CheckpointMetadata` from the supplied instance's fields. The
   re-construction is the validation: any
   `CheckpointMetadataDomainError` raised by `__post_init__`
   propagates unchanged.
3. Return the supplied `metadata` (identity-preserving). The
   function MUST NOT return a freshly constructed copy; the
   identity of the input is preserved when validation passes.

The validator does NOT log, print, mutate inputs, install
singletons, register lifespan hooks, call wall-clock helpers,
open sockets, run subprocesses, read `os.environ`, or import the
redis adapter, the url_env, or any other adapter / service /
composition module.

Imports: standard library only (`from __future__ import
annotations`); the in-package `checkpoint_metadata.py` module.
Imports nothing else.

## Forbidden tokens

The forbidden-token guard tests
(`test_checkpoint_metadata_domain_does_not_import_redis.py` and
`test_checkpoint_metadata_domain_does_not_import_url_env.py`)
MUST scan the five authored source files. The following literals
are forbidden absolutely (zero matches in any source file in this
milestone):

- `import redis`
- `from redis`
- `redis.asyncio`
- `hiredis`
- `aioredis`
- `xrevrange`
- `xadd`
- `xread`
- `xlen`
- `pipeline`
- `from v2.backend.app.adapters`
- `url_env`
- `os.environ`
- `subprocess`
- `socket.socket`
- `time.time(`
- `time.monotonic(`
- `datetime.now(`
- `datetime.utcnow(`
- `print(`
- `logging.`
- `httpx`
- `requests`
- `from v2.backend.app.services`
- `from v2.backend.app.composition`
- `from v2.backend.app.adapters.redis_v2`
- `from v2.backend.app.domain.trainer_liveness`
- `from v2.backend.app.domain.trainer_worker_health`
- `from v2.backend.app.domain.trainer_parity`

The literals are constructed at runtime in the guard tests via
string concatenation to avoid the forbidden-token guard scanning
its own source.

## Deferred items (NOT in 2E3.A)

- GPU telemetry domain (deferred to 2E3.B).
- Checkpoint observation service (deferred to 2E3.C).
- GPU telemetry observation service (deferred to 2E3.D).
- Composition root and subprocess-adapter wiring (deferred to
  2E3.E and 2E3.F).
- Real legacy checkpoint file reads (deferred to a later phase
  that opens the read-only legacy filesystem observation surface).
- Promotion controller invocation (forbidden — promotion remains
  legacy-controlled and human-approved per
  `03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md`).
- Stage A integration into `v2/backend/app/domain/trainer_parity/`
  (deferred to a later integration phase).
- Frontend rendering of checkpoint metadata (deferred to REQ_0008
  frontend milestone).
- Public API exposure / REST endpoints (deferred to a later
  phase).

PHASE2E3A_TRAINER_CHECKPOINT_METADATA_DOMAIN_SPEC_READY
