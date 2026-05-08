# PLANNER TURN — Phase 2O Open Codex Review (Lane A `paper_backtest_mvp`; Codex review dispatched via Lane C `codex_watchdog`)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0014 / REQ_0015 / REQ_0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), REQ_0011 / REQ_0021 (parallel Codex review and capacity scheduler), REQ_0019 / REQ_0023 (legacy monitor / read-only audit evidence consulted during V2 build), REQ_0007 (Codex autofix authority for non-live blockers).

## Active milestone

REQ_0017 milestone 8 `V2_BACKTEST_AND_PAPER_MVP_READY` closed at HEAD `7b46dbf`; Phase 2M LAB hedge-unwind / squeeze replay-case authoring closed with `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body line one at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`; Phase 2N paper-mode evidence-collection harness closed with `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body line one at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`. Phase 2O — shadow-mode evidence-collection harness — is the third post-consolidation Lane A evidence-collection milestone per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp" third bullet ("Shadow-mode evidence-collection harness"). This planner turn dispatches the Phase 2O Codex review.

## Trigger

Phase 2O implementation files are materialized at HEAD `c869a29` (Codex watchdog recovery from `codex_recover_167_phase2o_shadow_mode_evidence_collection_harness_implementation`):

- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/__init__.py`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py`
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/06_IMPLEMENTATION_REPORT.md` (`PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_REPORT_READY`)
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/07_GO_NO_GO.md` (`PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY`)

The Phase 2O implementation packet was recovered by the Codex watchdog under `codex_recover_167_phase2o_shadow_mode_evidence_collection_harness_implementation` after the original `167_phase2o_shadow_mode_evidence_collection_harness_implementation` supervisor run failed before Claude received a prompt; the recovered packet matches the task 167 `required_output_files` set and the validation-command surface area exactly. Per REQ_0014 / REQ_0015 evidence-first reconciliation, the GO/NO-GO PASS marker at `07_GO_NO_GO.md` overrides any stale queue `pending` status of the original 167 supervisor task; no further 167-implementation re-dispatch is required, and the predecessor surface area for the Phase 2O Codex review is the file marker, not the queue task status.

## Classification

Lane A `paper_backtest_mvp` evidence-collection sub-task. The Codex review itself runs under Lane C `codex_watchdog` per the standing parallel-capacity rule (Codex executes the review while the Claude planner remains free to author downstream Lane A planning artifacts). No new lineage IDs, no new typed surfaces, no new execution-side surfaces, no Redis access, no `/home/wali/Desktop/AI BOT` mutation, no live-readiness gate flip. The Phase 2O packet is test-only fixture / harness / pytest authoring against the existing seven REQ_0017 typed surfaces plus `ShadowModeReadinessFlag` and a test-only `ShadowModeComparisonRecord` value class; the Codex review verifies that the fixtures, the pure-function harness module, the pytest module, the implementation report, and the GO/NO-GO marker all conform to the planning artifacts (01–05) and that no out-of-scope file under `v2/backend/app/` was modified.

## Decision

Author and queue Codex review task `168_phase2o_shadow_mode_evidence_collection_harness_codex_review` in this same planner turn. The task scope is:

- Spec / planning inputs (read-only): `01_LEGACY_FAILURE_EVIDENCE.md`, `02_TYPED_INPUT_FIXTURE_SPEC.md`, `03_HARNESS_PIPELINE_SPEC.md`, `04_TEST_PLAN.md`, `05_GO_NO_GO_REQUEST.md`, `PLANNER_TURN_2O_OPEN_IMPLEMENTATION.md`, this planner-turn note (`PLANNER_TURN_2O_OPEN_CODEX_REVIEW.md`).
- Implementation evidence (read-only): `06_IMPLEMENTATION_REPORT.md`, `07_GO_NO_GO.md` body line one (must equal `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY`), and the four test-only files under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`.
- Codex review output surface (write-only): `08_CODEX_REVIEW.md` (carrying `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_REVIEW_READY`) and `09_CODEX_GO_NO_GO.md` (one line: `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` or `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_FAIL`).
- Predecessor evidence: `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY` at `07_GO_NO_GO.md` body line one, `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` at `paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md` body line one, `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` at `replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md` body line one, and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` at `v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` body line one.

Codex review must verify, at a minimum:

