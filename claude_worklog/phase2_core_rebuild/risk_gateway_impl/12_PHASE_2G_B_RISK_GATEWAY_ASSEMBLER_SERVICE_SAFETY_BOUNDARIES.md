# Phase 2G.B — Risk Gateway Assembler Service Safety Boundaries

This document enumerates hard safety invariants for Phase 2G.B. Codex review at the future task `129` MUST verify each invariant explicitly and cite evidence for each PASS row.

## Forbidden runtime behaviors (in any authored 2G.B source file)

- No `redis`, `redis.asyncio`, `aioredis`, `hiredis` import.
- No `httpx`, `requests` import.
- No `fastapi`, `uvicorn` import.
- No `asyncio`, `threading`, `multiprocessing` import.
- No `subprocess` invocation outside the three permitted test files (`test_assembler_service_does_not_import_redis.py`, `test_assembler_service_does_not_import_url_env.py`, `test_assembler_service_does_not_register_fastapi_lifespan.py`).
- No `socket` import.
- No `os.environ`, `os.getenv` access.
- No wall-clock helper call: `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`. The clock is injected via the `now_ms_clock` parameter only.
- No `logging` import. No `print(` invocation.
- No `url_env` import. No `gamma.real` factory import.
- No import of any `v2.backend.app.adapters.*`, `v2.backend.app.composition.*`, `v2.backend.app.api.*`, `v2.backend.app.cli.*`, `v2.backend.app.jobs.*`, `v2.backend.app.main.*`, or any other `v2.backend.app.services.*` sibling.
- No import of `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.trainer_worker_health`, `v2.backend.app.domain.trainer_parity`, `v2.backend.app.domain.trainer_liveness`, `v2.backend.app.domain.trainer_liveness_composition`, `v2.backend.app.domain.trainer_liveness_observation_collector`, or `v2.backend.app.domain.liveness_stream_growth`.
- No import of `RISK_DECISION_REASON_DENY_DEFAULT`. No emission of `"deny_default"` from the derivation table for any orchestrator-decision input. The reserved 2G.A taxonomy member is held for a future enrichment of 2G.B.
- No URL, token, key, or credential-shaped string literal.
- No FastAPI lifespan, dependency, or router registration.
- No module-level singleton, cache, or lock.
- No mutation of any prior-milestone source or test file.
- No mutation of any 2G.A authored source or test file.
- No mutation of any task definition under `claude_worklog/agent_supervisor/tasks/`.
- No mutation of the master planner prompt.
- No standalone harness BEGIN/END framing token marker line in any authored file body.

## Placeholder file deletion

The single one-line placeholder file `v2/backend/app/services/risk_gateway.py` is deleted by task `128`. After the task completes:

- `git ls-files v2/backend/app/services/risk_gateway.py` MUST return zero output lines.
- `git ls-files v2/backend/app/services/risk_gateway/__init__.py` MUST return exactly one line.
- `git ls-files v2/backend/app/services/risk_gateway/service.py` MUST return exactly one line.
- `git ls-files v2/backend/app/services/risk_gateway/errors.py` MUST return exactly one line.

The placeholder file MUST NOT be reintroduced under any condition. Codex review at task `129` re-runs each of the four `git ls-files` checks and confirms the result.

## Cross-isolation paths (must show zero git diff outside the new package, the new test directory, the placeholder deletion, and the impl-report directory after authoring)

Codex review MUST run `git status -s` over the following paths and assert zero output lines:

