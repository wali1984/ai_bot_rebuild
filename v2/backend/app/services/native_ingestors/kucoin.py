"""V2 native KuCoin public market data ingestor (paper-only).

Pure stdlib config layer. Builds:

- public REST endpoint config
- public WSS connection request (no API key required)
- symbol mapping V2 <-> KuCoin
- reconnect/backoff classification

No network IO at module-level. No order/exchange mutation. No old
Redis writes. Only V2 namespace payloads.

Legacy citation:

- v2/legacy_owned_runtime/ingest/live_kucoin.py
    sha256=73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976
    size_bytes=36382
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

LEGACY_KUCOIN_SHA256 = "73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976"

KUCOIN_BASE_SPOT = "https://api.kucoin.com"
KUCOIN_BASE_FUTURES = "https://api-futures.kucoin.com"
KUCOIN_PUBLIC_WSS_TOKEN_PATH = "/api/v1/bullet-public"

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h")
DEFAULT_TICKER_PERIOD_S = 3
DEFAULT_KLINE_PERIOD_S = 60
DEFAULT_FUNDING_PERIOD_S = 60
DEFAULT_ORDERBOOK_PERIOD_S = 30

STATUS_NATIVE_V2 = "NATIVE_V2"
STATUS_BLOCKED_BY_NETWORK_OR_API = "BLOCKED_BY_NETWORK_OR_API"

RECONNECT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 60.0)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def v2_to_kucoin_spot_symbol(v2_symbol: str) -> str:
    """Map V2 symbol (e.g. ``BTCUSDT``) to KuCoin spot symbol (``BTC-USDT``)."""
    s = v2_symbol.upper()
    if "-" in s:
        return s
    if s.endswith("USDT"):
        return f"{s[:-4]}-USDT"
    if s.endswith("USD"):
        return f"{s[:-3]}-USD"
    if s.endswith("BTC"):
        return f"{s[:-3]}-BTC"
    return s


def v2_to_kucoin_futures_symbol(v2_symbol: str) -> str:
    """Map V2 symbol to KuCoin USDT-margined perpetual (``XBTUSDTM``-style)."""
    s = v2_symbol.upper()
    # KuCoin uses XBT instead of BTC for futures.
    if s.startswith("BTC"):
        s = "XBT" + s[3:]
    if s.endswith("USDT"):
        return f"{s}M"
    return s


@dataclass(frozen=True)
class KuCoinRestEndpoint:
    name: str
    method: str  # GET only for public market data
    base: str
    path: str
    requires_auth: bool = False


@dataclass(frozen=True)
class KuCoinWssRequest:
    """A WSS subscription request descriptor (not the live connection)."""
    topic: str
    private_channel: bool = False
    response: bool = True


@dataclass(frozen=True)
class KuCoinIngestorConfig:
    symbols_v2: tuple[str, ...]
    timeframes: tuple[str, ...]
    spot_endpoints: tuple[KuCoinRestEndpoint, ...]
    futures_endpoints: tuple[KuCoinRestEndpoint, ...]
    public_wss_topics: tuple[KuCoinWssRequest, ...]
    ticker_period_seconds: int
    kline_period_seconds: int
    funding_period_seconds: int
    orderbook_period_seconds: int
    reconnect_backoff_seconds: tuple[float, ...]
    generated_utc: str
    classification: str


def classify_reconnect_attempt(attempt_index: int) -> dict:
    """Classify the attempt: backoff value + label.

    First attempt is index 0 -> 1.0s. After the end of the backoff
    table, the value caps at the final entry but is classified as
    ``BACKOFF_SATURATED`` so the caller can decide between
    persistent-retry and bailout.
    """
    if attempt_index < 0:
        raise ValueError("attempt_index must be >= 0")
    if attempt_index < len(RECONNECT_BACKOFF_SECONDS):
        return {
            "attempt_index": attempt_index,
            "backoff_seconds": float(RECONNECT_BACKOFF_SECONDS[attempt_index]),
            "classification": "BACKOFF_NORMAL",
        }
    return {
        "attempt_index": attempt_index,
        "backoff_seconds": float(RECONNECT_BACKOFF_SECONDS[-1]),
        "classification": "BACKOFF_SATURATED",
    }


def build_public_rest_endpoints(spot: bool) -> tuple[KuCoinRestEndpoint, ...]:
    if spot:
        return (
            KuCoinRestEndpoint("ticker_all", "GET", KUCOIN_BASE_SPOT,
                               "/api/v1/market/allTickers"),
            KuCoinRestEndpoint("klines", "GET", KUCOIN_BASE_SPOT,
                               "/api/v1/market/candles"),
            KuCoinRestEndpoint("orderbook20", "GET", KUCOIN_BASE_SPOT,
                               "/api/v1/market/orderbook/level2_20"),
            KuCoinRestEndpoint("symbols", "GET", KUCOIN_BASE_SPOT,
                               "/api/v2/symbols"),
        )
    return (
        KuCoinRestEndpoint("contracts_active", "GET", KUCOIN_BASE_FUTURES,
                           "/api/v1/contracts/active"),
        KuCoinRestEndpoint("contract_detail", "GET", KUCOIN_BASE_FUTURES,
                           "/api/v1/contracts/"),  # +symbol
        KuCoinRestEndpoint("funding_current", "GET", KUCOIN_BASE_FUTURES,
                           "/api/v1/funding-rate/"),  # +symbol/current
        KuCoinRestEndpoint("klines", "GET", KUCOIN_BASE_FUTURES,
                           "/api/v1/kline/query"),
        KuCoinRestEndpoint("orderbook_l2", "GET", KUCOIN_BASE_FUTURES,
                           "/api/v1/level2/snapshot"),
    )


def build_public_wss_topics(symbols_v2: Iterable[str], spot: bool = True) -> tuple[KuCoinWssRequest, ...]:
    out: list[KuCoinWssRequest] = []
    for s in symbols_v2:
        kc = v2_to_kucoin_spot_symbol(s) if spot else v2_to_kucoin_futures_symbol(s)
        out.append(KuCoinWssRequest(topic=f"/market/ticker:{kc}"))
        out.append(KuCoinWssRequest(topic=f"/market/level2:{kc}"))
        if not spot:
            out.append(KuCoinWssRequest(topic=f"/contractMarket/fundingRate:{kc}"))
    return tuple(out)


def build_ingestor_config(
    *,
    symbols_v2: Iterable[str],
    timeframes: Iterable[str] = DEFAULT_TIMEFRAMES,
    spot: bool = True,
) -> KuCoinIngestorConfig:
    symbols = tuple(s.upper() for s in symbols_v2)
    tfs = tuple(timeframes)
    return KuCoinIngestorConfig(
        symbols_v2=symbols,
        timeframes=tfs,
        spot_endpoints=build_public_rest_endpoints(spot=True),
        futures_endpoints=build_public_rest_endpoints(spot=False),
        public_wss_topics=build_public_wss_topics(symbols, spot=spot),
        ticker_period_seconds=DEFAULT_TICKER_PERIOD_S,
        kline_period_seconds=DEFAULT_KLINE_PERIOD_S,
        funding_period_seconds=DEFAULT_FUNDING_PERIOD_S,
        orderbook_period_seconds=DEFAULT_ORDERBOOK_PERIOD_S,
        reconnect_backoff_seconds=RECONNECT_BACKOFF_SECONDS,
        generated_utc=_utc_iso(),
        classification=STATUS_NATIVE_V2,
    )


def kucoin_invariants_snapshot() -> dict:
    return {
        "schema_version": "v2_native_kucoin_v1",
        "legacy_kucoin_sha256": LEGACY_KUCOIN_SHA256,
        "imports_torch": False,
        "imports_numpy": False,
        "imports_redis": False,
        "imports_exchange_sdk": False,
        "performs_network_io": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "requires_api_key": False,
        "public_market_data_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
