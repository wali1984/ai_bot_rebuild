from __future__ import annotations

from v2.backend.app.services import binance_readonly_probe as probe


def test_http_get_blocks_binance_rest_without_fallback(monkeypatch) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)

    status, body, headers = probe._http_get("https://fapi.binance.com/fapi/v1/time")

    assert status == 0
    assert body["error"] == "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"
    assert body["required_env"] == "BINANCE_REST_FALLBACK_ALLOWED=true"
    assert headers == {}
