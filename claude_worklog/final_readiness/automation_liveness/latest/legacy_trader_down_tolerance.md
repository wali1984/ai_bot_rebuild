# Legacy Trader Down Tolerance

Generated: 2026-05-09T18:41:07.646803+00:00

- legacy_trader_intentionally_disabled: `True`
- legacy_trader_required_for_v2_build: `False`
- legacy_trader_required_for_live_cutover: `human_review_required_later`
- legacy_trader_down_should_not_block_non_live_rebuild: `True`
- legacy_trainer_and_ingestors_may_continue_as_readonly_evidence_sources: `True`

The legacy trader must not be restarted by automation. If trader execution evidence is needed for a comparison, record the comparison as missing evidence and continue non-live V2 build work.

LEGACY_TRADER_DOWN_TOLERANCE_READY
