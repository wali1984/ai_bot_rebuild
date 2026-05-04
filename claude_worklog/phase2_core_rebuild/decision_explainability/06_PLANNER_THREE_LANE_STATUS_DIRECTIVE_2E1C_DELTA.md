# Planner Directive — Three-Lane Status as of 2026-05-03 (post 2E1.C.β Codex PASS, sanity-check correction)

This is a Master Non-Live Rebuild Planner directive. It does not
execute code, write Redis, restart live services, or modify legacy.
It updates the verified state of the three parallel non-live rebuild
lanes (REQ_0006, REQ_0008, REQ_0009) after the 2E1.C.β final Codex
PASS landed and orders the agent_supervisor to dispatch only what is
currently safe.

This directive supersedes the lane-A and lane-C sections of
`decision_explainability/05_PLANNER_THREE_LANE_STATUS_DIRECTIVE.md`
where they are inconsistent with the verified state below. Lane B is
unchanged and remains parked.

This turn's re-emit corrects two factual errors in the prior 06 turn
(the "body cleanup" claim for files 80-83 and the matching self-claim
on directive 06) and replaces the previous sanity check #2 with a
corrected check that accepts the canonical harness emit-trailer. The
narrow-scope δ-tree grep changes recorded in task 079 step 4 and task
080 rubric item 10 (the only changes that actually landed in the
prior 06 turn) remain unchanged and are the canonical mitigation for
the 2E1.B-era END_FILE leak class.

## Source of authority

- Active requirement set (unchanged):
  - `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`
  - `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`
  - `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
- Planner profile: Claude Code Max20 consolidated_default. Codex Pro
  parallel review/autofix lane is enabled, gated on
  `git_clean_and_no_active_dirty_claude_output`.
- Harness emit-trailer fact (re-confirmed at this turn's read time):
  the BEGIN_FILE / END_FILE materializer writes the literal
  `END_FILE: <repo-relative path>` line as the final non-empty line
  of every materialized file. Older committed JSON task definitions
  (e.g. `agent_supervisor/tasks/060_…`, `…/064_…`, `…/078_…`) are
  stripped of the trailer at commit time by the supervisor commit
  hook; older committed Markdown spec files in
  `trainer_gpu_parity_impl/` (e.g. file `70_PLANNER_2E1C_ALPHA_VALIDATION_DISPATCH_DIRECTIVE.md`)
  retain the trailer as plain text, byte-identical to the harness
  output. Both behaviors are pre-existing, not regressions.

## Lane A — REQ_0006 trainer parity (next sub-phase: 2E1.C.δ)

Verified state (read at planner turn time):

| Artifact | Path | Verified value |
| --- | --- | --- |
| 2E1.A Codex pass | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` |
| 2E1.B Codex pass | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` |
| 2E1.C.α Codex pass | `trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` |
| 2E1.C.β final Codex pass | `trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md` | `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` |
| 2E1.C.δ composition spec | `trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md` | body intact; final non-empty line is the canonical harness END_FILE trailer; status marker `PHASE2E1C_DELTA_COMPOSITION_SPEC_READY` is the second-to-last non-empty line |
| 2E1.C.δ test plan | `trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md` | body intact; END_FILE leak self-check narrowed to four scopes (δ source tree, δ test tree, file 84, file 85) per "END_FILE marker leak self-check" section |
| 2E1.C.δ safety boundaries | `trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md` | body intact; canonical trailer present |
| 2E1.C.δ GO request | `trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md` | body intact; `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED` is the second-to-last non-empty line |
| 2E1.C.δ implementation task | `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json` | step-4 grep scope narrowed to delta source/test trees and files 84/85 only; canonical trailer will be stripped by the supervisor commit hook (matches 060/064/078 precedent) |
| 2E1.C.δ Codex review task | `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json` | rubric item 10 grep scope narrowed accordingly; canonical trailer will be stripped at commit time |

### What the prior 06 turn actually achieved (corrected accounting)

The prior 06-turn output included a "Cleanup performed this turn"
section that claimed two things this turn now corrects:

1. (false claim, now corrected) "Re-emits files 80-83 with clean
   bodies — final line is the `PHASE2E1C_DELTA_*_READY` status
   marker, no trailing `END_FILE: <path>` literal in the body." —
   Verification at this turn's read time:
   `rg -c '^END_FILE:' trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md`
   returns 1, and analogously for files 81, 82, 83. The trailer is
   the canonical harness BEGIN_FILE/END_FILE boundary marker; the
   planner output policy ("BEGIN_FILE / END_FILE blocks only")
   cannot avoid producing it. For Markdown spec files this trailer
   is harmless plain text. The committed Markdown directive `70_…`
   in the same tree carries the same trailer (one hit per file) and
   has been operating as a planner directive without issue.
2. (false self-claim, now corrected) "Re-emits this directive (06)
   with the date corrected to 2026-05-03 and the `END_FILE: <path>`
   literal removed from the body." — Same verification: directive 06
   itself still ends with the canonical harness trailer, and cannot
   be re-emitted without one as long as the harness format is
   unchanged. The date-correction half of the claim WAS achieved
   (header date is 2026-05-03).

The two narrow-scope changes that DID land in the prior 06 turn and
remain in force this turn:

3. Task 079 step 4 END_FILE leak self-check is narrowed to four
   explicit scopes: (a) the δ source tree
   `v2/backend/app/domain/trainer_liveness_composition/`, (b) the δ
   test tree `v2/backend/tests/unit/domain/trainer_liveness_composition/`,
   (c) the implementer-authored file
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/84_2E1C_DELTA_GO_NO_GO.md`,
   (d) the implementer-authored file
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/85_2E1C_DELTA_IMPLEMENTATION_REPORT.md`.
4. Task 080 rubric item 10 grep scope is aligned to the same four
   narrow scopes.

(3) and (4) are the canonical mitigation for the 2E1.B regression
class. They protect the four file sets where the leak materially
matters (Python source/test trees, where the trailer breaks
`py_compile`; and the implementer-authored Markdown status files,
where the implementer is instructed to author cleanly via the Edit
or Write tool, not via BEGIN_FILE/END_FILE materialization).

The leak class explicitly does NOT apply to files 80-83 or directive
06 itself: those four files are planner-emitted Markdown specs whose
sole "code-impacting" content is the second-to-last `PHASE2E1C_DELTA_*_READY`
or `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_RECORDED` marker
line. Predecessor-marker grep tests look for those marker strings
verbatim, not for "exactly the final line equals X", so the trailer
on the final line does not affect any predecessor check.

### Sub-phase ordering note (unchanged)

Phase 2E1.C.γ (read-only Redis adapter that supplies
`StreamIdObservation` tuples to δ) is deliberately deferred until
2E1.C.δ is Codex-passed. The pure-domain composition must land first
to keep the in-process safety boundary intact for as long as
possible. γ will open under its own spec turn after δ-Codex-PASS.

### Supervisor next action for Lane A (sanity check #2 corrected)

1. Wait for the 83 GO request marker
   `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED` to be present in
   `trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`.
   Verification command (read-only):
   `rg -n 'PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED' claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`
   MUST return at least one line.
2. **Corrected sanity check #2 (canonical harness trailer accepted)**:
   For each of files
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md`,
   `…/81_PHASE_2E1C_DELTA_TEST_PLAN.md`,
   `…/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md`,
   `…/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`,
   confirm:
   - `rg -c '^END_FILE:' <file>` returns EXACTLY `1`. A value of `0`
     means the trailer is missing (file truncated mid-emit) and is a
     real sanity failure. A value `>1` means an additional in-body
     leak beyond the canonical trailer (the 2E1.B-era body-bleed
     regression) and is a real sanity failure.
   - The single matching line is the file's final non-empty line and
     equals exactly `END_FILE: ` followed by the file's repo-relative
     path. Verification command:
     `tail -n 1 <file>` MUST equal `END_FILE: <repo-relative path>`.
   The supervisor MUST NOT flag the canonical single-trailing
   `END_FILE: <path>` line as a leak; it is the harness boundary
   marker and is byte-identical to the format used by older committed
   Markdown directives (e.g. `70_PLANNER_2E1C_ALPHA_VALIDATION_DISPATCH_DIRECTIVE.md`)
   in the same tree. Only deviations from the exactly-one-trailing
   pattern (count != 1, or the matching line is not the final
   non-empty line, or its text does not match the expected path) are
   sanity failures and MUST halt Lane A and escalate to a REQ_0014
   Codex human-attention recovery task scoped to the offending file
   only.
