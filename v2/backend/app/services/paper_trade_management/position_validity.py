from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .accounting import coerce_float, normalize_side


VALID_ACCOUNT_SCOPES = {
    "PAPER_SIM_ACCOUNT",
    "SHADOW_DIAGNOSTIC_ACCOUNT",
    "QUARANTINED_INVALID_ACCOUNT",
    "LIVE_BINANCE_SIGNED_ACCOUNT",
}

PAPER_ACCOUNT_SCOPE = "PAPER_SIM_ACCOUNT"
QUARANTINED_ACCOUNT_SCOPE = "QUARANTINED_INVALID_ACCOUNT"
SHADOW_ACCOUNT_SCOPE = "SHADOW_DIAGNOSTIC_ACCOUNT"


@dataclass(frozen=True)
class PositionValidityConfig:
    max_entry_to_current_mark_ratio_without_fill_reference: float = 10.0
    max_fill_reference_mismatch_bps: float = 100.0
    max_mark_age_seconds: float = 120.0
    require_fresh_current_mark: bool = False
    require_production_cost_flag: bool = False
    require_explicit_paper_only: bool = False


DEFAULT_VALIDITY_CONFIG = PositionValidityConfig()
STRICT_WRITE_VALIDITY_CONFIG = PositionValidityConfig(
    require_fresh_current_mark=True,
    require_production_cost_flag=True,
    require_explicit_paper_only=True,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = coerce_float(row.get(key))
        if parsed is not None:
            return parsed
    return None


def source_fill_ids(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("source_fill_ids")
    values: list[str] = []
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, dict)):
        values.extend(str(item) for item in raw if item not in (None, ""))
    for key in ("entry_fill_id", "fill_id", "paper_fill_id", "ledger_row_id", "intent_id"):
        value = row.get(key)
        if value not in (None, ""):
            values.append(str(value))
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def entry_price(row: Mapping[str, Any]) -> float | None:
    return first_number(
        row,
        "entry_price",
        "avg_entry_price",
        "fill_price",
        "entry_fill_price",
        "paper_entry_price",
        "price_at_entry",
        "open_price",
    )


def entry_price_source(row: Mapping[str, Any]) -> str | None:
    explicit = first_present(
        row,
        "entry_price_source",
        "fill_price_source",
        "entry_fill_price_source",
        "paper_entry_price_source",
    )
    if explicit is not None:
        return str(explicit)
    for key in (
        "entry_price",
        "avg_entry_price",
        "fill_price",
        "entry_fill_price",
        "paper_entry_price",
        "price_at_entry",
        "open_price",
    ):
        if coerce_float(row.get(key)) is not None:
            return key
    return None


def row_quantity(row: Mapping[str, Any], price: float | None = None) -> float | None:
    qty = first_number(row, "quantity", "qty", "net_quantity", "size", "order_size")
    if qty is not None and abs(qty) > 0:
        return abs(qty)
    notional = first_number(row, "gross_notional_usd", "notional", "notional_usdt", "notional_usd")
    if notional is not None and notional > 0 and price is not None and price > 0:
        return abs(notional / price)
    return None


def gross_notional(row: Mapping[str, Any], price: float | None = None, qty: float | None = None) -> float | None:
    notional = first_number(row, "gross_notional_usd", "notional", "notional_usdt", "notional_usd")
    if notional is not None and notional > 0:
        return abs(notional)
    if price is not None and price > 0 and qty is not None and qty > 0:
        return abs(price * qty)
    return None


def current_mark(row: Mapping[str, Any], mark_price: float | None = None) -> float | None:
    if mark_price is not None and mark_price > 0:
        return mark_price
    return first_number(
        row,
        "current_mark_price",
        "mark_price",
        "last_mark_price",
        "latest_price",
        "current_price",
    )


def current_mark_source(row: Mapping[str, Any], mark_source: str | None = None) -> str | None:
    if mark_source:
        return mark_source
    value = first_present(
        row,
        "current_mark_price_source",
        "mark_price_source",
        "last_mark_price_source",
        "latest_price_source",
        "current_price_source",
    )
    return str(value) if value is not None else None


