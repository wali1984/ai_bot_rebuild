# Phase 2G.B — Risk Gateway Assembler Service GO/NO-GO Request

This document specifies the markers task `128` MUST emit and the markers the future Codex review task `129` MUST emit.

## Implementation markers (emitted by task 128)

Task `128_risk_gateway_2gb_assembler_service_implementation` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`:

- `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`
- `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED`

The companion implementation report `14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST end with the marker line `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review markers (emitted by future task 129)

Task `129_risk_gateway_2gb_assembler_service_codex_review` (NOT emitted in this turn) emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/risk_gateway_impl/17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`:

- `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`
- `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_FAIL`

The companion review report `16_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_REVIEW.md` MUST end with the marker line `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_REVIEW_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review rubric

Codex review MUST evaluate each row, mark PASS or FAIL, and cite a one-line evidence pointer for each PASS:

1. The placeholder file `v2/backend/app/services/risk_gateway.py` no longer exists in the worktree or git index.
2. The new package `v2/backend/app/services/risk_gateway/` exists with exactly `__init__.py`, `errors.py`, and `service.py`; no extra files.
3. Public surface `__all__` of `v2.backend.app.services.risk_gateway` equals exactly `("assemble_risk_decision_record", "RiskGatewayServiceError")` in that order.
4. `RiskGatewayServiceError` is a subclass of `ValueError` with the required `__init__` signature, `__str__` formatting, and `__repr__`.
5. `assemble_risk_decision_record` is keyword-only and has no default values for any parameter.
6. The function rejects a non-`OrchestratorDecisionRecord` `decision` BEFORE invoking the clock.
7. The function rejects a non-callable `now_ms_clock` BEFORE invoking it.
8. The function calls `now_ms_clock` exactly once and propagates the integer result into `risk_decision_ts_ms`.
9. The function rejects a clock returning non-`int` (including `bool` and `float`) AFTER one invocation.
10. The function rejects a clock returning a negative integer AFTER one invocation.
11. The function rejects a `decision.decision_id` of length greater than 125 with code `decision_id_too_long_for_risk_decision_id_derivation`.
12. The function derives `risk_decision_id = "rd_" + decision.decision_id` deterministically.
13. The default-deny derivation table runs in the order documented in 10 'Default-deny derivation table (ordered)'.
14. `decision_action == "open_long"` maps to `risk_action="allow"`, `risk_reason_code="allow_proceed_long"`.
15. `decision_action == "open_short"` maps to `risk_action="allow"`, `risk_reason_code="allow_proceed_short"`.
16. `decision_action == "hold"` maps to `risk_action="deny"`, `risk_reason_code="deny_orchestrator_held"`.
17. `decision_action == "abstain"` (any abstain reason) maps to `risk_action="deny"`, `risk_reason_code="deny_orchestrator_abstained"`.
18. The defensive fallback raises `RiskGatewayServiceError("unrecognized_decision_action", field="decision.decision_action")` for any decision_action outside the four 2F.A members.
19. The returned `RiskDecisionRecord` has `live_blocked=True` (literal boolean), propagates `decision.decision_id`, `decision.prediction_id`, `decision.feature_snapshot_id`, `decision.symbol`, `decision.decision_action`, and `decision.decision_reason_code` unchanged.
20. The returned record is frozen (assigning to any field raises `dataclasses.FrozenInstanceError`).
21. `service.py` imports limited to: `__future__`, `collections.abc.Callable`, the orchestrator_decision domain re-exports (the four `DECISION_ACTION_*` constants and `OrchestratorDecisionRecord`), the risk_gateway domain re-exports (`RISK_DECISION_ACTION_ALLOW`, `RISK_DECISION_ACTION_DENY`, `RISK_DECISION_REASON_ALLOW_PROCEED_LONG`, `RISK_DECISION_REASON_ALLOW_PROCEED_SHORT`, `RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED`, `RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD`, `RiskDecisionRecord`), and `.errors`.
22. `errors.py` imports limited to `__future__`.
23. `__init__.py` imports limited to `.service.assemble_risk_decision_record` and `.errors.RiskGatewayServiceError`.
24. No forbidden token from 10 'Forbidden tokens in source files' appears in any authored source file (including the reserved tokens `RISK_DECISION_REASON_DENY_DEFAULT` and `deny_default`).
25. Importing `v2.backend.app.services.risk_gateway` in a fresh subprocess does NOT load `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env`.
26. The exact 30 test files (one zero-byte `__init__.py` plus 29 test files) are present, one test function per file, no shared `conftest.py`.
27. The full test suite at `v2/backend/tests/unit/services/risk_gateway/` passes via `.venv/bin/python -m pytest -q`.
28. Cross-isolation diff is zero across all paths in `12_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md` 'Cross-isolation paths'.
29. No prior-milestone source or test file byte content is modified.
30. No 2G.A authored source or test file byte content is modified.
31. No master planner prompt edit. No supervisor task edit. No requirements inbox edit. No security edit.
32. No live behavior. No exchange action. No leverage/margin change. No deployment. No production migration.
33. No secret value or credential-shaped string in any authored file.
34. The implementation report cites function and line range for each of the six behavior contract steps in 10 'Behavior contract steps to be cited in the implementation report'.
35. The 2G.B service does NOT introduce a composition root, a paper-execution surface, an execution surface, or a FastAPI lifespan; it is a pure derivation surface.
36. The function does NOT introduce any module-level singleton, cache, or lock.
37. The placeholder file is NOT reintroduced anywhere in the worktree.
38. The regression test `test_assemble_never_emits_deny_default_for_orchestrator_inputs.py` confirms that `"deny_default"` is never emitted for any of the four 2F.A `_ALLOWED_DECISION_ACTIONS` inputs.

## Codex review out-of-scope

Codex review MUST NOT propose:

- Adding the risk gateway composition root in this milestone (that is 2G.C).
- Adding any execution-side surface, paper executor, shadow executor, or strategy library.
- Modifying any prior-milestone artifact, including 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, or any earlier file.
- Modifying any 2G.A authored source or test file.
- Adding any new lineage ID at the service layer beyond the derived `risk_decision_id`.
- Adding any FastAPI surface, Redis adapter, GPU runner, or model-loading subsystem.
- Adding any composition-root binder.
- Adding any non-trivial logic at the service layer beyond the documented validation, derivation, and propagation steps.
- Importing or emitting the reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT` in any 2G.B source file.

If Codex marks `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 29 new test files only and re-runs the implementation flow. On any safety violation, the supervisor surfaces to human attention; no autofix is permitted.

PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST_READY
