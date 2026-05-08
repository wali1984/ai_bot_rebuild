# Codex Parallel Review: Website Explainability Contract Readiness

Review topic: Website Explainability Contract Readiness
Review date: 2026-05-08
Result: BLOCKED

## Scope Inspected

- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

## Contract Checks

| Check | Status | Evidence |
| --- | --- | --- |
| `feature_snapshot_id` visibility | BLOCKED | `LineageBlockView` supports `feature_snapshot_id`, but `rg` finds no use of `LineageBlockView` under `v2/frontend/src/pages` or `v2/frontend/src/components`; required pages render placeholder `PageShell` content instead. |
| `prediction_id` visibility | BLOCKED | `LineageBlockView` supports `prediction_id`, but it is unused by the website pages. Backend `/predictions` is metadata-only skeleton. |
| `risk_decision_id` visibility | BLOCKED | `LineageBlockView` supports `risk_decision_id`, but it is unused. Backend `/risk-decisions` exposes only `OPTIONS /` route metadata and declares `milestone_d_status: skeleton`. |
| Paper/shadow comparison visibility | BLOCKED | No frontend implementation was found for paper/shadow/legacy comparison. Backend paper/shadow services exist only as partial assembly helpers or flags; `/paper-trades` is skeleton route metadata only. |
| No fake reasoning | PARTIAL | The UI does not fabricate reasoning; it openly renders a placeholder shell. This avoids fake reasoning but also means real source-backed reasoning is not visible. |

## Concrete Blockers

1. Required website pages do not render explainability content.
   - `v2/frontend/src/components/layout/PageShell.tsx:25` renders a generic milestone placeholder body.
   - `v2/frontend/src/pages/signal-explainability/index.tsx`, `trainer-prediction-monitor/index.tsx`, `risk-control/index.tsx`, `audit-ledger/index.tsx`, `symbols/index.tsx`, `paper-trading/index.tsx`, `executions/index.tsx`, and `live-readiness/index.tsx` delegate to this placeholder shell.
   - Mission Control adds health/queue/build panels, but no full decision lineage or paper/shadow comparison panel.

2. The reusable lineage UI is not integrated.
   - `v2/frontend/src/lineage/block.tsx:1` defines fields for `prediction_id`, `decision_id`, `risk_decision_id`, `intent_id`, and `feature_snapshot_id`.
   - Search found no page/component imports or renders of `LineageBlockView`.
   - Therefore the required ID visibility is component-level potential, not website-level readiness.

3. Backend lineage endpoints are skeleton metadata, not explainability data contracts.
   - `v2/backend/app/api/v1/features.py`, `predictions.py`, `signals.py`, `decisions.py`, `risk_decisions.py`, and `paper.py` expose only `OPTIONS /` route metadata.
   - `v2/backend/app/api/v1/risk_decisions.py:16` declares required IDs, but there is no `GET /risk-decisions/{risk_decision_id}/explain` implementation returning risk checks, sizing reason, blocked-trade reason, or final decision reason.
   - `v2/backend/app/api/v1/paper.py:14` declares the paper trade route group, but does not return paper/shadow/legacy comparison records.

4. Required explanation fields from REQ 0009 are not visible.
   Missing from implemented pages: confidence delta, positive/negative feature contributors, stale/missing/unused feature flags, source freshness by ingestor, risk checks, position sizing reason, open/close/hedge reason, blocked-trade reason, audit timeline, and paper/shadow/legacy comparison.

5. Required page coverage is incomplete.
   REQ 0009 requires visibility in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness. The current routes are mostly placeholders, and no `Feature Attribution` or `Trader Fleet` page implementation was found in `v2/frontend/src/pages`.

## Proposed Non-Live Autofix Tasks

1. Add read-only backend explainability DTOs and GET endpoints for `/feature-snapshots/{id}/explain`, `/predictions/{id}/explain`, `/signals/{id}/explain`, `/decisions/{id}/explain`, `/risk-decisions/{id}/explain`, and `/paper-trades/{id}/explain`.
   - Return explicit null/missing fields plus `lineage_gap_reason` when source evidence is unavailable.
   - Do not synthesize reasons. Every reason should be copied from domain records, audit records, or marked unavailable.

2. Wire `LineageBlockView` into the required admin pages with real API data.
   - At minimum surface `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, and `execution_intent_id`.
   - Add missing-route tests that assert unavailable IDs display `missing` plus `lineage_gap_reason`, not invented values.

3. Build a read-only `DecisionExplainabilityPanel`.
   - Sections: lineage IDs, confidence change, contributor table, source freshness, risk checks, sizing/open/close/hedge/block reasons, execution mode, final decision reason, and audit timeline.
   - Use backend evidence fields only; show `not recorded` or `lineage_gap_reason` for gaps.

4. Build a read-only paper/shadow/legacy comparison panel.
   - Inputs: paper ledger entry, shadow readiness/status, replay/backtest step summary, legacy mapped comparison if available.
   - Output: side-by-side action, reason code, PnL/result attribution, and source record IDs.

5. Add frontend route coverage for missing required surfaces.
   - Add or map Feature Attribution and Trader Fleet pages.
   - Ensure Mission Control links to per-decision drilldowns instead of only health panels.

6. Add contract tests.
   - Backend tests should fail if explain endpoints return skeleton metadata only.
   - Frontend tests should fail if required pages lack `data-testid="lineage-block"` and required explainability sections.
   - Add a no-fake-reasoning test fixture where missing evidence must render `missing`/`not recorded` rather than generated prose.

## Safety Notes

- No live services were restarted.
- No Redis reads or writes were performed.
- No live trading, leverage, margin, order, deployment, or secret-touching actions were performed.
