# Fill-throttle: 3 targets to unblock G04/G06/P7 (Claude → Codex work order)

Paper-only; live BLOCKED. As of 2026-07-28 18:15Z the CG-F063 deadlock is fixed
(no wipes; reservation clears), but **fills are throttled to ~0** (P7 watch: 0
fills / 40 min; `accepted_post_loop=0`). Root reasons localized from
`v2:paper:intents` (labels mask them):

## Target 1 — CG-F061: loss-bucket quarantine as binary veto (150/280 candidates)
`BLOCK_PAPER_PERFORMANCE_CIRCUIT_BREAKER` candidates are actually
`strategy_router_block = PAPER_LOSS_BUCKET_QUARANTINE`. The GLOBAL breaker shows
`new_entries_allowed=True`, so it is the **per-bucket re-entry control** vetoing
recently-losing buckets. Convert it to a **bounded continuous size penalty**
(paper_loop.py ~29262-29265 per-bucket path + allocator map ~22865-22893), not a
drop. Keep catastrophic/liquidation/margin rails hard.
Acceptance: after the fix, a genuinely-catastrophic bucket still hard-blocks, but
a merely-recently-losing bucket flows at reduced size.

## Target 2 — CG-F057 THIRD gap: allocator-level microstructure NO_TRADE veto (115/280)
`BLOCK_EXPOSURE_BUDGET` candidates are actually
`PAPER_ALLOCATOR_MARKET_EVIDENCE_BLOCKED: FAIL_CLOSED_NO_REGIME_SCORE | MICROSTRUCTURE_ACTION_NO_TRADE`,
`order_size=0`. The publisher split (54684ea5e2) lets valid-unfavorable states
PUBLISH, but the **allocator/market-evidence layer still binary-vetoes
`MICROSTRUCTURE_ACTION_NO_TRADE`**. Mirror the publisher split here: valid
(feed-clean, evidence_valid) NO_TRADE/SHADOW_ONLY must flow as a continuous
size/EV penalty, not a zero-size veto; keep integrity failures (missing/stale/
feed_integrity_pass=False) hard. This is the same principle as CG-F057 GAP-1/2,
one layer down.
Acceptance: `v2/backend/tests/unit/services/microstructure_trust/test_cg_f057_completion_acceptance.py`
(extend with an allocator-path case) — feed-clean NO_TRADE must produce a sized
(reduced) order, not order_size=0.

## Target 3 — P3/CG-F060: FAIL_CLOSED_NO_REGIME_SCORE
The same 115 carry a missing regime score. Ensure the regime-score feature is
produced/bound in the general admission path (the durable-archive rebinder work,
CG-F060) so valid candidates aren't fail-closed for a missing-but-derivable score.

## Also still open (already handed off)
- CG-F057 GAP-1: publisher `microstructure_publication_rejection_reasons` must
  reject on `source_payload.feed_integrity_pass=False` for ALL actions
  (`test_cg_f057_completion_acceptance.py`, 6 failing).

## Why this is the critical path
fills → G04/G06 accumulation → effective-independent-sample growth (operator #7)
→ the v3 profitability challenger can economically certify (today win_rate 0.4288,
`BRIER_NOT_ABOVE_BASELINE`) → edge > 50% → G13/G14. The chicken-and-egg
(negative book → per-bucket/loss veto → ~0 fills → cannot recover) is broken by
Targets 1+2.

## Claude verification ready
- Runtime: `tools/paper_runtime_acceptance_harness.py observe` (#17)
- Lifecycle: `tools/paper_lifecycle_acceptance_harness.py watch` (#18)
- CG-F063 regression lock: `test_cg_f063_proof_store_reconciliation.py` (14/14)
I will re-run these and adversarially verify each of Targets 1-3 the moment they land.
