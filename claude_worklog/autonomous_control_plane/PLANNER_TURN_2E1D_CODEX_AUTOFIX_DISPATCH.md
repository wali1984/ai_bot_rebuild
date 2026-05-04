# Planner Turn — 2E1.D Codex Autofix Dispatch

## Turn date

2026-05-04

## Active requirement

REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md

## Active milestone

Phase 2E1.D — Trainer Parity Service Composition.

## Decision for this turn

The 091 implementation task PASSED locally
(`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/117_2E1D_SERVICE_COMPOSITION_GO_NO_GO.md`
contains exactly
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`).
The 092 Codex review task ran and emitted FAIL
(`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/119_2E1D_SERVICE_COMPOSITION_CODEX_GO_NO_GO.md`
contains exactly
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_FAIL`)
with five concrete non-safety blockers enumerated at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/118_2E1D_SERVICE_COMPOSITION_CODEX_REVIEW.md`
lines 93-99, and the 'Safety review' section at lines 101-115 reports
'none observed' for every safety-line-item.

This is exactly the fallback scenario documented in the 092 task
prompt § 'next_recommended_action' and in the 091 task prompt
§ 'next_recommended_action': "On
PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_FAIL with concrete
blockers and no safety violation, supervisor dispatches a REQ_0007 /
REQ_0014 autofix task scoped to the four service source files and the
32 new test files only and re-runs Codex review."

This planner turn emits two new supervisor tasks that implement
exactly that fallback, narrowed further (the source files do not need
modification — every blocker is in the test files or in test-plan
documentation):

- `claude_worklog/agent_supervisor/tasks/094_trainer_parity_2e1d_codex_autofix.json`
- `claude_worklog/agent_supervisor/tasks/095_trainer_parity_2e1d_codex_rereview_after_autofix.json`

## Mapping of 092 blockers to 094 remediation

| # | 118 line range | Blocker | 094 remediation target |
|---|---|---|---|
| 1 | 95 | forbidden-token guard scan_files omits two authored test files | edit `v2/backend/tests/unit/services/trainer_parity/test_service_milestone_forbidden_tokens.py` to add the two missing entries; scan_files becomes 34 entries |
| 2 | 96 | 34 vs 32 test-file count | author `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/120_2E1D_TEST_PLAN_FINAL_COUNT_ADDENDUM.md`; declare 34 final; supersede 113 lines 22 and 195-200; do NOT delete tests, do NOT edit 113 in place |
| 3 | 97 | does_not_mutate test lacks identity assertions | edit `v2/backend/tests/unit/services/trainer_parity/test_evaluate_does_not_mutate_supplied_histories.py` to add tuple `is` reference equality and per-element identity assertions |
| 4 | 98 | passes_now_ms test lacks compute_stream_id_growth_in_window equality | edit `v2/backend/tests/unit/services/trainer_parity/test_evaluate_passes_now_ms_into_compose.py` to import compute_stream_id_growth_in_window and assert equality for both prediction and proposal at the same now_ms |
| 5 | 99 | happy-path growth coverage too loose | edit `v2/backend/tests/unit/services/trainer_parity/test_evaluate_returns_snapshot_with_growth_from_history.py` to assert positive integers, sequential string IDs, and history length 3 per stream |

## Why a single consolidated autofix task and not five split tasks

Per the planner profile (Claude Code Max20 consolidated_default), the
default granularity is one milestone-shaped task per remediation
batch. The five blockers all fall inside the same blast radius (four
test files plus one new addendum doc), all share the same predecessor
gate (119 FAIL), all require the same validation suite (the 34
service tests plus cross-isolation), and none of them depends on the
output of another. A single 094 task with seven required_output_files
is the smallest correct unit of work. Split fallback is reserved for
recovery if 094 itself FAILs with split-shaped concrete blockers.

## Why the source files are out of scope

The 092 review's 'Safety review' section confirms the four authored
service source files
(`v2/backend/app/services/trainer_parity/__init__.py`, `errors.py`,
`evaluation.py`, `liveness_service.py`) are clean: none of the five
blockers cites a source-file defect. Rubric rows 1-8, 10-12, 16, 19,
21-23 are PASS in 118. Therefore 094's `forbidden_output_paths`
explicitly excludes `v2/backend/app/services/` — the autofix is not
allowed to touch the source. This narrows blast radius and makes
re-review (095) a pure test/doc verification.

## Why 113 is not edited in place

The test plan 113 at lines 22 and 195-200 stipulated 'exactly 32 test
files' and offered two consolidation paths. The 091 implementation
chose to author 34 (matching the supervisor task definition's 34
`required_output_files` entries at 091.json lines 61-94). Codex review
flagged the 34-vs-32 mismatch as blocker 2 / rubric row 17. The
cleanest reconciliation is a NEW addendum 120 that supersedes the 113
'exactly 32' guidance and justifies each of the 34 authored tests
against a distinct rubric row, rather than editing 113 in place
(which is a predecessor doc that fed both the 091 implementation and
the 092 review). The addendum approach preserves every prior PASS in
the 118 rubric, requires no test deletion, and produces a single
canonical authority for future Codex reviews of milestone 2E1.D.

## Dispatch order

1. Supervisor verifies
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/119_2E1D_SERVICE_COMPOSITION_CODEX_GO_NO_GO.md`
   contains exactly
   `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_FAIL`.
