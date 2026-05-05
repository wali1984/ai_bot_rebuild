# Phase 2E3.A — Checkpoint Metadata Domain Test Plan

This document enumerates the exact 20 unit test files Phase 2E3.A
emits under `v2/backend/tests/unit/domain/checkpoint_metadata/`,
plus the package marker, plus the validation commands the
implementation task MUST execute. Each test file contains exactly
one `test_*` function whose name mirrors the file basename and
whose body exercises exactly one case. No shared `conftest.py` is
created or modified. No fixture is registered. Hand-written
`CheckpointMetadata` constructions are inline.

## Package marker

`v2/backend/tests/unit/domain/checkpoint_metadata/__init__.py` is a
single-newline file.

## Test files (20)

1. `test_public_surface.py` — asserts
   `v2.backend.app.domain.checkpoint_metadata.__all__` equals the
   exact 6-name tuple in canonical order from `179` and that each
   bound name is the symbol it claims to export.
2. `test_errors_invariants.py` — asserts
   `CheckpointMetadataDomainError` is a subclass of `ValueError`,
   stores `reason` and `field` attributes, formats the message as
   `"<field>: <reason>"` when field is provided, and as `"<reason>"`
   when field is None.
3. `test_promotion_status_constants.py` — asserts the three
   `PROMOTION_STATUS_*` constants have the exact string values
   `"NOT_PROMOTED"`, `"PROMOTED"`, `"UNKNOWN"`.
4. `test_metadata_invariants_checkpoint_id_must_be_non_empty_str.py`
   — exercises four sub-cases inline:
   - `checkpoint_id=42` raises with field `"checkpoint_id"` and
     reason `"must_be_str"`.
   - `checkpoint_id=None` raises with field `"checkpoint_id"` and
     reason `"must_be_str"`.
   - `checkpoint_id=b"bytes"` raises with field `"checkpoint_id"`
     and reason `"must_be_str"`.
   - `checkpoint_id=""` raises with field `"checkpoint_id"` and
     reason `"must_be_non_empty"`.
5. `test_metadata_invariants_model_version_must_be_non_empty_str.py`
   — exercises four sub-cases inline mirroring the
   `model_version` field.
6. `test_metadata_invariants_created_ts_ms_must_be_int.py` —
   exercises three sub-cases inline:
   - `created_ts_ms=1.0` raises with field `"created_ts_ms"` and
     reason `"must_be_int"`.
   - `created_ts_ms="1"` raises with field `"created_ts_ms"` and
     reason `"must_be_int"`.
   - `created_ts_ms=True` raises with field `"created_ts_ms"` and
     reason `"must_be_int"` (`bool` is rejected via
     `type(...) is int` check).
7. `test_metadata_invariants_created_ts_ms_must_be_non_negative.py`
   — `created_ts_ms=-1` raises with field `"created_ts_ms"` and
   reason `"must_be_non_negative"`.
8. `test_metadata_invariants_promotion_status_in_allowed.py` —
   exercises three sub-cases inline:
   - `promotion_status="HEALTHY"` raises with field
     `"promotion_status"` and reason `"invalid_promotion_status"`.
   - `promotion_status=""` raises with field `"promotion_status"`
     and reason `"invalid_promotion_status"`.
   - `promotion_status="not_promoted"` (lowercase) raises with
     field `"promotion_status"` and reason
     `"invalid_promotion_status"`.
9. `test_metadata_invariants_legacy_checkpoint_path_must_be_non_empty_str.py`
   — exercises three sub-cases inline:
   - `legacy_checkpoint_path=42` raises with field
     `"legacy_checkpoint_path"` and reason `"must_be_str"`.
   - `legacy_checkpoint_path=None` raises with field
     `"legacy_checkpoint_path"` and reason `"must_be_str"`.
   - `legacy_checkpoint_path=""` raises with field
     `"legacy_checkpoint_path"` and reason `"must_be_non_empty"`.
10. `test_metadata_invariants_legacy_checkpoint_path_must_be_absolute.py`
    — exercises two sub-cases inline:
    - `legacy_checkpoint_path="relative/path.pt"` raises with
      field `"legacy_checkpoint_path"` and reason
      `"must_be_absolute"`.
    - `legacy_checkpoint_path="./local.pt"` raises with field
      `"legacy_checkpoint_path"` and reason `"must_be_absolute"`.
11. `test_metadata_invariants_legacy_metadata_hash_format.py` —
    exercises five sub-cases inline:
    - `legacy_metadata_hash=123` raises with field
      `"legacy_metadata_hash"` and reason `"must_be_str"`.
    - `legacy_metadata_hash="abc"` (length 3) raises with field
      `"legacy_metadata_hash"` and reason `"must_be_64_chars"`.
    - `legacy_metadata_hash="a" * 65` raises with field
      `"legacy_metadata_hash"` and reason `"must_be_64_chars"`.
    - `legacy_metadata_hash="A" * 64` (uppercase hex) raises
      with field `"legacy_metadata_hash"` and reason
      `"must_be_lowercase_hex"`.
    - `legacy_metadata_hash="g" * 64` (non-hex) raises with field
      `"legacy_metadata_hash"` and reason
      `"must_be_lowercase_hex"`.
