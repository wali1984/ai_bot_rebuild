from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from v2.backend.app.services.market_state_integrity.trust import (
        ENFORCEMENT_EPOCH,
        TRUST_PRODUCER_VERSION,
        TRUST_SCHEMA_VERSION,
    )
except ModuleNotFoundError:  # pragma: no cover - supports app.* test imports
    from app.services.market_state_integrity.trust import (  # type: ignore[no-redef]
        ENFORCEMENT_EPOCH,
        TRUST_PRODUCER_VERSION,
        TRUST_SCHEMA_VERSION,
    )


SCHEMA_VERSION = "v2_coinapi_wsds_compat_status_v1"
V2_MARKET_KEY_TEMPLATE = "v2:market:coinapi:wsds:{symbol}"
V2_MICROFEAT_KEY_TEMPLATE = "v2:features:microfeat:{symbol}:{timeframe}"
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m")


def build_coinapi_wsds_status(
    *,
    credential_env_present: bool = False,
    operator_paid_streaming_approved: bool = False,
) -> dict[str, Any]:
    client_constructed = bool(credential_env_present and operator_paid_streaming_approved)
    blockers = []
    if not credential_env_present:
        blockers.append("coinapi_api_key_not_present_by_env_name")
    if not operator_paid_streaming_approved:
        blockers.append("coinapi_wsds_paid_streaming_not_operator_approved")
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": "V2_COINAPI_WSDS_OPERATOR_READY"
        if client_constructed
        else "V2_COINAPI_WSDS_OPERATOR_GATED",
        "source": "v2.backend.app.services.native_ingestors.coinapi_wsds",
        "client_constructed": client_constructed,
        "credential_env_name": "COINAPI_API_KEY",
        "credential_value_read": False,
        "operator_paid_streaming_approved": operator_paid_streaming_approved,
        "target_redis_key_patterns": [
            V2_MARKET_KEY_TEMPLATE,
            V2_MICROFEAT_KEY_TEMPLATE,
        ],
        "blockers": blockers,
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


def normalize_wsds_snapshot(
    *,
    symbol: str,
    snapshot: Mapping[str, Any],
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
) -> dict[str, Any]:
    if not symbol or not isinstance(symbol, str):
        raise ValueError("symbol must be a non-empty string")
    row = dict(snapshot)
    updated_ts_ms = row.get("updated_ts_ms") or row.get("ts_ms")
    trust_timestamps_present = updated_ts_ms is not None
    trust_block_reasons = [] if trust_timestamps_present else ["MISSING_TRUST_TIMESTAMPS"]
    market_payload = {
        "schema_version": "v2_coinapi_wsds_market_snapshot_v1",
        "symbol": symbol.upper(),
        "source": "coinapi_wsds",
        "updated_ts_ms": updated_ts_ms,
        "source_event_time": updated_ts_ms,
        "available_at": updated_ts_ms,
        "generated_at": updated_ts_ms,
        "best_bid_px": _safe_float(row.get("best_bid_px")),
        "best_ask_px": _safe_float(row.get("best_ask_px")),
        "mid_px": _safe_float(row.get("mid_px")),
        "spread": _safe_float(row.get("spread")),
        "microprice": _safe_float(row.get("microprice")),
        "book_bid_sum_5": _safe_float(row.get("book_bid_sum_5")),
        "book_ask_sum_5": _safe_float(row.get("book_ask_sum_5")),
        "imbalance_5": _safe_float(row.get("imbalance_5")),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    micro_features = {
        "churn_score": _safe_float(row.get("churn_score")),
        "snapback_score": _safe_float(row.get("snapback_score")),
        "spoof_score": _safe_float(row.get("spoof_score")),
        "fast_move_score": _safe_float(row.get("fast_move_score")),
        "p_false_move": _safe_float(row.get("p_false_move")),
        "trade_imbalance_1s": _safe_float(row.get("trade_imbalance_1s")),
        "trade_imbalance_5s": _safe_float(row.get("trade_imbalance_5s")),
    }
    return {
        "market_key": V2_MARKET_KEY_TEMPLATE.format(symbol=symbol.upper()),
        "market_payload": market_payload,
        "microfeat_payloads": {
            V2_MICROFEAT_KEY_TEMPLATE.format(symbol=symbol.upper(), timeframe=timeframe): {
                "schema_version": "v2_coinapi_wsds_microfeat_v1",
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "enforcement_epoch": ENFORCEMENT_EPOCH,
                "producer": "coinapi_wsds",
                "producer_version": TRUST_PRODUCER_VERSION,
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "source": "coinapi_wsds",
                "source_event_time": updated_ts_ms,
                "available_at": updated_ts_ms,
                "feature_cutoff": updated_ts_ms,
                "generated_at": updated_ts_ms,
                "feature_eligible": trust_timestamps_present,
                "trainer_consumable": False,
                "prediction_eligible": False,
                "trust_block_reasons": trust_block_reasons,
                "features": micro_features,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
            for timeframe in timeframes
        },
        "live_safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "places_real_order": False,
            "exchange_action_taken": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
