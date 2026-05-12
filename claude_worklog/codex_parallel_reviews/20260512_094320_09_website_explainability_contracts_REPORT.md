BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260512_094320_09_website_explainability_contracts_REPORT.md
# Website Explainability Contract Readiness Review

Review timestamp: 2026-05-12 09:43:20
Scope: v2/frontend, v2/backend/app, REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md
Mode: read-only static review; no Redis writes, no service restarts, no live actions.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The website has useful partial explainability surfaces, but it is not ready for the full REQ_0009 contract. Current implementation exposes feature_snapshot_id, prediction_id, risk_decision_id, and execution_intent_id on some panels, and it often separates static proof fixtures from current runtime evidence. However, required pages are not all wired to live/current explainability payloads, backend `/explain` routes are skeleton-only, paper/shadow/legacy comparison is not visible as a complete operator comparison, and one Risk Control panel can label missing lineage as REALTIME_RUNTIME_EVIDENCE.

## Evidence Observed

- Trainer Prediction Monitor exposes `prediction_id`, `feature_snapshot_id`, model/checkpoint, and raw/calibrated confidence when the trainer status is current; otherwise it shows explicit missing-evidence text. See v2/frontend/src/pages/operatorTruthComponents.tsx:405-424.
- Signal Explainability exposes `signal_id`, `prediction_id`, `feature_snapshot_id`, `orchestrator_decision_id`, `risk_decision_id`, `execution_intent_id`, reasons, and result only when `signal.status === REALTIME_RUNTIME_EVIDENCE`; otherwise it states static proof examples are not current signal lineage. See v2/frontend/src/pages/operatorTruthComponents.tsx:429-459.
- Static decision drawers expose several lineage IDs, confidence delta, source freshness, contributors, stale/missing flags, and reasons, but these are proof examples rather than a current complete runtime chain. See v2/frontend/src/pages/cockpitComponents.tsx:146-170.
- Paper Trading exposes paper runtime metrics, shadow decision count, and core lineage IDs from `paperRuntime.current_signal_lineage.lineage_ids`, with explicit non-live language. See v2/frontend/src/pages/paper-trading/index.tsx:20-45.
- Shared placeholder route shell explicitly marks many routes as requiring production payloads and says static/historical examples are not current runtime truth. See v2/frontend/src/components/layout/PageShell.tsx:13-67 and v2/frontend/src/components/layout/PageShell.tsx:152-162.
- Backend lineage schema defines the canonical chain fields (`feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`), but permits nullable values in the schema object. See v2/backend/app/api/schemas/lineage.py:26-50.

## Blockers

1. Backend explainability APIs are skeleton-only.
   - `/predictions`, `/decisions`, and `/risk-decisions` advertise `/{id}/explain` endpoints, but the files state scaffold-only and only implement an OPTIONS metadata shim. See v2/backend/app/api/v1/predictions.py:1-27, v2/backend/app/api/v1/decisions.py:1-32, and v2/backend/app/api/v1/risk_decisions.py:1-35.
   - Impact: the website cannot rely on backend read endpoints for full raw source data -> feature snapshot -> prediction -> signal -> decision -> risk -> execution -> paper/shadow/live-blocked action -> result/PnL attribution.

2. Required website pages are still placeholder/data-contract surfaces.
   - Symbol Universe, Audit Ledger, Executions, Positions, Orchestrator Admin, Execution Admin, and several related pages use the generic `PageShell`, which lists next-source tasks rather than rendering complete current explainability data. See v2/frontend/src/components/layout/PageShell.tsx:13-67 and v2/frontend/src/components/layout/PageShell.tsx:142-162.
   - Impact: REQ_0009 requires visibility in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness. Several of those are not complete explainability pages.

