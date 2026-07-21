"""Strict paper cross-margin portfolio liquidation evidence.

The guard consuming this module can force a paper close.  Consequently this
module never fills missing position, leverage, maintenance, mark, or PnL data
with defaults.  A portfolio result is authoritative only when the open-position
ledger and the account-margin ledger form one exact, generation-bound snapshot.

Pure computation only: no Redis, exchange, order, leverage, or margin mutation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.security.local_evidence_hmac import (
    AUTH_FIELDS,
    PAPER_AUTHORITY_TRUST_DOMAIN,
    seal_hmac_sha256,
    verify_hmac_sha256,
)

SCHEMA_VERSION = "cross_margin_liquidation_v2"
POSITION_EVIDENCE_VERSION = "cross_margin_position_evidence_v1"
ADAPTIVE_STRESS_SCHEMA_VERSION = "adaptive_portfolio_stress_v1"
ADAPTIVE_STRESS_SOURCE_OBSERVATIONS_SCHEMA_VERSION = (
    "adaptive_portfolio_stress_source_observations_v1"
)
_ABS_TOL = 1e-7
_REL_TOL = 1e-9


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _same_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


def _sha256(value: Any) -> str | None:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _exact_text(row: Mapping[str, Any], field: str) -> str | None:
    value = row.get(field)
    return value if isinstance(value, str) and bool(value.strip()) else None


def _paper_safety_valid(row: Mapping[str, Any]) -> bool:
    return (
        row.get("paper_only") is True
        and row.get("routes_to_live") is False
        and row.get("places_real_order") is False
    )


def adaptive_stress_source_observations_sha256(
    *,
    account: Mapping[str, Any],
    positions: Sequence[Mapping[str, Any]],
    position_margin_rows: Sequence[Mapping[str, Any]],
) -> str:
    """Bind stress authority to the exact account/position input snapshot."""

    digest = _sha256(
        {
            "schema_version": ADAPTIVE_STRESS_SOURCE_OBSERVATIONS_SCHEMA_VERSION,
            "account": dict(account),
            "positions": [dict(row) for row in positions],
            "position_margin_rows": [dict(row) for row in position_margin_rows],
        }
    )
    if digest is None:
        raise ValueError("ADAPTIVE_STRESS_SOURCE_OBSERVATIONS_NOT_CANONICAL_JSON")
    return digest


def seal_adaptive_stress_envelope(
    material: Mapping[str, Any],
    *,
    authentication_key_id: str,
    authentication_key: bytes | bytearray,
) -> dict[str, Any]:
    """Seal caller-derived PIT stress material without inventing scenarios."""

    payload = {
        key: value for key, value in dict(material).items() if key not in AUTH_FIELDS
    }
    payload.pop("evidence_sha256", None)
    evidence_hash = _sha256(payload)
    if evidence_hash is None:
        raise ValueError("ADAPTIVE_STRESS_ENVELOPE_NOT_CANONICAL_JSON")
    return seal_hmac_sha256(
        {**payload, "evidence_sha256": evidence_hash},
        trust_domain=PAPER_AUTHORITY_TRUST_DOMAIN,
        authentication_key_id=authentication_key_id,
        authentication_key=authentication_key,
    )


def _margin_mode(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"cross", "cross_paper_simulated"}:
        return "cross"
    if normalized in {"isolated", "isolated_paper_simulated"}:
        return "isolated"
    return None


def _quantity_and_side(position: Mapping[str, Any]) -> tuple[float | None, str | None, str | None]:
    """Normalize only the two explicit quantity contracts.

    Paper ``net_quantity`` is a positive magnitude and therefore requires an
    explicit side.  An exchange-style signed ``positionAmt`` may infer side
    only when its schema explicitly declares one-way/BOTH mode.
    """

    if "net_quantity" in position:
        quantity = _float(position.get("net_quantity"))
        side = str(position.get("side") or "").strip().lower()
        if quantity is None or quantity <= 0.0:
            return None, None, "NET_QUANTITY_MISSING_NONFINITE_OR_NON_POSITIVE"
        if side not in {"long", "short"}:
            return None, None, "NET_QUANTITY_REQUIRES_EXPLICIT_LONG_OR_SHORT_SIDE"
        return quantity, side, None

    amount_field = next(
        (field for field in ("positionAmt", "position_amt") if field in position),
        None,
    )
    if amount_field is None:
        return None, None, "POSITION_QUANTITY_CONTRACT_MISSING"
    amount = _float(position.get(amount_field))
    position_side = str(
        position.get("positionSide") or position.get("position_side") or ""
    ).strip().upper()
    if amount is None or amount == 0.0:
        return None, None, "SIGNED_POSITION_AMOUNT_MISSING_NONFINITE_OR_ZERO"
    if position_side != "BOTH":
        return None, None, "SIGNED_POSITION_AMOUNT_SIDE_INFERENCE_REQUIRES_BOTH_MODE"
    return abs(amount), "long" if amount > 0.0 else "short", None


def _blocked_snapshot(
    *,
    generated_utc: str,
    position_count: int,
    margin_row_count: int,
    reasons: list[str],
    invalid_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "authority_complete": False,
        "portfolio_level_computed": False,
        "per_position_only": False,
        "risk_decision_blocked": True,
        "core_system_blocked": False,
        "block_reasons": unique_reasons,
        "input_open_position_count": position_count,
        "input_position_margin_row_count": margin_row_count,
        "open_position_count": None,
        "positions": [],
        "position_liquidation_register": [],
        "correlated_shock_scenarios": {},
        "worst_case_scenario": None,
        "worst_case_liquidation_buffer_usd": None,
        "worst_case_liquidation_breached": None,
        "adaptive_stress_authority_complete": False,
        "adaptive_stress_block_reasons": unique_reasons,
        "cross_position_count": None,
        "isolated_position_count": None,
        "invalid_position_rows": list(invalid_rows or []),
        "raw_key_exposed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def _strict_position_row(
    position: Mapping[str, Any],
    margin_row: Mapping[str, Any],
    *,
    generated_at: datetime,
    expected_paper_session_id: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    position_id = _exact_text(position, "position_id")
    generation_id = _exact_text(position, "position_generation_id")
    margin_position_id = _exact_text(margin_row, "row_id")
    margin_generation_id = _exact_text(margin_row, "position_generation_id")
    if position_id is None:
        reasons.append("POSITION_ID_MISSING_OR_INVALID")
    if generation_id is None:
        reasons.append("POSITION_GENERATION_ID_MISSING_OR_INVALID")
    if margin_position_id != position_id:
        reasons.append("MARGIN_ROW_ID_DOES_NOT_EQUAL_POSITION_ID")
    if margin_generation_id != generation_id:
        reasons.append("MARGIN_ROW_GENERATION_DOES_NOT_EQUAL_POSITION_GENERATION")
    if position.get("paper_session_id") != expected_paper_session_id:
        reasons.append("POSITION_PAPER_SESSION_ID_MISMATCH")
    if margin_row.get("paper_session_id") != expected_paper_session_id:
        reasons.append("MARGIN_ROW_PAPER_SESSION_ID_MISMATCH")
    if not _paper_safety_valid(position):
        reasons.append("POSITION_PAPER_ROUTE_SAFETY_INVALID")
    if not _paper_safety_valid(margin_row):
        reasons.append("MARGIN_ROW_PAPER_ROUTE_SAFETY_INVALID")
    if margin_row.get("valid") is not True:
        reasons.append("POSITION_MARGIN_ROW_NOT_VALID")
    if margin_row.get("accounting_scope") != "OPEN_EXECUTED_POSITION":
        reasons.append("POSITION_MARGIN_ROW_SCOPE_INVALID")

    symbol = _exact_text(position, "symbol")
    margin_symbol = _exact_text(margin_row, "symbol")
    if symbol is None:
        reasons.append("POSITION_SYMBOL_MISSING_OR_INVALID")
        symbol = ""
    else:
        symbol = symbol.upper()
    if margin_symbol is None or margin_symbol.upper() != symbol:
        reasons.append("POSITION_MARGIN_SYMBOL_MISMATCH")

    margin_mode = _margin_mode(position.get("margin_mode_simulated"))
    margin_row_mode = _margin_mode(margin_row.get("margin_mode_simulated"))
    if margin_mode is None:
        reasons.append("POSITION_MARGIN_MODE_MISSING_OR_INVALID")
    if margin_row_mode is None:
        reasons.append("POSITION_MARGIN_ROW_MODE_MISSING_OR_INVALID")
    if (
        margin_mode is not None
        and margin_row_mode is not None
        and margin_mode != margin_row_mode
    ):
        reasons.append("POSITION_MARGIN_MODE_MISMATCH")

    quantity, side, quantity_reason = _quantity_and_side(position)
    if quantity_reason is not None:
        reasons.append(quantity_reason)

    leverage = _float(position.get("effective_leverage"))
    margin_leverage = _float(margin_row.get("effective_leverage"))
    if leverage is None or leverage < 1.0:
        reasons.append("POSITION_EFFECTIVE_LEVERAGE_MISSING_NONFINITE_OR_BELOW_ONE")
    if margin_leverage is None or margin_leverage < 1.0:
        reasons.append("MARGIN_EFFECTIVE_LEVERAGE_MISSING_NONFINITE_OR_BELOW_ONE")
    if (
        leverage is not None
        and margin_leverage is not None
        and not _same_number(leverage, margin_leverage)
    ):
        reasons.append("POSITION_MARGIN_EFFECTIVE_LEVERAGE_MISMATCH")

    entry_price = _float(position.get("avg_entry_price"))
    if entry_price is None or entry_price <= 0.0:
        reasons.append("POSITION_ENTRY_PRICE_MISSING_NONFINITE_OR_NON_POSITIVE")

    mark_price = _float(position.get("last_mark_price"))
    position_maintenance_mark = _float(position.get("maintenance_margin_mark_price"))
    margin_mark = _float(margin_row.get("maintenance_margin_mark_price"))
    if mark_price is None or mark_price <= 0.0:
        reasons.append("POSITION_MARK_PRICE_MISSING_NONFINITE_OR_NON_POSITIVE")
    if position_maintenance_mark is None or position_maintenance_mark <= 0.0:
        reasons.append("POSITION_MAINTENANCE_MARK_MISSING_NONFINITE_OR_NON_POSITIVE")
    if margin_mark is None or margin_mark <= 0.0:
        reasons.append("MARGIN_MAINTENANCE_MARK_MISSING_NONFINITE_OR_NON_POSITIVE")
    mark_values = [
        value
        for value in (mark_price, position_maintenance_mark, margin_mark)
        if value is not None
    ]
    if len(mark_values) == 3 and any(
        not _same_number(mark_values[0], value) for value in mark_values[1:]
    ):
        reasons.append("POSITION_MARGIN_MARK_PRICE_MISMATCH")

    position_mark_time = _exact_text(position, "maintenance_margin_mark_time")
    margin_mark_time = _exact_text(margin_row, "maintenance_margin_mark_time")
    mark_event_time = _exact_text(position, "maintenance_margin_mark_event_time")
    mark_generated_time = _exact_text(
        position, "maintenance_margin_mark_generated_at"
    )
    mark_available_time = _exact_text(
        position, "maintenance_margin_mark_available_at"
    )
    mark_decision_time = _exact_text(
        position, "maintenance_margin_mark_decision_time"
    )
    mark_source = _exact_text(position, "maintenance_margin_mark_source")
    mark_hash = _exact_text(position, "maintenance_margin_mark_evidence_sha256")
    cadence_policy_version = _exact_text(
        position, "maintenance_margin_mark_cadence_policy_version"
    )
    consumer_boundary = _exact_text(
        position, "maintenance_margin_mark_consumer_validation_boundary"
    )
    freshness_budget = _float(
        position.get("maintenance_margin_mark_freshness_budget_seconds")
    )
    mark_clock_fields = (
        "maintenance_margin_mark_time",
        "maintenance_margin_mark_event_time",
        "maintenance_margin_mark_generated_at",
        "maintenance_margin_mark_available_at",
        "maintenance_margin_mark_decision_time",
        "maintenance_margin_mark_source",
        "maintenance_margin_mark_evidence_sha256",
        "maintenance_margin_mark_contract_authoritative",
        "maintenance_margin_mark_freshness_budget_seconds",
        "maintenance_margin_mark_cadence_policy_version",
        "maintenance_margin_mark_consumer_validation_boundary",
    )
    for field in mark_clock_fields:
        if margin_row.get(field) != position.get(field):
            reasons.append(f"POSITION_MARGIN_{field.upper()}_MISMATCH")
    event_at = _utc(mark_event_time)
    mark_generated_at = _utc(mark_generated_time)
    mark_available_at = _utc(mark_available_time)
    mark_decision_at = _utc(mark_decision_time)
    if (
        position_mark_time is None
        or margin_mark_time != position_mark_time
        or position_mark_time != mark_event_time
    ):
        reasons.append("POSITION_MARGIN_MARK_TIME_MISMATCH_OR_MISSING")
    if None in (event_at, mark_generated_at, mark_available_at, mark_decision_at):
        reasons.append("POSITION_MARK_CLOCKS_INVALID")
    elif not (
        event_at
        <= mark_generated_at
        <= mark_available_at
        <= mark_decision_at
        <= generated_at
    ):
        reasons.append("POSITION_MARK_CLOCK_ORDER_INVALID")
    if (
        freshness_budget is None
        or freshness_budget <= 0.0
        or event_at is None
        or mark_decision_at is None
        or (mark_decision_at - event_at).total_seconds() > freshness_budget
    ):
        reasons.append("POSITION_MARK_ADAPTIVE_FRESHNESS_INVALID_OR_STALE")
    if (
        position.get("maintenance_margin_mark_contract_authoritative") is not True
        or mark_source is None
        or mark_hash is None
        or len(mark_hash) != 64
        or mark_hash != mark_hash.lower()
        or any(char not in "0123456789abcdef" for char in mark_hash)
        or cadence_policy_version is None
        or consumer_boundary != "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
    ):
        reasons.append("POSITION_MARK_AUTHORITY_CONTRACT_INVALID")

    rate = _float(position.get("maintenance_margin_rate"))
    margin_rate = _float(margin_row.get("maintenance_margin_rate"))
    if rate is None or not 0.0 < rate < 1.0:
        reasons.append("POSITION_MAINTENANCE_RATE_MISSING_OR_INVALID")
    if margin_rate is None or not 0.0 < margin_rate < 1.0:
        reasons.append("MARGIN_MAINTENANCE_RATE_MISSING_OR_INVALID")
    if rate is not None and margin_rate is not None and not _same_number(rate, margin_rate):
        reasons.append("POSITION_MARGIN_MAINTENANCE_RATE_MISMATCH")

    cum = _float(position.get("maintenance_margin_cum"))
    margin_cum = _float(margin_row.get("maintenance_margin_cum"))
    if cum is None or cum < 0.0:
        reasons.append("POSITION_MAINTENANCE_CUM_MISSING_OR_INVALID")
    if margin_cum is None or margin_cum < 0.0:
        reasons.append("MARGIN_MAINTENANCE_CUM_MISSING_OR_INVALID")
    if cum is not None and margin_cum is not None and not _same_number(cum, margin_cum):
        reasons.append("POSITION_MARGIN_MAINTENANCE_CUM_MISMATCH")

    position_mark_notional = _float(position.get("maintenance_margin_notional_usd"))
    margin_mark_notional = _float(margin_row.get("maintenance_margin_notional_usd"))
    position_entry_notional = _float(position.get("gross_notional_usd"))
    margin_entry_notional = _float(margin_row.get("canonical_notional_usd"))
    calculated_mark_notional = (
        quantity * mark_price
        if quantity is not None and mark_price is not None
        else None
    )
    calculated_entry_notional = (
        quantity * entry_price
        if quantity is not None and entry_price is not None
        else None
    )
    for value, reason in (
        (position_mark_notional, "POSITION_MARK_NOTIONAL_MISSING_NONFINITE_OR_NON_POSITIVE"),
        (margin_mark_notional, "MARGIN_MARK_NOTIONAL_MISSING_NONFINITE_OR_NON_POSITIVE"),
        (position_entry_notional, "POSITION_ENTRY_NOTIONAL_MISSING_NONFINITE_OR_NON_POSITIVE"),
        (margin_entry_notional, "MARGIN_ENTRY_NOTIONAL_MISSING_NONFINITE_OR_NON_POSITIVE"),
    ):
        if value is None or value <= 0.0:
            reasons.append(reason)
    if calculated_mark_notional is not None and any(
        value is not None and not _same_number(calculated_mark_notional, value)
        for value in (position_mark_notional, margin_mark_notional)
    ):
        reasons.append("MARK_BASED_NOTIONAL_RECONCILIATION_FAILED")
    if calculated_entry_notional is not None and any(
        value is not None and not _same_number(calculated_entry_notional, value)
        for value in (position_entry_notional, margin_entry_notional)
    ):
        reasons.append("ENTRY_BASED_NOTIONAL_RECONCILIATION_FAILED")

    position_maintenance = _float(position.get("maintenance_margin_estimate"))
    margin_maintenance = _float(margin_row.get("maintenance_margin_estimate"))
    calculated_maintenance = (
        max(0.0, calculated_mark_notional * rate - cum)
        if calculated_mark_notional is not None and rate is not None and cum is not None
        else None
    )
    if position_maintenance is None or position_maintenance < 0.0:
        reasons.append("POSITION_MAINTENANCE_ESTIMATE_MISSING_OR_INVALID")
    if margin_maintenance is None or margin_maintenance < 0.0:
        reasons.append("MARGIN_MAINTENANCE_ESTIMATE_MISSING_OR_INVALID")
    if calculated_maintenance is not None and any(
        value is not None and not _same_number(calculated_maintenance, value)
        for value in (position_maintenance, margin_maintenance)
    ):
        reasons.append("MARK_BASED_MAINTENANCE_RECONCILIATION_FAILED")

    pnl_usd = _float(position.get("unrealized_pnl"))
    margin_pnl_usd = _float(margin_row.get("unrealized_pnl_usd"))
    pnl_bps = _float(position.get("unrealized_pnl_bps"))
    margin_pnl_bps = _float(margin_row.get("unrealized_pnl_bps"))
    if pnl_usd is None or margin_pnl_usd is None:
        reasons.append("UNREALIZED_PNL_USD_EVIDENCE_MISSING_OR_NONFINITE")
    elif not _same_number(pnl_usd, margin_pnl_usd):
        reasons.append("POSITION_MARGIN_UNREALIZED_PNL_USD_MISMATCH")
    if pnl_bps is None or margin_pnl_bps is None:
        reasons.append("UNREALIZED_PNL_BPS_EVIDENCE_MISSING_OR_NONFINITE")
    elif not _same_number(pnl_bps, margin_pnl_bps):
        reasons.append("POSITION_MARGIN_UNREALIZED_PNL_BPS_MISMATCH")
    calculated_pnl_usd = None
    calculated_pnl_bps = None
    if all(
        value is not None for value in (quantity, entry_price, mark_price, side)
    ):
        direction = 1.0 if side == "long" else -1.0
        calculated_pnl_usd = direction * quantity * (mark_price - entry_price)
        calculated_pnl_bps = direction * (mark_price - entry_price) / entry_price * 10_000.0
        if pnl_usd is not None and not _same_number(calculated_pnl_usd, pnl_usd):
            reasons.append("UNREALIZED_PNL_USD_RECOMPUTE_MISMATCH")
        if pnl_bps is not None and not _same_number(calculated_pnl_bps, pnl_bps):
            reasons.append("UNREALIZED_PNL_BPS_RECOMPUTE_MISMATCH")

    canonical_margin = _float(margin_row.get("canonical_margin_usd"))
    calculated_margin = (
        calculated_entry_notional / leverage
        if calculated_entry_notional is not None and leverage is not None and leverage >= 1.0
        else None
    )
    if canonical_margin is None or canonical_margin <= 0.0:
        reasons.append("CANONICAL_POSITION_MARGIN_MISSING_OR_INVALID")
    elif calculated_margin is not None and not _same_number(canonical_margin, calculated_margin):
        reasons.append("CANONICAL_POSITION_MARGIN_RECONCILIATION_FAILED")

    if reasons:
        return None, list(dict.fromkeys(reasons))

    assert all(
        value is not None
        for value in (
            position_id,
            generation_id,
            quantity,
            side,
            leverage,
            entry_price,
            mark_price,
            position_mark_time,
            mark_event_time,
            mark_generated_time,
            mark_available_time,
            mark_decision_time,
            mark_source,
            mark_hash,
            freshness_budget,
            cadence_policy_version,
            consumer_boundary,
            margin_mode,
            rate,
            cum,
            calculated_mark_notional,
            calculated_entry_notional,
            calculated_maintenance,
            pnl_usd,
            pnl_bps,
            canonical_margin,
        )
    )
    evidence = {
        "schema_version": POSITION_EVIDENCE_VERSION,
        "position_id": position_id,
        "position_generation_id": generation_id,
        "symbol": symbol,
        "margin_mode": margin_mode,
        "side": side,
        "position_quantity": quantity,
        "entry_price": entry_price,
        "mark_price": mark_price,
        "mark_time": position_mark_time,
        "mark_event_time": mark_event_time,
        "mark_generated_at": mark_generated_time,
        "mark_available_at": mark_available_time,
        "mark_decision_time": mark_decision_time,
        "mark_source": mark_source,
        "mark_evidence_sha256": mark_hash,
        "mark_freshness_budget_seconds": freshness_budget,
        "mark_cadence_policy_version": cadence_policy_version,
        "mark_consumer_validation_boundary": consumer_boundary,
        "entry_notional_usd": calculated_entry_notional,
        "mark_notional_usd": calculated_mark_notional,
        "effective_leverage": leverage,
        "canonical_margin_usd": canonical_margin,
        "maintenance_margin_rate": rate,
        "maintenance_margin_cum": cum,
        "maintenance_margin_usd": calculated_maintenance,
        "unrealized_pnl_usd": pnl_usd,
        "unrealized_pnl_bps": pnl_bps,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    evidence_hash = _sha256(evidence)
    if evidence_hash is None:
        return None, ["POSITION_EVIDENCE_HASH_FAILED"]
    return {**evidence, "position_evidence_sha256": evidence_hash}, []


def _validated_adaptive_stress(
    envelope: Mapping[str, Any] | None,
    *,
    generated_at: datetime,
    paper_session_id: str,
    cross_symbols: set[str],
    authentication_keys: Mapping[str, bytes | bytearray] | None,
    expected_source_observations_sha256: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if not isinstance(envelope, Mapping):
        return None, ["ADAPTIVE_STRESS_ENVELOPE_MISSING"]
    material = {
        key: value for key, value in dict(envelope).items() if key not in AUTH_FIELDS
    }
    supplied_hash = material.pop("evidence_sha256", None)
    if envelope.get("schema_version") != ADAPTIVE_STRESS_SCHEMA_VERSION:
        reasons.append("ADAPTIVE_STRESS_SCHEMA_VERSION_INVALID")
    if envelope.get("authority_complete") is not True:
        reasons.append("ADAPTIVE_STRESS_UPSTREAM_AUTHORITY_INCOMPLETE")
    if envelope.get("paper_session_id") != paper_session_id:
        reasons.append("ADAPTIVE_STRESS_PAPER_SESSION_MISMATCH")
    if supplied_hash != _sha256(material):
        reasons.append("ADAPTIVE_STRESS_EVIDENCE_HASH_INVALID")
    reasons.extend(
        verify_hmac_sha256(
            envelope,
            expected_trust_domain=PAPER_AUTHORITY_TRUST_DOMAIN,
            authentication_keys=authentication_keys,
            reason_prefix="ADAPTIVE_STRESS",
        )
    )
    policy_version = _exact_text(envelope, "stress_policy_version")
    cadence_version = _exact_text(envelope, "cadence_policy_version")
    producer = _exact_text(envelope, "producer")
    auth_boundary = _exact_text(envelope, "auth_boundary")
    source_observations_hash = _exact_text(
        envelope, "source_observations_sha256"
    )
    if policy_version is None or cadence_version is None:
        reasons.append("ADAPTIVE_STRESS_POLICY_OR_CADENCE_VERSION_MISSING")
    if producer != "adaptive_portfolio_stress_controller":
        reasons.append("ADAPTIVE_STRESS_PRODUCER_INVALID")
    if auth_boundary != "PAPER_ADAPTIVE_STRESS_PIT_V1":
        reasons.append("ADAPTIVE_STRESS_AUTH_BOUNDARY_INVALID")
    if (
        source_observations_hash is None
        or len(source_observations_hash) != 64
        or any(character not in "0123456789abcdef" for character in source_observations_hash)
    ):
        reasons.append("ADAPTIVE_STRESS_SOURCE_OBSERVATIONS_HASH_INVALID")
    elif not hmac.compare_digest(
        source_observations_hash,
        expected_source_observations_sha256,
    ):
        reasons.append("ADAPTIVE_STRESS_SOURCE_OBSERVATIONS_MISMATCH")
    freshness_budget = _float(envelope.get("freshness_budget_seconds"))
    guard_lifetime = _float(envelope.get("guard_lifetime_seconds"))
    if freshness_budget is None or freshness_budget <= 0.0:
        reasons.append("ADAPTIVE_STRESS_FRESHNESS_BUDGET_INVALID")
    if guard_lifetime is None or guard_lifetime <= 0.0:
        reasons.append("ADAPTIVE_STRESS_GUARD_LIFETIME_INVALID")
    generated = _utc(envelope.get("generated_at"))
    available = _utc(envelope.get("available_at"))
    decision = _utc(envelope.get("decision_time"))
    if generated is None or available is None or decision is None:
        reasons.append("ADAPTIVE_STRESS_CLOCKS_INVALID")
    elif not generated <= available <= decision <= generated_at:
        reasons.append("ADAPTIVE_STRESS_CLOCK_ORDER_INVALID")
    elif (
        freshness_budget is None
        or (generated_at - decision).total_seconds() > freshness_budget
    ):
        reasons.append("ADAPTIVE_STRESS_STALE_AT_PORTFOLIO_DECISION")
    recovery_reserve = _float(envelope.get("recovery_reserve_usd"))
    if recovery_reserve is None or recovery_reserve < 0.0:
        reasons.append("ADAPTIVE_STRESS_RECOVERY_RESERVE_INVALID")
    scenarios = envelope.get("scenarios")
    normalized_scenarios: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if not isinstance(scenarios, list) or not scenarios:
        reasons.append("ADAPTIVE_STRESS_SCENARIOS_MISSING")
    else:
        for index, raw in enumerate(scenarios):
            if not isinstance(raw, Mapping):
                reasons.append(f"ADAPTIVE_STRESS_SCENARIO_{index}_NOT_MAPPING")
                continue
            scenario_id = _exact_text(raw, "scenario_id")
            moves = raw.get("symbol_moves")
            if scenario_id is None or scenario_id in seen_ids:
                reasons.append("ADAPTIVE_STRESS_SCENARIO_ID_INVALID_OR_DUPLICATE")
                continue
            seen_ids.add(scenario_id)
            if not isinstance(moves, Mapping) or not cross_symbols.issubset(set(moves)):
                reasons.append(
                    f"ADAPTIVE_STRESS_SCENARIO_{scenario_id}_SYMBOL_COVERAGE_MISMATCH"
                )
                continue
            normalized_moves: dict[str, float] = {}
            invalid_move = False
            for symbol, value in moves.items():
                move = _float(value)
                if move is None or move <= -1.0:
                    invalid_move = True
                    break
                normalized_symbol = str(symbol or "").upper()
                if not normalized_symbol:
                    invalid_move = True
                    break
                normalized_moves[normalized_symbol] = move
            if invalid_move:
                reasons.append(
                    f"ADAPTIVE_STRESS_SCENARIO_{scenario_id}_MOVE_INVALID"
                )
                continue
            normalized_scenarios.append(
                {"scenario_id": scenario_id, "symbol_moves": normalized_moves}
            )
    raw_hedge_maintenance = envelope.get("hedge_candidate_maintenance")
    normalized_hedge_maintenance: dict[str, dict[str, Any]] = {}
    if raw_hedge_maintenance not in (None, {}):
        if not isinstance(raw_hedge_maintenance, Mapping):
            reasons.append("ADAPTIVE_HEDGE_CANDIDATE_MAINTENANCE_NOT_MAPPING")
        else:
            for raw_symbol, raw_evidence in raw_hedge_maintenance.items():
                symbol = str(raw_symbol or "").strip().upper()
                if not symbol or not isinstance(raw_evidence, Mapping):
                    reasons.append("ADAPTIVE_HEDGE_CANDIDATE_MAINTENANCE_ROW_INVALID")
                    continue
                rate = _float(raw_evidence.get("maintenance_margin_rate"))
                cum = _float(raw_evidence.get("maintenance_margin_cum"))
                evidence_hash = _exact_text(raw_evidence, "evidence_sha256")
                if (
                    raw_evidence.get("authority_complete") is not True
                    or raw_evidence.get("source")
                    != "AUTHENTICATED_BINANCE_USDM_LEVERAGE_BRACKET"
                    or rate is None
                    or not 0.0 < rate < 1.0
                    or cum is None
                    or cum < 0.0
                    or evidence_hash is None
                    or len(evidence_hash) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in evidence_hash
                    )
                ):
                    reasons.append(
                        f"ADAPTIVE_HEDGE_CANDIDATE_MAINTENANCE_INVALID:{symbol}"
                    )
                    continue
                normalized_hedge_maintenance[symbol] = {
                    "authority_complete": True,
                    "source": raw_evidence["source"],
                    "maintenance_margin_rate": rate,
                    "maintenance_margin_cum": cum,
                    "evidence_sha256": evidence_hash,
                }
    if reasons:
        return None, list(dict.fromkeys(reasons))
    return {
        "stress_policy_version": policy_version,
        "cadence_policy_version": cadence_version,
        "producer": producer,
        "auth_boundary": auth_boundary,
        "source_observations_sha256": source_observations_hash,
        "evidence_sha256": supplied_hash,
        "evidence_auth_key_id": envelope.get("evidence_auth_key_id"),
        "evidence_auth_trust_domain": envelope.get("evidence_auth_trust_domain"),
        "evidence_hmac_sha256": envelope.get("evidence_hmac_sha256"),
        "freshness_budget_seconds": freshness_budget,
        "guard_lifetime_seconds": guard_lifetime,
        "recovery_reserve_usd": recovery_reserve,
        "generated_at": envelope.get("generated_at"),
        "available_at": envelope.get("available_at"),
        "decision_time": envelope.get("decision_time"),
        "scenarios": normalized_scenarios,
        "hedge_candidate_maintenance": normalized_hedge_maintenance,
    }, []


def build_portfolio_liquidation_snapshot(
    *,
    account: Mapping[str, Any],
    positions: Sequence[Mapping[str, Any]],
    position_margin_rows: Sequence[Mapping[str, Any]] | None = None,
    generated_utc: str,
    adaptive_stress_envelope: Mapping[str, Any] | None = None,
    adaptive_stress_authentication_keys: Mapping[
        str, bytes | bytearray
    ] | None = None,
) -> dict[str, Any]:
    """Build an authoritative portfolio snapshot or an explicit blocked result."""

    raw_positions = list(positions) if isinstance(positions, list | tuple) else []
    raw_margin_rows = (
        list(position_margin_rows)
        if isinstance(position_margin_rows, list | tuple)
        else []
    )
    reasons: list[str] = []
    invalid_rows: list[dict[str, Any]] = []
    generated_at = _utc(generated_utc)
    if generated_at is None:
        reasons.append("SNAPSHOT_GENERATED_UTC_INVALID")
    if not isinstance(account, Mapping):
        reasons.append("ACCOUNT_SNAPSHOT_NOT_A_MAPPING")
        account = {}
    paper_session_id = _exact_text(account, "paper_session_id")
    if paper_session_id is None:
        reasons.append("ACCOUNT_PAPER_SESSION_ID_MISSING_OR_INVALID")
    if not isinstance(positions, list | tuple):
        reasons.append("OPEN_POSITIONS_NOT_AN_EXPLICIT_SEQUENCE")
    if not isinstance(position_margin_rows, list | tuple):
        reasons.append("POSITION_MARGIN_ROWS_NOT_AN_EXPLICIT_SEQUENCE")
    if len(raw_positions) != len(raw_margin_rows):
        reasons.append("OPEN_POSITION_AND_MARGIN_ROW_COUNTS_DIFFER")

    margin_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    margin_position_ids: set[str] = set()
    margin_generation_ids: set[str] = set()
    for index, row in enumerate(raw_margin_rows):
        if not isinstance(row, Mapping):
            reasons.append("POSITION_MARGIN_ROW_NOT_A_MAPPING")
            invalid_rows.append({"margin_row_index": index, "reasons": ["NOT_A_MAPPING"]})
            continue
        key = (_exact_text(row, "row_id") or "", _exact_text(row, "position_generation_id") or "")
        if not all(key):
            reasons.append("POSITION_MARGIN_ROW_IDENTITY_INCOMPLETE")
        elif key in margin_index:
            reasons.append("DUPLICATE_POSITION_MARGIN_ROW_IDENTITY")
        else:
            if key[0] in margin_position_ids:
                reasons.append("POSITION_MARGIN_ROW_ID_REUSED_ACROSS_GENERATIONS")
            if key[1] in margin_generation_ids:
                reasons.append("POSITION_MARGIN_GENERATION_ID_REUSED")
            margin_position_ids.add(key[0])
            margin_generation_ids.add(key[1])
            margin_index[key] = row

    seen_positions: set[tuple[str, str]] = set()
    seen_position_ids: set[str] = set()
    seen_generation_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    if generated_at is not None:
        for index, position in enumerate(raw_positions):
            if not isinstance(position, Mapping):
                reasons.append("OPEN_POSITION_ROW_NOT_A_MAPPING")
                invalid_rows.append({"position_index": index, "reasons": ["NOT_A_MAPPING"]})
                continue
            key = (
                _exact_text(position, "position_id") or "",
                _exact_text(position, "position_generation_id") or "",
            )
            if not all(key):
                reasons.append("OPEN_POSITION_IDENTITY_INCOMPLETE")
                invalid_rows.append({"position_index": index, "reasons": ["IDENTITY_INCOMPLETE"]})
                continue
            if key in seen_positions:
                reasons.append("DUPLICATE_OPEN_POSITION_IDENTITY")
                invalid_rows.append(
                    {
                        "position_id": key[0],
                        "position_generation_id": key[1],
                        "reasons": ["DUPLICATE"],
                    }
                )
                continue
            if key[0] in seen_position_ids:
                reasons.append("OPEN_POSITION_ID_REUSED_ACROSS_GENERATIONS")
            if key[1] in seen_generation_ids:
                reasons.append("OPEN_POSITION_GENERATION_ID_REUSED")
            seen_positions.add(key)
            seen_position_ids.add(key[0])
            seen_generation_ids.add(key[1])
            margin_row = margin_index.get(key)
            if margin_row is None:
                reasons.append("OPEN_POSITION_HAS_NO_EXACT_MARGIN_ROW")
                invalid_rows.append(
                    {
                        "position_id": key[0],
                        "position_generation_id": key[1],
                        "reasons": ["MARGIN_ROW_MISSING"],
                    }
                )
                continue
            row, row_reasons = _strict_position_row(
                position,
                margin_row,
                generated_at=generated_at,
                expected_paper_session_id=paper_session_id or "",
            )
            if row is None:
                reasons.append("OPEN_POSITION_MARGIN_EVIDENCE_INVALID")
                invalid_rows.append(
                    {
                        "position_id": key[0],
                        "position_generation_id": key[1],
                        "reasons": row_reasons,
                    }
                )
            else:
                normalized.append(row)

    extra_margin_keys = sorted(set(margin_index) - seen_positions)
    if extra_margin_keys:
        reasons.append("POSITION_MARGIN_ROWS_CONTAIN_EXTRAS_OR_REUSE")
        invalid_rows.extend(
            {
                "position_id": position_id,
                "position_generation_id": generation_id,
                "reasons": ["MARGIN_ROW_HAS_NO_EXACT_OPEN_POSITION"],
            }
            for position_id, generation_id in extra_margin_keys
        )

    margin_balance = _float(account.get("equity_usd"))
    wallet_balance = _float(account.get("wallet_balance_usd"))
    available = _float(account.get("free_margin_usd"))
    declared_unrealized = _float(account.get("unrealized_pnl_usd"))
    declared_used_margin = _float(account.get("used_margin_usd"))
    declared_margin_base = _float(account.get("margin_base_usd"))
    newly_reserved = _float(account.get("newly_reserved_margin_usd"))
    reservations_included = account.get("newly_reserved_included_in_used_margin")
    row_unrealized = math.fsum(
        row["unrealized_pnl_usd"] for row in normalized
    )
    row_used_margin = math.fsum(
        row["canonical_margin_usd"] for row in normalized
    )
    cross_rows = [row for row in normalized if row["margin_mode"] == "cross"]
    isolated_rows = [row for row in normalized if row["margin_mode"] == "isolated"]
    cross_unrealized = math.fsum(
        row["unrealized_pnl_usd"] for row in cross_rows
    )
    isolated_used_margin = math.fsum(
        row["canonical_margin_usd"] for row in isolated_rows
    )
    if margin_balance is None or margin_balance <= 0.0:
        reasons.append("ACCOUNT_MARGIN_BALANCE_MISSING_NONFINITE_OR_NON_POSITIVE")
    if wallet_balance is None or wallet_balance <= 0.0:
        reasons.append("ACCOUNT_WALLET_BALANCE_MISSING_NONFINITE_OR_NON_POSITIVE")
    if available is None or available < 0.0:
        reasons.append("ACCOUNT_AVAILABLE_MARGIN_MISSING_NONFINITE_OR_NEGATIVE")
    if declared_unrealized is None:
        reasons.append("ACCOUNT_UNREALIZED_PNL_MISSING_OR_NONFINITE")
    elif not _same_number(declared_unrealized, row_unrealized):
        reasons.append("ACCOUNT_UNREALIZED_PNL_DOES_NOT_EQUAL_POSITION_ROW_SUM")
    if declared_used_margin is None or declared_used_margin < 0.0:
        reasons.append("ACCOUNT_USED_MARGIN_MISSING_OR_INVALID")
    elif not _same_number(declared_used_margin, row_used_margin):
        reasons.append("ACCOUNT_USED_MARGIN_DOES_NOT_EQUAL_CANONICAL_ROW_SUM")
    if declared_margin_base is None or declared_margin_base <= 0.0:
        reasons.append("ACCOUNT_MARGIN_BASE_MISSING_OR_INVALID")
    if newly_reserved is None or newly_reserved < 0.0:
        reasons.append("ACCOUNT_NEWLY_RESERVED_MARGIN_MISSING_OR_INVALID")
    if not isinstance(reservations_included, bool):
        reasons.append("ACCOUNT_RESERVATION_INCLUSION_FLAG_INVALID")
    if (
        margin_balance is not None
        and wallet_balance is not None
        and not _same_number(margin_balance, wallet_balance + row_unrealized)
    ):
        reasons.append("ACCOUNT_EQUITY_DOES_NOT_EQUAL_WALLET_PLUS_POSITION_PNL")
    expected_margin_base = (
        min(margin_balance, wallet_balance)
        if margin_balance is not None and wallet_balance is not None
        else None
    )
    if (
        expected_margin_base is not None
        and declared_margin_base is not None
        and not _same_number(declared_margin_base, expected_margin_base)
    ):
        reasons.append("ACCOUNT_MARGIN_BASE_RECONCILIATION_FAILED")
    expected_free = None
    if (
        expected_margin_base is not None
        and declared_used_margin is not None
        and newly_reserved is not None
        and isinstance(reservations_included, bool)
    ):
        projected_used = declared_used_margin + (
            0.0 if reservations_included else newly_reserved
        )
        expected_free = max(0.0, expected_margin_base - projected_used)
        if available is not None and not _same_number(available, expected_free):
            reasons.append("ACCOUNT_FREE_MARGIN_FORMULA_RECONCILIATION_FAILED")
    if account.get("status") != "PASS":
        reasons.append("ACCOUNT_MARGIN_STATUS_NOT_PASS")
    if account.get("accounting_complete") is not True:
        reasons.append("ACCOUNT_MARGIN_ACCOUNTING_NOT_COMPLETE")
    if account.get("account_balance_components_complete") is not True:
        reasons.append("ACCOUNT_MARGIN_BALANCE_COMPONENTS_NOT_COMPLETE")
    if account.get("wallet_balance_source") != (
        "SAME_LEDGER_STARTING_EQUITY_PLUS_REALIZED_NET_PNL"
    ):
        reasons.append("ACCOUNT_MARGIN_WALLET_BALANCE_SOURCE_INVALID")
    if account.get("equity_source") != (
        "SAME_LEDGER_WALLET_BALANCE_PLUS_CURRENT_UNREALIZED_PNL"
    ):
        reasons.append("ACCOUNT_MARGIN_EQUITY_SOURCE_INVALID")
    if not _paper_safety_valid(account):
        reasons.append("ACCOUNT_MARGIN_PAPER_ROUTE_SAFETY_INVALID")

    declared_cross_wallet = _float(account.get("cross_wallet_balance_usd"))
    declared_cross_unrealized = _float(account.get("cross_unrealized_pnl_usd"))
    declared_cross_equity = _float(account.get("cross_equity_usd"))
    expected_cross_wallet = (
        wallet_balance - isolated_used_margin
        if wallet_balance is not None
        else None
    )
    expected_cross_equity = (
        expected_cross_wallet + cross_unrealized
        if expected_cross_wallet is not None
        else None
    )
    if (
        expected_cross_wallet is None
        or expected_cross_wallet < 0.0
        or declared_cross_wallet is None
        or not _same_number(declared_cross_wallet, expected_cross_wallet)
    ):
        reasons.append("ACCOUNT_CROSS_WALLET_PARTITION_RECONCILIATION_FAILED")
    if (
        declared_cross_unrealized is None
        or not _same_number(declared_cross_unrealized, cross_unrealized)
    ):
        reasons.append("ACCOUNT_CROSS_UNREALIZED_RECONCILIATION_FAILED")
    if (
        expected_cross_equity is None
        or declared_cross_equity is None
        or not _same_number(declared_cross_equity, expected_cross_equity)
    ):
        reasons.append("ACCOUNT_CROSS_EQUITY_RECONCILIATION_FAILED")

    if reasons:
        return _blocked_snapshot(
            generated_utc=generated_utc,
            position_count=len(raw_positions),
            margin_row_count=len(raw_margin_rows),
            reasons=reasons,
            invalid_rows=invalid_rows,
        )

    assert (
        margin_balance is not None
        and wallet_balance is not None
        and available is not None
        and declared_cross_equity is not None
    )
    cross_margin_balance = declared_cross_equity
    maintenance_margin = math.fsum(
        row["maintenance_margin_usd"] for row in cross_rows
    )
    isolated_maintenance_margin = math.fsum(
        row["maintenance_margin_usd"] for row in isolated_rows
    )
    initial_margin = row_used_margin
    cross_initial_margin = math.fsum(
        row["canonical_margin_usd"] for row in cross_rows
    )
    unrealized = row_unrealized
    buffer_usd = cross_margin_balance - maintenance_margin
    buffer_pct = (
        buffer_usd / cross_margin_balance * 100.0
        if cross_margin_balance > 0.0
        else 0.0
    )
    total_notional = math.fsum(row["mark_notional_usd"] for row in cross_rows)
    for row in cross_rows:
        buffer_share = (
            buffer_usd * row["mark_notional_usd"] / total_notional
            if total_notional > 0.0
            else 0.0
        )
        price_buffer = buffer_share / row["position_quantity"]
        estimated_liq = (
            max(0.0, row["mark_price"] - price_buffer)
            if row["side"] == "long"
            else row["mark_price"] + price_buffer
        )
        row["estimated_position_liquidation_price"] = round(estimated_liq, 10)
        row["liquidation_estimate_model"] = "cross_margin_buffer_share_not_exchange_exact"
        row["liquidation_buffer_share_usd"] = round(buffer_share, 8)

    try:
        expected_stress_source_hash = adaptive_stress_source_observations_sha256(
            account=account,
            positions=raw_positions,
            position_margin_rows=raw_margin_rows,
        )
    except ValueError:
        expected_stress_source_hash = ""
    stress, stress_reasons = _validated_adaptive_stress(
        adaptive_stress_envelope,
        generated_at=generated_at,
        paper_session_id=paper_session_id or "",
        cross_symbols={row["symbol"] for row in cross_rows},
        authentication_keys=adaptive_stress_authentication_keys,
        expected_source_observations_sha256=expected_stress_source_hash,
    )
    shocks: dict[str, Any] = {}
    worst_case_buffer: float | None = None
    worst_scenario: str | None = None
    if stress is not None:
        for scenario in stress["scenarios"]:
            scenario_id = str(scenario["scenario_id"])
            moves = scenario["symbol_moves"]
            pnl_delta = 0.0
            shocked_maint = 0.0
            position_contributions: dict[str, Any] = {}
            for row in cross_rows:
                symbol_move = moves[row["symbol"]]
                shocked_mark = row["mark_price"] * (1.0 + symbol_move)
                direction = 1.0 if row["side"] == "long" else -1.0
                row_pnl_delta = (
                    direction
                    * row["position_quantity"]
                    * (shocked_mark - row["mark_price"])
                )
                row_shocked_maintenance = max(
                    0.0,
                    row["position_quantity"]
                    * shocked_mark
                    * row["maintenance_margin_rate"]
                    - row["maintenance_margin_cum"],
                )
                pnl_delta += row_pnl_delta
                shocked_maint += row_shocked_maintenance
                position_contributions[row["position_id"]] = {
                    "position_generation_id": row["position_generation_id"],
                    "symbol": row["symbol"],
                    "symbol_move": symbol_move,
                    "shock_pnl_delta_usd": round(row_pnl_delta, 8),
                    "shocked_maintenance_margin_usd": round(
                        row_shocked_maintenance, 8
                    ),
                    "marginal_stress_buffer_relief_if_closed_usd": round(
                        row_shocked_maintenance - row_pnl_delta, 8
                    ),
                }
            shocked_margin_balance = cross_margin_balance + pnl_delta
            shocked_buffer = shocked_margin_balance - shocked_maint
            shocks[scenario_id] = {
                "symbol_moves": moves,
                "portfolio_pnl_delta_usd": round(pnl_delta, 8),
                "shocked_margin_balance_usd": round(shocked_margin_balance, 8),
                "shocked_maintenance_margin_usd": round(shocked_maint, 8),
                "shocked_liquidation_buffer_usd": round(shocked_buffer, 8),
                "liquidation_breached": shocked_buffer <= 0.0,
                "recovery_reserve_breached": (
                    shocked_buffer < stress["recovery_reserve_usd"]
                ),
                "position_contributions": position_contributions,
            }
            if worst_case_buffer is None or shocked_buffer < worst_case_buffer:
                worst_case_buffer = shocked_buffer
                worst_scenario = scenario_id

    snapshot_material = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "portfolio_margin_balance_usd": cross_margin_balance,
        "wallet_balance_usd": wallet_balance,
        "maintenance_margin_usd": maintenance_margin,
        "positions": normalized,
        "correlated_shock_scenarios": shocks,
        "adaptive_stress_evidence_sha256": (
            stress.get("evidence_sha256") if stress is not None else None
        ),
        "adaptive_stress_evidence_auth_key_id": (
            stress.get("evidence_auth_key_id") if stress is not None else None
        ),
        "adaptive_stress_evidence_hmac_sha256": (
            stress.get("evidence_hmac_sha256") if stress is not None else None
        ),
        "hedge_candidate_maintenance": (
            stress.get("hedge_candidate_maintenance") if stress is not None else {}
        ),
        "adaptive_stress_producer": (
            stress.get("producer") if stress is not None else None
        ),
        "adaptive_stress_auth_boundary": (
            stress.get("auth_boundary") if stress is not None else None
        ),
        "adaptive_stress_source_observations_sha256": (
            stress.get("source_observations_sha256") if stress is not None else None
        ),
        "adaptive_stress_generated_at": (
            stress.get("generated_at") if stress is not None else None
        ),
        "adaptive_stress_available_at": (
            stress.get("available_at") if stress is not None else None
        ),
        "adaptive_stress_decision_time": (
            stress.get("decision_time") if stress is not None else None
        ),
        "adaptive_stress_freshness_budget_seconds": (
            stress.get("freshness_budget_seconds") if stress is not None else None
        ),
        "adaptive_guard_lifetime_seconds": (
            stress.get("guard_lifetime_seconds") if stress is not None else None
        ),
    }
    snapshot_hash = _sha256(snapshot_material)
    if snapshot_hash is None:
        return _blocked_snapshot(
            generated_utc=generated_utc,
            position_count=len(raw_positions),
            margin_row_count=len(raw_margin_rows),
            reasons=["PORTFOLIO_SNAPSHOT_HASH_FAILED"],
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "portfolio_snapshot_sha256": snapshot_hash,
        "portfolio_margin_balance_usd": round(cross_margin_balance, 8),
        "wallet_balance_usd": round(wallet_balance, 8),
        "cross_wallet_balance_usd": round(declared_cross_wallet or 0.0, 8),
        "cross_equity_usd": round(cross_margin_balance, 8),
        "cross_unrealized_pnl_usd": round(cross_unrealized, 8),
        "unrealized_pnl_usd": round(unrealized, 8),
        "initial_margin_usd": round(initial_margin, 8),
        "cross_initial_margin_usd": round(cross_initial_margin, 8),
        "isolated_initial_margin_usd": round(isolated_used_margin, 8),
        "maintenance_margin_usd": round(maintenance_margin, 8),
        "isolated_maintenance_margin_usd": round(
            isolated_maintenance_margin, 8
        ),
        "available_balance_usd": round(available, 8),
        "portfolio_liquidation_buffer_usd": round(buffer_usd, 8),
        "portfolio_liquidation_buffer_pct": round(buffer_pct, 8),
        "input_open_position_count": len(raw_positions),
        "input_position_margin_row_count": len(raw_margin_rows),
        "open_position_count": len(normalized),
        "cross_position_count": len(cross_rows),
        "isolated_position_count": len(isolated_rows),
        "positions": normalized,
        "position_liquidation_register": [
            {
                "position_id": row["position_id"],
                "position_generation_id": row["position_generation_id"],
                "position_evidence_sha256": row["position_evidence_sha256"],
                "symbol": row["symbol"],
                "side": row["side"],
                "mark_notional_usd": round(row["mark_notional_usd"], 8),
                "mark_price": row["mark_price"],
                "mark_time": row["mark_time"],
                "leverage": row["effective_leverage"],
                "maintenance_margin_usd": round(row["maintenance_margin_usd"], 8),
                "estimated_position_liquidation_price": row[
                    "estimated_position_liquidation_price"
                ],
                "liquidation_buffer_share_usd": row["liquidation_buffer_share_usd"],
            }
            for row in cross_rows
        ],
        "correlated_shock_scenarios": shocks,
        "worst_case_scenario": worst_scenario,
        "worst_case_liquidation_buffer_usd": (
            round(worst_case_buffer, 8)
            if worst_case_buffer is not None
            else None
        ),
        "worst_case_liquidation_breached": (
            worst_case_buffer <= 0.0
            if worst_case_buffer is not None
            else None
        ),
        "adaptive_stress_authority_complete": stress is not None,
        "adaptive_stress_block_reasons": stress_reasons,
        "hedge_candidate_maintenance": (
            stress.get("hedge_candidate_maintenance") if stress is not None else {}
        ),
        "adaptive_stress_policy_version": (
            stress.get("stress_policy_version") if stress is not None else None
        ),
        "adaptive_stress_cadence_policy_version": (
            stress.get("cadence_policy_version") if stress is not None else None
        ),
        "adaptive_stress_evidence_sha256": (
            stress.get("evidence_sha256") if stress is not None else None
        ),
        "adaptive_stress_producer": (
            stress.get("producer") if stress is not None else None
        ),
        "adaptive_stress_auth_boundary": (
            stress.get("auth_boundary") if stress is not None else None
        ),
        "adaptive_stress_source_observations_sha256": (
            stress.get("source_observations_sha256") if stress is not None else None
        ),
        "adaptive_stress_generated_at": (
            stress.get("generated_at") if stress is not None else None
        ),
        "adaptive_stress_available_at": (
            stress.get("available_at") if stress is not None else None
        ),
        "adaptive_stress_decision_time": (
            stress.get("decision_time") if stress is not None else None
        ),
        "adaptive_stress_freshness_budget_seconds": (
            stress.get("freshness_budget_seconds") if stress is not None else None
        ),
        "adaptive_guard_lifetime_seconds": (
            stress.get("guard_lifetime_seconds") if stress is not None else None
        ),
        "adaptive_recovery_reserve_usd": (
            stress.get("recovery_reserve_usd") if stress is not None else None
        ),
        "authority_complete": True,
        "portfolio_level_computed": True,
        "per_position_only": False,
        "risk_decision_blocked": False,
        "core_system_blocked": False,
        "block_reasons": [],
        "raw_key_exposed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def marginal_liquidation_impact(
    *,
    snapshot: Mapping[str, Any],
    added_notional_usd: float,
    added_symbol: str,
    added_side: str,
    added_maint_rate: float | None = None,
    added_maint_cum: float | None = None,
) -> dict[str, Any]:
    """Fully stress a hypothetical hedge using only bound adaptive evidence."""

    before = _float(snapshot.get("portfolio_liquidation_buffer_usd"))
    notional = _float(added_notional_usd)
    maint_rate = _float(added_maint_rate)
    maint_cum = _float(added_maint_cum)
    side = str(added_side or "").strip().lower()
    symbol = str(added_symbol or "").strip().upper()
    reasons: list[str] = []
    if (
        snapshot.get("authority_complete") is not True
        or snapshot.get("portfolio_level_computed") is not True
    ):
        reasons.append("PORTFOLIO_SNAPSHOT_NOT_AUTHORITATIVE")
    if snapshot.get("adaptive_stress_authority_complete") is not True:
        reasons.append("ADAPTIVE_STRESS_SNAPSHOT_NOT_AUTHORITATIVE")
    if before is None:
        reasons.append("PORTFOLIO_BUFFER_MISSING_OR_NONFINITE")
    if notional is None or notional == 0.0:
        reasons.append("ADDED_NOTIONAL_MISSING_NONFINITE_OR_ZERO")
    if maint_rate is None or not 0.0 < maint_rate < 1.0:
        reasons.append("ADDED_MAINTENANCE_RATE_INVALID")
    if maint_cum is None or maint_cum < 0.0:
        reasons.append("ADDED_MAINTENANCE_CUM_INVALID")
    if side not in {"long", "short"}:
        reasons.append("ADDED_SIDE_INVALID")
    scenarios = snapshot.get("correlated_shock_scenarios")
    if not isinstance(scenarios, Mapping) or not scenarios:
        reasons.append("ADAPTIVE_STRESS_SCENARIOS_MISSING")
    elif any(
        not isinstance(scenario, Mapping)
        or not isinstance(scenario.get("symbol_moves"), Mapping)
        or symbol not in scenario["symbol_moves"]
        for scenario in scenarios.values()
    ):
        reasons.append("ADDED_SYMBOL_NOT_COVERED_BY_ADAPTIVE_STRESS")
    if reasons:
        return {
            "authority_complete": False,
            "risk_decision_blocked": True,
            "block_reasons": reasons,
            "liquidation_buffer_before_usd": before,
            "liquidation_buffer_after_usd": None,
            "maintenance_margin_added_usd": None,
            "worsens_liquidation_buffer": None,
            "added_symbol": symbol,
            "added_side": side or None,
            "marginal_stress_buffer_improvement_usd": None,
        }
    assert (
        before is not None
        and notional is not None
        and maint_rate is not None
        and maint_cum is not None
        and isinstance(scenarios, Mapping)
    )
    direction = 1.0 if side == "long" else -1.0
    stressed_results: dict[str, Any] = {}
    worst_before: float | None = None
    worst_after: float | None = None
    for scenario_id, scenario in scenarios.items():
        assert isinstance(scenario, Mapping)
        moves = scenario["symbol_moves"]
        assert isinstance(moves, Mapping)
        move = _float(moves.get(symbol))
        before_scenario = _float(scenario.get("shocked_liquidation_buffer_usd"))
        if move is None or before_scenario is None:
            return {
                "authority_complete": False,
                "risk_decision_blocked": True,
                "block_reasons": ["ADAPTIVE_STRESS_SCENARIO_NUMERIC_INVALID"],
                "liquidation_buffer_before_usd": before,
                "liquidation_buffer_after_usd": None,
                "maintenance_margin_added_usd": None,
                "worsens_liquidation_buffer": None,
                "added_symbol": symbol,
                "added_side": side,
                "marginal_stress_buffer_improvement_usd": None,
            }
        shock_pnl = direction * abs(notional) * move
        shocked_notional = abs(notional) * (1.0 + move)
        shocked_maintenance = max(
            0.0, shocked_notional * maint_rate - maint_cum
        )
        after_scenario = before_scenario + shock_pnl - shocked_maintenance
        stressed_results[str(scenario_id)] = {
            "symbol_move": move,
            "shock_pnl_delta_usd": round(shock_pnl, 8),
            "shocked_maintenance_margin_added_usd": round(
                shocked_maintenance, 8
            ),
            "liquidation_buffer_before_usd": round(before_scenario, 8),
            "liquidation_buffer_after_usd": round(after_scenario, 8),
        }
        if worst_before is None or before_scenario < worst_before:
            worst_before = before_scenario
        if worst_after is None or after_scenario < worst_after:
            worst_after = after_scenario
    assert worst_before is not None and worst_after is not None
    current_maintenance = max(0.0, abs(notional) * maint_rate - maint_cum)
    current_buffer_after = before - current_maintenance
    return {
        "authority_complete": True,
        "risk_decision_blocked": False,
        "block_reasons": [],
        "liquidation_buffer_before_usd": round(worst_before, 8),
        "liquidation_buffer_after_usd": round(worst_after, 8),
        "current_liquidation_buffer_before_usd": round(before, 8),
        "current_liquidation_buffer_after_usd": round(current_buffer_after, 8),
        "maintenance_margin_added_usd": round(current_maintenance, 8),
        "worst_stress_buffer_before_usd": round(worst_before, 8),
        "worst_stress_buffer_after_usd": round(worst_after, 8),
        "marginal_stress_buffer_improvement_usd": round(
            worst_after - worst_before, 8
        ),
        "worsens_liquidation_buffer": worst_after < worst_before,
        "stress_scenarios": stressed_results,
        "adaptive_stress_evidence_sha256": snapshot.get(
            "adaptive_stress_evidence_sha256"
        ),
        "added_symbol": symbol,
        "added_side": side,
    }
