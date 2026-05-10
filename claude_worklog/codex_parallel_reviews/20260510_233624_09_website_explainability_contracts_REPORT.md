# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Inputs inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Decision: BLOCKED

## Summary

The website is not ready for the REQ_0009 explainability contract. It has useful partial visibility for `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, and paper/shadow comparisons through static proof payloads, but the implementation is not contract-backed across all required pages and still exposes many required fields as `evidence_missing` or deterministic fixture values.

The implementation does avoid fake reasoning in several places by showing explicit gaps such as `Evidence missing - cannot explain without guessing`, `evidence_missing`, and `STATIC_PROOF_FIXTURE`. That is good, but it also means the readiness gate must remain blocked until the missing contract fields are wired to real non-live evidence APIs or explicit audited proof artifacts.

## Findings

1. Required pages are still generic shells without explainability contract data.
   - `v2/frontend/src/pages/risk-control/index.tsx`, `v2/frontend/src/pages/paper-trading/index.tsx`, `v2/frontend/src/pages/audit-ledger/index.tsx`, `v2/frontend/src/pages/symbols/index.tsx`, and `v2/frontend/src/pages/orchestrator-admin/index.tsx` render only `PageShell`.
   - `PageShell` states: `Evidence missing - this route is registered but needs a dedicated data payload before it can be used for live-readiness decisions.`
   - REQ_0009 requires visibility in Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness. Several of these surfaces are only present inside `/admin/operator-proof-dashboard`, not as their dedicated required pages.

2. Backend explainability endpoints are skeleton metadata only.
   - `v2/backend/app/api/v1/features.py`, `predictions.py`, `signals.py`, `decisions.py`, `risk_decisions.py`, `intents.py`, and `paper.py` declare `/explain` paths in metadata, but each file says `Scaffold-only` and only implements an OPTIONS metadata shim.
   - There is no actual GET/list/detail/explain endpoint returning contract-backed decision explanations for the website to consume.

3. Lineage validation is scaffold-only.
   - `v2/backend/app/api/middleware/lineage_validator.py` is a pass-through and explicitly says the required validators land later.
   - The current middleware does not enforce shape, stage-required IDs, parent existence, cross-symbol coherence, immutability, or single-parent uniqueness.

4. Required confidence and model fields are missing from the current dashboard payload.
   - `v2/frontend/public/operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json` contains many rows with `old_confidence: evidence_missing`, `confidence_delta: evidence_missing`, `confidence_calibration: evidence_missing`, and `model_checkpoint: evidence_missing`.
   - REQ_0009 requires previous confidence, new confidence, delta, contributing feature deltas, regime context, model/checkpoint version, and data-quality impact.

5. Symbol selection explainability is incomplete.
   - The same payload shows `binance_evidence`, `coinank_evidence`, `coinapi_evidence`, `kucoin_evidence`, `liquidity_score`, `volume_score`, `volatility_score`, and `open_interest_score` as `evidence_missing`.
   - REQ_0009 requires discovery evidence, Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, and liquidity/volume/volatility/open-interest/freshness scores.

6. Risk explainability is partial.
   - `risk_gateway.rows` include `risk_decision_id` visibility and checks for stale/duplicate/exposure/final reason, but `drawdown_check` and `stop_policy_status` are still `evidence_missing`.
   - The dedicated Risk Gateway page is still `PageShell`, so the partial risk evidence is not available on the required dedicated page.

7. Paper/shadow comparison visibility exists but is fixture-driven and not surfaced on the dedicated paper page.
   - `v2/frontend/public/non_live_operational_proof/latest/shadow_comparison_result.json` and the operator dashboard payload expose paper and shadow rows.
   - The source is explicitly deterministic/offline fixture data, and `/admin/paper-trading` remains a generic missing-evidence page.

8. Audit timeline is insufficient.
   - The operator dashboard audit ledger only lists artifact existence/classification, not a decision-level audit timeline from raw source data through feature, prediction, signal, decision, risk decision, execution intent, paper/shadow action, and PnL attribution.
   - `/admin/audit-ledger` is still a generic missing-evidence page.

## Positive Coverage Observed

- Mission Control and Trainer Prediction Monitor display `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, and related lineage fields via `DecisionDrawers`.
- Signal Explainability displays lineage IDs and contributors through the shared cockpit payload.
- Operator Proof Dashboard has stronger coverage than the dedicated pages: trainer rows, signal rows, feature attribution, symbol universe rows, risk rows, trader fleet paper/shadow rows, audit artifact rows, live readiness, and data gaps.
- The UI does not silently invent missing evidence; it exposes `Evidence missing`, `evidence_missing`, `STATIC_PROOF_FIXTURE`, and `cannot explain without guessing`.

## Blockers

- Dedicated required pages do not all show the REQ_0009 contract fields.
- Backend explainability APIs are skeleton-only and cannot serve the contract.
- Lineage validation is not enforced.
- Confidence deltas, model/checkpoint version, calibration, source discovery evidence, liquidity/volume/volatility/open-interest scores, drawdown checks, stop policy status, and audit timeline are missing or fixture-only.
- Paper/shadow comparison is not contract-backed on the dedicated Paper / Shadow Trading page.

## Proposed Non-Live Autofix Tasks

1. Build a read-only `explainability` projection API that aggregates committed non-live proof artifacts and DB/repository records without Redis writes or live exchange actions.
2. Implement actual GET list/detail/explain handlers for feature snapshots, predictions, signals, decisions, risk decisions, execution intents, and paper trades using existing repositories or static non-live proof artifacts.
3. Replace `PageShell` on Symbol Universe, Risk Gateway, Paper / Shadow Trading, Audit Ledger, and Orchestrator Decisions with read-only contract-backed views.
4. Add a reusable frontend `LineageContractPanel` that renders the full REQ_0009 chain and always distinguishes real values, fixture values, and explicit evidence gaps.
5. Extend the non-live proof payload builder to include previous confidence, confidence delta, model/checkpoint version, calibration, regime context, feature deltas, data-quality impact, drawdown check, stop policy status, and decision-level audit events.
6. Extend symbol universe proof payloads with Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, liquidity, volume, volatility, open-interest, freshness scores, and manual override reasons.
7. Add non-live frontend tests for each required page verifying `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper/shadow comparison, blocked-trade reason, audit timeline, and explicit no-fake-reasoning gap labels.
8. Implement lineage middleware validators in non-live/test mode first: shape, stage-required IDs, gap reason, parent existence, cross-symbol coherence, immutability, and single-parent uniqueness.

