# Phase 2H.A — Paper Execution Ledger Domain Test Plan

This document enumerates the exact test files emitted by Phase 2H.A under `v2/backend/tests/unit/domain/paper_execution_ledger/`. Each test file contains exactly one test function. There is no shared `conftest.py`. All `PaperExecutionLedgerEntry` instances are constructed by keyword. No fixture, no parametrize, no shared helper module.

## Test files (exactly 31, including a zero-byte `__init__.py`)

1. `__init__.py` — zero bytes.
2. `test_public_surface.py` — verifies `__all__` of `v2.backend.app.domain.paper_execution_ledger` equals the 9-tuple from spec section "Public surface", in order, with no extras.
3. `test_init_module_does_not_load_redis.py` — runs a subprocess `python -c "import sys; import v2.backend.app.domain.paper_execution_ledger; assert 'redis' not in sys.modules and 'redis.asyncio' not in sys.modules and 'aioredis' not in sys.modules and 'hiredis' not in sys.modules"`; asserts return code 0.
4. `test_init_module_does_not_load_url_env.py` — subprocess assertion that `'v2.backend.app.adapters.redis_v2.url_env'` is NOT in `sys.modules` after import.
5. `test_init_module_does_not_register_fastapi_lifespan.py` — subprocess assertion that `'fastapi'`, `'uvicorn'`, and `'starlette'` are NOT in `sys.modules` after import.
6. `test_record_module_does_not_load_redis_when_imported.py` — subprocess assertion that importing `v2.backend.app.domain.paper_execution_ledger.record` directly does NOT load redis/aioredis/hiredis.
7. `test_domain_module_does_not_import_risk_gateway.py` — subprocess assertion that `'v2.backend.app.domain.risk_gateway'` is NOT in `sys.modules` after importing the paper-ledger package.
8. `test_domain_module_does_not_import_orchestrator_decision.py` — subprocess assertion that `'v2.backend.app.domain.orchestrator_decision'` is NOT in `sys.modules` after importing the paper-ledger package.
9. `test_domain_module_does_not_import_trainer_prediction_output.py` — subprocess assertion that `'v2.backend.app.domain.trainer_prediction_output'` is NOT in `sys.modules` after importing the paper-ledger package.
10. `test_forbidden_tokens_not_present.py` — for each forbidden token enumerated in spec section "Forbidden tokens in source files", reads the three authored source files via `pathlib.Path.read_text` and asserts the token (constructed at runtime via string concatenation) is NOT a substring. One token per assertion. The test file does NOT contain the bare forbidden token literals.
11. `test_action_constants_lowercase_and_unique.py` — asserts both ledger-action constants equal their own `.lower()`, are non-empty `str`, and the 2-tuple `(PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_ACTION_RECORD_DENY)` has 2 distinct members.
12. `test_reason_constants_lowercase_and_unique.py` — asserts all five mirror-reason constants equal their own `.lower()`, are non-empty `str`, and the 5-tuple has 5 distinct members.
13. `test_reason_constants_carry_correct_prefix.py` — asserts every `PAPER_LEDGER_REASON_MIRROR_ALLOW_*` value starts with `"mirror_allow_"` and every `PAPER_LEDGER_REASON_MIRROR_DENY_*` value starts with `"mirror_deny_"`.
14. `test_record_constructs_with_valid_inputs_record_allow_long.py` — constructs an entry with `ledger_action="record_allow"`, `ledger_reason_code="mirror_allow_proceed_long"`, `input_risk_action="allow"`, `input_risk_reason_code="allow_proceed_long"`, `live_blocked=True`; asserts no exception and field round-trip.
15. `test_record_constructs_with_valid_inputs_record_allow_short.py` — constructs an entry with `ledger_reason_code="mirror_allow_proceed_short"` and matching upstream; asserts success.
16. `test_record_constructs_with_valid_inputs_record_deny_orchestrator_held.py` — constructs an entry with `ledger_action="record_deny"`, `ledger_reason_code="mirror_deny_orchestrator_held"`, `input_risk_action="deny"`, `input_risk_reason_code="deny_orchestrator_held"`, `live_blocked=True`; asserts success.
17. `test_record_constructs_with_valid_inputs_record_deny_orchestrator_abstained.py` — analogous for `mirror_deny_orchestrator_abstained` / `deny_orchestrator_abstained`; asserts success.
18. `test_record_constructs_with_valid_inputs_record_deny_default.py` — analogous for `mirror_deny_default` / `deny_default`; asserts success.
19. `test_record_rejects_empty_paper_trade_id.py` — asserts `PaperExecutionLedgerDomainError` with `field == "paper_trade_id"` when `paper_trade_id == ""`.
20. `test_record_rejects_whitespace_paper_trade_id.py` — asserts `PaperExecutionLedgerDomainError` with `field == "paper_trade_id"` when `paper_trade_id` contains internal whitespace.
21. `test_record_rejects_too_long_paper_trade_id.py` — asserts `PaperExecutionLedgerDomainError` with `field == "paper_trade_id"` when `len(paper_trade_id) == 129`.
22. `test_record_rejects_invalid_symbol_lowercase.py` — asserts `PaperExecutionLedgerDomainError` with `field == "symbol"` when `symbol == "btcusdt"`.
23. `test_record_rejects_negative_ledger_entry_ts_ms.py` — asserts `PaperExecutionLedgerDomainError` with `field == "ledger_entry_ts_ms"` when `ledger_entry_ts_ms == -1`.
24. `test_record_rejects_bool_for_ledger_entry_ts_ms.py` — asserts `PaperExecutionLedgerDomainError` with `field == "ledger_entry_ts_ms"` when `ledger_entry_ts_ms is True` (bool subclass of int must be rejected).
25. `test_record_rejects_unknown_ledger_action.py` — asserts `PaperExecutionLedgerDomainError` with `field == "ledger_action"` when `ledger_action == "record_skip"`.
26. `test_record_rejects_unknown_ledger_reason_code.py` — asserts `PaperExecutionLedgerDomainError` with `field == "ledger_reason_code"` when `ledger_reason_code == "mirror_unknown"`.
27. `test_record_rejects_record_allow_with_mirror_deny_reason.py` — asserts `PaperExecutionLedgerDomainError` with `reason == "record_allow_requires_mirror_allow_prefix_reason"` when `ledger_action == "record_allow"` and `ledger_reason_code == "mirror_deny_orchestrator_held"`.
28. `test_record_rejects_record_deny_with_mirror_allow_reason.py` — asserts `PaperExecutionLedgerDomainError` with `reason == "record_deny_requires_mirror_deny_prefix_reason"` when `ledger_action == "record_deny"` and `ledger_reason_code == "mirror_allow_proceed_long"`.
29. `test_record_rejects_mirror_allow_proceed_long_with_wrong_input_reason.py` — asserts `PaperExecutionLedgerDomainError` with `reason == "mirror_allow_proceed_long_requires_allow_proceed_long_input_reason"` when `ledger_reason_code == "mirror_allow_proceed_long"` but `input_risk_reason_code == "allow_proceed_short"`.
30. `test_record_rejects_mirror_deny_default_with_wrong_input_reason.py` — asserts `PaperExecutionLedgerDomainError` with `reason == "mirror_deny_default_requires_deny_default_input_reason"` when `ledger_reason_code == "mirror_deny_default"` but `input_risk_reason_code == "deny_orchestrator_held"`.
31. `test_record_rejects_live_blocked_false.py` — asserts `PaperExecutionLedgerDomainError` with `reason == "paper_ledger_requires_live_blocked_true"` and `field == "live_blocked"` when `live_blocked == False`.

## Properties enforced across the suite

- Frozen dataclass: a separate assertion inside `test_record_constructs_with_valid_inputs_record_allow_long.py` attempts `entry.paper_trade_id = "x"` and expects `dataclasses.FrozenInstanceError`.
- Slotted dataclass: the same valid-construction tests assert that `entry.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
- Keyword-only construction: every test constructs via keyword.
- No shared `conftest.py`, no parametrize, no shared helper module. One test function per file.

## Validation commands the implementation task MUST run and capture

- `.venv/bin/python -m py_compile v2/backend/app/domain/paper_execution_ledger/__init__.py v2/backend/app/domain/paper_execution_ledger/errors.py v2/backend/app/domain/paper_execution_ledger/record.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` (must remain green)
- For each forbidden token T from spec section "Forbidden tokens in source files": `rg --fixed-strings --case-sensitive T v2/backend/app/domain/paper_execution_ledger/` (must show zero matches per token; the test file uses runtime string concatenation so it does not contain the bare token)

PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_TEST_PLAN_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/03_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_TEST_PLAN.md
