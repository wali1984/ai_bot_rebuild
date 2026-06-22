"""V2 paper position-history persistent tracker CLI.

Two modes:

- ``--once``: read V2 paper inputs once, write per-symbol
  ``v2:paper:position_price_track:{symbol}`` and
  ``v2:paper:position_history:{symbol}``, refresh
  ``v2:paper:position_history:heartbeat``, write status mirrors,
  return.

- ``--loop``: persistent daemon. Repeats ``--once`` work on a
  configurable interval, capped by ``--total-seconds`` and
  ``--max-seconds-per-session``. Refreshes the heartbeat every
  cycle so the governor can detect a dead daemon.

The CLI NEVER places, cancels, or modifies an exchange order; NEVER
enables live trading; NEVER writes to a non-V2 Redis namespace;
NEVER fabricates an accepted position; NEVER counts shadow or held
intents as accepted; NEVER allows the full-observation builder to
consume this payload until Codex passes the persistent-tracker
review.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.position_history_persistent_tracker import (
    NO_OPEN_POSITION_STATE,
    build_and_publish,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    resolve_symbols,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GO_READY = "V2_POSITION_HISTORY_PERSISTENT_TRACKER_PAPER_SHADOW_READY"
GO_BLOCKED = "V2_POSITION_HISTORY_PERSISTENT_TRACKER_PAPER_SHADOW_BLOCKED"

DEFAULT_SYMBOLS = tuple(BASELINE_25_SYMBOLS)
DEFAULT_TOTAL_SECONDS = 86_400  # 24 hours
DEFAULT_MAX_SECONDS_PER_SESSION = 600
DEFAULT_CYCLE_INTERVAL_SECONDS = 60
DEFAULT_HEARTBEAT_TTL_SECONDS = 300
DEFAULT_TRACK_TTL_SECONDS = 900
MIN_HEARTBEAT_TTL_OVER_INTERVAL_SECONDS = 30

PROCESS_MODE_ONE_SHOT = "one_shot"
PROCESS_MODE_PERSISTENT_DAEMON = "persistent_daemon"

WORKLOG_DIR = Path(
    "claude_worklog/final_readiness/v2_position_history_persistent_tracker/latest"
)
WORKLOG_STATUS = WORKLOG_DIR / "position_history_persistent_tracker_status.json"
WORKLOG_GO_NO_GO = WORKLOG_DIR / "GO_NO_GO.md"

PUBLIC_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_position_history_persistent_tracker/latest/"
    "position_history_persistent_tracker_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_position_history_persistent_tracker/latest/"
    "operator_dashboard_payload.json"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect_redis():  # pragma: no cover — exercised at runtime, mocked in tests
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_go_no_go(token: str) -> None:
    WORKLOG_GO_NO_GO.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_GO_NO_GO.write_text(token + "\n", encoding="utf-8")


def _packet_status_payload(
    heartbeat: dict[str, Any], *, process_mode: str, cycle_count: int
) -> dict[str, Any]:
    """Build the packet-status payload (worklog + dashboard mirrors).

    Adds the operator-facing fields the monitor center needs (safety
    invariants, hard "blocked" defaults, packet name, opt-in flag).
    """
    open_symbols = list(heartbeat.get("open_position_symbols") or [])
    no_open_symbols = list(heartbeat.get("no_open_position_symbols") or [])
    payload = dict(heartbeat)
    payload.update(
        {
            "schema_version": "v2_position_history_persistent_tracker_status_v1",
            "go_no_go": GO_READY,
            "packet": "v2_position_history_persistent_tracker",
            "process_mode": process_mode,
            "cycle_count": cycle_count,
            "open_position_symbol_count": len(open_symbols),
            "no_open_position_symbol_count": len(no_open_symbols),
            "no_open_position_state_token": NO_OPEN_POSITION_STATE,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "places_real_order": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "raw_credential_in_payload": "NEVER",
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "live_enabled": False,
            "full_observation_consumption_allowed": False,
            "full_observation_consumption_unblocked_after": (
                "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS"
            ),
            "may_authorize_live": False,
            "may_authorize_canary": False,
            "may_override_strict_paper_fill_gate": False,
            "may_place_orders": False,
            "synthesizes_accepted_positions": False,
            "counts_shadow_intents_as_accepted": False,
            "counts_held_intents_as_accepted": False,
            "fabricates_excursion_metrics": False,
            "allowed_redis_writes": [
                "v2:paper:position_history:{symbol}",
                "v2:paper:position_price_track:{symbol}",
                "v2:paper:position_history:heartbeat",
            ],
        }
    )
    return payload


def _write_status_mirrors(payload: dict[str, Any]) -> None:
    _write_json(WORKLOG_STATUS, payload)
    _write_json(PUBLIC_RUNTIME, payload)
    _write_json(PUBLIC_DASHBOARD, payload)


def run_once(
    *,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    redis_client: Any = None,
    process_mode: str = PROCESS_MODE_ONE_SHOT,
    cycle_count: int = 1,
    ttl_seconds: int = DEFAULT_TRACK_TTL_SECONDS,
    write_artifacts: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    if redis_client is None:
        redis_client = _connect_redis()
    heartbeat = build_and_publish(
        redis_client=redis_client,
        symbols=symbols,
        process_mode=process_mode,
        cycle_count=cycle_count,
        now=now,
        ttl_seconds=ttl_seconds,
    )
    payload = _packet_status_payload(
        heartbeat, process_mode=process_mode, cycle_count=cycle_count
    )
    if write_artifacts:
        _write_status_mirrors(payload)
        _write_go_no_go(payload["go_no_go"])
    return payload


def run_loop(
    *,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    redis_client: Any = None,
    total_seconds: int = DEFAULT_TOTAL_SECONDS,
    max_seconds_per_session: int = DEFAULT_MAX_SECONDS_PER_SESSION,
    cycle_interval_seconds: int = DEFAULT_CYCLE_INTERVAL_SECONDS,
    heartbeat_ttl_seconds: int = DEFAULT_HEARTBEAT_TTL_SECONDS,
    track_ttl_seconds: int = DEFAULT_TRACK_TTL_SECONDS,
    sleep: Any | None = None,
    write_artifacts: bool = True,
    now_factory: Any | None = None,
) -> dict[str, Any]:
    """Persistent-daemon loop.

    The loop terminates when either ``total_seconds`` is exceeded or
    ``max_seconds_per_session`` is reached. Each cycle calls
    :func:`run_once` (which calls into the build/publish helper that
    refreshes the heartbeat key). The heartbeat TTL must exceed the
    cycle interval so a missed cycle leaves a positive TTL window
    long enough for the governor's freshness check to observe the
    refresh, otherwise the daemon refuses to start.
    """
    if heartbeat_ttl_seconds <= cycle_interval_seconds + MIN_HEARTBEAT_TTL_OVER_INTERVAL_SECONDS - 1:
        raise ValueError(
            f"heartbeat_ttl_seconds={heartbeat_ttl_seconds} must exceed "
            f"cycle_interval_seconds={cycle_interval_seconds} by at least "
            f"{MIN_HEARTBEAT_TTL_OVER_INTERVAL_SECONDS} seconds; otherwise "
            "the heartbeat can expire between cycles"
        )
    if redis_client is None:
        redis_client = _connect_redis()
    sleep_fn = sleep or time.sleep
    now_fn = now_factory or _utc_now
    session_start = time.monotonic()
    cycle_count = 0
    last_payload: dict[str, Any] = {}
    while True:
        cycle_count += 1
        last_payload = run_once(
            symbols=symbols,
            redis_client=redis_client,
            process_mode=PROCESS_MODE_PERSISTENT_DAEMON,
            cycle_count=cycle_count,
            ttl_seconds=max(track_ttl_seconds, heartbeat_ttl_seconds),
            write_artifacts=write_artifacts,
            now=now_fn(),
        )
        elapsed = time.monotonic() - session_start
        if elapsed >= total_seconds or elapsed >= max_seconds_per_session:
            break
        # Sleep for the cycle interval, but not past the session cap.
        remaining = min(
            total_seconds - elapsed, max_seconds_per_session - elapsed
        )
        sleep_for = min(cycle_interval_seconds, max(0, remaining))
        if sleep_for <= 0:
            break
        sleep_fn(sleep_for)
    return last_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_position_history_persistent_tracker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
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
        "--total-seconds", type=int, default=DEFAULT_TOTAL_SECONDS
    )
    parser.add_argument(
        "--max-seconds-per-session",
        type=int,
        default=DEFAULT_MAX_SECONDS_PER_SESSION,
    )
    parser.add_argument(
        "--cycle-interval-seconds",
        type=int,
        default=DEFAULT_CYCLE_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--heartbeat-ttl-seconds",
        type=int,
        default=DEFAULT_HEARTBEAT_TTL_SECONDS,
    )
    parser.add_argument(
        "--track-ttl-seconds",
        type=int,
        default=DEFAULT_TRACK_TTL_SECONDS,
    )
    args = parser.parse_args(argv)

    symbols = tuple(
        resolve_symbols(
            explicit=args.symbols,
            smoke_test=args.smoke_test,
            include_baseline=True,
        )
    )

    # Refuse to enable live or canary regardless of caller intent.
    if os.environ.get("V2_LIVE_GATE_OVERRIDE") not in (None, "", "blocked_human_only"):
        raise SystemExit(
            "V2_LIVE_GATE_OVERRIDE is set to a non-blocked value; refusing to run. "
            "live_gate must remain blocked_human_only."
        )

    if args.loop:
        payload = run_loop(
            symbols=symbols,
            total_seconds=int(args.total_seconds),
            max_seconds_per_session=int(args.max_seconds_per_session),
            cycle_interval_seconds=int(args.cycle_interval_seconds),
            heartbeat_ttl_seconds=int(args.heartbeat_ttl_seconds),
            track_ttl_seconds=int(args.track_ttl_seconds),
        )
    else:
        payload = run_once(symbols=symbols, ttl_seconds=int(args.track_ttl_seconds))

    print(
        json.dumps(
            {
                "go_no_go": payload.get("go_no_go"),
                "process_mode": payload.get("process_mode"),
                "cycle_count": payload.get("cycle_count"),
                "open_position_symbol_count": payload.get(
                    "open_position_symbol_count"
                ),
                "no_open_position_symbol_count": payload.get(
                    "no_open_position_symbol_count"
                ),
                "live_gate": payload.get("live_gate"),
                "live_symbols": payload.get("live_symbols"),
                "writes_legacy_redis": payload.get("writes_legacy_redis"),
                "writes_exchange_orders": payload.get("writes_exchange_orders"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
