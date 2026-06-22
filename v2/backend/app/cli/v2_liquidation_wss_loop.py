"""V2 per-symbol liquidation WSS client CLI (paper/shadow only).

Connects to the public Binance Futures liquidation stream (no
credentials) and publishes per-symbol liquidation observations to
``v2:market:liquidations:*`` only.

Requires the operator opt-in env var ``V2_LIQUIDATION_WSS_OPT_IN=true``.
Without it the CLI exits with a `_BLOCKED` GO/NO-GO and does NOT open a
network connection.

NEVER places, cancels, or modifies any order. NEVER touches legacy.
NEVER writes non-v2 Redis keys. NEVER imports torch. NEVER deserializes
pickle.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.native_ingestors.liquidations_wss import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_HEARTBEAT_TTL_SECONDS,
    DEFAULT_WSS_URL,
    OPT_IN_ENV_VAR,
    RetentionRing,
    compute_backoff_seconds,
    opt_in_enabled,
    run_wss_session,
    write_heartbeat,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json"
)
PUBLIC_DASHBOARD_SECONDARY = Path(
    "v2/frontend/public/v2_liquidation_wss_client/latest/operator_dashboard_payload.json"
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _write_status(payload: dict, worklog: Path, publics: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text(body, encoding="utf-8")
    for p in publics:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def _build_blocked_status_payload(
    *,
    symbols: tuple[str, ...],
    blocked_reason: str | None,
) -> dict:
    return {
        "schema_version": "v2_liquidation_wss_client_status_v2",
        "generated_utc": _utc_iso(),
        "generated_at": _utc_iso(),
        "heartbeat_at": _utc_iso(),
        "go_no_go": "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_BLOCKED",
        "blocked_reason": blocked_reason
        or f"Operator opt-in env var {OPT_IN_ENV_VAR}!=true; client did not connect.",
        "process_mode": "persistent_daemon",
        "service_active": False,
        "opt_in_enabled": False,
        "symbols": list(symbols),
        "url": DEFAULT_WSS_URL,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthetic_liquidation_events": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _build_daemon_status_payload(
    *,
    symbols: tuple[str, ...],
    live_state: dict,
) -> dict:
    """Build a daemon-fresh status payload from live_state.

    live_state is mutated by the WSS reconnect loop and read by the
    heartbeat writer task. The shape captures session counters,
    reconnect counts, and the last event timestamp so consumers can
    distinguish daemon-fresh status from a stale-at-session-end status.
    """
    now = _utc_iso()
    session_count = int(live_state.get("sessions", 0) or 0)
    def total_counter(name: str, current_name: str | None = None) -> int:
        if current_name is None:
            current_name = f"current_session_{name}"
        return int(live_state.get(name, 0) or 0) + int(
            live_state.get(current_name, 0) or 0
        )

    return {
        "schema_version": "v2_liquidation_wss_client_status_v2",
        "generated_utc": now,
        "generated_at": now,
        "heartbeat_at": now,
        "go_no_go": "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY",
        "process_mode": "persistent_daemon",
        "service_active": True,
        "opt_in_enabled": True,
        "url": DEFAULT_WSS_URL,
        "symbols": list(symbols),
        "session_count": session_count,
        "sessions": session_count,
        "stream_connected": bool(live_state.get("stream_connected", False)),
        "current_session_started_utc": live_state.get("current_session_started_utc"),
        "last_frame_utc": live_state.get("last_frame_utc"),
        "reconnect_count": int(live_state.get("reconnect_count", 0) or 0),
        "events_received": total_counter("events_received"),
        "events_parsed": total_counter("events_parsed"),
        "events_filtered_by_symbol": total_counter(
            "events_filtered_by_symbol",
            "current_session_events_filtered_by_symbol",
        ),
        "events_written": total_counter("events_written"),
        "parse_errors": total_counter("parse_errors", "current_session_parse_errors"),
        "redis_write_failures": total_counter(
            "redis_write_failures",
            "current_session_redis_write_failures",
        ),
        "current_session_events_received": int(
            live_state.get("current_session_events_received", 0) or 0
        ),
        "current_session_events_parsed": int(
            live_state.get("current_session_events_parsed", 0) or 0
        ),
        "current_session_events_filtered_by_symbol": int(
            live_state.get("current_session_events_filtered_by_symbol", 0) or 0
        ),
        "current_session_events_written": int(
            live_state.get("current_session_events_written", 0) or 0
        ),
        "last_event_utc": live_state.get("last_event_utc"),
        "last_error_type": live_state.get("last_error_type"),
        "last_error_utc": live_state.get("last_error_utc"),
        "last_session_stats": dict(live_state),
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthetic_liquidation_events": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _refresh_freshness(
    *,
    symbols: tuple[str, ...],
    live_state: dict,
    redis_client,
    worklog_path: Path,
    public_paths: tuple[Path, ...],
    heartbeat_ttl_seconds: int,
) -> dict:
    """Write the heartbeat + refresh the status JSON payloads once.

    Safe to call from sync or async contexts; never raises. Returns the
    payload that was written so callers can log it.
    """
    payload = _build_daemon_status_payload(symbols=symbols, live_state=live_state)
    try:
        _write_status(payload, worklog_path, public_paths)
    except Exception:
        pass
    if redis_client is not None:
        try:
            write_heartbeat(
                redis_client, payload, ttl_seconds=heartbeat_ttl_seconds
            )
        except Exception:
            pass
    return payload


async def _heartbeat_writer(
    *,
    symbols: tuple[str, ...],
    live_state: dict,
    redis_client,
    worklog_path: Path,
    public_paths: tuple[Path, ...],
    interval_seconds: float,
    heartbeat_ttl_seconds: int,
) -> None:
    """Background coroutine. Writes heartbeat + status files every
    interval_seconds. Survives transient redis/filesystem errors and
    exits cleanly when cancelled.
    """
    while True:
        if redis_client is None:
            redis_client = _connect_redis()
        _refresh_freshness(
            symbols=symbols,
            live_state=live_state,
            redis_client=redis_client,
            worklog_path=worklog_path,
            public_paths=public_paths,
            heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        )
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return


async def _run_with_reconnect(
    *,
    symbols: tuple[str, ...],
    max_seconds_per_session: float,
    max_events_per_session: int,
    total_seconds: float,
    redis_client,
    live_state: dict | None = None,
) -> dict:
    rings = {s.upper(): RetentionRing() for s in symbols}
    overall_start = time.monotonic()
    attempts = 0
    sessions = 0
    if live_state is None:
        live_state = {}
    for k in (
        "events_received",
        "events_parsed",
        "events_filtered_by_symbol",
        "events_written",
        "parse_errors",
        "redis_write_failures",
        "reconnect_count",
    ):
        live_state.setdefault(k, 0)
    live_state.setdefault("last_event_utc", None)
    live_state.setdefault("last_error_type", None)
    live_state.setdefault("last_error_utc", None)
    live_state.setdefault("sessions", 0)
    while time.monotonic() - overall_start < total_seconds:
        if redis_client is None:
            redis_client = _connect_redis()
        attempts += 1
        try:
            session_stats = await run_wss_session(
                url=DEFAULT_WSS_URL,
                redis_client=redis_client,
                symbols=symbols,
                max_seconds=max_seconds_per_session,
                max_events=max_events_per_session,
                rings=rings,
                stats_sink=live_state,
            )
            sessions += 1
            attempts = 0  # reset backoff on a successful session
            for k in (
                "events_received",
                "events_parsed",
                "events_filtered_by_symbol",
                "events_written",
                "parse_errors",
                "redis_write_failures",
            ):
                live_state[k] += getattr(session_stats, k)
            if session_stats.last_event_utc:
                live_state["last_event_utc"] = session_stats.last_event_utc
            live_state["last_error_type"] = None
            live_state["last_error_utc"] = None
            live_state["stream_connected"] = False
            for k in (
                "current_session_events_received",
                "current_session_events_parsed",
                "current_session_events_filtered_by_symbol",
                "current_session_events_written",
                "current_session_parse_errors",
                "current_session_redis_write_failures",
            ):
                live_state[k] = 0
            live_state["sessions"] = sessions
        except Exception as exc:
            live_state["stream_connected"] = False
            live_state["reconnect_count"] += 1
            live_state["last_error_type"] = type(exc).__name__
            live_state["last_error_utc"] = _utc_iso()
            delay = compute_backoff_seconds(attempts)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
    live_state["sessions"] = sessions
    return dict(live_state)


async def _run_daemon(
    *,
    symbols: tuple[str, ...],
    max_seconds_per_session: float,
    max_events_per_session: int,
    total_seconds: float,
    redis_client,
    worklog_path: Path,
    public_paths: tuple[Path, ...],
    heartbeat_interval_seconds: float,
    heartbeat_ttl_seconds: int,
) -> dict:
    """Run the WSS reconnect loop and the heartbeat writer concurrently."""
    live_state: dict = {}
    _refresh_freshness(
        symbols=symbols,
        live_state=live_state,
        redis_client=redis_client,
        worklog_path=worklog_path,
        public_paths=public_paths,
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_writer(
            symbols=symbols,
            live_state=live_state,
            redis_client=redis_client,
            worklog_path=worklog_path,
            public_paths=public_paths,
            interval_seconds=heartbeat_interval_seconds,
            heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        )
    )
    try:
        stats = await _run_with_reconnect(
            symbols=symbols,
            max_seconds_per_session=max_seconds_per_session,
            max_events_per_session=max_events_per_session,
            total_seconds=total_seconds,
            redis_client=redis_client,
            live_state=live_state,
        )
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass
        _refresh_freshness(
            symbols=symbols,
            live_state=live_state,
            redis_client=redis_client,
            worklog_path=worklog_path,
            public_paths=public_paths,
            heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_liquidation_wss_loop")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Explicit comma-separated symbols. Omit for dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set; never the default.",
    )
    parser.add_argument(
        "--total-seconds",
        type=float,
        default=20.0,
        help="Total wall-clock budget for the run (default 20s).",
    )
    parser.add_argument(
        "--max-seconds-per-session",
        type=float,
        default=15.0,
        help="Max seconds per WSS session before the loop yields.",
    )
    parser.add_argument(
        "--max-events-per-session",
        type=int,
        default=100,
        help="Max events accepted per session (caps memory).",
    )
    parser.add_argument(
        "--heartbeat-interval-seconds",
        type=float,
        default=float(DEFAULT_HEARTBEAT_INTERVAL_SECONDS),
        help=(
            "Interval (seconds) between heartbeat + status writes during a "
            "long quiet session. Must be strictly less than --heartbeat-ttl-seconds."
        ),
    )
    parser.add_argument(
        "--heartbeat-ttl-seconds",
        type=int,
        default=int(DEFAULT_HEARTBEAT_TTL_SECONDS),
        help=(
            "Redis TTL (seconds) for v2:market:liquidations:heartbeat. Must "
            "be strictly greater than --heartbeat-interval-seconds."
        ),
    )
    parser.add_argument(
        "--out-worklog", type=Path, default=WORKLOG_STATUS
    )
    parser.add_argument(
        "--out-public", type=Path, default=PUBLIC_DASHBOARD
    )
    parser.add_argument(
        "--out-public-secondary", type=Path, default=PUBLIC_DASHBOARD_SECONDARY
    )
    args = parser.parse_args(argv)
    symbols = tuple(
        resolve_symbols(
            explicit=args.symbols,
            smoke_test=args.smoke_test,
            include_baseline=True,
        )
    )
    if args.heartbeat_interval_seconds >= args.heartbeat_ttl_seconds:
        print(
            json.dumps(
                {
                    "go_no_go": "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_BLOCKED",
                    "blocked_reason": (
                        "heartbeat_interval_seconds must be strictly less than "
                        "heartbeat_ttl_seconds"
                    ),
                }
            )
        )
        return 2
    opted = opt_in_enabled()
    redis_client = _connect_redis() if opted else None
    if not opted:
        payload = _build_blocked_status_payload(
            symbols=symbols,
            blocked_reason=(
                f"Operator opt-in env var {OPT_IN_ENV_VAR}!=true; "
                "client did not connect."
            ),
        )
        _write_status(
            payload,
            args.out_worklog,
            (args.out_public, args.out_public_secondary),
        )
        print(json.dumps({"go_no_go": payload["go_no_go"]}))
        return 0
    stats = asyncio.run(
        _run_daemon(
            symbols=symbols,
            max_seconds_per_session=args.max_seconds_per_session,
            max_events_per_session=args.max_events_per_session,
            total_seconds=args.total_seconds,
            redis_client=redis_client,
            worklog_path=args.out_worklog,
            public_paths=(args.out_public, args.out_public_secondary),
            heartbeat_interval_seconds=args.heartbeat_interval_seconds,
            heartbeat_ttl_seconds=args.heartbeat_ttl_seconds,
        )
    )
    print(
        json.dumps(
            {
                "go_no_go": "V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY",
                "events_written": stats.get("events_written"),
                "events_received": stats.get("events_received"),
                "sessions": stats.get("sessions"),
                "reconnect_count": stats.get("reconnect_count"),
                "last_event_utc": stats.get("last_event_utc"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
