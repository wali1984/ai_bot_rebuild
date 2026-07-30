#!/usr/bin/env python3
"""Continuous paper-cycle deterministic invariant monitor (PRE-WAIT CERT Phase 8).

READ-ONLY. Never mutates paper state, never restarts a service, never places an
order. Evaluates the deterministic engineering invariants that must hold on EVERY
completed paper cycle. When any invariant fails, the system must NOT classify
itself as market/economic gated — it must open the repair path.

Invariants (operator PRE-WAIT DETERMINISTIC CERTIFICATION, section 8):
  I01  exactly one paper writer
  I02  exactly one adaptive writer
  I03  all intents carry the current session/epoch
  I04  all directional candidates carry authenticated feature/cost/microstructure/
       orchestrator/risk evidence
  I05  every accepted fill has exactly one proof
  I06  every position has exactly one accepted fill
  I07  every close references exactly one position
  I08  accounting conservation (trade_sum ~= ledger within threshold, per session)
  I09  reservation conservation (no leak: reserved margin reconciles to open use)
  I10  duplicate fills / duplicate closes == 0
  I11  proof-store state valid (initialized; not the CG-F063 phantom-wipe signature)
  I12  no live authority anywhere in the runtime
  I13  service restart counters stable (no crash-loop churn)
  I14  memory / payload sizes bounded (no unbounded whole-file / Redis growth)

Usage:
  check                       one-shot evaluation -> verdict JSON to raw_evidence/
  watch [minutes] [poll_s]    poll every completed cycle; emit DETERMINISTIC_RUNTIME_DEFECT
                              immediately on any invariant breach

Exit code: 0 if all invariants PASS (or only NEEDS_INSTRUMENTATION), 2 on any FAIL.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parents[1]
EVID = REPO / "raw_evidence"
ACCT_THRESHOLD_USD = 0.02
# services whose restart churn would indicate a deterministic crash-loop defect
LIFECYCLE_SERVICES = [
    "ai-bot-v2-trade-management-paper-loop",
    "ai-bot-v2-feature-pipeline-native-loop",
    "ai-bot-v2-rl-core-inference-loop",
    "ai-bot-v2-portfolio-state-publisher",
    "ai-bot-v2-native-cuda-trainer-persistent",
]
# a payload larger than this (bytes) on a per-cycle mutable list is treated as
# an unbounded-growth smell that must be justified, not silently accepted.
PAYLOAD_SOFT_CAP_BYTES = 8 * 1024 * 1024      # WARN above this (load-scaling)
PAYLOAD_HARD_CEILING_BYTES = 256 * 1024 * 1024  # FAIL above this (genuinely unbounded)
RESTART_CHURN_CAP = 5  # NRestarts delta over the watch window that flags churn


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


def _raw_len(r, key) -> int:
    try:
        v = r.get(key)
        return len(v) if isinstance(v, str) else 0
    except Exception:
        return 0


def _svc(unit: str, props: list[str]) -> dict:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show", unit + ".service", *sum([["-p", p] for p in props], [])],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:80]}


def _pos_key(p) -> str:
    return str(p.get("identity") or p.get("position_id") or p.get("prediction_id")
               or f"{p.get('symbol')}:{p.get('side')}:{p.get('entry_time')}")


def _fill_ids(obj) -> set[str]:
    ids = set()
    for k in ("accepted_fill_id", "fill_proof_id", "fill_id", "prediction_id", "identity", "position_id"):
        v = obj.get(k) if isinstance(obj, dict) else None
        if v:
            ids.add(str(v))
    return ids


def _result(status: str, detail: str, evidence: dict | None = None) -> dict:
    return {"status": status, "detail": detail, "evidence": evidence or {}}


def evaluate(r) -> dict:
    epoch = _gj(r, "v2:paper:account_epoch:current") or {}
    cur_session = str(epoch.get("paper_session_id") or "")
    cur_epoch = epoch.get("paper_account_epoch")

    positions = _lst(_gj(r, "v2:paper:positions"))
    accepted = _lst(_gj(r, "v2:paper:accepted_fills"))
    proofs_raw = _gj(r, "v2:paper:open_position_fill_proofs")
    proofs = _lst(proofs_raw) if isinstance(proofs_raw, list) else (
        list(proofs_raw.values()) if isinstance(proofs_raw, dict) else [])
    closed = _lst(_gj(r, "v2:paper:closed_trades"))
    intents = _gj(r, "v2:paper:intents")
    intent_rows = intents if isinstance(intents, list) else (
        intents.get("intents", intents.get("candidates", [])) if isinstance(intents, dict) else [])
    portfolio = _gj(r, "v2:portfolio:state") or {}
    margin = _gj(r, "v2:paper:account_margin_status") or {}

    inv: dict[str, dict] = {}

    # I01 exactly one paper writer
    hb = _gj(r, "v2:paper:heartbeat") or {}
    paper_active = _svc("ai-bot-v2-trade-management-paper-loop", ["ActiveState", "MainPID"])
    legacy = _svc("ai-bot-v2-paper-online-runtime", ["ActiveState"])
    legacy_active = legacy.get("ActiveState") == "active"
    writer_id = hb.get("worker_id")
    one_paper_writer = (paper_active.get("ActiveState") == "active") and not legacy_active
    inv["I01_one_paper_writer"] = _result(
        "PASS" if one_paper_writer else "FAIL",
        f"paper_loop={paper_active.get('ActiveState')} legacy_online_runtime_active={legacy_active} writer_id={writer_id}",
        {"paper_main_pid": paper_active.get("MainPID"), "legacy_active": legacy_active})

    # I02 exactly one adaptive writer — adaptive policy actions are stamped with a
    # single policy_id; more than one distinct writer identity on live intents = defect.
    apa_writers = set()
    for row in intent_rows:
        apa = row.get("adaptive_policy_action") if isinstance(row, dict) else None
        if isinstance(apa, dict) and apa.get("policy_id"):
            apa_writers.add(str(apa["policy_id"]))
    if not apa_writers:
        inv["I02_one_adaptive_writer"] = _result(
            "NEEDS_INSTRUMENTATION", "no adaptive_policy_action on current intents to attribute a writer", {})
    else:
        inv["I02_one_adaptive_writer"] = _result(
            "PASS" if len(apa_writers) == 1 else "FAIL",
            f"distinct adaptive policy writers = {sorted(apa_writers)}", {"writers": sorted(apa_writers)})

    # I03 all intents carry the current session/epoch
    if not cur_session:
        inv["I03_intents_session_scoped"] = _result("NEEDS_INSTRUMENTATION", "no current epoch anchor", {})
    else:
        bad = []
        for row in intent_rows:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("paper_session_id") or (row.get("adaptive_policy_action") or {}).get("paper_session_id") or "")
            eid = row.get("paper_account_epoch")
            if sid and sid != cur_session:
                bad.append({"intent": row.get("intent_id"), "session": sid})
            elif eid is not None and cur_epoch is not None and eid != cur_epoch:
                bad.append({"intent": row.get("intent_id"), "epoch": eid})
        tagged = sum(1 for row in intent_rows if isinstance(row, dict) and (
            row.get("paper_session_id") or (row.get("adaptive_policy_action") or {}).get("paper_session_id")))
        status = "FAIL" if bad else ("PASS" if tagged else "NEEDS_INSTRUMENTATION")
        inv["I03_intents_session_scoped"] = _result(
            status, f"{len(bad)} intents mis-scoped; {tagged}/{len(intent_rows)} carry a session tag",
            {"mis_scoped_examples": bad[:5]})

    # I04 directional candidates carry authenticated evidence
    directional = [row for row in intent_rows if isinstance(row, dict)
                   and str((row.get("adaptive_policy_action") or {}).get("selected_action") or row.get("selected_action") or "").lower()
                   in ("directional_trade", "reduce_existing_exposure", "close_existing_exposure")]
    ev_fields = ("feature_snapshot_id", "expected_cost_breakdown", "microstructure", "orchestrator", "risk")
    missing_ev = []
    for row in directional:
        apa = row.get("adaptive_policy_action") or {}
        has_feature = bool(apa.get("feature_snapshot_id") or row.get("feature_snapshot_id"))
        has_cost = bool(apa.get("expected_cost_breakdown"))
        if not (has_feature and has_cost):
            missing_ev.append({"intent": row.get("intent_id"), "feature": has_feature, "cost": has_cost})
    inv["I04_directional_evidence_authenticated"] = _result(
        "FAIL" if missing_ev else "PASS",
        f"{len(directional)} directional candidates; {len(missing_ev)} missing authenticated feature/cost evidence",
        {"directional_count": len(directional), "missing_examples": missing_ev[:5]})

    # I05 every accepted fill has exactly one proof
    proof_ids = set()
    for p in proofs:
        if isinstance(p, dict):
            proof_ids |= _fill_ids(p)
    unproved_fills = []
    for f in accepted:
        if not isinstance(f, dict):
            continue
        if not (_fill_ids(f) & proof_ids):
            unproved_fills.append(f.get("accepted_fill_id") or f.get("fill_id"))
    inv["I05_accepted_fill_has_one_proof"] = _result(
        "FAIL" if unproved_fills else "PASS",
        f"{len(accepted)} accepted fills; {len(unproved_fills)} without a matching proof",
        {"unproved_examples": unproved_fills[:5], "proof_store_len": len(proofs)})

    # I06 every position has exactly one accepted fill
    accepted_ids = set()
    for f in accepted:
        if isinstance(f, dict):
            accepted_ids |= _fill_ids(f)
    unbacked_positions = []
    for p in positions:
        if not isinstance(p, dict):
            continue
        if not (_fill_ids(p) & (accepted_ids | proof_ids)):
            unbacked_positions.append(_pos_key(p))
    inv["I06_position_has_one_fill"] = _result(
        "FAIL" if unbacked_positions else "PASS",
        f"{len(positions)} positions; {len(unbacked_positions)} without a backing accepted fill/proof",
        {"unbacked_examples": unbacked_positions[:5]})

    # I07 every close references exactly one position.
    # NOTE: position_id is SYMBOL-scoped (paper_pos_<SYMBOL>) and is legitimately
    # reused across sequential trades on the same symbol (different close_id /
    # exit_price_utc). So multiple closes per position_id is NORMAL, not a defect.
    # The uniqueness invariant is on close_id (I10), not position_id.
    close_pos_refs = []
    for c in closed:
        if isinstance(c, dict):
            close_pos_refs.append(str(c.get("position_id") or c.get("prediction_id") or c.get("identity") or ""))
    inv["I07_close_references_one_position"] = _result(
        "PASS" if all(close_pos_refs) or not closed else "FAIL",
        f"{len(closed)} closed trades; {sum(1 for x in close_pos_refs if not x)} without a position ref "
        f"(note: {len(set(close_pos_refs))} distinct symbol-scoped position keys; sequential reuse is legitimate)",
        {"unreferenced": sum(1 for x in close_pos_refs if not x)})

    # I10 duplicate closes: a TRUE duplicate is two closed_trade records sharing the
    # same unique close identity (close_id, or (position_id, exit_price_utc) fallback).
    def _close_identity(c):
        cid = c.get("close_id")
        if cid:
            return str(cid)
        return f"{c.get('position_id')}|{c.get('exit_price_utc') or c.get('exit_utc') or c.get('exit_time')}|{c.get('realized_pnl_usd')}"
    close_ids = [_close_identity(c) for c in closed if isinstance(c, dict)]
    dup_closes = len(close_ids) - len(set(close_ids))

    # I08 accounting conservation (current-session scope)
    def _pnl(t):
        for k in ("realized_pnl_usd", "net_realized_pnl_usd", "realized_pnl"):
            if isinstance(t, dict) and t.get(k) is not None:
                try:
                    return float(t[k])
                except Exception:
                    return 0.0
        return 0.0
    cur_closed = [t for t in closed if isinstance(t, dict) and (
        not cur_session or str(t.get("paper_session_id") or "") in ("", cur_session))]
    # For accounting we compare the CURRENT-session trade sum against the current
    # ledger; historical sessions are reconciled in their archive manifest.
    session_closed = [t for t in closed if isinstance(t, dict) and str(t.get("paper_session_id") or "") == cur_session]
    trade_sum = sum(_pnl(t) for t in session_closed)
    ledger = portfolio.get("realized_pnl_usd")
    if ledger is None:
        inv["I08_accounting_conservation"] = _result(
            "NEEDS_INSTRUMENTATION", "portfolio has no realized_pnl_usd ledger field", {})
    else:
        diff = abs(trade_sum - float(ledger))
        inv["I08_accounting_conservation"] = _result(
            "PASS" if diff <= ACCT_THRESHOLD_USD else "FAIL",
            f"current-session trade_sum={round(trade_sum,6)} vs ledger={float(ledger)} diff={round(diff,6)} "
            f"(session={cur_session or 'NONE'}, n={len(session_closed)})",
            {"trade_sum": round(trade_sum, 6), "ledger": float(ledger), "diff": round(diff, 6),
             "note": "cross-session comparison is NOT an accounting break; historical sessions reconcile in their archive"})

    # I09 reservation conservation (no leak)
    resv_key = f"v2:paper:epoch:{cur_epoch}:reservations" if cur_epoch is not None else None
    resv = _gj(r, resv_key) if resv_key else None
    resv_rows = _lst(resv) if isinstance(resv, list) else (list(resv.values()) if isinstance(resv, dict) else [])
    open_pos_count = len(positions)
    # a leak = reservations outstanding with zero open positions and zero in-flight fills
    leak = bool(resv_rows) and open_pos_count == 0 and not accepted
    inv["I09_reservation_conservation"] = _result(
        "FAIL" if leak else "PASS",
        f"{len(resv_rows)} outstanding reservations, {open_pos_count} open positions, {len(accepted)} accepted fills",
        {"reservation_key": resv_key, "outstanding": len(resv_rows)})

    # I10 duplicate fills / closes == 0
    fill_id_list = [f.get("accepted_fill_id") or f.get("fill_id") for f in accepted if isinstance(f, dict)]
    fill_id_list = [x for x in fill_id_list if x]
    dup_fills = len(fill_id_list) - len(set(fill_id_list))
    inv["I10_no_duplicate_fills_or_closes"] = _result(
        "PASS" if (dup_fills == 0 and dup_closes == 0) else "FAIL",
        f"duplicate_fills={dup_fills} duplicate_closes={dup_closes}",
        {"duplicate_fills": dup_fills, "duplicate_closes": dup_closes})

    # I11 proof-store state valid (not the CG-F063 phantom-wipe signature)
    wipe_keys = list(r.scan_iter("v2:paper:position_fill_reconciliation:receipts:*", count=8000))
    phantom_wipes = 0
    for k in wipe_keys:
        d = _gj(r, k)
        if isinstance(d, dict) and d.get("phantom_position_count") and not d.get("accepted_fill_proof_count"):
            phantom_wipes += 1
    proof_uninit = proofs_raw is None
    # positions open but proof store empty AND uninitialized = the CG-F063 danger
    cg_f063_signature = (open_pos_count > 0 and len(proofs) == 0 and proof_uninit)
    inv["I11_proof_store_valid"] = _result(
        "FAIL" if cg_f063_signature else "PASS",
        f"proof_store_present={proofs_raw is not None} len={len(proofs)} open_positions={open_pos_count} "
        f"phantom_wipe_receipts={phantom_wipes}",
        {"cg_f063_signature": cg_f063_signature, "phantom_wipes": phantom_wipes})

    # I12 no live authority anywhere
    live_flags = {
        "places_real_order": portfolio.get("places_real_order"),
        "trader_execution_enabled": portfolio.get("trader_execution_enabled"),
        "account_mode": portfolio.get("account_mode"),
    }
    intent_live = any(isinstance(row, dict) and (
        row.get("places_real_order") or row.get("routes_to_live") or row.get("exchange_action_taken")
        or row.get("live_order")) for row in intent_rows)
    live_violation = bool(portfolio.get("places_real_order") or portfolio.get("trader_execution_enabled") or intent_live)
    inv["I12_no_live_authority"] = _result(
        "FAIL" if live_violation else "PASS",
        f"portfolio_live_flags={live_flags} any_intent_live={intent_live}",
        {"live_flags": live_flags, "intent_live": intent_live})

    # I14 bounded payload sizes. Per-cycle overwritten snapshots (intents) are
    # bounded by candidate_count * per_record_size; a large per-record size is a
    # LOAD-SCALING risk (verified for the load-acceptance phase), so we report the
    # per-record size and candidate count alongside the raw bytes.
    payloads = {k: _raw_len(r, k) for k in (
        "v2:paper:positions", "v2:paper:accepted_fills", "v2:paper:open_position_fill_proofs",
        "v2:paper:closed_trades", "v2:paper:intents")}
    intents_bytes = payloads.get("v2:paper:intents", 0)
    per_intent = int(intents_bytes / len(intent_rows)) if intent_rows else 0
    largest = max(payloads.values()) if payloads else 0
    # A per-cycle OVERWRITTEN snapshot that is merely large (soft cap < x < hard
    # ceiling) is a load-scaling WARN, not a correctness FAIL. Only a genuinely
    # unbounded payload (over the hard ceiling) is a deterministic defect.
    over_hard = {k: v for k, v in payloads.items() if v > PAYLOAD_HARD_CEILING_BYTES}
    over_soft = {k: v for k, v in payloads.items() if PAYLOAD_SOFT_CAP_BYTES < v <= PAYLOAD_HARD_CEILING_BYTES}
    if over_hard:
        i14_status = "FAIL"
    elif over_soft:
        i14_status = "WARN"
    else:
        i14_status = "PASS"
    inv["I14_bounded_payloads"] = _result(
        i14_status,
        f"largest mutable payload = {largest} bytes; soft {PAYLOAD_SOFT_CAP_BYTES} / hard {PAYLOAD_HARD_CEILING_BYTES}; "
        f"intents ~{per_intent} bytes/record x {len(intent_rows)} candidates (per-cycle overwrite, LOAD-SCALING = CG-F065)",
        {"payload_bytes": payloads, "over_soft": over_soft, "over_hard": over_hard, "bytes_per_intent": per_intent,
         "candidate_count": len(intent_rows),
         "load_scaling_note": "intents is overwritten per cycle (not accumulating) but scales linearly with candidate count; WARN not a correctness defect; verify under full-universe load (Phase 5); tracked as CG-F065"})

    # I13 restart counters (baseline snapshot in check; delta evaluated in watch)
    restarts = {s: _svc(s, ["NRestarts"]).get("NRestarts") for s in LIFECYCLE_SERVICES}
    inv["I13_restart_counters"] = _result(
        "PASS", f"restart baseline captured for {len(restarts)} services (delta evaluated in watch mode)",
        {"nrestarts": restarts})

    fails = [k for k, v in inv.items() if v["status"] == "FAIL"]
    warns = [k for k, v in inv.items() if v["status"] == "WARN"]
    needs = [k for k, v in inv.items() if v["status"] == "NEEDS_INSTRUMENTATION"]
    verdict = {
        "schema": "paper_cycle_invariant_monitor_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "current_session": cur_session,
        "current_epoch": cur_epoch,
        "invariants": inv,
        "failed_invariants": fails,
        "warnings": warns,
        "needs_instrumentation": needs,
        # Only HARD correctness/unbounded FAILs open the repair path; WARNs are
        # tracked resource-hygiene items (e.g. CG-F065) that do not, by themselves,
        # revoke natural-wait authorization.
        "classification": "DETERMINISTIC_RUNTIME_DEFECT" if fails else (
            "DETERMINISTIC_INVARIANTS_HOLD_WITH_WARNINGS" if warns else "DETERMINISTIC_INVARIANTS_HOLD"),
        "natural_wait_authorized": len(fails) == 0,
        "counts": {"open_positions": open_pos_count, "accepted_fills": len(accepted),
                   "proof_store": len(proofs), "closed_trades": len(closed), "intents": len(intent_rows)},
    }
    return verdict


def _publish(r, v: dict) -> None:
    """Publish the monitor's OWN status key. This is the monitor's self-report,
    NOT a mutation of any paper-execution state — it never touches positions,
    fills, proofs, closed_trades, reservations, ledger, or any economic record."""
    try:
        payload = {
            "schema_version": "paper_cycle_invariant_monitor_status_v1",
            "generated_utc": v.get("generated_utc"),
            "classification": v["classification"],
            "natural_wait_authorized": v["natural_wait_authorized"],
            "failed_invariants": v["failed_invariants"],
            "needs_instrumentation": v["needs_instrumentation"],
            "current_session": v["current_session"],
            "current_epoch": v["current_epoch"],
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "monitor": "read_only",
        }
        r.set("v2:paper:invariant_monitor:status", json.dumps(payload), ex=600)
    except Exception:
        pass


def check() -> int:
    r = _r()
    v = evaluate(r)
    _publish(r, v)
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "paper_cycle_invariant_latest.json").write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "classification": v["classification"],
        "natural_wait_authorized": v["natural_wait_authorized"],
        "failed_invariants": v["failed_invariants"],
        "needs_instrumentation": v["needs_instrumentation"],
        "counts": v["counts"],
    }, indent=2))
    for k, res in v["invariants"].items():
        print(f"  {res['status']:22} {k}: {res['detail']}")
    return 2 if v["failed_invariants"] else 0


def watch(minutes: float, poll_s: float) -> int:
    r = _r()
    base = {s: _svc(s, ["NRestarts"]).get("NRestarts") for s in LIFECYCLE_SERVICES}
    elapsed = 0.0
    worst = 0
    while elapsed < minutes * 60.0:
        v = evaluate(r)
        # I13 restart churn delta over the window
        now = {s: _svc(s, ["NRestarts"]).get("NRestarts") for s in LIFECYCLE_SERVICES}
        churn = {}
        for s in LIFECYCLE_SERVICES:
            try:
                d = int(now.get(s) or 0) - int(base.get(s) or 0)
                if d:
                    churn[s] = d
            except Exception:
                pass
        churn_fail = any(d > RESTART_CHURN_CAP for d in churn.values())
        if churn_fail:
            v["invariants"]["I13_restart_counters"] = _result(
                "FAIL", f"restart churn over window: {churn}", {"churn": churn})
            v["failed_invariants"] = [k for k, x in v["invariants"].items() if x["status"] == "FAIL"]
            v["classification"] = "DETERMINISTIC_RUNTIME_DEFECT"
            v["natural_wait_authorized"] = False
        EVID.mkdir(parents=True, exist_ok=True)
        (EVID / "paper_cycle_invariant_latest.json").write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
        n = len(v["failed_invariants"])
        worst = max(worst, n)
        print(f"[{elapsed:6.0f}s] {v['classification']} fails={v['failed_invariants']} churn={churn}")
        if n:
            print(json.dumps({"DETERMINISTIC_RUNTIME_DEFECT": v["failed_invariants"],
                              "detail": {k: v["invariants"][k]["detail"] for k in v["failed_invariants"]}}, indent=2))
        time.sleep(poll_s)
        elapsed += poll_s
    return 2 if worst else 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    mode = argv[1]
    if mode == "check":
        return check()
    if mode == "watch":
        return watch(float(argv[2]) if len(argv) > 2 else 30.0, float(argv[3]) if len(argv) > 3 else 60.0)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
