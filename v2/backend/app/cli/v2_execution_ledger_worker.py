"""V2 execution ledger worker — standalone CLI worker.

Subscribes to the ``v2_paper_execution_worker`` public status payload
and appends each accepted paper event to a durable, **append-only**
JSONL ledger at
``v2/runtime/v2_execution_ledger_worker/latest/paper_events.jsonl``.
The worker exposes a tail of the last ``N`` events via its
``public_runtime`` payload.

Hard rules (asserted by tests):
  - **Append-only.** The ledger file is opened only in append mode.
    Pre-existing lines are never rewritten, truncated, or modified.
    A re-run against the same upstream record is a no-op (dedup by
    ``event_id``).
  - **Action set.** Only ``input_risk_action`` in ``{"allow","deny"}``
    is accepted. Any other action causes a fail-closed status and no
    append.
  - **Fail-closed on unwritable directory.** If the ledger directory or
    file is not writable, the worker emits a fail-closed status and
    appends nothing.
  - **Live gate.** The live gate is permanently ``blocked_human_only``.
    There is no codepath that opens it.
  - **No exchange call.** The worker source contains no
    exchange-mutation method names, no Binance/ccxt/Redis imports, and
    no Redis-writer calls.
  - **Symbol Universe contract.** Symbol scope is read via the V2
    Symbol Universe service; the 25-symbol legacy active subset is
    surfaced as ``legacy_active_symbols`` and is not treated as the
    full universe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_execution_ledger_worker"
SOURCE_WORKER_ID = "v2_paper_execution_worker"
LIVE_GATE_STATUS = "blocked_human_only"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_LEDGER_WORKER"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"

ACCEPTED_ACTIONS: Tuple[str, ...] = ("allow", "deny")
DEFAULT_TAIL_SIZE = 20

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = (
    V2_ROOT / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
)
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / WORKER_ID / "latest"
WORKER_STATUS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "emergency_v2_runtime_migration"
    / "latest"
    / "workers"
)

LEDGER_DIR = LOCAL_RUNTIME_DIR
LEDGER_FILE = LEDGER_DIR / "paper_events.jsonl"

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"

PAPER_STATUS_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / SOURCE_WORKER_ID
    / "latest"
    / f"{SOURCE_WORKER_ID}_status.json",
]
SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
    V2_ROOT
    / "frontend"
    / "public"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
]

LEGACY_PAPER_SOURCE_PATHS: List[str] = [
    "legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py",
    "legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py",
    "legacy_reference/PAPER_TRADER_COMPLETE.md",
    "legacy_reference/trading/base_executor.py",
    "legacy_reference/trading/trader.py",
    "legacy_reference/config.py",
    "legacy_reference/monitor_trader_execution.py",
]

REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
    "ledger_file_path",
    "ledger_path_writable",
    "entries_appended_this_run",
    "entries_total",
    "duplicate_skipped",
    "last_appended_event_id",
    "last_appended_ts",
    "last_appended_ts_ms",
    "tail_size",
    "tail",
    "live_gate",
    "current_gate_state",
    "current_gate_state_must_equal_blocked_human_only",
    "gate_always_blocked_invariant",
    "exchange_call_invariant",
    "exchange_action_taken",
    "fail_closed",
    "fail_closed_reason",
    "missing_runtime_evidence",
    "runtime_evidence_status",
    "freshness_seconds",
    "input_risk_action",
    "input_risk_action_accepted_set",
    "input_action_rejected_reason",
    "source_payload_path",
    "source_worker_id",
    "legacy_paper_source_paths",
    "live_blocked",
    "symbol_universe_contract",
    "symbol_universe_source_path",
    "symbol_universe_public_payload_status",
    "legacy_active_symbols",
    "legacy_active_symbol_source",
    "discovered_symbols",
    "dynamic_discovered_symbols",
    "dynamic_symbol_sources",
    "observed_symbols",
    "training_symbols",
    "paper_symbols",
    "live_symbols",
    "live_blocked_symbols",
    "live_symbol_policy",
    "passive_monitor_all_discovered_symbols",
    "train_all_discovered_symbols",
    "trade_all_discovered_symbols",
    "binance_usdm_confirmed_symbols",
    "symbol_selection_score_factors",
)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_from_ms(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def freshness_seconds_from_ms(ts_ms: Optional[int]) -> Optional[int]:
    if not ts_ms:
        return None
    return max(0, int((now_ms() - int(ts_ms)) / 1000))


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        items: List[Any] = [value]
    elif isinstance(value, list):
        items = list(value)
    else:
        return []
    out: List[str] = []
    for raw in items:
        if isinstance(raw, dict):
            raw = (
                raw.get("canonical_symbol_id")
                or raw.get("symbol")
                or raw.get("legacy_symbol")
            )
        text = str(raw or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            try:
                rel_str = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel_str = str(candidate)
            return (data if isinstance(data, dict) else {}), rel_str
    return {}, None


def build_symbol_scope(
    *,
    observed_symbols: List[str],
    input_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    overrides = input_overrides or {}
    public_payload, public_path = _load_symbol_universe_public_payload()
    source_payload: Dict[str, Any] = public_payload if public_payload else overrides

    legacy_seed = _as_symbol_list(
        source_payload.get("legacy_active_symbols")
        or overrides.get("legacy_active_symbols")
        or LEGACY_ACTIVE_SYMBOLS_25
    )
    universe_service = SymbolUniverseService(legacy_active_symbols=legacy_seed)

    discovered = _as_symbol_list(
        source_payload.get("discovered_symbols")
        or source_payload.get("symbols_discovered")
        or source_payload.get("all_discovered_symbols")
    )
    if not discovered:
        discovered = sorted(
            {
                identity.canonical_symbol_id.upper()
                for identity in universe_service.all_discovered_symbols()
                if getattr(identity, "canonical_symbol_id", None)
            }
        )
    dynamic_discovered = _as_symbol_list(
        source_payload.get("dynamic_discovered_symbols")
        or source_payload.get("dynamic_symbols")
        or overrides.get("dynamic_discovered_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)

    training_symbols = _as_symbol_list(
        source_payload.get("training_symbols") or overrides.get("training_symbols")
    )
    paper_symbols = _as_symbol_list(
        source_payload.get("paper_symbols") or overrides.get("paper_symbols")
    )
    binance_confirmed = _as_symbol_list(
        source_payload.get("binance_usdm_confirmed_symbols")
        or source_payload.get("binance_usdm_tradable_symbols")
    )
    live_blocked = _as_symbol_list(
        source_payload.get("live_blocked_symbols")
        or overrides.get("live_blocked_symbols")
    )
    if not live_blocked:
        live_blocked = sorted(
            set(
                dynamic_discovered
                or discovered
                or observed_symbols
                or universe_service.legacy_active_symbols()
            )
        )

    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": public_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": (
            "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
        ),
        "legacy_active_symbols": universe_service.legacy_active_symbols(),
        "legacy_active_symbol_source": "legacy_config.py_SYMBOLS_current_25",
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": _as_symbol_list(observed_symbols),
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "coinank_symbols_tradability": (
            "market_intelligence_only_until_binance_usdm_confirmed"
        ),
        "symbol_scope_policy": (
            "do_not_train_or_trade_all_discovered_symbols_automatically"
        ),
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "live_symbol_policy": "none_live_blocked_human_only",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


# ---------------------------------------------------------------------------
# upstream paper status loading
# ---------------------------------------------------------------------------


def load_paper_status(
    args: argparse.Namespace,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Return (paper_status_dict_or_None, source_payload_path, status).

    status ∈ {"present", "missing", "load_failed"}.
    """
    if args.source_file:
        path = Path(args.source_file)
        if not path.exists():
            return None, str(path), "missing"
        data = _read_json(path)
        if not isinstance(data, dict):
            return None, str(path), "load_failed"
        return data, str(path), "present"
    for candidate in PAPER_STATUS_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            if not isinstance(data, dict):
                continue
            try:
                rel_str = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel_str = str(candidate)
            return data, rel_str, "present"
    return None, "", "missing"


