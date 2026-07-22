from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from v2.backend.app.cli import v2_binance_mark_price_wss_seeder as mark_seeder
from v2.backend.app.cli import v2_native_ingestors_live_loop as native_ingestors
from v2.backend.app.services.liquidation_surface import (
    MAX_RAW_REDIS_BYTES,
    RawRedisEvidence,
    SourceAdapterError,
    adapt_binance_finalized_candles,
    adapt_binance_mark_price,
    adapt_coinank_plan3_open_interest,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
DURATION_MS = 300_000
BASE_MS = 1_800_000_000_000
CONSUMER_MS = BASE_MS + 1_500_000


def _raw(payload: Any, *, whitespace: bool = False) -> bytes:
    if whitespace:
        return json.dumps(payload, sort_keys=False, indent=1).encode("utf-8")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _evidence(key: str, payload: Any, *, whitespace: bool = False) -> RawRedisEvidence:
    return RawRedisEvidence.from_value(
        key=key,
        value=_raw(payload, whitespace=whitespace),
        consumer_observed_at_ms=CONSUMER_MS,
    )


def _candle_row(index: int, **overrides: Any) -> dict[str, Any]:
    open_time = BASE_MS + index * DURATION_MS
    close_time = open_time + DURATION_MS - 1
    row: dict[str, Any] = {
        "symbol": SYMBOL,
        "exchange": "binance",
        "venue": "binance_usdm",
        "product_type": "USD-M",
        "timeframe": TIMEFRAME,
        "candle_open_time": open_time,
        "candle_close_time": close_time,
        "event_time": close_time,
        "ingested_at": close_time + 10,
        "available_at": close_time + 20,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "feature_eligible": True,
        "source": "binance_wss",
        "source_sequence_id": index + 1,
        "raw_payload_hash": f"{index + 1:064x}",
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "quote_volume": "1000",
        "taker_buy_quote_vol": "600",
    }
    row.update(overrides)
    return row


def _coinank_payload(
    *,
    rows: list[dict[str, Any]] | None = None,
    request_started_at_ms: int = BASE_MS + 2 * DURATION_MS + 1,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ts_ms": request_started_at_ms + 100,
        "request_started_at_ms": request_started_at_ms,
        "symbol": SYMBOL,
        "exchange": "Binance",
        "family": "open_interest",
        "endpoint": "openInterest_kline",
        "interval": TIMEFRAME,
        "request_parameters": {
            "exchange": "Binance",
            "symbol": SYMBOL,
            "interval": TIMEFRAME,
            "productType": "SWAP",
            "size": 15,
        },
        "data": {
            "success": True,
            "code": "1",
            "data": rows
            or [
                {"begin": BASE_MS, "close": "100"},
                {"begin": BASE_MS + DURATION_MS, "close": "120"},
                {"begin": BASE_MS + 2 * DURATION_MS, "close": "140"},
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_raw_evidence_hashes_exact_observed_bytes_and_rejects_non_strict_json() -> None:
    payload = {"symbol": SYMBOL, "value": 1}
    evidence = _evidence("key", payload, whitespace=True)

    assert evidence.raw_sha256 == hashlib.sha256(evidence.raw).hexdigest()
    assert evidence.json_value() == payload
    assert (
        RawRedisEvidence.from_value(
            key="key",
            value=evidence.raw.decode("utf-8"),
            consumer_observed_at_ms=CONSUMER_MS,
        ).raw
        == evidence.raw
    )

    bad = RawRedisEvidence.from_value(
        key="key",
        value=b'{"value":NaN}',
        consumer_observed_at_ms=CONSUMER_MS,
    )
    with pytest.raises(SourceAdapterError, match="REDIS_VALUE_NOT_STRICT_JSON"):
        bad.json_value()

    with pytest.raises(
        SourceAdapterError,
        match="REDIS_VALUE_EXCEEDS_HARD_RESOURCE_MAXIMUM",
    ):
        RawRedisEvidence.from_value(
            key="key",
            value=b"x" * (MAX_RAW_REDIS_BYTES + 1),
            consumer_observed_at_ms=CONSUMER_MS,
        )


@pytest.mark.parametrize("symbol", ["", "btcusdt", "BTC-USDT", " BTCUSDT"])
def test_adapters_require_canonical_binance_symbol(symbol: str) -> None:
    with pytest.raises(SourceAdapterError, match="SYMBOL_MISMATCH_OR_NOT_CANONICAL"):
        adapt_binance_finalized_candles(
            _evidence(
                f"v2:market:ohlcv:binance:{symbol}:{TIMEFRAME}",
                [_candle_row(0, symbol=symbol)],
            ),
            symbol=symbol,
            timeframe=TIMEFRAME,
        )


def test_candle_adapter_preserves_exact_lineage_and_latest_contiguous_suffix() -> None:
    payload = [_candle_row(0), _candle_row(1), _candle_row(3)]
    evidence = _evidence(
        f"v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}",
        payload,
        whitespace=True,
    )

    rows = adapt_binance_finalized_candles(
        evidence,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )

    assert len(rows) == 1
    assert rows[0].open_time_ms == BASE_MS + 3 * DURATION_MS
    assert rows[0].available_at_ms == CONSUMER_MS
    assert rows[0].source_sha256 == hashlib.sha256(evidence.raw).hexdigest()
    assert rows[0].source_key == evidence.key
    assert rows[0].quote_volume == 1000.0
    assert rows[0].taker_buy_quote_volume == 600.0


def test_canonical_rest_producer_is_accepted_without_identity_inference() -> None:
    close_time = BASE_MS + DURATION_MS - 1
    payload = canonical_from_binance_rest(
        [
            BASE_MS,
            "100",
            "102",
            "99",
            "101",
            "12",
            close_time,
            "1200",
            10,
            "6",
            "600",
            "0",
        ],
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        ingested_at=close_time + 10,
    ).to_dict()

    rows = adapt_binance_finalized_candles(
        _evidence(
            f"v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}",
            [payload],
        ),
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )

    assert len(rows) == 1
    assert rows[0].venue == "binance_usdm"
    assert payload["product_type"] == "USD-M"


def test_deployed_closed_window_legacy_identity_is_bounded_to_canonical_key() -> None:
    legacy = _candle_row(0)
    legacy.pop("venue")
    legacy.pop("product_type")
    closed_key = f"v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}"

    row = adapt_binance_finalized_candles(
        _evidence(closed_key, [legacy]),
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )[0]
    assert row.venue == "binance_usdm"

    with pytest.raises(
        SourceAdapterError,
        match="CANDLE_ROW_VENUE_OR_TIMEFRAME_MISMATCH",
    ):
        adapt_binance_finalized_candles(
            _evidence(
                f"v2:market:ohlcv:binance:{SYMBOL}:{TIMEFRAME}",
                [legacy],
            ),
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )

    partial = dict(legacy, venue="binance_usdm")
    with pytest.raises(
        SourceAdapterError,
        match="CANDLE_ROW_VENUE_OR_TIMEFRAME_MISMATCH",
    ):
        adapt_binance_finalized_candles(
            _evidence(closed_key, [partial]),
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )


def test_candle_adapter_accepts_only_complete_canonical_resampler_identity() -> None:
    resampled = _candle_row(
        0,
        source="v2_closed_candle_resampler:1m",
        resampled_from_timeframe="1m",
        resampled_source_candle_count=5,
    )
    evidence = _evidence(
        f"v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}",
        [resampled],
    )
    assert (
        adapt_binance_finalized_candles(
            evidence,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )[0].source_key
        == evidence.key
    )

    resampled["resampled_source_candle_count"] = 4
    with pytest.raises(SourceAdapterError, match="CANDLE_RESAMPLER_COVERAGE_INVALID"):
        adapt_binance_finalized_candles(
            _evidence(evidence.key, [resampled]),
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"is_closed": False}, "CANDLE_ROW_NOT_FINAL"),
        ({"feature_eligible": False}, "CANDLE_ROW_FEATURE_ELIGIBLE_NOT_TRUE"),
        ({"source": "coinank"}, "CANDLE_SOURCE_NOT_BINANCE_CANONICAL"),
        ({"venue": "binance_spot"}, "CANDLE_ROW_VENUE_OR_TIMEFRAME_MISMATCH"),
        ({"product_type": "SPOT"}, "CANDLE_ROW_VENUE_OR_TIMEFRAME_MISMATCH"),
        ({"raw_payload_hash": "bad"}, "CANDLE_RAW_PAYLOAD_HASH_INVALID"),
        ({"available_at": CONSUMER_MS + 1}, "CANDLE_SOURCE_CLOCK_ORDER_INVALID"),
        ({"authority": True}, "UNVERIFIED_SOURCE_AUTHORITY_CLAIM"),
    ],
)
def test_candle_adapter_rejects_dirty_or_self_authorized_rows(
    mutation: dict[str, Any],
    error: str,
) -> None:
    with pytest.raises(SourceAdapterError, match=error):
        adapt_binance_finalized_candles(
            _evidence(
                f"v2:market:ohlcv:binance:{SYMBOL}:{TIMEFRAME}",
                [_candle_row(0, **mutation)],
            ),
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )


def test_mark_adapter_requires_binance_identity_and_uses_consumer_receipt_clock() -> None:
    payload = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": SYMBOL,
        "venue": "binance_usdm",
        "product_type": "USD-M",
        "markPrice": "101.25",
        "event_time": BASE_MS + 1,
        "available_at": BASE_MS + 10,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
    }
    evidence = _evidence(f"v2:market:mark_price:{SYMBOL}", payload, whitespace=True)

    row = adapt_binance_mark_price(evidence, symbol=SYMBOL)

    assert row.price == 101.25
    assert row.event_time_ms == BASE_MS + 1
    assert row.ingested_at_ms == BASE_MS + 10
    assert row.available_at_ms == CONSUMER_MS
    assert row.source_sha256 == hashlib.sha256(evidence.raw).hexdigest()


