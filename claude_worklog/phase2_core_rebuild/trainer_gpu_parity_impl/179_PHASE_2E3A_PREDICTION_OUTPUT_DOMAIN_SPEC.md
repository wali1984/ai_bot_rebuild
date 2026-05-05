# Phase 2E3.A — Trainer Prediction Output Domain Spec

This document is the authoring spec for Phase 2E3.A of REQ_0006 ∩
REQ_0017. It is the first sub-phase of the
`TRAINER_PREDICTION_OUTPUT_MVP` milestone. It builds a NEW domain
package
`v2/backend/app/domain/trainer_prediction_output/` whose only purpose
is to define the `TrainerPredictionRecord` value object plus the
direction and freshness flag constants that downstream orchestrator,
risk-gateway, and paper-execution milestones will consume.

The package is purely value-object oriented. It does NOT compute
predictions. It does NOT call a model. It does NOT touch I/O, Redis,
files, or HTTP. Importing the package MUST NOT cause `redis`,
`redis.asyncio`, `aioredis`, `hiredis`, `fastapi`, `uvicorn`,
`httpx`, `requests`, `asyncio`, `threading`, or
`v2.backend.app.adapters.redis_v2.url_env` to enter `sys.modules`.

## Predecessor gates

- 2E2.C composition root Codex pass:
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`.

If this marker is absent, the supervisor MUST NOT dispatch
`110_trainer_parity_2e3a_prediction_output_domain_implementation`.

## Module location decision

The new package is a sibling of the existing
`v2/backend/app/domain/trainer_liveness/`,
`v2/backend/app/domain/trainer_worker_health/`, and
`v2/backend/app/domain/trainer_parity/` packages. It does NOT live
inside any of those, because the prediction record is a distinct
Stage A trainer output contract per
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`.

No 2E1 or 2E2 file is modified by this milestone.

## Scope (additive only — no edits to existing surface)

Files to create (exact set, no extras):

- `v2/backend/app/domain/trainer_prediction_output/__init__.py`
- `v2/backend/app/domain/trainer_prediction_output/errors.py`
- `v2/backend/app/domain/trainer_prediction_output/record.py`
- `v2/backend/tests/unit/domain/trainer_prediction_output/__init__.py`
- 31 sibling test files enumerated in
  `180_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_TEST_PLAN.md`.

## Public surface (exact `__all__`)

`v2/backend/app/domain/trainer_prediction_output/__init__.py` exposes
exactly the following names, in this order, in `__all__`:

1. `TrainerPredictionDomainError`
2. `TrainerPredictionRecord`
3. `PREDICTION_DIRECTION_LONG`
4. `PREDICTION_DIRECTION_SHORT`
5. `PREDICTION_DIRECTION_FLAT`
6. `PREDICTION_FRESHNESS_FRESH`
7. `PREDICTION_FRESHNESS_STALE`
8. `PREDICTION_FRESHNESS_MISSING`

No other names are re-exported. The `__init__.py` MUST NOT introduce
any module-level globals beyond the eight re-exports.

## TrainerPredictionDomainError

`errors.py` defines:

```
class TrainerPredictionDomainError(ValueError):
    def __init__(self, reason: str, *, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        message = reason if field is None else f"{field}: {reason}"
        super().__init__(message)
```

`errors.py` imports nothing beyond `from __future__ import annotations`.
It MUST NOT import any `v2/` module, `redis`, `aioredis`, `hiredis`,
`redis.asyncio`, the gamma.real factory, or `url_env`.

## Direction and freshness constants

`record.py` defines exactly six string constants with exact values:

- `PREDICTION_DIRECTION_LONG = "long"`
- `PREDICTION_DIRECTION_SHORT = "short"`
- `PREDICTION_DIRECTION_FLAT = "flat"`
- `PREDICTION_FRESHNESS_FRESH = "fresh"`
- `PREDICTION_FRESHNESS_STALE = "stale"`
- `PREDICTION_FRESHNESS_MISSING = "missing"`

Plus three module-private frozenset literals used by the dataclass
invariant check:

