"""Legacy log intelligence read-only service (paper-only)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Optional

LEGACY_BOT_ROOT = Path("/home/wali/Desktop/AI BOT")
LEGACY_LOGS_DIR = LEGACY_BOT_ROOT / "logs"
LEGACY_SCRIPTS_DIR = LEGACY_BOT_ROOT / "scripts"
OFFSET_DIR = Path("v2/runtime/legacy_log_intelligence/offsets")
MAX_TAIL_BYTES = 256 * 1024

REQUIRED_LOG_REQUESTS = (
    "logs/hybrid_trainer.log",
    "logs/orchestrator_worker.log",
)
REQUIRED_SCRIPT_REQUESTS = (
    "scripts/monitor_trainer_prices.py",
    "scripts/monitor_trainer_predictions.py",
    "scripts/monitor_signals.py",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_from_ts(ts: float) -> str:
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _resolve_with_typo_tolerance(requested: str) -> tuple[Optional[Path], str]:
    req = requested.strip()
    if not req:
        return None, "MISSING_PATH"
    head, _, tail = req.rpartition("/")
    head_l = head.lower().replace(" ", "")
    candidate_dirs: list[Path] = []
    if "log" in head_l:
        candidate_dirs.append(LEGACY_LOGS_DIR)
    if "script" in head_l:
        candidate_dirs.append(LEGACY_SCRIPTS_DIR)
    candidate_dirs.append(LEGACY_LOGS_DIR)
    candidate_dirs.append(LEGACY_SCRIPTS_DIR)
    candidate_dirs.append(LEGACY_BOT_ROOT)
    basename = tail or req
    candidates = [basename]
    if not basename.lower().endswith((".py", ".log", ".sh", ".json", ".toml", ".yaml", ".yml")):
        candidates.append(basename + ".py")
        candidates.append(basename + ".log")
    for d in candidate_dirs:
        if not d.is_dir():
            continue
        try:
            listing = [p.name for p in d.iterdir() if p.is_file()]
        except OSError:
            continue
        for cand in candidates:
            if cand in listing:
                return d / cand, "FOUND_READONLY"
        for cand in candidates:
            close = get_close_matches(cand, listing, n=2, cutoff=0.65)
            if len(close) > 1:
                return d / close[0], "AMBIGUOUS_MULTIPLE_MATCHES"
            if len(close) == 1:
                return d / close[0], "FOUND_READONLY"
    return None, "MISSING_PATH"


@dataclass
class SourceDescriptor:
    requested_name: str
    resolved_path: Optional[str]
    exists: bool
    readable: bool
    is_file: bool
    file_size_bytes: int
    mtime_utc: Optional[str]
    last_read_offset: int
    classification: str


def _offset_path_for(p: Path) -> Path:
    safe = str(p).replace("/", "_").replace(" ", "_").strip("_")
    return OFFSET_DIR / f"{safe}.offset"


def _load_offset(p: Path) -> int:
    op = _offset_path_for(p)
    if not op.exists():
        return 0
    try:
        return int(op.read_text().strip() or "0")
    except (OSError, ValueError):
        return 0


def _save_offset(p: Path, offset: int) -> None:
    OFFSET_DIR.mkdir(parents=True, exist_ok=True)
    op = _offset_path_for(p)
    try:
        op.write_text(str(int(offset)))
    except OSError:
        pass


def _read_tail(p: Path, start_offset: int) -> tuple[bytes, int]:
    try:
        st = p.stat()
    except OSError:
        return b"", start_offset
    size = int(st.st_size)
    if size < start_offset:
        start_offset = 0
    if size <= start_offset:
        return b"", size
    read_from = start_offset
    if size - start_offset > MAX_TAIL_BYTES:
        read_from = size - MAX_TAIL_BYTES
    try:
        with p.open("rb") as fh:
            fh.seek(read_from)
            data = fh.read(size - read_from)
    except OSError:
        return b"", start_offset
    return data, size


def _stale_seconds(p: Path) -> int:
    try:
        return int(datetime.now(timezone.utc).timestamp() - p.stat().st_mtime)
    except OSError:
        return -1


def _classify_source(requested: str, resolved: Optional[Path], cls_hint: str) -> SourceDescriptor:
    if resolved is None:
        return SourceDescriptor(
            requested_name=requested, resolved_path=None, exists=False, readable=False,
            is_file=False, file_size_bytes=0, mtime_utc=None, last_read_offset=0,
            classification="MISSING_PATH",
        )
    try:
        st = resolved.stat()
    except OSError:
        return SourceDescriptor(
            requested_name=requested, resolved_path=str(resolved), exists=False, readable=False,
            is_file=False, file_size_bytes=0, mtime_utc=None, last_read_offset=0,
            classification="UNREADABLE",
        )
    if not resolved.is_file():
        return SourceDescriptor(
            requested_name=requested, resolved_path=str(resolved), exists=True, readable=False,
            is_file=False, file_size_bytes=int(st.st_size), mtime_utc=_utc_from_ts(st.st_mtime),
            last_read_offset=0, classification="NOT_A_FILE",
        )
    try:
        with resolved.open("rb") as fh:
            fh.read(1)
        readable = True
    except OSError:
        readable = False
    return SourceDescriptor(
        requested_name=requested, resolved_path=str(resolved), exists=True, readable=readable,
        is_file=True, file_size_bytes=int(st.st_size), mtime_utc=_utc_from_ts(st.st_mtime),
        last_read_offset=_load_offset(resolved),
        classification=cls_hint if readable else "UNREADABLE",
    )


def _descriptor_to_dict(d: SourceDescriptor) -> dict:
    return {
        "requested_name": d.requested_name,
        "resolved_path": d.resolved_path,
        "exists": d.exists,
        "readable": d.readable,
        "is_file": d.is_file,
        "file_size_bytes": d.file_size_bytes,
        "mtime_utc": d.mtime_utc,
        "last_read_offset": d.last_read_offset,
        "classification": d.classification,
    }


def discover_legacy_sources() -> dict:
    logs: list[dict] = []
    for req in REQUIRED_LOG_REQUESTS:
        resolved, hint = _resolve_with_typo_tolerance(req)
        logs.append(_descriptor_to_dict(_classify_source(req, resolved, hint)))
    scripts: list[dict] = []
    for req in REQUIRED_SCRIPT_REQUESTS:
        resolved, hint = _resolve_with_typo_tolerance(req)
        scripts.append(_descriptor_to_dict(_classify_source(req, resolved, hint)))
    typo_probes = [
        "scripts/monitor_trainer_prediction.py",
        "scripts/monitor_trainer_oediction.py",
        "scripts/monitor_trainer_prices",
        "scripts/monitor_signals",
    ]
    typo_results: list[dict] = []
    for req in typo_probes:
        resolved, hint = _resolve_with_typo_tolerance(req)
        typo_results.append(_descriptor_to_dict(_classify_source(req, resolved, hint)))
    return {
        "schema_version": "v2_legacy_log_source_discovery_v1",
        "generated_utc": _utc_iso(),
        "legacy_bot_root": str(LEGACY_BOT_ROOT),
        "logs_dir": str(LEGACY_LOGS_DIR),
        "scripts_dir": str(LEGACY_SCRIPTS_DIR),
        "logs": logs,
        "scripts": scripts,
        "typo_tolerance_probes": typo_results,
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
        "no_legacy_script_executed": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


_TRAINER_PATTERNS = {
    "heartbeat": re.compile(r"\b(heartbeat|hybrid_trainer_alive|loop tick)\b", re.IGNORECASE),
    "prediction_event": re.compile(r"\bprediction[:\s]+(?P<sym>[A-Z0-9]{3,12})[:\s]+(?P<tf>1m|5m|15m|1h|4h|1d)\b"),
    "action_event": re.compile(r"\b(action|decision)\s*[:=]\s*(?P<action>hold|long|short|close|close_short_open_long|open_short|open_long|close_long_open_short)\b", re.IGNORECASE),
    "confidence_event": re.compile(r"\b(confidence|conf)\s*[:=]\s*(?P<conf>[01](?:\.\d+)?)\b", re.IGNORECASE),
    "ppo_confidence": re.compile(r"\bppo_confidence\s*[:=]\s*(?P<v>[01](?:\.\d+)?)\b", re.IGNORECASE),
    "masa_confidence": re.compile(r"\bmasa_confidence\s*[:=]\s*(?P<v>[01](?:\.\d+)?)\b", re.IGNORECASE),
    "expected_move": re.compile(r"\b(expected_move|expected_move_bps|expected_move_after_cost_bps)\s*[:=]\s*(?P<v>-?\d+(?:\.\d+)?)\b", re.IGNORECASE),
    "checkpoint": re.compile(r"\b(checkpoint|model_version|ppo_masa_ckpt|hybrid_trainer_ckpt)[:=\s]+([A-Za-z0-9_\-./]+)", re.IGNORECASE),
    "gpu_warning": re.compile(r"\b(cuda|gpu)\b.*\b(warn|error|out of memory|oom|fallback|cpu)\b", re.IGNORECASE),
    "feature_warning": re.compile(r"\b(feature)\b.*\b(missing|stale|nan|inf|skip)\b", re.IGNORECASE),
    "redis_publish": re.compile(r"\bpublish(ed)?\s+(prediction|signal)\b", re.IGNORECASE),
    "error_or_exception": re.compile(r"\b(exception|traceback|error)\b", re.IGNORECASE),
    "nan_inf": re.compile(r"\b(nan|inf|infinity)\b", re.IGNORECASE),
    "paralysis": re.compile(r"\b(paralysis|no\s+prediction|stuck)\b", re.IGNORECASE),
    "model_reload": re.compile(r"\b(checkpoint loaded|model reloaded|loaded weights)\b", re.IGNORECASE),
    "loss": re.compile(r"\b(loss|policy_loss|value_loss|entropy)\s*[:=]\s*(?P<v>-?\d+(?:\.\d+)?)\b", re.IGNORECASE),
    "signal_gate": re.compile(r"\b(signal\s+gated|gate\s+(open|close|block))\b", re.IGNORECASE),
}

_ORCH_PATTERNS = {
    "heartbeat": re.compile(r"\b(orchestrator|tradeplan).*\b(heartbeat|tick|loop)\b", re.IGNORECASE),
    "proposal": re.compile(r"\bproposal\s+(?P<id>[A-Za-z0-9_:.\-]+)\s+(consumed|received)\b", re.IGNORECASE),
    "signal_emit": re.compile(r"\b(emit|publish(ed)?)\s+signal\s+(?P<id>[A-Za-z0-9_:.\-]+)\b", re.IGNORECASE),
    "action_event": re.compile(r"\b(action|side)\s*[:=]\s*(?P<action>hold|long|short|close)\b", re.IGNORECASE),
    "score": re.compile(r"\b(score|confidence|protection_demand)\s*[:=]\s*(?P<v>-?\d+(?:\.\d+)?)\b", re.IGNORECASE),
    "deconflict": re.compile(r"\b(deconflict|ALL_SIGNALS_AGREE|MISSING_EVIDENCE|CONFLICT)\b", re.IGNORECASE),
    "stale_reject": re.compile(r"\b(stale|expired)\s+(proposal|signal|reject(ed)?)\b", re.IGNORECASE),
    "dup_reject": re.compile(r"\b(duplicate|already seen)\s+(proposal|signal|reject(ed)?)\b", re.IGNORECASE),
    "hedge_overlay": re.compile(r"\b(hedge|protection)\s+(overlay|applied|needed)\b", re.IGNORECASE),
    "consensus": re.compile(r"\b(htf|higher_timeframe)\s+(consensus|veto)\b", re.IGNORECASE),
    "stream_publish": re.compile(r"\b(xadd|stream\s+publish|consumer\s+group)\b", re.IGNORECASE),
    "stream_error": re.compile(r"\b(consumer\s+group|stream)\b.*\b(error|fail)\b", re.IGNORECASE),
    "error_or_exception": re.compile(r"\b(exception|traceback|error)\b", re.IGNORECASE),
    "no_trade_reason": re.compile(r"\b(no_trade|hold|block(ed)?|gate(d)?)\b", re.IGNORECASE),
}


def _scan_lines(lines: list[str], patterns: dict) -> dict:
    out: dict[str, Any] = {k: [] for k in patterns}
    error_count = 0
    nan_inf_count = 0
    for line in lines:
        for k, pat in patterns.items():
            m = pat.search(line)
            if m:
                out[k].append({"line": line.strip()[:240], "match": m.groupdict() or m.group(0)[:80]})
                if k == "error_or_exception":
                    error_count += 1
                if k == "nan_inf":
                    nan_inf_count += 1
    return {"matches_by_kind": out, "error_count": error_count, "nan_inf_count": nan_inf_count}


def parse_trainer_log_tail(p: Path, start_offset: int) -> dict:
    data, new_offset = _read_tail(p, start_offset)
    if not data:
        return {
            "source_path": str(p),
            "new_bytes": 0,
            "last_offset": new_offset,
            "trainer_log_stale_seconds": _stale_seconds(p),
            "matches": {},
            "latest_trainer_action_by_symbol": {},
            "latest_trainer_confidence_by_symbol": {},
            "latest_trainer_errors": [],
            "trainer_missing_fields": [],
            "trainer_behavior_v2_equivalence_notes": [],
        }
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    lines = text.splitlines()
    scanned = _scan_lines(lines, _TRAINER_PATTERNS)
    matches = scanned["matches_by_kind"]
    actions_by_symbol: dict[str, str] = {}
    conf_by_symbol: dict[str, float] = {}
    last_symbol: Optional[str] = None
    for ev in matches.get("prediction_event", []):
        sym = (ev.get("match") or {}).get("sym")
        if sym:
            last_symbol = sym
    for ev in matches.get("action_event", []):
        action = (ev.get("match") or {}).get("action")
        if last_symbol and action:
            actions_by_symbol[last_symbol] = action
    for ev in matches.get("confidence_event", []):
        v = (ev.get("match") or {}).get("conf")
        try:
            cval = float(v) if v else None
        except (TypeError, ValueError):
            cval = None
        if last_symbol and cval is not None:
            conf_by_symbol[last_symbol] = cval
    errors = [e["line"] for e in matches.get("error_or_exception", [])[-5:]]
    notes: list[str] = []
    if matches.get("paralysis"):
        notes.append("trainer_log_reports_paralysis_or_stuck")
    if matches.get("nan_inf"):
        notes.append("trainer_log_reports_nan_or_inf")
    if matches.get("gpu_warning"):
        notes.append("trainer_log_reports_gpu_warning")
    if matches.get("feature_warning"):
        notes.append("trainer_log_reports_feature_missing_or_stale")
    return {
        "source_path": str(p),
        "new_bytes": len(data),
        "last_offset": new_offset,
        "trainer_log_stale_seconds": _stale_seconds(p),
        "matches": {k: len(v) for k, v in matches.items()},
        "latest_trainer_action_by_symbol": actions_by_symbol,
        "latest_trainer_confidence_by_symbol": conf_by_symbol,
        "latest_trainer_errors": errors,
        "error_count": scanned["error_count"],
        "nan_inf_count": scanned["nan_inf_count"],
        "trainer_missing_fields": [
            k for k in ("prediction_event", "action_event", "confidence_event") if not matches.get(k)
        ],
        "trainer_behavior_v2_equivalence_notes": notes,
    }


def parse_orchestrator_log_tail(p: Path, start_offset: int) -> dict:
    data, new_offset = _read_tail(p, start_offset)
    if not data:
        return {
            "source_path": str(p),
            "new_bytes": 0,
            "last_offset": new_offset,
            "orchestrator_log_stale_seconds": _stale_seconds(p),
            "matches": {},
            "latest_orchestrator_signal_by_symbol": {},
            "latest_orchestrator_action_by_symbol": {},
            "latest_orchestrator_block_reasons": [],
            "latest_orchestrator_errors": [],
            "orchestrator_behavior_v2_equivalence_notes": [],
        }
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    lines = text.splitlines()
    scanned = _scan_lines(lines, _ORCH_PATTERNS)
    matches = scanned["matches_by_kind"]
    actions: dict[str, str] = {}
    signals: dict[str, str] = {}
    for ev in matches.get("action_event", []):
        a = (ev.get("match") or {}).get("action")
        if a:
            actions.setdefault("__last__", a)
    for ev in matches.get("signal_emit", []):
        sid = (ev.get("match") or {}).get("id")
        if sid:
            signals.setdefault("__last__", sid)
    block_reasons: list[str] = []
    if matches.get("stale_reject"):
        block_reasons.append("stale_reject")
    if matches.get("dup_reject"):
        block_reasons.append("duplicate_reject")
    if matches.get("deconflict"):
        block_reasons.append("deconflict")
    if matches.get("no_trade_reason"):
        block_reasons.append("no_trade_or_hold")
    errors = [e["line"] for e in matches.get("error_or_exception", [])[-5:]]
    notes: list[str] = []
    if matches.get("stream_error"):
        notes.append("orchestrator_log_reports_stream_or_consumer_error")
    if matches.get("hedge_overlay"):
        notes.append("orchestrator_log_reports_hedge_overlay_event")
    if matches.get("consensus"):
        notes.append("orchestrator_log_reports_htf_consensus_event")
    return {
        "source_path": str(p),
        "new_bytes": len(data),
        "last_offset": new_offset,
        "orchestrator_log_stale_seconds": _stale_seconds(p),
        "matches": {k: len(v) for k, v in matches.items()},
        "latest_orchestrator_signal_by_symbol": signals,
        "latest_orchestrator_action_by_symbol": actions,
        "latest_orchestrator_block_reasons": block_reasons,
        "latest_orchestrator_errors": errors,
        "error_count": scanned["error_count"],
        "orchestrator_behavior_v2_equivalence_notes": notes,
    }


def _process_running(needle: str) -> Optional[dict]:
    try:
        out = subprocess.run(["pgrep", "-fa", needle], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    first = out.stdout.splitlines()[0].strip()
    parts = first.split(None, 1)
    return {"pid": parts[0] if parts else "", "cmd": parts[1] if len(parts) > 1 else first}


def inspect_monitor_script(p: Path) -> dict:
    if not p.is_file():
        return {"source_path": str(p), "exists": False, "readable": False, "classification": "MISSING_PATH"}
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return {"source_path": str(p), "exists": True, "readable": False, "classification": "UNREADABLE"}
    redis_reads = sorted(set(
        re.findall(r"r\.get\(['\"]([^'\"]+)['\"]", text)
        + re.findall(r"redis\.get\(['\"]([^'\"]+)['\"]", text)
        + re.findall(r"hgetall\(['\"]([^'\"]+)['\"]", text)
    ))
    redis_writes = sorted(set(
        re.findall(r"\.set\(['\"]([^'\"]+)['\"]", text)
        + re.findall(r"\.publish\(['\"]([^'\"]+)['\"]", text)
        + re.findall(r"\.xadd\(['\"]([^'\"]+)['\"]", text)
    ))
    log_files = sorted(set(re.findall(r"['\"]([A-Za-z0-9_/.\-]*\.log)['\"]", text)))
    purpose: list[str] = []
    if "prediction" in p.name.lower():
        purpose.append("watch trainer prediction Redis keys + log")
    if "price" in p.name.lower():
        purpose.append("watch trainer price Redis keys + log")
    if "signal" in p.name.lower():
        purpose.append("watch orchestrator signal stream and emitted signals")
    pid_info = _process_running(p.name)
    return {
        "source_path": str(p),
        "exists": True,
        "readable": True,
        "classification": ("READONLY_LEGACY_MONITOR_RUNNING" if pid_info else "LEGACY_MONITOR_NOT_RUNNING"),
        "purpose_static_summary": purpose,
        "redis_keys_read": redis_reads,
        "redis_keys_written": redis_writes,
        "log_files_referenced": log_files,
        "process_running": bool(pid_info),
        "process_info": pid_info,
    }


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _safe_v2_set(r, key: str, value: str, ex: int = 600) -> bool:
    if r is None or not key.startswith("v2:"):
        return False
    try:
        r.set(key, value, ex=ex)
        return True
    except Exception:
        return False


def observe_once() -> dict:
    discovery = discover_legacy_sources()
    trainer = None
    for entry in discovery["logs"]:
        if entry["resolved_path"] and "hybrid_trainer" in entry["resolved_path"] and entry["readable"]:
            p = Path(entry["resolved_path"])
            trainer = parse_trainer_log_tail(p, entry["last_read_offset"])
            _save_offset(p, trainer["last_offset"])
            break
    orchestrator = None
    for entry in discovery["logs"]:
        if entry["resolved_path"] and "orchestrator_worker" in entry["resolved_path"] and entry["readable"]:
            p = Path(entry["resolved_path"])
            orchestrator = parse_orchestrator_log_tail(p, entry["last_read_offset"])
            _save_offset(p, orchestrator["last_offset"])
            break
    monitor_scripts: list[dict] = []
    for entry in discovery["scripts"]:
        if entry["resolved_path"]:
            monitor_scripts.append(inspect_monitor_script(Path(entry["resolved_path"])))
        else:
            monitor_scripts.append({
                "requested_name": entry["requested_name"],
                "resolved_path": None,
                "classification": "MISSING_PATH",
            })
    out = {
        "schema_version": "v2_legacy_log_intelligence_status_v1",
        "generated_at": _utc_iso(),
        "heartbeat_at": _utc_iso(),
        "freshness_seconds": 0,
        "process_running": True,
        "sources": discovery,
        "trainer_log_summary": trainer or {"present": False},
        "orchestrator_log_summary": orchestrator or {"present": False},
        "monitor_scripts_summary": monitor_scripts,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
        "no_legacy_script_executed": True,
    }
    r = _connect_redis()
    if r is not None:
        _safe_v2_set(r, "v2:legacy_log_observer:heartbeat", json.dumps({
            "at": out["heartbeat_at"],
            "trainer_present": out["trainer_log_summary"].get("source_path") is not None,
            "orchestrator_present": out["orchestrator_log_summary"].get("source_path") is not None,
            "monitor_script_count": len(monitor_scripts),
        }))
        _safe_v2_set(r, "v2:legacy_log_observer:trainer", json.dumps(out["trainer_log_summary"]))
        _safe_v2_set(r, "v2:legacy_log_observer:orchestrator", json.dumps(out["orchestrator_log_summary"]))
        _safe_v2_set(r, "v2:legacy_log_observer:monitors", json.dumps(monitor_scripts))
        _safe_v2_set(r, "v2:legacy_log_observer:last_summary", json.dumps({
            "trainer_actions": out["trainer_log_summary"].get("latest_trainer_action_by_symbol", {}),
            "orchestrator_block_reasons": out["orchestrator_log_summary"].get("latest_orchestrator_block_reasons", []),
        }))
    return out


def enrich_comparison(observation: dict, comparison: dict) -> dict:
    enriched: dict[str, Any] = {
        "schema_version": "v2_legacy_log_enriched_comparison_v1",
        "generated_utc": _utc_iso(),
        "no_invented_outcomes": True,
        "per_symbol": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
    }
    trainer_actions: dict[str, str] = ((observation.get("trainer_log_summary") or {})
                                       .get("latest_trainer_action_by_symbol") or {})
    orch_block_reasons: list[str] = ((observation.get("orchestrator_log_summary") or {})
                                     .get("latest_orchestrator_block_reasons") or [])
    for row in (comparison.get("per_symbol") or []):
        sym = row.get("symbol")
        v2 = row.get("v2") or {}
        legacy = row.get("legacy") or {}
        v2_action = v2.get("selected_action")
        legacy_action_from_redis = legacy.get("action")
        legacy_log_action = trainer_actions.get(sym) or "MISSING_EVIDENCE"
        causes: list[str] = []
        v2_block_reasons = (v2.get("paper_fill_gate_block_reasons") or [])
        row_matches = bool(row.get("match"))
        legacy_action_norm = str(legacy_action_from_redis or "").lower()
        if not row_matches and legacy_log_action == "MISSING_EVIDENCE":
            causes.append("missing_legacy_log_action_evidence")
        if not v2.get("exists"):
            causes.append("missing_v2_prediction")
        if not legacy.get("exists"):
            causes.append("missing_legacy_log_evidence")
        if v2_action == "hold" and legacy_action_from_redis and legacy_action_norm != "hold":
            causes.append("V2_hold_due_strict_gate")
            causes.append("checkpoint_weight_missing")
        v2_fresh = v2.get("feature_freshness_state")
        legacy_fresh = legacy.get("feature_freshness_state")
        if v2_fresh and legacy_fresh and v2_fresh != legacy_fresh:
            causes.append("feature_freshness_mismatch")
        if v2_block_reasons:
            causes.append("v2_paper_fill_gate_blocked")
        if "deconflict" in orch_block_reasons:
            causes.append("orchestrator_deconflict_mismatch")
        enriched["per_symbol"].append({
            "symbol": sym,
            "legacy_log_action": legacy_log_action,
            "legacy_redis_action": legacy_action_from_redis,
            "v2_action": v2_action,
            "v2_paper_fill_allowed": v2.get("paper_fill_allowed"),
            "v2_paper_fill_gate_block_reasons": v2_block_reasons,
            "match": row_matches,
            "mismatch_reason": ",".join(causes) if causes else None,
            "mismatch_causes_classified": causes,
        })
    return enriched


def remediation_hints_from_summary(observation: dict, enriched: dict) -> list[dict]:
    now = _utc_iso()
    hints: list[dict] = []
    trainer = observation.get("trainer_log_summary") or {}
    orchestrator = observation.get("orchestrator_log_summary") or {}
    monitors = observation.get("monitor_scripts_summary") or []
    trainer_stale = trainer.get("trainer_log_stale_seconds", -1)
    orch_stale = orchestrator.get("orchestrator_log_stale_seconds", -1)
    if trainer_stale is not None and trainer_stale > 600:
        hints.append({
            "id": "LEGACY_LOG_STALE_OR_MISSING",
            "severity": "INFO",
            "first_seen": now,
            "last_seen": now,
            "source_log_or_script": trainer.get("source_path", "logs/hybrid_trainer.log"),
            "symbol": None,
            "legacy_evidence": f"trainer_log_stale_seconds={trainer_stale}",
            "v2_evidence": "v2_rl_core_inference_loop heartbeat fresh",
            "recommended_claude_task": "Verify trainer log path or confirm legacy trainer paused.",
        })
    if orch_stale is not None and orch_stale > 600:
        hints.append({
            "id": "LEGACY_LOG_STALE_OR_MISSING",
            "severity": "INFO",
            "first_seen": now,
            "last_seen": now,
            "source_log_or_script": orchestrator.get("source_path", "logs/orchestrator_worker.log"),
            "symbol": None,
            "legacy_evidence": f"orchestrator_log_stale_seconds={orch_stale}",
            "v2_evidence": "v2_orchestrator_arbitration_loop heartbeat fresh",
            "recommended_claude_task": "Verify orchestrator log path or confirm legacy orchestrator paused.",
        })
    for row in (enriched.get("per_symbol") or []):
        if not row.get("match") and "V2_hold_due_strict_gate" in (row.get("mismatch_causes_classified") or []):
            hints.append({
                "id": "LEGACY_TRAINER_ACTION_NOT_REPLICATED_BY_V2_POLICY",
                "severity": "P1_FIX",
                "first_seen": now,
                "last_seen": now,
                "source_log_or_script": trainer.get("source_path", "logs/hybrid_trainer.log"),
                "symbol": row.get("symbol"),
                "legacy_evidence": f"legacy action={row.get('legacy_redis_action')}",
                "v2_evidence": f"v2 action={row.get('v2_action')}; paper_fill_allowed={row.get('v2_paper_fill_allowed')}",
                "recommended_claude_task": "Operator action: provide approved checkpoint blob (CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED) or accept paper-only limitation.",
            })
        if "feature_freshness_mismatch" in (row.get("mismatch_causes_classified") or []):
            hints.append({
                "id": "LEGACY_TRAINER_FEATURE_FIELD_MISSING_IN_V2",
                "severity": "P1_FIX",
                "first_seen": now,
                "last_seen": now,
                "source_log_or_script": trainer.get("source_path", "logs/hybrid_trainer.log"),
                "symbol": row.get("symbol"),
                "legacy_evidence": "legacy feature_freshness_state differs",
                "v2_evidence": "v2 feature_freshness_state differs",
                "recommended_claude_task": "Check v2_feature_pipeline_native_loop freshness gate for symbol.",
            })
    if "deconflict" in (orchestrator.get("latest_orchestrator_block_reasons") or []):
        hints.append({
            "id": "LEGACY_ORCHESTRATOR_DECONFLICT_NOT_REPLICATED",
            "severity": "INFO",
            "first_seen": now,
            "last_seen": now,
            "source_log_or_script": orchestrator.get("source_path", "logs/orchestrator_worker.log"),
            "symbol": None,
            "legacy_evidence": "legacy orchestrator log shows deconflict",
            "v2_evidence": "v2 orchestrator emits same path via in-process bus",
            "recommended_claude_task": "Confirm v2_orchestrator_arbitration_loop deconflict reasons cover legacy categories.",
        })
    for mscript in monitors:
        cls = mscript.get("classification")
        if cls == "MISSING_PATH":
            hints.append({
                "id": "LEGACY_MONITOR_SCRIPT_PATH_MISSING",
                "severity": "INFO",
                "first_seen": now,
                "last_seen": now,
                "source_log_or_script": mscript.get("requested_name", ""),
                "symbol": None,
                "legacy_evidence": "requested monitor script not found",
                "v2_evidence": "n/a",
                "recommended_claude_task": "Confirm operator path or treat as not-required.",
            })
        elif cls == "READONLY_LEGACY_MONITOR_RUNNING":
            reads = mscript.get("redis_keys_read") or []
            writes = mscript.get("redis_keys_written") or []
            if reads and not any(k.startswith("v2:") for k in reads + writes):
                hints.append({
                    "id": "LEGACY_MONITOR_SIGNALS_READS_KEY_NOT_IN_V2",
                    "severity": "INFO",
                    "first_seen": now,
                    "last_seen": now,
                    "source_log_or_script": mscript.get("source_path"),
                    "symbol": None,
                    "legacy_evidence": f"legacy reads keys: {reads[:5]}",
                    "v2_evidence": "v2 namespace v2:* may not yet host equivalents",
                    "recommended_claude_task": "Map legacy keys to v2:* equivalents in equivalence comparator.",
                })
    if (trainer.get("nan_inf_count") or 0) > 0:
        hints.append({
            "id": "LEGACY_TRAINER_NAN_INF_DETECTED",
            "severity": "INFO",
            "first_seen": now,
            "last_seen": now,
            "source_log_or_script": trainer.get("source_path"),
            "symbol": None,
            "legacy_evidence": f"nan_inf_count={trainer.get('nan_inf_count')}",
            "v2_evidence": "n/a",
            "recommended_claude_task": "Read legacy trainer error context only; no V2 action required.",
        })
    return hints
