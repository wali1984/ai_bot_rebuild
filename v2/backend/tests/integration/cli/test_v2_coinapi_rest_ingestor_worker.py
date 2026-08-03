from __future__ import annotations

import io
import json
import math
import sys
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[5]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from v2.backend.app.cli import v2_coinapi_rest_ingestor_worker as rest  # noqa: E402

COINAPI_SYMBOL_ID = "BINANCEFTS_PERP_BTC_USDT"
COINAPI_EXCHANGE_ID = "BINANCEFTS"


class StatefulRedis:
    def __init__(self, *, set_ack: object = True) -> None:
        self.set_ack = set_ack
        self.keys: list[str] = []
        self.fences: dict[str, dict[str, str]] = {}
        self.payloads: dict[str, str] = {}
        self.payload_ttls_ms: dict[str, int] = {}
        self.conflicts: dict[str, str] = {}
        self.auth_records: dict[str, dict[str, str]] = {}
        self.cadence_records: dict[str, dict[str, str]] = {}
        self.expiry_refreshes: dict[str, int] = {}
        self.lock = threading.Lock()

    def set(self, key: str, *args: object, **kwargs: object) -> object:
        del args, kwargs
        if self.set_ack is True:
            self.keys.append(key)
        return self.set_ack

    def hmget(self, key: str, *fields: str) -> list[str | None]:
        record = self.auth_records.get(key) or self.cadence_records.get(key) or {}
        return [record.get(field) for field in fields]

    def pttl(self, key: str) -> int:
        if key in self.auth_records or key in self.cadence_records:
            return -1
        return self.payload_ttls_ms.get(key, -2)

    def exists(self, key: str) -> int:
        return int(
            key in self.auth_records
            or key in self.cadence_records
            or key in self.payloads
            or key in self.fences
        )

    def delete(self, key: str) -> int:
        removed = key in self.auth_records or key in self.cadence_records
        self.auth_records.pop(key, None)
        self.cadence_records.pop(key, None)
        return int(removed)

    def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
        if "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script:
            assert numkeys == 1
            key, identity_field, payload_field, identity_limit, payload_limit = args
            record = self.auth_records.get(str(key)) or self.cadence_records.get(str(key))
            if record is None:
                return [rest._STATE_READ_MISSING, "", ""]
            if self.pttl(str(key)) != -1:
                return [rest._STATE_READ_INVALID, "", ""]
            identity = record.get(str(identity_field))
            payload = record.get(str(payload_field))
            if identity is None or payload is None:
                return [rest._STATE_READ_INVALID, "", ""]
            identity_length = len(identity.encode("utf-8"))
            payload_length = len(payload.encode("utf-8"))
            if identity_length > int(str(identity_limit)) or payload_length > int(
                str(payload_limit)
            ):
                return [rest._STATE_READ_OVERSIZED, identity_length, payload_length]
            return [rest._STATE_READ_OK, identity, payload]
        assert "decimal_compare" in script
        if "AUTH_STATE_COMMITTED_NEWER" in script:
            assert numkeys == 1
            key, revision, payload, identity_limit, payload_limit = args
            assert identity_limit == rest.MAX_STATE_IDENTITY_BYTES
            assert payload_limit == rest.MAX_STATE_JSON_BYTES
            current = self.auth_records.get(str(key))
            if current is not None:
                incoming = int(str(revision))
                previous = int(current["revision_ns"])
                if incoming < previous:
                    return [rest._AUTH_STATE_OLDER, 0]
                if incoming == previous:
                    if str(payload) == current["payload"]:
                        return [rest._AUTH_STATE_CURRENT, 0]
                    return [rest._AUTH_STATE_CONFLICT, 0]
            self.auth_records[str(key)] = {
                "revision_ns": str(revision),
                "payload": str(payload),
            }
            return [rest._AUTH_STATE_COMMITTED, 1]
        assert "PERSIST" in script
        assert numkeys == 3
        (
            fence_key,
            data_key,
            conflict_key,
            event,
            digest,
            payload,
            ttl,
            identity_limit,
            payload_limit,
        ) = args
        assert identity_limit == rest.MAX_STATE_IDENTITY_BYTES
        assert payload_limit == rest.MAX_REDIS_QUARANTINE_JSON_BYTES
        assert all(
            isinstance(item, str)
            for item in (fence_key, data_key, conflict_key, event, digest, payload)
        )
        assert type(ttl) is int and ttl > 0
        with self.lock:
            current = self.fences.get(str(fence_key))
            current_ttl = self.payload_ttls_ms.get(str(data_key), -2)
            if current is not None:
                incoming_int = int(str(event))
                current_int = int(current["event"])
                if incoming_int < current_int:
                    return [rest._FENCE_OLDER, 0, current_ttl]
                if incoming_int == current_int:
                    if str(digest) == current["digest"]:
                        return [rest._FENCE_DUPLICATE, 0, current_ttl]
                    if str(conflict_key) in self.conflicts:
                        return [rest._FENCE_CONFLICT_DUPLICATE, 0, current_ttl]
                    self.conflicts[str(conflict_key)] = str(payload)
                    return [rest._FENCE_CONFLICT, 1, current_ttl]
            self.fences[str(fence_key)] = {
                "event": str(event),
                "digest": str(digest),
            }
            self.payloads[str(data_key)] = str(payload)
            self.payload_ttls_ms[str(data_key)] = ttl * 1000
            self.expiry_refreshes[str(data_key)] = self.expiry_refreshes.get(str(data_key), 0) + 1
            return [rest._FENCE_COMMITTED, 1, ttl * 1000]


class NeverEvalRedis:
    def __init__(self) -> None:
        self.eval_calls = 0

    def eval(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.eval_calls += 1
        raise AssertionError("invalid raw payload reached Redis EVAL")


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}

    def read(self, limit: int) -> bytes:
        return self.body[:limit]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args


class FakeOpener:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.requests: list[Any] = []

    def open(self, request: Any, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _orderbook_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "symbol_id": "BINANCEFTS_PERP_BTC_USDT",
        "time_exchange": "2026-07-20T12:00:00.000000100Z",
        "time_coinapi": "2026-07-20T12:00:00.000000200Z",
        "bids": [{"price": 100, "size": 1}, {"price": 99, "size": 2}],
        "asks": [{"price": 101, "size": 3}, {"price": 102, "size": 4}],
    }
    body.update(overrides)
    return body


def _ohlcv_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "symbol_id": "BINANCEFTS_PERP_BTC_USDT",
        "period_id": "5MIN",
        "time_period_start": "2026-07-20T12:00:00Z",
        "time_period_end": "2026-07-20T12:05:00Z",
        "time_open": "2026-07-20T12:00:01Z",
        "time_close": "2026-07-20T12:04:59Z",
        "price_open": 100,
        "price_high": 102,
        "price_low": 99,
        "price_close": 101,
        "volume_traded": 0,
        "trades_count": 0,
    }
    body.update(overrides)
    return body


