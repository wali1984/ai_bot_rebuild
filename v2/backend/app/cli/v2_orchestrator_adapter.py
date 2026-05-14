"""V2 orchestrator adapter — standalone CLI worker.

Lifts the previously in-process composition runtime at
``v2/backend/app/composition/orchestrator_decision/runtime.py`` into a
standalone CLI subscriber. The adapter consumes ``trainer_prediction``
records from the V2 paper runtime bundle (or trainer-bridge payload),
assembles ``OrchestratorDecisionRecord`` instances via the existing
service code, and publishes them as a public operator payload.

Critical invariant (asserted by tests):

  - The orchestrator never overrides the risk gateway. The orchestrator
    only proposes one of ``{open_long, open_short, hold, abstain}``;
    the binding gate is the risk gateway. The closed decision-action
    enum prevents the adapter from ever inventing an ``execute`` or
    ``force_open`` action, and the public payload carries the
    ``cannot_bypass_risk_gateway`` / ``orchestrator_overrides_risk``
    flags so Codex can re-verify the invariant at review time.

Hard rules (asserted by tests):
  - Fail-closed if the source bundle is missing, invalid JSON, or
    older than the configured stale threshold.
  - Live gate is permanently ``blocked_human_only``.
  - No exchange-mutation method names; no Binance/ccxt/Redis imports
    or writer calls.
  - Symbol Universe contract: scope is read via the V2 Symbol Universe
    service; the 25-symbol legacy active subset is surfaced as
    ``legacy_active_symbols`` and is not the universe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from v2.backend.app.composition.orchestrator_decision import (
    OrchestratorDecisionCompositionError,
    build_orchestrator_decision_evaluator,
)
from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    OrchestratorDecisionDomainError,
)
from v2.backend.app.domain.trainer_prediction_output import (
    PREDICTION_DIRECTION_FLAT,
    PREDICTION_DIRECTION_LONG,
    PREDICTION_DIRECTION_SHORT,
    PREDICTION_FRESHNESS_FRESH,
    PREDICTION_FRESHNESS_MISSING,
    PREDICTION_FRESHNESS_STALE,
    TrainerPredictionDomainError,
    TrainerPredictionRecord,
)
from v2.backend.app.services.orchestrator_decision import (
    OrchestratorDecisionServiceError,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_orchestrator_adapter"
SOURCE_RUNTIME_ID = "paper_online"
LIVE_GATE_STATUS = "blocked_human_only"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_ORCHESTRATOR_ADAPTER"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
CODEX_REVIEW_TRIGGER = "codex_review_v2_orchestrator_adapter"

DEFAULT_WARN_THRESHOLD_SECONDS = 120
DEFAULT_STALE_THRESHOLD_SECONDS = 600
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.55

LEGACY_SOURCE_PATHS: List[str] = [
    "legacy_reference/rl/orchestrator_worker.py",
    "legacy_reference/rl/hybrid_trainer.py",
    "legacy_reference/risk/risk_evaluator.py",
    "legacy_reference/risk/auto_deleverager.py",
    "legacy_reference/risk/hedge_cage_manager.py",
    "legacy_reference/trading/signal_router.py",
    "legacy_reference/trading/trader.py",
    "legacy_reference/rl/signal_state_manager.py",
    "legacy_reference/monitor_trainer_signals.py",
    "legacy_reference/scripts/trace_symbol_e2e.py",
]

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

BUNDLE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / SOURCE_RUNTIME_ID
    / "latest"
    / "paper_runtime_status.json",
    V2_ROOT / "runtime" / SOURCE_RUNTIME_ID / "latest" / "paper_runtime_status.json",
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_trainer_bridge"
    / "latest"
    / "v2_trainer_bridge_status.json",
    V2_ROOT
    / "runtime"
    / "v2_trainer_bridge"
    / "latest"
    / "v2_trainer_bridge_status.json",
]

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
    "source_runtime_id",
    "legacy_source_paths",
    "live_blocked",
    "decision_record",
    "decision_record_present",
    "decision_action",
    "decision_reason_code",
    "decision_id",
    "prediction_id",
    "feature_snapshot_id",
    "symbol",
    "stale_threshold_seconds",
    "warn_threshold_seconds",
    "low_confidence_threshold",
    "orchestrator_overrides_risk",
    "cannot_bypass_risk_gateway",
    "risk_gateway_binding",
    "upstream_risk_decision_action",
    "upstream_risk_decision_observed",
    "decision_action_is_proposal_only",
    "allowed_decision_actions",
    "codex_review_trigger",
    "codex_review_emitted_at",
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

ALLOWED_DECISION_ACTIONS: Tuple[str, ...] = (
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_ABSTAIN,
)


# ---------------------------------------------------------------------------
# time / IO helpers
# ---------------------------------------------------------------------------


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_iso_to_ms(ts: Optional[str]) -> Optional[int]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        parsed = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            parsed = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return int(parsed.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def freshness_state(
    age_seconds: Optional[int],
    *,
    warn: int,
    stale: int,
) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds <= warn:
        return "CURRENT"
    if age_seconds <= stale:
        return "WARN"
    return "STALE"


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# symbol universe
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
                rel = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(candidate)
            return (data if isinstance(data, dict) else {}), rel
    return {}, None


def build_symbol_scope(*, observed_symbols: List[str]) -> Dict[str, Any]:
    public_payload, public_path = _load_symbol_universe_public_payload()
    legacy_seed = _as_symbol_list(
        public_payload.get("legacy_active_symbols") or LEGACY_ACTIVE_SYMBOLS_25
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
# bundle loading
# ---------------------------------------------------------------------------


def load_bundle(
    args: argparse.Namespace,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Return (bundle_or_None, source_payload_path, status).

    status in {"present", "missing", "load_failed"}.
    """
    if args.source_file:
        path = Path(args.source_file)
        if not path.exists():
            return None, str(path), "missing"
        data = _read_json(path)
        if not isinstance(data, dict):
            return None, str(path), "load_failed"
        return data, str(path), "present"
    for candidate in BUNDLE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            if not isinstance(data, dict):
                continue
            try:
                rel = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(candidate)
            return data, rel, "present"
    return None, "", "missing"


