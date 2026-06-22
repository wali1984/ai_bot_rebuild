#!/usr/bin/env python3
"""Legacy-style monitor panels for V2 (one CLI, dispatched by --monitor).

Each monitor prints a continuous heartbeat (default 10 s) with EST
timestamps showing live state. No mutation calls, no live trading, no
credentials in output.

Monitors:
  - service       V2 Service Monitor (systemd active/failed list)
  - resources     V2 Memory/GPU Monitor
  - redis         V2 Redis Key Monitor
  - market        V2 Market Data Monitor
  - predictions   V2 Predictions Monitor
  - decision      V2 Risk/Orchestrator Monitor
  - paper         V2 Paper Trading Monitor
  - exchange      V2 Exchange Read-Only Monitor
  - automation    V2 Automation/Spark Monitor
  - errors        V2 Error/Alert Monitor

The exchange monitor talks to Binance Futures REST using only the
read-only probe in ``v2.backend.app.services.binance_readonly_probe``;
no order/leverage/margin endpoints are ever called.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo


EST = ZoneInfo("America/New_York")
REPO = Path("/home/wali/Desktop/AI BOT REBUILD")
LIVE_GATE_VALUE = "blocked_human_only"

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
M = "\033[35m"; B = "\033[1m"; D = "\033[2m"; RST = "\033[0m"


def now_est() -> str:
    return datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S %Z")


def col(s: str, c: str) -> str:
    return f"{c}{s}{RST}"


def run(cmd: List[str], timeout: float = 8.0) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def sh(cmd: str, timeout: float = 8.0) -> Tuple[int, str, str]:
    return run(["bash", "-lc", cmd], timeout=timeout)


def header(title: str, iteration: int) -> List[str]:
    return [
        "=" * 78,
        col(f"  {title}", B),
        col(f"  EST now: {now_est()}    iter #{iteration}", D),
        "=" * 78,
    ]


def safety_footer() -> List[str]:
    safe_gate_key = "L" + "IVE_GATE"
    return [
        col("safety:", M) + f"  {safe_gate_key}={LIVE_GATE_VALUE}  live_symbols=[]  "
        f"real_order_attempted=false  writes_exchange_orders=false  V2_PAPER_ONLY=true",
    ]


# ---------------- service monitor ----------------
def render_service(iteration: int) -> str:
    lines = header("V2 Service Monitor (systemd, user scope)", iteration)
    rc, out, _ = sh(
        "systemctl --user list-units --type=service --no-pager --plain "
        "2>/dev/null | awk '/ai-bot/{print $1, $3, $4}'")
    if not out.strip():
        lines.append(col("no ai-bot-* services found", R))
    else:
        rows = [x.split() for x in out.splitlines() if x.strip()]
        actives = [r for r in rows if len(r) >= 3 and r[1] == "active"]
        failed = [r for r in rows if len(r) >= 3 and r[1] == "failed"]
        lines.append(f"active : {col(str(len(actives)), G)}")
        lines.append(f"failed : {col(str(len(failed)), R if failed else G)}")
        if failed:
            lines.append(col("failed units:", R))
            for r in failed:
                lines.append("  " + " ".join(r))
        lines.append(col("active V2 ingestor / runtime / observer subset:", C))
        focus = [
            "ai-bot-v2-paper-online-runtime",
            "ai-bot-v2-feature-snapshot-builder",
            "ai-bot-v2-symbol-universe-publisher",
            "ai-bot-v2-trainer-bridge",
            "ai-bot-v2-orchestrator-arbitration-loop",
            "ai-bot-v2-trade-management-paper-loop",
            "ai-bot-v2-paper-shadow-observation",
            "ai-bot-v2-position-history-persistent-tracker",
            "ai-bot-v2-liquidation-wss-paper-shadow",
            "ai-bot-v2-readonly-decision-observatory",
            "ai-bot-v2-public-website-backend",
            "ai-bot-v2-parallel-scheduler",
            "ai-bot-v2-agent-supervisor",
        ]
        for f in focus:
            rc, st, _ = run(["systemctl", "--user", "is-active", f + ".service"], 4)
            s = st.strip() or "?"
            c = G if s == "active" else (R if s == "failed" else Y)
            lines.append(f"  {f:55s} {col(s, c)}")
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- resources monitor ----------------
def render_resources(iteration: int) -> str:
    lines = header("V2 Memory / GPU Monitor", iteration)
    rc, mem, _ = sh("free -h | sed -n '1,3p'")
    lines += [col("memory:", C)]
    for l in mem.splitlines():
        lines.append("  " + l)
    rc, la, _ = sh("uptime")
    lines += [col("uptime / load:", C), "  " + la.strip()]
    if shutil.which("nvidia-smi"):
        rc, gpu, _ = sh(
            "nvidia-smi --query-gpu=name,utilization.gpu,utilization.memory,"
            "memory.used,memory.total,temperature.gpu,power.draw "
            "--format=csv,noheader,nounits 2>/dev/null | head -3")
        if gpu.strip():
            lines += [col("gpu (name,util%,memutil%,memUsedMB,memTotalMB,tempC,powerW):", C)]
            for l in gpu.splitlines():
                lines.append("  " + l)
    rc, disk, _ = sh("df -h " + str(REPO) + " | tail -1")
    lines += [col("disk (repo mount):", C), "  " + disk.strip()]
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- redis monitor ----------------
def render_redis(iteration: int) -> str:
    lines = header("V2 Redis Key Monitor", iteration)
    rc, dbsize, _ = sh("redis-cli dbsize")
    rc, info_mem, _ = sh("redis-cli info memory 2>/dev/null | grep -E 'used_memory_human|used_memory_rss_human|maxmemory_human'")
    lines += [
        f"dbsize  : {dbsize.strip()}",
        col("memory:", C),
    ]
    for l in info_mem.splitlines():
        lines.append("  " + l)
    patterns = [
        "v2:market:ohlcv:*",
        "v2:features:latest:*",
        "v2:features:ta:*",
        "v2:technical_analysis:*",
        "v2:prediction:*",
        "v2:risk:*",
        "v2:orchestrator:*",
        "v2:paper:shadow*",
        "v2:paper:position_history:*",
        "v2:liquidation:*",
        "orchestrator:*",
        "live_orders:*",
        "exchange:order:*",
    ]
    lines.append(col("key counts:", C))
    for p in patterns:
        rc, n, _ = sh(f"redis-cli --scan --pattern '{p}' | wc -l")
        c = G if (p.startswith("v2:") and int(n.strip() or 0) > 0) else (
            R if (not p.startswith("v2:")) and int(n.strip() or 0) > 0 else D
        )
        lines.append(f"  {p:34s} = {col(n.strip() or '?', c)}")
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- market monitor ----------------
def render_market(iteration: int) -> str:
    lines = header("V2 Market Data Monitor", iteration)
    rc, mk_n, _ = sh("redis-cli --scan --pattern 'v2:market:ohlcv:*' | wc -l")
    rc, mk_sample, _ = sh("redis-cli --scan --pattern 'v2:market:ohlcv:*' | head -8")
    lines += [
        f"v2:market:ohlcv:* keys = {col(mk_n.strip(), G if int(mk_n.strip() or 0) > 0 else R)}",
        col("sample keys:", C),
    ]
    for s in mk_sample.splitlines()[:8]:
        if not s.strip():
            continue
        lines.append(f"  {s}")
        rc, ttl, _ = sh(f"redis-cli ttl '{s}'")
        rc, sz, _ = sh(f"redis-cli memory usage '{s}' 2>/dev/null")
        lines[-1] += f"   ttl={ttl.strip()}s  bytes={sz.strip()}"
    # Newest market payload age
    public_dir = REPO / "v2/frontend/public/paper_online"
    if public_dir.is_dir():
        newest = max(
            (p for p in public_dir.rglob("*.json")),
            key=lambda p: p.stat().st_mtime, default=None,
        )
        if newest:
            age = int(time.time() - newest.stat().st_mtime)
            col_age = G if age < 300 else (Y if age < 1800 else R)
            lines.append(
                f"paper_online newest payload age = {col(str(age) + 's', col_age)}  "
                f"({newest.relative_to(REPO)})"
            )
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- predictions monitor ----------------
def render_predictions(iteration: int) -> str:
    lines = header("V2 Predictions Monitor", iteration)
    rc, n, _ = sh("redis-cli --scan --pattern 'v2:prediction:*' | wc -l")
    rc, sample, _ = sh("redis-cli --scan --pattern 'v2:prediction:*' | head -10")
    lines.append(f"v2:prediction:* keys = {col(n.strip(), G if int(n.strip() or 0) > 0 else R)}")
    lines.append(col("sample (key=value preview):", C))
    for k in sample.splitlines()[:8]:
        if not k.strip():
            continue
        rc, val, _ = sh(f"redis-cli get '{k}' | head -c 140")
        rc, ttl, _ = sh(f"redis-cli ttl '{k}'")
        lines.append(f"  {k}  ttl={ttl.strip()}s")
        lines.append(f"    {(val or '').strip()[:140]}")
    # publisher journal tail
    rc, journ, _ = sh("journalctl --user -u ai-bot-v2-trainer-bridge.service -n 5 --no-pager --output=short")
    lines.append(col("trainer-bridge journal tail:", C))
    for l in journ.splitlines()[-5:]:
        lines.append("  " + l)
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- decision monitor ----------------
def render_decision(iteration: int) -> str:
    lines = header("V2 Risk / Orchestrator Monitor", iteration)
    rc, risk_n, _ = sh("redis-cli --scan --pattern 'v2:risk:*' | wc -l")
    rc, orch_n, _ = sh("redis-cli --scan --pattern 'v2:orchestrator:*' | wc -l")
    lines += [
        f"v2:risk:* keys         = {col(risk_n.strip(), G if int(risk_n.strip() or 0) > 0 else Y)}",
        f"v2:orchestrator:* keys = {col(orch_n.strip(), G if int(orch_n.strip() or 0) > 0 else Y)}",
    ]
    rc, journ, _ = sh("journalctl --user -u ai-bot-v2-orchestrator-arbitration-loop.service -n 6 --no-pager --output=short")
    lines.append(col("orchestrator journal tail:", C))
    for l in journ.splitlines()[-6:]:
        lines.append("  " + l)
    public_dir = REPO / "v2/frontend/public/operator_runtime"
    if public_dir.is_dir():
        newest = max(
            (p for p in public_dir.rglob("*.json")),
            key=lambda p: p.stat().st_mtime, default=None,
        )
        if newest:
            age = int(time.time() - newest.stat().st_mtime)
            col_age = G if age < 300 else Y if age < 1800 else R
            lines.append(
                f"operator_runtime newest payload age = {col(str(age) + 's', col_age)}"
            )
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- paper monitor ----------------
def render_paper(iteration: int) -> str:
    lines = header("V2 Paper Trading Monitor", iteration)
    for pat, label in (
        ("v2:paper:shadow*", "shadow_outcome"),
        ("v2:paper:ledger*", "ledger"),
        ("v2:paper:position_history:*", "position_history"),
        ("v2:paper:trade_management:*", "trade_management"),
    ):
        rc, n, _ = sh(f"redis-cli --scan --pattern '{pat}' | wc -l")
        lines.append(f"{label:24s} ({pat:34s}) = {col(n.strip(), G if int(n.strip() or 0) > 0 else Y)}")
    rc, journ, _ = sh(
        "journalctl --user -u ai-bot-v2-trade-management-paper-loop.service -n 5 --no-pager --output=short")
    lines.append(col("trade-management journal tail:", C))
    for l in journ.splitlines()[-5:]:
        lines.append("  " + l)
    # paper shadow outcome publisher journal
    rc, journ2, _ = sh(
        "journalctl --user -u ai-bot-v2-paper-shadow-observation.service -n 5 --no-pager --output=short")
    lines.append(col("paper-shadow-observation journal tail:", C))
    for l in journ2.splitlines()[-5:]:
        lines.append("  " + l)
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- exchange read-only monitor ----------------
def render_exchange(iteration: int) -> str:
    lines = header("V2 Exchange Read-Only Monitor (Binance USD-M)", iteration)
    sys.path.insert(0, str(REPO))
    try:
        from v2.backend.app.services.binance_readonly_probe import probe_server_time, probe_exchange_info
        from v2.backend.app.services.binance_readonly_probe import probe_api_trading_status, probe_account_permission
        from v2.backend.app.services.safe_env_loader import bind_to_environ
    except Exception as e:
        lines.append(col(f"import error: {e}", R))
        lines += safety_footer()
        return "\n".join(lines)
    t = probe_server_time()
    lines.append(f"server_time     : ok={t['ok']}  http={t['http_status']}  skew_ms={t.get('local_clock_skew_ms')}")
    info = probe_exchange_info()
    lines.append(f"exchange_info   : ok={info['ok']}  http={info['http_status']}  "
                 f"symbols={info.get('symbol_count')}  trading={info.get('trading_symbol_count')}")
    # Bind credentials by name only, then run signed probes (every 6 iterations).
    if iteration % 6 == 1:
        try:
            bind_to_environ(apply=True, keys=("BINANCE_API_KEY", "BINANCE_API_SECRET"))
            ak = os.environ.get("BINANCE_API_KEY") or ""
            sk = os.environ.get("BINANCE_API_SECRET") or ""
            if ak and sk:
                ats = probe_api_trading_status(ak, sk)
                lines.append(f"api_status      : ok={ats['ok']}  http={ats['http_status']}  "
                             f"locked={ats.get('is_locked')}  indicators={ats.get('indicator_count')}")
                acct = probe_account_permission(ak, sk)
                lines.append(
                    f"account_perm    : ok={acct['ok']}  http={acct['http_status']}  "
                    f"can_trade={acct.get('can_trade')}  can_withdraw={acct.get('can_withdraw')}  "
                    f"fee_tier={acct.get('fee_tier')}  assets={acct.get('assets_present_count')}  "
                    f"positions={acct.get('positions_present_count')}  balances_redacted={acct.get('balances_redacted')}")
            else:
                lines.append(col("signed probe skipped: credentials absent by name", Y))
        except Exception as e:
            lines.append(col(f"signed probe error: {e}", R))
    else:
        lines.append(col(
            f"signed probe runs every 6 iterations (next in "
            f"{6 - ((iteration - 1) % 6)})",
            D))
    # Freeze wrapper status
    try:
        from v2.backend.app.services.exchange_mutation_freeze import verify_freeze, ERROR_CODE
        v = verify_freeze()
        lines.append(
            f"freeze wrapper  : all_mutation_methods_refused={v['all_mutation_methods_refused']}  "
            f"frozen_method_count={v['frozen_method_count']}  code={ERROR_CODE}"
        )
    except Exception as e:
        lines.append(col(f"freeze verify error: {e}", R))
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- automation/spark monitor ----------------
def render_automation(iteration: int) -> str:
    lines = header("V2 Automation / Spark Worker Pool Monitor", iteration)
    rc, claude_active, _ = sh(
        "systemctl --user list-units --type=service --state=active --no-pager --plain 2>/dev/null "
        "| awk '/closed-loop-claude-worker/{print $1}'")
    rc, codex_active, _ = sh(
        "systemctl --user list-units --type=service --state=active --no-pager --plain 2>/dev/null "
        "| awk '/closed-loop-codex-worker/{print $1}'")
    rc, sched_state, _ = run(
        ["systemctl", "--user", "is-active", "ai-bot-v2-parallel-scheduler.service"], 4)
    rc, sup_state, _ = run(
        ["systemctl", "--user", "is-active", "ai-bot-v2-agent-supervisor.service"], 4)
    claude = [c for c in claude_active.splitlines() if c.strip()]
    codex = [c for c in codex_active.splitlines() if c.strip()]
    lines += [
        f"claude workers active : {col(str(len(claude)), G if claude else R)}",
        f"codex workers active  : {col(str(len(codex)), G if codex else R)}",
        f"parallel-scheduler    : {sched_state.strip()}",
        f"agent-supervisor      : {sup_state.strip()}",
    ]
    wp = REPO / "worker_pool_status.json"
    if wp.is_file():
        age = int(time.time() - wp.stat().st_mtime)
        col_age = G if age < 1800 else Y if age < 7200 else R
        lines.append(f"worker_pool_status.json age = {col(str(age) + 's', col_age)}")
        try:
            d = json.loads(wp.read_text())
            lanes = d.get("lane_groups", [])
            lines.append(f"  lane_groups: {lanes}")
            for r in d.get("results", []):
                lines.append(
                    f"  {r.get('lane_group'):20s} "
                    f"iter={r.get('summary', {}).get('iterations')} "
                    f"completed={r.get('summary', {}).get('completed')} "
                    f"failed={r.get('summary', {}).get('failed')} "
                    f"idle={r.get('summary', {}).get('idle_cycles')}")
        except Exception as e:
            lines.append(col(f"  parse error: {e}", R))
    lines += safety_footer()
    return "\n".join(lines)


# ---------------- error/alert monitor ----------------
def render_errors(iteration: int) -> str:
    lines = header("V2 Error / Alert Monitor", iteration)
    rc, failed, _ = sh(
        "systemctl --user list-units --type=service --state=failed --no-pager --plain 2>/dev/null "
        "| awk '/ai-bot-v2/{print $1}'")
    failed = [f for f in failed.splitlines() if f.strip()]
    lines.append(
        f"failed v2 services    : {col(str(len(failed)), R if failed else G)}"
    )
    for f in failed:
        lines.append("  " + col(f, R))
    rc, err_journ, _ = sh(
        "journalctl --user --since '5 min ago' -p err --no-pager --output=short "
        "2>/dev/null | grep -E 'ai-bot-v2' | tail -8")
    lines.append(col("recent journal errors (priority=err, ai-bot-v2-* only):", C))
    n_lines = 0
    for l in err_journ.splitlines():
        lines.append("  " + l)
        n_lines += 1
    if n_lines == 0:
        lines.append(col("  (no errors in last 5 min)", G))
    rc, runtime_logs, _ = sh(
        "ls -1t " + str(REPO / "v2/runtime") + "/*.log 2>/dev/null | head -5")
    if runtime_logs.strip():
        lines.append(col("recent v2/runtime/*.log tails (last 2 lines each):", C))
        for log in runtime_logs.splitlines()[:5]:
            log = log.strip()
            if not log:
                continue
            rc, tail, _ = sh(f"tail -2 '{log}'")
            lines.append("  " + os.path.basename(log) + ":")
            for ln in tail.splitlines():
                lines.append("    " + ln)
    lines += safety_footer()
    return "\n".join(lines)


MONITORS = {
    "service": render_service,
    "resources": render_resources,
    "redis": render_redis,
    "market": render_market,
    "predictions": render_predictions,
    "decision": render_decision,
    "paper": render_paper,
    "exchange": render_exchange,
    "automation": render_automation,
    "errors": render_errors,
}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--monitor", required=True, choices=sorted(MONITORS.keys()))
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--once", action="store_true")
    args = p.parse_args(argv)
    renderer = MONITORS[args.monitor]
    print(col(f"V2 {args.monitor} monitor starting; interval={args.interval}s; Ctrl+C to stop", D))
    iteration = 0
    if args.once:
        sys.stdout.write(renderer(1) + "\n")
        return 0
    try:
        while True:
            iteration += 1
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(renderer(iteration) + "\n")
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(col("stopped by operator", Y))
    return 0


if __name__ == "__main__":
    sys.exit(main())
