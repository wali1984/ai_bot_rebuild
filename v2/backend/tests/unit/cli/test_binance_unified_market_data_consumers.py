from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from v2.backend.app.cli import paper_online_runtime
from v2.backend.app.cli import v2_feature_snapshot_builder as feature_builder


def _snapshot(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "price": 105.0,
        "source_type": "READONLY_MARKET_FEED",
        "source": "binance_usdm_wss_cache_primary",
        "source_pointer": (
            "v2:market:kline_current:binance:BTCUSDT:1m + "
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
        ),
        "generated_at": "2026-06-16T01:00:00-04:00",
        "last_event_at": "2026-06-16T00:59:59-04:00",
        "age_seconds": 1,
        "freshness_state": "CURRENT",
        "errors": [],
        "candles": [
            {
                "time": f"2026-06-16T00:5{index}:00-04:00",
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.5 + index,
                "volume": 10.0,
                "source_type": "READONLY_MARKET_FEED",
            }
            for index in range(6)
        ],
        "wss_cache_used": True,
        "wss_cache_reason": "WSS_CACHE_CURRENT",
        "rest_backup_used": False,
        "rest_backup_reason": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_paper_market_snapshot_uses_unified_binance_client(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        paper_online_runtime,
        "fetch_unified_market_snapshot",
        lambda *_args, **_kwargs: _snapshot(),
    )

    market = paper_online_runtime.fetch_market_snapshot("BTCUSDT")

    assert market.source == "binance_usdm_wss_cache_primary"
    assert market.source_pointer.startswith("v2:market:kline_current:binance:BTCUSDT:1m")
    assert market.generated_at.endswith("-04:00")
    assert market.last_event_at and market.last_event_at.endswith("-04:00")
    assert market.candles[0]["time"].endswith("-04:00")


def test_feature_snapshot_builder_preserves_unified_wss_provenance(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        feature_builder,
        "fetch_unified_market_snapshot",
        lambda *_args, **_kwargs: _snapshot(),
    )

    payload = feature_builder.fetch_live_payload("BTCUSDT")

    source = payload["sources"]["binance_unified_market_data"]
    assert payload["generated_ts"] == "2026-06-16T01:00:00-04:00"
    assert payload["feature_values"]["close"] == 105.0
    assert source["wss_cache_used"] is True
    assert source["rest_backup_used"] is False
    assert payload["source_key_refs"][0].startswith("v2:market:kline_current:binance:BTCUSDT:1m")


def test_active_paper_trainer_consumers_do_not_call_binance_rest_directly() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    active_files = [
        repo_root / "v2/backend/app/cli/paper_online_runtime.py",
        repo_root / "v2/backend/app/cli/v2_feature_snapshot_builder.py",
    ]
    for path in active_files:
        text = path.read_text(encoding="utf-8")
        assert "https://fapi.binance.com" not in text
        assert "urllib.request.urlopen" not in text
