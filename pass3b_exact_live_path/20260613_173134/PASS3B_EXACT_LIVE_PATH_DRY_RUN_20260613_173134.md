# Pass 3B Exact Live-Path Dry Run: 20260613_173134

Generated: `2026-06-13T17:31:35Z`

| Field | Value |
|---|---:|
| Status | `PASS3B_BLOCKED_INSUFFICIENT_AVAILABLE_BALANCE` |
| Candidate type | `ENGINEERING_CANARY_PROBE` |
| Candidate symbol | `BTCUSDT` |
| Candidate side | `BUY` |
| Candidate quantity | `0.001` |
| Candidate notional | `5.0` |
| Submit allowed | `False` |
| Final submit block reason | `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER` |
| Submit function called | `False` |
| Live order submitted | `False` |
| Places real order | `False` |
| Exchange action taken | `False` |
| Leverage changed | `False` |
| Margin mode changed | `False` |
| Pass 3C can be considered | `False` |

## Blockers

```json
[
  "ADAPTIVE_ALLOCATOR_BLOCK_INSUFFICIENT_MARGIN",
  "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
  "LIVE_CANARY:HUMAN_OPERATOR_ARM_REQUIRED",
  "LIVE_CANARY:LIVE_CANARY_DISABLED",
  "LIVE_CANARY:LIVE_TRADING_DISABLED",
  "LIVE_CANARY:NOTIONAL_NOT_POSITIVE",
  "LIVE_CANARY:ORDER_TRANSPORT_SUBMIT_DISABLED",
  "LIVE_CANARY:QUANTITY_NOT_POSITIVE",
  "LIVE_CANARY:RELEASE_MODE_NON_LIVE",
  "LIVE_CANARY_PREFLIGHT_BLOCKED",
  "LIVE_GATE_RUNTIME_NOT_ENABLED",
  "LIVE_ORDER_TRANSPORT_SUBMIT_NOT_ENABLED",
  "ORDER_QUANTITY_NOT_POSITIVE"
]
```
