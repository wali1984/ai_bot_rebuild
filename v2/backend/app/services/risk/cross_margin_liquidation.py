"""Cross-margin portfolio liquidation engine.

In cross margin the effective liquidation risk is PORTFOLIO-level: a single
position can look safe while a correlated shock across all open positions
drives the whole account to maintenance. This engine computes the portfolio
margin state and simulates correlated BTC/ETH/SOL shocks across every open
position and hedge.

Pure computation over a supplied account snapshot (signed-read payload) and
position list. No exchange calls, no mutation. USD-first.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "cross_margin_liquidation_v2"

# Correlated shock scenarios (fraction move applied to BTC; alts beta-scaled).
SHOCK_SCENARIOS = {
    "btc_down_5pct": -0.05,
    "btc_down_10pct": -0.10,
    "btc_down_20pct": -0.20,
    "btc_up_10pct": 0.10,
}

# Beta of alt classes to a BTC move (conservative; majors move ~1x, alts >1x).
DEFAULT_BETA = {
    "BTCUSDT": 1.0,
    "ETHUSDT": 1.15,
    "SOLUSDT": 1.35,
}
ALT_DEFAULT_BETA = 1.6


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _beta(symbol: str) -> float:
    return DEFAULT_BETA.get(str(symbol).upper(), ALT_DEFAULT_BETA)


def _first_present(mapping: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = mapping.get(field)
        if value not in (None, ""):
            return value
    return None


def _first_present_field(
    mapping: Mapping[str, Any], *fields: str
) -> tuple[str | None, Any]:
    for field in fields:
        value = mapping.get(field)
        if value not in (None, ""):
            return field, value
    return None, None


def _resolve_account_number(
    account: Mapping[str, Any],
    *fields: str,
    fallback: float,
    fallback_source: str,
) -> tuple[float, dict[str, Any]]:
    """Resolve an account number without treating an explicit zero as absent.

    The first present alias remains authoritative.  If it cannot be parsed we
    use the same derived/default fallback as before, but do not silently skip
    to a lower-precedence alias.
    """

    source_field, raw_value = _first_present_field(account, *fields)
    if source_field is None:
        return fallback, {
            "status": "MISSING",
            "source_field": None,
            "fallback_used": True,
            "fallback_source": fallback_source,
            "explicit_zero": False,
        }
    parsed = _float(raw_value)
    if parsed is None:
        return fallback, {
            "status": "INVALID",
            "source_field": source_field,
            "fallback_used": True,
            "fallback_source": fallback_source,
            "explicit_zero": False,
        }
    return parsed, {
        "status": "VALID",
        "source_field": source_field,
        "fallback_used": False,
        "fallback_source": None,
        "explicit_zero": parsed == 0.0,
    }


_DIRECTIONAL_SIDE = {
    "long": "long",
    "buy": "long",
    "short": "short",
    "sell": "short",
}


def _normalize_position_amount(
    position: Mapping[str, Any],
    *,
    amount: float,
    amount_source_field: str,
) -> tuple[float, str, dict[str, Any]]:
    directional_evidence: list[dict[str, str]] = []
    nondirectional_fields: list[str] = []
    unrecognized_fields: list[str] = []
    for field in ("side", "direction", "positionSide", "position_side"):
        raw_value = position.get(field)
        if raw_value in (None, ""):
            continue
        side_label = str(raw_value).strip().lower()
        if side_label == "both":
            nondirectional_fields.append(field)
            continue
        normalized = _DIRECTIONAL_SIDE.get(side_label)
        if normalized is None:
            unrecognized_fields.append(field)
            continue
        directional_evidence.append({"field": field, "side": normalized})

    position_side_present = any(
        position.get(field) not in (None, "")
        for field in ("positionSide", "position_side")
    )
    if amount_source_field == "positionAmt" or (
        amount_source_field == "position_amt" and position_side_present
    ):
        position_schema = "EXCHANGE_SIGNED_POSITION"
        controlling_fields = ("positionSide", "position_side")
        explicit_resolution = "EXCHANGE_POSITION_SIDE"
    elif amount_source_field == "net_quantity":
        position_schema = "CANONICAL_POSITION"
        controlling_fields = ("side", "direction", "positionSide", "position_side")
        explicit_resolution = "CANONICAL_POSITION_SIDE"
    else:
        position_schema = "GENERIC_POSITION"
        controlling_fields = ("side", "direction", "positionSide", "position_side")
        explicit_resolution = "GENERIC_EXPLICIT_DIRECTION"

    controlling_evidence = [
        item
        for field in controlling_fields
        for item in directional_evidence
        if item["field"] == field
    ]
    ignored_evidence = [item for item in directional_evidence if item not in controlling_evidence]
    unrecognized_controlling_fields = [
        field for field in controlling_fields if field in unrecognized_fields
    ]
    selected = controlling_evidence[0] if controlling_evidence else None
    explicit_side = selected["side"] if selected else None
    quantity_side = "long" if amount > 0.0 else "short"
    if explicit_side is None:
        normalized_amount = amount
        normalized_side = quantity_side
    else:
        normalized_side = explicit_side
        normalized_amount = abs(amount) if explicit_side == "long" else -abs(amount)

    evidence_sides = {item["side"] for item in directional_evidence}
    sign_conflict = explicit_side is not None and explicit_side != quantity_side
    diagnostics = {
        "quantity_source_field": amount_source_field,
        "signed_quantity_input": amount,
        "position_schema": position_schema,
        "side_resolution": explicit_resolution if explicit_side is not None else "SIGNED_QUANTITY",
        "side_source_field": selected["field"] if selected else None,
        "explicit_side": explicit_side,
        "quantity_sign_side_conflict": sign_conflict,
        "quantity_sign_adjusted": normalized_amount != amount,
        "direction_evidence_conflict": len(evidence_sides) > 1,
        "directional_evidence": directional_evidence,
        "controlling_directional_evidence": controlling_evidence,
        "ignored_directional_evidence": ignored_evidence,
        "nondirectional_side_fields": nondirectional_fields,
        "unrecognized_side_fields": unrecognized_fields,
        "unrecognized_controlling_side_fields": unrecognized_controlling_fields,
    }
    return normalized_amount, normalized_side, diagnostics


def _is_isolated(position: Mapping[str, Any]) -> bool:
    explicit = position.get("isolated")
    if isinstance(explicit, bool):
        return explicit
    margin_mode = str(
        _first_present(
            position,
            "marginType",
            "margin_type",
            "margin_mode",
            "margin_mode_simulated",
            "recommended_margin_mode",
        )
        or ""
    ).lower()
    return margin_mode.startswith("iso")


def _position_rows(
    positions: Sequence[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    for index, pos in enumerate(positions or ()):
        if not isinstance(pos, Mapping):
            dropped_rows.append(
                {
                    "index": index,
                    "symbol": None,
                    "reasons": ["POSITION_ROW_NOT_MAPPING"],
                }
            )
            continue
        symbol = str(pos.get("symbol") or "").upper()
        amount_source_field, raw_amount = _first_present_field(
            pos,
            "positionAmt",
            "position_amt",
            "net_quantity",
            "qty",
            "quantity",
        )
        amt = _float(raw_amount)
        mark_source_field, raw_mark = _first_present_field(
            pos,
            "markPrice",
            "mark_price",
            "current_mark_price",
            "last_mark_price",
            "last_mark_est",
        )
        mark = _float(raw_mark)
        rejection_reasons: list[str] = []
        if not symbol:
            rejection_reasons.append("POSITION_SYMBOL_MISSING")
        if amount_source_field is None:
            rejection_reasons.append("POSITION_QUANTITY_MISSING")
        elif amt is None:
            rejection_reasons.append("POSITION_QUANTITY_INVALID")
        elif amt == 0.0:
            rejection_reasons.append("POSITION_QUANTITY_ZERO")
        if mark_source_field is None:
            rejection_reasons.append("POSITION_MARK_MISSING")
        elif mark is None:
            rejection_reasons.append("POSITION_MARK_INVALID")
        elif mark <= 0.0:
            rejection_reasons.append("POSITION_MARK_NON_POSITIVE")
        if rejection_reasons:
            dropped_rows.append(
                {
                    "index": index,
                    "symbol": symbol or None,
                    "reasons": rejection_reasons,
                }
            )
            continue
        amt, side, normalization = _normalize_position_amount(
            pos,
            amount=amt,
            amount_source_field=amount_source_field,
        )
        normalization["mark_source_field"] = mark_source_field
        notional = abs(amt) * mark
        leverage = _float(
            _first_present(
                pos,
                "leverage",
                "effective_leverage",
                "recommended_leverage",
            )
        )
        maint_rate = _float(
            _first_present(
                pos,
                "maintMarginRatio",
                "maintenance_margin_rate",
                "maintenance_bracket_maint_margin_ratio",
            )
        )
        # Retain the audited conservative fallback for legacy exchange-shaped
        # fixtures, but stamp when it was used.  The paper cascade caller now
        # joins the canonical margin-accounting row, so current paper positions
        # do not silently depend on this fallback.
        maintenance_rate_source = "POSITION_EVIDENCE"
        if maint_rate is None or maint_rate <= 0.0:
            maint_rate = 0.005
            maintenance_rate_source = "LEGACY_CONSERVATIVE_FALLBACK"
        rows.append(
            {
                "symbol": symbol,
                "position_amt": amt,
                "side": side,
                "input_normalization": normalization,
                "mark_price": mark,
                "entry_price": _float(
                    _first_present(
                        pos,
                        "entryPrice",
                        "entry_price",
                        "avg_entry_price",
                    )
                )
                or mark,
                "notional_usd": notional,
                "leverage": leverage,
                "leverage_evidence_available": leverage is not None,
                "isolated": _is_isolated(pos),
                "unrealized_pnl_usd": _float(
                    _first_present(
                        pos,
                        "unRealizedProfit",
                        "unrealized_pnl_usd",
                        "unrealized_pnl",
                    )
                )
                or 0.0,
                "maintenance_margin_rate": maint_rate,
                "maintenance_margin_rate_source": maintenance_rate_source,
                "maintenance_margin_usd": notional * maint_rate,
                "adl_quantile": _float(_first_present(pos, "adlQuantile", "adl_quantile")),
                "symbol_leverage_bracket": _first_present(
                    pos,
                    "leverageBracket",
                    "leverage_bracket",
                    "maintenance_bracket_binding",
                ),
            }
        )
    return rows, dropped_rows


def _shock_pnl(rows: list[dict[str, Any]], btc_move: float) -> float:
    """Total unrealized PnL delta under a correlated BTC move (USD)."""
    total = 0.0
    for row in rows:
        move = btc_move * _beta(row["symbol"])
        direction = 1.0 if row["side"] == "long" else -1.0
        total += direction * row["notional_usd"] * move
    return total


def build_portfolio_liquidation_snapshot(
    *,
    account: Mapping[str, Any],
    positions: Sequence[Any],
    generated_utc: str,
) -> dict[str, Any]:
    position_inputs = list(positions or ())
    expected_position_count = len(position_inputs)
    account = account if isinstance(account, Mapping) else {}
    rows, dropped_positions = _position_rows(position_inputs)

    account_input_normalization: dict[str, dict[str, Any]] = {}
    wallet_balance, account_input_normalization["wallet_balance_usd"] = (
        _resolve_account_number(
            account,
            "totalWalletBalance",
            "wallet_balance",
            fallback=0.0,
            fallback_source="ZERO_DEFAULT",
        )
    )
    cross_wallet, account_input_normalization["cross_wallet_balance_usd"] = (
        _resolve_account_number(
            account,
            "totalCrossWalletBalance",
            "cross_wallet_balance",
            fallback=wallet_balance,
            fallback_source="WALLET_BALANCE",
        )
    )
    unrealized, account_input_normalization["unrealized_pnl_usd"] = (
        _resolve_account_number(
            account,
            "totalUnrealizedProfit",
            "unrealized_pnl",
            fallback=sum(r["unrealized_pnl_usd"] for r in rows),
            fallback_source="POSITION_UNREALIZED_PNL_SUM",
        )
    )
    initial_margin, account_input_normalization["initial_margin_usd"] = (
        _resolve_account_number(
            account,
            "totalInitialMargin",
            "initial_margin",
            fallback=0.0,
            fallback_source="ZERO_DEFAULT",
        )
    )
    maintenance_margin, account_input_normalization["maintenance_margin_usd"] = (
        _resolve_account_number(
            account,
            "totalMaintMargin",
            "maintenance_margin",
            fallback=sum(r["maintenance_margin_usd"] for r in rows),
            fallback_source="POSITION_MAINTENANCE_MARGIN_SUM",
        )
    )
    margin_balance, account_input_normalization["portfolio_margin_balance_usd"] = (
        _resolve_account_number(
            account,
            "totalMarginBalance",
            "margin_balance",
            fallback=wallet_balance + unrealized,
            fallback_source="WALLET_BALANCE_PLUS_UNREALIZED_PNL",
        )
    )
    available, account_input_normalization["available_balance_usd"] = (
        _resolve_account_number(
            account,
            "availableBalance",
            "available_balance",
            fallback=max(0.0, margin_balance - initial_margin),
            fallback_source="MARGIN_BALANCE_MINUS_INITIAL_MARGIN",
        )
    )

    # Portfolio liquidation buffer = margin balance above maintenance requirement.
    buffer_usd = margin_balance - maintenance_margin
    buffer_pct = (buffer_usd / margin_balance * 100.0) if margin_balance > 0 else 0.0
    total_notional = sum(row["notional_usd"] for row in rows)
    for row in rows:
        qty_abs = abs(row["position_amt"])
        buffer_share = (
            buffer_usd * (row["notional_usd"] / total_notional) if total_notional > 0 else 0.0
        )
        price_buffer = buffer_share / qty_abs if qty_abs > 0 else None
        if price_buffer is None:
            estimated_liq = None
        elif row["side"] == "long":
            estimated_liq = max(0.0, row["mark_price"] - price_buffer)
        else:
            estimated_liq = row["mark_price"] + price_buffer
        row["estimated_position_liquidation_price"] = (
            round(estimated_liq, 10) if estimated_liq is not None else None
        )
        row["liquidation_estimate_model"] = "cross_margin_buffer_share_not_exchange_exact"
        row["liquidation_buffer_share_usd"] = round(buffer_share, 2)

    shocks: dict[str, Any] = {}
    worst_case_buffer = buffer_usd
    worst_scenario = None
    for name, btc_move in SHOCK_SCENARIOS.items():
        pnl_delta = _shock_pnl(rows, btc_move)
        shocked_margin_balance = margin_balance + pnl_delta
        # Maintenance requirement is roughly notional-proportional; recompute
        # against shocked notionals for a conservative estimate.
        shocked_maint = sum(
            max(
                0.0,
                # Maintenance scales with |notional|, which moves by (1 + shock)
                # for the symbol regardless of side. The side sign belongs only
                # in _shock_pnl — applying it here under-estimated SHORT
                # maintenance in an up-shock and withheld a protective close.
                r["notional_usd"] * (1.0 + btc_move * _beta(r["symbol"])),
            )
            * r["maintenance_margin_rate"]
            for r in rows
        )
        shocked_buffer = shocked_margin_balance - shocked_maint
        shocks[name] = {
            "btc_move": btc_move,
            "portfolio_pnl_delta_usd": round(pnl_delta, 2),
            "shocked_margin_balance_usd": round(shocked_margin_balance, 2),
            "shocked_maintenance_margin_usd": round(shocked_maint, 2),
            "shocked_liquidation_buffer_usd": round(shocked_buffer, 2),
            "liquidation_breached": shocked_buffer <= 0,
        }
        if shocked_buffer < worst_case_buffer:
            worst_case_buffer = shocked_buffer
            worst_scenario = name

    adl_risk_positions = [r["symbol"] for r in rows if (r.get("adl_quantile") or 0) >= 3]
    maintenance_fallback_symbols = [
        row["symbol"]
        for row in rows
        if row.get("maintenance_margin_rate_source") == "LEGACY_CONSERVATIVE_FALLBACK"
    ]
    leverage_evidence_missing_symbols = [
        row["symbol"] for row in rows if row.get("leverage_evidence_available") is not True
    ]
    position_direction_conflicts = [
        {
            "symbol": row["symbol"],
            "quantity_source_field": row["input_normalization"]["quantity_source_field"],
            "position_schema": row["input_normalization"]["position_schema"],
            "directional_evidence": row["input_normalization"]["directional_evidence"],
        }
        for row in rows
        if row["input_normalization"]["direction_evidence_conflict"] is True
    ]
    unrecognized_direction_rows = [
        {
            "symbol": row["symbol"],
            "quantity_source_field": row["input_normalization"]["quantity_source_field"],
            "position_schema": row["input_normalization"]["position_schema"],
            "unrecognized_controlling_side_fields": row["input_normalization"][
                "unrecognized_controlling_side_fields"
            ],
        }
        for row in rows
        if row["input_normalization"]["unrecognized_controlling_side_fields"]
    ]
    direction_evidence_complete = not (
        position_direction_conflicts or unrecognized_direction_rows
    )
    computed_position_count = len(rows)
    position_count_evidence_complete = (
        computed_position_count == expected_position_count and not dropped_positions
    )
    critical_account_values = {
        "portfolio_margin_balance_usd": margin_balance,
        "maintenance_margin_usd": maintenance_margin,
    }
    account_dependency_issues: list[dict[str, Any]] = []
    for field, value in critical_account_values.items():
        diagnostic = account_input_normalization[field]
        if diagnostic["status"] != "VALID":
            account_dependency_issues.append(
                {
                    "field": field,
                    "reason": f"ACCOUNT_INPUT_{diagnostic['status']}",
                    "source_field": diagnostic["source_field"],
                    "fallback_source": diagnostic["fallback_source"],
                }
            )
        elif value < 0.0:
            account_dependency_issues.append(
                {
                    "field": field,
                    "reason": "ACCOUNT_INPUT_NEGATIVE",
                    "source_field": diagnostic["source_field"],
                    "fallback_source": None,
                }
            )
    account_dependency_evidence_complete = not account_dependency_issues
    maintenance_margin_evidence_complete = not maintenance_fallback_symbols
    authority_complete = all(
        (
            direction_evidence_complete,
            position_count_evidence_complete,
            account_dependency_evidence_complete,
            maintenance_margin_evidence_complete,
        )
    )
    portfolio_risk_block_reasons: list[str] = []
    if dropped_positions:
        portfolio_risk_block_reasons.append("POSITION_ROWS_DROPPED")
    if computed_position_count != expected_position_count:
        portfolio_risk_block_reasons.append("POSITION_COUNT_MISMATCH")
    if position_direction_conflicts:
        portfolio_risk_block_reasons.append("POSITION_DIRECTION_EVIDENCE_CONFLICT")
    if unrecognized_direction_rows:
        portfolio_risk_block_reasons.append("POSITION_DIRECTION_EVIDENCE_UNRECOGNIZED")
    if account_dependency_issues:
        portfolio_risk_block_reasons.append("ACCOUNT_DEPENDENCY_EVIDENCE_INCOMPLETE")
    if not maintenance_margin_evidence_complete:
        portfolio_risk_block_reasons.append("MAINTENANCE_MARGIN_EVIDENCE_INCOMPLETE")
    calculated_worst_case_breached = worst_case_buffer <= 0
    calculated_account_values = {
        "portfolio_margin_balance_usd": round(margin_balance, 2),
        "wallet_balance_usd": round(wallet_balance, 2),
        "cross_wallet_balance_usd": round(cross_wallet, 2),
        "unrealized_pnl_usd": round(unrealized, 2),
        "initial_margin_usd": round(initial_margin, 2),
        "maintenance_margin_usd": round(maintenance_margin, 2),
        "available_balance_usd": round(available, 2),
    }
    dependency_issue_fields = {item["field"] for item in account_dependency_issues}
    published_account_values = {
        field: (
            value
            if account_input_normalization[field]["status"] == "VALID"
            and field not in dependency_issue_fields
            else None
        )
        for field, value in calculated_account_values.items()
    }
    calculated_position_liquidation_register = [
        {
            "symbol": row["symbol"],
            "side": row["side"],
            "notional_usd": round(row["notional_usd"], 2),
            "mark_price": row["mark_price"],
            "leverage": row["leverage"],
            "isolated": row["isolated"],
            "estimated_position_liquidation_price": row[
                "estimated_position_liquidation_price"
            ],
            "liquidation_buffer_share_usd": row["liquidation_buffer_share_usd"],
            "adl_quantile": row["adl_quantile"],
        }
        for row in rows
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        **published_account_values,
        "calculated_account_values": calculated_account_values,
        "account_input_normalization": account_input_normalization,
        "account_dependency_evidence_complete": account_dependency_evidence_complete,
        "account_dependency_issues": account_dependency_issues,
        "canTrade": account.get("canTrade"),
        "canDeposit": account.get("canDeposit"),
        "canWithdraw": account.get("canWithdraw"),
        "dualSidePosition": account.get("dualSidePosition"),
        "multiAssetsMargin": account.get("multiAssetsMargin"),
        "portfolio_liquidation_buffer_usd": (
            round(buffer_usd, 2) if authority_complete else None
        ),
        "portfolio_liquidation_buffer_pct": (
            round(buffer_pct, 4) if authority_complete else None
        ),
        "calculated_portfolio_liquidation_buffer_usd": round(buffer_usd, 2),
        "calculated_portfolio_liquidation_buffer_pct": round(buffer_pct, 4),
        "expected_position_count": expected_position_count,
        "computed_position_count": computed_position_count,
        "open_position_count": computed_position_count,
        "dropped_position_count": len(dropped_positions),
        "dropped_positions": dropped_positions,
        "position_count_evidence_complete": position_count_evidence_complete,
        "maintenance_margin_evidence_complete": maintenance_margin_evidence_complete,
        "maintenance_margin_fallback_symbols": maintenance_fallback_symbols,
        "leverage_evidence_complete": not leverage_evidence_missing_symbols,
        "leverage_evidence_missing_symbols": leverage_evidence_missing_symbols,
        "position_direction_evidence_complete": direction_evidence_complete,
        "position_direction_conflicts": position_direction_conflicts,
        "unrecognized_position_directions": unrecognized_direction_rows,
        "portfolio_risk_result_authoritative": authority_complete,
        "portfolio_risk_computation_blocked": not authority_complete,
        "portfolio_risk_block_reasons": portfolio_risk_block_reasons,
        "positions": rows if authority_complete else None,
        "calculated_positions": rows,
        "position_liquidation_register": (
            calculated_position_liquidation_register if authority_complete else None
        ),
        "calculated_position_liquidation_register": (
            calculated_position_liquidation_register
        ),
        "correlated_shock_scenarios": shocks if authority_complete else None,
        "calculated_correlated_shock_scenarios": shocks,
        "worst_case_scenario": worst_scenario if authority_complete else None,
        "worst_case_liquidation_buffer_usd": (
            round(worst_case_buffer, 2) if authority_complete else None
        ),
        "worst_case_liquidation_breached": (
            calculated_worst_case_breached if authority_complete else None
        ),
        "calculated_worst_case_scenario": worst_scenario,
        "calculated_worst_case_liquidation_buffer_usd": round(worst_case_buffer, 2),
        "calculated_worst_case_liquidation_breached": calculated_worst_case_breached,
        "worst_case_liquidation_result_authoritative": authority_complete,
        "adl_risk_symbols": adl_risk_positions if authority_complete else None,
        "calculated_adl_risk_symbols": adl_risk_positions,
        "portfolio_level_computed": authority_complete,
        "per_position_only": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def marginal_liquidation_impact(
    *,
    snapshot: Mapping[str, Any],
    added_notional_usd: float,
    added_symbol: str,
    added_side: str,
    added_maint_rate: float = 0.005,
) -> dict[str, Any]:
    """How a proposed new position/hedge changes portfolio liquidation buffer.

    Used by the hedge-first controller to reject hedges that INCREASE
    maintenance margin beyond their risk-reduction benefit.
    """
    before = _float(snapshot.get("portfolio_liquidation_buffer_usd")) or 0.0
    maint_add = abs(added_notional_usd) * added_maint_rate
    # A hedge reduces directional exposure but still consumes maintenance margin.
    after = before - maint_add
    return {
        "liquidation_buffer_before_usd": round(before, 2),
        "liquidation_buffer_after_usd": round(after, 2),
        "maintenance_margin_added_usd": round(maint_add, 2),
        "worsens_liquidation_buffer": after < before,
        "added_symbol": str(added_symbol).upper(),
        "added_side": added_side,
    }
