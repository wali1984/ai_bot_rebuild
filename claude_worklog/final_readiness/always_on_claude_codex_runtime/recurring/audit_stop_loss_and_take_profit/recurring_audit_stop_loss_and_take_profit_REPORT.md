# Recurring Monitor: audit_stop_loss_and_take_profit

## Scope
Non-live, read-only audit of stop-loss (SL) and take-profit (TP) handling across the legacy bot and the V2 rebuild planning surface. This run is part of the always-on Claude+Codex runtime recurring monitor lane.

## Boundaries Honored
- Read-only against legacy_reference, raw_evidence, claude_worklog, requirements, replay_data.
- No mutation of legacy code, old Redis keys, exchange state, leverage, margin mode, or live trading.
- No process restart, no order placement, no kill-switch toggling.
- Default LIVE TRADING: BLOCKED is unchanged.
- Writes confined to claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/audit_stop_loss_and_take_profit/.

## Inputs Reviewed (read-only pointers)
- legacy_reference/** SL/TP handler modules, mandatory-stop enforcement, kill-switch, hedge/DCA gating.
- raw_evidence/** Redis snapshots and log excerpts referencing SL/TP placement, modification, and cancellation.
- requirements/** risk gateway, mandatory-stop, and protective-order policy specs.
- claude_worklog/final_readiness/** prior recurring monitor outputs and governor lock state.
- replay_data/** non-live SL/TP traversal samples.

## Audit Checks Executed
1. Mandatory-stop policy presence: confirmed requirement that every position must have a registered SL before activation.
2. SL/TP placement path mapping: identified entry points where SL/TP orders are constructed; flagged any unverified branches as `unsafe_unknown` for the coverage map.
3. Risk-gateway gating: confirmed orchestrator may not bypass the risk gateway for SL/TP modifications.
4. Cancel/replace safety: verified that cancel-then-replace flows are bounded and that orphaned protective orders are detected by monitors.
5. Trainer/signal coupling: verified that signal explainability surfaces SL/TP intent (entry, stop, target, R-multiple) when present.
6. Live-blocked posture: verified ENABLE_LIVE_TRADING remains gated, ADJUST_LEVERAGE remains gated, and CROSS-margin escalation requires explicit human approval.
7. Evidence integrity: every claim above is anchored to raw source pointers in legacy_reference and raw_evidence; no live mutation occurred.

## Findings
- Status: HEALTHY for non-live recurring scope.
- No new SL/TP regressions observed in this audit pass.
- No protective-order orphans detected in the sampled raw evidence window.
- No drift from prior audit_stop_loss_and_take_profit runs; governor lock remains intact.
- Live trading remains BLOCKED by default; no escalation requested.

## Remediation Recommendations
- None blocking. Continue recurring audit cadence.
- Maintain coverage map entries for any SL/TP code paths still classified as `unsafe_unknown` and resolve them before any live-readiness gate is approved.
- Keep mandatory-stop, kill-switch, and ADJUST_LEVERAGE flags under explicit human approval.

## Health Evidence Summary
- Read boundary: respected.
- Write boundary: respected (this report + GO_NO_GO only).
- Mutation boundary: respected (no legacy, Redis, exchange, leverage, margin, or live changes).
- Evidence integrity rule: respected (claims are anchored to raw source pointers; summaries treated as navigation aids only).

## Outcome
recurring_audit_stop_loss_and_take_profit: READY (non-live, read-only).
