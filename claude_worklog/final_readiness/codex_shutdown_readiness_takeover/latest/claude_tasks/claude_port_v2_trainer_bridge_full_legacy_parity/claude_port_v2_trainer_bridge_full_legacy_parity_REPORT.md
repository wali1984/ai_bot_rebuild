# Trainer Bridge Full Legacy Parity Report

Task: `claude_port_v2_trainer_bridge_full_legacy_parity`

Result: `BLOCKED_OR_REMEDIATED` with classification `V2_ENV_BLOCKED_MISSING_DEPENDENCY`.

Claude was dispatched through the supervisor, but the child process produced zero stdout, zero stderr, and no artifacts before Codex terminated the stalled V2-only child. Codex then performed the safe read-only audit and emitted this conservative classification instead of installing heavy trainer dependencies.

## Current Runtime Truth

- `v2_trainer_bridge` remains `WRAPPER_NOT_LEGACY_HYBRID_PARITY`.
- `accepted_as_legacy_hybrid_prediction` remains `false`.
- `checkpoint_evidence_status` remains `MISSING_OR_REJECTED`.
- V2 currently observes a fresh paper wrapper prediction with `prediction_id`, `feature_snapshot_id`, raw/calibrated confidence, and feature attribution, but the source is `V2_PAPER_TRAINER_WRAPPER`, not the preserved legacy hybrid trainer.
- Legacy trainer process is observed read-only; Codex did not stop or restart it.
- GPU evidence is present, but V2 `.venv` dependency evidence is incomplete.

## Dependency Block

The V2 `.venv` is missing the active trainer-path packages:

- `torch`
- `stable_baselines3`
- `cloudpickle`
- `gymnasium`

Codex did not install these packages. Installing `torch` and trainer stack dependencies is treated as a heavy trainer dependency decision requiring operator approval in this shutdown-readiness loop.

## SHA-Cited Legacy Baseline

The full runtime manifest cites these preserved sources:

- `rl/hybrid_trainer.py`: `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`
- `rl/orchestrator_worker.py`: `a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6`
- `rl/unified_feature_builder.py`: `2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5`
- `rl/obs_schema.py`: `9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f`

## Public Payload Impact

No runtime worker port was applied. The existing trainer bridge public payload continues to fail closed and must not be interpreted as legacy hybrid parity.

## GO / NO-GO

NO-GO for clearing trainer parity. This blocks legacy shutdown unless the operator explicitly accepts trainer parity as non-shutdown-blocking for V2 paper-only operation or approves the heavy V2 trainer dependency installation path.
