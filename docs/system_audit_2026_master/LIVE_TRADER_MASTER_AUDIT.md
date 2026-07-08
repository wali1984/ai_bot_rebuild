# Live Trader / Live Gate Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## Live Trader Status

**live_trader_currently_down_or_blocked**: TRUE — BLOCKED by design

**places_real_order**: FALSE
**places_test_order**: FALSE
**can_change_leverage**: FALSE
**can_change_margin_mode**: FALSE

## Live Gate State (from `v2:live_gate:state`)

```json
{
  "live_gate": "blocked_human_only",
  "live_trading_enabled": false,
  "live_blocked": true,
  "order_transport_submit_enabled": false,
  "order_transport_write_guard_enabled": true,
  "kill_switch_active": false,
  "kill_switch_enabled": true,
  "operator_approved": false,
  "operator_approval_required": true,
  "max_leverage": 1.0,
  "leverage_mutation_allowed": false,
  "margin_mutation_allowed": false,
  "places_real_order": false,
  "exchange_action_taken": false,
  "old_redis_write_allowed": false,
  "redis_trim_allowed": false,
  "legacy_restart_allowed": false,
  "release_mode": "NON_LIVE",
  "reason": "Pass 1A release gate: live submit disabled before paper/shadow validation",
  "generated_est": "2026-06-12T17:59:32-04:00"
}
```

**Note**: This state is intentionally stale (generated 2026-06-12). The orchestrator reports it as stale (age > 1.6M seconds). This is by design — the live gate state must be refreshed by an operator action before live can be enabled.

## Why Live Is Down (Current Blockers)

From orchestrator heartbeat, 5 live gate blockers:

| Blocker | Description |
|---------|-------------|
| LIVE_GATE_NOT_ENABLED | live_gate ≠ live_enabled |
| TRADER_EXECUTION_ENABLED_NOT_TRUE | order_transport_submit_enabled = false |
| LIVE_SYMBOL_SETS_DO_NOT_MATCH_ACCEPTED_SYMBOLS | No live symbols configured |
| ORDER_TRANSPORT_SUBMIT_NOT_ENABLED | Submit guard active (write guard enabled) |
| LIVE_GATE_RUNTIME_STATE_STALE | State age > 3600s (intentionally stale) |

## Live Canary (DRY RUN Only)

The live canary timer (`ai-bot-v2-live-canary-dry-run.timer`) runs every 60 seconds but uses **FakeExchangeAdapter only** — no real orders placed. This is purely for testing the code path without exchange mutation.

The canary scripts:
- `v2_live_canary_executor.py` — dry run only
- `run_pass3a_live_canary_safety_dry_run.py` — safety validation dry run
- `run_pass3b_exact_live_path_dry_run.py` — live path dry run
- `run_pass3c_tiny_live_canary_readiness_check.py` — canary readiness

## Exchange Credentials
- **credential_present_boolean_only**: true (Binance API keys present in env)
- **credential_value_exposed**: FALSE (not shown here)
- **signed_read_status**: Not surfaced in current heartbeat

## Available Margin / Open Orders
- Not readable without exchange API call (read-only audit)
- `v2_binance_readonly_probe` service can check signed account data

## Pre-Submit Checks (would apply if live were enabled)
1. live_gate = live_enabled (NOT MET)
2. order_transport_submit_enabled = true (NOT MET)
3. live symbols list non-empty (NOT MET)
4. kill switch not active (MET — kill switch enabled but not active)
5. operator_approved = true (NOT MET)
6. Exchange filters satisfied (min notional, lot size)
7. Margin sufficient for position

## What Would Be Required Before Live

### Engineering Requirements
- [ ] Live gate state refreshed to non-stale (operator run `v2_operator_runtime_truth_publisher` with live gate update)
- [ ] order_transport_submit_enabled set to true by operator
- [ ] Live symbols list configured and matching accepted_symbols
- [ ] Exchange API credentials verified for trading (not just read)
- [ ] Binance USDM adapter binding confirmed (v2_binance_usdm_adapter)

### Operator Approval Requirements
- [ ] Explicit human approval via `v2:live_gate:state` update
- [ ] Operator review of paper trading performance (currently -$253 realized, feedback quarantined)
- [ ] A-grade gate must be PASS (continuous_edge_guardian)

### Performance Requirements
- [ ] Paper trading profit demonstrated over meaningful sample size
- [ ] Trainer feedback loop repaired (currently 100% quarantined)
- [ ] Win rate and profit factor above minimum thresholds

## Current Operator Required Actions
1. Do NOT enable live trading
2. Investigate trainer feedback quarantine (741/741 rows quarantined)
3. Investigate paper trading negative PnL (-$253.49)
4. Repair feedback loop before re-evaluating live readiness
