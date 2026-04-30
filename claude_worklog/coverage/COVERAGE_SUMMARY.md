# Coverage Summary

Decision: **GO**

## Metrics
- total_files: 25963
- total_code_files: 806
- total_scripts: 954
- classified_scripts: 957
- unsafe_unknown_count: 0
- unsafe_unknown_canonical_label: unsafe_unknown
- tier_a_count: 701
- exchange_action_files: 574
- redis_writer_files: 873
- runtime_mapped_count: 30
- unmapped_bot_looking_runtime_processes: 0
- exchange_script_files_unclassified: 0
- unknown_exchange_use_count: 0
- blocking_unknown_exchange_use_count: 0
- exchange_unresolved_tier_a_review_count: 1361
- exchange_unresolved_missing_tier_a_plan_count: 0
- decision: GO

## Taxonomy
- Canonical unknown-risk class: `unsafe_unknown`.
- Legacy alias handling is normalized to `unsafe_unknown` during gap detection.

## Missing artifacts

## NO-GO reasons

## Gate rationale
- GO for Claude Phase 1 rerun because unresolved exchange logic is evidence-backed and queued for Tier A raw review.
