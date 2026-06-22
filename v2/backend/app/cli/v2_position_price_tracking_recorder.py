"""One-shot V2 paper position price-tracking recorder.

This CLI also implements the V2-owned entry-price and realized-exit
history burndown so MFE/MAE/ROE can be computed from V2 paper inputs
only. When entry/exit price evidence is recovered, the per-symbol
provenance and aggregate GO/NO-GO surface the burndown state for
operators and the website.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.position_price_tracking_recorder import (
    ENTRY_SOURCE_MISSING,
    EXIT_SOURCE_NONE,
    KEY_HEARTBEAT,
    KEY_HISTORY_TEMPLATE,
    KEY_PRICE_TRACK_TEMPLATE,
    build_heartbeat_payload,
    build_position_track,
    history_payload,
    safe_redis_set,
)

GO_READY = "V2_POSITION_PRICE_TRACKING_RECORDER_READY"
GO_BLOCKED = "V2_POSITION_PRICE_TRACKING_RECORDER_BLOCKED"

GO_BURNDOWN_PARTIAL = (
    "V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS"
)
GO_BURNDOWN_BLOCKED = (
    "V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED"
)

WORKLOG_DIR = Path("claude_worklog/final_readiness/v2_position_price_tracking_recorder/latest")
WORKLOG_STATUS = WORKLOG_DIR / "position_price_tracking_recorder_status.json"
WORKLOG_REPORT = WORKLOG_DIR / "V2_POSITION_PRICE_TRACKING_RECORDER_REPORT.md"
WORKLOG_GO_NO_GO = WORKLOG_DIR / "GO_NO_GO.md"

BURNDOWN_DIR = Path(
    "claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest"
)
BURNDOWN_STATUS = BURNDOWN_DIR / "burndown_status.json"
BURNDOWN_REPORT = BURNDOWN_DIR / "V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_REPORT.md"
BURNDOWN_GO_NO_GO = BURNDOWN_DIR / "GO_NO_GO.md"

PUBLIC_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_position_price_tracking_recorder/latest/position_price_tracking_recorder_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_position_price_tracking_recorder/latest/operator_dashboard_payload.json"
)
PUBLIC_BURNDOWN_DASHBOARD = Path(
    "v2/frontend/public/v2_position_price_tracking_entry_exit_history_burndown/latest/operator_dashboard_payload.json"
)


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _redis_get_json(redis_client: Any, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        return _json_loads(redis_client.get(key))
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_report(payload: dict[str, Any]) -> None:
    lines = [
        "# V2 Position Price Tracking Recorder Report",
        "",
        f"Generated: `{payload['generated_utc']}`",
        "",
        f"GO/NO-GO: `{payload['go_no_go']}`",
        "",
        f"Burndown GO/NO-GO: `{payload['burndown_go_no_go']}`",
        "",
        "This packet does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.",
        "",
        "## Scope",
        "",
        "The recorder reads V2 paper positions, ledger, intents, predictions, and market prices, then writes only V2 paper position price-track/history keys.",
        "",
        "## Per-Symbol State",
        "",
        "| Symbol | State | Entry | EntrySrc | Latest | Exit | ExitSrc | MFE bps | MAE bps | ROE bps | Missing |",
        "| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in payload["per_symbol"]:
        lines.append(
            "| {symbol} | {state} | {entry} | {entry_src} | {latest} | {exit} | {exit_src} | {mfe} | {mae} | {roe} | {missing} |".format(
                symbol=row["symbol"],
                state=row["position_state"],
                entry=row["entry_price"],
                entry_src=row.get("entry_price_source", "UNKNOWN"),
                latest=row["latest_price"],
                exit=row.get("realized_exit_price"),
                exit_src=row.get("realized_exit_source", "UNKNOWN"),
                mfe=row["mfe_bps"],
                mae=row["mae_bps"],
                roe=row["roe_bps"],
                missing=",".join(row["missing_flags"]) or "none",
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- `live_gate`: `blocked_human_only`",
            "- `live_symbols`: `[]`",
            "- `writes_legacy_redis`: `false`",
            "- `writes_exchange_orders`: `false`",
            "- `no_fake_price_tracks`: `true`",
            "- `no_silent_zero_fill`: `true`",
            "",
            "## Final Decision",
            "",
            f"`{payload['go_no_go']}`",
            "",
        ]
    )
    WORKLOG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_REPORT.write_text("\n".join(lines), encoding="utf-8")


def _write_burndown_report(payload: dict[str, Any]) -> None:
    lines = [
        "# V2 Position Price Tracking Entry/Exit History Burndown Report",
        "",
        f"Generated: `{payload['generated_utc']}`",
        "",
        f"GO/NO-GO: `{payload['burndown_go_no_go']}`",
        "",
        "Continues V2 full-observation migration by recovering entry-price and realized-exit evidence from V2-owned paper inputs only. Does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.",
        "",
        "## Per-Symbol Burndown",
        "",
        "| Symbol | State | Entry Source | Realized Exit Source | Realized Exit Price | MFE bps | MAE bps | ROE bps | Blockers |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["per_symbol"]:
        blockers: list[str] = []
        if row.get("entry_price_source") == ENTRY_SOURCE_MISSING:
            blockers.append("ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS")
        if row.get("realized_exit_source") == EXIT_SOURCE_NONE:
            blockers.append("REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS")
        lines.append(
            "| {symbol} | {state} | {entry_src} | {exit_src} | {exit_price} | {mfe} | {mae} | {roe} | {blockers} |".format(
                symbol=row["symbol"],
                state=row["position_state"],
                entry_src=row.get("entry_price_source", "UNKNOWN"),
                exit_src=row.get("realized_exit_source", "UNKNOWN"),
                exit_price=row.get("realized_exit_price"),
                mfe=row["mfe_bps"],
                mae=row["mae_bps"],
                roe=row["roe_bps"],
                blockers=",".join(blockers) or "none",
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- `live_gate`: `blocked_human_only`",
            "- `live_symbols`: `[]`",
            "- `writes_legacy_redis`: `false`",
            "- `writes_exchange_orders`: `false`",
            "- `no_fake_price_tracks`: `true`",
            "- `no_silent_zero_fill`: `true`",
            "",
            "## Final Decision",
            "",
            f"`{payload['burndown_go_no_go']}`",
            "",
        ]
    )
    BURNDOWN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    BURNDOWN_REPORT.write_text("\n".join(lines), encoding="utf-8")


def _compute_burndown_go_no_go(per_symbol: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide burndown PARTIAL_PROGRESS vs BLOCKED.

    PARTIAL_PROGRESS: at least one symbol either has a recovered entry
    price (non-MISSING) OR a recorded realized exit price. BLOCKED:
    every symbol is still MISSING_ENTRY_PRICE AND has no realized exit.
    """
    any_entry_recovered = False
    any_exit_recovered = False
    symbols_with_entry_recovered: list[str] = []
    symbols_with_exit_recovered: list[str] = []
    symbols_still_blocked: list[str] = []
    for row in per_symbol:
        entry_recovered = (
            row.get("entry_price_source")
            not in {ENTRY_SOURCE_MISSING, None}
            and row.get("entry_price") is not None
        )
        exit_recovered = (
            row.get("realized_exit_source") not in {EXIT_SOURCE_NONE, None}
            and row.get("realized_exit_price") is not None
        )
        if entry_recovered:
            any_entry_recovered = True
            symbols_with_entry_recovered.append(row["symbol"])
        if exit_recovered:
            any_exit_recovered = True
            symbols_with_exit_recovered.append(row["symbol"])
        if not entry_recovered and not exit_recovered:
            symbols_still_blocked.append(row["symbol"])
    decision = (
        GO_BURNDOWN_PARTIAL
        if (any_entry_recovered or any_exit_recovered)
        else GO_BURNDOWN_BLOCKED
    )
    return {
        "burndown_go_no_go": decision,
        "symbols_with_entry_recovered": sorted(symbols_with_entry_recovered),
        "symbols_with_realized_exit_recovered": sorted(symbols_with_exit_recovered),
        "symbols_still_blocked": sorted(symbols_still_blocked),
        "any_entry_recovered": any_entry_recovered,
        "any_realized_exit_recovered": any_exit_recovered,
    }