- `_ALLOWED_DIRECTIONS = frozenset({PREDICTION_DIRECTION_LONG, PREDICTION_DIRECTION_SHORT, PREDICTION_DIRECTION_FLAT})`
- `_ALLOWED_FRESHNESS = frozenset({PREDICTION_FRESHNESS_FRESH, PREDICTION_FRESHNESS_STALE, PREDICTION_FRESHNESS_MISSING})`
- `_ALLOWED_WORKER_HEALTH_STATUSES = frozenset({"HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"})`

The four worker-health-status string values are duplicated from the
2E2.A `trainer_worker_health.health_status` module DELIBERATELY. The
prediction record domain takes a SNAPSHOT STRING of worker health as
a lineage field; a runtime import from `trainer_worker_health` would
make `trainer_worker_health` a transitive import of every prediction
record consumer, which violates the redis-clean and minimal-coupling
invariants of this MVP package. The values are stable contract
strings; divergence risk is low.

## TrainerPredictionRecord

`record.py` defines:

```
@dataclass(frozen=True, slots=True)
class TrainerPredictionRecord:
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    model_version: str
    checkpoint_id: str
    prediction_ts_ms: int
    direction: str
    confidence_raw: float
    confidence_calibrated: float
    worker_id: str
    worker_health_status: str
    freshness_flag: str
    source_freshness_age_ms: int | None
    top_positive_feature_codes: tuple[str, ...]
    top_negative_feature_codes: tuple[str, ...]
```

Field count: 15. All fields are positional. No defaults.

### Field-level invariants (raised as `TrainerPredictionDomainError`)

- `prediction_id`: must be `str`, length >= 1, no leading/trailing
  whitespace, no embedded whitespace, length <= 128.
  - violations: `"must_be_str"`, `"must_be_non_empty"`,
    `"must_not_have_whitespace"`, `"must_be_at_most_128_chars"`
    (field=`prediction_id`).
- `feature_snapshot_id`: same shape and same violations as
  `prediction_id` (field=`feature_snapshot_id`).
- `symbol`: must be `str`, length >= 1, no whitespace, length <= 32,
  must equal its own `.upper()` (uppercase ASCII canonical form)
  - violations: `"must_be_str"`, `"must_be_non_empty"`,
    `"must_not_have_whitespace"`, `"must_be_at_most_32_chars"`,
    `"must_be_uppercase"` (field=`symbol`).
- `model_version`: must be `str`, length >= 1, length <= 64.
  - violations: `"must_be_str"`, `"must_be_non_empty"`,
    `"must_be_at_most_64_chars"` (field=`model_version`).
- `checkpoint_id`: must be `str`, length >= 1, length <= 128.
  - violations: `"must_be_str"`, `"must_be_non_empty"`,
    `"must_be_at_most_128_chars"` (field=`checkpoint_id`).
- `prediction_ts_ms`: must be `int` (not `bool`), >= 0.
  - violations: `"must_be_int"`, `"must_be_nonnegative"`
    (field=`prediction_ts_ms`).
- `direction`: must be in `_ALLOWED_DIRECTIONS`.
  - violations: `"must_be_str"`, `"invalid_direction"`
    (field=`direction`).
- `confidence_raw`: must be `float` (not `bool`, not `int`),
  `0.0 <= x <= 1.0`, finite (not NaN, not +inf, not -inf).
  - violations: `"must_be_float"`, `"must_be_finite"`,
    `"must_be_in_unit_interval"` (field=`confidence_raw`).
- `confidence_calibrated`: same shape and same violations as
  `confidence_raw` (field=`confidence_calibrated`).
- `worker_id`: must be `str`, length >= 1, length <= 64.
  - violations: `"must_be_str"`, `"must_be_non_empty"`,
    `"must_be_at_most_64_chars"` (field=`worker_id`).
- `worker_health_status`: must be in
  `_ALLOWED_WORKER_HEALTH_STATUSES`.
  - violations: `"must_be_str"`, `"invalid_worker_health_status"`
    (field=`worker_health_status`).
- `freshness_flag`: must be in `_ALLOWED_FRESHNESS`.
  - violations: `"must_be_str"`, `"invalid_freshness_flag"`
    (field=`freshness_flag`).
- `source_freshness_age_ms`: must be `None` OR `int` (not `bool`)
  with `>= 0`.
  - violations: `"must_be_int_or_none"`, `"must_be_nonnegative"`
    (field=`source_freshness_age_ms`).
