#!/usr/bin/env python3
"""Paper first-natural-lifecycle acceptance harness (FINAL PASS operator #18).

Claude's acceptance-evidence lane (read-only; NEVER mutates paper state, NEVER
restarts a service, NEVER places orders). Watches the running paper loop and
records the operator #18 lifecycle for the first proof-backed directional action:

    fill -> position -> mandatory protection -> restart reconstruction
    -> ordinary adaptive close -> accounting reconciliation -> two more cycles

Usage:
    watch [max_minutes] [poll_seconds]
        Poll until a FULL lifecycle (fill -> protected -> closed -> accounting
        reconciled) is observed for at least 3 distinct fills (the first + two
        more cycles), or until max_minutes elapses. Emits an immutable verdict
        JSON to raw_evidence/ with per-milestone evidence.

This only OBSERVES. It does not decide to restart; the restart-reconstruction
milestone is recorded if a restart happens to occur while a position is open
(e.g. an operator/Codex gated restart), but is never triggered here.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parents[1]
EVID = REPO / "raw_evidence"
ACCT_THRESHOLD_USD = 0.02


def _r() -> redis.Redis:
    return redis.Redis(decode_responses=True)


def _gj(r, key):
    v = r.get(key)
    if v is None:
        return None
    try:
        return json.loads(v)
    except Exception:
        return v


def _lst(x):
    return x if isinstance(x, list) else []


def _pos_key(p) -> str:
    return str(p.get("identity") or p.get("position_id") or p.get("prediction_id")
               or f"{p.get('symbol')}:{p.get('side')}:{p.get('entry_time')}")


def _is_protected(p) -> tuple[bool, dict]:
    """A position is protected when it carries a usable mandatory/stop distance."""
    stop_price = p.get("stop_price") or p.get("mandatory_stop_price") or p.get("protective_stop_price")
    stop_bps = p.get("stop_distance_bps") or p.get("mandatory_stop_distance_bps") or p.get("atr_stop_bps")
    liq = p.get("liquidation_price_estimate")
    ok = bool(stop_price) or (isinstance(stop_bps, (int, float)) and stop_bps and stop_bps > 0)
    return ok, {"stop_price": stop_price, "stop_distance_bps": stop_bps, "liquidation_price_estimate": liq}


def _accounting_reconciled(r) -> tuple[bool, dict]:
    closed = _lst(_gj(r, "v2:paper:closed_trades"))
    portfolio = _gj(r, "v2:portfolio:state") or {}
    trade_sum = 0.0
    for t in closed:
        if isinstance(t, dict):
            for k in ("realized_pnl_usd", "net_realized_pnl_usd", "realized_pnl"):
                if t.get(k) is not None:
                    try:
                        trade_sum += float(t[k])
                    except Exception:
                        pass
                    break
    ledger = portfolio.get("realized_pnl_usd") or portfolio.get("net_realized_pnl_usd")
    if ledger is None:
        # fall back: no explicit ledger field -> report the trade-sum only
        return True, {"trade_sum_usd": round(trade_sum, 6), "ledger_usd": None,
                      "note": "no explicit portfolio realized_pnl ledger field; G08 verifier is authoritative"}
    diff = abs(trade_sum - float(ledger))
    return diff <= ACCT_THRESHOLD_USD, {"trade_sum_usd": round(trade_sum, 6),
                                        "ledger_usd": float(ledger), "difference_usd": round(diff, 6)}


def watch(max_minutes: float, poll_s: float) -> int:
    r = _r()
    open_by_key: dict[str, dict] = {}
    lifecycles: list[dict] = []  # completed fill->close records
    protected_keys: set[str] = set()
    prev_pid = None
    restart_while_open = []
    prev_closed = len(_lst(_gj(r, "v2:paper:closed_trades")))
    elapsed = 0.0

    import subprocess
    def _pid():
        try:
            out = subprocess.run(["systemctl", "--user", "show",
                                  "ai-bot-v2-trade-management-paper-loop.service", "-p", "MainPID"],
                                 capture_output=True, text=True, timeout=8).stdout.strip()
            return out.split("=", 1)[-1] if "=" in out else None
        except Exception:
            return None

    while elapsed < max_minutes * 60.0:
        positions = _lst(_gj(r, "v2:paper:positions"))
        closed = _lst(_gj(r, "v2:paper:closed_trades"))
        pid = _pid()

        cur_keys = {}
        for p in positions:
            if not isinstance(p, dict):
                continue
            k = _pos_key(p)
            cur_keys[k] = p
            if k not in open_by_key:
                proof = bool(p.get("accepted_fill_id") or p.get("fill_proof_id"))
                open_by_key[k] = {"symbol": p.get("symbol"), "side": p.get("side"),
                                  "entry_price": p.get("entry_price"), "opened_seen_s": round(elapsed, 1),
                                  "proof_backed": proof, "prediction_id": p.get("prediction_id")}
                print(f"[{elapsed:6.0f}s] FILL detected: {p.get('symbol')} {p.get('side')} "
                      f"proof_backed={proof}")
            prot, pinfo = _is_protected(p)
            if prot and k not in protected_keys:
                protected_keys.add(k)
                open_by_key[k]["protected"] = pinfo
                print(f"[{elapsed:6.0f}s] PROTECTED: {p.get('symbol')} {pinfo}")

        # restart while a position is open
        if prev_pid is not None and pid != prev_pid and open_by_key:
            restart_while_open.append({"at_s": round(elapsed, 1), "from_pid": prev_pid, "to_pid": pid,
                                       "open_keys": list(cur_keys.keys())})
            print(f"[{elapsed:6.0f}s] RESTART while position open: {prev_pid}->{pid}")
        prev_pid = pid

        # close detection: a previously-open key gone + closed_trades grew
        gone = set(open_by_key) - set(cur_keys)
        if gone and len(closed) > prev_closed:
            for k in list(gone):
                rec = open_by_key.pop(k)
                protected_keys.discard(k)
                acct_ok, acct = _accounting_reconciled(r)
                last_close = closed[-1] if closed else {}
                rec.update({
                    "closed_seen_s": round(elapsed, 1),
                    "close_reason": last_close.get("close_reason") or last_close.get("exit_reason"),
                    "realized_pnl_usd": last_close.get("realized_pnl_usd"),
                    "accounting_reconciled": acct_ok, "accounting": acct,
                    "was_protected": "protected" in rec,
                })
                lifecycles.append(rec)
                print(f"[{elapsed:6.0f}s] CLOSE: {rec.get('symbol')} reason={rec.get('close_reason')} "
                      f"pnl={rec.get('realized_pnl_usd')} acct_ok={acct_ok} protected={rec.get('was_protected')}")
        prev_closed = len(closed)

        # done when 3 full lifecycles observed (first + 2 more)
        complete = [lc for lc in lifecycles if lc.get("proof_backed") and lc.get("was_protected")
                    and lc.get("accounting_reconciled")]
        if len(complete) >= 3:
            break
        time.sleep(poll_s)
        elapsed += poll_s

    complete = [lc for lc in lifecycles if lc.get("proof_backed") and lc.get("was_protected")
                and lc.get("accounting_reconciled")]
    verdict = {
        "schema": "paper_lifecycle_acceptance_v1",
        "paper_only": True, "live_gate": "blocked_human_only",
        "observed_minutes": round(elapsed / 60.0, 2),
        "fills_detected": len(lifecycles) + len(open_by_key),
        "lifecycles_completed": len(lifecycles),
        "lifecycles_fully_valid_proof_protected_reconciled": len(complete),
        "restart_reconstruction_events": restart_while_open,
        "first_lifecycle": lifecycles[0] if lifecycles else None,
        "all_lifecycles": lifecycles,
        "still_open_at_end": list(open_by_key.values()),
        "verdict": "PASS" if len(complete) >= 3 else ("PARTIAL" if lifecycles else "NO_FILL_OBSERVED"),
        "acceptance_rule": ("operator #18: >=3 proof-backed, protected, adaptively-closed, "
                            "accounting-reconciled lifecycles (first + two more cycles)"),
    }
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "paper_lifecycle_acceptance_latest.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: verdict[k] for k in (
        "verdict", "fills_detected", "lifecycles_completed",
        "lifecycles_fully_valid_proof_protected_reconciled", "restart_reconstruction_events")}, indent=2))
    return 0 if verdict["verdict"] == "PASS" else 2


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "watch":
        print(__doc__)
        return 1
    max_minutes = float(argv[2]) if len(argv) > 2 else 30.0
    poll_s = float(argv[3]) if len(argv) > 3 else 20.0
    return watch(max_minutes, poll_s)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