def entry_time(row: Mapping[str, Any]) -> str | None:
    value = first_present(
        row,
        "entry_time",
        "entry_time_utc",
        "opened_at",
        "opened_utc",
        "opened_est",
        "fill_price_utc",
        "fill_time_utc",
        "accepted_at_utc",
        "generated_utc",
        "generated_at",
    )
    return str(value) if value is not None else None


def side_value(row: Mapping[str, Any]) -> str | None:
    return normalize_side(first_present(row, "side", "selected_action", "action", "position_side"))


def paper_fill_allowed(row: Mapping[str, Any]) -> bool:
    if row.get("paper_fill_allowed") is True:
        return True
    decision = str(row.get("decision") or row.get("paper_fill_status") or "").upper()
    if decision in {"ACCEPTED_PAPER_FILL", "OPEN_POSITION", "NETTED_INTO_EXISTING_POSITION"}:
        return row.get("paper_fill_allowed") is not False
    return False


def paper_only(row: Mapping[str, Any], *, require_explicit: bool = False) -> bool:
    if row.get("paper_only") is True:
        return True
    if require_explicit:
        return False
    return row.get("places_real_order") is not True and row.get("routes_to_live") is not True


def routes_to_live(row: Mapping[str, Any]) -> bool:
    return row.get("routes_to_live") is True or row.get("live_order") is True


def places_real_order(row: Mapping[str, Any]) -> bool:
    return row.get("places_real_order") is True or row.get("test_order") is True


def action_is_hold(row: Mapping[str, Any]) -> bool:
    raw = str(first_present(row, "action", "selected_action", "side") or "").strip().lower()
    return raw in {"hold", "none", "flat", "no_trade", "wait"}


def is_shadow_only(row: Mapping[str, Any]) -> bool:
    tier = str(first_present(row, "source_tier", "paper_opportunity_tier", "paper_execution_tier") or "").upper()
    reason = str(first_present(row, "reason", "paper_opportunity_tier_reason", "paper_fill_block_reason") or "").upper()
    decision = str(first_present(row, "decision", "paper_fill_status") or "").upper()
    return (
        tier == "SHADOW_ONLY"
        or decision == "SHADOW_OBSERVATION_ONLY"
        or "SHADOW GATE OPEN" in reason
        or "SHADOW_ONLY" in reason
    )


def _price_delta_bps(reference: float, candidate: float) -> float:
    if reference <= 0:
        return float("inf")
    return abs(candidate - reference) / reference * 10000.0


def _price_ratio(a: float, b: float) -> float:
    lower = min(abs(a), abs(b))
    upper = max(abs(a), abs(b))
    if lower <= 0:
        return float("inf")
    return upper / lower


