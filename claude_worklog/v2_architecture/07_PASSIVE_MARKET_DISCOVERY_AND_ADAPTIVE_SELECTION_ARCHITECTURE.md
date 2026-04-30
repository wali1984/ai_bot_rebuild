# 07 Passive Market Discovery and Adaptive Selection Architecture

## Universe layers
1. Available Universe
2. Observed Universe
3. Training Universe
4. Trading Universe

## Market observation coverage
System must observe all coins/instruments from:
- Binance Futures
- CoinAnk
- CoinAPI
- KuCoin
- future futures exchanges
- future ingestors

## Per-symbol tracked dimensions
- data completeness
- liquidity
- spread
- volatility
- funding
- open interest
- order book depth
- liquidation activity
- technical/regime score
- feature freshness
- model confidence history
- paper performance
- train_enabled
- trade_enabled
- paper_only
- live_allowed
- manual override state

## Adaptive engine behavior
- Rank all available coins.
- Select training universe by score + system capacity.
- Select trading universe using stricter risk/performance gates.
- Support manual include/exclude.
- All changes audited and versioned.
- No full restart required.

## Governance
- Manual overrides require actor, reason, risk level, rollback value.
- Dangerous overrides require explicit confirmation and approval.
- Risk Gateway remains final authority for trade-path admission.
