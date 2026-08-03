from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from v2.backend.app.cli import v2_native_ingestors_live_loop as loop


class FakeRedis:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.store = {
            key: json.dumps(value, separators=(",", ":"))
            for key, value in (initial or {}).items()
        }

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True


def _coinank_payload(
    *,
    fetched_ms: int,
    begins_ms: list[int],
    request_started_at_ms: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ts_ms": fetched_ms,
        "data": {
            "data": [
                {"begin": begin_ms, "close": str(100 + index)}
                for index, begin_ms in enumerate(begins_ms)
            ]
        },
    }
    if request_started_at_ms is not None:
        payload["request_started_at_ms"] = request_started_at_ms
    return payload


def _rest_kline(*, open_ms: int, close_ms: int) -> list[Any]:
    return [
        open_ms,
        "1.0",
        "2.0",
        "0.5",
        "1.5",
        "10.0",
        close_ms,
        "15.0",
        4,
        "6.0",
        "9.0",
        "0",
    ]


def test_coinank_mapper_excludes_open_bucket_without_truncating_event_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket_open_ms = 1_800_000_000_000
    fetched_ms = bucket_open_ms + 120_000
    begins_ms = [
        bucket_open_ms - 900_000,
        bucket_open_ms - 600_000,
        bucket_open_ms - 300_000,
        bucket_open_ms,
    ]
    key = "latest:coinank:open_interest:BTCUSDT:5m"
    redis_client = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=fetched_ms,
                begins_ms=begins_ms,
                request_started_at_ms=fetched_ms,
            )
        }
    )
    monkeypatch.setattr(loop.time, "time", lambda: fetched_ms / 1_000.0)

    rows = loop._coinank_oi_hist_rows("BTCUSDT", redis_client=redis_client)
    point = loop._coinank_point_open_interest("BTCUSDT", redis_client=redis_client)

    assert rows is not None
    assert len(rows) == 3
    assert rows[-1]["timestamp"] == bucket_open_ms
    assert rows[-1]["event_time"] == bucket_open_ms
    assert rows[-1]["finality_cutoff_ms"] == fetched_ms
    assert rows[-1]["timestamp"] != fetched_ms
    assert all(row["timestamp"] <= row["available_at"] for row in rows)
    assert all(row["source_receipt_authority"] is False for row in rows)
    assert all(row["trainer_authority"] is False for row in rows)
    assert point is not None
    assert point["time"] == bucket_open_ms
    assert point["source_receipt_authority"] is False
    assert point["trainer_authority"] is False


def test_coinank_only_open_bucket_and_future_source_cutoff_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ms = 1_800_000_120_000
    open_ms = 1_800_000_000_000
    key = "latest:coinank:open_interest:BTCUSDT:5m"
    monkeypatch.setattr(loop.time, "time", lambda: now_ms / 1_000.0)

    open_only = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=now_ms,
                begins_ms=[open_ms],
                request_started_at_ms=now_ms,
            )
        }
    )
    future_cutoff = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=now_ms + 1,
                begins_ms=[open_ms - 300_000],
                request_started_at_ms=now_ms,
            )
        }
    )

    assert loop._coinank_oi_hist_rows("BTCUSDT", redis_client=open_only) is None
    assert loop._coinank_point_open_interest("BTCUSDT", redis_client=open_only) is None
    assert loop._coinank_oi_hist_rows("BTCUSDT", redis_client=future_cutoff) is None
    assert loop._open_interest_cache_age_seconds({"time": now_ms + 1}) is None
    future_iso = datetime.fromtimestamp(
        (now_ms + 1) / 1_000.0,
        tz=UTC,
    ).isoformat()
    assert loop._open_interest_cache_age_seconds({"fetched_utc": future_iso}) is None


