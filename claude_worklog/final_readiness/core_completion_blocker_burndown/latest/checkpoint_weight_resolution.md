# Phase 1 - Checkpoint Weight Blocker Resolution

Generated: 2026-05-16T22:25:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## Scope

Resolve CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED_NOT_ACCEPTED_FOR_PAPER_ONLY_SHUTDOWN
by scanning V2-owned / permitted paths only and emitting an honest
classification. The V2 control plane is not permitted to deserialize
legacy PyTorch state (see CLAUDE.md protected runtime policy).

## Scanned roots (V2-owned / permitted only)

- v2/legacy_owned_runtime
- v2/runtime
- .local_secrets
- claude_worklog/final_readiness/full_legacy_root_filesystem_inventory/latest

.local_models is absent and was skipped.

## Result

- candidate_count: 0 (no .pt/.pth/.ckpt/.zip in the scanned roots)
- checkpoint_weight_status: CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
- model_shape_status: MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH_LOAD_IN_V2

Note: legacy_reference/.backups holds 336 historical .pt files (per
P0.2C), but legacy_reference is outside the V2-owned scan and is NOT
permitted material for V2 to ingest into its policy weights without
operator approval.

## Operator request

The operator must choose ONE of the two options:

1. Provide an operator-approved checkpoint blob under
   `.local_models/<name>.pt` with a sidecar metadata JSON
   describing tensor shapes, AND authorize V2 to invoke a
   legacy-venv subprocess to inspect the tensor shapes via a
   read-only metadata export, AND have Codex review the resulting
   manifest before V2 references the artifact. OR

2. Explicitly accept CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED as a
   paper-only-shutdown limitation. In this case the V2 system
   continues to operate paper-only with native deterministic-init
   policy weights, and any future live trading must be re-gated by
   a new full approval flow.

The implementation does NOT load torch weights into the V2 process
either way. Option 1 is metadata-only inspection through a
subprocess boundary, then Codex review.

## What this does NOT change

- The strict P0.2F paper-fill gate remains in force.
- Checkpoint parity is NOT claimed.
- live_gate remains blocked_human_only; live_symbols remains [].
- No approval token created.

## Permanent migration contract checklist

- Legacy source path: cited (v2/legacy_owned_runtime/rl/checkpoint_manager.py).
- SHA256: yes.
- Dependency closure: pure stdlib classifier; no torch.
- Config/env mapping: candidate_paths_scanned recorded in JSON.
- Behavior mapping: yes (metadata-only inventory + operator
  request enumeration).
- V2 implementation: yes (run_p1_checkpoint_resolution.py).
- Tests: existing P0.2C tests cover the inventory and refusal-to-load
  contract.
- Public payload: yes
  (v2/frontend/public/core_completion_blocker_burndown/latest/checkpoint_weight_resolution.json).
- Codex review: pending.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

Phase 1 closes by honestly retaining CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
and emitting an explicit operator request. The final burndown
GO/NO-GO requires the operator to choose option 1 or option 2; this
phase does NOT make that choice.
