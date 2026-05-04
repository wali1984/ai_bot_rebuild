# Planner Dispatch Note — Phase 2E1.C.γ ready to fire after planner-level recovery

## Active requirements

- `REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE` — in flight at
  Phase 2E1.C.γ (trainer-liveness STREAM-ID OBSERVATION COLLECTOR
  domain layer). Predecessor sub-phases α / β / δ are all at Codex
  PASS.
- `REQ_0007_CODEX_AUTOFIX_NON_LIVE_BLOCKERS` — meta-policy; remains
  the autofix charter for any Codex FAIL on the γ lane.
- `REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM` — open at
  Phase 2F.A.1 (frontend design system spec) under tasks 067 / 068;
  parallel to γ, no path overlap.
- `REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI` —
  open at Phase 2H.A.0 (decision lineage inventory) under tasks
  069 / 070; parallel to γ, no path overlap.
- `REQ_0011_PARALLEL_CODEX_REVIEW_AND_AUTOFIX_LANE` — meta-policy;
  parallel Codex lane stays paused this turn (rationale below).
- `REQ_0014_CODEX_HUMAN_ATTENTION_AUTONOMOUS_RECOVERY` and
  `REQ_0015_PLANNER_LEVEL_HUMAN_ATTENTION_CODEX_AUTORECOVERY` —
  meta-policies; both already exercised on 084 (planner-level γ
  materialization recovery, see below) without operator intervention.

## State of the trainer parity service rebuild as of 2026-05-04

| Phase | Subject | Latest marker | File |
| --- | --- | --- | --- |
| 2E (plan) | Trainer GPU parity plan | `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS` | `trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md` |
| 2E1.A | Subprocess adapter foundation | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` |
| 2E1.B | Trainer output contract / domain records | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` |
| 2E1.B (validation) | Local pytest validation | `PHASE2E1B_LOCAL_VALIDATION_PASSED` | `trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md` |
| 2E1.C.α | Liveness DOMAIN LAYER | `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md` |
| 2E1.C.β | Stream-id GROWTH WINDOW domain layer | `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md` |
| 2E1.C.δ | Liveness COMPOSITION domain layer | `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md` |
| 2E1.C.γ (planner) | Observation-collector spec + tasks 082 / 083 | dispatch chain authored, awaiting supervisor execution | `trainer_gpu_parity_impl/88..91_*.md` + `agent_supervisor/tasks/082..083` |
| 2E1.C.γ (recovery) | Planner-level γ materialization blocker | `CODEX_GAMMA_MATERIALIZATION_RECOVERY_READY` | `trainer_gpu_parity_impl/84_CODEX_GAMMA_MATERIALIZATION_RECOVERY_GO_NO_GO.md` |

## 2E1.C.γ planner-side completeness (no new γ-artifacts this turn)

The 2E1.C.γ dispatch chain authored across commits `8916171`,
`997144c`, `98a9060`, `29192c3`, and `f2c505e` is in-tree and
committed. The planner-level `human_attention_required` raised when
the Claude harness refused to materialize
`89_PHASE_2E1C_GAMMA_TEST_PLAN.md` was resolved by the Codex recovery
task `084_codex_recover_planner_gamma_materialization_blocker.json`
under REQ_0014 / REQ_0015 authority; the recovery report and GO/NO-GO
are committed at `trainer_gpu_parity_impl/84_CODEX_GAMMA_MATERIALIZATION_RECOVERY_REPORT.md`
and `…/84_CODEX_GAMMA_MATERIALIZATION_RECOVERY_GO_NO_GO.md`
respectively. All four planning artifacts (88 spec, 89 test plan,
90 safety boundaries, 91 GO/NO-GO request) are present on disk and
referenced by `082_trainer_parity_2e1c_gamma_implementation.json` as
authoritative inputs. The planner has nothing further to emit for
2E1.C.γ; all subsequent action is supervisor execution:

1. Supervisor verifies the four predecessor markers required by
   `082_…json` are present (already true; see verification table
   below) and dispatches
   `tasks/082_trainer_parity_2e1c_gamma_implementation.json`.
