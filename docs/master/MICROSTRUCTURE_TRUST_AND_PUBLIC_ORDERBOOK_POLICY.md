# Microstructure Trust and Public Orderbook Policy

Last verified: 2026-07-07 00:15 EST (post F-0010 repair)
Source files: `v2/backend/app/services/microstructure_trust/{orderbook_adversarial_features,trust_score,cross_venue_confirmation,status}.py`, `v2/backend/app/cli/{v2_microstructure_feed_quality_monitor,v2_microstructure_runtime_supervisor,v2_direct_orderbook_recorder}.py`
Runtime keys: `v2:orderbook:{top,depth,features,health}:{binance|kucoin}:{SYMBOL}`, `v2:microstructure:trust_score:{SYMBOL}:{tf}`, `v2:microstructure:adversarial_features:{exchange}:{SYMBOL}`

## Purpose
Defines why the V2 system never trusts a public orderbook by default, how composite
microstructure trust is computed, and what that means for trade admission.

## Why public orderbook is not trusted by default
A public (unauthenticated) book feed can be spoofed, quote-stuffed, or thinned in
ways that mislead sizing and entry logic: painted walls that vanish before fill,
cancel bursts around sweeps, and venue-local anomalies that do not reflect the
tradable market. `public_orderbook_default_trust` is therefore hard-coded `LOW`;
trust must be EARNED per symbol from measured evidence, and every missing piece of
evidence fails closed (NO_TRADE or SHADOW_ONLY), never open.

## What depth persistence means
`book_depth_persistence_score` measures whether visible depth is REAL: does total
top-20 depth remain within 55% of its window maximum over an observed >=5s window
(`depth_persistence_ms / 5000`, capped 1.0)? Painted books collapse between
snapshots; persistent books do not.

Measurement contract (F-0010): the recorder subscribes to several partial-depth
streams per symbol (levels 5/10/20 on Binance, 5/50/increment on KuCoin). Depth
sums from different stream depths differ ~5x by construction, so the window is
STRATIFIED by `depth_level` and scored on the deepest stratum with >=5 samples.
Every score carries `depth_persistence_reason`:
- `STABLE_DEPTH_WINDOW` — evidence of persistent depth (score >0)
- `DEPTH_UNSTABLE` — real book variance >45% within stratum (honest low score)
- `INSUFFICIENT_DEPTH_WINDOW` — not enough samples; fail closed
- `MISSING_DEPTH_FIELDS` — depth fields absent/zero; fail closed

## What cross-venue confirmation means
A single venue can be locally manipulated. `cross_venue_confirmation_score`
compares Binance vs KuCoin mid-price divergence, depth disagreement, and
imbalance conflict. Two agreeing venues score >=0.5 (`venues_confirm`); a single
venue is capped low (`single_venue_unconfirmed`, baseline 0.25) and can NEVER
fake a pass. Symbols without KuCoin listing are recorded per symbol in
`F0010_cross_venue_confirmation_status.json` with reason
`KUCOIN_FUTURES_CONTRACT_NOT_LISTED` (currently 3/85: BICOUSDT, EPICUSDT, SYNUSDT).
A venue with no depth evidence cannot poison another venue's persistence via the
multi-exchange combiner; it is listed in `depth_persistence_unavailable_exchanges`.

## REDUCED_SIZE vs final A+
- `REDUCE_SIZE` (composite trust >= adaptive floor but < 0.65): paper-only
  bootstrap tier. Liquidity score is retained (reduced), sizing is a fraction of
  normal adaptive budget, outcomes NEVER count as A-grade evidence
  (`counts_as_a_grade_evidence=false`). Guarded by
  `REDUCED_SIZE_BOOTSTRAP_NOT_FINAL_A_PLUS` in `a_plus_trade_gate/service.py` and
  hard-fail `REDUCED_SIZE_APPEARS_AS_FINAL_A_PLUS` in `microstructure_trust/status.py`.
- Final A+ requires composite trust > 0.65 (adaptive minimum, never lowered),
  dual-venue confirmation or stronger non-book evidence, plus all A+ gate rows
  (rolling 100/300 trade windows, LCB win-rate/expectancy, stress suite).

## What blocks a candidate (in order)
1. Market-state integrity (missing critical feature family, staleness)
2. Expected edge after cost not favorable for side
3. Allocator: liquidity evidence (orderbook depth/spread derived; explicit scores
   must be positive) x microstructure trust gate (NO_TRADE zeroes, REDUCE_SIZE reduces)
4. Strategy/lifecycle, non-relaxable P0 entry gates
5. Risk gateway (exposure, drawdown, correlation, liquidation buffer)
6. Continuous edge guardian (A+ evidence thresholds)

## Debugging stale/missing trust
```bash
redis-cli GET v2:microstructure:trust_score:BTCUSDT:1m | python3 -m json.tool | head -40
# key fields: book_depth_persistence_score/_reason, cross_venue_confirmation_score,
#             feed_quality_fail_reasons, direct_orderbook_sources, adaptive_minimum
redis-cli --scan --pattern "v2:orderbook:depth:binance:*" | wc -l   # expect ~85
redis-cli --scan --pattern "v2:orderbook:depth:kucoin:*" | wc -l    # expect ~82
systemctl --user status ai-bot-v2-microstructure-runtime-supervisor.service
systemctl --user status ai-bot-v2-microstructure-feed-quality-monitor.service
ls -lt v2/runtime/orderbook_replay/binance/BTCUSDT/*/  | head    # replay freshness
```
Failure modes: supervisor down -> keys TTL out in ~30s -> BOOK_UPDATE_AGE_TOO_HIGH
fail-closed; replay files stale -> INSUFFICIENT_DEPTH_WINDOW; kucoin child dead ->
cross-venue degrades to single_venue_unconfirmed (honest, not fatal).

Evidence artifacts: `goal_state/V2_FULL_SYSTEM_END_TO_END_AUDIT_FIX_DOCUMENTATION_AND_GO_LIVE_READINESS_MASTER/F0010_*.json`

## Phase L Operator/Trader/Developer Meaning
- Operator: use trust reasons to distinguish honest fail-closed market truth from feed failure.
- Trader: treat `REDUCE_SIZE` as paper bootstrap only; it is not final A+ evidence.
- Developer: preserve named reasons for missing evidence and keep public orderbook evidence capped unless independently confirmed.

## Phase L Debug Commands
- `redis-cli GET v2:microstructure:trust_score:BTCUSDT:1m | python3 -m json.tool`
- `redis-cli --scan --pattern "v2:orderbook:depth:binance:*" | wc -l`
- `redis-cli --scan --pattern "v2:orderbook:depth:kucoin:*" | wc -l`

## Phase L Validation Commands
- `python -m py_compile v2/backend/app/services/microstructure_trust/*.py`
- `.venv/bin/pytest -q v2/backend/tests/unit/services/microstructure_trust`
- `python -m v2.backend.app.cli.v2_runtime_drift_monitor --write-status --write-redis`

## Phase L Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_C_F0010_MICROSTRUCTURE_REVALIDATION.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_K_RUNTIME_ALERT_MATRIX.json`

