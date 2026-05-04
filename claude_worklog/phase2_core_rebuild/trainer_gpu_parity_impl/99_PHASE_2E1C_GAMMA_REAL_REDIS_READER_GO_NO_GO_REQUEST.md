# Phase 2E1.C.γ.real — GO/NO-GO Request

This document requests permission to dispatch the consolidated
implementation task for Phase 2E1.C.γ.real of REQ_0006.

## Predecessor marker verification

The supervisor MUST verify, before dispatching the implementation
task, that every one of these markers is present and matches exactly:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`
  contains `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`
  contains `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`
  contains `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`
  contains `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`
  contains `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md`
  contains `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS`.

If any marker is missing or different, the supervisor MUST refuse to
dispatch the implementation task and MUST log the missing marker.

## Dirty-tree precondition

The supervisor MUST verify, before dispatch, that
`git status -s` over the four predecessor source trees plus the two
existing scaffold files returns zero modified lines:

```
git status -s \
  v2/backend/app/domain/trainer_liveness/ \
  v2/backend/app/domain/liveness_stream_growth/ \
  v2/backend/app/domain/trainer_liveness_composition/ \
  v2/backend/app/domain/trainer_liveness_observation_collector/ \
  v2/backend/app/adapters/redis_v2/client.py \
  v2/backend/app/adapters/redis_v2/streams.py
```

If non-empty, the supervisor MUST refuse to dispatch and MUST surface
a `dirty_predecessor_tree` reason.

## Authoring sequence

On verified predecessors and clean tree:

1. Dispatch task `087_trainer_parity_2e1c_gamma_real_implementation`
   (consolidated implementation). Wait for completion.
2. Verify
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/100_2E1C_GAMMA_REAL_GO_NO_GO.md`
   contains exactly
   `PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`.
   If `_BLOCKED` instead, supervisor surfaces the blocker and stops.
3. On PASS, dispatch task
   `088_trainer_parity_2e1c_gamma_real_codex_review` for Codex
   adversarial review against the rubric in 97 plus the safety
   boundaries in 98. Wait for completion.
4. Verify
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md`
   contains exactly
   `PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS`. If `_FAIL`,
   the supervisor dispatches a REQ_0007/REQ_0014 autofix task scoped
   to the γ.real source/test trees only and re-runs Codex review.
5. On Codex PASS, the planner opens the next REQ_0006 milestone in a
   fresh spec turn (γ.real.factory wiring under a separate spec set).

## Live-trading status

LIVE TRADING: BLOCKED. FINAL LIVE GATE: BLOCKED.

PHASE2E1C_GAMMA_REAL_REDIS_READER_GO_NO_GO_REQUEST_READY
