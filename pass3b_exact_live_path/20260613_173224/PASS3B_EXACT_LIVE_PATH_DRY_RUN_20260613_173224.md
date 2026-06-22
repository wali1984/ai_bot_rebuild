# Pass 3B Exact Live-Path Dry Run: 20260613_173224

Generated: `2026-06-13T17:32:25Z`

| Field | Value |
|---|---:|
| Status | `PASS3B_BLOCKED_INSUFFICIENT_AVAILABLE_BALANCE` |
| Evidence run | `pipeline_trust_evidence_pass3b/20260613_172929` |
| Recorded-state run | `recorded_state_verification_pass3b/20260613_172929` |
| Strict verifier exit | `0` |
| Recorded-state verifier exit | `0` |
| Critical failures | `0` |
| Active-stale count | `0` |
| Candidate type | `ENGINEERING_CANARY_PROBE` |
| Candidate symbol | `BTCUSDT` |
| Candidate side | `BUY` |
| Candidate quantity | `0.001` |
| Candidate notional | `5.0` |
| Signed read available | `True` |
| State machine allowed | `True` |
| State transition | `FLAT_TO_LONG_OPEN` |
| Exchange/local reconciled | `True` |
| Canary cap allowed | `False` |
| Lifecycle status | `READY` |
| Submit allowed | `False` |
| Final submit block reason | `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER` |
| Submit function called | `False` |
| Live order submitted | `False` |
| Places real order | `False` |
| Exchange action taken | `False` |
| Leverage changed | `False` |
| Margin mode changed | `False` |
| Pass 3C can be considered | `False` |

## Primary blockers

```json
[
  "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
  "REALISTIC_PREFLIGHT:RELEASE_MODE_NON_LIVE",
  "REALISTIC_PREFLIGHT:ORDER_TRANSPORT_SUBMIT_DISABLED",
  "REALISTIC_PREFLIGHT:LIVE_TRADING_DISABLED",
  "REALISTIC_PREFLIGHT:LIVE_CANARY_DISABLED",
  "REALISTIC_PREFLIGHT:HUMAN_OPERATOR_ARM_REQUIRED"
]
```

## Realistic candidate preflight blockers

```json
[
  "RELEASE_MODE_NON_LIVE",
  "ORDER_TRANSPORT_SUBMIT_DISABLED",
  "LIVE_TRADING_DISABLED",
  "LIVE_CANARY_DISABLED",
  "HUMAN_OPERATOR_ARM_REQUIRED"
]
```

## Raw transport blockers

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

## No-submit proof

- `submit_function_called=false` means the guarded submit function was not reached.
- `live_order_submitted=false`, `places_real_order=false`, and `exchange_action_taken=false` confirm no exchange mutation.
- `redis_write_attempts_blocked` records attempted runtime status/audit writes that were blocked by the read-only overlay.
