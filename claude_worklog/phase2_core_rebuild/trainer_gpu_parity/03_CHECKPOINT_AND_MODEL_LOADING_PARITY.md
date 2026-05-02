```
# Checkpoint and Model Loading Parity

## Source of truth

`claude_worklog/trainer_atlas/HYBRID_TRAINER_CHECKPOINT_PATHS.json` enumerates
all checkpoint save / load / promotion sites in
`legacy_reference/rl/hybrid_trainer.py`. The promotion controller is
referenced from `legacy_reference/rl/promotion_controller.py` (read-only).

## Parity rules

- Checkpoint file naming, directory layout, and metadata fields produced by
  the legacy runtime must be preserved bit-for-bit by the legacy runtime.
- V2 must not write to legacy checkpoint paths. V2 reads checkpoint metadata
  via the subprocess adapter (`07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`).
- Promotion of a checkpoint to a "production" or "live" status remains gated
  by the legacy promotion controller and by an explicit human approval at
  the live readiness gate.
- Paper / replay / shadow runs may load any non-promoted checkpoint via the
  subprocess adapter.

## Required V2-side metadata

For every checkpoint observed via the adapter, V2 must record:

- `checkpoint_id`
- `model_version`
- `created_ts_ms`
- `promoted_flag`
- `legacy_checkpoint_path`
- `legacy_metadata_hash`

These fields feed
`claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`
stage A (trainer inference output).

## Forbidden actions

- No mutation of legacy checkpoint files.
- No mutation of legacy promotion files.
- No execution of the legacy promotion controller from V2.
- No copy of legacy checkpoints into V2 storage at this phase.

PHASE2_TRAINER_GPU_PARITY_CHECKPOINT_READY
```