def _raw_orderbook_payload(event: int, *, bid: float = 100.0) -> dict[str, object]:
    source_event_time = rest.iso_utc_ns(event)
    provider_received_time = rest.iso_utc_ns(event)
    observed_at = rest.iso_utc_ns(((event // 1_000) + 1) * 1_000)
    ingested_at = rest.iso_utc_ns(((event // 1_000) + 2) * 1_000)
    generated_at = rest.iso_utc_ns(((event // 1_000) + 3) * 1_000)
    return {
        "schema_version": "v2_coinapi_rest_orderbook_quarantine_v3",
        "provider_identity_schema_version": rest.PROVIDER_IDENTITY_SCHEMA_VERSION,
        "trust_schema_version": rest.TRUST_SCHEMA_VERSION,
        "enforcement_epoch": rest.ENFORCEMENT_EPOCH,
        "producer_version": rest.TRUST_PRODUCER_VERSION,
        "symbol": "BTCUSDT",
        "coinapi_symbol_id": COINAPI_SYMBOL_ID,
        "coinapi_exchange_id": COINAPI_EXCHANGE_ID,
        "coinapi_market_type": "PERP",
        "source": "coinapi_rest_orderbooks3_current",
        "quarantine_only": True,
        "source_event_time": source_event_time,
        "source_event_ts_ms": event // 1_000_000,
        "source_event_ts_ns": event,
        "provider_received_time": provider_received_time,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "generated_at": generated_at,
        "generated_utc": generated_at,
        "time_exchange": source_event_time,
        "time_coinapi": provider_received_time,
        "best_bid_px": bid,
        "best_ask_px": bid + 1.0,
        "best_bid_sz": 1.0,
        "best_ask_sz": 1.0,
        "mid_px": bid + 0.5,
        "spread_bps": 10_000.0 / (bid + 0.5),
        "micro_price": bid + 0.5,
        "book_bid_sum_5": 1.0,
        "book_ask_sum_5": 1.0,
        "imbalance_5": 0.0,
        "bids_top5": [{"price": bid, "size": 1.0}],
        "asks_top5": [{"price": bid + 1.0, "size": 1.0}],
        "available_at": None,
        "postcommit_receipt_present": False,
        "feature_eligible": False,
        "trainer_consumable": False,
        "prediction_eligible": False,
        "trust_block_reasons": list(rest.RAW_TRUST_BLOCK_REASONS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        **rest.OPTIONAL_SOURCE_FIELDS,
    }


def test_rest_endpoint_allowlist_and_no_redirect_transport(monkeypatch) -> None:
    for rejected in (
        "http://rest.coinapi.io:443",
        "https://rest.coinapi.io",
        "https://user@rest.coinapi.io:443",
        "https://rest.coinapi.io:443/base",
        "https://rest.coinapi.io:443/?key=secret",
        "https://rest.coinapi.io:443/#fragment",
        "https://evil.invalid:443/",
    ):
        with pytest.raises(ValueError, match="allowlisted"):
            rest._validate_rest_base_url(rejected)

    opener = FakeOpener(FakeResponse(b'{"ok":true}'))
    handlers: list[object] = []

    def fake_build_opener(handler: object) -> FakeOpener:
        handlers.append(handler)
        return opener

    monkeypatch.setattr(rest.urllib.request, "build_opener", fake_build_opener)
    status, body, _metadata = rest._http_get_json(
        rest.COINAPI_REST_BASE,
        "/v1/orderbooks3/current",
        api_key="secret-never-emitted",
        params={"filter_symbol_id": "COINAPI_BTC"},
        timeout_seconds=1.0,
    )

    assert status == 200
    assert body == {"ok": True}
    assert len(opener.requests) == 1
    assert isinstance(handlers[0], rest._NoRedirectHandler)
    assert opener.requests[0].full_url.startswith(
        "https://rest.coinapi.io:443/v1/orderbooks3/current?"
    )


def test_rest_redirect_is_not_followed_and_response_bytes_are_bounded() -> None:
    redirect = urllib.error.HTTPError(
        rest.COINAPI_REST_BASE,
        302,
        "redirect",
        {"Location": "https://evil.invalid/steal"},
        io.BytesIO(b"{}"),
    )
    redirect_opener = FakeOpener(redirect)
    status, _body, _metadata = rest._http_get_json(
        rest.COINAPI_REST_BASE,
        "/v1/orderbooks3/current",
        api_key="secret-never-emitted",
        params={},
        timeout_seconds=1.0,
        opener=redirect_opener,
    )
    assert status == 302
    assert len(redirect_opener.requests) == 1

    oversized = FakeOpener(FakeResponse(b"x" * (rest.MAX_REST_RESPONSE_BYTES + 1)))
    status, body, metadata = rest._http_get_json(
        rest.COINAPI_REST_BASE,
        "/v1/orderbooks3/current",
        api_key="secret-never-emitted",
        params={},
        timeout_seconds=1.0,
        opener=oversized,
    )
    assert (status, body, metadata) == (598, None, {})


def test_rest_deep_json_is_typed_missing_without_recursion_escape() -> None:
    deeply_nested = ("[" * 2_000 + "0" + "]" * 2_000).encode()
    status, body, metadata = rest._http_get_json(
        rest.COINAPI_REST_BASE,
        "/v1/orderbooks3/current",
        api_key="secret-never-emitted",
        params={},
        timeout_seconds=1.0,
        opener=FakeOpener(FakeResponse(deeply_nested)),
    )
    assert status == 200
    assert body is None
    assert metadata == {}


def test_rest_direct_string_utf8_count_is_incremental_and_bounded() -> None:
    multibyte = '"' + ("é" * (rest.UTF8_COUNT_CHUNK_CHARACTERS + 1)) + '"'
    exact_bytes = 2 + (2 * (rest.UTF8_COUNT_CHUNK_CHARACTERS + 1))

    assert rest._utf8_length_within_limit(multibyte, max_bytes=exact_bytes)
    assert not rest._utf8_length_within_limit(multibyte, max_bytes=exact_bytes - 1)
    assert rest._loads_bounded_json(
        multibyte,
        max_bytes=exact_bytes,
        max_depth=rest.MAX_REST_JSON_DEPTH,
        max_items=rest.MAX_REST_JSON_ITEMS,
    ) == "é" * (rest.UTF8_COUNT_CHUNK_CHARACTERS + 1)
    assert (
        rest._loads_bounded_json(
            "x" * (rest.MAX_STATE_JSON_BYTES + 1),
            max_bytes=rest.MAX_STATE_JSON_BYTES,
            max_depth=16,
            max_items=64,
        )
        is None
    )


@pytest.mark.parametrize(
    "raw",
    (
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'{"value":1e999}',
        b'{"nested":[{"value":-1e999}]}',
    ),
)
def test_rest_bounded_json_rejects_nonfinite_constants_and_overflow(raw: bytes) -> None:
    assert (
        rest._loads_bounded_json(
            raw,
            max_bytes=rest.MAX_REST_RESPONSE_BYTES,
            max_depth=rest.MAX_REST_JSON_DEPTH,
            max_items=rest.MAX_REST_JSON_ITEMS,
        )
        is None
    )


def test_rest_non_2xx_body_is_typed_before_normalization_and_nonterminal_fanout_continues(
    monkeypatch,
) -> None:
    calls = 0

    def rejected(*args: object, **kwargs: object) -> tuple[int, object, dict[str, int]]:
        nonlocal calls
        del args, kwargs
        calls += 1
        return 404, _orderbook_body(symbol_id="BINANCEFTS_PERP_BTC_USDT"), {}

    monkeypatch.setattr(rest, "_http_get_json", rejected)
    monkeypatch.setattr(rest, "_rate_limit_sleep", lambda *args: None)
    monkeypatch.setattr(
        rest,
        "_normalize_orderbook",
        lambda *args, **kwargs: pytest.fail("non-2xx body reached normalizer"),
    )
    result = rest.fetch_for_symbols(
        ("BTCUSDT", "ETHUSDT"),
        api_key="configured-key",
        rest_base_url=rest.COINAPI_REST_BASE,
        exchange_id="BINANCEFTS",
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        ohlcv_timeframes=("5m",),
        ohlcv_symbol_limit=None,
        timeout_seconds=1.0,
        max_rps=10.0,
    )

    assert calls == 2
    assert result["fanout_stopped_early"] is False
    assert result["symbols_fetched"] == 2
    assert all(row["orderbook"] is None for row in result["rows"])
    assert all(
        row["orderbook_failure"]["provider_error_class"] == "PROVIDER_HTTP_CLIENT_ERROR"
        for row in result["rows"]
    )


def test_rest_ohlcv_non_2xx_after_orderbook_success_is_degraded_typed_missing(
    monkeypatch,
) -> None:
    responses = iter(
        (
            (200, {"valid": "orderbook"}, {}),
            (500, _ohlcv_body(symbol_id="BINANCEFTS_PERP_BTC_USDT"), {}),
        )
    )
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(rest, "_http_get_json", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(rest, "_rate_limit_sleep", lambda *args: None)
    monkeypatch.setattr(
        rest,
        "_normalize_orderbook",
        lambda *args, **kwargs: {"source_event_ts_ns": 123},
    )
    monkeypatch.setattr(
        rest,
        "_normalize_ohlcv",
        lambda *args, **kwargs: pytest.fail("non-2xx OHLCV reached normalizer"),
    )

    payload = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=True,
        ohlcv_timeframes=("5m",),
        ohlcv_symbol_limit=1,
        write_v2_redis=False,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )

    row = payload["fetch"]["rows"][0]
    assert payload["classification"] == "V2_COINAPI_REST_OPTIONAL_DEGRADED_PARTIAL"
    assert payload["provider_data_available"] is True
    assert payload["typed_missing"] is True
    assert row["ohlcv_failures"]["5m"]["provider_error_class"] == ("PROVIDER_HTTP_SERVER_ERROR")
    assert row["ohlcv_typed_missing_timeframes"] == ["5m"]


def test_rest_redis_ack_types_are_exact_and_fail_closed() -> None:
    for bad_ack in (False, 1, "OK", b"OK", None, RuntimeError("failure")):
        if isinstance(bad_ack, Exception):

            class RaisingRedis:
                def __init__(self, error: Exception) -> None:
                    self.error = error

                def set(self, *args: object, **kwargs: object) -> object:
                    del args, kwargs
                    raise self.error

            client: Any = RaisingRedis(bad_ack)
        else:
            client = StatefulRedis(set_ack=bad_ack)
        assert rest._safe_set_json(client, "v2:test", {"ok": True}, ex=60) is False
    assert rest._safe_set_json(StatefulRedis(), "v2:test", {"ok": True}, ex=60)


@pytest.mark.parametrize(
    "reply",
    (
        (rest._FENCE_COMMITTED, 1, 60_000),
        [rest._FENCE_COMMITTED, True, 60_000],
        [rest._FENCE_COMMITTED, 1, True],
        [rest._FENCE_COMMITTED, 0, 60_000],
        [rest._FENCE_COMMITTED, 1, 0],
        ["UNKNOWN", 1, 60_000],
    ),
)
def test_rest_atomic_fence_rejects_malformed_or_inexact_eval_ack(reply: object) -> None:
    class Redis:
        def eval(self, *args: object) -> object:
            del args
            return reply

    result = rest._atomic_fenced_quarantine_write(
        Redis(),
        fence_key=rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        data_key=rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        conflict_key="v2:quarantine:coinapi:rest:conflict:test",
        event_identity_ns="1",
        payload={"source_event_ts_ns": 1},
        ex=60,
    )
    assert result == (rest._FENCE_ERROR, -2)


def test_rest_orderbook_requires_identity_received_clock_and_ordering() -> None:
    observed = datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    invalid = (
        _orderbook_body(symbol_id="OTHER"),
        _orderbook_body(time_coinapi=None),
        _orderbook_body(bids=[{"price": 99, "size": 1}, {"price": 100, "size": 1}]),
        _orderbook_body(asks=[{"price": 102, "size": 1}, {"price": 101, "size": 1}]),
        _orderbook_body(bids=[{"price": 100, "size": True}]),
        _orderbook_body(asks=[{"price": math.inf, "size": 1}]),
    )
    for body in invalid:
        assert (
            rest._normalize_orderbook(
                "BTCUSDT", "BINANCEFTS_PERP_BTC_USDT", body, observed_at=observed
            )
            is None
        )


@pytest.mark.parametrize(
    "extreme_timestamp",
    (
        "0001-01-01T00:00:00+23:59",
        "9999-12-31T23:59:59-23:59",
    ),
)
def test_rest_orderbook_rejects_timestamp_utc_normalization_overflow(
    extreme_timestamp: str,
) -> None:
    body = _orderbook_body(
        time_exchange=extreme_timestamp,
        time_coinapi=extreme_timestamp,
    )

    assert (
        rest._normalize_orderbook(
            "BTCUSDT",
            "BINANCEFTS_PERP_BTC_USDT",
            body,
            observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
        )
        is None
    )


def test_rest_orderbook_preserves_zero_and_submillisecond_identity_with_strict_clocks() -> None:
    normalized = rest._normalize_orderbook(
        "BTCUSDT",
        "BINANCEFTS_PERP_BTC_USDT",
        _orderbook_body(
            bids=[{"price": 100, "size": 0}],
            asks=[{"price": 101, "size": 0}],
        ),
        observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
    )

    assert normalized is not None
    assert normalized["source_event_ts_ns"] == 1_784_548_800_000_000_100
    assert normalized["best_bid_sz"] == normalized["best_ask_sz"] == 0.0
    assert normalized["micro_price"] is None
    assert normalized["imbalance_5"] is None
    event = rest.parse_provider_timestamp(normalized["source_event_time"])
    received = rest.parse_provider_timestamp(normalized["provider_received_time"])
    observed = rest.parse_provider_timestamp(normalized["observed_at"])
    ingested = rest.parse_provider_timestamp(normalized["ingested_at"])
    generated = rest.parse_provider_timestamp(normalized["generated_at"])
    assert event and received and observed and ingested and generated
    assert event[1] <= received[1] <= observed[1] < ingested[1] < generated[1]


def test_rest_ohlcv_requires_deterministic_latest_boundary_and_strict_finality() -> None:
    accepted = rest._normalize_ohlcv(
        "BTCUSDT",
        "BINANCEFTS_PERP_BTC_USDT",
        "5m",
        "5MIN",
        _ohlcv_body(),
        observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
    )
    assert accepted is not None
    assert accepted["volume"] == 0.0
    assert accepted["trades_count"] == 0
    assert accepted["event_ts_ns"] == 1_784_549_100_000_000_000
    assert accepted["trust_schema_version"]
    assert accepted["trainer_consumable"] is False

    assert (
        rest._normalize_ohlcv(
            "BTCUSDT",
            "BINANCEFTS_PERP_BTC_USDT",
            "5m",
            "5MIN",
            _ohlcv_body(),
            observed_at=datetime(2026, 7, 20, 12, 5, 0, tzinfo=UTC),
        )
        is None
    )
    assert (
        rest._normalize_ohlcv(
            "BTCUSDT",
            "BINANCEFTS_PERP_BTC_USDT",
            "5m",
            "5MIN",
            _ohlcv_body(),
            observed_at=datetime(2026, 7, 20, 12, 10, 0, 1, tzinfo=UTC),
        )
        is None
    )
    assert (
        rest._normalize_ohlcv(
            "BTCUSDT",
            "BINANCEFTS_PERP_BTC_USDT",
            "5m",
            "5MIN",
            _ohlcv_body(time_close="2026-07-20T12:05:00Z"),
            observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol_id", "OTHER"),
        ("period_id", "1MIN"),
        ("volume_traded", True),
        ("trades_count", False),
        ("price_open", math.nan),
        ("time_open", "2026-07-20T11:59:59Z"),
        ("time_close", "2026-07-20T12:05:01Z"),
        ("trades_count", "1.00000000000000001"),
    ],
)
def test_rest_ohlcv_rejects_identity_boolean_nonfinite_and_interval_violations(
    field: str,
    value: object,
) -> None:
    assert (
        rest._normalize_ohlcv(
            "BTCUSDT",
            "BINANCEFTS_PERP_BTC_USDT",
            "5m",
            "5MIN",
            _ohlcv_body(**{field: value}),
            observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
        )
        is None
    )


@pytest.mark.parametrize(
    ("canonical", "legacy"),
    (
        ("price_open", "open"),
        ("price_high", "high"),
        ("price_low", "low"),
        ("price_close", "close"),
        ("volume_traded", "volume"),
    ),
)
def test_rest_ohlcv_rejects_legacy_value_aliases_without_canonical_fields(
    canonical: str,
    legacy: str,
) -> None:
    legacy_only = _ohlcv_body()
    legacy_only[legacy] = legacy_only.pop(canonical)

    assert (
        rest._normalize_ohlcv(
            "BTCUSDT",
            COINAPI_SYMBOL_ID,
            "5m",
            "5MIN",
            legacy_only,
            observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
        )
        is None
    )
    canonical_and_legacy = _ohlcv_body(**{legacy: legacy_only[legacy]})
    assert (
        rest._normalize_ohlcv(
            "BTCUSDT",
            COINAPI_SYMBOL_ID,
            "5m",
            "5MIN",
            canonical_and_legacy,
            observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
        )
        is None
    )


def test_rest_atomic_fence_rejects_older_and_duplicate_without_ttl_refresh() -> None:
    redis_client = StatefulRedis()
    fence_key = rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
    )
    data_key = rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
    )

    def write(event: int, bid: float = 100.0) -> tuple[str, int]:
        payload = _raw_orderbook_payload(event, bid=bid)
        digest = rest._provider_content_digest(payload)
        assert digest is not None
        return rest._atomic_fenced_quarantine_write(
            redis_client,
            fence_key=fence_key,
            data_key=data_key,
            conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                event_ns=event,
                digest=digest,
            ),
            event_identity_ns=str(event),
            payload=payload,
            ex=60,
        )

    assert write(1_000_000_100) == (rest._FENCE_COMMITTED, 60_000)
    assert write(1_000_000_100) == (rest._FENCE_DUPLICATE, 60_000)
    assert write(1_000_000_099) == (rest._FENCE_OLDER, 60_000)
    assert redis_client.expiry_refreshes[data_key] == 1
    assert write(1_000_000_100, bid=99.0) == (rest._FENCE_CONFLICT, 60_000)
    assert redis_client.expiry_refreshes[data_key] == 1
    assert write(1_000_000_200) == (rest._FENCE_COMMITTED, 60_000)
    assert redis_client.expiry_refreshes[data_key] == 2
    assert fence_key in redis_client.fences


def test_rest_atomic_fence_recovers_on_newer_event_after_payload_ttl_expiry() -> None:
    redis_client = StatefulRedis()
    fence_key = rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
    )
    data_key = rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
    )

    def write(event: int) -> tuple[str, int]:
        payload = _raw_orderbook_payload(event, bid=float(event))
        digest = rest._provider_content_digest(payload)
        assert digest is not None
        return rest._atomic_fenced_quarantine_write(
            redis_client,
            fence_key=fence_key,
            data_key=data_key,
            conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                event_ns=event,
                digest=digest,
            ),
            event_identity_ns=str(event),
            payload=payload,
            ex=60,
        )

    assert write(100) == (rest._FENCE_COMMITTED, 60_000)
    redis_client.payloads.pop(data_key)
    redis_client.payload_ttls_ms.pop(data_key)

    assert fence_key in redis_client.fences
    assert write(101) == (rest._FENCE_COMMITTED, 60_000)
    assert data_key in redis_client.payloads
    assert redis_client.expiry_refreshes[data_key] == 2


def test_rest_atomic_fence_is_single_eval_and_submillisecond_concurrent_safe() -> None:
    redis_client = StatefulRedis()
    fence_key = rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
    )
    data_key = rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
    )

    def write(event: int) -> tuple[str, int]:
        payload = _raw_orderbook_payload(event, bid=float(event))
        digest = rest._provider_content_digest(payload)
        assert digest is not None
        return rest._atomic_fenced_quarantine_write(
            redis_client,
            fence_key=fence_key,
            data_key=data_key,
            conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                event_ns=event,
                digest=digest,
            ),
            event_identity_ns=str(event),
            payload=payload,
            ex=60,
        )

    events = [1_784_548_800_000_000_100, 1_784_548_800_000_000_900]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, events))
    assert any(result[0] == rest._FENCE_COMMITTED for result in results)
    assert redis_client.fences[fence_key]["event"] == str(max(events))