2. Supervisor commits the impl artifacts and dispatches
   `tasks/083_trainer_parity_2e1c_gamma_codex_review.json` once
   `92_2E1C_GAMMA_GO_NO_GO.md` reads
   `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`.
3. On `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS` (file
   `95_2E1C_GAMMA_CODEX_GO_NO_GO.md`), the next planner turn opens
   2E1.C.γ.real (real-Redis-backed `StreamLatestIdReader`
   implementation under `v2/backend/app/adapters/redis_v2/`,
   non-live read-only) under a fresh spec turn.
4. On any FAIL marker the supervisor opens a remediation task under
   REQ_0007 autofix scope (with Codex authority per REQ_0014); the
   planner does NOT re-spec until remediation closes.

The planner explicitly does NOT re-author or amend the 2E1.C.γ
artifacts in this turn. Re-authoring would risk overwriting the
supervisor's predecessor markers and the just-recovered 89 test plan.

## Predecessor marker verification for `tasks/082_…json`

| Required marker | File | Observed value | Match? |
| --- | --- | --- | --- |
| `PHASE2E1C_GAMMA_GO_NO_GO_REQUEST_RECORDED` | `91_PHASE_2E1C_GAMMA_GO_NO_GO_REQUEST.md` | `PHASE2E1C_GAMMA_GO_NO_GO_REQUEST_RECORDED` | yes |
| `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS` | `87_2E1C_DELTA_CODEX_GO_NO_GO.md` | `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS` | yes |
| `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` | `69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md` | `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` | yes |
| `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` | `53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` | yes |

All four gates are satisfied. Supervisor may dispatch `082` on the
next reconciliation tick.

## Chosen next non-live milestone

**Phase 2E1.C.γ — trainer-liveness STREAM-ID OBSERVATION COLLECTOR
domain layer (consolidated Max20 milestone).**

Implementation, forbidden-token self-grep, END_FILE leak self-check,
`py_compile`, `pytest`, α/β/δ cross-isolation regression, and
status-report authoring are bundled in the single task `082`. This
matches the `consolidated_default` task granularity mode declared in
`master_rebuild_planner_status.json` and the planner profile rule
that trainer parity sub-milestones (liveness, prediction worker
health, GPU/checkpoint runner, confidence attribution) be authored as
single tasks unless an emit/path/size/timeout failure forces a split.

Codex review of the resulting artifacts is bundled in `083` per the
required `Claude builds → Codex reviews` cadence.

Rationale for choosing γ as the next dispatched milestone instead of
opening γ.real or a new lane:

- All α / β / δ Codex gates are PASS; γ is the fourth and final
  pure-domain liveness sub-phase before the γ.real adapter that will
  bridge to read-only Redis. Completing γ first keeps the adapter
  ungated by domain rework.
- The γ implementation task has been fully authored and the
  planner-level materialization blocker that blocked it has been
  closed by Codex recovery. No further planner work is required to
  unblock dispatch.
- The competing parallel-lane candidates (REQ_0008 task 067 frontend
  design spec, REQ_0009 task 069 decision-explainability lineage
  inventory) are documentation-only and remain queued; they do not
  share any path with the γ Python tree, so the supervisor can fire
  them at any time without conflict (path-overlap audit below).

## Path-overlap audit (parallelism safety)

