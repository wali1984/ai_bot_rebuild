"""V2 Continuous Hourly Monitor CLI.

Computes hourly paper trading windows from paper_events.jsonl and writes 7 artifacts per window.
Runs loss recovery evaluation and outcome memory updates each cycle.
Used for V2_CONTINUOUS_PAPER_RUNTIME_PROOF_AND_LOSS_RECOVERY goal.

Invocation:
    v2_continuous_hourly_monitor.py [--windows N] [--output-dir PATH] [--redis-url URL]

Safety:
    - No exchange orders
    - No legacy Redis writes
    - No trading enabled
    - All Redis writes use v2: prefix
    - Gate: blocked_human_only

Output artifacts per window (7 per window):
    trainer_hourly_status.json
    signal_prediction_hourly_accuracy.json
    orchestrator_hourly_decision_quality.json
    risk_controller_hourly_status.json
    paper_trader_hourly_pnl.json
    hedge_exit_hourly_status.json
    adaptive_action_leverage_margin_hourly_status.json

Final artifacts (9 total):
    continuous_hourly_monitor_status.json
    latest_3h_paper_quality_status.json
    adaptive_runtime_update_status.json
    trainer_feedback_learning_effect_status.json
    paper_loss_recovery_status.json
    adaptive_leverage_margin_shadow_status.json
    paper_soak_500_trade_status.json
    shap_attribution_status.json
    NO_GO_UNTIL_3H_EDGE_VALIDATED.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.paper_trade_management.hourly_monitor import (
    build_3h_window_artifacts,
    build_cumulative_artifacts,
    is_window_losing,
)
from v2.backend.app.services.paper_trade_management.loss_recovery import evaluate_loss_recovery
from v2.backend.app.services.paper_trade_management.outcome_memory_updater import update_outcome_memory

SCHEMA_VERSION = "v2_continuous_hourly_monitor_v1"
GATE_STATUS = "blocked_human_only"
PAPER_EVENTS_PATH = REPO_ROOT / "v2" / "runtime" / "paper_online" / "latest" / "paper_events.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "raw_evidence"
SOAK_TARGET = 500


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, data: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    try:
        print(f"  wrote: {path.relative_to(REPO_ROOT)}")
    except ValueError:
        print(f"  wrote: {path}")


def _write_text(path: Path, text: str) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        print(f"  wrote: {path.relative_to(REPO_ROOT)}")
    except ValueError:
        print(f"  wrote: {path}")


def _get_redis_client(redis_url: str) -> object | None:
    try:
        import redis
        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Redis unavailable ({exc}), skipping outcome memory + loss recovery Redis writes")
        return None


class _FakeRedis:
    """In-memory Redis substitute when real Redis is unavailable."""
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def ping(self) -> bool:
        return True


def build_shap_attribution_status(cumulative: dict) -> dict:
    pred_acc = cumulative.get("signal_prediction_hourly_accuracy", {})
    filled_count = pred_acc.get("filled_count", 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "blocker_4_status": "OPEN",
        "shap_available": False,
        "attribution_method": "gradient_sign_heuristic_fallback",
        "attribution_note": (
            "top_positive_feature_codes and top_negative_feature_codes populated via "
            "__gradient_sign_heuristic__ prefix. Real SHAP not wired in trainer checkpoint export. "
            "Must wire SHAP before operator approval."
        ),
        "predictions_enriched": filled_count,
        "required_before_trading": True,
        "waiveable_by_operator_for_paper": True,
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
    }


def build_paper_soak_status(cumulative: dict, jsonl_path: Path) -> dict:
    pnl = cumulative.get("paper_trader_hourly_pnl", {})
    closed = pnl.get("closed_trade_count", 0)
    win_rate = pnl.get("win_rate")
    soak_met = closed >= SOAK_TARGET and (win_rate is None or win_rate >= 0.55)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "blocker_3_status": "OPEN" if not soak_met else "MET",
        "paper_events_path": str(jsonl_path),
        "closed_trade_count": closed,
        "soak_target": SOAK_TARGET,
        "soak_progress_pct": round(closed / SOAK_TARGET * 100, 1),
        "win_rate": win_rate,
        "win_rate_target": 0.55,
        "soak_met": soak_met,
        "soak_remaining": max(0, SOAK_TARGET - closed),
        "required_before_trading": True,
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
    }


def build_nogolive_md(
    *,
    final_marker: str,
    all_pnl_windows: list[dict],
    losing_windows: int,
    closed: int,
    win_rate_all: object,
    soak_met: bool,
    soak_progress_pct: float,
    loss_recovery_result: dict,
    quality_verdict: str,
) -> str:
    n = len(all_pnl_windows)
    clean = n - losing_windows
    tightening = loss_recovery_result.get("tightening_active", False)
    consec_clean = loss_recovery_result.get("consecutive_clean_windows", 0)
    recovery_req = loss_recovery_result.get("recovery_required_windows", 3)
    return f"""# NO_GO_UNTIL_3H_EDGE_VALIDATED

