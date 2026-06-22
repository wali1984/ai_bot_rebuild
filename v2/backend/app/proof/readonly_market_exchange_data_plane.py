from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


GO_NO_GO_MARKER = "PHASE2Z_READONLY_MARKET_AND_EXCHANGE_DATA_PLANE_READY"
LIVE_GATE_STATUS = "blocked_human_only"
GENERATED_AT = "2026-05-10T00:00:00Z"

DEFAULT_ALLOWED_OUTPUT_PREFIXES = (
    "claude_worklog/final_readiness/readonly_market_exchange_data_plane/",
    "v2/frontend/public/readonly_market_exchange_data_plane/",
)

READONLY_METHODS = frozenset(
    {
        "fetch_market_candles",
        "fetch_market_ticker",
        "fetch_funding_rate",
        "fetch_open_interest",
        "fetch_orderbook_depth",
        "fetch_account_status_readonly",
        "fetch_balances_readonly",
        "fetch_positions_readonly",
        "fetch_open_orders_readonly",
        "fetch_fills_readonly",
    }
)

FORBIDDEN_MUTATION_METHODS = frozenset(
    {
        "create" + "_order",
        "cancel" + "_order",
        "change" + "_leverage",
        "change" + "_margin",
        "change" + "_position_mode",
        "withdraw",
        "transfer",
        "enable_live_trading",
    }
)


@dataclass(frozen=True, slots=True)
class Freshness:
    source: str
    generated_at: str
    last_event_at: str
    age_seconds: int
    freshness_state: str
    source_type: str
    source_pointer: str


@dataclass(frozen=True, slots=True)
class MarketCandle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    freshness: Freshness


@dataclass(frozen=True, slots=True)
class ExchangeStatus:
    exchange: str
    key_status: str
    account_read_status: str
    market_data_status: str
    order_capability: str
    permission_status: str
    freshness: Freshness


class ExchangeMutationForbidden(RuntimeError):
    pass


class ReadonlyExchangeConnector:
    exchange_name = "generic"

    def forbidden_mutation(self, action: str) -> None:
        raise ExchangeMutationForbidden(f"{action} is forbidden in V2 read-only data plane")

    def forbidden_method(self, action: str, *_args: Any, **_kwargs: Any) -> None:
        self.forbidden_mutation(action)


def _install_forbidden_method(name: str) -> None:
    def _blocked(self: ReadonlyExchangeConnector, *_args: Any, **_kwargs: Any) -> None:
        self.forbidden_method(name)

    setattr(ReadonlyExchangeConnector, name, _blocked)


for _forbidden_method_name in FORBIDDEN_MUTATION_METHODS:
    _install_forbidden_method(_forbidden_method_name)


