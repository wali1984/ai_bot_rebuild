# Phase 2E1.B — Planner Spec Revision Note

This note records the planner-driven revision of the Phase 2E1.B spec
applied **before** the supervisor dispatched the 2E1.B implementer
task (056). It exists so the Codex review at 057 can verify both the
final spec and the rationale behind the revision.

## Why a revision was needed

The original `26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md` (initial draft)
described Stage A trainer-inference records. Cross-checking against
the two binding sources surfaced two divergences:

### Divergence 1 — `freshness_metadata` was missing

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`
  Stage A bullet list includes both:
    - `freshness_metadata`
    - `feature_freshness_envelope` (per-source freshness flags)
  These are two distinct fields.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`
  classifies `freshness_metadata` as part of the **mandatory legacy-
  preservation explainability field set**, with the description:
  "per-feature last-update timestamp, age in milliseconds, and
  freshness envelope flag aligned to
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`."
  Per the parity map, "missing any field is a hard observability
  validation failure."
- The initial 2E1.B draft only included `feature_freshness_envelope`
  and silently folded `freshness_metadata` into it.
- That fold is incorrect because:
    - `feature_freshness_envelope` is **per-source** (e.g., one entry
      per upstream Redis key / data source).
    - `freshness_metadata` is **per-feature** (one entry per feature
      variable consumed by the active model).
    - A source can produce many features. A feature can be derived
      from multiple sources. The two views are not interchangeable.

The revision reinstates `freshness_metadata` as a distinct Stage A
field carried by a new `FreshnessMetadata` value object, alongside
the existing `FeatureFreshnessEnvelope` value object.

### Divergence 2 — `symbol` was added to Stage A without contract justification

- The contract Stage A bullet list does **not** literally include
  `symbol`. The integrity rules section of the same contract states:
  "Cross-symbol linkage is invalid."
- Stage B explicitly includes `symbol` and the lineage validator must
  enforce `stage_b.symbol == stage_a.symbol`.
- `feature_snapshot_id` recommended composition (per
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`)
  begins with `symbol`, so symbol identity is implicitly bound to
  `feature_snapshot_id`. However, at the dataclass surface the symbol
  is not directly readable from the opaque `feature_snapshot_id`
  string, which makes validator-time cross-symbol detection
  impossible without storing `symbol` explicitly on the Stage A
  record.

The revision retains `symbol` on Stage A and inlines this
justification into the spec so the divergence from the literal
contract bullet list is documented and reviewable.

## What was revised

- `26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`
    - Adds `FreshnessMetadata` value object with field shape and
      invariants.
    - Lists `freshness_metadata` as a Stage A field (between
      `feature_status_flags` and `feature_freshness_envelope`).
    - Adds an explicit "Stage A field rationale" subsection
      explaining the `symbol` field's contract grounding.
    - Public surface goes from eight to nine names (adds
      `FreshnessMetadata`).
    - Adds a new module file `freshness_metadata.py` to the surface.
- `27_PHASE_2E1B_TEST_PLAN.md`
    - Adds `test_freshness_metadata.py`.
    - Updates `conftest.py` fixture set to include
      `valid_freshness_metadata()`.
    - Updates Stage A fixture to use the new fixture.
    - Updates `test_public_surface.py` expectation from eight to
      nine exported names.
    - Adds Stage A invariant tests for `freshness_metadata`.
- `29_PHASE_2E1B_GO_NO_GO_REQUEST.md`
    - References this revision note.
    - Notes that the implementer must use the revised 26 and 27.

## What was NOT revised

- `28_PHASE_2E1B_SAFETY_BOUNDARIES.md` — unchanged. Forbidden
  imports, forbidden write paths, and Codex stop conditions are
  identical regardless of the field set. The mode declarations and
  test isolation rules remain in force. The "Public surface of
  `__init__.py` exports more than the spec names" check now applies
  to nine names instead of eight; that count is read from the spec,
  not duplicated in the safety doc.

## Impact on supervisor tasks

- `056_trainer_parity_2e1b_implementation.json` — required output
  files now include `freshness_metadata.py` and
  `test_freshness_metadata.py`; the prompt is updated to enumerate
  nine public surface names and reference this revision note.
- `057_trainer_parity_2e1b_codex_review.json` — required check 9
  (public surface size) updates from eight to nine names and check 4
  adds `FreshnessMetadata` invariants.

## Hard stops respected

- No legacy file modified.
- No Redis access.
- No subprocess.
- No exchange action.
- No live behavior.
- No secret value emitted.
- No deployment.
- No legacy mutation.

PHASE2E1B_PLANNER_SPEC_REVISION_RECORDED

