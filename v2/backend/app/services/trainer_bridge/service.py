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
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo


LIVE_GATE_STATUS = "blocked_human_only"
MISSING_RUNTIME_EVIDENCE = "MISSING_RUNTIME_EVIDENCE"
WRAPPER_NOT_LEGACY_HYBRID_PARITY = "WRAPPER_NOT_LEGACY_HYBRID_PARITY"
LEGACY_HYBRID_TRAINER_PRESENT = "LEGACY_HYBRID_TRAINER_PRESENT"
LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT = "LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT"
LEGACY_HYBRID_TRAINER_LOG_EVIDENCE_PRESENT = "LEGACY_HYBRID_TRAINER_LOG_EVIDENCE_PRESENT"
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
LEGACY_LOCAL_TZ = ZoneInfo("America/New_York")
LEGACY_LOG_TS_RE = r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
LEGACY_PPO_DECISION_RE = re.compile(
    LEGACY_LOG_TS_RE
    + r".*?PPO_DECISION_RAW\s+\|\s+account=(?P<account>[^|]+)\s+\|\s+"
    + r"symbol=(?P<symbol>[A-Za-z0-9]+)\s+\|\s+tf=(?P<timeframe>[^|]+)\s+\|\s+"
    + r"action_id=(?P<action_id>[^|]+)\s+\|\s+action=(?P<action>[^|]+)\s+\|\s+"
    + r"ppo_conf=(?P<ppo_conf>[-+]?\d+(?:\.\d+)?)\s+\|\s+"
    + r"top1=(?P<top1>[-+]?\d+(?:\.\d+)?)\s+\|\s+top2=(?P<top2>[-+]?\d+(?:\.\d+)?)\s+\|\s+"
    + r"top1_id=(?P<top1_id>[^|]+)\s+\|\s+top2_id=(?P<top2_id>[^|]+)"
)
ACTION_NAME_BY_ID = {
    "0": "HOLD",
    "1": "OPEN_LONG",
    "2": "OPEN_SHORT",
    "3": "CLOSE_LONG",
    "4": "CLOSE_SHORT",
    "5": "REDUCE_LONG",
    "6": "REDUCE_SHORT",
}
LEGACY_LOG_TAIL_BYTES = 2 * 1024 * 1024
LEGACY_REDIS_READONLY_COMMANDS = {"TYPE", "HGETALL"}
LEGACY_REDIS_PREDICTION_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
NATIVE_FIELD_PRESENT = "NATIVE_FIELD_PRESENT"
DERIVED_FROM_LEGACY_LOG = "DERIVED_FROM_LEGACY_LOG"
MISSING_EVIDENCE = "MISSING_EVIDENCE"
INCOMPLETE_ATTRIBUTION = "INCOMPLETE_ATTRIBUTION"
ACCEPTED_FOR_PAPER_ONLY = "ACCEPTED_FOR_PAPER_ONLY"
BLOCKS_LEGACY_SHUTDOWN = "BLOCKS_LEGACY_SHUTDOWN"
DERIVED_FEATURE_SNAPSHOT_LINK = "derived_feature_snapshot_link"
NATIVE_LEGACY_TRAINER_PRICE_TARGET = "native_legacy_trainer_price_target"


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


def parse_legacy_log_ts(value: str) -> Optional[dt.datetime]:
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return None
    return parsed.replace(tzinfo=LEGACY_LOCAL_TZ).astimezone(dt.timezone.utc)


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


