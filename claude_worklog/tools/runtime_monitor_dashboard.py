#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple


MONITOR_TMUX_SESSION = "ai_bot_read_only_monitor"
FORBIDDEN_TERMS = [
    "xadd",
    "set ",
    "hset",
    "lpush",
    "rpush",
    "publish",
    "order",
    "leverage",
    "margin",
    "cancel",
    "place",
]


@dataclass
class CmdResult:
    ok: bool
    out: str
    err: str
    code: int


def run_cmd(cmd, timeout=10) -> CmdResult:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return CmdResult(proc.returncode == 0, (proc.stdout or "").strip(), (proc.stderr or "").strip(), proc.returncode)
    except FileNotFoundError:
        return CmdResult(False, "", "not found", 127)
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", "timeout", 124)
    except Exception as exc:  # pragma: no cover
        return CmdResult(False, "", str(exc), 1)


def parse_iso_ts(value: str) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None


def parse_epochish(value) -> Optional[datetime]:
    try:
        f = float(value)
    except Exception:
        return None
    if f > 1e12:
        f = f / 1000.0
    if f < 0:
        return None
    try:
        return datetime.fromtimestamp(f, tz=timezone.utc)
    except Exception:
        return None


def extract_ts_from_json_obj(obj: Dict) -> Optional[datetime]:
    keys = [
        "ts",
        "ts_utc",
        "timestamp",
        "timestamp_utc",
        "timestamp_iso",
        "timestamp_ms",
        "created_at",
        "created_ts",
        "created_ts_ms",
        "ts_ms",
        "time",
    ]
    for k in keys:
        if k not in obj:
            continue
        v = obj.get(k)
        if isinstance(v, (int, float)):
            dt = parse_epochish(v)
            if dt:
                return dt
        elif isinstance(v, str):
            dt = parse_iso_ts(v) or parse_epochish(v)
            if dt:
                return dt
    return None


def read_jsonl_stats(path: Path) -> Tuple[int, Optional[datetime], Optional[datetime], int]:
    count = 0
    parse_errors = 0
    first_ts = None
    last_ts = None
    if not path.exists():
        return count, first_ts, last_ts, parse_errors
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                count += 1
                try:
                    obj = json.loads(line)
                    ts = extract_ts_from_json_obj(obj)
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                except Exception:
                    parse_errors += 1
    except Exception:
        return 0, None, None, 1
    return count, first_ts, last_ts, parse_errors


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def detect_tmux_session(name: str) -> bool:
    r = run_cmd(["tmux", "has-session", "-t", name], timeout=5)
    return r.ok


def detect_monitor_process() -> bool:
    r = run_cmd(["pgrep", "-af", "read_only_monitor.py"], timeout=5)
    if not r.ok:
        return False
    return any("read_only_monitor.py" in ln for ln in r.out.splitlines())


def parse_ollama_status(path: Path) -> str:
    txt = read_text(path)
    m = re.search(r"(OLLAMA_[A-Z0-9_]+)", txt)
    return m.group(1) if m else "UNKNOWN"


def parse_feature_classification(path: Path) -> str:
    txt = read_text(path)
    for token in ["FEATURE_KEY_MONITORING_PARTIAL", "FEATURE_KEY_MONITORING_COMPLETE", "FEATURE_KEY_MONITORING_MISSING"]:
        if token in txt:
            return token
    return "UNKNOWN"


def parse_log_health(log_text: str) -> Tuple[int, int]:
    crit = 0
    parse = 0
    for ln in log_text.splitlines():
        u = ln.upper()
        if "CRITICAL" in u or "TRACEBACK" in u or "FATAL" in u:
            crit += 1
        if "PARSE" in u and "ERROR" in u:
            parse += 1
    return crit, parse


def boundary_warning(log_text: str, script_text: str) -> bool:
    merged = (log_text + "\n" + script_text).lower()
    return any(term in merged for term in FORBIDDEN_TERMS)


