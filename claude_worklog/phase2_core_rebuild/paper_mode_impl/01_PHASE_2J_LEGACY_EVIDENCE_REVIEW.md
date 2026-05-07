# Phase 2J Legacy Evidence Review — Paper Mode MVP

This file documents the read-only legacy evidence consulted to scope Phase 2J. No legacy file is modified. No Redis key is read or written. No live service is restarted. No exchange action is taken. Secret values are not loaded; only key names are referenced.

## Legacy artifacts consulted

- `claude_worklog/legacy_runtime_audit/00_AUDIT_INDEX.md` — runtime audit index, used to enumerate every legacy entry point that carries an implicit live-mode posture.
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md` — trainer runtime evidence, used to confirm that trainer prediction emission does not inspect a typed paper-mode flag and that the trainer's prediction-output surface is paper-safe by construction (it does not place exchange orders).
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` — orchestrator/trader runtime evidence, used to confirm that the trader entry points carry implicit live-mode posture through environment variables and per-call argument passing rather than a typed runtime flag, which is the legacy failure 2J.A addresses by introducing a typed value object.
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` — signal-to-execution audit, used to confirm that the legacy live-mode branch reads from process-global state at the bottom of the call stack, not from a typed flag at the top of the call stack.
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` — risk-and-safety audit, used to confirm that risk gating did not previously refuse to operate on the absence of a typed paper-mode flag.
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` — failure-mode/gap register, used to confirm that the absence of a typed runtime-mode flag is a recurring contributing factor in the failure-case register (LAB hedge unwind / squeeze; ambiguous live-vs-paper posture in trader entry points).
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` — failure-case register; specifically the LAB hedge-unwind / squeeze case as the leading paper-mode-relevance scenario for downstream replay/backtest validation.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/00_PHASE_2I_SUB_PHASE_BREAKDOWN.md` — predecessor sub-phase breakdown, used as the structural template for the 2J sub-phase breakdown.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md` — predecessor domain spec, used as the structural template for the 2J.A domain spec.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/00_PHASE_2H_SUB_PHASE_BREAKDOWN.md` — second predecessor sub-phase breakdown, used as the second structural template for cross-checking the 2J sub-phase breakdown.
- `v2/backend/app/composition/replay_backtest_runner/runtime.py` — pre-existing 2I.C composition root, used to confirm the slotted-runtime / captured-clock pattern that 2J.C will mirror.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py` — pre-existing 2H.C composition root, used to confirm the pure-binder / captured-clock pattern that 2J.B and 2J.C will mirror.
- `v2/backend/app/services/paper_loop.py` — pre-existing one-line scaffold-placeholder file in the services layer; confirmed left UNCHANGED by Phase 2J.
- `v2/backend/app/domain/execution/` — pre-existing zero-byte placeholder directory in the domain layer; confirmed left UNCHANGED by Phase 2J.

## Requirement evidence consulted

- `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md` — REQ_0017 milestone 6 `PAPER_MODE_MVP` is the active milestone target for Phase 2J.
- `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md` — Phase 2J is in approved lane `paper_backtest_mvp` with explicit MVP relevance.
- `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md` — live-readiness gate remains hard-blocked; Phase 2J does NOT introduce any live-enable affordance.
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md` — LAB hedge-unwind / squeeze failure case; the 2J typed flag is a typed precondition for any future paper-mode replay/backtest of that scenario class.
- `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md` — read-only legacy audit sentinel; Phase 2J consults the runtime-audit and read-only-audit artifacts above and mutates none.

## Legacy behavior mapped

- Legacy entry points carry an implicit live-mode posture through process-global state (environment variables and per-call arguments). There is no typed runtime-mode flag in the legacy codebase.
- Legacy `trader.py` and `rl.orchestrator_worker` do not refuse to operate on the absence of a typed paper-mode flag; they default to a live-mode interpretation derived from environment variables.
- Legacy failure modes that contributed to the LAB hedge-unwind / squeeze case included an ambiguous live-vs-paper posture at the trader entry point that made it impossible to assert the runtime mode by typed value.

## Legacy failure addressed by Phase 2J

The absence of a typed runtime-mode flag at the top of the V2 call stack. Phase 2J introduces a typed `PaperModeFlag` value object (2J.A), an exhaustive two-branch service that returns a validated flag (2J.B), and a slotted composition-root runtime that captures the wall-clock reference at build time and adapts the service unchanged (2J.C). The default value is `PAPER_MODE_PAPER`; the only other constant is `PAPER_MODE_LIVE_BLOCKED`; there is NO `live_enabled` constant. Downstream lineage consumers (`paper_trade_id`, `replay_run`, future `shadow_decision_id`) can pattern-match on the value to refuse any live-execution path until the V2 live-readiness gate flips.

## V2 proof gate

The 2J.A unit tests assert that constructing a `PaperModeFlag` with any value other than the two named constants raises `PaperModeDomainError`. The 2J.B service tests assert that any unrecognized requested-mode string raises a service error before producing a flag. The 2J.C composition-root tests assert that the slotted runtime exposes a single `paper_mode_now` attribute that adapts the 2J.B service unchanged and shares the captured `now_ms_clock` closure. None of the three sub-phases introduces a live-enable affordance, a live-execution surface, a Redis read/write, a FastAPI surface, a router, a background loop, a scheduler, a strategy library, or any persistent ledger.

PHASE2J_PAPER_MODE_MVP_LEGACY_EVIDENCE_REVIEW_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_mode_impl/01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md
