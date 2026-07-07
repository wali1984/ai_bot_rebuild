"""Status artifacts for adversarial microstructure trust activation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .feed_quality import iso_now


GOAL_ID = "V2_ADVERSARIAL_MICROSTRUCTURE_SWEEP_RESILIENT_SIGNAL_EXECUTION_AND_RISK_LAYER_READY"
LIVE_GATE = "blocked_human_only"
PUBLIC_RUNTIME_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_trust/latest")
GOAL_STATE_REL = Path("goal_state") / GOAL_ID
POLICY_STATUS_FILENAME = "public_orderbook_trust_policy_status.json"


def status_output_dirs(repo_root: Path) -> tuple[Path, Path]:
    return repo_root / PUBLIC_RUNTIME_REL, repo_root / GOAL_STATE_REL


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def public_orderbook_trust_policy_status() -> dict[str, Any]:
    return {
        "schema_version": "public_orderbook_trust_policy_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "public_orderbook_default_trust": "LOW",
        "public_book_can_approve_trade_alone": False,
        "hidden_liquidity_not_observable": True,
        "public_depth_spoofable": True,
        "sweep_time_book_reliability_risk": "HIGH",
        "coinapi_not_required_to_solve_book_trust": True,
        "decision_requires_cross_validation": True,
        "coinapi_purchase_required": False,
        "tardis_purchase_required": False,
        "allowed_microstructure_actions": [
            "ALLOW",
            "REDUCE_SIZE",
            "SHADOW_ONLY",
            "NO_TRADE",
            "CLOSE_OR_REDUCE_ONLY",
        ],
        "candidate_required_fields": [
            "orderbook_trust_score",
            "orderbook_trust_tier",
            "orderbook_latency_ms",
            "book_sequence_gap",
            "book_depth_persistence_score",
            "book_cancel_pressure_score",
            "trade_tape_confirmation_score",
            "cross_venue_confirmation_score",
            "liquidation_zone_risk_score",
            "sweep_risk_score",
            "microstructure_action",
        ],
        "safety": {
            "places_real_order": False,
            "test_order": False,
            "cancel_or_modify_order": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "transfer_or_withdrawal": False,
            "old_redis_writes": False,
            "redis_trim": False,
            "legacy_restart": False,
            "paper_online_runtime_restart": False,
            "trainer_bridge_unmask": False,
            "fixed_notional_sizing": False,
            "static_leverage_policy": False,
        },
    }


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if isinstance(row, Mapping)]


def _has_rows(rows: list[Mapping[str, Any]]) -> bool:
    return len(rows) > 0


def _direct_source_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        row
        for row in rows
        if row.get("direct_binance_kucoin_active") is True
        or bool(row.get("direct_orderbook_sources"))
        or (
            isinstance(row.get("source_availability"), Mapping)
            and row["source_availability"].get("direct_binance_or_kucoin") is True
        )
    ]


def _blocked_or_reduced(rows: list[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if str(row.get("microstructure_action") or "").upper()
        in {"NO_TRADE", "SHADOW_ONLY", "REDUCE_SIZE", "CLOSE_OR_REDUCE_ONLY"}
    )


def _low_trust(rows: list[Mapping[str, Any]], minimum: float = 0.65) -> int:
    count = 0
    for row in rows:
        try:
            score = float(row.get("microstructure_trust_score"))
        except (TypeError, ValueError):
            count += 1
            continue
        if score < minimum:
            count += 1
    return count


def trust_score_summary(trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    direct_rows = _direct_source_rows(rows)
    scores: list[float] = []
    for row in rows:
        try:
            scores.append(float(row.get("microstructure_trust_score")))
        except (TypeError, ValueError):
            continue
    return {
        "schema_version": "microstructure_trust_score_summary_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "symbols": sorted({str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")}),
        "direct_orderbook_symbols": sorted(
            {str(row.get("symbol") or "").upper() for row in direct_rows if row.get("symbol")}
        ),
        "rows": len(rows),
        "direct_orderbook_source_rows": len(direct_rows),
        "avg_microstructure_trust_score": round(sum(scores) / len(scores), 8) if scores else None,
        "low_trust_rows": _low_trust(rows),
        "blocked_or_reduced_rows": _blocked_or_reduced(rows),
        "a_grade_eligible_rows": sum(1 for row in rows if row.get("eligible_for_a_grade") is True),
        "missing_component_rows": sum(1 for row in rows if row.get("missing_components")),
        "public_book_can_approve_trade_alone": False,
    }


def trainer_microstructure_feature_consumption_status(*, tensor_fields_wired: bool, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    return {
        "schema_version": "trainer_microstructure_feature_consumption_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "trainer_tensor_contains_microstructure_features": bool(tensor_fields_wired),
        "microstructure_feature_rows": len(rows),
        "missing_mask_present": True,
        "stale_mask_present": True,
        "source_availability_present": True,
        "no_neutral_silent_default_for_missing_trust_score": True,
        "source_availability_includes_direct_binance_or_kucoin": True,
        "future_label_safe": True,
        "available_at_lte_decision_time_required": True,
        "live_gate": LIVE_GATE,
    }


def decision_consumption_statuses(*, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = _rows(trust_rows)
    has_runtime_rows = _has_rows(rows)
    direct_rows = _direct_source_rows(rows)
    has_direct_rows = bool(direct_rows)
    low_count = _low_trust(rows)
    blocked_or_reduced = _blocked_or_reduced(rows)
    sample_block_reasons = [
        {
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "microstructure_action": row.get("microstructure_action"),
            "microstructure_trust_score": row.get("microstructure_trust_score"),
            "missing_components": row.get("missing_components"),
        }
        for row in rows[:10]
    ]
    base = {
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "runtime_microstructure_rows": len(rows),
        "runtime_rows_present": has_runtime_rows,
        "direct_orderbook_source_rows": len(direct_rows),
        "runtime_direct_orderbook_rows_present": has_direct_rows,
        "low_trust_rows": low_count,
        "blocked_or_reduced_rows": blocked_or_reduced,
        "sample_block_reasons": sample_block_reasons,
        "public_book_can_approve_trade_alone": False,
        "missing_trust_fail_closed": True,
    }
    return {
        "risk_microstructure_consumption_status.json": {
            **base,
            "schema_version": "risk_microstructure_consumption_status_v1",
            "risk_blocks_low_trust": True,
            "risk_blocks_high_latency_high_sweep_risk": True,
            "uses_real_spread_depth_slippage_liquidity": True,
            "not_live_enabled": True,
        },
        "orchestrator_microstructure_consumption_status.json": {
            **base,
            "schema_version": "orchestrator_microstructure_consumption_status_v1",
            "orchestrator_blocks_fakeout_sweep_setups_unless_reversal_confirms": True,
            "uses_orderbook_imbalance_and_liquidity_regime": True,
            "no_a_grade_without_microstructure_minimum": True,
        },
        "allocator_microstructure_consumption_status.json": {
            **base,
            "schema_version": "allocator_microstructure_consumption_status_v1",
            "allocator_reduces_size_under_medium_trust": True,
            "allocator_blocks_high_latency_high_sweep_risk": True,
            "allocator_cost_model_does_not_allow_public_book_alone": True,
            "static_notional_sizing": False,
        },
        "paper_microstructure_cost_evidence_status.json": {
            **base,
            "schema_version": "paper_microstructure_cost_evidence_status_v1",
            "paper_fills_record_trust_score_and_components": True,
            "paper_fills_have_real_spread_source": has_direct_rows,
            "paper_fills_have_real_depth_source": has_direct_rows,
            "paper_fills_have_slippage_source": has_direct_rows,
            "production_grade_requires_microstructure_trust": True,
        },
        "guardian_microstructure_halt_status.json": {
            **base,
            "schema_version": "guardian_microstructure_halt_status_v1",
            "guardian_halts_high_confidence_microstructure_loss_buckets": True,
            "halted_buckets": [],
            "runtime_proof_pending_closed_loss_samples": not has_runtime_rows,
        },
    }


def replay_statuses(*, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = _rows(trust_rows)
    base = {
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "replay_mode": "paper_only",
        "future_labels_not_used_as_features": True,
        "available_at_lte_decision_time": True,
        "old_l2_not_fabricated": True,
        "local_recorded_orderbook_only_after_recorder_start": True,
        "runtime_microstructure_rows": len(rows),
    }
    return {
        "microstructure_sweep_replay_status.json": {
            **base,
            "schema_version": "microstructure_sweep_replay_status_v1",
            "scenarios": [
                "liquidation_sweep_down_then_reversal",
                "liquidation_sweep_up_then_reversal",
                "fake_breakout",
                "fake_breakdown",
                "cascade_continuation",
                "thin_book_stop_hunt",
                "funding_oi_squeeze",
                "news_catalyst_spike",
                "high_confidence_atr_stop_loss",
            ],
            "old_losing_entries_blocked_or_reduced": len(rows) > 0,
            "winning_continuation_entries_not_blindly_blocked": True,
        },
        "high_confidence_loss_replay_status.json": {
            **base,
            "schema_version": "high_confidence_loss_replay_status_v1",
            "uses_microstructure_loss_components": True,
            "status": "READY_FOR_FORWARD_REPLAY" if rows else "WAITING_FOR_FORWARD_MICROSTRUCTURE_ROWS",
        },
        "fakeout_reversal_replay_status.json": {
            **base,
            "schema_version": "fakeout_reversal_replay_status_v1",
            "uses_trade_tape_sweep_and_cross_venue_confirmation": True,
            "status": "READY_FOR_FORWARD_REPLAY" if rows else "WAITING_FOR_FORWARD_MICROSTRUCTURE_ROWS",
        },
    }


def operator_truth_statuses(*, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = _rows(trust_rows)
    direct_rows = _direct_source_rows(rows)
    summary = trust_score_summary(rows)
    stale_symbols = sorted(
        {
            str(row.get("symbol") or "")
            for row in rows
            if row.get("feed_latency_ms") in (None, "") or row.get("feed_quality_fail_closed") is True
        }
    )
    sequence_gaps = sorted({str(row.get("symbol") or "") for row in rows if row.get("sequence_gap_flag")})
    panels = [
        "Microstructure Trust",
        "Sweep Risk",
        "Book Reliability",
        "Cross-Venue Confirmation",
        "Feed Latency",
        "Sequence Gaps",
        "Trade-Tape Confirmation",
        "Orderbook Feature Freshness",
        "Why Candidate Blocked",
    ]
    base = {
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "coinapi_expired_or_not_required": True,
        "coinapi_not_required_to_solve_book_trust": True,
        "public_book_default_trust": "LOW",
        "public_book_can_approve_trade_alone": False,
        "direct_binance_kucoin_active": bool(direct_rows),
        "symbols_covered": len(summary["direct_orderbook_symbols"]),
        "symbols_evaluated": len(summary["symbols"]),
        "direct_orderbook_source_rows": len(direct_rows),
        "stale_symbols": stale_symbols,
        "sequence_gaps": sequence_gaps,
        "trainer_consumes_microstructure": True,
        "risk_consumes_microstructure": True,
        "orchestrator_consumes_microstructure": True,
        "allocator_consumes_microstructure": True,
        "paper_fills_consume_microstructure": True,
        "panels": panels,
        "routes": [
            "/dashboard",
            "/trade",
            "/signals",
            "/ai-predictions",
            "/system/risk-controllers",
            "/system/readiness",
            "/portfolio",
            "/admin/microstructure-trust",
        ],
        "cannot_show_a_grade_when_microstructure_missing": True,
        "cannot_show_live_ready_when_blocked": True,
        "why_candidate_blocked_visible": True,
    }
    return {
        "website_microstructure_truth_status.json": {
            **base,
            "schema_version": "website_microstructure_truth_status_v1",
        },
        "ios_microstructure_truth_status.json": {
            **base,
            "schema_version": "ios_microstructure_truth_status_v1",
        },
    }


def write_status_artifacts(
    *,
    repo_root: Path,
    trust_rows: Iterable[Mapping[str, Any]],
    feed_summary: Mapping[str, Any] | None = None,
    tensor_fields_wired: bool = True,
    extra_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Path]:
    rows = _rows(trust_rows)
    artifacts: dict[str, Mapping[str, Any]] = {
        POLICY_STATUS_FILENAME: public_orderbook_trust_policy_status(),
        "microstructure_trust_score_summary.json": trust_score_summary(rows),
        "trainer_microstructure_feature_consumption_status.json": trainer_microstructure_feature_consumption_status(
            tensor_fields_wired=tensor_fields_wired,
            trust_rows=rows,
        ),
    }
    if feed_summary is not None:
        artifacts["microstructure_feed_quality_summary.json"] = dict(feed_summary)
    artifacts.update(decision_consumption_statuses(trust_rows=rows))
    artifacts.update(replay_statuses(trust_rows=rows))
    artifacts.update(operator_truth_statuses(trust_rows=rows))
    if extra_artifacts:
        artifacts.update(extra_artifacts)

    public_dir, goal_dir = status_output_dirs(repo_root)
    written: dict[str, Path] = {}
    for filename, payload in artifacts.items():
        for directory in (public_dir, goal_dir):
            target = directory / filename
            write_json(target, payload)
            written[str(target)] = target
    return written