def test_mark_wss_producer_is_accepted_without_identity_inference() -> None:
    payload = mark_seeder._normalize_row(  # noqa: SLF001
        {"s": SYMBOL, "p": "101.25", "i": "101.20", "E": BASE_MS + 1},
        available_at=str(BASE_MS + 10),
    )
    assert payload is not None

    row = adapt_binance_mark_price(
        _evidence(f"v2:market:mark_price:{SYMBOL}", payload),
        symbol=SYMBOL,
    )

    assert row.price == 101.25
    assert row.venue == "binance_usdm"
    assert payload["product_type"] == "USD-M"


def test_deployed_mark_wss_legacy_identity_is_bounded_to_exact_key() -> None:
    payload = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": SYMBOL,
        "markPrice": "101.25",
        "event_time": BASE_MS + 1,
        "available_at": BASE_MS + 10,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
    }
    exact_key = f"v2:market:mark_price:{SYMBOL}"
    assert (
        adapt_binance_mark_price(
            _evidence(exact_key, payload),
            symbol=SYMBOL,
        ).venue
        == "binance_usdm"
    )

    with pytest.raises(
        SourceAdapterError,
        match="MARK_PRICE_VENUE_OR_PRODUCT_TYPE_MISMATCH",
    ):
        adapt_binance_mark_price(
            _evidence(f"v2:market:funding:{SYMBOL}", payload),
            symbol=SYMBOL,
        )

    partial = dict(payload, venue="binance_usdm")
    with pytest.raises(
        SourceAdapterError,
        match="MARK_PRICE_VENUE_OR_PRODUCT_TYPE_MISMATCH",
    ):
        adapt_binance_mark_price(
            _evidence(exact_key, partial),
            symbol=SYMBOL,
        )


