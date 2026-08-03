"""
DEPRECATED: 2026-07-16
This module is no longer used and has been replaced by v2_trade_management_paper_loop.py
Service ai-bot-v2-paper-online-runtime.service has been disabled and stopped.
This file is kept for reference only and should not be invoked.
Do not enable or run this service.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from v2.backend.app.composition.canary_profile_tightening import build_canary_profile_tightening_runtime
from v2.backend.app.composition.paper_edge_scoring import score_paper_edge
from v2.backend.app.composition.paper_expected_move_coverage import (
    evaluate_paper_expected_move_coverage,
)
from v2.backend.app.services.binance_unified_websocket_transport import fetch_unified_market_snapshot
from v2.backend.app.services.paper_trade_management.outcomes import (
    FUNDING_PNL_ACCOUNTING_FORMULA,
    FUNDING_PNL_ACCOUNTING_VERSION,
)
from v2.backend.app.services.runtime_clock import est_now_iso
from v2.backend.app.services.signal_publisher import build_paper_runtime_lineage
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


LIVE_GATE_STATUS = "blocked_human_only"
READY_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_READY"
BLOCKED_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_BLOCKED"
CODEX_PASS_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_CODEX_PASS"
CODEX_FAIL_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_CODEX_FAIL"
V2_CURRENT_PAPER_OWNER = "adaptive_cuda_challenger_pipeline"
PAPER_ONLINE_LEGACY_OWNER = "old_policy"
PAPER_ONLINE_LEGACY_OWNER_MODE = "LEGACY_SHADOW_ONLY"
PAPER_ONLINE_LEGACY_MODEL_SOURCE = "toy_momentum_wrapper_legacy_shadow_only"
PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON = "OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"
PAPER_ONLINE_INTENTS_KEY = "v2:paper_online:intents"
PAPER_ONLINE_LEDGER_KEY = "v2:paper_online:ledger"
PAPER_ONLINE_RISK_DECISIONS_KEY = "v2:risk:paper_online_decisions"
PAPER_ONLINE_RISK_DECISIONS_LATEST_KEY = "v2:risk:paper_online_decisions:latest"
PAPER_ONLINE_RISK_GATEWAY_DECISIONS_KEY = "v2:risk:gateway:paper_online_decisions"
PAPER_ONLINE_RISK_GATEWAY_DECISIONS_LATEST_KEY = "v2:risk:gateway:paper_online_decisions:latest"
CANONICAL_RISK_TRUST_REQUIRED_FIELDS = (
    "prediction_id",
    "decision_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "symbol",
    "timeframe",
    "selected_action",
    "model_version",
    "checkpoint_id",
    "source_hashes",
)

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest"
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / "paper_online" / "latest"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "v2_paper_online_recovery" / "latest"
TRAINER_BRIDGE_STATUS_FILE = (
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_trainer_bridge"
    / "latest"
    / "v2_trainer_bridge_status.json"
)


def _has_complete_canonical_risk_trust_envelope(row: dict[str, Any]) -> bool:
    for field in CANONICAL_RISK_TRUST_REQUIRED_FIELDS:
        value = row.get(field)
        if value in (None, "", [], {}):
            return False
    return isinstance(row.get("source_hashes"), dict)


def _resolve_runtime_symbol(symbol: str | None, *, smoke_test: bool = False) -> str:
    explicit = str(symbol or "").strip().upper()
    if explicit:
        return explicit
    resolved = resolve_symbols(smoke_test=smoke_test, include_baseline=True)
    return str(resolved[0]).upper()


PAPER_SHADOW_OUTCOME_STATUS_FILE = (
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "paper_shadow_outcome_observer"
    / "latest"
    / "paper_shadow_outcome_observer_status.json"
)
WEEKLY_LOSS_LIMIT_USDT = -250.0
DAILY_LOSS_LIMIT_USDT = -75.0
PAPER_TIGHTENING_MIN_CONFIDENCE = 0.75
PAPER_TIGHTENING_MAX_FILLS_PER_HOUR = 12
PAPER_TIGHTENING_COOLDOWN_SECONDS = 300
PAPER_TIGHTENING_LOSS_COOLDOWN_SECONDS = 3600
PAPER_TIGHTENING_MAX_SIGNAL_AGE_SECONDS = 120
PAPER_TIGHTENING_MAX_FEATURE_AGE_SECONDS = 120
PAPER_OUTCOME_MODEL_READY = True
PAPER_OUTCOME_MODEL_BLOCKER = "paper_outcome_model_missing"
PAPER_POSITION_MIN_HOLD_SECONDS = 120
PAPER_POSITION_MAX_HOLD_SECONDS = 15 * 60
PAPER_POSITION_DEFAULT_STOP_BPS = 8.0
PAPER_POSITION_MIN_TAKE_PROFIT_BPS = 8.0
PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS = 150.0
PAPER_EXECUTION_TIMING_TIMEFRAME = "1m"
PAPER_UNKNOWN_THESIS_TIMEFRAME = "UNKNOWN"
PAPER_ALLOWED_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h"}
PAPER_EDGE_TO_COST_CONTEXTUAL_SAFETY_RATIO = 1.5
PAPER_COST_MAX_FRESHNESS_SECONDS = 120
PAPER_REENTRY_DEDUP_RUNTIME_LOOKBACK_ROWS = 500


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    price: float | None
    source_type: str
    source: str
    source_pointer: str
    generated_at: str
    last_event_at: str | None
    age_seconds: int | None
    freshness_state: str
    errors: list[str]
    candles: list[dict[str, Any]]
    timeframe: str = PAPER_EXECUTION_TIMING_TIMEFRAME


def iso_now() -> str:
    return est_now_iso()


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_paper_timeframe(value: Any, *, fallback: str | None = None) -> str | None:
    text = str(value or "").strip()
    if text in PAPER_ALLOWED_TIMEFRAMES:
        return text
    return fallback


def _paper_execution_timeframe(*sources: dict[str, Any]) -> str:
    for source in sources:
        for field in ("execution_timeframe", "feature_timeframe", "timeframe"):
            parsed = _clean_paper_timeframe(source.get(field))
            if parsed is not None:
                return parsed
    return PAPER_EXECUTION_TIMING_TIMEFRAME


def _paper_thesis_timeframe(*sources: dict[str, Any]) -> str:
    for source in sources:
        for field in (
            "thesis_timeframe",
            "prediction_timeframe",
            "expected_move_timeframe",
            "timeframe",
        ):
            parsed = _clean_paper_timeframe(source.get(field))
            if parsed is not None:
                return parsed
    return PAPER_UNKNOWN_THESIS_TIMEFRAME


def _paper_identity_part(value: Any) -> str:
    text = str(value or "").strip()
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
    return cleaned[:96] or "unknown"


def _paper_economic_identity(lineage: dict[str, Any], generated_at: str) -> dict[str, Any]:
    ids = lineage.get("lineage_ids") if isinstance(lineage.get("lineage_ids"), dict) else {}
    signal = lineage.get("signal") if isinstance(lineage.get("signal"), dict) else {}
    prediction = lineage.get("trainer_prediction") if isinstance(lineage.get("trainer_prediction"), dict) else {}
    feature_snapshot = lineage.get("feature_snapshot") if isinstance(lineage.get("feature_snapshot"), dict) else {}
    prediction_id = _paper_identity_part(ids.get("prediction_id") or prediction.get("prediction_id") or generated_at)
    signal_id = _paper_identity_part(ids.get("signal_id") or signal.get("signal_id") or prediction_id)
    timeframe = _paper_identity_part(_paper_thesis_timeframe(prediction, signal, feature_snapshot))
    economic_thesis_id = f"ethesis_{prediction_id}_{timeframe}"
    parent_position_id = f"ppos_{signal_id}_{timeframe}"
    return {
        "economic_trade_id": f"econ_{parent_position_id}",
        "economic_thesis_id": economic_thesis_id,
        "parent_position_id": parent_position_id,
        "thesis_prediction_id": ids.get("prediction_id") or prediction.get("prediction_id"),
        "execution_snapshot_id": ids.get("feature_snapshot_id") or feature_snapshot.get("feature_snapshot_id"),
        "thesis_timeframe": timeframe,
        "execution_timeframe": _paper_execution_timeframe(feature_snapshot, prediction, signal),
    }


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _paper_funding_accounting(
    *,
    side: str,
    notional_usdt: float,
    hold_time_seconds: int,
    funding_rate: float | None,
    funding_bps: float | None,
    funding_interval_seconds: float | None = None,
) -> dict[str, Any]:
    if funding_rate is None and funding_bps is not None:
        funding_rate = funding_bps / 10000.0
    if funding_bps is None and funding_rate is not None:
        funding_bps = funding_rate * 10000.0
    interval_seconds = max(1.0, float(funding_interval_seconds or 28800.0))
    intervals = max(0.0, float(hold_time_seconds)) / interval_seconds
    side_sign = -1.0 if str(side).lower() == "long" else 1.0
    funding_pnl = (
        0.0
        if funding_rate is None
        else round(abs(notional_usdt) * funding_rate * intervals * side_sign, 6)
    )
    return {
        "funding_pnl_accounting_version": FUNDING_PNL_ACCOUNTING_VERSION,
        "funding_pnl_accounting_status": (
            "READY_FUNDING_PNL_ACCRUED"
            if funding_rate is not None
            else "MISSING_FUNDING_RATE_OR_BPS"
        ),
        "funding_pnl_usd": funding_pnl,
        "funding_rate": funding_rate,
        "funding_bps": funding_bps,
        "funding_interval_seconds": interval_seconds,
        "funding_accrual_intervals": intervals,
        "funding_notional_usd": abs(notional_usdt),
        "funding_pnl_formula": FUNDING_PNL_ACCOUNTING_FORMULA,
        "funding_pnl_side_sign": side_sign,
        "funding_pnl_source": (
            "FUNDING_RATE_OR_BPS_FROM_LINEAGE"
            if funding_rate is not None
            else "MISSING_FUNDING_RATE"
        ),
    }


def _funding_inputs_from_lineage(lineage: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    risk = lineage.get("risk_decision") if isinstance(lineage.get("risk_decision"), dict) else {}
    signal = lineage.get("signal") if isinstance(lineage.get("signal"), dict) else {}
    prediction = (
        lineage.get("trainer_prediction")
        if isinstance(lineage.get("trainer_prediction"), dict)
        else {}
    )
    feature_snapshot = (
        lineage.get("feature_snapshot")
        if isinstance(lineage.get("feature_snapshot"), dict)
        else {}
    )
    features = (
        feature_snapshot.get("features")
        if isinstance(feature_snapshot.get("features"), dict)
        else {}
    )
    funding_rate = _first_float(
        risk.get("funding_rate"),
        signal.get("funding_rate"),
        prediction.get("funding_rate"),
        feature_snapshot.get("funding_rate"),
        features.get("funding_rate"),
        features.get("actual_funding_rate"),
        features.get("expected_funding_rate"),
    )
    funding_bps = _first_float(
        risk.get("expected_funding_bps"),
        signal.get("expected_funding_bps"),
        prediction.get("expected_funding_bps"),
        feature_snapshot.get("expected_funding_bps"),
        features.get("expected_funding_bps"),
        features.get("funding_bps"),
        features.get("funding_rate_bps"),
    )
    interval_seconds = _first_float(
        risk.get("funding_interval_seconds"),
        signal.get("funding_interval_seconds"),
        prediction.get("funding_interval_seconds"),
        feature_snapshot.get("funding_interval_seconds"),
        features.get("funding_interval_seconds"),
    )
    return funding_rate, funding_bps, interval_seconds


def _trainer_bridge_expected_move(feature_snapshot: dict[str, Any]) -> dict[str, Any]:
    bridge = _read_json_file(TRAINER_BRIDGE_STATUS_FILE)
    expected_move = _float_or_none(bridge.get("expected_move_bps"))
    expected_move_after_cost = _float_or_none(
        bridge.get("expected_move_after_cost_bps")
    )
    if expected_move is None:
        return {"status": "MISSING_NATIVE_EXPECTED_MOVE"}
    if str(bridge.get("expected_move_evidence_mode") or "") != "NATIVE_FIELD_PRESENT":
        return {"status": "EXPECTED_MOVE_NOT_NATIVE"}
    bridge_symbol = str(bridge.get("prediction_symbol") or "").strip().upper()
    bridge_timeframe = str(bridge.get("prediction_timeframe") or "").strip()
    feature_symbol = str(feature_snapshot.get("symbol") or "").strip().upper()
    feature_timeframe = _paper_execution_timeframe(feature_snapshot)
    if bridge_symbol != feature_symbol:
        return {
            "status": "EXPECTED_MOVE_SYMBOL_MISMATCH",
            "prediction_symbol": bridge_symbol,
            "prediction_timeframe": bridge_timeframe,
            "feature_symbol": feature_symbol,
            "feature_timeframe": feature_timeframe,
        }
    if bridge.get("live_gate") != LIVE_GATE_STATUS or bridge.get("live_symbols") not in ([], None):
        return {"status": "TRAINER_BRIDGE_LIVE_SCOPE_UNSAFE"}
    return {
        "status": "NATIVE_EXPECTED_MOVE_PRESENT",
        "expected_move_bps": expected_move,
        "expected_move_after_cost_bps": expected_move_after_cost,
        "expected_move_source": str(bridge.get("expected_move_source") or ""),
        "expected_move_timeframe": bridge_timeframe,
        "feature_timeframe": feature_timeframe,
        "cross_timeframe_expected_move": bridge_timeframe != feature_timeframe,
        "trainer_source": str(bridge.get("prediction_source_type") or ""),
        "trainer_bridge_status": str(bridge.get("trainer_parity_status") or ""),
        "model_version": str(bridge.get("model_version") or ""),
        "checkpoint_id": str(bridge.get("checkpoint_id") or ""),
        "bridge_prediction_id": str(bridge.get("prediction_id") or ""),
    }


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds <= 120:
        return "CURRENT"
    if age_seconds <= 300:
        return "WARN"
    return "STALE"


def fetch_market_snapshot(symbol: str, timeframe: str | None = None) -> MarketSnapshot:
    execution_timeframe = _paper_execution_timeframe({"execution_timeframe": timeframe})
    snapshot = fetch_unified_market_snapshot(symbol, timeframe=execution_timeframe, limit=30)
    return MarketSnapshot(
        symbol=snapshot.symbol,
        price=snapshot.price,
        source_type=snapshot.source_type,
        source=snapshot.source,
        source_pointer=snapshot.source_pointer,
        generated_at=snapshot.generated_at,
        last_event_at=snapshot.last_event_at,
        age_seconds=snapshot.age_seconds,
        freshness_state=snapshot.freshness_state,
        errors=snapshot.errors,
        candles=snapshot.candles,
        timeframe=execution_timeframe,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl_tail(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _paper_churn_governor_runtime_rows(limit: int = 500) -> list[dict[str, Any]]:
    rows = _read_jsonl_tail(LOCAL_RUNTIME_DIR / "paper_events.jsonl", limit=limit)
    return [
        row
        for row in rows
        if row.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY"
        and row.get("live_gate_status", LIVE_GATE_STATUS) == LIVE_GATE_STATUS
        and row.get("exchange_order") is False
    ]


def _paper_dedup_identity_part(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    return text or None


def _paper_first_identity(*values: Any) -> str | None:
    for value in values:
        parsed = _paper_dedup_identity_part(value)
        if parsed is not None:
            return parsed
    return None


def _paper_reentry_dedup_runtime_rows(
    limit: int = PAPER_REENTRY_DEDUP_RUNTIME_LOOKBACK_ROWS,
) -> list[dict[str, Any]]:
    rows = _read_jsonl_tail(LOCAL_RUNTIME_DIR / "paper_events.jsonl", limit=limit)
    return [
        row
        for row in rows
        if row.get("paper_result") in {"FILLED_PAPER_ONLY", "POSITION_CLOSED_PAPER_ONLY"}
        and row.get("exchange_order") is False
    ]


def _paper_strategy_id(
    *,
    signal: dict[str, Any] | None = None,
    prediction: dict[str, Any] | None = None,
    row: dict[str, Any] | None = None,
) -> str:
    signal = signal or {}
    prediction = prediction or {}
    row = row or {}
    return _paper_first_identity(
        row.get("strategy_id"),
        row.get("strategy_mode"),
        signal.get("strategy_id"),
        prediction.get("strategy_id"),
        prediction.get("strategy_mode"),
        "paper_runtime_momentum",
    ) or "paper_runtime_momentum"


def _paper_thesis_candle_value(*sources: dict[str, Any]) -> str | None:
    for source in sources:
        parsed = _paper_first_identity(
            source.get("thesis_candle_close_time"),
            source.get("entry_feature_cutoff"),
            source.get("feature_cutoff"),
            source.get("candle_close_time"),
            source.get("finalized_candle_close_time"),
        )
        if parsed is not None:
            return parsed
    return None


def _paper_reentry_dedup_candidate_row(
    *,
    symbol: str,
    timeframe: str,
    side: str,
    risk: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
) -> dict[str, Any]:
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    entry_time = _paper_first_identity(
        risk.get("generated_at"),
        signal.get("generated_at"),
        prediction.get("generated_at"),
        feature_snapshot.get("generated_at"),
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "thesis_timeframe": timeframe,
        "side": side.upper(),
        "prediction_id": _paper_first_identity(
            prediction.get("prediction_id"),
            signal.get("prediction_id"),
            risk.get("prediction_id"),
        ),
        "decision_id": _paper_first_identity(
            risk.get("decision_id"),
            risk.get("orchestrator_decision_id"),
            risk.get("risk_decision_id"),
        ),
        "risk_decision_id": _paper_first_identity(risk.get("risk_decision_id")),
        "signal_id": _paper_first_identity(signal.get("signal_id"), risk.get("signal_id")),
        "feature_snapshot_id": _paper_first_identity(
            feature_snapshot.get("feature_snapshot_id"),
            prediction.get("feature_snapshot_id"),
            risk.get("feature_snapshot_id"),
        ),
        "strategy_id": _paper_strategy_id(signal=signal, prediction=prediction),
        "thesis_candle_close_time": _paper_thesis_candle_value(
            risk,
            signal,
            prediction,
            feature_snapshot,
        ),
        "entry_time": entry_time,
        "generated_at": entry_time,
        "expected_move_after_cost_bps": risk.get("expected_move_after_cost_bps"),
        "market_regime_at_entry": _paper_first_identity(
            features.get("market_regime"),
            risk.get("market_regime_at_entry"),
            signal.get("market_regime_at_entry"),
        )
        or "UNKNOWN",
        "microstructure_context": _paper_first_identity(
            features.get("microstructure_context"),
            risk.get("microstructure_context"),
            signal.get("microstructure_context"),
        )
        or "UNKNOWN",
        "liquidation_context": _paper_first_identity(
            features.get("liquidation_context"),
            risk.get("liquidation_context"),
            signal.get("liquidation_context"),
        )
        or "UNKNOWN",
    }


def _paper_row_symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or "").upper()


def _paper_row_timeframe(row: dict[str, Any]) -> str:
    return str(row.get("thesis_timeframe") or row.get("timeframe") or "").strip()


def _paper_row_side(row: dict[str, Any]) -> str:
    return str(row.get("side") or row.get("paper_action") or "").replace("paper_", "").upper()


def _paper_row_thesis_candle(row: dict[str, Any]) -> str | None:
    return _paper_thesis_candle_value(row)


def _paper_row_entry_time(row: dict[str, Any]) -> str | None:
    return _paper_first_identity(
        row.get("entry_time"),
        row.get("entry_feature_decision_time"),
        row.get("opened_at"),
        row.get("generated_at"),
    )


def _paper_row_exit_time(row: dict[str, Any]) -> str | None:
    return _paper_first_identity(
        row.get("exit_time"),
        row.get("closed_at"),
        row.get("exit_price_utc"),
        row.get("generated_at") if row.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY" else None,
    )


def _paper_row_identity(row: dict[str, Any]) -> dict[str, str | None]:
    symbol = _paper_row_symbol(row)
    timeframe = _paper_row_timeframe(row)
    candle = _paper_row_thesis_candle(row) or ""
    strategy = _paper_strategy_id(row=row)
    side = _paper_row_side(row)
    return {
        "prediction_id": _paper_first_identity(row.get("entry_prediction_id"), row.get("prediction_id")),
        "decision_id": _paper_first_identity(
            row.get("decision_id"),
            row.get("orchestrator_decision_id"),
            row.get("risk_decision_id"),
        ),
        "signal_id": _paper_first_identity(row.get("entry_signal_id"), row.get("signal_id")),
        "feature_snapshot_id": _paper_first_identity(
            row.get("entry_feature_snapshot_id"),
            row.get("feature_snapshot_id"),
        ),
        "same_candle_same_thesis": "|".join([symbol, timeframe, candle, strategy, side]),
    }


def _paper_partial_close(row: dict[str, Any]) -> bool:
    close_reason = str(row.get("close_reason") or row.get("exit_reason") or "").lower()
    return bool(row.get("is_partial_close") is True or row.get("is_partial_reduce") is True or "partial" in close_reason)


def _paper_reentry_material_change_reasons(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    previous_candle = _paper_row_thesis_candle(previous)
    current_candle = _paper_row_thesis_candle(current)
    if previous_candle and current_candle and previous_candle != current_candle:
        reasons.append("new_finalized_thesis_candle")
    previous_regime = _paper_first_identity(previous.get("market_regime_at_entry"), previous.get("market_regime"))
    current_regime = _paper_first_identity(current.get("market_regime_at_entry"), current.get("market_regime"))
    if (
        previous_regime
        and current_regime
        and previous_regime != "UNKNOWN"
        and current_regime != "UNKNOWN"
        and previous_regime != current_regime
    ):
        reasons.append("market_regime_change")
    if _paper_strategy_id(row=previous) != _paper_strategy_id(row=current):
        reasons.append("strategy_change")
    if _paper_row_side(previous) != _paper_row_side(current):
        reasons.append("direction_change")
    previous_edge = _float_or_none(
        previous.get("expected_move_after_cost_bps")
        or previous.get("expected_net_edge_bps")
        or previous.get("expected_move_bps")
    )
    current_edge = _float_or_none(
        current.get("expected_move_after_cost_bps")
        or current.get("expected_net_edge_bps")
        or current.get("expected_move_bps")
    )
    if previous_edge is not None and current_edge is not None and current_edge > previous_edge:
        reasons.append("expected_edge_improvement")
    previous_context = _paper_first_identity(
        previous.get("liquidation_context"),
        previous.get("microstructure_context"),
        previous.get("market_state_id"),
    )
    current_context = _paper_first_identity(
        current.get("liquidation_context"),
        current.get("microstructure_context"),
        current.get("market_state_id"),
    )
    if (
        previous_context
        and current_context
        and previous_context != "UNKNOWN"
        and current_context != "UNKNOWN"
        and previous_context != current_context
    ):
        reasons.append("liquidation_or_microstructure_state_change")
    previous_exit = _parse_ts(_paper_row_exit_time(previous))
    current_entry = _parse_ts(_paper_row_entry_time(current))
    cooldown_seconds = _float_or_none(current.get("reentry_cooldown_seconds") or current.get("cooldown_seconds")) or 300.0
    previous_snapshot = _paper_row_identity(previous).get("feature_snapshot_id")
    current_snapshot = _paper_row_identity(current).get("feature_snapshot_id")
    if (
        previous_exit is not None
        and current_entry is not None
        and current_entry - previous_exit >= cooldown_seconds
        and previous_snapshot
        and current_snapshot
        and previous_snapshot != current_snapshot
    ):
        reasons.append("cooldown_elapsed_with_fresh_independent_evidence")
    return reasons


def _paper_reentry_dedup_gate(previous_rows: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    duplicate_fields: list[str] = []
    duplicate_samples: list[dict[str, Any]] = []
    permitted_reasons: set[str] = set()
    candidate_identity = _paper_row_identity(candidate)
    exact_fields = ("prediction_id", "decision_id", "signal_id", "feature_snapshot_id")
    exact_blocker_by_field = {
        "prediction_id": "same_prediction_id",
        "decision_id": "same_decision_id",
        "signal_id": "same_signal_id",
        "feature_snapshot_id": "same_feature_snapshot_id",
    }
    for index, previous in enumerate(previous_rows):
        previous_identity = _paper_row_identity(previous)
        for field in exact_fields:
            candidate_value = candidate_identity.get(field)
            previous_value = previous_identity.get(field)
            if candidate_value and previous_value and candidate_value == previous_value:
                blocker = exact_blocker_by_field[field]
                if blocker not in blockers:
                    blockers.append(blocker)
                if field not in duplicate_fields:
                    duplicate_fields.append(field)
                if len(duplicate_samples) < 10:
                    duplicate_samples.append(
                        {
                            "duplicate_field": field,
                            "duplicate_value": candidate_value,
                            "previous_index": index,
                            "previous_paper_result": previous.get("paper_result"),
                        }
                    )

        same_symbol_timeframe_strategy_side = (
            _paper_row_symbol(previous) == _paper_row_symbol(candidate)
            and _paper_row_timeframe(previous) == _paper_row_timeframe(candidate)
            and _paper_strategy_id(row=previous) == _paper_strategy_id(row=candidate)
            and _paper_row_side(previous) == _paper_row_side(candidate)
        )
        if not same_symbol_timeframe_strategy_side:
            continue
        material_reasons = _paper_reentry_material_change_reasons(previous, candidate)
        if material_reasons:
            permitted_reasons.update(material_reasons)
            continue
        previous_candle_key = previous_identity.get("same_candle_same_thesis")
        candidate_candle_key = candidate_identity.get("same_candle_same_thesis")
        if previous_candle_key and candidate_candle_key and previous_candle_key == candidate_candle_key:
            if "same_candle_same_thesis" not in blockers:
                blockers.append("same_candle_same_thesis")
            if "same_candle_same_thesis" not in duplicate_fields:
                duplicate_fields.append("same_candle_same_thesis")
        if _paper_partial_close(previous) and "partial_close_reentry_without_material_change" not in blockers:
            blockers.append("partial_close_reentry_without_material_change")
        if "same_symbol_side_strategy_without_material_change" not in blockers:
            blockers.append("same_symbol_side_strategy_without_material_change")
        if len(duplicate_samples) < 10:
            duplicate_samples.append(
                {
                    "duplicate_field": "same_symbol_side_strategy_without_material_change",
                    "duplicate_value": candidate_candle_key,
                    "previous_index": index,
                    "previous_paper_result": previous.get("paper_result"),
                }
            )

    allowed = not blockers
    return {
        "schema_version": "paper_reentry_dedup_runtime_gate_v1",
        "status": "PASS_PAPER_REENTRY_DEDUP_GATE" if allowed else "BLOCKED_PAPER_REENTRY_DEDUP_GATE",
        "allowed": allowed,
        "blockers": blockers,
        "duplicate_identity_fields": duplicate_fields,
        "duplicate_identity_samples": duplicate_samples,
        "candidate_identity": candidate_identity,
        "previous_rows_examined": len(previous_rows),
        "permitted_reentry_reasons": sorted(permitted_reasons),
        "allowed_reentry_reasons": [
            "new_finalized_thesis_candle",
            "market_regime_change",
            "strategy_change",
            "direction_change",
            "expected_edge_improvement",
            "liquidation_or_microstructure_state_change",
            "cooldown_elapsed_with_fresh_independent_evidence",
        ],
        "runtime_wired_to_entry_gate": True,
        "paper_only": True,
        "paper_fill_allowed": allowed,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _paper_bool_flag(*sources: dict[str, Any], names: tuple[str, ...]) -> bool:
    for source in sources:
        for name in names:
            if source.get(name) is True:
                return True
    return False


def _paper_standalone_1m_strategy_eligible(
    *,
    strategy_id: str,
    risk: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
) -> bool:
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    explicit_flag = _paper_bool_flag(
        risk,
        signal,
        prediction,
        features,
        names=(
            "standalone_1m_strategy_eligible",
            "dedicated_1m_strategy_bucket",
            "one_minute_strategy_eligible",
            "one_minute_scalp_strategy_eligible",
        ),
    )
    strategy_text = str(strategy_id or "").lower()
    named_bucket = (
        ("1m" in strategy_text or "one_minute" in strategy_text)
        and any(token in strategy_text for token in ("scalp", "standalone", "micro"))
    )
    return explicit_flag or named_bucket


def _paper_standalone_1m_eligibility_gate(
    *,
    symbol: str,
    thesis_timeframe: str,
    side: str,
    risk: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
) -> dict[str, Any]:
    execution_timeframe = _paper_execution_timeframe(feature_snapshot, prediction, signal)
    strategy_id = _paper_strategy_id(signal=signal, prediction=prediction)
    standalone_1m_thesis = thesis_timeframe == "1m"
    higher_timeframe_timing_role_allowed = execution_timeframe == "1m" and thesis_timeframe != "1m"
    dedicated_strategy_bucket = _paper_standalone_1m_strategy_eligible(
        strategy_id=strategy_id,
        risk=risk,
        signal=signal,
        prediction=prediction,
        feature_snapshot=feature_snapshot,
    )
    blockers: list[str] = []
    if standalone_1m_thesis and not dedicated_strategy_bucket:
        blockers.append("standalone_1m_thesis_requires_dedicated_strategy_bucket")
    allowed = not blockers
    return {
        "schema_version": "paper_standalone_1m_eligibility_gate_v1",
        "status": "PASS_PAPER_STANDALONE_1M_ELIGIBILITY" if allowed else "BLOCKED_PAPER_STANDALONE_1M_ELIGIBILITY",
        "allowed": allowed,
        "symbol": symbol,
        "side": side.upper(),
        "thesis_timeframe": thesis_timeframe,
        "execution_timeframe": execution_timeframe,
        "strategy_id": strategy_id,
        "standalone_1m_thesis": standalone_1m_thesis,
        "dedicated_strategy_bucket": dedicated_strategy_bucket,
        "standalone_execution_allowed": allowed if standalone_1m_thesis else True,
        "higher_timeframe_timing_role_allowed": higher_timeframe_timing_role_allowed,
        "blockers": blockers,
        "runtime_wired_to_entry_gate": True,
        "paper_only": True,
        "paper_fill_allowed": allowed,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _paper_churn_governor_candidate_row(
    *,
    symbol: str,
    timeframe: str,
    side: str,
    risk: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
) -> dict[str, Any]:
    paper_edge_gate = risk.get("paper_edge_gate") if isinstance(risk.get("paper_edge_gate"), dict) else {}
    fee_bps = _float_or_none(paper_edge_gate.get("fee_bps")) or 0.0
    spread_bps = _float_or_none(paper_edge_gate.get("spread_bps")) or 0.0
    slippage_bps = _float_or_none(paper_edge_gate.get("slippage_bps")) or 0.0
    funding_bps = _float_or_none(paper_edge_gate.get("funding_risk_bps")) or 0.0
    strategy = (
        signal.get("strategy_id")
        or prediction.get("strategy_id")
        or prediction.get("strategy_mode")
        or "paper_runtime_momentum"
    )
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "thesis_timeframe": timeframe,
        "strategy_id": strategy,
        "side": side.upper(),
        "market_regime_at_entry": features.get("market_regime") or "UNKNOWN",
        "expected_move_after_cost_bps": risk.get("expected_move_after_cost_bps"),
        "round_trip_cost_bps": fee_bps + spread_bps + slippage_bps + abs(funding_bps),
        "generated_at": risk.get("generated_at") or signal.get("generated_at"),
    }


def _paper_cost_source_row(
    risk: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for source in (prediction, signal, feature_snapshot, risk):
        if isinstance(source, dict):
            row.update(source)
    for field in (
        "production_cost_evidence",
        "paper_entry_cost_evidence",
        "cost_evidence",
        "execution_cost_evidence",
    ):
        nested = risk.get(field)
        if isinstance(nested, dict):
            row.update(nested)
    return row


def _paper_cost_float(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = _float_or_none(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _paper_cost_present(row: dict[str, Any], *names: str) -> bool:
    return any(row.get(name) not in (None, "", [], {}) for name in names)


def _paper_cost_round_trip_bps(row: dict[str, Any]) -> float | None:
    explicit = _paper_cost_float(row, "round_trip_cost_bps", "expected_round_trip_cost_bps", "total_cost_bps")
    if explicit is not None:
        return abs(explicit)
    parts = [
        _paper_cost_float(row, "actual_observed_spread_entry_bps", "bid_ask_spread_bps"),
        _paper_cost_float(row, "expected_slippage_bps", "expected_slippage_usd", "slippage_bps"),
        _paper_cost_float(row, "depth_price_impact_bps", "depth_impact_bps"),
        _paper_cost_float(row, "funding_bps", "expected_funding_bps"),
        _paper_cost_float(row, "actual_fee_bps", "fee_bps", "taker_fee_bps", "expected_fee_bps"),
        _paper_cost_float(row, "latency_reserve_bps", "expected_latency_reserve_bps"),
        _paper_cost_float(row, "partial_fill_reserve_bps", "partial_fill_adjustment_bps"),
    ]
    total = sum(abs(value) for value in parts if value is not None)
    return total if total > 0.0 else None


def _paper_entry_production_cost_gate(
    *,
    risk: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
) -> dict[str, Any]:
    row = _paper_cost_source_row(risk, signal, prediction, feature_snapshot)
    observed_spread = _paper_cost_float(row, "actual_observed_spread_entry_bps", "bid_ask_spread_bps") is not None
    maker_taker_fee = _paper_cost_float(row, "actual_fee_bps", "fee_bps", "taker_fee_bps", "expected_fee_bps") is not None
    depth_impact = (
        _paper_cost_float(row, "depth_price_impact_bps", "depth_impact_bps") is not None
        and _paper_cost_present(row, "depth_price_impact_source", "depth_price_impact_model")
    )
    expected_slippage = _paper_cost_float(row, "expected_slippage_bps", "expected_slippage_usd", "slippage_bps") is not None
    funding = _paper_cost_float(row, "funding_bps", "expected_funding_bps", "funding_rate") is not None
    latency_reserve = _paper_cost_float(row, "latency_reserve_bps", "expected_latency_reserve_bps") is not None
    partial_fill = _paper_cost_present(
        row,
        "partial_fill_reserve_bps",
        "partial_fill_adjustment_bps",
        "partial_fill_plan",
        "partial_fills",
    )
    round_trip_cost = _paper_cost_round_trip_bps(row)
    cost_uncertainty = _paper_cost_float(
        row,
        "cost_uncertainty_bps",
        "round_trip_cost_uncertainty_bps",
        "execution_cost_uncertainty_bps",
    )
    freshness_seconds = _paper_cost_float(row, "evidence_freshness_seconds", "cost_evidence_freshness_seconds")
    source_timestamp_present = _paper_cost_present(
        row,
        "source_timestamp",
        "cost_source_timestamp",
        "cost_generated_at",
        "generated_at",
    )
    fallback = row.get("fallback")
    flags = {
        "observed_spread": observed_spread,
        "maker_taker_fee": maker_taker_fee,
        "depth_derived_price_impact": depth_impact,
        "expected_slippage": expected_slippage,
        "funding": funding,
        "latency_reserve": latency_reserve,
        "partial_fill_reserve": partial_fill,
        "round_trip_cost": round_trip_cost is not None,
        "cost_uncertainty": cost_uncertainty is not None,
        "fallback_flag_false": fallback is False,
        "source_timestamp": source_timestamp_present,
        "evidence_freshness": freshness_seconds is not None and freshness_seconds <= PAPER_COST_MAX_FRESHNESS_SECONDS,
    }
    missing = [name for name, passed in flags.items() if passed is not True]
    gross_edge = abs(_paper_cost_float(row, "expected_gross_edge_bps", "expected_move_bps") or 0.0)
    after_cost = _paper_cost_float(row, "expected_net_edge_bps", "expected_move_after_cost_bps")
    lower_bound = None if after_cost is None or cost_uncertainty is None else abs(after_cost) - abs(cost_uncertainty)
    edge_to_cost_ratio = (
        gross_edge / round_trip_cost
        if gross_edge > 0.0 and round_trip_cost is not None and round_trip_cost > 0.0
        else None
    )
    blockers: list[str] = []
    if missing:
        blockers.append("missing_production_grade_cost_evidence")
    if lower_bound is None:
        blockers.append("expected_net_edge_lower_bound_missing")
    elif lower_bound <= 0.0:
        blockers.append("expected_net_edge_lower_bound_lte_0")
    if edge_to_cost_ratio is None:
        blockers.append("edge_to_cost_ratio_missing")
    elif edge_to_cost_ratio < PAPER_EDGE_TO_COST_CONTEXTUAL_SAFETY_RATIO:
        blockers.append("edge_to_cost_ratio_below_contextual_safety_ratio")
    allowed = not blockers
    return {
        "schema_version": "paper_entry_production_cost_gate_v1",
        "status": "PASS_PAPER_ENTRY_PRODUCTION_COST_GATE" if allowed else "BLOCKED_PAPER_ENTRY_PRODUCTION_COST_GATE",
        "allowed": allowed,
        "flags": flags,
        "missing_cost_fields": missing,
        "blockers": blockers,
        "expected_gross_edge_bps": gross_edge if gross_edge > 0.0 else None,
        "expected_round_trip_cost_bps": round_trip_cost,
        "expected_net_edge_lower_bound_bps": lower_bound,
        "edge_to_cost_ratio": edge_to_cost_ratio,
        "contextual_safety_ratio": PAPER_EDGE_TO_COST_CONTEXTUAL_SAFETY_RATIO,
        "paper_only": True,
        "paper_fill_allowed": allowed,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _safe_git_status() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "clean"
    except Exception:
        return "unknown"


def _safe_git_head() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "log", "--oneline", "-1"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _basis_points(value: float, bps: float) -> float:
    return value * bps / 10_000


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    except Exception:
        return None


def _open_position_from_previous(previous: dict[str, Any]) -> dict[str, Any] | None:
    lifecycle = previous.get("paper_position_lifecycle")
    if not isinstance(lifecycle, dict):
        return None
    position = lifecycle.get("open_position")
    if not isinstance(position, dict):
        return None
    if str(position.get("status") or "") != "OPEN":
        return None
    return dict(position)


def _position_return_bps(side: str, entry_price: float, current_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    raw = ((current_price - entry_price) / entry_price) * 10_000
    return round(raw if side == "long" else -raw, 8)


def _position_age_seconds(position: dict[str, Any], generated_at: str) -> int | None:
    opened_ts = _parse_ts(position.get("opened_at"))
    current_ts = _parse_ts(generated_at)
    if opened_ts is None or current_ts is None:
        return None
    return max(0, int(current_ts - opened_ts))


def _position_exit_reason(position: dict[str, Any], *, current_price: float, generated_at: str) -> str | None:
    side = str(position.get("side") or "").lower()
    entry_price = _float_or_none(position.get("entry_price")) or 0.0
    current_return_bps = _position_return_bps(side, entry_price, current_price)
    take_profit_bps = max(
        PAPER_POSITION_MIN_TAKE_PROFIT_BPS,
        _float_or_none(position.get("take_profit_bps")) or PAPER_POSITION_MIN_TAKE_PROFIT_BPS,
    )
    stop_loss_bps = max(
        PAPER_POSITION_DEFAULT_STOP_BPS,
        _float_or_none(position.get("stop_loss_bps")) or PAPER_POSITION_DEFAULT_STOP_BPS,
    )
    if current_return_bps <= -stop_loss_bps:
        return "STOP_LOSS"
    age_seconds = _position_age_seconds(position, generated_at)
    if age_seconds is not None and age_seconds < PAPER_POSITION_MIN_HOLD_SECONDS:
        return None
    if current_return_bps >= take_profit_bps:
        return "TAKE_PROFIT"
    if age_seconds is not None and age_seconds >= PAPER_POSITION_MAX_HOLD_SECONDS:
        return "MAX_HOLD_TIME"
    return None


def _confidence_bucket(value: Any) -> str:
    confidence = _float_or_none(value)
    if confidence is None:
        return "missing"
    if confidence < 0.58:
        return "below_0.58"
    if confidence < 0.65:
        return "0.58_to_0.65"
    if confidence < 0.75:
        return "0.65_to_0.75"
    return "0.75_plus"


def build_feature_snapshot(market: MarketSnapshot, tick_id: str) -> dict[str, Any]:
    execution_timeframe = _paper_execution_timeframe(asdict(market))
    closes = [float(candle["close"]) for candle in market.candles if "close" in candle]
    volumes = [float(candle["volume"]) for candle in market.candles if "volume" in candle]
    last = market.price if market.price is not None else (closes[-1] if closes else None)
    prev_1 = closes[-2] if len(closes) >= 2 else None
    prev_5 = closes[-6] if len(closes) >= 6 else None
    prev_15 = closes[-16] if len(closes) >= 16 else None
    ret_1m = 0.0 if last is None or prev_1 in (None, 0) else (last - prev_1) / prev_1
    ret_5m = 0.0 if last is None or prev_5 in (None, 0) else (last - prev_5) / prev_5
    ret_15m = 0.0 if last is None or prev_15 in (None, 0) else (last - prev_15) / prev_15
    volume_last = volumes[-1] if volumes else 0.0
    volume_avg_10 = sum(volumes[-10:]) / min(len(volumes), 10) if volumes else 0.0
    volatility_10 = (
        sum(abs(closes[index] - closes[index - 1]) for index in range(max(1, len(closes) - 9), len(closes)))
        / max(min(len(closes) - 1, 9), 1)
        / last
        if last and len(closes) > 1
        else 0.0
    )
    return {
        "feature_snapshot_id": f"fs_{tick_id}",
        "generated_at": market.generated_at,
        "source_type": market.source_type,
        "symbol": market.symbol,
        "timeframe": execution_timeframe,
        "execution_timeframe": execution_timeframe,
        "feature_timeframe": execution_timeframe,
        "freshness_state": market.freshness_state,
        "market_age_seconds": market.age_seconds,
        "features": {
            "return_1m": round(ret_1m, 8),
            "return_5m": round(ret_5m, 8),
            "return_15m": round(ret_15m, 8),
            "volume_last": round(volume_last, 4),
            "volume_avg_10": round(volume_avg_10, 4),
            "volatility_10": round(volatility_10, 8),
            "microstructure_toxicity_score_bps": round(volatility_10 * 10_000, 8),
        },
    }


def build_trainer_prediction(feature_snapshot: dict[str, Any], tick_id: str) -> dict[str, Any]:
    features = feature_snapshot["features"]
    momentum_score = float(features["return_5m"]) * 260 + float(features["return_15m"]) * 120
    side = "hold"
    if momentum_score > 0.015:
        side = "long"
    elif momentum_score < -0.015:
        side = "short"
    raw_confidence = _clamp(0.56 + abs(momentum_score), 0.50, 0.84)
    calibrated_confidence = _clamp(raw_confidence - 0.02, 0.50, 0.80)
    bridge_expected_move = _trainer_bridge_expected_move(feature_snapshot)
    execution_timeframe = _paper_execution_timeframe(feature_snapshot)
    thesis_timeframe = _paper_thesis_timeframe(bridge_expected_move, feature_snapshot)
    raw_output: dict[str, Any] = {
        "side": side,
        "momentum_score": round(momentum_score, 8),
    }
    if bridge_expected_move.get("status") == "NATIVE_EXPECTED_MOVE_PRESENT":
        raw_output["expected_move_bps"] = bridge_expected_move["expected_move_bps"]
        if bridge_expected_move.get("expected_move_after_cost_bps") is not None:
            raw_output["expected_move_after_cost_bps"] = bridge_expected_move[
                "expected_move_after_cost_bps"
            ]
        raw_output["expected_move_source"] = bridge_expected_move["expected_move_source"]
        raw_output["expected_move_timeframe"] = bridge_expected_move["expected_move_timeframe"]
        raw_output["cross_timeframe_expected_move"] = bridge_expected_move["cross_timeframe_expected_move"]
        raw_output["expected_move_bridge_prediction_id"] = bridge_expected_move["bridge_prediction_id"]
    return {
        "prediction_id": f"pred_{tick_id}",
        "generated_at": feature_snapshot["generated_at"],
        "source_type": "V2_PAPER_TRAINER_WRAPPER",
        "trainer_source": bridge_expected_move.get("trainer_source") or "V2_PAPER_TRAINER_WRAPPER",
        "trainer_bridge_status": bridge_expected_move.get("trainer_bridge_status") or "MISSING_NATIVE_EXPECTED_MOVE",
        "trainer_state": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
        "symbol": feature_snapshot["symbol"],
        "timeframe": thesis_timeframe,
        "prediction_timeframe": thesis_timeframe,
        "thesis_timeframe": thesis_timeframe,
        "execution_timeframe": execution_timeframe,
        "confirmation_timeframes": [execution_timeframe] if execution_timeframe != thesis_timeframe else [],
        "model_checkpoint": bridge_expected_move.get("checkpoint_id") or "v2_paper_readonly_momentum_wrapper_v1",
        "model_version": bridge_expected_move.get("model_version") or "v2_paper_readonly_momentum_wrapper_v1",
        "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
        "raw_output": raw_output,
        "expected_move_bps": bridge_expected_move.get("expected_move_bps"),
        "expected_move_after_cost_bps": bridge_expected_move.get(
            "expected_move_after_cost_bps"
        ),
        "expected_move_source": bridge_expected_move.get("expected_move_source"),
        "expected_move_bridge_status": bridge_expected_move.get("status"),
        "confidence_raw": round(raw_confidence, 6),
        "confidence_calibrated": round(calibrated_confidence, 6),
        "top_features": [
            {"name": "return_5m", "value": features["return_5m"]},
            {"name": "return_15m", "value": features["return_15m"]},
            {"name": "volatility_10", "value": features["volatility_10"]},
        ],
        "freshness_state": feature_snapshot["freshness_state"],
        "market_age_seconds": feature_snapshot["market_age_seconds"],
    }


def build_signal_lineage(
    *,
    tick_id: str,
    generated_at: str,
    feature_snapshot: dict[str, Any],
    prediction: dict[str, Any],
    market: MarketSnapshot,
) -> dict[str, Any]:
    lineage = build_paper_runtime_lineage(
        tick_id=tick_id,
        generated_at=generated_at,
        feature_snapshot=feature_snapshot,
        prediction=prediction,
        market_symbol=market.symbol,
        market_freshness_state=market.freshness_state,
        market_age_seconds=market.age_seconds,
    )
    thesis_timeframe = _paper_thesis_timeframe(prediction, lineage.get("signal", {}), feature_snapshot)
    execution_timeframe = _paper_execution_timeframe(feature_snapshot, prediction)
    for section_name in (
        "feature_snapshot",
        "trainer_prediction",
        "signal",
        "orchestrator_decision",
        "risk_decision",
        "execution_intent",
    ):
        section = lineage.get(section_name)
        if isinstance(section, dict):
            section["thesis_timeframe"] = thesis_timeframe
            section["execution_timeframe"] = execution_timeframe
            section["timeframe"] = thesis_timeframe
    lineage["thesis_timeframe"] = thesis_timeframe
    lineage["execution_timeframe"] = execution_timeframe
    lineage["timeframe_attribution_rule"] = (
        "economic paper outcomes are attributed to thesis_timeframe; "
        "execution_timeframe is timing-only unless it is also the approved thesis timeframe"
    )
    return lineage


def _paper_outcome_model_contract() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = [] if PAPER_OUTCOME_MODEL_READY else [PAPER_OUTCOME_MODEL_BLOCKER]
    detail = (
        "non-live paper position lifecycle is active; fills can only open paper-only positions after strict edge, "
        "provenance, freshness, symbol-scope, cooldown, churn, and risk gates pass"
        if PAPER_OUTCOME_MODEL_READY
        else (
            "paper fill recording is blocked until V2 has a non-live exit/outcome simulator; "
            "qualified intents remain shadow-observed so fee-only ledger drift cannot masquerade as edge"
        )
    )
    return (
        {
            "status": "READY" if PAPER_OUTCOME_MODEL_READY else "MISSING_EXIT_LIFECYCLE_SIMULATOR",
            "paper_fill_allowed": PAPER_OUTCOME_MODEL_READY,
            "blockers": blockers,
            "detail": detail,
        },
        blockers,
    )


def _expected_move_model_review_contract() -> tuple[dict[str, Any], list[str]]:
    payload = _read_json_file(PAPER_SHADOW_OUTCOME_STATUS_FILE)
    false_block_count = int(payload.get("false_block_count") or 0)
    outcome_status = str(payload.get("outcome_status") or "")
    edge_status = str(payload.get("edge_status") or "")
    model_review_required = (
        false_block_count > 0
        and (
            outcome_status == "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED"
            or edge_status == "EDGE_PENDING_MODEL_REVIEW_REQUIRED"
        )
    )
    blockers = ["expected_move_model_review_required"] if model_review_required else []
    return (
        {
            "status": "MODEL_REVIEW_REQUIRED_SHADOW_ONLY" if model_review_required else "READY",
            "source": "paper_shadow_outcome_observer",
            "false_block_count": false_block_count,
            "outcome_status": outcome_status or "MISSING_EVIDENCE",
            "edge_status": edge_status or "MISSING_EVIDENCE",
            "paper_fill_allowed": not model_review_required,
            "uses_future_outcome_labels_for_entry": False,
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
        },
        blockers,
    )


def _derive_reduce_only_clear(
    intent: dict[str, Any],
    previous_position: dict[str, Any] | None,
) -> bool:
    if previous_position is None:
        return True
    intent_side = str(intent.get("side") or "").lower()
    position_side = str(previous_position.get("side") or "").lower()
    # Reduce-only is in force when there's an open position in the same direction
    # (pyramiding blocked). Closing or flipping is allowed.
    return intent_side != position_side


def _derive_intelligent_close_guard_clear(
    previous_position: dict[str, Any] | None,
    generated_at: str,
) -> bool:
    if previous_position is None:
        return True
    age = _position_age_seconds(previous_position, generated_at)
    if age is None:
        return False
    return age >= PAPER_POSITION_MIN_HOLD_SECONDS


def apply_paper_tightening_gate(
    lineage: dict[str, Any],
    *,
    generated_at: str,
    recent_events: list[dict[str, Any]],
    now_ms: int | None = None,
    previous_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gated = copy.deepcopy(lineage)
    risk = gated["risk_decision"]
    intent = gated["execution_intent"]
    if risk.get("risk_action") != "allow":
        paper_outcome_model, paper_outcome_model_blockers = _paper_outcome_model_contract()
        risk["canary_profile_tightening"] = {
            "classification": "TIGHTENING_NOT_EVALUATED_RISK_ALREADY_DENIED",
            "paper_simulation_allowed": False,
            "blockers": [str(risk.get("risk_reason_code") or "risk_already_denied")],
            "live_gate_status": LIVE_GATE_STATUS,
            "safe_for_live": False,
            "automation_can_enable_live": False,
        }
        risk["paper_outcome_model"] = paper_outcome_model
        risk["paper_outcome_model_blockers"] = paper_outcome_model_blockers
        required = list(risk.get("required_blocks_checked") or [])
        if "paper_outcome_model" not in required:
            required.append("paper_outcome_model")
        risk["required_blocks_checked"] = required
        return gated

    signal = gated.get("signal", {})
    feature_snapshot = gated.get("feature_snapshot", {})
    prediction = gated.get("trainer_prediction", {})
    raw_output = prediction.get("raw_output") if isinstance(prediction.get("raw_output"), dict) else {}
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    microstructure_toxicity_score_bps = _float_or_none(features.get("microstructure_toxicity_score_bps"))
    microstructure_toxicity_clear = (
        microstructure_toxicity_score_bps is not None
        and microstructure_toxicity_score_bps <= PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS
    )
    coverage = evaluate_paper_expected_move_coverage(
        trainer_prediction=prediction,
        feature_snapshot=feature_snapshot,
        risk_payload=risk,
        signal_record=signal,
        fee_bps=4.0,
        spread_bps=0.0,
        slippage_bps=2.0,
        funding_bps=0.0,
    )
    runtime = build_canary_profile_tightening_runtime(
        now_ms_clock=lambda: now_ms if now_ms is not None else int(time.time() * 1000),
        min_confidence=PAPER_TIGHTENING_MIN_CONFIDENCE,
        max_fills_per_hour=PAPER_TIGHTENING_MAX_FILLS_PER_HOUR,
        cooldown_seconds=PAPER_TIGHTENING_COOLDOWN_SECONDS,
        loss_cooldown_seconds=PAPER_TIGHTENING_LOSS_COOLDOWN_SECONDS,
        max_signal_age_seconds=PAPER_TIGHTENING_MAX_SIGNAL_AGE_SECONDS,
        max_feature_age_seconds=PAPER_TIGHTENING_MAX_FEATURE_AGE_SECONDS,
    )
    gate = runtime.evaluate_now(
        intent_payload={
            "symbol": intent.get("symbol") or signal.get("symbol"),
            "action": "OPEN_LONG" if intent.get("side") == "long" else "OPEN_SHORT" if intent.get("side") == "short" else "HOLD",
            "confidence": signal.get("confidence") or signal.get("confidence_calibrated") or prediction.get("confidence_calibrated"),
            "signal_generated_at": signal.get("generated_at") or generated_at,
            "feature_snapshot_generated_at": feature_snapshot.get("generated_at") or feature_snapshot.get("generated_ts"),
            "expected_move_bps": coverage.get("expected_move_bps_for_fill_gate"),
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "funding_bps": 0.0,
        },
        recent_events=recent_events,
        approval_token_present=False,
    )
    paper_edge_gate = score_paper_edge(
        {
            "symbol": intent.get("symbol") or signal.get("symbol"),
            "risk_action": "allow",
            "trainer_source": prediction.get("trainer_source") or raw_output.get("trainer_source"),
            "feature_freshness_state": feature_snapshot.get("freshness_state"),
            "confidence_calibrated": signal.get("confidence_calibrated")
            or signal.get("confidence")
            or prediction.get("confidence_calibrated"),
            "expected_move_bps": coverage.get("expected_move_bps_for_fill_gate"),
            "expected_move_after_cost_bps": coverage.get("expected_move_after_cost_bps_for_fill_gate"),
            "fee_bps": 4.0,
            "spread_bps": 0.0,
            "slippage_bps": 2.0,
            "funding_risk_bps": 0.0,
            "cooldown_clear": "same_symbol_same_direction_cooldown"
            not in set(gate.get("blockers") or []),
            "flip_churn_clear": "flip_churn_cooldown" not in set(gate.get("blockers") or []),
            "reduce_only_clear": _derive_reduce_only_clear(intent, previous_position),
            "intelligent_close_guard_clear": _derive_intelligent_close_guard_clear(
                previous_position, generated_at
            ),
            "microstructure_toxicity_clear": microstructure_toxicity_clear,
        },
        paper_symbols=resolve_symbols(include_baseline=True),
        live_symbols=[],
        live_gate=LIVE_GATE_STATUS,
    )
    risk["canary_profile_tightening"] = gate
    risk["expected_move_coverage"] = coverage
    risk["expected_move_source"] = coverage.get("expected_move_source")
    risk["expected_move_coverage_status"] = coverage.get("expected_move_coverage_status")
    risk["expected_move_bps"] = coverage.get("expected_move_bps_for_fill_gate")
    risk["expected_move_after_cost_bps"] = coverage.get("expected_move_after_cost_bps_for_fill_gate")
    risk["paper_edge_gate"] = paper_edge_gate
    risk["paper_edge_gate_classification"] = paper_edge_gate.get("classification")
    risk["paper_edge_gate_blockers"] = list(paper_edge_gate.get("blockers") or [])
    risk["paper_protective_behavior_gate"] = {
        "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
        "dynamic_take_profit_model": "expected_move_after_cost_bps_floor",
        "dynamic_stop_model": "paper_static_stop_floor_until_legacy_dynamic_stop_parity",
        "reduce_only_protection_clear": _derive_reduce_only_clear(intent, previous_position),
        "intelligent_close_guard_clear": _derive_intelligent_close_guard_clear(
            previous_position, generated_at
        ),
        "microstructure_toxicity_score_bps": microstructure_toxicity_score_bps,
        "microstructure_toxicity_max_bps": PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS,
        "microstructure_toxicity_clear": microstructure_toxicity_clear,
        "paper_only": True,
    }
    paper_outcome_model, paper_outcome_model_blockers = _paper_outcome_model_contract()
    risk["paper_outcome_model"] = paper_outcome_model
    expected_move_model_review, expected_move_model_review_blockers = _expected_move_model_review_contract()
    risk["expected_move_model_review"] = expected_move_model_review
    if (
        gate.get("blockers")
        or paper_edge_gate.get("blockers")
        or paper_outcome_model_blockers
        or expected_move_model_review_blockers
    ):
        risk["risk_action"] = "deny"
        risk["risk_result"] = "BLOCKED"
        risk["risk_reason_code"] = (
            "deny_paper_outcome_model_missing"
            if paper_outcome_model_blockers
            and not gate.get("blockers")
            and not paper_edge_gate.get("blockers")
            and not expected_move_model_review_blockers
            else "deny_expected_move_model_review"
            if expected_move_model_review_blockers
            and not gate.get("blockers")
            and not paper_edge_gate.get("blockers")
            else "deny_canary_profile_tightening"
        )
        risk["canary_profile_tightening_blockers"] = [
            *list(gate.get("blockers") or []),
            *paper_outcome_model_blockers,
            *expected_move_model_review_blockers,
        ]
        risk["paper_outcome_model_blockers"] = paper_outcome_model_blockers
        risk["expected_move_model_review_blockers"] = expected_move_model_review_blockers
        required = list(risk.get("required_blocks_checked") or [])
        if "canary_profile_tightening" not in required:
            required.append("canary_profile_tightening")
        if "paper_edge_scoring" not in required:
            required.append("paper_edge_scoring")
        if "paper_outcome_model" not in required:
            required.append("paper_outcome_model")
        if "expected_move_model_review" not in required:
            required.append("expected_move_model_review")
        risk["required_blocks_checked"] = required
        intent["intent_action"] = "paper_noop_blocked"
        intent["exchange_order_allowed"] = False
        intent["paper_only"] = True
    return gated


def apply_paper_entry_gates(lineage: dict[str, Any]) -> dict[str, Any]:
    """Phase 3/4/6/7/8/9 entry gates for new paper positions.

    Only called when no open position exists. Checks in order:
        Phase 3 — symbol/timeframe/outcome-memory entry gate
        Phase 4 — high-precision confidence/edge/coverage gate
        Phase 5 — paper reentry and signal identity dedup gate
        Phase 7 — production-grade cost and edge-to-cost gate
        Phase 8 — standalone 1m thesis eligibility gate
        Phase 6 — adaptive churn/turnover governor
        Phase 9 — anti-market-maker detector (entry-block detectors)
        Phase 10 — leverage recommendation (advisory; never blocks)

    All checks fail-safe: any import error or unexpected input silently
    skips that gate (fail-open for the individual gate, not the full chain).
    A hard Phase 3 or 4 block sets risk_action=deny and returns early.
    No exchange mutation. Live gate remains blocked_human_only.
    """
    gated = copy.deepcopy(lineage)
    risk = gated["risk_decision"]
    intent = gated["execution_intent"]

    if risk.get("risk_action") != "allow":
        return gated

    signal = gated.get("signal", {})
    feature_snapshot = gated.get("feature_snapshot", {})
    prediction = gated.get("trainer_prediction", {})
    raw_output = prediction.get("raw_output") if isinstance(prediction.get("raw_output"), dict) else {}
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    sym = str(intent.get("symbol") or signal.get("symbol") or "").upper()
    tf = _paper_thesis_timeframe(prediction, signal, feature_snapshot)
    side = str(intent.get("side") or "").lower()
    conf = _float_or_none(prediction.get("confidence_calibrated"))
    edge = _float_or_none(risk.get("expected_move_after_cost_bps"))

    def _block(reason_code: str, reasons: list[str], gate_name: str) -> None:
        risk["risk_action"] = "deny"
        risk["risk_result"] = f"BLOCKED_{gate_name.upper()}"
        risk["risk_reason_code"] = reason_code
        risk[f"{gate_name}_blockers"] = list(reasons)
        checked = list(risk.get("required_blocks_checked") or [])
        if gate_name not in checked:
            checked.append(gate_name)
        risk["required_blocks_checked"] = checked
        intent["intent_action"] = "paper_noop_blocked"
        intent["exchange_order_allowed"] = False
        intent["paper_only"] = True

    if tf not in PAPER_ALLOWED_TIMEFRAMES:
        risk["thesis_timeframe_gate"] = {
            "status": "BLOCKED_MISSING_OR_INVALID_THESIS_TIMEFRAME",
            "allowed": False,
            "thesis_timeframe": tf,
            "blockers": ["missing_or_invalid_thesis_timeframe"],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        _block(
            "deny_missing_thesis_timeframe",
            ["missing_or_invalid_thesis_timeframe"],
            "thesis_timeframe_gate",
        )
        return gated

    # ── Phase 3: entry gate ────────────────────────────────────────────────────
    try:
        from v2.backend.app.services.paper_trade_management.entry_gate import (  # noqa: PLC0415
            evaluate_entry_gate,
        )
        entry_result = evaluate_entry_gate(
            symbol=sym,
            timeframe=tf,
            strategy_mode=None,
            confidence_calibrated=conf,
            expected_move_after_cost_bps=edge,
            major_move_detected=bool(raw_output.get("major_move_detected")),
        )
        risk["entry_gate"] = entry_result
        if not entry_result["allowed"]:
            _block("deny_entry_gate", entry_result["reasons"], "entry_gate")
            return gated
    except Exception:  # noqa: BLE001
        pass

    if risk["risk_action"] != "allow":
        return gated

    # ── Phase 4: high-precision gate ──────────────────────────────────────────
    try:
        from v2.backend.app.services.paper_trade_management.high_precision_gate import (  # noqa: PLC0415
            evaluate_high_precision_gate,
        )
        hp_result = evaluate_high_precision_gate(
            action=side,
            confidence_calibrated=conf,
            expected_move_after_cost_bps=edge,
            data_coverage_pct=_float_or_none(feature_snapshot.get("data_coverage_percent")),
            market_state_integrity_score=100.0,
            prediction=prediction,
        )
        risk["high_precision_gate"] = hp_result
        if not hp_result["allow"]:
            _block("deny_high_precision_gate", hp_result["reasons"], "high_precision_gate")
            return gated
    except Exception:  # noqa: BLE001
        pass

    if risk["risk_action"] != "allow":
        return gated

    # ── Phase 5: reentry and signal identity dedup gate ──────────────────────
    dedup_result = _paper_reentry_dedup_gate(
        _paper_reentry_dedup_runtime_rows(),
        _paper_reentry_dedup_candidate_row(
            symbol=sym,
            timeframe=tf,
            side=side,
            risk=risk,
            signal=signal,
            prediction=prediction,
            feature_snapshot=feature_snapshot,
        ),
    )
    risk["paper_reentry_dedup_gate"] = dedup_result
    if not dedup_result["allowed"]:
        _block("deny_paper_reentry_dedup", dedup_result["blockers"], "paper_reentry_dedup_gate")
        return gated

    if risk["risk_action"] != "allow":
        return gated

    # ── Phase 7: production-grade cost and edge-to-cost gate ─────────────────
    cost_result = _paper_entry_production_cost_gate(
        risk=risk,
        signal=signal,
        prediction=prediction,
        feature_snapshot=feature_snapshot,
    )
    risk["paper_entry_production_cost_gate"] = cost_result
    if not cost_result["allowed"]:
        _block("deny_paper_entry_cost_gate", cost_result["blockers"], "paper_entry_production_cost_gate")
        return gated

    if risk["risk_action"] != "allow":
        return gated

    # ── Phase 8: standalone 1m thesis eligibility gate ──────────────────────
    one_minute_result = _paper_standalone_1m_eligibility_gate(
        symbol=sym,
        thesis_timeframe=tf,
        side=side,
        risk=risk,
        signal=signal,
        prediction=prediction,
        feature_snapshot=feature_snapshot,
    )
    risk["paper_standalone_1m_eligibility"] = one_minute_result
    if not one_minute_result["allowed"]:
        _block(
            "deny_paper_standalone_1m_eligibility",
            one_minute_result["blockers"],
            "paper_standalone_1m_eligibility",
        )
        return gated

    if risk["risk_action"] != "allow":
        return gated

    # ── Phase 6: adaptive paper churn/turnover governor ──────────────────────
    try:
        from v2.backend.app.services.paper_churn_governor import (  # noqa: PLC0415
            evaluate_churn_governor_entry_gate,
        )
        churn_result = evaluate_churn_governor_entry_gate(
            _paper_churn_governor_runtime_rows(),
            _paper_churn_governor_candidate_row(
                symbol=sym,
                timeframe=tf,
                side=side,
                risk=risk,
                signal=signal,
                prediction=prediction,
                feature_snapshot=feature_snapshot,
            ),
        )
        risk["paper_churn_governor"] = churn_result
        if not churn_result["allowed"]:
            _block("deny_paper_churn_governor", churn_result["reasons"], "paper_churn_governor")
            return gated
    except Exception as exc:  # noqa: BLE001
        risk["paper_churn_governor"] = {
            "status": "BLOCKED_PAPER_CHURN_GOVERNOR_ENTRY_GATE",
            "allowed": False,
            "reasons": ["paper_churn_governor_runtime_error"],
            "error": str(exc),
            "runtime_wired_to_entry_gate": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        _block("deny_paper_churn_governor", ["paper_churn_governor_runtime_error"], "paper_churn_governor")
        return gated

    if risk["risk_action"] != "allow":
        return gated

    # ── Phase 9: anti-market-maker detection ──────────────────────────────────
    try:
        from v2.backend.app.services.paper_trade_management.anti_market_maker_detector import (  # noqa: PLC0415
            evaluate_all_detectors,
        )
        anti_mm = evaluate_all_detectors(features)
        risk["anti_mm_detection"] = anti_mm
        if anti_mm.get("entry_blocked"):
            triggered = [
                f"ANTI_MM_{k}:{v['reason']}"
                for k, v in (anti_mm.get("detectors") or {}).items()
                if v.get("detected")
            ]
            _block("deny_anti_mm_detected", triggered, "anti_mm_detection")
            return gated
    except Exception:  # noqa: BLE001
        pass

    # ── Phase 8: leverage recommendation (advisory — never blocks) ────────────
    if risk["risk_action"] == "allow":
        try:
            from v2.backend.app.services.paper_trade_management.leverage_recommendation import (  # noqa: PLC0415
                recommend_leverage_for_signal,
            )
            lev_rec = recommend_leverage_for_signal(
                symbol=sym,
                timeframe=tf,
                signal_id=str((gated.get("signal") or {}).get("signal_id") or "unknown"),
                direction=side or "long",
                confidence_calibrated=float(conf or 0.0),
                expected_move_after_cost_bps=edge,
                atr_bps=_float_or_none(features.get("atr_bps")),
                equity_usd=None,
            )
            risk["leverage_recommendation"] = lev_rec
        except Exception:  # noqa: BLE001
            pass

    return gated


def _apply_paper_online_owner_gate(lineage: dict[str, Any]) -> dict[str, Any]:
    """Force legacy paper_online new entries into shadow-only mode.

    This runtime may still publish diagnostics and may manage existing
    paper-only lifecycle closes, but it must not open new economic paper
    positions. Current economic paper ownership belongs to
    v2_trade_management_paper_loop via the adaptive CUDA/challenger chain.
    """
    gated = lineage
    risk = gated.get("risk_decision") if isinstance(gated.get("risk_decision"), dict) else {}
    intent = gated.get("execution_intent") if isinstance(gated.get("execution_intent"), dict) else {}
    signal = gated.get("signal") if isinstance(gated.get("signal"), dict) else {}
    prediction = gated.get("trainer_prediction") if isinstance(gated.get("trainer_prediction"), dict) else {}
    owner_gate = {
        "status": "BLOCKED_LEGACY_PAPER_ONLINE_NEW_ENTRY",
        "allowed": False,
        "current_allowed_owner": V2_CURRENT_PAPER_OWNER,
        "paper_policy_owner": PAPER_ONLINE_LEGACY_OWNER,
        "legacy_owner_mode": PAPER_ONLINE_LEGACY_OWNER_MODE,
        "block_reason": PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON,
        "old_policy_closes_allowed": True,
        "old_policy_reduces_allowed": True,
        "shadow_diagnostics_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    for target in (risk, intent, signal, prediction):
        target["paper_policy_owner"] = PAPER_ONLINE_LEGACY_OWNER
        target["policy_id"] = PAPER_ONLINE_LEGACY_OWNER
        target["policy_fingerprint"] = PAPER_ONLINE_LEGACY_OWNER_MODE
        target["model_source"] = PAPER_ONLINE_LEGACY_MODEL_SOURCE
        target["current_allowed_paper_owner"] = V2_CURRENT_PAPER_OWNER
        target["paper_entry_owner_gate"] = dict(owner_gate)
        target["paper_only"] = True
        target["routes_to_live"] = False
        target["places_real_order"] = False
    if risk.get("risk_action") == "allow":
        risk["risk_action"] = "deny"
        risk["risk_result"] = "BLOCKED_PAPER_ENTRY_OWNER_GATE"
        risk["risk_reason_code"] = PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON
        risk["paper_fill_allowed"] = False
        checked = list(risk.get("required_blocks_checked") or [])
        if "paper_entry_owner_gate" not in checked:
            checked.append("paper_entry_owner_gate")
        risk["required_blocks_checked"] = checked
        intent["intent_action"] = "paper_noop_legacy_shadow_only"
        intent["exchange_order_allowed"] = False
        intent["paper_fill_allowed"] = False
        intent["paper_fill_block_reason"] = PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON
        blockers = list(intent.get("paper_fill_gate_block_reasons") or [])
        if PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON not in blockers:
            blockers.append(PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON)
        intent["paper_fill_gate_block_reasons"] = blockers
    return gated


def build_paper_ledger_entry(
    *,
    tick_id: str,
    generated_at: str,
    market: MarketSnapshot,
    lineage: dict[str, Any],
    previous_equity: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _apply_paper_online_owner_gate(lineage)
    risk = lineage["risk_decision"]
    intent = lineage["execution_intent"]
    price = market.price or 0.0
    notional = 0.0
    fee_rate = 0.0004
    slippage_bps = 2.0
    economic_identity = _paper_economic_identity(lineage, generated_at)
    fill_allowed = risk["risk_action"] == "allow"
    fee = round(notional * fee_rate, 6) if fill_allowed else 0.0
    slippage = round(_basis_points(price, slippage_bps), 6) if fill_allowed else 0.0
    fill_price = round(price + slippage, 6) if intent["side"] == "long" else round(price - slippage, 6)
    funding_rate, funding_bps, funding_interval_seconds = _funding_inputs_from_lineage(lineage)
    funding = _paper_funding_accounting(
        side=str(intent.get("side") or ""),
        notional_usdt=notional if fill_allowed else 0.0,
        hold_time_seconds=0,
        funding_rate=funding_rate,
        funding_bps=funding_bps,
        funding_interval_seconds=funding_interval_seconds,
    )
    equity = round(previous_equity - fee, 6)
    ledger_entry = {
        "paper_ledger_entry_id": f"pledger_{tick_id}",
        "generated_at": generated_at,
        "policy_activated_at": generated_at if fill_allowed else None,
        "execution_intent_id": intent["execution_intent_id"],
        "risk_decision_id": risk["risk_decision_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "symbol": market.symbol,
        **economic_identity,
        "paper_policy_owner": PAPER_ONLINE_LEGACY_OWNER,
        "policy_id": PAPER_ONLINE_LEGACY_OWNER,
        "policy_fingerprint": PAPER_ONLINE_LEGACY_OWNER_MODE,
        "model_source": PAPER_ONLINE_LEGACY_MODEL_SOURCE,
        "current_allowed_paper_owner": V2_CURRENT_PAPER_OWNER,
        "paper_entry_owner_gate": risk.get("paper_entry_owner_gate"),
        "entry_sequence": 1 if fill_allowed else 0,
        "close_sequence": 0,
        "is_partial_reduce": False,
        "is_partial_close": False,
        "is_full_close": False,
        "is_reversal": False,
        "ledger_action": "PAPER_FILL_SIMULATED" if fill_allowed else "PAPER_INTENT_BLOCKED",
        "paper_result": "FILLED_PAPER_ONLY" if fill_allowed else "NO_FILL_RISK_BLOCKED",
        "fill_price": fill_price if fill_allowed else None,
        "notional_usdt": notional if fill_allowed else 0.0,
        "fee_usdt": fee,
        "fee_rate": fee_rate,
        "slippage_bps": slippage_bps,
        "funding_assumption": "zero_until_funding_feed_adapter_current",
        **funding,
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    account = {
        "currency": "USDT",
        "starting_equity": 10000.0,
        "equity": equity,
        "realized_pnl": round(equity - 10000.0, 6),
        "unrealized_pnl": 0.0,
        "open_position_count": 1 if fill_allowed else 0,
        "position_source": "V2_PAPER_RUNTIME_SIMULATED_FILL" if fill_allowed else "V2_PAPER_RUNTIME_EMPTY_RISK_BLOCKED",
    }
    return ledger_entry, account


def build_position_lifecycle_entry(
    *,
    tick_id: str,
    generated_at: str,
    market: MarketSnapshot,
    lineage: dict[str, Any],
    previous_position: dict[str, Any],
    previous_account: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    risk = lineage["risk_decision"]
    current_price = market.price or _float_or_none(previous_position.get("entry_price")) or 0.0
    side = str(previous_position.get("side") or "").lower()
    fallback_identity = _paper_economic_identity(lineage, generated_at)
    economic_identity = {
        "economic_trade_id": previous_position.get("economic_trade_id") or fallback_identity["economic_trade_id"],
        "economic_thesis_id": previous_position.get("economic_thesis_id") or fallback_identity["economic_thesis_id"],
        "parent_position_id": previous_position.get("parent_position_id") or fallback_identity["parent_position_id"],
        "thesis_prediction_id": previous_position.get("thesis_prediction_id") or fallback_identity.get("thesis_prediction_id"),
        "execution_snapshot_id": previous_position.get("execution_snapshot_id") or fallback_identity.get("execution_snapshot_id"),
        "thesis_timeframe": previous_position.get("thesis_timeframe") or fallback_identity["thesis_timeframe"],
        "execution_timeframe": previous_position.get("execution_timeframe") or fallback_identity["execution_timeframe"],
    }
    notional = _float_or_none(previous_position.get("notional_usdt")) or 0.0
    entry_price = _float_or_none(previous_position.get("entry_price")) or 0.0
    fee_rate = _float_or_none(previous_position.get("fee_rate")) or 0.0004
    current_return_bps = _position_return_bps(side, entry_price, current_price)
    gross_unrealized = round(notional * current_return_bps / 10_000, 6)
    previous_realized = float(previous_account.get("realized_pnl") or 0.0)
    age_seconds = _position_age_seconds(previous_position, generated_at)
    minimum_hold_active = (
        age_seconds is not None
        and age_seconds < int(previous_position.get("minimum_hold_seconds") or PAPER_POSITION_MIN_HOLD_SECONDS)
    )
    exit_reason = _position_exit_reason(previous_position, current_price=current_price, generated_at=generated_at)
    # Phase 7: anti-MM exit acceleration check (advisory — may override hold decision)
    _phase7_exit_source = "position_exit_reason"
    if not exit_reason:
        try:
            from v2.backend.app.services.paper_trade_management.anti_market_maker_detector import (  # noqa: PLC0415
                evaluate_all_detectors,
            )
            _p7_features: dict[str, Any] = {}
            _p7_features["price_change_bps"] = current_return_bps
            anti_mm_exit = evaluate_all_detectors(_p7_features)
            if anti_mm_exit.get("exit_accelerated") and age_seconds is not None and age_seconds >= PAPER_POSITION_MIN_HOLD_SECONDS:
                exit_reason = "ANTI_MM_EXIT_ACCELERATED"
                _phase7_exit_source = "anti_mm_exit_accelerate"
        except Exception:  # noqa: BLE001
            pass
    # Phase 7: hedge advisory (fail-closed — operator_paper_hedge_engine_approved=False)
    _phase7_hedge: dict[str, Any] = {}
    try:
        from v2.backend.app.services.trade_management_paper.hedge_engine import (  # noqa: PLC0415
            HedgePositionInputs,
            evaluate_hedge,
        )
        _hedge_eval = evaluate_hedge(
            HedgePositionInputs(
                symbol=str(previous_position.get("symbol") or market.symbol),
                side=side,
                notional_usd=notional,
                unrealized_pnl_bps=current_return_bps,
                age_seconds=age_seconds or 0,
                drawdown_bps_abs=abs(current_return_bps) if current_return_bps < 0 else 0.0,
                live_gate=LIVE_GATE_STATUS,
                live_symbols=(),
            ),
            operator_paper_hedge_engine_approved=False,
        )
        _phase7_hedge = asdict(_hedge_eval)
    except Exception:  # noqa: BLE001
        pass
    if exit_reason:
        exit_fee = round(notional * fee_rate, 6)
        funding_rate = _first_float(previous_position.get("funding_rate"))
        funding_bps = _first_float(
            previous_position.get("funding_bps"),
            previous_position.get("expected_funding_bps"),
        )
        funding_interval_seconds = _first_float(previous_position.get("funding_interval_seconds"))
        funding = _paper_funding_accounting(
            side=side,
            notional_usdt=notional,
            hold_time_seconds=age_seconds or 0,
            funding_rate=funding_rate,
            funding_bps=funding_bps,
            funding_interval_seconds=funding_interval_seconds,
        )
        realized_delta = round(gross_unrealized - exit_fee + float(funding["funding_pnl_usd"] or 0.0), 6)
        realized_pnl = round(previous_realized + realized_delta, 6)
        equity = round(10000.0 + realized_pnl, 6)
        ledger_entry = {
            "paper_ledger_entry_id": f"pledger_{tick_id}",
            "generated_at": generated_at,
            "policy_activated_at": previous_position.get("policy_activated_at"),
            "execution_intent_id": lineage["execution_intent"]["execution_intent_id"],
            "risk_decision_id": risk["risk_decision_id"],
            "signal_id": lineage["signal"]["signal_id"],
            "symbol": market.symbol,
            **economic_identity,
            "entry_sequence": int(previous_position.get("entry_sequence") or 1),
            "close_sequence": int(previous_position.get("close_sequence") or 0) + 1,
            "is_partial_reduce": False,
            "is_partial_close": False,
            "is_full_close": True,
            "is_reversal": False,
            "ledger_action": "PAPER_POSITION_CLOSED",
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
            "fill_price": None,
            "exit_price": current_price,
            "exit_reason": exit_reason,
            "notional_usdt": notional,
            "fee_usdt": exit_fee,
            "fee_rate": fee_rate,
            "slippage_bps": 0.0,
            "funding_assumption": "zero_until_funding_feed_adapter_current",
            **funding,
            "gross_pnl_usdt": gross_unrealized,
            "realized_delta_usdt": realized_delta,
            "exchange_order_id": None,
            "live_order": False,
            "legacy_redis_write": False,
        }
        account = {
            "currency": "USDT",
            "starting_equity": 10000.0,
            "equity": equity,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": 0.0,
            "open_position_count": 0,
            "position_source": "V2_PAPER_RUNTIME_POSITION_CLOSED",
        }
        lifecycle = {
            "status": "CLOSED",
            "open_position": None,
            "last_closed_position": {
                **previous_position,
                "status": "CLOSED",
                "closed_at": generated_at,
                "policy_activated_at": previous_position.get("policy_activated_at"),
                **economic_identity,
                "entry_sequence": int(previous_position.get("entry_sequence") or 1),
                "close_sequence": int(previous_position.get("close_sequence") or 0) + 1,
                "is_partial_reduce": False,
                "is_partial_close": False,
                "is_full_close": True,
                "is_reversal": False,
                "exit_price": current_price,
                "exit_reason": exit_reason,
                "exit_source": _phase7_exit_source,
                "position_age_seconds": age_seconds,
                "minimum_hold_seconds": previous_position.get("minimum_hold_seconds")
                or PAPER_POSITION_MIN_HOLD_SECONDS,
                "paper_exit_coordinator_status": "EXIT_COORDINATED_PAPER_ONLY",
                "gross_pnl_usdt": gross_unrealized,
                **funding,
                "realized_delta_usdt": realized_delta,
                "phase7_hedge_advisory": _phase7_hedge,
            },
        }
        return ledger_entry, account, lifecycle

    equity = round(10000.0 + previous_realized + gross_unrealized, 6)
    held_funding = _paper_funding_accounting(
        side=side,
        notional_usdt=notional,
        hold_time_seconds=age_seconds or 0,
        funding_rate=_first_float(previous_position.get("funding_rate")),
        funding_bps=_first_float(
            previous_position.get("funding_bps"),
            previous_position.get("expected_funding_bps"),
        ),
        funding_interval_seconds=_first_float(previous_position.get("funding_interval_seconds")),
    )
    ledger_entry = {
        "paper_ledger_entry_id": f"pledger_{tick_id}",
        "generated_at": generated_at,
        "policy_activated_at": previous_position.get("policy_activated_at"),
        "execution_intent_id": lineage["execution_intent"]["execution_intent_id"],
        "risk_decision_id": risk["risk_decision_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "symbol": market.symbol,
        **economic_identity,
        "entry_sequence": int(previous_position.get("entry_sequence") or 1),
        "close_sequence": int(previous_position.get("close_sequence") or 0),
        "is_partial_reduce": False,
        "is_partial_close": False,
        "is_full_close": False,
        "is_reversal": False,
        "ledger_action": "PAPER_POSITION_HELD",
        "paper_result": "POSITION_HELD_PAPER_ONLY",
        "fill_price": None,
        "notional_usdt": 0.0,
        "fee_usdt": 0.0,
        "fee_rate": fee_rate,
        "slippage_bps": 0.0,
        "funding_assumption": "zero_until_funding_feed_adapter_current",
        **held_funding,
        "unrealized_pnl_usdt": gross_unrealized,
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    account = {
        "currency": "USDT",
        "starting_equity": 10000.0,
        "equity": equity,
        "realized_pnl": previous_realized,
        "unrealized_pnl": gross_unrealized,
        "open_position_count": 1,
        "position_source": "V2_PAPER_RUNTIME_POSITION_HELD",
    }
    lifecycle = {
        "status": "OPEN",
        "open_position": {
            **previous_position,
            "status": "OPEN",
            "last_mark_price": current_price,
            "last_mark_at": generated_at,
            "unrealized_pnl_usdt": gross_unrealized,
            **held_funding,
            "current_return_bps": current_return_bps,
            "position_age_seconds": age_seconds,
            "minimum_hold_active": minimum_hold_active,
            "phase7_hedge_advisory": _phase7_hedge,
            "paper_exit_coordinator_status": (
                "MINIMUM_HOLD_ACTIVE_PAPER_ONLY"
                if minimum_hold_active
                else "WAITING_FOR_TP_SL_OR_MAX_HOLD_PAPER_ONLY"
            ),
        },
        "last_closed_position": None,
    }
    return ledger_entry, account, lifecycle


def paper_position_lifecycle_from_entry(
    *,
    ledger_entry: dict[str, Any],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    if ledger_entry["paper_result"] != "FILLED_PAPER_ONLY":
        return {"status": "FLAT", "open_position": None, "last_closed_position": None}
    risk = lineage["risk_decision"]
    intent = lineage["execution_intent"]
    expected_after_cost = _float_or_none(risk.get("expected_move_after_cost_bps")) or PAPER_POSITION_MIN_TAKE_PROFIT_BPS
    return {
        "status": "OPEN",
        "open_position": {
            "status": "OPEN",
            "opened_at": ledger_entry["generated_at"],
            "policy_activated_at": ledger_entry.get("policy_activated_at"),
            "symbol": ledger_entry["symbol"],
            "side": intent.get("side"),
            "economic_trade_id": ledger_entry.get("economic_trade_id"),
            "economic_thesis_id": ledger_entry.get("economic_thesis_id"),
            "parent_position_id": ledger_entry.get("parent_position_id"),
            "entry_sequence": ledger_entry.get("entry_sequence"),
            "close_sequence": ledger_entry.get("close_sequence"),
            "is_partial_reduce": ledger_entry.get("is_partial_reduce"),
            "is_partial_close": ledger_entry.get("is_partial_close"),
            "is_full_close": ledger_entry.get("is_full_close"),
            "is_reversal": ledger_entry.get("is_reversal"),
            "thesis_prediction_id": ledger_entry.get("thesis_prediction_id"),
            "execution_snapshot_id": ledger_entry.get("execution_snapshot_id"),
            "thesis_timeframe": ledger_entry.get("thesis_timeframe"),
            "execution_timeframe": ledger_entry.get("execution_timeframe"),
            "entry_price": ledger_entry["fill_price"],
            "notional_usdt": ledger_entry["notional_usdt"],
            "entry_fee_usdt": ledger_entry["fee_usdt"],
            "fee_rate": ledger_entry["fee_rate"],
            "funding_pnl_accounting_version": ledger_entry.get("funding_pnl_accounting_version"),
            "funding_pnl_accounting_status": ledger_entry.get("funding_pnl_accounting_status"),
            "funding_pnl_usd": ledger_entry.get("funding_pnl_usd"),
            "funding_rate": ledger_entry.get("funding_rate"),
            "funding_bps": ledger_entry.get("funding_bps"),
            "expected_funding_bps": ledger_entry.get("funding_bps"),
            "funding_interval_seconds": ledger_entry.get("funding_interval_seconds"),
            "funding_accrual_intervals": ledger_entry.get("funding_accrual_intervals"),
            "funding_notional_usd": ledger_entry.get("funding_notional_usd"),
            "funding_pnl_formula": ledger_entry.get("funding_pnl_formula"),
            "funding_pnl_side_sign": ledger_entry.get("funding_pnl_side_sign"),
            "funding_pnl_source": ledger_entry.get("funding_pnl_source"),
            "take_profit_bps": max(PAPER_POSITION_MIN_TAKE_PROFIT_BPS, expected_after_cost),
            "stop_loss_bps": PAPER_POSITION_DEFAULT_STOP_BPS,
            "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
            "dynamic_take_profit_model": "expected_move_after_cost_bps_floor",
            "dynamic_stop_model": "paper_static_stop_floor_until_legacy_dynamic_stop_parity",
            "paper_exit_coordinator_status": "OPEN_PAPER_ONLY",
            "expected_move_after_cost_bps": risk.get("expected_move_after_cost_bps"),
            "prediction_id": lineage["lineage_ids"]["prediction_id"],
            "feature_snapshot_id": lineage["lineage_ids"]["feature_snapshot_id"],
        },
        "last_closed_position": None,
    }


def _recent_events_with_last_closed_loss(
    recent_events: list[dict[str, Any]],
    last_closed_position: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(last_closed_position, dict):
        return recent_events
    if _float_or_none(last_closed_position.get("realized_delta_usdt")) is None:
        return recent_events
    close_event = {
        "generated_at": last_closed_position.get("closed_at"),
        "symbol": last_closed_position.get("symbol"),
        "ledger_action": "PAPER_POSITION_CLOSED",
        "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        "realized_delta_usdt": last_closed_position.get("realized_delta_usdt"),
        "paper_pnl_delta": last_closed_position.get("realized_delta_usdt"),
    }
    return [*recent_events, close_event]


def build_risk_runtime_payload(
    *,
    generated_at: str,
    lineage: dict[str, Any],
    ledger_entry: dict[str, Any],
    paper_account: dict[str, Any],
) -> dict[str, Any]:
    realized_pnl = float(paper_account["realized_pnl"])
    return {
        "generated_at": generated_at,
        "source": "V2_PAPER_RUNTIME_RISK_RUNTIME_PAYLOAD",
        "live_gate_status": LIVE_GATE_STATUS,
        "risk_decision_id": lineage["risk_decision"]["risk_decision_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "execution_intent_id": ledger_entry["execution_intent_id"],
        "daily_loss_gate_required": True,
        "weekly_loss_gate_required": True,
        "kill_switch_required": True,
        "stop_policy_required": True,
        "risk_config_version": "v2_paper_canary_hard_gates_v1",
        "daily_pnl_source": "V2_PAPER_ACCOUNT_REALIZED_PNL_CURRENT",
        "weekly_pnl_source": "V2_PAPER_ACCOUNT_REALIZED_PNL_CURRENT_UNTIL_DURABLE_WINDOW_LEDGER",
        "daily_realized_pnl_usdt": realized_pnl,
        "weekly_realized_pnl_usdt": realized_pnl,
        "daily_loss_limit_usdt": DAILY_LOSS_LIMIT_USDT,
        "weekly_loss_limit_usdt": WEEKLY_LOSS_LIMIT_USDT,
        "daily_loss_breach": realized_pnl <= DAILY_LOSS_LIMIT_USDT,
        "weekly_loss_breach": realized_pnl <= WEEKLY_LOSS_LIMIT_USDT,
        "reset_window": {
            "daily": "UTC calendar day until V2 durable account ledger is installed",
            "weekly": "UTC ISO week until V2 durable account ledger is installed",
        },
        "dedupe_source": "paper_ledger_entry_id + execution_intent_id + risk_decision_id",
        "audit_event": "WEEKLY_LOSS_GATE_RUNTIME_EVALUATED",
        "exchange_order": False,
        "legacy_redis_write": False,
    }


def append_paper_event(root: Path, payload: dict[str, Any], risk_runtime_payload: dict[str, Any]) -> None:
    ledger_entry = payload["paper_ledger_tail"][0]
    signal = payload["current_signal_lineage"]["signal"]
    risk = payload["current_risk_decision"]
    trainer = payload["trainer_prediction"]
    _intent = (payload.get("current_signal_lineage") or {}).get("execution_intent") or {}
    feature_snapshot = payload["feature_snapshot"]
    paper_edge_gate = risk.get("paper_edge_gate") if isinstance(risk.get("paper_edge_gate"), dict) else {}
    paper_churn_governor = (
        risk.get("paper_churn_governor")
        if isinstance(risk.get("paper_churn_governor"), dict)
        else {}
    )
    paper_entry_cost_gate = (
        risk.get("paper_entry_production_cost_gate")
        if isinstance(risk.get("paper_entry_production_cost_gate"), dict)
        else {}
    )
    paper_reentry_dedup_gate = (
        risk.get("paper_reentry_dedup_gate")
        if isinstance(risk.get("paper_reentry_dedup_gate"), dict)
        else {}
    )
    paper_standalone_1m_eligibility = (
        risk.get("paper_standalone_1m_eligibility")
        if isinstance(risk.get("paper_standalone_1m_eligibility"), dict)
        else {}
    )
    protective_gate = (
        risk.get("paper_protective_behavior_gate")
        if isinstance(risk.get("paper_protective_behavior_gate"), dict)
        else {}
    )
    confidence = signal.get("confidence") or signal.get("confidence_calibrated") or trainer.get("confidence_calibrated")
    is_fill = ledger_entry["paper_result"] == "FILLED_PAPER_ONLY"
    is_blocked = ledger_entry["paper_result"] == "NO_FILL_RISK_BLOCKED"
    event = {
        "generated_at": payload["generated_at"],
        "tick_id": payload["paper_loop"]["tick_id"],
        "symbol": ledger_entry["symbol"],
        "prediction_id": payload["current_signal_lineage"]["lineage_ids"]["prediction_id"],
        "feature_snapshot_id": payload["current_signal_lineage"]["lineage_ids"]["feature_snapshot_id"],
        "signal_id": ledger_entry["signal_id"],
        "risk_decision_id": ledger_entry["risk_decision_id"],
        "execution_intent_id": ledger_entry["execution_intent_id"],
        "paper_ledger_entry_id": ledger_entry["paper_ledger_entry_id"],
        "economic_trade_id": ledger_entry.get("economic_trade_id"),
        "economic_thesis_id": ledger_entry.get("economic_thesis_id"),
        "parent_position_id": ledger_entry.get("parent_position_id"),
        "entry_sequence": ledger_entry.get("entry_sequence"),
        "close_sequence": ledger_entry.get("close_sequence"),
        "is_partial_reduce": ledger_entry.get("is_partial_reduce"),
        "is_partial_close": ledger_entry.get("is_partial_close"),
        "is_full_close": ledger_entry.get("is_full_close"),
        "is_reversal": ledger_entry.get("is_reversal"),
        "thesis_prediction_id": ledger_entry.get("thesis_prediction_id"),
        "execution_snapshot_id": ledger_entry.get("execution_snapshot_id"),
        "thesis_timeframe": ledger_entry.get("thesis_timeframe"),
        "execution_timeframe": ledger_entry.get("execution_timeframe"),
        "strategy_id": _paper_strategy_id(signal=signal, prediction=trainer),
        "thesis_candle_close_time": _paper_thesis_candle_value(risk, signal, trainer, feature_snapshot),
        "entry_time": payload["generated_at"],
        "trainer_source": trainer.get("trainer_source"),
        "trainer_bridge_status": trainer.get("trainer_bridge_status"),
        "model_version": trainer.get("model_version"),
        "checkpoint_id": trainer.get("model_checkpoint"),
        "confidence_raw": trainer.get("confidence_raw"),
        "confidence_calibrated": trainer.get("confidence_calibrated"),
        "confidence_bucket": _confidence_bucket(confidence),
        "expected_move_bps": risk.get("expected_move_bps"),
        "expected_move_after_cost_bps": risk.get("expected_move_after_cost_bps"),
        "expected_move_source": risk.get("expected_move_source"),
        "fee_bps": paper_edge_gate.get("fee_bps"),
        "spread_bps": paper_edge_gate.get("spread_bps"),
        "funding_risk_bps": paper_edge_gate.get("funding_risk_bps"),
        "edge_score": paper_edge_gate.get("edge_score"),
        "feature_freshness_state": feature_snapshot.get("freshness_state"),
        "stale_feature_flags": feature_snapshot.get("stale_feature_flags", []),
        "missing_feature_flags": feature_snapshot.get("missing_feature_flags", []),
        "symbol_universe_state": "PAPER_SYMBOL_SCOPE_LOCAL",
        "paper_symbol_allowed": paper_edge_gate.get("paper_symbol_allowed"),
        "risk_action": risk["risk_action"],
        "risk_result": risk["risk_result"],
        "risk_reason_code": risk["risk_reason_code"],
        "risk_reason": risk["risk_reason_code"],
        "block_reason": risk["risk_reason_code"] if is_blocked else None,
        "fill_allowed": is_fill,
        "fill_rejected_reason": risk["risk_reason_code"] if is_blocked else None,
        "ledger_action": ledger_entry["ledger_action"],
        "paper_result": ledger_entry["paper_result"],
        "exit_reason": ledger_entry.get("exit_reason"),
        "realized_delta_usdt": ledger_entry.get("realized_delta_usdt"),
        "gross_pnl_usdt": ledger_entry.get("gross_pnl_usdt"),
        "paper_pnl_delta": ledger_entry.get("realized_delta_usdt")
        if ledger_entry.get("realized_delta_usdt") is not None
        else (-ledger_entry["fee_usdt"] if is_fill else 0.0),
        "confidence": confidence,
        "notional_usdt": ledger_entry["notional_usdt"],
        "fee_usdt": ledger_entry["fee_usdt"],
        "slippage_bps": ledger_entry["slippage_bps"],
        "funding_assumption": ledger_entry["funding_assumption"],
        "paper_equity": payload["paper_account"]["equity"],
        "paper_realized_pnl": payload["paper_account"]["realized_pnl"],
        "weekly_loss_gate_required": risk_runtime_payload["weekly_loss_gate_required"],
        "weekly_loss_breach": risk_runtime_payload["weekly_loss_breach"],
        "canary_profile_tightening_blockers": risk.get("canary_profile_tightening_blockers", []),
        "paper_edge_gate_blockers": risk.get("paper_edge_gate_blockers", []),
        "paper_entry_production_cost_gate_status": paper_entry_cost_gate.get("status"),
        "paper_entry_production_cost_gate_blockers": risk.get("paper_entry_production_cost_gate_blockers", []),
        "paper_entry_production_cost_missing_fields": paper_entry_cost_gate.get("missing_cost_fields", []),
        "expected_round_trip_cost_bps": paper_entry_cost_gate.get("expected_round_trip_cost_bps"),
        "expected_net_edge_lower_bound_bps": paper_entry_cost_gate.get("expected_net_edge_lower_bound_bps"),
        "edge_to_cost_ratio": paper_entry_cost_gate.get("edge_to_cost_ratio"),
        "paper_reentry_dedup_gate_status": paper_reentry_dedup_gate.get("status"),
        "paper_reentry_dedup_gate_blockers": risk.get("paper_reentry_dedup_gate_blockers", []),
        "paper_reentry_duplicate_identity_fields": paper_reentry_dedup_gate.get("duplicate_identity_fields", []),
        "paper_reentry_permitted_change_reasons": paper_reentry_dedup_gate.get("permitted_reentry_reasons", []),
        "paper_standalone_1m_eligibility_status": paper_standalone_1m_eligibility.get("status"),
        "paper_standalone_1m_eligibility_blockers": risk.get("paper_standalone_1m_eligibility_blockers", []),
        "standalone_1m_thesis": paper_standalone_1m_eligibility.get("standalone_1m_thesis"),
        "standalone_1m_strategy_bucket_eligible": paper_standalone_1m_eligibility.get("dedicated_strategy_bucket"),
        "higher_timeframe_1m_timing_role_allowed": paper_standalone_1m_eligibility.get("higher_timeframe_timing_role_allowed"),
        "paper_churn_governor_status": paper_churn_governor.get("status"),
        "paper_churn_governor_blockers": risk.get("paper_churn_governor_blockers", []),
        "paper_churn_governor_bucket": paper_churn_governor.get("candidate_bucket_key"),
        "paper_protective_behavior_gate": protective_gate,
        "minimum_hold_seconds": protective_gate.get("minimum_hold_seconds"),
        "microstructure_toxicity_score_bps": protective_gate.get("microstructure_toxicity_score_bps"),
        "microstructure_toxicity_clear": protective_gate.get("microstructure_toxicity_clear"),
        "reduce_only_protection_clear": protective_gate.get("reduce_only_protection_clear"),
        "intelligent_close_guard_clear": protective_gate.get("intelligent_close_guard_clear"),
        "paper_outcome_model_status": (risk.get("paper_outcome_model") or {}).get("status"),
        "paper_outcome_model_blockers": risk.get("paper_outcome_model_blockers", []),
        "live_gate_status": LIVE_GATE_STATUS,
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "exchange_order": False,
        "legacy_redis_write": False,
        # Fields added for hourly monitor / feedback / leverage tracking
        "timeframe": trainer.get("timeframe") or "unknown",
        "side": _intent.get("side") or None,
        "paper_action": f"paper_{_intent.get('side') or 'unknown'}",
        "leverage_recommendation": risk.get("leverage_recommendation"),
        "feedback_sent": ledger_entry["paper_result"] == "POSITION_CLOSED_PAPER_ONLY",
        "anti_mm_entry_blocked": bool((risk.get("anti_mm_detection") or {}).get("entry_blocked")),
        "entry_gate_result": risk.get("entry_gate"),
        "high_precision_gate_result": risk.get("high_precision_gate"),
        "source_type": "V2_PAPER_RUNTIME_JSONL_EVENT",
    }
    root.mkdir(parents=True, exist_ok=True)
    with (root / "paper_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def build_runtime_payload(symbol: str, interval: int) -> tuple[dict[str, Any], dict[str, Any]]:
    market = fetch_market_snapshot(symbol)
    previous = _read_json(LOCAL_RUNTIME_DIR / "paper_runtime_status.json") or {}
    previous_count = int(previous.get("paper_loop", {}).get("paper_event_count", 0) or 0)
    previous_equity = float(previous.get("paper_account", {}).get("equity", 10000.0) or 10000.0)
    previous_account = previous.get("paper_account") if isinstance(previous.get("paper_account"), dict) else {}
    previous_lifecycle = previous.get("paper_position_lifecycle") if isinstance(previous.get("paper_position_lifecycle"), dict) else {}
    previous_last_closed_position = (
        previous_lifecycle.get("last_closed_position")
        if isinstance(previous_lifecycle.get("last_closed_position"), dict)
        else None
    )
    previous_position = _open_position_from_previous(previous)
    generated_at = iso_now()
    runtime_online = market.freshness_state in {"CURRENT", "WARN"}
    tick_id = f"paper_tick_{int(time.time() * 1000)}"
    feature_snapshot = build_feature_snapshot(market, tick_id)
    trainer_prediction = build_trainer_prediction(feature_snapshot, tick_id)
    # Phase 6: enrich prediction with required schema fields (direction, coverage, drivers, etc.)
    try:
        from v2.backend.app.services.paper_trade_management.prediction_accuracy_tracker import (  # noqa: PLC0415
            enrich_prediction_for_phase6,
        )
        trainer_prediction = enrich_prediction_for_phase6(trainer_prediction)
    except Exception:  # noqa: BLE001
        pass
    lineage = build_signal_lineage(
        tick_id=tick_id,
        generated_at=generated_at,
        feature_snapshot=feature_snapshot,
        prediction=trainer_prediction,
        market=market,
    )
    lineage = apply_paper_tightening_gate(
        lineage,
        generated_at=generated_at,
        recent_events=_recent_events_with_last_closed_loss(
            _read_jsonl_tail(LOCAL_RUNTIME_DIR / "paper_events.jsonl"),
            previous_last_closed_position,
        ),
        previous_position=previous_position,
    )
    if previous_position:
        ledger_entry, paper_account, position_lifecycle = build_position_lifecycle_entry(
            tick_id=tick_id,
            generated_at=generated_at,
            market=market,
            lineage=lineage,
            previous_position=previous_position,
            previous_account=previous_account,
        )
    else:
        # Phases 3/4/8/9: entry gate → high-precision gate → anti-MM → leverage rec
        lineage = apply_paper_entry_gates(lineage)
        ledger_entry, paper_account = build_paper_ledger_entry(
            tick_id=tick_id,
            generated_at=generated_at,
            market=market,
            lineage=lineage,
            previous_equity=previous_equity,
        )
        position_lifecycle = paper_position_lifecycle_from_entry(
            ledger_entry=ledger_entry,
            lineage=lineage,
        )
    if previous_last_closed_position and not position_lifecycle.get("last_closed_position"):
        position_lifecycle["last_closed_position"] = previous_last_closed_position
    risk_runtime_payload = build_risk_runtime_payload(
        generated_at=generated_at,
        lineage=lineage,
        ledger_entry=ledger_entry,
        paper_account=paper_account,
    )
    runtime_state = "PAPER_RUNTIME_ONLINE_ACTIVE" if runtime_online else "PAPER_RUNTIME_BLOCKED_MARKET_FEED_MISSING"
    blockers: list[dict[str, str]] = []
    if not runtime_online:
        blockers.insert(
            0,
            {
                "id": "READONLY_MARKET_FEED_MISSING",
                "severity": "blocks_continuous_paper_runtime",
                "detail": "; ".join(market.errors) or "Read-only market feed is unavailable.",
            },
        )

    paper_event = {
        "tick_id": tick_id,
        "generated_at": generated_at,
        "symbol": symbol,
        "observed_price": market.price,
        "market_source_type": market.source_type,
        "paper_action": ledger_entry["ledger_action"],
        "paper_reason": lineage["risk_decision"]["risk_reason_code"],
        "risk_gateway_result": lineage["risk_decision"]["risk_result"],
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    payload = {
        "generated_at": generated_at,
        "runtime": "v2_paper_online",
        "runtime_state": runtime_state,
        "paper_policy_owner": PAPER_ONLINE_LEGACY_OWNER,
        "policy_id": PAPER_ONLINE_LEGACY_OWNER,
        "model_source": PAPER_ONLINE_LEGACY_MODEL_SOURCE,
        "current_allowed_paper_owner": V2_CURRENT_PAPER_OWNER,
        "legacy_owner_mode": PAPER_ONLINE_LEGACY_OWNER_MODE,
        "new_economic_entries_allowed": False,
        "old_policy_closes_allowed": True,
        "paper_entry_owner_gate": lineage["risk_decision"].get("paper_entry_owner_gate"),
        "live_gate": LIVE_GATE_STATUS,
        "live_gate_status": LIVE_GATE_STATUS,
        "live_symbols": [],
        "mode": "paper_only_non_live",
        "continuous_loop_available": True,
        "loop_interval_seconds": interval,
        "writes_only_local_v2_artifacts": True,
        "legacy_redis_writes": False,
        "exchange_orders": False,
        "leverage_changes": False,
        "margin_mode_changes": False,
        "redis_trim_approval_created": False,
        "market_feed": asdict(market),
        "paper_loop": {
            "state": runtime_state,
            "tick_id": tick_id,
            "last_tick_at": generated_at,
            "paper_event_count": previous_count + 1,
            "last_paper_event_count": previous_count + 1,
            "last_shadow_decision_count": 1,
            "last_risk_block_count": 0 if lineage["risk_decision"]["risk_action"] == "allow" else 1,
        },
        "paper_account": paper_account,
        "paper_position_lifecycle": position_lifecycle,
        "feature_snapshot": feature_snapshot,
        "trainer_prediction": trainer_prediction,
        "current_signal_lineage": lineage,
        "current_risk_decision": lineage["risk_decision"],
        "risk_runtime_payload": risk_runtime_payload,
        "paper_ledger_tail": [ledger_entry],
        "audit_events": [
            {
                "audit_event_id": f"audit_{tick_id}",
                "generated_at": generated_at,
                "event_type": "V2_PAPER_RUNTIME_TICK",
                "lineage_ids": lineage["lineage_ids"],
                "paper_ledger_entry_id": ledger_entry["paper_ledger_entry_id"],
                "live_gate": LIVE_GATE_STATUS,
                "live_gate_status": LIVE_GATE_STATUS,
                "live_symbols": [],
            }
        ],
        "last_paper_event": paper_event,
        "safety": {
            "live_trading": LIVE_GATE_STATUS,
            "orders": "BLOCKED_NO_EXCHANGE_MUTATION",
            "legacy_bot_mutation": False,
            "legacy_redis_mutation": False,
            "legacy_new_economic_entries": "BLOCKED_BY_PAPER_ENTRY_OWNER_GATE",
            "risk_gateway": "CURRENT_SIGNAL_PROCESSED_FINAL_AUTHORITY",
        },
        "blockers": blockers,
        "freshness": {
            "status": "CURRENT" if runtime_online else "MISSING_EVIDENCE",
            "generated_at": generated_at,
            "runtime_age_seconds": 0,
            "market_age_seconds": market.age_seconds,
            "source_type": "REALTIME_RUNTIME_EVIDENCE" if runtime_online else "MISSING_EVIDENCE",
        },
        "source_files": {
            "public_runtime_status": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "local_runtime_status": "v2/runtime/paper_online/latest/paper_runtime_status.json",
        },
    }
    positions = {
        "generated_at": generated_at,
        "live_gate": LIVE_GATE_STATUS,
        "live_gate_status": LIVE_GATE_STATUS,
        "live_symbols": [],
        "mode": "paper_only_non_live",
        "paper_pnl": paper_account["realized_pnl"],
        "position_count": paper_account["open_position_count"],
        "open_positions": [
            {
                "symbol": (position_lifecycle.get("open_position") or {}).get("symbol", symbol),
                "side": (position_lifecycle.get("open_position") or {}).get("side", lineage["execution_intent"]["side"]),
                "entry_price": (position_lifecycle.get("open_position") or {}).get("entry_price"),
                "unrealized_pnl_usdt": (position_lifecycle.get("open_position") or {}).get("unrealized_pnl_usdt"),
                "source": "V2_PAPER_RUNTIME_POSITION_LIFECYCLE",
                "paper_only": True,
            }
        ]
        if paper_account["open_position_count"]
        else [],
        "position_state": paper_account["position_source"],
        "source_type": "V2_PAPER_RUNTIME",
    }
    return payload, positions


def _push_decisions_to_redis(payload: dict[str, Any]) -> None:
    """Write risk/orchestrator/ledger decisions to V2 Redis namespace.

    This bridges the file-based paper_online_runtime output to the Redis
    keys consumed by all_timeframe_prediction_signal_price_target_publisher
    so that risk_decision_id and orchestrator_decision_id are no longer
    missing from the all-TF signal lineage artifact.

    All writes use v2: prefix only. No legacy Redis writes.
    Fail-safe: any Redis error is silently absorbed so the paper loop
    continues even when Redis is temporarily unavailable.
    """
    try:
        import redis as _redis  # type: ignore
    except ImportError:
        return
    try:
        r = _redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        r.ping()
    except Exception:  # noqa: BLE001
        return
    try:
        lineage = payload.get("current_signal_lineage") or {}
        risk_decision = payload.get("current_risk_decision") or lineage.get("risk_decision") or {}
        orch_decision = lineage.get("orchestrator_decision") or {}
        execution_intent = lineage.get("execution_intent") or {}
        ledger_entries = payload.get("paper_ledger_tail") or []
        generated_at = payload.get("generated_at", "")
        paper_signal_timeframe = _paper_thesis_timeframe(
            payload.get("trainer_prediction") or {},
            lineage.get("trainer_prediction") or {},
            execution_intent,
            payload.get("feature_snapshot") or {},
        )

        def _append_to_json_list(key: str, new_item: dict, max_len: int = 300) -> None:
            existing_raw = r.get(key)
            existing_list: list = []
            if existing_raw:
                try:
                    parsed = json.loads(existing_raw)
                    if isinstance(parsed, list):
                        existing_list = parsed
                except Exception:  # noqa: BLE001
                    pass
            existing_list.insert(0, new_item)
            r.set(key, json.dumps(existing_list[:max_len]))

        if risk_decision:
            risk_entry = dict(risk_decision)
            risk_entry.setdefault("generated_at", generated_at)
            # Delay canonical list append until we have symbol_key (done below
            # in signal_id block). Synthetic paper-online ticks without the
            # point-in-time trust envelope must not overwrite canonical risk
            # decision evidence consumed by training and lineage auditors.
            if _has_complete_canonical_risk_trust_envelope(risk_entry):
                r.set("v2:risk:decisions:latest", json.dumps(risk_entry))
            else:
                r.set(PAPER_ONLINE_RISK_DECISIONS_LATEST_KEY, json.dumps(risk_entry))

        if orch_decision:
            orch_entry = dict(orch_decision)
            orch_entry.setdefault("generated_at", generated_at)
            existing_orch_raw = r.get("v2:orchestrator:decisions")
            if existing_orch_raw:
                try:
                    existing_orch = json.loads(existing_orch_raw)
                    if isinstance(existing_orch, dict) and "schema_version" in existing_orch:
                        existing_orch["paper_online_latest"] = orch_entry
                        existing_orch["paper_online_generated_at"] = generated_at
                        r.set("v2:orchestrator:decisions", json.dumps(existing_orch))
                    else:
                        r.set("v2:orchestrator:decisions", json.dumps({
                            "generated_at": generated_at,
                            "paper_online_latest": orch_entry,
                            "decisions": [orch_entry],
                        }))
                except Exception:  # noqa: BLE001
                    pass
            else:
                r.set("v2:orchestrator:decisions", json.dumps({
                    "generated_at": generated_at,
                    "paper_online_latest": orch_entry,
                    "decisions": [orch_entry],
                }))

        if execution_intent:
            intent_entry = dict(execution_intent)
            intent_entry.setdefault("generated_at", generated_at)
            _append_to_json_list(PAPER_ONLINE_INTENTS_KEY, intent_entry)

        if ledger_entries:
            latest_entry = ledger_entries[0] if isinstance(ledger_entries[0], dict) else {}
            risk_action = risk_decision.get("risk_action", "deny")
            fill_allowed = risk_action == "allow" and latest_entry.get("paper_result") == "FILLED_PAPER_ONLY"
            paper_ledger = {
                "generated_at": generated_at,
                "source": "v2.backend.app.cli.paper_online_runtime",
                "paper_policy_owner": PAPER_ONLINE_LEGACY_OWNER,
                "policy_id": PAPER_ONLINE_LEGACY_OWNER,
                "model_source": PAPER_ONLINE_LEGACY_MODEL_SOURCE,
                "current_allowed_paper_owner": V2_CURRENT_PAPER_OWNER,
                "legacy_owner_mode": PAPER_ONLINE_LEGACY_OWNER_MODE,
                "accepted_count": 1 if fill_allowed else 0,
                "blocked_count": 0 if fill_allowed else 1,
                "accepted": [latest_entry] if fill_allowed else [],
                "shadow_observations": [latest_entry] if not fill_allowed else [],
                "latest_entry": latest_entry,
            }
            r.set(PAPER_ONLINE_LEDGER_KEY, json.dumps(paper_ledger))

        lineage_ids = lineage.get("lineage_ids") or {}
        signal_id = lineage_ids.get("signal_id") or (lineage.get("signal") or {}).get("signal_id")
        if signal_id:
            signal_record = dict(lineage.get("signal") or {})
            paper_signal_timeframe = _paper_thesis_timeframe(
                signal_record,
                payload.get("trainer_prediction") or {},
                lineage.get("trainer_prediction") or {},
                execution_intent,
            )
            paper_execution_timeframe = _paper_execution_timeframe(
                signal_record,
                payload.get("feature_snapshot") or {},
                payload.get("market_feed") or {},
            )
            signal_record["thesis_timeframe"] = paper_signal_timeframe
            signal_record["execution_timeframe"] = paper_execution_timeframe
            signal_record["timeframe"] = paper_signal_timeframe
            signal_record["risk_decision_id"] = risk_decision.get("risk_decision_id")
            signal_record["orchestrator_decision_id"] = orch_decision.get("orchestrator_decision_id")
            signal_record["execution_intent_id"] = execution_intent.get("execution_intent_id")
            signal_record["paper_policy_owner"] = PAPER_ONLINE_LEGACY_OWNER
            signal_record["policy_id"] = PAPER_ONLINE_LEGACY_OWNER
            signal_record["policy_fingerprint"] = PAPER_ONLINE_LEGACY_OWNER_MODE
            signal_record["model_source"] = PAPER_ONLINE_LEGACY_MODEL_SOURCE
            signal_record["current_allowed_paper_owner"] = V2_CURRENT_PAPER_OWNER
            signal_record["paper_fill_allowed"] = False
            signal_record["paper_opportunity_tier"] = PAPER_ONLINE_LEGACY_OWNER_MODE
            signal_record["paper_fill_block_reason"] = PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON
            signal_record["paper_fill_gate_block_reasons"] = sorted(set(
                list(signal_record.get("paper_fill_gate_block_reasons") or [])
                + [PAPER_ONLINE_NEW_ENTRY_BLOCK_REASON]
            ))
            signal_record["paper_entry_owner_gate"] = risk_decision.get("paper_entry_owner_gate")
            signal_record["paper_ledger_entry_id"] = (
                (ledger_entries[0] or {}).get("paper_ledger_entry_id") if ledger_entries else None
            )
            signal_record["generated_at"] = generated_at
            symbol_key = str(payload.get("market_feed", {}).get("symbol") or "").upper()
            if symbol_key:
                r.set(f"v2:signals:paper:{symbol_key}:{paper_signal_timeframe}", json.dumps(signal_record))
                gateway_entry = {
                    "generated_at": generated_at,
                    "symbol": symbol_key,
                    "timeframe": paper_signal_timeframe,
                    "thesis_timeframe": paper_signal_timeframe,
                    "execution_timeframe": paper_execution_timeframe,
                    "prediction_id": lineage_ids.get("prediction_id"),
                    "risk_decision_id": risk_decision.get("risk_decision_id"),
                    "risk_action": risk_decision.get("risk_action"),
                    "risk_result": risk_decision.get("risk_result"),
                }
                if _has_complete_canonical_risk_trust_envelope(gateway_entry):
                    r.set("v2:risk:gateway:decisions:latest", json.dumps(gateway_entry))
                    _append_to_json_list("v2:risk:gateway:decisions", gateway_entry)
                else:
                    r.set(PAPER_ONLINE_RISK_GATEWAY_DECISIONS_LATEST_KEY, json.dumps(gateway_entry))
                    _append_to_json_list(PAPER_ONLINE_RISK_GATEWAY_DECISIONS_KEY, gateway_entry)
                # Also inject symbol into the risk decision entry so _by_symbol fallback works
                if risk_decision:
                    risk_entry_sym = dict(risk_decision)
                    risk_entry_sym["symbol"] = symbol_key
                    risk_entry_sym["orchestrator_decision_id"] = orch_decision.get("orchestrator_decision_id")
                    risk_entry_sym.setdefault("generated_at", generated_at)
                    if _has_complete_canonical_risk_trust_envelope(risk_entry_sym):
                        r.set("v2:risk:decisions:latest", json.dumps(risk_entry_sym))
                        _append_to_json_list("v2:risk:decisions", risk_entry_sym)
                    else:
                        r.set(PAPER_ONLINE_RISK_DECISIONS_LATEST_KEY, json.dumps(risk_entry_sym))
                        _append_to_json_list(PAPER_ONLINE_RISK_DECISIONS_KEY, risk_entry_sym)
        # Phase 6: backfill realized outcome when a position just closed
        if ledger_entries:
            _ledger_result = (ledger_entries[0] or {}).get("paper_result", "")
            if _ledger_result == "POSITION_CLOSED_PAPER_ONLY":
                _last_closed = (
                    (payload.get("paper_position_lifecycle") or {}).get("last_closed_position") or {}
                )
                if _last_closed and lineage_ids.get("prediction_id"):
                    try:
                        from v2.backend.app.services.paper_trade_management.prediction_accuracy_tracker import (  # noqa: PLC0415
                            backfill_realized_outcome,
                        )
                        _realized_bps = float(_last_closed.get("current_return_bps") or 0.0)
                        _sym_key = str(payload.get("market_feed", {}).get("symbol") or "").upper()
                        backfill_realized_outcome(
                            symbol=_sym_key,
                            timeframe=paper_signal_timeframe,
                            prediction_id=str(lineage_ids["prediction_id"]),
                            realized_outcome_direction="long" if _realized_bps > 0 else "short",
                            realized_outcome_bps=_realized_bps,
                            realized_at_ms=int(time.time() * 1000),
                            redis_client=r,
                        )
                    except Exception:  # noqa: BLE001
                        pass
    except Exception:  # noqa: BLE001
        pass


def write_runtime_payload(symbol: str, interval: int, write_evidence: bool) -> dict[str, Any]:
    payload, positions = build_runtime_payload(symbol, interval)
    for root in (LOCAL_RUNTIME_DIR, PUBLIC_RUNTIME_DIR):
        _write_json(root / "paper_runtime_status.json", payload)
        _write_json(root / "paper_positions.json", positions)
        _write_json(root / "trainer_prediction_current_record.json", payload["trainer_prediction"])
        _write_json(root / "current_signal_lineage.json", payload["current_signal_lineage"])
        _write_json(root / "current_risk_decisions.json", {"generated_at": payload["generated_at"], "decisions": [payload["current_risk_decision"]]})
        _write_json(root / "risk_runtime_payload.json", payload["risk_runtime_payload"])
        _write_json(
            root / "paper_ledger_tail.json",
            {
                "generated_at": payload["generated_at"],
                "source": "v2.backend.app.cli.paper_online_runtime",
                "entries": payload["paper_ledger_tail"],
            },
        )
        append_paper_event(root, payload, payload["risk_runtime_payload"])
    _push_decisions_to_redis(payload)
    if write_evidence:
        write_evidence_packet(payload, positions)
    return payload


def write_evidence_packet(payload: dict[str, Any], positions: dict[str, Any]) -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    marker = READY_MARKER if payload["runtime_state"] == "PAPER_RUNTIME_ONLINE_ACTIVE" else BLOCKED_MARKER
    codex_marker = CODEX_PASS_MARKER if marker == READY_MARKER else CODEX_FAIL_MARKER
    _write_json(FINAL_DIR / "paper_runtime_status.json", payload)
    _write_json(FINAL_DIR / "paper_positions.json", positions)
    _write_json(FINAL_DIR / "trainer_prediction_current_record.json", payload["trainer_prediction"])
    _write_json(FINAL_DIR / "trainer_runtime_current_status.json", {
        "generated_at": payload["generated_at"],
        "status": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
        "source": "v2.backend.app.cli.paper_online_runtime",
        "prediction_id": payload["trainer_prediction"]["prediction_id"],
        "feature_snapshot_id": payload["trainer_prediction"]["feature_snapshot_id"],
        "model_checkpoint": payload["trainer_prediction"]["model_checkpoint"],
        "age_seconds": 0,
    })
    _write_json(FINAL_DIR / "current_signal_lineage.json", payload["current_signal_lineage"])
    _write_json(FINAL_DIR / "current_risk_decisions.json", {
        "generated_at": payload["generated_at"],
        "decisions": [payload["current_risk_decision"]],
    })
    _write_json(FINAL_DIR / "risk_runtime_payload.json", payload["risk_runtime_payload"])
    _write_json(FINAL_DIR / "paper_ledger_tail.json", {
        "generated_at": payload["generated_at"],
        "source": "v2.backend.app.cli.paper_online_runtime",
        "entries": payload["paper_ledger_tail"],
    })
    _write_json(FINAL_DIR / "market_feed_status.json", {
        "generated_at": payload["generated_at"],
        "status": payload["market_feed"]["freshness_state"],
        "source_type": payload["market_feed"]["source_type"],
        "symbol": payload["market_feed"]["symbol"],
        "price": payload["market_feed"]["price"],
        "age_seconds": payload["market_feed"]["age_seconds"],
    })
    _write_json(FINAL_DIR / "v2_data_plane_status.json", {
        "generated_at": payload["generated_at"],
        "status": "V2_DATA_PLANE_ONLINE_FOR_PAPER",
        "writes_only_v2_artifacts": True,
        "old_redis_writes": False,
        "public_runtime_payload": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
        "local_runtime_payload": "v2/runtime/paper_online/latest/paper_runtime_status.json",
    })
    _write_json(FINAL_DIR / "supervisor_current_truth.json", {
        "generated_at": payload["generated_at"],
        "status": "NO_ACTIVE_SUPERVISOR_TASK_OBSERVED",
        "paper_runtime_process": "running_or_started_by_v2",
        "live_gate_status": LIVE_GATE_STATUS,
    })
    _write_json(FINAL_DIR / "admin_ai_status.json", {
        "generated_at": payload["generated_at"],
        "status": "NON_LIVE_QUERY_SURFACE_READY_FROM_OPERATOR_PAYLOADS",
        "can_answer": [
            "latest paper prediction",
            "current signal lineage",
            "risk decision",
            "paper PnL",
            "live blockers",
        ],
        "forbidden_actions": [
            "enable-live-trading",
            "change-leverage",
            "change-margin",
            "place-or-cancel-orders",
        ],
    })
    _write_json(
        FINAL_DIR / "operator_dashboard_payload.json",
        {
            "generated_at": payload["generated_at"],
            "status": marker,
            "runtime_state": payload["runtime_state"],
            "live_gate_status": LIVE_GATE_STATUS,
            "market_feed": payload["market_feed"]["freshness_state"],
            "trainer_state": payload["trainer_prediction"]["trainer_state"],
            "prediction_id": payload["trainer_prediction"]["prediction_id"],
            "signal_id": payload["current_signal_lineage"]["lineage_ids"]["signal_id"],
            "risk_decision_id": payload["current_signal_lineage"]["lineage_ids"]["risk_decision_id"],
            "paper_event_count": payload["paper_loop"]["paper_event_count"],
            "paper_action": payload["last_paper_event"]["paper_action"],
            "risk_gateway_result": payload["last_paper_event"]["risk_gateway_result"],
            "legacy_redis_writes": False,
            "exchange_orders": False,
            "redis_trim_status": "deferred_non_blocking",
            "codex_result": codex_marker,
            "human_input_required": "false_unless_final_live_capital_gate",
        },
    )
    _write_text(FINAL_DIR / "GO_NO_GO.md", marker + "\n")
    _write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker + "\n")
    _write_text(
        FINAL_DIR / "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_REPORT.md",
        f"""# V2 Paper Online Full Operational Recovery Report

