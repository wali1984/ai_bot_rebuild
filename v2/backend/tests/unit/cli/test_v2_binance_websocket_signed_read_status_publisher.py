from __future__ import annotations

from typing import Any

from v2.backend.app.cli import v2_binance_websocket_signed_read_status_publisher as mod


class FakeAdapter:
    has_credentials = True

    def signed_ws_read(self, method: str, *, execute: bool = True) -> dict[str, Any]:
        assert execute is True
        if method == "account.status":
            return {
                "status": "SIGNED_WS_READ_EXECUTED",
                "ws_status_code": 200,
                "error_type": None,
                "endpoint": "wss://ws-fapi.binance.com/ws-fapi/v1",
                "response_json": {
                    "status": 200,
                    "result": {
                        "canTrade": True,
                        "canDeposit": True,
                        "canWithdraw": False,
                        "availableBalance": "25.5",
                        "totalWalletBalance": "50.0",
                        "totalMarginBalance": "48.0",
                        "totalUnrealizedProfit": "-2.0",
                        "assets": [{"asset": "USDT"}],
                        "positions": [],
                    },
                },
            }
        if method == "account.balance":
            return {
                "status": "SIGNED_WS_READ_EXECUTED",
                "ws_status_code": 200,
                "error_type": None,
                "endpoint": "wss://ws-fapi.binance.com/ws-fapi/v1",
                "response_json": {
                    "status": 200,
                    "result": [
                        {
                            "asset": "USDT",
                            "balance": "50.0",
                            "crossWalletBalance": "45.0",
                            "crossUnPnl": "-1.5",
                            "availableBalance": "30.0",
                        },
                        {
                            "asset": "USDC",
                            "balance": "2.0",
                            "crossWalletBalance": "2.0",
                            "crossUnPnl": "0.0",
                            "availableBalance": "2.0",
                        },
                    ],
                },
            }
        return {
            "status": "SIGNED_WS_READ_EXECUTED",
            "ws_status_code": 200,
            "error_type": None,
            "endpoint": "wss://ws-fapi.binance.com/ws-fapi/v1",
            "response_json": {
                "status": 200,
                "result": [
                    {"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": "0"},
                    {"symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "0.1"},
                ],
            },
        }


def test_build_status_publishes_dry_run_signed_read_contract(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod.BinanceUSDMAdapter, "from_env", classmethod(lambda _cls: FakeAdapter()))

    payload = mod.build_status(execute=True)

    assert payload["signed_read_overall_status"] == "WEBSOCKET_PRIMARY_READY"
    assert payload["places_real_order"] is False
    assert payload["order_submitted"] is False
    assert payload["test_order_submitted"] is False
    account = payload["signed_ws_read_results"]["account.status"]
    balance = payload["signed_ws_read_results"]["account.balance"]
    position = payload["signed_ws_read_results"]["account.position"]
    assert account["transport"] == "websocket_api_primary"
    assert account["response_summary"]["availableBalance"] == "25.5"
    assert balance["transport"] == "websocket_api_primary"
    assert balance["response_summary"]["usdt_available_balance"] == "30.0"
    assert balance["response_summary"]["total_available_balance_usd_equivalent"] == 32.0
    assert balance["response_summary"]["raw_balance_payload_stored"] is False
    assert account["raw_response_stored"] is False
    assert account["api_key_exposed"] is False
    assert account["api_secret_exposed"] is False
    assert position["response_summary"]["open_positions_count"] == 1
    assert position["raw_response_stored"] is False


def test_public_view_excludes_balance_and_position_details(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod.BinanceUSDMAdapter, "from_env", classmethod(lambda _cls: FakeAdapter()))
    payload = mod.build_status(execute=True)

    view = mod._public_view(payload, published=True)

    assert view["redis_published"] is True
    assert view["signed_read_overall_status"] == "WEBSOCKET_PRIMARY_READY"
    assert "availableBalance" not in str(view)
    assert "crossWalletBalance" not in str(view)
    assert "positionAmt" not in str(view)
    assert view["raw_credentials_exposed"] is False
