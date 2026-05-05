# Phase 2G.A — Risk Gateway Domain Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/domain/risk_gateway/`. The test package marker `__init__.py` is the 32nd file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 31 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_risk_decision_action_constants.py`
4. `test_risk_decision_reason_constants.py`
5. `test_errors_invariants.py`
6. `test_record_frozen.py`
7. `test_record_happy_path_allow_proceed_long.py`
8. `test_record_happy_path_allow_proceed_short.py`
9. `test_record_happy_path_deny_orchestrator_abstained.py`
10. `test_record_happy_path_deny_orchestrator_held.py`
11. `test_record_happy_path_deny_default_open_long_input.py`
12. `test_record_happy_path_deny_default_open_short_input.py`
13. `test_record_invariants_risk_decision_id_charset_and_length.py`
14. `test_record_invariants_risk_decision_id_non_empty.py`
15. `test_record_invariants_decision_id.py`
16. `test_record_invariants_prediction_id.py`
17. `test_record_invariants_feature_snapshot_id.py`
18. `test_record_invariants_symbol_uppercase_and_charset.py`
19. `test_record_invariants_risk_decision_ts_ms.py`
20. `test_record_invariants_risk_action_in_allowed.py`
21. `test_record_invariants_risk_reason_code_in_allowed.py`
22. `test_record_invariants_input_decision_action_in_allowed.py`
23. `test_record_invariants_input_decision_reason_code_in_allowed.py`
24. `test_record_invariants_live_blocked_must_be_true.py`
25. `test_record_invariants_allow_requires_allow_prefix_reason.py`
26. `test_record_invariants_deny_requires_deny_prefix_reason.py`
27. `test_record_invariants_allow_proceed_long_requires_open_long_input.py`
28. `test_record_invariants_allow_proceed_short_requires_open_short_input.py`
29. `test_record_invariants_deny_orchestrator_abstained_requires_abstain_input.py`
30. `test_record_invariants_deny_orchestrator_held_requires_hold_input.py`
31. `test_record_invariants_deny_default_requires_tradable_input.py`
32. `test_risk_gateway_domain_does_not_import_redis.py`
33. `test_risk_gateway_domain_forbidden_tokens.py`

