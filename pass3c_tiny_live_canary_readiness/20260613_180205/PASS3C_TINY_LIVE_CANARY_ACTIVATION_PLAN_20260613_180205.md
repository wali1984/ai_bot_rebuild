# Pass 3C Tiny Live Canary Activation Plan: 20260613_180205

Generated: `2026-06-13T18:02:07Z`

Scope: activation planning and readiness only. No live trading was enabled and no order was submitted.

## Result

| Field | Value |
|---|---:|
| Readiness status | `PASS3C_BLOCKED_EDGE_INSUFFICIENT_SAMPLE` |
| Execution-validation canary acknowledged | `False` |
| Canary intent | `EXECUTION_PATH_VALIDATION_ONLY` |
| Strict critical failures | `0` |
| Recorded-state critical failures | `None` |
| Trusted predictions | `10` |
| Replay snapshots | `12` |
| MTF snapshots | `12` |
| Available futures balance | `0.0` |
| Minimum required balance | `5.0` |
| Submit allowed | `False` |
| Live order submitted | `False` |
| Exchange action taken | `False` |

## Pass status

| Gate | Status |
|---|---|
| Pass 1A live submit disarmed | complete |
| Pass 2A trusted prediction + replay + MTF | complete |
| Pass 2B edge framework | complete |
| Pass 2B edge result | `INSUFFICIENT_SAMPLE` |
| Pass 3A live-canary safety implementation | complete |
| Pass 3B exact live-path dry run | complete, blocked by insufficient available balance |

Pass 2B is still `INSUFFICIENT_SAMPLE`; any future live canary is execution-path validation only, not strategy or profitability validation.

## Current live-control state

```json
{
  "exchange_action_taken": false,
  "live_blocked": true,
  "live_canary_enabled": null,
  "live_gate": "blocked_human_only",
  "live_trading_enabled": false,
  "operator_approved": false,
  "order_transport_submit_enabled": false,
  "places_real_order": false,
  "release_mode": "NON_LIVE",
  "transport_order_submitted": false,
  "transport_writes_exchange_orders": false
}
```

## Tiny canary configuration

```json
{
  "balance": {
    "available_balance_usdt": 0.0,
    "insufficient": true,
    "min_notional_usdt": 5.0,
    "minimum_required_usdt": 5.0,
    "signed_read_available": true
  },
  "candidate": {
    "action": "long",
    "notional_usd": 5.0,
    "order_type": "MARKET",
    "quantity": 0.001,
    "reduce_only": false,
    "side": "BUY",
    "symbol": "BTCUSDT"
  },
  "config": {
    "allow_leverage_mutation": false,
    "allow_margin_mode_mutation": false,
    "allowed_symbols": [
      "BNBUSDT",
      "BTCUSDT",
      "ETHUSDT",
      "PAXGUSDT",
      "XAUTUSDT",
      "ZECUSDT"
    ],
    "live_canary_enabled": false,
    "max_daily_loss_usd": 10.0,
    "max_daily_orders": 3,
    "max_notional_usd": 10.0,
    "max_open_positions": 1
  }
}
```

## Blockers

```json
[
  {
    "reason": "PASS2B_EDGE_INSUFFICIENT_SAMPLE_ACK_REQUIRED",
    "status": "PASS3C_BLOCKED_EDGE_INSUFFICIENT_SAMPLE"
  },
  {
    "reason": "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
    "status": "PASS3C_BLOCKED_INSUFFICIENT_BALANCE"
  },
  {
    "reason": "HUMAN_OPERATOR_ARM_REQUIRED",
    "status": "PASS3C_BLOCKED_LIVE_CONTROL_NOT_ARMED"
  },
  {
    "reason": "RELEASE_MODE_NOT_LIVE_CANARY_APPROVED",
    "status": "PASS3C_BLOCKED_LIVE_CONTROL_NOT_ARMED"
  },
  {
    "reason": "ORDER_TRANSPORT_SUBMIT_DISABLED",
    "status": "PASS3C_BLOCKED_LIVE_CONTROL_NOT_ARMED"
  },
  {
    "reason": "LIVE_TRADING_DISABLED",
    "status": "PASS3C_BLOCKED_LIVE_CONTROL_NOT_ARMED"
  },
  {
    "reason": "LIVE_CANARY_DISABLED",
    "status": "PASS3C_BLOCKED_LIVE_CONTROL_NOT_ARMED"
  }
]
```

## Required human acknowledgements

- I understand Pass 2B did not prove trading edge.
- I understand this is an execution-path validation canary only.
- I accept that the tiny order can lose money.
- I confirm the notional cap.
- I confirm max daily loss.
- I confirm no leverage or margin mutation.
- I confirm kill switch tested.
- I confirm manual disarm command is ready.

## Go conditions

- strict verifier exit = 0
- recorded-state verifier exit = 0
- critical failures = 0
- active-stale count = 0
- trusted prediction/replay/MTF evidence present
- live position state machine passes
- exchange/local reconciliation passes
- no open position
- no unexpected open orders
- futures available balance >= required minimum
- symbol is allowlisted
- notional <= tiny cap
- daily orders below cap
- daily loss below cap
- kill switch clear
- human operator arm present
- release mode explicitly changed from NON_LIVE only during activation
- order_transport_submit_enabled explicitly true only during activation
- live_canary_enabled explicitly true only during activation
- no leverage mutation
- no margin mode mutation

## No-go conditions

- Pass 2B still insufficient and execution-validation acknowledgement missing
- insufficient futures available balance
- strict verifier nonzero
- recorded-state verifier nonzero
- active-stale > 0
- missing replay snapshot
- missing MTF snapshot
- exchange/local drift
- stale signed read
- unexpected open order
- existing open position
- unsupported symbol
- min notional/filter failure
- kill switch active
- human arm missing
- leverage mutation required
- margin mutation required
- any submit-enabled key unexpectedly armed before activation sequence

## Activation sequence (not run)

1. Do not run until every go condition is true and operator acknowledgements are recorded by an approved manual workflow.
2. Fund futures account externally if needed; the bot must not transfer or borrow funds.
3. Rerun ./run_pass3c_tiny_live_canary_readiness_check and require PASS3C_READY_FOR_OPERATOR_REVIEW.
4. Run strict verifier and recorded-state verifier one final time.
5. Use the approved operator workflow to arm live_canary_enabled=true, release_mode=LIVE_CANARY_APPROVED, and order_transport_submit_enabled=true only for the tiny canary window.
6. Run one tiny allowlisted canary order through the existing live transport.
7. Immediately verify exchange order status, open position, fees, and lifecycle record.
8. Disarm live submit after the canary window.

## Rollback / disarm checklist

- `cd v2 && ../.venv/bin/python -m v2.backend.app.cli.v2_live_submit_disarm --redis-url redis://127.0.0.1:6379/0 --reason pass3c_manual_disarm`
- `./run_pass3c_tiny_live_canary_readiness_check --redis-url redis://127.0.0.1:6379/0 --output-dir pass3c_tiny_live_canary_readiness`
- Use Binance read-only open-orders check for the canary symbol; do not cancel from this readiness command.
- Use Binance read-only positions/account check for the canary symbol.
- `./export_pipeline_trust_evidence --redis-url redis://127.0.0.1:6379/0 --output-dir pipeline_trust_evidence_pass3c`
- `./verify_pipeline_trust --input pipeline_trust_evidence_pass3c/<run> --output-dir pipeline_trust_evidence_pass3c/<run>/report --strict-unknown`
- `.venv/bin/python -m v2.backend.app.cli.run_recorded_state_verification --input pipeline_trust_evidence_pass3c/<run> --output-dir recorded_state_verification_pass3c/<run>`
- Inspect v2:live_order_transport:status, v2:live_gate:state, and v2:trader:execution_state.

## Safety result

- `live_canary_enabled` was not changed.
- `order_transport_submit_enabled` was not changed.
- `live_trading_enabled` was not changed.
- No approval token was created.
- No live order was submitted.
- No exchange state was mutated.
- No leverage or margin mode mutation was performed.
