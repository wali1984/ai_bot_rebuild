"""Standalone V2 config/admin manager.

Publishes fail-closed runtime setting records. Dangerous settings remain staged
and require explicit human approval; this worker never creates approval tokens.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from v2.backend.app.services.config_admin.service import (
    apply_staged_changes,
    default_settings,
    load_staged_changes,
    summarize_settings,
    utc_now,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_config_admin_manager"
LIVE_GATE_STATUS = "blocked_human_only"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
LEGACY_ACTIVE_SYMBOL_SOURCE = "v2_symbol_universe_service:legacy_config.py_SYMBOLS_current_25"
CODEX_REVIEW_TRIGGER = "codex_review_v2_config_admin_manager"

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
    "settings_tracked_total",
    "settings_by_risk_class",
    "dangerous_settings_pending_approval",
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


def build_symbol_scope() -> Dict[str, Any]:
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
        live_blocked = sorted(set(dynamic_discovered or discovered or service.legacy_active_symbols()))
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
        "observed_symbols": [],
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


def build_status(*, staged_changes_path: Optional[Path] = None) -> Dict[str, Any]:
    settings = default_settings()
    settings = apply_staged_changes(settings, load_staged_changes(staged_changes_path))
    summary = summarize_settings(settings)
    payload: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": utc_now(),
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "live_blocked": True,
        "freshness_seconds": 0,
        "approval_token_created": False,
        "approval_token_self_creatable": False,
        "final_live_approval_token_absent_required": True,
        "old_redis_write": False,
        "exchange_action_taken": False,
        "leverage_or_margin_change": False,
        "secrets_written_to_payload": False,
        "codex_review_trigger": CODEX_REVIEW_TRIGGER,
    }
    payload.update(summary)
    payload.update(build_symbol_scope())
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
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--staged-changes", default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if not args.once and not args.loop:
        args.once = True
    return args


def run_once(*, staged_changes_path: Optional[Path] = None, write: bool = True) -> Dict[str, Any]:
    status = build_status(staged_changes_path=staged_changes_path)
    if write:
        write_status(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    staged_changes_path = Path(args.staged_changes) if args.staged_changes else None
    if args.once:
        run_once(staged_changes_path=staged_changes_path, write=not args.no_write)
        return 0
    while True:
        try:
            run_once(staged_changes_path=staged_changes_path, write=not args.no_write)
        except KeyboardInterrupt:
            return 0
        except Exception:
            pass
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
