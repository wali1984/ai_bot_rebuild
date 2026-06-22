# Recurring Monitor — audit_paper_shadow_vs_legacy

- Run timestamp: 2026-05-13
- Monitor: audit_paper_shadow_vs_legacy
- Scope: AI BOT REBUILD only (non-live, read-only legacy)
- Mode: V2_MODE=paper/read_only
- Live trading: BLOCKED (unchanged)

## Boundary Compliance
- Legacy processes: observed read-only (no exec, no signal, no restart).
- Legacy Redis: not mutated; no writes to old keys; no exchange-state reads attempted.
- Exchange state / leverage / margin: untouched.
- Live trader / live trainer: not started, not stopped, not reconfigured.
- Old bot config and .env files: not opened, not edited.
- V2 control plane: confined to ./v2 + ./claude_worklog read/write boundaries.

## Objective
Confirm that the V2 paper shadow ledger and the legacy live ledger remain comparable for non-live audit purposes, without touching either ledger's source of truth and without enabling any execution path.

## Inputs (read-only, evidence pointers)
- ./claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json
- ./claude_worklog/final_readiness/active_autonomous_dispatch/latest/primary_dispatch_state.json
- ./claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_parallel_dispatch_state.json
- ./claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/recurring_monitor_audit_tasks.json
- ./raw_evidence/** (legacy log tails, hashes only)
- Legacy Redis: read-only key enumeration via existing audit adapter (no SET / DEL / EXPIRE)

## Findings
1. Paper shadow ledger continues to record V2-paper fills against legacy market-tick snapshots; ledger format is stable vs. prior recurring run.
2. Legacy live ledger remains the source of truth for live PnL; V2 only mirrors it for diffing. No reconciliation writebacks into legacy occurred this run.
3. Schema drift check: V2 paper rows still include `signal_id`, `confidence`, `feature_snapshot_hash`, `model_version`, `checkpoint_id`, `risk_gate_decision`, `orchestrator_reason`. No missing required columns observed in the recurring sample.
4. Freshness: paper shadow lag relative to legacy tick stream remains within prior recurring monitor's recorded envelope; no new staleness regression introduced by this run.
5. Risk gate posture: LIVE TRADING BLOCKED reaffirmed; no dangerous-setting toggles observed; kill switch / mandatory stop unchanged.
6. Capital gate: post-final live capital gate remains operator-held per prior commits (52d4f72, 64c1cd6); recurring monitor does not advance it.

## Claims with Raw Evidence Pointers
- Claim: V2 paper shadow ledger is comparable to legacy ledger for non-live diffing.
  - Raw evidence pointer: claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json
  - Verification command: `jq '.paper_shadow_ledger // .ledgers' claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json`
  - Confidence: medium
  - Missing evidence: end-to-end row-level diff sample is rotated through latest/ only; recurring/ does not retain row payloads.

- Claim: No legacy mutation, no exchange action, no live-trading toggle was performed by this recurring run.
  - Raw evidence pointer: this report's Boundary Compliance section; absence of write-side tool calls in the run transcript.
  - Verification command: `git status -s | grep -E '\.env|legacy_reference|live_'` should return no matches attributable to this run.
  - Confidence: high
  - Missing evidence: none required (negative invariant, enforced by CLAUDE.md boundaries).

## Anomalies / Blockers
- None new this run.
- Pre-existing non-blocker: paper shadow lag envelope is tracked but not yet alarmed via Monitor Center thresholds; tracked under Phase 2Z follow-up, not regressed here.

## Remediation Recommendation
- Status: NOT BLOCKED — no remediation required this run.
- Optional follow-up (non-blocking): persist a hash-only row-level diff summary under `./raw_evidence/paper_shadow_vs_legacy/<date>/diff_hash_summary.json` so future recurring runs can detect schema drift without storing PII or trade payloads. To be scheduled via existing recurring monitor framework, not via legacy mutation.

## Confidence
- Overall: medium-high.
- Sufficient for recurring non-live monitor pass.
- Insufficient to advance any live-readiness gate (out of scope for this monitor).

## Live Posture
- LIVE TRADING: BLOCKED (unchanged)
- Approval required and not granted to:
  - enable live trading
  - add/activate live API keys
  - change leverage / margin mode
  - increase position size / loss limits
  - disable kill switch / mandatory stop
