# Phase 2H Legacy Evidence Review — Paper Execution Ledger MVP

This document captures the read-only legacy evidence consulted before opening Phase 2H of REQ_0006 ∩ REQ_0017. No legacy file is modified by Phase 2H. No legacy process is restarted. No Redis key is read or written. No exchange action is taken.

## Sources read (read-only)

- `claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_runtime_audit/12_LEGACY_AUDIT_GO_NO_GO.md`
- Directory listing of `legacy_reference/` and `legacy_reference/trading/` for naming evidence only.
- `v2/backend/app/services/paper_loop.py` (read-only placeholder).
- `v2/backend/app/domain/execution/` (empty placeholder directory; not used).
- Phase 2G artifacts under `claude_worklog/phase2_core_rebuild/risk_gateway_impl/00..25` for predecessor lineage.

## Legacy behavior preserved

- Paper-side action MUST never escape into a live order path. The legacy bot's strict separation between paper and live is preserved by the 2H.A `live_blocked == True` invariant on every constructed `PaperExecutionLedgerEntry`.
- A paper entry MUST be derived from a fully validated upstream decision lineage (prediction → orchestrator decision → risk decision). The 2H.A value-object propagates `prediction_id`, `feature_snapshot_id`, `decision_id`, and `risk_decision_id` as required string fields with the same charset and length rules already used in 2E3.A, 2F.A, and 2G.A. This guarantees lineage continuity when the assembler service is composed in 2H.B.
- A paper entry's reason MUST be traceable back to the exact upstream risk reason. The 2H.A cross-field invariants enforce one-to-one mapping between `ledger_reason_code` and `(input_risk_action, input_risk_reason_code)` pairs.

## Legacy failure addressed

- Legacy paper-side recording (where present) had no typed mirror of risk decisions. There was no machine-checked guarantee that a paper "allow" entry corresponded to an upstream `allow` decision, no machine-checked guarantee that a paper "deny" entry corresponded to an upstream `deny`, and no `paper_trade_id` lineage allowing post-hoc replay/backtest analysis to tie a paper outcome back to the originating risk decision and prediction.
- The 2H.A value-object fixes the typing gap. The new `paper_trade_id` lineage ID introduced at the value-object layer fills the missing link required by REQ_0009 (decision explainability) and REQ_0020 (full lineage). The mirror taxonomy fixed at the value-object layer makes silent drift between risk decisions and paper recordings impossible at the type level.
- Legacy paper-side recording could omit the live-blocked flag entirely, leaving downstream code free to interpret a paper entry as a tradable instruction. The 2H.A invariant `live_blocked: bool` with a `MUST be True` post-init check eliminates this class of bug at construction time.

## V2 proof gate

The 2H.A authored validation suite proves:
- the package imports without loading `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, the gamma.real factory, or the URL env adapter
- the package does NOT import `v2.backend.app.domain.risk_gateway` at the value-object layer
- every `PaperExecutionLedgerEntry` constructed via `__post_init__` enforces all per-field invariants
- every `PaperExecutionLedgerEntry` enforces the cross-field one-to-one mapping between `ledger_action` / `ledger_reason_code` and `(input_risk_action, input_risk_reason_code)`
- every `PaperExecutionLedgerEntry` enforces `live_blocked == True`
- the dataclass is frozen + slotted

## Safety

No mutation of `/home/wali/Desktop/AI BOT`. No Redis access. No service restart. No exchange action. No leverage or margin change. No live trading enablement. No deployment. No production migration. No secret exposure.

PHASE2H_LEGACY_EVIDENCE_REVIEW_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/01_PHASE_2H_LEGACY_EVIDENCE_REVIEW.md
