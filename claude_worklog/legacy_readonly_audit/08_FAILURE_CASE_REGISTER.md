# Legacy Failure Case Register

Generated: 2026-05-06T21:40:18.164932+00:00

## 2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md

- path: `/home/wali/Desktop/AI BOT REBUILD/claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

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
