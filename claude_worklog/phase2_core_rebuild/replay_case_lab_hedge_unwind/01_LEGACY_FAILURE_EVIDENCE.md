# Phase 2M — Legacy Failure Evidence (REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024)

## Legacy failure pattern

LAB hedge-unwind / squeeze: the legacy bot held a hedged position (long protective leg plus a directional short). The protective long was closed around breakeven, leaving the short exposed. An adverse move of approximately 80% followed and produced a large realized loss. The legacy bot did not block the close and did not reduce the residual short before the squeeze.

## Legacy evidence consulted (read-only)

The Phase 2M milestone consults the following legacy evidence sources read-only. None are mutated by the milestone. Each is a path inside the AI BOT REBUILD repo or a referenced category of legacy files; no file under `/home/wali/Desktop/AI BOT` is read or written by the supervisor task.

- `claude_worklog/legacy_runtime_audit/00_AUDIT_INDEX.md` — legacy runtime audit index.
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md` — legacy trainer prediction worker runtime evidence (worker-dead-but-process-alive contributing factor).
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` — legacy orchestrator/trader runtime evidence (untyped decision routing).
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` — legacy signal-to-execution runtime audit (untyped paper-mode posture).
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` — legacy risk-gateway and safety audit (missing default-deny boundary, missing residual-exposure check on hedge close).
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` — legacy failure-mode and gap register (LAB hedge-unwind / squeeze entry).
- `claude_worklog/legacy_runtime_audit/12_LEGACY_MONITOR_INVENTORY.md` — legacy monitor inventory (monitor coverage gaps around hedge / residual exposure).
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md` — the requirement body that motivates this milestone.
- `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md` — sentinel scope for the read-only legacy audit.
- `claude_worklog/requirements_inbox/REQ_0024_HISTORICAL_PNL_TRADE_TRAINER_AUDIT.md` — historical PnL audit scope (the realized-PnL audit milestone is a separate, later lane A category and is not in scope at Phase 2M).
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/03_LEGACY_EVIDENCE_AND_FAILURE_MAPPING.md` — consolidation packet's legacy evidence mapping table.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/04_SAFETY_BOUNDARIES_AND_LIVE_GATE_POSTURE.md` — consolidation packet's safety posture (out-of-scope items at consolidation).

## Legacy V2 surfaces touched (read-only references; no mutation)

The Phase 2M milestone uses the following V2 typed surfaces read-only as the targets that fixtures drive. None of these files are modified by the milestone:

- `v2/backend/app/domain/paper_execution_ledger/__init__.py` — `PaperExecutionLedgerEntry`, `PAPER_LEDGER_ACTION_RECORD_ALLOW`, `PAPER_LEDGER_ACTION_RECORD_DENY`, the five `PAPER_LEDGER_REASON_MIRROR_*` reason constants.
- `v2/backend/app/domain/paper_execution_ledger/record.py` — the `PaperExecutionLedgerEntry` dataclass field set and validation.
- `v2/backend/app/domain/replay_backtest_runner/__init__.py` — `ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`, the five `STEP_REASON_MIRROR_*` reason constants, the two `STEP_ACTION_RECORD_*` action constants.
- `v2/backend/app/domain/replay_backtest_runner/run.py` — `ReplayBacktestRun` dataclass field set and validation (including `live_blocked is True` invariant).
- `v2/backend/app/domain/replay_backtest_runner/step.py` — `ReplayBacktestStep` dataclass field set and validation.
- `v2/backend/app/domain/replay_backtest_runner/summary.py` — `ReplayBacktestSummary` dataclass.
- `v2/backend/app/services/replay_backtest_runner/service.py` — `assemble_replay_backtest_step` and `assemble_replay_backtest_summary` service functions.
- `v2/backend/app/composition/replay_backtest_runner/runtime.py` — `ReplayBacktestRunner` composition root and `build_replay_backtest_runner(now_ms_clock=...)` factory.

## Legacy failure addressed at Phase 2M

Phase 2M does not change risk-gateway logic and does not introduce hedge / residual-exposure / squeeze-risk modelling. Phase 2M records the legacy LAB hedge-unwind / squeeze failure as the first post-consolidation lane A typed mirror-narrative replay-case fixture so that subsequent paper-mode evidence-collection, shadow-mode evidence-collection, and risk-gateway-extension milestones have a typed regression input to test against. The typed surfaces certified by the V2_BACKTEST_AND_PAPER_MVP_READY consolidation gate are the contract that this milestone exercises.

## Legacy mutation policy

Phase 2M reads no file under `/home/wali/Desktop/AI BOT`. Phase 2M reads no Redis key. Phase 2M restarts no live service. Phase 2M places no exchange order. Phase 2M changes no leverage or margin. Phase 2M does not enable live trading. Phase 2M does not deploy. Phase 2M runs no production migration. Phase 2M exposes no secret value.

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_LEGACY_FAILURE_EVIDENCE_READY
