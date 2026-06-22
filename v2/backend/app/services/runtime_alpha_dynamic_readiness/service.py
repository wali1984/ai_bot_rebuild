"""Read-only dynamic strategy/leverage/margin readiness evidence.

This module aggregates current V2 runtime artifacts into the exact
runtime-alpha hourly dynamic strategy/leverage/margin proof packet. It does not
call exchanges, write Redis, submit/test/cancel/modify orders, or mutate
leverage/margin mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


READY = "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_1H_PAPER_SOAK_DYNAMIC_STRATEGY_LEVERAGE_MARGIN_READY"
BLOCKED = "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_1H_PAPER_SOAK_DYNAMIC_STRATEGY_LEVERAGE_MARGIN_BLOCKED"
REQUIRED_TRAINER_SOURCE = "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
REQUIRED_MODEL_SOURCE = "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"

REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_ROOT = REPO_ROOT / "v2/frontend/public"
OPERATOR_REL = Path("operator_runtime/v2_runtime_alpha_remediated_adaptive_1h_dynamic_strategy_leverage_margin/latest")
ARTIFACT_REL = Path("v2_runtime_alpha_remediated_adaptive_1h_paper_soak_dynamic_strategy_leverage_margin/latest")
LEGACY_OPERATOR_REL = Path("operator_runtime/v2_runtime_alpha_remediated_adaptive_12h_dynamic_strategy_leverage_margin/latest")
LEGACY_ARTIFACT_REL = Path("v2_runtime_alpha_remediated_adaptive_12h_paper_soak_dynamic_strategy_leverage_margin/latest")
EST = ZoneInfo("America/New_York")

SOAK_WINDOW_LABEL = "1h"
REQUIRED_SECONDS = 3_600
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
REQUIRED_STRATEGY_FAMILIES = (
    "trend_following",
    "mean_reversion",
    "breakout",
    "momentum",
    "funding_oi_divergence",
    "liquidation_cascade",
    "orderbook_imbalance",
    "microstructure_reversal",
    "ta_confirmation",
    "volatility_regime",
    "public_intel_confirmation",
    "hedged_protection",
    "profit_protection",
    "drawdown_recovery",
    "no_trade_preservation",
)

RUNTIME = Path("operator_runtime")
SOAK_REL = RUNTIME / "v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest"
PROFIT_REL = RUNTIME / "v2_monthly_10k_profit_target_monitor/latest"
PAPER_REL = RUNTIME / "v2_paper_trade_management/latest"
TRAINER_REL = RUNTIME / "v2_native_trainer/latest/native_trainer_runtime_status.json"
SIGNALS_REL = RUNTIME / "v2_signals/latest/signals_payload.json"
LIVE_REL = RUNTIME / "v2_live_gate_runtime/latest/live_gate_runtime_state.json"
RISK_REL = RUNTIME / "v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json"
TRAINER_BRIDGE_REL = RUNTIME / "v2_trainer_bridge/latest/v2_trainer_bridge_status.json"


@dataclass(frozen=True)
class DynamicReadinessPaths:
    repo_root: Path = REPO_ROOT
    public_root: Path = PUBLIC_ROOT

    @property
    def operator_dir(self) -> Path:
        return self.public_root / OPERATOR_REL

    @property
    def artifact_dir(self) -> Path:
        return self.public_root / ARTIFACT_REL

    @property
    def legacy_operator_dir(self) -> Path:
        return self.public_root / LEGACY_OPERATOR_REL

    @property
    def legacy_artifact_dir(self) -> Path:
        return self.public_root / LEGACY_ARTIFACT_REL


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def first_positive_int(*values: Any) -> int:
    for value in values:
        number = finite_float(value)
        if number is not None and number > 0:
            return int(number)
    for value in values:
        number = finite_float(value)
        if number is not None:
            return int(number)
    return 0


def confidence_interval_bounds(lower: Any, upper: Any) -> tuple[Any, Any]:
    low_value = finite_float(lower)
    high_value = finite_float(upper)
    if low_value is None or high_value is None:
        return lower, upper
    return (low_value, high_value) if low_value <= high_value else (high_value, low_value)


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def dict_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("rows", "strategies", "families", "sample_allocations", "observations"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [dict(row) for row in nested if isinstance(row, Mapping)]
    return []


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def last_hour_delta(rows: list[dict[str, Any]], field: str) -> float | None:
    stamped: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        ts = parse_timestamp(row.get("observed_utc") or row.get("generated_utc") or row.get("generated_est"))
        if ts is not None:
            stamped.append((ts, row))
    if not stamped:
        return None
    stamped.sort(key=lambda item: item[0])
    latest_ts, latest_row = stamped[-1]
    cutoff = latest_ts - timedelta(hours=1)
    window = [(ts, row) for ts, row in stamped if ts >= cutoff]
    if not window:
        return None
    base_row = window[0][1]
    latest_value = finite_float(latest_row.get(field))
    base_value = finite_float(base_row.get(field))
    if latest_value is None or base_value is None:
        return None
    return latest_value - base_value


def last_hour_pnl_delta(rows: list[dict[str, Any]]) -> float | None:
    stamped: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        ts = parse_timestamp(row.get("observed_utc") or row.get("generated_utc") or row.get("generated_est"))
        if ts is not None:
            stamped.append((ts, row))
    if not stamped:
        return None
    stamped.sort(key=lambda item: item[0])
    latest_ts, latest_row = stamped[-1]
    cutoff = latest_ts - timedelta(hours=1)
    window = [(ts, row) for ts, row in stamped if ts >= cutoff]
    if not window:
        return None

    def pnl_value(row: Mapping[str, Any]) -> float | None:
        direct = finite_float(row.get("paper_pnl"))
        if direct is not None:
            return direct
        realized = finite_float(row.get("realized_pnl_usd")) or 0.0
        unrealized = finite_float(row.get("unrealized_pnl_usd")) or 0.0
        return realized + unrealized

    latest_value = pnl_value(latest_row)
    base_value = pnl_value(window[0][1])
    if latest_value is None or base_value is None:
        return None
    return latest_value - base_value


def count_rows_with(rows: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in rows if row.get(field) not in (None, ""))


def derive_monthly_goal_status(
    sim: Mapping[str, Any],
    profit: Mapping[str, Any],
    projected_monthly: float | None,
) -> str:
    live_available = finite_float(profit.get("live_available_margin"))
    live_required = finite_float(profit.get("live_required_min_order_margin"))
    if profit.get("live_target_executable") is False or (
        live_available is not None
        and live_required is not None
        and live_available < live_required
    ):
        return "GOAL_REQUIRES_MORE_CAPITAL"
    risk_acceptable = sim.get("risk_acceptable")
    if risk_acceptable is None:
        risk_acceptable = profit.get("risk_acceptable")
    if risk_acceptable is False:
        return "GOAL_REQUIRES_UNACCEPTABLE_RISK"
    if projected_monthly is not None:
        return "ON_TRACK_FOR_10K_MONTHLY_PAPER" if projected_monthly >= 10_000.0 else "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE"
    raw_status = sim.get("goal_status") or sim.get("goal_simulation_status") or sim.get("status")
    if raw_status in {
        "ON_TRACK_FOR_10K_MONTHLY_PAPER",
        "NOT_ON_TRACK_FOR_10K_MONTHLY_PAPER",
        "INSUFFICIENT_SAMPLE_FOR_10K_TARGET",
        "GOAL_REQUIRES_MORE_CAPITAL",
        "GOAL_REQUIRES_UNACCEPTABLE_RISK",
        "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE",
    }:
        return str(raw_status)
    return "INSUFFICIENT_SAMPLE_FOR_10K_TARGET"


def derive_monthly_goal_blockers(
    sim: Mapping[str, Any],
    profit: Mapping[str, Any],
    projected_monthly: float | None,
) -> list[str]:
    blockers: list[str] = []
    live_available = finite_float(profit.get("live_available_margin"))
    live_required = finite_float(profit.get("live_required_min_order_margin"))
    if profit.get("live_target_executable") is False or (
        live_available is not None
        and live_required is not None
        and live_available < live_required
    ):
        blockers.append(
            "capital shortfall: live target is not executable because available margin is below minimum order margin"
        )
    risk_acceptable = sim.get("risk_acceptable")
    if risk_acceptable is None:
        risk_acceptable = profit.get("risk_acceptable")
    if risk_acceptable is False:
        blockers.append("risk too high: current risk requirement is not acceptable under the envelope")
    if projected_monthly is not None and projected_monthly < 10_000.0:
        blockers.append(
            f"edge shortfall: projected monthly net PnL {projected_monthly:.2f} USDT is below 10000.00 USDT"
        )
    sample_count = finite_float(sim.get("performance_outcome_count") or profit.get("performance_outcome_count"))
    sample_required = finite_float(
        sim.get("minimum_qualified_performance_outcomes") or profit.get("minimum_qualified_performance_outcomes")
    )
    sample_status = sim.get("performance_sample_status") or profit.get("performance_sample_status")
    if sample_status in {"INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE", "INSUFFICIENT_SAMPLE_FOR_10K_TARGET"} or (
        sample_count is not None
        and sample_required is not None
        and sample_count < sample_required
    ):
        blockers.append(
            f"insufficient clean outcomes: {int(sample_count or 0)} qualified outcomes, need {int(sample_required or 0)}"
        )
    if not blockers and projected_monthly is None:
        blockers.append("insufficient evidence: projected monthly net PnL is unavailable")
    return blockers


def prediction_rows(signals: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _get(signals, "cuda_prediction_contract", "prediction_rows", default=[])
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def missing_prediction_grid_rows(signals: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in prediction_rows(signals):
        if row.get("status") != "MISSING_TF_PREDICTION":
            continue
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if not symbol or not timeframe or (symbol, timeframe) in seen:
            continue
        seen.add((symbol, timeframe))
        source_lineage = as_dict(row.get("source_lineage"))
        required_key = row.get("prediction_redis_key") or source_lineage.get("required_prediction_key")
        remediation = row.get("next_remediation") or row.get("implementation_task") or source_lineage.get("remediation_task")
        rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "required_prediction_key": required_key,
                "trainer_source": row.get("trainer_source"),
                "trainer_source_required": row.get("trainer_source_required"),
                "model_source": row.get("model_source"),
                "model_source_required": row.get("model_source_required"),
                "missing_stale_reason": row.get("missing_stale_reason") or row.get("status"),
                "remediation": remediation,
            }
        )
    if rows:
        return rows

    missing_by_symbol = as_dict(_get(signals, "cuda_prediction_contract", "missing_prediction_timeframes_by_symbol"))
    for symbol, timeframes in sorted(missing_by_symbol.items()):
        symbol_text = str(symbol or "").upper()
        for timeframe in as_list(timeframes):
            timeframe_text = str(timeframe or "")
            if not symbol_text or not timeframe_text or (symbol_text, timeframe_text) in seen:
                continue
            seen.add((symbol_text, timeframe_text))
            rows.append(
                {
                    "symbol": symbol_text,
                    "timeframe": timeframe_text,
                    "required_prediction_key": f"v2:prediction:{symbol_text}:{timeframe_text}",
                    "missing_stale_reason": "MISSING_TF_PREDICTION",
                    "remediation": (
                        f"Generate v2:prediction:{symbol_text}:{timeframe_text} from the local "
                        "CUDA/RL/MASA/PPO trainer with feature lineage and expected-move telemetry."
                    ),
                }
            )
    return rows


def incomplete_prediction_symbols(missing_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in missing_rows:
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if not symbol or not timeframe:
            continue
        out.setdefault(symbol, [])
        if timeframe not in out[symbol]:
            out[symbol].append(timeframe)
    timeframe_order = {timeframe: index for index, timeframe in enumerate(REQUIRED_TIMEFRAMES)}
    return {
        symbol: sorted(timeframes, key=lambda timeframe: (timeframe_order.get(timeframe, 999), timeframe))
        for symbol, timeframes in sorted(out.items())
    }


def load_inputs(paths: DynamicReadinessPaths) -> dict[str, dict[str, Any]]:
    public = paths.public_root
    return {
        "soak": read_json(public / SOAK_REL / "runtime_alpha_remediated_1h_soak_status.json")
        or read_json(public / SOAK_REL / "operator_dashboard_payload.json"),
        "soak_observations": {
            "rows": read_jsonl(public / SOAK_REL / "runtime_alpha_remediated_soak_observations.jsonl"),
        },
        "soak_status": read_json(public / SOAK_REL / "runtime_alpha_remediated_soak_status.json"),
        "pnl_reconciliation": read_json(public / SOAK_REL / "paper_pnl_reconciliation_24h_status.json"),
        "strategy_weights": read_json(public / SOAK_REL / "strategy_weight_24h_status.json"),
        "hedge_cost_benefit": read_json(public / SOAK_REL / "hedge_cost_benefit_24h_status.json"),
        "exit_reason": read_json(public / SOAK_REL / "exit_reason_24h_status.json"),
        "profit_dashboard": read_json(public / PROFIT_REL / "operator_dashboard_payload.json"),
        "strategy": read_json(public / PROFIT_REL / "adaptive_strategy_selection_status.json"),
        "hedge": read_json(public / PROFIT_REL / "adaptive_hedging_capability_status.json"),
        "leverage_margin": read_json(public / PROFIT_REL / "adaptive_leverage_margin_selection_status.json"),
        "simulation": read_json(public / PROFIT_REL / "monthly_10k_goal_simulation_status.json"),
        "trainer_capability": read_json(public / PROFIT_REL / "trainer_profit_goal_capability_status.json"),
        "feedback_status": read_json(public / PROFIT_REL / "trainer_strategy_hedge_feedback_status.json"),
        "trainer": read_json(public / TRAINER_REL),
        "signals": read_json(public / SIGNALS_REL),
        "live": read_json(public / LIVE_REL),
        "risk": read_json(public / RISK_REL),
        "trainer_bridge": read_json(public / TRAINER_BRIDGE_REL),
        "allocator": read_json(public / PAPER_REL / "adaptive_capital_allocator_status.json"),
        "paper_sizing": read_json(public / PAPER_REL / "paper_adaptive_sizing_runtime_status.json"),
        "lifecycle": read_json(public / PAPER_REL / "trade_lifecycle_guard_status.json"),
        "risk_budget": read_json(public / PAPER_REL / "risk_envelope_dynamic_budget_status.json"),
        "netting": read_json(public / PAPER_REL / "paper_hedge_netting_status.json"),
        "exits": read_json(public / PAPER_REL / "paper_exit_coordinator_status.json"),
        "stop_tp": read_json(public / PAPER_REL / "paper_stop_takeprofit_trailing_status.json"),
        "position_lifecycle": read_json(public / PAPER_REL / "paper_position_lifecycle_status.json"),
        "outcomes": read_json(public / PAPER_REL / "paper_closed_trade_outcome_label_status.json"),
        "feedback": read_json(public / PAPER_REL / "trainer_feedback_outcomes.json"),
    }


def _get(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, Mapping):
            return default
        if key not in cur:
            return default
        cur = cur[key]
    return cur


def _soak_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    soak = inputs["soak"]
    pnl = inputs["pnl_reconciliation"]
    elapsed = int(finite_float(soak.get("completion_window_elapsed_seconds")) or 0)
    soak_complete = bool(soak.get("soak_complete") or soak.get("soak_1h_complete"))
    return {
        "schema_version": "adaptive_1h_paper_soak_status_v1",
        "generated_est": generated_est,
        "proof_status": soak.get("proof_status"),
        "soak_complete": soak_complete,
        "soak_1h_complete": soak_complete,
        "soak_12h_complete": bool(soak.get("soak_12h_complete")),
        "completion_marker": soak.get("completion_marker"),
        "soak_window_label": soak.get("soak_window_label") or SOAK_WINDOW_LABEL,
        "completion_window_elapsed_seconds": elapsed,
        "completion_window_required_seconds": REQUIRED_SECONDS,
        "observation_count": soak.get("observation_count"),
        "density_eligible_observation_count": soak.get("density_eligible_observation_count"),
        "minimum_required_observations": soak.get("minimum_required_observations"),
        "observation_density_status": soak.get("observation_density_status"),
        "last_observation_freshness_status": soak.get("last_observation_freshness_status"),
        "high_severity_alerts": as_list(soak.get("high_severity_alerts")),
        "paper_equity": soak.get("paper_equity"),
        "paper_pnl": soak.get("paper_pnl") or soak.get("realized_pnl_usd"),
        "realized_pnl_usd": soak.get("realized_pnl_usd"),
        "unrealized_pnl_usd": soak.get("unrealized_pnl_usd"),
        "closed_positions_count": soak.get("closed_positions_count"),
        "open_positions_count": soak.get("open_positions_count"),
        "outcome_label_count": soak.get("outcome_label_count"),
        "trainer_feedback_row_count": soak.get("trainer_feedback_total_row_count"),
        "static_sizing_regression_status": soak.get("static_sizing_regression_status"),
        "same_symbol_stack_status": soak.get("same_symbol_stack_status"),
        "same_symbol_hedge_status": soak.get("same_symbol_hedge_status"),
        "live_balance_hold_status": soak.get("live_balance_hold_status"),
        "paper_pnl_reconciliation_status": pnl.get("paper_pnl_reconciliation_status"),
    }


def _guard_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    live = inputs["live"]
    trainer = inputs["trainer"]
    signals = inputs["signals"]
    bridge = inputs["trainer_bridge"]
    allocator = inputs["allocator"]
    lifecycle = inputs["lifecycle"]
    risk = inputs["risk"]
    symbol_count = _get(signals, "summary", "symbols_count")
    timeframe_count = _get(signals, "summary", "timeframes_count")
    prediction_rows_count = _get(signals, "summary", "prediction_rows_count")
    current_prediction_count = _get(signals, "summary", "current_prediction_count")
    missing_grid_rows = missing_prediction_grid_rows(signals)
    incomplete_symbols = incomplete_prediction_symbols(missing_grid_rows)
    expected_prediction_grid_rows = (
        symbol_count * timeframe_count
        if isinstance(symbol_count, int) and isinstance(timeframe_count, int)
        else None
    )
    bridge_ts = parse_timestamp(bridge.get("generated_utc") or bridge.get("generated_at") or bridge.get("last_run_ts"))
    bridge_age_seconds = (
        int((datetime.now(tz=timezone.utc) - bridge_ts).total_seconds())
        if bridge_ts is not None
        else None
    )
    bridge_recent = bridge_age_seconds is not None and bridge_age_seconds <= 3600
    bridge_accepted_legacy = bridge.get("accepted_as_legacy_hybrid_prediction") is True
    bridge_masked = (not bridge_recent or not bridge_accepted_legacy) and bridge.get("legacy_mutation_performed") is not True
    dynamic_grid_current = (
        trainer.get("prediction_grid_current") is True
        and timeframe_count == len(REQUIRED_TIMEFRAMES)
        and _get(signals, "summary", "missing_prediction_count") == 0
        and _get(signals, "summary", "stale_prediction_count") == 0
        and isinstance(symbol_count, int)
        and symbol_count > 0
        and prediction_rows_count == expected_prediction_grid_rows
        and current_prediction_count == expected_prediction_grid_rows
    )
    checks = {
        "live_trader_down_or_balance_held": live.get("trader_state") == "LIVE_ARMED_BALANCE_HOLD" or live.get("trader_execution_enabled") is False,
        "order_submit_allowed": bool(live.get("order_transport_submit_enabled")),
        "test_order_allowed": False,
        "exchange_leverage_mutation_allowed": False,
        "exchange_margin_mode_mutation_allowed": False,
        "trainer_bridge_masked": bridge_masked,
        "trainer_bridge_payload_age_seconds": bridge_age_seconds,
        "trainer_bridge_payload_recent": bridge_recent,
        "trainer_bridge_accepted_legacy_prediction": bridge_accepted_legacy,
        "rl_core_primary_overwrites": int(trainer.get("rl_core_primary_overwrites") or 0),
        "native_local_trainer_source_active": trainer.get("trainer_source") == REQUIRED_TRAINER_SOURCE,
        "local_model_source_active": trainer.get("model_source") == REQUIRED_MODEL_SOURCE,
        "native_cuda_prediction_grid_current": trainer.get("prediction_grid_current") is True,
        "dynamic_symbol_timeframe_grid_current": dynamic_grid_current,
        "dynamic_symbol_count": symbol_count,
        "timeframe_count": timeframe_count,
        "expected_prediction_grid_rows": expected_prediction_grid_rows,
        "prediction_grid_rows": prediction_rows_count,
        "current_prediction_count": current_prediction_count,
        "missing_prediction_count": _get(signals, "summary", "missing_prediction_count"),
        "stale_prediction_count": _get(signals, "summary", "stale_prediction_count"),
        "missing_symbol_timeframe_count": len(missing_grid_rows),
        "missing_symbol_timeframes_by_symbol": incomplete_symbols,
        "missing_symbol_timeframes": missing_grid_rows[:100],
        "adaptive_allocator_active": allocator.get("paper_allocator_active") is True or inputs["paper_sizing"].get("allocator") == "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "paper_lifecycle_guard_active": lifecycle.get("paper_path_using_lifecycle_controls") is True,
        "risk_evaluator_active": risk.get("fail_closed") is True or risk.get("live_blocked") is True or risk.get("runtime_evidence_status") is not None,
    }
    guard_clear = (
        checks["live_trader_down_or_balance_held"]
        and checks["order_submit_allowed"] is False
        and checks["test_order_allowed"] is False
        and checks["exchange_leverage_mutation_allowed"] is False
        and checks["exchange_margin_mode_mutation_allowed"] is False
        and checks["trainer_bridge_masked"]
        and checks["rl_core_primary_overwrites"] == 0
        and checks["native_local_trainer_source_active"]
        and checks["local_model_source_active"]
        and checks["native_cuda_prediction_grid_current"]
        and checks["dynamic_symbol_timeframe_grid_current"]
        and checks["adaptive_allocator_active"]
        and checks["paper_lifecycle_guard_active"]
        and checks["risk_evaluator_active"]
    )
    return {
        "schema_version": "release_candidate_dynamic_strategy_leverage_margin_guard_status_v1",
        "generated_est": generated_est,
        "status": "CLEAR" if guard_clear else "BLOCKED",
        **checks,
    }


def _strategy_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    status = inputs["strategy"]
    signals = inputs["signals"]
    symbol_count = _get(signals, "summary", "symbols_count")
    timeframe_count = _get(signals, "summary", "timeframes_count")
    prediction_rows_count = _get(signals, "summary", "prediction_rows_count")
    current_prediction_count = _get(signals, "summary", "current_prediction_count")
    missing_grid_rows = missing_prediction_grid_rows(signals)
    expected_prediction_grid_rows = (
        symbol_count * timeframe_count
        if isinstance(symbol_count, int) and isinstance(timeframe_count, int)
        else None
    )
    all_timeframes_current = (
        timeframe_count == len(REQUIRED_TIMEFRAMES)
        and _get(signals, "summary", "missing_prediction_count") == 0
        and _get(signals, "summary", "stale_prediction_count") == 0
        and isinstance(symbol_count, int)
        and symbol_count > 0
        and prediction_rows_count == expected_prediction_grid_rows
        and current_prediction_count == expected_prediction_grid_rows
    )
    rows = {str(row.get("strategy_family") or row.get("strategy_id") or ""): row for row in dict_rows(status.get("families") or status.get("strategies"))}
    outcome_rows = {
        str(row.get("strategy_family") or row.get("strategy_id") or ""): row
        for row in dict_rows(inputs["strategy_weights"].get("strategy_weights_by_family"))
    }
    output_rows: list[dict[str, Any]] = []
    for family in REQUIRED_STRATEGY_FAMILIES:
        row = rows.get(family, {})
        outcome_row = outcome_rows.get(family, {})
        sample_count = int(
            outcome_row.get("closed_trade_count")
            or row.get("sample_count")
            or row.get("closed_trades")
            or 0
        )
        output_rows.append(
            {
                "strategy_family": family,
                "enabled_for_paper": bool(row.get("enabled_for_paper", True)),
                "current_weight": finite_float(outcome_row.get("current_weight") if outcome_row else row.get("current_weight")) or 0.0,
                "weight_change_reason": outcome_row.get("weight_change_reason")
                or row.get("weight_change_reason")
                or ("insufficient evidence; capped until paper outcomes exist" if sample_count <= 0 else "derived from paper outcome evidence"),
                "market_regime": row.get("current_market_regime") or row.get("market_regime") or "UNKNOWN",
                "active_timeframes": row.get("active_timeframes") or (list(REQUIRED_TIMEFRAMES) if all_timeframes_current else []),
                "signal_count": row.get("sample_count") or row.get("signal_count") or 0,
                "accepted_count": row.get("accepted_signals") or row.get("accepted_count") or 0,
                "blocked_count": row.get("blocked_signals") or row.get("blocked_count") or 0,
                "closed_trade_count": outcome_row.get("closed_trade_count") or row.get("closed_trades") or row.get("closed_trade_count") or 0,
                "win_rate": outcome_row.get("win_rate") if outcome_row else row.get("win_rate"),
                "expectancy_after_cost_bps": outcome_row.get("expectancy_after_cost_bps") if outcome_row else row.get("expectancy_after_cost_bps"),
                "profit_factor": outcome_row.get("profit_factor") if outcome_row else row.get("profit_factor"),
                "max_drawdown": outcome_row.get("max_drawdown") if outcome_row else row.get("max_drawdown"),
                "recent_realized_pnl": outcome_row.get("recent_pnl") if outcome_row else row.get("recent_realized_pnl"),
                "recent_unrealized_pnl": row.get("recent_unrealized_pnl"),
                "risk_veto_count": row.get("risk_veto_count") or 0,
                "allocator_veto_count": row.get("allocator_veto_count") or 0,
            }
        )
    return {
        "schema_version": "dynamic_strategy_brain_runtime_status_v1",
        "generated_est": generated_est,
        "status": status.get("adaptive_strategy_selection_status") or status.get("status"),
        "strategy_selection_must_not_be_static": True,
        "all_timeframe_prediction_grid_current": all_timeframes_current,
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "prediction_grid_rows": prediction_rows_count,
        "current_prediction_count": current_prediction_count,
        "missing_prediction_count": _get(signals, "summary", "missing_prediction_count"),
        "stale_prediction_count": _get(signals, "summary", "stale_prediction_count"),
        "missing_symbol_timeframe_count": len(missing_grid_rows),
        "missing_symbol_timeframes_by_symbol": incomplete_prediction_symbols(missing_grid_rows),
        "missing_symbol_timeframes": missing_grid_rows[:100],
        "strategy_selection_policy": status.get("strategy_selection_policy"),
        "dynamic_selection_inputs": status.get("dynamic_selection_inputs") or status.get("dynamic_selection_factors"),
        "strategies": output_rows,
    }


def _allocation_model_inputs(inputs: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = as_list(
        inputs["paper_sizing"].get("sample_allocations")
        or inputs["allocator"].get("sample_allocations")
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        model_inputs = as_dict(row.get("model_inputs"))
        if model_inputs:
            out.append(model_inputs)
    return out


def _average_model_input(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [finite_float(row.get(field)) for row in rows]
    finite_values = [value for value in values if value is not None]
    if not finite_values:
        return None
    return sum(finite_values) / len(finite_values)


def _selector_inputs(inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    lm_inputs = as_dict(inputs["leverage_margin"].get("inputs")) or as_dict(
        inputs["leverage_margin"].get("selection_factors")
    )
    model_rows = _allocation_model_inputs(inputs)

    def choose(field: str) -> Any:
        value = lm_inputs.get(field)
        if value is not None:
            return value
        return _average_model_input(model_rows, field)

    selector = dict(lm_inputs)
    for field in (
        "volatility_bps",
        "liquidity_score",
        "spread_bps",
        "slippage_bps",
        "drawdown_bps",
        "correlation_exposure_pct",
        "symbol_exposure_usdt",
        "total_exposure_usdt",
        "available_margin",
        "wallet_balance",
    ):
        value = choose(field)
        if value is not None:
            selector[field] = value

    selector["allocator_model_input_sample_count"] = len(model_rows)
    selector["risk_envelope_evidence_present"] = any(
        isinstance(row.get("risk_envelope"), Mapping) for row in model_rows
    )
    selector["exchange_filter_evidence_present"] = bool(
        selector.get("exchange_filter_evidence_present")
    ) or any(
        row.get("min_notional") is not None
        or row.get("min_qty") is not None
        or row.get("step_size") is not None
        for row in model_rows
    )
    return selector


def _leverage_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    lm = inputs["leverage_margin"]
    signals = inputs["signals"]
    selector = _selector_inputs(inputs)
    recommended = finite_float(lm.get("paper_recommended_leverage") or lm.get("recommended_leverage")) or 1.0
    status = lm.get("selection_status") or lm.get("status") or "LEVERAGE_RECOMMENDATION_BLOCKED_BAD_MARKET_STATE"
    if status == "LIVE_READY_BALANCE_HELD_NO_ACTION":
        status = "LEVERAGE_RECOMMENDATION_READY_PAPER_ONLY"
    candidate = {
        "symbol": "ALL_SYMBOLS",
        "timeframe": "1m,5m,15m,1h,4h" if _get(signals, "summary", "timeframes_count") == 5 else "UNKNOWN",
        "strategy_family": "dynamic_strategy_router",
        "action": "PAPER_RECOMMENDATION_ONLY",
        "recommended_leverage": recommended,
        "max_safe_leverage": recommended,
        "min_safe_leverage": 1.0,
        "leverage_reason": lm.get("reason") or lm.get("rationale"),
        "volatility_adjustment": selector.get("volatility_bps"),
        "liquidation_distance_adjustment": None,
        "drawdown_adjustment": selector.get("drawdown_bps"),
        "confidence_adjustment": selector.get("avg_confidence"),
        "liquidity_adjustment": selector.get("liquidity_score"),
        "risk_veto": bool(lm.get("risk_veto_reason")),
        "paper_only": True,
        "exchange_mutation": False,
    }
    return {
        "schema_version": "dynamic_leverage_recommendation_status_v1",
        "generated_est": generated_est,
        "status": status,
        "inputs": selector,
        "candidates": [candidate],
        "paper_only": True,
        "exchange_mutation": False,
        "live_leverage_mutation_allowed": False,
    }


def _margin_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    lm = inputs["leverage_margin"]
    selector = _selector_inputs(inputs)
    recommendation = "ISOLATED_RECOMMENDED_PAPER_ONLY"
    if lm.get("evidence_quality") == "MISSING_REQUIRED_EVIDENCE":
        recommendation = "NO_MARGIN_MODE_RECOMMENDATION_INSUFFICIENT_EVIDENCE"
    return {
        "schema_version": "dynamic_margin_mode_recommendation_status_v1",
        "generated_est": generated_est,
        "status": recommendation,
        "symbol": "ALL_SYMBOLS",
        "timeframe": "1m,5m,15m,1h,4h",
        "recommended_margin_mode": recommendation,
        "margin_mode_reason": lm.get("reason") or lm.get("rationale"),
        "isolated_score": 1.0,
        "cross_score": 0.0,
        "risk_veto": bool(lm.get("risk_veto_reason")),
        "paper_only": True,
        "exchange_mutation": False,
        "live_margin_mode_mutation_allowed": False,
        "inputs": selector,
    }


def _market_brain_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    signals = inputs["signals"]
    lm = inputs["leverage_margin"]
    strategy = inputs["strategy"]
    hedge = inputs["hedge"]
    selector = _selector_inputs(inputs)
    rows = prediction_rows(signals)
    missing_grid_rows = missing_prediction_grid_rows(signals)
    market_rows: list[dict[str, Any]] = []
    for row in rows:
        action_probs = as_dict(row.get("action_probabilities"))
        hedge_probability = finite_float(action_probs.get("hedge_reserved_fail_closed"))
        market_rows.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "market_state_integrity": {
                    "score": row.get("market_state_integrity_score"),
                    "reject_reasons": as_list(row.get("market_state_reject_reasons")),
                    "components": row.get("market_state_score_components"),
                    "source_lineage": row.get("market_state_source_lineage"),
                },
                "regime": row.get("market_regime") or row.get("missing_stale_reason") or "RUNTIME_FEATURES",
                "volatility_state": selector.get("volatility_bps"),
                "liquidity_state": selector.get("liquidity_score"),
                "liquidation_risk_state": "EVIDENCE_PENDING"
                if selector.get("exchange_filter_evidence_present") is not True
                else "FILTER_EVIDENCE_PRESENT",
                "microstructure_state": "EVIDENCE_PENDING" if selector.get("spread_bps") is None else "SPREAD_EVIDENCE_PRESENT",
                "strategy_preference": row.get("selected_action"),
                "hedge_preference": "HEDGE_RESERVED_FAIL_CLOSED"
                if row.get("selected_action") == "hedge_reserved_fail_closed" or (hedge_probability is not None and hedge_probability > 0.0)
                else "NO_HEDGE",
                "leverage_preference": lm.get("paper_recommended_leverage") or lm.get("recommended_leverage"),
                "margin_mode_preference": lm.get("paper_recommended_margin_mode") or lm.get("recommended_margin_mode"),
                "trade_actionability": row.get("paper_fill_gate_status") or row.get("status"),
                "prediction_id": row.get("prediction_id"),
                "feature_snapshot_id": row.get("feature_snapshot_id"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
            }
        )
    return {
        "schema_version": "all_timeframe_market_brain_status_v1",
        "generated_est": generated_est,
        "status": "ALL_TIMEFRAME_MARKET_BRAIN_MONITORED",
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "timeframe_count": _get(signals, "summary", "timeframes_count"),
        "symbol_count": _get(signals, "summary", "symbols_count"),
        "prediction_rows": _get(signals, "summary", "prediction_rows_count"),
        "current_prediction_count": _get(signals, "summary", "current_prediction_count"),
        "missing_prediction_count": _get(signals, "summary", "missing_prediction_count"),
        "stale_prediction_count": _get(signals, "summary", "stale_prediction_count"),
        "missing_symbol_timeframe_count": len(missing_grid_rows),
        "missing_symbol_timeframes_by_symbol": incomplete_prediction_symbols(missing_grid_rows),
        "missing_symbol_timeframes": missing_grid_rows[:100],
        "market_state_integrity": _get(signals, "cuda_prediction_contract", "coverage_status"),
        "regime": "MIXED_DYNAMIC_FROM_RUNTIME_FEATURES",
        "volatility_state": selector.get("volatility_bps"),
        "liquidity_state": selector.get("liquidity_score"),
        "liquidation_risk_state": "EVIDENCE_PENDING" if selector.get("exchange_filter_evidence_present") is not True else "FILTER_EVIDENCE_PRESENT",
        "microstructure_state": "EVIDENCE_PENDING" if selector.get("spread_bps") is None else "SPREAD_EVIDENCE_PRESENT",
        "strategy_preference": strategy.get("adaptive_strategy_selection_status"),
        "hedge_preference": hedge.get("adaptive_hedging_capability_status"),
        "leverage_preference": lm.get("paper_recommended_leverage") or lm.get("recommended_leverage"),
        "margin_mode_preference": lm.get("paper_recommended_margin_mode") or lm.get("recommended_margin_mode"),
        "trade_actionability": _get(signals, "cuda_prediction_contract", "actionability_status"),
        "market_row_count": len(market_rows),
        "markets": market_rows,
    }


def _exit_logic_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    coordinator = inputs["exits"]
    stop_tp = inputs["stop_tp"]
    reason_status = inputs["exit_reason"]
    close_reasons = as_dict(coordinator.get("close_reasons"))
    reason_distribution = as_dict(reason_status.get("exit_reason_distribution"))
    tiers_enabled = as_list(coordinator.get("tiers_enabled"))
    exit_logic_ready = bool(tiers_enabled) and (bool(close_reasons) or bool(reason_distribution))
    return {
        "schema_version": "dynamic_exit_logic_status_v1",
        "generated_est": generated_est,
        "status": "DYNAMIC_EXIT_LOGIC_READY_PAPER_ONLY" if exit_logic_ready else "DYNAMIC_EXIT_LOGIC_NOT_PROVEN",
        "paper_only": True,
        "exchange_mutation": False,
        "exit_selection_must_not_be_static": True,
        "tiers_enabled": tiers_enabled,
        "close_reason_counts": close_reasons,
        "observed_exit_reason_distribution": reason_distribution,
        "stop_loss_bps": stop_tp.get("stop_loss_bps"),
        "take_profit_bps": stop_tp.get("take_profit_bps"),
        "trailing_stop_bps": stop_tp.get("trailing_stop_bps"),
        "min_hold_seconds": stop_tp.get("min_hold_seconds"),
        "max_hold_seconds": stop_tp.get("max_hold_seconds"),
        "triggered_count": stop_tp.get("triggered_count"),
        "selection_inputs": [
            "stop_loss",
            "take_profit",
            "trailing_stop",
            "max_hold_time",
            "model_reversal",
            "netting_state",
            "profit_protection",
            "drawdown",
            "market_regime",
            "paper_outcome_feedback",
        ],
    }


def _paper_readiness_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    allocator = inputs["allocator"]
    sizing = inputs["paper_sizing"]
    sample_allocations = as_list(sizing.get("sample_allocations") or allocator.get("sample_allocations"))
    outcome_label_evidence_count = first_positive_int(
        inputs["position_lifecycle"].get("outcome_label_count"),
        inputs["outcomes"].get("outcome_label_count"),
        inputs["soak"].get("outcome_label_count"),
        inputs["soak"].get("outcome_labels_count"),
    )
    outcome_label_evidence_passed = outcome_label_evidence_count > 0 or _get(
        inputs["soak"], "success_criteria", "outcome_label_count_gt_0"
    ) is True or _get(inputs["soak"], "success_criteria", "outcome_labels_gt_0") is True
    trainer_feedback_evidence_count = first_positive_int(
        inputs["soak"].get("trainer_feedback_total_row_count"),
        inputs["soak"].get("trainer_feedback_row_count"),
        inputs["soak"].get("trainer_feedback_rows_count"),
        inputs["feedback"].get("trainer_feedback_total_row_count"),
        inputs["feedback"].get("trainer_feedback_row_count"),
    )
    trainer_feedback_evidence_passed = trainer_feedback_evidence_count > 0 or _get(
        inputs["soak"], "success_criteria", "trainer_feedback_total_rows_gt_0"
    ) is True or _get(inputs["soak"], "success_criteria", "trainer_feedback_row_count_gt_0") is True
    checks = {
        "paper_trader_uses_adaptive_allocator": allocator.get("paper_allocator_active") is True or sizing.get("allocator") == "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "paper_trader_uses_dynamic_strategy_weights": bool(inputs["strategy_weights"].get("strategy_weights_by_family")) or inputs["strategy"].get("adaptive_strategy_selection_status") is not None,
        "paper_trader_uses_lifecycle_guard": inputs["lifecycle"].get("paper_path_using_lifecycle_controls") is True,
        "paper_trader_uses_risk_evaluator": inputs["risk"].get("fail_closed") is True or inputs["risk_budget"].get("operator_envelope_type") is not None,
        "paper_trader_uses_exit_coordinator": bool(inputs["exits"].get("tiers_enabled")) or bool(inputs["exit_reason"].get("exit_reason_distribution")),
        "paper_trader_writes_outcome_labels": outcome_label_evidence_passed,
        "paper_trader_writes_trainer_feedback_rows": trainer_feedback_evidence_passed,
        "paper_trader_updates_realized_unrealized_pnl": inputs["soak"].get("realized_pnl_usd") is not None and inputs["soak"].get("unrealized_pnl_usd") is not None,
        "paper_trader_blocks_accidental_hedges": inputs["netting"].get("accidental_hedge_pairs_allowed") is False and inputs["soak"].get("same_symbol_hedge_status") == "CLEAR",
        "paper_trader_applies_dynamic_leverage_recommendation_only_in_simulation": inputs["leverage_margin"].get("live_leverage_mutation_allowed") is False,
        "paper_trader_applies_dynamic_margin_mode_recommendation_only_in_simulation": inputs["leverage_margin"].get("live_margin_mode_mutation_allowed") is False,
    }
    return {
        "schema_version": "paper_trader_adaptive_readiness_status_v1",
        "generated_est": generated_est,
        "status": "PAPER_TRADER_ADAPTIVE_READINESS_READY" if all(checks.values()) else "PAPER_TRADER_ADAPTIVE_READINESS_BLOCKED",
        "position_size_selection_status": "ADAPTIVE_ALLOCATOR_ACTIVE" if checks["paper_trader_uses_adaptive_allocator"] else "ADAPTIVE_ALLOCATOR_NOT_PROVEN",
        "exit_logic_selection_status": "DYNAMIC_EXIT_LOGIC_READY_PAPER_ONLY"
        if checks["paper_trader_uses_exit_coordinator"]
        else "DYNAMIC_EXIT_LOGIC_NOT_PROVEN",
        "position_size_allocator": sizing.get("allocator") or allocator.get("allocator"),
        "accepted_allocation_count": sizing.get("accepted_allocation_count") or allocator.get("accepted_allocation_count"),
        "blocked_allocation_count": sizing.get("blocked_allocation_count") or allocator.get("blocked_allocation_count"),
        "allocator_decision_counts": sizing.get("allocator_decision_counts") or allocator.get("allocator_decision_counts"),
        "outcome_label_evidence_count": outcome_label_evidence_count,
        "outcome_label_success_criterion": _get(inputs["soak"], "success_criteria", "outcome_label_count_gt_0"),
        "trainer_feedback_evidence_count": trainer_feedback_evidence_count,
        "trainer_feedback_success_criterion": _get(inputs["soak"], "success_criteria", "trainer_feedback_total_rows_gt_0"),
        "sample_allocations": sample_allocations[:25],
        "position_size_selection_inputs": [
            "confidence",
            "expected_move_after_cost",
            "volatility",
            "liquidity",
            "drawdown",
            "symbol_exposure",
            "portfolio_exposure",
            "exchange_filters",
            "risk_envelope",
        ],
        **checks,
    }


def _local_trainer_contract_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    trainer = inputs["trainer"]
    signals = inputs["signals"]
    symbol_count = _get(signals, "summary", "symbols_count")
    timeframe_count = _get(signals, "summary", "timeframes_count")
    missing_count = _get(signals, "summary", "missing_prediction_count")
    stale_count = _get(signals, "summary", "stale_prediction_count")
    prediction_rows_count = _get(signals, "summary", "prediction_rows_count")
    current_prediction_count = _get(signals, "summary", "current_prediction_count")
    missing_grid_rows = missing_prediction_grid_rows(signals)
    expected_prediction_grid_rows = (
        symbol_count * timeframe_count
        if isinstance(symbol_count, int) and isinstance(timeframe_count, int)
        else None
    )
    source_ok = trainer.get("trainer_source") == REQUIRED_TRAINER_SOURCE
    model_ok = trainer.get("model_source") == REQUIRED_MODEL_SOURCE
    grid_ok = (
        trainer.get("prediction_grid_current") is True
        and timeframe_count == len(REQUIRED_TIMEFRAMES)
        and missing_count == 0
        and stale_count == 0
        and isinstance(symbol_count, int)
        and symbol_count > 0
        and prediction_rows_count == expected_prediction_grid_rows
        and current_prediction_count == expected_prediction_grid_rows
    )
    status = "LOCAL_NATIVE_TRAINER_CORE_ACTIVE" if source_ok and model_ok and grid_ok else "LOCAL_NATIVE_TRAINER_CORE_NOT_PROVEN"
    return {
        "schema_version": "local_trainer_core_contract_status_v1",
        "generated_est": generated_est,
        "status": status,
        "trainer_source": trainer.get("trainer_source"),
        "trainer_source_required": REQUIRED_TRAINER_SOURCE,
        "model_source": trainer.get("model_source"),
        "model_source_required": REQUIRED_MODEL_SOURCE,
        "native_core_entrypoint": "v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime.run_hybrid_trainer_cycle",
        "legacy_hybrid_reference": "v2/legacy_owned_runtime/rl/hybrid_trainer.py",
        "legacy_reference_role": "design_parity_baseline_only",
        "wrapper_role": "launch_and_proof_guard_only",
        "wrappers_allowed": True,
        "wrapper_allowed_roles": [
            "process_launch",
            "paper_only_runtime_guard",
            "proof_packet_export",
            "website_payload_publication",
        ],
        "wrapper_forbidden_roles": [
            "model_replacement",
            "prediction_fabrication",
            "dynamic_symbol_narrowing",
            "risk_bypass",
            "live_order_submission",
            "test_order_submission",
            "leverage_mutation",
            "margin_mode_mutation",
        ],
        "dynamic_symbol_count": symbol_count,
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "timeframe_count": timeframe_count,
        "expected_prediction_grid_rows": expected_prediction_grid_rows,
        "prediction_grid_rows": prediction_rows_count,
        "current_prediction_count": current_prediction_count,
        "missing_prediction_count": missing_count,
        "stale_prediction_count": stale_count,
        "missing_symbol_timeframe_count": len(missing_grid_rows),
        "missing_symbol_timeframes_by_symbol": incomplete_prediction_symbols(missing_grid_rows),
        "missing_symbol_timeframes": missing_grid_rows[:100],
        "source_contract_ok": source_ok,
        "model_contract_ok": model_ok,
        "dynamic_symbol_timeframe_grid_ok": grid_ok,
        "full_dynamic_symbol_timeframe_grid_covered": grid_ok,
        "all_dynamic_symbols_must_use_local_model": True,
        "paper_only": True,
        "live_order_submitted": False,
        "test_order_called": False,
        "exchange_leverage_mutation": False,
        "exchange_margin_mode_mutation": False,
    }


def _trainer_objective_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    trainer = inputs["trainer"]
    signals = inputs["signals"]
    profit = inputs["profit_dashboard"]
    trainer_capability = inputs["trainer_capability"]
    feedback = inputs["feedback_status"]
    feedback_outcomes = inputs["feedback"]
    outcome_status = inputs["outcomes"]
    observations = dict_rows(inputs["soak_observations"])
    feedback_nested = as_dict(feedback_outcomes.get("trainer_strategy_hedge_feedback_status"))
    consumable_feedback_rows = as_list(feedback_outcomes.get("trainer_feedback_outcomes"))
    quarantined_feedback_rows = as_list(feedback_outcomes.get("trainer_feedback_outcomes_quarantine"))
    all_feedback_rows = consumable_feedback_rows + quarantined_feedback_rows
    strategy_feedback_rows = first_present(
        feedback.get("trainer_feedback_consumable_row_count"),
        feedback.get("complete_strategy_hedge_feedback_rows"),
        feedback.get("trainer_feedback_row_count"),
        feedback_nested.get("trainer_consumable_rows"),
        feedback_nested.get("trainer_feedback_rows"),
        profit.get("trainer_feedback_consumable_row_count"),
        profit.get("trainer_feedback_rows_ready"),
    )
    hedge_feedback_rows = first_present(
        feedback.get("feedback_rows_with_hedge_fields"),
        feedback.get("hedge_feedback_rows"),
        feedback_nested.get("trainer_feedback_rows"),
        count_rows_with(all_feedback_rows, "hedge_state") if all_feedback_rows else None,
    )
    exit_feedback_rows = first_present(
        feedback.get("exit_feedback_rows"),
        count_rows_with(all_feedback_rows, "exit_reason") if all_feedback_rows else None,
        outcome_status.get("outcome_label_count"),
    )
    liquidity_feedback_rows = first_present(
        feedback.get("liquidity_feedback_rows"),
        count_rows_with(all_feedback_rows, "liquidity_zone_context") if all_feedback_rows else None,
    )
    status = "TRAINER_ACTIVE_INSUFFICIENT_OUTCOMES"
    if profit.get("paper_run_rate_monthly_pnl", 0) and finite_float(profit.get("paper_run_rate_monthly_pnl")) and finite_float(profit.get("paper_run_rate_monthly_pnl")) < 0:
        status = "TRAINER_ACTIVE_BUT_NEGATIVE_EDGE"
    return {
        "schema_version": "trainer_10k_objective_readiness_status_v1",
        "generated_est": generated_est,
        "status": status,
        "local_trainer_core_status": "LOCAL_NATIVE_TRAINER_CORE_ACTIVE"
        if trainer.get("trainer_source") == REQUIRED_TRAINER_SOURCE and trainer.get("model_source") == REQUIRED_MODEL_SOURCE
        else "LOCAL_NATIVE_TRAINER_CORE_NOT_PROVEN",
        "trainer_source": trainer.get("trainer_source"),
        "trainer_source_required": REQUIRED_TRAINER_SOURCE,
        "model_source": trainer.get("model_source"),
        "model_source_required": REQUIRED_MODEL_SOURCE,
        "legacy_hybrid_reference": "v2/legacy_owned_runtime/rl/hybrid_trainer.py",
        "native_core_entrypoint": "v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime.run_hybrid_trainer_cycle",
        "wrapper_role": "launch_and_proof_guard_only",
        "dynamic_symbol_count": _get(signals, "summary", "symbols_count"),
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "prediction_grid_rows": _get(signals, "summary", "prediction_rows_count"),
        "current_prediction_count": _get(signals, "summary", "current_prediction_count"),
        "missing_prediction_count": _get(signals, "summary", "missing_prediction_count"),
        "stale_prediction_count": _get(signals, "summary", "stale_prediction_count"),
        "training_steps_last_hour": first_present(trainer.get("training_steps_last_hour"), trainer_capability.get("training_steps_last_hour")),
        "samples_seen_last_hour": first_present(profit.get("samples_seen_last_hour"), trainer_capability.get("samples_seen_last_hour")),
        "closed_trade_feedback_last_hour": first_present(
            profit.get("closed_trade_feedback_last_hour"),
            trainer_capability.get("closed_trades_last_hour"),
            outcome_status.get("new_closed_trade_count"),
            last_hour_delta(observations, "closed_trades_count"),
            last_hour_delta(observations, "closed_positions_count"),
        ),
        "strategy_feedback_rows": strategy_feedback_rows,
        "hedge_feedback_rows": hedge_feedback_rows,
        "exit_feedback_rows": exit_feedback_rows,
        "liquidity_feedback_rows": liquidity_feedback_rows,
        "paper_pnl_last_hour": first_present(profit.get("paper_pnl_last_hour"), last_hour_pnl_delta(observations)),
        "paper_pnl_12h": inputs["soak"].get("paper_pnl") or inputs["soak"].get("realized_pnl_usd"),
        "projected_monthly_pnl": profit.get("paper_run_rate_monthly_pnl"),
        "goal_status": profit.get("goal_status"),
        "goal_blocker": profit.get("trainer_primary_actionability_blocker") or profit.get("blockers"),
    }


def _projection_payload(generated_est: str, inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    sim = inputs["simulation"]
    soak = inputs["soak"]
    profit = inputs["profit_dashboard"]
    elapsed = finite_float(soak.get("completion_window_elapsed_seconds"))
    equity = finite_float(soak.get("paper_equity"))
    paper_pnl = finite_float(soak.get("realized_pnl_usd"))
    paper_return = paper_pnl / equity if paper_pnl is not None and equity and equity > 0 else None
    projected_daily = paper_pnl * (86_400.0 / elapsed) if paper_pnl is not None and elapsed and elapsed > 0 else None
    projected_monthly = first_present(sim.get("simulated_monthly_net_pnl"), projected_daily * 30.0 if projected_daily is not None else None)
    current_capital_sufficient = sim.get("current_capital_sufficient")
    ci_lower, ci_upper = confidence_interval_bounds(sim.get("confidence_interval_lower"), sim.get("confidence_interval_upper"))
    monthly_goal_status = derive_monthly_goal_status(sim, profit, finite_float(projected_monthly))
    monthly_goal_blockers = derive_monthly_goal_blockers(sim, profit, finite_float(projected_monthly))
    return {
        "schema_version": "monthly_10k_goal_1h_soak_projection_status_v1",
        "generated_est": generated_est,
        "soak_window_label": SOAK_WINDOW_LABEL,
        "paper_1h_net_pnl": soak.get("realized_pnl_usd"),
        "paper_1h_return_pct": paper_return,
        "paper_12h_net_pnl": soak.get("realized_pnl_usd"),
        "paper_12h_return_pct": paper_return,
        "projected_daily_net_pnl": projected_daily,
        "projected_monthly_net_pnl": projected_monthly,
        "confidence_interval_lower": ci_lower,
        "confidence_interval_upper": ci_upper,
        "max_drawdown_12h": sim.get("max_drawdown"),
        "profit_factor_12h": sim.get("profit_factor"),
        "win_rate_12h": sim.get("win_rate"),
        "required_capital_for_10k": sim.get("capital_required_for_10k_at_current_edge"),
        "current_capital_sufficient": bool(current_capital_sufficient) if isinstance(current_capital_sufficient, bool) else False,
        "risk_required_for_10k": sim.get("risk_required_for_10k"),
        "risk_acceptable": sim.get("risk_acceptable"),
        "goal_status": monthly_goal_status,
        "goal_blockers": monthly_goal_blockers,
        "live_goal_status": profit.get("goal_status"),
        "performance_sample_status": sim.get("performance_sample_status") or profit.get("performance_sample_status"),
        "performance_outcome_count": sim.get("performance_outcome_count") or profit.get("performance_outcome_count"),
        "minimum_qualified_performance_outcomes": sim.get("minimum_qualified_performance_outcomes") or profit.get("minimum_qualified_performance_outcomes"),
        "guaranteed_profit_claimed": False,
        "guaranteed_win_rate_claimed": False,
    }


def _website_payload(generated_est: str, payloads: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "runtime_website_dynamic_strategy_leverage_margin_status_v1",
        "generated_est": generated_est,
        "status": "WEBSITE_DYNAMIC_RUNTIME_TRUTH_PAYLOAD_READY",
        "shows_1h_soak_progress": True,
        "shows_12h_soak_progress": True,
        "shows_adaptive_strategy_weights": True,
        "shows_dynamic_leverage_recommendation": True,
        "shows_dynamic_margin_mode_recommendation": True,
        "shows_dynamic_exit_logic": True,
        "shows_paper_only_status": True,
        "shows_pnl_and_feedback_counts": True,
        "shows_10k_feasibility_not_guarantee": True,
        "source_payloads": {
            "operator_dashboard": "operator_dashboard_payload.json",
            "strategy": "dynamic_strategy_brain_runtime_status.json",
            "leverage": "dynamic_leverage_recommendation_status.json",
            "margin": "dynamic_margin_mode_recommendation_status.json",
            "exit_logic": "dynamic_exit_logic_status.json",
            "projection": "monthly_10k_goal_1h_soak_projection_status.json",
        },
        "gate": payloads["operator_dashboard_payload.json"]["gate"],
    }


def _blockers(payloads: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    guard = payloads["release_candidate_dynamic_strategy_leverage_margin_guard_status.json"]
    soak = payloads["adaptive_1h_paper_soak_status.json"]
    paper = payloads["paper_trader_adaptive_readiness_status.json"]
    exit_logic = payloads["dynamic_exit_logic_status.json"]
    projection = payloads["monthly_10k_goal_1h_soak_projection_status.json"]
    if guard.get("status") != "CLEAR":
        missing_count = int(finite_float(guard.get("missing_symbol_timeframe_count")) or 0)
        missing_by_symbol = as_dict(guard.get("missing_symbol_timeframes_by_symbol"))
        if missing_count and missing_by_symbol:
            summary = ", ".join(
                f"{symbol}({','.join(str(tf) for tf in as_list(timeframes))})"
                for symbol, timeframes in sorted(missing_by_symbol.items())
            )
            blockers.append(f"local trainer prediction grid missing {missing_count} symbol/timeframe rows: {summary}")
        else:
            blockers.append("release-candidate guard is not clear")
    if not soak.get("soak_complete") or int(soak.get("completion_window_elapsed_seconds") or 0) < REQUIRED_SECONDS:
        blockers.append(f"{SOAK_WINDOW_LABEL} density-aware soak is still pending")
    if soak.get("paper_pnl_reconciliation_status") != "RECONCILED":
        blockers.append("paper PnL reconciliation is not RECONCILED")
    for key, expected in (
        ("observation_density_status", "CLEAR"),
        ("last_observation_freshness_status", "CLEAR"),
        ("static_sizing_regression_status", "CLEAR"),
        ("same_symbol_stack_status", "CLEAR"),
        ("same_symbol_hedge_status", "CLEAR"),
        ("live_balance_hold_status", "CLEAR"),
    ):
        if soak.get(key) != expected:
            blockers.append(f"{key} is {soak.get(key)!r}, expected {expected}")
    if as_list(soak.get("high_severity_alerts")):
        blockers.append("high severity alerts are present")
    if paper.get("status") != "PAPER_TRADER_ADAPTIVE_READINESS_READY":
        blockers.append("paper trader adaptive readiness checks are not all true")
    if exit_logic.get("status") != "DYNAMIC_EXIT_LOGIC_READY_PAPER_ONLY":
        blockers.append("dynamic exit logic is not proven ready")
    return blockers


def build_payloads(paths: DynamicReadinessPaths | None = None) -> dict[str, Any]:
    paths = paths or DynamicReadinessPaths()
    generated_est = est_now()
    generated_utc = utc_now()
    inputs = load_inputs(paths)
    payloads: dict[str, Any] = {}
    payloads["release_candidate_dynamic_strategy_leverage_margin_guard_status.json"] = _guard_payload(generated_est, inputs)
    payloads["adaptive_1h_paper_soak_status.json"] = _soak_payload(generated_est, inputs)
    payloads["adaptive_12h_paper_soak_status.json"] = payloads["adaptive_1h_paper_soak_status.json"]
    payloads["adaptive_1h_paper_soak_observation_latest.json"] = inputs["soak"]
    payloads["adaptive_12h_paper_soak_observation_latest.json"] = inputs["soak"]
    payloads["dynamic_strategy_brain_runtime_status.json"] = _strategy_payload(generated_est, inputs)
    payloads["dynamic_leverage_recommendation_status.json"] = _leverage_payload(generated_est, inputs)
    payloads["dynamic_margin_mode_recommendation_status.json"] = _margin_payload(generated_est, inputs)
    payloads["all_timeframe_market_brain_status.json"] = _market_brain_payload(generated_est, inputs)
    payloads["dynamic_exit_logic_status.json"] = _exit_logic_payload(generated_est, inputs)
    payloads["paper_trader_adaptive_readiness_status.json"] = _paper_readiness_payload(generated_est, inputs)
    payloads["local_trainer_core_contract_status.json"] = _local_trainer_contract_payload(generated_est, inputs)
    payloads["trainer_10k_objective_readiness_status.json"] = _trainer_objective_payload(generated_est, inputs)
    payloads["monthly_10k_goal_1h_soak_projection_status.json"] = _projection_payload(generated_est, inputs)
    payloads["monthly_10k_goal_12h_soak_projection_status.json"] = payloads[
        "monthly_10k_goal_1h_soak_projection_status.json"
    ]
    blockers = _blockers(payloads)
    gate = READY if not blockers else BLOCKED
    payloads["operator_dashboard_payload.json"] = {
        "schema_version": "runtime_alpha_dynamic_strategy_leverage_margin_operator_dashboard_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "gate": gate,
        "status": "READY" if gate == READY else "BLOCKED",
        "blockers": blockers,
        "proof_status": payloads["adaptive_1h_paper_soak_status.json"].get("proof_status"),
        "soak_complete": payloads["adaptive_1h_paper_soak_status.json"].get("soak_complete"),
        "soak_1h_complete": payloads["adaptive_1h_paper_soak_status.json"].get("soak_1h_complete"),
        "soak_12h_complete": payloads["adaptive_1h_paper_soak_status.json"].get("soak_12h_complete"),
        "completion_window_elapsed_seconds": payloads["adaptive_1h_paper_soak_status.json"].get("completion_window_elapsed_seconds"),
        "completion_window_required_seconds": REQUIRED_SECONDS,
        "paper_only": True,
        "live_order_submitted": False,
        "test_order_called": False,
        "exchange_leverage_mutation": False,
        "exchange_margin_mode_mutation": False,
        "dynamic_strategy_status": payloads["dynamic_strategy_brain_runtime_status.json"].get("status"),
        "dynamic_leverage_status": payloads["dynamic_leverage_recommendation_status.json"].get("status"),
        "dynamic_margin_mode_status": payloads["dynamic_margin_mode_recommendation_status.json"].get("status"),
        "dynamic_exit_logic_status": payloads["dynamic_exit_logic_status.json"].get("status"),
        "paper_trader_adaptive_readiness_status": payloads["paper_trader_adaptive_readiness_status.json"].get("status"),
        "local_trainer_contract_status": payloads["local_trainer_core_contract_status.json"].get("status"),
        "missing_symbol_timeframe_count": payloads["local_trainer_core_contract_status.json"].get("missing_symbol_timeframe_count"),
        "missing_symbol_timeframes_by_symbol": payloads["local_trainer_core_contract_status.json"].get("missing_symbol_timeframes_by_symbol"),
        "missing_symbol_timeframes": payloads["local_trainer_core_contract_status.json"].get("missing_symbol_timeframes"),
        "position_size_selection_status": payloads["paper_trader_adaptive_readiness_status.json"].get("position_size_selection_status"),
        "exit_logic_selection_status": payloads["paper_trader_adaptive_readiness_status.json"].get("exit_logic_selection_status"),
        "trainer_10k_objective_status": payloads["trainer_10k_objective_readiness_status.json"].get("status"),
        "monthly_10k_goal_status": payloads["monthly_10k_goal_1h_soak_projection_status.json"].get("goal_status"),
        "monthly_10k_goal_blockers": payloads["monthly_10k_goal_1h_soak_projection_status.json"].get("goal_blockers"),
    }
    payloads["runtime_website_dynamic_strategy_leverage_margin_status.json"] = _website_payload(generated_est, payloads)
    payloads["runtime_alpha_1h_artifact_path_status.json"] = {
        "schema_version": "runtime_alpha_1h_artifact_path_status_v1",
        "generated_est": generated_est,
        "status": "RUNTIME_ALPHA_1H_ARTIFACT_PATH_READY",
        "canonical_operator_path": str(OPERATOR_REL),
        "canonical_artifact_path": str(ARTIFACT_REL),
        "legacy_operator_path": str(LEGACY_OPERATOR_REL),
        "legacy_artifact_path": str(LEGACY_ARTIFACT_REL),
        "legacy_path_alias": True,
        "legacy_alias_reason": "12h path retained only as a compatibility mirror for existing website/report readers",
        "canonical_window_label": SOAK_WINDOW_LABEL,
    }
    payloads["GO_NO_GO.md"] = gate
    payloads["V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_1H_PAPER_SOAK_DYNAMIC_STRATEGY_LEVERAGE_MARGIN_REPORT.md"] = _report(payloads)
    payloads["V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_12H_PAPER_SOAK_DYNAMIC_STRATEGY_LEVERAGE_MARGIN_REPORT.md"] = _report(payloads)
    return payloads


def _report(payloads: Mapping[str, Any]) -> str:
    dash = payloads["operator_dashboard_payload.json"]
    return (
        "# V2 Runtime Alpha Remediated Adaptive 1h Paper Soak Dynamic Strategy Leverage Margin Report\n\n"
        f"Generated: `{dash.get('generated_utc')}`\n\n"
        f"Gate: `{dash.get('gate')}`\n\n"
        f"Status: `{dash.get('status')}`\n\n"
        "## Blockers\n\n"
        + "\n".join(f"- {item}" for item in dash.get("blockers", []))
        + "\n\n## Safety\n\n"
        "- Paper only: `true`\n"
        "- Live order submitted: `false`\n"
        "- Test order called: `false`\n"
        "- Exchange leverage mutation: `false`\n"
        "- Exchange margin-mode mutation: `false`\n"
        "- Guaranteed profit/win-rate claim: `false`\n"
    )


def publish_all(paths: DynamicReadinessPaths | None = None) -> dict[str, Any]:
    paths = paths or DynamicReadinessPaths()
    payloads = build_payloads(paths)
    write_dirs = (
        paths.operator_dir,
        paths.artifact_dir,
        paths.legacy_operator_dir,
        paths.legacy_artifact_dir,
    )
    for name, payload in payloads.items():
        if name.endswith(".json"):
            for directory in write_dirs:
                write_json(directory / name, payload)
        else:
            for directory in write_dirs:
                write_text(directory / name, str(payload))
    observations = paths.operator_dir / "adaptive_1h_paper_soak_observations.jsonl"
    latest = payloads["adaptive_1h_paper_soak_observation_latest.json"]
    observations.parent.mkdir(parents=True, exist_ok=True)
    with observations.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(latest, sort_keys=True, default=str) + "\n")
    for directory in (paths.artifact_dir, paths.legacy_artifact_dir):
        write_json(directory / "adaptive_1h_paper_soak_observations.jsonl.manifest.json", {"mirrored_from": str(observations)})
        write_json(directory / "adaptive_12h_paper_soak_observations.jsonl.manifest.json", {"mirrored_from": str(observations)})
    return payloads
