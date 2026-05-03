# Requirement 0013 — Smart Money / Liquidity Features in Shadow Mode

## Objective

Add Smart Money Concepts, liquidity, positioning, and orderbook-derived features as an observation and scoring layer first.

These features must improve context, explainability, filtering, and shadow/paper evaluation before they are allowed to affect live or execution logic.

## Required phase order

Do not implement SMC execution logic directly.

Correct order:

1. external/manual position quarantine
2. provenance, dedupe, and attribution
3. degraded-state fail-closed gates
4. SMC/liquidity feature shadow mode
5. SMC/liquidity paper validation
6. SMC as risk-gated filter
7. only later, after proof, SMC-specific strategy logic

## Hard safety rules

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write Redis legacy keys.
- Do not restart live services.
- Do not place/cancel orders.
- Do not change leverage/margin.
- Do not enable live trading.
- Do not use SMC features to justify DCA, hedging, rescue trades, or risk-adds on manual/external positions.
- SMC features may inform alerts and shadow scoring only until validated.

## Feature families

The V2 feature layer should eventually support:

1. market structure
2. order blocks
3. fair value gaps / imbalance
4. liquidity sweeps
5. equal highs / equal lows
6. premium / discount zones
7. break of structure / change of character
8. volume confirmation
9. open interest change
10. long/short imbalance
11. liquidation clusters
12. orderbook imbalance
13. funding / basis
14. volatility expansion / compression

## Example deterministic features

SMC / structure:

- `smc_bos_bullish`
- `smc_bos_bearish`
- `smc_choch_bullish`
- `smc_choch_bearish`
- `smc_last_swing_high`
- `smc_last_swing_low`
- `smc_distance_to_swing_high_pct`
- `smc_distance_to_swing_low_pct`

Order blocks:

- `smc_nearest_bullish_ob_distance_pct`
- `smc_nearest_bearish_ob_distance_pct`
- `smc_inside_bullish_ob`
- `smc_inside_bearish_ob`
- `smc_orderblock_strength`

Fair value gaps:

- `smc_nearest_fvg_distance_pct`
- `smc_inside_fvg`
- `smc_fvg_direction`
- `smc_fvg_size_pct`

Liquidity:

- `smc_liquidity_sweep_high`
- `smc_liquidity_sweep_low`
- `smc_equal_highs_distance_pct`
- `smc_equal_lows_distance_pct`
- `liq_cluster_above_distance_pct`
- `liq_cluster_below_distance_pct`
- `liq_cluster_above_size`
- `liq_cluster_below_size`

Positioning / OI:

- `oi_change_1m_pct`
- `oi_change_5m_pct`
- `oi_price_divergence`
- `net_long_delta`
- `net_short_delta`
- `orderbook_bid_ask_imbalance`
- `orderbook_depth_above`
- `orderbook_depth_below`
- `spread_bps`

## Deterministic implementation policy

Do not use an LLM to look at charts and decide trades.

SMC must be deterministic feature computation from:
- OHLCV
- orderbook
- CoinAnk liquidation / OI / long-short data
- funding
- basis
- source freshness metadata

The system must compute numeric features, timestamps, freshness, source status, and confidence contribution.

## Required freshness / DQ gates

Every SMC/liquidity feature group must carry:

- `dq_smc_ok`
- `dq_smc_age_ms`
- `dq_liq_ok`
- `dq_liq_age_ms`
- `dq_oi_ok`
- `dq_oi_age_ms`
- `dq_orderbook_ok`
- `dq_orderbook_age_ms`

Features must be blocked or marked unusable if stale.

Bad behavior:
- “SMC says bullish, trade.”

Required behavior:
- “SMC context is bullish, data is fresh, liquidation map agrees, OI does not contradict, spread acceptable, risk gate passes.”

## Initial implementation mode

Initial mode must be shadow only:

- `smc_shadow_enabled = true`
- `smc_affects_execution = false`

Measure:
- PnL by SMC score bucket
- win rate by SMC score bucket
- loser reduction by SMC veto
- overtrading reduction
- performance by symbol/timeframe
- whether SMC would have avoided bad legacy trades

## Later filter mode

After shadow proof, SMC may veto poor-context trades.

Example:
- model says long
- SMC context score below threshold
- risk gateway skips or downgrades the trade

SMC must not create live trades by itself at this stage.

## Required modules when implemented

Future implementation may create:

- `features/smc_features.py`
- `features/liquidity_features.py`
- V2 feature snapshot integration
- SMC shadow audit scripts
- PnL-by-SMC-score analysis
- website panels for SMC/liquidity context

## Website visibility

The new website must eventually show:

- SMC context score
- liquidity cluster proximity
- OI/price regime
- FVG/order block proximity
- liquidity sweep detection
- feature freshness
- why SMC agreed/disagreed with trainer
- whether SMC vetoed or downgraded a paper/shadow signal
- PnL by SMC score bucket
- bad trades avoided by SMC filter in shadow/paper mode

## Required placement in roadmap

Implement only after:
- trainer parity foundations
- feature attribution foundations
- risk gateway foundation
- provenance/dedupe
- degraded-state fail-closed gates
- external/manual position quarantine

## Codex review

Codex must verify:
- no live execution logic added
- no Redis legacy writes
- no legacy bot mutation
- deterministic features only
- freshness/DQ gates included
- shadow mode first
- no SMC direct trade authority
- website explains feature causes clearly

REQ_SMC_LIQUIDITY_SHADOW_FEATURES_READY
