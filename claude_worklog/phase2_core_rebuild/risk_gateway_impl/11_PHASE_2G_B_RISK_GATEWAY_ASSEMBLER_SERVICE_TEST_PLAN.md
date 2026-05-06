# Phase 2G.B — Risk Gateway Assembler Service Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/services/risk_gateway/`. The test package marker `__init__.py` is the 30th file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 29 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_assembler_service_does_not_import_redis.py`
4. `test_assembler_service_does_not_import_url_env.py`
5. `test_assembler_service_does_not_register_fastapi_lifespan.py`
6. `test_assembler_service_forbidden_tokens.py`
7. `test_errors_invariants.py`
8. `test_assemble_keyword_only_params.py`
9. `test_assemble_calls_clock_exactly_once.py`
10. `test_assemble_records_clock_into_risk_decision_ts_ms.py`
11. `test_assemble_risk_decision_id_derived_from_decision_id.py`
12. `test_assemble_rejects_non_callable_clock.py`
13. `test_assemble_rejects_clock_returning_non_int.py`
14. `test_assemble_rejects_clock_returning_negative.py`
15. `test_assemble_rejects_decision_not_record.py`
16. `test_assemble_rejects_decision_id_too_long_for_risk_decision_id_derivation.py`
17. `test_assemble_returns_risk_decision_record.py`
18. `test_assemble_returns_frozen_record.py`
19. `test_assemble_allow_open_long.py`
20. `test_assemble_allow_open_short.py`
21. `test_assemble_deny_orchestrator_held_for_hold.py`
22. `test_assemble_deny_orchestrator_abstained_for_abstain_low_confidence.py`
23. `test_assemble_deny_orchestrator_abstained_for_abstain_freshness_missing.py`
24. `test_assemble_deny_orchestrator_abstained_for_abstain_freshness_stale.py`
25. `test_assemble_deny_orchestrator_abstained_for_abstain_worker_critical.py`
26. `test_assemble_deny_orchestrator_abstained_for_abstain_worker_degraded.py`
27. `test_assemble_deny_orchestrator_abstained_for_abstain_worker_unknown.py`
28. `test_assemble_propagates_input_lineage_fields.py`
29. `test_assemble_returned_record_is_live_blocked_true.py`
30. `test_assemble_never_emits_deny_default_for_orchestrator_inputs.py`

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.services.risk_gateway` and asserts that `__all__` equals exactly the 2-tuple `("assemble_risk_decision_record", "RiskGatewayServiceError")` in that order. Asserts `assemble_risk_decision_record` is callable. Asserts `RiskGatewayServiceError` is a subclass of `ValueError`.

### test_assembler_service_does_not_import_redis.py

Spawns a fresh subprocess via `subprocess.run([sys.executable, "-c", ...])` that imports `v2.backend.app.services.risk_gateway` and prints a Python list of forbidden module names that appear in `sys.modules`. The forbidden names are `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env`. Asserts the printed list is empty. This is one of the permitted uses of `subprocess` in 2G.B test files.

### test_assembler_service_does_not_import_url_env.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.adapters.redis_v2.url_env` is NOT in `sys.modules`. The check is duplicated here as a single-token guard for clarity.

### test_assembler_service_does_not_register_fastapi_lifespan.py

Spawns a fresh subprocess that imports the assembler package and asserts that `fastapi` is NOT in `sys.modules` and that no module-level callable named `lifespan` exists in `v2.backend.app.services.risk_gateway`.

### test_assembler_service_forbidden_tokens.py

Reads `__init__.py`, `errors.py`, and `service.py` as text. For each forbidden token in `10_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC.md` 'Forbidden tokens in source files', asserts the token does NOT appear in any of the three files. The test file constructs each forbidden literal at runtime via string concatenation so the test source file itself does not contain the bare token.

### test_errors_invariants.py

Constructs `RiskGatewayServiceError("must_be_int", field="now_ms_clock")` and asserts `.code == "must_be_int"`, `.field == "now_ms_clock"`, `str(e) == "must_be_int (now_ms_clock)"`, and `isinstance(e, ValueError) is True`.

