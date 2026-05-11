# Website Explainability Contract Readiness Review

Review mode: read-only parallel review. No live services, Redis writes, trading controls, orders, deployment, or files outside this report contract were touched.

Requirement source: `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

## Verdict

BLOCKED.

The website has partial explainability surfaces, but it is not contract-ready for REQ_0009. Mission Control, Trainer Prediction Monitor, Signal Explainability, and Risk Control expose some lineage fields through the shared `DecisionDrawers`, but several required pages are still generic evidence-gap shells, backend explain endpoints are skeleton-only, and paper/shadow/legacy comparison is not visibly rendered as first-class comparison data in the relevant website pages.

## Findings

1. Partial identifier visibility exists, but only through fixture-backed cockpit decisions.

Evidence:
- `v2/frontend/src/pages/cockpitComponents.tsx:145` defines `DecisionDrawers`.
- `v2/frontend/src/pages/cockpitComponents.tsx:157` shows `feature_snapshot_id`.
- `v2/frontend/src/pages/cockpitComponents.tsx:152` shows `prediction_id` in the drawer summary.
- `v2/frontend/src/pages/cockpitComponents.tsx:160` shows `risk_decision_id`.
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:155` contains `prediction_id`.
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:156` contains `feature_snapshot_id`.
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:159` contains `risk_decision_id`.

Assessment:
- `feature_snapshot_id`: visible where `DecisionDrawers` is mounted.
- `prediction_id`: visible where `DecisionDrawers` is mounted.
- `risk_decision_id`: visible where `DecisionDrawers` is mounted.
- Coverage is incomplete because several required pages do not mount this drawer or an equivalent dedicated contract surface.

2. Required website pages are not all implemented as explainability surfaces.

Evidence:
- `v2/frontend/src/pages/paper-trading/index.tsx:5` returns only `PageShell`.
- `v2/frontend/src/pages/symbols/index.tsx:5` returns only `PageShell`.
- `v2/frontend/src/pages/audit-ledger/index.tsx:5` returns only `PageShell`.
- `v2/frontend/src/pages/live-readiness/index.tsx:5` returns only `PageShell`.
- `v2/frontend/src/pages/executions/index.tsx:5` returns only `PageShell`.
- `v2/frontend/src/components/layout/PageShell.tsx:26` explicitly says the route needs a dedicated data payload before live-readiness decisions.

Impact:
REQ_0009 requires visibility in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness. Several of those surfaces are either missing as dedicated pages or only appear inside `operator-proof-dashboard`, not on the named route.

3. Paper/shadow/legacy comparison is not contract-ready on the website.

Evidence:
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:175` links to `legacy_vs_v2_decision_comparison.json`, but the shared `DecisionDrawers` renders only `result`, not comparison rows or divergence fields.
- `v2/frontend/src/pages/risk-control/index.tsx:23` shows only `paper/shadow/live result`.
- `v2/frontend/src/pages/paper-trading/index.tsx:5` is a generic evidence-gap shell.
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:657` has a Trader Fleet section and `:662` renders `Shadow comparisons`, but this is not the named Paper / Shadow Trading page and is not wired into the shared explainability contract.

Impact:
The user can see that an evidence link exists, but cannot inspect paper vs shadow vs legacy decisions, divergence status, action differences, or PnL attribution from the required website surfaces.

4. Backend explainability endpoints are skeleton-only.

Evidence:
- `v2/backend/app/api/v1/features.py:1` says scaffold-only.
- `v2/backend/app/api/v1/features.py:21` marks `milestone_d_status` as `skeleton`.
- `v2/backend/app/api/v1/predictions.py:1` says scaffold-only and `:21` marks skeleton.
- `v2/backend/app/api/v1/signals.py:1` says scaffold-only and `:21` marks skeleton.
- `v2/backend/app/api/v1/decisions.py:1` says scaffold-only and `:24` marks skeleton.
- `v2/backend/app/api/v1/risk_decisions.py:1` says scaffold-only and `:25` marks skeleton.
- `v2/backend/app/api/v1/paper.py:1` says scaffold-only and `:28` marks skeleton.

