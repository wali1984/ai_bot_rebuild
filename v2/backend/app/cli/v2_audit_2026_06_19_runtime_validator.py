"""Read-only validator for the 2026-06-19 V2 paper audit remediation.

This module inspects V2 paper/runtime Redis evidence and reports whether each
F01-F13 audit finding has current runtime proof. It does not write Redis, does
not touch exchange APIs, and never changes live gate state.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2.backend.app.services.paper_trade_management.exits import PAPER_EXIT_POLICY_VERSION


SCHEMA_VERSION = "v2_audit_2026_06_19_runtime_validator_v1"
PASSED = "PASSED"
FAILED = "FAILED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
NO_GO = "NO_GO"
F02_ACTIVE_POLICY_MIN_CLOSED_TRADES = 200
F02_ACTIVE_POLICY_MIN_TRAILING_STOPS = 50
F09_ACTIVE_POLICY_MIN_CLOSED_TRADES = 50


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed == parsed else None
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _safe_load_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _read_json_key(redis_client: Any, key: str) -> Any:
    if redis_client is None or not key.startswith("v2:"):
        return None
    try:
        return _safe_load_json(redis_client.get(key))
    except Exception:
        return None


def _rows_from_payload(payload: Any, keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if not keys:
        keys = (
            "closed_trades",
            "closed",
            "closes",
            "closed_positions",
            "outcome_labels",
            "accepted",
            "rows",
        )
    for key in keys:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def _row_identity(row: dict[str, Any]) -> str:
    return str(
        _first_present(
            row.get("close_id"),
            row.get("outcome_label_id"),
            row.get("trainer_feedback_id"),
            row.get("position_id"),
            row.get("fill_id"),
            row.get("ledger_row_id"),
            f"{row.get('symbol')}|{row.get('timeframe')}|{row.get('side')}|"
            f"{row.get('entry_price')}|{row.get('exit_price')}|{row.get('exit_time') or row.get('exit_price_utc')}",
        )
    )


def _dedupe_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(row)
    return out


def _closed_trade_rows(redis_client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_rows_from_payload(_read_json_key(redis_client, "v2:paper:closed_trades")))
    ledger = _read_json_key(redis_client, "v2:paper:ledger")
    rows.extend(
        _rows_from_payload(
            ledger,
            keys=("closed_trades", "closed", "closes", "closed_positions", "outcome_labels"),
        )
    )
    return _dedupe_rows(rows)


def _scan_json(redis_client: Any, pattern: str, *, limit: int = 5000) -> list[dict[str, Any]]:
    if redis_client is None:
        return []
    try:
        keys = list(redis_client.scan_iter(match=pattern, count=500))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for key in keys[:limit]:
        payload = _read_json_key(redis_client, str(key))
        if isinstance(payload, dict):
            payload.setdefault("_redis_key", str(key))
            rows.append(payload)
    return rows


def _realized_pnl(row: dict[str, Any]) -> float:
    return float(
        _coerce_float(
            _first_present(
                row.get("realized_pnl_usd"),
                row.get("realized_pnl_usdt"),
                row.get("net_realized_pnl_usd"),
                row.get("net_pnl_usd"),
                row.get("realized_pnl"),
            )
        )
        or 0.0
    )


def _winner(row: dict[str, Any]) -> bool:
    value = row.get("winner")
    if isinstance(value, bool):
        return value
    pnl = _realized_pnl(row)
    if pnl != 0.0:
        return pnl > 0.0
    bps = _coerce_float(row.get("realized_pnl_bps"))
    return bool(bps is not None and bps > 0.0)


def _profit_factor(rows: list[dict[str, Any]]) -> float | None:
    gross_profit = sum(max(0.0, _realized_pnl(row)) for row in rows)
    gross_loss = abs(sum(min(0.0, _realized_pnl(row)) for row in rows))
    if gross_loss <= 0.0:
        return None if gross_profit <= 0.0 else float("inf")
    return gross_profit / gross_loss


def _side(row: dict[str, Any]) -> str:
    return str(_first_present(row.get("side"), row.get("action"), row.get("direction"), "")).lower()


def _trailing_stop_metrics(
    *,
    rows: list[dict[str, Any]],
    total_net_pnl: float,
    prefix: str = "trailing_stop",
) -> dict[str, Any]:
    trailing_winners = sum(1 for row in rows if _winner(row))
    trailing_wr = trailing_winners / len(rows) if rows else None
    trailing_pnl = sum(_realized_pnl(row) for row in rows)
    trailing_loss_share = (
        abs(min(0.0, trailing_pnl)) / abs(min(0.0, total_net_pnl))
        if total_net_pnl < 0.0
        else 0.0
    )
    return {
        f"{prefix}_count": len(rows),
        f"{prefix}_win_rate": trailing_wr,
        f"{prefix}_pnl_usd": trailing_pnl,
        f"{prefix}_loss_share": trailing_loss_share,
    }


def _finding(status: str, metrics: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "metrics": metrics,
        "blockers": blockers,
    }


def _spread_values(row: dict[str, Any]) -> list[float]:
    values = [
        row.get("actual_observed_spread_entry_bps"),
        row.get("actual_observed_spread_exit_bps"),
        row.get("observed_bid_ask_spread_bps"),
        row.get("bid_ask_spread_bps"),
    ]
    micro = row.get("microstructure_context") if isinstance(row.get("microstructure_context"), dict) else {}
    values.extend(
        [
            micro.get("bid_ask_spread_bps"),
            micro.get("spread_bps"),
            micro.get("ob_spread_bps"),
        ]
    )
    return [parsed for value in values if (parsed := _coerce_float(value)) is not None]


def _build_finding_report(rows: list[dict[str, Any]], portfolio: dict[str, Any], outcome_memory_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    side_counts = Counter(_side(row) for row in rows if _side(row))
    winners = sum(1 for row in rows if _winner(row))
    win_rate = winners / total if total else None
    net_pnl = sum(_realized_pnl(row) for row in rows)
    pf = _profit_factor(rows) if rows else None
    findings: dict[str, Any] = {}

    long_count = side_counts.get("long", 0)
    short_count = side_counts.get("short", 0)
    status = PASSED if long_count >= 50 and short_count >= 50 else (FAILED if total else INSUFFICIENT)
    findings["F01"] = _finding(
        status,
        {"closed_trade_count": total, "long_count": long_count, "short_count": short_count, "side_counts": dict(side_counts)},
        [] if status == PASSED else ["NEED_AT_LEAST_50_LONG_AND_50_SHORT_CLOSED_TRADES"],
    )

    trailing = [
        row
        for row in rows
        if str(_first_present(row.get("close_reason"), row.get("exit_reason"), "")).upper()
        == "TIER_2_TRAILING_STOP"
    ]
    historical_trailing_metrics = _trailing_stop_metrics(rows=trailing, total_net_pnl=net_pnl)
    trailing_wr = historical_trailing_metrics["trailing_stop_win_rate"]
    trailing_pnl = historical_trailing_metrics["trailing_stop_pnl_usd"]
    trailing_loss_share = historical_trailing_metrics["trailing_stop_loss_share"]
    active_policy_rows = [
        row
        for row in rows
        if str(row.get("paper_exit_policy_version") or "") == PAPER_EXIT_POLICY_VERSION
    ]
    active_policy_net_pnl = sum(_realized_pnl(row) for row in active_policy_rows)
    active_policy_trailing = [
        row
        for row in active_policy_rows
        if str(_first_present(row.get("close_reason"), row.get("exit_reason"), "")).upper()
        == "TIER_2_TRAILING_STOP"
    ]
    active_policy_trailing_metrics = _trailing_stop_metrics(
        rows=active_policy_trailing,
        total_net_pnl=active_policy_net_pnl,
        prefix="active_policy_trailing_stop",
    )
    f02_metrics = {
        **historical_trailing_metrics,
        "trailing_loss_share": trailing_loss_share,
        "historical_trailing_stop_count": historical_trailing_metrics["trailing_stop_count"],
        "historical_trailing_stop_win_rate": trailing_wr,
        "historical_trailing_stop_pnl_usd": trailing_pnl,
        "historical_trailing_stop_loss_share": trailing_loss_share,
        "active_policy_version": PAPER_EXIT_POLICY_VERSION,
        "active_policy_closed_trade_count": len(active_policy_rows),
        "active_policy_net_pnl_usd": active_policy_net_pnl,
        "active_policy_min_closed_trades": F02_ACTIVE_POLICY_MIN_CLOSED_TRADES,
        "active_policy_min_trailing_stops": F02_ACTIVE_POLICY_MIN_TRAILING_STOPS,
        **active_policy_trailing_metrics,
    }
    active_policy_wr = active_policy_trailing_metrics["active_policy_trailing_stop_win_rate"]
    active_policy_pnl = active_policy_trailing_metrics["active_policy_trailing_stop_pnl_usd"]
    active_policy_loss_share = active_policy_trailing_metrics["active_policy_trailing_stop_loss_share"]
    if active_policy_rows:
        f02_blockers: list[str] = []
        if len(active_policy_rows) < F02_ACTIVE_POLICY_MIN_CLOSED_TRADES:
            f02_blockers.append("POST_POLICY_CLOSED_TRADE_SAMPLE_BELOW_MINIMUM")
        if len(active_policy_trailing) < F02_ACTIVE_POLICY_MIN_TRAILING_STOPS:
            f02_blockers.append("POST_POLICY_TRAILING_STOP_SAMPLE_BELOW_MINIMUM")
        if (
            not f02_blockers
            and active_policy_wr is not None
            and active_policy_wr >= 0.40
            and active_policy_pnl > 0.0
            and active_policy_loss_share < 0.50
        ):
            status = PASSED
        else:
            if not f02_blockers:
                f02_blockers.append("POST_POLICY_TRAILING_STOP_EXPECTANCY_NOT_PROVEN_POSITIVE")
            status = INSUFFICIENT if any("SAMPLE_BELOW_MINIMUM" in reason for reason in f02_blockers) else FAILED
    else:
        f02_blockers = [] if (
            trailing and trailing_wr is not None and trailing_wr >= 0.40 and trailing_pnl > 0.0 and trailing_loss_share < 0.50
        ) else ["TRAILING_STOP_RUNTIME_EXPECTANCY_NOT_PROVEN_POSITIVE"]
        status = (
            PASSED
            if not f02_blockers
            else (FAILED if trailing else INSUFFICIENT)
        )
    findings["F02"] = _finding(
        status,
        f02_metrics,
        [] if status == PASSED else f02_blockers,
    )

    closed_net = round(net_pnl, 8)
    portfolio_realized = _coerce_float(
        _first_present(
            portfolio.get("realized_pnl_usd"),
            portfolio.get("cumulative_realized_pnl"),
            portfolio.get("lifetime_realized_pnl"),
            portfolio.get("closed_ledger_net_pnl"),
        )
    )
    reconciliation_diff = None if portfolio_realized is None else round(float(portfolio_realized) - closed_net, 8)
    status = (
        PASSED
        if total and portfolio_realized is not None and abs(reconciliation_diff or 0.0) <= 0.01
        else (FAILED if total and portfolio_realized is not None else INSUFFICIENT)
    )
    findings["F03"] = _finding(
        status,
        {
            "closed_ledger_net_pnl_usd": closed_net,
            "portfolio_realized_pnl_usd": portfolio_realized,
            "reconciliation_diff_usd": reconciliation_diff,
        },
        [] if status == PASSED else ["PORTFOLIO_REALIZED_PNL_DOES_NOT_MATCH_CLOSED_LEDGER_OR_IS_MISSING"],
    )

    squeeze_scores = [_coerce_float(row.get("squeeze_evidence_score")) for row in rows]
    squeeze_scores = [value for value in squeeze_scores if value is not None]
    squeeze_sources = [row.get("squeeze_evidence_source") for row in rows if row.get("squeeze_evidence_source")]
    status = PASSED if squeeze_scores and squeeze_sources else (FAILED if total else INSUFFICIENT)
    findings["F04"] = _finding(
        status,
        {
            "closed_trade_count": total,
            "non_null_squeeze_count": len(squeeze_scores),
            "non_null_squeeze_rate": (len(squeeze_scores) / total if total else None),
            "squeeze_source_count": len(squeeze_sources),
        },
        [] if status == PASSED else ["SQUEEZE_EVIDENCE_NOT_PRESENT_WITH_SOURCE_ON_RUNTIME_CLOSED_TRADES"],
    )

    spreads = [value for row in rows for value in _spread_values(row)]
    rounded_spreads = sorted({round(value, 6) for value in spreads})
    all_static_2bps = bool(spreads) and all(abs(value - 2.0) <= 1e-9 for value in spreads)
    if not spreads:
        status = INSUFFICIENT
    elif all_static_2bps:
        status = FAILED
    elif len(rounded_spreads) >= 2:
        status = PASSED
    else:
        status = INSUFFICIENT
    findings["F05"] = _finding(
        status,
        {
            "spread_sample_count": len(spreads),
            "unique_spread_values": rounded_spreads[:25],
            "all_static_2bps": all_static_2bps,
        },
        [] if status == PASSED else ["RUNTIME_SPREAD_VARIABILITY_NOT_PROVEN"],
    )

    drawdowns = [_coerce_float(row.get("drawdown_at_entry")) for row in rows]
    drawdowns = [value for value in drawdowns if value is not None]
    unique_drawdowns = sorted({round(value, 6) for value in drawdowns})
    any_nonzero_drawdown = any(abs(value) > 1e-9 for value in drawdowns)
    status = PASSED if any_nonzero_drawdown and len(unique_drawdowns) >= 2 else (FAILED if drawdowns else INSUFFICIENT)
    findings["F06"] = _finding(
        status,
        {
            "drawdown_sample_count": len(drawdowns),
            "unique_drawdown_at_entry_values": unique_drawdowns[:25],
            "any_nonzero_drawdown": any_nonzero_drawdown,
        },
        [] if status == PASSED else ["DRAWDOWN_AT_ENTRY_VARIABILITY_NOT_PROVEN"],
    )

    by_timeframe: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for row in rows:
        tf = str(row.get("timeframe") or "unknown")
        by_timeframe[tf]["count"] += 1
        by_timeframe[tf]["pnl"] += _realized_pnl(row)
    negative_timeframes = [tf for tf, metrics in by_timeframe.items() if metrics["count"] >= 20 and metrics["pnl"] < 0.0]
    degraded_timeframe_buckets = {
        str(row.get("timeframe") or "")
        for row in outcome_memory_rows
        if (bool(row.get("degraded")) or row.get("block_reason"))
        and str(row.get("symbol") or "").upper() == "__ALL__"
        and int(_coerce_float(row.get("trade_count")) or 0) >= 20
    }
    unquarantined_negative_timeframes = [
        tf for tf in negative_timeframes if tf not in degraded_timeframe_buckets
    ]
    status = (
        PASSED
        if by_timeframe and not unquarantined_negative_timeframes
        else (FAILED if negative_timeframes else INSUFFICIENT)
    )
    findings["F07"] = _finding(
        status,
        {
            "timeframe_metrics": dict(by_timeframe),
            "negative_timeframes_with_min_20_trades": negative_timeframes,
            "degraded_timeframe_quarantine_buckets": sorted(degraded_timeframe_buckets),
            "unquarantined_negative_timeframes": unquarantined_negative_timeframes,
        },
        [] if status == PASSED else ["TIMEFRAME_EXPECTANCY_OR_ADAPTIVE_QUARANTINE_NOT_PROVEN"],
    )

    status = PASSED if total >= 300 and (win_rate or 0.0) > 0.3039 and (pf or 0.0) > 1.11 and net_pnl > 0.0 else (FAILED if total >= 300 else INSUFFICIENT)
    findings["F08"] = _finding(
        status,
        {
            "closed_trade_count": total,
            "win_rate": win_rate,
            "profit_factor": pf,
            "net_pnl_usd": net_pnl,
            "minimum_sample_required": 300,
        },
        [] if status == PASSED else ["POST_PATCH_GLOBAL_WR_PF_SAMPLE_NOT_PROVEN_IMPROVED"],
    )

    historical_modes = Counter(
        str(_first_present(row.get("strategy_selected_mode"), row.get("strategy_id"), row.get("strategy_family"), "unknown"))
        for row in rows
    )
    f09_rows = active_policy_rows if active_policy_rows else rows
    f09_evidence_scope = "active_policy" if active_policy_rows else "all_history"
    modes = Counter(
        str(_first_present(row.get("strategy_selected_mode"), row.get("strategy_id"), row.get("strategy_family"), "unknown"))
        for row in f09_rows
    )
    top_mode, top_count = modes.most_common(1)[0] if modes else ("none", 0)
    f09_total = len(f09_rows)
    top_share = top_count / f09_total if f09_total else None
    f09_blockers: list[str] = []
    if active_policy_rows and f09_total < F09_ACTIVE_POLICY_MIN_CLOSED_TRADES:
        f09_blockers.append("POST_POLICY_STRATEGY_MODE_SAMPLE_BELOW_MINIMUM")
        status = INSUFFICIENT
    elif f09_total and len(modes) >= 2 and (top_share or 1.0) < 0.80:
        status = PASSED
    else:
        f09_blockers.append("STRATEGY_ROUTER_MODE_DIVERSITY_NOT_PROVEN")
        status = FAILED if f09_total else INSUFFICIENT
    findings["F09"] = _finding(
        status,
        {
            "strategy_mode_evidence_scope": f09_evidence_scope,
            "strategy_mode_counts": dict(modes),
            "top_mode": top_mode,
            "top_mode_share": top_share,
            "closed_trade_count": f09_total,
            "minimum_closed_trades": F09_ACTIVE_POLICY_MIN_CLOSED_TRADES if active_policy_rows else None,
            "active_policy_version": PAPER_EXIT_POLICY_VERSION,
            "active_policy_closed_trade_count": len(active_policy_rows),
            "active_policy_strategy_mode_counts": (
                dict(modes)
                if active_policy_rows
                else {}
            ),
            "historical_strategy_mode_counts": dict(historical_modes),
            "historical_closed_trade_count": total,
        },
        [] if status == PASSED else f09_blockers,
    )

    degraded_buckets = [row for row in outcome_memory_rows if bool(row.get("degraded")) or row.get("block_reason")]
    current_buckets = [row for row in outcome_memory_rows if str(row.get("data_source") or "REDIS") == "REDIS"]
    status = PASSED if degraded_buckets else (FAILED if current_buckets else INSUFFICIENT)
    findings["F10"] = _finding(
        status,
        {
            "outcome_memory_bucket_count": len(outcome_memory_rows),
            "current_bucket_count": len(current_buckets),
            "degraded_bucket_count": len(degraded_buckets),
            "sample_degraded_buckets": degraded_buckets[:10],
        },
        [] if status == PASSED else ["CURRENT_ADAPTIVE_QUARANTINE_BUCKETS_NOT_PROVEN_ACTIVE"],
    )

    expected_slippage = [_coerce_float(row.get("expected_slippage_bps")) for row in rows]
    expected_slippage = [value for value in expected_slippage if value is not None]
    implementation_shortfall = [_coerce_float(row.get("implementation_shortfall_usd")) for row in rows]
    implementation_shortfall = [value for value in implementation_shortfall if value is not None]
    slippage_sources = [row.get("expected_slippage_source") for row in rows if row.get("expected_slippage_source")]
    status = PASSED if expected_slippage and implementation_shortfall and slippage_sources else (FAILED if total else INSUFFICIENT)
    findings["F11"] = _finding(
        status,
        {
            "expected_slippage_count": len(expected_slippage),
            "implementation_shortfall_count": len(implementation_shortfall),
            "expected_slippage_sources": sorted(set(str(src) for src in slippage_sources)),
        },
        [] if status == PASSED else ["EXPECTED_VS_REALIZED_SLIPPAGE_RUNTIME_EVIDENCE_MISSING"],
    )

    status = PASSED if long_count >= 50 else (FAILED if total else INSUFFICIENT)
    findings["F12"] = _finding(
        status,
        {"long_closed_trade_count": long_count, "minimum_required": 50},
        [] if status == PASSED else ["LONG_PAPER_LIFECYCLE_RUNTIME_SAMPLE_NOT_PROVEN"],
    )

    path_fields = (
        "mfe_bps",
        "mae_bps",
        "intra_trade_high_price",
        "intra_trade_low_price",
    )
    complete_path_rows = [
        row
        for row in rows
        if all(_coerce_float(row.get(field)) is not None for field in path_fields)
    ]
    trailing_history_rows = [row for row in rows if row.get("trailing_stop_history")]
    status = PASSED if total and len(complete_path_rows) == total else (FAILED if total else INSUFFICIENT)
    findings["F13"] = _finding(
        status,
        {
            "closed_trade_count": total,
            "path_complete_count": len(complete_path_rows),
            "trailing_history_count": len(trailing_history_rows),
        },
        [] if status == PASSED else ["MFE_MAE_INTRATRADE_PATH_TELEMETRY_MISSING_ON_CLOSED_TRADES"],
    )
    return findings


def _live_gate(redis_client: Any) -> str:
    payload = _read_json_key(redis_client, "v2:live_gate:state")
    if isinstance(payload, dict):
        return str(_first_present(payload.get("live_gate"), payload.get("status"), "blocked_human_only"))
    return "blocked_human_only"


def build_report(redis_client: Any | None = None, *, generated_utc: str | None = None) -> dict[str, Any]:
    rows = _closed_trade_rows(redis_client)
    portfolio = _read_json_key(redis_client, "v2:portfolio:state")
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    outcome_memory = _scan_json(redis_client, "v2:paper:outcome_memory:*")
    findings = _build_finding_report(rows, portfolio, outcome_memory)
    status_counts = Counter(row["status"] for row in findings.values())
    passed = all(row["status"] == PASSED for row in findings.values())
    gate = _live_gate(redis_client)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc or _utc_iso(),
        "paper_only": True,
        "read_only": True,
        "writes_redis": False,
        "places_real_order": False,
        "live_gate": gate,
        "live_gate_ok": gate == "blocked_human_only",
        "ready_for_live": False,
        "ready_phrase_allowed": False,
        "overall_status": PASSED if passed and gate == "blocked_human_only" else NO_GO,
        "status_counts": dict(status_counts),
        "closed_trade_count": len(rows),
        "outcome_memory_bucket_count": len(outcome_memory),
        "findings": findings,
        "remaining_blockers": [
            finding
            for finding, row in findings.items()
            if row["status"] != PASSED
        ],
    }


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_audit_2026_06_19_runtime_validator")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = build_report(_connect_redis())
    if args.out is not None:
        write_report(report, args.out)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["overall_status"] == PASSED else 2


if __name__ == "__main__":
    sys.exit(main())