### test_assemble_keyword_only_params.py

Asserts that `assemble_risk_decision_record(decision, lambda: 1)` (positional) raises `TypeError`. Asserts that the same call with all keyword arguments succeeds (using a happy-path open-long decision and a lambda clock returning a fixed positive int).

### test_assemble_calls_clock_exactly_once.py

Constructs a counter clock that increments a list on each call and returns `1` on the first call and `999` thereafter. Calls the assembler once and asserts the counter list has length 1. Asserts the returned `risk_decision_ts_ms == 1`.

### test_assemble_records_clock_into_risk_decision_ts_ms.py

Constructs a clock returning a fixed `42`. Calls the assembler with a happy-path open-long decision and asserts the returned record's `risk_decision_ts_ms == 42`.

### test_assemble_risk_decision_id_derived_from_decision_id.py

Constructs an orchestrator decision with `decision_id="dec_pred_abc"`. Calls the assembler and asserts the returned record's `risk_decision_id == "rd_dec_pred_abc"`.

### test_assemble_rejects_non_callable_clock.py

Calls the assembler with `now_ms_clock=42` (non-callable) and asserts that `RiskGatewayServiceError` is raised with `code="must_be_callable"` and `field="now_ms_clock"`.

### test_assemble_rejects_clock_returning_non_int.py

Calls the assembler with `now_ms_clock=lambda: 1.0` and asserts `RiskGatewayServiceError` is raised with `code="must_be_int"` and `field="now_ms_clock"`. Also tests `lambda: True` and `lambda: "100"`.

### test_assemble_rejects_clock_returning_negative.py

Calls the assembler with `now_ms_clock=lambda: -1` and asserts `RiskGatewayServiceError` is raised with `code="must_be_nonnegative"` and `field="now_ms_clock"`.

### test_assemble_rejects_decision_not_record.py

Calls the assembler with `decision=object()` and `decision=None` and asserts each raises `RiskGatewayServiceError` with `code="must_be_orchestrator_decision_record"` and `field="decision"`.

### test_assemble_rejects_decision_id_too_long_for_risk_decision_id_derivation.py

Constructs an `OrchestratorDecisionRecord` with `decision_id` of length 126 (one above the 125 cap) using a 126-char alphanumeric ASCII string. Calls the assembler and asserts `RiskGatewayServiceError` is raised with `code="decision_id_too_long_for_risk_decision_id_derivation"` and `field="decision.decision_id"`. Also asserts that `decision_id` of length 125 succeeds.

### test_assemble_returns_risk_decision_record.py

Calls the assembler with a happy-path open-long decision and asserts the returned object is an instance of `v2.backend.app.domain.risk_gateway.RiskDecisionRecord`.

### test_assemble_returns_frozen_record.py

Calls the assembler with a happy-path open-long decision and asserts that assignment to any field of the returned record raises `dataclasses.FrozenInstanceError`.

### test_assemble_allow_open_long.py

Constructs a fresh open-long decision with `decision_action="open_long"`, `decision_reason_code="proceed_long"`, `input_prediction_direction="long"`, `input_prediction_confidence_calibrated=0.85`, `input_prediction_freshness_flag="fresh"`, `input_worker_health_status="HEALTHY"`. Calls the assembler with a clock returning `1000`. Asserts `risk_action == "allow"`, `risk_reason_code == "allow_proceed_long"`, `risk_decision_ts_ms == 1000`, `risk_decision_id == "rd_" + decision_id`, `live_blocked is True`, `input_decision_action == "open_long"`, `input_decision_reason_code == "proceed_long"`, and the input lineage fields are propagated unchanged.

### test_assemble_allow_open_short.py

Same as `_allow_open_long` but with `decision_action="open_short"`, `decision_reason_code="proceed_short"`, `input_prediction_direction="short"`. Asserts `risk_action == "allow"`, `risk_reason_code == "allow_proceed_short"`, `input_decision_action == "open_short"`, `input_decision_reason_code == "proceed_short"`.

### test_assemble_deny_orchestrator_held_for_hold.py

