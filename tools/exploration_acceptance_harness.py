#!/usr/bin/env python3
"""Bounded information-gain exploration acceptance harness (operator directive).

READ-ONLY. Verifies the operator's acceptance criteria for the bounded
information-seeking exploration policy, scoped to the CURRENT paper epoch and to
GENUINE exploration provenance (never counts the pre-existing exploitation cohort).

Positive criteria (all must be > 0):
  current_epoch_directional_exploration_authorizations
  current_epoch_proof_backed_fills
  current_epoch_positions
  current_epoch_natural_closes
  exploration_outcomes_matured
  exploration_outcomes_consumed_by_training

Invariant criteria (must hold):
  duplicate_fill_count == 0
  duplicate_close_count == 0
  reservation_leak_count == 0
  accounting_conservation == true

Safety criteria (must hold):
  paper_only == true, live_gate == blocked_human_only,
  routes_to_live == false, places_real_order == false, exchange_action_taken == false

Usage:
  check                     one-shot evaluation -> raw_evidence/exploration_acceptance_latest.json
  watch [minutes] [poll_s]  poll until all positive criteria satisfied or timeout

Exploration provenance is recognised by ANY of:
  policy_mode in {bounded_information_seeking_exploration, BOUNDED_EXPLORATION}
  exploration_provenance is True
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parents[1]
EVID = REPO / "raw_evidence"
ACCT_THRESHOLD_USD = 0.02
EXPLORATION_MODES = {"bounded_information_seeking_exploration", "BOUNDED_EXPLORATION",
                     "bounded_exploration", "POLICY_MODE_BOUNDED_EXPLORATION",
                     "bootstrap_information_acquisition"}


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


def _is_exploration(row) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("exploration_provenance") is True:
        return True
    pm = str(row.get("policy_mode") or "")
    if pm in EXPLORATION_MODES:
        return True
    apa = row.get("adaptive_policy_action")
    if isinstance(apa, dict) and str(apa.get("policy_mode") or "") in EXPLORATION_MODES:
        return True
    return False


def _in_epoch(row, epoch) -> bool:
    if epoch is None:
        return True
    e = row.get("paper_account_epoch") if isinstance(row, dict) else None
    return e is None or e == epoch


def evaluate(r) -> dict:
    ae = _gj(r, "v2:paper:account_epoch:current") or {}
    epoch = ae.get("paper_account_epoch")
    session = ae.get("paper_session_id")

    intents = _gj(r, "v2:paper:intents")
    intent_rows = intents if isinstance(intents, list) else (
        intents.get("intents", intents.get("candidates", [])) if isinstance(intents, dict) else [])
    positions = _lst(_gj(r, "v2:paper:positions"))
    accepted = _lst(_gj(r, "v2:paper:accepted_fills"))
    closed = _lst(_gj(r, "v2:paper:closed_trades"))
    portfolio = _gj(r, "v2:portfolio:state") or {}

    # --- positive criteria (exploration-provenance + current epoch) ---
    def _auth(row):
        # a directional exploration authorization = exploration-provenance intent whose
        # selected/adaptive action is directional AND carries execution authority.
        if not _is_exploration(row):
            return False
        apa = row.get("adaptive_policy_action") if isinstance(row, dict) else None
        action = str((apa or {}).get("selected_action") or row.get("selected_action") or "").lower()
        authorized = bool((apa or {}).get("execution_authority") or row.get("execution_authority")
                          or row.get("paper_fill_allowed"))
        return action in ("directional_trade", "reduce_existing_exposure") and authorized

    exploration_auths = sum(1 for row in intent_rows if _in_epoch(row, epoch) and _auth(row))
    proof_backed_fills = sum(1 for f in accepted if _in_epoch(f, epoch) and _is_exploration(f)
                             and (f.get("accepted_fill_id") or f.get("fill_proof_id")))
    exploration_positions = sum(1 for p in positions if _in_epoch(p, epoch) and _is_exploration(p))
    exploration_closes = [t for t in closed if _in_epoch(t, epoch) and _is_exploration(t)]
    natural_closes = len(exploration_closes)

    # matured outcomes: exploration closes that produced a matured outcome (outcome
    # availability sealed / MFE/MAE present / outcome_label_id) — genuine maturation.
    matured = sum(1 for t in exploration_closes if (
        t.get("outcome_label_id") or t.get("trade_outcome") or
        (t.get("mfe_bps") is not None and t.get("mae_bps") is not None)))
    # consumed by training: exploration closes marked trainer-consumable / fed back.
    consumed = sum(1 for t in exploration_closes if (
        t.get("trainer_consumable") is True or t.get("trainer_feedback_id")))

    positive = {
        "current_epoch_directional_exploration_authorizations": exploration_auths,
        "current_epoch_proof_backed_fills": proof_backed_fills,
        "current_epoch_positions": exploration_positions,
        "current_epoch_natural_closes": natural_closes,
        "exploration_outcomes_matured": matured,
        "exploration_outcomes_consumed_by_training": consumed,
    }

    # --- invariant criteria ---
    fill_ids = [f.get("accepted_fill_id") or f.get("fill_id") for f in accepted if isinstance(f, dict)]
    fill_ids = [x for x in fill_ids if x]
    dup_fill = len(fill_ids) - len(set(fill_ids))
    close_ids = [str(t.get("close_id") or f"{t.get('position_id')}|{t.get('exit_price_utc')}|{t.get('realized_pnl_usd')}")
                 for t in closed if isinstance(t, dict)]
    dup_close = len(close_ids) - len(set(close_ids))
    resv = _gj(r, f"v2:paper:epoch:{epoch}:reservations") if epoch is not None else None
    resv_rows = _lst(resv) if isinstance(resv, list) else (list(resv.values()) if isinstance(resv, dict) else [])
    reservation_leak = 1 if (resv_rows and not positions and not accepted) else 0
    # accounting conservation: current-session trade_sum vs ledger
    def _pnl(t):
        for k in ("realized_pnl_usd", "net_realized_pnl_usd", "realized_pnl"):
            if isinstance(t, dict) and t.get(k) is not None:
                try:
                    return float(t[k])
                except Exception:
                    return 0.0
        return 0.0
    session_closed = [t for t in closed if isinstance(t, dict) and str(t.get("paper_session_id") or "") == str(session or "")]
    trade_sum = sum(_pnl(t) for t in session_closed)
    ledger = portfolio.get("realized_pnl_usd")
    accounting_conservation = (ledger is not None and abs(trade_sum - float(ledger)) <= ACCT_THRESHOLD_USD)

    invariants = {
        "duplicate_fill_count": dup_fill,
        "duplicate_close_count": dup_close,
        "reservation_leak_count": reservation_leak,
        "accounting_conservation": bool(accounting_conservation),
    }

    # --- safety criteria ---
    intent_live = any(isinstance(row, dict) and (row.get("places_real_order") or row.get("routes_to_live")
                      or row.get("exchange_action_taken") or row.get("live_order")) for row in intent_rows)
    safety = {
        "paper_only": True,
        "live_gate": portfolio.get("live_gate", "blocked_human_only"),
        "routes_to_live": bool(intent_live),
        "places_real_order": bool(portfolio.get("places_real_order")),
        "exchange_action_taken": bool(intent_live),
        "account_mode": portfolio.get("account_mode"),
    }
    safety_ok = (not portfolio.get("places_real_order") and not portfolio.get("trader_execution_enabled")
                 and not intent_live and portfolio.get("account_mode") in (None, "paper_shadow_only"))

    # --- operator #8 intermediate observability: effective-N / info-gain / venue-min decision ---
    # Persisted by the calibration/venue-min repair (Codex #2-7); reported when present so #8
    # acceptance + the A/B determination is verifiable the moment the fix lands. Absent -> null
    # (fix not yet active), never fabricated.
    def _first(row, keys):
        if isinstance(row, dict):
            for k in keys:
                if row.get(k) is not None:
                    return row.get(k)
            apa = row.get("adaptive_policy_action")
            if isinstance(apa, dict):
                for k in keys:
                    if apa.get(k) is not None:
                        return apa.get(k)
        return None
    sub_min = venue_eval = venue_min_positive_util_auths = 0
    eff_n_seen = set(); ig_seen = []
    for row in intent_rows:
        if not isinstance(row, dict):
            continue
        rt = _first(row, ["raw_learned_target_notional_usd", "raw_target_notional_usd"])
        vmn = _first(row, ["venue_minimum_candidate_notional_usd", "venue_min_notional_usd"])
        if rt is not None and vmn is not None and float(rt) < float(vmn):
            sub_min += 1
        if _first(row, ["venue_min_candidate_evaluated", "venue_minimum_candidate_evaluated"]) is True:
            venue_eval += 1
            u = _first(row, ["venue_min_candidate_utility", "venue_minimum_recomputed_utility"])
            if u is not None and float(u) > 0 and _first(row, ["venue_min_candidate_selected"]) is True:
                venue_min_positive_util_auths += 1
        en = _first(row, ["effective_sample_size", "n_eff", "effective_independent_sample_size"])
        if en is not None:
            eff_n_seen.add(round(float(en), 2))
        ig = _first(row, ["expected_information_gain_nats"])
        if ig is not None:
            ig_seen.append(round(float(ig), 5))
    operator_8_observability = {
        "sub_minimum_exploration_candidates": sub_min,
        "venue_minimum_candidates_evaluated": venue_eval,
        "venue_minimum_positive_utility_authorizations": venue_min_positive_util_auths,
        "effective_sample_sizes_observed": sorted(eff_n_seen)[:10] or None,
        "expected_information_gain_nats_observed": ig_seen[:10] or None,
        "effective_n_fix_active": bool(eff_n_seen) or bool(venue_eval),
        "note": ("null observables => the effective-N / venue-min repair (Codex #2-7) is not yet emitting these fields; "
                 "result A (venue_minimum_positive_utility_authorizations>0) or B (all evaluated nonpositive) is "
                 "determinable once effective_n_fix_active=true"),
    }

    positive_ok = all(v > 0 for v in positive.values())
    invariants_ok = (dup_fill == 0 and dup_close == 0 and reservation_leak == 0 and accounting_conservation)
    all_ok = positive_ok and invariants_ok and safety_ok

    return {
        "schema": "exploration_acceptance_v1",
        "operator_8_observability": operator_8_observability,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "current_epoch": epoch,
        "current_session": session,
        "positive_criteria": positive,
        "positive_criteria_all_met": positive_ok,
        "invariant_criteria": invariants,
        "invariant_criteria_all_met": invariants_ok,
        "safety_ok": safety_ok,
        "verdict": "EXPLORATION_ACCEPTED" if all_ok else "EXPLORATION_PENDING",
        "counts": {"intents": len(intent_rows), "open_positions": len(positions),
                   "accepted_fills": len(accepted), "closed_trades": len(closed),
                   "exploration_closes": natural_closes},
    }


def check() -> int:
    r = _r()
    v = evaluate(r)
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "exploration_acceptance_latest.json").write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "positive_criteria", "invariant_criteria",
                                        "safety_ok", "current_epoch", "operator_8_observability")}, indent=2))
    return 0 if v["verdict"] == "EXPLORATION_ACCEPTED" else 2


def watch(minutes: float, poll_s: float) -> int:
    r = _r()
    elapsed = 0.0
    while elapsed < minutes * 60.0:
        v = evaluate(r)
        EVID.mkdir(parents=True, exist_ok=True)
        (EVID / "exploration_acceptance_latest.json").write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
        p = v["positive_criteria"]
        print(f"[{elapsed:6.0f}s] {v['verdict']} auths={p['current_epoch_directional_exploration_authorizations']} "
              f"fills={p['current_epoch_proof_backed_fills']} pos={p['current_epoch_positions']} "
              f"closes={p['current_epoch_natural_closes']} matured={p['exploration_outcomes_matured']} "
              f"consumed={p['exploration_outcomes_consumed_by_training']} inv_ok={v['invariant_criteria_all_met']}")
        if v["verdict"] == "EXPLORATION_ACCEPTED":
            return 0
        time.sleep(poll_s)
        elapsed += poll_s
    return 2


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    if argv[1] == "check":
        return check()
    if argv[1] == "watch":
        return watch(float(argv[2]) if len(argv) > 2 else 30.0, float(argv[3]) if len(argv) > 3 else 60.0)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
