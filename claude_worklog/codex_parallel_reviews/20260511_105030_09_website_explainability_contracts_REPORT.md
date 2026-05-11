# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Verdict: BLOCKED

## Summary

REQ_0009 requires the website to expose full decision lineage and under-the-hood explanations across Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness.

The current implementation partially exposes lineage IDs and paper/shadow comparison evidence, but it is not contract-ready. Several required pages still render a generic evidence-gap shell, the operator payload self-reports missing confidence and symbol scoring fields, and backend explainability routes are skeleton metadata shims rather than implemented read/explain endpoints.

## Findings

### BLOCKER 1 - Required pages still render evidence-gap shells

`v2/frontend/src/components/layout/PageShell.tsx:25` renders:

`Evidence missing - this route is registered but needs a dedicated data payload before it can be used for live-readiness decisions.`

The following required or directly related explainability pages use that shell instead of rendering the required contract fields:

- `v2/frontend/src/pages/risk-control/index.tsx:5`
- `v2/frontend/src/pages/paper-trading/index.tsx:5`
- `v2/frontend/src/pages/symbols/index.tsx:5`
- `v2/frontend/src/pages/audit-ledger/index.tsx:5`
- `v2/frontend/src/pages/live-readiness/index.tsx:5`
- `v2/frontend/src/pages/orchestrator-admin/index.tsx:5`
- `v2/frontend/src/pages/signals/index.tsx:5`

Impact: REQ_0009 explicitly requires Risk Gateway, Paper / Shadow Trading, Symbol Universe, Audit Ledger, and Live Readiness visibility. These pages currently announce they are not usable for live-readiness decisions.

### BLOCKER 2 - Operator explainability payload has explicit data gaps for required fields

`v2/frontend/public/operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json` reports:

- `confidence_calibration`
- `confidence_delta`
- `liquidity_score`
- `model_checkpoint`
- `old_confidence`
- `open_interest_score`
- `volatility_score`
- `volume_score`

The first lineage row has `confidence_delta: "evidence_missing"`, `old_confidence: "evidence_missing"`, and `model_checkpoint: "evidence_missing"`. The first symbol row has Binance/CoinAnk/KuCoin/CoinAPI evidence and liquidity/volume/volatility/open-interest scores as `evidence_missing`.

Impact: this fails the confidence explanation and symbol selection explanation requirements.

### BLOCKER 3 - Backend `/explain` API surfaces are skeleton-only

The backend declares explain endpoints in metadata, but the files state they are scaffold-only:

- `v2/backend/app/api/v1/features.py:97`
- `v2/backend/app/api/v1/predictions.py:1`
- `v2/backend/app/api/v1/risk_decisions.py:28`
- `v2/backend/app/api/v1/paper.py:63`

The route metadata advertises `/{id}/explain`, but only `OPTIONS /` metadata handlers are implemented.

Impact: the website can only consume static/public artifact payloads for many explanations. It does not have implemented backend read/explain contracts for live application data.

### BLOCKER 4 - Main cockpit drawer omits some required fields

`v2/frontend/src/pages/cockpitComponents.tsx:148` through `:173` shows:

- `feature_snapshot_id`
- `signal_id`
- `orchestrator_decision_id`
- `risk_decision_id`
- `execution_intent_id`
- confidence raw/calibrated/delta
- source freshness
- signal/orchestrator/risk reason
- top positive/negative contributors
- stale/missing flags

However it does not show `prediction_id` as a labeled lineage field inside the details grid, does not show `unused_flags`, and does not expose a paper/shadow comparison section. `prediction_id` appears in the summary row at `v2/frontend/src/pages/cockpitComponents.tsx:145`, but the requested visibility is not consistently presented as a labeled contract field.

Impact: Mission Control, Trainer Prediction Monitor, and Signal Explainability have partial visibility but not the full REQ_0009 contract.

## Positive Evidence

- The reusable cockpit decision drawer exposes `feature_snapshot_id`, `risk_decision_id`, and several explanation fields in `v2/frontend/src/pages/cockpitComponents.tsx:148`.
- The operator proof dashboard renders a fuller lineage chain, including raw source data, feature snapshot, trainer prediction, confidence old/new/delta, signal, orchestrator decision, risk decision, execution intent, paper/shadow/live-blocked action, and result/PnL attribution in `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:474`.
- Paper/shadow comparison evidence exists in proof generators and public artifacts. `v2/backend/app/proof/non_live_operational_proof.py:316` builds `shadow_comparison_result`; `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226` builds `shadow_comparison_30d`.
- Fake reasoning is partially mitigated by explicit evidence-gap rendering. `v2/frontend/src/pages/cockpitComponents.tsx:173` uses `Evidence missing - cannot explain without guessing`, and `PageShell` clearly marks missing route payloads.

## No Fake Reasoning Assessment

The implementation does not appear to fabricate explanations silently. Missing evidence is usually labeled as `Evidence missing` or `evidence_missing`, and fixture-backed records are labeled as deterministic/static proof fixtures.

This is good safety behavior, but it also means the contract is blocked until the missing evidence is wired.

## Proposed Non-Live Autofix Tasks

1. Replace `PageShell` usage on `risk-control`, `paper-trading`, `symbols`, `audit-ledger`, `live-readiness`, `orchestrator-admin`, and `signals` with read-only panels backed by committed public artifacts or non-live API endpoints.
2. Add labeled `prediction_id`, `decision_id`, `unused_flags`, `paper/shadow/legacy comparison`, `risk checks`, `position sizing reason`, `blocked-trade reason`, and `audit timeline` fields to the shared `DecisionDrawers` contract.
3. Populate non-live confidence explanation fields in the operator payload: previous confidence, new confidence, delta, contributing feature deltas, calibration/model/checkpoint, regime context, and data-quality impact.
4. Populate symbol universe evidence fields from non-live/read-only artifacts: Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, liquidity, volume, volatility, open-interest, freshness, feature completeness, manual overrides, and state reason.
5. Implement backend read-only `/explain` endpoints for feature snapshots, predictions, risk decisions, execution intents, paper trades, and audit timeline projections. Keep them non-mutating and fixture/read-model backed until live approval.
6. Add e2e assertions for every REQ_0009 page so the test suite fails if any required page falls back to `PageShell` evidence-gap text.

CODEX_PARALLEL_REVIEW_BLOCKED
