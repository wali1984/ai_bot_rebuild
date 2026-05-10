# Exchange Connector Read-Only Policy

Allowed methods: fetch_account_status_readonly, fetch_balances_readonly, fetch_fills_readonly, fetch_funding_rate, fetch_market_candles, fetch_market_ticker, fetch_open_interest, fetch_open_orders_readonly, fetch_orderbook_depth, fetch_positions_readonly.

Forbidden mutation methods fail closed: cancel_order, change_leverage, change_margin, change_position_mode, create_order, enable_live_trading, transfer, withdraw.

No connector may place/cancel orders, change leverage, change margin, change position mode, withdraw, transfer, or enable live trading.

EXCHANGE_CONNECTOR_READONLY_POLICY_READY
