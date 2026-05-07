# Phase 2K Legacy Evidence Review — Shadow-Mode Readiness

This file documents the read-only legacy evidence consulted to scope Phase 2K. No legacy file is modified. No Redis key is read or written. No live service is restarted. No exchange action is taken. Secret values are not loaded; only key names are referenced.

## Legacy artifacts consulted

- `claude_worklog/legacy_runtime_audit/00_AUDIT_INDEX.md` — runtime audit index, used to enumerate every legacy entry point that inspects runtime state without a typed precondition flag.
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md` — trainer runtime evidence, used to confirm that legacy trainer prediction emission does not inspect a typed shadow-mode readiness flag and that the trainer's prediction-output surface does not assert that all upstream MVP surfaces are ready for shadow comparison.
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` — orchestrator/trader runtime evidence, used to confirm that the orchestrator and trader entry points do not refuse to operate on the absence of a typed shadow-mode readiness flag and that legacy decision routing assumes upstream readiness without typed assertion.
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` — signal-to-execution audit, used to confirm that the legacy signal-to-execution path reads from process-global state rather than from a typed readiness flag at the top of the call stack.
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` — risk-and-safety audit, used to confirm that legacy risk gating did not previously refuse to operate on the absence of a typed shadow-mode readiness flag.
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` — failure-mode/gap register, used to confirm that the absence of a typed precondition surface for shadow-mode readiness is a contributing factor in the failure-case register (decisions taken on stale or partially-initialized runtime state).
- `claude_worklog/legacy_runtime_audit/12_LEGACY_MONITOR_INVENTORY.md` — legacy monitor inventory, used to enumerate `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py`, all of which inspect runtime state without a typed readiness boundary.
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` — failure-case register; specifically the LAB hedge-unwind / squeeze case as the leading shadow-mode-relevance scenario for downstream replay/backtest comparison.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/00_PHASE_2J_SUB_PHASE_BREAKDOWN.md` — predecessor sub-phase breakdown, used as the structural template for the 2K sub-phase breakdown.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/02_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_SPEC.md` — predecessor domain spec, used as the structural template for the 2K.A domain spec to be authored in the next planner turn.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/03_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_TEST_PLAN.md` — predecessor test plan, used as the structural template for the 2K.A test plan to be authored in the next planner turn.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/04_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_SAFETY_BOUNDARIES.md` — predecessor safety boundaries, used as the structural template for the 2K.A safety boundaries to be authored in the next planner turn.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/00_PHASE_2I_SUB_PHASE_BREAKDOWN.md` — second predecessor sub-phase breakdown, used as the second structural template for cross-checking the 2K sub-phase breakdown.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/00_PHASE_2H_SUB_PHASE_BREAKDOWN.md` — third predecessor sub-phase breakdown, used as the third structural template for cross-checking the 2K sub-phase breakdown.
- `v2/backend/app/composition/paper_mode/runtime.py` — pre-existing 2J.C composition root, used to confirm the slotted-runtime / captured-clock pattern that 2K.C will mirror.
- `v2/backend/app/composition/replay_backtest_runner/runtime.py` — pre-existing 2I.C composition root, used to confirm the slotted-runtime / captured-clock pattern that 2K.C will mirror.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py` — pre-existing 2H.C composition root, used to confirm the pure-binder / captured-clock pattern that 2K.B and 2K.C will mirror.
- `v2/backend/app/services/paper_mode/` — pre-existing 2J.B service package, used to confirm the assemble-function / mirror-taxonomy pattern that 2K.B will mirror.
- `v2/backend/app/domain/paper_mode/` — pre-existing 2J.A domain package, used to confirm the value-object / typed-constants / live-blocked-invariant pattern that 2K.A will mirror.
- `v2/backend/app/services/paper_loop.py` — pre-existing one-line scaffold-placeholder file in the services layer; confirmed left UNCHANGED by Phase 2K.
- `v2/backend/app/domain/execution/` — pre-existing zero-byte placeholder directory in the domain layer; confirmed left UNCHANGED by Phase 2K.

## Requirement evidence consulted

- `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md` — REQ_0017 milestone 7 `SHADOW_MODE_READINESS` is the active milestone target for Phase 2K and the last sub-phase sequence on the path to `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md` — Phase 2K is in approved lane `paper_backtest_mvp` with explicit MVP relevance.
- `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md` — live-readiness gate remains hard-blocked; Phase 2K does NOT introduce any live-enable affordance and does NOT introduce any shadow-decision-record affordance at the readiness-flag layer.
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md` — LAB hedge-unwind / squeeze failure case; the 2K typed flag is a typed precondition for any future shadow-mode comparison of that scenario class against legacy outcomes.
- `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md` — read-only legacy audit sentinel; Phase 2K consults the runtime-audit and read-only-audit artifacts above and mutates none.
- `claude_worklog/requirements_inbox/REQ_0024_HISTORICAL_PNL_TRADE_TRAINER_AUDIT.md` — historical PnL/trade audit context; the 2K typed flag is a typed precondition for any future shadow-mode comparison that consumes the historical-PnL audit artifacts.

