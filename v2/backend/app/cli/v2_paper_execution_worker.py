"""V2 paper execution worker — standalone CLI worker.

Consumes ``RiskDecisionRecord`` events from a V2-namespaced source (a
direct JSON dict, a list under ``risk_decisions``, or the bridge format
emitted by ``v2_risk_gateway_runtime_worker``) and stamps
``PaperExecutionLedgerEntry`` rows via
``v2.backend.app.services.paper_execution_ledger.assemble_paper_execution_ledger_entry``
through the existing composition runtime
(``v2.backend.app.composition.paper_execution_ledger.build_paper_execution_ledger_recorder``).

Hard rules (asserted by tests):
  - The paper path never calls a real exchange. The worker source
    contains no ``create`` / ``cancel`` exchange-mutation method names,
    no Binance/ccxt/Redis imports, and no Redis-writer calls.
  - The live gate is permanently ``blocked_human_only``. There is no
    codepath that opens it.
  - On missing input (legacy bot shut down, no risk-gateway public
    payload yet), the worker classifies inputs as
    ``MISSING_RUNTIME_EVIDENCE`` and fail-closes rather than
    synthesising data.
  - Symbol scope is read via the V2 Symbol Universe service; the
    25-symbol legacy active subset is exposed as
    ``legacy_active_symbols`` and is not treated as the full universe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.composition.paper_execution_ledger import (
    build_paper_execution_ledger_recorder,
)
from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    PaperExecutionLedgerServiceError,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_paper_execution_worker"
LIVE_GATE_STATUS = "blocked_human_only"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_PAPER_PATH"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
UPSTREAM_RISK_GATEWAY_WORKER_ID = "v2_risk_gateway_runtime_worker"

# Legacy fee anchors — sourced from `legacy_reference/trading/trader.py`
# lines 2269-2275 (maker=0.0002, taker=0.0005). The V2 paper recorder
# reuses these constants but does not call any exchange to discover
# per-symbol rates.
FEE_RATE_MAKER_DEFAULT = 0.0002
FEE_RATE_TAKER_DEFAULT = 0.0005
# V2 default notional (intentionally lower than legacy BASE_NOTIONAL=500.0
# from legacy_reference/config.py:1894; see LEGACY_BASELINE_ANALYSIS).
BASE_NOTIONAL_USDT_DEFAULT = 100.0
# Local paper account baseline for this one-shot worker payload. This is
# not live equity and is only used to expose deterministic paper PnL.
PAPER_EQUITY_START_USDT = 10_000.0
# Conservative bps stand-in until the per-symbol slippage model is ported
# from legacy_reference/trading/execution_engine.py SlippageTracker.
DEFAULT_SLIPPAGE_BPS = 5.0

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

SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    V2_ROOT / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]

RISK_DECISION_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_risk_gateway_runtime_worker"
    / "latest"
    / "v2_risk_gateway_runtime_worker_status.json",
]

LEGACY_PAPER_SOURCE_PATHS: List[str] = [
    "legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py",
    "legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py",
    "legacy_reference/PAPER_TRADER_COMPLETE.md",
    "legacy_reference/trading/base_executor.py",
    "legacy_reference/trading/trader.py",
    "legacy_reference/config.py",
]


REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
    "last_risk_decision_id",
    "last_risk_decision_ts",
    "last_paper_trade_id",
    "last_paper_trade_ts",
    "last_paper_trade_ts_ms",
    "last_fill_ts",
    "ledger_action",
    "ledger_reason_code",
    "input_risk_action",
    "input_risk_reason_code",
    "symbol",
    "live_gate",
    "current_gate_state",
    "current_gate_state_must_equal_blocked_human_only",
    "gate_always_blocked_invariant",
    "exchange_call_invariant",
    "fail_closed",
    "missing_runtime_evidence",
    "runtime_evidence_status",
    "freshness_seconds",
    "simulated_fill",
    "fills_recorded_total",
    "fills_processed_total",
    "current_paper_equity",
    "current_paper_pnl",
    "denials_recorded_total",
    "denials_breakdown",
    "decisions_processed_total",
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
    "legacy_paper_source_paths",
    "source_payload_path",
    "live_blocked",
)


_ALLOW_REASON_TO_SIDE = {
    "allow_proceed_long": "long",
    "allow_proceed_short": "short",
}


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
            raw = raw.get("canonical_symbol_id") or raw.get("symbol") or raw.get("legacy_symbol")
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
        source_payload.get("live_blocked_symbols") or overrides.get("live_blocked_symbols")
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


def _looks_like_bridge_payload(record: Dict[str, Any]) -> bool:
    return (
        isinstance(record, dict)
        and record.get("worker_id") == UPSTREAM_RISK_GATEWAY_WORKER_ID
        and "last_risk_decision_id" in record
        and "risk_action" in record
    )


def _bridge_to_direct(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a v2_risk_gateway_runtime_worker bridge payload into a
    direct ``RiskDecisionRecord`` dict. Returns ``None`` if the bridge
    is itself fail-closed / has no risk decision to forward.
    """
    risk_decision_id = str(record.get("last_risk_decision_id") or "")
    if not risk_decision_id:
        return None
    if not record.get("symbol"):
        return None
    try:
        ts_ms = int(record.get("last_risk_decision_ts_ms") or 0)
    except (TypeError, ValueError):
        return None
    if ts_ms <= 0:
        return None
    return {
        "risk_decision_id": risk_decision_id,
        "decision_id": str(record.get("last_decision_id") or ""),
        "prediction_id": str(record.get("prediction_id") or ""),
        "feature_snapshot_id": str(record.get("feature_snapshot_id") or ""),
        "symbol": str(record.get("symbol") or ""),
        "risk_decision_ts_ms": ts_ms,
        "risk_action": str(record.get("risk_action") or ""),
        "risk_reason_code": str(record.get("risk_reason_code") or ""),
        "input_decision_action": str(record.get("input_decision_action") or ""),
        "input_decision_reason_code": str(record.get("input_decision_reason_code") or ""),
        "live_blocked": True,
    }


