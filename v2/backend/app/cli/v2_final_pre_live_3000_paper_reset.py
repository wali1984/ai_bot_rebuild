"""Archive and reset the final pre-live V2 paper session to $3,000.

This tool is intentionally paper-only. It archives the current V2 paper Redis
state and local operator payloads, stops only the canonical paper loop, resets
active paper-session state, and restarts only that same canonical paper loop.
It never places, cancels, modifies, or routes real exchange orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

GOAL_ID = "V2_FINAL_PRE_LIVE_3000_PAPER_EDGE_REBUILD_A_GRADE_1000X_TRAJECTORY"
REPO_ROOT = Path(__file__).resolve().parents[4]
GOAL_DIR = REPO_ROOT / "goal_state" / GOAL_ID
RAW_EVIDENCE_ROOT = REPO_ROOT / "raw_evidence"

RESET_INITIAL_CAPITAL = 3_000.0
CANONICAL_PAPER_LOOP_SERVICE = "ai-bot-v2-trade-management-paper-loop.service"
PAPER_TRAINING_EVIDENCE_TTL_SECONDS = 30 * 24 * 60 * 60
PORTFOLIO_STATE_TTL_SECONDS = 15 * 60
PAPER_HEARTBEAT_TTL_SECONDS = 60 * 60

ARCHIVE_KEYS = (
    "v2:portfolio:state",
    "v2:paper:ledger",
    "v2:paper:closed_trades",
    "v2:paper:open_positions",
    "v2:paper:accepted_fills",
    "v2:paper:heartbeat",
    "v2:paper:session",
    "v2:paper:churn_equity_bleed_governor_status",
    "v2:paper:a_grade_gate_burndown_status",
    "v2:paper:forward_canary_evidence_status",
    "v2:paper:b_grade_canary_supply_status",
    # Active aliases used by this repo's canonical paper loop.
    "v2:paper:positions",
    "v2:paper:outcome_labels",
    "v2:trainer:feedback:outcomes",
    "v2:trainer:feedback:outcomes:quarantine",
)
ARCHIVE_PATTERNS = (
    "v2:paper:outcome_memory:*",
    "v2:paper:quarantine:*",
)
RESET_FIXED_KEYS = (
    "v2:paper:ledger",
    "v2:paper:closed_trades",
    "v2:paper:open_positions",
    "v2:paper:accepted_fills",
    "v2:paper:heartbeat",
    "v2:paper:session",
    "v2:portfolio:state",
    # Compatibility aliases required to prevent stale paper-loop/lifecycle reads.
    "v2:paper:positions",
    "v2:paper:outcome_labels",
    "v2:trainer:feedback:outcomes",
    "v2:trainer:feedback:outcomes:quarantine",
)
RESET_PATTERNS = ("v2:paper:outcome_memory:*",)
PRESERVED_KEYS = (
    "v2:paper:historical_outcome_counts",
    "v2:paper:quarantine:*",
)

HTTP_ARCHIVE_URLS = {
    "api_v2_portfolio.json": "http://127.0.0.1:8000/api/v2/portfolio",
    "api_v2_paper_runtime_status.json": "http://127.0.0.1:8000/api/v2/paper/runtime-status",
    "api_v2_live_readiness.json": "http://127.0.0.1:8000/api/v2/live/readiness",
    "api_v2_account_summary.json": "http://127.0.0.1:8000/api/v2/account/summary",
    "api_v2_mobile_dashboard.json": "http://127.0.0.1:8000/api/v2/mobile/dashboard",
    "api_v2_mobile_positions.json": "http://127.0.0.1:8000/api/v2/mobile/positions",
    "api_v2_mobile_paper_summary.json": "http://127.0.0.1:8000/api/v2/mobile/paper-summary",
    "api_v2_mobile_health.json": "http://127.0.0.1:8000/api/v2/mobile/health",
}

TRADE_MANAGEMENT_PUBLIC_DIR = REPO_ROOT / (
    "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest"
)
PAPER_ACCEPTED_FILLS_STATE_PATH = TRADE_MANAGEMENT_PUBLIC_DIR / "paper_accepted_fills_state.json"
PAPER_LIFECYCLE_STATE_PATH = TRADE_MANAGEMENT_PUBLIC_DIR / "paper_lifecycle_state.json"
PAPER_OUTCOME_LABELS_PATH = TRADE_MANAGEMENT_PUBLIC_DIR / "paper_outcome_labels.json"
TRAINER_FEEDBACK_OUTCOMES_PATH = TRADE_MANAGEMENT_PUBLIC_DIR / "trainer_feedback_outcomes.json"
PORTFOLIO_PUBLIC_PATH = REPO_ROOT / (
    "v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"
)
LOCAL_RUNTIME_FILES = (
    PAPER_ACCEPTED_FILLS_STATE_PATH,
    PAPER_LIFECYCLE_STATE_PATH,
    PAPER_OUTCOME_LABELS_PATH,
    TRAINER_FEEDBACK_OUTCOMES_PATH,
    PORTFOLIO_PUBLIC_PATH,
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_default(value: Any) -> str:
    return str(value)


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


def _safe_int(value: Any, default: int = 0) -> int:
    parsed = _safe_float(value)
    return default if parsed is None else int(parsed)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_hashed_json(path: Path, payload: Any, hashes: dict[str, str]) -> None:
    _write_json(path, payload)
    hashes[str(path.relative_to(REPO_ROOT))] = _hash_file(path)


def _decode_json(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _connect_redis() -> Any:
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
            socket_timeout=5,
        )
        client.ping()
        return client
    except Exception:
        return None


def _read_redis_key(client: Any, key: str) -> dict[str, Any]:
    try:
        key_type = client.type(key)
    except Exception as exc:
        return {"key": key, "exists": False, "error": str(exc)}
    if isinstance(key_type, bytes):
        key_type = key_type.decode("utf-8", errors="replace")
    exists = key_type != "none"
    entry: dict[str, Any] = {"key": key, "type": key_type, "exists": exists}
    if not exists:
        return entry
    try:
        entry["ttl_seconds"] = client.ttl(key)
    except Exception:
        entry["ttl_seconds"] = None
    try:
        if key_type == "string":
            raw = client.get(key)
            entry["raw_bytes"] = len(raw.encode("utf-8")) if isinstance(raw, str) else 0
            entry["payload"] = _decode_json(raw)
        elif key_type == "list":
            rows = client.lrange(key, 0, -1)
            entry["payload"] = [_decode_json(row) for row in rows]
        elif key_type == "set":
            entry["payload"] = sorted(str(row) for row in client.smembers(key))
        elif key_type == "zset":
            entry["payload"] = [
                {"value": value, "score": score}
                for value, score in client.zrange(key, 0, -1, withscores=True)
            ]
        elif key_type == "hash":
            entry["payload"] = {
                field: _decode_json(value)
                for field, value in client.hgetall(key).items()
            }
        else:
            entry["payload"] = None
    except Exception as exc:
        entry["error"] = str(exc)
    return entry


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _archive_redis(client: Any, evidence_dir: Path, hashes: dict[str, str]) -> dict[str, Any]:
    redis_dir = evidence_dir / "redis"
    keys = set(ARCHIVE_KEYS)
    pattern_counts: dict[str, int] = {}
    if client is not None:
        for pattern in ARCHIVE_PATTERNS:
            matches = sorted(str(key) for key in client.scan_iter(match=pattern, count=1000))
            pattern_counts[pattern] = len(matches)
            keys.update(matches)
    archive_payloads: dict[str, Any] = {}
    index: dict[str, Any] = {
        "schema_version": "pre_3000_reset_redis_archive_index_v1",
        "generated_utc": _utc_iso(),
        "redis_available": client is not None,
        "archive_patterns": list(ARCHIVE_PATTERNS),
        "pattern_counts": pattern_counts,
        "keys": {},
    }
    if client is None:
        _write_hashed_json(evidence_dir / "redis_archive_index.json", index, hashes)
        return {"index": index, "payloads": archive_payloads}
    for key in sorted(keys):
        entry = _read_redis_key(client, key)
        archive_payloads[key] = entry.get("payload")
        key_path = redis_dir / f"{key.replace(':', '__')}.json"
        _write_hashed_json(key_path, entry, hashes)
        index["keys"][key] = {
            "exists": entry.get("exists"),
            "type": entry.get("type"),
            "ttl_seconds": entry.get("ttl_seconds"),
            "archive_file": _relative_or_absolute(key_path),
            "sha256": hashes[str(key_path.relative_to(REPO_ROOT))],
            "error": entry.get("error"),
        }
    _write_hashed_json(evidence_dir / "redis_archive_index.json", index, hashes)
    return {"index": index, "payloads": archive_payloads}


def _archive_http(evidence_dir: Path, hashes: dict[str, str]) -> dict[str, Any]:
    index: dict[str, Any] = {
        "schema_version": "pre_3000_reset_http_archive_index_v1",
        "generated_utc": _utc_iso(),
        "urls": {},
    }
    http_dir = evidence_dir / "http"
    for filename, url in HTTP_ARCHIVE_URLS.items():
        path = http_dir / filename
        try:
            with urlopen(url, timeout=3) as response:  # noqa: S310 - localhost operator API snapshot.
                raw = response.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            _write_hashed_json(path, payload, hashes)
            index["urls"][url] = {
                "available": True,
                "archive_file": _relative_or_absolute(path),
                "sha256": hashes[str(path.relative_to(REPO_ROOT))],
            }
        except (HTTPError, OSError, TimeoutError, URLError) as exc:
            unavailable = {"available": False, "url": url, "error": str(exc)}
            _write_hashed_json(path, unavailable, hashes)
            index["urls"][url] = {
                "available": False,
                "archive_file": _relative_or_absolute(path),
                "sha256": hashes[str(path.relative_to(REPO_ROOT))],
                "error": str(exc),
            }
    _write_hashed_json(evidence_dir / "http_archive_index.json", index, hashes)
    return index


def _archive_local_runtime_files(evidence_dir: Path, hashes: dict[str, str]) -> dict[str, Any]:
    file_dir = evidence_dir / "local_runtime_files"
    index: dict[str, Any] = {
        "schema_version": "pre_3000_reset_local_runtime_file_archive_index_v1",
        "generated_utc": _utc_iso(),
        "files": {},
    }
    for path in LOCAL_RUNTIME_FILES:
        archive_path = file_dir / path.relative_to(REPO_ROOT)
        if path.exists():
            try:
                payload = _decode_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                payload = {"read_error": str(exc)}
            _write_hashed_json(archive_path, payload, hashes)
            index["files"][_relative_or_absolute(path)] = {
                "exists": True,
                "archive_file": _relative_or_absolute(archive_path),
                "sha256": hashes[str(archive_path.relative_to(REPO_ROOT))],
            }
        else:
            payload = {"exists": False, "path": _relative_or_absolute(path)}
            _write_hashed_json(archive_path.with_suffix(".missing.json"), payload, hashes)
            index["files"][_relative_or_absolute(path)] = {
                "exists": False,
                "archive_file": _relative_or_absolute(archive_path.with_suffix(".missing.json")),
                "sha256": hashes[str(archive_path.with_suffix(".missing.json").relative_to(REPO_ROOT))],
            }
    _write_hashed_json(evidence_dir / "local_runtime_file_archive_index.json", index, hashes)
    return index


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("rows", "positions", "open_positions", "closed_trades", "accepted_fills"):
            rows = value.get(key)
            if isinstance(rows, list):
                return rows
    return []


def _count_payload_rows(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in (
            "open_positions",
            "positions",
            "closed_trades",
            "closes",
            "accepted",
            "accepted_fills",
            "outcome_labels",
            "rows",
        ):
            rows = value.get(key)
            if isinstance(rows, list):
                return len(rows)
    return 0


def _rows_for_phantom_check(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in (
        "accepted",
        "accepted_intents",
        "accepted_open_fills",
        "accepted_fills",
        "open_positions",
        "positions",
        "closed_trades",
        "closes",
    ):
        value_rows = value.get(key)
        if isinstance(value_rows, list):
            rows.extend(dict(row) for row in value_rows if isinstance(row, dict))
    return rows


def _row_is_btc_100_phantom(row: dict[str, Any]) -> bool:
    row_id = str(
        row.get("fill_id")
        or row.get("signal_id")
        or row.get("intent_id")
        or row.get("source_signal_id")
        or row.get("source_fill_id")
        or ""
    )
    if row_id == "signal-btc-1m":
        return True
    symbol = str(row.get("symbol") or "").upper()
    entry = _safe_float(
        row.get("entry_price")
        or row.get("avg_entry_price")
        or row.get("fill_price")
        or row.get("price")
    )
    quantity = _safe_float(row.get("quantity") or row.get("qty") or row.get("size"))
    return symbol == "BTCUSDT" and entry == 100.0 and (quantity is None or quantity >= 1.0)


def _btc_100_phantom_absent(payloads: dict[str, Any]) -> bool:
    for key, payload in payloads.items():
        if key.startswith("v2:paper:quarantine:"):
            continue
        for row in _rows_for_phantom_check(payload):
            if _row_is_btc_100_phantom(row):
                return False
    return True


def _pre_reset_summary(
    *,
    evidence_dir: Path,
    redis_archive: dict[str, Any],
    http_archive: dict[str, Any],
    file_archive: dict[str, Any],
    hashes: dict[str, str],
) -> dict[str, Any]:
    payloads = redis_archive.get("payloads", {})
    portfolio = payloads.get("v2:portfolio:state") if isinstance(payloads.get("v2:portfolio:state"), dict) else {}
    ledger = payloads.get("v2:paper:ledger") if isinstance(payloads.get("v2:paper:ledger"), dict) else {}
    closed = payloads.get("v2:paper:closed_trades")
    positions = payloads.get("v2:paper:positions")
    open_positions = payloads.get("v2:paper:open_positions")
    quarantine_positions = payloads.get("v2:paper:quarantine:invalid_positions")
    quarantine_closed = payloads.get("v2:paper:quarantine:invalid_closed_trades")

    pre_reset_open_positions = max(
        _safe_int(portfolio.get("open_positions_count")),
        _count_payload_rows(open_positions),
        _count_payload_rows(positions),
        _count_payload_rows(ledger.get("open_positions") if isinstance(ledger, dict) else None),
    )
    pre_reset_closed_trades = max(
        _safe_int(portfolio.get("closed_positions_count") or portfolio.get("closed_trades_count")),
        _count_payload_rows(closed),
        _count_payload_rows(ledger.get("closed_trades") if isinstance(ledger, dict) else None),
    )
    pre_reset_quarantined_positions = _count_payload_rows(quarantine_positions)
    pre_reset_invalid_positions = pre_reset_quarantined_positions + _count_payload_rows(quarantine_closed)
    live_gate = (
        portfolio.get("live_gate")
        or portfolio.get("live_gate_status")
        or ledger.get("live_gate")
        or "blocked_human_only"
    )
    places_real_order = bool(
        portfolio.get("places_real_order")
        or ledger.get("places_real_order")
        or False
    )
    pass_conditions = {
        "active_evidence_archived": bool(redis_archive.get("index", {}).get("redis_available")),
        "btc_100_phantom_absent": _btc_100_phantom_absent(payloads),
        "invalid_rows_quarantined_or_absent": pre_reset_invalid_positions > 0 or pre_reset_open_positions == 0,
        "live_still_blocked": live_gate == "blocked_human_only",
        "pre_reset_hashes_written": bool(hashes),
    }
    return {
        "schema_version": "pre_3000_reset_evidence_freeze_status_v1",
        "generated_utc": _utc_iso(),
        "status": "PRE_RESET_EVIDENCE_ARCHIVED" if all(pass_conditions.values()) else "PRE_RESET_EVIDENCE_ARCHIVE_BLOCKED",
        "goal_id": GOAL_ID,
        "raw_evidence_dir": _relative_or_absolute(evidence_dir),
        "pre_reset_equity": portfolio.get("equity") or portfolio.get("current_session_equity"),
        "pre_reset_realized_pnl": portfolio.get("realized_pnl_usd") or portfolio.get("realized_pnl") or 0.0,
        "pre_reset_unrealized_pnl": portfolio.get("unrealized_pnl_usd") or portfolio.get("unrealized_pnl") or 0.0,
        "pre_reset_open_positions": pre_reset_open_positions,
        "pre_reset_closed_trades": pre_reset_closed_trades,
        "pre_reset_quarantined_positions": pre_reset_quarantined_positions,
        "pre_reset_invalid_positions": pre_reset_invalid_positions,
        "pre_reset_live_gate": live_gate,
        "pre_reset_places_real_order": places_real_order,
        "pre_reset_hashes_written": bool(hashes),
        "pass_conditions": pass_conditions,
        "redis_archive": redis_archive.get("index", {}),
        "http_archive": http_archive,
        "local_runtime_file_archive": file_archive,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _build_reset_payloads(reset_session_id: str, generated_utc: str) -> dict[str, Any]:
    portfolio_state = {
        "schema_version": "v2_paper_3000_reset_portfolio_state_v1",
        "classification": "PAPER_3000_RESET_CLEAN_SESSION",
        "generated_utc": generated_utc,
        "account_mode": "paper_shadow_only",
        "account_scope": "PAPER_SIM_ACCOUNT",
        "source_type": "operator_authorized_paper_3000_reset",
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": False,
        "equity_trusted": True,
        "pnl_trusted": True,
        "reason_if_untrusted": None,
        "initial_capital": RESET_INITIAL_CAPITAL,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "available_balance": RESET_INITIAL_CAPITAL,
        "cash_balance": RESET_INITIAL_CAPITAL,
        "wallet_balance": RESET_INITIAL_CAPITAL,
        "equity": RESET_INITIAL_CAPITAL,
        "current_session_equity": RESET_INITIAL_CAPITAL,
        "equity_high_water_mark": RESET_INITIAL_CAPITAL,
        "realized_pnl": 0.0,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_usd": 0.0,
        "total_pnl_usd": 0.0,
        "current_drawdown_usd": 0.0,
        "current_drawdown_bps": 0.0,
        "positions": [],
        "open_positions": [],
        "closed_positions": [],
        "closed_trades": [],
        "positions_by_symbol": [],
        "paper_fill_economic_inventory": [],
        "open_positions_count": 0,
        "closed_positions_count": 0,
        "closed_trades_count": 0,
        "accepted_fill_total": 0,
        "active_accepted_fill_total": 0,
        "order_counters": {
            "paper_accepted_intent_count": 0,
            "paper_accepted_fill_count": 0,
            "paper_economic_fill_count": 0,
            "paper_non_economic_fill_count": 0,
            "paper_held_intent_count": 0,
            "paper_blocked_intent_count": 0,
            "paper_shadow_observation_count": 0,
            "paper_open_position_count": 0,
            "paper_closed_position_count": 0,
            "live_order_count": 0,
            "test_order_count": 0,
            "exchange_order_mutation_count": 0,
        },
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "live_gate": "blocked_human_only",
        "live_gate_status": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    paper_session = {
        "schema_version": "v2_paper_3000_session_v1",
        "generated_utc": generated_utc,
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "initial_capital": RESET_INITIAL_CAPITAL,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "account_scope": "PAPER_SIM_ACCOUNT",
        "paper_or_live": "paper",
        "session_state": "active",
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    ledger = {
        "schema_version": "v2_paper_3000_reset_ledger_v1",
        "generated_utc": generated_utc,
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "initial_capital": RESET_INITIAL_CAPITAL,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "accepted_count": 0,
        "current_cycle_accepted_count": 0,
        "blocked_count": 0,
        "held_by_paper_fill_gate_count": 0,
        "shadow_observation_count": 0,
        "persistent_shadow_observation_count": 0,
        "accepted_position_count": 0,
        "open_position_count": 0,
        "closed_trade_count": 0,
        "outcome_label_count": 0,
        "trainer_feedback_total_row_count": 0,
        "trainer_feedback_row_count": 0,
        "trainer_feedback_quarantined_row_count": 0,
        "accepted": [],
        "accepted_intents": [],
        "current_cycle_accepted": [],
        "blocked": [],
        "held_by_paper_fill_gate": [],
        "shadow_observations": [],
        "persistent_shadow_observations": [],
        "open_positions": [],
        "positions_by_symbol": {},
        "closed_trades": [],
        "closes": [],
        "outcome_labels": [],
        "trainer_feedback_outcomes": [],
        "trainer_feedback_outcomes_quarantine": [],
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "total_open_notional": 0.0,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    heartbeat = {
        "schema_version": "v2_paper_3000_reset_heartbeat_v1",
        "generated_utc": generated_utc,
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "initial_capital": RESET_INITIAL_CAPITAL,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "equity": RESET_INITIAL_CAPITAL,
        "current_session_equity": RESET_INITIAL_CAPITAL,
        "available_balance": RESET_INITIAL_CAPITAL,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "accepted_count": 0,
        "open_position_count": 0,
        "closed_trade_count": 0,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    accepted_fills_file = {
        "accepted_fill_state_schema_version": "v2_compact_accepted_fill_state_v1",
        "accepted_fill_state_compacted": True,
        "accepted_fill_state_row_count": 0,
        "accepted_fills": [],
        "current_cycle_accepted": [],
        "generated_utc": generated_utc,
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    lifecycle_file = {
        "paper_lifecycle_state_schema_version": "v2_paper_lifecycle_state_v1",
        "accepted_fills": [],
        "current_cycle_accepted": [],
        "open_positions": [],
        "positions_by_symbol": {},
        "closed_trades": [],
        "closes": [],
        "outcome_labels": [],
        "trainer_feedback_outcomes": [],
        "trainer_feedback_outcomes_quarantine": [],
        "accepted_count": 0,
        "current_cycle_accepted_count": 0,
        "open_position_count": 0,
        "closed_trade_count": 0,
        "outcome_label_count": 0,
        "trainer_feedback_row_count": 0,
        "trainer_feedback_quarantined_row_count": 0,
        "generated_utc": generated_utc,
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    return {
        "portfolio_state": portfolio_state,
        "paper_session": paper_session,
        "ledger": ledger,
        "heartbeat": heartbeat,
        "empty_list": [],
        "accepted_fills_file": accepted_fills_file,
        "lifecycle_file": lifecycle_file,
        "outcome_labels_file": {"outcome_labels": [], "new_outcome_labels": [], "generated_utc": generated_utc, "paper_only": True},
        "trainer_feedback_file": {
            "trainer_feedback_outcomes": [],
            "trainer_feedback_outcomes_quarantine": [],
            "generated_utc": generated_utc,
            "paper_only": True,
        },
    }


def _reset_key_plan(outcome_memory_keys: list[str]) -> dict[str, Any]:
    return {
        "fixed_reset_keys": list(RESET_FIXED_KEYS),
        "pattern_reset_keys": {"v2:paper:outcome_memory:*": outcome_memory_keys},
        "preserved_keys": list(PRESERVED_KEYS),
        "compatibility_aliases": [
            "v2:paper:positions",
            "v2:paper:outcome_labels",
            "v2:trainer:feedback:outcomes",
            "v2:trainer:feedback:outcomes:quarantine",
        ],
        "redis_trim_used": False,
        "old_redis_writes": False,
    }


def _write_reset_redis_state(client: Any, payloads: dict[str, Any]) -> dict[str, Any]:
    if client is None:
        return {"redis_available": False, "keys_written": [], "keys_deleted": [], "errors": ["REDIS_UNAVAILABLE"]}
    errors: list[str] = []
    keys_deleted: list[str] = []
    outcome_memory_keys = sorted(str(key) for key in client.scan_iter(match="v2:paper:outcome_memory:*", count=1000))
    for key in outcome_memory_keys:
        try:
            client.delete(key)
            keys_deleted.append(key)
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    writes = {
        "v2:portfolio:state": (payloads["portfolio_state"], PORTFOLIO_STATE_TTL_SECONDS),
        "v2:paper:session": (payloads["paper_session"], None),
        "v2:paper:ledger": (payloads["ledger"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:paper:closed_trades": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:paper:open_positions": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:paper:accepted_fills": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:paper:positions": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:paper:outcome_labels": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:trainer:feedback:outcomes": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:trainer:feedback:outcomes:quarantine": (payloads["empty_list"], PAPER_TRAINING_EVIDENCE_TTL_SECONDS),
        "v2:paper:heartbeat": (payloads["heartbeat"], PAPER_HEARTBEAT_TTL_SECONDS),
    }
    keys_written: list[str] = []
    for key, (payload, ttl) in writes.items():
        try:
            if ttl is None:
                client.set(key, json.dumps(payload, sort_keys=True, default=_json_default))
            else:
                client.setex(key, ttl, json.dumps(payload, sort_keys=True, default=_json_default))
            keys_written.append(key)
        except Exception as exc:
            errors.append(f"{key}: {exc}")
    return {
        "redis_available": True,
        "keys_written": keys_written,
        "keys_deleted": keys_deleted,
        "reset_key_plan": _reset_key_plan(outcome_memory_keys),
        "errors": errors,
    }


def _write_reset_local_files(payloads: dict[str, Any]) -> list[str]:
    file_payloads = {
        PAPER_ACCEPTED_FILLS_STATE_PATH: payloads["accepted_fills_file"],
        PAPER_LIFECYCLE_STATE_PATH: payloads["lifecycle_file"],
        PAPER_OUTCOME_LABELS_PATH: payloads["outcome_labels_file"],
        TRAINER_FEEDBACK_OUTCOMES_PATH: payloads["trainer_feedback_file"],
        PORTFOLIO_PUBLIC_PATH: payloads["portfolio_state"],
    }
    written: list[str] = []
    for path, payload in file_payloads.items():
        _write_json(path, payload)
        written.append(_relative_or_absolute(path))
    return written


def _systemctl(args: list[str]) -> dict[str, Any]:
    command = ["systemctl", "--user", *args]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _service_state(service_name: str) -> dict[str, Any]:
    result = _systemctl([
        "show",
        service_name,
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "MainPID",
        "-p",
        "ExecMainPID",
        "--no-pager",
    ])
    state: dict[str, Any] = {"service": service_name, **result}
    for line in str(result.get("stdout") or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            state[key] = value
    return state


def _paper_online_runtime_status() -> dict[str, Any]:
    services = ("paper_online_runtime.service", "ai-bot-v2-paper-online-runtime.service")
    statuses: dict[str, Any] = {}
    for service in services:
        result = _systemctl(["is-active", service])
        statuses[service] = {
            "active_state_text": result.get("stdout") or result.get("stderr"),
            "returncode": result.get("returncode"),
            "inactive": result.get("stdout") in {"inactive", "unknown", "failed"} or result.get("returncode") != 0,
        }
    return {
        "services": statuses,
        "all_inactive": all(status["inactive"] for status in statuses.values()),
    }


def _verification_payload(client: Any, reset_session_id: str) -> dict[str, Any]:
    portfolio = _decode_json(client.get("v2:portfolio:state")) if client is not None else {}
    session = _decode_json(client.get("v2:paper:session")) if client is not None else {}
    ledger = _decode_json(client.get("v2:paper:ledger")) if client is not None else {}
    closed = _decode_json(client.get("v2:paper:closed_trades")) if client is not None else []
    positions = _decode_json(client.get("v2:paper:positions")) if client is not None else []
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    session = session if isinstance(session, dict) else {}
    ledger = ledger if isinstance(ledger, dict) else {}
    canonical_state = _service_state(CANONICAL_PAPER_LOOP_SERVICE)
    online_runtime = _paper_online_runtime_status()
    paper_equity = _safe_float(portfolio.get("equity") or portfolio.get("current_session_equity"))
    open_positions = max(
        _safe_int(portfolio.get("open_positions_count")),
        len(_as_list(portfolio.get("open_positions"))),
        len(_as_list(positions)),
        len(_as_list(ledger.get("open_positions"))),
    )
    closed_trades = max(
        _safe_int(portfolio.get("closed_trades_count") or portfolio.get("closed_positions_count")),
        len(_as_list(closed)),
        len(_as_list(ledger.get("closed_trades"))),
    )
    live_gate = portfolio.get("live_gate") or portfolio.get("live_gate_status") or ledger.get("live_gate")
    places_real_order = bool(portfolio.get("places_real_order") or ledger.get("places_real_order"))
    pass_conditions = {
        "paper_equity_is_3000": paper_equity == RESET_INITIAL_CAPITAL,
        "open_positions_zero": open_positions == 0,
        "closed_trades_zero": closed_trades == 0,
        "paper_online_runtime_inactive": online_runtime["all_inactive"],
        "canonical_paper_loop_active": canonical_state.get("ActiveState") == "active",
        "live_gate_blocked": live_gate == "blocked_human_only",
        "places_real_order_false": places_real_order is False,
        "reset_session_id_matches": portfolio.get("reset_session_id") == reset_session_id,
        "paper_session_key_matches": session.get("paper_session_id") == reset_session_id,
        "paper_session_starting_equity_3000": _safe_float(session.get("starting_equity_usd")) == RESET_INITIAL_CAPITAL,
    }
    return {
        "schema_version": "paper_3000_reset_verification_status_v1",
        "generated_utc": _utc_iso(),
        "status": "PAPER_3000_RESET_VERIFIED" if all(pass_conditions.values()) else "PAPER_3000_RESET_VERIFICATION_BLOCKED",
        "reset_session_id": reset_session_id,
        "paper_equity": paper_equity,
        "open_positions": open_positions,
        "closed_trades": closed_trades,
        "paper_online_runtime": online_runtime,
        "canonical_paper_loop_service": canonical_state,
        "live_gate": live_gate,
        "places_real_order": places_real_order,
        "paper_session_key": session,
        "pass_conditions": pass_conditions,
        "paper_only": True,
        "routes_to_live": False,
    }


def _session_identity_status(reset_session_id: str, verification: dict[str, Any]) -> dict[str, Any]:
    pass_conditions = {
        "paper_session_id_required_for_new_rows": True,
        "starting_equity_required_for_new_rows": True,
        "old_open_positions_survive_reset": verification.get("open_positions") != 0,
        "old_trades_counted_in_new_session": verification.get("closed_trades") != 0,
        "old_btc_phantom_or_quarantined_rows_counted": False,
        "live_remains_blocked": verification.get("live_gate") == "blocked_human_only",
    }
    blocking_flags_clear = (
        pass_conditions["old_open_positions_survive_reset"] is False
        and pass_conditions["old_trades_counted_in_new_session"] is False
        and pass_conditions["old_btc_phantom_or_quarantined_rows_counted"] is False
    )
    return {
        "schema_version": "paper_3000_session_identity_status_v1",
        "generated_utc": _utc_iso(),
        "status": "PAPER_3000_SESSION_IDENTITY_READY" if blocking_flags_clear else "PAPER_3000_SESSION_IDENTITY_BLOCKED",
        "paper_session_id": reset_session_id,
        "reset_session_id": reset_session_id,
        "starting_equity_usd": RESET_INITIAL_CAPITAL,
        "required_new_row_fields": [
            "paper_session_id",
            "starting_equity_usd",
            "candidate_id",
            "policy_fingerprint",
            "model_source",
            "decision_time",
            "feature_cutoff",
            "available_at",
            "production_grade_cost",
            "paper_only",
            "routes_to_live",
            "places_real_order",
        ],
        "pass_conditions": pass_conditions,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _recovery_files(reset_session_id: str) -> list[str]:
    pending = GOAL_DIR / "paper_3000_recovery_pending.jsonl"
    closed = GOAL_DIR / "paper_3000_recovery_closed.jsonl"
    chain = GOAL_DIR / "paper_3000_recovery_hash_chain.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text("", encoding="utf-8")
    closed.write_text("", encoding="utf-8")
    _write_json(
        chain,
        {
            "schema_version": "paper_3000_recovery_hash_chain_v1",
            "generated_utc": _utc_iso(),
            "reset_session_id": reset_session_id,
            "starting_equity_usd": RESET_INITIAL_CAPITAL,
            "genesis_hash": hashlib.sha256(reset_session_id.encode("utf-8")).hexdigest(),
            "rows": [],
            "paper_only": True,
        },
    )
    return [_relative_or_absolute(pending), _relative_or_absolute(closed), _relative_or_absolute(chain)]


def run(*, operator_authorized_reset: bool, skip_systemctl: bool = False) -> dict[str, Any]:
    if not operator_authorized_reset:
        raise ValueError("operator_authorized_reset must be true for the paper $3,000 reset")
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp_slug()
    generated_utc = _utc_iso()
    reset_session_id = f"paper_3000_final_pre_live_{timestamp}"
    evidence_dir = RAW_EVIDENCE_ROOT / f"pre_3000_reset_{timestamp}"
    hashes: dict[str, str] = {}

    client = _connect_redis()
    redis_archive = _archive_redis(client, evidence_dir, hashes)
    http_archive = _archive_http(evidence_dir, hashes)
    file_archive = _archive_local_runtime_files(evidence_dir, hashes)
    _write_hashed_json(evidence_dir / "hashes.json", hashes, hashes)

    pre_reset_summary = _pre_reset_summary(
        evidence_dir=evidence_dir,
        redis_archive=redis_archive,
        http_archive=http_archive,
        file_archive=file_archive,
        hashes=hashes,
    )
    _write_json(GOAL_DIR / "pre_reset_evidence_freeze_status.json", pre_reset_summary)

    stop_result = {"skipped": True}
    if not skip_systemctl:
        stop_result = _systemctl(["stop", CANONICAL_PAPER_LOOP_SERVICE])

    reset_payloads = _build_reset_payloads(reset_session_id, generated_utc)
    redis_reset = _write_reset_redis_state(client, reset_payloads)
    local_files_written = _write_reset_local_files(reset_payloads)

    start_result = {"skipped": True}
    if not skip_systemctl:
        start_result = _systemctl(["start", CANONICAL_PAPER_LOOP_SERVICE])

    reset_status = {
        "schema_version": "operator_authorized_3000_paper_reset_status_v1",
        "generated_utc": _utc_iso(),
        "status": "PAPER_3000_RESET_WRITTEN" if not redis_reset.get("errors") else "PAPER_3000_RESET_WRITE_ERRORS",
        "operator_authorized_reset": True,
        "new_starting_equity_usd": RESET_INITIAL_CAPITAL,
        "reset_scope": "PAPER_ONLY",
        "live_account_untouched": True,
        "exchange_untouched": True,
        "historical_evidence_preserved": True,
        "raw_evidence_dir": _relative_or_absolute(evidence_dir),
        "reset_session_id": reset_session_id,
        "paper_session_id": reset_session_id,
        "systemctl_stop_result": stop_result,
        "systemctl_start_result": start_result,
        "redis_reset": redis_reset,
        "local_runtime_files_written": local_files_written,
        "preserved_keys": list(PRESERVED_KEYS),
        "no_real_orders": True,
        "no_test_orders": True,
        "no_cancel_modify": True,
        "no_exchange_leverage_mutation": True,
        "no_exchange_margin_mode_mutation": True,
        "no_transfers_or_withdrawals": True,
        "no_redis_trim": True,
        "no_old_redis_writes": True,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }
    _write_json(GOAL_DIR / "operator_authorized_3000_paper_reset_status.json", reset_status)

    verification = _verification_payload(client, reset_session_id)
    _write_json(GOAL_DIR / "paper_3000_reset_verification_status.json", verification)
    session_identity = _session_identity_status(reset_session_id, verification)
    _write_json(GOAL_DIR / "paper_3000_session_identity_status.json", session_identity)
    recovery_files = _recovery_files(reset_session_id)

    result = {
        "pre_reset_evidence_freeze_status": pre_reset_summary,
        "operator_authorized_3000_paper_reset_status": reset_status,
        "paper_3000_reset_verification_status": verification,
        "paper_3000_session_identity_status": session_identity,
        "recovery_files": recovery_files,
    }
    _write_json(GOAL_DIR / "paper_3000_reset_run_result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive and reset V2 paper state to $3,000")
    parser.add_argument(
        "--operator-authorized-reset",
        action="store_true",
        help="Required acknowledgement for the paper-only $3,000 reset.",
    )
    parser.add_argument(
        "--skip-systemctl",
        action="store_true",
        help="Testing only: skip canonical paper-loop stop/start.",
    )
    args = parser.parse_args()
    result = run(
        operator_authorized_reset=args.operator_authorized_reset,
        skip_systemctl=args.skip_systemctl,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
