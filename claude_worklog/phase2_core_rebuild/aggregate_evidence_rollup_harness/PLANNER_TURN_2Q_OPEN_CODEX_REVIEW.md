# PLANNER TURN — Phase 2Q Open Codex Review (Lane A `paper_backtest_mvp`; Codex review dispatched via Lane C `codex_watchdog`)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0009 (full decision explainability and under-the-hood UI), REQ_0024 (historical PnL / trade / trainer / decision audit), REQ_0014 / REQ_0015 / REQ_0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), REQ_0011 / REQ_0021 (parallel Codex review and capacity scheduler), REQ_0019 / REQ_0023 (legacy monitor / read-only audit evidence consulted during V2 build), REQ_0022 (LAB hedge-unwind / squeeze legacy failure mapped into the typed evidence pack as a deterministic pointer-presence count), REQ_0007 (Codex autofix authority for non-live blockers).

## Active milestone

REQ_0017 milestone 8 `V2_BACKTEST_AND_PAPER_MVP_READY` closed at HEAD `7b46dbf`; Phase 2M LAB hedge-unwind / squeeze replay-case authoring closed with `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body line one at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`; Phase 2N paper-mode evidence-collection harness closed with `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body line one at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`; Phase 2O shadow-mode evidence-collection harness closed with `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body line one at `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`; Phase 2P historical-PnL replay-wiring evidence-collection harness closed with `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` body line one at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`. Phase 2Q — aggregate-evidence roll-up harness — is the fifth post-consolidation Lane A evidence-collection milestone per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp" fifth bullet. This planner turn dispatches the Phase 2Q Codex review.

## Trigger

Phase 2Q implementation files are materialized under the Codex watchdog recovery `codex_recover_171_phase2q_aggregate_evidence_rollup_harness_implementation` (recovery report `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_171_phase2q_aggregate_evidence_rollup_harness_implementation_REPORT.md`; recovery GO/NO-GO `CODEX_NON_LIVE_RECOVERY_READY`):

- `v2/backend/tests/unit/aggregate_evidence_rollup_harness/__init__.py`
- `v2/backend/tests/unit/aggregate_evidence_rollup_harness/fixtures.py`
- `v2/backend/tests/unit/aggregate_evidence_rollup_harness/harness.py`
- `v2/backend/tests/unit/aggregate_evidence_rollup_harness/test_aggregate_evidence_rollup_harness.py`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/06_IMPLEMENTATION_REPORT.md` (`PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_IMPLEMENTATION_REPORT_READY`)
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/07_GO_NO_GO.md` (`PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_IMPLEMENTATION_READY`)

The Phase 2Q implementation packet was recovered by the Codex watchdog under `codex_recover_171_phase2q_aggregate_evidence_rollup_harness_implementation` after the original `171_phase2q_aggregate_evidence_rollup_harness_implementation` Claude run failed at process invocation with three immediate failures (`stderr.txt` contained `Input must be provided either through stdin or as a prompt argument when using --print`; `materialized_files` was empty). The recovered packet matches the task 171 `required_output_files` set exactly (six files), the `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_IMPLEMENTATION_READY` marker is materialized at `07_GO_NO_GO.md` body line one, and the `.venv/bin/python -m pytest v2/backend/tests/unit/aggregate_evidence_rollup_harness/test_aggregate_evidence_rollup_harness.py -v --no-header` validation produced `17 passed in 0.03s` per the recovery report. Per REQ_0014 / REQ_0015 evidence-first reconciliation, the GO/NO-GO PASS marker at `07_GO_NO_GO.md` overrides any stale queue `pending` status of the original 171 supervisor task; no further 171-implementation re-dispatch is required, and the predecessor surface area for the Phase 2Q Codex review is the file marker, not the queue task status.

## Classification

Lane A `paper_backtest_mvp` evidence-collection sub-task. The Codex review itself runs under Lane C `codex_watchdog` per the standing parallel-capacity rule (Codex executes the review while the Claude planner remains free to author downstream Lane A or first Lane B planning artifacts). No new lineage IDs, no new typed surfaces, no new execution-side surfaces, no Redis access, no `/home/wali/Desktop/AI BOT` mutation, no live-readiness gate flip, no Binance read-only account-history endpoint invocation. The Phase 2Q packet is test-only fixture / harness / pytest authoring driving the existing `PaperModeRuntime` composition root once at harness level plus test-only typed value classes (`AggregateRollupSourceInput`, `AggregateRollupPerSourceRecord`, `AggregateRollupSummary`); the Codex review verifies that the fixtures, the pure-function harness module, the pytest module, the implementation report, and the GO/NO-GO marker all conform to the planning artifacts (01–05) and that no out-of-scope file under `v2/backend/app/` was modified.

## Decision

Author and queue Codex review task `172_phase2q_aggregate_evidence_rollup_harness_codex_review` in this same planner turn. The task scope is:

- Spec / planning inputs (read-only): `01_LEGACY_FAILURE_EVIDENCE.md`, `02_TYPED_INPUT_FIXTURE_SPEC.md`, `03_HARNESS_PIPELINE_SPEC.md`, `04_TEST_PLAN.md`, `05_GO_NO_GO_REQUEST.md`, `PLANNER_TURN_2Q_OPEN_IMPLEMENTATION.md`, this planner-turn note (`PLANNER_TURN_2Q_OPEN_CODEX_REVIEW.md`).
- Implementation evidence (read-only): `06_IMPLEMENTATION_REPORT.md`, `07_GO_NO_GO.md` body line one (must equal `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_IMPLEMENTATION_READY`), and the four test-only files under `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.
- Codex review output surface (write-only): `08_CODEX_REVIEW.md` (carrying `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_REVIEW_READY`) and `09_CODEX_GO_NO_GO.md` (one line: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` or `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_FAIL`).
- Predecessor evidence: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_IMPLEMENTATION_READY` at `07_GO_NO_GO.md` body line one, `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` at `historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md` body line one, `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` at `shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md` body line one, `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` at `paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md` body line one, `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` at `replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md` body line one, `V2_BACKTEST_AND_PAPER_MVP_READY` at `v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` body line one, and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` at `v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` body line one.

Codex review must verify, at a minimum:

- Exactly four authored Python files under `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`: `__init__.py`, `fixtures.py`, `harness.py`, `test_aggregate_evidence_rollup_harness.py`.
- The three deterministic source packs per `02_TYPED_INPUT_FIXTURE_SPEC.md` are exercised by the fixture pack: `paper_mode` pack ×12 typed `AggregateRollupSourceInput` rows, `shadow_mode` pack ×12, `historical_pnl` pack ×12; 36 typed input rows total. Each pack defines four scenarios (`pack_btc_winner_long`, `pack_eth_winner_short`, `pack_lab_loser_short` carrying the LAB hedge-unwind / squeeze legacy-failure pointer literal, `pack_sol_orchestrator_held`); each scenario contributes three steps; 12 scenarios total; 36 input rows total mirroring the typed-record outputs of Phase 2N / 2O / 2P.
- Per-source-pack output: 3 typed `AggregateRollupPerSourceRecord` rows (one per source pack) carrying per-source action / per-symbol / LAB-pointer-presence counts (`lab_pointer_presence_count` equals 3 per source pack reflecting the three LAB-scenario steps per pack).
- Cross-source output: 1 typed `AggregateRollupSummary` row aggregating the three per-source records (`total_inputs` equals 36; `total_lab_pointer_presence_count` equals 9; per-symbol totals equal the sum of per-source per-symbol counts; per-action totals equal the sum of per-source per-action counts).
- Harness-level `PaperModeFlag` invariant: `live_blocked is True`; `mode in {"paper", "live_blocked"}`; the `AggregateRollupSummary.paper_mode_flag` is identity-equal to the harness-level `PaperModeFlag`.
- The fixture-identity invariants per `02_TYPED_INPUT_FIXTURE_SPEC.md` (per-scenario slug namespacing across all three source packs, distinct `risk_decision_id` / `decision_id` / `prediction_id` / `feature_snapshot_id` per row across the 36 rows, deterministic `legacy_evidence_pointer` strings of the form `legacy_evidence__<source>__<slug>__step_N` for the BTC / ETH / SOL scenarios and `legacy_evidence__<source>__lab_hedge_unwind_squeeze__step_N` for the LAB scenarios, deterministic clock counters built via `build_test_clock(start_ms, step_ms)`, no wall-clock helper invocation, no file I/O, no network client import, no environment-variable reader, no heavyweight numerics import, no Redis adapter, all symbols uppercase Binance USD-M tradable symbols `BTCUSDT` / `ETHUSDT` / `SOLUSDT` / `LABUSDT`).
- The harness pipeline invariants per `03_HARNESS_PIPELINE_SPEC.md` (the pure-function harness drives the existing `build_paper_mode_runtime` composition root **once at harness level**, not per row; no per-row composition-root invocation; no `PaperExecutionLedgerRecorder` invocation; no `RiskDecisionEvaluator` invocation; no `OrchestratorDecisionRouter` invocation; no `ReplayBacktestRunner` invocation; only deterministic in-memory counting against the existing `RiskDecisionRecord` carried by each `AggregateRollupSourceInput`; the test-only `AggregateRollupSourceInput`, `AggregateRollupPerSourceRecord`, and `AggregateRollupSummary` value classes are `@dataclass(frozen=True, slots=True)` under the unit-test package and are **not** V2 `app/domain` types, services, adapters, persistence models, API surfaces, schedulers, paper-mode trader processes, or live-readiness gates; the harness preserves `PaperModeRuntimeCompositionError` and `PaperModeDomainError` unchanged).
- The 17 required pytest functions per `04_TEST_PLAN.md` § "Required test cases" all pass under `.venv/bin/python -m pytest v2/backend/tests/unit/aggregate_evidence_rollup_harness/test_aggregate_evidence_rollup_harness.py -v --no-header`.
- Lineage carry-over coverage is asserted from the typed input `RiskDecisionRecord` (`feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, `symbol`) into the per-source action / per-symbol / LAB-pointer-presence counters and into the cross-source summary totals; no lineage field is dropped or rewritten by the roll-up.
- Paper-mode safety invariants are asserted across the harness-level `PaperModeFlag` (`live_blocked is True`; `mode in {"paper", "live_blocked"}`), every `RiskDecisionRecord` carried by every `AggregateRollupSourceInput` (`live_blocked is True`), and the `AggregateRollupSummary.paper_mode_flag` identity-link to the harness-level flag.
- The `pack_lab_loser_short` scenario's per-step pointer literal matches `legacy_evidence__<source>__lab_hedge_unwind_squeeze__step_N` for `N in {1, 2, 3}` across all three source packs and the harness never opens, dereferences, or reads the pointer string as a filesystem path.
- No file under `v2/backend/app/` is modified by the Phase 2Q packet.
- No file under `/home/wali/Desktop/AI BOT` is modified.
- No Redis access of any kind.
- No live service restart, no exchange action, no leverage / margin change, no live-trading enablement, no deployment, no production migration, no secret exposure.
- No Binance read-only account-history endpoint invocation, no Binance HTTP API invocation of any kind by the Phase 2Q packet.
- No new lineage ID is introduced beyond `feature_snapshot_id`, `prediction_id`, `decision_id`, the auto-derived `risk_decision_id`, and the existing `paper_trade_id` field on `PaperExecutionLedgerEntry` carried by the existing composition root (Phase 2Q does not invoke the ledger recorder, so it does not surface `paper_trade_id` either).
- No `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row is introduced.
- No PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation is introduced (those belong to separate, later milestones explicitly out of scope at Phase 2Q).
- No ledger persistence is introduced (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis, no in-memory dict acting as a ledger).
- The live-readiness gate is not flipped; `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval.
- No placeholder file `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py` is modified.
- No populating of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/` occurs.
- No `v2/backend/app/composition/v2_backtest_and_paper_mvp_ready.py` flat-file placeholder is introduced.
- No `mock`, `patch`, or `monkeypatch` is applied to `build_paper_mode_runtime`, `assemble_paper_mode_flag`, `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `build_risk_decision_evaluator`, `assemble_risk_decision_record`, or any of their dependencies.
- The Phase 2Q test or harness modules do not import any test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, or `v2/backend/tests/unit/historical_pnl_replay_wiring/` (Phase 2Q mirrors the typed-record outputs of those harnesses through fresh in-package fixtures, not by cross-importing prior test packages).

## Codex review marker

- PASS body line one: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS`.
- FAIL body line one: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_FAIL`.
- On Codex FAIL with concrete documentation blockers and no safety violation, supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the Phase 2Q packet only.
- If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C / 2J.C / 2L / 2M / 2N / 2O / 2P reconciliation precedent, supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/` and rewrites `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent.
- On any safety violation, surface to human attention; no autofix is permitted.

## Hard safety boundaries (restated)

- No `/home/wali/Desktop/AI BOT` mutation.
- No Redis read or write; no Redis adapter.
- No live service restart; no live-trader / live-orchestrator / live-trainer process modification.
- No exchange order placement or cancellation; no leverage / margin change; no live trading enablement.
- No deployment; no production migration.
- No secret read, print, or commit.
- No Binance read-only account-history endpoint invocation.
- No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- No file under `v2/backend/app/` modified.
- No prior-milestone Phase 2 artifact byte content modified.
- No Phase 2Q planning artifact (01–05), implementation report (06), implementation GO/NO-GO marker (07), planner-turn implementation note, or this Codex-review planner-turn note modified by the Codex reviewer.

## Next steps after Codex PASS

On `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS`, the planner opens the next post-consolidation Lane A or first Lane B category per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` — either the first Lane B explainability UI milestone backed by the typed lineage rows now certified across Phase 2N / 2O / 2P / 2Q, or alternatively the 30-day Binance read-only account-history pull (REQ_0024) wiring as a separate non-live milestone (HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY posture until secret-handling and 30-day-Binance-pull preconditions are independently approved). Live trading remains blocked.

PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_OPEN_CODEX_REVIEW_READY

Authored task `172_phase2q_aggregate_evidence_rollup_harness_codex_review` (Lane C `codex_watchdog`) plus the Phase 2Q Codex-review planner-turn note. Next gate: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/09_CODEX_GO_NO_GO.md`. Live gate remains human-only.