- `top_positive_feature_codes`: must be `tuple` (exact type, not
  list or any subclass), each element must be `str` of length >= 1,
  length <= 64, no embedded whitespace; tuple length must be `<= 8`;
  no duplicates.
  - violations: `"must_be_tuple"`, `"must_be_str"`,
    `"must_be_non_empty"`, `"must_not_have_whitespace"`,
    `"must_be_at_most_64_chars"`, `"must_be_at_most_8_entries"`,
    `"must_be_unique"` (field=`top_positive_feature_codes`).
- `top_negative_feature_codes`: same shape and same violations as
  `top_positive_feature_codes`
  (field=`top_negative_feature_codes`).

### Cross-field invariants

- `top_positive_feature_codes` and `top_negative_feature_codes`
  MUST be disjoint sets (no shared feature code).
  - violation: `"must_be_disjoint_from_top_positive"`
    (field=`top_negative_feature_codes`).
- If `freshness_flag == PREDICTION_FRESHNESS_MISSING` then
  `source_freshness_age_ms` MUST be `None`.
  - violation: `"missing_requires_none_age"`
    (field=`source_freshness_age_ms`).
- If `freshness_flag == PREDICTION_FRESHNESS_FRESH` OR
  `freshness_flag == PREDICTION_FRESHNESS_STALE` then
  `source_freshness_age_ms` MUST be an `int >= 0` (NOT `None`).
  - violation: `"freshness_requires_int_age"`
    (field=`source_freshness_age_ms`).

### Frozen / hashable

`@dataclass(frozen=True, slots=True)` is required. Tests assert
that mutation raises `dataclasses.FrozenInstanceError`.

## Forbidden tokens in source files

The following literal substrings MUST NOT appear in
`__init__.py`, `errors.py`, or `record.py`. The
`test_prediction_output_domain_forbidden_tokens.py` test scans all
three source files for each token via a runtime-constructed string
scan.

- `redis`
- `aioredis`
- `hiredis`
- `redis.asyncio`
- `url_env`
- `factory`
- `fastapi`
- `FastAPI`
- `lifespan`
- `uvicorn`
- `httpx`
- `requests`
- `asyncio`
- `threading`
- `multiprocessing`
- `subprocess`
- `socket`
- `selectors`
- `os.environ`
- `getenv`
- `open(`
- `Path(`
- `pathlib`
- `time.time`
- `time.sleep`
- `datetime`
- `logging`
- `print(`
- `eval(`
- `exec(`
- `compile(`
- `pickle`
- `marshal`
- `__import__`
- `importlib`

NO exemption applies.

## Import boundaries

### `__init__.py`

Imports allowed (exact set):

1. `from .errors import TrainerPredictionDomainError`
2. `from .record import TrainerPredictionRecord`
3. `from .record import PREDICTION_DIRECTION_LONG`
4. `from .record import PREDICTION_DIRECTION_SHORT`
5. `from .record import PREDICTION_DIRECTION_FLAT`
6. `from .record import PREDICTION_FRESHNESS_FRESH`
7. `from .record import PREDICTION_FRESHNESS_STALE`
8. `from .record import PREDICTION_FRESHNESS_MISSING`

No third-party import. No other `v2/` import.

### `errors.py`

Imports allowed (exact set):

1. `from __future__ import annotations`

No third-party import. No `v2/` import. No standard library import
beyond `__future__`.

### `record.py`

Imports allowed (exact set):

1. `from __future__ import annotations`
2. `import math`
3. `from dataclasses import dataclass`
4. `from .errors import TrainerPredictionDomainError`

No other import. `math` is required only for `math.isfinite` in the
confidence-finiteness invariant. No third-party import. No other
`v2/` import. No `typing` import (the `tuple[str, ...]`, `int | None`,
and other annotations are deferred via `from __future__ import
annotations`).

## Validation policy summary

- `pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q`
  passes with zero failures and zero errors.
- `python -m py_compile` passes for all three authored source files.
- `git status -s` over the cross-isolation paths declared in `181`
  returns zero lines.
- The four prior-suite regression tests in 2E1 and 2E2 still pass.
- `rg --fixed-strings --case-sensitive` finds zero matches per
  forbidden token across all three authored source files.
- Importing
  `v2.backend.app.domain.trainer_prediction_output` does not pull
  any forbidden module into `sys.modules`.

PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_SPEC_READY
