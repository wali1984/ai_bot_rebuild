# Website Explainability Contract Readiness Review

Status: BLOCKED

Scope inspected:
- `v2/frontend`
- `v2/backend/app`
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`

Findings:
1. Current paper runtime exposes required lineage IDs.
   - `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` contains `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `signal_id`, `orchestrator_decision_id`, and `execution_intent_id` in `lineage_ids`.
   - `v2/frontend/src/pages/paper-trading/index.tsx:33-39` renders `prediction_id`, `feature_snapshot_id`, `signal_id`, `orchestrator_decision_id`, `risk_decision_id`, and `execution_intent_id`.

2. Trainer and signal pages visibly fail closed instead of inventing reasoning.
   - `v2/frontend/src/pages/operatorTruthComponents.tsx:503-506` renders current `prediction_id` and `feature_snapshot_id` only when current trainer evidence exists.
   - `v2/frontend/src/pages/operatorTruthComponents.tsx:541-564` renders current signal lineage only when status is `REALTIME_RUNTIME_EVIDENCE`; otherwise it displays missing evidence.
   - This satisfies the no-fake-reasoning principle at the UI layer.

3. Backend explainability endpoints are still scaffold-only.
   - `v2/backend/app/api/v1/predictions.py:1-27`, `risk_decisions.py:28-62`, and `paper.py:63-96` advertise `/{id}/explain`, but only expose OPTIONS route metadata and mark status as `skeleton`.
   - This blocks readiness because the website is still driven mainly by public artifact JSON rather than backend read/explain contracts.

4. Paper/shadow comparison visibility is incomplete.
   - `v2/frontend/src/pages/paper-trading/index.tsx:24-26` shows only counts for paper events, shadow decisions, and risk blocks.
   - `v2/frontend/src/pages/operatorTruthComponents.tsx:235-285` shows live observer/shadow status, risk result, risk reason, and paper result, but does not render the full paper/shadow comparison rows with all contract IDs.
   - The underlying payload has shadow ledger evidence, but `v2/frontend/public/operator_runtime/live_observer/latest/current_runtime_truth_payload.json:18-26` has `feature_snapshot_id: null` and `prediction_id: null` for the shadow risk decision, explicitly missing required lineage fields.

Concrete blockers:
- Backend `/predictions/{prediction_id}/explain`, `/risk-decisions/{risk_decision_id}/explain`, and `/paper-trades/{paper_trade_id}/explain` are skeleton metadata only.
- Paper/shadow comparison UI does not present a row-level comparison with `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `execution_intent_id`, paper result, shadow result, and missing lineage fields.
- Live observer/shadow evidence currently includes null `prediction_id` and `feature_snapshot_id`, so the website cannot claim full decision explainability for that path.

Proposed non-live autofix tasks:
1. Implement read-only backend explain DTOs for prediction, risk decision, paper trade, and lineage chain using existing local V2 artifact files only.
2. Add a `PaperShadowComparisonPanel` to render row-level paper/shadow comparison records from current public/runtime payloads, including missing/null ID disclosure.
3. Extend frontend tests to assert `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `execution_intent_id`, paper result, shadow result, and no-guessing missing-evidence text on Mission Control, Signal Explainability, Trainer Prediction Monitor, and Paper Trading.
4. Add a non-live payload validator that marks GO only when current paper/shadow rows either contain all required IDs or explicitly display the missing lineage reason.
