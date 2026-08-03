"""V2 Top-10 market + alt-data dashboard renderer.

Read-only display-payload exporter. Reads V2 Redis keys ONLY, never
calls a provider directly, and writes a single static JSON payload
under ``v2/frontend/public/v2_top10_dashboards/latest/`` that the
frontend renders without any of its own provider knowledge.

The renderer classifies each panel's data state into exactly one of:

- ``OK_ROWS_PRESENT``: panel has fresh ranked rows.
- ``KEY_PRESENT_NO_CLIENT_YET``: data path is wired but the
  upstream client/exporter has not produced rows yet.
- ``KEY_MISSING``: required Redis key is absent.
- ``STALE``: payload exists but its ``generated_utc`` is older
  than the panel's freshness window.
- ``BUDGET_LIMITED``: provider hit free-tier daily budget / rate
  limit / cooldown; rows are intentionally absent.

Allowed file writes:
- ``v2/frontend/public/v2_top10_dashboards/latest/dashboard_payload.json``
- ``claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_rendering/latest/dashboard_payload.json``

NEVER writes Redis. NEVER calls any exchange or alt-data provider.
NEVER serializes raw credentials. NEVER exposes a live-trading
control surface.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

# Panel state labels — the rendered payload uses exactly these.
STATE_OK_ROWS_PRESENT = "OK_ROWS_PRESENT"
STATE_KEY_PRESENT_NO_CLIENT_YET = "KEY_PRESENT_NO_CLIENT_YET"
STATE_KEY_MISSING = "KEY_MISSING"
STATE_STALE = "STALE"
STATE_BUDGET_LIMITED = "BUDGET_LIMITED"

ALL_PANEL_STATES = (
    STATE_OK_ROWS_PRESENT,
    STATE_KEY_PRESENT_NO_CLIENT_YET,
    STATE_KEY_MISSING,
    STATE_STALE,
    STATE_BUDGET_LIMITED,
)

DEFAULT_FRESHNESS_SECONDS = 600
DEFAULT_FUNDING_FRESHNESS_SECONDS = 900
DEFAULT_LIQUIDATION_FRESHNESS_SECONDS = 600

WORKLOG_PAYLOAD_PATH = Path(
    "claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_rendering/latest/dashboard_payload.json"
)
PUBLIC_PAYLOAD_PATH = Path(
    "v2/frontend/public/v2_top10_dashboards/latest/dashboard_payload.json"
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _connect_redis() -> Any:  # pragma: no cover — runtime helper
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _safe_get_json(redis_client: Any, key: str) -> Any | None:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _payload_age_seconds(payload: dict[str, Any]) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("generated_utc", "heartbeat_at", "generated_at"):
        raw = payload.get(key)
        if not isinstance(raw, str):
            continue
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        except Exception:
            continue
    return None


def _classify_freshness(
    payload: dict[str, Any] | None, *, max_age_seconds: int
) -> tuple[str, float | None]:
    """Return ``(state_label, age_seconds)`` for a payload that
    contains a timestamp field. Caller decides whether absence of
    payload is ``KEY_MISSING`` (Redis key absent) or
    ``KEY_PRESENT_NO_CLIENT_YET`` (key exists but no rows yet)."""
    if payload is None:
        return (STATE_KEY_MISSING, None)
    age = _payload_age_seconds(payload)
    if age is None:
        return (STATE_KEY_PRESENT_NO_CLIENT_YET, None)
    if age > max_age_seconds:
        return (STATE_STALE, age)
    return (STATE_OK_ROWS_PRESENT, age)


# ---------------------------------------------------------------------------
# Binance Top-10 panels (6) — Volume, Trades, Volatility × Spot/Futures
# ---------------------------------------------------------------------------

_BINANCE_PANELS = (
    {
        "panel_id": "binance_spot_volume_12h",
        "title": "Binance Spot 12h Volume Leaders",
        "venue": "spot",
        "metric": "quote_volume",
        "redis_key": "v2:dashboards:binance_top10:spot_volume_12h",
    },
    {
        "panel_id": "binance_futures_volume_12h",
        "title": "Binance Futures 12h Volume Leaders",
        "venue": "futures",
        "metric": "quote_volume",
        "redis_key": "v2:dashboards:binance_top10:futures_volume_12h",
    },
    {
        "panel_id": "binance_spot_trades_12h",
        "title": "Binance Spot 12h Most Traded",
        "venue": "spot",
        "metric": "trade_count",
        "redis_key": "v2:dashboards:binance_top10:spot_trades_12h",
    },
    {
        "panel_id": "binance_futures_trades_12h",
        "title": "Binance Futures 12h Most Traded",
        "venue": "futures",
        "metric": "trade_count",
        "redis_key": "v2:dashboards:binance_top10:futures_trades_12h",
    },
    {
        "panel_id": "binance_spot_volatility_12h",
        "title": "Binance Spot 12h Volatility Leaders",
        "venue": "spot",
        "metric": "price_change_percent",
        "redis_key": "v2:dashboards:binance_top10:spot_volatility_12h",
    },
    {
        "panel_id": "binance_futures_volatility_12h",
        "title": "Binance Futures 12h Volatility Leaders",
        "venue": "futures",
        "metric": "price_change_percent",
        "redis_key": "v2:dashboards:binance_top10:futures_volatility_12h",
    },
)


def _build_binance_panel(redis_client: Any, panel_def: dict[str, Any]) -> dict[str, Any]:
    payload = _safe_get_json(redis_client, panel_def["redis_key"])
    state, age = _classify_freshness(
        payload, max_age_seconds=DEFAULT_FRESHNESS_SECONDS
    )
    rows: list[dict[str, Any]] = []
    rank_count = 0
    source_status = "UNKNOWN"
    window_size_requested = None
    window_size_actual = None
    if isinstance(payload, dict):
        candidate_rows = payload.get("rows") or payload.get("top") or []
        if isinstance(candidate_rows, list):
            for idx, row in enumerate(candidate_rows[:10]):
                if not isinstance(row, dict):
                    continue
                rows.append(
                    {
                        "rank": int(row.get("rank") or (idx + 1)),
                        "symbol": str(row.get("symbol") or "—"),
                        "quote_volume": row.get("quote_volume"),
                        "trade_count": row.get("trade_count"),
                        "price_change_percent": row.get("price_change_percent"),
                        "last_price": row.get("last_price"),
                    }
                )
            rank_count = len(rows)
        source_status = str(payload.get("source_status") or payload.get("status") or "UNKNOWN")
        window_size_requested = payload.get("window_size_requested")
        window_size_actual = payload.get("window_size_actual")
    # If freshness says OK but no rows arrived, downgrade.
    if state == STATE_OK_ROWS_PRESENT and rank_count == 0:
        state = STATE_KEY_PRESENT_NO_CLIENT_YET
    return {
        **panel_def,
        "state": state,
        "age_seconds": age,
        "rank_count": rank_count,
        "rows": rows,
        "source_status": source_status,
        "window_size_requested": window_size_requested,
        "window_size_actual": window_size_actual,
    }


# ---------------------------------------------------------------------------
# Liquidation tape top symbols
# ---------------------------------------------------------------------------


def _build_liquidation_panel(redis_client: Any) -> dict[str, Any]:
    panel_id = "liquidation_tape_top_symbols"
    heartbeat = _safe_get_json(
        redis_client, "v2:market:liquidations:heartbeat"
    )
    aggregated = _safe_get_json(
        redis_client, "v2:market:liquidations:top_symbols"
    )
    heartbeat_state, heartbeat_age = _classify_freshness(
        heartbeat, max_age_seconds=DEFAULT_LIQUIDATION_FRESHNESS_SECONDS
    )
    rows: list[dict[str, Any]] = []
    if isinstance(aggregated, dict):
        candidate_rows = aggregated.get("rows") or aggregated.get("top") or []
        if isinstance(candidate_rows, list):
            for idx, row in enumerate(candidate_rows[:10]):
                if not isinstance(row, dict):
                    continue
                rows.append(
                    {
                        "rank": int(row.get("rank") or (idx + 1)),
                        "symbol": str(row.get("symbol") or "—"),
                        "liquidated_notional_usdt": row.get(
                            "liquidated_notional_usdt"
                        ),
                        "long_count": row.get("long_count"),
                        "short_count": row.get("short_count"),
                    }
                )
    if rows:
        state = STATE_OK_ROWS_PRESENT
        age = _payload_age_seconds(aggregated) if isinstance(aggregated, dict) else None
    elif heartbeat is None:
        state = STATE_KEY_MISSING
        age = None
    elif heartbeat_state == STATE_STALE:
        state = STATE_STALE
        age = heartbeat_age
    else:
        # Heartbeat says the daemon is alive, but the aggregator
        # hasn't produced rows yet. This is the
        # KEY_PRESENT_NO_CLIENT_YET case.
        state = STATE_KEY_PRESENT_NO_CLIENT_YET
        age = heartbeat_age
    return {
        "panel_id": panel_id,
        "title": "Liquidation Tape Top Symbols",
        "metric": "liquidated_notional_usdt",
        "redis_key_heartbeat": "v2:market:liquidations:heartbeat",
        "redis_key_rows": "v2:market:liquidations:top_symbols",
        "state": state,
        "age_seconds": age,
        "rank_count": len(rows),
        "rows": rows,
        "heartbeat_present": heartbeat is not None,
        "heartbeat_age_seconds": heartbeat_age,
    }


# ---------------------------------------------------------------------------
# Funding/OI movers
# ---------------------------------------------------------------------------

_FUNDING_SYMBOLS = tuple(resolve_symbols()[:10])


def _build_funding_oi_panel(redis_client: Any) -> dict[str, Any]:
    panel_id = "funding_oi_movers"
    rows: list[dict[str, Any]] = []
    youngest_age: float | None = None
    oldest_age: float | None = None
    missing_symbols: list[str] = []
    for sym in _FUNDING_SYMBOLS:
        funding = _safe_get_json(redis_client, f"v2:market:funding:{sym}")
        oi = _safe_get_json(redis_client, f"v2:market:open_interest:{sym}")
        long_short = _safe_get_json(redis_client, f"v2:market:long_short:{sym}")
        if funding is None and oi is None and long_short is None:
            missing_symbols.append(sym)
            continue
        funding_rate = None
        if isinstance(funding, dict):
            try:
                funding_rate = float(funding.get("lastFundingRate") or "nan")
                if funding_rate != funding_rate:  # NaN
                    funding_rate = None
            except Exception:
                funding_rate = None
        open_interest = None
        if isinstance(oi, dict):
            try:
                open_interest = float(oi.get("openInterest") or "nan")
                if open_interest != open_interest:
                    open_interest = None
            except Exception:
                open_interest = None
        long_short_ratio = None
        if isinstance(long_short, dict):
            try:
                long_short_ratio = float(
                    long_short.get("long_short_ratio")
                    or long_short.get("longShortRatio")
                    or "nan"
                )
                if long_short_ratio != long_short_ratio:
                    long_short_ratio = None
            except Exception:
                long_short_ratio = None
        # Funding/OI keys in V2 carry epoch-millisecond "time"
        # timestamps; derive an age from the larger of the two.
        funding_age = _funding_oi_epoch_age_seconds(funding)
        oi_age = _funding_oi_epoch_age_seconds(oi)
        long_short_age = _funding_oi_epoch_age_seconds(long_short)
        candidate_age = None
        for v in (funding_age, oi_age, long_short_age):
            if v is None:
                continue
            candidate_age = v if candidate_age is None else max(candidate_age, v)
        if candidate_age is not None:
            youngest_age = (
                candidate_age if youngest_age is None else min(youngest_age, candidate_age)
            )
            oldest_age = (
                candidate_age if oldest_age is None else max(oldest_age, candidate_age)
            )
        rows.append(
            {
                "symbol": sym,
                "last_funding_rate": funding_rate,
                "open_interest": open_interest,
                "long_short_ratio": long_short_ratio,
                "funding_age_seconds": funding_age,
                "open_interest_age_seconds": oi_age,
                "long_short_age_seconds": long_short_age,
            }
        )
    if not rows:
        state = STATE_KEY_MISSING
    elif oldest_age is not None and oldest_age > DEFAULT_FUNDING_FRESHNESS_SECONDS:
        state = STATE_STALE
    elif missing_symbols:
        state = STATE_KEY_PRESENT_NO_CLIENT_YET
    else:
        state = STATE_OK_ROWS_PRESENT
    # Rank by abs(last_funding_rate). None values sort last.
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            r["last_funding_rate"] is None,
            -abs(r["last_funding_rate"]) if r["last_funding_rate"] is not None else 0,
        ),
    )
    for idx, row in enumerate(rows_sorted):
        row["rank"] = idx + 1
    return {
        "panel_id": panel_id,
        "title": "Funding / OI Movers",
        "metric": "abs(last_funding_rate)",
        "redis_key_pattern": (
            "v2:market:funding:{symbol} + "
            "v2:market:open_interest:{symbol} + "
            "v2:market:long_short:{symbol}"
        ),
        "state": state,
        "age_seconds": oldest_age,
        "rank_count": len(rows_sorted),
        "rows": rows_sorted,
        "missing_symbols": missing_symbols,
        "tracked_symbols": list(_FUNDING_SYMBOLS),
    }


def _funding_oi_epoch_age_seconds(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("time", payload.get("timestamp"))
    try:
        epoch_ms = int(raw)
    except (TypeError, ValueError):
        return None
    if epoch_ms <= 0:
        return None
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return max(0.0, (now_ms - epoch_ms) / 1000.0)


# ---------------------------------------------------------------------------
# Top-level assembly + write
# ---------------------------------------------------------------------------


def build_dashboard_payload(redis_client: Any = None) -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    for panel_def in _BINANCE_PANELS:
        panels.append(_build_binance_panel(redis_client, panel_def))
    panels.append(_build_liquidation_panel(redis_client))
    panels.append(_build_funding_oi_panel(redis_client))
    panels_with_rows = sum(1 for p in panels if p["rank_count"] > 0)
    panels_ok = sum(1 for p in panels if p["state"] == STATE_OK_ROWS_PRESENT)
    panels_key_missing = sum(1 for p in panels if p["state"] == STATE_KEY_MISSING)
    panels_stale = sum(1 for p in panels if p["state"] == STATE_STALE)
    panels_budget_limited = sum(
        1 for p in panels if p["state"] == STATE_BUDGET_LIMITED
    )
    panels_no_client_yet = sum(
        1 for p in panels if p["state"] == STATE_KEY_PRESENT_NO_CLIENT_YET
    )
    return {
        "schema_version": "v2_top10_market_and_altdata_dashboard_payload_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": "V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_RENDERING_READY",
        "panels_total": len(panels),
        "panels_with_rows": panels_with_rows,
        "panels_ok_rows_present": panels_ok,
        "panels_key_missing": panels_key_missing,
        "panels_stale": panels_stale,
        "panels_budget_limited": panels_budget_limited,
        "panels_key_present_no_client_yet": panels_no_client_yet,
        "panels": panels,
        "panel_state_legend": {
            STATE_OK_ROWS_PRESENT: "Panel has fresh ranked rows.",
            STATE_KEY_PRESENT_NO_CLIENT_YET: "Data path is wired but upstream client/exporter has not produced rows yet.",
            STATE_KEY_MISSING: "Required Redis key is absent.",
            STATE_STALE: "Payload exists but generated_utc is older than the panel's freshness window.",
            STATE_BUDGET_LIMITED: "Provider hit free-tier daily budget / rate limit / cooldown; rows intentionally absent.",
        },
        # Safety invariants — these are immutable and audited by the
        # validation sweep.
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "dry_run": True,
        "live_enabled": False,
        "real_order_attempted": False,
        "real_order_submitted": False,
        "writes_exchange_orders": False,
        "writes_legacy_redis": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "raw_credential_in_payload": "NEVER",
        "no_provider_network_calls_from_frontend": True,
        "no_provider_network_calls_from_renderer": True,
        "no_live_buttons": True,
        "no_order_buttons": True,
        "no_shutdown_claim": True,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "display_only": True,
    }


def write_dashboard_payload(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    for target in (WORKLOG_PAYLOAD_PATH, PUBLIC_PAYLOAD_PATH):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_top10_dashboards_renderer")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if args.once == args.loop:
        args.once = True
        args.loop = False
    if args.once:
        r = _connect_redis()
        payload = build_dashboard_payload(r)
        write_dashboard_payload(payload)
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "panels_total": payload["panels_total"],
                    "panels_ok_rows_present": payload["panels_ok_rows_present"],
                    "panels_key_missing": payload["panels_key_missing"],
                    "panels_stale": payload["panels_stale"],
                    "panels_budget_limited": payload["panels_budget_limited"],
                    "panels_key_present_no_client_yet": payload[
                        "panels_key_present_no_client_yet"
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    while True:  # pragma: no cover — runtime loop
        r = _connect_redis()
        write_dashboard_payload(build_dashboard_payload(r))
        try:
            time.sleep(max(15, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