3. Dispatch `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
   as a single Max20-consolidated milestone task.
4. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`
   (in `trainer_gpu_parity_impl/84_2E1C_DELTA_GO_NO_GO.md`), commit
   the artifacts and dispatch
   `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`.
5. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_BLOCKED`, open a
   REQ_0007/REQ_0014 autofix task scoped strictly to
   `v2/backend/app/domain/trainer_liveness_composition/` and
   `v2/backend/tests/unit/domain/trainer_liveness_composition/`
   only. Do NOT permit autofix to touch α
   (`v2/backend/app/domain/trainer_liveness/`) or β
   (`v2/backend/app/domain/liveness_stream_growth/`) packages.
6. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`
   (in `trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`),
   the planner opens 2E1.C.γ in a fresh turn under a separate spec.

## Lane B — REQ_0008 frontend design (2F.A.0 inventory)

Lane B remains parked exactly as recorded in
`decision_explainability/05_PLANNER_THREE_LANE_STATUS_DIRECTIVE.md`.

Verified state delta since 05 (unchanged from prior 06 turn):

| Artifact | Verified value |
| --- | --- |
| Manual Claude Design output `06_CLAUDE_DESIGN_OUTPUT.md` | still `CLAUDE_DESIGN_OUTPUT_PENDING` (manual session not yet completed) |
| Slot conflict between manual handoff and automated 063 inventory | unresolved |
| Recent commit `7eefb89 Avoid frontend inventory live-trading safety false positive` | did NOT resolve the slot conflict; only suppressed a false-positive safety hit |

