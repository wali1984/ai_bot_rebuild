# Legacy Failure Case - LAB Hedge Unwind / Short Squeeze Exposure

## Classification

Legacy trading/risk failure case.

## Summary

The legacy system opened or held short exposure near a local bottom and long exposure near a local top or hedge context. The LAB position became hedged. The system closed the long position around breakeven, leaving the short exposed. LAB then pumped approximately 80% against the remaining short.

## Why this matters

This is a high-priority failure case because the system removed protective exposure and left adverse directional exposure open.

## Observed failure pattern

- short exposure remained after hedge leg was closed
- protective long was closed at breakeven
- remaining short was exposed to a strong pump
- risk gateway did not block or reduce residual short exposure
- hedge unwind logic did not account for net exposure risk
- system likely ignored squeeze/liquidity/OI/regime context
- explanation/audit was insufficient

## V2 required behavior

V2 must not treat a hedge leg close as a simple break-even close. It must evaluate the remaining net position.

Before closing a protective hedge leg, V2 must check:

- current net exposure after close
- current trainer confidence
- confidence delta
- feature freshness
- liquidation cluster above/below
- open interest change
- orderbook imbalance
- funding/basis
- volatility expansion
- recent liquidity sweep
- local structure: top/bottom risk
- risk-gateway block state
- paper/shadow expected outcome

## Required V2 tests

Create replay/paper tests where:

1. Long hedge closes while short remains.
2. Price pumps strongly after hedge close.
3. V2 risk gateway must either:
   - keep hedge,
   - reduce short,
   - close short,
   - block hedge close,
   - or mark the action as unsafe.

## Required website visibility

Website must show:

- why the long was closed
- why the short remained
- whether the long was protective
- net exposure before/after close
- feature contributors behind confidence
- liquidity/OI/squeeze warnings
- risk decision ID
- execution intent ID
- paper/shadow alternate outcome
- PnL impact of hedge close vs hedge kept

## Safety

This is non-live evidence. Do not mutate legacy bot. Do not write Redis. Do not place/cancel orders.

LAB_HEDGE_UNWIND_FAILURE_CAPTURED
