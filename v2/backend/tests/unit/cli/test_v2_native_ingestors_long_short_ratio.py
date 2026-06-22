from __future__ import annotations

import pytest

from v2.backend.app.cli import v2_native_ingestors_live_loop as loop


def test_fetch_long_short_ratio_normalizes_binance_row(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str):
        assert "globalLongShortAccountRatio" in url
        return [
            {
                "symbol": "BTCUSDT",
                "longShortRatio": "1.25",
                "longAccount": "0.555",
                "shortAccount": "0.445",
                "timestamp": "1715500120000",
            }
        ]

    monkeypatch.setattr(loop, "_http_get_json", fake_get)

    payload = loop._fetch_long_short_ratio("BTCUSDT")

    assert payload is not None
    assert payload["long_short_ratio"] == 1.25
    assert payload["long_account_ratio"] == 0.555
    assert payload["short_account_ratio"] == 0.445
    assert payload["source"] == "binance_global_long_short_account_ratio"


def test_fetch_long_short_ratio_restricted_binance_payload_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda _url: {
            "code": 0,
            "msg": "Service unavailable from a restricted location.",
        },
    )

    assert loop._fetch_long_short_ratio("BTCUSDT") is None
