from __future__ import annotations

from typing import Any

from v2.backend.app.services.execution import binance_usdm_adapter as adapter_module


def test_commission_contract_reserves_exact_shared_ip_weight(
    monkeypatch: Any,
) -> None:
    observed: list[dict[str, Any]] = []

    def fallback_decision(**kwargs: Any) -> dict[str, Any]:
        observed.append(dict(kwargs))
        return {
            "request_allowed": False,
            "rest_fallback_blocked_reason": "UNIT_BLOCKED",
        }

    monkeypatch.setattr(
        adapter_module,
        "binance_rest_fallback_decision",
        fallback_decision,
    )
    adapter = adapter_module.BinanceUSDMAdapter()

    contract = adapter.signed_get_contract(
        "/fapi/v1/commissionRate",
        {"symbol": "BTCUSDT"},
        fallback_reason="TRAINER_CAUSAL_FEE_CAPTURE",
    )

    assert observed == [
        {
            "endpoint": "GET /fapi/v1/commissionRate",
            "fallback_reason": "TRAINER_CAUSAL_FEE_CAPTURE",
            "role": "signed_read_recovery",
            "request_weight": 20,
            "require_shared_budget": True,
        }
    ]
    assert contract["rest_fallback_request_weight"] == 20
    assert contract["rest_fallback_shared_budget_required"] is True
    assert contract["would_call"] is False


def test_unverified_weight_endpoint_preserves_bounded_default(
    monkeypatch: Any,
) -> None:
    observed: list[dict[str, Any]] = []

    def fallback_decision(**kwargs: Any) -> dict[str, Any]:
        observed.append(dict(kwargs))
        return {
            "request_allowed": False,
            "rest_fallback_blocked_reason": "UNIT_BLOCKED",
        }

    monkeypatch.setattr(
        adapter_module,
        "binance_rest_fallback_decision",
        fallback_decision,
    )
    adapter = adapter_module.BinanceUSDMAdapter()

    contract = adapter.signed_get_contract(
        "/fapi/v3/account",
        fallback_reason="WSS_ACCOUNT_CACHE_STALE",
    )

    assert observed[0]["request_weight"] == 1
    assert observed[0]["require_shared_budget"] is False
    assert contract["rest_fallback_request_weight"] == 1
    assert contract["rest_fallback_shared_budget_required"] is False


def test_endpoint_matrix_exposes_commission_budget_contract() -> None:
    matrix = adapter_module.endpoint_contract_matrix()

    assert matrix["signed_rest_request_weight_overrides"] == {
        "/fapi/v1/commissionRate": 20,
    }
    assert matrix["signed_rest_shared_budget_endpoints"] == [
        "/fapi/v1/commissionRate"
    ]