def _bundle_age_seconds(bundle: Mapping[str, Any]) -> Optional[int]:
    ts_ms_raw = bundle.get("generated_at_ms")
    ts_ms: Optional[int]
    if isinstance(ts_ms_raw, (int, float)):
        ts_ms = int(ts_ms_raw)
    else:
        ts_ms = parse_iso_to_ms(bundle.get("generated_at"))
    if ts_ms is None:
        return None
    return max(0, int((now_ms() - ts_ms) / 1000))


# ---------------------------------------------------------------------------
# trainer_prediction extraction + domain mapping
# ---------------------------------------------------------------------------


_SIDE_TO_DIRECTION: Dict[str, str] = {
    "long": PREDICTION_DIRECTION_LONG,
    "buy": PREDICTION_DIRECTION_LONG,
    "open_long": PREDICTION_DIRECTION_LONG,
    "short": PREDICTION_DIRECTION_SHORT,
    "sell": PREDICTION_DIRECTION_SHORT,
    "open_short": PREDICTION_DIRECTION_SHORT,
    "flat": PREDICTION_DIRECTION_FLAT,
    "hold": PREDICTION_DIRECTION_FLAT,
    "none": PREDICTION_DIRECTION_FLAT,
    "": PREDICTION_DIRECTION_FLAT,
}

_FRESHNESS_STATE_TO_FLAG: Dict[str, str] = {
    "CURRENT": PREDICTION_FRESHNESS_FRESH,
    "WARN": PREDICTION_FRESHNESS_FRESH,
    "STALE": PREDICTION_FRESHNESS_STALE,
    "MISSING": PREDICTION_FRESHNESS_MISSING,
}


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if not math.isfinite(candidate):
            return None
        return candidate
    if isinstance(value, str):
        try:
            candidate = float(value)
        except ValueError:
            return None
        if not math.isfinite(candidate):
            return None
        return candidate
    return None


