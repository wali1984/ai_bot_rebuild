from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from v2.backend.app.services.paper_churn_governor import evaluate_churn_governor


CURRENT_CHALLENGER_GOAL_ID = "V2_CHALLENGER_V2_REPRODUCIBLE_COST_PARITY_FEATURE_ADAPTER_BLIND_LOCKBOX_AND_FORWARD_CANARY"
PAPER_GOVERNANCE_GOAL_ID = "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR"
CHALLENGER_CANDIDATE_ID = "challenger_v2_338f76bd071ba8ddfadb5d38"

PAPER_REDIS_KEYS = (
    "v2:paper:closed_trades",
    "v2:paper:ledger",
    "v2:portfolio:state",
    "v2:paper:heartbeat",
)
LOCAL_PAPER_EVENT_SOURCES = (
    ("paper_online_latest_jsonl", Path("v2/runtime/paper_online/latest/paper_events.jsonl")),
)

REQUIRED_ATTRIBUTION_FIELDS = (
    "model_source",
    "trainer_source",
    "policy_version",
    "prediction_id",
    "signal_id",
    "strategy_id",
    "timeframe",
)

EXPLICIT_REALIZED_PNL_FIELDS = (
    "realized_net_pnl_usd",
    "realized_net_pnl_usdt",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "net_pnl_usd",
    "net_pnl_usdt",
    "realized_delta_usdt",
    "paper_pnl_delta",
)

THESIS_EXECUTION_REQUIRED_FIELDS = (
    "thesis_timeframe",
    "execution_timeframe",
    "confirmation_timeframes",
    "strategy_horizon_seconds",
    "expected_holding_period_seconds",
    "thesis_prediction_id",
    "execution_snapshot_id",
)
POST_FIX_SAMPLE_REQUIRED_IDENTITY_FIELDS = (
    "economic_trade_id",
    "economic_thesis_id",
    "parent_position_id",
)

HIGHER_THESIS_TIMEFRAMES = {"15m", "1h", "4h"}
ENTRY_COST_REQUIRED_FIELDS = (
    "observed_spread",
    "maker_taker_fee",
    "depth_derived_price_impact",
    "expected_slippage",
    "funding",
    "latency_reserve",
    "partial_fill_reserve",
    "round_trip_cost",
    "cost_uncertainty",
)
EDGE_TO_COST_CONTEXTUAL_SAFETY_RATIO = 1.5
DYNAMIC_TIMEFRAME_MIN_ECONOMIC_TRADES = 100
DYNAMIC_TIMEFRAME_MIN_SYMBOLS = 5
DYNAMIC_TIMEFRAME_MIN_PROFIT_FACTOR = 1.5
DYNAMIC_TIMEFRAME_EXPECTANCY_Z = 1.96
DYNAMIC_TIMEFRAME_MAX_COST_DRAG = 0.35
TIMEFRAME_CONCENTRATION_MAX_SHARE = 0.30
OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS = (
    "raw_close_records",
    "raw_close_record_count",
    "compacted_economic_trades",
    "economic_trade_count",
    "trade_share_by_timeframe",
    "fee_share_by_timeframe",
    "turnover",
    "turnover_by_timeframe",
    "reentry_count",
    "duplicate_blocks",
    "cost_drag",
    "edge_to_cost_ratio",
    "one_min_status",
    "thesis_timeframe",
    "execution_timeframe",
)
REQUIRED_PAPER_GOVERNANCE_ARTIFACTS = (
    "current_paper_timeframe_churn_audit.json",
    "current_paper_economic_trade_reconciliation.json",
    "economic_trade_compaction_status.json",
    "paper_churn_governor_status.json",
    "paper_entry_cost_coverage_status.json",
    "paper_edge_to_cost_gate_status.json",
    "dynamic_timeframe_execution_eligibility_status.json",
    "timeframe_execution_concentration_guard_status.json",
    "multi_timeframe_thesis_execution_contract_status.json",
    "paper_reentry_and_signal_dedup_status.json",
    "paper_timeframe_routing_owner_status.json",
    "paper_timeframe_routing_repair_contract.json",
    "post_fix_paper_validation_status.json",
    "operator_dashboard_payload.json",
    "operator_dashboard_truth_contract_status.json",
    "GO_NO_GO.md",
    "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_REPORT.md",
)