- `v2/backend/app/composition/`
- `v2/backend/app/services/agent_supervisor_reader.py`
- `v2/backend/app/services/audit_writer.py`
- `v2/backend/app/services/discovery_runner.py`
- `v2/backend/app/services/execution_router.py`
- `v2/backend/app/services/feature_assembly.py`
- `v2/backend/app/services/feature_snapshots/`
- `v2/backend/app/services/hot_reload_orchestrator.py`
- `v2/backend/app/services/__init__.py`
- `v2/backend/app/services/monitor_runner.py`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/services/paper_loop.py`
- `v2/backend/app/services/prediction_ingest.py`
- `v2/backend/app/services/replay_runner.py`
- `v2/backend/app/services/selection_runner.py`
- `v2/backend/app/services/signal_publisher.py`
- `v2/backend/app/services/symbol_universe/`
- `v2/backend/app/services/trainer_parity/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/services/trainer_worker_health/`
- `v2/backend/app/adapters/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/domain/decisions/`
- `v2/backend/app/domain/trainer_liveness/`
- `v2/backend/app/domain/trainer_liveness_composition/`
- `v2/backend/app/domain/trainer_liveness_observation_collector/`
- `v2/backend/app/domain/trainer_parity/`
- `v2/backend/app/domain/trainer_worker_health/`
- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/domain/liveness_stream_growth/`
- `v2/backend/app/domain/connectors/`
- `v2/backend/app/domain/execution/`
- `v2/backend/app/domain/features/`
- `v2/backend/app/domain/governance/`
- `v2/backend/app/domain/hot_reload/`
- `v2/backend/app/domain/lineage/`
- `v2/backend/app/domain/monitor/`
- `v2/backend/app/domain/predictions/`
- `v2/backend/app/domain/replay/`
- `v2/backend/app/domain/risk/`
- `v2/backend/app/domain/signals/`
- `v2/backend/app/domain/symbols/`
- `v2/backend/app/domain/traders/`
- `v2/backend/app/domain/universe/`
- `v2/frontend/`
- `v2/backend/tests/unit/composition/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/domain/trainer_liveness/`
- `v2/backend/tests/unit/domain/trainer_liveness_composition/`
- `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`
- `v2/backend/tests/unit/domain/trainer_parity/`
- `v2/backend/tests/unit/domain/trainer_worker_health/`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/domain/liveness_stream_growth/`
- `v2/backend/tests/unit/services/__init__.py`
- `v2/backend/tests/unit/services/feature_snapshots/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/services/symbol_universe/`
- `v2/backend/tests/unit/services/trainer_parity/`
- `v2/backend/tests/unit/services/trainer_prediction_output/`
- `v2/backend/tests/unit/services/trainer_worker_health/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/00_PHASE_2G_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/02_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/03_PHASE_2G_A_RISK_GATEWAY_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/04_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/05_PHASE_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/08_2G_A_RISK_GATEWAY_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/10_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/11_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/12_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/13_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`

The only allowed git-status outputs after task `128` runs are: deletion of `v2/backend/app/services/risk_gateway.py`; creation of the new package files at `v2/backend/app/services/risk_gateway/`; creation of the 30 new test files at `v2/backend/tests/unit/services/risk_gateway/`; creation of `14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` and `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`.

## Hard safety stops

Stop and write the FAILED marker (no autofix in this task) on any of the following:

- Any live behavior, any Redis access at any layer, any Redis command at any time.
- Any legacy mutation, any release intent in any environment.
- Any modification of any prior-milestone source or test file.
- Any modification of any 2G.A authored source or test file.
- Any FastAPI lifespan or router or singleton or cache or wall-clock helper or `os.environ` or subprocess (outside the three permitted test files) or socket in any authored 2G.B source file.
- Any direct `redis`, `url_env`, or factory import in any authored 2G.B source file.
- Any import of `RISK_DECISION_REASON_DENY_DEFAULT` in any authored 2G.B source file.
- Any emission of `"deny_default"` for any orchestrator-decision input under the 2F.A invariant.
- Any URL or credential leakage.
- Any REQ_0017 scope-cap violation (no risk-gateway composition root, no execution surface, no FastAPI surface, no adapter expansion, no decision-route reasoning beyond the documented derivation table).
- Reintroduction of the placeholder file `v2/backend/app/services/risk_gateway.py`.

## Live gate

The live gate remains blocked. The 2G.B service constructs every `RiskDecisionRecord` with `live_blocked=True` so the 2G.A domain invariant trips the construction-time fail-closed if any caller attempts to substitute `False`.

PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES_READY
