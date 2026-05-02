# Phase 2E Trainer GPU Parity Plan Codex Review Rerun

Verdict: FAIL

This was a planning-only rerun review. I did not write trainer code, did not
modify `legacy_reference/**`, did not touch `/home/wali/Desktop/AI BOT`, did
not invoke Redis tooling, did not mutate Redis streams or namespaces, did not
restart services, and did not perform exchange-side or live-mode actions.

## Prior Finding Resolution Status

- Finding 1 from `10_CODEX_REVIEW.md`: RESOLVED. Plan documents `02` through
  `07` now use canonical `PHASE2_TRAINER_GPU_PARITY_*_READY` markers, and
  `00`, `01`, `08`, and `09` retain acceptable ready markers.
- Finding 2 from `10_CODEX_REVIEW.md`: NOT RESOLVED for the rerun criteria.
  The originally cited plan files were remediated, but the rerun request also
  applies the literal-text ban to `12_REMEDIATION_LOG.md`, which still contains
  the exact prohibited exchange/config/live-operation phrases at lines 37-41.
- Finding 3 from `10_CODEX_REVIEW.md`: RESOLVED. `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`
  now binds the full legacy-preservation explainability set: `confidence_explainability`,
  `top_positive_features[]`, `top_negative_features[]`, `source_key_references[]`,
  `freshness_metadata`, and stale/missing/unused `feature_status_flags`.

## Findings

### 1. Blocker: `13_GO_NO_GO_RERUN_REQUEST.md` is not exactly one line

Requirement checked: `13_GO_NO_GO_RERUN_REQUEST.md` must contain exactly one
line:
`PHASE2_TRAINER_GPU_PARITY_PLAN_REMEDIATED_READY_FOR_CODEX_RERUN`.

Observed: the marker appears once, but the file is wrapped in a fenced code
block and has three lines:

- line 1: opening fence
- line 2: required marker
- line 3: closing fence

This fails the exact one-line requirement.

### 2. Blocker: rerun forbidden-literal check still fails in `12_REMEDIATION_LOG.md`

Requirement checked: no document `00` through `09`, `12`, or `13` may contain
the exact prohibited literal phrases named by the rerun request, even inside a
do-not-do clause.

Observed: `12_REMEDIATION_LOG.md` still contains the exact prohibited
exchange/config/live-operation phrases at lines 37-41 in the remediation table.
Because `12` is explicitly inside the rerun check surface, this keeps prior
Finding 2 unresolved for the rerun.

## Passed Checks

- `00_SCOPE.md` through `09_GO_NO_GO.md` each carry a canonical
  `PHASE2_TRAINER_GPU_PARITY_*_READY` marker or the required plan review marker.
- `09_GO_NO_GO.md` contains exactly one line:
  `PHASE2_TRAINER_GPU_PARITY_PLAN_READY_FOR_CODEX_REVIEW`.
- `01_LEGACY_HYBRID_TRAINER_BEHAVIOR_INVENTORY.md` cites the trainer atlas as
  source of truth and references the canonical primary trainer measurement from
  `TRAINER_SIZE_RECONCILIATION.md`: 57,250 lines, 3,165,342 bytes, sha256
  `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`.
- `02_GPU_AND_BATCHING_PARITY_REQUIREMENTS.md` forbids replacing the hybrid
  trainer with a basic policy-gradient loop and forbids CUDA device selection
  or SubprocVecEnv/batching changes without evidence or approval.
- `03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md` forbids mutating legacy
  checkpoint files and forbids executing the legacy promotion controller from
  V2.
- `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` forbids client-side mutation of
  `confidence_calibrated` and binds the full legacy-preservation explainability
  field set.
- `05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md` names
  `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`, names
  `TRAINER_INTERNAL_LIVENESS_CRITICAL`, and lists every observability signal
  required by `v2_requirements/09`.
- `06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md` enumerates every Stage A and
  Stage B field from `v2_requirements/03`, includes `feature_snapshot_id` from
  `v2_requirements/02`, and includes the full legacy-preservation
  explainability field set.
- `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md` mandates subprocess
  invocation only, restricts adapter arguments to `read_only`, `status`, and
  `export`, and forbids the listed legacy trainer/orchestrator/trader,
  exchange-write, leverage/margin-config-write, Redis-admin, and Redis-mutating
  invocation classes.
- `08_NON_LIVE_VALIDATION_PLAN.md` does not require live-mode action and gates
  execution validation behind future Phase 2E1.
- The plan states that `legacy_reference/**` and `/home/wali/Desktop/AI BOT`
  must not be modified.
- The reviewed plan follows the `CLAUDE.md` trainer size reconciliation rule by
  using the trainer atlas and targeted evidence rather than requiring an
  end-to-end raw trainer dump.
- The reviewed plan follows the `CLAUDE.md` protected runtime policy by
  requiring a subprocess boundary and not requiring legacy trainer imports into
  the FastAPI process.

## Required Fix Before Pass

1. Replace `13_GO_NO_GO_RERUN_REQUEST.md` with the required marker as the only
   line in the file.
2. Remove or abstract the exact prohibited phrases from `12_REMEDIATION_LOG.md`
   lines 37-41, because `12` is part of the rerun forbidden-literal surface.