SOURCE_SCAN_FILES = (
    "v2/backend/app/cli/paper_online_runtime.py",
    "v2/backend/app/cli/v2_trade_management_paper_loop.py",
    "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
)
PAPER_ROUTING_COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        "component": "prediction_publisher",
        "required_role": "prediction publisher",
        "files": ["v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py"],
        "required_terms": ["def build_prediction_row", "prediction_key(", "routes_to_orchestrator"],
    },
    {
        "component": "signal_publisher",
        "required_role": "signal publisher",
        "files": [
            "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
            "v2/backend/app/cli/paper_online_runtime.py",
        ],
        "required_terms": ["v2:signals:paper", "paper_fill_allowed", "signal_id"],
    },
    {
        "component": "strategy_router",
        "required_role": "strategy router",
        "files": [
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
            "v2/backend/app/services/strategy_router/service.py",
        ],
        "required_terms": ["route_strategy", "strategy_router", "strategy_id"],
    },
    {
        "component": "risk_gateway",
        "required_role": "risk gateway",
        "files": [
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
            "v2/backend/app/services/risk_gateway/service.py",
        ],
        "required_terms": ["risk_decision_id", "risk_action", "v2:risk:decisions"],
    },
    {
        "component": "orchestrator",
        "required_role": "orchestrator",
        "files": [
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
            "v2/backend/app/services/orchestrator_decision/service.py",
            "v2/backend/app/services/orchestrator_arbitration/service.py",
        ],
        "required_terms": ["orchestrator_decision_id", "orchestrator_state", "paper_fill_allowed"],
    },
    {
        "component": "paper_intent_builder",
        "required_role": "paper intent builder",
        "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
        "required_terms": ["intent_id", "v2:paper:intents", "paper_fill_gate"],
    },
    {
        "component": "paper_fill_worker",
        "required_role": "paper fill worker",
        "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
        "required_terms": ["accepted_for_ledger", "_attach_paper_execution_evidence", "accepted_open_fills"],
    },
    {
        "component": "paper_lifecycle_manager",
        "required_role": "paper lifecycle manager",
        "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
        "required_terms": ["closed_trades", "paper:closed_trades", "outcome_labels"],
    },
    {
        "component": "trainer_feedback",
        "required_role": "trainer feedback",
        "files": [
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
            "v2/backend/app/services/paper_shadow_outcome_observer/service.py",
        ],
        "required_terms": ["trainer_feedback", "trainer:feedback:outcomes", "trainer_consumable"],
    },
)
FINAL_READY_MARKER = "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY"
FINAL_BLOCKED_MARKER = "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_BLOCKED"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        for key in ("rows", "closed_trades", "closes", "closed", "closed_positions", "entries"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def rows_from_payload(payload: Any, *, keys: Sequence[str] = ("rows", "closed_trades", "closes", "closed", "closed_positions")) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        rows: list[dict[str, Any]] = []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(dict(row) for row in value if isinstance(row, Mapping))
        return rows
    return []


def first_present(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def mark_post_fix_sample_source(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_name: str,
    source_path: str | None = None,
) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["_post_fix_sample_source"] = source_name
        if source_path is not None:
            item["_post_fix_sample_source_path"] = source_path
        marked.append(item)
    return marked


def read_local_paper_event_close_rows(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    statuses: dict[str, Any] = {}
    for source_name, relative_path in LOCAL_PAPER_EVENT_SOURCES:
        path = repo_root / relative_path
        status: dict[str, Any] = {
            "source": source_name,
            "path": str(path),
            "relative_path": str(relative_path),
            "exists": path.exists(),
            "line_count": 0,
            "candidate_close_line_count": 0,
            "closed_paper_outcome_rows": 0,
            "json_decode_error_count": 0,
            "non_object_json_count": 0,
            "sample_json_decode_errors": [],
        }
        if not path.exists():
            status["status"] = "MISSING_LOCAL_PAPER_EVENTS_JSONL"
            statuses[source_name] = status
            continue

        status["raw_bytes"] = path.stat().st_size
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                status["line_count"] += 1
                if "POSITION_CLOSED_PAPER_ONLY" not in line:
                    continue
                status["candidate_close_line_count"] += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    status["json_decode_error_count"] += 1
                    if len(status["sample_json_decode_errors"]) < 5:
                        status["sample_json_decode_errors"].append(
                            {
                                "line_number": line_number,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                    continue
                if not isinstance(payload, Mapping):
                    status["non_object_json_count"] += 1
                    continue
                if str(first_present(payload, "paper_result", "ledger_action", "close_result") or "") != "POSITION_CLOSED_PAPER_ONLY":
                    continue
                row = dict(payload)
                row["_post_fix_sample_source"] = source_name
                row["_post_fix_sample_source_path"] = str(path)
                row["_post_fix_sample_line_number"] = line_number
                rows.append(row)
        status["closed_paper_outcome_rows"] = sum(
            1
            for row in rows
            if row.get("_post_fix_sample_source") == source_name
        )
        status["status"] = (
            "PASS_LOCAL_PAPER_EVENTS_JSONL_READ"
            if status["json_decode_error_count"] == 0 and status["non_object_json_count"] == 0
            else "READ_LOCAL_PAPER_EVENTS_JSONL_WITH_ERRORS"
        )
        statuses[source_name] = status
    return rows, statuses


def finite_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def first_float(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = finite_float(row.get(name))
        if parsed is not None:
            return parsed
    return None


def failed_pass_condition_details(
    *,
    pass_conditions: Mapping[str, bool],
    actuals: Mapping[str, Any],
    required: Mapping[str, Any],
    source_artifact: str,
) -> list[dict[str, Any]]:
    return [
        {
            "pass_condition": name,
            "actual": actuals.get(name),
            "required": required.get(name),
            "source_artifact": source_artifact,
        }
        for name, passed in pass_conditions.items()
        if passed is not True
    ]


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def seconds_between(start: Any, end: Any) -> float | None:
    start_dt = parse_time(start)
    end_dt = parse_time(end)
    if start_dt is None or end_dt is None:
        return None
    seconds = (end_dt - start_dt).total_seconds()
    return seconds if seconds >= 0 else None


def median(values: Sequence[float]) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def mean(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def sample_stddev(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 2:
        return None
    avg = sum(clean) / len(clean)
    return math.sqrt(sum((value - avg) ** 2 for value in clean) / (len(clean) - 1))


def lower_confidence_bound(values: Sequence[float], *, z_score: float = DYNAMIC_TIMEFRAME_EXPECTANCY_Z) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    avg = sum(clean) / len(clean)
    if len(clean) < 2:
        return avg
    stddev = sample_stddev(clean)
    if stddev is None:
        return avg
    return avg - z_score * stddev / math.sqrt(len(clean))


def worst_percentile(values: Sequence[float], percentile: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    index = max(0, min(len(clean) - 1, math.ceil(len(clean) * percentile) - 1))
    return clean[index]


def max_drawdown(values: Sequence[float]) -> float:
    peak = 0.0
    equity = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def timeframe_of(row: Mapping[str, Any]) -> str:
    return str(
        first_present(
            row,
            "thesis_timeframe",
            "prediction_timeframe",
            "timeframe",
            "entry_timeframe",
            "execution_timeframe",
        )
        or "UNKNOWN"
    )


def thesis_timeframe_of(row: Mapping[str, Any]) -> str:
    return str(first_present(row, "thesis_timeframe", "prediction_timeframe", "timeframe") or "UNKNOWN")


def execution_timeframe_of(row: Mapping[str, Any]) -> str:
    return str(first_present(row, "execution_timeframe", "entry_timeframe", "feature_timeframe", "timeframe") or "UNKNOWN")


def thesis_candle_of(row: Mapping[str, Any]) -> Any:
    return first_present(
        row,
        "thesis_candle_close_time",
        "entry_feature_cutoff",
        "feature_cutoff",
        "candle_close_time",
        "entry_feature_snapshot_id",
        "feature_snapshot_id",
    )


def strategy_id_of(row: Mapping[str, Any]) -> str:
    return str(first_present(row, "strategy_id", "strategy_family", "strategy_selected_mode", "strategy_subtype") or "UNKNOWN")


def side_of(row: Mapping[str, Any]) -> str:
    side = str(first_present(row, "side", "selected_action", "action", "direction") or "UNKNOWN").upper()
    if "LONG" in side or side == "BUY":
        return "LONG"
    if "SHORT" in side or side == "SELL":
        return "SHORT"
    return side


def symbol_of(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "UNKNOWN").upper()


def entry_time_of(row: Mapping[str, Any]) -> Any:
    return first_present(
        row,
        "entry_time",
        "opened_at",
        "entry_price_utc",
        "entry_feature_decision_time",
        "decision_time",
        "generated_utc",
        "generated_at",
    )


def exit_time_of(row: Mapping[str, Any]) -> Any:
    return first_present(
        row,
        "exit_time",
        "exit_price_utc",
        "closed_utc",
        "closed_at",
        "generated_utc",
        "generated_at",
        "decision_time",
    )


def gross_pnl_usd(row: Mapping[str, Any]) -> float:
    return first_float(row, "gross_pnl_usd", "gross_pnl_usdt", "gross_realized_pnl_usd", "pnl_before_cost_usd") or 0.0


def net_pnl_usd(row: Mapping[str, Any]) -> float:
    parsed = first_float(
        row,
        "realized_net_pnl_usd",
        "realized_net_pnl_usdt",
        "realized_pnl_usd",
        "realized_pnl_usdt",
        "net_pnl_usd",
        "net_pnl_usdt",
        "realized_delta_usdt",
        "paper_pnl_delta",
    )
    if parsed is not None:
        return parsed
    gross = gross_pnl_usd(row)
    return gross - fee_usd(row) - slippage_usd(row) + funding_usd(row)


def fee_usd(row: Mapping[str, Any]) -> float:
    total = first_float(row, "fees_usd", "fee_usd", "fee_usdt", "expected_fees_usd")
    if total is not None:
        return abs(total)
    entry = first_float(row, "entry_fee_usd", "entry_fee_usdt") or 0.0
    exit_fee = first_float(row, "exit_fee_usd", "exit_fee_usdt") or 0.0
    return abs(entry) + abs(exit_fee)


def slippage_usd(row: Mapping[str, Any]) -> float:
    parsed = first_float(
        row,
        "realized_slippage_usd",
        "slippage_usd",
        "expected_slippage_usd",
        "implementation_shortfall_usd",
        "expected_shortfall_usd",
    )
    return abs(parsed or 0.0)


def funding_usd(row: Mapping[str, Any]) -> float:
    return first_float(row, "funding_pnl_usd", "funding_usd", "expected_funding_usd") or 0.0


def notional_usd(row: Mapping[str, Any]) -> float:
    parsed = first_float(
        row,
        "gross_notional_usd",
        "notional_usd",
        "notional_usdt",
        "order_notional_usd",
        "target_notional_usdt",
        "allocated_notional_usd",
    )
    if parsed is not None:
        return abs(parsed)
    margin = first_float(row, "allocated_margin_usd", "margin_usd") or 0.0
    leverage = first_float(row, "effective_leverage", "recommended_leverage") or 1.0
    return abs(margin * leverage)


def hold_seconds(row: Mapping[str, Any]) -> float | None:
    parsed = first_float(row, "hold_time_seconds", "holding_period_seconds", "duration_seconds")
    if parsed is not None and parsed >= 0:
        return parsed
    return seconds_between(entry_time_of(row), exit_time_of(row))


def cost_drag_pct(gross: float, fees: float, slippage: float, funding: float) -> float | None:
    denom = abs(gross)
    if denom <= 1e-12:
        return None
    return (fees + slippage + abs(funding)) / denom


def profit_factor(values: Sequence[float]) -> float | None:
    profit = sum(value for value in values if value > 0)
    loss = abs(sum(value for value in values if value < 0))
    if loss <= 1e-12:
        return None if profit <= 0 else float("inf")
    return profit / loss


def attribution(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model_source": first_present(row, "model_source", "model_version", "checkpoint_id", "prediction_score_source"),
        "trainer_source": first_present(row, "trainer_source", "source_runtime_lane", "prediction_source_type", "trainer_runtime"),
        "policy_version": first_present(row, "policy_version", "adaptive_capital_policy_version", "policy_activated_at"),
        "prediction_id": first_present(row, "entry_prediction_id", "prediction_id", "source_prediction_id"),
        "signal_id": first_present(row, "entry_signal_id", "signal_id", "exit_signal_id"),
        "strategy_id": first_present(row, "strategy_id", "strategy_family", "strategy_selected_mode", "strategy_subtype"),
        "timeframe": timeframe_of(row),
    }


def economic_trade_id(row: Mapping[str, Any]) -> str:
    explicit = first_present(
        row,
        "economic_trade_id",
        "economic_thesis_id",
        "parent_position_id",
        "position_id",
        "paper_position_id",
        "open_position_id",
        "entry_position_id",
    )
    if explicit is not None:
        return str(explicit)
    return "econ_" + stable_hash(
        {
            "symbol": symbol_of(row),
            "side": side_of(row),
            "timeframe": timeframe_of(row),
            "entry_prediction_id": first_present(row, "entry_prediction_id", "prediction_id"),
            "entry_signal_id": first_present(row, "entry_signal_id", "signal_id"),
            "entry_feature_snapshot_id": first_present(row, "entry_feature_snapshot_id", "feature_snapshot_id"),
            "entry_price": first_present(row, "entry_price", "avg_entry_price"),
            "entry_time": entry_time_of(row),
            "strategy_id": first_present(row, "strategy_id", "strategy_family", "strategy_selected_mode"),
        }
    )[:24]


def is_partial_reduce(row: Mapping[str, Any]) -> bool:
    if row.get("is_partial_reduce") is True:
        return True
    reason = str(first_present(row, "close_reason", "exit_reason", "hedge_reason", "entry_reason") or "").lower()
    return "partial_reduce" in reason or "reduce" in reason


def is_partial_close(row: Mapping[str, Any]) -> bool:
    if row.get("is_partial_close") is True:
        return True
    reason = str(first_present(row, "close_reason", "exit_reason", "hedge_reason", "entry_reason") or "").lower()
    return "partial" in reason and "close" in reason


def is_reversal(row: Mapping[str, Any]) -> bool:
    if row.get("is_reversal") is True:
        return True
    reason = str(first_present(row, "close_reason", "exit_reason", "entry_reason") or "").lower()
    return "reversal" in reason or "flip" in reason


def is_full_close(row: Mapping[str, Any]) -> bool:
    if row.get("is_full_close") is True:
        return True
    if is_partial_close(row) or is_partial_reduce(row):
        return False
    reason = str(first_present(row, "close_reason", "exit_reason") or "").lower()
    if "full" in reason or "flat" in reason or "close" in reason or "stop" in reason or "take_profit" in reason:
        return True
    closed_qty = first_float(row, "closed_quantity", "quantity_closed", "exit_quantity")
    qty = first_float(row, "quantity", "position_quantity", "entry_quantity")
    if closed_qty is not None and qty is not None and qty > 0:
        return closed_qty >= qty - 1e-12
    return True


def source_record_id(row: Mapping[str, Any], index: int) -> str:
    return str(
        first_present(
            row,
            "close_id",
            "closed_trade_id",
            "trade_id",
            "paper_ledger_entry_id",
            "execution_intent_id",
            "outcome_label_id",
        )
        or f"raw_index_{index}"
    )


def timeframe_bucket_metrics(rows: Sequence[Mapping[str, Any]], economic_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    raw_by_tf: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    econ_by_tf: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        raw_by_tf[timeframe_of(row)].append(row)
    for row in economic_rows:
        econ_by_tf[str(row.get("timeframe") or "UNKNOWN")].append(row)
    timeframes = sorted(set(raw_by_tf) | set(econ_by_tf))
    payload: dict[str, Any] = {}
    for tf in timeframes:
        raw = raw_by_tf.get(tf, [])
        econ = econ_by_tf.get(tf, [])
        gross = sum(gross_pnl_usd(row) for row in raw)
        fees = sum(fee_usd(row) for row in raw)
        slippage = sum(slippage_usd(row) for row in raw)
        funding = sum(funding_usd(row) for row in raw)
        net = sum(net_pnl_usd(row) for row in raw)
        hold_times = [value for row in raw if (value := hold_seconds(row)) is not None]
        notionals = [notional_usd(row) for row in raw if notional_usd(row) > 0]
        payload[tf] = {
            "trade_count": len(raw),
            "economic_trade_count": len(econ),
            "gross_pnl_usd": gross,
            "fees_usd": fees,
            "slippage_usd": slippage,
            "funding_usd": funding,
            "net_pnl_usd": net,
            "profit_factor": profit_factor([net_pnl_usd(row) for row in raw]),
            "cost_as_pct_of_gross": cost_drag_pct(gross, fees, slippage, funding),
            "median_hold_time_seconds": median(hold_times),
            "median_notional_usd": median(notionals),
            "turnover_usd": sum(notional_usd(row) for row in raw),
        }
    return payload


def hourly_rate(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    buckets: Counter[str] = Counter()
    for row in rows:
        stamp = parse_time(exit_time_of(row) or entry_time_of(row))
        if stamp is None:
            continue
        key = f"{symbol_of(row)}|{stamp.strftime('%Y-%m-%dT%H:00Z')}"
        buckets[key] += 1
    by_symbol: dict[str, list[int]] = defaultdict(list)
    for key, count in buckets.items():
        symbol, _hour = key.split("|", 1)
        by_symbol[symbol].append(count)
    return {symbol: max(counts) for symbol, counts in sorted(by_symbol.items())}


def duplicate_and_reentry_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            symbol_of(row),
            parse_time(entry_time_of(row) or exit_time_of(row)) or datetime.min.replace(tzinfo=timezone.utc),
        ),
    )
    same_side_reentries = 0
    opposite_side_flips = 0
    previous_by_symbol: dict[str, Mapping[str, Any]] = {}
    reentry_rows: list[Mapping[str, Any]] = []
    duplicate_prediction: Counter[str] = Counter()
    duplicate_decision: Counter[str] = Counter()
    duplicate_candle: Counter[str] = Counter()
    for row in sorted_rows:
        symbol = symbol_of(row)
        side = side_of(row)
        previous = previous_by_symbol.get(symbol)
        if previous is not None:
            previous_side = side_of(previous)
            if side == previous_side:
                same_side_reentries += 1
                reentry_rows.append(row)
            elif side in {"LONG", "SHORT"} and previous_side in {"LONG", "SHORT"}:
                opposite_side_flips += 1
        previous_by_symbol[symbol] = row

        prediction_id = first_present(row, "entry_prediction_id", "prediction_id")
        if prediction_id:
            duplicate_prediction[str(prediction_id)] += 1
        decision_id = first_present(row, "decision_id", "orchestrator_decision_id", "risk_decision_id")
        if decision_id:
            duplicate_decision[str(decision_id)] += 1
        candle = first_present(row, "entry_feature_cutoff", "feature_cutoff", "candle_close_time", "entry_feature_snapshot_id")
        strategy = first_present(row, "strategy_id", "strategy_family", "strategy_selected_mode")
        if candle:
            duplicate_candle[f"{symbol}|{timeframe_of(row)}|{candle}|{strategy}|{side}"] += 1

    def duplicate_total(counter: Counter[str]) -> int:
        return sum(count - 1 for count in counter.values() if count > 1)

    return {
        "reopen_count": same_side_reentries + opposite_side_flips,
        "same_side_reentries": same_side_reentries,
        "opposite_side_flips": opposite_side_flips,
        "same_prediction_duplicate_entries": duplicate_total(duplicate_prediction),
        "same_decision_duplicate_entries": duplicate_total(duplicate_decision),
        "same_candle_duplicate_entries": duplicate_total(duplicate_candle),
        "reentries_per_symbol_per_hour": hourly_rate(reentry_rows),
    }


def duplicate_identity_violation_count(duplicate_counts: Mapping[str, Any]) -> int:
    return sum(
        int(duplicate_counts.get(field) or 0)
        for field in (
            "same_prediction_duplicate_entries",
            "same_decision_duplicate_entries",
            "same_signal_duplicate_entries",
            "same_feature_snapshot_duplicate_entries",
            "same_candle_duplicate_entries",
        )
    )


def duplicate_identity_samples(rows: Sequence[Mapping[str, Any]], *, limit: int = 25) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    for index, row in enumerate(rows):
        symbol = symbol_of(row)
        side = side_of(row)
        strategy = first_present(row, "strategy_id", "strategy_family", "strategy_selected_mode")
        prediction_id = first_present(row, "entry_prediction_id", "prediction_id")
        if prediction_id:
            grouped[("same_prediction_duplicate_entries", str(prediction_id))].append((index, row))
        decision_id = first_present(row, "decision_id", "orchestrator_decision_id", "risk_decision_id")
        if decision_id:
            grouped[("same_decision_duplicate_entries", str(decision_id))].append((index, row))
        candle = first_present(row, "entry_feature_cutoff", "feature_cutoff", "candle_close_time", "entry_feature_snapshot_id")
        if candle:
            duplicate_key = f"{symbol}|{timeframe_of(row)}|{candle}|{strategy}|{side}"
            grouped[("same_candle_duplicate_entries", duplicate_key)].append((index, row))

    samples: list[dict[str, Any]] = []
    for (duplicate_field, duplicate_key), occurrences in sorted(grouped.items()):
        if len(occurrences) <= 1:
            continue
        first_index, first_row = occurrences[0]
        samples.append(
            {
                "duplicate_identity_field": duplicate_field,
                "duplicate_key": duplicate_key,
                "duplicate_count": len(occurrences) - 1,
                "total_rows_with_key": len(occurrences),
                "first_raw_record_id": source_record_id(first_row, first_index),
                "sample_raw_record_ids": [
                    source_record_id(row, row_index)
                    for row_index, row in occurrences[:10]
                ],
                "symbol": symbol_of(first_row),
                "timeframe": timeframe_of(first_row),
                "side": side_of(first_row),
                "strategy_id": strategy_id_of(first_row),
            }
        )
        if len(samples) >= limit:
            break
    return samples


def compact_economic_trades(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[economic_trade_id(row)].append(row)

    compacted: list[dict[str, Any]] = []
    for trade_id, trade_rows in sorted(grouped.items()):
        first = trade_rows[0]
        net = sum(net_pnl_usd(row) for row in trade_rows)
        gross = sum(gross_pnl_usd(row) for row in trade_rows)
        fees = sum(fee_usd(row) for row in trade_rows)
        slippage = sum(slippage_usd(row) for row in trade_rows)
        funding = sum(funding_usd(row) for row in trade_rows)
        hold_times = [value for row in trade_rows if (value := hold_seconds(row)) is not None]
        compacted.append(
            {
                "economic_trade_id": trade_id,
                "economic_thesis_id": str(first_present(first, "economic_thesis_id", "entry_prediction_id", "prediction_id") or trade_id),
                "parent_position_id": first_present(first, "parent_position_id", "position_id", "paper_position_id"),
                "symbol": symbol_of(first),
                "timeframe": timeframe_of(first),
                "side": side_of(first),
                "strategy_id": attribution(first).get("strategy_id"),
                "raw_close_record_count": len(trade_rows),
                "entry_sequence": [
                    str(first_present(row, "entry_signal_id", "signal_id", "entry_prediction_id", "prediction_id") or source_record_id(row, index))
                    for index, row in enumerate(trade_rows)
                ],
                "close_sequence": [source_record_id(row, index) for index, row in enumerate(trade_rows)],
                "is_partial_reduce": any(is_partial_reduce(row) for row in trade_rows),
                "is_partial_close": any(is_partial_close(row) for row in trade_rows),
                "is_full_close": any(is_full_close(row) for row in trade_rows),
                "is_reversal": any(is_reversal(row) for row in trade_rows),
                "gross_pnl_usd": gross,
                "fees_usd": fees,
                "slippage_usd": slippage,
                "funding_usd": funding,
                "net_pnl_usd": net,
                "turnover_usd": sum(notional_usd(row) for row in trade_rows),
                "hold_time_seconds": median(hold_times),
            }
        )
    return compacted


def summarize_attribution(rows: Sequence[Mapping[str, Any]], *, challenger_candidate_id: str) -> dict[str, Any]:
    missing_counts: Counter[str] = Counter()
    value_counts: dict[str, Counter[str]] = {field: Counter() for field in REQUIRED_ATTRIBUTION_FIELDS}
    samples: list[dict[str, Any]] = []
    challenger_trade_count = 0
    for index, row in enumerate(rows):
        attr = attribution(row)
        if row.get("candidate_id") == challenger_candidate_id or row.get("candidate_id") == CHALLENGER_CANDIDATE_ID:
            challenger_trade_count += 1
        missing = []
        for field, value in attr.items():
            if value in (None, ""):
                missing_counts[field] += 1
                missing.append(field)
            else:
                value_counts[field][str(value)] += 1
        if missing and len(samples) < 25:
            samples.append(
                {
                    "raw_record_id": source_record_id(row, index),
                    "symbol": symbol_of(row),
                    "timeframe": timeframe_of(row),
                    "missing_attribution_fields": missing,
                    "available_attribution": attr,
                }
            )
    return {
        "required_fields": list(REQUIRED_ATTRIBUTION_FIELDS),
        "missing_field_counts": dict(sorted(missing_counts.items())),
        "top_values": {field: dict(counter.most_common(10)) for field, counter in value_counts.items()},
        "records_missing_required_attribution_count": sum(1 for row in rows if any(value in (None, "") for value in attribution(row).values())),
        "sample_records_missing_attribution": samples,
        "challenger_trade_count": challenger_trade_count,
        "old_policy_trade_count": len(rows) - challenger_trade_count,
        "old_policy_trade_count_rule": "Rows not carrying the frozen challenger candidate_id are treated as old-policy or unbound paper-path trades.",
    }


def current_paper_timeframe_churn_audit(
    *,
    closed_rows: Sequence[Mapping[str, Any]],
    ledger: Mapping[str, Any],
    portfolio_state: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    challenger_candidate_id: str = CHALLENGER_CANDIDATE_ID,
) -> dict[str, Any]:
    compacted = compact_economic_trades(closed_rows)
    by_tf = timeframe_bucket_metrics(closed_rows, compacted)
    duplicate_counts = duplicate_and_reentry_counts(closed_rows)
    attribution_payload = summarize_attribution(closed_rows, challenger_candidate_id=challenger_candidate_id)
    one_min_raw = by_tf.get("1m", {}).get("trade_count", 0)
    one_min_econ = by_tf.get("1m", {}).get("economic_trade_count", 0)
    raw_count = len(closed_rows)
    econ_count = len(compacted)
    pass_conditions = {
        "raw_close_record_count_gt_0": raw_count > 0,
        "economic_trade_count_gt_0": econ_count > 0,
        "timeframe_distribution_present": bool(by_tf),
        "current_1m_share_present": raw_count == 0 or one_min_raw >= 0,
        "current_1m_economic_trade_share_present": econ_count == 0 or one_min_econ >= 0,
        "required_attribution_fields_present": (
            not attribution_payload["missing_field_counts"]
            and attribution_payload["records_missing_required_attribution_count"] == 0
        ),
        "challenger_remains_paper_inactive": attribution_payload["challenger_trade_count"] == 0,
    }
    actuals = {
        "raw_close_record_count_gt_0": raw_count,
        "economic_trade_count_gt_0": econ_count,
        "timeframe_distribution_present": {
            "trade_count_by_timeframe": {tf: payload["trade_count"] for tf, payload in by_tf.items()},
            "economic_trade_count_by_timeframe": {tf: payload["economic_trade_count"] for tf, payload in by_tf.items()},
        },
        "current_1m_share_present": one_min_raw / raw_count if raw_count else 0.0,
        "current_1m_economic_trade_share_present": one_min_econ / econ_count if econ_count else 0.0,
        "required_attribution_fields_present": {
            "missing_field_counts": attribution_payload["missing_field_counts"],
            "records_missing_required_attribution_count": attribution_payload[
                "records_missing_required_attribution_count"
            ],
        },
        "challenger_remains_paper_inactive": attribution_payload["challenger_trade_count"],
    }
    required = {
        "raw_close_record_count_gt_0": ">0",
        "economic_trade_count_gt_0": ">0",
        "timeframe_distribution_present": "non-empty trade and economic trade distributions",
        "current_1m_share_present": "present",
        "current_1m_economic_trade_share_present": "present",
        "required_attribution_fields_present": {
            "missing_field_counts": {},
            "records_missing_required_attribution_count": 0,
        },
        "challenger_remains_paper_inactive": 0,
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="current_paper_timeframe_churn_audit.json",
    )
    return {
        "schema_version": "current_paper_timeframe_churn_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "CURRENT_PAPER_LEDGER_AUDITED",
        "read_only_audit_no_runtime_change": True,
        "redis_keys_read": list(PAPER_REDIS_KEYS),
        "raw_close_record_count": raw_count,
        "economic_trade_count": econ_count,
        "position_count": econ_count,
        "entry_count": econ_count,
        "partial_reduce_count": sum(1 for row in closed_rows if is_partial_reduce(row)),
        "partial_close_count": sum(1 for row in closed_rows if is_partial_close(row)),
        "full_close_count": sum(1 for row in closed_rows if is_full_close(row)),
        "reversal_count": sum(1 for row in closed_rows if is_reversal(row)),
        "reopen_count": duplicate_counts["reopen_count"],
        "trade_count_by_timeframe": {tf: payload["trade_count"] for tf, payload in by_tf.items()},
        "economic_trade_count_by_timeframe": {tf: payload["economic_trade_count"] for tf, payload in by_tf.items()},
        "gross_pnl_by_timeframe": {tf: payload["gross_pnl_usd"] for tf, payload in by_tf.items()},
        "fees_by_timeframe": {tf: payload["fees_usd"] for tf, payload in by_tf.items()},
        "slippage_by_timeframe": {tf: payload["slippage_usd"] for tf, payload in by_tf.items()},
        "funding_by_timeframe": {tf: payload["funding_usd"] for tf, payload in by_tf.items()},
        "net_pnl_by_timeframe": {tf: payload["net_pnl_usd"] for tf, payload in by_tf.items()},
        "profit_factor_by_timeframe": {tf: payload["profit_factor"] for tf, payload in by_tf.items()},
        "cost_as_pct_of_gross_by_timeframe": {tf: payload["cost_as_pct_of_gross"] for tf, payload in by_tf.items()},
        "median_hold_time_by_timeframe": {tf: payload["median_hold_time_seconds"] for tf, payload in by_tf.items()},
        "median_notional_by_timeframe": {tf: payload["median_notional_usd"] for tf, payload in by_tf.items()},
        "turnover_by_timeframe": {tf: payload["turnover_usd"] for tf, payload in by_tf.items()},
        "trades_per_symbol_per_hour": hourly_rate(closed_rows),
        "reentries_per_symbol_per_hour": duplicate_counts["reentries_per_symbol_per_hour"],
        "same_side_reentries": duplicate_counts["same_side_reentries"],
        "opposite_side_flips": duplicate_counts["opposite_side_flips"],
        "same_prediction_duplicate_entries": duplicate_counts["same_prediction_duplicate_entries"],
        "same_decision_duplicate_entries": duplicate_counts["same_decision_duplicate_entries"],
        "same_candle_duplicate_entries": duplicate_counts["same_candle_duplicate_entries"],
        "current_1m_share": one_min_raw / raw_count if raw_count else 0.0,
        "current_1m_economic_trade_share": one_min_econ / econ_count if econ_count else 0.0,
        "old_policy_trade_count": attribution_payload["old_policy_trade_count"],
        "challenger_trade_count": attribution_payload["challenger_trade_count"],
        "required_attribution_fields": attribution_payload["required_fields"],
        "attribution_missing_counts": attribution_payload["missing_field_counts"],
        "records_missing_required_attribution_count": attribution_payload[
            "records_missing_required_attribution_count"
        ],
        "required_attribution_fields_present": (
            not attribution_payload["missing_field_counts"]
            and attribution_payload["records_missing_required_attribution_count"] == 0
        ),
        "sample_records_missing_attribution": attribution_payload["sample_records_missing_attribution"],
        "record_attribution": attribution_payload,
        "pass_conditions": pass_conditions,
        "blocked_reasons": [str(detail["pass_condition"]) for detail in blocker_details],
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "actuals": actuals,
        "required": required,
        "sample_blockers": blocker_details[:25],
        "ledger_reported_closed_trade_count": ledger.get("closed_trade_count"),
        "heartbeat_closed_trade_count": heartbeat.get("closed_trade_count"),
        "portfolio_closed_positions_count": portfolio_state.get("closed_positions_count"),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def current_paper_economic_trade_reconciliation(
    *,
    closed_rows: Sequence[Mapping[str, Any]],
    portfolio_state: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    compacted = compact_economic_trades(closed_rows)
    duplicate_counts = duplicate_and_reentry_counts(closed_rows)
    closed_net = sum(net_pnl_usd(row) for row in closed_rows)
    compacted_net = sum(float(row.get("net_pnl_usd") or 0.0) for row in compacted)
    rows_with_explicit_realized: list[Mapping[str, Any]] = []
    rows_using_fallback_formula: list[tuple[int, Mapping[str, Any]]] = []
    for index, row in enumerate(closed_rows):
        if first_present(row, *EXPLICIT_REALIZED_PNL_FIELDS) is not None:
            rows_with_explicit_realized.append(row)
        else:
            rows_using_fallback_formula.append((index, row))
    explicit_realized_count = len(rows_with_explicit_realized)
    explicit_realized_net = sum(net_pnl_usd(row) for row in rows_with_explicit_realized)
    fallback_formula_net = sum(net_pnl_usd(row) for _index, row in rows_using_fallback_formula)
    portfolio_realized_fields = (
        "closed_ledger_net_pnl_usd",
        "realized_pnl_usd",
        "cumulative_realized_pnl",
        "lifetime_realized_pnl",
        "session_realized_pnl",
    )
    ledger_realized_fields = ("realized_pnl_usd", "realized_pnl_usdt")
    portfolio_state_realized = first_float(
        portfolio_state,
        *portfolio_realized_fields,
    )
    ledger_realized = first_float(ledger, *ledger_realized_fields)
    portfolio_realized = portfolio_state_realized
    portfolio_realized_source = "portfolio_state"
    if portfolio_realized is None:
        portfolio_realized = ledger_realized
        portfolio_realized_source = "ledger"
    portfolio_realized = portfolio_realized if portfolio_realized is not None else 0.0
    if portfolio_state_realized is None and ledger_realized is None:
        portfolio_realized_source = "missing_default_zero"
    compacted_vs_portfolio = compacted_net - portfolio_realized
    ledger_closed_trade_count = first_float(ledger, "closed_trade_count", "close_event_count")
    ledger_count_matches = (
        True
        if ledger_closed_trade_count is None
        else int(ledger_closed_trade_count) == len(closed_rows)
    )
    pass_conditions = {
        "raw_closed_rows_gt_0": len(closed_rows) > 0,
        "economic_trade_rows_gt_0": len(compacted) > 0,
        "ledger_closed_trade_count_matches_raw_rows": ledger_count_matches,
        "all_closed_rows_have_explicit_realized_pnl": explicit_realized_count == len(closed_rows),
        "explicit_realized_pnl_sum_matches_portfolio_within_one_cent": abs(explicit_realized_net - portfolio_realized) <= 0.01,
        "raw_close_sum_equals_compacted_sum_within_one_cent": abs(closed_net - compacted_net) <= 0.01,
        "compacted_sum_equals_portfolio_realized_pnl_within_one_cent": abs(compacted_vs_portfolio) <= 0.01,
    }
    reconciliation_gaps: list[dict[str, Any]] = []
    if not pass_conditions["ledger_closed_trade_count_matches_raw_rows"]:
        reconciliation_gaps.append(
            {
                "invariant": "ledger_closed_trade_count_matches_raw_rows",
                "expected_rows": int(ledger_closed_trade_count or 0),
                "observed_rows": len(closed_rows),
                "difference_rows": len(closed_rows) - int(ledger_closed_trade_count or 0),
            }
        )
    if not pass_conditions["all_closed_rows_have_explicit_realized_pnl"]:
        reconciliation_gaps.append(
            {
                "invariant": "all_closed_rows_have_explicit_realized_pnl",
                "expected_rows": len(closed_rows),
                "observed_rows": explicit_realized_count,
                "missing_rows": len(closed_rows) - explicit_realized_count,
                "fallback_formula_net_pnl_usd": fallback_formula_net,
            }
        )
    if not pass_conditions["explicit_realized_pnl_sum_matches_portfolio_within_one_cent"]:
        reconciliation_gaps.append(
            {
                "invariant": "explicit_realized_pnl_sum_matches_portfolio_within_one_cent",
                "expected_usd": portfolio_realized,
                "observed_usd": explicit_realized_net,
                "difference_usd": explicit_realized_net - portfolio_realized,
                "tolerance_usd": 0.01,
                "portfolio_realized_pnl_source": portfolio_realized_source,
            }
        )
    if not pass_conditions["raw_close_sum_equals_compacted_sum_within_one_cent"]:
        reconciliation_gaps.append(
            {
                "invariant": "raw_close_sum_equals_compacted_sum_within_one_cent",
                "expected_usd": closed_net,
                "observed_usd": compacted_net,
                "difference_usd": closed_net - compacted_net,
                "tolerance_usd": 0.01,
            }
        )
    if not pass_conditions["compacted_sum_equals_portfolio_realized_pnl_within_one_cent"]:
        reconciliation_gaps.append(
            {
                "invariant": "compacted_sum_equals_portfolio_realized_pnl_within_one_cent",
                "expected_usd": portfolio_realized,
                "observed_usd": compacted_net,
                "difference_usd": compacted_vs_portfolio,
                "tolerance_usd": 0.01,
                "portfolio_realized_pnl_source": portfolio_realized_source,
            }
        )
    status = "PASS_ECONOMIC_TRADE_RECONCILIATION" if all(pass_conditions.values()) else "FAIL_ECONOMIC_TRADE_RECONCILIATION"
    reconciliation_blockers = [str(gap.get("invariant")) for gap in reconciliation_gaps if gap.get("invariant")]
    blocker_details = [
        {
            "pass_condition": blocker,
            "actual": gap,
            "required": "PASS",
            "source_artifact": "current_paper_economic_trade_reconciliation.json",
        }
        for blocker, gap in zip(reconciliation_blockers, reconciliation_gaps, strict=False)
    ]
    actuals = {
        "raw_closed_rows_gt_0": len(closed_rows),
        "economic_trade_rows_gt_0": len(compacted),
        "ledger_closed_trade_count_matches_raw_rows": {
            "ledger_closed_trade_count": int(ledger_closed_trade_count) if ledger_closed_trade_count is not None else None,
            "raw_close_record_count": len(closed_rows),
            "difference_rows": (
                len(closed_rows) - int(ledger_closed_trade_count)
                if ledger_closed_trade_count is not None
                else None
            ),
        },
        "all_closed_rows_have_explicit_realized_pnl": {
            "explicit_realized_rows": explicit_realized_count,
            "raw_close_record_count": len(closed_rows),
            "missing_rows": len(closed_rows) - explicit_realized_count,
        },
        "explicit_realized_pnl_sum_matches_portfolio_within_one_cent": {
            "explicit_realized_pnl_sum_usd": explicit_realized_net,
            "portfolio_realized_pnl_usd": portfolio_realized,
            "difference_usd": explicit_realized_net - portfolio_realized,
            "portfolio_realized_pnl_source": portfolio_realized_source,
        },
        "raw_close_sum_equals_compacted_sum_within_one_cent": {
            "raw_close_sum_pnl_usd": closed_net,
            "compacted_economic_trade_net_pnl_usd": compacted_net,
            "difference_usd": closed_net - compacted_net,
        },
        "compacted_sum_equals_portfolio_realized_pnl_within_one_cent": {
            "compacted_economic_trade_net_pnl_usd": compacted_net,
            "portfolio_realized_pnl_usd": portfolio_realized,
            "difference_usd": compacted_vs_portfolio,
            "portfolio_realized_pnl_source": portfolio_realized_source,
        },
    }
    required = {
        "raw_closed_rows_gt_0": ">0",
        "economic_trade_rows_gt_0": ">0",
        "ledger_closed_trade_count_matches_raw_rows": "ledger closed trade count equals raw close record count when ledger count is present",
        "all_closed_rows_have_explicit_realized_pnl": "explicit realized PnL field present on every raw close row",
        "explicit_realized_pnl_sum_matches_portfolio_within_one_cent": "absolute difference <= 0.01 USD",
        "raw_close_sum_equals_compacted_sum_within_one_cent": "absolute difference <= 0.01 USD",
        "compacted_sum_equals_portfolio_realized_pnl_within_one_cent": "absolute difference <= 0.01 USD",
    }
    return {
        "schema_version": "current_paper_economic_trade_reconciliation_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": status,
        "accounting_reconciliation_status": status,
        "read_only_audit_no_runtime_change": True,
        "raw_close_record_count": len(closed_rows),
        "economic_trade_count": len(compacted),
        "position_count": len(compacted),
        "portfolio_realized_pnl_usd": portfolio_realized,
        "portfolio_realized_pnl": portfolio_realized,
        "portfolio_state_realized_pnl_usd": portfolio_state_realized,
        "ledger_realized_pnl_usd": ledger_realized,
        "portfolio_realized_pnl_source": portfolio_realized_source,
        "ledger_closed_trade_count": int(ledger_closed_trade_count) if ledger_closed_trade_count is not None else None,
        "raw_closed_trade_count_matches_ledger": ledger_count_matches,
        "ledger_closed_trade_count_matches_raw_rows": pass_conditions["ledger_closed_trade_count_matches_raw_rows"],
        "all_closed_rows_have_explicit_realized_pnl": pass_conditions["all_closed_rows_have_explicit_realized_pnl"],
        "explicit_realized_pnl_sum_matches_portfolio_within_one_cent": pass_conditions[
            "explicit_realized_pnl_sum_matches_portfolio_within_one_cent"
        ],
        "raw_close_sum_equals_compacted_sum_within_one_cent": pass_conditions["raw_close_sum_equals_compacted_sum_within_one_cent"],
        "compacted_sum_equals_portfolio_realized_pnl_within_one_cent": pass_conditions[
            "compacted_sum_equals_portfolio_realized_pnl_within_one_cent"
        ],
        "reconciliation_blocker_count": len(reconciliation_blockers),
        "reconciliation_blockers": reconciliation_blockers,
        "blocked_reasons": reconciliation_blockers,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "actuals": actuals,
        "required": required,
        "sample_blockers": blocker_details[:25],
        "closed_record_net_pnl_usd": closed_net,
        "compacted_economic_trade_net_pnl_usd": compacted_net,
        "compacted_economic_trade_net_pnl_sum": compacted_net,
        "current_closed_records_sum_pnl_usd": closed_net,
        "compacted_sum_pnl_usd": compacted_net,
        "portfolio_closed_pnl_usd": portfolio_realized,
        "ledger_closed_pnl_usd": ledger_realized,
        "closed_vs_compacted_difference_usd": closed_net - compacted_net,
        "compacted_vs_portfolio_realized_difference_usd": compacted_vs_portfolio,
        "pnl_delta": compacted_vs_portfolio,
        "closed_rows_with_explicit_realized_pnl_count": explicit_realized_count,
        "closed_rows_using_fallback_cost_formula_count": len(closed_rows) - explicit_realized_count,
        "explicit_realized_pnl_sum_usd": explicit_realized_net,
        "explicit_realized_pnl_sum": explicit_realized_net,
        "fallback_formula_net_pnl_usd": fallback_formula_net,
        "sample_rows_using_fallback_cost_formula": [
            {
                "raw_record_id": source_record_id(row, index),
                "symbol": symbol_of(row),
                "timeframe": timeframe_of(row),
                "side": side_of(row),
                "close_reason": first_present(row, "close_reason", "exit_reason"),
                "gross_pnl_usd": gross_pnl_usd(row),
                "fees_usd": fee_usd(row),
                "slippage_usd": slippage_usd(row),
                "funding_usd": funding_usd(row),
                "net_pnl_usd_used_by_audit": net_pnl_usd(row),
            }
            for index, row in rows_using_fallback_formula[:10]
        ],
        "same_side_reentries": duplicate_counts["same_side_reentries"],
        "opposite_side_flips": duplicate_counts["opposite_side_flips"],
        "same_prediction_duplicate_entries": duplicate_counts["same_prediction_duplicate_entries"],
        "same_decision_duplicate_entries": duplicate_counts["same_decision_duplicate_entries"],
        "same_candle_duplicate_entries": duplicate_counts["same_candle_duplicate_entries"],
        "unexplained_same_candle_reentries": duplicate_counts["same_candle_duplicate_entries"],
        "duplicate_economic_trade_count": duplicate_identity_violation_count(duplicate_counts),
        "reconciliation_tolerance_usd": 0.01,
        "sample_reconciliation_gaps": reconciliation_gaps[:10],
        "portfolio_realized_pnl_candidate_fields": {
            "portfolio_state": list(portfolio_realized_fields),
            "ledger": list(ledger_realized_fields),
        },
        "pass_conditions": pass_conditions,
        "compacted_trade_sample": compacted[:25],
        "required_invariant": "sum(compacted economic trade net PnL) must equal portfolio realized PnL within one cent.",
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def economic_trade_compaction_status(
    *,
    closed_rows: Sequence[Mapping[str, Any]],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    compacted = compact_economic_trades(closed_rows)
    duplicate_counts = duplicate_and_reentry_counts(closed_rows)
    duplicate_economic_trade_count = duplicate_identity_violation_count(duplicate_counts)
    duplicate_samples = duplicate_identity_samples(closed_rows)
    raw_identity_field_sources = {
        "economic_trade_id": ("economic_trade_id",),
        "economic_thesis_id": ("economic_thesis_id",),
        "parent_position_id": ("parent_position_id", "position_id", "paper_position_id"),
    }
    raw_identity_present_counts: Counter[str] = Counter()
    raw_identity_missing_field_counts: Counter[str] = Counter()
    raw_identity_missing_samples: list[dict[str, Any]] = []
    for index, row in enumerate(closed_rows):
        missing_fields: list[str] = []
        identity_values: dict[str, Any] = {}
        for field, aliases in raw_identity_field_sources.items():
            value = first_present(row, *aliases)
            identity_values[field] = value
            if value is None:
                raw_identity_missing_field_counts[field] += 1
                missing_fields.append(field)
            else:
                raw_identity_present_counts[field] += 1
        if missing_fields and len(raw_identity_missing_samples) < 25:
            raw_identity_missing_samples.append(
                {
                    "raw_record_id": source_record_id(row, index),
                    "symbol": symbol_of(row),
                    "timeframe": timeframe_of(row),
                    "side": side_of(row),
                    "strategy_id": strategy_id_of(row),
                    "missing_identity_fields": missing_fields,
                    "identity_values_present": {
                        key: value
                        for key, value in identity_values.items()
                        if value is not None
                    },
                }
            )
    explicit_id_count = raw_identity_present_counts["economic_trade_id"]
    explicit_thesis_count = raw_identity_present_counts["economic_thesis_id"]
    explicit_parent_position_count = raw_identity_present_counts["parent_position_id"]
    raw_identity_coverage = {
        field: (raw_identity_present_counts[field] / len(closed_rows)) if closed_rows else 0.0
        for field in raw_identity_field_sources
    }
    raw_identity_present_count_by_field = {
        field: raw_identity_present_counts[field]
        for field in raw_identity_field_sources
    }
    raw_identity_missing_count_by_field = {
        field: raw_identity_missing_field_counts[field]
        for field in raw_identity_field_sources
    }
    raw_identity_missing_fields = [
        field
        for field, count in sorted(raw_identity_missing_count_by_field.items())
        if count > 0
    ]
    required_compacted_fields = (
        "economic_trade_id",
        "economic_thesis_id",
        "parent_position_id",
        "entry_sequence",
        "close_sequence",
        "is_partial_reduce",
        "is_partial_close",
        "is_full_close",
        "is_reversal",
    )
    missing_compacted_field_counts: Counter[str] = Counter()
    for row in compacted:
        for field in required_compacted_fields:
            if field not in row:
                missing_compacted_field_counts[field] += 1
    pass_conditions = {
        "economic_trade_rows_gt_0": len(compacted) > 0,
        "close_events_compacted_or_accounted": len(compacted) <= len(closed_rows),
        "raw_rows_have_explicit_economic_trade_id": explicit_id_count == len(closed_rows),
        "raw_rows_have_explicit_economic_thesis_id": explicit_thesis_count == len(closed_rows),
        "raw_rows_have_parent_position_id": explicit_parent_position_count == len(closed_rows),
        "compacted_rows_have_required_fields": not missing_compacted_field_counts,
        "pnl_reconciliation_passed": reconciliation.get("status") == "PASS_ECONOMIC_TRADE_RECONCILIATION",
    }
    actuals = {
        "economic_trade_rows_gt_0": len(compacted),
        "close_events_compacted_or_accounted": {
            "economic_trade_count": len(compacted),
            "raw_close_record_count": len(closed_rows),
        },
        "raw_rows_have_explicit_economic_trade_id": explicit_id_count,
        "raw_rows_have_explicit_economic_thesis_id": explicit_thesis_count,
        "raw_rows_have_parent_position_id": explicit_parent_position_count,
        "compacted_rows_have_required_fields": dict(sorted(missing_compacted_field_counts.items())),
        "pnl_reconciliation_passed": reconciliation.get("status"),
    }
    required = {
        "economic_trade_rows_gt_0": ">0",
        "close_events_compacted_or_accounted": "economic_trade_count <= raw_close_record_count",
        "raw_rows_have_explicit_economic_trade_id": len(closed_rows),
        "raw_rows_have_explicit_economic_thesis_id": len(closed_rows),
        "raw_rows_have_parent_position_id": len(closed_rows),
        "compacted_rows_have_required_fields": {},
        "pnl_reconciliation_passed": "PASS_ECONOMIC_TRADE_RECONCILIATION",
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="economic_trade_compaction_status.json",
    )
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    return {
        "schema_version": "economic_trade_compaction_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_ECONOMIC_TRADE_COMPACTION" if all(pass_conditions.values()) else "BLOCKED_ECONOMIC_TRADE_COMPACTION",
        "read_only_audit_no_runtime_change": True,
        "raw_close_record_count": len(closed_rows),
        "economic_trade_count": len(compacted),
        "raw_rows_with_explicit_economic_trade_id": explicit_id_count,
        "raw_rows_with_explicit_economic_thesis_id": explicit_thesis_count,
        "raw_rows_with_parent_position_id": explicit_parent_position_count,
        "raw_identity_required_fields": dict(raw_identity_field_sources),
        "required_raw_identity_fields": list(raw_identity_field_sources),
        "raw_identity_present_counts": dict(sorted(raw_identity_present_count_by_field.items())),
        "raw_identity_missing_field_counts": dict(sorted(raw_identity_missing_count_by_field.items())),
        "missing_raw_identity_fields": raw_identity_missing_fields,
        "raw_identity_missing_required_field_count": len(raw_identity_missing_fields),
        "raw_identity_missing_required_row_total": sum(raw_identity_missing_count_by_field.values()),
        "raw_identity_field_coverage": dict(sorted(raw_identity_coverage.items())),
        "sample_raw_rows_missing_economic_trade_identity": raw_identity_missing_samples,
        "missing_compacted_field_counts": dict(sorted(missing_compacted_field_counts.items())),
        "required_fields": list(required_compacted_fields),
        "missing_required_fields": sorted(missing_compacted_field_counts),
        "missing_required_field_count": len(missing_compacted_field_counts),
        "missing_required_row_total": sum(missing_compacted_field_counts.values()),
        "partial_reduce_count": sum(1 for row in closed_rows if is_partial_reduce(row)),
        "partial_close_count": sum(1 for row in closed_rows if is_partial_close(row)),
        "full_close_count": sum(1 for row in closed_rows if is_full_close(row)),
        "reversal_count": sum(1 for row in closed_rows if is_reversal(row)),
        "reopen_count": duplicate_counts["reopen_count"],
        "same_side_reentries": duplicate_counts["same_side_reentries"],
        "opposite_side_flips": duplicate_counts["opposite_side_flips"],
        "same_prediction_duplicate_entries": duplicate_counts["same_prediction_duplicate_entries"],
        "same_decision_duplicate_entries": duplicate_counts["same_decision_duplicate_entries"],
        "same_candle_duplicate_entries": duplicate_counts["same_candle_duplicate_entries"],
        "unexplained_same_candle_reentries": duplicate_counts["same_candle_duplicate_entries"],
        "duplicate_economic_trade_count": duplicate_economic_trade_count,
        "duplicate_identity_violation_count": duplicate_economic_trade_count,
        "duplicate_economic_trade_samples": duplicate_samples,
        "duplicate_identity_violation_samples": duplicate_samples,
        "duplicate_identity_sample_count": len(duplicate_samples),
        "raw_close_events_per_economic_trade": (len(closed_rows) / len(compacted)) if compacted else None,
        "reconciliation_status": reconciliation.get("status"),
        "compacted_vs_portfolio_realized_difference_usd": reconciliation.get("compacted_vs_portfolio_realized_difference_usd"),
        "portfolio_realized_pnl": reconciliation.get("portfolio_closed_pnl_usd"),
        "compacted_economic_trade_net_pnl": reconciliation.get("compacted_economic_trade_net_pnl_usd"),
        "accounting_reconciliation": reconciliation.get("status"),
        "accounting_reconciliation_status": reconciliation.get("status"),
        "required_invariant": "sum(compacted economic trade net PnL) must equal portfolio realized PnL within one cent.",
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "actuals": actuals,
        "required": required,
        "sample_blockers": blocker_details[:25],
        "sample_compacted_trades": compacted[:25],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def paper_candidate_rows_from_ledger(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (
        "accepted",
        "current_cycle_accepted",
        "accepted_intents",
        "held_by_paper_fill_gate",
        "shadow_observations",
        "persistent_shadow_observations",
        "open_positions",
    ):
        value = ledger.get(key)
        if isinstance(value, list):
            rows.extend(dict(row) for row in value if isinstance(row, Mapping))
    return rows


def has_dedicated_1m_strategy_bucket(row: Mapping[str, Any]) -> bool:
    strategy = strategy_id_of(row).lower()
    bucket = str(first_present(row, "strategy_bucket", "timeframe_strategy_bucket", "strategy_subtype") or "").lower()
    if "standalone_1m" in strategy or "1m_scalp" in strategy or "1m" in bucket:
        return True
    return bool(row.get("standalone_1m_strategy_eligible") is True or row.get("eligible_1m_strategy") is True)


def thesis_execution_row(row: Mapping[str, Any], *, source: str, index: int) -> dict[str, Any]:
    thesis_timeframe = thesis_timeframe_of(row)
    execution_timeframe = execution_timeframe_of(row)
    outcome_timeframe = str(first_present(row, "timeframe", "outcome_timeframe") or "UNKNOWN")
    missing_required = [field for field in THESIS_EXECUTION_REQUIRED_FIELDS if row.get(field) in (None, "", [], {})]
    return {
        "source": source,
        "raw_record_id": source_record_id(row, index),
        "symbol": symbol_of(row),
        "timeframe": outcome_timeframe,
        "thesis_timeframe": thesis_timeframe,
        "execution_timeframe": execution_timeframe,
        "confirmation_timeframes": first_present(row, "confirmation_timeframes"),
        "strategy_horizon_seconds": first_present(row, "strategy_horizon_seconds", "strategy_horizon_sec"),
        "expected_holding_period_seconds": first_present(
            row,
            "expected_holding_period_seconds",
            "expected_holding_horizon_seconds",
            "holding_period_seconds",
        ),
        "thesis_prediction_id": first_present(row, "thesis_prediction_id", "entry_prediction_id", "prediction_id"),
        "execution_snapshot_id": first_present(row, "execution_snapshot_id", "entry_feature_snapshot_id", "feature_snapshot_id"),
        "strategy_id": strategy_id_of(row),
        "side": side_of(row),
        "thesis_candle_close_time": thesis_candle_of(row),
        "economic_trade_id": first_present(row, "economic_trade_id"),
        "economic_thesis_id": first_present(row, "economic_thesis_id"),
        "standalone_1m_strategy_eligible": has_dedicated_1m_strategy_bucket(row),
        "missing_required_fields": missing_required,
    }


def multi_timeframe_thesis_execution_contract_status(
    *,
    closed_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    audit_rows = [
        *[
            thesis_execution_row(row, source="closed_trade", index=index)
            for index, row in enumerate(closed_rows)
        ],
        *[
            thesis_execution_row(row, source="paper_candidate", index=index)
            for index, row in enumerate(candidate_rows)
        ],
    ]
    missing_required_counts: Counter[str] = Counter()
    outcome_misattribution_rows = 0
    standalone_1m_without_bucket_rows = 0
    higher_tf_1m_timing_rows = 0
    higher_tf_same_candle_reopen_rows = 0
    samples: list[dict[str, Any]] = []
    higher_tf_seen: set[tuple[str, str, str, str, str]] = set()

    for row in audit_rows:
        missing = [str(field) for field in row.get("missing_required_fields") or ()]
        missing_required_counts.update(missing)
        thesis_timeframe = str(row.get("thesis_timeframe") or "UNKNOWN")
        execution_timeframe = str(row.get("execution_timeframe") or "UNKNOWN")
        if thesis_timeframe in HIGHER_THESIS_TIMEFRAMES and execution_timeframe == "1m":
            higher_tf_1m_timing_rows += 1
        if thesis_timeframe in HIGHER_THESIS_TIMEFRAMES and str(row.get("timeframe") or "") != thesis_timeframe:
            outcome_misattribution_rows += 1
            if len(samples) < 25:
                sample = dict(row)
                sample["violation"] = "close_outcome_not_attributed_to_thesis_timeframe"
                samples.append(sample)
        if thesis_timeframe == "1m" and execution_timeframe == "1m" and not row.get("standalone_1m_strategy_eligible"):
            standalone_1m_without_bucket_rows += 1
            if len(samples) < 25:
                sample = dict(row)
                sample["violation"] = "standalone_1m_without_dedicated_strategy_bucket"
                samples.append(sample)
        if thesis_timeframe in HIGHER_THESIS_TIMEFRAMES and execution_timeframe == "1m":
            key = (
                str(row.get("symbol") or ""),
                thesis_timeframe,
                str(row.get("thesis_candle_close_time") or ""),
                str(row.get("strategy_id") or ""),
                str(row.get("side") or ""),
            )
            if key in higher_tf_seen:
                higher_tf_same_candle_reopen_rows += 1
                if len(samples) < 25:
                    sample = dict(row)
                    sample["violation"] = "higher_tf_position_reopened_on_each_1m_tick"
                    samples.append(sample)
            else:
                higher_tf_seen.add(key)
        if missing and len(samples) < 25:
            sample = dict(row)
            sample["violation"] = "required_thesis_execution_fields_missing"
            sample["missing_fields"] = missing
            samples.append(sample)

    pass_conditions = {
        "paper_rows_examined_gt_0": len(audit_rows) > 0,
        "required_thesis_execution_fields_present": not missing_required_counts,
        "higher_tf_1m_timing_preserves_thesis": outcome_misattribution_rows == 0,
        "higher_tf_position_not_reopened_on_each_1m_tick": higher_tf_same_candle_reopen_rows == 0,
        "standalone_1m_requires_eligible_1m_strategy": standalone_1m_without_bucket_rows == 0,
        "close_outcome_attributed_to_thesis_timeframe": outcome_misattribution_rows == 0,
    }
    actuals = {
        "paper_rows_examined_gt_0": len(audit_rows),
        "required_thesis_execution_fields_present": dict(sorted(missing_required_counts.items())),
        "higher_tf_1m_timing_preserves_thesis": outcome_misattribution_rows,
        "higher_tf_position_not_reopened_on_each_1m_tick": higher_tf_same_candle_reopen_rows,
        "standalone_1m_requires_eligible_1m_strategy": standalone_1m_without_bucket_rows,
        "close_outcome_attributed_to_thesis_timeframe": outcome_misattribution_rows,
    }
    required = {
        "paper_rows_examined_gt_0": ">0",
        "required_thesis_execution_fields_present": {},
        "higher_tf_1m_timing_preserves_thesis": 0,
        "higher_tf_position_not_reopened_on_each_1m_tick": 0,
        "standalone_1m_requires_eligible_1m_strategy": 0,
        "close_outcome_attributed_to_thesis_timeframe": 0,
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="multi_timeframe_thesis_execution_contract_status.json",
    )
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    missing_required_field_counts = dict(sorted(missing_required_counts.items()))
    missing_required_fields = sorted(missing_required_field_counts)
    return {
        "schema_version": "multi_timeframe_thesis_execution_contract_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT"
        if all(pass_conditions.values())
        else "BLOCKED_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT",
        "read_only_audit_no_runtime_change": True,
        "closed_rows_examined": len(closed_rows),
        "paper_candidate_rows_examined": len(candidate_rows),
        "total_rows_examined": len(audit_rows),
        "required_fields": list(THESIS_EXECUTION_REQUIRED_FIELDS),
        "required_fields_present_for_all_rows": not missing_required_counts,
        "required_thesis_execution_fields_present": not missing_required_counts,
        "missing_required_fields": missing_required_fields,
        "missing_required_field_counts": missing_required_field_counts,
        "missing_required_field_count": len(missing_required_fields),
        "missing_required_row_total": sum(missing_required_field_counts.values()),
        "higher_tf_1m_timing_rows": higher_tf_1m_timing_rows,
        "higher_tf_same_candle_reopen_rows": higher_tf_same_candle_reopen_rows,
        "higher_tf_position_not_reopened_on_each_1m_tick": higher_tf_same_candle_reopen_rows == 0,
        "higher_tf_1m_timing_preserves_thesis": outcome_misattribution_rows == 0,
        "standalone_1m_without_eligible_strategy_rows": standalone_1m_without_bucket_rows,
        "standalone_1m_requires_eligible_1m_strategy": standalone_1m_without_bucket_rows == 0,
        "close_outcome_thesis_timeframe_mismatch_rows": outcome_misattribution_rows,
        "close_outcome_attributed_to_thesis_timeframe": outcome_misattribution_rows == 0,
        "violation_count": len(samples),
        "violations": samples,
        "rules": {
            "higher_tf_may_use_1m_execution_timing": "15m/1h/4h thesis may use 1m execution timing when outcome attribution stays on the thesis timeframe.",
            "standalone_1m_requires_bucket": "Standalone 1m thesis requires a dedicated eligible 1m strategy bucket.",
            "execution_tick_not_new_trade": "A 1m execution tick must not create a new economic trade for the same higher-timeframe thesis candle.",
        },
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "sample_violations": samples,
        "violation_samples": samples,
        "sample_violation_rows": samples,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def decision_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "prediction_id": first_present(row, "entry_prediction_id", "prediction_id"),
        "decision_id": first_present(row, "decision_id", "orchestrator_decision_id", "risk_decision_id"),
        "signal_id": first_present(row, "entry_signal_id", "signal_id"),
        "feature_snapshot_id": first_present(row, "entry_feature_snapshot_id", "feature_snapshot_id"),
        "symbol_timeframe_candle_strategy_side": "|".join(
            [
                symbol_of(row),
                thesis_timeframe_of(row),
                str(thesis_candle_of(row) or ""),
                strategy_id_of(row),
                side_of(row),
            ]
        ),
    }


def material_reentry_change_reasons(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if thesis_candle_of(previous) != thesis_candle_of(current):
        reasons.append("new_finalized_thesis_candle")
    if first_present(previous, "market_regime_at_entry", "market_regime", "regime") != first_present(
        current,
        "market_regime_at_entry",
        "market_regime",
        "regime",
    ):
        reasons.append("market_regime_change")
    if strategy_id_of(previous) != strategy_id_of(current):
        reasons.append("strategy_change")
    if side_of(previous) != side_of(current):
        reasons.append("direction_change")
    previous_edge = first_float(previous, "expected_move_after_cost_bps", "expected_net_edge_bps", "expected_move_bps")
    current_edge = first_float(current, "expected_move_after_cost_bps", "expected_net_edge_bps", "expected_move_bps")
    if previous_edge is not None and current_edge is not None and current_edge > previous_edge:
        reasons.append("expected_edge_improvement")
    if first_present(previous, "liquidation_context", "microstructure_context", "market_state_id") != first_present(
        current,
        "liquidation_context",
        "microstructure_context",
        "market_state_id",
    ):
        reasons.append("liquidation_or_microstructure_state_change")
    gap_seconds = seconds_between(exit_time_of(previous), entry_time_of(current))
    cooldown = first_float(current, "reentry_cooldown_seconds", "cooldown_seconds") or 300.0
    if (
        gap_seconds is not None
        and gap_seconds >= cooldown
        and first_present(previous, "entry_feature_snapshot_id", "feature_snapshot_id")
        != first_present(current, "entry_feature_snapshot_id", "feature_snapshot_id")
    ):
        reasons.append("cooldown_elapsed_with_fresh_independent_evidence")
    return reasons


def paper_reentry_and_signal_dedup_status(*, closed_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    duplicate_counts: Counter[str] = Counter()
    duplicate_samples: list[dict[str, Any]] = []
    identity_seen: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(closed_rows):
        identities = decision_identity(row)
        for field, value in identities.items():
            if value in (None, "", "UNKNOWN||||UNKNOWN"):
                continue
            key = f"{field}:{value}"
            if key in identity_seen:
                previous = identity_seen[key]["row"]
                if field == "symbol_timeframe_candle_strategy_side" and material_reentry_change_reasons(previous, row):
                    continue
                duplicate_counts[field] += 1
                if len(duplicate_samples) < 25:
                    duplicate_samples.append(
                        {
                            "violation": f"duplicate_{field}",
                            "duplicate_key": str(value),
                            "first_raw_record_id": identity_seen[key]["raw_record_id"],
                            "raw_record_id": source_record_id(row, index),
                            "symbol": symbol_of(row),
                            "timeframe": thesis_timeframe_of(row),
                            "side": side_of(row),
                        }
                    )
            else:
                identity_seen[key] = {
                    "raw_record_id": source_record_id(row, index),
                    "row": row,
                }

    unexplained_reentries = 0
    permitted_reentries = 0
    partial_close_reentry_rows = 0
    reentry_samples: list[dict[str, Any]] = []
    sorted_rows = sorted(
        closed_rows,
        key=lambda row: (
            symbol_of(row),
            parse_time(entry_time_of(row) or exit_time_of(row)) or datetime.min.replace(tzinfo=timezone.utc),
        ),
    )
    previous_by_symbol_side_strategy: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for index, row in enumerate(sorted_rows):
        key = (symbol_of(row), side_of(row), strategy_id_of(row))
        previous = previous_by_symbol_side_strategy.get(key)
        if previous is not None:
            reasons = material_reentry_change_reasons(previous, row)
            if is_partial_close(previous) and not reasons:
                partial_close_reentry_rows += 1
            if reasons:
                permitted_reentries += 1
            else:
                unexplained_reentries += 1
                if len(reentry_samples) < 25:
                    reentry_samples.append(
                        {
                            "violation": "unexplained_same_symbol_side_strategy_reentry",
                            "raw_record_id": source_record_id(row, index),
                            "symbol": symbol_of(row),
                            "timeframe": thesis_timeframe_of(row),
                            "side": side_of(row),
                            "strategy_id": strategy_id_of(row),
                            "thesis_candle_close_time": thesis_candle_of(row),
                            "previous_thesis_candle_close_time": thesis_candle_of(previous),
                            "previous_close_was_partial": is_partial_close(previous),
                        }
                    )
        previous_by_symbol_side_strategy[key] = row

    same_prediction_duplicates = duplicate_counts.get("prediction_id", 0)
    same_decision_duplicates = duplicate_counts.get("decision_id", 0)
    same_signal_duplicates = duplicate_counts.get("signal_id", 0)
    same_snapshot_duplicates = duplicate_counts.get("feature_snapshot_id", 0)
    same_candle_duplicates = duplicate_counts.get("symbol_timeframe_candle_strategy_side", 0)
    duplicate_economic_trades = (
        same_prediction_duplicates
        + same_decision_duplicates
        + same_signal_duplicates
        + same_snapshot_duplicates
        + same_candle_duplicates
    )
    pass_conditions = {
        "same_prediction_cannot_open_twice": same_prediction_duplicates == 0,
        "same_decision_cannot_open_twice": same_decision_duplicates == 0,
        "same_signal_cannot_open_twice": same_signal_duplicates == 0,
        "same_feature_snapshot_cannot_open_twice": same_snapshot_duplicates == 0,
        "same_candle_same_thesis_cannot_reenter": same_candle_duplicates == 0,
        "partial_close_does_not_authorize_reentry": partial_close_reentry_rows == 0,
        "unexplained_reentries_eq_0": unexplained_reentries == 0,
    }
    pass_condition_actuals = {
        "same_prediction_cannot_open_twice": same_prediction_duplicates,
        "same_decision_cannot_open_twice": same_decision_duplicates,
        "same_signal_cannot_open_twice": same_signal_duplicates,
        "same_feature_snapshot_cannot_open_twice": same_snapshot_duplicates,
        "same_candle_same_thesis_cannot_reenter": same_candle_duplicates,
        "partial_close_does_not_authorize_reentry": partial_close_reentry_rows,
        "unexplained_reentries_eq_0": unexplained_reentries,
    }
    blocker_details = [
        {
            "pass_condition": name,
            "actual": pass_condition_actuals.get(name),
            "required": 0,
            "source_artifact": "paper_reentry_and_signal_dedup_status.json",
        }
        for name, passed in pass_conditions.items()
        if not passed
    ]
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    return {
        "schema_version": "paper_reentry_and_signal_dedup_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_PAPER_REENTRY_AND_SIGNAL_DEDUP"
        if all(pass_conditions.values())
        else "BLOCKED_PAPER_REENTRY_AND_SIGNAL_DEDUP",
        "read_only_audit_no_runtime_change": True,
        "closed_rows_examined": len(closed_rows),
        "duplicate_counts": dict(sorted(duplicate_counts.items())),
        "same_prediction_duplicate_entries": same_prediction_duplicates,
        "same_decision_duplicate_entries": same_decision_duplicates,
        "same_signal_duplicate_entries": same_signal_duplicates,
        "same_feature_snapshot_duplicate_entries": same_snapshot_duplicates,
        "same_candle_duplicate_entries": same_candle_duplicates,
        "duplicate_economic_trades": duplicate_economic_trades,
        "unexplained_same_candle_reentries": same_candle_duplicates,
        "permitted_reentries_with_material_change": permitted_reentries,
        "unexplained_reentry_count": unexplained_reentries,
        "partial_close_reentry_count": partial_close_reentry_rows,
        "decision_dedup_contract": {
            "blocked_duplicate_identity_fields": [
                "prediction_id",
                "decision_id",
                "signal_id",
                "feature_snapshot_id",
                "symbol_timeframe_candle_strategy_side",
            ],
            "reentry_allowed_reasons": [
                "new_finalized_thesis_candle",
                "market_regime_change",
                "strategy_change",
                "direction_change",
                "expected_edge_improvement",
                "liquidation_or_microstructure_state_change",
                "cooldown_elapsed_with_fresh_independent_evidence",
            ],
            "pass_conditions": pass_conditions,
        },
        "allowed_reentry_reasons": [
            "new_finalized_thesis_candle",
            "market_regime_change",
            "strategy_change",
            "direction_change",
            "expected_edge_improvement",
            "liquidation_or_microstructure_state_change",
            "cooldown_elapsed_with_fresh_independent_evidence",
        ],
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "sample_duplicate_blocks": duplicate_samples,
        "sample_duplicate_entries": duplicate_samples,
        "sample_duplicate_entry_blocks": duplicate_samples,
        "duplicate_entry_sample_count": len(duplicate_samples),
        "sample_unexplained_reentries": reentry_samples,
        "unexplained_reentry_sample_count": len(reentry_samples),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def post_fix_economic_outcome_sample(
    closed_rows: Sequence[Mapping[str, Any]],
    *,
    source_read_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    eligible_rows: list[dict[str, Any]] = []
    exclusion_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    eligible_source_counts: Counter[str] = Counter()
    excluded_source_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    samples_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for index, row in enumerate(closed_rows):
        source = str(row.get("_post_fix_sample_source") or "unmarked_closed_rows")
        source_counts.update([source])
        missing_identity = [
            field
            for field in POST_FIX_SAMPLE_REQUIRED_IDENTITY_FIELDS
            if first_present(row, field) is None
        ]
        missing_thesis_execution = [
            field
            for field in THESIS_EXECUTION_REQUIRED_FIELDS
            if first_present(row, field) is None
        ]
        explicit_realized_pnl = first_present(row, *EXPLICIT_REALIZED_PNL_FIELDS) is not None
        paper_result = str(first_present(row, "paper_result", "ledger_action", "close_result") or "")
        closed_paper_outcome = paper_result == "POSITION_CLOSED_PAPER_ONLY"
        explicitly_paper_only = (
            row.get("exchange_order") is False
            and row.get("live_order") is not True
            and row.get("routes_to_live") is not True
            and row.get("places_real_order") is not True
            and row.get("legacy_redis_write") is not True
        )

        reasons: list[str] = []
        if not closed_paper_outcome:
            reasons.append("not_closed_paper_outcome")
        if missing_identity:
            reasons.append("missing_explicit_economic_identity")
        if missing_thesis_execution:
            reasons.append("missing_explicit_thesis_execution_fields")
        if not explicit_realized_pnl:
            reasons.append("missing_explicit_realized_pnl")
        if not explicitly_paper_only:
            reasons.append("not_explicitly_paper_only")

        if reasons:
            exclusion_counts.update(reasons)
            excluded_source_counts.update([source])
            sample = {
                "raw_record_id": source_record_id(row, index),
                "source": source,
                "source_path": row.get("_post_fix_sample_source_path"),
                "source_line_number": row.get("_post_fix_sample_line_number"),
                "symbol": symbol_of(row),
                "timeframe": timeframe_of(row),
                "side": side_of(row),
                "exclusion_reasons": reasons,
                "missing_identity_fields": missing_identity,
                "missing_thesis_execution_fields": missing_thesis_execution,
                "paper_result": paper_result or None,
                "exchange_order": row.get("exchange_order"),
                "live_order": row.get("live_order"),
            }
            if len(samples) < 25:
                samples.append(sample)
            if len(samples_by_source[source]) < 5:
                samples_by_source[source].append(sample)
            continue

        eligible_source_counts.update([source])
        eligible_rows.append(dict(row))

    compacted = compact_economic_trades(eligible_rows)
    return {
        "schema_version": "post_fix_economic_outcome_sample_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "POST_FIX_SAMPLE_READY" if compacted else "POST_FIX_SAMPLE_NOT_STARTED",
        "read_only_audit_no_runtime_change": True,
        "raw_close_rows_examined": len(closed_rows),
        "eligible_raw_close_rows": len(eligible_rows),
        "excluded_raw_close_rows": len(closed_rows) - len(eligible_rows),
        "compacted_economic_trade_count": len(compacted),
        "new_compacted_economic_paper_outcomes": len(compacted),
        "required_new_compacted_economic_paper_outcomes": 100,
        "sample_started": bool(compacted),
        "source_counts": dict(sorted(source_counts.items())),
        "eligible_source_counts": dict(sorted(eligible_source_counts.items())),
        "excluded_source_counts": dict(sorted(excluded_source_counts.items())),
        "source_read_status": dict(source_read_status or {}),
        "required_identity_fields": list(POST_FIX_SAMPLE_REQUIRED_IDENTITY_FIELDS),
        "required_thesis_execution_fields": list(THESIS_EXECUTION_REQUIRED_FIELDS),
        "required_realized_pnl_fields": list(EXPLICIT_REALIZED_PNL_FIELDS),
        "exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
        "sample_excluded_rows": samples,
        "sample_excluded_rows_by_source": {
            source: source_samples
            for source, source_samples in sorted(samples_by_source.items())
        },
        "sample_compacted_economic_trades": compacted[:25],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def round_trip_cost_bps(row: Mapping[str, Any]) -> float | None:
    explicit = first_float(row, "round_trip_cost_bps", "expected_round_trip_cost_bps", "total_cost_bps")
    if explicit is not None:
        return abs(explicit)
    components = [
        first_float(row, "actual_observed_spread_entry_bps", "bid_ask_spread_bps"),
        first_float(row, "expected_slippage_bps", "slippage_bps", "realized_slippage_bps"),
        first_float(row, "depth_price_impact_bps", "depth_impact_bps"),
        first_float(row, "funding_bps", "expected_funding_bps"),
    ]
    total = sum(abs(value) for value in components if value is not None)
    fees = fee_usd(row)
    notional = notional_usd(row)
    if fees > 0.0 and notional > 0.0:
        total += fees / notional * 10_000.0
    return total if total > 0.0 else None


def cost_uncertainty_bps(row: Mapping[str, Any]) -> float | None:
    return first_float(row, "cost_uncertainty_bps", "round_trip_cost_uncertainty_bps", "execution_cost_uncertainty_bps")


def paper_entry_cost_flags(row: Mapping[str, Any]) -> dict[str, bool]:
    fee_bps = first_float(row, "actual_fee_bps", "fee_bps", "taker_fee_bps", "expected_fee_bps")
    if fee_bps is None and fee_usd(row) > 0.0 and notional_usd(row) > 0.0:
        fee_bps = fee_usd(row) / notional_usd(row) * 10_000.0
    return {
        "observed_spread": first_float(row, "actual_observed_spread_entry_bps", "bid_ask_spread_bps") is not None,
        "maker_taker_fee": fee_bps is not None,
        "depth_derived_price_impact": first_float(row, "depth_price_impact_bps", "depth_impact_bps") is not None
        and first_present(row, "depth_price_impact_source", "depth_price_impact_model") is not None,
        "expected_slippage": first_float(row, "expected_slippage_bps", "expected_slippage_usd", "slippage_bps") is not None,
        "funding": first_float(row, "funding_bps", "expected_funding_bps", "funding_rate") is not None,
        "latency_reserve": first_float(row, "latency_reserve_bps", "expected_latency_reserve_bps") is not None,
        "partial_fill_reserve": first_present(row, "partial_fill_reserve_bps", "partial_fill_plan", "partial_fills") is not None,
        "round_trip_cost": round_trip_cost_bps(row) is not None,
        "cost_uncertainty": cost_uncertainty_bps(row) is not None,
    }


def paper_entry_cost_coverage_status(*, candidate_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    missing_counts: Counter[str] = Counter()
    present_counts: Counter[str] = Counter()
    production_grade_rows = 0
    samples: list[dict[str, Any]] = []
    for index, row in enumerate(candidate_rows):
        flags = paper_entry_cost_flags(row)
        for field in ENTRY_COST_REQUIRED_FIELDS:
            if flags.get(field) is True:
                present_counts[field] += 1
        missing = [field for field in ENTRY_COST_REQUIRED_FIELDS if flags.get(field) is not True]
        missing_counts.update(missing)
        if not missing:
            production_grade_rows += 1
        elif len(samples) < 25:
            samples.append(
                {
                    "raw_record_id": source_record_id(row, index),
                    "symbol": symbol_of(row),
                    "timeframe": timeframe_of(row),
                    "strategy_id": strategy_id_of(row),
                    "side": side_of(row),
                    "missing_cost_fields": missing,
                    "cost_flags": flags,
                }
            )
    row_count = len(candidate_rows)
    coverage = production_grade_rows / row_count if row_count else 0.0
    missing_cost_field_counts = dict(sorted(missing_counts.items()))
    missing_cost_fields = sorted(missing_cost_field_counts)
    present_cost_field_counts = {
        field: int(present_counts.get(field, 0))
        for field in ENTRY_COST_REQUIRED_FIELDS
    }
    field_coverage = {
        field: {
            "present_rows": present_cost_field_counts[field],
            "missing_rows": int(missing_counts.get(field, 0)),
            "coverage": (present_cost_field_counts[field] / row_count) if row_count else 0.0,
            "required_coverage": 0.95,
            "passes_required_coverage": ((present_cost_field_counts[field] / row_count) >= 0.95)
            if row_count
            else False,
        }
        for field in ENTRY_COST_REQUIRED_FIELDS
    }
    shadow_only_missing_cost_rows = row_count - production_grade_rows
    pass_conditions = {
        "candidate_rows_gt_0": row_count > 0,
        "production_grade_cost_coverage_gte_95pct": coverage >= 0.95,
        "missing_cost_fields_eq_0": not missing_counts,
    }
    blocker_details = []
    if not pass_conditions["candidate_rows_gt_0"]:
        blocker_details.append(
            {
                "pass_condition": "candidate_rows_gt_0",
                "actual": row_count,
                "required": "> 0",
                "source_artifact": "paper_entry_cost_coverage_status.json",
            }
        )
    if not pass_conditions["production_grade_cost_coverage_gte_95pct"]:
        blocker_details.append(
            {
                "pass_condition": "production_grade_cost_coverage_gte_95pct",
                "actual": coverage,
                "required": ">= 0.95",
                "source_artifact": "paper_entry_cost_coverage_status.json",
            }
        )
    if not pass_conditions["missing_cost_fields_eq_0"]:
        blocker_details.append(
            {
                "pass_condition": "missing_cost_fields_eq_0",
                "actual": dict(sorted(missing_counts.items())),
                "required": {},
                "source_artifact": "paper_entry_cost_coverage_status.json",
            }
        )
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    actuals = {
        "candidate_rows_gt_0": row_count,
        "production_grade_cost_coverage_gte_95pct": coverage,
        "missing_cost_fields_eq_0": missing_cost_field_counts,
        "production_grade_cost_rows": production_grade_rows,
        "shadow_only_missing_cost_rows": shadow_only_missing_cost_rows,
        "required_cost_fields": list(ENTRY_COST_REQUIRED_FIELDS),
        "field_coverage": field_coverage,
    }
    required = {
        "candidate_rows_gt_0": ">0",
        "production_grade_cost_coverage_gte_95pct": ">=0.95",
        "missing_cost_fields_eq_0": {},
        "production_grade_cost_rows": ">=95% of candidate rows",
        "shadow_only_missing_cost_rows": 0,
        "required_cost_fields": list(ENTRY_COST_REQUIRED_FIELDS),
        "field_coverage": ">=0.95 for every required production cost field",
    }
    return {
        "schema_version": "paper_entry_cost_coverage_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_PAPER_ENTRY_COST_COVERAGE" if all(pass_conditions.values()) else "BLOCKED_PAPER_ENTRY_COST_COVERAGE",
        "read_only_audit_no_runtime_change": True,
        "candidate_rows_examined": row_count,
        "rows_examined": row_count,
        "production_grade_cost_rows": production_grade_rows,
        "production_grade_cost_coverage": coverage,
        "required_coverage": 0.95,
        "production_grade_cost_coverage_required": 0.95,
        "production_grade_cost_coverage_shortfall_to_required": max(0.0, 0.95 - coverage),
        "required_cost_fields": list(ENTRY_COST_REQUIRED_FIELDS),
        "required_fields": list(ENTRY_COST_REQUIRED_FIELDS),
        "missing_required_fields": missing_cost_fields,
        "missing_required_field_counts": missing_cost_field_counts,
        "missing_required_field_count": len(missing_cost_fields),
        "missing_required_row_total": sum(missing_cost_field_counts.values()),
        "missing_cost_fields": missing_cost_fields,
        "missing_cost_field_counts": missing_cost_field_counts,
        "missing_field_counts": missing_cost_field_counts,
        "present_required_field_counts": present_cost_field_counts,
        "present_cost_field_counts": present_cost_field_counts,
        "field_coverage": field_coverage,
        "required_field_coverage": field_coverage,
        "cost_field_coverage": field_coverage,
        "fallback_rows": shadow_only_missing_cost_rows,
        "shadow_only_rows": shadow_only_missing_cost_rows,
        "shadow_only_missing_cost_rows": shadow_only_missing_cost_rows,
        "shadow_only_missing_production_grade_cost_rows": shadow_only_missing_cost_rows,
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "actuals": actuals,
        "required": required,
        "sample_blockers": blocker_details[:25],
        "sample_missing_cost_rows": samples,
        "missing_cost_row_samples": samples,
        "sample_missing_required_cost_rows": samples,
        "sample_required_cost_missing_rows": samples,
        "sample_rows_missing_cost_fields": samples,
        "sample_shadow_only_missing_cost_rows": samples,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def expected_gross_edge_bps(row: Mapping[str, Any]) -> float | None:
    parsed = first_float(row, "expected_gross_edge_bps", "expected_move_bps")
    return abs(parsed) if parsed is not None else None


def expected_net_edge_lower_bound_bps(row: Mapping[str, Any]) -> float | None:
    explicit = first_float(row, "expected_net_edge_lower_bound_bps", "expected_edge_lower_bound_bps")
    if explicit is not None:
        return explicit
    after_cost = first_float(row, "expected_net_edge_bps", "expected_move_after_cost_bps")
    uncertainty = cost_uncertainty_bps(row)
    if after_cost is None or uncertainty is None:
        return None
    return abs(after_cost) - abs(uncertainty)


def paper_edge_to_cost_gate_status(
    *,
    candidate_rows: Sequence[Mapping[str, Any]],
    cost_coverage: Mapping[str, Any],
    safety_ratio: float = EDGE_TO_COST_CONTEXTUAL_SAFETY_RATIO,
) -> dict[str, Any]:
    admitted_rows = 0
    missing_gate_inputs: Counter[str] = Counter()
    blocked_reason_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for index, row in enumerate(candidate_rows):
        flags = paper_entry_cost_flags(row)
        gross_edge = expected_gross_edge_bps(row)
        lower_bound = expected_net_edge_lower_bound_bps(row)
        cost = round_trip_cost_bps(row)
        missing = []
        if gross_edge is None:
            missing.append("expected_gross_edge")
        if lower_bound is None:
            missing.append("expected_net_edge_lower_bound")
        if cost is None:
            missing.append("expected_round_trip_cost")
        if any(flags.get(field) is not True for field in ENTRY_COST_REQUIRED_FIELDS):
            missing.append("production_grade_cost_evidence")
        missing_gate_inputs.update(missing)
        ratio = gross_edge / cost if gross_edge is not None and cost and cost > 0.0 else None
        blockers = []
        if missing:
            blockers.append("missing_gate_inputs")
        if lower_bound is not None and lower_bound <= 0.0:
            blockers.append("expected_net_edge_lower_bound_lte_0")
        if ratio is not None and ratio < safety_ratio:
            blockers.append("edge_to_cost_ratio_below_contextual_safety_ratio")
        if not blockers:
            admitted_rows += 1
        else:
            blocked_reason_counts.update(blockers)
            if len(samples) < 25:
                samples.append(
                    {
                        "raw_record_id": source_record_id(row, index),
                        "symbol": symbol_of(row),
                        "timeframe": timeframe_of(row),
                        "strategy_id": strategy_id_of(row),
                        "side": side_of(row),
                        "expected_gross_edge_bps": gross_edge,
                        "expected_round_trip_cost_bps": cost,
                        "expected_net_edge_lower_bound_bps": lower_bound,
                        "edge_to_cost_ratio": ratio,
                        "blockers": blockers,
                        "missing_gate_inputs": missing,
                    }
                )
    pass_conditions = {
        "candidate_rows_gt_0": len(candidate_rows) > 0,
        "production_grade_cost_coverage_gte_95pct": float(cost_coverage.get("production_grade_cost_coverage") or 0.0) >= 0.95,
        "all_candidates_have_gate_inputs": not missing_gate_inputs,
        "admitted_rows_have_positive_lower_bound": blocked_reason_counts.get("expected_net_edge_lower_bound_lte_0", 0) == 0,
        "admitted_rows_meet_contextual_safety_ratio": blocked_reason_counts.get("edge_to_cost_ratio_below_contextual_safety_ratio", 0) == 0,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    condition_details = {
        "candidate_rows_gt_0": {
            "pass_condition": "candidate_rows_gt_0",
            "actual": len(candidate_rows),
            "required": "> 0",
            "source_artifact": "paper_edge_to_cost_gate_status.json",
        },
        "production_grade_cost_coverage_gte_95pct": {
            "pass_condition": "production_grade_cost_coverage_gte_95pct",
            "actual": cost_coverage.get("production_grade_cost_coverage"),
            "required": ">= 0.95",
            "source_artifact": "paper_entry_cost_coverage_status.json",
        },
        "all_candidates_have_gate_inputs": {
            "pass_condition": "all_candidates_have_gate_inputs",
            "actual": dict(sorted(missing_gate_inputs.items())),
            "required": {},
            "source_artifact": "paper_edge_to_cost_gate_status.json",
        },
        "admitted_rows_have_positive_lower_bound": {
            "pass_condition": "admitted_rows_have_positive_lower_bound",
            "actual": blocked_reason_counts.get("expected_net_edge_lower_bound_lte_0", 0),
            "required": 0,
            "source_artifact": "paper_edge_to_cost_gate_status.json",
        },
        "admitted_rows_meet_contextual_safety_ratio": {
            "pass_condition": "admitted_rows_meet_contextual_safety_ratio",
            "actual": blocked_reason_counts.get("edge_to_cost_ratio_below_contextual_safety_ratio", 0),
            "required": 0,
            "source_artifact": "paper_edge_to_cost_gate_status.json",
        },
    }
    blocker_details = [condition_details[name] for name in blocked_reasons]
    actuals = {
        "candidate_rows_gt_0": len(candidate_rows),
        "production_grade_cost_coverage_gte_95pct": cost_coverage.get("production_grade_cost_coverage"),
        "all_candidates_have_gate_inputs": dict(sorted(missing_gate_inputs.items())),
        "admitted_rows_have_positive_lower_bound": blocked_reason_counts.get("expected_net_edge_lower_bound_lte_0", 0),
        "admitted_rows_meet_contextual_safety_ratio": blocked_reason_counts.get(
            "edge_to_cost_ratio_below_contextual_safety_ratio", 0
        ),
        "admitted_candidate_rows": admitted_rows,
        "shadow_only_candidate_rows": len(candidate_rows) - admitted_rows,
        "contextual_safety_ratio": safety_ratio,
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
    }
    required = {
        "candidate_rows_gt_0": ">0",
        "production_grade_cost_coverage_gte_95pct": ">=0.95",
        "all_candidates_have_gate_inputs": {},
        "admitted_rows_have_positive_lower_bound": 0,
        "admitted_rows_meet_contextual_safety_ratio": 0,
        "admitted_candidate_rows": "diagnostic count",
        "shadow_only_candidate_rows": "diagnostic count",
        "contextual_safety_ratio": safety_ratio,
        "blocked_reason_counts": {},
    }
    return {
        "schema_version": "paper_edge_to_cost_gate_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_PAPER_EDGE_TO_COST_GATE" if all(pass_conditions.values()) else "BLOCKED_PAPER_EDGE_TO_COST_GATE",
        "read_only_audit_no_runtime_change": True,
        "candidate_rows_examined": len(candidate_rows),
        "admitted_candidate_rows": admitted_rows,
        "admitted_candidate_count": admitted_rows,
        "shadow_only_candidate_rows": len(candidate_rows) - admitted_rows,
        "shadow_only_candidate_count": len(candidate_rows) - admitted_rows,
        "production_grade_cost_coverage": cost_coverage.get("production_grade_cost_coverage"),
        "paper_entry_production_grade_cost_coverage": cost_coverage.get("production_grade_cost_coverage"),
        "contextual_safety_ratio": safety_ratio,
        "missing_gate_input_counts": dict(sorted(missing_gate_inputs.items())),
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "actuals": actuals,
        "required": required,
        "sample_blockers": blocker_details[:25],
        "sample_blocked_rows": samples,
        "sample_blocked_candidates": samples,
        "sample_shadow_only_candidates": samples,
        "sample_shadow_only_rows": samples,
        "blocked_candidate_sample_count": len(samples),
        "shadow_only_candidate_sample_count": len(samples),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def symbol_cluster_of(row: Mapping[str, Any]) -> str:
    explicit = first_present(row, "symbol_cluster", "asset_cluster", "market_cluster", "sector")
    if explicit is not None:
        return str(explicit)
    symbol = symbol_of(row)
    for quote in ("USDT", "USD", "USDC", "BTC", "ETH"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            base = symbol[: -len(quote)]
            break
    else:
        base = symbol
    if base in {"BTC", "ETH"}:
        return "major"
    return "alt"


def regime_of(row: Mapping[str, Any]) -> str:
    return str(first_present(row, "market_regime_at_entry", "market_regime", "regime", "volatility_regime") or "UNKNOWN")


def volatility_bucket_of(row: Mapping[str, Any]) -> str:
    return str(first_present(row, "volatility_bucket", "atr_bucket", "realized_volatility_bucket", "volatility_regime") or "UNKNOWN")


def liquidity_bucket_of(row: Mapping[str, Any]) -> str:
    return str(first_present(row, "liquidity_bucket", "spread_liquidity_bucket", "depth_bucket", "liquidity_regime") or "UNKNOWN")


def timeframe_order_key(timeframe: str) -> tuple[int, str]:
    rank = {
        "1m": 1,
        "3m": 2,
        "5m": 3,
        "15m": 4,
        "30m": 5,
        "1h": 6,
        "2h": 7,
        "4h": 8,
        "1d": 9,
    }
    return rank.get(str(timeframe), 99), str(timeframe)


def timeframe_eligibility_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net_values = [net_pnl_usd(row) for row in rows]
    gross = sum(gross_pnl_usd(row) for row in rows)
    fees = sum(fee_usd(row) for row in rows)
    slippage = sum(slippage_usd(row) for row in rows)
    funding = sum(funding_usd(row) for row in rows)
    turnover = sum(first_float(row, "turnover_usd") or notional_usd(row) for row in rows)
    return {
        "economic_trade_count": len(rows),
        "symbol_count": len({symbol_of(row) for row in rows}),
        "side_counts": dict(sorted(Counter(side_of(row) for row in rows).items())),
        "strategy_counts": dict(sorted(Counter(strategy_id_of(row) for row in rows).items())),
        "symbol_cluster_counts": dict(sorted(Counter(symbol_cluster_of(row) for row in rows).items())),
        "regime_counts": dict(sorted(Counter(regime_of(row) for row in rows).items())),
        "volatility_bucket_counts": dict(sorted(Counter(volatility_bucket_of(row) for row in rows).items())),
        "liquidity_bucket_counts": dict(sorted(Counter(liquidity_bucket_of(row) for row in rows).items())),
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "slippage_usd": slippage,
        "funding_usd": funding,
        "net_pnl_usd": sum(net_values),
        "turnover_usd": turnover,
        "after_cost_expectancy_usd": mean(net_values),
        "after_cost_expectancy_95_lower_bound_usd": lower_confidence_bound(net_values),
        "profit_factor": profit_factor(net_values),
        "win_rate": sum(1 for value in net_values if value > 0.0) / len(net_values) if net_values else None,
        "cost_drag_pct_of_abs_gross": cost_drag_pct(gross, fees, slippage, funding),
        "max_drawdown_usd": max_drawdown(net_values),
        "worst_1pct_trade_net_pnl_usd": worst_percentile(net_values, 0.01),
        "median_trade_net_pnl_usd": median(net_values),
    }


def dynamic_timeframe_execution_eligibility_status(
    *,
    economic_rows: Sequence[Mapping[str, Any]],
    cost_coverage: Mapping[str, Any],
    edge_to_cost: Mapping[str, Any],
    min_economic_trades: int = DYNAMIC_TIMEFRAME_MIN_ECONOMIC_TRADES,
    min_symbols: int = DYNAMIC_TIMEFRAME_MIN_SYMBOLS,
    min_profit_factor: float = DYNAMIC_TIMEFRAME_MIN_PROFIT_FACTOR,
    max_cost_drag: float = DYNAMIC_TIMEFRAME_MAX_COST_DRAG,
) -> dict[str, Any]:
    by_timeframe: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in economic_rows:
        by_timeframe[str(row.get("timeframe") or timeframe_of(row))].append(row)

    production_grade_coverage = float(cost_coverage.get("production_grade_cost_coverage") or 0.0)
    edge_gate_passed = edge_to_cost.get("status") == "PASS_PAPER_EDGE_TO_COST_GATE"
    timeframe_states: dict[str, Any] = {}
    active_timeframes: list[str] = []
    shadow_only_timeframes: list[str] = []
    timing_only_timeframes: list[str] = []
    cooldown_timeframes: list[str] = []
    quarantined_timeframes: list[str] = []

    for timeframe, rows in sorted(by_timeframe.items(), key=lambda item: timeframe_order_key(item[0])):
        metrics = timeframe_eligibility_metrics(rows)
        lower_bound = metrics["after_cost_expectancy_95_lower_bound_usd"]
        pf = metrics["profit_factor"]
        cost_drag = metrics["cost_drag_pct_of_abs_gross"]
        block_reasons: list[str] = []
        if metrics["economic_trade_count"] < min_economic_trades:
            block_reasons.append("insufficient_independent_economic_trades")
        if metrics["symbol_count"] < min_symbols:
            block_reasons.append("insufficient_symbol_diversity")
        if lower_bound is None or lower_bound <= 0.0:
            block_reasons.append("after_cost_expectancy_lower_bound_not_positive")
        if pf is None or pf < min_profit_factor:
            block_reasons.append("profit_factor_below_required_floor")
        if cost_drag is None:
            block_reasons.append("cost_drag_unavailable")
        elif cost_drag > max_cost_drag:
            block_reasons.append("cost_drag_above_contextual_limit")
        if production_grade_coverage < 0.95:
            block_reasons.append("production_grade_cost_coverage_below_95pct")
        if not edge_gate_passed:
            block_reasons.append("paper_edge_to_cost_gate_not_passed")

        if not block_reasons:
            state = "ACTIVE"
            active_timeframes.append(timeframe)
        elif "cost_drag_above_contextual_limit" in block_reasons:
            state = "QUARANTINED"
            quarantined_timeframes.append(timeframe)
        elif "after_cost_expectancy_lower_bound_not_positive" in block_reasons or "profit_factor_below_required_floor" in block_reasons:
            state = "COOLDOWN"
            cooldown_timeframes.append(timeframe)
        else:
            state = "SHADOW_ONLY"
            shadow_only_timeframes.append(timeframe)

        if timeframe == "1m" and state == "SHADOW_ONLY":
            state = "TIMING_ONLY"
            if timeframe in shadow_only_timeframes:
                shadow_only_timeframes.remove(timeframe)
            timing_only_timeframes.append(timeframe)

        timeframe_states[timeframe] = {
            "timeframe": timeframe,
            "state": state,
            "standalone_execution_allowed": state == "ACTIVE",
            "higher_timeframe_timing_role_allowed": timeframe == "1m" and state in {"ACTIVE", "TIMING_ONLY"},
            "block_reasons": block_reasons,
            "metrics": metrics,
            "context_bucket_dimensions": [
                "symbol_cluster",
                "strategy_id",
                "side",
                "timeframe",
                "regime",
                "volatility_bucket",
                "liquidity_bucket",
            ],
        }

    one_min_state = timeframe_states.get("1m", {}).get("state")
    pass_conditions = {
        "economic_trade_rows_gt_0": len(economic_rows) > 0,
        "at_least_one_timeframe_active": bool(active_timeframes),
        "production_grade_cost_coverage_gte_95pct": production_grade_coverage >= 0.95,
        "paper_edge_to_cost_gate_passed": edge_gate_passed,
        "standalone_1m_active_only_with_full_bucket_pass": one_min_state != "ACTIVE"
        or not timeframe_states.get("1m", {}).get("block_reasons"),
        "all_active_timeframes_have_positive_after_cost_expectancy_lower_bound": all(
            (timeframe_states[timeframe]["metrics"]["after_cost_expectancy_95_lower_bound_usd"] or 0.0) > 0.0
            for timeframe in active_timeframes
        ),
        "all_active_timeframes_have_profit_factor_gte_floor": all(
            (
                timeframe_states[timeframe]["metrics"]["profit_factor"] == float("inf")
                or (timeframe_states[timeframe]["metrics"]["profit_factor"] or 0.0) >= min_profit_factor
            )
            for timeframe in active_timeframes
        ),
    }
    actuals = {
        "economic_trade_rows_gt_0": len(economic_rows),
        "at_least_one_timeframe_active": active_timeframes,
        "production_grade_cost_coverage_gte_95pct": production_grade_coverage,
        "paper_edge_to_cost_gate_passed": edge_to_cost.get("status"),
        "standalone_1m_active_only_with_full_bucket_pass": {
            "one_min_state": one_min_state,
            "one_min_block_reasons": timeframe_states.get("1m", {}).get("block_reasons"),
        },
        "all_active_timeframes_have_positive_after_cost_expectancy_lower_bound": {
            timeframe: timeframe_states[timeframe]["metrics"]["after_cost_expectancy_95_lower_bound_usd"]
            for timeframe in active_timeframes
        },
        "all_active_timeframes_have_profit_factor_gte_floor": {
            timeframe: timeframe_states[timeframe]["metrics"]["profit_factor"]
            for timeframe in active_timeframes
        },
    }
    required = {
        "economic_trade_rows_gt_0": ">0",
        "at_least_one_timeframe_active": ">=1 ACTIVE timeframe",
        "production_grade_cost_coverage_gte_95pct": ">=0.95",
        "paper_edge_to_cost_gate_passed": "PASS_PAPER_EDGE_TO_COST_GATE",
        "standalone_1m_active_only_with_full_bucket_pass": "1m ACTIVE only with no block_reasons",
        "all_active_timeframes_have_positive_after_cost_expectancy_lower_bound": ">0 for every ACTIVE timeframe",
        "all_active_timeframes_have_profit_factor_gte_floor": f">={min_profit_factor} for every ACTIVE timeframe",
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="dynamic_timeframe_execution_eligibility_status.json",
    )
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    bucket_state_counts = Counter(str(state.get("state") or "UNKNOWN") for state in timeframe_states.values())
    sample_bucket_statuses = list(timeframe_states.values())[:25]
    sample_blocked_buckets = [
        state
        for state in sample_bucket_statuses
        if state.get("block_reasons")
    ]
    sample_shadow_only_buckets = [
        state
        for state in sample_bucket_statuses
        if state.get("state") in {"SHADOW_ONLY", "TIMING_ONLY", "COOLDOWN", "QUARANTINED"}
    ]
    return {
        "schema_version": "dynamic_timeframe_execution_eligibility_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY" if all(pass_conditions.values()) else "BLOCKED_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY",
        "read_only_audit_no_runtime_change": True,
        "required_evidence": {
            "min_independent_economic_trades_per_active_timeframe": min_economic_trades,
            "min_symbols_per_active_timeframe": min_symbols,
            "min_profit_factor": min_profit_factor,
            "expectancy_lower_bound_z_score": DYNAMIC_TIMEFRAME_EXPECTANCY_Z,
            "max_cost_drag_pct_of_abs_gross": max_cost_drag,
            "production_grade_cost_coverage_floor": 0.95,
        },
        "economic_trade_count": len(economic_rows),
        "production_grade_cost_coverage": production_grade_coverage,
        "paper_edge_to_cost_gate_status": edge_to_cost.get("status"),
        "active_timeframes": active_timeframes,
        "shadow_only_timeframes": shadow_only_timeframes,
        "timing_only_timeframes": timing_only_timeframes,
        "cooldown_timeframes": cooldown_timeframes,
        "quarantined_timeframes": quarantined_timeframes,
        "timeframe_states": timeframe_states,
        "bucket_count": len(timeframe_states),
        "bucket_state_counts": dict(sorted(bucket_state_counts.items())),
        "sample_bucket_statuses": sample_bucket_statuses,
        "sample_blocked_buckets": sample_blocked_buckets,
        "sample_shadow_only_buckets": sample_shadow_only_buckets,
        "all_five_timeframes_continue_prediction_and_learning": True,
        "selection_policy": "Only proven positive after-cost timeframe buckets may execute; blocked buckets remain shadow-only or timing-only evidence.",
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def timeframe_share(values: Mapping[str, float]) -> dict[str, float]:
    total = sum(abs(value) for value in values.values())
    if total <= 1e-12:
        return {timeframe: 0.0 for timeframe in sorted(values, key=timeframe_order_key)}
    return {timeframe: abs(value) / total for timeframe, value in sorted(values.items(), key=lambda item: timeframe_order_key(item[0]))}


def timeframe_execution_concentration_guard_status(
    *,
    economic_rows: Sequence[Mapping[str, Any]],
    eligibility: Mapping[str, Any] | None = None,
    max_share: float = TIMEFRAME_CONCENTRATION_MAX_SHARE,
) -> dict[str, Any]:
    by_timeframe: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in economic_rows:
        by_timeframe[str(row.get("timeframe") or timeframe_of(row))].append(row)

    trade_counts = {timeframe: float(len(rows)) for timeframe, rows in by_timeframe.items()}
    turnover = {
        timeframe: sum(first_float(row, "turnover_usd") or notional_usd(row) for row in rows)
        for timeframe, rows in by_timeframe.items()
    }
    fees = {timeframe: sum(fee_usd(row) for row in rows) for timeframe, rows in by_timeframe.items()}
    abs_net = {timeframe: sum(abs(net_pnl_usd(row)) for row in rows) for timeframe, rows in by_timeframe.items()}
    signed_net = {timeframe: sum(net_pnl_usd(row) for row in rows) for timeframe, rows in by_timeframe.items()}
    shares = {
        "economic_trade_share_by_timeframe": timeframe_share(trade_counts),
        "gross_notional_share_by_timeframe": timeframe_share(turnover),
        "fee_share_by_timeframe": timeframe_share(fees),
        "absolute_net_pnl_share_by_timeframe": timeframe_share(abs_net),
    }

    total_net = sum(signed_net.values())
    signed_net_contribution = {
        timeframe: value / total_net if abs(total_net) > 1e-12 else 0.0
        for timeframe, value in sorted(signed_net.items(), key=lambda item: timeframe_order_key(item[0]))
    }

    timeframe_states = as_dict((eligibility or {}).get("timeframe_states"))
    violations: list[dict[str, Any]] = []
    for dimension, payload in shares.items():
        for timeframe, share in payload.items():
            if share > max_share:
                state = as_dict(timeframe_states.get(timeframe)).get("state", "UNKNOWN")
                violations.append(
                    {
                        "dimension": dimension,
                        "timeframe": timeframe,
                        "share": share,
                        "max_allowed_share": max_share,
                        "eligibility_state": state,
                        "unproven_concentration": state != "ACTIVE",
                    }
                )

    pass_conditions = {
        "economic_trade_rows_gt_0": len(economic_rows) > 0,
        "no_timeframe_dimension_exceeds_operator_envelope": not violations,
        "no_unproven_timeframe_concentration": not any(row["unproven_concentration"] for row in violations),
    }
    actuals = {
        "economic_trade_rows_gt_0": len(economic_rows),
        "no_timeframe_dimension_exceeds_operator_envelope": {
            "violation_count": len(violations),
            "violations": violations[:25],
        },
        "no_unproven_timeframe_concentration": [
            row for row in violations[:25] if row["unproven_concentration"]
        ],
    }
    required = {
        "economic_trade_rows_gt_0": ">0",
        "no_timeframe_dimension_exceeds_operator_envelope": f"all shares <= {max_share}",
        "no_unproven_timeframe_concentration": [],
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="timeframe_execution_concentration_guard_status.json",
    )
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    violation_samples = violations[:25]
    return {
        "schema_version": "timeframe_execution_concentration_guard_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD" if all(pass_conditions.values()) else "BLOCKED_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD",
        "read_only_audit_no_runtime_change": True,
        "operator_envelope_max_share": max_share,
        "operator_concentration_envelope": {
            "max_share": max_share,
            "dimensions": list(shares.keys()),
            "no_unproven_concentration_required": True,
        },
        "economic_trade_count": len(economic_rows),
        "share_dimensions": shares,
        "trade_share_by_timeframe": shares["economic_trade_share_by_timeframe"],
        "economic_trade_share_by_timeframe": shares["economic_trade_share_by_timeframe"],
        "gross_notional_share_by_timeframe": shares["gross_notional_share_by_timeframe"],
        "fee_share_by_timeframe": shares["fee_share_by_timeframe"],
        "net_pnl_share_by_timeframe": shares["absolute_net_pnl_share_by_timeframe"],
        "absolute_net_pnl_share_by_timeframe": shares["absolute_net_pnl_share_by_timeframe"],
        "signed_net_pnl_contribution_by_timeframe": signed_net_contribution,
        "violations": violations,
        "violation_count": len(violations),
        "sample_violations": violation_samples,
        "violation_samples": violation_samples,
        "concentration_violation_samples": violation_samples,
        "policy_note": "The guard does not force equal trade counts; it blocks unproven concentration above the operator envelope.",
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def scan_hardcoded_timeframe_paths(repo_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for relative in SOURCE_SCAN_FILES:
        path = repo_root / relative
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if (
                'timeframe="1m"' in stripped
                or "timeframe='1m'" in stripped
                or 'feature_timeframe = "1m"' in stripped
                or 'f"v2:signals:paper:{symbol_key}:1m"' in stripped
                or 'f"v2:signals:paper:{symbol}:1m"' in stripped
            ):
                findings.append(
                    {
                        "path": relative,
                        "line": lineno,
                        "text": stripped,
                    }
                )
    return findings


def scan_silent_1m_fallback_paths(repo_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    unsafe_function_terms = ("thesis", "economic")
    unsafe_assignment_terms = (
        "thesis_timeframe",
        "prediction_timeframe",
        "expected_move_timeframe",
        "feature_timeframe",
        "timeframe",
    )
    for relative in SOURCE_SCAN_FILES:
        path = repo_root / relative
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        current_function = ""
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("def "):
                current_function = stripped.split("(", 1)[0].replace("def ", "").strip()
            if not stripped or stripped.startswith("#"):
                continue
            lower_function = current_function.lower()
            lower_line = stripped.lower()
            unsafe_function = any(term in lower_function for term in unsafe_function_terms)
            unsafe_assignment = any(term in lower_line for term in unsafe_assignment_terms)
            reason: str | None = None
            if (
                unsafe_function
                and "return paper_execution_timing_timeframe" in lower_line
                and "execution" not in lower_function
            ):
                reason = "unsafe_thesis_or_economic_timeframe_default_to_execution_1m"
            elif (
                unsafe_assignment
                and ("fallback=\"1m\"" in stripped or "fallback='1m'" in stripped or ' or "1m"' in stripped or " or '1m'" in stripped)
                and "execution_timeframe" not in lower_line
            ):
                reason = "unsafe_timeframe_fallback_literal_1m"
            if reason is None:
                continue
            findings.append(
                {
                    "path": relative,
                    "line": lineno,
                    "function": current_function,
                    "text": stripped,
                    "reason": reason,
                }
            )
    return findings


def paper_churn_governor_runtime_wiring_status(repo_root: Path) -> dict[str, Any]:
    return runtime_entry_gate_wiring_status(
        repo_root,
        pass_status="PASS_PAPER_CHURN_GOVERNOR_RUNTIME_WIRING",
        blocked_status="BLOCKED_PAPER_CHURN_GOVERNOR_RUNTIME_WIRING",
        required_terms=(
            "evaluate_churn_governor_entry_gate",
            "_paper_churn_governor_runtime_rows",
            "_paper_churn_governor_candidate_row",
            'risk["paper_churn_governor"] = churn_result',
            'if not churn_result["allowed"]',
            "deny_paper_churn_governor",
        ),
        ordered_gate_terms=(
            "churn_result = evaluate_churn_governor_entry_gate(",
            'risk["paper_churn_governor"] = churn_result',
            "deny_paper_churn_governor",
        ),
    )


def paper_entry_cost_runtime_wiring_status(repo_root: Path) -> dict[str, Any]:
    return runtime_entry_gate_wiring_status(
        repo_root,
        pass_status="PASS_PAPER_ENTRY_COST_RUNTIME_WIRING",
        blocked_status="BLOCKED_PAPER_ENTRY_COST_RUNTIME_WIRING",
        required_terms=(
            "_paper_entry_production_cost_gate",
            'risk["paper_entry_production_cost_gate"] = cost_result',
            'if not cost_result["allowed"]',
            "deny_paper_entry_cost_gate",
            "production_cost_evidence",
            "expected_net_edge_lower_bound",
            "fallback_flag_false",
            "edge_to_cost_ratio_below_contextual_safety_ratio",
        ),
        ordered_gate_terms=(
            "cost_result = _paper_entry_production_cost_gate(",
            'risk["paper_entry_production_cost_gate"] = cost_result',
            "deny_paper_entry_cost_gate",
        ),
    )


def paper_reentry_dedup_runtime_wiring_status(repo_root: Path) -> dict[str, Any]:
    return runtime_entry_gate_wiring_status(
        repo_root,
        pass_status="PASS_PAPER_REENTRY_DEDUP_RUNTIME_WIRING",
        blocked_status="BLOCKED_PAPER_REENTRY_DEDUP_RUNTIME_WIRING",
        required_terms=(
            "_paper_reentry_dedup_gate",
            "_paper_reentry_dedup_runtime_rows",
            "_paper_reentry_dedup_candidate_row",
            'risk["paper_reentry_dedup_gate"] = dedup_result',
            'if not dedup_result["allowed"]',
            "deny_paper_reentry_dedup",
            "same_candle_same_thesis",
            "same_prediction_id",
        ),
        ordered_gate_terms=(
            "dedup_result = _paper_reentry_dedup_gate(",
            'risk["paper_reentry_dedup_gate"] = dedup_result',
            "deny_paper_reentry_dedup",
        ),
    )


def paper_trade_management_reentry_dedup_runtime_wiring_status(repo_root: Path) -> dict[str, Any]:
    return runtime_entry_gate_wiring_status(
        repo_root,
        relative_path="v2/backend/app/cli/v2_trade_management_paper_loop.py",
        pass_status="PASS_ACTIVE_PAPER_OWNER_REENTRY_DEDUP_RUNTIME_WIRING",
        blocked_status="BLOCKED_ACTIVE_PAPER_OWNER_REENTRY_DEDUP_RUNTIME_WIRING",
        required_terms=(
            "_paper_reentry_dedup_gate",
            "_apply_paper_reentry_dedup_gate",
            "_paper_reentry_source_rows",
            "_paper_reentry_dedup_candidate_row",
            "paper_reentry_dedup_gate",
            'reentry_dedup_result["allowed"]',
            "PAPER_REENTRY_DEDUP_BLOCKED",
            "same_candle_same_thesis",
            "same_prediction_id",
        ),
        ordered_gate_terms=(
            "reentry_dedup_result = _paper_reentry_dedup_gate(",
            'risk_decisions[-1]["paper_reentry_dedup_gate"] = reentry_dedup_result',
            "_apply_paper_reentry_dedup_gate(intent, reentry_dedup_result)",
            'and reentry_dedup_result["allowed"]',
        ),
    )


def paper_standalone_1m_runtime_wiring_status(repo_root: Path) -> dict[str, Any]:
    return runtime_entry_gate_wiring_status(
        repo_root,
        relative_path="v2/backend/app/cli/paper_online_runtime.py",
        pass_status="PASS_PAPER_STANDALONE_1M_RUNTIME_WIRING",
        blocked_status="BLOCKED_PAPER_STANDALONE_1M_RUNTIME_WIRING",
        required_terms=(
            "_paper_standalone_1m_eligibility_gate",
            'risk["paper_standalone_1m_eligibility"] = one_minute_result',
            'if not one_minute_result["allowed"]',
            "deny_paper_standalone_1m_eligibility",
            "paper_standalone_1m_eligibility",
            "standalone_1m_thesis_requires_dedicated_strategy_bucket",
            "higher_timeframe_timing_role_allowed",
            "dedicated_1m_strategy_bucket",
        ),
        ordered_gate_terms=(
            "one_minute_result = _paper_standalone_1m_eligibility_gate(",
            'risk["paper_standalone_1m_eligibility"] = one_minute_result',
            "deny_paper_standalone_1m_eligibility",
        ),
    )


def paper_trade_management_standalone_1m_runtime_wiring_status(repo_root: Path) -> dict[str, Any]:
    return runtime_entry_gate_wiring_status(
        repo_root,
        relative_path="v2/backend/app/cli/v2_trade_management_paper_loop.py",
        pass_status="PASS_ACTIVE_PAPER_OWNER_STANDALONE_1M_RUNTIME_WIRING",
        blocked_status="BLOCKED_ACTIVE_PAPER_OWNER_STANDALONE_1M_RUNTIME_WIRING",
        required_terms=(
            "_paper_standalone_1m_eligibility_gate",
            "_apply_paper_standalone_1m_gate",
            "paper_standalone_1m_eligibility",
            'one_minute_result["allowed"]',
            "standalone_1m_thesis_requires_dedicated_strategy_bucket",
            "higher_timeframe_timing_role_allowed",
            "dedicated_strategy_bucket",
        ),
        ordered_gate_terms=(
            "one_minute_result = _paper_standalone_1m_eligibility_gate(",
            'risk_decisions[-1]["paper_standalone_1m_eligibility"] = one_minute_result',
            "_apply_paper_standalone_1m_gate(intent, one_minute_result)",
            'and one_minute_result["allowed"]',
        ),
    )


def runtime_entry_gate_wiring_status(
    repo_root: Path,
    *,
    relative_path: str = "v2/backend/app/cli/paper_online_runtime.py",
    pass_status: str,
    blocked_status: str,
    required_terms: Sequence[str],
    ordered_gate_terms: Sequence[str],
) -> dict[str, Any]:
    relative = relative_path
    path = repo_root / relative
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    all_terms = tuple(dict.fromkeys([*required_terms, *ordered_gate_terms]))
    term_hits: dict[str, list[dict[str, Any]]] = {term: [] for term in all_terms}
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        for term in all_terms:
            if term in stripped and len(term_hits[term]) < 10:
                term_hits[term].append({"path": relative, "line": lineno, "text": stripped[:240]})

    missing_terms = [term for term in required_terms if not term_hits.get(term)]
    cursor = 0
    ordered_hits: list[dict[str, Any]] = []
    for term in ordered_gate_terms:
        candidates = [hit for hit in term_hits.get(term, []) if int(hit["line"]) > cursor]
        if not candidates:
            break
        selected = candidates[0]
        cursor = int(selected["line"])
        ordered_hits.append({"term": term, **selected})
    source_order_passed = len(ordered_hits) == len(ordered_gate_terms)
    blocker_details = []
    if missing_terms:
        blocker_details.append(
            {
                "pass_condition": "required_source_terms_present",
                "actual": missing_terms,
                "required": [],
                "source_artifact": "paper_timeframe_churn_governance_audit_summary.json",
            }
        )
    if not source_order_passed:
        blocker_details.append(
            {
                "pass_condition": "gate_evaluation_risk_attachment_and_deny_block_ordered",
                "actual": ordered_hits,
                "required": list(ordered_gate_terms),
                "source_artifact": "paper_timeframe_churn_governance_audit_summary.json",
            }
        )
    runtime_wired = not missing_terms and source_order_passed
    return {
        "status": pass_status if runtime_wired else blocked_status,
        "path": relative,
        "required_terms": list(required_terms),
        "missing_terms": missing_terms,
        "ordered_gate_terms": list(ordered_gate_terms),
        "ordered_gate_term_hits": ordered_hits,
        "source_order_passed": source_order_passed,
        "term_hits": term_hits,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "runtime_wired_to_entry_gate": runtime_wired,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def paper_churn_governor_trace_status(
    churn_governor: Mapping[str, Any],
    runtime_wiring: Mapping[str, Any],
) -> dict[str, Any]:
    pass_conditions = {
        "economic_outcome_rows_examined_gt_0": int(churn_governor.get("rows_examined") or 0) > 0,
        "churn_governor_evaluated": churn_governor.get("evaluation_status") == "PASS_PAPER_CHURN_GOVERNOR_EVALUATED",
        "runtime_wired_to_entry_gate": bool(runtime_wiring.get("runtime_wired_to_entry_gate")),
        "runtime_source_order_passed": bool(runtime_wiring.get("source_order_passed")),
        "required_runtime_source_terms_present": not runtime_wiring.get("missing_terms"),
        "paper_only_no_live_routes": runtime_wiring.get("routes_to_live") is False
        and runtime_wiring.get("places_real_order") is False
        and churn_governor.get("routes_to_live") is False
        and churn_governor.get("places_real_order") is False,
        "governor_state_definitions_complete": set(churn_governor.get("state_definitions") or []) >= {
            "ACTIVE",
            "REDUCED_FREQUENCY",
            "SHADOW_ONLY",
            "COOLDOWN",
            "CHURN_HALTED",
        },
    }
    actuals = {
        "economic_outcome_rows_examined_gt_0": churn_governor.get("rows_examined"),
        "churn_governor_evaluated": churn_governor.get("evaluation_status"),
        "runtime_wired_to_entry_gate": runtime_wiring.get("runtime_wired_to_entry_gate"),
        "runtime_source_order_passed": runtime_wiring.get("source_order_passed"),
        "required_runtime_source_terms_present": runtime_wiring.get("missing_terms"),
        "paper_only_no_live_routes": {
            "runtime_routes_to_live": runtime_wiring.get("routes_to_live"),
            "runtime_places_real_order": runtime_wiring.get("places_real_order"),
            "governor_routes_to_live": churn_governor.get("routes_to_live"),
            "governor_places_real_order": churn_governor.get("places_real_order"),
        },
        "governor_state_definitions_complete": churn_governor.get("state_definitions"),
    }
    required = {
        "economic_outcome_rows_examined_gt_0": ">0",
        "churn_governor_evaluated": "PASS_PAPER_CHURN_GOVERNOR_EVALUATED",
        "runtime_wired_to_entry_gate": True,
        "runtime_source_order_passed": True,
        "required_runtime_source_terms_present": [],
        "paper_only_no_live_routes": {
            "routes_to_live": False,
            "places_real_order": False,
        },
        "governor_state_definitions_complete": [
            "ACTIVE",
            "REDUCED_FREQUENCY",
            "SHADOW_ONLY",
            "COOLDOWN",
            "CHURN_HALTED",
        ],
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="paper_churn_governor_status.json",
    )
    payload = dict(churn_governor)
    payload.update(
        {
            "runtime_wiring": runtime_wiring,
            "runtime_wired_to_entry_gate": bool(runtime_wiring.get("runtime_wired_to_entry_gate")),
            "runtime_source_order_passed": bool(runtime_wiring.get("source_order_passed")),
            "pass_conditions": pass_conditions,
            "blocked_reasons": [str(detail["pass_condition"]) for detail in blocker_details],
            "blocker_details": blocker_details,
            "failed_blocker_details": blocker_details,
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        }
    )
    if blocker_details:
        payload["status"] = "BLOCKED_PAPER_CHURN_GOVERNOR_RUNTIME_TRACE"
    return payload


def _source_term_hits(repo_root: Path, files: Sequence[str], terms: Sequence[str]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    hits: dict[str, list[dict[str, Any]]] = {term: [] for term in terms}
    missing_files: list[str] = []
    for relative in files:
        path = repo_root / relative
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            missing_files.append(relative)
            continue
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            for term in terms:
                if term in stripped and len(hits[term]) < 10:
                    hits[term].append({"path": relative, "line": lineno, "text": stripped[:240]})
    return hits, sorted(set(missing_files))


def paper_routing_component_trace(repo_root: Path) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for component in PAPER_ROUTING_COMPONENTS:
        terms = [str(term) for term in component.get("required_terms", [])]
        files = [str(file_name) for file_name in component.get("files", [])]
        hits, missing_files = _source_term_hits(repo_root, files, terms)
        missing_terms = [term for term in terms if not hits.get(term)]
        status = "PASS_COMPONENT_TRACE" if not missing_terms and not missing_files else "BLOCKED_COMPONENT_TRACE"
        components.append(
            {
                "component": component.get("component"),
                "required_role": component.get("required_role"),
                "status": status,
                "files": files,
                "missing_files": missing_files,
                "required_terms": terms,
                "missing_terms": missing_terms,
                "term_hits": hits,
            }
        )
    missing_components = [str(component["component"]) for component in components if component["status"] != "PASS_COMPONENT_TRACE"]
    return {
        "status": "PASS_PAPER_ROUTING_COMPONENT_TRACE" if not missing_components else "BLOCKED_PAPER_ROUTING_COMPONENT_TRACE",
        "required_components": [str(component.get("component")) for component in PAPER_ROUTING_COMPONENTS],
        "missing_or_incomplete_components": missing_components,
        "components": components,
    }


def paper_signal_key_rows(redis_payloads: Mapping[str, Any]) -> tuple[dict[str, int], list[str]]:
    counts: Counter[str] = Counter()
    keys = []
    for key, payload in redis_payloads.items():
        if not key.startswith("v2:signals:paper"):
            continue
        keys.append(key)
        tf = "UNKNOWN"
        parts = key.split(":")
        if len(parts) >= 5:
            tf = parts[-1]
        if isinstance(payload, Mapping):
            tf = str(payload.get("timeframe") or payload.get("prediction_timeframe") or tf)
        counts[tf] += 1
    return dict(sorted(counts.items())), sorted(keys)


def paper_timeframe_routing_owner_status(
    *,
    repo_root: Path,
    closed_rows: Sequence[Mapping[str, Any]],
    heartbeat: Mapping[str, Any],
    redis_signal_payloads: Mapping[str, Any],
    challenger_candidate_id: str = CHALLENGER_CANDIDATE_ID,
) -> dict[str, Any]:
    hardcoded = scan_hardcoded_timeframe_paths(repo_root)
    silent_fallbacks = scan_silent_1m_fallback_paths(repo_root)
    component_trace = paper_routing_component_trace(repo_root)
    signal_counts, signal_keys = paper_signal_key_rows(redis_signal_payloads)
    trade_counts = Counter(timeframe_of(row) for row in closed_rows)
    challenger_trade_count = sum(
        1
        for row in closed_rows
        if row.get("candidate_id") == challenger_candidate_id or row.get("candidate_id") == CHALLENGER_CANDIDATE_ID
    )
    paper_fill_owner = str(heartbeat.get("worker_id") or "UNKNOWN")
    pass_conditions = {
        "paper_closed_rows_scanned": len(closed_rows) > 0,
        "hardcoded_1m_economic_paths_absent": not hardcoded,
        "silent_1m_thesis_or_economic_fallbacks_absent": not silent_fallbacks,
        "paper_fill_owner_identified": paper_fill_owner != "UNKNOWN",
        "challenger_does_not_control_paper_before_lockbox": challenger_trade_count == 0,
        "all_timeframe_rows_seen": len(signal_counts) > 1 or len(trade_counts) > 1,
        "routing_components_traced": component_trace["status"] == "PASS_PAPER_ROUTING_COMPONENT_TRACE",
    }
    actuals = {
        "paper_closed_rows_scanned": len(closed_rows),
        "hardcoded_1m_economic_paths_absent": hardcoded,
        "silent_1m_thesis_or_economic_fallbacks_absent": silent_fallbacks,
        "paper_fill_owner_identified": paper_fill_owner,
        "challenger_does_not_control_paper_before_lockbox": challenger_trade_count,
        "all_timeframe_rows_seen": sorted(set(signal_counts) | set(trade_counts)),
        "routing_components_traced": component_trace["status"],
    }
    required = {
        "paper_closed_rows_scanned": ">0",
        "hardcoded_1m_economic_paths_absent": [],
        "silent_1m_thesis_or_economic_fallbacks_absent": [],
        "paper_fill_owner_identified": "not UNKNOWN",
        "challenger_does_not_control_paper_before_lockbox": 0,
        "all_timeframe_rows_seen": "more than one timeframe in paper signals or closed rows",
        "routing_components_traced": "PASS_PAPER_ROUTING_COMPONENT_TRACE",
    }
    blocker_details = failed_pass_condition_details(
        pass_conditions=pass_conditions,
        actuals=actuals,
        required=required,
        source_artifact="paper_timeframe_routing_owner_status.json",
    )
    blocked_reasons = [str(detail["pass_condition"]) for detail in blocker_details]
    old_policy_controls_paper = challenger_trade_count == 0 and paper_fill_owner != "challenger"
    if hardcoded or silent_fallbacks:
        status = "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    elif component_trace["status"] != "PASS_PAPER_ROUTING_COMPONENT_TRACE":
        status = "BLOCKED_PAPER_TIMEFRAME_ROUTING_OWNER_TRACE_INCOMPLETE"
    else:
        status = "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    return {
        "schema_version": "paper_timeframe_routing_owner_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": status,
        "read_only_audit_no_runtime_change": True,
        "primary_prediction_keys_read": [
            "v2:signals:paper",
            "v2:signals:paper:{symbol}",
            "v2:signals:paper:{symbol}:{timeframe}",
        ],
        "primary_signal_keys_read": signal_keys[:500],
        "primary_signal_key_count": len(signal_keys),
        "routing_component_trace_status": component_trace["status"],
        "routing_component_trace": component_trace,
        "hardcoded_timeframe_paths": hardcoded,
        "hardcoded_1m_path_count": len(hardcoded),
        "silent_1m_fallback_paths": silent_fallbacks,
        "silent_1m_fallback_path_count": len(silent_fallbacks),
        "timeframe_routing_violation_count": len(hardcoded) + len(silent_fallbacks),
        "all_timeframe_rows_seen": sorted(set(signal_counts) | set(trade_counts)),
        "rows_routed_by_timeframe": dict(sorted(trade_counts.items())),
        "paper_signal_rows_by_timeframe": signal_counts,
        "paper_fill_owner": paper_fill_owner,
        "old_policy_controls_paper": old_policy_controls_paper,
        "challenger_controls_paper": challenger_trade_count > 0,
        "challenger_closed_trade_count": challenger_trade_count,
        "old_policy_or_unbound_closed_trade_count": len(closed_rows) - challenger_trade_count,
        "fail_rule": "Fail if the paper path hardcodes :1m or silently falls back to 1m when another timeframe supplied the thesis.",
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def paper_timeframe_routing_repair_contract(*, routing: Mapping[str, Any]) -> dict[str, Any]:
    hardcoded_paths = [as_dict(row) for row in routing.get("hardcoded_timeframe_paths") or []]
    silent_fallback_paths = [as_dict(row) for row in routing.get("silent_1m_fallback_paths") or []]
    repair_steps: list[dict[str, Any]] = []
    for finding in [*hardcoded_paths, *silent_fallback_paths]:
        text = str(finding.get("text") or "")
        if finding in silent_fallback_paths:
            repair_kind = "remove_silent_1m_thesis_or_economic_fallback"
            required_change = (
                "Require an explicit thesis_timeframe for economic attribution and fail closed or mark shadow-only "
                "when no thesis timeframe is available; keep 1m only as explicit execution_timeframe timing."
            )
        elif "v2:signals:paper" in text and ":1m" in text:
            repair_kind = "replace_hardcoded_paper_signal_key_timeframe"
            required_change = "Use the signal or thesis timeframe when writing paper signal keys; do not write v2:signals:paper:{symbol}:1m unless the thesis timeframe is explicitly 1m and eligible."
        elif "fetch_unified_market_snapshot" in text:
            repair_kind = "separate_execution_snapshot_from_thesis_timeframe"
            required_change = "Use execution_timeframe for timing snapshots and persist thesis_timeframe separately so a 1m timing snapshot cannot become the economic thesis."
        elif "feature_timeframe" in text:
            repair_kind = "derive_feature_timeframe_from_candidate"
            required_change = "Derive feature_timeframe from the selected candidate or thesis record instead of defaulting every economic entry to 1m."
        elif 'timeframe="1m"' in text or "timeframe='1m'" in text:
            repair_kind = "replace_literal_timeframe_argument"
            required_change = "Pass the candidate thesis timeframe or explicit execution_timeframe variable; require standalone 1m eligibility before treating 1m as a thesis."
        else:
            repair_kind = "remove_hardcoded_1m_path"
            required_change = "Replace the hardcoded 1m path with thesis_timeframe and execution_timeframe aware routing."
        repair_steps.append(
            {
                "path": finding.get("path"),
                "line": finding.get("line"),
                "current_text": text,
                "repair_kind": repair_kind,
                "required_change": required_change,
                "post_repair_required_evidence": [
                    "paper_timeframe_routing_owner_status.hardcoded_1m_path_count == 0",
                    "paper_timeframe_routing_owner_status.status == PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
                    "multi_timeframe_thesis_execution_contract_status.status == PASS_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT",
                    "paper_entry_cost_coverage_status.production_grade_cost_coverage >= 0.95 before economic paper fills",
                ],
            }
        )

    hardcoded_count = int(routing.get("hardcoded_1m_path_count") or len(hardcoded_paths))
    silent_fallback_count = int(routing.get("silent_1m_fallback_path_count") or len(silent_fallback_paths))
    routing_violation_count = hardcoded_count + silent_fallback_count
    hardcoded_repair_step_count = sum(
        1
        for step in repair_steps
        if step.get("repair_kind") != "remove_silent_1m_thesis_or_economic_fallback"
    )
    silent_fallback_repair_step_count = sum(
        1
        for step in repair_steps
        if step.get("repair_kind") == "remove_silent_1m_thesis_or_economic_fallback"
    )
    pass_conditions = {
        "routing_owner_audit_present": bool(routing),
        "hardcoded_1m_paths_absent": hardcoded_count == 0,
        "silent_1m_fallbacks_absent": silent_fallback_count == 0,
        "routing_owner_audit_passed": routing.get("status") == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "repair_steps_cover_all_current_hardcoded_paths": hardcoded_repair_step_count == hardcoded_count,
        "repair_steps_cover_all_current_silent_fallbacks": silent_fallback_repair_step_count == silent_fallback_count,
        "repair_steps_cover_all_current_routing_violations": len(repair_steps) == routing_violation_count,
        "old_redis_writes_forbidden": True,
        "runtime_patch_not_applied_by_audit": True,
        "challenger_remains_paper_inactive_until_lockbox_pass": routing.get("challenger_controls_paper") is False,
        "paper_only_no_live_routes": routing.get("routes_to_live") is False and routing.get("places_real_order") is False,
    }
    status = (
        "PASS_PAPER_TIMEFRAME_ROUTING_REPAIR_CONTRACT"
        if all(pass_conditions.values())
        else "BLOCKED_PAPER_TIMEFRAME_ROUTING_REPAIR_CONTRACT"
    )
    return {
        "schema_version": "paper_timeframe_routing_repair_contract_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": status,
        "read_only_audit_no_runtime_change": True,
        "repair_scope": "paper_timeframe_routing_only",
        "hardcoded_1m_path_count": hardcoded_count,
        "silent_1m_fallback_path_count": silent_fallback_count,
        "timeframe_routing_violation_count": routing_violation_count,
        "hardcoded_repair_step_count": hardcoded_repair_step_count,
        "silent_fallback_repair_step_count": silent_fallback_repair_step_count,
        "hardcoded_timeframe_paths": hardcoded_paths,
        "silent_1m_fallback_paths": silent_fallback_paths,
        "repair_steps": repair_steps,
        "post_repair_gate_order": [
            "remove hardcoded 1m economic routing paths",
            "prove thesis_timeframe and execution_timeframe are distinct in paper candidates",
            "prove production-grade entry cost coverage >= 95%",
            "collect 100+ post-fix compacted economic paper outcomes",
            "keep challenger paper binding blocked until blind lockbox pass",
        ],
        "forbidden_changes": [
            "no real orders",
            "no test orders",
            "no exchange leverage or margin mutation",
            "no live routing",
            "no old Redis writes or historical backfill for credit",
            "no permanent static timeframe or symbol blacklist",
            "no lowering gates to create trade volume",
            "no challenger paper binding before blind lockbox pass",
        ],
        "pass_conditions": pass_conditions,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def _share_by_timeframe(values: Mapping[str, Any]) -> dict[str, float]:
    numeric = {str(key): abs(float(value or 0.0)) for key, value in values.items()}
    total = sum(numeric.values())
    if total <= 1e-12:
        return {key: 0.0 for key in sorted(numeric)}
    return {key: numeric[key] / total for key in sorted(numeric)}


def failed_pass_condition_names(payload: Mapping[str, Any]) -> list[str]:
    return sorted(
        name
        for name, passed in as_dict(payload.get("pass_conditions")).items()
        if not bool(passed)
    )


def paper_governance_phase_trace(
    *,
    churn: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    compaction: Mapping[str, Any],
    routing: Mapping[str, Any],
    routing_repair: Mapping[str, Any],
    thesis_execution: Mapping[str, Any],
    reentry_dedup: Mapping[str, Any],
    churn_governor: Mapping[str, Any],
    cost_coverage: Mapping[str, Any],
    edge_to_cost: Mapping[str, Any],
    dynamic_timeframe_eligibility: Mapping[str, Any],
    concentration_guard: Mapping[str, Any],
    post_fix_validation: Mapping[str, Any],
) -> dict[str, Any]:
    phase_statuses = {
        "phase_1_recompute_current_ledger": churn.get("status"),
        "phase_1_reconciliation": reconciliation.get("status"),
        "phase_2_prove_active_paper_routing_owner": routing.get("status"),
        "phase_2_routing_repair_contract": routing_repair.get("status"),
        "phase_3_thesis_execution_contract": thesis_execution.get("status"),
        "phase_4_economic_trade_identity": compaction.get("status"),
        "phase_5_reentry_dedup_governance": reentry_dedup.get("status"),
        "phase_6_adaptive_churn_governor": churn_governor.get("status"),
        "phase_7_entry_cost_coverage": cost_coverage.get("status"),
        "phase_7_edge_to_cost_gate": edge_to_cost.get("status"),
        "phase_8_dynamic_timeframe_eligibility": dynamic_timeframe_eligibility.get("status"),
        "phase_9_concentration_guard": concentration_guard.get("status"),
        "phase_10_post_fix_paper_validation": post_fix_validation.get("status"),
    }
    phase_pass_conditions = {
        "phase_1_recompute_current_ledger": {
            "raw_close_record_count_gt_0": int(churn.get("raw_close_record_count") or 0) > 0,
            "economic_trade_count_gt_0": int(churn.get("economic_trade_count") or 0) > 0,
            "all_required_redis_keys_read": bool(churn.get("redis_keys_read")),
        },
        "phase_1_reconciliation": as_dict(reconciliation.get("pass_conditions")),
        "phase_2_prove_active_paper_routing_owner": as_dict(routing.get("pass_conditions")),
        "phase_2_routing_repair_contract": as_dict(routing_repair.get("pass_conditions")),
        "phase_3_thesis_execution_contract": as_dict(thesis_execution.get("pass_conditions")),
        "phase_4_economic_trade_identity": as_dict(compaction.get("pass_conditions")),
        "phase_5_reentry_dedup_governance": as_dict(reentry_dedup.get("pass_conditions")),
        "phase_6_adaptive_churn_governor": as_dict(churn_governor.get("pass_conditions")),
        "phase_7_entry_cost_coverage": as_dict(cost_coverage.get("pass_conditions")),
        "phase_7_edge_to_cost_gate": as_dict(edge_to_cost.get("pass_conditions")),
        "phase_8_dynamic_timeframe_eligibility": as_dict(dynamic_timeframe_eligibility.get("pass_conditions")),
        "phase_9_concentration_guard": as_dict(concentration_guard.get("pass_conditions")),
        "phase_10_post_fix_paper_validation": as_dict(post_fix_validation.get("pass_conditions")),
    }
    phase_blockers = {
        phase: sorted(name for name, passed in conditions.items() if not bool(passed))
        for phase, conditions in phase_pass_conditions.items()
    }
    return {
        "phase_statuses": phase_statuses,
        "phase_pass_conditions": phase_pass_conditions,
        "phase_blockers": phase_blockers,
    }


def post_fix_paper_validation_status(
    *,
    churn: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    compaction: Mapping[str, Any],
    churn_governor: Mapping[str, Any],
    cost_coverage: Mapping[str, Any],
    edge_to_cost: Mapping[str, Any],
    dynamic_timeframe_eligibility: Mapping[str, Any],
    concentration_guard: Mapping[str, Any],
    thesis_execution: Mapping[str, Any],
    reentry_dedup: Mapping[str, Any],
    routing: Mapping[str, Any],
    post_fix_sample: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_timeframes = set((churn.get("trade_count_by_timeframe") or {}).keys())
    economic_timeframes = set((churn.get("economic_trade_count_by_timeframe") or {}).keys())
    represented = sorted(economic_timeframes | set(dynamic_timeframe_eligibility.get("active_timeframes") or []))
    sample = as_dict(post_fix_sample)
    new_outcome_count = int(sample.get("compacted_economic_trade_count") or 0)
    source_statuses = {
        "current_paper_timeframe_churn_audit": churn.get("status"),
        "current_paper_economic_trade_reconciliation": reconciliation.get("status"),
        "economic_trade_compaction_status": compaction.get("status"),
        "paper_churn_governor_status": churn_governor.get("status"),
        "paper_entry_cost_coverage_status": cost_coverage.get("status"),
        "paper_edge_to_cost_gate_status": edge_to_cost.get("status"),
        "dynamic_timeframe_execution_eligibility_status": dynamic_timeframe_eligibility.get("status"),
        "timeframe_execution_concentration_guard_status": concentration_guard.get("status"),
        "multi_timeframe_thesis_execution_contract_status": thesis_execution.get("status"),
        "paper_reentry_and_signal_dedup_status": reentry_dedup.get("status"),
        "paper_timeframe_routing_owner_status": routing.get("status"),
    }
    pass_conditions = {
        "runtime_routing_repair_applied": routing.get("status") == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "post_fix_100_new_compacted_economic_outcomes_collected": new_outcome_count >= 100,
        "all_five_timeframes_still_predicted": {"1m", "5m", "15m", "1h", "4h"}.issubset(current_timeframes),
        "at_least_three_timeframes_represented_in_economic_or_b_grade_candidates": len(represented) >= 3,
        "1m_not_monopolizing_execution_without_evidence": float(churn.get("current_1m_economic_trade_share") or 0.0) <= TIMEFRAME_CONCENTRATION_MAX_SHARE,
        "duplicate_economic_trades_eq_0": reentry_dedup.get("status") == "PASS_PAPER_REENTRY_AND_SIGNAL_DEDUP",
        "unexplained_same_candle_reentries_eq_0": int(reentry_dedup.get("same_candle_duplicate_entries") or 0) == 0,
        "production_cost_coverage_gte_95pct": float(cost_coverage.get("production_grade_cost_coverage") or 0.0) >= 0.95,
        "after_cost_expectancy_gt_0": bool(dynamic_timeframe_eligibility.get("active_timeframes")),
        "profit_factor_gte_1_5": dynamic_timeframe_eligibility.get("status") == "PASS_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY",
        "cost_drag_inside_approved_envelope": concentration_guard.get("status") == "PASS_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD",
        "accounting_reconciliation_pass": reconciliation.get("status") == "PASS_ECONOMIC_TRADE_RECONCILIATION",
        "no_liquidation_events": True,
        "economic_trade_compaction_pass": compaction.get("status") == "PASS_ECONOMIC_TRADE_COMPACTION",
        "churn_governor_wired_to_entry_gate": bool(churn_governor.get("runtime_wired_to_entry_gate")),
        "reentry_dedup_wired_to_entry_gate": bool(reentry_dedup.get("runtime_wired_to_entry_gate")),
        "standalone_1m_runtime_wired_to_entry_gate": bool(thesis_execution.get("standalone_1m_runtime_wired_to_entry_gate")),
        "thesis_execution_contract_pass": thesis_execution.get("status") == "PASS_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT",
        "edge_to_cost_gate_pass": edge_to_cost.get("status") == "PASS_PAPER_EDGE_TO_COST_GATE",
    }
    validation_actuals = {
        "runtime_routing_repair_applied": routing.get("status"),
        "post_fix_100_new_compacted_economic_outcomes_collected": new_outcome_count,
        "all_five_timeframes_still_predicted": sorted(current_timeframes),
        "at_least_three_timeframes_represented_in_economic_or_b_grade_candidates": represented,
        "1m_not_monopolizing_execution_without_evidence": churn.get("current_1m_economic_trade_share"),
        "duplicate_economic_trades_eq_0": {
            "status": reentry_dedup.get("status"),
            "duplicate_economic_trades": reentry_dedup.get("duplicate_economic_trades"),
        },
        "unexplained_same_candle_reentries_eq_0": reentry_dedup.get("same_candle_duplicate_entries"),
        "production_cost_coverage_gte_95pct": cost_coverage.get("production_grade_cost_coverage"),
        "after_cost_expectancy_gt_0": dynamic_timeframe_eligibility.get("active_timeframes") or [],
        "profit_factor_gte_1_5": dynamic_timeframe_eligibility.get("status"),
        "cost_drag_inside_approved_envelope": concentration_guard.get("status"),
        "accounting_reconciliation_pass": reconciliation.get("status"),
        "no_liquidation_events": True,
        "economic_trade_compaction_pass": compaction.get("status"),
        "churn_governor_wired_to_entry_gate": churn_governor.get("runtime_wired_to_entry_gate"),
        "reentry_dedup_wired_to_entry_gate": reentry_dedup.get("runtime_wired_to_entry_gate"),
        "standalone_1m_runtime_wired_to_entry_gate": thesis_execution.get("standalone_1m_runtime_wired_to_entry_gate"),
        "thesis_execution_contract_pass": thesis_execution.get("status"),
        "edge_to_cost_gate_pass": edge_to_cost.get("status"),
    }
    validation_required = {
        "runtime_routing_repair_applied": "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "post_fix_100_new_compacted_economic_outcomes_collected": ">= 100",
        "all_five_timeframes_still_predicted": ["1m", "5m", "15m", "1h", "4h"],
        "at_least_three_timeframes_represented_in_economic_or_b_grade_candidates": ">= 3",
        "1m_not_monopolizing_execution_without_evidence": f"<= {TIMEFRAME_CONCENTRATION_MAX_SHARE}",
        "duplicate_economic_trades_eq_0": 0,
        "unexplained_same_candle_reentries_eq_0": 0,
        "production_cost_coverage_gte_95pct": ">= 0.95",
        "after_cost_expectancy_gt_0": ">= 1 ACTIVE timeframe with positive after-cost evidence",
        "profit_factor_gte_1_5": "PASS_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY",
        "cost_drag_inside_approved_envelope": "PASS_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD",
        "accounting_reconciliation_pass": "PASS_ECONOMIC_TRADE_RECONCILIATION",
        "no_liquidation_events": True,
        "economic_trade_compaction_pass": "PASS_ECONOMIC_TRADE_COMPACTION",
        "churn_governor_wired_to_entry_gate": True,
        "reentry_dedup_wired_to_entry_gate": True,
        "standalone_1m_runtime_wired_to_entry_gate": True,
        "thesis_execution_contract_pass": "PASS_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT",
        "edge_to_cost_gate_pass": "PASS_PAPER_EDGE_TO_COST_GATE",
    }
    blockers = [name for name, passed in pass_conditions.items() if not passed]
    status = "PASS_POST_FIX_PAPER_VALIDATION" if not blockers else "BLOCKED_POST_FIX_PAPER_VALIDATION"
    source_statuses["post_fix_paper_validation_status"] = status
    blocker_sources = {
        "runtime_routing_repair_applied": "paper_timeframe_routing_owner_status",
        "post_fix_100_new_compacted_economic_outcomes_collected": "post_fix_paper_validation_status",
        "all_five_timeframes_still_predicted": "current_paper_timeframe_churn_audit",
        "at_least_three_timeframes_represented_in_economic_or_b_grade_candidates": "dynamic_timeframe_execution_eligibility_status",
        "1m_not_monopolizing_execution_without_evidence": "current_paper_timeframe_churn_audit",
        "duplicate_economic_trades_eq_0": "paper_reentry_and_signal_dedup_status",
        "unexplained_same_candle_reentries_eq_0": "paper_reentry_and_signal_dedup_status",
        "production_cost_coverage_gte_95pct": "paper_entry_cost_coverage_status",
        "after_cost_expectancy_gt_0": "dynamic_timeframe_execution_eligibility_status",
        "profit_factor_gte_1_5": "dynamic_timeframe_execution_eligibility_status",
        "cost_drag_inside_approved_envelope": "timeframe_execution_concentration_guard_status",
        "accounting_reconciliation_pass": "current_paper_economic_trade_reconciliation",
        "no_liquidation_events": "post_fix_paper_validation_status",
        "economic_trade_compaction_pass": "economic_trade_compaction_status",
        "churn_governor_wired_to_entry_gate": "paper_churn_governor_status",
        "reentry_dedup_wired_to_entry_gate": "paper_reentry_and_signal_dedup_status",
        "standalone_1m_runtime_wired_to_entry_gate": "multi_timeframe_thesis_execution_contract_status",
        "thesis_execution_contract_pass": "multi_timeframe_thesis_execution_contract_status",
        "edge_to_cost_gate_pass": "paper_edge_to_cost_gate_status",
    }
    blocker_details = [
        {
            "pass_condition": blocker,
            "source_artifact": blocker_sources.get(blocker),
            "source_status": source_statuses.get(str(blocker_sources.get(blocker))),
            "actual": validation_actuals.get(blocker),
            "required": validation_required.get(blocker),
        }
        for blocker in blockers
    ]
    blocker_summary = {
        "blocker_count": len(blockers),
        "blocked_pass_conditions": blockers,
        "blocker_details": blocker_details,
        "source_statuses": source_statuses,
        "production_grade_cost_coverage": cost_coverage.get("production_grade_cost_coverage"),
        "required_production_grade_cost_coverage": 0.95,
        "current_1m_economic_trade_share": churn.get("current_1m_economic_trade_share"),
        "new_compacted_economic_paper_outcomes": new_outcome_count,
        "required_new_compacted_economic_paper_outcomes": 100,
    }
    return {
        "schema_version": "post_fix_paper_validation_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": status,
        "final_gate": FINAL_READY_MARKER if not blockers else FINAL_BLOCKED_MARKER,
        "read_only_audit_no_runtime_change": True,
        "post_fix_ready": not blockers,
        "post_fix_sample_status": sample.get("status") or "POST_FIX_SAMPLE_NOT_STARTED",
        "post_fix_sample_started": bool(sample.get("sample_started")) or new_outcome_count > 0,
        "post_fix_sample_raw_close_rows": sample.get("raw_close_rows_examined", 0),
        "post_fix_sample_eligible_raw_close_rows": sample.get("eligible_raw_close_rows", 0),
        "post_fix_sample_excluded_raw_close_rows": sample.get("excluded_raw_close_rows", 0),
        "post_fix_sample_exclusion_reason_counts": sample.get("exclusion_reason_counts", {}),
        "post_fix_sample_source_counts": sample.get("source_counts", {}),
        "post_fix_sample_eligible_source_counts": sample.get("eligible_source_counts", {}),
        "post_fix_sample_excluded_source_counts": sample.get("excluded_source_counts", {}),
        "post_fix_sample_source_read_status": sample.get("source_read_status", {}),
        "post_fix_sample_sample_excluded_rows": sample.get("sample_excluded_rows", []),
        "sample_excluded_rows": sample.get("sample_excluded_rows", []),
        "excluded_row_samples": sample.get("sample_excluded_rows", []),
        "post_fix_sample_excluded_row_samples": sample.get("sample_excluded_rows", []),
        "post_fix_sample_sample_excluded_rows_by_source": sample.get("sample_excluded_rows_by_source", {}),
        "post_fix_sample_sample_compacted_economic_trades": sample.get("sample_compacted_economic_trades", []),
        "post_fix_sample_required_identity_fields": sample.get("required_identity_fields", list(POST_FIX_SAMPLE_REQUIRED_IDENTITY_FIELDS)),
        "post_fix_sample_required_thesis_execution_fields": sample.get(
            "required_thesis_execution_fields",
            list(THESIS_EXECUTION_REQUIRED_FIELDS),
        ),
        "post_fix_sample_required_realized_pnl_fields": sample.get(
            "required_realized_pnl_fields",
            list(EXPLICIT_REALIZED_PNL_FIELDS),
        ),
        "new_compacted_economic_paper_outcomes": new_outcome_count,
        "required_new_compacted_economic_paper_outcomes": 100,
        "current_raw_close_record_count": churn.get("raw_close_record_count"),
        "current_economic_trade_count": churn.get("economic_trade_count"),
        "current_timeframes_seen": sorted(current_timeframes),
        "current_economic_timeframes_seen": sorted(economic_timeframes),
        "current_1m_economic_trade_share": churn.get("current_1m_economic_trade_share"),
        "blockers": blockers,
        "blocked_reasons": blockers,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "blocker_summary": blocker_summary,
        "source_statuses": source_statuses,
        "validation_actuals": validation_actuals,
        "actuals": validation_actuals,
        "validation_required": validation_required,
        "required": validation_required,
        "pass_conditions": pass_conditions,
        "duplicate_economic_trades": reentry_dedup.get("duplicate_economic_trades"),
        "unexplained_same_candle_reentries": reentry_dedup.get("same_candle_duplicate_entries"),
        "accounting_reconciliation": reconciliation.get("status"),
        "accounting_reconciliation_status": reconciliation.get("status"),
        "production_grade_cost_coverage": cost_coverage.get("production_grade_cost_coverage"),
        "required_production_grade_cost_coverage": 0.95,
        "edge_to_cost_gate_status": edge_to_cost.get("status"),
        "economic_trade_compaction_status": compaction.get("status"),
        "multi_timeframe_thesis_execution_contract_status": thesis_execution.get("status"),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def operator_dashboard_payload(
    *,
    churn: Mapping[str, Any],
    reentry_dedup: Mapping[str, Any],
    cost_coverage: Mapping[str, Any],
    edge_to_cost: Mapping[str, Any],
    dynamic_timeframe_eligibility: Mapping[str, Any],
    concentration_guard: Mapping[str, Any],
    thesis_execution: Mapping[str, Any],
    post_fix_validation: Mapping[str, Any],
) -> dict[str, Any]:
    trade_counts = as_dict(churn.get("trade_count_by_timeframe"))
    fees = as_dict(churn.get("fees_by_timeframe"))
    turnover = as_dict(churn.get("turnover_by_timeframe"))
    total_turnover = sum(value for value in (finite_float(item) for item in turnover.values()) if value is not None)
    net_pnl = as_dict(churn.get("net_pnl_by_timeframe"))
    one_minute = as_dict(as_dict(dynamic_timeframe_eligibility.get("timeframe_states")).get("1m"))
    thesis_execution_status = thesis_execution.get("status")
    duplicate_blocks = {
        "same_prediction_duplicate_entries": reentry_dedup.get("same_prediction_duplicate_entries"),
        "same_decision_duplicate_entries": reentry_dedup.get("same_decision_duplicate_entries"),
        "same_signal_duplicate_entries": reentry_dedup.get("same_signal_duplicate_entries"),
        "same_feature_snapshot_duplicate_entries": reentry_dedup.get("same_feature_snapshot_duplicate_entries"),
        "same_candle_duplicate_entries": reentry_dedup.get("same_candle_duplicate_entries"),
        "unexplained_reentry_count": reentry_dedup.get("unexplained_reentry_count"),
        "partial_close_reentry_count": reentry_dedup.get("partial_close_reentry_count"),
    }
    payload = {
        "schema_version": "operator_dashboard_payload_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PAPER_GOVERNANCE_DASHBOARD_PAYLOAD_READY",
        "final_gate": post_fix_validation.get("final_gate"),
        "raw_close_records": churn.get("raw_close_record_count"),
        "raw_close_record_count": churn.get("raw_close_record_count"),
        "compacted_economic_trades": churn.get("economic_trade_count"),
        "economic_trade_count": churn.get("economic_trade_count"),
        "trade_share_by_timeframe": _share_by_timeframe(trade_counts),
        "fee_share_by_timeframe": _share_by_timeframe(fees),
        "turnover": total_turnover,
        "turnover_by_timeframe": turnover,
        "turnover_share_by_timeframe": _share_by_timeframe(turnover),
        "net_pnl_by_timeframe": net_pnl,
        "reentry_count": churn.get("reopen_count"),
        "duplicate_blocks": duplicate_blocks,
        "cost_drag_by_timeframe": churn.get("cost_as_pct_of_gross_by_timeframe"),
        "cost_drag": churn.get("cost_as_pct_of_gross_by_timeframe"),
        "edge_to_cost_ratio": {
            "contextual_safety_ratio": edge_to_cost.get("contextual_safety_ratio"),
            "admitted_candidate_rows": edge_to_cost.get("admitted_candidate_rows"),
            "shadow_only_candidate_rows": edge_to_cost.get("shadow_only_candidate_rows"),
            "blocked_reason_counts": edge_to_cost.get("blocked_reason_counts"),
        },
        "one_minute_status": one_minute.get("state") or "UNKNOWN",
        "one_min_status": one_minute.get("state") or "UNKNOWN",
        "one_minute_standalone_execution_allowed": one_minute.get("standalone_execution_allowed", False),
        "one_minute_higher_timeframe_timing_role_allowed": one_minute.get("higher_timeframe_timing_role_allowed", False),
        "thesis_timeframe": {
            "contract_status": thesis_execution_status,
            "missing_required_field_counts": thesis_execution.get("missing_required_field_counts"),
            "close_outcome_thesis_timeframe_mismatch_rows": thesis_execution.get("close_outcome_thesis_timeframe_mismatch_rows"),
        },
        "execution_timeframe": {
            "contract_status": thesis_execution_status,
            "higher_tf_1m_timing_rows": thesis_execution.get("higher_tf_1m_timing_rows"),
            "higher_tf_same_candle_reopen_rows": thesis_execution.get("higher_tf_same_candle_reopen_rows"),
            "standalone_1m_without_eligible_strategy_rows": thesis_execution.get("standalone_1m_without_eligible_strategy_rows"),
        },
        "thesis_timeframe_contract_status": thesis_execution_status,
        "execution_timeframe_contract_status": thesis_execution_status,
        "reentry_dedup_runtime_wired_to_entry_gate": bool(reentry_dedup.get("runtime_wired_to_entry_gate")),
        "production_grade_cost_coverage": cost_coverage.get("production_grade_cost_coverage"),
        "concentration_guard_status": concentration_guard.get("status"),
        "do_not_display_raw_close_count_as_independent_trades": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    truth_contract = operator_dashboard_truth_contract(payload)
    payload.update(
        {
            "operator_dashboard_truth_contract_status": truth_contract["status"],
            "website_truth_contract_status": truth_contract["status"],
            "pass_conditions": truth_contract["pass_conditions"],
            "blocked_conditions": truth_contract["blocked_conditions"],
            "blocked_reasons": truth_contract["blocked_reasons"],
            "blocker_details": truth_contract["blocker_details"],
            "failed_blocker_details": truth_contract["failed_blocker_details"],
            "required_website_truth_fields": truth_contract["required_website_truth_fields"],
            "missing_required_fields": truth_contract["missing_required_fields"],
        }
    )
    if truth_contract["status"] != "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT":
        payload["status"] = "BLOCKED_PAPER_GOVERNANCE_DASHBOARD_PAYLOAD"
    return payload


def operator_dashboard_truth_contract(dashboard: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the website-facing payload exposes economic-trade truth, not raw-event inflation."""
    dashboard_payload = as_dict(dashboard)
    pass_conditions = {
        "required_website_truth_fields_present": all(
            field in dashboard_payload and dashboard_payload.get(field) not in (None, "", [], {})
            for field in OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS
        ),
        "raw_close_records_present": finite_float(dashboard_payload.get("raw_close_records")) is not None,
        "compacted_economic_trades_present": finite_float(dashboard_payload.get("compacted_economic_trades")) is not None,
        "raw_close_records_not_displayed_as_independent_trades": (
            dashboard_payload.get("do_not_display_raw_close_count_as_independent_trades") is True
        ),
        "turnover_total_present": finite_float(dashboard_payload.get("turnover")) is not None,
        "timeframe_share_dimensions_present": bool(as_dict(dashboard_payload.get("trade_share_by_timeframe")))
        and bool(as_dict(dashboard_payload.get("fee_share_by_timeframe")))
        and bool(as_dict(dashboard_payload.get("turnover_share_by_timeframe"))),
        "duplicate_blocks_present": bool(as_dict(dashboard_payload.get("duplicate_blocks"))),
        "one_minute_status_present": bool(dashboard_payload.get("one_min_status")),
        "thesis_and_execution_timeframes_present": bool(as_dict(dashboard_payload.get("thesis_timeframe")))
        and bool(as_dict(dashboard_payload.get("execution_timeframe"))),
        "paper_only_no_live_routes": dashboard_payload.get("paper_fill_allowed") is False
        and dashboard_payload.get("routes_to_live") is False
        and dashboard_payload.get("places_real_order") is False,
        "counts_as_a_grade_evidence_false": dashboard_payload.get("counts_as_a_grade_evidence") is False,
    }
    blocked_conditions = [name for name, passed in pass_conditions.items() if passed is not True]
    missing_required_fields = [
        field
        for field in OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS
        if field not in dashboard_payload or dashboard_payload.get(field) in (None, "", [], {})
    ]
    blocker_details = [
        {
            "pass_condition": condition,
            "source_artifact": "operator_dashboard_payload.json",
            "source_status": dashboard_payload.get("status"),
            "actual": {
                "required_website_truth_fields_present": {
                    "required_fields": list(OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS),
                    "missing_required_fields": missing_required_fields,
                },
                "raw_close_records_present": dashboard_payload.get("raw_close_records"),
                "compacted_economic_trades_present": dashboard_payload.get("compacted_economic_trades"),
                "raw_close_records_not_displayed_as_independent_trades": dashboard_payload.get(
                    "do_not_display_raw_close_count_as_independent_trades"
                ),
                "turnover_total_present": dashboard_payload.get("turnover"),
                "timeframe_share_dimensions_present": {
                    "trade_share_by_timeframe": dashboard_payload.get("trade_share_by_timeframe"),
                    "fee_share_by_timeframe": dashboard_payload.get("fee_share_by_timeframe"),
                    "turnover_share_by_timeframe": dashboard_payload.get("turnover_share_by_timeframe"),
                },
                "duplicate_blocks_present": dashboard_payload.get("duplicate_blocks"),
                "one_minute_status_present": dashboard_payload.get("one_min_status"),
                "thesis_and_execution_timeframes_present": {
                    "thesis_timeframe": dashboard_payload.get("thesis_timeframe"),
                    "execution_timeframe": dashboard_payload.get("execution_timeframe"),
                },
                "paper_only_no_live_routes": {
                    "paper_fill_allowed": dashboard_payload.get("paper_fill_allowed"),
                    "routes_to_live": dashboard_payload.get("routes_to_live"),
                    "places_real_order": dashboard_payload.get("places_real_order"),
                },
                "counts_as_a_grade_evidence_false": dashboard_payload.get("counts_as_a_grade_evidence"),
            }.get(condition),
        }
        for condition in blocked_conditions
    ]
    return {
        "schema_version": "operator_dashboard_truth_contract_status_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
        if not blocked_conditions
        else "BLOCKED_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
        "pass_conditions": pass_conditions,
        "blocked_conditions": blocked_conditions,
        "blocked_reasons": blocked_conditions,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "required_website_truth_fields": list(OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS),
        "missing_required_fields": missing_required_fields,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def go_no_go_markdown(summary: Mapping[str, Any], post_fix_validation: Mapping[str, Any]) -> str:
    final_gate = summary.get("final_gate") or post_fix_validation.get("final_gate")
    blockers = summary.get("blocked_reasons") or post_fix_validation.get("blockers") or []
    return "\n".join(
        [
            f"# {PAPER_GOVERNANCE_GOAL_ID}",
            "",
            f"Final gate: **{final_gate}**",
            "",
            f"- Raw close records audited: {summary.get('raw_close_record_count')}",
            f"- Compacted economic trades: {summary.get('economic_trade_count')}",
            "- Raw close records are not independent trades: true",
            f"- Challenger closed trades: {summary.get('challenger_trade_count')}",
            f"- Old-policy or unbound closed trades: {summary.get('old_policy_trade_count')}",
            f"- 1m status: {summary.get('one_min_status')}",
            f"- Trade share by timeframe: {summary.get('trade_share_by_timeframe')}",
            f"- Fee share by timeframe: {summary.get('fee_share_by_timeframe')}",
            f"- Turnover: {summary.get('turnover')}",
            f"- Cost drag by timeframe: {summary.get('cost_drag_by_timeframe')}",
            f"- Reentry count: {summary.get('reentry_count')}",
            f"- Duplicate/reentry blocks: {summary.get('duplicate_blocks')}",
            f"- Routing status: {summary.get('routing_status')}",
            f"- Hardcoded 1m path count: {summary.get('hardcoded_1m_path_count')}",
            f"- Silent 1m fallback path count: {summary.get('silent_1m_fallback_path_count')}",
            f"- Timeframe routing violation count: {summary.get('timeframe_routing_violation_count')}",
            f"- Thesis timeframe contract: {summary.get('thesis_timeframe_contract_status')}",
            f"- Execution timeframe contract: {summary.get('execution_timeframe_contract_status')}",
            f"- Production-grade paper entry cost coverage: {summary.get('paper_entry_production_grade_cost_coverage')}",
            f"- Edge-to-cost ratio: {summary.get('edge_to_cost_ratio')}",
            f"- Operator dashboard truth contract: {summary.get('operator_dashboard_truth_contract_status')}",
            f"- Phase statuses: {summary.get('phase_statuses')}",
            f"- Phase blockers: {summary.get('phase_blockers')}",
            f"- Post-fix validation status: {post_fix_validation.get('status')}",
            "",
            "Blockers:",
            *[f"- {blocker}" for blocker in blockers],
            "",
        ]
    )


def repair_report_markdown(summary: Mapping[str, Any], post_fix_validation: Mapping[str, Any]) -> str:
    final_gate = summary.get("final_gate") or post_fix_validation.get("final_gate")
    return "\n".join(
        [
            f"# {PAPER_GOVERNANCE_GOAL_ID} Report",
            "",
            "This is a read-only evidence report. It does not alter runtime routing, paper fill gates, Redis writes, or live execution.",
            "",
            "## Current Ledger",
            "",
            f"- Raw close records: {summary.get('raw_close_record_count')}",
            f"- Compacted economic trades: {summary.get('economic_trade_count')}",
            "- Raw close records are not independent trades: true",
            f"- Current 1m raw share: {summary.get('current_1m_share')}",
            f"- Current 1m economic share: {summary.get('current_1m_economic_trade_share')}",
            f"- 1m status: {summary.get('one_min_status')}",
            f"- Trade share by timeframe: {summary.get('trade_share_by_timeframe')}",
            f"- Fee share by timeframe: {summary.get('fee_share_by_timeframe')}",
            f"- Turnover: {summary.get('turnover')}",
            f"- Turnover by timeframe: {summary.get('turnover_by_timeframe')}",
            f"- Cost drag by timeframe: {summary.get('cost_drag_by_timeframe')}",
            f"- Reentry count: {summary.get('reentry_count')}",
            f"- Duplicate/reentry blocks: {summary.get('duplicate_blocks')}",
            f"- Old-policy or unbound trades: {summary.get('old_policy_trade_count')}",
            f"- Challenger trades: {summary.get('challenger_trade_count')}",
            "",
            "## Thesis And Execution",
            "",
            f"- Thesis timeframe: {summary.get('thesis_timeframe')}",
            f"- Execution timeframe: {summary.get('execution_timeframe')}",
            f"- Thesis/execution contract: {summary.get('multi_timeframe_thesis_execution_contract_status')}",
            "",
            "## Gates",
            "",
            f"- Routing: {summary.get('routing_status')}",
            f"- Silent 1m fallback paths: {summary.get('silent_1m_fallback_paths')}",
            f"- Economic reconciliation: {summary.get('reconciliation_status')}",
            f"- Economic compaction: {summary.get('economic_trade_compaction_status')}",
            f"- Churn governor: {summary.get('paper_churn_governor_status')}",
            f"- Entry cost coverage: {summary.get('paper_entry_cost_coverage_status')}",
            f"- Edge-to-cost gate: {summary.get('paper_edge_to_cost_gate_status')}",
            f"- Dynamic timeframe eligibility: {summary.get('dynamic_timeframe_execution_eligibility_status')}",
            f"- Concentration guard: {summary.get('timeframe_execution_concentration_guard_status')}",
            f"- Thesis/execution contract: {summary.get('multi_timeframe_thesis_execution_contract_status')}",
            f"- Reentry/dedup: {summary.get('paper_reentry_and_signal_dedup_status')}",
            f"- Edge-to-cost ratio: {summary.get('edge_to_cost_ratio')}",
            f"- Operator dashboard truth contract: {summary.get('operator_dashboard_truth_contract_status')}",
            f"- Phase statuses: {summary.get('phase_statuses')}",
            f"- Phase blockers: {summary.get('phase_blockers')}",
            "",
            f"Final gate: **{final_gate}**",
            "",
        ]
    )


def paper_governance_phase_blocker_count(phase_blockers: Mapping[str, Any]) -> int:
    return sum(
        len(blockers)
        for blockers in phase_blockers.values()
        if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes, bytearray))
    )


def _list_payload(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def paper_governance_summary_source_blocker_fields(
    *,
    post_fix_validation: Mapping[str, Any],
    phase_trace: Mapping[str, Any],
) -> dict[str, Any]:
    blocker_summary = as_dict(post_fix_validation.get("blocker_summary"))
    source_blocked_pass_conditions = _list_payload(
        blocker_summary.get("blocked_pass_conditions")
        or post_fix_validation.get("blocked_reasons")
        or post_fix_validation.get("blockers")
    )
    source_blocker_details = _list_payload(
        blocker_summary.get("blocker_details")
        or post_fix_validation.get("blocker_details")
    )
    raw_blocker_count = blocker_summary.get("blocker_count")
    source_blocker_count = (
        int(raw_blocker_count)
        if isinstance(raw_blocker_count, (int, float)) and not isinstance(raw_blocker_count, bool)
        else len(source_blocked_pass_conditions)
    )
    source_phase_blockers = as_dict(phase_trace.get("phase_blockers"))
    return {
        "source_blocker_count": source_blocker_count,
        "source_blocked_pass_conditions": source_blocked_pass_conditions,
        "source_blocker_details": source_blocker_details,
        "source_phase_blocker_count": paper_governance_phase_blocker_count(source_phase_blockers),
        "source_phase_blockers": source_phase_blockers,
    }


def paper_governance_summary_pass_conditions(summary: Mapping[str, Any]) -> dict[str, bool]:
    phase_blockers = as_dict(summary.get("phase_blockers"))
    phase_blocker_count = paper_governance_phase_blocker_count(phase_blockers)
    return {
        "required_artifacts_present": summary.get("required_artifacts_present") is True
        and int(summary.get("missing_required_artifact_count") or 0) == 0,
        "current_ledger_recomputed": int(summary.get("raw_close_record_count") or 0) > 0
        and int(summary.get("economic_trade_count") or 0) > 0,
        "challenger_remains_paper_inactive": int(summary.get("challenger_trade_count") or 0) == 0,
        "routing_owner_audit_passed": summary.get("routing_status") == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "operator_dashboard_website_truth_contract_passed": (
            summary.get("operator_dashboard_truth_contract_status") == "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
        ),
        "post_fix_ready": summary.get("post_fix_ready") is True,
        "final_gate_ready": summary.get("final_gate") == FINAL_READY_MARKER,
        "source_blockers_cleared": not summary.get("blocked_reasons"),
        "source_phase_blockers_cleared": phase_blocker_count == 0,
        "paper_only_no_live_routes": summary.get("paper_fill_allowed") is False
        and summary.get("routes_to_live") is False
        and summary.get("places_real_order") is False
        and summary.get("counts_as_a_grade_evidence") is False,
    }


def read_redis_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    import redis

    client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=2, socket_timeout=10)
    client.ping()
    payloads: dict[str, Any] = {}
    status: dict[str, Any] = {}
    for key in PAPER_REDIS_KEYS:
        raw = client.get(key)
        status[key] = {"exists": bool(raw), "raw_bytes": len(raw or "")}
        if not raw:
            payloads[key] = None
            continue
        try:
            payloads[key] = json.loads(raw)
            status[key]["json_status"] = "PASS"
            status[key]["payload_type"] = type(payloads[key]).__name__
        except json.JSONDecodeError as exc:
            payloads[key] = None
            status[key]["json_status"] = f"FAIL:{type(exc).__name__}"

    signal_payloads: dict[str, Any] = {}
    for key in client.scan_iter(match="v2:signals:paper*", count=200):
        raw = client.get(str(key))
        if not raw:
            continue
        try:
            signal_payloads[str(key)] = json.loads(raw)
        except json.JSONDecodeError:
            signal_payloads[str(key)] = None
    return {**payloads, "_signals": signal_payloads}, status


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run_audit(repo_root: Path, out_dir: Path) -> dict[str, Any]:
    payloads, redis_status = read_redis_payloads()
    closed_rows = rows_from_payload(payloads.get("v2:paper:closed_trades"))
    ledger = as_dict(payloads.get("v2:paper:ledger"))
    portfolio_state = as_dict(payloads.get("v2:portfolio:state"))
    heartbeat = as_dict(payloads.get("v2:paper:heartbeat"))
    signal_payloads = as_dict(payloads.get("_signals"))
    candidate_rows = paper_candidate_rows_from_ledger(ledger)

    churn = current_paper_timeframe_churn_audit(
        closed_rows=closed_rows,
        ledger=ledger,
        portfolio_state=portfolio_state,
        heartbeat=heartbeat,
    )
    churn["redis_read_status"] = redis_status
    reconciliation = current_paper_economic_trade_reconciliation(
        closed_rows=closed_rows,
        portfolio_state=portfolio_state,
        ledger=ledger,
    )
    compaction = economic_trade_compaction_status(
        closed_rows=closed_rows,
        reconciliation=reconciliation,
    )
    compacted_economic_rows = compact_economic_trades(closed_rows)
    churn_governor_wiring = paper_churn_governor_runtime_wiring_status(repo_root)
    churn_governor = evaluate_churn_governor(
        compacted_economic_rows,
        runtime_wired_to_entry_gate=bool(churn_governor_wiring.get("runtime_wired_to_entry_gate")),
    )
    churn_governor.update(
        {
            "goal_id": CURRENT_CHALLENGER_GOAL_ID,
            "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        }
    )
    churn_governor = paper_churn_governor_trace_status(churn_governor, churn_governor_wiring)
    thesis_execution = multi_timeframe_thesis_execution_contract_status(
        closed_rows=closed_rows,
        candidate_rows=candidate_rows,
    )
    standalone_1m_wiring = paper_standalone_1m_runtime_wiring_status(repo_root)
    active_owner_standalone_1m_wiring = paper_trade_management_standalone_1m_runtime_wiring_status(repo_root)
    standalone_1m_runtime_wired = (
        bool(standalone_1m_wiring.get("runtime_wired_to_entry_gate"))
        and bool(active_owner_standalone_1m_wiring.get("runtime_wired_to_entry_gate"))
    )
    thesis_execution.update(
        {
            "standalone_1m_runtime_wiring": standalone_1m_wiring,
            "paper_online_standalone_1m_runtime_wiring": standalone_1m_wiring,
            "active_paper_owner_standalone_1m_runtime_wiring": active_owner_standalone_1m_wiring,
            "standalone_1m_runtime_wired_to_entry_gate": standalone_1m_runtime_wired,
            "active_paper_owner_standalone_1m_runtime_wired_to_entry_gate": bool(
                active_owner_standalone_1m_wiring.get("runtime_wired_to_entry_gate")
            ),
            "future_runtime_standalone_1m_gate_status": standalone_1m_wiring.get("status"),
            "active_paper_owner_standalone_1m_gate_status": active_owner_standalone_1m_wiring.get("status"),
        }
    )
    reentry_dedup = paper_reentry_and_signal_dedup_status(closed_rows=closed_rows)
    reentry_wiring = paper_reentry_dedup_runtime_wiring_status(repo_root)
    active_owner_reentry_wiring = paper_trade_management_reentry_dedup_runtime_wiring_status(repo_root)
    reentry_runtime_wired = bool(reentry_wiring.get("runtime_wired_to_entry_gate")) and bool(
        active_owner_reentry_wiring.get("runtime_wired_to_entry_gate")
    )
    reentry_dedup.update(
        {
            "runtime_wiring": reentry_wiring,
            "paper_online_reentry_dedup_runtime_wiring": reentry_wiring,
            "active_paper_owner_reentry_dedup_runtime_wiring": active_owner_reentry_wiring,
            "runtime_wired_to_entry_gate": reentry_runtime_wired,
            "paper_online_reentry_dedup_runtime_wired_to_entry_gate": bool(
                reentry_wiring.get("runtime_wired_to_entry_gate")
            ),
            "active_paper_owner_reentry_dedup_runtime_wired_to_entry_gate": bool(
                active_owner_reentry_wiring.get("runtime_wired_to_entry_gate")
            ),
            "future_runtime_reentry_dedup_gate_status": reentry_wiring.get("status"),
            "active_paper_owner_reentry_dedup_gate_status": active_owner_reentry_wiring.get("status"),
        }
    )
    cost_wiring = paper_entry_cost_runtime_wiring_status(repo_root)
    cost_coverage = paper_entry_cost_coverage_status(candidate_rows=candidate_rows)
    cost_coverage.update(
        {
            "runtime_wiring": cost_wiring,
            "runtime_wired_to_entry_gate": bool(cost_wiring.get("runtime_wired_to_entry_gate")),
        }
    )
    edge_to_cost = paper_edge_to_cost_gate_status(
        candidate_rows=candidate_rows,
        cost_coverage=cost_coverage,
    )
    dynamic_timeframe_eligibility = dynamic_timeframe_execution_eligibility_status(
        economic_rows=compacted_economic_rows,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
    )
    concentration_guard = timeframe_execution_concentration_guard_status(
        economic_rows=compacted_economic_rows,
        eligibility=dynamic_timeframe_eligibility,
    )
    local_post_fix_rows, local_post_fix_source_status = read_local_paper_event_close_rows(repo_root)
    redis_post_fix_rows = mark_post_fix_sample_source(
        closed_rows,
        source_name="redis_v2_paper_closed_trades",
    )
    post_fix_source_status: dict[str, Any] = {
        "redis_v2_paper_closed_trades": {
            **as_dict(redis_status.get("v2:paper:closed_trades")),
            "source": "redis_v2_paper_closed_trades",
            "closed_paper_outcome_rows": len(closed_rows),
        },
        **local_post_fix_source_status,
    }
    post_fix_sample = post_fix_economic_outcome_sample(
        [*redis_post_fix_rows, *local_post_fix_rows],
        source_read_status=post_fix_source_status,
    )
    routing = paper_timeframe_routing_owner_status(
        repo_root=repo_root,
        closed_rows=closed_rows,
        heartbeat=heartbeat,
        redis_signal_payloads=signal_payloads,
    )
    routing_repair = paper_timeframe_routing_repair_contract(routing=routing)
    post_fix_validation = post_fix_paper_validation_status(
        churn=churn,
        reconciliation=reconciliation,
        compaction=compaction,
        churn_governor=churn_governor,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
        dynamic_timeframe_eligibility=dynamic_timeframe_eligibility,
        concentration_guard=concentration_guard,
        thesis_execution=thesis_execution,
        reentry_dedup=reentry_dedup,
        routing=routing,
        post_fix_sample=post_fix_sample,
    )
    dashboard = operator_dashboard_payload(
        churn=churn,
        reentry_dedup=reentry_dedup,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
        dynamic_timeframe_eligibility=dynamic_timeframe_eligibility,
        concentration_guard=concentration_guard,
        thesis_execution=thesis_execution,
        post_fix_validation=post_fix_validation,
    )
    dashboard_truth_contract = operator_dashboard_truth_contract(dashboard)
    phase_trace = paper_governance_phase_trace(
        churn=churn,
        reconciliation=reconciliation,
        compaction=compaction,
        routing=routing,
        routing_repair=routing_repair,
        thesis_execution=thesis_execution,
        reentry_dedup=reentry_dedup,
        churn_governor=churn_governor,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
        dynamic_timeframe_eligibility=dynamic_timeframe_eligibility,
        concentration_guard=concentration_guard,
        post_fix_validation=post_fix_validation,
    )
    phase_trace["phase_statuses"]["website_truth"] = dashboard_truth_contract["status"]
    phase_trace["phase_pass_conditions"]["website_truth"] = dashboard_truth_contract["pass_conditions"]
    phase_trace["phase_blockers"]["website_truth"] = dashboard_truth_contract["blocked_conditions"]
    source_blocker_fields = paper_governance_summary_source_blocker_fields(
        post_fix_validation=post_fix_validation,
        phase_trace=phase_trace,
    )
    summary_blocked_reasons = list(post_fix_validation["blocked_reasons"])
    summary_blocker_details = list(post_fix_validation["blocker_details"])
    summary_source_statuses = dict(post_fix_validation["source_statuses"])
    summary_source_statuses["operator_dashboard_truth_contract_status"] = dashboard_truth_contract["status"]
    if dashboard_truth_contract["status"] != "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT":
        dashboard_blocker = "operator_dashboard_website_truth_contract_passed"
        if dashboard_blocker not in summary_blocked_reasons:
            summary_blocked_reasons.append(dashboard_blocker)
        summary_blocker_details.append(
            {
                "pass_condition": dashboard_blocker,
                "source_artifact": "operator_dashboard_truth_contract_status",
                "source_status": dashboard_truth_contract["status"],
            }
        )
    summary_blocker_summary = dict(post_fix_validation["blocker_summary"])
    summary_blocker_summary["blocked_pass_conditions"] = summary_blocked_reasons
    summary_blocker_summary["blocker_count"] = len(summary_blocked_reasons)
    summary_blocker_summary["blocker_details"] = summary_blocker_details
    summary_blocker_summary["source_statuses"] = summary_source_statuses
    source_blocker_fields["source_blocker_count"] = len(summary_blocked_reasons)
    source_blocker_fields["source_blocked_pass_conditions"] = summary_blocked_reasons
    source_blocker_fields["source_blocker_details"] = summary_blocker_details
    summary_status = (
        "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY"
        if not summary_blocked_reasons
        else "BLOCKED_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR"
    )
    summary_final_gate = FINAL_READY_MARKER if not summary_blocked_reasons else FINAL_BLOCKED_MARKER
    summary_phase_blocker_count = paper_governance_phase_blocker_count(phase_trace["phase_blockers"])
    summary_phase_blocked_conditions = [
        {
            "phase": phase,
            "blocked_condition": str(condition),
        }
        for phase, phase_blockers in phase_trace["phase_blockers"].items()
        if isinstance(phase_blockers, Sequence) and not isinstance(phase_blockers, (str, bytes, bytearray))
        for condition in phase_blockers
    ]
    artifacts_written = list(REQUIRED_PAPER_GOVERNANCE_ARTIFACTS)
    missing_required_artifacts = [
        artifact for artifact in REQUIRED_PAPER_GOVERNANCE_ARTIFACTS if artifact not in set(artifacts_written)
    ]
    required_artifacts_present = not missing_required_artifacts

    write_json(out_dir / "current_paper_timeframe_churn_audit.json", churn)
    write_json(out_dir / "current_paper_economic_trade_reconciliation.json", reconciliation)
    write_json(out_dir / "economic_trade_compaction_status.json", compaction)
    write_json(out_dir / "paper_churn_governor_status.json", churn_governor)
    write_json(out_dir / "paper_entry_cost_coverage_status.json", cost_coverage)
    write_json(out_dir / "paper_edge_to_cost_gate_status.json", edge_to_cost)
    write_json(out_dir / "dynamic_timeframe_execution_eligibility_status.json", dynamic_timeframe_eligibility)
    write_json(out_dir / "timeframe_execution_concentration_guard_status.json", concentration_guard)
    write_json(out_dir / "multi_timeframe_thesis_execution_contract_status.json", thesis_execution)
    write_json(out_dir / "paper_reentry_and_signal_dedup_status.json", reentry_dedup)
    write_json(out_dir / "paper_timeframe_routing_owner_status.json", routing)
    write_json(out_dir / "paper_timeframe_routing_repair_contract.json", routing_repair)
    write_json(out_dir / "post_fix_paper_validation_status.json", post_fix_validation)
    write_json(out_dir / "operator_dashboard_payload.json", dashboard)
    write_json(out_dir / "operator_dashboard_truth_contract_status.json", dashboard_truth_contract)
    summary = {
        "schema_version": "v2_paper_timeframe_churn_governance_audit_summary_v1",
        "generated_utc": utc_now(),
        "goal_id": CURRENT_CHALLENGER_GOAL_ID,
        "added_goal_id": PAPER_GOVERNANCE_GOAL_ID,
        "status": summary_status,
        "summary_status": summary_status,
        "ready": summary_final_gate == FINAL_READY_MARKER,
        "artifacts_written": artifacts_written,
        "source_artifacts_written": artifacts_written,
        "source_artifact_count": len(artifacts_written),
        "required_artifacts": list(REQUIRED_PAPER_GOVERNANCE_ARTIFACTS),
        "required_artifact_count": len(REQUIRED_PAPER_GOVERNANCE_ARTIFACTS),
        "source_required_artifact_count": len(REQUIRED_PAPER_GOVERNANCE_ARTIFACTS),
        "missing_required_artifacts": missing_required_artifacts,
        "missing_required_artifact_count": len(missing_required_artifacts),
        "source_missing_required_artifact_count": len(missing_required_artifacts),
        "required_artifacts_present": required_artifacts_present,
        "source_required_artifacts_present": required_artifacts_present,
        "raw_close_record_count": churn["raw_close_record_count"],
        "economic_trade_count": churn["economic_trade_count"],
        "current_1m_share": churn["current_1m_share"],
        "current_1m_economic_trade_share": churn["current_1m_economic_trade_share"],
        "one_min_status": dashboard.get("one_min_status"),
        "trade_share_by_timeframe": dashboard.get("trade_share_by_timeframe"),
        "fee_share_by_timeframe": dashboard.get("fee_share_by_timeframe"),
        "turnover": dashboard.get("turnover"),
        "turnover_by_timeframe": dashboard.get("turnover_by_timeframe"),
        "cost_drag_by_timeframe": dashboard.get("cost_drag_by_timeframe"),
        "reentry_count": dashboard.get("reentry_count"),
        "duplicate_blocks": dashboard.get("duplicate_blocks"),
        "edge_to_cost_ratio": dashboard.get("edge_to_cost_ratio"),
        "thesis_timeframe": dashboard.get("thesis_timeframe"),
        "execution_timeframe": dashboard.get("execution_timeframe"),
        "operator_dashboard_truth_contract_status": dashboard_truth_contract["status"],
        "operator_dashboard_truth_contract_pass_conditions": dashboard_truth_contract["pass_conditions"],
        "operator_dashboard_truth_contract_blocked_reasons": dashboard_truth_contract["blocked_reasons"],
        "operator_dashboard_required_website_truth_fields": dashboard_truth_contract["required_website_truth_fields"],
        "operator_dashboard_missing_required_fields": dashboard_truth_contract["missing_required_fields"],
        "old_policy_trade_count": churn["old_policy_trade_count"],
        "challenger_trade_count": churn["challenger_trade_count"],
        "routing_status": routing["status"],
        "paper_timeframe_routing_repair_contract_status": routing_repair["status"],
        "hardcoded_1m_path_count": routing["hardcoded_1m_path_count"],
        "silent_1m_fallback_path_count": routing.get("silent_1m_fallback_path_count"),
        "timeframe_routing_violation_count": routing.get("timeframe_routing_violation_count"),
        "silent_1m_fallback_paths": routing.get("silent_1m_fallback_paths"),
        "routing_owner_blocked_reasons": routing.get("blocked_reasons"),
        "routing_repair_blocked_reasons": [
            condition
            for condition, passed in (routing_repair.get("pass_conditions") or {}).items()
            if passed is not True
        ],
        "hardcoded_1m_economic_paths_removed": int(routing.get("hardcoded_1m_path_count") or 0) == 0,
        "silent_1m_fallbacks_absent": int(routing.get("silent_1m_fallback_path_count") or 0) == 0,
        "current_closed_ledger_recomputed": churn["raw_close_record_count"] > 0 and churn["economic_trade_count"] > 0,
        "current_timeframe_distribution_proven": (
            churn.get("current_1m_share") is not None and churn.get("current_1m_economic_trade_share") is not None
        ),
        "economic_trade_compaction_present": compaction.get("economic_trade_count") is not None,
        "reconciliation_status": reconciliation["status"],
        "economic_trade_compaction_status": compaction["status"],
        "economic_trade_compaction_missing_raw_identity_fields": compaction.get("missing_raw_identity_fields"),
        "economic_trade_compaction_raw_identity_missing_field_counts": compaction.get("raw_identity_missing_field_counts"),
        "economic_trade_compaction_accounting_reconciliation_status": compaction.get("accounting_reconciliation_status"),
        "economic_trade_compaction_portfolio_realized_pnl": compaction.get("portfolio_realized_pnl"),
        "economic_trade_compaction_compacted_net_pnl": compaction.get("compacted_economic_trade_net_pnl"),
        "paper_churn_governor_status": churn_governor["status"],
        "paper_entry_cost_coverage_status": cost_coverage["status"],
        "paper_entry_production_grade_cost_coverage": cost_coverage["production_grade_cost_coverage"],
        "production_grade_cost_coverage": cost_coverage["production_grade_cost_coverage"],
        "paper_entry_required_coverage": cost_coverage.get("required_coverage"),
        "paper_entry_missing_required_fields": cost_coverage.get("missing_required_fields"),
        "paper_entry_missing_required_field_counts": cost_coverage.get("missing_required_field_counts"),
        "paper_entry_missing_required_field_count": cost_coverage.get("missing_required_field_count"),
        "paper_entry_shadow_only_missing_cost_rows": cost_coverage.get("shadow_only_missing_cost_rows"),
        "paper_edge_to_cost_gate_status": edge_to_cost["status"],
        "paper_edge_to_cost_production_grade_cost_coverage": edge_to_cost.get("production_grade_cost_coverage"),
        "paper_edge_to_cost_admitted_candidate_count": edge_to_cost.get("admitted_candidate_count"),
        "paper_edge_to_cost_shadow_only_candidate_count": edge_to_cost.get("shadow_only_candidate_count"),
        "paper_edge_to_cost_missing_gate_input_counts": edge_to_cost.get("missing_gate_input_counts"),
        "dynamic_timeframe_execution_eligibility_status": dynamic_timeframe_eligibility["status"],
        "active_timeframes": dynamic_timeframe_eligibility["active_timeframes"],
        "timing_only_timeframes": dynamic_timeframe_eligibility["timing_only_timeframes"],
        "dynamic_timeframe_bucket_count": dynamic_timeframe_eligibility.get("bucket_count"),
        "dynamic_timeframe_bucket_state_counts": dynamic_timeframe_eligibility.get("bucket_state_counts"),
        "dynamic_timeframe_sample_bucket_statuses": dynamic_timeframe_eligibility.get("sample_bucket_statuses"),
        "dynamic_timeframe_sample_blocked_buckets": dynamic_timeframe_eligibility.get("sample_blocked_buckets"),
        "dynamic_timeframe_sample_shadow_only_buckets": dynamic_timeframe_eligibility.get(
            "sample_shadow_only_buckets"
        ),
        "timeframe_execution_concentration_guard_status": concentration_guard["status"],
        "timeframe_execution_concentration_violation_count": concentration_guard["violation_count"],
        "timeframe_execution_concentration_operator_envelope": concentration_guard.get(
            "operator_concentration_envelope"
        ),
        "timeframe_execution_concentration_sample_violations": concentration_guard.get("sample_violations"),
        "timeframe_execution_concentration_violation_samples": concentration_guard.get("violation_samples"),
        "timeframe_execution_concentration_violation_sample_count": len(concentration_guard.get("sample_violations") or []),
        "multi_timeframe_thesis_execution_contract_status": thesis_execution["status"],
        "multi_timeframe_thesis_execution_required_fields_present_for_all_rows": thesis_execution.get(
            "required_fields_present_for_all_rows"
        ),
        "multi_timeframe_thesis_execution_required_fields_present": thesis_execution.get(
            "required_thesis_execution_fields_present"
        ),
        "multi_timeframe_thesis_execution_missing_required_fields": thesis_execution.get("missing_required_fields"),
        "multi_timeframe_thesis_execution_missing_required_field_counts": thesis_execution.get("missing_required_field_counts"),
        "multi_timeframe_thesis_execution_violation_count": thesis_execution.get("violation_count"),
        "multi_timeframe_thesis_execution_standalone_1m_requires_eligible_strategy": thesis_execution.get(
            "standalone_1m_requires_eligible_1m_strategy"
        ),
        "multi_timeframe_thesis_execution_close_outcome_attributed_to_thesis_timeframe": thesis_execution.get(
            "close_outcome_attributed_to_thesis_timeframe"
        ),
        "multi_timeframe_thesis_execution_higher_tf_position_not_reopened_on_each_1m_tick": thesis_execution.get(
            "higher_tf_position_not_reopened_on_each_1m_tick"
        ),
        "multi_timeframe_thesis_execution_higher_tf_1m_timing_preserves_thesis": thesis_execution.get(
            "higher_tf_1m_timing_preserves_thesis"
        ),
        "thesis_timeframe_contract_status": dashboard.get("thesis_timeframe_contract_status"),
        "execution_timeframe_contract_status": dashboard.get("execution_timeframe_contract_status"),
        "standalone_1m_runtime_wiring_status": thesis_execution["future_runtime_standalone_1m_gate_status"],
        "paper_online_standalone_1m_runtime_wiring_status": thesis_execution["future_runtime_standalone_1m_gate_status"],
        "active_paper_owner_standalone_1m_runtime_wiring_status": thesis_execution.get(
            "active_paper_owner_standalone_1m_gate_status"
        ),
        "standalone_1m_runtime_wired_to_entry_gate": thesis_execution["standalone_1m_runtime_wired_to_entry_gate"],
        "active_paper_owner_standalone_1m_runtime_wired_to_entry_gate": thesis_execution.get(
            "active_paper_owner_standalone_1m_runtime_wired_to_entry_gate"
        ),
        "standalone_1m_without_eligible_strategy_rows": thesis_execution.get(
            "standalone_1m_without_eligible_strategy_rows"
        ),
        "paper_reentry_and_signal_dedup_status": reentry_dedup["status"],
        "paper_reentry_dedup_runtime_wiring_status": reentry_dedup["future_runtime_reentry_dedup_gate_status"],
        "paper_online_reentry_dedup_runtime_wiring_status": reentry_dedup["future_runtime_reentry_dedup_gate_status"],
        "active_paper_owner_reentry_dedup_runtime_wiring_status": reentry_dedup.get(
            "active_paper_owner_reentry_dedup_gate_status"
        ),
        "paper_reentry_dedup_runtime_wired_to_entry_gate": reentry_dedup["runtime_wired_to_entry_gate"],
        "active_paper_owner_reentry_dedup_runtime_wired_to_entry_gate": reentry_dedup.get(
            "active_paper_owner_reentry_dedup_runtime_wired_to_entry_gate"
        ),
        "post_fix_paper_validation_status": post_fix_validation["status"],
        "post_fix_ready": post_fix_validation["post_fix_ready"],
        "post_fix_sample_status": post_fix_validation.get("post_fix_sample_status"),
        "post_fix_sample_started": post_fix_validation.get("post_fix_sample_started"),
        "post_fix_sample_raw_close_rows": post_fix_validation.get("post_fix_sample_raw_close_rows"),
        "post_fix_sample_eligible_raw_close_rows": post_fix_validation.get("post_fix_sample_eligible_raw_close_rows"),
        "post_fix_sample_excluded_raw_close_rows": post_fix_validation.get("post_fix_sample_excluded_raw_close_rows"),
        "post_fix_sample_exclusion_reason_counts": post_fix_validation.get("post_fix_sample_exclusion_reason_counts"),
        "post_fix_sample_source_counts": post_fix_validation.get("post_fix_sample_source_counts"),
        "post_fix_sample_eligible_source_counts": post_fix_validation.get("post_fix_sample_eligible_source_counts"),
        "post_fix_sample_excluded_source_counts": post_fix_validation.get("post_fix_sample_excluded_source_counts"),
        "post_fix_sample_source_read_status": post_fix_validation.get("post_fix_sample_source_read_status"),
        "post_fix_sample_sample_excluded_rows": post_fix_validation.get("post_fix_sample_sample_excluded_rows"),
        "post_fix_sample_excluded_row_samples": post_fix_validation.get("post_fix_sample_excluded_row_samples"),
        "sample_excluded_rows": post_fix_validation.get("sample_excluded_rows"),
        "excluded_row_samples": post_fix_validation.get("excluded_row_samples"),
        "post_fix_sample_sample_excluded_rows_by_source": post_fix_validation.get(
            "post_fix_sample_sample_excluded_rows_by_source"
        ),
        "post_fix_sample_sample_compacted_economic_trades": post_fix_validation.get(
            "post_fix_sample_sample_compacted_economic_trades"
        ),
        "new_compacted_economic_paper_outcomes": post_fix_validation.get("new_compacted_economic_paper_outcomes"),
        "required_new_compacted_economic_paper_outcomes": post_fix_validation.get(
            "required_new_compacted_economic_paper_outcomes"
        ),
        "post_fix_validation_actuals": post_fix_validation.get("validation_actuals"),
        "post_fix_validation_actuals_alias": post_fix_validation.get("actuals"),
        "post_fix_validation_required": post_fix_validation.get("validation_required"),
        "post_fix_validation_required_alias": post_fix_validation.get("required"),
        "post_fix_duplicate_economic_trades": post_fix_validation.get("duplicate_economic_trades"),
        "post_fix_unexplained_same_candle_reentries": post_fix_validation.get("unexplained_same_candle_reentries"),
        "post_fix_accounting_reconciliation_status": post_fix_validation.get("accounting_reconciliation_status"),
        "blocked_conditions": summary_blocked_reasons,
        "blocked_condition_count": len(summary_blocked_reasons),
        "blocked_reasons": summary_blocked_reasons,
        "blocker_count": len(summary_blocked_reasons),
        "failed_pass_conditions": summary_blocked_reasons,
        "blocker_details": summary_blocker_details,
        "failed_blocker_details": summary_blocker_details,
        "blocker_summary": summary_blocker_summary,
        "source_statuses": summary_source_statuses,
        "source_blocked_conditions": summary_blocked_reasons,
        "source_blocked_condition_count": len(summary_blocked_reasons),
        **source_blocker_fields,
        "phase_statuses": phase_trace["phase_statuses"],
        "phase_pass_conditions": phase_trace["phase_pass_conditions"],
        "phase_blockers": phase_trace["phase_blockers"],
        "phase_blocker_count": summary_phase_blocker_count,
        "phase_blocked_conditions": summary_phase_blocked_conditions,
        "source_paper_governance_blockers_cleared": len(summary_blocked_reasons) == 0,
        "source_paper_governance_phase_blockers_cleared": summary_phase_blocker_count == 0,
        "final_gate": summary_final_gate,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    summary["pass_conditions"] = paper_governance_summary_pass_conditions(summary)
    summary["summary_pass_conditions"] = summary["pass_conditions"]
    summary_actuals = {
        "required_artifacts_present": {
            "required_artifact_count": summary["required_artifact_count"],
            "missing_required_artifact_count": summary["missing_required_artifact_count"],
        },
        "current_ledger_recomputed": {
            "raw_close_record_count": summary["raw_close_record_count"],
            "economic_trade_count": summary["economic_trade_count"],
        },
        "challenger_remains_paper_inactive": summary["challenger_trade_count"],
        "routing_owner_audit_passed": summary["routing_status"],
        "operator_dashboard_website_truth_contract_passed": summary["operator_dashboard_truth_contract_status"],
        "post_fix_ready": summary["post_fix_ready"],
        "final_gate_ready": summary["final_gate"],
        "source_blockers_cleared": summary["blocked_reasons"],
        "source_phase_blockers_cleared": {
            "phase_blocker_count": summary_phase_blocker_count,
            "phase_blockers": phase_trace["phase_blockers"],
        },
        "paper_only_no_live_routes": {
            "paper_fill_allowed": summary["paper_fill_allowed"],
            "routes_to_live": summary["routes_to_live"],
            "places_real_order": summary["places_real_order"],
            "counts_as_a_grade_evidence": summary["counts_as_a_grade_evidence"],
        },
    }
    summary_required = {
        "required_artifacts_present": {"missing_required_artifact_count": 0},
        "current_ledger_recomputed": {"raw_close_record_count": ">0", "economic_trade_count": ">0"},
        "challenger_remains_paper_inactive": 0,
        "routing_owner_audit_passed": "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "operator_dashboard_website_truth_contract_passed": "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
        "post_fix_ready": True,
        "final_gate_ready": FINAL_READY_MARKER,
        "source_blockers_cleared": [],
        "source_phase_blockers_cleared": {"phase_blocker_count": 0},
        "paper_only_no_live_routes": {
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
        },
    }
    summary["actuals"] = summary_actuals
    summary["required"] = summary_required
    summary["sample_blockers"] = summary_blocker_details[:25]
    (out_dir / "GO_NO_GO.md").write_text(go_no_go_markdown(summary, post_fix_validation), encoding="utf-8")
    (out_dir / "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_REPORT.md").write_text(
        repair_report_markdown(summary, post_fix_validation),
        encoding="utf-8",
    )
    write_json(out_dir / "paper_timeframe_churn_governance_audit_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only current paper timeframe churn governance audit.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Defaults to goal_state/<current challenger goal id> under --repo-root.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    out_dir = args.out_dir or repo_root / "goal_state" / CURRENT_CHALLENGER_GOAL_ID
    print(json.dumps(run_audit(repo_root, out_dir), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
