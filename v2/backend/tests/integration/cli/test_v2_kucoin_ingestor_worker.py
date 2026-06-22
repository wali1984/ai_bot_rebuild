"""V2 KuCoin ingestor tests (paper-only public-data config)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


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
    row = payload["public_rest_fetch"]["rows"][0]

    assert payload["classification"] == "BLOCKED_BY_NETWORK_OR_API"
    assert row["ticker"] is None
    assert row["funding"] is None
    assert row["contract"] is None
    assert row["orderbook20"] is None
    assert row["klines"] == {}
    assert row["endpoint_codes"]["spot_level1"] == "400302"


def test_kucoin_futures_fallback_populates_public_market_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from v2.backend.app.cli import v2_kucoin_ingestor_worker as worker

    def fake_get_json(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        if path == "/api/v1/market/orderbook/level1":
            return 200, {"code": "400100", "msg": "spot symbol not found"}
        if path == "/api/v1/ticker":
            return 200, {
                "code": "200000",
                "data": {
                    "price": "63331.1",
                    "bestBidPrice": "63331.0",
                    "bestAskPrice": "63331.2",
                    "size": "12",
                    "ts": 1780623600000,
                },
            }
        if path == "/api/v1/market/candles":
            return 200, {"code": "400100", "msg": "spot symbol not found"}
        if path == "/api/v1/kline/query":
            return 200, {"code": "200000", "data": [[1780623600000, 1.0, 1.2, 0.9, 1.1, 10, 11]]}
        if path == "/api/v1/market/orderbook/level2_20":
            return 200, {"code": "400100", "msg": "spot symbol not found"}
        if path == "/api/v1/level2/snapshot":
            return 200, {"code": "200000", "data": {"bids": [[1.0, 2]], "asks": [[1.1, 3]]}}
        if path == "/api/ua/v1/market/funding-rate":
            return 200, {
                "code": "200000",
                "data": {
                    "nextFundingRate": "-0.000241",
                    "fundingTime": 1776153600000,
                    "fundingRateCap": "0.003",
                    "fundingRateFloor": "-0.003",
                },
            }
        if path.startswith("/api/v1/contracts/"):
            return 200, {
                "code": "200000",
                "data": {"openInterest": "28864204", "markPrice": "63331.06", "indexPrice": "63334.66"},
            }
        raise AssertionError(f"unexpected KuCoin path: {base}{path} {params}")

    monkeypatch.setattr(worker, "_http_get_json", fake_get_json)
    payload = worker.build_payload(("BTCUSDT",), fetch_public_rest=True, timeframes=("1m",))
    row = payload["public_rest_fetch"]["rows"][0]

    assert payload["classification"] == "NATIVE_V2_PUBLIC_REST_OK"
    assert row["ticker"]["source"] == "kucoin_futures_public_rest"
    assert row["ticker"]["last"] == 63331.1
    assert row["klines"]["1m"]["source"] == "kucoin_futures_public_rest"
    assert row["orderbook20"]["source"] == "kucoin_futures_public_rest"
    assert row["funding"]["source"] == "kucoin_uta_public_rest"
    assert row["funding"]["rate"] == -0.000241
    assert row["contract"]["open_interest"] == 28864204.0
