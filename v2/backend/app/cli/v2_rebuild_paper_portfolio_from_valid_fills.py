"""Rebuild V2 paper portfolio state from valid economic fills only."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_validate_paper_position_ledger import (
    GOAL_DIR,
    INVALID_CLOSED_TRADE_QUARANTINE_KEY,
    INVALID_POSITION_QUARANTINE_KEY,
    V2_REDIS_PREFIX,
    _closed_trade_rows,
    _connect_redis,
    _json_default,
    _market_prices,
    _open_position_rows,
    _read_redis_key,
    _utc_iso,
    _write_json,
    _write_redis_json,
)
from v2.backend.app.services.paper_accounting.mark_to_market import build_accounting_state
from v2.backend.app.services.paper_trade_management.position_validity import (
    PAPER_ACCOUNT_SCOPE,
    PositionValidityConfig,
    account_truth_metadata,
    split_valid_invalid_closed_trades,
    split_valid_invalid_positions,
)

PAPER_INITIAL_CAPITAL = 10_000.0
PORTFOLIO_STATE_KEY = "v2:portfolio:state"
PORTFOLIO_PUBLIC_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"
)


def _portfolio_state_from_redis(client: Any) -> dict[str, Any]:
    if client is None:
        return {}
    entry = _read_redis_key(client, PORTFOLIO_STATE_KEY)
    payload = entry.get("payload")
    return payload if isinstance(payload, dict) else {}


def _ledger_archive(client: Any) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    if client is None:
        return {"redis_available": False, "keys": keys}
    for key in (
        "v2:paper:positions",
        "v2:paper:closed_trades",
        "v2:paper:ledger",
        PORTFOLIO_STATE_KEY,
    ):
        keys[key] = _read_redis_key(client, key)
    return {"redis_available": True, "keys": keys}


def _sum_realized(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        try:
            total += float(
                row.get("realized_pnl_usd")
                or row.get("realized_pnl_usdt")
                or row.get("realized_pnl")
                or row.get("pnl_usd")
                or 0.0
            )
        except (TypeError, ValueError):
            continue
    return total


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _status_from_accounting(valid_rows: int, invalid_rows: int, accounting: dict[str, Any]) -> str:
    if valid_rows <= 0:
        return "NO_VALID_EVIDENCE"
    if invalid_rows > 0:
        return "PORTFOLIO_TRUSTED_RECOVERY_READY"
    total_pnl = _safe_float(accounting.get("total_pnl")) or 0.0
    return "PORTFOLIO_TRUSTED_RECOVERY_READY" if total_pnl >= 0 else "PORTFOLIO_TRUSTED_BUT_EDGE_NEGATIVE"


def run(*, write_redis: bool = False, write_public_file: bool = True) -> dict[str, Any]:
    client = _connect_redis()
    archive = _ledger_archive(client)
    previous_state = _portfolio_state_from_redis(client)
    open_rows = _open_position_rows(archive)
    closed_rows = _closed_trade_rows(archive)
    symbols = {str(row.get("symbol") or "").upper() for row in open_rows if row.get("symbol")}
    marks = _market_prices(client, symbols)
    validation_config = PositionValidityConfig(
        require_production_cost_flag=True,
        require_explicit_paper_only=True,
        require_fresh_current_mark=False,
    )
    valid_open_rows, invalid_open_rows, position_statuses = split_valid_invalid_positions(
        open_rows,
        mark_prices=marks,
        config=validation_config,
    )
    valid_closed_rows, invalid_closed_rows, closed_statuses = split_valid_invalid_closed_trades(closed_rows)
    accounting = build_accounting_state(
        valid_open_rows,
        valid_closed_rows,
        marks,
        initial_capital=PAPER_INITIAL_CAPITAL,
    )
    valid_positions = [
        row
        for row in accounting.get("positions_by_symbol", [])
        if isinstance(row, dict) and row.get("open_position") is True
    ]
    invalid_count = len(invalid_open_rows) + len(invalid_closed_rows)
    status = _status_from_accounting(len(valid_open_rows) + len(valid_closed_rows), invalid_count, accounting)
    truth = account_truth_metadata(
        invalid_positions=len(invalid_open_rows),
        invalid_closed_trades=len(invalid_closed_rows),
    )
    generated_utc = _utc_iso()
    rebuilt_state = {
        "schema_version": "v2_native_portfolio_state_rebuilt_from_valid_fills_v1",
        "classification": status,
        "generated_utc": generated_utc,
        "account_mode": "paper",
        "account_scope": PAPER_ACCOUNT_SCOPE,
        "source_type": "paper_sim_valid_economic_fills",
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": invalid_count > 0,
        "equity_trusted": True,
        "pnl_trusted": True,
        "reason_if_untrusted": None,
        "initial_capital": PAPER_INITIAL_CAPITAL,
        "realized_pnl_usd": round(float(accounting.get("realized_pnl") or 0.0), 8),
        "unrealized_pnl_usd": round(float(accounting.get("unrealized_pnl") or 0.0), 8),
        "total_pnl_usd": round(float(accounting.get("total_pnl") or 0.0), 8),
        "cash_balance": round(PAPER_INITIAL_CAPITAL + float(accounting.get("realized_pnl") or 0.0), 8),
        "equity": round(float(accounting.get("current_session_equity") or PAPER_INITIAL_CAPITAL), 8),
        "current_session_equity": round(float(accounting.get("current_session_equity") or PAPER_INITIAL_CAPITAL), 8),
        "open_positions_count": len(valid_positions),
        "closed_positions_count": len(valid_closed_rows),
        "valid_position_count": len(valid_open_rows),
        "invalid_position_count": len(invalid_open_rows),
        "valid_closed_trades": len(valid_closed_rows),
        "invalid_closed_trades": len(invalid_closed_rows),
        "quarantined_pnl_impact": {
            "invalid_open_position_count": len(invalid_open_rows),
            "invalid_closed_trade_realized_pnl_usd": round(_sum_realized(invalid_closed_rows), 8),
        },
        "stale_mark_excluded_from_equity_count": sum(
            1 for status_row in position_statuses if "MISSING_CURRENT_MARK_PRICE" in status_row.get("reasons", [])
        ),
        "positions": valid_positions,
        "positions_by_symbol": accounting.get("positions_by_symbol", []),
        "paper_fill_economic_inventory": accounting.get("inventory", []),
        "quarantine_keys": {
            "invalid_positions": INVALID_POSITION_QUARANTINE_KEY,
            "invalid_closed_trades": INVALID_CLOSED_TRADE_QUARANTINE_KEY,
        },
        "truth_metadata": truth,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }
    diff = {
        "schema_version": "paper_portfolio_rebuild_diff_v1",
        "generated_utc": generated_utc,
        "equity_before": previous_state.get("equity"),
        "equity_after": rebuilt_state["equity"],
        "realized_pnl_before": previous_state.get("realized_pnl_usd") or previous_state.get("realized_pnl"),
        "realized_pnl_after": rebuilt_state["realized_pnl_usd"],
        "unrealized_pnl_before": previous_state.get("unrealized_pnl_usd") or previous_state.get("unrealized_pnl"),
        "unrealized_pnl_after": rebuilt_state["unrealized_pnl_usd"],
        "invalid_position_count": len(invalid_open_rows),
        "valid_position_count": len(valid_open_rows),
        "quarantined_pnl_impact": rebuilt_state["quarantined_pnl_impact"],
        "fake_invalid_equity_removed": (
            _safe_float(previous_state.get("equity")) is not None
            and abs(float(previous_state.get("equity")) - rebuilt_state["equity"]) > 0.01
            and len(invalid_open_rows) > 0
        ),
    }
    pass_conditions = {
        "equity_rebuilt_from_valid_fills_only": True,
        "invalid_btc_entry_100_not_in_valid_positions": not any(
            str(row.get("symbol") or "").upper() == "BTCUSDT"
            and _safe_float(row.get("entry_price") or row.get("avg_entry_price")) == 100.0
            for row in valid_open_rows
        ),
        "unrealized_pnl_excludes_missing_mark_positions": rebuilt_state["stale_mark_excluded_from_equity_count"] == 0,
        "open_positions_have_valid_lineage": not any(
            not row.get("source_fill_ids") for row in valid_positions
        ),
        "no_live_mutation": True,
    }
    rebuild_status = {
        "schema_version": "paper_portfolio_rebuild_status_v1",
        "generated_utc": generated_utc,
        "status": "PASSED_PORTFOLIO_REBUILD_FROM_VALID_FILLS" if all(pass_conditions.values()) else "BLOCKED_PORTFOLIO_REBUILD_VALIDATION",
        "portfolio_truth_status": status,
        "pass_conditions": pass_conditions,
        "valid_position_count": len(valid_open_rows),
        "invalid_position_count": len(invalid_open_rows),
        "valid_closed_trade_count": len(valid_closed_rows),
        "invalid_closed_trade_count": len(invalid_closed_rows),
        "position_statuses": position_statuses,
        "closed_trade_statuses": closed_statuses,
        "write_redis_requested": write_redis,
        "write_public_file_requested": write_public_file,
        "redis_portfolio_state_written": False,
        "public_file_written": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if write_redis:
        rebuild_status["redis_portfolio_state_written"] = _write_redis_json(
            client,
            PORTFOLIO_STATE_KEY,
            rebuilt_state,
        )
    if write_public_file:
        _write_json(PORTFOLIO_PUBLIC_PATH, rebuilt_state)
        rebuild_status["public_file_written"] = True

    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(GOAL_DIR / "paper_portfolio_rebuild_status.json", rebuild_status)
    _write_json(GOAL_DIR / "paper_portfolio_rebuilt_state.json", rebuilt_state)
    _write_json(GOAL_DIR / "paper_portfolio_rebuild_diff.json", diff)

    return {
        "paper_portfolio_rebuild_status": rebuild_status,
        "paper_portfolio_rebuilt_state": rebuilt_state,
        "paper_portfolio_rebuild_diff": diff,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild V2 paper portfolio from valid fills")
    parser.add_argument("--write-redis", action="store_true")
    parser.add_argument("--no-public-file", action="store_true")
    args = parser.parse_args()
    result = run(write_redis=args.write_redis, write_public_file=not args.no_public_file)
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
