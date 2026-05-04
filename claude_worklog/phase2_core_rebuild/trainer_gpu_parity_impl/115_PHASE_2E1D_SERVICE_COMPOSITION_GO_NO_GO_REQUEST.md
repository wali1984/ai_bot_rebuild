# Phase 2E1.D — Trainer Parity Service Composition GO / NO-GO Request

## Predecessor markers (must all be present)

- `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`.
- `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`.
- `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`.
- `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`.
- `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md`.
- `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`.
- `PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md`.
- `PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS` in
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/111_2E1C_GAMMA_REAL_FACTORY_CODEX_GO_NO_GO.md`.

The supervisor confirms each marker before dispatching 091. Any
missing or mismatched marker blocks dispatch.

## Implementation task

`claude_worklog/agent_supervisor/tasks/091_trainer_parity_2e1d_service_composition_implementation.json`
emits the following files under
`v2/backend/app/services/trainer_parity/`:

- `__init__.py`
- `errors.py`
- `evaluation.py`
- `liveness_service.py`

Plus the 32 test files under
`v2/backend/tests/unit/services/trainer_parity/`, the
`__init__.py` package markers under
`v2/backend/tests/unit/services/` and
`v2/backend/tests/unit/services/trainer_parity/`, the implementation
report at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/116_2E1D_SERVICE_COMPOSITION_IMPLEMENTATION_REPORT.md`,
and the GO / NO-GO marker file at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/117_2E1D_SERVICE_COMPOSITION_GO_NO_GO.md`.

The 091 task runs all validation commands listed in 113 §
"Validation commands" before emitting the GO / NO-GO marker. Failure
of any command emits the FAIL marker; success emits
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`.

## Codex review task

`claude_worklog/agent_supervisor/tasks/092_trainer_parity_2e1d_service_composition_codex_review.json`
runs only after 091 emits
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`.
Codex emits the review at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/118_2E1D_SERVICE_COMPOSITION_CODEX_REVIEW.md`
and the verdict at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/119_2E1D_SERVICE_COMPOSITION_CODEX_GO_NO_GO.md`.

On Codex PASS, the marker is
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS`.

On Codex FAIL with concrete blockers and no safety violation, the
supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the
four service source files plus the 32 new test files only; no autofix
may touch any prior-milestone file.

On Codex FAIL with any safety violation per 114 § "Stop conditions",
the milestone surfaces to human attention; no autofix is permitted.

## What this milestone unblocks

On 092 PASS:

- The trainer-liveness assembly stack (α / β / γ / δ / γ.real / factory /
  service) is complete in process.
- 2E1.E (composition root: a small startup-time helper that calls the
  factory, builds default `GrowthWindowConfig` and stream names from
  versioned config, and exposes a single `build_trainer_liveness_evaluator`
  function) becomes the next milestone under
  `v2/backend/app/services/trainer_parity/composition_root.py`. 2E1.E
  is the first milestone allowed to import the factory.
- After 2E1.E, the trainer-parity service is callable from a small
  FastAPI read-only endpoint planned for 2E1.F (no live trading;
  paper / shadow only) and from a CLI smoke command planned for 2E1.G.

The planner does NOT open 2E1.E in this turn. Opening 2E1.E requires
092 PASS.
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/115_PHASE_2E1D_SERVICE_COMPOSITION_GO_NO_GO_REQUEST.md