def test_native_rest_fallback_is_accepted_with_exact_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyRedis:
        @staticmethod
        def get(_key: str) -> None:
            return None

    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(
        native_ingestors,
        "_http_get_json",
        lambda _url, *, fallback_reason: {
            "symbol": SYMBOL,
            "markPrice": "101.25",
            "indexPrice": "101.20",
            "lastFundingRate": "0.0001",
            "time": BASE_MS + 1,
        },
    )
    monkeypatch.setattr(
        native_ingestors,
        "_utc_iso_precise",
        lambda: str(BASE_MS + 10),
    )

    payload = native_ingestors._fetch_funding(  # noqa: SLF001
        SYMBOL,
        redis_client=EmptyRedis(),
    )
    assert payload is not None
    row = adapt_binance_mark_price(
        _evidence(f"v2:market:funding:{SYMBOL}", payload),
        symbol=SYMBOL,
    )

    assert row.price == 101.25
    assert payload["source_endpoint"] == "/fapi/v1/premiumIndex"
    assert payload["venue"] == "binance_usdm"
    assert payload["product_type"] == "USD-M"


def test_funding_mark_adapter_accepts_only_known_usdm_premium_index_provenance() -> None:
    payload = {
        "symbol": SYMBOL,
        "venue": "binance_usdm",
        "product_type": "USD-M",
        "markPrice": "101.25",
        "time": BASE_MS + 1,
        "available_at": BASE_MS + 10,
        "source": "binance_public_rest_premium_index_fallback",
        "source_endpoint": "/fapi/v1/premiumIndex",
        "transport": "rest_fallback",
    }
    evidence = _evidence(f"v2:market:funding:{SYMBOL}", payload)

    row = adapt_binance_mark_price(evidence, symbol=SYMBOL)

    assert row.price == 101.25
    assert row.source_key == evidence.key

    payload["source"] = "binance"
    with pytest.raises(SourceAdapterError, match="MARK_PRICE_SOURCE_NOT_BINANCE_USDM"):
        adapt_binance_mark_price(
            _evidence(f"v2:market:funding:{SYMBOL}", payload),
            symbol=SYMBOL,
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            {"source": "unknown"},
            "MARK_PRICE_SOURCE_NOT_EXACT_BINANCE_USDM_WSS",
        ),
        ({"markPrice": "0"}, "MARK_PRICE_NOT_POSITIVE"),
        ({"event_time": CONSUMER_MS + 1}, "MARK_PRICE_SOURCE_CLOCK_ORDER_INVALID"),
        ({"trainer_authority": True}, "UNVERIFIED_SOURCE_AUTHORITY_CLAIM"),
    ],
)
def test_mark_adapter_rejects_wrong_source_price_clock_or_authority(
    mutation: dict[str, Any],
    error: str,
) -> None:
    payload = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": SYMBOL,
        "venue": "binance_usdm",
        "product_type": "USD-M",
        "markPrice": "101.25",
        "event_time": BASE_MS + 1,
        "available_at": BASE_MS + 10,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
    }
    payload.update(mutation)
    with pytest.raises(SourceAdapterError, match=error):
        adapt_binance_mark_price(
            _evidence(f"v2:market:mark_price:{SYMBOL}", payload),
            symbol=SYMBOL,
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"symbol": None}, "MARK_PRICE_SYMBOL_MISMATCH"),
        ({"venue": "binance_spot"}, "MARK_PRICE_VENUE_OR_PRODUCT_TYPE_MISMATCH"),
        ({"product_type": "SPOT"}, "MARK_PRICE_VENUE_OR_PRODUCT_TYPE_MISMATCH"),
    ],
)
def test_mark_adapter_requires_exact_symbol_usdm_venue_and_product(
    mutation: dict[str, Any],
    error: str,
) -> None:
    payload = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": SYMBOL,
        "venue": "binance_usdm",
        "product_type": "USD-M",
        "markPrice": "101.25",
        "event_time": BASE_MS + 1,
        "available_at": BASE_MS + 10,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
    }
    payload.update(mutation)
    with pytest.raises(SourceAdapterError, match=error):
        adapt_binance_mark_price(
            _evidence(f"v2:market:mark_price:{SYMBOL}", payload),
            symbol=SYMBOL,
        )


