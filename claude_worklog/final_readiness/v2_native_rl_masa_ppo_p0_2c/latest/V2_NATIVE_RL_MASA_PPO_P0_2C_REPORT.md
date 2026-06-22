# V2 Native RL MASA/PPO P0.2C - Checkpoint Metadata + Safe Weight Loading

Phase: P0.2C; Sprint: 12h native core migration.

Generated: 2026-05-16T03:55:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## What was built

- v2/backend/app/services/rl_core/checkpoints.py - metadata-only
  inventory + safe-load shim. Walks configurable roots, hashes
  candidate files, parses legacy filenames, and refuses to
  deserialize PyTorch state into the V2 process.
- v2/backend/tests/integration/cli/test_v2_rl_core_p0_2c_checkpoint.py
  - 7 tests covering inventory, sha256, safe-load, and
  forbidden-import scan.

## Inventory snapshot

- Roots scanned: legacy_reference/.backups, v2/legacy_owned_runtime.
- Candidate count: 336 (truncated to first 25 in inventory JSON).
- Status: CHECKPOINT_METADATA_ONLY_NO_WEIGHTS_LOADED.

## Safe-load result

- weight_loading_status: CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED.
- model_shape_status: MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH.
- declared_observation_dim: 26 (matches POLICY_OBSERVATION_DIM).
- declared_action_count: 5 (hold, long, short, close, hedge).
- Blockers:
  - v2_control_plane_does_not_load_torch_weights
  - weight_shape_verification_requires_operator_approved_subprocess
  - checkpoint_promotion_to_v2_requires_codex_review

## Why no weight load happens

The V2 control plane is paper-only. Deserializing legacy .pt/.pth
into the FastAPI process would require PyTorch in the V2 venv, and
would execute arbitrary pickled Python. The promotion path is: an
operator-approved subprocess on the legacy trainer venv inspects
shape and exports a metadata manifest, and Codex reviews the export
before V2 references it.

## Legacy citations

- v2/legacy_owned_runtime/rl/checkpoint_manager.py
  sha256=151d8808d53b7ba00edc4411569ba2f86519154d52da1997b300cec14c3e1ba8
  size_bytes=12300.

## Output contract

checkpoint_inventory.json and checkpoint_loading_status.json carry
all the fields required by the P0.2C contract:

- checkpoint_id
- checkpoint_source
- checkpoint_metadata_status
- weight_loading_status
- model_shape_status
- missing_checkpoint_blockers

## Permanent migration contract checklist

- Legacy source path: yes (checkpoint_manager.py).
- SHA256: yes.
- Dependency closure: yes (no torch/numpy/redis dependency).
- Config/env mapping: not applicable (no runtime knobs read).
- Behavior mapping: yes (metadata-only inventory).
- V2 implementation: yes.
- Tests: yes (7 passing).
- Public payload: yes (inventory JSON; loading-status JSON).
- Codex review: pending.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

P0.2C is READY at the metadata-only contract level. Real weight
promotion remains CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED and is
gated by operator + Codex approval.
