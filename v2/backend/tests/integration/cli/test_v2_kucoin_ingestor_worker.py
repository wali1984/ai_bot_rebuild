"""V2 KuCoin ingestor tests (paper-only public-data config)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.expiries[key] = ex


def _venv_python() -> str:
    cand = REPO / ".venv/bin/python"
    return str(cand) if cand.exists() else sys.executable


def test_symbol_mapping_v2_to_kucoin_spot() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import (
        v2_to_kucoin_spot_symbol,
    )

    assert v2_to_kucoin_spot_symbol("BTCUSDT") == "BTC-USDT"
    assert v2_to_kucoin_spot_symbol("ethusdt") == "ETH-USDT"
    assert v2_to_kucoin_spot_symbol("SOL-USDT") == "SOL-USDT"
    assert v2_to_kucoin_spot_symbol("XRPBTC") == "XRP-BTC"


def test_symbol_mapping_v2_to_kucoin_futures_uses_xbt_for_btc() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import (
        v2_to_kucoin_futures_symbol,
    )

    assert v2_to_kucoin_futures_symbol("BTCUSDT") == "XBTUSDTM"
    assert v2_to_kucoin_futures_symbol("ETHUSDT") == "ETHUSDTM"


def test_build_ingestor_config_classifies_native_v2() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import build_ingestor_config

    cfg = build_ingestor_config(symbols_v2=["BTCUSDT", "ETHUSDT"])
    assert cfg.classification == "NATIVE_V2"
    assert cfg.symbols_v2 == ("BTCUSDT", "ETHUSDT")
    assert len(cfg.spot_endpoints) >= 3
    assert len(cfg.futures_endpoints) >= 3
    assert any(e.path.startswith("/api/v1/market/allTickers") for e in cfg.spot_endpoints)
    assert any(t.topic.startswith("/market/ticker:BTC-USDT") for t in cfg.public_wss_topics)
    for e in cfg.spot_endpoints + cfg.futures_endpoints:
        assert e.requires_auth is False
        assert e.method == "GET"


def test_build_ingestor_config_uses_official_futures_wss_topics() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import build_ingestor_config

    cfg = build_ingestor_config(symbols_v2=["BTCUSDT"], spot=False)

    assert [request.topic for request in cfg.public_wss_topics] == [
        "/contractMarket/tickerV2:XBTUSDTM",
        "/contractMarket/level2:XBTUSDTM",
        "/contract/instrument:XBTUSDTM",
    ]
    assert all(request.private_channel is False for request in cfg.public_wss_topics)


def test_reconnect_backoff_classification_progression() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import classify_reconnect_attempt

    assert classify_reconnect_attempt(0)["backoff_seconds"] == 1.0
    assert classify_reconnect_attempt(0)["classification"] == "BACKOFF_NORMAL"
    saturated = classify_reconnect_attempt(20)
    assert saturated["classification"] == "BACKOFF_SATURATED"
    assert saturated["backoff_seconds"] == 60.0


def test_reconnect_backoff_rejects_negative_attempt() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import classify_reconnect_attempt

    with pytest.raises(ValueError):
        classify_reconnect_attempt(-1)


def test_kucoin_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.native_ingestors.kucoin import kucoin_invariants_snapshot

    s = kucoin_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["performs_network_io"] is False
    assert s["writes_legacy_redis"] is False
    assert s["places_exchange_orders"] is False
    assert s["public_market_data_only"] is True
    assert s["requires_api_key"] is False


def test_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/native_ingestors/kucoin.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
        "import requests",
        "import websockets", "from websockets",
        "import aiohttp",
    ):
        assert forbidden not in text, f"kucoin.py contains forbidden: {forbidden}"


def test_cli_writes_status_payload(tmp_path: Path) -> None:
    out = tmp_path / "v2_kucoin_ingestor_status.json"
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_kucoin_ingestor_worker",
        "--write-evidence",
        "--symbols",
        "BTCUSDT,ETHUSDT",
        "--out",
        str(out),
    ]
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    body = json.loads(out.read_text())
    assert body["worker_id"] == "v2_kucoin_ingestor"
    assert body["classification"] == "NATIVE_V2"
    assert body["live_gate"] == "blocked_human_only"
    assert body["live_symbols"] == []
    assert body["approves_live"] is False
    assert body["symbols_v2"] == ["BTCUSDT", "ETHUSDT"]
    assert len(body["public_wss_topics"]) >= 4


def test_kucoin_business_error_does_not_classify_as_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from v2.backend.app.cli import v2_kucoin_ingestor_worker as worker

    def fake_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        return 200, {"code": "400302", "msg": "restricted area"}

    monkeypatch.setattr(worker, "_http_get_json", fake_get_json)
    payload = worker.build_payload(("BTCUSDT",), fetch_public_rest=True, timeframes=("1m",))

    assert payload["classification"] == "BLOCKED_BY_NETWORK_OR_API"
    assert payload["public_rest_fetch"]["rows"] == []
    assert payload["public_rest_fetch"]["symbols_unsupported"] == ["BTCUSDT"]
    assert payload["public_rest_fetch"]["authority"]["spot"]["provider_code"] == "400302"


def test_kucoin_dual_listed_symbol_uses_homogeneous_futures_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.cli import v2_kucoin_ingestor_worker as worker

    def fake_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        if path == "/api/v2/symbols":
            return 200, {
                "code": "200000",
                "data": [{
                    "symbol": "BTC-USDT",
                    "baseCurrency": "BTC",
                    "quoteCurrency": "USDT",
                    "enableTrading": True,
                }],
            }
        if path == "/api/v1/contracts/active":
            return 200, {
                "code": "200000",
                "data": [{
                    "symbol": "XBTUSDTM",
                    "baseCurrency": "XBT",
                    "quoteCurrency": "USDT",
                    "settleCurrency": "USDT",
                    "isInverse": False,
                    "marketStage": "NORMAL",
                    "status": "Open",
                    "multiplier": "0.001",
                    "openInterest": "28864204",
                    "markPrice": "63331.06",
                    "indexPrice": "63334.66",
                    "lastTradePrice": "63331.1",
                    "volumeOf24h": "5000",
                    "fundingFeeRate": "-0.000241",
                    "predictedFundingFeeRate": "-0.000160",
                    "currentFundingRateGranularity": 28_800_000,
                    "fundingRateCap": "0.003",
                    "fundingRateFloor": "-0.003",
                    "nextFundingRateDateTime": 1780652400000,
                }],
            }
        if path == "/api/v1/kline/query":
            assert params is not None
            assert params["granularity"] == 1
            assert params["to"] - params["from"] == 180_000
            return 200, {"code": "200000", "data": [[1780623600000, 1.0, 1.2, 0.9, 1.1, 10, 11]]}
        if path == "/api/v1/level2/depth20":
            return 200, {
                "code": "200000",
                "data": {"bids": [[1.0, 2]], "asks": [[1.1, 3]], "ts": 1780623600000000000},
            }
        raise AssertionError(f"unexpected KuCoin path: {base}{path} {params}")

    monkeypatch.setattr(worker, "_http_get_json", fake_get_json)
    monkeypatch.setattr(worker, "_now_ms", lambda: 1780623720000)
    payload = worker.build_payload(("BTCUSDT",), fetch_public_rest=True, timeframes=("1m",))
    row = payload["public_rest_fetch"]["rows"][0]

    assert payload["classification"] == "NATIVE_V2_PUBLIC_REST_OK"
    assert row["spot_authorized"] is True
    assert row["futures_authorized"] is True
    assert row["authorized_product_coverage"] == ["spot", "linear_perpetual"]
    assert row["primary_market_type"] == "linear_perpetual"
    assert row["product_coverage"] == ["linear_perpetual"]
    assert row["ticker"]["source"] == "kucoin_futures_public_rest"
    assert row["ticker"]["market_type"] == "linear_perpetual"
    assert row["ticker"]["last"] == 63331.1
    assert row["klines"]["1m"]["source"] == "kucoin_futures_public_rest"
    assert row["klines"]["1m"]["is_final"] is True
    assert row["orderbook20"]["source"] == "kucoin_futures_public_rest"
    assert row["funding"]["source"] == "kucoin_futures_contract_authority_snapshot"
    assert row["funding"]["rate"] == -0.000241
    assert row["funding"]["rate_unit"] == "fraction_per_funding_interval"
    assert row["funding"]["funding_interval_hours"] == 8
    assert row["funding"]["rate_per_hour"] == pytest.approx(-0.000241 / 8)
    assert row["funding"]["rate_per_hour_unit"] == "fraction_per_hour"
    assert row["contract"]["open_interest"] == 28864204.0
    assert row["contract"]["open_interest_unit"] == "contracts"
    assert row["contract"]["contract_multiplier"] == 0.001
    assert row["contract"]["contract_multiplier_unit"] == "base_asset_per_contract"


def test_kucoin_partial_cycle_pins_preferred_major_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.cli import v2_kucoin_ingestor_worker as worker

    symbols = ("AAAUSDT", "BTCUSDT", "BBBUSDT", "ETHUSDT", "SOLUSDT")
    spot_rows = [
        {
            "symbol": f"{symbol[:-4]}-USDT",
            "baseCurrency": symbol[:-4],
            "quoteCurrency": "USDT",
            "enableTrading": True,
        }
        for symbol in symbols
    ]

    def fake_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        if path == "/api/v2/symbols":
            return 200, {"code": "200000", "data": spot_rows}
        if path == "/api/v1/contracts/active":
            return 200, {"code": "200000", "data": []}
        if path == "/api/v1/market/orderbook/level1":
            return 200, {
                "code": "200000",
                "data": {
                    "time": 1780623600000,
                    "price": "10",
                    "bestBid": "9.9",
                    "bestAsk": "10.1",
                    "size": "1",
                },
            }
        if path == "/api/v1/market/candles":
            return 200, {
                "code": "200000",
                "data": [[1780623600, "10", "10.1", "10.2", "9.9", "5", "50"]],
            }
        if path == "/api/v1/market/orderbook/level2_20":
            return 200, {
                "code": "200000",
                "data": {
                    "time": 1780623600000,
                    "bids": [["9.9", "2"]],
                    "asks": [["10.1", "3"]],
                },
            }
        raise AssertionError(f"unexpected KuCoin path: {base}{path} {params}")

    monkeypatch.setattr(worker, "_http_get_json", fake_get_json)
    monkeypatch.setattr(worker, "_now_ms", lambda: 1780623720000)
    payload = worker.build_payload(
        symbols,
        fetch_public_rest=True,
        timeframes=("1m",),
        public_rest_request_budget=11,
    )
    fetch = payload["public_rest_fetch"]

    assert [row["symbol"] for row in fetch["rows"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert fetch["preferred_every_cycle_symbols"] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert set(fetch["symbols_deferred"]) == {"AAAUSDT", "BBBUSDT"}


def test_kucoin_request_budget_rotates_and_reports_partial_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.cli import v2_kucoin_ingestor_worker as worker

    symbols = ("AAAUSDT", "BBBUSDT", "CCCUSDT")
    spot_rows = [
        {
            "symbol": f"{symbol[:-4]}-USDT",
            "baseCurrency": symbol[:-4],
            "quoteCurrency": "USDT",
            "enableTrading": True,
        }
        for symbol in symbols
    ]

    def fake_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        if path == "/api/v2/symbols":
            return 200, {"code": "200000", "data": spot_rows}
        if path == "/api/v1/contracts/active":
            return 200, {"code": "200000", "data": []}
        if path == "/api/v1/market/orderbook/level1":
            return 200, {
                "code": "200000",
                "data": {
                    "time": 1780623600000,
                    "price": "10",
                    "bestBid": "9.9",
                    "bestAsk": "10.1",
                    "size": "1",
                },
            }
        if path == "/api/v1/market/candles":
            assert "limit" not in (params or {})
            assert {"startAt", "endAt"} <= set(params or {})
            return 200, {
                "code": "200000",
                "data": [[1780623600, "10", "10.1", "10.2", "9.9", "5", "50"]],
            }
        if path == "/api/v1/market/orderbook/level2_20":
            return 200, {
                "code": "200000",
                "data": {
                    "time": 1780623600000,
                    "bids": [["9.9", "2"]],
                    "asks": [["10.1", "3"]],
                },
            }
        raise AssertionError(f"unexpected KuCoin path: {base}{path} {params}")

    monkeypatch.setattr(worker, "_http_get_json", fake_get_json)
    monkeypatch.setattr(worker, "_now_ms", lambda: 1780623720000)
    payload = worker.build_payload(
        symbols,
        fetch_public_rest=True,
        timeframes=("1m",),
        public_rest_request_budget=5,
    )
    fetch = payload["public_rest_fetch"]

    assert payload["classification"] == "NATIVE_V2_PUBLIC_REST_PARTIAL_REQUEST_BUDGET"
    assert fetch["request_count"] == 5
    assert fetch["request_budget"] == 5
    assert fetch["request_budget_exhausted"] is True
    assert fetch["symbols_fetched"] == 1
    assert fetch["symbols_skipped_budget_count"] == 2
    assert fetch["symbols_unsupported_count"] == 0


def test_kucoin_persisted_cursor_covers_uneven_cycles_without_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.cli import v2_kucoin_ingestor_worker as worker

    symbols = (
        "AAAUSDT",
        "BTCUSDT",
        "BBBUSDT",
        "ETHUSDT",
        "CCCUSDT",
        "SOLUSDT",
        "DDDUSDT",
    )
    redis_client = _FakeRedis()
    clock = {"ms": 1_800_000_050_000}
    spot_rows = [
        {
            "symbol": f"{symbol[:-4]}-USDT",
            "baseCurrency": symbol[:-4],
            "quoteCurrency": "USDT",
            "enableTrading": True,
        }
        for symbol in symbols
    ]

    def fake_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        if path == "/api/v2/symbols":
            return 200, {"code": "200000", "data": spot_rows}
        if path == "/api/v1/contracts/active":
            return 200, {"code": "200000", "data": []}
        if path == "/api/v1/market/orderbook/level1":
            return 200, {
                "code": "200000",
                "data": {
                    "time": clock["ms"] - 1,
                    "price": "10",
                    "bestBid": "9.9",
                    "bestAsk": "10.1",
                    "size": "1",
                },
            }
        if path == "/api/v1/market/candles":
            closed_open_seconds = ((clock["ms"] // 60_000) - 1) * 60
            return 200, {
                "code": "200000",
                "data": [
                    [closed_open_seconds, "10", "10.1", "10.2", "9.9", "5", "50"]
                ],
            }
        if path == "/api/v1/market/orderbook/level2_20":
            return 200, {
                "code": "200000",
                "data": {
                    "time": clock["ms"] - 1,
                    "bids": [["9.9", "2"]],
                    "asks": [["10.1", "3"]],
                },
            }
        raise AssertionError(f"unexpected KuCoin path: {base}{path} {params}")

    monkeypatch.setattr(worker, "_connect_redis", lambda: redis_client)
    monkeypatch.setattr(worker, "_http_get_json", fake_get_json)
    monkeypatch.setattr(worker, "_now_ms", lambda: clock["ms"])

    def run_cycle(*, redis_ttl_seconds: int = 900) -> dict:
        return worker.build_payload(
            symbols,
            fetch_public_rest=True,
            timeframes=("1m",),
            write_v2_redis=True,
            redis_ttl_seconds=redis_ttl_seconds,
            public_rest_request_budget=17,
        )["public_rest_fetch"]

    first = run_cycle()
    assert [row["symbol"] for row in first["rows"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "AAAUSDT",
        "BBBUSDT",
    ]
    assert first["rotation_next_symbol"] == "CCCUSDT"
    assert first["rotation_cursor_source"] == "cold_start"
    assert first["rotation_cursor_persisted"] is True
    assert first["coverage_ledger_persisted"] is True
    assert first["runtime_ttl_compatibility"] == "warming"

    clock["ms"] += 388_000
    second = run_cycle()
    assert [row["symbol"] for row in second["rows"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "CCCUSDT",
        "DDDUSDT",
    ]
    assert second["rotation_next_symbol"] == "AAAUSDT"
    assert second["rotation_completed_wrap_count"] == 1
    assert second["rotation_cycle_start_interval_seconds_history"][-1] == 388.0
    assert second["runtime_ttl_compatibility"] == "warming"

    clock["ms"] += 388_000
    third = run_cycle()
    assert [row["symbol"] for row in third["rows"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "AAAUSDT",
        "BBBUSDT",
    ]
    assert third["rotation_next_symbol"] == "CCCUSDT"

    clock["ms"] += 388_000
    fourth = run_cycle()
    assert [row["symbol"] for row in fourth["rows"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "CCCUSDT",
        "DDDUSDT",
    ]
    assert fourth["scheduled_worst_case_revisit_seconds"] == 776.0
    assert fourth["runtime_ttl_compatibility"] == "safe"
    assert fourth["coverage_ledger"]["components_with_observed_revisit"] == 21

    persisted_ledger = json.loads(redis_client.values[worker.COVERAGE_LEDGER_KEY])
    assert set(persisted_ledger["symbols"]) == set(symbols)
    assert all(
        component["last_success_at_ms"] > 0
        for entry in persisted_ledger["symbols"].values()
        for component in entry["components"].values()
    )

    clock["ms"] += 388_000
    unsafe = run_cycle(redis_ttl_seconds=700)
    assert unsafe["runtime_ttl_compatibility"] == "unsafe"
    assert unsafe["runtime_ttl_compatibility_reason"] == (
        "scheduled_or_observed_revisit_not_below_configured_ttl"
    )
    assert unsafe["redis_ttl_seconds"] == 700
