# V2 Paper Edge Recovery And Cost-Aware Trade Selection Report

Generated: `2026-05-15T11:04:24Z`

Result: `V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`

This report does not approve live, canary, or legacy shutdown.

Current paper runtime:
- paper runtime generated at: `2026-05-15T11:03:53Z`
- realized paper PnL: `-49.196177`
- unrealized paper PnL: `-0.012406`
- open paper position count: `1`
- edge status: `EDGE_PENDING_POSITION_OPEN`
- shadow outcome status: `BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED`
- shadow false blocks: `14`

Implemented controls:
- no paper fill without expected_move_after_cost_bps above threshold
- no paper fill without accepted trainer_source
- no paper fill without CURRENT feature freshness
- no paper fill outside paper symbol scope
- confidence alone cannot allow a fill
- missing cooldown/churn evidence fails closed
- missing reduce-only, intelligent close guard, or microstructure toxicity evidence fails closed
- paper-only position lifecycle now carries minimum hold, TP/SL/max-hold coordination, and protective behavior evidence

Remaining blockers:
- post-filter positive edge is not proven while the sample is small and/or a paper-only position remains open
- shadow false blocks require continued model review; future outcomes cannot be used to retroactively allow fills
- trainer derived evidence requires explicit operator acceptance for paper-only shutdown evaluation
- trade permission remains live/canary/operator-decision only

Safety:
- live_gate remains `blocked_human_only`
- live_symbols remains `[]`
- old Redis writes absent
- exchange actions absent
- final approval token absent
- Redis trim approval absent
