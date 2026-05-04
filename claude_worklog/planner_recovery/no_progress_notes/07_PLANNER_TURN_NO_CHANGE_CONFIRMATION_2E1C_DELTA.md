# Planner Directive — Turn-Stamp Dispatch Authorization for 2E1.C.δ (2026-05-03)

This is a Master Non-Live Rebuild Planner turn-stamp. It confirms
that the prior directive
`claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`
remains the canonical non-live rebuild three-lane status, verifies
that all δ predecessor artifacts have been authored cleanly with
the canonical harness `END_FILE: <path>` trailer pattern, and
authorizes the agent_supervisor to proceed with the dispatch
sequence already ordered in directive 06. No new task definitions,
spec files, V2 source files, or status markers are introduced this
turn. No legacy under `/home/wali/Desktop/AI BOT/` is touched. No
Redis write or delete is performed. No live trading is enabled.

This directive does NOT supersede directive 06; it stamps a planner
turn boundary so the supervisor can attribute its commit-and-dispatch
action to a verified planner authorization marker rather than to an
inferred state read.

## Source of authority

- Active requirement set (unchanged):
  - `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`
  - `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`
  - `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
- Planner profile: Claude Code Max20 `consolidated_default`. Codex
  Pro parallel review/autofix lane is enabled, gated on
  `git_clean_and_no_active_dirty_claude_output`.
- Harness emit-trailer fact (re-confirmed at this turn's read time):
  the BEGIN_FILE / END_FILE materializer writes the literal
  `END_FILE: <repo-relative path>` line as the final non-empty line
  of every materialized file. Older committed JSON task definitions
  are stripped of the trailer at commit time by the supervisor
  commit hook; older committed Markdown spec files retain the
  trailer as plain text.

## Verified state at this turn's read time

| Artifact | Verified value |
| --- | --- |
| `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` |
| `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` |
| `trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` |
| `trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md` | `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` |
| `trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_COMPOSITION_SPEC_READY`; final non-empty line is the canonical harness `END_FILE` trailer (1 hit, byte-identical to file path) |
| `trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_TEST_PLAN_READY`; canonical trailer present (1 hit) |
| `trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_SAFETY_BOUNDARIES_READY`; canonical trailer present (1 hit) |
| `trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED`; canonical trailer present (1 hit) |
| `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json` | `pending`; step-4 grep scope narrowed to four δ-only scopes per directive 06 §3 |
| `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json` | `pending`; rubric item 10 grep scope narrowed accordingly per directive 06 §4 |
| `decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md` | final non-empty token before the canonical trailer is `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_SANITY_CHECK_CORRECTION_RECORDED` |
| `git status -s` | seven `??` (untracked) δ artifacts listed below; one `M` on `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (external process; planner does NOT touch it this turn) |

The seven untracked δ artifacts are:
- `claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
- `claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`

This turn's directive (07) will become an eighth untracked artifact
that the supervisor SHOULD include in the same δ-dispatch commit.

## Lane A authorization (REQ_0006 trainer parity, sub-phase 2E1.C.δ)

The agent_supervisor is authorized to perform the following sequence,
in order, without further planner intervention until a stop condition
fires:

1. Stage and commit, in a single non-live milestone commit, exactly
   the eight untracked δ artifacts (the seven listed above plus this
   directive). Commit message format SHOULD follow the recent Lane A
   style (`Add Phase 2E1.C.δ trainer parity composition specs and
   tasks`) with the standard `Co-Authored-By` trailer. The commit
   MUST NOT include the `M`-modified
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`;
   that file is owned by a separate concurrent process and is out of
   scope for this turn. The commit MUST be created via the standard
   supervisor commit hook so JSON task files have their canonical
   harness `END_FILE` trailer stripped at commit time (matching the
   `060`/`064`/`078` precedent); Markdown spec files retain the
   canonical trailer as plain text (matching the `70_…` precedent).

