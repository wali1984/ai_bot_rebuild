# Passive Market Discovery and Adaptive Selection

## Requirement ID
V2-PASSIVE-DISCOVERY-ADAPTIVE-SELECTION-001

## Scope
The system must ingest/observe all available coins from:
- Binance Futures
- CoinAnk
- CoinAPI
- KuCoin
- any future futures exchange connector
- any additional ingestor added later

## Universe layers (mandatory)

### 1. Available Universe
- every coin/instrument known from exchanges/ingestors
- passive metadata only
- not necessarily trained or traded

### 2. Observed Universe
- coins monitored for status, liquidity, volatility, funding, open interest, spread, volume, news/technical/flow/liquidation factors
- read-only passive monitoring

### 3. Training Universe
- dynamically selected coins for trainer/model updates
- based on scoring and system capacity
- hot-reloadable without full service restart

### 4. Trading Universe
- subset approved for paper/live trade consideration
- stricter gates than training universe
- risk gateway final authority

## Per-symbol tracking schema (required)
For every symbol, V2 must track:
- symbol
- exchange
- market type
- base/quote asset
- available from which ingestors
- data completeness score
- liquidity score
- spread score
- volatility score
- funding score
- open interest score
- order book depth score
- liquidation activity score
- technical/regime score
- feature freshness score
- model confidence history
- paper performance
- live eligibility
- train_enabled
- trade_enabled
- paper_only
- live_allowed
- manual_override_state
- override_reason
- last updated time

## Dynamic selection engine (required)
- ranks all available coins
- selects training symbols based on score/capacity
- selects trading candidates based on stricter risk/performance criteria
- supports manual include/exclude
- supports force train-only, force paper-only, force disabled
- all changes versioned and audited
- hot-reload event emitted on changes
- no full system restart required

## Manual override governance (required)
- admin can add/remove/modify symbols in GUI
- override must show who changed it, when, why, risk level, and rollback value
- dangerous overrides require confirmation

## Safety and rollout constraints
- Trading Universe admission is blocked until required risk/readiness gates pass.
- Risk Gateway remains the final authority even after selection/admission.
- Passive discovery never implies auto-live enablement.

## Pre-architecture acceptance
- Four-layer universe model is implemented in requirements baseline.
- Dynamic selection + manual override governance are fully specified.
- Restart-free propagation and audit requirements are explicitly tied to requirement 14.