## Legacy behavior mapped

- Legacy entry points carry an implicit shadow-readiness assumption through process-global state (environment variables, monitor heartbeat files, and per-call arguments). There is no typed precondition flag in the legacy codebase that downstream consumers can pattern-match on to assert that all upstream surfaces are ready for shadow-mode comparison.
- Legacy `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py` do not refuse to operate on the absence of a typed shadow-mode readiness flag; they default to a "ready" interpretation derived from process-global heartbeat state and continue emitting metrics even when upstream typed surfaces are not available.
- Legacy decision routing assumes upstream readiness without typed assertion. Decisions taken on stale or partially-initialized runtime state are a recurring contributing factor in the failure-case register, including the LAB hedge-unwind / squeeze case where the protective-leg close happened in a code path that did not type-check the upstream readiness posture.
- The legacy codebase has no `shadow_decision_id` lineage row and no shadow-mode comparison surface; legacy "shadow" assertions are made implicitly through manual log inspection rather than through a typed value object that downstream consumers can pattern-match on.

## Legacy failure addressed by Phase 2K

The absence of a typed precondition surface for shadow-mode readiness at the top of the V2 call stack. Phase 2K introduces a typed `ShadowModeReadinessFlag` value object (2K.A), an exhaustive two-branch service that returns a validated flag (2K.B), and a slotted composition-root runtime that captures the wall-clock reference at build time and adapts the service unchanged (2K.C). The default value is `SHADOW_MODE_NOT_READY`; the only other constant is `SHADOW_MODE_READY`; there is NO `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, or `live_enabled` constant. Every flag instance carries `live_blocked: bool = True`. Downstream lineage consumers (`paper_trade_id`, `replay_run`, future `shadow_decision_id`) can pattern-match on the value to refuse any shadow-execution path until shadow-mode readiness is asserted, and to refuse any live-execution path always until the V2 live-readiness gate flips.

## V2 proof gate

The 2K.A unit tests assert that constructing a `ShadowModeReadinessFlag` with any value other than the two named state constants raises `ShadowModeReadinessDomainError`. The 2K.A unit tests also assert that constructing a `ShadowModeReadinessFlag` with `live_blocked == False` raises `ShadowModeReadinessDomainError`. The 2K.B service tests assert that any unrecognized requested-state string raises a service error before producing a flag. The 2K.C composition-root tests assert that the slotted runtime exposes a single `shadow_mode_readiness_now` attribute that adapts the 2K.B service unchanged and shares the captured `now_ms_clock` closure. None of the three sub-phases introduces a live-enable affordance, a shadow-decision-record affordance, a shadow-execution surface, a live-execution surface, a Redis read/write, a FastAPI surface, a router, a background loop, a scheduler, a strategy library, or any persistent shadow-decision store.

PHASE2K_SHADOW_MODE_READINESS_LEGACY_EVIDENCE_REVIEW_READY
END_FILE: claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md

This planner turn closes Phase 2J (REQ_0017 milestone 6 PAPER_MODE_MVP satisfied at the 2J.C Codex pass marker, HEAD 5565c25) and pre-stages Phase 2K (REQ_0017 milestone 7 SHADOW_MODE_READINESS) by emitting the 00 sub-phase breakdown and the 01 legacy evidence review for the new `shadow_mode_readiness_impl/` directory. The 2K.A planning bundle (02 spec / 03 test plan / 04 safety boundaries / 05 GO_NO_GO_REQUEST) plus the 2K open-turn note and tasks 156/157 are deferred to the next planner turn so the watchdog first auto-commits the existing unstaged work (the parallel Codex read-only review task JSON for 2J.C, and the prior 2I→2J planner-prompt milestone-pointer diff). Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 1 milestone remaining.