Impact:
The frontend currently relies on static public proof payloads. It cannot satisfy “for every major system decision” until these explain endpoints return real, read-only, lineage-bearing records or an explicit evidence-missing contract.

5. No-fake-reasoning posture is partially present but not sufficient.

Evidence:
- `v2/frontend/src/pages/signal-explainability/index.tsx:13` renders a “No-Guessing Rule” panel.
- `v2/frontend/src/pages/signal-explainability/index.tsx:14` says evidence is missing and cannot explain without guessing.
- `v2/frontend/src/pages/cockpitComponents.tsx:180` uses “Evidence missing - cannot explain without guessing” when missing flags are empty.
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:184` marks decision data as `STATIC_PROOF_FIXTURE`.

Assessment:
This is directionally correct, but the UI still displays canned fixture reasons such as `fresh_features_and_positive_regime`, `paper_long_intent_only`, and `allow_paper_only` as explanation values. Without a clear per-row evidence classification, source pointer, and comparison detail display, operators can mistake fixtures for live/current reasoning.

## Contract Checklist

- `feature_snapshot_id` visibility: PARTIAL.
- `prediction_id` visibility: PARTIAL.
- `risk_decision_id` visibility: PARTIAL.
- Paper/shadow comparison visibility: BLOCKED.
- No fake reasoning: PARTIAL/BLOCKED until fixture and missing-evidence boundaries are enforced per row and per page.

## Concrete Blockers

1. Named REQ_0009 pages are still generic shells or absent as dedicated explainability pages.
2. Paper / Shadow Trading page does not render paper ledger rows, shadow comparison rows, divergence fields, legacy comparison, or PnL attribution.
3. Symbol Universe page does not render symbol state reasons, source discovery evidence, exchange confirmations, feature completeness, overrides, or observed/training/paper/shadow/live-blocked state reasons.
4. Audit Ledger page does not render audit timeline linked to `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, and `execution_intent_id`.
5. Backend `/explain` routes are skeleton-only and cannot back real website explainability.
6. Shared `DecisionRow` lacks first-class paper/shadow/legacy comparison fields, risk check arrays, sizing reason, open/close/hedge reason, blocked-trade reason, regime context, and data-quality impact fields.
7. Fixture-backed reasons are visible without a strong per-row “STATIC_PROOF_FIXTURE / not current runtime explanation” marker inside each drawer.

## Proposed Non-Live Autofix Tasks

1. Add a typed `ExplanationContractRow` frontend model extending `DecisionRow` with:
   `decision_id`, `paper_action`, `shadow_action`, `legacy_action`, `comparison_status`, `divergence_reason`, `paper_pnl_attribution`, `risk_checks`, `position_sizing_reason`, `open_close_hedge_reason`, `blocked_trade_reason`, `regime_context`, `data_quality_impact`, and `source_classification`.

2. Update `DecisionDrawers` to render:
   lineage IDs, source classification, confidence explanation, risk checks, sizing/open-close-hedge/block reasons, evidence links, and an explicit paper/shadow/legacy comparison table.

3. Replace generic shells for `paper-trading`, `symbols`, `audit-ledger`, `live-readiness`, `executions`, and any missing Feature Attribution / Trader Fleet route with read-only evidence panels that either render contract data or clearly show `MISSING_EVIDENCE`.

4. Add frontend contract tests that fail if required labels are absent:
   `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `paper_action`, `shadow_action`, `legacy_action`, `comparison_status`, `blocked_trade_reason`, and `Evidence missing - cannot explain without guessing`.

5. Implement read-only backend `/explain` endpoints using existing repository/service layers or static proof readers only. Return explicit `source_classification` values and never infer missing fields.

6. Add a no-fake-reasoning validator for website payloads:
   fail if any row has reason text without an evidence link, source pointer, source classification, and missing-evidence status for absent fields.

7. Keep all autofixes non-live:
   no Redis writes, no Redis deletes, no order placement, no live service restart, no leverage/margin changes, and no live trading enablement.
