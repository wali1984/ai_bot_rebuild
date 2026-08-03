# Pass 3A Live-Canary Safety Report: 20260613_030432

Generated: `2026-06-13T03:04:32Z`

| Field | Value |
|---|---:|
| Submit allowed | `False` |
| Submit block reason | `RELEASE_MODE_NON_LIVE` |
| Live canary enabled | `False` |
| Order transport submit enabled | `False` |
| Live trading enabled | `False` |
| Places real order | `False` |
| Exchange action taken | `False` |
| Live order submitted | `False` |
| Trusted predictions | `10` |
| Replay snapshots | `12` |
| MTF snapshots | `12` |

## Preflight blockers

```json
[
  "RELEASE_MODE_NON_LIVE",
  "ORDER_TRANSPORT_SUBMIT_DISABLED",
  "LIVE_TRADING_DISABLED",
  "LIVE_CANARY_DISABLED",
  "HUMAN_OPERATOR_ARM_REQUIRED",
  "QUANTITY_NOT_POSITIVE",
  "NOTIONAL_NOT_POSITIVE",
  "ACTION_NOT_SUPPORTED",
  "SIGNED_READ_TIMESTAMP_MISSING",
  "HEDGE_MODE_MISMATCH",
  "HEDGE_MODE_DISABLED",
  "MARGIN_MODE_UNKNOWN"
]
```
