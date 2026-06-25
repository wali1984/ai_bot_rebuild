"""Append-only evidence producers for the live-grade reverify gate.

This module intentionally lives outside the frozen selector/status publisher
manifest. It imports the frozen selector helpers as read-only code, writes local
evidence artifacts only, and never submits orders, mutates exchange leverage, or
writes Redis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_adaptive_capital_productivity_status as status_module


SCHEMA_VERSION = "v2_out_of_sample_reverify_evidence_producer_v1"
EXPECTED_SELECTOR_POLICY_FINGERPRINT = (
    "c4b8fb1ed12aabcb87224723f1758563eefff10de90288be09866d2bf3fa74b5"
)
REPLAY_EXPECTANCY_AFTER_COST_BPS = 41.76153327
MIN_REALTIME_EXPECTANCY_AFTER_COST_BPS = 20.88076664

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_adaptive_capital_productivity/latest"
)
DEFAULT_BUCKET_MATRIX_PATH = DEFAULT_OUT_DIR / "a_grade_bucket_performance_matrix.json"
DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH = (
    DEFAULT_OUT_DIR / "accelerated_counterfactual_replay_status.json"
)
DEFAULT_CONSTRUCTION_SUBSET_IDENTITY_MANIFEST_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_229_construction_identity_manifest.json"
)
DEFAULT_HOLDOUT_SOURCE_CANDIDATE_IDENTITY_MANIFEST_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_source_candidate_identity_manifest.json"
)
DEFAULT_HOLDOUT_SOURCE_JSONL = DEFAULT_OUT_DIR / "closed_candle_replay_evidence_rows.jsonl"
DEFAULT_FORWARD_HOLDOUT_SOURCE_JSONL = (
    DEFAULT_OUT_DIR / "out_of_sample_forward_holdout_source_rows.jsonl"
)
DEFAULT_HOLDOUT_ROWS_PATH = DEFAULT_OUT_DIR / "out_of_sample_holdout_reverify_rows.jsonl"
DEFAULT_REALTIME_ROWS_PATH = DEFAULT_OUT_DIR / "out_of_sample_realtime_paper_reverify_rows.jsonl"
DEFAULT_HOLDOUT_REGISTRY_PATH = DEFAULT_OUT_DIR / "out_of_sample_holdout_window_registry.json"
DEFAULT_HOLDOUT_REGISTRY_PREFLIGHT_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_window_registry_preflight.json"
)
DEFAULT_HOLDOUT_WINDOW_CANDIDATE_AUDIT_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_window_candidate_audit.json"
)
DEFAULT_HOLDOUT_WINDOW_PROMOTION_PACKET_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_window_promotion_packet.json"
)
DEFAULT_HOLDOUT_REGISTRY_PROMOTION_MANIFEST_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_window_registry_promotion_manifest.json"
)
DEFAULT_HOLDOUT_REGISTRY_DRAFT_MANIFEST_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_window_registry_draft_manifest.json"
)
DEFAULT_FORWARD_HOLDOUT_REGISTRATION_MANIFEST_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_forward_holdout_pre_registration.json"
)
DEFAULT_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_untouched_attestation_request.json"
)
DEFAULT_PAPER_LIVE_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest"
    / "v2_trade_management_paper_live_status.json"
)
DEFAULT_PAPER_LEDGER_TAIL_PATH = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_ledger_tail.json"
)
DEFAULT_CURRENT_SIGNAL_LINEAGE_PATH = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/current_signal_lineage.json"
)
DEFAULT_PAPER_RUNTIME_STATUS_PATH = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json"
)
DEFAULT_PAPER_LOOP_ONCE_STATUS_PATH = DEFAULT_OUT_DIR / "PAPER_LOOP_ONCE_STATUS.json"
DEFAULT_PAPER_ADAPTIVE_SIZING_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest"
    / "paper_adaptive_sizing_runtime_status.json"
)
DEFAULT_PAPER_EVENTS_PATH = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_events.jsonl"
)
DEFAULT_INTEGRITY_STATUS_PATH = DEFAULT_OUT_DIR / "out_of_sample_evidence_integrity_status.json"
_CHAIN_LAST_HASH_BY_PATH: dict[Path, str] = {}

PENDING_ELIGIBLE_SOURCE_KINDS = {
    "filesystem_runtime_snapshot",
    "redis_paper_intent",
    "redis_paper_signal",
    "redis_prediction",
    "redis_paper_ledger_accepted",
}
REALTIME_PENDING_SOURCE_TIMESTAMP_FIELDS = (
    "generated_at",
    "available_at",
    "decision_time",
    "entry_feature_generated_at",
    "entry_feature_available_at",
    "entry_feature_decision_time",
)
MAX_REALTIME_PENDING_SOURCE_AGE_SECONDS = 900
MAX_REALTIME_PENDING_SOURCE_CLOCK_SKEW_SECONDS = 60
HISTORICAL_REDIS_SOURCE_KINDS = {
    "redis_paper_ledger_open",
}
REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS = (
    "not_used_for_selector_development",
    "not_used_for_bucket_construction",
    "not_used_for_strategy_weight_calibration",
    "not_used_for_allocator_calibration",
    "not_used_for_229_candidate_subset",
)
CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS = (
    "PASSED_NO_OVERLAP_WITH_229_CONSTRUCTION_IDENTITIES"
)
FORWARD_HOLDOUT_PROOF_STATUS = "PASSED_UNTOUCHED_FORWARD_PRE_REGISTRATION"
FORWARD_CONSTRUCTION_SUBSET_PROOF_STATUS = (
    "PASSED_FORWARD_TEMPORAL_SEPARATION_FROM_229_CONSTRUCTION_IDENTITIES"
)

OUTCOME_FIELDS = {
    "after_cost_return_bps",
    "realized_after_cost_return_bps",
    "realized_pnl_bps",
    "paper_exit_pnl_bps",
    "outcome_after_cost_usd",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "funding_pnl_usd",
    "funding_pnl",
    "funding_pnl_source",
    "funding_pnl_accounting_version",
    "funding_pnl_accounting_status",
    "actual_funding_bps",
    "actual_funding_usd",
    "actual_funding_rate",
    "actual_fee_bps",
    "actual_fees_usd",
    "fee_usd",
    "actual_slippage_bps",
    "realized_slippage_bps",
    "actual_slippage_usd",
    "future_label_close_time",
    "future_label_horizon_candles",
    "closed_at",
    "exit_time",
    "exit_price",
    "mfe_bps",
    "mae_bps",
    "drawdown_bps",
}
PAPER_EVENT_OUTCOME_LIKE_FIELDS = (
    "paper_realized_pnl",
    "paper_pnl_delta",
    "paper_result",
    "gross_pnl_usdt",
    "realized_delta_usdt",
)
PAPER_EVENT_RECOGNIZED_CLOSED_OUTCOME_FIELDS = (
    "after_cost_return_bps",
    "realized_after_cost_return_bps",
    "realized_pnl_bps",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "funding_pnl_usd",
    "funding_pnl",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_format(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_payload(payload: Any) -> str:
    return _sha256_text(_stable_json(payload))


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def _sidecar_manifest_path(rows_path: Path) -> Path:
    return rows_path.with_suffix(rows_path.suffix + ".manifest.json")


def _manifest_history_path(manifest_path: Path) -> Path:
    return manifest_path.with_suffix(manifest_path.suffix + ".history.jsonl")


def _resolve_repo_relative_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else REPO_ROOT / path
    return candidate.resolve(strict=False)


def _manifest_history_path_matches(*, expected: Path, actual: Any) -> bool:
    if actual in (None, ""):
        return False
    actual_path = Path(str(actual))
    if str(actual_path) == str(expected):
        return True
    return _resolve_repo_relative_path(actual_path) == _resolve_repo_relative_path(expected)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=False, separators=(",", ":")) + "\n")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def _iter_jsonl(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    scanned = 0
    if not path.exists():
        return rows, {
            "path": str(path),
            "exists": False,
            "scanned_line_count": 0,
            "parse_error_count": 0,
            "parse_error_sample": [],
            "sha256": None,
        }
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            scanned += 1
            try:
                payload = json.loads(stripped)
            except Exception as exc:  # noqa: BLE001
                if len(parse_errors) < 20:
                    parse_errors.append({"line_number": line_number, "error": str(exc)})
                continue
            if isinstance(payload, dict):
                payload.setdefault("_source_line_number", line_number)
                rows.append(payload)
    return rows, {
        "path": str(path),
        "exists": True,
        "scanned_line_count": scanned,
        "parse_error_count": len(parse_errors),
        "parse_error_sample": parse_errors,
        "sha256": _file_sha256(path),
    }


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _set_if_present(row: dict[str, Any], field: str, value: Any) -> None:
    if _present(row.get(field)) or not _present(value):
        return
    row[field] = value


def _current_signal_lineage_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    lineage_payload = payload.get("current_signal_lineage")
    lineage = lineage_payload if isinstance(lineage_payload, dict) else payload
    if not isinstance(lineage, dict):
        return None
    signal = lineage.get("signal") if isinstance(lineage.get("signal"), dict) else {}
    trainer = (
        lineage.get("trainer_prediction")
        if isinstance(lineage.get("trainer_prediction"), dict)
        else {}
    )
    risk = lineage.get("risk_decision") if isinstance(lineage.get("risk_decision"), dict) else {}
    execution = (
        lineage.get("execution_intent")
        if isinstance(lineage.get("execution_intent"), dict)
        else {}
    )
    feature_snapshot = (
        lineage.get("feature_snapshot")
        if isinstance(lineage.get("feature_snapshot"), dict)
        else {}
    )
    lineage_ids = lineage.get("lineage_ids") if isinstance(lineage.get("lineage_ids"), dict) else {}
    if not signal and not trainer and not execution:
        return None

    row: dict[str, Any] = {
        "_producer_extracted_from_json": "current_signal_lineage",
        "future_labels_used_as_features": False,
        "source_payload_classification": lineage.get("classification"),
    }
    if lineage_ids:
        row["lineage_ids"] = dict(lineage_ids)
    for field in (
        "symbol",
        "timeframe",
        "side",
        "action",
        "strategy",
        "strategy_family",
        "selected_action",
        "proposed_action",
        "market_regime",
        "volatility_bucket",
        "liquidity_bucket",
        "decision_time",
        "available_at",
        "feature_cutoff",
        "generated_at",
        "entry_feature_snapshot_id",
        "entry_feature_decision_time",
        "entry_feature_available_at",
        "entry_feature_generated_at",
        "entry_feature_cutoff",
        "entry_feature_source",
        "entry_feature_candle_closed_confirmed",
        "confidence",
        "confidence_calibrated",
        "expected_move_after_cost_bps",
        "expected_move_bps",
        "expected_net_edge_bps",
        "signal_id",
        "prediction_id",
        "feature_snapshot_id",
        "market_age_seconds",
        "price_target",
        "price_target_after_cost",
        "price_target_high",
        "price_target_low",
        "stop_reference",
        "take_profit_reference",
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "margin_mode",
        "stop_distance_bps",
        "take_profit_structure",
        "take_profit_price",
        "hedge_budget_usd",
        "hedge_enabled",
        "entry_spread_bps",
        "actual_observed_spread_entry_bps",
        "depth_impact_bps",
        "expected_slippage_bps",
        "expected_slippage_usd",
        "fee_bps",
        "expected_fees_usd",
        "expected_funding_bps",
        "expected_funding_usd",
        "liquidation_buffer_bps",
        "liquidation_price_estimate",
        "orderbook_depth_usd",
        "correlation_exposure_pct",
        "allocator_decision",
        "selector_policy_fingerprint",
        "candidate_selection_tier",
        "paper_opportunity_tier",
        "paper_opportunity_tier_reason",
        "explicit_paper_opportunity_tier",
        "pre_guardian_paper_opportunity_tier",
        "pre_guardian_paper_opportunity_tier_reason",
        "pre_guardian_paper_fill_allowed_source",
        "continuous_edge_guardian_forced_shadow_only",
        "continuous_edge_guardian_status",
        "continuous_edge_guardian_block_reasons",
        "continuous_edge_guardian_allowed_runtime_actions",
        "counts_as_a_grade_evidence",
        "admission_tier",
        "candidate_tier",
        "masa_feature_cutoff",
        "live_gate",
    ):
        _set_if_present(row, field, signal.get(field))
    for target, source in (
        ("symbol", "symbol"),
        ("timeframe", "timeframe"),
        ("side", "direction"),
        ("confidence_calibrated", "confidence_calibrated"),
        ("confidence", "confidence_raw"),
        ("expected_move_after_cost_bps", "expected_move_after_cost_bps"),
        ("expected_move_bps", "expected_move_bps"),
        ("generated_at", "generated_at"),
        ("prediction_id", "prediction_id"),
        ("feature_snapshot_id", "feature_snapshot_id"),
        ("market_regime", "regime"),
        ("strategy_family", "strategy_family"),
        ("model_version", "model_version"),
        ("model_checkpoint", "model_checkpoint"),
        ("trainer_source", "trainer_source"),
    ):
        _set_if_present(row, target, trainer.get(source))
    for target, source in (
        ("expected_move_after_cost_bps", "expected_move_after_cost_bps"),
        ("expected_move_bps", "expected_move_bps"),
        ("risk_action", "risk_action"),
        ("risk_result", "risk_result"),
        ("risk_decision_id", "risk_decision_id"),
    ):
        _set_if_present(row, target, risk.get(source))
    for target, source in (
        ("symbol", "symbol"),
        ("side", "side"),
        ("signal_id", "signal_id"),
        ("risk_decision_id", "risk_decision_id"),
        ("execution_intent_id", "execution_intent_id"),
        ("generated_at", "generated_at"),
    ):
        _set_if_present(row, target, execution.get(source))
    _set_if_present(row, "feature_snapshot_id", feature_snapshot.get("feature_snapshot_id"))
    _set_if_present(row, "feature_generated_at", feature_snapshot.get("generated_at"))

    edge_gate = risk.get("paper_edge_gate") if isinstance(risk.get("paper_edge_gate"), dict) else {}
    if edge_gate:
        _set_if_present(row, "confidence_calibrated", edge_gate.get("confidence_calibrated"))
        _set_if_present(
            row,
            "expected_move_after_cost_bps",
            edge_gate.get("expected_move_after_cost_bps")
            or edge_gate.get("computed_expected_move_after_cost_bps"),
        )
        _set_if_present(row, "expected_move_bps", edge_gate.get("expected_move_bps"))
        row["market_snapshot"] = {
            key: value
            for key, value in {
                "fee_bps": edge_gate.get("fee_bps"),
                "spread_bps": edge_gate.get("spread_bps"),
                "slippage_bps": edge_gate.get("slippage_bps"),
            }.items()
            if _present(value)
        }
    protective_gate = (
        risk.get("paper_protective_behavior_gate")
        if isinstance(risk.get("paper_protective_behavior_gate"), dict)
        else {}
    )
    if protective_gate:
        _set_if_present(
            row,
            "microstructure_toxicity_score_bps",
            protective_gate.get("microstructure_toxicity_score_bps"),
        )
    exchange_order_allowed = execution.get("exchange_order_allowed")
    if exchange_order_allowed is not None:
        row["places_real_order"] = bool(exchange_order_allowed)
        row["live_order"] = bool(exchange_order_allowed)
    paper_only = execution.get("paper_only")
    if paper_only is not None:
        row["paper_only"] = bool(paper_only)
    if not _present(row.get("decision_time")) and _present(row.get("generated_at")):
        row["decision_time"] = row["generated_at"]
    if _present(lineage.get("generated_at")):
        row["source_lineage_generated_at"] = lineage.get("generated_at")
    if _present(payload.get("generated_at")):
        row["source_runtime_generated_at"] = payload.get("generated_at")
    return row


def _append_paper_loop_alias(
    row: dict[str, Any],
    *,
    target_field: str,
    source_field: str,
    value: Any,
) -> None:
    if _present(row.get(target_field)) or not _present(value):
        return
    row[target_field] = value
    aliases = row.setdefault("_producer_normalized_accounting_aliases", [])
    if isinstance(aliases, list):
        aliases.append({
            "target_field": target_field,
            "source_field": source_field,
            "normalization": "paper_loop_once_allocation_alias",
        })


def _append_paper_loop_derived_alias(
    row: dict[str, Any],
    *,
    target_field: str,
    source_fields: list[str],
    value: Any,
    formula: str,
) -> None:
    if _present(row.get(target_field)) or not _present(value):
        return
    row[target_field] = value
    aliases = row.setdefault("_producer_normalized_accounting_aliases", [])
    if isinstance(aliases, list):
        aliases.append({
            "target_field": target_field,
            "source_field": "+".join(source_fields),
            "normalization": "paper_loop_once_allocation_derived_accounting",
            "formula": formula,
        })


def _paper_loop_model_input_aliases(
    row: dict[str, Any],
    *,
    model_inputs: dict[str, Any],
) -> None:
    _append_paper_loop_alias(
        row,
        target_field="recommended_leverage",
        source_field="model_inputs.selected_leverage",
        value=model_inputs.get("selected_leverage"),
    )
    _append_paper_loop_alias(
        row,
        target_field="effective_leverage",
        source_field="model_inputs.selected_leverage",
        value=model_inputs.get("selected_leverage"),
    )
    _append_paper_loop_alias(
        row,
        target_field="recommended_leverage",
        source_field="model_inputs.leverage_target",
        value=model_inputs.get("leverage_target"),
    )
    _append_paper_loop_alias(
        row,
        target_field="effective_leverage",
        source_field="model_inputs.leverage_target",
        value=model_inputs.get("leverage_target"),
    )
    _append_paper_loop_alias(
        row,
        target_field="recommended_margin_mode",
        source_field="model_inputs.selected_margin_mode",
        value=model_inputs.get("selected_margin_mode"),
    )
    _append_paper_loop_alias(
        row,
        target_field="margin_mode",
        source_field="model_inputs.selected_margin_mode",
        value=model_inputs.get("selected_margin_mode"),
    )
    _append_paper_loop_alias(
        row,
        target_field="stop_distance_bps",
        source_field="model_inputs.stop_distance_bps",
        value=model_inputs.get("stop_distance_bps"),
    )
    _append_paper_loop_alias(
        row,
        target_field="fee_bps",
        source_field="model_inputs.fee_bps",
        value=model_inputs.get("fee_bps"),
    )
    _append_paper_loop_alias(
        row,
        target_field="expected_funding_bps",
        source_field="model_inputs.expected_funding_bps",
        value=model_inputs.get("expected_funding_bps"),
    )
    _append_paper_loop_alias(
        row,
        target_field="funding_rate",
        source_field="model_inputs.funding_rate",
        value=model_inputs.get("funding_rate"),
    )
    _append_paper_loop_alias(
        row,
        target_field="orderbook_depth_usd",
        source_field="model_inputs.orderbook_depth_usd",
        value=model_inputs.get("orderbook_depth_usd"),
    )
    _append_paper_loop_alias(
        row,
        target_field="orderbook_depth_usd",
        source_field="model_inputs.market_depth_capacity_usd",
        value=model_inputs.get("market_depth_capacity_usd"),
    )
    _append_paper_loop_alias(
        row,
        target_field="orderbook_depth_usd",
        source_field="model_inputs.depth_usd",
        value=model_inputs.get("depth_usd"),
    )

    gross_notional = status_module._coerce_float(row.get("gross_notional_usd"))
    effective_leverage = status_module._coerce_float(row.get("effective_leverage"))
    if (
        gross_notional is not None
        and gross_notional >= 0.0
        and effective_leverage is not None
        and effective_leverage > 0.0
    ):
        _append_paper_loop_derived_alias(
            row,
            target_field="allocated_margin_usd",
            source_fields=["gross_notional_usd", "effective_leverage"],
            value=round(gross_notional / effective_leverage, 8),
            formula="gross_notional_usd / effective_leverage",
        )
    fee_bps = status_module._coerce_float(row.get("fee_bps"))
    if gross_notional is not None and gross_notional >= 0.0 and fee_bps is not None:
        _append_paper_loop_derived_alias(
            row,
            target_field="expected_fees_usd",
            source_fields=["gross_notional_usd", "fee_bps"],
            value=round(gross_notional * fee_bps / 10_000.0, 8),
            formula="gross_notional_usd * fee_bps / 10000",
        )
    funding_bps = status_module._coerce_float(row.get("expected_funding_bps"))
    if gross_notional is not None and gross_notional >= 0.0 and funding_bps is not None:
        _append_paper_loop_derived_alias(
            row,
            target_field="expected_funding_usd",
            source_fields=["gross_notional_usd", "expected_funding_bps"],
            value=round(gross_notional * funding_bps / 10_000.0, 8),
            formula="gross_notional_usd * expected_funding_bps / 10000",
        )


def _paper_loop_once_allocation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nested_runtime = payload.get("paper_adaptive_sizing_runtime_status")
    if isinstance(nested_runtime, dict):
        runtime = nested_runtime
        payload_shape = "nested_paper_adaptive_sizing_runtime_status"
    elif isinstance(payload.get("candidate_allocations"), list) or isinstance(
        payload.get("sample_allocations"),
        list,
    ):
        runtime = payload
        payload_shape = "top_level_paper_adaptive_sizing_runtime_status"
    else:
        runtime = {}
        payload_shape = "unknown"
    allocation_sources: list[tuple[str, list[Any]]] = []
    for field in ("candidate_allocations", "sample_allocations"):
        allocations = runtime.get(field)
        if isinstance(allocations, list):
            allocation_sources.append((field, allocations))
    if not allocation_sources:
        return []

    rows: list[dict[str, Any]] = []
    seen_allocations: set[str] = set()
    for source_list_field, allocations in allocation_sources:
        for allocation in allocations:
            if not isinstance(allocation, dict):
                continue
            allocation_identity = status_module._first_present(
                allocation.get("allocation_id"),
                allocation.get("row_id"),
                allocation.get("prediction_id"),
                _stable_json(allocation),
            )
            dedupe_key = str(allocation_identity)
            if dedupe_key in seen_allocations:
                continue
            seen_allocations.add(dedupe_key)
            rows.append(
                _paper_loop_once_allocation_row(
                    allocation,
                    payload=payload,
                    runtime=runtime,
                    payload_shape=payload_shape,
                    source_list_field=source_list_field,
                )
            )
    return rows


def _paper_loop_once_allocation_row(
    allocation: dict[str, Any],
    *,
    payload: dict[str, Any],
    runtime: dict[str, Any],
    payload_shape: str,
    source_list_field: str,
) -> dict[str, Any]:
    model_inputs = (
        allocation.get("model_inputs")
        if isinstance(allocation.get("model_inputs"), dict)
        else {}
    )
    lineage_ids = (
        allocation.get("lineage_ids")
        if isinstance(allocation.get("lineage_ids"), dict)
        else {}
    )
    row: dict[str, Any] = {
        "_producer_extracted_from_json": (
            "paper_loop_once_candidate_allocation"
            if source_list_field == "candidate_allocations"
            else "paper_loop_once_sample_allocation"
        ),
        "_producer_source_payload_shape": payload_shape,
        "_producer_source_list_field": source_list_field,
        "future_labels_used_as_features": False,
        "source_payload_classification": payload.get("classification"),
        "source_runtime_status": runtime.get("status"),
        "source_runtime_started_at": payload.get("started_at"),
        "source_runtime_finished_at": payload.get("finished_at"),
        "source_runtime_generated_at": (
            runtime.get("generated_utc")
            or payload.get("generated_utc")
            or payload.get("generated_at")
        ),
    }
    raw_outcome_fields = sorted(
        field
        for field in OUTCOME_FIELDS
        if _present(allocation.get(field))
    )
    if raw_outcome_fields:
        row["_producer_source_outcome_fields_present"] = raw_outcome_fields
    allocation_id = allocation.get("allocation_id")
    if _present(allocation_id):
        row["row_id"] = f"paper_loop_once_allocation:{allocation_id}"
    if lineage_ids:
        row["lineage_ids"] = dict(lineage_ids)
    if model_inputs:
        row["model_inputs"] = dict(model_inputs)

    for field in (
        "allocation_id",
        "symbol",
        "timeframe",
        "side",
        "action",
        "selected_action",
        "proposed_action",
        "strategy",
        "strategy_family",
        "market_regime",
        "volatility_bucket",
        "liquidity_bucket",
        "decision_time",
        "available_at",
        "feature_cutoff",
        "generated_at",
        "confidence",
        "confidence_calibrated",
        "expected_move_after_cost_bps",
        "expected_move_bps",
        "expected_net_edge_bps",
        "signal_id",
        "prediction_id",
        "risk_decision_id",
        "execution_intent_id",
        "feature_snapshot_id",
        "model_version",
        "model_checkpoint",
        "trainer_source",
        "target_notional_usdt",
        "target_quantity",
        "risk_budget_pct",
        "risk_budget_pct_of_available_margin",
        "risk_budget_pct_of_equity",
        "market_state_integrity_score",
        "candidate_selection_tier",
        "explicit_paper_opportunity_tier",
        "paper_opportunity_tier",
        "paper_opportunity_tier_reason",
        "pre_guardian_paper_opportunity_tier",
        "pre_guardian_paper_opportunity_tier_reason",
        "pre_guardian_paper_fill_allowed_source",
        "continuous_edge_guardian_forced_shadow_only",
        "continuous_edge_guardian_status",
        "continuous_edge_guardian_block_reasons",
        "continuous_edge_guardian_allowed_runtime_actions",
        "counts_as_a_grade_evidence",
        "admission_tier",
        "candidate_tier",
        "liquidity_adjustment",
        "regime_adjustment",
        "confidence_adjustment",
        "risk_veto_reason_if_blocked",
        "final_size_reason",
        "price_target",
        "price_target_after_cost",
        "price_target_high",
        "price_target_low",
        "stop_reference",
        "take_profit_reference",
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "margin_mode",
        "stop_distance_bps",
        "take_profit_structure",
        "take_profit_price",
        "hedge_budget_usd",
        "hedge_enabled",
        "entry_spread_bps",
        "actual_observed_spread_entry_bps",
        "depth_impact_bps",
        "expected_slippage_bps",
        "expected_slippage_usd",
        "fee_bps",
        "expected_fees_usd",
        "expected_funding_bps",
        "expected_funding_usd",
        "liquidation_buffer_bps",
        "liquidation_price_estimate",
        "orderbook_depth_usd",
        "correlation_exposure_pct",
        "allocator_decision",
        "selector_policy_fingerprint",
        "policy_activated_at",
        "masa_feature_cutoff",
        "live_gate",
    ):
        _set_if_present(row, field, allocation.get(field))

    _set_if_present(
        row,
        "side",
        allocation.get("direction")
        or allocation.get("action")
        or allocation.get("selected_action")
        or allocation.get("proposed_action"),
    )
    _set_if_present(
        row,
        "action",
        allocation.get("action")
        or allocation.get("selected_action")
        or allocation.get("proposed_action"),
    )
    _set_if_present(row, "confidence_calibrated", allocation.get("confidence"))
    _set_if_present(row, "prediction_id", lineage_ids.get("prediction_id"))
    _set_if_present(row, "signal_id", lineage_ids.get("signal_id"))
    _set_if_present(row, "risk_decision_id", lineage_ids.get("risk_decision_id"))
    _set_if_present(row, "feature_snapshot_id", lineage_ids.get("feature_snapshot_id"))

    paper_only = status_module._first_present(
        allocation.get("paper_only"),
        runtime.get("paper_only"),
        payload.get("paper_only"),
    )
    if paper_only not in {None, ""}:
        row["paper_only"] = bool(paper_only)
    real_order_flag = status_module._first_present(
        allocation.get("places_real_order"),
        allocation.get("live_order"),
        runtime.get("places_real_order"),
        payload.get("places_real_order"),
    )
    if real_order_flag not in {None, ""}:
        row["places_real_order"] = bool(real_order_flag)
        row["live_order"] = bool(real_order_flag)

    _append_paper_loop_alias(
        row,
        target_field="gross_notional_usd",
        source_field="target_notional_usdt",
        value=allocation.get("target_notional_usdt"),
    )
    _append_paper_loop_alias(
        row,
        target_field="entry_spread_bps",
        source_field="model_inputs.spread_bps",
        value=model_inputs.get("spread_bps"),
    )
    _append_paper_loop_alias(
        row,
        target_field="actual_observed_spread_entry_bps",
        source_field="model_inputs.spread_bps",
        value=model_inputs.get("spread_bps"),
    )
    _append_paper_loop_alias(
        row,
        target_field="expected_slippage_bps",
        source_field="model_inputs.slippage_bps",
        value=model_inputs.get("slippage_bps"),
    )
    _append_paper_loop_alias(
        row,
        target_field="correlation_exposure_pct",
        source_field="model_inputs.correlation_exposure_pct",
        value=model_inputs.get("correlation_exposure_pct"),
    )
    _paper_loop_model_input_aliases(row, model_inputs=model_inputs)
    return row


def _rows_from_json(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = _load_json(path)
    rows: list[dict[str, Any]] = []
    extracted_counts: dict[str, int] = {}
    if isinstance(payload, dict):
        for key in ("rows", "items", "entries", "closed_trades", "accepted", "open_positions"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(dict(row) for row in value if isinstance(row, dict))
        if not rows:
            observations = payload.get("shadow_observations")
            if isinstance(observations, list):
                rows.extend(dict(row) for row in observations if isinstance(row, dict))
        current_signal_row = _current_signal_lineage_row(payload)
        if current_signal_row is not None:
            rows.append(current_signal_row)
            extracted_counts["current_signal_lineage"] = (
                extracted_counts.get("current_signal_lineage", 0) + 1
            )
        paper_loop_rows = _paper_loop_once_allocation_rows(payload)
        if paper_loop_rows:
            rows.extend(paper_loop_rows)
            for row in paper_loop_rows:
                extraction = str(
                    row.get("_producer_extracted_from_json")
                    or "paper_loop_once_allocation"
                )
                extracted_counts[extraction] = extracted_counts.get(extraction, 0) + 1
    elif isinstance(payload, list):
        rows.extend(dict(row) for row in payload if isinstance(row, dict))
    return rows, {
        "path": str(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "extracted_row_counts": {
            key: extracted_counts[key] for key in sorted(extracted_counts)
        },
        "sha256": _file_sha256(path),
    }


def _existing_identities(path: Path) -> set[str]:
    rows, _status = _iter_jsonl(path)
    identities: set[str] = set()
    for row in rows:
        identity = str(row.get("candidate_identity") or row.get("position_identity") or "")
        if identity:
            identities.add(identity)
    return identities


def _existing_rows_by_identity(path: Path) -> dict[str, dict[str, Any]]:
    rows, _status = _iter_jsonl(path)
    by_identity: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get("candidate_identity") or row.get("position_identity") or "")
        if identity and identity not in by_identity:
            by_identity[identity] = row
    return by_identity


def _last_chain_hash(path: Path) -> str:
    if not path.exists():
        return "GENESIS"
    last_hash = "GENESIS"
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("chain_hash"):
                last_hash = str(payload["chain_hash"])
    return last_hash


def _append_chain(
    *,
    chain_path: Path,
    event_type: str,
    sidecar_path: Path,
    identity: str,
    payload: dict[str, Any],
    generated_utc: str,
) -> dict[str, str]:
    record_hash = _sha256_payload(payload)
    if chain_path not in _CHAIN_LAST_HASH_BY_PATH:
        _CHAIN_LAST_HASH_BY_PATH[chain_path] = _last_chain_hash(chain_path)
    previous_hash = _CHAIN_LAST_HASH_BY_PATH[chain_path]
    chain_record = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "event_type": event_type,
        "sidecar_path": str(sidecar_path),
        "identity": identity,
        "previous_hash": previous_hash,
        "record_hash": record_hash,
    }
    chain_hash = _sha256_payload(chain_record)
    chain_record["chain_hash"] = chain_hash
    _append_jsonl(chain_path, chain_record)
    _CHAIN_LAST_HASH_BY_PATH[chain_path] = chain_hash
    return {
        "record_hash": record_hash,
        "previous_hash": previous_hash,
        "chain_hash": chain_hash,
    }


def _append_manifest_history(
    *,
    manifest_path: Path,
    sidecar_path: Path,
    manifest: dict[str, Any],
    generated_utc: str,
) -> dict[str, str]:
    history_path = _manifest_history_path(manifest_path)
    manifest_payload = dict(manifest)
    manifest_hash = _sha256_payload(manifest_payload)
    if history_path not in _CHAIN_LAST_HASH_BY_PATH:
        _CHAIN_LAST_HASH_BY_PATH[history_path] = _last_chain_hash(history_path)
    previous_hash = _CHAIN_LAST_HASH_BY_PATH[history_path]
    record = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "event_type": "sidecar_manifest_written",
        "producer": manifest.get("producer"),
        "manifest_path": str(manifest_path),
        "sidecar_path": str(sidecar_path),
        "previous_hash": previous_hash,
        "manifest_hash": manifest_hash,
        "manifest_payload": manifest_payload,
    }
    chain_hash = _sha256_payload(record)
    record["chain_hash"] = chain_hash
    _append_jsonl(history_path, record)
    _CHAIN_LAST_HASH_BY_PATH[history_path] = chain_hash
    return {
        "manifest_hash": manifest_hash,
        "previous_hash": previous_hash,
        "chain_hash": chain_hash,
        "history_path": str(history_path),
    }


def _holdout_registry_manifest_path(registry_path: Path) -> Path:
    return registry_path.with_suffix(registry_path.suffix + ".manifest.json")


def _write_holdout_registry_manifest(
    *,
    registry_path: Path,
    source_path: Path,
    registry: dict[str, Any],
    source_status: dict[str, Any],
    registry_preflight: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    manifest_path = _holdout_registry_manifest_path(registry_path)
    windows = [
        window
        for window in registry.get("windows") or []
        if isinstance(window, dict)
    ]
    window_summaries = []
    for window in windows:
        proof = window.get("exclusion_proof")
        window_summaries.append({
            "window_id": window.get("window_id"),
            "start_decision_time": window.get("start_decision_time"),
            "end_decision_time": window.get("end_decision_time"),
            "symbols": window.get("symbols") if isinstance(window.get("symbols"), list) else [],
            "timeframes": (
                window.get("timeframes")
                if isinstance(window.get("timeframes"), list)
                else []
            ),
            "eligible_for_holdout": window.get("eligible_for_holdout") is True,
            "row_identity_filter_mode": window.get("row_identity_filter_mode"),
            "registered_source_row_identity_hash_count": len(
                _registered_source_row_identity_hashes(window)
            ),
            "window_hashes": window.get("window_hashes")
            if isinstance(window.get("window_hashes"), dict)
            else {},
            "exclusion_proof_status": (
                proof.get("status") if isinstance(proof, dict) else None
            ),
            "exclusion_proof_attestations": (
                proof.get("attestations") if isinstance(proof, dict) else {}
            ),
        })

    registry_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "holdout_registry",
        "status": (
            "READY_HOLDOUT_REGISTRY_MANIFEST"
            if registry_path.exists()
            else "NO_GO_HOLDOUT_REGISTRY_MISSING"
        ),
        "registry_path": str(registry_path),
        "registry_sha256": _file_sha256(registry_path),
        "registry_status": registry.get("status"),
        "selector_policy_fingerprint": registry.get("selector_policy_fingerprint"),
        "source_path": str(source_path),
        "source_status": {
            "path": source_status.get("path"),
            "exists": source_status.get("exists"),
            "sha256": source_status.get("sha256"),
            "scanned_line_count": source_status.get("scanned_line_count"),
            "parse_error_count": source_status.get("parse_error_count"),
        },
        "preflight_status": registry_preflight.get("status"),
        "preflight_global_reasons": registry_preflight.get("global_reasons"),
        "registered_window_count": len(windows),
        "window_summaries": window_summaries,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, registry_manifest)
    history = _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=registry_path,
        manifest=registry_manifest,
        generated_utc=generated_utc,
    )
    return {
        "manifest_path": str(manifest_path),
        "manifest": registry_manifest,
        "history": history,
    }


def _payload_without_chain_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    stripped = dict(payload)
    stripped.pop("producer_hash_chain", None)
    return stripped


def _possible_sidecar_hashes(row: dict[str, Any]) -> set[str]:
    stripped = _payload_without_chain_metadata(row)
    hashes = {_sha256_payload(stripped)}
    if "_source_line_number" in stripped:
        without_line = dict(stripped)
        without_line.pop("_source_line_number", None)
        hashes.add(_sha256_payload(without_line))
    return hashes


def _sidecar_hash_index(paths: list[Path]) -> tuple[dict[str, dict[str, list[int]]], dict[str, int], dict[str, Any]]:
    hash_index: dict[str, dict[str, list[int]]] = {}
    row_counts: dict[str, int] = {}
    statuses: dict[str, Any] = {}
    for path in paths:
        rows, source_status = _iter_jsonl(path)
        path_key = str(path)
        row_counts[path_key] = len(rows)
        statuses[path_key] = {
            **source_status,
            "row_count": len(rows),
        }
        indexed: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            for row_hash in _possible_sidecar_hashes(row):
                indexed.setdefault(row_hash, []).append(index)
        hash_index[path_key] = indexed
    return hash_index, row_counts, statuses


def verify_hash_chain(
    *,
    chain_path: Path,
    sidecar_paths: list[Path],
    generated_utc: str,
) -> dict[str, Any]:
    chain_rows, chain_status = _iter_jsonl(chain_path)
    hash_index, sidecar_row_counts, sidecar_statuses = _sidecar_hash_index(sidecar_paths)
    consumed_indices: dict[str, set[int]] = {path: set() for path in sidecar_row_counts}
    failures: list[dict[str, Any]] = []
    previous_hash = "GENESIS"
    verified_records = 0
    event_type_counts: dict[str, int] = {}

    for index, chain_record in enumerate(chain_rows):
        event_type = str(chain_record.get("event_type") or "UNKNOWN")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        chain_hash = str(chain_record.get("chain_hash") or "")
        chain_without_hash = dict(chain_record)
        chain_without_hash.pop("chain_hash", None)
        chain_without_hash.pop("_source_line_number", None)
        expected_chain_hash = _sha256_payload(chain_without_hash)
        if chain_record.get("previous_hash") != previous_hash:
            failures.append({
                "index": index,
                "identity": chain_record.get("identity"),
                "reason": "CHAIN_PREVIOUS_HASH_MISMATCH",
                "expected_previous_hash": previous_hash,
                "actual_previous_hash": chain_record.get("previous_hash"),
            })
        if chain_hash != expected_chain_hash:
            failures.append({
                "index": index,
                "identity": chain_record.get("identity"),
                "reason": "CHAIN_HASH_MISMATCH",
                "expected_chain_hash": expected_chain_hash,
                "actual_chain_hash": chain_hash,
            })
        sidecar_path = str(chain_record.get("sidecar_path") or "")
        record_hash = str(chain_record.get("record_hash") or "")
        sidecar_index = hash_index.get(sidecar_path)
        if sidecar_index is None:
            failures.append({
                "index": index,
                "identity": chain_record.get("identity"),
                "reason": "CHAIN_REFERENCES_UNEXPECTED_SIDECAR_PATH",
                "sidecar_path": sidecar_path,
            })
        else:
            candidate_indices = sidecar_index.get(record_hash, [])
            consumed = consumed_indices.setdefault(sidecar_path, set())
            matched_index = next(
                (candidate_index for candidate_index in candidate_indices if candidate_index not in consumed),
                None,
            )
            if matched_index is None:
                failures.append({
                    "index": index,
                    "identity": chain_record.get("identity"),
                    "reason": "CHAIN_RECORD_HASH_NOT_FOUND_IN_SIDECAR",
                    "sidecar_path": sidecar_path,
                    "record_hash": record_hash,
                })
            else:
                consumed.add(matched_index)
                verified_records += 1
        previous_hash = chain_hash

    unchained_sidecar_rows = {
        path: max(0, sidecar_row_counts.get(path, 0) - len(consumed_indices.get(path, set())))
        for path in sidecar_row_counts
    }
    for path, count in sorted(unchained_sidecar_rows.items()):
        if count > 0:
            failures.append({
                "reason": "SIDECAR_ROWS_WITHOUT_CHAIN_RECORD",
                "sidecar_path": path,
                "unchained_row_count": count,
            })

    status = "PASSED_HASH_CHAIN_INTEGRITY" if not failures else "NO_GO_HASH_CHAIN_INTEGRITY_FAILED"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": status,
        "chain_path": str(chain_path),
        "chain_status": chain_status,
        "sidecar_statuses": sidecar_statuses,
        "chain_record_count": len(chain_rows),
        "verified_sidecar_record_count": verified_records,
        "event_type_counts": {
            key: event_type_counts[key]
            for key in sorted(event_type_counts)
        },
        "unchained_sidecar_row_counts": {
            path: count
            for path, count in sorted(unchained_sidecar_rows.items())
            if count > 0
        },
        "failure_count": len(failures),
        "failure_sample": failures[:50],
    }


def verify_manifest_history(
    *,
    manifest_path: Path,
    generated_utc: str,
) -> dict[str, Any]:
    requested_manifest_path = manifest_path
    manifest_path = _resolve_repo_relative_path(manifest_path)
    history_path = _manifest_history_path(manifest_path)
    history_rows, history_status = _iter_jsonl(history_path)
    current_manifest = _load_json(manifest_path)
    current_manifest = current_manifest if isinstance(current_manifest, dict) else None
    current_manifest_hash = _sha256_payload(current_manifest) if current_manifest is not None else None
    failures: list[dict[str, Any]] = []
    previous_hash = "GENESIS"
    event_type_counts: dict[str, int] = {}
    latest_record: dict[str, Any] | None = None

    if not history_rows:
        failures.append({
            "reason": "MANIFEST_HISTORY_MISSING",
            "manifest_path": str(manifest_path),
            "history_path": str(history_path),
        })
    if current_manifest is None:
        failures.append({
            "reason": "CURRENT_MANIFEST_MISSING_OR_MALFORMED",
            "manifest_path": str(manifest_path),
        })

    for index, record in enumerate(history_rows):
        event_type = str(record.get("event_type") or "UNKNOWN")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        chain_hash = str(record.get("chain_hash") or "")
        record_without_hash = dict(record)
        record_without_hash.pop("chain_hash", None)
        record_without_hash.pop("_source_line_number", None)
        expected_chain_hash = _sha256_payload(record_without_hash)
        if record.get("previous_hash") != previous_hash:
            failures.append({
                "index": index,
                "reason": "MANIFEST_HISTORY_PREVIOUS_HASH_MISMATCH",
                "expected_previous_hash": previous_hash,
                "actual_previous_hash": record.get("previous_hash"),
            })
        if chain_hash != expected_chain_hash:
            failures.append({
                "index": index,
                "reason": "MANIFEST_HISTORY_CHAIN_HASH_MISMATCH",
                "expected_chain_hash": expected_chain_hash,
                "actual_chain_hash": chain_hash,
            })
        if not _manifest_history_path_matches(
            expected=manifest_path,
            actual=record.get("manifest_path"),
        ):
            failures.append({
                "index": index,
                "reason": "MANIFEST_HISTORY_REFERENCES_UNEXPECTED_MANIFEST_PATH",
                "expected_manifest_path": str(manifest_path),
                "requested_manifest_path": str(requested_manifest_path),
                "actual_manifest_path": record.get("manifest_path"),
            })
        manifest_payload = record.get("manifest_payload")
        if not isinstance(manifest_payload, dict):
            failures.append({
                "index": index,
                "reason": "MANIFEST_HISTORY_PAYLOAD_MISSING_OR_MALFORMED",
            })
        else:
            expected_manifest_hash = _sha256_payload(manifest_payload)
            if record.get("manifest_hash") != expected_manifest_hash:
                failures.append({
                    "index": index,
                    "reason": "MANIFEST_HISTORY_PAYLOAD_HASH_MISMATCH",
                    "expected_manifest_hash": expected_manifest_hash,
                    "actual_manifest_hash": record.get("manifest_hash"),
                })
        previous_hash = chain_hash
        latest_record = record

    if latest_record is not None and current_manifest_hash is not None:
        if latest_record.get("manifest_hash") != current_manifest_hash:
            failures.append({
                "reason": "LATEST_MANIFEST_HISTORY_NOT_CURRENT",
                "expected_current_manifest_hash": current_manifest_hash,
                "latest_history_manifest_hash": latest_record.get("manifest_hash"),
            })

    status = "PASSED_MANIFEST_HISTORY_INTEGRITY" if not failures else "NO_GO_MANIFEST_HISTORY_INTEGRITY_FAILED"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": status,
        "manifest_path": str(manifest_path),
        "history_path": str(history_path),
        "history_status": history_status,
        "history_record_count": len(history_rows),
        "current_manifest_hash": current_manifest_hash,
        "latest_history_manifest_hash": latest_record.get("manifest_hash") if latest_record else None,
        "latest_history_chain_hash": latest_record.get("chain_hash") if latest_record else None,
        "event_type_counts": {
            key: event_type_counts[key]
            for key in sorted(event_type_counts)
        },
        "failure_count": len(failures),
        "failure_sample": failures[:50],
    }


def verify_evidence_integrity(
    *,
    holdout_rows: Path,
    realtime_rows: Path,
    out_dir: Path,
    generated_utc: str,
    holdout_registry: Path | None = None,
) -> dict[str, Any]:
    holdout_pending = holdout_rows.with_name("out_of_sample_holdout_reverify_pending.jsonl")
    holdout_rejected = holdout_rows.with_name("out_of_sample_holdout_reverify_rejected.jsonl")
    realtime_pending = realtime_rows.with_name("out_of_sample_realtime_paper_reverify_pending.jsonl")
    realtime_rejected = realtime_rows.with_name("out_of_sample_realtime_paper_reverify_rejected.jsonl")
    holdout = verify_hash_chain(
        chain_path=holdout_rows.with_suffix(holdout_rows.suffix + ".hash_chain.jsonl"),
        sidecar_paths=[holdout_rows, holdout_pending, holdout_rejected],
        generated_utc=generated_utc,
    )
    realtime = verify_hash_chain(
        chain_path=realtime_rows.with_suffix(realtime_rows.suffix + ".hash_chain.jsonl"),
        sidecar_paths=[realtime_rows, realtime_pending, realtime_rejected],
        generated_utc=generated_utc,
    )
    holdout_manifest_history = verify_manifest_history(
        manifest_path=_sidecar_manifest_path(holdout_rows),
        generated_utc=generated_utc,
    )
    realtime_manifest_history = verify_manifest_history(
        manifest_path=_sidecar_manifest_path(realtime_rows),
        generated_utc=generated_utc,
    )
    holdout_registry_manifest_history: dict[str, Any] | None = None
    if holdout_registry is not None:
        holdout_registry_manifest_history = verify_manifest_history(
            manifest_path=_holdout_registry_manifest_path(holdout_registry),
            generated_utc=generated_utc,
        )
    registry_manifest_history_passed = (
        holdout_registry_manifest_history is None
        or holdout_registry_manifest_history.get("status")
        == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    )
    status = (
        "PASSED_EVIDENCE_INTEGRITY"
        if holdout.get("status") == "PASSED_HASH_CHAIN_INTEGRITY"
        and realtime.get("status") == "PASSED_HASH_CHAIN_INTEGRITY"
        and holdout_manifest_history.get("status") == "PASSED_MANIFEST_HISTORY_INTEGRITY"
        and realtime_manifest_history.get("status") == "PASSED_MANIFEST_HISTORY_INTEGRITY"
        and registry_manifest_history_passed
        else "NO_GO_EVIDENCE_INTEGRITY_FAILED"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "verify",
        "status": status,
        "selector_policy_fingerprint": EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "holdout": holdout,
        "realtime": realtime,
        "holdout_manifest_history": holdout_manifest_history,
        "realtime_manifest_history": realtime_manifest_history,
        "holdout_registry_manifest_history": (
            holdout_registry_manifest_history
            if holdout_registry_manifest_history is not None
            else {
                "schema_version": SCHEMA_VERSION,
                "generated_utc": generated_utc,
                "status": "SKIPPED_HOLDOUT_REGISTRY_MANIFEST_HISTORY_NOT_REQUESTED",
            }
        ),
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(out_dir / DEFAULT_INTEGRITY_STATUS_PATH.name, summary)
    return summary


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _row_identity(row: dict[str, Any]) -> str:
    explicit = status_module._first_present(
        row.get("candidate_identity"),
        row.get("position_identity"),
        row.get("row_id"),
        row.get("intent_id"),
        row.get("paper_intent_id"),
        row.get("prediction_id"),
        row.get("entry_prediction_id"),
        row.get("source_prediction_id"),
        row.get("signal_id"),
        row.get("entry_signal_id"),
        row.get("source_signal_id"),
        row.get("fill_id"),
        row.get("source_redis_key"),
    )
    if explicit not in {None, ""}:
        return str(explicit)
    return "|".join(
        str(value or "")
        for value in (
            status_module._normalized_symbol(row),
            status_module._row_value(row, "timeframe") or row.get("timeframe"),
            status_module._directional_side(row),
            row.get("decision_time") or row.get("entry_feature_decision_time"),
        )
    )


def _row_identity_hash(row: dict[str, Any]) -> str:
    return _sha256_text(_row_identity(row))


def _candidate_identity(row: dict[str, Any], *, scope: str) -> str:
    raw = f"{scope}|{_row_identity(row)}"
    return _sha256_text(raw)


def _row_identity_alias_values(row: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for field in (
        "row_id",
        "intent_id",
        "source_intent_id",
        "paper_intent_id",
        "paper_fill_intent_id",
        "prediction_id",
        "entry_prediction_id",
        "source_prediction_id",
        "signal_id",
        "entry_signal_id",
        "source_signal_id",
        "fill_id",
        "ledger_row_id",
        "position_id",
        "close_id",
        "outcome_label_id",
    ):
        value = row.get(field)
        if value not in {None, ""}:
            aliases.add(str(value))
    for field in (
        "source_fill_ids",
        "accepted_fill_policy_reconciliation_ids",
    ):
        values = row.get(field)
        if isinstance(values, list):
            aliases.update(str(value) for value in values if value not in {None, ""})
    lineage = row.get("lineage_ids")
    if isinstance(lineage, dict):
        aliases.update(str(value) for value in lineage.values() if value not in {None, ""})
    fallback = _row_identity(row)
    if fallback:
        aliases.add(fallback)
    return aliases


def _candidate_identity_aliases(row: dict[str, Any], *, scope: str) -> set[str]:
    return {
        _sha256_text(f"{scope}|{alias}")
        for alias in _row_identity_alias_values(row)
    }


def _rows_at_path(payload: Any, path: tuple[str, ...]) -> list[dict[str, Any]]:
    value = payload
    for segment in path:
        if not isinstance(value, dict):
            return []
        value = value.get(segment)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _construction_subset_identity_source_status(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    source_sha256 = _file_sha256(path)
    if not isinstance(payload, dict):
        return {
            "status": "NO_GO_CONSTRUCTION_SUBSET_SOURCE_MISSING_OR_INVALID",
            "path": str(path),
            "exists": path.exists(),
            "sha256": source_sha256,
            "full_identity_set_available": False,
            "candidate_count": None,
            "identity_source_paths": [],
            "identity_hash_count": 0,
            "unique_identity_hash_count": 0,
            "identity_hash_set_sha256": None,
            "identity_hashes": [],
            "identity_hash_sample": [],
            "sample_only_identity_count": 0,
            "sample_only_identity_hash_sample": [],
            "validated_replay_sample_is_not_full_proof": False,
        }

    candidate_count = status_module._coerce_float(
        payload.get("validated_replay_candidate_count")
        or payload.get("selected_a_grade_subset_candidate_count")
    )
    deployment = payload.get("validated_replay_deployment_status")
    if candidate_count is None and isinstance(deployment, dict):
        candidate_count = status_module._coerce_float(
            deployment.get("validated_replay_deployment_candidate_count")
            or deployment.get("validated_replay_candidate_count")
        )
    expected_count = int(candidate_count) if candidate_count is not None else 229
    identity_paths = (
        ("construction_subset_identity_rows",),
        ("construction_subset_rows",),
        ("validated_replay_candidates",),
        ("validated_replay_deployment_candidates",),
        ("selected_a_grade_subset_candidates",),
        ("validated_replay_rows",),
        ("rows",),
        ("validated_replay_deployment_status", "validated_replay_candidates"),
        ("validated_replay_deployment_status", "validated_replay_deployment_candidates"),
        ("validated_replay_deployment_status", "selected_a_grade_subset_candidates"),
        ("validated_replay_deployment_status", "validated_replay_rows"),
        ("validated_replay_deployment_status", "rows"),
    )
    sample_paths = (
        ("validated_replay_deployment_status", "validated_replay_sample"),
        ("valid_label_sample",),
    )
    identity_rows: list[dict[str, Any]] = []
    identity_source_paths: list[str] = []
    for row_path in identity_paths:
        rows = _rows_at_path(payload, row_path)
        if rows:
            identity_rows.extend(rows)
            identity_source_paths.append(".".join(row_path))
    sample_rows: list[dict[str, Any]] = []
    for row_path in sample_paths:
        sample_rows.extend(_rows_at_path(payload, row_path))

    identity_hashes = sorted({_sha256_text(_row_identity(row)) for row in identity_rows})
    sample_identity_hashes = sorted({_sha256_text(_row_identity(row)) for row in sample_rows})
    full_identity_set_available = bool(
        expected_count > 0
        and len(identity_hashes) >= expected_count
        and len(identity_source_paths) > 0
    )
    return {
        "status": (
            "PASSED_CONSTRUCTION_SUBSET_EXACT_IDENTITIES_AVAILABLE"
            if full_identity_set_available
            else "NO_GO_CONSTRUCTION_SUBSET_EXACT_IDENTITIES_UNAVAILABLE"
        ),
        "path": str(path),
        "exists": path.exists(),
        "sha256": source_sha256,
        "candidate_count": expected_count,
        "full_identity_set_available": full_identity_set_available,
        "identity_source_paths": identity_source_paths,
        "identity_hash_count": len(identity_hashes),
        "unique_identity_hash_count": len(set(identity_hashes)),
        "identity_hash_set_sha256": (
            _sha256_payload(identity_hashes) if identity_hashes else None
        ),
        "identity_hashes": identity_hashes,
        "identity_hash_sample": identity_hashes[:20],
        "sample_only_identity_count": len(sample_identity_hashes),
        "sample_only_identity_hash_sample": sample_identity_hashes[:20],
        "validated_replay_sample_is_not_full_proof": (
            len(sample_identity_hashes) > 0 and not full_identity_set_available
        ),
    }


def _construction_subset_identity_manifest(
    *,
    source_path: Path,
    source_status: dict[str, Any],
    source_rows: list[dict[str, Any]],
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    generated_utc: str,
) -> dict[str, Any]:
    identity_rows: list[dict[str, Any]] = []
    reject_reason_counts: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    symbols: set[str] = set()
    timeframes: set[str] = set()

    for row in source_rows:
        selection_row = _without_outcome_fields(row)
        reasons = _decision_time_holdout_reject_reasons(
            selection_row,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_bucket_keys,
        )
        if reasons:
            for reason in reasons:
                reject_reason_counts[reason] = reject_reason_counts.get(reason, 0) + 1
            continue
        row_identity = _row_identity(selection_row)
        row_identity_hash = _sha256_text(row_identity)
        symbol = status_module._normalized_symbol(selection_row)
        timeframe = str(
            status_module._row_value(selection_row, "timeframe")
            or selection_row.get("timeframe")
            or ""
        )
        side = status_module._directional_side(selection_row) or "unknown"
        if symbol != "UNKNOWN":
            symbols.add(symbol)
        if timeframe:
            timeframes.add(timeframe)
        side_counts[side] = side_counts.get(side, 0) + 1
        identity_rows.append({
            "row_id": row_identity,
            "source_row_identity": row_identity,
            "source_row_identity_hash": row_identity_hash,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "decision_time": (
                selection_row.get("decision_time")
                or selection_row.get("entry_feature_decision_time")
            ),
            "available_at": selection_row.get("available_at"),
            "feature_cutoff": selection_row.get("feature_cutoff"),
            "candidate_selected_before_outcome": True,
            "future_labels_used_as_features": False,
        })

    identity_hashes = sorted(
        {str(row["source_row_identity_hash"]) for row in identity_rows}
    )
    expected_construction_count = 229
    count_matches_expected = len(identity_rows) == expected_construction_count
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": (
            "PASSED_DERIVED_229_CONSTRUCTION_SUBSET_IDENTITIES"
            if count_matches_expected
            else "NO_GO_DERIVED_CONSTRUCTION_SUBSET_COUNT_MISMATCH"
        ),
        "selector_policy_fingerprint": expected_fingerprint,
        "construction_subset_identity_source": (
            "derived_from_holdout_source_with_frozen_selector_decision_time_readiness"
        ),
        "source_path": str(source_path),
        "source_sha256": source_status.get("sha256"),
        "source_row_count": len(source_rows),
        "validated_replay_candidate_count": len(identity_rows),
        "expected_construction_candidate_count": expected_construction_count,
        "candidate_count_matches_expected_229": count_matches_expected,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_identity_derivation": [],
        "outcome_fields_excluded_from_identity_derivation": sorted(OUTCOME_FIELDS),
        "eligible_bucket_count": len(eligible_bucket_keys),
        "construction_subset_symbol_count": len(symbols),
        "construction_subset_symbols_sample": sorted(symbols)[:100],
        "construction_subset_timeframes": sorted(timeframes),
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "identity_hash_count": len(identity_hashes),
        "unique_identity_hash_count": len(set(identity_hashes)),
        "identity_hash_set_sha256": _sha256_payload(identity_hashes),
        "identity_hash_sample": identity_hashes[:20],
        "decision_time_reject_reason_counts": {
            key: reject_reason_counts[key] for key in sorted(reject_reason_counts)
        },
        "validated_replay_candidates": identity_rows,
        "construction_subset_identity_rows": identity_rows,
        "not_countable_holdout_evidence": True,
        "interpretation": (
            "Exact identity set for the previously selected replay construction subset. "
            "This artifact is used only to reject holdout overlap and does not create "
            "or promote countable out-of-sample evidence."
        ),
    }


def _construction_subset_identity_proof_template(
    *,
    construction_subset_status: dict[str, Any],
    window_hashes: dict[str, Any],
    source_row_identity_hashes: list[str] | None = None,
) -> dict[str, Any]:
    construction_hashes = {
        str(value)
        for value in construction_subset_status.get("identity_hashes") or []
        if value not in {None, ""}
    }
    holdout_hashes = {
        str(value)
        for value in source_row_identity_hashes or []
        if value not in {None, ""}
    }
    overlap_hashes = sorted(construction_hashes & holdout_hashes)
    exact_identity_set_available = (
        construction_subset_status.get("full_identity_set_available") is True
        and bool(construction_hashes)
        and bool(holdout_hashes)
    )
    return {
        "status": (
            CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
            if exact_identity_set_available and not overlap_hashes
            else "NO_GO_OVERLAPS_229_CONSTRUCTION_IDENTITIES"
            if exact_identity_set_available and overlap_hashes
            else "REQUIRES_CONSTRUCTION_SUBSET_IDENTITY_PROOF"
        ),
        "construction_subset_source_path": construction_subset_status.get("path"),
        "construction_subset_source_sha256": construction_subset_status.get("sha256"),
        "construction_subset_candidate_count": construction_subset_status.get(
            "candidate_count"
        ),
        "construction_subset_identity_hash_set_sha256": construction_subset_status.get(
            "identity_hash_set_sha256"
        ),
        "holdout_source_row_identity_hash_set_sha256": window_hashes.get(
            "source_row_identity_hash_set_sha256"
        ),
        "overlap_identity_hash_count": len(overlap_hashes) if exact_identity_set_available else None,
        "overlap_identity_hash_sample": overlap_hashes[:20],
        "overlap_identity_hashes_computed_from_exact_sets": exact_identity_set_available,
        "proof_generation_policy": (
            "Machine-verifiable overlap proof only. This does not attest that the "
            "window was untouched by development, calibration, bucket construction, "
            "or allocator work; PASSED_UNTOUCHED remains independently required."
        ),
    }


def _construction_subset_identity_proof_reasons(
    proof: dict[str, Any],
    *,
    construction_subset_status: dict[str, Any],
    window_hashes: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if construction_subset_status.get("full_identity_set_available") is not True:
        reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_EXACT_IDENTITIES_UNAVAILABLE")
    if proof.get("status") != CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS:
        reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_PROOF_NOT_PASSED")
    source_sha256 = construction_subset_status.get("sha256")
    proof_source_sha256 = proof.get("construction_subset_source_sha256")
    if source_sha256:
        if not proof_source_sha256:
            reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_SOURCE_SHA256_MISSING")
        elif proof_source_sha256 != source_sha256:
            reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_SOURCE_SHA256_MISMATCH")
    identity_hash_set = construction_subset_status.get("identity_hash_set_sha256")
    proof_identity_hash_set = proof.get("construction_subset_identity_hash_set_sha256")
    if identity_hash_set:
        if not proof_identity_hash_set:
            reasons.append(
                "HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_HASH_SET_SHA256_MISSING"
            )
        elif proof_identity_hash_set != identity_hash_set:
            reasons.append(
                "HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_HASH_SET_SHA256_MISMATCH"
            )
    holdout_identity_hash_set = window_hashes.get("source_row_identity_hash_set_sha256")
    proof_holdout_identity_hash_set = proof.get(
        "holdout_source_row_identity_hash_set_sha256"
    )
    if holdout_identity_hash_set:
        if not proof_holdout_identity_hash_set:
            reasons.append("HOLDOUT_CONSTRUCTION_PROOF_HOLDOUT_HASH_SET_MISSING")
        elif proof_holdout_identity_hash_set != holdout_identity_hash_set:
            reasons.append("HOLDOUT_CONSTRUCTION_PROOF_HOLDOUT_HASH_SET_MISMATCH")
    overlap_count = proof.get("overlap_identity_hash_count")
    if overlap_count is None:
        reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_OVERLAP_COUNT_MISSING")
    else:
        parsed_overlap_count = status_module._coerce_float(overlap_count)
        if parsed_overlap_count is None:
            reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_OVERLAP_COUNT_MALFORMED")
        elif int(parsed_overlap_count) != 0:
            reasons.append("HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_OVERLAP")
    return reasons


def _construction_subset_identity_proof_summary(
    proof: dict[str, Any],
    *,
    construction_subset_status: dict[str, Any],
    window_hashes: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": proof.get("status"),
        "required_status": CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS,
        "construction_subset_identity_source_status": construction_subset_status.get(
            "status"
        ),
        "construction_subset_full_identity_set_available": (
            construction_subset_status.get("full_identity_set_available") is True
        ),
        "construction_subset_candidate_count": construction_subset_status.get(
            "candidate_count"
        ),
        "construction_subset_identity_hash_count": construction_subset_status.get(
            "identity_hash_count"
        ),
        "proof_construction_subset_source_sha256": proof.get(
            "construction_subset_source_sha256"
        ),
        "construction_subset_source_sha256": construction_subset_status.get("sha256"),
        "construction_subset_source_sha256_matches": (
            proof.get("construction_subset_source_sha256")
            == construction_subset_status.get("sha256")
            if proof.get("construction_subset_source_sha256") not in {None, ""}
            and construction_subset_status.get("sha256") not in {None, ""}
            else None
        ),
        "proof_construction_subset_identity_hash_set_sha256": proof.get(
            "construction_subset_identity_hash_set_sha256"
        ),
        "construction_subset_identity_hash_set_sha256": construction_subset_status.get(
            "identity_hash_set_sha256"
        ),
        "construction_subset_identity_hash_set_matches": (
            proof.get("construction_subset_identity_hash_set_sha256")
            == construction_subset_status.get("identity_hash_set_sha256")
            if proof.get("construction_subset_identity_hash_set_sha256")
            not in {None, ""}
            and construction_subset_status.get("identity_hash_set_sha256")
            not in {None, ""}
            else None
        ),
        "proof_holdout_source_row_identity_hash_set_sha256": proof.get(
            "holdout_source_row_identity_hash_set_sha256"
        ),
        "holdout_source_row_identity_hash_set_sha256": window_hashes.get(
            "source_row_identity_hash_set_sha256"
        ),
        "holdout_source_row_identity_hash_set_matches": (
            proof.get("holdout_source_row_identity_hash_set_sha256")
            == window_hashes.get("source_row_identity_hash_set_sha256")
            if proof.get("holdout_source_row_identity_hash_set_sha256")
            not in {None, ""}
            and window_hashes.get("source_row_identity_hash_set_sha256")
            not in {None, ""}
            else None
        ),
        "overlap_identity_hash_count": proof.get("overlap_identity_hash_count"),
        "overlap_identity_hash_sample": (
            proof.get("overlap_identity_hash_sample")
            if isinstance(proof.get("overlap_identity_hash_sample"), list)
            else []
        ),
    }


def _candidate_identity_alias_index(
    rows_by_identity: dict[str, dict[str, Any]],
    *,
    scope: str,
) -> dict[str, str]:
    index: dict[str, str] = {}
    for identity, row in rows_by_identity.items():
        index[identity] = identity
        for alias_identity in _candidate_identity_aliases(row, scope=scope):
            index.setdefault(alias_identity, identity)
    return index


def _resolve_candidate_identity(
    row: dict[str, Any],
    *,
    scope: str,
    alias_index: dict[str, str],
) -> str:
    primary = _candidate_identity(row, scope=scope)
    if primary in alias_index:
        return alias_index[primary]
    for alias_identity in _candidate_identity_aliases(row, scope=scope):
        if alias_identity in alias_index:
            return alias_index[alias_identity]
    return primary


def _without_outcome_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in OUTCOME_FIELDS}


def _setdefault_first(row: dict[str, Any], field: str, *values: Any) -> None:
    if row.get(field) not in {None, ""}:
        return
    value = status_module._first_present(*values)
    if value not in {None, ""}:
        row[field] = value


def _setdefault_first_with_audit(
    row: dict[str, Any],
    field: str,
    *sources: tuple[str, Any],
) -> None:
    if row.get(field) not in {None, ""}:
        return
    for source_field, value in sources:
        if value in {None, ""}:
            continue
        row[field] = value
        aliases = row.setdefault("_producer_normalized_accounting_aliases", [])
        if isinstance(aliases, list):
            aliases.append({
                "target_field": field,
                "source_field": source_field,
                "normalization": "decision_time_accounting_alias",
            })
        return


def _selector_context_scalar(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        values = [
            str(item).strip()
            for item in value
            if item not in {None, ""} and str(item).strip()
        ]
        return ",".join(values) if values else None
    if value in {None, ""}:
        return None
    text = str(value).strip()
    return text or None


def _setdefault_first_selector_context_with_audit(
    row: dict[str, Any],
    field: str,
    *,
    target_guards: tuple[str, ...],
    sources: tuple[tuple[str, Any], ...],
) -> None:
    if any(_present(row.get(target_field)) for target_field in target_guards):
        return
    for source_field, value in sources:
        normalized_value = _selector_context_scalar(value)
        if normalized_value is None:
            continue
        row[field] = normalized_value
        aliases = row.setdefault("_producer_normalized_selector_context_aliases", [])
        if isinstance(aliases, list):
            aliases.append({
                "target_field": field,
                "source_field": source_field,
                "normalization": "decision_time_selector_context_alias",
            })
        return


def _setdefault_first_selector_field_with_audit(
    row: dict[str, Any],
    field: str,
    *,
    target_guards: tuple[str, ...],
    sources: tuple[tuple[str, Any], ...],
) -> None:
    if any(_present(row.get(target_field)) for target_field in target_guards):
        return
    for source_field, value in sources:
        if not _present(value):
            continue
        row[field] = value
        aliases = row.setdefault("_producer_normalized_selector_context_aliases", [])
        if isinstance(aliases, list):
            aliases.append({
                "target_field": field,
                "source_field": source_field,
                "normalization": "decision_time_selector_field_alias",
            })
        return


def _nested_mapping(row: dict[str, Any], field: str) -> dict[str, Any]:
    value = row.get(field)
    return value if isinstance(value, dict) else {}


def _normalize_realtime_accounting_aliases(row: dict[str, Any]) -> None:
    market_snapshot = _nested_mapping(row, "market_snapshot")
    adaptive_allocation = _nested_mapping(row, "adaptive_allocation")
    _setdefault_first_with_audit(
        row,
        "gross_notional_usd",
        ("notional_usdt", row.get("notional_usdt")),
        ("notional", row.get("notional")),
        ("adaptive_allocation.gross_notional_usd", adaptive_allocation.get("gross_notional_usd")),
        ("adaptive_allocation.target_notional_usdt", adaptive_allocation.get("target_notional_usdt")),
    )
    _setdefault_first_with_audit(
        row,
        "allocated_margin_usd",
        ("margin_usdt", row.get("margin_usdt")),
        ("margin_usd", row.get("margin_usd")),
        ("initial_margin_usdt", row.get("initial_margin_usdt")),
        ("initial_margin_usd", row.get("initial_margin_usd")),
        ("adaptive_allocation.allocated_margin_usd", adaptive_allocation.get("allocated_margin_usd")),
    )
    _setdefault_first_with_audit(
        row,
        "take_profit_price",
        ("take_profit_reference", row.get("take_profit_reference")),
        ("price_target_after_cost", row.get("price_target_after_cost")),
        ("price_target", row.get("price_target")),
        ("price_target_high", row.get("price_target_high")),
        ("adaptive_allocation.take_profit_price", adaptive_allocation.get("take_profit_price")),
    )
    _setdefault_first_with_audit(
        row,
        "recommended_margin_mode",
        ("margin_mode_simulated", row.get("margin_mode_simulated")),
        ("adaptive_allocation.recommended_margin_mode", adaptive_allocation.get("recommended_margin_mode")),
    )
    _setdefault_first_with_audit(
        row,
        "entry_spread_bps",
        ("observed_bid_ask_spread_bps", row.get("observed_bid_ask_spread_bps")),
        ("bid_ask_spread_bps", row.get("bid_ask_spread_bps")),
        ("upstream_reported_spread_bps", row.get("upstream_reported_spread_bps")),
        ("market_snapshot.spread_bps", market_snapshot.get("spread_bps")),
    )
    _setdefault_first_with_audit(
        row,
        "fee_bps",
        ("market_snapshot.fee_bps", market_snapshot.get("fee_bps")),
        ("market_snapshot.default_fee_bps_visible", market_snapshot.get("default_fee_bps_visible")),
    )
    _setdefault_first_with_audit(
        row,
        "fee_usd",
        ("fee_usdt", row.get("fee_usdt")),
    )
    if str(row.get("hedge_state") or row.get("hedge_reason") or "").upper() in {
        "NO_HEDGE",
        "NO_HEDGE_CONTEXT",
    }:
        _setdefault_first_with_audit(
            row,
            "hedge_enabled",
            ("hedge_state", False),
        )


def _normalize_realtime_selector_context_aliases(row: dict[str, Any]) -> None:
    _setdefault_first_selector_field_with_audit(
        row,
        "timeframe",
        target_guards=("timeframe",),
        sources=(
            ("source_redis_timeframe", row.get("source_redis_timeframe")),
            ("path_telemetry_candle_timeframe", row.get("path_telemetry_candle_timeframe")),
        ),
    )
    _setdefault_first_selector_field_with_audit(
        row,
        "expected_move_after_cost_bps",
        target_guards=(
            "expected_move_after_cost_bps",
            "expected_net_edge_bps",
        ),
        sources=(
            (
                "paper_allocation_signed_expected_move_after_cost_bps",
                row.get("paper_allocation_signed_expected_move_after_cost_bps"),
            ),
        ),
    )
    _setdefault_first_selector_context_with_audit(
        row,
        "regime_label",
        target_guards=(
            "market_regime",
            "regime",
            "regime_label",
            "market_state",
            "strategy_mode",
        ),
        sources=(
            ("market_regime_at_entry", row.get("market_regime_at_entry")),
            ("strategy_regime_labels", row.get("strategy_regime_labels")),
            ("strategy_router_regime_labels", row.get("strategy_router_regime_labels")),
            ("regime_labels", row.get("regime_labels")),
            ("market_regime_labels", row.get("market_regime_labels")),
        ),
    )
    _setdefault_first_selector_context_with_audit(
        row,
        "source_strategy",
        target_guards=(
            "strategy",
            "strategy_family",
            "signal_strategy",
            "model_strategy",
            "source_strategy",
            "capital_allocation_reason",
        ),
        sources=(
            ("strategy_router_selected_mode", row.get("strategy_router_selected_mode")),
            ("strategy_selected_mode", row.get("strategy_selected_mode")),
        ),
    )


def _has_realtime_outcome(row: dict[str, Any]) -> bool:
    return (
        status_module._outcome_after_cost_bps(row) is not None
        or status_module._trade_outcome_pnl(row) is not None
    )


def _row_with_outcome_fields(
    selection_row: dict[str, Any],
    outcome_row: dict[str, Any],
) -> dict[str, Any]:
    combined = dict(selection_row)
    for field in OUTCOME_FIELDS:
        if field in outcome_row:
            combined[field] = outcome_row[field]
    return combined


def _normalize_realtime_source_row(
    row: dict[str, Any],
    *,
    source_kind: str,
    source_label: str,
) -> dict[str, Any]:
    normalized = dict(row)
    normalized.setdefault("_producer_source_kind", source_kind)
    normalized.setdefault("_producer_source_path", source_label)
    _setdefault_first(
        normalized,
        "decision_time",
        normalized.get("decision_time"),
        normalized.get("entry_feature_decision_time"),
        normalized.get("strategy_decision_time"),
        normalized.get("entry_price_utc"),
        normalized.get("generated_at"),
        normalized.get("generated_utc"),
    )
    _setdefault_first(
        normalized,
        "generated_at",
        normalized.get("generated_at"),
        normalized.get("entry_feature_generated_at"),
        normalized.get("generated_utc"),
    )
    _setdefault_first(
        normalized,
        "available_at",
        normalized.get("available_at"),
        normalized.get("entry_feature_available_at"),
    )
    _setdefault_first(
        normalized,
        "feature_cutoff",
        normalized.get("feature_cutoff"),
        normalized.get("entry_feature_cutoff"),
        normalized.get("strategy_feature_cutoff"),
    )
    _normalize_realtime_accounting_aliases(normalized)
    _normalize_realtime_selector_context_aliases(normalized)
    return normalized


def _eligible_bucket_keys(bucket_matrix_path: Path) -> set[tuple[str, ...]]:
    matrix = _load_json(bucket_matrix_path)
    if not isinstance(matrix, dict):
        return set()
    return status_module._eligible_bucket_keys_from_matrix(matrix)


def _is_pre_guardian_a_grade_halted(row: dict[str, Any]) -> bool:
    current_tier = str(
        status_module._first_present(
            row.get("candidate_selection_tier"),
            row.get("paper_opportunity_tier"),
            row.get("explicit_paper_opportunity_tier"),
            row.get("admission_tier"),
            row.get("candidate_tier"),
        )
        or ""
    ).strip().upper()
    pre_guardian_tier = str(row.get("pre_guardian_paper_opportunity_tier") or "").strip().upper()
    tier_reason = str(row.get("paper_opportunity_tier_reason") or "").strip().upper()
    fill_source = str(row.get("paper_fill_allowed_source") or "").strip().upper()
    forced_shadow = row.get("continuous_edge_guardian_forced_shadow_only") is True
    return (
        current_tier == "SHADOW_ONLY"
        and pre_guardian_tier == "A_GRADE_EXECUTION_PAPER"
        and (
            forced_shadow
            or tier_reason == "CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED"
            or fill_source == "CONTINUOUS_EDGE_GUARDIAN_BLOCKED_NEW_A_GRADE_ENTRIES"
        )
    )


def _selector_reject_reasons(
    row: dict[str, Any],
    *,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> list[str]:
    reasons: list[str] = []
    key = tuple(str(value) for value in status_module._a_grade_bucket_key(row))
    edge = status_module._expected_edge_bps(row)
    side = status_module._directional_side(row)
    source_tier = status_module._first_present(
        row.get("candidate_selection_tier"),
        row.get("paper_opportunity_tier"),
        row.get("explicit_paper_opportunity_tier"),
        row.get("admission_tier"),
        row.get("candidate_tier"),
    )
    if key not in eligible_bucket_keys:
        reasons.append("DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE")
    if source_tier != "A_GRADE_EXECUTION_PAPER":
        if _is_pre_guardian_a_grade_halted(row):
            reasons.append("A_GRADE_HALTED_BY_CONTINUOUS_EDGE_GUARDIAN")
        else:
            reasons.append("SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING")
    if edge is None or edge <= 0.0:
        reasons.append("NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE")
    if side not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_SIDE")
    if status_module._allocator_decision(row).startswith("BLOCK_"):
        reasons.append("ALLOCATOR_BLOCKED_CANDIDATE")
    reasons.extend(status_module._pre_submit_temporal_reasons(row))
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    return sorted(set(reasons))


def _accounting_reject_reasons(row: dict[str, Any]) -> list[str]:
    coverage = status_module._accelerated_replay_simulation_accounting_coverage([row])
    if coverage.get("status") == "PASSED":
        return []
    missing = coverage.get("missing_field_group_counts") or {}
    return [f"MISSING_ACCOUNTING_{key.upper()}" for key in sorted(missing)]


def _fingerprint_reject_reasons(row: dict[str, Any], *, expected_fingerprint: str) -> list[str]:
    source_fingerprint = status_module._first_present(
        row.get("selector_policy_fingerprint"),
        row.get("frozen_selector_fingerprint"),
        row.get("policy_fingerprint"),
    )
    source_fingerprint = str(source_fingerprint) if source_fingerprint not in {None, ""} else ""
    if not source_fingerprint:
        return ["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISSING"]
    if source_fingerprint != expected_fingerprint:
        return ["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISMATCH"]
    return []


def _realtime_pending_source_freshness_policy() -> dict[str, Any]:
    return {
        "timestamp_fields": list(REALTIME_PENDING_SOURCE_TIMESTAMP_FIELDS),
        "maximum_source_age_seconds": MAX_REALTIME_PENDING_SOURCE_AGE_SECONDS,
        "maximum_clock_skew_seconds": MAX_REALTIME_PENDING_SOURCE_CLOCK_SKEW_SECONDS,
        "applies_to": "new_realtime_pending_candidates_only",
    }


def _latest_realtime_source_timestamp(row: dict[str, Any]) -> datetime | None:
    timestamps = [
        parsed
        for field in REALTIME_PENDING_SOURCE_TIMESTAMP_FIELDS
        for parsed in [status_module._parse_utc(row.get(field))]
        if parsed is not None
    ]
    if not timestamps:
        return None
    return max(timestamps)


def _realtime_pending_source_age_seconds(
    row: dict[str, Any],
    *,
    generated_utc: str,
) -> float | None:
    generated_at = status_module._parse_utc(generated_utc)
    source_timestamp = _latest_realtime_source_timestamp(row)
    if generated_at is None or source_timestamp is None:
        return None
    return (generated_at - source_timestamp).total_seconds()


def _post_outcome_selection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("candidate_selected_before_outcome") is False or row.get("selected_before_outcome") is False:
        reasons.append("CANDIDATE_SELECTION_MARKED_AFTER_OUTCOME")
    selected_at = status_module._parse_utc(row.get("candidate_selected_at") or row.get("selected_at"))
    outcome_at = status_module._parse_utc(
        status_module._first_present(row.get("future_label_close_time"), row.get("closed_at"), row.get("exit_time"))
    )
    if selected_at is not None and outcome_at is not None and selected_at >= outcome_at:
        reasons.append("CANDIDATE_SELECTED_AT_OR_AFTER_OUTCOME_TIME")
    return reasons


def _empty_holdout_registry_for_source(
    *,
    source_path: Path,
    generated_utc: str,
) -> dict[str, Any]:
    rows, source_status = _iter_jsonl(source_path)
    symbols = sorted({status_module._normalized_symbol(row) for row in rows if status_module._normalized_symbol(row) != "UNKNOWN"})
    timeframes = sorted({
        str(status_module._row_value(row, "timeframe") or row.get("timeframe"))
        for row in rows
        if status_module._row_value(row, "timeframe") or row.get("timeframe")
    })
    decisions = [
        status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
        for row in rows
    ]
    decisions = [value for value in decisions if value is not None]
    registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "NO_ELIGIBLE_HOLDOUT_WINDOWS_REGISTERED",
        "selector_policy_fingerprint": EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "source_path": str(source_path),
        "source_sha256": source_status.get("sha256"),
        "source_row_count": len(rows),
        "registered_window_count": 0,
        "source_symbols_sample": symbols[:100],
        "source_symbol_count": len(symbols),
        "source_timeframes": timeframes,
        "source_decision_time_min": (
            min(decisions).isoformat().replace("+00:00", "Z") if decisions else None
        ),
        "source_decision_time_max": (
            max(decisions).isoformat().replace("+00:00", "Z") if decisions else None
        ),
        "windows": [],
        "exclusion_proof": {
            "status": "SOURCE_EXCLUDED_FROM_HOLDOUT_BY_DEFAULT",
            "reason": (
                "The available closed-candle replay source is the accelerated replay "
                "coverage source used by the adaptive-capital replay gate; no window is "
                "countable until explicitly pre-registered with untouched-data proof."
            ),
        },
    }
    return registry


def _empty_holdout_registry_can_refresh(registry: dict[str, Any]) -> bool:
    windows = [window for window in registry.get("windows") or [] if isinstance(window, dict)]
    if windows:
        return False
    return str(registry.get("status") or "") in {
        "NO_ELIGIBLE_HOLDOUT_WINDOWS_REGISTERED",
        "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF",
    }


def _load_holdout_registry(
    *,
    registry_path: Path,
    source_path: Path,
    generated_utc: str,
) -> dict[str, Any]:
    registry = _load_json(registry_path)
    if isinstance(registry, dict):
        source_sha256 = _file_sha256(source_path)
        if (
            _empty_holdout_registry_can_refresh(registry)
            and (
                str(registry.get("source_path") or "") != str(source_path)
                or registry.get("source_sha256") != source_sha256
            )
        ):
            registry = _empty_holdout_registry_for_source(
                source_path=source_path,
                generated_utc=generated_utc,
            )
            _write_json(registry_path, registry)
        return registry
    registry = _empty_holdout_registry_for_source(
        source_path=source_path,
        generated_utc=generated_utc,
    )
    _write_json(registry_path, registry)
    return registry


def _row_overlap_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("used_for_dynamic_a_grade_bucket_construction") is True:
        reasons.append("HOLDOUT_OVERLAPS_DYNAMIC_BUCKET_CONSTRUCTION")
    if row.get("used_for_229_candidate_subset") is True:
        reasons.append("HOLDOUT_OVERLAPS_229_CANDIDATE_SUBSET")
    if row.get("selector_training_window_overlap") is True:
        reasons.append("HOLDOUT_OVERLAPS_SELECTOR_TRAINING_WINDOW")
    return reasons


def _construction_subset_row_overlap_reasons(
    row: dict[str, Any],
    construction_subset_status: dict[str, Any],
) -> list[str]:
    identity_hashes = construction_subset_status.get("identity_hashes")
    if not isinstance(identity_hashes, list) or not identity_hashes:
        return []
    construction_hashes = {str(value) for value in identity_hashes}
    row_hashes = {_sha256_text(alias) for alias in _row_identity_alias_values(row)}
    if construction_hashes & row_hashes:
        return ["HOLDOUT_OVERLAPS_229_CANDIDATE_CONSTRUCTION_IDENTITY"]
    return []


def _utc_format(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _identity_hash_summary(identity_hashes: list[str]) -> dict[str, Any]:
    sorted_hashes = sorted(str(value) for value in identity_hashes)
    return {
        "hash_algorithm": "sha256(stable_json(sorted_identity_hashes))",
        "identity_hash_count": len(sorted_hashes),
        "unique_identity_hash_count": len(set(sorted_hashes)),
        "identity_hash_set_sha256": _sha256_payload(sorted_hashes),
    }


def _holdout_window_hashes(
    *,
    window_id: str,
    start_decision_time: str | None,
    end_decision_time: str | None,
    symbols: list[str],
    timeframes: list[str],
    source_row_identity_hashes: list[str],
    decision_time_ready_row_identity_hashes: list[str],
    source_sha256: str | None,
) -> dict[str, Any]:
    source_summary = _identity_hash_summary(source_row_identity_hashes)
    ready_summary = _identity_hash_summary(decision_time_ready_row_identity_hashes)
    metadata_payload = {
        "window_id": window_id,
        "start_decision_time": start_decision_time,
        "end_decision_time": end_decision_time,
        "symbols": sorted(symbols),
        "timeframes": sorted(timeframes),
        "source_sha256": source_sha256,
        "source_row_identity_hash_set_sha256": source_summary["identity_hash_set_sha256"],
        "decision_time_ready_identity_hash_set_sha256": ready_summary["identity_hash_set_sha256"],
    }
    return {
        "hash_algorithm": "sha256(stable_json(payload))",
        "source_sha256": source_sha256,
        "window_metadata_sha256": _sha256_payload(metadata_payload),
        "source_row_identity_hash_count": source_summary["identity_hash_count"],
        "source_row_unique_identity_hash_count": source_summary["unique_identity_hash_count"],
        "source_row_identity_hash_set_sha256": source_summary["identity_hash_set_sha256"],
        "decision_time_ready_identity_hash_count": ready_summary["identity_hash_count"],
        "decision_time_ready_unique_identity_hash_count": ready_summary[
            "unique_identity_hash_count"
        ],
        "decision_time_ready_identity_hash_set_sha256": ready_summary[
            "identity_hash_set_sha256"
        ],
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_window_hash": [],
    }


def _registered_source_row_identity_hashes(window: dict[str, Any]) -> set[str]:
    for field in (
        "registered_source_row_identity_hashes",
        "source_row_identity_hashes",
    ):
        values = window.get(field)
        if isinstance(values, list):
            hashes = {
                str(value)
                for value in values
                if value not in {None, ""}
            }
            if hashes:
                return hashes
    return set()


def _holdout_window_candidate_audit(
    *,
    source_path: Path,
    source_status: dict[str, Any],
    source_rows: list[dict[str, Any]],
    registry: dict[str, Any],
    construction_subset_status: dict[str, Any],
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    generated_utc: str,
) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    missing_decision_time_count = 0
    for row in source_rows:
        decision = status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
        if decision is None:
            missing_decision_time_count += 1
            continue
        window_key = decision.astimezone(timezone.utc).date().isoformat()
        bucket = buckets.setdefault(
            window_key,
            {
                "decision_times": [],
                "symbols": set(),
                "timeframes": set(),
                "side_counts": {},
                "overlap_flag_counts": {
                    "used_for_dynamic_a_grade_bucket_construction": 0,
                    "used_for_229_candidate_subset": 0,
                    "selector_training_window_overlap": 0,
                },
                "source_row_identity_hashes": [],
                "source_row_identity_hash_sample": [],
                "decision_time_candidate_ready_count": 0,
                "decision_time_ready_side_counts": {},
                "decision_time_reject_reason_counts": {},
                "decision_time_ready_row_identity_hashes": [],
                "decision_time_ready_row_identity_hash_sample": [],
                "decision_time_ready_no_construction_overlap_count": 0,
                "decision_time_ready_no_construction_overlap_side_counts": {},
                "decision_time_ready_no_construction_overlap_symbols": set(),
                "decision_time_ready_no_construction_overlap_timeframes": set(),
                "decision_time_ready_no_construction_overlap_decision_times": [],
                "decision_time_ready_no_construction_overlap_row_identity_hashes": [],
                "decision_time_ready_no_construction_overlap_row_identity_hash_sample": [],
                "decision_time_ready_construction_overlap_count": 0,
                "decision_time_ready_construction_overlap_row_identity_hashes": [],
                "decision_time_ready_construction_overlap_row_identity_hash_sample": [],
                "source_row_count": 0,
            },
        )
        bucket["decision_times"].append(decision)
        symbol = status_module._normalized_symbol(row)
        if symbol != "UNKNOWN":
            bucket["symbols"].add(symbol)
        timeframe = status_module._row_value(row, "timeframe") or row.get("timeframe")
        if timeframe not in {None, ""}:
            bucket["timeframes"].add(str(timeframe))
        side = status_module._directional_side(row) or "unknown"
        bucket["side_counts"][side] = bucket["side_counts"].get(side, 0) + 1
        for field in bucket["overlap_flag_counts"]:
            if row.get(field) is True:
                bucket["overlap_flag_counts"][field] += 1
        row_identity_hash = _row_identity_hash(row)
        bucket["source_row_identity_hashes"].append(row_identity_hash)
        if len(bucket["source_row_identity_hash_sample"]) < 20:
            bucket["source_row_identity_hash_sample"].append(row_identity_hash)
        row_reasons = _decision_time_holdout_reject_reasons(
            row,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_bucket_keys,
        )
        if row_reasons:
            for reason in row_reasons:
                reason_counts = bucket["decision_time_reject_reason_counts"]
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        else:
            bucket["decision_time_candidate_ready_count"] += 1
            ready_side_counts = bucket["decision_time_ready_side_counts"]
            ready_side_counts[side] = ready_side_counts.get(side, 0) + 1
            if len(bucket["decision_time_ready_row_identity_hash_sample"]) < 20:
                bucket["decision_time_ready_row_identity_hash_sample"].append(
                    row_identity_hash
                )
            bucket["decision_time_ready_row_identity_hashes"].append(row_identity_hash)
            construction_overlap_reasons = _construction_subset_row_overlap_reasons(
                row,
                construction_subset_status,
            )
            if construction_overlap_reasons:
                bucket["decision_time_ready_construction_overlap_count"] += 1
                bucket["decision_time_ready_construction_overlap_row_identity_hashes"].append(
                    row_identity_hash
                )
                if len(
                    bucket[
                        "decision_time_ready_construction_overlap_row_identity_hash_sample"
                    ]
                ) < 20:
                    bucket[
                        "decision_time_ready_construction_overlap_row_identity_hash_sample"
                    ].append(row_identity_hash)
            else:
                bucket["decision_time_ready_no_construction_overlap_count"] += 1
                no_overlap_side_counts = bucket[
                    "decision_time_ready_no_construction_overlap_side_counts"
                ]
                no_overlap_side_counts[side] = no_overlap_side_counts.get(side, 0) + 1
                if symbol != "UNKNOWN":
                    bucket[
                        "decision_time_ready_no_construction_overlap_symbols"
                    ].add(symbol)
                if timeframe not in {None, ""}:
                    bucket[
                        "decision_time_ready_no_construction_overlap_timeframes"
                    ].add(str(timeframe))
                bucket[
                    "decision_time_ready_no_construction_overlap_decision_times"
                ].append(decision)
                bucket[
                    "decision_time_ready_no_construction_overlap_row_identity_hashes"
                ].append(row_identity_hash)
                if len(
                    bucket[
                        "decision_time_ready_no_construction_overlap_row_identity_hash_sample"
                    ]
                ) < 20:
                    bucket[
                        "decision_time_ready_no_construction_overlap_row_identity_hash_sample"
                    ].append(row_identity_hash)
        bucket["source_row_count"] += 1

    source_sha256 = source_status.get("sha256")
    windows: list[dict[str, Any]] = []
    for window_key in sorted(buckets):
        bucket = buckets[window_key]
        decision_times = bucket["decision_times"]
        symbols = sorted(bucket["symbols"])
        timeframes = sorted(bucket["timeframes"])
        start = _utc_format(min(decision_times))
        end = _utc_format(max(decision_times))
        window_id = f"draft_holdout_decision_date_{window_key}"
        overlap_counts = dict(bucket["overlap_flag_counts"])
        window_hashes = _holdout_window_hashes(
            window_id=window_id,
            start_decision_time=start,
            end_decision_time=end,
            symbols=symbols,
            timeframes=timeframes,
            source_row_identity_hashes=bucket["source_row_identity_hashes"],
            decision_time_ready_row_identity_hashes=bucket[
                "decision_time_ready_row_identity_hashes"
            ],
            source_sha256=source_sha256,
        )
        draft_window = {
            "window_id": window_id,
            "start_decision_time": start,
            "end_decision_time": end,
            "symbols": symbols,
            "timeframes": timeframes,
            "window_hashes": window_hashes,
            "eligible_for_holdout": False,
            "exclusion_proof": {
                "status": "REQUIRES_PASSED_UNTOUCHED_PROOF",
                "source_sha256": source_sha256,
                "window_metadata_sha256": window_hashes["window_metadata_sha256"],
                "source_row_identity_hash_set_sha256": window_hashes[
                    "source_row_identity_hash_set_sha256"
                ],
                "construction_subset_identity_proof": (
                    _construction_subset_identity_proof_template(
                        construction_subset_status=construction_subset_status,
                        window_hashes=window_hashes,
                        source_row_identity_hashes=bucket["source_row_identity_hashes"],
                    )
                ),
                "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
            },
        }
        clean_ready_hashes = list(
            bucket["decision_time_ready_no_construction_overlap_row_identity_hashes"]
        )
        clean_registry_window = None
        if clean_ready_hashes:
            clean_decision_times = bucket[
                "decision_time_ready_no_construction_overlap_decision_times"
            ]
            clean_symbols = sorted(
                bucket["decision_time_ready_no_construction_overlap_symbols"]
            )
            clean_timeframes = sorted(
                bucket["decision_time_ready_no_construction_overlap_timeframes"]
            )
            clean_start = _utc_format(min(clean_decision_times))
            clean_end = _utc_format(max(clean_decision_times))
            clean_window_id = f"{window_id}_clean_a_grade_no_229_overlap"
            clean_window_hashes = _holdout_window_hashes(
                window_id=clean_window_id,
                start_decision_time=clean_start,
                end_decision_time=clean_end,
                symbols=clean_symbols,
                timeframes=clean_timeframes,
                source_row_identity_hashes=clean_ready_hashes,
                decision_time_ready_row_identity_hashes=clean_ready_hashes,
                source_sha256=source_sha256,
            )
            clean_registry_window = {
                "window_id": clean_window_id,
                "start_decision_time": clean_start,
                "end_decision_time": clean_end,
                "symbols": clean_symbols,
                "timeframes": clean_timeframes,
                "row_identity_filter_mode": (
                    "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES"
                ),
                "registered_source_row_identity_hash_count": len(clean_ready_hashes),
                "registered_source_row_identity_hash_sample": clean_ready_hashes[:20],
                "registered_source_row_identity_hashes": clean_ready_hashes,
                "window_hashes": clean_window_hashes,
                "eligible_for_holdout": False,
                "exclusion_proof": {
                    "status": "REQUIRES_PASSED_UNTOUCHED_PROOF",
                    "source_sha256": source_sha256,
                    "window_metadata_sha256": clean_window_hashes[
                        "window_metadata_sha256"
                    ],
                    "source_row_identity_hash_set_sha256": clean_window_hashes[
                        "source_row_identity_hash_set_sha256"
                    ],
                    "construction_subset_identity_proof": (
                        _construction_subset_identity_proof_template(
                            construction_subset_status=construction_subset_status,
                            window_hashes=clean_window_hashes,
                            source_row_identity_hashes=clean_ready_hashes,
                        )
                    ),
                    "required_attestations": list(
                        REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
                    ),
                },
            }
        windows.append({
            "window_id": window_id,
            "status": "DRAFT_NOT_COUNTABLE_REQUIRES_UNTOUCHED_EXCLUSION_PROOF",
            "start_decision_time": start,
            "end_decision_time": end,
            "source_row_count": bucket["source_row_count"],
            "symbol_count": len(symbols),
            "symbols_sample": symbols[:100],
            "timeframe_count": len(timeframes),
            "timeframes": timeframes,
            "side_counts": {
                key: bucket["side_counts"][key]
                for key in sorted(bucket["side_counts"])
            },
            "overlap_flag_counts": overlap_counts,
            "has_overlap_flags": any(count > 0 for count in overlap_counts.values()),
            "window_hashes": window_hashes,
            "decision_time_candidate_ready_count": bucket["decision_time_candidate_ready_count"],
            "decision_time_ready_side_counts": {
                key: bucket["decision_time_ready_side_counts"][key]
                for key in sorted(bucket["decision_time_ready_side_counts"])
            },
            "decision_time_reject_reason_counts": {
                key: bucket["decision_time_reject_reason_counts"][key]
                for key in sorted(bucket["decision_time_reject_reason_counts"])
            },
            "source_row_identity_hash_sample": bucket["source_row_identity_hash_sample"],
            "decision_time_ready_row_identity_hash_sample": (
                bucket["decision_time_ready_row_identity_hash_sample"]
            ),
            "decision_time_ready_no_construction_overlap_count": bucket[
                "decision_time_ready_no_construction_overlap_count"
            ],
            "decision_time_ready_no_construction_overlap_side_counts": {
                key: bucket["decision_time_ready_no_construction_overlap_side_counts"][key]
                for key in sorted(
                    bucket["decision_time_ready_no_construction_overlap_side_counts"]
                )
            },
            "decision_time_ready_no_construction_overlap_row_identity_hash_sample": (
                bucket[
                    "decision_time_ready_no_construction_overlap_row_identity_hash_sample"
                ]
            ),
            "decision_time_ready_construction_overlap_count": bucket[
                "decision_time_ready_construction_overlap_count"
            ],
            "decision_time_ready_construction_overlap_row_identity_hash_sample": (
                bucket[
                    "decision_time_ready_construction_overlap_row_identity_hash_sample"
                ]
            ),
            "suggested_registry_window": draft_window,
            "clean_no_overlap_registry_window_template": clean_registry_window,
        })

    registered_windows = [window for window in registry.get("windows") or [] if isinstance(window, dict)]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": (
            "DRAFT_HOLDOUT_WINDOW_CANDIDATES_NOT_COUNTABLE"
            if windows
            else "NO_DRAFT_HOLDOUT_WINDOW_CANDIDATES"
        ),
        "selector_policy_fingerprint": expected_fingerprint,
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "construction_subset_identity_source_status": construction_subset_status,
        "construction_subset_identity_proof_required": True,
        "construction_subset_identity_proof_required_status": (
            CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
        ),
        "source_status": source_status,
        "source_row_count": len(source_rows),
        "missing_decision_time_count": missing_decision_time_count,
        "draft_window_count": len(windows),
        "registered_window_count": len(registered_windows),
        "window_partition": "UTC_DECISION_DATE",
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_window_selection": [],
        "readiness_uses_outcome_fields": False,
        "outcome_fields_used_for_readiness": [],
        "outcome_fields_excluded_from_window_selection": sorted(OUTCOME_FIELDS),
        "draft_windows_are_countable": False,
        "promotion_requires_exclusion_proof_status": "PASSED_UNTOUCHED",
        "promotion_requires_source_sha256_match": True,
        "promotion_required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        "source_reuse_warning": (
            "Draft windows are derived from the current holdout source metadata only. "
            "They must remain non-countable unless an independent untouched-data proof "
            "shows the window did not contribute to development, bucket construction, "
            "strategy or allocator calibration, or the 229-candidate replay subset."
        ),
        "windows": windows,
    }


def _holdout_window_promotion_packet(
    *,
    candidate_audit: dict[str, Any],
    registry_path: Path,
    expected_fingerprint: str,
    generated_utc: str,
) -> dict[str, Any]:
    source_sha256 = candidate_audit.get("source_sha256")
    source_path = candidate_audit.get("source_path")
    windows = [
        window
        for window in candidate_audit.get("windows") or []
        if isinstance(window, dict)
    ]
    draft_windows: list[dict[str, Any]] = []
    registry_windows: list[dict[str, Any]] = []
    clean_no_overlap_registry_windows: list[dict[str, Any]] = []
    draft_decision_time_candidate_ready_count = 0
    draft_decision_time_ready_overlap_with_229_count = 0
    draft_decision_time_ready_no_overlap_count = 0
    draft_decision_time_ready_row_level_no_overlap_count = 0
    draft_windows_with_decision_time_candidates = 0
    draft_windows_with_overlap_proof = 0
    draft_windows_with_no_overlap_proof = 0
    draft_windows_with_no_overlap_ready_candidates = 0
    draft_windows_with_row_level_no_overlap_ready_candidates = 0
    clean_no_overlap_registry_template_count = 0
    for window in windows:
        suggested = (
            dict(window.get("suggested_registry_window"))
            if isinstance(window.get("suggested_registry_window"), dict)
            else {}
        )
        proof = (
            dict(suggested.get("exclusion_proof"))
            if isinstance(suggested.get("exclusion_proof"), dict)
            else {}
        )
        window_hashes = (
            dict(suggested.get("window_hashes"))
            if isinstance(suggested.get("window_hashes"), dict)
            else dict(window.get("window_hashes"))
            if isinstance(window.get("window_hashes"), dict)
            else {}
        )
        proof.update({
            "status": "REQUIRES_PASSED_UNTOUCHED_PROOF",
            "source_sha256": source_sha256,
            "window_metadata_sha256": window_hashes.get("window_metadata_sha256"),
            "source_row_identity_hash_set_sha256": window_hashes.get(
                "source_row_identity_hash_set_sha256"
            ),
            "construction_subset_identity_proof": proof.get(
                "construction_subset_identity_proof"
            ),
            "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        })
        registry_window = {
            "window_id": suggested.get("window_id") or window.get("window_id"),
            "start_decision_time": suggested.get("start_decision_time") or window.get("start_decision_time"),
            "end_decision_time": suggested.get("end_decision_time") or window.get("end_decision_time"),
            "symbols": suggested.get("symbols") if isinstance(suggested.get("symbols"), list) else [],
            "timeframes": suggested.get("timeframes") if isinstance(suggested.get("timeframes"), list) else [],
            "window_hashes": window_hashes,
            "eligible_for_holdout": False,
            "exclusion_proof": proof,
        }
        construction_proof = (
            proof.get("construction_subset_identity_proof")
            if isinstance(proof.get("construction_subset_identity_proof"), dict)
            else {}
        )
        ready_count = int(window.get("decision_time_candidate_ready_count") or 0)
        overlap_count = int(construction_proof.get("overlap_identity_hash_count") or 0)
        proof_status = str(construction_proof.get("status") or "")
        no_overlap_proof = proof_status == CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
        overlap_proof = proof_status == "NO_GO_OVERLAPS_229_CONSTRUCTION_IDENTITIES"
        row_level_no_overlap_count = int(
            window.get("decision_time_ready_no_construction_overlap_count") or 0
        )
        draft_decision_time_candidate_ready_count += ready_count
        draft_decision_time_ready_overlap_with_229_count += min(ready_count, overlap_count)
        draft_decision_time_ready_row_level_no_overlap_count += row_level_no_overlap_count
        if ready_count > 0:
            draft_windows_with_decision_time_candidates += 1
        if row_level_no_overlap_count > 0:
            draft_windows_with_row_level_no_overlap_ready_candidates += 1
        if no_overlap_proof:
            draft_windows_with_no_overlap_proof += 1
            draft_decision_time_ready_no_overlap_count += ready_count
            if ready_count > 0:
                draft_windows_with_no_overlap_ready_candidates += 1
        if overlap_proof:
            draft_windows_with_overlap_proof += 1
        registry_windows.append(registry_window)
        clean_registry_window = None
        clean_suggested = (
            dict(window.get("clean_no_overlap_registry_window_template"))
            if isinstance(window.get("clean_no_overlap_registry_window_template"), dict)
            else {}
        )
        if clean_suggested:
            clean_proof = (
                dict(clean_suggested.get("exclusion_proof"))
                if isinstance(clean_suggested.get("exclusion_proof"), dict)
                else {}
            )
            clean_window_hashes = (
                dict(clean_suggested.get("window_hashes"))
                if isinstance(clean_suggested.get("window_hashes"), dict)
                else {}
            )
            clean_proof.update({
                "status": "REQUIRES_PASSED_UNTOUCHED_PROOF",
                "source_sha256": source_sha256,
                "window_metadata_sha256": clean_window_hashes.get(
                    "window_metadata_sha256"
                ),
                "source_row_identity_hash_set_sha256": clean_window_hashes.get(
                    "source_row_identity_hash_set_sha256"
                ),
                "construction_subset_identity_proof": clean_proof.get(
                    "construction_subset_identity_proof"
                ),
                "required_attestations": list(
                    REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
                ),
            })
            clean_registry_window = {
                "window_id": clean_suggested.get("window_id"),
                "start_decision_time": clean_suggested.get("start_decision_time"),
                "end_decision_time": clean_suggested.get("end_decision_time"),
                "symbols": (
                    clean_suggested.get("symbols")
                    if isinstance(clean_suggested.get("symbols"), list)
                    else []
                ),
                "timeframes": (
                    clean_suggested.get("timeframes")
                    if isinstance(clean_suggested.get("timeframes"), list)
                    else []
                ),
                "row_identity_filter_mode": clean_suggested.get(
                    "row_identity_filter_mode"
                ),
                "registered_source_row_identity_hash_count": clean_suggested.get(
                    "registered_source_row_identity_hash_count"
                ),
                "registered_source_row_identity_hash_sample": (
                    clean_suggested.get("registered_source_row_identity_hash_sample")
                    if isinstance(
                        clean_suggested.get(
                            "registered_source_row_identity_hash_sample"
                        ),
                        list,
                    )
                    else []
                ),
                "registered_source_row_identity_hashes": (
                    clean_suggested.get("registered_source_row_identity_hashes")
                    if isinstance(
                        clean_suggested.get("registered_source_row_identity_hashes"),
                        list,
                    )
                    else []
                ),
                "window_hashes": clean_window_hashes,
                "eligible_for_holdout": False,
                "exclusion_proof": clean_proof,
            }
            clean_no_overlap_registry_windows.append(clean_registry_window)
            clean_no_overlap_registry_template_count += 1
        draft_windows.append({
            "window_id": window.get("window_id"),
            "status": "PROMOTION_BLOCKED_AWAITING_UNTOUCHED_PROOF",
            "start_decision_time": window.get("start_decision_time"),
            "end_decision_time": window.get("end_decision_time"),
            "source_row_count": window.get("source_row_count"),
            "symbol_count": window.get("symbol_count"),
            "symbols_sample": window.get("symbols_sample") if isinstance(window.get("symbols_sample"), list) else [],
            "timeframe_count": window.get("timeframe_count"),
            "timeframes": window.get("timeframes") if isinstance(window.get("timeframes"), list) else [],
            "side_counts": window.get("side_counts") if isinstance(window.get("side_counts"), dict) else {},
            "decision_time_candidate_ready_count": window.get("decision_time_candidate_ready_count"),
            "decision_time_ready_side_counts": (
                window.get("decision_time_ready_side_counts")
                if isinstance(window.get("decision_time_ready_side_counts"), dict)
                else {}
            ),
            "decision_time_reject_reason_counts": (
                window.get("decision_time_reject_reason_counts")
                if isinstance(window.get("decision_time_reject_reason_counts"), dict)
                else {}
            ),
            "overlap_flag_counts": (
                window.get("overlap_flag_counts")
                if isinstance(window.get("overlap_flag_counts"), dict)
                else {}
            ),
            "has_overlap_flags": window.get("has_overlap_flags") is True,
            "window_hashes": window_hashes,
            "source_row_identity_hash_sample": (
                window.get("source_row_identity_hash_sample")
                if isinstance(window.get("source_row_identity_hash_sample"), list)
                else []
            ),
            "decision_time_ready_row_identity_hash_sample": (
                window.get("decision_time_ready_row_identity_hash_sample")
                if isinstance(window.get("decision_time_ready_row_identity_hash_sample"), list)
                else []
            ),
            "decision_time_ready_no_construction_overlap_count": (
                row_level_no_overlap_count
            ),
            "decision_time_ready_no_construction_overlap_side_counts": (
                window.get("decision_time_ready_no_construction_overlap_side_counts")
                if isinstance(
                    window.get(
                        "decision_time_ready_no_construction_overlap_side_counts"
                    ),
                    dict,
                )
                else {}
            ),
            "decision_time_ready_no_construction_overlap_row_identity_hash_sample": (
                window.get(
                    "decision_time_ready_no_construction_overlap_row_identity_hash_sample"
                )
                if isinstance(
                    window.get(
                        "decision_time_ready_no_construction_overlap_row_identity_hash_sample"
                    ),
                    list,
                )
                else []
            ),
            "decision_time_ready_construction_overlap_count": (
                window.get("decision_time_ready_construction_overlap_count")
            ),
            "decision_time_ready_construction_overlap_row_identity_hash_sample": (
                window.get(
                    "decision_time_ready_construction_overlap_row_identity_hash_sample"
                )
                if isinstance(
                    window.get(
                        "decision_time_ready_construction_overlap_row_identity_hash_sample"
                    ),
                    list,
                )
                else []
            ),
            "promotion_blockers": [
                "REQUIRES_PASSED_UNTOUCHED_PROOF",
                "REQUIRES_SOURCE_SHA256_MATCH",
                "REQUIRES_ALL_UNTOUCHED_ATTESTATIONS_TRUE",
                "REQUIRES_OPERATOR_TO_SET_ELIGIBLE_FOR_HOLDOUT_TRUE_AFTER_PROOF",
            ],
            "registry_window_template": registry_window,
            "clean_no_overlap_registry_window_template": clean_registry_window,
        })

    promotion_ready_candidate_count = max(
        draft_decision_time_ready_no_overlap_count,
        draft_decision_time_ready_row_level_no_overlap_count,
    )
    promotion_readiness_summary = {
        "status": (
            "NO_COUNTABLE_HOLDOUT_WINDOWS_READY"
            if promotion_ready_candidate_count == 0
            else "DRAFT_HOLDOUT_WINDOWS_REQUIRE_UNTOUCHED_PROOF"
        ),
        "draft_window_count": len(draft_windows),
        "draft_windows_with_decision_time_candidates_count": (
            draft_windows_with_decision_time_candidates
        ),
        "draft_decision_time_candidate_ready_count": (
            draft_decision_time_candidate_ready_count
        ),
        "draft_windows_with_no_overlap_proof_count": draft_windows_with_no_overlap_proof,
        "draft_windows_with_overlap_proof_count": draft_windows_with_overlap_proof,
        "draft_windows_with_no_overlap_ready_candidates_count": (
            draft_windows_with_no_overlap_ready_candidates
        ),
        "draft_windows_with_row_level_no_overlap_ready_candidates_count": (
            draft_windows_with_row_level_no_overlap_ready_candidates
        ),
        "draft_decision_time_ready_overlap_with_229_count": (
            draft_decision_time_ready_overlap_with_229_count
        ),
        "draft_decision_time_ready_no_overlap_count": (
            draft_decision_time_ready_no_overlap_count
        ),
        "draft_decision_time_ready_row_level_no_overlap_count": (
            draft_decision_time_ready_row_level_no_overlap_count
        ),
        "clean_no_overlap_registry_template_count": (
            clean_no_overlap_registry_template_count
        ),
        "required_before_countable": [
            "PASSED_UNTOUCHED exclusion proof",
            "matching source_sha256",
            "all required untouched attestations true",
            "eligible_for_holdout=true",
            "PASSED_NO_OVERLAP_WITH_229_CONSTRUCTION_IDENTITIES",
            "registered_source_row_identity_hashes match the promoted clean row set",
        ],
        "packet_is_countable_evidence": False,
        "selection_uses_outcome_fields": False,
        "readiness_uses_outcome_fields": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": (
            "READY_HOLDOUT_PROMOTION_PACKET_AWAITING_UNTOUCHED_PROOF"
            if draft_windows
            else "NO_DRAFT_HOLDOUT_WINDOWS_TO_PROMOTE"
        ),
        "selector_policy_fingerprint": expected_fingerprint,
        "registry_path": str(registry_path),
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source_sha256_match_required": True,
        "construction_subset_identity_proof_required": True,
        "construction_subset_identity_proof_required_status": (
            CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
        ),
        "construction_subset_identity_source_status": candidate_audit.get(
            "construction_subset_identity_source_status"
        ),
        "promotion_required_exclusion_proof_status": "PASSED_UNTOUCHED",
        "promotion_required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        "draft_window_count": len(draft_windows),
        "draft_windows_are_countable": False,
        "packet_is_countable_evidence": False,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_window_selection": [],
        "readiness_uses_outcome_fields": False,
        "outcome_fields_used_for_readiness": [],
        "operator_promotion_required": True,
        "operator_promotion_note": (
            "This packet is a non-countable registry template. A window can only become "
            "eligible after independent proof sets exclusion_proof.status to PASSED_UNTOUCHED, "
            "keeps source_sha256 equal to the current source, sets every required attestation "
            "to true, and then sets eligible_for_holdout=true."
        ),
        "promotion_readiness_summary": promotion_readiness_summary,
        "draft_windows": draft_windows,
        "clean_no_overlap_registry_windows": clean_no_overlap_registry_windows,
        "registry_template": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "status": "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF",
            "selector_policy_fingerprint": expected_fingerprint,
            "source_path": source_path,
            "source_sha256": source_sha256,
            "windows": registry_windows + clean_no_overlap_registry_windows,
        },
    }


def _holdout_promotion_attestations(attestation: dict[str, Any]) -> dict[str, Any]:
    attestations = attestation.get("attestations")
    return attestations if isinstance(attestations, dict) else {}


def draft_holdout_registry_from_packet(
    *,
    promotion_packet_path: Path,
    registry_path: Path,
    source_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    generated_utc: str,
    construction_subset_status_path: Path = DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path or DEFAULT_HOLDOUT_REGISTRY_DRAFT_MANIFEST_PATH
    packet = _load_json(promotion_packet_path)
    packet = packet if isinstance(packet, dict) else {}
    packet_sha256 = _file_sha256(promotion_packet_path)
    source_sha256 = _file_sha256(source_path)
    global_reasons: list[str] = []
    if not packet:
        global_reasons.append("HOLDOUT_DRAFT_REGISTRY_PACKET_MISSING_OR_MALFORMED")
    if promotion_packet_path.exists() is False:
        global_reasons.append("HOLDOUT_DRAFT_REGISTRY_PACKET_MISSING")
    if source_path.exists() is False:
        global_reasons.append("HOLDOUT_DRAFT_REGISTRY_SOURCE_MISSING")
    if packet.get("selector_policy_fingerprint") != expected_fingerprint:
        global_reasons.append("HOLDOUT_DRAFT_REGISTRY_PACKET_SELECTOR_FINGERPRINT_MISMATCH")
    packet_source_sha256 = str(packet.get("source_sha256") or "")
    if source_sha256 and packet_source_sha256 != source_sha256:
        global_reasons.append("HOLDOUT_DRAFT_REGISTRY_PACKET_SOURCE_SHA256_MISMATCH")

    source_rows, source_status = _iter_jsonl(source_path)
    eligible_keys = _eligible_bucket_keys(bucket_matrix_path)
    construction_subset_status = _construction_subset_identity_source_status(
        construction_subset_status_path
    )
    if (
        construction_subset_status_path == DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH
        and construction_subset_status.get("full_identity_set_available") is not True
    ):
        local_construction_subset_status_path = registry_path.with_name(
            DEFAULT_CONSTRUCTION_SUBSET_IDENTITY_MANIFEST_PATH.name
        )
        if local_construction_subset_status_path.exists():
            construction_subset_status_path = local_construction_subset_status_path
            construction_subset_status = _construction_subset_identity_source_status(
                construction_subset_status_path
            )

    clean_windows = [
        window
        for window in packet.get("clean_no_overlap_registry_windows") or []
        if isinstance(window, dict)
    ]
    if not clean_windows:
        global_reasons.append("NO_CLEAN_NO_OVERLAP_WINDOWS_IN_DRAFT_PACKET")

    window_results: list[dict[str, Any]] = []
    draft_windows: list[dict[str, Any]] = []
    for window in clean_windows:
        window_reasons: list[str] = []
        proof = (
            dict(window.get("exclusion_proof"))
            if isinstance(window.get("exclusion_proof"), dict)
            else {}
        )
        window_hashes = (
            dict(window.get("window_hashes"))
            if isinstance(window.get("window_hashes"), dict)
            else {}
        )
        construction_proof = (
            proof.get("construction_subset_identity_proof")
            if isinstance(proof.get("construction_subset_identity_proof"), dict)
            else {}
        )
        registered_hashes = [
            str(item)
            for item in window.get("registered_source_row_identity_hashes") or []
            if str(item)
        ]
        registered_count = int(window.get("registered_source_row_identity_hash_count") or 0)
        if window.get("row_identity_filter_mode") != "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES":
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_MISSING_IDENTITY_ALLOWLIST_MODE")
        if not registered_hashes:
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_REGISTERED_IDENTITIES_MISSING")
        if registered_count != len(registered_hashes):
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_REGISTERED_IDENTITY_COUNT_MISMATCH")
        if source_sha256 and window_hashes.get("source_sha256") != source_sha256:
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_SOURCE_SHA256_MISMATCH")
        if proof.get("source_sha256") != source_sha256:
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_PROOF_SOURCE_SHA256_MISMATCH")
        if proof.get("status") != "REQUIRES_PASSED_UNTOUCHED_PROOF":
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_PROOF_STATUS_NOT_AWAITING_UNTOUCHED")
        if proof.get("window_metadata_sha256") != window_hashes.get("window_metadata_sha256"):
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_METADATA_SHA256_MISMATCH")
        if proof.get("source_row_identity_hash_set_sha256") != window_hashes.get(
            "source_row_identity_hash_set_sha256"
        ):
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_IDENTITY_SET_SHA256_MISMATCH")
        if construction_proof.get("status") != CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS:
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_CONSTRUCTION_NO_OVERLAP_PROOF_NOT_PASSED")
        if construction_proof.get("overlap_identity_hash_count") != 0:
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_CONSTRUCTION_OVERLAP_COUNT_NONZERO")
        if window.get("eligible_for_holdout") is True:
            window_reasons.append("DRAFT_HOLDOUT_WINDOW_MUST_NOT_BE_MARKED_ELIGIBLE")

        if not window_reasons:
            draft = dict(window)
            draft["eligible_for_holdout"] = False
            draft_proof = dict(proof)
            draft_proof["status"] = "REQUIRES_PASSED_UNTOUCHED_PROOF"
            draft_proof["required_attestations"] = list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS)
            draft["exclusion_proof"] = draft_proof
            draft_windows.append(draft)

        window_results.append({
            "window_id": window.get("window_id"),
            "registered_source_row_identity_hash_count": len(registered_hashes),
            "status": (
                "READY_DRAFT_HOLDOUT_WINDOW_PREREGISTERED"
                if not window_reasons
                else "NO_GO_DRAFT_HOLDOUT_WINDOW_REJECTED"
            ),
            "reasons": window_reasons,
        })

    registry_written = False
    registry: dict[str, Any] = {}
    registry_preflight: dict[str, Any] | None = None
    holdout_registry_manifest: dict[str, Any] | None = None
    if not global_reasons and draft_windows:
        registry = {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "status": "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF",
            "selector_policy_fingerprint": expected_fingerprint,
            "source_path": str(source_path),
            "source_sha256": source_sha256,
            "promotion_packet_path": str(promotion_packet_path),
            "promotion_packet_sha256": packet_sha256,
            "registered_window_count": len(draft_windows),
            "windows": draft_windows,
            "exclusion_proof": {
                "status": "DRAFT_REQUIRES_INDEPENDENT_UNTOUCHED_ATTESTATION",
                "packet_is_countable_evidence": False,
                "all_windows_eligible_for_holdout": False,
                "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
            },
        }
        _write_json(registry_path, registry)
        registry_written = True
        preflight_path = registry_path.with_name(DEFAULT_HOLDOUT_REGISTRY_PREFLIGHT_PATH.name)
        registry_preflight = _holdout_registry_preflight(
            registry_path=registry_path,
            registry=registry,
            source_path=source_path,
            source_status=source_status,
            source_rows=source_rows,
            construction_subset_status=construction_subset_status,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_keys,
            generated_utc=generated_utc,
        )
        _write_json(preflight_path, registry_preflight)
        holdout_registry_manifest = _write_holdout_registry_manifest(
            registry_path=registry_path,
            source_path=source_path,
            registry=registry,
            source_status=source_status,
            registry_preflight=registry_preflight,
            generated_utc=generated_utc,
        )

    status = (
        "READY_DRAFT_HOLDOUT_REGISTRY_PREREGISTERED"
        if registry_written
        else "NO_GO_DRAFT_HOLDOUT_REGISTRY_NOT_WRITTEN"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "holdout_registry_draft",
        "status": status,
        "global_reasons": sorted(set(global_reasons)),
        "promotion_packet_path": str(promotion_packet_path),
        "promotion_packet_sha256": packet_sha256,
        "registry_path": str(registry_path),
        "registry_written": registry_written,
        "registry_sha256": _file_sha256(registry_path),
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "selector_policy_fingerprint": expected_fingerprint,
        "clean_no_overlap_window_count": len(clean_windows),
        "draft_registered_window_count": len(draft_windows),
        "window_results": window_results,
        "registry_preflight": registry_preflight,
        "holdout_registry_manifest": holdout_registry_manifest,
        "draft_policy": {
            "packet_is_countable_evidence": False,
            "registry_windows_are_countable": False,
            "eligible_for_holdout_written_value": False,
            "promotion_still_requires_passed_untouched_attestation": True,
            "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        },
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    history = _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=registry_path,
        manifest=manifest,
        generated_utc=generated_utc,
    )
    manifest["history"] = history
    _write_json(manifest_path, manifest)
    return manifest


def build_holdout_untouched_attestation_request(
    *,
    promotion_packet_path: Path,
    source_path: Path,
    expected_fingerprint: str,
    generated_utc: str,
    request_path: Path | None = None,
) -> dict[str, Any]:
    request_path = request_path or DEFAULT_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST_PATH
    packet = _load_json(promotion_packet_path)
    packet = packet if isinstance(packet, dict) else {}
    packet_sha256 = _file_sha256(promotion_packet_path)
    source_sha256 = _file_sha256(source_path)
    global_reasons: list[str] = []
    if not packet:
        global_reasons.append("HOLDOUT_ATTESTATION_REQUEST_PACKET_MISSING_OR_MALFORMED")
    if promotion_packet_path.exists() is False:
        global_reasons.append("HOLDOUT_ATTESTATION_REQUEST_PACKET_MISSING")
    if source_path.exists() is False:
        global_reasons.append("HOLDOUT_ATTESTATION_REQUEST_SOURCE_MISSING")
    if packet.get("selector_policy_fingerprint") != expected_fingerprint:
        global_reasons.append("HOLDOUT_ATTESTATION_REQUEST_SELECTOR_FINGERPRINT_MISMATCH")
    packet_source_sha256 = str(packet.get("source_sha256") or "")
    if source_sha256 and packet_source_sha256 != source_sha256:
        global_reasons.append("HOLDOUT_ATTESTATION_REQUEST_SOURCE_SHA256_MISMATCH")

    clean_windows = [
        window
        for window in packet.get("clean_no_overlap_registry_windows") or []
        if isinstance(window, dict)
    ]
    if not clean_windows:
        global_reasons.append("NO_CLEAN_NO_OVERLAP_WINDOWS_FOR_ATTESTATION_REQUEST")

    window_requests: list[dict[str, Any]] = []
    approved_window_ids: list[str] = []
    total_registered_identity_count = 0
    for window in clean_windows:
        window_reasons: list[str] = []
        proof = (
            dict(window.get("exclusion_proof"))
            if isinstance(window.get("exclusion_proof"), dict)
            else {}
        )
        window_hashes = (
            dict(window.get("window_hashes"))
            if isinstance(window.get("window_hashes"), dict)
            else {}
        )
        construction_proof = (
            proof.get("construction_subset_identity_proof")
            if isinstance(proof.get("construction_subset_identity_proof"), dict)
            else {}
        )
        registered_hashes = [
            str(item)
            for item in window.get("registered_source_row_identity_hashes") or []
            if str(item)
        ]
        registered_count = int(window.get("registered_source_row_identity_hash_count") or 0)
        window_id = str(window.get("window_id") or "")
        if not window_id:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_WINDOW_ID_MISSING")
        if window.get("row_identity_filter_mode") != "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES":
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_MISSING_IDENTITY_ALLOWLIST_MODE")
        if not registered_hashes:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_REGISTERED_IDENTITIES_MISSING")
        if registered_count != len(registered_hashes):
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_REGISTERED_IDENTITY_COUNT_MISMATCH")
        if source_sha256 and window_hashes.get("source_sha256") != source_sha256:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_WINDOW_SOURCE_SHA256_MISMATCH")
        if proof.get("source_sha256") != source_sha256:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_PROOF_SOURCE_SHA256_MISMATCH")
        if proof.get("status") != "REQUIRES_PASSED_UNTOUCHED_PROOF":
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_PROOF_STATUS_NOT_AWAITING_UNTOUCHED")
        if proof.get("window_metadata_sha256") != window_hashes.get("window_metadata_sha256"):
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_METADATA_SHA256_MISMATCH")
        if proof.get("source_row_identity_hash_set_sha256") != window_hashes.get(
            "source_row_identity_hash_set_sha256"
        ):
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_IDENTITY_SET_SHA256_MISMATCH")
        if construction_proof.get("status") != CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_CONSTRUCTION_NO_OVERLAP_NOT_PASSED")
        if construction_proof.get("overlap_identity_hash_count") != 0:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_CONSTRUCTION_OVERLAP_COUNT_NONZERO")
        if window.get("eligible_for_holdout") is True:
            window_reasons.append("HOLDOUT_ATTESTATION_REQUEST_WINDOW_ALREADY_ELIGIBLE")

        if not window_reasons:
            approved_window_ids.append(window_id)
            total_registered_identity_count += len(registered_hashes)
        window_requests.append({
            "window_id": window_id,
            "status": (
                "READY_FOR_INDEPENDENT_UNTOUCHED_ATTESTATION"
                if not window_reasons
                else "NO_GO_HOLDOUT_ATTESTATION_REQUEST_WINDOW_INVALID"
            ),
            "reasons": window_reasons,
            "registered_source_row_identity_hash_count": len(registered_hashes),
            "window_metadata_sha256": window_hashes.get("window_metadata_sha256"),
            "source_row_identity_hash_set_sha256": window_hashes.get(
                "source_row_identity_hash_set_sha256"
            ),
            "construction_subset_identity_proof_status": construction_proof.get("status"),
            "construction_subset_overlap_identity_hash_count": construction_proof.get(
                "overlap_identity_hash_count"
            ),
        })

    template_attestations = {
        attestation: None
        for attestation in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    }
    request_status = (
        "READY_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST"
        if not global_reasons
        and len(approved_window_ids) == len(clean_windows)
        else "NO_GO_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST_INCOMPLETE"
    )
    request = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "holdout_untouched_attestation_request",
        "status": request_status,
        "global_reasons": sorted(set(global_reasons)),
        "selector_policy_fingerprint": expected_fingerprint,
        "request_path": str(request_path),
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "promotion_packet_path": str(promotion_packet_path),
        "promotion_packet_sha256": packet_sha256,
        "clean_no_overlap_window_count": len(clean_windows),
        "clean_no_overlap_identity_count": total_registered_identity_count,
        "attestation_ready_window_count": len(approved_window_ids),
        "total_registered_source_row_identity_hash_count": total_registered_identity_count,
        "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        "approved_window_ids": approved_window_ids,
        "window_requests": window_requests,
        "attestation_template": {
            "schema_version": SCHEMA_VERSION,
            "status": "REQUIRES_INDEPENDENT_UNTOUCHED_REVIEW",
            "selector_policy_fingerprint": expected_fingerprint,
            "source_sha256": source_sha256,
            "promotion_packet_sha256": packet_sha256,
            "approve_all_clean_no_overlap_windows": True,
            "approved_window_ids": approved_window_ids,
            "attestations": template_attestations,
            "required_final_status_for_promotion": "PASSED_UNTOUCHED",
            "not_valid_for_promotion_until": (
                "An independent reviewer verifies every attestation, changes status "
                "to PASSED_UNTOUCHED, and sets each required attestation to true."
            ),
        },
        "not_countable_holdout_evidence": True,
        "not_a_promotion_attestation": True,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_attestation_request": [],
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
        "operator_attestation_required": True,
        "next_required_actions": [
            "Have an independent reviewer verify every required untouched attestation.",
            "Set attestation_template.status to PASSED_UNTOUCHED only after every required attestation is true.",
            "Use promote-holdout-registry with the independently completed attestation before counting holdout rows.",
        ],
    }
    _write_json(request_path, request)
    history = _append_manifest_history(
        manifest_path=request_path,
        sidecar_path=promotion_packet_path,
        manifest=request,
        generated_utc=generated_utc,
    )
    return {**request, "history": history}


def promote_holdout_registry_from_packet(
    *,
    promotion_packet_path: Path,
    attestation_path: Path | None,
    registry_path: Path,
    source_path: Path,
    expected_fingerprint: str,
    generated_utc: str,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path or DEFAULT_HOLDOUT_REGISTRY_PROMOTION_MANIFEST_PATH
    packet = _load_json(promotion_packet_path)
    packet = packet if isinstance(packet, dict) else {}
    attestation = _load_json(attestation_path) if attestation_path is not None else None
    attestation = attestation if isinstance(attestation, dict) else {}
    packet_sha256 = _file_sha256(promotion_packet_path)
    source_sha256 = _file_sha256(source_path)
    attestation_sha256 = _file_sha256(attestation_path) if attestation_path is not None else None

    global_reasons: list[str] = []
    if not packet:
        global_reasons.append("HOLDOUT_PROMOTION_PACKET_MISSING_OR_MALFORMED")
    if promotion_packet_path.exists() is False:
        global_reasons.append("HOLDOUT_PROMOTION_PACKET_MISSING")
    if source_path.exists() is False:
        global_reasons.append("HOLDOUT_PROMOTION_SOURCE_MISSING")
    if packet.get("selector_policy_fingerprint") != expected_fingerprint:
        global_reasons.append("HOLDOUT_PROMOTION_PACKET_SELECTOR_FINGERPRINT_MISMATCH")
    packet_source_sha256 = str(packet.get("source_sha256") or "")
    if source_sha256 and packet_source_sha256 != source_sha256:
        global_reasons.append("HOLDOUT_PROMOTION_PACKET_SOURCE_SHA256_MISMATCH")
    if attestation_path is None:
        global_reasons.append("HOLDOUT_UNTOUCHED_ATTESTATION_PATH_MISSING")
    elif not attestation:
        global_reasons.append("HOLDOUT_UNTOUCHED_ATTESTATION_MISSING_OR_MALFORMED")

    attestations = _holdout_promotion_attestations(attestation)
    if attestation:
        if attestation.get("status") != "PASSED_UNTOUCHED":
            global_reasons.append("HOLDOUT_UNTOUCHED_ATTESTATION_NOT_PASSED")
        if attestation.get("selector_policy_fingerprint") != expected_fingerprint:
            global_reasons.append("HOLDOUT_UNTOUCHED_ATTESTATION_SELECTOR_FINGERPRINT_MISMATCH")
        if source_sha256 and attestation.get("source_sha256") != source_sha256:
            global_reasons.append("HOLDOUT_UNTOUCHED_ATTESTATION_SOURCE_SHA256_MISMATCH")
        if packet_sha256 and attestation.get("promotion_packet_sha256") != packet_sha256:
            global_reasons.append("HOLDOUT_UNTOUCHED_ATTESTATION_PACKET_SHA256_MISMATCH")
        for attestation_name in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS:
            if attestations.get(attestation_name) is not True:
                global_reasons.append(
                    f"HOLDOUT_UNTOUCHED_ATTESTATION_MISSING_{attestation_name.upper()}"
                )

    approve_all = attestation.get("approve_all_clean_no_overlap_windows") is True
    approved_window_ids = {
        str(item)
        for item in attestation.get("approved_window_ids") or []
        if str(item)
    }
    if not approve_all and not approved_window_ids:
        global_reasons.append("NO_APPROVED_CLEAN_HOLDOUT_WINDOWS_IN_ATTESTATION")

    clean_windows = [
        window
        for window in packet.get("clean_no_overlap_registry_windows") or []
        if isinstance(window, dict)
    ]
    clean_windows_by_id = {
        str(window.get("window_id")): window
        for window in clean_windows
        if window.get("window_id") not in {None, ""}
    }
    unknown_window_ids = sorted(approved_window_ids.difference(clean_windows_by_id))
    if unknown_window_ids:
        global_reasons.append("APPROVED_HOLDOUT_WINDOW_ID_NOT_IN_CLEAN_PACKET")

    window_results: list[dict[str, Any]] = []
    promoted_windows: list[dict[str, Any]] = []
    selected_windows = (
        clean_windows
        if approve_all
        else [clean_windows_by_id[window_id] for window_id in sorted(approved_window_ids) if window_id in clean_windows_by_id]
    )
    for window in selected_windows:
        window_reasons: list[str] = []
        window_id = str(window.get("window_id") or "")
        proof = (
            dict(window.get("exclusion_proof"))
            if isinstance(window.get("exclusion_proof"), dict)
            else {}
        )
        window_hashes = (
            dict(window.get("window_hashes"))
            if isinstance(window.get("window_hashes"), dict)
            else {}
        )
        construction_proof = (
            proof.get("construction_subset_identity_proof")
            if isinstance(proof.get("construction_subset_identity_proof"), dict)
            else {}
        )
        registered_hashes = [
            str(item)
            for item in window.get("registered_source_row_identity_hashes") or []
            if str(item)
        ]
        registered_count = int(window.get("registered_source_row_identity_hash_count") or 0)
        if window.get("row_identity_filter_mode") != "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES":
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_MISSING_IDENTITY_ALLOWLIST_MODE")
        if not registered_hashes:
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_REGISTERED_IDENTITIES_MISSING")
        if registered_count != len(registered_hashes):
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_REGISTERED_IDENTITY_COUNT_MISMATCH")
        if source_sha256 and window_hashes.get("source_sha256") != source_sha256:
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_SOURCE_SHA256_MISMATCH")
        if proof.get("source_sha256") != source_sha256:
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_PROOF_SOURCE_SHA256_MISMATCH")
        if proof.get("window_metadata_sha256") != window_hashes.get("window_metadata_sha256"):
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_METADATA_SHA256_MISMATCH")
        if proof.get("source_row_identity_hash_set_sha256") != window_hashes.get(
            "source_row_identity_hash_set_sha256"
        ):
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_IDENTITY_SET_SHA256_MISMATCH")
        if construction_proof.get("status") != CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS:
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_CONSTRUCTION_NO_OVERLAP_PROOF_NOT_PASSED")
        if construction_proof.get("overlap_identity_hash_count") != 0:
            window_reasons.append("CLEAN_HOLDOUT_WINDOW_CONSTRUCTION_OVERLAP_COUNT_NONZERO")

        if not window_reasons and not global_reasons:
            promoted = dict(window)
            promoted_proof = dict(proof)
            promoted_proof.update({
                "status": "PASSED_UNTOUCHED",
                "source_sha256": source_sha256,
                "attestations": {
                    key: True for key in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
                },
                "promotion_attestation": {
                    "attestation_path": str(attestation_path),
                    "attestation_sha256": attestation_sha256,
                    "promotion_packet_path": str(promotion_packet_path),
                    "promotion_packet_sha256": packet_sha256,
                    "promoted_at": generated_utc,
                },
            })
            promoted["eligible_for_holdout"] = True
            promoted["exclusion_proof"] = promoted_proof
            promoted_windows.append(promoted)

        window_results.append({
            "window_id": window_id,
            "selected_for_promotion": True,
            "registered_source_row_identity_hash_count": len(registered_hashes),
            "status": (
                "READY_CLEAN_HOLDOUT_WINDOW_PROMOTED"
                if not window_reasons and not global_reasons
                else "NO_GO_CLEAN_HOLDOUT_WINDOW_PROMOTION_FAILED"
            ),
            "reasons": window_reasons,
        })

    if not clean_windows:
        global_reasons.append("NO_CLEAN_NO_OVERLAP_WINDOWS_IN_PROMOTION_PACKET")
    if selected_windows and not promoted_windows and not global_reasons:
        global_reasons.append("NO_CLEAN_HOLDOUT_WINDOWS_PROMOTED")

    registry_written = False
    if not global_reasons and promoted_windows:
        registry = {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "status": "READY_HOLDOUT_REGISTRY_PROMOTED_BY_UNTOUCHED_ATTESTATION",
            "selector_policy_fingerprint": expected_fingerprint,
            "source_path": str(source_path),
            "source_sha256": source_sha256,
            "promotion_packet_path": str(promotion_packet_path),
            "promotion_packet_sha256": packet_sha256,
            "attestation_path": str(attestation_path),
            "attestation_sha256": attestation_sha256,
            "registered_window_count": len(promoted_windows),
            "windows": promoted_windows,
        }
        _write_json(registry_path, registry)
        registry_written = True

    status = (
        "READY_HOLDOUT_REGISTRY_PROMOTED"
        if registry_written
        else "NO_GO_HOLDOUT_REGISTRY_PROMOTION_FAILED"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "holdout_registry_promotion",
        "status": status,
        "global_reasons": sorted(set(global_reasons)),
        "promotion_packet_path": str(promotion_packet_path),
        "promotion_packet_sha256": packet_sha256,
        "attestation_path": str(attestation_path) if attestation_path is not None else None,
        "attestation_sha256": attestation_sha256,
        "registry_path": str(registry_path),
        "registry_written": registry_written,
        "registry_sha256": _file_sha256(registry_path),
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "selector_policy_fingerprint": expected_fingerprint,
        "clean_no_overlap_window_count": len(clean_windows),
        "approved_window_ids": sorted(approved_window_ids),
        "approve_all_clean_no_overlap_windows": approve_all,
        "promoted_window_count": len(promoted_windows),
        "window_results": window_results,
        "promotion_policy": {
            "requires_attestation_status": "PASSED_UNTOUCHED",
            "requires_packet_sha256_match": True,
            "requires_source_sha256_match": True,
            "requires_selector_policy_fingerprint_match": True,
            "requires_clean_no_overlap_packet_windows": True,
            "requires_registered_source_row_identity_hashes": True,
            "requires_construction_subset_identity_proof_status": (
                CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
            ),
            "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        },
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    history = _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=registry_path,
        manifest=manifest,
        generated_utc=generated_utc,
    )
    return {**manifest, "history": history}


def _exclusion_proof_attestations(proof: dict[str, Any]) -> dict[str, Any]:
    attestations = proof.get("attestations")
    return attestations if isinstance(attestations, dict) else {}


def _window_is_forward_preregistered(window: dict[str, Any] | None) -> bool:
    if not isinstance(window, dict):
        return False
    proof = window.get("exclusion_proof") if isinstance(window.get("exclusion_proof"), dict) else {}
    return (
        window.get("forward_pre_registered") is True
        or proof.get("status") == FORWARD_HOLDOUT_PROOF_STATUS
        or proof.get("proof_type") == "FORWARD_TIME_LOCKED_PRE_REGISTRATION"
    )


def _forward_construction_subset_identity_proof(
    construction_subset_status: dict[str, Any],
    *,
    generated_utc: str,
) -> dict[str, Any]:
    return {
        "status": FORWARD_CONSTRUCTION_SUBSET_PROOF_STATUS,
        "construction_subset_source_path": construction_subset_status.get("path"),
        "construction_subset_source_sha256": construction_subset_status.get("sha256"),
        "construction_subset_candidate_count": construction_subset_status.get(
            "candidate_count"
        ),
        "construction_subset_identity_hash_count": construction_subset_status.get(
            "identity_hash_count"
        ),
        "construction_subset_identity_hash_set_sha256": construction_subset_status.get(
            "identity_hash_set_sha256"
        ),
        "pre_registered_at": generated_utc,
        "overlap_check_deferred_to_row_level": True,
        "row_level_overlap_gate": "HOLDOUT_OVERLAPS_229_CANDIDATE_SUBSET",
        "proof_generation_policy": (
            "Future holdout rows do not exist at pre-registration time. The frozen "
            "construction identity set is locked here, and every materialized row is "
            "still checked against that exact identity set before it can count."
        ),
    }


def _forward_holdout_exclusion_proof_reasons(
    window: dict[str, Any],
    *,
    construction_subset_status: dict[str, Any],
) -> list[str]:
    proof = window.get("exclusion_proof") if isinstance(window.get("exclusion_proof"), dict) else {}
    window_hashes = window.get("window_hashes") if isinstance(window.get("window_hashes"), dict) else {}
    construction_proof = (
        proof.get("construction_subset_identity_proof")
        if isinstance(proof.get("construction_subset_identity_proof"), dict)
        else {}
    )
    attestations = _exclusion_proof_attestations(proof)
    reasons: list[str] = []

    if window.get("forward_pre_registered") is not True:
        reasons.append("HOLDOUT_FORWARD_WINDOW_NOT_MARKED_FORWARD_PREREGISTERED")
    if proof.get("status") != FORWARD_HOLDOUT_PROOF_STATUS:
        reasons.append("HOLDOUT_FORWARD_EXCLUSION_PROOF_NOT_PASSED")
    if proof.get("proof_type") != "FORWARD_TIME_LOCKED_PRE_REGISTRATION":
        reasons.append("HOLDOUT_FORWARD_PROOF_TYPE_MISSING")

    start = status_module._parse_utc(window.get("start_decision_time"))
    pre_registered_at = status_module._parse_utc(proof.get("pre_registered_at"))
    if pre_registered_at is None:
        reasons.append("HOLDOUT_FORWARD_PREREGISTERED_AT_MISSING")
    if start is None:
        reasons.append("HOLDOUT_FORWARD_START_DECISION_TIME_MISSING")
    if start is not None and pre_registered_at is not None and start <= pre_registered_at:
        reasons.append("HOLDOUT_FORWARD_WINDOW_NOT_AFTER_PREREGISTRATION")

    if proof.get("source_sha256") not in {None, ""}:
        reasons.append("HOLDOUT_FORWARD_SOURCE_SHA256_MUST_NOT_BE_PREBOUND")
    if proof.get("source_sha256_policy") != "NOT_BOUND_BEFORE_FORWARD_ROWS_EXIST":
        reasons.append("HOLDOUT_FORWARD_SOURCE_SHA256_POLICY_MISSING")

    for attestation in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS:
        if attestations.get(attestation) is not True:
            reasons.append(f"HOLDOUT_FORWARD_ATTESTATION_MISSING_{attestation.upper()}")

    for field in ("window_metadata_sha256", "source_row_identity_hash_set_sha256"):
        proof_value = str(proof.get(field) or "")
        window_value = str(window_hashes.get(field) or "")
        field_reason = field.upper()
        if not proof_value:
            reasons.append(f"HOLDOUT_FORWARD_PROOF_{field_reason}_MISSING")
            continue
        if not window_value:
            reasons.append(f"HOLDOUT_FORWARD_WINDOW_{field_reason}_MISSING")
            continue
        if proof_value != window_value:
            reasons.append(f"HOLDOUT_FORWARD_PROOF_{field_reason}_MISMATCH")

    if construction_subset_status.get("full_identity_set_available") is not True:
        reasons.append("HOLDOUT_FORWARD_CONSTRUCTION_SUBSET_EXACT_IDENTITIES_UNAVAILABLE")
    if construction_proof.get("status") != FORWARD_CONSTRUCTION_SUBSET_PROOF_STATUS:
        reasons.append("HOLDOUT_FORWARD_CONSTRUCTION_SUBSET_PROOF_NOT_PASSED")
    if construction_proof.get("overlap_check_deferred_to_row_level") is not True:
        reasons.append("HOLDOUT_FORWARD_ROW_LEVEL_OVERLAP_GATE_MISSING")

    source_sha256 = construction_subset_status.get("sha256")
    proof_source_sha256 = construction_proof.get("construction_subset_source_sha256")
    if source_sha256:
        if not proof_source_sha256:
            reasons.append("HOLDOUT_FORWARD_CONSTRUCTION_SUBSET_SOURCE_SHA256_MISSING")
        elif proof_source_sha256 != source_sha256:
            reasons.append("HOLDOUT_FORWARD_CONSTRUCTION_SUBSET_SOURCE_SHA256_MISMATCH")
    identity_hash_set = construction_subset_status.get("identity_hash_set_sha256")
    proof_identity_hash_set = construction_proof.get(
        "construction_subset_identity_hash_set_sha256"
    )
    if identity_hash_set:
        if not proof_identity_hash_set:
            reasons.append(
                "HOLDOUT_FORWARD_CONSTRUCTION_SUBSET_IDENTITY_HASH_SET_SHA256_MISSING"
            )
        elif proof_identity_hash_set != identity_hash_set:
            reasons.append(
                "HOLDOUT_FORWARD_CONSTRUCTION_SUBSET_IDENTITY_HASH_SET_SHA256_MISMATCH"
            )
    return sorted(set(reasons))


def _holdout_exclusion_proof_reasons(
    window: dict[str, Any],
    *,
    source_sha256: str | None,
    construction_subset_status: dict[str, Any],
) -> list[str]:
    proof = window.get("exclusion_proof") if isinstance(window.get("exclusion_proof"), dict) else {}
    window_hashes = window.get("window_hashes") if isinstance(window.get("window_hashes"), dict) else {}
    reasons: list[str] = []
    if _window_is_forward_preregistered(window):
        return _forward_holdout_exclusion_proof_reasons(
            window,
            construction_subset_status=construction_subset_status,
        )
    if proof.get("status") != "PASSED_UNTOUCHED":
        reasons.append("HOLDOUT_EXCLUSION_PROOF_NOT_PASSED")
    proof_source_sha256 = str(proof.get("source_sha256") or "")
    if source_sha256:
        if not proof_source_sha256:
            reasons.append("HOLDOUT_EXCLUSION_PROOF_SOURCE_SHA256_MISSING")
        elif proof_source_sha256 != source_sha256:
            reasons.append("HOLDOUT_EXCLUSION_PROOF_SOURCE_SHA256_MISMATCH")
    attestations = _exclusion_proof_attestations(proof)
    for attestation in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS:
        if attestations.get(attestation) is not True:
            reasons.append(f"HOLDOUT_EXCLUSION_PROOF_ATTESTATION_MISSING_{attestation.upper()}")
    for field in ("window_metadata_sha256", "source_row_identity_hash_set_sha256"):
        proof_value = str(proof.get(field) or "")
        window_value = str(window_hashes.get(field) or "")
        field_reason = field.upper()
        if not proof_value:
            reasons.append(f"HOLDOUT_EXCLUSION_PROOF_{field_reason}_MISSING")
            continue
        if not window_value:
            reasons.append(f"HOLDOUT_WINDOW_{field_reason}_MISSING")
            continue
        if proof_value != window_value:
            reasons.append(f"HOLDOUT_EXCLUSION_PROOF_{field_reason}_MISMATCH")
    construction_proof = (
        proof.get("construction_subset_identity_proof")
        if isinstance(proof.get("construction_subset_identity_proof"), dict)
        else {}
    )
    reasons.extend(_construction_subset_identity_proof_reasons(
        construction_proof,
        construction_subset_status=construction_subset_status,
        window_hashes=window_hashes,
    ))
    return reasons


def _holdout_exclusion_proof_summary(
    window: dict[str, Any],
    *,
    source_sha256: str | None,
    construction_subset_status: dict[str, Any],
) -> dict[str, Any]:
    proof = window.get("exclusion_proof") if isinstance(window.get("exclusion_proof"), dict) else {}
    window_hashes = window.get("window_hashes") if isinstance(window.get("window_hashes"), dict) else {}
    attestations = _exclusion_proof_attestations(proof)
    passed_attestations = [
        attestation
        for attestation in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
        if attestations.get(attestation) is True
    ]
    missing_attestations = [
        attestation
        for attestation in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
        if attestations.get(attestation) is not True
    ]
    return {
        "status": proof.get("status"),
        "source_sha256": proof.get("source_sha256"),
        "source_sha256_matches_current_source": (
            proof.get("source_sha256") == source_sha256
            if source_sha256 and proof.get("source_sha256") not in {None, ""}
            else None
        ),
        "proof_window_metadata_sha256": proof.get("window_metadata_sha256"),
        "window_metadata_sha256": window_hashes.get("window_metadata_sha256"),
        "window_metadata_sha256_matches_registry_window": (
            proof.get("window_metadata_sha256") == window_hashes.get("window_metadata_sha256")
            if proof.get("window_metadata_sha256") not in {None, ""}
            and window_hashes.get("window_metadata_sha256") not in {None, ""}
            else None
        ),
        "proof_source_row_identity_hash_set_sha256": proof.get(
            "source_row_identity_hash_set_sha256"
        ),
        "source_row_identity_hash_set_sha256": window_hashes.get(
            "source_row_identity_hash_set_sha256"
        ),
        "source_row_identity_hash_set_sha256_matches_registry_window": (
            proof.get("source_row_identity_hash_set_sha256")
            == window_hashes.get("source_row_identity_hash_set_sha256")
            if proof.get("source_row_identity_hash_set_sha256") not in {None, ""}
            and window_hashes.get("source_row_identity_hash_set_sha256") not in {None, ""}
            else None
        ),
        "construction_subset_identity_proof": _construction_subset_identity_proof_summary(
            proof.get("construction_subset_identity_proof")
            if isinstance(proof.get("construction_subset_identity_proof"), dict)
            else {},
            construction_subset_status=construction_subset_status,
            window_hashes=window_hashes,
        ),
        "required_attestations": list(REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS),
        "passed_attestations": passed_attestations,
        "missing_attestations": missing_attestations,
    }


def _window_static_reasons(
    window: dict[str, Any],
    *,
    source_sha256: str | None = None,
    construction_subset_status: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    start = status_module._parse_utc(window.get("start_decision_time"))
    end = status_module._parse_utc(window.get("end_decision_time"))
    if start is None or end is None:
        reasons.append("HOLDOUT_WINDOW_MISSING_DECISION_TIME_RANGE")
    elif start >= end:
        reasons.append("HOLDOUT_WINDOW_INVALID_DECISION_TIME_RANGE")
    if window.get("eligible_for_holdout") is not True:
        reasons.append("HOLDOUT_WINDOW_NOT_MARKED_ELIGIBLE")
    reasons.extend(_holdout_exclusion_proof_reasons(
        window,
        source_sha256=source_sha256,
        construction_subset_status=construction_subset_status,
    ))
    return sorted(set(reasons))


def _decision_time_holdout_reject_reasons(
    row: dict[str, Any],
    *,
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> list[str]:
    selection_row = _without_outcome_fields(row)
    reasons: list[str] = []
    reasons.extend(_fingerprint_reject_reasons(selection_row, expected_fingerprint=expected_fingerprint))
    reasons.extend(_row_overlap_reasons(selection_row))
    reasons.extend(_selector_reject_reasons(selection_row, eligible_bucket_keys=eligible_bucket_keys))
    reasons.extend(_accounting_reject_reasons(selection_row))
    return sorted(set(reasons))


def _holdout_registry_preflight(
    *,
    registry_path: Path,
    registry: dict[str, Any],
    source_path: Path,
    source_status: dict[str, Any],
    source_rows: list[dict[str, Any]],
    construction_subset_status: dict[str, Any],
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    generated_utc: str,
) -> dict[str, Any]:
    windows = [window for window in registry.get("windows") or [] if isinstance(window, dict)]
    registry_fingerprint = str(registry.get("selector_policy_fingerprint") or "")
    source_sha256 = source_status.get("sha256")
    registry_source_sha256 = registry.get("source_sha256")
    source_symbols = sorted({
        status_module._normalized_symbol(row)
        for row in source_rows
        if status_module._normalized_symbol(row) != "UNKNOWN"
    })
    source_timeframes = sorted({
        str(status_module._row_value(row, "timeframe") or row.get("timeframe"))
        for row in source_rows
        if status_module._row_value(row, "timeframe") or row.get("timeframe")
    })
    decision_times = [
        status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
        for row in source_rows
    ]
    decision_times = [value for value in decision_times if value is not None]
    global_reasons: list[str] = []
    if registry_fingerprint and registry_fingerprint != expected_fingerprint:
        global_reasons.append("HOLDOUT_REGISTRY_SELECTOR_POLICY_FINGERPRINT_MISMATCH")
    if registry_source_sha256 not in {None, ""} and registry_source_sha256 != source_sha256:
        global_reasons.append("HOLDOUT_REGISTRY_SOURCE_SHA256_MISMATCH")
    if source_status.get("parse_error_count"):
        global_reasons.append("HOLDOUT_SOURCE_PARSE_ERRORS_PRESENT")
    if not windows:
        global_reasons.append("NO_REGISTERED_HOLDOUT_WINDOWS")
    if windows and construction_subset_status.get("full_identity_set_available") is not True:
        global_reasons.append("CONSTRUCTION_SUBSET_EXACT_IDENTITIES_UNAVAILABLE")

    matched_source_identities: set[str] = set()
    total_matching_rows = 0
    total_decision_time_candidate_ready = 0
    total_countable_after_label = 0
    total_overlap_rows = 0
    total_static_eligible_windows = 0
    window_summaries: list[dict[str, Any]] = []

    for window in windows:
        window_registry = {"windows": [window]}
        static_reasons = _window_static_reasons(
            window,
            source_sha256=source_sha256,
            construction_subset_status=construction_subset_status,
        )
        if not static_reasons:
            total_static_eligible_windows += 1
        matching_rows = [
            row
            for row in source_rows
            if _window_for_row(row, window_registry) is not None
        ]
        reason_counts: dict[str, int] = {}
        decision_time_candidate_ready = 0
        countable_after_label = 0
        overlap_row_count = 0
        matching_row_identity_hashes: list[str] = []
        decision_time_ready_identity_hashes: list[str] = []
        matching_symbols = sorted({
            status_module._normalized_symbol(row)
            for row in matching_rows
            if status_module._normalized_symbol(row) != "UNKNOWN"
        })
        matching_timeframes = sorted({
            str(status_module._row_value(row, "timeframe") or row.get("timeframe"))
            for row in matching_rows
            if status_module._row_value(row, "timeframe") or row.get("timeframe")
        })
        for row in matching_rows:
            matched_source_identities.add(_row_identity(row))
            row_identity_hash = _sha256_text(_row_identity(row))
            matching_row_identity_hashes.append(row_identity_hash)
            row_reasons = list(static_reasons)
            row_reasons.extend(_decision_time_holdout_reject_reasons(
                row,
                expected_fingerprint=expected_fingerprint,
                eligible_bucket_keys=eligible_bucket_keys,
            ))
            construction_overlap_reasons = _construction_subset_row_overlap_reasons(
                row,
                construction_subset_status,
            )
            row_reasons.extend(construction_overlap_reasons)
            row_reasons = sorted(set(row_reasons))
            if _row_overlap_reasons(row) or construction_overlap_reasons:
                overlap_row_count += 1
            if row_reasons:
                for reason in row_reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            else:
                decision_time_candidate_ready += 1
                decision_time_ready_identity_hashes.append(row_identity_hash)
                if status_module._outcome_after_cost_bps(row) is not None or status_module._trade_outcome_pnl(row) is not None:
                    countable_after_label += 1
        total_matching_rows += len(matching_rows)
        total_decision_time_candidate_ready += decision_time_candidate_ready
        total_countable_after_label += countable_after_label
        total_overlap_rows += overlap_row_count
        window_summaries.append({
            "window_id": window.get("window_id"),
            "start_decision_time": window.get("start_decision_time"),
            "end_decision_time": window.get("end_decision_time"),
            "eligible_for_holdout": window.get("eligible_for_holdout") is True,
            "exclusion_proof_status": (
                window.get("exclusion_proof", {}).get("status")
                if isinstance(window.get("exclusion_proof"), dict)
                else None
            ),
            "exclusion_proof_summary": _holdout_exclusion_proof_summary(
                window,
                source_sha256=source_sha256,
                construction_subset_status=construction_subset_status,
            ),
            "symbols": window.get("symbols") if isinstance(window.get("symbols"), list) else [],
            "timeframes": window.get("timeframes") if isinstance(window.get("timeframes"), list) else [],
            "matching_source_symbols": matching_symbols,
            "matching_source_timeframes": matching_timeframes,
            "matching_window_hashes": _holdout_window_hashes(
                window_id=str(window.get("window_id") or ""),
                start_decision_time=window.get("start_decision_time"),
                end_decision_time=window.get("end_decision_time"),
                symbols=matching_symbols,
                timeframes=matching_timeframes,
                source_row_identity_hashes=matching_row_identity_hashes,
                decision_time_ready_row_identity_hashes=decision_time_ready_identity_hashes,
                source_sha256=source_sha256,
            ),
            "matching_source_row_count": len(matching_rows),
            "decision_time_candidate_ready_count": decision_time_candidate_ready,
            "countable_after_label_count": countable_after_label,
            "overlap_row_count": overlap_row_count,
            "static_reasons": static_reasons,
            "decision_time_reject_reason_counts": {
                key: reason_counts[key] for key in sorted(reason_counts)
            },
            "status": (
                "READY_HOLDOUT_WINDOW_HAS_DECISION_TIME_CANDIDATES"
                if decision_time_candidate_ready > 0 and not static_reasons
                else "NO_GO_HOLDOUT_WINDOW_NO_DECISION_TIME_CANDIDATES"
                if not static_reasons
                else "NO_GO_HOLDOUT_WINDOW_PREFLIGHT_FAILED"
            ),
        })

    unmatched_source_rows = max(0, len(source_rows) - len(matched_source_identities))
    if windows and total_static_eligible_windows == 0:
        global_reasons.append("NO_STATICALLY_ELIGIBLE_HOLDOUT_WINDOWS")
    if windows and total_matching_rows == 0:
        global_reasons.append("REGISTERED_HOLDOUT_WINDOWS_MATCH_NO_SOURCE_ROWS")
    if total_matching_rows > 0 and total_decision_time_candidate_ready == 0:
        global_reasons.append("NO_DECISION_TIME_A_GRADE_HOLDOUT_CANDIDATES")
    if total_decision_time_candidate_ready > 0 and total_countable_after_label == 0:
        global_reasons.append("NO_LABEL_OUTCOMES_FOR_DECISION_TIME_HOLDOUT_CANDIDATES")
    if total_overlap_rows > 0:
        global_reasons.append("HOLDOUT_REGISTRY_MATCHES_OVERLAPPING_SOURCE_ROWS")

    status = (
        "READY_HOLDOUT_REGISTRY_PREFLIGHT"
        if not global_reasons
        else "NO_GO_NO_REGISTERED_HOLDOUT_WINDOWS"
        if global_reasons == ["NO_REGISTERED_HOLDOUT_WINDOWS"]
        else "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": status,
        "selector_policy_fingerprint": expected_fingerprint,
        "registry_path": str(registry_path),
        "registry_sha256": _file_sha256(registry_path),
        "registry_status": registry.get("status"),
        "registry_selector_policy_fingerprint": registry.get("selector_policy_fingerprint"),
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "registry_source_sha256": registry_source_sha256,
        "source_hash_match": (
            registry_source_sha256 == source_sha256
            if registry_source_sha256 not in {None, ""}
            else None
        ),
        "construction_subset_identity_source_status": construction_subset_status,
        "construction_subset_identity_proof_required": True,
        "construction_subset_identity_proof_required_status": (
            CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
        ),
        "source_row_count": len(source_rows),
        "source_symbol_count": len(source_symbols),
        "source_symbols_sample": source_symbols[:100],
        "source_timeframes": source_timeframes,
        "source_decision_time_min": (
            min(decision_times).isoformat().replace("+00:00", "Z") if decision_times else None
        ),
        "source_decision_time_max": (
            max(decision_times).isoformat().replace("+00:00", "Z") if decision_times else None
        ),
        "registered_window_count": len(windows),
        "statically_eligible_window_count": total_static_eligible_windows,
        "matching_source_row_count": total_matching_rows,
        "unmatched_source_row_count": unmatched_source_rows,
        "decision_time_candidate_ready_count": total_decision_time_candidate_ready,
        "countable_after_label_count": total_countable_after_label,
        "overlap_row_count": total_overlap_rows,
        "global_reasons": global_reasons,
        "windows": window_summaries,
        "candidate_selection_preflight": {
            "selection_fields_freeze": "decision_time_features_only",
            "outcome_fields_excluded_before_selection": sorted(OUTCOME_FIELDS),
            "future_labels_used_as_features_allowed": False,
            "selection_does_not_filter_by_outcome": True,
        },
    }


def forward_preregister_holdout_registry(
    *,
    registry_path: Path,
    source_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    generated_utc: str,
    window_start: str | None,
    start_delay_minutes: float,
    window_minutes: float,
    window_count: int,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    construction_subset_status_path: Path = DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path or DEFAULT_FORWARD_HOLDOUT_REGISTRATION_MANIFEST_PATH
    generated_at = status_module._parse_utc(generated_utc)
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    if window_start:
        first_start = status_module._parse_utc(window_start)
    else:
        first_start = generated_at + timedelta(minutes=start_delay_minutes)
    duration = timedelta(minutes=window_minutes)
    source_rows, source_status = _iter_jsonl(source_path)
    eligible_keys = _eligible_bucket_keys(bucket_matrix_path)
    construction_subset_status = _construction_subset_identity_source_status(
        construction_subset_status_path
    )
    if (
        construction_subset_status_path == DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH
        and construction_subset_status.get("full_identity_set_available") is not True
    ):
        local_construction_subset_status_path = registry_path.with_name(
            DEFAULT_CONSTRUCTION_SUBSET_IDENTITY_MANIFEST_PATH.name
        )
        if local_construction_subset_status_path.exists():
            construction_subset_status_path = local_construction_subset_status_path
            construction_subset_status = _construction_subset_identity_source_status(
                construction_subset_status_path
            )

    global_reasons: list[str] = []
    if first_start is None:
        global_reasons.append("FORWARD_HOLDOUT_WINDOW_START_MISSING_OR_MALFORMED")
    if window_minutes <= 0:
        global_reasons.append("FORWARD_HOLDOUT_WINDOW_MINUTES_MUST_BE_POSITIVE")
    if window_count <= 0:
        global_reasons.append("FORWARD_HOLDOUT_WINDOW_COUNT_MUST_BE_POSITIVE")
    if construction_subset_status.get("full_identity_set_available") is not True:
        global_reasons.append("CONSTRUCTION_SUBSET_EXACT_IDENTITIES_UNAVAILABLE")

    normalized_symbols = sorted({
        str(symbol).upper()
        for symbol in symbols or []
        if str(symbol or "").strip()
    })
    normalized_timeframes = sorted({
        str(timeframe)
        for timeframe in timeframes or []
        if str(timeframe or "").strip()
    })
    windows: list[dict[str, Any]] = []
    window_results: list[dict[str, Any]] = []
    if first_start is not None and duration.total_seconds() > 0 and window_count > 0:
        for index in range(window_count):
            start = first_start + index * duration
            end = start + duration
            start_iso = _utc_format(start)
            end_iso = _utc_format(end)
            window_id = "forward-holdout-" + _sha256_payload({
                "index": index,
                "start_decision_time": start_iso,
                "end_decision_time": end_iso,
                "symbols": normalized_symbols,
                "timeframes": normalized_timeframes,
                "selector_policy_fingerprint": expected_fingerprint,
                "pre_registered_at": generated_utc,
            })[:20]
            window_hashes = _holdout_window_hashes(
                window_id=window_id,
                start_decision_time=start_iso,
                end_decision_time=end_iso,
                symbols=normalized_symbols,
                timeframes=normalized_timeframes,
                source_row_identity_hashes=[],
                decision_time_ready_row_identity_hashes=[],
                source_sha256=None,
            )
            window_reasons: list[str] = []
            if start <= generated_at:
                window_reasons.append("FORWARD_HOLDOUT_WINDOW_NOT_AFTER_PREREGISTRATION")
            proof = {
                "status": FORWARD_HOLDOUT_PROOF_STATUS,
                "proof_type": "FORWARD_TIME_LOCKED_PRE_REGISTRATION",
                "pre_registered_at": generated_utc,
                "source_sha256": None,
                "source_sha256_policy": "NOT_BOUND_BEFORE_FORWARD_ROWS_EXIST",
                "window_metadata_sha256": window_hashes["window_metadata_sha256"],
                "source_row_identity_hash_set_sha256": window_hashes[
                    "source_row_identity_hash_set_sha256"
                ],
                "construction_subset_identity_proof": (
                    _forward_construction_subset_identity_proof(
                        construction_subset_status,
                        generated_utc=generated_utc,
                    )
                ),
                "attestations": {
                    attestation: True
                    for attestation in REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
                },
                "attestation_basis": (
                    "Machine time-lock: this window starts after pre-registration, "
                    "the selector fingerprint is frozen, and materialized rows must "
                    "pass row-level point-in-time and construction-overlap gates."
                ),
            }
            window = {
                "window_id": window_id,
                "start_decision_time": start_iso,
                "end_decision_time": end_iso,
                "symbols": normalized_symbols,
                "timeframes": normalized_timeframes,
                "window_hashes": window_hashes,
                "eligible_for_holdout": True,
                "forward_pre_registered": True,
                "row_identity_filter_mode": "DECISION_TIME_RANGE_ONLY_FORWARD_PRE_REGISTRATION",
                "candidate_selection_policy": "PENDING_ROWS_MUST_BE_CREATED_BEFORE_OUTCOME_LABELS",
                "registered_source_row_identity_hash_count": 0,
                "registered_source_row_identity_hashes": [],
                "exclusion_proof": proof,
            }
            window_reasons.extend(_window_static_reasons(
                window,
                source_sha256=None,
                construction_subset_status=construction_subset_status,
            ))
            if not window_reasons:
                windows.append(window)
            window_results.append({
                "window_id": window_id,
                "start_decision_time": start_iso,
                "end_decision_time": end_iso,
                "status": (
                    "READY_FORWARD_HOLDOUT_WINDOW_PREREGISTERED"
                    if not window_reasons
                    else "NO_GO_FORWARD_HOLDOUT_WINDOW_REJECTED"
                ),
                "reasons": sorted(set(window_reasons)),
            })

    registry_written = False
    registry: dict[str, Any] = {}
    registry_preflight: dict[str, Any] | None = None
    holdout_registry_manifest: dict[str, Any] | None = None
    previous_registry = _load_json(registry_path)
    previous_registry = previous_registry if isinstance(previous_registry, dict) else {}
    if not global_reasons and windows:
        registry = {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "status": "FORWARD_PRE_REGISTERED_AWAITING_OUTCOMES",
            "selector_policy_fingerprint": expected_fingerprint,
            "source_path": str(source_path),
            "source_sha256": None,
            "source_sha256_policy": "NOT_BOUND_BEFORE_FORWARD_ROWS_EXIST",
            "registered_window_count": len(windows),
            "windows": windows,
            "previous_registry_status": previous_registry.get("status"),
            "previous_registry_sha256": _file_sha256(registry_path),
            "not_countable_holdout_evidence": True,
            "post_outcome_candidate_selection_allowed": False,
        }
        _write_json(registry_path, registry)
        registry_written = True
        preflight_path = registry_path.with_name(DEFAULT_HOLDOUT_REGISTRY_PREFLIGHT_PATH.name)
        registry_preflight = _holdout_registry_preflight(
            registry_path=registry_path,
            registry=registry,
            source_path=source_path,
            source_status=source_status,
            source_rows=source_rows,
            construction_subset_status=construction_subset_status,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_keys,
            generated_utc=generated_utc,
        )
        _write_json(preflight_path, registry_preflight)
        holdout_registry_manifest = _write_holdout_registry_manifest(
            registry_path=registry_path,
            source_path=source_path,
            registry=registry,
            source_status=source_status,
            registry_preflight=registry_preflight,
            generated_utc=generated_utc,
        )

    status = (
        "READY_FORWARD_HOLDOUT_REGISTRY_PREREGISTERED"
        if registry_written
        else "NO_GO_FORWARD_HOLDOUT_REGISTRY_NOT_WRITTEN"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "forward_holdout_preregistration",
        "status": status,
        "global_reasons": sorted(set(global_reasons)),
        "selector_policy_fingerprint": expected_fingerprint,
        "registry_path": str(registry_path),
        "registry_written": registry_written,
        "registry_sha256": _file_sha256(registry_path),
        "registry_status": registry.get("status"),
        "source_path": str(source_path),
        "source_sha256_at_registration": source_status.get("sha256"),
        "source_sha256_bound_to_registry": False,
        "source_sha256_policy": "NOT_BOUND_BEFORE_FORWARD_ROWS_EXIST",
        "construction_subset_status_path": str(construction_subset_status_path),
        "construction_subset_identity_source_status": construction_subset_status,
        "requested_window_count": window_count,
        "forward_registered_window_count": len(windows),
        "window_minutes": window_minutes,
        "start_delay_minutes": start_delay_minutes,
        "symbols": normalized_symbols,
        "timeframes": normalized_timeframes,
        "window_results": window_results,
        "registry_preflight": registry_preflight,
        "holdout_registry_manifest": holdout_registry_manifest,
        "not_countable_holdout_evidence": True,
        "does_not_mark_ready": True,
        "post_outcome_candidate_selection_allowed": False,
        "pending_selection_policy": (
            "Rows inside these windows can create pending holdout selections only "
            "while no realized outcome label is present. Labeled rows require a "
            "preexisting pending selection."
        ),
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    history = _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=registry_path,
        manifest=manifest,
        generated_utc=generated_utc,
    )
    manifest["history"] = history
    _write_json(manifest_path, manifest)
    return manifest


def _window_for_row(row: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    decision = status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
    symbol = status_module._normalized_symbol(row)
    timeframe = str(status_module._row_value(row, "timeframe") or row.get("timeframe") or "")
    if decision is None:
        return None
    for window in registry.get("windows") or []:
        if not isinstance(window, dict):
            continue
        start = status_module._parse_utc(window.get("start_decision_time"))
        end = status_module._parse_utc(window.get("end_decision_time"))
        if start is None or end is None or not (start <= decision <= end):
            continue
        symbols = window.get("symbols")
        timeframes = window.get("timeframes")
        if isinstance(symbols, list) and symbols and symbol not in {str(item).upper() for item in symbols}:
            continue
        if isinstance(timeframes, list) and timeframes and timeframe not in {str(item) for item in timeframes}:
            continue
        registered_identity_hashes = _registered_source_row_identity_hashes(window)
        if registered_identity_hashes and _row_identity_hash(row) not in registered_identity_hashes:
            continue
        return window
    return None


def _holdout_reject_reasons(
    row: dict[str, Any],
    *,
    registry: dict[str, Any],
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    source_sha256: str | None,
    construction_subset_status: dict[str, Any],
    require_label_outcome: bool = True,
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_fingerprint_reject_reasons(row, expected_fingerprint=expected_fingerprint))
    reasons.extend(_post_outcome_selection_reasons(row))
    reasons.extend(_row_overlap_reasons(row))
    reasons.extend(_construction_subset_row_overlap_reasons(
        row,
        construction_subset_status,
    ))
    window = _window_for_row(row, registry)
    if not window:
        reasons.append("NO_PRE_REGISTERED_HOLDOUT_WINDOW")
    else:
        reasons.extend(_window_static_reasons(
            window,
            source_sha256=source_sha256,
            construction_subset_status=construction_subset_status,
        ))
    selection_row = _without_outcome_fields(row)
    reasons.extend(_selector_reject_reasons(selection_row, eligible_bucket_keys=eligible_bucket_keys))
    reasons.extend(_accounting_reject_reasons(row))
    if (
        require_label_outcome
        and status_module._outcome_after_cost_bps(row) is None
        and status_module._trade_outcome_pnl(row) is None
    ):
        reasons.append("MISSING_LABEL_OUTCOME")
    return sorted(set(reasons))


def _holdout_prediction_action(row: dict[str, Any]) -> str:
    tier = str(status_module._first_present(
        row.get("candidate_selection_tier"),
        row.get("paper_opportunity_tier"),
        row.get("explicit_paper_opportunity_tier"),
        row.get("admission_tier"),
        row.get("candidate_tier"),
        "",
    ) or "").upper()
    if tier == "NO_TRADE":
        return "NO_TRADE"
    side = status_module._directional_side(row)
    if side == "long":
        return "LONG"
    if side == "short":
        return "SHORT"
    action = str(status_module._first_present(
        row.get("selected_action"),
        row.get("action"),
        row.get("proposed_action"),
        "",
    ) or "").upper()
    if action in {"LONG", "BUY"}:
        return "LONG"
    if action in {"SHORT", "SELL"}:
        return "SHORT"
    if action in {"NO_TRADE", "HOLD", "FLAT"}:
        return "NO_TRADE"
    return "UNKNOWN"


def _holdout_prediction_coverage_reasons(
    row: dict[str, Any],
    *,
    registry: dict[str, Any],
    expected_fingerprint: str,
    source_sha256: str | None,
    construction_subset_status: dict[str, Any],
) -> list[str]:
    selection_row = _without_outcome_fields(row)
    reasons: list[str] = []
    reasons.extend(_fingerprint_reject_reasons(selection_row, expected_fingerprint=expected_fingerprint))
    reasons.extend(_post_outcome_selection_reasons(selection_row))
    reasons.extend(_row_overlap_reasons(selection_row))
    reasons.extend(_construction_subset_row_overlap_reasons(
        selection_row,
        construction_subset_status,
    ))
    window = _window_for_row(selection_row, registry)
    if not window:
        reasons.append("NO_PRE_REGISTERED_HOLDOUT_WINDOW")
    else:
        reasons.extend(_window_static_reasons(
            window,
            source_sha256=source_sha256,
            construction_subset_status=construction_subset_status,
        ))
    reasons.extend(status_module._pre_submit_temporal_reasons(selection_row))
    if selection_row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    if status_module._parse_utc(selection_row.get("decision_time") or selection_row.get("entry_feature_decision_time")) is None:
        reasons.append("MISSING_DECISION_TIME")
    if status_module._normalized_symbol(selection_row) == "UNKNOWN":
        reasons.append("MISSING_SYMBOL")
    if not (status_module._row_value(selection_row, "timeframe") or selection_row.get("timeframe")):
        reasons.append("MISSING_TIMEFRAME")
    return sorted(set(reasons))


def _holdout_prediction_coverage_status(
    source_rows: list[dict[str, Any]],
    *,
    registry: dict[str, Any],
    expected_fingerprint: str,
    source_sha256: str | None,
    construction_subset_status: dict[str, Any],
) -> dict[str, Any]:
    valid_count = 0
    symbols: set[str] = set()
    timeframes: set[str] = set()
    action_counts: dict[str, int] = {"LONG": 0, "SHORT": 0, "NO_TRADE": 0, "UNKNOWN": 0}
    reason_counts: dict[str, int] = {}
    valid_samples: list[dict[str, Any]] = []
    rejected_samples: list[dict[str, Any]] = []

    for row in source_rows:
        selection_row = _without_outcome_fields(row)
        reasons = _holdout_prediction_coverage_reasons(
            selection_row,
            registry=registry,
            expected_fingerprint=expected_fingerprint,
            source_sha256=source_sha256,
            construction_subset_status=construction_subset_status,
        )
        action = _holdout_prediction_action(selection_row)
        if reasons:
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if len(rejected_samples) < 20:
                rejected_samples.append({
                    "symbol": status_module._normalized_symbol(selection_row),
                    "timeframe": status_module._row_value(selection_row, "timeframe") or selection_row.get("timeframe"),
                    "decision_time": selection_row.get("decision_time") or selection_row.get("entry_feature_decision_time"),
                    "selected_policy_action": action,
                    "reasons": reasons,
                })
            continue

        valid_count += 1
        action_counts[action] = action_counts.get(action, 0) + 1
        symbol = status_module._normalized_symbol(selection_row)
        timeframe = str(status_module._row_value(selection_row, "timeframe") or selection_row.get("timeframe") or "")
        if symbol != "UNKNOWN":
            symbols.add(symbol)
        if timeframe:
            timeframes.add(timeframe)
        if len(valid_samples) < 20:
            valid_samples.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "decision_time": selection_row.get("decision_time") or selection_row.get("entry_feature_decision_time"),
                "selected_policy_action": action,
                "paper_opportunity_tier": status_module._first_present(
                    selection_row.get("paper_opportunity_tier"),
                    selection_row.get("candidate_selection_tier"),
                    selection_row.get("admission_tier"),
                ),
                "counts_as_a_grade_evidence": False,
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE"
            if valid_count > 0
            else "BLOCKED_NO_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS"
        ),
        "policy": (
            "Counts point-in-time-valid frozen-policy holdout predictions for Phase 3 "
            "coverage only. This does not admit A-grade economic evidence and never "
            "counts NO_TRADE as an economic win."
        ),
        "processed_source_row_count": len(source_rows),
        "point_in_time_valid_prediction_count": valid_count,
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "symbols": sorted(symbols),
        "timeframes": sorted(timeframes),
        "selected_policy_action_counts": {
            key: action_counts[key] for key in sorted(action_counts)
        },
        "rejected_prediction_count": len(source_rows) - valid_count,
        "prediction_reject_reason_counts": {
            key: reason_counts[key] for key in sorted(reason_counts)
        },
        "valid_prediction_samples": valid_samples,
        "rejected_prediction_samples": rejected_samples,
        "counts_as_a_grade_evidence": False,
        "counts_no_trade_as_win": False,
        "post_outcome_candidate_selection_allowed": False,
        "future_labels_used_as_decision_features_allowed": False,
    }


def _candidate_record(
    row: dict[str, Any],
    *,
    scope: str,
    expected_fingerprint: str,
    generated_utc: str,
) -> dict[str, Any]:
    candidate = _without_outcome_fields(dict(row))
    identity = _candidate_identity(row, scope=scope)
    candidate.update({
        "schema_version": SCHEMA_VERSION,
        "candidate_identity": identity,
        "selector_policy_fingerprint": expected_fingerprint,
        "candidate_selection_tier": "A_GRADE_EXECUTION_PAPER",
        "out_of_sample_reverify_candidate": True,
        "selected_before_outcome": True,
        "candidate_selected_before_outcome": True,
        "candidate_selected_at": generated_utc,
        "future_labels_used_as_features": False,
        "future_label_used_as_outcome_only": True,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": status_module.LIVE_GATE,
    })
    if scope == "realtime":
        age_seconds = _realtime_pending_source_age_seconds(row, generated_utc=generated_utc)
        latest_source_timestamp = _latest_realtime_source_timestamp(row)
        candidate.update({
            "realtime_pending_source_observed_at": generated_utc,
            "realtime_pending_source_latest_timestamp": (
                latest_source_timestamp.isoformat().replace("+00:00", "Z")
                if latest_source_timestamp is not None else None
            ),
            "realtime_pending_source_age_seconds": (
                round(age_seconds, 6) if age_seconds is not None else None
            ),
            "realtime_pending_source_freshness_policy": _realtime_pending_source_freshness_policy(),
        })
    return candidate


def _final_holdout_record(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    final = _payload_without_chain_metadata(candidate)
    for field in OUTCOME_FIELDS:
        if field in row:
            final[field] = row[field]
    window = _window_for_row(row, registry) or {}
    final.update({
        "holdout_window_id": window.get("window_id"),
        "untouched_holdout_window": True,
        "out_of_sample_holdout": True,
        "used_for_dynamic_a_grade_bucket_construction": False,
        "used_for_229_candidate_subset": False,
        "selector_training_window_overlap": False,
    })
    return final


def _metric_values(rows: list[dict[str, Any]]) -> list[float]:
    values = [
        value
        for row in rows
        for value in [status_module._outcome_after_cost_bps(row)]
        if value is not None
    ]
    if values:
        return values
    return [
        value
        for row in rows
        for value in [status_module._trade_outcome_pnl(row)]
        if value is not None
    ]


def _profit_concentration(rows: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    positive: dict[str, float] = {}
    for row in rows:
        metric = status_module._outcome_after_cost_bps(row)
        if metric is None:
            metric = status_module._trade_outcome_pnl(row)
        if metric is None or metric <= 0.0:
            continue
        if dimension == "symbol":
            key = status_module._normalized_symbol(row)
        elif dimension == "timeframe":
            key = str(status_module._row_value(row, "timeframe") or row.get("timeframe") or "UNKNOWN")
        elif dimension == "regime":
            key = status_module._market_regime_bucket(row)
        elif dimension == "strategy":
            key = status_module._row_strategy(row)
        else:
            key = "UNKNOWN"
        positive[key] = positive.get(key, 0.0) + metric
    total = sum(positive.values())
    if total <= 0.0:
        return {"dimension": dimension, "top_profit_share": None, "status": "NO_GROSS_PROFIT"}
    top_key, top_value = max(positive.items(), key=lambda item: item[1])
    share = top_value / total
    return {
        "dimension": dimension,
        "status": "PASSED" if share <= 0.35 else "PROFIT_CONCENTRATION_RISK",
        "top_key": top_key,
        "top_profit_share": round(share, 8),
        "maximum_allowed_top_profit_share": 0.35,
    }


def _sidecar_summary(rows_path: Path) -> dict[str, Any]:
    rows, source_status = _iter_jsonl(rows_path)
    values = _metric_values(rows)
    profit_factor, profit_factor_numeric = status_module._profit_factor_from_values(values)
    expectancy = sum(values) / len(values) if values else None
    symbols = sorted({status_module._normalized_symbol(row) for row in rows if status_module._normalized_symbol(row) != "UNKNOWN"})
    side_counts: dict[str, int] = {}
    for row in rows:
        side = status_module._directional_side(row)
        if side:
            side_counts[side] = side_counts.get(side, 0) + 1
    concentration = {
        dimension: _profit_concentration(rows, dimension)
        for dimension in ("symbol", "timeframe", "regime", "strategy")
    }
    return {
        "source_status": source_status,
        "row_count": len(rows),
        "symbol_count": len(symbols),
        "symbols_sample": symbols[:100],
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "expectancy_metric": round(expectancy, 8) if expectancy is not None else None,
        "profit_factor": profit_factor,
        "profit_factor_numeric": (
            "inf" if profit_factor_numeric == float("inf") else round(profit_factor_numeric, 8)
            if profit_factor_numeric is not None else None
        ),
        "profit_concentration_status": concentration,
    }


def _pending_sidecar_summary(
    pending_path: Path,
    *,
    final_rows_path: Path,
    expected_fingerprint: str,
    generated_utc: str,
    scope: str,
) -> dict[str, Any]:
    rows, source_status = _iter_jsonl(pending_path)
    final_identities = _existing_identities(final_rows_path)
    generated_at = status_module._parse_utc(generated_utc)
    symbols = sorted({
        status_module._normalized_symbol(row)
        for row in rows
        if status_module._normalized_symbol(row) != "UNKNOWN"
    })
    side_counts: dict[str, int] = {}
    timeframe_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    fingerprint_counts: dict[str, int] = {}
    outcome_field_presence_counts: dict[str, int] = {}
    selected_times: list[datetime] = []
    max_age_seconds: float | None = None
    unresolved = 0
    finalized = 0
    chain_recorded = 0
    future_leak_count = 0
    post_outcome_selected_count = 0
    fingerprint_mismatch_count = 0

    for row in rows:
        identity = str(row.get("candidate_identity") or _candidate_identity(row, scope=scope))
        if identity in final_identities:
            finalized += 1
        else:
            unresolved += 1
        if row.get("producer_hash_chain"):
            chain_recorded += 1
        side = status_module._directional_side(row)
        if side:
            side_counts[side] = side_counts.get(side, 0) + 1
        timeframe = str(status_module._row_value(row, "timeframe") or row.get("timeframe") or "UNKNOWN")
        timeframe_counts[timeframe] = timeframe_counts.get(timeframe, 0) + 1
        tier = str(row.get("candidate_selection_tier") or "__missing__")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        fingerprint = status_module._first_present(
            row.get("selector_policy_fingerprint"),
            row.get("frozen_selector_fingerprint"),
            row.get("policy_fingerprint"),
        )
        fingerprint_key = str(fingerprint) if fingerprint not in {None, ""} else "__missing__"
        fingerprint_counts[fingerprint_key] = fingerprint_counts.get(fingerprint_key, 0) + 1
        if fingerprint_key != expected_fingerprint:
            fingerprint_mismatch_count += 1
        if row.get("future_labels_used_as_features") is True:
            future_leak_count += 1
        if row.get("candidate_selected_before_outcome") is False or row.get("selected_before_outcome") is False:
            post_outcome_selected_count += 1
        for field in OUTCOME_FIELDS:
            if row.get(field) not in {None, ""}:
                outcome_field_presence_counts[field] = outcome_field_presence_counts.get(field, 0) + 1
        selected_at = status_module._parse_utc(row.get("candidate_selected_at") or row.get("selected_at"))
        if selected_at is not None:
            selected_times.append(selected_at)
            if generated_at is not None:
                age_seconds = (generated_at - selected_at).total_seconds()
                max_age_seconds = age_seconds if max_age_seconds is None else max(max_age_seconds, age_seconds)

    status = (
        "READY_PENDING_SELECTIONS_WAITING_FOR_OUTCOMES"
        if unresolved > 0
        else "READY_PENDING_SELECTIONS_ALL_FINALIZED"
        if finalized > 0
        else "NO_PENDING_SELECTION_ROWS"
    )
    if (
        source_status.get("parse_error_count")
        or fingerprint_mismatch_count
        or future_leak_count
        or post_outcome_selected_count
        or outcome_field_presence_counts
    ):
        status = "NO_GO_PENDING_SIDECAR_INTEGRITY_GAP"

    return {
        "source_status": source_status,
        "status": status,
        "row_count": len(rows),
        "unresolved_pending_count": unresolved,
        "finalized_pending_count": finalized,
        "chain_recorded_count": chain_recorded,
        "symbol_count": len(symbols),
        "symbols_sample": symbols[:100],
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "timeframe_counts": {key: timeframe_counts[key] for key in sorted(timeframe_counts)},
        "candidate_tier_counts": {key: tier_counts[key] for key in sorted(tier_counts)},
        "selector_policy_fingerprint_counts": {
            key: fingerprint_counts[key] for key in sorted(fingerprint_counts)
        },
        "selector_policy_fingerprint_mismatch_count": fingerprint_mismatch_count,
        "future_labels_used_as_features_true_count": future_leak_count,
        "post_outcome_selected_flag_count": post_outcome_selected_count,
        "outcome_field_presence_counts": {
            key: outcome_field_presence_counts[key] for key in sorted(outcome_field_presence_counts)
        },
        "candidate_selected_at_min": (
            min(selected_times).isoformat().replace("+00:00", "Z") if selected_times else None
        ),
        "candidate_selected_at_max": (
            max(selected_times).isoformat().replace("+00:00", "Z") if selected_times else None
        ),
        "max_pending_age_seconds": (
            round(max_age_seconds, 6) if max_age_seconds is not None else None
        ),
    }


def _accounting_alias_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_kind_counts: dict[str, int] = {}
    target_field_counts: dict[str, int] = {}
    source_field_counts: dict[str, int] = {}
    target_field_counts_by_source_kind: dict[str, dict[str, int]] = {}
    source_field_counts_by_source_kind: dict[str, dict[str, int]] = {}
    rows_with_aliases_by_source_kind: dict[str, int] = {}
    rows_with_aliases = 0

    for row in rows:
        source_kind = str(row.get("_producer_source_kind") or "UNKNOWN")
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        aliases = row.get("_producer_normalized_accounting_aliases")
        if not isinstance(aliases, list) or not aliases:
            continue
        rows_with_aliases += 1
        rows_with_aliases_by_source_kind[source_kind] = (
            rows_with_aliases_by_source_kind.get(source_kind, 0) + 1
        )
        source_kind_targets = target_field_counts_by_source_kind.setdefault(source_kind, {})
        source_kind_sources = source_field_counts_by_source_kind.setdefault(source_kind, {})
        for alias in aliases:
            if not isinstance(alias, dict):
                continue
            target = str(alias.get("target_field") or "__missing__")
            source = str(alias.get("source_field") or "__missing__")
            target_field_counts[target] = target_field_counts.get(target, 0) + 1
            source_field_counts[source] = source_field_counts.get(source, 0) + 1
            source_kind_targets[target] = source_kind_targets.get(target, 0) + 1
            source_kind_sources[source] = source_kind_sources.get(source, 0) + 1

    return {
        "status": "READY_ACCOUNTING_ALIAS_SUMMARY",
        "processed_source_row_count": len(rows),
        "rows_with_normalized_aliases_count": rows_with_aliases,
        "source_kind_counts": {
            key: source_kind_counts[key] for key in sorted(source_kind_counts)
        },
        "rows_with_aliases_by_source_kind": {
            key: rows_with_aliases_by_source_kind[key]
            for key in sorted(rows_with_aliases_by_source_kind)
        },
        "target_field_counts": {
            key: target_field_counts[key] for key in sorted(target_field_counts)
        },
        "source_field_counts": {
            key: source_field_counts[key] for key in sorted(source_field_counts)
        },
        "target_field_counts_by_source_kind": {
            source_kind: {
                key: target_counts[key]
                for key in sorted(target_counts)
            }
            for source_kind, target_counts in sorted(target_field_counts_by_source_kind.items())
        },
        "source_field_counts_by_source_kind": {
            source_kind: {
                key: source_counts[key]
                for key in sorted(source_counts)
            }
            for source_kind, source_counts in sorted(source_field_counts_by_source_kind.items())
        },
        "note": (
            "Counts producer-only decision-time accounting alias normalization. "
            "Outcome fields are not created here."
        ),
    }


def _selector_context_alias_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_kind_counts: dict[str, int] = {}
    target_field_counts: dict[str, int] = {}
    source_field_counts: dict[str, int] = {}
    target_field_counts_by_source_kind: dict[str, dict[str, int]] = {}
    source_field_counts_by_source_kind: dict[str, dict[str, int]] = {}
    rows_with_aliases_by_source_kind: dict[str, int] = {}
    rows_with_aliases = 0

    for row in rows:
        source_kind = str(row.get("_producer_source_kind") or "UNKNOWN")
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        aliases = row.get("_producer_normalized_selector_context_aliases")
        if not isinstance(aliases, list) or not aliases:
            continue
        rows_with_aliases += 1
        rows_with_aliases_by_source_kind[source_kind] = (
            rows_with_aliases_by_source_kind.get(source_kind, 0) + 1
        )
        source_kind_targets = target_field_counts_by_source_kind.setdefault(source_kind, {})
        source_kind_sources = source_field_counts_by_source_kind.setdefault(source_kind, {})
        for alias in aliases:
            if not isinstance(alias, dict):
                continue
            target = str(alias.get("target_field") or "__missing__")
            source = str(alias.get("source_field") or "__missing__")
            target_field_counts[target] = target_field_counts.get(target, 0) + 1
            source_field_counts[source] = source_field_counts.get(source, 0) + 1
            source_kind_targets[target] = source_kind_targets.get(target, 0) + 1
            source_kind_sources[source] = source_kind_sources.get(source, 0) + 1

    return {
        "status": "READY_SELECTOR_CONTEXT_ALIAS_SUMMARY",
        "processed_source_row_count": len(rows),
        "rows_with_normalized_aliases_count": rows_with_aliases,
        "source_kind_counts": {
            key: source_kind_counts[key] for key in sorted(source_kind_counts)
        },
        "rows_with_aliases_by_source_kind": {
            key: rows_with_aliases_by_source_kind[key]
            for key in sorted(rows_with_aliases_by_source_kind)
        },
        "target_field_counts": {
            key: target_field_counts[key] for key in sorted(target_field_counts)
        },
        "source_field_counts": {
            key: source_field_counts[key] for key in sorted(source_field_counts)
        },
        "target_field_counts_by_source_kind": {
            source_kind: {
                key: target_counts[key]
                for key in sorted(target_counts)
            }
            for source_kind, target_counts in sorted(target_field_counts_by_source_kind.items())
        },
        "source_field_counts_by_source_kind": {
            source_kind: {
                key: source_counts[key]
                for key in sorted(source_counts)
            }
            for source_kind, source_counts in sorted(source_field_counts_by_source_kind.items())
        },
        "note": (
            "Counts producer-only decision-time selector-context alias normalization. "
            "Labels are preserved exactly from source fields and are not mapped to "
            "passing bucket values."
        ),
    }


def _rejection_ledger_summary(rejected_path: Path) -> dict[str, Any]:
    rows, source_status = _iter_jsonl(rejected_path)
    reason_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    source_kind_reason_counts: dict[str, dict[str, int]] = {}
    combination_counts: dict[str, int] = {}
    candidate_identity_counts: dict[str, int] = {}
    missing_candidate_identity_count = 0
    samples_by_reason: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        candidate_identity = row.get("candidate_identity")
        if candidate_identity in {None, ""}:
            missing_candidate_identity_count += 1
        else:
            candidate_identity_text = str(candidate_identity)
            candidate_identity_counts[candidate_identity_text] = (
                candidate_identity_counts.get(candidate_identity_text, 0) + 1
            )
        raw_reasons = row.get("reasons")
        reasons = sorted({
            str(reason)
            for reason in raw_reasons
            if reason not in {None, ""}
        }) if isinstance(raw_reasons, list) else []
        if not reasons:
            reasons = ["NO_REASONS_RECORDED"]
        source_kind = str(row.get("source_kind") or row.get("scope") or "UNKNOWN")
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        source_reasons = source_kind_reason_counts.setdefault(source_kind, {})
        combination_key = "|".join(reasons)
        combination_counts[combination_key] = combination_counts.get(combination_key, 0) + 1
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            source_reasons[reason] = source_reasons.get(reason, 0) + 1
            samples = samples_by_reason.setdefault(reason, [])
            if len(samples) < 3:
                samples.append({
                    "candidate_identity": row.get("candidate_identity"),
                    "source_kind": row.get("source_kind"),
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "side": row.get("side"),
                    "decision_time": row.get("decision_time"),
                })

    top_combinations = sorted(
        (
            {"reasons": key.split("|"), "row_count": count}
            for key, count in combination_counts.items()
        ),
        key=lambda item: (-int(item["row_count"]), item["reasons"]),
    )[:20]
    top_reasons = sorted(
        (
            {"reason": reason, "row_count": count}
            for reason, count in reason_counts.items()
        ),
        key=lambda item: (-int(item["row_count"]), item["reason"]),
    )[:20]
    duplicated_identity_sample = sorted(
        (
            {"candidate_identity": identity, "row_count": count}
            for identity, count in candidate_identity_counts.items()
            if count > 1
        ),
        key=lambda item: (-int(item["row_count"]), item["candidate_identity"]),
    )[:20]
    duplicate_candidate_identity_row_count = sum(
        count - 1 for count in candidate_identity_counts.values() if count > 1
    )
    duplicated_candidate_identity_count = sum(
        1 for count in candidate_identity_counts.values() if count > 1
    )
    return {
        "source_status": source_status,
        "row_count": len(rows),
        "unique_candidate_identity_count": len(candidate_identity_counts),
        "missing_candidate_identity_count": missing_candidate_identity_count,
        "duplicated_candidate_identity_count": duplicated_candidate_identity_count,
        "duplicate_candidate_identity_row_count": duplicate_candidate_identity_row_count,
        "reason_counts": {
            key: reason_counts[key]
            for key in sorted(reason_counts)
        },
        "top_rejection_reasons": top_reasons,
        "source_kind_counts": {
            key: source_kind_counts[key]
            for key in sorted(source_kind_counts)
        },
        "source_kind_reason_counts": {
            source_kind: {
                reason: reason_counts_by_source[reason]
                for reason in sorted(reason_counts_by_source)
            }
            for source_kind, reason_counts_by_source in sorted(source_kind_reason_counts.items())
        },
        "top_reason_combinations": top_combinations,
        "duplicated_candidate_identity_sample": duplicated_identity_sample,
        "samples_by_reason": {
            key: samples_by_reason[key]
            for key in sorted(samples_by_reason)
        },
    }


def _holdout_evidence_acquisition_status(
    *,
    registry_preflight: dict[str, Any],
    candidate_audit: dict[str, Any],
    promotion_packet: dict[str, Any],
    accepted_count: int,
    pending_count: int,
) -> dict[str, Any]:
    promotion_summary = promotion_packet.get("promotion_readiness_summary")
    promotion_summary = promotion_summary if isinstance(promotion_summary, dict) else {}
    clean_windows = promotion_packet.get("clean_no_overlap_registry_windows")
    clean_windows = clean_windows if isinstance(clean_windows, list) else []
    clean_registered_identity_count = sum(
        int(window.get("registered_source_row_identity_hash_count") or 0)
        for window in clean_windows
        if isinstance(window, dict)
    )
    preflight_windows = registry_preflight.get("windows")
    preflight_windows = preflight_windows if isinstance(preflight_windows, list) else []
    static_reason_counts: dict[str, int] = {}
    for window in preflight_windows:
        if not isinstance(window, dict):
            continue
        weight = int(window.get("matching_source_row_count") or 0) or 1
        static_reasons = window.get("static_reasons")
        if not isinstance(static_reasons, list):
            continue
        for reason in static_reasons:
            if reason in {None, ""}:
                continue
            reason_text = str(reason)
            static_reason_counts[reason_text] = static_reason_counts.get(reason_text, 0) + weight

    global_reasons = registry_preflight.get("global_reasons")
    global_reasons = [
        str(reason)
        for reason in global_reasons
        if reason not in {None, ""}
    ] if isinstance(global_reasons, list) else []
    missing_untouched_attestation = any(
        reason.startswith("HOLDOUT_EXCLUSION_PROOF_ATTESTATION_MISSING_")
        for reason in static_reason_counts
    ) or bool(
        clean_registered_identity_count
        and registry_preflight.get("statically_eligible_window_count") == 0
    )

    if accepted_count > 0:
        status = "READY_HOLDOUT_FINAL_ROWS_APPENDED"
    elif pending_count > 0:
        status = "READY_HOLDOUT_PENDING_SELECTIONS_APPENDED"
    elif registry_preflight.get("status") == "READY_HOLDOUT_REGISTRY_PREFLIGHT":
        status = "READY_HOLDOUT_REGISTRY_CAN_APPEND_PENDING_SELECTIONS"
    elif clean_registered_identity_count > 0 and missing_untouched_attestation:
        status = "NO_GO_HOLDOUT_CLEAN_NO_OVERLAP_ROWS_REQUIRE_UNTOUCHED_ATTESTATION"
    elif int(promotion_summary.get("draft_decision_time_candidate_ready_count") or 0) > 0:
        status = "NO_GO_HOLDOUT_DRAFT_CANDIDATES_REQUIRE_CLEAN_PROMOTION"
    elif "NO_REGISTERED_HOLDOUT_WINDOWS" in global_reasons:
        status = "NO_GO_HOLDOUT_NO_REGISTERED_WINDOWS"
    else:
        status = "NO_GO_HOLDOUT_NO_DECISION_TIME_A_GRADE_ROWS_READY"

    next_required_actions: list[str] = []
    if status == "NO_GO_HOLDOUT_CLEAN_NO_OVERLAP_ROWS_REQUIRE_UNTOUCHED_ATTESTATION":
        next_required_actions.append(
            "Provide independent PASSED_UNTOUCHED attestation and promote the clean no-overlap registry windows."
        )
    if status == "NO_GO_HOLDOUT_DRAFT_CANDIDATES_REQUIRE_CLEAN_PROMOTION":
        next_required_actions.append(
            "Promote only clean no-overlap draft windows after untouched attestation; do not use outcome fields."
        )
    if status == "NO_GO_HOLDOUT_NO_REGISTERED_WINDOWS":
        next_required_actions.append(
            "Pre-register untouched historical windows before running holdout evidence collection."
        )
    if status == "READY_HOLDOUT_REGISTRY_CAN_APPEND_PENDING_SELECTIONS":
        next_required_actions.append(
            "Run the holdout producer to append pending selections before labeling outcomes in a later pass."
        )
    if status == "READY_HOLDOUT_PENDING_SELECTIONS_APPENDED":
        next_required_actions.append(
            "Run the holdout producer again only against the same pre-registered window set to label preexisting pending selections."
        )
    if not next_required_actions:
        next_required_actions.append(
            "Continue registering genuinely untouched windows with frozen-policy A-grade decision-time candidates."
        )

    return {
        "status": status,
        "scope": "holdout",
        "countable_rows_appended_count": accepted_count,
        "pending_rows_appended_count": pending_count,
        "registered_window_count": registry_preflight.get("registered_window_count"),
        "statically_eligible_window_count": registry_preflight.get(
            "statically_eligible_window_count"
        ),
        "registered_matching_source_row_count": registry_preflight.get(
            "matching_source_row_count"
        ),
        "registered_decision_time_candidate_ready_count": registry_preflight.get(
            "decision_time_candidate_ready_count"
        ),
        "registered_countable_after_label_count": registry_preflight.get(
            "countable_after_label_count"
        ),
        "registered_overlap_row_count": registry_preflight.get("overlap_row_count"),
        "preflight_global_reasons": global_reasons,
        "registered_window_static_reason_counts": {
            key: static_reason_counts[key]
            for key in sorted(static_reason_counts)
        },
        "draft_window_count": candidate_audit.get("draft_window_count"),
        "draft_decision_time_candidate_ready_count": promotion_summary.get(
            "draft_decision_time_candidate_ready_count"
        ),
        "draft_decision_time_ready_no_overlap_count": promotion_summary.get(
            "draft_decision_time_ready_no_overlap_count"
        ),
        "draft_decision_time_ready_row_level_no_overlap_count": promotion_summary.get(
            "draft_decision_time_ready_row_level_no_overlap_count"
        ),
        "clean_no_overlap_registry_template_count": promotion_summary.get(
            "clean_no_overlap_registry_template_count"
        ),
        "clean_no_overlap_registered_identity_count": clean_registered_identity_count,
        "packet_is_countable_evidence": promotion_packet.get("packet_is_countable_evidence"),
        "selection_uses_outcome_fields": promotion_packet.get("selection_uses_outcome_fields"),
        "readiness_uses_outcome_fields": promotion_packet.get("readiness_uses_outcome_fields"),
        "next_required_actions": next_required_actions,
    }


def _realtime_evidence_acquisition_status(
    *,
    source_gate_breakdown: dict[str, Any],
    source_readiness_summary: dict[str, Any],
    paper_allocation_diagnostics: dict[str, Any],
    selector_source_contract_diagnostics: dict[str, Any],
    lineage_bridge_diagnostics: dict[str, Any] | None = None,
    accepted_count: int,
    pending_count: int,
) -> dict[str, Any]:
    lineage_bridge_diagnostics = lineage_bridge_diagnostics or {}
    full_fidelity_count = int(
        paper_allocation_diagnostics.get(
            "full_fidelity_frozen_candidate_allocation_count"
        )
        or 0
    )
    low_fidelity_count = int(
        paper_allocation_diagnostics.get("low_fidelity_candidate_allocation_count") or 0
    )
    ready_full_count = int(
        paper_allocation_diagnostics.get("ready_full_candidate_allocation_count") or 0
    )
    ready_gate_count = int(
        paper_allocation_diagnostics.get("ready_for_pending_gate_count") or 0
    )
    allocator_allowed_by_fidelity = paper_allocation_diagnostics.get(
        "allocator_allowed_count_by_fidelity"
    )
    allocator_allowed_by_fidelity = (
        allocator_allowed_by_fidelity
        if isinstance(allocator_allowed_by_fidelity, dict)
        else {}
    )
    full_fidelity_allocator_allowed_count = int(
        allocator_allowed_by_fidelity.get(
            "full_fidelity_frozen_candidate_allocation"
        )
        or 0
    )
    low_fidelity_allocator_allowed_count = int(
        allocator_allowed_by_fidelity.get(
            "low_fidelity_candidate_allocation_missing_fingerprint"
        )
        or 0
    )
    source_ready_count = int(
        source_readiness_summary.get("candidate_ready_source_row_count") or 0
    )
    source_gate_ready_count = int(
        source_gate_breakdown.get("candidate_ready_source_row_count") or 0
    )
    allocation_row_count = int(
        paper_allocation_diagnostics.get("allocation_row_count") or 0
    )
    candidate_allocation_count = int(
        paper_allocation_diagnostics.get("candidate_allocation_count") or 0
    )

    if accepted_count > 0:
        status = "READY_REALTIME_FINAL_ROWS_APPENDED"
    elif pending_count > 0:
        status = "READY_REALTIME_PENDING_SELECTIONS_APPENDED"
    elif source_ready_count > 0 or source_gate_ready_count > 0:
        status = "READY_REALTIME_SOURCE_CAN_APPEND_PENDING_SELECTIONS"
    elif ready_full_count > 0 or ready_gate_count > 0:
        status = "NO_GO_REALTIME_READY_ALLOCATIONS_NOT_APPENDED"
    elif full_fidelity_count > 0 and full_fidelity_allocator_allowed_count == 0:
        status = "NO_GO_REALTIME_FROZEN_CANDIDATES_ALLOCATOR_BLOCKED"
    elif full_fidelity_count == 0 and low_fidelity_allocator_allowed_count > 0:
        status = "NO_GO_REALTIME_ALLOWED_ALLOCATIONS_MISSING_FROZEN_FINGERPRINT"
    elif candidate_allocation_count == 0:
        status = "NO_GO_REALTIME_NO_CANDIDATE_ALLOCATIONS_EXPOSED"
    elif allocation_row_count == 0:
        status = "NO_GO_REALTIME_NO_ALLOCATION_ROWS_EXPOSED"
    else:
        status = "NO_GO_REALTIME_NO_GATE_READY_FROZEN_CANDIDATES"

    next_required_actions: list[str] = []
    if status == "NO_GO_REALTIME_FROZEN_CANDIDATES_ALLOCATOR_BLOCKED":
        next_required_actions.append(
            "Wait for frozen-policy A_GRADE_EXECUTION_PAPER candidates that the allocator admits with size."
        )
    if status == "NO_GO_REALTIME_ALLOWED_ALLOCATIONS_MISSING_FROZEN_FINGERPRINT":
        next_required_actions.append(
            "Do not count allocator-allowed rows unless the frozen selector policy fingerprint is present and matches."
        )
    if status in {
        "NO_GO_REALTIME_NO_CANDIDATE_ALLOCATIONS_EXPOSED",
        "NO_GO_REALTIME_NO_ALLOCATION_ROWS_EXPOSED",
    }:
        next_required_actions.append(
            "Keep the paper-only loop publishing full candidate allocations before running the realtime producer."
        )
    if status == "READY_REALTIME_SOURCE_CAN_APPEND_PENDING_SELECTIONS":
        next_required_actions.append(
            "Run the realtime producer to append immutable pending selections before any outcome label is known."
        )
    if status == "READY_REALTIME_PENDING_SELECTIONS_APPENDED":
        next_required_actions.append(
            "Continue paper-only execution and label only preexisting pending selections after positions close."
        )
    if not next_required_actions:
        next_required_actions.append(
            "Continue paper-only collection until frozen-policy A-grade candidates pass all evidence gates."
        )

    return {
        "status": status,
        "scope": "realtime",
        "countable_rows_appended_count": accepted_count,
        "pending_rows_appended_count": pending_count,
        "processed_source_row_count": source_readiness_summary.get(
            "processed_source_row_count"
        ),
        "candidate_ready_source_row_count": source_ready_count,
        "source_gate_candidate_ready_source_row_count": source_gate_ready_count,
        "source_gate_rejected_source_row_count": source_gate_breakdown.get(
            "rejected_source_row_count"
        ),
        "source_gate_category_counts": source_gate_breakdown.get("category_counts"),
        "source_gate_reason_counts": source_gate_breakdown.get("reason_counts"),
        "source_gate_top_reason_combinations": source_gate_breakdown.get(
            "top_reason_combinations"
        ),
        "allocation_diagnostics_status": paper_allocation_diagnostics.get("status"),
        "allocation_row_count": allocation_row_count,
        "candidate_allocation_count": candidate_allocation_count,
        "full_fidelity_frozen_candidate_allocation_count": full_fidelity_count,
        "low_fidelity_candidate_allocation_count": low_fidelity_count,
        "full_fidelity_frozen_allocator_allowed_count": (
            full_fidelity_allocator_allowed_count
        ),
        "low_fidelity_allocator_allowed_count": low_fidelity_allocator_allowed_count,
        "ready_for_pending_gate_count": ready_gate_count,
        "ready_full_candidate_allocation_count": ready_full_count,
        "ready_for_pending_gate_count_by_fidelity": paper_allocation_diagnostics.get(
            "ready_for_pending_gate_count_by_fidelity"
        ),
        "allocator_decision_counts_by_fidelity": paper_allocation_diagnostics.get(
            "allocator_decision_counts_by_fidelity"
        ),
        "stage_blocked_row_counts": source_readiness_summary.get(
            "stage_blocked_row_counts"
        ),
        "selector_source_contract_status": selector_source_contract_diagnostics.get(
            "status"
        ),
        "lineage_bridge_status": lineage_bridge_diagnostics.get("status"),
        "low_fidelity_allowed_allocations_with_lineage_bridge_count": (
            lineage_bridge_diagnostics.get("allocations_with_bridge_match_count")
        ),
        "low_fidelity_allowed_allocations_bridge_contract_complete_count": (
            lineage_bridge_diagnostics.get("allocations_bridge_contract_complete_count")
        ),
        "low_fidelity_allowed_missing_after_bridge_field_counts": (
            lineage_bridge_diagnostics.get("missing_after_bridge_field_counts")
        ),
        "selection_uses_outcome_fields": False,
        "future_labels_used_as_features_allowed": False,
        "next_required_actions": next_required_actions,
    }


def _rejection_reason_category(reason: str) -> str:
    if reason.startswith("MISSING_ACCOUNTING_"):
        return "accounting"
    if reason in {
        "DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE",
        "NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE",
        "NON_DIRECTIONAL_SIDE",
        "ALLOCATOR_BLOCKED_CANDIDATE",
        "SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING",
        "A_GRADE_HALTED_BY_CONTINUOUS_EDGE_GUARDIAN",
    }:
        return "frozen_selector"
    if (
        reason.startswith("MISSING_")
        or "_AFTER_" in reason
        or reason in {"FUTURE_LABELS_USED_AS_FEATURES"}
    ):
        return "point_in_time_lineage"
    if "FINGERPRINT" in reason:
        return "fingerprint"
    if reason.startswith("REALTIME_SOURCE_"):
        return "safety"
    if (
        reason.startswith("REALTIME_PENDING_SOURCE_")
        or "PENDING_SELECTION" in reason
        or "HISTORICAL_SOURCE" in reason
        or "CLOSED_OUTCOME" in reason
        or "SOURCE_KIND_NOT_ELIGIBLE" in reason
        or "CANDIDATE_SELECTED" in reason
        or "CANDIDATE_SELECTION" in reason
        or reason.startswith("HOLDOUT_")
        or reason.startswith("NO_PRE_REGISTERED_HOLDOUT")
    ):
        return "evidence_protocol"
    return "other"


def _new_source_gate_breakdown(*, processed_source_row_count: int) -> dict[str, Any]:
    return {
        "processed_source_row_count": processed_source_row_count,
        "existing_final_duplicate_count": 0,
        "candidate_ready_source_row_count": 0,
        "rejected_source_row_count": 0,
        "category_counts": {},
        "reason_counts": {},
        "_combination_counts": {},
    }


def _record_source_gate_result(
    breakdown: dict[str, Any],
    *,
    reasons: list[str],
) -> None:
    if not reasons:
        breakdown["candidate_ready_source_row_count"] += 1
        return
    breakdown["rejected_source_row_count"] += 1
    category_counts = breakdown["category_counts"]
    reason_counts = breakdown["reason_counts"]
    for reason in reasons:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        category = _rejection_reason_category(reason)
        category_counts[category] = category_counts.get(category, 0) + 1
    combination_key = "|".join(sorted(reasons))
    combinations = breakdown["_combination_counts"]
    combinations[combination_key] = combinations.get(combination_key, 0) + 1


def _finalize_source_gate_breakdown(breakdown: dict[str, Any]) -> dict[str, Any]:
    combinations = breakdown.pop("_combination_counts", {})
    breakdown["category_counts"] = {
        key: breakdown["category_counts"][key]
        for key in sorted(breakdown["category_counts"])
    }
    breakdown["reason_counts"] = {
        key: breakdown["reason_counts"][key]
        for key in sorted(breakdown["reason_counts"])
    }
    breakdown["top_reason_combinations"] = sorted(
        (
            {"reasons": key.split("|"), "row_count": count}
            for key, count in combinations.items()
        ),
        key=lambda item: (-int(item["row_count"]), item["reasons"]),
    )[:20]
    return breakdown


REALTIME_READINESS_STAGES = (
    "fingerprint",
    "point_in_time_lineage",
    "frozen_selector",
    "accounting",
    "safety",
    "evidence_protocol",
    "other",
)
SELECTOR_BUCKET_KEY_FIELDS = (
    "strategy",
    "side",
    "symbol_cluster",
    "timeframe",
    "market_regime",
    "volatility_bucket",
    "liquidity_bucket",
    "confidence_bucket",
    "expected_move_bucket",
)
LINEAGE_BRIDGE_REQUIRED_FIELD_GROUPS = {
    "selector_policy_fingerprint": (
        "selector_policy_fingerprint",
        "frozen_selector_fingerprint",
        "policy_fingerprint",
    ),
    "candidate_selection_tier": (
        "candidate_selection_tier",
        "paper_opportunity_tier",
        "explicit_paper_opportunity_tier",
        "admission_tier",
        "candidate_tier",
    ),
    "decision_time": ("decision_time", "entry_feature_decision_time"),
    "generated_at": ("generated_at", "entry_feature_generated_at"),
    "available_at": ("available_at", "entry_feature_available_at"),
    "feature_cutoff": ("feature_cutoff", "entry_feature_cutoff"),
    "symbol": ("symbol",),
    "timeframe": ("timeframe",),
    "side": ("side", "action", "selected_action", "proposed_action"),
    "strategy": ("strategy", "strategy_family", "source_strategy"),
    "market_regime": ("market_regime", "regime", "regime_label", "market_state"),
}
LINEAGE_BRIDGE_ALIAS_FIELDS = (
    "prediction_id",
    "entry_prediction_id",
    "source_prediction_id",
    "signal_id",
    "entry_signal_id",
    "source_signal_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "decision_id",
    "execution_intent_id",
    "feature_snapshot_id",
    "entry_feature_snapshot_id",
)
PAPER_LOOP_ALLOCATION_EXTRACTIONS = {
    "paper_loop_once_candidate_allocation",
    "paper_loop_once_sample_allocation",
}


def _sorted_counts(mapping: dict[str, int]) -> dict[str, int]:
    return {key: mapping[key] for key in sorted(mapping)}


def _new_realtime_source_readiness_summary(*, processed_source_row_count: int) -> dict[str, Any]:
    return {
        "status": "READY_REALTIME_SOURCE_READINESS_SUMMARY",
        "processed_source_row_count": processed_source_row_count,
        "existing_final_duplicate_count": 0,
        "candidate_ready_source_row_count": 0,
        "source_kind_counts": {},
        "candidate_ready_by_source_kind": {},
        "existing_final_duplicate_by_source_kind": {},
        "stage_pass_counts": {stage: 0 for stage in REALTIME_READINESS_STAGES},
        "stage_blocked_row_counts": {stage: 0 for stage in REALTIME_READINESS_STAGES},
        "stage_pass_counts_by_source_kind": {},
        "stage_blocked_row_counts_by_source_kind": {},
        "note": (
            "Diagnostic only. Rows still require zero rejection reasons before they can create "
            "pending or final evidence."
        ),
    }


def _increment_counter(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    mapping[key] = mapping.get(key, 0) + amount


def _kind_stage_counts(
    summary: dict[str, Any],
    field: str,
    source_kind: str,
) -> dict[str, int]:
    by_kind = summary.setdefault(field, {})
    stage_counts = by_kind.setdefault(
        source_kind,
        {stage: 0 for stage in REALTIME_READINESS_STAGES},
    )
    return stage_counts


def _record_realtime_source_readiness(
    summary: dict[str, Any],
    *,
    row: dict[str, Any],
    reasons: list[str],
    existing_final_duplicate: bool = False,
) -> None:
    source_kind = str(row.get("_producer_source_kind") or "UNKNOWN")
    _increment_counter(summary["source_kind_counts"], source_kind)
    if existing_final_duplicate:
        summary["existing_final_duplicate_count"] += 1
        _increment_counter(summary["existing_final_duplicate_by_source_kind"], source_kind)
        return

    categories = {_rejection_reason_category(reason) for reason in reasons}
    if not reasons:
        summary["candidate_ready_source_row_count"] += 1
        _increment_counter(summary["candidate_ready_by_source_kind"], source_kind)

    source_pass_counts = _kind_stage_counts(
        summary,
        "stage_pass_counts_by_source_kind",
        source_kind,
    )
    source_blocked_counts = _kind_stage_counts(
        summary,
        "stage_blocked_row_counts_by_source_kind",
        source_kind,
    )
    for stage in REALTIME_READINESS_STAGES:
        if stage in categories:
            summary["stage_blocked_row_counts"][stage] += 1
            source_blocked_counts[stage] += 1
        else:
            summary["stage_pass_counts"][stage] += 1
            source_pass_counts[stage] += 1


def _finalize_realtime_source_readiness_summary(summary: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "source_kind_counts",
        "candidate_ready_by_source_kind",
        "existing_final_duplicate_by_source_kind",
    ):
        summary[field] = {
            key: summary[field][key]
            for key in sorted(summary[field])
        }
    for field in (
        "stage_pass_counts_by_source_kind",
        "stage_blocked_row_counts_by_source_kind",
    ):
        summary[field] = {
            source_kind: {
                stage: counts.get(stage, 0)
                for stage in REALTIME_READINESS_STAGES
            }
            for source_kind, counts in sorted(summary[field].items())
        }
    summary["stage_pass_counts"] = {
        stage: summary["stage_pass_counts"].get(stage, 0)
        for stage in REALTIME_READINESS_STAGES
    }
    summary["stage_blocked_row_counts"] = {
        stage: summary["stage_blocked_row_counts"].get(stage, 0)
        for stage in REALTIME_READINESS_STAGES
    }
    return summary


def _paper_event_source_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    event_rows = [
        row
        for row in rows
        if str(row.get("_producer_source_path") or "").endswith("paper_events.jsonl")
    ]
    ledger_action_counts: dict[str, int] = {}
    outcome_like_counts: dict[str, int] = {}
    recognized_outcome_counts: dict[str, int] = {}
    feature_snapshot_ids: set[str] = set()
    timing_counts = {
        "decision_time": 0,
        "generated_at": 0,
        "available_at": 0,
        "feature_cutoff": 0,
    }
    selector_dimension_counts = {
        "timeframe": 0,
        "directional_side": 0,
        "positive_after_cost_edge": 0,
    }
    for row in event_rows:
        ledger_action = str(row.get("ledger_action") or "__missing__")
        ledger_action_counts[ledger_action] = ledger_action_counts.get(ledger_action, 0) + 1
        feature_snapshot_id = row.get("feature_snapshot_id")
        if feature_snapshot_id not in {None, ""}:
            feature_snapshot_ids.add(str(feature_snapshot_id))
        for field in timing_counts:
            if row.get(field) not in {None, ""}:
                timing_counts[field] += 1
        if row.get("timeframe") not in {None, ""}:
            selector_dimension_counts["timeframe"] += 1
        if status_module._directional_side(row) in {"long", "short"}:
            selector_dimension_counts["directional_side"] += 1
        edge = status_module._expected_edge_bps(row)
        if edge is not None and edge > 0.0:
            selector_dimension_counts["positive_after_cost_edge"] += 1
        for field in PAPER_EVENT_OUTCOME_LIKE_FIELDS:
            if row.get(field) not in {None, ""}:
                outcome_like_counts[field] = outcome_like_counts.get(field, 0) + 1
        for field in PAPER_EVENT_RECOGNIZED_CLOSED_OUTCOME_FIELDS:
            if row.get(field) not in {None, ""}:
                recognized_outcome_counts[field] = recognized_outcome_counts.get(field, 0) + 1
    return {
        "status": (
            "READY_PAPER_EVENT_SOURCE_DIAGNOSTICS"
            if event_rows
            else "NO_PAPER_EVENT_ROWS_PROCESSED"
        ),
        "diagnostic_only": True,
        "counts_as_pending_or_final_evidence": False,
        "processed_paper_event_row_count": len(event_rows),
        "ledger_action_counts": {
            key: ledger_action_counts[key] for key in sorted(ledger_action_counts)
        },
        "rows_with_feature_snapshot_id_count": sum(
            1 for row in event_rows if row.get("feature_snapshot_id") not in {None, ""}
        ),
        "unique_feature_snapshot_id_count": len(feature_snapshot_ids),
        "timing_field_presence_counts": timing_counts,
        "selector_dimension_presence_counts": selector_dimension_counts,
        "outcome_like_field_presence_counts": {
            key: outcome_like_counts[key] for key in sorted(outcome_like_counts)
        },
        "recognized_closed_outcome_field_presence_counts": {
            key: recognized_outcome_counts[key]
            for key in sorted(recognized_outcome_counts)
        },
        "not_mapped_to_reconciled_outcome_fields": list(PAPER_EVENT_OUTCOME_LIKE_FIELDS),
        "note": (
            "paper_events.jsonl rows are diagnostic source events. paper_realized_pnl, "
            "paper_pnl_delta, paper_result, gross_pnl_usdt, and realized_delta_usdt are "
            "not normalized into realized_pnl_usd because they are not proven immutable "
            "closed-position outcome records with preexisting pending selections."
        ),
    }


def _realtime_source_safety_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("paper_only") is not True:
        if row.get("paper_only") in {None, ""}:
            reasons.append("REALTIME_SOURCE_PAPER_ONLY_FLAG_MISSING")
        else:
            reasons.append("REALTIME_SOURCE_NOT_PAPER_ONLY")
    real_order_values = (
        row.get("places_real_order"),
        row.get("live_order"),
    )
    if all(value in {None, ""} for value in real_order_values):
        reasons.append("REALTIME_SOURCE_REAL_ORDER_FLAG_MISSING")
    if row.get("places_real_order") is True or row.get("live_order") is True:
        reasons.append("REALTIME_SOURCE_REAL_ORDER_FLAG_TRUE")
    if row.get("test_order") is True or row.get("test_orders") is True:
        reasons.append("REALTIME_SOURCE_TEST_ORDER_FLAG_TRUE")
    if row.get("leverage_mutation") is True:
        reasons.append("REALTIME_SOURCE_LEVERAGE_MUTATION_TRUE")
    if row.get("margin_mode_mutation") is True:
        reasons.append("REALTIME_SOURCE_MARGIN_MODE_MUTATION_TRUE")
    if row.get("legacy_redis_write") is True or row.get("writes_legacy_redis") is True:
        reasons.append("REALTIME_SOURCE_OLD_REDIS_WRITE_TRUE")
    return reasons


def _paper_allocation_safety_reasons(row: dict[str, Any]) -> list[str]:
    return _realtime_source_safety_reasons(row)


def _closed_outcome_safety_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("paper_only") is False:
        reasons.append("REALTIME_SOURCE_NOT_PAPER_ONLY")
    if row.get("places_real_order") is True or row.get("live_order") is True:
        reasons.append("REALTIME_SOURCE_REAL_ORDER_FLAG_TRUE")
    if row.get("test_order") is True or row.get("test_orders") is True:
        reasons.append("REALTIME_SOURCE_TEST_ORDER_FLAG_TRUE")
    if row.get("leverage_mutation") is True:
        reasons.append("REALTIME_SOURCE_LEVERAGE_MUTATION_TRUE")
    if row.get("margin_mode_mutation") is True:
        reasons.append("REALTIME_SOURCE_MARGIN_MODE_MUTATION_TRUE")
    if row.get("legacy_redis_write") is True or row.get("writes_legacy_redis") is True:
        reasons.append("REALTIME_SOURCE_OLD_REDIS_WRITE_TRUE")
    return reasons


def _paper_allocation_protocol_reasons(
    row: dict[str, Any],
    *,
    generated_utc: str,
) -> list[str]:
    reasons: list[str] = []
    source_kind = str(row.get("_producer_source_kind") or "")
    if source_kind and source_kind not in PENDING_ELIGIBLE_SOURCE_KINDS:
        reasons.append("SOURCE_KIND_NOT_ELIGIBLE_TO_CREATE_PENDING_RECORD")
    source_age_seconds = _realtime_pending_source_age_seconds(row, generated_utc=generated_utc)
    if source_age_seconds is None:
        reasons.append("REALTIME_PENDING_SOURCE_FRESHNESS_TIMESTAMP_MISSING")
    elif source_age_seconds < -MAX_REALTIME_PENDING_SOURCE_CLOCK_SKEW_SECONDS:
        reasons.append("REALTIME_PENDING_SOURCE_TIMESTAMP_AFTER_PRODUCER_RUN")
    elif source_age_seconds > MAX_REALTIME_PENDING_SOURCE_AGE_SECONDS:
        reasons.append("REALTIME_PENDING_SOURCE_STALE_FOR_NEW_PENDING_RECORD")
    if _has_realtime_outcome(row):
        reasons.append("PAPER_ALLOCATION_SOURCE_CONTAINS_OUTCOME_FIELD")
    return reasons


def _paper_allocation_gate_reasons(
    row: dict[str, Any],
    *,
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    generated_utc: str,
) -> list[str]:
    selection_row = _without_outcome_fields(row)
    reasons: list[str] = []
    reasons.extend(
        _fingerprint_reject_reasons(
            selection_row,
            expected_fingerprint=expected_fingerprint,
        )
    )
    reasons.extend(_post_outcome_selection_reasons(selection_row))
    reasons.extend(
        _selector_reject_reasons(
            selection_row,
            eligible_bucket_keys=eligible_bucket_keys,
        )
    )
    reasons.extend(_accounting_reject_reasons(selection_row))
    reasons.extend(_paper_allocation_safety_reasons(selection_row))
    reasons.extend(
        _paper_allocation_protocol_reasons(selection_row, generated_utc=generated_utc)
    )
    return sorted(set(reasons))


def _paper_allocation_fidelity_bucket(
    row: dict[str, Any],
    *,
    expected_fingerprint: str,
) -> str:
    source_list_field = str(row.get("_producer_source_list_field") or "")
    if source_list_field != "candidate_allocations":
        return "sample_allocation_context_only"
    fingerprint = status_module._first_present(
        row.get("selector_policy_fingerprint"),
        row.get("frozen_selector_fingerprint"),
        row.get("policy_fingerprint"),
    )
    point_in_time_fields_present = all(
        row.get(field) not in {None, ""}
        for field in ("decision_time", "generated_at", "available_at", "feature_cutoff")
    )
    if fingerprint == expected_fingerprint and point_in_time_fields_present:
        return "full_fidelity_frozen_candidate_allocation"
    if fingerprint == expected_fingerprint:
        return "frozen_candidate_allocation_missing_point_in_time_fields"
    if fingerprint in {None, ""}:
        return "low_fidelity_candidate_allocation_missing_fingerprint"
    return "non_frozen_candidate_allocation"


def _paper_allocation_tier(row: dict[str, Any]) -> str:
    tier = status_module._first_present(
        row.get("candidate_selection_tier"),
        row.get("paper_opportunity_tier"),
        row.get("explicit_paper_opportunity_tier"),
        row.get("admission_tier"),
        row.get("candidate_tier"),
    )
    return str(tier) if tier not in {None, ""} else "__missing__"


def _paper_allocation_diagnostic_identity(row: dict[str, Any]) -> str:
    return str(status_module._first_present(
        row.get("allocation_id"),
        row.get("row_id"),
        row.get("prediction_id"),
        row.get("signal_id"),
        _row_identity(row),
    ))


def _paper_allocation_source_diagnostics(
    rows: list[dict[str, Any]],
    *,
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    generated_utc: str,
) -> dict[str, Any]:
    allocation_rows = [
        row
        for row in rows
        if str(row.get("_producer_extracted_from_json") or "")
        in PAPER_LOOP_ALLOCATION_EXTRACTIONS
    ]
    source_list_field_counts: dict[str, int] = {}
    source_payload_shape_counts: dict[str, int] = {}
    source_path_counts: dict[str, int] = {}
    allocator_decision_counts: dict[str, int] = {}
    allocation_fidelity_counts: dict[str, int] = {}
    allocation_identity_records: dict[str, dict[str, Any]] = {}
    allocation_identity_sets_by_fidelity: dict[str, set[str]] = {}
    allocator_decision_counts_by_fidelity: dict[str, dict[str, int]] = {}
    tier_counts_by_fidelity: dict[str, dict[str, int]] = {}
    reason_counts: dict[str, int] = {}
    reason_counts_by_list_field: dict[str, dict[str, int]] = {}
    reason_counts_by_fidelity: dict[str, dict[str, int]] = {}
    stage_blocked_row_counts: dict[str, int] = {stage: 0 for stage in REALTIME_READINESS_STAGES}
    stage_blocked_row_counts_by_list_field: dict[str, dict[str, int]] = {}
    stage_blocked_row_counts_by_fidelity: dict[str, dict[str, int]] = {}
    timing_field_presence_counts: dict[str, int] = {
        "decision_time": 0,
        "generated_at": 0,
        "available_at": 0,
        "feature_cutoff": 0,
        "policy_activated_at": 0,
        "source_runtime_generated_at": 0,
    }
    lineage_field_presence_counts: dict[str, int] = {
        "prediction_id": 0,
        "signal_id": 0,
        "risk_decision_id": 0,
        "feature_snapshot_id": 0,
    }
    row_counts_by_readiness_and_list_field = {
        "ready_for_pending_gate": {},
        "blocked_before_pending_gate": {},
    }
    complete_accounting_count = 0
    frozen_bucket_match_count = 0
    positive_edge_count = 0
    directional_side_count = 0
    allocator_allowed_count = 0
    ready_for_pending_gate_count = 0
    ready_full_candidate_allocation_count = 0
    ready_sample_allocation_count = 0
    ready_for_pending_gate_count_by_fidelity: dict[str, int] = {}
    allocator_allowed_count_by_fidelity: dict[str, int] = {}
    blocked_sample: list[dict[str, Any]] = []
    ready_sample: list[dict[str, Any]] = []

    for row in allocation_rows:
        selection_row = _without_outcome_fields(row)
        source_list_field = str(row.get("_producer_source_list_field") or "__missing__")
        source_path = str(row.get("_producer_source_path") or "__missing__")
        payload_shape = str(row.get("_producer_source_payload_shape") or "__missing__")
        fidelity_bucket = _paper_allocation_fidelity_bucket(
            row,
            expected_fingerprint=expected_fingerprint,
        )
        allocation_identity = _paper_allocation_diagnostic_identity(selection_row)
        identity_record = allocation_identity_records.setdefault(
            allocation_identity,
            {
                "row_count": 0,
                "source_paths": set(),
                "source_list_fields": set(),
                "fidelity_buckets": set(),
            },
        )
        identity_record["row_count"] += 1
        identity_record["source_paths"].add(source_path)
        identity_record["source_list_fields"].add(source_list_field)
        identity_record["fidelity_buckets"].add(fidelity_bucket)
        allocation_identity_sets_by_fidelity.setdefault(
            fidelity_bucket,
            set(),
        ).add(allocation_identity)
        _increment_counter(source_list_field_counts, source_list_field)
        _increment_counter(source_path_counts, source_path)
        _increment_counter(source_payload_shape_counts, payload_shape)
        _increment_counter(allocation_fidelity_counts, fidelity_bucket)
        allocator_decision = status_module._allocator_decision(selection_row)
        _increment_counter(allocator_decision_counts, allocator_decision or "__missing__")
        _increment_counter(
            allocator_decision_counts_by_fidelity.setdefault(fidelity_bucket, {}),
            allocator_decision or "__missing__",
        )
        _increment_counter(
            tier_counts_by_fidelity.setdefault(fidelity_bucket, {}),
            _paper_allocation_tier(selection_row),
        )
        if not allocator_decision.startswith("BLOCK_"):
            allocator_allowed_count += 1
            _increment_counter(allocator_allowed_count_by_fidelity, fidelity_bucket)
        for field in timing_field_presence_counts:
            if row.get(field) not in {None, ""}:
                timing_field_presence_counts[field] += 1
        lineage = row.get("lineage_ids") if isinstance(row.get("lineage_ids"), dict) else {}
        for field in lineage_field_presence_counts:
            if row.get(field) not in {None, ""} or lineage.get(field) not in {None, ""}:
                lineage_field_presence_counts[field] += 1

        payload = _selector_bucket_key_payload_from_row(selection_row)
        key = tuple(str(payload[field]) for field in SELECTOR_BUCKET_KEY_FIELDS)
        if key in eligible_bucket_keys:
            frozen_bucket_match_count += 1
        edge = status_module._expected_edge_bps(selection_row)
        if edge is not None and edge > 0.0:
            positive_edge_count += 1
        if status_module._directional_side(selection_row) in {"long", "short"}:
            directional_side_count += 1
        accounting_reasons = _accounting_reject_reasons(selection_row)
        if not accounting_reasons:
            complete_accounting_count += 1

        reasons = _paper_allocation_gate_reasons(
            selection_row,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_bucket_keys,
            generated_utc=generated_utc,
        )
        bucket = row_counts_by_readiness_and_list_field[
            "ready_for_pending_gate" if not reasons else "blocked_before_pending_gate"
        ]
        _increment_counter(bucket, source_list_field)
        if not reasons:
            ready_for_pending_gate_count += 1
            _increment_counter(ready_for_pending_gate_count_by_fidelity, fidelity_bucket)
            if source_list_field == "candidate_allocations":
                ready_full_candidate_allocation_count += 1
            elif source_list_field == "sample_allocations":
                ready_sample_allocation_count += 1
        for reason in reasons:
            _increment_counter(reason_counts, reason)
            _increment_counter(
                reason_counts_by_list_field.setdefault(source_list_field, {}),
                reason,
            )
            _increment_counter(
                reason_counts_by_fidelity.setdefault(fidelity_bucket, {}),
                reason,
            )
            stage = _rejection_reason_category(reason)
            _increment_counter(stage_blocked_row_counts, stage)
            _increment_counter(
                stage_blocked_row_counts_by_list_field.setdefault(
                    source_list_field,
                    {stage_name: 0 for stage_name in REALTIME_READINESS_STAGES},
                ),
                stage,
            )
            _increment_counter(
                stage_blocked_row_counts_by_fidelity.setdefault(
                    fidelity_bucket,
                    {stage_name: 0 for stage_name in REALTIME_READINESS_STAGES},
                ),
                stage,
            )

        sample = {
            "source_row_identity_hash": _sha256_text(_row_identity(selection_row)),
            "source_path": source_path,
            "source_list_field": source_list_field,
            "source_payload_shape": payload_shape,
            "allocation_fidelity_bucket": fidelity_bucket,
            "symbol": status_module._normalized_symbol(selection_row),
            "timeframe": status_module._row_value(selection_row, "timeframe")
            or selection_row.get("timeframe"),
            "side": status_module._directional_side(selection_row),
            "decision_time": selection_row.get("decision_time"),
            "generated_at": selection_row.get("generated_at"),
            "available_at": selection_row.get("available_at"),
            "feature_cutoff": selection_row.get("feature_cutoff"),
            "policy_activated_at": selection_row.get("policy_activated_at"),
            "selector_bucket_key": payload,
            "reasons": reasons,
        }
        if reasons and len(blocked_sample) < 20:
            blocked_sample.append(sample)
        elif not reasons and len(ready_sample) < 20:
            ready_sample.append(sample)

    candidate_allocation_count = source_list_field_counts.get("candidate_allocations", 0)
    sample_allocation_count = source_list_field_counts.get("sample_allocations", 0)
    full_fidelity_frozen_candidate_allocation_count = allocation_fidelity_counts.get(
        "full_fidelity_frozen_candidate_allocation",
        0,
    )
    low_fidelity_candidate_allocation_count = allocation_fidelity_counts.get(
        "low_fidelity_candidate_allocation_missing_fingerprint",
        0,
    )
    duplicated_identity_records = {
        identity: record
        for identity, record in allocation_identity_records.items()
        if int(record["row_count"]) > 1
    }
    duplicated_allocation_identity_sample = [
        {
            "allocation_identity": identity,
            "row_count": int(record["row_count"]),
            "source_paths": sorted(record["source_paths"]),
            "source_list_fields": sorted(record["source_list_fields"]),
            "fidelity_buckets": sorted(record["fidelity_buckets"]),
        }
        for identity, record in sorted(
            duplicated_identity_records.items(),
            key=lambda item: (-int(item[1]["row_count"]), item[0]),
        )[:20]
    ]
    if not allocation_rows:
        status = "NO_PAPER_ALLOCATION_ROWS_PROCESSED"
    elif candidate_allocation_count == 0:
        status = "NO_GO_NO_FULL_CANDIDATE_ALLOCATIONS_EXPOSED"
    elif ready_full_candidate_allocation_count == 0:
        status = "NO_GO_FULL_CANDIDATE_ALLOCATIONS_NOT_GATE_READY"
    else:
        status = "READY_FULL_CANDIDATE_ALLOCATIONS_GATE_READY"

    return {
        "status": status,
        "diagnostic_only": True,
        "counts_as_pending_or_final_evidence": False,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_allocation_diagnostics": [],
        "bucket_key_fields": list(SELECTOR_BUCKET_KEY_FIELDS),
        "eligible_bucket_count": len(eligible_bucket_keys),
        "processed_source_row_count": len(rows),
        "allocation_row_count": len(allocation_rows),
        "candidate_allocation_count": candidate_allocation_count,
        "sample_allocation_count": sample_allocation_count,
        "full_candidate_allocation_source_exposed": candidate_allocation_count > 0,
        "sample_allocations_are_context_only": True,
        "ready_for_pending_gate_count": ready_for_pending_gate_count,
        "ready_full_candidate_allocation_count": ready_full_candidate_allocation_count,
        "ready_sample_allocation_count": ready_sample_allocation_count,
        "complete_accounting_count": complete_accounting_count,
        "frozen_bucket_match_count": frozen_bucket_match_count,
        "positive_edge_count": positive_edge_count,
        "directional_side_count": directional_side_count,
        "allocator_allowed_count": allocator_allowed_count,
        "source_list_field_counts": _sorted_counts(source_list_field_counts),
        "source_payload_shape_counts": _sorted_counts(source_payload_shape_counts),
        "allocation_fidelity_counts": _sorted_counts(allocation_fidelity_counts),
        "unique_allocation_identity_count": len(allocation_identity_records),
        "duplicate_allocation_row_count": (
            len(allocation_rows) - len(allocation_identity_records)
        ),
        "duplicated_allocation_identity_count": len(duplicated_identity_records),
        "unique_allocation_identity_count_by_fidelity": {
            fidelity: len(identity_set)
            for fidelity, identity_set in sorted(allocation_identity_sets_by_fidelity.items())
        },
        "duplicated_allocation_identity_sample": duplicated_allocation_identity_sample,
        "full_fidelity_frozen_candidate_allocation_count": (
            full_fidelity_frozen_candidate_allocation_count
        ),
        "low_fidelity_candidate_allocation_count": low_fidelity_candidate_allocation_count,
        "allocator_allowed_count_by_fidelity": _sorted_counts(
            allocator_allowed_count_by_fidelity
        ),
        "ready_for_pending_gate_count_by_fidelity": _sorted_counts(
            ready_for_pending_gate_count_by_fidelity
        ),
        "source_path_counts": _sorted_counts(source_path_counts),
        "allocator_decision_counts": _sorted_counts(allocator_decision_counts),
        "allocator_decision_counts_by_fidelity": {
            fidelity: _sorted_counts(counts)
            for fidelity, counts in sorted(allocator_decision_counts_by_fidelity.items())
        },
        "tier_counts_by_fidelity": {
            fidelity: _sorted_counts(counts)
            for fidelity, counts in sorted(tier_counts_by_fidelity.items())
        },
        "timing_field_presence_counts": timing_field_presence_counts,
        "lineage_field_presence_counts": lineage_field_presence_counts,
        "row_counts_by_readiness_and_list_field": {
            key: _sorted_counts(value)
            for key, value in row_counts_by_readiness_and_list_field.items()
        },
        "reason_counts": _sorted_counts(reason_counts),
        "reason_counts_by_list_field": {
            list_field: _sorted_counts(counts)
            for list_field, counts in sorted(reason_counts_by_list_field.items())
        },
        "reason_counts_by_fidelity": {
            fidelity: _sorted_counts(counts)
            for fidelity, counts in sorted(reason_counts_by_fidelity.items())
        },
        "stage_blocked_row_counts": {
            stage: stage_blocked_row_counts.get(stage, 0)
            for stage in REALTIME_READINESS_STAGES
        },
        "stage_blocked_row_counts_by_list_field": {
            list_field: {
                stage: counts.get(stage, 0)
                for stage in REALTIME_READINESS_STAGES
            }
            for list_field, counts in sorted(stage_blocked_row_counts_by_list_field.items())
        },
        "stage_blocked_row_counts_by_fidelity": {
            fidelity: {
                stage: counts.get(stage, 0)
                for stage in REALTIME_READINESS_STAGES
            }
            for fidelity, counts in sorted(stage_blocked_row_counts_by_fidelity.items())
        },
        "ready_sample": ready_sample,
        "blocked_sample": blocked_sample,
        "note": (
            "Diagnostic only. Full candidate allocations are separated from sample "
            "allocations because production evidence must be selected from the frozen "
            "decision-time candidate stream before outcomes are known. The producer "
            "does not promote samples, rewrite bucket labels, or relax the gate."
        ),
    }


def _lineage_bridge_alias_values(row: dict[str, Any]) -> set[str]:
    aliases = {
        str(row.get(field))
        for field in LINEAGE_BRIDGE_ALIAS_FIELDS
        if row.get(field) not in {None, ""}
    }
    lineage = row.get("lineage_ids")
    if isinstance(lineage, dict):
        aliases.update(str(value) for value in lineage.values() if value not in {None, ""})
    return aliases


def _lineage_bridge_group_value(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> Any:
    for row in rows:
        for field in fields:
            value = row.get(field)
            if _present(value):
                return value
    return None


def _lineage_bridge_missing_groups(rows: list[dict[str, Any]]) -> list[str]:
    return [
        group
        for group, fields in LINEAGE_BRIDGE_REQUIRED_FIELD_GROUPS.items()
        if not _present(_lineage_bridge_group_value(rows, fields))
    ]


def _lineage_bridge_fingerprint_state(
    rows: list[dict[str, Any]],
    *,
    expected_fingerprint: str,
) -> str:
    value = _lineage_bridge_group_value(
        rows,
        LINEAGE_BRIDGE_REQUIRED_FIELD_GROUPS["selector_policy_fingerprint"],
    )
    if not _present(value):
        return "missing"
    if str(value) == expected_fingerprint:
        return "matches_expected"
    return "mismatched"


def _low_fidelity_allocation_lineage_bridge_diagnostics(
    rows: list[dict[str, Any]],
    *,
    expected_fingerprint: str,
) -> dict[str, Any]:
    bridge_index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("_producer_extracted_from_json") or "") in PAPER_LOOP_ALLOCATION_EXTRACTIONS:
            continue
        for alias in _lineage_bridge_alias_values(row):
            bridge_index.setdefault(alias, []).append(row)

    allocation_rows = [
        row
        for row in rows
        if str(row.get("_producer_extracted_from_json") or "")
        in PAPER_LOOP_ALLOCATION_EXTRACTIONS
    ]
    low_fidelity_allowed_rows = [
        row
        for row in allocation_rows
        if _paper_allocation_fidelity_bucket(
            row,
            expected_fingerprint=expected_fingerprint,
        )
        == "low_fidelity_candidate_allocation_missing_fingerprint"
        and not status_module._allocator_decision(row).startswith("BLOCK_")
    ]
    missing_before_counts: dict[str, int] = {}
    missing_after_counts: dict[str, int] = {}
    supplied_counts: dict[str, int] = {}
    bridge_source_kind_counts: dict[str, int] = {}
    bridge_extracted_from_json_counts: dict[str, int] = {}
    fingerprint_state_before_counts: dict[str, int] = {}
    fingerprint_state_after_counts: dict[str, int] = {}
    allocations_with_lineage_alias_count = 0
    allocations_with_bridge_match_count = 0
    allocations_with_bridge_field_supply_count = 0
    allocations_bridge_contract_complete_count = 0
    bridge_match_row_count = 0
    sample: list[dict[str, Any]] = []

    for row in low_fidelity_allowed_rows:
        selection_row = _without_outcome_fields(row)
        aliases = _lineage_bridge_alias_values(selection_row)
        if aliases:
            allocations_with_lineage_alias_count += 1
        bridge_matches_by_identity: dict[int, dict[str, Any]] = {}
        for alias in aliases:
            for candidate in bridge_index.get(alias, []):
                bridge_matches_by_identity[id(candidate)] = _without_outcome_fields(candidate)
        bridge_matches = [
            bridge_matches_by_identity[key]
            for key in sorted(bridge_matches_by_identity)
        ]
        if bridge_matches:
            allocations_with_bridge_match_count += 1
        bridge_match_row_count += len(bridge_matches)
        for bridge_row in bridge_matches:
            _increment_counter(
                bridge_source_kind_counts,
                str(bridge_row.get("_producer_source_kind") or "UNKNOWN"),
            )
            _increment_counter(
                bridge_extracted_from_json_counts,
                str(bridge_row.get("_producer_extracted_from_json") or "__missing__"),
            )

        missing_before = _lineage_bridge_missing_groups([selection_row])
        missing_after = _lineage_bridge_missing_groups([selection_row, *bridge_matches])
        supplied = sorted(set(missing_before) - set(missing_after))
        if supplied:
            allocations_with_bridge_field_supply_count += 1
        for group in missing_before:
            _increment_counter(missing_before_counts, group)
        for group in missing_after:
            _increment_counter(missing_after_counts, group)
        for group in supplied:
            _increment_counter(supplied_counts, group)

        before_state = _lineage_bridge_fingerprint_state(
            [selection_row],
            expected_fingerprint=expected_fingerprint,
        )
        after_state = _lineage_bridge_fingerprint_state(
            [selection_row, *bridge_matches],
            expected_fingerprint=expected_fingerprint,
        )
        _increment_counter(fingerprint_state_before_counts, before_state)
        _increment_counter(fingerprint_state_after_counts, after_state)
        if not missing_after and after_state == "matches_expected":
            allocations_bridge_contract_complete_count += 1

        if len(sample) < 20:
            sample.append({
                "allocation_identity_hash": _sha256_text(
                    _paper_allocation_diagnostic_identity(selection_row)
                ),
                "source_row_identity_hash": _sha256_text(_row_identity(selection_row)),
                "symbol": status_module._normalized_symbol(selection_row),
                "timeframe": status_module._row_value(selection_row, "timeframe")
                or selection_row.get("timeframe"),
                "side": status_module._directional_side(selection_row),
                "lineage_alias_count": len(aliases),
                "lineage_alias_hash_sample": [
                    _sha256_text(alias) for alias in sorted(aliases)[:8]
                ],
                "bridge_match_row_count": len(bridge_matches),
                "bridge_source_kinds": sorted({
                    str(bridge_row.get("_producer_source_kind") or "UNKNOWN")
                    for bridge_row in bridge_matches
                }),
                "bridge_extracted_from_json": sorted({
                    str(
                        bridge_row.get("_producer_extracted_from_json")
                        or "__missing__"
                    )
                    for bridge_row in bridge_matches
                }),
                "missing_before_bridge": missing_before,
                "bridge_supplied_field_groups": supplied,
                "missing_after_bridge": missing_after,
                "fingerprint_state_before_bridge": before_state,
                "fingerprint_state_after_bridge": after_state,
            })

    if not low_fidelity_allowed_rows:
        status = "NO_LOW_FIDELITY_ALLOWED_ALLOCATIONS_TO_BRIDGE"
    elif allocations_with_bridge_match_count == 0:
        status = "NO_GO_LOW_FIDELITY_ALLOWED_ALLOCATIONS_HAVE_NO_LINEAGE_BRIDGE"
    elif allocations_bridge_contract_complete_count == 0:
        status = "NO_GO_LINEAGE_BRIDGE_INCOMPLETE_FOR_LOW_FIDELITY_ALLOCATIONS"
    else:
        status = "WARN_LINEAGE_BRIDGE_CONTRACT_PRESENT_DIAGNOSTIC_ONLY"

    return {
        "status": status,
        "diagnostic_only": True,
        "counts_as_pending_or_final_evidence": False,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_lineage_bridge": [],
        "required_field_groups": {
            group: list(fields)
            for group, fields in LINEAGE_BRIDGE_REQUIRED_FIELD_GROUPS.items()
        },
        "processed_source_row_count": len(rows),
        "bridge_index_alias_count": len(bridge_index),
        "allocation_row_count": len(allocation_rows),
        "low_fidelity_allowed_allocation_count": len(low_fidelity_allowed_rows),
        "allocations_with_lineage_alias_count": allocations_with_lineage_alias_count,
        "allocations_with_bridge_match_count": allocations_with_bridge_match_count,
        "bridge_match_row_count": bridge_match_row_count,
        "allocations_with_bridge_field_supply_count": (
            allocations_with_bridge_field_supply_count
        ),
        "allocations_bridge_contract_complete_count": (
            allocations_bridge_contract_complete_count
        ),
        "missing_before_bridge_field_counts": _sorted_counts(missing_before_counts),
        "bridge_supplied_field_counts": _sorted_counts(supplied_counts),
        "missing_after_bridge_field_counts": _sorted_counts(missing_after_counts),
        "fingerprint_state_before_bridge_counts": _sorted_counts(
            fingerprint_state_before_counts
        ),
        "fingerprint_state_after_bridge_counts": _sorted_counts(
            fingerprint_state_after_counts
        ),
        "bridge_source_kind_counts": _sorted_counts(bridge_source_kind_counts),
        "bridge_extracted_from_json_counts": _sorted_counts(
            bridge_extracted_from_json_counts
        ),
        "sample": sample,
        "note": (
            "Diagnostic only. Matching lineage rows can explain why low-fidelity "
            "allocator-allowed rows are not countable, but the producer does not merge "
            "or promote them into pending evidence. Countable realtime evidence still "
            "requires the source candidate itself to pass the frozen fingerprint, "
            "point-in-time lineage, selector, accounting, safety, and protocol gates."
        ),
    }


def _selector_bucket_key_payload_from_row(row: dict[str, Any]) -> dict[str, str]:
    key = tuple(str(value) for value in status_module._a_grade_bucket_key(row))
    return status_module._a_grade_bucket_key_payload(key)


def _record_selector_bucket_count(
    buckets: dict[str, dict[str, Any]],
    *,
    payload: dict[str, str],
    source_kind: str,
) -> None:
    key = _stable_json(payload)
    record = buckets.setdefault(
        key,
        {
            "bucket_key": payload,
            "row_count": 0,
            "source_kind_counts": {},
        },
    )
    record["row_count"] += 1
    _increment_counter(record["source_kind_counts"], source_kind)


def _top_selector_bucket_counts(buckets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "bucket_key": record["bucket_key"],
            "row_count": record["row_count"],
            "source_kind_counts": {
                key: record["source_kind_counts"][key]
                for key in sorted(record["source_kind_counts"])
            },
        }
        for record in sorted(
            buckets.values(),
            key=lambda item: (-int(item["row_count"]), _stable_json(item["bucket_key"])),
        )[:20]
    ]


def _eligible_bucket_payloads(eligible_bucket_keys: set[tuple[str, ...]]) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    for key in sorted(eligible_bucket_keys):
        payload = status_module._a_grade_bucket_key_payload(tuple(str(value) for value in key))
        payloads.append(
            {
                field: str(payload.get(field) or "__missing__")
                for field in SELECTOR_BUCKET_KEY_FIELDS
            }
        )
    return sorted(payloads, key=_stable_json)


def _closest_eligible_bucket_distance(
    payload: dict[str, str],
    *,
    eligible_bucket_payloads: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not eligible_bucket_payloads:
        return None

    closest: dict[str, Any] | None = None
    for eligible_payload in eligible_bucket_payloads:
        mismatch_fields = [
            field
            for field in SELECTOR_BUCKET_KEY_FIELDS
            if str(payload.get(field) or "__missing__")
            != str(eligible_payload.get(field) or "__missing__")
        ]
        candidate = {
            "closest_eligible_bucket_key": eligible_payload,
            "mismatch_count": len(mismatch_fields),
            "mismatch_fields": mismatch_fields,
        }
        if closest is None:
            closest = candidate
            continue
        if len(mismatch_fields) < int(closest["mismatch_count"]):
            closest = candidate
            continue
        if len(mismatch_fields) == int(closest["mismatch_count"]) and _stable_json(
            eligible_payload
        ) < _stable_json(closest["closest_eligible_bucket_key"]):
            closest = candidate
    return closest


def _selector_bucket_distance_diagnostics(
    rows: list[dict[str, Any]],
    *,
    eligible_bucket_payloads: list[dict[str, str]],
) -> dict[str, Any]:
    mismatch_count_distribution: dict[str, int] = {}
    mismatch_count_distribution_by_source_kind: dict[str, dict[str, int]] = {}
    mismatch_dimension_counts: dict[str, int] = {}
    mismatch_dimension_counts_by_source_kind: dict[str, dict[str, int]] = {}
    closest_samples: list[dict[str, Any]] = []
    rows_without_eligible_bucket = 0

    for row in rows:
        selection_row = _without_outcome_fields(row)
        payload = _selector_bucket_key_payload_from_row(selection_row)
        closest = _closest_eligible_bucket_distance(
            payload,
            eligible_bucket_payloads=eligible_bucket_payloads,
        )
        if closest is None:
            rows_without_eligible_bucket += 1
            continue

        source_kind = str(row.get("_producer_source_kind") or "UNKNOWN")
        mismatch_count_key = str(closest["mismatch_count"])
        _increment_counter(mismatch_count_distribution, mismatch_count_key)
        by_kind = mismatch_count_distribution_by_source_kind.setdefault(source_kind, {})
        _increment_counter(by_kind, mismatch_count_key)

        dimension_by_kind = mismatch_dimension_counts_by_source_kind.setdefault(source_kind, {})
        for field in closest["mismatch_fields"]:
            _increment_counter(mismatch_dimension_counts, field)
            _increment_counter(dimension_by_kind, field)

        if len(closest_samples) < 20:
            closest_samples.append(
                {
                    "source_kind": source_kind,
                    "source_row_identity_hash": _sha256_text(_row_identity(selection_row)),
                    "symbol": status_module._normalized_symbol(selection_row),
                    "timeframe": status_module._row_value(selection_row, "timeframe")
                    or selection_row.get("timeframe"),
                    "side": status_module._directional_side(selection_row),
                    "bucket_key": payload,
                    "closest_eligible_bucket_key": closest["closest_eligible_bucket_key"],
                    "mismatch_count": closest["mismatch_count"],
                    "mismatch_fields": closest["mismatch_fields"],
                }
            )

    return {
        "status": "READY_SELECTOR_BUCKET_DISTANCE_DIAGNOSTICS",
        "diagnostic_only": True,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_bucket_distance": [],
        "bucket_key_fields": list(SELECTOR_BUCKET_KEY_FIELDS),
        "eligible_bucket_count": len(eligible_bucket_payloads),
        "processed_source_row_count": len(rows),
        "rows_without_comparable_eligible_bucket_count": rows_without_eligible_bucket,
        "minimum_mismatch_count_distribution": {
            key: mismatch_count_distribution[key]
            for key in sorted(mismatch_count_distribution, key=lambda item: int(item))
        },
        "minimum_mismatch_count_distribution_by_source_kind": {
            source_kind: {
                key: counts[key] for key in sorted(counts, key=lambda item: int(item))
            }
            for source_kind, counts in sorted(
                mismatch_count_distribution_by_source_kind.items()
            )
        },
        "closest_eligible_mismatch_dimension_counts": {
            key: mismatch_dimension_counts[key] for key in sorted(mismatch_dimension_counts)
        },
        "closest_eligible_mismatch_dimension_counts_by_source_kind": {
            source_kind: {
                key: counts[key] for key in sorted(counts)
            }
            for source_kind, counts in sorted(mismatch_dimension_counts_by_source_kind.items())
        },
        "closest_sample": closest_samples,
        "note": (
            "Diagnostic only. Each source row is compared to the nearest frozen eligible "
            "bucket using outcome-stripped decision-time fields. The producer does not "
            "rewrite source values or use distance to admit evidence."
        ),
    }


def _top_selector_contract_value_counts(
    counts: dict[str, int],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return [
        {
            "value": value,
            "row_count": counts[value],
        }
        for value in sorted(counts, key=lambda item: (-counts[item], item))[:limit]
    ]


def _selector_source_contract_diagnostics(
    rows: list[dict[str, Any]],
    *,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> dict[str, Any]:
    eligible_payloads = _eligible_bucket_payloads(eligible_bucket_keys)
    eligible_values_by_dimension = {
        field: {
            str(payload.get(field) or "__missing__")
            for payload in eligible_payloads
        }
        for field in SELECTOR_BUCKET_KEY_FIELDS
    }
    source_kind_counts: dict[str, int] = {}
    full_bucket_match_by_source_kind: dict[str, int] = {}
    missing_or_unknown_dimension_counts: dict[str, int] = {}
    missing_or_unknown_dimension_counts_by_source_kind: dict[str, dict[str, int]] = {}
    value_not_in_eligible_counts_by_dimension: dict[str, int] = {}
    value_not_in_eligible_counts_by_source_kind: dict[str, dict[str, int]] = {}
    observed_value_counts_by_dimension: dict[str, dict[str, int]] = {
        field: {} for field in SELECTOR_BUCKET_KEY_FIELDS
    }
    rows_with_all_bucket_dimensions = 0
    rows_with_all_values_in_eligible_dimensions = 0
    rows_with_value_not_in_eligible_dimensions = 0
    full_bucket_match_count = 0

    for row in rows:
        selection_row = _without_outcome_fields(row)
        payload = _selector_bucket_key_payload_from_row(selection_row)
        key = tuple(str(payload[field]) for field in SELECTOR_BUCKET_KEY_FIELDS)
        source_kind = str(row.get("_producer_source_kind") or "UNKNOWN")
        _increment_counter(source_kind_counts, source_kind)

        missing_fields: list[str] = []
        value_not_in_eligible_fields: list[str] = []
        for field in SELECTOR_BUCKET_KEY_FIELDS:
            value = str(payload.get(field) or "__missing__")
            _increment_counter(observed_value_counts_by_dimension[field], value)
            if value in {"__unknown__", "__missing__"}:
                missing_fields.append(field)
                continue
            if value not in eligible_values_by_dimension.get(field, set()):
                value_not_in_eligible_fields.append(field)

        if missing_fields:
            by_kind = missing_or_unknown_dimension_counts_by_source_kind.setdefault(
                source_kind,
                {},
            )
            for field in missing_fields:
                _increment_counter(missing_or_unknown_dimension_counts, field)
                _increment_counter(by_kind, field)
        else:
            rows_with_all_bucket_dimensions += 1

        if value_not_in_eligible_fields:
            rows_with_value_not_in_eligible_dimensions += 1
            by_kind = value_not_in_eligible_counts_by_source_kind.setdefault(
                source_kind,
                {},
            )
            for field in value_not_in_eligible_fields:
                _increment_counter(value_not_in_eligible_counts_by_dimension, field)
                _increment_counter(by_kind, field)

        if not missing_fields and not value_not_in_eligible_fields:
            rows_with_all_values_in_eligible_dimensions += 1

        if key in eligible_bucket_keys:
            full_bucket_match_count += 1
            _increment_counter(full_bucket_match_by_source_kind, source_kind)

    if not rows:
        status = "NO_SOURCE_ROWS_FOR_SELECTOR_SOURCE_CONTRACT"
    elif full_bucket_match_count == 0:
        status = "NO_GO_SELECTOR_SOURCE_CONTRACT_GAPS"
    elif (
        rows_with_all_bucket_dimensions < len(rows)
        or rows_with_all_values_in_eligible_dimensions < len(rows)
    ):
        status = "WARN_SELECTOR_SOURCE_CONTRACT_PARTIAL_GAPS"
    else:
        status = "READY_SELECTOR_SOURCE_CONTRACT_SATISFIED"

    return {
        "status": status,
        "diagnostic_only": True,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_source_contract": [],
        "bucket_key_fields": list(SELECTOR_BUCKET_KEY_FIELDS),
        "eligible_bucket_count": len(eligible_bucket_keys),
        "processed_source_row_count": len(rows),
        "source_kind_counts": {
            key: source_kind_counts[key] for key in sorted(source_kind_counts)
        },
        "eligible_values_by_dimension": {
            field: sorted(values)
            for field, values in eligible_values_by_dimension.items()
        },
        "rows_with_all_bucket_dimensions_count": rows_with_all_bucket_dimensions,
        "rows_with_missing_or_unknown_bucket_dimension_count": (
            len(rows) - rows_with_all_bucket_dimensions
        ),
        "missing_or_unknown_dimension_counts": {
            key: missing_or_unknown_dimension_counts[key]
            for key in sorted(missing_or_unknown_dimension_counts)
        },
        "missing_or_unknown_dimension_counts_by_source_kind": {
            source_kind: {
                key: counts[key] for key in sorted(counts)
            }
            for source_kind, counts in sorted(
                missing_or_unknown_dimension_counts_by_source_kind.items()
            )
        },
        "rows_with_all_values_in_eligible_dimensions_count": (
            rows_with_all_values_in_eligible_dimensions
        ),
        "rows_with_value_not_in_eligible_dimensions_count": (
            rows_with_value_not_in_eligible_dimensions
        ),
        "value_not_in_eligible_counts_by_dimension": {
            key: value_not_in_eligible_counts_by_dimension[key]
            for key in sorted(value_not_in_eligible_counts_by_dimension)
        },
        "value_not_in_eligible_counts_by_source_kind": {
            source_kind: {
                key: counts[key] for key in sorted(counts)
            }
            for source_kind, counts in sorted(
                value_not_in_eligible_counts_by_source_kind.items()
            )
        },
        "full_bucket_match_count": full_bucket_match_count,
        "full_bucket_match_by_source_kind": {
            key: full_bucket_match_by_source_kind[key]
            for key in sorted(full_bucket_match_by_source_kind)
        },
        "observed_value_counts_by_dimension": {
            field: _top_selector_contract_value_counts(counts)
            for field, counts in observed_value_counts_by_dimension.items()
        },
        "note": (
            "Diagnostic only. Source rows are stripped of outcome fields before bucket-key "
            "evaluation. The producer does not infer missing dimensions, rewrite source "
            "values, or use this diagnostic to admit evidence."
        ),
    }


def _selector_bucket_diagnostics(
    rows: list[dict[str, Any]],
    *,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> dict[str, Any]:
    source_kind_counts: dict[str, int] = {}
    eligible_by_source_kind: dict[str, int] = {}
    noneligible_by_source_kind: dict[str, int] = {}
    missing_dimension_counts: dict[str, int] = {}
    missing_dimension_counts_by_source_kind: dict[str, dict[str, int]] = {}
    eligible_buckets: dict[str, dict[str, Any]] = {}
    noneligible_buckets: dict[str, dict[str, Any]] = {}
    rows_with_unknown_or_missing = 0
    eligible_payloads = _eligible_bucket_payloads(eligible_bucket_keys)

    for row in rows:
        selection_row = _without_outcome_fields(row)
        payload = _selector_bucket_key_payload_from_row(selection_row)
        key = tuple(str(payload[field]) for field in SELECTOR_BUCKET_KEY_FIELDS)
        source_kind = str(row.get("_producer_source_kind") or "UNKNOWN")
        _increment_counter(source_kind_counts, source_kind)

        missing_fields = [
            field
            for field, value in payload.items()
            if value in {"__unknown__", "__missing__"}
        ]
        if missing_fields:
            rows_with_unknown_or_missing += 1
            by_kind = missing_dimension_counts_by_source_kind.setdefault(source_kind, {})
            for field in missing_fields:
                _increment_counter(missing_dimension_counts, field)
                _increment_counter(by_kind, field)

        if key in eligible_bucket_keys:
            _increment_counter(eligible_by_source_kind, source_kind)
            _record_selector_bucket_count(
                eligible_buckets,
                payload=payload,
                source_kind=source_kind,
            )
        else:
            _increment_counter(noneligible_by_source_kind, source_kind)
            _record_selector_bucket_count(
                noneligible_buckets,
                payload=payload,
                source_kind=source_kind,
            )

    return {
        "status": "READY_SELECTOR_BUCKET_DIAGNOSTICS",
        "diagnostic_only": True,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_bucket_diagnostics": [],
        "bucket_key_fields": list(SELECTOR_BUCKET_KEY_FIELDS),
        "processed_source_row_count": len(rows),
        "eligible_bucket_count": len(eligible_bucket_keys),
        "dynamic_bucket_eligible_source_row_count": sum(eligible_by_source_kind.values()),
        "dynamic_bucket_noneligible_source_row_count": sum(noneligible_by_source_kind.values()),
        "source_kind_counts": {
            key: source_kind_counts[key] for key in sorted(source_kind_counts)
        },
        "dynamic_bucket_eligible_by_source_kind": {
            key: eligible_by_source_kind[key] for key in sorted(eligible_by_source_kind)
        },
        "dynamic_bucket_noneligible_by_source_kind": {
            key: noneligible_by_source_kind[key] for key in sorted(noneligible_by_source_kind)
        },
        "rows_with_unknown_or_missing_bucket_dimension_count": rows_with_unknown_or_missing,
        "unknown_or_missing_bucket_dimension_counts": {
            key: missing_dimension_counts[key] for key in sorted(missing_dimension_counts)
        },
        "unknown_or_missing_bucket_dimension_counts_by_source_kind": {
            source_kind: {
                key: counts[key] for key in sorted(counts)
            }
            for source_kind, counts in sorted(missing_dimension_counts_by_source_kind.items())
        },
        "top_dynamic_bucket_eligible_keys": _top_selector_bucket_counts(eligible_buckets),
        "top_dynamic_bucket_noneligible_keys": _top_selector_bucket_counts(noneligible_buckets),
        "eligible_bucket_distance_diagnostics": _selector_bucket_distance_diagnostics(
            rows,
            eligible_bucket_payloads=eligible_payloads,
        ),
        "note": (
            "Diagnostic only. Bucket keys are computed with the frozen selector helpers from "
            "outcome-stripped source rows; no row becomes pending or final evidence unless the "
            "normal producer gate has zero rejection reasons."
        ),
    }


def materialize_forward_holdout_source(
    *,
    source_jsonl: Path,
    registry_path: Path,
    json_sources: list[Path],
    expected_fingerprint: str,
    max_rows: int | None,
    generated_utc: str,
) -> dict[str, Any]:
    _touch(source_jsonl)
    manifest_path = _sidecar_manifest_path(source_jsonl)
    chain_path = source_jsonl.with_suffix(source_jsonl.suffix + ".hash_chain.jsonl")
    registry = _load_holdout_registry(
        registry_path=registry_path,
        source_path=source_jsonl,
        generated_utc=generated_utc,
    )
    existing_rows, existing_status_before = _iter_jsonl(source_jsonl)
    existing_identities = {
        _candidate_identity(row, scope="holdout")
        for row in existing_rows
    }

    extracted_rows: list[dict[str, Any]] = []
    source_statuses: list[dict[str, Any]] = []
    for path in json_sources:
        rows, source_status = _rows_from_json(path)
        source_statuses.append(source_status)
        extracted_rows.extend(
            _normalize_realtime_source_row(
                row,
                source_kind="filesystem_forward_holdout_candidate_allocation",
                source_label=str(path),
            )
            for row in rows
        )

    source_rows = extracted_rows[:max_rows] if max_rows is not None else extracted_rows
    appended = 0
    duplicate = 0
    skipped = 0
    full_candidate_allocation_count = 0
    reason_counts: dict[str, int] = {}
    source_path_counts: dict[str, int] = {}
    window_counts: dict[str, int] = {}
    skip_samples: list[dict[str, Any]] = []
    appended_samples: list[dict[str, Any]] = []

    for row in source_rows:
        source_path = str(row.get("_producer_source_path") or "__missing__")
        _increment_counter(source_path_counts, source_path)
        reasons: list[str] = []
        if str(row.get("_producer_source_list_field") or "") != "candidate_allocations":
            reasons.append("FORWARD_HOLDOUT_SOURCE_NOT_FULL_CANDIDATE_ALLOCATION")
        else:
            full_candidate_allocation_count += 1

        raw_outcome_fields = row.get("_producer_source_outcome_fields_present")
        if (
            (isinstance(raw_outcome_fields, list) and raw_outcome_fields)
            or any(field in row for field in OUTCOME_FIELDS)
            or _has_realtime_outcome(row)
        ):
            reasons.append("FORWARD_HOLDOUT_SOURCE_ROW_HAS_OUTCOME_FIELDS")

        reasons.extend(_realtime_source_safety_reasons(row))
        if row.get("future_labels_used_as_features") is True:
            reasons.append("FUTURE_LABELS_USED_AS_FEATURES")

        decision = status_module._parse_utc(
            row.get("decision_time") or row.get("entry_feature_decision_time")
        )
        if decision is None:
            reasons.append("MISSING_DECISION_TIME")
        window = _window_for_row(row, registry)
        if not _window_is_forward_preregistered(window):
            reasons.append("NO_ACTIVE_FORWARD_HOLDOUT_WINDOW_FOR_DECISION_TIME")

        reasons = sorted(set(reasons))
        if reasons:
            skipped += 1
            for reason in reasons:
                _increment_counter(reason_counts, reason)
            if len(skip_samples) < 20:
                skip_samples.append({
                    "source_row_identity_hash": _sha256_text(_row_identity(row)),
                    "source_path": source_path,
                    "source_list_field": row.get("_producer_source_list_field"),
                    "symbol": status_module._normalized_symbol(row),
                    "timeframe": status_module._row_value(row, "timeframe") or row.get("timeframe"),
                    "side": status_module._directional_side(row),
                    "decision_time": row.get("decision_time") or row.get("entry_feature_decision_time"),
                    "reasons": reasons,
                })
            continue

        identity = _candidate_identity(row, scope="holdout")
        if identity in existing_identities:
            duplicate += 1
            continue

        source_row = _without_outcome_fields(row)
        source_row.setdefault("selected_before_outcome", True)
        source_row.setdefault("candidate_selected_before_outcome", True)
        source_row.setdefault("candidate_selected_at", generated_utc)
        source_row.setdefault("future_labels_used_as_features", False)
        source_row.setdefault("post_outcome_candidate_selection", False)
        source_row.update({
            "schema_version": SCHEMA_VERSION,
            "producer": "forward_holdout_source_materializer",
            "forward_holdout_source_candidate": True,
            "forward_holdout_source_materialized_at": generated_utc,
            "forward_holdout_window_id": window.get("window_id") if isinstance(window, dict) else None,
            "forward_holdout_source_policy": (
                "pre-outcome full candidate_allocations only; no A-grade tier, "
                "fingerprint, bucket, allocator, or outcome mutation"
            ),
            "expected_selector_policy_fingerprint": expected_fingerprint,
            "paper_only_source_materializer": True,
            "places_real_order": False,
            "test_orders": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "old_redis_writes": False,
            "live_gate": status_module.LIVE_GATE,
        })
        if isinstance(window, dict):
            _increment_counter(window_counts, str(window.get("window_id") or "__missing__"))
        chain = _append_chain(
            chain_path=chain_path,
            event_type="forward_holdout_source_materialized",
            sidecar_path=source_jsonl,
            identity=identity,
            payload=source_row,
            generated_utc=generated_utc,
        )
        source_row["producer_hash_chain"] = chain
        _append_jsonl(source_jsonl, source_row)
        existing_identities.add(identity)
        appended += 1
        if len(appended_samples) < 20:
            appended_samples.append({
                "source_row_identity_hash": _sha256_text(_row_identity(source_row)),
                "candidate_identity": identity,
                "window_id": source_row.get("forward_holdout_window_id"),
                "symbol": status_module._normalized_symbol(source_row),
                "timeframe": status_module._row_value(source_row, "timeframe") or source_row.get("timeframe"),
                "side": status_module._directional_side(source_row),
                "decision_time": source_row.get("decision_time") or source_row.get("entry_feature_decision_time"),
                "paper_opportunity_tier": _paper_allocation_tier(source_row),
            })

    final_rows, source_status_after = _iter_jsonl(source_jsonl)
    status = (
        "READY_FORWARD_HOLDOUT_SOURCE_ROWS_APPENDED"
        if appended > 0
        else "READY_FORWARD_HOLDOUT_SOURCE_HAS_EXISTING_ROWS"
        if final_rows
        else "NO_GO_FORWARD_HOLDOUT_SOURCE_NO_ROWS_APPENDED"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "forward_holdout_source_materializer",
        "status": status,
        "selector_policy_fingerprint": expected_fingerprint,
        "source_jsonl": str(source_jsonl),
        "source_status_before": existing_status_before,
        "source_status_after": source_status_after,
        "input_source_statuses": source_statuses,
        "processed_source_row_count": len(source_rows),
        "full_candidate_allocation_source_row_count": full_candidate_allocation_count,
        "appended_count": appended,
        "duplicate_skipped_count": duplicate,
        "skipped_count": skipped,
        "skip_reason_counts": _sorted_counts(reason_counts),
        "source_path_counts": _sorted_counts(source_path_counts),
        "forward_holdout_window_counts": _sorted_counts(window_counts),
        "skip_samples": skip_samples,
        "appended_samples": appended_samples,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_selection": [],
        "does_not_mark_ready": True,
        "does_not_create_final_holdout_evidence": True,
        "does_not_create_a_grade_admission": True,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    history = _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=source_jsonl,
        manifest=manifest,
        generated_utc=generated_utc,
    )
    manifest["history"] = history
    _write_json(manifest_path, manifest)
    return manifest


def produce_holdout(
    *,
    source_jsonl: Path,
    rows_path: Path,
    registry_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    max_rows: int | None,
    generated_utc: str,
    construction_subset_status_path: Path = DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH,
    tail_source_rows: bool = False,
) -> dict[str, Any]:
    _touch(rows_path)
    pending_path = rows_path.with_name("out_of_sample_holdout_reverify_pending.jsonl")
    rejected_path = rows_path.with_name("out_of_sample_holdout_reverify_rejected.jsonl")
    _touch(pending_path)
    _touch(rejected_path)
    chain_path = rows_path.with_suffix(rows_path.suffix + ".hash_chain.jsonl")
    manifest_path = rows_path.with_suffix(rows_path.suffix + ".manifest.json")
    registry = _load_holdout_registry(
        registry_path=registry_path,
        source_path=source_jsonl,
        generated_utc=generated_utc,
    )
    rows, source_status = _iter_jsonl(source_jsonl)
    eligible_keys = _eligible_bucket_keys(bucket_matrix_path)
    if max_rows is None:
        source_rows = rows
    elif tail_source_rows:
        source_rows = rows[-max_rows:]
    else:
        source_rows = rows[:max_rows]
    construction_subset_identity_manifest_path = registry_path.with_name(
        DEFAULT_CONSTRUCTION_SUBSET_IDENTITY_MANIFEST_PATH.name
    )
    holdout_source_candidate_identity_manifest_path = registry_path.with_name(
        DEFAULT_HOLDOUT_SOURCE_CANDIDATE_IDENTITY_MANIFEST_PATH.name
    )
    holdout_source_candidate_identity_manifest = _construction_subset_identity_manifest(
        source_path=source_jsonl,
        source_status=source_status,
        source_rows=source_rows,
        expected_fingerprint=expected_fingerprint,
        eligible_bucket_keys=eligible_keys,
        generated_utc=generated_utc,
    )
    _write_json(
        holdout_source_candidate_identity_manifest_path,
        holdout_source_candidate_identity_manifest,
    )
    should_refresh_canonical_construction_manifest = (
        holdout_source_candidate_identity_manifest.get("status")
        == "PASSED_DERIVED_229_CONSTRUCTION_SUBSET_IDENTITIES"
        and len(source_rows) == int(
            holdout_source_candidate_identity_manifest.get("source_row_count") or -1
        )
    )
    if (
        should_refresh_canonical_construction_manifest
        or not construction_subset_identity_manifest_path.exists()
    ):
        _write_json(
            construction_subset_identity_manifest_path,
            holdout_source_candidate_identity_manifest,
        )
    local_construction_subset_status_path = registry_path.with_name(
        DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH.name
    )
    if (
        construction_subset_status_path == DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH
        and local_construction_subset_status_path.exists()
    ):
        construction_subset_status_path = local_construction_subset_status_path
    construction_subset_status = _construction_subset_identity_source_status(
        construction_subset_status_path
    )
    if (
        construction_subset_status_path == DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH
        and construction_subset_status.get("full_identity_set_available") is not True
    ):
        construction_subset_status_path = construction_subset_identity_manifest_path
        construction_subset_status = _construction_subset_identity_source_status(
            construction_subset_status_path
        )
    construction_subset_identity_manifest = _load_json(construction_subset_status_path)
    if not isinstance(construction_subset_identity_manifest, dict):
        construction_subset_identity_manifest = holdout_source_candidate_identity_manifest
    existing_final = _existing_identities(rows_path)
    pending_by_identity = _existing_rows_by_identity(pending_path)
    preexisting_pending = set(pending_by_identity)
    existing_pending = set(pending_by_identity)
    existing_rejected = _existing_identities(rejected_path)
    accepted = 0
    rejected = 0
    duplicate = 0
    pending = 0
    reason_counts: dict[str, int] = {}
    preflight_path = registry_path.with_name(DEFAULT_HOLDOUT_REGISTRY_PREFLIGHT_PATH.name)
    candidate_audit_path = registry_path.with_name(DEFAULT_HOLDOUT_WINDOW_CANDIDATE_AUDIT_PATH.name)
    promotion_packet_path = registry_path.with_name(DEFAULT_HOLDOUT_WINDOW_PROMOTION_PACKET_PATH.name)
    candidate_audit = _holdout_window_candidate_audit(
        source_path=source_jsonl,
        source_status=source_status,
        source_rows=source_rows,
        registry=registry,
        construction_subset_status=construction_subset_status,
        expected_fingerprint=expected_fingerprint,
        eligible_bucket_keys=eligible_keys,
        generated_utc=generated_utc,
    )
    _write_json(candidate_audit_path, candidate_audit)
    promotion_packet = _holdout_window_promotion_packet(
        candidate_audit=candidate_audit,
        registry_path=registry_path,
        expected_fingerprint=expected_fingerprint,
        generated_utc=generated_utc,
    )
    _write_json(promotion_packet_path, promotion_packet)
    registry_preflight = _holdout_registry_preflight(
        registry_path=registry_path,
        registry=registry,
        source_path=source_jsonl,
        source_status=source_status,
        source_rows=source_rows,
        construction_subset_status=construction_subset_status,
        expected_fingerprint=expected_fingerprint,
        eligible_bucket_keys=eligible_keys,
        generated_utc=generated_utc,
    )
    _write_json(preflight_path, registry_preflight)
    holdout_registry_manifest = _write_holdout_registry_manifest(
        registry_path=registry_path,
        source_path=source_jsonl,
        registry=registry,
        source_status=source_status,
        registry_preflight=registry_preflight,
        generated_utc=generated_utc,
    )
    source_gate_breakdown = _new_source_gate_breakdown(
        processed_source_row_count=len(source_rows),
    )
    for source_row in source_rows:
        identity = _candidate_identity(source_row, scope="holdout")
        if identity in existing_final:
            duplicate += 1
            source_gate_breakdown["existing_final_duplicate_count"] += 1
            continue
        window = _window_for_row(source_row, registry)
        forward_window = _window_is_forward_preregistered(window)
        has_outcome = _has_realtime_outcome(source_row)
        candidate = pending_by_identity.get(identity)
        reasons = _holdout_reject_reasons(
            source_row,
            registry=registry,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_keys,
            source_sha256=source_status.get("sha256"),
            construction_subset_status=construction_subset_status,
            require_label_outcome=has_outcome or not forward_window,
        )
        if has_outcome and forward_window:
            if identity not in preexisting_pending:
                reasons.append(
                    "MISSING_PREOUTCOME_PENDING_SELECTION_RECORD_FOR_FORWARD_HOLDOUT"
                )
            elif candidate is not None:
                combined_selection = _row_with_outcome_fields(candidate, source_row)
                reasons.extend(_post_outcome_selection_reasons(combined_selection))
        reasons = sorted(set(reasons))
        _record_source_gate_result(source_gate_breakdown, reasons=reasons)
        if reasons:
            if identity in existing_rejected:
                duplicate += 1
                continue
            rejected += 1
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            rejection = {
                "schema_version": SCHEMA_VERSION,
                "generated_utc": generated_utc,
                "scope": "holdout",
                "candidate_identity": identity,
                "source_row_identity": _row_identity(source_row),
                "symbol": status_module._normalized_symbol(source_row),
                "timeframe": status_module._row_value(source_row, "timeframe") or source_row.get("timeframe"),
                "side": status_module._directional_side(source_row),
                "decision_time": source_row.get("decision_time") or source_row.get("entry_feature_decision_time"),
                "reasons": reasons,
            }
            chain = _append_chain(
                chain_path=chain_path,
                event_type="holdout_rejected",
                sidecar_path=rejected_path,
                identity=identity,
                payload=rejection,
                generated_utc=generated_utc,
            )
            rejection["producer_hash_chain"] = chain
            _append_jsonl(rejected_path, rejection)
            existing_rejected.add(identity)
            continue
        if candidate is None:
            candidate = _candidate_record(
                source_row,
                scope="holdout",
                expected_fingerprint=expected_fingerprint,
                generated_utc=generated_utc,
            )
        if not has_outcome:
            if identity not in existing_pending:
                pending_chain = _append_chain(
                    chain_path=chain_path,
                    event_type="holdout_candidate_selected_before_label",
                    sidecar_path=pending_path,
                    identity=identity,
                    payload=candidate,
                    generated_utc=generated_utc,
                )
                candidate["producer_hash_chain"] = pending_chain
                _append_jsonl(pending_path, candidate)
                existing_pending.add(identity)
                pending_by_identity[identity] = candidate
                pending += 1
            else:
                duplicate += 1
            continue
        if identity not in existing_pending:
            pending_chain = _append_chain(
                chain_path=chain_path,
                event_type="holdout_candidate_selected_before_label",
                sidecar_path=pending_path,
                identity=identity,
                payload=candidate,
                generated_utc=generated_utc,
            )
            candidate["producer_hash_chain"] = pending_chain
            _append_jsonl(pending_path, candidate)
            existing_pending.add(identity)
            pending_by_identity[identity] = candidate
            pending += 1
            continue
        if identity not in preexisting_pending:
            duplicate += 1
            continue
        final = _final_holdout_record(source_row, candidate=candidate, registry=registry)
        final_chain = _append_chain(
            chain_path=chain_path,
            event_type="holdout_labeled",
            sidecar_path=rows_path,
            identity=identity,
            payload=final,
            generated_utc=generated_utc,
        )
        final["producer_hash_chain"] = final_chain
        _append_jsonl(rows_path, final)
        existing_final.add(identity)
        accepted += 1
    sidecar = _sidecar_summary(rows_path)
    pending_sidecar = _pending_sidecar_summary(
        pending_path,
        final_rows_path=rows_path,
        expected_fingerprint=expected_fingerprint,
        generated_utc=generated_utc,
        scope="holdout",
    )
    rejection_ledger = _rejection_ledger_summary(rejected_path)
    candidate_audit_windows = [
        window
        for window in candidate_audit.get("windows") or []
        if isinstance(window, dict)
    ]
    draft_decision_time_candidate_ready_count = sum(
        int(window.get("decision_time_candidate_ready_count") or 0)
        for window in candidate_audit_windows
    )
    draft_decision_time_ready_no_construction_overlap_count = sum(
        int(window.get("decision_time_ready_no_construction_overlap_count") or 0)
        for window in candidate_audit_windows
    )
    draft_decision_time_ready_construction_overlap_count = sum(
        int(window.get("decision_time_ready_construction_overlap_count") or 0)
        for window in candidate_audit_windows
    )
    clean_no_overlap_registry_template_count = sum(
        1
        for window in candidate_audit_windows
        if isinstance(window.get("clean_no_overlap_registry_window_template"), dict)
    )
    draft_decision_time_reject_reason_counts: dict[str, int] = {}
    for window in candidate_audit_windows:
        reason_counts_by_window = window.get("decision_time_reject_reason_counts")
        if not isinstance(reason_counts_by_window, dict):
            continue
        for reason, count in reason_counts_by_window.items():
            draft_decision_time_reject_reason_counts[str(reason)] = (
                draft_decision_time_reject_reason_counts.get(str(reason), 0)
                + int(count or 0)
            )
    holdout_prediction_coverage = _holdout_prediction_coverage_status(
        source_rows,
        registry=registry,
        expected_fingerprint=expected_fingerprint,
        source_sha256=source_status.get("sha256"),
        construction_subset_status=construction_subset_status,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "holdout",
        "status": (
            "READY"
            if accepted > 0
            else "READY_HOLDOUT_PENDING_SELECTIONS_APPENDED"
            if pending > 0
            else "NO_COUNTABLE_HOLDOUT_ROWS_APPENDED"
        ),
        "selector_policy_fingerprint": expected_fingerprint,
        "holdout_labeling_policy": "REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD",
        "labeled_from_preexisting_pending_count": accepted,
        "same_run_pending_rows_not_labeled_count": pending,
        "source_status": source_status,
        "source_row_selection_policy": (
            "tail_source_rows"
            if max_rows is not None and tail_source_rows
            else "head_source_rows"
            if max_rows is not None
            else "all_source_rows"
        ),
        "construction_subset_status_path": str(construction_subset_status_path),
        "construction_subset_identity_source_status": construction_subset_status,
        "holdout_source_candidate_identity_manifest_path": str(
            holdout_source_candidate_identity_manifest_path
        ),
        "holdout_source_candidate_identity_manifest": {
            "status": holdout_source_candidate_identity_manifest.get("status"),
            "validated_replay_candidate_count": (
                holdout_source_candidate_identity_manifest.get(
                    "validated_replay_candidate_count"
                )
            ),
            "expected_construction_candidate_count": (
                holdout_source_candidate_identity_manifest.get(
                    "expected_construction_candidate_count"
                )
            ),
            "candidate_count_matches_expected_229": (
                holdout_source_candidate_identity_manifest.get(
                    "candidate_count_matches_expected_229"
                )
            ),
            "selection_uses_outcome_fields": (
                holdout_source_candidate_identity_manifest.get(
                    "selection_uses_outcome_fields"
                )
            ),
            "outcome_fields_used_for_identity_derivation": (
                holdout_source_candidate_identity_manifest.get(
                    "outcome_fields_used_for_identity_derivation"
                )
            ),
            "identity_hash_count": holdout_source_candidate_identity_manifest.get(
                "identity_hash_count"
            ),
            "identity_hash_set_sha256": holdout_source_candidate_identity_manifest.get(
                "identity_hash_set_sha256"
            ),
            "not_countable_holdout_evidence": (
                holdout_source_candidate_identity_manifest.get(
                    "not_countable_holdout_evidence"
                )
            ),
        },
        "construction_subset_identity_manifest_path": str(
            construction_subset_identity_manifest_path
        ),
        "construction_subset_identity_manifest": {
            "status": construction_subset_identity_manifest.get("status"),
            "validated_replay_candidate_count": (
                construction_subset_identity_manifest.get(
                    "validated_replay_candidate_count"
                )
            ),
            "expected_construction_candidate_count": (
                construction_subset_identity_manifest.get(
                    "expected_construction_candidate_count"
                )
            ),
            "candidate_count_matches_expected_229": (
                construction_subset_identity_manifest.get(
                    "candidate_count_matches_expected_229"
                )
            ),
            "selection_uses_outcome_fields": (
                construction_subset_identity_manifest.get(
                    "selection_uses_outcome_fields"
                )
            ),
            "outcome_fields_used_for_identity_derivation": (
                construction_subset_identity_manifest.get(
                    "outcome_fields_used_for_identity_derivation"
                )
            ),
            "identity_hash_count": construction_subset_identity_manifest.get(
                "identity_hash_count"
            ),
            "identity_hash_set_sha256": construction_subset_identity_manifest.get(
                "identity_hash_set_sha256"
            ),
            "not_countable_holdout_evidence": (
                construction_subset_identity_manifest.get(
                    "not_countable_holdout_evidence"
                )
            ),
        },
        "bucket_matrix_path": str(bucket_matrix_path),
        "eligible_bucket_count": len(eligible_keys),
        "registry_path": str(registry_path),
        "registry_status": registry.get("status"),
        "holdout_registry_manifest_path": holdout_registry_manifest["manifest_path"],
        "holdout_registry_manifest_history_path": holdout_registry_manifest[
            "history"
        ]["history_path"],
        "holdout_registry_manifest": {
            "status": holdout_registry_manifest["manifest"].get("status"),
            "registry_sha256": holdout_registry_manifest["manifest"].get(
                "registry_sha256"
            ),
            "preflight_status": holdout_registry_manifest["manifest"].get(
                "preflight_status"
            ),
            "registered_window_count": holdout_registry_manifest["manifest"].get(
                "registered_window_count"
            ),
            "window_summaries": holdout_registry_manifest["manifest"].get(
                "window_summaries"
            ),
        },
        "holdout_registry_manifest_history": holdout_registry_manifest["history"],
        "holdout_registry_preflight_path": str(preflight_path),
        "holdout_registry_preflight": registry_preflight,
        "holdout_window_candidate_audit_path": str(candidate_audit_path),
        "holdout_window_candidate_audit": {
            "status": candidate_audit.get("status"),
            "draft_window_count": candidate_audit.get("draft_window_count"),
            "draft_windows_are_countable": candidate_audit.get("draft_windows_are_countable"),
            "selection_uses_outcome_fields": candidate_audit.get("selection_uses_outcome_fields"),
            "promotion_requires_exclusion_proof_status": candidate_audit.get(
                "promotion_requires_exclusion_proof_status"
            ),
            "promotion_requires_source_sha256_match": candidate_audit.get(
                "promotion_requires_source_sha256_match"
            ),
            "promotion_required_attestations": candidate_audit.get(
                "promotion_required_attestations"
            ),
            "readiness_uses_outcome_fields": candidate_audit.get("readiness_uses_outcome_fields"),
            "outcome_fields_used_for_readiness": candidate_audit.get(
                "outcome_fields_used_for_readiness"
            ),
            "draft_decision_time_candidate_ready_count": draft_decision_time_candidate_ready_count,
            "draft_decision_time_ready_no_construction_overlap_count": (
                draft_decision_time_ready_no_construction_overlap_count
            ),
            "draft_decision_time_ready_construction_overlap_count": (
                draft_decision_time_ready_construction_overlap_count
            ),
            "clean_no_overlap_registry_template_count": (
                clean_no_overlap_registry_template_count
            ),
            "draft_decision_time_reject_reason_counts": {
                key: draft_decision_time_reject_reason_counts[key]
                for key in sorted(draft_decision_time_reject_reason_counts)
            },
            "source_sha256": candidate_audit.get("source_sha256"),
            "construction_subset_identity_source_status": candidate_audit.get(
                "construction_subset_identity_source_status"
            ),
            "construction_subset_identity_proof_required": candidate_audit.get(
                "construction_subset_identity_proof_required"
            ),
            "construction_subset_identity_proof_required_status": (
                candidate_audit.get(
                    "construction_subset_identity_proof_required_status"
                )
            ),
        },
        "holdout_window_promotion_packet_path": str(promotion_packet_path),
        "holdout_window_promotion_packet": {
            "status": promotion_packet.get("status"),
            "draft_window_count": promotion_packet.get("draft_window_count"),
            "packet_is_countable_evidence": promotion_packet.get("packet_is_countable_evidence"),
            "source_sha256_match_required": promotion_packet.get("source_sha256_match_required"),
            "construction_subset_identity_proof_required": promotion_packet.get(
                "construction_subset_identity_proof_required"
            ),
            "construction_subset_identity_proof_required_status": promotion_packet.get(
                "construction_subset_identity_proof_required_status"
            ),
            "construction_subset_identity_source_status": promotion_packet.get(
                "construction_subset_identity_source_status"
            ),
            "promotion_required_exclusion_proof_status": promotion_packet.get(
                "promotion_required_exclusion_proof_status"
            ),
            "promotion_required_attestations": promotion_packet.get(
                "promotion_required_attestations"
            ),
            "promotion_readiness_summary": promotion_packet.get(
                "promotion_readiness_summary"
            ),
            "readiness_uses_outcome_fields": promotion_packet.get("readiness_uses_outcome_fields"),
            "outcome_fields_used_for_readiness": promotion_packet.get(
                "outcome_fields_used_for_readiness"
            ),
            "draft_decision_time_candidate_ready_count": draft_decision_time_candidate_ready_count,
        },
        "holdout_evidence_acquisition_status": _holdout_evidence_acquisition_status(
            registry_preflight=registry_preflight,
            candidate_audit=candidate_audit,
            promotion_packet=promotion_packet,
            accepted_count=accepted,
            pending_count=pending,
        ),
        "holdout_prediction_coverage_status": holdout_prediction_coverage,
        "registered_window_count": len(registry.get("windows") or []),
        "processed_source_row_count": len(source_rows),
        "accepted_appended_count": accepted,
        "pending_appended_count": pending,
        "rejected_appended_count": rejected,
        "duplicate_skipped_count": duplicate,
        "rejection_reason_counts": {
            key: reason_counts[key] for key in sorted(reason_counts)
        },
        "source_gate_breakdown": _finalize_source_gate_breakdown(source_gate_breakdown),
        "rejection_ledger_summary": rejection_ledger,
        "sidecar_summary": sidecar,
        "pending_sidecar_path": str(pending_path),
        "pending_sidecar_summary": pending_sidecar,
        "hash_chain_path": str(chain_path),
        "manifest_history_path": str(_manifest_history_path(manifest_path)),
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=rows_path,
        manifest=manifest,
        generated_utc=generated_utc,
    )
    return manifest


def _realtime_rows_from_redis(*, scan_limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = status_module._connect_redis()
    if client is None:
        return [], {
            "source": "redis",
            "status": "REDIS_UNAVAILABLE",
            "row_count": 0,
            "read_only": True,
        }
    ledger = status_module._redis_json(client, "v2:paper:ledger") or {}
    paper_signals = status_module._scan_redis_json_rows(
        client,
        "v2:signals:paper:*",
        limit=scan_limit,
    )
    prediction_rows = status_module._scan_redis_json_rows(
        client,
        "v2:prediction:*",
        limit=scan_limit,
    )
    latest_feature_rows = status_module._scan_redis_json_rows(
        client,
        "v2:features:latest:*",
        limit=scan_limit,
    )
    archived_feature_rows = status_module._read_archived_feature_rows_from_redis(
        client,
        prediction_rows + paper_signals,
        limit=scan_limit,
    )
    feature_rows = latest_feature_rows + archived_feature_rows
    prediction_rows = status_module._prediction_rows_with_pit_feature_market_cost_context(
        prediction_rows,
        feature_rows,
    )
    paper_intents = status_module._read_paper_intents_from_redis(
        client,
        fallback_ledger=ledger if isinstance(ledger, dict) else None,
    )
    counterfactual_paper_signals = status_module._counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        feature_rows=feature_rows,
    )
    accepted_rows = status_module._safe_rows(ledger if isinstance(ledger, dict) else {}, "accepted")
    raw_closed_trades = status_module._safe_rows(ledger if isinstance(ledger, dict) else {}, "closed_trades")
    closed_trades, accepted_reconciliation = status_module._reconcile_closed_trades_with_accepted_fills(
        closed_trades=raw_closed_trades,
        accepted_rows=accepted_rows,
    )
    open_positions = status_module._safe_rows(ledger if isinstance(ledger, dict) else {}, "open_positions")
    durable_accepted_rows, durable_accepted_evidence = status_module._paper_ledger_accepted_counterfactual_rows(
        ledger_payload=ledger if isinstance(ledger, dict) else {},
        base_source_rows=[*counterfactual_paper_signals, *paper_intents],
    )

    source_groups: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("redis_paper_intent", "v2:paper:intents+held", paper_intents),
        ("redis_paper_signal", "v2:signals:paper:*", counterfactual_paper_signals),
        ("redis_prediction", "v2:prediction:*", prediction_rows),
        ("redis_paper_ledger_accepted", "v2:paper:ledger.accepted", durable_accepted_rows),
        ("redis_paper_ledger_open", "v2:paper:ledger.open_positions", open_positions),
        ("redis_paper_ledger_closed", "v2:paper:ledger.closed_trades", closed_trades),
    ]
    rows: list[dict[str, Any]] = []
    group_counts: dict[str, int] = {}
    for source_kind, source_label, source_rows in source_groups:
        normalized_rows = [
            _normalize_realtime_source_row(
                row,
                source_kind=source_kind,
                source_label=source_label,
            )
            for row in source_rows
            if isinstance(row, dict)
        ]
        rows.extend(normalized_rows)
        group_counts[source_kind] = len(normalized_rows)
    return rows, {
        "source": "redis",
        "status": "READY_READ_ONLY_REDIS_SOURCE",
        "row_count": len(rows),
        "read_only": True,
        "scan_limit": scan_limit,
        "source_group_counts": group_counts,
        "paper_signal_row_count": len(paper_signals),
        "prediction_row_count": len(prediction_rows),
        "latest_feature_row_count": len(latest_feature_rows),
        "archived_feature_row_count": len(archived_feature_rows),
        "accepted_fill_reconciliation": accepted_reconciliation,
        "durable_accepted_counterfactual_evidence": durable_accepted_evidence,
    }


def _realtime_source_rows(
    json_sources: list[Path],
    jsonl_sources: list[Path],
    *,
    include_redis: bool,
    redis_scan_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for path in json_sources:
        source_rows, source_status = _rows_from_json(path)
        rows.extend(
            _normalize_realtime_source_row(
                row,
                source_kind="filesystem_runtime_snapshot",
                source_label=str(path),
            )
            for row in source_rows
        )
        statuses.append(source_status)
    for path in jsonl_sources:
        source_rows, source_status = _iter_jsonl(path)
        rows.extend(
            _normalize_realtime_source_row(
                row,
                source_kind="filesystem_runtime_snapshot",
                source_label=str(path),
            )
            for row in source_rows
        )
        statuses.append(source_status)
    if include_redis:
        redis_rows, redis_status = _realtime_rows_from_redis(scan_limit=redis_scan_limit)
        rows.extend(redis_rows)
        statuses.append(redis_status)
    return rows, statuses


def _realtime_reject_reasons(
    row: dict[str, Any],
    *,
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    require_pending_for_closed: bool,
    pending_by_identity: dict[str, dict[str, Any]],
    preexisting_pending_identities: set[str],
    resolved_identity: str,
    closed_outcome_identities: set[str],
    generated_utc: str,
) -> list[str]:
    reasons: list[str] = []
    identity = resolved_identity
    has_outcome = _has_realtime_outcome(row)
    pending_selection = pending_by_identity.get(identity)
    validation_selection = pending_selection if has_outcome and pending_selection is not None else row
    accounting_row = (
        _row_with_outcome_fields(validation_selection, row)
        if has_outcome and pending_selection is not None
        else row
    )
    reasons.extend(_fingerprint_reject_reasons(validation_selection, expected_fingerprint=expected_fingerprint))
    reasons.extend(_post_outcome_selection_reasons(validation_selection))
    selection_row = _without_outcome_fields(validation_selection)
    reasons.extend(_selector_reject_reasons(selection_row, eligible_bucket_keys=eligible_bucket_keys))
    reasons.extend(_accounting_reject_reasons(accounting_row))
    reasons.extend(_realtime_source_safety_reasons(validation_selection))
    if row is not validation_selection:
        reasons.extend(_closed_outcome_safety_reasons(row))
    if has_outcome and identity not in preexisting_pending_identities:
        reasons.append("PENDING_SELECTION_NOT_PREEXISTING_FOR_CLOSED_OUTCOME")
    if has_outcome and require_pending_for_closed and pending_selection is None:
        reasons.append("MISSING_PENDING_SELECTION_RECORD_FOR_CLOSED_OUTCOME")
    source_kind = str(row.get("_producer_source_kind") or "")
    if (
        not has_outcome
        and pending_selection is None
        and source_kind in HISTORICAL_REDIS_SOURCE_KINDS
    ):
        reasons.append("HISTORICAL_SOURCE_CANNOT_CREATE_NEW_PENDING_RECORD")
    if (
        not has_outcome
        and pending_selection is None
        and source_kind in PENDING_ELIGIBLE_SOURCE_KINDS
    ):
        source_age_seconds = _realtime_pending_source_age_seconds(row, generated_utc=generated_utc)
        if source_age_seconds is None:
            reasons.append("REALTIME_PENDING_SOURCE_FRESHNESS_TIMESTAMP_MISSING")
        elif source_age_seconds < -MAX_REALTIME_PENDING_SOURCE_CLOCK_SKEW_SECONDS:
            reasons.append("REALTIME_PENDING_SOURCE_TIMESTAMP_AFTER_PRODUCER_RUN")
        elif source_age_seconds > MAX_REALTIME_PENDING_SOURCE_AGE_SECONDS:
            reasons.append("REALTIME_PENDING_SOURCE_STALE_FOR_NEW_PENDING_RECORD")
    if (
        not has_outcome
        and pending_selection is None
        and (
            identity in closed_outcome_identities
            or bool(_candidate_identity_aliases(row, scope="realtime") & closed_outcome_identities)
        )
    ):
        reasons.append("HISTORICAL_ACCEPTED_ROW_ALREADY_HAS_CLOSED_OUTCOME_NO_PRIOR_PENDING_RECORD")
    if (
        not has_outcome
        and pending_selection is None
        and source_kind
        and source_kind not in PENDING_ELIGIBLE_SOURCE_KINDS
    ):
        reasons.append("SOURCE_KIND_NOT_ELIGIBLE_TO_CREATE_PENDING_RECORD")
    return sorted(set(reasons))


def _final_realtime_record(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    final = _payload_without_chain_metadata(candidate)
    for field in OUTCOME_FIELDS:
        if field in row:
            final[field] = row[field]
    final.update({
        "realtime_paper_reverify": True,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": status_module.LIVE_GATE,
    })
    return final


def produce_realtime(
    *,
    rows_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    json_sources: list[Path],
    jsonl_sources: list[Path],
    include_redis: bool,
    redis_scan_limit: int,
    require_pending_for_closed: bool,
    max_rows: int | None,
    generated_utc: str,
) -> dict[str, Any]:
    _touch(rows_path)
    pending_path = rows_path.with_name("out_of_sample_realtime_paper_reverify_pending.jsonl")
    rejected_path = rows_path.with_name("out_of_sample_realtime_paper_reverify_rejected.jsonl")
    _touch(pending_path)
    _touch(rejected_path)
    chain_path = rows_path.with_suffix(rows_path.suffix + ".hash_chain.jsonl")
    manifest_path = rows_path.with_suffix(rows_path.suffix + ".manifest.json")
    source_rows, source_statuses = _realtime_source_rows(
        json_sources,
        jsonl_sources,
        include_redis=include_redis,
        redis_scan_limit=redis_scan_limit,
    )
    source_rows = source_rows[:max_rows] if max_rows is not None else source_rows
    source_gate_breakdown = _new_source_gate_breakdown(
        processed_source_row_count=len(source_rows),
    )
    source_readiness_summary = _new_realtime_source_readiness_summary(
        processed_source_row_count=len(source_rows),
    )
    eligible_keys = _eligible_bucket_keys(bucket_matrix_path)
    existing_final = _existing_identities(rows_path)
    pending_by_identity = _existing_rows_by_identity(pending_path)
    preexisting_pending = set(pending_by_identity)
    pending_alias_index = _candidate_identity_alias_index(pending_by_identity, scope="realtime")
    existing_pending = set(pending_by_identity)
    existing_rejected = _existing_identities(rejected_path)
    closed_outcome_identities = {
        alias_identity
        for row in source_rows
        if _has_realtime_outcome(row)
        for alias_identity in _candidate_identity_aliases(row, scope="realtime")
    }
    accepted = 0
    pending = 0
    rejected = 0
    duplicate = 0
    reason_counts: dict[str, int] = {}
    for source_row in source_rows:
        identity = _resolve_candidate_identity(
            source_row,
            scope="realtime",
            alias_index=pending_alias_index,
        )
        if identity in existing_final:
            duplicate += 1
            source_gate_breakdown["existing_final_duplicate_count"] += 1
            _record_realtime_source_readiness(
                source_readiness_summary,
                row=source_row,
                reasons=[],
                existing_final_duplicate=True,
            )
            continue
        reasons = _realtime_reject_reasons(
            source_row,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_keys,
            require_pending_for_closed=require_pending_for_closed,
            pending_by_identity=pending_by_identity,
            preexisting_pending_identities=preexisting_pending,
            resolved_identity=identity,
            closed_outcome_identities=closed_outcome_identities,
            generated_utc=generated_utc,
        )
        _record_source_gate_result(source_gate_breakdown, reasons=reasons)
        _record_realtime_source_readiness(
            source_readiness_summary,
            row=source_row,
            reasons=reasons,
        )
        if reasons:
            if identity in existing_rejected:
                duplicate += 1
                continue
            rejected += 1
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            rejection = {
                "schema_version": SCHEMA_VERSION,
                "generated_utc": generated_utc,
                "scope": "realtime",
                "candidate_identity": identity,
                "source_row_identity": _row_identity(source_row),
                "source_path": source_row.get("_producer_source_path"),
                "source_kind": source_row.get("_producer_source_kind"),
                "symbol": status_module._normalized_symbol(source_row),
                "timeframe": status_module._row_value(source_row, "timeframe") or source_row.get("timeframe"),
                "side": status_module._directional_side(source_row),
                "decision_time": source_row.get("decision_time") or source_row.get("entry_feature_decision_time"),
                "reasons": reasons,
            }
            chain = _append_chain(
                chain_path=chain_path,
                event_type="realtime_rejected",
                sidecar_path=rejected_path,
                identity=identity,
                payload=rejection,
                generated_utc=generated_utc,
            )
            rejection["producer_hash_chain"] = chain
            _append_jsonl(rejected_path, rejection)
            existing_rejected.add(identity)
            continue
        has_outcome = _has_realtime_outcome(source_row)
        candidate = pending_by_identity.get(identity)
        if candidate is None:
            candidate = _candidate_record(
                source_row,
                scope="realtime",
                expected_fingerprint=expected_fingerprint,
                generated_utc=generated_utc,
            )
        if identity not in existing_pending:
            pending_chain = _append_chain(
                chain_path=chain_path,
                event_type="realtime_candidate_pending",
                sidecar_path=pending_path,
                identity=identity,
                payload=candidate,
                generated_utc=generated_utc,
            )
            candidate["producer_hash_chain"] = pending_chain
            _append_jsonl(pending_path, candidate)
            existing_pending.add(identity)
            pending_by_identity[identity] = candidate
            for alias_identity in _candidate_identity_aliases(candidate, scope="realtime"):
                pending_alias_index.setdefault(alias_identity, identity)
            pending += 1
        if not has_outcome:
            continue
        final = _final_realtime_record(source_row, candidate=candidate)
        final_chain = _append_chain(
            chain_path=chain_path,
            event_type="realtime_closed_outcome_labeled",
            sidecar_path=rows_path,
            identity=identity,
            payload=final,
            generated_utc=generated_utc,
        )
        final["producer_hash_chain"] = final_chain
        _append_jsonl(rows_path, final)
        existing_final.add(identity)
        accepted += 1
    sidecar = _sidecar_summary(rows_path)
    pending_sidecar = _pending_sidecar_summary(
        pending_path,
        final_rows_path=rows_path,
        expected_fingerprint=expected_fingerprint,
        generated_utc=generated_utc,
        scope="realtime",
    )
    rejection_ledger = _rejection_ledger_summary(rejected_path)
    source_gate_summary = _finalize_source_gate_breakdown(source_gate_breakdown)
    realtime_readiness_summary = _finalize_realtime_source_readiness_summary(
        source_readiness_summary,
    )
    paper_allocation_diagnostics = _paper_allocation_source_diagnostics(
        source_rows,
        expected_fingerprint=expected_fingerprint,
        eligible_bucket_keys=eligible_keys,
        generated_utc=generated_utc,
    )
    lineage_bridge_diagnostics = _low_fidelity_allocation_lineage_bridge_diagnostics(
        source_rows,
        expected_fingerprint=expected_fingerprint,
    )
    selector_bucket_diagnostics = _selector_bucket_diagnostics(
        source_rows,
        eligible_bucket_keys=eligible_keys,
    )
    selector_source_contract_diagnostics = _selector_source_contract_diagnostics(
        source_rows,
        eligible_bucket_keys=eligible_keys,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "realtime",
        "status": "READY" if accepted > 0 else "NO_COUNTABLE_REALTIME_ROWS_APPENDED",
        "selector_policy_fingerprint": expected_fingerprint,
        "realtime_labeling_policy": "REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD",
        "realtime_pending_source_freshness_policy": _realtime_pending_source_freshness_policy(),
        "labeled_from_preexisting_pending_count": accepted,
        "same_run_pending_rows_not_labeled_count": pending,
        "source_statuses": source_statuses,
        "bucket_matrix_path": str(bucket_matrix_path),
        "eligible_bucket_count": len(eligible_keys),
        "processed_source_row_count": len(source_rows),
        "include_redis": include_redis,
        "redis_scan_limit": redis_scan_limit,
        "accounting_alias_summary": _accounting_alias_summary(source_rows),
        "selector_context_alias_summary": _selector_context_alias_summary(source_rows),
        "accepted_appended_count": accepted,
        "pending_appended_count": pending,
        "rejected_appended_count": rejected,
        "duplicate_skipped_count": duplicate,
        "rejection_reason_counts": {
            key: reason_counts[key] for key in sorted(reason_counts)
        },
        "source_gate_breakdown": source_gate_summary,
        "realtime_source_readiness_summary": realtime_readiness_summary,
        "realtime_evidence_acquisition_status": _realtime_evidence_acquisition_status(
            source_gate_breakdown=source_gate_summary,
            source_readiness_summary=realtime_readiness_summary,
            paper_allocation_diagnostics=paper_allocation_diagnostics,
            selector_source_contract_diagnostics=selector_source_contract_diagnostics,
            lineage_bridge_diagnostics=lineage_bridge_diagnostics,
            accepted_count=accepted,
            pending_count=pending,
        ),
        "paper_event_source_diagnostics": _paper_event_source_diagnostics(source_rows),
        "paper_allocation_source_diagnostics": paper_allocation_diagnostics,
        "low_fidelity_allocation_lineage_bridge_diagnostics": lineage_bridge_diagnostics,
        "selector_bucket_diagnostics": selector_bucket_diagnostics,
        "selector_source_contract_diagnostics": selector_source_contract_diagnostics,
        "rejection_ledger_summary": rejection_ledger,
        "sidecar_summary": sidecar,
        "pending_sidecar_path": str(pending_path),
        "pending_sidecar_summary": pending_sidecar,
        "hash_chain_path": str(chain_path),
        "manifest_history_path": str(_manifest_history_path(manifest_path)),
        "replay_projection_expectancy_after_cost_bps": REPLAY_EXPECTANCY_AFTER_COST_BPS,
        "minimum_realtime_expectancy_after_cost_bps": MIN_REALTIME_EXPECTANCY_AFTER_COST_BPS,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    _append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=rows_path,
        manifest=manifest,
        generated_utc=generated_utc,
    )
    return manifest


def produce_realtime_watch(
    *,
    rows_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    json_sources: list[Path],
    jsonl_sources: list[Path],
    include_redis: bool,
    redis_scan_limit: int,
    require_pending_for_closed: bool,
    max_rows: int | None,
    cycles: int,
    poll_seconds: float,
) -> dict[str, Any]:
    cycles = max(1, cycles)
    cycle_summaries: list[dict[str, Any]] = []
    totals = {
        "accepted_appended_count": 0,
        "pending_appended_count": 0,
        "rejected_appended_count": 0,
        "duplicate_skipped_count": 0,
    }
    for cycle_index in range(cycles):
        cycle_generated_utc = _utc_iso()
        manifest = produce_realtime(
            rows_path=rows_path,
            bucket_matrix_path=bucket_matrix_path,
            expected_fingerprint=expected_fingerprint,
            json_sources=json_sources,
            jsonl_sources=jsonl_sources,
            include_redis=include_redis,
            redis_scan_limit=redis_scan_limit,
            require_pending_for_closed=require_pending_for_closed,
            max_rows=max_rows,
            generated_utc=cycle_generated_utc,
        )
        cycle_summary = {
            "cycle_index": cycle_index,
            "generated_utc": cycle_generated_utc,
            "status": manifest.get("status"),
            "processed_source_row_count": manifest.get("processed_source_row_count"),
            "accepted_appended_count": manifest.get("accepted_appended_count"),
            "pending_appended_count": manifest.get("pending_appended_count"),
            "rejected_appended_count": manifest.get("rejected_appended_count"),
            "duplicate_skipped_count": manifest.get("duplicate_skipped_count"),
            "rejection_reason_counts": manifest.get("rejection_reason_counts"),
        }
        cycle_summaries.append(cycle_summary)
        for key in totals:
            totals[key] += int(manifest.get(key) or 0)
        if cycle_index < cycles - 1 and poll_seconds > 0.0:
            time.sleep(poll_seconds)

    last_manifest = cycle_summaries[-1] if cycle_summaries else {}
    status = (
        "READY_REALTIME_WATCH_CAPTURED_COUNTABLE_ROWS"
        if totals["accepted_appended_count"] > 0
        else "READY_REALTIME_WATCH_CAPTURED_PENDING_ROWS"
        if totals["pending_appended_count"] > 0
        else "NO_COUNTABLE_REALTIME_ROWS_APPENDED"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _utc_iso(),
        "producer": "realtime_watch",
        "status": status,
        "cycles_requested": cycles,
        "cycles_completed": len(cycle_summaries),
        "poll_seconds": poll_seconds,
        "include_redis": include_redis,
        "redis_scan_limit": redis_scan_limit,
        "selector_policy_fingerprint": expected_fingerprint,
        "totals": totals,
        "last_cycle": last_manifest,
        "cycle_summaries": cycle_summaries,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
        "notes": (
            "Bounded local watcher for genuine realtime paper evidence. It polls read-only sources "
            "and appends only immutable sidecar/hash-chain records through produce_realtime."
        ),
    }


def regenerate_status(*, horizon_years: float) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "v2.backend.app.cli.v2_adaptive_capital_productivity_status",
        "--horizon-years",
        str(horizon_years),
    ]
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    log_path = DEFAULT_OUT_DIR / "out_of_sample_evidence_producer_status_regeneration.log"
    log_path.write_text(completed.stdout + completed.stderr)
    dashboard = _load_json(DEFAULT_OUT_DIR / "operator_dashboard_payload.json")
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    out_of_sample = dashboard.get("out_of_sample_live_grade_reverify_status")
    out_of_sample = out_of_sample if isinstance(out_of_sample, dict) else {}
    overall_status = dashboard.get("overall_status")
    regeneration_status = (
        "PASSED_STATUS_REGENERATED"
        if completed.returncode == 0
        else "READY_STATUS_REGENERATED_WITH_NO_GO_GATE"
        if completed.returncode == 2 and overall_status == "NO_GO"
        else "NO_GO_STATUS_REGENERATION_COMMAND_FAILED"
    )
    return {
        "status": regeneration_status,
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started, 8),
        "log_path": str(log_path),
        "dashboard_generated_utc": dashboard.get("generated_utc"),
        "dashboard_overall_status": overall_status,
        "out_of_sample_live_grade_status": out_of_sample.get("status"),
    }


def _compact_producer_summary(summary: dict[str, Any]) -> dict[str, Any]:
    realtime = summary.get("realtime") if isinstance(summary.get("realtime"), dict) else {}
    holdout = summary.get("holdout") if isinstance(summary.get("holdout"), dict) else {}
    forward_source = (
        summary.get("forward_holdout_source")
        if isinstance(summary.get("forward_holdout_source"), dict)
        else {}
    )
    realtime_acquisition = (
        realtime.get("realtime_evidence_acquisition_status")
        if isinstance(realtime.get("realtime_evidence_acquisition_status"), dict)
        else {}
    )
    holdout_acquisition = (
        holdout.get("holdout_evidence_acquisition_status")
        if isinstance(holdout.get("holdout_evidence_acquisition_status"), dict)
        else {}
    )
    return {
        "schema_version": summary.get("schema_version"),
        "generated_utc": summary.get("generated_utc"),
        "producer": summary.get("producer"),
        "safety": {
            "paper_only": summary.get("paper_only") is True,
            "places_real_order": summary.get("places_real_order") is True,
            "test_orders": summary.get("test_orders") is True,
            "leverage_mutation": summary.get("leverage_mutation") is True,
            "margin_mode_mutation": summary.get("margin_mode_mutation") is True,
            "old_redis_writes": summary.get("old_redis_writes") is True,
        },
        "holdout": {
            "status": holdout.get("status"),
            "accepted_appended_count": holdout.get("accepted_appended_count"),
            "pending_appended_count": holdout.get("pending_appended_count"),
            "rejected_appended_count": holdout.get("rejected_appended_count"),
            "duplicate_skipped_count": holdout.get("duplicate_skipped_count"),
            "acquisition_status": holdout_acquisition.get("status"),
            "registered_window_count": holdout_acquisition.get("registered_window_count"),
            "statically_eligible_window_count": holdout_acquisition.get(
                "statically_eligible_window_count"
            ),
        },
        "forward_holdout_source": {
            "status": forward_source.get("status"),
            "processed_source_row_count": forward_source.get("processed_source_row_count"),
            "full_candidate_allocation_source_row_count": forward_source.get(
                "full_candidate_allocation_source_row_count"
            ),
            "appended_count": forward_source.get("appended_count"),
            "duplicate_skipped_count": forward_source.get("duplicate_skipped_count"),
            "skipped_count": forward_source.get("skipped_count"),
            "top_skip_reasons": [
                {"reason": reason, "row_count": count}
                for reason, count in list(
                    (forward_source.get("skip_reason_counts") or {}).items()
                )[:10]
            ] if isinstance(forward_source.get("skip_reason_counts"), dict) else None,
        },
        "realtime": {
            "status": realtime.get("status"),
            "processed_source_row_count": realtime.get("processed_source_row_count"),
            "accepted_appended_count": realtime.get("accepted_appended_count"),
            "pending_appended_count": realtime.get("pending_appended_count"),
            "rejected_appended_count": realtime.get("rejected_appended_count"),
            "duplicate_skipped_count": realtime.get("duplicate_skipped_count"),
            "acquisition_status": realtime_acquisition.get("status"),
            "candidate_ready_source_row_count": realtime_acquisition.get(
                "candidate_ready_source_row_count"
            ),
            "candidate_allocation_count": realtime_acquisition.get(
                "candidate_allocation_count"
            ),
            "ready_full_candidate_allocation_count": realtime_acquisition.get(
                "ready_full_candidate_allocation_count"
            ),
            "top_rejection_reasons": (
                realtime.get("rejection_ledger_summary", {}).get("top_rejection_reasons")
                if isinstance(realtime.get("rejection_ledger_summary"), dict)
                else None
            ),
        },
        "integrity_status": (
            summary.get("integrity", {}).get("status")
            if isinstance(summary.get("integrity"), dict)
            else None
        ),
        "status_regeneration_status": (
            summary.get("status_regeneration", {}).get("status")
            if isinstance(summary.get("status_regeneration"), dict)
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "producer",
        choices=(
            "holdout",
            "realtime",
            "both",
            "verify",
            "forward-holdout-source",
            "holdout-attestation-request",
            "draft-holdout-registry",
            "promote-holdout-registry",
            "forward-holdout-preregistration",
        ),
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--bucket-matrix", type=Path, default=DEFAULT_BUCKET_MATRIX_PATH)
    parser.add_argument("--holdout-source-jsonl", type=Path, default=DEFAULT_HOLDOUT_SOURCE_JSONL)
    parser.add_argument(
        "--forward-holdout-source-jsonl",
        type=Path,
        default=DEFAULT_FORWARD_HOLDOUT_SOURCE_JSONL,
    )
    parser.add_argument("--holdout-registry", type=Path, default=DEFAULT_HOLDOUT_REGISTRY_PATH)
    parser.add_argument(
        "--holdout-promotion-packet",
        type=Path,
        default=DEFAULT_HOLDOUT_WINDOW_PROMOTION_PACKET_PATH,
    )
    parser.add_argument("--holdout-attestation", type=Path, default=None)
    parser.add_argument(
        "--holdout-registry-promotion-manifest",
        type=Path,
        default=DEFAULT_HOLDOUT_REGISTRY_PROMOTION_MANIFEST_PATH,
    )
    parser.add_argument(
        "--holdout-registry-draft-manifest",
        type=Path,
        default=DEFAULT_HOLDOUT_REGISTRY_DRAFT_MANIFEST_PATH,
    )
    parser.add_argument(
        "--holdout-attestation-request",
        type=Path,
        default=DEFAULT_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST_PATH,
    )
    parser.add_argument(
        "--forward-holdout-registration-manifest",
        type=Path,
        default=DEFAULT_FORWARD_HOLDOUT_REGISTRATION_MANIFEST_PATH,
    )
    parser.add_argument("--forward-window-start", default=None)
    parser.add_argument("--forward-start-delay-minutes", type=float, default=5.0)
    parser.add_argument("--forward-window-minutes", type=float, default=1440.0)
    parser.add_argument("--forward-window-count", type=int, default=7)
    parser.add_argument("--forward-symbol", action="append", default=[])
    parser.add_argument("--forward-timeframe", action="append", default=[])
    parser.add_argument("--holdout-rows", type=Path, default=DEFAULT_HOLDOUT_ROWS_PATH)
    parser.add_argument(
        "--construction-subset-status",
        type=Path,
        default=DEFAULT_CONSTRUCTION_SUBSET_STATUS_PATH,
    )
    parser.add_argument("--realtime-rows", type=Path, default=DEFAULT_REALTIME_ROWS_PATH)
    parser.add_argument("--paper-status-json", type=Path, default=DEFAULT_PAPER_LIVE_STATUS_PATH)
    parser.add_argument("--paper-ledger-json", type=Path, default=DEFAULT_PAPER_LEDGER_TAIL_PATH)
    parser.add_argument(
        "--current-signal-lineage-json",
        type=Path,
        default=DEFAULT_CURRENT_SIGNAL_LINEAGE_PATH,
    )
    parser.add_argument(
        "--paper-runtime-status-json",
        type=Path,
        default=DEFAULT_PAPER_RUNTIME_STATUS_PATH,
    )
    parser.add_argument(
        "--paper-loop-once-status-json",
        type=Path,
        default=DEFAULT_PAPER_LOOP_ONCE_STATUS_PATH,
    )
    parser.add_argument(
        "--paper-adaptive-sizing-status-json",
        type=Path,
        default=DEFAULT_PAPER_ADAPTIVE_SIZING_STATUS_PATH,
    )
    parser.add_argument("--paper-events-jsonl", type=Path, default=DEFAULT_PAPER_EVENTS_PATH)
    parser.add_argument("--selector-policy-fingerprint", default=EXPECTED_SELECTOR_POLICY_FINGERPRINT)
    parser.add_argument("--read-redis", action="store_true")
    parser.add_argument("--redis-scan-limit", type=int, default=5000)
    parser.add_argument("--realtime-redis-only", action="store_true")
    parser.add_argument("--realtime-skip-jsonl-sources", action="store_true")
    parser.add_argument("--realtime-watch-cycles", type=int, default=1)
    parser.add_argument("--realtime-watch-poll-seconds", type=float, default=0.0)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--tail-source-rows", action="store_true")
    parser.add_argument("--allow-closed-without-pending", action="store_true")
    parser.add_argument("--verify-integrity", action="store_true")
    parser.add_argument("--regenerate-status", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--horizon-years", type=float, default=5.0)
    args = parser.parse_args(argv)

    generated_utc = _utc_iso()
    summary_path = (
        args.out_dir / "out_of_sample_holdout_window_registry_promotion_summary.json"
        if args.producer == "promote-holdout-registry"
        else args.out_dir / "out_of_sample_holdout_untouched_attestation_request_summary.json"
        if args.producer == "holdout-attestation-request"
        else args.out_dir / "out_of_sample_holdout_window_registry_draft_summary.json"
        if args.producer == "draft-holdout-registry"
        else args.out_dir / "out_of_sample_forward_holdout_pre_registration_summary.json"
        if args.producer == "forward-holdout-preregistration"
        else args.out_dir / "out_of_sample_forward_holdout_source_summary.json"
        if args.producer == "forward-holdout-source"
        else args.out_dir / "out_of_sample_evidence_producer_summary.json"
    )
    previous_summary = _load_json(summary_path)
    previous_summary = previous_summary if isinstance(previous_summary, dict) else {}
    summaries: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "selector_policy_fingerprint": args.selector_policy_fingerprint,
        "producer": args.producer,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    realtime_json_sources = (
        []
        if args.realtime_redis_only
        else [
            args.paper_status_json,
            args.paper_ledger_json,
            args.current_signal_lineage_json,
            args.paper_runtime_status_json,
            args.paper_loop_once_status_json,
            args.paper_adaptive_sizing_status_json,
        ]
    )
    realtime_jsonl_sources = (
        []
        if args.realtime_redis_only or args.realtime_skip_jsonl_sources
        else [args.paper_events_jsonl]
    )
    forward_holdout_json_sources = [
        args.paper_status_json,
        args.paper_loop_once_status_json,
        args.paper_adaptive_sizing_status_json,
    ]
    if args.producer == "holdout-attestation-request":
        summaries["holdout_attestation_request"] = build_holdout_untouched_attestation_request(
            promotion_packet_path=args.holdout_promotion_packet,
            source_path=args.holdout_source_jsonl,
            expected_fingerprint=args.selector_policy_fingerprint,
            generated_utc=generated_utc,
            request_path=args.holdout_attestation_request,
        )
    if args.producer == "draft-holdout-registry":
        summaries["holdout_registry_draft"] = draft_holdout_registry_from_packet(
            promotion_packet_path=args.holdout_promotion_packet,
            registry_path=args.holdout_registry,
            source_path=args.holdout_source_jsonl,
            bucket_matrix_path=args.bucket_matrix,
            expected_fingerprint=args.selector_policy_fingerprint,
            generated_utc=generated_utc,
            construction_subset_status_path=args.construction_subset_status,
            manifest_path=args.holdout_registry_draft_manifest,
        )
    if args.producer == "promote-holdout-registry":
        summaries["holdout_registry_promotion"] = promote_holdout_registry_from_packet(
            promotion_packet_path=args.holdout_promotion_packet,
            attestation_path=args.holdout_attestation,
            registry_path=args.holdout_registry,
            source_path=args.holdout_source_jsonl,
            expected_fingerprint=args.selector_policy_fingerprint,
            generated_utc=generated_utc,
            manifest_path=args.holdout_registry_promotion_manifest,
        )
    if args.producer == "forward-holdout-preregistration":
        summaries["forward_holdout_preregistration"] = forward_preregister_holdout_registry(
            registry_path=args.holdout_registry,
            source_path=args.holdout_source_jsonl,
            bucket_matrix_path=args.bucket_matrix,
            expected_fingerprint=args.selector_policy_fingerprint,
            generated_utc=generated_utc,
            window_start=args.forward_window_start,
            start_delay_minutes=args.forward_start_delay_minutes,
            window_minutes=args.forward_window_minutes,
            window_count=args.forward_window_count,
            symbols=args.forward_symbol,
            timeframes=args.forward_timeframe,
            construction_subset_status_path=args.construction_subset_status,
            manifest_path=args.forward_holdout_registration_manifest,
        )
    if args.producer == "forward-holdout-source":
        summaries["forward_holdout_source"] = materialize_forward_holdout_source(
            source_jsonl=args.forward_holdout_source_jsonl,
            registry_path=args.holdout_registry,
            json_sources=forward_holdout_json_sources,
            expected_fingerprint=args.selector_policy_fingerprint,
            max_rows=args.max_rows,
            generated_utc=generated_utc,
        )
    if args.producer in {"holdout", "both"}:
        summaries["holdout"] = produce_holdout(
            source_jsonl=args.holdout_source_jsonl,
            rows_path=args.holdout_rows,
            registry_path=args.holdout_registry,
            bucket_matrix_path=args.bucket_matrix,
            expected_fingerprint=args.selector_policy_fingerprint,
            max_rows=args.max_rows,
            generated_utc=generated_utc,
            construction_subset_status_path=args.construction_subset_status,
            tail_source_rows=args.tail_source_rows,
        )
    if args.producer in {"realtime", "both"}:
        if args.realtime_watch_cycles > 1:
            watch_summary = produce_realtime_watch(
                rows_path=args.realtime_rows,
                bucket_matrix_path=args.bucket_matrix,
                expected_fingerprint=args.selector_policy_fingerprint,
                json_sources=realtime_json_sources,
                jsonl_sources=realtime_jsonl_sources,
                include_redis=args.read_redis,
                redis_scan_limit=args.redis_scan_limit,
                require_pending_for_closed=not args.allow_closed_without_pending,
                max_rows=args.max_rows,
                cycles=args.realtime_watch_cycles,
                poll_seconds=args.realtime_watch_poll_seconds,
            )
            summaries["realtime_watch"] = watch_summary
            summaries["realtime"] = _load_json(_sidecar_manifest_path(args.realtime_rows)) or {}
        else:
            summaries["realtime"] = produce_realtime(
                rows_path=args.realtime_rows,
                bucket_matrix_path=args.bucket_matrix,
                expected_fingerprint=args.selector_policy_fingerprint,
                json_sources=realtime_json_sources,
                jsonl_sources=realtime_jsonl_sources,
                include_redis=args.read_redis,
                redis_scan_limit=args.redis_scan_limit,
                require_pending_for_closed=not args.allow_closed_without_pending,
                max_rows=args.max_rows,
                generated_utc=generated_utc,
            )
    if args.producer == "verify" or args.verify_integrity:
        summaries.setdefault("holdout", _load_json(_sidecar_manifest_path(args.holdout_rows)) or {})
        summaries.setdefault("realtime", _load_json(_sidecar_manifest_path(args.realtime_rows)) or {})
        if "realtime_watch" in previous_summary:
            summaries.setdefault("realtime_watch", previous_summary["realtime_watch"])
        holdout_registry_for_integrity: Path | None = None
        holdout_registry_manifest_path = _holdout_registry_manifest_path(args.holdout_registry)
        try:
            holdout_registry_under_out_dir = (
                args.holdout_registry.parent.resolve() == args.out_dir.resolve()
            )
        except OSError:
            holdout_registry_under_out_dir = False
        if holdout_registry_manifest_path.exists() and (
            args.producer in {"holdout", "both"} or holdout_registry_under_out_dir
        ):
            holdout_registry_for_integrity = args.holdout_registry
        summaries["integrity"] = verify_evidence_integrity(
            holdout_rows=args.holdout_rows,
            realtime_rows=args.realtime_rows,
            out_dir=args.out_dir,
            generated_utc=generated_utc,
            holdout_registry=holdout_registry_for_integrity,
        )
    if args.regenerate_status:
        summaries["status_regeneration"] = regenerate_status(horizon_years=args.horizon_years)
    _write_json(summary_path, summaries)
    printable = _compact_producer_summary(summaries) if args.summary_only else summaries
    print(json.dumps(printable, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
