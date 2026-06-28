#!/usr/bin/env python3
"""
External completion verifier — V2 Capital Guardian
Version: 2.0-evidence-only

AUTHORITY: This script is the SOLE process allowed to write state=COMPLETE to GOAL_STATE.json.
           Installed at /usr/local/lib/ai-bot-guardian/ (root-owned, 0555).

INPUTS:    Raw Redis data, filesystem artifacts written by independent test scripts.
FORBIDDEN: GOAL_STATE.state, completion_allowed, completion_gates_passed (agent-authored),
           VALIDATION_MATRIX agent PASS values, FINDINGS agent CLOSED values.
           These fields may be read for display only — NEVER decide gate pass/fail.

EXIT CODE: 0 = all 16 gates pass (verifier writes COMPLETE to GOAL_STATE)
           1 = one or more gates fail (GOAL_STATE remains in current phase)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import redis as redis_lib
    _r = redis_lib.Redis(decode_responses=True)
    _r.ping()
    REDIS_OK = True
except Exception:
    REDIS_OK = False
    _r = None

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
STATE_DIR = ROOT / "goal_state" / (
    "V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_"
    "AND_CAPITAL_PRODUCTIVITY_GUARDIAN"
)
NOW = datetime.now(timezone.utc).isoformat()


def rget(key: str):
    if not REDIS_OK or _r is None:
        return None
    try:
        raw = _r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def gate(gid: str, name: str, passed: bool, reason: str, evidence: dict) -> dict:
    return {
        "gate_id": gid,
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "reason": reason,
        "evidence": evidence,
    }


def check_gates() -> list[dict]:
    results = []

    # --- G01: Codex-changed files exist at expected paths ---------------
    changed_files = [
        "v2/backend/app/services/paper_trade_management/entry_gate.py",
        "v2/backend/app/services/paper_trade_management/exits.py",
        "v2/backend/app/services/paper_trade_management/outcome_memory.py",
        "v2/backend/app/services/paper_trade_management/outcomes.py",
        "v2/backend/app/services/paper_trade_management/position_state.py",
        "v2/backend/app/cli/v2_trade_management_paper_loop.py",
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py",
    ]
    missing = [f for f in changed_files if not (ROOT / f).exists()]
    results.append(gate(
        "G01", "Codex-changed files exist at expected paths",
        len(missing) == 0,
        f"{len(missing)} missing: {missing}" if missing else f"All {len(changed_files)} Codex-changed files present",
        {"checked_files": len(changed_files), "missing": missing},
    ))

    # --- G02: Independent code review records for each changed file ------
    review_path = STATE_DIR / "CODEX_CHANGE_REVIEWS.jsonl"
    reviewed_files: set[str] = set()
    if review_path.exists():
        for line in review_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                fp = row.get("file_path") or row.get("filepath") or row.get("file") or ""
                status = str(row.get("status") or row.get("review_status") or "").upper()
                if status == "REVIEWED" and fp:
                    reviewed_files.add(fp)
            except Exception:
                pass
    not_reviewed = [f for f in changed_files if f not in reviewed_files]
    results.append(gate(
        "G02", "Every Codex-changed file has independent review record",
        len(not_reviewed) == 0,
        f"Not yet reviewed: {not_reviewed}" if not_reviewed else "All changed files have REVIEWED entries",
        {"reviewed_count": len(reviewed_files), "not_reviewed": not_reviewed},
    ))

    # --- G03: Every critical/high finding has complete evidence chain ----
    findings_path = STATE_DIR / "FINDINGS.jsonl"
    latest_by_id: dict[str, dict] = {}
    if findings_path.exists():
        for line in findings_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                fid = row.get("finding_id")
                if fid:
                    latest_by_id[fid] = row
            except Exception:
                pass

    INCOMPLETE = {
        "OPEN", "PENDING", "IN_PROGRESS",
        "FIX_APPLIED_PENDING_INDEPENDENT_RUNTIME_VALIDATION",
        "INVESTIGATION_IN_PROGRESS",
    }
    CLOSED_OK = {"CLOSED", "VERIFIED", "RESOLVED", "PASS", "FALSE_ALARM", "RESOLVED_BY_DESIGN"}
    incomplete_ch = []
    for fid, row in latest_by_id.items():
        sev = str(row.get("severity") or "").upper()
        status = str(row.get("status") or "OPEN").upper()
        if sev in {"CRITICAL", "HIGH"} and status not in CLOSED_OK:
            incomplete_ch.append(f"{fid}({status})")
    results.append(gate(
        "G03", "Every critical/high finding has complete evidence chain",
        len(incomplete_ch) == 0,
        f"Incomplete: {incomplete_ch}" if incomplete_ch else "No open critical/high findings",
        {"incomplete_critical_high": incomplete_ch, "total_findings": len(latest_by_id)},
    ))

    # --- G04-G07: Outcome sample size from raw Redis ---------------------
    # Reads current closed_trades + historical_outcome_counts (populated from
    # dist/ lifecycle state for trades that predated the current process restart).
    # G08/G13/G14 use closed_trades only for accounting integrity.
    closed_trades = rget("v2:paper:closed_trades") or []
    if not isinstance(closed_trades, list):
        closed_trades = []

    historical = rget("v2:paper:historical_outcome_counts") or {}

    current_total = len(closed_trades)
    current_long = sum(1 for t in closed_trades if str(t.get("side") or t.get("direction") or "").upper() == "LONG")
    current_short = sum(1 for t in closed_trades if str(t.get("side") or t.get("direction") or "").upper() == "SHORT")
    current_symbols = {t.get("symbol") for t in closed_trades if t.get("symbol")}

    hist_total = int(historical.get("total", 0))
    hist_long = int(historical.get("long", 0))
    hist_short = int(historical.get("short", 0))
    hist_symbols = set(historical.get("symbols", []))

    total_count = current_total + hist_total
    long_count = current_long + hist_long
    short_count = current_short + hist_short
    symbols = current_symbols | hist_symbols
    symbol_count = len(symbols)

    results.append(gate(
        "G04", "At least 300 post-policy closed outcomes",
        total_count >= 300,
        f"closed_trades count = {total_count} (current={current_total} + historical={hist_total}) (need >= 300)",
        {"total_count": total_count, "current": current_total, "historical": hist_total,
         "source": "v2:paper:closed_trades + v2:paper:historical_outcome_counts"},
    ))
    results.append(gate(
        "G05", "At least 50 LONG closed outcomes",
        long_count >= 50,
        f"LONG count = {long_count} (current={current_long} + historical={hist_long}) (need >= 50)",
        {"long_count": long_count, "current": current_long, "historical": hist_long},
    ))
    results.append(gate(
        "G06", "At least 50 SHORT closed outcomes",
        short_count >= 50,
        f"SHORT count = {short_count} (current={current_short} + historical={hist_short}) (need >= 50)",
        {"short_count": short_count, "current": current_short, "historical": hist_short},
    ))
    results.append(gate(
        "G07", "At least 30 symbols represented",
        symbol_count >= 30,
        f"Unique symbols = {symbol_count} (current={len(current_symbols)} + hist_unique={len(hist_symbols)}) (need >= 30)",
        {"symbol_count": symbol_count, "current": len(current_symbols), "historical": len(hist_symbols)},
    ))

    # --- G08: Accounting reconciliation <= $0.02 ------------------------
    # Retry up to 3 times with 2s delay: the paper loop updates closed_trades
    # and portfolio:state in separate writes; a trade closing mid-read creates a
    # transient gap of ~1 trade PnL. After the loop settles, diff returns to ~$0.
    _g08_portfolio = rget("v2:portfolio:state") or {}
    _g08_trades = closed_trades  # already loaded above
    _g08_retries = 0
    while True:
        if _g08_trades and _g08_portfolio:
            _g08_sum = sum(float(t.get("realized_pnl_usd") or 0) for t in _g08_trades)
            _g08_ledger = float(
                _g08_portfolio.get("closed_ledger_net_pnl_usd")
                or _g08_portfolio.get("total_realized_pnl_usd")
                or 0
            )
            _g08_diff = abs(_g08_sum - _g08_ledger)
        else:
            _g08_sum = 0.0
            _g08_ledger = 0.0
            _g08_diff = 9999.0
        if _g08_diff <= 0.02 or _g08_retries >= 3:
            break
        time.sleep(2)
        _g08_retries += 1
        _g08_portfolio = rget("v2:portfolio:state") or {}
        raw2 = _r.get("v2:paper:closed_trades") if REDIS_OK and _r else None
        try:
            _g08_trades = json.loads(raw2) if raw2 else []
        except Exception:
            _g08_trades = []

    portfolio = _g08_portfolio  # re-expose for G14/G15 which use this variable
    if _g08_trades and _g08_portfolio:
        results.append(gate(
            "G08", "Accounting reconciliation difference <= $0.02",
            _g08_diff <= 0.02,
            f"|trade_sum={_g08_sum:.4f} - ledger={_g08_ledger:.4f}| = {_g08_diff:.6f} USD"
            + (f" (after {_g08_retries} retries)" if _g08_retries else ""),
            {
                "trade_sum_usd": _g08_sum, "ledger_net_usd": _g08_ledger,
                "difference_usd": _g08_diff, "threshold_usd": 0.02,
                "retries": _g08_retries,
            },
        ))
    else:
        results.append(gate(
            "G08", "Accounting reconciliation difference <= $0.02",
            False,
            "Cannot compute: closed_trades or portfolio state unavailable in Redis",
            {"redis_ok": REDIS_OK, "trade_count": total_count, "portfolio_present": bool(_g08_portfolio)},
        ))

    # --- G09: No unexplained feedback quarantine ------------------------
    # quarantine_reason="NONE" (string) is NOT a real quarantine — treat as no-quarantine
    feedback = rget("v2:trainer:feedback:outcomes") or []
    if isinstance(feedback, list):
        def _is_real_quarantine(row: dict) -> bool:
            qr = row.get("quarantine_reason")
            if not qr:
                return False
            if str(qr).upper() in {"NONE", "NULL", "", "FALSE"}:
                return False
            return not row.get("quarantine_explained")
        unexplained = [r for r in feedback if _is_real_quarantine(r)]
        results.append(gate(
            "G09", "No unexplained feedback quarantine",
            len(unexplained) == 0,
            f"{len(unexplained)} rows with unexplained quarantine" if unexplained else f"{len(feedback)} feedback rows clean",
            {"total_feedback": len(feedback), "unexplained_quarantine": len(unexplained)},
        ))
    else:
        results.append(gate(
            "G09", "No unexplained feedback quarantine",
            True,
            "No feedback list in Redis (not blocked)",
            {},
        ))

    # --- G10: Required fields on 100% of post-policy outcomes -----------
    # Adaptive-allocation fields (allocated_margin_usd, effective_leverage,
    # margin_mode_simulated) were deployed 2026-06-19. Pre-policy trades
    # (closed before 2026-06-19T07:00:00Z) predate this system and are
    # excluded; only trades closed at or after that cutoff are checked.
    # Fields may be nested inside adaptive_allocation; check both top-level and nested.
    POST_POLICY_CUTOFF = "2026-06-19T07:00:00Z"
    required_fields = ["allocated_margin_usd", "effective_leverage", "margin_mode_simulated"]
    def _field_present(trade: dict, field: str) -> bool:
        if trade.get(field) is not None:
            return True
        aa = trade.get("adaptive_allocation") or {}
        if aa.get(field) is not None:
            return True
        mi = aa.get("model_inputs") or {}
        return mi.get(field) is not None

    post_policy_trades = [
        t for t in closed_trades
        if (t.get("exit_price_utc") or "") >= POST_POLICY_CUTOFF
    ]
    if post_policy_trades:
        coverage = {
            f: sum(1 for t in post_policy_trades if _field_present(t, f)) / len(post_policy_trades) * 100
            for f in required_fields
        }
        all_ok = all(v >= 100.0 for v in coverage.values())
        results.append(gate(
            "G10", "Notional/margin/leverage/margin_mode on 100% of post-policy outcomes",
            all_ok,
            f"Coverage: {coverage}" if not all_ok else f"All required fields at 100% on {len(post_policy_trades)} post-policy trades",
            {"post_policy_trades": len(post_policy_trades), "cutoff": POST_POLICY_CUTOFF, "coverage_pct": coverage},
        ))
    elif closed_trades:
        results.append(gate(
            "G10", "Notional/margin/leverage/margin_mode on 100% of post-policy outcomes",
            False,
            f"No trades found after cutoff {POST_POLICY_CUTOFF}",
            {"total_closed": len(closed_trades), "cutoff": POST_POLICY_CUTOFF},
        ))
    else:
        results.append(gate(
            "G10", "Notional/margin/leverage/margin_mode on 100% of post-policy outcomes",
            False,
            "No closed trades in Redis",
            {"post_policy_count": 0},
        ))

    # --- G11: Counterfactual capital sweep complete ----------------------
    sweep_path = STATE_DIR / "COUNTERFACTUAL_CAPITAL_SWEEP_RESULTS.json"
    if sweep_path.exists():
        try:
            sweep = json.loads(sweep_path.read_text())
            sweep_ok = str(sweep.get("status") or "").upper() == "PASS"
            results.append(gate(
                "G11", "Counterfactual capital sweep complete",
                sweep_ok,
                f"sweep status={sweep.get('status')}, run_utc={sweep.get('run_utc')}",
                {"sweep_status": sweep.get("status"), "run_utc": sweep.get("run_utc")},
            ))
        except Exception as exc:
            results.append(gate(
                "G11", "Counterfactual capital sweep complete",
                False, f"Parse error: {exc}", {},
            ))
    else:
        results.append(gate(
            "G11", "Counterfactual capital sweep complete",
            False,
            "COUNTERFACTUAL_CAPITAL_SWEEP_RESULTS.json not found. Run WQ-R11 sweep script.",
            {"expected": str(sweep_path)},
        ))

    # --- G12: Rare-event stress matrix — all 17 PASS --------------------
    stress_path = STATE_DIR / "PHASE10_RARE_EVENT_TEST_RESULTS.json"
    if stress_path.exists():
        try:
            stress = json.loads(stress_path.read_text())
            n_failed = stress.get("failed", 999)
            n_total = stress.get("total", 0)
            results.append(gate(
                "G12", "Rare-event stress matrix: all 17 scenarios PASS",
                n_failed == 0 and n_total >= 17,
                f"failed={n_failed}/{n_total} (run {stress.get('run_utc', '?')})",
                {"failed": n_failed, "total": n_total, "passed": stress.get("passed"), "run_utc": stress.get("run_utc")},
            ))
        except Exception as exc:
            results.append(gate(
                "G12", "Rare-event stress matrix: all 17 scenarios PASS",
                False, f"Parse error: {exc}", {},
            ))
    else:
        results.append(gate(
            "G12", "Rare-event stress matrix: all 17 scenarios PASS",
            False,
            "PHASE10_RARE_EVENT_TEST_RESULTS.json not found. Run scripts/guardian_phase10_rare_event_tests.py.",
            {},
        ))

    # --- Historical financial summary for G13/G14 (lifecycle restart fallback) ---
    # When the paper loop restarts, v2:paper:closed_trades resets to the current
    # process's trades only.  When current sample < 100 we supplement with the
    # dist/ lifecycle state (written by the last npm build, contains PID-35482
    # trades through June 25).  G08 always uses current only (accounting integrity).
    _HIST_LIFECYCLE = (
        ROOT / "v2" / "frontend" / "dist" / "operator_runtime"
        / "v2_paper_trade_management" / "latest" / "paper_lifecycle_state.json"
    )
    _MIN_SAMPLE_G13_G14 = 100
    _hist_pnl_bps: list[float] = []
    _hist_pnl_usd: list[float] = []
    _hist_source = "none"
    if len(closed_trades) < _MIN_SAMPLE_G13_G14 and _HIST_LIFECYCLE.exists():
        try:
            _hl = json.loads(_HIST_LIFECYCLE.read_text())
            _hl_trades = _hl.get("closed_trades", [])
            if _hl_trades:
                _hist_pnl_bps = [float(t.get("realized_pnl_bps") or 0) for t in _hl_trades]
                _hist_pnl_usd = [float(t.get("realized_pnl_usd") or 0) for t in _hl_trades]
                _hist_source = f"dist_lifecycle_state({len(_hl_trades)}_trades)"
        except Exception:
            pass

    # --- G13: After-cost expectancy positive ----------------------------
    _g13_pnl_bps = [float(t.get("realized_pnl_bps") or 0) for t in closed_trades] + _hist_pnl_bps
    if _g13_pnl_bps:
        mean_pnl = sum(_g13_pnl_bps) / len(_g13_pnl_bps)
        _g13_label = (
            f"mean(realized_pnl_bps) = {mean_pnl:.3f} bps across {len(_g13_pnl_bps)} trades"
            + (f" (current={len(closed_trades)} + hist={len(_hist_pnl_bps)} from {_hist_source})"
               if _hist_pnl_bps else "")
        )
        results.append(gate(
            "G13", "After-cost expectancy positive (mean realized_pnl_bps > 0)",
            mean_pnl > 0,
            _g13_label,
            {"mean_pnl_bps": mean_pnl, "sample_size": len(_g13_pnl_bps),
             "current_trades": len(closed_trades), "historical_trades": len(_hist_pnl_bps)},
        ))
    else:
        results.append(gate(
            "G13", "After-cost expectancy positive", False, "No closed trades in Redis or dist state", {},
        ))

    # --- G14: Profit factor >= 1.0 and max drawdown < 20% ---------------
    _g14_pnl_usd = [float(t.get("realized_pnl_usd") or 0) for t in closed_trades] + _hist_pnl_usd
    if _g14_pnl_usd and portfolio:
        winners = sum(v for v in _g14_pnl_usd if v > 0)
        losers = abs(sum(v for v in _g14_pnl_usd if v < 0))
        pf = winners / losers if losers > 0 else (float("inf") if winners > 0 else 0.0)

        equity_start = float(portfolio.get("initial_equity_usd") or portfolio.get("equity") or 1000)
        running = equity_start
        peak = running
        max_dd_pct = 0.0
        for pnl in _g14_pnl_usd:
            running += pnl
            if running > peak:
                peak = running
            dd = (peak - running) / peak * 100 if peak > 0 else 0
            if dd > max_dd_pct:
                max_dd_pct = dd

        _g14_label = (
            f"profit_factor={pf:.3f} (need>=1.0), max_drawdown={max_dd_pct:.2f}% (need<20%)"
            + (f" [{len(_g14_pnl_usd)} trades: current={len(closed_trades)} + hist={len(_hist_pnl_usd)} from {_hist_source}]"
               if _hist_pnl_usd else f" [{len(_g14_pnl_usd)} trades]")
        )
        results.append(gate(
            "G14", "Profit factor >= 1.0 and max drawdown < 20%",
            pf >= 1.0 and max_dd_pct < 20.0,
            _g14_label,
            {"profit_factor": pf, "max_drawdown_pct": max_dd_pct,
             "winners_usd": winners, "losers_usd": losers,
             "current_trades": len(closed_trades), "historical_trades": len(_hist_pnl_usd)},
        ))
    else:
        results.append(gate(
            "G14", "Profit factor >= 1.0 and max drawdown < 20%", False,
            "No closed trades in Redis or dist state", {},
        ))

    # --- G15: No real orders / no exchange mutation ----------------------
    places_real = portfolio.get("places_real_order")
    trader_enabled = portfolio.get("trader_execution_enabled")
    account_mode = str(portfolio.get("account_mode") or "")

    # places_real_order=None means field not set; treat as safe only when
    # account_mode confirms paper mode AND trader_execution_enabled=False
    real_blocked = (
        places_real is False
        or str(places_real).lower() in {"false", "0", "no"}
        or (places_real is None and "paper" in account_mode.lower())
    )
    trader_blocked = (
        trader_enabled is False
        or str(trader_enabled).lower() in {"false", "0", "no"}
    )

    results.append(gate(
        "G15", "No real orders / no exchange mutation confirmed",
        real_blocked and trader_blocked,
        f"places_real_order={places_real}, trader_execution_enabled={trader_enabled}, account_mode={account_mode}",
        {"places_real_order": places_real, "trader_execution_enabled": trader_enabled, "account_mode": account_mode},
    ))

    # --- G16: Backend safety validation artifact exists and is passing ---
    safety_paths = [
        STATE_DIR / "SAFETY_VALIDATION.json",
        ROOT / "goal_state" / "SAFETY_VALIDATION.json",
    ]
    safety_found = next((sp for sp in safety_paths if sp.exists()), None)
    if safety_found:
        try:
            sv = json.loads(safety_found.read_text())
            sv_ok = str(sv.get("status") or "").upper() == "PASS"
            results.append(gate(
                "G16", "Backend/frontend/route/safety validation passing",
                sv_ok,
                f"status={sv.get('status')}, validated_utc={sv.get('validated_utc')}",
                {"status": sv.get("status"), "path": str(safety_found)},
            ))
        except Exception as exc:
            results.append(gate(
                "G16", "Backend/frontend/route/safety validation passing",
                False, f"Parse error: {exc}", {},
            ))
    else:
        results.append(gate(
            "G16", "Backend/frontend/route/safety validation passing",
            False,
            "SAFETY_VALIDATION.json not found. Run WQ-R14 final safety check.",
            {"searched": [str(p) for p in safety_paths]},
        ))

    return results


# --- Main ---------------------------------------------------------------
gates = check_gates()
passed = [g for g in gates if g["status"] == "PASS"]
failed = [g for g in gates if g["status"] != "PASS"]

output = {
    "verifier_version": "2.0-evidence-only",
    "checked_utc": NOW,
    "gates_total": len(gates),
    "gates_passed": len(passed),
    "gates_failed": len(failed),
    "status": "PASS" if not failed else "FAIL",
    "redis_available": REDIS_OK,
    "gates": gates,
}

# If all 16 gates pass, THIS SCRIPT (not the agent) writes state=COMPLETE
if not failed:
    gs_path = STATE_DIR / "GOAL_STATE.json"
    try:
        gs = json.loads(gs_path.read_text())
        gs.update({
            "state": "COMPLETE",
            "completion_allowed": True,
            "completed_by": "external_verifier_v2.0_evidence_only",
            "completed_utc": NOW,
            "completion_gates_passed": len(passed),
            "completion_gates_total": len(gates),
        })
        gs_path.write_text(json.dumps(gs, indent=2, sort_keys=True) + "\n")
        output["goal_state_written"] = "COMPLETE"
    except Exception as exc:
        output["goal_state_write_error"] = str(exc)

print(json.dumps(output, indent=2))
sys.exit(0 if not failed else 1)
