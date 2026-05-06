# Phase 2H.B — Paper Execution Ledger Assembler Service Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/services/paper_execution_ledger/`. The test package marker `__init__.py` is the 29th file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 28 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_assembler_service_does_not_import_redis.py`
4. `test_assembler_service_does_not_import_url_env.py`
5. `test_assembler_service_does_not_register_fastapi_lifespan.py`
6. `test_assembler_service_forbidden_tokens.py`
7. `test_errors_invariants.py`
8. `test_assemble_keyword_only_params.py`
9. `test_assemble_calls_clock_exactly_once.py`
10. `test_assemble_records_clock_into_ledger_entry_ts_ms.py`
11. `test_assemble_paper_trade_id_derived_from_risk_decision_id.py`
12. `test_assemble_rejects_non_callable_clock.py`
13. `test_assemble_rejects_clock_returning_non_int.py`
14. `test_assemble_rejects_clock_returning_negative.py`
15. `test_assemble_rejects_decision_not_record.py`
16. `test_assemble_rejects_risk_decision_id_too_long_for_paper_trade_id_derivation.py`
17. `test_assemble_returns_paper_execution_ledger_entry.py`
18. `test_assemble_returns_frozen_record.py`
19. `test_assemble_record_allow_for_allow_proceed_long.py`
20. `test_assemble_record_allow_for_allow_proceed_short.py`
21. `test_assemble_record_deny_for_deny_orchestrator_held.py`
22. `test_assemble_record_deny_for_deny_orchestrator_abstained.py`
23. `test_assemble_record_deny_for_deny_default.py`
24. `test_assemble_propagates_input_lineage_fields.py`
25. `test_assemble_returned_record_is_live_blocked_true.py`
26. `test_assemble_input_risk_action_propagates.py`
27. `test_assemble_input_risk_reason_code_propagates.py`
28. `test_assemble_exhaustive_over_allowed_risk_reasons.py`
29. `test_assemble_satisfies_2ha_cross_field_invariants.py`

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.services.paper_execution_ledger` and asserts that `__all__` equals exactly the 2-tuple `("assemble_paper_execution_ledger_entry", "PaperExecutionLedgerServiceError")` in that order. Asserts `assemble_paper_execution_ledger_entry` is callable. Asserts `PaperExecutionLedgerServiceError` is a subclass of `ValueError`.

### test_assembler_service_does_not_import_redis.py

Spawns a fresh subprocess via `subprocess.run([sys.executable, "-c", ...])` that imports `v2.backend.app.services.paper_execution_ledger` and prints a Python list of forbidden module names that appear in `sys.modules`. The forbidden names are `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env`. Asserts the printed list is empty. This is one of the permitted uses of `subprocess` in 2H.B test files.

### test_assembler_service_does_not_import_url_env.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.adapters.redis_v2.url_env` is NOT in `sys.modules`. The check is duplicated here as a single-token guard for clarity.

### test_assembler_service_does_not_register_fastapi_lifespan.py

Spawns a fresh subprocess that imports the assembler package and asserts that `fastapi` is NOT in `sys.modules` and that no module-level callable named `lifespan` exists in `v2.backend.app.services.paper_execution_ledger`.

### test_assembler_service_forbidden_tokens.py

Reads `__init__.py`, `errors.py`, and `service.py` as text. For each forbidden token in `11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md` 'Forbidden tokens in source files', asserts the token does NOT appear in any of the three files. The test file constructs each forbidden literal at runtime via string concatenation so the test source file itself does not contain the bare token.

### test_errors_invariants.py

Constructs `PaperExecutionLedgerServiceError("must_be_int", field="now_ms_clock")` and asserts `.code == "must_be_int"`, `.field == "now_ms_clock"`, `str(e) == "must_be_int (now_ms_clock)"`, and `isinstance(e, ValueError) is True`.

### test_assemble_keyword_only_params.py

Asserts that `assemble_paper_execution_ledger_entry(decision, lambda: 1)` (positional) raises `TypeError`. Asserts that the same call with all keyword arguments succeeds (using a happy-path allow_proceed_long decision and a lambda clock returning a fixed positive int).

### test_assemble_calls_clock_exactly_once.py

Constructs a counter clock that increments a list on each call and returns `1` on the first call and `999` thereafter. Calls the assembler once and asserts the counter list has length 1. Asserts the returned `ledger_entry_ts_ms == 1`.

### test_assemble_records_clock_into_ledger_entry_ts_ms.py

Constructs a clock returning a fixed `42`. Calls the assembler with a happy-path allow_proceed_long decision and asserts the returned record's `ledger_entry_ts_ms == 42`.

### test_assemble_paper_trade_id_derived_from_risk_decision_id.py

Constructs a `RiskDecisionRecord` with `risk_decision_id="rd_dec_pred_abc"`. Calls the assembler and asserts the returned record's `paper_trade_id == "pt_rd_dec_pred_abc"`.

