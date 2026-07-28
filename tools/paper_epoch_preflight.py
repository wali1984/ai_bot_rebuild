#!/usr/bin/env python3
"""Read-only preflight safety gate for the PaperAccountEpochV1 rotation.

Evaluates every precondition required before a clean $3,000 paper-session rotation.
STRICTLY READ-ONLY: issues only Redis GET/TYPE/OBJECT reads, never writes/deletes,
never restarts anything, never mutates paper state. Emits a structured report with
`state_mutated: false` always. On any failing precondition it reports
`status: BLOCKED_RESET_PRECONDITION` — it does NOT "solve" a failure by deleting a
position/proof/quarantine row.

Usage (under the backend venv so redis-py is importable):
  "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3" tools/paper_epoch_preflight.py
Exit code 0 = PASS (safe to proceed), 2 = BLOCKED, 1 = read error.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Preconditions that must hold before rotation (name -> required value / predicate label)
REQUIRED = {
    "valid_proof_backed_open_positions": 0,
    "pending_fills": 0,
    "pending_reservations": 0,
    "used_margin_usd": 0,
    "reserved_margin_usd": 0,
    "unresolved_position_proof_rows": 0,
    "unresolved_accounting_reconciliation": 0,
    "duplicate_fill_count": 0,
    "duplicate_close_count": 0,
    "proof_store_initialized": True,
    "proof_store_backfill_complete": True,
}
RECONCILE_THRESHOLD_USD = 0.02


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _get_json(r, key):
    raw = r.get(key)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _as_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("positions", "rows", "items", "open_positions"):
            if isinstance(payload.get(k), list):
                return payload[k]
        return list(payload.values())
    return []


def evaluate(r) -> dict:
    checks: dict[str, dict] = {}

    def record(name, actual, ok, evidence=""):
        checks[name] = {"required": REQUIRED[name], "actual": actual, "pass": bool(ok), "evidence": evidence}

    portfolio = _get_json(r, "v2:portfolio:state") or {}
    positions = _as_rows(_get_json(r, "v2:paper:positions"))
    accepted = _get_json(r, "v2:paper:accepted_fills") or []
    closed = _get_json(r, "v2:paper:closed_trades") or []
    trace = _get_json(r, "v2:paper:fill_persistence_trace") or {}

    def _num(v):
        return v if isinstance(v, (int, float)) else None

    # open positions split by proof
    proof_backed = sum(
        1 for p in positions if isinstance(p, dict) and isinstance(p.get("accepted_fills"), list) and p["accepted_fills"]
    )
    proofless = sum(1 for p in positions if isinstance(p, dict) and p.get("accepted_fills") in ([], None))
    record("valid_proof_backed_open_positions", proof_backed, proof_backed == 0, f"{len(positions)} rows in v2:paper:positions")
    record("unresolved_position_proof_rows", proofless + int(trace.get("invalid_admission_quarantined") or 0),
           (proofless + int(trace.get("invalid_admission_quarantined") or 0)) == 0,
           f"proofless_position_rows={proofless}, invalid_admission_quarantined={trace.get('invalid_admission_quarantined')}")

    record("pending_fills", len(accepted), len(accepted) == 0, "v2:paper:accepted_fills length")

    # reservations: no canonical live key observed; treat absence as 0 but surface it
    resv = _get_json(r, "v2:paper:reservations")
    resv_n = len(_as_rows(resv)) if resv is not None else 0
    record("pending_reservations", resv_n, resv_n == 0, "no v2:paper:reservations key present" if resv is None else "")

    used = _num(portfolio.get("used_margin_usd"))
    record("used_margin_usd", used, used == 0, "v2:portfolio:state.used_margin_usd")
    reserved = _num(portfolio.get("reserved_margin_usd"))
    record("reserved_margin_usd", reserved, reserved == 0,
           "null/unset" if reserved is None else "v2:portfolio:state.reserved_margin_usd")

    # accounting reconciliation: sum(closed realized) vs ledger realized
    def _pnl(t):
        # Canonical basis = realized NET usd (fees+funding+slippage), which reconciles to the
        # ledger (matches Guardian G08). Gross fields (realized_pnl_usd) do NOT reconcile.
        for k in ("realized_net_pnl_usd", "realized_net_pnl", "realized_pnl_usd", "realized_pnl", "net_pnl_usd", "pnl_usd"):
            if isinstance(t, dict) and isinstance(t.get(k), (int, float)):
                return t[k]
        return 0.0
    trade_sum = sum(_pnl(t) for t in closed if isinstance(t, dict))
    ledger = _num(portfolio.get("realized_pnl_usd"))
    if ledger is None:
        record("unresolved_accounting_reconciliation", "ledger_realized_null", False, "v2:portfolio:state.realized_pnl_usd is null")
    else:
        diff = abs(trade_sum - ledger)
        record("unresolved_accounting_reconciliation", round(diff, 6), diff <= RECONCILE_THRESHOLD_USD,
               f"|trade_sum {trade_sum:.4f} - ledger {ledger:.4f}| = {diff:.6f} (<= {RECONCILE_THRESHOLD_USD})")

    def _dupes(rows, id_keys):
        ids = []
        for x in rows:
            if isinstance(x, dict):
                for k in id_keys:
                    if x.get(k):
                        ids.append(x[k]); break
        return len(ids) - len(set(ids))
    fd = _dupes(accepted, ("fill_id", "accepted_fill_id", "id"))
    cd = _dupes(closed, ("trade_id", "close_id", "id"))
    record("duplicate_fill_count", fd, fd == 0, "")
    record("duplicate_close_count", cd, cd == 0, "")

    psi = trace.get("proof_store_initialized")
    psb = trace.get("proof_store_backfill_complete")
    record("proof_store_initialized", psi, psi is True, "v2:paper:fill_persistence_trace.proof_store_initialized")
    record("proof_store_backfill_complete", psb, psb is True, "v2:paper:fill_persistence_trace.proof_store_backfill_complete")

    all_pass = all(c["pass"] for c in checks.values())
    session = _get_json(r, "v2:paper:session") or {}
    return {
        "schema_version": "paper_epoch_preflight_v1",
        "generated_utc": _now(),
        "state_mutated": False,
        "status": "PASS" if all_pass else "BLOCKED_RESET_PRECONDITION",
        "current_paper_session_id": session.get("paper_session_id"),
        "current_paper_account_epoch": portfolio.get("paper_account_epoch"),
        "historical_closed_trade_count": len(closed),
        "checks": checks,
        "failing": [k for k, v in checks.items() if not v["pass"]],
        "note": (
            "PASS reflects one snapshot; CG-F056 phantom churn means positions/fills must be proof-clean "
            "across >=3 consecutive cycles before rotation. Re-run this gate each cycle."
        ),
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }


def main() -> int:
    try:
        import redis  # type: ignore
    except Exception as e:  # pragma: no cover
        print(json.dumps({"status": "READ_ERROR", "state_mutated": False, "error": f"redis import failed: {e}"}), file=sys.stderr)
        return 1
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)
        r.ping()
        report = evaluate(r)
    except Exception as e:  # pragma: no cover
        print(json.dumps({"status": "READ_ERROR", "state_mutated": False, "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
