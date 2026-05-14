"""V2 risk gateway runtime worker — standalone CLI worker.

Consumes ``OrchestratorDecisionRecord`` events from a V2-namespaced source
(JSON file or fallback V2 public payload) and emits ``RiskDecisionRecord``
stamps via ``v2.backend.app.services.risk_gateway.assemble_risk_decision_record``
through the existing composition runtime
(``v2.backend.app.composition.risk_gateway.build_risk_decision_evaluator``).

Hard rules (asserted by tests):
  - Live gate is permanently ``blocked_human_only`` regardless of input;
    no codepath opens it.
  - No legacy Redis writes. No exchange order / leverage / margin call.
  - No approval-token creation.
  - When the orchestrator decision input is absent (e.g. the legacy bot is
    shut down), trainer-parity inputs are classified as
    ``MISSING_RUNTIME_EVIDENCE`` and the worker fail-closes rather than
    synthesizing data.
  - Symbol scope is read via the V2 Symbol Universe service; the 25-symbol
    legacy active subset is exposed as ``legacy_active_symbols`` and is NOT
    treated as the full universe.
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

from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import RiskGatewayServiceError
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_risk_gateway_runtime_worker"
LIVE_GATE_STATUS = "blocked_human_only"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"

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

ORCHESTRATOR_DECISION_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "orchestrator_decision"
    / "latest"
    / "orchestrator_decision_status.json",
    V2_ROOT
    / "frontend"
    / "public"
    / "orchestrator_decision_evidence_reconciliation"
    / "latest"
    / "orchestrator_decision_record.json",
]

LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY: List[str] = [
    "wma:kill_switch",
    "wma:kill_switch:{account}",
    "wma:kill_switch:{symbol}",
    "risk_budget:state:{account_id}",
    "reversal:global",
    "toxicity:{symbol}",
    "market:state:contract",
    "regime:{symbol}",
]

LEGACY_RISK_GATE_SOURCE_PATHS: List[str] = [
    "legacy_reference/risk/shared_risk_gate.py",
    "legacy_reference/risk/adaptive_gate.py",
    "legacy_reference/risk/risk_state_machine.py",
    "legacy_reference/risk/halt_manager.py",
    "legacy_reference/risk/kill_switch.py",
    "legacy_reference/risk/margin_governor.py",
    "legacy_reference/risk/auto_deleverager.py",
    "legacy_reference/risk/global_breadth.py",
    "legacy_reference/risk/microstructure_toxicity.py",
    "legacy_reference/risk/market_state_contract.py",
    "legacy_reference/risk/reversal_detector.py",
    "legacy_reference/risk/intelligent_close_guard.py",
    "legacy_reference/risk/reduce_only_latch.py",
    "legacy_reference/risk/phase_controller.py",
    "legacy_reference/risk/risk_budget_allocator.py",
    "legacy_reference/risk/trainer_alignment.py",
    "legacy_reference/risk/trainer_intent.py",
    "legacy_reference/risk/hedge_cage_manager.py",
    "legacy_reference/risk/ltf_reversal.py",
    "legacy_reference/risk/market_regime.py",
]


REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
    "last_decision_id",
    "last_decision_ts",
    "last_risk_decision_id",
    "last_risk_decision_ts",
    "decisions_processed_total",
    "denials_breakdown",
    "risk_action",
    "risk_reason_code",
    "input_decision_action",
    "input_decision_reason_code",
    "symbol",
    "live_gate",
    "current_gate_state",
    "current_gate_state_must_equal_blocked_human_only",
    "gate_always_blocked_invariant",
    "fail_closed",
    "missing_runtime_evidence",
    "runtime_evidence_status",
    "freshness_seconds",
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
    "legacy_kill_switch_key_references",
    "legacy_risk_gate_source_paths",
    "source_payload_path",
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


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        items = [value]
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


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            try:
                rel = candidate.relative_to(REPO_ROOT)
                rel_str = str(rel)
            except ValueError:
                rel_str = str(candidate)
            return (data or {}), rel_str
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


def _decision_from_dict(record: Dict[str, Any]) -> OrchestratorDecisionRecord:
    return OrchestratorDecisionRecord(
        decision_id=str(record["decision_id"]),
        prediction_id=str(record["prediction_id"]),
        feature_snapshot_id=str(record["feature_snapshot_id"]),
        symbol=str(record["symbol"]),
        decision_ts_ms=int(record["decision_ts_ms"]),
        decision_action=str(record["decision_action"]),
        decision_reason_code=str(record["decision_reason_code"]),
        input_prediction_direction=str(record["input_prediction_direction"]),
        input_prediction_confidence_calibrated=float(
            record["input_prediction_confidence_calibrated"]
        ),
        input_prediction_freshness_flag=str(record["input_prediction_freshness_flag"]),
        input_worker_health_status=str(record["input_worker_health_status"]),
        live_blocked=True,
    )


def _load_orchestrator_decision_from_file(path: Path) -> Optional[Dict[str, Any]]:
    data = _read_json(path)
    if data is None:
        return None
    if isinstance(data, dict) and "decisions" in data and isinstance(data["decisions"], list):
        if not data["decisions"]:
            return None
        return data["decisions"][-1]
    if isinstance(data, dict) and "orchestrator_decision" in data:
        nested = data["orchestrator_decision"]
        if isinstance(nested, dict):
            return nested
    return data if isinstance(data, dict) else None


def load_orchestrator_decision(
    args: argparse.Namespace,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Return (decision_dict_or_None, source_payload_path, status).

    status ∈ {"present", "missing_runtime_evidence", "load_failed"}.
    """
    if args.decision_file:
        path = Path(args.decision_file)
        record = _load_orchestrator_decision_from_file(path)
        if record is None:
            return None, str(path), "load_failed"
        return record, str(path), "present"
    for candidate in ORCHESTRATOR_DECISION_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            record = _load_orchestrator_decision_from_file(candidate)
            if record is not None:
                try:
                    rel = candidate.relative_to(REPO_ROOT)
                    rel_str = str(rel)
                except ValueError:
                    rel_str = str(candidate)
                return record, rel_str, "present"
    return None, "", "missing_runtime_evidence"


