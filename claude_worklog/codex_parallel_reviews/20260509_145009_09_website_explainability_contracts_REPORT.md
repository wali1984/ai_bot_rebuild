# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Inputs inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Result: BLOCKED

## Requirement Summary

REQ_0009 requires the website to expose detailed human-readable decision explanations and full lineage from raw source data through feature snapshot, prediction, signal, orchestrator decision, risk gateway decision, execution intent, paper/shadow/live-blocked action, and result/PnL attribution.

Required visibility includes `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`, symbol universe state, confidence delta, feature contributors, feature quality flags, source freshness, risk checks, sizing/open/close/hedge/block reasons, paper/shadow/legacy comparison, blocked-trade reason, and audit timeline.

## Findings

### 1. Required pages are mostly placeholder shells

Blocking evidence:
- `v2/frontend/src/components/layout/PageShell.tsx` renders a generic body: "Placeholder shell for milestone E. Concrete handlers, repositories, and interactive controls land in later milestones per the V2 implementation sequence."
- Contract-critical pages render only that shell, including:
  - `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx`
  - `v2/frontend/src/pages/signal-explainability/index.tsx`
  - `v2/frontend/src/pages/risk-control/index.tsx`
  - `v2/frontend/src/pages/paper-trading/index.tsx`
  - `v2/frontend/src/pages/audit-ledger/index.tsx`
  - `v2/frontend/src/pages/live-readiness/index.tsx`
  - `v2/frontend/src/pages/symbols/index.tsx`
  - `v2/frontend/src/pages/orchestrator-admin/index.tsx`
  - `v2/frontend/src/pages/executions/index.tsx`

Impact:
- REQ_0009 says visibility must be present in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness.
- The required explainability contract is not present on most named website surfaces.

### 2. Backend explainability endpoints are skeleton metadata, not usable read/explain APIs

Blocking evidence:
- `v2/backend/app/api/v1/features.py`, `predictions.py`, `decisions.py`, `risk_decisions.py`, and `paper.py` describe themselves as scaffold-only and expose only an OPTIONS metadata shim.
- These files declare intended endpoints such as `/{prediction_id}/explain`, `/{decision_id}/explain`, and `/{risk_decision_id}/explain`, but do not implement GET handlers that return explainability payloads.

Impact:
- The website has no backend contract to fetch real `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, risk checks, contributor lists, source freshness, or audit timeline by entity ID.
- The UI cannot truthfully satisfy the contract without hardcoded or fixture data.

### 3. `feature_snapshot_id`, `prediction_id`, and `risk_decision_id` visibility is partial and fixture-scoped

Observed:
- `v2/frontend/src/lineage/block.tsx` defines a reusable `LineageBlockView` with `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, and execution intent display.
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` displays `feature_snapshot_id`, `prediction_id`, and `risk_decision_id` only for the selected LABUSDT proof explanation.

Blockers:
- `LineageBlockView` is not wired into the contract-critical pages found in the page registry.
- The operator proof dashboard omits full lineage visibility in its risk blocks, paper ledger rows, shadow comparison rows, and historical comparison rows even though row types contain lineage fields.
- The dashboard uses committed proof artifacts under `v2/frontend/public/...`, not live/read-side backend records.

Impact:
- The requested identifier visibility exists as code fragments but is not contract-ready as a website-wide explainability surface.

### 4. Paper/shadow/legacy comparison is visible only as proof fixture summaries

Observed:
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` renders `ShadowComparison`, `PaperLedger`, and `Historical30DSection`.
- Historical and non-live proof builders explicitly use deterministic fixtures:
  - `v2/backend/app/proof/non_live_operational_proof.py` uses `mode: offline_fixture` and fixture IDs.
  - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` uses `mode: offline_deterministic_historical_fixture` and limitations that say realized PnL values are fixture values.

Blocker:
- REQ_0009 asks for paper/shadow/legacy comparison as part of decision explainability. The current website shows a proof artifact dashboard, not a per-decision paper/shadow/legacy explainability contract across the required pages.

Impact:
- The comparison is useful operator proof, but it is not sufficient for website contract readiness.

### 5. No fake reasoning guard is not fully satisfied

Positive evidence:
- The proof artifacts label themselves as fixtures/offline deterministic proof and include limitations.

Blocking evidence:
- `v2/backend/app/proof/non_live_operational_proof.py` synthesizes `explanation_payload.summary` and `causes` from deterministic scenario fields.
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` displays those synthetic causes as "Decision Explainability".
- Backend real explain endpoints are not implemented, so the website cannot distinguish evidence-derived explanation from generated fixture explanation for production/read-side entities.

