"""Paper-only confidence threshold trial and outcome monitor.

The trial consumes the current native CUDA prediction grid and promotes only
clean, confidence-blocked rows into a separate paper-only signal overlay. It
never changes live thresholds and never writes legacy Redis keys.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import dumps_pretty


GO_READY = "V2_PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_AND_OUTCOME_MONITOR_READY"
GO_BLOCKED = "V2_PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_AND_OUTCOME_MONITOR_BLOCKED"
SCHEMA_VERSION = "v2_paper_only_confidence_threshold_trial_v1"
ARTIFACT_REL = Path("v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest")

PREDICTION_SOURCE_REL = Path(
    "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json"
)
RUNTIME_TRUTH_REL = Path("operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json")
PORTFOLIO_REL = Path("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")
OUTCOME_OBSERVER_REL = Path(
    "operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json"
)
CONFIDENCE_PROPOSAL_REL = Path(
    "v2_confidence_calibration_and_paper_actionability_improvement/latest/calibrated_confidence_threshold_proposal.json"
)

TRIAL_SIGNAL_REDIS_KEY = "v2:signals:paper:confidence_threshold_trial"
TRIAL_STATUS_REDIS_KEY = "v2:paper:confidence_threshold_trial:status"
TRIAL_DRAWDOWN_GUARD_REDIS_KEY = "v2:paper:confidence_threshold_trial:drawdown_guard"
TRIAL_THRESHOLD = 0.54
EXPECTED_MOVE_FLOOR_BPS = 8.0
MARKET_STATE_INTEGRITY_FLOOR = 90.0
DATA_COVERAGE_FLOOR = 70.0
MAX_PROMOTED_ROWS = 25


@dataclass(frozen=True)
class PaperConfidenceTrialPaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    prediction_source_path: Path
    runtime_truth_path: Path
    portfolio_path: Path
    outcome_observer_path: Path
    confidence_proposal_path: Path


@dataclass(frozen=True)
class PaperConfidenceTrialResult:
    go_no_go: str
    artifacts: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


def default_paths(repo_root: Path) -> PaperConfidenceTrialPaths:
    root = repo_root.resolve()
    public_root = root / "v2/frontend/public"
    return PaperConfidenceTrialPaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=public_root / ARTIFACT_REL,
        prediction_source_path=public_root / PREDICTION_SOURCE_REL,
        runtime_truth_path=public_root / RUNTIME_TRUTH_REL,
        portfolio_path=public_root / PORTFOLIO_REL,
        outcome_observer_path=public_root / OUTCOME_OBSERVER_REL,
        confidence_proposal_path=public_root / CONFIDENCE_PROPOSAL_REL,
    )


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return _as_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def _prediction_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_as_dict(row) for row in _as_list(source.get("prediction_rows"))]


def _block_reasons(row: Mapping[str, Any]) -> list[str]:
    return [str(reason) for reason in _as_list(row.get("paper_fill_gate_block_reasons"))]


def _selected_action(row: Mapping[str, Any]) -> str:
    return str(row.get("selected_action") or row.get("action") or "").lower()


def _bucket(confidence: float | None) -> str:
    if confidence is None:
        return "missing"
    for low, high in (
        (0.50, 0.52),
        (0.52, 0.53),
        (0.53, 0.54),
        (0.54, 0.545),
        (0.545, 0.55),
        (0.55, 0.60),
        (0.60, 1.01),
    ):
        if low <= confidence < high:
            return f"{low:.3f}-{high:.3f}"
    if confidence < 0.50:
        return "below-0.500"
    return "1.010-plus"


def _safe_list_without_confidence_reason(row: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            str(reason)
            for reason in _block_reasons(row)
            if str(reason) and str(reason) != "confidence_below_threshold"
        }
    )


def classify_trial_candidate(
    row: Mapping[str, Any],
    *,
    threshold: float = TRIAL_THRESHOLD,
    expected_move_floor_bps: float = EXPECTED_MOVE_FLOOR_BPS,
    market_state_integrity_floor: float = MARKET_STATE_INTEGRITY_FLOOR,
    data_coverage_floor: float = DATA_COVERAGE_FLOOR,
) -> tuple[bool, list[str]]:
    """Return whether a row can enter the paper-only threshold trial."""
    reasons: list[str] = []
    confidence = _float(row.get("confidence_calibrated"))
    expected = _float(row.get("expected_move_after_cost_bps"))
    integrity = _float(row.get("market_state_integrity_score"))
    coverage = _float(row.get("data_coverage_percent"))
    stale = int(_float(row.get("stale_feature_count")) or 0)
    price = _float(row.get("price_target"))
    price_status = str(row.get("price_target_validation_status") or "VALID").upper()
    block_reasons = _block_reasons(row)

    if _bool(row.get("paper_fill_allowed")):
        reasons.append("ALREADY_PAPER_ALLOWED")
    if "confidence_below_threshold" not in block_reasons:
        reasons.append("NOT_BLOCKED_BY_CONFIDENCE_GATE")
    non_confidence_reasons = _safe_list_without_confidence_reason(row)
    if non_confidence_reasons:
        reasons.extend(f"OTHER_BLOCKER:{reason}" for reason in non_confidence_reasons)
    if _selected_action(row) not in {"long", "short"}:
        reasons.append("NON_TRADE_ACTION")
    if confidence is None:
        reasons.append("CONFIDENCE_MISSING")
    elif confidence < threshold:
        reasons.append("CONFIDENCE_BELOW_TRIAL_THRESHOLD")
    if expected is None:
        reasons.append("EXPECTED_MOVE_AFTER_COST_MISSING")
    elif expected < expected_move_floor_bps:
        reasons.append("EXPECTED_MOVE_AFTER_COST_BELOW_TRIAL_FLOOR")
    if integrity is None:
        reasons.append("MARKET_STATE_INTEGRITY_SCORE_MISSING")
    elif integrity < market_state_integrity_floor:
        reasons.append("MARKET_STATE_INTEGRITY_BELOW_TRIAL_FLOOR")
    if coverage is None:
        reasons.append("DATA_COVERAGE_MISSING")
    elif coverage < data_coverage_floor:
        reasons.append("DATA_COVERAGE_BELOW_TRIAL_FLOOR")
    if stale != 0:
        reasons.append("STALE_FEATURES_PRESENT")
    if price is None or price <= 0:
        reasons.append("PRICE_TARGET_MISSING_OR_INVALID")
    if price_status not in {"VALID", ""}:
        reasons.append(f"PRICE_TARGET_STATUS_{price_status}")
    for field in ("prediction_id", "feature_snapshot_id", "market_state_id"):
        if not row.get(field):
            reasons.append(f"{field.upper()}_MISSING")
    for field in ("valid_for_training", "valid_for_prediction", "valid_for_risk", "valid_for_orchestrator", "valid_for_paper"):
        if row.get(field) is not True:
            reasons.append(f"{field.upper()}_NOT_TRUE")
    return not reasons, sorted(set(reasons))


def _trial_signal(row: Mapping[str, Any], *, threshold: float, generated_est: str) -> dict[str, Any]:
    prediction_id = str(row.get("prediction_id"))
    symbol = str(row.get("symbol") or "").upper()
    timeframe = str(row.get("timeframe") or "")
    signal_id = f"sig_paper_conf_trial_{prediction_id}"
    risk_decision_id = f"paper_conf_trial_risk_{prediction_id}"
    orchestrator_decision_id = f"paper_conf_trial_orch_{prediction_id}"
    original_reasons = _block_reasons(row)
    return {
        **dict(row),
        "signal_id": signal_id,
        "risk_decision_id": risk_decision_id,
        "orchestrator_decision_id": orchestrator_decision_id,
        "winner_proposal_id": prediction_id,
        "source_prediction_id": prediction_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": _selected_action(row),
        "action": _selected_action(row),
        "selected_action": _selected_action(row),
        "paper_fill_allowed": True,
        "paper_fill_gate_status": "PAPER_ONLY_CONFIDENCE_TRIAL_GATE_OPEN",
        "paper_fill_gate_block_reasons": [],
        "paper_confidence_threshold_trial": True,
        "paper_confidence_trial_id": f"paper_conf_trial_{prediction_id}",
        "paper_confidence_trial_threshold": threshold,
        "paper_confidence_trial_original_block_reasons": original_reasons,
        "paper_confidence_trial_promoted": True,
        "paper_confidence_trial_generated_est": generated_est,
        "paper_confidence_trial_scope": "paper_only_no_live_threshold_change",
        "paper_confidence_trial_operator_acceptance": "current_user_instruction_2026_06_10",
        "paper_confidence_trial_lineage": {
            "prediction_id": prediction_id,
            "signal_id": signal_id,
            "risk_decision_id": risk_decision_id,
            "orchestrator_decision_id": orchestrator_decision_id,
            "feature_snapshot_id": row.get("feature_snapshot_id"),
            "market_state_id": row.get("market_state_id"),
        },
        "places_real_order": False,
        "live_threshold_changed": False,
    }


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _read_trial_drawdown_guard() -> dict[str, Any]:
    client = _connect_redis()
    if client is None:
        return {}
    try:
        raw = client.get(TRIAL_DRAWDOWN_GUARD_REDIS_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _trial_drawdown_guard_paused(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("stop_promoting_new_threshold_trial_signals") is True
        or str(payload.get("status") or "") in {
            "TRIAL_PAUSED_DRAWDOWN_GUARD",
            "TRIAL_BLOCKED_INSUFFICIENT_OUTCOME_SAMPLE",
        }
    )


def _write_trial_signals_to_redis(signals: list[dict[str, Any]], status: dict[str, Any]) -> dict[str, Any]:
    client = _connect_redis()
    if client is None:
        return {
            "redis_available": False,
            "keys_written": [],
            "write_status": "REDIS_UNAVAILABLE_TRIAL_SIGNALS_NOT_WRITTEN",
            "old_redis_write": False,
        }
    keys: list[str] = []
    try:
        client.set(TRIAL_SIGNAL_REDIS_KEY, json.dumps(signals, sort_keys=True), ex=1800)
        keys.append(TRIAL_SIGNAL_REDIS_KEY)
        client.set(TRIAL_STATUS_REDIS_KEY, json.dumps(status, sort_keys=True), ex=1800)
        keys.append(TRIAL_STATUS_REDIS_KEY)
    except Exception as exc:  # noqa: BLE001
        return {
            "redis_available": True,
            "keys_written": keys,
            "write_status": f"REDIS_WRITE_FAILED:{type(exc).__name__}",
            "old_redis_write": False,
        }
    return {
        "redis_available": True,
        "keys_written": keys,
        "write_status": "V2_PAPER_TRIAL_SIGNALS_WRITTEN",
        "old_redis_write": False,
    }


def _run_paper_loop_once() -> dict[str, Any]:
    try:
        from v2.backend.app.cli.v2_trade_management_paper_loop import run_once
    except Exception as exc:  # noqa: BLE001
        return {"paper_loop_run": False, "paper_loop_status": f"IMPORT_FAILED:{type(exc).__name__}"}
    try:
        status = run_once()
    except Exception as exc:  # noqa: BLE001
        return {"paper_loop_run": False, "paper_loop_status": f"RUN_FAILED:{type(exc).__name__}"}
    return {
        "paper_loop_run": True,
        "paper_loop_status": status.get("classification"),
        "paper_signals_seen": status.get("paper_signals_seen"),
        "intents_accepted": status.get("intents_accepted"),
        "persistent_accepted_fill_count": status.get("persistent_accepted_fill_count"),
        "shadow_observation_count": status.get("shadow_observation_count"),
        "intents_held_by_paper_fill_gate": status.get("intents_held_by_paper_fill_gate"),
    }


def _refresh_portfolio_public_payload() -> dict[str, Any]:
    try:
        from v2.backend.app.cli.v2_portfolio_state_publisher import run_once
    except Exception as exc:  # noqa: BLE001
        return {"portfolio_refresh_run": False, "portfolio_refresh_status": f"IMPORT_FAILED:{type(exc).__name__}"}
    try:
        payload = run_once(write_redis=True)
    except Exception as exc:  # noqa: BLE001
        return {"portfolio_refresh_run": False, "portfolio_refresh_status": f"RUN_FAILED:{type(exc).__name__}"}
    return {
        "portfolio_refresh_run": True,
        "portfolio_refresh_status": payload.get("classification"),
        "accepted_fill_total": payload.get("accepted_fill_total"),
        "economic_fill_total": payload.get("economic_fill_total"),
        "open_positions_count": payload.get("open_positions_count"),
        "current_session_equity": payload.get("equity"),
        "current_session_pnl": payload.get("total_pnl_usd"),
        "last_equity_update_est": payload.get("last_equity_update_est"),
    }


def _summarize_portfolio(portfolio: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "accepted_fill_total": portfolio.get("accepted_fill_total"),
        "economic_fill_total": portfolio.get("economic_fill_total"),
        "open_positions_count": portfolio.get("open_positions_count"),
        "current_session_equity": portfolio.get("equity"),
        "current_session_pnl": portfolio.get("total_pnl_usd"),
        "realized_pnl_usd": portfolio.get("realized_pnl_usd"),
        "unrealized_pnl_usd": portfolio.get("unrealized_pnl_usd"),
        "last_equity_update_est": portfolio.get("last_equity_update_est"),
    }


def _bucket_monitor(rows: list[Mapping[str, Any]], outcome_observer: Mapping[str, Any]) -> dict[str, Any]:
    observations = {
        str(row.get("prediction_id")): row
        for row in _as_list(outcome_observer.get("observations"))
        if isinstance(row, dict) and row.get("prediction_id")
    }
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "prediction_count": 0,
            "paper_allowed_before": 0,
            "trial_candidate_count": 0,
            "matched_completed_outcomes": 0,
            "after_cost_correct_count": 0,
            "would_have_beaten_costs_count": 0,
            "_expected": [],
            "_confidence": [],
        }
    )
    for row in rows:
        confidence = _float(row.get("confidence_calibrated"))
        bucket = _bucket(confidence)
        item = grouped[bucket]
        item["prediction_count"] += 1
        item["paper_allowed_before"] += int(_bool(row.get("paper_fill_allowed")))
        ok, _ = classify_trial_candidate(row)
        item["trial_candidate_count"] += int(ok)
        expected = _float(row.get("expected_move_after_cost_bps"))
        if expected is not None:
            item["_expected"].append(expected)
        if confidence is not None:
            item["_confidence"].append(confidence)
        outcome = observations.get(str(row.get("prediction_id")))
        if isinstance(outcome, dict) and _bool(outcome.get("completed")):
            item["matched_completed_outcomes"] += 1
            item["after_cost_correct_count"] += int(_bool(outcome.get("after_cost_correct")))
            item["would_have_beaten_costs_count"] += int(_bool(outcome.get("would_have_beaten_costs")))
    for item in grouped.values():
        expected_values = item.pop("_expected")
        confidence_values = item.pop("_confidence")
        item["avg_expected_move_after_cost_bps"] = statistics.fmean(expected_values) if expected_values else None
        item["avg_confidence"] = statistics.fmean(confidence_values) if confidence_values else None
    return dict(sorted(grouped.items()))


def build_paper_confidence_threshold_trial(
    *,
    prediction_source: Mapping[str, Any],
    runtime_truth: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    outcome_observer: Mapping[str, Any],
    confidence_proposal: Mapping[str, Any],
    generated_est: str,
    threshold: float = TRIAL_THRESHOLD,
    apply_trial: bool = True,
    run_paper_loop: bool = True,
) -> PaperConfidenceTrialResult:
    predictions = _prediction_rows(prediction_source)
    trial_candidate_rows: list[dict[str, Any]] = []
    rejected_reason_counts: Counter[str] = Counter()
    rejected_rows: list[dict[str, Any]] = []
    for row in predictions:
        allowed, reasons = classify_trial_candidate(row, threshold=threshold)
        if allowed:
            trial_candidate_rows.append(row)
        else:
            rejected_reason_counts.update(reasons)
            if "confidence_below_threshold" in _block_reasons(row):
                rejected_rows.append(
                    {
                        "prediction_id": row.get("prediction_id"),
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "confidence_calibrated": row.get("confidence_calibrated"),
                        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                        "trial_reject_reasons": reasons[:8],
                    }
                )
    ranked = sorted(
        trial_candidate_rows,
        key=lambda row: (
            _float(row.get("expected_move_after_cost_bps")) or -9999,
            _float(row.get("confidence_calibrated")) or 0,
            _float(row.get("market_state_integrity_score")) or 0,
        ),
        reverse=True,
    )[:MAX_PROMOTED_ROWS]
    trial_signals = [_trial_signal(row, threshold=threshold, generated_est=generated_est) for row in ranked]
    drawdown_guard = _read_trial_drawdown_guard() if apply_trial else {}
    drawdown_guard_paused = apply_trial and _trial_drawdown_guard_paused(drawdown_guard)
    if drawdown_guard_paused:
        trial_signals = []
    paper_allowed_before = sum(1 for row in predictions if _bool(row.get("paper_fill_allowed")))
    live_submit_allowed = runtime_truth.get("live_order_submit_allowed") is True
    live_blocker = runtime_truth.get("live_order_submit_blocker")

    trial_status = {
        "schema_version": f"{SCHEMA_VERSION}_redis_status",
        "generated_est": generated_est,
        "trial_threshold": threshold,
        "paper_shadow_only": True,
        "trial_signal_count": len(trial_signals),
        "drawdown_guard_status": drawdown_guard.get("status"),
        "drawdown_guard_reason": drawdown_guard.get("drawdown_guard_reason"),
        "live_threshold_changed": False,
        "live_submit_allowed": bool(live_submit_allowed),
        "live_submit_blocker": live_blocker,
    }
    redis_write = (
        _write_trial_signals_to_redis(trial_signals, trial_status)
        if apply_trial and trial_signals and not live_submit_allowed
        else {
            "redis_available": None,
            "keys_written": [],
            "write_status": "TRIAL_SIGNAL_WRITE_SKIPPED",
            "old_redis_write": False,
        }
    )
    paper_loop = (
        _run_paper_loop_once()
        if apply_trial and trial_signals and not live_submit_allowed and run_paper_loop
        else {"paper_loop_run": False, "paper_loop_status": "PAPER_LOOP_RUN_SKIPPED"}
    )
    portfolio_refresh = (
        _refresh_portfolio_public_payload()
        if apply_trial and trial_signals and not live_submit_allowed and run_paper_loop
        else {"portfolio_refresh_run": False, "portfolio_refresh_status": "PORTFOLIO_REFRESH_SKIPPED"}
    )
    after_portfolio = _read_json(default_paths(Path.cwd()).portfolio_path)
    if not after_portfolio:
        after_portfolio = dict(portfolio)

    config = {
        "schema_version": f"{SCHEMA_VERSION}_config",
        "generated_est": generated_est,
        "status": (
            "PAPER_ONLY_THRESHOLD_TRIAL_PAUSED_BY_DRAWDOWN_GUARD"
            if drawdown_guard_paused
            else "PAPER_ONLY_THRESHOLD_TRIAL_ACTIVE" if trial_signals and apply_trial else "PAPER_ONLY_THRESHOLD_TRIAL_NO_CANDIDATES"
        ),
        "trial_enabled": bool(apply_trial and trial_signals and not live_submit_allowed),
        "paper_confidence_threshold": threshold,
        "expected_move_after_cost_floor_bps": EXPECTED_MOVE_FLOOR_BPS,
        "market_state_integrity_floor": MARKET_STATE_INTEGRITY_FLOOR,
        "data_coverage_floor": DATA_COVERAGE_FLOOR,
        "stale_feature_count_required": 0,
        "max_promoted_rows": MAX_PROMOTED_ROWS,
        "operator_acceptance_source": "current_user_instruction_2026_06_10",
        "source_proposal_status": confidence_proposal.get("status"),
        "live_threshold_changed": False,
        "live_risk_changed": False,
        "live_submit_allowed": bool(live_submit_allowed),
        "live_submit_blocker": live_blocker,
        "redis_signal_key": TRIAL_SIGNAL_REDIS_KEY,
        "drawdown_guard_status": drawdown_guard.get("status"),
        "drawdown_guard_reason": drawdown_guard.get("drawdown_guard_reason"),
        "guard_contract": [
            "paper_only",
            "confidence_above_trial_threshold",
            "positive_expected_move_after_cost",
            "valid_market_state_for_paper",
            "fresh_features_only",
            "valid_price_target",
            "deterministic_trial_lineage",
            "no_live_threshold_change",
        ],
    }
    before_after = {
        "schema_version": f"{SCHEMA_VERSION}_before_after",
        "generated_est": generated_est,
        "prediction_rows": len(predictions),
        "paper_allowed_before": paper_allowed_before,
        "trial_candidate_count": len(trial_candidate_rows),
        "trial_promoted_signal_count": len(trial_signals),
        "paper_allowed_after_simulated": paper_allowed_before + len(trial_signals),
        "paper_loop_result": paper_loop,
        "portfolio_refresh_result": portfolio_refresh,
        "redis_write_result": redis_write,
        "trial_promoted_rows": [
            {
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "selected_action": row.get("selected_action"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "market_state_integrity_score": row.get("market_state_integrity_score"),
                "signal_id": signal.get("signal_id"),
                "risk_decision_id": signal.get("risk_decision_id"),
                "orchestrator_decision_id": signal.get("orchestrator_decision_id"),
            }
            for row, signal in zip(ranked, trial_signals)
        ],
        "confidence_blocked_rejected_reason_counts": dict(rejected_reason_counts.most_common()),
        "confidence_blocked_rejected_sample": rejected_rows[:50],
        "live_threshold_changed": False,
        "live_risk_changed": False,
    }
    outcome_monitor = {
        "schema_version": f"{SCHEMA_VERSION}_bucket_outcome_monitor",
        "generated_est": generated_est,
        "status": "CONFIDENCE_BUCKET_OUTCOME_MONITOR_ARMED",
        "bucket_monitor": _bucket_monitor(predictions, outcome_observer),
        "shadow_observations_total": outcome_observer.get("observations_total"),
        "completed_observations": outcome_observer.get("completed_observations"),
        "trial_threshold": threshold,
        "monitor_window_minutes": 60,
        "alerts": [
            "PAPER_CONFIDENCE_TRIAL_DRAWDOWN_EXCEEDED",
            "PAPER_CONFIDENCE_TRIAL_ALLOWED_LOSER_RATE_HIGH",
            "PAPER_CONFIDENCE_TRIAL_NO_EDGE_AFTER_60M",
        ],
    }
    pnl = {
        "schema_version": f"{SCHEMA_VERSION}_pnl_monitor",
        "generated_est": generated_est,
        "status": "PAPER_PNL_MONITOR_AFTER_THRESHOLD_TRIAL_ARMED",
        "before_trial_portfolio": _summarize_portfolio(portfolio),
        "after_trial_portfolio": _summarize_portfolio(after_portfolio),
        "trial_promoted_signal_count": len(trial_signals),
        "paper_loop_run": paper_loop.get("paper_loop_run"),
        "live_unchanged": True,
    }
    lineage = {
        "schema_version": f"{SCHEMA_VERSION}_lineage",
        "generated_est": generated_est,
        "status": "TRIAL_LINEAGE_READY" if trial_signals else "NO_TRIAL_LINEAGE_ROWS",
        "complete_trial_lineage_count": sum(
            1
            for row in trial_signals
            if all(
                row.get(field)
                for field in (
                    "prediction_id",
                    "signal_id",
                    "risk_decision_id",
                    "orchestrator_decision_id",
                    "feature_snapshot_id",
                    "market_state_id",
                )
            )
        ),
        "trial_signal_count": len(trial_signals),
        "risk_bypass": False,
        "orchestrator_bypass": False,
        "paper_only": True,
        "live_threshold_changed": False,
    }
    overlay_rows = [
        {
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "candidate_direction": row.get("selected_action"),
            "source": "paper_confidence_threshold_trial",
            "overlay_reason": "confidence threshold paper-only trial with clean positive-edge guards",
            "risk_bypass": False,
            "risk_decision_id": signal.get("risk_decision_id"),
            "risk_action": "paper_trial_allow",
            "realized_after_cost_bps": None,
            "confidence_calibrated": row.get("confidence_calibrated"),
            "data_coverage_percent": row.get("data_coverage_percent"),
        }
        for row, signal in zip(ranked, trial_signals)
    ]
    dashboard = {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "gate": GO_READY if predictions else GO_BLOCKED,
        "generated_est": generated_est,
        "status": (
            "PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_PAUSED_BY_DRAWDOWN_GUARD"
            if drawdown_guard_paused
            else "PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_ACTIVE" if trial_signals else "PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_NO_CANDIDATES"
        ),
        "summary": {
            "prediction_rows": len(predictions),
            "paper_allowed_before": paper_allowed_before,
            "trial_candidate_count": len(trial_candidate_rows),
            "trial_promoted_signal_count": len(trial_signals),
            "paper_confidence_threshold": threshold,
            "paper_loop_run": paper_loop.get("paper_loop_run"),
        },
        "threshold_actionability_simulation": {
            "status": "PAPER_ONLY_THRESHOLD_TRIAL_APPLIED" if trial_signals and apply_trial else "PAPER_ONLY_THRESHOLD_TRIAL_MONITOR_ONLY",
            "paper_only": True,
            "runtime_thresholds_changed": False,
            "thresholds_auto_accepted": False,
            "recommended_simulation_id": "paper_confidence_threshold_0_54",
            "simulations": [
                {
                    "simulation_id": "paper_confidence_threshold_0_54",
                    "paper_only": True,
                    "confidence_threshold": threshold,
                    "candidate_count": len(trial_candidate_rows),
                    "promoted_signal_count": len(trial_signals),
                    "runtime_thresholds_changed": False,
                }
            ],
        },
        "paper_actionability_overlay": {
            "status": (
                "PAPER_ONLY_CONFIDENCE_TRIAL_OVERLAY_PAUSED_BY_DRAWDOWN_GUARD"
                if drawdown_guard_paused
                else "PAPER_ONLY_CONFIDENCE_TRIAL_OVERLAY_ACTIVE" if trial_signals else "NO_CLEAN_TRIAL_CANDIDATES"
            ),
            "overlay_source": "v2_paper_only_confidence_threshold_trial_and_outcome_monitor",
            "overlay_candidate_count": len(trial_signals),
            "paper_shadow_only": True,
            "runtime_config_changed": bool(apply_trial and trial_signals),
            "thresholds_auto_accepted": False,
            "risk_bypass": False,
            "risk_fail_closed_preserved": True,
            "can_bypass_risk": False,
            "rows": overlay_rows,
        },
        "paper": pnl["after_trial_portfolio"],
        "live": {
            "live_gate": runtime_truth.get("live_gate"),
            "trader_state": runtime_truth.get("trader_state"),
            "live_order_submit_allowed": runtime_truth.get("live_order_submit_allowed"),
            "live_order_submit_blocker": runtime_truth.get("live_order_submit_blocker"),
            "live_threshold_changed": False,
        },
        "safety": {
            "paper_only": True,
            "exchange_order_submitted": False,
            "test_order_called": False,
            "leverage_or_margin_mutation": False,
            "old_redis_write": False,
            "raw_credentials_exposed": False,
            "live_threshold_changed": False,
        },
    }
    blockers: list[str] = []
    if not predictions:
        blockers.append("NO_CURRENT_NATIVE_CUDA_PREDICTION_ROWS")
    if live_submit_allowed:
        blockers.append("LIVE_SUBMIT_ALLOWED_UNEXPECTED_FOR_PAPER_TRIAL")
    if apply_trial and trial_signals and redis_write.get("write_status") != "V2_PAPER_TRIAL_SIGNALS_WRITTEN":
        blockers.append(str(redis_write.get("write_status")))
    go_no_go = GO_READY if not blockers else GO_BLOCKED
    dashboard["gate"] = go_no_go
    if blockers:
        dashboard["blockers"] = blockers

    artifacts = {
        "paper_threshold_trial_config.json": config,
        "paper_actionability_before_after_status.json": before_after,
        "confidence_bucket_outcome_monitor.json": outcome_monitor,
        "paper_pnl_after_threshold_trial.json": pnl,
        "risk_orchestrator_paper_lineage_status.json": lineage,
        "operator_dashboard_payload.json": dashboard,
    }
    return PaperConfidenceTrialResult(go_no_go=go_no_go, artifacts=artifacts)


def _report(result: PaperConfidenceTrialResult, *, generated_est: str) -> str:
    dashboard = _as_dict(result.artifacts.get("operator_dashboard_payload.json"))
    summary = _as_dict(dashboard.get("summary"))
    paper = _as_dict(dashboard.get("paper"))
    live = _as_dict(dashboard.get("live"))
    blockers = _as_list(dashboard.get("blockers"))
    blocker_text = "\n".join(f"- `{item}`" for item in blockers) if blockers else "- none"
    return f"""# V2 Paper Only Confidence Threshold Trial And Outcome Monitor Report

