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


def _float(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _proof_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("proofs") or payload.get("bindings")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return [row for row in payload.values() if isinstance(row, dict)]
    return []


def _identity(row: dict, fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    return None


def _duplicate_count(rows: list[dict], fields: tuple[str, ...]) -> int:
    identities = [_identity(row, fields) for row in rows]
    present = [identity for identity in identities if identity is not None]
    return len(present) - len(set(present))


def _epoch_state(r) -> tuple[dict, str | None, int | None]:
    pointer = _gj(r, "v2:paper:account_epoch:current") or {}
    session_id = pointer.get("paper_session_id") if isinstance(pointer, dict) else None
    raw_epoch = pointer.get("paper_account_epoch") if isinstance(pointer, dict) else None
    epoch = raw_epoch if isinstance(raw_epoch, int) and not isinstance(raw_epoch, bool) else None
    return pointer if isinstance(pointer, dict) else {}, session_id, epoch


def _epoch_key(epoch: int | None, leaf: str, fallback: str) -> str:
    return f"v2:paper:epoch:{epoch}:{leaf}" if epoch is not None else fallback


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
    for p in _proof_rows(proofs):
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
    pointer, paper_session_id, paper_account_epoch = _epoch_state(r)
    legacy_session = _gj(r, "v2:paper:session") or {}
    positions = _gj(
        r,
        _epoch_key(paper_account_epoch, "positions", "v2:paper:positions"),
    ) or []
    proofs = _gj(r, "v2:paper:open_position_fill_proofs")
    proof_rows = _proof_rows(proofs)
    proof_manifest = _gj(r, "v2:paper:open_position_fill_proofs:manifest") or {}
    accepted = _gj(
        r,
        _epoch_key(paper_account_epoch, "accepted_fills", "v2:paper:accepted_fills"),
    ) or []
    quarantine = _gj(r, "v2:paper:accepted_fills:quarantine") or []
    portfolio = _gj(r, "v2:portfolio:state") or {}
    paper_status = _gj(r, "v2:paper:trade_management:status") or {}
    margin = (
        paper_status.get("paper_margin_reservation_status")
        if isinstance(paper_status, dict)
        and isinstance(paper_status.get("paper_margin_reservation_status"), dict)
        else _gj(r, "v2:paper:account_margin_status") or {}
    )
    trace = _gj(r, "v2:paper:fill_persistence_trace") or {}
    closed = _gj(
        r,
        _epoch_key(paper_account_epoch, "closed_trades", "v2:paper:closed_trades"),
    ) or []
    reservations = _gj(
        r,
        _epoch_key(paper_account_epoch, "reservations", "v2:paper:reservations"),
    ) or []
    reservation_rows = (
        reservations
        if isinstance(reservations, list)
        else margin.get("reservation_rows")
        if isinstance(margin, dict) and isinstance(margin.get("reservation_rows"), list)
        else []
    )

    # wipe receipts
    wipe_keys = list(r.scan_iter("v2:paper:position_fill_reconciliation:receipts:*", count=8000))
    wipes = []
    for k in wipe_keys:
        d = _gj(r, k)
        if isinstance(d, dict):
            phantom_count = int(d.get("phantom_position_count") or 0)
            margin_released = float(d.get("used_margin_released_usd") or 0.0)
            removed = d.get("removed_position_ids") or d.get("removed_positions") or []
            if phantom_count > 0 or margin_released > 0.0 or bool(removed):
                wipes.append({
                    "reason": d.get("reason"),
                    "phantom_position_count": phantom_count,
                    "accepted_fill_proof_count": d.get("accepted_fill_proof_count"),
                    "used_margin_released_usd": margin_released,
                    "removed_position_count": len(removed) if isinstance(removed, list) else None,
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

    accepted_rows = [row for row in _as_list(accepted) if isinstance(row, dict)]
    closed_rows = [row for row in _as_list(closed) if isinstance(row, dict)]
    duplicate_fills = _duplicate_count(
        accepted_rows,
        ("fill_id", "ledger_row_id", "accepted_fill_id"),
    )
    duplicate_closes = _duplicate_count(
        closed_rows,
        ("close_id", "closed_trade_id", "outcome_label_id", "position_id"),
    )
    used_margin = _float(margin.get("used_margin_usd")) if isinstance(margin, dict) else None
    free_margin = _float(margin.get("free_margin_usd")) if isinstance(margin, dict) else None
    reserved_margin = _float(portfolio.get("reserved_margin_usd"))
    if reserved_margin is None and isinstance(margin, dict):
        reserved_margin = _float(margin.get("reserved_margin_usd"))
    equity = _float(portfolio.get("equity"))
    wallet = _float(portfolio.get("wallet_balance"))
    margin_base = _float(margin.get("margin_base_usd")) if isinstance(margin, dict) else None
    accounting_conserved = (
        equity is not None
        and wallet is not None
        and used_margin is not None
        and free_margin is not None
        and abs((margin_base if margin_base is not None else min(equity, wallet))
                - used_margin - free_margin) <= 0.01
        and margin.get("post_lifecycle_accounting_invariant_holds") is not False
        and margin.get("post_lifecycle_reconciled") is not False
    )
    reservation_leak_count = len(reservation_rows)
    if (reserved_margin or 0.0) > 0.005 and not reservation_rows:
        reservation_leak_count += 1
    candidate_count = int(margin.get("candidate_count") or 0) if isinstance(margin, dict) else 0
    reservation_snapshot_present = (
        candidate_count == 0
        or (
            isinstance(margin.get("pre_lifecycle_snapshot_sha256"), str)
            and len(margin["pre_lifecycle_snapshot_sha256"]) == 64
        )
    )
    safety = {
        "paper_only": pointer.get("paper_only") is True,
        "live_gate": pointer.get("live_gate") == "blocked_human_only",
        "routes_to_live": pointer.get("routes_to_live") is False,
        "places_real_order": pointer.get("places_real_order") is False,
        "exchange_action_taken": (
            pointer.get("exchange_action_taken") is False
            or (
                pointer.get("exchange_action_taken") is None
                and isinstance(legacy_session, dict)
                and legacy_session.get("exchange_action_taken") is False
            )
        ),
    }

    return {
        "paper_session_id": paper_session_id,
        "paper_account_epoch": paper_account_epoch,
        "cycle_generated_utc": paper_status.get("generated_utc"),
        "wallet_balance_usd": wallet,
        "equity_usd": equity,
        "used_margin_usd": used_margin,
        "free_margin_usd": free_margin,
        "reserved_margin_usd": reserved_margin,
        "open_positions_count": len(_as_list(positions)),
        "proof_store_len": len(proof_rows),
        "proof_store_present": proofs is not None,
        "proof_store_initialized": (
            isinstance(proof_manifest, dict)
            and proof_manifest.get("initialization_state")
            in {"EMPTY_INITIALIZED_PROOF_SET", "INITIALIZED_WITH_PROOFS"}
        ),
        "proof_store_backfill_complete": (
            isinstance(proof_manifest, dict) and proof_manifest.get("completed") is True
        ),
        "proof_backed_positions": backed,
        "unproved_positions": unproved,
        "accepted_fills_count": len(accepted_rows),
        "valid_accepted_for_ledger": trace.get("valid_accepted_for_ledger"),
        "invalid_admission_quarantined": trace.get("invalid_admission_quarantined"),
        "quarantine_count": len(_as_list(quarantine)),
        "quarantine_rows_with_empty_reasons": q_empty,
        "closed_trades_count": len(closed_rows),
        "destructive_wipe_receipt_count": len(wipes),
        "wipe_receipts": wipes,
        "pending_reservations_count": len(reservation_rows),
        "reservation_snapshot_present": reservation_snapshot_present,
        "duplicate_fill_count": duplicate_fills,
        "duplicate_close_count": duplicate_closes,
        "reservation_leak_count": reservation_leak_count,
        "wallet_equity_margin_conserved": accounting_conserved,
        "safety": safety,
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
        "destructive_wipe_receipt_count": snap["destructive_wipe_receipt_count"],
    }, indent=2))
    return 0


def observe(cycles: int, interval_s: float) -> int:
    r = _r()
    samples = []
    baseline_wipes = None
    previous_cycle = None
    for i in range(cycles):
        deadline = time.monotonic() + max(90.0, interval_s * 3.0)
        while True:
            snap = snapshot(r)
            cycle_id = snap.get("cycle_generated_utc")
            if cycle_id and cycle_id != previous_cycle:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("paper_cycle_observation_timeout")
            time.sleep(min(3.0, interval_s))
        previous_cycle = cycle_id
        samples.append(snap)
        if baseline_wipes is None:
            baseline_wipes = snap["destructive_wipe_receipt_count"]
        print(f"[cycle {i+1}/{cycles}] pos={snap['open_positions_count']} "
              f"proof_backed={snap['proof_backed_positions']} unproved={snap['unproved_positions']} "
              f"proof_store={snap['proof_store_len']} quarantine_empty={snap['quarantine_rows_with_empty_reasons']} "
              f"wipes={snap['destructive_wipe_receipt_count']} closed={snap['closed_trades_count']} "
              f"cycle={snap['cycle_generated_utc']}")

    last = samples[-1]
    # criteria
    new_wipes = last["destructive_wipe_receipt_count"] - (baseline_wipes or 0)
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
        "reservation_snapshot_present": all(s["reservation_snapshot_present"] for s in samples),
        "duplicate_fills_or_closes_zero": all(
            s["duplicate_fill_count"] == 0 and s["duplicate_close_count"] == 0
            for s in samples
        ),
        "reservation_leak_zero": all(s["reservation_leak_count"] == 0 for s in samples),
        "wallet_equity_margin_conservation": all(
            s["wallet_equity_margin_conserved"] for s in samples
        ),
        "proof_store_initialized_and_backfilled": all(
            s["proof_store_initialized"] and s["proof_store_backfill_complete"]
            for s in samples
        ),
        "paper_only_no_live_authority": all(all(s["safety"].values()) for s in samples),
        "one_current_epoch": len(
            {(s["paper_session_id"], s["paper_account_epoch"]) for s in samples}
        ) == 1,
    }
    all_pass = all(criteria.values())
    verdict = {
        "schema": "paper_runtime_acceptance_observe_v1",
        "cycles": cycles,
        "criteria": criteria,
        "new_wipe_receipts_during_observation": new_wipes,
        "verdict": "PASS" if all_pass else "FAIL",
        "note": "All criteria are bound to the active PaperAccountEpochV1 keys and completed-cycle heartbeats.",
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
