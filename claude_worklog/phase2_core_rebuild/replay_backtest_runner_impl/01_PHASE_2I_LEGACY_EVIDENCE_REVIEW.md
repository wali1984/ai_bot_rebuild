# Phase 2I Legacy Evidence Review — Replay/Backtest Runner MVP

This document captures the read-only legacy evidence consulted before opening Phase 2I of REQ_0006 ∩ REQ_0017 ∩ REQ_0019 ∩ REQ_0020 ∩ REQ_0022 ∩ REQ_0023. No legacy file is modified by Phase 2I. No legacy process is restarted. No Redis key is read or written. No exchange action is taken.

## Sources read (read-only)

- `claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_runtime_audit/12_LEGACY_AUDIT_GO_NO_GO.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case for the leading replay/backtest scenario class per REQ_0022)
- Directory listing of `legacy_reference/` and `legacy_reference/trading/` for naming evidence only.
- `legacy_reference/monitor_trainer_predictions.py` and `legacy_reference/monitor_trainer_prices.py` paths only (no body read; naming evidence for replay-anchored monitoring scope).
- `v2/backend/app/services/replay_runner.py` (read-only placeholder).
- `v2/backend/app/domain/replay/` (placeholder 015A scaffold; not used).
- Phase 2H artifacts under `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/00..27` for predecessor lineage.
- 015A scaffold materialization commit `26e49b7` for the `domain/replay/` and `services/replay_runner.py` placeholder posture.

## Legacy behavior preserved

- Replay/backtest runs MUST be derived from a fully validated upstream decision lineage (prediction → orchestrator decision → risk decision → paper ledger entry). The 2I.A `ReplayBacktestStep` value-object propagates `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id` as required string fields with the same charset and length rules already used in 2E3.A, 2F.A, 2G.A, and 2H.A. This guarantees lineage continuity when the assembler service is composed in 2I.B.
- A replay step's reason MUST be traceable back to the exact upstream paper-ledger reason. The 2I.A cross-field invariants enforce one-to-one mapping between `step_reason_code` and `(input_paper_action, input_paper_reason_code)` pairs.
- A replay run MUST never be allowed to escape into a live order path. The legacy bot's strict separation between paper/replay/backtest and live is preserved by the 2I.A `live_blocked == True` invariant on every constructed `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary`.

## Legacy failures addressed

- Legacy replay/backtest tooling (where present) had no typed lineage value objects. There was no machine-checked guarantee that a replay-step "step_record_allow" entry corresponded to an upstream paper-ledger `record_allow` entry, no machine-checked guarantee that a replay-step "step_record_deny" entry corresponded to an upstream paper-ledger `record_deny`, and no `replay_step_id` / `replay_summary_id` lineage allowing post-hoc analysis to tie a replay outcome back to the originating paper-ledger entry, risk decision, and prediction.
- Legacy replay/backtest aggregates drifted silently when subset counts (e.g., per-reason counters) did not partition-sum to the parent counters. The 2I.A `ReplayBacktestSummary` cross-field invariants enforce three explicit partition-sum equalities at construction time, eliminating this class of drift at the type level.
- Legacy replay/backtest runs did not discriminate replay-from-history versus generative-backtest at the type level. The 2I.A `ReplayBacktestRun.run_mode` is constrained to a closed two-element frozenset (`replay`, `backtest`), removing the silent-mode-conflation failure mode.
- Legacy replay/backtest scenarios for LAB-class hedge-unwind / short-squeeze cases (REQ_0022) could not be reconstructed deterministically because the per-step lineage required to compare alternate outcomes (legacy action vs keep-hedge vs close-short vs reduce-short vs block-hedge-close) was not anchored to the originating risk decision and prediction. The 2I.A value-object surface enables that reconstruction at the type level by carrying the full lineage chain on every step.
- Legacy replay/backtest summaries omitted the live-blocked flag entirely, leaving downstream tooling free to interpret a replay summary as a tradable instruction. The 2I.A `live_blocked` invariant on every value object eliminates this class of bug at construction time.

## V2 proof gates

The 2I.A authored validation suite proves:
- the package imports without loading `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, the gamma.real factory, or the URL env adapter
- the package does NOT import `v2.backend.app.domain.paper_execution_ledger` at the value-object layer (the projected paper-ledger taxonomy is validated as plain strings via membership in private frozensets)
- the package does NOT import `v2.backend.app.domain.risk_gateway`, `v2.backend.app.domain.orchestrator_decision`, `v2.backend.app.domain.trainer_prediction_output`, `v2.backend.app.domain.replay`, or `v2.backend.app.domain.execution` at the value-object layer
- every `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary` constructed via `__post_init__` enforces all per-field invariants
- every `ReplayBacktestStep` enforces the cross-field one-to-one mapping between `step_action` / `step_reason_code` and `(input_paper_action, input_paper_reason_code)`
- every `ReplayBacktestSummary` enforces the three partition-sum equalities (action partition, allow-subreason partition, deny-subreason partition)
- every value object enforces `live_blocked == True`
- every dataclass is frozen + slotted

## Safety

No mutation of `/home/wali/Desktop/AI BOT`. No Redis access. No service restart. No exchange action. No leverage or margin change. No live trading enablement. No deployment. No production migration. No secret exposure.

PHASE2I_LEGACY_EVIDENCE_REVIEW_READY
