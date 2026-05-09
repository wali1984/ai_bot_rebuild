# Website Explainability Contract Readiness Review

Review topic: Website Explainability Contract Readiness  
Date: 2026-05-09  
Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

## Verdict

BLOCKED.

The current implementation has useful non-live proof artifacts and a partial `operator-proof-dashboard`, but the website is not ready for the REQ_0009 explainability contract. The required operator pages are mostly placeholder shells, several named pages do not exist under the requested names, backend explain endpoints are skeleton metadata only, and the UI does not expose the full decision lineage or required under-the-hood fields for every major decision.

## Evidence Reviewed

Requirement REQ_0009 requires website visibility for:
- `feature_snapshot_id`
- `prediction_id`
- `signal_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id`
- symbol universe state
- confidence delta
- positive/negative feature contributors
- stale/missing/unused feature flags
- source freshness by ingestor
- risk checks
- sizing/open/close/hedge/block reasons
- paper/shadow/legacy comparison
- audit timeline

Required pages include Mission Control, Trainer Prediction Monitor, Feature Attribution, Signal Explainability, Symbol Universe, Risk Gateway, Trader Fleet, Paper / Shadow Trading, Audit Ledger, and Live Readiness.

## Passing / Partial Findings

1. Non-live proof payloads carry several lineage IDs.
   - `v2/backend/app/proof/non_live_operational_proof.py:166` builds `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`, `paper_trade_id`, and `shadow_decision_id`.
   - `v2/backend/app/proof/non_live_operational_proof.py:269` emits `decision_explainability_result`.
   - `v2/backend/app/proof/non_live_operational_proof.py:281` emits `shadow_comparison_result`.
   - `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py:64` asserts required lineage fields exist in replay scenarios.

