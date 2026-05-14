"""V2 replay/backtest worker — standalone CLI worker.

Lifts the V2 composition runtime
``v2.backend.app.composition.replay_backtest_runner.runtime`` into a
standalone CLI. The worker consumes ``PaperExecutionLedgerEntry``
records (emitted by ``v2_paper_execution_worker``), filters them by a
replay window ``[--window-start-ms, --window-end-ms]``, sorts them
chronologically, and produces:

  * a ``ReplayBacktestRun`` (replay or backtest mode)
  * a tuple of ``ReplayBacktestStep`` records
  * a ``ReplayBacktestSummary``

Hard rules (asserted by tests):
  - The replay path never calls a real exchange. No Binance / ccxt /
    Redis imports; no exchange-mutation method names.
  - Replay output is scoped to ``operator_runtime/v2_replay_worker/``
    and ``v2/runtime/v2_replay_worker/``. Replay output NEVER overwrites
    ``operator_runtime/paper_online/`` (invariant
    ``REPLAY_OUTPUT_NEVER_OVERWRITES_PAPER_ONLINE``).
  - On missing/invalid input or an empty replay window the worker
    fail-closes with a structured status payload and returns rc 2.
  - The live gate is permanently ``blocked_human_only``.
  - Symbol scope is read via the V2 Symbol Universe service. The
    25-symbol legacy active subset is exposed as
    ``legacy_active_symbols``; it is not treated as the full universe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from v2.backend.app.composition.replay_backtest_runner import (
    build_replay_backtest_runner,
)
from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import (
    RUN_MODE_BACKTEST,
    RUN_MODE_REPLAY,
    ReplayBacktestRun,
    ReplayBacktestStep,
    ReplayBacktestSummary,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_replay_worker"
LIVE_GATE_STATUS = "blocked_human_only"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_REPLAY_WORKER"
REPLAY_OUTPUT_INVARIANT = "REPLAY_OUTPUT_NEVER_OVERWRITES_PAPER_ONLINE"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
UPSTREAM_PAPER_EXECUTION_WORKER_ID = "v2_paper_execution_worker"

DEFAULT_RUN_MODE = RUN_MODE_REPLAY
DEFAULT_WARN_THRESHOLD_SECONDS = 600
DEFAULT_STALE_THRESHOLD_SECONDS = 7 * 24 * 3600

PAPER_ONLINE_FORBIDDEN_FRAGMENT = "operator_runtime/paper_online/"

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

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"

SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
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

PAPER_LEDGER_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / UPSTREAM_PAPER_EXECUTION_WORKER_ID
    / "latest"
    / f"{UPSTREAM_PAPER_EXECUTION_WORKER_ID}_status.json",
]

LEGACY_SOURCE_PATHS: List[str] = [
    "legacy_reference/scripts/replay_sanity_check.py",
    "legacy_reference/rl/scripts/replay_decision.py",
    "legacy_reference/rl/replay_store.py",
    "legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py",
    "legacy_reference/rl/historical_data_loader.py",
]

REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
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
    "source_payload_path",
    "source_payload_kind",
    "legacy_source_paths",
    "live_blocked",
    "replay_run_id",
    "run_mode",
    "replay_symbol",
    "window_start_ms",
    "window_end_ms",
    "run_started_ts_ms",
    "run_ended_ts_ms",
    "entries_total_count",
    "entries_in_window_count",
    "entries_filtered_outside_window_count",
    "entries_rejected_invalid_count",
    "replay_steps",
    "replay_steps_count",
    "replay_summary",
    "replay_output_path_invariant",
    "replay_output_paths",
    "replay_output_paths_must_not_contain_paper_online",
    "stale_threshold_seconds",
    "warn_threshold_seconds",
    "content_hash",
    "symbol_universe_contract",
    "symbol_universe_source_path",
    "symbol_universe_public_payload_status",
    "legacy_active_symbols",
    "legacy_active_symbol_source",
    "legacy_active_symbols_public_payload_status",
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
    "legacy_fetch_executions_index_preserved",
    "executions_by_signal_id",
    "executions_by_signal_id_count",
    "executions_unindexed_count",
)


# ---------------------------------------------------------------------------
# clocks / io helpers
# ---------------------------------------------------------------------------


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in payload.items() if k not in ("last_run_ts", "content_hash")},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# symbol universe scope
# ---------------------------------------------------------------------------


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


def build_symbol_scope(*, observed_symbols: List[str]) -> Dict[str, Any]:
    public_payload, public_path = _load_symbol_universe_public_payload()
    legacy_seed = _as_symbol_list(LEGACY_ACTIVE_SYMBOLS_25)
    public_legacy_active = _as_symbol_list(public_payload.get("legacy_active_symbols"))
    public_legacy_active_status = "NOT_PROVIDED"
    if public_legacy_active:
        public_legacy_active_status = (
            "MATCHES_CANONICAL_LEGACY_25"
            if public_legacy_active == legacy_seed
            else "PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED"
        )
    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
    discovered = _as_symbol_list(
        public_payload.get("discovered_symbols")
        or public_payload.get("symbols_discovered")
    )
    if not discovered:
        discovered = sorted(
            {
                identity.canonical_symbol_id.upper()
                for identity in service.all_discovered_symbols()
                if getattr(identity, "canonical_symbol_id", None)
            }
        )
    dynamic_discovered = _as_symbol_list(
        public_payload.get("dynamic_discovered_symbols") or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(public_payload.get("training_symbols"))
    paper_symbols = _as_symbol_list(public_payload.get("paper_symbols"))
    binance_confirmed = _as_symbol_list(
        public_payload.get("binance_usdm_confirmed_symbols")
        or public_payload.get("binance_usdm_tradable_symbols")
    )
    live_blocked = _as_symbol_list(public_payload.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(
            set(
                dynamic_discovered
                or discovered
                or observed_symbols
                or service.legacy_active_symbols()
            )
        )
    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": public_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": (
            "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
        ),
        "legacy_active_symbols": service.legacy_active_symbols(),
        "legacy_active_symbol_source": "v2_symbol_universe_service:legacy_config.py_SYMBOLS_current_25",
        "legacy_active_symbols_public_payload_status": public_legacy_active_status,
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
# paper ledger loading
# ---------------------------------------------------------------------------


def _entry_from_dict(record: Mapping[str, Any]) -> PaperExecutionLedgerEntry:
    return PaperExecutionLedgerEntry(
        paper_trade_id=str(record["paper_trade_id"]),
        risk_decision_id=str(record["risk_decision_id"]),
        decision_id=str(record["decision_id"]),
        prediction_id=str(record["prediction_id"]),
        feature_snapshot_id=str(record["feature_snapshot_id"]),
        symbol=str(record["symbol"]),
        ledger_entry_ts_ms=int(record["ledger_entry_ts_ms"]),
        ledger_action=str(record["ledger_action"]),
        ledger_reason_code=str(record["ledger_reason_code"]),
        input_risk_action=str(record["input_risk_action"]),
        input_risk_reason_code=str(record["input_risk_reason_code"]),
        live_blocked=True,
    )


def _paper_execution_status_to_entry_dict(
    record: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    paper_trade_id = str(record.get("last_paper_trade_id") or "")
    if not paper_trade_id:
        return None
    if not record.get("symbol"):
        return None
    try:
        ts_ms = int(record.get("last_paper_trade_ts_ms") or 0)
    except (TypeError, ValueError):
        return None
    if ts_ms <= 0:
        return None
    return {
        "paper_trade_id": paper_trade_id,
        "risk_decision_id": str(record.get("last_risk_decision_id") or ""),
        "decision_id": str(record.get("decision_id") or ""),
        "prediction_id": str(record.get("prediction_id") or ""),
        "feature_snapshot_id": str(record.get("feature_snapshot_id") or ""),
        "symbol": str(record.get("symbol") or ""),
        "ledger_entry_ts_ms": ts_ms,
        "ledger_action": str(record.get("ledger_action") or ""),
        "ledger_reason_code": str(record.get("ledger_reason_code") or ""),
        "input_risk_action": str(record.get("input_risk_action") or ""),
        "input_risk_reason_code": str(record.get("input_risk_reason_code") or ""),
        "live_blocked": True,
    }


def _extract_entries_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    if isinstance(payload, dict):
        items = payload.get("paper_ledger_entries")
        if isinstance(items, list):
            return [e for e in items if isinstance(e, dict)]
        items = payload.get("entries")
        if isinstance(items, list):
            return [e for e in items if isinstance(e, dict)]
        if payload.get("worker_id") == UPSTREAM_PAPER_EXECUTION_WORKER_ID:
            single = _paper_execution_status_to_entry_dict(payload)
            return [single] if single else []
    return []


def _collect_paper_ledger_entries(
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], str, str, str]:
    """Return (entries, source_payload_path, source_kind, status).

    status in {"present", "missing", "load_failed"}.
    """
    if args.source_file:
        path = Path(args.source_file)
        if not path.exists():
            return [], str(path), "explicit_source_file", "missing"
        data = _read_json(path)
        if data is None:
            return [], str(path), "explicit_source_file", "load_failed"
        entries = _extract_entries_from_payload(data)
        return entries, str(path), "explicit_source_file", "present"
    for candidate in PAPER_LEDGER_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            if data is None:
                continue
            entries = _extract_entries_from_payload(data)
            try:
                rel = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(candidate)
            return entries, rel, "paper_execution_worker_public_payload", "present"
    return [], "", "missing", "missing"


def _load_paper_ledger_entries_from_source(
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], str, str, str]:
    return _collect_paper_ledger_entries(args)


# ---------------------------------------------------------------------------
# window filter + replay execution
# ---------------------------------------------------------------------------


def _filter_entries_to_window(
    entries: List[Dict[str, Any]],
    *,
    symbol: str,
    window_start_ms: int,
    window_end_ms: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Return (in_window_sorted, outside_window_count, invalid_count).

    Each entry must declare ``ledger_entry_ts_ms`` and ``symbol``.
    Entries with an unparseable timestamp or non-matching symbol are
    counted as ``invalid_count`` and are not retained.
    """
    in_window: List[Dict[str, Any]] = []
    outside = 0
    invalid = 0
    for entry in entries:
        ts_raw = entry.get("ledger_entry_ts_ms")
        try:
            ts_ms = int(ts_raw) if ts_raw is not None else None
        except (TypeError, ValueError):
            invalid += 1
            continue
        entry_symbol = str(entry.get("symbol") or "").upper()
        if not entry_symbol or entry_symbol != symbol:
            invalid += 1
            continue
        if ts_ms is None:
            invalid += 1
            continue
        if ts_ms < window_start_ms or ts_ms > window_end_ms:
            outside += 1
            continue
        normalised = dict(entry)
        normalised["symbol"] = entry_symbol
        normalised["ledger_entry_ts_ms"] = ts_ms
        in_window.append(normalised)
    in_window.sort(key=lambda e: int(e["ledger_entry_ts_ms"]))
    return in_window, outside, invalid