def redis_info() -> Dict[str, str]:
    if shutil.which("redis-cli") is None:
        return {
            "ping": "UNKNOWN",
            "used": "UNKNOWN",
            "max": "UNKNOWN",
            "ratio": "UNKNOWN",
            "warn": "NO",
        }
    ping = run_cmd(["redis-cli", "PING"], timeout=5)
    info = run_cmd(["redis-cli", "INFO", "memory"], timeout=8)
    used = "UNKNOWN"
    maxm = "UNKNOWN"
    ratio = "UNKNOWN"
    warn = "NO"
    if info.ok:
        mem = {}
        for ln in info.out.splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                mem[k.strip()] = v.strip()
        used = mem.get("used_memory_human", mem.get("used_memory", "UNKNOWN"))
        maxm = mem.get("maxmemory_human", mem.get("maxmemory", "UNKNOWN"))
        try:
            used_raw = float(mem.get("used_memory", "0"))
            max_raw = float(mem.get("maxmemory", "0"))
            if max_raw > 0:
                pct = (used_raw / max_raw) * 100.0
                ratio = f"{pct:.2f}%"
                if pct > 90.0:
                    warn = "YES"
        except Exception:
            pass
    return {
        "ping": ping.out if ping.ok else "UNKNOWN",
        "used": used,
        "max": maxm,
        "ratio": ratio,
        "warn": warn,
    }


def read_meminfo() -> Dict[str, str]:
    mi = Path("/proc/meminfo")
    if not mi.exists():
        return {
            "ram_total": "UNKNOWN",
            "ram_avail": "UNKNOWN",
            "ram_used_pct": "UNKNOWN",
            "swap_total": "UNKNOWN",
            "swap_free": "UNKNOWN",
            "swap_used_pct": "UNKNOWN",
        }
    vals = {}
    for ln in read_text(mi).splitlines():
        if ":" not in ln:
            continue
        k, rest = ln.split(":", 1)
        parts = rest.strip().split()
        if parts:
            try:
                vals[k] = int(parts[0])
            except Exception:
                pass
    kb = 1024
    total = vals.get("MemTotal", 0)
    avail = vals.get("MemAvailable", 0)
    swap_total = vals.get("SwapTotal", 0)
    swap_free = vals.get("SwapFree", 0)
    used = max(total - avail, 0)
    ram_pct = (used / total * 100.0) if total else None
    swap_used = max(swap_total - swap_free, 0)
    swap_pct = (swap_used / swap_total * 100.0) if swap_total else 0.0
    gib = 1024 * 1024
    return {
        "ram_total": f"{total / gib:.2f} GiB" if total else "UNKNOWN",
        "ram_avail": f"{avail / gib:.2f} GiB" if total else "UNKNOWN",
        "ram_used_pct": f"{ram_pct:.2f}%" if ram_pct is not None else "UNKNOWN",
        "swap_total": f"{swap_total / gib:.2f} GiB" if swap_total else "0.00 GiB",
        "swap_free": f"{swap_free / gib:.2f} GiB" if swap_total else "0.00 GiB",
        "swap_used_pct": f"{swap_pct:.2f}%",
        "ram_avail_kib": str(avail),
    }


def pia_status() -> Dict[str, str]:
    if shutil.which("piactl") is None:
        return {"state": "UNKNOWN", "region": "UNKNOWN", "vpnip": "UNKNOWN"}
    def get(cmd):
        r = run_cmd(["piactl", "get", cmd], timeout=5)
        return r.out if r.ok and r.out else "UNKNOWN"
    return {"state": get("connectionstate"), "region": get("region"), "vpnip": get("vpnip")}