### test_assemble_rejects_non_callable_clock.py

Calls the assembler with `now_ms_clock=42` (non-callable) and asserts that `PaperExecutionLedgerServiceError` is raised with `code="must_be_callable"` and `field="now_ms_clock"`.

### test_assemble_rejects_clock_returning_non_int.py

Calls the assembler with `now_ms_clock=lambda: 1.0` and asserts `PaperExecutionLedgerServiceError` is raised with `code="must_be_int"` and `field="now_ms_clock"`. Also tests `lambda: True` and `lambda: "100"`.

### test_assemble_rejects_clock_returning_negative.py

Calls the assembler with `now_ms_clock=lambda: -1` and asserts `PaperExecutionLedgerServiceError` is raised with `code="must_be_nonnegative"` and `field="now_ms_clock"`.

### test_assemble_rejects_decision_not_record.py

Calls the assembler with `decision=object()` and `decision=None` and asserts each raises `PaperExecutionLedgerServiceError` with `code="must_be_risk_decision_record"` and `field="decision"`.

### test_assemble_rejects_risk_decision_id_too_long_for_paper_trade_id_derivation.py

Constructs a `RiskDecisionRecord` with `risk_decision_id` of length 126 (one above the 125 cap) using a 126-char alphanumeric ASCII string. Calls the assembler and asserts `PaperExecutionLedgerServiceError` is raised with `code="risk_decision_id_too_long_for_paper_trade_id_derivation"` and `field="decision.risk_decision_id"`. Also asserts that `risk_decision_id` of length 125 succeeds.

### test_assemble_returns_paper_execution_ledger_entry.py

Calls the assembler with a happy-path allow_proceed_long decision and asserts the returned object is an instance of `v2.backend.app.domain.paper_execution_ledger.PaperExecutionLedgerEntry`.

### test_assemble_returns_frozen_record.py

Calls the assembler with a happy-path allow_proceed_long decision and asserts that assignment to any field of the returned record raises `dataclasses.FrozenInstanceError`.

### test_assemble_record_allow_for_allow_proceed_long.py

Constructs a fresh allow_proceed_long decision with `risk_action="allow"`, `risk_reason_code="allow_proceed_long"`, `input_decision_action="open_long"`, `input_decision_reason_code="proceed_long"`. Calls the assembler with a clock returning `1000`. Asserts `ledger_action == "record_allow"`, `ledger_reason_code == "mirror_allow_proceed_long"`, `ledger_entry_ts_ms == 1000`, `paper_trade_id == "pt_" + risk_decision_id`, `live_blocked is True`, `input_risk_action == "allow"`, `input_risk_reason_code == "allow_proceed_long"`, and the input lineage fields are propagated unchanged.

### test_assemble_record_allow_for_allow_proceed_short.py

Same as `_record_allow_for_allow_proceed_long` but with `risk_reason_code="allow_proceed_short"`, `input_decision_action="open_short"`, `input_decision_reason_code="proceed_short"`. Asserts `ledger_action == "record_allow"`, `ledger_reason_code == "mirror_allow_proceed_short"`, `input_risk_reason_code == "allow_proceed_short"`.

### test_assemble_record_deny_for_deny_orchestrator_held.py

Constructs a deny_orchestrator_held decision with `risk_action="deny"`, `risk_reason_code="deny_orchestrator_held"`, `input_decision_action="hold"`, `input_decision_reason_code="hold_flat_direction"`. Asserts `ledger_action == "record_deny"`, `ledger_reason_code == "mirror_deny_orchestrator_held"`, `input_risk_action == "deny"`, `input_risk_reason_code == "deny_orchestrator_held"`, `live_blocked is True`.

### test_assemble_record_deny_for_deny_orchestrator_abstained.py

Constructs a deny_orchestrator_abstained decision with `risk_action="deny"`, `risk_reason_code="deny_orchestrator_abstained"`, `input_decision_action="abstain"`, `input_decision_reason_code="abstain_low_confidence"`. Asserts `ledger_action == "record_deny"`, `ledger_reason_code == "mirror_deny_orchestrator_abstained"`, `input_risk_reason_code == "deny_orchestrator_abstained"`.

### test_assemble_record_deny_for_deny_default.py

Constructs a deny_default decision with `risk_action="deny"`, `risk_reason_code="deny_default"`, `input_decision_action="open_long"`, `input_decision_reason_code="proceed_long"` (the 2G.A `_TRADABLE_INPUT_DECISION_ACTIONS` invariant requires a tradable input action when `risk_reason_code == "deny_default"`). Asserts `ledger_action == "record_deny"`, `ledger_reason_code == "mirror_deny_default"`, `input_risk_action == "deny"`, `input_risk_reason_code == "deny_default"`. The literal `"deny_default"` MUST NOT appear in the test source file body; the test constructs it at runtime via string concatenation.

