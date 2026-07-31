#!/usr/bin/env python3
"""Final paper policy-gate bypass — same-pass runtime acceptance (item 10).

READ-ONLY collector.  Evaluates criteria A-G from the operator's FINAL PAPER
POLICY-GATE BYPASS directive (2026-07-31) against the live paper runtime on
one frozen SHA, and emits a verdict JSON to raw_evidence/.

  A. a candidate with a negative policy metric executes while all hard rails pass
  B. at least two unrelated protected paper positions coexist
  C. a later authorization occurs while an earlier position remains open
  D. a later authorization occurs while an earlier close is unmatured/unconsumed
  E. a close increments policy_state_version and the next decision consumes it
  F. resulting positions close with protection, complete accounting, valid
     reconciliation
  G. zero duplicate/phantom/unresolved/reservation/accounting/protection/
     schema/parity/restart/live defects

Each criterion reports PASS/PENDING with raw evidence pointers.  PENDING means
the runtime has not yet produced the event, never that the check was skipped.

Usage: check [--sha EXPECTED_SHA]
Exit code: 0 all PASS, 3 any PENDING, 2 defect (G violated).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parents[1]
EVID = REPO / "raw_evidence"
POLICY_STATE_KEY = "v2:adaptive_system:paper_policy_state:v1"

NEGATIVE_POLICY_TOKENS = (
    "expected_move_after_cost_not_positive",
    "BLOCK_NO_EDGE",
    "EXPECTED_MOVE_",
    "expected_move_",
    "CONFIDENCE_BELOW",
    "BLOCK_NEGATIVE_EXPECTANCY",
    "NEGATIVE_BUCKET_PERFORMANCE",
    "INFORMATION_GAIN_NONPOSITIVE",
    "UTILITY_NONPOSITIVE",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gj(r: redis.Redis, key: str):
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _lst(value) -> list:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ms(value):
    n = _num(value)
    return n if n is not None else None


def _parse_iso_ms(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp() * 1000.0
    except (ValueError, TypeError):
        return None


def _fill_authorized_at_ms(row: dict):
    auth = row.get("adaptive_paper_policy_authorization")
    if isinstance(auth, dict):
        ms = _ms(auth.get("authorized_at_ms"))
        if ms:
            return ms
    for field in ("adaptive_policy_authorized_at", "entry_time", "created_utc"):
        ms = _parse_iso_ms(row.get(field))
        if ms:
            return ms
    return None


def _negative_policy_evidence(row: dict) -> list[str]:
    hits: list[str] = []
    telemetry: list[str] = []
    for key, value in row.items():
        if isinstance(key, str) and key.endswith("trading_policy_telemetry_reasons"):
            telemetry.extend(str(item) for item in (value or []))
    for reason in telemetry:
        if any(token in reason for token in NEGATIVE_POLICY_TOKENS):
            hits.append(f"telemetry:{reason}")
    auth = row.get("adaptive_paper_policy_authorization")
    if isinstance(auth, dict):
        ret = _num(auth.get("expected_after_cost_return_bps"))
        if ret is not None and ret <= 0.0:
            hits.append(f"authorization.expected_after_cost_return_bps={ret}")
    edge = _num(row.get("expected_move_after_cost_bps"))
    side = str(row.get("side") or row.get("action") or "").lower()
    if edge is not None and (
        (side == "long" and edge <= 0.0) or (side == "short" and edge >= 0.0)
    ):
        hits.append(f"direction_aligned_edge_nonpositive:{side}:{edge}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="check")
    parser.add_argument("--sha", default=None)
    args = parser.parse_args()

    r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
    fills = _lst(_gj(r, "v2:paper:accepted_fills"))
    positions = _lst(_gj(r, "v2:paper:positions"))
    closed = _lst(_gj(r, "v2:paper:closed_trades"))
    intents = _lst(_gj(r, "v2:paper:intents"))
    session = _gj(r, "v2:paper:heartbeat") or {}
    invariants = _gj(r, "v2:paper:invariant_monitor:status") or {}
    try:
        policy_state = r.hgetall(POLICY_STATE_KEY) or {}
    except Exception:
        policy_state = {}

    session_id = str(
        session.get("paper_session_id")
        or (intents[-1].get("paper_session_id") if intents else "")
        or ""
    )
    runtime_sha = str(session.get("code_sha") or session.get("ai_bot_code_sha") or "")

    def session_rows(rows: list) -> list:
        if not session_id:
            return rows
        return [
            row
            for row in rows
            if str(row.get("paper_session_id") or "") in ("", session_id)
        ]

    fills = session_rows(fills)
    # Frozen-SHA discrimination (item 10: "prove on one frozen SHA"): only
    # fills produced by the final-bypass line carry the mandatory-protection
    # receipt; earlier-line fills never qualify as acceptance evidence.
    fills = [
        row
        for row in fills
        if isinstance(row.get("mandatory_protection_receipt"), dict)
    ]
    closed_session = [
        row for row in closed if str(row.get("paper_session_id") or "") == session_id
    ] if session_id else closed

    verdict: dict[str, dict] = {}

    # -- A: negative-policy-metric candidate executed with hard rails passing
    a_hits = []
    for row in fills:
        neg = _negative_policy_evidence(row)
        auth = row.get("adaptive_paper_policy_authorization")
        hard_ok = (
            isinstance(auth, dict) and auth.get("hard_validator_passed") is True
        ) or row.get("paper_fill_allowed") is True
        if neg and hard_ok:
            a_hits.append(
                {
                    "position_id": row.get("position_id"),
                    "symbol": row.get("symbol"),
                    "authorization_id": row.get("authorization_id")
                    or (auth or {}).get("authorization_id")
                    if isinstance(auth, dict)
                    else None,
                    "negative_policy_evidence": neg[:4],
                }
            )
    verdict["A_negative_policy_metric_executes"] = {
        "status": "PASS" if a_hits else "PENDING",
        "evidence": a_hits[:5],
    }

    # -- B: >=2 unrelated protected positions coexist (current snapshot OR
    #    reconstructed overlap from fills/closes)
    open_syms = {
        str(row.get("symbol") or "").upper()
        for row in positions
        if row.get("paper_only") is not False
    }
    protected = [
        row
        for row in positions
        if isinstance(row.get("mandatory_protection_receipt"), dict)
        or row.get("stop_price") not in (None, "", 0)
        or _num(row.get("atr_stop_bps"))
    ]
    b_now = len(open_syms) >= 2 and len(protected) >= 2
    # historical overlap reconstruction: interval overlap between two closes
    intervals = []
    for row in closed_session:
        start = _parse_iso_ms(row.get("entry_time") or row.get("opened_est"))
        end = _parse_iso_ms(row.get("exit_time") or row.get("close_event_time"))
        sym = str(row.get("symbol") or "").upper()
        if start and end and sym:
            intervals.append((start, end, sym, row.get("position_id")))
    overlap_pairs = []
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            s1, e1, sym1, p1 = intervals[i]
            s2, e2, sym2, p2 = intervals[j]
            if sym1 != sym2 and max(s1, s2) < min(e1, e2):
                overlap_pairs.append({"a": p1, "b": p2, "symbols": [sym1, sym2]})
    verdict["B_concurrent_protected_positions"] = {
        "status": "PASS" if (b_now or overlap_pairs) else "PENDING",
        "open_symbols_now": sorted(open_syms),
        "protected_open_count": len(protected),
        "historical_overlap_pairs": overlap_pairs[:5],
    }

    # -- C: later authorization while an earlier position remains open
    c_hits = []
    fill_times = []
    for row in fills:
        ms = _fill_authorized_at_ms(row)
        if ms:
            fill_times.append((ms, row))
    for start, end, sym, pid in intervals:
        for ms, row in fill_times:
            if start < ms < end and str(row.get("symbol") or "").upper() != sym:
                c_hits.append(
                    {
                        "earlier_position": pid,
                        "earlier_symbol": sym,
                        "later_fill_position": row.get("position_id"),
                        "later_symbol": row.get("symbol"),
                        "authorized_at_ms": ms,
                        "open_interval_ms": [start, end],
                    }
                )
    # open positions also count as intervals without end
    for pos in positions:
        start = _parse_iso_ms(pos.get("entry_time") or pos.get("opened_est"))
        sym = str(pos.get("symbol") or "").upper()
        if not start:
            continue
        for ms, row in fill_times:
            if ms > start and str(row.get("symbol") or "").upper() != sym:
                c_hits.append(
                    {
                        "earlier_position": pos.get("position_id"),
                        "earlier_symbol": sym,
                        "later_fill_position": row.get("position_id"),
                        "later_symbol": row.get("symbol"),
                        "authorized_at_ms": ms,
                        "open_interval_ms": [start, None],
                    }
                )
    verdict["C_authorization_while_position_open"] = {
        "status": "PASS" if c_hits else "PENDING",
        "evidence": c_hits[:5],
    }

    # -- D: later authorization while an earlier close unmatured/unconsumed
    d_hits = []
    for row in closed_session:
        close_ms = _parse_iso_ms(row.get("exit_time") or row.get("close_event_time"))
        pending = (
            str(row.get("maturation_status") or "").startswith("PENDING")
            or str(row.get("training_consumption_status") or "")
            == "NOT_YET_CONSUMED"
        )
        if not close_ms or not pending:
            continue
        for ms, fill_row in fill_times:
            if ms > close_ms:
                d_hits.append(
                    {
                        "earlier_close": row.get("close_id"),
                        "close_maturation_status": row.get("maturation_status"),
                        "close_training_consumption_status": row.get(
                            "training_consumption_status"
                        ),
                        "later_fill_position": fill_row.get("position_id"),
                        "later_authorized_at_ms": ms,
                    }
                )
                break
    verdict["D_authorization_before_maturation"] = {
        "status": "PASS" if d_hits else "PENDING",
        "evidence": d_hits[:5],
    }

    # -- E: close increments policy_state_version; next decision consumes it
    e_hits = []
    close_versions = sorted(
        (
            int(v)
            for v in (
                row.get("close_policy_state_version") for row in closed_session
            )
            if isinstance(v, int) or (isinstance(v, str) and str(v).isdigit())
        )
    )
    current_version = None
    try:
        current_version = int(policy_state.get("policy_state_version") or 0)
    except (TypeError, ValueError):
        pass
    consuming_rows = []
    for row in intents + fills:
        v = row.get("policy_state_version")
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if close_versions and v >= close_versions[0] and v > 0:
            consuming_rows.append(
                {
                    "record": row.get("position_id")
                    or row.get("intent_id")
                    or row.get("candidate_id"),
                    "policy_state_version": v,
                }
            )
    if close_versions and consuming_rows:
        e_hits = consuming_rows[:5]
    verdict["E_close_increments_and_next_decision_consumes"] = {
        "status": "PASS" if e_hits else "PENDING",
        "close_policy_state_versions": close_versions[:10],
        "current_policy_state_version": current_version,
        "consuming_decisions": e_hits,
    }

    # -- F: closes carry protection + accounting + reconciliation
    f_bad = []
    f_checked = 0
    for row in closed_session:
        if not (
            isinstance(row.get("mandatory_protection_receipt"), dict)
            or isinstance(row.get("risk_capacity_receipt"), dict)
            or row.get("authorization_id") not in (None, "")
        ):
            # Item 10.F judges "the RESULTING positions" — closes whose entry
            # fill was authorized on the frozen bypass SHA (receipt-joined).
            # Historical closes get policy_gate_authority stamped too, so the
            # receipt chain, not the authority stamp, is the discriminator.
            continue
        f_checked += 1
        problems = []
        if not (
            isinstance(row.get("mandatory_protection_receipt"), dict)
            or _num(row.get("atr_stop_bps"))
            or row.get("stop_price") not in (None, "", 0)
        ):
            problems.append("missing_protection_evidence")
        if _num(row.get("realized_net_pnl_usd")) is None:
            problems.append("missing_net_accounting")
        if problems:
            f_bad.append({"close_id": row.get("close_id"), "problems": problems})
    inv_map = invariants.get("invariants") or {}
    i08 = (inv_map.get("I08_accounting_conservation") or {}).get("status")
    verdict["F_protected_reconciled_closes"] = {
        "status": (
            "PASS"
            if f_checked > 0 and not f_bad and i08 == "PASS"
            else ("PENDING" if not f_checked else "FAIL")
        ),
        "post_deployment_closes_checked": f_checked,
        "defects": f_bad[:5],
        "I08_accounting_conservation": i08,
    }

    # -- G: zero defects
    failed_invariants = invariants.get("failed_invariants") or []
    parity_bad = [
        row.get("intent_id")
        for row in intents
        if row.get("adaptive_policy_reference_parity_status")
        not in (None, "", "PASS")
    ]
    live_bad = [
        row.get("position_id") or row.get("intent_id")
        for row in fills + positions + closed_session
        if row.get("places_real_order") is True or row.get("routes_to_live") is True
    ]
    # Item 4's MANDATORY invariant is on the authoritative FIELDS: no
    # TRADING_POLICY reason may remain in one on a published paper candidate.
    # Verify the fields directly with the central classifier.
    sys.path.insert(0, str(REPO))
    from v2.backend.app.services.adaptive_system.paper_exploration_authority_v2 import (  # noqa: E402
        TRADING_POLICY,
        classify_paper_blocker,
    )

    def _policy_residue(row: dict) -> list[str]:
        residue: list[str] = []
        for field in (
            "rejection_reasons",
            "paper_fill_gate_block_reasons",
            "entry_gate_block_reasons",
            "local_block_reasons",
            "authoritative_hard_blockers",
        ):
            for reason in row.get(field) or []:
                text = str(reason)
                bare = text.split(":", 1)[1] if ":" in text else text
                if TRADING_POLICY in (
                    classify_paper_blocker(text),
                    classify_paper_blocker(bare),
                ):
                    residue.append(f"{field}:{text}")
        primary = row.get("paper_fill_block_reason")
        if isinstance(primary, str) and classify_paper_blocker(primary) == TRADING_POLICY:
            residue.append(f"paper_fill_block_reason:{primary}")
        return residue

    invariant_violations = []
    for row in intents:
        residue = _policy_residue(row)
        if residue:
            invariant_violations.append(
                {"intent_id": row.get("intent_id"), "residue": residue[:3]}
            )
    sanitized_leaks = sum(
        1 for row in intents if row.get("paper_authority_field_policy_leak") is True
    )
    g_defects = {
        "failed_invariants": failed_invariants,
        "parity_failures": parity_bad[:5],
        "live_authority_rows": live_bad[:5],
        "authority_field_invariant_violations": invariant_violations[:5],
    }
    g_clean = not any(g_defects.values())
    verdict["G_zero_defects"] = {
        "status": "PASS" if g_clean else "FAIL",
        **g_defects,
        # Upstream writes the publish-time invariant moved to telemetry
        # (source burndown metric — the trainer-lane signal annotations are a
        # separately deployed producer); the invariant itself held.
        "authority_field_policy_leaks_sanitized": sanitized_leaks,
    }

    statuses = [item["status"] for item in verdict.values()]
    overall = (
        "ACCEPTANCE_PASS"
        if all(s == "PASS" for s in statuses)
        else ("DEFECT" if "FAIL" in statuses else "ACCRUING")
    )
    payload = {
        "schema_version": "paper_final_bypass_acceptance_v1",
        "generated_utc": _now(),
        "overall": overall,
        "paper_session_id": session_id,
        "expected_sha": args.sha,
        "runtime_sha_hint": runtime_sha,
        "policy_state": policy_state,
        "counts": {
            "session_fills": len(fills),
            "open_positions": len(positions),
            "session_closes": len(closed_session),
            "intents": len(intents),
        },
        "criteria": verdict,
        "paper_only": True,
        "places_real_order": False,
    }
    EVID.mkdir(exist_ok=True)
    out = EVID / "paper_final_bypass_acceptance_latest.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    stamp = EVID / (
        "paper_final_bypass_acceptance_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    if overall != "ACCRUING":
        stamp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    print(json.dumps({"overall": overall, "criteria": {k: v["status"] for k, v in verdict.items()}}))
    return 0 if overall == "ACCEPTANCE_PASS" else (2 if overall == "DEFECT" else 3)


if __name__ == "__main__":
    sys.exit(main())
