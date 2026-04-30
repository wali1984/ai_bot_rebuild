# 05 Feature Flow Monitoring Plan

## Objective
Close feature-flow visibility gaps identified in prior audits.

## Required tracking dimensions
1. Ingestor key freshness
   - Track per-key/per-pattern freshness age and SLA status.
2. Feature key freshness
   - Track feature namespace freshness and stale/missing counts.
3. Trainer input `feature_snapshot_id`
   - Verify presence for each prediction-producing cycle.
4. Confidence movement causes
   - Capture top contributing positive/negative features and deltas.
5. Source Redis key/pattern references
   - Persist source key/pattern for each major feature used in decisioning.

## Evidence model
- Raw snapshots store freshness facts and source references.
- Hourly packet summarizes stale/missing/unused source distribution.
- Alert packet emitted on freshness SLA breaches or lineage gaps.

## Required outputs
- feature freshness matrix
- per-symbol stale key ledger
- `feature_snapshot_id` presence ratio
- confidence-cause attribution completeness ratio