def _clamp_unit(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _feature_codes(values: Any) -> Tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    out: List[str] = []
    for raw in values:
        if isinstance(raw, dict):
            raw = raw.get("feature_code") or raw.get("code") or raw.get("name")
        if not isinstance(raw, str):
            continue
        code = raw.strip()
        if not code or any(c.isspace() for c in code):
            continue
        if code in out:
            continue
        out.append(code)
        if len(out) >= 8:
            break
    return tuple(out)


def _direction_from_side(side: Any) -> str:
    if isinstance(side, str):
        return _SIDE_TO_DIRECTION.get(side.strip().lower(), PREDICTION_DIRECTION_FLAT)
    return PREDICTION_DIRECTION_FLAT


def _freshness_flag(freshness_state_str: Any) -> str:
    if isinstance(freshness_state_str, str):
        return _FRESHNESS_STATE_TO_FLAG.get(
            freshness_state_str.strip().upper(), PREDICTION_FRESHNESS_MISSING
        )
    return PREDICTION_FRESHNESS_MISSING


def _market_age_ms(prediction: Mapping[str, Any], freshness_flag_value: str) -> Optional[int]:
    if freshness_flag_value == PREDICTION_FRESHNESS_MISSING:
        return None
    age_seconds = prediction.get("market_age_seconds")
    if not isinstance(age_seconds, (int, float)) or isinstance(age_seconds, bool):
        age_seconds = prediction.get("age_seconds")
    if not isinstance(age_seconds, (int, float)) or isinstance(age_seconds, bool):
        return 0
    age_ms = int(max(0.0, float(age_seconds)) * 1000)
    return age_ms


def _extract_trainer_prediction(
    bundle: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (raw_trainer_prediction_dict, source_origin)."""
    trainer_prediction = bundle.get("trainer_prediction")
    if isinstance(trainer_prediction, dict) and trainer_prediction.get("prediction_id"):
        return dict(trainer_prediction), "paper_runtime_bundle.trainer_prediction"
    # trainer_bridge fallback shape
    if bundle.get("prediction_id"):
        prediction = {
            "prediction_id": bundle.get("prediction_id"),
            "feature_snapshot_id": bundle.get("feature_snapshot_id"),
            "symbol": (
                bundle.get("symbol")
                or (
                    bundle.get("observed_symbols")[0]
                    if isinstance(bundle.get("observed_symbols"), list)
                    and bundle.get("observed_symbols")
                    else ""
                )
            ),
            "generated_at": bundle.get("latest_prediction_timestamp")
            or bundle.get("last_prediction_ts")
            or bundle.get("generated_at"),
            "confidence_raw": bundle.get("raw_confidence"),
            "confidence_calibrated": bundle.get("calibrated_confidence"),
            "raw_output": {"side": bundle.get("direction") or "flat"},
            "model_version": bundle.get("model_version")
            or bundle.get("model_checkpoint_id")
            or "",
            "model_checkpoint": bundle.get("model_checkpoint_id") or "",
            "freshness_state": bundle.get("freshness_state"),
            "market_age_seconds": bundle.get("freshness_seconds"),
            "worker_health_status": bundle.get("trainer_readiness"),
            "top_positive_features": bundle.get("top_positive_features"),
            "top_negative_features": bundle.get("top_negative_features"),
        }
        return prediction, "v2_trainer_bridge.bundle"
    return None, ""


def _build_trainer_prediction_record(
    *,
    raw: Mapping[str, Any],
    bundle_age_seconds: Optional[int],
) -> Tuple[Optional[TrainerPredictionRecord], List[str]]:
    """Map a raw trainer_prediction dict to a validated record.

    Returns (record_or_None, mapping_warnings).
    """
    warnings: List[str] = []
    prediction_id = str(raw.get("prediction_id") or "").strip()
    feature_snapshot_id = str(raw.get("feature_snapshot_id") or "").strip()
    symbol = str(raw.get("symbol") or "").strip().upper()
    if not prediction_id or not feature_snapshot_id or not symbol:
        warnings.append("missing_required_prediction_identity_fields")
        return None, warnings

    model_version = str(
        raw.get("model_version") or raw.get("model_checkpoint") or "v2_unknown_model"
    ).strip() or "v2_unknown_model"
    checkpoint_id = str(
        raw.get("checkpoint_id")
        or raw.get("model_checkpoint")
        or raw.get("model_checkpoint_id")
        or "v2_unknown_checkpoint"
    ).strip() or "v2_unknown_checkpoint"

    prediction_ts_ms_raw = raw.get("prediction_ts_ms")
    if isinstance(prediction_ts_ms_raw, (int, float)) and not isinstance(
        prediction_ts_ms_raw, bool
    ):
        prediction_ts_ms = int(prediction_ts_ms_raw)
    else:
        parsed = parse_iso_to_ms(raw.get("generated_at"))
        if parsed is None and bundle_age_seconds is not None:
            parsed = now_ms() - bundle_age_seconds * 1000
        if parsed is None:
            parsed = now_ms()
        prediction_ts_ms = max(0, int(parsed))

    raw_output = raw.get("raw_output") if isinstance(raw.get("raw_output"), dict) else {}
    direction = _direction_from_side(raw_output.get("side") or raw.get("direction"))

    confidence_raw = _coerce_float(raw.get("confidence_raw"))
    if confidence_raw is None:
        confidence_raw = _coerce_float(raw.get("raw_confidence")) or 0.0
    confidence_raw = _clamp_unit(confidence_raw)
    confidence_calibrated = _coerce_float(raw.get("confidence_calibrated"))
    if confidence_calibrated is None:
        confidence_calibrated = (
            _coerce_float(raw.get("calibrated_confidence")) or confidence_raw
        )
    confidence_calibrated = _clamp_unit(confidence_calibrated)

    worker_id_raw = str(raw.get("worker_id") or "v2_trainer_bridge").strip() or "v2_trainer_bridge"
    health_raw = raw.get("worker_health_status") or raw.get("trainer_state") or raw.get("trainer_readiness")
    if isinstance(health_raw, str):
        canonical = health_raw.strip().upper()
        if canonical in {"HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"}:
            worker_health_status = canonical
        elif canonical in {"READY", "READY_TO_RUN"}:
            worker_health_status = "HEALTHY"
        elif canonical in {"BLOCKED", "STOPPED"}:
            worker_health_status = "CRITICAL"
        else:
            worker_health_status = "UNKNOWN"
    else:
        worker_health_status = "UNKNOWN"

    freshness_flag_value = _freshness_flag(raw.get("freshness_state"))
    source_freshness_age_ms = _market_age_ms(raw, freshness_flag_value)

    top_positive = _feature_codes(
        raw.get("top_positive_feature_codes") or raw.get("top_positive_features")
    )
    top_negative_seed = (
        raw.get("top_negative_feature_codes") or raw.get("top_negative_features") or []
    )
    top_negative_filtered = tuple(
        code for code in _feature_codes(top_negative_seed) if code not in top_positive
    )

    try:
        record = TrainerPredictionRecord(
            prediction_id=prediction_id,
            feature_snapshot_id=feature_snapshot_id,
            symbol=symbol,
            model_version=model_version,
            checkpoint_id=checkpoint_id,
            prediction_ts_ms=prediction_ts_ms,
            direction=direction,
            confidence_raw=confidence_raw,
            confidence_calibrated=confidence_calibrated,
            worker_id=worker_id_raw,
            worker_health_status=worker_health_status,
            freshness_flag=freshness_flag_value,
            source_freshness_age_ms=source_freshness_age_ms,
            top_positive_feature_codes=top_positive,
            top_negative_feature_codes=top_negative_filtered,
        )
    except TrainerPredictionDomainError as exc:
        warnings.append(f"trainer_prediction_validation_failed:{exc.code}:{exc.field}")
        return None, warnings
    return record, warnings


# ---------------------------------------------------------------------------
# upstream risk-decision observation (read-only)
# ---------------------------------------------------------------------------


def _observe_upstream_risk_decision(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    lineage = bundle.get("current_signal_lineage") if isinstance(bundle, dict) else None
    if not isinstance(lineage, dict):
        return {
            "observed": False,
            "risk_action": None,
            "risk_decision_id": None,
            "risk_reason_code": None,
            "live_blocked": True,
        }
    record = lineage.get("risk_decision")
    if not isinstance(record, dict):
        return {
            "observed": False,
            "risk_action": None,
            "risk_decision_id": None,
            "risk_reason_code": None,
            "live_blocked": True,
        }
    live_blocked_raw = record.get("live_blocked")
    return {
        "observed": True,
        "risk_action": record.get("risk_action"),
        "risk_decision_id": record.get("risk_decision_id"),
        "risk_reason_code": record.get("risk_reason_code"),
        "live_blocked": True if not isinstance(live_blocked_raw, bool) else live_blocked_raw,
    }


# ---------------------------------------------------------------------------
# decision record -> dict
# ---------------------------------------------------------------------------


def _decision_record_to_dict(record: Any) -> Dict[str, Any]:
    return {
        "schema": "v2_orchestrator_decision_record_v1",
        "decision_id": record.decision_id,
        "prediction_id": record.prediction_id,
        "feature_snapshot_id": record.feature_snapshot_id,
        "symbol": record.symbol,
        "decision_ts_ms": int(record.decision_ts_ms),
        "decision_action": record.decision_action,
        "decision_reason_code": record.decision_reason_code,
        "input_prediction_direction": record.input_prediction_direction,
        "input_prediction_confidence_calibrated": float(
            record.input_prediction_confidence_calibrated
        ),
        "input_prediction_freshness_flag": record.input_prediction_freshness_flag,
        "input_worker_health_status": record.input_worker_health_status,
        "live_blocked": bool(record.live_blocked),
        "risk_gateway_binding": True,
        "cannot_bypass_risk_gateway": True,
        "orchestrator_overrides_risk": False,
        "exchange_action_taken": False,
        "live_gate": LIVE_GATE_STATUS,
    }


def _empty_decision_record() -> Dict[str, Any]:
    return {
        "schema": "v2_orchestrator_decision_record_v1",
        "decision_id": "",
        "prediction_id": "",
        "feature_snapshot_id": "",
        "symbol": "",
        "decision_ts_ms": 0,
        "decision_action": "",
        "decision_reason_code": "",
        "input_prediction_direction": "",
        "input_prediction_confidence_calibrated": 0.0,
        "input_prediction_freshness_flag": "",
        "input_worker_health_status": "",
        "live_blocked": True,
        "risk_gateway_binding": True,
        "cannot_bypass_risk_gateway": True,
        "orchestrator_overrides_risk": False,
        "exchange_action_taken": False,
        "live_gate": LIVE_GATE_STATUS,
    }


# ---------------------------------------------------------------------------
# status payload
# ---------------------------------------------------------------------------


def build_status_payload(
    *,
    run_ts: str,
    source_payload_path: str,
    decision_record: Mapping[str, Any],
    decision_record_present: bool,
    fail_closed: bool,
    fail_closed_reason: str,
    missing_runtime_evidence: bool,
    runtime_evidence_status: str,
    freshness_seconds: Optional[int],
    warn_threshold: int,
    stale_threshold: int,
    low_confidence_threshold: float,
    upstream_risk: Mapping[str, Any],
    symbol_scope: Mapping[str, Any],
    mapping_warnings: List[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_ts,
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
        "source_runtime_id": SOURCE_RUNTIME_ID,
        "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
        "live_blocked": True,
        "decision_record": dict(decision_record),
        "decision_record_present": bool(decision_record_present),
        "decision_action": str(decision_record.get("decision_action") or ""),
        "decision_reason_code": str(decision_record.get("decision_reason_code") or ""),
        "decision_id": str(decision_record.get("decision_id") or ""),
        "prediction_id": str(decision_record.get("prediction_id") or ""),
        "feature_snapshot_id": str(decision_record.get("feature_snapshot_id") or ""),
        "symbol": str(decision_record.get("symbol") or ""),
        "stale_threshold_seconds": int(stale_threshold),
        "warn_threshold_seconds": int(warn_threshold),
        "low_confidence_threshold": float(low_confidence_threshold),
        "orchestrator_overrides_risk": False,
        "cannot_bypass_risk_gateway": True,
        "risk_gateway_binding": True,
        "upstream_risk_decision_action": upstream_risk.get("risk_action"),
        "upstream_risk_decision_observed": bool(upstream_risk.get("observed")),
        "decision_action_is_proposal_only": True,
        "allowed_decision_actions": list(ALLOWED_DECISION_ACTIONS),
        "codex_review_trigger": CODEX_REVIEW_TRIGGER,
        "codex_review_emitted_at": run_ts,
        "mapping_warnings": list(mapping_warnings),
    }
    payload.update(symbol_scope)
    return payload


def write_status(status: Mapping[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(body)
    LOCAL_STATUS_FILE.write_text(body)
    WORKER_STATUS_FILE.write_text(body)


def maybe_write_status(args: argparse.Namespace, status: Mapping[str, Any]) -> None:
    if bool(getattr(args, "no_write", False)):
        return
    write_status(status)


# ---------------------------------------------------------------------------
# main run loop
# ---------------------------------------------------------------------------


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_ts = iso_now()
    warn_threshold = max(
        1, int(getattr(args, "warn_threshold_seconds", DEFAULT_WARN_THRESHOLD_SECONDS))
    )
    stale_threshold = max(
        warn_threshold + 1,
        int(getattr(args, "stale_threshold_seconds", DEFAULT_STALE_THRESHOLD_SECONDS)),
    )
    low_confidence_threshold = float(
        getattr(args, "low_confidence_threshold", DEFAULT_LOW_CONFIDENCE_THRESHOLD)
    )
    if not math.isfinite(low_confidence_threshold):
        low_confidence_threshold = DEFAULT_LOW_CONFIDENCE_THRESHOLD
    low_confidence_threshold = _clamp_unit(low_confidence_threshold)

    bundle, source_path, load_status = load_bundle(args)
    observed: List[str] = []
    if isinstance(bundle, dict):
        market_feed = bundle.get("market_feed") if isinstance(bundle.get("market_feed"), dict) else None
        if market_feed and isinstance(market_feed.get("symbol"), str):
            observed = [market_feed["symbol"]]
        elif isinstance(bundle.get("trainer_prediction"), dict):
            sym = bundle["trainer_prediction"].get("symbol")
            if isinstance(sym, str) and sym:
                observed = [sym]
        elif isinstance(bundle.get("symbol"), str) and bundle.get("symbol"):
            observed = [bundle["symbol"]]
    symbol_scope = build_symbol_scope(observed_symbols=observed)
    upstream_risk = _observe_upstream_risk_decision(bundle or {})

    if load_status == "missing":
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            decision_record=_empty_decision_record(),
            decision_record_present=False,
            fail_closed=True,
            fail_closed_reason="no_runtime_source_found",
            missing_runtime_evidence=True,
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            freshness_seconds=None,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            low_confidence_threshold=low_confidence_threshold,
            upstream_risk=upstream_risk,
            symbol_scope=symbol_scope,
            mapping_warnings=[],
        )
        maybe_write_status(args, status)
        return status

    if load_status == "load_failed":
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            decision_record=_empty_decision_record(),
            decision_record_present=False,
            fail_closed=True,
            fail_closed_reason="runtime_source_invalid_json",
            missing_runtime_evidence=True,
            runtime_evidence_status="INVALID_PAYLOAD",
            freshness_seconds=None,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            low_confidence_threshold=low_confidence_threshold,
            upstream_risk=upstream_risk,
            symbol_scope=symbol_scope,
            mapping_warnings=[],
        )
        maybe_write_status(args, status)
        return status

    assert isinstance(bundle, dict)
    bundle_age = _bundle_age_seconds(bundle)
    bundle_fresh_state = freshness_state(bundle_age, warn=warn_threshold, stale=stale_threshold)

    if bundle_fresh_state in ("STALE", "MISSING"):
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            decision_record=_empty_decision_record(),
            decision_record_present=False,
            fail_closed=True,
            fail_closed_reason=(
                f"runtime_source_stale: age_seconds={bundle_age} "
                f"stale_threshold={stale_threshold}"
            ),
            missing_runtime_evidence=True,
            runtime_evidence_status="STALE_RUNTIME_EVIDENCE",
            freshness_seconds=bundle_age,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            low_confidence_threshold=low_confidence_threshold,
            upstream_risk=upstream_risk,
            symbol_scope=symbol_scope,
            mapping_warnings=[],
        )
        maybe_write_status(args, status)
        return status

    raw_prediction, raw_origin = _extract_trainer_prediction(bundle)
    if raw_prediction is None:
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            decision_record=_empty_decision_record(),
            decision_record_present=False,
            fail_closed=True,
            fail_closed_reason="missing_trainer_prediction",
            missing_runtime_evidence=True,
            runtime_evidence_status="MISSING_CHAIN_RECORDS",
            freshness_seconds=bundle_age,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            low_confidence_threshold=low_confidence_threshold,
            upstream_risk=upstream_risk,
            symbol_scope=symbol_scope,
            mapping_warnings=[f"missing_trainer_prediction_from:{raw_origin or 'none'}"],
        )
        maybe_write_status(args, status)
        return status

    record, mapping_warnings = _build_trainer_prediction_record(
        raw=raw_prediction, bundle_age_seconds=bundle_age
    )
    if record is None:
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            decision_record=_empty_decision_record(),
            decision_record_present=False,
            fail_closed=True,
            fail_closed_reason="trainer_prediction_validation_failed:" + ",".join(mapping_warnings),
            missing_runtime_evidence=True,
            runtime_evidence_status="TRAINER_PREDICTION_VALIDATION_FAILED",
            freshness_seconds=bundle_age,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            low_confidence_threshold=low_confidence_threshold,
            upstream_risk=upstream_risk,
            symbol_scope=symbol_scope,
            mapping_warnings=mapping_warnings,
        )
        maybe_write_status(args, status)
        return status

    try:
        evaluator = build_orchestrator_decision_evaluator(
            low_confidence_threshold=low_confidence_threshold,
            now_ms_clock=now_ms,
        )
        decision = evaluator(prediction=record)
    except (
        OrchestratorDecisionCompositionError,
        OrchestratorDecisionDomainError,
        OrchestratorDecisionServiceError,
    ) as exc:
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            decision_record=_empty_decision_record(),
            decision_record_present=False,
            fail_closed=True,
            fail_closed_reason=(
                f"orchestrator_decision_assembly_failed:{getattr(exc, 'code', exc.__class__.__name__)}"
                f":{getattr(exc, 'field', '')}"
            ),
            missing_runtime_evidence=False,
            runtime_evidence_status="DECISION_ASSEMBLY_FAILED",
            freshness_seconds=bundle_age,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            low_confidence_threshold=low_confidence_threshold,
            upstream_risk=upstream_risk,
            symbol_scope=symbol_scope,
            mapping_warnings=mapping_warnings,
        )
        maybe_write_status(args, status)
        return status

    decision_dict = _decision_record_to_dict(decision)
    status = build_status_payload(
        run_ts=run_ts,
        source_payload_path=source_path,
        decision_record=decision_dict,
        decision_record_present=True,
        fail_closed=False,
        fail_closed_reason="",
        missing_runtime_evidence=False,
        runtime_evidence_status="PRESENT",
        freshness_seconds=bundle_age,
        warn_threshold=warn_threshold,
        stale_threshold=stale_threshold,
        low_confidence_threshold=low_confidence_threshold,
        upstream_risk=upstream_risk,
        symbol_scope=symbol_scope,
        mapping_warnings=mapping_warnings,
    )
    maybe_write_status(args, status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--source-file",
        default=None,
        help=(
            "Path to a paper_online runtime bundle or trainer_bridge "
            "payload. If omitted, the adapter reads the paper_online "
            "public payload, then the trainer_bridge public payload."
        ),
    )
    parser.add_argument(
        "--warn-threshold-seconds",
        type=int,
        default=DEFAULT_WARN_THRESHOLD_SECONDS,
        help="freshness WARN threshold in seconds",
    )
    parser.add_argument(
        "--stale-threshold-seconds",
        type=int,
        default=DEFAULT_STALE_THRESHOLD_SECONDS,
        help="freshness STALE threshold in seconds (fail-closed boundary)",
    )
    parser.add_argument(
        "--low-confidence-threshold",
        type=float,
        default=DEFAULT_LOW_CONFIDENCE_THRESHOLD,
        help="abstain when prediction.confidence_calibrated < threshold",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--interval", type=int, default=30, help="seconds between loop iterations"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="dry-run; do not write the public payload",
    )
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


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
        except Exception:  # noqa: BLE001 - the loop must not crash
            pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