- Exactly four authored Python files under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`: `__init__.py`, `fixtures.py`, `harness.py`, `test_shadow_mode_evidence_collection_harness.py`.
- The four deterministic typed scenarios per `02_TYPED_INPUT_FIXTURE_SPEC.md` are exercised by the fixture pack (`shadow_mode_evidence_pack_btc_long` x3 steps producing `allow_proceed_long`, `shadow_mode_evidence_pack_eth_short` x3 steps producing `allow_proceed_short`, `shadow_mode_evidence_pack_sol_held` x3 steps producing `deny_orchestrator_held`, `shadow_mode_evidence_pack_lab_abstained` x3 steps producing `deny_orchestrator_abstained`; total 12 typed input `OrchestratorDecisionRecord` rows; total 12 produced typed `RiskDecisionRecord` rows; total 12 produced test-only `ShadowModeComparisonRecord` rows; one harness-level `ShadowModeReadinessFlag` with `live_blocked is True`).
- The fixture-identity invariants per `02_TYPED_INPUT_FIXTURE_SPEC.md` (per-scenario slug namespacing, distinct decision IDs, distinct prediction IDs, distinct feature snapshot IDs, deterministic legacy-action evidence pointers, deterministic clock, no wall-clock helper invocation, no file I/O, no network client import, no environment-variable reader, no heavyweight numerics import, no Redis adapter).
- The harness pipeline invariants per `03_HARNESS_PIPELINE_SPEC.md` (the pure-function harness drives the existing risk-gateway composition root end-to-end against typed `OrchestratorDecisionRecord` inputs without mocks, monkeypatching, filesystem access, Redis access, network clients, wall-clock helpers, persistence, or live-service interaction; the test-only `ShadowModeComparisonRecord` value class is a `@dataclass(frozen=True)` under the unit-test package and is not a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, shadow-trader process, or live-readiness gate).
- The 13 required pytest functions per `04_TEST_PLAN.md` § "Required test functions" all pass under `.venv/bin/python -m pytest v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py -v --no-header`.
- Lineage carry-over coverage is asserted for `feature_snapshot_id`, `prediction_id`, `decision_id`, and the auto-derived `risk_decision_id` (`rd_<decision_id>`) from the typed input `OrchestratorDecisionRecord` into the produced `RiskDecisionRecord` and into the paired `ShadowModeComparisonRecord`.
- Shadow-mode safety invariants are asserted across the harness-level `ShadowModeReadinessFlag` (both `ready` and `not_ready` requested states are covered as evidence without enforcing a runtime kill), every produced `RiskDecisionRecord`, and every produced `ShadowModeComparisonRecord`; the `ShadowModeReadinessFlag` carries `live_blocked is True`.
- Legacy-action evidence pointers are deterministic read-only strings of the form `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md#shadow_<scenario_slug>_<ordinal>` and the harness never opens or dereferences these strings as filesystem paths.
- No file under `v2/backend/app/` is modified by the Phase 2O packet.
- No file under `/home/wali/Desktop/AI BOT` is modified.
- No Redis access of any kind.
- No live service restart, no exchange action, no leverage / margin change, no live-trading enablement, no deployment, no production migration, no secret exposure.
- No new lineage ID is introduced beyond `feature_snapshot_id`, `prediction_id`, `decision_id`, and the auto-derived `risk_decision_id` already carried by the existing typed records.
- No `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row is introduced.
- No PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation is introduced (those belong to separate, later milestones explicitly out of scope at Phase 2O).
- No ledger persistence is introduced (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis, no in-memory dict acting as a ledger).
- The live-readiness gate is not flipped; `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval.
- No placeholder file `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py` is modified.
- No populating of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/` occurs.
- No `v2/backend/app/composition/v2_backtest_and_paper_mvp_ready.py` flat-file placeholder is introduced.
- No prior-milestone artifact byte content under `claude_worklog/phase2_core_rebuild/` is modified, including the Phase 2O planning artifacts (01–05), the Phase 2O planner-turn implementation note, the Phase 2O implementation report (06), and the Phase 2O implementation GO/NO-GO marker (07).
- No standalone harness framing token marker line is emitted in any authored review or GO/NO-GO file body.

## Sequencing rule for the next planner turn

The next planner turn opens after task 168 produces its Codex review marker (`PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` or `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_FAIL` with autofix-eligible blockers). On Codex PASS, the planner opens the next post-consolidation Lane A evidence-collection category per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp (post-consolidation evidence collection per REQ_0020 § 'Required proof before live')" — historical-PnL audit Phase 2P stub authoring (read-only legacy-evidence indexing per REQ_0024; non-live, non-FastAPI, non-scheduler; no Binance API call dispatched at this planner turn; the typed audit packet authored under `claude_worklog/historical_pnl_audit/` per REQ_0024 § "Required Artifacts" with a `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` posture until the secret-handling and 30-day-Binance-pull preconditions are independently approved).

On Codex FAIL with concrete documentation blockers and no safety violation, supervisor dispatches a REQ_0007 / REQ_0014 autofix scoped to the Phase 2O packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C / 2J.C / 2L / 2M / 2N reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

## Live-gate posture (restated)

Live trading remains blocked. Phase 2O does not advance the live-readiness gate. `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval, and is NOT requested by this turn or by the Phase 2O Codex review.

## Hard-stop reaffirmation

No modification of `/home/wali/Desktop/AI BOT`. No Redis read or write of any kind by Phase 2O or by its Codex review. No live service restart. No exchange-side action of any kind. No leverage / margin change. No live-trading enablement. No deployment. No production migration. No secret exposure. The Codex review must independently confirm each of these hard-stop invariants for the Phase 2O packet before emitting `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS`.

PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_PLANNER_TURN_OPEN_CODEX_REVIEW_READY