def _entry_signal_id(entry: Mapping[str, Any]) -> str:
    for key in ("signal_id", "source_signal_id", "decision_id", "risk_decision_id", "prediction_id"):
        raw = entry.get(key)
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def _index_executions_by_signal_id(
    entries: List[Dict[str, Any]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], int]:
    index: Dict[str, List[Dict[str, Any]]] = {}
    unindexed = 0
    for entry in entries:
        signal_id = _entry_signal_id(entry)
        if not signal_id:
            unindexed += 1
            continue
        index.setdefault(signal_id, []).append(
            {
                "paper_trade_id": str(entry.get("paper_trade_id") or ""),
                "ledger_entry_ts_ms": int(entry.get("ledger_entry_ts_ms") or 0),
                "ledger_action": str(entry.get("ledger_action") or ""),
                "ledger_reason_code": str(entry.get("ledger_reason_code") or ""),
            }
        )
    for signal_id in list(index):
        index[signal_id].sort(
            key=lambda item: (
                int(item.get("ledger_entry_ts_ms") or 0),
                str(item.get("paper_trade_id") or ""),
            )
        )
    return {key: index[key] for key in sorted(index)}, unindexed


def _now_ms_clock() -> int:
    return now_ms()


def _execute_replay(
    *,
    replay_run: ReplayBacktestRun,
    entries: List[Dict[str, Any]],
) -> Tuple[Tuple[ReplayBacktestStep, ...], ReplayBacktestSummary]:
    runner = build_replay_backtest_runner(now_ms_clock=_now_ms_clock)
    steps: List[ReplayBacktestStep] = []
    for entry_dict in entries:
        ledger_entry = _entry_from_dict(entry_dict)
        step = runner.assemble_step(
            paper_ledger_entry=ledger_entry,
            replay_run=replay_run,
        )
        steps.append(step)
    steps_tuple = tuple(steps)
    summary = runner.assemble_summary(replay_run=replay_run, steps=steps_tuple)
    return steps_tuple, summary


