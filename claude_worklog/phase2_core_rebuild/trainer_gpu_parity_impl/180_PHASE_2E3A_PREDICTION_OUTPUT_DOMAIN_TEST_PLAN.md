# Phase 2E3.A — Trainer Prediction Output Domain Test Plan

This document enumerates the exact test files to author for Phase
2E3.A of REQ_0006 ∩ REQ_0017. The implementation task `110` MUST
emit the package marker plus all 31 sibling test files listed below
under
`v2/backend/tests/unit/domain/trainer_prediction_output/`. Every
test file contains exactly one test function whose name starts with
`test_` and uses inline hand-written fakes; no shared `conftest.py`
is created or modified.

## Package marker

- `v2/backend/tests/unit/domain/trainer_prediction_output/__init__.py`
  is empty (zero bytes; no docstring; no imports; no statements).

## Test files (exactly 31)

Public surface and constants:

1. `test_public_surface.py` — asserts the exact 8-tuple of names in
   `__all__` in the exact order declared in the spec.
2. `test_errors_invariants.py` — constructs
   `TrainerPredictionDomainError` with and without `field`, asserts
   `reason`, `field`, and `str(...)` formatting; asserts
   `isinstance(..., ValueError)`.
3. `test_prediction_direction_constants.py` — asserts the exact
   string values `"long"`, `"short"`, `"flat"` for the three
   direction constants.
4. `test_prediction_freshness_constants.py` — asserts the exact
   string values `"fresh"`, `"stale"`, `"missing"` for the three
   freshness constants.

Per-field invariants (each builds a fully valid record helper inline
and varies one field):

5. `test_record_invariants_prediction_id_non_empty.py` — empty
   string and whitespace-only string both fail; valid string passes.
6. `test_record_invariants_prediction_id_charset_and_length.py` —
   embedded whitespace fails; length-129 string fails; length-128
   passes; non-`str` types fail with `must_be_str`.
7. `test_record_invariants_feature_snapshot_id.py` — same shape as
   `prediction_id` covering empty, whitespace, length cap, type.
8. `test_record_invariants_symbol_uppercase_and_charset.py` —
   lowercase fails (`must_be_uppercase`); embedded whitespace
   fails; length cap 32; non-`str` fails; canonical
   `BTCUSDT`-style passes.
9. `test_record_invariants_model_version.py` — empty fails; length
   cap 64 enforced; non-`str` fails.
10. `test_record_invariants_checkpoint_id.py` — empty fails; length
    cap 128 enforced; non-`str` fails.
11. `test_record_invariants_prediction_ts_ms.py` — negative fails;
    `bool` fails (`must_be_int`); zero passes; positive int passes.
12. `test_record_invariants_direction_in_allowed.py` — `"long"`,
    `"short"`, `"flat"` pass; any other string fails
    (`invalid_direction`); non-`str` fails (`must_be_str`).
13. `test_record_invariants_confidence_raw_range.py` — values below
    0.0, above 1.0, NaN, +inf, -inf each fail; 0.0, 0.5, 1.0 pass.
14. `test_record_invariants_confidence_raw_type.py` — `int` 0 and
    `bool` False each fail with `must_be_float`; valid `float`
    passes.
15. `test_record_invariants_confidence_calibrated_range.py` — same
    coverage as `confidence_raw_range` for the calibrated field.
16. `test_record_invariants_confidence_calibrated_type.py` — same
    coverage as `confidence_raw_type` for the calibrated field.
17. `test_record_invariants_worker_id.py` — empty fails; length cap
    64 enforced; non-`str` fails.
18. `test_record_invariants_worker_health_status_in_allowed.py` —
    `"HEALTHY"`, `"DEGRADED"`, `"CRITICAL"`, `"UNKNOWN"` all pass;
    any other string fails (`invalid_worker_health_status`); lower
    case `"healthy"` fails; non-`str` fails.
19. `test_record_invariants_freshness_flag_in_allowed.py` —
    `"fresh"`, `"stale"`, `"missing"` all pass; any other string
    fails (`invalid_freshness_flag`); non-`str` fails.
20. `test_record_invariants_freshness_missing_requires_none_age.py`
    — `freshness_flag == "missing"` with non-`None`
    `source_freshness_age_ms` fails with
    `missing_requires_none_age`.
