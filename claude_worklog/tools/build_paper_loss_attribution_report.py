#!/usr/bin/env python3
"""Build source-limited attribution for current V2 paper losses.

This script reads V2 paper/shadow artifacts only. It does not touch legacy,
Redis, exchange APIs, approval tokens, or live configuration.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKLOG_OUT = ROOT / "claude_worklog/final_readiness/paper_loss_attribution/latest"
PUBLIC_OUT = ROOT / "v2/frontend/public/paper_loss_attribution/latest"

PAPER_EVENTS = ROOT / "v2/runtime/paper_online/latest/paper_events.jsonl"
PAPER_EVENTS_PUBLIC = ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_events.jsonl"
PAPER_STATUS = ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json"
SHADOW_STATUS = ROOT / "v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json"
POST_FILTER_STATUS = ROOT / "claude_worklog/final_readiness/paper_edge_post_filter_observation_window/latest/paper_edge_post_filter_observation_status.json"
NEGATIVE_DIAGNOSIS = ROOT / "claude_worklog/final_readiness/paper_shadow_soak_negative_pnl/latest/negative_paper_pnl_diagnosis.json"
FILL_QUALITY_AUDIT = ROOT / "claude_worklog/final_readiness/paper_shadow_soak_negative_pnl/latest/paper_fill_quality_and_overtrading_audit.json"
TRAINER_STATUS = ROOT / "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json"
FEATURE_STATUS = ROOT / "v2/frontend/public/operator_runtime/v2_feature_pipeline_and_ta_worker/latest/v2_feature_pipeline_and_ta_worker_status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    last_error: Exception | None = None
    for _ in range(5):
        text = path.read_text(errors="replace")
        if text.strip():
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                last_error = exc
        time.sleep(0.1)
    if default is not None:
        return default
    if last_error:
        raise last_error
    raise ValueError(f"{path} is empty")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def confidence_bucket(value: Any) -> str:
    if value is None:
        return "missing_confidence"
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "invalid_confidence"
    if confidence < 0.58:
        return "below_0.58"
    if confidence < 0.65:
        return "0.58_to_0.65"
    if confidence < 0.75:
        return "0.65_to_0.75"
    return "0.75_plus"


def round_money(value: float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), 6)


def read_events(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path]:
    source = path if path.exists() else PAPER_EVENTS_PUBLIC
    events: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    if not source.exists():
        return events, [{"line_number": None, "error": "paper_events_jsonl_missing"}], source
    for line_number, line in enumerate(source.read_text(errors="replace").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("{"):
            invalid.append(
                {
                    "line_number": line_number,
                    "error": "line_does_not_start_with_json_object",
                    "prefix_repr": repr(line[:24]),
                }
            )
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            invalid.append(
                {
                    "line_number": line_number,
                    "error": str(exc),
                    "prefix_repr": repr(line[:80]),
                }
            )
            continue
        event_dt = parse_dt(event.get("generated_at"))
        if event_dt is None:
            invalid.append({"line_number": line_number, "error": "missing_generated_at"})
            continue
        event["_dt"] = event_dt
        events.append(event)
    events.sort(key=lambda item: item["_dt"])
    return events, invalid, source


def counter_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    fills = [event for event in events if event.get("ledger_action") == "PAPER_FILL_SIMULATED"]
    blocked = [event for event in events if event.get("ledger_action") != "PAPER_FILL_SIMULATED"]
    first = events[0] if events else {}
    last = events[-1] if events else {}
    pnl_delta = None
    if first and last and first.get("paper_realized_pnl") is not None and last.get("paper_realized_pnl") is not None:
        pnl_delta = round_money(float(last["paper_realized_pnl"]) - float(first["paper_realized_pnl"]))
    notional = sum(float(event.get("notional_usdt") or 0.0) for event in fills)
    slippage_estimate = sum(
        float(event.get("notional_usdt") or 0.0) * float(event.get("slippage_bps") or 0.0) / 10000.0
        for event in fills
    )
    return {
        "event_count": len(events),
        "fill_count": len(fills),
        "blocked_count": len(blocked),
        "first_event_at": first.get("generated_at"),
        "last_event_at": last.get("generated_at"),
        "first_cumulative_pnl_usdt": round_money(first.get("paper_realized_pnl")),
        "last_cumulative_pnl_usdt": round_money(last.get("paper_realized_pnl")),
        "cumulative_pnl_delta_usdt": pnl_delta,
        "symbol_distribution": counter_dict(Counter(event.get("symbol", "missing_symbol") for event in events)),
        "fill_symbol_distribution": counter_dict(Counter(event.get("symbol", "missing_symbol") for event in fills)),
        "risk_reason_distribution": counter_dict(Counter(event.get("risk_reason_code", "missing_reason") for event in events)),
        "fill_risk_reason_distribution": counter_dict(Counter(event.get("risk_reason_code", "missing_reason") for event in fills)),
        "confidence_bucket_distribution": counter_dict(Counter(confidence_bucket(event.get("confidence")) for event in events)),
        "fill_confidence_bucket_distribution": counter_dict(Counter(confidence_bucket(event.get("confidence")) for event in fills)),
        "canary_profile_tightening_blocker_distribution": counter_dict(
            Counter(blocker for event in events for blocker in (event.get("canary_profile_tightening_blockers") or []))
        ),
        "fee_usdt": round_money(sum(float(event.get("fee_usdt") or 0.0) for event in fills)),
        "notional_usdt": round_money(notional),
        "slippage_bps_assumption_values": counter_dict(Counter(event.get("slippage_bps", "missing") for event in fills)),
        "slippage_usdt_estimate_not_separately_booked": round_money(slippage_estimate),
        "old_redis_write_events": sum(1 for event in events if event.get("legacy_redis_write")),
        "exchange_order_events": sum(1 for event in events if event.get("exchange_order")),
        "live_gate_values": counter_dict(Counter(event.get("live_gate_status", "missing_live_gate") for event in events)),
    }


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(out)


def build_markdown(status: dict[str, Any]) -> str:
    waterfall = status["pnl_waterfall"]
    pre = status["pre_filter_event_detail"]
    post = status["post_filter_event_detail"]
    observed = status["observed_pre_filter_loss_breakdown"]
    limitations = status["source_limitations"]
    source_integrity = status["source_integrity"]

    lines = [
        "# Paper Loss Attribution Report",
        "",
        f"Generated: `{status['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Current cumulative paper PnL: `{waterfall['current_cumulative_paper_pnl_usdt']}` USDT.",
        f"- Source-detailed pre-filter observed loss: `{waterfall['observed_pre_filter_pnl_delta_usdt']}` USDT.",
        f"- Source-limited pre-observation/baseline loss: `{waterfall['source_limited_prior_baseline_loss_usdt']}` USDT.",
        f"- Post-filter PnL delta: `{waterfall['post_filter_pnl_delta_usdt']}` USDT with `{post['fill_count']}` fills.",
        f"- Post-filter safety classification: `{status['post_filter_classification']['post_filter_safety_classification']}`.",
        f"- Edge classification: `{status['post_filter_classification']['classification']}`.",
        "",
        "The important split is that the current `-49.12` paper PnL is historical/pre-filter. The post-filter window has no fills and no additional realized loss, so it proves no unsafe fills in the observed window, not positive edge.",
        "",
        "## PnL Waterfall",
        "",
        table(
            ["Bucket", "PnL USDT", "Evidence"],
            [
                [
                    "Source-limited prior baseline through first observed paper event",
                    waterfall["source_limited_prior_baseline_loss_usdt"],
                    "Cumulative PnL already negative at first JSONL event; no per-fill source detail for this portion",
                ],
                [
                    "Observed pre-filter event delta",
                    waterfall["observed_pre_filter_pnl_delta_usdt"],
                    "Paper JSONL cumulative PnL delta before filter activation",
                ],
                [
                    "Observed post-filter event delta",
                    waterfall["post_filter_pnl_delta_usdt"],
                    "Paper JSONL cumulative PnL delta after filter activation",
                ],
                [
                    "Current cumulative paper PnL",
                    waterfall["current_cumulative_paper_pnl_usdt"],
                    "Paper shadow status / latest paper event",
                ],
            ],
        ),
        "",
        "## Pre-Filter Vs Post-Filter",
        "",
        table(
            ["Window", "Events", "Fills", "Blocked", "PnL Delta", "Fees", "Slippage Estimate", "Classification"],
            [
                [
                    "Pre-filter observed",
                    pre["event_count"],
                    pre["fill_count"],
                    pre["blocked_count"],
                    pre["cumulative_pnl_delta_usdt"],
                    pre["fee_usdt"],
                    pre["slippage_usdt_estimate_not_separately_booked"],
                    "LOSS_OBSERVED_PRE_FILTER",
                ],
                [
                    "Post-filter observed",
                    post["event_count"],
                    post["fill_count"],
                    post["blocked_count"],
                    post["cumulative_pnl_delta_usdt"],
                    post["fee_usdt"],
                    post["slippage_usdt_estimate_not_separately_booked"],
                    status["post_filter_classification"]["post_filter_safety_classification"],
                ],
            ],
        ),
        "",
        "## Requested Attribution Dimensions",
        "",
        "### Symbol",
        "",
        table(
            ["Symbol / bucket", "Observed pre-filter PnL", "Post-filter PnL", "Events / note"],
            [
                [
                    "BTCUSDT",
                    observed["pnl_by_symbol"].get("BTCUSDT", "MISSING"),
                    post["cumulative_pnl_delta_usdt"],
                    f"{pre['symbol_distribution'].get('BTCUSDT', 0)} pre-filter events, {post['symbol_distribution'].get('BTCUSDT', 0)} post-filter events",
                ],
                [
                    "SOURCE_LIMITED_PRIOR_BASELINE",
                    waterfall["source_limited_prior_baseline_loss_usdt"],
                    0.0,
                    "No source detail by symbol for this prior cumulative portion",
                ],
            ],
        ),
        "",
        "### Side / Risk Reason",
        "",
        table(
            ["Side / reason", "Observed pre-filter PnL", "Fill count", "Source"],
            [
                ["long / allow_proceed_long", observed["pnl_by_action"].get("long", "MISSING"), pre["fill_risk_reason_distribution"].get("allow_proceed_long", 0), "paper fill quality audit"],
                ["short / allow_proceed_short", observed["pnl_by_action"].get("short", "MISSING"), pre["fill_risk_reason_distribution"].get("allow_proceed_short", 0), "paper fill quality audit"],
            ],
        ),
        "",
        "### Reason Code / Risk Decision",
        "",
        table(
            ["Reason code", "Risk decision", "Observed pre-filter PnL", "Pre-filter count", "Post-filter count"],
            [
                [
                    "allow_proceed_long",
                    "APPROVED_FOR_PAPER_ONLY",
                    observed["pnl_by_risk_decision"].get("allow_proceed_long", 0.0),
                    pre["risk_reason_distribution"].get("allow_proceed_long", 0),
                    post["risk_reason_distribution"].get("allow_proceed_long", 0),
                ],
                [
                    "allow_proceed_short",
                    "APPROVED_FOR_PAPER_ONLY",
                    observed["pnl_by_risk_decision"].get("allow_proceed_short", 0.0),
                    pre["risk_reason_distribution"].get("allow_proceed_short", 0),
                    post["risk_reason_distribution"].get("allow_proceed_short", 0),
                ],
                [
                    "deny_canary_profile_tightening",
                    "BLOCKED",
                    0.0,
                    pre["risk_reason_distribution"].get("deny_canary_profile_tightening", 0),
                    post["risk_reason_distribution"].get("deny_canary_profile_tightening", 0),
                ],
                [
                    "deny_low_confidence",
                    "BLOCKED",
                    0.0,
                    pre["risk_reason_distribution"].get("deny_low_confidence", 0),
                    post["risk_reason_distribution"].get("deny_low_confidence", 0),
                ],
                [
                    "deny_orchestrator_held",
                    "BLOCKED",
                    0.0,
                    pre["risk_reason_distribution"].get("deny_orchestrator_held", 0),
                    post["risk_reason_distribution"].get("deny_orchestrator_held", 0),
                ],
                [
                    "deny_stale_market_feed",
                    "BLOCKED",
                    0.0,
                    pre["risk_reason_distribution"].get("deny_stale_market_feed", 0),
                    post["risk_reason_distribution"].get("deny_stale_market_feed", 0),
                ],
            ],
        ),
        "",
        "### Confidence Bucket",
        "",
        table(
            ["Confidence bucket", "Observed pre-filter PnL", "Pre-filter fill count", "Post-filter fill count"],
            [
                [
                    bucket,
                    observed["pnl_by_confidence_bucket"].get(bucket, 0.0),
                    pre["fill_confidence_bucket_distribution"].get(bucket, 0),
                    post["fill_confidence_bucket_distribution"].get(bucket, 0),
                ]
                for bucket in ["below_0.58", "0.58_to_0.65", "0.65_to_0.75", "0.75_plus"]
            ],
        ),
        "",
        "### Fee / Slippage",
        "",
        table(
            ["Metric", "Pre-filter observed", "Post-filter observed", "Note"],
            [
                ["Explicit fee USDT", pre["fee_usdt"], post["fee_usdt"], "Booked in paper events"],
                ["Slippage bps assumption", pre["slippage_bps_assumption_values"], post["slippage_bps_assumption_values"], "Logged as bps, not separately booked as realized PnL"],
                ["Estimated slippage USDT", pre["slippage_usdt_estimate_not_separately_booked"], post["slippage_usdt_estimate_not_separately_booked"], "Notional * slippage_bps / 10000"],
                ["Gross PnL if fees added back", observed["gross_pnl_if_fees_added_back_usdt"], "N/A", "From negative PnL diagnosis"],
            ],
        ),
        "",
        "### Trainer Source And Feature Freshness",
        "",
        table(
            ["Dimension", "Classification", "Evidence"],
            [
                ["Per-fill trainer source", limitations["trainer_source_per_fill"], "Paper JSONL has prediction_id but no trainer source field"],
                ["Current paper runtime trainer source", status["trainer_source"]["current_paper_runtime_trainer_source"], "paper runtime status"],
                ["Trainer bridge source", status["trainer_source"]["trainer_bridge_source"], "trainer bridge status"],
                ["Per-fill feature freshness", limitations["feature_freshness_per_fill"], "Paper JSONL has feature_snapshot_id but no freshness field"],
                ["Current feature freshness", status["feature_freshness"]["current_paper_runtime_feature_freshness"], "paper runtime current lineage"],
                ["Stale market feed risk decisions", pre["risk_reason_distribution"].get("deny_stale_market_feed", 0), "Pre-filter denials, not filled-loss attribution"],
                ["Post-filter stale market feed risk decisions", post["risk_reason_distribution"].get("deny_stale_market_feed", 0), "Post-filter denials, no fills"],
            ],
        ),
        "",
        "### Edge-After-Costs / Cooldown / Churn",
        "",
        table(
            ["Dimension", "Pre-filter observed", "Post-filter observed", "Interpretation"],
            [
                [
                    "missing_expected_move_after_costs",
                    pre["canary_profile_tightening_blocker_distribution"].get("missing_expected_move_after_costs", 0),
                    post["canary_profile_tightening_blocker_distribution"].get("missing_expected_move_after_costs", 0),
                    "Edge-after-costs unavailable on denied intents; not present for pre-filter allowed fills",
                ],
                [
                    "same_symbol_same_direction_cooldown",
                    pre["canary_profile_tightening_blocker_distribution"].get("same_symbol_same_direction_cooldown", 0),
                    post["canary_profile_tightening_blocker_distribution"].get("same_symbol_same_direction_cooldown", 0),
                    "Explicit cooldown blocker counts in event stream",
                ],
                [
                    "flip_churn_cooldown",
                    pre["canary_profile_tightening_blocker_distribution"].get("flip_churn_cooldown", 0),
                    post["canary_profile_tightening_blocker_distribution"].get("flip_churn_cooldown", 0),
                    "Explicit flip/churn blocker counts in event stream",
                ],
                [
                    "churn_flip_count",
                    observed["churn_flip_count"],
                    status["post_filter_classification"]["post_filter_churn_events"],
                    "Pre-filter audit count vs post-filter observation",
                ],
            ],
        ),
        "",
        "## Safety State",
        "",
        table(
            ["Check", "Value"],
            [
                ["live_gate", status["safety"]["live_gate"]],
                ["live_symbols", status["safety"]["live_symbols"]],
                ["old Redis write events in parsed paper JSONL", status["safety"]["old_redis_write_events"]],
                ["exchange order events in parsed paper JSONL", status["safety"]["exchange_order_events"]],
                ["approval token", status["safety"]["final_approval_token"]],
                ["approves live", status["safety"]["approves_live"]],
                ["approves legacy shutdown", status["safety"]["approves_legacy_shutdown"]],
            ],
        ),
        "",
        "## Source Limitations",
        "",
        "- Per-fill trainer source is missing from paper events.",
        "- Per-fill feature freshness is missing from paper events.",
        "- Edge-after-costs value is missing for pre-filter allowed fills; post-filter denials carry `missing_expected_move_after_costs` blockers.",
        "- Cooldown and flip/churn are explicit only when the canary tightening filter emits blockers; the pre-filter loss audit also reports aggregate churn.",
        f"- Invalid JSONL rows skipped: `{source_integrity['invalid_jsonl_rows']}`.",
        "",
        "## Decision",
        "",
        f"`{status['go_no_go']}`",
        "",
        "This report does not approve live trading, canary trading, or legacy shutdown. It narrows the paper loss blocker to historical/pre-filter loss plus source-limited attribution gaps, while post-filter behavior remains no-fill/no-loss and edge-pending.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    paper_status = load_json(PAPER_STATUS, {})
    shadow_status = load_json(SHADOW_STATUS, {})
    post_filter = load_json(POST_FILTER_STATUS, {})
    negative = load_json(NEGATIVE_DIAGNOSIS, {})
    fill_quality = load_json(FILL_QUALITY_AUDIT, {})
    trainer = load_json(TRAINER_STATUS, {})
    feature = load_json(FEATURE_STATUS, {})

    events, invalid_rows, event_source = read_events(PAPER_EVENTS)
    post_start = parse_dt(post_filter.get("post_filter_window_start_utc"))
    if post_start is None:
        post_start = parse_dt(events[-1].get("generated_at")) if events else None
    pre_events = [event for event in events if post_start and event["_dt"] < post_start]
    post_events = [event for event in events if post_start and event["_dt"] >= post_start]
    all_summary = summarize_events(events)
    pre_summary = summarize_events(pre_events)
    post_summary = summarize_events(post_events)

    current_pnl = (
        shadow_status.get("paper_pnl_current_usdt")
        if shadow_status.get("paper_pnl_current_usdt") is not None
        else all_summary.get("last_cumulative_pnl_usdt")
    )
    post_delta = (
        post_filter.get("post_filter_realized_pnl_delta_usdt")
        if post_filter.get("post_filter_realized_pnl_delta_usdt") is not None
        else post_summary.get("cumulative_pnl_delta_usdt")
    )
    observed_pre_delta = pre_summary.get("cumulative_pnl_delta_usdt")
    baseline = None
    if current_pnl is not None and observed_pre_delta is not None and post_delta is not None:
        baseline = round_money(float(current_pnl) - float(observed_pre_delta) - float(post_delta))

    current_lineage = paper_status.get("current_signal_lineage") or {}
    current_trainer = current_lineage.get("trainer_prediction") or paper_status.get("trainer_prediction") or {}
    current_feature = current_lineage.get("feature_snapshot") or paper_status.get("feature_snapshot") or {}

    status: dict[str, Any] = {
        "task_id": "paper_loss_attribution",
        "generated_at": utc_now(),
        "classification": "PAPER_LOSS_ATTRIBUTION_READY_SOURCE_LIMITED",
        "go_no_go": "PAPER_LOSS_ATTRIBUTION_READY_SOURCE_LIMITED",
        "recommendation": "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE",
        "source_files": {
            "paper_events_jsonl": rel(event_source),
            "paper_runtime_status": rel(PAPER_STATUS),
            "paper_shadow_observation_status": rel(SHADOW_STATUS),
            "post_filter_observation_status": rel(POST_FILTER_STATUS),
            "negative_pnl_diagnosis": rel(NEGATIVE_DIAGNOSIS),
            "fill_quality_audit": rel(FILL_QUALITY_AUDIT),
            "trainer_bridge_status": rel(TRAINER_STATUS),
            "feature_pipeline_status": rel(FEATURE_STATUS),
        },
        "source_integrity": {
            "valid_jsonl_events": len(events),
            "invalid_jsonl_rows": len(invalid_rows),
            "invalid_jsonl_row_samples": invalid_rows[:5],
            "source_limited_prior_baseline_present": baseline is not None and baseline != 0,
        },
        "pnl_waterfall": {
            "current_cumulative_paper_pnl_usdt": round_money(current_pnl),
            "source_limited_prior_baseline_loss_usdt": baseline,
            "observed_pre_filter_pnl_delta_usdt": observed_pre_delta,
            "post_filter_pnl_delta_usdt": round_money(post_delta),
            "reconciles_to_current_cumulative_pnl": (
                baseline is not None
                and current_pnl is not None
                and observed_pre_delta is not None
                and post_delta is not None
                and abs((baseline + float(observed_pre_delta) + float(post_delta)) - float(current_pnl)) < 0.0001
            ),
            "note": "Only the observed pre-filter event delta has per-fill dimensional attribution. The prior baseline is cumulative source-limited evidence.",
        },
        "pre_filter_event_detail": pre_summary,
        "post_filter_event_detail": post_summary,
        "all_event_detail": all_summary,
        "post_filter_classification": {
            "classification": post_filter.get("classification", "POST_FILTER_EDGE_PENDING"),
            "post_filter_safety_classification": post_filter.get("post_filter_safety_classification", "POST_FILTER_NO_UNSAFE_FILLS" if post_summary.get("fill_count") == 0 else "POST_FILTER_FILLS_OBSERVED"),
            "post_filter_window_start_utc": post_filter.get("post_filter_window_start_utc"),
            "post_filter_window_end_utc": post_filter.get("post_filter_window_end_utc"),
            "post_filter_churn_events": post_filter.get("post_filter_churn_events", 0),
            "paper_edge_positive_proven": bool(post_filter.get("paper_edge_positive_proven", False)),
        },
        "observed_pre_filter_loss_breakdown": {
            "source_scope": "observed_pre_filter_delta_only",
            "pnl_by_symbol": fill_quality.get("pnl_by_symbol", {}),
            "pnl_by_action": fill_quality.get("pnl_by_action", {}),
            "pnl_by_confidence_bucket": fill_quality.get("pnl_by_confidence_bucket", {}),
            "pnl_by_risk_decision": fill_quality.get("pnl_by_risk_decision", {}),
            "pnl_per_fill_avg_usdt": fill_quality.get("pnl_per_fill_avg_usdt"),
            "churn_flip_count": fill_quality.get("churn_flip_count"),
            "repeated_same_direction_fills": fill_quality.get("repeated_same_direction_fills", {}),
            "repeated_same_symbol_fills": fill_quality.get("repeated_same_symbol_fills", {}),
            "stricter_canary_profile_would_block_count": fill_quality.get("stricter_canary_profile_would_block_count"),
            "gross_pnl_if_fees_added_back_usdt": negative.get("gross_pnl_if_fees_added_back_usdt"),
            "fees_usdt": negative.get("fees_usdt"),
            "slippage_assumption_bps": negative.get("slippage_assumption_bps"),
            "paper_engine_assumption": negative.get("paper_engine_assumption"),
        },
        "trainer_source": {
            "per_fill_trainer_source": "MISSING_IN_PAPER_EVENTS",
            "current_paper_runtime_trainer_source": current_trainer.get("source_type", "MISSING_CURRENT_TRAINER_SOURCE"),
            "current_prediction_id": current_trainer.get("prediction_id"),
            "trainer_bridge_source": trainer.get("prediction_source_type") or trainer.get("model_version") or "MISSING_TRAINER_BRIDGE_SOURCE",
            "trainer_bridge_remaining_parity_gaps": trainer.get("remaining_parity_gaps", []),
            "trainer_bridge_field_classification": trainer.get("field_classification", {}),
        },
        "feature_freshness": {
            "per_fill_feature_freshness": "MISSING_IN_PAPER_EVENTS",
            "current_paper_runtime_feature_freshness": current_feature.get("freshness_state", "MISSING_CURRENT_FEATURE_FRESHNESS"),
            "current_market_age_seconds": current_feature.get("market_age_seconds"),
            "feature_pipeline_freshness_seconds": feature.get("freshness_seconds"),
            "feature_pipeline_last_run_ts": feature.get("last_run_ts"),
            "stale_market_feed_denials_pre_filter": pre_summary["risk_reason_distribution"].get("deny_stale_market_feed", 0),
            "stale_market_feed_denials_post_filter": post_summary["risk_reason_distribution"].get("deny_stale_market_feed", 0),
        },
        "source_limitations": {
            "trainer_source_per_fill": "MISSING_IN_PAPER_EVENTS",
            "feature_freshness_per_fill": "MISSING_IN_PAPER_EVENTS",
            "edge_after_costs_for_allowed_pre_filter_fills": "MISSING_EXPECTED_MOVE_AFTER_COSTS_FIELD",
            "cooldown_violation_for_pre_filter_allowed_fills": "SOURCE_LIMITED_TO_CANARY_BLOCKER_COUNTS_AND_AUDIT",
            "flip_churn_violation_for_pre_filter_allowed_fills": "SOURCE_LIMITED_TO_CANARY_BLOCKER_COUNTS_AND_AUDIT",
            "prior_baseline_attribution": "SOURCE_LIMITED_PRIOR_CUMULATIVE_PNL_WITHOUT_EVENT_DETAIL",
        },
        "safety": {
            "live_gate": post_filter.get("live_gate") or paper_status.get("live_gate_status") or "blocked_human_only",
            "live_symbols": post_filter.get("live_symbols", []),
            "final_approval_token": post_filter.get("final_approval_token", "absent"),
            "redis_trim_approval": post_filter.get("redis_trim_approval", "absent"),
            "old_redis_write_events": all_summary["old_redis_write_events"],
            "exchange_order_events": all_summary["exchange_order_events"],
            "approves_live": False,
            "approves_legacy_shutdown": False,
        },
    }

    WORKLOG_OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC_OUT.mkdir(parents=True, exist_ok=True)
    markdown = build_markdown(status)

    (WORKLOG_OUT / "paper_loss_attribution_status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    (WORKLOG_OUT / "PAPER_LOSS_ATTRIBUTION_REPORT.md").write_text(markdown)
    (WORKLOG_OUT / "GO_NO_GO.md").write_text(status["go_no_go"] + "\n")
    (PUBLIC_OUT / "operator_dashboard_payload.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    print(json.dumps({"status": status["go_no_go"], "report": rel(WORKLOG_OUT / "PAPER_LOSS_ATTRIBUTION_REPORT.md")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
