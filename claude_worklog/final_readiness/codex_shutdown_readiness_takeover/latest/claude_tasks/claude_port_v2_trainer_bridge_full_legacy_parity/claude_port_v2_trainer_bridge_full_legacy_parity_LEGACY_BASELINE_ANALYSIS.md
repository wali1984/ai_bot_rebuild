# Legacy Baseline Analysis: Trainer Bridge Full Parity

The preserved legacy hybrid trainer baseline is large and dependency-heavy. Codex reviewed it read-only and did not execute it from the legacy tree.

## SHA Citations

- `rl/hybrid_trainer.py` SHA256 `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`: main hybrid trainer runtime, PPO/raw-decision path, signal publication helpers, checkpoint behavior, and GPU trainer behavior.
- `rl/orchestrator_worker.py` SHA256 `a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6`: orchestrator/trainer handoff context.
- `rl/unified_feature_builder.py` SHA256 `2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5`: feature snapshot construction used by trainer inputs.
- `rl/obs_schema.py` SHA256 `9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f`: observation schema and feature contract.

## Parity Finding

The current V2 trainer bridge does not yet produce an accepted legacy hybrid prediction. The public status continues to reject current wrapper predictions as `WRAPPER_NOT_LEGACY_HYBRID_PARITY`, which is the correct fail-closed classification.

## Blocked Dependency Finding

The V2 `.venv` is missing `torch`, `stable_baselines3`, `cloudpickle`, and `gymnasium`. These are required for a full preserved-tree legacy hybrid trainer execution path unless an operator-approved V2-native parity implementation avoids them.

No package installation was performed.
