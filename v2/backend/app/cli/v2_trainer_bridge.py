"""V2 trainer bridge.

This worker bridges trainer evidence into V2 without starting legacy,
mutating legacy trainer state, writing old Redis, or inventing
predictions. It rejects generic paper wrapper predictions as full legacy
hybrid trainer parity and emits explicit blockers instead.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)
from v2.backend.app.services.trainer_bridge.service import (
    LEGACY_HYBRID_TRAINER_PRESENT,
    LEGACY_MANIFEST_PATH,
    LEGACY_SOURCE_PATH,
    LIVE_GATE_STATUS,
    MISSING_RUNTIME_EVIDENCE,
    WRAPPER_NOT_LEGACY_HYBRID_PARITY,
    detect_gpu_state,
    detect_trainer_process,
    evaluate_feature_snapshot,
    find_current_prediction,
    inspect_legacy_trainer_source,
    legacy_log_prediction_payload,
    utc_now,
)


WORKER_ID = "v2_trainer_bridge"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
LEGACY_ACTIVE_SYMBOL_SOURCE = "legacy_reference/config.py SYMBOLS via SymbolUniverseService"

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

SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    V2_ROOT / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]
UPSTREAM_SYMBOL_SCOPE_CANDIDATES = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_feature_pipeline_and_ta_worker"
    / "latest"
    / "v2_feature_pipeline_and_ta_worker_status.json",
    WORKER_STATUS_DIR / "v2_feature_pipeline_and_ta_worker_from_legacy_baseline_status.json",
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "v2_feature_snapshot_builder" / "latest" / "v2_feature_snapshot_builder_status.json",
]
FEATURE_SNAPSHOT_CANDIDATES = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "v2_feature_snapshot_builder" / "latest" / "v2_feature_snapshot_builder_status.json",
]
PREDICTION_CANDIDATES = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "trainer_prediction_current_record.json",
    V2_ROOT / "runtime" / "paper_online" / "latest" / "trainer_prediction_current_record.json",
    V2_ROOT / "frontend" / "public" / "legacy_trainer_restart_runtime" / "latest" / "legacy_trainer_current_prediction.json",
    REPO_ROOT / "claude_worklog" / "final_readiness" / "legacy_trainer_restart_runtime" / "latest" / "legacy_trainer_current_prediction.json",
]
LEGACY_READONLY_TRAINER_LOG = Path("/home/wali/Desktop/AI BOT/.logs/hybrid_trainer.log")
LEGACY_READONLY_CHECKPOINT_METADATA = Path(
    "/home/wali/Desktop/AI BOT/models/checkpoints/live_legacy/checkpoint_metadata_latest.json"
)

REQUIRED_PUBLIC_PAYLOAD_FIELDS = (
    "worker_id",
    "last_run_ts",
    "trainer_mode_one_of_PARITY_BRIDGE_V2_NATIVE",
    "last_prediction_ts",
    "predictions_emitted_total",
    "legacy_binary_state",
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


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    items: List[Any]
    if isinstance(value, str):
        items = [value]
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


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            return (data if isinstance(data, dict) else {}), _rel(candidate)
    return {}, None


def _load_first_payload(paths: List[Path]) -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in paths:
        if candidate.exists():
            data = _read_json(candidate)
            return (data if isinstance(data, dict) else {}), _rel(candidate)
    return {}, None


def build_symbol_scope(*, observed_symbols: List[str], input_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    overrides = input_overrides or {}
    public_payload, public_path = _load_symbol_universe_public_payload()
    upstream_payload, upstream_path = _load_first_payload(UPSTREAM_SYMBOL_SCOPE_CANDIDATES)
    source_payload: Dict[str, Any] = public_payload or upstream_payload or overrides
    legacy_seed = _as_symbol_list(
        source_payload.get("legacy_active_symbols")
        or overrides.get("legacy_active_symbols")
        or LEGACY_ACTIVE_SYMBOLS_25
    )
    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
    discovered = _as_symbol_list(
        source_payload.get("discovered_symbols")
        or source_payload.get("symbols_discovered")
        or source_payload.get("all_discovered_symbols")
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
        source_payload.get("dynamic_discovered_symbols")
        or source_payload.get("dynamic_symbols")
        or overrides.get("dynamic_discovered_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(source_payload.get("training_symbols") or overrides.get("training_symbols"))
    paper_symbols = _as_symbol_list(source_payload.get("paper_symbols") or overrides.get("paper_symbols"))
    observed = _as_symbol_list(observed_symbols)
    binance_confirmed = _as_symbol_list(
        source_payload.get("binance_usdm_confirmed_symbols")
        or source_payload.get("tradable_symbols")
        or overrides.get("binance_usdm_confirmed_symbols")
    )
    live_blocked = sorted(set(binance_confirmed or discovered or service.legacy_active_symbols()))
    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD",
        "symbol_universe_public_payload_path": public_path or "",
        "symbol_scope_upstream_payload_status": "PRESENT" if upstream_path else "MISSING_UPSTREAM_SYMBOL_SCOPE_PAYLOAD",
        "symbol_scope_upstream_payload_path": upstream_path or "",
        "legacy_active_symbols": service.legacy_active_symbols(),
        "legacy_active_symbol_source": LEGACY_ACTIVE_SYMBOL_SOURCE,
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": observed,
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "live_symbol_policy": "live_symbols_empty_while_live_gate_blocked_human_only",
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "coinank_symbols_directly_tradable": False,
        "coinank_tradability_policy": "CoinAnk-only symbols remain intelligence candidates until Binance USD-M confirmation exists.",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def _first_existing(paths: List[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def build_status() -> Dict[str, Any]:
    legacy = inspect_legacy_trainer_source(repo_root=REPO_ROOT)
    feature_path = _first_existing(FEATURE_SNAPSHOT_CANDIDATES) or FEATURE_SNAPSHOT_CANDIDATES[0]
    feature = evaluate_feature_snapshot(feature_path, repo_root=REPO_ROOT)
    legacy_log_payload = legacy_log_prediction_payload(
        log_path=LEGACY_READONLY_TRAINER_LOG,
        checkpoint_metadata_path=LEGACY_READONLY_CHECKPOINT_METADATA,
    )
    extra_prediction_payloads: List[Tuple[str, Dict[str, Any]]] = []
    if legacy_log_payload:
        extra_prediction_payloads.append(
            (
                "legacy_readonly:/home/wali/Desktop/AI BOT/.logs/hybrid_trainer.log",
                legacy_log_payload,
            )
        )
    prediction = find_current_prediction(
        PREDICTION_CANDIDATES,
        repo_root=REPO_ROOT,
        extra_payloads=extra_prediction_payloads,
    )
    process = detect_trainer_process()
    gpu = detect_gpu_state()
    accepted_prediction = bool(prediction.get("accepted_as_legacy_hybrid_prediction"))
    observed_symbol = str(
        prediction.get("raw_prediction_payload", {}).get("symbol")
        or feature.get("raw_prediction_payload", {}).get("symbol")
        or ""
    )
    blockers: List[str] = []
    if legacy.get("legacy_binary_state") != "PRESENT":
        blockers.append(MISSING_RUNTIME_EVIDENCE)
    if legacy.get("manifest_status") != "SHA_MATCH":
        blockers.append("LEGACY_BASELINE_SHA_MISMATCH")
    if not accepted_prediction:
        blockers.append(str(prediction.get("prediction_evidence_status") or MISSING_RUNTIME_EVIDENCE))
    if feature.get("feature_snapshot_status") != "PRESENT":
        blockers.append("FEATURE_SNAPSHOT_MISSING")
    if feature.get("missing_feature_flags"):
        blockers.append("MISSING_FEATURE_FLAGS")
    if feature.get("stale_feature_flags"):
        blockers.append("STALE_FEATURE_FLAGS")
    for item in prediction.get("trainer_full_parity_blockers") or []:
        blockers.append(str(item))

    runtime_status = LEGACY_HYBRID_TRAINER_PRESENT if legacy.get("legacy_binary_state") == "PRESENT" else MISSING_RUNTIME_EVIDENCE
    if accepted_prediction and prediction.get("prediction_evidence_status"):
        runtime_status = str(prediction.get("prediction_evidence_status"))
    elif accepted_prediction:
        runtime_status = "LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT"
    elif prediction.get("prediction_evidence_status") == WRAPPER_NOT_LEGACY_HYBRID_PARITY:
        runtime_status = WRAPPER_NOT_LEGACY_HYBRID_PARITY

    status: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": utc_now(),
        "trainer_mode_one_of_PARITY_BRIDGE_V2_NATIVE": "PARITY_BRIDGE",
        "trainer_mode": "PARITY_BRIDGE",
        "legacy_binary_state": legacy.get("legacy_binary_state", "MISSING"),
        "legacy_hybrid_trainer_sha256": legacy.get("legacy_source_sha256", ""),
        "legacy_manifest_sha256": legacy.get("manifest_sha256", ""),
        "legacy_manifest_path": LEGACY_MANIFEST_PATH,
        "legacy_source_path": LEGACY_SOURCE_PATH,
        "legacy_baseline_sha_status": legacy.get("manifest_status", ""),
        "legacy_behavior_features": legacy.get("legacy_behavior_features", []),
        "legacy_methods_required_present": legacy.get("legacy_methods_required_present", {}),
        "legacy_config_dependencies": legacy.get("legacy_config_dependencies", []),
        "legacy_stream_contracts_readonly_reference": legacy.get("legacy_stream_contracts_readonly_reference", []),
        "legacy_gpu_behavior": legacy.get("legacy_gpu_behavior", []),
        "legacy_checkpoint_behavior": legacy.get("legacy_checkpoint_behavior", []),
        "trainer_process_state": process.get("trainer_process_state", "NOT_OBSERVED"),
        "trainer_process_count": process.get("trainer_process_count", 0),
        "trainer_process_sample": process.get("trainer_process_sample", []),
        "gpu_state": gpu.get("gpu_state", "GPU_EVIDENCE_MISSING"),
        "gpu_runtime": gpu,
        "last_prediction_ts": prediction.get("latest_prediction_timestamp", ""),
        "latest_prediction_timestamp": prediction.get("latest_prediction_timestamp", ""),
        "freshness_seconds": prediction.get("prediction_age_seconds"),
        "predictions_emitted_total": 1 if accepted_prediction else 0,
        "prediction_id": prediction.get("prediction_id", ""),
        "feature_snapshot_id": prediction.get("feature_snapshot_id") or feature.get("feature_snapshot_id", ""),
        "model_version": prediction.get("model_version", ""),
        "model_checkpoint_id": prediction.get("model_checkpoint_id", ""),
        "checkpoint_id": prediction.get("checkpoint_id") or prediction.get("model_checkpoint_id", ""),
        "checkpoint_evidence_status": "PRESENT" if accepted_prediction and prediction.get("model_checkpoint_id") else "MISSING_OR_REJECTED",
        "raw_confidence": prediction.get("raw_confidence"),
        "calibrated_confidence": prediction.get("calibrated_confidence"),
        "confidence_raw": prediction.get("raw_confidence"),
        "confidence_calibrated": prediction.get("calibrated_confidence"),
        "top_positive_features": prediction.get("top_positive_features", []),
        "top_negative_features": prediction.get("top_negative_features", []),
        "missing_feature_flags": feature.get("missing_feature_flags", []),
        "stale_feature_flags": feature.get("stale_feature_flags", []),
        "unused_feature_flags": [],
        "lineage_derivation_warnings": prediction.get("lineage_derivation_warnings", []),
        "trainer_full_parity_blockers": sorted(set(map(str, prediction.get("trainer_full_parity_blockers") or []))),
        "legacy_readonly_log_bridge": {
            "status": "PRESENT" if legacy_log_payload else "MISSING_OR_UNPARSEABLE",
            "log_path": str(LEGACY_READONLY_TRAINER_LOG),
            "checkpoint_metadata_path": str(LEGACY_READONLY_CHECKPOINT_METADATA),
        },
        "trainer_readiness": "READY" if accepted_prediction and not blockers else "BLOCKED",
        "feature_snapshot_trainer_readiness_signal": feature.get("trainer_readiness_signal", "UNKNOWN"),
        "feature_snapshot_dependency_status": feature.get("feature_snapshot_status", MISSING_RUNTIME_EVIDENCE),
        "runtime_evidence_status": runtime_status,
        "prediction_evidence_status": prediction.get("prediction_evidence_status", MISSING_RUNTIME_EVIDENCE),
        "accepted_as_legacy_hybrid_prediction": accepted_prediction,
        "prediction_source_path": prediction.get("prediction_source_path", ""),
        "prediction_source_type": prediction.get("prediction_source_type", ""),
        "prediction_candidates_seen": prediction.get("prediction_candidates_seen", []),
        "rejected_prediction_sources": [
            item
            for item in prediction.get("prediction_candidates_seen", [])
            if not item.get("accepted_as_legacy_hybrid_prediction")
        ],
        "source_feature_snapshot": feature,
        "error_blocker_state": sorted(set(blockers)),
        "fail_closed": bool(blockers),
        "missing_runtime_evidence": bool(blockers),
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "live_blocked": True,
        "exchange_action_taken": False,
        "legacy_mutation_performed": False,
        "old_redis_write_performed": False,
        "subprocess_invocation": "not_started_by_bridge",
        "legacy_state_dirs_writable_by_bridge": False,
    }
    status.update(build_symbol_scope(observed_symbols=[observed_symbol] if observed_symbol else []))
    return status


def write_status(status: Dict[str, Any]) -> None:
    for path in (PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, WORKER_STATUS_FILE):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bridge",), default="bridge")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--readonly", action="store_true", default=True)
    parser.add_argument("--readonly-only", action="store_true", default=True)
    return parser.parse_args(argv)


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    del args
    status = build_status()
    write_status(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.loop:
        args.once = True
    while True:
        status = run_once(args)
        if not args.loop:
            return 2 if status.get("fail_closed") else 0
        time.sleep(max(1.0, float(args.interval)))


if __name__ == "__main__":
    sys.exit(main())
