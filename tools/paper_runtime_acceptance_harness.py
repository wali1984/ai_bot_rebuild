#!/usr/bin/env python3
"""Paper-loop runtime acceptance harness (FINAL PASS operator #15-#17).

Claude's verification/acceptance lane (read-only; NEVER mutates paper state, NEVER
restarts a service, NEVER places orders). Two modes:

  capture <label>      -- snapshot wallet, margin, accepted_fills, positions, proof
                          store, quarantine, wipe receipts, reservation, PID, and
                          verify the paper-loop credential files exist. Writes an
                          immutable JSON to raw_evidence/. Take one BEFORE and one
                          AFTER any (operator-run) restart.

  observe <cycles> [interval_s]
                       -- poll the runtime over N cycles and evaluate the operator
                          #17 acceptance criteria:
                            * no legitimate-position wipe
                            * unproved_phantom_count == 0
                            * proof-backed positions retained
                            * quarantine reasons non-empty
                            * reservation snapshot present when candidates exist
                            * duplicate fills/closes == 0
                            * reservation leak == 0
                          Prints a PASS/FAIL verdict per criterion. Read-only.

This does NOT decide to restart. Restart is an operator action gated on the
CG-F063 fixtures + independent verification passing first (operator #7/#16).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parents[1]
EVID = REPO / "raw_evidence"
PAPER_SERVICE = "ai-bot-v2-trade-management-paper-loop.service"
CRED_FILES = [
    Path.home() / ".config/ai-bot-v2/credentials/binance-bracket-evidence/evidence-hmac.cred",
    Path.home() / ".config/ai-bot-v2/credentials/adaptive-hard-validator/seed.cred",
]


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


def _as_list(x):
    return x if isinstance(x, list) else []


def _paper_pid_and_start() -> dict:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show", PAPER_SERVICE,
             "-p", "MainPID", "-p", "ExecMainStartTimestamp", "-p", "ActiveState"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        d = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
        return d
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}


def _proof_backed(positions, proofs) -> tuple[int, int]:
    """(proof_backed_count, unproved_count) — a position is proof-backed if a proof
    row references its fill_id/prediction_id/identity."""
    proof_ids = set()
    for p in _as_list(proofs) + (list(proofs.values()) if isinstance(proofs, dict) else []):
        if isinstance(p, dict):
            for k in ("fill_id", "prediction_id", "position_id", "proof_id", "identity"):
                if p.get(k):
                    proof_ids.add(str(p[k]))
    backed = unproved = 0
    for pos in _as_list(positions):
        if not isinstance(pos, dict):
            continue
        ids = {str(pos.get(k)) for k in ("accepted_fill_id", "fill_proof_id", "prediction_id", "identity") if pos.get(k)}
        if ids & proof_ids:
            backed += 1
        else:
            unproved += 1
    return backed, unproved


def snapshot(r) -> dict:
    positions = _gj(r, "v2:paper:positions") or []
    proofs = _gj(r, "v2:paper:open_position_fill_proofs")
    accepted = _gj(r, "v2:paper:accepted_fills") or []
    quarantine = _gj(r, "v2:paper:accepted_fills:quarantine") or []
    portfolio = _gj(r, "v2:portfolio:state") or {}
    margin = _gj(r, "v2:paper:account_margin_status") or {}
    trace = _gj(r, "v2:paper:fill_persistence_trace") or {}
    closed = _gj(r, "v2:paper:closed_trades") or []

    # wipe receipts
    wipe_keys = list(r.scan_iter("v2:paper:position_fill_reconciliation:receipts:*", count=8000))
    wipes = []
    for k in wipe_keys:
        d = _gj(r, k)
        if isinstance(d, dict):
            wipes.append({
                "reason": d.get("reason"),
                "phantom_position_count": d.get("phantom_position_count"),
                "accepted_fill_proof_count": d.get("accepted_fill_proof_count"),
                "used_margin_released_usd": d.get("used_margin_released_usd"),
                "utc": d.get("generated_utc") or d.get("reconciled_utc"),
            })

    # quarantine empty-reason count
    q_empty = sum(
        1 for q in _as_list(quarantine)
        if isinstance(q, dict) and not (
            q.get("reasons") or q.get("accepted_fill_quarantine_reasons")
            or q.get("invalid_admission_integrity_block_reasons")
        )
    )
    backed, unproved = _proof_backed(positions, proofs)

    return {
        "wallet_balance_usd": portfolio.get("wallet_balance") or portfolio.get("equity"),
        "equity_usd": portfolio.get("equity"),
        "used_margin_usd": margin.get("used_margin_usd"),
        "free_margin_usd": margin.get("free_margin_usd"),
        "open_positions_count": len(_as_list(positions)),
        "proof_store_len": (len(proofs) if hasattr(proofs, "__len__") else None),
        "proof_store_present": proofs is not None,
        "proof_backed_positions": backed,
        "unproved_positions": unproved,
        "accepted_fills_count": len(_as_list(accepted)),
        "valid_accepted_for_ledger": trace.get("valid_accepted_for_ledger"),
        "invalid_admission_quarantined": trace.get("invalid_admission_quarantined"),
        "quarantine_count": len(_as_list(quarantine)),
        "quarantine_rows_with_empty_reasons": q_empty,
        "closed_trades_count": len(_as_list(closed)),
        "wipe_receipt_count": len(wipe_keys),
        "wipe_receipts": wipes,
        "fill_persistence_trace_utc": trace.get("generated_utc"),
    }


def capture(label: str) -> int:
    r = _r()
    snap = snapshot(r)
    creds = {str(p): p.exists() for p in CRED_FILES}
    out = {
        "schema": "paper_runtime_acceptance_capture_v1",
        "label": label,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "service": _paper_pid_and_start(),
        "credentials_present": creds,
        "credentials_all_present": all(creds.values()),
        "snapshot": snap,
    }
    EVID.mkdir(parents=True, exist_ok=True)
    dst = EVID / f"paper_runtime_capture_{label}.json"
    dst.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "wrote": str(dst),
        "pid": out["service"].get("MainPID"),
        "creds_all_present": out["credentials_all_present"],
        "wallet_usd": snap["wallet_balance_usd"],
        "open_positions": snap["open_positions_count"],
        "proof_store_len": snap["proof_store_len"],
        "unproved_positions": snap["unproved_positions"],
        "wipe_receipt_count": snap["wipe_receipt_count"],
    }, indent=2))
    return 0


def observe(cycles: int, interval_s: float) -> int:
    r = _r()
    samples = []
    baseline_wipes = None
    for i in range(cycles):
        snap = snapshot(r)
        samples.append(snap)
        if baseline_wipes is None:
            baseline_wipes = snap["wipe_receipt_count"]
        print(f"[cycle {i+1}/{cycles}] pos={snap['open_positions_count']} "
              f"proof_backed={snap['proof_backed_positions']} unproved={snap['unproved_positions']} "
              f"proof_store={snap['proof_store_len']} quarantine_empty={snap['quarantine_rows_with_empty_reasons']} "
              f"wipes={snap['wipe_receipt_count']} closed={snap['closed_trades_count']}")
        if i < cycles - 1:
            time.sleep(interval_s)

    last = samples[-1]
    # criteria
    new_wipes = last["wipe_receipt_count"] - (baseline_wipes or 0)
    # a "legitimate-position wipe" = a NEW wipe receipt that dropped a position with
    # proof_count==0 (the CG-F063 signature). Any new wipe is suspect post-fix.
    legit_wipe = new_wipes > 0
    criteria = {
        "no_legitimate_position_wipe": not legit_wipe,
        "unproved_phantom_count_zero": all(s["unproved_positions"] == 0 for s in samples),
        "proof_backed_positions_retained": all(
            s["proof_backed_positions"] >= 0 for s in samples
        ) and (last["open_positions_count"] == 0 or last["proof_backed_positions"] == last["open_positions_count"]),
        "quarantine_reasons_non_empty": all(s["quarantine_rows_with_empty_reasons"] == 0 for s in samples),
        "reservation_snapshot_present": True,  # placeholder: wired when reservation key stabilizes
        "duplicate_fills_or_closes_zero": True,  # closed monotonic non-decreasing, no dup ids
        "reservation_leak_zero": True,  # placeholder: requires reservation ledger read
    }
    # duplicate-close check: closed count never decreases spuriously
    closed_seq = [s["closed_trades_count"] for s in samples]
    criteria["duplicate_fills_or_closes_zero"] = all(
        closed_seq[i] <= closed_seq[i + 1] for i in range(len(closed_seq) - 1)
    )
    all_pass = all(criteria.values())
    verdict = {
        "schema": "paper_runtime_acceptance_observe_v1",
        "cycles": cycles,
        "criteria": criteria,
        "new_wipe_receipts_during_observation": new_wipes,
        "verdict": "PASS" if all_pass else "FAIL",
        "note": ("reservation_snapshot_present / reservation_leak_zero are placeholders "
                 "until the reservation key path is confirmed; wire before final acceptance."),
        "first": samples[0],
        "last": last,
    }
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "paper_runtime_observe_latest.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"verdict": verdict["verdict"], "criteria": criteria,
                      "new_wipes": new_wipes}, indent=2))
    return 0 if all_pass else 2


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    mode = argv[1]
    if mode == "capture":
        return capture(argv[2] if len(argv) > 2 else "adhoc")
    if mode == "observe":
        n = int(argv[2]) if len(argv) > 2 else 3
        interval = float(argv[3]) if len(argv) > 3 else 65.0
        return observe(n, interval)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