def test_rest_ohlcv_uses_one_atomic_monotonic_quarantine_publication() -> None:
    candle = rest._normalize_ohlcv(
        "BTCUSDT",
        "BINANCEFTS_PERP_BTC_USDT",
        "5m",
        "5MIN",
        _ohlcv_body(),
        observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
    )
    assert candle is not None
    redis_client = StatefulRedis()
    fetch = {
        "finished_utc": "2026-07-20T12:05:01Z",
        "provider_health": None,
        "per_symbol_health": {"BTCUSDT": {}},
        "rows": [{"symbol": "BTCUSDT", "orderbook": None, "ohlcv": {"5m": candle}}],
    }
    written = rest.persist_to_v2_redis(redis_client, fetch, ttl_seconds=60)

    data_key = rest.REST_OHLCV_DATA_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
        timeframe="5m",
    )
    fence_key = rest.REST_OHLCV_FENCE_KEY_TEMPLATE.format(
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        symbol="BTCUSDT",
        timeframe="5m",
    )
    assert data_key in written
    assert fence_key in written
    assert fence_key in redis_client.fences
    assert json.loads(redis_client.payloads[data_key]) == candle
    assert fetch["rows"][0]["ohlcv_commit_states"] == {"5m": rest._FENCE_COMMITTED}
    assert fetch["publication_stats"]["ohlcv_committed"] == 1
    assert not any(
        key.startswith(
            (
                "v2:latest:coinapi:",
                "v2:normalized:coinapi:",
                "v2:market:coinapi:",
                "v2:ohlcv:list:coinapi:",
            )
        )
        for key in (*written, *redis_client.keys)
    )
    for field in (
        "schema_version",
        "trust_schema_version",
        "enforcement_epoch",
        "producer_version",
        "postcommit_receipt_present",
        "trainer_consumable",
        "trust_block_reasons",
    ):
        assert field in redis_client.payloads[data_key]

    repeated_candle = rest._normalize_ohlcv(
        "BTCUSDT",
        "BINANCEFTS_PERP_BTC_USDT",
        "5m",
        "5MIN",
        _ohlcv_body(),
        observed_at=datetime(2026, 7, 20, 12, 5, 0, 2, tzinfo=UTC),
    )
    assert repeated_candle is not None
    assert repeated_candle["ingested_ts_ms"] != candle["ingested_ts_ms"] or (
        repeated_candle["observed_at"] != candle["observed_at"]
    )
    assert rest._provider_content_digest(repeated_candle) == rest._provider_content_digest(candle)
    fetch["rows"][0]["ohlcv"] = {"5m": repeated_candle}
    second = rest.persist_to_v2_redis(redis_client, fetch, ttl_seconds=60)
    assert data_key not in second
    assert fetch["rows"][0]["ohlcv_commit_states"] == {"5m": rest._FENCE_DUPLICATE}
    assert redis_client.expiry_refreshes[data_key] == 1