2. After the commit, run the corrected sanity check #2 from
   directive 06 against files 80-83 (read-only verification):
   - `rg -c '^END_FILE:' <each file>` returns exactly `1`;
   - `tail -n 1 <each file>` equals `END_FILE: ` followed by the
     file's repo-relative path.
   On any deviation (count `!= 1`, `^END_FILE:` line that is not the
   final non-empty line, or final-line text that does not match the
   file's repo-relative path), HALT Lane A and open a REQ_0014 Codex
   human-attention recovery task scoped to the offending file only.

3. Verify the predecessor markers required by task 079 are present
   (read-only):
   - `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED` in `83_…`,
   - `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` in `69_…`,
   - `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` in `53_…`.
   All three MUST return at least one match line under `rg -n`.

4. Dispatch
   `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
   as a single Max20-consolidated milestone task. Do NOT split it
   unless it fails for an emit/path/size/timeout reason; the task
   prompt is explicit that implementation, forbidden-token grep,
   cross-isolation regression, and status-report authoring all run
   in this single task.

5. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`
   in `trainer_gpu_parity_impl/84_2E1C_DELTA_GO_NO_GO.md`, commit
   the `84/85` artifacts and dispatch
   `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`.

6. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_BLOCKED`, open a
   REQ_0007 / REQ_0014 autofix task scoped strictly to
   `v2/backend/app/domain/trainer_liveness_composition/` and
   `v2/backend/tests/unit/domain/trainer_liveness_composition/`.
   Autofix MUST NOT touch α
   (`v2/backend/app/domain/trainer_liveness/`) or β
   (`v2/backend/app/domain/liveness_stream_growth/`) packages, the
   master planner prompt, or any file outside the canonical Codex
   parallel scope.

7. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS` in
   `trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`, surface
   to the planner so a fresh turn can open 2E1.C.γ (read-only Redis
   observation collector) under a separate spec. The planner does
   not pre-author γ this turn.

## Lane B authorization (REQ_0008 frontend) — unchanged

Lane B remains parked exactly as recorded in
`decision_explainability/05_PLANNER_THREE_LANE_STATUS_DIRECTIVE.md`
and re-confirmed in directive 06. The slot conflict between the
manual Claude Design handoff (`06_CLAUDE_DESIGN_OUTPUT.md` still
`CLAUDE_DESIGN_OUTPUT_PENDING`) and the automated `063` inventory
remains unresolved. Tasks `063`, `067`, `068` remain blocked. The
planner does NOT advance Lane B this turn. Resolution still requires
the human choice between Path B1 (complete the manual session) and
Path B2 (archive the manual brief into
`frontend_design/manual_handoff_archive/`).

## Lane C authorization (REQ_0009 decision explainability) — unchanged

Task `069_decision_explainability_2ha0_lineage_inventory` remains
`pending`; predecessor marker `PHASE2HA0_GO_NO_GO_REQUEST_RECORDED`
is present in `decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`;
the three required outputs (`05_DECISION_LINEAGE_INVENTORY_REPORT.md`,
`06_…GAP_MATRIX.md`, `07_…GO_NO_GO.md`) are absent. Supervisor SHOULD
apply its standard stale-running recovery to `069` (refresh dispatch
with the same prompt; no spec changes). If `069` becomes stale a
second time without progress on the three required output files,
escalate to a REQ_0014 Codex human-attention recovery task scoped
strictly to `decision_explainability/` outputs (Codex MUST NOT modify
any file under `v2/` for Lane C). On
`PHASE2HA0_DECISION_LINEAGE_INVENTORY_PASSED`, dispatch
`070_decision_explainability_2ha0_codex_review` per directive 06.

## Combined dispatch order this turn

The supervisor SHOULD execute the two non-blocked lanes in parallel
where Codex Pro capacity allows; both are independent:

1. Lane A — commit-and-sanity-check, then `079` → `080` per the
   sequence above.
2. Lane C — refresh stale `069`; on PASS dispatch `070`.

Lane B remains blocked pending human reconciliation of the slot
conflict.

## Codex Pro parallel lane policy this turn — unchanged

- Codex Pro MAY in parallel review the already-committed 2E1.C.β
  artifacts (final Codex pass landed; nothing else to autofix
  there) for residual hardening opportunities under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  status reports only — no `v2/` source changes.
- Codex Pro MUST NOT pre-empt the `080` Codex review for 2E1.C.δ;
  predecessor marker
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` does
  not yet exist.
- Codex Pro MUST NOT touch α or β packages, the master planner
  prompt under `claude_worklog/autonomous_control_plane/`, or any
  file outside the canonical Codex parallel scope.
- Codex Pro parallel review MAY proceed only when
  `git status -s` is clean of dirty Claude output AND no Claude
  child or supervisor task is actively writing inside the Codex
  parallel scope. The supervisor enforces this gate.

## Stop conditions (planner-binding) — unchanged from directive 06

The supervisor MUST halt the active lane and surface to the planner
on any of:

- a FAIL marker written by `069`/`070`/`079`/`080`;
- any forbidden-token hit per the per-lane lists in each task spec;
- any `END_FILE: <path>` marker leak inside the δ source tree
  (`v2/backend/app/domain/trainer_liveness_composition/`), the δ
  test tree
  (`v2/backend/tests/unit/domain/trainer_liveness_composition/`),
  or the implementer-authored `84` / `85` status files (the canonical
  2E1.B regression class — Python source/test files where the
  trailer breaks `py_compile`, and the implementer-authored markdown
  the implementer is instructed to author cleanly via the Edit or
  Write tool, NOT via BEGIN_FILE/END_FILE materialization);
- any planner-emitted Markdown spec under
  `trainer_gpu_parity_impl/{80,81,82,83}_*.md` containing more than
  one `^END_FILE:` line, or an `^END_FILE:` line that is not the
  file's final non-empty line, or whose final-line text does not
  match the file's repo-relative path (the body-bleed regression);
  the canonical exactly-one trailing `END_FILE: <path>` line is NOT
  a leak and MUST NOT be flagged;
- any write attempt outside the per-task `allowed_output_prefixes`;
- α or β cross-isolation regression inside Lane A (the δ
  implementation modifies any byte under
  `v2/backend/app/domain/trainer_liveness/` or
  `v2/backend/app/domain/liveness_stream_growth/`);
- any L4/L5 escalation, live/legacy/Redis/exchange/deploy/secrets
  attempt, or Codex hard fail with no safe remediation.

## Live-trading status

LIVE TRADING: BLOCKED. No artifact in this directive may change
this. The δ composition layer is pure-Python, sync, no-async,
no-Redis, no-subprocess, no-network, no-clock, no-legacy by
construction; γ (read-only Redis observation collector) is
deliberately deferred until δ is Codex-passed so the in-process
safety boundary remains intact for as long as possible.

PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_DISPATCH_AUTHORIZED