def _now_ms_clock() -> int:
    return now_ms()


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
    decision_id = ""
    input_decision_action = ""
    input_decision_reason_code = ""
    decision_ts_ms: Optional[int] = None
    if decision_dict:
        decision_symbol = str(decision_dict.get("symbol", "")).upper()
        decision_id = str(decision_dict.get("decision_id", ""))
        input_decision_action = str(decision_dict.get("decision_action", ""))
        input_decision_reason_code = str(decision_dict.get("decision_reason_code", ""))
        try:
            decision_ts_ms = int(decision_dict.get("decision_ts_ms", 0)) or None
        except (TypeError, ValueError):
            decision_ts_ms = None
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_decision_id": decision_id,
        "last_decision_ts": iso_from_ms(decision_ts_ms) if decision_ts_ms else "",
        "last_risk_decision_id": "",
        "last_risk_decision_ts": "",
        "last_risk_decision_ts_ms": 0,
        "decisions_processed_total": 0,
        "denials_breakdown": {"deny_default": 1},
        "risk_action": "deny",
        "risk_reason_code": "deny_default",
        "input_decision_action": input_decision_action,
        "input_decision_reason_code": input_decision_reason_code,
        "symbol": decision_symbol,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "fail_closed": True,
        "missing_runtime_evidence": missing_runtime_evidence,
        "runtime_evidence_status": (
            "MISSING_RUNTIME_EVIDENCE"
            if missing_runtime_evidence
            else "INVALID_RUNTIME_EVIDENCE"
        ),
        "freshness_seconds": freshness_seconds_from_ms(decision_ts_ms),
        "fail_closed_reason": reason,
        "source_payload_path": source_payload_path,
        "legacy_kill_switch_key_references": list(
            LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY
        ),
        "legacy_risk_gate_source_paths": list(LEGACY_RISK_GATE_SOURCE_PATHS),
        "live_blocked": True,
        **symbol_scope,
    }


def build_success_status(
    *,
    decision: OrchestratorDecisionRecord,
    risk_record: Any,
    source_payload_path: str,
    run_started_ts: str,
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    risk_decision_ts_iso = dt.datetime.fromtimestamp(
        risk_record.risk_decision_ts_ms / 1000.0, tz=dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    denied = risk_record.risk_action == "deny"
    status = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_decision_id": decision.decision_id,
        "last_decision_ts": iso_from_ms(int(decision.decision_ts_ms)),
        "last_risk_decision_id": risk_record.risk_decision_id,
        "last_risk_decision_ts": risk_decision_ts_iso,
        "last_risk_decision_ts_ms": int(risk_record.risk_decision_ts_ms),
        "decisions_processed_total": 1,
        "denials_breakdown": {risk_record.risk_reason_code: 1} if denied else {},
        "risk_action": risk_record.risk_action,
        "risk_reason_code": risk_record.risk_reason_code,
        "input_decision_action": risk_record.input_decision_action,
        "input_decision_reason_code": risk_record.input_decision_reason_code,
        "symbol": risk_record.symbol,
        "prediction_id": risk_record.prediction_id,
        "feature_snapshot_id": risk_record.feature_snapshot_id,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "fail_closed": True,
        "missing_runtime_evidence": False,
        "runtime_evidence_status": "PRESENT",
        "freshness_seconds": freshness_seconds_from_ms(int(decision.decision_ts_ms)),
        "fail_closed_reason": "",
        "source_payload_path": source_payload_path,
        "live_blocked": True,
        "input_prediction_direction": decision.input_prediction_direction,
        "input_prediction_confidence_calibrated": (
            decision.input_prediction_confidence_calibrated
        ),
        "input_prediction_freshness_flag": decision.input_prediction_freshness_flag,
        "input_worker_health_status": decision.input_worker_health_status,
        "legacy_kill_switch_key_references": list(
            LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY
        ),
        "legacy_risk_gate_source_paths": list(LEGACY_RISK_GATE_SOURCE_PATHS),
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
    record_dict, source_path, load_status = load_orchestrator_decision(args)
    observed = []
    if record_dict and isinstance(record_dict.get("symbol"), str):
        observed = [record_dict["symbol"]]
    symbol_scope = build_symbol_scope(observed_symbols=observed)

    if load_status == "missing_runtime_evidence":
        status = build_fail_closed_status(
            reason="no_orchestrator_decision_source_found",
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
            reason="orchestrator_decision_payload_unreadable_or_empty",
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
            reason=f"invalid_orchestrator_decision_fields: {exc}",
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
            reason=f"orchestrator_decision_record_rejected: {exc}",
            source_payload_path=source_path,
            run_started_ts=run_started_ts,
            decision_dict=record_dict,
            symbol_scope=symbol_scope,
            missing_runtime_evidence=True,
        )
        write_status(status)
        return status

    evaluator = build_risk_decision_evaluator(now_ms_clock=_now_ms_clock)
    try:
        risk_record = evaluator(decision=decision)
    except RiskGatewayServiceError as exc:
        status = build_fail_closed_status(
            reason=f"risk_gateway_service_error: {exc}",
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
        risk_record=risk_record,
        source_payload_path=source_path,
        run_started_ts=run_started_ts,
        symbol_scope=symbol_scope,
    )
    # Fail-closed gate invariant: the gate stays blocked regardless of any allow.
    status["live_gate"] = LIVE_GATE_STATUS
    status["current_gate_state"] = LIVE_GATE_STATUS
    status["gate_always_blocked_invariant"] = True
    write_status(status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--decision-file",
        default=None,
        help="V2-namespaced JSON file containing an OrchestratorDecisionRecord (or a list under 'decisions')",
    )
    parser.add_argument(
        "--once", action="store_true", help="run a single iteration and exit"
    )
    parser.add_argument(
        "--loop", action="store_true", help="run continuously"
    )
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
        if status.get("risk_action") == "deny" and status.get("risk_reason_code") == "deny_default":
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
