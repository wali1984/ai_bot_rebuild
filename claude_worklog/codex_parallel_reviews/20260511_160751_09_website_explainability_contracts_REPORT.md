# Codex Parallel Review: Website Explainability Contract Readiness

Review topic: Website Explainability Contract Readiness
Reviewed at: 2026-05-11 16:07:51
Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The current website is not ready for the full explainability contract. Some lineage identifiers are visible in the shared Mission Control / Signal Explainability / Trainer Prediction Monitor decision drawer, but multiple required website pages are still registered shells, paper/shadow comparison is not part of the main decision row contract, and backend explain endpoints remain metadata skeletons.

## Checks

### feature_snapshot_id visibility

Partial pass.

Evidence:
- `v2/frontend/src/pages/cockpitData.ts:41` defines `DecisionRow.feature_snapshot_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:150` renders `feature_snapshot_id` inside `DecisionDrawers`.
- `v2/frontend/src/pages/mission-control/index.tsx` uses `DecisionDrawers` for Mission Control.
- `v2/frontend/src/pages/signal-explainability/index.tsx` and `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx` also use `DecisionDrawers`.

Blocker:
- The required dedicated pages for Risk Gateway, Paper / Shadow Trading, Audit Ledger, Symbol Universe, and related decision-chain views still use generic `PageShell`, which explicitly says evidence is missing.

### prediction_id visibility

Partial pass.

Evidence:
- `v2/frontend/src/pages/cockpitData.ts:45` defines `DecisionRow.prediction_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:145` renders `prediction_id` in the drawer summary.
- `v2/frontend/src/pages/cockpitComponents.tsx:150-161` renders the surrounding lineage chain.

Blocker:
- Visibility depends on static cockpit payload rows and shared drawers, not on implemented prediction read/explain endpoints.

### risk_decision_id visibility

Partial pass.

Evidence:
- `v2/frontend/src/pages/cockpitData.ts:49` defines `DecisionRow.risk_decision_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:153` renders `risk_decision_id`.
- `v2/backend/app/api/v1/risk_decisions.py:16-29` advertises risk decision lineage metadata.

Blocker:
- `v2/backend/app/api/v1/risk_decisions.py:1-35` is scaffold-only and exposes only an OPTIONS metadata shim, not usable GET/explain read models for website contract readiness.

### paper/shadow comparison visibility

Blocked.

Evidence:
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` has an operator proof surface with `paper_shadow_live_blocked_action` and `TraderFleet` shadow comparison rendering.
- Static proof artifacts under `v2/frontend/public/non_live_operational_proof/latest/` include paper/shadow fixture comparison records.

Blockers:
- `DecisionRow` in `v2/frontend/src/pages/cockpitData.ts:41-67` does not include `paper_trade_id`, `shadow_decision_id`, `legacy_action`, `v2_action`, or explicit paper-vs-shadow-vs-legacy comparison fields.
- `DecisionDrawers` in `v2/frontend/src/pages/cockpitComponents.tsx:138-178` renders `result` but does not render a structured paper/shadow/legacy comparison.
- `v2/frontend/src/pages/paper-trading/index.tsx`, `v2/frontend/src/pages/risk-control/index.tsx`, `v2/frontend/src/pages/audit-ledger/index.tsx`, and `v2/frontend/src/pages/symbols/index.tsx` all route through `PageShell`; `PageShell` renders “Evidence missing - this route is registered but needs a dedicated data payload before it can be used for live-readiness decisions” at `v2/frontend/src/components/layout/PageShell.tsx:25-29`.
- `v2/backend/app/api/v1/paper.py:1-34` is scaffold-only and exposes only route metadata for `/paper-trades`, not paper/shadow explanation data.

### no fake reasoning

Partial pass with caveat.

Evidence:
- The UI labels missing explanation data as evidence missing rather than guessing. Example: `v2/frontend/src/pages/cockpitComponents.tsx:173` renders “Evidence missing - cannot explain without guessing” when missing flags are absent.
- Static fixture usage is usually labeled as `STATIC_PROOF_FIXTURE` or source pointers in payloads.

Caveat:
- Static fixture payloads can support non-live demos, but they are not sufficient for contract readiness unless every displayed explanation is traceable to a real persisted decision/explain endpoint or explicitly marked as fixture-only.

## Concrete blockers

1. Required pages are not contract-complete.
   - Risk Gateway, Paper / Shadow Trading, Audit Ledger, Symbol Universe, Execution Admin, and Orchestrator Admin still render generic `PageShell` evidence gaps rather than full lineage/explainability data.

2. Backend explain routes are skeletons.
   - `/predictions/{id}/explain`, `/decisions/{id}/explain`, `/risk-decisions/{id}/explain`, `/execution-intents/{id}/explain`, and `/paper-trades/{id}/explain` are advertised in metadata, but the inspected route modules do not implement usable GET/explain handlers.

3. The main website decision contract omits paper/shadow/legacy comparison fields.
   - The shared `DecisionRow` contract exposes lineage IDs and confidence fields, but not structured `paper_trade_id`, `shadow_decision_id`, `legacy_action`, `v2_action`, comparison outcome, or PnL attribution fields.

4. Audit timeline visibility is not implemented on the dedicated Audit Ledger page.
   - The page is registered but renders the generic evidence-missing shell.

5. Symbol universe explanation is not implemented on the dedicated Symbols page.
   - The requirement asks for discovery evidence, exchange evidence, scores, state, overrides, and state reasons. The dedicated page currently does not render those fields.

## Proposed non-live autofix tasks

1. Add backend read-only explain endpoints.
   - Implement GET-only handlers for prediction, decision, risk decision, execution intent, and paper-trade explain routes.
   - Source from persisted repositories or committed non-live proof artifacts only.
   - Return explicit `lineage_gap_reason` when a link is missing.

2. Expand the frontend decision contract.
   - Add structured fields to `DecisionRow`: `decision_id` alias or canonical field, `paper_trade_id`, `shadow_decision_id`, `legacy_action`, `v2_action`, `comparison_outcome`, `paper_pnl`, `shadow_result`, `blocked_trade_reason`, and `audit_timeline`.
   - Render those fields in `DecisionDrawers` without inventing values.

3. Replace PageShell placeholders for required pages with read-only data panels.
   - Risk Gateway: policy checks, risk decision ID, block/allow reason, sizing reason, stale/duplicate/exposure/drawdown checks, live gate status.
   - Paper / Shadow Trading: paper ledger, shadow comparison, live-blocked action, PnL attribution.
   - Audit Ledger: append-only timeline linked to the same lineage IDs.
   - Symbol Universe: discovery evidence, exchange confirmations, score breakdown, manual overrides, state reason.

4. Add contract tests.
   - Frontend tests should assert visible `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper/shadow comparison fields, and explicit evidence-missing states.
   - Backend tests should assert all explain endpoints are GET-only, side-effect-free, and never synthesize reasoning when source data is missing.

5. Preserve safety constraints.
   - All autofixes should be non-live, read-only, and fixture-or-database backed.
   - Do not write Redis, restart services, place/cancel orders, change leverage/margin, enable live trading, or deploy.

