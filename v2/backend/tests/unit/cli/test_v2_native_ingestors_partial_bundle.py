from __future__ import annotations

from typing import Any

from v2.backend.app.cli import v2_native_ingestors_live_loop as worker


def test_symbol_bundle_preserves_valid_families_when_one_timeframe_is_unavailable(
    monkeypatch: Any,
) -> None:
    ticker = {"lastPrice": "10", "transport": "websocket_cache_primary"}
    funding = {"mark_price": 10.0, "transport": "websocket_cache_primary"}
    open_interest = {"open_interest": 100.0, "transport": "rest_fallback"}
    orderbook = {"best_bid": 9.9, "best_ask": 10.1, "transport": "websocket_cache_primary"}

    monkeypatch.setattr(worker, "_fetch_ticker_24hr", lambda *_args, **_kwargs: ticker)
    monkeypatch.setattr(worker, "_fetch_funding", lambda *_args, **_kwargs: funding)
    monkeypatch.setattr(worker, "_fetch_open_interest", lambda *_args, **_kwargs: open_interest)
    monkeypatch.setattr(worker, "_fetch_orderbook_top", lambda *_args, **_kwargs: orderbook)
    monkeypatch.setattr(worker, "_fetch_open_interest_hist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_fetch_long_short_ratio", lambda *_args, **_kwargs: None)

    def fetch_klines(_symbol: str, *, interval: str, **_kwargs: Any) -> list[dict[str, Any]]:
        if interval == "5m":
            raise RuntimeError(
                "REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION:121>120_per_minute"
            )
        return [{"timeframe": interval, "is_closed": True}]

    monkeypatch.setattr(worker, "_fetch_klines", fetch_klines)

    bundle = worker._fetch_symbol_bundle(
        "BTCUSDT",
        kline_timeframes=("1m", "5m", "15m"),
        redis_client=object(),
    )

    assert bundle["ticker"] is ticker
    assert bundle["funding"] is funding
    assert bundle["open_interest"] is open_interest
    assert bundle["orderbook"] is orderbook
    assert sorted(bundle["klines_by_timeframe"]) == ["15m", "1m"]
    assert bundle["partial_bundle"] is True
    assert bundle["fetch_errors"] == {
        "klines:5m": (
            "RuntimeError:REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION:"
            "121>120_per_minute"
        ),
        "open_interest_hist": "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE",
        "long_short": "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE",
    }
    assert bundle["symbol_info"]["ticker_present"] is True
    assert bundle["symbol_info"]["funding_present"] is True
    assert bundle["symbol_info"]["open_interest_present"] is True
    assert bundle["symbol_info"]["partial_bundle"] is True


def test_internal_transport_timeout_is_reported_as_partial_unavailability(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(worker.OPTIONAL_DERIVATIVE_REST_ENV, "true")
    monkeypatch.setattr(worker, "_rest_fallback_disabled", lambda: False)
    monkeypatch.setattr(
        worker,
        "_http_get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("provider timeout")),
    )
    monkeypatch.setattr(worker, "resolve_current_price", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "_coinank_point_open_interest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_coinank_oi_hist_rows", lambda *_args, **_kwargs: None)

    bundle = worker._fetch_symbol_bundle(
        "BTCUSDT",
        kline_timeframes=(),
        redis_client=object(),
    )

    assert bundle["partial_bundle"] is True
    assert bundle["fetch_errors"] == {
        "ticker_24hr": "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE",
        "funding": "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE",
        "open_interest": "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE",
        "orderbook": "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE",
        "open_interest_hist": "SOURCE_CACHE_READ_FAILED",
        "long_short": "LONG_SHORT_RATIO_REST_REQUEST_FAILED",
    }


def test_conflicting_rest_transport_is_counted_as_rest_fallback(monkeypatch: Any) -> None:
    rest_payload = {"source": "binance", "transport": "rest_fallback"}
    monkeypatch.setattr(worker, "_fetch_ticker_24hr", lambda *_args, **_kwargs: rest_payload)
    monkeypatch.setattr(worker, "_fetch_funding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_fetch_open_interest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_fetch_orderbook_top", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_fetch_open_interest_hist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_fetch_long_short_ratio", lambda *_args, **_kwargs: None)

    bundle = worker._fetch_symbol_bundle(
        "BTCUSDT",
        kline_timeframes=(),
        redis_client=object(),
    )

    assert bundle["rest_fallback_used"] is True
    assert bundle["symbol_info"]["rest_fallback_field_count"] == 1
    assert bundle["symbol_info"]["cache_primary_field_count"] == 0


def test_every_component_failure_returns_a_bounded_diagnostic_bundle(
    monkeypatch: Any,
) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise TimeoutError("x" * 1_000)

    for name in (
        "_fetch_ticker_24hr",
        "_fetch_funding",
        "_fetch_open_interest",
        "_fetch_klines",
        "_fetch_orderbook_top",
        "_fetch_open_interest_hist",
        "_fetch_long_short_ratio",
    ):
        monkeypatch.setattr(worker, name, unavailable)

    bundle = worker._fetch_symbol_bundle(
        "BTCUSDT",
        kline_timeframes=("1m", "5m"),
        redis_client=object(),
    )

    assert bundle["partial_bundle"] is True
    assert set(bundle["fetch_errors"]) == {
        "ticker_24hr",
        "funding",
        "open_interest",
        "klines:1m",
        "klines:5m",
        "orderbook",
        "open_interest_hist",
        "long_short",
    }
    assert all(len(reason) <= 253 for reason in bundle["fetch_errors"].values())
    assert bundle["symbol_info"]["ticker_present"] is False
    assert bundle["symbol_info"]["kline_timeframes_present"] == []