| Lane | Writes under | Reads under |
| --- | --- | --- |
| 2E1.C.γ (tasks 082 / 083) | `v2/backend/app/domain/trainer_liveness_observation_collector/`, `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`, `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` (only files 92 / 93 / 94 / 95) | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/88..91_*.md`, `v2/backend/app/domain/liveness_stream_growth/` (read-only β contract), `v2/backend/app/domain/trainer_liveness/` (read-only α contract), `v2/backend/app/domain/trainer_liveness_composition/` (read-only δ contract) |
| 2F.A.1 (tasks 067 / 068) | `claude_worklog/phase2_core_rebuild/frontend_design/` | `claude_worklog/requirements_inbox/REQ_0008_*`, `v2/frontend/` (read-only) |
| 2H.A.0 (tasks 069 / 070) | `claude_worklog/phase2_core_rebuild/decision_explainability/` | `claude_worklog/requirements_inbox/REQ_0009_*`, existing α / β / δ / γ contracts (read-only) |

No write-write conflicts. No read-of-each-other's-writes. Any of the
three lanes may complete first without affecting the others'
predecessor markers.

## Parallel Codex lane status this turn

The parallel Codex lane is `git_clean_and_no_active_dirty_claude_output`
gated. Current `git status -s` is:

```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
```

The dirty path is the master planner prompt itself, which sits in
`claude_worklog/autonomous_control_plane/` — NOT inside the Codex
parallel lane scope (`v2/`,
`claude_worklog/phase2_core_rebuild/`,
`claude_worklog/v2_scaffold_reviews/`,
`claude_worklog/security/`,
`claude_worklog/agent_supervisor/tasks/`,
`claude_worklog/tools/` for safety/status/review tooling only). It
therefore cannot collide with any Codex parallel write. However the
strict policy phrase `git_clean_and_no_active_dirty_claude_output`
treats any dirty repo as a pause condition. Decision: the parallel
Codex lane stays **paused** this turn. The operator's next
reconciliation tick should commit the planner-prompt diff (it is the
operator's own edit, not Claude's output, so committing it is safe and
not subject to the Codex re-review gate); the parallel lane will
auto-resume on the next tick once the working tree is clean.

The pending parallel Codex review tasks `069_codex_parallel_review_trainer_liveness_stack`
and `073_codex_parallel_rereview_trainer_liveness_autofix` remain
queued at `pending`. They become eligible immediately after the
planner-prompt diff is committed and `082` has not yet started; if
`082` has already fired, they wait for `082` to finish per the
parallel-lane mid-flight conflict rule.

## Hard exclusions for the γ lane (and all lanes this turn)

- No live trading enable.
- No Redis client construction in the γ source or test trees (γ is
  pure-domain; the Redis-backed reader belongs to γ.real, not γ).
- No exchange API call.
- No legacy module import.
- No subprocess against the legacy trainer venv (the γ task allows
  only `pytest`, `python -m py_compile`, `python -c`, `git status -s`,
  and `grep` / `rg`).
- No production secret read.
- No deployment script invocation.
- No production migration.
- No write under `/home/wali/Desktop/AI BOT/`.
- No write under `legacy_reference/`.
- No modification of the master planner prompt by Claude or Codex
  inside the γ lane (operator-only domain).
- No modification of α / β / δ source or test trees from inside `082`
  (cross-isolation regression must show zero git-status churn under
  those three trees per Step 7 of the `082` prompt).

## Dispatch chain summary (this turn's net additions)

- This planner turn emits **only** this dispatch note. No new task
  JSON is created. No new spec/test/safety/GO-NO-GO markdown is
  created. The two queued tasks `082` and `083` carry forward
  unchanged.
- `tasks/082_trainer_parity_2e1c_gamma_implementation.json` is ready
  to fire.
- `tasks/083_trainer_parity_2e1c_gamma_codex_review.json` is gated on
  the success marker `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`
  in `92_2E1C_GAMMA_GO_NO_GO.md`.
- `tasks/084_codex_recover_planner_gamma_materialization_blocker.json`
  has produced
  `CODEX_GAMMA_MATERIALIZATION_RECOVERY_READY`; supervisor should
  reconcile its status from `pending` to `completed` on the next tick
  using the GO/NO-GO file as evidence (no further planner action
  required).
- The parallel Codex lane stays paused until the planner-prompt diff
  is committed by the operator.

PLANNER_PHASE_2E1C_GAMMA_DISPATCH_NOTE_RECORDED
END_FILE: claude_worklog/autonomous_control_plane/PLANNER_PHASE_2E1C_GAMMA_DISPATCH_NOTE.md
