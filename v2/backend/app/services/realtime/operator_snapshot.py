"""Compact read models for enterprise web/iOS realtime surfaces."""

from __future__ import annotations

import json
import os
import time
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


def _iso_age_seconds(value: Any) -> float | None:
    """Age in seconds of an ISO-8601 timestamp, or None if unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _provider_card(client: Any, provider: str) -> dict[str, Any]:
    health = _read_json(client, f"v2:provider:{provider}:health")
    bridge = _read_json(client, f"v2:provider:{provider}:feature_bridge_status")
    rate = _read_json(client, f"v2:provider:{provider}:rate_limit")
    usage = _read_json(client, f"v2:provider:{provider}:usage")
    endpoint_status = _read_json(client, f"v2:provider:{provider}:endpoint_status")
    metric_status = _read_json(client, f"v2:provider:{provider}:metric_status")
    watchlist = _read_json(client, "v2:moralis:wallet_watchlist_status") if provider == "moralis" else {}
    cu_budget = _read_json(client, "v2:provider:moralis:cu_budget_status") if provider == "moralis" else {}
    cu_ledger = usage.get("persistent_cu_ledger") if isinstance(usage.get("persistent_cu_ledger"), dict) else {}
    token_map = _read_json(client, "v2:moralis:token_map_status") if provider == "moralis" else {}
    scheduler = _read_json(client, "v2:provider:moralis:scheduler_status") if provider == "moralis" else {}

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

    # Freshness/lag/last-success truth for the card footer rows. Publishers
    # use several field names; derive missing lag from the last-success age.
    last_success_utc = _first(
        bridge.get("last_success_utc"),
        health.get("last_success_utc"),
        health.get("last_success_at"),
        bridge.get("last_success_at"),
    )
    source_lag_seconds = _first(bridge.get("source_lag_seconds"), health.get("source_lag_seconds"))
    if source_lag_seconds is None:
        _success_age = _iso_age_seconds(last_success_utc)
        if _success_age is not None:
            source_lag_seconds = round(_success_age, 3)
    health_generated_utc = _first(
        health.get("generated_utc"),
        bridge.get("generated_utc"),
        health.get("generated_at"),
        bridge.get("generated_at"),
    )
    health_age = _iso_age_seconds(health_generated_utc)

    # ISOLATED_BY_POLICY is a deliberate consumption quarantine, not a failure.
    # Surface the policy scope + the real rejection reasons from the health key
    # so UIs can show reason text instead of a bare gray chip.
    status_value = str(_first(bridge.get("status"), health.get("status"), "unknown"))
    status_policy = None
    if "ISOLATED_BY_POLICY" in status_value.upper():
        policy_reasons = health.get("source_temporal_rejection_reasons")
        status_policy = {
            "policy": "ISOLATED_BY_POLICY",
            "scope": "trainer_consumption",
            "trainer_consumption_status": health.get("trainer_consumption_status"),
            "trainer_isolation_active": health.get("trainer_isolation_active"),
            "reasons": [str(r) for r in policy_reasons] if isinstance(policy_reasons, list) else [],
            "transport_status": health.get("current_transport_status"),
            "auth_status": health.get("auth_status"),
            "core_system_blocked": health.get("core_system_blocked"),
            "explanation": (
                "Deliberate policy quarantine: provider payloads are ingested but "
                "isolated from trainer/decision-time consumers until temporal "
                "receipts are bound. Transport/auth health is tracked separately; "
                "gray here is a hold, not an outage."
            ),
        }

    return {
        "provider": provider,
        "display_name": provider.replace("_", " ").title(),
        "subscription_tier": _first(
            health.get("subscription_tier"),
            health.get("subscription_status"),
            bridge.get("subscription_tier"),
            bridge.get("subscription_status"),
            usage.get("subscription_tier"),
            "unknown",
        ),
        "status": _first(bridge.get("status"), health.get("status"), "unknown"),
        "status_policy": status_policy,
        "dashboard_color": dashboard_color,
        "dashboard_color_reason": (
            "heartbeat_only_forces_yellow" if heartbeat_only and raw_color == "green"
            else _first(bridge.get("dashboard_color_reason"), health.get("dashboard_color_reason"), "provider_runtime_summary")
        ),
        "actual_payload_count": actual_payload_count,
        # Field-name variants: some publishers write last_success_at /
        # last_error_at (e.g. coinglass health) instead of *_utc; without
        # these fallbacks the card rows rendered permanent dashes.
        "last_success_utc": last_success_utc,
        "last_error_utc": _first(
            bridge.get("last_error_utc"),
            health.get("last_error_utc"),
            health.get("last_error_at"),
            bridge.get("last_error_at"),
        ),
        "source_lag_seconds": source_lag_seconds,
        "freshness_status": _freshness_status(health_age),
        "health_generated_utc": health_generated_utc,
        "keys_published": [key for key in (
            f"v2:provider:{provider}:health",
            f"v2:provider:{provider}:feature_bridge_status",
        ) if _read_json(client, key)],
        "feature_count": feature_count or 0,
        "consumer_count": consumer_count,
        "consumer_roles": [str(role) for role in consumer_roles],
        "symbols_covered": [str(symbol) for symbol in symbols_covered],
        "rate_limit": rate or usage,
        "rate_limit_used": _first(
            rate.get("used"),
            rate.get("used_minute"),
            usage.get("used"),
            rate.get("requests_per_minute"),
            usage.get("requests_per_minute"),
        ),
        "rate_limit_remaining": _first(
            rate.get("remaining"),
            rate.get("remaining_minute"),
            rate.get("rate_limit_remaining_minute"),
            usage.get("remaining"),
            # Token-bucket publishers (coinglass) expose live capacity as
            # tokens_available; the card left this null while the nested
            # rate_limit block carried the value one level deeper.
            rate.get("tokens_available"),
            usage.get("tokens_available"),
        ),
        # The durable CU-ledger rework nests spend under persistent_cu_ledger /
        # the dedicated cu_budget_status key; the old flat fields no longer exist.
        "daily_quota_used": _first(
            usage.get("daily_used"), usage.get("cu_used_today"), usage.get("used_today"),
            cu_ledger.get("day_spent_cu"), cu_budget.get("day_spent_cu"),
        ),
        "monthly_quota_used": _first(
            usage.get("monthly_used"), usage.get("cu_used_month"), usage.get("used_month"),
            cu_ledger.get("month_spent_cu"), cu_budget.get("month_spent_cu"),
        ),
        "endpoints_active": active_endpoints,
        "endpoints_disabled": disabled_endpoints,
        "provider_family_status": family_status,
        "cu_usage": usage if provider == "moralis" else {},
        "cu_budget": {
            "day_spent_cu": cu_budget.get("day_spent_cu"),
            "month_spent_cu": cu_budget.get("month_spent_cu"),
            "remaining_today_cu": cu_budget.get("remaining_today_cu"),
            "remaining_month_cu": cu_budget.get("remaining_month_cu"),
            "provider_polling_blocked": cu_budget.get("provider_polling_blocked"),
        } if provider == "moralis" and cu_budget else None,
        "heartbeat_only": heartbeat_only,
        "actual_payload_present": actual_payload_count > 0,
        "raw_key_exposed": False,
        "routes_to_live": False,
        "places_real_order": False,
        # wallet_watchlist_status has a 6h TTL and the reworked bootstrap no
        # longer refreshes it; the resident loop's health key carries the count.
        "watchlist_count": _first(
            watchlist.get("watchlist_count"), health.get("wallet_watchlist_count"),
        ) if provider == "moralis" else None,
        "smart_wallet_candidate_count": _first(
            watchlist.get("candidate_smart_wallet_count"),
            watchlist.get("candidate_count"),
            watchlist.get("t0_count"),
        ) if provider == "moralis" else None,
        "verified_smart_wallet_count": watchlist.get("verified_smart_wallet_count") if provider == "moralis" else None,
        "token_map_count": token_map.get("token_map_count") if provider == "moralis" else None,
        # Scheduler run-control state (v2:provider:moralis:scheduler_status).
        # Scoped SCHEDULER_RUN_CONTROL_STATE — it must never override the
        # provider-health color above; it explains WHY the scheduler is pacing.
        "scheduler_run_state": {
            "status": scheduler.get("status"),
            "status_scope": scheduler.get("status_scope"),
            "bootstrap_status": scheduler.get("bootstrap_status"),
            "scheduler_run_suppressed_reason": scheduler.get("scheduler_run_suppressed_reason"),
            "active_candidate_chain": scheduler.get("active_candidate_chain"),
            "active_candidate_wallet_count": _first(
                scheduler.get("active_candidate_wallet_count"),
                scheduler.get("chain_candidate_wallet_count"),
                scheduler.get("wallet_count"),
            ),
            "candidate_wallet_count": scheduler.get("candidate_wallet_count"),
            "candidate_wallet_chain_counts": scheduler.get("candidate_wallet_chain_counts")
            if isinstance(scheduler.get("candidate_wallet_chain_counts"), dict) else {},
            "queued_candidate_wallet_count": scheduler.get("queued_candidate_wallet_count"),
            "queued_candidate_wallet_chain_counts": scheduler.get("queued_candidate_wallet_chain_counts")
            if isinstance(scheduler.get("queued_candidate_wallet_chain_counts"), dict) else {},
            "queued_candidate_wallet_polling_status": scheduler.get("queued_candidate_wallet_polling_status"),
            "watchlist_refresh_action": scheduler.get("watchlist_refresh_action"),
            "watchlist_refresh_succeeded": scheduler.get("watchlist_refresh_succeeded"),
            "candidate_chain_activation_policy": scheduler.get("candidate_chain_activation_policy"),
            "paced_cu_admission_credit_balance_cu": scheduler.get("paced_cu_admission_credit_balance_cu"),
            "current_run_compute_unit_budget": scheduler.get("current_run_compute_unit_budget"),
            "current_run_admitted_compute_units": scheduler.get("current_run_admitted_compute_units"),
            "paced_cu_admission_denied_count": scheduler.get("paced_cu_admission_denied_count"),
            "quarantined_contract_count": scheduler.get("quarantined_contract_count"),
            "unsupported_endpoint_contract_count": scheduler.get("unsupported_endpoint_contract_count"),
            "deduplicated_endpoint_contract_count": scheduler.get("deduplicated_endpoint_contract_count"),
            "durable_cadence_claim_count": scheduler.get("durable_cadence_claim_count"),
            "durable_cadence_suppressed_count": scheduler.get("durable_cadence_suppressed_count"),
            "generated_utc": scheduler.get("generated_utc"),
            "source_key": "v2:provider:moralis:scheduler_status",
        } if provider == "moralis" and scheduler else None,
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


def _hedge_payload(client: Any) -> dict[str, Any]:
    """Hedge-engine posture summary for realtime display (read-only, on-demand).

    The hedge engine (risk.hedge_first_controller + hedge_engine.cross_margin_stress)
    is evaluated per negative/adverse position; this surfaces its posture so the UI
    can show whether any open position needs a hedge and the portfolio buffer. Never
    places an order.
    """
    def _f(value: Any) -> float | None:
        try:
            f = float(value)
            return f if f == f else None  # drop NaN
        except (TypeError, ValueError):
            return None

    raw = _read_json(client, "v2:paper:positions")
    positions = raw.get("positions") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    positions = positions if isinstance(positions, list) else []
    open_positions = [
        p for p in positions
        if isinstance(p, dict) and (p.get("is_open") is True or str(p.get("status") or "open").lower() == "open")
    ]

    def _upnl(p: dict[str, Any]) -> float | None:
        return _f(_first(p.get("unrealized_pnl_usd"), p.get("unrealized_pnl"), p.get("upnl_usd")))

    negative = [p for p in open_positions if (_upnl(p) or 0.0) < 0.0]
    portfolio = _read_json(client, "v2:portfolio:state")
    return {
        "schema_version": "enterprise_hedge_snapshot_v1",
        "hedge_engine_active": True,
        "hedge_evaluation_mode": "on_demand_per_negative_position",
        "open_position_count": len(open_positions),
        "negative_position_count": len(negative),
        "hedge_required_candidates": [
            {"symbol": p.get("symbol"), "side": p.get("side"), "unrealized_pnl_usd": _upnl(p)}
            for p in negative
        ][:10],
        "portfolio_liquidation_buffer_usd": _first(
            portfolio.get("portfolio_liquidation_buffer_usd"),
            portfolio.get("liquidation_buffer_usd"),
        ),
        "hedge_basket": ["same_symbol_opposite", "BTC", "ETH", "SOL", "top5_beta", "correlation", "cash"],
        "cross_margin_model": "portfolio_level",
        "places_real_order": False,
        "routes_to_live": False,
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
        "hedge": _hedge_payload(client),
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


def _ingestors_payload(client: Any) -> dict[str, Any]:
    """Consolidated ingestor / provider health roll-up (read-only, lightweight).

    Provider health is read by KNOWN name (``PROVIDER_NAMES``) via direct GETs —
    never a ``scan_iter(match="v2:provider:*:health")`` enumeration, which on a
    large keyspace (millions of keys) must exhaust the cursor to collect the ~15
    sparse provider keys and can take tens of seconds. Per-stream presence is
    short-circuited from provider health first (O(1)); a bounded first-match scan
    is only a fallback when the mapped provider is not reporting healthy, so an
    absent stream can never trigger a full-keyspace scan on the hot path.
    """
    def _age_s(ts: Any) -> float | None:
        if not ts:
            return None
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
            return (datetime.now(UTC) - t).total_seconds()
        except Exception:
            return None

    # ── Provider health: direct reads over the known registry (O(providers)). ──
    provider_health: dict[str, Any] = {}
    stale_providers: list[str] = []
    provider_active: dict[str, bool] = {}
    if client is not None:
        for name in PROVIDER_NAMES:
            payload = _read_json(client, f"v2:provider:{name}:health")
            if not isinstance(payload, dict):
                continue
            age = _age_s(payload.get("generated_utc") or payload.get("generated_at"))
            status = payload.get("status")
            provider_health[name] = {
                "status": status,
                "age_seconds": round(age, 1) if age is not None else None,
                "freshness": _freshness_status(age),
            }
            stale = age is not None and age > 900
            if stale:
                stale_providers.append(name)
            provider_active[name] = (
                str(status or "").upper() in {"ACTIVE", "OK", "HEALTHY", "LIVE_OK"} and not stale
            )

    def _present(pattern: str, deadline_s: float = 0.35) -> bool:
        # Wall-clock-bounded first-match scan; only reached when the mapped
        # provider is not reporting healthy. A present (dense) stream hits on the
        # first round; an absent/sparse pattern can NEVER run away into a full
        # keyspace scan (which on a millions-of-keys Redis costs tens of seconds).
        if client is None:
            return False
        scan = getattr(client, "scan", None)
        try:
            if callable(scan):
                cursor = 0
                start = time.monotonic()
                while True:
                    cursor, keys = scan(cursor=cursor, match=pattern, count=2048)
                    if keys:
                        return True
                    if int(cursor) == 0 or (time.monotonic() - start) > deadline_s:
                        return False
            # Fallback for test doubles without .scan (small keyspaces only).
            for _ in client.scan_iter(match=pattern, count=512):
                return True
            return False
        except Exception:
            return False

    def _stream(provider: str | None, *patterns: str) -> bool:
        if provider is not None and provider_active.get(provider):
            return True
        return any(_present(p) for p in patterns)

    streams = {
        "candles": _stream("binance", "v2:market:kline*", "v2:market:ohlcv*"),
        "orderbook_features": _stream("orderbook", "v2:orderbook:features:*"),
        "trade_tape": _stream("binance", "v2:market:trade_tape_features:*"),
        # Funding/OI: cheapest-hitting pattern first; coinank is a common source
        # but the direct funding keys are authoritative, so probe those first.
        "funding_oi": _stream("coinank", "v2:*funding*", "v2:coinank:funding*"),
        "liquidation_levels": _stream("liquidations", "v2:liquidations:levels:*"),
        "ta_full": _stream("ta", "v2:features:ta_full:*"),
        "feature_snapshots": _stream("feature_snapshot_builder", "v2:features:snapshot:*"),
    }

    critical_present = streams["candles"] and streams["ta_full"] and streams["feature_snapshots"]
    if not critical_present:
        overall = "DEGRADED_MISSING_CORE_STREAM"
    elif stale_providers:
        overall = "SOME_PROVIDERS_STALE"
    else:
        overall = "HEALTHY"
    return {
        "schema_version": "enterprise_ingestors_rollup_v1",
        "overall_status": overall,
        "stream_present": streams,
        "all_core_streams_present": bool(critical_present),
        "provider_health": provider_health,
        "provider_count": len(provider_health),
        "active_provider_count": sum(1 for active in provider_active.values() if active),
        "stale_provider_count": len(stale_providers),
        "stale_providers": stale_providers,
        "paper_only": True,
    }


def _system_health_payload(client: Any) -> dict[str, Any]:
    return {
        "schema_version": "enterprise_system_health_snapshot_v1",
        "backend_service": "active",
        "ingestors": _ingestors_payload(client),
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
