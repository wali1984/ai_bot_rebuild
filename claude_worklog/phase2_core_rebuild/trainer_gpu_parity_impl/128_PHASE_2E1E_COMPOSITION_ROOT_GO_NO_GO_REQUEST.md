# Phase 2E1.E — Trainer Parity Composition Root GO/NO-GO Request

The planner authored 125 (spec), 126 (test plan), and 127 (safety
boundaries) for Phase 2E1.E and is requesting GO authorization to
dispatch supervisor task 096
(`096_trainer_parity_2e1e_composition_root_implementation`).

## Predecessor evidence

- 124_2E1D_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md contains exactly
  `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS`
  (verified at planner turn 2026-05-04). This is the authoritative
  2E1.D Codex pass marker.

## Scope summary

- New top-level package `v2/backend/app/composition/trainer_parity/`.
- Three authored source files: `__init__.py`, `errors.py`,
  `runtime.py`.
- 25 new unit tests under
  `v2/backend/tests/unit/composition/trainer_parity/`.
- Public surface: `build_trainer_liveness_evaluator`,
  `TrainerLivenessEvaluator`, `TrainerParityCompositionError`.
- The first trainer-parity milestone allowed to import the γ.real
  factory at module load time. Importing the package transitively
  loads `redis` into `sys.modules`; this is asserted by
  `test_runtime_module_loads_redis_when_imported.py` and is the
  inverse of the 2E1.D service's redis-clean invariant.

## Hard stops not triggered

- No legacy mutation. `/home/wali/Desktop/AI BOT` is untouched.
- No Redis write or delete.
- No live trainer / trader / orchestrator / Redis / VPN restart.
- No exchange action.
- No leverage or margin change.
- No live trading enabled.
- No deploy intent.
- No production migration.
- No secret exposure.
- No L4 / L5 behavior.

## Dispatch sequence directive

1. Supervisor commits this turn's working-tree artifacts (the four
   spec markdown files, the two task JSON files, and the two
   planner-turn artifacts under
   `claude_worklog/autonomous_control_plane/`) plus the prior
   already-modified `claude_master_rebuild_planner_prompt.txt`.

2. Supervisor dispatches
   `096_trainer_parity_2e1e_composition_root_implementation`. 096
   emits the three source files plus the 25 test files plus 129
   (implementation report) and 130 (impl GO/NO-GO marker).

3. On 096 PASS marker
   `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`,
   supervisor dispatches
   `097_trainer_parity_2e1e_composition_root_codex_review`. 097
   emits 131 (Codex review report) and 132 (Codex GO/NO-GO marker).

4. On 097 PASS marker
   `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`, the
   trainer-liveness assembly stack is fully wired end-to-end and the
   planner closes Phase 2E1 (REQ_0006). The next planner turn opens
   the next sub-phase under REQ_0006 (trainer prediction worker
   health metrics or trainer GPU/checkpoint runner) per the
   consolidated milestone plan.

## REQ_0007 / REQ_0014 fallback

- 096 FAIL with concrete blockers and zero safety violation:
  supervisor dispatches a narrow REQ_0007 / REQ_0014 autofix task
  scoped to the three authored source files plus the 25 new test
  files only.
- 097 FAIL with concrete blockers and zero safety violation:
  same scope as the 096 fallback.
- Any safety violation in 096 or 097: surface to human attention; no
  autofix permitted.

PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
