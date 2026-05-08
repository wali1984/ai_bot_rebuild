# Phase 2M — Replay-Case Authoring: LAB Hedge-Unwind / Squeeze — Scope

## Milestone identity

- Phase code: 2M.
- Title: Replay-Case Authoring: LAB Hedge-Unwind / Squeeze (REQ_0022).
- Lane: `paper_backtest_mvp` (post-consolidation lane A evidence collection per REQ_0020 § "Required proof before live").
- Task granularity mode: consolidated_default. Single consolidated implementation task (`163_phase2m_replay_case_lab_hedge_unwind_squeeze_implementation`).
- Planning HEAD: 7b46dbf.

## MVP relevance

The seven REQ_0017 typed surfaces and the `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation gate are satisfied at HEAD 7b46dbf. The planner is now in post-consolidation lane A evidence collection. Phase 2M authors the first replay-case fixture set — the REQ_0022 LAB hedge-unwind / squeeze case — and runs it through the existing `ReplayBacktestRunner` composition root (`v2/backend/app/composition/replay_backtest_runner/`) to produce typed `ReplayBacktestStep` and `ReplayBacktestSummary` evidence rows for offline inspection. This establishes the pattern that subsequent paper-mode and shadow-mode evidence-collection harnesses follow. No new code surface beyond test-only fixtures and a pytest test module is introduced.

## Blocked by (all materialized at HEAD 7b46dbf)

- `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.

## Next gate

- Local validation marker: `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md`.
- Codex review gate (subsequent task): `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.

## In scope

1. A test-only fixtures module under `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py` providing per-outcome typed `PaperExecutionLedgerEntry` mirror rows and `ReplayBacktestRun` instances for the five REQ_0022 outcome variants. The fixtures use deterministic identifier strings (e.g., `replay_run_lab_hedge_unwind_legacy`, `replay_step_lab_hedge_unwind_legacy_001`, `paper_trade_lab_hedge_unwind_legacy_001`) and a deterministic monotonic test clock.
2. A pytest module under `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py` that:
   - For each of the five REQ_0022 outcome variants, builds a `ReplayBacktestRunner` via `build_replay_backtest_runner(now_ms_clock=...)` with a deterministic monotonic test clock.
   - Calls `assemble_step` for each fixture `PaperExecutionLedgerEntry` to produce a `ReplayBacktestStep`, asserting the typed action / reason / identifier projection per `02_REPLAY_CASE_OUTCOME_MATRIX.md` and `03_TYPED_INPUT_FIXTURE_SPEC.md`.
   - Calls `assemble_summary` over the produced step tuple to produce a `ReplayBacktestSummary`, asserting the per-outcome step counts.
   - Asserts that `live_blocked is True` on every record.
   - Asserts that no record carries any disallowed lineage row (no `shadow_decision_id`, no `execution_intent_id`, no PnL / size / price / fees / slippage / funding fields).
3. An `__init__.py` shim under `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`.
4. An `06_IMPLEMENTATION_REPORT.md` describing the implementation, the per-outcome typed step counts, and the read-only legacy evidence pointers per `01_LEGACY_FAILURE_EVIDENCE.md`.
5. A `07_GO_NO_GO.md` marker file with body `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY` produced after local validation passes.

## Out of scope (explicit)

The following are explicitly out of scope at Phase 2M and remain so until subsequent milestones declare them in scope:

- any modification of any file under `v2/backend/app/` (no domain change, no service change, no composition change, no API change, no CLI change, no jobs change, no main.py change, no adapter change);
- any new domain type, service, composition root, adapter, FastAPI surface, scheduler, background loop, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- any `shadow_decision_id`, `execution_intent_id`, or standalone `paper_trade_id` lineage row beyond the existing `PaperExecutionLedgerEntry.paper_trade_id` field carried into the existing `ReplayBacktestStep.paper_trade_id` projection;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, or squeeze-risk computation;
- any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger);
- any wall-clock helper invocation (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`) in fixture or test code;
- any modification of any file under `claude_worklog/phase2_core_rebuild/` other than the five Phase 2M planning artifacts (00–05) authored by this planner turn and the two implementation artifacts (06–07) authored by the supervisor task;
- any modification of any file under `claude_worklog/autonomous_control_plane/` other than the planner turn note for this turn;
- any modification of any task definition under `claude_worklog/agent_supervisor/tasks/` other than the new `163_phase2m_replay_case_lab_hedge_unwind_squeeze_implementation.json`;
- any modification of `/home/wali/Desktop/AI BOT`;
- any Redis read or write;
- any live service restart;
- any exchange order, leverage change, or margin change;
- any deployment or production migration;
- any secret exposure or commit;
- any flip of the live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.

## Safety posture

Live trading: BLOCKED. Phase 2M is non-live by construction. No file under `/home/wali/Desktop/AI BOT` is read or written. No Redis key is read or written. No live service is restarted. No exchange action is taken. No leverage or margin change is made. No deployment is performed. No production migration is run. No secret value is read, printed, or committed.

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_SCOPE_READY
