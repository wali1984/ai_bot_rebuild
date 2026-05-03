# Planner directive: refresh tasks 061 and 062 after Codex parallel autofix

## Context

Active requirement: REQ_0006 (V2 trainer GPU parity service).
Active sub-milestone: Phase 2E1.C.alpha (trainer liveness domain layer).

The Codex parallel review/autofix/re-review lane authorized under REQ_0011 ran
out-of-band against the committed trainer liveness stack and produced the
following committed deliverables:

- `5f085c3` Add parallel Codex review for trainer liveness stack
- `d4bc276` Autofix trainer liveness worker-dead detection
- `c804896` Add Codex re-review for trainer liveness autofix

Re-review outcome at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/74_CODEX_PARALLEL_REREVIEW_TRAINER_LIVENESS_AUTOFIX_GO_NO_GO.md`:

```
CODEX_PARALLEL_TRAINER_LIVENESS_AUTOFIX_PASS
```

The autofix introduced two material changes to the post-implementation domain:

1. A new public reason constant `LIVENESS_REASON_PREDICTION_WORKER_DEAD`,
   exported via `__all__` (now 11 names instead of 10).
2. A new dedicated test
   `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_prediction_worker_dead.py`
   (test count for the trainer_liveness suite is now 12 files / >=24 tests).
3. A new evaluator branch making `prediction_worker_dead` independent of the
   zero-stream-growth branch (evaluator now has six rules in deterministic
   order instead of five).

## Why tasks 061 and 062 needed refresh

Both 061 (Claude formal local validation) and 062 (Codex formal milestone
review) were authored at task definition revision 1 against the pre-autofix
spec. Their assertions pinned:

- exactly 17 files in the trainer_liveness source + test trees,
- exactly 10 names in `__all__`,
- a five-rule evaluator with worker-dead absent or merged into zero-growth.

The post-autofix domain at HEAD has 18 files, 11 names, and six rules. If 061
and 062 had been dispatched at revision 1, they would have failed their own
checks against correct code. This is a definitional-staleness fault, not a
code fault.

## What this directive changes

Task definition revision 2 of 061 (Claude validator):

- File presence list now enumerates all 18 files (6 source + 12 test).
- Public-surface check now requires the 11-name `__all__`.
- Pytest assertion now requires test count >= 24 (autofix adds 1 file with
  at least 1 test).
- Adds an explicit Step 8 evaluator-rule-order spot-check listing the six
  rules in deterministic order, including the worker-dead-independent-of-
  zero-growth gating.
- Adds explicit references to the autofix and re-review artifacts.

Task definition revision 2 of 062 (Codex formal reviewer):

- Rubric #1 now expects 11 `__all__` names.
- Rubric #4 now expects six allowed reasons.
- Rubric #5 now spells out the six-rule evaluator with the worker-dead
  branch independent of the zero-growth branch, citing the post-autofix
  evaluator.py:48-57.
- Rubric #8 now requires py_compile to pass for 18 Python files.
- Rubric #9 now requires presence of `test_evaluator_prediction_worker_dead.py`
  with the autofix-introduced non-zero-growth-still-fires case.
- Adds a new "Autofix continuity check" section in the emitted review.
- Adds explicit references to the autofix report (71), re-review (73), and
  re-review GO/NO-GO (74).

## What this directive does NOT change

- Predecessor markers and predecessor task IDs are unchanged.
- Sequencing constraint is unchanged: task 062 must NOT dispatch before task
  061 records `PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED` at
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/48_2E1C_ALPHA_VALIDATION_GO_NO_GO.md`.
- Risk level (L1), agent assignments (claude / codex), allowed output
  prefixes, and required output files are unchanged.
- The Codex parallel re-review PASS does NOT substitute for the formal
  milestone Codex review. The formal review is still required and must
  independently re-verify post-autofix invariants.

## Safety reaffirmation

- LIVE TRADING: BLOCKED.
- No write to `/home/wali/Desktop/AI BOT`.
- No Redis write or delete.
- No legacy mutation.
- No exchange action.
- No leverage / margin change.
- No deployment.
- No secret exposure.
- No legacy trainer process restart.

## Next planner trigger

After 061 records `PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED`, dispatch task 062.
After 062 records `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`, the next
planner cycle will spec Phase 2E1.C.beta (read-only Redis stream-id growth
probe) as the next consolidated trainer-parity sub-milestone.

PLANNER_2E1C_ALPHA_TASK_DEFINITION_REFRESH_RECORDED