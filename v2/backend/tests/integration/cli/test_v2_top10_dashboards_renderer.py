"""Tests for the V2 Top-10 market + alt-data dashboard renderer.

The renderer is display-only and must:

- never call a provider endpoint (no network);
- classify every panel into one of five explicit states;
- write its payload to BOTH the worklog and the public mirror;
- never serialize raw credentials or live-trading approvals.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from v2.backend.app.cli.v2_top10_dashboards_renderer import (
    STATE_BUDGET_LIMITED,
    STATE_KEY_MISSING,
    STATE_KEY_PRESENT_NO_CLIENT_YET,
    STATE_OK_ROWS_PRESENT,
    STATE_STALE,
    _FUNDING_SYMBOLS,
    build_dashboard_payload,
)


class _FakeRedis:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = dict(store or {})

    def get(self, key: str):
        return self.store.get(key)


def _iso(seconds_old: int = 0) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(seconds=seconds_old))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# --------------------------------------------------------------------------- #
# State-classification tests                                                  #
# --------------------------------------------------------------------------- #


def test_renderer_emits_eight_panels_with_legend_and_safety_pins() -> None:
    payload = build_dashboard_payload(_FakeRedis())
    assert payload["go_no_go"] == "V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_RENDERING_READY"
    assert payload["panels_total"] == 8
    assert isinstance(payload["panels"], list) and len(payload["panels"]) == 8
    # Legend covers every possible state.
    legend = payload["panel_state_legend"]
    for state in (
        STATE_OK_ROWS_PRESENT,
        STATE_KEY_PRESENT_NO_CLIENT_YET,
        STATE_KEY_MISSING,
        STATE_STALE,
        STATE_BUDGET_LIMITED,
    ):
        assert state in legend
    # Display-only safety pins.
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["dry_run"] is True
    assert payload["live_enabled"] is False
    assert payload["real_order_attempted"] is False
    assert payload["real_order_submitted"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert payload["no_provider_network_calls_from_frontend"] is True
    assert payload["no_provider_network_calls_from_renderer"] is True
    assert payload["no_live_buttons"] is True
    assert payload["no_order_buttons"] is True
    assert payload["no_shutdown_claim"] is True
    assert payload["display_only"] is True


def test_renderer_with_empty_redis_marks_all_panels_key_missing_or_no_client_yet() -> None:
    payload = build_dashboard_payload(_FakeRedis())
    for panel in payload["panels"]:
        assert panel["state"] in (
            STATE_KEY_MISSING,
            STATE_KEY_PRESENT_NO_CLIENT_YET,
        )
        assert panel["rank_count"] == 0
        assert panel["rows"] == []


def test_binance_panel_with_fresh_rows_classifies_ok_rows_present() -> None:
    store = {
        "v2:dashboards:binance_top10:spot_volume_12h": json.dumps(
            {
                "generated_utc": _iso(seconds_old=10),
                "source_status": "API_OK",
                "window_size_requested": "12h",
                "window_size_actual": "12h",
                "rows": [
                    {"rank": 1, "symbol": "BTCUSDT", "quote_volume": 12345.6, "last_price": 77000},
                    {"rank": 2, "symbol": "ETHUSDT", "quote_volume": 9999.9, "last_price": 3000},
                ],
            }
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    spot_vol = next(p for p in payload["panels"] if p["panel_id"] == "binance_spot_volume_12h")
    assert spot_vol["state"] == STATE_OK_ROWS_PRESENT
    assert spot_vol["rank_count"] == 2
    assert spot_vol["rows"][0]["symbol"] == "BTCUSDT"
    assert spot_vol["source_status"] == "API_OK"
    assert spot_vol["window_size_requested"] == "12h"


def test_binance_panel_with_stale_payload_classifies_stale() -> None:
    store = {
        "v2:dashboards:binance_top10:futures_volume_12h": json.dumps(
            {
                "generated_utc": _iso(seconds_old=99_999),
                "source_status": "API_OK",
                "rows": [
                    {"rank": 1, "symbol": "BTCUSDT", "quote_volume": 100.0},
                ],
            }
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    futures_vol = next(
        p for p in payload["panels"] if p["panel_id"] == "binance_futures_volume_12h"
    )
    assert futures_vol["state"] == STATE_STALE


def test_binance_panel_fresh_payload_with_no_rows_downgrades_to_no_client_yet() -> None:
    store = {
        "v2:dashboards:binance_top10:spot_trades_12h": json.dumps(
            {
                "generated_utc": _iso(seconds_old=5),
                "source_status": "API_OK",
                "rows": [],
            }
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    spot_trades = next(
        p for p in payload["panels"] if p["panel_id"] == "binance_spot_trades_12h"
    )
    assert spot_trades["state"] == STATE_KEY_PRESENT_NO_CLIENT_YET
    assert spot_trades["rank_count"] == 0


def test_liquidation_panel_with_heartbeat_only_is_no_client_yet() -> None:
    store = {
        "v2:market:liquidations:heartbeat": json.dumps(
            {"generated_utc": _iso(seconds_old=30), "process_mode": "persistent_daemon"}
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    liq = next(p for p in payload["panels"] if p["panel_id"] == "liquidation_tape_top_symbols")
    assert liq["state"] == STATE_KEY_PRESENT_NO_CLIENT_YET
    assert liq["rank_count"] == 0


def test_liquidation_panel_with_aggregated_rows_is_ok_rows_present() -> None:
    store = {
        "v2:market:liquidations:heartbeat": json.dumps(
            {"generated_utc": _iso(seconds_old=20)}
        ),
        "v2:market:liquidations:top_symbols": json.dumps(
            {
                "generated_utc": _iso(seconds_old=20),
                "rows": [
                    {"rank": 1, "symbol": "BTCUSDT", "liquidated_notional_usdt": 1.2e6, "long_count": 8, "short_count": 12},
                ],
            }
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    liq = next(p for p in payload["panels"] if p["panel_id"] == "liquidation_tape_top_symbols")
    assert liq["state"] == STATE_OK_ROWS_PRESENT
    assert liq["rank_count"] == 1
    assert liq["rows"][0]["symbol"] == "BTCUSDT"


def test_funding_oi_panel_with_no_keys_is_key_missing() -> None:
    payload = build_dashboard_payload(_FakeRedis())
    funding = next(p for p in payload["panels"] if p["panel_id"] == "funding_oi_movers")
    assert funding["state"] == STATE_KEY_MISSING
    assert funding["rank_count"] == 0
    assert sorted(funding["missing_symbols"]) == sorted(funding["tracked_symbols"])


def test_funding_oi_panel_with_fresh_values_is_ok_rows_present_and_ranks_by_abs_funding() -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    store = {}
    for index, symbol in enumerate(_FUNDING_SYMBOLS):
        rate = (index + 1) / 1_000_000
        if index == len(_FUNDING_SYMBOLS) - 1:
            rate = -0.00020
        store[f"v2:market:funding:{symbol}"] = json.dumps(
            {"symbol": symbol, "lastFundingRate": str(rate), "time": now_ms - 30_000}
        )
        store[f"v2:market:open_interest:{symbol}"] = json.dumps(
            {"symbol": symbol, "openInterest": str(100000.0 - index), "time": now_ms - 30_000}
        )
        store[f"v2:market:long_short:{symbol}"] = json.dumps(
            {
                "symbol": symbol,
                "long_short_ratio": 1.0 + (index / 10.0),
                "timestamp": now_ms - 30_000,
            }
        )
    payload = build_dashboard_payload(_FakeRedis(store))
    funding = next(p for p in payload["panels"] if p["panel_id"] == "funding_oi_movers")
    assert funding["state"] == STATE_OK_ROWS_PRESENT
    assert funding["rank_count"] == len(_FUNDING_SYMBOLS)
    # The largest absolute rate ranks first.
    assert funding["rows"][0]["symbol"] == _FUNDING_SYMBOLS[-1]
    assert funding["rows"][0]["rank"] == 1
    assert funding["rows"][0]["long_short_ratio"] is not None


def test_funding_oi_panel_with_old_epoch_times_is_stale() -> None:
    very_old_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 10_000_000
    store = {}
    for symbol in _FUNDING_SYMBOLS:
        store[f"v2:market:funding:{symbol}"] = json.dumps(
            {"symbol": symbol, "lastFundingRate": "0.0001", "time": very_old_ms}
        )
        store[f"v2:market:open_interest:{symbol}"] = json.dumps(
            {"symbol": symbol, "openInterest": "100000", "time": very_old_ms}
        )
    payload = build_dashboard_payload(_FakeRedis(store))
    funding = next(p for p in payload["panels"] if p["panel_id"] == "funding_oi_movers")
    assert funding["state"] == STATE_STALE


def test_panel_rows_are_capped_at_ten() -> None:
    rows = [
        {"rank": i, "symbol": f"SYM{i:02d}", "quote_volume": float(100 - i)}
        for i in range(1, 25)
    ]
    store = {
        "v2:dashboards:binance_top10:spot_volume_12h": json.dumps(
            {"generated_utc": _iso(0), "source_status": "API_OK", "rows": rows}
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    spot_vol = next(p for p in payload["panels"] if p["panel_id"] == "binance_spot_volume_12h")
    assert spot_vol["rank_count"] == 10
    assert len(spot_vol["rows"]) == 10


def test_payload_does_not_contain_raw_credential_like_values() -> None:
    secret = "sk-LEAK-1234567890abcdef-TOP10-RENDERER-TEST"
    store = {
        "v2:dashboards:binance_top10:spot_volume_12h": json.dumps(
            {
                "generated_utc": _iso(seconds_old=10),
                "source_status": "API_OK",
                # Synthetic adversarial: even if an upstream exporter
                # erroneously leaked a secret into extra payload/row
                # fields, the renderer copies only its whitelisted
                # fields and never serializes the secret.
                "api_key": secret,
                "rows": [
                    {
                        "rank": 1,
                        "symbol": "BTCUSDT",
                        "quote_volume": 12345.6,
                        "leaked_field": secret,
                    }
                ],
            }
        ),
    }
    payload = build_dashboard_payload(_FakeRedis(store))
    flat = json.dumps(payload)
    assert secret not in flat
    assert payload["raw_credential_in_payload"] == "NEVER"


def test_renderer_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Static guarantee: building the dashboard payload calls no
    HTTP function. We monkeypatch urlopen on the off chance any
    transitive import opens a socket."""
    import urllib.request as _urllib_request

    calls: list[Any] = []

    def _spy(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        raise RuntimeError("renderer must never call urlopen")

    monkeypatch.setattr(_urllib_request, "urlopen", _spy)
    payload = build_dashboard_payload(_FakeRedis())
    assert calls == []
    assert payload["no_provider_network_calls_from_renderer"] is True