def test_quota_403_uses_durable_sparse_reprobe_state_across_cycles(monkeypatch) -> None:
    calls = 0

    def rejected(*args: object, **kwargs: object) -> tuple[int, object, dict[str, int]]:
        nonlocal calls
        del args, kwargs
        calls += 1
        return 403, {"detail": "quota secret body"}, {"rate_limit_remaining": 0}

    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(rest, "_http_get_json", rejected)
    redis_client = StatefulRedis()
    monkeypatch.setattr(rest, "_connect_redis", lambda: redis_client)
    first = rest.build_payload(
        ("BTCUSDT", "ETHUSDT"),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=True,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )
    second = rest.build_payload(
        ("BTCUSDT", "ETHUSDT"),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=True,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )

    assert calls == 1
    assert (
        first["classification"]
        == second["classification"]
        == "V2_COINAPI_REST_OPTIONAL_AUTH_UNAVAILABLE"
    )
    assert second["fetch"]["durable_authorization_backoff"]["failure_count"] == 1
    assert second["fetch"]["requests_attempted"] == 0
    assert (
        second["fetch"]["durable_authorization_backoff"]["credential_fingerprint_emitted"] is False
    )
    assert second["live_data_enabled"] is False


@pytest.mark.parametrize("fault", ("exists", "read"))
def test_indeterminate_durable_auth_state_blocks_before_provider_probe(
    monkeypatch,
    fault: str,
) -> None:
    redis_client = StatefulRedis()

    def unavailable(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("durable state unavailable")

    if fault == "exists":
        monkeypatch.setattr(redis_client, "exists", unavailable)
    else:
        monkeypatch.setattr(redis_client, "exists", lambda key: 1)
        monkeypatch.setattr(redis_client, "eval", unavailable)
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(rest, "_connect_redis", lambda: redis_client)
    monkeypatch.setattr(
        rest,
        "_http_get_json",
        lambda *args, **kwargs: pytest.fail("provider probe occurred before durable read"),
    )

    payload = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=True,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )

    assert payload["classification"] == "V2_COINAPI_REST_OPTIONAL_RETRY_STATE_UNAVAILABLE"
    assert payload["provider_health"]["state"] == "OPTIONAL_RETRY_STATE_INVALID"
    assert payload["provider_health"]["provider_error_class"] == ("DURABLE_RETRY_STATE_INVALID")
    assert payload["fetch"]["requests_attempted"] == 0
    assert payload["durable_auth_retry_state_healthy"] is False
    assert payload["provider_data_usable"] is False
    assert payload["trainer_consumable"] is False
    assert payload["live_decision_input_enabled"] is False
    assert payload["trader_execution_enabled"] is False
    assert payload["live_gate"] == "blocked_human_only"


def test_rate_limit_reset_is_absolute_epoch_and_past_is_zero() -> None:
    assert (
        rest._provider_retry_delay_seconds(
            {"rate_limit_reset": 1_700_000_100}, now_epoch=1_700_000_000
        )
        == 100.0
    )
    assert (
        rest._provider_retry_delay_seconds(
            {"rate_limit_reset": 1_699_999_999}, now_epoch=1_700_000_000
        )
        == 0.0
    )
    assert (
        rest._provider_retry_delay_seconds(
            {"rate_limit_reset": 1_699_999_999, "rate_limit_reset_after_seconds": 7},
            now_epoch=1_700_000_000,
        )
        == 7.0
    )


def test_partial_rest_coverage_is_degraded_and_typed_missing(monkeypatch) -> None:
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(
        rest,
        "fetch_for_symbols",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "symbol": "BTCUSDT",
                    "orderbook_present": True,
                    "ohlcv_present_timeframes": [],
                    "typed_missing": False,
                },
                {
                    "symbol": "ETHUSDT",
                    "orderbook_present": False,
                    "ohlcv_present_timeframes": [],
                    "typed_missing": True,
                },
            ],
            "provider_health": None,
            "symbols_unprobed": 0,
            "typed_missing_rows": 1,
            "per_symbol_health": {
                "BTCUSDT": {"observed": True, "committed": False},
                "ETHUSDT": {"observed": True, "committed": False},
            },
        },
    )
    payload = rest.build_payload(
        ("BTCUSDT", "ETHUSDT"),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=False,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )
    assert payload["classification"] == "V2_COINAPI_REST_OPTIONAL_DEGRADED_PARTIAL"
    assert payload["typed_missing"] is True
    assert payload["degraded_partial"] is True
    assert payload["provider_data_available"] is True
    assert payload["provider_data_usable"] is False
    assert payload["live_decision_input_enabled"] is False


