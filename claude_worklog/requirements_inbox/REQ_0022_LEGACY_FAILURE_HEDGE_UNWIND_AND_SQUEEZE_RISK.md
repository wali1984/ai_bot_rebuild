# Requirement 0022 - Legacy Failure: Hedge Unwind and Short Squeeze Risk

## Objective

V2 must learn from the LAB hedge-unwind failure where the legacy bot closed the protective long around breakeven and left a short exposed before an approximately 80% pump.

This requirement supports the paper/backtest MVP path.

## Required lane

`paper_backtest_mvp`

## Required MVP relevance

This must feed:

- trainer prediction output
- orchestrator decision
- risk gateway default-deny
- paper execution ledger
- replay/backtest runner
- paper mode
- shadow comparison
- decision explainability UI

## Required risk-gateway rules

Before closing a hedge/protective leg, V2 must evaluate:

- remaining net exposure
- whether the closed leg was reducing risk
- whether residual position becomes naked directional exposure
- current confidence and confidence delta
- feature_snapshot_id freshness
- OI/funding/liquidation/squeeze context
- orderbook/spread context
- local top/bottom / liquidity sweep risk
- stale/missing/unused feature flags
- expected paper/shadow risk

If risk increases materially, default behavior must be:

- block close,
- require reduce-only action,
- keep hedge,
- close/reduce dangerous residual exposure,
- or send to human approval in live-gate context.

## Required replay/backtest case

V2 must include a replay/backtest scenario for:

- hedged LAB-like position
- long hedge closed around breakeven
- remaining short exposed
- strong adverse pump
- compare outcomes:
  - legacy action
  - keep hedge
  - close short
  - reduce short
  - block hedge close

## Required explainability

V2 must explain:

- why the hedge close was allowed or blocked
- why the residual short was allowed or blocked
- which features contributed
- which risk checks passed/failed
- what alternate paper/shadow outcome would have occurred

## Forbidden

Do not modify `/home/wali/Desktop/AI BOT`.
Do not write Redis.
Do not restart live services.
Do not place/cancel orders.
Do not enable live trading.

REQ_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK_READY
