# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Result: BLOCKED

Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Safety posture:
- Read-only source and artifact review only.
- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, or deploy.

## Requirement Baseline

REQ_0009 requires the website to show full decision lineage from raw source data through feature snapshot, trainer prediction, signal, orchestrator decision, risk gateway decision, execution intent, paper/shadow/live-blocked action, and result/PnL attribution.

Required visibility includes `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper/shadow/legacy comparison, confidence deltas, feature contributors, stale/missing/unused feature flags, source freshness, risk checks, sizing/action reasons, blocked-trade reasons, and audit timeline. Missing evidence must be explicit; the UI must not invent reasoning.

## Passing Evidence

- Mission Control renders the shared decision drawer from `payload.decisions` and keeps live trading visibly blocked: `v2/frontend/src/pages/mission-control/index.tsx:28` and `v2/frontend/src/pages/mission-control/index.tsx:35`.
- Signal Explainability and Trainer Prediction Monitor also render the shared decision drawer when the cockpit payload is present: `v2/frontend/src/pages/signal-explainability/index.tsx:18`, `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx:18`.
- The shared drawer exposes `feature_snapshot_id`, `risk_decision_id`, `execution_intent_id`, confidence raw/calibrated/delta, source freshness, signal/orchestrator/risk reasons, result, positive/negative contributors, stale flags, and missing flags: `v2/frontend/src/pages/cockpitComponents.tsx:127`.
- The drawer shows `prediction_id` in the summary row: `v2/frontend/src/pages/cockpitComponents.tsx:132`.
- Missing explanation evidence is labeled instead of fabricated: `v2/frontend/src/pages/cockpitComponents.tsx:162`; the e2e suite asserts this text: `v2/frontend/tests/e2e/enterprise_trading_cockpit.spec.ts:14`.
- Static proof artifacts contain lineage IDs and paper/shadow/legacy comparison data, for example `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:155`, `v2/frontend/public/non_live_operational_proof/latest/shadow_comparison_result.json:20`, and `v2/frontend/public/historical_30d_replay_and_paper_proof/latest/operator_dashboard_payload.json:4`.
- The operator proof dashboard has a fuller lineage panel with raw source data, feature snapshot, trainer prediction, confidence old/new/delta, risk decision, execution intent, paper/shadow/live-blocked action, and result/PnL attribution: `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:474`.
- The operator proof dashboard includes a Trader Fleet / Paper-Shadow Actions section: `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:657`.

## Blockers

1. Required REQ_0009 pages are still placeholder shells.

   Evidence: Paper Trading, Risk Control, Symbol Universe, and Audit Ledger render only `PageShell`: `v2/frontend/src/pages/paper-trading/index.tsx:5`, `v2/frontend/src/pages/risk-control/index.tsx:5`, `v2/frontend/src/pages/symbols/index.tsx:5`, `v2/frontend/src/pages/audit-ledger/index.tsx:5`. `PageShell` displays "Evidence missing - this route is registered but needs a dedicated data payload" at `v2/frontend/src/components/layout/PageShell.tsx:25`.

   Impact: REQ_0009 requires visibility in Paper / Shadow Trading, Risk Gateway, Symbol Universe, Audit Ledger, and Live Readiness. The generic shell is honest about missing evidence, but it is not contract readiness.

2. Backend explainability endpoints are metadata-only skeletons.

   Evidence: `/predictions`, `/risk-decisions`, and `/paper-trades` document `/{id}/explain` routes in metadata, but the files say scaffold-only and only implement an OPTIONS shim: `v2/backend/app/api/v1/predictions.py:1`, `v2/backend/app/api/v1/risk_decisions.py:1`, `v2/backend/app/api/v1/paper.py:1`.

   Impact: The frontend cannot fetch authoritative per-ID explainability payloads from backend read models. The current visible contract depends on static public proof JSON rather than implemented API contracts.

3. `prediction_id` visibility is present but weaker than the other required IDs in the shared drawer.

   Evidence: `DecisionRow` types include `prediction_id`: `v2/frontend/src/pages/cockpitData.ts:45`, and the drawer summary renders the value at `v2/frontend/src/pages/cockpitComponents.tsx:132`. The labeled lineage grid renders `feature_snapshot_id`, `signal_id`, `orchestrator_decision_id`, `risk_decision_id`, and `execution_intent_id`, but omits a labeled `prediction_id` row: `v2/frontend/src/pages/cockpitComponents.tsx:137`.

   Impact: Operators can see the prediction identifier, but the UI is inconsistent with the explicit ID-label contract.

4. Paper/shadow comparison is not wired into the actual Paper Trading page.

   Evidence: The static operator proof dashboard can show paper/shadow actions at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:657`, and static artifacts contain shadow comparisons. The required `/admin/paper-trading` page itself is still the generic `PageShell`: `v2/frontend/src/pages/paper-trading/index.tsx:5`.

   Impact: Paper/shadow comparison visibility exists as proof-dashboard evidence, not as the required Paper / Shadow Trading contract surface.

