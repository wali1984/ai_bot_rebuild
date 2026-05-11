# Website Explainability Contract Readiness Review

Review timestamp: 2026-05-11 05:25:47
Review mode: read-only parallel review, non-live
Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The website is not ready for the full REQ_0009 explainability contract. The Signal Explainability and Trainer Prediction Monitor views expose several critical lineage fields and use explicit evidence-gap language, but required contract surfaces are still partial, static, or skeleton-only.

## Checks

### feature_snapshot_id visibility

Partial pass.

Evidence:
- `v2/frontend/src/pages/cockpitData.ts:41` defines `DecisionRow.feature_snapshot_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:141` renders `feature_snapshot_id` in the decision drawer.
- `v2/backend/app/api/v1/predictions.py:20` advertises `feature_snapshot_id` as a required stage ID.

Blocker:
- The backend prediction route is explicitly skeleton-only (`v2/backend/app/api/v1/predictions.py:1-4`, `:21`) and exposes only OPTIONS metadata, not a real read/explain payload.

### prediction_id visibility

Partial pass.

Evidence:
- `v2/frontend/src/pages/cockpitData.ts:45` defines `DecisionRow.prediction_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:136` renders the prediction ID in the drawer summary.
- `v2/backend/app/api/schemas/prediction.py` defines the prediction read/ingest schema with `prediction_id`.

Blocker:
- The `/predictions/{prediction_id}/explain` endpoint is metadata-only and marked skeleton (`v2/backend/app/api/v1/predictions.py:17`, `:21`), so the website cannot rely on a live contract-backed explanation source.

### risk_decision_id visibility

Partial pass.

Evidence:
- `v2/frontend/src/pages/cockpitData.ts:49` defines `DecisionRow.risk_decision_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:144` renders `risk_decision_id`.
- `v2/backend/app/api/v1/risk_decisions.py:22-28` advertises the full upstream stage ID chain through `risk_decision_id`.

Blocker:
- The dedicated risk-decision API is also skeleton-only (`v2/backend/app/api/v1/risk_decisions.py:1-4`, `:29`).
- The visible Risk Control page is still the generic placeholder shell (`v2/frontend/src/pages/risk-control/index.tsx:5-6`, `v2/frontend/src/components/layout/PageShell.tsx:26-28`), not a Risk Gateway explainability page.

### paper/shadow comparison visibility

Blocked.

Evidence:
- The operator proof dashboard has a Paper/Shadow section path and can render arbitrary paper/shadow rows (`v2/frontend/src/pages/operator-proof-dashboard/index.tsx:657-663`).
- The `DecisionDrawers` result field can show a terminal result (`v2/frontend/src/pages/cockpitComponents.tsx:151-152`).

Blockers:
- The required Paper / Shadow Trading page is only a placeholder shell (`v2/frontend/src/pages/paper-trading/index.tsx:5-6`, `v2/frontend/src/components/layout/PageShell.tsx:26-28`).
- The backend paper-trades route is metadata-only and skeleton (`v2/backend/app/api/v1/paper.py:1-4`, `:28`).
- No active frontend contract in the reviewed page-specific Paper Trading route guarantees side-by-side paper, shadow, legacy comparison, divergence, and PnL attribution visibility.

### no fake reasoning

Partial pass.

Evidence:
- Missing values render as `Evidence missing` instead of fabricated text (`v2/frontend/src/pages/cockpitData.ts:643-645`).
- Missing flags in the main decision drawer explicitly say `Evidence missing - cannot explain without guessing` (`v2/frontend/src/pages/cockpitComponents.tsx:164`).
- Static chart evidence is labeled as `STATIC_PROOF_FIXTURE` when the read-only market feed is not wired (`v2/frontend/src/pages/cockpitComponents.tsx:121-124`).

Residual risk:
- Static proof fixtures and broad `reason` strings are acceptable only if clearly labeled at every consuming page. The current generic placeholder pages cannot prove that requirement for the full REQ_0009 page set.

## Concrete Blockers

1. Backend explain endpoints are skeleton-only for predictions, risk decisions, and paper trades. The advertised `/{id}/explain` endpoints do not provide real contract-backed explanation documents.
2. Required website pages are not all explainability-capable. `Paper Trading` and `Risk Control` use `PageShell`, which explicitly says the route lacks a dedicated data payload for live-readiness decisions.
3. Paper/shadow comparison visibility is not guaranteed in the required Paper / Shadow Trading page. Existing visibility appears in the operator proof dashboard, not the required route-specific page.
4. The main `DecisionDrawers` omits `unused_flags` from rendering even though the type includes it and REQ_0009 requires stale/missing/unused feature flags.
5. The current UI does not prove complete visibility for all REQ_0009 pages: Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness.

## Proposed Non-Live Autofix Tasks

1. Implement read-only `/api/v1/predictions/{prediction_id}/explain`, `/api/v1/risk-decisions/{risk_decision_id}/explain`, and `/api/v1/paper-trades/{paper_trade_id}/explain` handlers backed by deterministic local repositories or static proof artifacts. Do not touch Redis or live services.
2. Replace `PageShell` usage for `paper-trading` and `risk-control` with read-only contract components that render lineage IDs, risk checks, blocked/allow reasons, execution mode, paper/shadow comparison, divergence, and PnL attribution from local/public proof payloads.
3. Add an explicit `unused_flags` mini-list to `DecisionDrawers` and route-level tests proving stale, missing, and unused flags render without fabricated reasoning.
4. Add a `paper_shadow_comparison` typed frontend model and require rows to include paper action, shadow action, legacy action when available, divergence flag, result/PnL attribution, and evidence source label.
5. Add Playwright checks for every REQ_0009 required page that assert visibility of `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, evidence-gap language, and paper/shadow comparison where applicable.
6. Add backend contract tests proving explain endpoints return explicit nulls/evidence gaps rather than omitted IDs or invented rationale.

## Safety Notes

No live service restarts, Redis writes/deletes, order placement/cancellation, leverage/margin changes, deployment, or live-trading enablement were performed. This review only inspected local files and wrote this report plus the GO/NO-GO marker.
