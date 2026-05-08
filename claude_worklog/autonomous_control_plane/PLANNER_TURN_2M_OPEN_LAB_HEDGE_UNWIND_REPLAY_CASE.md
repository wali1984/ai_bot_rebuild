# Planner Turn — Open Phase 2M Replay-Case Authoring (REQ_0022 LAB Hedge-Unwind / Squeeze)

Date: 2026-05-07.
Planning HEAD: 7b46dbf (per `claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json` `last_commit`).
Active requirement (per inbox header): REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md.
Effective enforcing requirements (post-consolidation lane A evidence collection): REQ_0017, REQ_0018, REQ_0019, REQ_0020, REQ_0021, REQ_0022, REQ_0023, REQ_0024.
Lane: paper_backtest_mvp.
Task granularity mode: consolidated_default.
Planner profile: Claude Code Max20 consolidated default.
Codex parallel lane: enabled (review-only while git is dirty during this turn; Codex parallel readonly review may continue against committed milestone artifacts only).

## Evidence-first reconciliation (REQ_0015 #4)

The master planner prompt body still asserts `Current MVP milestone: REPLAY_BACKTEST_RUNNER_MVP` and `Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 3 milestones remaining`. This statement is stale. Per REQ_0015 #4 (GO/NO-GO PASS markers override stale queue/current_status/dashboard noise), at HEAD 7b46dbf the following ten markers are materialized:

1. `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/205_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 1 `TRAINER_PREDICTION_OUTPUT_MVP`.
2. `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/25_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`.
3. `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`.
4. `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP`.
5. `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`.
6. `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 6 `PAPER_MODE_MVP`.
7. `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/25_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — closes REQ_0017 milestone 7 `SHADOW_MODE_READINESS`.
8. `V2_BACKTEST_AND_PAPER_MVP_READY` at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` — closes REQ_0017 milestone 8 (consolidation gate).
9. `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` — closes the Codex review gate of the consolidation packet (supervisor task 162).
10. The Phase 2L exit clause is satisfied; Phase 2M opens here.

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at this planner turn open: zero (already satisfied at marker #8). The planner is now in the post-consolidation lane A evidence-collection sequence per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp (post-consolidation evidence collection per REQ_0020)". The first eligible category is replay-case authoring for the REQ_0022 LAB hedge-unwind / squeeze case.

## What this turn opens (single consolidated milestone)

Phase 2M — Replay-Case Authoring: LAB Hedge-Unwind / Squeeze (REQ_0022).

Consolidated_default mode produces one bundle:

1. This planner turn note.
2. The new milestone packet directory `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/` containing:
   - `00_SCOPE.md` — milestone scope, lane, MVP relevance, in-scope / out-of-scope.
   - `01_LEGACY_FAILURE_EVIDENCE.md` — REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024 legacy evidence consulted and the LAB hedge-unwind / squeeze legacy failure pattern this milestone records.
   - `02_REPLAY_CASE_OUTCOME_MATRIX.md` — the five REQ_0022 outcome variants and how each maps onto today's typed surfaces.
   - `03_TYPED_INPUT_FIXTURE_SPEC.md` — typed input record fixture contracts (what `PaperExecutionLedgerEntry` and `ReplayBacktestRun` instances each outcome requires).
   - `04_TEST_PLAN.md` — pytest plan: per-outcome test name, expected `ReplayBacktestStep` mirror-row sequence, expected `ReplayBacktestSummary` count breakdown, isolation rules, no-time-source rules, no-Redis rules.
   - `05_GO_NO_GO_REQUEST.md` — supervisor GO request body listing the typed surfaces driven, the safety posture, and the marker expected.
3. The supervisor task definition `claude_worklog/agent_supervisor/tasks/163_phase2m_replay_case_lab_hedge_unwind_squeeze_implementation.json` for the consolidated implementation task.

This turn does not author the implementation files. The supervisor task implements the fixtures, the test module, and the milestone success marker (`07_GO_NO_GO.md` body `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY`) plus the implementation report at `06_IMPLEMENTATION_REPORT.md`. After local validation passes, the planner authors the Codex review task in a subsequent turn.

## Consolidated milestone scope (high-level)

The milestone authors test fixtures and a pytest module that drive the existing typed surfaces (`PaperExecutionLedgerEntry`, `ReplayBacktestRun`, the `ReplayBacktestRunner` composition root from `v2/backend/app/composition/replay_backtest_runner/`) for the five REQ_0022 § "Required replay/backtest case" outcome variants:

1. legacy action (close-long-hedge allowed, squeeze loss);
2. keep hedge (do not close the protective long);
3. close short (close residual short instead of the hedge);
4. reduce short (partial residual-short close);
5. block hedge close (risk-gateway default-deny).

At consolidation HEAD the typed surfaces do not model hedge state, residual exposure, position size, PnL, slippage, fees, funding, OI, liquidation map, orderbook depth, or squeeze risk. Per `04_SAFETY_BOUNDARIES_AND_LIVE_GATE_POSTURE.md` those concepts remain explicitly out of scope at consolidation. The Phase 2M milestone therefore authors the LAB scenario as a typed mirror narrative — each outcome maps onto a different sequence of `record_allow` / `record_deny` × `mirror_allow_proceed_long` / `mirror_allow_proceed_short` / `mirror_deny_orchestrator_held` / `mirror_deny_orchestrator_abstained` / `mirror_deny_default` typed step records. The richer hedge-unwind / residual-exposure / squeeze-risk modelling belongs to a separate, later REQ_0022 milestone that is explicitly out of scope at Phase 2M.

The Phase 2M milestone produces no new code surface beyond test-only fixture modules and the pytest test module. No file under `v2/backend/app/` is modified. No FastAPI surface, no scheduler, no background loop, no Redis adapter, no GPU runner, no model-loading subsystem, no strategy library, no shadow_decision_id lineage row, no execution_intent_id lineage row, no PnL / position sizing / quantity / price / fees / slippage computation is introduced.

## REQ_0018 / REQ_0020 mandatory task fields (carried in 163 task json)

- `lane`: `paper_backtest_mvp`.
- `mvp_relevance`: post-consolidation lane A evidence-collection — replay-case authoring for the REQ_0022 LAB hedge-unwind / squeeze case, the highest-priority post-consolidation lane A category per `07_NEXT_STEP_AFTER_CONSOLIDATION.md`. Records the typed mirror narrative of the legacy failure pattern through the existing `ReplayBacktestRunner` composition root, producing per-outcome `ReplayBacktestStep` and `ReplayBacktestSummary` evidence for offline inspection. Establishes the pattern that subsequent paper-mode and shadow-mode evidence-collection harnesses follow.
- `blocked_by`: the seven REQ_0017 Codex PASS markers plus `V2_BACKTEST_AND_PAPER_MVP_READY` and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`. All nine are materialized at HEAD 7b46dbf.
- `next_gate`: `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md`. Codex review gate (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`) follows in a subsequent task.
- `legacy_evidence_consulted`: see `01_LEGACY_FAILURE_EVIDENCE.md` for the full list (legacy_runtime_audit `06_TRAINER_RUNTIME_EVIDENCE.md`, `07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`, `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`, `10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`, `11_FAILURE_MODE_AND_GAP_REGISTER.md`, REQ_0022 inbox body, REQ_0023 sentinel scope, REQ_0024 historical PnL audit scope).
- `legacy_failure_addressed`: the LAB hedge-unwind / squeeze legacy failure where the legacy bot closed the protective long around breakeven and left the short exposed before an approximately 80% pump. Phase 2M does not fix the failure (no risk-gateway logic change is made); it records the failure as the first post-consolidation lane A typed mirror-narrative replay-case fixture so subsequent paper-mode / shadow-mode / risk-gateway-extension milestones have a typed regression input to test against.