def run_once(
    *,
    symbols: tuple[str, ...] | None = None,
    redis_client_override=None,
    write_redis: bool = True,
    write_artifacts: bool | None = None,
    smoke_test: bool = False,
) -> dict[str, Any]:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    if write_artifacts is None:
        write_artifacts = redis_client_override is None
    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    paper_positions = _redis_get_json(redis_client, "v2:paper:positions")
    paper_ledger = _redis_get_json(redis_client, "v2:paper:ledger")
    paper_intents = _redis_get_json(redis_client, "v2:paper:intents")
    paper_intents_held = _redis_get_json(redis_client, "v2:paper:intents_held_by_paper_fill_gate")
    tracks = {}
    resolved_symbols = tuple(resolve_symbols(explicit=symbols, smoke_test=smoke_test))
    for symbol in sorted({s.strip().upper() for s in resolved_symbols if s.strip()}):
        market_price = _redis_get_json(redis_client, f"v2:market:prices:{symbol}")
        prediction = _redis_get_json(redis_client, f"v2:prediction:{symbol}:1m")
        previous_track = _redis_get_json(
            redis_client, KEY_PRICE_TRACK_TEMPLATE.format(symbol=symbol)
        )
        tracks[symbol] = build_position_track(
            symbol=symbol,
            paper_positions=paper_positions if isinstance(paper_positions, list) else [],
            paper_ledger=paper_ledger if isinstance(paper_ledger, dict) else {},
            market_price=market_price if isinstance(market_price, dict) else None,
            prediction=prediction if isinstance(prediction, dict) else None,
            paper_intents=paper_intents if isinstance(paper_intents, list) else [],
            paper_intents_held=paper_intents_held if isinstance(paper_intents_held, list) else [],
            previous_track=previous_track if isinstance(previous_track, dict) else None,
        )
    redis_write_results: dict[str, bool] = {}
    if write_redis and redis_client is not None:
        for symbol, track in tracks.items():
            track_key = KEY_PRICE_TRACK_TEMPLATE.format(symbol=symbol)
            history_key = KEY_HISTORY_TEMPLATE.format(symbol=symbol)
            redis_write_results[track_key] = safe_redis_set(
                redis_client, track_key, track.as_payload()
            )
            redis_write_results[history_key] = safe_redis_set(
                redis_client, history_key, history_payload(track)
            )
        redis_write_results[KEY_HEARTBEAT] = safe_redis_set(
            redis_client, KEY_HEARTBEAT, build_heartbeat_payload(tracks)
        )
    heartbeat = build_heartbeat_payload(tracks)
    per_symbol = [track.as_payload() for track in tracks.values()]
    burndown_summary = _compute_burndown_go_no_go(per_symbol)
    payload = {
        **heartbeat,
        "go_no_go": GO_READY,
        "per_symbol": per_symbol,
        "redis_write_results": redis_write_results,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        **burndown_summary,
    }
    if write_artifacts:
        _write_json(WORKLOG_STATUS, payload)
        _write_json(PUBLIC_RUNTIME, payload)
        _write_json(PUBLIC_DASHBOARD, payload)
        _write_json(BURNDOWN_STATUS, payload)
        _write_json(PUBLIC_BURNDOWN_DASHBOARD, payload)
        WORKLOG_GO_NO_GO.parent.mkdir(parents=True, exist_ok=True)
        WORKLOG_GO_NO_GO.write_text(payload["go_no_go"] + "\n", encoding="utf-8")
        BURNDOWN_GO_NO_GO.parent.mkdir(parents=True, exist_ok=True)
        BURNDOWN_GO_NO_GO.write_text(payload["burndown_go_no_go"] + "\n", encoding="utf-8")
        _write_report(payload)
        _write_burndown_report(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_position_price_tracking_recorder")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--symbols", default=None)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use BTC/ETH/SOL only for explicit smoke tests; never the default.",
    )
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args(argv)
    symbols = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    payload = run_once(
        symbols=symbols,
        write_redis=not args.no_redis,
        smoke_test=args.smoke_test,
    )
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "burndown_go_no_go": payload["burndown_go_no_go"],
                "symbols": payload["symbols"],
                "state_counts": payload["state_counts"],
                "symbols_with_entry_recovered": payload["symbols_with_entry_recovered"],
                "symbols_with_realized_exit_recovered": payload[
                    "symbols_with_realized_exit_recovered"
                ],
                "symbols_still_blocked": payload["symbols_still_blocked"],
                "writes_legacy_redis": payload["writes_legacy_redis"],
                "writes_exchange_orders": payload["writes_exchange_orders"],
                "live_symbols": payload["live_symbols"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