2. `operator-proof-dashboard` loads static non-live proof artifacts.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:247` fetches replay, paper ledger, shadow comparison, risk gateway, and explainability JSON files.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:187` renders a shadow comparison table with legacy vs V2 action and divergence.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:213` renders a limited decision explainability panel.

3. The dashboard exposes the three requested IDs for one selected LABUSDT explanation.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:227` renders `feature_snapshot_id`.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:230` renders `prediction_id`.
   - `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:232` renders `risk_decision_id`.

4. A reusable lineage component exists, but is not wired into pages.
   - `v2/frontend/src/lineage/block.tsx:18` includes fields for prediction, signal, decision, risk decision, execution intent, and feature snapshot.
   - No imports/usages of `LineageBlockView` were found under `v2/frontend/src`.

## Concrete Blockers

1. Required website pages are placeholders or missing.
   - `v2/frontend/src/components/layout/PageShell.tsx:25` renders placeholder text stating concrete handlers and controls land later.
   - Mission Control wraps that placeholder shell at `v2/frontend/src/pages/mission-control/index.tsx:13`.
   - Trainer Prediction Monitor, Signal Explainability, Paper Trading, Audit Ledger, Live Readiness, Symbols, and Risk Control all return only `PageShell`.
   - No page directories exist for `feature-attribution`, `symbol-universe`, `risk-gateway`, or `trader-fleet`; closest existing names are `symbols` and `risk-control`.

2. `feature_snapshot_id`, `prediction_id`, and `risk_decision_id` are not generally visible across required pages.
   - Only `operator-proof-dashboard` renders these IDs, and only for the LABUSDT explainability record.
   - Risk blocks at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:138` show scenario, symbol, decision, and reason only.
   - Paper ledger at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:163` shows event, symbol, paper trade, and PnL only.
   - Shadow comparison at `v2/frontend/src/pages/operator-proof-dashboard/index.tsx:187` omits the lineage IDs even though the payload contains them.

3. Full REQ_0009 lineage is not visible.
   - `signal_id`, `decision_id`, and `execution_intent_id` are required by REQ_0009 but are not rendered in the explainability panel.
   - Raw source data, feature changes, confidence change, signal, orchestrator decision, risk gateway decision, execution intent, action, result/PnL attribution, and audit timeline are not shown as one trace.

4. Paper/shadow comparison visibility is partial.
   - The dashboard shows legacy action, V2 action, and divergence.
   - It does not show paper-vs-shadow-vs-legacy comparison with lineage IDs, risk reason, execution intent, result/PnL attribution, and audit timeline on the required Paper / Shadow Trading page.

5. Backend explainability endpoints are skeleton metadata only.
   - `v2/backend/app/api/v1/features.py:3` says scaffold-only and only implements OPTIONS metadata.
   - `v2/backend/app/api/v1/predictions.py:3` says scaffold-only and only implements OPTIONS metadata.
   - `v2/backend/app/api/v1/decisions.py:3` says scaffold-only and only implements OPTIONS metadata.
   - `v2/backend/app/api/v1/risk_decisions.py:3` says scaffold-only and only implements OPTIONS metadata.
   - `v2/backend/app/api/v1/paper.py:3` says scaffold-only and only implements OPTIONS metadata.

6. Required explainability fields are not exposed in the website.
   - No UI found for confidence delta, previous/new confidence, contributing feature deltas, top positive contributors, top negative contributors, source freshness by ingestor, regime context, model/checkpoint version, data quality impact, position sizing reason, open/close/hedge reason, duplicate/stale/exposure/drawdown checks, or final decision reason.
   - The proof generator has `feature_flags` at `v2/backend/app/proof/non_live_operational_proof.py:159`, but the dashboard does not render stale/missing/unused feature flags in the explainability panel or required pages.

7. No fake reasoning gate is insufficient for production website readiness.
   - The current explanation text is generated from deterministic fixture fields in `v2/backend/app/proof/non_live_operational_proof.py:187`.
   - This is acceptable as a non-live proof fixture, but it is not sufficient for production website explainability because the required pages do not bind explanations to persisted feature, prediction, signal, decision, risk, execution, paper/shadow, and audit records.
   - The broader website still displays placeholder text through `PageShell`, so it avoids fake reasoning but also does not provide real reasoning.

## Requested Check Results

- `feature_snapshot_id` visibility: PARTIAL. Visible only in one proof-dashboard explainability detail and raw/static artifacts, not across required pages.
- `prediction_id` visibility: PARTIAL. Same limitation.
- `risk_decision_id` visibility: PARTIAL. Same limitation.
- Paper/shadow comparison visibility: PARTIAL. Static operator proof table exists, but required Paper / Shadow Trading page and full lineage comparison are missing.
- No fake reasoning: PARTIAL. No production fake reasoning was found, but the implemented explanation UI is fixture-derived and the production pages are placeholders rather than grounded explainability views.

## Proposed Non-Live Autofix Tasks

1. Add a non-live explainability data contract in `v2/frontend/src` for a canonical decision trace:
   - IDs: `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`, paper/shadow IDs.
   - Explanation blocks: confidence delta, contributors, feature flags, source freshness, risk checks, sizing/action/block reasons, PnL attribution, audit events.

2. Wire `LineageBlockView` into required pages and fix the field name mismatch:
   - Rename or map `intent_id` to `execution_intent_id`.
   - Render present/missing state and `lineage_gap_reason` without inventing text.

3. Replace required `PageShell` placeholders with read-only explainability panels backed by static non-live fixtures or backend read-only endpoints:
   - Mission Control
   - Trainer Prediction Monitor
   - Feature Attribution
   - Signal Explainability
   - Symbol Universe
   - Risk Gateway
   - Trader Fleet
   - Paper / Shadow Trading
   - Audit Ledger
   - Live Readiness

4. Add route aliases or actual pages for the REQ_0009 names not present today:
   - `feature-attribution`
   - `symbol-universe`
   - `risk-gateway`
   - `trader-fleet`

5. Expand `operator-proof-dashboard` as a non-live reference implementation:
   - Show full lineage IDs in risk, paper ledger, shadow comparison, and explainability tables.
   - Render all scenarios, not just LABUSDT.
   - Render feature flags, confidence fields, risk checks, execution intent, paper/shadow result, and audit event list.

6. Implement read-only backend GET/explain endpoints or static fixture adapters:
   - `/feature-snapshots/{feature_snapshot_id}/explain`
   - `/predictions/{prediction_id}/explain`
   - `/decisions/{decision_id}/explain`
   - `/risk-decisions/{risk_decision_id}/explain`
   - `/paper-trades/{paper_trade_id}/explain`
   These must remain non-mutating and must not write Redis or touch live exchange paths.

7. Add frontend tests that fail on placeholder-only readiness:
   - Assert each required page renders lineage IDs or explicit missing state.
   - Assert paper/shadow comparison renders lineage IDs and PnL attribution.
   - Assert explanations are derived from payload fields and do not contain generic placeholder prose.

## GO / NO-GO

NO-GO for Website Explainability Contract Readiness.