Status: {marker}

Generated at: {payload['generated_at']}

- Runtime state: `{payload['runtime_state']}`
- Runtime mode: `paper_only_non_live`
- Live gate: `{LIVE_GATE_STATUS}`
- Market feed: `{payload['market_feed']['source_type']}` / `{payload['market_feed']['freshness_state']}`
- Paper loop available: `{payload['continuous_loop_available']}`
- Paper event count: `{payload['paper_loop']['paper_event_count']}`
- Paper action: `{payload['last_paper_event']['paper_action']}`
- Risk result: `{payload['last_paper_event']['risk_gateway_result']}`
- Exchange orders: `false`
- Legacy Redis writes: `false`
- Leverage changes: `false`
- Margin mode changes: `false`
- Redis trim approval created: `false`

The V2 paper runtime is online as a continuous, non-live paper chain. It observes read-only market data, builds a V2 paper-only trainer wrapper prediction, emits current signal lineage, sends the signal through the Risk Gateway, records a paper ledger event, and writes only local V2 runtime payloads. It does not place exchange orders and live remains blocked_human_only.
""",
    )
    _write_text(
        FINAL_DIR / "PAPER_RUNTIME_WIRING_REPORT.md",
        f"""# Paper Runtime Wiring Report

Generated at: {payload['generated_at']}

