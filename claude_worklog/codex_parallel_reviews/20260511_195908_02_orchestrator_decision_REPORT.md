# Codex Parallel Review - Orchestrator Decision MVP

Review mode: read-only. No files, Redis keys, live services, orders, leverage/margin, live-trading flags, deployments, or secrets were modified. I did not run pytest because the user requested read-only review mode; prior phase reports record passing suites.

## Scope inspected

- `v2/backend/app/domain/orchestrator_decision/record.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/composition/orchestrator_decision/runtime.py`
- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/app/services/risk_gateway/service.py`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Decision ID lineage

PASS.

- `OrchestratorDecisionRecord` requires `decision_id`, `prediction_id`, and `feature_snapshot_id`, each non-empty, whitespace-free, and length bounded at 128 chars in `v2/backend/app/domain/orchestrator_decision/record.py:73-93`.
- The assembler deterministically derives `decision_id = "dec_" + prediction.prediction_id` and rejects prediction IDs longer than 124 chars before derivation in `v2/backend/app/services/orchestrator_decision/service.py:70-76`.
- The returned decision propagates `prediction_id`, `feature_snapshot_id`, `symbol`, freshness, confidence, direction, and worker health unchanged in `v2/backend/app/services/orchestrator_decision/service.py:105-118`.
- Risk gateway lineage continues with `risk_decision_id="rd_" + decision.decision_id` while preserving `decision_id`, `prediction_id`, and `feature_snapshot_id` in `v2/backend/app/services/risk_gateway/service.py:67-78`.

## Risk gateway handoff completeness

PASS.

- The Orchestrator Decision MVP emits only candidate actions: `open_long`, `open_short`, `hold`, or `abstain` in `v2/backend/app/domain/orchestrator_decision/record.py:8-21`.
- The risk gateway consumes an `OrchestratorDecisionRecord` directly and maps `open_long/open_short` to allow, while mapping `hold/abstain` to deny in `v2/backend/app/services/risk_gateway/service.py:25-60`.
- The risk gateway record carries both input decision action/reason and lineage fields in `v2/backend/app/domain/risk_gateway/record.py:58-68`.
- Both records require `live_blocked is True`, enforced in `v2/backend/app/domain/orchestrator_decision/record.py:159-164` and `v2/backend/app/domain/risk_gateway/record.py:214-218`.

## Stale / duplicate signal handling

PASS for MVP scope, with one explicit boundary.

- Stale and missing freshness are fail-closed before action selection: missing maps to `abstain_freshness_missing`; stale maps to `abstain_freshness_stale` in `v2/backend/app/services/orchestrator_decision/service.py:77-82`.
- Freshness checks run before worker-health, confidence, and direction checks, so stale/missing predictions cannot become `open_long` or `open_short`.
- Duplicate signal handling is intentionally not inside this MVP path: Phase 2F legacy review states `signal_id` is reserved for an upstream signal layer and not introduced by 2F.A. The current input is a validated `TrainerPredictionRecord`, not a raw signal.
- Repeated use of the same `prediction_id` is idempotent at this layer because it produces the same `decision_id`. Cross-prediction duplicate classification is represented elsewhere by `v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py`, not by Orchestrator Decision.

## Legacy orchestrator behavior mapping

PASS.

- Legacy read-only evidence requires decisions to include `decision_id` and risk gateway default-deny for stale/unsafe signals in `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`.
- Phase 2F documents that legacy orchestrator runtime evidence had no concrete decision payload, so the MVP maps the behavior through explicit lineage, abstain reasons, `live_blocked=True`, and downstream risk-gateway gating.
- The default-deny table covers stale/missing freshness, degraded/critical/unknown worker health, low confidence, flat hold, and long/short candidate opens in `v2/backend/app/services/orchestrator_decision/service.py:77-103`.

## No direct trade execution

PASS.

- The orchestrator decision domain/service/composition path has no Redis, exchange, HTTP, FastAPI, subprocess, order, leverage, margin, or live-trading implementation imports.
- A targeted token scan over `v2/backend/app/domain/orchestrator_decision`, `v2/backend/app/services/orchestrator_decision`, and `v2/backend/app/composition/orchestrator_decision` found no direct live execution tokens in authored source; matches were limited to test subprocess import-clean checks and harmless constant names.
- The composition root only binds `low_confidence_threshold` and `now_ms_clock`, then forwards a `TrainerPredictionRecord` to the assembler in `v2/backend/app/composition/orchestrator_decision/runtime.py:15-51`.

## Blockers

None.

## Proposed non-live autofix tasks

None required for Orchestrator Decision MVP readiness. A future non-live integration task may wire upstream `signal_id`/dedupe classification into the broader signal-to-risk chain, but that is outside the Phase 2F Orchestrator Decision MVP contract.

## Recommendation

CODEX_PARALLEL_REVIEW_READY
