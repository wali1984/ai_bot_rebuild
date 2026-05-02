# Phase 2E1.C.α — GO / NO-GO Request

## Predecessor markers required

| Marker | File | Required value |
| --- | --- | --- |
| Trainer GPU parity plan | `trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md` | `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS` |
| Liveness fix spec | `trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md` | `PHASE2_TRAINER_GPU_PARITY_PREDICTION_WORKER_LIVENESS_READY` |
| 2E1.A subprocess adapter | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` |
| 2E1.B trainer output contract | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` |
| 2E1.B local validation | `trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md` | `PHASE2E1B_LOCAL_VALIDATION_PASSED` |
| 2E1.C.α domain spec | `trainer_gpu_parity_impl/42_PHASE_2E1C_ALPHA_LIVENESS_DOMAIN_SPEC.md` | `PHASE2E1C_ALPHA_TRAINER_LIVENESS_DOMAIN_SPEC_READY` |
| 2E1.C.α test plan | `trainer_gpu_parity_impl/43_PHASE_2E1C_ALPHA_TEST_PLAN.md` | `PHASE2E1C_ALPHA_TRAINER_LIVENESS_TEST_PLAN_READY` |
| 2E1.C.α safety boundaries | `trainer_gpu_parity_impl/44_PHASE_2E1C_ALPHA_SAFETY_BOUNDARIES.md` | `PHASE2E1C_ALPHA_TRAINER_LIVENESS_SAFETY_BOUNDARIES_READY` |

## Dispatch chain

1. `agent_supervisor/tasks/060_trainer_parity_2e1c_alpha_implementation.json`
2. `agent_supervisor/tasks/061_trainer_parity_2e1c_alpha_local_validation.json`
3. `agent_supervisor/tasks/062_trainer_parity_2e1c_alpha_codex_review.json`

The supervisor executes 060, then 061 only after `46_2E1C_ALPHA_GO_NO_GO.md`
reads `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`, then
062 only after `48_2E1C_ALPHA_VALIDATION_GO_NO_GO.md` reads
`PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED`.

## Stop the chain immediately if

- any predecessor marker file does not contain its required value;
- a forbidden token (Redis, subprocess, network, legacy import, GPU,
  clock read) is detected during self-grep or in the validation
  forbidden-token grep;
- a `python -m py_compile` failure on any authored Python file occurs;
- any Codex finding indicates live behavior, Redis writes, legacy
  mutation, or deployment intent;
- the `END_FILE: <path>` marker leak recurs in any authored Python
  file (the 2E1.B regression class).

## Live-trading status

LIVE TRADING: BLOCKED. No phase 2E1.C.α artifact may change this.

PHASE2E1C_ALPHA_GO_NO_GO_REQUEST_RECORDED
