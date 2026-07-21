from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.hedge_engine import evaluate_hedge_intent, simulate_cross_margin_stress
from v2.backend.app.services.paper_trade_management.exits import (
    PaperExitConfig,
    effective_atr_stop_bps,
)
from v2.backend.app.services.paper_trade_management.hedging import hedge_arm_fraction

from .contracts import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    MAINTENANCE_MARGIN_INPUT_UNSET,
    AllocationInput,
    AllocationResult,
    RiskEnvelope,
)
from .exchange_filters import min_order_notional, round_down_to_step
from .explanation import explain_allocation
from .risk_budget import available_margin_budget_usdt, risk_envelope_gross_notional_ceiling
from .sizing_model import (
    adaptive_budget_pct,
    confidence_adjustment,
    correlation_adjustment,
    drawdown_adjustment,
    edge_adjustment,
    exposure_adjustment,
    liquidity_adjustment,
    market_state_adjustment,
    regime_adjustment,
    spread_slippage_adjustment,
    volatility_adjustment,
)

MAX_DYNAMIC_HEDGE_BUDGET_PCT_OF_RISK = 0.35
LIVE_LEGACY_MAINTENANCE_MARGIN_RATE = 0.005
PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY = "paper_growth_envelope_authorization_receipt"
PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY = (
    "paper_growth_envelope_authorization_receipt_sha256"
)
PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY = "paper_allocator_liquidity_source_material"
PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY = (
    "paper_allocator_liquidity_source_material_sha256"
)
PAPER_ALLOCATOR_REGIME_SOURCE_MATERIAL_LINEAGE_KEY = "paper_allocator_regime_source_material"
PAPER_ALLOCATOR_REGIME_SOURCE_HASH_LINEAGE_KEY = "paper_allocator_regime_source_material_sha256"
PAPER_LIQUIDATION_ATR_EVIDENCE_SCHEMA_VERSION = "paper_liquidation_atr_evidence_v1"
PAPER_LIQUIDATION_ATR_SOURCE_MATERIAL_SCHEMA_VERSION = "paper_liquidation_atr_source_material_v1"
PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY = "paper_liquidation_atr_evidence"
PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY = "paper_liquidation_atr_evidence_sha256"
PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY = "paper_allocator_arithmetic_receipt"
PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION = "paper_allocator_arithmetic_receipt_v1"
PAPER_ALLOCATOR_ARITHMETIC_VERSION = "adaptive_capital_allocator_binary64_arithmetic_v1"
PAPER_ALLOCATOR_ARITHMETIC_FORMULA = (
    "raw_post_step_notional=abs(binary64(raw_post_step_quantity)*"
    "binary64(input_price));raw_allocated_margin=raw_post_step_notional/"
    "binary64(selected_leverage);publish=round(quantity,12),round(notional,8),"
    "round(leverage,8),round(margin,8)"
)
_PAPER_LIQUIDATION_ATR_BPS_FIELDS = (
    "entry_atr_bps",
    "atr_bps",
    "true_range_bps",
    "natr_bps",
)
_PAPER_LIQUIDATION_ATR_PERCENT_FIELDS = (
    "atr_pct",
    "true_range_pct",
    "ta_NATR",
    "ta_NATR_14",
)
_PAPER_LIQUIDATION_ATR_PRICE_FIELDS = (
    "atr_14",
    "ta_ATR",
    "ta_ATR_14",
    "ATR",
    "TRANGE",
    "ta_TRANGE",
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _canonical_sha256(value: Any) -> str | None:
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _paper_allocator_arithmetic_receipt(
    *,
    raw_post_step_quantity: float,
    input_price: float,
    raw_post_step_notional: float,
    selected_leverage: float,
) -> dict[str, str]:
    """Seal the exact binary64 operands behind the rounded paper ABI."""

    values = (
        raw_post_step_quantity,
        input_price,
        raw_post_step_notional,
        selected_leverage,
    )
    if not all(type(value) is float and math.isfinite(value) and value > 0.0 for value in values):
        raise ValueError("paper allocator arithmetic receipt requires positive finite binary64")
    material = {
        "schema_version": PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION,
        "arithmetic_version": PAPER_ALLOCATOR_ARITHMETIC_VERSION,
        "formula": PAPER_ALLOCATOR_ARITHMETIC_FORMULA,
        "raw_post_step_quantity_binary64_hex": raw_post_step_quantity.hex(),
        "input_price_binary64_hex": input_price.hex(),
        "raw_post_step_notional_binary64_hex": raw_post_step_notional.hex(),
        "selected_leverage_binary64_hex": selected_leverage.hex(),
    }
    receipt_sha256 = _canonical_sha256(material)
    if receipt_sha256 is None:  # pragma: no cover - fixed finite/string material
        raise ValueError("paper allocator arithmetic receipt is not canonical JSON")
    return {**material, "receipt_sha256": receipt_sha256}


def _aware_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def build_paper_liquidation_atr_evidence(
    *,
    feature_snapshot: Mapping[str, Any] | None,
    symbol: str,
    timeframe: str,
    entry_price: float,
    allocation_decision_time: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Build the only ATR receipt allowed to authorize PAPER leverage above 1x.

    The source must be the already validated canonical entry feature snapshot.
    Top-level signal values, volatility defaults, and TA-flat fallbacks are
    deliberately outside this authority boundary.
    """

    reasons: list[str] = []
    snapshot = dict(feature_snapshot) if isinstance(feature_snapshot, Mapping) else {}
    if not snapshot:
        return None, ["PAPER_LIQUIDATION_ATR_CANONICAL_FEATURE_SNAPSHOT_MISSING"]

    normalized_symbol = str(symbol or "").strip().upper()
    normalized_timeframe = str(timeframe or "").strip().lower()
    snapshot_symbol = str(snapshot.get("symbol") or "").strip().upper()
    snapshot_timeframe = str(snapshot.get("timeframe") or "").strip().lower()
    snapshot_id = str(snapshot.get("feature_snapshot_id") or "").strip()
    if not snapshot_id:
        reasons.append("PAPER_LIQUIDATION_ATR_FEATURE_SNAPSHOT_ID_MISSING")
    if not normalized_symbol or snapshot_symbol != normalized_symbol:
        reasons.append("PAPER_LIQUIDATION_ATR_FEATURE_SNAPSHOT_SYMBOL_MISMATCH")
    if not normalized_timeframe or snapshot_timeframe != normalized_timeframe:
        reasons.append("PAPER_LIQUIDATION_ATR_FEATURE_SNAPSHOT_TIMEFRAME_MISMATCH")
    if str(snapshot.get("feature_freshness_state") or "").strip().upper() != "CURRENT":
        reasons.append("PAPER_LIQUIDATION_ATR_FEATURE_SNAPSHOT_NOT_CURRENT")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("PAPER_LIQUIDATION_ATR_CANDLE_NOT_FINAL")
    if snapshot.get("latest_unclosed_kline_excluded") is not True:
        reasons.append("PAPER_LIQUIDATION_ATR_UNCLOSED_KLINE_EXCLUSION_NOT_PROVEN")

    parsed_times = {
        "candle_close_time": _aware_utc(snapshot.get("candle_close_time")),
        "feature_cutoff": _aware_utc(snapshot.get("feature_cutoff")),
        "available_at": _aware_utc(snapshot.get("available_at")),
        "generated_at": _aware_utc(snapshot.get("generated_at")),
        "allocation_decision_time": _aware_utc(allocation_decision_time),
    }
    for field, parsed in parsed_times.items():
        if parsed is None:
            reasons.append(f"PAPER_LIQUIDATION_ATR_TIME_INVALID:{field}")
    if all(parsed_times.values()):
        ordered_fields = (
            "candle_close_time",
            "feature_cutoff",
            "available_at",
            "generated_at",
            "allocation_decision_time",
        )
        for left, right in zip(ordered_fields, ordered_fields[1:], strict=False):
            left_time = parsed_times[left]
            right_time = parsed_times[right]
            if left_time is not None and right_time is not None and left_time > right_time:
                reasons.append(f"PAPER_LIQUIDATION_ATR_TIME_ORDER_INVALID:{left}>{right}")

    features = snapshot.get("features")
    features = dict(features) if isinstance(features, Mapping) else {}
    if not features:
        reasons.append("PAPER_LIQUIDATION_ATR_FEATURES_MISSING")

    atr_field: str | None = None
    atr_raw_value: float | None = None
    atr_conversion: str | None = None
    atr_bps: float | None = None
    for field in _PAPER_LIQUIDATION_ATR_BPS_FIELDS:
        value = _finite_float(features.get(field))
        if value is not None and value > 0.0:
            atr_field = field
            atr_raw_value = value
            atr_conversion = "BPS_IDENTITY"
            atr_bps = value
            break
    if atr_bps is None:
        for field in _PAPER_LIQUIDATION_ATR_PERCENT_FIELDS:
            value = _finite_float(features.get(field))
            if value is not None and value > 0.0:
                atr_field = field
                atr_raw_value = value
                atr_conversion = "PERCENT_UNITS_X_100_TO_BPS"
                atr_bps = value * 100.0
                break
    if atr_bps is None:
        price = _finite_float(entry_price)
        if price is not None and price > 0.0:
            for field in _PAPER_LIQUIDATION_ATR_PRICE_FIELDS:
                value = _finite_float(features.get(field))
                if value is not None and value > 0.0:
                    atr_field = field
                    atr_raw_value = value
                    atr_conversion = "PRICE_UNITS_DIV_ENTRY_PRICE_X_10000_TO_BPS"
                    atr_bps = value / price * 10000.0
                    break
    if atr_bps is None or not math.isfinite(atr_bps) or atr_bps <= 0.0:
        reasons.append("PAPER_LIQUIDATION_ATR_POSITIVE_FINITE_VALUE_MISSING")

    source_snapshot_sha256 = _canonical_sha256(snapshot)
    if not _valid_sha256(source_snapshot_sha256):
        reasons.append("PAPER_LIQUIDATION_ATR_FEATURE_SNAPSHOT_HASH_INVALID")
    if reasons:
        return None, sorted(set(reasons))

    assert atr_field is not None
    assert atr_raw_value is not None
    assert atr_conversion is not None
    assert atr_bps is not None
    assert source_snapshot_sha256 is not None
    candle_close_time = parsed_times["candle_close_time"]
    feature_cutoff = parsed_times["feature_cutoff"]
    available_at = parsed_times["available_at"]
    generated_at = parsed_times["generated_at"]
    decision_time = parsed_times["allocation_decision_time"]
    assert candle_close_time is not None
    assert feature_cutoff is not None
    assert available_at is not None
    assert generated_at is not None
    assert decision_time is not None
    source_material = {
        "schema_version": PAPER_LIQUIDATION_ATR_SOURCE_MATERIAL_SCHEMA_VERSION,
        "feature_snapshot_id": snapshot_id,
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "latest_unclosed_kline_excluded": True,
        "candle_close_time": _utc_iso(candle_close_time),
        "feature_cutoff": _utc_iso(feature_cutoff),
        "available_at": _utc_iso(available_at),
        "generated_at": _utc_iso(generated_at),
        "allocation_decision_time": _utc_iso(decision_time),
        "atr_source_field": atr_field,
        "atr_source_value": atr_raw_value,
        "atr_conversion": atr_conversion,
        "entry_price": float(entry_price),
        "source_snapshot_sha256": source_snapshot_sha256,
    }
    source_material_sha256 = _canonical_sha256(source_material)
    if source_material_sha256 is None:
        return None, ["PAPER_LIQUIDATION_ATR_SOURCE_MATERIAL_HASH_INVALID"]
    receipt_material = {
        "schema_version": PAPER_LIQUIDATION_ATR_EVIDENCE_SCHEMA_VERSION,
        "source": "CANONICAL_PIT_FINAL_ENTRY_FEATURE_SNAPSHOT",
        "feature_snapshot_id": snapshot_id,
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "latest_unclosed_kline_excluded": True,
        "candle_close_time": source_material["candle_close_time"],
        "feature_cutoff": source_material["feature_cutoff"],
        "available_at": source_material["available_at"],
        "generated_at": source_material["generated_at"],
        "allocation_decision_time": source_material["allocation_decision_time"],
        "atr_bps": atr_bps,
        "atr_source_field": atr_field,
        "atr_source_value": atr_raw_value,
        "atr_conversion": atr_conversion,
        "entry_price": float(entry_price),
        "source_snapshot_sha256": source_snapshot_sha256,
        "source_material": source_material,
        "source_material_sha256": source_material_sha256,
    }
    evidence_sha256 = _canonical_sha256(receipt_material)
    if evidence_sha256 is None:
        return None, ["PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_INVALID"]
    return {
        **receipt_material,
        "evidence_sha256": evidence_sha256,
    }, []


def validate_paper_liquidation_atr_evidence(
    evidence: Mapping[str, Any] | None,
    claimed_evidence_sha256: Any,
    *,
    symbol: str,
    timeframe: str,
    entry_atr_bps: Any,
) -> tuple[float | None, list[str]]:
    """Recompute a PAPER liquidation ATR receipt at each money-path boundary."""

    reasons: list[str] = []
    receipt = dict(evidence) if isinstance(evidence, Mapping) else {}
    if not receipt:
        return None, ["PAPER_LIQUIDATION_ATR_EVIDENCE_MISSING"]
    embedded_hash = receipt.pop("evidence_sha256", None)
    recomputed_hash = _canonical_sha256(receipt)
    if (
        not _valid_sha256(embedded_hash)
        or embedded_hash != claimed_evidence_sha256
        or embedded_hash != recomputed_hash
    ):
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_MISMATCH")
    if receipt.get("schema_version") != PAPER_LIQUIDATION_ATR_EVIDENCE_SCHEMA_VERSION:
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_SCHEMA_INVALID")
    if receipt.get("source") != "CANONICAL_PIT_FINAL_ENTRY_FEATURE_SNAPSHOT":
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_SOURCE_INVALID")

    normalized_symbol = str(symbol or "").strip().upper()
    normalized_timeframe = str(timeframe or "").strip().lower()
    if str(receipt.get("symbol") or "").strip().upper() != normalized_symbol:
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_SYMBOL_MISMATCH")
    if str(receipt.get("timeframe") or "").strip().lower() != normalized_timeframe:
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_TIMEFRAME_MISMATCH")
    if str(receipt.get("feature_snapshot_id") or "").strip() == "":
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_SNAPSHOT_ID_MISSING")
    if str(receipt.get("feature_freshness_state") or "").upper() != "CURRENT":
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_NOT_CURRENT")
    if receipt.get("candle_closed_confirmed") is not True:
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_CANDLE_NOT_FINAL")
    if receipt.get("latest_unclosed_kline_excluded") is not True:
        reasons.append("PAPER_LIQUIDATION_ATR_EVIDENCE_UNCLOSED_KLINE_NOT_EXCLUDED")

    parsed_times = {
        field: _aware_utc(receipt.get(field))
        for field in (
            "candle_close_time",
            "feature_cutoff",
            "available_at",
            "generated_at",
            "allocation_decision_time",
        )
    }
    for field, parsed in parsed_times.items():
        if parsed is None:
            reasons.append(f"PAPER_LIQUIDATION_ATR_EVIDENCE_TIME_INVALID:{field}")
    if all(parsed_times.values()):
        ordered_fields = (
            "candle_close_time",
            "feature_cutoff",
            "available_at",
            "generated_at",
            "allocation_decision_time",
        )
        for left, right in zip(ordered_fields, ordered_fields[1:], strict=False):
            left_time = parsed_times[left]
            right_time = parsed_times[right]
            if left_time is not None and right_time is not None and left_time > right_time:
                reasons.append(f"PAPER_LIQUIDATION_ATR_EVIDENCE_TIME_ORDER_INVALID:{left}>{right}")

    source_material = receipt.get("source_material")
    source_material = dict(source_material) if isinstance(source_material, Mapping) else {}
    if (
        not source_material
        or source_material.get("schema_version")
        != PAPER_LIQUIDATION_ATR_SOURCE_MATERIAL_SCHEMA_VERSION
        or _canonical_sha256(source_material) != receipt.get("source_material_sha256")
    ):
        reasons.append("PAPER_LIQUIDATION_ATR_SOURCE_MATERIAL_INVALID")
    for field in (
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "feature_freshness_state",
        "candle_closed_confirmed",
        "latest_unclosed_kline_excluded",
        "candle_close_time",
        "feature_cutoff",
        "available_at",
        "generated_at",
        "allocation_decision_time",
        "atr_source_field",
        "atr_source_value",
        "atr_conversion",
        "entry_price",
        "source_snapshot_sha256",
    ):
        if source_material.get(field) != receipt.get(field):
            reasons.append(f"PAPER_LIQUIDATION_ATR_SOURCE_MATERIAL_MISMATCH:{field}")
    if not _valid_sha256(receipt.get("source_snapshot_sha256")):
        reasons.append("PAPER_LIQUIDATION_ATR_SOURCE_SNAPSHOT_HASH_INVALID")

    raw_value = _finite_float(receipt.get("atr_source_value"))
    receipt_price = _finite_float(receipt.get("entry_price"))
    conversion = receipt.get("atr_conversion")
    recomputed_atr: float | None = None
    if raw_value is not None and raw_value > 0.0:
        if conversion == "BPS_IDENTITY":
            recomputed_atr = raw_value
        elif conversion == "PERCENT_UNITS_X_100_TO_BPS":
            recomputed_atr = raw_value * 100.0
        elif (
            conversion == "PRICE_UNITS_DIV_ENTRY_PRICE_X_10000_TO_BPS"
            and receipt_price is not None
            and receipt_price > 0.0
        ):
            recomputed_atr = raw_value / receipt_price * 10000.0
    receipt_atr = _finite_float(receipt.get("atr_bps"))
    row_atr = _finite_float(entry_atr_bps)
    if (
        recomputed_atr is None
        or receipt_atr is None
        or receipt_atr <= 0.0
        or abs(recomputed_atr - receipt_atr) > max(1e-12, abs(receipt_atr) * 1e-12)
    ):
        reasons.append("PAPER_LIQUIDATION_ATR_VALUE_RECOMPUTATION_FAILED")
    if (
        row_atr is None
        or row_atr <= 0.0
        or receipt_atr is None
        or abs(row_atr - receipt_atr) > max(1e-12, abs(receipt_atr) * 1e-12)
    ):
        reasons.append("PAPER_LIQUIDATION_ATR_ALLOCATION_INPUT_MISMATCH")
    unique_reasons = sorted(set(reasons))
    return (receipt_atr if not unique_reasons else None), unique_reasons


def _maintenance_margin_contract(
    row: AllocationInput,
    *,
    mode: str,
) -> tuple[Any, dict[str, Any]]:
    """Resolve maintenance evidence without inventing paper liquidation math.

    The live fallback deliberately preserves pre-existing behavior. Removing it
    would alter an exchange-touching path and therefore needs separate operator
    approval. Paper and counterfactual paths have no such compatibility escape.
    """
    raw_value = row.maintenance_margin_rate
    if mode != "paper":
        # This branch is an exact compatibility shim for the separately
        # operator-gated LIVE path.  Historically, omission meant the
        # AllocationInput default of 0.005, while every explicitly supplied
        # object flowed unchanged into the legacy liquidation math (including
        # its existing results and exceptions).  Do not parse, coerce, or
        # validate an explicit LIVE value here.
        if raw_value is MAINTENANCE_MARGIN_INPUT_UNSET:
            return LIVE_LEGACY_MAINTENANCE_MARGIN_RATE, {}
        return raw_value, {}

    # Finite/range validation belongs exclusively to PAPER.  PAPER must have
    # positive symbol/tier evidence and may not inherit LIVE's compatibility
    # behavior.
    supplied = _finite_float(raw_value)
    if supplied is not None and 0.0 < supplied < 1.0:
        return supplied, {
            "maintenance_margin_evidence_status": "SUPPLIED_FINITE",
            "maintenance_margin_rate_supplied": supplied,
            "maintenance_margin_rate_effective": supplied,
            "maintenance_margin_rate_live_compatibility_defaulted": False,
        }
    return None, {
        "maintenance_margin_evidence_status": "MISSING_OR_INVALID_FAIL_CLOSED",
        "maintenance_margin_rate_supplied": row.maintenance_margin_rate,
        "maintenance_margin_rate_effective": None,
        "maintenance_margin_rate_live_compatibility_defaulted": False,
    }


def _paper_input_rejection_reasons(row: AllocationInput, envelope: RiskEnvelope) -> list[str]:
    """Validate finite evidence before adaptive math can turn NaN into a pass."""
    reasons: list[str] = []
    required_fields = (
        "price",
        "equity",
        "available_margin",
        "wallet_balance",
        "confidence_calibrated",
        "expected_move_after_cost_bps",
        "market_state_integrity_score",
        "volatility_bps",
        "liquidity_score",
        "spread_bps",
        "slippage_bps",
        "fee_bps",
        "expected_funding_bps",
        "hedge_budget_pct_of_risk",
        "drawdown_bps",
        "symbol_exposure_usdt",
        "total_exposure_usdt",
        "correlation_exposure_pct",
        "regime_score",
        "paper_risk_budget_fraction",
        "paper_quality_sizing_weight",
    )
    optional_fields = (
        "stop_distance_bps",
        "min_qty",
        "step_size",
        "max_qty",
        "min_notional",
        "ppo_action_probability",
        "masa_confidence",
        "entry_atr_bps",
        "exit_overshoot_premium_bps",
    )
    for field in required_fields:
        if _finite_float(getattr(row, field)) is None:
            reasons.append(f"NONFINITE_{field.upper()}")
    for field in optional_fields:
        value = getattr(row, field)
        if value is not None and _finite_float(value) is None:
            reasons.append(f"NONFINITE_{field.upper()}")
    confidence = _finite_float(row.confidence_calibrated)
    if confidence is None or not 0.0 <= confidence <= 1.0:
        reasons.append("CONFIDENCE_OUTSIDE_UNIT_INTERVAL")
    paper_risk_budget_fraction = _finite_float(row.paper_risk_budget_fraction)
    if paper_risk_budget_fraction is None or not 0.0 < paper_risk_budget_fraction <= 1.0:
        reasons.append("PAPER_RISK_BUDGET_FRACTION_OUTSIDE_OPEN_CLOSED_UNIT_INTERVAL")
    paper_quality_sizing_weight = _finite_float(row.paper_quality_sizing_weight)
    if paper_quality_sizing_weight is None or not 0.0 < paper_quality_sizing_weight <= 1.0:
        reasons.append("PAPER_QUALITY_SIZING_WEIGHT_OUTSIDE_OPEN_CLOSED_UNIT_INTERVAL")
    min_qty = _finite_float(row.min_qty)
    max_qty = _finite_float(row.max_qty)
    if max_qty is not None and max_qty <= 0.0:
        reasons.append("MAX_QTY_NOT_POSITIVE")
    if min_qty is not None and max_qty is not None and min_qty > max_qty:
        reasons.append("MIN_QTY_EXCEEDS_MAX_QTY")
    permitted_values = row.permitted_leverage_values
    if not isinstance(permitted_values, list | tuple) or not permitted_values:
        reasons.append("PERMITTED_LEVERAGE_VALUES_EMPTY")
    elif any(_finite_float(value) is None for value in permitted_values):
        reasons.append("PERMITTED_LEVERAGE_VALUES_NONFINITE")
    envelope_fields = (
        "max_total_portfolio_risk_pct",
        "max_single_symbol_exposure_pct",
        "max_daily_drawdown_pct",
        "max_loss_per_trade_pct",
        "min_available_margin_buffer_pct",
        "max_correlation_exposure_pct",
        "min_liquidation_buffer_bps",
        "max_effective_leverage",
        "tail_loss_multiplier",
    )
    for field in envelope_fields:
        if _finite_float(getattr(envelope, field)) is None:
            reasons.append(f"NONFINITE_ENVELOPE_{field.upper()}")
    if (
        envelope.emergency_absolute_cap_usdt is not None
        and _finite_float(envelope.emergency_absolute_cap_usdt) is None
    ):
        reasons.append("NONFINITE_ENVELOPE_EMERGENCY_ABSOLUTE_CAP_USDT")
    return sorted(set(reasons))


def _safe_block_row(row: AllocationInput) -> AllocationInput:
    """Produce serialization-safe values only for a zero-sized blocked result."""

    def finite_or_zero(value: Any) -> float:
        parsed = _finite_float(value)
        return parsed if parsed is not None else 0.0

    def finite_optional(value: Any) -> float | None:
        return _finite_float(value) if value is not None else None

    permitted_values = (
        row.permitted_leverage_values
        if isinstance(row.permitted_leverage_values, list | tuple)
        else ()
    )
    permitted = tuple(
        parsed
        for value in permitted_values
        if (parsed := _finite_float(value)) is not None and parsed >= 1.0
    ) or (1.0,)
    paper_quality = _finite_float(row.paper_quality_sizing_weight)
    if paper_quality is None or not 0.0 < paper_quality <= 1.0:
        paper_quality = 1.0
    return replace(
        row,
        price=finite_or_zero(row.price),
        equity=finite_or_zero(row.equity),
        available_margin=finite_or_zero(row.available_margin),
        wallet_balance=finite_or_zero(row.wallet_balance),
        confidence_calibrated=finite_or_zero(row.confidence_calibrated),
        expected_move_after_cost_bps=finite_or_zero(row.expected_move_after_cost_bps),
        market_state_integrity_score=finite_or_zero(row.market_state_integrity_score),
        volatility_bps=finite_or_zero(row.volatility_bps),
        liquidity_score=finite_or_zero(row.liquidity_score),
        spread_bps=finite_or_zero(row.spread_bps),
        slippage_bps=finite_or_zero(row.slippage_bps),
        fee_bps=finite_or_zero(row.fee_bps),
        expected_funding_bps=finite_or_zero(row.expected_funding_bps),
        stop_distance_bps=finite_optional(row.stop_distance_bps),
        maintenance_margin_rate=finite_optional(row.maintenance_margin_rate),
        permitted_leverage_values=permitted,
        hedge_budget_pct_of_risk=finite_or_zero(row.hedge_budget_pct_of_risk),
        drawdown_bps=finite_or_zero(row.drawdown_bps),
        symbol_exposure_usdt=finite_or_zero(row.symbol_exposure_usdt),
        total_exposure_usdt=finite_or_zero(row.total_exposure_usdt),
        correlation_exposure_pct=finite_or_zero(row.correlation_exposure_pct),
        regime_score=finite_or_zero(row.regime_score),
        min_qty=finite_optional(row.min_qty),
        step_size=finite_optional(row.step_size),
        max_qty=finite_optional(row.max_qty),
        min_notional=finite_optional(row.min_notional),
        ppo_action_probability=finite_optional(row.ppo_action_probability),
        masa_confidence=finite_optional(row.masa_confidence),
        entry_atr_bps=finite_optional(row.entry_atr_bps),
        exit_overshoot_premium_bps=finite_optional(row.exit_overshoot_premium_bps),
        paper_risk_budget_fraction=(finite_or_zero(row.paper_risk_budget_fraction) or 1.0),
        paper_quality_sizing_weight=paper_quality,
    )


def _safe_block_envelope(envelope: RiskEnvelope) -> RiskEnvelope:
    """Use conservative finite values only to serialize an already blocked row."""
    base = RiskEnvelope()

    def finite_or(field: str, fallback: float) -> float:
        parsed = _finite_float(getattr(envelope, field))
        return parsed if parsed is not None else fallback

    emergency = _finite_float(envelope.emergency_absolute_cap_usdt)
    return replace(
        envelope,
        max_total_portfolio_risk_pct=finite_or(
            "max_total_portfolio_risk_pct", base.max_total_portfolio_risk_pct
        ),
        max_single_symbol_exposure_pct=finite_or(
            "max_single_symbol_exposure_pct", base.max_single_symbol_exposure_pct
        ),
        max_daily_drawdown_pct=finite_or("max_daily_drawdown_pct", base.max_daily_drawdown_pct),
        max_loss_per_trade_pct=finite_or("max_loss_per_trade_pct", base.max_loss_per_trade_pct),
        min_available_margin_buffer_pct=finite_or(
            "min_available_margin_buffer_pct", base.min_available_margin_buffer_pct
        ),
        max_correlation_exposure_pct=finite_or(
            "max_correlation_exposure_pct", base.max_correlation_exposure_pct
        ),
        min_liquidation_buffer_bps=finite_or(
            "min_liquidation_buffer_bps", base.min_liquidation_buffer_bps
        ),
        max_effective_leverage=finite_or("max_effective_leverage", base.max_effective_leverage),
        tail_loss_multiplier=finite_or("tail_loss_multiplier", base.tail_loss_multiplier),
        emergency_absolute_cap_usdt=emergency,
    )


ALLOCATION_INPUT_SCHEMA_VERSION = "adaptive_capital_allocation_input_v1"
ALLOCATION_INPUT_HASH_ALGORITHM = "sha256(canonical-json-v1)"


def allocation_input_material(
    row: AllocationInput,
    envelope: RiskEnvelope,
    *,
    mode: str,
) -> dict[str, Any]:
    """Return every economic input consumed by one allocation decision."""

    allocation_input = asdict(row)
    if mode != "paper":
        # This paper-only input is intentionally absent from the live material
        # so adding it cannot change a live allocation hash or payload.
        allocation_input.pop("paper_quality_sizing_weight", None)
    return {
        "schema_version": ALLOCATION_INPUT_SCHEMA_VERSION,
        "mode": str(mode),
        "allocation_input": allocation_input,
        "risk_envelope": asdict(envelope),
    }


def canonical_allocation_input_hash(material: dict[str, Any]) -> str:
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _live_compat_allocation_input_hash(material: dict[str, Any]) -> str:
    """Hash LIVE telemetry without tightening its legacy numeric surface."""

    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        # Legacy LIVE accepted IEEE NaN/infinities far enough to return its
        # historical result payloads.  Strict PAPER hashing remains unchanged.
        allow_nan=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _allocation_id(
    row: AllocationInput,
    mode: str,
    envelope: RiskEnvelope,
) -> str:
    if mode == "paper":
        # Paper identity binds every economic input and every adaptive envelope
        # field.  Truncation is only a readable identifier; the full digest is
        # published separately as ``allocation_input_hash``.
        digest = canonical_allocation_input_hash(
            allocation_input_material(row, envelope, mode=mode)
        )
        return "alloc_" + digest[:24]
    identity_parts = [
        mode,
        row.symbol,
        row.timeframe,
        row.action,
        str(row.lineage_ids.get("prediction_id") or ""),
        f"{row.confidence_calibrated:.8f}",
        f"{row.expected_move_after_cost_bps:.8f}",
    ]
    raw = "|".join(identity_parts)
    return "alloc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _paper_economic_edge_after_cost_bps(row: AllocationInput, *, mode: str) -> float:
    """Return positive economic edge for paper sizing without changing live behavior."""
    if mode != "paper":
        return max(0.0, float(row.expected_move_after_cost_bps or 0.0))
    action = str(row.action or "").strip().lower()
    signed_edge = float(row.expected_move_after_cost_bps or 0.0)
    if action == "short":
        if signed_edge < 0.0:
            return -signed_edge
        return 0.0
    if action == "long":
        return max(0.0, signed_edge)
    return 0.0


def _paper_sizing_row(row: AllocationInput, *, mode: str) -> AllocationInput:
    edge = _paper_economic_edge_after_cost_bps(row, mode=mode)
    if mode != "paper" or edge == row.expected_move_after_cost_bps:
        return row
    return replace(row, expected_move_after_cost_bps=edge)


def _adaptive_hedge_budget_selection(
    row: AllocationInput, envelope: RiskEnvelope
) -> tuple[float, dict[str, float | str]]:
    operator_floor = _clamp(
        float(row.hedge_budget_pct_of_risk or 0.0), 0.0, MAX_DYNAMIC_HEDGE_BUDGET_PCT_OF_RISK
    )
    edge = max(0.0, float(row.expected_move_after_cost_bps or 0.0))
    cost_drag = (
        max(0.0, row.spread_bps)
        + max(0.0, row.slippage_bps)
        + max(0.0, row.fee_bps)
        + abs(row.expected_funding_bps)
    )
    correlation_pressure = _clamp(
        max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
        0.0,
        1.0,
    )
    drawdown_pressure = _clamp(
        max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
        0.0,
        1.0,
    )
    volatility_pressure = _clamp((max(0.0, row.volatility_bps) - 80.0) / 240.0, 0.0, 1.0)
    cost_pressure = _clamp(cost_drag / max(1.0, edge), 0.0, 1.0) if edge > 0.0 else 1.0
    risk_pressure = max(
        correlation_pressure, drawdown_pressure, volatility_pressure * 0.5, cost_pressure * 0.5
    )
    dynamic_pct = (
        0.0
        if risk_pressure < 0.25
        else _clamp(
            0.05 + (0.30 * risk_pressure),
            0.0,
            MAX_DYNAMIC_HEDGE_BUDGET_PCT_OF_RISK,
        )
    )
    selected_pct = max(operator_floor, dynamic_pct)
    reason = (
        "operator_hedge_budget_floor"
        if operator_floor >= dynamic_pct and operator_floor > 0.0
        else (
            "correlation_drawdown_volatility_cost_pressure"
            if selected_pct > 0.0
            else "hedge_budget_not_required_for_current_risk"
        )
    )
    return selected_pct, {
        "operator_hedge_budget_pct_of_risk": round(operator_floor, 8),
        "selected_hedge_budget_pct_of_risk": round(selected_pct, 8),
        "hedge_budget_selection_reason": reason,
        "hedge_correlation_pressure": round(correlation_pressure, 8),
        "hedge_drawdown_pressure": round(drawdown_pressure, 8),
        "hedge_volatility_pressure": round(volatility_pressure, 8),
        "hedge_cost_pressure": round(cost_pressure, 8),
        "hedge_risk_pressure": round(risk_pressure, 8),
    }


_PAPER_STRICT_EDGE_ROW_ID_FIELDS = {
    "position_id",
    "outcome_label_id",
    "close_id",
    "trade_id",
    "fill_id",
    "ledger_row_id",
    "allocation_id",
    "intent_id",
}
_PAPER_STRICT_EDGE_BPS_FIELDS = {
    "realized_net_pnl_bps",
    "realized_pnl_bps",
    "paper_exit_pnl_bps",
    "net_pnl_bps",
    "pnl_bps",
}
_PAPER_STRICT_EDGE_USD_FIELDS = {
    "realized_net_pnl_usd",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "net_pnl_usd",
    "pnl_usd",
}
_PAPER_NON_STRICT_GOVERNANCE_TIERS = {
    "A_PLUS_BOOTSTRAP_REDUCED_SIZE_PAPER_ONLY",
    "PAPER_RISK_CONTROLLER_EXPLORATION",
}
_PAPER_PROMOTED_CHECKPOINT_SOURCE_FIELDS = {
    "schema_version",
    "generated_utc",
    "status_payload_expires_at",
    "status_publication_status",
    "cycle_id",
    "process_instance_id",
    "status_publication",
    "current_cycle_learning_envelope_identity",
    "runtime_readiness_status",
    "trainer_learning_ready",
    "checkpoint_id",
    "candidate_policy_fingerprint",
    "checkpoint_promotion_allowed",
    "checkpoint_promotion_reason",
    "mandatory_pit_edge_gate_passed",
    "validation_split_pit_safe",
    "validation_policy_edge_status",
    "validation_policy_edge_after_cost_bps",
    "validation_policy_edge_lower_confidence_bound_bps",
    "validation_policy_edge_rows_evaluated",
    "model_serving_allowed",
    "model_serving_source",
    "current_cycle_verified_serving_checkpoint_evidence",
}


def _paper_promoted_checkpoint_replay_rejection_reasons(
    checkpoint_value: Any,
    *,
    decision_time: Any,
) -> list[str]:
    """Independently replay the promoted-checkpoint source at allocation."""

    checkpoint = dict(checkpoint_value) if isinstance(checkpoint_value, Mapping) else {}
    source_value = checkpoint.get("source_material")
    source = dict(source_value) if isinstance(source_value, Mapping) else {}
    reasons: list[str] = []
    if (
        checkpoint.get("schema_version") != "paper_promoted_checkpoint_growth_receipt_v1"
        or checkpoint.get("source") != "redis:v2:trainer:hybrid_cuda:status"
        or checkpoint.get("paper_only") is not True
        or checkpoint.get("routes_to_live") is not False
        or checkpoint.get("places_real_order") is not False
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_RECEIPT_CONTRACT_INVALID")
    if set(source) != _PAPER_PROMOTED_CHECKPOINT_SOURCE_FIELDS or checkpoint.get(
        "source_material_hash"
    ) != _canonical_sha256(source):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_SOURCE_MATERIAL_INVALID")

    checkpoint_id = str(checkpoint.get("candidate_checkpoint_id") or "").strip()
    checkpoint_id_source = str(checkpoint.get("candidate_checkpoint_id_source") or "").strip()
    if (
        not checkpoint_id
        or checkpoint_id_source
        not in {
            "trust_envelope.checkpoint_id",
            "signal.checkpoint_id",
            "prediction.checkpoint_id",
        }
        or source.get("checkpoint_id") != checkpoint_id
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_LINEAGE_INVALID")

    decision = _aware_utc(decision_time)
    receipt_decision = _aware_utc(checkpoint.get("decision_time"))
    generated = _aware_utc(source.get("generated_utc"))
    expires = _aware_utc(source.get("status_payload_expires_at"))
    if decision is None or receipt_decision != decision:
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_DECISION_TIME_INVALID")
    if (
        generated is None
        or expires is None
        or decision is None
        or generated > decision
        or expires < decision
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_STATUS_TIME_INVALID")

    cycle_id = str(source.get("cycle_id") or "").strip()
    process_instance_id = str(source.get("process_instance_id") or "").strip()
    publication_value = source.get("status_publication")
    publication = dict(publication_value) if isinstance(publication_value, Mapping) else {}
    publication_components = publication.get("component_results")
    if (
        source.get("schema_version") != "v2_native_rl_masa_ppo_cuda_trainer_status_v1"
        or source.get("status_publication_status") != "ACTIVE"
        or not cycle_id
        or not process_instance_id
        or publication.get("schema_version") != "v2_trainer_expiring_status_publication_v1"
        or publication.get("publication_complete") is not True
        or publication.get("cycle_id") != cycle_id
        or publication.get("process_instance_id") != process_instance_id
        or publication.get("generated_utc") != source.get("generated_utc")
        or publication.get("expires_at") != source.get("status_payload_expires_at")
        or not isinstance(publication_components, Mapping)
        or set(publication_components)
        != {
            "blocked_staging_status",
            "heartbeat",
            "metrics",
            "feature_schema_status",
            "status",
        }
        or not all(value is True for value in publication_components.values())
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_PUBLICATION_INVALID")

    fingerprint = source.get("candidate_policy_fingerprint")
    identity_value = source.get("current_cycle_learning_envelope_identity")
    identity = dict(identity_value) if isinstance(identity_value, Mapping) else {}
    if (
        identity.get("cycle_id") != cycle_id
        or identity.get("process_instance_id") != process_instance_id
        or identity.get("checkpoint_id") != checkpoint_id
        or identity.get("candidate_policy_fingerprint") != fingerprint
        or not _valid_sha256(identity.get("envelope_sha256"))
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_ENVELOPE_IDENTITY_INVALID")

    edge_lcb = _finite_float(source.get("validation_policy_edge_lower_confidence_bound_bps"))
    edge_rows = _finite_float(source.get("validation_policy_edge_rows_evaluated"))
    if (
        source.get("runtime_readiness_status") != "READY"
        or source.get("trainer_learning_ready") is not True
        or source.get("checkpoint_promotion_allowed") is not True
        or source.get("checkpoint_promotion_reason")
        != "PIT_EDGE_CONFIDENCE_PARETO_SERVING_PROMOTION_PASS"
        or source.get("mandatory_pit_edge_gate_passed") is not True
        or source.get("validation_split_pit_safe") is not True
        or source.get("validation_policy_edge_status") != "VALID"
        or edge_lcb is None
        or edge_lcb <= 0.0
        or edge_rows is None
        or edge_rows < 1.0
        or not edge_rows.is_integer()
        or source.get("model_serving_allowed") is not True
        or source.get("model_serving_source") != "VERIFIED_PROMOTED_SERVING_CHECKPOINT"
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_PROMOTION_INVALID")

    verified_value = source.get("current_cycle_verified_serving_checkpoint_evidence")
    verified = dict(verified_value) if isinstance(verified_value, Mapping) else {}
    verified_generated = _aware_utc(verified.get("generated_utc"))
    if (
        verified.get("checkpoint_artifact_verified") is not True
        or verified.get("causal_order_verified") is not True
        or verified.get("lineage_kind") != "VERIFIED_SERVING_POLICY"
        or verified.get("checkpoint_id") != checkpoint_id
        or verified.get("model_parameter_fingerprint") != fingerprint
        or not _valid_sha256(fingerprint)
        or not _valid_sha256(verified.get("weight_file_sha256"))
        or not _valid_sha256(verified.get("parent_policy_fingerprint"))
        or verified.get("ledger_disposition") != "SERVING_PROMOTED"
        or verified.get("exact_optimizer_contract_durable") is not True
        or verified.get("manager_semantic_verification_recomputed_this_cycle") is not True
        or verified_generated is None
        or generated is None
        or verified_generated > generated
    ):
        reasons.append("PAPER_CANDIDATE_CHECKPOINT_ARTIFACT_INVALID")
    return sorted(set(reasons))


def _paper_strict_selector_material_is_valid(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    selector = dict(value)
    for field in (
        "paper_opportunity_tier",
        "source_tier",
        "tier",
        "exploration_tier",
        "paper_exploration_tier",
        "paper_fill_allowed_source",
        "preemptive_decision",
    ):
        marker = str(selector.get(field) or "").strip().upper()
        if any(tier in marker for tier in _PAPER_NON_STRICT_GOVERNANCE_TIERS):
            return False
    if any(
        selector.get(field) is True
        for field in (
            "reconstructed",
            "trust_reconstructed",
            "reconstructed_from_archive",
            "reconstructed_from_artifacts",
            "materialization_queue_id_reconstructed_from_candidate_id",
        )
    ):
        return False
    return not (
        selector.get("counts_as_strict_preemptive_evidence") is False
        or selector.get("counts_as_a_plus_evidence") is False
    )


def _paper_strict_edge_cohort_replay_rejection_reasons(
    cohort_value: Any,
    *,
    edge_source: Mapping[str, Any],
    decision_time: Any,
) -> list[str]:
    """Recompute all strict-cohort outputs at the allocator trust boundary."""

    cohort = dict(cohort_value) if isinstance(cohort_value, Mapping) else {}
    reasons: list[str] = []
    if (
        cohort.get("schema_version") != "paper_strict_after_cost_edge_cohort_material_v1"
        or cohort.get("strict_governance_selector") != "STRICT_TIER_EXCLUSION_ACTIVE"
    ):
        reasons.append("PAPER_STRICT_EDGE_COHORT_SCHEMA_INVALID")
    rows_value = cohort.get("rows")
    rows = list(rows_value) if isinstance(rows_value, list) else []
    if not rows:
        reasons.append("PAPER_STRICT_EDGE_COHORT_EMPTY")
    decision = _aware_utc(decision_time)
    if decision is None:
        reasons.append("PAPER_STRICT_EDGE_DECISION_TIME_INVALID")
    row_ids: list[str] = []
    realized: list[float] = []
    available_times: list[datetime] = []
    observed_order: list[tuple[str, str]] = []
    for index, row_value in enumerate(rows):
        if not isinstance(row_value, Mapping):
            reasons.append(f"PAPER_STRICT_EDGE_ROW_INVALID:{index}")
            continue
        row = dict(row_value)
        row_id = str(row.get("row_id") or "").strip()
        if not row_id or row.get("row_id_field") not in _PAPER_STRICT_EDGE_ROW_ID_FIELDS:
            reasons.append(f"PAPER_STRICT_EDGE_ROW_ID_INVALID:{index}")
        else:
            row_ids.append(row_id)
        bps = _finite_float(row.get("realized_after_cost_bps"))
        if (
            bps is None
            or row.get("realized_after_cost_bps_field") not in _PAPER_STRICT_EDGE_BPS_FIELDS
        ):
            reasons.append(f"PAPER_STRICT_EDGE_BPS_INVALID:{index}")
        else:
            realized.append(bps)
        usd = row.get("realized_after_cost_usd")
        if usd is not None and (
            _finite_float(usd) is None
            or row.get("realized_after_cost_usd_field") not in _PAPER_STRICT_EDGE_USD_FIELDS
        ):
            reasons.append(f"PAPER_STRICT_EDGE_USD_INVALID:{index}")
        if not _paper_strict_selector_material_is_valid(row.get("selector_material")):
            reasons.append(f"PAPER_STRICT_EDGE_SELECTOR_INVALID:{index}")
        event_time = _aware_utc(row.get("event_time"))
        available_at = _aware_utc(row.get("available_at"))
        close_time = _aware_utc(row.get("close_time"))
        if event_time is None or available_at is None or close_time is None:
            reasons.append(f"PAPER_STRICT_EDGE_TIME_INVALID:{index}")
        else:
            available_times.append(available_at)
            if event_time > available_at or close_time > available_at:
                reasons.append(f"PAPER_STRICT_EDGE_TIME_ORDER_INVALID:{index}")
            if decision is not None and available_at > decision:
                reasons.append(f"PAPER_STRICT_EDGE_FUTURE_ROW:{index}")
        observed_order.append((str(row.get("available_at") or ""), str(row.get("row_id") or "")))
    if len(row_ids) != len(set(row_ids)):
        reasons.append("PAPER_STRICT_EDGE_DUPLICATE_ROW_ID")
    if observed_order != sorted(observed_order):
        reasons.append("PAPER_STRICT_EDGE_ROW_ORDER_INVALID")
    if len(realized) != len(rows):
        reasons.append("PAPER_STRICT_EDGE_REALIZED_COUNT_MISMATCH")

    count = len(realized)
    mean = math.fsum(realized) / count if count else None
    if count == 0:
        lower_bound = None
    elif count == 1:
        lower_bound = mean
    else:
        assert mean is not None
        variance = math.fsum((item - mean) ** 2 for item in realized) / count
        lower_bound = mean - 1.959963984540054 * (math.sqrt(variance) / math.sqrt(count))
    scale = math.fsum(abs(item) for item in realized) / count if count else None
    resolution = (
        math.ulp(scale) if scale is not None and math.isfinite(scale) and scale > 0.0 else None
    )
    profit = math.fsum(item for item in realized if item > 0.0)
    loss = abs(math.fsum(item for item in realized if item < 0.0))
    if loss > 0.0:
        numeric_profit_factor = profit / loss
        profit_factor: float | str | None = numeric_profit_factor
        profit_factor_numeric: float | None = numeric_profit_factor
        profit_factor_is_infinite = False
    elif profit > 0.0:
        profit_factor = "inf"
        profit_factor_numeric = None
        profit_factor_is_infinite = True
    else:
        profit_factor = None
        profit_factor_numeric = None
        profit_factor_is_infinite = False
    maximum_available = max(available_times) if available_times else None
    expected = {
        "after_cost_edge_mean_bps": mean,
        "after_cost_edge_lower_bound_bps": lower_bound,
        "after_cost_edge_scale_bps": scale,
        "after_cost_edge_resolution_bps": resolution,
        "after_cost_edge_evidence_count": count,
        "after_cost_edge_scale_evidence_count": count,
        "strict_after_cost_edge_win_rate": (
            sum(1 for item in realized if item > 0.0) / count if count else None
        ),
        "strict_after_cost_edge_profit_factor": profit_factor,
        "strict_after_cost_edge_profit_factor_numeric": profit_factor_numeric,
        "strict_after_cost_edge_profit_factor_is_infinite": (profit_factor_is_infinite),
        "after_cost_edge_available_at": (
            _utc_iso(maximum_available) if maximum_available is not None else None
        ),
    }
    for field, expected_value in expected.items():
        if edge_source.get(field) != expected_value:
            reasons.append(f"PAPER_STRICT_EDGE_REPLAY_MISMATCH:{field}")
    if edge_source.get("governed_closed_rows") != count:
        reasons.append("PAPER_STRICT_EDGE_GOVERNED_COUNT_MISMATCH")
    return sorted(set(reasons))


def _first_finite_field(
    sources: tuple[tuple[str, Mapping[str, Any]], ...],
    fields: tuple[str, ...],
) -> tuple[float | None, str | None]:
    for source_name, source in sources:
        for field in fields:
            value = _finite_float(source.get(field))
            if value is not None:
                return value, f"{source_name}.{field}"
    return None, None


def _paper_context_source_replay_rejection_reasons(
    liquidity_value: Any,
    regime_value: Any,
) -> list[str]:
    """Replay exact allocator liquidity/regime materials without CLI trust."""

    reasons: list[str] = []
    liquidity = dict(liquidity_value) if isinstance(liquidity_value, Mapping) else {}
    liquidity_inputs_value = liquidity.get("derivation_inputs")
    liquidity_inputs = (
        dict(liquidity_inputs_value) if isinstance(liquidity_inputs_value, Mapping) else {}
    )
    if (
        liquidity.get("schema_version") != "paper_allocator_liquidity_source_material_v1"
        or set(liquidity_inputs)
        != {
            "signal",
            "prediction",
            "features",
            "market_microstructure",
            "spread_bps_argument",
        }
        or not all(
            isinstance(liquidity_inputs.get(field), Mapping)
            for field in (
                "signal",
                "prediction",
                "features",
                "market_microstructure",
            )
        )
    ):
        reasons.append("PAPER_LIQUIDITY_SOURCE_MATERIAL_INVALID")
    else:
        microstructure = dict(liquidity_inputs["market_microstructure"])
        explicit, explicit_source = _first_finite_field(
            (("market_microstructure", microstructure),),
            (
                "liquidity_score",
                "market_liquidity_score",
                "depth_liquidity_score",
            ),
        )
        if explicit is not None:
            explicit = explicit / 100.0 if explicit > 1.0 else explicit
            base_score = _clamp(explicit, 0.0, 1.0)
            base_source = explicit_source or "explicit_liquidity_score"
            base_reason = (
                "EXPLICIT_LIQUIDITY_SCORE"
                if base_score > 0.0
                else "FAIL_CLOSED_NON_POSITIVE_EXPLICIT_LIQUIDITY_SCORE"
            )
        else:
            depth, depth_source = _first_finite_field(
                (("market_microstructure", microstructure),),
                (
                    "entry_orderbook_depth_usd",
                    "orderbook_depth_usd",
                    "top_of_book_depth_usd",
                    "market_depth_usd",
                    "depth_usd",
                    "available_depth_usd",
                    "one_percent_depth_usd",
                ),
            )
            if depth is None or depth <= 0.0:
                depth_score = None
            elif depth >= 250_000.0:
                depth_score = 1.0
            elif depth >= 100_000.0:
                depth_score = 0.9
            elif depth >= 50_000.0:
                depth_score = 0.8
            elif depth >= 25_000.0:
                depth_score = 0.65
            elif depth >= 10_000.0:
                depth_score = 0.5
            elif depth >= 5_000.0:
                depth_score = 0.35
            else:
                depth_score = 0.2
            orderbook_spread, _ = _first_finite_field(
                (("market_microstructure", microstructure),),
                ("bid_ask_spread_bps", "spread_bps"),
            )
            spread_score = (
                None
                if orderbook_spread is None
                else (
                    1.0
                    if abs(orderbook_spread) <= 2.0
                    else _clamp(1.0 - ((abs(orderbook_spread) - 2.0) / 48.0), 0.0, 1.0)
                )
            )
            if depth_score is not None and spread_score is not None:
                base_score = round(min(depth_score, spread_score), 8)
                base_source = f"{depth_source or 'orderbook_depth_usd'}+spread_bps"
                base_reason = "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD"
            elif depth_score is not None:
                base_score = 0.0
                base_source = depth_source or "orderbook_depth_usd"
                base_reason = "FAIL_CLOSED_PARTIAL_ORDERBOOK_LIQUIDITY_DEPTH_ONLY"
            elif spread_score is not None:
                base_score = 0.0
                base_source = "spread_bps"
                base_reason = "FAIL_CLOSED_PARTIAL_ORDERBOOK_LIQUIDITY_SPREAD_ONLY"
            else:
                base_score = 0.0
                base_source = "MISSING_AUTHORITATIVE_MARKET_LIQUIDITY_EVIDENCE"
                base_reason = "FAIL_CLOSED_NO_AUTHORITATIVE_LIQUIDITY_SCORE"
        if (
            liquidity.get("base_score") != base_score
            or liquidity.get("base_source") != base_source
            or liquidity.get("base_reason") != base_reason
        ):
            reasons.append("PAPER_LIQUIDITY_SOURCE_DERIVATION_MISMATCH")
        gate_value = liquidity.get("microstructure_gate_inputs")
        gate = dict(gate_value) if isinstance(gate_value, Mapping) else {}
        trust_raw = gate.get("microstructure_trust_score")
        minimum_raw = gate.get("microstructure_adaptive_minimum")
        trust = _finite_float(trust_raw)
        minimum = _finite_float(minimum_raw)
        action = str(gate.get("microstructure_action") or "").strip().upper()
        invalid = bool(
            (trust_raw not in (None, "") and (trust is None or not 0.0 <= trust <= 1.0))
            or trust is None
            or (minimum_raw not in (None, "") and (minimum is None or not 0.0 < minimum <= 1.0))
            or minimum is None
            or action not in {"ALLOW", "REDUCE_SIZE"}
        )
        if invalid:
            final_score = 0.0
        elif action == "REDUCE_SIZE" or (
            trust is not None and minimum is not None and trust < minimum
        ):
            final_score = min(base_score, 0.35)
        else:
            final_score = base_score
        if liquidity.get("final_score") != round(final_score, 8):
            reasons.append("PAPER_LIQUIDITY_SOURCE_FINAL_SCORE_MISMATCH")

    regime = dict(regime_value) if isinstance(regime_value, Mapping) else {}
    regime_inputs_value = regime.get("derivation_inputs")
    regime_inputs = dict(regime_inputs_value) if isinstance(regime_inputs_value, Mapping) else {}
    if (
        regime.get("schema_version") != "paper_allocator_regime_source_material_v1"
        or set(regime_inputs)
        != {"intent", "strategy_explanation", "signal", "prediction", "features"}
        or not all(isinstance(value, Mapping) for value in regime_inputs.values())
    ):
        reasons.append("PAPER_REGIME_SOURCE_MATERIAL_INVALID")
    else:
        explicit, explicit_source = _first_finite_field(
            (
                ("intent", regime_inputs["intent"]),
                ("strategy_explanation", regime_inputs["strategy_explanation"]),
            ),
            ("regime_score", "market_regime_score", "strategy_regime_score"),
        )
        if explicit is not None:
            if explicit <= 0.0:
                regime_score = 0.0
                regime_reason = "FAIL_CLOSED_INVALID_REGIME_SCORE"
            else:
                normalized = explicit / 100.0 if explicit > 2.0 else explicit
                regime_score = _clamp(normalized, 0.2, 1.25)
                regime_reason = "EXPLICIT_REGIME_SCORE"
            regime_source = explicit_source or "explicit_regime_score"
        else:
            intent_inputs = dict(regime_inputs["intent"])
            raw_labels = intent_inputs.get("strategy_regime_labels") or []
            labels = (
                [item.strip() for item in raw_labels.split(",") if item.strip()]
                if isinstance(raw_labels, str)
                else list(raw_labels)
            )
            tokens = {str(label).strip().upper() for label in labels if str(label).strip()}
            mode = (
                str(
                    intent_inputs.get("strategy_router_selected_mode")
                    or intent_inputs.get("strategy_selected_mode")
                    or ""
                )
                .strip()
                .lower()
            )
            if "NO_TRADE" in tokens or "BLOCKED" in tokens or mode == "no_trade_mode":
                regime_score, regime_reason = 0.2, "REGIME_LABEL_NO_TRADE_OR_BLOCKED"
            elif tokens & {"CHOP", "CHOPPY", "SIDEWAYS", "RANGE_BOUND", "RANGE"}:
                regime_score, regime_reason = 0.75, "REGIME_LABEL_CHOP_RANGE"
            elif tokens & {"HIGH_VOL", "HIGH_VOLATILITY", "VOLATILE", "LIQUIDATION_RISK"}:
                regime_score, regime_reason = 0.85, "REGIME_LABEL_HIGH_VOLATILITY"
            elif "MEAN_REVERSION" in tokens or "mean_reversion" in mode:
                regime_score, regime_reason = 0.9, "REGIME_LABEL_MEAN_REVERSION"
            elif tokens & {"TREND", "MOMENTUM", "BREAKOUT"} or mode in {
                "trend_following",
                "breakout",
            }:
                regime_score, regime_reason = 1.0, "REGIME_LABEL_TREND_MOMENTUM"
            else:
                regime_score, regime_reason = 0.0, "FAIL_CLOSED_NO_REGIME_SCORE"
            regime_source = (
                "strategy_router_regime_labels" if regime_score > 0.0 else "MISSING_REGIME_EVIDENCE"
            )
        if (
            regime.get("score") != regime_score
            or regime.get("source") != regime_source
            or regime.get("reason") != regime_reason
        ):
            reasons.append("PAPER_REGIME_SOURCE_DERIVATION_MISMATCH")
    return sorted(set(reasons))


def _paper_growth_envelope_authorization_rejection_reasons(
    row: AllocationInput,
    envelope: RiskEnvelope,
) -> list[str]:
    """Replay the candidate receipt before a public PAPER call may exceed 1x."""

    if float(envelope.max_effective_leverage) <= 1.0:
        return []
    reasons: list[str] = []
    receipt_value = row.lineage_ids.get(PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY)
    receipt = dict(receipt_value) if isinstance(receipt_value, Mapping) else {}
    supplied_hash = row.lineage_ids.get(PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY)
    embedded_hash = receipt.get("evidence_hash")
    receipt_material = dict(receipt)
    receipt_material.pop("evidence_hash", None)
    if (
        not receipt
        or not _valid_sha256(supplied_hash)
        or supplied_hash != embedded_hash
        or embedded_hash != _canonical_sha256(receipt_material)
    ):
        reasons.append("PAPER_GROWTH_ENVELOPE_RECEIPT_HASH_INVALID")
    if (
        receipt.get("schema_version") != "paper_dynamic_envelope_reservation_evidence_v1"
        or receipt.get("status") != "READY"
        or receipt.get("rejection_reasons") != []
        or receipt.get("paper_only") is not True
        or receipt.get("routes_to_live") is not False
        or receipt.get("places_real_order") is not False
    ):
        reasons.append("PAPER_GROWTH_ENVELOPE_RECEIPT_NOT_READY")
    limits = receipt.get("limits")
    expected_limits = asdict(envelope)
    if not isinstance(limits, Mapping) or dict(limits) != expected_limits:
        reasons.append("PAPER_GROWTH_ENVELOPE_LIMIT_BINDING_INVALID")

    calculation = receipt.get("calculation_input_material")
    if not isinstance(calculation, Mapping):
        reasons.append("PAPER_GROWTH_ENVELOPE_CALCULATION_MISSING")
        calculation = {}
    if calculation.get(
        "schema_version"
    ) != "paper_dynamic_envelope_calculation_input_v2" or receipt.get(
        "calculation_input_hash"
    ) != _canonical_sha256(calculation):
        reasons.append("PAPER_GROWTH_ENVELOPE_CALCULATION_HASH_INVALID")
    arguments = calculation.get("arguments")
    base_material = calculation.get("base_envelope")
    if not isinstance(arguments, Mapping) or not isinstance(base_material, Mapping):
        reasons.append("PAPER_GROWTH_ENVELOPE_REPLAY_INPUT_INVALID")
        arguments = {}
        base_material = {}
    if (
        arguments.get("paper_mode") is not True
        or str(arguments.get("symbol") or "").strip().upper()
        != str(row.symbol or "").strip().upper()
    ):
        reasons.append("PAPER_GROWTH_ENVELOPE_CANDIDATE_BINDING_INVALID")

    authorization = calculation.get("growth_authorization_receipt")
    if not isinstance(authorization, Mapping):
        reasons.append("PAPER_GROWTH_AUTHORIZATION_RECEIPT_MISSING")
        authorization = {}
    authorization_material = dict(authorization)
    authorization_hash = authorization_material.pop("evidence_hash", None)
    if (
        authorization.get("schema_version") != "paper_candidate_growth_authorization_receipt_v1"
        or authorization.get("symbol") != str(row.symbol or "").strip().upper()
        or authorization.get("decision_time") != arguments.get("decision_time")
        or authorization.get("status") != "READY"
        or authorization.get("rejection_reasons") != []
        or authorization.get("paper_only") is not True
        or authorization.get("routes_to_live") is not False
        or authorization.get("places_real_order") is not False
        or authorization.get("missing_or_invalid_growth_evidence_caps_leverage_at_1x") is not True
        or authorization_hash != _canonical_sha256(authorization_material)
        or calculation.get("growth_authorization_receipt_hash") != authorization_hash
    ):
        reasons.append("PAPER_GROWTH_AUTHORIZATION_RECEIPT_INVALID")
    components = authorization.get("component_receipts")
    component_hashes = authorization.get("component_receipt_hashes")
    required_components = {
        "promoted_checkpoint",
        "strict_after_cost_edge",
        "candidate_market_context",
    }
    if (
        not isinstance(components, Mapping)
        or not isinstance(component_hashes, Mapping)
        or set(components) != required_components
        or set(component_hashes) != required_components
    ):
        reasons.append("PAPER_GROWTH_AUTHORIZATION_COMPONENT_SET_INVALID")
        components = {}
        component_hashes = {}
    for name in required_components:
        component = components.get(name)
        if not isinstance(component, Mapping):
            reasons.append(f"PAPER_GROWTH_COMPONENT_MISSING:{name}")
            continue
        component_material = dict(component)
        component_hash = component_material.pop("evidence_hash", None)
        if (
            component.get("status") != "READY"
            or component.get("rejection_reasons") != []
            or component.get("paper_only") is not True
            or component.get("routes_to_live") is not False
            or component.get("places_real_order") is not False
            or component_hash != _canonical_sha256(component_material)
            or component_hashes.get(name) != component_hash
        ):
            reasons.append(f"PAPER_GROWTH_COMPONENT_INVALID:{name}")

    checkpoint = components.get("promoted_checkpoint")
    if isinstance(checkpoint, Mapping):
        try:
            reasons.extend(
                _paper_promoted_checkpoint_replay_rejection_reasons(
                    checkpoint,
                    decision_time=arguments.get("decision_time"),
                )
            )
        except Exception:  # noqa: BLE001 - untrusted receipt boundary
            reasons.append("PAPER_CANDIDATE_CHECKPOINT_REPLAY_FAILED")

    edge = components.get("strict_after_cost_edge")
    if isinstance(edge, Mapping):
        edge_source = edge.get("source_material")
        cohort = (
            edge_source.get("strict_after_cost_edge_cohort_material")
            if isinstance(edge_source, Mapping)
            else None
        )
        if (
            edge.get("schema_version") != "paper_strict_after_cost_edge_growth_receipt_v1"
            or edge.get("decision_time") != arguments.get("decision_time")
            or not isinstance(edge_source, Mapping)
            or edge.get("source_material_hash") != _canonical_sha256(edge_source)
            or not isinstance(cohort, Mapping)
            or edge_source.get("strict_after_cost_edge_cohort_material_hash")
            != _canonical_sha256(cohort)
            or edge_source.get("strict_after_cost_edge_cohort_status") != "READY"
            or edge_source.get("strict_after_cost_edge_cohort_rejection_reasons") != []
        ):
            reasons.append("PAPER_STRICT_EDGE_COHORT_BINDING_INVALID")
        elif isinstance(arguments, Mapping):
            edge_argument_bindings = {
                "win_rate": "strict_after_cost_edge_win_rate",
                "profit_factor": "strict_after_cost_edge_profit_factor_numeric",
                "closed_trade_count": "after_cost_edge_evidence_count",
                "after_cost_edge_lower_bound_bps": ("after_cost_edge_lower_bound_bps"),
                "after_cost_edge_scale_bps": "after_cost_edge_scale_bps",
                "after_cost_edge_resolution_bps": ("after_cost_edge_resolution_bps"),
                "after_cost_edge_evidence_count": ("after_cost_edge_evidence_count"),
                "after_cost_edge_evidence_source": ("after_cost_edge_evidence_source"),
                "edge_available_at": "after_cost_edge_available_at",
            }
            if (
                edge_source.get("after_cost_edge_evidence_source")
                != "STRICT_GOVERNED_CLOSED_OUTCOMES_REALIZED_AFTER_COST_PNL_BPS"
                or edge_source.get("after_cost_edge_scale_method")
                != "MEAN_ABSOLUTE_REALIZED_AFTER_COST_PNL_BPS"
                or edge_source.get("after_cost_edge_resolution_method")
                != "IEEE754_ULP_OF_EDGE_SCALE_BPS"
                or any(
                    arguments.get(argument_field) != edge_source.get(source_field)
                    for argument_field, source_field in edge_argument_bindings.items()
                )
            ):
                reasons.append("PAPER_STRICT_EDGE_ARGUMENT_BINDING_INVALID")
            try:
                reasons.extend(
                    _paper_strict_edge_cohort_replay_rejection_reasons(
                        cohort,
                        edge_source=edge_source,
                        decision_time=arguments.get("decision_time"),
                    )
                )
            except Exception:  # noqa: BLE001 - untrusted receipt boundary
                reasons.append("PAPER_STRICT_EDGE_COHORT_REPLAY_FAILED")

    context = components.get("candidate_market_context")
    if isinstance(context, Mapping):
        liquidity_material = context.get("liquidity_source_material")
        regime_material = context.get("regime_source_material")
        liquidity_hash = context.get("liquidity_source_material_hash")
        regime_hash = context.get("regime_source_material_hash")
        if (
            context.get("schema_version") != "paper_candidate_market_context_growth_receipt_v1"
            or context.get("symbol") != str(row.symbol or "").strip().upper()
            or context.get("timeframe") != str(row.timeframe or "").strip().lower()
            or context.get("candidate_confidence_calibrated") != row.confidence_calibrated
            or context.get("liquidity_score") != row.liquidity_score
            or context.get("regime_quality_score") != row.regime_score
            or context.get("decision_time") != arguments.get("decision_time")
            or not isinstance(liquidity_material, Mapping)
            or not isinstance(regime_material, Mapping)
            or liquidity_hash != _canonical_sha256(liquidity_material)
            or regime_hash != _canonical_sha256(regime_material)
            or row.lineage_ids.get(PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY)
            != liquidity_hash
            or row.lineage_ids.get(PAPER_ALLOCATOR_REGIME_SOURCE_HASH_LINEAGE_KEY) != regime_hash
            or row.lineage_ids.get(PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY)
            != liquidity_material
            or row.lineage_ids.get(PAPER_ALLOCATOR_REGIME_SOURCE_MATERIAL_LINEAGE_KEY)
            != regime_material
        ):
            reasons.append("PAPER_CANDIDATE_MARKET_CONTEXT_BINDING_INVALID")
        else:
            pit_value = context.get("point_in_time_material")
            pit = dict(pit_value) if isinstance(pit_value, Mapping) else {}
            pit_hash = context.get("point_in_time_material_hash")
            observed_value = pit.get("observed_component_times")
            observed = dict(observed_value) if isinstance(observed_value, Mapping) else {}
            availability_fields = sorted(
                str(field)
                for field in observed
                if str(field).endswith("available_at")
                and not str(field).startswith("dynamic_envelope_")
            )
            availability_times = [_aware_utc(observed.get(field)) for field in availability_fields]
            valid_availability_times = [value for value in availability_times if value is not None]
            decision = _aware_utc(arguments.get("decision_time"))
            context_available = _aware_utc(context.get("market_context_available_at"))
            if (
                not pit
                or pit.get("status") != "PASS"
                or pit.get("rejection_reasons") != []
                or pit.get("decision_time") != arguments.get("decision_time")
                or pit_hash != _canonical_sha256(pit)
                or context.get("market_context_source")
                != f"PAPER_ALLOCATOR_CANDIDATE_PIT_CONTEXT:{pit_hash}"
                or not availability_fields
                or context.get("availability_fields_used") != availability_fields
                or len(valid_availability_times) != len(availability_times)
                or decision is None
                or context_available is None
                or context_available != max(valid_availability_times)
                or context_available > decision
            ):
                reasons.append("PAPER_CANDIDATE_MARKET_CONTEXT_PIT_INVALID")
            if (
                liquidity_material.get("symbol") != str(row.symbol or "").strip().upper()
                or liquidity_material.get("timeframe") != str(row.timeframe or "").strip().lower()
                or liquidity_material.get("final_score") != context.get("liquidity_score")
                or liquidity_material.get("base_source") != context.get("liquidity_source")
                or regime_material.get("symbol") != str(row.symbol or "").strip().upper()
                or regime_material.get("timeframe") != str(row.timeframe or "").strip().lower()
                or regime_material.get("score") != context.get("regime_quality_score")
                or regime_material.get("source") != context.get("regime_source")
                or arguments.get("liquidity_score") != context.get("liquidity_score")
                or arguments.get("regime_quality_score") != context.get("regime_quality_score")
                or arguments.get("model_avg_confidence")
                != context.get("candidate_confidence_calibrated")
                or arguments.get("market_context_source") != context.get("market_context_source")
                or arguments.get("market_context_available_at")
                != context.get("market_context_available_at")
            ):
                reasons.append("PAPER_CANDIDATE_MARKET_CONTEXT_SCORE_BINDING_INVALID")
            try:
                reasons.extend(
                    _paper_context_source_replay_rejection_reasons(
                        liquidity_material,
                        regime_material,
                    )
                )
            except Exception:  # noqa: BLE001 - untrusted receipt boundary
                reasons.append("PAPER_CANDIDATE_MARKET_CONTEXT_REPLAY_FAILED")

    if not reasons:
        try:
            from .dynamic_envelope import calculate_dynamic_risk_envelope

            replayed = calculate_dynamic_risk_envelope(
                base_envelope=RiskEnvelope(**dict(base_material)),
                **dict(arguments),
            )
        except (TypeError, ValueError, KeyError):
            reasons.append("PAPER_GROWTH_ENVELOPE_SEMANTIC_REPLAY_FAILED")
        else:
            if asdict(replayed) != expected_limits:
                reasons.append("PAPER_GROWTH_ENVELOPE_SEMANTIC_REPLAY_MISMATCH")
    return sorted(set(reasons))


def _adaptive_leverage_target_selection(
    row: AllocationInput,
    envelope: RiskEnvelope,
    *,
    mode: str,
    signed_expected_market_move_after_cost_bps: float,
) -> tuple[float, dict[str, Any]]:
    cost_drag_bps = (
        max(0.0, row.spread_bps)
        + max(0.0, row.slippage_bps)
        + max(0.0, row.fee_bps)
        + abs(row.expected_funding_bps)
    )
    edge_bps = max(0.0, row.expected_move_after_cost_bps)
    correlation_pressure = _clamp(
        max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
        0.0,
        1.0,
    )
    drawdown_pressure = _clamp(
        max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
        0.0,
        1.0,
    )
    edge_cost_ratio = edge_bps / max(1.0, cost_drag_bps)
    diagnostics: dict[str, Any] = {
        "leverage_selection_mode": mode,
        "leverage_cost_drag_bps": round(cost_drag_bps, 8),
        "leverage_edge_cost_ratio": round(edge_cost_ratio, 8),
        "leverage_correlation_pressure": round(correlation_pressure, 8),
        "leverage_drawdown_pressure": round(drawdown_pressure, 8),
        "leverage_live_mutation_allowed": False,
        "leverage_sizing_economic_edge_after_cost_bps": round(edge_bps, 8),
        "leverage_signed_expected_market_move_after_cost_bps": (
            signed_expected_market_move_after_cost_bps
        ),
        "leverage_recommender_edge_semantics": (
            "SIGNED_MARKET_MOVE_LONG_POSITIVE_SHORT_NEGATIVE"
            if mode == "paper"
            else "LIVE_DYNAMIC_LEVERAGE_DISABLED"
        ),
    }
    if mode != "paper":
        diagnostics.update(
            {
                "leverage_target": 1.0,
                "leverage_selection_reason": (
                    "live_mode_requires_operator_approval_for_dynamic_leverage_change"
                ),
            }
        )
        return 1.0, diagnostics

    from v2.backend.app.services.paper_trade_management.leverage_recommendation import (  # noqa: PLC0415
        LeverageRecommendationConfig,
        recommend_leverage_for_signal,
        symbol_leverage_ceiling,
        validate_leverage_recommendation,
    )

    growth_authorization_rejection_reasons = _paper_growth_envelope_authorization_rejection_reasons(
        row, envelope
    )
    growth_authorization_required = float(envelope.max_effective_leverage) > 1.0
    liquidation_atr_evidence = row.lineage_ids.get(PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY)
    liquidation_atr_evidence_hash = row.lineage_ids.get(
        PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY
    )
    liquidation_atr_bps, liquidation_atr_rejection_reasons = (
        validate_paper_liquidation_atr_evidence(
            liquidation_atr_evidence if isinstance(liquidation_atr_evidence, Mapping) else None,
            liquidation_atr_evidence_hash,
            symbol=row.symbol,
            timeframe=row.timeframe,
            entry_atr_bps=row.entry_atr_bps,
        )
    )
    recommendation_config = LeverageRecommendationConfig()
    liquidation_safety_atr_multiple = _finite_float(
        recommendation_config.liquidation_safety_atr_multiple
    )
    liquidation_safety_config_valid = bool(
        liquidation_safety_atr_multiple is not None and liquidation_safety_atr_multiple > 0.0
    )
    recommendation = recommend_leverage_for_signal(
        symbol=row.symbol,
        timeframe=row.timeframe,
        signal_id=str(
            row.lineage_ids.get("signal_id") or row.lineage_ids.get("prediction_id") or row.symbol
        ),
        direction=row.action,
        confidence_calibrated=row.confidence_calibrated,
        expected_move_after_cost_bps=(signed_expected_market_move_after_cost_bps),
        atr_bps=liquidation_atr_bps,
        equity_usd=row.equity,
        config=recommendation_config,
    )
    if liquidation_atr_rejection_reasons or not liquidation_safety_config_valid:
        # The standalone recommender has legacy optional-ATR diagnostics.  A
        # missing receipt must not let that compatibility default appear as a
        # PAPER leverage authorization anywhere in the allocator payload.
        # Stamp the complete recommendation itself fail-closed at 1x; valid
        # receipts take the untouched exact-ATR path above.
        fail_closed_tier = (
            "LIQUIDATION_ATR_EVIDENCE_INVALID_FAIL_CLOSED_1X"
            if liquidation_atr_rejection_reasons
            else "LIQUIDATION_ATR_SAFETY_MULTIPLE_INVALID_FAIL_CLOSED_1X"
        )
        recommendation.update(
            {
                "recommended_leverage": 1,
                "adaptive_leverage_ceiling": 1,
                "liquidation_safe_leverage_ceiling": 1,
                "liquidation_distance_bps": max(
                    0.0,
                    10000.0
                    - max(
                        0.0,
                        float(recommendation_config.liquidation_fee_buffer_bps),
                    ),
                ),
                "volatility_budget_bps": None,
                "reason_tier": fail_closed_tier,
                "reason": (
                    f"{fail_closed_tier}|symbol={row.symbol}|"
                    f"tf={row.timeframe}|lev=1x|margin=isolated|"
                    "atr_authority=BLOCKED"
                ),
            }
        )
    violations = validate_leverage_recommendation(recommendation)
    raw_target = float(recommendation.get("recommended_leverage") or 1.0)
    authorized_symbol_ceiling = max(
        1.0,
        float(symbol_leverage_ceiling(row.symbol)),
    )
    envelope_cap = min(
        max(1.0, float(envelope.max_effective_leverage)),
        authorized_symbol_ceiling,
    )
    confidence_quality = _clamp(float(row.confidence_calibrated), 0.0, 1.0)
    liquidity_quality = _clamp(float(row.liquidity_score), 0.0, 1.0)
    regime_quality = _clamp(float(row.regime_score), 0.0, 1.0)
    drawdown_resilience = 1.0 - drawdown_pressure
    correlation_resilience = 1.0 - correlation_pressure
    # Expected move is already after cost. This second continuous term asks
    # whether that claimed residual is large compared with the evidence's
    # execution drag and volatility, rather than crossing a fixed bps tier.
    evidence_scale_bps = edge_bps + cost_drag_bps + max(0.0, row.volatility_bps)
    edge_market_quality = (
        edge_bps / evidence_scale_bps if edge_bps > 0.0 and evidence_scale_bps > 0.0 else 0.0
    )
    adaptive_quality = _clamp(
        confidence_quality
        * edge_market_quality
        * liquidity_quality
        * regime_quality
        * drawdown_resilience
        * correlation_resilience,
        0.0,
        1.0,
    )
    if not growth_authorization_required:
        target = 1.0
        reason = "paper_dynamic_envelope_already_caps_at_1x"
    elif growth_authorization_rejection_reasons:
        target = 1.0
        reason = "paper_growth_envelope_authorization_invalid_fail_closed_1x"
    elif liquidation_atr_rejection_reasons:
        target = 1.0
        reason = "paper_liquidation_atr_evidence_invalid_fail_closed_1x"
    elif not liquidation_safety_config_valid:
        target = 1.0
        reason = "paper_liquidation_atr_safety_multiple_invalid_fail_closed_1x"
    elif violations:
        # A recommendation-contract violation is a safety failure. Confidence
        # is evidence, never authority to override a broken invariant.
        target = 1.0
        reason = "phase8_leverage_recommendation_invariant_violation_fail_closed"
    else:
        # The supplied envelope is the realized-performance/PIT-derived hard
        # ceiling. Candidate evidence can only interpolate continuously from
        # 1x toward it; it cannot create additional leverage. The authorized
        # Phase-8 recommendation remains a second binding ceiling because it
        # carries the symbol tier and 5x-ATR liquidation-distance constraint.
        continuous_target = 1.0 + ((envelope_cap - 1.0) * adaptive_quality)
        target = min(raw_target, continuous_target)
        reason = "continuous_market_evidence_within_supplied_dynamic_envelope"
    target = _clamp(target, 1.0, envelope_cap)
    diagnostics.update(
        {
            "phase8_leverage_recommendation": recommendation,
            "phase8_leverage_recommendation_violations": violations,
            "paper_growth_envelope_authorization_status": (
                "NOT_REQUIRED_ENVELOPE_ALREADY_CAPPED_AT_1X"
                if not growth_authorization_required
                else ("READY" if not growth_authorization_rejection_reasons else "BLOCKED")
            ),
            "paper_growth_envelope_authorization_rejection_reasons": list(
                growth_authorization_rejection_reasons
            ),
            "paper_growth_envelope_authorization_receipt_sha256": (
                row.lineage_ids.get(PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY)
                if growth_authorization_required and not growth_authorization_rejection_reasons
                else None
            ),
            "paper_above_1x_growth_authorized": bool(
                not growth_authorization_rejection_reasons
                and growth_authorization_required
                and envelope_cap > 1.0
            ),
            "paper_1x_cap_classification": (
                "UNTRUSTED_OR_INCOMPLETE_GROWTH_RECEIPT_FAIL_CLOSED_1X"
                if growth_authorization_rejection_reasons
                else (
                    "ENVELOPE_ALREADY_CAPPED_AT_1X_NO_GROWTH_AUTHORITY"
                    if not growth_authorization_required
                    else "AUTHENTICATED_DYNAMIC_ENVELOPE_RESULT"
                )
            ),
            "paper_liquidation_atr_evidence_status": (
                "READY" if not liquidation_atr_rejection_reasons else "BLOCKED"
            ),
            "paper_liquidation_atr_evidence_rejection_reasons": list(
                liquidation_atr_rejection_reasons
            ),
            "paper_liquidation_atr_evidence_sha256": (
                liquidation_atr_evidence_hash if not liquidation_atr_rejection_reasons else None
            ),
            "paper_liquidation_atr_bps": liquidation_atr_bps,
            "paper_liquidation_safety_atr_multiple": (
                liquidation_safety_atr_multiple if liquidation_safety_config_valid else None
            ),
            "phase8_recommendation_uses_exact_paper_liquidation_atr": bool(
                not liquidation_atr_rejection_reasons and liquidation_atr_bps is not None
            ),
            "raw_leverage_target": round(raw_target, 8),
            "leverage_authorized_symbol_ceiling": round(
                authorized_symbol_ceiling,
                8,
            ),
            "leverage_authorized_symbol_ceiling_source": (
                "operator_authorized_symbol_leverage_ceiling"
            ),
            "leverage_dynamic_envelope_cap": round(envelope_cap, 8),
            "leverage_confidence_quality": round(confidence_quality, 8),
            "leverage_edge_market_quality": round(edge_market_quality, 8),
            "leverage_liquidity_quality": round(liquidity_quality, 8),
            "leverage_regime_quality": round(regime_quality, 8),
            "leverage_drawdown_resilience": round(drawdown_resilience, 8),
            "leverage_correlation_resilience": round(correlation_resilience, 8),
            "leverage_adaptive_quality": round(adaptive_quality, 8),
            "leverage_formula": (
                "min(phase8_recommended_leverage, "
                "1 + (min(dynamic_envelope_cap, authorized_symbol_ceiling) - 1)"
                " * adaptive_quality)"
            ),
            "leverage_target": round(target, 8),
            "leverage_selection_reason": reason,
        }
    )
    return target, diagnostics


def _paper_minimum_liquidation_buffer(
    row: AllocationInput,
    envelope: RiskEnvelope,
) -> tuple[float | None, dict[str, Any]]:
    """Return the receipt-bound five-ATR residual buffer for PAPER only."""

    from v2.backend.app.services.paper_trade_management.leverage_recommendation import (  # noqa: PLC0415
        LeverageRecommendationConfig,
    )

    evidence = row.lineage_ids.get(PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY)
    evidence_hash = row.lineage_ids.get(PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY)
    atr_bps, reasons = validate_paper_liquidation_atr_evidence(
        evidence if isinstance(evidence, Mapping) else None,
        evidence_hash,
        symbol=row.symbol,
        timeframe=row.timeframe,
        entry_atr_bps=row.entry_atr_bps,
    )
    config_multiple = _finite_float(LeverageRecommendationConfig().liquidation_safety_atr_multiple)
    if config_multiple is None or config_multiple <= 0.0:
        reasons.append("PAPER_LIQUIDATION_ATR_SAFETY_MULTIPLE_INVALID")
    envelope_buffer = _finite_float(envelope.min_liquidation_buffer_bps)
    base_buffer = _finite_float(RiskEnvelope().min_liquidation_buffer_bps)
    if envelope_buffer is None or envelope_buffer < 0.0:
        reasons.append("PAPER_LIQUIDATION_ENVELOPE_BUFFER_INVALID")
    if base_buffer is None or base_buffer <= 0.0:
        reasons.append("PAPER_LIQUIDATION_BASE_BUFFER_INVALID")
    adverse_factor: float | None = None
    if envelope_buffer is not None and base_buffer is not None and base_buffer > 0.0:
        adverse_factor = max(1.0, envelope_buffer / base_buffer)
    required_buffer: float | None = None
    if (
        not reasons
        and atr_bps is not None
        and config_multiple is not None
        and adverse_factor is not None
    ):
        required_buffer = config_multiple * atr_bps * adverse_factor
        if not math.isfinite(required_buffer) or required_buffer <= 0.0:
            reasons.append("PAPER_LIQUIDATION_REQUIRED_BUFFER_INVALID")
            required_buffer = None
    unique_reasons = sorted(set(reasons))
    return required_buffer, {
        "paper_liquidation_buffer_contract_status": ("READY" if not unique_reasons else "BLOCKED"),
        "paper_liquidation_buffer_contract_rejection_reasons": unique_reasons,
        "paper_liquidation_atr_evidence_sha256": (evidence_hash if not unique_reasons else None),
        "paper_liquidation_atr_bps": atr_bps,
        "paper_liquidation_safety_atr_multiple": (
            config_multiple if config_multiple is not None and config_multiple > 0.0 else None
        ),
        "paper_liquidation_adverse_envelope_factor": adverse_factor,
        "paper_required_liquidation_buffer_bps": required_buffer,
        "paper_required_liquidation_buffer_formula": (
            "exact_final_pit_atr_bps * configured_safety_atr_multiple * "
            "max(1, dynamic_envelope_min_buffer / base_envelope_min_buffer)"
        ),
        "paper_liquidation_buffer_is_residual_after_stop_and_cost_reserve": True,
    }


def _adaptive_margin_mode_selection(
    row: AllocationInput,
    envelope: RiskEnvelope,
    *,
    mode: str,
    leverage: float,
    liquidation_buffer_bps: float | None,
) -> tuple[str, dict[str, Any]]:
    cost_drag_bps = (
        max(0.0, row.spread_bps)
        + max(0.0, row.slippage_bps)
        + max(0.0, row.fee_bps)
        + abs(row.expected_funding_bps)
    )
    edge_bps = max(0.0, row.expected_move_after_cost_bps)
    edge_cost_ratio = edge_bps / max(1.0, cost_drag_bps)
    correlation_pressure = _clamp(
        max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
        0.0,
        1.0,
    )
    drawdown_pressure = _clamp(
        max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
        0.0,
        1.0,
    )
    if mode != "paper":
        volatility_pressure = _clamp(
            (max(0.0, row.volatility_bps) - 80.0) / 240.0,
            0.0,
            1.0,
        )
    else:
        volatility_scale = (
            edge_bps
            + cost_drag_bps
            + max(
                0.0,
                row.volatility_bps,
            )
        )
        volatility_pressure = (
            max(0.0, row.volatility_bps) / volatility_scale if volatility_scale > 0.0 else 1.0
        )
    diagnostics: dict[str, Any] = {
        "margin_mode_selection_mode": mode,
        "margin_mode_live_mutation_allowed": False,
        "margin_mode_edge_cost_ratio": round(edge_cost_ratio, 8),
        "margin_mode_correlation_pressure": round(correlation_pressure, 8),
        "margin_mode_drawdown_pressure": round(drawdown_pressure, 8),
        "margin_mode_volatility_pressure": round(volatility_pressure, 8),
        "margin_mode_liquidation_buffer_bps": (
            round(liquidation_buffer_bps, 8) if liquidation_buffer_bps is not None else None
        ),
    }
    if mode != "paper":
        diagnostics.update(
            {
                "selected_margin_mode": "isolated",
                "margin_mode_selection_reason": (
                    "live_mode_requires_operator_approval_for_margin_mode_change"
                ),
            }
        )
        return "isolated", diagnostics

    liquidation_buffer = liquidation_buffer_bps if liquidation_buffer_bps is not None else 0.0
    confidence_quality = _clamp(float(row.confidence_calibrated), 0.0, 1.0)
    liquidity_quality = _clamp(float(row.liquidity_score), 0.0, 1.0)
    regime_quality = _clamp(float(row.regime_score), 0.0, 1.0)
    edge_market_denominator = edge_bps + cost_drag_bps + max(0.0, row.volatility_bps)
    edge_market_quality = (
        edge_bps / edge_market_denominator
        if edge_bps > 0.0 and edge_market_denominator > 0.0
        else 0.0
    )
    drawdown_resilience = 1.0 - drawdown_pressure
    correlation_resilience = 1.0 - correlation_pressure
    leverage_capacity = max(0.0, envelope.max_effective_leverage - 1.0)
    leverage_utilization = (
        _clamp((leverage - 1.0) / leverage_capacity, 0.0, 1.0) if leverage_capacity > 0.0 else 0.0
    )
    liquidation_quality = (
        liquidation_buffer / (liquidation_buffer + max(0.0, envelope.min_liquidation_buffer_bps))
        if liquidation_buffer > 0.0
        else 0.0
    )
    cross_benefit_score = (
        confidence_quality
        * edge_market_quality
        * liquidity_quality
        * regime_quality
        * drawdown_resilience
        * correlation_resilience
        * leverage_utilization
        * liquidation_quality
    )
    contagion_pressure = max(
        correlation_pressure,
        drawdown_pressure,
        volatility_pressure,
        1.0 - liquidity_quality,
        1.0 - regime_quality,
    )
    cross_net_benefit = cross_benefit_score - contagion_pressure
    diagnostics.update(
        {
            "margin_mode_cross_benefit_score": round(cross_benefit_score, 8),
            "margin_mode_contagion_pressure": round(contagion_pressure, 8),
            "margin_mode_cross_net_benefit": round(cross_net_benefit, 8),
            "margin_mode_selection_formula": "cross_benefit_score - contagion_pressure",
            "portfolio_cross_margin_liquidation_model_available": False,
        }
    )
    if leverage > 1.0 and cross_net_benefit > 0.0:
        diagnostics.update(
            {
                "selected_margin_mode": "isolated_paper_simulated",
                "margin_mode_counterfactual_candidate": "cross_paper_simulated",
                "margin_mode_counterfactual_reason": (
                    "paper_cross_margin_positive_candidate_level_modeled_net_benefit"
                ),
                "margin_mode_selection_reason": (
                    "isolated_until_account_wide_cross_margin_liquidation_model_is_proven"
                ),
            }
        )
        return "isolated_paper_simulated", diagnostics
    diagnostics.update(
        {
            "selected_margin_mode": "isolated_paper_simulated",
            "margin_mode_selection_reason": "isolated_limits_tail_contagion_for_current_risk",
        }
    )
    return "isolated_paper_simulated", diagnostics


def _block(
    row: AllocationInput,
    *,
    mode: str,
    decision: str,
    reason: str,
    envelope: RiskEnvelope,
    extra_diagnostics: dict[str, Any] | None = None,
) -> AllocationResult:
    leverage_selection = {
        "leverage_selection_mode": mode,
        "leverage_cost_drag_bps": round(
            max(0.0, row.spread_bps)
            + max(0.0, row.slippage_bps)
            + max(0.0, row.fee_bps)
            + abs(row.expected_funding_bps),
            8,
        ),
        "leverage_edge_cost_ratio": 0.0,
        "leverage_correlation_pressure": round(
            _clamp(
                max(0.0, row.correlation_exposure_pct)
                / max(1e-9, envelope.max_correlation_exposure_pct),
                0.0,
                1.0,
            ),
            8,
        ),
        "leverage_drawdown_pressure": round(
            _clamp(
                max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
                0.0,
                1.0,
            ),
            8,
        ),
        "leverage_live_mutation_allowed": False,
        "raw_leverage_target": 1.0,
        "leverage_target": 1.0,
        "selected_leverage": 1.0,
        "leverage_selection_reason": f"blocked_allocation_uses_1x_leverage:{reason}",
    }
    if extra_diagnostics:
        leverage_selection.update(extra_diagnostics)
    return _result(
        row,
        mode=mode,
        envelope=envelope,
        sizing_row=_paper_sizing_row(row, mode=mode),
        decision=decision,
        target_notional=0.0,
        target_quantity=0.0,
        risk_budget_usd=0.0,
        allocated_margin=0.0,
        leverage=1.0,
        stop_distance_bps=_stop_distance_bps(row),
        liquidation_price=None,
        liquidation_buffer_bps=None,
        final_size_reason=reason,
        risk_veto_reason=row.risk_veto_reason if row.risk_veto else reason,
        leverage_selection=leverage_selection,
        margin_mode="isolated_paper_simulated" if mode == "paper" else "isolated",
        margin_mode_selection={
            "margin_mode_selection_mode": mode,
            "margin_mode_live_mutation_allowed": False,
            "selected_margin_mode": "isolated_paper_simulated" if mode == "paper" else "isolated",
            "margin_mode_selection_reason": "blocked_allocation_uses_isolated_margin_mode",
        },
    )


def _result(
    row: AllocationInput,
    *,
    mode: str,
    envelope: RiskEnvelope,
    sizing_row: AllocationInput | None = None,
    decision: str,
    target_notional: float,
    target_quantity: float,
    risk_budget_usd: float,
    allocated_margin: float,
    leverage: float,
    stop_distance_bps: float | None,
    liquidation_price: float | None,
    liquidation_buffer_bps: float | None,
    final_size_reason: str,
    risk_veto_reason: str | None = None,
    leverage_selection: dict[str, Any] | None = None,
    margin_mode: str | None = None,
    margin_mode_selection: dict[str, Any] | None = None,
) -> AllocationResult:
    sizing_row = sizing_row or row
    input_material = allocation_input_material(row, envelope, mode=mode)
    input_hash = (
        canonical_allocation_input_hash(input_material)
        if mode == "paper"
        else _live_compat_allocation_input_hash(input_material)
    )
    maintenance_margin_rate, maintenance_diagnostics = _maintenance_margin_contract(
        row,
        mode=mode,
    )
    available_margin = row.available_margin if row.available_margin > 0 else 1.0
    hedge_budget_pct, hedge_selection = _adaptive_hedge_budget_selection(sizing_row, envelope)
    model_inputs: dict[str, Any] = {
        "mode": mode,
        "price": row.price,
        "equity": row.equity,
        "available_margin": row.available_margin,
        "wallet_balance": row.wallet_balance,
        "volatility_bps": row.volatility_bps,
        "liquidity_score": row.liquidity_score,
        "spread_bps": row.spread_bps,
        "slippage_bps": row.slippage_bps,
        "fee_bps": row.fee_bps,
        "expected_funding_bps": row.expected_funding_bps,
        "stop_distance_bps": stop_distance_bps,
        "maintenance_margin_rate": (
            maintenance_margin_rate if mode == "live" else row.maintenance_margin_rate
        ),
        "permitted_leverage_values": list(row.permitted_leverage_values),
        "hedge_budget_pct_of_risk": row.hedge_budget_pct_of_risk,
        "drawdown_bps": row.drawdown_bps,
        "symbol_exposure_usdt": row.symbol_exposure_usdt,
        "total_exposure_usdt": row.total_exposure_usdt,
        "correlation_exposure_pct": row.correlation_exposure_pct,
        "regime_score": row.regime_score,
        "signed_expected_move_after_cost_bps": row.expected_move_after_cost_bps,
        "allocator_economic_edge_after_cost_bps": _paper_economic_edge_after_cost_bps(
            row,
            mode=mode,
        ),
        "allocator_edge_sign_convention": (
            "paper_short_negative_signed_move_is_positive_economic_edge"
            if mode == "paper"
            else "live_existing_positive_edge_semantics"
        ),
        "min_qty": row.min_qty,
        "step_size": row.step_size,
        "min_notional": row.min_notional,
        "risk_envelope": {
            "max_total_portfolio_risk_pct": envelope.max_total_portfolio_risk_pct,
            "max_single_symbol_exposure_pct": envelope.max_single_symbol_exposure_pct,
            "max_daily_drawdown_pct": envelope.max_daily_drawdown_pct,
            "max_loss_per_trade_pct": envelope.max_loss_per_trade_pct,
            "min_available_margin_buffer_pct": envelope.min_available_margin_buffer_pct,
            "max_correlation_exposure_pct": envelope.max_correlation_exposure_pct,
            "min_liquidation_buffer_bps": envelope.min_liquidation_buffer_bps,
            "max_effective_leverage": envelope.max_effective_leverage,
            "tail_loss_multiplier": envelope.tail_loss_multiplier,
            "emergency_absolute_cap_usdt": envelope.emergency_absolute_cap_usdt,
        },
    }
    if mode == "paper":
        model_inputs.update(
            {
                "allocation_input_schema_version": ALLOCATION_INPUT_SCHEMA_VERSION,
                "allocation_input_hash": input_hash,
                "allocation_input_hash_algorithm": ALLOCATION_INPUT_HASH_ALGORITHM,
                "paper_risk_budget_fraction": row.paper_risk_budget_fraction,
                "max_qty": row.max_qty,
                **maintenance_diagnostics,
            }
        )
        model_inputs["paper_quality_sizing_weight"] = row.paper_quality_sizing_weight
    provider_context = (
        row.lineage_ids.get("provider_context")
        if isinstance(row.lineage_ids.get("provider_context"), dict)
        else None
    )
    if provider_context is not None:
        model_inputs["provider_context"] = provider_context
        model_inputs["optional_provider_failures_core_blocking"] = False
    model_inputs.update(hedge_selection)
    if leverage_selection:
        model_inputs.update(leverage_selection)
    if margin_mode_selection:
        model_inputs.update(margin_mode_selection)
    gross_notional = max(0.0, target_notional)
    if mode == "paper" and decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}:
        model_inputs[PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY] = (
            _paper_allocator_arithmetic_receipt(
                raw_post_step_quantity=float(target_quantity),
                input_price=float(row.price),
                raw_post_step_notional=float(gross_notional),
                selected_leverage=float(leverage),
            )
        )
    fee_bps = max(0.0, row.fee_bps)
    slippage_bps = max(0.0, row.slippage_bps)
    funding_bps = abs(row.expected_funding_bps)
    expected_fees_usd = gross_notional * fee_bps / 10000.0
    expected_slippage_usd = gross_notional * slippage_bps / 10000.0
    expected_funding_usd = gross_notional * funding_bps / 10000.0
    expected_net_pnl_usd = gross_notional * sizing_row.expected_move_after_cost_bps / 10000.0
    expected_gross_pnl_usd = (
        expected_net_pnl_usd + expected_fees_usd + expected_slippage_usd + expected_funding_usd
    )
    expected_shortfall_usd = risk_budget_usd * max(0.0, envelope.tail_loss_multiplier)
    hedge_budget_usd = risk_budget_usd * hedge_budget_pct
    modeled_stop_loss_usd = (
        None
        if stop_distance_bps is None
        else gross_notional * max(0.0, stop_distance_bps) / 10000.0
    )
    max_loss_if_stop_hit = (
        None
        if modeled_stop_loss_usd is None
        else modeled_stop_loss_usd
        + expected_fees_usd
        + expected_slippage_usd
        + expected_funding_usd
    )
    risk_reward = (
        None
        if max_loss_if_stop_hit is None or max_loss_if_stop_hit <= 0.0
        else expected_net_pnl_usd / max_loss_if_stop_hit
    )
    portfolio_exposure_after_trade = max(0.0, row.total_exposure_usdt) + gross_notional
    correlation_exposure_after_trade = _clamp(
        max(0.0, row.correlation_exposure_pct)
        + (0.0 if row.equity <= 0.0 else gross_notional / row.equity),
        0.0,
        1.0,
    )
    risk_of_ruin_contribution = _clamp(
        0.0
        if row.equity <= 0.0 or max_loss_if_stop_hit is None
        else (
            (max_loss_if_stop_hit / row.equity)
            * (
                1.0
                + max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0)
            )
            * (
                1.0
                + max(0.0, row.correlation_exposure_pct)
                / max(1e-9, envelope.max_correlation_exposure_pct)
            )
        ),
        0.0,
        1.0,
    )
    liquidation_distance_usd = (
        None
        if liquidation_buffer_bps is None
        else gross_notional * max(0.0, liquidation_buffer_bps) / 10000.0
    )
    hedge_plan = evaluate_hedge_intent(
        candidate={
            "symbol": row.symbol,
            "action": row.action,
            "side": row.action,
            "target_notional_usd": gross_notional,
            "gross_notional_usd": gross_notional,
        },
        positions=(),
        equity_usd=row.equity,
        risk_budget_usd=risk_budget_usd,
        hedge_budget_usd=hedge_budget_usd,
        max_loss_usd=max_loss_if_stop_hit,
        expected_net_pnl_usd=expected_net_pnl_usd,
        spread_bps=row.spread_bps,
        slippage_bps=row.slippage_bps,
        fee_bps=row.fee_bps,
        funding_bps=row.expected_funding_bps,
        correlation_exposure_pct=correlation_exposure_after_trade,
        liquidation_buffer_usd=liquidation_distance_usd,
        edge_remains=expected_net_pnl_usd > 0.0 and gross_notional > 0.0,
    )
    if mode == "paper" and maintenance_margin_rate is None:
        cross_margin: dict[str, Any] = {
            "recommended_margin_mode": margin_mode
            or ("isolated_paper_simulated" if mode == "paper" else "isolated"),
            "isolated_margin_required_usd": round(max(0.0, allocated_margin), 8),
            "cross_margin_stress_used_usd": 0.0,
            "cross_margin_available_buffer_usd": 0.0,
            "portfolio_liquidation_buffer_usd": 0.0,
            "worst_case_portfolio_loss_usd": round(max(0.0, max_loss_if_stop_hit or 0.0), 8),
            "maintenance_margin_estimate_usd": None,
            "margin_call_risk": "UNKNOWN_MAINTENANCE_MARGIN",
            "cross_margin_safe": False,
            "why_cross_margin_or_isolated": (
                "maintenance_margin_evidence_missing_no_liquidation_simulation"
            ),
            "exchange_margin_mode_mutation_allowed": False,
            "paper_only": mode == "paper",
            "places_real_order": False,
            "liquidation_simulation_status": "NOT_RUN_MAINTENANCE_MARGIN_MISSING",
        }
    else:
        cross_margin = simulate_cross_margin_stress(
            equity_usd=row.equity,
            available_margin_usd=row.available_margin,
            target_notional_usd=gross_notional,
            allocated_margin_usd=allocated_margin,
            recommended_leverage=leverage,
            max_loss_usd=max_loss_if_stop_hit,
            hedge_plan=hedge_plan,
            requested_margin_mode=margin_mode
            or ("isolated_paper_simulated" if mode == "paper" else "isolated"),
            maintenance_margin_rate=maintenance_margin_rate,
            expectancy_usd=expected_net_pnl_usd,
        )
        if mode == "paper":
            cross_margin["liquidation_simulation_status"] = (
                "CALCULATED_FROM_EFFECTIVE_MAINTENANCE_MARGIN"
            )
    recommended_margin_mode = str(
        cross_margin.get("recommended_margin_mode") or margin_mode or "isolated_paper_simulated"
    )
    model_inputs.update(
        {
            "hedge_engine": hedge_plan,
            "cross_margin_stress": cross_margin,
            "liquidation_distance_usd": None
            if liquidation_distance_usd is None
            else round(liquidation_distance_usd, 8),
            "expected_gross_pnl_usd": round(expected_gross_pnl_usd, 8),
            "max_loss_usd": None
            if max_loss_if_stop_hit is None
            else round(max_loss_if_stop_hit, 8),
            "stop_loss_usd": None
            if modeled_stop_loss_usd is None
            else round(modeled_stop_loss_usd, 8),
            "take_profit_usd": round(max(0.0, expected_gross_pnl_usd), 8),
        }
    )
    if mode == "paper":
        model_inputs.update(
            {
                "margin_mode_requested_before_stress": margin_mode,
                "margin_mode_effective_after_stress": recommended_margin_mode,
                "margin_mode_stress_downgraded": recommended_margin_mode != margin_mode,
                "cross_margin_simulation_scope": (
                    "CANDIDATE_AND_ACCOUNT_BALANCE_WITHOUT_OPEN_POSITION_SET"
                ),
                "cross_margin_account_wide_positions_included": False,
            }
        )
    return AllocationResult(
        adaptive_capital_policy_version=ADAPTIVE_CAPITAL_POLICY_VERSION,
        allocation_id=_allocation_id(row, mode, envelope),
        allocation_input_schema_version=ALLOCATION_INPUT_SCHEMA_VERSION,
        allocation_input_hash=input_hash,
        allocation_input_hash_algorithm=ALLOCATION_INPUT_HASH_ALGORITHM,
        allocation_input_material=input_material,
        symbol=row.symbol,
        timeframe=row.timeframe,
        action=row.action,
        decision=decision,  # type: ignore[arg-type]
        target_notional_usdt=round(gross_notional, 8),
        target_quantity=round(max(0.0, target_quantity), 12),
        risk_budget_usd=round(max(0.0, risk_budget_usd), 8),
        gross_notional_usd=round(gross_notional, 8),
        allocated_margin_usd=round(max(0.0, allocated_margin), 8),
        recommended_leverage=round(max(1.0, leverage), 8),
        effective_leverage=round(max(1.0, leverage), 8),
        recommended_margin_mode=recommended_margin_mode,
        stop_distance_bps=None
        if stop_distance_bps is None
        else round(max(0.0, stop_distance_bps), 8),
        liquidation_price_estimate=None
        if liquidation_price is None
        else round(max(0.0, liquidation_price), 12),
        liquidation_buffer_bps=None
        if liquidation_buffer_bps is None
        else round(liquidation_buffer_bps, 8),
        max_loss_if_stop_hit=None
        if max_loss_if_stop_hit is None
        else round(max_loss_if_stop_hit, 8),
        risk_reward=None if risk_reward is None else round(risk_reward, 8),
        risk_of_ruin_contribution=round(risk_of_ruin_contribution, 8),
        portfolio_exposure_after_trade=round(portfolio_exposure_after_trade, 8),
        correlation_exposure_after_trade=round(correlation_exposure_after_trade, 8),
        expected_fees_usd=round(expected_fees_usd, 8),
        expected_slippage_usd=round(expected_slippage_usd, 8),
        expected_funding_usd=round(expected_funding_usd, 8),
        expected_gross_pnl_usd=round(expected_gross_pnl_usd, 8),
        expected_net_pnl_usd=round(expected_net_pnl_usd, 8),
        expected_shortfall_usd=round(expected_shortfall_usd, 8),
        max_loss_usd=None if max_loss_if_stop_hit is None else round(max_loss_if_stop_hit, 8),
        stop_loss_usd=None if modeled_stop_loss_usd is None else round(modeled_stop_loss_usd, 8),
        take_profit_usd=round(max(0.0, expected_gross_pnl_usd), 8),
        mfe_usd=round(max(0.0, expected_gross_pnl_usd), 8),
        mae_usd=None if modeled_stop_loss_usd is None else round(modeled_stop_loss_usd, 8),
        liquidation_distance_usd=None
        if liquidation_distance_usd is None
        else round(liquidation_distance_usd, 8),
        hedge_budget_usd=round(hedge_budget_usd, 8),
        net_delta_usd=round(float(hedge_plan.get("net_delta_usd") or 0.0), 8),
        gross_exposure_usd=round(float(hedge_plan.get("gross_exposure_usd") or 0.0), 8),
        long_exposure_usd=round(float(hedge_plan.get("long_exposure_usd") or 0.0), 8),
        short_exposure_usd=round(float(hedge_plan.get("short_exposure_usd") or 0.0), 8),
        btc_beta_exposure_usd=round(float(hedge_plan.get("btc_beta_exposure_usd") or 0.0), 8),
        eth_beta_exposure_usd=round(float(hedge_plan.get("eth_beta_exposure_usd") or 0.0), 8),
        sector_exposure_usd=dict(hedge_plan.get("sector_exposure_usd") or {}),
        correlation_exposure_usd=round(float(hedge_plan.get("correlation_exposure_usd") or 0.0), 8),
        hedge_required=bool(hedge_plan.get("hedge_required")),
        hedge_action=str(hedge_plan.get("hedge_action") or "NO_HEDGE"),
        hedge_reason=str(hedge_plan.get("hedge_reason") or ""),
        hedge_symbol=hedge_plan.get("hedge_symbol"),
        hedge_side=hedge_plan.get("hedge_side"),
        hedge_notional_usd=round(float(hedge_plan.get("hedge_notional_usd") or 0.0), 8),
        hedge_margin_usd=round(float(hedge_plan.get("hedge_margin_usd") or 0.0), 8),
        hedge_leverage=round(float(hedge_plan.get("hedge_leverage") or 1.0), 8),
        hedge_cost_usd=round(float(hedge_plan.get("hedge_cost_usd") or 0.0), 8),
        hedge_expected_risk_reduction_usd=round(
            float(hedge_plan.get("hedge_expected_risk_reduction_usd") or 0.0), 8
        ),
        hedge_net_benefit_usd=round(float(hedge_plan.get("hedge_net_benefit_usd") or 0.0), 8),
        hedge_exit_plan=dict(hedge_plan.get("hedge_exit_plan") or {}),
        isolated_margin_required_usd=round(
            float(cross_margin.get("isolated_margin_required_usd") or 0.0), 8
        ),
        cross_margin_stress_used_usd=round(
            float(cross_margin.get("cross_margin_stress_used_usd") or 0.0), 8
        ),
        cross_margin_available_buffer_usd=round(
            float(cross_margin.get("cross_margin_available_buffer_usd") or 0.0), 8
        ),
        portfolio_liquidation_buffer_usd=round(
            float(cross_margin.get("portfolio_liquidation_buffer_usd") or 0.0), 8
        ),
        worst_case_portfolio_loss_usd=round(
            float(cross_margin.get("worst_case_portfolio_loss_usd") or 0.0), 8
        ),
        maintenance_margin_estimate_usd=(
            None
            if cross_margin.get("maintenance_margin_estimate_usd") is None
            else round(float(cross_margin["maintenance_margin_estimate_usd"]), 8)
        ),
        margin_call_risk=str(cross_margin.get("margin_call_risk") or "UNKNOWN"),
        cross_margin_safe=bool(cross_margin.get("cross_margin_safe")),
        why_cross_margin_or_isolated=str(cross_margin.get("why_cross_margin_or_isolated") or ""),
        capital_allocation_reason=final_size_reason,
        risk_budget_pct_of_equity=0.0
        if row.equity <= 0
        else round(risk_budget_usd / row.equity, 8),
        risk_budget_pct_of_available_margin=round(risk_budget_usd / available_margin, 8),
        confidence_calibrated=row.confidence_calibrated,
        expected_move_after_cost_bps=row.expected_move_after_cost_bps,
        market_state_integrity_score=row.market_state_integrity_score,
        volatility_adjustment=round(volatility_adjustment(sizing_row), 8),
        liquidity_adjustment=round(liquidity_adjustment(sizing_row), 8),
        spread_slippage_adjustment=round(spread_slippage_adjustment(sizing_row), 8),
        drawdown_adjustment=round(drawdown_adjustment(sizing_row, envelope), 8),
        exposure_adjustment=round(exposure_adjustment(sizing_row, envelope), 8),
        correlation_adjustment=round(correlation_adjustment(sizing_row, envelope), 8),
        regime_adjustment=round(regime_adjustment(sizing_row), 8),
        exchange_min_order_adjustment=round(
            min_order_notional(min_qty=row.min_qty, min_notional=row.min_notional, price=row.price),
            8,
        ),
        final_size_reason=final_size_reason,
        risk_veto_reason_if_blocked=risk_veto_reason,
        model_inputs=model_inputs,
        lineage_ids=dict(row.lineage_ids),
    )


def _stop_distance_bps(row: AllocationInput) -> float:
    """Stop distance used for notional sizing (risk_budget / stop_distance).

    2026-07-16 G13/G14 root cause: sizing used the intent's explicit stop
    (14.8-23.2bps on the losing cohort) while the exit engine enforced its
    floor-clamped, overshoot-carrying ATR stop (~35-81bps realized), so
    realized losses ran 2.0-4.8x the sized risk budget on exactly the
    high-confidence trades the allocator up-sized. Sizing now uses the WIDER
    of the explicit stop and the exit engine's own effective stop (same
    formula via effective_atr_stop_bps) plus round-trip execution drag.
    """
    entry_atr = row.entry_atr_bps if (row.entry_atr_bps or 0) > 0 else None
    exit_engine_stop: float | None = None
    round_trip_cost = max(0.0, row.spread_bps) + max(0.0, row.slippage_bps) + max(0.0, row.fee_bps)
    if entry_atr is not None:
        # Only rows carrying real entry ATR (all runtime intents with ATR
        # evidence — the entire observed mis-sized cohort) get the unified
        # stop; ATR-less rows keep the legacy fallback semantics.
        exit_engine_stop = effective_atr_stop_bps(
            atr_bps=entry_atr,
            confidence_calibrated=row.confidence_calibrated,
            strategy_selected_mode=row.strategy_selected_mode,
            market_regime=row.market_regime,
            config=PaperExitConfig(atr_stop_overshoot_premium_bps=row.exit_overshoot_premium_bps),
        )
    explicit = row.stop_distance_bps if row.stop_distance_bps is not None else None
    if explicit is not None and explicit > 0:
        if exit_engine_stop is not None:
            return max(float(explicit), exit_engine_stop + round_trip_cost)
        return float(explicit)
    cost_floor = max(1.0, round_trip_cost)
    volatility_floor = max(10.0, row.volatility_bps * 1.5)
    base = max(cost_floor * 2.0, volatility_floor)
    if exit_engine_stop is not None:
        base = max(base, exit_engine_stop + round_trip_cost)
    return base


def _liquidation_distance_bps(*, leverage: float, maintenance_margin_rate: float) -> float:
    if leverage <= 0:
        return 0.0
    return max(0.0, (1.0 / leverage - max(0.0, maintenance_margin_rate)) * 10000.0)


def _liquidation_price(
    *, side: str, price: float, leverage: float, maintenance_margin_rate: float
) -> float | None:
    if price <= 0 or leverage <= 0:
        return None
    distance = 1.0 / leverage - max(0.0, maintenance_margin_rate)
    if side == "short":
        return price * (1.0 + max(0.0, distance))
    return max(0.0, price * (1.0 - max(0.0, distance)))


def paper_isolated_liquidation_geometry(
    *,
    side: str,
    entry_price: float,
    leverage: float,
    maintenance_margin_rate: float,
) -> tuple[float, float] | None:
    """Return conservative PAPER isolated distance and price without ``cum``.

    Binance bracket ``cum`` is non-negative and moves liquidation farther from
    entry.  Omitting it is therefore conservative.  The side-aware maintenance
    denominator is essential for shorts: ``(1/L-MMR)/(1+MMR)``.
    """

    normalized_side = str(side or "").strip().lower()
    rate = _finite_float(maintenance_margin_rate)
    parsed_price = _finite_float(entry_price)
    parsed_leverage = _finite_float(leverage)
    if (
        normalized_side not in {"long", "short"}
        or parsed_price is None
        or parsed_price <= 0.0
        or parsed_leverage is None
        or parsed_leverage <= 0.0
        or rate is None
        or not 0.0 < rate < 1.0
    ):
        return None
    raw_distance = max(0.0, (1.0 / parsed_leverage) - rate)
    denominator = 1.0 - rate if normalized_side == "long" else 1.0 + rate
    distance_fraction = raw_distance / denominator
    liquidation_price = (
        max(0.0, parsed_price * (1.0 - distance_fraction))
        if normalized_side == "long"
        else parsed_price * (1.0 + distance_fraction)
    )
    return distance_fraction * 10000.0, liquidation_price


def _select_margin_configuration(
    row: AllocationInput,
    *,
    gross_notional: float,
    stop_distance_bps: float,
    envelope: RiskEnvelope,
    maintenance_margin_rate: float,
    target_leverage: float = 1.0,
    allow_above_target: bool = False,
    minimum_liquidation_buffer_bps: float | None = None,
    paper_mode: bool = False,
) -> tuple[float, float, float | None, float | None] | None:
    usable_margin = available_margin_budget_usdt(row, envelope)
    reserve_bps = max(0.0, row.fee_bps) + max(0.0, row.slippage_bps) + abs(row.expected_funding_bps)
    permitted = sorted(
        {
            float(value)
            for value in row.permitted_leverage_values
            if value is not None
            and float(value) >= 1.0
            and float(value) <= max(1.0, envelope.max_effective_leverage)
        }
    )
    if not permitted:
        permitted = [1.0]
    leverage_floor = max(1.0, target_leverage)
    preferred = sorted([value for value in permitted if value <= leverage_floor], reverse=True)
    # Paper must never use scarce margin as a reason to exceed the leverage
    # supported by its candidate evidence. The live compatibility path retains
    # its pre-existing fallback ordering until separately approved migration.
    fallback = (
        sorted([value for value in permitted if value > leverage_floor])
        if allow_above_target
        else []
    )
    required_liquidation_buffer_bps = (
        envelope.min_liquidation_buffer_bps
        if minimum_liquidation_buffer_bps is None
        else minimum_liquidation_buffer_bps
    )
    for leverage in [*preferred, *fallback]:
        allocated_margin = gross_notional / leverage if leverage > 0 else gross_notional
        if allocated_margin > usable_margin:
            continue
        paper_geometry = (
            paper_isolated_liquidation_geometry(
                side=row.action,
                entry_price=row.price,
                leverage=leverage,
                maintenance_margin_rate=maintenance_margin_rate,
            )
            if paper_mode
            else None
        )
        if paper_mode and paper_geometry is None:
            continue
        liquidation_distance = (
            paper_geometry[0]
            if paper_geometry is not None
            else _liquidation_distance_bps(
                leverage=leverage,
                maintenance_margin_rate=maintenance_margin_rate,
            )
        )
        liquidation_buffer = liquidation_distance - stop_distance_bps - reserve_bps
        if liquidation_buffer < required_liquidation_buffer_bps:
            continue
        return (
            leverage,
            allocated_margin,
            (
                paper_geometry[1]
                if paper_geometry is not None
                else _liquidation_price(
                    side=row.action,
                    price=row.price,
                    leverage=leverage,
                    maintenance_margin_rate=maintenance_margin_rate,
                )
            ),
            liquidation_buffer,
        )
    return None


def _allocate(row: AllocationInput, *, mode: str, envelope: RiskEnvelope) -> AllocationResult:
    if mode == "paper":
        invalid_reasons = _paper_input_rejection_reasons(row, envelope)
        if invalid_reasons:
            safe_row = _safe_block_row(row)
            return _block(
                safe_row,
                mode=mode,
                decision="BLOCK_BAD_MARKET_STATE",
                reason="paper_allocator_nonfinite_or_invalid_input",
                envelope=_safe_block_envelope(envelope),
                extra_diagnostics={
                    "paper_allocator_input_validation_status": "FAIL_CLOSED",
                    "paper_allocator_input_rejection_reasons": invalid_reasons,
                },
            )
    maintenance_margin_rate, maintenance_diagnostics = _maintenance_margin_contract(
        row,
        mode=mode,
    )
    if mode == "paper" and maintenance_margin_rate is None:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_LIQUIDATION_RISK",
            reason="maintenance_margin_rate_missing_or_invalid_no_liquidation_math",
            envelope=envelope,
            extra_diagnostics=maintenance_diagnostics,
        )
    # PAPER returned above when this is absent.  LIVE deliberately preserves
    # the historical explicit-None failure when legacy liquidation math first
    # consumes the value.
    sizing_row = _paper_sizing_row(row, mode=mode)
    economic_edge_bps = sizing_row.expected_move_after_cost_bps
    if row.risk_veto:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_EXPOSURE_BUDGET",
            reason=row.risk_veto_reason or "risk_envelope_veto",
            envelope=envelope,
        )
    # The normal paper loop already applies the authoritative integrity and
    # adaptive entry gates.  Preserve the legacy live admission cliff exactly;
    # paper market quality remains a continuous sizing input below.
    if mode == "live" and row.market_state_integrity_score < 70.0:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_BAD_MARKET_STATE",
            reason="market_state_integrity_score_below_minimum",
            envelope=envelope,
        )

    # Preserve the legacy live confidence admission cliff.  Positive paper
    # confidence contributes continuously to size instead of being admitted at
    # one threshold and then zero-sized at another threshold.
    if mode == "live" and row.confidence_calibrated < 0.50:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_LOW_CONFIDENCE",
            reason="confidence_below_adaptive_minimum",
            envelope=envelope,
        )

    if economic_edge_bps <= 0.0:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_NO_EDGE",
            reason="expected_move_after_cost_not_positive",
            envelope=envelope,
        )

    # Paper requires real positive liquidity evidence, then applies its
    # magnitude continuously in the sizing model.  Live retains its historical
    # admission threshold unchanged.
    if (mode == "paper" and row.liquidity_score <= 0.0) or (
        mode == "live" and row.liquidity_score <= 0.05
    ):
        return _block(
            row,
            mode=mode,
            decision="BLOCK_INSUFFICIENT_LIQUIDITY",
            reason="liquidity_score_too_low",
            envelope=envelope,
        )

    # Expected edge is already after cost.  Paper therefore uses the existing
    # continuous cost-pressure factor rather than rejecting again at a fixed
    # cost/edge ratio.  Live keeps the historical hard safety gate unchanged.
    if mode == "live" and row.spread_bps + row.slippage_bps >= max(1.0, economic_edge_bps):
        return _block(
            row,
            mode=mode,
            decision="BLOCK_SPREAD_SLIPPAGE",
            reason="spread_plus_slippage_exceeds_expected_edge",
            envelope=envelope,
        )
    if row.drawdown_bps >= envelope.max_daily_drawdown_pct * 10000.0:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_DRAWDOWN_GUARD",
            reason="drawdown_guard_breached",
            envelope=envelope,
        )
    if mode == "paper" and row.available_margin <= 0:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_INSUFFICIENT_MARGIN",
            reason="paper_free_margin_missing_or_zero",
            envelope=envelope,
        )
    if mode == "live" and row.available_margin <= 0:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_INSUFFICIENT_MARGIN",
            reason="available_margin_missing_or_zero",
            envelope=envelope,
        )

    paper_risk_budget_fraction = row.paper_risk_budget_fraction if mode == "paper" else 1.0
    paper_quality_sizing_weight = row.paper_quality_sizing_weight if mode == "paper" else 1.0
    ceiling_before_paper_fraction_usd = risk_envelope_gross_notional_ceiling(
        row,
        envelope,
    )
    ceiling_after_paper_fraction_usd = (
        ceiling_before_paper_fraction_usd * paper_risk_budget_fraction
    )
    ceiling = ceiling_after_paper_fraction_usd * paper_quality_sizing_weight
    if ceiling <= 0:
        return _block(
            row,
            mode=mode,
            decision="BLOCK_EXPOSURE_BUDGET",
            reason="risk_envelope_budget_exhausted",
            envelope=envelope,
        )

    budget_pct = adaptive_budget_pct(
        sizing_row,
        envelope,
        continuous_confidence_from_zero=mode == "paper",
    )
    risk_budget_before_paper_fraction_usd = row.equity * budget_pct
    risk_budget_after_paper_fraction_usd = (
        risk_budget_before_paper_fraction_usd * paper_risk_budget_fraction
    )
    risk_budget_usd = risk_budget_after_paper_fraction_usd * paper_quality_sizing_weight
    stop_distance_bps = _stop_distance_bps(row)
    if risk_budget_usd <= 0:
        # Signal Explainability Rule: a zeroed adaptive budget must say WHICH
        # multiplicative factor zeroed it, or the block is undiagnosable.
        zero_diag = {
            "budget_factor_confidence": round(
                confidence_adjustment(
                    sizing_row,
                    continuous_from_zero=mode == "paper",
                ),
                8,
            ),
            "budget_factor_edge": round(edge_adjustment(sizing_row), 8),
            "budget_factor_market_state": round(market_state_adjustment(sizing_row), 8),
            "budget_factor_volatility": round(volatility_adjustment(sizing_row), 8),
            "budget_factor_liquidity": round(liquidity_adjustment(sizing_row), 8),
            "budget_factor_spread_slippage": round(spread_slippage_adjustment(sizing_row), 8),
            "budget_factor_drawdown": round(drawdown_adjustment(sizing_row, envelope), 8),
            "budget_factor_exposure": round(exposure_adjustment(sizing_row, envelope), 8),
            "budget_factor_correlation": round(correlation_adjustment(sizing_row, envelope), 8),
            "budget_factor_regime": round(regime_adjustment(sizing_row), 8),
            "budget_max_loss_per_trade_pct": round(envelope.max_loss_per_trade_pct, 8),
            "budget_equity_usd": round(row.equity, 8),
            "budget_total_exposure_usdt": round(row.total_exposure_usdt, 8),
            "budget_envelope_max_total_portfolio_risk_pct": round(
                envelope.max_total_portfolio_risk_pct, 8
            ),
        }
        return _block(
            row,
            mode=mode,
            decision="BLOCK_NO_EDGE",
            reason="risk_budget_after_adjustments_is_zero",
            envelope=envelope,
            extra_diagnostics=zero_diag,
        )
    # A requested hedge is not proof that a hedge is atomically filled, funded,
    # and cap-safe for this allocation. Size against the full unhedged stop; the
    # former hedge-arm amplification could raise max loss above the same risk
    # budget when a direct caller enabled the dormant flag.
    sizing_stop_bps = stop_distance_bps
    hedge_sizing_diag: dict[str, Any] | None = None
    if mode == "live" and row.adaptive_hedge_sizing_enabled and stop_distance_bps > 0.0:
        hedge_arm = hedge_arm_fraction(
            row.confidence_calibrated,
            portfolio_drawdown_bps=row.drawdown_bps,
        )
        hedge_leg_drag_bps = 2.0 * (max(0.0, row.fee_bps) + max(0.0, row.slippage_bps))
        sizing_stop_bps = max(
            stop_distance_bps * hedge_arm + hedge_leg_drag_bps,
            0.5 * stop_distance_bps,
        )
        hedge_sizing_diag = {
            "hedge_arm_fraction": round(hedge_arm, 6),
            "hedge_leg_drag_bps": round(hedge_leg_drag_bps, 4),
            "full_stop_bps": round(stop_distance_bps, 4),
            "hedge_sizing_stop_bps": round(sizing_stop_bps, 4),
            "size_amplification": round(stop_distance_bps / sizing_stop_bps, 4),
        }
    elif row.adaptive_hedge_sizing_enabled:
        hedge_sizing_diag = {
            "status": "DISABLED_NO_ATOMIC_FUNDED_HEDGE_PROOF",
            "requested": True,
            "enabled": False,
            "full_stop_bps": round(stop_distance_bps, 4),
            "hedge_sizing_stop_bps": round(stop_distance_bps, 4),
            "size_amplification": 1.0,
        }
    paper_modeled_loss_bps = (
        sizing_stop_bps
        + max(0.0, row.fee_bps)
        + max(0.0, row.slippage_bps)
        + abs(row.expected_funding_bps)
        if mode == "paper"
        else sizing_stop_bps
    )
    target_notional = min(
        risk_budget_usd / (paper_modeled_loss_bps / 10000.0),
        ceiling,
    )
    min_notional = min_order_notional(
        min_qty=row.min_qty, min_notional=row.min_notional, price=row.price
    )
    if min_notional > 0 and target_notional < min_notional:
        # Every paper allocation is an upper-bounded risk experiment. Raising
        # any continuous target to a venue minimum can violate that budget,
        # even when the explicit recovery fraction is exactly one.
        if mode == "paper":
            return _block(
                row,
                mode=mode,
                decision="BLOCK_EXCHANGE_MIN_ORDER",
                reason=(
                    "paper_reduced_risk_budget_below_exchange_min_order"
                    if paper_risk_budget_fraction < 1.0
                    else "paper_continuous_target_below_exchange_min_order"
                ),
                envelope=envelope,
                extra_diagnostics={
                    "paper_risk_budget_fraction": round(
                        paper_risk_budget_fraction,
                        8,
                    ),
                    "paper_quality_sizing_weight": round(
                        paper_quality_sizing_weight,
                        8,
                    ),
                    "risk_budget_before_paper_fraction_usd": round(
                        risk_budget_before_paper_fraction_usd,
                        8,
                    ),
                    "risk_budget_after_paper_fraction_usd": round(
                        risk_budget_after_paper_fraction_usd,
                        8,
                    ),
                    "risk_budget_after_paper_quality_weight_usd": round(
                        risk_budget_usd,
                        8,
                    ),
                    "paper_modeled_loss_bps": round(paper_modeled_loss_bps, 8),
                    "target_notional_before_exchange_minimum_usd": round(
                        target_notional,
                        8,
                    ),
                    "exchange_min_order_notional_usd": round(min_notional, 8),
                },
            )
        if ceiling >= min_notional:
            target_notional = min_notional
        else:
            return _block(
                row,
                mode=mode,
                decision="BLOCK_EXCHANGE_MIN_ORDER",
                reason="adaptive_size_below_exchange_min_order",
                envelope=envelope,
            )
    target_notional_before_step_quantization = target_notional
    paper_quantized_quantity: float | None = None
    paper_quantized_notional: float | None = None
    if mode == "paper":
        paper_raw_quantity = 0.0 if row.price <= 0.0 else target_notional / row.price
        paper_quantity_before_max_cap = paper_raw_quantity
        paper_exchange_max_qty_reduction_applied = bool(
            row.max_qty is not None and row.max_qty > 0.0 and paper_raw_quantity > row.max_qty
        )
        if paper_exchange_max_qty_reduction_applied:
            assert row.max_qty is not None
            paper_raw_quantity = float(row.max_qty)
        paper_quantized_quantity = round_down_to_step(
            paper_raw_quantity,
            row.step_size,
        )
        if paper_quantized_quantity <= 0.0:
            return _block(
                row,
                mode=mode,
                decision="BLOCK_EXCHANGE_MIN_ORDER",
                reason="quantity_rounds_to_zero",
                envelope=envelope,
                extra_diagnostics={
                    "paper_post_quantization_exchange_filter_status": "FAIL_CLOSED",
                    "paper_target_notional_before_step_quantization_usd": round(
                        target_notional_before_step_quantization,
                        8,
                    ),
                    "paper_target_quantity_after_step_quantization": 0.0,
                    "paper_target_notional_after_step_quantization_usd": 0.0,
                },
            )
        paper_quantized_notional = abs(paper_quantized_quantity * row.price)
        below_min_qty = bool(
            row.min_qty is not None and row.min_qty > 0.0 and paper_quantized_quantity < row.min_qty
        )
        below_min_notional = bool(
            row.min_notional is not None
            and row.min_notional > 0.0
            and paper_quantized_notional < row.min_notional
        )
        above_max_qty = bool(
            row.max_qty is not None and row.max_qty > 0.0 and paper_quantized_quantity > row.max_qty
        )
        if below_min_qty or below_min_notional or above_max_qty:
            return _block(
                row,
                mode=mode,
                decision=(
                    "BLOCK_EXCHANGE_MAX_ORDER" if above_max_qty else "BLOCK_EXCHANGE_MIN_ORDER"
                ),
                reason=(
                    "paper_step_quantization_above_exchange_max_order"
                    if above_max_qty
                    else "paper_step_quantization_below_exchange_min_order"
                ),
                envelope=envelope,
                extra_diagnostics={
                    "paper_post_quantization_exchange_filter_status": "FAIL_CLOSED",
                    "paper_post_quantization_below_min_qty": below_min_qty,
                    "paper_post_quantization_below_min_notional": below_min_notional,
                    "paper_post_quantization_above_max_qty": above_max_qty,
                    "paper_target_notional_before_step_quantization_usd": round(
                        target_notional_before_step_quantization,
                        8,
                    ),
                    "paper_target_quantity_after_step_quantization": round(
                        paper_quantized_quantity,
                        12,
                    ),
                    "paper_target_notional_after_step_quantization_usd": round(
                        paper_quantized_notional,
                        8,
                    ),
                    "exchange_min_qty": row.min_qty,
                    "exchange_max_qty": row.max_qty,
                    "exchange_min_notional_usd": row.min_notional,
                },
            )
        if paper_exchange_max_qty_reduction_applied:
            target_notional = paper_quantized_notional
    target_leverage, leverage_selection = _adaptive_leverage_target_selection(
        sizing_row,
        envelope,
        mode=mode,
        signed_expected_market_move_after_cost_bps=(row.expected_move_after_cost_bps),
    )
    paper_minimum_liquidation_buffer_bps: float | None = None
    if mode == "paper":
        (
            paper_minimum_liquidation_buffer_bps,
            paper_liquidation_buffer_diagnostics,
        ) = _paper_minimum_liquidation_buffer(sizing_row, envelope)
        leverage_selection.update(paper_liquidation_buffer_diagnostics)
    if mode == "paper":
        leverage_selection.update(
            {
                **maintenance_diagnostics,
                "paper_exchange_max_qty_reduction_applied": (
                    paper_exchange_max_qty_reduction_applied
                ),
                "paper_quantity_before_exchange_max_cap": round(
                    paper_quantity_before_max_cap,
                    12,
                ),
            }
        )
    if mode == "paper":
        leverage_selection.update(
            {
                "paper_risk_budget_fraction": round(
                    paper_risk_budget_fraction,
                    8,
                ),
                "risk_budget_before_paper_fraction_usd": round(
                    risk_budget_before_paper_fraction_usd,
                    8,
                ),
                "risk_budget_after_paper_fraction_usd": round(
                    risk_budget_after_paper_fraction_usd,
                    8,
                ),
                "paper_reduced_risk_budget_applied_pre_quantization": bool(
                    paper_risk_budget_fraction < 1.0
                ),
                "gross_notional_ceiling_before_paper_fraction_usd": round(
                    ceiling_before_paper_fraction_usd,
                    8,
                ),
                "gross_notional_ceiling_after_paper_fraction_usd": round(
                    ceiling_after_paper_fraction_usd,
                    8,
                ),
                "paper_quality_sizing_weight": round(
                    paper_quality_sizing_weight,
                    8,
                ),
                "risk_budget_after_paper_quality_weight_usd": round(
                    risk_budget_usd,
                    8,
                ),
                "paper_quality_weight_applied_pre_quantization": bool(
                    paper_quality_sizing_weight < 1.0
                ),
                "paper_modeled_loss_bps": round(paper_modeled_loss_bps, 8),
                "paper_modeled_loss_formula": (
                    "stop_distance_bps + max(fee_bps, 0) + "
                    "max(slippage_bps, 0) + abs(expected_funding_bps)"
                ),
                "gross_notional_ceiling_after_paper_quality_weight_usd": round(
                    ceiling,
                    8,
                ),
                "paper_post_quantization_exchange_filter_status": "PASS",
                "paper_target_notional_before_step_quantization_usd": round(
                    target_notional_before_step_quantization,
                    8,
                ),
                "paper_target_quantity_after_step_quantization": round(
                    paper_quantized_quantity or 0.0,
                    12,
                ),
                "paper_target_notional_after_step_quantization_usd": round(
                    paper_quantized_notional or 0.0,
                    8,
                ),
                "paper_margin_configuration_uses_post_quantization_notional": True,
            }
        )
    if hedge_sizing_diag is not None:
        leverage_selection = {
            **leverage_selection,
            "hedge_aware_sizing": hedge_sizing_diag,
        }
    margin_config = _select_margin_configuration(
        sizing_row,
        gross_notional=(
            paper_quantized_notional
            if mode == "paper" and paper_quantized_notional is not None
            else target_notional
        ),
        stop_distance_bps=stop_distance_bps,
        envelope=envelope,
        maintenance_margin_rate=maintenance_margin_rate,
        target_leverage=target_leverage,
        allow_above_target=mode != "paper",
        minimum_liquidation_buffer_bps=(
            paper_minimum_liquidation_buffer_bps
            if mode == "paper" and paper_minimum_liquidation_buffer_bps is not None
            else None
        ),
        paper_mode=mode == "paper",
    )
    if margin_config is None:
        if mode == "live":
            # Live execution remains a separately operator-gated contract.
            # Preserve its legacy blocked payload exactly; the adaptive
            # leverage evidence below is paper-only telemetry.
            return _block(
                row,
                mode=mode,
                decision="BLOCK_LIQUIDATION_RISK",
                reason="no_safe_leverage_margin_configuration",
                envelope=envelope,
            )
        return _block(
            row,
            mode=mode,
            decision="BLOCK_LIQUIDATION_RISK",
            reason="no_safe_leverage_margin_configuration",
            envelope=envelope,
            extra_diagnostics={
                **leverage_selection,
                "paper_margin_may_exceed_evidence_leverage_target": mode != "paper",
            },
        )
    leverage, allocated_margin, liquidation_price, liquidation_buffer_bps = margin_config
    margin_mode, margin_mode_selection = _adaptive_margin_mode_selection(
        row,
        envelope,
        mode=mode,
        leverage=leverage,
        liquidation_buffer_bps=liquidation_buffer_bps,
    )
    if mode == "paper" and allocated_margin > available_margin_budget_usdt(row, envelope):
        return _block(
            row,
            mode=mode,
            decision="BLOCK_INSUFFICIENT_MARGIN",
            reason="paper_adaptive_margin_exceeds_free_margin_after_buffer",
            envelope=envelope,
        )
    if mode == "live" and allocated_margin > available_margin_budget_usdt(row, envelope):
        return _block(
            row,
            mode=mode,
            decision="BLOCK_INSUFFICIENT_MARGIN",
            reason="adaptive_margin_exceeds_available_margin_after_buffer",
            envelope=envelope,
        )
    if mode == "paper":
        # Paper exchange filters are applied before margin selection.  Reuse
        # that exact quantity/notional here so no downstream accounting field
        # can silently revert to the larger pre-quantization target.
        assert paper_quantized_quantity is not None
        assert paper_quantized_notional is not None
        quantity = paper_quantized_quantity
        adjusted_notional = paper_quantized_notional
    else:
        # Preserve the separately operator-gated live sizing sequence.
        quantity = 0.0 if row.price <= 0 else target_notional / row.price
        quantity = round_down_to_step(quantity, row.step_size)
        if quantity <= 0:
            return _block(
                row,
                mode=mode,
                decision="BLOCK_EXCHANGE_MIN_ORDER",
                reason="quantity_rounds_to_zero",
                envelope=envelope,
            )
        adjusted_notional = quantity * row.price
    decision = (
        "ALLOW_WITH_SIZE"
        if adjusted_notional >= target_notional_before_step_quantization * 0.95
        else "REDUCE_SIZE"
    )
    result = _result(
        row,
        mode=mode,
        envelope=envelope,
        sizing_row=sizing_row,
        decision=decision,
        target_notional=adjusted_notional,
        target_quantity=quantity,
        risk_budget_usd=risk_budget_usd,
        allocated_margin=allocated_margin,
        leverage=leverage,
        stop_distance_bps=stop_distance_bps,
        liquidation_price=liquidation_price,
        liquidation_buffer_bps=liquidation_buffer_bps,
        final_size_reason=(
            "paper_allocation_from_reduced_risk_budget_and_ceiling_pre_quantization"
            if mode == "paper" and paper_risk_budget_fraction < 1.0
            else (
                "paper_allocation_from_quality_weighted_risk_budget_and_ceiling_pre_quantization"
                if mode == "paper" and paper_quality_sizing_weight < 1.0
                else "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget"
            )
        ),
        leverage_selection={
            **leverage_selection,
            "selected_leverage": round(leverage, 8),
            "selected_allocated_margin_usd": round(allocated_margin, 8),
        },
        margin_mode=margin_mode,
        margin_mode_selection=margin_mode_selection,
    )
    return result


def allocate_paper_candidate(
    row: AllocationInput, envelope: RiskEnvelope | None = None
) -> AllocationResult:
    return _allocate(row, mode="paper", envelope=envelope or RiskEnvelope())


def allocate_live_candidate(
    row: AllocationInput, envelope: RiskEnvelope | None = None
) -> AllocationResult:
    return _allocate(row, mode="live", envelope=envelope or RiskEnvelope())


__all__ = [
    "PAPER_ALLOCATOR_ARITHMETIC_FORMULA",
    "PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY",
    "PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION",
    "PAPER_ALLOCATOR_ARITHMETIC_VERSION",
    "PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY",
    "PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY",
    "PAPER_ALLOCATOR_REGIME_SOURCE_HASH_LINEAGE_KEY",
    "PAPER_ALLOCATOR_REGIME_SOURCE_MATERIAL_LINEAGE_KEY",
    "PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY",
    "PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY",
    "PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY",
    "PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY",
    "PAPER_LIQUIDATION_ATR_EVIDENCE_SCHEMA_VERSION",
    "allocate_paper_candidate",
    "allocate_live_candidate",
    "build_paper_liquidation_atr_evidence",
    "explain_allocation",
    "paper_isolated_liquidation_geometry",
    "validate_paper_liquidation_atr_evidence",
]
