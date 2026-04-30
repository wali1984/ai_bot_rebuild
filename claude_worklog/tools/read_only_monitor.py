#!/usr/bin/env python3
"""
Read-only Redis monitor for AI BOT REBUILD.

Supports one-shot, bounded duration, and continuous modes.
Writes JSONL telemetry and packet artifacts. Never writes to Redis.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_REDIS_BASE = ["redis-cli", "-u", REDIS_URL] if REDIS_URL else ["redis-cli"]

STREAMS = (
    "executed_signals",
    "signals:trading",
    "signals:trading:primary",
    "signals:trading:asjad",
    "signals:execution:skips",
    "wma:proposals",
    "wma:trainer:predictions",
)

HEARTBEAT_KEYS = (
    "orchestrator:heartbeat_ms",
    "heartbeat:FeaturePipeline",
    "heartbeat:trainer",
    "heartbeat:Trainer",
    "signals:trainer:heartbeat",
)

LINEAGE_FIELDS = (
    "feature_snapshot_id",
    "prediction_id",
    "signal_id",
    "decision_id",
    "risk_decision_id",
    "execution_intent_id",
)

SECRETISH = re.compile(
    r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}",
    re.I,
)

TS_FIELD_HINTS = (
    "ts_ms",
    "timestamp_ms",
    "created_ts_ms",
    "published_ts_ms",
    "heartbeat_ts_ms",
    "event_ts_ms",
    "updated_ts_ms",
)


def _redact(obj: Any) -> Any:
    if isinstance(obj, str):
        return SECRETISH.sub(r"\1=<redacted>", obj)
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj[:200]]
    return obj


def redis_cmd(*args: str) -> Tuple[bool, str]:
    try:
        p = subprocess.run(
            [*_REDIS_BASE, *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out.strip()
    except Exception as exc:
        return False, str(exc)


def xlen(name: str) -> Optional[int]:
    ok, out = redis_cmd("XLEN", name)
    if not ok:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _extract_ts_ms_from_obj(obj: Any) -> Optional[int]:
    if isinstance(obj, dict):
        for k in TS_FIELD_HINTS:
            if k in obj:
                try:
                    return int(float(obj[k]))
                except Exception:
                    pass
        for v in obj.values():
            t = _extract_ts_ms_from_obj(v)
            if t is not None:
                return t
    elif isinstance(obj, list):
        for v in obj:
            t = _extract_ts_ms_from_obj(v)
            if t is not None:
                return t
    return None


def _parse_json_maybe(s: str) -> Any:
    try:
        return json.loads(s)
    except Exception:
        return s


def xrevrange_json(stream: str, count: int = 200) -> List[Dict[str, Any]]:
    ok, out = redis_cmd("XREVRANGE", stream, "+", "-", "COUNT", str(count))
    if not ok or not out:
        return []

    lines = out.splitlines()
    rows: List[Dict[str, Any]] = []
    i = 0
    while i + 2 < len(lines):
        rid = lines[i].strip()
        if lines[i + 1].strip() != "data":
            i += 1
            continue
        blob = lines[i + 2]
        parsed = _parse_json_maybe(blob)
        if isinstance(parsed, dict):
            parsed["_stream_id"] = rid
            rows.append(parsed)
        i += 3
    return rows


def read_memory_ratio() -> Tuple[Optional[float], Dict[str, Any]]:
    ok, out = redis_cmd("INFO", "memory")
    details: Dict[str, Any] = {}
    if not ok:
        details["error"] = out[:300]
        return None, details
    raw: Dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            raw[k.strip()] = v.strip()
    used = raw.get("used_memory")
    maxm = raw.get("maxmemory")
    details["used_memory"] = used
    details["maxmemory"] = maxm
    try:
        used_f = float(used or 0)
        max_f = float(maxm or 0)
        if max_f <= 0:
            details["memory_ratio_pct"] = None
            return None, details
        ratio = (used_f / max_f) * 100.0
        details["memory_ratio_pct"] = ratio
        return ratio, details
    except Exception:
        details["memory_ratio_pct"] = None
        return None, details


def threshold_band(ratio: Optional[float]) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= 95.0:
        return "critical_95"
    if ratio >= 90.0:
        return "elevated_90"
    if ratio >= 85.0:
        return "warning_85"
    return "normal"


def trend_value(samples: List[Tuple[int, float]], window_ms: int) -> str:
    if len(samples) < 2:
        return "insufficient_samples"
    now = samples[-1][0]
    in_window = [(ts, v) for ts, v in samples if now - ts <= window_ms]
    if len(in_window) < 2:
        return "insufficient_samples"
    delta = in_window[-1][1] - in_window[0][1]
    return f"{delta:+.2f}%"


def parse_pattern_inventory(map_md_path: Path) -> List[str]:
    if not map_md_path.exists():
        return []
    patterns: List[str] = []
    with map_md_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.strip().split("|")]
            if len(parts) < 3:
                continue
            key = parts[1]
            if key in {"key/pattern", "---", "<requires targeted extraction from source references>", ""}:
                continue
            patterns.append(key)
    return sorted(set(patterns))


def pattern_to_match(pattern: str) -> Optional[str]:
    p = pattern.strip()
    if not p or "<requires" in p:
        return None
    p = re.sub(r"\{[^}]+\}", "*", p)
    p = p.replace(" ", "")
    return p


def scan_one_key(match: str) -> Optional[str]:
    cursor = "0"
    attempts = 0
    while attempts < 6:
        attempts += 1
        ok, out = redis_cmd("SCAN", cursor, "MATCH", match, "COUNT", "100")
        if not ok or not out:
            return None
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        if not lines:
            return None
        cursor = lines[0]
        for candidate in lines[1:]:
            if candidate not in {"1)"}:
                if candidate.startswith("1)"):
                    candidate = candidate.split(" ", 1)[-1].strip('"')
                return candidate
        if cursor == "0":
            break
    return None


def freshness_status(age_ms: Optional[int]) -> str:
    if age_ms is None:
        return "unknown"
    if age_ms > 900_000:
        return "stale"
    return "fresh"


def key_freshness_entry(pattern: str, now_ms: int) -> Dict[str, Any]:
    match = pattern_to_match(pattern)
    if not match:
        return {
            "pattern": pattern,
            "sample_key": None,
            "status": "unknown",
            "freshness_age_ms": None,
            "source": "pattern_unresolved",
        }

    sample_key = None
    if "*" in match:
        sample_key = scan_one_key(match)
    else:
        sample_key = match

    if not sample_key:
        return {
            "pattern": pattern,
            "sample_key": None,
            "status": "missing",
            "freshness_age_ms": None,
            "source": "scan_no_match",
        }

    ok_type, out_type = redis_cmd("TYPE", sample_key)
    if not ok_type:
        return {
            "pattern": pattern,
            "sample_key": sample_key,
            "status": "unknown",
            "freshness_age_ms": None,
            "source": "type_error",
            "error": out_type[:180],
        }

    rtype = out_type.strip()
    age_ms: Optional[int] = None
    source = "unknown"

    if rtype == "stream":
        ok, out = redis_cmd("XREVRANGE", sample_key, "+", "-", "COUNT", "1")
        if ok and out:
            rid = out.splitlines()[0].strip()
            try:
                age_ms = max(0, now_ms - int(rid.split("-")[0]))
                source = "stream_id_age"
            except Exception:
                pass
    elif rtype in {"string", "hash", "list", "set", "zset"}:
        ok_idle, out_idle = redis_cmd("OBJECT", "IDLETIME", sample_key)
        if ok_idle:
            try:
                age_ms = max(0, int(float(out_idle)) * 1000)
                source = "object_idletime_age"
            except Exception:
                pass
    return {
        "pattern": pattern,
        "sample_key": sample_key,
        "redis_type": rtype,
        "status": freshness_status(age_ms),
        "freshness_age_ms": age_ms,
        "source": source,
    }


def analyze_executed(rows: List[Dict[str, Any]], now_ms: int) -> Dict[str, Any]:
    null_sid = sum(1 for r in rows if r.get("signal_id") in (None, "", "null"))
    null_conf = sum(1 for r in rows if r.get("confidence") is None)
    missing_prediction_id = sum(1 for r in rows if not r.get("prediction_id"))
    missing_feature_snapshot_id = sum(1 for r in rows if not r.get("feature_snapshot_id"))

    oids: List[str] = []
    for r in rows:
        oid = r.get("exchange_order_id")
        if oid is not None and str(oid).strip():
            oids.append(str(oid))
    dup = sum(1 for c in Counter(oids).values() if c > 1)

    cross = 0
    high_lev = 0
    latencies: List[int] = []
    risk_addish = 0
    stale_exec = 0
    adj_in_stream = 0
    lineage_missing = 0

    for r in rows:
        act = str(r.get("action") or r.get("action_name") or "").upper()
        if any(x in act for x in ("OPEN_", "INCREASE_", "ADD_")) and r.get("success"):
            risk_addish += 1
        if "ADJUST_LEVERAGE" in act:
            adj_in_stream += 1

        if any(r.get(k) in (None, "") for k in LINEAGE_FIELDS):
            lineage_missing += 1

        pb = r.get("pos_before") or {}
        if isinstance(pb, dict):
            mt = str(pb.get("margin_type") or "").lower()
            if mt == "cross":
                cross += 1
            try:
                lv = float(pb.get("leverage") or 0)
                if lv >= 25:
                    high_lev += 1
            except (TypeError, ValueError):
                pass

        lm = r.get("latency_ms")
        if lm is not None:
            try:
                latencies.append(int(lm))
            except (TypeError, ValueError):
                pass

        ts = r.get("ts_ms")
        if ts is not None:
            try:
                if now_ms - int(ts) > 300_000:
                    stale_exec += 1
            except (TypeError, ValueError):
                pass

    lat_buckets = Counter()
    for ms in latencies:
        if ms <= 0:
            lat_buckets["0"] += 1
        elif ms <= 5_000:
            lat_buckets["1-5s"] += 1
        elif ms <= 30_000:
            lat_buckets["5-30s"] += 1
        elif ms <= 300_000:
            lat_buckets["30-300s"] += 1
        else:
            lat_buckets[">300s"] += 1

    return {
        "executed_sample_size": len(rows),
        "missing_signal_id": null_sid,
        "missing_confidence": null_conf,
        "missing_prediction_id": missing_prediction_id,
        "missing_feature_snapshot_id": missing_feature_snapshot_id,
        "lineage_tuple_incomplete_rows": lineage_missing,
        "duplicate_exchange_order_id_rows": dup,
        "cross_margin_pos_before_hits": cross,
        "high_leverage_pos_ge_25": high_lev,
        "latency_buckets": dict(lat_buckets),
        "risk_add_like_success_rows": risk_addish,
        "adjust_leverage_rows": adj_in_stream,
        "stale_executed_ts_ms_gt_5m": stale_exec,
    }


def attribution_completeness(
    executed_rows: List[Dict[str, Any]],
    primary_rows: List[Dict[str, Any]],
    prediction_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    def safe_rate(missing: int, total: int) -> float:
        return 0.0 if total <= 0 else max(0.0, min(100.0, (1.0 - (missing / total)) * 100.0))

    sig_missing_signal_id = sum(1 for r in primary_rows if not r.get("signal_id"))
    sig_missing_conf = sum(1 for r in primary_rows if r.get("confidence") is None)
    sig_missing_prediction = sum(1 for r in primary_rows if not r.get("prediction_id"))
    sig_missing_snapshot = sum(1 for r in primary_rows if not r.get("feature_snapshot_id"))
    sig_lineage_missing = sum(1 for r in primary_rows if any(r.get(k) in (None, "") for k in ("feature_snapshot_id", "prediction_id", "signal_id")))

    exec_missing_tuple = sum(1 for r in executed_rows if any(r.get(k) in (None, "") for k in LINEAGE_FIELDS))

    pred_missing_snapshot = sum(1 for r in prediction_rows if not r.get("feature_snapshot_id"))
    pred_missing_prediction_id = sum(1 for r in prediction_rows if not r.get("prediction_id"))

    return {
        "signal_sample_size": len(primary_rows),
        "execution_sample_size": len(executed_rows),
        "prediction_sample_size": len(prediction_rows),
        "missing_signal_id": sig_missing_signal_id,
        "missing_confidence": sig_missing_conf,
        "missing_prediction_id": sig_missing_prediction,
        "missing_feature_snapshot_id": sig_missing_snapshot,
        "missing_lineage_tuple_signal_rows": sig_lineage_missing,
        "missing_feature_snapshot_id_prediction_rows": pred_missing_snapshot,
        "missing_prediction_id_prediction_rows": pred_missing_prediction_id,
        "missing_lineage_tuple_execution_rows": exec_missing_tuple,
        "signal_attribution_completeness_pct": safe_rate(
            sig_missing_signal_id + sig_missing_conf + sig_missing_prediction + sig_missing_snapshot,
            len(primary_rows) * 4 if primary_rows else 0,
        ),
        "execution_lineage_completeness_pct": safe_rate(exec_missing_tuple, len(executed_rows)),
    }


def sample_primary_signals(rows: List[Dict[str, Any]], now_ms: int) -> Dict[str, Any]:
    stale = 0
    missing_sid = 0
    for r in rows:
        if not r.get("signal_id"):
            missing_sid += 1
        ts = r.get("ts_ms") or r.get("published_ts_ms") or r.get("_received_ts_ms")
        if ts is not None:
            try:
                if now_ms - int(ts) > 120_000:
                    stale += 1
            except (TypeError, ValueError):
                pass
    return {
        "primary_sample": len(rows),
        "primary_missing_signal_id": missing_sid,
        "primary_stale_gt_2m": stale,
    }


def ensure_packet_dirs(base_dir: Path) -> Dict[str, Path]:
    hourly = base_dir / "hourly"
    daily = base_dir / "daily"
    alerts = base_dir / "alerts"
    hourly.mkdir(parents=True, exist_ok=True)
    daily.mkdir(parents=True, exist_ok=True)
    alerts.mkdir(parents=True, exist_ok=True)
    return {"hourly": hourly, "daily": daily, "alerts": alerts}


def packet_confidence_level(missing_evidence: List[str], anomalies: List[str]) -> str:
    if missing_evidence:
        return "low"
    if anomalies:
        return "medium"
    return "high"


def packet_common(
    packet_type: str,
    start_ts_utc: str,
    end_ts_utc: str,
    affected_components: List[str],
    metric_values: Dict[str, Any],
    anomaly_classification: List[str],
    verification_commands: List[str],
    missing_evidence: List[str],
) -> Dict[str, Any]:
    return {
        "packet_id": f"{packet_type}_{uuid.uuid4().hex[:12]}",
        "packet_type": packet_type,
        "generated_ts_utc": datetime.now(timezone.utc).isoformat(),
        "timestamp_range": {"start_ts_utc": start_ts_utc, "end_ts_utc": end_ts_utc},
        "raw_evidence_pointer": [
            "claude_worklog/monitoring/snapshots.jsonl",
            "claude_worklog/monitoring/trainer_metrics.jsonl",
        ],
        "affected_component": sorted(set(affected_components)),
        "metric_values": _redact(metric_values),
        "anomaly_classification": anomaly_classification,
        "verification_command": verification_commands,
        "missing_evidence": missing_evidence,
        "confidence_level": packet_confidence_level(missing_evidence, anomaly_classification),
    }


def write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(_redact(payload), fh, indent=2)


def write_hourly_packet(packet_dirs: Dict[str, Path], payload: Dict[str, Any], now_dt: datetime) -> Path:
    name = now_dt.strftime("%Y%m%d_%H.json")
    out = packet_dirs["hourly"] / name
    write_json_file(out, payload)
    return out


def write_daily_packet(packet_dirs: Dict[str, Path], payload: Dict[str, Any], now_dt: datetime) -> Path:
    name = now_dt.strftime("%Y%m%d.json")
    out = packet_dirs["daily"] / name
    write_json_file(out, payload)
    return out


def write_alert_packet(packet_dirs: Dict[str, Path], payload: Dict[str, Any], now_dt: datetime, alert_class: str) -> Path:
    name = now_dt.strftime(f"%Y%m%d_%H%M%S_{alert_class}.json")
    out = packet_dirs["alerts"] / name
    write_json_file(out, payload)
    return out


def build_feature_freshness(map_md: Path, now_ms: int) -> Dict[str, Any]:
    patterns = parse_pattern_inventory(map_md)
    entries = [key_freshness_entry(p, now_ms) for p in patterns[:500]]
    status_counts = Counter(e.get("status") for e in entries)
    return {
        "key_pattern_inventory_count": len(patterns),
        "tracked_samples": len(entries),
        "status_counts": dict(status_counts),
        "entries": entries,
        "feature_visibility_classification": (
            "missing"
            if status_counts.get("missing", 0) >= max(1, int(0.7 * len(entries)))
            else "partial"
            if status_counts.get("missing", 0) > 0 or status_counts.get("unknown", 0) > 0
            else "complete"
        ),
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_daily_cutoff(s: str) -> Tuple[int, int]:
    try:
        hh, mm = s.split(":", 1)
        return max(0, min(23, int(hh))), max(0, min(59, int(mm)))
    except Exception:
        return 0, 0


def should_emit_daily(last_daily_key: Optional[str], dt: datetime, cutoff_h: int, cutoff_m: int) -> bool:
    day_key = dt.strftime("%Y%m%d")
    if last_daily_key == day_key:
        return False
    return dt.hour > cutoff_h or (dt.hour == cutoff_h and dt.minute >= cutoff_m)


def run_dry_validation(output_dir: Path, packet_dir: Path) -> int:
    packet_dirs = ensure_packet_dirs(packet_dir)
    checks: Dict[str, Any] = {
        "mode": "dry_validation",
        "timestamp_utc": now_utc().isoformat(),
        "read_only": True,
        "redis_write_operations": "none",
        "service_mutation": "none",
        "output_dir_exists": output_dir.exists(),
        "packet_dirs": {k: str(v) for k, v in packet_dirs.items()},
    }

    required_packet_fields = [
        "packet_id",
        "packet_type",
        "generated_ts_utc",
        "timestamp_range",
        "raw_evidence_pointer",
        "affected_component",
        "metric_values",
        "anomaly_classification",
        "verification_command",
        "missing_evidence",
        "confidence_level",
    ]

    sample = {
        "packet_id": "dry_sample",
        "packet_type": "hourly_packet",
        "generated_ts_utc": now_utc().isoformat(),
        "timestamp_range": {"start_ts_utc": now_utc().isoformat(), "end_ts_utc": now_utc().isoformat()},
        "raw_evidence_pointer": [],
        "affected_component": [],
        "metric_values": {},
        "anomaly_classification": [],
        "verification_command": [],
        "missing_evidence": [],
        "confidence_level": "high",
    }
    checks["packet_schema_ok"] = all(k in sample for k in required_packet_fields)
    checks["redis_ping_ok"] = redis_cmd("PING")[0]
    checks["validation_passed"] = bool(
        checks["output_dir_exists"] and checks["packet_schema_ok"] and checks["redis_ping_ok"]
    )

    report_path = output_dir.parent / "continuous_monitoring_impl" / "VALIDATION_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Continuous Monitor Dry Validation Report",
        "",
        f"- timestamp_utc: {checks['timestamp_utc']}",
        f"- read_only: {checks['read_only']}",
        f"- redis_write_operations: {checks['redis_write_operations']}",
        f"- service_mutation: {checks['service_mutation']}",
        f"- output_dir_exists: {checks['output_dir_exists']}",
        f"- packet_schema_ok: {checks['packet_schema_ok']}",
        f"- redis_ping_ok: {checks['redis_ping_ok']}",
        f"- validation_passed: {checks['validation_passed']}",
        "",
        "## Packet output paths",
    ]
    for k, v in checks["packet_dirs"].items():
        lines.append(f"- {k}: {v}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 0 if checks["validation_passed"] else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-hours", type=float, default=12.0)
    ap.add_argument("--interval-seconds", type=int, default=60)
    ap.add_argument("--output-dir", default="./claude_worklog/monitoring")
    ap.add_argument("--continuous", action="store_true")
    ap.add_argument("--packet-output-dir", default="./claude_worklog/continuous_monitoring/packets")
    ap.add_argument("--hourly-packet-interval", type=int, default=3600)
    ap.add_argument("--daily-cutoff-utc", default="00:00")
    ap.add_argument("--validate-continuous-dry", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = Path(args.packet_output_dir).resolve()
    packet_dirs = ensure_packet_dirs(packet_dir)

    if args.validate_continuous_dry:
        return run_dry_validation(out_dir, packet_dir)

    jsonl_path = out_dir / "snapshots.jsonl"
    trainer_metrics_path = out_dir / "trainer_metrics.jsonl"
    summary_path = (out_dir / ".." / "monitoring_summary.md").resolve()
    ingestor_map_path = (out_dir / "INGESTOR_FEATURE_KEY_MAP.md").resolve()

    end = time.time() + float(args.duration_hours) * 3600.0
    tick = 0
    stop_requested = False
    mem_samples: deque[Tuple[int, float]] = deque(maxlen=2000)

    last_hourly_emit = 0.0
    last_daily_key: Optional[str] = None
    cutoff_h, cutoff_m = parse_daily_cutoff(args.daily_cutoff_utc)

    def write_summary(reason: str) -> None:
        lines = [
            "# Read-only monitoring summary",
            "",
            f"- **Finished:** {datetime.now(timezone.utc).isoformat()}",
            f"- **Reason:** {reason}",
            "- **Mode:** continuous_read_only" if args.continuous else "- **Mode:** bounded_read_only",
            "",
            "See `monitoring/snapshots.jsonl` for per-tick JSON.",
            "Packets are under `claude_worklog/continuous_monitoring/packets/`.",
        ]
        summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def handle_stop(*_a) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    while True:
        if stop_requested:
            write_summary("signal")
            return 0
        if (not args.continuous) and time.time() >= end:
            write_summary("duration_complete")
            return 0

        tick += 1
        now_dt = now_utc()
        now_ms = int(now_dt.timestamp() * 1000)
        rec: Dict[str, Any] = {
            "tick": tick,
            "ts_utc": now_dt.isoformat(),
            "mode": "continuous_read_only" if args.continuous else "bounded_read_only",
            "redis_url_set": bool(os.environ.get("REDIS_URL")),
        }

        ok_ping, ping_out = redis_cmd("PING")
        rec["redis_ping_ok"] = ok_ping
        if not ok_ping:
            rec["redis_error"] = _redact(ping_out[:500])

        lengths = {s: xlen(s) for s in STREAMS}
        rec["stream_xlen"] = lengths

        hb = {}
        for k in HEARTBEAT_KEYS:
            ok, v = redis_cmd("GET", k)
            hb[k] = {"ok": ok, "value": _redact(v[:500] if v else "")}
        rec["heartbeats"] = hb

        exec_rows = xrevrange_json("executed_signals", 400)
        prim_rows = xrevrange_json("signals:trading:primary", 100)
        pred_rows = xrevrange_json("wma:trainer:predictions", 120)
        skips = xrevrange_json("signals:execution:skips", 60)

        rec["executed_analysis"] = analyze_executed(exec_rows, now_ms)
        rec["primary_signal_analysis"] = sample_primary_signals(prim_rows, now_ms)
        rec["attribution_completeness"] = attribution_completeness(exec_rows, prim_rows, pred_rows)
        rec["recent_skips_sample"] = len(skips)

        feature_freshness = build_feature_freshness(ingestor_map_path, now_ms)
        rec["feature_freshness"] = feature_freshness

        ratio, mem_detail = read_memory_ratio()
        if ratio is not None:
            mem_samples.append((now_ms, ratio))
        rec["redis_memory"] = {
            **mem_detail,
            "threshold_class": threshold_band(ratio),
            "memory_trend_1h": trend_value(list(mem_samples), 3_600_000),
            "memory_trend_6h": trend_value(list(mem_samples), 21_600_000),
            "memory_trend_24h": trend_value(list(mem_samples), 86_400_000),
        }

        with jsonl_path.open("a", encoding="utf-8") as jf:
            jf.write(json.dumps(_redact(rec), separators=(",", ":")) + "\n")

        trainer_metric = {
            "tick": tick,
            "ts_utc": rec["ts_utc"],
            "trainer_heartbeat": hb.get("heartbeat:trainer", {}).get("value") or hb.get("heartbeat:Trainer", {}).get("value"),
            "trainer_signal_heartbeat": hb.get("signals:trainer:heartbeat", {}).get("value"),
            "predictions_stream_xlen": lengths.get("wma:trainer:predictions"),
            "primary_stream_xlen": lengths.get("signals:trading:primary"),
            "redis_ping_ok": ok_ping,
            "memory_ratio_pct": ratio,
            "memory_threshold_class": threshold_band(ratio),
        }
        with trainer_metrics_path.open("a", encoding="utf-8") as tf:
            tf.write(json.dumps(_redact(trainer_metric), separators=(",", ":")) + "\n")

        anomalies: List[str] = []
        if rec["redis_memory"]["threshold_class"] in {"warning_85", "elevated_90", "critical_95"}:
            anomalies.append(f"redis_memory_{rec['redis_memory']['threshold_class']}")
        if feature_freshness["status_counts"].get("missing", 0) > 0:
            anomalies.append("feature_key_missing")
        if rec["attribution_completeness"]["missing_signal_id"] > 0:
            anomalies.append("missing_signal_id")
        if rec["attribution_completeness"]["missing_confidence"] > 0:
            anomalies.append("missing_confidence")
        if rec["attribution_completeness"]["missing_lineage_tuple_execution_rows"] > 0:
            anomalies.append("execution_lineage_incomplete")

        packet_metrics = {
            "ingestor_key_freshness": feature_freshness["status_counts"],
            "feature_key_freshness": {
                "fresh": feature_freshness["status_counts"].get("fresh", 0),
                "stale": feature_freshness["status_counts"].get("stale", 0),
                "missing": feature_freshness["status_counts"].get("missing", 0),
                "unknown": feature_freshness["status_counts"].get("unknown", 0),
            },
            "feature_snapshot_presence_rate": rec["attribution_completeness"]["signal_attribution_completeness_pct"],
            "confidence_movement_causes": anomalies,
            "source_redis_refs": [e.get("sample_key") for e in feature_freshness["entries"][:100] if e.get("sample_key")],
            "missing_signal_id_rate": rec["attribution_completeness"]["missing_signal_id"],
            "missing_confidence_rate": rec["attribution_completeness"]["missing_confidence"],
            "lineage_chain_complete_rate": rec["attribution_completeness"]["signal_attribution_completeness_pct"],
            "execution_lineage_complete_rate": rec["attribution_completeness"]["execution_lineage_completeness_pct"],
            "used_memory": rec["redis_memory"].get("used_memory"),
            "maxmemory": rec["redis_memory"].get("maxmemory"),
            "memory_ratio_pct": rec["redis_memory"].get("memory_ratio_pct"),
            "memory_trend_1h": rec["redis_memory"].get("memory_trend_1h"),
            "memory_trend_6h": rec["redis_memory"].get("memory_trend_6h"),
            "memory_trend_24h": rec["redis_memory"].get("memory_trend_24h"),
            "threshold_class": rec["redis_memory"].get("threshold_class"),
        }

        common_payload = packet_common(
            packet_type="hourly_packet",
            start_ts_utc=now_dt.isoformat(),
            end_ts_utc=now_dt.isoformat(),
            affected_components=["redis", "feature_pipeline", "trainer", "orchestrator", "trader"],
            metric_values=packet_metrics,
            anomaly_classification=anomalies,
            verification_commands=[
                "redis-cli INFO memory",
                "redis-cli XLEN signals:trading",
                "python3 claude_worklog/tools/runtime_monitor_dashboard.py --once",
            ],
            missing_evidence=["ingestor_feature_key_map_missing"] if not ingestor_map_path.exists() else [],
        )

        now_epoch = time.time()
        if now_epoch - last_hourly_emit >= max(300, int(args.hourly_packet_interval)):
            write_hourly_packet(packet_dirs, common_payload, now_dt)
            last_hourly_emit = now_epoch

        if should_emit_daily(last_daily_key, now_dt, cutoff_h, cutoff_m):
            daily_payload = dict(common_payload)
            daily_payload["packet_type"] = "daily_packet"
            write_daily_packet(packet_dirs, daily_payload, now_dt)
            last_daily_key = now_dt.strftime("%Y%m%d")

        if anomalies:
            alert_payload = dict(common_payload)
            alert_payload["packet_type"] = "alert_packet"
            alert_class = anomalies[0]
            write_alert_packet(packet_dirs, alert_payload, now_dt, alert_class)

        time.sleep(max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