(Files 1 through 33 above; the package marker `__init__.py` is the 32nd in alphabetical order but is named first here for orientation. The required_output_files list in task 126 enumerates all 33 files.)

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.domain.risk_gateway` and asserts that `__all__` equals exactly the 9-tuple in spec order. Asserts each name resolves to the expected object: `RiskGatewayDomainError` is a subclass of `ValueError`; `RiskDecisionRecord` is a frozen dataclass with `__dataclass_fields__`; the two action constants and five reason constants are `str`.

### test_risk_decision_action_constants.py

Asserts the two action constants equal `"allow"` and `"deny"` exactly. Asserts they are pairwise distinct.

### test_risk_decision_reason_constants.py

Asserts each of the five reason constants equals its expected literal. Asserts pairwise distinctness. Asserts every `RISK_DECISION_REASON_ALLOW_*` starts with `"allow_"`. Asserts every `RISK_DECISION_REASON_DENY_*` starts with `"deny_"`.

### test_errors_invariants.py

Constructs `RiskGatewayDomainError("must_be_int")` and asserts `.reason == "must_be_int"`, `.field is None`, `str(e) == "must_be_int"`, and `isinstance(e, ValueError) is True`. Constructs `RiskGatewayDomainError("must_be_int", field="risk_decision_ts_ms")` and asserts `.field == "risk_decision_ts_ms"`, `str(e) == "risk_decision_ts_ms: must_be_int"`.

### test_record_frozen.py

Constructs a happy-path record. Asserts assignment to any field raises `dataclasses.FrozenInstanceError`. Asserts `__slots__` is present on the class.

### test_record_happy_path_allow_proceed_long.py

Constructs a happy-path record with `risk_action=RISK_DECISION_ACTION_ALLOW`, `risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG`, `input_decision_action="open_long"`, `input_decision_reason_code="proceed_long"`, `live_blocked=True`. Asserts no exception is raised. Asserts each field is preserved by reading back the attribute.

### test_record_happy_path_allow_proceed_short.py

Same as `_allow_proceed_long` but with the short side: `RISK_DECISION_REASON_ALLOW_PROCEED_SHORT`, `input_decision_action="open_short"`, `input_decision_reason_code="proceed_short"`.

### test_record_happy_path_deny_orchestrator_abstained.py

Constructs a deny record with `risk_action=RISK_DECISION_ACTION_DENY`, `risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED`, `input_decision_action="abstain"`, `input_decision_reason_code` set to one of `"abstain_low_confidence"`, `"abstain_freshness_stale"`, `"abstain_freshness_missing"`, `"abstain_worker_degraded"`, `"abstain_worker_critical"`, or `"abstain_worker_unknown"` (the test picks one and documents the choice). Asserts no exception.

### test_record_happy_path_deny_orchestrator_held.py

Constructs a deny record with `risk_action=RISK_DECISION_ACTION_DENY`, `risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD`, `input_decision_action="hold"`, `input_decision_reason_code="hold_flat_direction"`. Asserts no exception.

### test_record_happy_path_deny_default_open_long_input.py

Constructs a deny record with `risk_action=RISK_DECISION_ACTION_DENY`, `risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT`, `input_decision_action="open_long"`, `input_decision_reason_code="proceed_long"`. Asserts no exception. (This locks in that a tradable orchestrator action can be denied by default-deny without requiring a specific upstream rejection reason.)

### test_record_happy_path_deny_default_open_short_input.py

Mirror of the open-long test for the short side.

### test_record_invariants_risk_decision_id_charset_and_length.py

Asserts each of the following inputs raises `RiskGatewayDomainError` with `field="risk_decision_id"`:
- non-string (e.g., `42`) → reason `must_be_str`
- empty `""` → reason `must_be_non_empty`
- leading/trailing whitespace `" abc"` → reason `must_not_have_whitespace`
- internal whitespace `"a b"` → reason `must_not_have_whitespace`
- length 129 → reason `must_be_at_most_128_chars`

### test_record_invariants_risk_decision_id_non_empty.py

Tests the explicit empty-string rejection separately to lock in the message.

### test_record_invariants_decision_id.py

Same charset and length matrix as `risk_decision_id`, with `field="decision_id"`.

### test_record_invariants_prediction_id.py

Same charset and length matrix as `risk_decision_id`, with `field="prediction_id"`.

### test_record_invariants_feature_snapshot_id.py

Same charset and length matrix as `risk_decision_id`, with `field="feature_snapshot_id"`.

### test_record_invariants_symbol_uppercase_and_charset.py

Asserts non-string raises with reason `must_be_str`; empty raises `must_be_non_empty`; whitespace raises `must_not_have_whitespace`; length 33 raises `must_be_at_most_32_chars`; lowercase `"btcusdt"` raises `must_be_uppercase`.

### test_record_invariants_risk_decision_ts_ms.py

Asserts non-int (e.g., `1.0`, `"100"`, `True`, `False`) raises with reason `must_be_int`. Asserts `-1` raises `must_be_nonnegative`. Asserts `0` is accepted in a happy-path construction.

### test_record_invariants_risk_action_in_allowed.py

Asserts the literal `"ALLOW"` (uppercase), the literal `"abstain"`, and the literal `""` each raise `RiskGatewayDomainError` with `field="risk_action"` and reason `invalid_risk_action`. Asserts a non-string `42` raises `must_be_str`.

### test_record_invariants_risk_reason_code_in_allowed.py

Asserts an unrecognized reason code (e.g., `"allow_neutral"`) raises with reason `invalid_risk_reason_code` and `field="risk_reason_code"`. Asserts non-string raises `must_be_str`.

### test_record_invariants_input_decision_action_in_allowed.py

Asserts an unrecognized action (e.g., `"sideways"`) raises `invalid_input_decision_action` with `field="input_decision_action"`. Asserts non-string raises `must_be_str`.

### test_record_invariants_input_decision_reason_code_in_allowed.py

Asserts an unrecognized reason (e.g., `"proceed_neutral"`) raises `invalid_input_decision_reason_code` with `field="input_decision_reason_code"`. Asserts non-string raises `must_be_str`.

### test_record_invariants_live_blocked_must_be_true.py

Asserts `live_blocked=False` raises `RiskGatewayDomainError("must_be_true", field="live_blocked")`. Asserts `live_blocked=1` (or any non-bool) raises `must_be_bool`.

### test_record_invariants_allow_requires_allow_prefix_reason.py

Asserts `risk_action=RISK_DECISION_ACTION_ALLOW` paired with `risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT` raises `allow_requires_allow_prefix_reason` with `field="risk_reason_code"`.

### test_record_invariants_deny_requires_deny_prefix_reason.py

Asserts `risk_action=RISK_DECISION_ACTION_DENY` paired with `risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG` raises `deny_requires_deny_prefix_reason` with `field="risk_reason_code"`.

### test_record_invariants_allow_proceed_long_requires_open_long_input.py

Asserts `risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG` paired with `input_decision_action="open_short"` raises `allow_proceed_long_requires_open_long_input` with `field="input_decision_action"`. Asserts the same reason paired with `input_decision_action="open_long"` and `input_decision_reason_code="proceed_short"` raises `allow_proceed_long_requires_proceed_long_input_reason` with `field="input_decision_reason_code"`.

### test_record_invariants_allow_proceed_short_requires_open_short_input.py

Mirror of the `_allow_proceed_long` test for the short side.

### test_record_invariants_deny_orchestrator_abstained_requires_abstain_input.py

Asserts `risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED` paired with `input_decision_action="hold"` raises `deny_orchestrator_abstained_requires_abstain_input` with `field="input_decision_action"`.

### test_record_invariants_deny_orchestrator_held_requires_hold_input.py

Asserts `risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD` paired with `input_decision_action="abstain"` raises `deny_orchestrator_held_requires_hold_input` with `field="input_decision_action"`.

### test_record_invariants_deny_default_requires_tradable_input.py

Asserts `risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT` paired with `input_decision_action="hold"` raises `deny_default_requires_tradable_input` with `field="input_decision_action"`. Asserts the same reason paired with `input_decision_action="abstain"` also raises `deny_default_requires_tradable_input`. Asserts the same reason paired with `input_decision_action="open_long"` and `input_decision_action="open_short"` each construct successfully.

### test_risk_gateway_domain_does_not_import_redis.py

Imports `v2.backend.app.domain.risk_gateway` in a fresh subprocess via `subprocess.run([sys.executable, "-c", code])`, then asserts `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env` are NOT in `sys.modules`. The subprocess invocation is the only `subprocess` call in the test suite and is permitted only inside this test file.

### test_risk_gateway_domain_forbidden_tokens.py

Reads each authored source file as text and asserts none of the forbidden tokens listed in `02_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SPEC.md` appear in the file contents. The forbidden-token literals are constructed at runtime via string concatenation so the test file itself does not contain the bare tokens.

PHASE2G_A_RISK_GATEWAY_DOMAIN_TEST_PLAN_READY
