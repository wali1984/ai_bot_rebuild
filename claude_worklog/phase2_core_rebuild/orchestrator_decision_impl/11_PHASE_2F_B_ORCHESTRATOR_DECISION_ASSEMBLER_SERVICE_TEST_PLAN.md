# Phase 2F.B — Orchestrator Decision Assembler Service Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/services/orchestrator_decision/`. The test package marker `__init__.py` is the 37th file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 36 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_assembler_service_does_not_import_redis.py`
4. `test_assembler_service_does_not_import_url_env.py`
5. `test_assembler_service_does_not_register_fastapi_lifespan.py`
6. `test_assembler_service_forbidden_tokens.py`
7. `test_errors_invariants.py`
8. `test_assemble_keyword_only_params.py`
9. `test_assemble_calls_clock_exactly_once.py`
10. `test_assemble_records_clock_into_decision_ts_ms.py`
11. `test_assemble_decision_id_derived_from_prediction_id.py`
12. `test_assemble_rejects_non_callable_clock.py`
13. `test_assemble_rejects_clock_returning_non_int.py`
14. `test_assemble_rejects_clock_returning_negative.py`
15. `test_assemble_rejects_low_confidence_threshold_not_float.py`
16. `test_assemble_rejects_low_confidence_threshold_not_finite.py`
17. `test_assemble_rejects_low_confidence_threshold_below_zero.py`
18. `test_assemble_rejects_low_confidence_threshold_above_one.py`
19. `test_assemble_rejects_prediction_not_record.py`
20. `test_assemble_rejects_prediction_id_too_long_for_decision_id_derivation.py`
21. `test_assemble_returns_orchestrator_decision_record.py`
22. `test_assemble_returns_frozen_record.py`
23. `test_assemble_open_long.py`
24. `test_assemble_open_short.py`
25. `test_assemble_hold_flat.py`
26. `test_assemble_abstain_freshness_missing.py`
27. `test_assemble_abstain_freshness_stale.py`
28. `test_assemble_abstain_worker_critical.py`
29. `test_assemble_abstain_worker_degraded.py`
30. `test_assemble_abstain_worker_unknown.py`
31. `test_assemble_abstain_low_confidence.py`
32. `test_assemble_priority_freshness_missing_over_stale.py`
33. `test_assemble_priority_freshness_over_worker.py`
34. `test_assemble_priority_worker_over_low_confidence.py`
35. `test_assemble_priority_low_confidence_over_action.py`
36. `test_assemble_at_threshold_is_not_low_confidence.py`
37. `test_assemble_propagates_input_lineage_fields.py`

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.services.orchestrator_decision` and asserts that `__all__` equals exactly the 2-tuple `("assemble_orchestrator_decision_record", "OrchestratorDecisionServiceError")` in that order. Asserts `assemble_orchestrator_decision_record` is callable. Asserts `OrchestratorDecisionServiceError` is a subclass of `ValueError`.

### test_assembler_service_does_not_import_redis.py

Spawns a fresh subprocess via `subprocess.run([sys.executable, "-c", ...])` that imports `v2.backend.app.services.orchestrator_decision` and prints a Python list of forbidden module names that appear in `sys.modules`. The forbidden names are `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env`. Asserts the printed list is empty. This is the single permitted use of `subprocess` in 2F.B test files.

### test_assembler_service_does_not_import_url_env.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.adapters.redis_v2.url_env` is NOT in `sys.modules`. The check is duplicated here as a single-token guard for clarity.

### test_assembler_service_does_not_register_fastapi_lifespan.py

Spawns a fresh subprocess that imports the assembler package and asserts that `fastapi` is NOT in `sys.modules` and that no module-level callable named `lifespan` exists in `v2.backend.app.services.orchestrator_decision`.

### test_assembler_service_forbidden_tokens.py

Reads `__init__.py`, `errors.py`, and `service.py` as text. For each forbidden token in `10_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SPEC.md` 'Forbidden tokens in source files', asserts the token does NOT appear in any of the three files. The test file constructs each forbidden literal at runtime via string concatenation so the test source file itself does not contain the bare token.

### test_errors_invariants.py

Constructs `OrchestratorDecisionServiceError("must_be_int", field="now_ms_clock")` and asserts `.code == "must_be_int"`, `.field == "now_ms_clock"`, `str(e) == "must_be_int (now_ms_clock)"`, and `isinstance(e, ValueError) is True`.

### test_assemble_keyword_only_params.py