def test_malformed_optional_exchange_is_typed_unavailable_without_http(monkeypatch) -> None:
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.setenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS:INJECTED")
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(
        rest,
        "_http_get_json",
        lambda *args, **kwargs: pytest.fail("malformed exchange reached provider HTTP"),
    )

    payload = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=False,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )

    assert payload["classification"] == "V2_COINAPI_REST_OPTIONAL_CONFIGURATION_INVALID"
    assert payload["coinapi_exchange_id"] is None
    assert payload["provider_health"]["state"] == "OPTIONAL_CONFIGURATION_INVALID"
    assert payload["provider_health"]["provider_error_class"] == ("INVALID_PRIMARY_EXCHANGE_ID")
    assert payload["fetch"]["requests_attempted"] == 0
    assert payload["typed_missing"] is True
    assert payload["provider_data_usable"] is False
    assert payload["trainer_consumable"] is False
    assert payload["live_decision_input_enabled"] is False
    assert payload["trader_execution_enabled"] is False
    assert payload["schema_version"] == "v2_coinapi_rest_ingestor_status_v3"
    assert payload["quarantine_namespace_version"] == "v4"
    assert payload["cadence_namespace_version"] == "v4"
    assert payload["provider_identity_schema_version"] == (rest.PROVIDER_IDENTITY_SCHEMA_VERSION)
    assert payload["legacy_namespace_reads_enabled"] is False
    assert payload["legacy_namespace_migration_mode"] == "COLD_BOOTSTRAP_REQUIRED"


@pytest.mark.parametrize(
    ("timeout_seconds", "max_rps", "error_class"),
    (
        (math.nan, 0.5, "INVALID_TIMEOUT_SECONDS"),
        (math.inf, 0.5, "INVALID_TIMEOUT_SECONDS"),
        (0.0, 0.5, "INVALID_TIMEOUT_SECONDS"),
        (rest.MAX_REST_TIMEOUT_SECONDS + 1.0, 0.5, "INVALID_TIMEOUT_SECONDS"),
        (1.0, math.nan, "INVALID_MAX_RPS"),
        (1.0, math.inf, "INVALID_MAX_RPS"),
        (1.0, 0.0, "INVALID_MAX_RPS"),
        (1.0, rest.MAX_REST_MAX_RPS + 1.0, "INVALID_MAX_RPS"),
    ),
)
def test_rest_nonfinite_or_out_of_range_transport_config_is_typed_before_http(
    monkeypatch,
    timeout_seconds: float,
    max_rps: float,
    error_class: str,
) -> None:
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(
        rest,
        "_http_get_json",
        lambda *args, **kwargs: pytest.fail("invalid transport config reached HTTP"),
    )

    payload = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=False,
        ttl_seconds=60,
        timeout_seconds=timeout_seconds,
        max_rps=max_rps,
    )

    assert payload["classification"] == "V2_COINAPI_REST_OPTIONAL_CONFIGURATION_INVALID"
    assert payload["provider_health"]["provider_error_class"] == error_class
    assert payload["fetch"]["requests_attempted"] == 0
    assert payload["trainer_consumable"] is False
    assert payload["live_decision_input_enabled"] is False


def test_rest_rate_delay_rejects_zero_or_nonfinite_values(monkeypatch) -> None:
    for invalid in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="finite and positive"):
            rest._rate_limit_sleep(0.0, invalid)

    sleeps: list[float] = []
    monkeypatch.setattr(rest.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(rest.time, "sleep", sleeps.append)
    rest._rate_limit_sleep(10.0, 1.0 / rest.MAX_REST_MAX_RPS)
    assert sleeps == [1.0 / rest.MAX_REST_MAX_RPS]


def test_status_mkdir_failure_is_typed_and_sanitized(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    raw_error = "secret mkdir path marker"

    def fail_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        raise PermissionError(raw_error)

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    payload: dict[str, Any] = {"classification": "TEST"}
    assert rest.write_payload(payload, tmp_path / "nested" / "status.json") is False
    assert payload["status_file_write_healthy"] is False
    assert payload["status_file_write_error_classes"] == ["PermissionError"]
    assert payload["raw_status_file_error_recorded"] is False
    assert raw_error not in capsys.readouterr().err


def test_rest_old_orderbook_can_be_quarantined_but_cannot_self_authorize_freshness() -> None:
    orderbook = rest._normalize_orderbook(
        "BTCUSDT",
        "BINANCEFTS_PERP_BTC_USDT",
        _orderbook_body(
            time_exchange="2019-01-01T00:00:00Z",
            time_coinapi="2019-01-01T00:00:00.1Z",
        ),
        observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
    )
    assert orderbook is not None
    fetch: dict[str, Any] = {
        "finished_utc": "2026-07-20T12:00:01Z",
        "provider_health": None,
        "typed_missing_rows": 0,
        "rows": [
            {
                "symbol": "BTCUSDT",
                "orderbook": orderbook,
                "ohlcv": {},
                "typed_missing": False,
            }
        ],
        "per_symbol_health": {"BTCUSDT": {}},
    }
    client = StatefulRedis()
    rest.persist_to_v2_redis(
        client,
        fetch,
        ttl_seconds=60,
        api_key="configured-key",
    )
    assert fetch["publication_stats"]["committed"] == 1
    assert fetch["publication_stats"]["fresh"] == 0
    assert fetch["per_symbol_health"]["BTCUSDT"]["orderbook_committed"] is True
    assert fetch["per_symbol_health"]["BTCUSDT"]["orderbook_fresh"] is False
    assert fetch["per_symbol_health"]["BTCUSDT"]["fresh"] is False


def test_rest_prior_authenticated_ws_cadence_can_authorize_current_raw_book() -> None:
    api_key = "configured-key"
    previous_event = rest.datetime_epoch_ns(datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC))
    unsigned: dict[str, Any] = {
        "schema_version": rest.WS_CADENCE_SCHEMA_VERSION,
        "provider_identity_schema_version": rest.PROVIDER_IDENTITY_SCHEMA_VERSION,
        "symbol": "BTCUSDT",
        "coinapi_symbol_id": COINAPI_SYMBOL_ID,
        "coinapi_exchange_id": COINAPI_EXCHANGE_ID,
        "coinapi_market_type": "PERP",
        "sample_count": 3,
        "event_cadence_ns": 1_000_000_000,
        "provider_cadence_ns": 1_000_000_000,
        "arrival_cadence_ns": 1_000_000_000,
        "max_source_lag_ns": 100_000_000,
        "max_arrival_lag_ns": 100_000_000,
        "last_event_ns": previous_event,
        "last_provider_received_ns": previous_event + 100_000_000,
        "last_observed_ns": previous_event + 200_000_000,
        "generated_at": "2026-07-20T12:00:00.3Z",
    }
    signature = rest._ws_cadence_signature(api_key, unsigned)
    assert signature is not None
    basis = {**unsigned, "signature": signature}
    client = StatefulRedis()
    cadence_key = rest._ws_cadence_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        api_key=api_key,
    )
    assert cadence_key is not None
    client.cadence_records[cadence_key] = {
        "last_event_ns": str(previous_event),
        "payload": json.dumps(basis, sort_keys=True, separators=(",", ":")),
    }
    orderbook = rest._normalize_orderbook(
        "BTCUSDT",
        "BINANCEFTS_PERP_BTC_USDT",
        _orderbook_body(
            time_exchange="2026-07-20T12:00:01Z",
            time_coinapi="2026-07-20T12:00:01.1Z",
        ),
        observed_at=datetime(2026, 7, 20, 12, 0, 1, 200_000, tzinfo=UTC),
    )
    assert orderbook is not None
    fetch: dict[str, Any] = {
        "finished_utc": "2026-07-20T12:00:01.2Z",
        "provider_health": None,
        "typed_missing_rows": 0,
        "rows": [
            {
                "symbol": "BTCUSDT",
                "orderbook": orderbook,
                "ohlcv": {},
                "typed_missing": False,
            }
        ],
        "per_symbol_health": {"BTCUSDT": {}},
    }
    rest.persist_to_v2_redis(client, fetch, ttl_seconds=60, api_key=api_key)
    assert fetch["publication_stats"]["fresh"] == 1
    assert fetch["per_symbol_health"]["BTCUSDT"]["fresh"] is True


