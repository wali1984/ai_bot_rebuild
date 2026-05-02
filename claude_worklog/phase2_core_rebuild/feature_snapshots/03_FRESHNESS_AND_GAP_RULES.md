# Freshness and Gap Rules

Freshness:
- Source timestamps are compared to snapshot `generated_ts`.
- Each source has `max_age_ms`.
- Features mapped to stale sources are listed in `stale_features`.

Gaps:
- Required trainer features missing from payload are listed in `missing_features`.
- Payload features not used by the current trainer contract are listed in `unused_features`.
- `lineage_gap_reason` records why a snapshot cannot be fully attributed.

FRESHNESS_AND_GAP_RULES_READY
