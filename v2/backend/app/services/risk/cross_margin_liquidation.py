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

from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "cross_margin_liquidation_v1"

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


def _position_rows(positions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pos in positions or ():
        if not isinstance(pos, Mapping):
            continue
        amt = _float(pos.get("positionAmt") or pos.get("position_amt") or pos.get("qty"))
        mark = _float(pos.get("markPrice") or pos.get("mark_price") or pos.get("entryPrice") or pos.get("entry_price"))
        if amt is None or mark is None or amt == 0:
            continue
        symbol = str(pos.get("symbol") or "").upper()
        notional = abs(amt) * mark
        leverage = _float(pos.get("leverage")) or 1.0
        maint_rate = _float(pos.get("maintMarginRatio") or pos.get("maintenance_margin_rate")) or 0.005
        rows.append({
            "symbol": symbol,
            "position_amt": amt,
            "side": "long" if amt > 0 else "short",
            "mark_price": mark,
            "entry_price": _float(pos.get("entryPrice") or pos.get("entry_price")) or mark,
            "notional_usd": notional,
            "leverage": leverage,
            "isolated": bool(pos.get("isolated")) or str(pos.get("marginType") or pos.get("margin_type") or "").lower().startswith("iso"),
            "unrealized_pnl_usd": _float(pos.get("unRealizedProfit") or pos.get("unrealized_pnl")) or 0.0,
            "maintenance_margin_rate": maint_rate,
            "maintenance_margin_usd": notional * maint_rate,
            "adl_quantile": _float(pos.get("adlQuantile") or pos.get("adl_quantile")),
            "symbol_leverage_bracket": pos.get("leverageBracket") or pos.get("leverage_bracket"),
        })
    return rows


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
    positions: Sequence[Mapping[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    account = account if isinstance(account, Mapping) else {}
    rows = _position_rows(positions)

    wallet_balance = _float(account.get("totalWalletBalance") or account.get("wallet_balance")) or 0.0
    cross_wallet = _float(account.get("totalCrossWalletBalance") or account.get("cross_wallet_balance")) or wallet_balance
    unrealized = _float(account.get("totalUnrealizedProfit") or account.get("unrealized_pnl")) or sum(r["unrealized_pnl_usd"] for r in rows)
    initial_margin = _float(account.get("totalInitialMargin") or account.get("initial_margin")) or 0.0
    maintenance_margin = _float(account.get("totalMaintMargin") or account.get("maintenance_margin")) or sum(r["maintenance_margin_usd"] for r in rows)
    margin_balance = _float(account.get("totalMarginBalance") or account.get("margin_balance")) or (wallet_balance + unrealized)
    available = _float(account.get("availableBalance") or account.get("available_balance")) or max(0.0, margin_balance - initial_margin)

    # Portfolio liquidation buffer = margin balance above maintenance requirement.
    buffer_usd = margin_balance - maintenance_margin
    buffer_pct = (buffer_usd / margin_balance * 100.0) if margin_balance > 0 else 0.0
    total_notional = sum(row["notional_usd"] for row in rows)
    for row in rows:
        qty_abs = abs(row["position_amt"])
        buffer_share = buffer_usd * (row["notional_usd"] / total_notional) if total_notional > 0 else 0.0
        price_buffer = buffer_share / qty_abs if qty_abs > 0 else None
        if price_buffer is None:
            estimated_liq = None
        elif row["side"] == "long":
            estimated_liq = max(0.0, row["mark_price"] - price_buffer)
        else:
            estimated_liq = row["mark_price"] + price_buffer
        row["estimated_position_liquidation_price"] = round(estimated_liq, 10) if estimated_liq is not None else None
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
                r["notional_usd"] * (1.0 + btc_move * _beta(r["symbol"]) * (1 if r["side"] == "long" else -1)),
            ) * r["maintenance_margin_rate"]
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

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "portfolio_margin_balance_usd": round(margin_balance, 2),
        "wallet_balance_usd": round(wallet_balance, 2),
        "cross_wallet_balance_usd": round(cross_wallet, 2),
        "unrealized_pnl_usd": round(unrealized, 2),
        "initial_margin_usd": round(initial_margin, 2),
        "maintenance_margin_usd": round(maintenance_margin, 2),
        "available_balance_usd": round(available, 2),
        "canTrade": account.get("canTrade"),
        "canDeposit": account.get("canDeposit"),
        "canWithdraw": account.get("canWithdraw"),
        "dualSidePosition": account.get("dualSidePosition"),
        "multiAssetsMargin": account.get("multiAssetsMargin"),
        "portfolio_liquidation_buffer_usd": round(buffer_usd, 2),
        "portfolio_liquidation_buffer_pct": round(buffer_pct, 4),
        "open_position_count": len(rows),
        "positions": rows,
        "position_liquidation_register": [
            {
                "symbol": r["symbol"],
                "side": r["side"],
                "notional_usd": round(r["notional_usd"], 2),
                "mark_price": r["mark_price"],
                "leverage": r["leverage"],
                "isolated": r["isolated"],
                "estimated_position_liquidation_price": r["estimated_position_liquidation_price"],
                "liquidation_buffer_share_usd": r["liquidation_buffer_share_usd"],
                "adl_quantile": r["adl_quantile"],
            }
            for r in rows
        ],
        "correlated_shock_scenarios": shocks,
        "worst_case_scenario": worst_scenario,
        "worst_case_liquidation_buffer_usd": round(worst_case_buffer, 2),
        "worst_case_liquidation_breached": worst_case_buffer <= 0,
        "adl_risk_symbols": adl_risk_positions,
        "portfolio_level_computed": True,
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