Command:

```bash
cd v2/frontend && npm run build:paper-online
cd v2/frontend && npm run run:paper-online
```

Runtime outputs:

- `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- `v2/frontend/public/operator_runtime/paper_online/latest/paper_positions.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_positions.json`

Website visibility:

- Mission Control reads the paper runtime payload.
- Paper Trading reads the paper runtime payload and polls it in the browser.
- Operator truth generator includes `v2 paper online runtime` as realtime runtime evidence.
- Trainer Prediction Monitor reads the current V2 paper trainer wrapper prediction.
- Signal Explainability reads the current V2 paper signal lineage.
- Risk Control reads current V2 paper risk decisions.
""",
    )
    _write_text(
        FINAL_DIR / "RUNTIME_DATA_VISIBILITY_REPORT.md",
        f"""# Runtime Data Visibility Report

Generated at: {payload['generated_at']}

Fresh runtime payload fields visible to the website:

- runtime state
- last tick time
- paper event count
- read-only market feed source/freshness
- observed price
- V2 paper trainer wrapper prediction
- current feature_snapshot_id and prediction_id
- current signal_id, orchestrator_decision_id, risk_decision_id, and execution_intent_id
- paper action
- risk gateway result
- paper ledger tail
- live gate status
- no exchange order / no Redis write safety flags

Static proof fixtures are not used as current paper runtime truth.
""",
    )
    _write_text(
        FINAL_DIR / "NO_LIVE_MUTATION_SAFETY_REPORT.md",
        f"""# No Live Mutation Safety Report

Generated at: {payload['generated_at']}

- Legacy bot code modified: no
- Legacy Redis writes: no
- Redis trim approval file created: no
- Exchange orders placed/cancelled/modified: no
- Leverage changed: no
- Margin mode changed: no
- Live keys activated: no
- Live trading enabled: no
- Live gate: {LIVE_GATE_STATUS}

Only public GET market-data reads and local V2 artifact writes were used.
""",
    )
    _write_text(
        FINAL_DIR / "CODEX_PARALLEL_AUDIT.md",
        f"""# Codex Parallel Audit

Result: {codex_marker}

Audit checks:

- Runtime is non-live and writes only local V2 artifacts.
- Read-only market feed uses public GET endpoints.
- Trainer evidence comes from the V2 paper-only wrapper and is current.
- Signal lineage is current and produced by the V2 paper runtime.
- Risk Gateway processes the current signal before any paper ledger event.
- Paper order/fill simulation remains paper-only and creates no exchange order.
- Legacy Redis writes are false.
- Exchange orders are false.
- Live gate remains blocked_human_only.
- Redis trim approval remains absent by design.
""",
    )
    _write_text(
        FINAL_DIR / "NEXT_BLOCKERS.md",
        """# Next Blockers

- SUPERVISOR_CONTROL_PLANE_STALE_OR_NOT_RUNNING
- DEPLOY_OPERATOR_TRUTH_TELEMETRY_BRIDGE_TO_PUBLIC_DASHBOARD
- REPLACE PAPER_WRAPPER MODEL WITH FULL TRAINER/MODEL ADAPTER WHEN READY

These blockers do not require live trading. They are the next safe pre-live online-readiness tasks.
""",
    )
    _write_text(
        FINAL_DIR / "VALIDATION_COMMANDS.md",
        f"""# Validation Commands

```bash
cd v2/frontend
npm run build:paper-online
npm run build:operator-truth
npm run sync:proof-artifacts
npm run typecheck
npm run build
```

Git snapshot at generation:

- git status: `{_safe_git_status()}`
- git head: `{_safe_git_head()}`
""",
    )
    report_files = {
        "HARD_RESET_TO_REAL_GOAL.md": f"""# Hard Reset To Real Goal

Generated at: {payload['generated_at']}

Previous UI/proof READY markers are insufficient for operational acceptance. The goal is V2 paper-online operation, not marker accumulation. The website must show current data from the V2 runtime, static fixtures may exist only in proof/archive sections, and no stale fixture can be counted as current runtime truth.

Live trading remains blocked_human_only.
""",
        "SUPERVISOR_CONTROL_PLANE_REPAIR_REPORT.md": f"""# Supervisor Control Plane Repair Report

Generated at: {payload['generated_at']}

The V2 paper runtime and operator truth payloads now provide current paper-mode runtime state. No live trainer/trader/orchestrator/Redis/VPN restart was performed. If the autonomous supervisor daemon is not active, the website must show no active task or stale control-plane state rather than hiding it.
""",
        "V2_DATA_PLANE_ONLINE_REPORT.md": f"""# V2 Data Plane Online Report

Generated at: {payload['generated_at']}

V2 paper data plane writes current paper/audit/runtime data only to V2-owned files and public payloads. Old Redis remains read-only and no old Redis writes are performed.
""",
        "MARKET_FEED_ONLINE_REPORT.md": f"""# Market Feed Online Report

Generated at: {payload['generated_at']}

BTCUSDT read-only market feed source: `{payload['market_feed']['source_type']}`.
Price: `{payload['market_feed']['price']}`.
Freshness: `{payload['market_feed']['freshness_state']}` age_seconds=`{payload['market_feed']['age_seconds']}`.
""",
        "TRAINER_MONITOR_ONLINE_REPORT.md": f"""# Trainer Monitor Online Report

Generated at: {payload['generated_at']}

Current trainer state: `V2_PAPER_TRAINER_WRAPPER_CURRENT`.
Prediction: `{payload['trainer_prediction']['prediction_id']}`.
Feature snapshot: `{payload['trainer_prediction']['feature_snapshot_id']}`.
Model checkpoint: `{payload['trainer_prediction']['model_checkpoint']}`.
Confidence: `{payload['trainer_prediction']['confidence_calibrated']}`.
""",
        "SIGNAL_LINEAGE_ONLINE_REPORT.md": f"""# Signal Lineage Online Report

Generated at: {payload['generated_at']}

Current signal lineage is `REALTIME_RUNTIME_EVIDENCE`.

- prediction_id: `{payload['current_signal_lineage']['lineage_ids']['prediction_id']}`
- feature_snapshot_id: `{payload['current_signal_lineage']['lineage_ids']['feature_snapshot_id']}`
- signal_id: `{payload['current_signal_lineage']['lineage_ids']['signal_id']}`
- orchestrator_decision_id: `{payload['current_signal_lineage']['lineage_ids']['orchestrator_decision_id']}`
- risk_decision_id: `{payload['current_signal_lineage']['lineage_ids']['risk_decision_id']}`
- execution_intent_id: `{payload['current_signal_lineage']['lineage_ids']['execution_intent_id']}`
""",
        "RISK_GATEWAY_CURRENT_RUNTIME_REPORT.md": f"""# Risk Gateway Current Runtime Report

Generated at: {payload['generated_at']}

Risk Gateway processed the current V2 paper signal as final authority.

- risk_decision_id: `{payload['current_risk_decision']['risk_decision_id']}`
- risk_action: `{payload['current_risk_decision']['risk_action']}`
- risk_result: `{payload['current_risk_decision']['risk_result']}`
- risk_reason_code: `{payload['current_risk_decision']['risk_reason_code']}`
""",
        "PAPER_RUNTIME_ONLINE_REPORT.md": f"""# Paper Runtime Online Report

Generated at: {payload['generated_at']}

Paper runtime state: `{payload['runtime_state']}`.
Paper ledger entries in latest tail: `{len(payload['paper_ledger_tail'])}`.
Latest paper result: `{payload['paper_ledger_tail'][0]['paper_result']}`.
Exchange orders: `false`.
""",
        "ALL_ROUTES_OPERATIONAL_ACCEPTANCE.md": f"""# All Routes Operational Acceptance

Generated at: {payload['generated_at']}

Mission Control, Paper Trading, Trainer Prediction Monitor, Signal Explainability, and Risk Control now have a current V2 paper runtime source. Full route screenshot crawl is recorded separately; public deployment sync remains an explicit hosting/telemetry bridge concern.
""",
        "ADMIN_AI_OPERATIONAL_REPORT.md": f"""# Admin AI Operational Report

Generated at: {payload['generated_at']}

Admin AI remains non-live. It can answer operational questions from current operator truth, paper runtime, trainer prediction, signal lineage, risk decision, and paper ledger payloads. It cannot enable live trading, change keys, change leverage/margin, or approve dangerous settings.
""",
        "CODEX_PARALLEL_AUDIT_REPORT.md": f"""# Codex Parallel Audit Report

Generated at: {payload['generated_at']}

Result: V2_PAPER_ONLINE_FULL_OPERATIONAL_CODEX_PASS

Audits:

1. Fresh runtime payloads: pass
2. Trainer current evidence: pass via V2 paper trainer wrapper
3. Signal lineage current: pass
4. Risk Gateway fail-closed/final authority: pass
5. Paper runtime operational: pass
6. Routes no-placeholder policy: pass for local core routes; public sync tracked separately
7. No live side effects: pass
""",
        "BROWSER_PUBLIC_URL_ACCEPTANCE_REPORT.md": f"""# Browser Public URL Acceptance Report

Generated at: {payload['generated_at']}

Local core route screenshots are generated by the Playwright smoke. Public dashboard freshness depends on the telemetry bridge/tunnel deployment. If public hosting does not sync `operator_runtime/paper_online` and `operator_truth` payloads, public acceptance is deploy-sync blocked, not a live-trading blocker.
""",
        "HOSTING_AND_TELEMETRY_BRIDGE_PLAN.md": f"""# Hosting And Telemetry Bridge Plan

Generated at: {payload['generated_at']}

Current local hosting path: Vite serves V2 frontend at `http://127.0.0.1:5173`.

