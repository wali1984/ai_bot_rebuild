# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Result: BLOCKED

Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Requirement baseline:
- The website must expose full decision lineage from raw source data through feature snapshot, trainer prediction, signal, orchestrator decision, risk gateway decision, execution intent, paper/shadow/live-blocked action, and result/PnL attribution.
- Required visible fields include `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper/shadow/legacy comparison, and factual explanations without fake reasoning.

Findings:

1. Required explainability pages are mostly placeholder shells.
   Evidence: `v2/frontend/src/components/layout/PageShell.tsx:25` renders only a milestone placeholder body. Pages such as Signal Explainability, Trainer Prediction Monitor, Risk Control, Paper Trading, Symbol Universe, Audit Ledger, and Live Readiness delegate to this shell instead of rendering decision lineage or explanation data.
   Impact: REQ_0009 says the visibility must exist in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness. Current UI does not satisfy that page-level contract.

2. Backend explainability endpoints are route metadata skeletons, not read/explain implementations.
   Evidence: `v2/backend/app/api/v1/features.py:1` says scaffold-only and only exposes an OPTIONS metadata shim. `v2/backend/app/api/v1/risk_decisions.py:1` has the same skeleton pattern for risk decisions. The same pattern exists for predictions, signals, decisions, execution intents, and paper trades.
   Impact: The website has no real backend contract to retrieve per-ID `/explain` payloads for feature snapshots, predictions, decisions, risk decisions, intents, or paper trades.

3. `feature_snapshot_id`, `prediction_id`, and `risk_decision_id` are only partially visible.
   Evidence: `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:281` renders those three IDs only for the LABUSDT proof explanation. Historical table row types include lineage IDs at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:83`, but the visible historical table columns at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:371` omit those IDs.
   Impact: Operators cannot inspect required IDs across every decision row or required page.

4. Paper/shadow comparison visibility exists only as static proof-fixture dashboard output.
   Evidence: `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:241` renders a shadow comparison table from `/non_live_operational_proof/latest`, and `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:317` renders historical legacy-vs-V2 fixture comparisons.
   Impact: This is useful non-live proof evidence, but it is not wired to the actual explainability pages or live-blocked/paper/shadow decision read models required by REQ_0009.

5. Current explanations are deterministic fixture summaries, not full factual reasoning chains.
   Evidence: `v2/backend/app/proof/non_live_operational_proof.py:187` builds explanation causes from fixture fields such as feature freshness, duplicate signal, squeeze context, and requested action. `v2/backend/app/proof/non_live_operational_proof.py:228` labels the replay mode `offline_fixture`, and `v2/backend/app/proof/non_live_operational_proof.py:237` includes `max_drawdown_placeholder`.
   Impact: The proof data is clearly non-live and local, but it is not enough for website contract readiness. The production UI must avoid presenting generated fixture summaries as actual model, feature-attribution, risk-check, sizing, open/close/hedge, or confidence-delta reasoning.

Passing evidence:
- Lineage schema fields exist in backend wire models, including `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, and `execution_intent_id`.
- The operator proof dashboard safely reads static public artifacts and displays live gate status as blocked.
- Static proof artifacts include non-live paper, shadow, risk, and explainability fixture data.

Concrete blockers:
- Implemented website pages do not expose the REQ_0009 lineage and explanation contract.
- `/explain` API routes are metadata-only skeletons, so frontend pages cannot fetch real explanation payloads.
- Required IDs are not visible on every relevant decision, table row, and page.
- Paper/shadow/legacy comparison is confined to operator proof fixtures, not integrated as a reusable decision explainability surface.
- Full confidence explanation, feature contributors, source freshness, risk checks, position sizing reason, open/close/hedge reason, blocked-trade reason, and audit timeline are not rendered from authoritative records.

Proposed non-live autofix tasks:
1. Add read-only backend explainability endpoints for feature snapshots, predictions, signals, decisions, risk decisions, execution intents, and paper trades using repository-backed or fixture-backed non-live data only.
2. Define a shared `DecisionExplainabilityContract` response that contains lineage IDs, source freshness, feature contributors, stale/missing/unused flags, confidence delta, risk checks, sizing reason, action reason, paper/shadow/legacy comparison, live gate status, and audit events.
3. Build a reusable frontend `LineageExplainabilityPanel` that renders all required IDs and labels missing upstream/downstream data explicitly as unavailable rather than inventing reasons.
4. Replace placeholder bodies on Signal Explainability, Trainer Prediction Monitor, Risk Control, Paper Trading, Symbol Universe, Audit Ledger, Live Readiness, and Mission Control with read-only explainability panels or tables.
5. Expand operator proof dashboard tables so every visible decision row shows `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`, and paper/shadow IDs where present.
6. Add fixture-backed E2E tests asserting the required fields are visible and that unavailable reasoning displays explicit gap text instead of synthetic explanation text.
7. Keep all autofixes non-live: no Redis writes, no service restarts, no order placement, no leverage/margin changes, and no live trading enablement.
