# Planner Next-Milestone Selection — Phase 2E1.B

## Decision

The next safest non-live milestone for REQ_0006 is Phase 2E1.B —
Trainer Output Contract domain layer.

## Why this is the safest next step

Phase 2E1.A (subprocess adapter foundation) reached
PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS at
`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`.

Phase 2E1.B is:
- Pure domain layer (no I/O, no subprocess, no Redis).
- Bound by the existing PASSed contract spec
  (`trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`)
  and the parity map
  (`trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`).
- Independent of any live trainer process.
- Independent of the subprocess adapter — the domain layer must not
  import the adapter (enforced by the safety-boundary doc).

Phase 2E1.C (prediction worker liveness) is the next slice after
2E1.B, but it requires the domain records to exist first so that
liveness reporting can use the lineage record types. Sequencing
2E1.B before 2E1.C keeps the change radius minimal per slice.

## Spec revision performed in this planner turn

The original Phase 2E1.B spec (`26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`)
diverged from the contract/parity map in two places. Both are
corrected in this turn before any implementation begins. Detail in
`trainer_gpu_parity_impl/35_PLANNER_PHASE_2E1B_SPEC_REVISION_NOTE.md`.

The two corrections, summary:
1. `freshness_metadata` was silently dropped. It is reinstated as a
   distinct Stage A field with its own value object, because the
   parity map lists it as mandatory legacy-preservation
   explainability and the contract lists it separately from
   `feature_freshness_envelope` (per-source vs per-feature).
2. `symbol` was added to Stage A without contract justification. The
   field is retained because the contract integrity rule
   "Cross-symbol linkage is invalid" plus Stage B carrying `symbol`
   require the prediction record to expose `symbol` at the dataclass
   surface for validator-time enforcement. The justification is now
   inline in the revised spec.

## Predecessors satisfied

- PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS
- PHASE2_TRAINER_GPU_PARITY_OUTPUT_CONTRACT_READY
- PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2_FEATURE_SNAPSHOT_CODEX_REVIEW_PASS
- PHASE2_LEGACY_SERVICE_MAP_CODEX_PASS

## Hard stops not triggered

- No legacy mutation.
- No Redis writes.
- No exchange action.
- No live trainer restart.
- No subprocess.
- No deploy.
- No production migration.
- No secret exposure.
- No L4/L5 behavior requested.

## Artifacts dispatched in this turn

Authoring artifacts (revised in this turn):
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/27_PHASE_2E1B_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/29_PHASE_2E1B_GO_NO_GO_REQUEST.md`

Authoring artifacts (unchanged in this turn):
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/28_PHASE_2E1B_SAFETY_BOUNDARIES.md`

New planner artifact:
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/35_PLANNER_PHASE_2E1B_SPEC_REVISION_NOTE.md`

Supervisor tasks (revised in this turn):
- `claude_worklog/agent_supervisor/tasks/056_trainer_parity_2e1b_implementation.json`
- `claude_worklog/agent_supervisor/tasks/057_trainer_parity_2e1b_codex_review.json`
  (gated on 056's GO_NO_GO marker)

## What this turn does NOT do

- Does not implement code in `v2/`. Implementation is dispatched to
  task 056 under the existing staged author → implement → Codex
  pattern used for 2E1.A.
- Does not advance REQ_0007 (Codex autofix authorization). 2E1.B is
  expected to pass without autofix; if Codex returns a FAIL on 057,
  REQ_0007 scope authorizes a remediation task in the same family.
- Does not advance REQ_0008 (enterprise website). Frontend work is a
  parallel track; opening it in the same turn would expand the change
  radius beyond what is safe.

## Markers

- Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE
- Active slice: 2E1.B
- Slice status: spec revised (contract-aligned), implementation
  pending via task 056

PLANNER_NEXT_MILESTONE_PHASE2E1B_SELECTED
PLANNER_NEXT_MILESTONE_PHASE2E1B_SPEC_REVISED