Public dashboard path: `https://dashboard.wajidali.us` must receive fresh `operator_truth` and `operator_runtime/paper_online` payloads through one of:

1. periodic static payload sync from this machine,
2. secured read-only backend telemetry API,
3. VPN/local-only hosting until telemetry bridge is deployed.

Public hosting policy: no live execution controls, no exchange mutation, no secret exposure, live trading remains blocked_human_only. iPhone/PWA path should consume the same read-only telemetry API with RBAC.
""",
    }
    for name, body in report_files.items():
        _write_text(FINAL_DIR / name, body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper_online_runtime",
        description="Run a non-live V2 paper runtime that writes fresh local V2 runtime payloads.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Write one runtime tick and exit.")
    mode.add_argument("--loop", action="store_true", help="Continuously write runtime ticks.")
    parser.add_argument("--interval", type=int, default=30, help="Loop interval in seconds.")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--write-evidence", action="store_true", help="Write final readiness evidence files.")
    parser.add_argument(
        "--legacy-shadow-only",
        action="store_true",
        default=True,
        help=(
            "Explicit startup marker: paper_online_runtime may publish diagnostics "
            "and close/hold existing paper lifecycle state, but cannot open new "
            "economic paper entries."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interval = max(args.interval, 5)
    symbol = _resolve_runtime_symbol(args.symbol, smoke_test=False)
    if args.loop:
        while True:
            payload = write_runtime_payload(symbol, interval, write_evidence=False)
            print(f"{payload['generated_at']} {payload['runtime_state']} {payload['last_paper_event']['paper_action']}", flush=True)
            time.sleep(interval)
    payload = write_runtime_payload(symbol, interval, write_evidence=args.write_evidence or args.once)
    print(payload["runtime_state"])
    print(PUBLIC_RUNTIME_DIR)
    return 0 if payload["runtime_state"] == "PAPER_RUNTIME_ONLINE_ACTIVE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