def validate_open_position(
    row: Mapping[str, Any],
    *,
    mark_price: float | None = None,
    mark_source: str | None = None,
    mark_age_seconds: float | None = None,
    now: datetime | None = None,
    config: PositionValidityConfig = DEFAULT_VALIDITY_CONFIG,
) -> dict[str, Any]:
    now = now or utc_now()
    reasons: list[str] = []
    symbol = str(row.get("symbol") or "").upper()
    price = entry_price(row)
    qty = row_quantity(row, price)
    notional = gross_notional(row, price, qty)
    side = side_value(row)
    mark = current_mark(row, mark_price)
    mark_src = current_mark_source(row, mark_source)
    fill_ids = source_fill_ids(row)
    entry_ts_raw = entry_time(row)
    entry_dt = parse_utc(entry_ts_raw)

    if not first_present(row, "position_id", "id", "fill_id", "ledger_row_id", "intent_id"):
        reasons.append("MISSING_POSITION_ID")
    if not symbol:
        reasons.append("MISSING_SYMBOL")
    if side not in {"long", "short"}:
        reasons.append("MISSING_OR_INVALID_SIDE")
    if qty is None or qty <= 0:
        reasons.append("MISSING_OR_ZERO_QUANTITY")
    if price is None or price <= 0:
        reasons.append("MISSING_OR_INVALID_ENTRY_PRICE")
    if entry_price_source(row) is None:
        reasons.append("MISSING_ENTRY_PRICE_SOURCE")
    if not fill_ids:
        reasons.append("MISSING_ENTRY_FILL_ID")
    if not entry_ts_raw:
        reasons.append("MISSING_ENTRY_TIME")
    elif entry_dt is None:
        reasons.append("INVALID_ENTRY_TIME")
    elif entry_dt > now:
        reasons.append("ENTRY_TIME_AFTER_NOW")
    if not first_present(row, "entry_prediction_id", "prediction_id", "source_prediction_id"):
        reasons.append("MISSING_ENTRY_PREDICTION_ID")
    if not first_present(row, "entry_signal_id", "signal_id", "source_signal_id"):
        reasons.append("MISSING_ENTRY_SIGNAL_ID")
    if not first_present(row, "risk_decision_id", "risk_id"):
        reasons.append("MISSING_RISK_DECISION_ID")
    if not first_present(row, "orchestrator_decision_id", "decision_id"):
        reasons.append("MISSING_ORCHESTRATOR_DECISION_ID")
    if not paper_fill_allowed(row):
        reasons.append("PAPER_FILL_ALLOWED_NOT_TRUE")
    if not paper_only(row, require_explicit=config.require_explicit_paper_only):
        reasons.append("PAPER_ONLY_NOT_TRUE")
    if routes_to_live(row):
        reasons.append("ROUTES_TO_LIVE_TRUE")
    if places_real_order(row):
        reasons.append("PLACES_REAL_ORDER_TRUE")
    if first_number(row, "allocated_margin_usd") is None:
        reasons.append("MISSING_ALLOCATED_MARGIN_USD")
    if notional is None or notional <= 0:
        reasons.append("MISSING_GROSS_NOTIONAL_USD")
    if first_number(row, "effective_leverage", "leverage") is None:
        reasons.append("MISSING_EFFECTIVE_LEVERAGE")
    if not first_present(row, "margin_mode_simulated", "recommended_margin_mode"):
        reasons.append("MISSING_MARGIN_MODE_SIMULATED")
    if not first_present(row, "feature_cutoff", "entry_feature_cutoff"):
        reasons.append("MISSING_FEATURE_CUTOFF")
    if not first_present(row, "available_at", "entry_feature_available_at"):
        reasons.append("MISSING_AVAILABLE_AT")
    if not first_present(row, "decision_time", "entry_feature_decision_time"):
        reasons.append("MISSING_DECISION_TIME")

    available_at = parse_utc(str(first_present(row, "available_at", "entry_feature_available_at") or ""))
    decision_time = parse_utc(str(first_present(row, "decision_time", "entry_feature_decision_time") or ""))
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")

    if mark is None or mark <= 0:
        reasons.append("MISSING_CURRENT_MARK_PRICE")
    elif not mark_src:
        reasons.append("MISSING_CURRENT_MARK_PRICE_SOURCE")
    elif config.require_fresh_current_mark and mark_age_seconds is not None and mark_age_seconds > config.max_mark_age_seconds:
        reasons.append("STALE_CURRENT_MARK_PRICE")

    if is_shadow_only(row):
        reasons.append("SHADOW_ONLY_CANNOT_CREATE_ECONOMIC_POSITION")
    if action_is_hold(row):
        reasons.append("HOLD_ACTION_CANNOT_OPEN_POSITION")
    if config.require_production_cost_flag:
        if row.get("production_grade_cost_flag") is not True and row.get("production_grade_cost_evidence") is not True:
            reasons.append("MISSING_PRODUCTION_GRADE_COST_FLAG")
        if row.get("fallback_cost_flag") is True or row.get("fallback") is True:
            reasons.append("FALLBACK_COST_NOT_ALLOWED")

    if price is not None and price > 0:
        for key in ("recorded_fill_price", "mark_price_at_fill", "entry_fill_price"):
            reference = coerce_float(row.get(key))
            if reference is not None and reference > 0:
                delta_bps = _price_delta_bps(reference, price)
                if delta_bps > config.max_fill_reference_mismatch_bps:
                    reasons.append(f"ENTRY_PRICE_MISMATCHES_{key.upper()}")
        if mark is not None and mark > 0:
            ratio = _price_ratio(price, mark)
            if ratio > config.max_entry_to_current_mark_ratio_without_fill_reference:
                reasons.append("ENTRY_PRICE_CURRENT_MARK_IMPOSSIBLE_RATIO")
            if symbol == "BTCUSDT" and price < 1000.0 and mark > 10000.0:
                reasons.append("BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_CURRENT_MARK")

    valid = not reasons
    return {
        "valid": valid,
        "status": "VALID_PAPER_POSITION" if valid else "INVALID_PAPER_POSITION",
        "reasons": sorted(set(reasons)),
        "position_id": first_present(row, "position_id", "id", "fill_id", "ledger_row_id", "intent_id"),
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "entry_price": price,
        "entry_price_source": entry_price_source(row),
        "entry_fill_id": fill_ids[0] if fill_ids else None,
        "entry_time": entry_ts_raw,
        "current_mark_price": mark,
        "current_mark_price_source": mark_src,
        "current_mark_age_seconds": mark_age_seconds,
        "paper_only": paper_only(row, require_explicit=config.require_explicit_paper_only),
        "routes_to_live": routes_to_live(row),
        "places_real_order": places_real_order(row),
        "account_scope": PAPER_ACCOUNT_SCOPE if valid else QUARANTINED_ACCOUNT_SCOPE,
    }


