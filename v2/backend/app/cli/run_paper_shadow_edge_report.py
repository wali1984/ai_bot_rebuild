"""Pass 2B paper/shadow edge report.

Read-only release-gate reporter for trusted paper/shadow decisions. The report
uses only non-live decisions with replay and MTF evidence, refuses to count open
or incomplete trades as realized edge, and emits separate edge, ablation,
liquidity, sample, and release-gate artifacts.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - import shape differs between pytest and python -m
    from app.cli.export_pipeline_trust_evidence import export_pipeline_trust_evidence
    from app.cli.run_pass2b_paper_shadow_edge_proof import (
        ACTIONABLE_ACTIONS,
        HOLD_ACTIONS,
        LIVE_FLAGS,
        TRUST_FIELDS,
        first_numeric,
        first_value,
        has_required_value,
        hold_time_seconds,
        is_closed_trade,
        is_live_record,
        is_open_trade,
        is_paper_intent,
        links_to_trusted,
        load_evidence_records,
        load_strict_summary,
        order_status,
        snapshot_refs,
        truthy,
    )
    from app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
except ModuleNotFoundError:  # pragma: no cover
    from v2.backend.app.cli.export_pipeline_trust_evidence import export_pipeline_trust_evidence
    from v2.backend.app.cli.run_pass2b_paper_shadow_edge_proof import (
        ACTIONABLE_ACTIONS,
        HOLD_ACTIONS,
        LIVE_FLAGS,
        TRUST_FIELDS,
        first_numeric,
        first_value,
        has_required_value,
        hold_time_seconds,
        is_closed_trade,
        is_live_record,
        is_open_trade,
        is_paper_intent,
        links_to_trusted,
        load_evidence_records,
        load_strict_summary,
        order_status,
        snapshot_refs,
        truthy,
    )
    from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION

REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
REQUIRED_PREDICTION_FIELDS = (
    "prediction_id",
    "symbol",
    "timeframe",
    "decision_time",
    "feature_cutoff",
    "available_at",
    "generated_at",
    "input_feature_hash",
    "mtf_snapshot_id",
    "replay_snapshot_id",
    "model_version",
)
OUTCOME_REQUIRED_FIELDS = (
    "fill_price",
    "exit_price",
    "fees",
    "slippage",
    "fill_price_provenance",
)
ABLATION_NAMES = (
    "masa_only",
    "ppo_only",
    "masa_ppo_agreement_only",
    "masa_ppo_disagreement",
    "strategy_router_accepted",
    "risk_gate_accepted",
    "trust_gate_blocked",
    "strategy_conflict_blocked",
    "execution_quality_blocked",
    "no_trade_baseline",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_paper_shadow_edge_report")
    parser.add_argument("--input", required=True, help="Exported evidence directory or redis:// URL")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--redis-url", default="", help="Explicit Redis URL. Overrides --input as evidence source.")
    parser.add_argument("--min-trusted-decisions", type=int, default=300)
    parser.add_argument("--min-closed-trades", type=int, default=100)
    parser.add_argument("--profit-factor-threshold", type=float, default=1.15)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = resolve_evidence_dir(args.input, args.redis_url, output_dir)

    bundle = build_reports(
        evidence_dir=evidence_dir,
        min_trusted_decisions=args.min_trusted_decisions,
        min_closed_trades=args.min_closed_trades,
        profit_factor_threshold=args.profit_factor_threshold,
    )
    write_outputs(output_dir, bundle)
    print(json.dumps(bundle["release_gate"], indent=2, sort_keys=True, default=str))
    return 1 if bundle["release_gate"]["sample_size_status"] == "NO-GO" or bundle["release_gate"].get("pass2e_verdict") == "NO-GO" else 0


def resolve_evidence_dir(input_value: str, redis_url: str, output_dir: Path) -> Path:
    source = redis_url or input_value
    if source.startswith("redis://"):
        client = redis_client(source)
        return export_pipeline_trust_evidence(
            client=client,
            redis_url=source,
            output_root=output_dir / "exported_evidence",
        )
    return Path(input_value)


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def build_reports(
    *,
    evidence_dir: Path,
    min_trusted_decisions: int = 300,
    min_closed_trades: int = 100,
    profit_factor_threshold: float = 1.15,
) -> dict[str, Any]:
    records = expand_records(load_evidence_records(evidence_dir))
    strict_summary = load_strict_summary(evidence_dir) or {"critical_failures": None, "status": "not_available"}
    predictions = [record for record in records if is_prediction_record(record)]
    replay_refs, mtf_refs = snapshot_refs(records)
    mtf_by_id = index_by_id(records, "mtf_snapshot_id", key_contains="mtf_snapshot")
    replay_by_id = index_by_id(records, "replay_snapshot_id", key_contains="replay:snapshots")
    candle_index = build_candle_index(records)

    valid_decisions: list[dict[str, Any]] = []
    invalid_decisions: list[dict[str, Any]] = []
    stale_excluded = 0
    live_excluded = 0
    dirty_accepted_decisions = 0
    active_missing_contract = 0
    active_inconsistent_cutoff = 0
    active_duplicate_conflicts = 0
    active_out_of_order = 0
    active_non_positive_volume = 0
    active_source_disagreement = 0
    replay_reconstruction_failures = 0
    mtf_reconstruction_failures = 0

    for prediction in predictions:
        pred_id = str(first_value(prediction, ("prediction_id",)) or "")
        if first_value(prediction, ("trust_schema_version",)) != TRUST_SCHEMA_VERSION:
            stale_excluded += 1
            continue
        if is_live_record(prediction) or truthy(first_value(prediction, ("routes_to_live", "live_order_allowed"))):
            live_excluded += 1
            continue
        missing = prediction_contract_missing(prediction)
        if missing:
            active_missing_contract += 1
        if not (truthy(first_value(prediction, ("paper_only",))) or truthy(first_value(prediction, ("shadow_only",)))):
            missing.append("paper_or_shadow_only")
        replay_id = str(first_value(prediction, ("replay_snapshot_id",)) or "")
        mtf_id = str(first_value(prediction, ("mtf_snapshot_id",)) or "")
        replay_exists = bool(replay_id and replay_id in replay_refs) or bool(pred_id and pred_id in replay_refs)
        mtf_exists = bool(mtf_id and mtf_id in mtf_refs)
        if not replay_exists:
            missing.append("replay_snapshot_reconstruction")
            replay_reconstruction_failures += 1
        mtf_record = mtf_by_id.get(mtf_id)
        if not mtf_exists or not mtf_record:
            missing.append("mtf_snapshot_reconstruction")
            mtf_reconstruction_failures += 1
        else:
            mtf_defects = mtf_snapshot_defects(prediction, mtf_record, candle_index)
            if mtf_defects["inconsistent_cutoff"]:
                active_inconsistent_cutoff += 1
            active_duplicate_conflicts += mtf_defects["duplicate_conflicts"]
            active_out_of_order += mtf_defects["out_of_order"]
            active_non_positive_volume += mtf_defects["non_positive_volume"]
            active_source_disagreement += mtf_defects["source_disagreement"]
            missing.extend(mtf_defects["missing_reasons"])
        if missing:
            invalid_decisions.append({"prediction_id": pred_id, "symbol": first_value(prediction, ("symbol",)), "missing": sorted(set(missing))})
            if decision_is_accepted(prediction):
                dirty_accepted_decisions += 1
            continue
        valid_decisions.append(prediction)

    trusted_ids = id_sets(valid_decisions)
    paper_intents = [record for record in records if is_paper_intent(record) and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    accepted_paper_intents = [record for record in paper_intents if is_accepted_paper_intent(record)]
    linked_closed = [record for record in records if is_closed_trade(record) and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    linked_open = [record for record in records if is_open_trade(record) and links_to_trusted(record, trusted_ids) and not is_live_record(record)]
    complete_closed, incomplete_closed = split_complete_outcomes(linked_closed)
    metrics = compute_realized_metrics(complete_closed)
    ablation = build_ablation_report(valid_decisions, complete_closed, records)
    liquidity = build_liquidity_report(valid_decisions, records)
    residual = classify_residual_findings(records, valid_decisions)
    live_state = extract_live_state(records)

    action_counts = count_actions(valid_decisions)
    blocked_decisions = [prediction for prediction in valid_decisions if not decision_is_accepted(prediction)]
    lifecycle_diagnostics = build_lifecycle_diagnostics(valid_decisions, records, complete_closed, incomplete_closed, linked_open)
    block_trace = build_paper_intent_block_trace(valid_decisions, records, lifecycle_diagnostics)
    confidence_trace = build_confidence_block_trace(valid_decisions, records, block_trace)
    routeability_candidates = [prediction for prediction in valid_decisions if is_routeability_candidate(prediction)]
    prediction_producer_inventory = build_prediction_producer_inventory(predictions, records)
    release_gate = classify_release_gate(
        strict_summary=strict_summary,
        valid_decisions=len(valid_decisions),
        closed_trades=len(complete_closed),
        min_trusted_decisions=min_trusted_decisions,
        min_closed_trades=min_closed_trades,
        dirty_accepted_decisions=dirty_accepted_decisions,
        replay_failures=replay_reconstruction_failures,
        mtf_failures=mtf_reconstruction_failures,
        active_missing_contract=active_missing_contract,
        active_inconsistent_cutoff=active_inconsistent_cutoff,
        live_state=live_state,
        metrics=metrics,
        profit_factor_threshold=profit_factor_threshold,
        liquidity_report=liquidity,
        accepted_intents=len(accepted_paper_intents),
        open_trades=len(linked_open),
    )
    pass2e_release_gate = classify_pass2e_gate(
        confidence_trace=confidence_trace,
        release_gate=release_gate,
        accepted_intents=len(accepted_paper_intents),
        live_state=live_state,
    )
    release_gate["pass2e_verdict"] = pass2e_release_gate["verdict"]
    release_gate["pass2e_reason"] = pass2e_release_gate["reason"]

    edge_report = {
        "generated_at": utc_now(),
        "input_evidence_dir": str(evidence_dir),
        "strict_summary": strict_summary,
        "total_prediction_records": len(predictions),
        "active_decisions_evaluated": len(valid_decisions),
        "real_routeability_candidates_evaluated": len(routeability_candidates),
        "accepted_paper_decisions": action_counts["accepted"],
        "blocked_decisions": len(blocked_decisions),
        "shadow_decisions": action_counts["shadow"],
        "closed_trades_evaluated": len(complete_closed),
        "open_trades": len(linked_open),
        "paper_intents": len(paper_intents),
        "accepted_paper_intents": len(accepted_paper_intents),
        "incomplete_closed_trades_excluded": len(incomplete_closed),
        "stale_pre_v3_predictions_excluded": stale_excluded,
        "live_prediction_records_excluded": live_excluded,
        "replay_reconstruction_failures": replay_reconstruction_failures,
        "mtf_reconstruction_failures": mtf_reconstruction_failures,
        "dirty_accepted_decisions": dirty_accepted_decisions,
        "active_prediction_missing_contract_count": active_missing_contract,
        "active_mtf_inconsistent_cutoff_count": active_inconsistent_cutoff,
        "active_duplicate_conflicted_candle_count": active_duplicate_conflicts,
        "active_out_of_order_candle_count": active_out_of_order,
        "active_non_positive_volume_candle_count": active_non_positive_volume,
        "active_source_disagreement_count": active_source_disagreement,
        "metrics": metrics,
        "residual_findings": residual,
        "sample_size_status": release_gate["sample_size_status"],
        "edge_gate_status": release_gate["edge_gate_status"],
        "pass2e_verdict": pass2e_release_gate["verdict"],
        "pass2e_reason": pass2e_release_gate["reason"],
    }
    trade_sample = build_trade_sample(valid_decisions, complete_closed, incomplete_closed, replay_by_id)
    return {
        "edge_report": edge_report,
        "ablation_report": ablation,
        "liquidity_report": liquidity,
        "trade_sample": trade_sample,
        "closed_trades": complete_closed,
        "open_trades": linked_open,
        "lifecycle_diagnostics": lifecycle_diagnostics,
        "paper_intent_block_trace": block_trace,
        "confidence_block_trace": confidence_trace,
        "prediction_producer_inventory": prediction_producer_inventory,
        "pass2e_release_gate": pass2e_release_gate,
        "release_gate": release_gate,
    }


def expand_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for record in records:
        expanded.append(record)
        value = record.get("value")
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            child = dict(item)
            child.setdefault("_category", record.get("_category"))
            child.setdefault("_key", record.get("_key"))
            expanded.append(child)
    return expanded


def is_prediction_record(record: Mapping[str, Any]) -> bool:
    return str(record.get("_key") or "").startswith("v2:prediction:")


def prediction_contract_missing(prediction: Mapping[str, Any]) -> list[str]:
    missing = [field for field in REQUIRED_PREDICTION_FIELDS if not has_required_value(dict(prediction), field)]
    if not has_required_value(dict(prediction), "policy_version") and any(
        has_required_value(dict(prediction), field) for field in ("ppo_feature_cutoff", "ppo_observation_time", "ppo_timeframe")
    ):
        missing.append("policy_version")
    if truthy(first_value(prediction, ("routes_to_live", "live_order_allowed", "places_real_order", "exchange_action_taken"))):
        missing.append("non_live_flags")
    for field in TRUST_FIELDS:
        if not has_required_value(dict(prediction), field):
            missing.append(field)
    return sorted(set(missing))


def decision_is_accepted(prediction: Mapping[str, Any]) -> bool:
    action = str(first_value(prediction, ("selected_action", "action", "ppo_action", "side")) or "").lower()
    return action in ACTIONABLE_ACTIONS and truthy(first_value(prediction, ("paper_fill_allowed", "paper_eligible", "accepted")))


def count_actions(predictions: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"accepted": 0, "hold_no_trade": 0, "shadow": 0}
    for prediction in predictions:
        action = str(first_value(prediction, ("selected_action", "action", "ppo_action", "side")) or "").lower()
        if decision_is_accepted(prediction):
            counts["accepted"] += 1
        elif action in HOLD_ACTIONS:
            counts["hold_no_trade"] += 1
        if truthy(first_value(prediction, ("shadow_only",))):
            counts["shadow"] += 1
    return counts


def is_accepted_paper_intent(record: Mapping[str, Any]) -> bool:
    status = order_status(dict(record))
    if status in {"blocked", "denied", "rejected", "canceled", "cancelled", "expired"}:
        return False
    if any(truthy(first_value(record, (field,))) for field in ("accepted", "intent_accepted", "paper_intent_accepted", "paper_fill_allowed", "fill_allowed")):
        return True
    if status in {"accepted", "created", "pending", "submitted", "filled", "partially_filled", "open"}:
        return True
    return False


def id_sets(records: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    out = {"prediction_id": set(), "decision_id": set(), "replay_snapshot_id": set(), "mtf_snapshot_id": set()}
    for record in records:
        for field in out:
            value = first_value(record, (field,))
            if value:
                out[field].add(str(value))
    return out


def index_by_id(records: Iterable[dict[str, Any]], id_field: str, *, key_contains: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("_key") or "")
        value = first_value(record, (id_field,))
        if key_contains in key and value:
            out[str(value)] = record
    return out


def build_candle_index(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    index: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = str(record.get("_key") or "")
        if "ohlcv_closed" not in key:
            continue
        rows = record.get("value") if isinstance(record.get("value"), list) else None
        candidates = rows if rows is not None else [record]
        for row in candidates:
            if not isinstance(row, Mapping):
                continue
            symbol = str(first_value(row, ("symbol",)) or "").upper()
            timeframe = str(first_value(row, ("timeframe",)) or "")
            close_time = int(first_numeric(row, ("candle_close_time", "close_time", "event_time")) or 0)
            if symbol and timeframe and close_time:
                index[(symbol, timeframe, close_time)].append(dict(row))
    return index


def mtf_snapshot_defects(
    prediction: Mapping[str, Any],
    mtf_snapshot: Mapping[str, Any],
    candle_index: Mapping[tuple[str, str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    selected = mtf_snapshot.get("selected_candles")
    decision_time = timestamp_ms(first_value(prediction, ("decision_time",)))
    symbol = str(first_value(prediction, ("symbol",)) or "").upper()
    reasons: list[str] = []
    duplicate_conflicts = 0
    non_positive_volume = 0
    source_disagreement = 0
    out_of_order = 0
    inconsistent_cutoff = 0
    if not isinstance(selected, Mapping):
        return {
            "missing_reasons": ["mtf_selected_candles_missing"],
            "duplicate_conflicts": 0,
            "out_of_order": 0,
            "non_positive_volume": 0,
            "source_disagreement": 0,
            "inconsistent_cutoff": 1,
        }
    for timeframe in REQUIRED_TIMEFRAMES:
        candle = selected.get(timeframe)
        if not isinstance(candle, Mapping):
            reasons.append(f"missing_{timeframe}_candle")
            continue
        if candle.get("is_closed") is not True and candle.get("candle_closed_confirmed") is not True:
            reasons.append(f"{timeframe}_not_closed")
        close_time = int(first_numeric(candle, ("candle_close_time", "close_time", "event_time")) or 0)
        available_at = int(first_numeric(candle, ("available_at", "ingested_at")) or 0)
        if decision_time is not None and close_time and close_time > decision_time:
            reasons.append(f"{timeframe}_close_after_decision")
            inconsistent_cutoff = 1
        if decision_time is not None and available_at and available_at > decision_time:
            reasons.append(f"{timeframe}_available_after_decision")
            inconsistent_cutoff = 1
        rows = candle_index.get((symbol, timeframe, close_time), [])
        if len(rows) > 1:
            hashes = {str(row.get("raw_payload_hash") or row.get("candle_id") or "") for row in rows}
            if len(hashes) > 1:
                duplicate_conflicts += 1
        volumes = [first_numeric(row, ("volume", "quote_volume")) for row in rows]
        if volumes and all((volume or 0.0) <= 0 for volume in volumes):
            non_positive_volume += 1
        sources = {str(row.get("source") or row.get("exchange") or "") for row in rows if row.get("source") or row.get("exchange")}
        if len(sources) > 1:
            source_disagreement += 1
    if mtf_snapshot.get("missing_timeframes"):
        reasons.append("mtf_missing_timeframes")
    if mtf_snapshot.get("reject_reasons"):
        reasons.append("mtf_reject_reasons")
    return {
        "missing_reasons": reasons,
        "duplicate_conflicts": duplicate_conflicts,
        "out_of_order": out_of_order,
        "non_positive_volume": non_positive_volume,
        "source_disagreement": source_disagreement,
        "inconsistent_cutoff": inconsistent_cutoff,
    }


def split_complete_outcomes(trades: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    complete: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for trade in trades:
        missing = [field for field in OUTCOME_REQUIRED_FIELDS if not has_required_value(trade, field)]
        if not (has_required_value(trade, "gross_pnl") or has_required_value(trade, "net_pnl") or has_required_value(trade, "realized_pnl")):
            missing.append("pnl")
        if missing:
            copy = dict(trade)
            copy["_missing_outcome_fields"] = sorted(set(missing))
            incomplete.append(copy)
        else:
            complete.append(trade)
    return complete, incomplete


def compute_realized_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "win_rate": None,
            "gross_pnl": None,
            "fees": None,
            "slippage": None,
            "net_pnl_after_fees_slippage": None,
            "profit_factor_after_fees_slippage": None,
            "expectancy_per_closed_trade": None,
            "average_win": None,
            "average_loss": None,
            "max_drawdown": None,
            "average_holding_time_seconds": None,
            "average_adverse_excursion": None,
            "average_favorable_excursion": None,
            "masa_confidence_average": average_numeric([], ("masa_confidence",)),
            "ppo_confidence_value_average": average_numeric([], ("ppo_confidence", "ppo_value")),
            "router_size_multiplier_average": average_numeric([], ("strategy_size_multiplier", "router_size_multiplier")),
            "blocked_trade_count": 0,
            "avoided_losing_trades": None,
            "avoided_winning_trades": None,
            "net_value_of_blocks": None,
        }
    rows: list[dict[str, float]] = []
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    holding_times: list[float] = []
    for trade in trades:
        gross = first_numeric(trade, ("gross_pnl", "gross_pnl_usd", "realized_pnl_gross", "pnl"))
        net_existing = first_numeric(trade, ("net_pnl", "net_pnl_usd", "realized_pnl", "realized_pnl_after_cost", "pnl_after_cost"))
        fee = first_numeric(trade, ("fees", "fee", "fee_usd", "commission", "commission_usd")) or 0.0
        slippage = first_numeric(trade, ("slippage", "slippage_usd", "slippage_cost", "slippage_cost_usd")) or 0.0
        if gross is None and net_existing is not None:
            gross = net_existing + fee + slippage
        gross = gross or 0.0
        net = net_existing if net_existing is not None else gross - fee - slippage
        equity += net
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        hold_time = hold_time_seconds(trade)
        if hold_time is not None:
            holding_times.append(hold_time)
        rows.append({"gross": gross, "fee": fee, "slippage": slippage, "net": net})
    nets = [row["net"] for row in rows]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0 and gross_profit > 0:
        profit_factor: float | str | None = "Infinity"
    elif gross_loss == 0:
        profit_factor = None
    else:
        profit_factor = gross_profit / gross_loss
    return {
        "win_rate": len(wins) / len(nets),
        "gross_pnl": sum(row["gross"] for row in rows),
        "fees": sum(row["fee"] for row in rows),
        "slippage": sum(row["slippage"] for row in rows),
        "net_pnl_after_fees_slippage": sum(nets),
        "profit_factor_after_fees_slippage": profit_factor,
        "expectancy_per_closed_trade": sum(nets) / len(nets),
        "average_win": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
        "max_drawdown": max_drawdown,
        "average_holding_time_seconds": sum(holding_times) / len(holding_times) if holding_times else None,
        "average_adverse_excursion": average_numeric(trades, ("mae_bps", "max_adverse_bps", "adverse_excursion")),
        "average_favorable_excursion": average_numeric(trades, ("mfe_bps", "max_favorable_bps", "favorable_excursion")),
        "masa_confidence_average": average_numeric(trades, ("masa_confidence",)),
        "ppo_confidence_value_average": average_numeric(trades, ("ppo_confidence", "ppo_value")),
        "router_size_multiplier_average": average_numeric(trades, ("strategy_size_multiplier", "router_size_multiplier")),
        "blocked_trade_count": 0,
        "avoided_losing_trades": None,
        "avoided_winning_trades": None,
        "net_value_of_blocks": None,
    }


def build_ablation_report(predictions: list[dict[str, Any]], trades: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for name in ABLATION_NAMES:
        rows[name] = unavailable_ablation(name, "no_reconstructable_closed_trade_cohort")
    agreement_predictions = [p for p in predictions if masa_ppo_bucket(p) == "agreement"]
    disagreement_predictions = [p for p in predictions if masa_ppo_bucket(p) == "disagreement"]
    if agreement_predictions or disagreement_predictions:
        rows["masa_ppo_agreement_only"]["decision_count"] = len(agreement_predictions)
        rows["masa_ppo_agreement_only"]["availability"] = "closed_outcomes_missing" if not trades else "available"
        rows["masa_ppo_disagreement"]["decision_count"] = len(disagreement_predictions)
        rows["masa_ppo_disagreement"]["availability"] = "closed_outcomes_missing" if not trades else "available"
    return {"generated_at": utc_now(), "cohorts": rows}


def unavailable_ablation(name: str, reason: str) -> dict[str, Any]:
    return {
        "cohort": name,
        "availability": "unavailable",
        "reason": reason,
        "decision_count": 0,
        "closed_trade_count": 0,
        "net_pnl_after_fees_slippage": None,
        "profit_factor": None,
        "expectancy": None,
        "max_drawdown": None,
        "avoided_losing_trades": None,
        "avoided_winning_trades": None,
        "net_value_of_blocks": None,
    }


def masa_ppo_bucket(record: Mapping[str, Any]) -> str:
    masa = str(first_value(record, ("masa_direction", "masa_action", "masa_signal")) or "").lower()
    ppo = str(first_value(record, ("ppo_direction", "ppo_action", "ppo_signal")) or "").lower()
    if masa and ppo and masa == ppo:
        return "agreement"
    if masa and ppo:
        return "disagreement"
    return "unavailable"


def build_liquidity_report(predictions: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    features_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if str(record.get("_category") or "") != "features":
            continue
        symbol = str(first_value(record, ("symbol",)) or "").upper()
        if symbol:
            features_by_symbol[symbol].append(record)
    symbols = sorted({str(first_value(pred, ("symbol",)) or "").upper() for pred in predictions if first_value(pred, ("symbol",))})
    rows = []
    for symbol in symbols:
        feature = latest_feature(features_by_symbol.get(symbol, []))
        spread = nested_numeric(feature, ("bid_ask_spread_bps", "spread_bps"))
        quote_volume = nested_numeric(feature, ("quote_volume", "volume_quote_24h", "volume_24h_quote"))
        liquidity_bucket = liquidity_bucket_for(spread, quote_volume)
        rows.append(
            {
                "symbol": symbol,
                "spread_estimate_bps": spread,
                "volume_liquidity_bucket": liquidity_bucket,
                "slippage_estimate_bps": nested_numeric(feature, ("slippage_bps", "estimated_slippage_bps")),
                "minimum_notional_constraints": None,
                "eligible_for_future_micro_canary": liquidity_bucket in {"high", "medium"} and spread is not None and spread <= 5.0,
                "reason_if_not_eligible": None
                if liquidity_bucket in {"high", "medium"} and spread is not None and spread <= 5.0
                else "liquidity_or_spread_not_proven",
            }
        )
    return {"generated_at": utc_now(), "symbols": rows}


def latest_feature(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    return max(records, key=lambda row: timestamp_ms(first_value(row, ("available_at", "generated_at"))) or 0)


def nested_numeric(record: Mapping[str, Any], fields: tuple[str, ...]) -> float | None:
    direct = first_numeric(record, fields)
    if direct is not None:
        return direct
    features = record.get("features")
    if isinstance(features, Mapping):
        return first_numeric(features, fields)
    return None


def liquidity_bucket_for(spread: float | None, quote_volume: float | None) -> str:
    if spread is None and quote_volume is None:
        return "unknown"
    if quote_volume is not None and quote_volume >= 1_000_000 and (spread is None or spread <= 5.0):
        return "high"
    if quote_volume is not None and quote_volume >= 100_000 and (spread is None or spread <= 10.0):
        return "medium"
    if quote_volume is not None and quote_volume > 0:
        return "low"
    return "unknown"


def classify_residual_findings(records: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "active_decision_affecting": 0,
        "inactive_stale_non_consumable": count_records(records, "candles") + count_records(records, "features"),
        "exporter_verifier_residue": 0,
        "provider_discrepancy": 0,
        "model_disagreement": sum(1 for prediction in predictions if masa_ppo_bucket(prediction) == "disagreement"),
        "parity_difference": 0,
    }


def count_records(records: Iterable[Mapping[str, Any]], category: str) -> int:
    return sum(1 for record in records if str(record.get("_category") or "") == category)


def extract_live_state(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "live_gate": "blocked_human_only",
        "order_transport_submit_enabled": False,
        "live_trading_enabled": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "any_live_submit_enabled": False,
    }
    for record in records:
        key = str(record.get("_key") or "")
        if "live_gate:state" not in key and "trader:execution_state" not in key and "live_order_transport" not in key:
            continue
        for field in ("live_gate", "order_transport_submit_enabled", "live_trading_enabled", "places_real_order", "exchange_action_taken"):
            value = first_value(record, (field,))
            if value is not None:
                fields[field] = value
        if any(truthy(first_value(record, (field,))) for field in ("order_transport_submit_enabled", "live_trading_enabled", "places_real_order", "exchange_action_taken")):
            fields["any_live_submit_enabled"] = True
    return fields


def classify_release_gate(
    *,
    strict_summary: Mapping[str, Any],
    valid_decisions: int,
    closed_trades: int,
    min_trusted_decisions: int,
    min_closed_trades: int,
    dirty_accepted_decisions: int,
    replay_failures: int,
    mtf_failures: int,
    active_missing_contract: int,
    active_inconsistent_cutoff: int,
    live_state: Mapping[str, Any],
    metrics: Mapping[str, Any],
    profit_factor_threshold: float,
    liquidity_report: Mapping[str, Any],
    accepted_intents: int,
    open_trades: int,
) -> dict[str, Any]:
    trust_clean = (
        int(strict_summary.get("critical_failures") or 0) == 0
        and dirty_accepted_decisions == 0
        and replay_failures == 0
        and mtf_failures == 0
        and active_missing_contract == 0
        and active_inconsistent_cutoff == 0
        and not truthy(live_state.get("any_live_submit_enabled"))
    )
    pf = metrics.get("profit_factor_after_fees_slippage")
    pf_value = math.inf if pf == "Infinity" else (float(pf) if pf is not None else None)
    expectancy = metrics.get("expectancy_per_closed_trade")
    liquid_symbols = [row for row in liquidity_report.get("symbols", []) if row.get("eligible_for_future_micro_canary")]
    if not trust_clean:
        status = "NO-GO"
        edge_status = "TRUST_GATE_FAILED"
    elif closed_trades == 0:
        status = "NO-GO"
        edge_status = "NO_CLOSED_TRADE_OUTCOMES"
    elif closed_trades < min_closed_trades or valid_decisions < min_trusted_decisions:
        status = "PRELIMINARY"
        edge_status = "INSUFFICIENT_SAMPLE"
    elif expectancy is not None and expectancy > 0 and pf_value is not None and pf_value > profit_factor_threshold and liquid_symbols:
        status = "GO"
        edge_status = "EDGE_POSITIVE"
    else:
        status = "NO-GO"
        edge_status = "EDGE_OR_LIQUIDITY_GATE_FAILED"
    return {
        "generated_at": utc_now(),
        "sample_size_status": status,
        "edge_gate_status": edge_status,
        "backend_tests_green": None,
        "strict_verifier_exit_code": 0 if int(strict_summary.get("critical_failures") or 0) == 0 else 1,
        "recorded_state_verifier_exit_code": None,
        "active_decisions_evaluated": valid_decisions,
        "closed_trades_evaluated": closed_trades,
        "minimum_trusted_decisions": min_trusted_decisions,
        "minimum_closed_trades": min_closed_trades,
        "dirty_accepted_decisions": dirty_accepted_decisions,
        "replay_reconstruction_failures": replay_failures,
        "mtf_reconstruction_failures": mtf_failures,
        "active_missing_contract_count": active_missing_contract,
        "active_inconsistent_cutoff_count": active_inconsistent_cutoff,
        "net_expectancy_after_fees_slippage": expectancy,
        "profit_factor_after_fees_slippage": pf,
        "profit_factor_threshold": profit_factor_threshold,
        "liquidity_eligible_symbols": [row.get("symbol") for row in liquid_symbols],
        "live_control_state": dict(live_state),
        "no_live_order_submitted": not truthy(live_state.get("exchange_action_taken")) and not truthy(live_state.get("places_real_order")),
        "pass2c_verdict": pass2c_verdict(
            accepted_intents=accepted_intents,
            closed_trades=closed_trades,
            open_trades=open_trades,
            trust_clean=trust_clean,
        ),
    }


def pass2c_verdict(*, accepted_intents: int, closed_trades: int, open_trades: int, trust_clean: bool) -> str:
    if not trust_clean:
        return "NO-GO"
    if accepted_intents <= 0:
        return "NO-GO"
    if closed_trades > 0:
        return "GO"
    if open_trades > 0:
        return "PRELIMINARY"
    return "PRELIMINARY"


def classify_pass2e_gate(
    *,
    confidence_trace: Mapping[str, Any],
    release_gate: Mapping[str, Any],
    accepted_intents: int,
    live_state: Mapping[str, Any],
) -> dict[str, Any]:
    real_count = int(confidence_trace.get("real_model_confidence_count") or 0)
    placeholder_count = int(confidence_trace.get("placeholder_or_default_confidence_count") or 0)
    missing_count = int(confidence_trace.get("missing_confidence_count") or 0)
    routeability_candidates = int(confidence_trace.get("routeability_candidate_count") or 0)
    routeability_placeholder_count = int(confidence_trace.get("routeability_placeholder_or_default_confidence_count") or 0)
    above_threshold = int(confidence_trace.get("predictions_above_threshold") or 0)
    below_threshold = int(confidence_trace.get("predictions_below_threshold") or 0)
    trust_clean = (
        int(release_gate.get("strict_verifier_exit_code", 1)) == 0
        and int(release_gate.get("dirty_accepted_decisions") or 0) == 0
        and int(release_gate.get("replay_reconstruction_failures") or 0) == 0
        and int(release_gate.get("mtf_reconstruction_failures") or 0) == 0
        and int(release_gate.get("active_missing_contract_count") or 0) == 0
        and int(release_gate.get("active_inconsistent_cutoff_count") or 0) == 0
        and not truthy(live_state.get("any_live_submit_enabled"))
    )
    if not trust_clean:
        verdict = "NO-GO"
        reason = "TRUST_GATE_FAILED"
    elif routeability_candidates <= 0 and placeholder_count > 0:
        verdict = "NO-GO"
        reason = "PLACEHOLDER_CONFIDENCE_PERSISTS"
    elif routeability_candidates <= 0:
        verdict = "NO-GO"
        reason = "REAL_INFERENCE_UNAVAILABLE"
    elif routeability_placeholder_count > 0:
        verdict = "NO-GO"
        reason = "ROUTEABILITY_CANDIDATES_INCLUDE_PLACEHOLDER_CONFIDENCE"
    elif accepted_intents > 0:
        verdict = "GO"
        reason = "REAL_INFERENCE_ROUTEABLE_INTENT_ACCEPTED"
    elif above_threshold <= 0:
        verdict = "NO-GO"
        reason = "ALL_REAL_MODEL_CONFIDENCE_BELOW_THRESHOLD"
    else:
        verdict = "NO-GO"
        reason = "NO_ACCEPTED_INTENT_DESPITE_ABOVE_THRESHOLD_CONFIDENCE"
    return {
        "generated_at": utc_now(),
        "verdict": verdict,
        "reason": reason,
        "real_model_confidence_count": real_count,
        "placeholder_or_default_confidence_count": placeholder_count,
        "missing_confidence_count": missing_count,
        "routeability_candidate_count": routeability_candidates,
        "routeability_placeholder_or_default_confidence_count": routeability_placeholder_count,
        "predictions_above_threshold": above_threshold,
        "predictions_below_threshold": below_threshold,
        "accepted_paper_or_shadow_intents": accepted_intents,
        "live_submit_disabled": not truthy(live_state.get("any_live_submit_enabled")),
        "no_live_order_submitted": not truthy(live_state.get("exchange_action_taken")) and not truthy(live_state.get("places_real_order")),
    }


def build_prediction_producer_inventory(predictions: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts: dict[str, int] = defaultdict(int)
    for prediction in predictions:
        source_counts[prediction_confidence_provenance(prediction)] += 1
    return {
        "generated_at": utc_now(),
        "current_evidence": {
            "prediction_records": len(predictions),
            "confidence_source_counts": dict(sorted(source_counts.items())),
            "signals_paper_records": sum(1 for record in records if "signals:paper" in str(record.get("_key") or "")),
        },
        "producers": prediction_producer_rows(),
    }


def prediction_confidence_provenance(prediction: Mapping[str, Any]) -> str:
    explicit = str(first_value(prediction, ("confidence_source", "combined_confidence_source")) or "").upper()
    if explicit in {"REAL_MODEL", "PROOF_DEFAULT", "PLACEHOLDER", "MISSING", "INFERRED"}:
        return explicit
    calibration = first_value(prediction, ("confidence_calibration",))
    calibration_text = json.dumps(calibration, sort_keys=True, default=str).lower() if isinstance(calibration, Mapping) else str(calibration or "").lower()
    if "publisher_proof" in calibration_text or "proof" in calibration_text:
        return "PROOF_DEFAULT"
    values = [
        first_numeric(prediction, ("confidence_raw",)),
        first_numeric(prediction, ("confidence_normalized", "confidence_calibrated", "confidence")),
        first_numeric(prediction, ("masa_confidence",)),
        first_numeric(prediction, ("ppo_confidence", "ppo_action_probability", "ppo_action_confidence")),
    ]
    if all(value is None for value in values):
        return "MISSING"
    if all((value or 0.0) == 0.0 for value in values if value is not None):
        return "PLACEHOLDER"
    return "INFERRED"


def is_routeability_candidate(prediction: Mapping[str, Any]) -> bool:
    if prediction_confidence_provenance(prediction) != "REAL_MODEL":
        return False
    if truthy(first_value(prediction, ("proof_only", "paper_only_diagnostic_prediction"))):
        return False
    if first_value(prediction, ("model_consumable",)) is False:
        return False
    if first_value(prediction, ("paper_intent_consumable",)) is False:
        return False
    if first_value(prediction, ("routeability_candidate",)) is False:
        return False
    if truthy(first_value(prediction, ("routes_to_live", "live_order_allowed", "places_real_order", "exchange_action_taken"))):
        return False
    return True


def prediction_producer_rows() -> list[dict[str, Any]]:
    return [
        {
            "file_path": "v2/backend/app/cli/run_trusted_prediction_publisher_once.py",
            "function_or_class": "run_publisher_proof_once",
            "redis_key_written": "v2:prediction:{symbol}:{timeframe}",
            "producer_type": "proof_publisher",
            "uses_real_ppo_inference": False,
            "uses_real_masa_inference": False,
            "writes_real_confidence": False,
            "confidence": "PROOF_DEFAULT/PLACEHOLDER",
            "paper_intent_consumable": "only as blocked artifact proof, not Pass 2E routeability",
            "can_route_to_live": False,
            "routes_to_live_disabled": True,
        },
        {
            "file_path": "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py",
            "function_or_class": "Hybrid CUDA trainer runtime",
            "redis_key_written": "delegates to V2HybridPredictionPublisher.publish_prediction",
            "producer_type": "intended_real_runtime",
            "uses_real_ppo_inference": "upstream_contract_required",
            "uses_real_masa_inference": "upstream_contract_required",
            "writes_real_confidence": "not_observed_in_current_evidence",
            "confidence": "REAL_MODEL only if upstream payload provides explicit provenance",
            "paper_intent_consumable": "yes only with confidence_source=REAL_MODEL and non-live flags",
            "can_route_to_live": False,
            "routes_to_live_disabled": "must remain true for Pass 2E",
        },
        {
            "file_path": "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py",
            "function_or_class": "V2HybridPredictionPublisher.publish_prediction",
            "redis_key_written": "v2:prediction:{symbol}:{timeframe}; v2:replay:snapshots:*",
            "producer_type": "publisher_transport",
            "uses_real_ppo_inference": False,
            "uses_real_masa_inference": False,
            "writes_real_confidence": "passes through payload only",
            "confidence": "source depends on caller payload",
            "paper_intent_consumable": "yes only with explicit REAL_MODEL provenance",
            "can_route_to_live": False,
            "routes_to_live_disabled": "payload_enforced_for_paper_proof",
        },
        {
            "file_path": "v2/backend/app/services/trainer_bridge_exit/native_prediction_publisher.py",
            "function_or_class": "publish_predictions_for_universe",
            "redis_key_written": "v2:prediction:{symbol}:{timeframe}",
            "producer_type": "native_trainer_bridge",
            "uses_real_ppo_inference": "not_proven_by_current_evidence",
            "uses_real_masa_inference": "not_proven_by_current_evidence",
            "writes_real_confidence": "not_proven_by_current_evidence",
            "confidence": "contract dependent",
            "paper_intent_consumable": "requires REAL_MODEL confidence provenance",
            "can_route_to_live": False,
            "routes_to_live_disabled": "required for Pass 2E",
        },
        {
            "file_path": "v2/backend/app/services/native_trainer/baseline_model.py",
            "function_or_class": "baseline prediction publisher",
            "redis_key_written": "v2:prediction:{symbol}:{timeframe}",
            "producer_type": "baseline_model",
            "uses_real_ppo_inference": False,
            "uses_real_masa_inference": False,
            "writes_real_confidence": "baseline_only",
            "confidence": "not valid as PPO/MASA routeability proof unless explicitly labeled REAL_MODEL by contract",
            "paper_intent_consumable": "not Pass 2E routeability by default",
            "can_route_to_live": False,
            "routes_to_live_disabled": True,
        },
        {
            "file_path": "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
            "function_or_class": "all-timeframe signal/paper publisher",
            "redis_key_written": "v2:prediction:{symbol}:{timeframe}; v2:signals:paper:{symbol}:{timeframe}",
            "producer_type": "signal_aggregator",
            "uses_real_ppo_inference": "consumes_upstream_prediction",
            "uses_real_masa_inference": "consumes_upstream_prediction",
            "writes_real_confidence": "passes through or derives from upstream",
            "confidence": "not source of truth unless provenance remains REAL_MODEL",
            "paper_intent_consumable": "yes only if upstream prediction is REAL_MODEL and non-live",
            "can_route_to_live": False,
            "routes_to_live_disabled": "required for Pass 2E",
        },
        {
            "file_path": "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
            "function_or_class": "orchestrator paper signal publisher",
            "redis_key_written": "v2:signals:paper",
            "producer_type": "paper_signal_consumer",
            "uses_real_ppo_inference": "consumes_v2_prediction",
            "uses_real_masa_inference": "consumes_v2_prediction",
            "writes_real_confidence": False,
            "confidence": "must not upgrade proof/default confidence",
            "paper_intent_consumable": "yes after StrategyRouter/RiskGateway acceptance",
            "can_route_to_live": False,
            "routes_to_live_disabled": True,
        },
    ]


def build_trade_sample(
    predictions: list[dict[str, Any]],
    complete_trades: list[dict[str, Any]],
    incomplete_trades: list[dict[str, Any]],
    replay_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    trades_by_prediction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in complete_trades + incomplete_trades:
        pred_id = str(first_value(trade, ("prediction_id",)) or "")
        if pred_id:
            trades_by_prediction[pred_id].append(trade)
    for prediction in predictions:
        pred_id = str(first_value(prediction, ("prediction_id",)) or "")
        rows.append(
            {
                "prediction_id": pred_id,
                "decision_id": first_value(prediction, ("decision_id",)),
                "symbol": first_value(prediction, ("symbol",)),
                "timeframe": first_value(prediction, ("timeframe",)),
                "replay_snapshot_id": first_value(prediction, ("replay_snapshot_id",)),
                "mtf_snapshot_id": first_value(prediction, ("mtf_snapshot_id",)),
                "paper_only": first_value(prediction, ("paper_only",)),
                "shadow_only": first_value(prediction, ("shadow_only",)),
                "routes_to_live": first_value(prediction, ("routes_to_live",)),
                "live_order_allowed": first_value(prediction, ("live_order_allowed",)),
                "selected_action": first_value(prediction, ("selected_action", "action")),
                "closed_trade_records": len(trades_by_prediction.get(pred_id, [])),
                "replay_snapshot_found": str(first_value(prediction, ("replay_snapshot_id",)) or "") in replay_by_id,
            }
        )
    return rows


def build_lifecycle_diagnostics(
    predictions: list[dict[str, Any]],
    records: list[dict[str, Any]],
    complete_closed: list[dict[str, Any]],
    incomplete_closed: list[dict[str, Any]],
    open_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = defaultdict(int)
    for prediction in predictions:
        pred_id = str(first_value(prediction, ("prediction_id",)) or "")
        linked = [record for record in records if record_links_prediction(record, prediction)]
        intents = [record for record in linked if is_paper_intent(record) and not is_live_record(record)]
        accepted_intents = [record for record in intents if is_accepted_paper_intent(record)]
        fills = [record for record in linked if is_fill_like_record(record)]
        opened = [record for record in linked if is_open_trade(record) or is_closed_trade(record)]
        closed = [record for record in complete_closed + incomplete_closed if record_links_prediction(record, prediction)]
        open_for_prediction = [record for record in open_trades if record_links_prediction(record, prediction)]
        fees_recorded = any(has_required_value(record, "fees") or has_required_value(record, "fee") for record in closed + fills)
        slippage_recorded = any(has_required_value(record, "slippage") or has_required_value(record, "slippage_usd") for record in closed + fills)
        reason = missing_closed_trade_reason(
            prediction=prediction,
            intents=accepted_intents,
            fills=fills,
            opened=opened,
            closed=closed,
            open_for_prediction=open_for_prediction,
            fees_recorded=fees_recorded,
            slippage_recorded=slippage_recorded,
        )
        reason_counts[reason] += 1
        rows.append(
            {
                "prediction_id": pred_id,
                "symbol": first_value(prediction, ("symbol",)),
                "timeframe": first_value(prediction, ("timeframe",)),
                "strategy_router_output": {
                    "selected_action": first_value(prediction, ("selected_action", "action")),
                    "selected_strategy_mode": first_value(prediction, ("selected_strategy_mode", "strategy_selected_mode")),
                    "regime_label": first_value(prediction, ("regime_label", "strategy_regime_label", "strategy_regime_labels")),
                    "paper_fill_allowed": first_value(prediction, ("paper_fill_allowed",)),
                    "paper_eligible": first_value(prediction, ("paper_eligible",)),
                    "block_reason": first_value(prediction, ("blocked_reason", "paper_fill_gate_block_reasons", "strategy_router_block_reason")),
                },
                "paper_or_shadow_intent_created": bool(intents),
                "accepted_paper_or_shadow_intent_created": bool(accepted_intents),
                "raw_paper_or_shadow_intent_records": len(intents),
                "fill_created": bool(fills),
                "position_opened": bool(opened),
                "exit_rule_existed": any(first_value(record, ("exit_reason", "exit_rule", "close_reason")) is not None for record in linked),
                "position_still_open": bool(open_for_prediction),
                "fees_recorded": fees_recorded,
                "slippage_recorded": slippage_recorded,
                "closed_trade_recorded": bool(closed),
                "missing_closed_trade_reason": reason,
            }
        )
    return {"summary": dict(sorted(reason_counts.items())), "predictions": rows}


def record_links_prediction(record: Mapping[str, Any], prediction: Mapping[str, Any]) -> bool:
    identifiers = {
        "prediction_id": str(first_value(prediction, ("prediction_id",)) or ""),
        "decision_id": str(first_value(prediction, ("decision_id",)) or ""),
        "replay_snapshot_id": str(first_value(prediction, ("replay_snapshot_id",)) or ""),
        "mtf_snapshot_id": str(first_value(prediction, ("mtf_snapshot_id",)) or ""),
    }
    for field, expected in identifiers.items():
        if expected and str(first_value(record, (field,)) or "") == expected:
            return True
    lineage = record.get("lineage_ids")
    if isinstance(lineage, Mapping):
        return any(expected and str(value) == expected for expected in identifiers.values() for value in lineage.values())
    return False


def missing_closed_trade_reason(
    *,
    prediction: Mapping[str, Any],
    intents: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    opened: list[dict[str, Any]],
    closed: list[dict[str, Any]],
    open_for_prediction: list[dict[str, Any]],
    fees_recorded: bool,
    slippage_recorded: bool,
) -> str:
    if closed and not fees_recorded:
        return "fee_slippage_missing"
    if closed and not slippage_recorded:
        return "fee_slippage_missing"
    if closed:
        return "closed_trade_available"
    if open_for_prediction:
        return "still_open_by_design"
    if not intents:
        if not decision_is_accepted(prediction):
            return "intent_blocked"
        return "prediction_never_became_intent"
    if intents and not fills:
        return "intent_accepted_but_no_fill"
    if fills and not opened:
        return "fill_created_but_no_position"
    if opened:
        return "position_opened_but_no_exit_triggered"
    return "other"


def is_fill_like_record(record: Mapping[str, Any]) -> bool:
    status = order_status(dict(record))
    if status in {"blocked", "denied", "rejected", "canceled", "cancelled", "expired"}:
        return False
    if status in {"filled", "partially_filled", "partial_fill"}:
        return True
    return first_value(record, ("fill_price", "avg_fill_price")) is not None and is_accepted_paper_intent(record)


def build_paper_intent_block_trace(
    predictions: list[dict[str, Any]],
    records: list[dict[str, Any]],
    lifecycle_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    diagnostics_by_prediction = {
        str(row.get("prediction_id") or ""): row
        for row in lifecycle_diagnostics.get("predictions", [])
        if isinstance(row, Mapping)
    }
    rows: list[dict[str, Any]] = []
    distribution: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        pred_id = str(first_value(prediction, ("prediction_id",)) or "")
        linked = [record for record in records if record_links_prediction(record, prediction)]
        signal = first_linked_by_key(linked, "signals:paper")
        risk = first_linked_by_key(linked, "risk:decisions") or first_linked_by_key(linked, "risk:gateway")
        diagnostic = diagnostics_by_prediction.get(pred_id, {})
        category, affected_fields, legitimacy, recommended_action = classify_block_root_cause(prediction, signal, risk, diagnostic)
        symbol = str(first_value(prediction, ("symbol",)) or "").upper()
        distribution.setdefault(
            category,
            {
                "count": 0,
                "affected_symbols": set(),
                "affected_fields": set(),
                "legitimacy": legitimacy,
                "recommended_action": recommended_action,
            },
        )
        distribution[category]["count"] += 1
        if symbol:
            distribution[category]["affected_symbols"].add(symbol)
        for field in affected_fields:
            distribution[category]["affected_fields"].add(field)
        rows.append(
            {
                "prediction_id": pred_id,
                "symbol": symbol,
                "timeframe": first_value(prediction, ("timeframe",)),
                "decision_time": first_value(prediction, ("decision_time",)),
                "paper_only": first_value(prediction, ("paper_only",)),
                "routes_to_live": first_value(prediction, ("routes_to_live",)),
                "live_order_allowed": first_value(prediction, ("live_order_allowed",)),
                "mtf_snapshot_id": first_value(prediction, ("mtf_snapshot_id",)),
                "replay_snapshot_id": first_value(prediction, ("replay_snapshot_id",)),
                "masa_direction": first_value(prediction, ("masa_direction", "masa_action", "masa_signal")),
                "masa_confidence": first_value(prediction, ("masa_confidence", "confidence_calibrated", "confidence")),
                "ppo_action": first_value(prediction, ("ppo_action", "selected_action", "action")),
                "ppo_confidence": first_value(prediction, ("ppo_confidence", "confidence_raw")),
                "ppo_value": first_value(prediction, ("ppo_value", "value_estimate")),
                "masa_ppo_agreement_status": masa_ppo_bucket(prediction),
                "selected_strategy_mode": first_value(risk or prediction, ("strategy_selected_mode", "selected_strategy_mode")),
                "regime_label": first_value(risk or prediction, ("strategy_regime_labels", "regime_label", "strategy_regime_label")),
                "action_mask": first_value(prediction, ("action_mask",)),
                "allowed_actions": first_value(risk or prediction, ("strategy_allowed_actions", "allowed_actions", "action_labels")),
                "router_block_reason": first_value(risk or signal or prediction, ("strategy_router_block_reason", "router_block_reason")),
                "risk_block_reason": first_value(risk or prediction, ("risk_block_reason", "risk_state", "fee_gate_reason")),
                "paper_fill_block_reason": first_value(signal or prediction, ("paper_fill_gate_block_reasons", "paper_fill_block_reason", "blocked_reason")),
                "paper_intent_created": diagnostic.get("paper_or_shadow_intent_created", False),
                "paper_intent_key": first_value(first_linked_by_key(linked, "paper:intents") or {}, ("_key",)),
                "shadow_intent_created": any(truthy(first_value(record, ("shadow_only", "shadow_intent"))) for record in linked),
                "shadow_key": first_value(first_linked_by_key(linked, "shadow") or {}, ("_key",)),
                "liquidity_eligibility_status": "unknown",
                "spread_slippage_bucket": "unknown",
                "portfolio_equity_margin_status": first_value(risk or signal or prediction, ("portfolio_equity_status", "margin_status", "balance_status")),
                "position_state_before_decision": first_value(risk or signal or prediction, ("position_state", "position_state_before_decision")),
                "exact_final_block_reason": diagnostic.get("missing_closed_trade_reason"),
                "root_cause_category": category,
                "affected_fields": affected_fields,
                "block_legitimacy": legitimacy,
                "recommended_action": recommended_action,
            }
        )
    return {
        "predictions": rows,
        "distribution": {
            category: {
                "count": values["count"],
                "affected_symbols": sorted(values["affected_symbols"]),
                "affected_fields": sorted(values["affected_fields"]),
                "legitimacy": values["legitimacy"],
                "recommended_action": values["recommended_action"],
            }
            for category, values in sorted(distribution.items())
        },
    }


def first_linked_by_key(records: Iterable[Mapping[str, Any]], key_fragment: str) -> Mapping[str, Any] | None:
    needle = key_fragment.lower()
    for record in records:
        if needle in str(record.get("_key") or "").lower():
            return record
    return None


def classify_block_root_cause(
    prediction: Mapping[str, Any],
    signal: Mapping[str, Any] | None,
    risk: Mapping[str, Any] | None,
    diagnostic: Mapping[str, Any],
) -> tuple[str, list[str], str, str]:
    source = risk or signal or prediction
    action = str(first_value(source, ("side", "selected_action", "action", "ppo_action")) or "").lower()
    router_reason = str(first_value(source, ("strategy_router_block_reason", "router_block_reason")) or "")
    paper_reasons = first_value(signal or prediction, ("paper_fill_gate_block_reasons", "blocked_reason", "paper_fill_block_reason"))
    fee_reason = str(first_value(risk or {}, ("fee_gate_reason",)) or "")
    risk_state = str(first_value(risk or signal or {}, ("risk_state", "paper_fill_gate_status")) or "")
    missing_reason = str(diagnostic.get("missing_closed_trade_reason") or "")
    reason_text = " ".join(str(value) for value in (action, router_reason, paper_reasons, fee_reason, risk_state, missing_reason)).lower()
    if missing_reason == "prediction_never_became_intent":
        return (
            "PAPER_INTENT_CONTRACT_MISSING_FIELD",
            ["paper_intent_id", "paper_intent_writer"],
            "contract/plumbing drift",
            "Verify trusted prediction consumption by paper intent builder.",
        )
    if "liquidity" in reason_text:
        return ("LOW_LIQUIDITY_BLOCK", ["liquidity", "volume", "spread"], "legitimate block", "Use liquid eligible symbols or wait for liquidity evidence.")
    if "spread" in reason_text or "slippage" in reason_text:
        return ("SPREAD_SLIPPAGE_BLOCK", ["spread", "slippage"], "legitimate block", "Do not force intent; collect better liquidity/spread evidence.")
    if "confidence" in reason_text:
        return ("LOW_CONFIDENCE_BLOCK", ["confidence_calibrated", "expected_move_after_cost_bps"], "legitimate block", "Do not force intent; collect eligible higher-confidence decisions.")
    if "execution_success_probability" in reason_text:
        return (
            "STRATEGY_ROUTER_NO_TRADE",
            ["strategy_router_block_reason", "execution_success_probability"],
            "legitimate block",
            "Generate a new trusted batch from symbols/timeframes that pass router gates.",
        )
    if action in HOLD_ACTIONS or "no_trade" in reason_text:
        return ("STRATEGY_ROUTER_NO_TRADE", ["selected_action", "strategy_selected_mode"], "legitimate block", "Record as no-trade; do not force paper intent.")
    if "allowed_action" in reason_text or "action_mask" in reason_text:
        return ("ACTION_MASK_NO_ALLOWED_ACTION", ["action_mask", "allowed_actions"], "legitimate block", "Do not bypass action mask.")
    if "margin" in reason_text or "notional" in reason_text:
        return ("MARGIN_OR_NOTIONAL_BLOCK", ["notional", "margin"], "legitimate block", "Seed/fix paper-only equity only if missing by contract drift.")
    if "position" in reason_text:
        return ("POSITION_STATE_BLOCK", ["position_state"], "legitimate block", "Respect position state machine.")
    if "risk" in reason_text or "gate" in reason_text:
        return ("TRUST_GATE_BLOCK", ["risk_state", "paper_fill_gate_status"], "legitimate block", "Do not bypass risk/trust gate.")
    return ("OTHER", ["unknown"], "needs investigation", "Inspect linked prediction/signal/risk records.")


def build_confidence_block_trace(
    predictions: list[dict[str, Any]],
    records: list[dict[str, Any]],
    block_trace: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = confidence_threshold_from_records(records)
    block_by_prediction = {
        str(row.get("prediction_id") or ""): row
        for row in block_trace.get("predictions", [])
        if isinstance(row, Mapping)
    }
    rows: list[dict[str, Any]] = []
    confidence_values: list[float] = []
    above = 0
    below = 0
    placeholder_count = 0
    real_count = 0
    missing_count = 0
    inferred_count = 0
    routeability_candidate_count = 0
    routeability_placeholder_count = 0
    for prediction in predictions:
        pred_id = str(first_value(prediction, ("prediction_id",)) or "")
        block = block_by_prediction.get(pred_id, {})
        confidence = confidence_value(prediction)
        if confidence is not None:
            confidence_values.append(confidence)
            if confidence >= threshold:
                above += 1
            else:
                below += 1
        source = prediction_source(prediction)
        provenance = prediction_confidence_provenance(prediction)
        routeability_candidate = is_routeability_candidate(prediction)
        placeholder = confidence_is_placeholder(prediction)
        if provenance == "MISSING":
            missing_count += 1
        elif provenance == "INFERRED":
            inferred_count += 1
        if provenance in {"PROOF_DEFAULT", "PLACEHOLDER", "MISSING", "INFERRED"} or placeholder:
            placeholder_count += 1
        if routeability_candidate and provenance == "REAL_MODEL" and not placeholder:
            real_count += 1
            routeability_candidate_count += 1
        elif routeability_candidate:
            routeability_candidate_count += 1
            routeability_placeholder_count += 1
        action_probabilities = first_value(prediction, ("action_probabilities",))
        rows.append(
            {
                "prediction_id": pred_id,
                "symbol": first_value(prediction, ("symbol",)),
                "timeframe": first_value(prediction, ("timeframe",)),
                "decision_time": first_value(prediction, ("decision_time",)),
                "prediction_source": source,
                "masa_direction": first_value(prediction, ("masa_direction", "masa_action", "masa_signal")),
                "masa_confidence_raw": first_value(prediction, ("masa_confidence", "confidence_raw")),
                "masa_confidence_normalized": first_value(prediction, ("masa_confidence_normalized", "confidence_calibrated", "confidence")),
                "masa_confidence_threshold": threshold,
                "ppo_action": first_value(prediction, ("ppo_action", "selected_action", "action")),
                "ppo_action_probability": max_numeric(action_probabilities),
                "ppo_value_estimate": first_value(prediction, ("ppo_value", "value_estimate")),
                "ppo_confidence_threshold": threshold,
                "combined_confidence_score": confidence,
                "confidence_source": provenance,
                "routeability_candidate": routeability_candidate,
                "final_confidence_threshold": threshold,
                "selected_strategy_mode": block.get("selected_strategy_mode") or first_value(prediction, ("selected_strategy_mode",)),
                "regime_label": block.get("regime_label") or first_value(prediction, ("regime_label",)),
                "masa_ppo_agreement_status": masa_ppo_bucket(prediction),
                "action_mask": first_value(prediction, ("action_mask",)),
                "allowed_actions": block.get("allowed_actions") or first_value(prediction, ("allowed_actions", "action_labels")),
                "risk_score": first_value(prediction, ("risk_score", "market_state_integrity_score")),
                "router_block_reason": block.get("router_block_reason"),
                "exact_confidence_block_field": "confidence_calibrated" if confidence is not None and confidence < threshold else None,
                "confidence_missing_defaulted_inferred": placeholder or confidence is None,
                "confidence_from_real_model_output": provenance == "REAL_MODEL" and routeability_candidate,
                "root_cause_category": block.get("root_cause_category"),
            }
        )
    return {
        "generated_at": utc_now(),
        "threshold": threshold,
        "prediction_count": len(predictions),
        "confidence_distribution": confidence_distribution(confidence_values),
        "predictions_above_threshold": above,
        "predictions_below_threshold": below,
        "placeholder_or_default_confidence_count": placeholder_count,
        "missing_confidence_count": missing_count,
        "inferred_confidence_count": inferred_count,
        "real_model_confidence_count": real_count,
        "routeability_candidate_count": routeability_candidate_count,
        "routeability_placeholder_or_default_confidence_count": routeability_placeholder_count,
        "low_confidence_block_count": sum(1 for row in rows if row.get("root_cause_category") == "LOW_CONFIDENCE_BLOCK"),
        "source_of_truth": confidence_source_table(threshold),
        "predictions": rows,
        "verdict": "NO-GO" if above == 0 or real_count == 0 else "PRELIMINARY",
    }


def confidence_threshold_from_records(records: Iterable[Mapping[str, Any]]) -> float:
    for record in records:
        risk_profile = record.get("risk_profile")
        if isinstance(risk_profile, Mapping):
            fields = risk_profile.get("fields")
            if isinstance(fields, Mapping):
                value = first_numeric(fields, ("min_confidence_calibrated",))
                if value is not None:
                    return value
        value = first_numeric(record, ("min_confidence_calibrated", "confidence_threshold", "min_confidence"))
        if value is not None:
            return value
    return 0.66


def confidence_value(record: Mapping[str, Any]) -> float | None:
    return first_numeric(record, ("confidence_calibrated", "confidence", "combined_confidence_score", "masa_confidence_normalized"))


def prediction_source(record: Mapping[str, Any]) -> str:
    producer = str(first_value(record, ("producer", "publisher", "source", "checkpoint_source")) or "").lower()
    mode = ""
    calibration = record.get("confidence_calibration")
    if isinstance(calibration, Mapping):
        mode = str(calibration.get("mode") or "").lower()
    if "publisher_proof" in producer or "publisher_proof" in mode:
        return "proof_publisher"
    if "hybrid" in producer or "cuda" in producer:
        return "hybrid_cuda_trainer_publisher"
    if "masa" in producer:
        return "masa_adapter"
    if "ppo" in producer:
        return "real_ppo_inference"
    return str(first_value(record, ("checkpoint_source",)) or "unknown")


def confidence_is_placeholder(record: Mapping[str, Any]) -> bool:
    calibration = record.get("confidence_calibration")
    mode = str(calibration.get("mode") if isinstance(calibration, Mapping) else "").lower()
    if "publisher_proof" in mode or "hold_no_trade" in mode:
        return True
    source = prediction_source(record)
    if source == "proof_publisher":
        return True
    value = confidence_value(record)
    action = str(first_value(record, ("selected_action", "action", "ppo_action")) or "").lower()
    return value == 0.0 and action in HOLD_ACTIONS


def max_numeric(value: Any) -> float | None:
    if not isinstance(value, (list, tuple, set)):
        return None
    numbers: list[float] = []
    for item in value:
        try:
            numbers.append(float(item))
        except (TypeError, ValueError):
            pass
    return max(numbers) if numbers else None


def confidence_distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "max": None}
    sorted_values = sorted(values)
    return {
        "min": sorted_values[0],
        "p25": percentile(sorted_values, 0.25),
        "median": percentile(sorted_values, 0.5),
        "p75": percentile(sorted_values, 0.75),
        "max": sorted_values[-1],
    }


def percentile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


def confidence_source_table(threshold: float) -> list[dict[str, Any]]:
    return [
        {
            "component": "trusted prediction publisher",
            "confidence_field_read": "confidence_raw/confidence_calibrated",
            "confidence_field_written": "confidence_raw/confidence_calibrated/confidence_calibration",
            "default_value": "0.0 for publisher-proof hold/no-trade payloads",
            "threshold_value": threshold,
            "config_env_source": "risk_profile.fields.min_confidence_calibrated or fallback 0.66",
            "scale": "0-1 probability",
            "missing_value_behavior": "reported as confidence missing/defaulted in trace",
            "block_behavior": "downstream paper fill gate blocks below threshold",
        },
        {
            "component": "paper fill gate / edge report",
            "confidence_field_read": "confidence_calibrated/confidence",
            "confidence_field_written": "none",
            "default_value": "none",
            "threshold_value": threshold,
            "config_env_source": "runtime risk profile",
            "scale": "0-1 probability",
            "missing_value_behavior": "not accepted as routeable confidence",
            "block_behavior": "LOW_CONFIDENCE_BLOCK",
        },
    ]


def write_outputs(output_dir: Path, bundle: Mapping[str, Any]) -> None:
    write_json(output_dir / "paper_shadow_edge_report.json", bundle["edge_report"])
    write_json(output_dir / "paper_shadow_ablation_report.json", bundle["ablation_report"])
    write_json(output_dir / "paper_shadow_symbol_liquidity_report.json", bundle["liquidity_report"])
    write_json(output_dir / "pass2b_release_gate.json", bundle["release_gate"])
    write_json(output_dir / "pass2b_final_release_gate.json", bundle["release_gate"])
    write_json(output_dir / "paper_shadow_lifecycle_diagnostics.json", bundle["lifecycle_diagnostics"])
    write_json(output_dir / "paper_intent_block_trace.json", bundle["paper_intent_block_trace"])
    write_json(output_dir / "confidence_block_trace.json", bundle["confidence_block_trace"])
    write_json(output_dir / "prediction_producer_inventory.json", bundle["prediction_producer_inventory"])
    write_json(output_dir / "pass2e_release_gate.json", bundle["pass2e_release_gate"])
    (output_dir / "paper_shadow_edge_report.md").write_text(render_edge_markdown(bundle["edge_report"], bundle["release_gate"]), encoding="utf-8")
    (output_dir / "paper_shadow_ablation_report.md").write_text(render_ablation_markdown(bundle["ablation_report"]), encoding="utf-8")
    (output_dir / "paper_intent_block_trace.md").write_text(render_block_trace_markdown(bundle["paper_intent_block_trace"]), encoding="utf-8")
    (output_dir / "confidence_block_trace.md").write_text(render_confidence_trace_markdown(bundle["confidence_block_trace"]), encoding="utf-8")
    (output_dir / "prediction_producer_inventory.md").write_text(
        render_prediction_producer_inventory_markdown(bundle["prediction_producer_inventory"]),
        encoding="utf-8",
    )
    with (output_dir / "paper_shadow_trade_sample.jsonl").open("w", encoding="utf-8") as handle:
        for row in bundle["trade_sample"]:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    with (output_dir / "paper_shadow_closed_trades.jsonl").open("w", encoding="utf-8") as handle:
        for row in bundle["closed_trades"]:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    with (output_dir / "paper_shadow_open_trades.jsonl").open("w", encoding="utf-8") as handle:
        for row in bundle["open_trades"]:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def render_prediction_producer_inventory_markdown(report: Mapping[str, Any]) -> str:
    current = report.get("current_evidence", {})
    lines = [
        "# Prediction Producer Inventory",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        "## Current evidence",
        "",
        f"- Prediction records: `{current.get('prediction_records')}`",
        f"- Signals paper records: `{current.get('signals_paper_records')}`",
        f"- Confidence source counts: `{json.dumps(current.get('confidence_source_counts', {}), sort_keys=True)}`",
        "",
        "## Producers",
        "",
        "| File | Function/class | Type | Redis key | Confidence | Routeability use |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("producers", []):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                str(row.get(field, ""))
                for field in (
                    "file_path",
                    "function_or_class",
                    "producer_type",
                    "redis_key_written",
                    "confidence",
                    "paper_intent_consumable",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_edge_markdown(report: Mapping[str, Any], gate: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    lines = [
        "# Paper/Shadow Edge Report",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Sample-size status | `{gate.get('sample_size_status')}` |",
        f"| Edge gate status | `{gate.get('edge_gate_status')}` |",
        f"| Active decisions evaluated | `{report.get('active_decisions_evaluated')}` |",
        f"| Closed trades evaluated | `{report.get('closed_trades_evaluated')}` |",
        f"| Replay reconstruction failures | `{report.get('replay_reconstruction_failures')}` |",
        f"| MTF reconstruction failures | `{report.get('mtf_reconstruction_failures')}` |",
        f"| Dirty accepted decisions | `{report.get('dirty_accepted_decisions')}` |",
        f"| Net PnL after fees/slippage | `{metrics.get('net_pnl_after_fees_slippage')}` |",
        f"| Profit factor after fees/slippage | `{metrics.get('profit_factor_after_fees_slippage')}` |",
        f"| Expectancy after fees/slippage | `{metrics.get('expectancy_per_closed_trade')}` |",
        f"| Max drawdown | `{metrics.get('max_drawdown')}` |",
        "",
        "Open or incomplete trades are not counted as realized closed-trade edge.",
    ]
    return "\n".join(lines) + "\n"


def render_ablation_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Paper/Shadow Ablation Report", "", "| Cohort | Availability | Closed trades | Net PnL |", "|---|---|---:|---:|"]
    for name, row in sorted((report.get("cohorts") or {}).items()):
        lines.append(f"| `{name}` | `{row.get('availability')}` | `{row.get('closed_trade_count')}` | `{row.get('net_pnl_after_fees_slippage')}` |")
    return "\n".join(lines) + "\n"


def render_block_trace_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Paper Intent Block Trace", "", "## Distribution", "", "| Category | Count | Legitimacy | Recommended action |", "|---|---:|---|---|"]
    for category, row in (report.get("distribution") or {}).items():
        lines.append(f"| `{category}` | `{row.get('count')}` | {row.get('legitimacy')} | {row.get('recommended_action')} |")
    lines.extend(["", "## Predictions", "", "| Prediction | Symbol | Action | Final block | Root cause |", "|---|---|---|---|---|"])
    for row in report.get("predictions") or []:
        lines.append(
            f"| `{row.get('prediction_id')}` | `{row.get('symbol')}` | `{row.get('ppo_action')}` | "
            f"`{row.get('exact_final_block_reason')}` | `{row.get('root_cause_category')}` |"
        )
    return "\n".join(lines) + "\n"


def render_confidence_trace_markdown(report: Mapping[str, Any]) -> str:
    distribution = report.get("confidence_distribution") or {}
    lines = [
        "# Confidence Block Trace",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Verdict | `{report.get('verdict')}` |",
        f"| Threshold | `{report.get('threshold')}` |",
        f"| Predictions | `{report.get('prediction_count')}` |",
        f"| Above threshold | `{report.get('predictions_above_threshold')}` |",
        f"| Below threshold | `{report.get('predictions_below_threshold')}` |",
        f"| Placeholder/default confidence | `{report.get('placeholder_or_default_confidence_count')}` |",
        f"| Real model confidence | `{report.get('real_model_confidence_count')}` |",
        f"| Low-confidence blocks | `{report.get('low_confidence_block_count')}` |",
        f"| Min confidence | `{distribution.get('min')}` |",
        f"| Median confidence | `{distribution.get('median')}` |",
        f"| Max confidence | `{distribution.get('max')}` |",
        "",
        "## Predictions",
        "",
        "| Prediction | Symbol | Source | Confidence | Threshold | Real model output |",
        "|---|---|---|---:|---:|---|",
    ]
    for row in report.get("predictions") or []:
        lines.append(
            f"| `{row.get('prediction_id')}` | `{row.get('symbol')}` | `{row.get('prediction_source')}` | "
            f"`{row.get('combined_confidence_score')}` | `{row.get('final_confidence_threshold')}` | "
            f"`{row.get('confidence_from_real_model_output')}` |"
        )
    return "\n".join(lines) + "\n"


def average_numeric(records: Iterable[Mapping[str, Any]], fields: tuple[str, ...]) -> float | None:
    values = [value for record in records if (value := first_numeric(record, fields)) is not None]
    return sum(values) / len(values) if values else None


def timestamp_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number if number > 10_000_000_000 else number * 1000)
    text = str(value).strip()
    if not text:
        return None
    try:
        return timestamp_ms(float(text))
    except ValueError:
        pass
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