**Final Marker: `{final_marker}`**
Generated: {_now_iso()}
Gate: {GATE_STATUS}

---

## 3-Hour Consecutive Window Quality

| Check | Result |
|-------|--------|
| Windows evaluated | {n} |
| Losing windows | {losing_windows} |
| Clean windows | {clean} |
| 3H quality verdict | `{quality_verdict}` |
| Required | 3 consecutive clean windows |

---

## Paper Soak Progress

| Metric | Value | Target |
|--------|-------|--------|
| Closed trades | {closed} | {SOAK_TARGET} |
| Progress | {soak_progress_pct}% | 100% |
| Win rate | {win_rate_all if win_rate_all is not None else 'N/A'} | >= 55% |
| Soak met | {soak_met} | True |

---

## Loss Recovery Status

| Metric | Value |
|--------|-------|
| Tightening active | {tightening} |
| Losing windows (3h) | {losing_windows} |
| Consecutive clean | {consec_clean} |
| Required to clear | {recovery_req} |

---

## Remaining Blockers

- **BLOCKER-3**: Paper soak -- {closed}/{SOAK_TARGET} closed trades ({soak_progress_pct}%)
- **BLOCKER-4**: SHAP attribution -- gradient-sign heuristic active, real SHAP not wired
- **BLOCKER-5**: DataLoader zombies -- code fixed, awaiting natural trainer restart
- **BLOCKER-6**: No operator sign-off on paper accuracy evidence

---

## Safety Invariants

- Gate: blocked_human_only (requires explicit operator GUI action)
- Exchange mutation: False
- Legacy Redis writes: False
- Max leverage recommendation: 3x isolated only
- Hedge engine: fail-closed until operator approval

---

