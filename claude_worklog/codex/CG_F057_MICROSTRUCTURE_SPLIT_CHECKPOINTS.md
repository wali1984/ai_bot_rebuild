# CG-F057 microstructure split — 2 check-points for Codex

Codex is implementing CG-F057 in v2_paper_provisional_prediction_publisher.py (good:
MICRO_ACTIONS_AUTHENTICATED_MARKET_STATE split + microstructure_publication_rejection_reasons
+ microstructure_continuous_estimates + double-GET readback). Two gaps my design+verification
found (both were also gaps in Claude's parallel impl — now discarded as redundant):

## 1. Feed-integrity coverage
microstructure_publication_rejection_reasons checks `evidence_valid` but not
`feed_integrity_pass`. They are SEPARATE signals: evidence_valid = envelope hash/schema OK;
feed_integrity_pass (trust_score.py:142, from :343-348) = the feed itself is trustworthy.
A feed-degraded SHADOW_ONLY/NO_TRADE (~0.24 fail_closed cap) has evidence_valid=True but
feed_integrity_pass=False and should be HARD-REJECTED (integrity, not honest-adverse) for
ALL publishable actions — read source_payload.feed_integrity_pass and reject when False.
(Distinguish from the sweep direction_uncertain 0.24 slice at :349-350, which keeps
feed_integrity_pass=True and SHOULD flow as valid-unfavorable.)

## 2. Consumer blend (else estimates are published but dropped)
adaptive_policy_shadow_v2.py sets expected_slippage/fill_probability/adverse_selection
(:1449-1452) but never reads microstructure_continuous_estimates. Wire them via a
COST-IDENTITY-PRESERVING blend at the create site (~:1304-1324):
  slippage = max(stats_slippage, micro.expected_slippage_bps)
  impact   = max(stats_impact,   micro.expected_market_impact_bps)   # both THROUGH ExpectedCostBreakdownV2
  fill_probability = min(stats_fill, micro.expected_fill_probability)
  adverse_selection = max(stats_adverse, micro.expected_adverse_selection)
record.py:947-950 requires expected_slippage==cost_breakdown.slippage_bps and
expected_market_impact==cost_breakdown.market_impact_bps — so the bps MUST flow through the
breakdown, not be set on the typed fields independently. Conservative (raises cost / lowers
fill) — strengthens survival/accounting.