def _step_to_dict(step: ReplayBacktestStep) -> Dict[str, Any]:
    return {
        "replay_step_id": step.replay_step_id,
        "replay_run_id": step.replay_run_id,
        "paper_trade_id": step.paper_trade_id,
        "risk_decision_id": step.risk_decision_id,
        "decision_id": step.decision_id,
        "prediction_id": step.prediction_id,
        "feature_snapshot_id": step.feature_snapshot_id,
        "symbol": step.symbol,
        "step_ts_ms": int(step.step_ts_ms),
        "step_action": step.step_action,
        "step_reason_code": step.step_reason_code,
        "input_paper_action": step.input_paper_action,
        "input_paper_reason_code": step.input_paper_reason_code,
        "live_blocked": bool(step.live_blocked),
    }


def _summary_to_dict(summary: ReplayBacktestSummary) -> Dict[str, Any]:
    return {
        "replay_summary_id": summary.replay_summary_id,
        "replay_run_id": summary.replay_run_id,
        "summary_emitted_ts_ms": int(summary.summary_emitted_ts_ms),
        "total_steps_count": int(summary.total_steps_count),
        "record_allow_steps_count": int(summary.record_allow_steps_count),
        "record_deny_steps_count": int(summary.record_deny_steps_count),
        "mirror_allow_proceed_long_steps_count": int(
            summary.mirror_allow_proceed_long_steps_count
        ),
        "mirror_allow_proceed_short_steps_count": int(
            summary.mirror_allow_proceed_short_steps_count
        ),
        "mirror_deny_orchestrator_held_steps_count": int(
            summary.mirror_deny_orchestrator_held_steps_count
        ),
        "mirror_deny_orchestrator_abstained_steps_count": int(
            summary.mirror_deny_orchestrator_abstained_steps_count
        ),
        "mirror_deny_default_steps_count": int(
            summary.mirror_deny_default_steps_count
        ),
        "live_blocked": bool(summary.live_blocked),
    }


