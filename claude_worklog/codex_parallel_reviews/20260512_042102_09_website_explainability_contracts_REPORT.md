BEGIN_FILE claude_worklog/codex_parallel_reviews/20260512_042102_09_website_explainability_contracts_REPORT.md
# Codex Parallel Review: Website Explainability Contract Readiness

Review timestamp: 2026-05-12 04:21:02
Mode: read-only parallel review, static source inspection only
Scope inspected:
- v2/frontend
- v2/backend/app
- claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The website is not ready for the REQ_0009 full decision explainability contract. It has useful partial static/proof visibility and explicit "Evidence missing - cannot explain without guessing" safeguards, but the required current-runtime website/API contract is incomplete and several required pages are generic placeholder shells.

## Findings Against Requested Checks

### feature_snapshot_id visibility

Partial.

Evidence:
- v2/frontend/src/pages/cockpitComponents.tsx:157-165 shows feature_snapshot_id in DecisionDrawers for static/proof decision rows.
- v2/frontend/src/pages/trainer-prediction-monitor/index.tsx:14-22 advertises prediction_id/feature_snapshot_id and shows a no-guessing panel when current trainer evidence is missing.
- v2/frontend/src/pages/risk-control/index.tsx:22-30 shows feature_snapshot_id from truthPayload signal lineage when present.

Blocker:
- Generic required pages do not expose a current feature snapshot explainability view. Symbols, Audit Ledger, Signals, Executions, and Positions are PageShell wrappers, and PageShell only lists production data requirements plus limited static fixture context for some pages.

### prediction_id visibility

Partial.

Evidence:
- v2/frontend/src/pages/cockpitComponents.tsx:151-164 shows prediction_id in static/proof decision drawers.
- v2/frontend/src/pages/trainer-prediction-monitor/index.tsx:14-22 explicitly requires current trainer runtime evidence before treating prediction_id as current.
- v2/frontend/src/pages/risk-control/index.tsx:22-30 exposes prediction_id when currentRisk exists.

Blocker:
- Backend /predictions is skeleton-only. v2/backend/app/api/v1/predictions.py:1-27 defines only route metadata and an OPTIONS shim; there is no GET/POST or /{prediction_id}/explain implementation returning current prediction explanations.

### risk_decision_id visibility

Partial.

Evidence:
- v2/frontend/src/pages/cockpitComponents.tsx:157-169 shows risk_decision_id and risk reason in static/proof drawers.
- v2/frontend/src/pages/risk-control/index.tsx:22-30 and 46-52 show risk_decision_id in current/static sections.
- v2/frontend/src/components/layout/PageShell.tsx:175-184 shows risk_decision_id for limited static fixture context on signals/executions/positions/audit-ledger.

Blocker:
- Backend /risk-decisions is skeleton-only. v2/backend/app/api/v1/risk_decisions.py:1-35 exposes metadata with milestone_d_status "skeleton" and no implemented explain response.
- Risk Control labels the current panel as REALTIME_RUNTIME_EVIDENCE whenever truthPayload exists, even if each currentRisk field is MISSING. That can overstate readiness.

### paper/shadow comparison visibility

Partial to insufficient.

Evidence:
- v2/frontend/src/pages/paper-trading/index.tsx:18-29 displays current paper runtime counters including shadow decisions, risk blocks, and exchange order false.
- v2/frontend/src/pages/paper-trading/index.tsx:31-35 states the current paper runtime is not live readiness and fails closed when evidence is missing.

Blocker:
- Paper Trading only shows signal_id, risk, and result for static decision rows at v2/frontend/src/pages/paper-trading/index.tsx:47-59. It does not show prediction_id, feature_snapshot_id, risk_decision_id, execution_intent_id, paper/shadow/legacy comparison, PnL attribution, or blocked-trade lineage in that context.
- Backend /paper-trades is skeleton-only. v2/backend/app/api/v1/paper.py:1-34 has only metadata and no paper/shadow comparison explain endpoint.

### no fake reasoning

Partially satisfied.

Evidence:
- v2/frontend/src/components/layout/PageShell.tsx:156-159 says static proof fixtures and historical examples are not current runtime truth and missing evidence cannot be explained without guessing.
- v2/frontend/src/pages/trainer-prediction-monitor/index.tsx:18-22 shows a no-guessing warning when current trainer runtime evidence is missing.
- v2/frontend/src/pages/signal-explainability/index.tsx:18-21 shows an explicit no-guessing warning when realtime signal lineage is missing.

