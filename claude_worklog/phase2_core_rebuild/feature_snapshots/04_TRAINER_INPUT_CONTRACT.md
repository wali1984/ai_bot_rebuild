# Trainer Input Contract

Trainer-ready snapshots must include:
- stable `feature_snapshot_id`
- canonical and legacy symbol identities
- trainer schema version
- feature values
- freshness flags
- source key references
- source ingestor references
- stale/missing/unused feature lists

`confidence_input_ready` is true only when required features exist and no stale features block confidence use.

TRAINER_INPUT_CONTRACT_READY
