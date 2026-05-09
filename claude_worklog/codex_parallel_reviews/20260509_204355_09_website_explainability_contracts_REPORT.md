# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness

Verdict: BLOCKED

Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Requirement focus:
- `feature_snapshot_id` visibility
- `prediction_id` visibility
- `risk_decision_id` visibility
- paper/shadow comparison visibility
- no fake reasoning

Findings:

1. Partial visibility exists only in the operator proof cockpit, not across the required website pages.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` defines lineage rows with `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, and paper/shadow action fields.
   - The cockpit renders the chain at lines 441-454 and paper/shadow lists at lines 591-597.
   - The cockpit mounts Trainer Prediction Monitor, Signal Explainability, Feature Attribution, Symbol Universe, Risk Gateway, Trader Fleet, Audit Ledger, Live Readiness sections at lines 791-801.
   - This is useful evidence, but it is a single aggregate dashboard. REQ_0009 requires the fields to be visible in the named first-class pages, including Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness.

2. Required first-class pages are still placeholder shells.
   - `v2/frontend/src/components/layout/PageShell.tsx` lines 25-30 renders: "Placeholder shell for milestone E..."
   - `v2/frontend/src/pages/signal-explainability/index.tsx` lines 5-6 returns only `PageShell`.
   - `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx` lines 5-6 returns only `PageShell`.
   - `v2/frontend/src/pages/paper-trading/index.tsx` lines 5-6 returns only `PageShell`.
   - Similar `PageShell`-only implementations exist for Symbols, Risk Control, Audit Ledger, Live Readiness, Signals, and Executions. Those pages do not independently expose the contract fields.

3. Backend lineage/explainability endpoints are scaffold-only, so website pages cannot yet be data-backed by contract endpoints.
   - `v2/backend/app/api/v1/features.py` lines 1-4 says scaffold-only; lines 14-22 expose only route metadata.
   - `v2/backend/app/api/v1/predictions.py` lines 1-4 says scaffold-only; lines 14-22 expose only route metadata.
   - `v2/backend/app/api/v1/risk_decisions.py` lines 1-4 says scaffold-only; lines 16-30 expose only route metadata.
   - `v2/backend/app/api/v1/intents.py` lines 1-5 says scaffold-only; lines 16-31 expose only route metadata.
   - The required `/explain` endpoints are declared in metadata but not implemented as GET handlers returning resolved lineage, contributor, freshness, risk check, paper/shadow, or audit timeline data.

4. Paper/shadow comparison is visible in the aggregate cockpit, but not ready as a contract-complete paper/shadow page.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` lines 591-597 renders `Paper ledger actions` and `Shadow comparisons` from `trader_fleet_paper_shadow`.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` lines 696-704 renders continuous paper/shadow runtime counters.
   - `v2/frontend/src/pages/paper-trading/index.tsx` lines 5-6 is still only `PageShell`, so the required Paper / Shadow Trading page does not expose a drilldown lineage contract.

5. The current implementation avoids pretending unknown evidence is known, but the contract is not complete.
   - `claude_worklog/tools/build_operator_gui_explainability_payload.py` uses explicit `evidence_missing` values for missing old confidence, confidence delta, model checkpoint, confidence calibration, drawdown checks, stop policy, exchange/source evidence, and symbol scoring fields.
   - The generated cockpit payload includes `data_gaps`: `confidence_calibration`, `confidence_delta`, `liquidity_score`, `model_checkpoint`, `old_confidence`, plus other scoring gaps.
   - This satisfies the narrow "no fake reasoning" expectation better than fabricated explanations, but it is also a blocker for REQ_0009 because required confidence and symbol-selection explanation fields remain missing.

6. Some required fields are typed but not rendered in the cockpit tables.
   - `RiskRow` includes `drawdown_check`, `sizing_reason`, `live_gate_status`, and `execution_mode` at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx` lines 211-224.
   - The Risk Gateway table at lines 529-544 renders only symbol, final decision, stale, duplicate, exposure, and reason. It omits drawdown, sizing reason, live gate status, and execution mode.
   - `LineageRow` includes `source_freshness_by_ingestor` at line 159, but the lineage card renderer at lines 441-468 does not display that map.

Blockers:
- First-class required pages still render placeholder shell content instead of data-backed explainability views.
- `/feature-snapshots`, `/predictions`, `/signals`, `/decisions`, `/risk-decisions`, `/execution-intents`, and `/paper-trades` explainability routes are metadata skeletons rather than implemented read endpoints.
- Required confidence explanation fields remain `evidence_missing`: previous confidence, confidence delta, model/checkpoint version, and calibration.
- Required symbol selection evidence remains `evidence_missing`: Binance USD-M confirmation, CoinAnk alias evidence, KuCoin/CoinAPI evidence, liquidity, volume, volatility, open-interest scores.
- Risk Gateway UI omits required displayed fields already present in row types: drawdown check, sizing reason, live gate status, execution mode.
- Paper/shadow comparison exists only in aggregate proof cockpit and not in the Paper / Shadow Trading first-class page.

Proposed non-live autofix tasks:
- Build reusable read-only explainability components for lineage IDs, confidence deltas, contributors, freshness, risk checks, and audit links; reuse them across the named pages instead of only the operator cockpit.
- Replace `PageShell` placeholders for Signal Explainability, Trainer Prediction Monitor, Symbols, Risk Control, Paper Trading, Audit Ledger, Live Readiness, Signals, and Executions with read-only views backed by static public proof payloads first, then API endpoints.
- Implement non-mutating GET handlers for `/api/v1/*/{id}/explain` endpoints using existing repositories and schemas; no Redis writes and no live execution side effects.
- Extend the operator cockpit Risk Gateway table to render drawdown check, sizing reason, live gate status, and execution mode.
- Render `source_freshness_by_ingestor` in lineage and feature attribution cards.
- Add explicit UI badges for `evidence_missing` fields so missing evidence remains visible and cannot be confused with real reasoning.
- Add Playwright checks asserting `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper rows, shadow comparison rows, and `evidence_missing` badges are visible on each required page.
- Keep live status hard-blocked and verify all new controls are read-only.

Conclusion:

The website is not contract-ready for REQ_0009. The aggregate operator cockpit demonstrates a useful partial implementation and does not appear to fabricate missing evidence, but the required website contract remains blocked by placeholder pages, scaffold-only backend explain routes, omitted display fields, and material evidence gaps.
