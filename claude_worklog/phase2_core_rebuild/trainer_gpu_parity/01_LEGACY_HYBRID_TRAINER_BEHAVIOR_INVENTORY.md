# Legacy Hybrid Trainer Behavior Inventory

This inventory is grounded in the trainer atlas. Raw verification uses
`tools/show_trainer_section.py` against
`legacy_reference/rl/hybrid_trainer.py`.

## Canonical primary file (from atlas)

- Path: `legacy_reference/rl/hybrid_trainer.py`
- Lines: 57,250
- Bytes: 3,165,342
- SHA256: `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`
- Source: `claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md`

## Atlas coverage status (from atlas)

- `unclassified_chunks: 0`
- `unknown_signal_paths: 0`
- `unknown_reward_paths: 0`
- `unknown_confidence_paths: 0`
- `unknown_redis_writes: 0`
- Source: `claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md`

## Behaviors to preserve (parity-critical)

Parity behaviors are recorded as references into the atlas, not as inline
rewrites. V2 must reproduce these behaviors via subprocess boundary against
the legacy runtime and via parity tests.

- Hybrid PPO + supervised pretraining loop.
  - Atlas evidence: `HYBRID_TRAINER_FUNCTION_INDEX.json`,
    `HYBRID_TRAINER_CLASS_INDEX.json`,
    `HYBRID_TRAINER_RUNTIME_ENTRYPOINTS.json`.
- MASS / state-space construction and feature ingestion.
  - Atlas evidence: `HYBRID_TRAINER_FEATURE_PATHS.json`.
- Reward path computation and reward shaping.
  - Atlas evidence: `HYBRID_TRAINER_REWARD_PATHS.json`,
    chunk classifications in `HYBRID_TRAINER_CHUNK_CLASSIFICATION.md`.
- Confidence calibration and confidence-driven gating.
  - Atlas evidence: `HYBRID_TRAINER_CONFIDENCE_PATHS.json`,
    Tier A confidence chunks in `HYBRID_TRAINER_CHUNK_CLASSIFICATION.md`.
- Signal publication path (legacy publisher pattern).
  - Atlas evidence: `HYBRID_TRAINER_SIGNAL_PATHS.json`,
    `HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md` (`write_signal` markers).
- Checkpoint save / load / promotion behavior.
  - Atlas evidence: `HYBRID_TRAINER_CHECKPOINT_PATHS.json`.
- Live / paper mode branching.
  - Atlas evidence: `HYBRID_TRAINER_RUNTIME_ENTRYPOINTS.json`,
    `HYBRID_TRAINER_CONFIG_USAGE.json`.
- Symbol/timeframe context, including hot-reload from Redis (read-only).
  - Atlas evidence: `HYBRID_TRAINER_REDIS_USAGE.json`,
    `HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md` (`read_only` markers).

## Known fragility classes (must be fixed in V2 wrapper, not in legacy file)

- Prediction worker death while parent process remains alive.
- Standard-output / broken-pipe vulnerability in long-running training loops.
- Missing `feature_snapshot_id` and `prediction_id` propagation.
- Missing confidence attribution and explainability metadata.
- Weak worker liveness monitoring.
- Missing freshness / stale / missing / unused feature flags.
- Source: `claude_worklog/legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`.

## Non-mutation rule

`legacy_reference/rl/hybrid_trainer.py` and any other trainer file under
`legacy_reference/**` must not be modified by V2 work. Behavior fixes are
implemented by the V2 wrapper layer, not by editing the legacy file.

PHASE2_TRAINER_GPU_PARITY_BEHAVIOR_INVENTORY_READY
