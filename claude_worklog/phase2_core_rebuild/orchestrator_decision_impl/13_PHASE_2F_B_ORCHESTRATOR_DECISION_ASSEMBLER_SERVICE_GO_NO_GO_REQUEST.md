# Phase 2F.B — Orchestrator Decision Assembler Service GO/NO-GO Request

This document specifies the markers Codex review at task `120` MUST emit and the markers the implementation task `119` MUST emit.

## Implementation markers (emitted by task 119)

Task `119_orchestrator_decision_2fb_assembler_service_implementation` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md`:

- `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`
- `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED`

The companion implementation report `14_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` MUST end with the marker line `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review markers (emitted by task 120)

Task `120_orchestrator_decision_2fb_assembler_service_codex_review` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/17_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`:

- `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS`
- `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_FAIL`

The companion review report `16_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_REVIEW.md` MUST end with the marker line `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_REVIEW_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review rubric

Codex review MUST evaluate each row, mark PASS or FAIL, and cite a one-line evidence pointer for each PASS:

1. The placeholder file `v2/backend/app/services/orchestrator_decision.py` no longer exists in the worktree or git index.
2. The new package `v2/backend/app/services/orchestrator_decision/` exists with exactly `__init__.py`, `errors.py`, and `service.py`; no extra files.
3. Public surface `__all__` of `v2.backend.app.services.orchestrator_decision` equals exactly `("assemble_orchestrator_decision_record", "OrchestratorDecisionServiceError")` in that order.
4. `OrchestratorDecisionServiceError` is a subclass of `ValueError` with the required `__init__` signature, `__str__` formatting, and `__repr__`.
5. `assemble_orchestrator_decision_record` is keyword-only and has no default values for any parameter.
6. The function rejects a non-`TrainerPredictionRecord` `prediction` BEFORE invoking the clock.
7. The function rejects a non-`float` `low_confidence_threshold` (including `bool`) BEFORE invoking the clock.
8. The function rejects a non-finite `low_confidence_threshold` BEFORE invoking the clock.
9. The function rejects a `low_confidence_threshold` outside `[0.0, 1.0]` BEFORE invoking the clock.
10. The function rejects a non-callable `now_ms_clock` BEFORE invoking it.
11. The function calls `now_ms_clock` exactly once and propagates the integer result into `decision_ts_ms`.
12. The function rejects a clock returning non-`int` (including `bool` and `float`) AFTER one invocation.
13. The function rejects a clock returning a negative integer AFTER one invocation.
14. The function rejects a `prediction.prediction_id` of length greater than 124 with code `prediction_id_too_long_for_decision_id_derivation`.
15. The function derives `decision_id = "dec_" + prediction.prediction_id` deterministically.
16. The default-deny derivation table runs in the order documented in 10 'Default-deny derivation table (ordered)'.
17. `freshness_flag == "missing"` wins over `freshness_flag == "stale"` (priority is enforced by ordered match, not by truth-table reduction).
18. `freshness_flag` checks win over `worker_health_status` checks.
19. `worker_health_status` checks win over `confidence_calibrated < threshold`.
20. `confidence_calibrated < threshold` wins over the action-by-direction branches.
21. `confidence_calibrated == threshold` is NOT abstain-low-confidence (boundary-inclusive).
22. `direction == "flat"` (after passing all abstain gates) maps to `hold` / `hold_flat_direction`.
23. `direction == "long"` (after passing all abstain gates) maps to `open_long` / `proceed_long`.
24. `direction == "short"` (after passing all abstain gates) maps to `open_short` / `proceed_short`.
25. The returned `OrchestratorDecisionRecord` has `live_blocked=True` (literal boolean), propagates `prediction.prediction_id`, `prediction.feature_snapshot_id`, `prediction.symbol`, `prediction.direction`, `prediction.confidence_calibrated`, `prediction.freshness_flag`, and `prediction.worker_health_status` unchanged.
26. The returned record is frozen (assigning to any field raises `dataclasses.FrozenInstanceError`).
27. `service.py` imports limited to: `__future__`, `math`, `collections.abc.Callable`, the orchestrator_decision domain re-exports, the trainer_prediction_output domain re-exports, and `.errors`.
28. `errors.py` imports limited to `__future__`.
29. `__init__.py` imports limited to `.service.assemble_orchestrator_decision_record` and `.errors.OrchestratorDecisionServiceError`.
30. No forbidden token from 10 'Forbidden tokens in source files' appears in any authored source file.
31. Importing `v2.backend.app.services.orchestrator_decision` in a fresh subprocess does NOT load `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env`.
32. The exact 37 test files (one zero-byte `__init__.py` plus 36 test files) are present, one test function per file, no shared `conftest.py`.
33. The full test suite at `v2/backend/tests/unit/services/orchestrator_decision/` passes via `.venv/bin/python -m pytest -q`.
34. Cross-isolation diff is zero across all paths in `12_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md` 'Cross-isolation paths'.
35. No prior-milestone source or test file byte content is modified.
36. No 2F.A authored source or test file byte content is modified.
37. No master planner prompt edit. No supervisor task edit. No requirements inbox edit. No security edit.
38. No live behavior. No exchange action. No leverage/margin change. No deployment. No production migration.
39. No secret value or credential-shaped string in any authored file.
40. The implementation report cites function and line range for each of the six behavior contract steps in 10 'Behavior contract steps to be cited in the implementation report'.
41. The 2F.B service does NOT introduce a composition root, a risk-gateway hop, an execution surface, or a FastAPI lifespan; it is a pure derivation surface.
42. The function does NOT introduce any module-level singleton, cache, or lock.
43. The placeholder file is NOT reintroduced anywhere in the worktree.

## Codex review out-of-scope

Codex review MUST NOT propose:

- Adding the orchestrator decision composition root in this milestone (that is 2F.C).
- Modifying any prior-milestone artifact, including 2E1, 2E2, 2E3, or any earlier file.
- Modifying any 2F.A authored source or test file.
- Adding any new lineage ID at the service layer beyond the derived `decision_id`.
- Adding any FastAPI surface, Redis adapter, GPU runner, or model-loading subsystem.
- Adding any composition-root binder.
- Adding any non-trivial logic at the service layer beyond the documented validation, derivation, and propagation steps.

If Codex marks `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 36 new test files only and re-runs the implementation flow. On any safety violation, the supervisor surfaces to human attention; no autofix is permitted.

PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST_READY
