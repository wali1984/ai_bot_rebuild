# Phase 2G.A — Risk Gateway Domain GO/NO-GO Request

This document specifies the markers Codex review at task `127` MUST emit and the markers the implementation task `126` MUST emit.

## Implementation markers (emitted by task 126)

Task `126_risk_gateway_2ga_domain_implementation` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/risk_gateway_impl/07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`:

- `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_PASSED`
- `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_FAILED`

The companion implementation report `06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md` MUST end with the marker line `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review markers (emitted by task 127)

Task `127_risk_gateway_2ga_domain_codex_review` emits exactly one of the following markers as the sole content of `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`:

- `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`
- `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_FAIL`

The companion review report `08_2G_A_RISK_GATEWAY_DOMAIN_CODEX_REVIEW.md` MUST end with the marker line `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_REVIEW_READY`. The body MUST NOT contain any harness BEGIN/END framing token marker line.

## Codex review rubric

Codex review MUST evaluate each row, mark PASS or FAIL, and cite a one-line evidence pointer for each PASS:

1. Public surface `__all__` ordered list matches the 9-tuple in `02_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SPEC.md`.
2. `RiskGatewayDomainError` is a subclass of `ValueError` with the required `__init__` signature and `__str__` formatting.
3. `RiskDecisionRecord` is `@dataclass(frozen=True, slots=True)` with the 11 fields in the spec order and no defaults.
4. `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` invariants enforced (type, non-empty, no whitespace, length ≤ 128).
5. `symbol` invariants enforced (uppercase, no whitespace, length ≤ 32).
6. `risk_decision_ts_ms` invariants enforced (int, not bool, ≥ 0).
7. `risk_action` is a member of the two-action allowed frozenset.
8. `risk_reason_code` is a member of the five-reason allowed frozenset.
9. `input_decision_action` is a member of `{"open_long","open_short","hold","abstain"}`.
10. `input_decision_reason_code` is a member of the nine-reason orchestrator-input frozenset.
11. `live_blocked` MUST be `bool` and MUST be `True` (default-deny safety).
12. Cross-field invariant: `allow` requires reason starting with `allow_`.
13. Cross-field invariant: `deny` requires reason starting with `deny_`.
14. Cross-field invariant: `allow_proceed_long` requires `open_long` input action and `proceed_long` input reason.
15. Cross-field invariant: `allow_proceed_short` requires `open_short` input action and `proceed_short` input reason.
16. Cross-field invariant: `deny_orchestrator_abstained` requires `abstain` input action.
17. Cross-field invariant: `deny_orchestrator_held` requires `hold` input action.
18. Cross-field invariant: `deny_default` requires `open_long` or `open_short` input action.
19. Order of invariant checks is per-field then cross-field, deterministic, in the order documented in the spec.
20. `record.py` imports limited to `__future__`, `dataclasses.dataclass`, and `.errors`.
21. `errors.py` imports limited to `__future__`.
22. `__init__.py` imports limited to `.errors` and `.record` re-exports.
23. No forbidden token from `02_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SPEC.md` 'Forbidden tokens in source files' appears in any authored source file.
24. Importing `v2.backend.app.domain.risk_gateway` in a fresh subprocess does NOT load `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, or `v2.backend.app.adapters.redis_v2.url_env`.
25. The exact 32 test files (one `__init__.py` plus 31 test files) are present, one test function per file, no shared `conftest.py`.
26. The full test suite at `v2/backend/tests/unit/domain/risk_gateway/` passes via `.venv/bin/python -m pytest -q`.
27. Cross-isolation diff is zero across all paths in `04_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SAFETY_BOUNDARIES.md` 'Cross-isolation paths'.
28. No prior-milestone source or test file byte content is modified.
29. No master planner prompt edit. No supervisor task edit. No requirements inbox edit. No security edit.
30. No live behavior. No exchange action. No leverage/margin change. No deployment. No production migration.
31. No secret value or credential-shaped string in any authored file.
32. The implementation report cites function and line range for each of the four behavior contract steps in `02_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SPEC.md` 'Behavior contract steps to be cited in the implementation report'.
33. The 2G.A domain does NOT introduce any risk-gateway derivation logic; it is a pure value-object surface.
34. The `live_blocked` invariant is wired so that any caller constructing a record with `live_blocked == False` fails closed at `__post_init__` time.
35. The forbidden-token test reads each authored source file as text and asserts no forbidden literal appears; the test file itself constructs each literal at runtime.
36. The 2G.A domain does NOT import `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, or `v2.backend.app.domain.liveness_stream_growth`.

## Codex review out-of-scope

Codex review MUST NOT propose:

- Adding the risk gateway assembler service or composition root in this milestone (those are 2G.B and 2G.C).
- Modifying any prior-milestone artifact, including 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, or any earlier file.
- Adding any new lineage ID beyond `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` at the value-object layer.
- Adding any FastAPI surface, Redis adapter, GPU runner, or model-loading subsystem.
- Adding any non-trivial logic at the value-object layer beyond the validation invariants enumerated in 02.
- Importing the orchestrator decision domain at the value-object layer.

If Codex marks `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 31 new test files only and re-runs the implementation flow. On any safety violation, the supervisor surfaces to human attention; no autofix is permitted.

PHASE2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO_REQUEST_READY
