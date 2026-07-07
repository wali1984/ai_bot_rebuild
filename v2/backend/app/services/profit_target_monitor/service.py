"""Read-only monthly 10k net-profit target monitor.

The monitor evaluates feasibility from current V2 paper/runtime artifacts and
optional V2 Redis reads. It writes V2-owned public JSON/Markdown artifacts only.
It never calls exchange endpoints, never submits orders or test-orders, never
changes leverage or margin mode, and never writes Redis.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .contracts import (
    BLOCKED,
    DAYS_PER_MONTH,
    HOURS_PER_MONTH,
    MONTHLY_TARGET_NET_USDT,
    READY,
    REQUIRED_TRAINER_FEEDBACK_FIELDS,
    STRATEGY_FAMILIES,
)


REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_ROOT = REPO_ROOT / "v2/frontend/public"
ARTIFACT_REL = Path("v2_monthly_10k_profit_target_trainer_strategy_hedge_monitor/latest")
OPERATOR_REL = Path("operator_runtime/v2_monthly_10k_profit_target_monitor/latest")
WORKLOG_REL = Path("claude_worklog/final_readiness") / ARTIFACT_REL
EST = ZoneInfo("America/New_York")

PORTFOLIO_REL = Path("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")
NATIVE_TRAINER_REL = Path("operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json")
PREDICTIONS_REL = Path("operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json")
LIVE_GATE_REL = Path("operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json")
REMEDIATED_SOAK_STATUS_REL = Path(
    "operator_runtime/v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest/runtime_alpha_remediated_soak_status.json"
)
REMEDIATED_SOAK_OBSERVATIONS_REL = Path(
    "operator_runtime/v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest/runtime_alpha_remediated_soak_observations.jsonl"
)
SOAK_STATUS_REL = Path("operator_runtime/v2_adaptive_allocation_and_trade_lifecycle_24h_paper_soak/latest/soak_status.json")
SOAK_OBSERVATIONS_REL = Path("operator_runtime/v2_adaptive_allocation_and_trade_lifecycle_24h_paper_soak/latest/soak_observations.jsonl")
TRADE_MANAGEMENT_REL = Path("operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json")
PAPER_TRADE_REL = Path("operator_runtime/v2_paper_trade_management/latest")
REQUIRED_PREDICTION_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
REDIS_PREDICTION_FRESH_SECONDS = 900


@dataclass(frozen=True)
class ProfitTargetMonitorPaths:
    repo_root: Path = REPO_ROOT
    public_root: Path = PUBLIC_ROOT

    @property
    def artifact_dir(self) -> Path:
        return self.public_root / ARTIFACT_REL

    @property
    def operator_dir(self) -> Path:
        return self.public_root / OPERATOR_REL

    @property
    def worklog_dir(self) -> Path:
        return self.repo_root / WORKLOG_REL


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def dict_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("rows", "positions", "open_positions", "closed_positions", "closed_trades", "outcome_labels", "new_outcome_labels"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [dict(row) for row in nested if isinstance(row, Mapping)]
    return []


def is_canonical_position_row(row: Mapping[str, Any]) -> bool:
    """Return true for net/open position rows, not raw fill ledger rows."""
    if row.get("open_position") is True:
        return True
    if row.get("net_quantity") is not None:
        return True
    if isinstance(row.get("source_fill_ids"), list):
        return True
    if row.get("opened_est"):
        return True
    if row.get("position_id"):
        return True
    state = str(row.get("position_state") or row.get("status") or "").upper()
    return bool(state and ("POSITION" in state or state in {"OPEN", "CLOSED"}))


def canonical_position_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if is_canonical_position_row(row)]


def portfolio_open_positions(portfolio: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = dict_rows(portfolio.get("open_positions"))
    if rows:
        return rows
    positions = dict_rows(portfolio.get("positions"))
    return [
        row
        for row in positions
        if row.get("open_position") is True
        or "OPEN" in str(row.get("position_state") or row.get("status") or "").upper()
    ]


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def read_first_json(public_root: Path, *relative_paths: Path) -> dict[str, Any]:
    for relative_path in relative_paths:
        path = public_root / relative_path
        if path.exists():
            payload = read_json(path, {})
            if isinstance(payload, Mapping):
                return dict(payload)
    return {}


def read_first_jsonl(public_root: Path, *relative_paths: Path) -> list[dict[str, Any]]:
    for relative_path in relative_paths:
        path = public_root / relative_path
        if path.exists():
            rows = read_jsonl(path)
            if rows:
                return rows
    return []


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


def connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        client.ping()
        return client
    except Exception:
        return None


def redis_json(client: Any, key: str, default: Any = None) -> Any:
    if client is None or not key.startswith("v2:"):
        return {} if default is None else default
    try:
        raw = client.get(key)
    except Exception:
        return {} if default is None else default
    if raw is None:
        return {} if default is None else default
    try:
        return json.loads(raw)
    except Exception:
        return {} if default is None else default


def _prediction_payload_time(payload: Mapping[str, Any]) -> datetime | None:
    for key in ("generated_utc", "generated_at", "generated_est", "source_generated_utc", "source_generated_at"):
        parsed = parse_time(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def redis_prediction_timeframe_inventory(
    client: Any,
    *,
    now_utc: datetime | None = None,
    fresh_seconds: int = REDIS_PREDICTION_FRESH_SECONDS,
) -> dict[str, dict[str, list[str]]]:
    if client is None:
        return {"current": {}, "stale": {}, "unknown_time": {}}
    now_utc = now_utc or datetime.now(timezone.utc)
    current: defaultdict[str, set[str]] = defaultdict(set)
    stale: defaultdict[str, set[str]] = defaultdict(set)
    unknown_time: defaultdict[str, set[str]] = defaultdict(set)
    try:
        for key in client.scan_iter(match="v2:prediction:*", count=500):
            parts = str(key).split(":")
            if len(parts) < 4 or parts[2] == "rl_core":
                continue
            symbol = parts[2].upper()
            timeframe = parts[3]
            payload: dict[str, Any] = {}
            try:
                raw = client.get(key)
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            generated_at = _prediction_payload_time(payload)
            if generated_at is None:
                unknown_time[symbol].add(timeframe)
                continue
            age_seconds = (now_utc - generated_at).total_seconds()
            if -60 <= age_seconds <= fresh_seconds:
                current[symbol].add(timeframe)
            else:
                stale[symbol].add(timeframe)
    except Exception:
        return {"current": {}, "stale": {}, "unknown_time": {}}
    return {
        "current": {symbol: sorted(timeframes) for symbol, timeframes in sorted(current.items())},
        "stale": {symbol: sorted(timeframes) for symbol, timeframes in sorted(stale.items())},
        "unknown_time": {symbol: sorted(timeframes) for symbol, timeframes in sorted(unknown_time.items())},
    }


def redis_prediction_timeframes_by_symbol(client: Any) -> dict[str, list[str]]:
    return redis_prediction_timeframe_inventory(client).get("current", {})


def redis_key_exists(client: Any, key: str) -> bool:
    if client is None or not key.startswith("v2:"):
        return False
    try:
        return bool(client.exists(key))
    except Exception:
        return False


def missing_prediction_input_diagnostics(
    client: Any,
    prediction_payload: Mapping[str, Any],
) -> dict[str, Any]:
    missing_by_symbol: defaultdict[str, set[str]] = defaultdict(set)
    payload_timeframes = as_dict(prediction_payload.get("missing_prediction_timeframes_by_symbol"))
    for symbol, timeframes in payload_timeframes.items():
        for timeframe in as_list(timeframes):
            if symbol and timeframe:
                missing_by_symbol[str(symbol).upper()].add(str(timeframe))
    for row in dict_rows(prediction_payload.get("prediction_rows")):
        if str(row.get("status") or "") != "MISSING_TF_PREDICTION":
            continue
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if symbol and timeframe:
            missing_by_symbol[symbol].add(timeframe)
    for symbol in as_list(prediction_payload.get("missing_prediction_symbols")):
        if symbol:
            missing_by_symbol.setdefault(str(symbol).upper(), set(REQUIRED_PREDICTION_TIMEFRAMES))

    reason_counts: Counter[str] = Counter()
    rows: dict[str, dict[str, Any]] = {}
    for symbol in sorted(missing_by_symbol):
        timeframes = sorted(
            missing_by_symbol[symbol],
            key=lambda tf: REQUIRED_PREDICTION_TIMEFRAMES.index(tf)
            if tf in REQUIRED_PREDICTION_TIMEFRAMES
            else len(REQUIRED_PREDICTION_TIMEFRAMES),
        )
        missing_closed = [
            timeframe
            for timeframe in timeframes
            if not redis_key_exists(client, f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}")
        ]
        missing_features = [
            timeframe
            for timeframe in timeframes
            if not (
                redis_key_exists(client, f"v2:features:latest:{symbol}:{timeframe}")
                or redis_key_exists(client, f"v2:unified_features:{symbol}:{timeframe}:latest")
                or redis_key_exists(client, f"v2:unified_features:{symbol}:{timeframe}")
            )
        ]
        if missing_closed:
            reason_counts["MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE"] += len(missing_closed)
        if missing_features:
            reason_counts["MISSING_FEATURE_PAYLOAD"] += len(missing_features)
        if not missing_closed and not missing_features:
            reason_counts["TRAINING_TRUST_CONTRACT_REJECTED_DESPITE_BASIC_INPUTS_PRESENT"] += len(timeframes)
        rows[symbol] = {
            "missing_prediction_timeframes": timeframes,
            "missing_closed_candle_timeframes": missing_closed,
            "missing_feature_payload_timeframes": missing_features,
            "likely_root_cause": (
                "MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE"
                if missing_closed
                else "MISSING_FEATURE_PAYLOAD"
                if missing_features
                else "TRAINING_TRUST_CONTRACT_REJECTED_DESPITE_BASIC_INPUTS_PRESENT"
            ),
        }
    return {
        "missing_prediction_input_diagnostics_by_symbol": rows,
        "missing_prediction_input_reason_counts": dict(reason_counts.most_common()),
    }


def rows_since(rows: list[dict[str, Any]], *, now_utc: datetime, seconds: int, time_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    cutoff = now_utc - timedelta(seconds=seconds)
    output: list[dict[str, Any]] = []
    for row in rows:
        row_time = None
        for key in time_keys:
            row_time = parse_time(row.get(key))
            if row_time is not None:
                break
        if row_time is not None and row_time >= cutoff:
            output.append(row)
    return output


def sum_numbers(rows: list[dict[str, Any]], *keys: str) -> float:
    total = 0.0
    for row in rows:
        for key in keys:
            value = finite_float(row.get(key))
            if value is not None:
                total += value
                break
    return total


def avg_numbers(rows: list[dict[str, Any]], *keys: str) -> float | None:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = finite_float(row.get(key))
            if value is not None:
                values.append(value)
                break
    return statistics.fmean(values) if values else None


def win_rate(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    wins = 0
    usable = 0
    for row in rows:
        if isinstance(row.get("winner"), bool):
            usable += 1
            wins += 1 if row["winner"] else 0
            continue
        pnl = finite_float(row.get("realized_pnl_usd"))
        if pnl is None:
            pnl = finite_float(row.get("realized_pnl_bps"))
        if pnl is not None:
            usable += 1
            wins += 1 if pnl > 0 else 0
    return (wins / usable) if usable else None


def profit_factor(rows: list[dict[str, Any]]) -> float | None:
    gross_profit = 0.0
    gross_loss = 0.0
    for row in rows:
        pnl = finite_float(row.get("realized_pnl_usd"))
        if pnl is None:
            pnl = finite_float(row.get("realized_pnl_bps"))
        if pnl is None:
            continue
        if pnl > 0:
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)
    if gross_profit <= 0 and gross_loss <= 0:
        return None
    if gross_loss <= 0:
        return None
    return gross_profit / gross_loss


def filter_observations_since(
    observations: list[dict[str, Any]],
    *,
    start_utc: str | None = None,
) -> list[dict[str, Any]]:
    start_time = parse_time(start_utc)
    if start_time is None:
        return list(observations)
    filtered: list[dict[str, Any]] = []
    for row in observations:
        observed_at = parse_time(row.get("observed_utc") or row.get("generated_utc"))
        if observed_at is not None and observed_at >= start_time:
            filtered.append(row)
    return filtered or list(observations)


def drawdown_from_observations(
    observations: list[dict[str, Any]],
    *,
    fallback_bps: float | None = None,
    start_utc: str | None = None,
) -> dict[str, Any]:
    window = filter_observations_since(observations, start_utc=start_utc)
    candidates: list[tuple[str, float]] = []
    reported_values = [
        value for row in window if (value := finite_float(row.get("drawdown_bps"))) is not None and value >= 0
    ]
    if reported_values:
        candidates.append(("reported_drawdown_bps", max(reported_values)))

    equity_points: list[tuple[datetime, float]] = []
    for row in window:
        observed_at = parse_time(row.get("observed_utc") or row.get("generated_utc"))
        equity = finite_float(row.get("paper_equity"))
        if observed_at is not None and equity is not None and equity > 0:
            equity_points.append((observed_at, equity))
    if len(equity_points) >= 2:
        equity_points.sort(key=lambda item: item[0])
        peak = equity_points[0][1]
        max_equity_drawdown_bps = 0.0
        for _observed_at, equity in equity_points:
            peak = max(peak, equity)
            if peak > 0:
                max_equity_drawdown_bps = max(max_equity_drawdown_bps, ((peak - equity) / peak) * 10_000.0)
        candidates.append(("paper_equity_curve", max_equity_drawdown_bps))

    if fallback_bps is not None and fallback_bps >= 0:
        candidates.append(("portfolio_current_drawdown_bps", fallback_bps))

    if not candidates:
        return {
            "max_drawdown_bps": None,
            "drawdown_source": "MISSING_DRAWDOWN_EVIDENCE",
            "drawdown_observation_count": len(window),
            "drawdown_equity_point_count": len(equity_points),
            "drawdown_window_start_utc": start_utc,
        }
    source, value = max(candidates, key=lambda item: item[1])
    return {
        "max_drawdown_bps": value,
        "drawdown_source": source,
        "drawdown_observation_count": len(window),
        "drawdown_equity_point_count": len(equity_points),
        "drawdown_window_start_utc": start_utc,
    }


def max_drawdown_from_observations(
    observations: list[dict[str, Any]],
    fallback_bps: float | None = None,
    *,
    start_utc: str | None = None,
) -> float | None:
    return drawdown_from_observations(
        observations,
        fallback_bps=fallback_bps,
        start_utc=start_utc,
    )["max_drawdown_bps"]


def paper_24h_pnl(
    observations: list[dict[str, Any]],
    portfolio: Mapping[str, Any],
    now_utc: datetime,
    *,
    start_utc: str | None = None,
) -> float | None:
    window = filter_observations_since(observations, start_utc=start_utc)
    recent = rows_since(window, now_utc=now_utc, seconds=24 * 3600, time_keys=("observed_utc",))
    points: list[tuple[datetime, float]] = []
    for row in recent:
        ts = parse_time(row.get("observed_utc"))
        equity = finite_float(row.get("paper_equity"))
        if ts is not None and equity is not None and equity > 0:
            points.append((ts, equity))
    if len(points) >= 2:
        points.sort(key=lambda item: item[0])
        return points[-1][1] - points[0][1]
    total_pnl = finite_float(portfolio.get("total_pnl_usd"))
    return total_pnl


def required_return_pct(target: float, capital: float | None) -> float | None:
    if capital is None or capital <= 0:
        return None
    return target / capital


def prediction_rows(predictions_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return dict_rows(predictions_payload.get("prediction_rows"))


def current_edge_after_cost_bps(rows: list[dict[str, Any]]) -> float | None:
    allowed = [row for row in rows if row.get("paper_fill_allowed") is True]
    positive = [
        row
        for row in (allowed or rows)
        if (finite_float(row.get("expected_move_after_cost_bps")) or 0.0) > 0
    ]
    return avg_numbers(positive or allowed or rows, "expected_move_after_cost_bps")


def confidence_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for row in rows if (value := finite_float(row.get("confidence_calibrated"))) is not None]
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None, "high_count": 0, "mid_count": 0, "low_count": 0}
    return {
        "count": len(values),
        "min": round(min(values), 8),
        "median": round(statistics.median(values), 8),
        "max": round(max(values), 8),
        "high_count": sum(1 for value in values if value >= 0.65),
        "mid_count": sum(1 for value in values if 0.5 <= value < 0.65),
        "low_count": sum(1 for value in values if value < 0.5),
    }


def expected_move_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for row in rows if (value := finite_float(row.get("expected_move_after_cost_bps"))) is not None]
    if not values:
        return {"count": 0, "min_bps": None, "median_bps": None, "max_bps": None, "positive_count": 0}
    return {
        "count": len(values),
        "min_bps": round(min(values), 8),
        "median_bps": round(statistics.median(values), 8),
        "max_bps": round(max(values), 8),
        "positive_count": sum(1 for value in values if value > 0),
    }


def calibration_error(rows: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> float | None:
    rate = win_rate(outcomes)
    confidence = avg_numbers(rows, "confidence_calibrated")
    if rate is None or confidence is None:
        return None
    return abs(confidence - rate)


def monthly_projection_from_24h(pnl_24h: float | None) -> float | None:
    if pnl_24h is None:
        return None
    return pnl_24h * DAYS_PER_MONTH


def drawdown_adjust_projection(monthly_projection: float | None, max_drawdown_bps: float | None) -> float | None:
    if monthly_projection is None:
        return None
    drawdown_fraction = max(0.0, (max_drawdown_bps or 0.0) / 10_000.0)
    return monthly_projection * max(0.0, 1.0 - drawdown_fraction)


def costs_from_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    fees = sum_numbers(outcomes, "fees", "fee", "fees_usd", "fees_usdt")
    slippage = sum_numbers(outcomes, "slippage", "slippage_usd", "slippage_usdt")
    funding = sum_numbers(outcomes, "funding", "funding_usd", "funding_usdt")
    return {
        "fees_usdt": round(fees, 8),
        "slippage_usdt": round(slippage, 8),
        "funding_usdt": round(funding, 8),
        "total_costs_usdt": round(fees + slippage + funding, 8),
        "funding_source": "outcome_labels_when_present_else_zero",
    }


PERFORMANCE_OUTCOME_REQUIRED_FIELDS: tuple[str, ...] = (
    *REQUIRED_TRAINER_FEEDBACK_FIELDS,
)
PERFORMANCE_CONTEXT_FIELDS: tuple[str, ...] = (
    "liquidity_zone_context",
    "liquidation_distance_context",
    "microstructure_context",
)
MIN_QUALIFIED_PERFORMANCE_OUTCOMES = 30


def performance_sample_status(sample_count: int) -> str:
    if sample_count >= MIN_QUALIFIED_PERFORMANCE_OUTCOMES:
        return "QUALIFIED_CLEAN_PERFORMANCE_SAMPLE"
    if sample_count > 0:
        return "INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE"
    return "NO_CLEAN_PERFORMANCE_SAMPLE"


def qualified_performance_metric(value: float | None, sample_count: int) -> float | None:
    if sample_count < MIN_QUALIFIED_PERFORMANCE_OUTCOMES:
        return None
    return value


def is_performance_outcome_complete(row: Mapping[str, Any]) -> bool:
    if (
        row.get("winner") is None
        and finite_float(row.get("realized_pnl_usd")) is None
        and finite_float(row.get("realized_pnl_bps")) is None
    ):
        return False
    return all(row.get(field) not in (None, "") for field in PERFORMANCE_OUTCOME_REQUIRED_FIELDS)


def performance_outcome_rows(
    *,
    raw_outcomes: list[dict[str, Any]],
    trainer_feedback_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if trainer_feedback_rows:
        complete_feedback = [
            row for row in trainer_feedback_rows if is_performance_outcome_complete(row)
        ]
        context_missing_counts = {
            field: sum(1 for row in complete_feedback if row.get(field) in (None, ""))
            for field in PERFORMANCE_CONTEXT_FIELDS
        }
        return complete_feedback, {
            "performance_metric_source": "v2:trainer:feedback:outcomes",
            "raw_outcome_count": len(raw_outcomes),
            "trainer_feedback_row_count": len(trainer_feedback_rows),
            "performance_outcome_count": len(complete_feedback),
            "dirty_outcome_count": max(0, len(raw_outcomes) - len(complete_feedback)),
            "performance_outcome_required_fields": list(PERFORMANCE_OUTCOME_REQUIRED_FIELDS),
            "performance_context_fields": list(PERFORMANCE_CONTEXT_FIELDS),
            "performance_context_missing_field_counts": context_missing_counts,
        }
    complete_raw = [row for row in raw_outcomes if is_performance_outcome_complete(row)]
    context_missing_counts = {
        field: sum(1 for row in complete_raw if row.get(field) in (None, ""))
        for field in PERFORMANCE_CONTEXT_FIELDS
    }
    return complete_raw, {
        "performance_metric_source": "paper_outcomes_feedback_complete"
        if complete_raw
        else "INSUFFICIENT_CLEAN_TRAINER_FEEDBACK_OUTCOMES",
        "raw_outcome_count": len(raw_outcomes),
        "trainer_feedback_row_count": 0,
        "performance_outcome_count": len(complete_raw),
        "dirty_outcome_count": len(raw_outcomes) - len(complete_raw),
        "performance_outcome_required_fields": list(PERFORMANCE_OUTCOME_REQUIRED_FIELDS),
        "performance_context_fields": list(PERFORMANCE_CONTEXT_FIELDS),
        "performance_context_missing_field_counts": context_missing_counts,
    }


def classify_goal_status(
    *,
    live_available_margin: float | None,
    live_required_min_order_margin: float | None,
    outcome_count: int,
    monthly_projection: float | None,
    max_drawdown_bps: float | None,
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if live_available_margin is None or live_available_margin <= 0 or (
        live_required_min_order_margin is not None and live_available_margin < live_required_min_order_margin
    ):
        blockers.append("capital shortfall: live target is not executable because available margin is below minimum order margin")
        return "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL", blockers
    if outcome_count < 30:
        blockers.append("insufficient outcomes: fewer than 30 closed-trade labels")
        return "INSUFFICIENT_SAMPLE_FOR_10K_TARGET", blockers
    if max_drawdown_bps is not None and max_drawdown_bps >= 500:
        blockers.append("drawdown too high for target feasibility")
        return "RISK_TOO_HIGH_FOR_10K_TARGET", blockers
    if monthly_projection is not None and monthly_projection >= MONTHLY_TARGET_NET_USDT:
        return "ON_TRACK_FOR_10K_MONTHLY_PAPER", blockers
    blockers.append("edge shortfall: paper monthly run-rate is below 10k net target")
    return "NOT_ON_TRACK_FOR_10K_MONTHLY_PAPER", blockers


def capital_required_for_target(target: float, monthly_projection: float | None, equity: float | None) -> float | None:
    if equity is None or equity <= 0 or monthly_projection is None or monthly_projection <= 0:
        return None
    monthly_return_fraction = monthly_projection / equity
    if monthly_return_fraction <= 0:
        return None
    return target / monthly_return_fraction


def build_monthly_profit_target_feasibility_status(
    *,
    generated_est: str,
    generated_utc: str,
    portfolio: Mapping[str, Any],
    live_gate: Mapping[str, Any],
    predictions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    performance_evidence: Mapping[str, Any] | None = None,
    observation_window_start_utc: str | None = None,
) -> dict[str, Any]:
    performance_evidence = dict(performance_evidence or {})
    now_dt = parse_time(generated_utc) or datetime.now(timezone.utc)
    paper_equity = finite_float(portfolio.get("equity"))
    paper_equity_source = str(portfolio.get("_portfolio_source") or "operator_runtime:v2_portfolio_state")
    session_pnl = finite_float(portfolio.get("total_pnl_usd"))
    pnl_24h = paper_24h_pnl(
        observations,
        portfolio,
        now_dt,
        start_utc=observation_window_start_utc,
    )
    monthly_projection = monthly_projection_from_24h(pnl_24h)
    monthly_return_pct = None if paper_equity in (None, 0.0) or monthly_projection is None else monthly_projection / paper_equity
    drawdown_evidence = drawdown_from_observations(
        observations,
        fallback_bps=finite_float(portfolio.get("current_drawdown_bps")),
        start_utc=observation_window_start_utc,
    )
    max_drawdown = finite_float(drawdown_evidence.get("max_drawdown_bps"))
    drawdown_adjusted = drawdown_adjust_projection(monthly_projection, max_drawdown)
    live_margin = finite_float(live_gate.get("available_margin"))
    wallet = finite_float(live_gate.get("wallet_balance"))
    required_margin = finite_float(live_gate.get("required_initial_margin"))
    edge = current_edge_after_cost_bps(predictions)
    current_pf = profit_factor(outcomes)
    current_wr = win_rate(outcomes)
    performance_sample_count = len(outcomes)
    sample_status = performance_sample_status(performance_sample_count)
    current_pf_qualified = qualified_performance_metric(current_pf, performance_sample_count)
    current_wr_qualified = qualified_performance_metric(current_wr, performance_sample_count)
    costs = costs_from_outcomes(outcomes)
    goal_status, blockers = classify_goal_status(
        live_available_margin=live_margin,
        live_required_min_order_margin=required_margin,
        outcome_count=len(outcomes),
        monthly_projection=drawdown_adjusted,
        max_drawdown_bps=max_drawdown,
    )
    required_capital = capital_required_for_target(MONTHLY_TARGET_NET_USDT, drawdown_adjusted, paper_equity)
    return {
        "schema_version": "monthly_profit_target_feasibility_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "monthly_target_net_usdt": MONTHLY_TARGET_NET_USDT,
        "daily_target_net_usdt": round(MONTHLY_TARGET_NET_USDT / DAYS_PER_MONTH, 8),
        "hourly_target_net_usdt": round(MONTHLY_TARGET_NET_USDT / HOURS_PER_MONTH, 8),
        "paper_equity": paper_equity,
        "paper_equity_source": paper_equity_source,
        "paper_current_session_pnl": session_pnl,
        "paper_24h_pnl": pnl_24h,
        "paper_run_rate_monthly_pnl": monthly_projection,
        "paper_run_rate_monthly_return_pct": monthly_return_pct,
        "required_monthly_return_pct": required_return_pct(MONTHLY_TARGET_NET_USDT, paper_equity),
        "target_return_warning": "10000/month requires aggressive return; feasibility must be proven by evidence"
        if paper_equity and required_return_pct(MONTHLY_TARGET_NET_USDT, paper_equity) and required_return_pct(MONTHLY_TARGET_NET_USDT, paper_equity) >= 1.0
        else None,
        "live_available_margin": live_margin,
        "live_wallet_balance": wallet,
        "live_required_min_order_margin": required_margin,
        "live_target_executable": bool(live_margin is not None and required_margin is not None and live_margin >= required_margin),
        "capital_required_for_target_at_current_edge": required_capital,
        "current_edge_after_cost_bps": edge,
        "current_win_rate": current_wr,
        "current_win_rate_qualified": current_wr_qualified,
        "current_profit_factor": current_pf,
        "current_profit_factor_qualified": current_pf_qualified,
        "max_drawdown": max_drawdown,
        "max_drawdown_bps": max_drawdown,
        "drawdown_source": drawdown_evidence.get("drawdown_source"),
        "drawdown_observation_count": drawdown_evidence.get("drawdown_observation_count"),
        "drawdown_equity_point_count": drawdown_evidence.get("drawdown_equity_point_count"),
        "drawdown_window_start_utc": drawdown_evidence.get("drawdown_window_start_utc"),
        "drawdown_adjusted_monthly_projection": drawdown_adjusted,
        "fees_slippage_funding_costs": costs,
        "performance_metric_source": performance_evidence.get("performance_metric_source"),
        "raw_outcome_count": performance_evidence.get("raw_outcome_count", len(outcomes)),
        "performance_outcome_count": performance_evidence.get("performance_outcome_count", len(outcomes)),
        "dirty_outcome_count": performance_evidence.get("dirty_outcome_count", 0),
        "performance_sample_status": sample_status,
        "minimum_qualified_performance_outcomes": MIN_QUALIFIED_PERFORMANCE_OUTCOMES,
        "performance_outcome_required_fields": performance_evidence.get(
            "performance_outcome_required_fields",
            list(PERFORMANCE_OUTCOME_REQUIRED_FIELDS),
        ),
        "performance_context_fields": performance_evidence.get(
            "performance_context_fields",
            list(PERFORMANCE_CONTEXT_FIELDS),
        ),
        "performance_context_missing_field_counts": performance_evidence.get(
            "performance_context_missing_field_counts",
            {},
        ),
        "goal_status": goal_status,
        "goal_blockers": blockers,
        "profit_claim_policy": "NO_GUARANTEE_EVIDENCE_REQUIRED",
    }


def build_trainer_profit_goal_capability_status(
    *,
    generated_est: str,
    trainer: Mapping[str, Any],
    predictions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    now_utc: datetime,
    prediction_payload: Mapping[str, Any] | None = None,
    redis_prediction_timeframes: Mapping[str, Any] | None = None,
    redis_stale_prediction_timeframes: Mapping[str, Any] | None = None,
    redis_unknown_time_prediction_timeframes: Mapping[str, Any] | None = None,
    missing_prediction_input_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    prediction_payload = dict(prediction_payload or {})
    redis_prediction_timeframes = dict(redis_prediction_timeframes or {})
    redis_stale_prediction_timeframes = dict(redis_stale_prediction_timeframes or {})
    redis_unknown_time_prediction_timeframes = dict(redis_unknown_time_prediction_timeframes or {})
    missing_prediction_input_diagnostics = dict(missing_prediction_input_diagnostics or {})
    last_hour_outcomes = rows_since(outcomes, now_utc=now_utc, seconds=3600, time_keys=("exit_time", "closed_utc", "generated_utc"))
    last_hour_feedback = rows_since(feedback_rows, now_utc=now_utc, seconds=3600, time_keys=("exit_time", "closed_utc", "generated_utc"))
    last_hour_closed = rows_since(closed_trades, now_utc=now_utc, seconds=3600, time_keys=("exit_time", "closed_utc", "generated_utc"))
    prediction_rows = int(finite_float(trainer.get("prediction_grid_rows")) or len(predictions))
    blocked_rows = int(finite_float(trainer.get("blocked_prediction_rows")) or 0)
    missing_prediction_rows = int(
        finite_float(prediction_payload.get("missing_prediction_rows_count"))
        or finite_float(prediction_payload.get("non_current_prediction_rows_count"))
        or blocked_rows
    )
    stale_prediction_rows = int(finite_float(prediction_payload.get("stale_prediction_rows_count")) or 0)
    missing_symbols = [
        str(symbol)
        for symbol in as_list(prediction_payload.get("missing_prediction_symbols"))
        if symbol not in (None, "")
    ]
    stale_symbols = [
        str(symbol)
        for symbol in as_list(prediction_payload.get("stale_prediction_symbols"))
        if symbol not in (None, "")
    ]
    missing_timeframes_by_symbol = {
        str(symbol): [str(tf) for tf in as_list(timeframes) if tf not in (None, "")]
        for symbol, timeframes in as_dict(prediction_payload.get("missing_prediction_timeframes_by_symbol")).items()
    }
    stale_timeframes_by_symbol = {
        str(symbol): [str(tf) for tf in as_list(timeframes) if tf not in (None, "")]
        for symbol, timeframes in as_dict(prediction_payload.get("stale_prediction_timeframes_by_symbol")).items()
    }
    paper_block_reasons = {
        str(reason): int(finite_float(count) or 0)
        for reason, count in as_dict(prediction_payload.get("paper_actionability_block_reason_counts")).items()
    }
    expected_symbols = sorted(str(symbol).upper() for symbol in as_list(prediction_payload.get("symbols_covered")) if symbol)
    redis_symbols = sorted(str(symbol).upper() for symbol in redis_prediction_timeframes if symbol)
    stale_redis_symbols = sorted(str(symbol).upper() for symbol in redis_stale_prediction_timeframes if symbol)
    unknown_time_redis_symbols = sorted(str(symbol).upper() for symbol in redis_unknown_time_prediction_timeframes if symbol)
    expected_symbol_set = set(expected_symbols)
    redis_symbol_set = set(redis_symbols)
    expected_missing_from_redis = sorted(expected_symbol_set - redis_symbol_set)
    redis_extra_vs_expected = sorted(redis_symbol_set - expected_symbol_set)
    extra_timeframes_by_symbol = {
        symbol: [str(tf) for tf in as_list(redis_prediction_timeframes.get(symbol)) if tf not in (None, "")]
        for symbol in redis_extra_vs_expected
    }
    if expected_missing_from_redis:
        symbol_universe_status = "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_MISMATCH"
    elif redis_extra_vs_expected:
        symbol_universe_status = "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_ALIGNED_WITH_RECENT_REDIS_RESIDUE"
    else:
        symbol_universe_status = "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_ALIGNED"
    training_steps_last_hour = int(finite_float(trainer.get("training_steps_last_hour")) or 0)
    bottleneck = str(trainer.get("resource_bottleneck_reason") or "")
    cal_error = calibration_error(predictions, outcomes)
    edge = current_edge_after_cost_bps(predictions)
    loop_active = bool(trainer.get("training_loop_active") or trainer.get("continuous_training_enabled"))
    if "DATASET_TOO_SMALL" in bottleneck:
        status = "TRAINER_DATASET_TOO_SMALL"
    elif not loop_active or training_steps_last_hour <= 0:
        status = "TRAINER_NOT_TRAINING_FAST_ENOUGH"
    elif not last_hour_outcomes or not last_hour_feedback:
        status = "TRAINER_ACTIVE_BUT_INSUFFICIENT_FEEDBACK"
    elif edge is None or edge <= 0:
        status = "TRAINER_ACTIVE_BUT_LOW_EDGE"
    elif cal_error is not None and cal_error > 0.25:
        status = "TRAINER_ACTIVE_BUT_CALIBRATION_WEAK"
    else:
        status = "TRAINER_CAPABLE_AND_LEARNING"
    return {
        "schema_version": "trainer_profit_goal_capability_status_v1",
        "generated_est": generated_est,
        "trainer_source": trainer.get("trainer_source"),
        "cuda_active": bool(trainer.get("cuda_active")),
        "training_loop_active": loop_active,
        "training_steps_total": int(finite_float(trainer.get("training_steps_total")) or 0),
        "training_steps_last_hour": training_steps_last_hour,
        "samples_seen_last_hour": finite_float(trainer.get("samples_per_second")),
        "outcome_labels_last_hour": len(last_hour_outcomes),
        "trainer_feedback_rows_last_hour": len(last_hour_feedback),
        "closed_trades_last_hour": len(last_hour_closed),
        "prediction_grid_current": prediction_rows > 0,
        "prediction_grid_rows": prediction_rows,
        "blocked_prediction_rows": blocked_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "missing_prediction_symbols": missing_symbols,
        "missing_prediction_symbol_count": len(missing_symbols),
        "missing_prediction_timeframes_by_symbol": missing_timeframes_by_symbol,
        "stale_prediction_rows_count": stale_prediction_rows,
        "stale_prediction_symbols": stale_symbols,
        "stale_prediction_symbol_count": len(stale_symbols),
        "stale_prediction_timeframes_by_symbol": stale_timeframes_by_symbol,
        "paper_actionability_allowed_rows_count": int(
            finite_float(prediction_payload.get("paper_actionability_allowed_rows_count")) or 0
        ),
        "paper_actionability_blocked_rows_count": int(
            finite_float(prediction_payload.get("paper_actionability_blocked_rows_count")) or 0
        ),
        "paper_actionability_block_reason_counts": paper_block_reasons,
        "trainer_prediction_redis_symbol_count": len(redis_symbols),
        "trainer_stale_prediction_redis_symbol_count": len(stale_redis_symbols),
        "trainer_unknown_time_prediction_redis_symbol_count": len(unknown_time_redis_symbols),
        "publisher_expected_symbol_count": len(expected_symbols),
        "trainer_expected_symbol_mismatch_count": len(expected_missing_from_redis),
        "trainer_recent_redis_residue_symbol_count": len(redis_extra_vs_expected),
        "trainer_recent_redis_residue_symbols": redis_extra_vs_expected,
        "trainer_expected_missing_from_redis_symbols": expected_missing_from_redis,
        "trainer_redis_extra_prediction_symbols": redis_extra_vs_expected,
        "trainer_redis_extra_prediction_timeframes_by_symbol": extra_timeframes_by_symbol,
        "trainer_stale_redis_prediction_symbols": stale_redis_symbols,
        "trainer_stale_redis_prediction_timeframes_by_symbol": {
            symbol: [str(tf) for tf in as_list(redis_stale_prediction_timeframes.get(symbol)) if tf not in (None, "")]
            for symbol in stale_redis_symbols
        },
        "trainer_unknown_time_redis_prediction_symbols": unknown_time_redis_symbols,
        "trainer_unknown_time_redis_prediction_timeframes_by_symbol": {
            symbol: [
                str(tf)
                for tf in as_list(redis_unknown_time_prediction_timeframes.get(symbol))
                if tf not in (None, "")
            ]
            for symbol in unknown_time_redis_symbols
        },
        "missing_prediction_input_reason_counts": as_dict(
            missing_prediction_input_diagnostics.get("missing_prediction_input_reason_counts")
        ),
        "missing_prediction_input_diagnostics_by_symbol": as_dict(
            missing_prediction_input_diagnostics.get("missing_prediction_input_diagnostics_by_symbol")
        ),
        "trainer_symbol_universe_alignment_status": symbol_universe_status,
        "confidence_distribution": confidence_distribution(predictions),
        "expected_move_distribution": expected_move_distribution(predictions),
        "calibration_error": cal_error,
        "loss_trend": {
            "loss_before": as_dict(as_dict(trainer.get("metrics")).get("training")).get("loss_before"),
            "loss_after": as_dict(as_dict(trainer.get("metrics")).get("training")).get("loss_after"),
        },
        "paper_pnl_by_checkpoint": {
            str(trainer.get("checkpoint_id") or "checkpoint_pending"): finite_float(trainer.get("paper_current_session_pnl")),
        },
        "checkpoint_id": trainer.get("checkpoint_id"),
        "checkpoint_age_seconds": trainer.get("checkpoint_age_seconds"),
        "bottleneck_reason": bottleneck or None,
        "trainer_capability_status": status,
    }


def family_from_mode(mode: str) -> str:
    mapping = {
        "trend_mode": "trend_following",
        "mean_reversion_mode": "mean_reversion",
        "breakout_mode": "breakout",
        "scalp_mode": "momentum",
        "reduce_size_mode": "volatility_regime",
        "no_trade_mode": "no_trade_preservation",
    }
    return mapping.get(mode, "no_trade_preservation")


def family_from_outcome(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("strategy_family") or "").strip()
    if explicit:
        return explicit
    reason = str(row.get("close_reason") or row.get("exit_reason") or "").upper()
    if "TRAIL" in reason or "STOP" in reason:
        return "volatility_regime"
    if "TAKE_PROFIT" in reason:
        return "momentum"
    if "REVERSAL" in reason:
        return "mean_reversion"
    return "no_trade_preservation"


def strategy_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[family_from_outcome(row)].append(row)
    stats: dict[str, dict[str, Any]] = {}
    for family, items in grouped.items():
        pnl_values = [value for item in items if (value := finite_float(item.get("realized_pnl_usd"))) is not None]
        bps_values = [value for item in items if (value := finite_float(item.get("realized_pnl_bps"))) is not None]
        stats[family] = {
            "closed_trades": len(items),
            "win_rate": win_rate(items),
            "avg_realized_pnl_bps": statistics.fmean(bps_values) if bps_values else None,
            "expectancy_after_cost_bps": statistics.fmean(bps_values) if bps_values else None,
            "profit_factor": profit_factor(items),
            "max_drawdown": min(pnl_values) if pnl_values else None,
        }
    return stats


def build_adaptive_strategy_selection_status(
    *,
    generated_est: str,
    trade_management: Mapping[str, Any],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    router_report = as_dict(trade_management.get("strategy_router_report"))
    mode_counts = as_dict(trade_management.get("strategy_router_mode_counts") or router_report.get("mode_counts"))
    regime_counts = as_dict(trade_management.get("strategy_router_regime_counts") or router_report.get("regime_counts"))
    accepted_total = int(finite_float(trade_management.get("intents_accepted")) or 0)
    blocked_total = int(finite_float(trade_management.get("intents_blocked")) or 0)
    outcome_stats = strategy_stats(outcomes)
    sample_counts = Counter()
    for mode, count in mode_counts.items():
        sample_counts[family_from_mode(str(mode))] += int(finite_float(count) or 0)
    total_samples = sum(sample_counts.values())
    rows: list[dict[str, Any]] = []
    for family in STRATEGY_FAMILIES:
        stats = outcome_stats.get(family, {})
        sample_count = int(sample_counts.get(family, 0))
        expectancy = finite_float(stats.get("expectancy_after_cost_bps"))
        positive = max(0.0, expectancy or 0.0)
        rows.append(
            {
                "strategy_id": f"strategy_{family}",
                "strategy_family": family,
                "enabled_for_paper": True,
                "current_market_regime": ",".join(sorted(regime_counts.keys())) if regime_counts else "REGIME_EVIDENCE_PENDING",
                "sample_count": sample_count,
                "accepted_signals": accepted_total if family != "no_trade_preservation" and sample_count else 0,
                "blocked_signals": blocked_total if family == "no_trade_preservation" else 0,
                "closed_trades": stats.get("closed_trades", 0),
                "win_rate": stats.get("win_rate"),
                "avg_realized_pnl_bps": stats.get("avg_realized_pnl_bps"),
                "expectancy_after_cost_bps": expectancy,
                "profit_factor": stats.get("profit_factor"),
                "max_drawdown": stats.get("max_drawdown"),
                "current_weight": None,
                "weight_change_reason": "computed from observed router mode counts and closed-trade expectancy",
                "trainer_feedback_effect": "feedback tagged" if family in outcome_stats else "pending strategy-tagged outcomes",
                "_positive_expectancy": positive,
            }
        )
    weight_base = sum(float(row["_positive_expectancy"]) * max(1, int(row["closed_trades"] or 0)) for row in rows)
    fallback_sample_base = max(1, total_samples)
    for row in rows:
        if weight_base > 0:
            row["current_weight"] = round(float(row["_positive_expectancy"]) * max(1, int(row["closed_trades"] or 0)) / weight_base, 8)
        else:
            row["current_weight"] = round(int(row["sample_count"] or 0) / fallback_sample_base, 8)
        del row["_positive_expectancy"]
    static_strategy_assignment_used = False
    dynamic_inputs = [
        "regime",
        "confidence",
        "expected_move",
        "liquidity",
        "volatility",
        "funding_oi",
        "liquidation_pressure",
        "orderbook_imbalance",
        "recent_realized_outcomes",
        "drawdown",
    ]
    status = (
        "DYNAMIC_STRATEGY_SELECTION_MONITORED"
        if not static_strategy_assignment_used
        else "STATIC_STRATEGY_SELECTION_DETECTED"
    )
    return {
        "schema_version": "adaptive_strategy_selection_status_v1",
        "generated_est": generated_est,
        "status": status,
        "strategy_selection_status": status,
        "adaptive_strategy_selection_status": status,
        "strategy_selection_policy": "evidence_weighted_monitor_only_runtime_router_unchanged",
        "strategy_router_mode_counts": dict(mode_counts),
        "strategy_router_regime_counts": dict(regime_counts),
        "families": rows,
        "strategies": rows,
        "strategy_families": list(STRATEGY_FAMILIES),
        "strategy_family_count": len(STRATEGY_FAMILIES),
        "dynamic_selection_inputs": dynamic_inputs,
        "dynamic_strategy_inputs": dynamic_inputs,
        "dynamic_selection_factors": dynamic_inputs,
        "not_allowed_static_behavior": [
            "hard_code_strategy_trend",
            "hard_code_hedge_always_on",
            "hard_code_fixed_allocation_per_strategy",
        ],
        "static_strategy_assignment_used": static_strategy_assignment_used,
    }


def build_adaptive_hedging_capability_status(
    *,
    generated_est: str,
    hedge_status: Mapping[str, Any],
    outcomes: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    position_source: str = "input_positions",
) -> dict[str, Any]:
    accidental_symbols = []
    sides_by_symbol: defaultdict[str, set[str]] = defaultdict(set)
    active_positions = []
    noncanonical_ignored = 0
    for row in positions:
        if not is_canonical_position_row(row):
            noncanonical_ignored += 1
            continue
        state = str(row.get("position_state") or row.get("status") or "").upper()
        qty = finite_float(row.get("net_quantity") if row.get("net_quantity") is not None else row.get("quantity"))
        if row.get("open_position") is False:
            continue
        if state and "CLOSED" in state:
            continue
        if qty is not None and abs(qty) <= 1e-12:
            continue
        active_positions.append(row)
    for row in active_positions:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        side = str(row.get("side") or "").lower()
        if side:
            sides_by_symbol[symbol].add(side)
    accidental_symbols = sorted(symbol for symbol, sides in sides_by_symbol.items() if len(sides) > 1)
    hedge_rows = [
        row
        for row in outcomes
        if str(row.get("hedge_state") or "").upper() not in {"", "NO_HEDGE"}
        or str(row.get("strategy_family") or "") == "hedged_protection"
    ]
    hedge_cost = sum_numbers(hedge_rows, "fees", "slippage", "hedge_cost")
    hedge_net = sum_numbers(hedge_rows, "realized_pnl_usd", "hedge_net_pnl")
    accidental_count = len(accidental_symbols)
    risk_disabled = bool(hedge_status.get("accidental_hedge_pairs_allowed")) is False and not hedge_rows
    if accidental_count:
        status = "ACCIDENTAL_HEDGE_DETECTED_BLOCKED"
    elif risk_disabled:
        status = "HEDGING_BLOCKED_NO_VALID_HEDGE_CONTEXT"
    elif hedge_rows and hedge_net <= hedge_cost:
        status = "HEDGING_ACTIVE_BUT_NOT_PROVEN_PROFITABLE"
    else:
        status = "HEDGING_READY_ADAPTIVE"
    return {
        "schema_version": "adaptive_hedging_capability_status_v1",
        "generated_est": generated_est,
        "status": status,
        "adaptive_hedging_capability_status": status,
        "hedge_intent_count": len(hedge_rows),
        "hedge_approved_count": sum(1 for row in hedge_rows if row.get("hedge_state") == "HEDGE_APPROVED"),
        "hedge_blocked_count": sum(1 for row in hedge_rows if "BLOCK" in str(row.get("hedge_state") or "")),
        "hedge_open_count": 0,
        "position_source": position_source,
        "open_position_count_checked_for_accidental_hedge": len(active_positions),
        "noncanonical_position_rows_ignored_count": noncanonical_ignored,
        "hedge_closed_count": len(hedge_rows),
        "hedge_net_pnl": hedge_net,
        "hedge_cost": hedge_cost,
        "hedge_benefit": hedge_net - hedge_cost,
        "symbols_hedged": sorted({str(row.get("symbol")) for row in hedge_rows if row.get("symbol")}),
        "hedge_reasons": dict(Counter(str(row.get("hedge_reason") or "NO_HEDGE") for row in hedge_rows)),
        "unhedge_reasons": dict(Counter(str(row.get("exit_reason") or row.get("close_reason") or "NO_HEDGE_EXIT") for row in hedge_rows)),
        "accidental_hedge_count": accidental_count,
        "accidental_hedge_symbols": accidental_symbols,
        "same_symbol_opposite_exposure_requires_explicit_hedge_tag": True,
        "hedge_requires_budget_risk_approval_and_exit": True,
        "static_always_on_hedge_used": False,
        "hedge_status": status,
        "hedging_status": status,
    }


def build_trainer_strategy_hedge_feedback_status(
    *,
    generated_est: str,
    outcomes: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    feedback_quarantine_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    feedback_quarantine_rows = feedback_quarantine_rows or []
    source = [*feedback_rows, *feedback_quarantine_rows] if (feedback_rows or feedback_quarantine_rows) else outcomes
    consumable_missing_counts = {
        field: sum(1 for row in feedback_rows if row.get(field) in (None, ""))
        for field in REQUIRED_TRAINER_FEEDBACK_FIELDS
    }
    quarantine_missing_counts = {
        field: sum(1 for row in feedback_quarantine_rows if row.get(field) in (None, ""))
        for field in REQUIRED_TRAINER_FEEDBACK_FIELDS
    }
    outcome_missing_counts = {
        field: sum(1 for row in outcomes if row.get(field) in (None, ""))
        for field in REQUIRED_TRAINER_FEEDBACK_FIELDS
    }
    missing_counts = {
        field: sum(1 for row in source if row.get(field) in (None, ""))
        for field in REQUIRED_TRAINER_FEEDBACK_FIELDS
    }
    complete_rows = [
        row
        for row in source
        if all(row.get(field) not in (None, "") for field in REQUIRED_TRAINER_FEEDBACK_FIELDS)
    ]
    rows_with_strategy_fields = sum(
        1
        for row in source
        if row.get("strategy_id") not in (None, "") and row.get("strategy_family") not in (None, "")
    )
    rows_with_hedge_fields = sum(
        1
        for row in source
        if row.get("hedge_state") not in (None, "") and row.get("hedge_reason") not in (None, "")
    )
    missing_strategy_feedback_count = len(source) - rows_with_strategy_fields
    missing_hedge_feedback_count = len(source) - rows_with_hedge_fields
    consumable_complete_rows = [
        row
        for row in feedback_rows
        if all(row.get(field) not in (None, "") for field in REQUIRED_TRAINER_FEEDBACK_FIELDS)
    ]
    feedback_status = (
        "COMPLETE_STRATEGY_HEDGE_FEEDBACK"
        if feedback_rows and not feedback_quarantine_rows and len(complete_rows) == len(feedback_rows)
        else "COMPLETE_FEEDBACK_AVAILABLE_WITH_QUARANTINE"
        if feedback_rows and len(consumable_complete_rows) == len(feedback_rows)
        else "MISSING_STRATEGY_HEDGE_FEEDBACK_FIELDS"
    )
    readiness_summary = (
        f"{len(complete_rows)} complete strategy/hedge feedback rows; "
        f"{len(feedback_quarantine_rows)} quarantined rows; "
        f"{sum(1 for value in quarantine_missing_counts.values() if value)} quarantined required fields have missing values; "
        f"{sum(1 for value in consumable_missing_counts.values() if value)} consumable required fields have missing values."
    )
    return {
        "schema_version": "trainer_strategy_hedge_feedback_status_v1",
        "generated_est": generated_est,
        "status": feedback_status,
        "outcome_label_count": len(outcomes),
        "trainer_feedback_row_count": len(feedback_rows),
        "trainer_feedback_consumable_row_count": len(feedback_rows),
        "trainer_feedback_quarantined_row_count": len(feedback_quarantine_rows),
        "trainer_feedback_total_row_count": len(feedback_rows) + len(feedback_quarantine_rows),
        "required_fields": list(REQUIRED_TRAINER_FEEDBACK_FIELDS),
        "missing_field_counts": missing_counts,
        "consumable_missing_field_counts": consumable_missing_counts,
        "quarantine_missing_field_counts": quarantine_missing_counts,
        "outcome_missing_field_counts": outcome_missing_counts,
        "feedback_rows_with_strategy_fields": rows_with_strategy_fields,
        "feedback_rows_with_hedge_fields": rows_with_hedge_fields,
        "missing_strategy_feedback_count": missing_strategy_feedback_count,
        "missing_hedge_feedback_count": missing_hedge_feedback_count,
        "complete_strategy_hedge_feedback_rows": len(complete_rows),
        "trainer_consumes_closed_trade_outcomes": bool(feedback_rows),
        "trainer_closed_trade_outcome_evidence_present": bool(outcomes),
        "trainer_feedback_quarantine_active": bool(feedback_quarantine_rows),
        "feedback_status": feedback_status,
        "readiness_summary": readiness_summary,
    }


def _field_count_map(value: Any) -> dict[str, int]:
    if isinstance(value, Mapping):
        return {
            str(field): int(finite_float(count) or 0)
            for field, count in value.items()
        }
    counts: dict[str, int] = {}
    for row in as_list(value):
        if not isinstance(row, Mapping):
            continue
        field = row.get("field")
        if field in (None, ""):
            continue
        counts[str(field)] = int(finite_float(row.get("count")) or 0)
    return counts


def aggregate_feedback_evidence_from_soak(soak_status: Mapping[str, Any]) -> dict[str, Any]:
    nested = as_dict(soak_status.get("trainer_feedback_alpha_status"))
    complete = int(
        finite_float(nested.get("current_complete_strategy_hedge_feedback_rows"))
        or finite_float(soak_status.get("trainer_feedback_complete_row_count"))
        or finite_float(nested.get("trainer_consumable_rows"))
        or 0
    )
    quarantined = int(
        finite_float(nested.get("current_quarantined_incomplete_feedback_rows"))
        or finite_float(soak_status.get("trainer_feedback_quarantined_row_count"))
        or finite_float(nested.get("trainer_feedback_quarantined_rows"))
        or 0
    )
    total = int(
        finite_float(nested.get("current_trainer_feedback_total_rows"))
        or finite_float(soak_status.get("trainer_feedback_total_row_count"))
        or complete + quarantined
    )
    if complete <= 0 and total <= 0:
        return {}
    missing_counts = _field_count_map(
        nested.get("current_missing_field_counts")
        or nested.get("current_missing_feedback_field_counts")
        or soak_status.get("trainer_feedback_missing_field_counts")
    )
    return {
        "complete_rows": complete,
        "quarantined_rows": quarantined,
        "total_rows": total,
        "missing_field_counts": missing_counts,
        "readiness_status": str(
            nested.get("current_feedback_readiness_status")
            or soak_status.get("trainer_feedback_readiness_status")
            or ""
        ),
        "readiness_summary": str(
            nested.get("current_feedback_readiness_summary")
            or soak_status.get("trainer_feedback_readiness_summary")
            or ""
        ),
        "source": str(nested.get("current_feedback_source") or "remediated_soak_feedback_aggregate"),
    }


def merge_feedback_aggregate_evidence(
    feedback_status: Mapping[str, Any],
    aggregate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(feedback_status)
    complete = int(finite_float(aggregate_evidence.get("complete_rows")) or 0)
    total = int(finite_float(aggregate_evidence.get("total_rows")) or 0)
    if complete <= 0 or total <= 0:
        merged["feedback_aggregate_evidence_used"] = False
        return merged
    current_total = int(finite_float(merged.get("trainer_feedback_total_row_count")) or 0)
    if current_total >= total:
        merged["feedback_aggregate_evidence_used"] = False
        return merged
    quarantined = int(finite_float(aggregate_evidence.get("quarantined_rows")) or max(0, total - complete))
    missing_counts = {
        field: int(finite_float(count) or 0)
        for field, count in as_dict(aggregate_evidence.get("missing_field_counts")).items()
    }
    rows_with_strategy = max(
        0,
        total
        - max(
            int(missing_counts.get("strategy_id", 0)),
            int(missing_counts.get("strategy_family", 0)),
        ),
    )
    rows_with_hedge = max(
        0,
        total
        - max(
            int(missing_counts.get("hedge_state", 0)),
            int(missing_counts.get("hedge_reason", 0)),
        ),
    )
    status = (
        "COMPLETE_FEEDBACK_AVAILABLE_FROM_SOAK_EVIDENCE"
        if complete > 0
        else str(merged.get("feedback_status") or merged.get("status") or "MISSING_STRATEGY_HEDGE_FEEDBACK_FIELDS")
    )
    merged.update(
        {
            "status": status,
            "feedback_status": status,
            "trainer_feedback_row_count": complete,
            "trainer_feedback_consumable_row_count": complete,
            "trainer_feedback_quarantined_row_count": quarantined,
            "trainer_feedback_total_row_count": total,
            "missing_field_counts": missing_counts,
            "consumable_missing_field_counts": {
                field: 0 for field in REQUIRED_TRAINER_FEEDBACK_FIELDS
            },
            "quarantine_missing_field_counts": missing_counts,
            "feedback_rows_with_strategy_fields": rows_with_strategy,
            "feedback_rows_with_hedge_fields": rows_with_hedge,
            "missing_strategy_feedback_count": max(0, total - rows_with_strategy),
            "missing_hedge_feedback_count": max(0, total - rows_with_hedge),
            "complete_strategy_hedge_feedback_rows": complete,
            "trainer_consumes_closed_trade_outcomes": True,
            "trainer_closed_trade_outcome_evidence_present": True,
            "trainer_feedback_quarantine_active": quarantined > 0,
            "feedback_aggregate_evidence_used": True,
            "feedback_aggregate_evidence_source": aggregate_evidence.get("source"),
            "performance_rows_materialized_for_metrics": False,
            "readiness_summary": aggregate_evidence.get("readiness_summary")
            or f"{complete}/{complete} trainer feedback rows are complete and consumable.",
        }
    )
    return merged


def build_monthly_10k_goal_simulation_status(
    *,
    generated_est: str,
    feasibility: Mapping[str, Any],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    monthly = finite_float(feasibility.get("drawdown_adjusted_monthly_projection"))
    equity = finite_float(feasibility.get("paper_equity"))
    target = finite_float(feasibility.get("monthly_target_net_usdt")) or MONTHLY_TARGET_NET_USDT
    pf = profit_factor(outcomes)
    wr = win_rate(outcomes)
    sample_count = len(outcomes)
    sample_status = performance_sample_status(sample_count)
    pf_qualified = qualified_performance_metric(pf, sample_count)
    wr_qualified = qualified_performance_metric(wr, sample_count)
    avg_trade = avg_numbers(outcomes, "realized_pnl_usd")
    expected_trade_count = len(outcomes) * DAYS_PER_MONTH if outcomes else None
    required_trade_count = None if avg_trade is None or avg_trade <= 0 else target / avg_trade
    capital_required = finite_float(feasibility.get("capital_required_for_target_at_current_edge"))
    monthly_return = None if equity in (None, 0.0) or monthly is None else monthly / equity
    risk_required = None if equity in (None, 0.0) else target / equity
    if len(outcomes) < 30:
        status = "INSUFFICIENT_EVIDENCE"
    elif monthly is not None and monthly >= target:
        status = "GOAL_PLAUSIBLE_WITH_CURRENT_CAPITAL_AND_RISK"
    elif capital_required is not None and capital_required > (equity or 0):
        status = "GOAL_REQUIRES_MORE_CAPITAL"
    elif risk_required is not None and risk_required >= 1.0:
        status = "GOAL_REQUIRES_UNACCEPTABLE_RISK"
    else:
        status = "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE"
    return {
        "schema_version": "monthly_10k_goal_simulation_status_v1",
        "generated_est": generated_est,
        "status": status,
        "goal_status": status,
        "simulation_mode": "paper_observed_run_rate_projection_no_live_execution",
        "simulated_monthly_net_pnl": monthly,
        "simulated_monthly_return_pct": monthly_return,
        "confidence_interval_lower": None if monthly is None else monthly * 0.5,
        "confidence_interval_upper": None if monthly is None else monthly * 1.5,
        "max_drawdown": feasibility.get("max_drawdown"),
        "profit_factor": pf,
        "profit_factor_qualified": pf_qualified,
        "win_rate": wr,
        "win_rate_qualified": wr_qualified,
        "performance_sample_status": sample_status,
        "performance_outcome_count": sample_count,
        "minimum_qualified_performance_outcomes": MIN_QUALIFIED_PERFORMANCE_OUTCOMES,
        "average_trade_pnl": avg_trade,
        "expected_trade_count_per_month": expected_trade_count,
        "required_trade_count_for_10k": required_trade_count,
        "capital_required_for_10k_at_current_edge": capital_required,
        "risk_required_for_10k": risk_required,
        "risk_acceptable": bool(risk_required is not None and risk_required < 1.0),
        "goal_simulation_status": status,
    }


def _position_notional_usdt(row: Mapping[str, Any]) -> float:
    notional = finite_float(row.get("notional_usdt") or row.get("notional") or row.get("gross_notional"))
    if notional is not None:
        return abs(notional)
    qty = finite_float(row.get("net_quantity") if row.get("net_quantity") is not None else row.get("quantity"))
    price = finite_float(row.get("mark_price") or row.get("last_mark_price") or row.get("avg_entry_price") or row.get("entry_price"))
    if qty is None or price is None:
        return 0.0
    return abs(qty * price)


def build_adaptive_leverage_margin_selection_status(
    *,
    generated_est: str,
    feasibility: Mapping[str, Any],
    predictions: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    live_gate: Mapping[str, Any],
) -> dict[str, Any]:
    confidence = avg_numbers(predictions, "confidence_calibrated", "confidence")
    edge_bps = finite_float(feasibility.get("current_edge_after_cost_bps"))
    drawdown_bps = finite_float(feasibility.get("max_drawdown"))
    raw_win_rate_value = finite_float(feasibility.get("current_win_rate"))
    raw_profit_factor_value = finite_float(feasibility.get("current_profit_factor"))
    win_rate_value = finite_float(feasibility.get("current_win_rate_qualified"))
    profit_factor_value = finite_float(feasibility.get("current_profit_factor_qualified"))
    sample_status = str(feasibility.get("performance_sample_status") or "")
    volatility_bps = avg_numbers(predictions, "volatility_bps", "atr_bps", "realized_volatility_bps")
    liquidity_score = avg_numbers(predictions, "liquidity_score", "market_liquidity_score", "depth_score")
    spread_bps = avg_numbers(predictions, "effective_spread_bps", "spread_bps", "spread_after_cost_bps")
    total_exposure = round(sum(_position_notional_usdt(row) for row in positions), 8)
    live_margin = finite_float(feasibility.get("live_available_margin"))
    required_margin = finite_float(feasibility.get("live_required_min_order_margin"))
    live_executable = bool(feasibility.get("live_target_executable"))
    timeframe_count = len({str(row.get("timeframe") or row.get("tf") or "") for row in predictions if row.get("timeframe") or row.get("tf")})
    symbols_count = len({str(row.get("symbol") or "") for row in predictions if row.get("symbol")})
    exchange_filter_evidence_present = any(
        row.get(key) not in (None, "")
        for row in predictions
        for key in ("min_notional", "min_notional_usdt", "min_qty", "step_size", "quantity_step", "tick_size")
    )

    missing_evidence = [
        name
        for name, value in (
            ("confidence", confidence),
            ("edge_after_cost_bps", edge_bps),
            ("drawdown_bps", drawdown_bps),
            ("live_available_margin", live_margin),
            ("live_required_min_order_margin", required_margin),
        )
        if value is None
    ]
    optional_missing = [
        name
        for name, value in (
            ("volatility_bps", volatility_bps),
            ("liquidity_score", liquidity_score),
            ("spread_bps", spread_bps),
        )
        if value is None
    ]
    if not exchange_filter_evidence_present:
        optional_missing.append("exchange_filter_evidence")

    minimum_paper_leverage = 1.0
    recommended_leverage = minimum_paper_leverage
    reasons: list[str] = []
    risk_veto_reason = None
    if not live_executable:
        selection_status = "LIVE_READY_BALANCE_HELD_NO_ACTION"
        risk_veto_reason = "live available margin is below required minimum order margin"
        reasons.append("live path remains balance-held; recommendation is paper/read-only")
    elif missing_evidence:
        selection_status = "ADAPTIVE_LEVERAGE_MARGIN_RECOMMENDATION_INSUFFICIENT_EVIDENCE"
        risk_veto_reason = "required confidence, edge, drawdown, or margin evidence is missing"
        reasons.append("missing required evidence prevents leverage increase")
    elif sample_status != "QUALIFIED_CLEAN_PERFORMANCE_SAMPLE":
        selection_status = "ADAPTIVE_LEVERAGE_MARGIN_RECOMMENDATION_INSUFFICIENT_EVIDENCE"
        risk_veto_reason = "clean performance sample is below the qualified evidence threshold"
        reasons.append("fewer than 30 complete clean outcomes keeps paper leverage at 1x")
    elif (edge_bps or 0.0) <= 0 or (confidence or 0.0) < 0.55:
        selection_status = "RISK_ENVELOPE_RECOMMENDS_MINIMUM_LEVERAGE"
        risk_veto_reason = "edge or confidence is too weak for increased paper leverage"
        reasons.append("weak edge/confidence keeps paper recommendation at 1x")
    elif drawdown_bps is not None and drawdown_bps >= 300:
        selection_status = "RISK_ENVELOPE_RECOMMENDS_MINIMUM_LEVERAGE"
        risk_veto_reason = "drawdown is elevated"
        reasons.append("drawdown protection keeps paper recommendation at 1x")
    else:
        selection_status = "ADAPTIVE_LEVERAGE_MARGIN_PAPER_RECOMMENDATION_READY"
        if (
            (confidence or 0.0) >= 0.75
            and (edge_bps or 0.0) >= 25
            and profit_factor_value is not None
            and profit_factor_value >= 1.5
        ):
            recommended_leverage = 3.0
            reasons.append("high confidence, positive edge, and acceptable profit factor support higher paper leverage")
        elif (confidence or 0.0) >= 0.65 and (edge_bps or 0.0) >= 10:
            recommended_leverage = 2.0
            reasons.append("moderate confidence and positive edge support limited paper leverage")
        else:
            reasons.append("evidence supports paper activity but not leverage above 1x")

    if volatility_bps is not None and volatility_bps >= 150:
        recommended_leverage = min(recommended_leverage, minimum_paper_leverage)
        reasons.append("high volatility caps paper leverage recommendation")
    if spread_bps is not None and spread_bps >= 15:
        recommended_leverage = min(recommended_leverage, minimum_paper_leverage)
        reasons.append("wide spread caps paper leverage recommendation")
    if liquidity_score is not None and liquidity_score < 0.35:
        recommended_leverage = min(recommended_leverage, minimum_paper_leverage)
        reasons.append("weak liquidity caps paper leverage recommendation")

    live_action_status = (
        "LIVE_READY_BALANCE_HELD_NO_ACTION"
        if not live_executable
        else "LIVE_PRE_SUBMIT_EVIDENCE_ONLY_NO_MUTATION"
    )
    rationale = "; ".join(reasons) if reasons else "No leverage or margin recommendation rationale available."
    selection_factors = {
        "avg_confidence": confidence,
        "edge_after_cost_bps": edge_bps,
        "current_win_rate": raw_win_rate_value,
        "current_win_rate_qualified": win_rate_value,
        "current_profit_factor": raw_profit_factor_value,
        "current_profit_factor_qualified": profit_factor_value,
        "performance_sample_status": sample_status,
        "minimum_qualified_performance_outcomes": feasibility.get("minimum_qualified_performance_outcomes"),
        "performance_outcome_count": feasibility.get("performance_outcome_count"),
        "drawdown_bps": drawdown_bps,
        "volatility_bps": volatility_bps,
        "liquidity_score": liquidity_score,
        "spread_bps": spread_bps,
        "open_exposure_usdt": total_exposure,
        "live_available_margin": live_margin,
        "live_required_min_order_margin": required_margin,
        "live_wallet_balance": finite_float(feasibility.get("live_wallet_balance")),
        "exchange_filter_evidence_present": exchange_filter_evidence_present,
        "prediction_symbol_count": symbols_count,
        "prediction_timeframe_count": timeframe_count,
        "live_trader_state": live_gate.get("trader_state"),
        "live_order_submit_blocker": live_gate.get("live_order_submit_blocker"),
    }
    safety = {
        "paper_recommendation_only": True,
        "live_leverage_mutation_allowed": False,
        "live_margin_mode_mutation_allowed": False,
        "live_order_submitted": False,
        "test_order_called": False,
        "risk_envelope_can_veto_allocator_output": True,
    }
    return {
        "schema_version": "adaptive_leverage_margin_selection_status_v1",
        "generated_est": generated_est,
        "status": selection_status,
        "selection_status": selection_status,
        "selection_mode": "PAPER_RECOMMENDATION_ONLY_NO_LIVE_MUTATION",
        "recommended_leverage": recommended_leverage,
        "recommended_margin_mode": "ISOLATED_PAPER_SIMULATION",
        "adaptive_leverage": recommended_leverage,
        "adaptive_margin_mode": "ISOLATED_PAPER_SIMULATION",
        "paper_recommended_leverage": recommended_leverage,
        "paper_recommended_margin_mode": "ISOLATED_PAPER_SIMULATION",
        "paper_recommended_margin_budget_policy": "adaptive_allocator_and_risk_envelope_remain_authoritative",
        "live_action_status": live_action_status,
        "live_leverage_margin_action_status": live_action_status,
        "live_available_margin": live_margin,
        "live_required_min_order_margin": required_margin,
        "live_target_executable": live_executable,
        "live_leverage_mutation_allowed": False,
        "live_margin_mode_mutation_allowed": False,
        "no_live_mutation": True,
        "risk_envelope_can_veto_allocator_output": True,
        "risk_veto_reason": risk_veto_reason,
        "selection_reasons": reasons,
        "rationale": rationale,
        "reason": rationale,
        "evidence_quality": (
            "MISSING_REQUIRED_EVIDENCE"
            if missing_evidence
            else "INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE"
            if sample_status != "QUALIFIED_CLEAN_PERFORMANCE_SAMPLE"
            else "QUALIFIED_EVIDENCE"
        ),
        "missing_required_evidence": missing_evidence,
        "missing_optional_evidence": optional_missing,
        "selection_factors": selection_factors,
        "inputs": selection_factors,
        "risk_envelope": {
            "can_veto_allocator_output": True,
            "veto_reason": risk_veto_reason,
            "selection_status": selection_status,
        },
        "safety": safety,
    }


def collect_runtime_inputs(paths: ProfitTargetMonitorPaths | None = None) -> dict[str, Any]:
    paths = paths or ProfitTargetMonitorPaths()
    public = paths.public_root
    paper_dir = public / PAPER_TRADE_REL
    redis_client = connect_redis()
    redis_outcomes = dict_rows(redis_json(redis_client, "v2:paper:outcome_labels", []))
    redis_feedback = dict_rows(redis_json(redis_client, "v2:trainer:feedback:outcomes", []))
    redis_feedback_quarantine = dict_rows(redis_json(redis_client, "v2:trainer:feedback:outcomes:quarantine", []))
    redis_closed = dict_rows(redis_json(redis_client, "v2:paper:closed_trades", []))
    redis_positions = dict_rows(redis_json(redis_client, "v2:paper:positions", []))
    redis_portfolio = as_dict(redis_json(redis_client, "v2:portfolio:state", {}))
    redis_prediction_inventory = redis_prediction_timeframe_inventory(redis_client)
    redis_prediction_timeframes = redis_prediction_inventory.get("current", {})
    prediction_payload = as_dict(read_json(public / PREDICTIONS_REL, {}))
    missing_prediction_diagnostics = missing_prediction_input_diagnostics(redis_client, prediction_payload)
    paper_outcomes = as_dict(read_json(paper_dir / "paper_outcome_labels.json", {}))
    if redis_portfolio:
        portfolio = redis_portfolio
        portfolio["_portfolio_source"] = "redis:v2:portfolio:state"
    else:
        portfolio = as_dict(read_json(public / PORTFOLIO_REL, {}))
        if portfolio:
            portfolio["_portfolio_source"] = str(PORTFOLIO_REL)
    portfolio_positions = portfolio_open_positions(portfolio)
    canonical_redis_positions = canonical_position_rows(redis_positions)
    if portfolio_positions:
        positions = portfolio_positions
        position_source = "operator_runtime:v2_portfolio_state.open_positions"
    elif canonical_redis_positions:
        positions = canonical_redis_positions
        position_source = "redis:v2:paper:positions.canonical_only"
    else:
        positions = []
        position_source = "no_canonical_open_position_rows"
    return {
        "portfolio": portfolio,
        "trainer": as_dict(read_json(public / NATIVE_TRAINER_REL, {})),
        "predictions": prediction_payload,
        "live_gate": as_dict(read_json(public / LIVE_GATE_REL, {})),
        "soak_status": read_first_json(public, REMEDIATED_SOAK_STATUS_REL, SOAK_STATUS_REL),
        "soak_observations": read_first_jsonl(public, REMEDIATED_SOAK_OBSERVATIONS_REL, SOAK_OBSERVATIONS_REL),
        "trade_management": as_dict(read_json(public / TRADE_MANAGEMENT_REL, {})),
        "paper_adaptive_sizing": as_dict(read_json(paper_dir / "paper_adaptive_sizing_runtime_status.json", {})),
        "paper_hedge_netting": as_dict(read_json(paper_dir / "paper_hedge_netting_status.json", {})),
        "paper_outcomes": redis_outcomes or dict_rows(paper_outcomes.get("outcome_labels")),
        "trainer_feedback": redis_feedback,
        "trainer_feedback_quarantine": redis_feedback_quarantine,
        "closed_trades": redis_closed or dict_rows(portfolio.get("closed_positions")),
        "positions": positions,
        "position_source": position_source,
        "raw_redis_position_row_count": len(redis_positions),
        "canonical_redis_position_row_count": len(canonical_redis_positions),
        "redis_prediction_timeframes_by_symbol": redis_prediction_timeframes,
        "redis_stale_prediction_timeframes_by_symbol": redis_prediction_inventory.get("stale", {}),
        "redis_unknown_time_prediction_timeframes_by_symbol": redis_prediction_inventory.get("unknown_time", {}),
        "missing_prediction_input_diagnostics": missing_prediction_diagnostics,
    }


def build_monitor_payloads(inputs: Mapping[str, Any], *, generated_est: str | None = None, generated_utc: str | None = None) -> dict[str, Any]:
    generated_est = generated_est or est_now()
    generated_utc = generated_utc or utc_now()
    now_dt = parse_time(generated_utc) or datetime.now(timezone.utc)
    portfolio = as_dict(inputs.get("portfolio"))
    trainer = as_dict(inputs.get("trainer"))
    live_gate = as_dict(inputs.get("live_gate"))
    trade_management = as_dict(inputs.get("trade_management"))
    hedge_netting = as_dict(inputs.get("paper_hedge_netting"))
    prediction_payload = as_dict(inputs.get("predictions"))
    predictions = prediction_rows(prediction_payload)
    redis_prediction_timeframes = as_dict(inputs.get("redis_prediction_timeframes_by_symbol"))
    redis_stale_prediction_timeframes = as_dict(inputs.get("redis_stale_prediction_timeframes_by_symbol"))
    redis_unknown_time_prediction_timeframes = as_dict(inputs.get("redis_unknown_time_prediction_timeframes_by_symbol"))
    missing_prediction_input_diagnostics = as_dict(inputs.get("missing_prediction_input_diagnostics"))
    soak_status = as_dict(inputs.get("soak_status"))
    observation_window_start_utc = (
        soak_status.get("density_window_first_observation_utc")
        or soak_status.get("first_observation_utc")
        or soak_status.get("proof_window_first_observation_utc")
    )
    outcomes = dict_rows(inputs.get("paper_outcomes"))
    feedback = dict_rows(inputs.get("trainer_feedback"))
    feedback_quarantine = dict_rows(inputs.get("trainer_feedback_quarantine"))
    performance_outcomes, performance_evidence = performance_outcome_rows(
        raw_outcomes=outcomes,
        trainer_feedback_rows=feedback,
    )
    closed = dict_rows(inputs.get("closed_trades"))
    positions = dict_rows(inputs.get("positions"))
    position_source = str(inputs.get("position_source") or "input_positions")
    observations = dict_rows(inputs.get("soak_observations"))

    feasibility = build_monthly_profit_target_feasibility_status(
        generated_est=generated_est,
        generated_utc=generated_utc,
        portfolio=portfolio,
        live_gate=live_gate,
        predictions=predictions,
        outcomes=performance_outcomes,
        observations=observations,
        performance_evidence=performance_evidence,
        observation_window_start_utc=str(observation_window_start_utc)
        if observation_window_start_utc
        else None,
    )
    trainer_capability = build_trainer_profit_goal_capability_status(
        generated_est=generated_est,
        trainer=trainer,
        predictions=predictions,
        prediction_payload=prediction_payload,
        redis_prediction_timeframes=redis_prediction_timeframes,
        redis_stale_prediction_timeframes=redis_stale_prediction_timeframes,
        redis_unknown_time_prediction_timeframes=redis_unknown_time_prediction_timeframes,
        missing_prediction_input_diagnostics=missing_prediction_input_diagnostics,
        outcomes=performance_outcomes,
        feedback_rows=feedback,
        closed_trades=closed,
        now_utc=now_dt,
    )
    strategy = build_adaptive_strategy_selection_status(
        generated_est=generated_est,
        trade_management=trade_management,
        outcomes=performance_outcomes,
    )
    hedge = build_adaptive_hedging_capability_status(
        generated_est=generated_est,
        hedge_status=hedge_netting,
        outcomes=performance_outcomes,
        positions=positions,
        position_source=position_source,
    )
    feedback_status = build_trainer_strategy_hedge_feedback_status(
        generated_est=generated_est,
        outcomes=outcomes,
        feedback_rows=feedback,
        feedback_quarantine_rows=feedback_quarantine,
    )
    feedback_status = merge_feedback_aggregate_evidence(
        feedback_status,
        aggregate_feedback_evidence_from_soak(soak_status),
    )
    simulation = build_monthly_10k_goal_simulation_status(
        generated_est=generated_est,
        feasibility=feasibility,
        outcomes=performance_outcomes,
    )
    leverage_margin = build_adaptive_leverage_margin_selection_status(
        generated_est=generated_est,
        feasibility=feasibility,
        predictions=predictions,
        positions=positions,
        live_gate=live_gate,
    )
    website = {
        "schema_version": "profit_target_website_status_v1",
        "generated_est": generated_est,
        "routes_updated": [
            "/dashboard",
            "/ai-predictions",
            "/ai-predictions/model-state",
            "/signals",
            "/trade/paper",
            "/portfolio",
            "/backtests",
            "/system/trainer",
            "/system/risk-controllers",
            "/system/readiness",
        ],
        "source_payload": "/operator_runtime/v2_monthly_10k_profit_target_monitor/latest/monthly_profit_target_feasibility_status.json",
        "guaranteed_profit_wording_allowed": False,
        "static_200_sizing_visible": False,
    }
    blockers = list(feasibility.get("goal_blockers") or [])
    if feedback_status["feedback_status"] not in {
        "COMPLETE_STRATEGY_HEDGE_FEEDBACK",
        "COMPLETE_FEEDBACK_AVAILABLE_WITH_QUARANTINE",
        "COMPLETE_FEEDBACK_AVAILABLE_FROM_SOAK_EVIDENCE",
    }:
        blockers.append("trainer feedback missing strategy/hedge/regime fields on some closed-trade outcomes")
    if (
        feedback_status.get("feedback_aggregate_evidence_used") is True
        and not performance_outcomes
    ):
        blockers.append(
            "complete trainer feedback is available as aggregate soak evidence, "
            "but realized-PnL feedback rows were not materialized for profit metrics"
        )
    safety = {
        "real_order": False,
        "test_order": False,
        "leverage_margin_mutation": False,
        "old_redis_write": False,
        "legacy_restart": False,
        "redis_trim": False,
        "raw_credentials": False,
        "trainer_bridge_unmasked": False,
        "fixed_runtime_sizing": False,
        "live_balance_held_until_margin_sufficient": str(live_gate.get("trader_state")) == "LIVE_ARMED_BALANCE_HOLD"
        or str(live_gate.get("live_order_submit_blocker")) == "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
    }
    dashboard = {
        "schema_version": "v2_monthly_10k_profit_target_operator_dashboard_v1",
        "gate": READY,
        "go_no_go_marker": READY,
        "generated_est": generated_est,
        "goal_status": feasibility["goal_status"],
        "goal_feasibility_status": feasibility["goal_status"],
        "trainer_capability_status": trainer_capability["trainer_capability_status"],
        "trainer_missing_prediction_rows_count": trainer_capability["missing_prediction_rows_count"],
        "trainer_missing_prediction_symbols": trainer_capability["missing_prediction_symbols"],
        "trainer_missing_prediction_timeframes_by_symbol": trainer_capability["missing_prediction_timeframes_by_symbol"],
        "trainer_stale_prediction_rows_count": trainer_capability["stale_prediction_rows_count"],
        "trainer_stale_prediction_symbols": trainer_capability["stale_prediction_symbols"],
        "trainer_paper_actionability_allowed_rows_count": trainer_capability[
            "paper_actionability_allowed_rows_count"
        ],
        "trainer_paper_actionability_blocked_rows_count": trainer_capability[
            "paper_actionability_blocked_rows_count"
        ],
        "trainer_paper_actionability_block_reason_counts": trainer_capability["paper_actionability_block_reason_counts"],
        "trainer_primary_actionability_blocker": max(
            trainer_capability["paper_actionability_block_reason_counts"].items(),
            key=lambda item: item[1],
        )[0]
        if trainer_capability["paper_actionability_block_reason_counts"]
        else None,
        "trainer_confidence_distribution": trainer_capability["confidence_distribution"],
        "trainer_expected_move_distribution": trainer_capability["expected_move_distribution"],
        "trainer_confidence_median": as_dict(trainer_capability["confidence_distribution"]).get("median"),
        "trainer_confidence_max": as_dict(trainer_capability["confidence_distribution"]).get("max"),
        "trainer_confidence_high_count": as_dict(trainer_capability["confidence_distribution"]).get("high_count"),
        "trainer_expected_move_after_cost_median_bps": as_dict(
            trainer_capability["expected_move_distribution"]
        ).get("median_bps"),
        "trainer_expected_move_after_cost_max_bps": as_dict(
            trainer_capability["expected_move_distribution"]
        ).get("max_bps"),
        "trainer_positive_expected_move_count": as_dict(
            trainer_capability["expected_move_distribution"]
        ).get("positive_count"),
        "trainer_symbol_universe_alignment_status": trainer_capability["trainer_symbol_universe_alignment_status"],
        "trainer_prediction_redis_symbol_count": trainer_capability["trainer_prediction_redis_symbol_count"],
        "publisher_expected_symbol_count": trainer_capability["publisher_expected_symbol_count"],
        "trainer_expected_symbol_mismatch_count": trainer_capability["trainer_expected_symbol_mismatch_count"],
        "trainer_recent_redis_residue_symbol_count": trainer_capability[
            "trainer_recent_redis_residue_symbol_count"
        ],
        "trainer_recent_redis_residue_symbols": trainer_capability["trainer_recent_redis_residue_symbols"],
        "trainer_expected_missing_from_redis_symbols": trainer_capability["trainer_expected_missing_from_redis_symbols"],
        "trainer_redis_extra_prediction_symbols": trainer_capability["trainer_redis_extra_prediction_symbols"],
        "trainer_redis_extra_prediction_timeframes_by_symbol": trainer_capability["trainer_redis_extra_prediction_timeframes_by_symbol"],
        "trainer_stale_prediction_redis_symbol_count": trainer_capability[
            "trainer_stale_prediction_redis_symbol_count"
        ],
        "trainer_stale_redis_prediction_symbols": trainer_capability["trainer_stale_redis_prediction_symbols"],
        "trainer_stale_redis_prediction_timeframes_by_symbol": trainer_capability[
            "trainer_stale_redis_prediction_timeframes_by_symbol"
        ],
        "trainer_unknown_time_prediction_redis_symbol_count": trainer_capability[
            "trainer_unknown_time_prediction_redis_symbol_count"
        ],
        "trainer_unknown_time_redis_prediction_symbols": trainer_capability[
            "trainer_unknown_time_redis_prediction_symbols"
        ],
        "trainer_unknown_time_redis_prediction_timeframes_by_symbol": trainer_capability[
            "trainer_unknown_time_redis_prediction_timeframes_by_symbol"
        ],
        "missing_prediction_input_reason_counts": trainer_capability["missing_prediction_input_reason_counts"],
        "missing_prediction_input_diagnostics_by_symbol": trainer_capability[
            "missing_prediction_input_diagnostics_by_symbol"
        ],
        "hedging_status": hedge["hedging_status"],
        "hedge_status": hedge["hedge_status"],
        "adaptive_hedging_capability_status": hedge["adaptive_hedging_capability_status"],
        "accidental_hedge_count": hedge["accidental_hedge_count"],
        "goal_simulation_status": simulation["goal_simulation_status"],
        "strategy_selection_status": strategy["strategy_selection_status"],
        "adaptive_strategy_selection_status": strategy["adaptive_strategy_selection_status"],
        "strategy_family_count": strategy["strategy_family_count"],
        "adaptive_leverage_margin_selection_status": leverage_margin["selection_status"],
        "paper_recommended_leverage": leverage_margin["paper_recommended_leverage"],
        "paper_recommended_margin_mode": leverage_margin["paper_recommended_margin_mode"],
        "live_leverage_margin_action_status": leverage_margin["live_action_status"],
        "live_action_status": leverage_margin["live_action_status"],
        "monthly_target_net_usdt": MONTHLY_TARGET_NET_USDT,
        "paper_equity": feasibility["paper_equity"],
        "paper_equity_source": feasibility.get("paper_equity_source"),
        "paper_24h_pnl": feasibility["paper_24h_pnl"],
        "paper_run_rate_monthly_pnl": feasibility["paper_run_rate_monthly_pnl"],
        "paper_run_rate_monthly_return_pct": feasibility["paper_run_rate_monthly_return_pct"],
        "max_drawdown": feasibility["max_drawdown"],
        "max_drawdown_bps": feasibility["max_drawdown_bps"],
        "drawdown_source": feasibility["drawdown_source"],
        "drawdown_observation_count": feasibility["drawdown_observation_count"],
        "drawdown_equity_point_count": feasibility["drawdown_equity_point_count"],
        "drawdown_window_start_utc": feasibility["drawdown_window_start_utc"],
        "drawdown_adjusted_monthly_projection": feasibility["drawdown_adjusted_monthly_projection"],
        "capital_required_for_target_at_current_edge": feasibility["capital_required_for_target_at_current_edge"],
        "required_monthly_return_pct": feasibility["required_monthly_return_pct"],
        "current_edge_after_cost_bps": feasibility["current_edge_after_cost_bps"],
        "current_win_rate": feasibility["current_win_rate"],
        "current_win_rate_qualified": feasibility["current_win_rate_qualified"],
        "current_profit_factor": feasibility["current_profit_factor"],
        "current_profit_factor_qualified": feasibility["current_profit_factor_qualified"],
        "performance_metric_source": feasibility["performance_metric_source"],
        "raw_outcome_count": feasibility["raw_outcome_count"],
        "performance_outcome_count": feasibility["performance_outcome_count"],
        "dirty_outcome_count": feasibility["dirty_outcome_count"],
        "performance_sample_status": feasibility["performance_sample_status"],
        "minimum_qualified_performance_outcomes": feasibility["minimum_qualified_performance_outcomes"],
        "live_available_margin": feasibility["live_available_margin"],
        "live_required_min_order_margin": leverage_margin.get("live_required_min_order_margin")
        if leverage_margin.get("live_required_min_order_margin") is not None
        else feasibility["live_required_min_order_margin"],
        "live_target_executable": feasibility["live_target_executable"],
        "adaptive_leverage_status": leverage_margin["selection_status"],
        "adaptive_leverage": leverage_margin.get("adaptive_leverage"),
        "adaptive_margin_mode": leverage_margin.get("adaptive_margin_mode"),
        "adaptive_leverage_evidence_quality": leverage_margin.get("evidence_quality"),
        "adaptive_leverage_reason": leverage_margin.get("reason"),
        "risk_envelope_veto_reason": as_dict(leverage_margin.get("risk_envelope")).get("veto_reason"),
        "risk_envelope_can_veto_allocator_output": as_dict(leverage_margin.get("risk_envelope")).get("can_veto_allocator_output"),
        "risk_required_for_10k": simulation["risk_required_for_10k"],
        "top_strategy_weights": [
            {
                "strategy_family": row.get("strategy_family"),
                "current_weight": row.get("current_weight"),
                "expectancy_after_cost_bps": row.get("expectancy_after_cost_bps"),
                "closed_trades": row.get("closed_trades"),
            }
            for row in sorted(
                strategy.get("families") or [],
                key=lambda item: finite_float(as_dict(item).get("current_weight")) or 0.0,
                reverse=True,
            )[:5]
            if isinstance(row, Mapping)
        ],
        "dynamic_strategy_inputs": strategy.get("dynamic_strategy_inputs") or strategy.get("dynamic_selection_inputs"),
        "dynamic_selection_factors": strategy.get("dynamic_selection_factors") or strategy.get("dynamic_selection_inputs"),
        "hedge_net_pnl": hedge["hedge_net_pnl"],
        "hedge_cost": hedge["hedge_cost"],
        "hedge_benefit": hedge["hedge_benefit"],
        "hedge_position_source": hedge["position_source"],
        "hedge_open_position_count_checked": hedge["open_position_count_checked_for_accidental_hedge"],
        "hedge_noncanonical_position_rows_ignored": hedge["noncanonical_position_rows_ignored_count"],
        "feedback_status": feedback_status["feedback_status"],
        "trainer_feedback_aggregate_evidence_used": feedback_status.get("feedback_aggregate_evidence_used", False),
        "trainer_feedback_aggregate_evidence_source": feedback_status.get("feedback_aggregate_evidence_source"),
        "trainer_feedback_performance_rows_materialized_for_metrics": feedback_status.get(
            "performance_rows_materialized_for_metrics",
            True,
        ),
        "trainer_feedback_row_count": feedback_status["trainer_feedback_row_count"],
        "trainer_feedback_consumable_row_count": feedback_status["trainer_feedback_consumable_row_count"],
        "trainer_feedback_quarantined_row_count": feedback_status["trainer_feedback_quarantined_row_count"],
        "trainer_feedback_total_row_count": feedback_status["trainer_feedback_total_row_count"],
        "trainer_feedback_missing_field_counts": feedback_status["missing_field_counts"],
        "trainer_feedback_consumable_missing_field_counts": feedback_status["consumable_missing_field_counts"],
        "trainer_feedback_quarantine_missing_field_counts": feedback_status["quarantine_missing_field_counts"],
        "trainer_feedback_rows_with_strategy_fields": feedback_status["feedback_rows_with_strategy_fields"],
        "trainer_feedback_rows_with_hedge_fields": feedback_status["feedback_rows_with_hedge_fields"],
        "trainer_feedback_missing_strategy_feedback_count": feedback_status["missing_strategy_feedback_count"],
        "trainer_feedback_missing_hedge_feedback_count": feedback_status["missing_hedge_feedback_count"],
        "trainer_feedback_readiness_summary": feedback_status["readiness_summary"],
        "blockers": blockers,
        "profit_claim_policy": "objective_not_guarantee",
        "safety": safety,
    }
    report = build_report(dashboard, feasibility, trainer_capability, strategy, hedge, feedback_status, simulation, leverage_margin)
    go_no_go = READY
    return {
        "monthly_profit_target_feasibility_status.json": feasibility,
        "trainer_profit_goal_capability_status.json": trainer_capability,
        "adaptive_strategy_selection_status.json": strategy,
        "adaptive_hedging_capability_status.json": hedge,
        "adaptive_leverage_margin_selection_status.json": leverage_margin,
        "trainer_strategy_hedge_feedback_status.json": feedback_status,
        "monthly_10k_goal_simulation_status.json": simulation,
        "profit_target_website_status.json": website,
        "operator_dashboard_payload.json": dashboard,
        "GO_NO_GO.md": go_no_go,
        "V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_REPORT.md": report,
    }


def build_report(
    dashboard: Mapping[str, Any],
    feasibility: Mapping[str, Any],
    trainer: Mapping[str, Any],
    strategy: Mapping[str, Any],
    hedge: Mapping[str, Any],
    feedback: Mapping[str, Any],
    simulation: Mapping[str, Any],
    leverage_margin: Mapping[str, Any],
) -> str:
    blockers = dashboard.get("blockers") or []
    return (
        "# V2 Monthly 10K Profit Target Trainer Strategy Hedge Monitor Report\n\n"
        f"Gate: `{dashboard.get('gate')}`\n\n"
        "This monitor treats 10,000+ USDT/month as an evidence-based net-profit objective, not a guaranteed return.\n\n"
        "| Field | Value |\n|---|---:|\n"
        f"| Goal status | `{feasibility.get('goal_status')}` |\n"
        f"| Paper equity | `{feasibility.get('paper_equity')}` |\n"
        f"| Paper monthly run-rate net PnL | `{feasibility.get('paper_run_rate_monthly_pnl')}` |\n"
        f"| Drawdown-adjusted monthly projection | `{feasibility.get('drawdown_adjusted_monthly_projection')}` |\n"
        f"| Required monthly return pct | `{feasibility.get('required_monthly_return_pct')}` |\n"
        f"| Live available margin | `{feasibility.get('live_available_margin')}` |\n"
        f"| Live target executable | `{feasibility.get('live_target_executable')}` |\n"
        f"| Trainer capability | `{trainer.get('trainer_capability_status')}` |\n"
        f"| Hedge status | `{hedge.get('hedging_status')}` |\n"
        f"| Simulation status | `{simulation.get('goal_simulation_status')}` |\n\n"
        f"| Adaptive leverage/margin status | `{leverage_margin.get('selection_status')}` |\n"
        f"| Paper recommended leverage | `{leverage_margin.get('paper_recommended_leverage')}` |\n"
        f"| Paper recommended margin mode | `{leverage_margin.get('paper_recommended_margin_mode')}` |\n"
        f"| Live leverage/margin action | `{leverage_margin.get('live_action_status')}` |\n\n"
        "Blockers:\n"
        + "\n".join(f"- {item}" for item in blockers)
        + ("\n" if blockers else "- none\n")
        + "\nSafety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no trainer bridge unmask.\n"
        + f"\nStrategy families monitored: `{len(strategy.get('families') or [])}`. "
        + f"Feedback status: `{feedback.get('feedback_status')}`.\n"
    )


def publish_all(paths: ProfitTargetMonitorPaths | None = None) -> dict[str, Any]:
    paths = paths or ProfitTargetMonitorPaths()
    payloads = build_monitor_payloads(collect_runtime_inputs(paths))
    json_names = [
        "monthly_profit_target_feasibility_status.json",
        "trainer_profit_goal_capability_status.json",
        "adaptive_strategy_selection_status.json",
        "adaptive_hedging_capability_status.json",
        "adaptive_leverage_margin_selection_status.json",
        "trainer_strategy_hedge_feedback_status.json",
        "monthly_10k_goal_simulation_status.json",
        "profit_target_website_status.json",
        "operator_dashboard_payload.json",
    ]
    for name in json_names:
        write_json(paths.operator_dir / name, payloads[name])
        write_json(paths.artifact_dir / name, payloads[name])
        write_json(paths.worklog_dir / name, payloads[name])
    for name in ("GO_NO_GO.md", "V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_REPORT.md"):
        write_text(paths.artifact_dir / name, str(payloads[name]))
        write_text(paths.worklog_dir / name, str(payloads[name]))
    return payloads


__all__ = [
    "READY",
    "BLOCKED",
    "ProfitTargetMonitorPaths",
    "build_monitor_payloads",
    "collect_runtime_inputs",
    "publish_all",
]
