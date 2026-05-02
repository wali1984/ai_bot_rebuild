```
# Reward and Confidence Parity Map

## Reward parity

- Source of truth: `claude_worklog/trainer_atlas/HYBRID_TRAINER_REWARD_PATHS.json`.
- Tier A chunk classification: `claude_worklog/trainer_atlas/HYBRID_TRAINER_CHUNK_CLASSIFICATION.md`
  (the majority of trainer chunks are classified `reward` Tier A).
- V2 does not reimplement the reward function. V2 must call the legacy
  runtime via the subprocess boundary and observe reward outputs.
- V2 may compute derived reward telemetry (e.g., reward distribution stats)
  for monitoring purposes only, and must mark such telemetry as derived.

## Confidence parity

- Source of truth: `claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIDENCE_PATHS.json`.
- Confidence calibration must remain in the legacy runtime. V2 only consumes
  `confidence_raw` and `confidence_calibrated`.
- Per `claude_worklog/legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`,
  V2 must bind the **full legacy-preservation explainability field set** to
  every trainer inference record. The set is mandatory and complete; missing
  any field is a hard observability validation failure.

## Mandatory legacy-preservation explainability field set

Every Stage A trainer inference record (per
`06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`) must include:

- `confidence_explainability` — structured payload describing how
  `confidence_calibrated` was produced.
- `top_positive_features[]` — ranked list of features with positive
  contribution to the prediction.
- `top_negative_features[]` — ranked list of features with negative
  contribution to the prediction.
- `source_key_references[]` — for every contributing feature, the Redis
  key or pattern (and any DB / file source) the value originated from.
  This binds explainability to raw evidence per CLAUDE.md.
- `freshness_metadata` — per-feature last-update timestamp, age in
  milliseconds, and freshness envelope flag aligned to
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`.
- `feature_status_flags` — per-feature classification into:
  - `stale[]` — feature exists but is older than its freshness SLA.
  - `missing[]` — feature is referenced by the model but absent from the
    snapshot.
  - `unused[]` — feature is present in the snapshot but not consumed by
    the active model version.

## Forbidden actions

- No replacement of reward shaping with a "simplified" reward.
- No replacement of confidence calibration with a fixed threshold.
- No client-side mutation of `confidence_calibrated`.
- No emission of a Stage A record that omits any field in the mandatory
  legacy-preservation explainability field set above.

PHASE2_TRAINER_GPU_PARITY_REWARD_CONFIDENCE_READY
```