def test_coinank_plan3_oi_adapter_uses_request_start_finality_and_base_asset_unit() -> None:
    evidence = _evidence(
        f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}",
        _coinank_payload(),
        whitespace=True,
    )

    rows = adapt_coinank_plan3_open_interest(
        evidence,
        symbol=SYMBOL,
        source_timeframe=TIMEFRAME,
    )

    assert [row.value for row in rows] == [100.0, 120.0]
    assert [row.feature_cutoff_ms for row in rows] == [
        BASE_MS + DURATION_MS,
        BASE_MS + 2 * DURATION_MS,
    ]
    assert all(row.unit == "base_asset" for row in rows)
    assert all(row.available_at_ms == CONSUMER_MS for row in rows)
    assert all(row.source_sha256 == hashlib.sha256(evidence.raw).hexdigest() for row in rows)


def test_coinank_oi_adapter_returns_only_latest_contiguous_final_suffix() -> None:
    rows = [
        {"begin": BASE_MS, "close": "100"},
        {"begin": BASE_MS + DURATION_MS, "close": "120"},
        {"begin": BASE_MS + 3 * DURATION_MS, "close": "140"},
    ]
    payload = _coinank_payload(
        rows=rows,
        request_started_at_ms=BASE_MS + 4 * DURATION_MS + 1,
    )

    adapted = adapt_coinank_plan3_open_interest(
        _evidence(f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}", payload),
        symbol=SYMBOL,
        source_timeframe=TIMEFRAME,
    )

    assert len(adapted) == 1
    assert adapted[0].value == 140.0


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"endpoint": "liquidationHeatmap"}, "COINANK_OI_ENDPOINT_MISMATCH"),
        ({"family": "liquidation_map"}, "COINANK_OI_FAMILY_MISMATCH"),
        ({"exchange": "Bybit"}, "COINANK_OI_VENUE_NOT_BINANCE_USDM"),
        ({"interval": "1h"}, "COINANK_OI_TIMEFRAME_MISMATCH"),
        ({"request_started_at_ms": None}, "COINANK_REQUEST_STARTED_AT"),
        ({"source_receipt_authority": True}, "UNVERIFIED_SOURCE_AUTHORITY_CLAIM"),
    ],
)
def test_coinank_oi_adapter_rejects_plan4_wrong_identity_missing_clock_or_authority(
    mutation: dict[str, Any],
    error: str,
) -> None:
    payload = _coinank_payload()
    payload.update(mutation)
    with pytest.raises(SourceAdapterError, match=error):
        adapt_coinank_plan3_open_interest(
            _evidence(f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}", payload),
            symbol=SYMBOL,
            source_timeframe=TIMEFRAME,
        )