# ---------------------------------------------------------------------------
# status payload + safe write
# ---------------------------------------------------------------------------


def _replay_output_paths() -> List[str]:
    def _repo_relative(path: Path) -> str:
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            return str(path)

    return [
        _repo_relative(PUBLIC_STATUS_FILE),
        _repo_relative(LOCAL_STATUS_FILE),
        _repo_relative(WORKER_STATUS_FILE),
    ]


def _assert_replay_output_paths_not_paper_online(paths: List[str]) -> None:
    for path in paths:
        if PAPER_ONLINE_FORBIDDEN_FRAGMENT in path:
            raise RuntimeError(
                f"{REPLAY_OUTPUT_INVARIANT}: refusing to write replay output to "
                f"a paper_online-scoped path: {path}"
            )


def write_status(status: Mapping[str, Any]) -> None:
    paths = [PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, WORKER_STATUS_FILE]
    _assert_replay_output_paths_not_paper_online([str(p) for p in paths])
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(status, indent=2, sort_keys=True, default=str)
    for target in paths:
        target.write_text(body)


def build_status_payload(
    *,
    run_started_ts: str,
    args: argparse.Namespace,
    source_payload_path: str,
    source_payload_kind: str,
    entries_total_count: int,
    entries_in_window_count: int,
    entries_filtered_outside_window_count: int,
    entries_rejected_invalid_count: int,
    replay_steps: List[Dict[str, Any]],
    replay_summary: Dict[str, Any],
    executions_by_signal_id: Mapping[str, List[Dict[str, Any]]],
    executions_unindexed_count: int,
    fail_closed: bool,
    fail_closed_reason: str,
    missing_runtime_evidence: bool,
    runtime_evidence_status: str,
    freshness_seconds: Optional[int],
    symbol_scope: Mapping[str, Any],
) -> Dict[str, Any]:
    output_paths = _replay_output_paths()
    must_not_contain = [PAPER_ONLINE_FORBIDDEN_FRAGMENT not in p for p in output_paths]
    payload: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "fail_closed": bool(fail_closed),
        "fail_closed_reason": fail_closed_reason,
        "missing_runtime_evidence": bool(missing_runtime_evidence),
        "runtime_evidence_status": runtime_evidence_status,
        "freshness_seconds": freshness_seconds,
        "source_payload_path": source_payload_path,
        "source_payload_kind": source_payload_kind,
        "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
        "live_blocked": True,
        "replay_run_id": str(args.replay_run_id),
        "run_mode": str(args.run_mode),
        "replay_symbol": str(args.symbol),
        "window_start_ms": int(args.window_start_ms),
        "window_end_ms": int(args.window_end_ms),
        "run_started_ts_ms": int(args.window_start_ms),
        "run_ended_ts_ms": int(args.window_end_ms),
        "entries_total_count": int(entries_total_count),
        "entries_in_window_count": int(entries_in_window_count),
        "entries_filtered_outside_window_count": int(
            entries_filtered_outside_window_count
        ),
        "entries_rejected_invalid_count": int(entries_rejected_invalid_count),
        "replay_steps": list(replay_steps),
        "replay_steps_count": len(replay_steps),
        "replay_summary": dict(replay_summary),
        "legacy_fetch_executions_index_preserved": True,
        "executions_by_signal_id": dict(executions_by_signal_id),
        "executions_by_signal_id_count": len(executions_by_signal_id),
        "executions_unindexed_count": int(executions_unindexed_count),
        "replay_output_path_invariant": REPLAY_OUTPUT_INVARIANT,
        "replay_output_paths": list(output_paths),
        "replay_output_paths_must_not_contain_paper_online": all(must_not_contain),
        "stale_threshold_seconds": int(
            getattr(args, "stale_threshold_seconds", DEFAULT_STALE_THRESHOLD_SECONDS)
        ),
        "warn_threshold_seconds": int(
            getattr(args, "warn_threshold_seconds", DEFAULT_WARN_THRESHOLD_SECONDS)
        ),
    }
    payload.update(symbol_scope)
    payload["content_hash"] = _content_hash(payload)
    return payload