Asserts that `assemble_orchestrator_decision_record(prediction, 0.5, lambda: 1)` (positional) raises `TypeError`. Asserts that the same call with all keyword arguments succeeds (using a happy-path long prediction and a lambda clock returning a fixed positive int).

### test_assemble_calls_clock_exactly_once.py

Constructs a counter clock that increments a list on each call and returns `1` on the first call and `999` thereafter. Calls the assembler once and asserts the counter list has length 1. Asserts the returned `decision_ts_ms == 1`.

### test_assemble_records_clock_into_decision_ts_ms.py

Constructs a clock returning a fixed `42`. Calls the assembler with a happy-path long prediction and asserts the returned record's `decision_ts_ms == 42`.

### test_assemble_decision_id_derived_from_prediction_id.py

Constructs a prediction with `prediction_id="pred_abc"`. Calls the assembler and asserts the returned record's `decision_id == "dec_pred_abc"`.

### test_assemble_rejects_non_callable_clock.py

Calls the assembler with `now_ms_clock=42` (non-callable) and asserts that `OrchestratorDecisionServiceError` is raised with `code="must_be_callable"` and `field="now_ms_clock"`.

### test_assemble_rejects_clock_returning_non_int.py

Calls the assembler with `now_ms_clock=lambda: 1.0` and asserts `OrchestratorDecisionServiceError` is raised with `code="must_be_int"` and `field="now_ms_clock"`. Also tests `lambda: True` and `lambda: "100"`.

### test_assemble_rejects_clock_returning_negative.py

Calls the assembler with `now_ms_clock=lambda: -1` and asserts `OrchestratorDecisionServiceError` is raised with `code="must_be_nonnegative"` and `field="now_ms_clock"`.

### test_assemble_rejects_low_confidence_threshold_not_float.py

Calls the assembler with `low_confidence_threshold=0` (int, not float) and asserts `OrchestratorDecisionServiceError` is raised with `code="must_be_float"` and `field="low_confidence_threshold"`. Also tests `True` (bool subclass of int) and `"0.5"`.

### test_assemble_rejects_low_confidence_threshold_not_finite.py

Calls the assembler with `low_confidence_threshold=float("inf")`, `float("-inf")`, and `float("nan")` and asserts each raises with `code="must_be_finite"` and `field="low_confidence_threshold"`.

### test_assemble_rejects_low_confidence_threshold_below_zero.py

Calls the assembler with `low_confidence_threshold=-0.0001` and asserts `code="must_be_in_unit_interval"` and `field="low_confidence_threshold"`.

### test_assemble_rejects_low_confidence_threshold_above_one.py

Calls the assembler with `low_confidence_threshold=1.0001` and asserts `code="must_be_in_unit_interval"` and `field="low_confidence_threshold"`.

### test_assemble_rejects_prediction_not_record.py

Calls the assembler with `prediction=object()` and `prediction=None` and asserts each raises `OrchestratorDecisionServiceError` with `code="must_be_trainer_prediction_record"` and `field="prediction"`.

### test_assemble_rejects_prediction_id_too_long_for_decision_id_derivation.py

Constructs a `TrainerPredictionRecord` with `prediction_id` of length 125 (one above the cap) using a 125-char alphanumeric ASCII string. Calls the assembler and asserts `OrchestratorDecisionServiceError` is raised with `code="prediction_id_too_long_for_decision_id_derivation"` and `field="prediction.prediction_id"`. Also asserts that `prediction_id` of length 124 succeeds.

### test_assemble_returns_orchestrator_decision_record.py

Calls the assembler with a happy-path long prediction and asserts the returned object is an instance of `v2.backend.app.domain.orchestrator_decision.OrchestratorDecisionRecord`.

### test_assemble_returns_frozen_record.py

Calls the assembler with a happy-path long prediction and asserts that assignment to any field of the returned record raises `dataclasses.FrozenInstanceError`.

### test_assemble_open_long.py

Constructs a fresh long prediction with `direction="long"`, `freshness_flag="fresh"`, `worker_health_status="HEALTHY"`, `confidence_calibrated=0.85`. Calls the assembler with `low_confidence_threshold=0.5` and a clock returning `1000`. Asserts `decision_action == "open_long"`, `decision_reason_code == "proceed_long"`, `decision_ts_ms == 1000`, `decision_id == "dec_" + prediction_id`, `live_blocked is True`, and the input lineage fields are propagated unchanged.

### test_assemble_open_short.py

