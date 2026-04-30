# 12 Risk Gateway Architecture

## Authority
Risk Gateway is final authority for execution allow/block.

## Mandatory controls
- stale signal block
- missing attribution block
- duplicate execution block
- leverage/margin block
- stop policy block
- daily/weekly loss gate
- kill switch
- position sizing
- reduceOnly enforcement
- live trading gate

## Integration points
- receives orchestrator decisions
- evaluates policy bundles
- emits `risk_decision`
- gates execution intent generation

## Non-bypass guarantee
No trader/fleet/exchange path may bypass Risk Gateway.