## Safety posture (restated)

- Live trading: BLOCKED. Phase 2M does not enable live trading.
- No mutation of `/home/wali/Desktop/AI BOT`. Read-only legacy evidence only.
- No Redis writes / deletes. No live service restart. No exchange action. No leverage / margin change.
- No deployment. No production migration. No secret exposure.
- No file under `v2/backend/app/` is modified by the supervisor task. The forbidden_output_paths list in 163 task json enforces this.
- No `shadow_decision_id`, `execution_intent_id`, or new lineage row introduced. No PnL / position sizing / quantity / price / fees / slippage computation introduced. No persistence (SQL / SQLite / JSON file / Parquet / CSV / Redis / dict-acting-as-ledger) introduced.
- No wall-clock helper invocation (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`) in test or fixture code. Test fixtures and `now_ms_clock` injection use deterministic monotonic test clocks.
- No live-readiness gate flip. The `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` marker remains a separate downstream artifact requiring explicit human approval.

## Codex parallel lane posture during this turn

Per REQ_0011 / REQ_0021, while this planner turn is dirty in the worktree authoring the Phase 2M packet, Codex is restricted to readonly review of already-committed milestones (e.g., a re-read of the V2_BACKTEST_AND_PAPER_MVP_READY consolidation packet under task 162's already-PASS marker, or readonly review of the Phase 2K shadow_mode_readiness composition root). Codex must not patch any file the planner is currently authoring. After this planner turn is committed and the supervisor dispatches task 163, Codex parallel readonly review may proceed against the committed Phase 2M planning artifacts; the actual implementation produced by task 163 is then reviewed by a follow-on Codex task authored in a subsequent planner turn.

## Stop conditions

Standard non-live stop conditions per CLAUDE.md and REQ_0014 / REQ_0016 / REQ_0021 apply. Final live trading approval remains human-only and is not requested by this milestone. Phase 2M is non-live by construction.

## Supervisor expectations

The supervisor materializes this turn's emitted blocks under the named relative paths inside `/home/wali/Desktop/AI BOT REBUILD`. Safe path remap rules per REQ_0010 do not apply to this turn (every emitted path is canonical). High-confidence secret scan runs after materialization; this turn emits no secret values. Commit message: short, descriptive, follows the existing repository convention; do not skip hooks. Push, then dispatch task 163 once git is clean.

PLANNER_TURN_2M_OPEN_LAB_HEDGE_UNWIND_REPLAY_CASE_READY