Gate: `{result.go_no_go}`
Generated EST: `{generated_est}`
Prediction rows: `{summary.get("prediction_rows")}`
Paper allowed before: `{summary.get("paper_allowed_before")}`
Trial candidates: `{summary.get("trial_candidate_count")}`
Trial promoted signals: `{summary.get("trial_promoted_signal_count")}`
Paper threshold: `{summary.get("paper_confidence_threshold")}`
Paper loop run: `{summary.get("paper_loop_run")}`
Paper equity: `{paper.get("current_session_equity")}`
Paper PnL: `{paper.get("current_session_pnl")}`
Live gate: `{live.get("live_gate")}`
Trader state: `{live.get("trader_state")}`
Live submit blocker: `{live.get("live_order_submit_blocker")}`
Live threshold changed: `False`

## Result

The 0.54 confidence threshold is applied only as a guarded paper/shadow trial.
Rows must have clean market-state integrity, positive after-cost expected move,
fresh features, valid price targets, and deterministic paper-only lineage.
Live thresholds, live risk, leverage, margin, and exchange execution remain
unchanged.

## Blockers

{blocker_text}

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation,
no old Redis write, no legacy restart, no Redis trim, no raw credential output,
and no live threshold change.
"""


def write_paper_confidence_trial_artifacts(
    *,
    paths: PaperConfidenceTrialPaths,
    result: PaperConfidenceTrialResult,
    generated_est: str,
) -> PaperConfidenceTrialResult:
    payloads = {
        "GO_NO_GO.md": result.go_no_go,
        "V2_PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_AND_OUTCOME_MONITOR_REPORT.md": _report(
            result,
            generated_est=generated_est,
        ),
        **{name: dumps_pretty(payload) for name, payload in result.artifacts.items()},
    }
    written: list[str] = []
    for directory in (paths.public_dir, paths.worklog_dir):
        for name, text in payloads.items():
            path = directory / name
            _write_text_atomic(path, text)
            written.append(str(path))
    return PaperConfidenceTrialResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        paths_written=tuple(written),
    )


def run_paper_confidence_threshold_trial(
    *,
    repo_root: Path,
    threshold: float = TRIAL_THRESHOLD,
    apply_trial: bool = True,
    run_paper_loop: bool = True,
) -> PaperConfidenceTrialResult:
    paths = default_paths(repo_root)
    generated_est = _est_iso()
    result = build_paper_confidence_threshold_trial(
        prediction_source=_read_json(paths.prediction_source_path),
        runtime_truth=_read_json(paths.runtime_truth_path),
        portfolio=_read_json(paths.portfolio_path),
        outcome_observer=_read_json(paths.outcome_observer_path),
        confidence_proposal=_read_json(paths.confidence_proposal_path),
        generated_est=generated_est,
        threshold=threshold,
        apply_trial=apply_trial,
        run_paper_loop=run_paper_loop,
    )
    return write_paper_confidence_trial_artifacts(
        paths=paths,
        result=result,
        generated_est=generated_est,
    )
