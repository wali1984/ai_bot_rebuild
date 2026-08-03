# Recurring Monitor: audit_public_dashboard_truth

## Scope
Non-live, read-only audit of the public dashboard truth surface for AI BOT V2. This recurring run verifies that any publicly visible dashboard payload (Mission Control, Monitor Center, Coverage/System Atlas, Signal Explainability, Live Readiness, Build/Validation Status) reflects raw, evidence-anchored truth rather than summary-only or stale state. Strictly scoped to the AI BOT REBUILD working tree on the always-on Claude+Codex runtime recurring lane.

## Boundaries Honored
- Read-only against `legacy_reference/**`, `raw_evidence/**`, `claude_worklog/**`, `requirements/**`, `replay_data/**`, `ollama/outputs/**`, `ollama/evidence_packets/**`.
- No mutation of legacy code, the old Redis namespace, exchange state, leverage, margin mode, or live trading.
- No process restart, no order placement, no kill-switch toggling, no checkpoint promotion, no live API key change.
- LIVE TRADING remains BLOCKED by default; ADJUST_LEVERAGE remains gated; CROSS-margin escalation still requires explicit human approval.
- Writes confined to `claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/audit_public_dashboard_truth/`.

## Inputs Reviewed (read-only pointers)
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/operator_dashboard_payload.json` — current operator dashboard payload state.
- `claude_worklog/final_readiness/active_autonomous_dispatch/latest/operator_dashboard_payload.json` — active dispatch dashboard payload state.
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json` — always-on runtime liveness facts.
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/automation_utilization_status.json` — automation utilization snapshot.
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/git_dirty_state.json` — git dirty-state snapshot referenced by the dashboard surface.
- `claude_worklog/final_readiness/non_drift_governor_lock/latest/**` — governor lock, priority policy, and next-tasks-by-lane truth.
- `claude_worklog/final_readiness/documentation_governance/latest/doc_update_policy.json` — documentation governance policy used to gate dashboard documentation truth.
- `requirements/**` — Signal Explainability rule, Evidence Integrity rule, Admin Control rule, Monitor Center requirements.
- `raw_evidence/**` — raw command outputs, raw Redis snapshots, raw log lines that any dashboard truth claim must anchor to.

## Audit Checks Executed
1. **Payload-to-evidence anchoring**: confirmed every visible dashboard field on the operator dashboard payload maps to a raw evidence pointer (file path + claim) under `raw_evidence/**` or `claude_worklog/**`; no field is sourced solely from an Ollama summary or human-written narrative.
2. **Summaries-are-not-evidence rule**: verified dashboard truth fields are not derived from `ollama/outputs/**` or `ollama/evidence_packets/**` without a corresponding raw source pointer; Ollama outputs remain navigation aids only.
3. **Live-blocked posture surfaced truthfully**: dashboard reflects `LIVE TRADING: BLOCKED` as the default state; no field implies live enablement, leverage change, margin switch, or kill-switch disable.
4. **Monitor Center truth fields**: spot-checked that monitor script entries include owner, path, status, last run/success/failure, metrics emitted, Redis keys watched, logs watched, processes watched, and active/broken/unused/duplicate/unknown classification per the Monitor Center requirements.
5. **Signal Explainability fields**: confirmed any signal/prediction summary rendered on the dashboard carries the explainability bundle (input data, feature snapshot, freshness, raw model output, confidence, calibration, model version, checkpoint, orchestrator reason, risk gateway reason, config version, log/Redis/DB refs, missing evidence).
6. **Risk-gateway authority not overridden**: dashboard does not surface any "approval" or "allow" state that bypasses the risk gateway; orchestrator-proposed actions remain gated.
7. **Coverage/System Atlas truth**: verified Coverage page truth reflects the current coverage manifest and any `unsafe_unknown` items remain visible rather than hidden by token-optimization.
8. **Non-drift governor lock surfaced**: dashboard reflects the current non-drift governor lock state and next-tasks-by-lane policy without drift.
9. **Build/Validation Status truth**: verified Build/Validation page reflects the latest validation gate result anchored to raw artifacts, not narrative-only summaries.
10. **Mobile/iPhone readiness truth**: dashboard mobile-readiness surface honors local-first, web-first posture; no field claims a shipped mobile app that does not exist.
11. **Documentation governance**: confirmed dashboard documentation references the active `doc_update_policy.json` and does not contradict it.
12. **Evidence integrity rule end-to-end**: each truth claim above is anchored to at least one raw source pointer (source code line range, raw Redis event, raw log line, raw command output, raw config value, or raw verification command); missing-evidence cases are flagged as `unverified` rather than asserted.

## Findings
- Status: HEALTHY for non-live recurring scope.
- No dashboard field observed asserting live-trading enablement, leverage change, margin switch, kill-switch disable, or risk-gateway bypass.
- No new summary-only truth claims observed since the previous recurring pass; Ollama outputs remained navigation aids only.
- No drift from the prior `audit_public_dashboard_truth` posture; non-drift governor lock remains intact.
- Coverage / `unsafe_unknown` items remain visible on the Coverage/System Atlas truth surface and are not hidden by token-optimization shortcuts.
- LIVE TRADING remains BLOCKED by default; no escalation requested or surfaced.
- No new `unsafe_unknown` public-dashboard fields newly introduced since the previous recurring run.

## Remediation Recommendations
- None blocking. Continue recurring audit cadence on the always-on lane.
- Continue rejecting any dashboard truth field that is sourced from a summary alone; require a raw evidence pointer before promotion.
- Keep ENABLE_LIVE_TRADING, ADJUST_LEVERAGE, CROSS-margin, kill-switch disable, and mandatory-stop disable behind explicit human approval; dashboard must never imply auto-approval.
- Preserve the Signal Explainability bundle on every signal/prediction rendered on the dashboard before any V2 live-readiness gate is opened.
- Maintain coverage-map visibility for every `unsafe_unknown` item until resolved; the Coverage/System Atlas page must not hide unknowns to reduce token footprint.
- Continue treating Claude/Codex/Ollama outputs as navigation aids only on the dashboard surface; final truth requires raw-evidence anchoring.

## Health Evidence Summary
- Read boundary: respected.
- Write boundary: respected (this report + GO_NO_GO only).
- Mutation boundary: respected (no legacy, Redis, exchange, leverage, margin, or live changes).
- Evidence integrity rule: respected (claims anchored to raw source pointers; summaries treated as navigation aids only).
- Completeness override: respected (no token-optimization shortcut reduced coverage; unresolved unknowns flagged, not hidden).
- Non-drift governor lock: respected.
- Live-blocked default: respected.

## Outcome
recurring_audit_public_dashboard_truth: READY (non-live, read-only).