12. `test_metadata_invariants_promoted_requires_promotion_ts.py` —
    constructs a `CheckpointMetadata` candidate with
    `promotion_status=PROMOTION_STATUS_PROMOTED` and
    `promotion_ts_ms=None` and asserts a
    `CheckpointMetadataDomainError` is raised with field
    `"promotion_ts_ms"` and reason
    `"promoted_requires_promotion_ts"`.
13. `test_metadata_invariants_no_promotion_ts_when_not_promoted_or_unknown.py`
    — exercises two sub-cases inline:
    - `promotion_status=PROMOTION_STATUS_NOT_PROMOTED` and
      `promotion_ts_ms=1700000000000` raises with field
      `"promotion_ts_ms"` and reason
      `"not_promoted_requires_no_promotion_ts"`.
    - `promotion_status=PROMOTION_STATUS_UNKNOWN` and
      `promotion_ts_ms=1700000000000` raises with field
      `"promotion_ts_ms"` and reason
      `"unknown_requires_no_promotion_ts"`.
14. `test_metadata_invariants_promotion_ts_must_be_non_negative_int_when_set.py`
    — exercises three sub-cases inline (with
    `promotion_status=PROMOTION_STATUS_PROMOTED` so the
    promotion-required branch is exercised first only if the
    type/sign branch fires after; the test constructs the inputs
    so the type/sign branch fires):
    - `promotion_ts_ms=1.0` raises with field
      `"promotion_ts_ms"` and reason `"must_be_int"`.
    - `promotion_ts_ms=True` raises with field
      `"promotion_ts_ms"` and reason `"must_be_int"`.
    - `promotion_ts_ms=-1` raises with field `"promotion_ts_ms"`
      and reason `"must_be_non_negative"`.
15. `test_metadata_immutable.py` — constructs a valid
    `CheckpointMetadata` and asserts that
    `dataclasses.is_dataclass(CheckpointMetadata) is True`,
    `CheckpointMetadata.__dataclass_params__.frozen is True`,
    and that `setattr(instance, "checkpoint_id", "other")`
    raises `dataclasses.FrozenInstanceError`. Also asserts
    `__slots__` is present on the class.
16. `test_validate_checkpoint_metadata_passes_valid.py` —
    constructs a fully-valid `CheckpointMetadata` instance,
    invokes `validate_checkpoint_metadata`, asserts the return
    value is the exact same object (`is` identity preserved),
    and asserts no exception is raised.
17. `test_validate_checkpoint_metadata_propagates_invariant_error.py`
    — confirms that validating a candidate that fails an
    invariant (constructed via `object.__new__` to bypass the
    constructor and assigning frozen-dataclass fields via
    `object.__setattr__`) propagates the original
    `CheckpointMetadataDomainError` unchanged. The test asserts
    the same `reason` and `field` attributes appear on the
    propagated error.
18. `test_validate_checkpoint_metadata_does_not_mutate_input.py` —
    constructs a fully-valid `CheckpointMetadata`, captures
    `(id(instance), instance.checkpoint_id, instance.model_version,
    instance.created_ts_ms, instance.promotion_status,
    instance.promotion_ts_ms, instance.legacy_checkpoint_path,
    instance.legacy_metadata_hash)` before the call, invokes
    `validate_checkpoint_metadata`, and asserts every captured
    field is unchanged after the call and the returned object
    `is` the input.
19. `test_checkpoint_metadata_domain_does_not_import_redis.py` —
    constructs every forbidden literal at runtime via string
    concatenation (per `179` 'Forbidden tokens' list). Reads each
    of the five authored source files via `pathlib.Path.read_text`
    and asserts no forbidden literal appears in any file.
    Removes any cached `redis*` and `aioredis*` modules from
    `sys.modules` via a list-comprehension over `sys.modules`,
    re-imports `v2.backend.app.domain.checkpoint_metadata`, and
    asserts that no module name starting with `"redis"` is in
    `sys.modules`.
20. `test_checkpoint_metadata_domain_does_not_import_url_env.py` —
    constructs every forbidden literal at runtime via string
    concatenation. Reads each of the five authored source files
    and asserts no forbidden literal appears in any file. Removes
    any cached `v2.backend.app.adapters.redis_v2.url_env` module
    from `sys.modules`, re-imports
    `v2.backend.app.domain.checkpoint_metadata`, and asserts that
    `"v2.backend.app.adapters.redis_v2.url_env"` is NOT in
    `sys.modules`. Also asserts the
    `"v2.backend.app.adapters"` package is NOT in `sys.modules`.

## Validation commands

The implementation task `110` MUST run, in this exact order, and
abort on the first non-zero exit by emitting the FAIL marker in
`184`:

- `python -m py_compile v2/backend/app/domain/checkpoint_metadata/__init__.py v2/backend/app/domain/checkpoint_metadata/errors.py v2/backend/app/domain/checkpoint_metadata/promotion_status.py v2/backend/app/domain/checkpoint_metadata/checkpoint_metadata.py v2/backend/app/domain/checkpoint_metadata/checkpoint_validators.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/checkpoint_metadata/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_worker_health/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_worker_health/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_worker_health/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/checkpoint_metadata/ --collect-only -q`
- `git status -s` over the cross-isolation paths in `181`. Any
  line is a hard fail.

The collect-only command MUST report exactly 20 collected items.

PHASE2E3A_TRAINER_CHECKPOINT_METADATA_DOMAIN_TEST_PLAN_READY