def test_coinank_fractional_cutoff_cannot_round_up_to_close_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket_open_ms = 1_800_000_000_000
    bucket_close_ms = bucket_open_ms + 300_000
    observed_ms = bucket_close_ms + 2_000
    key = "latest:coinank:open_interest:BTCUSDT:5m"
    monkeypatch.setattr(loop.time, "time", lambda: observed_ms / 1_000.0)
    exact_boundary = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=observed_ms,
                begins_ms=[bucket_open_ms],
                request_started_at_ms=bucket_close_ms,
            )
        }
    )
    assert loop._coinank_oi_hist_rows("BTCUSDT", redis_client=exact_boundary) is None

    after_boundary = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=observed_ms,
                begins_ms=[bucket_open_ms],
                request_started_at_ms=bucket_close_ms + 1,
            )
        }
    )
    after_rows = loop._coinank_oi_hist_rows(
        "BTCUSDT",
        redis_client=after_boundary,
    )
    assert after_rows is not None
    assert after_rows[-1]["event_time"] == bucket_close_ms

    payload = json.loads(after_boundary.store[key])
    payload["request_started_at_ms"] = f"{bucket_close_ms}.9999"
    fractional_cutoff = FakeRedis()
    fractional_cutoff.store[key] = json.dumps(payload, separators=(",", ":"))

    assert (
        loop._coinank_oi_hist_rows("BTCUSDT", redis_client=fractional_cutoff)
        is None
    )
    assert (
        loop._coinank_point_open_interest("BTCUSDT", redis_client=fractional_cutoff)
        is None
    )
    assert (
        loop._open_interest_cache_age_seconds(
            {"time": f"{observed_ms}.0001"}
        )
        is None
    )


def test_coinank_missing_or_boundary_straddling_request_cutoff_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket_open_ms = 1_800_000_000_000
    bucket_close_ms = bucket_open_ms + 300_000
    response_available_ms = bucket_close_ms + 1_000
    key = "latest:coinank:open_interest:BTCUSDT:5m"
    monkeypatch.setattr(
        loop.time,
        "time",
        lambda: response_available_ms / 1_000.0,
    )
    missing_cutoff = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=response_available_ms,
                begins_ms=[bucket_open_ms],
                request_started_at_ms=None,
            )
        }
    )
    straddled = FakeRedis(
        {
            key: _coinank_payload(
                fetched_ms=response_available_ms,
                begins_ms=[bucket_open_ms],
                request_started_at_ms=bucket_close_ms - 1_000,
            )
        }
    )

    assert loop._coinank_oi_hist_rows("BTCUSDT", redis_client=missing_cutoff) is None
    assert loop._coinank_oi_hist_rows("BTCUSDT", redis_client=straddled) is None


def test_binance_rest_kline_finality_is_bound_to_request_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_started_ms = 1_800_000_000_000
    response_received_ms = request_started_ms + 2_000
    rows = [
        _rest_kline(
            open_ms=request_started_ms - 60_000,
            close_ms=request_started_ms - 1,
        ),
        _rest_kline(
            open_ms=request_started_ms - 59_999,
            close_ms=request_started_ms,
        ),
        _rest_kline(
            open_ms=request_started_ms - 58_999,
            close_ms=request_started_ms + 1_000,
        ),
    ]
    clocks = iter((request_started_ms, response_received_ms))
    monkeypatch.setattr(loop, "_observed_epoch_ms", lambda: next(clocks))
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: False)
    monkeypatch.setattr(loop, "_http_get_json", lambda *_args, **_kwargs: rows)

    result = loop._fetch_klines(
        "BTCUSDT",
        interval="1m",
        redis_client=FakeRedis(),
    )

    assert result is not None
    assert len(result) == 1
    assert result[0]["candle_close_time"] == request_started_ms - 1
    assert result[0]["ingested_at"] == response_received_ms
    assert result[0]["available_at"] == response_received_ms
    assert result[0]["is_closed"] is True
    assert result[0]["source_receipt_authority"] is False
    assert result[0]["trainer_authority"] is False