def validate_paper_fill_write_invariant(
    row: Mapping[str, Any],
    *,
    mark_price: float | None = None,
    mark_source: str | None = None,
    mark_age_seconds: float | None = None,
    now: datetime | None = None,
    config: PositionValidityConfig = STRICT_WRITE_VALIDITY_CONFIG,
) -> dict[str, Any]:
    status = validate_open_position(
        row,
        mark_price=mark_price,
        mark_source=mark_source,
        mark_age_seconds=mark_age_seconds,
        now=now,
        config=config,
    )
    status["schema_version"] = "paper_fill_write_invariant_v1"
    status["status"] = (
        "PASSED_PAPER_FILL_WRITE_INVARIANT"
        if status["valid"]
        else "BLOCKED_PAPER_FILL_WRITE_INVARIANT"
    )
    return status


def validate_closed_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    symbol = str(row.get("symbol") or "").upper()
    entry = entry_price(row)
    exit_price = first_number(row, "exit_price", "paper_exit_price", "close_price", "avg_exit_price")
    if not first_present(row, "close_id", "paper_close_id", "outcome_label_id", "trainer_feedback_id"):
        reasons.append("MISSING_CLOSE_ID")
    if not symbol:
        reasons.append("MISSING_SYMBOL")
    if side_value(row) not in {"long", "short"}:
        reasons.append("MISSING_OR_INVALID_SIDE")
    if entry is None:
        reasons.append("MISSING_ENTRY_PRICE")
    if exit_price is None:
        reasons.append("MISSING_EXIT_PRICE")
    if first_number(row, "realized_pnl_usd", "realized_pnl_usdt", "realized_pnl", "pnl_usd") is None:
        reasons.append("MISSING_REALIZED_PNL")
    trust_source_ids = row.get("trust_source_ids") if isinstance(row.get("trust_source_ids"), Mapping) else {}
    trust_reconstructed_lineage = (
        row.get("trust_reconstructed") is True
        and bool(trust_source_ids.get("entry_prediction_id"))
        and bool(trust_source_ids.get("entry_feature_snapshot_id"))
    )
    if not source_fill_ids(row) and not first_present(row, "entry_fill_id") and not trust_reconstructed_lineage:
        reasons.append("MISSING_ENTRY_FILL_ID")
    if first_present(row, "quarantine_reasons", "quarantine_rejection_reasons", "source_quarantine_reasons") is not None:
        reasons.append("EXPLICIT_QUARANTINE_REASONS")
    quarantine_reason = str(
        first_present(row, "quarantine_reason", "reason_if_untrusted", "source_quarantine_reason") or ""
    ).upper()
    if quarantine_reason and quarantine_reason != "NONE":
        reasons.append("EXPLICIT_QUARANTINE_REASON")
    if str(row.get("account_scope") or "").upper() == QUARANTINED_ACCOUNT_SCOPE:
        reasons.append("QUARANTINED_ACCOUNT_SCOPE")
    if str(first_present(row, "validity_status", "position_validity_status") or "").upper().startswith("INVALID"):
        reasons.append("INVALID_VALIDITY_STATUS")
    if is_shadow_only(row):
        reasons.append("SHADOW_ONLY_CANNOT_CREATE_ECONOMIC_CLOSED_TRADE")
    if routes_to_live(row):
        reasons.append("ROUTES_TO_LIVE_TRUE")
    if places_real_order(row):
        reasons.append("PLACES_REAL_ORDER_TRUE")
    if entry is not None and entry > 0 and exit_price is not None and exit_price > 0:
        ratio = _price_ratio(entry, exit_price)
        if ratio > DEFAULT_VALIDITY_CONFIG.max_entry_to_current_mark_ratio_without_fill_reference:
            reasons.append("ENTRY_PRICE_EXIT_PRICE_IMPOSSIBLE_RATIO")
        if symbol == "BTCUSDT" and entry < 1000.0 and exit_price > 10000.0:
            reasons.append("BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_EXIT_PRICE")
    valid = not reasons
    return {
        "valid": valid,
        "status": "VALID_CLOSED_TRADE" if valid else "INVALID_CLOSED_TRADE",
        "reasons": sorted(set(reasons)),
        "close_id": first_present(row, "close_id", "paper_close_id", "outcome_label_id", "trainer_feedback_id"),
        "symbol": symbol,
        "account_scope": PAPER_ACCOUNT_SCOPE if valid else QUARANTINED_ACCOUNT_SCOPE,
    }