# ---------------------------------------------------------------------------
# append-only ledger I/O
# ---------------------------------------------------------------------------


def _ensure_ledger_writable(file_path: Path) -> Tuple[bool, str]:
    """Try to make the ledger file writable in append mode without
    truncating or rewriting it. Returns (writable, reason_if_not).
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"ledger_dir_unwritable: {exc.__class__.__name__}: {exc}"
    try:
        with file_path.open("a", encoding="utf-8") as _fh:
            pass
    except OSError as exc:
        return False, f"ledger_file_unwritable: {exc.__class__.__name__}: {exc}"
    return True, ""


def _read_existing_event_ids(file_path: Path) -> Set[str]:
    if not file_path.exists():
        return set()
    out: Set[str] = set()
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    eid = row.get("event_id")
                    if isinstance(eid, str) and eid:
                        out.add(eid)
    except OSError:
        return set()
    return out


def _count_ledger_lines(file_path: Path) -> int:
    if not file_path.exists():
        return 0
    count = 0
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


def _tail_ledger(file_path: Path, n: int) -> List[Dict[str, Any]]:
    if not file_path.exists() or n <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows[-n:]


def _append_event(file_path: Path, event: Dict[str, Any]) -> None:
    """Append a single event line to the ledger file. Open mode is
    strictly append; existing bytes are never overwritten.
    """
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
    with file_path.open("a", encoding="utf-8") as fh:
        fh.write(encoded + "\n")


# ---------------------------------------------------------------------------
# event construction
# ---------------------------------------------------------------------------


def _build_event(
    paper_status: Dict[str, Any], source_payload_path: str
) -> Dict[str, Any]:
    fill = paper_status.get("simulated_fill") or {}
    paper_trade_id = str(paper_status.get("last_paper_trade_id") or "")
    risk_decision_id = str(paper_status.get("last_risk_decision_id") or "")
    return {
        "event_id": paper_trade_id,
        "event_ts": iso_now(),
        "event_ts_ms": now_ms(),
        "source_worker_id": SOURCE_WORKER_ID,
        "source_payload_path": source_payload_path,
        "input_risk_action": str(paper_status.get("input_risk_action") or ""),
        "input_risk_reason_code": str(
            paper_status.get("input_risk_reason_code") or ""
        ),
        "ledger_action": str(paper_status.get("ledger_action") or ""),
        "ledger_reason_code": str(paper_status.get("ledger_reason_code") or ""),
        "symbol": str(paper_status.get("symbol") or ""),
        "risk_decision_id": risk_decision_id,
        "decision_id": str(paper_status.get("decision_id") or ""),
        "prediction_id": str(paper_status.get("prediction_id") or ""),
        "feature_snapshot_id": str(paper_status.get("feature_snapshot_id") or ""),
        "paper_trade_id": paper_trade_id,
        "paper_trade_ts_ms": int(paper_status.get("last_paper_trade_ts_ms") or 0),
        "fill_recorded": bool(fill.get("fill_recorded") or False),
        "side": str(fill.get("side") or "none"),
        "notional_usdt": float(fill.get("notional_usdt") or 0.0),
        "fee_usdt": float(fill.get("fee_usdt") or 0.0),
        "slippage_bps": float(fill.get("slippage_bps") or 0.0),
        "live_gate": LIVE_GATE_STATUS,
        "exchange_action_taken": False,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
    }


def _content_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# status payload builders
# ---------------------------------------------------------------------------


def _ledger_file_rel(file_path: Path) -> str:
    try:
        return str(file_path.relative_to(REPO_ROOT))
    except ValueError:
        return str(file_path)


def build_fail_closed_status(
    *,
    reason: str,
    runtime_evidence_status: str,
    source_payload_path: str,
    run_started_ts: str,
    paper_status: Optional[Dict[str, Any]],
    symbol_scope: Dict[str, Any],
    ledger_writable: Optional[bool],
    input_action_rejected_reason: str,
    entries_total: int,
    tail: List[Dict[str, Any]],
    tail_size: int,
) -> Dict[str, Any]:
    input_action = ""
    paper_ts_ms: Optional[int] = None
    if paper_status:
        input_action = str(paper_status.get("input_risk_action") or "")
        try:
            paper_ts_ms = (
                int(paper_status.get("last_paper_trade_ts_ms") or 0) or None
            )
        except (TypeError, ValueError):
            paper_ts_ms = None
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "ledger_file_path": _ledger_file_rel(LEDGER_FILE),
        "ledger_path_writable": (
            True if ledger_writable is True else False if ledger_writable is False else False
        ),
        "entries_appended_this_run": 0,
        "entries_total": entries_total,
        "duplicate_skipped": False,
        "last_appended_event_id": "",
        "last_appended_ts": "",
        "last_appended_ts_ms": 0,
        "tail_size": tail_size,
        "tail": tail,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "fail_closed": True,
        "fail_closed_reason": reason,
        "missing_runtime_evidence": True,
        "runtime_evidence_status": runtime_evidence_status,
        "freshness_seconds": freshness_seconds_from_ms(paper_ts_ms),
        "input_risk_action": input_action,
        "input_risk_action_accepted_set": list(ACCEPTED_ACTIONS),
        "input_action_rejected_reason": input_action_rejected_reason,
        "source_payload_path": source_payload_path,
        "source_worker_id": SOURCE_WORKER_ID,
        "legacy_paper_source_paths": list(LEGACY_PAPER_SOURCE_PATHS),
        "live_blocked": True,
        **symbol_scope,
    }


def build_success_status(
    *,
    run_started_ts: str,
    source_payload_path: str,
    paper_status: Dict[str, Any],
    event: Dict[str, Any],
    appended_this_run: int,
    duplicate_skipped: bool,
    entries_total: int,
    tail: List[Dict[str, Any]],
    tail_size: int,
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    paper_ts_ms = int(paper_status.get("last_paper_trade_ts_ms") or 0) or None
    last_appended_ts_ms = int(event["event_ts_ms"]) if appended_this_run else 0
    last_appended_ts = iso_from_ms(last_appended_ts_ms) if last_appended_ts_ms else ""
    status = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "ledger_file_path": _ledger_file_rel(LEDGER_FILE),
        "ledger_path_writable": True,
        "entries_appended_this_run": appended_this_run,
        "entries_total": entries_total,
        "duplicate_skipped": duplicate_skipped,
        "last_appended_event_id": event["event_id"] if appended_this_run else "",
        "last_appended_ts": last_appended_ts,
        "last_appended_ts_ms": last_appended_ts_ms,
        "tail_size": tail_size,
        "tail": tail,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "fail_closed": False,
        "fail_closed_reason": "",
        "missing_runtime_evidence": False,
        "runtime_evidence_status": "PRESENT",
        "freshness_seconds": freshness_seconds_from_ms(paper_ts_ms),
        "input_risk_action": event["input_risk_action"],
        "input_risk_action_accepted_set": list(ACCEPTED_ACTIONS),
        "input_action_rejected_reason": "",
        "source_payload_path": source_payload_path,
        "source_worker_id": SOURCE_WORKER_ID,
        "legacy_paper_source_paths": list(LEGACY_PAPER_SOURCE_PATHS),
        "live_blocked": True,
        "event": event,
        **symbol_scope,
    }
    status["content_hash"] = _content_hash(
        {k: v for k, v in status.items() if k != "last_run_ts"}
    )
    return status


def write_status(status: Dict[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(payload)
    LOCAL_STATUS_FILE.write_text(payload)
    WORKER_STATUS_FILE.write_text(payload)


# ---------------------------------------------------------------------------
# main run loop
# ---------------------------------------------------------------------------


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_started_ts = iso_now()
    paper_status, source_path, load_status = load_paper_status(args)

    observed: List[str] = []
    if (
        paper_status
        and isinstance(paper_status.get("symbol"), str)
        and paper_status["symbol"]
    ):
        observed = [paper_status["symbol"]]
    symbol_scope = build_symbol_scope(observed_symbols=observed)

    tail_size = max(0, int(getattr(args, "tail_size", DEFAULT_TAIL_SIZE)))
    pre_tail = _tail_ledger(LEDGER_FILE, tail_size)
    pre_total = _count_ledger_lines(LEDGER_FILE)

    if load_status == "missing":
        status = build_fail_closed_status(
            reason="no_paper_execution_source_found",
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            paper_status=None,
            symbol_scope=symbol_scope,
            ledger_writable=None,
            input_action_rejected_reason="",
            entries_total=pre_total,
            tail=pre_tail,
            tail_size=tail_size,
        )
        write_status(status)
        return status

    if load_status == "load_failed":
        status = build_fail_closed_status(
            reason="paper_execution_source_unreadable_or_invalid_json",
            runtime_evidence_status="INVALID_PAYLOAD",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            paper_status=None,
            symbol_scope=symbol_scope,
            ledger_writable=None,
            input_action_rejected_reason="",
            entries_total=pre_total,
            tail=pre_tail,
            tail_size=tail_size,
        )
        write_status(status)
        return status

    assert paper_status is not None

    # Propagate upstream fail-closed state.
    upstream_missing = bool(paper_status.get("missing_runtime_evidence"))
    upstream_evidence_status = str(paper_status.get("runtime_evidence_status") or "")
    if upstream_missing or upstream_evidence_status != "PRESENT":
        status = build_fail_closed_status(
            reason="upstream_paper_execution_worker_reports_missing_or_invalid_evidence",
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            paper_status=paper_status,
            symbol_scope=symbol_scope,
            ledger_writable=None,
            input_action_rejected_reason="",
            entries_total=pre_total,
            tail=pre_tail,
            tail_size=tail_size,
        )
        write_status(status)
        return status

    # Action-set rejection.
    input_action = str(paper_status.get("input_risk_action") or "")
    if input_action not in ACCEPTED_ACTIONS:
        rejected_reason = (
            f"input_risk_action_outside_accepted_set: got={input_action!r} "
            f"accepted={list(ACCEPTED_ACTIONS)!r}"
        )
        status = build_fail_closed_status(
            reason=rejected_reason,
            runtime_evidence_status="INVALID_ACTION",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            paper_status=paper_status,
            symbol_scope=symbol_scope,
            ledger_writable=None,
            input_action_rejected_reason=rejected_reason,
            entries_total=pre_total,
            tail=pre_tail,
            tail_size=tail_size,
        )
        write_status(status)
        return status

    # Ledger writability gate.
    writable, write_reason = _ensure_ledger_writable(LEDGER_FILE)
    if not writable:
        status = build_fail_closed_status(
            reason=write_reason,
            runtime_evidence_status="UNWRITABLE_LEDGER_DIR",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            paper_status=paper_status,
            symbol_scope=symbol_scope,
            ledger_writable=False,
            input_action_rejected_reason="",
            entries_total=pre_total,
            tail=pre_tail,
            tail_size=tail_size,
        )
        write_status(status)
        return status

    event = _build_event(paper_status, source_path)
    if not event["event_id"]:
        status = build_fail_closed_status(
            reason="paper_status_missing_paper_trade_id_event_id",
            runtime_evidence_status="INVALID_PAYLOAD",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            paper_status=paper_status,
            symbol_scope=symbol_scope,
            ledger_writable=True,
            input_action_rejected_reason="",
            entries_total=pre_total,
            tail=pre_tail,
            tail_size=tail_size,
        )
        write_status(status)
        return status

    existing_ids = _read_existing_event_ids(LEDGER_FILE)
    duplicate = event["event_id"] in existing_ids
    appended_this_run = 0
    if not duplicate:
        _append_event(LEDGER_FILE, event)
        appended_this_run = 1

    entries_total = _count_ledger_lines(LEDGER_FILE)
    tail = _tail_ledger(LEDGER_FILE, tail_size)

    status = build_success_status(
        run_started_ts=run_started_ts,
        source_payload_path=source_path,
        paper_status=paper_status,
        event=event,
        appended_this_run=appended_this_run,
        duplicate_skipped=duplicate,
        entries_total=entries_total,
        tail=tail,
        tail_size=tail_size,
        symbol_scope=symbol_scope,
    )
    status["live_gate"] = LIVE_GATE_STATUS
    status["current_gate_state"] = LIVE_GATE_STATUS
    status["gate_always_blocked_invariant"] = True
    status["exchange_call_invariant"] = EXCHANGE_CALL_INVARIANT
    write_status(status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--source-file",
        default=None,
        help=(
            "JSON file shaped like v2_paper_execution_worker_status.json; "
            "if omitted, the worker reads the public status payload of "
            "v2_paper_execution_worker."
        ),
    )
    parser.add_argument(
        "--tail-size",
        type=int,
        default=DEFAULT_TAIL_SIZE,
        help="number of most recent events to surface in the public payload tail",
    )
    parser.add_argument("--once", action="store_true", help="run a single iteration and exit")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument(
        "--interval", type=int, default=30, help="seconds between loop iterations"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="dry-run; do not write any payload or ledger line to disk",
    )
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.no_write:
        global write_status, _append_event

        def _skip_status(_status: Dict[str, Any]) -> None:
            return None

        def _skip_append(_file_path: Path, _event: Dict[str, Any]) -> None:
            return None

        write_status = _skip_status  # type: ignore[assignment]
        _append_event = _skip_append  # type: ignore[assignment]
    if args.once:
        status = run_once(args)
        if status.get("missing_runtime_evidence") or status.get("fail_closed_reason"):
            return 0 if (
                status.get("runtime_evidence_status") == "PRESENT"
            ) else 2
        return 0
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 — loop must not crash
            try:
                symbol_scope = build_symbol_scope(observed_symbols=[])
                fail = build_fail_closed_status(
                    reason=f"loop_iteration_failed: {exc}",
                    runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
                    source_payload_path="",
                    run_started_ts=iso_now(),
                    paper_status=None,
                    symbol_scope=symbol_scope,
                    ledger_writable=None,
                    input_action_rejected_reason="",
                    entries_total=_count_ledger_lines(LEDGER_FILE),
                    tail=_tail_ledger(LEDGER_FILE, DEFAULT_TAIL_SIZE),
                    tail_size=DEFAULT_TAIL_SIZE,
                )
                write_status(fail)
            except Exception:
                pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
