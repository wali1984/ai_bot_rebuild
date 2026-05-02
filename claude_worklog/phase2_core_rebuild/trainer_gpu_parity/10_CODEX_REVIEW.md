# Phase 2E Trainer GPU Parity Plan Codex Review

Verdict: FAIL

This was a planning-only adversarial review. I did not write trainer code, did
not modify `legacy_reference/**`, did not touch `/home/wali/Desktop/AI BOT`,
did not invoke Redis tooling, did not publish/delete streams, did not restart
services, and did not perform exchange or live-trading actions.

## Findings

### 1. Blocker: six plan documents do not carry the required canonical semantic marker

Requirement checked: every plan document carries a
`PHASE2_TRAINER_GPU_PARITY_*_READY` semantic marker.

Observed canonical matches exist only in:

- `00_SCOPE.md`: `PHASE2_TRAINER_GPU_PARITY_SCOPE_READY`
- `01_LEGACY_HYBRID_TRAINER_BEHAVIOR_INVENTORY.md`:
  `PHASE2_TRAINER_GPU_PARITY_BEHAVIOR_INVENTORY_READY`
- `08_NON_LIVE_VALIDATION_PLAN.md`:
  `PHASE2_TRAINER_GPU_PARITY_VALIDATION_PLAN_READY`

The following files use non-canonical markers that do not match the required
`PHASE2_TRAINER_GPU_PARITY_*_READY` form:

- `02_GPU_AND_BATCHING_PARITY_REQUIREMENTS.md`:
  `PHASE2_TRAINER_GPU_BATCHING_PARITY_READY`
- `03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md`:
  `PHASE2_TRAINER_CHECKPOINT_PARITY_READY`
- `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`:
  `PHASE2_TRAINER_REWARD_CONFIDENCE_PARITY_READY`
- `05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`:
  `PHASE2_TRAINER_PREDICTION_WORKER_LIVENESS_FIX_READY`
- `06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`:
  `PHASE2_TRAINER_OUTPUT_CONTRACT_READY`
- `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`:
  `PHASE2_TRAINER_PROCESS_BOUNDARY_READY`

`09_GO_NO_GO.md` correctly contains exactly one line:
`PHASE2_TRAINER_GPU_PARITY_PLAN_READY_FOR_CODEX_REVIEW`.

### 2. Blocker: prohibited literal operation phrases are present in the plan surface

Requirement checked: no plan document contains a literal Redis CLI command,
stream-publish call, stream-delete call, Redis database flush, order placement
call, order cancellation call, leverage modification call, margin mode
modification call, or live trading enablement call.

The plan uses several of these literals in forbidden-action wording. Even
though they are stated as prohibitions, they still violate the requested
literal-text check:

- `00_SCOPE.md` contains "order placement or cancellation", "leverage
  modification or margin mode modification", and "live trading enablement".
- `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md` contains "order
  placement", "order cancellation", "leverage modification", "margin mode
  modification", "live trading enablement", "stream-publish", and "Redis
  database flush".
- `08_NON_LIVE_VALIDATION_PLAN.md` contains "leverage / margin mutations" and
  "live trading enablement".

### 3. Major: reward/confidence parity doc does not enumerate all explainability fields required by legacy preservation

Requirement checked: reward and confidence parity rules forbid client-side
mutation of `confidence_calibrated` and require explainability fields per
`legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`.

The plan correctly forbids client-side mutation of `confidence_calibrated`.
However, `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` only names
`confidence_explainability`, `top_positive_features[]`, and
`top_negative_features[]`. The legacy preservation requirement also requires
source key/pattern references, freshness metadata, and stale/missing/unused
flags. Those fields are covered elsewhere in the output contract and feature
snapshot requirements, but the reward/confidence parity document itself does
not fully bind the legacy-preservation explainability field set.

## Passed Checks

- The behavior inventory cites the trainer atlas as the source basis and
  references the canonical primary trainer size/hash from
  `TRAINER_SIZE_RECONCILIATION.md`: 57,250 lines, 3,165,342 bytes, sha256
  `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`.
- GPU and batching parity rules forbid replacing the hybrid trainer with a
  basic policy gradient loop and forbid CUDA/SubprocVecEnv/batch changes
  without evidence or approval.
- Checkpoint parity rules forbid mutating legacy checkpoint files and forbid
  executing the legacy promotion controller from V2.
- The prediction-worker liveness spec names
  `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`, names
  `TRAINER_INTERNAL_LIVENESS_CRITICAL`, and lists every observability signal
  required by `v2_requirements/09`.
- The trainer output contract enumerates all Stage A and Stage B fields from
  `v2_requirements/03` and includes `feature_snapshot_id` from
  `v2_requirements/02`.
- The process-boundary spec mandates subprocess invocation, restricts adapter
  vocabulary to `read_only`, `status`, and `export`, forbids the listed legacy
  trainer/orchestrator/trader invocations, forbids Redis-mutating tools, and
  does not require importing legacy trainer modules into FastAPI.
- The non-live validation plan does not require live action and places
  execution validation behind future Phase 2E1.
- The plan states that `legacy_reference/**` and `/home/wali/Desktop/AI BOT`
  must not be modified.
- The plan respects the `CLAUDE.md` trainer size reconciliation approach by
  relying on the trainer atlas and targeted section review rather than
  requiring an end-to-end raw trainer dump.

## Required Fix Before Pass

1. Rename the `02` through `07` ready markers so each matches
   `PHASE2_TRAINER_GPU_PARITY_*_READY`.
2. Remove or abstract the prohibited literal operation phrases from plan docs,
   especially the `stream-publish` and Redis database flush wording in
   `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`.
3. Extend `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` so its confidence
   explainability section explicitly requires the full legacy-preservation
   field set: confidence explainability, top positive/negative contributors,
   source key/pattern references, freshness metadata, and stale/missing/unused
   flags.
