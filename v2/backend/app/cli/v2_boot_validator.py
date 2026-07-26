"""Permanent boot validator (PERMANENT_SYSTEM_RECOVERY Section 10).

Runs after ai-bot-v2-stack.target (and periodically via timer). Classifies
every ai-bot user unit, validates runtime planes, and publishes:

  v2:operations:boot_validation
  v2:evidence:credentialed_services_status

Exit code 0 = boot valid (failures list empty), 1 = FAILED_UNEXPECTED present.
Read-only against the trading system; writes only its two status keys.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
KLINE_STATUS = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json"
PUBLISHER_STATUS = Path("/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled_base_publisher_status_v1.json")
COMMISSION_CAS = Path("/home/wali/ai_bot_local_data/v2_authenticated_evidence/binance_usdm_commission_broker_v1/commission-evidence-cas")
UNIT_DIR = Path.home() / ".config/systemd/user"
PLANE_TARGETS = [
    "ai-bot-v2-data-plane.target",
    "ai-bot-v2-evidence-plane.target",
    "ai-bot-v2-training.target",
    "ai-bot-v2-serving.target",
    "ai-bot-v2-paper-runtime.target",
    "ai-bot-v2-observability.target",
]
SUPERSEDED = {
    "ai-bot-v2-profiled-base-feature-publisher.service": "ai-bot-v2-native-cuda-trainer-persistent.service",
    "ai-bot-v2-paper-online-runtime.service": "ai-bot-v2-trade-management-paper-loop.service",
}
FRESHNESS_SAMPLE_STRIDE = 8
DATA_PLANE_MIN_FRESH_FRACTION = 0.95


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def redis_cli(*args: str) -> str:
    return sh(["redis-cli", *args])


def get_json_key(key: str):
    raw = redis_cli("GET", key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def unit_state(unit: str) -> tuple[str, str, str]:
    out = sh(["systemctl", "--user", "show", unit,
              "-p", "ActiveState", "-p", "SubState", "-p", "ConditionResult"])
    vals = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return vals.get("ActiveState", "unknown"), vals.get("SubState", ""), vals.get("ConditionResult", "")


def expected_active_units() -> dict[str, str]:
    expected: dict[str, str] = {}
    for target in PLANE_TARGETS:
        wants_dir = UNIT_DIR / f"{target}.wants"
        if wants_dir.is_dir():
            for link in sorted(wants_dir.iterdir()):
                expected[link.name] = target
    return expected


def repair_holds() -> dict[str, dict]:
    payload = get_json_key("v2:operations:repair_holds") or {}
    return {h.get("unit"): h for h in payload.get("holds", []) if h.get("unit")}


def credentialed_units() -> list[str]:
    units = []
    for path in sorted(UNIT_DIR.glob("ai-bot-v2-*.service")):
        try:
            text = path.read_text()
        except OSError:
            continue
        if "LoadCredential" in text or ".cred" in text:
            units.append(path.name)
    return units


def classify_units() -> tuple[list[dict], list[dict]]:
    expected = expected_active_units()
    holds = repair_holds()
    now = utc_now()
    rows: list[dict] = []
    failures: list[dict] = []
    listed = sh(["bash", "-c",
                 "systemctl --user list-unit-files 'ai-bot*.service' --no-legend | awk '{print $1, $2}'"])
    for line in listed.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit, enable_state = parts[0], (parts[1] if len(parts) > 1 else "unknown")
        active, sub, cond = unit_state(unit)
        hold = holds.get(unit)
        if hold:
            classification = "INACTIVE_REPAIR_HELD"
            if str(hold.get("expires_at", "9999")) < now:
                classification = "FAILED_UNEXPECTED"
                failures.append({
                    "unit": unit, "expected_state": "hold renewed or released with receipt",
                    "actual_state": f"hold expired {hold.get('expires_at')}",
                    "reason": "repair hold past expiry", "owner": hold.get("owner"),
                    "recovery_action": "renew RepairHoldV1 with receipt or release the hold",
                })
        elif unit in SUPERSEDED:
            classification = "SUPERSEDED"
            if active == "active":
                failures.append({
                    "unit": unit, "expected_state": "inactive (superseded)",
                    "actual_state": active,
                    "reason": f"superseded by {SUPERSEDED[unit]} but still running (duplicate writer risk)",
                    "owner": "operations", "recovery_action": "stop + mask after replacement proven",
                })
        elif unit in expected:
            if active == "active":
                classification = "ACTIVE_EXPECTED"
            elif cond == "no":
                classification = "INACTIVE_CREDENTIALS_REQUIRED"
            else:
                classification = "FAILED_UNEXPECTED"
                failures.append({
                    "unit": unit, "expected_state": "active",
                    "actual_state": f"{active}/{sub}",
                    "reason": f"member of {expected[unit]} but not running",
                    "owner": "operations",
                    "recovery_action": f"journalctl --user -u {unit}; systemctl --user start {unit}",
                })
        else:
            classification = "OPTIONAL"
        rows.append({
            "unit": unit, "classification": classification, "enable_state": enable_state,
            "active_state": active, "sub_state": sub, "plane": expected.get(unit),
        })
    return rows, failures


def check_gpu() -> dict:
    out = sh(["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"])
    return {"ok": "RTX" in out or "NVIDIA" in out, "detail": out or "nvidia-smi unavailable"}


def check_redis() -> dict:
    return {"ok": redis_cli("PING") == "PONG", "detail": "PING"}


def check_data_plane() -> dict:
    try:
        status = json.loads(KLINE_STATUS.read_text())
        symbols = list(status.get("symbols") or [])
    except Exception as error:
        return {"ok": False, "detail": f"kline status unreadable: {error}"}
    if not symbols:
        return {"ok": False, "detail": "kline status has no symbols"}
    sample = sorted(set(symbols[::FRESHNESS_SAMPLE_STRIDE] + ["BTCUSDT", "ETHUSDT", "SOLUSDT"]) & set(symbols))
    now_ms = int(time.time() * 1000)
    fresh = 0
    for sym in sample:
        raw = get_json_key(f"v2:market:ohlcv_closed:binance:{sym}:5m")
        candles = raw.get("candles") if isinstance(raw, dict) else (raw or [])
        opens = [int(c.get("open_time", 0)) for c in candles if isinstance(c, dict)]
        if opens and (now_ms - 300_000 - max(opens)) < 2.5 * 300_000:
            fresh += 1
    frac = fresh / len(sample) if sample else 0.0
    return {"ok": frac >= DATA_PLANE_MIN_FRESH_FRACTION,
            "detail": f"5m tail fresh {fresh}/{len(sample)} sampled ({frac:.0%}, need >= {DATA_PLANE_MIN_FRESH_FRACTION:.0%})",
            "universe_size": len(symbols)}


def check_evidence_plane() -> dict:
    ages = {}
    try:
        newest = max((p.stat().st_mtime for p in COMMISSION_CAS.rglob("*") if p.is_file()), default=0)
        ages["commission_cas_age_s"] = int(time.time() - newest) if newest else None
    except OSError:
        ages["commission_cas_age_s"] = None
    try:
        payload = json.loads(PUBLISHER_STATUS.read_text())
        cyc = payload.get("cycle_completed_at", "")
        age = (datetime.now(UTC) - datetime.fromisoformat(cyc.replace("Z", "+00:00"))).total_seconds() if cyc else None
        ages["profiled_publisher_cycle_age_s"] = int(age) if age is not None else None
    except Exception:
        ages["profiled_publisher_cycle_age_s"] = None
    cas_ok = ages["commission_cas_age_s"] is not None and ages["commission_cas_age_s"] < 3600
    return {"ok": bool(cas_ok), "detail": ages}


def check_serving() -> dict:
    status = get_json_key("v2:prediction_serving:status") or {}
    gen = status.get("generated_utc") or status.get("generated_at") or ""
    fresh = False
    if gen:
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(str(gen).replace("Z", "+00:00"))).total_seconds()
            fresh = age < 900
        except ValueError:
            fresh = False
    return {"ok": fresh, "detail": {"status_present": bool(status), "generated": gen,
            "records_published": status.get("records_published")}}


def check_paper_loop() -> dict:
    running = bool(sh(["pgrep", "-f", "v2_trade_management_paper_loop"]))
    return {"ok": running, "detail": "process present" if running else "paper loop process absent"}


def check_single_writers() -> dict:
    # Match only real python invocations of the serving module — a plain -f
    # pattern also matches transient shells that merely mention the name.
    serving_writers = sh(["bash", "-c",
                          "pgrep -cf 'python[0-9.]* .*v2_canonical_prediction_serving_runtime' || true"])
    count = int(serving_writers or 0)
    return {"ok": count == 1, "detail": {"canonical_serving_processes": count,
            "expected": "exactly one canonical prediction writer"}}


def credentialed_status(rows: list[dict]) -> dict:
    by_unit = {r["unit"]: r for r in rows}
    services = []
    for unit in credentialed_units():
        text = (UNIT_DIR / unit).read_text()
        cred_files = [seg.split(":", 1)[1] if ":" in seg else seg
                      for line in text.splitlines() if line.startswith("LoadCredential=")
                      for seg in [line.split("=", 1)[1]]]
        cred_files += [line.split("=", 1)[1] for line in text.splitlines()
                       if line.startswith("ConditionPathExists=") and ".cred" in line]
        present = all(os.path.exists(os.path.expanduser(f.replace("%h", str(Path.home()))))
                      for f in cred_files) if cred_files else None
        row = by_unit.get(unit, {})
        services.append({
            "unit": unit,
            "credential_names": [os.path.basename(f) for f in cred_files],
            "credential_files_present": present,
            "preflight_status": "CREDENTIALS_PRESENT" if present else "CREDENTIALS_REQUIRED",
            "active_state": row.get("active_state", "unknown"),
            "classification": row.get("classification"),
        })
    return {"schema_version": "v2_credentialed_services_status_v1",
            "generated_utc": utc_now(), "services": services}


def main() -> int:
    rows, failures = classify_units()
    checks = {
        "gpu": check_gpu(),
        "redis": check_redis(),
        "data_plane_freshness": check_data_plane(),
        "evidence_plane_freshness": check_evidence_plane(),
        "prediction_serving": check_serving(),
        "paper_loop": check_paper_loop(),
        "single_writers": check_single_writers(),
    }
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    payload = {
        "schema_version": "v2_boot_validation_v1",
        "generated_utc": utc_now(),
        "boot_id": sh(["cat", "/proc/sys/kernel/random/boot_id"]),
        "classification_counts": counts,
        "units": rows,
        "checks": checks,
        "failures": failures,
        "boot_validator_pass": not failures and all(c["ok"] for c in checks.values()),
        "manual_service_starts_required": [f["unit"] for f in failures],
        "live_gate": "blocked_human_only",
        "places_real_order": False,
    }
    redis_cli("SET", "v2:operations:boot_validation", json.dumps(payload))
    cred = credentialed_status(rows)
    redis_cli("SET", "v2:evidence:credentialed_services_status", json.dumps(cred))
    print(json.dumps({"boot_validator_pass": payload["boot_validator_pass"],
                      "classification_counts": counts,
                      "check_results": {k: v["ok"] for k, v in checks.items()},
                      "failures": failures}, indent=2))
    return 0 if payload["boot_validator_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
