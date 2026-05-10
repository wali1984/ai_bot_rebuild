# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness
Review mode: read-only parallel review; no live service, Redis, order, leverage, margin, deployment, or secret access performed.
Inputs inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Decision: BLOCKED

## Requirement Baseline

`REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md` requires the website to show full decision lineage from raw source data through feature snapshot, trainer prediction, confidence change, signal, orchestrator decision, risk gateway decision, execution intent, paper/shadow/live-blocked trader action, and result/PnL attribution.

Required website-visible fields include `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`, confidence deltas, feature contributors, stale/missing/unused flags, source freshness, risk checks, sizing/open/close/hedge/block reasons, paper/shadow/legacy comparison, and audit timeline.

## Findings

### Partial ID Visibility Exists

The shared frontend decision drawer renders several required lineage IDs:
- `prediction_id` is visible in the drawer summary.
- `feature_snapshot_id` is visible in the lineage grid.
- `risk_decision_id` is visible in the lineage grid.
- `signal_id`, `orchestrator_decision_id`, and `execution_intent_id` are also visible.

Evidence:
- `v2/frontend/src/pages/cockpitComponents.tsx:127-164`
- `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx:18`
- `v2/frontend/src/pages/signal-explainability/index.tsx:18`
- `v2/frontend/src/pages/mission-control/index.tsx:35`

Static cockpit payload rows also contain those IDs:
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:150-175`
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:187-211`

### Paper/Shadow Comparison Visibility Is Not Contract-Complete

Paper/shadow visibility exists in the operator proof dashboard, where `LineageCards` shows `paper/shadow/live-blocked action` and `TraderFleet` shows paper ledger actions plus shadow comparisons.

Evidence:
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:474-487`
- `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:657-663`

Blocker: the named website pages required by REQ_0009 are not all wired to these views. `Paper Trading`, `Risk Control`, `Symbols`, `Orchestrator Admin`, `Audit Ledger`, and `Live Readiness` still render generic `PageShell` content instead of the required explainability panels.

Evidence:
- `v2/frontend/src/pages/paper-trading/index.tsx:1-7`
- `v2/frontend/src/pages/risk-control/index.tsx:1-7`
- `v2/frontend/src/pages/symbols/index.tsx:1-7`
- `v2/frontend/src/pages/orchestrator-admin/index.tsx:1-7`
- `v2/frontend/src/pages/audit-ledger/index.tsx:1-7`
- `v2/frontend/src/pages/live-readiness/index.tsx:1-7`

### Backend Explainability APIs Are Skeletons

The backend declares lineage-bearing routes and `/explain` endpoint metadata, but the actual API files are scaffold-only OPTIONS metadata shims. They do not serve decision explanations, feature attribution, risk checks, paper/shadow comparison records, or audit timelines.

Evidence:
- `v2/backend/app/api/v1/predictions.py:1-27`
- `v2/backend/app/api/v1/risk_decisions.py:1-35`
- `v2/backend/app/api/v1/paper.py:1-34`

This blocks readiness because the website currently depends on static public proof payloads rather than contract-backed read endpoints for live operator explainability.

### No Unlabeled Fake Reasoning Detected, But Fixture Reasoning Is Not Production Evidence

The reviewed UI is generally explicit when data is a static fixture or missing evidence. Examples include `STATIC_PROOF_FIXTURE` freshness modes in the cockpit payload and the UI fallback `Evidence missing - cannot explain without guessing`.

Evidence:
- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json:176-184`
- `v2/frontend/src/pages/cockpitComponents.tsx:162`

Blocker: the current displayed explanations are still fixture/proof-artifact based, not durable API-backed explanations from persisted feature snapshots, predictions, risk decisions, execution intents, paper trades, and audit events. The site can demonstrate the shape, but it is not ready as a production explainability contract.

## Check Results

- `feature_snapshot_id` visibility: PARTIAL PASS. Visible in decision drawers and operator proof dashboard, but not consistently available across all required pages.
- `prediction_id` visibility: PARTIAL PASS. Visible in decision drawers and operator proof dashboard, but not consistently available across all required pages.
- `risk_decision_id` visibility: PARTIAL PASS. Visible in decision drawers and operator proof dashboard, but not consistently available across all required pages.
- Paper/shadow comparison visibility: PARTIAL PASS. Present in operator proof dashboard and public proof artifacts, but not wired into the required `Paper / Shadow Trading` page or all required decision surfaces.
- No fake reasoning: PARTIAL PASS. No clearly unlabeled fabricated reasoning found; fixture status is exposed. Blocked because production readiness still relies on static fixture reasoning rather than backend explanation records.

## Concrete Blockers

1. Required pages are not fully wired.
   `Paper Trading`, `Risk Control`, `Symbols`, `Orchestrator Admin`, `Audit Ledger`, and `Live Readiness` render generic shells and do not expose the full REQ_0009 lineage/under-the-hood contract.

2. Backend `/explain` routes are skeleton metadata only.
   Prediction, risk-decision, and paper-trade routes advertise lineage-bearing explain endpoints but do not return explanation payloads.

3. Paper/shadow comparison is proof-dashboard-local.
   Paper/shadow/legacy comparison is visible in proof artifacts and the operator proof dashboard, but the dedicated paper/shadow trading page does not expose it.

4. Static fixture explanations cannot satisfy production contract readiness.
   Current evidence is useful as a non-live demonstration, but the site needs durable read models or APIs backed by persisted decision lineage.

## Proposed Non-Live Autofix Tasks

1. Add shared frontend panels for `LineageCards`, `FeatureAttribution`, `SymbolUniverse`, `RiskGateway`, `TraderFleet`, and `AuditTimeline`, then reuse them on the required pages instead of generic `PageShell` placeholders.

2. Wire `Paper Trading` to the existing non-live paper ledger and shadow comparison public payloads, with explicit fixture/evidence-gap badges and no order-capable controls.

3. Implement non-mutating backend GET endpoints for `/api/v1/predictions/{prediction_id}/explain`, `/api/v1/risk-decisions/{risk_decision_id}/explain`, and `/api/v1/paper-trades/{paper_trade_id}/explain` that return persisted or fixture-labeled explanation envelopes only.

4. Add frontend contract tests asserting each required page renders `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `execution_intent_id`, source freshness, feature contributor lists, risk checks, and paper/shadow comparison or an explicit evidence-gap message.

5. Add a no-fake-reasoning guard: when attribution fields are absent, render `Evidence missing - cannot explain without guessing` rather than fallback prose; require `source_type` or `mode` on every explanation row.

CODEX_PARALLEL_REVIEW_BLOCKED