# ---------------------------------------------------------------------------
# main run loop
# ---------------------------------------------------------------------------


def _empty_summary(replay_run_id: str) -> Dict[str, Any]:
    return {
        "replay_summary_id": "",
        "replay_run_id": replay_run_id,
        "summary_emitted_ts_ms": 0,
        "total_steps_count": 0,
        "record_allow_steps_count": 0,
        "record_deny_steps_count": 0,
        "mirror_allow_proceed_long_steps_count": 0,
        "mirror_allow_proceed_short_steps_count": 0,
        "mirror_deny_orchestrator_held_steps_count": 0,
        "mirror_deny_orchestrator_abstained_steps_count": 0,
        "mirror_deny_default_steps_count": 0,
        "live_blocked": True,
    }


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_started_ts = iso_now()
    symbol = str(args.symbol or "").upper()
    args.symbol = symbol

    entries, source_path, source_kind, load_status = _load_paper_ledger_entries_from_source(
        args
    )
    symbol_scope = build_symbol_scope(observed_symbols=[symbol] if symbol else [])
    empty_summary = _empty_summary(str(args.replay_run_id))
    empty_execution_index: Dict[str, List[Dict[str, Any]]] = {}

    if load_status == "missing":
        status = build_status_payload(
            run_started_ts=run_started_ts,
            args=args,
            source_payload_path=source_path,
            source_payload_kind=source_kind,
            entries_total_count=0,
            entries_in_window_count=0,
            entries_filtered_outside_window_count=0,
            entries_rejected_invalid_count=0,
            replay_steps=[],
            replay_summary=empty_summary,
            executions_by_signal_id=empty_execution_index,
            executions_unindexed_count=0,
            fail_closed=True,
            fail_closed_reason="no_paper_ledger_source_found",
            missing_runtime_evidence=True,
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            freshness_seconds=None,
            symbol_scope=symbol_scope,
        )
        write_status(status)
        return status

    if load_status == "load_failed":
        status = build_status_payload(
            run_started_ts=run_started_ts,
            args=args,
            source_payload_path=source_path,
            source_payload_kind=source_kind,
            entries_total_count=0,
            entries_in_window_count=0,
            entries_filtered_outside_window_count=0,
            entries_rejected_invalid_count=0,
            replay_steps=[],
            replay_summary=empty_summary,
            executions_by_signal_id=empty_execution_index,
            executions_unindexed_count=0,
            fail_closed=True,
            fail_closed_reason="paper_ledger_source_invalid_json",
            missing_runtime_evidence=True,
            runtime_evidence_status="INVALID_PAPER_LEDGER_ENTRY",
            freshness_seconds=None,
            symbol_scope=symbol_scope,
        )
        write_status(status)
        return status

    in_window, outside_count, invalid_count = _filter_entries_to_window(
        entries,
        symbol=symbol,
        window_start_ms=int(args.window_start_ms),
        window_end_ms=int(args.window_end_ms),
    )

    if args.paper_trade_id:
        in_window = [
            e for e in in_window if str(e.get("paper_trade_id")) == str(args.paper_trade_id)
        ]
        if not in_window:
            status = build_status_payload(
                run_started_ts=run_started_ts,
                args=args,
                source_payload_path=source_path,
                source_payload_kind=source_kind,
                entries_total_count=len(entries),
                entries_in_window_count=0,
                entries_filtered_outside_window_count=outside_count,
                entries_rejected_invalid_count=invalid_count,
                replay_steps=[],
                replay_summary=empty_summary,
                executions_by_signal_id=empty_execution_index,
                executions_unindexed_count=0,
                fail_closed=True,
                fail_closed_reason="paper_trade_id_not_in_window",
                missing_runtime_evidence=True,
                runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
                freshness_seconds=None,
                symbol_scope=symbol_scope,
            )
            write_status(status)
            return status

    if not in_window:
        status = build_status_payload(
            run_started_ts=run_started_ts,
            args=args,
            source_payload_path=source_path,
            source_payload_kind=source_kind,
            entries_total_count=len(entries),
            entries_in_window_count=0,
            entries_filtered_outside_window_count=outside_count,
            entries_rejected_invalid_count=invalid_count,
            replay_steps=[],
            replay_summary=empty_summary,
            executions_by_signal_id=empty_execution_index,
            executions_unindexed_count=0,
            fail_closed=True,
            fail_closed_reason="no_paper_ledger_entries_in_window",
            missing_runtime_evidence=True,
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            freshness_seconds=None,
            symbol_scope=symbol_scope,
        )
        write_status(status)
        return status

    # Newest entry's age — used to surface staleness without fail-closing,
    # because replay/backtest may legitimately walk historical windows.
    latest_ts_ms = int(in_window[-1]["ledger_entry_ts_ms"])
    freshness_seconds = max(0, int((now_ms() - latest_ts_ms) / 1000))

    try:
        replay_run = ReplayBacktestRun(
            replay_run_id=str(args.replay_run_id),
            run_mode=str(args.run_mode),
            symbol=symbol,
            run_started_ts_ms=int(args.window_start_ms),
            run_ended_ts_ms=int(args.window_end_ms),
            live_blocked=True,
        )
    except Exception as exc:  # noqa: BLE001 — domain validators raise their own type
        status = build_status_payload(
            run_started_ts=run_started_ts,
            args=args,
            source_payload_path=source_path,
            source_payload_kind=source_kind,
            entries_total_count=len(entries),
            entries_in_window_count=len(in_window),
            entries_filtered_outside_window_count=outside_count,
            entries_rejected_invalid_count=invalid_count,
            replay_steps=[],
            replay_summary=empty_summary,
            executions_by_signal_id=empty_execution_index,
            executions_unindexed_count=0,
            fail_closed=True,
            fail_closed_reason=f"replay_run_rejected: {exc.__class__.__name__}",
            missing_runtime_evidence=True,
            runtime_evidence_status="INVALID_REPLAY_RUN",
            freshness_seconds=freshness_seconds,
            symbol_scope=symbol_scope,
        )
        write_status(status)
        return status

    try:
        steps_tuple, summary = _execute_replay(
            replay_run=replay_run, entries=in_window
        )
    except Exception as exc:  # noqa: BLE001 — domain/service rejections
        status = build_status_payload(
            run_started_ts=run_started_ts,
            args=args,
            source_payload_path=source_path,
            source_payload_kind=source_kind,
            entries_total_count=len(entries),
            entries_in_window_count=len(in_window),
            entries_filtered_outside_window_count=outside_count,
            entries_rejected_invalid_count=invalid_count + len(in_window),
            replay_steps=[],
            replay_summary=empty_summary,
            executions_by_signal_id=empty_execution_index,
            executions_unindexed_count=0,
            fail_closed=True,
            fail_closed_reason=(
                f"paper_ledger_entry_rejected: {exc.__class__.__name__}"
            ),
            missing_runtime_evidence=False,
            runtime_evidence_status="INVALID_PAPER_LEDGER_ENTRY",
            freshness_seconds=freshness_seconds,
            symbol_scope=symbol_scope,
        )
        write_status(status)
        return status

    steps_dicts = [_step_to_dict(step) for step in steps_tuple]
    summary_dict = _summary_to_dict(summary)
    executions_by_signal_id, executions_unindexed_count = _index_executions_by_signal_id(
        in_window
    )
    status = build_status_payload(
        run_started_ts=run_started_ts,
        args=args,
        source_payload_path=source_path,
        source_payload_kind=source_kind,
        entries_total_count=len(entries),
        entries_in_window_count=len(in_window),
        entries_filtered_outside_window_count=outside_count,
        entries_rejected_invalid_count=invalid_count,
        replay_steps=steps_dicts,
        replay_summary=summary_dict,
        executions_by_signal_id=executions_by_signal_id,
        executions_unindexed_count=executions_unindexed_count,
        fail_closed=False,
        fail_closed_reason="",
        missing_runtime_evidence=False,
        runtime_evidence_status="PRESENT",
        freshness_seconds=freshness_seconds,
        symbol_scope=symbol_scope,
    )
    write_status(status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--replay-run-id",
        required=True,
        help="identifier for this replay/backtest run",
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="uppercase canonical symbol id, e.g. BTCUSDT",
    )
    parser.add_argument(
        "--window-start-ms",
        type=int,
        required=True,
        help="inclusive window start (ms since epoch)",
    )
    parser.add_argument(
        "--window-end-ms",
        type=int,
        required=True,
        help="inclusive window end (ms since epoch)",
    )
    parser.add_argument(
        "--run-mode",
        choices=(RUN_MODE_REPLAY, RUN_MODE_BACKTEST),
        default=DEFAULT_RUN_MODE,
        help="replay or backtest",
    )
    parser.add_argument(
        "--source-file",
        default=None,
        help=(
            "Path to a paper-ledger JSON file. If omitted, the worker reads "
            "the v2_paper_execution_worker public payload."
        ),
    )
    parser.add_argument(
        "--paper-trade-id",
        default=None,
        help=(
            "Replay a single paper_trade_id within the window (legacy "
            "replay_decision.py-style narrow replay)."
        ),
    )
    parser.add_argument(
        "--warn-threshold-seconds",
        type=int,
        default=DEFAULT_WARN_THRESHOLD_SECONDS,
    )
    parser.add_argument(
        "--stale-threshold-seconds",
        type=int,
        default=DEFAULT_STALE_THRESHOLD_SECONDS,
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--interval", type=int, default=60, help="seconds between loop iterations"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="dry-run; do not write the public payload",
    )
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    if int(args.window_end_ms) < int(args.window_start_ms):
        parser.error("--window-end-ms must be >= --window-start-ms")
    args.symbol = str(args.symbol).upper()
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.no_write:
        global write_status

        def _skip(_status: Mapping[str, Any]) -> None:
            return None

        write_status = _skip  # type: ignore[assignment]
    if args.once:
        status = run_once(args)
        return 0 if not status.get("fail_closed") else 2
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception:  # noqa: BLE001 — the loop must not crash
            pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