21. `test_record_invariants_freshness_fresh_or_stale_requires_int_age.py`
    — `freshness_flag == "fresh"` or `"stale"` with `None`
    `source_freshness_age_ms` fails with
    `freshness_requires_int_age`; with valid `int >= 0` passes.
22. `test_record_invariants_source_freshness_age_ms_type.py` —
    negative `int` fails; `bool` fails (`must_be_int_or_none`);
    `0` and positive `int` and `None` pass per spec rules.
23. `test_record_invariants_top_positive_feature_codes.py` —
    non-`tuple` (list, set, dict) fails; empty `tuple` passes;
    each element must be `str`; embedded whitespace fails; length
    cap 64 per element; tuple length cap 8; duplicates fail.
24. `test_record_invariants_top_negative_feature_codes.py` — same
    shape as `top_positive_feature_codes` for the negative tuple.
25. `test_record_invariants_top_positive_negative_disjoint.py` —
    intersecting feature codes fail with
    `must_be_disjoint_from_top_positive`; disjoint passes; both
    empty passes.

Happy paths and immutability:

26. `test_record_happy_path_long.py` — full valid LONG record;
    asserts no exception and field round-trip equality.
27. `test_record_happy_path_short.py` — full valid SHORT record.
28. `test_record_happy_path_flat.py` — full valid FLAT record with
    confidences 0.0 and empty top-K tuples and
    `freshness_flag == "missing"` with `source_freshness_age_ms is
    None`.
29. `test_record_frozen.py` — asserts mutation raises
    `dataclasses.FrozenInstanceError`; asserts `__hash__` works
    (hash equality on equal records).

Import-graph and forbidden-token tests:

30. `test_prediction_output_domain_does_not_import_redis.py` —
    imports the package fresh in a child interpreter via
    `subprocess.run([sys.executable, "-c", ...])` (note: the
    `subprocess` module reference is in the TEST file only, NEVER
    in any of the three authored source files; the test verifies
    none of `redis`, `redis.asyncio`, `aioredis`, `hiredis`,
    `v2.backend.app.adapters.redis_v2.url_env`, the gamma.real
    factory, `fastapi`, or `uvicorn` enter `sys.modules` after
    import).
31. `test_prediction_output_domain_forbidden_tokens.py` — for each
    forbidden literal listed in spec §"Forbidden tokens in source
    files", scans the THREE authored source files
    (`__init__.py`, `errors.py`, `record.py`) and asserts zero
    matches. Each forbidden literal is constructed at runtime via
    string concatenation so the test file itself does not contain
    the bare token. NO exemption applies.

## Validation commands run by `110`

The implementation task runs these commands and captures stdout +
exit code into `183_2E3A_PREDICTION_OUTPUT_DOMAIN_IMPLEMENTATION_REPORT.md`:

1. `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q`
   (REQUIRED RESULT: 31 passed, zero failures, zero errors).
2. `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_worker_health/ -q`
   (regression).
3. `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ -q`
   (regression).
4. `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_worker_health/ -q`
   (regression).
5. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_worker_health/ -q`
   (regression).
6. `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q`
   (regression).
7. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q`
   (regression).
8. `python -m py_compile v2/backend/app/domain/trainer_prediction_output/__init__.py v2/backend/app/domain/trainer_prediction_output/errors.py v2/backend/app/domain/trainer_prediction_output/record.py`
   (REQUIRED RESULT: exit code zero).
9. `git status -s` over the cross-isolation paths declared in `181`
   (REQUIRED RESULT: zero lines).
10. `rg --fixed-strings --case-sensitive <token>
    v2/backend/app/domain/trainer_prediction_output/` for each
    forbidden token from spec §"Forbidden tokens in source files"
    (REQUIRED RESULT: zero matches per token).
11. `rg "^END_FILE_SENTINEL:"
    v2/backend/app/domain/trainer_prediction_output/
    v2/backend/tests/unit/domain/trainer_prediction_output/
    claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/183_2E3A_PREDICTION_OUTPUT_DOMAIN_IMPLEMENTATION_REPORT.md
    claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/184_2E3A_PREDICTION_OUTPUT_DOMAIN_GO_NO_GO.md`
    (REQUIRED RESULT: zero matches).

PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_TEST_PLAN_READY
