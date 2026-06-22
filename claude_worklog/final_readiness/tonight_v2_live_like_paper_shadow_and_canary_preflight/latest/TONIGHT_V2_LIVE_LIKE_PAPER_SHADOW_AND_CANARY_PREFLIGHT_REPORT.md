# TONIGHT V2 LIVE-LIKE PAPER / SHADOW / CANARY PREFLIGHT REPORT

- Date: 2026-05-13
- Scope: `AI BOT REBUILD` only. Legacy = read-only observed.
- Live trading status: **BLOCKED_HUMAN_ONLY** (unchanged).
- Objective: stage V2 for a live-like paper + shadow + canary run **tonight**, with all unsafe edges fenced and every dispatch path proven non-drift.

## 1. Mission

Bring V2 to a state where:
1. A live-like paper engine can run uninterrupted overnight against real-time market data.
2. A shadow signal lane mirrors the same inputs the (still-blocked) live lane would consume, with zero exchange side effects.
3. A canary preflight gate verifies that, if a human operator were to flip live, every hard guard would refuse without explicit live-key + capital approval.
4. The always-on Claude/Codex runtime keeps non-drift governor lock through the night without falling back to legacy.

Live trading remains BLOCKED. No order placement, no order cancellation, no leverage change, no margin-mode change, no live-key activation, no kill-switch disable.

## 2. Inputs Read (read-only)

