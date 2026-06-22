"""Pass 2B paper/shadow edge proof.

This command is a read-only edge calculator. It includes only trusted
pipeline_trust_v3 paper/shadow decisions with replay and MTF evidence, excludes
live records, and reports whether the sample is positive, negative,
insufficient, or invalid.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.cli.export_pipeline_trust_evidence import export_pipeline_trust_evidence
from app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION

ACTIONABLE_ACTIONS = {"long", "short", "open_long", "open_short", "close_long", "close_short", "reduce"}
HOLD_ACTIONS = {"", "hold", "no_trade", "none", "abstain"}
BAD_ORDER_STATUSES = {"rejected", "reject", "canceled", "cancelled", "expired", "blocked", "denied"}
LIVE_FLAGS = ("places_real_order", "exchange_action_taken", "live_order", "live_order_submitted")
TRUST_FIELDS = (
    "trust_schema_version",
    "decision_id",
    "prediction_id",
    "mtf_snapshot_id",
    "replay_snapshot_id",
    "feature_cutoff",
    "available_at",
    "all_tf_candle_timestamps",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_pass2b_paper_shadow_edge_proof")
    parser.add_argument("--redis-url", default="")
    parser.add_argument("--input", "--evidence-dir", dest="evidence_dir", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-trusted-decisions", type=int, default=25)
    parser.add_argument("--min-closed-trades", type=int, default=10)
    parser.add_argument("--fee-bps-assumption", type=float, default=0.0)
    parser.add_argument("--slippage-bps-assumption", type=float, default=0.0)
    parser.add_argument("--profit-factor-threshold", type=float, default=1.0)
    parser.add_argument("--symbol", default="")
    args = parser.parse_args(argv)

    if not args.redis_url and not args.evidence_dir:
        parser.error("one of --redis-url or --input/--evidence-dir is required")

    output_root = Path(args.output_dir)
    run_id = utc_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    evidence_dir: Path
    if args.evidence_dir:
        evidence_dir = Path(args.evidence_dir)
    else:
        client = redis_client(args.redis_url)
        evidence_dir = export_pipeline_trust_evidence(
            client=client,
            redis_url=args.redis_url,
            output_root=run_dir / "evidence",
        )

    result = run_edge_proof(
        evidence_dir=evidence_dir,
        min_trusted_decisions=args.min_trusted_decisions,
        min_closed_trades=args.min_closed_trades,
        fee_bps_assumption=args.fee_bps_assumption,
        slippage_bps_assumption=args.slippage_bps_assumption,
        profit_factor_threshold=args.profit_factor_threshold,
        symbol_filter=args.symbol or None,
    )
    result.update(
        {
            "run_id": run_id,
            "generated_at": utc_now(),
            "input_evidence_dir": str(evidence_dir),
            "output_dir": str(run_dir),
        }
    )
    (run_dir / "pass2b_edge_proof.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (run_dir / "PASS2B_EDGE_PROOF.md").write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result.get("verdict") == "EDGE_DATA_INVALID" else 0


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def run_edge_proof(
    *,
    evidence_dir: Path,
    min_trusted_decisions: int = 25,
    min_closed_trades: int = 10,
    fee_bps_assumption: float = 0.0,
    slippage_bps_assumption: float = 0.0,
    profit_factor_threshold: float = 1.0,
    symbol_filter: str | None = None,
) -> dict[str, Any]:
    records = load_evidence_records(evidence_dir)
    strict_summary = load_strict_summary(evidence_dir)
    prediction_records = [record for record in records if is_prediction_record(record)]
    replay_refs, mtf_refs = snapshot_refs(records)

    trusted_predictions: list[dict[str, Any]] = []
    invalid_decisions: list[dict[str, Any]] = []
    stale_pre_v3 = 0
    live_predictions_excluded = 0
    missing_replay = 0
    missing_mtf = 0

    for prediction in prediction_records:
        if symbol_filter and str(first_value(prediction, ("symbol",))).upper() != symbol_filter.upper():
            continue
        if any(truthy(first_value(prediction, (flag,))) for flag in LIVE_FLAGS):
            live_predictions_excluded += 1
            continue
        if first_value(prediction, ("trust_schema_version",)) != TRUST_SCHEMA_VERSION:
            stale_pre_v3 += 1
            continue
        missing = [field for field in TRUST_FIELDS if not has_required_value(prediction, field)]
        pred_id = str(first_value(prediction, ("prediction_id",)) or "")
        mtf_id = str(first_value(prediction, ("mtf_snapshot_id",)) or "")
        replay_id = str(first_value(prediction, ("replay_snapshot_id",)) or "")
        replay_exists = bool(pred_id and pred_id in replay_refs) or bool(replay_id and replay_id in replay_refs)
        mtf_exists = bool(mtf_id and mtf_id in mtf_refs)
        if not replay_exists:
            missing_replay += 1
            missing.append("replay_snapshot_exists")
        if not mtf_exists:
            missing_mtf += 1
            missing.append("mtf_snapshot_exists")
        if truthy(first_value(prediction, ("routes_to_live", "live_order_allowed"))):
            missing.append("live_disabled_flags")
        if missing:
            invalid_decisions.append({"prediction_id": pred_id, "missing": sorted(set(missing))})
            continue
        trusted_predictions.append(prediction)

    trusted_ids = id_sets(trusted_predictions)
    paper_intents = [record for record in records if is_paper_intent(record)]
    live_order_records_excluded = sum(1 for record in records if any(truthy(first_value(record, (flag,))) for flag in LIVE_FLAGS))
    paper_intents_linked = [record for record in paper_intents if links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    fills = [record for record in records if is_fill_record(record) and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    closed_trades = [record for record in records if is_closed_trade(record) and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    open_trades = [record for record in records if is_open_trade(record) and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    rejected = [record for record in records if order_status(record) == "rejected" and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    canceled = [record for record in records if order_status(record) in {"canceled", "cancelled"} and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    expired = [record for record in records if order_status(record) == "expired" and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    blocked = [record for record in records if order_status(record) in {"blocked", "denied"} and links_to_trusted(record, trusted_ids) and not is_live_record(record)]

    trade_metrics = compute_trade_metrics(
        closed_trades,
        fee_bps_assumption=fee_bps_assumption,
        slippage_bps_assumption=slippage_bps_assumption,
    )
    invalid_feedback = find_invalid_feedback(records, trusted_ids)
    action_counts = count_prediction_actions(trusted_predictions)
    strict_critical = int((strict_summary or {}).get("critical_failures") or 0)

    verdict = classify_verdict(
        strict_critical=strict_critical,
        invalid_decision_count=len(invalid_decisions),
        invalid_feedback_count=len(invalid_feedback),
        trusted_decision_count=len(trusted_predictions),
        closed_trade_count=len(closed_trades),
        min_trusted_decisions=min_trusted_decisions,
        min_closed_trades=min_closed_trades,
        expectancy=trade_metrics["expectancy_per_trade"],
        profit_factor=trade_metrics["profit_factor"],
        profit_factor_threshold=profit_factor_threshold,
    )

    return {
        "verdict": verdict,
        "strict_summary": strict_summary or {"critical_failures": None, "status": "not_available"},
        "total_prediction_records": len(prediction_records),
        "total_trusted_predictions": len(trusted_predictions),
        "actionable_predictions": action_counts["actionable"],
        "hold_no_trade_predictions": action_counts["hold_no_trade"],
        "blocked_predictions": action_counts["blocked"],
        "stale_pre_v3_predictions_excluded": stale_pre_v3,
        "live_prediction_records_excluded": live_predictions_excluded,
        "live_order_records_excluded": live_order_records_excluded,
        "decisions_missing_replay_snapshot": missing_replay,
        "decisions_missing_mtf_snapshot": missing_mtf,
        "invalid_decision_count": len(invalid_decisions),
        "invalid_decisions": invalid_decisions[:25],
        "paper_intents": len(paper_intents_linked),
        "simulated_fills": len(fills),
        "open_paper_trades": len(open_trades),
        "closed_paper_trades": len(closed_trades),
        "rejected_orders": len(rejected),
        "canceled_orders": len(canceled),
        "expired_orders": len(expired),
        "blocked_orders": len(blocked),
        "invalid_feedback_count": len(invalid_feedback),
        "invalid_feedback_examples": invalid_feedback[:25],
        "minimums": {
            "min_trusted_decisions": min_trusted_decisions,
            "min_closed_trades": min_closed_trades,
            "profit_factor_threshold": profit_factor_threshold,
        },
        "metrics": trade_metrics,
        "pass3_live_canary_safety_may_begin": verdict in {"EDGE_POSITIVE", "INSUFFICIENT_SAMPLE"},
    }


def load_evidence_records(evidence_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict) and "value" in raw and ("redis_key" in raw or "category" in raw):
                value = raw.get("value")
                if isinstance(value, dict):
                    record = dict(value)
                else:
                    record = {"value": value}
                record.setdefault("_category", raw.get("category") or path.stem)
                record.setdefault("_key", raw.get("redis_key"))
            elif isinstance(raw, dict):
                record = dict(raw)
                record.setdefault("_category", path.stem)
            else:
                record = {"value": raw, "_category": path.stem}
            records.append(record)
    return records


def load_strict_summary(evidence_dir: Path) -> dict[str, Any] | None:
    path = evidence_dir / "report" / "pipeline_trust_report.json"
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"critical_failures": 1, "status": "report_parse_failed"}
    return dict(report.get("summary") or {})


def snapshot_refs(records: Iterable[dict[str, Any]]) -> tuple[set[str], set[str]]:
    replay: set[str] = set()
    mtf: set[str] = set()
    for record in records:
        key = str(record.get("_key") or "")
        pred_id = first_value(record, ("prediction_id",))
        replay_id = first_value(record, ("replay_snapshot_id",))
        mtf_id = first_value(record, ("mtf_snapshot_id",))
        if "mtf_snapshot" in key:
            if mtf_id:
                mtf.add(str(mtf_id))
        if "replay:snapshots" in key or "replay_snapshot" in key:
            if pred_id:
                replay.add(str(pred_id))
            if replay_id:
                replay.add(str(replay_id))
        inline = record.get("replay_snapshot")
        if isinstance(inline, Mapping):
            if inline.get("prediction_id"):
                replay.add(str(inline["prediction_id"]))
            if inline.get("replay_snapshot_id"):
                replay.add(str(inline["replay_snapshot_id"]))
        if mtf_id and first_value(record, ("mtf_snapshot_valid", "valid")) is True:
            mtf.add(str(mtf_id))
    return replay, mtf


def id_sets(records: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    out = {"prediction_id": set(), "decision_id": set(), "replay_snapshot_id": set(), "mtf_snapshot_id": set()}
    for record in records:
        for field in out:
            value = first_value(record, (field,))
            if value:
                out[field].add(str(value))
    return out


def is_prediction_record(record: dict[str, Any]) -> bool:
    key = str(record.get("_key") or "")
    return key.startswith("v2:prediction:")


def is_live_record(record: dict[str, Any]) -> bool:
    return any(truthy(first_value(record, (flag,))) for flag in LIVE_FLAGS)


def is_paper_intent(record: dict[str, Any]) -> bool:
    key = str(record.get("_key") or "").lower()
    return "paper:intents" in key or first_value(record, ("paper_intent_id", "intent_id")) is not None


def is_fill_record(record: dict[str, Any]) -> bool:
    status = order_status(record)
    return status in {"filled", "partially_filled", "partial_fill"} or first_value(record, ("fill_price", "avg_fill_price")) is not None


def is_closed_trade(record: dict[str, Any]) -> bool:
    state = str(first_value(record, ("trade_status", "position_status", "lifecycle_state", "state")) or "").lower()
    if state in {"closed", "flat", "complete", "completed"} and first_numeric(record, ("net_pnl", "realized_pnl", "gross_pnl", "pnl")) is not None:
        return True
    return first_value(record, ("exit_price", "closed_at", "close_time", "exit_time")) is not None and first_numeric(
        record, ("net_pnl", "realized_pnl", "gross_pnl", "pnl")
    ) is not None


def is_open_trade(record: dict[str, Any]) -> bool:
    state = str(first_value(record, ("trade_status", "position_status", "lifecycle_state", "state")) or "").lower()
    return state in {"open", "long_open", "short_open"}


def order_status(record: dict[str, Any]) -> str:
    raw = str(
        first_value(
            record,
            ("order_status", "fill_status", "paper_fill_status", "status", "paper_fill_gate_status", "risk_state"),
        )
        or ""
    ).lower()
    if "partially" in raw:
        return "partially_filled"
    if "filled" in raw or raw == "fill":
        return "filled"
    if "reject" in raw:
        return "rejected"
    if "cancel" in raw:
        return "canceled"
    if "expire" in raw:
        return "expired"
    if "block" in raw:
        return "blocked"
    if "deny" in raw:
        return "denied"
    return raw


def links_to_trusted(record: dict[str, Any], trusted_ids: dict[str, set[str]]) -> bool:
    if not any(trusted_ids.values()):
        return False
    for field, values in trusted_ids.items():
        value = first_value(record, (field,))
        if value and str(value) in values:
            return True
    lineage = record.get("lineage_ids")
    if isinstance(lineage, Mapping):
        for value in lineage.values():
            if value and any(str(value) in values for values in trusted_ids.values()):
                return True
    return False


def count_prediction_actions(predictions: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"actionable": 0, "hold_no_trade": 0, "blocked": 0}
    for prediction in predictions:
        action = str(first_value(prediction, ("selected_action", "action", "ppo_action", "side")) or "").lower()
        if action in ACTIONABLE_ACTIONS:
            counts["actionable"] += 1
        elif action in HOLD_ACTIONS:
            counts["hold_no_trade"] += 1
        if first_value(prediction, ("paper_fill_allowed",)) is False or first_value(prediction, ("paper_eligible",)) is False:
            counts["blocked"] += 1
    return counts


def compute_trade_metrics(
    trades: list[dict[str, Any]],
    *,
    fee_bps_assumption: float,
    slippage_bps_assumption: float,
) -> dict[str, Any]:
    trade_rows: list[dict[str, Any]] = []
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    wins = 0
    losses = 0
    current_wins = 0
    current_losses = 0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    symbol_breakdown: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0})
    side_breakdown: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0})
    action_breakdown: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0})
    regime_breakdown: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0})
    hold_times: list[float] = []

    for trade in trades:
        gross = first_numeric(trade, ("gross_pnl", "gross_pnl_usd", "realized_pnl_gross", "pnl"))
        net_existing = first_numeric(trade, ("net_pnl", "net_pnl_usd", "realized_pnl_after_cost", "pnl_after_cost"))
        notional = abs(first_numeric(trade, ("notional", "notional_usd", "entry_notional", "quantity_usd")) or 0.0)
        fee = first_numeric(trade, ("fees", "fee", "fee_usd", "commission", "commission_usd"))
        slippage = first_numeric(trade, ("slippage", "slippage_usd", "slippage_cost", "slippage_cost_usd"))
        if fee is None:
            fee = notional * fee_bps_assumption / 10_000.0 if notional else 0.0
        if slippage is None:
            slippage = notional * slippage_bps_assumption / 10_000.0 if notional else 0.0
        if gross is None and net_existing is not None:
            gross = net_existing + fee + slippage
        if gross is None:
            gross = 0.0
        net = net_existing if net_existing is not None else gross - fee - slippage
        equity += net
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if net > 0:
            wins += 1
            current_wins += 1
            current_losses = 0
        elif net < 0:
            losses += 1
            current_losses += 1
            current_wins = 0
        else:
            current_wins = 0
            current_losses = 0
        max_consecutive_wins = max(max_consecutive_wins, current_wins)
        max_consecutive_losses = max(max_consecutive_losses, current_losses)
        symbol = str(first_value(trade, ("symbol",)) or "UNKNOWN").upper()
        side = str(first_value(trade, ("side", "direction", "position_side", "action")) or "UNKNOWN").lower()
        action = str(first_value(trade, ("model_action", "selected_action", "action")) or side or "UNKNOWN").lower()
        regime = str(first_value(trade, ("regime", "mode", "selected_mode")) or "UNKNOWN")
        for bucket, key in ((symbol_breakdown, symbol), (side_breakdown, side), (action_breakdown, action), (regime_breakdown, regime)):
            bucket[key]["trades"] += 1
            bucket[key]["net_pnl"] += net
        hold_seconds = hold_time_seconds(trade)
        if hold_seconds is not None:
            hold_times.append(hold_seconds)
        trade_rows.append({"gross_pnl": gross, "fees": fee, "slippage": slippage, "net_pnl": net})

    nets = [row["net_pnl"] for row in trade_rows]
    wins_values = [value for value in nets if value > 0]
    loss_values = [value for value in nets if value < 0]
    gross_profit = sum(wins_values)
    gross_loss = abs(sum(loss_values))
    profit_factor: float | str
    if gross_loss == 0 and gross_profit > 0:
        profit_factor = "Infinity"
    elif gross_loss == 0:
        profit_factor = 0.0
    else:
        profit_factor = gross_profit / gross_loss
    return {
        "gross_pnl": sum(row["gross_pnl"] for row in trade_rows),
        "fees": sum(row["fees"] for row in trade_rows),
        "slippage": sum(row["slippage"] for row in trade_rows),
        "net_pnl_after_fees_slippage": sum(nets),
        "expectancy_per_trade": (sum(nets) / len(nets)) if nets else 0.0,
        "win_rate": (wins / len(nets)) if nets else 0.0,
        "profit_factor": profit_factor,
        "average_win": (sum(wins_values) / len(wins_values)) if wins_values else 0.0,
        "average_loss": (sum(loss_values) / len(loss_values)) if loss_values else 0.0,
        "largest_win": max(wins_values) if wins_values else 0.0,
        "largest_loss": min(loss_values) if loss_values else 0.0,
        "max_drawdown": max_drawdown,
        "consecutive_wins": max_consecutive_wins,
        "consecutive_losses": max_consecutive_losses,
        "exposure_time_seconds": sum(hold_times),
        "average_hold_time_seconds": (sum(hold_times) / len(hold_times)) if hold_times else 0.0,
        "symbol_breakdown": normalize_breakdown(symbol_breakdown),
        "long_short_breakdown": normalize_breakdown(side_breakdown),
        "model_action_breakdown": normalize_breakdown(action_breakdown),
        "regime_mode_breakdown": normalize_breakdown(regime_breakdown),
    }


def find_invalid_feedback(records: list[dict[str, Any]], trusted_ids: dict[str, set[str]]) -> list[dict[str, Any]]:
    bad_records = [record for record in records if order_status(record) in BAD_ORDER_STATUSES and links_to_trusted(record, trusted_ids)]
    bad_ids = id_sets(bad_records)
    out: list[dict[str, Any]] = []
    for sample in records:
        if not is_training_sample(sample):
            continue
        if not links_to_trusted(sample, trusted_ids):
            continue
        if not links_to_trusted(sample, bad_ids):
            continue
        if is_positive_training_sample(sample):
            out.append(
                {
                    "sample_id": first_value(sample, ("sample_id", "training_sample_id")),
                    "prediction_id": first_value(sample, ("prediction_id",)),
                    "decision_id": first_value(sample, ("decision_id",)),
                    "reason": "positive_training_sample_from_bad_order_state",
                }
            )
    return out


def is_training_sample(record: dict[str, Any]) -> bool:
    key = str(record.get("_key") or "").lower()
    category = str(record.get("_category") or "").lower()
    return "training" in key or "training" in category or first_value(record, ("sample_id", "training_sample_id")) is not None


def is_positive_training_sample(record: dict[str, Any]) -> bool:
    accepted = any(truthy(first_value(record, (field,))) for field in ("accepted_for_training", "used_for_training", "included_in_training", "accepted"))
    positive_numeric = any((first_numeric(record, (field,)) or 0.0) > 0 for field in ("label_pnl", "outcome_pnl", "reward", "net_pnl"))
    label = str(first_value(record, ("label", "outcome", "training_outcome", "result")) or "").lower()
    positive_label = label in {"positive", "win", "profit", "success"}
    return accepted and (positive_numeric or positive_label)


def classify_verdict(
    *,
    strict_critical: int,
    invalid_decision_count: int,
    invalid_feedback_count: int,
    trusted_decision_count: int,
    closed_trade_count: int,
    min_trusted_decisions: int,
    min_closed_trades: int,
    expectancy: float,
    profit_factor: float | str,
    profit_factor_threshold: float,
) -> str:
    if strict_critical > 0 or invalid_decision_count > 0 or invalid_feedback_count > 0:
        return "EDGE_DATA_INVALID"
    if trusted_decision_count < min_trusted_decisions or closed_trade_count < min_closed_trades:
        return "INSUFFICIENT_SAMPLE"
    pf = math.inf if profit_factor == "Infinity" else float(profit_factor)
    if expectancy > 0 and pf > profit_factor_threshold:
        return "EDGE_POSITIVE"
    return "EDGE_NEGATIVE"


def normalize_breakdown(breakdown: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
    return {key: {"trades": int(value["trades"]), "net_pnl": value["net_pnl"]} for key, value in sorted(breakdown.items())}


def hold_time_seconds(record: dict[str, Any]) -> float | None:
    start = timestamp_seconds(first_value(record, ("entry_time", "opened_at", "open_time", "created_at")))
    end = timestamp_seconds(first_value(record, ("exit_time", "closed_at", "close_time", "updated_at")))
    if start is None or end is None or end < start:
        return None
    return end - start


def timestamp_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 1000.0 if number > 10_000_000_000 else number
    text = str(value).strip()
    if not text:
        return None
    try:
        return timestamp_seconds(float(text))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def has_required_value(record: dict[str, Any], field: str) -> bool:
    value = first_value(record, (field,))
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def first_value(record: Mapping[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        if field in record:
            return record[field]
    return None


def first_numeric(record: Mapping[str, Any], fields: tuple[str, ...]) -> float | None:
    for field in fields:
        value = record.get(field)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "allow", "allowed", "approved", "filled", "submitted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def render_markdown(result: dict[str, Any]) -> str:
    metrics = result.get("metrics") or {}
    return "\n".join(
        [
            f"# Pass 2B Edge Proof: {result.get('run_id')}",
            "",
            f"Generated: `{result.get('generated_at')}`",
            "",
            "| Field | Value |",
            "|---|---:|",
            f"| Verdict | `{result.get('verdict')}` |",
            f"| Strict critical failures | `{(result.get('strict_summary') or {}).get('critical_failures')}` |",
            f"| Total trusted predictions | `{result.get('total_trusted_predictions')}` |",
            f"| Actionable predictions | `{result.get('actionable_predictions')}` |",
            f"| HOLD/no-trade predictions | `{result.get('hold_no_trade_predictions')}` |",
            f"| Paper intents | `{result.get('paper_intents')}` |",
            f"| Closed paper trades | `{result.get('closed_paper_trades')}` |",
            f"| Open paper trades | `{result.get('open_paper_trades')}` |",
            f"| Rejected orders | `{result.get('rejected_orders')}` |",
            f"| Canceled orders | `{result.get('canceled_orders')}` |",
            f"| Expired orders | `{result.get('expired_orders')}` |",
            f"| Invalid feedback count | `{result.get('invalid_feedback_count')}` |",
            f"| Net PnL after fees/slippage | `{metrics.get('net_pnl_after_fees_slippage')}` |",
            f"| Expectancy | `{metrics.get('expectancy_per_trade')}` |",
            f"| Profit factor | `{metrics.get('profit_factor')}` |",
            f"| Max drawdown | `{metrics.get('max_drawdown')}` |",
            f"| Win rate | `{metrics.get('win_rate')}` |",
            "",
            "## Symbol breakdown",
            "",
            "```json",
            json.dumps(metrics.get("symbol_breakdown") or {}, indent=2, sort_keys=True),
            "```",
            "",
            "## Long/short breakdown",
            "",
            "```json",
            json.dumps(metrics.get("long_short_breakdown") or {}, indent=2, sort_keys=True),
            "```",
        ]
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