3. Risk Control can mislabel missing lineage as realtime evidence.
   - The "Current V2 Paper Risk Decision" panel renders whenever `truthPayload` exists and always displays a `REALTIME_RUNTIME_EVIDENCE` chip, while every lineage value can still be `MISSING` if `truthPayload.signal_lineage_status.latest_signal` is absent. See v2/frontend/src/pages/risk-control/index.tsx:19-30.
   - Impact: this violates the no-fake-reasoning/no-guessing contract because missing current risk lineage can be visually classified as realtime evidence.

4. Paper/shadow comparison visibility is incomplete.
   - Paper Trading shows paper events, shadow decision count, and lineage IDs, but does not render a row-level paper vs shadow vs legacy comparison with divergence reason, PnL attribution, blocked-trade reason, or audit timeline. See v2/frontend/src/pages/paper-trading/index.tsx:20-45 and v2/frontend/src/pages/paper-trading/index.tsx:57-69.
   - Impact: REQ_0009 specifically requires paper/shadow/legacy comparison and result/PnL attribution visibility.

5. Confidence and feature attribution are partial.
   - Trainer Prediction Monitor shows current prediction ID, feature snapshot ID, model/checkpoint, and raw/calibrated confidence, but does not show previous confidence, new confidence, delta, contributing feature deltas, positive contributors, negative contributors, source freshness, regime context, and data-quality impact for the current prediction. See v2/frontend/src/pages/operatorTruthComponents.tsx:405-424.
   - Static decision drawers contain some attribution fields, but they are collapsed proof examples, not current runtime truth. See v2/frontend/src/pages/cockpitComponents.tsx:146-170.

6. Risk decision reasoning is too shallow for the contract.
   - Backend risk assembly maps orchestrator actions to allow/deny reason codes and `live_blocked=True`, but does not expose the full risk-check breakdown required by REQ_0009: stale signal check, duplicate check, exposure check, drawdown check, sizing reason, hedge/open/close reason, and final decision reason. See v2/backend/app/services/risk_gateway/service.py:49-78.

## No-Fake-Reasoning Assessment

Mostly positive, with one blocker. The frontend repeatedly uses "Evidence missing - cannot explain without guessing" and separates static proof fixtures from current runtime truth. The Risk Control panel is the exception because it can claim REALTIME_RUNTIME_EVIDENCE without validating `signal_lineage_status.status` or `latest_signal`.

## Proposed Non-Live Autofix Tasks

1. Frontend: change Risk Control to compute `hasCurrentRisk = truthPayload?.signal_lineage_status.status === 'REALTIME_RUNTIME_EVIDENCE' && !!currentRisk`; show `CURRENT_RISK_DECISION_MISSING` and a warning chip when false.
2. Frontend: replace placeholder `PageShell` usage for Symbol Universe and Audit Ledger with read-only panels that render current payloads or explicit missing-evidence states for the exact REQ_0009 fields.
3. Frontend: add a Paper/Shadow/Legacy Comparison panel that consumes non-live public/runtime payloads and displays paper action, shadow action, legacy action, divergence reason, blocked reason, result/PnL attribution, and audit event pointers.
4. Frontend: extend Trainer Prediction Monitor current panel to render previous/new confidence, delta, positive/negative contributors, feature deltas, stale/missing/unused flags, source freshness by ingestor, regime context, model/checkpoint, and data-quality impact when present; otherwise show field-specific missing evidence.
5. Backend: implement read-only GET `/api/v1/*/{id}` and `/api/v1/*/{id}/explain` endpoints for feature snapshots, predictions, signals, decisions, risk decisions, execution intents, and paper trades using existing repositories only; no live mutations.
6. Backend: extend risk decision read/explain payloads with structured risk checks: stale signal, duplicate, exposure, drawdown, live gate, sizing reason, open/close/hedge reason, block reason, and final decision reason.
7. Tests: add frontend unit/e2e assertions that every required page either displays the IDs and explanation fields from current evidence or displays a missing-evidence/no-guessing state; add a regression test for Risk Control not showing REALTIME_RUNTIME_EVIDENCE when `latest_signal` is missing.

END_FILE