Same as `_open_long` but with `direction="short"` and asserts `decision_action == "open_short"`, `decision_reason_code == "proceed_short"`.

### test_assemble_hold_flat.py

Same as above but with `direction="flat"` and asserts `decision_action == "hold"`, `decision_reason_code == "hold_flat_direction"`.

### test_assemble_abstain_freshness_missing.py

Constructs a prediction with `freshness_flag="missing"` and `source_freshness_age_ms=None`. The other fields are otherwise valid (e.g., `direction="long"`, `confidence_calibrated=0.9`, `worker_health_status="HEALTHY"`). Calls the assembler and asserts `decision_action == "abstain"`, `decision_reason_code == "abstain_freshness_missing"`, `live_blocked is True`.

### test_assemble_abstain_freshness_stale.py

Same as above but with `freshness_flag="stale"` and `source_freshness_age_ms=1_000_000`. Asserts `decision_reason_code == "abstain_freshness_stale"`.

### test_assemble_abstain_worker_critical.py

Constructs a prediction with `worker_health_status="CRITICAL"`, `freshness_flag="fresh"`, `direction="long"`, `confidence_calibrated=0.9`. Asserts `decision_action == "abstain"`, `decision_reason_code == "abstain_worker_critical"`.

### test_assemble_abstain_worker_degraded.py

Same as above but with `worker_health_status="DEGRADED"`. Asserts `decision_reason_code == "abstain_worker_degraded"`.

### test_assemble_abstain_worker_unknown.py

Same as above but with `worker_health_status="UNKNOWN"`. Asserts `decision_reason_code == "abstain_worker_unknown"`.

### test_assemble_abstain_low_confidence.py

Constructs a prediction with `confidence_calibrated=0.10`, `freshness_flag="fresh"`, `worker_health_status="HEALTHY"`, `direction="long"`. Calls the assembler with `low_confidence_threshold=0.5`. Asserts `decision_action == "abstain"`, `decision_reason_code == "abstain_low_confidence"`.

### test_assemble_priority_freshness_missing_over_stale.py

Constructs a prediction with `freshness_flag="missing"` and `source_freshness_age_ms=None`. Calls the assembler and asserts `decision_reason_code == "abstain_freshness_missing"` (NOT `"abstain_freshness_stale"`). Documents the priority order.

### test_assemble_priority_freshness_over_worker.py

Constructs a prediction with `freshness_flag="stale"` AND `worker_health_status="CRITICAL"`. Calls the assembler and asserts `decision_reason_code == "abstain_freshness_stale"` (freshness wins over worker health).

### test_assemble_priority_worker_over_low_confidence.py

Constructs a prediction with `freshness_flag="fresh"`, `worker_health_status="DEGRADED"`, AND `confidence_calibrated=0.05`. Calls the assembler with `low_confidence_threshold=0.5`. Asserts `decision_reason_code == "abstain_worker_degraded"` (worker health wins over low confidence).

### test_assemble_priority_low_confidence_over_action.py

Constructs a prediction with `freshness_flag="fresh"`, `worker_health_status="HEALTHY"`, `confidence_calibrated=0.05`, `direction="long"`. Calls the assembler with `low_confidence_threshold=0.5`. Asserts `decision_action == "abstain"` (NOT `"open_long"`) and `decision_reason_code == "abstain_low_confidence"`.

### test_assemble_at_threshold_is_not_low_confidence.py

Constructs a prediction with `confidence_calibrated=0.5` exactly equal to the threshold, `freshness_flag="fresh"`, `worker_health_status="HEALTHY"`, `direction="long"`. Calls the assembler with `low_confidence_threshold=0.5`. Asserts `decision_action == "open_long"` and `decision_reason_code == "proceed_long"`. The boundary value is NOT abstain.

### test_assemble_propagates_input_lineage_fields.py

Constructs a happy-path long prediction with distinct ids `prediction_id="pred_lineage_xyz"`, `feature_snapshot_id="snap_lineage_xyz"`, and `symbol="ETHUSDT"`. Calls the assembler. Asserts the returned record's `prediction_id == "pred_lineage_xyz"`, `feature_snapshot_id == "snap_lineage_xyz"`, `symbol == "ETHUSDT"`, `input_prediction_direction == "long"`, `input_prediction_confidence_calibrated == 0.85`, `input_prediction_freshness_flag == "fresh"`, `input_worker_health_status == "HEALTHY"`, and `live_blocked is True`.

PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_TEST_PLAN_READY