@pytest.mark.parametrize(
    ("parameter_mutation", "error"),
    [
        ({"symbol": "ETHUSDT"}, "SYMBOL_MISMATCH_OR_NOT_CANONICAL"),
        ({"exchange": "Bybit"}, "COINANK_OI_REQUEST_VENUE_MISMATCH"),
        ({"interval": "1h"}, "COINANK_OI_REQUEST_TIMEFRAME_MISMATCH"),
        ({"productType": "SPOT"}, "COINANK_OI_REQUEST_PRODUCT_TYPE_NOT_SWAP"),
    ],
)
def test_coinank_oi_adapter_binds_exact_request_parameters(
    parameter_mutation: dict[str, Any],
    error: str,
) -> None:
    payload = _coinank_payload()
    payload["request_parameters"].update(parameter_mutation)
    with pytest.raises(SourceAdapterError, match=error):
        adapt_coinank_plan3_open_interest(
            _evidence(f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}", payload),
            symbol=SYMBOL,
            source_timeframe=TIMEFRAME,
        )


def test_coinank_oi_adapter_rejects_unsuccessful_response_envelope() -> None:
    payload = _coinank_payload()
    payload["data"]["success"] = False
    with pytest.raises(SourceAdapterError, match="COINANK_OI_RESPONSE_NOT_SUCCESS"):
        adapt_coinank_plan3_open_interest(
            _evidence(f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}", payload),
            symbol=SYMBOL,
            source_timeframe=TIMEFRAME,
        )


def test_coinank_oi_boundary_equal_to_request_start_is_not_final() -> None:
    request_start = BASE_MS + DURATION_MS
    payload = _coinank_payload(
        rows=[{"begin": BASE_MS, "close": "100"}],
        request_started_at_ms=request_start,
    )
    with pytest.raises(SourceAdapterError, match="COINANK_OI_NO_FINALIZED_ROWS"):
        adapt_coinank_plan3_open_interest(
            _evidence(f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}", payload),
            symbol=SYMBOL,
            source_timeframe=TIMEFRAME,
        )
