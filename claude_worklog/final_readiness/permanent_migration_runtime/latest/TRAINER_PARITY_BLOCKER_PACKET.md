# Trainer Parity Blocker Packet

Generated: 2026-05-15
Source: V2 Permanent Migration Fix and Professional Frontend Runtime Readiness.

## Current trainer state

From `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json`
and the expected-move review payload:

- `trainer_parity_status`: `BLOCKS_LEGACY_SHUTDOWN`
- `confidence_calibration_mode`: `DERIVED_FROM_LEGACY_LOG`
- remaining parity gaps:
  - `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED`
  - `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE`
  - `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED`

The current trainer bridge is honestly classified as `READONLY_BRIDGED` / `PAPER_ONLY`
under the migration completion contract. It is NOT `MIGRATED_CODEX_PASS`.

## Why this packet exists

This packet:
1. Tells the permanent objective router that trainer parity is a P0 blocker.
2. Refuses to mark the trainer bridge `MIGRATED_CODEX_PASS` because native trainer
   evidence (native confidence calibration, native feature attribution, native
   feature snapshot id) is not present.
3. Refuses to emit a synthetic full-parity claim because the contract requires real
   evidence (SHA256 from the legacy manifest, dependency closure, GPU/CUDA parity,
   prediction schema parity) before that label can be applied.

## Required work to clear the blocker

The router will continue to dispatch `claude_port_v2_trainer_bridge_full_legacy_parity`
until all of the following artifacts exist and pass Codex review:

- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/v2_trainer_bridge_FULL_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/v2_trainer_bridge_legacy_behavior_mapping.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_dependency_closure_final.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_config_env_parity.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_feature_input_parity.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_prediction_output_parity.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_checkpoint_parity.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_gpu_runtime_parity.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_confidence_calibration_parity.json`
- `claude_worklog/final_readiness/v2_trainer_bridge_full_legacy_parity/latest/trainer_feature_attribution_parity.json`

Each artifact must satisfy clauses 1-13 of the migration completion contract.

## What this packet does not do

- It does not enable live trading.
- It does not authorize canary trading.
- It does not authorize legacy shutdown.
- It does not authorize Redis trim.
- It does not modify the trainer venv, legacy services, or exchange state.
- It does not produce a synthetic full-parity claim.

If the operator wishes to advance V2 paper-only shutdown evaluation in the meantime,
they must explicitly accept the
`TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET` referenced in
`claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json`.
Live and canary remain `blocked_human_only` regardless.
