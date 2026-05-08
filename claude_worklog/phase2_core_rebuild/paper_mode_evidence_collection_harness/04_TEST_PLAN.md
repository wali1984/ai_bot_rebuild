# Phase 2N — Test Plan

## Test module

`v2/backend/tests/unit/paper_mode_evidence_collection_harness/test_paper_mode_evidence_collection_harness.py`.

The test module imports only from:

- `v2.backend.app.domain.paper_mode` (constants and `PaperModeFlag`).
- `v2.backend.app.domain.paper_execution_ledger` (constants and `PaperExecutionLedgerEntry`).
- `v2.backend.app.domain.replay_backtest_runner` (`ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`, run-mode constants, step / summary action and reason constants).
- `v2.backend.tests.unit.paper_mode_evidence_collection_harness.fixtures` (evidence-pack factory, deterministic test clocks).
- `v2.backend.tests.unit.paper_mode_evidence_collection_harness.harness` (`replay_paper_mode_evidence_pack`, `PaperModeEvidenceTrio`).

The test module must NOT import `time`, `datetime`, `os`, `sys`, `pathlib`, any network client, `torch`, `numpy`, `pandas`, `scikit-learn`, `mock`, or `unittest.mock`. It must NOT use `monkeypatch`. It must NOT define any wall-clock helper.

## Required test functions

At minimum the test module defines the following pytest functions. Each function is a pure assertion against the typed evidence trio returned by `replay_paper_mode_evidence_pack`:

1. `test_paper_mode_evidence_pack_emits_paper_mode_flag` — asserts `paper_mode_flag.mode == "paper"`, `paper_mode_flag.live_blocked is True`, and `paper_mode_flag.flag_emitted_ts_ms` is the deterministic timestamp produced by the test paper-mode clock.
2. `test_paper_mode_evidence_pack_emits_live_blocked_flag_under_live_blocked_request` — same harness with `requested_mode="live_blocked"`; asserts `paper_mode_flag.mode == "live_blocked"` and `paper_mode_flag.live_blocked is True`.
3. `test_paper_mode_evidence_pack_emits_one_trio_per_scenario` — asserts `len(trios) == 5` (one per scenario per `02_TYPED_INPUT_FIXTURE_SPEC.md`).
4. `test_paper_mode_evidence_pack_step_counts_match_per_scenario` — for each scenario asserts `len(trio.steps) == expected_count` per the table in `02_TYPED_INPUT_FIXTURE_SPEC.md` (3 / 3 / 2 / 2 / 2; total = 12).
5. `test_paper_mode_evidence_pack_lineage_carry_over` — for each step asserts that lineage IDs (`feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, `paper_trade_id`, `replay_run_id`) on the produced `ReplayBacktestStep` match the input `PaperExecutionLedgerEntry` and `ReplayBacktestRun`.
6. `test_paper_mode_evidence_pack_typed_action_reason_projection` — asserts the typed `step_action` / `step_reason_code` projection matches the input `ledger_action` / `ledger_reason_code` per the existing `assemble_replay_backtest_step` mirror contract for each REQ_0017 mirror reason in the pack.
7. `test_paper_mode_evidence_pack_live_blocked_invariant_on_every_record` — asserts `live_blocked is True` on every `PaperModeFlag`, every `ReplayBacktestStep`, every `ReplayBacktestRun`, every `ReplayBacktestSummary`, and every `PaperExecutionLedgerEntry` in the pack.
8. `test_paper_mode_evidence_pack_per_scenario_summary_aggregation` — for each scenario asserts the summary `replay_run_id` matches the run, and asserts the summary's allow / deny counts equal the scenario's mirror reason mix per `02_TYPED_INPUT_FIXTURE_SPEC.md`.
9. `test_paper_mode_evidence_pack_distinct_replay_run_ids` — asserts the five returned `replay_run_id` values are pairwise distinct.
10. `test_paper_mode_evidence_pack_distinct_paper_trade_ids` — asserts the 12 returned `paper_trade_id` values are pairwise distinct.
11. `test_paper_mode_evidence_pack_no_disallowed_lineage_rows` — asserts that no produced typed record exposes a `shadow_decision_id`, `execution_intent_id`, or any new standalone `paper_trade_id` lineage row beyond the existing carried `paper_trade_id` field; asserts that no produced typed record carries any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk attribute.
12. `test_paper_mode_evidence_pack_propagates_paper_mode_runtime_composition_error` — passes a non-callable to `paper_mode_clock` and asserts `PaperModeRuntimeCompositionError` propagates with the documented `must_be_callable` reason and `now_ms_clock` field.
13. `test_paper_mode_evidence_pack_propagates_replay_backtest_runner_composition_error` — passes a non-callable to `replay_clock` and asserts `ReplayBacktestRunnerCompositionError` propagates with the documented `must_be_callable` reason and `now_ms_clock` field.

## Forbidden in tests

- No use of `unittest.mock`, `mock`, `patch`, or `monkeypatch`.
- No use of `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`.
- No filesystem write of any artifact.
- No introduction of any new domain type beyond the test-only `PaperModeEvidenceTrio` defined under `harness.py`.
- No assertion that depends on environment variables or secrets.
- No tolerance comparison for floating-point arithmetic; the harness must remain integer-typed across all assertions.
- No `BEGIN_FILE` / `END_FILE` standalone marker line in any test file body.

## Local validation commands (run by supervisor task `165`)

1. `git status --porcelain`.
2. `python -m pytest v2/backend/tests/unit/paper_mode_evidence_collection_harness/test_paper_mode_evidence_collection_harness.py -v --no-header`.
3. Existence checks for the five test-only files plus the planning artifacts and the implementation report and 07 marker.
4. `git diff --stat HEAD -- v2/backend/app/` must show no change.
5. `git diff --stat HEAD -- /home/wali/Desktop/AI\ BOT` must show no change.
6. `git diff --stat HEAD --` against every prior-milestone Phase 2 directory must show no change.
7. `test "$(cat claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/07_GO_NO_GO.md)" = "PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY"`.

PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_TEST_PLAN_READY
