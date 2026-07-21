"""Paper-only fill, position, and mark-to-market accounting.

This module is deterministic and side-effect free. It never calls an
exchange, never writes Redis, and never imports legacy runtime code.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from ..paper_trade_management.generation_identity import (
    closed_generation_match,
    entry_generation_identity,
)


LINEAGE_FIELDS = ("prediction_id", "risk_decision_id", "orchestrator_decision_id", "signal_id")


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def first_present(row: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def closed_realized_pnl_usd(row: Mapping[str, Any]) -> float:
    value = first_present(
        row,
        (
            "realized_net_pnl_usd",
            "realized_net_pnl",
            "net_pnl_usd",
            "realized_pnl_usd",
            "realized_pnl_usdt",
            "realized_pnl",
            "pnl_usd",
        ),
    )
    return float(coerce_float(value) or 0.0)


def normalized_side(row: Mapping[str, Any]) -> str | None:
    raw = str(first_present(row, ("side", "selected_action", "action", "position_side")) or "").lower()
    if raw in {"long", "buy"}:
        return "long"
    if raw in {"short", "sell"}:
        return "short"
    if raw in {"close", "flat"}:
        return "close"
    return None


def fill_identity(row: Mapping[str, Any]) -> str:
    for key in ("fill_id", "paper_fill_id", "ledger_row_id", "intent_id", "signal_id", "prediction_id", "source_prediction_id"):
        value = row.get(key)
        if value:
            return str(value)
    return entry_generation_identity(row).generation_id


def identity_values(row: Mapping[str, Any], keys: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            values.update(str(item) for item in value if item not in (None, ""))
        elif value not in (None, ""):
            values.add(str(value))
    return values


def closed_fill_identity_values(closed_rows: list[Mapping[str, Any]]) -> set[str]:
    closed_ids: set[str] = set()
    for row in closed_rows:
        closed_ids.update(
            identity_values(
                row,
                (
                    "source_fill_ids",
                    "entry_fill_id",
                    "fill_id",
                    "paper_fill_id",
                    "ledger_row_id",
                    "intent_id",
                    "entry_signal_id",
                    "signal_id",
                    "entry_prediction_id",
                    "prediction_id",
                    "source_prediction_id",
                ),
            )
        )
    return closed_ids


def suppress_accepted_rows_already_closed(
    accepted_rows: list[Mapping[str, Any]],
    closed_rows: list[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    if not closed_rows:
        return list(accepted_rows), []
    active: list[Mapping[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for row in accepted_rows:
        matched_evidence = None
        matched_closed_row = None
        for closed_row in closed_rows:
            evidence = closed_generation_match(row, closed_row)
            if evidence is not None:
                matched_evidence = evidence
                matched_closed_row = closed_row
                break
        if matched_evidence is not None:
            suppressed.append(
                {
                    "fill_id": fill_identity(row),
                    "symbol": str(row.get("symbol") or "").upper(),
                    "matched_closed_source_ids": list(
                        matched_evidence.get("matched_ids") or []
                    ),
                    "closed_generation_match_type": matched_evidence.get(
                        "match_type"
                    ),
                    "position_generation_id": matched_evidence.get(
                        "position_generation_id"
                    ),
                    "matched_close_id": (
                        matched_closed_row.get("close_id")
                        if isinstance(matched_closed_row, Mapping)
                        else None
                    ),
                }
            )
            continue
        active.append(row)
    return active, suppressed


def extract_lineage(row: Mapping[str, Any]) -> dict[str, Any]:
    prediction_id = first_present(row, ("prediction_id", "source_prediction_id", "trainer_prediction_id"))
    return {
        "prediction_id": prediction_id,
        "risk_decision_id": first_present(row, ("risk_decision_id", "risk_id")),
        "orchestrator_decision_id": first_present(row, ("orchestrator_decision_id", "decision_id")),
        "signal_id": first_present(row, ("signal_id", "paper_signal_id")),
    }


def _entry_price(row: Mapping[str, Any]) -> float | None:
    return coerce_float(first_present(row, ("fill_price", "entry_price", "price")))


def _quantity_and_notional(row: Mapping[str, Any], price: float | None) -> tuple[float | None, float | None]:
    quantity = coerce_float(first_present(row, ("quantity", "qty", "size")))
    notional = coerce_float(first_present(row, ("notional", "requested_notional_usdt", "notional_usdt", "notional_usd")))
    if quantity is None and notional is not None and price and price > 0:
        quantity = abs(notional / price)
    if notional is None and quantity is not None and price and price > 0:
        notional = abs(quantity * price)
    if quantity is not None:
        quantity = abs(quantity)
    if notional is not None:
        notional = abs(notional)
    return quantity, notional


def classify_fill(
    row: Mapping[str, Any],
    *,
    mark_price: float | None = None,
    mark_price_source: str | None = None,
    mark_price_age_seconds: float | None = None,
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    side = normalized_side(row)
    entry = _entry_price(row)
    quantity, notional = _quantity_and_notional(row, entry)
    lineage = extract_lineage(row)
    missing: list[str] = []
    if not symbol:
        missing.append("MISSING_SYMBOL")
    if side is None:
        missing.append("MISSING_SIDE")
    if entry is None or entry <= 0:
        missing.append("MISSING_PRICE")
    if quantity is None or quantity <= 0:
        missing.append("MISSING_QTY")
    if notional is None or notional <= 0:
        missing.append("MISSING_NOTIONAL")
    for field, value in lineage.items():
        if not value:
            missing.append(f"MISSING_{field.upper()}")
    effective_mark = mark_price if mark_price and mark_price > 0 else coerce_float(row.get("latest_price"))
    if entry is not None and entry > 0 and effective_mark is not None and effective_mark > 0:
        price_ratio = max(entry, effective_mark) / min(entry, effective_mark)
        if price_ratio > 10.0:
            missing.append("ENTRY_PRICE_CURRENT_MARK_IMPOSSIBLE_RATIO")
        if symbol == "BTCUSDT" and entry < 1000.0 and effective_mark > 10000.0:
            missing.append("BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_CURRENT_MARK")
    classification = "ECONOMIC_FILL" if not missing else missing[0]
    economic = classification == "ECONOMIC_FILL"
    price_delta = None
    unrealized_pnl = None
    if economic and effective_mark is not None and entry is not None and quantity is not None:
        price_delta = effective_mark - entry
        unrealized_pnl = price_delta * quantity if side == "long" else -price_delta * quantity
    raw_source_fill_ids = row.get("source_fill_ids")
    if isinstance(raw_source_fill_ids, (list, tuple, set)):
        source_fill_ids = [str(item) for item in raw_source_fill_ids if item not in (None, "")]
    else:
        source_fill_ids = []
    if not source_fill_ids:
        source_fill_ids = [fill_identity(row)]
    return {
        "fill_id": fill_identity(row),
        "ledger_row_id": fill_identity(row),
        "source_fill_ids": source_fill_ids,
        "intent_id": row.get("intent_id"),
        "signal_id": lineage["signal_id"],
        "prediction_id": lineage["prediction_id"],
        "risk_decision_id": lineage["risk_decision_id"],
        "orchestrator_decision_id": lineage["orchestrator_decision_id"],
        "symbol": symbol,
        "timeframe": row.get("timeframe"),
        "side": side,
        "action": row.get("action") or row.get("selected_action") or side,
        "quantity": quantity,
        "notional": notional,
        "entry_price": entry,
        "fill_price": coerce_float(row.get("fill_price")),
        "mark_price_at_fill": coerce_float(row.get("fill_price")) or coerce_float(row.get("mark_price_at_fill")) or entry,
        "current_mark_price": effective_mark,
        "mark_price_source": mark_price_source or row.get("latest_price_source"),
        "mark_price_age_seconds": mark_price_age_seconds,
        "price_delta": price_delta,
        "unrealized_pnl": unrealized_pnl,
        "paper_session_id": row.get("paper_session_id"),
        "session_id": row.get("session_id"),
        "reset_session_id": row.get("reset_session_id"),
        "starting_equity_usd": row.get("starting_equity_usd"),
        "fill_time_est": row.get("accepted_at_est") or row.get("generated_est"),
        "fill_time_utc": row.get("accepted_at_utc") or row.get("generated_utc"),
        "trainer_source": row.get("trainer_source"),
        "model_id": row.get("model_id"),
        "checkpoint_id": row.get("checkpoint_id"),
        "feature_snapshot_id": row.get("feature_snapshot_id"),
        "paper_fill_status": row.get("paper_fill_status") or row.get("decision"),
        "paper_sizing_source": row.get("paper_sizing_source"),
        "economic_fill": economic,
        "classification": classification,
        "reason_if_non_economic": None if economic else ",".join(missing),
        "missing_fields": missing,
        "raw_row_source": row.get("source") or "v2:paper:ledger.accepted",
    }


def classify_fills(
    rows: list[Mapping[str, Any]],
    mark_prices: Mapping[str, tuple[float | None, str | None, float | None]],
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        mark, source, age = mark_prices.get(symbol, (None, None, None))
        inventory.append(
            classify_fill(
                row,
                mark_price=mark,
                mark_price_source=source,
                mark_price_age_seconds=age,
            )
        )
    return inventory


def reconstruct_positions(inventory: list[Mapping[str, Any]]) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "net_quantity": 0.0,
            "avg_entry_price": 0.0,
            "gross_notional": 0.0,
            "realized_pnl": 0.0,
            "fill_count": 0,
            "closed_fill_count": 0,
            "last_mark_price": None,
            "last_mark_price_source": None,
            "paper_session_ids": set(),
            "session_ids": set(),
            "reset_session_ids": set(),
            "starting_equity_usd": None,
            "fills": [],
        }
    )
    for fill in inventory:
        if fill.get("classification") != "ECONOMIC_FILL":
            continue
        symbol = str(fill["symbol"])
        state = states[symbol]
        side = str(fill.get("side"))
        qty = float(fill.get("quantity") or 0.0)
        price = float(fill.get("entry_price") or 0.0)
        signed_qty = qty if side == "long" else -qty
        existing_qty = float(state["net_quantity"])
        existing_sign = 1 if existing_qty >= 0 else -1
        incoming_sign = 1 if signed_qty >= 0 else -1
        if existing_qty == 0 or existing_sign == incoming_sign:
            new_abs = abs(existing_qty) + abs(signed_qty)
            weighted = (abs(existing_qty) * float(state["avg_entry_price"])) + (abs(signed_qty) * price)
            state["avg_entry_price"] = weighted / new_abs if new_abs else 0.0
            state["net_quantity"] = existing_qty + signed_qty
        else:
            closing_qty = min(abs(existing_qty), abs(signed_qty))
            state["realized_pnl"] += (price - float(state["avg_entry_price"])) * closing_qty * existing_sign
            state["closed_fill_count"] += 1
            remaining_qty = existing_qty + signed_qty
            if remaining_qty == 0:
                state["net_quantity"] = 0.0
                state["avg_entry_price"] = 0.0
            elif (1 if remaining_qty >= 0 else -1) == existing_sign:
                state["net_quantity"] = remaining_qty
            else:
                state["net_quantity"] = remaining_qty
                state["avg_entry_price"] = price
        state["gross_notional"] += float(fill.get("notional") or 0.0)
        state["fill_count"] += 1
        state["last_mark_price"] = fill.get("current_mark_price")
        state["last_mark_price_source"] = fill.get("mark_price_source")
        for field, state_field in (
            ("paper_session_id", "paper_session_ids"),
            ("session_id", "session_ids"),
            ("reset_session_id", "reset_session_ids"),
        ):
            value = fill.get(field)
            if value not in (None, ""):
                state[state_field].add(str(value))
        if state.get("starting_equity_usd") in (None, "") and fill.get("starting_equity_usd") not in (None, ""):
            state["starting_equity_usd"] = fill.get("starting_equity_usd")
        state["fills"].append(fill.get("fill_id"))

    positions: list[dict[str, Any]] = []
    realized = 0.0
    unrealized = 0.0
    open_count = 0
    closed_count = 0
    for symbol, state in sorted(states.items()):
        net_qty = float(state["net_quantity"])
        avg_entry = float(state["avg_entry_price"])
        mark = coerce_float(state.get("last_mark_price"))
        position_unrealized = 0.0
        if net_qty and mark is not None and avg_entry > 0:
            position_unrealized = (mark - avg_entry) * net_qty
        realized += float(state["realized_pnl"])
        unrealized += position_unrealized
        if abs(net_qty) > 0:
            open_count += 1
        if state["closed_fill_count"]:
            closed_count += int(state["closed_fill_count"])
        paper_session_ids = sorted(str(item) for item in state["paper_session_ids"])
        session_ids = sorted(str(item) for item in state["session_ids"])
        reset_session_ids = sorted(str(item) for item in state["reset_session_ids"])
        positions.append(
            {
                "symbol": symbol,
                "side": "long" if net_qty > 0 else ("short" if net_qty < 0 else "flat"),
                "open_position": abs(net_qty) > 0,
                "avg_entry_price": avg_entry,
                "net_quantity": net_qty,
                "gross_notional": float(state["gross_notional"]),
                "realized_pnl": float(state["realized_pnl"]),
                "unrealized_pnl": position_unrealized,
                "last_mark_price": mark,
                "last_mark_price_source": state.get("last_mark_price_source"),
                "paper_session_id": paper_session_ids[0] if len(paper_session_ids) == 1 else None,
                "paper_session_ids": paper_session_ids,
                "session_id": session_ids[0] if len(session_ids) == 1 else None,
                "session_ids": session_ids,
                "reset_session_id": reset_session_ids[0] if len(reset_session_ids) == 1 else None,
                "reset_session_ids": reset_session_ids,
                "starting_equity_usd": state.get("starting_equity_usd"),
                "position_age_seconds": None,
                "fill_count": int(state["fill_count"]),
                "closed_fill_count": int(state["closed_fill_count"]),
                "source_fill_ids": list(state["fills"]),
            }
        )
    return {
        "open_positions_count": open_count,
        "closed_positions_count": closed_count,
        "positions_by_symbol": positions,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
    }


def zero_pnl_reason(inventory: list[Mapping[str, Any]], positions: Mapping[str, Any]) -> str | None:
    economic = [row for row in inventory if row.get("classification") == "ECONOMIC_FILL"]
    if not inventory:
        return "NO_ACCEPTED_PAPER_FILL_IN_CURRENT_V2_LEDGER"
    if not economic:
        return "NO_ECONOMIC_FILLS"
    if not positions.get("open_positions_count"):
        return "NO_OPEN_POSITIONS"
    missing_mark = [row for row in economic if not row.get("current_mark_price")]
    if missing_mark:
        return "MARK_PRICE_MISSING"
    total = float(positions.get("realized_pnl") or 0.0) + float(positions.get("unrealized_pnl") or 0.0)
    if abs(total) < 0.00000001:
        all_flat = all(abs(float(row.get("price_delta") or 0.0)) < 0.00000001 for row in economic)
        return "MARK_PRICE_EQUALS_ENTRY_PRICE" if all_flat else "ROUNDING_TO_ZERO"
    return None


def build_accounting_state(
    accepted_rows: list[Mapping[str, Any]],
    closed_rows: list[Mapping[str, Any]],
    mark_prices: Mapping[str, tuple[float | None, str | None, float | None]],
    *,
    initial_capital: float = 10_000.0,
    fees: float = 0.0,
    slippage: float = 0.0,
) -> dict[str, Any]:
    active_accepted_rows, suppressed_closed_rows = suppress_accepted_rows_already_closed(
        accepted_rows,
        closed_rows,
    )
    inventory = classify_fills(active_accepted_rows, mark_prices)
    positions = reconstruct_positions(inventory)
    explicit_closed_realized = 0.0
    for row in closed_rows:
        explicit_closed_realized += closed_realized_pnl_usd(row)
    reconstructed_fill_realized = float(positions["realized_pnl"])
    has_explicit_closed_ledger = bool(closed_rows)
    realized = explicit_closed_realized if has_explicit_closed_ledger else reconstructed_fill_realized
    session_realized = explicit_closed_realized if has_explicit_closed_ledger else reconstructed_fill_realized
    unrealized = float(positions["unrealized_pnl"])
    total = realized + unrealized - float(fees) - float(slippage)
    equity = float(initial_capital) + total
    expected_equity = float(initial_capital) + realized + unrealized - float(fees) - float(slippage)
    reconciliation_difference = equity - expected_equity
    economic = [row for row in inventory if row.get("classification") == "ECONOMIC_FILL"]
    non_economic = [row for row in inventory if row.get("classification") != "ECONOMIC_FILL"]
    reason = zero_pnl_reason(inventory, {**positions, "realized_pnl": realized, "unrealized_pnl": unrealized})
    return {
        "accepted_fill_count": len(accepted_rows),
        "active_accepted_fill_count": len(active_accepted_rows),
        "accepted_closed_filter_count": len(suppressed_closed_rows),
        "accepted_closed_filter_sample": suppressed_closed_rows[:25],
        "economic_fill_count": len(economic),
        "non_economic_fill_count": len(non_economic),
        "inventory": inventory,
        "non_economic_fill_blockers": [
            {
                "fill_id": row.get("fill_id"),
                "symbol": row.get("symbol"),
                "classification": row.get("classification"),
                "missing_fields": row.get("missing_fields"),
            }
            for row in non_economic
        ],
        "open_positions_count": positions["open_positions_count"],
        "closed_positions_count": positions["closed_positions_count"] + len(closed_rows),
        "positions_by_symbol": positions["positions_by_symbol"],
        "realized_pnl": realized,
        "cumulative_realized_pnl": realized,
        "session_realized_pnl": session_realized,
        "lifetime_realized_pnl": realized,
        "closed_ledger_net_pnl": explicit_closed_realized,
        "reconstructed_fill_realized_pnl": reconstructed_fill_realized,
        "realized_pnl_source": (
            "explicit_closed_trade_ledger"
            if has_explicit_closed_ledger
            else "reconstructed_accepted_fills"
        ),
        "reconstructed_fill_realized_pnl_suppressed": (
            reconstructed_fill_realized if has_explicit_closed_ledger else 0.0
        ),
        "unrealized_pnl": unrealized,
        "fees": float(fees),
        "slippage": float(slippage),
        "separately_unbooked_costs": float(fees) + float(slippage),
        "total_pnl": total,
        "current_session_equity": equity,
        "expected_equity": expected_equity,
        "equity_reconciliation_difference": reconciliation_difference,
        "equity_formula": (
            "initial_capital + cumulative_realized_pnl + unrealized_pnl "
            "- separately_unbooked_costs"
        ),
        "closed_ledger_matches_portfolio_realized": (
            abs(explicit_closed_realized - realized) <= 0.01
            if has_explicit_closed_ledger
            else None
        ),
        "zero_pnl_reason": reason,
        "ledger_to_position_status": (
            "FILL_TO_POSITION_PIPE_BROKEN"
            if accepted_rows and not economic
            else "NO_ACCEPTED_PAPER_FILL_IN_CURRENT_V2_LEDGER"
            if not accepted_rows
            else "LEDGER_TO_POSITION_PIPE_OK"
        ),
    }