### test_assemble_propagates_input_lineage_fields.py

Constructs a happy-path allow_proceed_long decision with distinct ids `risk_decision_id="rd_dec_lineage_xyz"`, `decision_id="dec_lineage_xyz"`, `prediction_id="pred_lineage_xyz"`, `feature_snapshot_id="snap_lineage_xyz"`, and `symbol="ETHUSDT"`. Calls the assembler. Asserts the returned record's `risk_decision_id == "rd_dec_lineage_xyz"`, `decision_id == "dec_lineage_xyz"`, `prediction_id == "pred_lineage_xyz"`, `feature_snapshot_id == "snap_lineage_xyz"`, `symbol == "ETHUSDT"`, `paper_trade_id == "pt_rd_dec_lineage_xyz"`, `input_risk_action == "allow"`, `input_risk_reason_code == "allow_proceed_long"`, and `live_blocked is True`.

### test_assemble_returned_record_is_live_blocked_true.py

Calls the assembler with a happy-path allow_proceed_long decision and asserts `returned_record.live_blocked is True` (identity check, not equality). Then asserts `returned_record.live_blocked == True` and `type(returned_record.live_blocked) is bool`.

### test_assemble_input_risk_action_propagates.py

Iterates over the two 2G.A `_ALLOWED_RISK_ACTIONS` values (`allow`, `deny`) and constructs a 2G.A-valid `RiskDecisionRecord` for each (allow paired with `allow_proceed_long`; deny paired with `deny_orchestrator_held`). Calls the assembler for each. Asserts the returned `input_risk_action` equals the input `risk_action` exactly for each row.

### test_assemble_input_risk_reason_code_propagates.py

Iterates over all five 2G.A `_ALLOWED_RISK_REASONS` values and constructs a 2G.A-valid `RiskDecisionRecord` for each (deny_default paired with `input_decision_action="open_long"` and `input_decision_reason_code="proceed_long"` to satisfy the 2G.A `_TRADABLE_INPUT_DECISION_ACTIONS` invariant). Calls the assembler for each. Asserts the returned `input_risk_reason_code` equals the input `risk_reason_code` exactly for each row.

### test_assemble_exhaustive_over_allowed_risk_reasons.py

Constructs the 5-row table of (input `risk_reason_code`, expected `ledger_action`, expected `ledger_reason_code`) explicitly:

- `("allow_proceed_long", "record_allow", "mirror_allow_proceed_long")`
- `("allow_proceed_short", "record_allow", "mirror_allow_proceed_short")`
- `("deny_orchestrator_held", "record_deny", "mirror_deny_orchestrator_held")`
- `("deny_orchestrator_abstained", "record_deny", "mirror_deny_orchestrator_abstained")`
- `("deny_default", "record_deny", "mirror_deny_default")`

For each row, constructs a 2G.A-valid `RiskDecisionRecord` (deny_default paired with a tradable input action), calls the assembler, and asserts `ledger_action` and `ledger_reason_code` match the expected values. Asserts the table covers exactly the 5 members of the 2G.A `_ALLOWED_RISK_REASONS` frozenset (length check). Constructs an unrecognized `risk_reason_code` (`"deny_unrecognized_synthetic"`) by bypassing the 2G.A invariants via `dataclasses.replace` on a frozen instance — wait, frozen instances cannot be replaced this way; instead, the test uses `object.__setattr__` to set an unrecognized `risk_reason_code` on a constructed record, then asserts the assembler raises `PaperExecutionLedgerServiceError` with `code="unrecognized_risk_reason_code"` and `field="decision.risk_reason_code"`.

### test_assemble_satisfies_2ha_cross_field_invariants.py

For each row of the 5-row mirror derivation table, constructs the corresponding 2G.A-valid `RiskDecisionRecord`, calls the assembler, captures the returned `PaperExecutionLedgerEntry`, and asserts the 2H.A cross-field invariants hold:

- If `ledger_action == "record_allow"`: `ledger_reason_code` starts with `"mirror_allow_"` and `input_risk_action == "allow"`.
- If `ledger_action == "record_deny"`: `ledger_reason_code` starts with `"mirror_deny_"` and `input_risk_action == "deny"`.
- For each row, the one-to-one mapping holds: `mirror_allow_proceed_long ↔ allow_proceed_long`, `mirror_allow_proceed_short ↔ allow_proceed_short`, `mirror_deny_orchestrator_held ↔ deny_orchestrator_held`, `mirror_deny_orchestrator_abstained ↔ deny_orchestrator_abstained`, `mirror_deny_default ↔ deny_default`.

The literal `"mirror_allow_"`, `"mirror_deny_"`, and `"deny_default"` substrings MUST NOT appear in the test source file body except as runtime string-concatenated literals.

PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_TEST_PLAN_READY
