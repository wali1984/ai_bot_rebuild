# Phase 2F.A — Orchestrator Decision Domain GO/NO-GO Request

This document specifies the markers Codex review at task `118` MUST emit and the markers the implementation task `117` MUST emit.

## Implementation markers (emitted by task 117)

Task `117_orchestrator_decision_2fa_domain_implementation` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/07_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO.md`:

- `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPL_AND_VALIDATION_PASSED`
- `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPL_AND_VALIDATION_FAILED`

The companion implementation report `06_2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPLEMENTATION_REPORT.md` MUST end with the marker line `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPLEMENTATION_REPORT_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review markers (emitted by task 118)

Task `118_orchestrator_decision_2fa_domain_codex_review` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/09_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_GO_NO_GO.md`:

- `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS`
- `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_FAIL`

The companion review report `08_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_REVIEW.md` MUST end with the marker line `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_REVIEW_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review rubric

Codex review MUST evaluate each row, mark PASS or FAIL, and cite a one-line evidence pointer for each PASS:

1. Public surface `__all__` ordered list matches the 15-tuple in `02_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC.md`.
2. `OrchestratorDecisionDomainError` is a subclass of `ValueError` with the required `__init__` signature and `__str__` formatting.
3. `OrchestratorDecisionRecord` is `@dataclass(frozen=True, slots=True)` with the 12 fields in the spec order and no defaults.
4. `decision_id`, `prediction_id`, `feature_snapshot_id` invariants enforced (type, non-empty, no whitespace, length ≤ 128).
5. `symbol` invariants enforced (uppercase, no whitespace, length ≤ 32).
6. `decision_ts_ms` invariants enforced (int, not bool, ≥ 0).
7. `decision_action` is a member of the four-action allowed frozenset.
8. `decision_reason_code` is a member of the eleven-reason allowed frozenset.
9. `input_prediction_direction` is a member of `{"long","short","flat"}`.
10. `input_prediction_confidence_calibrated` invariants enforced (float, not bool, finite, in `[0.0, 1.0]`).
11. `input_prediction_freshness_flag` is a member of `{"fresh","stale","missing"}`.
12. `input_worker_health_status` is a member of `{"HEALTHY","DEGRADED","CRITICAL","UNKNOWN"}`.
13. `live_blocked` MUST be `bool` and MUST be `True` (default-deny safety).
14. Cross-field invariant: `open_long` requires `proceed_long` and direction `long`.
15. Cross-field invariant: `open_short` requires `proceed_short` and direction `short`.
16. Cross-field invariant: `hold` requires `hold_flat_direction` and direction `flat`.
17. Cross-field invariant: `abstain` requires reason starting with `abstain_`.
18. Order of invariant checks is per-field then cross-field, deterministic.
19. `record.py` imports limited to `__future__`, `math`, `dataclasses.dataclass`, and `.errors`.
20. `errors.py` imports limited to `__future__`.
21. `__init__.py` imports limited to `.errors` and `.record` re-exports.
22. No forbidden token from `02_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC.md` 'Forbidden tokens in source files' appears in any authored source file.
23. Importing `v2.backend.app.domain.orchestrator_decision` in a fresh subprocess does NOT load `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env`.
24. The exact 35 test files (one `__init__.py` plus 34 test files) are present, one test function per file, no shared `conftest.py`.
25. The full test suite at `v2/backend/tests/unit/domain/orchestrator_decision/` passes via `.venv/bin/python -m pytest -q`.
26. Cross-isolation diff is zero across all paths in `04_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SAFETY_BOUNDARIES.md` 'Cross-isolation paths'.
27. No prior-milestone source or test file byte content is modified.
28. No master planner prompt edit. No supervisor task edit. No requirements inbox edit. No security edit.
29. No live behavior. No exchange action. No leverage/margin change. No deployment. No production migration.
30. No secret value or credential-shaped string in any authored file.
31. The implementation report cites function and line range for each of the four behavior contract steps in `02_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC.md` 'Behavior contract steps to be cited in the implementation report'.
32. The 2F.A domain does NOT introduce any orchestrator decision derivation logic; it is a pure value-object surface.
33. The `live_blocked` invariant is wired so that any caller constructing a record with `live_blocked == False` fails closed at `__post_init__` time.
34. The forbidden-token test reads each authored source file as text and asserts no forbidden literal appears; the test file itself constructs each literal at runtime.

## Codex review out-of-scope

Codex review MUST NOT propose:

- Adding the orchestrator decision assembler service or composition root in this milestone (those are 2F.B and 2F.C).
- Modifying any prior-milestone artifact, including 2E1, 2E2, 2E3, or any earlier file.
- Adding any new lineage ID beyond `decision_id`, `prediction_id`, `feature_snapshot_id` at the value-object layer.
- Adding any FastAPI surface, Redis adapter, GPU runner, or model-loading subsystem.
- Adding any non-trivial logic at the value-object layer beyond the validation invariants enumerated in 02.

If Codex marks `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 34 new test files only and re-runs the implementation flow. On any safety violation, the supervisor surfaces to human attention; no autofix is permitted.

PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO_REQUEST_READY