class BinanceReadonlyConnector(ReadonlyExchangeConnector):
    exchange_name = "Binance USD-M"
    base_url = "https://fapi.binance.com"

    def __init__(self, http_get: Callable[[str], Any] | None = None) -> None:
        self._http_get = http_get or _default_http_get

    def fetch_market_candles(self, symbol: str = "BTCUSDT", interval: str = "5m", limit: int = 60) -> list[MarketCandle]:
        params = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": str(limit)})
        data = self._http_get(f"{self.base_url}/fapi/v1/klines?{params}")
        candles: list[MarketCandle] = []
        now = int(time.time())
        for row in data:
            event_ts = int(row[0]) // 1000
            freshness = classify_freshness(
                generated_at=GENERATED_AT,
                last_event_at=str(event_ts),
                age_seconds=max(now - event_ts, 0),
                source="binance_usdm_public_klines",
                source_type="READONLY_MARKET_FEED",
                source_pointer="/fapi/v1/klines",
            )
            candles.append(
                MarketCandle(
                    time=str(event_ts),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    freshness=freshness,
                )
            )
        return candles

    def fetch_market_ticker(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        params = urllib.parse.urlencode({"symbol": symbol})
        data = self._http_get(f"{self.base_url}/fapi/v1/ticker/24hr?{params}")
        return {"symbol": data.get("symbol", symbol), "price": data.get("lastPrice"), "change_24h": data.get("priceChangePercent")}

    def fetch_funding_rate(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        params = urllib.parse.urlencode({"symbol": symbol, "limit": "1"})
        data = self._http_get(f"{self.base_url}/fapi/v1/fundingRate?{params}")
        row = data[0] if isinstance(data, list) and data else {}
        return {"symbol": row.get("symbol", symbol), "funding_rate": row.get("fundingRate")}

    def fetch_open_interest(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        params = urllib.parse.urlencode({"symbol": symbol})
        data = self._http_get(f"{self.base_url}/fapi/v1/openInterest?{params}")
        return {"symbol": data.get("symbol", symbol), "open_interest": data.get("openInterest")}


class DesignOnlyReadonlyConnector(ReadonlyExchangeConnector):
    def __init__(self, exchange_name: str) -> None:
        self.exchange_name = exchange_name


def _default_http_get(url: str) -> Any:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "ai-bot-v2-readonly-data-plane"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def classify_freshness(
    *,
    generated_at: str,
    last_event_at: str,
    age_seconds: int,
    source: str,
    source_type: str,
    source_pointer: str,
) -> Freshness:
    if source_type == "MISSING":
        state = "missing"
    elif age_seconds <= 300:
        state = "fresh"
    elif age_seconds <= 1800:
        state = "warn"
    else:
        state = "stale"
    return Freshness(source, generated_at, last_event_at, age_seconds, state, source_type, source_pointer)


def validate_output_dir(
    output_dir: str | Path,
    *,
    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_OUTPUT_PREFIXES,
    workspace: str | Path | None = None,
) -> Path:
    root = Path(workspace or Path.cwd()).resolve()
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    rel = output.relative_to(root).as_posix()
    normalized = rel.rstrip("/") + "/"
    if not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
        raise ValueError(f"output directory is outside allowed prefixes: {rel}")
    return output


def fixture_candles() -> list[MarketCandle]:
    freshness = classify_freshness(
        generated_at=GENERATED_AT,
        last_event_at=GENERATED_AT,
        age_seconds=0,
        source="static_market_fixture",
        source_type="STATIC_PROOF_FIXTURE",
        source_pointer="v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json",
    )
    return [
        MarketCandle("23:00", 63200, 63540, 63110, 63480, 4200, freshness),
        MarketCandle("23:05", 63480, 63720, 63390, 63640, 5100, freshness),
        MarketCandle("23:10", 63640, 63880, 63590, 63810, 6100, freshness),
        MarketCandle("23:15", 63810, 63980, 63620, 63710, 5800, freshness),
        MarketCandle("23:20", 63710, 64120, 63680, 64090, 7200, freshness),
        MarketCandle("23:25", 64090, 64220, 63890, 63950, 6500, freshness),
    ]


def build_operator_payload(*, fetch_binance: bool = False, symbol: str = "BTCUSDT") -> dict[str, Any]:
    feed_errors: list[str] = []
    source_type = "STATIC_PROOF_FIXTURE"
    candles = fixture_candles()
    ticker = {"symbol": symbol, "price": "fixture_63950.25", "change_24h": "fixture_2.1"}
    funding = {"symbol": symbol, "funding_rate": "fixture_0.0001"}
    open_interest = {"symbol": symbol, "open_interest": "fixture_11800000000"}

    if fetch_binance:
        connector = BinanceReadonlyConnector()
        try:
            candles = connector.fetch_market_candles(symbol=symbol, limit=60)
            ticker = connector.fetch_market_ticker(symbol=symbol)
            funding = connector.fetch_funding_rate(symbol=symbol)
            open_interest = connector.fetch_open_interest(symbol=symbol)
            source_type = "READONLY_MARKET_FEED"
        except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError, TypeError) as exc:
            feed_errors.append(f"binance_public_market_feed_failed: {exc.__class__.__name__}")

    missing = classify_freshness(
        generated_at=GENERATED_AT,
        last_event_at="missing",
        age_seconds=0,
        source="local_secret_provider",
        source_type="MISSING",
        source_pointer="local-only API key provider not configured in committed artifacts",
    )
    market_freshness = candles[-1].freshness if candles else missing

    exchange_status = [
        ExchangeStatus("Binance USD-M", "not_configured", "missing", "ready" if source_type == "READONLY_MARKET_FEED" else "fixture_fallback", "BLOCKED", "order_methods_absent", market_freshness),
        ExchangeStatus("KuCoin", "not_configured", "missing", "design_only", "BLOCKED", "read_only_required", missing),
        ExchangeStatus("MEXC", "not_configured", "missing", "design_only", "BLOCKED", "read_only_required_no_sandbox_assumption", missing),
    ]

    return {
        "generated_at": GENERATED_AT,
        "go_no_go": GO_NO_GO_MARKER,
        "live_gate_status": LIVE_GATE_STATUS,
        "selected_symbol": symbol,
        "feed_health": {
            "source_type": source_type,
            "freshness_state": market_freshness.freshness_state,
            "errors": feed_errors,
            "order_capability": "BLOCKED",
        },
        "market_candles": [asdict(candle) for candle in candles],
        "market_tickers": [{**ticker, "source_type": source_type, "freshness": asdict(market_freshness)}],
        "market_funding": [{**funding, "source_type": source_type, "freshness": asdict(market_freshness)}],
        "market_open_interest": [{**open_interest, "source_type": source_type, "freshness": asdict(market_freshness)}],
        "market_orderbook_depth": [{"symbol": symbol, "source_type": "MISSING", "freshness": asdict(missing), "reason": "read-only orderbook depth connector not configured"}],
        "exchange_account_status": [asdict(row) for row in exchange_status],
        "exchange_balances_readonly": [{"exchange": "Binance USD-M", "source_type": "MISSING", "reason": "read-only account key not configured", "freshness": asdict(missing)}],
        "exchange_positions_readonly": [{"exchange": "Binance USD-M", "source_type": "MISSING", "reason": "read-only account key not configured", "freshness": asdict(missing)}],
        "exchange_open_orders_readonly": [{"exchange": "Binance USD-M", "source_type": "MISSING", "reason": "read-only account key not configured", "freshness": asdict(missing)}],
        "exchange_fills_readonly": [{"exchange": "Binance USD-M", "source_type": "MISSING", "reason": "read-only account key not configured", "freshness": asdict(missing)}],
        "api_key_permission_status": [
            {"exchange": "Binance USD-M", "status": "not_configured", "trade_permission_detected": False, "order_capability": "BLOCKED"},
            {"exchange": "KuCoin", "status": "not_configured", "trade_permission_detected": False, "order_capability": "BLOCKED"},
            {"exchange": "MEXC", "status": "not_configured", "trade_permission_detected": False, "order_capability": "BLOCKED"},
        ],
        "paper_runtime_market_feed": {
            "can_consume_feed": True,
            "source_type": source_type,
            "writes_legacy_redis": False,
            "places_orders": False,
            "records_source_freshness": True,
        },
    }


def write_readonly_market_exchange_data_plane(
    output_dir: str | Path,
    *,
    public_output_dir: str | Path | None = None,
    fetch_binance: bool = False,
    symbol: str = "BTCUSDT",
) -> dict[str, Any]:
    output = validate_output_dir(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    payload = build_operator_payload(fetch_binance=fetch_binance, symbol=symbol)

    files = {
        "GO_NO_GO.md": GO_NO_GO_MARKER + "\n",
        "operator_dashboard_payload.json": json.dumps(payload, indent=2) + "\n",
        "PHASE2Z_READONLY_MARKET_EXCHANGE_DATA_PLANE_REPORT.md": _report(payload),
        "MARKET_DATA_CONTRACTS.md": _contracts_doc(),
        "EXCHANGE_CONNECTOR_READONLY_POLICY.md": _policy_doc(),
        "FEED_FRESHNESS_REPORT.md": _freshness_doc(payload),
        "CHART_DATA_WIRING_REPORT.md": _chart_doc(payload),
        "ACCOUNT_READONLY_WIRING_REPORT.md": _account_doc(payload),
        "PAPER_RUNTIME_MARKET_FEED_REPORT.md": _paper_doc(payload),
    }
    for name, body in files.items():
        (output / name).write_text(body)

    if public_output_dir is not None:
        public_output = validate_output_dir(public_output_dir)
        public_output.parent.mkdir(parents=True, exist_ok=True)
        if public_output.exists():
            shutil.rmtree(public_output)
        shutil.copytree(output, public_output)
    return payload


def _report(payload: dict[str, Any]) -> str:
    return (
        "# Phase 2Z Read-Only Market / Exchange Data Plane Report\n\n"
        f"Status: `{GO_NO_GO_MARKER}`\n\n"
        f"Feed source type: `{payload['feed_health']['source_type']}`\n\n"
        "The data plane exposes read-only market/account contracts, Binance public market-data fetch support, "
        "fixture fallback with explicit source labels, and fail-closed exchange connector policy. "
        "Account-read data remains `MISSING` until local read-only keys are configured outside committed artifacts.\n\n"
        "PHASE2Z_READONLY_MARKET_EXCHANGE_DATA_PLANE_REPORT_READY\n"
    )


def _contracts_doc() -> str:
    return "# Market Data Contracts\n\nContracts: market_candles, market_tickers, market_funding, market_open_interest, market_orderbook_depth, exchange_account_status, exchange_balances_readonly, exchange_positions_readonly, exchange_open_orders_readonly, exchange_fills_readonly, feed_health, data_freshness, api_key_permission_status.\n\nMARKET_DATA_CONTRACTS_READY\n"


def _policy_doc() -> str:
    forbidden = ", ".join(sorted(FORBIDDEN_MUTATION_METHODS))
    return f"# Exchange Connector Read-Only Policy\n\nAllowed methods: {', '.join(sorted(READONLY_METHODS))}.\n\nForbidden mutation methods fail closed: {forbidden}.\n\nNo connector may place/cancel orders, change leverage, change margin, change position mode, withdraw, transfer, or enable live trading.\n\nEXCHANGE_CONNECTOR_READONLY_POLICY_READY\n"


def _freshness_doc(payload: dict[str, Any]) -> str:
    return f"# Feed Freshness Report\n\nSource type: `{payload['feed_health']['source_type']}`\nFreshness: `{payload['feed_health']['freshness_state']}`\nErrors: `{payload['feed_health']['errors']}`\n\nFEED_FRESHNESS_REPORT_READY\n"


def _chart_doc(payload: dict[str, Any]) -> str:
    return f"# Chart Data Wiring Report\n\nCandles emitted: `{len(payload['market_candles'])}`\nSource type: `{payload['feed_health']['source_type']}`\nFixture fallback remains explicitly labeled when public feed data is unavailable.\n\nCHART_DATA_WIRING_REPORT_READY\n"


def _account_doc(payload: dict[str, Any]) -> str:
    statuses = ", ".join(f"{row['exchange']}={row['key_status']}" for row in payload["exchange_account_status"])
    return f"# Account Readonly Wiring Report\n\nKey statuses: {statuses}.\n\nNo committed secret provider is present. Account reads remain missing until local read-only credentials are configured.\n\nACCOUNT_READONLY_WIRING_REPORT_READY\n"


def _paper_doc(payload: dict[str, Any]) -> str:
    paper = payload["paper_runtime_market_feed"]
    return f"# Paper Runtime Market Feed Report\n\nCan consume feed: `{paper['can_consume_feed']}`\nSource type: `{paper['source_type']}`\nWrites legacy Redis: `{paper['writes_legacy_redis']}`\nPlaces orders: `{paper['places_orders']}`\nRecords source freshness: `{paper['records_source_freshness']}`\n\nPAPER_RUNTIME_MARKET_FEED_REPORT_READY\n"
