"""Compact read models for enterprise web/iOS realtime surfaces."""

from __future__ import annotations

import json
import os
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
ENTERPRISE_UI_MATERIALIZED_MAX_AGE_SECONDS = float(
    os.environ.get("ALPHAFORGE_ENTERPRISE_UI_MATERIALIZED_MAX_AGE_SECONDS", "300")
)
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


def _freshness_status(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "unknown"
    if age_seconds <= 300:
        return "fresh"
    if age_seconds <= 1800:
        return "degraded"
    return "stale"


def _ui_canonical_owner(resource: str) -> str:
    return f"/api/v2/ui/{resource.replace('_', '-')}"


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


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return []


def _dict_keys_with_truthy_status(value: Any, *, accepted: set[str]) -> list[str]:
    if not isinstance(value, dict):
        return []
    names: list[str] = []
    for key, raw in value.items():
        status = ""
        if isinstance(raw, dict):
            status = str(_first(raw.get("status"), raw.get("dashboard_color"), raw.get("color"), "")).lower()
        elif isinstance(raw, bool):
            status = "green" if raw else "gray"
        else:
            status = str(raw).lower()
        if status in accepted:
            names.append(str(key))
    return sorted(names)


def _active_endpoint_names(endpoint_status: dict[str, Any], metric_status: dict[str, Any]) -> list[str]:
    endpoints = _as_list(endpoint_status.get("active_endpoints"))
    if not endpoints:
        endpoints = _as_list(endpoint_status.get("endpoints_active"))
    if not endpoints:
        endpoints = _dict_keys_with_truthy_status(
            endpoint_status.get("endpoints") or endpoint_status,
            accepted={"ok", "green", "active", "available", "success", "true"},
        )
    metrics = _as_list(metric_status.get("active_metrics"))
    if metrics:
        endpoints.extend(f"metric:{metric}" for metric in metrics)
    return sorted({str(item) for item in endpoints if str(item).strip()})


def _disabled_endpoint_names(endpoint_status: dict[str, Any], metric_status: dict[str, Any]) -> list[str]:
    disabled = [
        *_as_list(endpoint_status.get("disabled_endpoints")),
        *_as_list(endpoint_status.get("endpoints_disabled")),
        *_as_list(metric_status.get("disabled_metrics")),
    ]
    if not disabled:
        disabled = _dict_keys_with_truthy_status(
            endpoint_status.get("endpoints") or endpoint_status,
            accepted={"disabled", "gray", "plan_blocked", "forbidden", "403", "blocked"},
        )
    return sorted({str(item) for item in disabled if str(item).strip()})


def _live_gate_value(client: Any) -> str:
    state = _read_json(client, "v2:live_gate:state")
    return str(
        _first(
            state.get("live_gate"),
            state.get("gate"),
            state.get("state"),
            _read_text(client, "v2:live_gate"),
            "blocked_human_only",
        )
    )


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
        # Moralis health publishes windowed counts, not a flat field.
        health.get("actual_payload_count_1h"),
        health.get("actual_payload_count_5m"),
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

    active_endpoints = _active_endpoint_names(endpoint_status, metric_status)
    disabled_endpoints = _disabled_endpoint_names(endpoint_status, metric_status)
    consumer_roles = _as_list(_first(bridge.get("consumer_roles"), health.get("consumer_roles")))
    symbols_covered = _as_list(_first(
        bridge.get("symbols_covered"),
        health.get("symbols_covered"),
        endpoint_status.get("symbols_covered"),
        metric_status.get("symbols_covered"),
    ))
    family_status = _first(
        endpoint_status.get("families"),
        endpoint_status.get("endpoint_families"),
        metric_status.get("metrics"),
        metric_status.get("metric_status"),
        {},
    )

    return {
        "provider": provider,
        "display_name": "Santiment/Sanbase" if provider == "santiment" else provider.replace("_", " ").title(),
        "subscription_tier": _first(
            health.get("subscription_tier"),
            health.get("subscription_status"),
            bridge.get("subscription_tier"),
            bridge.get("subscription_status"),
            usage.get("subscription_tier"),
            "unknown",
        ),
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
        "consumer_roles": [str(role) for role in consumer_roles],
        "symbols_covered": [str(symbol) for symbol in symbols_covered],
        "rate_limit": rate or usage,
        "rate_limit_used": _first(rate.get("used"), rate.get("used_minute"), usage.get("used")),
        "rate_limit_remaining": _first(
            rate.get("remaining"),
            rate.get("remaining_minute"),
            rate.get("rate_limit_remaining_minute"),
            usage.get("remaining"),
        ),
        "daily_quota_used": _first(usage.get("daily_used"), usage.get("cu_used_today"), usage.get("used_today")),
        "monthly_quota_used": _first(usage.get("monthly_used"), usage.get("cu_used_month"), usage.get("used_month")),
        "endpoints_active": active_endpoints,
        "endpoints_disabled": disabled_endpoints,
        "provider_family_status": family_status,
        "cu_usage": usage if provider == "moralis" else {},
        "heartbeat_only": heartbeat_only,
        "actual_payload_present": actual_payload_count > 0,
        "raw_key_exposed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "watchlist_count": watchlist.get("watchlist_count") if provider == "moralis" else None,
        "smart_wallet_candidate_count": _first(
            watchlist.get("candidate_smart_wallet_count"),
            watchlist.get("candidate_count"),
            watchlist.get("t0_count"),
        ) if provider == "moralis" else None,
        "verified_smart_wallet_count": watchlist.get("verified_smart_wallet_count") if provider == "moralis" else None,
        "token_map_count": token_map.get("token_map_count") if provider == "moralis" else None,
        "metric_count": metric_status.get("metric_count") if provider == "santiment" else None,
        "missing_high_value_metrics": (
            metric_status.get("missing_high_value_metrics")
            if provider == "santiment"
            else None
        ),
        "disabled_heatmap_endpoint": (
            "liquidation_heatmap_or_levels" in disabled_endpoints
            if provider == "coinglass"
            else None
        ),
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
        "live_gate": _live_gate_value(client),
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
            _live_gate_value(client),
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


def _ai_brain_edge_backtest_runway(client: Any) -> dict[str, Any]:
    """Realtime edge / backtest / generalization / A-grade-runway blocks.

    Folded into the streamed ai_brain resource so every field updates over the
    existing WebSocket with no refresh/loading gap. All read-only.
    """
    trainer_status = _read_json(client, "v2:trainer:hybrid_cuda:status")
    util = trainer_status.get("cuda_cpu_resource_utilization")
    pb = util.get("policy_backtest") if isinstance(util, dict) else {}
    pb = pb if isinstance(pb, dict) else {}
    lm = trainer_status.get("learning_metrics")
    lm = lm if isinstance(lm, dict) else {}
    roll = trainer_status.get("parallel_environment_rollout")
    roll = roll if isinstance(roll, dict) else {}
    cf = _read_json(client, "v2:trainer:feedback:counterfactual_status")
    ef = _read_json(client, "v2:edge_factory:replay_status")
    gate = _read_json(client, "v2:continuous_edge_guardian:a_grade_execution_gate")
    burn = _read_json(client, "v2:paper:a_grade_gate_burndown_status")
    src = burn.get("source_rows") if isinstance(burn.get("source_rows"), dict) else {}
    pes = _read_json(client, "v2:paper:preemptive_edge_control_status")
    return {
        "edge": {
            "policy_entropy": lm.get("ppo_entropy"),
            "rollout_reward_avg_bps": roll.get("reward_avg_bps"),
            "rollout_reward_max_bps": roll.get("reward_max_bps"),
            "rollout_reward_min_bps": roll.get("reward_min_bps"),
            "online_learning_status": trainer_status.get("online_learning_status"),
            "last_weight_update": trainer_status.get("last_successful_weight_update_at"),
        },
        "backtest_replay": {
            "available": bool(pb),
            "win_rate": pb.get("win_rate"),
            "profit_factor": pb.get("profit_factor_proxy"),
            "expectancy_after_cost_bps": pb.get("expectancy_after_cost_bps"),
            "rows_evaluated": pb.get("rows_evaluated"),
            "evidence_class": pb.get("evidence_class"),
            "backtest_is_a_plus_evidence": False,
            "validation_supervised_loss": lm.get("validation_supervised_loss"),
            "train_loss": lm.get("loss_after"),
            "train_val_generalization_gap": lm.get("train_val_generalization_gap"),
            "overfit_gap_warning": lm.get("overfit_gap_warning"),
            "continuous_replay_active": bool(ef),
            "replay_examples_built": trainer_status.get("trusted_replay_examples_built"),
            "counterfactual_rows": cf.get("existing_counterfactual_rows"),
            "counterfactual_pending": cf.get("pending_rows"),
        },
        "a_grade_runway": {
            "gate_status": gate.get("status"),
            "a_grade_new_entries_allowed": gate.get("a_grade_new_entries_allowed"),
            "A_grade_rows": burn.get("A_grade_rows"),
            "near_A_grade_rows": burn.get("near_A_grade_rows"),
            "closed_rows": src.get("closed_rows"),
            "requirements": [
                {"reason": f.get("reason"), "observed": f.get("observed"), "required": f.get("required")}
                for f in (gate.get("failure_reasons") or [])
                if isinstance(f, dict)
            ][:16],
            "preemptive_candidate_count": pes.get("candidate_count"),
            "preemptive_accepted_count": pes.get("accepted_count"),
            "preemptive_action_counts": pes.get("action_counts"),
        },
    }


def _trainer_payload(client: Any) -> dict[str, Any]:
    providers_payload = _providers_payload(client)
    provider_counts = {
        card["provider"]: card["feature_count"] for card in providers_payload["providers"]
    }
    provider_consumption = _read_json(client, "v2:altdata:provider_consumption_status")
    trainer_summary = _read_json(client, "v2:trainer:summary")
    ppo_watch = _read_json(client, "v2:trainer:ppo_on_policy_watch_status")
    return {
        "schema_version": "enterprise_ai_brain_snapshot_v1",
        **_ai_brain_edge_backtest_runway(client),
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
            "ppo_on_policy": {
                "objective_used": bool(ppo_watch.get("ppo_objective_used")),
                "clipped_surrogate_active": bool(ppo_watch.get("ppo_objective_used")),
                "why_surrogate_inactive": ppo_watch.get(
                    "why_ppo_surrogate_inactive"
                ),
                "rows_pending": ppo_watch.get("ppo_rows_pending"),
                "rows_consumed": ppo_watch.get("ppo_rows_consumed"),
                "learning_update_lane": ppo_watch.get("learning_update_lane"),
                "open_positions_waiting_for_close": ppo_watch.get(
                    "open_positions_waiting_for_close"
                ),
                "closed_positions_ready_for_ppo": ppo_watch.get(
                    "closed_positions_ready_for_ppo"
                ),
                "last_consumed_utc": ppo_watch.get("last_consumed_utc"),
            },
            "decision_scope": "display_only_no_live_approval",
            "live_gate": _live_gate_value(client),
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
        "live_gate": _live_gate_value(client),
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
        "status": "CONTROL_CENTER_RESOURCE_INDEX_READY",
        "resource_refs": {
            "portfolio": "/api/v2/ui/portfolio",
            "paper": "/api/v2/paper/runtime-status",
            "risk": "/api/v2/ui/risk",
            "providers": "/api/v2/ui/providers",
            "trainer": "/api/v2/ui/ai-brain",
            "trader_cockpit": "/api/v2/ui/trader-cockpit",
        },
        "primary_realtime_stream": "/api/v2/stream/runtime",
        "websocket_endpoint": "/api/v2/realtime/ws",
        "go_no_go": "BLOCKED_HUMAN_ONLY",
        "live_gate": _live_gate_value(client),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def build_ui_snapshot(client: Any, resource: str, *, use_materialized: bool = True) -> dict[str, Any]:
    normalized = normalize_resource_name(resource)
    if normalized not in resource_names():
        raise KeyError(normalized)
    stale_materialized_key: str | None = None
    stale_materialized_age: float | None = None
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
        if (
            age is not None
            and age > max(1.0, ENTERPRISE_UI_MATERIALIZED_MAX_AGE_SECONDS)
        ):
            stale_materialized_key = redis_key
            stale_materialized_age = age
            materialized = None
        else:
            out = dict(materialized)
            out["generated_utc"] = _utc_now()
            out["display_time_et"] = _display_time_et()
            out["source"] = redis_key or out.get("source") or "redis_materialized"
            out["source_type"] = "redis_materialized"
            out["source_keys"] = [redis_key] if redis_key else list(out.get("source_keys") or [])
            out["staleness_seconds"] = age
            freshness_status = _freshness_status(age)
            out["freshness_status"] = freshness_status
            out["data_quality"] = (
                "stale"
                if freshness_status == "stale"
                else "partial" if out.get("error_sections") else "valid"
            )
            out["data_quality_status"] = out["data_quality"]
            out["canonical_owner"] = _ui_canonical_owner(normalized)
            out["missing_sections"] = [
                section
                for section in list(out.get("missing_sections") or [])
                if section != "redis_materialized_view"
            ]
            out["live_gate"] = _live_gate_value(client)
            out["last_good_payload_used"] = False
            out["routes_to_live"] = False
            out["places_real_order"] = False
            return out
    from_materialized = materialized is not None
    payload = materialized if materialized is not None else _fallback_payload(client, normalized)
    age = payload_age_seconds(payload)
    if not from_materialized and age is None:
        age = 0.0
    missing_sections: list[str] = []
    if not from_materialized:
        missing_sections.append("redis_materialized_view")
    if stale_materialized_key:
        missing_sections.append("redis_materialized_view_stale")
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
        "source_keys": [key for key in (redis_key if from_materialized else stale_materialized_key,) if key],
        "stale_materialized_source_key": stale_materialized_key,
        "stale_materialized_age_seconds": stale_materialized_age,
        "staleness_seconds": age,
        "freshness_status": _freshness_status(age),
        "data_quality": data_quality,
        "data_quality_status": data_quality,
        "canonical_owner": _ui_canonical_owner(normalized),
        "missing_sections": missing_sections,
        "error_sections": [],
        "last_good_payload_used": False,
        "payload": payload,
        "live_gate": _live_gate_value(client),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _bootstrap_resource_alias(resource: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "enterprise_realtime_resource_alias_v1",
        "resource": resource,
        "endpoint": _ui_canonical_owner(resource),
        "payload_schema_version": (
            snapshot.get("payload", {}).get("schema_version")
            if isinstance(snapshot.get("payload"), dict)
            else None
        ),
        "source": snapshot.get("source"),
        "source_type": snapshot.get("source_type"),
        "staleness_seconds": snapshot.get("staleness_seconds"),
        "freshness_status": snapshot.get("freshness_status"),
        "data_quality_status": snapshot.get("data_quality_status") or snapshot.get("data_quality"),
        "live_gate": snapshot.get("live_gate"),
        "routes_to_live": False,
        "places_real_order": False,
    }


def build_enterprise_bootstrap(client: Any) -> dict[str, Any]:
    resources = {name: build_ui_snapshot(client, name) for name in resource_names()}
    ages = [
        float(resource["staleness_seconds"])
        for resource in resources.values()
        if isinstance(resource.get("staleness_seconds"), (int, float))
    ]
    age = max(ages) if ages else 0.0
    freshness = _freshness_status(age)
    resource_qualities = {
        str(resource.get("data_quality_status") or resource.get("data_quality") or "unknown")
        for resource in resources.values()
    }
    if "stale" in resource_qualities or freshness == "stale":
        data_quality_status = "stale"
    elif "partial" in resource_qualities or freshness == "degraded":
        data_quality_status = "partial"
    else:
        data_quality_status = "fresh"
    return {
        "schema_version": "enterprise_realtime_bootstrap_v1",
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "display_timezone": "America/New_York",
        "source": "redis_materialized_or_compact_fallback",
        "staleness_seconds": age,
        "freshness_status": freshness,
        "canonical_owner": "/api/v2/realtime/bootstrap",
        "data_quality_status": data_quality_status,
        "auth": {"required_for_controls": True, "public_routes": ["login", "health"]},
        "portfolio": _bootstrap_resource_alias("portfolio", resources["portfolio"]),
        "paper": {
            "schema_version": "enterprise_realtime_resource_alias_v1",
            "resource": "paper",
            "endpoint": "/api/v2/paper/runtime-status",
            "freshness_status": resources["dashboard"].get("freshness_status"),
            "data_quality_status": resources["dashboard"].get("data_quality_status") or resources["dashboard"].get("data_quality"),
            "live_gate": _live_gate_value(client),
            "routes_to_live": False,
            "places_real_order": False,
        },
        "risk": _bootstrap_resource_alias("risk", resources["risk"]),
        "trainer": _bootstrap_resource_alias("ai_brain", resources["ai_brain"]),
        "signals": {},
        "providers": _bootstrap_resource_alias("providers", resources["providers"]),
        "ingestors": _bootstrap_resource_alias("providers", resources["providers"]),
        "markets": _bootstrap_resource_alias("markets", resources["markets"]),
        "live_canary": {
            "schema_version": "enterprise_realtime_resource_alias_v1",
            "resource": "live_canary",
            "endpoint": "/api/v2/live-canary/status",
            "freshness_status": resources["risk"].get("freshness_status"),
            "data_quality_status": resources["risk"].get("data_quality_status") or resources["risk"].get("data_quality"),
            "live_gate": _live_gate_value(client),
            "routes_to_live": False,
            "places_real_order": False,
        },
        "alerts": {},
        "ui_hints": {
            "default_pnl_display": "usd_and_percent",
            "show_stale_degraded_state": True,
            "live_controls_disabled": True,
        },
        "resources": resources,
        "live_gate": _live_gate_value(client),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
