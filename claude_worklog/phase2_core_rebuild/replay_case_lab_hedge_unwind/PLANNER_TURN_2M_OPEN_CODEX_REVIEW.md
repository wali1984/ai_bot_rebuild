# PLANNER TURN — Phase 2M Open Codex Review (Lane A paper_backtest_mvp; Codex review dispatched via Lane C codex_watchdog)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0022 (legacy failure: hedge-unwind and short-squeeze risk; LAB replay-case authoring), REQ_0014 / REQ_0015 / REQ_0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), REQ_0011 / REQ_0021 (parallel Codex review and capacity scheduler), REQ_0019 / REQ_0023 (legacy monitor / read-only audit evidence consulted during V2 build).

## Active milestone

REQ_0017 milestone 8 `V2_BACKTEST_AND_PAPER_MVP_READY` is closed at HEAD `d5beba5`:

- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` body line one — `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` body line one — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.

This planner turn opens the first post-consolidation Lane A evidence-collection milestone (highest priority per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Next planner-eligible lanes (post-consolidation) — Lane A — paper_backtest_mvp"): the LAB hedge-unwind / short-squeeze replay-case authoring under `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/`. The Phase 2M implementation is already on disk; this turn dispatches its Codex review.

## Trigger

Phase 2M implementation files are materialized at HEAD `d5beba5`:

- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/__init__.py`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_REPORT_READY`)
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md` (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY`)

The Phase 2M implementation packet was recovered by the Codex watchdog under `codex_recover_163_phase2m_replay_case_lab_hedge_unwind_squeeze_implementation` (committed) after the original `163_phase2m_replay_case_lab_hedge_unwind_squeeze_implementation` supervisor run failed before Claude received a prompt; the recovered packet matches the task 163 `required_output_files` set and validation-command surface area exactly. Per REQ_0014 / REQ_0015 evidence-first reconciliation, the GO/NO-GO PASS marker at `07_GO_NO_GO.md` overrides the stale queue `pending` status of the original 163 supervisor task; no further 163-implementation re-dispatch is required, and the predecessor surface area for the Phase 2M Codex review is the file marker, not the queue task status.

## Classification

Lane A `paper_backtest_mvp` evidence-collection sub-task. The Codex review itself runs under Lane C `codex_watchdog` per the standing parallel-capacity rule (Codex executes the review while Claude planner remains free to author downstream Lane A planning artifacts). No new lineage IDs, no new typed surfaces, no new execution-side surfaces, no Redis access, no `/home/wali/Desktop/AI BOT` mutation, no live-readiness gate flip. The Phase 2M packet is test-only fixture / pytest authoring against the existing seven REQ_0017 typed surfaces; the Codex review verifies that the fixtures, the pytest module, the implementation report, and the GO/NO-GO marker all conform to the planning artifacts (00–05) and that no out-of-scope file under `v2/backend/app/` was modified.

## Decision

Author and queue Codex review task `164_phase2m_replay_case_lab_hedge_unwind_squeeze_codex_review` in this same planner turn. The task scope is:

- Spec / planning inputs (read-only): `00_SCOPE.md`, `01_LEGACY_FAILURE_EVIDENCE.md`, `02_REPLAY_CASE_OUTCOME_MATRIX.md`, `03_TYPED_INPUT_FIXTURE_SPEC.md`, `04_TEST_PLAN.md`, `05_GO_NO_GO_REQUEST.md`.
- Implementation evidence (read-only): `06_IMPLEMENTATION_REPORT.md`, `07_GO_NO_GO.md` body line one (must equal `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY`), and the three test-only files under `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`.
- Codex review output surface (write-only): `08_CODEX_REVIEW.md` (carrying `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_REVIEW_READY`) and `09_CODEX_GO_NO_GO.md` (one line: `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` or `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_FAIL`).
- Predecessor evidence: `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY` at `07_GO_NO_GO.md` body line one and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` at `v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` body line one.

Codex review must verify, at a minimum:

- The five typed-mirror replay-case variants (`legacy_action`, `keep_hedge`, `close_short`, `reduce_short`, `block_hedge_close`) per `02_REPLAY_CASE_OUTCOME_MATRIX.md` are exercised by the fixture builder and the pytest module.
- The fixture-identity invariants per `03_TYPED_INPUT_FIXTURE_SPEC.md` (per-outcome slug namespacing, distinct replay-run IDs, distinct paper-trade IDs, deterministic clock, no wall-clock helper invocation, no file I/O, no network client import, no environment-variable reader, no heavyweight numerics import, no Redis adapter).
- The test-plan invariants per `04_TEST_PLAN.md` (typed mirror projection, lineage carry-over `feature_snapshot_id` / `prediction_id` / `decision_id` / `risk_decision_id` / `paper_trade_id`, live-blocked posture, per-outcome summary counts, distinct replay-run IDs, distinct paper-trade IDs, the documented Phase 2M typing limitation that `close_short` and `reduce_short` share the same typed mirror sequence under the existing seven typed surfaces).
- No file under `v2/backend/app/` is modified by the Phase 2M packet.
- No file under `/home/wali/Desktop/AI BOT` is modified.
- No Redis access of any kind.
- No live service restart, no exchange action, no leverage / margin change, no live-trading enablement, no deployment, no production migration, no secret exposure.
- No new lineage ID is introduced beyond `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, `paper_trade_id` already carried by the existing typed records.
- No `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row is introduced beyond the existing `PaperExecutionLedgerEntry.paper_trade_id` field carry.
- No PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, or squeeze-risk computation is introduced (those belong to a separate, later milestone explicitly out of scope at Phase 2M).
- No ledger persistence is introduced (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis, no in-memory dict acting as a ledger).
- The live-readiness gate is not flipped; `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval.
- No placeholder file `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py` is modified.
- No populating of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/` occurs.
- No `v2/backend/app/composition/v2_backtest_and_paper_mvp_ready.py` flat-file placeholder is introduced.
- The Phase 2M implementation runs `python -m pytest v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py -v --no-header` to green without `mock`, `patch`, or `monkeypatch` on `build_replay_backtest_runner` or its dependencies.

## Sequencing rule for the next planner turn

The next planner turn opens after task 164 produces its Codex review marker (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` or `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_FAIL` with autofix-eligible blockers). On Codex PASS, the planner opens the next Lane A evidence-collection category per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp (post-consolidation evidence collection per REQ_0020 § 'Required proof before live')" — paper-mode evidence-collection harness (a non-live, non-FastAPI, non-scheduler harness that replays a sequence of typed prediction inputs through the existing typed surfaces and records the resulting `PaperExecutionLedgerEntry` mirror sequence and `ReplayBacktestSummary` for offline inspection; pure-function pipeline; no scheduler, no background loop, no FastAPI surface, no persistence, no Redis adapter at this stage).

On Codex FAIL with concrete documentation blockers and no safety violation, supervisor dispatches a REQ_0007 / REQ_0014 autofix scoped to the Phase 2M packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C / 2J.C / 2L reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

## Live-gate posture (restated)

Live trading remains blocked. Phase 2M does not advance the live-readiness gate. `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval, and is NOT requested by this turn or by the Phase 2M Codex review.

## Hard-stop reaffirmation

No modification of `/home/wali/Desktop/AI BOT`. No Redis read or write of any kind by Phase 2M or by its Codex review. No live service restart. No exchange-side action of any kind. No leverage / margin change. No live-trading enablement. No deployment. No production migration. No secret exposure. The Codex review must independently confirm each of these hard-stop invariants for the Phase 2M packet before emitting `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.