Residual blocker:
- Some panels still present static proof drawers and fixture context as explainability surfaces. They are mostly labeled, but the contract requires every major system decision to be explainable from full lineage. Current implementation does not consistently gate all required pages to current evidence or provide complete explain payloads.

## Contract Gaps By REQ_0009 Required UI Visibility

Missing or incomplete in current website/API contract:
- signal_id, decision_id, risk_decision_id, execution_intent_id are not consistently visible on all required pages.
- Symbol Universe page is a generic PageShell and lacks source discovery evidence, Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, liquidity/volume/volatility/open-interest/freshness scores, feature completeness, manual overrides, and observed/training/paper/shadow/live-blocked state reasons.
- No dedicated Feature Attribution page was found in v2/frontend/src/pages, despite REQ_0009 listing it as required.
- Risk Gateway page is represented by Risk Control but lacks full risk check breakdown, position sizing reason, stale/duplicate/exposure/drawdown checks as structured current evidence.
- Trader Fleet page was not found as a dedicated required page.
- Paper / Shadow Trading lacks full paper/shadow/legacy comparison with lineage IDs and PnL attribution on the primary page.
- Audit Ledger page is generic PageShell and does not expose append-only audit timeline or chain integrity rows beyond required-data text and limited static fixture context.
- Live Readiness exists, but no inspected implementation showed complete explainability chain visibility across feature snapshot -> prediction -> signal -> orchestrator -> risk -> execution intent -> paper/shadow/live-blocked result.
- Backend explain endpoints for feature snapshots, predictions, decisions, risk decisions, and paper trades are metadata-only skeletons.

## Backend Contract Evidence

Positive:
- v2/backend/app/api/schemas/lineage.py:26-41 defines the canonical lineage block with feature_snapshot_id, prediction_id, signal_id, decision_id, risk_decision_id, execution_intent_id, and lineage_gap_reason.

Blockers:
- v2/backend/app/api/v1/predictions.py:1-27 is scaffold-only and returns route metadata only.
- v2/backend/app/api/v1/risk_decisions.py:1-35 is scaffold-only and returns route metadata only.
- v2/backend/app/api/v1/paper.py:1-34 is scaffold-only and returns route metadata only.
- Similar skeleton pattern applies to the feature snapshot and decision explain surfaces, so the frontend has no implemented backend explain contract to consume.

## Proposed Non-Live Autofix Tasks

1. Implement read-only explain payload endpoints for:
   - GET /api/v1/feature-snapshots/{feature_snapshot_id}/explain
   - GET /api/v1/predictions/{prediction_id}/explain
   - GET /api/v1/decisions/{decision_id}/explain
   - GET /api/v1/risk-decisions/{risk_decision_id}/explain
   - GET /api/v1/paper-trades/{paper_trade_id}/explain

2. Add typed response schemas for a FullDecisionExplainability payload covering:
   - all lineage IDs
   - confidence previous/new/delta
   - positive/negative feature contributors
   - stale/missing/unused feature flags
   - source freshness by ingestor
   - model/checkpoint version
   - risk checks
   - sizing/open/close/hedge/block reasons
   - paper/shadow/legacy comparison
   - PnL attribution
   - audit timeline
   - explicit evidence_source/current_vs_static classification

3. Replace generic PageShell-only required pages with real current-evidence explainability sections for Symbol Universe, Audit Ledger, Signals, Executions, Positions, and Live Readiness.

4. Add missing required pages or route aliases for Feature Attribution and Trader Fleet, or document exact existing page mappings and expose the required fields there.

5. Tighten frontend labeling so REALTIME_RUNTIME_EVIDENCE is shown only when the actual row exists and all required current IDs are present; otherwise show MISSING_EVIDENCE / cannot explain without guessing.

6. Expand Paper / Shadow Trading to show row-level paper/shadow/legacy comparison with feature_snapshot_id, prediction_id, signal_id, decision_id, risk_decision_id, execution_intent_id, result, blocked reason, and PnL attribution.

7. Add non-live tests asserting that every REQ_0009 required page renders the required IDs or an explicit no-guessing missing-evidence state, and that no static fixture is presented as current runtime truth.

## Safety Notes

This review did not modify /home/wali/Desktop/AI BOT, did not write Redis, did not delete Redis keys, did not restart services, did not place/cancel orders, did not change leverage/margin, did not enable live trading, and did not deploy.
END_FILE