def split_valid_invalid_positions(
    rows: Iterable[Mapping[str, Any]],
    *,
    mark_prices: Mapping[str, tuple[float | None, str | None, float | None]] | None = None,
    config: PositionValidityConfig = DEFAULT_VALIDITY_CONFIG,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    mark_prices = mark_prices or {}
    for row in rows:
        item = dict(row)
        symbol = str(item.get("symbol") or "").upper()
        mark, source, age = mark_prices.get(symbol, (None, None, None))
        status = validate_open_position(item, mark_price=mark, mark_source=source, mark_age_seconds=age, config=config)
        statuses.append(status)
        if status["valid"]:
            valid.append(item)
        else:
            invalid.append({**item, "quarantine_reasons": status["reasons"], "account_scope": QUARANTINED_ACCOUNT_SCOPE})
    return valid, invalid, statuses


def split_valid_invalid_closed_trades(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        status = validate_closed_trade(item)
        statuses.append(status)
        if status["valid"]:
            valid.append(item)
        else:
            invalid.append({**item, "quarantine_reasons": status["reasons"], "account_scope": QUARANTINED_ACCOUNT_SCOPE})
    return valid, invalid, statuses


def account_truth_metadata(*, invalid_positions: int = 0, invalid_closed_trades: int = 0) -> dict[str, Any]:
    trusted = invalid_positions == 0 and invalid_closed_trades == 0
    return {
        "account_scope": PAPER_ACCOUNT_SCOPE if trusted else QUARANTINED_ACCOUNT_SCOPE,
        "source_type": "paper_sim_rebuilt_from_valid_fills",
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": invalid_positions > 0 or invalid_closed_trades > 0,
        "equity_trusted": trusted,
        "pnl_trusted": trusted,
        "reason_if_untrusted": None if trusted else "INVALID_OR_QUARANTINED_PAPER_ROWS_PRESENT",
    }
