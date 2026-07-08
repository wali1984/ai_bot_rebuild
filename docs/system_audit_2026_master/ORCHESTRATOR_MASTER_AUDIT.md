# Orchestrator Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## What the Orchestrator Does

The orchestrator (**v2_orchestrator_arbitration_loop**) is the component that:
1. Reads ALL prediction keys from Redis (`v2:prediction:{sym}:{tf}`)
2. Arbitrates among competing predictions to select the strongest signal per symbol/side bucket
3. Routes selected signals to the risk gateway and paper trader
4. Manages the paper fill gate (holds intents if gate is active)

## Runtime Status (from `v2:orchestrator:heartbeat`)

```json
{
  "worker_id": "v2_orchestrator_arbitration_loop",
  "schema_version": "v2_orchestrator_arbitration_live_v1",
  "started_at": "2026-07-01T22:59:08Z",
  "finished_at": "2026-07-01T22:59:14Z",
  "predictions_seen": 393,
  "proposals_arbitrated": 393,
  "predictions_held_by_paper_fill_gate": 0,
  "bucket_winners_count": 130,
  "stale_proposal_count": 0,
  "deconflict_reason": "OPPOSITE_SIDES_DOMINANT_CONFIDENCE_WINS",
  "deconflict_selected_side": "short",
  "classification": "V2_ORCHESTRATOR_PRODUCTION_OK",
  "live_gate": "blocked_human_only",
  "approves_live": false,
  "approves_legacy_shutdown": false,
  "cannot_bypass_risk_gateway": true,
  "writes_legacy_redis": false
}
```

## Inputs
- `v2:prediction:{sym}:{tf}` — all predictions from native trainer
- `v2:continuous_edge_guardian:a_grade_execution_gate` — A-grade signal quality gate
- `v2:paper:intents_held_by_paper_fill_gate` — intents currently held (feedback loop gate)
- Live gate state (from `v2:live_gate:state`) — always blocked_human_only

## Prediction Selection Algorithm

1. Groups predictions by (symbol, side) buckets
2. Within each bucket, selects winner by **highest confidence_calibrated**
3. Deconflict rule: if LONG and SHORT both have signals for same symbol → **OPPOSITE_SIDES_DOMINANT_CONFIDENCE_WINS** (higher confidence side wins)
4. Result: 393 predictions → 130 bucket winners per cycle (at audit time)
5. Stale predictions: 0 stale proposals — freshness filter active

## What It Refuses
- Malformed predictions (`skipped_malformed_prediction_count`: 0 at audit)
- Stale predictions (`stale_proposal_count`: 0 at audit)
- Predictions blocked by paper fill gate
- Does NOT bypass risk gateway (`cannot_bypass_risk_gateway`: true)

## How It Hands to Paper Trader
1. Orchestrator writes winners to `v2:orchestrator:decisions` (list of selected proposals)
2. Also writes `v2:signals:paper` for paper trader consumption
3. Paper trader reads from `v2:signals:paper` and `v2:orchestrator:decisions`
4. Risk gateway intercepts; paper trader only acts on risk-approved signals

## How It Would Hand to Live Trader
- NOT CURRENTLY ACTIVE
- If live gate were enabled: orchestrator would write to `v2:live_transport:orders` (currently write-guarded)
- Order transport submit is disabled via `order_transport_submit_enabled: false`
- Execution live symbols list is empty (`execution_live_symbols: []`)

## Conflict Handling
- LONG vs SHORT same symbol: confidence wins; lower side rejected
- Multiple timeframes same symbol/side: highest calibrated confidence wins
- Paper fill gate hold: intents queued, not routed

## Keys Written
- `v2:orchestrator:proposals`
- `v2:orchestrator:decisions`
- `v2:signals:paper`
- `v2:orchestrator:heartbeat`