def _load_risk_decision_from_file(path: Path) -> Optional[Dict[str, Any]]:
    data = _read_json(path)
    if data is None:
        return None
    if isinstance(data, dict) and "risk_decisions" in data and isinstance(
        data["risk_decisions"], list
    ):
        if not data["risk_decisions"]:
            return None
        candidate = data["risk_decisions"][-1]
        if isinstance(candidate, dict):
            return candidate
        return None
    if isinstance(data, dict) and "risk_decision" in data and isinstance(
        data["risk_decision"], dict
    ):
        return data["risk_decision"]
    if isinstance(data, dict) and _looks_like_bridge_payload(data):
        return _bridge_to_direct(data)
    return data if isinstance(data, dict) else None


def _decision_from_dict(record: Dict[str, Any]) -> RiskDecisionRecord:
    return RiskDecisionRecord(
        risk_decision_id=str(record["risk_decision_id"]),
        decision_id=str(record["decision_id"]),
        prediction_id=str(record["prediction_id"]),
        feature_snapshot_id=str(record["feature_snapshot_id"]),
        symbol=str(record["symbol"]),
        risk_decision_ts_ms=int(record["risk_decision_ts_ms"]),
        risk_action=str(record["risk_action"]),
        risk_reason_code=str(record["risk_reason_code"]),
        input_decision_action=str(record["input_decision_action"]),
        input_decision_reason_code=str(record["input_decision_reason_code"]),
        live_blocked=True,
    )


