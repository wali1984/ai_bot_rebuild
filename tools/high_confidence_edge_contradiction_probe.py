#!/usr/bin/env python3
"""Classify high-confidence prediction rows against executable USD edge.

This tool is analysis-only. It reads current A+ inventory rows and optional
Redis prediction keys, writes goal artifacts, and never calls exchange APIs,
order endpoints, leverage/margin mutation, Redis trim, or live routes.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


HIGH_CONFIDENCE_THRESHOLD = 0.75
CONFIDENCE_BUCKETS = (
    (0.50, 0.55),
    (0.55, 0.60),
    (0.60, 0.65),
    (0.65, 0.70),
    (0.70, 0.75),
    (0.75, 0.80),
    (0.80, 0.85),
    (0.85, 0.90),
    (0.90, 1.01),
)

TAXONOMY_CLASSES = {
    "CONFIDENCE_IS_FOR_HOLD_NOT_TRADE",
    "CONFIDENCE_NOT_SIDE_SPECIFIC",
    "CONFIDENCE_PRE_COST_ONLY",
    "CONFIDENCE_CALIBRATED_BUT_NOT_OUTCOME_VALIDATED",
    "EXPECTED_MOVE_SIGN_INVERSION",
    "EXPECTED_USD_CONVERSION_BUG",
    "NOTIONAL_ZERO_OR_TOO_SMALL",
    "PRICE_MISSING_OR_STALE",
    "COST_MODEL_OVER_PENALIZES_EDGE",
    "LOSS_PROBABILITY_OVERRIDES_CONFIDENCE",
    "MICROSTRUCTURE_TRUST_OVERRIDES_CONFIDENCE",
    "RISK_GATEWAY_OVERRIDES_CONFIDENCE",
    "ORCHESTRATOR_OVERRIDES_CONFIDENCE",
    "ALLOCATOR_BUG_FALSE_NEGATIVE",
    "TRAINER_MISWIRED_ACTION_PROBABILITIES",
    "STALE_FEATURE_SNAPSHOT",
    "MISSING_MATURED_LABELS",
}

OUTPUT_ROW_FIELDS = (
    "candidate_id",
    "prediction_id",
    "signal_id",
    "symbol",
    "timeframe",
    "decision_time",
    "feature_cutoff",
    "available_at",
    "selected_action",
    "selected_side",
    "predicted_direction",
    "confidence_raw",
    "confidence_calibrated",
    "selected_action_probability",
    "action_probabilities",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "expected_net_pnl_usd",
    "expected_gross_pnl_usd",
    "expected_cost_usd",
    "expected_fees_usd",
    "expected_slippage_usd",
    "expected_funding_usd",
    "current_price",
    "current_price_source",
    "gross_notional_usd",
    "recommended_leverage",
    "recommended_margin_mode",
    "side",
    "best_side",
    "best_side_net_edge_bps",
    "expected_long_net_pnl_usd",
    "expected_short_net_pnl_usd",
    "expected_long_net_edge_bps",
    "expected_short_net_edge_bps",
    "pre_trade_loss_probability",
    "allocator_decision",
    "allocator_block_reasons",
    "risk_decision",
    "risk_block_reasons",
    "orchestrator_decision",
    "orchestrator_block_reasons",
    "preemptive_action",
    "preemptive_block_reasons",
    "microstructure_trust_score",
    "altdata_confluence_score",
    "strategy_family",
    "strategy_supply_hypothesis_id",
    "counts_as_A_plus",
    "counts_as_live_ready",
    "block_reasons",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass", "allow"}


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def normalize_action(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"buy", "open_long"}:
        return "long"
    if text in {"sell", "open_short"}:
        return "short"
    if text in {"hold", "no_trade", "none", "flat", "0"}:
        return "hold"
    if text in {"long", "short"}:
        return text
    return text or None


def selected_side(row: Mapping[str, Any]) -> str | None:
    for field in ("side", "selected_side", "selected_action", "action", "predicted_direction"):
        action = normalize_action(row.get(field))
        if action in {"long", "short"}:
            return action
    return None


def action_probabilities(row: Mapping[str, Any]) -> dict[str, float] | None:
    raw = first_present(
        row.get("action_probabilities"),
        row.get("action_probability_by_label"),
        row.get("policy_action_probabilities"),
    )
    if isinstance(raw, dict):
        out = {str(key).lower(): value for key, value in ((k, to_float(v)) for k, v in raw.items()) if value is not None}
        return out or None
    if isinstance(raw, list):
        labels = row.get("action_labels")
        if not isinstance(labels, list) or len(labels) != len(raw):
            labels = ["hold", "long", "short", "close", "hedge_reserved_fail_closed"][: len(raw)]
        out = {str(label).lower(): value for label, value in zip(labels, (to_float(v) for v in raw)) if value is not None}
        return out or None
    return None


def selected_probability(row: Mapping[str, Any], action: str | None, probs: Mapping[str, float] | None) -> float | None:
    explicit = to_float(first_present(row.get("selected_action_probability"), row.get("opening_policy_argmax_probability")))
    if explicit is not None:
        return explicit
    if action and probs:
        return to_float(probs.get(action))
    return None


def max_confidence(row: Mapping[str, Any]) -> float | None:
    action = normalize_action(first_present(row.get("selected_action"), row.get("action"), row.get("side")))
    probs = action_probabilities(row)
    values = [
        to_float(row.get("confidence_raw")),
        to_float(first_present(row.get("confidence_calibrated"), row.get("calibrated_confidence"), row.get("confidence"))),
        selected_probability(row, action, probs),
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def is_high_confidence(row: Mapping[str, Any]) -> bool:
    value = max_confidence(row)
    return value is not None and value >= HIGH_CONFIDENCE_THRESHOLD


def merged_block_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in (
        "block_reasons",
        "allocator_block_reasons",
        "risk_block_reasons",
        "orchestrator_block_reasons",
        "preemptive_block_reasons",
        "preemptive_decision_reasons",
        "paper_fill_gate_block_reasons",
    ):
        value = row.get(field)
        if isinstance(value, list):
            reasons.extend(str(item) for item in value if item)
        elif value:
            reasons.append(str(value))
    return list(dict.fromkeys(reasons))


def has_reason(row: Mapping[str, Any], *phrases: str) -> bool:
    upper = " ".join(merged_block_reasons(row)).upper()
    return any(phrase.upper() in upper for phrase in phrases)


def temporal_violation(row: Mapping[str, Any]) -> bool:
    decision = parse_time(first_present(row.get("decision_time"), row.get("generated_utc"), row.get("generated_at")))
    feature_cutoff = parse_time(row.get("feature_cutoff"))
    available = parse_time(row.get("available_at"))
    if decision is None:
        return False
    return bool((feature_cutoff and feature_cutoff > decision) or (available and available > decision))


def expected_cost_usd(row: Mapping[str, Any]) -> float | None:
    components = [
        to_float(first_present(row.get("expected_fees_usd"), row.get("fees_usd"), row.get("expected_fee_usd"))),
        to_float(row.get("expected_slippage_usd")),
        to_float(row.get("expected_funding_usd")),
        to_float(row.get("latency_reserve_usd")),
        to_float(row.get("hedge_cost_usd")),
        to_float(row.get("exit_failure_reserve_usd")),
    ]
    summed = sum(value or 0.0 for value in components)
    explicit = to_float(first_present(row.get("expected_cost_usd"), row.get("pre_trade_expected_cost_usd")))
    if explicit is not None:
        return max(explicit, summed)
    return summed if any(value is not None for value in components) else None


def notional_usd(row: Mapping[str, Any]) -> float | None:
    value = to_float(
        first_present(
            row.get("gross_notional_usd"),
            row.get("target_notional_usd"),
            row.get("notional_usd"),
            row.get("notional"),
            row.get("per_side_usd_notional"),
        )
    )
    return value if value is not None and value > 0.0 else None


def side_edge_bps(row: Mapping[str, Any], side: str | None) -> float | None:
    if side == "long":
        return to_float(first_present(row.get("expected_long_net_edge_bps"), row.get("long_expected_net_edge_bps")))
    if side == "short":
        return to_float(first_present(row.get("expected_short_net_edge_bps"), row.get("short_expected_net_edge_bps")))
    return None


def side_net_usd(row: Mapping[str, Any], side: str | None) -> float | None:
    if side == "long":
        return to_float(first_present(row.get("expected_long_net_pnl_usd"), row.get("long_expected_net_pnl_usd")))
    if side == "short":
        return to_float(first_present(row.get("expected_short_net_pnl_usd"), row.get("short_expected_net_pnl_usd")))
    return None


def independent_expected_net(row: Mapping[str, Any]) -> dict[str, Any]:
    side = selected_side(row)
    notional = notional_usd(row)
    system_net = to_float(first_present(row.get("expected_net_pnl_usd"), row.get("pre_trade_expected_net_pnl_usd")))
    edge_bps = side_edge_bps(row, side)
    side_net = side_net_usd(row, side)
    expected_move = to_float(row.get("expected_move_bps"))
    cost = expected_cost_usd(row)
    reason = "INSUFFICIENT_INPUTS"
    independent: float | None = None
    independent_gross: float | None = None
    independent_cost: float | None = cost
    if notional is not None and edge_bps is not None:
        independent = round(notional * edge_bps / 10000.0, 8)
        independent_gross = round(independent + (cost or 0.0), 8)
        reason = "SIDE_NET_EDGE_BPS_TIMES_GROSS_NOTIONAL"
    elif side_net is not None:
        independent = side_net
        independent_gross = round(side_net + (cost or 0.0), 8)
        reason = "EXPLICIT_SIDE_NET_USD"
    elif side in {"long", "short"} and notional is not None and expected_move is not None:
        side_sign = 1.0 if side == "long" else -1.0
        independent_gross = round(side_sign * expected_move / 10000.0 * notional, 8)
        independent = round(independent_gross - (cost or 0.0), 8)
        reason = "SIGNED_EXPECTED_MOVE_MINUS_COST"
    delta = None if independent is None or system_net is None else round(system_net - independent, 8)
    if delta is not None and abs(delta) <= 0.000001:
        delta_reason = "MATCH"
    elif independent is None:
        delta_reason = reason
    elif system_net is None:
        delta_reason = "SYSTEM_NET_MISSING"
    elif independent > 0.0 and system_net <= 0.0:
        delta_reason = "SYSTEM_NON_POSITIVE_BUT_INDEPENDENT_POSITIVE"
    else:
        delta_reason = "EXPLAINED_DELTA_OR_DIFFERENT_NOTIONAL_BASIS"
    return {
        "system_expected_net_pnl_usd": system_net,
        "independent_expected_net_pnl_usd": independent,
        "independent_expected_gross_pnl_usd": independent_gross,
        "independent_expected_cost_usd": independent_cost,
        "delta_usd": delta,
        "delta_reason": delta_reason,
        "independent_formula_source": reason,
    }


def confidence_semantics(row: Mapping[str, Any]) -> dict[str, Any]:
    action = normalize_action(first_present(row.get("selected_action"), row.get("action"), row.get("side"))) or "hold"
    probs = action_probabilities(row) or {}
    calibrated = to_float(first_present(row.get("confidence_calibrated"), row.get("calibrated_confidence"), row.get("confidence")))
    raw = to_float(row.get("confidence_raw"))
    selected_conf = selected_probability(row, action, probs) or calibrated or raw
    long_conf = to_float(first_present(row.get("confidence_directional_long"), probs.get("long")))
    short_conf = to_float(first_present(row.get("confidence_directional_short"), probs.get("short")))
    hold_conf = to_float(first_present(row.get("confidence_hold"), probs.get("hold")))
    if action == "long" and long_conf is None:
        long_conf = selected_conf
    elif action == "short" and short_conf is None:
        short_conf = selected_conf
    elif action == "hold" and hold_conf is None:
        hold_conf = selected_conf

    long_net = to_float(first_present(row.get("expected_long_net_pnl_usd"), row.get("long_expected_net_pnl_usd")))
    short_net = to_float(first_present(row.get("expected_short_net_pnl_usd"), row.get("short_expected_net_pnl_usd")))
    loss_prob = to_float(row.get("pre_trade_loss_probability"))
    missing_matured = has_reason(row, "BUCKET_EVIDENCE_INSUFFICIENT", "GUARDIAN_HALTED", "MISSING_MATURED")
    post_long = long_conf if long_conf is not None and long_net is not None and long_net > 0.0 else 0.0
    post_short = short_conf if short_conf is not None and short_net is not None and short_net > 0.0 else 0.0
    blockers: list[str] = []
    executable: float | None = None
    label = "Unproven confidence"
    if action == "hold":
        executable = 0.0
        label = "Hold confidence"
        blockers.append("selected_action_hold_not_trade")
    elif action == "long":
        executable = post_long
        label = "Post-cost executable confidence" if post_long else "Blocked by cost"
    elif action == "short":
        executable = post_short
        label = "Post-cost executable confidence" if post_short else "Blocked by cost"
    else:
        executable = 0.0
        label = "Unproven confidence"
        blockers.append("selected_action_not_directional")
    selected_net = long_net if action == "long" else short_net if action == "short" else None
    if selected_net is not None and selected_net <= 0.0:
        blockers.append("expected_net_pnl_usd_non_positive")
    if loss_prob is not None and loss_prob >= 0.65:
        blockers.append("loss_probability_high")
        if executable is not None:
            executable = min(executable, max(0.0, 1.0 - loss_prob))
        label = "Blocked by loss probability"
    if missing_matured:
        blockers.append("missing_matured_labels")
        label = "Unproven confidence" if executable else label
    if executable == 0.0 and not blockers:
        blockers.append("post_cost_executable_confidence_zero")
    return {
        "confidence_directional_long": long_conf,
        "confidence_directional_short": short_conf,
        "confidence_hold": hold_conf,
        "confidence_selected_action": selected_conf,
        "confidence_post_cost_long": post_long,
        "confidence_post_cost_short": post_short,
        "confidence_executable_trade": executable,
        "confidence_display_label": label,
        "confidence_tradeability_block_reasons": list(dict.fromkeys(blockers)),
    }


def classify_failure(row: Mapping[str, Any], conversion: Mapping[str, Any], semantics: Mapping[str, Any]) -> str:
    action = normalize_action(first_present(row.get("selected_action"), row.get("action"), row.get("side"))) or "hold"
    side = selected_side(row)
    expected_after = to_float(row.get("expected_move_after_cost_bps"))
    expected_move = to_float(row.get("expected_move_bps"))
    system_net = to_float(row.get("expected_net_pnl_usd"))
    independent_net = to_float(conversion.get("independent_expected_net_pnl_usd"))
    cost = expected_cost_usd(row)
    gross = to_float(row.get("expected_gross_pnl_usd"))
    loss_prob = to_float(row.get("pre_trade_loss_probability"))
    probs = action_probabilities(row)

    if action == "hold":
        return "CONFIDENCE_IS_FOR_HOLD_NOT_TRADE"
    if side is None:
        return "CONFIDENCE_NOT_SIDE_SPECIFIC"
    if temporal_violation(row) or has_reason(row, "STALE", "FRESHNESS", "AVAILABLE_AT_AFTER_DECISION", "CUTOFF_AFTER_DECISION"):
        return "STALE_FEATURE_SNAPSHOT"
    if probs is None and to_float(row.get("selected_action_probability")) is None and to_float(row.get("confidence_raw")) is not None:
        return "TRAINER_MISWIRED_ACTION_PROBABILITIES"
    if notional_usd(row) is None:
        return "NOTIONAL_ZERO_OR_TOO_SMALL"
    if to_float(row.get("current_price")) is None:
        return "PRICE_MISSING_OR_STALE"
    if independent_net is not None and system_net is not None and independent_net > 0.0 and system_net <= 0.0:
        return "EXPECTED_USD_CONVERSION_BUG"
    if side == "long" and expected_after is not None and expected_after < 0.0 and independent_net is not None and independent_net > 0.0:
        return "EXPECTED_MOVE_SIGN_INVERSION"
    if side == "short" and expected_after is not None and expected_after > 0.0 and has_reason(row, "SIGN", "SHORT_IN_BREAKOUT"):
        return "EXPECTED_MOVE_SIGN_INVERSION"
    if expected_move is not None and expected_after is not None and abs(expected_move) > 0.0 and expected_after <= 0.0:
        return "CONFIDENCE_PRE_COST_ONLY"
    if cost is not None and gross is not None and gross <= cost:
        return "COST_MODEL_OVER_PENALIZES_EDGE"
    if loss_prob is not None and loss_prob >= 0.65 or has_reason(row, "LOSS_PROBABILITY", "LOSS_RATE"):
        return "LOSS_PROBABILITY_OVERRIDES_CONFIDENCE"
    if has_reason(row, "MICROSTRUCTURE", "TAPE", "ORDERBOOK", "PUBLIC_BOOK"):
        return "MICROSTRUCTURE_TRUST_OVERRIDES_CONFIDENCE"
    if has_reason(row, "RISK_GATEWAY", "GUARDIAN", "LIQUIDATION", "STOP", "ATR", "EXIT"):
        return "RISK_GATEWAY_OVERRIDES_CONFIDENCE"
    if has_reason(row, "ORCHESTRATOR"):
        return "ORCHESTRATOR_OVERRIDES_CONFIDENCE"
    if str(row.get("allocator_decision") or "").upper() == "REJECT" and independent_net is not None and independent_net > 0.0:
        return "ALLOCATOR_BUG_FALSE_NEGATIVE"
    if has_reason(row, "BUCKET_EVIDENCE_INSUFFICIENT", "GUARDIAN_HALTED", "MISSING_MATURED") or semantics.get("confidence_display_label") == "Unproven confidence":
        return "MISSING_MATURED_LABELS"
    return "CONFIDENCE_CALIBRATED_BUT_NOT_OUTCOME_VALIDATED"


def output_row(row: Mapping[str, Any], source: str) -> dict[str, Any]:
    action = normalize_action(first_present(row.get("selected_action"), row.get("action"), row.get("side")))
    probs = action_probabilities(row)
    selected_prob = selected_probability(row, action, probs)
    conversion = independent_expected_net(row)
    semantics = confidence_semantics({**row, "selected_action_probability": selected_prob, "action_probabilities": probs})
    failure_class = classify_failure(row, conversion, semantics)
    long_edge = to_float(first_present(row.get("expected_long_net_edge_bps"), row.get("long_expected_net_edge_bps")))
    short_edge = to_float(first_present(row.get("expected_short_net_edge_bps"), row.get("short_expected_net_edge_bps")))
    best_side = first_present(row.get("best_side"))
    if best_side is None and (long_edge is not None or short_edge is not None):
        best_side = "long" if (long_edge or float("-inf")) >= (short_edge or float("-inf")) else "short"
    best_side_net_edge = long_edge if best_side == "long" else short_edge if best_side == "short" else None
    base = {
        "candidate_id": first_present(row.get("candidate_id"), row.get("decision_id"), row.get("prediction_id")),
        "prediction_id": row.get("prediction_id"),
        "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "decision_time": first_present(row.get("decision_time"), row.get("generated_utc"), row.get("generated_at")),
        "feature_cutoff": row.get("feature_cutoff"),
        "available_at": row.get("available_at"),
        "selected_action": action,
        "selected_side": selected_side(row),
        "predicted_direction": first_present(row.get("predicted_direction"), row.get("direction"), selected_side(row)),
        "confidence_raw": to_float(row.get("confidence_raw")),
        "confidence_calibrated": to_float(first_present(row.get("confidence_calibrated"), row.get("calibrated_confidence"), row.get("confidence"))),
        "selected_action_probability": selected_prob,
        "action_probabilities": probs,
        "expected_move_bps": to_float(row.get("expected_move_bps")),
        "expected_move_after_cost_bps": to_float(first_present(row.get("expected_move_after_cost_bps"), row.get("expected_edge_after_cost_bps"))),
        "expected_net_pnl_usd": to_float(first_present(row.get("expected_net_pnl_usd"), row.get("pre_trade_expected_net_pnl_usd"))),
        "expected_gross_pnl_usd": to_float(first_present(row.get("expected_gross_pnl_usd"), row.get("pre_trade_expected_gross_pnl_usd"))),
        "expected_cost_usd": expected_cost_usd(row),
        "expected_fees_usd": to_float(first_present(row.get("expected_fees_usd"), row.get("expected_fee_usd"), row.get("fees_usd"))),
        "expected_slippage_usd": to_float(row.get("expected_slippage_usd")),
        "expected_funding_usd": to_float(row.get("expected_funding_usd")),
        "current_price": to_float(first_present(row.get("current_price"), row.get("last_price"), row.get("mark_price"), row.get("price"))),
        "current_price_source": first_present(row.get("current_price_source"), row.get("price_source"), row.get("selected_execution_price_basis")),
        "gross_notional_usd": to_float(first_present(row.get("gross_notional_usd"), row.get("target_notional_usd"), row.get("notional_usd"))),
        "recommended_leverage": to_float(row.get("recommended_leverage")),
        "recommended_margin_mode": row.get("recommended_margin_mode"),
        "side": selected_side(row),
        "best_side": best_side,
        "best_side_net_edge_bps": best_side_net_edge,
        "expected_long_net_pnl_usd": to_float(first_present(row.get("expected_long_net_pnl_usd"), row.get("long_expected_net_pnl_usd"))),
        "expected_short_net_pnl_usd": to_float(first_present(row.get("expected_short_net_pnl_usd"), row.get("short_expected_net_pnl_usd"))),
        "expected_long_net_edge_bps": long_edge,
        "expected_short_net_edge_bps": short_edge,
        "pre_trade_loss_probability": to_float(row.get("pre_trade_loss_probability")),
        "allocator_decision": row.get("allocator_decision"),
        "allocator_block_reasons": as_list(row.get("allocator_block_reasons")),
        "risk_decision": row.get("risk_decision"),
        "risk_block_reasons": as_list(row.get("risk_block_reasons")),
        "orchestrator_decision": row.get("orchestrator_decision"),
        "orchestrator_block_reasons": as_list(row.get("orchestrator_block_reasons")),
        "preemptive_action": row.get("preemptive_action"),
        "preemptive_block_reasons": as_list(first_present(row.get("preemptive_block_reasons"), row.get("preemptive_decision_reasons"))),
        "microstructure_trust_score": to_float(first_present(row.get("microstructure_trust_score"), row.get("composite_microstructure_trust_score"))),
        "altdata_confluence_score": to_float(first_present(row.get("altdata_confluence_score"), row.get("altdata_symbol_score"))),
        "strategy_family": row.get("strategy_family"),
        "strategy_supply_hypothesis_id": first_present(row.get("strategy_supply_hypothesis_id"), row.get("hypothesis_id")),
        "counts_as_A_plus": to_bool(first_present(row.get("counts_as_A_plus"), row.get("A_plus_candidate"), row.get("counts_as_final_a_plus"))),
        "counts_as_live_ready": to_bool(first_present(row.get("counts_as_live_ready"), row.get("live_ready_candidate"))),
        "block_reasons": merged_block_reasons(row),
        "source": source,
        "primary_failure_class": failure_class,
        **conversion,
        **semantics,
    }
    return {field: base.get(field) for field in OUTPUT_ROW_FIELDS} | {
        key: base[key]
        for key in (
            "source",
            "primary_failure_class",
            "system_expected_net_pnl_usd",
            "independent_expected_net_pnl_usd",
            "independent_expected_gross_pnl_usd",
            "independent_expected_cost_usd",
            "delta_usd",
            "delta_reason",
            "independent_formula_source",
            "confidence_directional_long",
            "confidence_directional_short",
            "confidence_hold",
            "confidence_selected_action",
            "confidence_post_cost_long",
            "confidence_post_cost_short",
            "confidence_executable_trade",
            "confidence_display_label",
            "confidence_tradeability_block_reasons",
        )
    }


def load_redis_prediction_rows(redis_url: str | None) -> list[dict[str, Any]]:
    if not redis_url:
        return []
    try:
        import redis  # type: ignore
    except Exception:
        return []
    try:
        client = redis.Redis.from_url(redis_url)
        keys = list(client.scan_iter(match="v2:prediction:*", count=500))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for key in keys:
        try:
            raw = client.get(key)
        except Exception:
            continue
        if not raw:
            continue
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            payload.setdefault("source_runtime_key", key.decode("utf-8") if isinstance(key, bytes) else str(key))
            rows.append(payload)
    return rows


def reliability_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    for low, high in CONFIDENCE_BUCKETS:
        if low <= value < high:
            return f"{low:.2f}-{high if high < 1.0 else 1.0:.2f}"
    return "outside_bucket_range"


def build_reliability_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for low, high in CONFIDENCE_BUCKETS:
        label = f"{low:.2f}-{high if high < 1.0 else 1.0:.2f}"
        bucket_rows = [
            row for row in rows
            if (value := to_float(row.get("confidence_selected_action"))) is not None and low <= value < high
        ]
        sample_count = len([row for row in bucket_rows if row.get("realized_outcome_present") is True])
        buckets[label] = {
            "predicted_confidence_mean": (
                round(sum(to_float(row.get("confidence_selected_action")) or 0.0 for row in bucket_rows) / len(bucket_rows), 6)
                if bucket_rows else None
            ),
            "actual_win_rate": None,
            "actual_net_usd": None,
            "profit_factor": None,
            "sample_count": sample_count,
            "calibration_error": None,
            "lcb_win_rate": None,
            "lcb_net_usd": None,
            "should_penalize": sample_count < 30,
            "status": "UNPROVEN_LOW_SAMPLE" if sample_count < 30 else "READY_FOR_CALIBRATION",
            "row_count": len(bucket_rows),
        }
    breakdown_dimensions = [
        "symbol",
        "timeframe",
        "side",
        "strategy_family",
        "market_regime",
        "volatility_bucket",
        "provider_confluence_bucket",
        "microstructure_trust_bucket",
    ]
    return {
        "schema_version": "high_confidence_reliability_curve_v1",
        "generated_utc": utc_now(),
        "confidence_buckets": buckets,
        "breakdown_dimensions": breakdown_dimensions,
        "calibration_patch_required": any(bucket["should_penalize"] for bucket in buckets.values()),
        "calibration_patch_applied": "confidence_display_label marks low-sample high-confidence rows as unproven; runtime thresholds were not lowered",
    }


def build_exploration_status(output_rows: list[dict[str, Any]], redis_url: str | None) -> dict[str, Any]:
    redis_payloads: dict[str, Any] = {}
    if redis_url:
        try:
            import redis  # type: ignore
            client = redis.Redis.from_url(redis_url)
            for key in (
                "v2:trainer:status",
                "v2:trainer:feedback:outcomes",
                "v2:trainer:feedback:counterfactual_status",
                "v2:trainer:feedback:counterfactuals",
            ):
                raw = client.get(key)
                if raw:
                    try:
                        redis_payloads[key] = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                    except Exception:
                        redis_payloads[key] = None
        except Exception:
            pass
    trainer_status = as_dict(redis_payloads.get("v2:trainer:status"))
    outcomes = redis_payloads.get("v2:trainer:feedback:outcomes")
    counterfactual_status = as_dict(redis_payloads.get("v2:trainer:feedback:counterfactual_status"))
    counterfactuals = redis_payloads.get("v2:trainer:feedback:counterfactuals")
    rows_last_24h = len(outcomes) if isinstance(outcomes, list) else to_float(as_dict(outcomes).get("consumable_row_count"))
    return {
        "schema_version": "ppo_masa_exploration_status_v1",
        "generated_utc": utc_now(),
        "PPO_latest_checkpoint": first_present(trainer_status.get("PPO_latest_checkpoint"), trainer_status.get("ppo_checkpoint"), trainer_status.get("checkpoint_id")),
        "MASA_latest_checkpoint": first_present(trainer_status.get("MASA_latest_checkpoint"), trainer_status.get("masa_checkpoint"), trainer_status.get("checkpoint_id")),
        "training_rows_last_1h": trainer_status.get("training_rows_last_1h"),
        "training_rows_last_24h": rows_last_24h,
        "counterfactual_rows_consumed": counterfactual_status.get("existing_counterfactual_rows"),
        "matured_rows_consumed": trainer_status.get("matured_rows_consumed"),
        "paper_rows_consumed": trainer_status.get("paper_rows_consumed"),
        "replay_rows_consumed": counterfactual_status.get("merged_counterfactual_rows"),
        "strategy_families_explored": sorted({str(row.get("strategy_family")) for row in output_rows if row.get("strategy_family")}),
        "symbols_explored": sorted({str(row.get("symbol")) for row in output_rows if row.get("symbol")}),
        "timeframes_explored": sorted({str(row.get("timeframe")) for row in output_rows if row.get("timeframe")}),
        "long_rows": sum(1 for row in output_rows if row.get("selected_side") == "long"),
        "short_rows": sum(1 for row in output_rows if row.get("selected_side") == "short"),
        "hold_rows": sum(1 for row in output_rows if row.get("selected_action") == "hold"),
        "exploration_temperature": trainer_status.get("exploration_temperature"),
        "entropy": trainer_status.get("entropy"),
        "policy_update_count": trainer_status.get("policy_update_count"),
        "value_loss": trainer_status.get("value_loss"),
        "policy_loss": trainer_status.get("policy_loss"),
        "calibration_loss": trainer_status.get("calibration_loss"),
        "why_no_update_if_no_update": trainer_status.get("why_no_update_if_no_update") or (
            "trainer status did not publish checkpoint/update telemetry" if not trainer_status else None
        ),
        "counterfactual_rows_available": len(counterfactuals) if isinstance(counterfactuals, list) else counterfactual_status.get("pending_rows"),
    }


def compact_counterfactual_hypotheses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    for row in rows:
        if row.get("selected_action") != "hold":
            continue
        long_net = to_float(row.get("expected_long_net_pnl_usd"))
        short_net = to_float(row.get("expected_short_net_pnl_usd"))
        candidates = [("long", long_net), ("short", short_net)]
        candidates = [(side, value) for side, value in candidates if value is not None and value > 0.0]
        if not candidates:
            continue
        side, value = max(candidates, key=lambda item: item[1])
        hypotheses.append({
            "source": "COUNTERFACTUAL_SIDE_HYPOTHESIS",
            "candidate_id": row.get("candidate_id"),
            "prediction_id": row.get("prediction_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "original_selected_action": row.get("selected_action"),
            "counterfactual_side": side,
            "counterfactual_expected_net_pnl_usd": value,
            "why_selected_action_was_hold": row.get("hold_no_trade_reason") or "selected_action_hold",
            "why_counterfactual_side_is_considered": "positive_post_cost_side_diagnostic",
            "feature_hash": row.get("feature_vector_hash"),
            "provider_hashes": row.get("provider_feature_hashes") or row.get("source_hashes") or {},
            "maturity_requirement": "requires_guardian_evidence_and_matured_label",
            "requires_guardian_evidence": True,
            "requires_matured_label": True,
            "counts_as_A_plus": False,
            "counts_as_live_ready": False,
        })
    return hypotheses


def summarize(rows: list[dict[str, Any]], total_candidates: int) -> dict[str, Any]:
    return {
        "total_candidates": total_candidates,
        "high_confidence_rows": len(rows),
        "high_confidence_directional_rows": sum(1 for row in rows if row.get("selected_side") in {"long", "short"}),
        "high_confidence_hold_rows": sum(1 for row in rows if row.get("selected_action") == "hold"),
        "high_confidence_positive_expected_net_usd_rows": sum(1 for row in rows if (to_float(row.get("expected_net_pnl_usd")) or 0.0) > 0.0),
        "high_confidence_negative_expected_net_usd_rows": sum(1 for row in rows if (to_float(row.get("expected_net_pnl_usd")) or 0.0) <= 0.0),
        "high_confidence_missing_side_rows": sum(1 for row in rows if row.get("selected_side") not in {"long", "short"}),
        "high_confidence_price_missing_rows": sum(1 for row in rows if to_float(row.get("current_price")) is None),
        "high_confidence_cost_over_edge_rows": sum(
            1
            for row in rows
            if (to_float(row.get("expected_gross_pnl_usd")) is not None and to_float(row.get("expected_cost_usd")) is not None)
            and (to_float(row.get("expected_gross_pnl_usd")) or 0.0) <= (to_float(row.get("expected_cost_usd")) or 0.0)
        ),
        "high_confidence_loss_probability_blocked_rows": sum(1 for row in rows if (to_float(row.get("pre_trade_loss_probability")) or 0.0) >= 0.65 or has_reason(row, "LOSS_PROBABILITY", "LOSS_RATE")),
        "high_confidence_allocator_blocked_rows": sum(1 for row in rows if str(row.get("allocator_decision") or "").upper() in {"REJECT", "BLOCKED"}),
        "high_confidence_risk_blocked_rows": sum(1 for row in rows if str(row.get("risk_decision") or "").upper() in {"BLOCKED", "MISSING"}),
        "high_confidence_orchestrator_blocked_rows": sum(1 for row in rows if str(row.get("orchestrator_decision") or "").upper() in {"ABSTAIN", "BLOCKED", "MISSING"}),
        "high_confidence_matured_evidence_rows": sum(1 for row in rows if not has_reason(row, "BUCKET_EVIDENCE_INSUFFICIENT", "GUARDIAN_HALTED", "MISSING_MATURED")),
        "high_confidence_unmatured_rows": sum(1 for row in rows if has_reason(row, "BUCKET_EVIDENCE_INSUFFICIENT", "GUARDIAN_HALTED", "MISSING_MATURED")),
    }


def dedupe_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any, Any]] = set()
    for row in rows:
        key = (row.get("candidate_id"), row.get("prediction_id"), row.get("symbol"), row.get("timeframe"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    inventory_dir = Path(args.inventory_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_rows = read_jsonl(inventory_dir / "candidate_inventory.jsonl")
    prediction_rows = load_redis_prediction_rows(args.redis_url)
    inventory_summary = read_json(inventory_dir / "candidate_inventory_summary.json")
    inventory_high = [output_row(row, "candidate_inventory") for row in candidate_rows if is_high_confidence(row)]
    prediction_high = [output_row(row, "redis_prediction") for row in prediction_rows if is_high_confidence(row)]
    high_rows = dedupe_rows(inventory_high + prediction_high)
    class_counts = Counter(row["primary_failure_class"] for row in high_rows)
    unknown = [row for row in high_rows if row["primary_failure_class"] not in TAXONOMY_CLASSES]
    counterfactual_hypotheses = compact_counterfactual_hypotheses(high_rows)
    conversion_rows = [
        {
            "candidate_id": row.get("candidate_id"),
            "prediction_id": row.get("prediction_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "selected_action": row.get("selected_action"),
            "selected_side": row.get("selected_side"),
            "system_expected_net_pnl_usd": row.get("system_expected_net_pnl_usd"),
            "independent_expected_net_pnl_usd": row.get("independent_expected_net_pnl_usd"),
            "delta_usd": row.get("delta_usd"),
            "delta_reason": row.get("delta_reason"),
            "independent_formula_source": row.get("independent_formula_source"),
            "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
            "expected_cost_usd": row.get("expected_cost_usd"),
            "expected_gross_pnl_usd": row.get("expected_gross_pnl_usd"),
            "gross_notional_usd": row.get("gross_notional_usd"),
        }
        for row in high_rows
        if row.get("selected_side") in {"long", "short"}
    ]
    positive_independent_system_nonpositive = [
        row for row in conversion_rows
        if (to_float(row.get("independent_expected_net_pnl_usd")) or 0.0) > 0.0
        and (to_float(row.get("system_expected_net_pnl_usd")) or 0.0) <= 0.0
    ]
    summary = summarize(high_rows, int(inventory_summary.get("total_candidate_count") or len(candidate_rows)))
    phase0 = {
        "schema_version": "phase0_high_confidence_edge_contradiction_matrix_v1",
        "generated_utc": utc_now(),
        "inventory_dir": str(inventory_dir),
        "candidate_inventory_rows_scanned": len(candidate_rows),
        "redis_prediction_rows_scanned": len(prediction_rows),
        **summary,
        "primary_failure_class_counts": dict(sorted(class_counts.items())),
        "hard_fail": False,
        "safety": {
            "paper_only": True,
            "places_real_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "redis_trim": False,
        },
    }
    phase1 = {
        "schema_version": "phase1_high_confidence_failure_taxonomy_v1",
        "generated_utc": utc_now(),
        "taxonomy_classes": sorted(TAXONOMY_CLASSES),
        "class_counts": dict(sorted(class_counts.items())),
        "unknown_count": len(unknown),
        "unknown_rows": unknown[:25],
        "all_rows_classified_once": len(unknown) == 0 and sum(class_counts.values()) == len(high_rows),
    }
    phase3 = {
        "schema_version": "phase3_expected_net_usd_conversion_repair_v1",
        "generated_utc": utc_now(),
        "formula": {
            "expected_gross_pnl_usd": "side_sign * expected_move_pct * gross_notional_usd",
            "expected_cost_usd": "fees + slippage + funding + latency reserve + hedge cost if applicable",
            "expected_net_pnl_usd": "expected_gross_pnl_usd - expected_cost_usd",
        },
        "directional_high_confidence_rows": len(conversion_rows),
        "row_level_diff": conversion_rows,
        "positive_independent_expected_net_but_system_non_positive_count": len(positive_independent_system_nonpositive),
        "positive_independent_expected_net_but_system_non_positive_rows": positive_independent_system_nonpositive[:100],
        "hard_fail": len(positive_independent_system_nonpositive) > 0,
        "repair_status": (
            "NO_EXPECTED_USD_CONVERSION_MISMATCH_FOUND"
            if not positive_independent_system_nonpositive
            else "EXPECTED_USD_CONVERSION_MISMATCH_REQUIRES_RUNTIME_PATCH"
        ),
    }
    phase4 = {
        "schema_version": "phase4_counterfactual_side_rescue_status_v1",
        "generated_utc": utc_now(),
        "counterfactual_side_hypothesis_count": len(counterfactual_hypotheses),
        "candidate_hypothesis_rows": counterfactual_hypotheses[:250],
        "counts_as_A_plus": False,
        "counts_as_live_ready": False,
        "requires_guardian_evidence": True,
        "requires_matured_label": True,
        "hard_fail": False,
    }
    phase5 = build_reliability_curve(high_rows)
    phase6 = build_exploration_status(high_rows, args.redis_url)
    phase8 = {
        "schema_version": "phase8_ui_confidence_truth_status_v1",
        "generated_utc": utc_now(),
        "required_ui_labels": [
            "Hold confidence",
            "Directional confidence",
            "Post-cost executable confidence",
            "A+ eligible confidence",
            "Unproven confidence",
            "Blocked by cost",
            "Blocked by loss probability",
            "Blocked by allocator",
            "Blocked by missing matured labels",
        ],
        "high_confidence_rows_with_display_label": sum(1 for row in high_rows if row.get("confidence_display_label")),
        "high_confidence_executable_rows": sum(1 for row in high_rows if (to_float(row.get("confidence_executable_trade")) or 0.0) > 0.0),
        "generic_confidence_replaced_by_semantic_fields": True,
        "hard_fail": False,
    }
    write_jsonl(output_dir / "high_confidence_candidate_rows.jsonl", high_rows)
    write_json(output_dir / "phase0_high_confidence_edge_contradiction_matrix.json", phase0)
    write_json(output_dir / "phase1_high_confidence_failure_taxonomy.json", phase1)
    write_json(output_dir / "phase3_expected_net_usd_conversion_repair.json", phase3)
    write_json(output_dir / "phase4_counterfactual_side_rescue_status.json", phase4)
    write_json(output_dir / "phase5_high_confidence_reliability_curve.json", phase5)
    write_json(output_dir / "phase6_ppo_masa_exploration_status.json", phase6)
    write_json(output_dir / "phase8_ui_confidence_truth_status.json", phase8)
    return {
        "phase0": phase0,
        "phase1": phase1,
        "phase3": {
            key: value
            for key, value in phase3.items()
            if key not in {"row_level_diff", "positive_independent_expected_net_but_system_non_positive_rows"}
        },
        "phase4_counterfactual_side_hypothesis_count": len(counterfactual_hypotheses),
        "phase5": {
            "calibration_patch_required": phase5["calibration_patch_required"],
            "bucket_count": len(phase5["confidence_buckets"]),
        },
        "phase6": phase6,
        "phase8": phase8,
        "output_dir": str(output_dir),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
