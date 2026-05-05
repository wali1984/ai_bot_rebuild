# Phase 2F.A — Orchestrator Decision Domain Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/domain/orchestrator_decision/`. The test package marker `__init__.py` is the 35th file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 34 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_decision_action_constants.py`
4. `test_decision_reason_constants.py`
5. `test_errors_invariants.py`
6. `test_record_frozen.py`
7. `test_record_happy_path_open_long.py`
8. `test_record_happy_path_open_short.py`
9. `test_record_happy_path_hold.py`
10. `test_record_happy_path_abstain_low_confidence.py`
11. `test_record_happy_path_abstain_freshness_stale.py`
12. `test_record_happy_path_abstain_freshness_missing.py`
13. `test_record_happy_path_abstain_worker_degraded.py`
14. `test_record_happy_path_abstain_worker_critical.py`
15. `test_record_happy_path_abstain_worker_unknown.py`
16. `test_record_invariants_decision_id_charset_and_length.py`
17. `test_record_invariants_decision_id_non_empty.py`
18. `test_record_invariants_prediction_id.py`
19. `test_record_invariants_feature_snapshot_id.py`
20. `test_record_invariants_symbol_uppercase_and_charset.py`
21. `test_record_invariants_decision_ts_ms.py`
22. `test_record_invariants_decision_action_in_allowed.py`
23. `test_record_invariants_decision_reason_code_in_allowed.py`
24. `test_record_invariants_input_prediction_direction_in_allowed.py`
25. `test_record_invariants_input_prediction_confidence_calibrated_range.py`
26. `test_record_invariants_input_prediction_confidence_calibrated_type.py`
27. `test_record_invariants_input_prediction_freshness_flag_in_allowed.py`
28. `test_record_invariants_input_worker_health_status_in_allowed.py`
29. `test_record_invariants_live_blocked_must_be_true.py`
30. `test_record_invariants_open_long_requires_proceed_long_and_long_direction.py`
31. `test_record_invariants_open_short_requires_proceed_short_and_short_direction.py`
32. `test_record_invariants_hold_requires_hold_flat_direction_and_flat_direction.py`
33. `test_record_invariants_abstain_requires_abstain_prefix_reason.py`
34. `test_orchestrator_decision_domain_does_not_import_redis.py`
35. `test_orchestrator_decision_domain_forbidden_tokens.py`

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.domain.orchestrator_decision` and asserts that `__all__` equals exactly the 15-tuple in spec order. Asserts each name resolves to the expected object: `OrchestratorDecisionDomainError` is a subclass of `ValueError`; `OrchestratorDecisionRecord` is a frozen dataclass with `__dataclass_fields__`; the four action constants and eleven reason constants are `str`.

### test_decision_action_constants.py

Asserts the four action constants equal `"open_long"`, `"open_short"`, `"hold"`, `"abstain"` exactly. Asserts they are pairwise distinct.

### test_decision_reason_constants.py

Asserts each of the eleven reason constants equals its expected literal. Asserts pairwise distinctness. Asserts every `DECISION_REASON_ABSTAIN_*` starts with `"abstain_"`. Asserts every `DECISION_REASON_PROCEED_*` starts with `"proceed_"`. Asserts `DECISION_REASON_HOLD_FLAT_DIRECTION == "hold_flat_direction"`.

### test_errors_invariants.py

Constructs `OrchestratorDecisionDomainError("must_be_int")` and asserts `.reason == "must_be_int"`, `.field is None`, `str(e) == "must_be_int"`, and `isinstance(e, ValueError) is True`. Constructs `OrchestratorDecisionDomainError("must_be_int", field="decision_ts_ms")` and asserts `.field == "decision_ts_ms"`, `str(e) == "decision_ts_ms: must_be_int"`.

### test_record_frozen.py

Constructs a happy-path record. Asserts assignment to any field raises `dataclasses.FrozenInstanceError`. Asserts `__slots__` is present on the class.

### test_record_happy_path_open_long.py

Constructs a happy-path record with `decision_action=DECISION_ACTION_OPEN_LONG`, `decision_reason_code=DECISION_REASON_PROCEED_LONG`, `input_prediction_direction="long"`, `input_prediction_confidence_calibrated=0.85`, `input_prediction_freshness_flag="fresh"`, `input_worker_health_status="HEALTHY"`, `live_blocked=True`. Asserts no exception is raised. Asserts each field is preserved by reading back the attribute.

### test_record_happy_path_open_short.py

Same as `_open_long` but with the open-short combination.

### test_record_happy_path_hold.py

Same as above but with `decision_action=DECISION_ACTION_HOLD`, `decision_reason_code=DECISION_REASON_HOLD_FLAT_DIRECTION`, `input_prediction_direction="flat"`.

### test_record_happy_path_abstain_low_confidence.py

Constructs an abstain record with `decision_action=DECISION_ACTION_ABSTAIN`, `decision_reason_code=DECISION_REASON_ABSTAIN_LOW_CONFIDENCE`. The input fields are otherwise valid (e.g., `input_prediction_direction="long"`, `input_prediction_confidence_calibrated=0.10`, `input_prediction_freshness_flag="fresh"`, `input_worker_health_status="HEALTHY"`). Asserts no exception.

### test_record_happy_path_abstain_freshness_stale.py / _missing.py / _worker_degraded.py / _worker_critical.py / _worker_unknown.py

Each test constructs a record with the abstain action and the matching abstain reason code; the input fields reflect the specific abstain cause (e.g., `input_prediction_freshness_flag="stale"` for the stale test, `input_worker_health_status="DEGRADED"` for the worker-degraded test). Asserts no exception. The input direction can be any allowed value (`"long"`, `"short"`, `"flat"`); each test picks one and documents the choice.

### test_record_invariants_decision_id_charset_and_length.py

Asserts each of the following inputs raises `OrchestratorDecisionDomainError` with `field="decision_id"`:
- non-string (e.g., `42`) → reason `must_be_str`
- empty `""` → reason `must_be_non_empty`
- leading/trailing whitespace `" abc"` → reason `must_not_have_whitespace`
- internal whitespace `"a b"` → reason `must_not_have_whitespace`
- length 129 → reason `must_be_at_most_128_chars`

### test_record_invariants_decision_id_non_empty.py

Tests the explicit empty-string rejection separately to lock in the message.

### test_record_invariants_prediction_id.py

Same charset and length matrix as `decision_id`, with `field="prediction_id"`.

### test_record_invariants_feature_snapshot_id.py

Same charset and length matrix as `decision_id`, with `field="feature_snapshot_id"`.

### test_record_invariants_symbol_uppercase_and_charset.py

Asserts non-string raises with reason `must_be_str`; empty raises `must_be_non_empty`; whitespace raises `must_not_have_whitespace`; length 33 raises `must_be_at_most_32_chars`; lowercase `"btcusdt"` raises `must_be_uppercase`.

### test_record_invariants_decision_ts_ms.py

Asserts non-int (e.g., `1.0`, `"100"`, `True`, `False`) raises with reason `must_be_int`. Asserts `-1` raises `must_be_nonnegative`. Asserts `0` is accepted in a happy-path construction.

### test_record_invariants_decision_action_in_allowed.py

Asserts the literal `"OPEN_LONG"` (uppercase), the literal `"buy"`, and the literal `""` each raise `OrchestratorDecisionDomainError` with `field="decision_action"` and reason `invalid_decision_action`. Asserts a non-string `42` raises `must_be_str`.

### test_record_invariants_decision_reason_code_in_allowed.py

Asserts an unrecognized reason code (e.g., `"proceed_neutral"`) raises with reason `invalid_decision_reason_code` and `field="decision_reason_code"`. Asserts non-string raises `must_be_str`.

### test_record_invariants_input_prediction_direction_in_allowed.py

Asserts an unrecognized direction (e.g., `"sideways"`) raises `invalid_input_prediction_direction`. Asserts non-string raises `must_be_str`.

### test_record_invariants_input_prediction_confidence_calibrated_range.py

Asserts `-0.0001` raises `must_be_in_unit_interval`; `1.0001` raises `must_be_in_unit_interval`; `float("nan")` and `float("inf")` and `float("-inf")` raise `must_be_finite`.

### test_record_invariants_input_prediction_confidence_calibrated_type.py

Asserts `True`, `1`, `"0.5"` each raise `must_be_float`.

### test_record_invariants_input_prediction_freshness_flag_in_allowed.py

Asserts `"unknown"`, `"FRESH"`, `""` raise `invalid_input_prediction_freshness_flag`. Non-string raises `must_be_str`.

### test_record_invariants_input_worker_health_status_in_allowed.py

Asserts `"healthy"` (lowercase), `"OK"`, `""` raise `invalid_input_worker_health_status`. Non-string raises `must_be_str`.

### test_record_invariants_live_blocked_must_be_true.py

Asserts `live_blocked=False` raises `OrchestratorDecisionDomainError("must_be_true", field="live_blocked")`. Asserts `live_blocked=1` (or any non-bool) raises `must_be_bool`.

### test_record_invariants_open_long_requires_proceed_long_and_long_direction.py

Asserts `decision_action=DECISION_ACTION_OPEN_LONG` with `decision_reason_code=DECISION_REASON_PROCEED_SHORT` raises `open_long_requires_proceed_long_reason` (`field="decision_reason_code"`).
Asserts `decision_action=DECISION_ACTION_OPEN_LONG` with `decision_reason_code=DECISION_REASON_PROCEED_LONG` and `input_prediction_direction="short"` raises `open_long_requires_long_input_direction` (`field="input_prediction_direction"`).

### test_record_invariants_open_short_requires_proceed_short_and_short_direction.py

Mirror of the `_open_long` test for the short side.

### test_record_invariants_hold_requires_hold_flat_direction_and_flat_direction.py

Asserts `decision_action=DECISION_ACTION_HOLD` with `decision_reason_code=DECISION_REASON_PROCEED_LONG` raises `hold_requires_hold_flat_direction_reason`. Asserts `decision_action=DECISION_ACTION_HOLD` with the correct reason but `input_prediction_direction="long"` raises `hold_requires_flat_input_direction`.

### test_record_invariants_abstain_requires_abstain_prefix_reason.py

Asserts `decision_action=DECISION_ACTION_ABSTAIN` with `decision_reason_code=DECISION_REASON_PROCEED_LONG` raises `abstain_requires_abstain_prefix_reason` (`field="decision_reason_code"`). Asserts an abstain action with each `DECISION_REASON_ABSTAIN_*` code constructs successfully.

### test_orchestrator_decision_domain_does_not_import_redis.py

Imports `v2.backend.app.domain.orchestrator_decision` in a fresh subprocess, then asserts `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env` are NOT in `sys.modules`. The subprocess invocation is the only `subprocess` call in the test suite and is permitted only inside this test file.

### test_orchestrator_decision_domain_forbidden_tokens.py

Reads each authored source file as text and asserts none of the forbidden tokens listed in `02_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC.md` appear in the file contents. The forbidden-token literals are constructed at runtime via string concatenation so the test file itself does not contain the bare tokens.

PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_TEST_PLAN_READY
