from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TRADER_RUNTIME_STATE_SCHEMA_VERSION = "v2_trader_runtime_state_v1"


def build_trader_runtime_state(
    *,
    portfolio_state: Mapping[str, Any] | None = None,
    opportunity_summary: Mapping[str, Any] | None = None,
    risk_gateway_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    portfolio = dict(portfolio_state or {})
    opportunity = dict(opportunity_summary or {})
    risk = dict(risk_gateway_status or {})
    return {
        "schema_version": TRADER_RUNTIME_STATE_SCHEMA_VERSION,
        "classification": "V2_TRADER_RUNTIME_STATE_PAPER_ONLY",
        "source": "v2.backend.app.composition.trader_runtime_state",
        "portfolio_classification": portfolio.get("classification"),
        "opportunity_classification": opportunity.get("classification"),
        "risk_gateway_classification": risk.get("classification") or risk.get("go_no_go"),
        "symbols_tracked": portfolio.get("symbols_tracked", 0),
        "symbols_with_activity": portfolio.get("symbols_with_activity", 0),
        "top_opportunity_symbols": opportunity.get("top_symbols", []),
        "account_mode": "paper_shadow_only",
        "trader_execution_enabled": False,
        "live_gate_status": "blocked_human_only",
        "live_symbols": [],
        "live_safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "trader_execution_enabled": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }
