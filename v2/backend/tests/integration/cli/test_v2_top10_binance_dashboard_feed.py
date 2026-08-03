"""Tests for the V2 Top-10 Binance market dashboard feed.

Paper-only. No real network IO. No torch import. No legacy filesystem
mutation. No exchange mutation.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _svc():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.binance_top10_dashboards"
    )


def _cli():
    return importlib.import_module(
        "v2.backend.app.cli.v2_top10_binance_dashboard_feed"
    )


SPOT_FIXTURE = [
    {
        "symbol": "BTCUSDT",
        "quoteVolume": "5000000000.0",
        "count": 9000,
        "priceChangePercent": "-3.20",
        "lastPrice": "50000.0",
    },
    {
        "symbol": "ETHUSDT",
        "quoteVolume": "1500000000.0",
        "count": 7000,
        "priceChangePercent": "2.50",
        "lastPrice": "1800.0",
    },
    {
        "symbol": "SOLUSDT",
        "quoteVolume": "300000000.0",
        "count": 4000,
        "priceChangePercent": "15.10",
        "lastPrice": "120.0",
    },
    {
        "symbol": "PEPEBNB",  # non-USDT, must be filtered out
        "quoteVolume": "10000000000.0",
        "count": 9999999,
        "priceChangePercent": "99.0",
        "lastPrice": "0.0",
    },
    {
        "symbol": "DOGEUSDT",
        "quoteVolume": "250000000.0",
        "count": 6000,
        "priceChangePercent": "-7.40",
        "lastPrice": "0.13",
    },
]

FUTURES_FIXTURE = [
    {
        "symbol": "BTCUSDT",
        "quoteVolume": "12000000000.0",
        "count": 18000,
        "priceChangePercent": "-2.10",
        "lastPrice": "50000.0",
    },
    {
        "symbol": "ETHUSDT",
        "quoteVolume": "4000000000.0",
        "count": 11000,
        "priceChangePercent": "1.20",
        "lastPrice": "1800.0",
    },
    {
        "symbol": "SOLUSDT",
        "quoteVolume": "900000000.0",
        "count": 8000,
        "priceChangePercent": "10.50",
        "lastPrice": "120.0",
    },
    {
        "symbol": "ADAUSDT",
        "quoteVolume": "400000000.0",
        "count": 5500,
        "priceChangePercent": "-12.80",
        "lastPrice": "0.35",
    },
]


def test_safe_redis_set_refuses_non_dashboard_keys() -> None:
    mod = _svc()
    r = FakeRedis()
    assert mod._safe_redis_set(r, mod.KEY_SPOT_VOLUME, "x", ex=600) is True
    assert mod._safe_redis_set(r, mod.KEY_HEARTBEAT, "y", ex=120) is True
    assert mod._safe_redis_set(r, "v2:market:prices:BTCUSDT", "z", ex=600) is False
    assert mod._safe_redis_set(r, "prediction:BTCUSDT", "z", ex=600) is False
    assert mod._safe_redis_set(r, "v2:altdata:provider_status", "z", ex=600) is False
    for k in r.store.keys():
        assert k in mod.ALLOWED_KEYS


def test_filter_symbols_keeps_only_quote_filter() -> None:
    mod = _svc()
    filtered = mod.filter_symbols(SPOT_FIXTURE, "USDT")
    symbols = {row["symbol"] for row in filtered}
    assert "PEPEBNB" not in symbols
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"} <= symbols


def test_filter_symbols_passthrough_when_filter_is_none() -> None:
    mod = _svc()
    filtered = mod.filter_symbols(SPOT_FIXTURE, None)
    assert len(filtered) == len(SPOT_FIXTURE)


def test_rank_top_n_by_quote_volume_descending() -> None:
    mod = _svc()
    rows = mod.rank_top_n(
        mod.filter_symbols(SPOT_FIXTURE, "USDT"),
        metric_field="quoteVolume",
        top_n=3,
    )
    assert [r.symbol for r in rows] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert [r.rank for r in rows] == [1, 2, 3]


def test_rank_top_n_volatility_uses_abs_value() -> None:
    mod = _svc()
    rows = mod.rank_top_n(
        mod.filter_symbols(SPOT_FIXTURE, "USDT"),
        metric_field="priceChangePercent",
        metric_transform=mod._abs_price_change,
        top_n=3,
    )
    # SOLUSDT=15.10, DOGEUSDT=-7.40, BTCUSDT=-3.20
    assert [r.symbol for r in rows] == ["SOLUSDT", "DOGEUSDT", "BTCUSDT"]


def test_rank_top_n_count_metric() -> None:
    mod = _svc()
    rows = mod.rank_top_n(
        mod.filter_symbols(FUTURES_FIXTURE, "USDT"),
        metric_field="count",
        top_n=2,
    )
    assert [r.symbol for r in rows] == ["BTCUSDT", "ETHUSDT"]


def test_fetch_ticker_maps_status_codes_explicitly() -> None:
    mod = _svc()
    for status_code, expected in (
        (200, "API_OK"),
        (429, "API_RATE_LIMITED_429"),
        (403, "API_FORBIDDEN_403"),
        (500, "API_NETWORK_ERROR"),
    ):
        def http_get(url, headers, timeout, code=status_code):
            return code, SPOT_FIXTURE if code == 200 else None

        status, rows = mod.fetch_ticker(
            mod.SPOT_ROLLING_TICKER_URL, http_get=http_get
        )
        assert status == expected
        if status == "API_OK":
            assert rows == SPOT_FIXTURE
        else:
            assert rows == []


def test_fetch_ticker_handles_exceptions() -> None:
    mod = _svc()

    def http_get_timeout(url, headers, timeout):
        raise TimeoutError("timed out")

    status, rows = mod.fetch_ticker(
        mod.SPOT_ROLLING_TICKER_URL, http_get=http_get_timeout
    )
    assert status == "API_TIMEOUT"
    assert rows == []

    def http_get_conn(url, headers, timeout):
        raise ConnectionError("unreachable")

    status, rows = mod.fetch_ticker(
        mod.SPOT_ROLLING_TICKER_URL, http_get=http_get_conn
    )
    assert status == "API_NETWORK_ERROR"
    assert rows == []


def test_build_dashboards_creates_six_payloads() -> None:
    mod = _svc()
    dashboards = mod.build_dashboards(
        spot_rows=SPOT_FIXTURE,
        futures_rows=FUTURES_FIXTURE,
        spot_source_status="API_OK",
        futures_source_status="API_OK",
    )
    assert set(dashboards.keys()) == {
        "spot_volume_12h",
        "spot_trades_12h",
        "spot_volatility_12h",
        "futures_volume_12h",
        "futures_trades_12h",
        "futures_volatility_12h",
    }
    for payload in dashboards.values():
        assert payload["writes_legacy_redis"] is False
        assert payload["writes_exchange_orders"] is False
        assert payload["credential_in_payload"] == "NEVER"
        assert payload["gate"] == "blocked_human_only"
        assert payload["symbols_real"] == []
        assert payload["redis_key"].startswith("v2:dashboards:binance_top10:")


def test_futures_dashboards_advertise_window_size_24h_actual() -> None:
    mod = _svc()
    dashboards = mod.build_dashboards(
        spot_rows=SPOT_FIXTURE,
        futures_rows=FUTURES_FIXTURE,
        spot_source_status="API_OK",
        futures_source_status="API_OK",
    )
    for dash_id in (
        "futures_volume_12h",
        "futures_trades_12h",
        "futures_volatility_12h",
    ):
        payload = dashboards[dash_id]
        assert payload["window_size_requested"] == "12h"
        assert payload["window_size_actual"] == "24h"
        assert payload["source_endpoint"] == mod.FUTURES_24H_TICKER_URL


def test_spot_dashboards_advertise_window_size_12h_actual() -> None:
    mod = _svc()
    dashboards = mod.build_dashboards(
        spot_rows=SPOT_FIXTURE,
        futures_rows=FUTURES_FIXTURE,
        spot_source_status="API_OK",
        futures_source_status="API_OK",
    )
    for dash_id in (
        "spot_volume_12h",
        "spot_trades_12h",
        "spot_volatility_12h",
    ):
        payload = dashboards[dash_id]
        assert payload["window_size_requested"] == "12h"
        assert payload["window_size_actual"] == "12h"
        assert payload["source_endpoint"] == mod.SPOT_ROLLING_TICKER_URL


def test_publish_dashboards_writes_to_allowed_keys_only() -> None:
    mod = _svc()
    r = FakeRedis()
    dashboards = mod.build_dashboards(
        spot_rows=SPOT_FIXTURE,
        futures_rows=FUTURES_FIXTURE,
        spot_source_status="API_OK",
        futures_source_status="API_OK",
    )
    result = mod.publish_dashboards(r, dashboards)
    assert all(result.values()) is True
    for k in r.store.keys():
        assert k in mod.ALLOWED_KEYS
        assert k.startswith(mod.DASHBOARD_KEY_PREFIX)


def test_heartbeat_payload_includes_safety_fields() -> None:
    mod = _svc()
    dashboards = mod.build_dashboards(
        spot_rows=SPOT_FIXTURE,
        futures_rows=FUTURES_FIXTURE,
        spot_source_status="API_OK",
        futures_source_status="API_OK",
    )
    hb = mod.build_heartbeat_payload(
        spot_source_status="API_OK",
        futures_source_status="API_OK",
        dashboards=dashboards,
    )
    for field in (
        "schema_version",
        "generated_utc",
        "heartbeat_at",
        "spot_source_status",
        "futures_source_status",
        "dashboards_published",
        "dashboards_count",
        "writes_legacy_redis",
        "writes_exchange_orders",
        "no_synthetic_market_data",
        "credential_in_payload",
        "auth_required_for_source_endpoints",
        "gate",
        "symbols_real",
    ):
        assert field in hb, f"missing heartbeat field: {field}"
    assert hb["dashboards_count"] == 6
    assert hb["writes_legacy_redis"] is False
    assert hb["writes_exchange_orders"] is False
    assert hb["credential_in_payload"] == "NEVER"
    assert hb["auth_required_for_source_endpoints"] is False
    assert hb["gate"] == "blocked_human_only"


def test_cli_run_once_end_to_end_with_fake_http_and_redis(tmp_path: Path) -> None:
    cli = _cli()
    mod = _svc()
    r = FakeRedis()

    def http_get(url, headers, timeout):
        if mod.SPOT_ROLLING_TICKER_URL in url:
            return 200, SPOT_FIXTURE
        if mod.FUTURES_24H_TICKER_URL in url:
            return 200, FUTURES_FIXTURE
        return 404, None

    out = cli.run_once(
        redis_client=r,
        http_get=http_get,
        quote_filter="USDT",
        top_n=10,
    )
    assert out["spot_source_status"] == "API_OK"
    assert out["futures_source_status"] == "API_OK"
    assert set(out["dashboards"].keys()) == {
        "spot_volume_12h",
        "spot_trades_12h",
        "spot_volatility_12h",
        "futures_volume_12h",
        "futures_trades_12h",
        "futures_volatility_12h",
    }
    for k in r.store.keys():
        assert k in mod.ALLOWED_KEYS
    assert mod.KEY_HEARTBEAT in r.store


def test_cli_main_handles_provider_unreachable_without_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    cli = _cli()
    monkeypatch.setattr(cli, "_connect_redis", lambda: None)
    import v2.backend.app.services.alternative_data.binance_top10_dashboards as svc

    def fake_http_get(url, headers, timeout):
        raise ConnectionError("provider unreachable")

    monkeypatch.setattr(svc, "_default_http_get", fake_http_get)
    worklog = tmp_path / "wl.json"
    pub_a = tmp_path / "pa.json"
    pub_b = tmp_path / "pb.json"
    rc = cli.main(
        [
            "--out-worklog", str(worklog),
            "--out-public", str(pub_a),
            "--out-public-secondary", str(pub_b),
        ]
    )
    assert rc == 0
    payload = json.loads(worklog.read_text())
    assert payload["go_no_go"] == "V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_READY"
    assert payload["spot_source_status"] == "API_NETWORK_ERROR"
    assert payload["futures_source_status"] == "API_NETWORK_ERROR"
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False


def test_no_exchange_mutation_surface_in_module_source() -> None:
    import inspect

    mod = _svc()
    cli = _cli()
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for source_mod in (mod, cli):
        src = inspect.getsource(source_mod)
        for token in forbidden:
            assert token not in src, f"forbidden token in module: {token}"


def test_no_torch_imported_in_binance_dashboard_modules() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.alternative_data.binance_top10_dashboards"
    )
    importlib.import_module("v2.backend.app.cli.v2_top10_binance_dashboard_feed")
    assert "torch" not in sys.modules


def test_no_pickle_deserialization_in_modules() -> None:
    import inspect

    for name in (
        "v2.backend.app.services.alternative_data.binance_top10_dashboards",
        "v2.backend.app.cli.v2_top10_binance_dashboard_feed",
    ):
        mod = importlib.import_module(name)
        src = inspect.getsource(mod)
        assert "pickle.load" not in src
        assert "pickle.loads" not in src
        assert "cPickle" not in src


def test_top_10_truncation_when_more_than_10_rows() -> None:
    mod = _svc()
    rows = [
        {
            "symbol": f"SYM{i}USDT",
            "quoteVolume": str(1_000_000.0 * (50 - i)),
            "count": 50 - i,
            "priceChangePercent": "1.0",
            "lastPrice": "1.0",
        }
        for i in range(20)
    ]
    ranked = mod.rank_top_n(
        mod.filter_symbols(rows, "USDT"),
        metric_field="quoteVolume",
        top_n=10,
    )
    assert len(ranked) == 10
    assert ranked[0].symbol == "SYM0USDT"
    assert ranked[-1].symbol == "SYM9USDT"


def test_partial_provider_failure_publishes_what_it_can(tmp_path: Path) -> None:
    """If spot succeeds but futures fails, the spot dashboards must
    still publish and the futures dashboards must reflect the failure
    in source_status without containing fabricated rows."""
    cli = _cli()
    mod = _svc()
    r = FakeRedis()

    def http_get(url, headers, timeout):
        if mod.SPOT_ROLLING_TICKER_URL in url:
            return 200, SPOT_FIXTURE
        if mod.FUTURES_24H_TICKER_URL in url:
            return 429, None
        return 404, None

    out = cli.run_once(
        redis_client=r,
        http_get=http_get,
        quote_filter="USDT",
        top_n=10,
    )
    assert out["spot_source_status"] == "API_OK"
    assert out["futures_source_status"] == "API_RATE_LIMITED_429"
    spot = out["dashboards"]["spot_volume_12h"]
    futures = out["dashboards"]["futures_volume_12h"]
    assert spot["rank_count"] > 0
    assert futures["rank_count"] == 0
    assert futures["source_status"] == "API_RATE_LIMITED_429"
    assert mod.KEY_HEARTBEAT in r.store
