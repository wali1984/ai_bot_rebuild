# Phase 2E1.B — Trainer Output Contract Domain Record Spec

This document is the authoring spec for Phase 2E1.B of REQ_0006
(implement V2 trainer GPU parity service).

It is non-live, non-Redis, non-subprocess, non-legacy-mutating.

This file was revised in the planner turn that authored
`35_PLANNER_PHASE_2E1B_SPEC_REVISION_NOTE.md`. Two divergences from
the contract were corrected before implementer dispatch:
1. `freshness_metadata` reinstated as a distinct Stage A field.
2. `symbol` retention on Stage A justified inline (see "Stage A field
   rationale").

## Predecessor gates

- Trainer GPU parity plan: PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS
  (`trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md`).
- Trainer output contract spec: PHASE2_TRAINER_GPU_PARITY_OUTPUT_CONTRACT_READY
  (`trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`).
- Subprocess adapter foundation:
  PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- Feature snapshot schema:
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`.
- Prediction/signal/decision ID chain:
  `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`.
- Reward & confidence parity map:
  `trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`.

## Surface to create

Package: `v2/backend/app/domain/trainer_parity/`

Files (exact set, no extras):
- `__init__.py` — public surface only, re-exports the nine names listed
  in "Public surface" below.
- `stage_a_record.py` — Stage A trainer-inference record dataclass and
  helpers.
- `stage_b_record.py` — Stage B trainer-signal record dataclass and
  helpers.
- `feature_status_flags.py` — feature status flag value object
  (`stale`, `missing`, `unused`) and per-source freshness envelope
  value object.
- `freshness_metadata.py` — per-feature freshness value object
  aligned to `02_FEATURE_SNAPSHOT_SCHEMA.md` freshness policy.
- `lineage_validator.py` — pure-function lineage validators that bind
  Stage B → Stage A → feature_snapshot_id → symbol.
- `explainability_validator.py` — pure-function validator that requires
  the full legacy-preservation explainability set on every Stage A
  record.
- `errors.py` — domain-specific exception types.

Tests live in `v2/backend/tests/unit/domain/trainer_parity/`.

## Public surface (`__init__.py` re-exports, exactly these names)

1. `StageATrainerRecord`
2. `StageBTrainerRecord`
3. `FeatureStatusFlags`
4. `FeatureFreshnessEnvelope`
5. `FreshnessMetadata`
6. `validate_stage_a_lineage`
7. `validate_stage_b_lineage`
8. `validate_stage_a_explainability`
9. `TrainerParityLineageError`

No other names are re-exported. No re-export of internal helpers, no
re-export of `errors` submodule itself, no re-export of
`ConfidenceExplainability` (it is a public type but only as a
constructor argument for `StageATrainerRecord`; it lives at module
scope in `stage_a_record.py` and is not re-exported from `__init__`).

## Stage A field rationale

The contract bullet list at
`trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`
does not literally enumerate `symbol` for Stage A. This spec retains
`symbol` on the Stage A record because:

- The contract Integrity rules section states "Cross-symbol linkage is
  invalid."
- Stage B carries `symbol` (per the same contract).
- `validate_stage_b_lineage` must enforce
  `stage_b.symbol == stage_a.symbol`. That is impossible without
  Stage A exposing `symbol` directly at the dataclass surface, since
  `feature_snapshot_id` is an opaque string at the domain layer even
  though its composition (per `02_FEATURE_SNAPSHOT_SCHEMA.md`) starts
  with the symbol.

The contract bullet list does literally enumerate both
`freshness_metadata` and `feature_freshness_envelope` as distinct
Stage A fields. This spec carries both:
- `freshness_metadata` is **per feature consumed by the active model**.
- `feature_freshness_envelope` is **per source the snapshot reads
  from**. Sources can fan out to many features and features can be
  derived from many sources, so the two views are not interchangeable.

## Stage A record (`stage_a_record.py`)

Dataclass `StageATrainerRecord` (`@dataclass(frozen=True, slots=True)`).

Field set, in this order, with these types:

- `prediction_id: str`
- `feature_snapshot_id: str`
- `symbol: str`
- `model_version: str`
- `checkpoint_id: str`
- `prediction_ts_ms: int`
- `confidence_raw: float`
- `confidence_calibrated: float`
- `confidence_explainability: ConfidenceExplainability`
- `top_positive_features: tuple[str, ...]`
- `top_negative_features: tuple[str, ...]`
- `source_key_references: tuple[str, ...]`
- `feature_status_flags: FeatureStatusFlags`
- `freshness_metadata: FreshnessMetadata`
- `feature_freshness_envelope: FeatureFreshnessEnvelope`
- `worker_id: str`
- `worker_health_status: str`

`ConfidenceExplainability` is also defined in this module as a
`@dataclass(frozen=True, slots=True)` whose required fields mirror the
explainability bundle named in
`trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`:

- `confidence_components: tuple[tuple[str, float], ...]`
  (each tuple is (component_name, contribution); ordering is preserved)
- `confidence_floor_applied: bool`
- `confidence_ceiling_applied: bool`
- `calibration_model_version: str`
- `calibration_method: str`

The dataclass must:
- Be frozen and slotted.
- Validate basic invariants in `__post_init__`:
  - `prediction_id`, `feature_snapshot_id`, `symbol`, `model_version`,
    `checkpoint_id`, `worker_id`, `worker_health_status` non-empty.
  - `prediction_ts_ms >= 0`.
  - `confidence_raw` and `confidence_calibrated` in `[0.0, 1.0]`
    inclusive.
  - `top_positive_features` and `top_negative_features` are tuples of
    str, no duplicates, may be empty tuples.
  - `source_key_references` is a tuple of str, no duplicates.
- Raise `TrainerParityLineageError` on any invariant violation.
- Not perform any I/O.
- Not perform any subprocess, network, or filesystem call.
- Not import legacy modules.
- Not write Redis.

`ConfidenceExplainability.__post_init__` invariants:
- `calibration_model_version` and `calibration_method` non-empty are
  enforced by `validate_stage_a_explainability` (defense-in-depth);
  the dataclass constructor itself raises only if the contributions
  contain a non-finite value or a component name is empty (so that
  building any `ConfidenceExplainability` with malformed components
  is impossible without raising). Duplicate-name and non-empty-set
  checks live in the explainability validator.

## Stage B record (`stage_b_record.py`)

Dataclass `StageBTrainerRecord` (`@dataclass(frozen=True, slots=True)`).

Field set, in this order:

- `signal_id: str`
- `prediction_id: str`
- `feature_snapshot_id: str`
- `symbol: str`
- `action: str`
- `action_type: str`
- `confidence: float`
- `signal_ts_ms: int`

`__post_init__` invariants:
- All str fields non-empty.
- `confidence` in `[0.0, 1.0]` inclusive.
- `signal_ts_ms >= 0`.
- `action` in the closed set `{"buy", "sell", "hold", "close"}`.
- `action_type` in the closed set `{"open_long", "open_short",
  "close_long", "close_short", "hold"}`.

These closed sets are local module constants prefixed with
`_ALLOWED_`. They are not exported.

Violations raise `TrainerParityLineageError`.

## Feature status flags (`feature_status_flags.py`)

Two dataclasses, both `@dataclass(frozen=True, slots=True)`.

`FeatureStatusFlags`:
- `stale: tuple[str, ...]`
- `missing: tuple[str, ...]`
- `unused: tuple[str, ...]`

`__post_init__` invariants:
- Each tuple has no duplicates.
- A feature name must not appear in more than one of the three tuples.

`FeatureFreshnessEnvelope` (per-source):
- `per_source_freshness_ms: tuple[tuple[str, int], ...]`
  (each tuple is (source_name, freshness_ms); ordering preserved)
- `oldest_source_age_ms: int`
- `oldest_source_name: str`

Invariants:
- `oldest_source_age_ms >= 0`.
- `oldest_source_name` non-empty.
- All freshness_ms `>= 0`.
- Source names in `per_source_freshness_ms` have no duplicates.
- The `(oldest_source_name, oldest_source_age_ms)` pair must equal the
  maximum-age entry in `per_source_freshness_ms`.

Violations raise `TrainerParityLineageError`.

## Freshness metadata (`freshness_metadata.py`)

Single dataclass `FreshnessMetadata` (`@dataclass(frozen=True,
slots=True)`).

`FreshnessMetadata` is the **per-feature** freshness view aligned to
the freshness policy in
`claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`. Each
entry references one feature consumed by the active model and reports
its last-update timestamp, age, and freshness status.

Field set, in this order:

- `per_feature_last_update_ms: tuple[tuple[str, int], ...]`
  (each tuple is (feature_name, last_update_ts_ms); ordering preserved)
- `per_feature_age_ms: tuple[tuple[str, int], ...]`
  (each tuple is (feature_name, age_ms); ordering preserved)
- `per_feature_status: tuple[tuple[str, str], ...]`
  (each tuple is (feature_name, status); ordering preserved)

Allowed status values are exactly:
`{"fresh", "warning", "stale", "missing"}`

The closed set is a local module constant
`_ALLOWED_FRESHNESS_STATUSES`. It is not exported.

`__post_init__` invariants:
- Each of the three tuples has no duplicate feature names.
- The set of feature names is identical across the three tuples
  (same membership; ordering is independent and preserved within
  each tuple).
- All `last_update_ts_ms` values are `>= 0`.
- All `age_ms` values are `>= 0`.
- All status values are in `_ALLOWED_FRESHNESS_STATUSES`.
- All feature names are non-empty strings.
- The three tuples are not all empty (`FreshnessMetadata` with zero
  features is invalid; the active model always consumes at least one
  feature).

Violations raise `TrainerParityLineageError`.

## Lineage validator (`lineage_validator.py`)

Two pure functions:

- `validate_stage_a_lineage(record: StageATrainerRecord) -> None`
- `validate_stage_b_lineage(stage_b: StageBTrainerRecord,
  stage_a: StageATrainerRecord) -> None`

`validate_stage_a_lineage`:
- Confirms all lineage fields are non-empty (a defense-in-depth check
  beyond `__post_init__`): `prediction_id`, `feature_snapshot_id`,
  `symbol`.
- Raises `TrainerParityLineageError` on any violation.

`validate_stage_b_lineage`:
- Confirms `stage_b.prediction_id == stage_a.prediction_id`.
- Confirms `stage_b.feature_snapshot_id == stage_a.feature_snapshot_id`.
- Confirms `stage_b.symbol == stage_a.symbol`.
- Confirms `stage_b.signal_ts_ms >= stage_a.prediction_ts_ms`.
- Raises `TrainerParityLineageError` on any violation, with a structured
  reason string identifying which lineage edge failed (one of:
  `"prediction_id"`, `"feature_snapshot_id"`, `"symbol"`,
  `"signal_ts_ms_before_prediction_ts_ms"`).

Both functions are pure, side-effect free, and do no I/O.

## Explainability validator (`explainability_validator.py`)

Single pure function:

- `validate_stage_a_explainability(record: StageATrainerRecord) -> None`

Behavior:
- Confirms `confidence_explainability` is present (always true since
  the Stage A record requires it).
- Confirms `confidence_explainability.confidence_components` is a
  non-empty tuple.
- Confirms each component name is non-empty and contribution is finite
  (use `math.isfinite`).
- Confirms component names are unique.
- Confirms `calibration_model_version` and `calibration_method` are
  non-empty.
- Confirms `top_positive_features` and `top_negative_features` together
  cover at least one entry (otherwise the prediction has no
  attributable explainability).
- Confirms `source_key_references` is non-empty.
- Confirms `freshness_metadata` is present and not empty (Stage A
  invariant already enforces non-empty; this is defense-in-depth).
- Raises `TrainerParityLineageError` on any violation, with a
  structured reason string identifying which explainability rule
  failed.

## Errors (`errors.py`)

Single exception:

- `TrainerParityLineageError(ValueError)`

It carries `reason: str` and `field: str | None` attributes. Its
constructor signature is `__init__(self, reason: str, *, field: str |
None = None)`.

## Hard exclusions for Phase 2E1.B

- No subprocess / shell calls.
- No file I/O.
- No network.
- No Redis import or client construction.
- No legacy module import (no `legacy_reference.*`, no path injection
  to legacy bot, no reading of `/home/wali/Desktop/AI BOT`).
- No environment variable reads.
- No reliance on the subprocess adapter from Phase 2E1.A.
- No live trainer call.
- No model loading.
- No checkpoint loading.
- No GPU code.
- No async I/O. Domain layer is fully synchronous.
- No use of `time.time()` or `datetime.now()` inside the module
  (timestamps come in as int args).

## Cross-references

- Stage A field set is taken from
  `trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`
  Stage A bullet list. The `symbol` retention is justified inline
  under "Stage A field rationale" above.
- Stage B field set is taken verbatim from the same file's Stage B
  bullet list.
- Explainability bundle reference is
  `trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`
  "Mandatory legacy-preservation explainability field set".
- `FreshnessMetadata` per-feature shape is aligned to
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`
  "Freshness policy fields" (`freshness_status` enum is the source
  of `_ALLOWED_FRESHNESS_STATUSES`).
- Lineage rules are taken from
  `trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`
  "Integrity rules".

PHASE2E1B_TRAINER_PARITY_IMPL_DOMAIN_RECORD_SPEC_READY
PHASE2E1B_TRAINER_PARITY_IMPL_DOMAIN_RECORD_SPEC_REVISED

