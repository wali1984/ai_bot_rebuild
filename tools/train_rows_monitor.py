#!/usr/bin/env python3
"""Live train-rows runway monitor.

Shows the champion/challenger corpus runway in real time: train_rows vs the
1000 gate, the two blocker halves (cost-coverage + insufficient-rows), the
durable-ledger supply that grows train_rows, an instantaneous supply rate +
ETA, the trainer cycle state, and any errors.  Read-only; polls Redis + the
status files every 20s.  Ctrl-C to exit.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

try:
    import redis

    R = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_timeout=3)
except Exception:  # noqa: BLE001
    R = None

ROOT = "/home/wali/ai_bot_local_data/v2_native_trainer"
LEDGER = f"{ROOT}/durable_feature_snapshot_ledger.sqlite3"
PROFILED_STATUS = f"{ROOT}/local_profiled_research_v1/status.json"
BASE_PUB_STATUS = f"{ROOT}/profiled_base_publisher_v1/profiled_base_publisher_status_v1.json"
CC_KEY = "v2:trainer:champion_challenger_status"
CKPT_EVIDENCE_KEY = "v2:trainer:checkpoint:evidence"
RECOVERY_CKPT_META = "/home/wali/Desktop/AI BOT REBUILD/.local_models/paper_recovery/paper_recovery_checkpoint_v1.json"
TARGET_TRAIN = 1000
# Paper-recovery train gate — separate corpus (paper-only, non-promotable) and a
# far lower floor than the strict champion gate. 272 (recovery checkpoint) >= 256.
PAPER_RECOVERY_TARGET = 256
# Autonomous PAPER checkpoint gate — the SAME admitted-row corpus as the strict
# champion gate, at a lower threshold (paper-only, non-promotable, never-live).
PAPER_CHECKPOINT_TARGET = 100


def recovery_train_rows():
    """Actual recovery checkpoint train_rows (272), or None if absent."""
    try:
        with open(RECOVERY_CKPT_META) as fh:
            meta = json.load(fh)
        value = meta.get("train_rows")
        return int(value) if isinstance(value, (int, float)) else None
    except Exception:  # noqa: BLE001
        return None
# Empirical conversion (from the corpus map): committed ledger -> valid (~0.75)
# -> train (~0.4 of valid early, rising toward 0.7). ~3300 committed ~= 1000 train.
COMMITTED_FOR_TARGET = 3300

C = {
    "g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "c": "\033[96m",
    "b": "\033[1m", "d": "\033[2m", "x": "\033[0m",
}


def rget(key):
    if R is None:
        return {}
    try:
        raw = R.get(key)
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def rexists(key):
    try:
        return bool(R and R.exists(key))
    except Exception:  # noqa: BLE001
        return False


def jget(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def ledger_counts():
    try:
        c = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=3)
        rec = c.execute("SELECT COUNT(*) FROM feature_snapshot_records").fetchone()[0]
        rcpt = c.execute(
            "SELECT COUNT(*) FROM feature_snapshot_append_receipts"
        ).fetchone()[0]
        c.close()
        return rec, rcpt
    except Exception:  # noqa: BLE001
        return None, None


def bar(cur, target, width=44):
    cur = cur if isinstance(cur, (int, float)) else 0
    frac = min(1.0, cur / target) if target else 0.0
    filled = int(frac * width)
    color = C["g"] if frac >= 1.0 else C["y"] if frac >= 0.5 else C["c"]
    return f"{color}[{'#' * filled}{'-' * (width - filled)}]{C['x']} {cur}/{target} ({frac * 100:.1f}%)"


def age(iso):
    if not iso:
        return "?"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return f"{(datetime.now(timezone.utc) - t).total_seconds():.0f}s ago"
    except Exception:  # noqa: BLE001
        return str(iso)[:19]


prev_committed = None
prev_t = None
rates: list[float] = []

while True:
    os.system("clear")
    now = datetime.now(timezone.utc)
    cc = rget(CC_KEY)
    prof = jget(PROFILED_STATUS)
    base = jget(BASE_PUB_STATUS)
    rec, committed = ledger_counts()
    # Top-level train_rows is published now; fall back to the nested terminal
    # value so a real count shows even before the publisher republishes.
    train_rows = cc.get("train_rows")
    if train_rows is None:
        train_rows = (cc.get("backtests_processed") or {}).get("train_rows")
    blockers = cc.get("blocker_reasons") or []
    status = cc.get("status", "UNKNOWN")

    if committed is not None:
        t = time.time()
        if prev_committed is not None and prev_t is not None and t > prev_t:
            dh = (t - prev_t) / 3600.0
            if dh > 0:
                rates.append((committed - prev_committed) / dh)
                rates[:] = rates[-30:]
        prev_committed, prev_t = committed, t
    avg_rate = (sum(rates) / len(rates)) if rates else None

    print(f"{C['b']}{C['c']}══════ TRAIN-ROWS RUNWAY MONITOR ══════{C['x']}   {now.isoformat(timespec='seconds')}")
    print()
    # Paper-recovery gate (256) — separate paper-only corpus; must NOT wait on
    # the strict 1000 gate. Shown first so operators see paper recovery is unblocked.
    rec_tr = recovery_train_rows()
    rec_pass = rec_tr is not None and rec_tr >= PAPER_RECOVERY_TARGET
    rec_col = C["g"] if rec_pass else C["y"]
    rec_disp = f"{rec_tr if rec_tr is not None else '—'}/{PAPER_RECOVERY_TARGET}"
    print(f"{C['b']}PAPER RECOVERY GATE (need {PAPER_RECOVERY_TARGET}):{C['x']} "
          f"{rec_col}{rec_disp} {'PASS' if rec_pass else 'PENDING'}{C['x']} "
          f"{C['d']}(paper-only, non-promotable, independent of the 1000 champion gate){C['x']}")
    print()
    tr = train_rows if isinstance(train_rows, int) else 0
    # Autonomous PAPER checkpoint gate (100) — same admitted corpus, lower threshold.
    paper_req = cc.get("paper_train_rows_required") or PAPER_CHECKPOINT_TARGET
    paper_rem = cc.get("paper_train_rows_remaining")
    if paper_rem is None:
        paper_rem = max(0, paper_req - tr)
    paper_pass = tr >= paper_req
    paper_col = C["g"] if paper_pass else C["y"]
    print(f"{C['b']}PAPER CHECKPOINT GATE (need {paper_req}):{C['x']} "
          f"{paper_col}{tr}/{paper_req} {'PASS' if paper_pass else 'PENDING'}{C['x']} "
          f"{C['d']}(remaining {paper_rem}; paper-only, non-promotable, never live){C['x']}")
    print()
    print(f"{C['b']}STRICT CHAMPION GATE (need {TARGET_TRAIN}):{C['x']}")
    print("  " + bar(tr, TARGET_TRAIN) + f"   {C['d']}strict champion: {tr}/{TARGET_TRAIN} "
          f"(remaining {cc.get('strict_train_rows_remaining', TARGET_TRAIN - tr)}){C['x']}")
    if train_rows is None:
        print(f"  {C['y']}train_rows=None{C['x']} {C['d']}(no terminal manifest value yet this run){C['x']}")
    print()

    gate_col = C["g"] if not blockers else C["r"]
    print(f"{C['b']}CHAMPION/CHALLENGER GATE:{C['x']} {gate_col}{status}{C['x']}")
    cost_block = "ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE" in blockers
    rows_block = "INSUFFICIENT_TRAIN_ROWS" in blockers
    print(f"    cost-coverage half : "
          + (f"{C['r']}INCOMPLETE — blocks{C['x']}" if cost_block else f"{C['g']}OK{C['x']}"))
    print(f"    train-rows half    : "
          + (f"{C['r']}INSUFFICIENT — blocks{C['x']}" if rows_block else f"{C['g']}OK{C['x']}"))
    for b in blockers:
        if b not in ("ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE", "INSUFFICIENT_TRAIN_ROWS"):
            print(f"    {C['r']}other block{C['x']} {b}")
    # Prefer the published top-level field; fall back to the nested PIT path.
    latest_unclosed = cc.get("latest_unclosed_rejected_rows")
    if latest_unclosed is None:
        latest_unclosed = (cc.get("point_in_time_safety") or {}).get(
            "latest_unclosed_exclusion_unproven_rejected"
        )
    remaining = cc.get("strict_train_rows_remaining")
    ayr = cc.get("admission_yield_ratio")
    print(f"    {C['d']}best_challenger_id={cc.get('best_challenger_id')} "
          f"strict_remaining={remaining} admission_yield={ayr} "
          f"latest_unclosed_rejected={latest_unclosed} "
          f"scanned={cc.get('replay_snapshots_scanned')}{C['x']}")
    print()

    print(f"{C['b']}CORPUS SUPPLY (durable feature ledger — grows train_rows):{C['x']}")
    print(f"  records={rec}   committed={committed}   (need ~{COMMITTED_FOR_TARGET} committed for ~{TARGET_TRAIN} train)")
    if avg_rate and avg_rate > 0:
        need = max(0, COMMITTED_FOR_TARGET - (committed or 0))
        eta_h = need / avg_rate if need else 0.0
        print(f"  supply rate ≈ {C['c']}{avg_rate:.0f} committed/hr{C['x']}   "
              f"ETA to gate ≈ {C['c']}{eta_h:.1f}h{C['x']} ({eta_h / 24:.1f}d)")
    else:
        print(f"  {C['d']}measuring supply rate (needs 2+ polls)...{C['x']}")
    print()

    print(f"{C['b']}TRAINER CYCLE:{C['x']} {prof.get('classification', '?')}   "
          f"in_progress={prof.get('cycle_in_progress')}   sha={str(prof.get('code_sha', '?'))[:10]}")
    err = prof.get("error") or {}
    if err:
        print(f"    {C['r']}ERROR{C['x']} {json.dumps(err)[:140]}")
    rd = base.get("resource_decision", {}) if isinstance(base, dict) else {}
    print(f"  base publisher: selected/cycle={rd.get('selected_count', '?')} "
          f"eligible={rd.get('discovered_eligible_count', '?')} "
          f"class={str(base.get('classification', '?'))[:38]}")
    print(f"  RL checkpoint evidence key present: "
          + (f"{C['g']}YES{C['x']}" if rexists(CKPT_EVIDENCE_KEY) else f"{C['r']}NO — RL predictions blocked until a champion is promoted{C['x']}"))
    print()
    print(f"{C['d']}refresh 20s · read-only · Ctrl-C to exit{C['x']}")
    time.sleep(20)
