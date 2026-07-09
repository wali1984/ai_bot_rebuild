"""Current-session A+ live-canary candidate inventory.

Read-only. This command reads runtime Redis payloads and writes inventory
artifacts. It does not submit orders, write Redis, or mutate exchange state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.allocator import build_allocator_simulation
from v2.backend.app.services.preemptive_edge_control import evaluate_candidate


SCHEMA_VERSION = "v2_a_plus_candidate_inventory_v1"
TARGET_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
PREEMPTIVE_MATRIX_KEY = "v2:paper:preemptive_candidate_decision_matrix"
PREEMPTIVE_STATUS_KEY = "v2:paper:preemptive_edge_control_status"
LIVE_GATE_KEY = "v2:live_gate:state"

ALLOWED_BLOCKER_CLASSES = (
    "DATA_FRESHNESS_BLOCKER",
    "FEATURE_COVERAGE_BLOCKER",
    "MICROSTRUCTURE_TRUST_BLOCKER",
    "PROVIDER_MISSING_BLOCKER",
    "TRAINER_CONFIDENCE_BLOCKER",
    "EXPECTED_NET_EDGE_BLOCKER",
    "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER",
    "RISK_GATEWAY_BLOCKER",
    "ORCHESTRATOR_BLOCKER",
    "ALLOCATOR_BLOCKER",
    "POSITION_LIMIT_BLOCKER",
    "LIVE_DRY_RUN_PACKET_BLOCKER",
    "SIGNED_READ_OPERATOR_BLOCKER",
)

ALLOW_RISK_VALUES = {"PASS", "ALLOW", "ALLOWED", "APPROVE", "APPROVED"}
ALLOW_ORCHESTRATOR_VALUES = {"PASS", "ALLOW", "ALLOWED", "APPROVE", "APPROVED"}
ALLOW_ALLOCATOR_VALUES = {"PASS", "ALLOW", "ALLOWED", "APPROVE", "APPROVED", "ALLOW_WITH_SIZE"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "pass", "allow", "allowed"}


def _read_json(client: Any, key: str) -> Any:
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    url = redis_url or os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def _scan_prediction_keys(client: Any, *, timeframes: tuple[str, ...], max_keys: int) -> list[str]:
    if client is None or max_keys <= 0:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for timeframe in timeframes:
        pattern = f"v2:prediction:*:{timeframe}"
        try:
            iterator = client.scan_iter(match=pattern, count=500)
        except TypeError:
            iterator = client.scan_iter(pattern)
        except Exception:
            continue
        try:
            for key in iterator:
                text = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
                if text in seen:
                    continue
                seen.add(text)
                keys.append(text)
                if len(keys) >= max_keys:
                    return keys
        except Exception:
            continue
    return keys


def _candidate_hash_basis(row: Mapping[str, Any], prediction: Mapping[str, Any] | None) -> str:
    basis = {
        "symbol": _first_present(row.get("symbol"), prediction and prediction.get("symbol")),
        "timeframe": _first_present(row.get("timeframe"), prediction and prediction.get("timeframe")),
        "prediction_id": _first_present(row.get("prediction_id"), prediction and prediction.get("prediction_id")),
        "signal_id": _first_present(row.get("signal_id"), prediction and prediction.get("signal_id")),
        "decision_time": _first_present(
            row.get("preemptive_decision_time"),
            row.get("decision_time"),
            prediction and prediction.get("decision_time"),
            prediction and prediction.get("generated_at"),
        ),
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
    return f"cand_{digest}"


def _feature_values(prediction: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str], list[str]]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    features = _as_dict(_first_present(entry_snapshot.get("features"), prediction.get("features")))
    feature_names = [str(item) for item in _as_list(prediction.get("feature_names"))]
    source_labels = [str(item) for item in _as_list(prediction.get("source_labels"))]
    return features, feature_names, source_labels


def _has_named_feature(
    *,
    features: Mapping[str, Any],
    feature_names: list[str],
    source_labels: list[str],
    needles: tuple[str, ...],
) -> bool:
    names = set(str(name).lower() for name in features)
    names.update(str(name).lower() for name in feature_names)
    labels = " ".join(source_labels).lower()
    for needle in needles:
        lower = needle.lower()
        if lower in labels:
            return True
        if any(lower in name for name in names):
            return True
    return False


def _provider_presence(prediction: Mapping[str, Any] | None) -> dict[str, Any]:
    features, feature_names, source_labels = _feature_values(prediction)
    coinank = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("coinank", "liquidation", "long_short", "open_interest"),
    )
    coinglass = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("coinglass", "funding", "open_interest", "long_short", "liquidation"),
    )
    moralis = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("moralis", "wallet", "smart_money", "onchain", "token_transfer"),
    )
    ta = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("ta_", "rsi", "macd", "ema", "atr", "bollinger"),
    )
    micro = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("orderbook", "depth", "spread", "microstructure", "tape", "bid_ask"),
    )
    advanced = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("fvg", "liquidity_zone", "vwap", "structure", "sweep", "order_block"),
    )
    fvg_liquidity = _has_named_feature(
        features=features,
        feature_names=feature_names,
        source_labels=source_labels,
        needles=("fvg", "liquidity_zone", "nearest_liquidity", "liquidity_sweep"),
    )
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot")) if isinstance(prediction, Mapping) else {}
    missing_names = [
        str(item)
        for item in _as_list(
            _first_present(
                entry_snapshot.get("missing_feature_flags"),
                entry_snapshot.get("missing_feature_names"),
                prediction and prediction.get("tensor_unreconstructed_feature_names"),
                prediction and prediction.get("missing_feature_names"),
            )
        )
    ]
    return {
        "CoinAnk_features_present": coinank,
        "CoinGlass_features_present": coinglass,
        "Moralis_features_present": moralis,
        "TA_features_present": ta,
        "microstructure_features_present": micro,
        "advanced_indicator_features_present": advanced,
        "FVG_liquidity_zone_features_present": fvg_liquidity,
        "provider_missing_masks": {
            "required_missing": [
                name
                for name, present in (
                    ("CoinAnk", coinank),
                    ("CoinGlass", coinglass),
                    ("TA", ta),
                    ("microstructure", micro),
                    ("advanced_indicator", advanced),
                )
                if not present
            ],
            "optional_missing": [] if moralis else ["Moralis"],
            "raw_missing_feature_names": missing_names,
        },
    }


def _lineage_value(row: Mapping[str, Any], prediction: Mapping[str, Any] | None, field: str) -> Any:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    source_hashes = _as_dict(prediction.get("source_hashes"))
    return _first_present(
        row.get(field),
        prediction.get(field),
        source_hashes.get(field),
        entry_snapshot.get(field),
    )


def _candidate_field(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    *fields: str,
) -> tuple[str | None, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    entry_snapshot = _as_dict(prediction.get("entry_feature_snapshot"))
    features = _as_dict(_first_present(entry_snapshot.get("features"), prediction.get("features")))
    for field in fields:
        value = _first_present(row.get(field), prediction.get(field), entry_snapshot.get(field), features.get(field))
        if value is not None:
            return field, value
    return None, None


def _candidate_value(row: Mapping[str, Any], prediction: Mapping[str, Any] | None, *fields: str) -> Any:
    return _candidate_field(row, prediction, *fields)[1]


def _risk_status(row: Mapping[str, Any]) -> str:
    value = _first_present(
        row.get("risk_decision"),
        row.get("risk_result"),
        row.get("risk_action"),
        _as_dict(row.get("risk")).get("decision"),
    )
    if value is None:
        return "MISSING"
    text = str(value).strip().upper()
    if text in ALLOW_RISK_VALUES or text == "PASS":
        return "PASS"
    if text in {"DENY", "DENIED", "BLOCK", "BLOCKED", "FAIL", "FAILED"}:
        return "BLOCKED"
    return text


def _orchestrator_status(row: Mapping[str, Any]) -> str:
    value = _first_present(
        row.get("orchestrator_decision"),
        row.get("orchestrator_result"),
        row.get("orchestrator_action"),
        _as_dict(row.get("orchestrator")).get("decision"),
    )
    if value is None:
        return "MISSING"
    text = str(value).strip().upper()
    if text in ALLOW_ORCHESTRATOR_VALUES:
        return "PASS"
    if text in {"HOLD", "HELD", "DENY", "BLOCK", "BLOCKED", "FAIL", "FAILED"}:
        return "BLOCKED"
    return text


def _allocator_status(row: Mapping[str, Any]) -> str:
    allocation = _as_dict(row.get("allocation"))
    value = _first_present(row.get("allocator_decision"), row.get("allocation_decision"), allocation.get("allocator_decision"), allocation.get("decision"))
    if value is None:
        return "MISSING"
    text = str(value).strip().upper()
    if text in ALLOW_ALLOCATOR_VALUES:
        return "PASS"
    if text.startswith("BLOCK"):
        return text
    return text


def _side(row: Mapping[str, Any], prediction: Mapping[str, Any] | None) -> str | None:
    value = _first_present(row.get("side"), row.get("action"), prediction and prediction.get("selected_action"), prediction and prediction.get("ppo_action"))
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "open_long"}:
        return "long"
    if text in {"short", "sell", "open_short"}:
        return "short"
    return None


def _is_probation(row: Mapping[str, Any]) -> bool:
    action = str(row.get("preemptive_action") or "").upper()
    return (
        action == "ALLOW_PROBATION_PAPER"
        or row.get("allow_positive_edge_probation_paper") is True
        or row.get("counts_as_probation") is True
        or "PROBATION" in str(row.get("source_tier") or "").upper()
    )


def _is_reconstructed(row: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(_first_present(row.get("source_tier"), row.get("candidate_id"), row.get("paper_session_id"), ""))
        .upper()
        .split()
    )
    return (
        row.get("counts_as_reconstructed") is True
        or row.get("reconstructed") is True
        or row.get("preemptive_decision_backfilled") is True
        or "RECONSTRUCT" in text
        or "LEGACY" in text
    )


def _no_side_reason(
    row: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    *,
    expected_long_net: float | None,
    expected_short_net: float | None,
    feature_vector_hash: Any,
) -> str | None:
    if _side(row, prediction) is not None:
        return None
    raw_action = _first_present(
        row.get("side"),
        row.get("action"),
        row.get("selected_action"),
        prediction and prediction.get("selected_action"),
        prediction and prediction.get("ppo_action"),
        prediction and prediction.get("side"),
    )
    text = str(raw_action or "").strip().lower()
    if not feature_vector_hash:
        return "FEATURE_SNAPSHOT_MISSING"
    if expected_long_net is not None and expected_short_net is not None and expected_long_net <= 0.0 and expected_short_net <= 0.0:
        return "BOTH_LONG_AND_SHORT_NET_PNL_NON_POSITIVE"
    if text in {"hold", "no_trade", "none", "flat", "0"}:
        return "MODEL_HOLD_OR_NO_TRADE_ACTION"
    if raw_action in (None, ""):
        return "SIDE_NOT_EMITTED_BY_PUBLISHER"
    return f"UNSUPPORTED_ACTION_{str(raw_action).upper()}"


def _blocker_class(reason: str) -> str:
    upper = reason.upper()
    if any(token in upper for token in ("STALE", "FRESHNESS", "AVAILABLE_AT_AFTER_DECISION", "CUTOFF_AFTER_DECISION")):
        return "DATA_FRESHNESS_BLOCKER"
    if any(token in upper for token in ("FEATURE", "HASH_MISSING", "TA_", "LINEAGE_FEATURE", "ADVANCED_INDICATOR_DECISION_MISSING")):
        return "FEATURE_COVERAGE_BLOCKER"
    if any(token in upper for token in ("MICROSTRUCTURE", "ORDERBOOK", "TAPE", "PUBLIC_BOOK", "TRUST_LOW")):
        return "MICROSTRUCTURE_TRUST_BLOCKER"
    if any(token in upper for token in ("PROVIDER", "COINANK", "COINGLASS", "MORALIS")):
        return "PROVIDER_MISSING_BLOCKER"
    if any(token in upper for token in ("CONFIDENCE", "TRAINER", "SIDE_MISSING", "NO_TRADE_MODE")):
        return "TRAINER_CONFIDENCE_BLOCKER"
    if any(token in upper for token in ("EXPECTED", "EDGE", "PNL", "BPS_ONLY", "COST")):
        return "EXPECTED_NET_EDGE_BLOCKER"
    if any(token in upper for token in ("LOSS_PROBABILITY", "LOSS_RATE", "HIGH_CONFIDENCE_LOSS", "ATR_STOP")):
        return "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER"
    if any(token in upper for token in ("RISK_", "MAX_LOSS", "LIQUIDATION_BUFFER", "GUARDIAN")):
        return "RISK_GATEWAY_BLOCKER"
    if "ORCHESTRATOR" in upper:
        return "ORCHESTRATOR_BLOCKER"
    if "ALLOCATOR" in upper:
        return "ALLOCATOR_BLOCKER"
    if any(token in upper for token in ("POSITION", "EXPOSURE_CAP", "MIN_NOTIONAL", "STEP_SIZE", "TICK_SIZE")):
        return "POSITION_LIMIT_BLOCKER"
    if any(token in upper for token in ("LIVE_DRY_RUN", "PACKET", "SYMBOL_FILTER")):
        return "LIVE_DRY_RUN_PACKET_BLOCKER"
    if "SIGNED" in upper:
        return "SIGNED_READ_OPERATOR_BLOCKER"
    return "EXPECTED_NET_EDGE_BLOCKER"


def _normalize_candidate(
    row: Mapping[str, Any],
    *,
    prediction: Mapping[str, Any] | None,
    generated_utc: str,
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    allocator_packet = build_allocator_simulation(row, prediction=prediction, generated_utc=generated_utc)
    row = {
        **dict(row),
        "allocation": allocator_packet,
        "allocator_simulation": allocator_packet,
        "allocator_decision_id": allocator_packet.get("allocator_decision_id"),
        "allocator_decision": allocator_packet.get("allocator_decision"),
        "allocator_block_reasons": allocator_packet.get("allocator_block_reasons") or allocator_packet.get("block_reasons") or [],
        "recommended_leverage": allocator_packet.get("recommended_leverage"),
        "recommended_leverage_source": allocator_packet.get("recommended_leverage_source"),
        "recommended_margin_mode": allocator_packet.get("recommended_margin_mode"),
        "recommended_margin_mode_source": allocator_packet.get("recommended_margin_mode_source"),
        "gross_notional_usd": allocator_packet.get("gross_notional_usd"),
        "target_notional_usd": allocator_packet.get("target_notional_usd"),
        "allocated_margin_usd": allocator_packet.get("allocated_margin_usd"),
        "max_loss_usd": allocator_packet.get("max_loss_usd"),
        "expected_max_loss_usd": allocator_packet.get("expected_max_loss_usd"),
        "expected_net_pnl_usd": allocator_packet.get("expected_net_pnl_usd"),
        "expected_fee_usd": allocator_packet.get("expected_fee_usd"),
        "expected_fees_usd": allocator_packet.get("expected_fees_usd"),
        "expected_slippage_usd": allocator_packet.get("expected_slippage_usd"),
        "expected_funding_usd": allocator_packet.get("expected_funding_usd"),
        "liquidation_buffer_usd": allocator_packet.get("liquidation_buffer_usd"),
        "expected_liquidation_buffer_usd": allocator_packet.get("expected_liquidation_buffer_usd"),
        "liquidation_buffer_pct": allocator_packet.get("liquidation_buffer_pct"),
        "maintenance_margin_usd": allocator_packet.get("maintenance_margin_usd"),
        "estimated_liquidation_price": allocator_packet.get("estimated_liquidation_price"),
        "distance_to_liquidation_usd": allocator_packet.get("distance_to_liquidation_usd"),
        "hedge_required": allocator_packet.get("hedge_required"),
        "hedge_plan": allocator_packet.get("hedge_plan"),
        "signed_read_status": allocator_packet.get("signed_read_status"),
        "available_margin_usd": allocator_packet.get("available_margin_usd"),
    }
    provider = _provider_presence(prediction)
    risk_decision = _risk_status(row)
    orchestrator_decision = _orchestrator_status(row)
    allocator_decision = _allocator_status(row)
    price_field, price_value = _candidate_field(
        row,
        prediction,
        "selected_execution_price",
        "entry_price",
        "current_price",
        "mark_price",
        "last_trade_price",
        "last_price",
        "price",
        "price_reference",
        "close",
        "close_price",
    )
    current_price = _float(price_value)
    if current_price is not None and current_price <= 0.0:
        current_price = None
    mark_price = _float(_candidate_value(row, prediction, "mark_price"))
    index_price = _float(_candidate_value(row, prediction, "index_price"))
    last_trade_price = _float(_candidate_value(row, prediction, "last_trade_price", "last_price", "price", "close", "close_price"))
    best_bid = _float(_candidate_value(row, prediction, "best_bid", "bid", "bid_price"))
    best_ask = _float(_candidate_value(row, prediction, "best_ask", "ask", "ask_price"))
    price_source = _first_present(
        row.get("price_source"),
        row.get("current_price_source"),
        prediction.get("price_source"),
        prediction.get("market_data_source"),
        "candidate_payload" if current_price is not None else None,
    )
    price_available_at = _first_present(
        row.get("price_available_at"),
        row.get("market_price_available_at"),
        prediction.get("price_available_at"),
        prediction.get("market_data_available_at"),
        row.get("available_at"),
        prediction.get("available_at"),
    )
    expected_net = _float(
        _first_present(
            row.get("expected_net_pnl_usd"),
            row.get("pre_trade_expected_net_pnl_usd"),
            prediction.get("expected_net_pnl_usd"),
        )
    )
    expected_fees = _float(
        _first_present(
            row.get("expected_fees_usd"),
            row.get("expected_fee_usd"),
            row.get("pre_trade_expected_fees_usd"),
            prediction.get("expected_fees_usd"),
        )
    )
    expected_slippage = _float(
        _first_present(row.get("expected_slippage_usd"), row.get("pre_trade_slippage_risk_usd"), prediction.get("expected_slippage_usd"))
    )
    expected_funding = _float(_first_present(row.get("expected_funding_usd"), row.get("pre_trade_funding_risk_usd"), prediction.get("expected_funding_usd")))
    expected_max_loss = _float(
        _first_present(row.get("expected_max_loss_usd"), row.get("pre_trade_max_loss_usd"), row.get("max_loss_usd"), row.get("max_loss_if_stop_hit"))
    )
    latency_reserve = _float(_candidate_value(row, prediction, "latency_reserve_usd", "pre_trade_latency_reserve_usd"))
    liquidation_risk_reserve = _float(
        _candidate_value(row, prediction, "liquidation_risk_reserve_usd", "pre_trade_liquidation_risk_usd")
    )
    exit_failure_reserve = _float(_candidate_value(row, prediction, "exit_failure_reserve_usd", "pre_trade_exit_failure_reserve_usd"))
    expected_cost = sum(
        component or 0.0
        for component in (
            expected_fees,
            expected_slippage,
            expected_funding,
            latency_reserve,
            liquidation_risk_reserve,
            exit_failure_reserve,
        )
    )
    expected_gross = _float(
        _first_present(
            row.get("expected_gross_pnl_usd"),
            row.get("pre_trade_expected_gross_pnl_usd"),
            prediction.get("expected_gross_pnl_usd"),
            prediction.get("pre_trade_expected_gross_pnl_usd"),
            allocator_packet.get("expected_gross_pnl_usd"),
        )
    )
    if expected_gross is None and expected_net is not None:
        expected_gross = expected_net + expected_cost
    expected_move_after_cost_bps = _float(
        _candidate_value(
            row,
            prediction,
            "expected_move_after_cost_bps",
            "expected_edge_after_cost_bps",
            "pre_trade_expected_edge_after_cost_bps",
            "edge_after_cost_bps",
        )
    )
    expected_move = _float(
        _candidate_value(
            row,
            prediction,
            "expected_move_bps",
            "native_expected_move_bps",
            "expected_gross_move_bps",
        )
    )
    if expected_move is None:
        expected_move = expected_move_after_cost_bps
    notional_for_move = _float(_first_present(row.get("target_notional_usd"), row.get("gross_notional_usd"), prediction.get("notional_usd")))
    if expected_move is None and expected_gross is not None and notional_for_move not in (None, 0.0):
        expected_move = expected_gross / abs(notional_for_move) * 10000.0
    confidence_raw = _float(_first_present(row.get("confidence_raw"), prediction.get("confidence_raw"), row.get("confidence"), prediction.get("confidence")))
    confidence_calibrated = _float(
        _first_present(
            row.get("confidence_calibrated"),
            row.get("calibrated_confidence"),
            prediction.get("confidence_calibrated"),
            prediction.get("calibrated_confidence"),
        )
    )
    liquidation_buffer_usd = _float(
        _first_present(row.get("expected_liquidation_buffer_usd"), row.get("liquidation_buffer_usd"), prediction.get("liquidation_buffer_usd"))
    )
    if liquidation_buffer_usd is None:
        notional = _float(_first_present(row.get("target_notional_usd"), row.get("gross_notional_usd"), prediction.get("notional_usd")))
        buffer_bps = _float(_first_present(row.get("liquidation_buffer_bps"), row.get("liquidation_buffer")))
        if notional is not None and buffer_bps is not None:
            liquidation_buffer_usd = round(abs(notional) * buffer_bps / 10000.0, 8)
    feature_vector_hash = _lineage_value(row, prediction, "feature_vector_hash")
    feature_cutoff = _first_present(
        _lineage_value(row, prediction, "feature_cutoff"),
        prediction.get("ppo_feature_cutoff"),
        prediction.get("masa_feature_cutoff"),
    )
    feature_snapshot_id = _first_present(
        _lineage_value(row, prediction, "feature_snapshot_id"),
        prediction.get("entry_feature_snapshot_id"),
        _as_dict(prediction.get("entry_feature_snapshot")).get("feature_snapshot_id"),
    )
    available_at = _lineage_value(row, prediction, "available_at")
    decision_time = _first_present(row.get("decision_time"), row.get("preemptive_decision_time"), prediction.get("decision_time"), prediction.get("generated_at"), generated_utc)
    preemptive_action = str(row.get("preemptive_action") or "")
    preemptive_decision = str(row.get("preemptive_decision") or "")
    action = _first_present(row.get("action"), row.get("selected_action"), prediction.get("selected_action"), prediction.get("ppo_action"))
    side = _side(row, prediction)
    expected_long_net = _float(_candidate_value(row, prediction, "expected_long_net_pnl_usd", "long_expected_net_pnl_usd"))
    expected_short_net = _float(_candidate_value(row, prediction, "expected_short_net_pnl_usd", "short_expected_net_pnl_usd"))
    expected_long_net_edge_bps = _float(_candidate_value(row, prediction, "expected_long_net_edge_bps", "long_expected_net_edge_bps"))
    expected_short_net_edge_bps = _float(_candidate_value(row, prediction, "expected_short_net_edge_bps", "short_expected_net_edge_bps"))
    if expected_long_net_edge_bps is None and expected_move is not None:
        expected_long_net_edge_bps = expected_move - (
            _float(_candidate_value(row, prediction, "actual_observed_spread_entry_bps", "spread_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_slippage_bps", "slippage_bps")) or 0.0) - (
            _float(_candidate_value(row, prediction, "fee_bps", "taker_fee_bps", "expected_fee_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_funding_bps", "funding_bps")) or 0.0)
    if expected_short_net_edge_bps is None and expected_move is not None:
        expected_short_net_edge_bps = -expected_move - (
            _float(_candidate_value(row, prediction, "actual_observed_spread_entry_bps", "spread_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_slippage_bps", "slippage_bps")) or 0.0) - (
            _float(_candidate_value(row, prediction, "fee_bps", "taker_fee_bps", "expected_fee_bps")) or 0.0
        ) - (_float(_candidate_value(row, prediction, "expected_funding_bps", "funding_bps")) or 0.0)
    per_side_notional = notional_for_move
    per_side_notional_basis = "candidate_notional_usd"
    if per_side_notional is None or per_side_notional <= 0.0:
        per_side_notional = 1.0
        per_side_notional_basis = "diagnostic_unit_notional_usd_no_allocator_size"
    if expected_long_net is None and expected_long_net_edge_bps is not None:
        expected_long_net = round(per_side_notional * expected_long_net_edge_bps / 10000.0, 8)
    if expected_short_net is None and expected_short_net_edge_bps is not None:
        expected_short_net = round(per_side_notional * expected_short_net_edge_bps / 10000.0, 8)
    best_side = None
    if expected_long_net is not None or expected_short_net is not None:
        long_value = expected_long_net if expected_long_net is not None else float("-inf")
        short_value = expected_short_net if expected_short_net is not None else float("-inf")
        best_side = "long" if long_value >= short_value else "short"
    no_side_reason = _no_side_reason(
        row,
        prediction,
        expected_long_net=expected_long_net,
        expected_short_net=expected_short_net,
        feature_vector_hash=feature_vector_hash,
    )
    best_side_rejected_reason = None
    if side is None:
        best_side_rejected_reason = _candidate_value(row, prediction, "why_best_side_rejected", "best_side_rejected_reason")
        if best_side_rejected_reason is None and expected_long_net is not None and expected_short_net is not None:
            if expected_long_net <= 0.0 and expected_short_net <= 0.0:
                best_side_rejected_reason = (
                    "both_long_and_short_diagnostic_net_pnl_usd_non_positive"
                    f"_long_{expected_long_net:.8f}_short_{expected_short_net:.8f}"
                )
            elif best_side:
                best_value = expected_long_net if best_side == "long" else expected_short_net
                best_side_rejected_reason = f"selected_hold_best_side_{best_side}_diagnostic_net_pnl_usd_{best_value:.8f}"
        if best_side_rejected_reason is None:
            best_side_rejected_reason = no_side_reason
    raw_reasons = [
        str(reason)
        for reason in _as_list(
            _first_present(row.get("block_reasons"), row.get("preemptive_block_reasons"), row.get("preemptive_decision_reasons"))
        )
    ]
    raw_reasons.extend(str(reason) for reason in _as_list(row.get("allocator_block_reasons")))
    block_reasons = list(dict.fromkeys(reason for reason in raw_reasons if reason and reason.upper() != "UNKNOWN"))

    if not row.get("preemptive_decision_id"):
        block_reasons.append("LINEAGE_PREEMPTIVE_DECISION_ID_MISSING")
    if not feature_vector_hash:
        block_reasons.append("LINEAGE_FEATURE_VECTOR_HASH_MISSING")
    if expected_net is None:
        if _float(row.get("expected_edge_after_cost_bps")) is not None:
            block_reasons.append("ECONOMICS_BPS_ONLY")
        block_reasons.append("ECONOMICS_EXPECTED_NET_PNL_USD_MISSING")
    elif expected_net <= 0:
        block_reasons.append("EXPECTED_NET_EDGE_NON_POSITIVE")
    if expected_gross is None:
        block_reasons.append("ECONOMICS_EXPECTED_GROSS_PNL_USD_MISSING")
    if current_price is None:
        block_reasons.append("CURRENT_PRICE_MISSING")
    loss_probability = _float(row.get("pre_trade_loss_probability"))
    if loss_probability is None:
        block_reasons.append("PRE_TRADE_LOSS_PROBABILITY_MISSING")
    elif loss_probability >= 0.80:
        block_reasons.append("PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND")
    if expected_max_loss is None:
        block_reasons.append("RISK_MAX_LOSS_USD_MISSING")
    if liquidation_buffer_usd is None:
        block_reasons.append("RISK_LIQUIDATION_BUFFER_USD_MISSING")
    side = _side(row, prediction)
    if side is None:
        block_reasons.append("TRAINER_SIDE_MISSING_OR_HOLD")
    if risk_decision != "PASS":
        block_reasons.append("RISK_GATEWAY_NOT_PASS")
    if orchestrator_decision != "PASS":
        block_reasons.append("ORCHESTRATOR_NOT_PASS")
    if allocator_decision != "PASS":
        block_reasons.append("ALLOCATOR_NOT_PASS")
    if str(row.get("microstructure_trust_state") or "").upper() in {"UNSAFE", "FAIL_CLOSED"}:
        block_reasons.append("MICROSTRUCTURE_TRUST_FAIL_CLOSED")
    if not provider["TA_features_present"]:
        block_reasons.append("FEATURE_COVERAGE_TA_MISSING")
    if not provider["microstructure_features_present"]:
        block_reasons.append("FEATURE_COVERAGE_MICROSTRUCTURE_MISSING")
    if not provider["advanced_indicator_features_present"]:
        block_reasons.append("FEATURE_COVERAGE_ADVANCED_INDICATOR_MISSING")
    if not provider["CoinAnk_features_present"]:
        block_reasons.append("PROVIDER_COINANK_REQUIRED_FEATURES_MISSING")
    if _is_probation(row):
        block_reasons.append("PROBATION_ROW_NOT_FINAL_A_PLUS")
    if _is_reconstructed(row):
        block_reasons.append("EVIDENCE_RECONSTRUCTED_OR_LEGACY_ROW_NOT_A_PLUS")
    if preemptive_action != "ALLOW_A_PLUS_CANDIDATE" or preemptive_decision != "ALLOW":
        block_reasons.append("PREEMPTIVE_ACTION_NOT_A_PLUS_ALLOW")

    unique_reasons = list(dict.fromkeys(block_reasons))
    reason_classes = sorted({_blocker_class(reason) for reason in unique_reasons})
    a_plus = not unique_reasons and preemptive_action == "ALLOW_A_PLUS_CANDIDATE" and preemptive_decision == "ALLOW"
    live_ready = a_plus and row.get("live_dry_run_packet_complete") is True
    if a_plus and not live_ready:
        unique_reasons.append("LIVE_DRY_RUN_PACKET_INCOMPLETE")
        reason_classes = sorted({_blocker_class(reason) for reason in unique_reasons})
        a_plus = False

    return {
        "candidate_id": _first_present(row.get("candidate_id"), prediction.get("candidate_id"), prediction.get("decision_id"), _candidate_hash_basis(row, prediction)),
        "symbol": _first_present(row.get("symbol"), prediction.get("symbol")),
        "timeframe": _first_present(row.get("timeframe"), prediction.get("timeframe")),
        "side": side,
        "no_side_reason": no_side_reason,
        "action": action,
        "best_side": best_side,
        "best_side_rejected_reason": best_side_rejected_reason,
        "strategy_id": _first_present(row.get("strategy_id"), prediction.get("strategy_id"), _as_dict(prediction.get("strategy_router")).get("selected_mode")),
        "prediction_id": _first_present(row.get("prediction_id"), prediction.get("prediction_id")),
        "signal_id": _first_present(row.get("signal_id"), prediction.get("signal_id")),
        "preemptive_decision_id": row.get("preemptive_decision_id"),
        "trainer_prediction_id": prediction.get("prediction_id") or row.get("prediction_id"),
        "feature_snapshot_id": feature_snapshot_id,
        "feature_vector_hash": feature_vector_hash,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "decision_time": decision_time,
        "confidence": _float(_first_present(row.get("confidence"), row.get("calibrated_confidence"), prediction.get("confidence_calibrated"), prediction.get("confidence_raw"))),
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_calibrated,
        "current_price": current_price,
        "price_missing_reason": None if current_price is not None else "NO_MARK_INDEX_LAST_BID_ASK_OR_CLOSE_PRICE_AVAILABLE",
        "mark_price": mark_price,
        "index_price": index_price,
        "last_trade_price": last_trade_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "selected_execution_price_basis": price_field,
        "price_available_at": price_available_at,
        "price_source": price_source,
        "expected_move": expected_move,
        "expected_move_bps": expected_move,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "expected_gross_pnl_usd": expected_gross,
        "expected_cost_usd": round(expected_cost, 8),
        "fees_usd": expected_fees or 0.0,
        "slippage_usd": expected_slippage or 0.0,
        "funding_usd": expected_funding or 0.0,
        "latency_reserve_usd": latency_reserve or 0.0,
        "liquidation_risk_reserve_usd": liquidation_risk_reserve or 0.0,
        "exit_failure_reserve_usd": exit_failure_reserve or 0.0,
        "expected_net_pnl_usd": expected_net,
        "expected_fees_usd": expected_fees,
        "expected_slippage_usd": expected_slippage,
        "expected_funding_usd": expected_funding,
        "expected_max_loss_usd": expected_max_loss,
        "expected_long_net_pnl_usd": expected_long_net,
        "expected_short_net_pnl_usd": expected_short_net,
        "expected_long_net_edge_bps": expected_long_net_edge_bps,
        "expected_short_net_edge_bps": expected_short_net_edge_bps,
        "per_side_usd_notional": per_side_notional,
        "per_side_usd_notional_basis": per_side_notional_basis,
        "expected_liquidation_buffer_usd": liquidation_buffer_usd,
        "pre_trade_loss_probability": loss_probability,
        "preemptive_action": preemptive_action or None,
        "risk_decision": risk_decision,
        "orchestrator_decision": orchestrator_decision,
        "allocator_decision": allocator_decision,
        "allocator_decision_id": row.get("allocator_decision_id"),
        "allocator_block_reasons": _as_list(row.get("allocator_block_reasons")),
        "allocator_simulation_status": row.get("allocator_simulation_status") or allocator_packet.get("allocator_simulation_status"),
        "allocator_packet": allocator_packet,
        "recommended_leverage": row.get("recommended_leverage"),
        "recommended_leverage_source": row.get("recommended_leverage_source"),
        "recommended_margin_mode": row.get("recommended_margin_mode"),
        "recommended_margin_mode_source": row.get("recommended_margin_mode_source"),
        "gross_notional_usd": row.get("gross_notional_usd"),
        "target_notional_usd": row.get("target_notional_usd"),
        "allocated_margin_usd": row.get("allocated_margin_usd"),
        "max_loss_usd": row.get("max_loss_usd"),
        "liquidation_buffer_usd": row.get("liquidation_buffer_usd"),
        "liquidation_buffer_pct": row.get("liquidation_buffer_pct"),
        "maintenance_margin_usd": row.get("maintenance_margin_usd"),
        "estimated_liquidation_price": row.get("estimated_liquidation_price"),
        "distance_to_liquidation_usd": row.get("distance_to_liquidation_usd"),
        "hedge_required": row.get("hedge_required"),
        "hedge_plan": row.get("hedge_plan"),
        "signed_read_status": row.get("signed_read_status"),
        "available_margin_usd": row.get("available_margin_usd"),
        **provider,
        "block_reasons": unique_reasons,
        "blocker_classes": reason_classes,
        "A_plus_candidate": a_plus,
        "live_ready_candidate": live_ready,
        "counts_as_probation": _is_probation(row),
        "counts_as_reconstructed": _is_reconstructed(row),
        "counts_as_A_plus": a_plus,
        "counts_as_live_ready": live_ready,
        "counts_as_final_a_plus": a_plus,
        "source_runtime_key": _first_present(row.get("source_runtime_key"), prediction.get("redis_key")),
        "generated_utc": generated_utc,
    }


SESSION_MAX_PREDICTION_AGE_SECONDS = 6 * 3600


def _prediction_age_seconds(prediction: Mapping[str, Any]) -> float | None:
    stamp = _first_present(
        prediction.get("generated_at"),
        prediction.get("decision_time"),
        prediction.get("generated_utc"),
    )
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _prediction_candidate(
    prediction: Mapping[str, Any],
    guardian: Mapping[str, Any] | None,
    altdata_confluence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = {
        **_as_dict(prediction),
        "action": _first_present(prediction.get("selected_action"), prediction.get("ppo_action")),
        "side": _first_present(prediction.get("selected_action"), prediction.get("ppo_action")),
        "gross_notional_usd": _first_present(prediction.get("gross_notional_usd"), prediction.get("notional_usd"), 0.0),
        "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
        "advanced_indicator_context": _as_dict(prediction.get("advanced_indicator_context")),
    }
    decision = evaluate_candidate(
        candidate,
        continuous_edge_guardian_gate=guardian or {},
        altdata_confluence=dict(altdata_confluence) if altdata_confluence else None,
    )
    # Predictions older than the session window are historical residue, not
    # current-session candidates; they must never inflate A+/candidate counts.
    age_seconds = _prediction_age_seconds(prediction)
    if age_seconds is None or age_seconds > SESSION_MAX_PREDICTION_AGE_SECONDS:
        decision["stale_prediction"] = True
        decision["prediction_age_seconds"] = age_seconds
        reasons = list(decision.get("preemptive_decision_reasons") or [])
        if "STALE_PREDICTION_NOT_CURRENT_SESSION" not in reasons:
            reasons.append("STALE_PREDICTION_NOT_CURRENT_SESSION")
        decision["preemptive_decision_reasons"] = reasons
        if decision.get("preemptive_decision") not in ("NO_TRADE",):
            decision["preemptive_decision"] = "NO_TRADE"
    else:
        decision["stale_prediction"] = False
        decision["prediction_age_seconds"] = age_seconds
    return decision


def build_inventory(
    *,
    client: Any,
    output_dir: Path | None = None,
    session: str = "current",
    timeframes: tuple[str, ...] = TARGET_TIMEFRAMES,
    max_prediction_keys: int = 2500,
) -> dict[str, Any]:
    generated = _utc_now()
    matrix = _as_dict(_read_json(client, PREEMPTIVE_MATRIX_KEY))
    status_payload = _as_dict(_read_json(client, PREEMPTIVE_STATUS_KEY))
    live_gate_payload = _as_dict(_read_json(client, LIVE_GATE_KEY))
    guardian = {
        "status": _first_present(status_payload.get("status"), live_gate_payload.get("guardian_state"), "A_GRADE_HALTED_PERFORMANCE"),
        "a_grade_new_entries_allowed": False,
        "new_entries_allowed": False,
    }
    matrix_rows = [_as_dict(row) for row in _as_list(matrix.get("rows"))]
    rows_by_prediction_id: dict[str, dict[str, Any]] = {
        str(row["prediction_id"]): dict(row)
        for row in matrix_rows
        if row.get("prediction_id")
    }
    prediction_keys = _scan_prediction_keys(client, timeframes=timeframes, max_keys=max_prediction_keys)
    predictions: dict[tuple[str, str], dict[str, Any]] = {}
    predictions_by_id: dict[str, dict[str, Any]] = {}
    for key in prediction_keys:
        payload = _as_dict(_read_json(client, key))
        if not payload:
            continue
        symbol = str(payload.get("symbol") or "").upper()
        timeframe = str(payload.get("timeframe") or "").strip()
        if timeframe not in timeframes or not symbol:
            continue
        payload["redis_key"] = key
        predictions[(symbol, timeframe)] = payload
        if payload.get("prediction_id"):
            predictions_by_id[str(payload["prediction_id"])] = payload

    # Allocator simulation runs inside _normalize_candidate via
    # build_allocator_simulation. It resolves price from row/prediction fields
    # only, so inject the live V2 market price (read-only public data already
    # in Redis) per symbol before normalization — a candidate without any
    # market price is still honestly rejected.
    price_cache: dict[str, float | None] = {}

    def _live_market_price(symbol: str) -> float | None:
        if symbol in price_cache:
            return price_cache[symbol]
        price: float | None = None
        prices_payload = _read_json(client, f"v2:market:prices:{symbol}")
        if isinstance(prices_payload, Mapping):
            ticker = prices_payload.get("ticker_24hr")
            price = _float(
                _first_present(
                    prices_payload.get("price"),
                    prices_payload.get("lastPrice"),
                    isinstance(ticker, Mapping) and ticker.get("lastPrice"),
                )
            )
        if price is None or price <= 0:
            ohlcv = _read_json(client, f"v2:market:ohlcv_closed:binance:{symbol}:1m")
            if isinstance(ohlcv, list) and ohlcv and isinstance(ohlcv[-1], Mapping):
                price = _float(_first_present(ohlcv[-1].get("close"), ohlcv[-1].get("close_price")))
        price_cache[symbol] = price if price is not None and price > 0 else None
        return price_cache[symbol]

    def _with_price(row: dict[str, Any]) -> dict[str, Any]:
        if _float(_first_present(row.get("current_price"), row.get("entry_price"), row.get("price"))):
            return row
        symbol = str(row.get("symbol") or "").upper()
        price = _live_market_price(symbol) if symbol else None
        if price is not None:
            row = dict(row)
            row["current_price"] = price
            row["current_price_source"] = "v2_market_redis_read_only"
        return row

    normalized: list[dict[str, Any]] = []
    seen_prediction_ids: set[str] = set()
    for row in matrix_rows:
        prediction = predictions_by_id.get(str(row.get("prediction_id") or ""))
        if prediction is None:
            key = f"v2:prediction:{str(row.get('symbol') or '').upper()}:{row.get('timeframe')}"
            prediction = _as_dict(_read_json(client, key))
            if prediction:
                prediction["redis_key"] = key
        item = _normalize_candidate(_with_price(dict(row)), prediction=prediction, generated_utc=generated)
        normalized.append(item)
        if item.get("prediction_id"):
            seen_prediction_ids.add(str(item["prediction_id"]))

    _confluence_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def _confluence_for(symbol: str, timeframe: str) -> dict[str, Any]:
        cache_key = (symbol, timeframe)
        if cache_key not in _confluence_cache:
            _confluence_cache[cache_key] = _as_dict(
                _read_json(client, f"v2:altdata:confluence:{symbol}:{timeframe}")
            )
        return _confluence_cache[cache_key]

    for prediction in predictions.values():
        prediction_id = str(prediction.get("prediction_id") or "")
        if prediction_id in seen_prediction_ids:
            continue
        decision = rows_by_prediction_id.get(prediction_id) or _prediction_candidate(
            prediction,
            guardian,
            altdata_confluence=_confluence_for(
                str(prediction.get("symbol") or "").upper(),
                str(prediction.get("timeframe") or "1m"),
            ),
        )
        decision["source_runtime_key"] = prediction.get("redis_key")
        normalized.append(
            _normalize_candidate(_with_price(dict(decision)), prediction=prediction, generated_utc=generated)
        )

    normalized.sort(key=lambda item: (str(item.get("timeframe")), str(item.get("symbol")), str(item.get("prediction_id"))))
    reason_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    timeframe_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    for item in normalized:
        timeframe_counts[str(item.get("timeframe") or "missing")] += 1
        symbol_counts[str(item.get("symbol") or "missing")] += 1
        if item.get("A_plus_candidate"):
            continue
        reason_counts.update(str(reason) for reason in item.get("block_reasons") or [])
        class_counts.update(str(name) for name in item.get("blocker_classes") or [])

    a_plus_rows = [row for row in normalized if row.get("A_plus_candidate")]
    live_ready_rows = [row for row in normalized if row.get("live_ready_candidate")]
    allocator_decision_status_counts = Counter(str(row.get("allocator_decision") or "MISSING") for row in normalized)
    risk_decision_status_counts = Counter(str(row.get("risk_decision") or "MISSING") for row in normalized)
    orchestrator_decision_status_counts = Counter(str(row.get("orchestrator_decision") or "MISSING") for row in normalized)
    preemptive_decision_status_counts = Counter(str(row.get("preemptive_action") or "MISSING") for row in normalized)
    allocator_decision_missing_count = allocator_decision_status_counts.get("MISSING", 0)
    allocator_decision_pass_count = allocator_decision_status_counts.get("PASS", 0)
    allocator_decision_reject_count = sum(
        count
        for decision, count in allocator_decision_status_counts.items()
        if decision not in {"MISSING", "PASS"}
    )
    near_rows = sorted(
        [row for row in normalized if not row.get("A_plus_candidate")],
        key=lambda row: (
            len(row.get("blocker_classes") or []),
            -float(row.get("expected_net_pnl_usd") or 0.0),
            float(row.get("pre_trade_loss_probability") or 1.0),
        ),
    )[:50]
    hard_failures = {
        "missing_candidate_id_count": sum(1 for row in normalized if not row.get("candidate_id")),
        "missing_symbol_count": sum(1 for row in normalized if not row.get("symbol")),
        "missing_timeframe_count": sum(1 for row in normalized if not row.get("timeframe")),
        "missing_side_and_no_side_reason_count": sum(1 for row in normalized if not row.get("side") and not row.get("no_side_reason")),
        "missing_current_price_and_price_missing_reason_count": sum(
            1 for row in normalized if row.get("current_price") is None and not row.get("price_missing_reason")
        ),
        "missing_expected_move_count": sum(1 for row in normalized if row.get("expected_move") is None),
        "missing_expected_gross_pnl_usd_count": sum(1 for row in normalized if row.get("expected_gross_pnl_usd") is None),
        "missing_expected_cost_usd_count": sum(1 for row in normalized if row.get("expected_cost_usd") is None),
        "unknown_rejection_reason_count": sum(1 for reason in reason_counts if reason.upper() == "UNKNOWN"),
        "missing_preemptive_decision_id_count": sum(1 for row in normalized if not row.get("preemptive_decision_id")),
        "missing_allocator_decision_id_count": sum(1 for row in normalized if not row.get("allocator_decision_id")),
        "missing_feature_vector_hash_count": sum(1 for row in normalized if not row.get("feature_vector_hash")),
        "missing_feature_cutoff_count": sum(1 for row in normalized if not row.get("feature_cutoff")),
        "missing_decision_time_count": sum(1 for row in normalized if not row.get("decision_time")),
        "missing_expected_net_pnl_usd_count": sum(1 for row in normalized if row.get("expected_net_pnl_usd") is None),
        "allocator_decision_missing_count": allocator_decision_missing_count,
        "expected_liquidation_buffer_usd_missing_count": sum(1 for row in normalized if row.get("expected_liquidation_buffer_usd") is None),
        "expected_max_loss_usd_missing_count": sum(1 for row in normalized if row.get("expected_max_loss_usd") is None),
        "bps_only_economics_count": sum(1 for row in normalized if "ECONOMICS_BPS_ONLY" in set(row.get("block_reasons") or [])),
        "probation_final_a_plus_count": sum(1 for row in normalized if row.get("counts_as_probation") and row.get("counts_as_A_plus")),
        "reconstructed_final_a_plus_count": sum(1 for row in normalized if row.get("counts_as_reconstructed") and row.get("counts_as_A_plus")),
    }
    rejection_matrix = {
        "schema_version": "v2_a_plus_candidate_rejection_matrix_v1",
        "generated_utc": generated,
        "session": session,
        "total_candidate_count": len(normalized),
        "a_plus_candidate_count": len(a_plus_rows),
        "live_ready_candidate_count": len(live_ready_rows),
        "blocker_class_counts": dict(class_counts.most_common()),
        "rejection_reason_counts": dict(reason_counts.most_common()),
        "top_blocker_class": class_counts.most_common(1)[0][0] if class_counts else None,
        "allowed_blocker_classes": list(ALLOWED_BLOCKER_CLASSES),
        "unknown_rejection_reason_count": hard_failures["unknown_rejection_reason_count"],
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated,
        "session": session,
        "timeframes": list(timeframes),
        "matrix_generated_utc": matrix.get("generated_utc"),
        "matrix_candidate_count": matrix.get("candidate_count"),
        "matrix_materialized_row_count": len(matrix_rows),
        "prediction_key_count": len(prediction_keys),
        "total_candidate_count": len(normalized),
        "a_plus_candidate_count": len(a_plus_rows),
        "live_ready_candidate_count": len(live_ready_rows),
        "counts_by_timeframe": dict(timeframe_counts),
        "top_symbols": [symbol for symbol, _ in symbol_counts.most_common(20)],
        "allocator_decision_missing_count": allocator_decision_missing_count,
        "allocator_decision_pass_count": allocator_decision_pass_count,
        "allocator_decision_reject_count": allocator_decision_reject_count,
        "allocator_decision_status_counts": dict(allocator_decision_status_counts),
        "risk_decision_status_counts": dict(risk_decision_status_counts),
        "orchestrator_decision_status_counts": dict(orchestrator_decision_status_counts),
        "preemptive_decision_status_counts": dict(preemptive_decision_status_counts),
        "expected_liquidation_buffer_usd_missing_count": hard_failures["expected_liquidation_buffer_usd_missing_count"],
        "expected_max_loss_usd_missing_count": hard_failures["expected_max_loss_usd_missing_count"],
        "expected_net_pnl_usd_missing_count": hard_failures["missing_expected_net_pnl_usd_count"],
        "preemptive_status": status_payload,
        "live_gate": _first_present(live_gate_payload.get("live_gate"), "blocked_human_only"),
        "hard_failures": hard_failures,
        "hard_fail": any(int(value or 0) > 0 for value in hard_failures.values()),
        "primary_blocker": rejection_matrix["top_blocker_class"],
        "final_state": "OPERATOR_REVIEW_READY_FIRST_LIVE_CANARY" if live_ready_rows else "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON",
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(output_dir / "candidate_inventory.jsonl", normalized)
        _write_json(output_dir / "candidate_inventory_summary.json", summary)
        _write_json(output_dir / "candidate_rejection_matrix.json", rejection_matrix)
        _write_jsonl(output_dir / "a_plus_candidate_rows.jsonl", a_plus_rows)
        _write_jsonl(output_dir / "near_a_plus_candidate_rows.jsonl", near_rows)
    return {
        "rows": normalized,
        "summary": summary,
        "rejection_matrix": rejection_matrix,
        "a_plus_rows": a_plus_rows,
        "near_rows": near_rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--session", default="current", choices=("current",))
    parser.add_argument("--all-symbols", action="store_true")
    parser.add_argument("--all-timeframes", action="store_true")
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--max-prediction-keys", type=int, default=2500)
    parser.add_argument("--fail-on-hard-fail", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Compatibility flag; this read-only inventory command already runs once.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = _redis_client(args.redis_url)
    result = build_inventory(
        client=client,
        output_dir=Path(args.output_dir),
        session=args.session,
        timeframes=TARGET_TIMEFRAMES,
        max_prediction_keys=args.max_prediction_keys,
    )
    payload = {
        "summary": result["summary"],
        "rejection_matrix": result["rejection_matrix"],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "total_candidate_count": result["summary"]["total_candidate_count"],
            "a_plus_candidate_count": result["summary"]["a_plus_candidate_count"],
            "live_ready_candidate_count": result["summary"]["live_ready_candidate_count"],
            "primary_blocker": result["summary"]["primary_blocker"],
            "hard_fail": result["summary"]["hard_fail"],
        }, sort_keys=True))
    if args.fail_on_hard_fail and result["summary"]["hard_fail"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