Impact:
- The system avoids live side effects, but the website is not yet protected against presenting fixture/synthetic explanation as real operational reasoning outside the proof-dashboard context.

## Contract Checklist

- `feature_snapshot_id` visibility: PARTIAL, BLOCKED. Present in type definitions and one proof-detail panel, not wired across required pages/rows.
- `prediction_id` visibility: PARTIAL, BLOCKED. Present in type definitions and one proof-detail panel, not wired across required pages/rows.
- `risk_decision_id` visibility: PARTIAL, BLOCKED. Present in type definitions and one proof-detail panel, not wired across required pages/rows.
- Paper/shadow comparison visibility: PARTIAL, BLOCKED. Present only in fixture/proof dashboard summaries.
- No fake reasoning: BLOCKED. Fixture explanations are labeled by artifact mode in source data, but the UI displays synthetic causes as decision explainability and real explain endpoints are absent.

## Concrete Blockers

1. Implement backend read/explain endpoints for feature snapshots, predictions, decisions, risk decisions, execution intents, paper trades, shadow comparisons, and audit timeline.
2. Define a single website explainability response schema that includes all REQ_0009 fields, including source freshness, top positive/negative contributors, stale/missing/unused flags, risk checks, sizing reason, action reason, blocked-trade reason, and evidence mode.
3. Wire `LineageBlockView` or an equivalent full-chain component into Mission Control, Trainer Prediction Monitor, Signal Explainability, Symbol Universe, Risk Gateway/Risk Control, Paper/Shadow Trading, Audit Ledger, and Live Readiness.
4. Replace placeholder `PageShell` bodies on contract-critical pages with read-only explainability views backed by non-live/read-side APIs.
5. Expand paper/shadow/legacy comparison UI from fixture summary tables into per-decision comparison with visible lineage IDs and evidence source labels.
6. Add a UI guard that labels fixture, replay, paper, shadow, and live-blocked evidence modes explicitly and never renders synthetic fixture causes as real model/risk reasoning.
7. Add tests that assert required IDs and explanation fields are visible on each required page and that missing lineage is shown as a gap, not silently omitted.

## Proposed Non-Live Autofix Tasks

1. Add read-only backend schemas for `DecisionExplainabilityRead`, `ConfidenceExplanationRead`, `FeatureContributorRead`, `RiskCheckRead`, `PaperShadowComparisonRead`, and `AuditTimelineEventRead`.
2. Implement non-mutating GET endpoints using repositories or committed proof/read-side fixtures only; keep POST/order/leverage/live-trading paths untouched.
3. Create a frontend `ExplainabilityPanel` component that renders full lineage, confidence deltas, feature contributors, source freshness, risk checks, action reasons, paper/shadow/legacy comparison, and audit timeline.
4. Replace `PageShell` placeholders on the required pages with read-only data-loading views and explicit empty/error/gap states.
5. Update operator proof dashboard tables to show `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, and `execution_intent_id` per row.
6. Add Playwright tests for identifier visibility and fixture/evidence-mode labeling on all required pages.

## Safety Notes

No live systems were restarted. No Redis writes/deletes were performed. No orders, leverage/margin, live-trading toggles, deployments, or secret exposure were performed during this review.
