"""Decision-facing advanced-indicator consumption rules."""

from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _score(value: Any) -> float | None:
    score = _f(value)
    if score is None:
        return None
    return score / 100.0 if score > 1.0 else score


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _side(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"long", "buy"}:
        return "long"
    if text in {"short", "sell"}:
        return "short"
    return None


def _direction(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"up", "bull", "bullish", "long"}:
        return "up"
    if text in {"down", "bear", "bearish", "short"}:
        return "down"
    return None


def _dig(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        cur: Any = payload
        for part in key.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur is not None:
            return cur
    return None


ADVANCED_CONTEXT_FIELDS = (
    "bullish_fvg_present",
    "bearish_fvg_present",
    "fvg_size_bps",
    "distance_to_fvg_bps",
    "fvg_fill_percent",
    "fvg_retest_confirmed",
    "htf_fvg_alignment",
    "fvg_liquidity_confluence",
    "fvg_orderbook_trust_confluence",
    "fvg_trade_tape_confirmation",
    "fvg_expected_edge_after_cost",
    "bos_direction",
    "choch_direction",
    "order_block_strength",
    "breaker_block_active",
    "mitigation_block_active",
    "premium_discount_zone",
    "session_high_sweep",
    "session_low_sweep",
    "structure_trend_state",
    "nearest_liquidity_above",
    "nearest_liquidity_below",
    "distance_to_liquidity_above_bps",
    "distance_to_liquidity_below_bps",
    "liquidity_zone_strength",
    "sweep_risk_long_side",
    "sweep_risk_short_side",
    "fake_breakout_risk",
    "fake_breakdown_risk",
    "post_sweep_reversal_probability",
    "cascade_continuation_probability",
    "distance_to_vwap_bps",
    "vwap_slope",
    "cvd_slope",
    "cvd_divergence",
    "trade_imbalance",
    "large_trade_cluster",
    "sweep_prints",
)


def extract_advanced_indicator_context(candidate: dict[str, Any]) -> dict[str, Any]:
    nested = candidate.get("advanced_indicator_context")
    context: dict[str, Any] = dict(nested) if isinstance(nested, dict) else {}
    for field in ADVANCED_CONTEXT_FIELDS:
        if field in candidate and field not in context:
            context[field] = candidate[field]
    for source_name in (
        "fvg",
        "market_structure",
        "liquidity_zones",
        "sweep_risk",
        "vwap_features",
        "volume_profile",
        "cvd_features",
        "trade_tape_features",
    ):
        source = candidate.get(source_name)
        if not isinstance(source, dict):
            continue
        for field in ADVANCED_CONTEXT_FIELDS:
            if field in source and field not in context:
                context[field] = source[field]
    return context


def evaluate_advanced_indicator_context(candidate: dict[str, Any]) -> dict[str, Any]:
    context = extract_advanced_indicator_context(candidate)
    side = _side(candidate.get("side") or candidate.get("action") or candidate.get("selected_action"))
    reasons: list[str] = []
    caution: list[str] = []
    missing: list[str] = []
    if not context:
        missing.append("ADVANCED_INDICATOR_CONTEXT_MISSING")
    if candidate.get("advanced_indicator_invalid_contract_keys"):
        missing.append("ADVANCED_INDICATOR_CONTRACT_INVALID_OR_UNREPAIRED")

    tape_score = _f(
        _dig(context, "trade_tape_confirmation_score")
        or context.get("fvg_trade_tape_confirmation")
        or candidate.get("trade_tape_confirmation_score")
    )
    trust_score = _score(
        _first_present(
            _dig(context, "fvg_orderbook_trust_confluence"),
            candidate.get("composite_microstructure_trust_score"),
            candidate.get("microstructure_trust_score"),
            candidate.get("market_state_integrity_score"),
        )
    )
    expected_edge = _f(
        context.get("fvg_expected_edge_after_cost")
        or candidate.get("expected_move_after_cost_bps_directional")
        or candidate.get("expected_move_after_cost_bps")
    )
    exit_score = _f(candidate.get("exit_feasibility_score"))

    bullish_fvg = _truthy(context.get("bullish_fvg_present"))
    bearish_fvg = _truthy(context.get("bearish_fvg_present"))
    fvg_present = bullish_fvg or bearish_fvg
    fvg_aligned = (side == "long" and bullish_fvg) or (side == "short" and bearish_fvg)
    if fvg_present and not fvg_aligned:
        caution.append("FVG_NOT_ALIGNED_WITH_CANDIDATE_SIDE")
    if fvg_present:
        if trust_score is None or trust_score < 0.65:
            caution.append("FVG_CONFLUENCE_WITHOUT_SUFFICIENT_MICROSTRUCTURE_TRUST")
        if tape_score is None or tape_score < 0.55:
            caution.append("FVG_CONFLUENCE_WITHOUT_TAPE_CONFIRMATION")
        if expected_edge is None or expected_edge <= 0:
            caution.append("FVG_CONFLUENCE_WITHOUT_POSITIVE_AFTER_COST_EDGE")
        if exit_score is None or exit_score < 0.55:
            caution.append("FVG_CONFLUENCE_WITHOUT_VALID_EXIT_FEASIBILITY")

    choch = _direction(context.get("choch_direction"))
    bos = _direction(context.get("bos_direction"))
    if side == "long" and choch == "down":
        reasons.append("CHOCH_AGAINST_LONG_DIRECTION")
    if side == "short" and choch == "up":
        reasons.append("CHOCH_AGAINST_SHORT_DIRECTION")

    sweep_long = _f(context.get("sweep_risk_long_side"))
    sweep_short = _f(context.get("sweep_risk_short_side"))
    generic_sweep = _f(context.get("liquidity_sweep_risk") or candidate.get("liquidity_sweep_risk"))
    side_sweep = sweep_long if side == "long" else sweep_short if side == "short" else generic_sweep
    if side_sweep is None:
        side_sweep = generic_sweep
    if side_sweep is not None and side_sweep >= 0.75 and (tape_score is None or tape_score < 0.60):
        reasons.append("LIQUIDITY_SWEEP_RISK_HIGH_UNCONFIRMED")

    cvd_slope = _f(context.get("cvd_slope"))
    distance_vwap = _f(context.get("distance_to_vwap_bps"))
    if side == "long" and distance_vwap is not None and distance_vwap > 0 and cvd_slope is not None and cvd_slope < 0:
        caution.append("PRICE_ABOVE_VWAP_WITH_FALLING_CVD")
    if side == "short" and distance_vwap is not None and distance_vwap < 0 and cvd_slope is not None and cvd_slope > 0:
        caution.append("PRICE_BELOW_VWAP_WITH_RISING_CVD")

    confluence_parts = []
    if fvg_present and fvg_aligned and not any(item.startswith("FVG_CONFLUENCE_WITHOUT") for item in caution):
        confluence_parts.append(0.2)
    if bos and ((side == "long" and bos == "up") or (side == "short" and bos == "down")):
        confluence_parts.append(0.2)
    if tape_score is not None:
        confluence_parts.append(max(0.0, min(0.2, tape_score * 0.2)))
    if trust_score is not None:
        confluence_parts.append(max(0.0, min(0.2, trust_score * 0.2)))
    if side_sweep is not None:
        confluence_parts.append(max(0.0, min(0.2, (1.0 - side_sweep) * 0.2)))
    confluence = round(sum(confluence_parts), 4) if confluence_parts else None
    return {
        "advanced_indicator_consumed": True,
        "advanced_indicator_status": (
            "ADVANCED_INDICATOR_BLOCK"
            if reasons
            else "ADVANCED_INDICATOR_EVIDENCE_MISSING"
            if missing
            else "ADVANCED_INDICATOR_CAUTION"
            if caution
            else "ADVANCED_INDICATOR_CONSUMED"
        ),
        "advanced_indicator_block": bool(reasons),
        "advanced_indicator_shadow": bool(caution or missing) and not reasons,
        "advanced_indicator_block_reasons": list(dict.fromkeys(reasons)),
        "advanced_indicator_caution_reasons": list(dict.fromkeys(caution)),
        "advanced_indicator_missing_evidence": list(dict.fromkeys(missing)),
        "advanced_indicator_confluence_score": confluence,
        "fvg_standalone_allows_trade": False,
        "fvg_present": fvg_present,
        "fvg_side_aligned": fvg_aligned if fvg_present and side else None,
        "liquidity_sweep_risk": side_sweep,
        "advanced_indicator_exit_plan_inputs": {
            "nearest_liquidity_above": context.get("nearest_liquidity_above"),
            "nearest_liquidity_below": context.get("nearest_liquidity_below"),
            "distance_to_fvg_bps": context.get("distance_to_fvg_bps"),
            "distance_to_vwap_bps": context.get("distance_to_vwap_bps"),
            "structure_invalidation": context.get("choch_direction"),
        },
    }