def load_risk_decision(
    args: argparse.Namespace,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Return (risk_decision_dict_or_None, source_payload_path, status).

    status ∈ {"present", "missing_runtime_evidence", "load_failed"}.
    """
    if args.decision_file:
        path = Path(args.decision_file)
        record = _load_risk_decision_from_file(path)
        if record is None:
            return None, str(path), "load_failed"
        return record, str(path), "present"
    for candidate in RISK_DECISION_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            record = _load_risk_decision_from_file(candidate)
            if record is None:
                continue
            try:
                rel_str = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel_str = str(candidate)
            return record, rel_str, "present"
    return None, "", "missing_runtime_evidence"


def _now_ms_clock() -> int:
    return now_ms()


def _build_simulated_fill(
    *,
    risk_reason_code: str,
    notional_usdt: float = BASE_NOTIONAL_USDT_DEFAULT,
    fee_rate_taker: float = FEE_RATE_TAKER_DEFAULT,
    fee_rate_maker: float = FEE_RATE_MAKER_DEFAULT,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, Any]:
    side = _ALLOW_REASON_TO_SIDE.get(risk_reason_code, "none")
    fill_recorded = side != "none"
    if fill_recorded:
        notional = float(notional_usdt)
        fee = round(notional * float(fee_rate_taker), 8)
        slippage = float(slippage_bps)
    else:
        notional = 0.0
        fee = 0.0
        slippage = 0.0
    return {
        "side": side,
        "fill_recorded": fill_recorded,
        "notional_usdt": notional,
        "fee_usdt": fee,
        "fee_rate_taker": float(fee_rate_taker),
        "fee_rate_maker": float(fee_rate_maker),
        "slippage_bps": slippage,
        "exchange_action_taken": False,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
    }


def _empty_simulated_fill() -> Dict[str, Any]:
    return {
        "side": "none",
        "fill_recorded": False,
        "notional_usdt": 0.0,
        "fee_usdt": 0.0,
        "fee_rate_taker": float(FEE_RATE_TAKER_DEFAULT),
        "fee_rate_maker": float(FEE_RATE_MAKER_DEFAULT),
        "slippage_bps": 0.0,
        "exchange_action_taken": False,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
    }


def _content_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def build_fail_closed_status(
    *,
    reason: str,
    source_payload_path: str,
    run_started_ts: str,
    decision_dict: Optional[Dict[str, Any]],
    symbol_scope: Dict[str, Any],
    missing_runtime_evidence: bool,
) -> Dict[str, Any]:
    decision_symbol = ""
    risk_decision_id = ""
    input_risk_action = ""
    input_risk_reason_code = ""
    risk_decision_ts_ms: Optional[int] = None
    if decision_dict:
        decision_symbol = str(decision_dict.get("symbol", "")).upper()
        risk_decision_id = str(decision_dict.get("risk_decision_id", ""))
        input_risk_action = str(decision_dict.get("risk_action", ""))
        input_risk_reason_code = str(decision_dict.get("risk_reason_code", ""))
        try:
            risk_decision_ts_ms = int(decision_dict.get("risk_decision_ts_ms", 0)) or None
        except (TypeError, ValueError):
            risk_decision_ts_ms = None

    runtime_evidence_status = (
        "MISSING_RUNTIME_EVIDENCE"
        if missing_runtime_evidence and not decision_dict
        else "INVALID_RUNTIME_EVIDENCE"
        if decision_dict
        else "MISSING_RUNTIME_EVIDENCE"
    )
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_risk_decision_id": risk_decision_id,
        "last_risk_decision_ts": iso_from_ms(risk_decision_ts_ms) if risk_decision_ts_ms else "",
        "last_paper_trade_id": "",
        "last_paper_trade_ts": "",
        "last_paper_trade_ts_ms": 0,
        "last_fill_ts": "",
        "ledger_action": "",
        "ledger_reason_code": "",
        "input_risk_action": input_risk_action,
        "input_risk_reason_code": input_risk_reason_code,
        "symbol": decision_symbol,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "fail_closed": True,
        "missing_runtime_evidence": True,
        "runtime_evidence_status": runtime_evidence_status,
        "freshness_seconds": freshness_seconds_from_ms(risk_decision_ts_ms),
        "fail_closed_reason": reason,
        "simulated_fill": _empty_simulated_fill(),
        "fills_recorded_total": 0,
        "fills_processed_total": 0,
        "current_paper_equity": PAPER_EQUITY_START_USDT,
        "current_paper_pnl": 0.0,
        "denials_recorded_total": 0,
        "denials_breakdown": {"deny_default": 1},
        "decisions_processed_total": 0,
        "source_payload_path": source_payload_path,
        "legacy_paper_source_paths": list(LEGACY_PAPER_SOURCE_PATHS),
        "live_blocked": True,
        **symbol_scope,
    }


def build_success_status(
    *,
    decision: RiskDecisionRecord,
    ledger_entry: PaperExecutionLedgerEntry,
    source_payload_path: str,
    run_started_ts: str,
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    fill_block = _build_simulated_fill(risk_reason_code=decision.risk_reason_code)
    is_allow = decision.risk_action == "allow"
    fills_total = 1 if is_allow else 0
    denials_total = 0 if is_allow else 1
    denials_breakdown = {} if is_allow else {decision.risk_reason_code: 1}
    last_paper_trade_ts = iso_from_ms(int(ledger_entry.ledger_entry_ts_ms))
    last_risk_decision_ts = iso_from_ms(int(decision.risk_decision_ts_ms))
    current_paper_pnl = -float(fill_block["fee_usdt"]) if fill_block["fill_recorded"] else 0.0
    current_paper_equity = round(PAPER_EQUITY_START_USDT + current_paper_pnl, 8)
    status = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_risk_decision_id": decision.risk_decision_id,
        "last_risk_decision_ts": last_risk_decision_ts,
        "last_paper_trade_id": ledger_entry.paper_trade_id,
        "last_paper_trade_ts": last_paper_trade_ts,
        "last_paper_trade_ts_ms": int(ledger_entry.ledger_entry_ts_ms),
        "last_fill_ts": last_paper_trade_ts if fill_block["fill_recorded"] else "",
        "ledger_action": ledger_entry.ledger_action,
        "ledger_reason_code": ledger_entry.ledger_reason_code,
        "input_risk_action": ledger_entry.input_risk_action,
        "input_risk_reason_code": ledger_entry.input_risk_reason_code,
        "symbol": ledger_entry.symbol,
        "decision_id": ledger_entry.decision_id,
        "prediction_id": ledger_entry.prediction_id,
        "feature_snapshot_id": ledger_entry.feature_snapshot_id,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "fail_closed": True,
        "missing_runtime_evidence": False,
        "runtime_evidence_status": "PRESENT",
        "freshness_seconds": freshness_seconds_from_ms(int(decision.risk_decision_ts_ms)),
        "fail_closed_reason": "",
        "simulated_fill": fill_block,
        "fills_recorded_total": fills_total,
        "fills_processed_total": fills_total,
        "current_paper_equity": current_paper_equity,
        "current_paper_pnl": current_paper_pnl,
        "denials_recorded_total": denials_total,
        "denials_breakdown": denials_breakdown,
        "decisions_processed_total": 1,
        "source_payload_path": source_payload_path,
        "legacy_paper_source_paths": list(LEGACY_PAPER_SOURCE_PATHS),
        "live_blocked": True,
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


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_started_ts = iso_now()
    record_dict, source_path, load_status = load_risk_decision(args)
    observed: List[str] = []
    if record_dict and isinstance(record_dict.get("symbol"), str):
        observed = [record_dict["symbol"]]
    symbol_scope = build_symbol_scope(observed_symbols=observed)

    if load_status == "missing_runtime_evidence":
        status = build_fail_closed_status(
            reason="no_risk_decision_source_found",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            decision_dict=None,
            symbol_scope=symbol_scope,
            missing_runtime_evidence=True,
        )
        write_status(status)
        return status

    if load_status == "load_failed":
        status = build_fail_closed_status(
            reason="risk_decision_payload_unreadable_or_empty",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            decision_dict=record_dict,
            symbol_scope=symbol_scope,
            missing_runtime_evidence=True,
        )
        write_status(status)
        return status

    assert record_dict is not None

    try:
        decision = _decision_from_dict(record_dict)
    except (KeyError, TypeError, ValueError) as exc:
        status = build_fail_closed_status(
            reason=f"invalid_risk_decision_fields: {exc}",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            decision_dict=record_dict,
            symbol_scope=symbol_scope,
            missing_runtime_evidence=True,
        )
        write_status(status)
        return status
    except Exception as exc:  # pragma: no cover — domain validators raise their own type
        status = build_fail_closed_status(
            reason=f"risk_decision_record_rejected: {exc}",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            decision_dict=record_dict,
            symbol_scope=symbol_scope,
            missing_runtime_evidence=True,
        )
        write_status(status)
        return status

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=_now_ms_clock)
    try:
        ledger_entry = recorder(decision=decision)
    except PaperExecutionLedgerServiceError as exc:
        status = build_fail_closed_status(
            reason=f"paper_execution_ledger_service_error: {exc}",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            decision_dict=record_dict,
            symbol_scope=symbol_scope,
            missing_runtime_evidence=True,
        )
        write_status(status)
        return status

    status = build_success_status(
        decision=decision,
        ledger_entry=ledger_entry,
        source_payload_path=source_path,
        run_started_ts=run_started_ts,
        symbol_scope=symbol_scope,
    )
    # Fail-closed gate invariant: the live gate stays blocked regardless of allow/deny.
    status["live_gate"] = LIVE_GATE_STATUS
    status["current_gate_state"] = LIVE_GATE_STATUS
    status["gate_always_blocked_invariant"] = True
    status["exchange_call_invariant"] = EXCHANGE_CALL_INVARIANT
    write_status(status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--decision-file",
        default=None,
        help=(
            "V2-namespaced JSON file containing a RiskDecisionRecord, a list under "
            "'risk_decisions', or the bridge format from v2_risk_gateway_runtime_worker_status.json"
        ),
    )
    parser.add_argument("--once", action="store_true", help="run a single iteration and exit")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument(
        "--interval", type=int, default=30, help="seconds between loop iterations"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="dry-run; do not write any payload to disk",
    )
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.no_write:
        global write_status

        def _skip(_status: Dict[str, Any]) -> None:
            return None

        write_status = _skip  # type: ignore[assignment]
    if args.once:
        status = run_once(args)
        if status.get("missing_runtime_evidence"):
            return 2
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
                    source_payload_path="",
                    run_started_ts=iso_now(),
                    decision_dict=None,
                    symbol_scope=symbol_scope,
                    missing_runtime_evidence=True,
                )
                write_status(fail)
            except Exception:
                pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