5. Contract payloads are static proof-fixture oriented, not authoritative full reasoning chains.

   Evidence: `useCockpitPayload` fetches `/enterprise_trading_cockpit/latest/operator_cockpit_payload.json` and other static public proof paths: `v2/frontend/src/pages/cockpitData.ts:342`. The data model has many required fields, but it lacks first-class risk-check arrays, position sizing reason, explicit open/close/hedge reason fields, and audit timeline fields in `DecisionRow`: `v2/frontend/src/pages/cockpitData.ts:41`.

   Impact: The UI avoids fake reasoning by showing evidence gaps, but it is not yet a complete website explainability contract for every major decision type.

## Required Checks

- `feature_snapshot_id` visibility: PARTIAL PASS. Visible in the shared drawer and proof payloads, but not across all required pages.
- `prediction_id` visibility: PARTIAL PASS. Visible as a summary value, but missing as a labeled lineage grid field.
- `risk_decision_id` visibility: PARTIAL PASS. Visible in the shared drawer and proof payloads, but not across all required pages.
- Paper/shadow comparison visibility: PARTIAL PASS. Present in proof dashboard/static artifacts; missing from the Paper Trading page contract.
- No fake reasoning: PASS for current UI behavior. Missing data is labeled explicitly, and static/fixture evidence is marked as such, but full authoritative reasoning is not implemented.

## Proposed Non-Live Autofix Tasks

1. Add a shared read-only `DecisionExplainabilityContract` schema for backend and frontend fixtures with required fields for all REQ_0009 IDs, confidence explanation, feature contributors, stale/missing/unused flags, source freshness, risk checks, sizing reason, open/close/hedge reason, blocked-trade reason, paper/shadow/legacy comparison, live gate status, and audit timeline.
2. Implement non-mutating backend GET endpoints for `/{id}/explain` on feature snapshots, predictions, signals, decisions, risk decisions, execution intents, and paper trades. Use repository-backed reads where available and fixture-backed reads only when explicitly marked `STATIC_PROOF_FIXTURE`.
3. Add a reusable frontend `DecisionExplainabilityPanel` that renders all required IDs with labels, including a labeled `prediction_id` row, and renders explicit "Evidence missing" rows for unavailable contract fields.
4. Replace generic `PageShell` bodies on Paper Trading, Risk Control, Symbol Universe, Audit Ledger, and Live Readiness with read-only panels/tables that consume the shared contract or show explicit contract gaps.
5. Wire paper/shadow/legacy comparison into `/admin/paper-trading` using existing static artifacts first, clearly marked non-live, then swap to backend read models when available.
6. Expand tests to assert `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper/shadow comparison, risk checks, sizing/action reasons, and audit timeline visibility on each required page.
7. Keep all autofixes non-live: no Redis writes, no Redis key deletion, no service restarts, no order placement/cancellation, no leverage or margin changes, no live trading enablement, and no deployment.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED
