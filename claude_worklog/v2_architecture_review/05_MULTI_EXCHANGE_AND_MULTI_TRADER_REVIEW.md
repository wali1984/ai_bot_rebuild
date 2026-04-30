# 05 Multi-Exchange and Multi-Trader Review

## Scope
Verify passive coverage of all required market sources, multi-exchange connector pluggability with Binance Futures first, and multi-trader fleet support.

## Inputs
- Architecture: 02, 03, 07, 09, 10
- Requirements: 12, 13, 19

## Passive observation coverage
Architecture file 07 explicitly lists the following observation sources:
- Binance Futures
- CoinAnk
- CoinAPI
- KuCoin
- future futures exchanges
- future ingestors

Requirement 19 lists exactly the same six sources. Lists match.

## Connector interface
Mandatory methods (per requirement 12 and architecture 09):
- `list_symbols`
- `get_symbol_metadata`
- `get_ohlcv`
- `get_orderbook`
- `get_funding`
- `get_open_interest`
- `get_account_state`
- `create_order`
- `cancel_order`
- `set_leverage`
- `set_margin_mode`

Both files list all 11 methods identically.

## Pluggable rollout
- Architecture 09: "Binance Futures is first connector. Additional futures exchanges are pluggable without rewriting core services."
- Requirement 12: Initial rollout = Binance Futures reference; "Additional futures connectors integrated via same interface without core platform rewrite."
- Database schema 03 encodes this via `exchanges`, `exchange_connectors`, `exchange_symbols` with capability metadata, allowing adding new exchanges by data not code-rewrite.

## Mutation safety
- Architecture 09 and requirement 12 keep `create_order/cancel_order/set_leverage/set_margin_mode` blocked until live readiness gates pass.
- Architecture 05 confirms: "Live mutation routes return blocked status by default until readiness gates pass."

## Connector standards
- Capability declaration per connector — covered in 09 and 12.
- Unified error model — covered in 09 and 12.
- Health heartbeat per connector instance — covered in 09 and 12; persisted via `heartbeat_events` (03).
- Audit envelope with redaction — covered in 09 and 12; persisted via `audit_events` (03).
- Secrets server-side only — covered in 12 and 15.

## Multi-trader fleet
Architecture file 10 specifies fleet support with mandatory trader instance fields, matching requirement 13:
- `trader_id`
- `account_id`
- `exchange_id`
- `strategy_profile`
- `symbol_scope`
- `risk_profile`
- `paper_live_mode`
- `assigned_symbols`
- `heartbeat`
- `pnl`
- `attribution_completeness`

All fields are persisted in `trader_instances` and `trader_assignments` (03).

## Fleet controls
- Dynamic add/remove of trader instances — covered.
- Capacity-aware assignment and sharding — covered.
- Per-trader paper/live mode with safe defaults — covered.
- Heartbeat SLA, stale detection, quarantine, recovery — covered (10 + 13).
- Per-trader attribution completeness — covered (architecture 10 + database 03).

## Risk Gateway authority over fleet
- Architecture 10: "Risk Gateway remains final authority for allow/block of execution intents."
- Requirement 13: "Trader cannot bypass Risk Gateway."
- Architecture 12: "No trader/fleet/exchange path may bypass Risk Gateway."

The non-bypass guarantee is consistent across all three artifacts.

## Verdict
- Passive coverage of all six required market sources is mandated.
- Connector interface is pluggable; Binance-first explicit.
- Multi-trader fleet schema, controls, and risk authority are complete.