def test_binance_rest_clock_reversal_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clocks = iter((1_800_000_002_000, 1_800_000_001_999))
    monkeypatch.setattr(loop, "_observed_epoch_ms", lambda: next(clocks))
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: False)
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda *_args, **_kwargs: [
            _rest_kline(
                open_ms=1_799_999_940_000,
                close_ms=1_799_999_999_999,
            )
        ],
    )

    assert (
        loop._fetch_klines(
            "BTCUSDT",
            interval="1m",
            redis_client=FakeRedis(),
        )
        is None
    )


def test_cached_websocket_rows_require_explicit_causal_finality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at_ms = 1_800_000_120_000
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    common = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "source": "binance_wss",
        "transport": "websocket_primary",
    }
    invalid_open = {
        **common,
        "candle_close_time": observed_at_ms - 1,
        "available_at": observed_at_ms,
        "is_closed": False,
        "feature_eligible": False,
    }
    invalid_future = {
        **common,
        "candle_close_time": observed_at_ms + 1,
        "available_at": observed_at_ms,
        "is_closed": True,
        "feature_eligible": True,
    }
    valid = {
        **common,
        "candle_close_time": observed_at_ms - 1,
        "available_at": observed_at_ms,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "feature_eligible": True,
    }
    redis_client = FakeRedis({key: [invalid_open, invalid_future, valid]})
    monkeypatch.setattr(loop, "_observed_epoch_ms", lambda: observed_at_ms)
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda *_args, **_kwargs: pytest.fail("valid WSS cache must precede REST"),
    )

    result = loop._fetch_klines(
        "BTCUSDT",
        interval="1m",
        redis_client=redis_client,
    )

    assert result is not None
    assert len(result) == 1
    assert result[0]["candle_close_time"] == observed_at_ms - 1
    assert result[0]["source_receipt_authority"] is False
    assert result[0]["trainer_authority"] is False
    written: list[str] = []
    sink = FakeRedis()
    loop._write_symbol_bundle(
        sink,
        "BTCUSDT",
        {"klines_by_timeframe": {"1m": result}},
        written,
    )
    stored = json.loads(sink.store["v2:market:ohlcv:binance:BTCUSDT:1m"])
    assert stored[0]["source_receipt_authority"] is False
    assert stored[0]["trainer_authority"] is False
    assert loop._contains_unverified_publication_claim(stored[0]) is False


def test_cached_websocket_fractional_future_availability_fails_closed() -> None:
    observed_at_ms = 1_800_000_120_000
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "source": "binance_wss",
        "transport": "websocket_primary",
        "candle_close_time": observed_at_ms - 1,
        "available_at": f"{observed_at_ms}.1",
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "feature_eligible": True,
    }

    assert (
        loop._finalized_cached_websocket_kline(
            row,
            observed_at_ms=observed_at_ms,
        )
        is None
    )


@pytest.mark.parametrize(
    ("claim_field", "claim_value"),
    [
        ("source_receipt_authority", True),
        ("trainer_authority", True),
        ("postcommit_observed_at", 1_800_000_120_000),
        ("postcommit_receipt_sha256", "a" * 64),
        ("postcommit_readback_verified", True),
        ("durable_postcommit_readback_verified", True),
        ("source_read_receipt", {"verified": True}),
        ("source_read_receipt_v4", {"verified": True}),
        ("receipt_sha256", "b" * 64),
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_cached_websocket_inherited_receipt_claim_fails_closed(
    claim_field: str,
    claim_value: Any,
    nested: bool,
) -> None:
    observed_at_ms = 1_800_000_120_000
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "source": "binance_wss",
        "transport": "websocket_primary",
        "candle_close_time": observed_at_ms - 1,
        "available_at": observed_at_ms,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "feature_eligible": True,
    }
    if nested:
        row["nested_claim"] = {claim_field: claim_value}
    else:
        row[claim_field] = claim_value

    assert (
        loop._finalized_cached_websocket_kline(
            row,
            observed_at_ms=observed_at_ms,
        )
        is None
    )
