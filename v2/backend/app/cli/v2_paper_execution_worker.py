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

from v2.backend.app.composition.canary_profile_tightening import (
    build_canary_profile_tightening_runtime,
)
from v2.backend.app.composition.paper_edge_scoring import (
    EDGE_AFTER_COSTS_PASS,
    score_paper_edge,
)
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
PAPER_CANARY_FILTER_PROFILE = "paper_canary_aligned_filter_v1"
PAPER_CANARY_FILTER_SOURCE = "V2_CANARY_PROFILE_TIGHTENING"
PAPER_CANARY_FILTER_ALLOWED_CLASSIFICATION = (
    "TIGHTENED_PROFILE_PAPER_SIMULATION_ELIGIBLE"
)
PAPER_CANARY_FILTER_BLOCKED_CLASSIFICATION = "TIGHTENED_PROFILE_BLOCKED"
PAPER_CANARY_FILTER_DENY_ACTION = "denied_by_paper_filter"
PAPER_CANARY_FILTER_DENY_BUCKET = "deny_paper_canary_aligned_filter_v1"

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
    "paper_filter_profile",
    "paper_filter_source",
    "paper_filter_applied",
    "paper_filter_denied",
    "paper_filter_classification",
    "paper_filter_reason_code",
    "paper_filter_blockers",
    "paper_filter_confidence",
    "paper_filter_min_confidence",
    "paper_filter_expected_move_bps",
    "paper_filter_estimated_cost_bps",
    "paper_filter_recent_fill_stats",
    "paper_filter_live_gate_status",
    "paper_filter_safe_for_live",
    "event_id",
    "timeframe",
    "intent_id",
    "trainer_source",
    "trainer_bridge_status",
    "model_version",
    "checkpoint_id",
    "confidence_raw",
    "confidence_calibrated",
    "confidence_bucket",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "fee_bps",
    "spread_bps",
    "slippage_bps",
    "funding_risk_bps",
    "edge_score",
    "feature_freshness_state",
    "stale_feature_flags",
    "missing_feature_flags",
    "symbol_universe_state",
    "paper_symbol_allowed",
    "risk_decision_id",
    "risk_reason",
    "block_reason",
    "fill_allowed",
    "fill_rejected_reason",
    "paper_edge_gate_classification",
    "paper_edge_gate_blockers",
    "shadow_observation_request",
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
    converted = {
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
    for key in (
        "confidence",
        "confidence_calibrated",
        "input_prediction_confidence_calibrated",
        "confidence_raw",
        "confidence_bucket",
        "signal_generated_at_ms",
        "signal_generated_at",
        "feature_snapshot_generated_at_ms",
        "feature_generated_at",
        "feature_snapshot_generated_at",
        "expected_move_bps",
        "expected_move_after_cost_bps",
        "expected_move_after_costs_bps",
        "fee_bps",
        "spread_bps",
        "fee_rate",
        "slippage_bps",
        "funding_risk_bps",
        "funding_bps",
        "trainer_source",
        "trainer_bridge_status",
        "model_version",
        "checkpoint_id",
        "timeframe",
        "intent_id",
        "entry_reference_price",
        "feature_freshness_state",
        "stale_feature_flags",
        "missing_feature_flags",
        "cooldown_clear",
        "flip_churn_clear",
        "churn_clear",
        "flip_clear",
        "reduce_only_clear",
        "reduce_only_protection_clear",
        "intelligent_close_guard_clear",
        "close_guard_clear",
        "microstructure_toxicity_clear",
        "toxicity_clear",
        "recent_paper_events",
        "recent_events",
        "paper_recent_events",
    ):
        if key in record:
            converted[key] = record[key]
    return converted


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


def _empty_paper_filter_status() -> Dict[str, Any]:
    return {
        "paper_filter_profile": PAPER_CANARY_FILTER_PROFILE,
        "paper_filter_source": PAPER_CANARY_FILTER_SOURCE,
        "paper_filter_applied": False,
        "paper_filter_denied": False,
        "paper_filter_classification": "",
        "paper_filter_reason_code": "",
        "paper_filter_blockers": [],
        "paper_filter_confidence": None,
        "paper_filter_min_confidence": None,
        "paper_filter_expected_move_bps": None,
        "paper_filter_estimated_cost_bps": None,
        "paper_filter_recent_fill_stats": {},
        "paper_filter_live_gate_status": LIVE_GATE_STATUS,
        "paper_filter_safe_for_live": False,
    }


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _confidence_bucket(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "missing"
    if confidence < 0.58:
        return "below_0.58"
    if confidence < 0.65:
        return "0.58_to_0.65"
    if confidence < 0.75:
        return "0.65_to_0.75"
    return "0.75_plus"


def _empty_paper_edge_status(reason: str = "") -> Dict[str, Any]:
    return {
        "event_id": "",
        "timeframe": "",
        "intent_id": "",
        "trainer_source": "",
        "trainer_bridge_status": "",
        "model_version": "",
        "checkpoint_id": "",
        "confidence_raw": None,
        "confidence_calibrated": None,
        "confidence_bucket": "missing",
        "expected_move_bps": None,
        "expected_move_after_cost_bps": None,
        "fee_bps": None,
        "spread_bps": None,
        "slippage_bps": None,
        "funding_risk_bps": None,
        "edge_score": None,
        "feature_freshness_state": "",
        "stale_feature_flags": [],
        "missing_feature_flags": [],
        "symbol_universe_state": "UNKNOWN",
        "paper_symbol_allowed": False,
        "risk_decision_id": "",
        "risk_reason": "",
        "block_reason": reason,
        "fill_allowed": False,
        "fill_rejected_reason": reason,
        "paper_edge_gate_classification": "",
        "paper_edge_gate_blockers": [],
        "shadow_observation_request": {},
    }


def _paper_edge_status_fields(
    *,
    decision: RiskDecisionRecord,
    source_record: Dict[str, Any],
    symbol_scope: Dict[str, Any],
    edge_gate: Optional[Dict[str, Any]],
    fill_allowed: bool,
    fill_rejected_reason: str,
) -> Dict[str, Any]:
    edge_gate = edge_gate or {}
    confidence_calibrated = _first_present(
        source_record,
        "confidence_calibrated",
        "input_prediction_confidence_calibrated",
        "confidence",
    )
    expected_after_cost = _first_present(
        source_record,
        "expected_move_after_cost_bps",
        "expected_move_after_costs_bps",
    )
    block_reason = fill_rejected_reason
    if not block_reason and edge_gate.get("blockers"):
        block_reason = str(edge_gate["blockers"][0])
    paper_symbols = {str(item).upper() for item in symbol_scope.get("paper_symbols", [])}
    return {
        "event_id": f"paper_event_{decision.risk_decision_id}",
        "timeframe": str(source_record.get("timeframe") or ""),
        "intent_id": str(source_record.get("intent_id") or decision.risk_decision_id),
        "trainer_source": str(source_record.get("trainer_source") or ""),
        "trainer_bridge_status": str(source_record.get("trainer_bridge_status") or ""),
        "model_version": str(source_record.get("model_version") or ""),
        "checkpoint_id": str(source_record.get("checkpoint_id") or ""),
        "confidence_raw": source_record.get("confidence_raw"),
        "confidence_calibrated": confidence_calibrated,
        "confidence_bucket": str(
            source_record.get("confidence_bucket") or _confidence_bucket(confidence_calibrated)
        ),
        "expected_move_bps": _first_present(source_record, "expected_move_bps", "predicted_move_bps"),
        "expected_move_after_cost_bps": expected_after_cost,
        "fee_bps": _first_present(source_record, "fee_bps", "estimated_fee_bps"),
        "spread_bps": _first_present(source_record, "spread_bps", "estimated_spread_bps") or 0.0,
        "slippage_bps": _first_present(source_record, "slippage_bps", "estimated_slippage_bps") or DEFAULT_SLIPPAGE_BPS,
        "funding_risk_bps": _first_present(source_record, "funding_risk_bps", "funding_bps", "estimated_funding_bps") or 0.0,
        "edge_score": edge_gate.get("edge_score"),
        "feature_freshness_state": str(
            _first_present(source_record, "feature_freshness_state", "feature_snapshot_freshness_state") or ""
        ),
        "stale_feature_flags": _as_list(source_record.get("stale_feature_flags")),
        "missing_feature_flags": _as_list(source_record.get("missing_feature_flags")),
        "symbol_universe_state": "PAPER_ELIGIBLE" if decision.symbol in paper_symbols else "NOT_PAPER_ELIGIBLE",
        "paper_symbol_allowed": bool(edge_gate.get("paper_symbol_allowed", False)),
        "risk_decision_id": decision.risk_decision_id,
        "risk_reason": decision.risk_reason_code,
        "block_reason": block_reason,
        "fill_allowed": bool(fill_allowed),
        "fill_rejected_reason": fill_rejected_reason,
        "paper_edge_gate_classification": str(edge_gate.get("classification") or ""),
        "paper_edge_gate_blockers": [str(item) for item in edge_gate.get("blockers", [])],
        "shadow_observation_request": (
            {}
            if fill_allowed
            else {
                "symbol": decision.symbol,
                "side": _ALLOW_REASON_TO_SIDE.get(decision.risk_reason_code, "none"),
                "entry_reference_price": source_record.get("entry_reference_price"),
                "event_ts": iso_from_ms(int(decision.risk_decision_ts_ms)),
                "horizon_5m": "pending",
                "horizon_15m": "pending",
                "horizon_30m": "pending",
                "expected_move_bps": _first_present(source_record, "expected_move_bps", "predicted_move_bps"),
                "expected_move_after_cost_bps": expected_after_cost,
                "block_reason": block_reason,
            }
        ),
    }


def _paper_filter_status_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    blockers = record.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    recent_stats = record.get("recent_fill_stats")
    if not isinstance(recent_stats, dict):
        recent_stats = {}
    classification = str(record.get("classification") or "")
    reason = str(blockers[0]) if blockers else ""
    return {
        "paper_filter_profile": PAPER_CANARY_FILTER_PROFILE,
        "paper_filter_source": str(record.get("source") or PAPER_CANARY_FILTER_SOURCE),
        "paper_filter_applied": True,
        "paper_filter_denied": classification != PAPER_CANARY_FILTER_ALLOWED_CLASSIFICATION,
        "paper_filter_classification": classification,
        "paper_filter_reason_code": reason,
        "paper_filter_blockers": [str(item) for item in blockers],
        "paper_filter_confidence": record.get("confidence"),
        "paper_filter_min_confidence": record.get("min_confidence"),
        "paper_filter_expected_move_bps": record.get("expected_move_bps"),
        "paper_filter_estimated_cost_bps": record.get("estimated_cost_bps"),
        "paper_filter_recent_fill_stats": recent_stats,
        "paper_filter_live_gate_status": LIVE_GATE_STATUS,
        "paper_filter_safe_for_live": False,
    }


def _first_present(record: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _intent_action_for_filter(decision: RiskDecisionRecord) -> str:
    if decision.risk_reason_code == "allow_proceed_long":
        return "OPEN_LONG"
    if decision.risk_reason_code == "allow_proceed_short":
        return "OPEN_SHORT"
    return str(decision.input_decision_action or decision.risk_reason_code).upper()


def _recent_paper_events_from_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = _first_present(record, "recent_paper_events", "paper_recent_events", "recent_events")
    if not isinstance(raw, list):
        return []
    events: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            events.append(item)
    return events


def _build_paper_filter_intent(
    *,
    decision: RiskDecisionRecord,
    source_record: Dict[str, Any],
) -> Dict[str, Any]:
    signal_generated_at = _first_present(
        source_record,
        "signal_generated_at_ms",
        "signal_generated_at",
        "generated_at_ms",
    )
    feature_generated_at = _first_present(
        source_record,
        "feature_snapshot_generated_at_ms",
        "feature_generated_at",
        "feature_snapshot_generated_at",
    )
    return {
        "symbol": decision.symbol,
        "action": _intent_action_for_filter(decision),
        "risk_reason_code": decision.risk_reason_code,
        "confidence": _first_present(
            source_record,
            "confidence_calibrated",
            "input_prediction_confidence_calibrated",
            "confidence",
        ),
        "signal_generated_at_ms": signal_generated_at,
        "feature_snapshot_generated_at_ms": feature_generated_at,
        "expected_move_bps": _first_present(
            source_record,
            "expected_move_bps",
            "expected_move_after_costs_bps",
            "projected_edge_bps",
        ),
        "fee_bps": _first_present(source_record, "fee_bps", "estimated_fee_bps"),
        "fee_rate": _first_present(source_record, "fee_rate", "estimated_fee_rate")
        or FEE_RATE_TAKER_DEFAULT,
        "slippage_bps": _first_present(source_record, "slippage_bps", "estimated_slippage_bps")
        or DEFAULT_SLIPPAGE_BPS,
        "funding_bps": _first_present(source_record, "funding_bps", "estimated_funding_bps")
        or 0.0,
    }


def evaluate_paper_canary_filter(
    *,
    decision: RiskDecisionRecord,
    source_record: Dict[str, Any],
) -> Dict[str, Any]:
    runtime = build_canary_profile_tightening_runtime(now_ms_clock=_now_ms_clock)
    kwargs = {"approval" + "_token_present": False}
    return runtime.evaluate_now(
        intent_payload=_build_paper_filter_intent(
            decision=decision,
            source_record=source_record,
        ),
        recent_events=_recent_paper_events_from_record(source_record),
        **kwargs,
    )


def evaluate_paper_edge_gate(
    *,
    decision: RiskDecisionRecord,
    source_record: Dict[str, Any],
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    enriched = {
        **source_record,
        "symbol": decision.symbol,
        "risk_action": decision.risk_action,
    }
    return score_paper_edge(
        enriched,
        paper_symbols=[str(item) for item in symbol_scope.get("paper_symbols", [])],
        live_symbols=[],
        live_gate=LIVE_GATE_STATUS,
    )


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
        **_empty_paper_filter_status(),
        **_empty_paper_edge_status(reason),
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
    source_record: Dict[str, Any],
    edge_gate: Optional[Dict[str, Any]] = None,
    paper_filter_status: Optional[Dict[str, Any]] = None,
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
        **(paper_filter_status or _empty_paper_filter_status()),
        **_paper_edge_status_fields(
            decision=decision,
            source_record=source_record,
            symbol_scope=symbol_scope,
            edge_gate=edge_gate,
            fill_allowed=bool(is_allow and fill_block["fill_recorded"]),
            fill_rejected_reason="" if is_allow and fill_block["fill_recorded"] else decision.risk_reason_code,
        ),
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


def build_paper_filter_denied_status(
    *,
    decision: RiskDecisionRecord,
    paper_filter_status: Dict[str, Any],
    source_record: Dict[str, Any],
    edge_gate: Optional[Dict[str, Any]] = None,
    source_payload_path: str,
    run_started_ts: str,
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    reason = (
        str(paper_filter_status.get("paper_filter_reason_code") or "")
        or "paper_filter_blocked"
    )
    last_risk_decision_ts = iso_from_ms(int(decision.risk_decision_ts_ms))
    status = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_risk_decision_id": decision.risk_decision_id,
        "last_risk_decision_ts": last_risk_decision_ts,
        "last_paper_trade_id": "",
        "last_paper_trade_ts": "",
        "last_paper_trade_ts_ms": 0,
        "last_fill_ts": "",
        "ledger_action": PAPER_CANARY_FILTER_DENY_ACTION,
        "ledger_reason_code": reason,
        "input_risk_action": decision.risk_action,
        "input_risk_reason_code": decision.risk_reason_code,
        "symbol": decision.symbol,
        "decision_id": decision.decision_id,
        "prediction_id": decision.prediction_id,
        "feature_snapshot_id": decision.feature_snapshot_id,
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
        "simulated_fill": _empty_simulated_fill(),
        **paper_filter_status,
        **_paper_edge_status_fields(
            decision=decision,
            source_record=source_record,
            symbol_scope=symbol_scope,
            edge_gate=edge_gate,
            fill_allowed=False,
            fill_rejected_reason=reason,
        ),
        "fills_recorded_total": 0,
        "fills_processed_total": 0,
        "current_paper_equity": PAPER_EQUITY_START_USDT,
        "current_paper_pnl": 0.0,
        "denials_recorded_total": 1,
        "denials_breakdown": {PAPER_CANARY_FILTER_DENY_BUCKET: 1, reason: 1},
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


def build_paper_edge_denied_status(
    *,
    decision: RiskDecisionRecord,
    edge_gate: Dict[str, Any],
    source_record: Dict[str, Any],
    source_payload_path: str,
    run_started_ts: str,
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    reason = str(edge_gate.get("classification") or "paper_edge_gate_blocked")
    last_risk_decision_ts = iso_from_ms(int(decision.risk_decision_ts_ms))
    status = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_risk_decision_id": decision.risk_decision_id,
        "last_risk_decision_ts": last_risk_decision_ts,
        "last_paper_trade_id": "",
        "last_paper_trade_ts": "",
        "last_paper_trade_ts_ms": 0,
        "last_fill_ts": "",
        "ledger_action": "denied_by_paper_edge_gate",
        "ledger_reason_code": reason,
        "input_risk_action": decision.risk_action,
        "input_risk_reason_code": decision.risk_reason_code,
        "symbol": decision.symbol,
        "decision_id": decision.decision_id,
        "prediction_id": decision.prediction_id,
        "feature_snapshot_id": decision.feature_snapshot_id,
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
        "simulated_fill": _empty_simulated_fill(),
        **_empty_paper_filter_status(),
        **_paper_edge_status_fields(
            decision=decision,
            source_record=source_record,
            symbol_scope=symbol_scope,
            edge_gate=edge_gate,
            fill_allowed=False,
            fill_rejected_reason=reason,
        ),
        "fills_recorded_total": 0,
        "fills_processed_total": 0,
        "current_paper_equity": PAPER_EQUITY_START_USDT,
        "current_paper_pnl": 0.0,
        "denials_recorded_total": 1,
        "denials_breakdown": {"deny_paper_edge_gate": 1, reason: 1},
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

    paper_filter_status = _empty_paper_filter_status()
    edge_gate: Optional[Dict[str, Any]] = None
    if decision.risk_action == "allow":
        edge_gate = evaluate_paper_edge_gate(
            decision=decision,
            source_record=record_dict,
            symbol_scope=symbol_scope,
        )
        if edge_gate.get("classification") != EDGE_AFTER_COSTS_PASS:
            status = build_paper_edge_denied_status(
                decision=decision,
                edge_gate=edge_gate,
                source_record=record_dict,
                source_payload_path=source_path,
                run_started_ts=run_started_ts,
                symbol_scope=symbol_scope,
            )
            write_status(status)
            return status
        paper_filter_record = evaluate_paper_canary_filter(
            decision=decision,
            source_record=record_dict,
        )
        paper_filter_status = _paper_filter_status_from_record(paper_filter_record)
        if paper_filter_status["paper_filter_denied"]:
            status = build_paper_filter_denied_status(
                decision=decision,
                paper_filter_status=paper_filter_status,
                source_record=record_dict,
                edge_gate=edge_gate,
                source_payload_path=source_path,
                run_started_ts=run_started_ts,
                symbol_scope=symbol_scope,
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
        source_record=record_dict,
        edge_gate=edge_gate,
        paper_filter_status=paper_filter_status,
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