def latest_legacy_ppo_decision_line(log_path: Path) -> Optional[str]:
    try:
        size = log_path.stat().st_size
        with log_path.open("rb") as handle:
            handle.seek(max(0, size - LEGACY_LOG_TAIL_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    for line in reversed(lines):
        if "PPO_DECISION_RAW" in line and LEGACY_PPO_DECISION_RE.search(line):
            return line
    return None


def latest_checkpoint_id(metadata_path: Path) -> str:
    data = load_json(metadata_path)
    if not isinstance(data, Mapping):
        return ""
    timestamp = data.get("timestamp")
    ppo_path = str(data.get("ppo_path") or "")
    if timestamp not in (None, ""):
        return f"legacy_live_checkpoint_{timestamp}"
    if ppo_path:
        return Path(ppo_path).stem
    return ""


def _redis_base_command() -> List[str]:
    redis_url = os.environ.get("LEGACY_REDIS_URL") or os.environ.get("REDIS_URL")
    if redis_url:
        return ["redis-cli", "-u", redis_url, "--raw"]
    return ["redis-cli", "--raw"]


def _run_legacy_redis_readonly(command: str, *args: str) -> subprocess.CompletedProcess[str]:
    upper = command.upper()
    if upper not in LEGACY_REDIS_READONLY_COMMANDS:
        raise ValueError(f"legacy Redis command is not read-only for trainer bridge: {command}")
    return subprocess.run(
        [*_redis_base_command(), command, *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )


def _decode_hgetall_raw(stdout: str) -> Dict[str, str]:
    lines = [line for line in stdout.splitlines() if line != ""]
    return {lines[index]: lines[index + 1] for index in range(0, len(lines) - 1, 2)}


def _epoch_to_utc_iso(value: Any) -> str:
    number = _to_float(value)
    if number is None or number <= 0:
        return ""
    if number > 1e12:
        number = number / 1000.0
    return dt.datetime.fromtimestamp(number, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expected_move_bps_from_target(data: Mapping[str, Any]) -> Optional[float]:
    pct = _to_float(data.get("price_target_pct"))
    if pct is not None and pct > 0:
        return round(abs(pct) * 10000.0, 8)
    target = _to_float(data.get("price_target"))
    entry = _to_float(data.get("entry_price") or data.get("current_price") or data.get("price"))
    if target is None or entry is None or target <= 0 or entry <= 0:
        return None
    return round(abs(target - entry) / entry * 10000.0, 8)


def legacy_redis_prediction_payload_from_hash(
    *,
    key: str,
    data: Mapping[str, Any],
    checkpoint_metadata_path: Path,
) -> Optional[Dict[str, Any]]:
    """Map a read-only legacy prediction hash into bridge evidence.

    The legacy trainer writes ``price_target`` / ``price_target_pct`` into
    ``prediction:{symbol}:{tf}`` hashes. Those are native trainer outputs,
    but they do not clear separate feature-snapshot, calibration, or
    attribution blockers.
    """
    symbol = str(data.get("symbol") or "").strip().upper()
    timeframe = str(data.get("timeframe") or "").strip()
    if not symbol or not timeframe:
        parts = key.split(":")
        if len(parts) >= 3:
            symbol = symbol or parts[1].strip().upper()
            timeframe = timeframe or parts[2].strip()
    generated_at = _epoch_to_utc_iso(data.get("timestamp") or data.get("ts_ms"))
    if not symbol or not timeframe or not generated_at:
        return None
    confidence_raw = _to_float(
        data.get("model_confidence")
        or data.get("confidence")
        or data.get("ppo_confidence")
    )
    if confidence_raw is None:
        return None
    expected_move_bps = _expected_move_bps_from_target(data)
    digest = hashlib.sha256(
        json.dumps(dict(data), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    checkpoint_id = latest_checkpoint_id(checkpoint_metadata_path)
    raw_model_output = {
        "key": key,
        "action": str(data.get("action") or data.get("action_name") or "").upper(),
        "direction": str(data.get("direction") or "").upper(),
        "confidence": data.get("confidence"),
        "model_confidence": data.get("model_confidence"),
        "ppo_confidence": data.get("ppo_confidence"),
        "masa_confidence": data.get("masa_confidence"),
        "price_target": data.get("price_target"),
        "price_target_pct": data.get("price_target_pct"),
        "entry_price": data.get("entry_price"),
        "predicted_return": data.get("predicted_return"),
        "published": data.get("published"),
        "threshold_passed": data.get("threshold_passed"),
        "why": data.get("why"),
        "evidence_hash_sha256": digest,
    }
    warnings = [
        "feature_snapshot_id_bridge_derived_from_legacy_redis_prediction_hash",
        "confidence_calibrated_bridge_derived_from_legacy_prediction_confidence",
        "top_features_absent_from_legacy_prediction_hash",
        "top_negative_features_absent_from_legacy_prediction_hash",
    ]
    if expected_move_bps is None:
        warnings.append("expected_move_bps_absent_from_legacy_prediction_hash")
    return {
        "source_type": "LEGACY_HYBRID_TRAINER_REDIS_READONLY",
        "generated_at": generated_at,
        "prediction_id": f"legacy_redis_pred_{digest[:20]}",
        "feature_snapshot_id": f"legacy_redis_feature_{symbol}_{timeframe}_{int(parse_ts(generated_at).timestamp())}",
        "model_version": "legacy_hybrid_trainer_live_legacy",
        "model_checkpoint": checkpoint_id,
        "checkpoint_id": checkpoint_id,
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_raw,
        "symbol": symbol,
        "timeframe": timeframe,
        "top_features": [],
        "feature_snapshot_link_mode": DERIVED_FROM_LEGACY_LOG,
        "feature_snapshot_id_classification": DERIVED_FROM_LEGACY_LOG,
        "confidence_calibration_mode": DERIVED_FROM_LEGACY_LOG,
        "feature_attribution_status": INCOMPLETE_ATTRIBUTION,
        "expected_move_bps": expected_move_bps,
        "native_expected_move_bps": expected_move_bps,
        "expected_move_source": NATIVE_LEGACY_TRAINER_PRICE_TARGET if expected_move_bps is not None else "missing",
        "expected_move_evidence_mode": NATIVE_FIELD_PRESENT if expected_move_bps is not None else MISSING_EVIDENCE,
        "field_classification": {
            "feature_snapshot_id": DERIVED_FROM_LEGACY_LOG,
            "confidence_calibration": DERIVED_FROM_LEGACY_LOG,
            "feature_attribution": INCOMPLETE_ATTRIBUTION,
        },
        "raw_model_output": raw_model_output,
        "lineage_derivation_warnings": warnings,
        "trainer_full_parity_blockers": [
            "LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED",
            "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED",
            "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE",
        ],
    }


def legacy_redis_prediction_payload(
    *,
    symbols: Iterable[str],
    checkpoint_metadata_path: Path,
    timeframes: Iterable[str] | None = None,
) -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for symbol in symbols:
        symbol_text = str(symbol or "").strip().upper()
        if not symbol_text:
            continue
        for timeframe in (timeframes or LEGACY_REDIS_PREDICTION_TIMEFRAMES):
            timeframe_text = str(timeframe or "").strip()
            if not timeframe_text:
                continue
            key = f"prediction:{symbol_text}:{timeframe_text}"
            try:
                type_result = _run_legacy_redis_readonly("TYPE", key)
                if type_result.returncode != 0 or type_result.stdout.strip() != "hash":
                    continue
                hash_result = _run_legacy_redis_readonly("HGETALL", key)
                if hash_result.returncode != 0 or not hash_result.stdout.strip():
                    continue
            except Exception:
                continue
            payload = legacy_redis_prediction_payload_from_hash(
                key=key,
                data=_decode_hgetall_raw(hash_result.stdout),
                checkpoint_metadata_path=checkpoint_metadata_path,
            )
            if isinstance(payload, dict):
                candidates.append(payload)
    if not candidates:
        return None
    def _candidate_rank(item: Mapping[str, Any]) -> tuple[int, float, dt.datetime]:
        generated = parse_ts(item.get("generated_at")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        return (
            1 if _to_float(item.get("expected_move_bps")) is not None else 0,
            _to_float(item.get("confidence_raw")) or 0.0,
            generated,
        )

    return max(candidates, key=_candidate_rank)


def legacy_log_prediction_payload(
    *,
    log_path: Path,
    checkpoint_metadata_path: Path,
) -> Optional[Dict[str, Any]]:
    line = latest_legacy_ppo_decision_line(log_path)
    if not line:
        return None
    match = LEGACY_PPO_DECISION_RE.search(line)
    if not match:
        return None
    ts = parse_legacy_log_ts(match.group("ts"))
    if ts is None:
        return None
    symbol = match.group("symbol").strip().upper()
    timeframe = match.group("timeframe").strip()
    action = match.group("action").strip()
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    checkpoint_id = latest_checkpoint_id(checkpoint_metadata_path)
    confidence_raw = float(match.group("ppo_conf"))
    top1_id = match.group("top1_id").strip()
    top2_id = match.group("top2_id").strip()
    action_probability_evidence = [
        {
            "name": f"ppo_action_{ACTION_NAME_BY_ID.get(top1_id, top1_id)}_probability",
            "value": float(match.group("top1")),
            "source": "legacy_log:PPO_DECISION_RAW.top1",
        },
        {
            "name": f"ppo_action_{ACTION_NAME_BY_ID.get(top2_id, top2_id)}_probability",
            "value": float(match.group("top2")),
            "source": "legacy_log:PPO_DECISION_RAW.top2",
        },
    ]
    generated_at = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source_type": "LEGACY_HYBRID_TRAINER_LOG_READONLY",
        "generated_at": generated_at,
        "prediction_id": f"legacy_log_pred_{digest[:20]}",
        "feature_snapshot_id": f"legacy_log_feature_{symbol}_{timeframe}_{int(ts.timestamp())}",
        "model_version": "legacy_hybrid_trainer_live_legacy",
        "model_checkpoint": checkpoint_id,
        "checkpoint_id": checkpoint_id,
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_raw,
        "symbol": symbol,
        "timeframe": timeframe,
        "top_features": [],
        "action_probability_evidence": action_probability_evidence,
        "feature_snapshot_link_mode": DERIVED_FROM_LEGACY_LOG,
        "feature_snapshot_id_classification": DERIVED_FROM_LEGACY_LOG,
        "confidence_calibration_mode": DERIVED_FROM_LEGACY_LOG,
        "feature_attribution_status": INCOMPLETE_ATTRIBUTION,
        "field_classification": {
            "feature_snapshot_id": DERIVED_FROM_LEGACY_LOG,
            "confidence_calibration": DERIVED_FROM_LEGACY_LOG,
            "feature_attribution": INCOMPLETE_ATTRIBUTION,
        },
        "raw_model_output": {
            "account": match.group("account").strip(),
            "action": action,
            "action_id": match.group("action_id").strip(),
            "top1": match.group("top1"),
            "top2": match.group("top2"),
            "top1_id": top1_id,
            "top2_id": top2_id,
            "action_probability_evidence": action_probability_evidence,
            "evidence_line_sha256": digest,
        },
        "lineage_derivation_warnings": [
            "feature_snapshot_id_bridge_derived_from_legacy_log_line",
            "confidence_calibrated_bridge_derived_from_ppo_conf",
            "top_features_are_action_probability_evidence_not_full_feature_attribution",
            "top_negative_features_absent_from_legacy_log_line",
        ],
        "trainer_full_parity_blockers": [
            "LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED",
            "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED",
            "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE",
        ],
    }


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


def _has_feature_attribution(payload: Mapping[str, Any]) -> bool:
    top_features = payload.get("top_features")
    if not isinstance(top_features, list) or not top_features:
        return False
    for item in top_features:
        if not isinstance(item, Mapping):
            return False
        if not item.get("name"):
            return False
        if _to_float(item.get("value")) is None:
            return False
    return True


def _field_classification(payload: Mapping[str, Any], *, is_legacy_log_evidence: bool) -> Dict[str, str]:
    explicit = payload.get("field_classification")
    if isinstance(explicit, Mapping):
        return {
            "feature_snapshot_id": str(explicit.get("feature_snapshot_id") or MISSING_EVIDENCE),
            "confidence_calibration": str(explicit.get("confidence_calibration") or MISSING_EVIDENCE),
            "feature_attribution": str(explicit.get("feature_attribution") or MISSING_EVIDENCE),
        }
    return {
        "feature_snapshot_id": DERIVED_FROM_LEGACY_LOG if is_legacy_log_evidence else NATIVE_FIELD_PRESENT,
        "confidence_calibration": DERIVED_FROM_LEGACY_LOG if is_legacy_log_evidence else NATIVE_FIELD_PRESENT,
        "feature_attribution": INCOMPLETE_ATTRIBUTION
        if is_legacy_log_evidence or not _has_feature_attribution(payload)
        else NATIVE_FIELD_PRESENT,
    }


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
    parity_blockers = list(payload.get("trainer_full_parity_blockers") or [])
    is_legacy_log_evidence = source_type == "LEGACY_HYBRID_TRAINER_LOG_READONLY"
    field_classification = _field_classification(payload, is_legacy_log_evidence=is_legacy_log_evidence)
    if (
        field_classification["feature_attribution"] == INCOMPLETE_ATTRIBUTION
        and "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE" not in parity_blockers
        and is_legacy_log_evidence
    ):
        parity_blockers.append("LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE")
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
    elif is_legacy_log_evidence:
        accepted = True
        status = LEGACY_HYBRID_TRAINER_LOG_EVIDENCE_PRESENT
    else:
        accepted = True
        status = LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT
    raw_conf = payload.get("confidence_raw", payload.get("confidence"))
    calibrated_conf = payload.get("confidence_calibrated", payload.get("calibrated_confidence"))
    raw_model_output = payload.get("raw_model_output") if isinstance(payload.get("raw_model_output"), Mapping) else {}
    expected_move_bps = _to_float(
        payload.get("expected_move_bps")
        or payload.get("native_expected_move_bps")
        or raw_model_output.get("expected_move_bps")
        or raw_model_output.get("native_expected_move_bps")
    )
    expected_move_after_cost_bps = _to_float(
        payload.get("expected_move_after_cost_bps")
        or raw_model_output.get("expected_move_after_cost_bps")
    )
    top_features = payload.get("top_features") if isinstance(payload.get("top_features"), list) else []
    feature_attribution_is_native = field_classification["feature_attribution"] == NATIVE_FIELD_PRESENT
    top_positive = (
        [
            item
            for item in top_features
            if isinstance(item, dict) and _to_float(item.get("value")) is not None and float(item.get("value")) >= 0
        ][:5]
        if feature_attribution_is_native
        else []
    )
    top_negative = (
        [
            item
            for item in top_features
            if isinstance(item, dict) and _to_float(item.get("value")) is not None and float(item.get("value")) < 0
        ][:5]
        if feature_attribution_is_native
        else []
    )
    return {
        "accepted_as_legacy_hybrid_prediction": accepted,
        "prediction_evidence_status": status,
        "prediction_source_path": source_path,
        "prediction_source_type": payload.get("source_type") or payload.get("trainer_state") or "",
        "prediction_id": payload.get("prediction_id") or "",
        "prediction_symbol": str(payload.get("symbol") or "").strip().upper(),
        "prediction_timeframe": str(payload.get("timeframe") or "").strip(),
        "feature_snapshot_id": payload.get("feature_snapshot_id") or "",
        "model_checkpoint_id": checkpoint,
        "model_version": payload.get("model_version") or "",
        "checkpoint_id": payload.get("checkpoint_id") or checkpoint,
        "latest_prediction_timestamp": generated_at or "",
        "prediction_age_seconds": prediction_age_seconds,
        "raw_confidence": raw_conf,
        "calibrated_confidence": calibrated_conf,
        "expected_move_bps": expected_move_bps,
        "native_expected_move_bps": expected_move_bps,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "expected_move_source": payload.get("expected_move_source") or "",
        "expected_move_evidence_mode": payload.get("expected_move_evidence_mode") or "",
        "top_positive_features": top_positive,
        "top_negative_features": top_negative,
        "action_probability_evidence": list(payload.get("action_probability_evidence") or []),
        "feature_snapshot_link_mode": payload.get("feature_snapshot_link_mode")
        or field_classification["feature_snapshot_id"],
        "feature_snapshot_id_classification": field_classification["feature_snapshot_id"],
        "confidence_calibration_mode": payload.get("confidence_calibration_mode")
        or field_classification["confidence_calibration"],
        "feature_attribution_status": payload.get("feature_attribution_status")
        or field_classification["feature_attribution"],
        "field_classification": field_classification,
        "raw_prediction_payload": dict(payload),
        "missing_prediction_fields": missing,
        "lineage_derivation_warnings": list(payload.get("lineage_derivation_warnings") or []),
        "trainer_full_parity_blockers": sorted(set(map(str, parity_blockers))),
    }


def find_current_prediction(
    candidate_paths: Iterable[Path],
    *,
    repo_root: Path,
    extra_payloads: Optional[Iterable[tuple[str, Mapping[str, Any]]]] = None,
) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    for source_path, payload in extra_payloads or ():
        evaluated = evaluate_prediction_payload(payload, source_path)
        evidence.append(evaluated)
        if evaluated["accepted_as_legacy_hybrid_prediction"]:
            return evaluated | {"prediction_candidates_seen": evidence}
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
        "prediction_symbol": "",
        "prediction_timeframe": "",
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


def _legacy_symbol_from_canonical(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("BINANCE-USDM-") and text.endswith("-PERP"):
        inner = text.removeprefix("BINANCE-USDM-").removesuffix("-PERP")
        parts = [part for part in inner.split("-") if part]
        if len(parts) >= 2:
            return "".join(parts)
    return text


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
    feature_ts = data.get("last_snapshot_ts") or snapshot.get("generated_ts") or ""
    try:
        rel = str(path.relative_to(repo_root))
    except ValueError:
        rel = str(path)
    legacy_symbol = (
        str(snapshot.get("legacy_symbol") or "").strip().upper()
        or _legacy_symbol_from_canonical(snapshot.get("canonical_symbol_id"))
    )
    return {
        "feature_snapshot_status": "PRESENT",
        "feature_snapshot_id": data.get("last_snapshot_id") or snapshot.get("feature_snapshot_id") or "",
        "feature_snapshot_path": rel,
        "feature_snapshot_generated_ts": feature_ts,
        "feature_snapshot_age_seconds": age_seconds(feature_ts),
        "feature_snapshot_symbol": legacy_symbol,
        "feature_snapshot_timeframe": str(snapshot.get("timeframe") or data.get("timeframe") or "").strip(),
        "missing_feature_flags": list(data.get("missing_features") or snapshot.get("missing_features") or []),
        "stale_feature_flags": list(data.get("stale_features") or snapshot.get("stale_features") or []),
        "unused_feature_flags": list(data.get("unused_features") or snapshot.get("unused_features") or []),
        "trainer_readiness_signal": data.get("trainer_readiness") or snapshot.get("confidence_input_ready") or "UNKNOWN",
        "feature_categories_present": list(data.get("feature_categories_present") or []),
    }


def derived_feature_snapshot_link(
    prediction: Mapping[str, Any],
    feature: Mapping[str, Any],
    *,
    max_age_seconds: int = MAX_PREDICTION_AGE_SECONDS,
) -> Dict[str, Any]:
    raw = prediction.get("raw_prediction_payload") if isinstance(prediction.get("raw_prediction_payload"), Mapping) else {}
    prediction_symbol = str(raw.get("symbol") or "").strip().upper()
    prediction_timeframe = str(raw.get("timeframe") or "").strip()
    feature_symbol = str(feature.get("feature_snapshot_symbol") or "").strip().upper()
    feature_timeframe = str(feature.get("feature_snapshot_timeframe") or "").strip()
    prediction_ts = parse_ts(prediction.get("latest_prediction_timestamp"))
    feature_ts = parse_ts(feature.get("feature_snapshot_generated_ts"))
    age_delta_seconds: Optional[int] = None
    if prediction_ts and feature_ts:
        age_delta_seconds = abs(int((prediction_ts - feature_ts).total_seconds()))
    symbol_scope_matches = bool(prediction_symbol and feature_symbol and prediction_symbol == feature_symbol)
    timeframe_matches = bool(prediction_timeframe and feature_timeframe and prediction_timeframe == feature_timeframe)
    freshness_matches = age_delta_seconds is not None and age_delta_seconds <= max_age_seconds
    linked = (
        bool(feature.get("feature_snapshot_id"))
        and symbol_scope_matches
        and timeframe_matches
        and freshness_matches
    )
    return {
        "mode": DERIVED_FEATURE_SNAPSHOT_LINK if linked else DERIVED_FROM_LEGACY_LOG,
        "linked": linked,
        "linked_feature_snapshot_id": feature.get("feature_snapshot_id") if linked else "",
        "source_prediction_id": prediction.get("prediction_id") or "",
        "prediction_symbol": prediction_symbol,
        "feature_snapshot_symbol": feature_symbol,
        "prediction_timeframe": prediction_timeframe,
        "feature_snapshot_timeframe": feature_timeframe,
        "age_delta_seconds": age_delta_seconds,
        "symbol_scope_matches": symbol_scope_matches,
        "timeframe_matches": timeframe_matches,
        "freshness_matches": freshness_matches,
        "classification": DERIVED_FROM_LEGACY_LOG,
    }
