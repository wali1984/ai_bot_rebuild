# Codex Parallel Review: Website Explainability Contract Readiness

Review timestamp: 2026-05-12 14:57 America/New_York
Scope: `v2/frontend`, `v2/backend/app`, `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
Mode: read-only inspection; no Redis writes, live-service restarts, exchange actions, leverage/margin changes, deployment, or live-trading enablement.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The website has a partial no-guessing explainability surface. Current paper runtime and operator truth payloads expose `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, `signal_id`, `orchestrator_decision_id`, and `execution_intent_id` on key routes. Static proof sections also expose paper/shadow comparison rows and explicitly label many examples as fixture or non-current evidence.

Readiness is blocked because REQ_0009 requires these contracts across named website pages, but multiple named pages are still generic contract placeholders or archive-only sections rather than dedicated explainability pages. One Risk Control panel also labels a block as `REALTIME_RUNTIME_EVIDENCE` whenever an operator truth payload exists, even if the current risk lineage row is missing.

## Evidence Checked

- Requirement: `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
- Runtime truth data path: `v2/frontend/src/pages/operatorTruthData.ts`
- Runtime truth display components: `v2/frontend/src/pages/operatorTruthComponents.tsx`
- Mission Control: `v2/frontend/src/pages/mission-control/index.tsx`
- Trainer Prediction Monitor: `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx`
- Signal Explainability: `v2/frontend/src/pages/signal-explainability/index.tsx`
- Risk Control: `v2/frontend/src/pages/risk-control/index.tsx`
- Paper / Shadow Trading: `v2/frontend/src/pages/paper-trading/index.tsx`
- Generic placeholder route shell: `v2/frontend/src/components/layout/PageShell.tsx`
- Static proof dashboard: `v2/frontend/src/pages/operator-proof-dashboard/index.tsx`
- Current payload samples:
  - `v2/frontend/public/operator_truth/latest/operator_truth_payload.json`
  - `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
  - `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json`
  - `v2/frontend/public/operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json`

## Checks

### feature_snapshot_id visibility

Partial pass.

- Current paper runtime payload includes `current_signal_lineage.lineage_ids.feature_snapshot_id` and the nested feature snapshot object in `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`.
- `SignalLineageTruthPanel` renders `feature_snapshot_id` for realtime signal lineage in `v2/frontend/src/pages/operatorTruthComponents.tsx`.
- `TrainerPredictionTruthPanel` renders `feature_snapshot_id` when trainer status is realtime or `V2_PAPER_TRAINER_WRAPPER_CURRENT`.
- `PaperTradingPage` renders `feature_snapshot_id` from current lineage or trainer prediction.
- Blocker: `Symbol Universe`, `Audit Ledger`, `Signals`, `Executions`, and `Positions` route implementations are generic `PageShell` placeholders. The shell shows only a limited static fixture context for some pages and does not provide the full per-decision REQ_0009 chain.

### prediction_id visibility

Partial pass.

- Current paper runtime and operator truth payloads include `prediction_id`.
- `SignalLineageTruthPanel`, `TrainerPredictionTruthPanel`, `MissionControl` current signal panel, `RiskControlPage`, and `PaperTradingPage` render `prediction_id`.
- Blocker: placeholder routes do not consistently expose `prediction_id` in the required production context. For example, `symbols` and `audit-ledger` are generic `PageShell` routes, and `symbols` has no fixture context block.

### risk_decision_id visibility

Partial pass.

- Current paper runtime and operator truth payloads include `risk_decision_id`.
- `SignalLineageTruthPanel`, `MissionControl` current signal panel, `RiskControlPage`, `PaperTradingPage`, `DecisionDrawers`, and static proof dashboard rows render `risk_decision_id`.
- Blocker: `RiskControlPage` marks the "Current V2 Paper Risk Decision" panel as `REALTIME_RUNTIME_EVIDENCE` whenever `truthPayload` exists, even if `truthPayload.signal_lineage_status.latest_signal` is null and the rendered risk fields are `MISSING`. This can overstate evidence.

### paper/shadow comparison visibility

Partial pass.

- `PaperTradingPage` shows current paper runtime counts, paper event count, shadow decision count, and risk block count.
- `operator-proof-dashboard` has a `TraderFleet` section that renders paper ledger actions and shadow comparisons from static proof payloads.
- Historical replay and non-live proof public payloads include paper ledger and shadow comparison files.
- Blocker: Mission Control intentionally offloads proof archive detail, and the dedicated `Paper / Shadow Trading` page does not render the paper-vs-shadow comparison row detail. Users must go to the Operator Proof Dashboard archive for comparison details, so REQ_0009 paper/shadow comparison visibility is not satisfied on the named `Paper / Shadow Trading` page itself.

### no fake reasoning

Partial pass.

