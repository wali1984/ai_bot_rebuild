"""Validate and quarantine invalid V2 paper portfolio rows.

This CLI is evidence-preserving. It reads V2 paper Redis keys, writes immutable
snapshot files, and optionally writes new V2 quarantine/freeze keys. It never
places, cancels, modifies, or routes real exchange orders.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from v2.backend.app.services.paper_trade_management.position_validity import (
    PAPER_ACCOUNT_SCOPE,
    QUARANTINED_ACCOUNT_SCOPE,
    SHADOW_ACCOUNT_SCOPE,
    PositionValidityConfig,
    split_valid_invalid_closed_trades,
    split_valid_invalid_positions,
)

GOAL_ID = "V2_PORTFOLIO_LEDGER_TRUTH_INVALID_POSITION_QUARANTINE_AND_END_TO_END_RECOVERY"
REPO_ROOT = Path(__file__).resolve().parents[4]
GOAL_DIR = REPO_ROOT / "goal_state" / GOAL_ID
RAW_EVIDENCE_ROOT = REPO_ROOT / "raw_evidence"
V2_REDIS_PREFIX = "v2:"
FREEZE_KEY = "v2:paper:entry_freeze"
INVALID_POSITION_QUARANTINE_KEY = "v2:paper:quarantine:invalid_positions"
INVALID_CLOSED_TRADE_QUARANTINE_KEY = "v2:paper:quarantine:invalid_closed_trades"

ARCHIVE_KEYS = (
    "v2:portfolio:state",
    "v2:paper:open_positions",
    "v2:paper:positions",
    "v2:paper:closed_trades",
    "v2:paper:heartbeat",
    "v2:paper:ledger",
)
ARCHIVE_PATTERNS = (
    "v2:paper:*position*",
    "v2:paper:*fill*",
    "v2:paper:*outcome*",
)
HTTP_ARCHIVE_URLS = {
    "api_v2_portfolio.json": "http://127.0.0.1:8000/api/v2/portfolio",
    "api_v2_paper_runtime_status.json": "http://127.0.0.1:8000/api/v2/paper/runtime-status",
    "api_v2_live_readiness.json": "http://127.0.0.1:8000/api/v2/live/readiness",
    "api_v2_account_summary.json": "http://127.0.0.1:8000/api/v2/account/summary",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _decode_json(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _read_redis_key(client: Any, key: str) -> dict[str, Any]:
    try:
        key_type = client.type(key)
    except Exception as exc:
        return {"key": key, "error": str(exc)}
    if isinstance(key_type, bytes):
        key_type = key_type.decode()
    payload: Any = None
    try:
        if key_type == "string":
            payload = _decode_json(client.get(key))
        elif key_type == "list":
            payload = [_decode_json(item) for item in client.lrange(key, 0, -1)]
        elif key_type == "set":
            payload = sorted(str(item) for item in client.smembers(key))
        elif key_type == "zset":
            payload = [{"value": value, "score": score} for value, score in client.zrange(key, 0, -1, withscores=True)]
        elif key_type == "hash":
            payload = {field: _decode_json(value) for field, value in client.hgetall(key).items()}
        else:
            payload = None
    except Exception as exc:
        return {"key": key, "type": key_type, "error": str(exc)}
    return {"key": key, "type": key_type, "payload": payload}


def _archive_redis(client: Any, evidence_dir: Path) -> dict[str, Any]:
    keys: set[str] = set(ARCHIVE_KEYS)
    if client is not None:
        for pattern in ARCHIVE_PATTERNS:
            try:
                keys.update(str(key) for key in client.scan_iter(match=pattern, count=500))
            except Exception:
                continue
    archive: dict[str, Any] = {"generated_utc": _utc_iso(), "keys": {}}
    if client is None:
        archive["redis_available"] = False
    else:
        archive["redis_available"] = True
        for key in sorted(keys):
            archive["keys"][key] = _read_redis_key(client, key)
            _write_json(evidence_dir / "redis" / f"{key.replace(':', '__')}.json", archive["keys"][key])
    _write_json(evidence_dir / "redis_archive_index.json", archive)
    return archive


def _archive_http(evidence_dir: Path) -> dict[str, Any]:
    archived: dict[str, Any] = {"generated_utc": _utc_iso(), "urls": {}}
    for filename, url in HTTP_ARCHIVE_URLS.items():
        try:
            with urlopen(url, timeout=3) as response:  # noqa: S310 - local operator API snapshot only
                raw = response.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            archived["urls"][url] = {"available": True, "filename": filename}
            _write_json(evidence_dir / "http" / filename, payload)
        except (OSError, URLError, TimeoutError) as exc:
            archived["urls"][url] = {"available": False, "error": str(exc), "filename": filename}
    _write_json(evidence_dir / "http_archive_index.json", archived)
    return archived


def _rows_from_payload(value: Any) -> list[dict[str, Any]]:
    decoded = _decode_json(value)
    if isinstance(decoded, list):
        return [dict(row) for row in decoded if isinstance(row, dict)]
    if isinstance(decoded, dict):
        return [dict(row) for row in decoded.values() if isinstance(row, dict)]
    return []


def _ledger_from_archive(archive: dict[str, Any]) -> dict[str, Any]:
    entry = archive.get("keys", {}).get("v2:paper:ledger", {})
    payload = entry.get("payload")
    return payload if isinstance(payload, dict) else {}


def _standalone_rows(archive: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entry = archive.get("keys", {}).get(key, {})
    return _rows_from_payload(entry.get("payload"))


def _dedupe_identity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        identity = str(
            row.get("fill_id")
            or row.get("ledger_row_id")
            or row.get("intent_id")
            or row.get("source_intent_id")
            or row.get("position_id")
            or row.get("id")
            or row
        )
        if identity in seen:
            continue
        seen.add(identity)
        out.append(row)
    return out


def _open_position_rows(archive: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = _ledger_from_archive(archive)
    accepted_rows: list[dict[str, Any]] = []
    for key in ("accepted", "accepted_intents", "accepted_open_fills"):
        value = ledger.get(key)
        if isinstance(value, list):
            accepted_rows.extend(dict(row) for row in value if isinstance(row, dict))
    if accepted_rows:
        return _dedupe_identity_rows(accepted_rows)
    standalone_rows = _standalone_rows(archive, "v2:paper:positions")
    if standalone_rows:
        return _dedupe_identity_rows(standalone_rows)
    fallback_rows: list[dict[str, Any]] = []
    for key in ("open_positions", "positions"):
        value = ledger.get(key)
        if isinstance(value, list):
            fallback_rows.extend(dict(row) for row in value if isinstance(row, dict))
    if fallback_rows:
        return _dedupe_identity_rows(fallback_rows)
    return []


def _closed_trade_rows(archive: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = _ledger_from_archive(archive)
    rows = _standalone_rows(archive, "v2:paper:closed_trades")
    for key in ("closed_trades", "closes", "closed", "closed_positions"):
        value = ledger.get(key)
        if isinstance(value, list):
            rows.extend(dict(row) for row in value if isinstance(row, dict))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get("close_id") or row.get("paper_close_id") or row.get("outcome_label_id") or row.get("trainer_feedback_id") or row)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(row)
    return out


def _price_from_market_payload(payload: Any) -> tuple[float | None, str | None, float | None]:
    if not isinstance(payload, dict):
        return None, None, None
    candidates = []
    ticker = payload.get("ticker_24hr") if isinstance(payload.get("ticker_24hr"), dict) else {}
    funding = payload.get("funding") if isinstance(payload.get("funding"), dict) else {}
    for source, container, keys in (
        ("v2:market:prices.ticker_24hr.lastPrice", ticker, ("lastPrice", "weightedAvgPrice")),
        ("v2:market:prices.funding.markPrice", funding, ("markPrice", "indexPrice")),
        ("v2:market:prices", payload, ("price", "last_price", "mark_price", "close")),
    ):
        for key in keys:
            try:
                value = container.get(key)
                parsed = float(value) if value is not None else None
            except (AttributeError, TypeError, ValueError):
                parsed = None
            if parsed is not None and parsed > 0:
                candidates.append((parsed, source, payload.get("fetched_utc") or payload.get("generated_utc")))
    if not candidates:
        return None, None, None
    price, source, generated = candidates[0]
    age = None
    if isinstance(generated, str) and generated:
        try:
            generated_dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            age = max(0.0, time.time() - generated_dt.timestamp())
        except ValueError:
            age = None
    return price, source, age


def _market_prices(client: Any, symbols: set[str]) -> dict[str, tuple[float | None, str | None, float | None]]:
    out: dict[str, tuple[float | None, str | None, float | None]] = {}
    if client is None:
        return out
    for symbol in sorted(symbols):
        try:
            payload = _decode_json(client.get(f"v2:market:prices:{symbol}"))
        except Exception:
            payload = None
        out[symbol] = _price_from_market_payload(payload)
    return out


def _write_redis_json(client: Any, key: str, payload: Any) -> bool:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        client.set(key, json.dumps(payload, sort_keys=True, default=_json_default))
        return True
    except Exception:
        return False


def _freeze_payload(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "paper_entry_freeze_v1",
        "generated_utc": _utc_iso(),
        "paper_new_entries_halted": True,
        "new_entries_allowed": False,
        "close_reduce_diagnostics_allowed": True,
        "mark_to_market_allowed": True,
        "reason": reason,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }


def run(
    *,
    evidence_dir: Path | None = None,
    write_redis_quarantine: bool = False,
    halt_new_entries: bool = False,
) -> dict[str, Any]:
    client = _connect_redis()
    evidence_dir = evidence_dir or RAW_EVIDENCE_ROOT / f"portfolio_corruption_{_timestamp_slug()}"
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    archive = _archive_redis(client, evidence_dir)
    http_archive = _archive_http(evidence_dir)
    open_rows = _open_position_rows(archive)
    closed_rows = _closed_trade_rows(archive)
    symbols = {str(row.get("symbol") or "").upper() for row in open_rows if row.get("symbol")}
    marks = _market_prices(client, symbols)

    validation_config = PositionValidityConfig(
        require_production_cost_flag=True,
        require_explicit_paper_only=True,
        require_fresh_current_mark=False,
    )
    valid_positions, invalid_positions, position_statuses = split_valid_invalid_positions(
        open_rows,
        mark_prices=marks,
        config=validation_config,
    )
    valid_closed, invalid_closed, closed_statuses = split_valid_invalid_closed_trades(closed_rows)

    invalid_btc_position_present = any(
        str(row.get("symbol") or "").upper() == "BTCUSDT"
        and (
            "BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_CURRENT_MARK" in row.get("quarantine_reasons", [])
            or "ENTRY_PRICE_CURRENT_MARK_IMPOSSIBLE_RATIO" in row.get("quarantine_reasons", [])
        )
        for row in invalid_positions
    )
    shadow_invalid = [
        row
        for row in invalid_positions
        if any("SHADOW" in str(reason) for reason in row.get("quarantine_reasons", []))
    ]
    impossible_price_invalid = [
        row
        for row in invalid_positions
        if any("IMPOSSIBLE" in str(reason) or "MISMATCH" in str(reason) for reason in row.get("quarantine_reasons", []))
    ]
    portfolio_state = archive.get("keys", {}).get("v2:portfolio:state", {}).get("payload")
    portfolio_state = portfolio_state if isinstance(portfolio_state, dict) else {}

    freeze_written = False
    if halt_new_entries:
        freeze_written = _write_redis_json(
            client,
            FREEZE_KEY,
            _freeze_payload("PORTFOLIO_LEDGER_TRUTH_VALIDATION_AND_QUARANTINE"),
        )
    quarantine_positions_written = False
    quarantine_closed_written = False
    if write_redis_quarantine:
        quarantine_positions_written = _write_redis_json(client, INVALID_POSITION_QUARANTINE_KEY, invalid_positions)
        quarantine_closed_written = _write_redis_json(client, INVALID_CLOSED_TRADE_QUARANTINE_KEY, invalid_closed)

    freeze_packet = {
        "schema_version": "portfolio_corruption_freeze_packet_v1",
        "generated_utc": _utc_iso(),
        "raw_evidence_dir": str(evidence_dir),
        "paper_new_entries_halted": bool(halt_new_entries and freeze_written),
        "paper_entry_freeze_key": FREEZE_KEY,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "invalid_btc_position_present": invalid_btc_position_present,
        "equity_before_rebuild": portfolio_state.get("equity"),
        "unrealized_pnl_before_rebuild": portfolio_state.get("unrealized_pnl_usd") or portfolio_state.get("unrealized_pnl"),
        "open_position_count_before_rebuild": len(open_rows),
        "redis_archive_available": archive.get("redis_available") is True,
        "http_archive": http_archive,
    }
    validity_status = {
        "schema_version": "paper_position_validity_status_v1",
        "generated_utc": _utc_iso(),
        "status": "INVALID_POSITIONS_PRESENT" if invalid_positions else "ALL_OPEN_POSITIONS_VALID",
        "account_scope": PAPER_ACCOUNT_SCOPE if not invalid_positions else QUARANTINED_ACCOUNT_SCOPE,
        "open_position_count": len(open_rows),
        "valid_open_position_count": len(valid_positions),
        "invalid_open_position_count": len(invalid_positions),
        "closed_trade_count": len(closed_rows),
        "valid_closed_trade_count": len(valid_closed),
        "invalid_closed_trade_count": len(invalid_closed),
        "position_statuses": position_statuses,
        "closed_trade_statuses": closed_statuses,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    quarantine_status = {
        "schema_version": "paper_invalid_position_quarantine_status_v1",
        "generated_utc": _utc_iso(),
        "status": "INVALID_ROWS_QUARANTINED" if invalid_positions or invalid_closed else "NO_INVALID_ROWS_TO_QUARANTINE",
        "invalid_position_count": len(invalid_positions),
        "invalid_closed_trade_count": len(invalid_closed),
        "valid_position_count": len(valid_positions),
        "valid_closed_trade_count": len(valid_closed),
        "redis_invalid_positions_quarantine_key": INVALID_POSITION_QUARANTINE_KEY,
        "redis_invalid_closed_trades_quarantine_key": INVALID_CLOSED_TRADE_QUARANTINE_KEY,
        "redis_invalid_positions_quarantine_written": quarantine_positions_written,
        "redis_invalid_closed_trades_quarantine_written": quarantine_closed_written,
        "quarantined_positions_file": str(evidence_dir / "quarantined_positions.jsonl"),
        "quarantined_closed_trades_file": str(evidence_dir / "quarantined_closed_trades.jsonl"),
        "excluded_from_equity": True,
        "excluded_from_available_balance": True,
        "excluded_from_realized_pnl": True,
        "excluded_from_unrealized_pnl": True,
        "excluded_from_capital_productivity": True,
        "excluded_from_a_grade_evidence": True,
        "excluded_from_1000x_trajectory": True,
        "excluded_from_trainer_feedback": True,
        "excluded_from_win_rate": True,
        "excluded_from_profit_factor": True,
        "excluded_from_drawdown": True,
    }
    shadow_status = {
        "schema_version": "shadow_position_leak_status_v1",
        "generated_utc": _utc_iso(),
        "status": "SHADOW_LEAKS_QUARANTINED" if shadow_invalid else "NO_SHADOW_POSITION_LEAKS",
        "shadow_invalid_position_count": len(shadow_invalid),
        "account_scope": SHADOW_ACCOUNT_SCOPE if shadow_invalid else PAPER_ACCOUNT_SCOPE,
        "sample_rows": shadow_invalid[:25],
    }
    impossible_price_status = {
        "schema_version": "impossible_price_position_status_v1",
        "generated_utc": _utc_iso(),
        "status": "IMPOSSIBLE_PRICE_POSITIONS_QUARANTINED" if impossible_price_invalid else "NO_IMPOSSIBLE_PRICE_POSITIONS",
        "invalid_btc_position_present": invalid_btc_position_present,
        "impossible_price_position_count": len(impossible_price_invalid),
        "sample_rows": impossible_price_invalid[:25],
    }

    _write_json(GOAL_DIR / "current_corruption_freeze_packet.json", freeze_packet)
    _write_json(GOAL_DIR / "paper_position_validity_status.json", validity_status)
    _write_json(GOAL_DIR / "invalid_open_positions.json", invalid_positions)
    _write_json(GOAL_DIR / "invalid_closed_trades.json", invalid_closed)
    _write_json(GOAL_DIR / "shadow_position_leak_status.json", shadow_status)
    _write_json(GOAL_DIR / "impossible_price_position_status.json", impossible_price_status)
    _write_json(GOAL_DIR / "paper_invalid_position_quarantine_status.json", quarantine_status)
    _append_jsonl(evidence_dir / "quarantined_positions.jsonl", invalid_positions)
    _append_jsonl(evidence_dir / "quarantined_closed_trades.jsonl", invalid_closed)

    return {
        "freeze_packet": freeze_packet,
        "validity_status": validity_status,
        "quarantine_status": quarantine_status,
        "shadow_status": shadow_status,
        "impossible_price_status": impossible_price_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and quarantine V2 paper portfolio rows")
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--write-redis-quarantine", action="store_true")
    parser.add_argument("--halt-new-entries", action="store_true")
    args = parser.parse_args()
    result = run(
        evidence_dir=args.evidence_dir,
        write_redis_quarantine=args.write_redis_quarantine,
        halt_new_entries=args.halt_new_entries,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