- `claude_worklog/final_readiness/non_drift_governor_lock/latest/CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_REPORT.md`
- `claude_worklog/final_readiness/non_drift_governor_lock/latest/GOVERNOR_PRIORITY_POLICY.md`
- `claude_worklog/final_readiness/non_drift_governor_lock/latest/NEXT_TASKS_BY_LANE.md`
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json`
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/automation_utilization_status.json`
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/git_dirty_state.json`
- `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/recurring_monitor_audit_tasks.json`
- `claude_worklog/final_readiness/active_autonomous_dispatch/latest/ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_PROOF_REPORT.md`
- `claude_worklog/final_readiness/active_autonomous_dispatch/latest/PRIMARY_DISPATCH_PROOF.md`
- `claude_worklog/final_readiness/active_autonomous_dispatch/latest/CODEX_PARALLEL_DISPATCH_PROOF.md`
- `claude_worklog/final_readiness/active_autonomous_dispatch/latest/CLAUDE_IDLE_AND_DISPATCH_DIAGNOSTIC.md`
- `claude_worklog/final_readiness/documentation_governance/latest/doc_update_policy.json`
- `claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.md`
- `claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json`

These are summaries / navigation aids only — not evidence. Every claim below is bound to raw artifacts under `v2/`, `raw_evidence/`, and `claude_worklog/**/latest/*.json` produced by deterministic V2 scripts.

## 3. Preflight Lanes

### Lane A — Live-Like Paper Engine
- Engine: V2 paper executor with the same feature pipeline, signal lane, and risk gateway path the live lane would use, but with `EXECUTION_MODE=paper` and exchange-action surface fully stubbed at the adapter boundary.
- Inputs: real-time ticker/orderbook feeds via the V2 ingest path (read-only on legacy Redis; writes go to `V2_REDIS_PREFIX` only).
- Outputs: paper fills, paper PnL ledger, paper position ledger, audit-ledger entries with `mode=paper`.
- Required preconditions:
  - V2 Redis prefix configured and exclusive (no legacy key writes).
  - Risk gateway `paper_allow_only` policy active.
  - Kill switch present and reachable from GUI Mission Control.
  - Audit ledger append-only and timestamped with monotonic + wallclock.

### Lane B — Shadow Signal Lane
- Mirrors live inputs into the V2 signal/orchestrator path, but every downstream `place_order` / `cancel_order` adapter call is short-circuited at the **risk gateway**, not at the adapter, so the rejection itself is logged with reason `live_blocked_human_only`.
- Purpose: prove that the *full* decision graph (features → model → confidence → orchestrator → risk gateway) refuses to emit a live action even when fed live-like inputs.
- Required preconditions:
  - Risk gateway returns `BLOCK(reason=live_blocked_human_only)` for any `mode=live` request, regardless of orchestrator confidence.
  - Shadow lane writes only to `v2:shadow:*` keys and `audit_ledger` rows with `mode=shadow`.
  - No order-id ever leaves the process boundary.

### Lane C — Canary Preflight Gate
- A one-shot, dry-run probe that asserts each hard guard fires before any live attempt would reach an exchange adapter:
  1. `LIVE_TRADING=BLOCKED` default present and read at startup.
  2. Live API keys are absent or refused by the adapter without explicit human-approval token.
  3. Leverage / margin-mode mutation refused without dual-control approval record.
  4. Daily-loss-limit, max-position, mandatory-stop, kill-switch all loaded and non-default-permissive.
  5. Hedge / DCA / `ADJUST_LEVERAGE` flags default-off.
  6. Capital gate (final live capital approval packet) refuses without the operator signature record.
- The canary gate emits a single JSON verdict per guard. Any `allow` from a guard that should be `block` aborts the night and pins the governor on `live_block_regression`.

## 4. Non-Drift Governor Lock — Tonight

The always-on runner must:
- Keep selecting V2 non-live final-readiness tasks only (per `GOVERNOR_PRIORITY_POLICY.md`).
- Never advance to a legacy-mutation task even if the queue is empty; idle is preferred to drift.
- Re-emit dispatch proof on every task transition into `latest/` under the relevant final-readiness folder.
- Refresh `NON_DRIFT_GOVERNOR_LOCK.json` with the active task id, lane, and an `evidence_pointer` array.

If the governor cannot find a non-live task, it parks on `recurring_monitor_audit_tasks` and emits a `parked` status — it does not synthesize work.

## 5. Hard Guards (must all be true before paper run starts)

| Guard | Required state | Verifier |
|---|---|---|
| Live trading | `BLOCKED_HUMAN_ONLY` | `v2/config/live_state.json` |
| Exchange adapter | `mode=paper` only loadable; `mode=live` requires human token | `v2/exec/adapter_boot.log` |
| Legacy Redis | read-only from V2; no writers from V2 PIDs | `raw_evidence/redis/v2_writer_audit.json` |
| Legacy trainer venv | not mutated; subprocess-only adapter | `raw_evidence/runtime/legacy_python_hash.json` |
| Risk gateway | refuses `mode=live` unconditionally tonight | `v2/risk/gate_decisions.jsonl` |
| Kill switch | reachable from GUI; tested in dry-run | `v2/gui/mission_control_kill_test.json` |
| Audit ledger | append-only; checksum chain valid | `v2/audit/ledger_chain_verify.json` |
| Capital gate | final-live capital approval absent → live refused | `claude_worklog/final_readiness/.../FINAL_LIVE_CAPITAL_GATE.md` |
| Non-drift lock | governor pinned to V2 non-live final-readiness | `claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json` |

Any guard not green → night runs in **paper-only no-shadow** degraded mode, and the canary lane is skipped (not faked).

## 6. Tonight Run Plan

1. **T-0**: Operator confirms guards 1–9 green (read the verifier artifacts, do not infer).
2. **T+0**: Start V2 paper engine. Begin shadow lane in lockstep.
3. **T+0..+5m**: Fire canary preflight gate once; archive verdicts under `claude_worklog/final_readiness/tonight_v2_live_like_paper_shadow_and_canary_preflight/latest/canary_verdicts.json`.
4. **T+5m..+overnight**: Always-on runner cycles monitor + audit tasks; governor stays pinned; no live keys ever loaded; no legacy mutation.
5. **T+overnight**: Emit a morning summary packet from raw paper-ledger, shadow-ledger, and audit-ledger artifacts. No claim is accepted without a raw pointer.

## 7. Stop Conditions

The night auto-stops the paper engine (shadow lane keeps running for forensics) if any of:
- Risk gateway emits an `allow` for a `mode=live` request.
- V2 process is observed writing to a legacy Redis key prefix.
- Audit-ledger checksum chain breaks.
- Governor selects any task outside the non-live final-readiness lanes.
- Capital gate file is mutated by an automated process.

Auto-stop is paper-only. It never *enables* anything; live stays blocked.

## 8. Out of Scope Tonight

- No live key activation, no live order, no leverage change, no margin change.
- No edits under `legacy_reference/**` or `../AI BOT/**`.
- No Docker, no trainer venv mutation, no PyTorch/CUDA upgrade.
- No website / GUI feature work beyond what the canary verifier reads.
- No new strategy approval. No win-rate-based promotion.

## 9. Evidence Pointers (raw)

- Paper engine fills (tonight): `v2/paper/ledger/YYYY-MM-DD.jsonl`
- Shadow decisions (tonight): `v2/shadow/decisions/YYYY-MM-DD.jsonl`
- Risk-gateway decisions: `v2/risk/gate_decisions.jsonl`
- Audit ledger chain: `v2/audit/ledger.jsonl` + `v2/audit/ledger_chain_verify.json`
- Canary verdicts: `claude_worklog/final_readiness/tonight_v2_live_like_paper_shadow_and_canary_preflight/latest/canary_verdicts.json`
- Governor lock state: `claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json`
- Always-on runtime state: `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json`
- Dispatch proofs: `claude_worklog/final_readiness/active_autonomous_dispatch/latest/*.md` + `*.json`

## 10. Verdict

Preflight artifacts, hard guards, lane definitions, non-drift governor lock, and stop conditions are specified. With guards 1–9 green at T-0, V2 is cleared to run **paper + shadow + canary preflight** tonight under `LIVE_TRADING=BLOCKED_HUMAN_ONLY`. If any guard is not green, degrade to paper-only without shadow/canary; do not fabricate green.
