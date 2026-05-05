# Phase 2E3.A Codex FAIL Diagnosis and Re-Review Plan

Active requirement: REQ_0006 ∩ REQ_0017 (TRAINER_PREDICTION_OUTPUT_MVP).
Active lane (REQ_0018): codex_watchdog (clearing dispatch-tree noise that
blocks the paper_backtest_mvp lane).
Date: 2026-05-05.

## What happened

Task `110_trainer_parity_2e3a_prediction_output_domain_implementation`
authored the new domain package and the 31-test suite and produced
`PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_IMPL_AND_VALIDATION_PASSED`
in `184_2E3A_PREDICTION_OUTPUT_DOMAIN_GO_NO_GO.md`.

Task `111_trainer_parity_2e3a_prediction_output_domain_codex_review`
ran the adversarial review and produced
`PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_FAIL` in
`186_2E3A_PREDICTION_OUTPUT_DOMAIN_CODEX_GO_NO_GO.md`.

## FAIL classification

Reading `185_2E3A_PREDICTION_OUTPUT_DOMAIN_CODEX_REVIEW.md`:

| Rubric items | Result | Notes |
| --- | --- | --- |
| 1-22 | PASS | Source files match spec, all 31 new tests pass, all six prior trainer suites pass, py_compile clean, every spec-179 forbidden token has zero matches. |
| 23 | FAIL | `git status -s claude_worklog/autonomous_control_plane/` returned `M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`, and `181_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SAFETY_BOUNDARIES.md:51-82` lists `claude_worklog/autonomous_control_plane/` as forbidden in the cross-isolation check. |
| 24-27 | PASS | No FastAPI lifespan, no module-level singleton, no secret leakage, no `trainer_worker_health/trainer_liveness/trainer_parity` import in authored sources. |

The single FAIL is dispatch-tree noise. The dirty file is the master
planner prompt itself, which the harness regenerates every planner turn
with the latest requirements_inbox content. The dirty diff is purely
the requirements_inbox sync that REQ_0014 / REQ_0015 / REQ_0016 expect
the watchdog to commit.

## Safety classification

| Concern | Result |
| --- | --- |
| live behavior in 2E3.A diff | none observed |
| Redis access at construction or import | none observed |
| Redis command at construction | none observed |
| legacy mutation | none observed |
| release intent | none observed |
| modification of any prior-milestone source or test file | none observed |
| FastAPI startup hook / lifespan in authored files | none observed |
| module-level singleton, cache, or lock | none observed |
| wall-clock helper call in authored sources | none observed |
| direct `redis` / `url_env` / `gamma.real factory` import | none observed |
| URL logging | none observed |
| secret-shaped strings | none observed |
| REQ_0017 scope cap (no checkpoint/GPU/model-loading/service/composition/adapter expansion) | none observed |
| `trainer_worker_health` / `trainer_liveness` / `trainer_parity` import in authored sources | none observed |

No safety stop condition is satisfied. The FAIL is recoverable without
any source/test edit and without modifying the master planner prompt
itself.

## Prior planner-output-policy violation in this lane

The first emission of this diagnosis and of task `112` leaked
`END_FILE: <path>` envelope marker lines into the file bodies (and, in
the case of `112`, also leaked a "Planner turn summary:" prose
paragraph after the JSON closing brace, making the task definition
invalid JSON the supervisor could not dispatch). This is the
explicitly enumerated in REQ_0014 §"recover safe path mismatches",
REQ_0015 §"END_FILE marker leakage", and REQ_0016 §"validate generated
task JSON/docs" / "remove standalone END_FILE leakage".

The current planner turn re-emits both planner artifacts cleanly. The
file bodies end at their last semantic content line; no standalone
`END_FILE:` marker line appears in either body; the task-`112` JSON
parses with `python -m json.tool` and contains no trailing prose. The
re-review precondition section in `112` fails fast if either condition
regresses, so the recovery class is now self-detecting.

## Prescribed remediation (REQ_0014 / REQ_0015 / REQ_0016)

1. The Codex watchdog cycle commits the standing dirty
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
   with a "Codex watchdog recover dirty non-live automation artifacts"
   message. This is the same pattern already applied in commits
   `b2afb6d`, `07d62b8`, `bf7c1bd`, `17644bf`, `90767bb`, `4ab82dc`,
   `0f678d4`, `7991af6`, `d9536a6`, `c72d741`, `7ddb990`, and `7977f3c`
   and is explicitly authorised by REQ_0016 §"fix dirty-tree dispatch
   holds" and REQ_0014 §"recover safe path mismatches".
2. The watchdog also commits the clean re-emission of this planner
   diagnosis (file `187`) and of the new re-review task definition
   (`claude_worklog/agent_supervisor/tasks/112_trainer_parity_2e3a_codex_rereview_after_dirty_tree_clean.json`)
   so the worktree is clean before re-dispatch.
3. The supervisor dispatches
   `112_trainer_parity_2e3a_codex_rereview_after_dirty_tree_clean.json`,
   which re-runs the same Rubric 1-27 against the unchanged 2E3.A
   authored artifacts and emits fresh
   `188_2E3A_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN.md` and
   `189_2E3A_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_GO_NO_GO.md`. No
   v2/ source or test file is touched.

## Why no autofix task is opened

REQ_0007 / REQ_0014 autofix scope is "patch the three authored source
files and the 31 new test files only". The 2E3.A authored source/test
files are already PASS on every rubric that targets them. There is
nothing for an autofix to patch. Opening an autofix task would violate
the REQ_0017 scope cap (no sideways expansion not required by the MVP)
and would risk perturbing artifacts that already pass the spec.

The dirty file lives outside the 2E3.A authored set and outside any
allowed autofix path. A watchdog commit, not a Codex autofix, is the
correct mechanism.

## Why a re-review task is required (rather than just superseding 186)

Task `111` produced a real Codex FAIL artifact at `186`. The supervisor
honours that artifact. The cleanest evidence-first path is to leave
`185`/`186` intact as the historical record of the dispatch-tree FAIL,
emit fresh `188`/`189` after the worktree is clean, and gate the next
sub-phase (2E3.B) on the new
`PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_PASS`
marker rather than the failed `186`. This avoids the "stale status
overrides PASS evidence" anti-pattern that REQ_0015 §"evidence-first
reconciliation" warns against.

## Hard stops still respected

- No write under `/home/wali/Desktop/AI BOT`.
- No Redis read or write.
- No restart of any live service.
- No exchange action.
- No leverage or margin change.
- No live trading enable.
- No deployment.
- No production migration.
- No secret exposure or commit.

## Lane and MVP relevance

- Lane: codex_watchdog (clearing dispatch-tree noise that blocks the
  paper_backtest_mvp lane).
- MVP relevance: unblocks 2E3.A → 2E3.B → 2E3.C closure of
  `TRAINER_PREDICTION_OUTPUT_MVP`, which is REQ_0017 milestone 1 on
  the path to `V2_BACKTEST_AND_PAPER_MVP_READY`.
- Next gate after re-review:
  `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_PASS`.
- Sub-phase advance gate (per `178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md`):
  the planner opens 2E3.B (trainer prediction record assembler service)
  only after the new re-review PASS marker materialises.

PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_FAIL_DIAGNOSIS_AND_REREVIEW_PLAN_READY
```
