"""V2 signal publisher.

Broadcasts V2 signal-lineage evidence to V2-only consumers. This worker
does not route to execution, does not write legacy Redis, does not call
exchange APIs, and keeps live blocked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_signal_publisher"
SOURCE_RUNTIME_ID = "v2_signal_lineage_worker"
LIVE_GATE_STATUS = "blocked_human_only"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
LEGACY_ACTIVE_SYMBOL_SOURCE = "legacy_config.py_SYMBOLS_current_25"
CODEX_REVIEW_TRIGGER = "codex_review_v2_signal_publisher"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_SIGNAL_PUBLISHER"
DEFAULT_WARN_THRESHOLD_SECONDS = 120
DEFAULT_STALE_THRESHOLD_SECONDS = 600
CONSUMERS: Tuple[str, ...] = ("webhook", "gui", "admin_ai")
LEGACY_SOURCE_PATHS: Tuple[str, ...] = (
    "legacy_reference/rl/hybrid_trainer.py",
    "legacy_reference/trading/signal_router.py",
    "legacy_reference/rl/signal_state_manager.py",
    "legacy_reference/rl/orchestrator_worker.py",
    "legacy_reference/monitor_trainer_signals.py",
)
REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
    "signals_published_total",
    "consumer_count",
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
    "route_to_execution",
    "execution_route_enabled",
    "consumer_envelopes",
    "published_targets",
    "codex_review_trigger",
    "live_gate",
)

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / WORKER_ID / "latest"
WORKER_STATUS_DIR = (
    REPO_ROOT / "claude_worklog" / "final_readiness" / "emergency_v2_runtime_migration" / "latest" / "workers"
)
PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"
SOURCE_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / SOURCE_RUNTIME_ID / "latest" / f"{SOURCE_RUNTIME_ID}_status.json",
    WORKER_STATUS_DIR / f"{SOURCE_RUNTIME_ID}_status.json",
    WORKER_STATUS_DIR / "v2_orchestrator_adapter_status.json",
]
SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    V2_ROOT / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_ts(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def freshness_seconds(value: Any) -> Optional[int]:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))


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


def load_symbol_payload() -> Tuple[Dict[str, Any], str]:
    for path in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if path.exists():
            data = _read_json(path)
            return (data if isinstance(data, dict) else {}), _rel(path)
    return {}, ""


def build_symbol_scope(source_payload: Mapping[str, Any], observed_symbols: List[str]) -> Dict[str, Any]:
    symbol_payload, symbol_path = load_symbol_payload()
    source = symbol_payload or source_payload
    legacy_seed = _as_symbol_list(source.get("legacy_active_symbols") or LEGACY_ACTIVE_SYMBOLS_25)
    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
    discovered = _as_symbol_list(source.get("discovered_symbols") or source.get("symbols_discovered"))
    dynamic_discovered = _as_symbol_list(
        source.get("dynamic_discovered_symbols") or source.get("dynamic_symbols") or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(source.get("training_symbols"))
    paper_symbols = _as_symbol_list(source.get("paper_symbols"))
    binance_confirmed = _as_symbol_list(
        source.get("binance_usdm_confirmed_symbols") or source.get("binance_usdm_tradable_symbols")
    )
    live_blocked = _as_symbol_list(source.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(set(binance_confirmed or dynamic_discovered or discovered or observed_symbols or service.legacy_active_symbols()))
    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": symbol_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": "PRESENT" if symbol_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD",
        "legacy_active_symbols": service.legacy_active_symbols(),
        "legacy_active_symbol_source": LEGACY_ACTIVE_SYMBOL_SOURCE,
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


def load_source_payload(source_file: Optional[str]) -> Tuple[Optional[Dict[str, Any]], str, str]:
    paths = [Path(source_file)] if source_file else SOURCE_PAYLOAD_CANDIDATES
    for path in paths:
        if path.exists():
            data = _read_json(path)
            if isinstance(data, dict):
                return data, _rel(path), "PRESENT"
            return None, _rel(path), "INVALID_PAYLOAD"
    return None, "", "MISSING_RUNTIME_EVIDENCE"


def source_generated_at(payload: Mapping[str, Any]) -> Any:
    return payload.get("last_run_ts") or payload.get("generated_at") or payload.get("codex_review_emitted_at")


def extract_signal_identity(payload: Mapping[str, Any]) -> Dict[str, Any]:
    record = payload.get("signal_lineage_record")
    if not isinstance(record, dict):
        record = payload.get("decision_record")
    if not isinstance(record, dict):
        record = payload
    symbol = str(record.get("symbol") or payload.get("symbol") or "").upper()
    prediction_id = str(record.get("prediction_id") or payload.get("prediction_id") or "")
    feature_snapshot_id = str(record.get("feature_snapshot_id") or payload.get("feature_snapshot_id") or "")
    decision_id = str(record.get("decision_id") or payload.get("decision_id") or "")
    decision_action = str(record.get("decision_action") or payload.get("decision_action") or "")
    decision_reason_code = str(record.get("decision_reason_code") or payload.get("decision_reason_code") or "")
    return {
        "signal_id": decision_id or prediction_id or f"signal_{now_ms()}",
        "symbol": symbol,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "decision_id": decision_id,
        "decision_action": decision_action,
        "decision_reason_code": decision_reason_code,
    }


def make_consumer_envelopes(identity: Mapping[str, Any], run_ts: str, source_path: str) -> List[Dict[str, Any]]:
    envelopes = []
    for consumer in CONSUMERS:
        envelopes.append(
            {
                "consumer": consumer,
                "signal_id": identity["signal_id"],
                "symbol": identity["symbol"],
                "prediction_id": identity["prediction_id"],
                "feature_snapshot_id": identity["feature_snapshot_id"],
                "decision_id": identity["decision_id"],
                "decision_action": identity["decision_action"],
                "decision_reason_code": identity["decision_reason_code"],
                "route_to_execution": False,
                "execution_route_enabled": False,
                "live_gate": LIVE_GATE_STATUS,
                "source_payload_path": source_path,
                "published_at": run_ts,
            }
        )
    return envelopes


def build_status(args: argparse.Namespace) -> Dict[str, Any]:
    run_ts = iso_now()
    warn_threshold = max(1, int(getattr(args, "warn_threshold_seconds", DEFAULT_WARN_THRESHOLD_SECONDS)))
    stale_threshold = max(warn_threshold + 1, int(getattr(args, "stale_threshold_seconds", DEFAULT_STALE_THRESHOLD_SECONDS)))
    payload, source_path, load_status = load_source_payload(getattr(args, "source_file", None))
    age = freshness_seconds(source_generated_at(payload or {})) if isinstance(payload, dict) else None
    observed_symbols: List[str] = []
    if isinstance(payload, dict):
        identity_for_symbols = extract_signal_identity(payload)
        if identity_for_symbols.get("symbol"):
            observed_symbols = [str(identity_for_symbols["symbol"])]
    symbol_scope = build_symbol_scope(payload or {}, observed_symbols)
    fail_closed = load_status != "PRESENT"
    fail_reason = "" if not fail_closed else load_status.lower()
    runtime_status = load_status
    envelopes: List[Dict[str, Any]] = []
    identity: Dict[str, Any] = {
        "signal_id": "",
        "symbol": "",
        "prediction_id": "",
        "feature_snapshot_id": "",
        "decision_id": "",
        "decision_action": "",
        "decision_reason_code": "",
    }
    if payload is not None:
        if payload.get("fail_closed") is True:
            fail_closed = True
            fail_reason = "upstream_fail_closed"
            runtime_status = "UPSTREAM_FAIL_CLOSED"
        elif age is None:
            fail_closed = True
            fail_reason = "source_freshness_missing"
            runtime_status = "SOURCE_FRESHNESS_MISSING"
        elif age > stale_threshold:
            fail_closed = True
            fail_reason = "source_stale"
            runtime_status = "SOURCE_STALE"
        identity = extract_signal_identity(payload)
        missing_identity = [k for k in ("signal_id", "symbol", "prediction_id") if not identity.get(k)]
        if missing_identity:
            fail_closed = True
            fail_reason = "missing_signal_identity:" + ",".join(missing_identity)
            runtime_status = "MISSING_SIGNAL_IDENTITY"
        if not fail_closed:
            envelopes = make_consumer_envelopes(identity, run_ts, source_path)
    status: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_ts,
        "source_payload_path": source_path,
        "source_runtime_id": SOURCE_RUNTIME_ID,
        "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "live_blocked": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "old_redis_write_performed": False,
        "legacy_mutation_performed": False,
        "route_to_execution": False,
        "execution_route_enabled": False,
        "publisher_never_routes_to_real_execution": True,
        "fail_closed": bool(fail_closed),
        "fail_closed_reason": fail_reason,
        "missing_runtime_evidence": bool(fail_closed),
        "runtime_evidence_status": runtime_status,
        "freshness_seconds": age,
        "warn_threshold_seconds": warn_threshold,
        "stale_threshold_seconds": stale_threshold,
        "signals_published_total": len(envelopes),
        "consumer_count": len(CONSUMERS),
        "consumers": list(CONSUMERS),
        "consumer_envelopes": envelopes,
        "published_targets": [f"consumers/{item['consumer']}_signal.json" for item in envelopes],
        "codex_review_trigger": CODEX_REVIEW_TRIGGER,
        "codex_review_emitted_at": run_ts,
        **identity,
    }
    status.update(symbol_scope)
    return status


def write_status(status: Mapping[str, Any]) -> None:
    for directory in (PUBLIC_RUNTIME_DIR, LOCAL_RUNTIME_DIR, WORKER_STATUS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    body = json.dumps(status, indent=2, sort_keys=True)
    for path in (PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, WORKER_STATUS_FILE):
        path.write_text(body + "\n")
    for base in (PUBLIC_RUNTIME_DIR, LOCAL_RUNTIME_DIR):
        consumer_dir = base / "consumers"
        consumer_dir.mkdir(parents=True, exist_ok=True)
        for envelope in status.get("consumer_envelopes", []):
            if isinstance(envelope, dict):
                (consumer_dir / f"{envelope['consumer']}_signal.json").write_text(
                    json.dumps(envelope, indent=2, sort_keys=True) + "\n"
                )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--source-file", default=None)
    parser.add_argument("--warn-threshold-seconds", type=int, default=DEFAULT_WARN_THRESHOLD_SECONDS)
    parser.add_argument("--stale-threshold-seconds", type=int, default=DEFAULT_STALE_THRESHOLD_SECONDS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    status = build_status(args)
    if not getattr(args, "no_write", False):
        write_status(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.once:
        status = run_once(args)
        return 0 if not status.get("fail_closed") else 2
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception:
            pass
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
