"""Compact read models for enterprise web/iOS realtime surfaces."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.services.portfolio import build_canonical_pnl
from app.services.realtime.redis_materialized_views import (
    payload_age_seconds,
    read_materialized_view,
)
from app.services.realtime.resource_registry import (
    normalize_resource_name,
    resource_key,
    resource_names,
)

DISPLAY_TZ = ZoneInfo("America/New_York")
PROVIDER_NAMES = (
    "binance",
    "kucoin",
    "coinank",
    "coinglass",
    "santiment",
    "moralis",
    "ta",
    "feature_snapshot_builder",
    "microstructure",
    "liquidations",
    "orderbook",
    "trainer_feed",
    "portfolio_publisher",
    "paper_loop",
    "live_canary",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


def _json_object(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json(client: Any, key: str) -> dict[str, Any]:
    if client is None:
        return {}
    try:
        return _json_object(client.get(key))
    except Exception:
        return {}


def _read_text(client: Any, key: str) -> str | None:
    if client is None:
        return None
    try:
        value = client.get(key)
    except Exception:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value) if value is not None else None


def _count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _provider_card(client: Any, provider: str) -> dict[str, Any]:
    health = _read_json(client, f"v2:provider:{provider}:health")
    bridge = _read_json(client, f"v2:provider:{provider}:feature_bridge_status")
    rate = _read_json(client, f"v2:provider:{provider}:rate_limit")
    usage = _read_json(client, f"v2:provider:{provider}:usage")
    endpoint_status = _read_json(client, f"v2:provider:{provider}:endpoint_status")
    metric_status = _read_json(client, f"v2:provider:{provider}:metric_status")
    watchlist = _read_json(client, "v2:moralis:wallet_watchlist_status") if provider == "moralis" else {}
    token_map = _read_json(client, "v2:moralis:token_map_status") if provider == "moralis" else {}

    feature_count = _count(_first(
        bridge.get("feature_count"),
        health.get("feature_count"),
        bridge.get("required_feature_count"),
    ))
    actual_payload_count = _count(_first(
        health.get("actual_payload_count"),
        bridge.get("actual_payload_count"),
        endpoint_status.get("actual_payload_count"),
        metric_status.get("actual_payload_count"),
        1 if (health.get("actual_payload_present") or bridge.get("actual_payload_present")) else 0,
    )) or 0
    heartbeat_only = bool(
        health.get("heartbeat_only") is True
        or bridge.get("heartbeat_only") is True
        or (actual_payload_count <= 0 and not bridge and bool(health))
    )
    consumer_count = _count(_first(
        bridge.get("consumer_count"),
        health.get("consumer_count"),
        len(bridge.get("consumer_roles") or []) if isinstance(bridge.get("consumer_roles"), list) else None,
    )) or 0
    raw_color = str(_first(
        bridge.get("dashboard_color"),
        health.get("dashboard_color"),
        health.get("status_color"),
        "gray",
    )).lower()
    dashboard_color = "yellow" if heartbeat_only and raw_color == "green" else raw_color
    if feature_count is None and provider in {"binance", "kucoin", "coinank", "ta", "microstructure", "liquidations", "orderbook"}:
        feature_count = 0

    return {
        "provider": provider,
        "display_name": "Santiment/Sanbase" if provider == "santiment" else provider.replace("_", " ").title(),
        "status": _first(bridge.get("status"), health.get("status"), "unknown"),
        "dashboard_color": dashboard_color,
        "dashboard_color_reason": (
            "heartbeat_only_forces_yellow" if heartbeat_only and raw_color == "green"
            else _first(bridge.get("dashboard_color_reason"), health.get("dashboard_color_reason"), "provider_runtime_summary")
        ),
        "actual_payload_count": actual_payload_count,
        "last_success_utc": _first(bridge.get("last_success_utc"), health.get("last_success_utc")),
        "last_error_utc": _first(bridge.get("last_error_utc"), health.get("last_error_utc")),
        "source_lag_seconds": _first(bridge.get("source_lag_seconds"), health.get("source_lag_seconds")),
        "keys_published": [key for key in (
            f"v2:provider:{provider}:health",
            f"v2:provider:{provider}:feature_bridge_status",
        ) if _read_json(client, key)],
        "feature_count": feature_count or 0,
        "consumer_count": consumer_count,
        "rate_limit": rate or usage,
        "cu_usage": usage if provider == "moralis" else {},
        "heartbeat_only": heartbeat_only,
        "actual_payload_present": actual_payload_count > 0,
        "raw_key_exposed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "watchlist_count": watchlist.get("watchlist_count") if provider == "moralis" else None,
        "token_map_count": token_map.get("token_map_count") if provider == "moralis" else None,
        "metric_count": metric_status.get("metric_count") if provider == "santiment" else None,
    }


def _providers_payload(client: Any) -> dict[str, Any]:
    cards = [_provider_card(client, provider) for provider in PROVIDER_NAMES]
    return {
        "schema_version": "enterprise_provider_cards_v1",
        "providers": cards,
        "provider_count": len(cards),
        "heartbeat_only_green_count": sum(
            1 for card in cards if card["heartbeat_only"] and card["dashboard_color"] == "green"
        ),
        "live_gate": _read_text(client, "v2:live_gate") or "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _risk_payload(client: Any) -> dict[str, Any]:
    live_canary = _read_json(client, "v2:live_canary:status")
    preemptive = _read_json(client, "v2:preemptive:runtime_status")
    probation = _read_json(client, "v2:paper:probation_5_trade_gate")
    return {
        "schema_version": "enterprise_risk_snapshot_v1",
        "live_gate": _first(
            live_canary.get("live_gate"),
            _read_text(client, "v2:live_gate"),
            "blocked_human_only",
        ),
        "kill_switch": _read_text(client, "v2:kill_switch") or "not_set",
        "signed_read_status": _first(live_canary.get("signed_read_status"), "unknown"),
        "probation_gate": probation,
        "preemptive_runtime": preemptive,
        "live_canary": live_canary,
        "mutation_flags": {
            "places_real_order": False,
            "places_test_order": False,
            "cancels_order": False,
            "modifies_order": False,
            "mutates_leverage": False,
            "mutates_margin_mode": False,
            "transfers_or_withdraws": False,
        },
        "operator_approval_required": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _paper_payload(client: Any) -> dict[str, Any]:
    ledger = _read_json(client, "v2:paper:ledger")
    heartbeat = _read_json(client, "v2:paper:heartbeat")
    heartbeat_summary = {
        key: heartbeat.get(key)
        for key in (
            "heartbeat_generated_at",
            "generated_utc",
            "cycle_state",
            "classification",
            "live_gate",
            "new_entries_allowed",
            "paper_new_entries_halted",
            "paper_session_id",
            "open_position_count",
            "closed_trade_count",
            "intents_built",
            "intents_accepted",
            "intents_blocked",
            "signals_seen",
            "model_source",
            "paper_only",
            "routes_to_live",
            "places_real_order",
        )
        if key in heartbeat
    }
    return {
        "schema_version": "enterprise_paper_snapshot_v1",
        "ledger": {
            "generated_utc": ledger.get("generated_utc"),
            "status": ledger.get("status"),
            "closed_trade_count": ledger.get("closed_trade_count"),
            "open_position_count": ledger.get("open_position_count"),
        },
        "heartbeat": heartbeat_summary,
        "heartbeat_compacted": bool(heartbeat),
        "entry_freeze": _read_text(client, "v2:paper:entry_freeze"),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _trainer_payload(client: Any) -> dict[str, Any]:
    providers_payload = _providers_payload(client)
    provider_counts = {
        card["provider"]: card["feature_count"] for card in providers_payload["providers"]
    }
    provider_consumption = _read_json(client, "v2:altdata:provider_consumption_status")
    trainer_summary = _read_json(client, "v2:trainer:summary")
    return {
        "schema_version": "enterprise_ai_brain_snapshot_v1",
        "trainer_summary": trainer_summary,
        "champion_challenger": _read_json(client, "v2:trainer:champion_challenger_status"),
        "preemptive_feedback": _read_json(client, "v2:trainer:preemptive_blocked_counterfactual_status"),
        "provider_feature_counts": provider_counts,
        "provider_consumption_status": provider_consumption,
        "provider_confluence_available": bool(provider_consumption),
        "ai_page_contract": {
            "schema_version": "enterprise_ai_page_contract_v1",
            "ppo_tensor_provider_features": bool(provider_consumption.get("provider_tensor_consumption")),
            "masa_tensor_provider_features": bool(provider_consumption.get("provider_tensor_consumption")),
            "provider_feature_count_by_provider": provider_counts,
            "provider_features_in_tensor": provider_consumption.get("provider_tensor_consumption"),
            "provider_contribution_last_50": _first(
                provider_consumption.get("provider_contribution_last_50"),
                trainer_summary.get("provider_contribution_last_50"),
                {"status": "not_available", "sample_count": 0},
            ),
            "altdata_actionability": {
                "blocked": _first(provider_consumption.get("blocked_count"), 0),
                "reduced": _first(provider_consumption.get("reduced_count"), 0),
                "hedged": _first(provider_consumption.get("hedged_count"), 0),
                "trade_block_score": provider_consumption.get("confluence_trade_block_score"),
                "reduce_size_score": provider_consumption.get("confluence_reduce_size_score"),
                "hedge_required_score": provider_consumption.get("confluence_hedge_required_score"),
            },
            "next_replay_or_backtest": _first(
                provider_consumption.get("next_replay_or_backtest"),
                trainer_summary.get("next_replay_or_backtest"),
                "pending_runtime_scheduler",
            ),
            "decision_scope": "display_only_no_live_approval",
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
        },
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _markets_payload(client: Any) -> dict[str, Any]:
    universe = _read_json(client, "v2:symbol_universe:status")
    top_symbols = _read_json(client, "v2:market:top_symbols")
    return {
        "schema_version": "enterprise_markets_snapshot_v1",
        "symbol_universe": universe,
        "top_symbols": top_symbols.get("symbols") or top_symbols.get("rows") or [],
        "provider_confluence_available": bool(_read_json(client, "v2:altdata:provider_consumption_status")),
        "source_note": "compact Redis materialized market summary; heavy /api/v2/markets remains a fallback only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _system_health_payload(client: Any) -> dict[str, Any]:
    return {
        "schema_version": "enterprise_system_health_snapshot_v1",
        "backend_service": "active",
        "redis_available": client is not None,
        "frontend_production_serving": "dist_served_by_backend_when_built",
        "frontend_vite_dev_only": True,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _trader_cockpit_payload(client: Any) -> dict[str, Any]:
    live_canary = _read_json(client, "v2:live_canary:status")
    confluence = _read_json(client, "v2:altdata:provider_consumption_status")
    return {
        "schema_version": "enterprise_trader_cockpit_snapshot_v1",
        "active_candidate": _first(live_canary.get("active_candidate"), live_canary.get("candidate")),
        "entry_plan": _first(live_canary.get("entry_plan"), {}),
        "exit_plan": _first(live_canary.get("exit_plan"), {}),
        "hedge_plan": _first(live_canary.get("hedge_plan"), {}),
        "expected_net_pnl_usd": live_canary.get("expected_net_pnl_usd"),
        "expected_max_loss_usd": live_canary.get("expected_max_loss_usd"),
        "liquidation_buffer_usd": live_canary.get("liquidation_buffer_usd"),
        "provider_confluence": confluence,
        "live_blocked_reason": _first(live_canary.get("live_blocker"), "blocked_human_only"),
        "order_ticket_enabled": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _fallback_payload(client: Any, resource: str) -> dict[str, Any]:
    if resource == "portfolio":
        return build_canonical_pnl(client)
    if resource == "providers":
        return _providers_payload(client)
    if resource == "risk":
        return _risk_payload(client)
    if resource == "ai_brain":
        return _trainer_payload(client)
    if resource == "markets":
        return _markets_payload(client)
    if resource == "system_health":
        return _system_health_payload(client)
    if resource == "trader_cockpit":
        return _trader_cockpit_payload(client)
    return {
        "schema_version": "enterprise_dashboard_snapshot_v1",
        "portfolio": build_canonical_pnl(client),
        "paper": _paper_payload(client),
        "risk": _risk_payload(client),
        "providers": _providers_payload(client),
        "trainer": _trainer_payload(client),
        "go_no_go": "BLOCKED_HUMAN_ONLY",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def build_ui_snapshot(client: Any, resource: str, *, use_materialized: bool = True) -> dict[str, Any]:
    normalized = normalize_resource_name(resource)
    if normalized not in resource_names():
        raise KeyError(normalized)
    if use_materialized:
        materialized, redis_key = read_materialized_view(client, normalized)
    else:
        materialized, redis_key = None, resource_key(normalized)
    while (
        isinstance(materialized, dict)
        and materialized.get("schema_version") == "enterprise_ui_snapshot_v1"
        and isinstance(materialized.get("payload"), dict)
        and materialized["payload"].get("schema_version") == "enterprise_ui_snapshot_v1"
        and materialized["payload"].get("resource") == normalized
    ):
        materialized = materialized["payload"]
    if (
        isinstance(materialized, dict)
        and materialized.get("schema_version") == "enterprise_ui_snapshot_v1"
        and materialized.get("resource") == normalized
    ):
        age = payload_age_seconds(materialized)
        out = dict(materialized)
        out["generated_utc"] = _utc_now()
        out["display_time_et"] = _display_time_et()
        out["source"] = redis_key or out.get("source") or "redis_materialized"
        out["source_type"] = "redis_materialized"
        out["source_keys"] = [redis_key] if redis_key else list(out.get("source_keys") or [])
        out["staleness_seconds"] = age
        out["data_quality"] = "valid" if not out.get("error_sections") else "partial"
        out["missing_sections"] = [
            section
            for section in list(out.get("missing_sections") or [])
            if section != "redis_materialized_view"
        ]
        out["last_good_payload_used"] = False
        out["routes_to_live"] = False
        out["places_real_order"] = False
        return out
    from_materialized = materialized is not None
    payload = materialized if materialized is not None else _fallback_payload(client, normalized)
    age = payload_age_seconds(payload)
    missing_sections: list[str] = []
    if not from_materialized:
        missing_sections.append("redis_materialized_view")
    data_quality = "valid" if from_materialized else "partial"
    if isinstance(payload, dict) and payload.get("missing_fields"):
        data_quality = "partial"

    return {
        "schema_version": "enterprise_ui_snapshot_v1",
        "resource": normalized,
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "source_timezone": "UTC",
        "display_timezone": "America/New_York",
        "source": redis_key if from_materialized else "compact_live_fallback",
        "source_type": "redis_materialized" if from_materialized else "computed_fallback",
        "source_keys": [redis_key] if redis_key else [],
        "staleness_seconds": age,
        "data_quality": data_quality,
        "missing_sections": missing_sections,
        "error_sections": [],
        "last_good_payload_used": False,
        "payload": payload,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def build_enterprise_bootstrap(client: Any) -> dict[str, Any]:
    resources = {name: build_ui_snapshot(client, name) for name in resource_names()}
    return {
        "schema_version": "enterprise_realtime_bootstrap_v1",
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "display_timezone": "America/New_York",
        "source": "redis_materialized_or_compact_fallback",
        "auth": {"required_for_controls": True, "public_routes": ["login", "health"]},
        "portfolio": resources["portfolio"]["payload"],
        "paper": resources["dashboard"]["payload"].get("paper", {}),
        "risk": resources["risk"]["payload"],
        "trainer": resources["ai_brain"]["payload"],
        "signals": {},
        "providers": resources["providers"]["payload"],
        "ingestors": resources["providers"]["payload"],
        "markets": resources["markets"]["payload"],
        "live_canary": resources["risk"]["payload"].get("live_canary", {}),
        "alerts": {},
        "ui_hints": {
            "default_pnl_display": "usd_and_percent",
            "show_stale_degraded_state": True,
            "live_controls_disabled": True,
        },
        "resources": resources,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
