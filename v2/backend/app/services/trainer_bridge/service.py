"""Evidence helpers for the V2 trainer bridge.

The bridge is deliberately evidence-first. It may inspect copied legacy
source, current V2/public payloads, process state, GPU state, and
checkpoint metadata, but it must not start legacy, train a model, write
legacy state, write old Redis, or synthesize predictions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


LIVE_GATE_STATUS = "blocked_human_only"
MISSING_RUNTIME_EVIDENCE = "MISSING_RUNTIME_EVIDENCE"
WRAPPER_NOT_LEGACY_HYBRID_PARITY = "WRAPPER_NOT_LEGACY_HYBRID_PARITY"
LEGACY_HYBRID_TRAINER_PRESENT = "LEGACY_HYBRID_TRAINER_PRESENT"
LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT = "LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT"
LEGACY_SOURCE_PATH = "v2/legacy_preserved/startup_baseline/rl/hybrid_trainer.py"
LEGACY_MANIFEST_PATH = (
    "claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/"
    "copied_baseline_manifest.json"
)
LEGACY_EXPECTED_SHA256 = "b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102"
MAX_PREDICTION_AGE_SECONDS = 900
REQUIRED_PREDICTION_FIELDS = (
    "prediction_id",
    "feature_snapshot_id",
    "model_checkpoint",
    "confidence_raw",
    "confidence_calibrated",
)
ACCEPTED_PREDICTION_SOURCE_PREFIXES = (
    "LEGACY_HYBRID_TRAINER",
    "V2_NATIVE_TRAINER",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def age_seconds(value: Any) -> Optional[int]:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def manifest_records(manifest_path: Path) -> List[Dict[str, Any]]:
    data = load_json(manifest_path)
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def find_manifest_record(records: Iterable[Mapping[str, Any]], legacy_rel_path: str) -> Dict[str, Any]:
    for record in records:
        if record.get("legacy_rel_path") == legacy_rel_path:
            return dict(record)
    return {}


def _regex_names(pattern: str, text: str) -> List[str]:
    return sorted(set(match.group(1) for match in re.finditer(pattern, text, re.MULTILINE)))


def inspect_legacy_trainer_source(
    *,
    repo_root: Path,
    source_rel_path: str = LEGACY_SOURCE_PATH,
    manifest_rel_path: str = LEGACY_MANIFEST_PATH,
) -> Dict[str, Any]:
    source_path = repo_root / source_rel_path
    manifest_path = repo_root / manifest_rel_path
    if not source_path.exists():
        return {
            "legacy_binary_state": "MISSING",
            "legacy_source_path": source_rel_path,
            "legacy_source_sha256": "",
            "manifest_sha256": LEGACY_EXPECTED_SHA256,
            "manifest_status": "MISSING_SOURCE",
            "legacy_behavior_features": [],
        }
    text = source_path.read_text(errors="replace")
    actual_sha = sha256_file(source_path)
    record = find_manifest_record(manifest_records(manifest_path), "rl/hybrid_trainer.py")
    classes = _regex_names(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    functions = _regex_names(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    method_names = _regex_names(r"^\s{4}def\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    behavior_features = [
        name
        for name in (
            "RTX5080FeatureExtractor",
            "RTX5080Policy",
            "GPUForcedPPO",
            "HybridTrainer",
            "HybridConfig",
            "RTX5080Optimizer",
        )
        if name in classes
    ]
    expected_methods = [
        "setup_models",
        "_publish_signal_payload",
        "_build_trade_signal",
        "_normalize_action_name",
        "_publish_signal_unified",
    ]
    return {
        "legacy_binary_state": "PRESENT",
        "legacy_source_path": source_rel_path,
        "legacy_source_sha256": actual_sha,
        "manifest_sha256": str(record.get("sha256") or LEGACY_EXPECTED_SHA256),
        "manifest_status": "SHA_MATCH" if actual_sha == str(record.get("sha256") or "") else "SHA_MISMATCH",
        "manifest_record": record,
        "source_size_bytes": source_path.stat().st_size,
        "legacy_classes_detected": classes[:80],
        "legacy_functions_detected_sample": functions[:80],
        "legacy_methods_detected_sample": method_names[:120],
        "legacy_behavior_features": behavior_features,
        "legacy_methods_required_present": {
            name: name in method_names for name in expected_methods
        },
        "legacy_config_dependencies": [
            "SYMBOLS",
            "TIMEFRAMES",
            "PREDICTION_LOOP_SECONDS",
            "SAVE_EVERY_LOOPS",
            "DISABLE_MODEL_SAVES",
            "OBS_SCHEMA_VERSION",
            "SAFE_MODE_DEFAULT_ON",
            "ENABLE_GPU_BATCH_INFERENCE",
            "SIGNAL_OUTPUT_STREAM",
            "SIGNAL_HEARTBEAT_STREAM",
        ],
        "legacy_stream_contracts_readonly_reference": [
            "signals:trading",
            "signals:trainer:heartbeat",
            "wma:proposals",
            "prediction:{symbol}:{timeframe}",
            "status:trainer",
            "heartbeat:trainer",
        ],
        "legacy_gpu_behavior": [
            "CUDA allocator defaults",
            "RTX5080FeatureExtractor",
            "GPUForcedPPO",
            "mixed precision GradScaler",
            "torch compile optional path",
            "GPU utilization/VRAM observer",
        ],
        "legacy_checkpoint_behavior": [
            "PPO checkpoint load",
            "state_dict fallback",
            "MASA checkpoint load",
            "safe mode until checkpoint load succeeds",
            "checkpoint compatibility guards",
        ],
    }


def detect_trainer_process(process_lines: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    if process_lines is None:
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,ppid,etimes,pcpu,pmem,cmd"],
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
            lines = result.stdout.splitlines()
        except Exception:
            lines = []
    else:
        lines = list(process_lines)
    matches = [
        line.strip()
        for line in lines
        if ("rl.hybrid_trainer" in line or "hybrid_trainer.py" in line)
        and "grep" not in line
        and "v2_trainer_bridge" not in line
    ]
    return {
        "trainer_process_state": "RUNNING_READONLY_OBSERVED" if matches else "NOT_OBSERVED",
        "trainer_process_count": len(matches),
        "trainer_process_sample": matches[:3],
    }


def detect_gpu_state() -> Dict[str, Any]:
    query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except Exception as exc:
        return {"gpu_state": "GPU_EVIDENCE_MISSING", "gpu_error": str(exc)[:160]}
    if result.returncode != 0 or not result.stdout.strip():
        return {"gpu_state": "GPU_EVIDENCE_MISSING", "gpu_error": (result.stderr or "")[:160]}
    rows = []
    for raw in result.stdout.splitlines():
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) >= 5:
            rows.append(
                {
                    "name": parts[0],
                    "gpu_util_pct": _to_float(parts[1]),
                    "memory_used_mb": _to_float(parts[2]),
                    "memory_total_mb": _to_float(parts[3]),
                    "temperature_c": _to_float(parts[4]),
                }
            )
    return {"gpu_state": "GPU_EVIDENCE_PRESENT" if rows else "GPU_EVIDENCE_MISSING", "gpus": rows}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _prediction_generated_at(payload: Mapping[str, Any]) -> Any:
    return payload.get("generated_at") or payload.get("last_prediction_ts") or payload.get("timestamp")


def _prediction_missing_fields(payload: Mapping[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in REQUIRED_PREDICTION_FIELDS:
        if payload.get(field) in (None, ""):
            # Accept legacy aliases for confidence fields.
            if field == "confidence_raw" and payload.get("confidence") not in (None, ""):
                continue
            if field == "confidence_calibrated" and payload.get("calibrated_confidence") not in (None, ""):
                continue
            if field == "model_checkpoint" and payload.get("model_checkpoint_id") not in (None, ""):
                continue
            missing.append(field)
    return missing


def evaluate_prediction_payload(payload: Mapping[str, Any], source_path: str) -> Dict[str, Any]:
    source_type = str(payload.get("source_type") or payload.get("trainer_state") or "").upper()
    checkpoint = str(payload.get("model_checkpoint") or payload.get("model_checkpoint_id") or "")
    missing = _prediction_missing_fields(payload)
    generated_at = _prediction_generated_at(payload)
    prediction_age_seconds = age_seconds(generated_at)
    wrapper_markers = ("WRAPPER", "MOMENTUM", "PAPER_TRAINER")
    is_wrapper = any(marker in source_type for marker in wrapper_markers) or any(
        marker.lower() in checkpoint.lower() for marker in wrapper_markers
    )
    accepted_source_type = any(
        source_type.startswith(prefix) for prefix in ACCEPTED_PREDICTION_SOURCE_PREFIXES
    )
    if is_wrapper:
        accepted = False
        status = WRAPPER_NOT_LEGACY_HYBRID_PARITY
    elif missing:
        accepted = False
        status = "PREDICTION_EVIDENCE_INCOMPLETE"
    elif not accepted_source_type:
        accepted = False
        status = "PREDICTION_SOURCE_NOT_LEGACY_HYBRID_OR_V2_NATIVE"
    elif prediction_age_seconds is None:
        accepted = False
        status = "PREDICTION_TIMESTAMP_MISSING"
    elif prediction_age_seconds > MAX_PREDICTION_AGE_SECONDS:
        accepted = False
        status = "PREDICTION_EVIDENCE_STALE"
    else:
        accepted = True
        status = LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT
    raw_conf = payload.get("confidence_raw", payload.get("confidence"))
    calibrated_conf = payload.get("confidence_calibrated", payload.get("calibrated_confidence"))
    top_features = payload.get("top_features") if isinstance(payload.get("top_features"), list) else []
    top_positive = [
        item for item in top_features if isinstance(item, dict) and _to_float(item.get("value")) is not None and float(item.get("value")) >= 0
    ][:5]
    top_negative = [
        item for item in top_features if isinstance(item, dict) and _to_float(item.get("value")) is not None and float(item.get("value")) < 0
    ][:5]
    return {
        "accepted_as_legacy_hybrid_prediction": accepted,
        "prediction_evidence_status": status,
        "prediction_source_path": source_path,
        "prediction_source_type": payload.get("source_type") or payload.get("trainer_state") or "",
        "prediction_id": payload.get("prediction_id") or "",
        "feature_snapshot_id": payload.get("feature_snapshot_id") or "",
        "model_checkpoint_id": checkpoint,
        "latest_prediction_timestamp": generated_at or "",
        "prediction_age_seconds": prediction_age_seconds,
        "raw_confidence": raw_conf,
        "calibrated_confidence": calibrated_conf,
        "top_positive_features": top_positive,
        "top_negative_features": top_negative,
        "raw_prediction_payload": dict(payload),
        "missing_prediction_fields": missing,
    }


def find_current_prediction(candidate_paths: Iterable[Path], *, repo_root: Path) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    for path in candidate_paths:
        data = load_json(path)
        if not isinstance(data, Mapping):
            continue
        try:
            source_path = str(path.relative_to(repo_root))
        except ValueError:
            source_path = str(path)
        evaluated = evaluate_prediction_payload(data, source_path)
        evidence.append(evaluated)
        if evaluated["accepted_as_legacy_hybrid_prediction"]:
            return evaluated | {"prediction_candidates_seen": evidence}
    if evidence:
        best = evidence[0]
        return best | {"prediction_candidates_seen": evidence}
    return {
        "accepted_as_legacy_hybrid_prediction": False,
        "prediction_evidence_status": MISSING_RUNTIME_EVIDENCE,
        "prediction_source_path": "",
        "prediction_source_type": "",
        "prediction_id": "",
        "feature_snapshot_id": "",
        "model_checkpoint_id": "",
        "latest_prediction_timestamp": "",
        "prediction_age_seconds": None,
        "raw_confidence": None,
        "calibrated_confidence": None,
        "top_positive_features": [],
        "top_negative_features": [],
        "raw_prediction_payload": {},
        "missing_prediction_fields": list(REQUIRED_PREDICTION_FIELDS),
        "prediction_candidates_seen": [],
    }


def evaluate_feature_snapshot(path: Path, *, repo_root: Path) -> Dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, Mapping):
        return {
            "feature_snapshot_status": MISSING_RUNTIME_EVIDENCE,
            "feature_snapshot_id": "",
            "feature_snapshot_path": "",
            "missing_feature_flags": ["feature_snapshot_payload_missing"],
            "stale_feature_flags": [],
            "trainer_readiness_signal": "MISSING",
        }
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), Mapping) else {}
    try:
        rel = str(path.relative_to(repo_root))
    except ValueError:
        rel = str(path)
    return {
        "feature_snapshot_status": "PRESENT",
        "feature_snapshot_id": data.get("last_snapshot_id") or snapshot.get("feature_snapshot_id") or "",
        "feature_snapshot_path": rel,
        "feature_snapshot_generated_ts": data.get("last_snapshot_ts") or snapshot.get("generated_ts") or "",
        "feature_snapshot_age_seconds": age_seconds(data.get("last_snapshot_ts") or snapshot.get("generated_ts")),
        "missing_feature_flags": list(data.get("missing_features") or snapshot.get("missing_features") or []),
        "stale_feature_flags": list(data.get("stale_features") or snapshot.get("stale_features") or []),
        "trainer_readiness_signal": data.get("trainer_readiness") or snapshot.get("confidence_input_ready") or "UNKNOWN",
        "feature_categories_present": list(data.get("feature_categories_present") or []),
    }