Constructs a hold decision with `decision_action="hold"`, `decision_reason_code="hold_flat_direction"`, `input_prediction_direction="flat"`. Asserts `risk_action == "deny"`, `risk_reason_code == "deny_orchestrator_held"`, `input_decision_action == "hold"`, `input_decision_reason_code == "hold_flat_direction"`, `live_blocked is True`.

### test_assemble_deny_orchestrator_abstained_for_abstain_low_confidence.py

Constructs an abstain decision with `decision_action="abstain"`, `decision_reason_code="abstain_low_confidence"`, `input_prediction_direction="long"`, `input_prediction_confidence_calibrated=0.05`. Asserts `risk_action == "deny"`, `risk_reason_code == "deny_orchestrator_abstained"`, `input_decision_action == "abstain"`, `input_decision_reason_code == "abstain_low_confidence"`.

### test_assemble_deny_orchestrator_abstained_for_abstain_freshness_missing.py

Same as above but with `decision_reason_code="abstain_freshness_missing"` and `input_prediction_freshness_flag="missing"`. Asserts `risk_action == "deny"`, `risk_reason_code == "deny_orchestrator_abstained"`, `input_decision_reason_code == "abstain_freshness_missing"`.

### test_assemble_deny_orchestrator_abstained_for_abstain_freshness_stale.py

Same as above but with `decision_reason_code="abstain_freshness_stale"` and `input_prediction_freshness_flag="stale"`. Asserts `input_decision_reason_code == "abstain_freshness_stale"`.

### test_assemble_deny_orchestrator_abstained_for_abstain_worker_critical.py

Same as above but with `decision_reason_code="abstain_worker_critical"` and `input_worker_health_status="CRITICAL"`. Asserts `input_decision_reason_code == "abstain_worker_critical"`.

### test_assemble_deny_orchestrator_abstained_for_abstain_worker_degraded.py

Same as above but with `decision_reason_code="abstain_worker_degraded"` and `input_worker_health_status="DEGRADED"`. Asserts `input_decision_reason_code == "abstain_worker_degraded"`.

### test_assemble_deny_orchestrator_abstained_for_abstain_worker_unknown.py

Same as above but with `decision_reason_code="abstain_worker_unknown"` and `input_worker_health_status="UNKNOWN"`. Asserts `input_decision_reason_code == "abstain_worker_unknown"`.

### test_assemble_propagates_input_lineage_fields.py

Constructs a happy-path open-long decision with distinct ids `decision_id="dec_lineage_xyz"`, `prediction_id="pred_lineage_xyz"`, `feature_snapshot_id="snap_lineage_xyz"`, and `symbol="ETHUSDT"`. Calls the assembler. Asserts the returned record's `decision_id == "dec_lineage_xyz"`, `prediction_id == "pred_lineage_xyz"`, `feature_snapshot_id == "snap_lineage_xyz"`, `symbol == "ETHUSDT"`, `risk_decision_id == "rd_dec_lineage_xyz"`, `input_decision_action == "open_long"`, `input_decision_reason_code == "proceed_long"`, and `live_blocked is True`.

### test_assemble_returned_record_is_live_blocked_true.py

Calls the assembler with a happy-path open-long decision and asserts `returned_record.live_blocked is True` (identity check, not equality). Then asserts `returned_record.live_blocked == True` and `type(returned_record.live_blocked) is bool`.

### test_assemble_never_emits_deny_default_for_orchestrator_inputs.py

Iterates over the four 2F.A `_ALLOWED_DECISION_ACTIONS` values and constructs a 2F.A-valid `OrchestratorDecisionRecord` for each (open_long → proceed_long; open_short → proceed_short; hold → hold_flat_direction; abstain → abstain_low_confidence). Calls the assembler for each. Asserts the returned `risk_reason_code` is NEVER equal to the literal string constructed at runtime as `"deny" + "_" + "default"`. The test asserts the assembler emits `allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_held`, and `deny_orchestrator_abstained` exactly, in that order. The literal `"deny_default"` MUST NOT appear in the test source file body; the test constructs it at runtime via string concatenation so the test source file does not contain the bare token.

PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_TEST_PLAN_READY
