"""Direct Binance/KuCoin orderbook recorder primitives.

The package is public-market-data only. It never signs requests, never submits
orders, and only targets new ``v2:orderbook:*`` Redis keys plus local replay
files.
"""
from .features import build_orderbook_payloads
from .local_book import LocalOrderBook
from .providers import (
    build_binance_stream_names,
    build_kucoin_subscription_messages,
    parse_binance_message,
    parse_kucoin_message,
)
from .store import LocalReplayStore

__all__ = [
    "LocalOrderBook",
    "LocalReplayStore",
    "build_binance_stream_names",
    "build_kucoin_subscription_messages",
    "build_orderbook_payloads",
    "parse_binance_message",
    "parse_kucoin_message",
]