2. Supervisor dispatches
   `094_trainer_parity_2e1d_codex_autofix`.
3. On 094 PASS marker
   `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_AUTOFIX_PASSED`
   in 122, supervisor dispatches
   `095_trainer_parity_2e1d_codex_rereview_after_autofix`.
4. On 095 PASS marker
   `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS`
   in 124, the trainer-liveness assembly stack closes and the
   planner opens 2E1.E (composition root) under a fresh spec turn.

## Stop conditions and fallback

- 094 FAILED with concrete blockers and zero safety violation:
  surface to human attention; no second autofix layer.
- 094 FAILED with safety violation: surface to human attention;
  no autofix.
- 095 FAIL with concrete blockers: surface to human attention.
- 095 FAIL with safety violation: surface to human attention.
- Any modification outside the seven `required_output_files` of 094
  or the two `required_output_files` of 095: hard fail; surface to
  human attention.

## Status of task 093 (end-file marker leakage cleanup)

Task 093
(`claude_worklog/agent_supervisor/tasks/093_codex_recovery_2e1d_end_file_marker_leakage_cleanup.json`)
remains in the supervisor queue but is now superseded by evidence:
the 091 and 092 dispatch chain has already executed successfully
through to a parseable FAIL marker, the four 112 / 113 / 114 / 115
markdown files have already been read by 091 / 092 without their
trailing leakage line affecting downstream behavior, and the
materializer regex hardening that 093 was scoped to deliver is not on
the critical path for completing milestone 2E1.D. Per REQ_0015
§ 'Evidence-first reconciliation', GO/NO-GO PASS / FAIL markers
override stale queue noise; the supervisor should mark 093 as
`superseded_by_evidence` and skip dispatch. The materializer regex
hardening 093 was authored to produce remains a useful future tooling
improvement and may be re-opened as a separate non-blocking task
under `claude_worklog/agent_supervisor_reliability/` after milestone
2E1.D closes.

## Codex parallel lane status this turn

The repository working tree at the start of this turn contained one
modified file
(`claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`)
inside the planner's allowed write surface. After this turn, the
working tree additionally contains three new files in allowed write
surfaces:

- `claude_worklog/agent_supervisor/tasks/094_trainer_parity_2e1d_codex_autofix.json` (new)
- `claude_worklog/agent_supervisor/tasks/095_trainer_parity_2e1d_codex_rereview_after_autofix.json` (new)
- `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E1D_CODEX_AUTOFIX_DISPATCH.md` (this file, new)

No `v2/` path is touched. No
`claude_worklog/phase2_core_rebuild/` path is touched. No prior-task
file is modified. Per the prompt's parallel lane rule, Codex parallel
review of older committed trainer artifacts may resume once these
three files are committed; the dispatch chain (094 then 095) will
proceed in series since each depends on the marker file from the
previous task.

## Hard stops not triggered

- No legacy mutation (`/home/wali/Desktop/AI BOT` untouched).
- No Redis read or write.
- No live trainer / trader / orchestrator / Redis / VPN restart.
- No exchange action.
- No leverage or margin change.
- No live trading enable.
- No deploy intent.
- No production migration.
- No secret exposure.
- No L4 / L5 behavior.
- All writes are inside the planner's allowed materializer prefixes
  (`claude_worklog/agent_supervisor/tasks/` and
  `claude_worklog/autonomous_control_plane/`).
- No prior-milestone trainer-parity source or test file is touched.
- No file under `v2/`, `claude_worklog/security/`, or
  `claude_worklog/requirements_inbox/` is touched.

## End-marker discipline this turn

This turn's three emitted blocks (094.json, 095.json, this markdown)
all close with the bare `END_FILE` form so the strict materializer
regex in
`claude_worklog/tools/claude_master_rebuild_planner.py` function
`parse_begin_file_blocks` matches cleanly. No emitted block uses the
`END_FILE: <path>` close form. This turn therefore introduces zero
new trailing-marker leakage to the working tree.

## Files emitted by this planner turn

- `claude_worklog/agent_supervisor/tasks/094_trainer_parity_2e1d_codex_autofix.json` (new)
- `claude_worklog/agent_supervisor/tasks/095_trainer_parity_2e1d_codex_rereview_after_autofix.json` (new)
- `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E1D_CODEX_AUTOFIX_DISPATCH.md` (this file, new)

No other file is authored, modified, or deleted by this planner
turn. The planner does NOT re-emit 091, 092, 093, 112, 113, 114, 115,
116, 117, 118, 119, the prompt file, or any of the prior planner-turn
markdown artifacts.

## Next planner turn trigger

The planner re-fires after one of:

- 094 emits `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_AUTOFIX_PASSED`
  (continue dispatch chain to 095).
- 094 emits `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_AUTOFIX_FAILED`
  (surface to human attention; no second autofix layer).
- 095 emits `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS`
  (close 2E1.D, open 2E1.E spec turn).
- 095 emits `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_FAIL`
  (surface to human attention; no further autofix layer).
- A safety stop or human-attention condition is detected.
- The supervisor reports inability to dispatch 094 or 095 from a
  clean tree (in which case the planner opens a narrow Codex
  watchdog diagnostic task per REQ_0015 § 'Codex watchdog lane').
