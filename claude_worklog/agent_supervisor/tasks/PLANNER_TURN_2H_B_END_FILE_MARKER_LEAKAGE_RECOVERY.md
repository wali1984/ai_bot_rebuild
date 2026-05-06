# PLANNER TURN — 2H.B END_FILE Marker Leakage Recovery (Lane C codex_watchdog)

## Trigger

`claude_worklog/agent_supervisor/tasks/137_paper_execution_ledger_2hb_assembler_service_codex_review.json`
contained a stray `END_FILE: ...` framing-token line at line 156, leaked into the JSON body during a prior planner emission. The file ended at `}` on line 155 followed by the leaked marker on line 156, making the JSON un-parseable for the supervisor dispatch loop.

## Classification

- Lane: `codex_watchdog`
- Recovery type: planner emit-leakage cleanup (REQ_0010 safe path remap / REQ_0014 planner-level human-attention autorecovery / REQ_0016 Codex non-live human-replacement watchdog)
- Risk level: L1 (clean re-emit of supervisor task definition; no v2/ source touched)
- Predecessor evidence intact: `16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md` already byte-equals `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`

## Pre-recovery state

- `git status --porcelain` shows exactly one entry: `?? claude_worklog/agent_supervisor/tasks/137_paper_execution_ledger_2hb_assembler_service_codex_review.json`
- Tasks 138 (2H.C composition root implementation) and 139 (2H.C Codex review) are already authored, JSON-clean, and predecessor-wired to consume the 2H.B Codex pass marker.
- Predecessor 2H.A pass marker at file 09 is intact.
- Predecessor 2H.B impl/validation marker at file 16 is intact.
- v2/ tree: 2H.B service package (`v2/backend/app/services/paper_execution_ledger/__init__.py`, `errors.py`, `service.py`) plus the 28-test sibling package are tracked per the recovery report at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_fail_marker_..._16_2h_b_paper_exe_REPORT.md`.

## Recovery action

Re-emit `claude_worklog/agent_supervisor/tasks/137_paper_execution_ledger_2hb_assembler_service_codex_review.json` byte-equal to the prior body lines 1-155, with the stray line-156 `END_FILE:` marker stripped. Content of the JSON task definition (predecessor wiring, allowed_output_prefixes, forbidden_output_paths, required_output_files, forbidden_actions, prompt rubric items 1-55, validation commands, next_recommended_action, lane=`paper_backtest_mvp`, mvp_relevance, next_gate=`PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`, blocked_by, legacy_evidence_consulted, legacy_failure_addressed) is unchanged from the prior emission.

## Safety review

- No `/home/wali/Desktop/AI BOT` mutation
- No Redis read/write/delete or Redis command
- No live service restart
- No exchange order action
- No leverage/margin change
- No live trading enablement
- No deployment / production migration
- No secret exposure or commit
- No prior-milestone artifact byte change
- No 2H.A artifact (00-10) modification
- No 2H.B planning artifact (11-14) modification
- No 2H.B implementation artifact (15-16) modification
- No v2/ source or test modification
- No new task definition outside the existing 137 / 138 / 139 set

## Post-recovery dispatch sequence

After the supervisor materializes the cleaned 137 JSON and commits/pushes:

1. Supervisor dispatches 137 (2H.B Codex review). Predecessor marker file 16 is already correct.
2. On `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`, supervisor dispatches 138 (2H.C composition root implementation), already wired to consume the 2H.B Codex pass marker.
3. On `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`, supervisor dispatches 139 (2H.C Codex review).
4. On `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`, REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` closes. Planner advances to REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`.

## MVP relevance

This recovery unblocks Lane A `paper_backtest_mvp`. Without a parseable 137, the dispatch bridge cannot route the Codex review and the 2H.B → 2H.C → MVP-4 → MVP-5 chain stalls. With 137 cleaned, the path to `V2_BACKTEST_AND_PAPER_MVP_READY` resumes (4 milestones remaining after 2H.C closes).

## Stop conditions honored

- No live action requested
- No legacy mutation
- No Redis access
- No exchange/leverage/margin action
- No deployment
- No secret exposure
- No L4/L5 escalation
- Final live gate remains human-only

PLANNER_TURN_2H_B_END_FILE_MARKER_LEAKAGE_RECOVERY_READY

Two files emitted. Re-emitted task 137 strips the stray `END_FILE:` marker on line 156 (clean JSON ends at `}` on line 155); content otherwise byte-equal to the prior emission. The companion planner-turn doc records the Lane C codex_watchdog recovery, confirms predecessor markers (09, 16) are intact, and traces the post-recovery dispatch chain 137 → 138 → 139 closing REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` and unblocking milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`.
