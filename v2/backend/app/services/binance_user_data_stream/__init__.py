"""Read-only Binance USD-M futures user-data (account) WebSocket stream.

This package consumes the Binance USER DATA STREAM (listenKey push) to keep a
live, read-only mirror of the account: balances, positions, open orders, margin
calls, and leverage/margin-mode config changes. It NEVER submits, cancels, or
modifies orders, and it never changes leverage or margin mode — a user-data
stream is inbound-only and cannot place trades. Order execution stays behind the
existing risk gateway + superadmin live-gate approval flow; this module is the
account-visibility half of the gated live adapter and is safe to run against a
$0, read-only account.
"""
from .service import (
    READ_ONLY,
    PLACES_REAL_ORDER,
    UserDataAccountModel,
    UserDataStreamStatus,
    BinanceUserDataStreamClient,
    derive_user_data_ws_base,
    normalize_account_update,
    normalize_order_trade_update,
    normalize_margin_call,
    normalize_account_config_update,
)

__all__ = [
    "READ_ONLY",
    "PLACES_REAL_ORDER",
    "UserDataAccountModel",
    "UserDataStreamStatus",
    "BinanceUserDataStreamClient",
    "derive_user_data_ws_base",
    "normalize_account_update",
    "normalize_order_trade_update",
    "normalize_margin_call",
    "normalize_account_config_update",
]