Planner directive for Lane B (this turn): unchanged. `063` remains
NOT dispatched; `067` and `068` remain blocked. The planner does NOT
advance Lane B this turn. Resolution still requires the human choice
between Path B1 (complete manual session) and Path B2 (archive
manual brief into `frontend_design/manual_handoff_archive/`).

## Lane C — REQ_0009 decision explainability (2H.A.0 inventory)

Verified state (read at planner turn time):

| Artifact | Path | Verified value |
| --- | --- | --- |
| Lane C task 069 | `agent_supervisor/tasks/069_decision_explainability_2ha0_lineage_inventory.json` | `pending` per task definition; supervisor `status/queue_status.json.current_running_task` = `069_decision_explainability_2ha0_lineage_inventory` with `stale_running_count = 1` |
| 069 predecessor marker | `decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md` | `PHASE2HA0_GO_NO_GO_REQUEST_RECORDED` (predecessor satisfied) |
| 069 required outputs | `decision_explainability/05_DECISION_LINEAGE_INVENTORY_REPORT.md`, `…/06_…GAP_MATRIX.md`, `…/07_…GO_NO_GO.md` | absent |
| Lane C Codex review task 070 | `agent_supervisor/tasks/070_decision_explainability_2ha0_codex_review.json` | `pending`, blocked on `PHASE2HA0_DECISION_LINEAGE_INVENTORY_PASSED` |

Diagnosis (unchanged): `069` was dispatched and entered a
stale-running state without producing the three required output
files. The supervisor's own staleness watchdog correctly classified
it as `stale_running`. The planner does NOT this turn rewrite the
069 prompt; the existing prompt is correct and the staleness is most
likely a Claude session interruption rather than a content blocker.

Planner directive for Lane C (this turn, unchanged):

- The supervisor SHOULD apply its standard stale-running recovery to
  `069_decision_explainability_2ha0_lineage_inventory` (refresh
  dispatch with the same prompt; no spec changes required).
- If the refreshed `069` again becomes stale without progress on the
  three required output files, escalate to a REQ_0014 Codex
  human-attention recovery task that diagnoses the partial-output
  state and may safely rewrite the inventory artifacts under the
  same `allowed_output_prefixes`. The Codex recovery MUST NOT
  modify any file under `v2/`.
- On `PHASE2HA0_DECISION_LINEAGE_INVENTORY_PASSED`, dispatch
  `070_decision_explainability_2ha0_codex_review` per the existing
  Lane C plan.

## Combined dispatch order (this planner turn)

The agent_supervisor SHOULD execute the two non-blocked lanes in
parallel where Codex Pro capacity allows; both are independent:

1. Lane A — `079` → `080` per this turn's outputs (after the
   corrected sanity check #2 above passes).
2. Lane C — refresh `069`; on PASS dispatch `070`.

Lane B remains blocked pending human reconciliation of the slot
conflict.

## Codex Pro parallel lane policy this turn (unchanged)

- Codex Pro MAY in parallel review the already-committed 2E1.C.β
  artifacts (final Codex pass landed; nothing else to autofix
  there) for residual hardening opportunities under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  status reports only — no v2/ source changes.
- Codex Pro MUST NOT pre-empt the 080 Codex review for 2E1.C.δ;
  that review's predecessor marker
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` does
  not yet exist.
- Codex Pro MUST NOT touch α or β packages, the master planner
  prompt, or any file outside the canonical Codex parallel scope
  (per the Codex Pro lane definition in
  `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`).

## Stop conditions (planner-binding)

The supervisor MUST halt either active lane and surface to the
planner if any of:

- any FAIL marker is written by `069`/`070`/`079`/`080`;
- any forbidden-token hit (the per-lane lists are defined in each
  lane's task spec);
- any `END_FILE: <path>` marker leak inside the δ source tree, the
  δ test tree, or the implementer-authored 84 / 85 status files —
  this is the canonical 2E1.B regression class (Python source/test
  files where the trailer breaks `py_compile`, and the
  implementer-authored markdown that the implementer is instructed
  to author cleanly via Write/Edit, NOT via BEGIN_FILE/END_FILE
  materialization);
- any planner-emitted Markdown spec or JSON task definition under
  the four files
  `trainer_gpu_parity_impl/{80,81,82,83}_*.md` containing MORE THAN
  ONE `^END_FILE:` line, or an `^END_FILE:` line that is not the
  file's final non-empty line, or whose final-line text does not
  match the file's repo-relative path (the body-bleed regression);
  the canonical exactly-one trailing `END_FILE: <path>` line is
  NOT a leak and MUST NOT be flagged;
- any write attempt outside the per-task `allowed_output_prefixes`;
- α or β cross-isolation regression fails inside Lane A (the δ
  implementation modifies any byte under
  `v2/backend/app/domain/trainer_liveness/` or
  `v2/backend/app/domain/liveness_stream_growth/`);
- any L4/L5 escalation, live/legacy/Redis/exchange/deploy/secrets
  attempt, or Codex hard fail with no safe remediation.

## Live-trading status

LIVE TRADING: BLOCKED. No artifact in this directive may change this.

PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_SANITY_CHECK_CORRECTION_RECORDED
END_FILE: claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md
