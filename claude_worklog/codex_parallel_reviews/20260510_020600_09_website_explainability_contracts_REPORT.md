# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Inputs inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Verdict: BLOCKED

## Summary

The website has partial explainability visibility through `MissionControlPage`, `SignalExplainabilityPage`, `TrainerPredictionMonitorPage`, and especially `OperatorProofDashboardPage`. The visible fields include `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `execution_intent_id`, feature contributors, stale/missing/unused flags, and paper/shadow rows.

The contract is not ready because the implementation still relies on static proof fixtures for core reasoning, several required standalone pages are shells with no dedicated payload, and the published readiness artifacts explicitly list missing required fields while still declaring a ready marker.

## Checked Contract Items

- `feature_snapshot_id` visibility: PARTIAL PASS. Visible in `DecisionDrawers` and `OperatorProofDashboardPage` lineage/feature sections.
- `prediction_id` visibility: PARTIAL PASS. Visible in decision drawers and operator lineage cards.
- `risk_decision_id` visibility: PARTIAL PASS. Visible in decision drawers, operator lineage cards, risk gateway, and paper ledger rows.
- Paper/shadow comparison visibility: PARTIAL PASS. Visible in `OperatorProofDashboardPage` `Trader Fleet / Paper-Shadow Actions` and historical proof payloads, but the dedicated `paper-trading` page is only a generic missing-evidence shell.
- No fake reasoning: BLOCKED. The UI usually labels missing data as `evidence_missing` instead of guessing, which is good. However, the ready marker is contradicted by known missing contract fields and fixture-only explanations, so the readiness claim itself is misleading.

## Concrete Blockers

1. Required pages are registered shells, not explainability views.
   - `v2/frontend/src/pages/risk-control/index.tsx`, `paper-trading/index.tsx`, `audit-ledger/index.tsx`, `symbols/index.tsx`, `live-readiness/index.tsx`, and `executions/index.tsx` all render `PageShell`.
   - `PageShell` states: `Evidence missing - this route is registered but needs a dedicated data payload before it can be used for live-readiness decisions.`
   - REQ_0009 requires visibility in Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, Live Readiness, Symbol Universe, and related pages, not only inside the operator dashboard.

2. Published explainability readiness contradicts its own data gaps.
   - `v2/frontend/public/operator_gui_real_data_and_explainability/latest/GO_NO_GO.md` contains `PROFESSIONAL_OPERATOR_GUI_AND_DECISION_EXPLAINABILITY_READY`.
   - The paired coverage files list missing required fields: `confidence_calibration`, `confidence_delta`, `liquidity_score`, `model_checkpoint`, `old_confidence`, `open_interest_score`, `volatility_score`, and `volume_score`.
   - The operator cockpit payload repeats these gaps in `data_gaps`.

3. Confidence explanation chain is incomplete.
   - `operator_cockpit_payload.json` lineage rows show `old_confidence: evidence_missing`, `confidence_delta: evidence_missing`, and `confidence_calibration: evidence_missing`.
   - REQ_0009 requires previous confidence, new confidence, delta, contributing feature deltas, model/checkpoint version, source freshness, regime context, and data-quality impact.

4. Symbol selection explanation is incomplete.
   - `symbol_universe.rows` includes placeholders such as `binance_evidence: evidence_missing`, `coinank_evidence: evidence_missing`, `coinapi_evidence: evidence_missing`, `kucoin_evidence: evidence_missing`, and missing liquidity/volume/volatility/open-interest scores.
   - REQ_0009 requires discovery evidence, Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, score breakdowns, feature completeness, overrides, and state reasons.

5. Trade/risk explanation is incomplete.
   - Risk rows include `drawdown_check: evidence_missing` and `stop_policy_status: evidence_missing`.
   - Position sizing is represented as `paper_fixture_no_live_sizing`, not a real sizing reason contract.
   - REQ_0009 requires sizing reason, stale signal check, duplicate check, exposure check, drawdown check, live gate status, execution mode, and final reason.

6. Backend production contract is not wired end-to-end.
   - `v2/backend/app/proof/non_live_operational_proof.py` and `historical_30d_replay_and_paper_proof.py` generate deterministic fixture lineage.
   - Backend domain modules exist for features, trainer prediction output, orchestrator decision, risk gateway, paper ledger, replay, and symbols, but the reviewed website payloads are static/public fixture artifacts rather than a complete backend-served explainability contract.

## Proposed Non-Live Autofix Tasks

1. Add a single typed `DecisionExplainabilityContract` in backend/frontend shared schema form, with required fields from REQ_0009 and explicit nullable `evidence_status` metadata for unavailable data.

2. Build a non-live backend assembler that joins existing domain records into the full chain:
   raw source data -> feature snapshot -> feature deltas -> trainer prediction -> signal -> orchestrator decision -> risk decision -> execution intent -> paper/shadow/live-blocked action -> result/PnL attribution.

3. Replace fixture-only ready markers with a gate that blocks readiness when any required field is `evidence_missing` unless the requirement explicitly allows that field to be unavailable.

4. Convert standalone `PageShell` routes for Symbol Universe, Risk Gateway, Paper / Shadow Trading, Audit Ledger, Live Readiness, and Trader Fleet/Executions into dedicated non-live evidence pages using the same contract payload.

5. Add frontend tests that assert every REQ_0009 field is visible on each required page and that a page with missing required fields shows a blocked readiness state, not a ready marker.

6. Add fixture provenance labels next to deterministic explanations so operator-facing text cannot be mistaken for live model reasoning.

7. Extend symbol-universe non-live artifacts with Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, liquidity/volume/volatility/open-interest/freshness scores, manual overrides, and universe state reasons.

8. Extend risk non-live artifacts with drawdown check, stop policy status, real paper sizing reason, open/close/hedge reason, blocked-trade reason, and explicit live gate state.

## Safety Notes

- No live services were restarted.
- No Redis writes or deletes were performed.
- No orders, leverage, margin, deployment, or live-trading state changes were performed.
- This review only inspected files and wrote this requested report artifact.