def test_rest_heartbeat_only_ack_is_not_current_data_publication(monkeypatch) -> None:
    client = StatefulRedis()
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(rest, "_connect_redis", lambda: client)
    monkeypatch.setattr(rest, "_rate_limit_sleep", lambda *args: None)
    monkeypatch.setattr(rest, "_http_get_json", lambda *args, **kwargs: (200, {}, {}))
    payload = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=False,
        write_v2_redis=True,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )
    assert payload["redis_ok"] is True
    assert payload["status_publication_healthy"] is True
    assert payload["publication_healthy"] is False
    assert payload["current_data_commit_acked"] is False
    assert payload["typed_missing"] is True


def test_provider_identity_binds_raw_fence_data_and_cadence_namespaces() -> None:
    observed = datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    okx_symbol_id = "OKX_SPOT_BTC_USDT"
    binance = rest._normalize_orderbook(
        "BTCUSDT",
        COINAPI_SYMBOL_ID,
        _orderbook_body(),
        observed_at=observed,
    )
    okx = rest._normalize_orderbook(
        "BTCUSDT",
        okx_symbol_id,
        _orderbook_body(symbol_id=okx_symbol_id),
        observed_at=observed,
    )
    assert binance is not None and okx is not None
    for payload, exchange_id, provider_symbol_id in (
        (binance, COINAPI_EXCHANGE_ID, COINAPI_SYMBOL_ID),
        (okx, "OKX", okx_symbol_id),
    ):
        assert payload["schema_version"] == "v2_coinapi_rest_orderbook_quarantine_v3"
        assert payload["provider_identity_schema_version"] == (
            rest.PROVIDER_IDENTITY_SCHEMA_VERSION
        )
        assert payload["coinapi_exchange_id"] == exchange_id
        assert payload["coinapi_market_type"] == ("PERP" if exchange_id == "BINANCEFTS" else "SPOT")
        assert payload["coinapi_symbol_id"] == provider_symbol_id
        assert payload["quarantine_only"] is True
        assert payload["available_at"] is None
        assert payload["trainer_consumable"] is False
        assert payload["prediction_eligible"] is False
        assert payload["live_gate"] == "blocked_human_only"

    binance_keys = rest._expected_quarantine_keys(binance)
    okx_keys = rest._expected_quarantine_keys(okx)
    assert binance_keys is not None and okx_keys is not None
    assert binance_keys[:3] != okx_keys[:3]
    assert all(":v4:" in key for key in (*binance_keys[:3], *okx_keys[:3]))
    assert all(COINAPI_SYMBOL_ID in key for key in binance_keys[:3])
    assert all(okx_symbol_id in key for key in okx_keys[:3])
    assert "v2:quarantine:coinapi:rest:orderbook:raw:v3:BTCUSDT" not in {
        *binance_keys[:3],
        *okx_keys[:3],
    }

    legacy_raw = dict(binance)
    legacy_raw["schema_version"] = "v2_coinapi_rest_orderbook_quarantine_v2"
    assert rest._expected_quarantine_keys(legacy_raw) is None

    api_key = "configured-key"
    binance_cadence_key = rest._ws_cadence_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        api_key=api_key,
    )
    okx_cadence_key = rest._ws_cadence_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=okx_symbol_id,
        api_key=api_key,
    )
    assert binance_cadence_key is not None and okx_cadence_key is not None
    assert binance_cadence_key != okx_cadence_key
    assert ":cadence:v4:" in binance_cadence_key
    assert COINAPI_SYMBOL_ID in binance_cadence_key
    assert okx_symbol_id in okx_cadence_key
    assert rest._coinapi_symbol_id("BTCUSDT", exchange_id="OKX") == okx_symbol_id

    unsigned_cadence: dict[str, Any] = {
        "schema_version": rest.WS_CADENCE_SCHEMA_VERSION,
        "provider_identity_schema_version": rest.PROVIDER_IDENTITY_SCHEMA_VERSION,
        "symbol": "BTCUSDT",
        "coinapi_symbol_id": COINAPI_SYMBOL_ID,
        "coinapi_exchange_id": COINAPI_EXCHANGE_ID,
        "coinapi_market_type": "PERP",
        "sample_count": 3,
        "event_cadence_ns": 1_000_000_000,
        "provider_cadence_ns": 1_000_000_000,
        "arrival_cadence_ns": 1_000_000_000,
        "max_source_lag_ns": 100_000_000,
        "max_arrival_lag_ns": 100_000_000,
        "last_event_ns": 3_000_000_000,
        "last_provider_received_ns": 3_100_000_000,
        "last_observed_ns": 3_200_000_000,
        "generated_at": "2026-07-20T12:00:00.3Z",
    }
    signature = rest._ws_cadence_signature(api_key, unsigned_cadence)
    assert signature is not None
    cadence = {**unsigned_cadence, "signature": signature}
    assert (
        rest._validated_ws_cadence_basis(
            cadence,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key=api_key,
        )
        is not None
    )
    legacy_unsigned = {
        **unsigned_cadence,
        "schema_version": "v2_coinapi_wsds_authenticated_cadence_v1",
    }
    legacy_signature = rest._ws_cadence_signature(api_key, legacy_unsigned)
    assert legacy_signature is not None
    assert (
        rest._validated_ws_cadence_basis(
            {**legacy_unsigned, "signature": legacy_signature},
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key=api_key,
        )
        is None
    )


def test_rest_symbol_and_payload_key_injection_fail_closed() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        rest._coinapi_symbol_id("BTC:EVILUSDT")
    assert (
        rest._normalize_orderbook(
            "BTC:EVILUSDT",
            "BINANCEFTS_PERP_BTC_USDT",
            _orderbook_body(),
            observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
        )
        is None
    )
    payload = _raw_orderbook_payload(1)
    digest = rest._provider_content_digest(payload)
    assert digest is not None
    with pytest.raises(ValueError, match="exactly bind"):
        rest._atomic_fenced_quarantine_write(
            StatefulRedis(),
            fence_key=rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
                coinapi_symbol_id="BINANCEFTS_PERP_ETH_USDT",
                symbol="ETHUSDT",
            ),
            data_key=rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
                coinapi_symbol_id="BINANCEFTS_PERP_ETH_USDT",
                symbol="ETHUSDT",
            ),
            conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id="BINANCEFTS_PERP_ETH_USDT",
                symbol="ETHUSDT",
                event_ns=1,
                digest=digest,
            ),
            event_identity_ns="1",
            payload=payload,
            ex=60,
        )

    authority_injected = dict(payload)
    authority_injected["trainer_consumable"] = True
    injected_digest = rest._provider_content_digest(authority_injected)
    assert injected_digest is not None
    result = rest._atomic_fenced_quarantine_write(
        StatefulRedis(),
        fence_key=rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        data_key=rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
            event_ns=1,
            digest=injected_digest,
        ),
        event_identity_ns="1",
        payload=authority_injected,
        ex=60,
    )
    assert result == (rest._FENCE_ERROR, -2)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("market_key", "v2:features:microfeat:BTCUSDT:1m"),
        ("microfeat_payloads", {"v2:features:microfeat:BTCUSDT:1m": {}}),
        ("writes_exchange_orders", True),
        ("places_exchange_orders", True),
        ("trader_execution_enabled", True),
        ("execution_live_symbols", ["BTCUSDT"]),
        ("approves_live", True),
        ("authority_grant", "trainer"),
        ("order_id", "provider-order"),
    ),
)
def test_rest_atomic_commit_rejects_unknown_authority_and_trainer_alias_fields(
    field: str,
    value: object,
) -> None:
    payload = {**_raw_orderbook_payload(1), field: value}
    digest = rest._provider_content_digest(payload)
    assert digest is not None

    result = rest._atomic_fenced_quarantine_write(
        StatefulRedis(),
        fence_key=rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        data_key=rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
            event_ns=1,
            digest=digest,
        ),
        event_identity_ns="1",
        payload=payload,
        ex=60,
    )

    assert result == (rest._FENCE_ERROR, -2)


