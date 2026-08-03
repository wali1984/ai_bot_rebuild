"""V2 Top-10 Binance market dashboard feed CLI (paper/shadow only).

Bounded one-shot. Calls the two public Binance ticker endpoints once
each (spot 12h rolling ticker, futures 24h ticker), builds the six
dashboards from the result, writes them under
v2:dashboards:binance_top10:*, and emits a heartbeat key.

NEVER places, cancels, or modifies any exchange entry. NEVER changes
leverage or margin. NEVER calls authenticated endpoints. NEVER
exposes any credential (no credential is required for these endpoints
in the first place). NEVER writes old Redis keys. NEVER synthesizes
ticker rows. NEVER imports torch. NEVER deserializes pickle.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.alternative_data.binance_top10_dashboards import (
    DEFAULT_QUOTE_FILTER,
    DEFAULT_TOP_N,
    FUTURES_24H_TICKER_URL,
    KEY_HEARTBEAT,
    SPOT_ROLLING_TICKER_URL,
    build_dashboards,
    build_heartbeat_payload,
    fetch_ticker,
    publish_dashboards,
    write_heartbeat_payload,
)

GO_READY = "V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_READY"
GO_BLOCKED = "V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_BLOCKED"

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_top10_binance_dashboard_feed/latest/v2_top10_binance_dashboard_feed_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/operator_runtime/v2_top10_binance_dashboard_feed/latest/v2_top10_binance_dashboard_feed_status.json"
)
PUBLIC_DASHBOARD_SECONDARY = Path(
    "v2/frontend/public/v2_top10_binance_dashboard_feed/latest/operator_dashboard_payload.json"
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


def _write_status_files(payload: dict, worklog: Path, publics: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text(body, encoding="utf-8")
    for p in publics:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def run_once(
    *,
    redis_client,
    http_get=None,
    quote_filter: str | None = DEFAULT_QUOTE_FILTER,
    top_n: int = DEFAULT_TOP_N,
    timeout: float = 10.0,
) -> dict:
    spot_status, spot_rows = fetch_ticker(
        SPOT_ROLLING_TICKER_URL, http_get=http_get, timeout=timeout
    )
    futures_status, futures_rows = fetch_ticker(
        FUTURES_24H_TICKER_URL, http_get=http_get, timeout=timeout
    )
    dashboards = build_dashboards(
        spot_rows=spot_rows,
        futures_rows=futures_rows,
        spot_source_status=spot_status,
        futures_source_status=futures_status,
        quote_filter=quote_filter,
        top_n=top_n,
    )
    publish_result = publish_dashboards(redis_client, dashboards)
    heartbeat = build_heartbeat_payload(
        spot_source_status=spot_status,
        futures_source_status=futures_status,
        dashboards=dashboards,
    )
    write_heartbeat_payload(redis_client, heartbeat)
    return {
        "spot_source_status": spot_status,
        "futures_source_status": futures_status,
        "dashboards": dashboards,
        "publish_result": publish_result,
        "heartbeat": heartbeat,
    }


def _summary_status_payload(
    result: dict,
    *,
    quote_filter: str | None,
    top_n: int,
) -> dict:
    dashboards = result["dashboards"]
    summarized = {
        dash_id: {
            "title": payload["title"],
            "venue": payload["venue"],
            "metric": payload["metric"],
            "window_size_requested": payload["window_size_requested"],
            "window_size_actual": payload["window_size_actual"],
            "source_endpoint": payload["source_endpoint"],
            "source_status": payload["source_status"],
            "rank_count": payload["rank_count"],
            "top_symbol": (payload["rows"][0]["symbol"] if payload["rows"] else None),
            "redis_key": payload["redis_key"],
        }
        for dash_id, payload in dashboards.items()
    }
    return {
        "schema_version": "v2_top10_binance_dashboard_feed_status_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": GO_READY,
        "spot_source_status": result["spot_source_status"],
        "futures_source_status": result["futures_source_status"],
        "quote_filter": quote_filter,
        "top_n": int(top_n),
        "dashboards": summarized,
        "heartbeat_redis_key": KEY_HEARTBEAT,
        "publish_result": result["publish_result"],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthetic_market_data": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "credential_in_payload": "NEVER",
        "auth_required_for_source_endpoints": False,
        "gate": "blocked_human_only",
        "symbols_real": [],
        "approves_real": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_top10_binance_dashboard_feed")
    parser.add_argument(
        "--quote-filter",
        default=DEFAULT_QUOTE_FILTER,
        help=(
            "Quote-currency filter applied to ticker rows before ranking. "
            "Default USDT. Pass an empty string to disable filtering."
        ),
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of ranked rows per dashboard (default 10).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="Per-request HTTP timeout in seconds.",
    )
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_DASHBOARD)
    parser.add_argument(
        "--out-public-secondary", type=Path, default=PUBLIC_DASHBOARD_SECONDARY
    )
    args = parser.parse_args(argv)
    quote_filter = args.quote_filter or None
    redis_client = _connect_redis()
    result = run_once(
        redis_client=redis_client,
        quote_filter=quote_filter,
        top_n=int(args.top_n),
        timeout=float(args.timeout_seconds),
    )
    status = _summary_status_payload(
        result, quote_filter=quote_filter, top_n=int(args.top_n)
    )
    _write_status_files(
        status, args.out_worklog, (args.out_public, args.out_public_secondary)
    )
    summary = {
        "go_no_go": status["go_no_go"],
        "spot_source_status": status["spot_source_status"],
        "futures_source_status": status["futures_source_status"],
        "dashboards_published": list(result["dashboards"].keys()),
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "credential_in_payload": "NEVER",
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
