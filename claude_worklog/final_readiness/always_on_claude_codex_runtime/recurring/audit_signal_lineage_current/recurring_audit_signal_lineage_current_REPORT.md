# Recurring Monitor: audit_signal_lineage_current

## Scope
Non-live, read-only audit of current signal lineage across the legacy bot's trainer-to-signal-to-orchestrator-to-execution chain and the V2 rebuild planning surface. This run is part of the always-on Claude+Codex runtime recurring monitor lane and is scoped strictly to the AI BOT REBUILD working tree.

## Boundaries Honored
- Read-only against `legacy_reference/**`, `raw_evidence/**`, `claude_worklog/**`, `requirements/**`, `replay_data/**`, `ollama/outputs/**`, `ollama/evidence_packets/**`.
- No mutation of legacy code, old Redis keys, exchange state, leverage, margin mode, or live trading.
- No process restart, no order placement, no kill-switch toggling, no checkpoint promotion.
- Default LIVE TRADING: BLOCKED is unchanged; ADJUST_LEVERAGE remains gated; CROSS-margin escalation still requires explicit human approval.
- Writes confined to `claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/audit_signal_lineage_current/`.

## Inputs Reviewed (read-only pointers)
- `legacy_reference/**` hybrid trainer prediction-to-signal conversion, signal publisher, orchestrator handoff, Redis writer paths.
- `raw_evidence/**` raw Redis snapshots, signal event log excerpts, prediction stream samples, orchestrator decision traces.
- `requirements/**` signal explainability spec, orchestrator vs risk gateway contract, evidence integrity rule.
- `claude_worklog/trainer_atlas/**` trainer atlas Tier A signal/confidence/reward path indexes and prior chunk hashes.
- `claude_worklog/final_readiness/**` prior recurring monitor outputs, governor lock state, non-drift policy.
- `replay_data/**` non-live signal-lineage traversal samples.

## Audit Checks Executed
1. **Prediction → signal conversion path**: confirmed the trainer prediction-to-signal conversion entrypoint is mapped in the trainer atlas Tier A index; no unclassified branches detected in the current snapshot window.
2. **Signal publishing path**: verified the publisher writes to the documented Redis stream key set only; no new writer paths observed outside the mapped writer inventory.
3. **Orchestrator handoff**: confirmed orchestrator consumes published signals via the documented consumer contract and does not bypass the risk gateway for downstream execution.
4. **Feature freshness lineage**: verified every sampled signal carries a feature-snapshot pointer with freshness timestamp; stale-feature signals are flagged by the existing trainer_stale logic, not silently consumed.
5. **Confidence + calibration lineage**: verified raw model output, confidence, calibration, model version, and checkpoint id are present on sampled signal records per the signal explainability rule.
6. **Risk-gateway gating**: confirmed risk gateway remains the single allow/block authority; orchestrator may not override.
7. **Live-blocked posture**: ENABLE_LIVE_TRADING remains gated; no signal in the sampled window triggered an exchange action path.
8. **Evidence integrity**: each claim above is anchored to raw source pointers in `legacy_reference/**` and `raw_evidence/**`; Ollama outputs and prior summaries were treated as navigation aids only and not as evidence.

## Findings
- Status: HEALTHY for non-live recurring scope.
- No new signal-lineage regressions observed in this audit pass.
- No unclassified prediction-to-signal branches detected in the sampled current window.
- No drift from prior `audit_signal_lineage_current` runs; non-drift governor lock remains intact.
- Live trading remains BLOCKED by default; no escalation requested.
- No `unsafe_unknown` signal-publisher paths newly introduced since the previous recurring run.

## Remediation Recommendations
- None blocking. Continue recurring audit cadence on the always-on lane.
- Maintain coverage-map entries for any signal-lineage code paths still classified as `unsafe_unknown` in the trainer atlas; resolve them before any live-readiness gate is approved.
- Keep mandatory-stop, kill-switch, ADJUST_LEVERAGE, and CROSS-margin escalation flags under explicit human approval.
- Continue requiring signal explainability records (input data, feature snapshot, freshness, raw model output, confidence, calibration, model version, checkpoint, orchestrator reason, risk gateway reason, config version) on every sampled signal before any V2 live-readiness gate is opened.

## Health Evidence Summary
- Read boundary: respected.
- Write boundary: respected (this report + GO_NO_GO only).
- Mutation boundary: respected (no legacy, Redis, exchange, leverage, margin, or live changes).
- Evidence integrity rule: respected (claims anchored to raw source pointers; summaries treated as navigation aids only).
- Completeness override: respected (no token-optimization shortcut reduced coverage; unresolved unknowns flagged, not hidden).

## Outcome
recurring_audit_signal_lineage_current: READY (non-live, read-only).
