# Microstructure Trust — Implementation Guide (Developer)

Last verified: 2026-07-07 00:15 EST | Tests: `v2/backend/tests/unit/services/microstructure_trust/` (29)

## Data flow
```
v2_direct_orderbook_recorder (per-venue WSS children, batches of 8 symbols)
  -> Redis v2:orderbook:{top,depth,features}:{exchange}:{SYM}  (TTL 5-30s)
  -> replay JSONL v2/runtime/orderbook_replay/{exchange}/{SYM}/{date}/{hour}/features.jsonl
v2_microstructure_runtime_supervisor (systemd, managed-until-stopped)
  -> spawns binance children + kucoin children (--direct-kucoin, default on)
  -> restart-exited-children keeps windows continuous
v2_microstructure_feed_quality_monitor (systemd, 2s loop)
  -> _read_replay_snapshots (last 24 rows) + live Redis payload
  -> compute_orderbook_adversarial_features (per exchange)  <- F-0010 stratification here
  -> _combine_adversarial (venue-evidence isolation)
  -> score_microstructure_trust -> v2:microstructure:trust_score:{SYM}:{tf}
consumers: allocator microstructure gate (paper loop), A+ gate, market-state integrity
```

## F-0010 stratification contract (orderbook_adversarial_features.py)
- `_stratum_key(row)` = `depth_level:{n}` (fallback `update:{type}`)
- `_select_depth_stratum(rows)` -> (rows, stratum, insufficiency|None); deepest
  stratum with >= MIN_STRATUM_SAMPLES (5) wins. ALL depth-series metrics
  (persistence, add/cancel, collapse, pulls, stuffing rate) run on ONE stratum.
- Persistence: window_ms if min(total)>=0.55*max(total) else 0, with
  `depth_persistence_reason` one of STABLE_DEPTH_WINDOW | DEPTH_UNSTABLE |
  INSUFFICIENT_DEPTH_WINDOW | MISSING_DEPTH_FIELDS. Never emit a bare 0.0.
- Score = min(1, persistence_ms/5000) in trust_score.py (weights 0.25/0.12).

## Combiner rules (_combine_adversarial, monitor)
- Adversarial risk scores: worst-case max across venues.
- Persistence: min ONLY across venues with evidence (reason in {None, STABLE,
  UNSTABLE}); venues without evidence go to `depth_persistence_unavailable_exchanges`
  and cannot zero out real evidence. Two evidenced venues -> conservative min.

## Cross-venue (cross_venue_confirmation.py)
`venues_present<=1` => baseline 0.25, `single_venue_unconfirmed` — cannot pass.
Divergence/depth-disagreement/imbalance-conflict subtract; tape + correlated move
add small confirmations. KuCoin symbol mapping: `kucoin_v2_symbol_to_futures`
(BTCUSDT->XBTUSDTM); keys written back under the V2 symbol name.

## Extending
- New venue: add provider in orderbook_recorder/providers.py, extend supervisor
  plan builder (see kucoin_symbols param), add coverage to the matrix artifact.
- New trust component: add to adversarial features WITH a reason field, wire
  through trust_score composite + status.py hard-fail checks, add tests for the
  missing-evidence path (must fail closed with a named reason).

## Invariants under test
- mixed 5/10/20 strata never pin persistence to 0 (regression for F-0010)
- non-positive alt-data liquidity never vetoes orderbook evidence (P-0001)
- binance-only symbols cannot fake cross-venue pass
- REDUCED_SIZE never counts as final A+ (status.py hard fail)

## Purpose
Guide developers extending microstructure trust without weakening fail-closed semantics, cross-venue confirmation, or REDUCE_SIZE/A+ separation.

## Source Files
- `v2/backend/app/services/microstructure_trust/orderbook_adversarial_features.py`
- `v2/backend/app/services/microstructure_trust/trust_score.py`
- `v2/backend/app/services/microstructure_trust/status.py`
- `v2/backend/tests/unit/services/microstructure_trust/`

## Runtime Redis Keys/API Routes
- Redis: `v2:orderbook:depth:{exchange}:{SYMBOL}`
- Redis: `v2:microstructure:trust_score:{SYMBOL}:{timeframe}`
- API: `/api/v2/paper/runtime-status`

## Failure Modes
- Missing depth evidence emits a bare zero without an explicit reason.
- Single venue confirmation passes as final A+ trust.
- Public orderbook defaults to trusted.

## Debug Commands
- `redis-cli --scan --pattern "v2:orderbook:depth:*" | wc -l`
- `redis-cli GET v2:microstructure:trust_score:BTCUSDT:1m | python3 -m json.tool`

## Validation Commands
- `python -m py_compile v2/backend/app/services/microstructure_trust/*.py`
- `.venv/bin/pytest -q v2/backend/tests/unit/services/microstructure_trust`

## Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_C_F0010_MICROSTRUCTURE_REVALIDATION.json`

