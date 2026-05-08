# Codex Parallel Review - Orchestrator Decision MVP

Review timestamp: 2026-05-08 22:49:02 America/New_York

Scope reviewed:
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- adjacent `v2/backend/app/domain/trainer_prediction_output/`
- adjacent `v2/backend/app/domain/risk_gateway/`, `v2/backend/app/services/risk_gateway/`, and `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/api/v1/decisions.py`
- `v2/backend/app/api/schemas/decision.py`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

Verdict: BLOCKED

## Summary

The Orchestrator Decision MVP is safe as a pure, non-live derivation surface, but it is not ready against the requested parallel-review checklist. The implementation does not directly execute trades and it does produce deterministic `decision_id` values from `prediction_id`; however, it lacks `signal_id` lineage, has no duplicate-signal admission/skip behavior, and has no integrated orchestrator-to-risk handoff contract proving stale/duplicate/unsafe signal treatment before risk evaluation.

## Findings

### BLOCKER 1 - `signal_id` lineage is absent from the decision record path

Evidence:
- `v2/backend/app/domain/trainer_prediction_output/record.py:91-105` defines `TrainerPredictionRecord` with `prediction_id` and `feature_snapshot_id`, but no `signal_id`.
- `v2/backend/app/domain/orchestrator_decision/record.py:73-86` defines `OrchestratorDecisionRecord` with `decision_id`, `prediction_id`, and `feature_snapshot_id`, but no `signal_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:76-117` derives `decision_id = "dec_" + prediction.prediction_id` and propagates `prediction_id`/`feature_snapshot_id`, but cannot propagate a signal id.
- `v2/backend/app/api/v1/decisions.py:20-25` declares the decision stage required ids as `feature_snapshot_id`, `prediction_id`, `signal_id`, and `decision_id`, so the runtime/domain MVP is narrower than the declared lineage surface.

Impact:
- Decision lineage is not complete from signal to decision.
- Downstream risk and evidence surfaces cannot prove the exact signal that produced a decision.

Non-live autofix task:
- Add a pure lineage extension task that introduces `signal_id` into the upstream prediction/decision value path, propagates it through `assemble_orchestrator_decision_record(...)`, and adds unit tests proving `signal_id -> prediction_id -> decision_id` continuity without Redis, HTTP, live services, or order execution.

### BLOCKER 2 - Duplicate signal handling is not implemented or represented

Evidence:
- `v2/backend/app/services/orchestrator_decision/service.py:34-117` is a stateless assembler; it validates one `TrainerPredictionRecord` and returns one `OrchestratorDecisionRecord`.
- `v2/backend/app/composition/orchestrator_decision/runtime.py:15-51` builds a closure over threshold and clock only. There is no injected duplicate detector, idempotency policy, last-seen id reader, or skip/deny result.
- `v2/backend/tests/unit/services/orchestrator_decision/` covers stale/missing freshness, low confidence, worker health, direction mapping, clock validation, and id derivation, but no duplicate signal or duplicate prediction admission behavior.

Impact:
- Replayed or duplicated upstream signals can produce repeated equivalent decisions, and the MVP has no explicit skip/duplicate reason code or idempotency contract.
- Deterministic `decision_id = dec_<prediction_id>` helps identify repeated predictions but does not define duplicate handling behavior.

Non-live autofix task:
- Add a pure duplicate-admission layer or explicit duplicate outcome before decision assembly. Keep it dependency-injected and side-effect-free in tests, with cases for first-seen, duplicate-signal, duplicate-prediction, and replayed stale input. Do not use Redis writes; use fake in-memory readers/adapters in unit tests only.

### BLOCKER 3 - Risk gateway handoff is only adjacent, not contract-complete

Evidence:
- `v2/backend/app/services/risk_gateway/service.py:25-79` can convert an `OrchestratorDecisionRecord` into a `RiskDecisionRecord`.
- It maps `open_long` and `open_short` to allow, and maps `hold`/`abstain` to deny at `v2/backend/app/services/risk_gateway/service.py:49-60`.
- Stale and missing prediction freshness become orchestrator `abstain` decisions in `v2/backend/app/services/orchestrator_decision/service.py:77-82`, and risk gateway then denies abstain at `v2/backend/app/services/risk_gateway/service.py:58-60`.
- There is no reviewed composition/runtime contract that wires orchestrator evaluation directly into risk evaluation with lineage preservation and duplicate/stale admission semantics.

Impact:
- Stale freshness is default-denied if both services are called in the right order, but the handoff is not proven as a single contract.
- Duplicate signal behavior remains undefined before the risk gateway receives a decision.

Non-live autofix task:
- Add a pure orchestrator-to-risk handoff contract test or composition helper that takes a validated prediction/decision, calls the risk evaluator, preserves all lineage ids including `signal_id`, and proves stale/missing/worker-unhealthy/low-confidence outcomes all become risk denies.

## Passing Checks

- No direct trade execution observed in the orchestrator decision MVP. The reviewed domain/service/composition files do not import exchange adapters, execution routers, Redis clients, FastAPI routers, or live service control paths.
- `live_blocked=True` is enforced in `OrchestratorDecisionRecord` at `v2/backend/app/domain/orchestrator_decision/record.py:159-164` and set by the assembler at `v2/backend/app/services/orchestrator_decision/service.py:105-117`.
- `decision_id` is deterministic and bounded: `v2/backend/app/services/orchestrator_decision/service.py:70-76` rejects overly long `prediction_id` and derives `decision_id` by prefixing `dec_`.
- Legacy audit requirements were considered. `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-16` requires decisions to include `decision_id`, risk gateway default-deny for stale/unsafe signals, and paper ledger capture; the current MVP covers only part of that path.
- The phase breakdown explicitly limits 2F to no risk gateway behavior, execution-side surface, or strategy library at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/00_PHASE_2F_SUB_PHASE_BREAKDOWN.md:1-3` and `:50-52`. That explains the narrow implementation but does not satisfy this broader parallel-review checklist.

## Validation

No live services were restarted. No Redis reads/writes or key deletions were performed. No orders were placed or cancelled. No leverage, margin, deployment, or live trading settings were changed.

Tests were not run during this read-only parallel review to avoid creating new test cache artifacts. Existing implementation reports claim prior orchestrator decision suites passed, including `28 passed` for composition, `36 passed` for services, and `34 passed` for domain in `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/24_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_REVIEW.md:109-128`.

## Recommendation

Do not advance this review gate as ready. Schedule the non-live autofix tasks above, then re-review lineage continuity, duplicate/stale handling, and orchestrator-to-risk handoff as a single contract before enabling any downstream execution-facing milestone.
