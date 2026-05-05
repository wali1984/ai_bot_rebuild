# Planner Turn — Phase 2E2.C Task Definition Harness Leakage Restrip Handoff

## Date

2026-05-05

## Predecessor turn

`PLANNER_TURN_2E2C_OPEN_WORKER_HEALTH_COMPOSITION.md` (2026-05-05) opened
Phase 2E2.C of REQ_0006 and emitted seven artifacts via BEGIN_FILE /
END_FILE blocks. The materializer in
`claude_worklog/tools/claude_master_rebuild_planner.py` parsed the blocks,
but its `parse_begin_file_blocks` strict regex
(`r"^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$"`, line 293) only matches
a bare `END_FILE` closing marker. The previous planner closed each block
with `END_FILE: <repo-relative-path>`, which the strict regex fails to
match. The materializer then fell to its fallback path
(`if content.endswith("END_FILE"): content = content[: -len("END_FILE")]`,
line 305-306), which only strips a bare `END_FILE` suffix. The
`END_FILE: <repo-relative-path>` literal was therefore captured INTO the
file body for every emitted artifact, landing as the absolute last line
of each materialized file.

## Affected files

Seven artifacts emitted with a leaked trailing
`END_FILE: <repo-relative-path>` literal as their final non-empty line:

1. `claude_worklog/agent_supervisor/tasks/108_trainer_parity_2e2c_worker_health_composition_implementation.json`
   (line 106; breaks `json.load`).
2. `claude_worklog/agent_supervisor/tasks/109_trainer_parity_2e2c_worker_health_composition_codex_review.json`
   (line 60; breaks `json.load`).
3. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/170_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_SPEC.md`
   (line 337; cosmetic but violates the planner's own emitted invariant
   "MUST NOT contain any trailing END_FILE: <path> literal").
4. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/171_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_TEST_PLAN.md`
   (line 230; cosmetic).
5. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/172_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_SAFETY_BOUNDARIES.md`
   (line 195; cosmetic).
6. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/173_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO_REQUEST.md`
   (line 88; cosmetic).
7. `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E2C_OPEN_WORKER_HEALTH_COMPOSITION.md`
   (line 151; cosmetic).

Items 1 and 2 are blocking: the supervisor cannot `json.load` the task
definitions, so 108 cannot dispatch and 109 cannot dispatch. Items 3-7
are cosmetic but violate the planner-emitted body invariant reproduced
verbatim in the prompts of 108 and 109 ("The body MUST NOT contain any
trailing END_FILE: <path> literal").

## Decision

Dispatch a narrow Codex recovery task
`110_codex_recovery_2e2c_end_file_marker_leakage_cleanup` under
REQ_0014 (Codex Autonomous Recovery for Non-Live Human Attention) and
REQ_0015 (Planner-Level Human Attention Codex Autorecovery) authority.

Task 110 strips ONLY the trailing leaked `END_FILE: <repo-relative-path>`
literal (and any trailing whitespace-only lines strictly between the body
and the leaked marker) from each of the seven affected files. Task 110
does NOT modify any body line of any leaked file beyond removal of the
trailing leaked marker. Task 110 does NOT modify
`claude_worklog/tools/claude_master_rebuild_planner.py`; the materializer
regex extension is the responsibility of the pre-existing
`093_codex_recovery_2e1d_end_file_marker_leakage_cleanup` task, which
already specifies the regex change and the equivalent 2E1.D body strip.
Task 110 references 093 as the upstream root-cause fix and is independent
of 093's dispatch order — both tasks are required, since 093 does not
touch the seven 2E2.C files and 110 does not touch the materializer.

## Granularity

Consolidated. One Codex recovery task (`110`). No microsplit. The
recovery is L1 (file-content body strip + json.load validation +
secret scan + cross-isolation git status), so it fits the
consolidated_default mode in the master planner prompt.

## Artifacts emitted in this turn

1. `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E2C_TASK_HARNESS_LEAKAGE_RESTRIP.md`
   (this file).
2. `claude_worklog/agent_supervisor/tasks/110_codex_recovery_2e2c_end_file_marker_leakage_cleanup.json`.

Both blocks in this planner turn close with a bare `END_FILE` marker
(no trailing path) so they are strict-regex-compatible with the existing
materializer at `claude_worklog/tools/claude_master_rebuild_planner.py`
line 293. Neither emitted file contains a trailing `END_FILE` literal
anywhere in its body.

## Marker chain

- Cleanup gate (after 110):
  `claude_worklog/agent_supervisor_reliability/87_2E2C_END_FILE_MARKER_LEAKAGE_RECOVERY_GO_NO_GO.md`
  contains `PHASE2E2C_END_FILE_MARKER_LEAKAGE_RECOVERY_PASS`.
- Implementation gate (after 108, gated on 110 PASS):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md`
  contains
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
- Codex gate (after 109):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`
  contains `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS`.

## Hard stops carried into 110

- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis read or write at any layer.
- No Redis command of any kind.
- No live service restart.
- No order placement or cancellation.
- No leverage or margin change.
- No live trading enablement.
- No shipping anywhere.
- No migration in any environment.
- No credential exposure.
- No live-gate approval.
- No modification of any `v2/` source or test file.
- No modification of any prior-milestone trainer-parity, trainer-liveness,
  trainer-worker-health, or trainer-parity-composition source or test
  file.
- No modification of `claude_worklog/tools/claude_master_rebuild_planner.py`
  (deferred to task 093).
- No modification of any body line of the seven leaked files beyond
  removal of the trailing leaked marker (and any trailing whitespace-only
  lines strictly between the body and the leaked marker).

## Next supervisor action

On the next reconciliation tick with the working tree clean:

1. Supervisor dispatches
   `110_codex_recovery_2e2c_end_file_marker_leakage_cleanup` to local
   Codex CLI.
2. On `PHASE2E2C_END_FILE_MARKER_LEAKAGE_RECOVERY_PASS` in 87, supervisor
   re-validates `json.load` parse on 108 and 109 and dispatches 108.
3. On
   `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`
   in 175, supervisor dispatches 109.
4. On `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS` in
   177, the planner closes Phase 2E2.C and Phase 2E2 as a whole and
   opens the next REQ_0006 sub-phase (trainer GPU/checkpoint runner or
   trainer confidence attribution per the consolidated milestone hint
   in the master planner prompt) under a fresh consolidated milestone
   turn.

## Next planner action contingencies

- On `PHASE2E2C_END_FILE_MARKER_LEAKAGE_RECOVERY_FAIL` with concrete
  non-safety blockers, the planner enqueues a narrow REQ_0007 /
  REQ_0014 autofix task scoped to the same seven files only and
  re-runs 110.
- On any safety violation in 110, the planner surfaces to human
  attention; no autofix is permitted.
- If task 093 reaches PASS before 110 dispatches, the materializer
  regex extension takes effect and future planner turn
  `END_FILE: <path>` closing markers will be stripped automatically.
  Task 110 remains required either way, because 093 does not touch the
  seven 2E2.C files. Conversely, if 110 reaches PASS before 093, future
  planner turns must continue to use a bare `END_FILE` closing marker
  until 093 lands.
- On REQ_0011 parallel Codex usage: while 108 and 109 remain
  dispatch-blocked, Codex parallel lane only reviews already committed
  prior-milestone artifacts (2E2.A, 2E2.B, 2E1.E, 2E1.D); no parallel
  Codex run touches the 2E2.C authored paths until 110 PASS unblocks
  108 and 108 commits clean.

PHASE2E2C_PLANNER_TURN_TASK_HARNESS_LEAKAGE_RESTRIP_READY