- Positive: current code repeatedly distinguishes `REALTIME_RUNTIME_EVIDENCE`, `STATIC_PROOF_FIXTURE`, `V2_PROOF_ARTIFACT`, `STALE_PAYLOAD`, and `MISSING_EVIDENCE`.
- Positive: Signal and Trainer pages show "Evidence missing - cannot explain without guessing" and keep static examples collapsed.
- Positive: current paper-runtime payload uses concrete lineage IDs and risk checks rather than invented IDs.
- Blocker: the generic `PageShell` is still used by several REQ_0009 routes and displays "Required Production Data Contract" instead of real per-route decision explanations. This is honest, but not contract-ready.
- Blocker: static proof payloads still contain `evidence_missing` fields for model checkpoint, confidence delta, exchange discovery evidence, liquidity/volume/open-interest scores, drawdown check, and stop policy status. Those are labeled as missing, but the pages that depend on them cannot be marked ready.

## Concrete Blockers

1. Dedicated REQ_0009 page coverage is incomplete.
   - `v2/frontend/src/pages/symbols/index.tsx` uses generic `PageShell`.
   - `v2/frontend/src/pages/audit-ledger/index.tsx` uses generic `PageShell`.
   - `v2/frontend/src/pages/signals/index.tsx`, `executions/index.tsx`, and `positions/index.tsx` also use generic `PageShell`.
   - REQ_0009 explicitly requires visibility in Symbol Universe and Audit Ledger, and also requires signal/execution/position lineage chains.

2. Risk Control can overstate realtime evidence.
   - `v2/frontend/src/pages/risk-control/index.tsx` renders the current risk panel badge as `REALTIME_RUNTIME_EVIDENCE` whenever `truthPayload` is present.
   - The panel should key off `truthPayload.signal_lineage_status.status === 'REALTIME_RUNTIME_EVIDENCE'` and non-null `latest_signal`; otherwise it should show `MISSING_EVIDENCE` with the no-guessing text.

3. Paper / Shadow Trading page lacks comparison-row detail.
   - `v2/frontend/src/pages/paper-trading/index.tsx` shows current runtime counts and lineage IDs, but not the actual paper/shadow comparison rows or divergence reasons.
   - Static comparison rows exist in proof artifacts and `operator-proof-dashboard`, but the named Paper / Shadow Trading route does not expose them directly.

4. Feature Attribution is archive-only, not a dedicated routed page.
   - `operator-proof-dashboard` contains a `FeatureAttribution` section, but there is no dedicated route/page for Feature Attribution despite REQ_0009 listing it as required website visibility.

5. Static proof payload still has missing explanation fields.
   - `v2/frontend/public/operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json` includes `confidence_delta: evidence_missing`, `model_checkpoint: evidence_missing`, symbol exchange evidence as `evidence_missing`, and risk `drawdown_check` / `stop_policy_status` as `evidence_missing`.
   - This is correctly disclosed, but blocks readiness.

## Proposed Non-Live Autofix Tasks

1. Replace placeholder REQ_0009 routes with read-only explainability components.
   - Implement dedicated `symbols`, `signals`, `executions`, `positions`, and `audit-ledger` pages using existing `operatorTruthData`, `cockpitData`, and static proof payload readers.
   - No Redis or exchange calls; browser fetches only local public JSON artifacts.

2. Add a dedicated Feature Attribution route.
   - Register `/admin/feature-attribution` and render top positive/negative contributors, stale/missing/unused feature flags, source freshness, `feature_snapshot_id`, `prediction_id`, model/checkpoint, and explicit missing-evidence states.

3. Fix Risk Control evidence badge logic.
   - Change the badge and panel body to display `REALTIME_RUNTIME_EVIDENCE` only when `signal_lineage_status.status` is realtime and `latest_signal` exists.
   - Otherwise render `CURRENT_RISK_DECISION_MISSING` and "Evidence missing - cannot explain without guessing."

4. Expand Paper / Shadow Trading comparison visibility.
   - Render current paper ledger tail and shadow decision rows from `operator_runtime/paper_online/latest/paper_runtime_status.json`.
   - Add a collapsed static comparison table from existing non-live/historical proof payloads with clear `STATIC_PROOF_FIXTURE` labels.

5. Add contract tests.
   - Extend Playwright checks to assert `feature_snapshot_id`, `prediction_id`, `risk_decision_id`, paper/shadow comparison labels, and no-guessing missing evidence text on every REQ_0009 named page.
   - Add a negative test ensuring no page marks missing current lineage as `REALTIME_RUNTIME_EVIDENCE`.

6. Backfill missing static proof fields with explicit source-backed values or keep them blocked.
   - Non-live only: regenerate public proof artifacts with model checkpoint, confidence old/new/delta, exchange discovery evidence, drawdown check, stop policy status, and risk sizing reasons where source evidence exists.
   - If evidence does not exist, preserve `evidence_missing` and keep the readiness gate blocked.

## Safety Notes

- No secrets were inspected or exposed.
- No live trading capability was enabled or implied.
- All recommended fixes are non-live UI/data-contract work against local public artifacts and source code.
