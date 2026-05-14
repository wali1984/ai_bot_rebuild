"""Standalone V2 script monitor worker.

Monitors V2 worker scripts and public payloads without executing legacy code.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from v2.backend.app.services.monitor_runner import (
    collect_script_statuses,
    summarize_statuses,
    utc_now,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_script_monitor"
LIVE_GATE_STATUS = "blocked_human_only"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
LEGACY_ACTIVE_SYMBOL_SOURCE = "v2_symbol_universe_service:legacy_config.py_SYMBOLS_current_25"
CODEX_REVIEW_TRIGGER = "codex_review_v2_script_monitor"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / WORKER_ID / "latest"
WORKER_STATUS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "emergency_v2_runtime_migration"
    / "latest"
    / "workers"
)
PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"
SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    V2_ROOT / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]

REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
    "scripts_enumerated_total",
    "scripts_by_status",
    "scripts_broken",
    "scripts_unused",
    "alerts_generated",
    "freshness_seconds",
    "symbol_universe_contract",
    "symbol_universe_source_path",
    "legacy_active_symbols",
    "discovered_symbols",
    "observed_symbols",
    "training_symbols",
    "paper_symbols",
    "live_blocked_symbols",
    "binance_usdm_confirmed_symbols",
    "legacy_active_symbol_source",
    "dynamic_discovered_symbols",
    "dynamic_symbol_sources",
    "live_symbols",
    "passive_monitor_all_discovered_symbols",
    "train_all_discovered_symbols",
    "trade_all_discovered_symbols",
    "live_symbol_policy",
    "symbol_selection_score_factors",
)


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        items: Iterable[Any] = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    out: List[str] = []
    for raw in items:
        if isinstance(raw, dict):
            raw = raw.get("canonical_symbol_id") or raw.get("symbol") or raw.get("legacy_symbol")
        text = str(raw or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def _load_symbol_payload() -> Tuple[Dict[str, Any], str]:
    for path in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if path.exists():
            data = _read_json(path)
            return (data if isinstance(data, dict) else {}), _rel(path)
    return {}, ""


def build_symbol_scope(observed_symbols: List[str]) -> Dict[str, Any]:
    payload, payload_path = _load_symbol_payload()
    canonical_legacy = _as_symbol_list(LEGACY_ACTIVE_SYMBOLS_25)
    public_legacy = _as_symbol_list(payload.get("legacy_active_symbols"))
    public_legacy_status = "NOT_PROVIDED"
    if public_legacy:
        public_legacy_status = (
            "MATCHES_CANONICAL_LEGACY_25"
            if public_legacy == canonical_legacy
            else "PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED"
        )
    service = SymbolUniverseService(legacy_active_symbols=canonical_legacy)
    discovered = _as_symbol_list(payload.get("discovered_symbols") or payload.get("symbols_discovered"))
    dynamic_discovered = _as_symbol_list(payload.get("dynamic_discovered_symbols") or discovered)
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(payload.get("training_symbols"))
    paper_symbols = _as_symbol_list(payload.get("paper_symbols"))
    binance_confirmed = _as_symbol_list(
        payload.get("binance_usdm_confirmed_symbols") or payload.get("binance_usdm_tradable_symbols")
    )
    live_blocked = _as_symbol_list(payload.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(set(dynamic_discovered or discovered or observed_symbols or service.legacy_active_symbols()))
    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": payload_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": "PRESENT" if payload_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD",
        "legacy_active_symbols": service.legacy_active_symbols(),
        "legacy_active_symbol_source": LEGACY_ACTIVE_SYMBOL_SOURCE,
        "legacy_active_symbols_public_payload_status": public_legacy_status,
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": _as_symbol_list(observed_symbols),
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "coinank_symbols_tradability": "market_intelligence_only_until_binance_usdm_confirmed",
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "live_symbol_policy": "none_live_blocked_human_only",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def _freshness_seconds(statuses: Mapping[str, Any]) -> Optional[int]:
    latest: Optional[dt.datetime] = None
    for script in statuses.get("scripts", []):
        if not isinstance(script, dict):
            continue
        value = script.get("last_run") or script.get("last_success") or script.get("last_failure")
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError:
            continue
        latest = parsed if latest is None or parsed > latest else latest
    if latest is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - latest).total_seconds()))


def build_status() -> Dict[str, Any]:
    statuses = summarize_statuses(collect_script_statuses(repo_root=REPO_ROOT))
    observed_symbols: List[str] = []
    symbol_scope = build_symbol_scope(observed_symbols)
    payload: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": utc_now(),
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "live_blocked": True,
        "legacy_scripts_executed": False,
        "legacy_script_execution_policy": "forbidden_static_v2_inspection_only",
        "old_redis_write": False,
        "exchange_action_taken": False,
        "leverage_or_margin_change": False,
        "codex_review_trigger": CODEX_REVIEW_TRIGGER,
        "freshness_seconds": _freshness_seconds(statuses),
    }
    payload.update(statuses)
    payload.update(symbol_scope)
    return payload


def write_status(status: Mapping[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(status, indent=2, sort_keys=True, default=str)
    for target in (PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, WORKER_STATUS_FILE):
        target.write_text(body)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if not args.once and not args.loop:
        args.once = True
    return args


def run_once(*, write: bool = True) -> Dict[str, Any]:
    status = build_status()
    if write:
        write_status(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.once:
        run_once(write=not args.no_write)
        return 0
    while True:
        try:
            run_once(write=not args.no_write)
        except KeyboardInterrupt:
            return 0
        except Exception:
            pass
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