def test_rest_atomic_commit_rejects_nested_authority_alias() -> None:
    payload = _raw_orderbook_payload(1)
    bids = payload["bids_top5"]
    assert isinstance(bids, list) and isinstance(bids[0], dict)
    bids[0]["market_key"] = "v2:features:microfeat:BTCUSDT:1m"
    digest = rest._provider_content_digest(payload)
    assert digest is not None

    result = rest._atomic_fenced_quarantine_write(
        StatefulRedis(),
        fence_key=rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        data_key=rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
        ),
        conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
            event_ns=1,
            digest=digest,
        ),
        event_identity_ns="1",
        payload=payload,
        ex=60,
    )

    assert result == (rest._FENCE_ERROR, -2)

    ohlcv_payload = rest._normalize_ohlcv(
        "BTCUSDT",
        COINAPI_SYMBOL_ID,
        "5m",
        "5MIN",
        _ohlcv_body(),
        observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
    )
    assert ohlcv_payload is not None
    ohlcv_payload["open"] = {
        "market_key": "v2:features:microfeat:BTCUSDT:5m",
        "microfeat_payloads": {"forbidden": {}},
    }
    ohlcv_digest = rest._provider_content_digest(ohlcv_payload)
    event_ns = ohlcv_payload["event_ts_ns"]
    assert ohlcv_digest is not None and type(event_ns) is int
    assert rest._atomic_fenced_quarantine_write(
        StatefulRedis(),
        fence_key=rest.REST_OHLCV_FENCE_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
            timeframe="5m",
        ),
        data_key=rest.REST_OHLCV_DATA_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
            timeframe="5m",
        ),
        conflict_key=rest.REST_OHLCV_CONFLICT_KEY_TEMPLATE.format(
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            symbol="BTCUSDT",
            timeframe="5m",
            event_ns=event_ns,
            digest=ohlcv_digest,
        ),
        event_identity_ns=str(event_ns),
        payload=ohlcv_payload,
        ex=60,
    ) == (rest._FENCE_ERROR, -2)


def test_rest_atomic_commit_revalidates_post_normalization_payload_before_eval() -> None:
    orderbook = rest._normalize_orderbook(
        "BTCUSDT",
        COINAPI_SYMBOL_ID,
        _orderbook_body(),
        observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
    )
    assert orderbook is not None

    def assert_orderbook_rejected(payload: dict[str, Any]) -> None:
        event_ns = payload.get("source_event_ts_ns")
        assert type(event_ns) is int
        digest = rest._provider_content_digest(payload) or ("0" * 64)
        client = NeverEvalRedis()
        result = rest._atomic_fenced_quarantine_write(
            client,
            fence_key=rest.REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
            ),
            data_key=rest.REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
            ),
            conflict_key=rest.REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                event_ns=event_ns,
                digest=digest,
            ),
            event_identity_ns=str(event_ns),
            payload=payload,
            ex=60,
        )
        assert result == (rest._FENCE_ERROR, -2)
        assert client.eval_calls == 0

    orderbook_mutations: tuple[tuple[str, object], ...] = (
        ("best_bid_px", "100.0"),
        ("best_bid_px", 10**400),
        ("best_bid_sz", -1.0),
        ("spread_bps", math.inf),
        ("source_event_ts_ms", int(orderbook["source_event_ts_ms"]) + 1),
        ("producer_version", "tampered-producer"),
        ("best_ask_px", 99.0),
        ("mid_px", 999.0),
    )
    for field, value in orderbook_mutations:
        assert_orderbook_rejected({**orderbook, field: value})

    inverted_orderbook_clock = dict(orderbook)
    inverted_orderbook_clock["generated_at"] = orderbook["ingested_at"]
    inverted_orderbook_clock["generated_utc"] = orderbook["ingested_at"]
    assert_orderbook_rejected(inverted_orderbook_clock)

    inconsistent_levels = dict(orderbook)
    bids = orderbook["bids_top5"]
    assert isinstance(bids, list) and isinstance(bids[0], dict)
    inconsistent_levels["bids_top5"] = [{**bids[0], "size": 2.0}, *bids[1:]]
    assert_orderbook_rejected(inconsistent_levels)

    ohlcv = rest._normalize_ohlcv(
        "BTCUSDT",
        COINAPI_SYMBOL_ID,
        "5m",
        "5MIN",
        _ohlcv_body(),
        observed_at=datetime(2026, 7, 20, 12, 5, 0, 1, tzinfo=UTC),
    )
    assert ohlcv is not None

    def assert_ohlcv_rejected(payload: dict[str, Any]) -> None:
        event_ns = payload.get("event_ts_ns")
        assert type(event_ns) is int
        digest = rest._provider_content_digest(payload) or ("0" * 64)
        client = NeverEvalRedis()
        result = rest._atomic_fenced_quarantine_write(
            client,
            fence_key=rest.REST_OHLCV_FENCE_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                timeframe="5m",
            ),
            data_key=rest.REST_OHLCV_DATA_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                timeframe="5m",
            ),
            conflict_key=rest.REST_OHLCV_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                symbol="BTCUSDT",
                timeframe="5m",
                event_ns=event_ns,
                digest=digest,
            ),
            event_identity_ns=str(event_ns),
            payload=payload,
            ex=60,
        )
        assert result == (rest._FENCE_ERROR, -2)
        assert client.eval_calls == 0

    ohlcv_mutations: tuple[tuple[str, object], ...] = (
        ("open", "100.0"),
        ("open", 10**400),
        ("volume", -1.0),
        ("trades_count", 0.0),
        ("high", 99.0),
        ("event_ts_ms", int(ohlcv["event_ts_ms"]) + 1),
        ("feature_cutoff", ohlcv["time_period_start"]),
        ("observed_at", ohlcv["time_period_end"]),
        ("native_worker_id", "tampered-worker"),
    )
    for field, value in ohlcv_mutations:
        assert_ohlcv_rejected({**ohlcv, field: value})


def test_rest_persistent_state_reads_are_atomic_and_length_gated() -> None:
    class OversizedStateRedis:
        def __init__(self) -> None:
            self.identity_fields: list[str] = []
            self.direct_fetch_calls = 0

        def hmget(self, *args: object) -> object:
            del args
            self.direct_fetch_calls += 1
            raise AssertionError("persistent state must not use HMGET")

        def hget(self, *args: object) -> object:
            del args
            self.direct_fetch_calls += 1
            raise AssertionError("persistent state must not use direct HGET")

        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 1
            assert "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script
            assert "HMGET" not in script
            assert script.index("redis.call('TYPE'") < script.index("redis.call('PTTL'")
            assert script.index("redis.call('PTTL'") < script.index("redis.call('HSTRLEN'")
            assert script.index("redis.call('HSTRLEN'") < script.index("redis.call('HGET'")
            _key, identity_field, _payload_field, _identity_limit, payload_limit = args
            self.identity_fields.append(str(identity_field))
            return [rest._STATE_READ_OVERSIZED, 1, int(str(payload_limit)) + 1]

    client = OversizedStateRedis()
    auth_key = rest._auth_latch_key("configured-key")
    cadence_key = rest._ws_cadence_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        api_key="configured-key",
    )
    assert auth_key is not None and cadence_key is not None

    assert rest._bounded_persistent_hash_read(
        client,
        key=auth_key,
        identity_field="revision_ns",
    ) == (rest._STATE_READ_OVERSIZED, None, None)
    assert rest._load_auth_state(client, api_key="configured-key") is None
    assert (
        rest._load_ws_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        is None
    )
    assert client.identity_fields == ["revision_ns", "revision_ns", "last_event_ns"]
    assert client.direct_fetch_calls == 0

    class ReplyRedis:
        def __init__(self, reply: object) -> None:
            self.reply = reply

        def eval(self, script: str, numkeys: int, *args: object) -> object:
            del script, numkeys, args
            return self.reply

    assert rest._bounded_persistent_hash_read(
        ReplyRedis([rest._STATE_READ_INVALID, "", ""]),
        key=auth_key,
        identity_field="revision_ns",
    ) == (rest._STATE_READ_INVALID, None, None)
    assert rest._bounded_persistent_hash_read(
        ReplyRedis([rest._STATE_READ_OK, b"1", b"x" * (rest.MAX_STATE_JSON_BYTES + 1)]),
        key=auth_key,
        identity_field="revision_ns",
    ) == (rest._STATE_READ_ERROR, None, None)


def test_rest_retry_after_and_credential_rotation_are_bounded_and_nonsecret() -> None:
    first = rest._build_auth_state(
        api_key="first-secret",
        http_status=403,
        error_class="ENTITLEMENT_REJECTED",
        prior_state=None,
        quota_metadata={"retry_after_seconds": 17},
        now_ns=1_000_000_000,
    )
    assert first is not None
    assert first["next_probe_at_ns"] == 31_000_000_000
    assert first["retry_after_honored"] is True
    serialized = json.dumps(first, sort_keys=True)
    assert "first-secret" not in serialized
    short_window = {
        **first,
        "next_probe_at_ns": first["revision_ns"] + 29_000_000_000,
    }
    short_unsigned = {key: value for key, value in short_window.items() if key != "signature"}
    short_window["signature"] = rest._auth_state_signature("first-secret", short_unsigned)
    assert rest._validated_auth_state(short_window, api_key="first-secret") is None
    assert rest._validated_auth_state(first, api_key="second-secret") is None
    assert rest._auth_latch_key("first-secret") != rest._auth_latch_key("second-secret")
    first_cadence_key = rest._ws_cadence_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        api_key="first-secret",
    )
    second_cadence_key = rest._ws_cadence_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        api_key="second-secret",
    )
    assert first_cadence_key is not None and second_cadence_key is not None
    assert first_cadence_key != second_cadence_key
    assert "first-secret" not in first_cadence_key
    assert "second-secret" not in second_cadence_key
    assert (
        rest._provider_retry_delay_seconds(
            {"retry_after_seconds": rest.AUTH_BACKOFF_MAX_SECONDS * 1000}
        )
        == rest.AUTH_BACKOFF_MAX_SECONDS
    )


