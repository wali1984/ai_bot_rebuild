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
| `feature_snapshot_id` visibility | BLOCKED | `v2/frontend/src/lineage/block.tsx:7` supports the field, but `rg` found no imports/renders of `LineageBlockView` outside its own file. Required pages render the generic `PageShell` placeholder. |
| `prediction_id` visibility | BLOCKED | `v2/frontend/src/lineage/block.tsx:2` supports the field, but it is not mounted on the website pages. `v2/backend/app/api/v1/predictions.py` is route metadata only. |
| `risk_decision_id` visibility | BLOCKED | `v2/frontend/src/lineage/block.tsx:5` supports the field, but it is unused. `v2/backend/app/api/v1/risk_decisions.py:1` says scaffold-only and exposes only an OPTIONS metadata shim. |
| Paper/shadow comparison visibility | BLOCKED | No frontend implementation found for paper/shadow/legacy comparison. `v2/backend/app/api/v1/paper.py:1` is scaffold-only route metadata, not a read contract returning comparison data. |
| No fake reasoning | PARTIAL | The website does not appear to fabricate decision prose; it displays placeholder shells instead. This avoids fake reasoning but also means real source-backed reasoning is not visible. |

## Concrete Blockers

1. Required website pages do not render explainability content.
   - `v2/frontend/src/components/layout/PageShell.tsx:25` renders a milestone placeholder body.
   - `v2/frontend/src/pages/signal-explainability/index.tsx`, `trainer-prediction-monitor/index.tsx`, `risk-control/index.tsx`, `audit-ledger/index.tsx`, `symbols/index.tsx`, `paper-trading/index.tsx`, `executions/index.tsx`, and `live-readiness/index.tsx` delegate to `PageShell`.
   - Mission Control adds health/queue/stale/build panels, but no full decision lineage, risk explainability, or paper/shadow comparison panel.

2. The reusable lineage UI is not integrated.
   - `v2/frontend/src/lineage/block.tsx:1` defines a display component for lineage fields.
   - Search found no page/component usage of `LineageBlockView`.
   - It also uses `intent_id` rather than the backend/schema contract field `execution_intent_id`, so even if mounted it would not exactly match REQ 0009.

3. Backend explainability endpoints are skeleton metadata.
   - `v2/backend/app/api/v1/features.py`, `predictions.py`, `signals.py`, `decisions.py`, `risk_decisions.py`, `intents.py`, and `paper.py` advertise `/{id}/explain` in metadata but do not implement GET handlers.
   - `v2/backend/app/api/v1/risk_decisions.py:16` declares required IDs, but returns no risk checks, sizing reason, blocked-trade reason, or final decision reason.
   - `v2/backend/app/api/v1/paper.py:14` declares paper trade endpoints, but returns no paper/shadow/legacy comparison record.

4. Required REQ 0009 explanation fields are not visible.
   Missing from implemented website pages: confidence delta, positive/negative feature contributors, stale/missing/unused feature flags, source freshness by ingestor, risk checks, position sizing reason, open/close/hedge reason, blocked-trade reason, audit timeline, and paper/shadow/legacy comparison.

5. Required page coverage is incomplete.
   REQ 0009 requires visibility in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness. Current matching pages are mostly placeholders, and no dedicated Feature Attribution or Trader Fleet page implementation was found under `v2/frontend/src/pages`.

## Proposed Non-Live Autofix Tasks

1. Add read-only backend explainability DTOs and GET handlers for `/feature-snapshots/{id}/explain`, `/predictions/{id}/explain`, `/signals/{id}/explain`, `/decisions/{id}/explain`, `/risk-decisions/{id}/explain`, `/execution-intents/{id}/explain`, and `/paper-trades/{id}/explain`.
   - Return explicit nulls plus `lineage_gap_reason` when evidence is unavailable.
   - Do not synthesize reasons; copy reason codes/details from domain records, audit records, or mark them `not_recorded`.

2. Wire a contract-correct lineage component into required admin pages.
   - Surface `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, and `execution_intent_id`.
   - Fix frontend `intent_id` naming to `execution_intent_id`.

3. Build a read-only decision explainability panel.
   - Sections: lineage IDs, confidence change, contributor table, source freshness, risk checks, sizing/open/close/hedge/block reasons, execution mode, final decision reason, and audit timeline.
   - Render missing evidence as `missing`, `not_recorded`, or the supplied `lineage_gap_reason`.

4. Build a read-only paper/shadow/legacy comparison panel.
   - Inputs: paper ledger entry, shadow readiness/status, replay/backtest summary, and legacy mapped comparison if available.
   - Output: side-by-side action, reason code, result/PnL attribution, and source record IDs.

5. Add frontend route coverage for missing required surfaces.
   - Add or map Feature Attribution and Trader Fleet pages.
   - Ensure Mission Control links to per-decision drilldowns instead of only status panels.

6. Add contract tests.
   - Backend tests should fail if explain endpoints return skeleton metadata only.
   - Frontend tests should fail if required pages lack `data-testid="lineage-block"` and required explainability sections.
   - Add a no-fake-reasoning fixture where missing evidence must render `missing` or `not_recorded`, not generated prose.

## Safety Notes

- No live services were restarted.
- No Redis reads or writes were performed.
- No live trading, leverage, margin, order, deployment, or secret-touching actions were performed.