def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "UNKNOWN"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def recommendation(natural_done: bool, elapsed_h: float, fresh: bool, crit: int, stale: bool, monitor_ok: bool,
                   redis_ratio: str, ram_avail_kib: int, parse_errors: int, target_hours: float) -> str:
    if natural_done:
        return "NATURALLY_COMPLETED"
    redis_bad = False
    if isinstance(redis_ratio, str) and redis_ratio.endswith("%"):
        try:
            redis_bad = float(redis_ratio[:-1]) > 95.0
        except Exception:
            redis_bad = False
    parse_bad = parse_errors >= 10
    ram_bad = ram_avail_kib < (10 * 1024 * 1024)
    if stale or (not monitor_ok) or crit > 0 or redis_bad or ram_bad or parse_bad:
        return "ATTENTION_REQUIRED"
    if elapsed_h >= target_hours and fresh and crit == 0:
        return "STOP_READY"
    return "CONTINUE_GOOD"


def print_dashboard(root: Path, refresh_seconds: int, target_hours: float, min_hours: float):
    mon_dir = root / "claude_worklog" / "monitoring"
    ollama_path = root / "claude_worklog" / "ollama" / "OLLAMA_STATUS.md"
    snap_path = mon_dir / "snapshots.jsonl"
    metrics_path = mon_dir / "trainer_metrics.jsonl"
    log_path = mon_dir / "read_only_monitor.log"
    midrun_path = mon_dir / "RUNTIME_MONITOR_MIDRUN_CHECK.md"
    gap_path = mon_dir / "FEATURE_KEY_MONITORING_GAP_AUDIT.md"
    natural_summary = root / "claude_worklog" / "monitoring_summary.md"

    snap_count, first_ts, last_ts, snap_parse_err = read_jsonl_stats(snap_path)
    metrics_count, _, _, metrics_parse_err = read_jsonl_stats(metrics_path)
    parse_errors = snap_parse_err + metrics_parse_err

    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)
    elapsed_h = 0.0
    if first_ts and last_ts:
        if first_ts.tzinfo is None:
            first_ts = first_ts.replace(tzinfo=timezone.utc)
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        elapsed_h = max((last_ts - first_ts).total_seconds() / 3600.0, 0.0)

    elapsed_minutes = elapsed_h * 60.0
    expected_count = int(round(elapsed_minutes / 0.5)) if elapsed_minutes > 0 else 0
    completeness = min((elapsed_h / target_hours) * 100.0, 999.0) if target_hours > 0 else 0.0

    tmux_ok = detect_tmux_session(MONITOR_TMUX_SESSION)
    proc_ok = detect_monitor_process()
    natural_done = natural_summary.exists()

    stale = True
    fresh = False
    if last_ts:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age = (now_utc - last_ts.astimezone(timezone.utc)).total_seconds()
        stale = age > 180
        fresh = not stale

    log_text = read_text(log_path)
    crit_count, parse_err_log = parse_log_health(log_text)
    parse_errors += parse_err_log

    script_text = read_text(root / "claude_worklog" / "tools" / "read_only_monitor.py")
    boundary_warn = boundary_warning(log_text, script_text)

    redis = redis_info()
    mem = read_meminfo()
    pia = pia_status()
    ollama = parse_ollama_status(ollama_path)
    feature_class = parse_feature_classification(gap_path)

    try:
        ram_avail_kib = int(mem.get("ram_avail_kib", "0"))
    except Exception:
        ram_avail_kib = 0

    rec = recommendation(
        natural_done=natural_done,
        elapsed_h=elapsed_h,
        fresh=fresh,
        crit=crit_count,
        stale=stale,
        monitor_ok=(tmux_ok and proc_ok),
        redis_ratio=redis.get("ratio", "UNKNOWN"),
        ram_avail_kib=ram_avail_kib,
        parse_errors=parse_errors,
        target_hours=target_hours,
    )

    os.system("clear")
    print("AI BOT Read-Only Runtime Monitor Dashboard")
    print("=" * 72)
    print(f"Local time: {now_local.isoformat()}")
    print(f"UTC time:   {now_utc.isoformat()}")
    print(f"Target hours: {target_hours} | Minimum hours: {min_hours} | Refresh: {refresh_seconds}s")
    print()

    print("[1] Monitor status")
    print(f"tmux session present: {'YES' if tmux_ok else 'NO'}")
    print(f"monitor process present: {'YES' if proc_ok else 'NO'}")
    print(f"natural completion summary exists: {'YES' if natural_done else 'NO'}")
    print()

    print("[2] Runtime progress")
    print(f"first snapshot timestamp: {fmt_dt(first_ts)}")
    print(f"last snapshot timestamp:  {fmt_dt(last_ts)}")
    print(f"elapsed hours: {elapsed_h:.2f}")
    print(f"snapshots count: {snap_count}")
    print(f"expected count (~30s cadence): {expected_count}")
    print(f"trainer metrics count: {metrics_count}")
    print(f"completeness to target: {completeness:.2f}%")
    print()

    print("[3] Health")
    print(f"snapshot freshness: {'STALE' if stale else 'FRESH'}")
    print(f"monitor log critical error count: {crit_count}")
    print(f"parse error count: {parse_errors}")
    print(f"read-only boundary warning: {'YES' if boundary_warn else 'NO'}")
    print()

    print("[4] Redis")
    print(f"PING: {redis.get('ping', 'UNKNOWN')}")
    print(f"used memory: {redis.get('used', 'UNKNOWN')}")
    print(f"maxmemory: {redis.get('max', 'UNKNOWN')}")
    print(f"memory ratio: {redis.get('ratio', 'UNKNOWN')}")
    print(f"memory > 90% warning: {redis.get('warn', 'NO')}")
    print()

    print("[5] System")
    print(f"RAM total: {mem.get('ram_total', 'UNKNOWN')}")
    print(f"RAM available: {mem.get('ram_avail', 'UNKNOWN')}")
    print(f"RAM used percent: {mem.get('ram_used_pct', 'UNKNOWN')}")
    print(f"Swap total: {mem.get('swap_total', 'UNKNOWN')}")
    print(f"Swap free: {mem.get('swap_free', 'UNKNOWN')}")
    print(f"Swap used percent: {mem.get('swap_used_pct', 'UNKNOWN')}")
    print()

    print("[6] PIA")
    print(f"state: {pia.get('state', 'UNKNOWN')}")
    print(f"region: {pia.get('region', 'UNKNOWN')}")
    print(f"vpnip: {pia.get('vpnip', 'UNKNOWN')}")
    print()

    print("[7] Feature visibility")
    print(f"classification: {feature_class}")
    print(f"ollama status: {ollama}")
    print()

    print("[8] Recommendation")
    print(f"status: {rec}")
    if rec == "CONTINUE_GOOD":
        print("Next action: Keep monitor running.")
    elif rec == "STOP_READY":
        print("Next action: tmux send-keys -t ai_bot_read_only_monitor C-c")
    elif rec == "NATURALLY_COMPLETED":
        print("Next action: Do not stop; proceed to post-monitor analysis.")
    else:
        print("Next action: Do not build V2; inspect logs before stopping.")
    print()
    print(f"midrun report exists: {'YES' if midrun_path.exists() else 'NO'}")
    print("=" * 72)

    return {
        "recommendation": rec,
        "elapsed_h": elapsed_h,
        "snap_count": snap_count,
        "metrics_count": metrics_count,
        "redis_ratio": redis.get("ratio", "UNKNOWN"),
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only runtime monitor dashboard")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--refresh-seconds", type=int, default=15)
    parser.add_argument("--target-hours", type=float, default=16)
    parser.add_argument("--min-hours", type=float, default=12)
    parser.add_argument("--once", action="store_true", help="Print dashboard once and exit")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.once:
        print_dashboard(root, args.refresh_seconds, args.target_hours, args.min_hours)
        return 0
    while True:
        print_dashboard(root, args.refresh_seconds, args.target_hours, args.min_hours)
        time.sleep(max(args.refresh_seconds, 1))


if __name__ == "__main__":
    sys.exit(main())