def test_successful_orderbook_does_not_clear_ohlcv_entitlement_backoff(monkeypatch) -> None:
    observed = datetime.now(UTC)
    boundary = observed.replace(second=0, microsecond=0)
    period_start = boundary - timedelta(minutes=5)
    calls = 0

    def mixed_endpoint_result(
        base_url: str,
        path: str,
        **kwargs: object,
    ) -> tuple[int, object, dict[str, int]]:
        nonlocal calls
        del base_url, kwargs
        calls += 1
        if path == "/v1/orderbooks3/current":
            now = datetime.now(UTC)
            event = now - timedelta(milliseconds=2)
            received = now - timedelta(milliseconds=1)
            return (
                200,
                {
                    "symbol_id": "BINANCEFTS_PERP_BTC_USDT",
                    "time_exchange": event.isoformat().replace("+00:00", "Z"),
                    "time_coinapi": received.isoformat().replace("+00:00", "Z"),
                    "bids": [{"price": 100.0, "size": 2.0}],
                    "asks": [{"price": 101.0, "size": 3.0}],
                },
                {},
            )
        assert path.endswith("/latest")
        return 403, {"detail": "plan entitlement required"}, {}

    # The exact candle values aren't consumed because the OHLCV request is
    # rejected.  Keep these variables explicit to document the intended
    # completed-window shape for this mixed-endpoint regression.
    assert period_start < boundary <= observed
    monkeypatch.delenv("COINAPI_REST_URL", raising=False)
    monkeypatch.setattr(rest, "_read_secret_value", lambda name: "configured-key")
    monkeypatch.setattr(rest, "_http_get_json", mixed_endpoint_result)
    monkeypatch.setattr(rest, "_rate_limit_sleep", lambda *args: None)
    redis_client = StatefulRedis()
    monkeypatch.setattr(rest, "_connect_redis", lambda: redis_client)

    first = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=True,
        ohlcv_timeframes=("5m",),
        ohlcv_symbol_limit=1,
        write_v2_redis=True,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )
    second = rest.build_payload(
        ("BTCUSDT",),
        fetch_symbol_limit=None,
        fetch_ohlcv=True,
        ohlcv_timeframes=("5m",),
        ohlcv_symbol_limit=1,
        write_v2_redis=True,
        ttl_seconds=60,
        timeout_seconds=1.0,
        max_rps=10.0,
    )

    assert calls == 2
    assert first["fetch"]["authenticated_http_successes"] == 1
    assert first["classification"] == "V2_COINAPI_REST_OPTIONAL_DEGRADED_PARTIAL"
    assert rest._load_auth_state(redis_client, api_key="configured-key") is not None
    assert second["classification"] == "V2_COINAPI_REST_OPTIONAL_AUTH_UNAVAILABLE"
    assert second["fetch"]["requests_attempted"] == 0


def test_rest_atomic_lua_reads_are_length_gated_and_existing_state_is_consistent() -> None:
    for marker, script in (
        ("COINAPI_ATOMIC_FENCE_BOUNDED_V2", rest._ATOMIC_FENCE_LUA),
        ("COINAPI_ATOMIC_AUTH_STATE_BOUNDED_V2", rest._ATOMIC_AUTH_STATE_LUA),
    ):
        assert marker in script
        assert script.count("redis.call('HGET'") == 1
        assert script.index("redis.call('HSTRLEN'") < script.index("redis.call('HGET'")
        assert "identity_limit = tonumber" in script
        assert "payload_limit = tonumber" in script
        assert "identity_limit > 64" in script
    assert rest._ATOMIC_FENCE_LUA.count("redis.call('GET'") == 1
    assert rest._ATOMIC_FENCE_LUA.index("redis.call('STRLEN'") < rest._ATOMIC_FENCE_LUA.index(
        "redis.call('GET'"
    )
    assert "payload_limit > 2097152" in rest._ATOMIC_FENCE_LUA
    assert "payload_limit > 32768" in rest._ATOMIC_AUTH_STATE_LUA
    assert "fence_type == 'hash'" in rest._ATOMIC_FENCE_LUA
    assert (
        "current_event and baseline_payload and baseline_payload ~= current_payload"
        in rest._ATOMIC_FENCE_LUA
    )
    assert "redis.sha1hex(current_payload) ~= current_payload_sha1" in rest._ATOMIC_FENCE_LUA
    assert "existing_conflict == incoming_payload" in rest._ATOMIC_FENCE_LUA


def test_rest_atomic_writes_reject_oversized_input_and_preflight_race(monkeypatch) -> None:
    payload = _raw_orderbook_payload(1_000_000)
    expected = rest._expected_quarantine_keys(payload)
    assert expected is not None
    fence_key, data_key, conflict_key, event_identity_ns = expected
    never_eval = NeverEvalRedis()
    monkeypatch.setattr(rest, "MAX_REDIS_QUARANTINE_JSON_BYTES", 1)
    assert rest._atomic_fenced_quarantine_write(
        never_eval,
        fence_key=fence_key,
        data_key=data_key,
        conflict_key=conflict_key,
        event_identity_ns=event_identity_ns,
        payload=payload,
        ex=60,
    ) == (rest._FENCE_ERROR, -2)
    assert never_eval.eval_calls == 0
    monkeypatch.setattr(
        rest,
        "MAX_REDIS_QUARANTINE_JSON_BYTES",
        rest.MAX_REST_RESPONSE_BYTES,
    )

    class OversizedFenceStateRedis:
        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 3
            assert "COINAPI_ATOMIC_FENCE_BOUNDED_V2" in script
            assert args[-2:] == (
                rest.MAX_STATE_IDENTITY_BYTES,
                rest.MAX_REDIS_QUARANTINE_JSON_BYTES,
            )
            oversized_existing_payload = "x" * (int(args[-1]) + 1)
            assert len(oversized_existing_payload) > int(args[-1])
            return [rest._FENCE_ERROR, 0, -2]

    assert rest._atomic_fenced_quarantine_write(
        OversizedFenceStateRedis(),
        fence_key=fence_key,
        data_key=data_key,
        conflict_key=conflict_key,
        event_identity_ns=event_identity_ns,
        payload=payload,
        ex=60,
    ) == (rest._FENCE_ERROR, -2)

    prior = rest._build_auth_state(
        api_key="configured-key",
        http_status=403,
        error_class="ENTITLEMENT_REJECTED",
        prior_state=None,
        quota_metadata=None,
        now_ns=1,
    )
    replacement = rest._build_auth_state(
        api_key="configured-key",
        http_status=403,
        error_class="ENTITLEMENT_REJECTED",
        prior_state=prior,
        quota_metadata=None,
        now_ns=2,
    )
    assert prior is not None and replacement is not None
    prior_serialized = rest._canonical_json(prior)
    assert prior_serialized is not None

    class AuthPreflightRaceRedis:
        def __init__(self) -> None:
            self.current_payload = prior_serialized
            self.atomic_calls = 0

        def exists(self, key: str) -> int:
            del key
            return 1

        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 1
            if "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script:
                before_race = self.current_payload
                self.current_payload = "x" * (rest.MAX_STATE_JSON_BYTES + 1)
                return [rest._STATE_READ_OK, str(prior["revision_ns"]), before_race]
            assert "COINAPI_ATOMIC_AUTH_STATE_BOUNDED_V2" in script
            self.atomic_calls += 1
            assert args[-2:] == (
                rest.MAX_STATE_IDENTITY_BYTES,
                rest.MAX_STATE_JSON_BYTES,
            )
            assert len(self.current_payload) > int(args[-1])
            return [rest._AUTH_STATE_ERROR, 0]

    race_client = AuthPreflightRaceRedis()
    assert (
        rest._persist_auth_state(
            race_client,
            api_key="configured-key",
            state=replacement,
        )
        == rest._AUTH_STATE_ERROR
    )
    assert race_client.atomic_calls == 1