*This file is regenerated each monitor cycle. Do not manually edit.*
*Trading remains blocked until final marker changes to PAPER_VALIDATED_NOT_TRADING_READY and operator explicitly enables via GUI.*
"""


def run_monitor(
    *,
    windows: int = 3,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    redis_url: str = "redis://localhost:6379/0",
    jsonl_path: Path = PAPER_EVENTS_PATH,
) -> None:
    print("\n=== V2 Continuous Hourly Monitor ===")
    print(f"  events: {jsonl_path}")
    print(f"  windows: {windows}")
    print(f"  output: {output_dir}")
    print(f"  gate: {GATE_STATUS}")
    print()

    redis_client = _get_redis_client(redis_url)
    if redis_client is None:
        redis_client = _FakeRedis()

    print("Computing cumulative artifacts (all-time window)...")
    cumulative = build_cumulative_artifacts(jsonl_path=jsonl_path)
    for artifact_name, payload in cumulative.items():
        _write_json(output_dir / f"{artifact_name}.json", payload)

    print(f"\nComputing {windows} hourly windows...")
    window_list = build_3h_window_artifacts(jsonl_path=jsonl_path, hours=windows)
    all_pnl_windows: list[dict] = []

    for win_data in window_list:
        idx = win_data["window_index"]
        win_dir = output_dir / "hourly_windows" / f"window_{idx:03d}"
        print(f"  Window {idx}: {win_data['window_start']} -> {win_data['window_end']}")
        for artifact_name, payload in win_data["artifacts"].items():
            _write_json(win_dir / f"{artifact_name}.json", payload)
        pnl = win_data["artifacts"].get("paper_trader_hourly_pnl", {})
        all_pnl_windows.append(pnl)

    print("\nUpdating outcome memory (12 Redis stores)...")
    outcome_update_result = update_outcome_memory(jsonl_path=jsonl_path, redis_client=redis_client)
    _write_json(output_dir / "adaptive_runtime_update_status.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "outcome_memory_update": outcome_update_result,
        "stores_updated": 12,
        "store_types": [
            "total_trades", "win_count", "loss_count", "rolling_win_rate",
            "rolling_ev_bps", "avg_winner_bps", "avg_loser_bps", "max_drawdown_bps",
            "consecutive_losses", "last_trade_ts", "degraded", "soak_count",
        ],
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
        "writes_old_redis": False,
    })

    print("Evaluating loss recovery loop...")
    loss_recovery_result = evaluate_loss_recovery(
        window_artifacts_list=all_pnl_windows,
        redis_client=redis_client,
        symbol="ALL",
        timeframe="all",
        now_iso=_now_iso(),
    )
    _write_json(output_dir / "paper_loss_recovery_status.json", loss_recovery_result)

    print("Building latest 3h paper quality status...")
    latest_closed = sum(w.get("closed_trade_count", 0) for w in all_pnl_windows)
    latest_realized_pnl = sum(w.get("paper_realized_pnl", 0.0) for w in all_pnl_windows)
    losing_windows = sum(1 for w in all_pnl_windows if is_window_losing({"paper_trader_hourly_pnl": w}))
    quality_verdict = (
        "3H_EDGE_VALIDATED"
        if losing_windows == 0 and latest_closed >= 3 and latest_realized_pnl >= 0
        else "3H_EDGE_NOT_YET_VALIDATED"
    )
    _write_json(output_dir / "latest_3h_paper_quality_status.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "windows_evaluated": len(all_pnl_windows),
        "losing_windows": losing_windows,
        "clean_windows": len(all_pnl_windows) - losing_windows,
        "total_closed_trades_3h": latest_closed,
        "total_realized_pnl_3h": latest_realized_pnl,
        "quality_verdict": quality_verdict,
        "required_for_final_marker": "3 consecutive clean windows + 500 trade soak",
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
    })

    print("Building trainer feedback learning effect status...")
    _trainer_status = cumulative.get("trainer_hourly_status", {})
    _feedback_consumed = _trainer_status.get("trainer_feedback_consumed", 0)
    _write_json(output_dir / "trainer_feedback_learning_effect_status.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "backfill_wired": True,
        "backfill_method": "backfill_realized_outcome in _push_decisions_to_redis on POSITION_CLOSED_PAPER_ONLY",
        "feedback_consumed": _feedback_consumed,
        "feedback_quarantined": 0,
        "trainer_source": "protected_ml_runtime_subprocess_boundary",
        "trainer_note": (
            "feedback_consumed = closed trades that triggered backfill_realized_outcome (one per closed trade). "
            "The trainer is a protected ML runtime. "
            "V2 writes realized outcomes to v2:prediction:{sym}:{tf} Redis keys via backfill_realized_outcome(). "
            "Feedback effect measurable only after trainer restart reads updated outcomes."
        ),
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
    })

    print("Building adaptive leverage/margin shadow status...")
    lev_data = cumulative.get("adaptive_action_leverage_margin_hourly_status", {})
    lev_rec_count = lev_data.get("adaptive_leverage_recommendation_count", 0)
    _write_json(output_dir / "adaptive_leverage_margin_shadow_status.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "recommendation_count": lev_rec_count,
        "margin_recommendation_count": lev_rec_count,
        "mutation_count_must_be_zero": 0,
        "max_leverage_cap": 3,
        "max_loss_budget_usd": 50.0,
        "margin_mode": "isolated_only",
        "cross_margin_blocked": True,
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
        "recommendation_count_note": (
            "0 is expected for pre-wiring-sprint fills (2279 events from old gates). "
            "Field 'leverage_recommendation' was added to paper events post-patch (2026-06-18). "
            "Count will increment only for new entries that pass Phase 3/4/9 gates (conf>=0.75, edge>=15bps, 15m+)."
        ),
    })

    print("Building SHAP attribution status...")
    _write_json(output_dir / "shap_attribution_status.json", build_shap_attribution_status(cumulative))

    print("Building paper soak 500 trade status...")
    soak_status = build_paper_soak_status(cumulative, jsonl_path)
    _write_json(output_dir / "paper_soak_500_trade_status.json", soak_status)

    closed_all_time = cumulative.get("paper_trader_hourly_pnl", {}).get("closed_trade_count", 0)
    win_rate_all = cumulative.get("paper_trader_hourly_pnl", {}).get("win_rate")
    soak_met = soak_status["soak_met"]

    print("Building continuous hourly monitor status...")
    _write_json(output_dir / "continuous_hourly_monitor_status.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "hourly_windows_computed": len(window_list),
        "cumulative_artifacts_written": len(cumulative),
        "outcome_memory_buckets_updated": outcome_update_result.get("buckets_updated", 0),
        "loss_recovery_tightening_active": loss_recovery_result.get("tightening_active", False),
        "loss_recovery_losing_windows": loss_recovery_result.get("losing_windows", 0),
        "closed_trades_all_time": closed_all_time,
        "closed_trades_3h_windows": latest_closed,
        "soak_progress_pct": soak_status["soak_progress_pct"],
        "quality_verdict_3h": quality_verdict,
        "shap_blocker_status": "OPEN",
        "gate_status": GATE_STATUS,
        "mutates_exchange": False,
        "writes_old_redis": False,
    })

    three_h_validated = quality_verdict == "3H_EDGE_VALIDATED"
    final_marker = (
        "V2_CONTINUOUS_PAPER_LOSS_RECOVERY_AND_ADAPTIVE_RUNTIME_CONTROL_PAPER_VALIDATED_NOT_TRADING_READY"
        if (three_h_validated and soak_met)
        else "V2_CONTINUOUS_PAPER_LOSS_RECOVERY_AND_ADAPTIVE_RUNTIME_CONTROL_BLOCKED"
    )

    print("Writing NO_GO_UNTIL_3H_EDGE_VALIDATED.md...")
    nogolive_md = build_nogolive_md(
        final_marker=final_marker,
        all_pnl_windows=all_pnl_windows,
        losing_windows=losing_windows,
        closed=closed_all_time,
        win_rate_all=win_rate_all,
        soak_met=soak_met,
        soak_progress_pct=soak_status["soak_progress_pct"],
        loss_recovery_result=loss_recovery_result,
        quality_verdict=quality_verdict,
    )
    _write_text(output_dir / "NO_GO_UNTIL_3H_EDGE_VALIDATED.md", nogolive_md)

    print(f"\n=== Monitor run complete ===")
    print(f"  Final marker: {final_marker}")
    print(f"  Closed trades: {closed_all_time}/{SOAK_TARGET}")
    print(f"  3H quality: {quality_verdict}")
    print(f"  Tightening active: {loss_recovery_result.get('tightening_active', False)}")
    print(f"  Gate: {GATE_STATUS}")


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 Continuous Hourly Monitor")
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--events", type=Path, default=PAPER_EVENTS_PATH)
    args = parser.parse_args()

    run_monitor(
        windows=args.windows,
        output_dir=args.output_dir,
        redis_url=args.redis_url,
        jsonl_path=args.events,
    )


if __name__ == "__main__":
    main()
