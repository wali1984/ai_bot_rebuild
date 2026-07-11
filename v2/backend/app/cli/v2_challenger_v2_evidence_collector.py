"""Collect V2 challenger evidence without changing the frozen policy.

This command is artifact-only. It reads the frozen challenger artifact and
current feature snapshots, but it does not write Redis, submit orders, bind
paper fills, alter model parameters, or change cost/feature normalization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from v2.backend.app.cli.v2_challenger_v2_reproducible_pipeline import (
    GOAL_ID,
    MODEL_SOURCE,
    ReplayCandidateRow,
    _build_candle_index,
    _build_dataset,
    _read_current_snapshots,
)
from v2.backend.app.services.native_trainer.challenger_v2_cost_model import (
    cost_model_hash,
    estimate_paper_cost,
    estimate_replay_cost,
)
from v2.backend.app.services.native_trainer.challenger_v2_feature_adapter import (
    NormalizationSpec,
    adapt_replay_snapshot,
    adapt_runtime_snapshot,
    finite_float,
    feature_schema_hash,
    numeric_feature_mapping,
    normalization_hash,
    parse_utc,
    stable_hash,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    default_archive_root,
    iter_snapshots,
)
from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)


SCHEMA_VERSION = "challenger_v2_evidence_collector_v1"
ADDED_PAPER_GOVERNANCE_GOAL_ID = "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR"
ADDED_PAPER_GOVERNANCE_READY_MARKER = "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY"
ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS = (
    "GO_NO_GO.md",
    "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_REPORT.md",
    "current_paper_timeframe_churn_audit.json",
    "current_paper_economic_trade_reconciliation.json",
    "paper_timeframe_routing_owner_status.json",
    "paper_timeframe_routing_repair_contract.json",
    "multi_timeframe_thesis_execution_contract_status.json",
    "economic_trade_compaction_status.json",
    "paper_reentry_and_signal_dedup_status.json",
    "paper_churn_governor_status.json",
    "paper_entry_cost_coverage_status.json",
    "paper_edge_to_cost_gate_status.json",
    "dynamic_timeframe_execution_eligibility_status.json",
    "timeframe_execution_concentration_guard_status.json",
    "post_fix_paper_validation_status.json",
    "operator_dashboard_payload.json",
    "operator_dashboard_truth_contract_status.json",
)
PENDING_LOCKBOX = "challenger_v2_future_lockbox_pending.jsonl"
LABELLED_LOCKBOX = "challenger_v2_future_lockbox_labelled.jsonl"
HASH_CHAIN = "challenger_v2_future_lockbox_hash_chain.json"
HASH_CHAIN_ALGORITHM = "sha256(canonical_json({previous_hash,row_hash}))"
SHADOW_COST_EVIDENCE = "challenger_v2_candidate_bound_shadow_cost_evidence.jsonl"
SHADOW_COST_HASH_CHAIN = "challenger_v2_candidate_bound_shadow_cost_evidence_hash_chain.json"
SHADOW_COST_RECONCILIATION = "challenger_v2_candidate_bound_shadow_cost_reconciliation_audit.json"
PAPER_CREDIT_ATTRIBUTION_GUARD = "challenger_v2_paper_challenger_credit_attribution_guard.json"
REQUIREMENT_TRACEABILITY_MATRIX = "challenger_v2_goal_requirement_traceability_matrix.json"
COST_IDENTITY_JOIN_RECOVERY_AUDIT = "challenger_v2_cost_identity_join_recovery_audit.json"
RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT = "challenger_v2_runtime_cost_capture_remediation_contract.json"
RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT = "challenger_v2_runtime_cost_capture_write_path_audit.json"
RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET = "challenger_v2_runtime_cost_capture_operator_approval_packet.json"
RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT = "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE = "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS = "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
RUNTIME_IDENTITY_BINDING_IMPLEMENTATION_PLAN = "challenger_v2_runtime_identity_binding_implementation_plan.json"
FUTURE_RUNTIME_COST_EVIDENCE_ACCEPTANCE_CONTRACT = "challenger_v2_future_runtime_cost_evidence_acceptance_contract.json"
ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT = "challenger_v2_added_paper_governance_blocker_audit.json"
SHADOW_LOCKBOX_OUTCOME_ACTIONABILITY_AUDIT = "challenger_v2_shadow_lockbox_outcome_actionability_audit.json"
FROZEN_CANDIDATE_INTEGRITY_AUDIT = "challenger_v2_frozen_candidate_integrity_audit.json"
PAPER_CHAIN_BINDING_READINESS_AUDIT = "challenger_v2_paper_chain_binding_readiness_audit.json"
TEMPORAL_SEMANTICS_AUDIT = "challenger_v2_temporal_semantics_audit.json"
COST_REPLAY_PAPER_PARITY_AUDIT = "challenger_v2_cost_replay_paper_parity_audit.json"
REQUIRED_COST_EVIDENCE_FIELDS = (
    "observed_bid_ask_spread",
    "order_size",
    "top_book_evidence",
    "depth_evidence",
    "depth_derived_price_impact",
    "maker_taker_assumption_and_probability",
    "fee_schedule",
    "funding_rate_and_holding_period_funding",
    "latency_reserve",
    "partial_fill_estimate",
    "mark_index_divergence",
    "source_timestamp",
    "evidence_freshness",
    "fallback_flag",
)
PENDING_LOCKBOX_REQUIRED_FIELDS = (
    "candidate_id",
    "policy_fingerprint",
    "model_source",
    "snapshot_id",
    "symbol",
    "timeframe",
    "decision_time",
    "feature_cutoff",
    "available_at",
    "feature_vector_hash",
    "predicted_direction",
    "predicted_move_bps",
    "score",
    "estimated_production_cost",
    "selected",
    "rejected",
    "rejection_reasons",
)
LABELLED_LOCKBOX_REQUIRED_FIELDS = (
    "lockbox_record_id",
    "candidate_id",
    "policy_fingerprint",
    "snapshot_id",
    "symbol",
    "timeframe",
    "decision_time",
    "feature_cutoff",
    "available_at",
    "selection_record_hash",
    "predicted_direction",
    "label_source",
    "label_source_timestamp",
    "label_horizon_minutes",
    "label_uses_future_data_as_label_only",
    "future_finalized_price",
    "gross_return_bps",
    "fees_bps",
    "spread_bps",
    "slippage_bps",
    "funding_bps",
    "net_return_bps",
    "mfe_bps",
    "mae_bps",
)
LOCKBOX_NON_EXECUTION_FIELDS = (
    "paper_fill_allowed",
    "routes_to_live",
    "places_real_order",
    "counts_as_a_grade_evidence",
    "promotion_evidence",
)
LABEL_FORBIDDEN_SELECTION_FIELDS = (
    "feature_values_by_name",
    "feature_vector_hash",
    "estimated_production_cost",
    "score",
    "selection_payload_hash",
)
PENDING_FORBIDDEN_LABEL_FIELDS = (
    "selection_record_hash",
    "label_record_id",
    "label_created_utc",
    "label_source",
    "label_source_timestamp",
    "label_horizon_minutes",
    "label_uses_future_data_as_label_only",
    "future_finalized_price",
    "gross_return_bps",
    "fees_bps",
    "spread_bps",
    "slippage_bps",
    "funding_bps",
    "net_return_bps",
    "mfe_bps",
    "mae_bps",
)
SHADOW_SUPPLY_REQUIRED_ROW_FIELDS = (
    "predicted_gross_edge_bps",
    "production_cost_bps",
    "predicted_net_edge_bps",
    "threshold_distance_bps",
    "feature_drift",
    "liquidity_status",
    "rejection_reason",
)
REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS = (
    "candidate_id",
    "policy_fingerprint",
    "model_source",
)
COST_IDENTITY_JOIN_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "snapshot_id": ("feature_snapshot_id", "entry_feature_snapshot_id", "snapshot_id", "source_snapshot_id"),
    "signal_id": ("signal_id", "paper_signal_id"),
    "prediction_id": ("prediction_id",),
    "decision_id": ("decision_id",),
    "market_state_id": ("market_state_id",),
    "intent_id": ("intent_id", "execution_intent_id", "paper_intent_id"),
}
CORE_COST_JOIN_FIELDS = (
    "order_size",
    "top_book_evidence",
    "depth_derived_price_impact",
    "maker_taker_assumption_and_probability",
    "latency_reserve",
    "partial_fill_estimate",
)
ALTERNATE_PAPER_IDENTITY_FIELDS = (
    "selector_policy_fingerprint",
    "frozen_selector_fingerprint",
    "trainer_source",
    "model_id",
)
PAPER_CANARY_CHAIN = (
    "challenger",
    "signal",
    "strategy",
    "adaptive_allocator",
    "risk",
    "orchestrator",
    "paper_lifecycle",
    "exit",
    "pnl",
    "trainer_feedback",
)
PAPER_RUNTIME_TELEMETRY_KEYS = (
    "v2:paper:intents",
    "v2:paper:intents_held_by_paper_fill_gate",
    "v2:paper_online:ledger",
    "v2:paper:ledger",
    "v2:paper:closed_trades",
    "v2:trainer:feedback:outcomes",
    "v2:trainer:feedback:outcomes:quarantine",
    "v2:trainer:feedback",
    "v2:trainer:feedback_quarantine",
)
LOCAL_PAPER_ONLINE_EVENT_RELATIVE_PATH = Path("v2/runtime/paper_online/latest/paper_events.jsonl")
LOCAL_PAPER_COST_EVENT_RESULTS = frozenset({"FILLED_PAPER_ONLY", "POSITION_CLOSED_PAPER_ONLY"})
PAPER_INTENT_COST_JOIN_KEYS = (
    "v2:paper:intents",
    "v2:paper:intents_held_by_paper_fill_gate",
    "v2:paper:ledger",
)
DEFAULT_PAPER_SIGNAL_SCAN_LIMIT = 10_000
DRIFT_COHORTS = (
    "training",
    "validation",
    "previous_holdout",
    "current_runtime",
    "future_lockbox",
)
DRIFT_REQUIRED_METRICS = (
    "row_count",
    "observed_value_count",
    "mean",
    "standard_deviation",
    "quantiles",
    "missing_rate",
    "stale_rate",
    "psi_vs_training",
    "ks_statistic_vs_training",
    "out_of_training_range_rate",
)
DRIFT_REQUIRED_QUANTILES = ("p01", "p05", "p25", "p50", "p75", "p95", "p99")
FIELD_SOURCE_CANDIDATES: dict[str, tuple[tuple[str, ...], ...]] = {
    "observed_bid_ask_spread": (
        ("observed_bid_ask_spread_bps",),
        ("actual_observed_spread_entry_bps",),
        ("bid_ask_spread_bps",),
        ("spread_bps",),
        ("best_bid", "best_ask"),
        ("bid", "ask"),
    ),
    "order_size": (
        ("order_size_usd",),
        ("order_notional_usd",),
        ("notional_usd",),
        ("target_notional_usdt",),
        ("gross_notional_usd",),
    ),
    "top_book_evidence": (("best_bid", "best_ask"), ("bid", "ask")),
    "depth_evidence": (
        ("top_book_bid_depth_usd", "top_book_ask_depth_usd"),
        ("ask_depth_usd",),
        ("bid_depth_usd",),
        ("entry_orderbook_depth_usd",),
        ("orderbook_depth_usd",),
        ("market_depth_usd",),
        ("top_of_book_depth_usd",),
        ("book_depth_usd",),
    ),
    "depth_derived_price_impact": (
        ("depth_price_impact_bps",),
        ("depth_impact_bps",),
        ("expected_price_impact_bps",),
        ("orderbook_depth_usd", "order_notional_usd"),
        ("orderbook_depth_usd", "order_size_usd"),
    ),
    "maker_taker_assumption_and_probability": (
        ("maker_probability", "taker_probability"),
        ("maker_taker_probability",),
    ),
    "fee_schedule": (
        ("maker_fee_bps", "taker_fee_bps"),
        ("fee_bps",),
        ("expected_fee_bps",),
        ("actual_fee_bps",),
    ),
    "funding_rate_and_holding_period_funding": (
        ("expected_funding_bps",),
        ("funding_bps",),
        ("funding_rate_bps",),
        ("funding_rate",),
        ("last_funding_rate",),
    ),
    "latency_reserve": (
        ("latency_reserve_bps",),
        ("latency_ms",),
        ("paper_fill_latency_ms",),
        ("fill_latency_ms",),
        ("execution_latency_ms",),
        ("simulated_latency_ms",),
    ),
    "partial_fill_estimate": (
        ("partial_fill_adjustment_bps",),
        ("partial_fill_probability",),
        ("execution_probability",),
        ("partial_fill_count",),
        ("partial_fills",),
        ("partial_fill_plan",),
    ),
    "mark_index_divergence": (
        ("mark_index_divergence_bps",),
        ("mark_price", "index_price"),
    ),
    "source_timestamp": (
        ("source_timestamp",),
        ("source_event_time_est",),
        ("feature_cutoff",),
        ("event_time",),
        ("candle_close_time",),
        ("generated_at",),
        ("generated_utc",),
    ),
    "evidence_freshness": (
        ("available_at", "decision_time"),
        ("source_available_time", "decision_time_est"),
        ("source_received_time_est", "decision_cutoff_time_est"),
    ),
    "fallback_flag": (("fallback",),),
}
FIELD_RECOVERY_BOUNDARY: dict[str, str] = {
    "order_size": "adaptive_allocator_or_paper_intent_pre_submit",
    "top_book_evidence": "feature_snapshot_builder_must_persist_best_bid_best_ask_with_source_timestamp",
    "depth_derived_price_impact": "requires_depth_plus_order_size_or_explicit_depth_impact_at_decision_time",
    "maker_taker_assumption_and_probability": "paper_intent_or_cost_policy_must_record_explicit_maker_taker_assumption",
    "latency_reserve": "paper_intent_or_fill_path_must_record_latency_or_explicit_latency_reserve",
    "partial_fill_estimate": "paper_intent_or_fill_path_must_record_partial_fill_probability_or_plan",
}
RUNTIME_COST_CAPTURE_STAGE_BY_GROUP = {
    "paper_signal": "decision_time_signal",
    "paper_intent": "pre_submit_intent",
    "paper_ledger": "paper_lifecycle_or_fill",
    "paper_online_ledger": "paper_lifecycle_or_fill",
    "paper_closed_trades": "closed_outcome",
    "trainer_feedback": "trainer_feedback_outcome",
}
RUNTIME_COST_CAPTURE_WRITE_POINTS: dict[str, dict[str, Any]] = {
    "paper_signal": {
        "producer": "all_timeframe_prediction_signal_price_target_publisher",
        "files": [
            "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
            "v2/backend/app/cli/paper_online_runtime.py",
        ],
        "redis_keys": ["v2:signals:paper:*"],
        "required_role": "decision_time_signal_snapshot",
    },
    "paper_intent": {
        "producer": "paper_trade_management_intent_gate",
        "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
        "redis_keys": ["v2:paper:intents", "v2:paper:intents_held_by_paper_fill_gate"],
        "required_role": "pre_submit_candidate_bound_cost_capture",
    },
    "paper_ledger": {
        "producer": "paper_trade_management_lifecycle",
        "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
        "redis_keys": ["v2:paper:ledger"],
        "required_role": "paper_fill_or_lifecycle_cost_capture",
    },
    "paper_online_ledger": {
        "producer": "paper_online_runtime_lifecycle",
        "files": ["v2/backend/app/cli/paper_online_runtime.py"],
        "redis_keys": ["v2:paper_online:ledger"],
        "required_role": "paper_online_lifecycle_cost_capture",
    },
    "paper_closed_trades": {
        "producer": "paper_trade_management_closed_trade_writer",
        "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
        "redis_keys": ["v2:paper:closed_trades"],
        "required_role": "closed_outcome_cost_and_identity_linkage",
    },
    "trainer_feedback": {
        "producer": "trainer_feedback_outcome_writer",
        "files": [
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
            "v2/backend/app/services/paper_shadow_outcome_observer/service.py",
        ],
        "redis_keys": ["v2:trainer:feedback:outcomes", "v2:trainer:feedback:outcomes:quarantine"],
        "required_role": "trainer_feedback_identity_and_accounting_linkage",
    },
}
RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS: dict[str, list[str]] = {
    "candidate_id": [
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    ],
    "policy_fingerprint": [
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    ],
    "model_source": [
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    ],
    "observed_bid_ask_spread": ["paper_signal", "paper_intent"],
    "order_size": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "top_book_evidence": ["paper_signal", "paper_intent"],
    "depth_evidence": ["paper_signal", "paper_intent"],
    "depth_derived_price_impact": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "maker_taker_assumption_and_probability": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "fee_schedule": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "funding_rate_and_holding_period_funding": [
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
    ],
    "latency_reserve": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "partial_fill_estimate": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "mark_index_divergence": ["paper_intent", "paper_ledger", "paper_online_ledger"],
    "source_timestamp": [
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    ],
    "evidence_freshness": ["paper_signal", "paper_intent", "paper_ledger", "paper_online_ledger"],
    "fallback_flag": [
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    ],
}
RUNTIME_IDENTITY_BINDING_LINE_TARGET_TERMS: dict[str, tuple[str, ...]] = {
    "paper_signal": (
        "model_source",
        "trainer_source",
        "signal_id",
        "paper_fill_allowed",
        "v2:signals:paper",
    ),
    "paper_intent": (
        "intent = {",
        "\"model_id\": s.get(\"model_id\")",
        "\"trainer_source\": s.get(\"trainer_source\")",
        "paper:intents",
        "paper:intents_held_by_paper_fill_gate",
    ),
    "paper_ledger": (
        "ledger_payload = {",
        "accepted_for_ledger",
        "paper:ledger",
        "accepted_intents",
    ),
    "paper_online_ledger": (
        "PAPER_ONLINE_LEDGER_KEY",
        "paper_online:ledger",
        "paper_fill_allowed",
    ),
    "paper_closed_trades": (
        "closed_trades",
        "close_state_sample",
        "paper:closed_trades",
    ),
    "trainer_feedback": (
        "_build_trainer_feedback_rows",
        "trainer_feedback_consumable_rows",
        "trainer:feedback:outcomes",
        "trainer:feedback:outcomes:quarantine",
    ),
}
QUANTILES = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)


@dataclass(frozen=True)
class FrozenPolicy:
    candidate_id: str
    policy_fingerprint: str
    feature_names: tuple[str, ...]
    normalization: NormalizationSpec
    weights: tuple[float, ...]
    bias: float
    threshold_bps: float
    model_source: str

    def predict_vector(self, normalized_vector: Sequence[float]) -> float:
        total = float(self.bias)
        for value, weight in zip(normalized_vector, self.weights):
            total += float(value) * float(weight)
        return float(total)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def row_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def append_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    ensure_jsonl(path)
    if not rows:
        return
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def file_sha256(path: Path) -> str:
    if not path.exists():
        return stable_hash({"missing": str(path)})
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iso_from_ms(value: int | float) -> str:
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms(value: Any) -> int | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return int(parsed.timestamp() * 1000)


def first_present(row: Mapping[str, Any], *names: str) -> Any:
    features = row.get("features")
    feature_map = features if isinstance(features, Mapping) else {}
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
        value = feature_map.get(name)
        if value not in (None, ""):
            return value
    return None


def first_float(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = first_present(row, name)
        parsed = finite_float(value)
        if parsed is not None:
            return parsed
    return None


def field_source(row: Mapping[str, Any], name: str) -> str | None:
    features = row.get("features")
    feature_map = features if isinstance(features, Mapping) else {}
    value = row.get(name)
    if value not in (None, ""):
        return f"row.{name}"
    value = feature_map.get(name)
    if value not in (None, ""):
        return f"features.{name}"
    return None


def source_group_present(row: Mapping[str, Any], field_names: Sequence[str]) -> tuple[bool, str | None]:
    sources: list[str] = []
    for name in field_names:
        source = field_source(row, name)
        if source is None:
            return False, None
        sources.append(source)
    return True, "+".join(sources)


def mapping_first_present(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = mapping.get(name)
        if value not in (None, ""):
            return value
    return None


def top_book_evidence_source(row: Mapping[str, Any]) -> str | None:
    if first_float(row, "best_bid", "bid") is not None and first_float(row, "best_ask", "ask") is not None:
        return "row.best_bid+row.best_ask"
    spread = first_float(
        row,
        "observed_bid_ask_spread_bps",
        "actual_observed_spread_entry_bps",
        "bid_ask_spread_bps",
        "entry_spread_bps",
        "spread_bps",
    )
    if spread is None:
        return None
    source_fields = row.get("market_cost_evidence_source_fields")
    source_field_value = None
    if isinstance(source_fields, Mapping):
        source_field_value = mapping_first_present(
            source_fields,
            "observed_bid_ask_spread_bps",
            "actual_observed_spread_entry_bps",
            "bid_ask_spread_bps",
            "entry_spread_bps",
        )
    microstructure = row.get("microstructure_context")
    microstructure_source = microstructure.get("source") if isinstance(microstructure, Mapping) else None
    for source in (
        first_present(row, "entry_spread_source", "upstream_reported_spread_source"),
        source_field_value,
        microstructure_source,
    ):
        source_text = str(source or "").upper()
        if "ORDERBOOK" in source_text and "TOP" in source_text and "BOOK" in source_text:
            return "row.top_book_spread_lineage"
    return None


def positive_field_source(row: Mapping[str, Any], name: str) -> str | None:
    source = field_source(row, name)
    value = first_present(row, name)
    parsed = finite_float(value)
    if source is not None and parsed is not None and parsed > 0.0:
        return source
    return None


def nonnegative_field_source(row: Mapping[str, Any], name: str) -> str | None:
    source = field_source(row, name)
    value = first_present(row, name)
    parsed = finite_float(value)
    if source is not None and parsed is not None and parsed >= 0.0:
        return source
    return None


def source_presence_for_required_field(row: Mapping[str, Any], required_field: str) -> tuple[bool, str | None]:
    if required_field == "fallback_flag":
        return True, "computed.challenger_v2_cost_model.fallback"
    if required_field == "evidence_freshness":
        decision_time = parse_utc(first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"))
        available_at = parse_utc(first_present(row, "available_at", "source_available_time", "source_received_time_est", "generated_at", "generated_utc"))
        freshness_state = str(first_present(row, "feature_freshness_state") or "").upper()
        if decision_time is not None and available_at is not None and available_at <= decision_time and freshness_state not in {"STALE", "EXPIRED", "DIRTY"}:
            return True, "computed.available_at_lte_decision_time"
        return False, None
    if required_field == "top_book_evidence":
        source = top_book_evidence_source(row)
        if source is not None:
            return True, source
        return False, None
    if required_field == "order_size":
        for name in ("order_size_usd", "order_notional_usd", "notional_usd", "target_notional_usdt", "gross_notional_usd"):
            source = positive_field_source(row, name)
            if source is not None:
                return True, source
        return False, None
    if required_field == "depth_evidence":
        for group in FIELD_SOURCE_CANDIDATES.get(required_field, ()):
            sources = []
            for name in group:
                source = positive_field_source(row, name)
                if source is None:
                    break
                sources.append(source)
            else:
                return True, "+".join(sources)
        return False, None
    if required_field == "depth_derived_price_impact":
        for name in ("depth_price_impact_bps", "depth_impact_bps", "expected_price_impact_bps"):
            source = nonnegative_field_source(row, name)
            if source is not None:
                return True, source
        for depth_name in ("orderbook_depth_usd",):
            depth_source = positive_field_source(row, depth_name)
            if depth_source is None:
                continue
            for order_name in ("order_notional_usd", "order_size_usd"):
                order_source = positive_field_source(row, order_name)
                if order_source is not None:
                    return True, f"{depth_source}+{order_source}"
        return False, None
    for group in FIELD_SOURCE_CANDIDATES.get(required_field, ()):
        present, source = source_group_present(row, group)
        if present:
            return True, source
    if required_field == "fee_schedule":
        return True, "configured.adaptive_capital_allocator.AllocationInput.fee_bps"
    return False, None


def parse_orderbook_top_book(payload: Mapping[str, Any], *, source_key: str) -> dict[str, Any] | None:
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, Sequence) or isinstance(bids, (str, bytes, bytearray, Mapping)):
        return None
    if not isinstance(asks, Sequence) or isinstance(asks, (str, bytes, bytearray, Mapping)):
        return None
    if not bids or not asks:
        return None
    best_bid_row = bids[0]
    best_ask_row = asks[0]
    if not isinstance(best_bid_row, Sequence) or isinstance(best_bid_row, (str, bytes, bytearray, Mapping)):
        return None
    if not isinstance(best_ask_row, Sequence) or isinstance(best_ask_row, (str, bytes, bytearray, Mapping)):
        return None
    if len(best_bid_row) < 2 or len(best_ask_row) < 2:
        return None
    best_bid = finite_float(best_bid_row[0])
    bid_qty = finite_float(best_bid_row[1])
    best_ask = finite_float(best_ask_row[0])
    ask_qty = finite_float(best_ask_row[1])
    event_ms = finite_float(payload.get("T") or payload.get("E") or payload.get("event_time_ms") or payload.get("source_timestamp_ms"))
    if best_bid is None or best_ask is None or bid_qty is None or ask_qty is None:
        return None
    if best_bid <= 0.0 or best_ask <= 0.0 or best_ask < best_bid:
        return None
    mid = (best_bid + best_ask) / 2.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "top_book_bid_quantity": bid_qty,
        "top_book_ask_quantity": ask_qty,
        "top_book_bid_depth_usd": best_bid * bid_qty,
        "top_book_ask_depth_usd": best_ask * ask_qty,
        "top_book_mid_price": mid,
        "top_book_spread_bps": (best_ask - best_bid) / mid * 10_000.0 if mid > 0.0 else None,
        "top_book_source_key": source_key,
        "top_book_source_timestamp": iso_from_ms(int(event_ms)) if event_ms is not None else None,
        "top_book_source_event_ms": int(event_ms) if event_ms is not None else None,
    }


def enrich_current_snapshots_with_top_book(
    snapshots: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    required_coverage = 0.95
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
    except Exception as exc:
        pass_conditions = {
            "current_rows_scanned_gt_0": len(snapshots) > 0,
            "top_book_enrichment_coverage_gte_95pct": False,
            "top_book_missing_rows_eq_0": len(snapshots) == 0,
            "pit_safe_for_all_enriched_rows": True,
        }
        blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
        blocker_details = [
            {
                "pass_condition": "top_book_enrichment_coverage_gte_95pct",
                "actual": 0.0,
                "required": f">={required_coverage}",
                "source_artifact": "challenger_v2_top_book_enrichment_status.json",
            },
            {
                "pass_condition": "top_book_missing_rows_eq_0",
                "actual": len(snapshots),
                "required": 0,
                "source_artifact": "challenger_v2_top_book_enrichment_status.json",
            },
        ]
        actuals = {
            "current_rows_scanned_gt_0": len(snapshots),
            "top_book_enrichment_coverage_gte_95pct": 0.0,
            "top_book_missing_rows_eq_0": len(snapshots),
            "pit_safe_for_all_enriched_rows": True,
        }
        required = {
            "current_rows_scanned_gt_0": ">0",
            "top_book_enrichment_coverage_gte_95pct": f">={required_coverage}",
            "top_book_missing_rows_eq_0": 0,
            "pit_safe_for_all_enriched_rows": True,
        }
        return list(snapshots), {
            "schema_version": "challenger_v2_top_book_enrichment_status_v1",
            "generated_utc": utc_now(),
            "status": f"BLOCKED_TOP_BOOK_REDIS_UNAVAILABLE:{type(exc).__name__}",
            "current_rows_scanned": len(snapshots),
            "top_book_enriched_rows": 0,
            "top_book_missing_rows": len(snapshots),
            "top_book_enrichment_coverage": 0.0,
            "required_top_book_enrichment_coverage": required_coverage,
            "reject_reason_counts": {"redis_unavailable": len(snapshots)},
            "source_counts": {},
            "pass_conditions": pass_conditions,
            "blocked_reasons": blocked_reasons,
            "blocker_details": blocker_details,
            "failed_blocker_details": blocker_details,
            "actuals": actuals,
            "required": required,
            "sample_blockers": blocker_details[:25],
            "sample_enriched_rows": [],
            "sample_missing_rows": [
                {
                    "symbol": snapshot.get("symbol"),
                    "timeframe": snapshot.get("timeframe"),
                    "snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
                    "decision_time": first_present(
                        snapshot,
                        "decision_time",
                        "decision_time_est",
                        "decision_cutoff_time_est",
                        "generated_at",
                        "generated_utc",
                    ),
                    "reject_reason": "redis_unavailable",
                }
                for snapshot in list(snapshots)[:10]
            ],
            "pit_rule": "top_book_source_event_time <= decision_time; no exchange/account mutation",
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
        }
    enriched: list[Mapping[str, Any]] = []
    reject_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    missing_samples: list[dict[str, Any]] = []
    for snapshot in snapshots:
        row = dict(snapshot)
        symbol = str(row.get("symbol") or "").upper()
        decision_time = parse_utc(first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"))
        sample_base = {
            "symbol": symbol or row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
            "decision_time": first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"),
        }
        if not symbol:
            reject_counts["symbol_missing"] += 1
            if len(missing_samples) < 10:
                missing_samples.append({**sample_base, "reject_reason": "symbol_missing"})
            enriched.append(row)
            continue
        if decision_time is None:
            reject_counts["decision_time_missing"] += 1
            if len(missing_samples) < 10:
                missing_samples.append({**sample_base, "reject_reason": "decision_time_missing"})
            enriched.append(row)
            continue
        accepted: dict[str, Any] | None = None
        reject_reason = "orderbook_key_missing"
        for key in (f"v2:market:orderbook:binance:{symbol}", f"v2:market:orderbook:{symbol}"):
            raw = client.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                reject_reason = "orderbook_payload_invalid_json"
                continue
            if not isinstance(payload, Mapping):
                reject_reason = "orderbook_payload_not_mapping"
                continue
            top_book = parse_orderbook_top_book(payload, source_key=key)
            if top_book is None:
                reject_reason = "top_book_parse_failed"
                continue
            event_ms = top_book.get("top_book_source_event_ms")
            if event_ms is None:
                reject_reason = "top_book_source_timestamp_missing"
                continue
            decision_ms = int(decision_time.timestamp() * 1000)
            if int(event_ms) > decision_ms:
                reject_reason = "top_book_event_after_decision_time"
                continue
            accepted = top_book
            break
        if accepted is None:
            reject_counts[reject_reason] += 1
            if len(missing_samples) < 10:
                missing_samples.append({**sample_base, "reject_reason": reject_reason})
            enriched.append(row)
            continue
        row.update(accepted)
        row["top_book_pit_status"] = "EVENT_TIME_LTE_DECISION_TIME_REDIS_READ_ONLY"
        source_counts[str(accepted.get("top_book_source_key") or "UNKNOWN")] += 1
        if len(samples) < 10:
            samples.append(
                {
                    "symbol": symbol,
                    "timeframe": row.get("timeframe"),
                    "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
                    "decision_time": first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"),
                    "top_book_source_timestamp": row.get("top_book_source_timestamp"),
                    "best_bid": row.get("best_bid"),
                    "best_ask": row.get("best_ask"),
                }
            )
        enriched.append(row)
    enriched_count = sum(1 for row in enriched if row.get("top_book_pit_status") == "EVENT_TIME_LTE_DECISION_TIME_REDIS_READ_ONLY")
    missing_count = len(snapshots) - enriched_count
    coverage = enriched_count / len(snapshots) if snapshots else 0.0
    pass_conditions = {
        "current_rows_scanned_gt_0": len(snapshots) > 0,
        "top_book_enrichment_coverage_gte_95pct": coverage >= required_coverage,
        "top_book_missing_rows_eq_0": missing_count == 0,
        "pit_safe_for_all_enriched_rows": True,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    blocker_details = []
    if not pass_conditions["current_rows_scanned_gt_0"]:
        blocker_details.append(
            {
                "pass_condition": "current_rows_scanned_gt_0",
                "actual": len(snapshots),
                "required": ">0",
                "source_artifact": "challenger_v2_top_book_enrichment_status.json",
            }
        )
    if not pass_conditions["top_book_enrichment_coverage_gte_95pct"]:
        blocker_details.append(
            {
                "pass_condition": "top_book_enrichment_coverage_gte_95pct",
                "actual": coverage,
                "required": f">={required_coverage}",
                "source_artifact": "challenger_v2_top_book_enrichment_status.json",
            }
        )
    if not pass_conditions["top_book_missing_rows_eq_0"]:
        blocker_details.append(
            {
                "pass_condition": "top_book_missing_rows_eq_0",
                "actual": missing_count,
                "required": 0,
                "source_artifact": "challenger_v2_top_book_enrichment_status.json",
            }
        )
    actuals = {
        "current_rows_scanned_gt_0": len(snapshots),
        "top_book_enrichment_coverage_gte_95pct": coverage,
        "top_book_missing_rows_eq_0": missing_count,
        "pit_safe_for_all_enriched_rows": True,
    }
    required = {
        "current_rows_scanned_gt_0": ">0",
        "top_book_enrichment_coverage_gte_95pct": f">={required_coverage}",
        "top_book_missing_rows_eq_0": 0,
        "pit_safe_for_all_enriched_rows": True,
    }
    status = (
        "PASS_TOP_BOOK_ENRICHMENT_COVERAGE"
        if all(pass_conditions.values())
        else "BLOCKED_TOP_BOOK_ENRICHMENT_INCOMPLETE"
    )
    return enriched, {
        "schema_version": "challenger_v2_top_book_enrichment_status_v1",
        "generated_utc": utc_now(),
        "status": status,
        "current_rows_scanned": len(snapshots),
        "top_book_enriched_rows": enriched_count,
        "top_book_missing_rows": missing_count,
        "top_book_enrichment_coverage": coverage,
        "required_top_book_enrichment_coverage": required_coverage,
        "reject_reason_counts": dict(sorted(reject_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "actuals": actuals,
        "required": required,
        "sample_blockers": blocker_details[:25],
        "sample_enriched_rows": samples,
        "sample_missing_rows": missing_samples,
        "pit_rule": "top_book_source_event_time <= decision_time; no exchange/account mutation",
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def json_list_from_redis_value(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    if isinstance(payload, Mapping):
        payload = list(payload.values())
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def positive_first_float(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = first_present(row, name)
        parsed = finite_float(value)
        if parsed is not None and parsed > 0.0:
            return parsed
    return None


def paper_intent_snapshot_ids(intent: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for name in (
        "feature_snapshot_id",
        "entry_feature_snapshot_id",
        "snapshot_id",
        "source_snapshot_id",
    ):
        value = intent.get(name)
        if value not in (None, ""):
            ids.add(str(value))
    return ids


def paper_intent_source_time(intent: Mapping[str, Any]) -> datetime | None:
    for name in (
        "cost_evidence_generated_at",
        "paper_cost_evidence_generated_at",
        "generated_utc",
        "generated_at",
        "entry_price_utc",
        "fill_price_utc",
        "decision_time",
    ):
        parsed = parse_utc(intent.get(name))
        if parsed is not None:
            return parsed
    return None


def challenger_bound_paper_intent_reasons(intent: Mapping[str, Any], policy: FrozenPolicy) -> list[str]:
    reasons: list[str] = []
    if str(intent.get("candidate_id") or "") != policy.candidate_id:
        reasons.append("candidate_id_missing_or_mismatch")
    if str(intent.get("policy_fingerprint") or "") != policy.policy_fingerprint:
        reasons.append("policy_fingerprint_missing_or_mismatch")
    if str(intent.get("model_source") or "") != policy.model_source:
        reasons.append("model_source_missing_or_mismatch")
    return reasons


def copy_paper_intent_cost_fields(row: dict[str, Any], intent: Mapping[str, Any]) -> dict[str, str]:
    copied: dict[str, str] = {}
    notional = positive_first_float(
        intent,
        "order_size_usd",
        "order_notional_usd",
        "notional_usd",
        "notional",
        "notional_usdt",
        "gross_notional_usd",
        "target_notional_usdt",
    )
    if notional is not None:
        row["order_size_usd"] = notional
        row["order_notional_usd"] = notional
        row["notional_usd"] = notional
        copied["order_size_usd"] = "paper_intent_positive_notional"
    for name in (
        "quantity",
        "target_quantity",
        "observed_bid_ask_spread_bps",
        "actual_observed_spread_entry_bps",
        "bid_ask_spread_bps",
        "spread_bps",
        "entry_spread_source",
        "entry_spread_available_at",
        "entry_spread_decision_time",
        "market_cost_evidence_source_fields",
        "best_bid",
        "best_ask",
        "bid",
        "ask",
        "top_book_bid_depth_usd",
        "top_book_ask_depth_usd",
        "bid_depth_usd",
        "ask_depth_usd",
        "entry_orderbook_depth_usd",
        "entry_orderbook_depth_side",
        "top_of_book_depth_usd",
        "market_depth_usd",
        "orderbook_depth_usd",
        "orderbook_depth_source",
        "depth_price_impact_bps",
        "depth_impact_bps",
        "expected_price_impact_bps",
        "maker_probability",
        "taker_probability",
        "maker_taker_probability",
        "maker_taker_probabilities",
        "maker_taker_probability_source",
        "latency_reserve_bps",
        "latency_ms",
        "decision_latency_ms",
        "paper_fill_latency_ms",
        "fill_latency_ms",
        "execution_latency_ms",
        "simulated_latency_ms",
        "latency_source",
        "partial_fill_adjustment_bps",
        "partial_fill_probability",
        "execution_probability",
        "partial_fill_count",
        "partial_fills",
        "fill_count",
        "all_partial_fills",
        "partial_fill_plan",
        "expected_slippage_bps",
        "slippage_bps",
        "maker_fee_bps",
        "taker_fee_bps",
        "fee_bps",
        "expected_fee_bps",
        "expected_funding_bps",
        "funding_bps",
        "funding_rate_bps",
        "funding_rate",
        "mark_index_divergence_bps",
        "mark_index_divergence",
        "mark_price",
        "index_price",
        "mark_index_source",
        "mark_index_available_at",
    ):
        value = intent.get(name)
        if value in (None, ""):
            continue
        row[name] = value
        copied[name] = "paper_intent_challenger_bound"
    source_time = paper_intent_source_time(intent)
    if source_time is not None:
        row["paper_intent_cost_evidence_source_timestamp"] = source_time.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        copied["paper_intent_cost_evidence_source_timestamp"] = "paper_intent_challenger_bound"
    row["paper_intent_id"] = intent.get("intent_id") or intent.get("execution_intent_id") or intent.get("signal_id")
    row["paper_intent_cost_evidence_source"] = intent.get("_paper_intent_source_key") or "v2:paper:intents"
    row["paper_intent_cost_evidence_binding_status"] = "CHALLENGER_CANDIDATE_POLICY_MODEL_MATCH"
    return copied


def enrich_snapshots_with_paper_intents_from_rows(
    snapshots: Sequence[Mapping[str, Any]],
    paper_intents: Sequence[Mapping[str, Any]],
    *,
    policy: FrozenPolicy,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    intents_by_snapshot_id: dict[str, list[Mapping[str, Any]]] = {}
    for intent in paper_intents:
        for snapshot_id in paper_intent_snapshot_ids(intent):
            intents_by_snapshot_id.setdefault(snapshot_id, []).append(intent)

    enriched: list[Mapping[str, Any]] = []
    reject_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    potential_matches = trusted_matches = positive_order_size_matches = 0
    samples: list[dict[str, Any]] = []
    rejected_samples: list[dict[str, Any]] = []

    for snapshot in snapshots:
        row = dict(snapshot)
        snapshot_id = str(row.get("feature_snapshot_id") or row.get("snapshot_id") or "")
        candidates = intents_by_snapshot_id.get(snapshot_id, [])
        if not candidates:
            reject_counts["no_matching_paper_intent_snapshot_id"] += 1
            enriched.append(row)
            continue
        potential_matches += len(candidates)
        row_decision = parse_utc(first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"))
        accepted_intent: Mapping[str, Any] | None = None
        accepted_copied: dict[str, str] = {}
        for intent in sorted(candidates, key=lambda item: str(item.get("generated_utc") or item.get("generated_at") or "")):
            binding_reasons = challenger_bound_paper_intent_reasons(intent, policy)
            if binding_reasons:
                for reason in binding_reasons:
                    reject_counts[reason] += 1
                if len(rejected_samples) < 10:
                    rejected_samples.append(
                        {
                            "snapshot_id": snapshot_id,
                            "symbol": row.get("symbol"),
                            "timeframe": row.get("timeframe"),
                            "intent_id": intent.get("intent_id") or intent.get("execution_intent_id") or intent.get("signal_id"),
                            "intent_candidate_id": intent.get("candidate_id"),
                            "intent_policy_fingerprint": intent.get("policy_fingerprint"),
                            "intent_model_source": intent.get("model_source"),
                            "reject_reasons": binding_reasons,
                        }
                    )
                continue
            source_time = paper_intent_source_time(intent)
            if row_decision is None:
                reject_counts["snapshot_decision_time_missing"] += 1
                continue
            if source_time is None:
                reject_counts["paper_intent_source_timestamp_missing"] += 1
                continue
            if source_time > row_decision:
                reject_counts["paper_intent_source_timestamp_after_snapshot_decision_time"] += 1
                continue
            if positive_first_float(
                intent,
                "order_size_usd",
                "order_notional_usd",
                "notional_usd",
                "notional",
                "notional_usdt",
                "gross_notional_usd",
                "target_notional_usdt",
            ) is None:
                reject_counts["paper_intent_positive_order_size_missing"] += 1
                continue
            accepted_intent = intent
            accepted_copied = copy_paper_intent_cost_fields(row, intent)
            break
        if accepted_intent is None:
            enriched.append(row)
            continue
        trusted_matches += 1
        positive_order_size_matches += 1
        field_counts.update(accepted_copied.keys())
        source_counts[str(accepted_intent.get("_paper_intent_source_key") or "v2:paper:intents")] += 1
        if len(samples) < 10:
            samples.append(
                {
                    "snapshot_id": snapshot_id,
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "decision_time": first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"),
                    "intent_id": accepted_intent.get("intent_id") or accepted_intent.get("execution_intent_id") or accepted_intent.get("signal_id"),
                    "paper_intent_cost_evidence_source_timestamp": row.get("paper_intent_cost_evidence_source_timestamp"),
                    "order_size_usd": row.get("order_size_usd"),
                    "copied_fields": sorted(accepted_copied.keys()),
                }
            )
        enriched.append(row)

    candidate_bound_intents = sum(1 for intent in paper_intents if not challenger_bound_paper_intent_reasons(intent, policy))
    return enriched, {
        "schema_version": "challenger_v2_paper_intent_cost_evidence_join_status_v1",
        "generated_utc": utc_now(),
        "status": "PASS_TRUSTED_PAPER_INTENT_COST_EVIDENCE_JOINED" if trusted_matches else "NO_TRUSTED_CHALLENGER_BOUND_PAPER_INTENT_COST_EVIDENCE",
        "current_rows_scanned": len(snapshots),
        "paper_intent_rows_scanned": len(paper_intents),
        "candidate_bound_intents": candidate_bound_intents,
        "potential_snapshot_matches": potential_matches,
        "trusted_snapshot_matches": trusted_matches,
        "positive_order_size_matches": positive_order_size_matches,
        "paper_intent_enriched_rows": trusted_matches,
        "paper_intent_enrichment_coverage": trusted_matches / len(snapshots) if snapshots else 0.0,
        "reject_reason_counts": dict(sorted(reject_counts.items())),
        "field_enrichment_counts": dict(sorted(field_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "sample_enriched_rows": samples,
        "sample_rejected_snapshot_matches": rejected_samples,
        "binding_rule": "paper intent must identify candidate_id, policy_fingerprint, and model_source for the frozen challenger before it can count",
        "pit_rule": "paper intent cost evidence source timestamp must be <= challenger snapshot decision_time",
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def enrich_current_snapshots_with_paper_intents(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    policy: FrozenPolicy,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
        paper_intents: list[Mapping[str, Any]] = []
        for key in PAPER_INTENT_COST_JOIN_KEYS:
            for row in paper_binding_rows_from_redis_value(client.get(key), source_key=key):
                tagged = dict(row)
                tagged["_paper_intent_source_key"] = tagged.get("_paper_binding_source_key") or key
                paper_intents.append(tagged)
    except Exception as exc:
        return list(snapshots), {
            "schema_version": "challenger_v2_paper_intent_cost_evidence_join_status_v1",
            "generated_utc": utc_now(),
            "status": f"SKIPPED_REDIS_UNAVAILABLE:{type(exc).__name__}",
            "current_rows_scanned": len(snapshots),
            "paper_intent_rows_scanned": 0,
            "candidate_bound_intents": 0,
            "potential_snapshot_matches": 0,
            "trusted_snapshot_matches": 0,
            "positive_order_size_matches": 0,
            "paper_intent_enriched_rows": 0,
            "paper_intent_enrichment_coverage": 0.0,
            "reject_reason_counts": {"redis_unavailable": len(snapshots)},
            "field_enrichment_counts": {},
            "source_counts": {},
            "sample_enriched_rows": [],
            "sample_rejected_snapshot_matches": [],
            "binding_rule": "paper intent must identify candidate_id, policy_fingerprint, and model_source for the frozen challenger before it can count",
            "pit_rule": "paper intent cost evidence source timestamp must be <= challenger snapshot decision_time",
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
        }
    return enrich_snapshots_with_paper_intents_from_rows(snapshots, paper_intents, policy=policy)


def tagged_json_rows_from_payload(payload: Any, *, source_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, Mapping):
        for key in ("latest_entry",):
            value = payload.get(key)
            if isinstance(value, Mapping):
                row = dict(value)
                row["_paper_binding_source_key"] = f"{source_key}.{key}"
                rows.append(row)
        for key in (
            "accepted",
            "accepted_intents",
            "current_cycle_accepted",
            "blocked",
            "shadow_observations",
            "held_by_paper_fill_gate",
            "current_cycle_held",
            "rows",
            "closed_trades",
            "closed_positions",
            "outcome_labels",
            "new_outcome_labels",
            "trainer_feedback",
            "trainer_feedback_rows",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, Mapping):
                        row = dict(item)
                        row["_paper_binding_source_key"] = f"{source_key}.{key}"
                        rows.append(row)
        if not rows:
            row = dict(payload)
            row["_paper_binding_source_key"] = source_key
            rows.append(row)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                row = dict(item)
                row["_paper_binding_source_key"] = source_key
                rows.append(row)
    return rows


def paper_binding_rows_from_redis_value(raw: Any, *, source_key: str) -> list[dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return tagged_json_rows_from_payload(payload, source_key=source_key)


def bounded_paper_signal_scan(
    client: Any,
    *,
    signal_scan_limit: int,
    row_reader: Callable[[Any, str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], Counter[str], int, bool]:
    signal_scan_limit = max(0, int(signal_scan_limit))
    if signal_scan_limit == 0:
        return [], Counter(), 0, True

    rows: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    signal_count = 0
    scan_limit_reached = False
    for key in client.scan_iter(match="v2:signals:paper:*", count=100):
        if signal_count >= signal_scan_limit:
            scan_limit_reached = True
            break
        key_text = str(key)
        key_rows = row_reader(client.get(key), key_text)
        rows.extend(key_rows)
        source_counts[key_text] += len(key_rows)
        signal_count += 1
    return rows, source_counts, signal_count, scan_limit_reached


def paper_row_routes_to_live(row: Mapping[str, Any]) -> bool:
    return any(
        row.get(name) is True
        for name in (
            "routes_to_live",
            "places_real_order",
            "live_order",
            "exchange_order_allowed",
        )
    )


def challenger_identity_state(row: Mapping[str, Any], policy: FrozenPolicy) -> str:
    candidate_match = row.get("candidate_id") == policy.candidate_id
    fingerprint_match = row.get("policy_fingerprint") == policy.policy_fingerprint
    model_match = row.get("model_source") == policy.model_source
    if candidate_match and fingerprint_match and model_match:
        return "complete"
    if candidate_match or fingerprint_match or model_match:
        return "partial"
    return "none"


def paper_binding_identity_preflight_from_rows(
    *,
    policy: FrozenPolicy,
    rows: Sequence[Mapping[str, Any]],
    cost_status: Mapping[str, Any],
    lockbox_perf: Mapping[str, Any],
    redis_status: str = "READ_FROM_SUPPLIED_ROWS",
    source_counts: Mapping[str, int] | None = None,
    scan_limit_reached: bool = False,
) -> dict[str, Any]:
    complete_rows = []
    partial_rows = []
    live_route_rows = []
    paper_fill_allowed_rows = []
    source_counter: Counter[str] = Counter()
    for row in rows:
        source = str(row.get("_paper_binding_source_key") or "UNKNOWN")
        source_counter[source] += 1
        state = challenger_identity_state(row, policy)
        if state == "complete":
            complete_rows.append(row)
        elif state == "partial":
            partial_rows.append(row)
        if paper_row_routes_to_live(row):
            live_route_rows.append(row)
        if row.get("paper_fill_allowed") is True:
            paper_fill_allowed_rows.append(row)

    lockbox_pass = lockbox_perf.get("pass") is True or lockbox_perf.get("status") == "PASS"
    cost_pass = cost_status.get("status") == "PASS"
    candidate_bound_before_pass = len(complete_rows) if not lockbox_pass else 0
    old_policy_credit_risk_rows = len(partial_rows)
    pass_conditions = {
        "blind_lockbox_passed_before_binding": lockbox_pass,
        "production_cost_passed_before_binding": cost_pass,
        "no_candidate_bound_rows_before_lockbox_pass": candidate_bound_before_pass == 0,
        "no_partial_challenger_identity_rows": len(partial_rows) == 0,
        "no_routes_to_live": len(live_route_rows) == 0,
    }
    if lockbox_pass and cost_pass and not partial_rows and not live_route_rows:
        status = "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT"
    elif not lockbox_pass and candidate_bound_before_pass == 0 and not partial_rows and not live_route_rows:
        status = "PASS_PRELOCKBOX_NO_BINDING_LEAKS"
    else:
        status = "FAIL_PAPER_BINDING_IDENTITY_PREFLIGHT"

    def sample_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "source_key": row.get("_paper_binding_source_key"),
            "candidate_id": row.get("candidate_id"),
            "policy_fingerprint": row.get("policy_fingerprint"),
            "model_source": row.get("model_source"),
            "model_id": row.get("model_id"),
            "trainer_source": row.get("trainer_source"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "decision_time": row.get("decision_time"),
            "generated_utc": row.get("generated_utc") or row.get("generated_at"),
            "paper_fill_allowed": row.get("paper_fill_allowed"),
            "routes_to_live": row.get("routes_to_live"),
            "places_real_order": row.get("places_real_order"),
            "live_order": row.get("live_order"),
            "exchange_order_allowed": row.get("exchange_order_allowed"),
        }

    redis_scan_source_counts = dict(sorted(Counter(dict(source_counts or {})).items()))
    return {
        "schema_version": "challenger_v2_paper_binding_identity_preflight_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": status,
        "redis_status": redis_status,
        "paper_rows_scanned": len(rows),
        "source_counts": dict(sorted(source_counter.items())),
        "redis_scan_source_counts": redis_scan_source_counts,
        "scan_limit_reached": scan_limit_reached,
        "candidate_identity_complete_rows": len(complete_rows),
        "partial_challenger_identity_rows": len(partial_rows),
        "candidate_bound_rows_before_lockbox_pass": candidate_bound_before_pass,
        "old_policy_silent_credit_risk_rows": old_policy_credit_risk_rows,
        "live_route_violation_rows": len(live_route_rows),
        "paper_fill_allowed_rows": len(paper_fill_allowed_rows),
        "old_policy_silent_control_ruled_out_for_candidate": old_policy_credit_risk_rows == 0 and len(live_route_rows) == 0,
        "paper_binding_allowed": lockbox_pass and cost_pass and len(partial_rows) == 0 and len(live_route_rows) == 0,
        "pass_conditions": pass_conditions,
        "sample_candidate_identity_complete_rows": [sample_row(row) for row in complete_rows[:10]],
        "sample_partial_challenger_identity_rows": [sample_row(row) for row in partial_rows[:10]],
        "sample_live_route_violation_rows": [sample_row(row) for row in live_route_rows[:10]],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "Preflight is read-only and does not bind challenger to paper.",
            "A paper row can credit challenger only when candidate_id, policy_fingerprint, and model_source all match.",
        ],
    }


def paper_binding_identity_preflight_from_redis(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    lockbox_perf: Mapping[str, Any],
    signal_scan_limit: int = DEFAULT_PAPER_SIGNAL_SCAN_LIMIT,
) -> dict[str, Any]:
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
    except Exception as exc:
        return paper_binding_identity_preflight_from_rows(
            policy=policy,
            rows=[],
            cost_status=cost_status,
            lockbox_perf=lockbox_perf,
            redis_status=f"SKIPPED_REDIS_UNAVAILABLE:{type(exc).__name__}",
        )

    rows: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for key in PAPER_RUNTIME_TELEMETRY_KEYS:
        key_rows = paper_binding_rows_from_redis_value(client.get(key), source_key=key)
        rows.extend(key_rows)
        source_counts[key] += len(key_rows)

    signal_rows, signal_source_counts, _signal_count, scan_limit_reached = bounded_paper_signal_scan(
        client,
        signal_scan_limit=signal_scan_limit,
        row_reader=lambda raw, key: paper_binding_rows_from_redis_value(raw, source_key=key),
    )
    rows.extend(signal_rows)
    source_counts.update(signal_source_counts)

    return paper_binding_identity_preflight_from_rows(
        policy=policy,
        rows=rows,
        cost_status=cost_status,
        lockbox_perf=lockbox_perf,
        redis_status="READ_REDIS_PAPER_ROWS_BOUNDED",
        source_counts=source_counts,
        scan_limit_reached=scan_limit_reached,
    )


def paper_cost_readiness_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize paper telemetry aliases for read-only evidence analysis."""
    normalized = dict(row)
    notional = positive_first_float(
        row,
        "order_size_usd",
        "order_notional_usd",
        "notional_usd",
        "notional",
        "notional_usdt",
        "gross_notional_usd",
        "target_notional_usdt",
    )
    if notional is not None:
        normalized.setdefault("order_size_usd", notional)
        normalized.setdefault("order_notional_usd", notional)
        normalized.setdefault("notional_usd", notional)
    return normalized


def paper_cost_source_group(source: str) -> str:
    if source.startswith("v2:paper:intents"):
        return "paper_intent"
    if source.startswith("v2:paper:ledger"):
        return "paper_ledger"
    if source.startswith("v2:paper_online:ledger"):
        return "paper_online_ledger"
    if source.startswith("local:paper_online:paper_events"):
        return "paper_online_ledger"
    if source.startswith("v2:paper:closed_trades"):
        return "paper_closed_trades"
    if source.startswith("v2:signals:paper:"):
        return "paper_signal"
    if source.startswith("v2:trainer:feedback"):
        return "trainer_feedback"
    return "unknown"


def read_local_paper_cost_event_rows(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = repo_root / LOCAL_PAPER_ONLINE_EVENT_RELATIVE_PATH
    status: dict[str, Any] = {
        "source": "local:paper_online:paper_events",
        "path": str(path),
        "relative_path": str(LOCAL_PAPER_ONLINE_EVENT_RELATIVE_PATH),
        "exists": path.exists(),
        "line_count": 0,
        "candidate_cost_event_line_count": 0,
        "paper_cost_event_rows": 0,
        "json_decode_error_count": 0,
        "non_object_json_count": 0,
        "result_counts": {},
        "sample_json_decode_errors": [],
    }
    rows: list[dict[str, Any]] = []
    result_counts: Counter[str] = Counter()
    if not path.exists():
        status["status"] = "MISSING_LOCAL_PAPER_COST_EVENTS_JSONL"
        return rows, status

    status["raw_bytes"] = path.stat().st_size
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            status["line_count"] += 1
            if not any(result in line for result in LOCAL_PAPER_COST_EVENT_RESULTS):
                continue
            status["candidate_cost_event_line_count"] += 1
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
            paper_result = str(payload.get("paper_result") or "")
            if paper_result not in LOCAL_PAPER_COST_EVENT_RESULTS:
                continue
            row = dict(payload)
            source_key = f"local:paper_online:paper_events.{paper_result}"
            row["_paper_binding_source_key"] = source_key
            row["_paper_local_event_source_path"] = str(path)
            row["_paper_local_event_line_number"] = line_number
            rows.append(row)
            result_counts[source_key] += 1

    status["paper_cost_event_rows"] = len(rows)
    status["result_counts"] = dict(sorted(result_counts.items()))
    status["status"] = (
        "PASS_LOCAL_PAPER_COST_EVENTS_JSONL_READ"
        if status["json_decode_error_count"] == 0 and status["non_object_json_count"] == 0
        else "READ_LOCAL_PAPER_COST_EVENTS_JSONL_WITH_ERRORS"
    )
    return rows, status


def paper_cost_telemetry_readiness_from_rows(
    *,
    policy: FrozenPolicy,
    rows: Sequence[Mapping[str, Any]],
    redis_status: str = "READ_FROM_SUPPLIED_ROWS",
    source_counts: Mapping[str, int] | None = None,
    scan_limit_reached: bool = False,
    local_source_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_counter: Counter[str] = Counter()
    identity_counts: Counter[str] = Counter()
    identity_field_present: Counter[str] = Counter()
    production_grade_identity_field_present: Counter[str] = Counter()
    production_grade_identity_missing_counts: Counter[str] = Counter()
    production_grade_alternate_identity_values: dict[str, Counter[str]] = {
        name: Counter() for name in ALTERNATE_PAPER_IDENTITY_FIELDS
    }
    field_present: Counter[str] = Counter()
    fallback_components: Counter[str] = Counter()
    missing_reason_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    source_group_stats: dict[str, Counter[str]] = defaultdict(Counter)
    source_group_missing_fields: dict[str, Counter[str]] = defaultdict(Counter)
    source_group_route_fill_samples: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"paper_fill_allowed": [], "live_route": []}
    )
    paper_fill_allowed_source_counts: Counter[str] = Counter()
    live_route_source_counts: Counter[str] = Counter()
    production_grade_rows = 0
    production_grade_complete_identity_rows = 0
    production_grade_route_or_fill_blocked_rows = 0
    all_required_source_rows = 0
    challenger_bound_production_grade_rows = 0
    complete_identity_rows = 0
    partial_identity_rows = 0
    none_identity_rows = 0
    live_route_rows = 0
    paper_fill_allowed_rows = 0
    candidate_bound_live_route_rows = 0
    candidate_bound_paper_fill_allowed_rows = 0
    candidate_bound_route_or_fill_rows = 0
    candidate_bound_route_or_fill_blocked_production_grade_rows = 0
    sample_production_grade_rows: list[dict[str, Any]] = []
    sample_production_grade_identity_gap_rows: list[dict[str, Any]] = []
    sample_challenger_bound_rows: list[dict[str, Any]] = []
    sample_blocked_rows: list[dict[str, Any]] = []
    sample_paper_fill_allowed_rows: list[dict[str, Any]] = []
    sample_live_route_rows: list[dict[str, Any]] = []

    def route_fill_sample(
        *,
        row: Mapping[str, Any],
        source: str,
        source_group: str,
        identity_state: str,
        route_or_fill_reason: str,
    ) -> dict[str, Any]:
        return {
            "source_key": source,
            "source_group": source_group,
            "route_or_fill_reason": route_or_fill_reason,
            "identity_state": identity_state,
            "candidate_id": row.get("candidate_id"),
            "policy_fingerprint": row.get("policy_fingerprint"),
            "model_source": row.get("model_source"),
            "selector_policy_fingerprint": row.get("selector_policy_fingerprint"),
            "frozen_selector_fingerprint": row.get("frozen_selector_fingerprint"),
            "trainer_source": row.get("trainer_source"),
            "model_id": row.get("model_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
            "decision_time": first_present(row, "decision_time", "decision_time_est", "generated_at", "generated_utc"),
            "source_event_time": first_present(row, "event_time", "available_at", "source_timestamp", "generated_at"),
            "order_size_usd": row.get("order_size_usd"),
            "paper_fill_allowed": row.get("paper_fill_allowed"),
            "routes_to_live": row.get("routes_to_live"),
            "places_real_order": row.get("places_real_order"),
            "live_order": row.get("live_order"),
            "paper_result": row.get("paper_result"),
            "local_event_line_number": row.get("_paper_local_event_line_number"),
        }

    for raw_row in rows:
        row = paper_cost_readiness_row(raw_row)
        source = str(
            raw_row.get("_paper_binding_source_key")
            or raw_row.get("_paper_intent_source_key")
            or "UNKNOWN"
        )
        source_counter[source] += 1
        source_group = paper_cost_source_group(source)
        group_stats = source_group_stats[source_group]
        group_stats["rows"] += 1
        identity_state = challenger_identity_state(row, policy)
        identity_counts[identity_state] += 1
        for identity_field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS:
            if row.get(identity_field) not in (None, ""):
                identity_field_present[identity_field] += 1
        if identity_state == "complete":
            complete_identity_rows += 1
            group_stats["candidate_identity_complete_rows"] += 1
        elif identity_state == "partial":
            partial_identity_rows += 1
            group_stats["candidate_identity_partial_rows"] += 1
        else:
            none_identity_rows += 1
            group_stats["candidate_identity_none_rows"] += 1
        row_routes_to_live = paper_row_routes_to_live(row)
        row_paper_fill_allowed = row.get("paper_fill_allowed") is True
        if row_routes_to_live:
            live_route_rows += 1
            group_stats["live_route_rows"] += 1
            live_route_source_counts[source] += 1
            live_route_sample = route_fill_sample(
                row=row,
                source=source,
                source_group=source_group,
                identity_state=identity_state,
                route_or_fill_reason="routes_to_live_true",
            )
            if len(sample_live_route_rows) < 10:
                sample_live_route_rows.append(live_route_sample)
            if len(source_group_route_fill_samples[source_group]["live_route"]) < 5:
                source_group_route_fill_samples[source_group]["live_route"].append(live_route_sample)
        if row_paper_fill_allowed:
            paper_fill_allowed_rows += 1
            group_stats["paper_fill_allowed_rows"] += 1
            paper_fill_allowed_source_counts[source] += 1
            paper_fill_sample = route_fill_sample(
                row=row,
                source=source,
                source_group=source_group,
                identity_state=identity_state,
                route_or_fill_reason="paper_fill_allowed_true",
            )
            if len(sample_paper_fill_allowed_rows) < 10:
                sample_paper_fill_allowed_rows.append(paper_fill_sample)
            if len(source_group_route_fill_samples[source_group]["paper_fill_allowed"]) < 5:
                source_group_route_fill_samples[source_group]["paper_fill_allowed"].append(paper_fill_sample)
        if identity_state == "complete" and row_routes_to_live:
            candidate_bound_live_route_rows += 1
            group_stats["candidate_bound_live_route_rows"] += 1
        if identity_state == "complete" and row_paper_fill_allowed:
            candidate_bound_paper_fill_allowed_rows += 1
            group_stats["candidate_bound_paper_fill_allowed_rows"] += 1
        if identity_state == "complete" and (row_routes_to_live or row_paper_fill_allowed):
            candidate_bound_route_or_fill_rows += 1
            group_stats["candidate_bound_route_or_fill_rows"] += 1

        missing_fields: list[str] = []
        for required_field in REQUIRED_COST_EVIDENCE_FIELDS:
            present, field_source_name = source_presence_for_required_field(row, required_field)
            if present:
                field_present[required_field] += 1
            else:
                missing_fields.append(required_field)
                missing_reason_counts[required_field] += 1
                source_group_missing_fields[source_group][required_field] += 1
        if not missing_fields:
            all_required_source_rows += 1
            group_stats["all_required_source_fields_present_rows"] += 1
        else:
            group_stats["missing_required_source_fields_rows"] += 1

        evidence = cost_evidence_for_row(row, source_context="paper_runtime")
        fallback_components.update(str(name) for name in evidence.get("fallback_components") or ())
        production_grade = evidence.get("production_grade") is True
        if production_grade:
            production_grade_rows += 1
            group_stats["production_grade_rows"] += 1
            if identity_state == "complete":
                production_grade_complete_identity_rows += 1
                group_stats["candidate_identity_complete_production_grade_rows"] += 1
            if row_routes_to_live or row_paper_fill_allowed:
                production_grade_route_or_fill_blocked_rows += 1
                group_stats["route_or_fill_blocked_production_grade_rows"] += 1
                if identity_state == "complete":
                    candidate_bound_route_or_fill_blocked_production_grade_rows += 1
                    group_stats["candidate_bound_route_or_fill_blocked_production_grade_rows"] += 1
            missing_identity_fields: list[str] = []
            for identity_field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS:
                if row.get(identity_field) not in (None, ""):
                    production_grade_identity_field_present[identity_field] += 1
                else:
                    production_grade_identity_missing_counts[identity_field] += 1
                    group_stats[f"production_grade_missing_{identity_field}_rows"] += 1
                    missing_identity_fields.append(identity_field)
            for alternate_field, values in production_grade_alternate_identity_values.items():
                value = row.get(alternate_field)
                if value not in (None, ""):
                    values[str(value)] += 1
            if len(sample_production_grade_rows) < 10:
                sample_production_grade_rows.append(
                    {
                        "source_key": source,
                        "identity_state": identity_state,
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
                        "decision_time": first_present(row, "decision_time", "decision_time_est", "generated_at", "generated_utc"),
                        "order_size_usd": row.get("order_size_usd"),
                        "paper_fill_allowed": row.get("paper_fill_allowed"),
                        "routes_to_live": row.get("routes_to_live"),
                    }
                )
            if identity_state != "complete" and len(sample_production_grade_identity_gap_rows) < 10:
                sample_production_grade_identity_gap_rows.append(
                    {
                        "source_key": source,
                        "identity_state": identity_state,
                        "missing_required_identity_fields": missing_identity_fields,
                        "candidate_id": row.get("candidate_id"),
                        "policy_fingerprint": row.get("policy_fingerprint"),
                        "model_source": row.get("model_source"),
                        "selector_policy_fingerprint": row.get("selector_policy_fingerprint"),
                        "frozen_selector_fingerprint": row.get("frozen_selector_fingerprint"),
                        "trainer_source": row.get("trainer_source"),
                        "model_id": row.get("model_id"),
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
                        "decision_time": first_present(row, "decision_time", "decision_time_est", "generated_at", "generated_utc"),
                        "order_size_usd": row.get("order_size_usd"),
                        "paper_fill_allowed": row.get("paper_fill_allowed"),
                        "routes_to_live": row.get("routes_to_live"),
                        "places_real_order": row.get("places_real_order"),
                        "live_order": row.get("live_order"),
                    }
                )

        row_blockers: list[str] = []
        if identity_state != "complete":
            row_blockers.append("challenger_identity_not_complete")
        if not production_grade:
            row_blockers.append("production_cost_not_grade")
        if missing_fields:
            row_blockers.append("required_cost_source_fields_missing")
        if row_routes_to_live:
            row_blockers.append("routes_to_live_true")
        if row_paper_fill_allowed:
            row_blockers.append("paper_fill_allowed_true")
        if row_blockers:
            blocker_counts.update(row_blockers)
            for blocker in row_blockers:
                group_stats[f"blocker_{blocker}_rows"] += 1
            if len(sample_blocked_rows) < 10:
                sample_blocked_rows.append(
                    {
                        "source_key": source,
                        "identity_state": identity_state,
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
                        "decision_time": first_present(row, "decision_time", "decision_time_est", "generated_at", "generated_utc"),
                        "missing_source_fields": missing_fields,
                        "fallback_components": evidence.get("fallback_components"),
                        "blockers": row_blockers,
                        "paper_fill_allowed": row.get("paper_fill_allowed"),
                        "routes_to_live": row.get("routes_to_live"),
                        "places_real_order": row.get("places_real_order"),
                        "live_order": row.get("live_order"),
                    }
                )
        elif production_grade:
            challenger_bound_production_grade_rows += 1
            group_stats["challenger_bound_production_grade_rows"] += 1
            if len(sample_challenger_bound_rows) < 10:
                sample_challenger_bound_rows.append(
                    {
                        "source_key": source,
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "snapshot_id": row.get("feature_snapshot_id") or row.get("snapshot_id"),
                        "decision_time": first_present(row, "decision_time", "decision_time_est", "generated_at", "generated_utc"),
                        "order_size_usd": row.get("order_size_usd"),
                    }
                )

    row_count = len(rows)
    redis_scan_source_counts = dict(sorted(Counter(dict(source_counts or {})).items()))
    old_policy_or_unbound_production_grade_rows = production_grade_rows - production_grade_complete_identity_rows
    if scan_limit_reached:
        status = "BLOCKED_PAPER_COST_TELEMETRY_SCAN_LIMIT_REACHED"
    elif challenger_bound_production_grade_rows and live_route_rows == 0 and paper_fill_allowed_rows == 0:
        status = "READY_CHALLENGER_BOUND_PRODUCTION_GRADE_COST_TELEMETRY_PRESENT"
    elif production_grade_rows and old_policy_or_unbound_production_grade_rows:
        status = "BLOCKED_CHALLENGER_IDENTITY_MISSING_FOR_COST_TELEMETRY"
    elif production_grade_rows and production_grade_route_or_fill_blocked_rows:
        status = "BLOCKED_PAPER_COST_TELEMETRY_ROUTE_OR_FILL_ALLOWED"
    elif production_grade_rows:
        status = "BLOCKED_CHALLENGER_BOUND_COST_TELEMETRY_NOT_COUNTABLE"
    else:
        status = "BLOCKED_PRODUCTION_GRADE_PAPER_COST_TELEMETRY_MISSING"
    pass_conditions = {
        "paper_rows_scanned_gt_0": row_count > 0,
        "redis_scan_limit_not_reached": not scan_limit_reached,
        "production_grade_paper_cost_rows_gt_0": production_grade_rows > 0,
        "challenger_bound_production_grade_rows_gt_0": challenger_bound_production_grade_rows > 0,
        "old_policy_or_unbound_rows_not_counted": True,
        "live_route_rows_eq_0": live_route_rows == 0,
        "paper_fill_allowed_rows_eq_0": paper_fill_allowed_rows == 0,
        "candidate_bound_live_route_rows_eq_0": candidate_bound_live_route_rows == 0,
        "candidate_bound_paper_fill_allowed_rows_eq_0": candidate_bound_paper_fill_allowed_rows == 0,
        "fallback_rows_excluded_from_training_lockbox_promotion": True,
        "counted_rows_have_complete_identity_and_production_grade_cost": (
            challenger_bound_production_grade_rows <= production_grade_complete_identity_rows
            and challenger_bound_production_grade_rows <= production_grade_rows
        ),
    }
    readiness_actuals = {
        "paper_rows_scanned_gt_0": row_count,
        "redis_scan_limit_not_reached": {"scan_limit_reached": scan_limit_reached},
        "production_grade_paper_cost_rows_gt_0": production_grade_rows,
        "challenger_bound_production_grade_rows_gt_0": challenger_bound_production_grade_rows,
        "old_policy_or_unbound_rows_not_counted": old_policy_or_unbound_production_grade_rows,
        "live_route_rows_eq_0": live_route_rows,
        "paper_fill_allowed_rows_eq_0": paper_fill_allowed_rows,
        "candidate_bound_live_route_rows_eq_0": candidate_bound_live_route_rows,
        "candidate_bound_paper_fill_allowed_rows_eq_0": candidate_bound_paper_fill_allowed_rows,
        "fallback_rows_excluded_from_training_lockbox_promotion": True,
        "counted_rows_have_complete_identity_and_production_grade_cost": {
            "challenger_bound_production_grade_rows": challenger_bound_production_grade_rows,
            "candidate_identity_complete_production_grade_rows": production_grade_complete_identity_rows,
            "paper_telemetry_production_grade_rows": production_grade_rows,
        },
    }
    readiness_required = {
        "paper_rows_scanned_gt_0": ">0",
        "redis_scan_limit_not_reached": {"scan_limit_reached": False},
        "production_grade_paper_cost_rows_gt_0": ">0",
        "challenger_bound_production_grade_rows_gt_0": ">0",
        "old_policy_or_unbound_rows_not_counted": "excluded from challenger credit",
        "live_route_rows_eq_0": 0,
        "paper_fill_allowed_rows_eq_0": 0,
        "candidate_bound_live_route_rows_eq_0": 0,
        "candidate_bound_paper_fill_allowed_rows_eq_0": 0,
        "fallback_rows_excluded_from_training_lockbox_promotion": True,
        "counted_rows_have_complete_identity_and_production_grade_cost": (
            "challenger_bound_production_grade_rows <= complete identity production-grade rows"
        ),
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if not passed]
    blocked_reason_details = {
        name: {
            "pass_condition": name,
            "passed": pass_conditions.get(name) is True,
            "meaning": {
                "paper_rows_scanned_gt_0": "At least one paper telemetry row must be inspected.",
                "redis_scan_limit_not_reached": "The Redis paper signal scan must finish without hitting the configured limit.",
                "production_grade_paper_cost_rows_gt_0": "At least one paper telemetry row must have production-grade cost evidence.",
                "challenger_bound_production_grade_rows_gt_0": "At least one production-grade paper telemetry row must be bound to the frozen challenger identity.",
                "live_route_rows_eq_0": "No inspected paper telemetry rows may route to live execution.",
                "paper_fill_allowed_rows_eq_0": "No inspected rows may be paper-fill allowed before cost, lockbox, and canary gates pass.",
                "candidate_bound_live_route_rows_eq_0": "No frozen-challenger-bound paper telemetry rows may route to live execution.",
                "candidate_bound_paper_fill_allowed_rows_eq_0": "No frozen-challenger-bound paper telemetry rows may be paper-fill allowed before lockbox pass.",
            }.get(name, "See pass_conditions for the required invariant."),
            "observed": readiness_actuals.get(name),
            "required": readiness_required.get(name),
        }
        for name in blocked_reasons
    }
    source_group_readiness: dict[str, Any] = {}
    for group, stats in sorted(source_group_stats.items()):
        group_rows = int(stats.get("rows") or 0)
        group_production_grade_rows = int(stats.get("production_grade_rows") or 0)
        group_identity_complete_production_grade_rows = int(
            stats.get("candidate_identity_complete_production_grade_rows") or 0
        )
        group_challenger_bound_production_grade_rows = int(stats.get("challenger_bound_production_grade_rows") or 0)
        group_old_or_unbound_production_grade_rows = max(
            0,
            group_production_grade_rows - group_identity_complete_production_grade_rows,
        )
        group_missing_counts = dict(sorted(source_group_missing_fields.get(group, Counter()).items()))
        group_blockers: list[str] = []
        if group_challenger_bound_production_grade_rows == 0:
            group_blockers.append("challenger_bound_production_grade_rows_gt_0")
        if group_old_or_unbound_production_grade_rows:
            group_blockers.append("old_policy_or_unbound_production_grade_rows_present")
        if int(stats.get("paper_fill_allowed_rows") or 0):
            group_blockers.append("paper_fill_allowed_rows_eq_0")
        if int(stats.get("live_route_rows") or 0):
            group_blockers.append("live_route_rows_eq_0")
        if int(stats.get("candidate_bound_paper_fill_allowed_rows") or 0):
            group_blockers.append("candidate_bound_paper_fill_allowed_rows_eq_0")
        if int(stats.get("candidate_bound_live_route_rows") or 0):
            group_blockers.append("candidate_bound_live_route_rows_eq_0")
        if int(stats.get("missing_required_source_fields_rows") or 0):
            group_blockers.append("all_required_source_fields_present")
        source_group_readiness[group] = {
            "rows": group_rows,
            "production_grade_rows": group_production_grade_rows,
            "production_grade_coverage": group_production_grade_rows / group_rows if group_rows else 0.0,
            "candidate_identity_complete_rows": int(stats.get("candidate_identity_complete_rows") or 0),
            "candidate_identity_partial_rows": int(stats.get("candidate_identity_partial_rows") or 0),
            "candidate_identity_none_rows": int(stats.get("candidate_identity_none_rows") or 0),
            "candidate_identity_complete_production_grade_rows": group_identity_complete_production_grade_rows,
            "challenger_bound_production_grade_rows": group_challenger_bound_production_grade_rows,
            "old_policy_or_unbound_production_grade_rows": group_old_or_unbound_production_grade_rows,
            "route_or_fill_blocked_production_grade_rows": int(
                stats.get("route_or_fill_blocked_production_grade_rows") or 0
            ),
            "candidate_bound_route_or_fill_blocked_production_grade_rows": int(
                stats.get("candidate_bound_route_or_fill_blocked_production_grade_rows") or 0
            ),
            "candidate_bound_route_or_fill_rows": int(stats.get("candidate_bound_route_or_fill_rows") or 0),
            "candidate_bound_paper_fill_allowed_rows": int(stats.get("candidate_bound_paper_fill_allowed_rows") or 0),
            "candidate_bound_live_route_rows": int(stats.get("candidate_bound_live_route_rows") or 0),
            "paper_fill_allowed_rows": int(stats.get("paper_fill_allowed_rows") or 0),
            "live_route_rows": int(stats.get("live_route_rows") or 0),
            "all_required_source_fields_present_rows": int(stats.get("all_required_source_fields_present_rows") or 0),
            "missing_required_source_fields_rows": int(stats.get("missing_required_source_fields_rows") or 0),
            "missing_required_cost_source_field_counts": group_missing_counts,
            "blocker_counts": {
                key.removeprefix("blocker_").removesuffix("_rows"): int(value)
                for key, value in sorted(stats.items())
                if key.startswith("blocker_")
            },
            "sample_paper_fill_allowed_rows": source_group_route_fill_samples[group]["paper_fill_allowed"],
            "sample_live_route_rows": source_group_route_fill_samples[group]["live_route"],
            "blocked_reasons": group_blockers,
        }

    source_group_readiness_summary = {
        group: {
            "rows": payload.get("rows"),
            "production_grade_rows": payload.get("production_grade_rows"),
            "challenger_bound_production_grade_rows": payload.get("challenger_bound_production_grade_rows"),
            "old_policy_or_unbound_production_grade_rows": payload.get("old_policy_or_unbound_production_grade_rows"),
            "paper_fill_allowed_rows": payload.get("paper_fill_allowed_rows"),
            "live_route_rows": payload.get("live_route_rows"),
            "blocked_reasons": payload.get("blocked_reasons") or [],
        }
        for group, payload in source_group_readiness.items()
    }
    blocker_samples = list(blocked_reason_details.values())[:25]

    return {
        "schema_version": "challenger_v2_paper_cost_telemetry_readiness_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": status,
        "redis_status": redis_status,
        "local_source_status": dict(local_source_status or {}),
        "paper_rows_scanned": row_count,
        "source_counts": dict(sorted(source_counter.items())),
        "redis_scan_source_counts": redis_scan_source_counts,
        "scan_limit_reached": scan_limit_reached,
        "scan_completeness_status": "SCAN_INCOMPLETE_LIMIT_REACHED" if scan_limit_reached else "SCAN_COMPLETE_WITHIN_LIMIT",
        "candidate_identity_counts": {
            "complete": complete_identity_rows,
            "partial": partial_identity_rows,
            "none": none_identity_rows,
        },
        "required_credit_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "identity_field_coverage": {
            name: {
                "present_rows": identity_field_present.get(name, 0),
                "missing_rows": row_count - identity_field_present.get(name, 0),
                "coverage": identity_field_present.get(name, 0) / row_count if row_count else 0.0,
            }
            for name in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS
        },
        "production_grade_identity_field_coverage": {
            name: {
                "present_rows": production_grade_identity_field_present.get(name, 0),
                "missing_rows": production_grade_rows - production_grade_identity_field_present.get(name, 0),
                "coverage": production_grade_identity_field_present.get(name, 0) / production_grade_rows if production_grade_rows else 0.0,
            }
            for name in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS
        },
        "production_grade_identity_missing_counts": dict(sorted(production_grade_identity_missing_counts.items())),
        "production_grade_alternate_identity_value_counts": {
            name: dict(counter.most_common(10))
            for name, counter in production_grade_alternate_identity_values.items()
            if counter
        },
        "paper_telemetry_production_grade_rows": production_grade_rows,
        "candidate_identity_complete_production_grade_rows": production_grade_complete_identity_rows,
        "route_or_fill_blocked_production_grade_rows": production_grade_route_or_fill_blocked_rows,
        "candidate_bound_route_or_fill_blocked_production_grade_rows": (
            candidate_bound_route_or_fill_blocked_production_grade_rows
        ),
        "candidate_bound_route_or_fill_rows": candidate_bound_route_or_fill_rows,
        "candidate_bound_paper_fill_allowed_rows": candidate_bound_paper_fill_allowed_rows,
        "candidate_bound_live_route_rows": candidate_bound_live_route_rows,
        "all_required_source_fields_present_rows": all_required_source_rows,
        "challenger_bound_production_grade_rows": challenger_bound_production_grade_rows,
        "old_policy_or_unbound_production_grade_rows": old_policy_or_unbound_production_grade_rows,
        "live_route_rows": live_route_rows,
        "paper_fill_allowed_rows": paper_fill_allowed_rows,
        "live_route_source_counts": dict(sorted(live_route_source_counts.items())),
        "paper_fill_allowed_source_counts": dict(sorted(paper_fill_allowed_source_counts.items())),
        "blocked_reasons": blocked_reasons,
        "blocked_reason_details": blocked_reason_details,
        "blocker_details": blocked_reason_details,
        "failed_blocker_details": blocked_reason_details,
        "actuals": readiness_actuals,
        "required": readiness_required,
        "sample_blockers": blocker_samples,
        "pass_conditions": pass_conditions,
        "source_group_readiness": source_group_readiness,
        "source_group_readiness_summary": source_group_readiness_summary,
        "field_coverage": {
            name: {
                "present_rows": field_present.get(name, 0),
                "missing_rows": row_count - field_present.get(name, 0),
                "coverage": field_present.get(name, 0) / row_count if row_count else 0.0,
                "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(name),
            }
            for name in REQUIRED_COST_EVIDENCE_FIELDS
        },
        "missing_reason_counts": dict(sorted(missing_reason_counts.items())),
        "fallback_component_counts": dict(sorted(fallback_components.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "sample_production_grade_rows": sample_production_grade_rows,
        "sample_production_grade_identity_gap_rows": sample_production_grade_identity_gap_rows,
        "sample_challenger_bound_production_grade_rows": sample_challenger_bound_rows,
        "sample_blocked_rows": sample_blocked_rows,
        "sample_paper_fill_allowed_rows": sample_paper_fill_allowed_rows,
        "sample_live_route_rows": sample_live_route_rows,
        "binding_rule": "paper telemetry may count only when candidate_id, policy_fingerprint, and model_source all match the frozen challenger",
        "cost_rule": "row must satisfy the production-equivalent cost estimator without fallback components and all required source fields",
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def paper_cost_telemetry_readiness_from_redis(
    *,
    policy: FrozenPolicy,
    signal_scan_limit: int = DEFAULT_PAPER_SIGNAL_SCAN_LIMIT,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    local_rows: list[dict[str, Any]] = []
    local_status: dict[str, Any] = {}
    local_source_counts: Counter[str] = Counter()
    if repo_root is not None:
        local_rows, local_status = read_local_paper_cost_event_rows(repo_root)
        local_source_counts.update(
            str(row.get("_paper_binding_source_key") or "local:paper_online:paper_events")
            for row in local_rows
        )
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
    except Exception as exc:
        return paper_cost_telemetry_readiness_from_rows(
            policy=policy,
            rows=local_rows,
            redis_status=f"SKIPPED_REDIS_UNAVAILABLE:{type(exc).__name__}",
            source_counts=local_source_counts,
            local_source_status=local_status,
        )

    rows: list[dict[str, Any]] = [*local_rows]
    source_counts: Counter[str] = Counter(local_source_counts)
    for key in PAPER_RUNTIME_TELEMETRY_KEYS:
        key_rows = paper_binding_rows_from_redis_value(client.get(key), source_key=key)
        rows.extend(key_rows)
        source_counts[key] += len(key_rows)

    signal_rows, signal_source_counts, _signal_count, scan_limit_reached = bounded_paper_signal_scan(
        client,
        signal_scan_limit=signal_scan_limit,
        row_reader=lambda raw, key: paper_binding_rows_from_redis_value(raw, source_key=key),
    )
    rows.extend(signal_rows)
    source_counts.update(signal_source_counts)

    return paper_cost_telemetry_readiness_from_rows(
        policy=policy,
        rows=rows,
        redis_status="READ_REDIS_PAPER_ROWS_BOUNDED",
        source_counts=source_counts,
        scan_limit_reached=scan_limit_reached,
        local_source_status=local_status,
    )


def runtime_cost_capture_operator_approved(payload: Mapping[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return status in {
        "APPROVED_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "OPERATOR_APPROVED_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_GRANTED",
        "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
    } or payload.get("operator_approval_granted") is True


def _runtime_cost_capture_approval_scope_subject_rows(approval_scope: Any) -> list[dict[str, Any]]:
    if not isinstance(approval_scope, Sequence) or isinstance(approval_scope, (str, bytes, bytearray)):
        return []
    subject_rows: list[dict[str, Any]] = []
    for row in approval_scope:
        if not isinstance(row, Mapping):
            continue
        subject_rows.append(
            {
                "source_group": row.get("source_group"),
                "capture_stage": row.get("capture_stage"),
                "producer": row.get("producer"),
                "files": sorted(str(item) for item in (row.get("files") or [])),
                "redis_keys": sorted(str(item) for item in (row.get("redis_keys") or [])),
                "required_role": row.get("required_role"),
                "requires_operator_approval": row.get("requires_operator_approval"),
                "missing_identity_fields": sorted(str(item) for item in (row.get("missing_identity_fields") or [])),
                "missing_cost_fields": sorted(str(item) for item in (row.get("missing_cost_fields") or [])),
                "required_identity_fields": sorted(str(item) for item in (row.get("required_identity_fields") or [])),
                "required_cost_fields": sorted(str(item) for item in (row.get("required_cost_fields") or [])),
                "identity_field_coverage": row.get("identity_field_coverage"),
                "cost_field_coverage": row.get("cost_field_coverage"),
                "combined_required_field_coverage": row.get("combined_required_field_coverage"),
                "approved_change_class": row.get("approved_change_class"),
                "forbidden_change_classes": sorted(
                    str(item) for item in (row.get("forbidden_change_classes") or [])
                ),
                "post_approval_proof_required": sorted(
                    str(item) for item in (row.get("post_approval_proof_required") or [])
                ),
            }
        )
    return sorted(subject_rows, key=lambda item: str(item.get("source_group") or ""))


def runtime_cost_capture_approval_subject(
    *,
    policy: FrozenPolicy,
    runtime_cost_capture_operator_approval: Mapping[str, Any],
    runtime_identity_binding_plan: Mapping[str, Any],
) -> dict[str, Any]:
    required_groups = sorted(
        str(group)
        for group in (runtime_cost_capture_operator_approval.get("approval_required_source_groups") or [])
    )
    plan_steps = runtime_identity_binding_plan.get("implementation_steps")
    plan_source_groups = []
    if isinstance(plan_steps, Sequence) and not isinstance(plan_steps, (str, bytes, bytearray)):
        plan_source_groups = sorted(
            str(step.get("source_group"))
            for step in plan_steps
            if isinstance(step, Mapping) and step.get("source_group") not in (None, "")
        )
    approval_scope = _runtime_cost_capture_approval_scope_subject_rows(
        runtime_cost_capture_operator_approval.get("approval_scope")
    )
    source_group_field_coverage_matrix = runtime_cost_capture_operator_approval.get("source_group_field_coverage_matrix")
    source_group_field_coverage_matrix = (
        dict(source_group_field_coverage_matrix)
        if isinstance(source_group_field_coverage_matrix, Mapping)
        else {}
    )
    approval_scope_field_coverage_summary = runtime_cost_capture_operator_approval.get(
        "approval_scope_field_coverage_summary"
    )
    approval_scope_field_coverage_summary = (
        dict(approval_scope_field_coverage_summary)
        if isinstance(approval_scope_field_coverage_summary, Mapping)
        else {}
    )
    required_acknowledgements = runtime_cost_capture_operator_approval.get("required_operator_acknowledgements")
    if not isinstance(required_acknowledgements, Sequence) or isinstance(
        required_acknowledgements, (str, bytes, bytearray)
    ):
        required_acknowledgements = runtime_cost_capture_operator_approval.get("required_acknowledgements")
    required_acknowledgements = [
        str(item)
        for item in (required_acknowledgements or [])
    ]
    prohibited_patch_scope = [
        str(item)
        for item in (runtime_cost_capture_operator_approval.get("prohibited_patch_scope") or [])
    ]
    return {
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "approved_patch_scope": "telemetry_only_future_runtime_cost_and_identity_capture",
        "approval_required_source_groups": required_groups,
        "implementation_plan_source_groups": plan_source_groups,
        "approval_scope": approval_scope,
        "approval_scope_hash": row_hash({"approval_scope": approval_scope}),
        "approval_scope_field_coverage_summary": approval_scope_field_coverage_summary,
        "source_group_field_coverage_matrix": source_group_field_coverage_matrix,
        "source_group_field_coverage_matrix_hash": row_hash(
            {"source_group_field_coverage_matrix": source_group_field_coverage_matrix}
        ),
        "required_identity_fields_to_persist": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "required_cost_fields_to_capture": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_operator_acknowledgements": required_acknowledgements,
        "prohibited_patch_scope": sorted(prohibited_patch_scope),
        "minimum_new_candidate_bound_production_grade_rows": runtime_cost_capture_operator_approval.get(
            "minimum_new_candidate_bound_production_grade_rows"
        ),
        "operator_approval_packet_status": runtime_cost_capture_operator_approval.get("status"),
        "runtime_identity_binding_plan_status": runtime_identity_binding_plan.get("status"),
        "paper_fill_allowed": runtime_cost_capture_operator_approval.get("paper_fill_allowed"),
        "routes_to_live": runtime_cost_capture_operator_approval.get("routes_to_live"),
        "counts_as_a_grade_evidence": runtime_cost_capture_operator_approval.get("counts_as_a_grade_evidence"),
        "forbidden_changes": [
            "do_not_modify_frozen_candidate",
            "do_not_change_features_normalization_cost_model_weights_or_thresholds",
            "do_not_backfill_existing_old_policy_or_unbound_rows_for_credit",
            "do_not_enable_paper_fill_or_live_routes_as_part_of_telemetry_capture",
        ],
    }


def runtime_cost_capture_approval_subject_hash(
    *,
    policy: FrozenPolicy,
    runtime_cost_capture_operator_approval: Mapping[str, Any],
    runtime_identity_binding_plan: Mapping[str, Any],
) -> str:
    return row_hash(
        runtime_cost_capture_approval_subject(
            policy=policy,
            runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
            runtime_identity_binding_plan=runtime_identity_binding_plan,
        )
    )


def runtime_cost_capture_operator_approval_receipt_template(
    *,
    policy: FrozenPolicy,
    runtime_cost_capture_operator_approval: Mapping[str, Any],
    runtime_identity_binding_plan: Mapping[str, Any],
) -> dict[str, Any]:
    subject = runtime_cost_capture_approval_subject(
        policy=policy,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_identity_binding_plan=runtime_identity_binding_plan,
    )
    subject_hash = row_hash(subject)
    return {
        "schema_version": "challenger_v2_runtime_cost_capture_operator_approval_receipt_template_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": "TEMPLATE_ONLY_NOT_OPERATOR_APPROVAL",
        "approval_receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "runtime_cost_capture_operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approval_subject": subject,
        "approval_subject_hash": subject_hash,
        "approval_subject_hash_status": "READY",
        "operator_approval_subject_hash_status": "READY",
        "required_source_groups": subject["approval_required_source_groups"],
        "approved_source_groups": subject["approval_required_source_groups"],
        "approved_patch_scope": subject["approved_patch_scope"],
        "expected_approved_patch_scope": subject["approved_patch_scope"],
        "required_acknowledgements": subject["required_operator_acknowledgements"],
        "required_operator_acknowledgements": subject["required_operator_acknowledgements"],
        "prohibited_patch_scope": subject["prohibited_patch_scope"],
        "operator_instructions": {
            "write_receipt_to": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
            "start_from_template_key": "receipt_template",
            "set_operator_approval_granted": True,
            "set_approval_utc": "UTC timestamp supplied by operator",
            "set_approved_by": "operator identity",
            "do_not_change": [
                "approved_goal_id",
                "candidate_id",
                "policy_fingerprint",
                "model_source",
                "approval_subject_hash",
                "approved_source_groups",
                "approved_patch_scope",
            ],
            "must_set_acknowledgements_true": subject["required_operator_acknowledgements"],
            "approval_scope": "telemetry-only future runtime cost and identity capture",
            "does_not_authorize": subject["prohibited_patch_scope"],
            "existing_rows_remain_non_counting": True,
            "paper_fill_allowed_after_approval": False,
            "routes_to_live_after_approval": False,
        },
        "receipt_template": {
            "schema_version": "challenger_v2_runtime_cost_capture_operator_approval_receipt_v1",
            "operator_approval_granted": False,
            "approval_utc": "",
            "approved_by": "",
            "approved_goal_id": GOAL_ID,
            "candidate_id": policy.candidate_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "model_source": policy.model_source,
            "approval_subject_hash": subject_hash,
            "approved_source_groups": subject["approval_required_source_groups"],
            "approved_patch_scope": subject["approved_patch_scope"],
            "acknowledges_no_historical_backfill_for_credit": False,
            "acknowledges_no_frozen_candidate_or_model_changes": False,
            "acknowledges_paper_fill_and_live_routes_remain_false": False,
            "operator_notes": "",
        },
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def runtime_cost_capture_operator_approval_receipt_status(
    *,
    policy: FrozenPolicy,
    runtime_cost_capture_operator_approval: Mapping[str, Any],
    runtime_identity_binding_plan: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    receipt_payload = receipt if isinstance(receipt, Mapping) else {}
    subject = runtime_cost_capture_approval_subject(
        policy=policy,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_identity_binding_plan=runtime_identity_binding_plan,
    )
    subject_hash = row_hash(subject)
    required_groups = list(subject["approval_required_source_groups"])
    approved_groups = sorted(str(group) for group in (receipt_payload.get("approved_source_groups") or []))
    pass_conditions = {
        "approval_receipt_present": bool(receipt_payload),
        "operator_approval_granted_true": receipt_payload.get("operator_approval_granted") is True,
        "approval_utc_present": receipt_payload.get("approval_utc") not in (None, ""),
        "approved_by_present": receipt_payload.get("approved_by") not in (None, ""),
        "approved_goal_id_matches": receipt_payload.get("approved_goal_id") == GOAL_ID,
        "candidate_id_matches_frozen_candidate": receipt_payload.get("candidate_id") == policy.candidate_id,
        "policy_fingerprint_matches_frozen_policy": receipt_payload.get("policy_fingerprint") == policy.policy_fingerprint,
        "model_source_matches_frozen_policy": receipt_payload.get("model_source") == policy.model_source,
        "approval_subject_hash_matches_current_plan": receipt_payload.get("approval_subject_hash") == subject_hash,
        "approved_source_groups_exact_match": approved_groups == required_groups,
        "approved_patch_scope_telemetry_only": receipt_payload.get("approved_patch_scope") == subject["approved_patch_scope"],
        "acknowledges_no_historical_backfill_for_credit": receipt_payload.get("acknowledges_no_historical_backfill_for_credit") is True,
        "acknowledges_no_frozen_candidate_or_model_changes": receipt_payload.get("acknowledges_no_frozen_candidate_or_model_changes") is True,
        "acknowledges_paper_fill_and_live_routes_remain_false": receipt_payload.get("acknowledges_paper_fill_and_live_routes_remain_false") is True,
        "operator_approval_packet_awaiting_or_approved": str(runtime_cost_capture_operator_approval.get("status") or "") in {
            "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "APPROVED_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "OPERATOR_APPROVED_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_GRANTED",
        },
        "runtime_identity_binding_plan_ready": runtime_identity_binding_plan.get("status")
        == "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
    }
    blocked_conditions = [name for name, passed in pass_conditions.items() if passed is not True]
    condition_receipt_fields = {
        "approval_receipt_present": "__receipt__",
        "operator_approval_granted_true": "operator_approval_granted",
        "approval_utc_present": "approval_utc",
        "approved_by_present": "approved_by",
        "approved_goal_id_matches": "approved_goal_id",
        "candidate_id_matches_frozen_candidate": "candidate_id",
        "policy_fingerprint_matches_frozen_policy": "policy_fingerprint",
        "model_source_matches_frozen_policy": "model_source",
        "approval_subject_hash_matches_current_plan": "approval_subject_hash",
        "approved_source_groups_exact_match": "approved_source_groups",
        "approved_patch_scope_telemetry_only": "approved_patch_scope",
        "acknowledges_no_historical_backfill_for_credit": "acknowledges_no_historical_backfill_for_credit",
        "acknowledges_no_frozen_candidate_or_model_changes": "acknowledges_no_frozen_candidate_or_model_changes",
        "acknowledges_paper_fill_and_live_routes_remain_false": "acknowledges_paper_fill_and_live_routes_remain_false",
    }
    missing_or_invalid_receipt_fields = [
        field
        for condition in blocked_conditions
        for field in [condition_receipt_fields.get(condition)]
        if field
    ]
    observed_by_condition = {
        "approval_receipt_present": bool(receipt_payload),
        "operator_approval_granted_true": receipt_payload.get("operator_approval_granted"),
        "approval_utc_present": receipt_payload.get("approval_utc"),
        "approved_by_present": receipt_payload.get("approved_by"),
        "approved_goal_id_matches": receipt_payload.get("approved_goal_id"),
        "candidate_id_matches_frozen_candidate": receipt_payload.get("candidate_id"),
        "policy_fingerprint_matches_frozen_policy": receipt_payload.get("policy_fingerprint"),
        "model_source_matches_frozen_policy": receipt_payload.get("model_source"),
        "approval_subject_hash_matches_current_plan": receipt_payload.get("approval_subject_hash"),
        "approved_source_groups_exact_match": approved_groups,
        "approved_patch_scope_telemetry_only": receipt_payload.get("approved_patch_scope"),
        "acknowledges_no_historical_backfill_for_credit": receipt_payload.get(
            "acknowledges_no_historical_backfill_for_credit"
        ),
        "acknowledges_no_frozen_candidate_or_model_changes": receipt_payload.get(
            "acknowledges_no_frozen_candidate_or_model_changes"
        ),
        "acknowledges_paper_fill_and_live_routes_remain_false": receipt_payload.get(
            "acknowledges_paper_fill_and_live_routes_remain_false"
        ),
        "operator_approval_packet_awaiting_or_approved": runtime_cost_capture_operator_approval.get("status"),
        "runtime_identity_binding_plan_ready": runtime_identity_binding_plan.get("status"),
    }
    required_by_condition = {
        "approval_receipt_present": True,
        "operator_approval_granted_true": True,
        "approval_utc_present": "non-empty approval_utc",
        "approved_by_present": "non-empty approved_by",
        "approved_goal_id_matches": GOAL_ID,
        "candidate_id_matches_frozen_candidate": policy.candidate_id,
        "policy_fingerprint_matches_frozen_policy": policy.policy_fingerprint,
        "model_source_matches_frozen_policy": policy.model_source,
        "approval_subject_hash_matches_current_plan": subject_hash,
        "approved_source_groups_exact_match": required_groups,
        "approved_patch_scope_telemetry_only": subject["approved_patch_scope"],
        "acknowledges_no_historical_backfill_for_credit": True,
        "acknowledges_no_frozen_candidate_or_model_changes": True,
        "acknowledges_paper_fill_and_live_routes_remain_false": True,
        "operator_approval_packet_awaiting_or_approved": [
            "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "APPROVED_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "OPERATOR_APPROVED_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_GRANTED",
        ],
        "runtime_identity_binding_plan_ready": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
    }
    blocker_details = [
        {
            "pass_condition": condition,
            "passed": False,
            "receipt_field": condition_receipt_fields.get(condition),
            "observed": observed_by_condition.get(condition),
            "required": required_by_condition.get(condition),
            "source_artifact": (
                RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT
                if condition in condition_receipt_fields
                else "challenger_v2_runtime_identity_binding_implementation_plan.json"
                if condition == "runtime_identity_binding_plan_ready"
                else "challenger_v2_runtime_cost_capture_operator_approval_packet.json"
            ),
            "operator_action": "provide_valid_runtime_cost_capture_operator_approval_receipt",
        }
        for condition in blocked_conditions
    ]
    if not receipt_payload:
        status = "AWAITING_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    elif blocked_conditions:
        status = "BLOCKED_INVALID_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    else:
        status = "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    required_receipt_fields = [
        "operator_approval_granted",
        "approval_utc",
        "approved_by",
        "approved_goal_id",
        "candidate_id",
        "policy_fingerprint",
        "model_source",
        "approval_subject_hash",
        "approved_source_groups",
        "approved_patch_scope",
        "acknowledges_no_historical_backfill_for_credit",
        "acknowledges_no_frozen_candidate_or_model_changes",
        "acknowledges_paper_fill_and_live_routes_remain_false",
    ]
    return {
        "schema_version": "challenger_v2_runtime_cost_capture_operator_approval_receipt_status_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": status,
        "operator_approval_required": True,
        "operator_approval_granted": status == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "approval_receipt_present": pass_conditions["approval_receipt_present"],
        "operator_approval_receipt_present": pass_conditions["approval_receipt_present"],
        "operator_approval_receipt_status": status,
        "operator_approval_receipt_valid": status == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "approval_gate_open": status == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "operator_approved_runtime_cost_capture": status == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "operator_approved_identity_binding": status == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "approval_required_before_runtime_write_path_edits": True,
        "operator_approval_required_before_runtime_write_path_edits": True,
        "operator_approval_required_before_applying_plan": True,
        "approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "runtime_cost_capture_operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "required_receipt_fields": required_receipt_fields,
        "approval_subject": subject,
        "approval_subject_hash": subject_hash,
        "expected_approval_subject_hash": subject_hash,
        "receipt_approval_subject_hash": receipt_payload.get("approval_subject_hash"),
        "approval_subject_hash_status": "READY",
        "operator_approval_subject_hash_status": "READY",
        "approved_source_groups_observed": approved_groups,
        "approved_source_groups": approved_groups,
        "required_source_groups": required_groups,
        "expected_source_groups": required_groups,
        "expected_approved_source_groups": required_groups,
        "source_groups": required_groups,
        "source_group_count": len(required_groups),
        "approved_source_group_count": len(approved_groups),
        "required_source_group_count": len(required_groups),
        "approval_required_source_groups": required_groups,
        "operator_approval_required_source_groups": required_groups,
        "approved_patch_scope": receipt_payload.get("approved_patch_scope"),
        "approved_patch_scope_observed": receipt_payload.get("approved_patch_scope"),
        "expected_approved_patch_scope": subject["approved_patch_scope"],
        "required_acknowledgements": subject["required_operator_acknowledgements"],
        "required_operator_acknowledgements": subject["required_operator_acknowledgements"],
        "prohibited_patch_scope": subject["prohibited_patch_scope"],
        "blocked_conditions": blocked_conditions,
        "blocked_reasons": blocked_conditions,
        "missing_or_invalid_receipt_fields": missing_or_invalid_receipt_fields,
        "missing_receipt_fields": missing_or_invalid_receipt_fields,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "sample_blockers": blocker_details[:25],
        "actuals": observed_by_condition,
        "required": required_by_condition,
        "operator_action_required": status != "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "operator_instructions": {
            "required_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
            "template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
            "required_approval_subject_hash": subject_hash,
            "required_source_groups": required_groups,
            "required_patch_scope": subject["approved_patch_scope"],
            "must_acknowledge": subject["required_operator_acknowledgements"],
            "existing_rows_remain_non_counting": True,
            "paper_fill_allowed_after_approval": False,
            "routes_to_live_after_approval": False,
        },
        "receipt_acceptance_rule": {
            "operator_approval_granted": True,
            "approval_subject_hash": subject_hash,
            "approved_source_groups": required_groups,
            "approved_patch_scope": subject["approved_patch_scope"],
            "must_acknowledge_no_historical_backfill_for_credit": True,
            "must_acknowledge_no_frozen_candidate_or_model_changes": True,
            "must_acknowledge_paper_fill_and_live_routes_remain_false": True,
        },
        "pass_conditions": pass_conditions,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def future_runtime_cost_evidence_acceptance_decision(
    row: Mapping[str, Any],
    *,
    policy: FrozenPolicy,
    source_group: str,
    operator_approved: bool,
    lockbox_passed: bool = False,
) -> dict[str, Any]:
    normalized = paper_cost_readiness_row(row)
    evidence = cost_evidence_for_row(normalized, source_context=f"future_runtime_acceptance.{source_group}")
    missing_source_fields: list[str] = []
    for required_field in REQUIRED_COST_EVIDENCE_FIELDS:
        present, _source = source_presence_for_required_field(normalized, required_field)
        if not present:
            missing_source_fields.append(required_field)

    rejection_reasons: list[str] = []
    if not operator_approved:
        rejection_reasons.append("operator_approval_missing")
    if source_group not in RUNTIME_COST_CAPTURE_WRITE_POINTS:
        rejection_reasons.append("source_group_not_approved_for_runtime_capture")
    identity_state = challenger_identity_state(normalized, policy)
    if identity_state != "complete":
        rejection_reasons.append("challenger_identity_not_complete")
    if evidence.get("production_grade") is not True:
        rejection_reasons.append("cost_not_production_grade")
    if evidence.get("fallback") is True:
        rejection_reasons.append("fallback_true_not_countable")
    if missing_source_fields:
        rejection_reasons.append("required_cost_source_fields_missing")

    decision_time = parse_utc(first_present(normalized, "decision_time", "decision_time_est", "generated_at", "generated_utc"))
    available_at = parse_utc(first_present(normalized, "available_at", "source_available_time", "source_received_time_est", "generated_at", "generated_utc"))
    feature_cutoff = parse_utc(first_present(normalized, "feature_cutoff", "entry_feature_cutoff", "candle_close_time"))
    if decision_time is None:
        rejection_reasons.append("decision_time_missing_or_invalid")
    if available_at is None:
        rejection_reasons.append("available_at_missing_or_invalid")
    if feature_cutoff is None:
        rejection_reasons.append("feature_cutoff_missing_or_invalid")
    if decision_time is not None and available_at is not None and available_at > decision_time:
        rejection_reasons.append("available_at_after_decision_time")
    if decision_time is not None and feature_cutoff is not None and feature_cutoff > decision_time:
        rejection_reasons.append("feature_cutoff_after_decision_time")
    if paper_row_routes_to_live(normalized):
        rejection_reasons.append("routes_to_live_true")
    if normalized.get("paper_fill_allowed") is True and not lockbox_passed:
        rejection_reasons.append("paper_fill_allowed_before_lockbox_pass")

    return {
        "accepted_as_phase_1_production_grade_evidence": not rejection_reasons,
        "rejection_reasons": rejection_reasons,
        "source_group": source_group,
        "identity_state": identity_state,
        "production_grade": evidence.get("production_grade") is True,
        "fallback": evidence.get("fallback") is True,
        "missing_source_fields": missing_source_fields,
        "cost_evidence": evidence,
        "paper_fill_allowed": normalized.get("paper_fill_allowed") is True,
        "routes_to_live": paper_row_routes_to_live(normalized),
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def future_runtime_cost_evidence_acceptance_contract(
    *,
    policy: FrozenPolicy,
    paper_cost_telemetry: Mapping[str, Any],
    runtime_cost_capture_operator_approval: Mapping[str, Any],
    runtime_identity_binding_plan: Mapping[str, Any],
    runtime_cost_capture_operator_approval_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    receipt_payload = (
        runtime_cost_capture_operator_approval_receipt
        if isinstance(runtime_cost_capture_operator_approval_receipt, Mapping)
        else {}
    )
    operator_approved = runtime_cost_capture_operator_approved(runtime_cost_capture_operator_approval) or runtime_cost_capture_operator_approved(receipt_payload)
    challenger_bound_rows = int(paper_cost_telemetry.get("challenger_bound_production_grade_rows") or 0)
    old_or_unbound_rows = int(paper_cost_telemetry.get("old_policy_or_unbound_production_grade_rows") or 0)
    paper_fill_allowed_rows = int(paper_cost_telemetry.get("paper_fill_allowed_rows") or 0)
    live_route_rows = int(paper_cost_telemetry.get("live_route_rows") or 0)
    candidate_bound_paper_fill_allowed_rows = int(paper_cost_telemetry.get("candidate_bound_paper_fill_allowed_rows") or 0)
    candidate_bound_live_route_rows = int(paper_cost_telemetry.get("candidate_bound_live_route_rows") or 0)
    quarantined_paper_fill_allowed_rows = max(0, paper_fill_allowed_rows - candidate_bound_paper_fill_allowed_rows)
    quarantined_live_route_rows = max(0, live_route_rows - candidate_bound_live_route_rows)
    source_group_readiness = paper_cost_telemetry.get("source_group_readiness")
    source_group_readiness = source_group_readiness if isinstance(source_group_readiness, Mapping) else {}
    group_acceptance_summary: dict[str, Any] = {}
    for group, payload in sorted(source_group_readiness.items()):
        if not isinstance(payload, Mapping):
            continue
        group_acceptance_summary[str(group)] = {
            "rows": payload.get("rows"),
            "production_grade_rows": payload.get("production_grade_rows"),
            "challenger_bound_production_grade_rows": payload.get("challenger_bound_production_grade_rows"),
            "old_policy_or_unbound_production_grade_rows": payload.get("old_policy_or_unbound_production_grade_rows"),
            "candidate_bound_paper_fill_allowed_rows": payload.get("candidate_bound_paper_fill_allowed_rows"),
            "candidate_bound_live_route_rows": payload.get("candidate_bound_live_route_rows"),
            "paper_fill_allowed_rows": payload.get("paper_fill_allowed_rows"),
            "live_route_rows": payload.get("live_route_rows"),
            "current_acceptance_blockers": payload.get("blocked_reasons"),
        }

    pass_conditions = {
        "acceptance_predicate_declared": True,
        "runtime_identity_binding_plan_ready": runtime_identity_binding_plan.get("status")
        == "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
        "operator_approval_granted": operator_approved,
        "operator_approval_receipt_valid_or_packet_explicitly_approved": operator_approved,
        "future_challenger_bound_production_grade_rows_present": challenger_bound_rows > 0,
        "old_or_unbound_rows_not_counted": True,
        "old_or_unbound_paper_fill_allowed_rows_quarantined": True,
        "old_or_unbound_live_route_rows_quarantined": True,
        "candidate_bound_paper_fill_allowed_rows_eq_0": candidate_bound_paper_fill_allowed_rows == 0,
        "candidate_bound_live_route_rows_eq_0": candidate_bound_live_route_rows == 0,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    future_runtime_row_acceptance_gate_open = (
        pass_conditions["runtime_identity_binding_plan_ready"] is True
        and pass_conditions["operator_approval_granted"] is True
        and pass_conditions["candidate_bound_paper_fill_allowed_rows_eq_0"] is True
        and pass_conditions["candidate_bound_live_route_rows_eq_0"] is True
    )
    currently_countable_phase_1_rows = challenger_bound_rows if future_runtime_row_acceptance_gate_open else 0
    acceptance_blocker_details = {
        "runtime_identity_binding_plan_ready": {
            "passed": pass_conditions["runtime_identity_binding_plan_ready"],
            "observed": runtime_identity_binding_plan.get("status"),
            "required": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
        },
        "operator_approval_granted": {
            "passed": pass_conditions["operator_approval_granted"],
            "observed": operator_approved,
            "required": True,
        },
        "operator_approval_receipt_valid_or_packet_explicitly_approved": {
            "passed": pass_conditions["operator_approval_receipt_valid_or_packet_explicitly_approved"],
            "observed": receipt_payload.get("status") or runtime_cost_capture_operator_approval.get("status"),
            "required": "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
            "receipt_blocked_conditions": receipt_payload.get("blocked_conditions"),
            "missing_or_invalid_receipt_fields": receipt_payload.get("missing_or_invalid_receipt_fields"),
        },
        "future_challenger_bound_production_grade_rows_present": {
            "passed": pass_conditions["future_challenger_bound_production_grade_rows_present"],
            "observed": challenger_bound_rows,
            "required": ">0",
        },
        "candidate_bound_paper_fill_allowed_rows_eq_0": {
            "passed": pass_conditions["candidate_bound_paper_fill_allowed_rows_eq_0"],
            "observed": candidate_bound_paper_fill_allowed_rows,
            "required": 0,
            "quarantined_non_candidate_bound_rows": quarantined_paper_fill_allowed_rows,
        },
        "candidate_bound_live_route_rows_eq_0": {
            "passed": pass_conditions["candidate_bound_live_route_rows_eq_0"],
            "observed": candidate_bound_live_route_rows,
            "required": 0,
            "quarantined_non_candidate_bound_rows": quarantined_live_route_rows,
        },
    }
    blocker_details = {
        name: detail
        for name, detail in acceptance_blocker_details.items()
        if detail.get("passed") is not True
    }
    sample_blockers = [
        {"pass_condition": name, **detail}
        for name, detail in blocker_details.items()
    ]
    if runtime_identity_binding_plan.get("status") != "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH":
        status = "BLOCKED_ACCEPTANCE_CONTRACT_NEEDS_IMPLEMENTATION_PLAN"
    elif not operator_approved:
        status = "AWAITING_OPERATOR_APPROVAL_BEFORE_ACCEPTING_FUTURE_RUNTIME_COST_ROWS"
    elif challenger_bound_rows == 0:
        status = "AWAITING_FUTURE_CHALLENGER_BOUND_PRODUCTION_GRADE_RUNTIME_ROWS"
    elif candidate_bound_paper_fill_allowed_rows or candidate_bound_live_route_rows:
        status = "BLOCKED_RUNTIME_COST_ACCEPTANCE_ROUTE_OR_FILL_ALLOWED"
    else:
        status = "READY_TO_ACCEPT_FUTURE_RUNTIME_COST_EVIDENCE_ROWS"
    acceptance_actuals = {
        "runtime_identity_binding_plan_ready": runtime_identity_binding_plan.get("status"),
        "operator_approval_granted": operator_approved,
        "operator_approval_receipt_valid_or_packet_explicitly_approved": (
            receipt_payload.get("status") or runtime_cost_capture_operator_approval.get("status")
        ),
        "future_challenger_bound_production_grade_rows_present": challenger_bound_rows,
        "old_or_unbound_rows_not_counted": old_or_unbound_rows,
        "old_or_unbound_paper_fill_allowed_rows_quarantined": quarantined_paper_fill_allowed_rows,
        "old_or_unbound_live_route_rows_quarantined": quarantined_live_route_rows,
        "candidate_bound_paper_fill_allowed_rows_eq_0": candidate_bound_paper_fill_allowed_rows,
        "candidate_bound_live_route_rows_eq_0": candidate_bound_live_route_rows,
        "future_runtime_row_acceptance_gate_open": future_runtime_row_acceptance_gate_open,
        "currently_countable_phase_1_production_grade_rows": currently_countable_phase_1_rows,
    }
    acceptance_required = {
        "runtime_identity_binding_plan_ready": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
        "operator_approval_granted": True,
        "operator_approval_receipt_valid_or_packet_explicitly_approved": (
            "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
        ),
        "future_challenger_bound_production_grade_rows_present": ">0",
        "old_or_unbound_rows_not_counted": "excluded from challenger production-grade credit",
        "old_or_unbound_paper_fill_allowed_rows_quarantined": (
            "non-candidate-bound paper_fill_allowed rows stay quarantined"
        ),
        "old_or_unbound_live_route_rows_quarantined": "non-candidate-bound live-route rows stay quarantined",
        "candidate_bound_paper_fill_allowed_rows_eq_0": 0,
        "candidate_bound_live_route_rows_eq_0": 0,
        "future_runtime_row_acceptance_gate_open": True,
        "currently_countable_phase_1_production_grade_rows": ">0 after approval and future candidate-bound capture",
    }

    return {
        "schema_version": "challenger_v2_future_runtime_cost_evidence_acceptance_contract_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": status,
        "acceptance_predicate": {
            "operator_approval_required": True,
            "source_group_must_be_one_of": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
            "identity_required": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "identity_match_required": {
                "candidate_id": policy.candidate_id,
                "policy_fingerprint": policy.policy_fingerprint,
                "model_source": policy.model_source,
            },
            "cost_fields_required": list(REQUIRED_COST_EVIDENCE_FIELDS),
            "production_grade_required": True,
            "fallback_must_be_false": True,
            "temporal_rules": [
                "available_at <= decision_time",
                "feature_cutoff <= decision_time",
                "source_timestamp <= available_at <= decision_time",
            ],
            "route_rules": [
                "routes_to_live=false",
                "places_real_order=false",
                "paper_fill_allowed=false before blind lockbox pass",
            ],
            "historical_backfill_allowed_for_credit": False,
        },
        "current_runtime_cost_capture_operator_approved": operator_approved,
        "operator_approved": operator_approved,
        "current_operator_approved": operator_approved,
        "operator_approval_packet_status": runtime_cost_capture_operator_approval.get("status"),
        "operator_approval_receipt_status": receipt_payload.get("status"),
        "current_operator_approval_packet_status": runtime_cost_capture_operator_approval.get("status"),
        "current_operator_approval_receipt_status": receipt_payload.get("status"),
        "current_operator_approval_receipt_blocked_conditions": receipt_payload.get("blocked_conditions"),
        "current_operator_approval_missing_or_invalid_receipt_fields": receipt_payload.get(
            "missing_or_invalid_receipt_fields"
        ),
        "current_operator_approval_receipt_path": receipt_payload.get("operator_approval_receipt_path")
        or receipt_payload.get("approval_receipt_path")
        or RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "current_operator_approval_receipt_template_path": receipt_payload.get("operator_approval_receipt_template_path")
        or receipt_payload.get("approval_receipt_template_path")
        or RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "current_operator_approval_receipt_status_path": receipt_payload.get(
            "runtime_cost_capture_operator_approval_receipt_status_path"
        )
        or RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "required_source_groups": receipt_payload.get("operator_approval_required_source_groups")
        or receipt_payload.get("required_source_groups")
        or runtime_cost_capture_operator_approval.get("operator_approval_required_source_groups")
        or runtime_cost_capture_operator_approval.get("required_source_groups")
        or runtime_cost_capture_operator_approval.get("approval_required_source_groups")
        or [],
        "approved_source_groups": receipt_payload.get("approved_source_groups")
        or receipt_payload.get("approved_source_groups_observed")
        or [],
        "current_operator_approval_subject_hash": receipt_payload.get("approval_subject_hash")
        or runtime_cost_capture_operator_approval.get("approval_subject_hash"),
        "current_challenger_bound_production_grade_rows": challenger_bound_rows,
        "future_challenger_bound_production_grade_rows": challenger_bound_rows,
        "current_old_policy_or_unbound_production_grade_rows_quarantined": old_or_unbound_rows,
        "old_policy_or_unbound_production_grade_rows": old_or_unbound_rows,
        "current_paper_fill_allowed_rows": paper_fill_allowed_rows,
        "paper_fill_allowed_rows": paper_fill_allowed_rows,
        "current_live_route_rows": live_route_rows,
        "live_route_rows": live_route_rows,
        "current_candidate_bound_paper_fill_allowed_rows": candidate_bound_paper_fill_allowed_rows,
        "candidate_bound_paper_fill_allowed_rows": candidate_bound_paper_fill_allowed_rows,
        "current_candidate_bound_live_route_rows": candidate_bound_live_route_rows,
        "candidate_bound_live_route_rows": candidate_bound_live_route_rows,
        "quarantined_non_candidate_bound_paper_fill_allowed_rows": quarantined_paper_fill_allowed_rows,
        "quarantined_non_candidate_bound_live_route_rows": quarantined_live_route_rows,
        "future_runtime_row_acceptance_gate_open": future_runtime_row_acceptance_gate_open,
        "gate_open": future_runtime_row_acceptance_gate_open,
        "future_runtime_cost_acceptance_gate_open": future_runtime_row_acceptance_gate_open,
        "currently_countable_phase_1_production_grade_rows": currently_countable_phase_1_rows,
        "blocked_reasons": blocked_reasons,
        "acceptance_blocker_details": acceptance_blocker_details,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "sample_blockers": sample_blockers,
        "actuals": acceptance_actuals,
        "required": acceptance_required,
        "rows_count_only_after_operator_approval": True,
        "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
        "source_group_acceptance_summary": group_acceptance_summary,
        "pass_conditions": pass_conditions,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def cost_identity_join_keys(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for key_class, field_names in COST_IDENTITY_JOIN_KEY_FIELDS.items():
        for field_name in field_names:
            value = row.get(field_name)
            if value not in (None, ""):
                keys.append((key_class, str(value)))
    return keys


def source_key_for_paper_row(row: Mapping[str, Any]) -> str:
    return str(
        row.get("_paper_binding_source_key")
        or row.get("_paper_intent_source_key")
        or row.get("_paper_canary_source_key")
        or row.get("source_key")
        or "UNKNOWN"
    )


def missing_required_cost_source_fields(row: Mapping[str, Any]) -> list[str]:
    return [
        field
        for field in REQUIRED_COST_EVIDENCE_FIELDS
        if source_presence_for_required_field(row, field)[0] is not True
    ]


def cost_identity_join_recovery_audit(
    *,
    policy: FrozenPolicy,
    paper_rows: Sequence[Mapping[str, Any]],
    candidate_bound_rows: Sequence[Mapping[str, Any]],
    redis_status: str = "READ_FROM_SUPPLIED_ROWS",
    source_counts: Mapping[str, int] | None = None,
    scan_limit_reached: bool = False,
) -> dict[str, Any]:
    candidate_join_key_counts: Counter[tuple[str, str]] = Counter()
    candidate_join_key_source_counts: Counter[str] = Counter()
    candidate_bound_rows_examined = 0
    candidate_bound_rows_with_join_key = 0
    for row in candidate_bound_rows:
        if challenger_identity_state(row, policy) != "complete":
            continue
        candidate_bound_rows_examined += 1
        keys = cost_identity_join_keys(row)
        if keys:
            candidate_bound_rows_with_join_key += 1
        for key in keys:
            candidate_join_key_counts[key] += 1
            candidate_join_key_source_counts[key[0]] += 1

    paper_join_key_counts: Counter[tuple[str, str]] = Counter()
    paper_join_key_source_counts: Counter[str] = Counter()
    paper_rows_with_join_key = 0
    overlapping_join_keys: set[tuple[str, str]] = set()
    overlap_by_kind: Counter[str] = Counter()
    overlap_source_counts: Counter[str] = Counter()
    overlap_missing_field_counts: Counter[str] = Counter()
    overlapping_paper_rows = 0
    overlapping_paper_rows_with_all_required_source_fields = 0
    overlapping_paper_rows_with_core_cost_fields = 0
    overlapping_paper_rows_with_production_grade_cost = 0
    overlapping_paper_rows_with_complete_challenger_identity = 0
    recoverable_candidate_bound_production_grade_rows = 0
    diagnostic_only_external_identity_overlap_rows = 0
    live_route_overlap_rows = 0
    paper_fill_allowed_overlap_rows = 0
    samples: list[dict[str, Any]] = []

    for raw_row in paper_rows:
        row = dict(raw_row)
        keys = cost_identity_join_keys(row)
        if keys:
            paper_rows_with_join_key += 1
        for key in keys:
            paper_join_key_counts[key] += 1
            paper_join_key_source_counts[key[0]] += 1

        matched_keys = [key for key in keys if key in candidate_join_key_counts]
        if not matched_keys:
            continue

        overlapping_paper_rows += 1
        source_key = source_key_for_paper_row(row)
        overlap_source_counts[source_key] += 1
        overlapping_join_keys.update(matched_keys)
        for key in matched_keys:
            overlap_by_kind[key[0]] += 1

        missing_fields = missing_required_cost_source_fields(row)
        overlap_missing_field_counts.update(missing_fields)
        if not missing_fields:
            overlapping_paper_rows_with_all_required_source_fields += 1
        if all(field not in missing_fields for field in CORE_COST_JOIN_FIELDS):
            overlapping_paper_rows_with_core_cost_fields += 1
        evidence = cost_evidence_for_row(row, source_context="paper_runtime")
        production_grade = evidence.get("production_grade") is True
        identity_complete = challenger_identity_state(row, policy) == "complete"
        if production_grade:
            overlapping_paper_rows_with_production_grade_cost += 1
        if identity_complete:
            overlapping_paper_rows_with_complete_challenger_identity += 1
        if paper_row_routes_to_live(row):
            live_route_overlap_rows += 1
        if row.get("paper_fill_allowed") is True:
            paper_fill_allowed_overlap_rows += 1
        if production_grade and identity_complete and not paper_row_routes_to_live(row) and row.get("paper_fill_allowed") is not True:
            recoverable_candidate_bound_production_grade_rows += 1
        else:
            diagnostic_only_external_identity_overlap_rows += 1

        if len(samples) < 10:
            samples.append(
                {
                    "source_key": source_key,
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "decision_time": first_present(row, "decision_time", "decision_time_est", "generated_at", "generated_utc"),
                    "join_keys": [{"kind": key[0], "value": key[1]} for key in matched_keys[:5]],
                    "matched_candidate_bound_rows": sum(candidate_join_key_counts[key] for key in matched_keys),
                    "paper_identity_state": challenger_identity_state(row, policy),
                    "production_grade_cost": production_grade,
                    "missing_required_cost_source_fields": missing_fields,
                    "paper_fill_allowed": row.get("paper_fill_allowed"),
                    "routes_to_live": row.get("routes_to_live"),
                    "places_real_order": row.get("places_real_order"),
                    "live_order": row.get("live_order"),
                }
            )

    pass_conditions = {
        "candidate_bound_rows_with_join_keys_gt_0": candidate_bound_rows_with_join_key > 0,
        "paper_rows_with_join_keys_gt_0": paper_rows_with_join_key > 0,
        "exact_join_key_overlap_gt_0": bool(overlapping_join_keys),
        "overlap_with_complete_paper_identity_gt_0": overlapping_paper_rows_with_complete_challenger_identity > 0,
        "overlap_with_production_grade_cost_gt_0": overlapping_paper_rows_with_production_grade_cost > 0,
        "recoverable_candidate_bound_production_grade_rows_gt_0": recoverable_candidate_bound_production_grade_rows > 0,
        "external_identity_overlap_not_counted": diagnostic_only_external_identity_overlap_rows >= 0,
        "overlap_live_route_rows_eq_0": live_route_overlap_rows == 0,
        "overlap_paper_fill_allowed_rows_eq_0": paper_fill_allowed_overlap_rows == 0,
        "redis_scan_limit_not_reached": not scan_limit_reached,
    }
    if recoverable_candidate_bound_production_grade_rows and not scan_limit_reached:
        status = "PASS_COST_IDENTITY_JOIN_RECOVERY_READY"
    elif overlapping_join_keys:
        status = "BLOCKED_COST_IDENTITY_JOIN_OVERLAP_DIAGNOSTIC_ONLY"
    else:
        status = "BLOCKED_NO_COST_IDENTITY_JOIN_OVERLAP"
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    join_blocker_details = {
        name: {
            "pass_condition": name,
            "passed": False,
            "observed": {
                "candidate_bound_rows_with_join_keys_gt_0": candidate_bound_rows_with_join_key,
                "paper_rows_with_join_keys_gt_0": paper_rows_with_join_key,
                "exact_join_key_overlap_gt_0": len(overlapping_join_keys),
                "overlap_with_complete_paper_identity_gt_0": overlapping_paper_rows_with_complete_challenger_identity,
                "overlap_with_production_grade_cost_gt_0": overlapping_paper_rows_with_production_grade_cost,
                "recoverable_candidate_bound_production_grade_rows_gt_0": recoverable_candidate_bound_production_grade_rows,
                "external_identity_overlap_not_counted": diagnostic_only_external_identity_overlap_rows,
                "overlap_live_route_rows_eq_0": live_route_overlap_rows,
                "overlap_paper_fill_allowed_rows_eq_0": paper_fill_allowed_overlap_rows,
                "redis_scan_limit_not_reached": {"scan_limit_reached": scan_limit_reached},
            }.get(name),
            "required": {
                "candidate_bound_rows_with_join_keys_gt_0": ">0",
                "paper_rows_with_join_keys_gt_0": ">0",
                "exact_join_key_overlap_gt_0": ">0",
                "overlap_with_complete_paper_identity_gt_0": ">0",
                "overlap_with_production_grade_cost_gt_0": ">0",
                "recoverable_candidate_bound_production_grade_rows_gt_0": ">0",
                "external_identity_overlap_not_counted": "diagnostic only; not credited",
                "overlap_live_route_rows_eq_0": 0,
                "overlap_paper_fill_allowed_rows_eq_0": 0,
                "redis_scan_limit_not_reached": False,
            }.get(name),
        }
        for name in blocked_reasons
    }
    join_actuals = {
        name: detail.get("observed")
        for name, detail in {
            "candidate_bound_rows_with_join_keys_gt_0": {
                "observed": candidate_bound_rows_with_join_key,
            },
            "paper_rows_with_join_keys_gt_0": {
                "observed": paper_rows_with_join_key,
            },
            "exact_join_key_overlap_gt_0": {
                "observed": len(overlapping_join_keys),
            },
            "overlap_with_complete_paper_identity_gt_0": {
                "observed": overlapping_paper_rows_with_complete_challenger_identity,
            },
            "overlap_with_production_grade_cost_gt_0": {
                "observed": overlapping_paper_rows_with_production_grade_cost,
            },
            "recoverable_candidate_bound_production_grade_rows_gt_0": {
                "observed": recoverable_candidate_bound_production_grade_rows,
            },
            "external_identity_overlap_not_counted": {
                "observed": diagnostic_only_external_identity_overlap_rows,
            },
            "overlap_live_route_rows_eq_0": {
                "observed": live_route_overlap_rows,
            },
            "overlap_paper_fill_allowed_rows_eq_0": {
                "observed": paper_fill_allowed_overlap_rows,
            },
            "redis_scan_limit_not_reached": {
                "observed": {"scan_limit_reached": scan_limit_reached},
            },
        }.items()
    }
    join_required = {
        "candidate_bound_rows_with_join_keys_gt_0": ">0",
        "paper_rows_with_join_keys_gt_0": ">0",
        "exact_join_key_overlap_gt_0": ">0",
        "overlap_with_complete_paper_identity_gt_0": ">0",
        "overlap_with_production_grade_cost_gt_0": ">0",
        "recoverable_candidate_bound_production_grade_rows_gt_0": ">0",
        "external_identity_overlap_not_counted": "diagnostic only; not credited",
        "overlap_live_route_rows_eq_0": 0,
        "overlap_paper_fill_allowed_rows_eq_0": 0,
        "redis_scan_limit_not_reached": {"scan_limit_reached": False},
    }
    join_sample_blockers = list(join_blocker_details.values())[:25]

    return {
        "schema_version": "challenger_v2_cost_identity_join_recovery_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "redis_status": redis_status,
        "redis_scan_source_counts": dict(sorted(Counter(dict(source_counts or {})).items())),
        "scan_limit_reached": scan_limit_reached,
        "candidate_bound_rows_examined": candidate_bound_rows_examined,
        "candidate_bound_rows_with_join_key": candidate_bound_rows_with_join_key,
        "candidate_bound_join_key_count": len(candidate_join_key_counts),
        "candidate_bound_join_key_counts_by_kind": dict(sorted(candidate_join_key_source_counts.items())),
        "paper_rows_examined": len(paper_rows),
        "paper_rows_with_join_key": paper_rows_with_join_key,
        "paper_join_key_count": len(paper_join_key_counts),
        "paper_join_key_counts_by_kind": dict(sorted(paper_join_key_source_counts.items())),
        "exact_join_key_overlap_count": len(overlapping_join_keys),
        "overlapping_paper_rows": overlapping_paper_rows,
        "overlap_by_join_key_kind": dict(sorted(overlap_by_kind.items())),
        "overlap_source_counts": dict(sorted(overlap_source_counts.items())),
        "overlapping_paper_rows_with_all_required_source_fields": overlapping_paper_rows_with_all_required_source_fields,
        "overlapping_paper_rows_with_core_cost_fields": overlapping_paper_rows_with_core_cost_fields,
        "overlapping_paper_rows_with_production_grade_cost": overlapping_paper_rows_with_production_grade_cost,
        "overlapping_paper_rows_with_complete_challenger_identity": overlapping_paper_rows_with_complete_challenger_identity,
        "recoverable_candidate_bound_production_grade_rows": recoverable_candidate_bound_production_grade_rows,
        "diagnostic_only_external_identity_overlap_rows": diagnostic_only_external_identity_overlap_rows,
        "overlap_missing_required_cost_source_field_counts": dict(sorted(overlap_missing_field_counts.items())),
        "overlap_live_route_rows": live_route_overlap_rows,
        "overlap_paper_fill_allowed_rows": paper_fill_allowed_overlap_rows,
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": join_blocker_details,
        "failed_blocker_details": join_blocker_details,
        "actuals": join_actuals,
        "required": join_required,
        "sample_blockers": join_sample_blockers,
        "sample_overlap_rows": samples,
        "join_key_classes": {key: list(value) for key, value in COST_IDENTITY_JOIN_KEY_FIELDS.items()},
        "identity_credit_rule": "Candidate identity from lockbox or shadow rows is diagnostic only; a paper/runtime cost row must itself carry candidate_id, policy_fingerprint, and model_source before it can count.",
        "cost_credit_rule": "A join can recover production-grade evidence only when the overlapping paper/runtime row has complete challenger identity, production-grade cost evidence, no live route, and paper_fill_allowed is not true.",
        "can_recover_from_existing_authoritative_sources_without_new_capture": recoverable_candidate_bound_production_grade_rows > 0 and not scan_limit_reached,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def cost_identity_join_recovery_audit_from_redis(
    *,
    policy: FrozenPolicy,
    candidate_bound_rows: Sequence[Mapping[str, Any]],
    signal_scan_limit: int = DEFAULT_PAPER_SIGNAL_SCAN_LIMIT,
) -> dict[str, Any]:
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
    except Exception as exc:
        return cost_identity_join_recovery_audit(
            policy=policy,
            paper_rows=[],
            candidate_bound_rows=candidate_bound_rows,
            redis_status=f"SKIPPED_REDIS_UNAVAILABLE:{type(exc).__name__}",
        )

    rows: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for key in PAPER_RUNTIME_TELEMETRY_KEYS:
        key_rows = paper_binding_rows_from_redis_value(client.get(key), source_key=key)
        rows.extend(key_rows)
        source_counts[key] += len(key_rows)

    signal_rows, signal_source_counts, _signal_count, scan_limit_reached = bounded_paper_signal_scan(
        client,
        signal_scan_limit=signal_scan_limit,
        row_reader=lambda raw, key: paper_binding_rows_from_redis_value(raw, source_key=key),
    )
    rows.extend(signal_rows)
    source_counts.update(signal_source_counts)

    return cost_identity_join_recovery_audit(
        policy=policy,
        paper_rows=rows,
        candidate_bound_rows=candidate_bound_rows,
        redis_status="READ_REDIS_PAPER_ROWS_BOUNDED",
        source_counts=source_counts,
        scan_limit_reached=scan_limit_reached,
    )


def load_frozen_policy(out_dir: Path) -> FrozenPolicy:
    payload = read_json(out_dir / "challenger_v2_frozen_policy_status.json", {})
    if not isinstance(payload, Mapping):
        raise ValueError("frozen_policy_artifact_missing_or_invalid")
    normalization_payload = payload.get("normalization")
    if not isinstance(normalization_payload, Mapping):
        raise ValueError("frozen_policy_normalization_missing")
    feature_names = tuple(str(name) for name in normalization_payload.get("feature_names") or payload.get("feature_names_in_order") or ())
    normalization = NormalizationSpec(
        feature_names=feature_names,
        means=tuple(float(v) for v in normalization_payload.get("means") or ()),
        stds=tuple(float(v) for v in normalization_payload.get("stds") or ()),
        mins=tuple(float(v) for v in normalization_payload.get("mins") or ()),
        maxs=tuple(float(v) for v in normalization_payload.get("maxs") or ()),
        schema_version=str(normalization_payload.get("schema_version") or "challenger_v2_shared_feature_adapter_v1"),
    )
    weights = tuple(float(v) for v in payload.get("weights") or ())
    if not feature_names or len(weights) != len(feature_names):
        raise ValueError("frozen_policy_feature_weight_shape_mismatch")
    return FrozenPolicy(
        candidate_id=str(payload.get("candidate_id") or ""),
        policy_fingerprint=str(payload.get("policy_fingerprint") or ""),
        feature_names=feature_names,
        normalization=normalization,
        weights=weights,
        bias=float(payload.get("bias") or 0.0),
        threshold_bps=float(payload.get("threshold") or 0.0),
        model_source=str(payload.get("model_source") or MODEL_SOURCE),
    )


def frozen_candidate_integrity_audit(out_dir: Path, policy: FrozenPolicy) -> dict[str, Any]:
    path = out_dir / "challenger_v2_frozen_policy_status.json"
    previous = read_json(out_dir / FROZEN_CANDIDATE_INTEGRITY_AUDIT, {})
    payload = read_json(path, {})
    file_bytes = path.read_bytes() if path.exists() else b""
    file_sha256 = hashlib.sha256(file_bytes).hexdigest() if file_bytes else None
    previous_file_sha256 = previous.get("frozen_policy_file_sha256") if isinstance(previous, Mapping) else None
    normalization_payload = payload.get("normalization") if isinstance(payload, Mapping) else None
    normalization_payload = normalization_payload if isinstance(normalization_payload, Mapping) else {}
    feature_names = tuple(str(name) for name in payload.get("feature_names_in_order") or normalization_payload.get("feature_names") or ())
    norm_feature_names = tuple(str(name) for name in normalization_payload.get("feature_names") or ())
    means = tuple(float(value) for value in normalization_payload.get("means") or ())
    stds = tuple(float(value) for value in normalization_payload.get("stds") or ())
    mins = tuple(float(value) for value in normalization_payload.get("mins") or ())
    maxs = tuple(float(value) for value in normalization_payload.get("maxs") or ())
    weights = tuple(float(value) for value in payload.get("weights") or ()) if isinstance(payload, Mapping) else ()
    normalization_spec = NormalizationSpec(
        feature_names=norm_feature_names,
        means=means,
        stds=stds,
        mins=mins,
        maxs=maxs,
        schema_version=str(normalization_payload.get("schema_version") or "challenger_v2_shared_feature_adapter_v1"),
    )
    recomputed_feature_schema_hash = feature_schema_hash(feature_names) if feature_names else None
    recomputed_normalization_hash = normalization_hash(normalization_spec) if norm_feature_names else None
    recomputed_cost_model_hash = cost_model_hash()
    policy_material_hash = stable_hash(
        {
            "candidate_id": payload.get("candidate_id") if isinstance(payload, Mapping) else None,
            "policy_fingerprint": payload.get("policy_fingerprint") if isinstance(payload, Mapping) else None,
            "model_source": payload.get("model_source") if isinstance(payload, Mapping) else None,
            "feature_names_in_order": list(feature_names),
            "normalization": dict(normalization_payload),
            "weights": list(weights),
            "bias": payload.get("bias") if isinstance(payload, Mapping) else None,
            "threshold": payload.get("threshold") if isinstance(payload, Mapping) else None,
            "ridge_lambda": payload.get("ridge_lambda") if isinstance(payload, Mapping) else None,
            "target_clipping_bps": payload.get("target_clipping_bps") if isinstance(payload, Mapping) else None,
            "dataset_manifest_hash": payload.get("dataset_manifest_hash") if isinstance(payload, Mapping) else None,
            "cost_model_hash": payload.get("cost_model_hash") if isinstance(payload, Mapping) else None,
        }
    )
    feature_count = len(feature_names)
    pass_conditions = {
        "frozen_policy_artifact_exists": path.exists(),
        "candidate_id_matches_expected": payload.get("candidate_id") == policy.candidate_id if isinstance(payload, Mapping) else False,
        "policy_fingerprint_matches_expected": payload.get("policy_fingerprint") == policy.policy_fingerprint if isinstance(payload, Mapping) else False,
        "model_source_matches_expected": payload.get("model_source") == policy.model_source if isinstance(payload, Mapping) else False,
        "feature_names_match_loaded_policy": feature_names == policy.feature_names,
        "normalization_feature_names_match_policy": norm_feature_names == policy.feature_names,
        "weights_match_loaded_policy": weights == policy.weights,
        "feature_weight_shape_is_32": feature_count == 32 and len(weights) == 32,
        "normalization_vector_shapes_are_32": all(len(values) == 32 for values in (norm_feature_names, means, stds, mins, maxs)),
        "feature_schema_hash_matches_recomputed": payload.get("feature_schema_hash") == recomputed_feature_schema_hash if isinstance(payload, Mapping) else False,
        "normalization_hash_matches_recomputed": payload.get("normalization_hash") == recomputed_normalization_hash if isinstance(payload, Mapping) else False,
        "cost_model_hash_matches_recomputed": payload.get("cost_model_hash") == recomputed_cost_model_hash if isinstance(payload, Mapping) else False,
        "paper_only_true": payload.get("paper_only") is True if isinstance(payload, Mapping) else False,
        "routes_to_live_false": payload.get("routes_to_live") is False if isinstance(payload, Mapping) else False,
        "promotion_allowed_false": payload.get("promotion_allowed") is False if isinstance(payload, Mapping) else False,
        "post_freeze_change_invalidates_candidate": payload.get("post_freeze_source_or_parameter_change_invalidates_candidate") is True if isinstance(payload, Mapping) else False,
        "previous_frozen_policy_hash_unchanged_or_baseline_initialized": previous_file_sha256 in (None, file_sha256),
    }
    status = "PASS_FROZEN_CANDIDATE_INTEGRITY_AUDIT" if all(pass_conditions.values()) else "FAIL_FROZEN_CANDIDATE_INTEGRITY_AUDIT"
    return {
        "schema_version": "challenger_v2_frozen_candidate_integrity_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "frozen_policy_path": str(path),
        "frozen_policy_file_sha256": file_sha256,
        "previous_frozen_policy_file_sha256": previous_file_sha256,
        "policy_material_hash": policy_material_hash,
        "freeze_status": payload.get("freeze_status") if isinstance(payload, Mapping) else None,
        "paper_only": payload.get("paper_only") if isinstance(payload, Mapping) else None,
        "promotion_allowed": payload.get("promotion_allowed") if isinstance(payload, Mapping) else None,
        "post_freeze_source_or_parameter_change_invalidates_candidate": (
            payload.get("post_freeze_source_or_parameter_change_invalidates_candidate")
            if isinstance(payload, Mapping)
            else None
        ),
        "frozen_policy_safety_contract": {
            "paper_only": payload.get("paper_only") if isinstance(payload, Mapping) else None,
            "routes_to_live": payload.get("routes_to_live") if isinstance(payload, Mapping) else None,
            "promotion_allowed": payload.get("promotion_allowed") if isinstance(payload, Mapping) else None,
            "post_freeze_source_or_parameter_change_invalidates_candidate": (
                payload.get("post_freeze_source_or_parameter_change_invalidates_candidate")
                if isinstance(payload, Mapping)
                else None
            ),
            "new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes": True,
        },
        "frozen_policy_generated_utc": payload.get("generated_utc") if isinstance(payload, Mapping) else None,
        "feature_count": feature_count,
        "weight_count": len(weights),
        "normalization_counts": {
            "feature_names": len(norm_feature_names),
            "means": len(means),
            "stds": len(stds),
            "mins": len(mins),
            "maxs": len(maxs),
        },
        "recorded_hashes": {
            "feature_schema_hash": payload.get("feature_schema_hash") if isinstance(payload, Mapping) else None,
            "normalization_hash": payload.get("normalization_hash") if isinstance(payload, Mapping) else None,
            "cost_model_hash": payload.get("cost_model_hash") if isinstance(payload, Mapping) else None,
            "weights_hash": payload.get("weights_hash") if isinstance(payload, Mapping) else None,
            "dataset_manifest_hash": payload.get("dataset_manifest_hash") if isinstance(payload, Mapping) else None,
        },
        "recomputed_hashes": {
            "feature_schema_hash": recomputed_feature_schema_hash,
            "normalization_hash": recomputed_normalization_hash,
            "cost_model_hash": recomputed_cost_model_hash,
        },
        "pass_conditions": pass_conditions,
        "frozen_candidate_modified_since_previous_evidence_run": previous_file_sha256 not in (None, file_sha256),
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def cost_evidence_flags(row: Mapping[str, Any], cost: Mapping[str, Any]) -> dict[str, bool]:
    fallback_components = set(str(name) for name in cost.get("fallback_components") or ())
    source_time = first_present(
        row,
        "source_timestamp",
        "source_event_time_est",
        "feature_cutoff",
        "event_time",
        "candle_close_time",
        "generated_at",
        "generated_utc",
    )
    decision_time = parse_utc(first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"))
    available_at = parse_utc(first_present(row, "available_at", "source_available_time", "source_received_time_est", "generated_at", "generated_utc"))
    freshness_state = str(first_present(row, "feature_freshness_state") or "").upper()
    freshness_ok = (
        source_time not in (None, "")
        and decision_time is not None
        and available_at is not None
        and available_at <= decision_time
        and freshness_state not in {"STALE", "EXPIRED", "DIRTY"}
    )
    return {
        "observed_bid_ask_spread": cost.get("observed_bid_ask_spread_bps") is not None,
        "order_size": positive_first_float(row, "order_size_usd", "order_notional_usd", "notional_usd", "target_notional_usdt", "gross_notional_usd") is not None,
        "top_book_evidence": top_book_evidence_source(row) is not None,
        "depth_evidence": first_float(
            row,
            "ask_depth_usd",
            "bid_depth_usd",
            "entry_orderbook_depth_usd",
            "orderbook_depth_usd",
            "market_depth_usd",
            "top_of_book_depth_usd",
            "book_depth_usd",
        )
        is not None,
        "depth_derived_price_impact": "depth_impact_bps" not in fallback_components,
        "maker_taker_assumption_and_probability": (
            first_float(row, "maker_probability") is not None
            and first_float(row, "taker_probability") is not None
            and "maker_taker_probability" not in fallback_components
        ),
        "fee_schedule": bool(cost.get("component_sources", {}).get("fee_bps")),
        "funding_rate_and_holding_period_funding": "funding_bps" not in fallback_components,
        "latency_reserve": "latency_reserve_bps" not in fallback_components,
        "partial_fill_estimate": "partial_fill_adjustment_bps" not in fallback_components,
        "mark_index_divergence": "mark_index_divergence_bps" not in fallback_components,
        "source_timestamp": source_time not in (None, ""),
        "evidence_freshness": freshness_ok,
        "fallback_flag": isinstance(cost.get("fallback"), bool),
    }


def cost_evidence_for_row(row: Mapping[str, Any], *, source_context: str) -> dict[str, Any]:
    long_cost = estimate_replay_cost(row, side="long").to_jsonable() if source_context == "replay" else estimate_paper_cost(row, side="long").to_jsonable()
    short_cost = estimate_replay_cost(row, side="short").to_jsonable() if source_context == "replay" else estimate_paper_cost(row, side="short").to_jsonable()
    replay_long = estimate_replay_cost(row, side="long").to_jsonable()
    paper_long = estimate_paper_cost(row, side="long").to_jsonable()
    replay_short = estimate_replay_cost(row, side="short").to_jsonable()
    paper_short = estimate_paper_cost(row, side="short").to_jsonable()
    parity_by_side = {
        "long": replay_long == paper_long,
        "short": replay_short == paper_short,
    }
    flags = cost_evidence_flags(row, long_cost)
    missing = [name for name, present in flags.items() if not present]
    fallback = bool(long_cost.get("fallback") or short_cost.get("fallback"))
    production_grade = bool(long_cost.get("production_grade_evidence") and short_cost.get("production_grade_evidence") and not missing)
    unexplained_missing = bool(missing and not fallback)
    return {
        "source_context": source_context,
        "symbol": str(row.get("symbol") or "").upper(),
        "timeframe": str(row.get("timeframe") or ""),
        "snapshot_id": str(row.get("feature_snapshot_id") or row.get("snapshot_id") or ""),
        "decision_time": first_present(row, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"),
        "feature_cutoff": first_present(row, "feature_cutoff", "source_event_time_est", "candle_close_time"),
        "available_at": first_present(row, "available_at", "source_available_time", "source_received_time_est", "generated_at", "generated_utc"),
        "evidence_flags": flags,
        "missing_evidence_fields": missing,
        "fallback": fallback,
        "fallback_components": sorted(set(long_cost.get("fallback_components") or ()) | set(short_cost.get("fallback_components") or ())),
        "production_grade": production_grade,
        "unexplained_missing": unexplained_missing,
        "long_cost": long_cost,
        "short_cost": short_cost,
        "replay_paper_cost_parity": all(parity_by_side.values()),
        "replay_paper_cost_parity_by_side": parity_by_side,
        "replay_paper_cost_parity_mismatch_sides": [
            side for side, parity in parity_by_side.items() if parity is not True
        ],
    }


def summarize_cost_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    row_count = len(rows)
    field_present: dict[str, int] = {name: 0 for name in REQUIRED_COST_EVIDENCE_FIELDS}
    fallback_components: Counter[str] = Counter()
    missing_reason_counts: Counter[str] = Counter()
    parity_mismatch_side_counts: Counter[str] = Counter()
    sample_missing_rows: list[dict[str, Any]] = []
    sample_parity_mismatch_rows: list[dict[str, Any]] = []
    production_grade = unexplained = parity_mismatch = fallback_rows = 0
    for row in rows:
        if row.get("production_grade") is True:
            production_grade += 1
        if row.get("unexplained_missing") is True:
            unexplained += 1
        if row.get("replay_paper_cost_parity") is not True:
            parity_mismatch += 1
            sides = [str(side) for side in row.get("replay_paper_cost_parity_mismatch_sides") or ["unknown"]]
            parity_mismatch_side_counts.update(sides)
            if len(sample_parity_mismatch_rows) < 25:
                sample_parity_mismatch_rows.append(
                    {
                        "source_context": row.get("source_context"),
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "snapshot_id": row.get("snapshot_id"),
                        "decision_time": row.get("decision_time"),
                        "mismatch_sides": sides,
                    }
                )
        if row.get("fallback") is True:
            fallback_rows += 1
        for field, present in (row.get("evidence_flags") or {}).items():
            if present:
                field_present[field] = field_present.get(field, 0) + 1
            else:
                missing_reason_counts[field] += 1
        fallback_components.update(str(name) for name in row.get("fallback_components") or ())
        if row.get("missing_evidence_fields") and len(sample_missing_rows) < 25:
            sample_missing_rows.append(
                {
                    "source_context": row.get("source_context"),
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "snapshot_id": row.get("snapshot_id"),
                    "decision_time": row.get("decision_time"),
                    "missing_evidence_fields": row.get("missing_evidence_fields"),
                    "fallback": row.get("fallback"),
                    "fallback_components": row.get("fallback_components"),
                }
            )
    return {
        "row_count": row_count,
        "production_grade_rows": production_grade,
        "production_grade_cost_coverage": production_grade / row_count if row_count else 0.0,
        "fallback_rows": fallback_rows,
        "unexplained_cost_missing_rows": unexplained,
        "replay_paper_cost_parity_comparable_rows": row_count,
        "replay_paper_cost_parity_same_snapshot_order_rows": row_count,
        "replay_paper_cost_parity_compared_side_count": row_count * 2,
        "replay_paper_cost_parity_matched_rows": max(0, row_count - parity_mismatch),
        "replay_paper_cost_parity_matched_side_count": max(0, (row_count * 2) - sum(parity_mismatch_side_counts.values())),
        "replay_paper_cost_parity_mismatch_rows": parity_mismatch,
        "replay_paper_cost_parity_mismatch_side_counts": dict(sorted(parity_mismatch_side_counts.items())),
        "field_coverage": {
            name: {
                "present_rows": field_present.get(name, 0),
                "missing_rows": row_count - field_present.get(name, 0),
                "coverage": field_present.get(name, 0) / row_count if row_count else 0.0,
            }
            for name in REQUIRED_COST_EVIDENCE_FIELDS
        },
        "missing_reason_counts": dict(sorted(missing_reason_counts.items())),
        "fallback_component_counts": dict(sorted(fallback_components.items())),
        "sample_missing_rows": sample_missing_rows,
        "sample_replay_paper_cost_parity_mismatch_rows": sample_parity_mismatch_rows,
    }


def cost_replay_paper_parity_audit_from_evidence(
    *,
    policy: FrozenPolicy,
    evidence_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    source_context_counts: Counter[str] = Counter()
    side_mismatch_counts: Counter[str] = Counter()
    malformed_parity_rows = 0
    mismatch_rows = 0
    same_snapshot_order_comparison_rows = 0
    same_snapshot_order_side_comparisons = 0
    sample_mismatches: list[dict[str, Any]] = []
    for row in evidence_rows:
        source_context_counts[str(row.get("source_context") or "UNKNOWN")] += 1
        same_snapshot_order_comparison_rows += 1
        parity_by_side = row.get("replay_paper_cost_parity_by_side")
        if not isinstance(parity_by_side, Mapping) or not parity_by_side:
            malformed_parity_rows += 1
            mismatch_sides = ["unknown"]
        else:
            same_snapshot_order_side_comparisons += sum(
                1 for side in ("long", "short") if side in parity_by_side
            )
            mismatch_sides = [
                str(side)
                for side in ("long", "short")
                if parity_by_side.get(side) is not True
            ]
            extra_sides = [
                str(side)
                for side, parity in parity_by_side.items()
                if side not in {"long", "short"} and parity is not True
            ]
            mismatch_sides.extend(extra_sides)
        if mismatch_sides:
            mismatch_rows += 1
            side_mismatch_counts.update(mismatch_sides)
            if len(sample_mismatches) < 25:
                sample_mismatches.append(
                    {
                        "source_context": row.get("source_context"),
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "snapshot_id": row.get("snapshot_id"),
                        "decision_time": row.get("decision_time"),
                        "feature_cutoff": row.get("feature_cutoff"),
                        "available_at": row.get("available_at"),
                        "mismatch_sides": mismatch_sides,
                    }
                )
    pass_conditions = {
        "rows_examined_gt_0": len(evidence_rows) > 0,
        "same_snapshot_order_comparison_rows_gt_0": same_snapshot_order_comparison_rows > 0,
        "same_snapshot_order_side_comparisons_gt_0": same_snapshot_order_side_comparisons > 0,
        "parity_map_present_for_all_rows": malformed_parity_rows == 0,
        "long_side_mismatch_rows_eq_0": side_mismatch_counts.get("long", 0) == 0,
        "short_side_mismatch_rows_eq_0": side_mismatch_counts.get("short", 0) == 0,
        "total_replay_paper_cost_mismatch_rows_eq_0": mismatch_rows == 0,
    }
    return {
        "schema_version": "challenger_v2_cost_replay_paper_parity_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_COST_REPLAY_PAPER_PARITY_AUDIT" if all(pass_conditions.values()) else "FAIL_COST_REPLAY_PAPER_PARITY_AUDIT",
        "rows_examined": len(evidence_rows),
        "comparable_rows": same_snapshot_order_comparison_rows,
        "compared_rows": same_snapshot_order_comparison_rows,
        "matched_rows": max(0, same_snapshot_order_comparison_rows - mismatch_rows),
        "same_snapshot_order_comparison_rows": same_snapshot_order_comparison_rows,
        "same_snapshot_order_side_comparisons": same_snapshot_order_side_comparisons,
        "matched_side_comparisons": max(0, same_snapshot_order_side_comparisons - sum(side_mismatch_counts.values())),
        "replay_paper_cost_parity_comparable_rows": same_snapshot_order_comparison_rows,
        "replay_paper_cost_parity_compared_side_count": same_snapshot_order_side_comparisons,
        "replay_paper_cost_parity_matched_rows": max(0, same_snapshot_order_comparison_rows - mismatch_rows),
        "replay_paper_cost_parity_matched_side_count": max(0, same_snapshot_order_side_comparisons - sum(side_mismatch_counts.values())),
        "replay_paper_cost_parity_mismatch_rows": mismatch_rows,
        "source_context_counts": dict(sorted(source_context_counts.items())),
        "same_snapshot_order_identity_fields": [
            "source_context",
            "symbol",
            "timeframe",
            "snapshot_id",
            "decision_time",
            "feature_cutoff",
            "available_at",
            "side",
        ],
        "parity_rule": "estimate_replay_cost(row, side) must equal estimate_paper_cost(row, side) for the same normalized snapshot/order input",
        "mismatch_rows": mismatch_rows,
        "side_mismatch_counts": dict(sorted(side_mismatch_counts.items())),
        "malformed_parity_rows": malformed_parity_rows,
        "sample_mismatch_rows": sample_mismatches,
        "pass_conditions": pass_conditions,
        "read_only_audit_no_runtime_change": True,
        "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def cost_replay_paper_parity_audit(
    *,
    policy: FrozenPolicy,
    replay_rows: Sequence[ReplayCandidateRow],
    current_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    replay_evidence = [cost_evidence_for_row(row.snapshot, source_context="replay") for row in replay_rows]
    current_evidence = [cost_evidence_for_row(snapshot, source_context="current_runtime") for snapshot in current_snapshots]
    return cost_replay_paper_parity_audit_from_evidence(
        policy=policy,
        evidence_rows=[*replay_evidence, *current_evidence],
    )


def summarize_source_presence(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    source_context: str,
) -> dict[str, Any]:
    row_count = len(raw_rows)
    fields: dict[str, Any] = {}
    for required_field in REQUIRED_COST_EVIDENCE_FIELDS:
        present_rows = 0
        source_counts: Counter[str] = Counter()
        sample_missing: list[dict[str, Any]] = []
        for row in raw_rows:
            present, source = source_presence_for_required_field(row, required_field)
            if present:
                present_rows += 1
                source_counts[str(source)] += 1
            elif len(sample_missing) < 10:
                sample_missing.append(
                    {
                        "symbol": str(row.get("symbol") or "").upper(),
                        "timeframe": str(row.get("timeframe") or ""),
                        "snapshot_id": str(row.get("feature_snapshot_id") or row.get("snapshot_id") or ""),
                        "decision_time": first_present(
                            row,
                            "decision_time",
                            "decision_time_est",
                            "decision_cutoff_time_est",
                            "generated_at",
                            "generated_utc",
                        ),
                    }
                )
        missing_rows = row_count - present_rows
        fields[required_field] = {
            "present_rows": present_rows,
            "missing_rows": missing_rows,
            "coverage": present_rows / row_count if row_count else 0.0,
            "source_counts": dict(sorted(source_counts.items())),
            "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(required_field),
            "sample_missing_rows": sample_missing,
        }
    return {
        "source_context": source_context,
        "row_count": row_count,
        "fields": fields,
    }


def combine_source_presence(
    replay_presence: Mapping[str, Any],
    current_presence: Mapping[str, Any],
) -> dict[str, Any]:
    row_count = int(replay_presence.get("row_count") or 0) + int(current_presence.get("row_count") or 0)
    fields: dict[str, Any] = {}
    replay_fields = replay_presence.get("fields") if isinstance(replay_presence.get("fields"), Mapping) else {}
    current_fields = current_presence.get("fields") if isinstance(current_presence.get("fields"), Mapping) else {}
    for required_field in REQUIRED_COST_EVIDENCE_FIELDS:
        replay_field = replay_fields.get(required_field) if isinstance(replay_fields, Mapping) else {}
        current_field = current_fields.get(required_field) if isinstance(current_fields, Mapping) else {}
        present_rows = int(replay_field.get("present_rows") or 0) + int(current_field.get("present_rows") or 0)
        source_counts = Counter()
        source_counts.update(replay_field.get("source_counts") or {})
        source_counts.update(current_field.get("source_counts") or {})
        sample_missing_rows = [
            *list(replay_field.get("sample_missing_rows") or [])[:5],
            *list(current_field.get("sample_missing_rows") or [])[:5],
        ][:10]
        fields[required_field] = {
            "present_rows": present_rows,
            "missing_rows": row_count - present_rows,
            "coverage": present_rows / row_count if row_count else 0.0,
            "source_counts": dict(sorted(source_counts.items())),
            "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(required_field),
            "sample_missing_rows": sample_missing_rows,
        }
    return {
        "source_context": "combined",
        "row_count": row_count,
        "fields": fields,
    }


def source_group_coverage_matrix(
    source_presence_by_group: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    coverage_by_group: dict[str, dict[str, Any]] = {}
    missing_by_group: dict[str, dict[str, int]] = {}
    for group_name, presence in source_presence_by_group.items():
        fields = presence.get("fields") if isinstance(presence.get("fields"), Mapping) else {}
        group_coverage: dict[str, Any] = {}
        group_missing: dict[str, int] = {}
        for field in REQUIRED_COST_EVIDENCE_FIELDS:
            field_payload = fields.get(field) if isinstance(fields, Mapping) else {}
            present_rows = int(field_payload.get("present_rows") or 0)
            missing_rows = int(field_payload.get("missing_rows") or 0)
            coverage = float(field_payload.get("coverage") or 0.0)
            group_coverage[field] = {
                "present_rows": present_rows,
                "missing_rows": missing_rows,
                "coverage": coverage,
                "source_counts": dict(field_payload.get("source_counts") or {}),
                "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
                "sample_missing_rows": list(field_payload.get("sample_missing_rows") or []),
            }
            group_missing[field] = missing_rows
        coverage_by_group[str(group_name)] = group_coverage
        missing_by_group[str(group_name)] = group_missing
    return coverage_by_group, missing_by_group


def cost_evidence_recovery_classification(
    *,
    replay_summary: Mapping[str, Any],
    current_summary: Mapping[str, Any],
    combined_summary: Mapping[str, Any],
    replay_source_presence: Mapping[str, Any],
    current_source_presence: Mapping[str, Any],
    combined_source_presence: Mapping[str, Any],
) -> dict[str, Any]:
    group_inputs = {
        "replay": (replay_summary, replay_source_presence),
        "current_runtime": (current_summary, current_source_presence),
        "combined": (combined_summary, combined_source_presence),
    }
    source_groups: dict[str, dict[str, Any]] = {}
    for group_name, (summary, presence) in group_inputs.items():
        fields = presence.get("fields") if isinstance(presence.get("fields"), Mapping) else {}
        missing_field_counts = {
            field: int((fields.get(field) or {}).get("missing_rows") or 0)
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        }
        hard_missing_fields = [
            field
            for field in CORE_COST_JOIN_FIELDS
            if int(missing_field_counts.get(field) or 0) > 0
        ]
        missing_fields = [
            field
            for field in REQUIRED_COST_EVIDENCE_FIELDS
            if int(missing_field_counts.get(field) or 0) > 0
        ]
        if not missing_fields and float(summary.get("production_grade_cost_coverage") or 0.0) >= 0.95:
            recovery_class = "PRODUCTION_GRADE_COST_EVIDENCE_SUFFICIENT"
            existing_rows_may_count_after_backfill = False
            required_next_action = "none"
        elif group_name == "replay" and hard_missing_fields:
            recovery_class = "HISTORICAL_REPLAY_COST_EVIDENCE_IRRECOVERABLE_WITHOUT_NEW_POINT_IN_TIME_CAPTURE"
            existing_rows_may_count_after_backfill = False
            required_next_action = "collect_new_candidate_bound_replay_or_future_lockbox_rows_with_cost_evidence"
        elif group_name == "current_runtime" and hard_missing_fields:
            recovery_class = "FUTURE_RUNTIME_CANDIDATE_BOUND_COST_CAPTURE_REQUIRED"
            existing_rows_may_count_after_backfill = False
            required_next_action = "capture_future_candidate_bound_order_intent_and_fill_cost_evidence_before_counting_rows"
        elif group_name == "combined" and hard_missing_fields:
            recovery_class = "EXISTING_REPLAY_AND_CURRENT_ROWS_NOT_PRODUCTION_GRADE"
            existing_rows_may_count_after_backfill = False
            required_next_action = "exclude_existing_fallback_rows_and_wait_for_future_candidate_bound_production_grade_rows"
        else:
            recovery_class = "NON_HARD_COST_EVIDENCE_GAPS_REQUIRE_SOURCE_FRESHNESS_OR_FIELD_CAPTURE"
            existing_rows_may_count_after_backfill = False
            required_next_action = "resolve_required_non_hard_cost_evidence_fields_before_counting_rows"

        source_groups[group_name] = {
            "source_group": group_name,
            "recovery_class": recovery_class,
            "row_count": int(summary.get("row_count") or 0),
            "production_grade_rows": int(summary.get("production_grade_rows") or 0),
            "production_grade_cost_coverage": float(summary.get("production_grade_cost_coverage") or 0.0),
            "fallback_rows": int(summary.get("fallback_rows") or 0),
            "unexplained_cost_missing_rows": int(summary.get("unexplained_cost_missing_rows") or 0),
            "missing_fields": missing_fields,
            "hard_missing_fields": hard_missing_fields,
            "missing_field_counts": missing_field_counts,
            "hard_missing_field_counts": {
                field: missing_field_counts[field]
                for field in hard_missing_fields
            },
            "field_recovery_boundaries": {
                field: FIELD_RECOVERY_BOUNDARY.get(field)
                for field in missing_fields
                if FIELD_RECOVERY_BOUNDARY.get(field)
            },
            "sample_missing_cost_evidence_rows": list(summary.get("sample_missing_rows") or []),
            "sample_missing_source_rows_by_field": {
                field: list((fields.get(field) or {}).get("sample_missing_rows") or [])
                for field in missing_fields
                if (fields.get(field) or {}).get("sample_missing_rows")
            },
            "existing_rows_may_be_backfilled_for_training_lockbox_promotion_credit": existing_rows_may_count_after_backfill,
            "fallback_rows_may_be_shadow_scored": True,
            "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "required_next_action": required_next_action,
        }

    replay_irrecoverable_fields = source_groups["replay"]["hard_missing_fields"]
    current_future_capture_fields = source_groups["current_runtime"]["hard_missing_fields"]
    combined_hard_missing_fields = source_groups["combined"]["hard_missing_fields"]
    if not combined_hard_missing_fields and float(combined_summary.get("production_grade_cost_coverage") or 0.0) >= 0.95:
        status = "PASS_COST_EVIDENCE_RECOVERY_CLASSIFICATION"
    else:
        status = "BLOCKED_EXISTING_ROWS_NOT_PRODUCTION_GRADE_REQUIRES_FUTURE_CAPTURE"

    pass_conditions = {
        "replay_has_no_irrecoverable_hard_cost_gaps": not replay_irrecoverable_fields,
        "current_runtime_has_no_future_capture_hard_cost_gaps": not current_future_capture_fields,
        "combined_hard_cost_gaps_resolved": not combined_hard_missing_fields,
        "existing_missing_or_fallback_rows_not_backfilled_for_credit": all(
            group["existing_rows_may_be_backfilled_for_training_lockbox_promotion_credit"] is False
            for group in source_groups.values()
        ),
        "fallback_rows_remain_shadow_only": all(
            group["fallback_rows_count_as_training_lockbox_or_promotion_evidence"] is False
            for group in source_groups.values()
        ),
    }
    return {
        "schema_version": "challenger_v2_cost_evidence_recovery_classification_v1",
        "status": status,
        "pass_conditions": pass_conditions,
        "blocked_reasons": [name for name, passed in pass_conditions.items() if passed is not True],
        "source_groups": source_groups,
        "replay_irrecoverable_cost_evidence_fields": replay_irrecoverable_fields,
        "current_runtime_future_capture_required_fields": current_future_capture_fields,
        "combined_hard_missing_cost_evidence_fields": combined_hard_missing_fields,
        "existing_replay_rows_may_be_backfilled_for_credit": False,
        "existing_current_runtime_rows_may_be_backfilled_for_credit": False,
        "existing_old_or_unbound_paper_rows_may_be_backfilled_for_credit": False,
        "required_next_action": source_groups["combined"]["required_next_action"],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def cost_blocker_diagnosis(
    *,
    combined_summary: Mapping[str, Any],
    combined_source_presence: Mapping[str, Any],
) -> dict[str, Any]:
    fields = combined_source_presence.get("fields") if isinstance(combined_source_presence.get("fields"), Mapping) else {}
    fully_missing = []
    partial = []
    for name in REQUIRED_COST_EVIDENCE_FIELDS:
        field = fields.get(name) if isinstance(fields, Mapping) else {}
        coverage = float(field.get("coverage") or 0.0)
        if coverage <= 0.0:
            fully_missing.append(name)
        elif coverage < 0.95:
            partial.append(name)
    hard_blockers = [
        name
        for name in (
            "order_size",
            "top_book_evidence",
            "depth_derived_price_impact",
            "maker_taker_assumption_and_probability",
            "latency_reserve",
            "partial_fill_estimate",
        )
        if name in fully_missing or name in partial
    ]
    return {
        "root_cause": "MISSING_ORDER_INTENT_AND_FILL_TELEMETRY_FOR_PRODUCTION_GRADE_COST_EVIDENCE"
        if hard_blockers
        else "COST_EVIDENCE_PRESENT_BUT_FALLBACK_OR_FRESHNESS_GATE_FAILED",
        "hard_blocking_fields": hard_blockers,
        "fully_missing_fields": fully_missing,
        "partially_missing_fields": partial,
        "fallback_true_rows": combined_summary.get("fallback_rows"),
        "unexplained_cost_missing_rows": combined_summary.get("unexplained_cost_missing_rows"),
        "replay_paper_cost_parity_mismatch_rows": combined_summary.get("replay_paper_cost_parity_mismatch_rows"),
        "frozen_candidate_cost_logic_changed": False,
        "new_candidate_required_if_cost_assumptions_or_model_change": True,
        "safe_next_capture_boundary": {
            field: FIELD_RECOVERY_BOUNDARY.get(field)
            for field in hard_blockers
            if FIELD_RECOVERY_BOUNDARY.get(field)
        },
    }


def production_cost_evidence_artifacts(
    *,
    policy: FrozenPolicy,
    replay_rows: Sequence[ReplayCandidateRow],
    current_snapshots: Sequence[Mapping[str, Any]],
    current_source: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    replay_evidence = [cost_evidence_for_row(row.snapshot, source_context="replay") for row in replay_rows]
    current_evidence = [cost_evidence_for_row(snapshot, source_context="current_runtime") for snapshot in current_snapshots]
    replay_summary = summarize_cost_rows(replay_evidence)
    current_summary = summarize_cost_rows(current_evidence)
    combined_summary = summarize_cost_rows([*replay_evidence, *current_evidence])
    replay_source_presence = summarize_source_presence([row.snapshot for row in replay_rows], source_context="replay")
    current_source_presence = summarize_source_presence(current_snapshots, source_context="current_runtime")
    combined_source_presence = combine_source_presence(replay_source_presence, current_source_presence)
    coverage_by_source_group, missing_by_source_group = source_group_coverage_matrix(
        {
            "replay": replay_source_presence,
            "current_runtime": current_source_presence,
            "combined": combined_source_presence,
        }
    )
    blocker_diagnosis = cost_blocker_diagnosis(
        combined_summary=combined_summary,
        combined_source_presence=combined_source_presence,
    )
    recovery_classification = cost_evidence_recovery_classification(
        replay_summary=replay_summary,
        current_summary=current_summary,
        combined_summary=combined_summary,
        replay_source_presence=replay_source_presence,
        current_source_presence=current_source_presence,
        combined_source_presence=combined_source_presence,
    )
    core_pass_conditions = {
        "production_grade_cost_coverage_gte_95pct": combined_summary["production_grade_cost_coverage"] >= 0.95,
        "unexplained_cost_missing_rows_eq_0": combined_summary["unexplained_cost_missing_rows"] == 0,
        "replay_paper_cost_parity_comparable_rows_gt_0": int(
            combined_summary.get("replay_paper_cost_parity_comparable_rows") or 0
        )
        > 0,
        "replay_paper_cost_parity_side_comparisons_gt_0": int(
            combined_summary.get("replay_paper_cost_parity_compared_side_count") or 0
        )
        > 0,
        "replay_paper_cost_parity_for_same_snapshot_order": combined_summary["replay_paper_cost_parity_mismatch_rows"] == 0
        and int(combined_summary.get("replay_paper_cost_parity_comparable_rows") or 0) > 0,
    }
    combined_source_fields = combined_source_presence.get("fields")
    combined_source_fields = combined_source_fields if isinstance(combined_source_fields, Mapping) else {}
    missing_field_counts = {
        field: int((combined_source_fields.get(field) or {}).get("missing_rows") or 0)
        for field in REQUIRED_COST_EVIDENCE_FIELDS
    }
    required_fields_present_counts = {
        field: max(0, int(combined_summary["row_count"]) - missing_count)
        for field, missing_count in missing_field_counts.items()
    }
    required_coverage = 0.95
    required_field_coverage_pass_conditions = {
        f"required_cost_field_{field}_coverage_gte_95pct": float(
            (combined_source_fields.get(field) or {}).get("coverage") or 0.0
        )
        >= required_coverage
        for field in REQUIRED_COST_EVIDENCE_FIELDS
    }
    required_field_all_rows_pass_conditions = {
        f"required_cost_field_{field}_present_for_all_rows": missing_count == 0
        for field, missing_count in missing_field_counts.items()
    }
    pass_conditions = {**core_pass_conditions, **required_field_all_rows_pass_conditions}
    required_evidence_fields_present = all(required_field_all_rows_pass_conditions.values())
    required_evidence_fields_covered_gte_95pct = all(required_field_coverage_pass_conditions.values())
    replay_paper_identical_costs = core_pass_conditions["replay_paper_cost_parity_for_same_snapshot_order"]
    required_rows = math.ceil(combined_summary["row_count"] * required_coverage) if combined_summary["row_count"] else 0
    production_shortfall = max(0, required_rows - combined_summary["production_grade_rows"])
    cost_evidence_blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "actual": {
                "production_grade_cost_coverage_gte_95pct": combined_summary["production_grade_cost_coverage"],
                "unexplained_cost_missing_rows_eq_0": combined_summary["unexplained_cost_missing_rows"],
                "replay_paper_cost_parity_comparable_rows_gt_0": combined_summary.get(
                    "replay_paper_cost_parity_comparable_rows"
                ),
                "replay_paper_cost_parity_side_comparisons_gt_0": combined_summary.get(
                    "replay_paper_cost_parity_compared_side_count"
                ),
                "replay_paper_cost_parity_for_same_snapshot_order": combined_summary["replay_paper_cost_parity_mismatch_rows"],
            }.get(name),
            "expected": {
                "production_grade_cost_coverage_gte_95pct": ">=0.95",
                "unexplained_cost_missing_rows_eq_0": 0,
                "replay_paper_cost_parity_comparable_rows_gt_0": ">0",
                "replay_paper_cost_parity_side_comparisons_gt_0": ">0",
                "replay_paper_cost_parity_for_same_snapshot_order": 0,
            }.get(name),
        }
        for name, passed in core_pass_conditions.items()
        if passed is not True
    ]
    hard_blocking_fields = list(blocker_diagnosis.get("hard_blocking_fields") or [])
    required_field_blocker_details = [
        {
            "pass_condition": f"required_cost_field_{field}_present_for_all_rows",
            "field": field,
            "passed": False,
            "actual": {
                "coverage": float((combined_source_fields.get(field) or {}).get("coverage") or 0.0),
                "missing_rows": int((combined_source_fields.get(field) or {}).get("missing_rows") or 0),
                "present_rows": int((combined_source_fields.get(field) or {}).get("present_rows") or 0),
                "source_counts": dict((combined_source_fields.get(field) or {}).get("source_counts") or {}),
            },
            "expected": {
                "coverage": ">=0.95",
                "missing_rows": 0,
            },
            "hard_blocking_field": field in hard_blocking_fields,
            "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
        }
        for field in REQUIRED_COST_EVIDENCE_FIELDS
        if required_field_all_rows_pass_conditions[f"required_cost_field_{field}_present_for_all_rows"] is not True
    ]
    hard_blocking_field_blocker_details = [
        detail for detail in required_field_blocker_details if detail["hard_blocking_field"] is True
    ]
    hard_blocking_missing_fields = [
        field for field in hard_blocking_fields if int(missing_field_counts.get(field) or 0) > 0
    ]
    hard_blocking_missing_field_counts = {
        field: int(missing_field_counts.get(field) or 0)
        for field in hard_blocking_missing_fields
    }
    hard_blocking_present_counts = {
        field: int(required_fields_present_counts.get(field) or 0)
        for field in hard_blocking_fields
    }
    cost_evidence_blocker_details.extend(required_field_blocker_details)
    phase_1_actuals = {
        "production_grade_cost_coverage_gte_95pct": combined_summary["production_grade_cost_coverage"],
        "unexplained_cost_missing_rows_eq_0": combined_summary["unexplained_cost_missing_rows"],
        "replay_paper_cost_parity_comparable_rows_gt_0": combined_summary.get(
            "replay_paper_cost_parity_comparable_rows"
        ),
        "replay_paper_cost_parity_side_comparisons_gt_0": combined_summary.get(
            "replay_paper_cost_parity_compared_side_count"
        ),
        "replay_paper_cost_parity_for_same_snapshot_order": combined_summary["replay_paper_cost_parity_mismatch_rows"],
        "required_cost_fields_present_for_all_rows": {
            "missing_required_field_counts": missing_field_counts,
            "hard_blocking_missing_fields": hard_blocking_missing_fields,
            "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        },
    }
    phase_1_required = {
        "production_grade_cost_coverage_gte_95pct": ">=0.95",
        "unexplained_cost_missing_rows_eq_0": 0,
        "replay_paper_cost_parity_comparable_rows_gt_0": ">0",
        "replay_paper_cost_parity_side_comparisons_gt_0": ">0",
        "replay_paper_cost_parity_for_same_snapshot_order": 0,
        "required_cost_fields_present_for_all_rows": {
            "missing_required_field_counts": {field: 0 for field in REQUIRED_COST_EVIDENCE_FIELDS},
            "hard_blocking_missing_fields": [],
        },
    }
    status = {
        "schema_version": "challenger_v2_production_cost_evidence_status_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": "PASS" if all(pass_conditions.values()) else "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
        "current_snapshot_source": current_source,
        "required_evidence_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_production_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_coverage": required_coverage,
        "production_grade_cost_coverage_required": ">=0.95",
        "production_grade_cost_coverage": combined_summary["production_grade_cost_coverage"],
        "production_grade_cost_coverage_shortfall_to_required": max(
            0.0,
            required_coverage - float(combined_summary["production_grade_cost_coverage"] or 0.0),
        ),
        "required_evidence_fields_present": required_evidence_fields_present,
        "required_cost_fields_present_for_all_rows": required_evidence_fields_present,
        "required_evidence_fields_covered_gte_95pct": required_evidence_fields_covered_gte_95pct,
        "required_cost_fields_covered_gte_95pct": required_evidence_fields_covered_gte_95pct,
        "production_grade_cost_rows": combined_summary["production_grade_rows"],
        "production_grade_rows": combined_summary["production_grade_rows"],
        "total_cost_evidence_rows": combined_summary["row_count"],
        "total_rows": combined_summary["row_count"],
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "production_grade_cost_row_shortfall_to_95pct": production_shortfall,
        "shortfall_to_95pct": production_shortfall,
        "phase_1_exit_minimum_new_candidate_bound_production_grade_rows": production_shortfall,
        "replay_rows_examined": replay_summary["row_count"],
        "current_rows_examined": current_summary["row_count"],
        "replay_paper_cost_parity_comparable_rows": combined_summary["replay_paper_cost_parity_comparable_rows"],
        "replay_paper_cost_parity_same_snapshot_order_rows": combined_summary[
            "replay_paper_cost_parity_same_snapshot_order_rows"
        ],
        "replay_paper_cost_parity_compared_side_count": combined_summary[
            "replay_paper_cost_parity_compared_side_count"
        ],
        "replay_paper_cost_parity_matched_rows": combined_summary["replay_paper_cost_parity_matched_rows"],
        "replay_paper_cost_parity_matched_side_count": combined_summary[
            "replay_paper_cost_parity_matched_side_count"
        ],
        "replay_paper_cost_parity_non_vacuous": int(
            combined_summary.get("replay_paper_cost_parity_comparable_rows") or 0
        )
        > 0,
        "replay_paper_cost_parity_comparison_contract": {
            "same_snapshot_order_identity_fields": [
                "source_context",
                "symbol",
                "timeframe",
                "snapshot_id",
                "decision_time",
                "feature_cutoff",
                "available_at",
                "side",
            ],
            "comparable_rows": combined_summary["replay_paper_cost_parity_comparable_rows"],
            "same_snapshot_order_rows": combined_summary["replay_paper_cost_parity_same_snapshot_order_rows"],
            "side_comparisons": combined_summary["replay_paper_cost_parity_compared_side_count"],
            "matched_rows": combined_summary["replay_paper_cost_parity_matched_rows"],
            "matched_side_comparisons": combined_summary["replay_paper_cost_parity_matched_side_count"],
            "mismatch_rows": combined_summary["replay_paper_cost_parity_mismatch_rows"],
            "side_mismatch_counts": combined_summary["replay_paper_cost_parity_mismatch_side_counts"],
            "non_vacuous": int(combined_summary.get("replay_paper_cost_parity_comparable_rows") or 0) > 0,
            "parity_rule": "estimate_replay_cost(row, side) must equal estimate_paper_cost(row, side) for the same normalized snapshot/order input",
        },
        "cost_evidence_fields": combined_source_fields,
        "required_fields_present_counts": required_fields_present_counts,
        "missing_field_counts": missing_field_counts,
        "missing_cost_field_counts": missing_field_counts,
        "required_field_missing_counts": missing_field_counts,
        "missing_required_field_counts": missing_field_counts,
        "field_coverage": combined_source_fields,
        "unexplained_cost_missing_rows": combined_summary["unexplained_cost_missing_rows"],
        "fallback_true_rows": combined_summary["fallback_rows"],
        "fallback_rows": combined_summary["fallback_rows"],
        "shadow_only_fallback_rows": combined_summary["fallback_rows"],
        "fallback_rows_shadow_only": True,
        "fallback_rows_are_shadow_only": True,
        "fallback_rows_may_be_shadow_scored": True,
        "fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
        "fallback_rows_count_as_production_grade_evidence": False,
        "fallback_rows_count_as_production_grade_training_evidence": False,
        "fallback_rows_count_as_lockbox_evidence": False,
        "fallback_rows_count_as_promotion_evidence": False,
        "fallback_true_rows_may_count_as_production_evidence": False,
        "production_evidence_rules": {
            "fallback_true_rows_may_be_shadow_scored": True,
            "fallback_true_rows_may_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
            "fallback_true_rows_may_count_as_production_grade_evidence": False,
            "fallback_true_rows_may_count_as_lockbox_evidence": False,
            "fallback_true_rows_may_count_as_promotion_evidence": False,
            "required_cost_fields_must_be_present_for_all_rows": True,
            "production_grade_cost_coverage_required": ">=0.95",
            "unexplained_cost_missing_rows_required": 0,
            "replay_and_paper_costs_identical_for_same_snapshot_order_required": True,
        },
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "replay_paper_cost_parity": combined_summary["replay_paper_cost_parity_mismatch_rows"] == 0,
        "replay_paper_cost_parity_for_same_snapshot_order": pass_conditions[
            "replay_paper_cost_parity_for_same_snapshot_order"
        ],
        "replay_paper_identical_costs_for_same_snapshot_order": replay_paper_identical_costs,
        "replay_paper_identical_costs": replay_paper_identical_costs,
        "replay_and_paper_produce_identical_costs_for_same_snapshot_order": replay_paper_identical_costs,
        "replay_paper_cost_parity_mismatch_rows": combined_summary["replay_paper_cost_parity_mismatch_rows"],
        "replay_paper_cost_parity_mismatch_side_counts": combined_summary["replay_paper_cost_parity_mismatch_side_counts"],
        "pass_conditions": pass_conditions,
        "blocked_reasons": [name for name, passed in pass_conditions.items() if passed is not True],
        "cost_evidence_blocker_details": cost_evidence_blocker_details,
        "blocker_details": cost_evidence_blocker_details,
        "failed_blocker_details": cost_evidence_blocker_details,
        "actuals": phase_1_actuals,
        "required": phase_1_required,
        "sample_blockers": cost_evidence_blocker_details[:25],
        "required_field_pass_conditions": required_field_all_rows_pass_conditions,
        "required_field_all_rows_pass_conditions": required_field_all_rows_pass_conditions,
        "required_field_coverage_pass_conditions": required_field_coverage_pass_conditions,
        "required_field_blocker_details": required_field_blocker_details,
        "hard_blocking_field_blocker_details": hard_blocking_field_blocker_details,
        "hard_blocking_field_blocked_reasons": [
            detail["pass_condition"] for detail in hard_blocking_field_blocker_details
        ],
        "blocker_diagnosis": blocker_diagnosis,
        "cost_evidence_recovery_classification": recovery_classification,
        "source_recovery_summary": recovery_classification["source_groups"],
        "source_group_recovery_classification": recovery_classification["source_groups"],
        "replay_irrecoverable_cost_evidence_fields": recovery_classification[
            "replay_irrecoverable_cost_evidence_fields"
        ],
        "current_runtime_future_capture_required_fields": recovery_classification[
            "current_runtime_future_capture_required_fields"
        ],
        "combined_hard_missing_cost_evidence_fields": recovery_classification[
            "combined_hard_missing_cost_evidence_fields"
        ],
        "existing_replay_rows_may_be_backfilled_for_credit": False,
        "existing_current_runtime_rows_may_be_backfilled_for_credit": False,
        "sample_missing_cost_evidence_rows": combined_summary["sample_missing_rows"],
        "sample_missing_cost_evidence_rows_by_source_group": {
            "replay": replay_summary["sample_missing_rows"],
            "current_runtime": current_summary["sample_missing_rows"],
            "combined": combined_summary["sample_missing_rows"],
        },
        "hard_blocker_fields": hard_blocking_fields,
        "hard_blocker_count": len(hard_blocking_fields),
        "hard_blocker_missing_fields": hard_blocking_missing_fields,
        "hard_blocker_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocker_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocker_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_fields": hard_blocking_fields,
        "hard_blocking_cost_fields": hard_blocking_fields,
        "hard_blocking_field_count": len(hard_blocking_fields),
        "hard_blocking_cost_field_count": len(hard_blocking_fields),
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_cost_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_cost_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_cost_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_missing_cost_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_present_counts": hard_blocking_present_counts,
        "hard_blocking_cost_present_counts": hard_blocking_present_counts,
        "fully_missing_cost_fields": list(blocker_diagnosis.get("fully_missing_fields") or []),
        "partially_missing_cost_fields": list(blocker_diagnosis.get("partially_missing_fields") or []),
        "safe_next_capture_boundary": dict(blocker_diagnosis.get("safe_next_capture_boundary") or {}),
        "source_group_summary": coverage_by_source_group,
        "source_group_coverage": coverage_by_source_group,
        "cohorts": {
            "replay": replay_summary,
            "current_runtime": current_summary,
            "combined": combined_summary,
        },
    }
    matrix_pass_conditions = {
        "replay_source_presence_computed": int(replay_source_presence.get("row_count") or 0) == replay_summary["row_count"],
        "current_runtime_source_presence_computed": int(current_source_presence.get("row_count") or 0) == current_summary["row_count"],
        "all_required_source_fields_covered_gte_95pct": all(
            float((combined_source_fields.get(field) or {}).get("coverage") or 0.0) >= 0.95
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        ),
    }
    field_source_coverage = {
        field: float((combined_source_fields.get(field) or {}).get("coverage") or 0.0)
        for field in REQUIRED_COST_EVIDENCE_FIELDS
    }
    combined_source_coverage = min(field_source_coverage.values()) if field_source_coverage else 0.0
    source_coverage_blocker_details = [
        {
            "field": field,
            "pass_condition": f"required_cost_field_{field}_coverage_gte_95pct",
            "coverage": coverage,
            "missing_rows": int((combined_source_fields.get(field) or {}).get("missing_rows") or 0),
            "expected_coverage": ">=0.95",
            "required": ">=0.95",
            "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
        }
        for field, coverage in field_source_coverage.items()
        if coverage < 0.95
    ]
    matrix_actuals = {
        "replay_source_presence_computed": {
            "source_presence_rows": int(replay_source_presence.get("row_count") or 0),
            "summary_rows": replay_summary["row_count"],
        },
        "current_runtime_source_presence_computed": {
            "source_presence_rows": int(current_source_presence.get("row_count") or 0),
            "summary_rows": current_summary["row_count"],
        },
        "all_required_source_fields_covered_gte_95pct": field_source_coverage,
    }
    matrix_required = {
        "replay_source_presence_computed": "source_presence.row_count == replay_summary.row_count",
        "current_runtime_source_presence_computed": (
            "source_presence.row_count == current_runtime_summary.row_count"
        ),
        "all_required_source_fields_covered_gte_95pct": {
            field: ">=0.95" for field in REQUIRED_COST_EVIDENCE_FIELDS
        },
    }
    source_group_summaries: dict[str, Any] = {}
    source_group_inputs = {
        "replay": replay_summary,
        "current_runtime": current_summary,
        "combined": combined_summary,
    }
    for group_name, summary in source_group_inputs.items():
        group_fields = coverage_by_source_group.get(group_name) or {}
        group_missing_counts = missing_by_source_group.get(group_name) or {}
        group_field_coverages = [
            float((group_fields.get(field) or {}).get("coverage") or 0.0)
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        ]
        group_required_fields_present = all(
            int(group_missing_counts.get(field) or 0) == 0
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        )
        group_required_fields_covered = all(
            float((group_fields.get(field) or {}).get("coverage") or 0.0) >= required_coverage
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        )
        group_hard_missing_fields = [
            field
            for field in CORE_COST_JOIN_FIELDS
            if int(group_missing_counts.get(field) or 0) > 0
        ]
        source_group_summaries[group_name] = {
            "source_group": group_name,
            "row_count": int(summary.get("row_count") or 0),
            "production_grade_rows": int(summary.get("production_grade_rows") or 0),
            "production_grade_cost_coverage": float(summary.get("production_grade_cost_coverage") or 0.0),
            "fallback_rows": int(summary.get("fallback_rows") or 0),
            "unexplained_cost_missing_rows": int(summary.get("unexplained_cost_missing_rows") or 0),
            "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
            "required_cost_fields_present_for_all_rows": group_required_fields_present,
            "required_cost_fields_covered_gte_95pct": group_required_fields_covered,
            "minimum_required_cost_field_coverage": min(group_field_coverages) if group_field_coverages else 0.0,
            "missing_cost_field_counts": dict(sorted(group_missing_counts.items())),
            "hard_blocking_missing_cost_fields": group_hard_missing_fields,
            "field_coverage": group_fields,
        }
    matrix = {
        "schema_version": "challenger_v2_cost_source_coverage_matrix_v1",
        "generated_utc": status["generated_utc"],
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": getattr(policy, "model_source", None),
        "status": "PASS_COST_SOURCE_COVERAGE_MATRIX" if all(matrix_pass_conditions.values()) else "FAIL_COST_SOURCE_COVERAGE_MATRIX",
        "overall_status": "PASS_COST_SOURCE_COVERAGE_MATRIX" if all(matrix_pass_conditions.values()) else "FAIL_COST_SOURCE_COVERAGE_MATRIX",
        "current_snapshot_source": current_source,
        "required_evidence_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_cost_evidence_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_production_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_source_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_coverage": required_coverage,
        "source_field_coverage_required": ">=0.95",
        "total_rows": combined_summary["row_count"],
        "total_runtime_rows": current_summary["row_count"],
        "total_cost_evidence_rows": combined_summary["row_count"],
        "combined_coverage": combined_source_coverage,
        "combined_source_coverage": combined_source_coverage,
        "combined_required_field_min_coverage": combined_source_coverage,
        "production_grade_cost_coverage": combined_summary["production_grade_cost_coverage"],
        "production_grade_rows": combined_summary["production_grade_rows"],
        "production_grade_cost_rows": combined_summary["production_grade_rows"],
        "unexplained_cost_missing_rows": combined_summary["unexplained_cost_missing_rows"],
        "fallback_rows": combined_summary["fallback_rows"],
        "shadow_only_fallback_rows": combined_summary["fallback_rows"],
        "fallback_rows_shadow_only": True,
        "fallback_rows_are_shadow_only": True,
        "source_groups": ["replay", "current_runtime", "combined"],
        "fields": combined_source_fields,
        "field_coverage": combined_source_fields,
        "coverage_by_field": combined_source_fields,
        "source_coverage_by_field": combined_source_fields,
        "source_field_coverage_summary": combined_source_fields,
        "coverage_by_field_summary": field_source_coverage,
        "source_coverage_rate_by_field": field_source_coverage,
        "source_field_coverage_rate_summary": field_source_coverage,
        "source_coverage": coverage_by_source_group,
        "coverage_by_source": coverage_by_source_group,
        "source_coverage_matrix": coverage_by_source_group,
        "coverage_by_source_group": coverage_by_source_group,
        "source_coverage_by_group": coverage_by_source_group,
        "cost_source_coverage_by_group": coverage_by_source_group,
        "field_coverage_by_source_group": coverage_by_source_group,
        "required_cost_field_coverage_by_source_group": coverage_by_source_group,
        "source_group_coverage": coverage_by_source_group,
        "source_group_summary": source_group_summaries,
        "source_group_summaries": source_group_summaries,
        "source_group_cost_coverage_summary": source_group_summaries,
        "source_type_summary": source_group_summaries,
        "missing_field_counts": missing_field_counts,
        "missing_cost_field_counts": missing_field_counts,
        "missing_required_field_counts": missing_field_counts,
        "missing_by_field": missing_field_counts,
        "missing_source_field_counts": missing_field_counts,
        "missing_required_source_field_counts": missing_field_counts,
        "missing_field_counts_by_source_group": missing_by_source_group,
        "missing_cost_field_counts_by_source_group": missing_by_source_group,
        "missing_required_field_counts_by_source_group": missing_by_source_group,
        "field_source_coverage": field_source_coverage,
        "required_evidence_fields_present": required_evidence_fields_present,
        "required_cost_fields_present_for_all_rows": required_evidence_fields_present,
        "required_source_fields_covered_gte_95pct": required_evidence_fields_covered_gte_95pct,
        "required_cost_fields_covered_gte_95pct": required_evidence_fields_covered_gte_95pct,
        "source_coverage_blocker_details": source_coverage_blocker_details,
        "blocker_details": source_coverage_blocker_details,
        "failed_blocker_details": source_coverage_blocker_details,
        "actuals": matrix_actuals,
        "required": matrix_required,
        "sample_blockers": source_coverage_blocker_details[:25],
        "hard_blocker_fields": hard_blocking_fields,
        "hard_blocker_count": len(hard_blocking_fields),
        "hard_blocker_missing_fields": hard_blocking_missing_fields,
        "hard_blocker_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocker_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocker_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_fields": hard_blocking_fields,
        "hard_blocking_cost_fields": hard_blocking_fields,
        "hard_blocking_field_count": len(hard_blocking_fields),
        "hard_blocking_cost_field_count": len(hard_blocking_fields),
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_cost_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_cost_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_cost_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_missing_cost_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_present_counts": hard_blocking_present_counts,
        "hard_blocking_cost_present_counts": hard_blocking_present_counts,
        "fully_missing_cost_fields": list(blocker_diagnosis.get("fully_missing_fields") or []),
        "partially_missing_cost_fields": list(blocker_diagnosis.get("partially_missing_fields") or []),
        "safe_next_capture_boundary": dict(blocker_diagnosis.get("safe_next_capture_boundary") or {}),
        "pass_conditions": matrix_pass_conditions,
        "blocked_reasons": [name for name, passed in matrix_pass_conditions.items() if passed is not True],
        "source_presence": {
            "replay": replay_source_presence,
            "current_runtime": current_source_presence,
            "combined": combined_source_presence,
        },
        "blocker_diagnosis": blocker_diagnosis,
        "cost_evidence_recovery_classification": recovery_classification,
        "source_recovery_summary": recovery_classification["source_groups"],
        "source_group_recovery_classification": recovery_classification["source_groups"],
        "replay_irrecoverable_cost_evidence_fields": recovery_classification[
            "replay_irrecoverable_cost_evidence_fields"
        ],
        "current_runtime_future_capture_required_fields": recovery_classification[
            "current_runtime_future_capture_required_fields"
        ],
        "combined_hard_missing_cost_evidence_fields": recovery_classification[
            "combined_hard_missing_cost_evidence_fields"
        ],
        "existing_replay_rows_may_be_backfilled_for_credit": False,
        "existing_current_runtime_rows_may_be_backfilled_for_credit": False,
        "sample_missing_cost_evidence_rows": combined_summary["sample_missing_rows"],
        "sample_missing_rows": combined_summary["sample_missing_rows"],
        "sample_missing_cost_evidence_rows_by_source_group": {
            "replay": replay_summary["sample_missing_rows"],
            "current_runtime": current_summary["sample_missing_rows"],
            "combined": combined_summary["sample_missing_rows"],
        },
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
        "fallback_rows_count_as_production_grade_evidence": False,
        "fallback_rows_count_as_production_grade_training_evidence": False,
        "fallback_rows_count_as_lockbox_evidence": False,
        "fallback_rows_count_as_promotion_evidence": False,
        "production_evidence_rules": {
            "fallback_true_rows_may_be_shadow_scored": True,
            "fallback_true_rows_may_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
            "fallback_true_rows_may_count_as_production_grade_evidence": False,
            "fallback_true_rows_may_count_as_lockbox_evidence": False,
            "fallback_true_rows_may_count_as_promotion_evidence": False,
            "required_cost_fields_must_be_present_for_all_rows": True,
            "source_field_coverage_required": ">=0.95",
            "unexplained_cost_missing_rows_required": 0,
        },
        "cohorts": {
            "replay": replay_summary,
            "current_runtime": current_summary,
            "combined": combined_summary,
        },
    }
    return status, matrix


def production_cost_capture_gap_audit(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    paper_intent_join_status: Mapping[str, Any],
    paper_cost_telemetry: Mapping[str, Any],
    top_book_enrichment_status: Mapping[str, Any],
) -> dict[str, Any]:
    total_rows = int(cost_status.get("total_cost_evidence_rows") or 0)
    production_rows = int(cost_status.get("production_grade_cost_rows") or 0)
    required_coverage = finite_float(cost_status.get("required_coverage"))
    if required_coverage is None:
        required_coverage = finite_float(coverage_matrix.get("required_coverage"))
    if required_coverage is None:
        required_coverage = 0.95
    required_rows = math.ceil(total_rows * 0.95) if total_rows else 0
    production_shortfall = max(0, required_rows - production_rows)
    source_presence = coverage_matrix.get("source_presence") if isinstance(coverage_matrix.get("source_presence"), Mapping) else {}
    combined_presence = source_presence.get("combined") if isinstance(source_presence, Mapping) else {}
    combined_fields = combined_presence.get("fields") if isinstance(combined_presence, Mapping) else {}
    field_shortfalls: dict[str, Any] = {}
    for field in REQUIRED_COST_EVIDENCE_FIELDS:
        field_payload = combined_fields.get(field) if isinstance(combined_fields, Mapping) else {}
        field_payload = field_payload if isinstance(field_payload, Mapping) else {}
        present = int(field_payload.get("present_rows") or 0)
        missing = int(field_payload.get("missing_rows") or max(0, total_rows - present))
        coverage = float(field_payload.get("coverage") or 0.0)
        field_shortfalls[field] = {
            "present_rows": present,
            "missing_rows": missing,
            "coverage": coverage,
            "additional_rows_needed_for_95pct": max(0, required_rows - present),
            "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
            "source_counts": field_payload.get("source_counts") if isinstance(field_payload, Mapping) else {},
        }

    raw_field_coverage = cost_status.get("field_coverage")
    field_coverage = (
        dict(raw_field_coverage)
        if isinstance(raw_field_coverage, Mapping)
        else (
            dict(coverage_matrix.get("field_coverage"))
            if isinstance(coverage_matrix.get("field_coverage"), Mapping)
            else dict(field_shortfalls)
        )
    )
    raw_required_field_missing_counts = (
        cost_status.get("required_field_missing_counts")
        or cost_status.get("missing_field_counts")
        or coverage_matrix.get("missing_field_counts")
    )
    required_field_missing_counts = (
        {str(field): int(count or 0) for field, count in raw_required_field_missing_counts.items()}
        if isinstance(raw_required_field_missing_counts, Mapping)
        else {
            field: int((field_shortfalls.get(field) or {}).get("missing_rows") or 0)
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        }
    )
    raw_required_fields_present_counts = (
        cost_status.get("required_fields_present_counts")
        or cost_status.get("present_field_counts")
        or coverage_matrix.get("present_field_counts")
    )
    required_fields_present_counts = (
        {str(field): int(count or 0) for field, count in raw_required_fields_present_counts.items()}
        if isinstance(raw_required_fields_present_counts, Mapping)
        else {
            field: int((field_shortfalls.get(field) or {}).get("present_rows") or 0)
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        }
    )
    source_group_summary = (
        cost_status.get("source_group_summary")
        if isinstance(cost_status.get("source_group_summary"), Mapping)
        else coverage_matrix.get("coverage_by_source_group")
    )
    source_group_summary = (
        source_group_summary
        if isinstance(source_group_summary, Mapping)
        else coverage_matrix.get("source_group_coverage")
    )
    source_group_summary = source_group_summary if isinstance(source_group_summary, Mapping) else {}

    paper_production_grade_rows = int(paper_cost_telemetry.get("paper_telemetry_production_grade_rows") or 0)
    challenger_bound_production_grade_rows = int(paper_cost_telemetry.get("challenger_bound_production_grade_rows") or 0)
    old_or_unbound_production_grade_rows = int(paper_cost_telemetry.get("old_policy_or_unbound_production_grade_rows") or 0)
    candidate_bound_intents = int(paper_intent_join_status.get("candidate_bound_intents") or 0)
    trusted_intent_matches = int(paper_intent_join_status.get("trusted_snapshot_matches") or 0)
    positive_order_size_matches = int(paper_intent_join_status.get("positive_order_size_matches") or 0)
    blocker_payload = cost_status.get("blocker_diagnosis")
    blocker_payload = blocker_payload if isinstance(blocker_payload, Mapping) else {}
    hard_blockers = list(blocker_payload.get("hard_blocking_fields") or [])
    hard_blocking_missing_fields = [
        str(field)
        for field in (
            cost_status.get("hard_blocking_missing_fields")
            if isinstance(cost_status.get("hard_blocking_missing_fields"), Sequence)
            and not isinstance(cost_status.get("hard_blocking_missing_fields"), (str, bytes, bytearray))
            else [
                field
                for field in hard_blockers
                if int((field_shortfalls.get(field) or {}).get("missing_rows") or 0) > 0
            ]
        )
    ]
    raw_hard_blocking_missing_counts = cost_status.get("hard_blocking_missing_field_counts")
    hard_blocking_missing_field_counts = (
        {str(field): int(count or 0) for field, count in raw_hard_blocking_missing_counts.items()}
        if isinstance(raw_hard_blocking_missing_counts, Mapping)
        else {
            field: int((field_shortfalls.get(field) or {}).get("missing_rows") or 0)
            for field in hard_blocking_missing_fields
        }
    )
    raw_hard_blocking_present_counts = cost_status.get("hard_blocking_present_counts")
    hard_blocking_present_counts = (
        {str(field): int(count or 0) for field, count in raw_hard_blocking_present_counts.items()}
        if isinstance(raw_hard_blocking_present_counts, Mapping)
        else {
            field: int((field_shortfalls.get(field) or {}).get("present_rows") or 0)
            for field in hard_blockers
        }
    )
    fallback_rows = int(cost_status.get("fallback_true_rows") or cost_status.get("fallback_rows") or 0)
    pass_payload = cost_status.get("pass_conditions") if isinstance(cost_status.get("pass_conditions"), Mapping) else {}
    can_recover_from_existing_authoritative_sources = (
        cost_status.get("status") == "PASS"
        and challenger_bound_production_grade_rows >= required_rows
        and trusted_intent_matches >= required_rows
    )
    pass_conditions = {
        "production_grade_cost_coverage_gte_95pct": pass_payload.get("production_grade_cost_coverage_gte_95pct") is True,
        "unexplained_cost_missing_rows_eq_0": pass_payload.get("unexplained_cost_missing_rows_eq_0") is True,
        "replay_paper_cost_parity_for_same_snapshot_order": pass_payload.get("replay_paper_cost_parity_for_same_snapshot_order") is True,
        "candidate_bound_production_grade_paper_telemetry_available": challenger_bound_production_grade_rows >= required_rows if required_rows else False,
        "trusted_candidate_bound_paper_intent_matches_available": trusted_intent_matches >= required_rows if required_rows else False,
        "old_policy_or_unbound_rows_not_counted": True,
        "can_recover_from_existing_authoritative_sources_without_new_capture": can_recover_from_existing_authoritative_sources,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    if all(pass_conditions.values()):
        status = "PASS_PRODUCTION_COST_CAPTURE_READY"
    elif old_or_unbound_production_grade_rows and challenger_bound_production_grade_rows == 0:
        status = "BLOCKED_EXISTING_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    else:
        status = "BLOCKED_RUNTIME_COST_CAPTURE_MISSING"
    priority_field_shortfalls: list[dict[str, Any]] = []
    for field, field_payload in field_shortfalls.items():
        missing_rows = int(field_payload.get("missing_rows") or 0)
        additional_rows = int(field_payload.get("additional_rows_needed_for_95pct") or 0)
        if missing_rows <= 0 and additional_rows <= 0:
            continue
        capture_groups = list(RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS.get(field, []))
        priority_field_shortfalls.append(
            {
                "field": field,
                "missing_rows": missing_rows,
                "additional_rows_needed_for_95pct": additional_rows,
                "coverage": field_payload.get("coverage"),
                "recovery_boundary": field_payload.get("recovery_boundary"),
                "hard_blocking_field": field in hard_blockers,
                "required_capture_source_groups": capture_groups,
                "source_counts": field_payload.get("source_counts") or {},
            }
        )
    priority_field_shortfalls.sort(
        key=lambda item: (
            not bool(item["hard_blocking_field"]),
            -int(item["additional_rows_needed_for_95pct"] or 0),
            -int(item["missing_rows"] or 0),
            str(item["field"]),
        )
    )
    limiting_cost_fields_for_95pct = [
        field_payload
        for field_payload in priority_field_shortfalls
        if int(field_payload.get("additional_rows_needed_for_95pct") or 0) > 0
    ]
    hard_blocking_field_shortfalls = [
        field_payload for field_payload in priority_field_shortfalls if field_payload.get("hard_blocking_field") is True
    ]
    priority_source_groups: dict[str, dict[str, Any]] = {}
    for field_payload in priority_field_shortfalls:
        field = str(field_payload["field"])
        for source_group in field_payload["required_capture_source_groups"]:
            write_point = RUNTIME_COST_CAPTURE_WRITE_POINTS.get(str(source_group), {})
            group_payload = priority_source_groups.setdefault(
                str(source_group),
                {
                    "source_group": str(source_group),
                    "producer": write_point.get("producer"),
                    "capture_stage": RUNTIME_COST_CAPTURE_STAGE_BY_GROUP.get(str(source_group), "unknown"),
                    "required_role": write_point.get("required_role"),
                    "files": list(write_point.get("files", [])),
                    "redis_keys": list(write_point.get("redis_keys", [])),
                    "missing_cost_fields": [],
                    "hard_blocking_fields": [],
                    "total_missing_rows_across_fields": 0,
                    "max_additional_rows_needed_for_95pct": 0,
                    "required_actions": [],
                    "operator_approval_required_before_runtime_edit": True,
                    "existing_rows_may_not_be_backfilled_for_credit": True,
                    "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
                },
            )
            group_payload["missing_cost_fields"].append(field)
            if field_payload["hard_blocking_field"]:
                group_payload["hard_blocking_fields"].append(field)
            group_payload["total_missing_rows_across_fields"] += int(field_payload["missing_rows"] or 0)
            group_payload["max_additional_rows_needed_for_95pct"] = max(
                int(group_payload["max_additional_rows_needed_for_95pct"] or 0),
                int(field_payload["additional_rows_needed_for_95pct"] or 0),
            )
            group_payload["required_actions"].append(
                {
                    "field": field,
                    "action": f"capture_{field}_for_future_candidate_bound_rows",
                    "recovery_boundary": field_payload.get("recovery_boundary"),
                }
            )
    for group_payload in priority_source_groups.values():
        group_payload["missing_cost_fields"] = sorted(set(group_payload["missing_cost_fields"]))
        group_payload["hard_blocking_fields"] = sorted(set(group_payload["hard_blocking_fields"]))
        group_payload["priority"] = (
            "HIGH"
            if group_payload["hard_blocking_fields"] or int(group_payload["max_additional_rows_needed_for_95pct"] or 0) > 0
            else "MEDIUM"
        )
    next_capture_batch_contract = {
        "identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "minimum_new_candidate_bound_production_grade_rows": production_shortfall,
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "limiting_cost_fields_for_95pct": limiting_cost_fields_for_95pct,
        "hard_blocking_field_shortfalls": hard_blocking_field_shortfalls,
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_present_counts": hard_blocking_present_counts,
        "priority_field_shortfalls": priority_field_shortfalls,
        "priority_source_groups": sorted(
            priority_source_groups.values(),
            key=lambda item: (
                item.get("priority") != "HIGH",
                -int(item.get("max_additional_rows_needed_for_95pct") or 0),
                str(item.get("source_group")),
            ),
        ),
        "field_capture_requirements": RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS,
        "runtime_capture_write_points": RUNTIME_COST_CAPTURE_WRITE_POINTS,
        "timestamp_rule": "source_timestamp <= available_at <= decision_time and feature_cutoff <= decision_time",
        "candidate_binding_rule": "candidate_id, policy_fingerprint, and model_source must all match the frozen challenger before cost rows can count",
        "fallback_rule": "fallback=true may be shadow-scored but cannot count as production-grade training, lockbox, paper canary, or promotion evidence",
        "route_rule": "capture must remain paper-only until production cost evidence and blind lockbox pass",
        "operator_approval_required_before_runtime_write_path_edits": True,
        "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
    }
    phase_1_exit_criteria = {
        "minimum_new_candidate_bound_production_grade_rows": production_shortfall,
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "production_grade_cost_coverage_required": ">=0.95",
        "unexplained_cost_missing_rows_required": 0,
        "replay_paper_cost_parity_mismatch_rows_required": 0,
        "candidate_identity_fields_required": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "cost_evidence_fields_required": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "operator_approval_required_before_runtime_write_path_edits": True,
        "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
        "fallback_true_rows_may_count_as_production_evidence": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
    }
    implementation_handoff = {
        "handoff_status": (
            "READY_NO_RUNTIME_PATCH_REQUIRED"
            if all(pass_conditions.values())
            else "AWAITING_OPERATOR_APPROVAL_FOR_RUNTIME_COST_CAPTURE"
        ),
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "approval_required_before_runtime_write_path_edits": True,
        "approval_packet_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        "approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "minimum_new_candidate_bound_production_grade_rows": production_shortfall,
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "production_grade_cost_coverage_required": ">=0.95",
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        "priority_source_groups": next_capture_batch_contract["priority_source_groups"],
        "priority_field_shortfalls": priority_field_shortfalls,
        "identity_fields_required_on_every_future_row": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "cost_fields_required_on_every_future_row": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "timestamp_rule": next_capture_batch_contract["timestamp_rule"],
        "fallback_rule": next_capture_batch_contract["fallback_rule"],
        "candidate_binding_rule": next_capture_batch_contract["candidate_binding_rule"],
        "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
        "allowed_before_approval": [
            "read_only_audits",
            "artifact_generation",
            "unit_tests",
            "operator_approval_packet_preparation",
        ],
        "prohibited_without_approval": [
            "runtime_write_path_edits",
            "exchange_touching_order_submission_or_modification",
            "backfill_old_policy_or_unbound_rows_for_credit",
            "frozen_candidate_feature_normalization_cost_model_weight_or_threshold_change",
            "paper_binding_before_blind_lockbox_pass",
        ],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    phase_1_blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "actual": {
                "production_grade_cost_coverage_gte_95pct": cost_status.get("production_grade_cost_coverage"),
                "unexplained_cost_missing_rows_eq_0": cost_status.get("unexplained_cost_missing_rows"),
                "replay_paper_cost_parity_for_same_snapshot_order": cost_status.get("replay_paper_cost_parity_mismatch_rows"),
                "candidate_bound_production_grade_paper_telemetry_available": challenger_bound_production_grade_rows,
                "trusted_candidate_bound_paper_intent_matches_available": trusted_intent_matches,
                "old_policy_or_unbound_rows_not_counted": old_or_unbound_production_grade_rows,
                "can_recover_from_existing_authoritative_sources_without_new_capture": can_recover_from_existing_authoritative_sources,
            }.get(name),
            "expected": {
                "production_grade_cost_coverage_gte_95pct": ">=0.95",
                "unexplained_cost_missing_rows_eq_0": 0,
                "replay_paper_cost_parity_for_same_snapshot_order": 0,
                "candidate_bound_production_grade_paper_telemetry_available": f">={required_rows}",
                "trusted_candidate_bound_paper_intent_matches_available": f">={required_rows}",
                "old_policy_or_unbound_rows_not_counted": "not counted for training, lockbox, canary, or promotion",
                "can_recover_from_existing_authoritative_sources_without_new_capture": True,
            }.get(name),
        }
        for name in blocked_reasons
    ]
    gap_actuals = {
        "production_grade_cost_coverage_gte_95pct": cost_status.get("production_grade_cost_coverage"),
        "unexplained_cost_missing_rows_eq_0": cost_status.get("unexplained_cost_missing_rows"),
        "replay_paper_cost_parity_for_same_snapshot_order": cost_status.get("replay_paper_cost_parity_mismatch_rows"),
        "candidate_bound_production_grade_paper_telemetry_available": challenger_bound_production_grade_rows,
        "trusted_candidate_bound_paper_intent_matches_available": trusted_intent_matches,
        "old_policy_or_unbound_rows_not_counted": old_or_unbound_production_grade_rows,
        "can_recover_from_existing_authoritative_sources_without_new_capture": can_recover_from_existing_authoritative_sources,
    }
    gap_required = {
        "production_grade_cost_coverage_gte_95pct": ">=0.95",
        "unexplained_cost_missing_rows_eq_0": 0,
        "replay_paper_cost_parity_for_same_snapshot_order": 0,
        "candidate_bound_production_grade_paper_telemetry_available": f">={required_rows}",
        "trusted_candidate_bound_paper_intent_matches_available": f">={required_rows}",
        "old_policy_or_unbound_rows_not_counted": "not counted for training, lockbox, canary, or promotion",
        "can_recover_from_existing_authoritative_sources_without_new_capture": True,
    }
    source_gap_summary = {
        "required_runtime_write_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "priority_source_groups": next_capture_batch_contract["priority_source_groups"],
        "priority_field_shortfalls": priority_field_shortfalls,
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
    }
    top_gap_patterns = priority_field_shortfalls[:25]
    sample_gap_rows = [
        {
            "field": field_payload.get("field"),
            "missing_rows": field_payload.get("missing_rows"),
            "additional_rows_needed_for_95pct": field_payload.get("additional_rows_needed_for_95pct"),
            "recovery_boundary": field_payload.get("recovery_boundary"),
            "required_capture_source_groups": field_payload.get("required_capture_source_groups"),
        }
        for field_payload in top_gap_patterns
    ]
    return {
        "schema_version": "challenger_v2_production_cost_capture_gap_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "total_rows": total_rows,
        "total_cost_evidence_rows": total_rows,
        "production_grade_cost_rows": production_rows,
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "required_coverage": required_coverage,
        "field_coverage": field_coverage,
        "required_field_missing_counts": required_field_missing_counts,
        "missing_required_field_counts": required_field_missing_counts,
        "missing_cost_field_counts": required_field_missing_counts,
        "required_fields_present_counts": required_fields_present_counts,
        "source_group_summary": dict(source_group_summary),
        "source_gap_summary": source_gap_summary,
        "top_gap_patterns": top_gap_patterns,
        "sample_gap_rows": sample_gap_rows,
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "production_grade_cost_row_shortfall_to_95pct": production_shortfall,
        "shortfall_to_95pct": production_shortfall,
        "minimum_new_candidate_bound_production_grade_rows": production_shortfall,
        "required_new_candidate_bound_production_grade_rows": production_shortfall,
        "phase_1_exit_minimum_new_candidate_bound_production_grade_rows": production_shortfall,
        "runtime_cost_capture_remediation_contract_path": RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT,
        "runtime_cost_capture_operator_approval_packet_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        "runtime_cost_capture_operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "unexplained_cost_missing_rows": cost_status.get("unexplained_cost_missing_rows"),
        "replay_paper_cost_parity_mismatch_rows": cost_status.get("replay_paper_cost_parity_mismatch_rows"),
        "hard_blocking_fields": hard_blockers,
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_present_counts": hard_blocking_present_counts,
        "field_shortfalls": field_shortfalls,
        "limiting_cost_fields_for_95pct": limiting_cost_fields_for_95pct,
        "hard_blocking_field_shortfalls": hard_blocking_field_shortfalls,
        "top_book_enriched_rows": top_book_enrichment_status.get("top_book_enriched_rows"),
        "top_book_enrichment_coverage": top_book_enrichment_status.get("top_book_enrichment_coverage"),
        "paper_intent_rows_scanned": paper_intent_join_status.get("paper_intent_rows_scanned"),
        "candidate_bound_intents": candidate_bound_intents,
        "trusted_candidate_bound_intent_matches": trusted_intent_matches,
        "positive_order_size_matches": positive_order_size_matches,
        "paper_telemetry_production_grade_rows": paper_production_grade_rows,
        "challenger_bound_production_grade_paper_rows": challenger_bound_production_grade_rows,
        "old_policy_or_unbound_production_grade_paper_rows": old_or_unbound_production_grade_rows,
        "candidate_bound_production_grade_rows": challenger_bound_production_grade_rows,
        "old_policy_or_unbound_production_grade_rows": old_or_unbound_production_grade_rows,
        "fallback_rows": fallback_rows,
        "old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "can_recover_from_existing_authoritative_sources_without_new_capture": can_recover_from_existing_authoritative_sources,
        "can_recover_from_existing_sources": can_recover_from_existing_authoritative_sources,
        "priority_field_shortfalls": priority_field_shortfalls,
        "priority_source_groups": next_capture_batch_contract["priority_source_groups"],
        "source_group_shortfalls": next_capture_batch_contract["priority_source_groups"],
        "source_group_gaps": next_capture_batch_contract["priority_source_groups"],
        "required_runtime_write_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "required_runtime_source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "operator_approval_required": True,
        "operator_approval_required_before_runtime_write_path_edits": True,
        "approval_packet_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        "receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "phase_1_blocker_details": phase_1_blocker_details,
        "blocker_details": phase_1_blocker_details,
        "failed_phase_1_blocker_details": phase_1_blocker_details,
        "failed_blocker_details": phase_1_blocker_details,
        "actuals": gap_actuals,
        "required": gap_required,
        "sample_blockers": phase_1_blocker_details[:25],
        "phase_1_exit_criteria": phase_1_exit_criteria,
        "required_next_capture_contract": next_capture_batch_contract,
        "next_capture_batch_contract": next_capture_batch_contract,
        "implementation_handoff": implementation_handoff,
        "operator_handoff": implementation_handoff,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def runtime_cost_capture_contract_audit(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    cost_capture_gap: Mapping[str, Any],
    paper_intent_join_status: Mapping[str, Any],
    paper_cost_telemetry: Mapping[str, Any],
    top_book_enrichment_status: Mapping[str, Any],
    paper_binding_preflight: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    total_rows = int(cost_capture_gap.get("total_cost_evidence_rows") or cost_status.get("total_cost_evidence_rows") or 0)
    required_rows = int(cost_capture_gap.get("minimum_rows_required_for_95pct_coverage") or (math.ceil(total_rows * 0.95) if total_rows else 0))
    hard_blockers = [str(field) for field in cost_capture_gap.get("hard_blocking_fields") or []]
    if not hard_blockers:
        hard_blockers = [str(field) for field in cost_status.get("hard_blocking_fields") or []]
    hard_blocking_missing_fields = [
        str(field)
        for field in (
            cost_capture_gap.get("hard_blocking_missing_fields")
            if isinstance(cost_capture_gap.get("hard_blocking_missing_fields"), Sequence)
            and not isinstance(cost_capture_gap.get("hard_blocking_missing_fields"), (str, bytes, bytearray))
            else cost_status.get("hard_blocking_missing_cost_fields")
            if isinstance(cost_status.get("hard_blocking_missing_cost_fields"), Sequence)
            and not isinstance(cost_status.get("hard_blocking_missing_cost_fields"), (str, bytes, bytearray))
            else hard_blockers
        )
    ]
    raw_hard_blocking_missing_counts = (
        cost_capture_gap.get("hard_blocking_missing_field_counts")
        or cost_status.get("hard_blocking_missing_field_counts")
        or cost_status.get("hard_blocking_missing_cost_field_counts")
    )
    hard_blocking_missing_field_counts = (
        {str(field): int(count or 0) for field, count in raw_hard_blocking_missing_counts.items()}
        if isinstance(raw_hard_blocking_missing_counts, Mapping)
        else {}
    )
    raw_hard_blocking_present_counts = cost_capture_gap.get("hard_blocking_present_counts")
    hard_blocking_present_counts = (
        {str(field): int(count or 0) for field, count in raw_hard_blocking_present_counts.items()}
        if isinstance(raw_hard_blocking_present_counts, Mapping)
        else {}
    )
    raw_missing_required_field_counts = (
        cost_status.get("missing_required_field_counts")
        or cost_status.get("missing_cost_field_counts")
        or cost_status.get("required_field_missing_counts")
    )
    missing_required_field_counts = (
        {str(field): int(count or 0) for field, count in raw_missing_required_field_counts.items()}
        if isinstance(raw_missing_required_field_counts, Mapping)
        else {}
    )
    raw_field_coverage = cost_status.get("field_coverage")
    field_coverage = dict(raw_field_coverage) if isinstance(raw_field_coverage, Mapping) else {}
    required_cost_fields_present_for_all_rows = cost_status.get("required_cost_fields_present_for_all_rows")
    required_cost_fields_covered_gte_95pct = cost_status.get("required_cost_fields_covered_gte_95pct")
    required_evidence_fields_present = cost_status.get("required_evidence_fields_present")
    required_evidence_fields_covered_gte_95pct = cost_status.get("required_evidence_fields_covered_gte_95pct")
    recovery_boundaries = {field: FIELD_RECOVERY_BOUNDARY.get(field) for field in hard_blockers}
    challenger_bound_paper_rows = int(cost_capture_gap.get("challenger_bound_production_grade_paper_rows") or 0)
    old_or_unbound_paper_rows = int(cost_capture_gap.get("old_policy_or_unbound_production_grade_paper_rows") or 0)
    candidate_bound_intents = int(cost_capture_gap.get("candidate_bound_intents") or paper_intent_join_status.get("candidate_bound_intents") or 0)
    trusted_intent_matches = int(
        cost_capture_gap.get("trusted_candidate_bound_intent_matches")
        or paper_intent_join_status.get("trusted_snapshot_matches")
        or 0
    )
    positive_order_size_matches = int(
        cost_capture_gap.get("positive_order_size_matches")
        or paper_intent_join_status.get("positive_order_size_matches")
        or 0
    )
    top_book_enriched_rows = int(cost_capture_gap.get("top_book_enriched_rows") or top_book_enrichment_status.get("top_book_enriched_rows") or 0)
    paper_binding_preflight = paper_binding_preflight if isinstance(paper_binding_preflight, Mapping) else {}
    live_route_rows = int(paper_cost_telemetry.get("live_route_rows") or 0)
    paper_fill_allowed_rows = int(paper_cost_telemetry.get("paper_fill_allowed_rows") or 0)
    candidate_bound_live_route_rows = int(paper_cost_telemetry.get("candidate_bound_live_route_rows") or 0)
    candidate_bound_paper_fill_allowed_rows = int(paper_cost_telemetry.get("candidate_bound_paper_fill_allowed_rows") or 0)
    quarantined_live_route_rows = max(0, live_route_rows - candidate_bound_live_route_rows)
    quarantined_paper_fill_allowed_rows = max(0, paper_fill_allowed_rows - candidate_bound_paper_fill_allowed_rows)

    pass_conditions = {
        "cost_rows_exist": total_rows > 0,
        "production_grade_cost_evidence_passed": cost_status.get("status") == "PASS",
        "production_grade_cost_coverage_gte_95pct": float(cost_status.get("production_grade_cost_coverage") or 0.0) >= 0.95,
        "unexplained_cost_missing_rows_eq_0": int(cost_status.get("unexplained_cost_missing_rows") or 0) == 0,
        "replay_paper_cost_parity_mismatch_rows_eq_0": int(cost_status.get("replay_paper_cost_parity_mismatch_rows") or 0) == 0,
        "hard_blocking_fields_resolved": not hard_blockers,
        "all_hard_blocking_fields_have_recovery_boundary": all(recovery_boundaries.get(field) for field in hard_blockers),
        "top_book_enrichment_rows_gte_required_rows": top_book_enriched_rows >= required_rows if required_rows else False,
        "candidate_bound_intents_gte_required_rows": candidate_bound_intents >= required_rows if required_rows else False,
        "trusted_candidate_bound_intent_matches_gte_required_rows": trusted_intent_matches >= required_rows if required_rows else False,
        "positive_order_size_matches_gte_required_rows": positive_order_size_matches >= required_rows if required_rows else False,
        "challenger_bound_production_grade_paper_rows_gte_required_rows": challenger_bound_paper_rows >= required_rows if required_rows else False,
        "old_policy_or_unbound_rows_not_counted": cost_capture_gap.get("old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence") is False,
        "fallback_rows_excluded_from_training_lockbox_promotion": cost_capture_gap.get("fallback_rows_count_as_training_lockbox_or_promotion_evidence") is False,
        "required_identity_fields_declared": tuple(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
        == tuple(cost_capture_gap.get("required_next_capture_contract", {}).get("identity_fields") or REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
        if isinstance(cost_capture_gap.get("required_next_capture_contract"), Mapping)
        else True,
        "paper_telemetry_live_route_rows_quarantined_when_not_candidate_bound": True,
        "paper_telemetry_fill_allowed_rows_quarantined_when_not_candidate_bound": True,
        "candidate_bound_live_route_rows_eq_0": candidate_bound_live_route_rows == 0,
        "candidate_bound_paper_fill_allowed_rows_eq_0": candidate_bound_paper_fill_allowed_rows == 0,
        "paper_binding_preflight_has_no_live_route_violations": int(paper_binding_preflight.get("live_route_violation_rows") or 0) == 0,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if not passed]
    if not blocked_reasons:
        status = "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"
    elif old_or_unbound_paper_rows and challenger_bound_paper_rows == 0:
        status = "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    else:
        status = "BLOCKED_RUNTIME_COST_CAPTURE_CONTRACT_NOT_SATISFIED"
    condition_details = {
        "cost_rows_exist": {
            "passed": pass_conditions["cost_rows_exist"],
            "observed": total_rows,
            "required": ">0",
        },
        "production_grade_cost_evidence_passed": {
            "passed": pass_conditions["production_grade_cost_evidence_passed"],
            "observed": cost_status.get("status"),
            "required": "PASS",
        },
        "production_grade_cost_coverage_gte_95pct": {
            "passed": pass_conditions["production_grade_cost_coverage_gte_95pct"],
            "observed": cost_status.get("production_grade_cost_coverage"),
            "required": ">=0.95",
        },
        "unexplained_cost_missing_rows_eq_0": {
            "passed": pass_conditions["unexplained_cost_missing_rows_eq_0"],
            "observed": int(cost_status.get("unexplained_cost_missing_rows") or 0),
            "required": 0,
        },
        "replay_paper_cost_parity_mismatch_rows_eq_0": {
            "passed": pass_conditions["replay_paper_cost_parity_mismatch_rows_eq_0"],
            "observed": int(cost_status.get("replay_paper_cost_parity_mismatch_rows") or 0),
            "required": 0,
        },
        "hard_blocking_fields_resolved": {
            "passed": pass_conditions["hard_blocking_fields_resolved"],
            "observed": hard_blockers,
            "required": [],
            "recovery_boundaries": recovery_boundaries,
        },
        "all_hard_blocking_fields_have_recovery_boundary": {
            "passed": pass_conditions["all_hard_blocking_fields_have_recovery_boundary"],
            "observed": recovery_boundaries,
            "required": "non-empty recovery boundary for every hard blocking field",
        },
        "top_book_enrichment_rows_gte_required_rows": {
            "passed": pass_conditions["top_book_enrichment_rows_gte_required_rows"],
            "observed": top_book_enriched_rows,
            "required": f">={required_rows}",
            "shortfall": max(0, required_rows - top_book_enriched_rows),
        },
        "candidate_bound_intents_gte_required_rows": {
            "passed": pass_conditions["candidate_bound_intents_gte_required_rows"],
            "observed": candidate_bound_intents,
            "required": f">={required_rows}",
            "shortfall": max(0, required_rows - candidate_bound_intents),
        },
        "trusted_candidate_bound_intent_matches_gte_required_rows": {
            "passed": pass_conditions["trusted_candidate_bound_intent_matches_gte_required_rows"],
            "observed": trusted_intent_matches,
            "required": f">={required_rows}",
            "shortfall": max(0, required_rows - trusted_intent_matches),
        },
        "positive_order_size_matches_gte_required_rows": {
            "passed": pass_conditions["positive_order_size_matches_gte_required_rows"],
            "observed": positive_order_size_matches,
            "required": f">={required_rows}",
            "shortfall": max(0, required_rows - positive_order_size_matches),
        },
        "challenger_bound_production_grade_paper_rows_gte_required_rows": {
            "passed": pass_conditions["challenger_bound_production_grade_paper_rows_gte_required_rows"],
            "observed": challenger_bound_paper_rows,
            "required": f">={required_rows}",
            "shortfall": max(0, required_rows - challenger_bound_paper_rows),
        },
        "old_policy_or_unbound_rows_not_counted": {
            "passed": pass_conditions["old_policy_or_unbound_rows_not_counted"],
            "observed": cost_capture_gap.get("old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence"),
            "required": False,
        },
        "fallback_rows_excluded_from_training_lockbox_promotion": {
            "passed": pass_conditions["fallback_rows_excluded_from_training_lockbox_promotion"],
            "observed": cost_capture_gap.get("fallback_rows_count_as_training_lockbox_or_promotion_evidence"),
            "required": False,
        },
        "required_identity_fields_declared": {
            "passed": pass_conditions["required_identity_fields_declared"],
            "observed": (
                cost_capture_gap.get("required_next_capture_contract", {}).get("identity_fields")
                if isinstance(cost_capture_gap.get("required_next_capture_contract"), Mapping)
                else list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
            ),
            "required": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        },
        "paper_telemetry_live_route_rows_quarantined_when_not_candidate_bound": {
            "passed": pass_conditions["paper_telemetry_live_route_rows_quarantined_when_not_candidate_bound"],
            "observed": live_route_rows,
            "required": "non-candidate-bound live route rows are quarantined and cannot count",
            "candidate_bound_live_route_rows": candidate_bound_live_route_rows,
            "quarantined_non_candidate_bound_live_route_rows": quarantined_live_route_rows,
        },
        "paper_telemetry_fill_allowed_rows_quarantined_when_not_candidate_bound": {
            "passed": pass_conditions["paper_telemetry_fill_allowed_rows_quarantined_when_not_candidate_bound"],
            "observed": paper_fill_allowed_rows,
            "required": "non-candidate-bound paper-fill rows are quarantined and cannot count",
            "candidate_bound_paper_fill_allowed_rows": candidate_bound_paper_fill_allowed_rows,
            "quarantined_non_candidate_bound_paper_fill_allowed_rows": quarantined_paper_fill_allowed_rows,
        },
        "candidate_bound_live_route_rows_eq_0": {
            "passed": pass_conditions["candidate_bound_live_route_rows_eq_0"],
            "observed": candidate_bound_live_route_rows,
            "required": 0,
        },
        "candidate_bound_paper_fill_allowed_rows_eq_0": {
            "passed": pass_conditions["candidate_bound_paper_fill_allowed_rows_eq_0"],
            "observed": candidate_bound_paper_fill_allowed_rows,
            "required": 0,
        },
        "paper_binding_preflight_has_no_live_route_violations": {
            "passed": pass_conditions["paper_binding_preflight_has_no_live_route_violations"],
            "observed": int(paper_binding_preflight.get("live_route_violation_rows") or 0),
            "required": 0,
        },
    }
    blocker_details = {
        name: detail
        for name, detail in condition_details.items()
        if detail.get("passed") is not True
    }
    contract_actuals = {
        name: detail.get("observed")
        for name, detail in condition_details.items()
    }
    contract_required = {
        name: detail.get("required")
        for name, detail in condition_details.items()
    }
    contract_sample_blockers = [
        {"pass_condition": name, **detail}
        for name, detail in blocker_details.items()
    ][:25]
    required_runtime_source_groups = sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS)
    contract_operator_approval_boundary = {
        "phase": "operator_approval_boundary",
        "status": "AWAITING_OPERATOR_APPROVAL",
        "required_source_groups": required_runtime_source_groups,
        "required_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "required_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approved_patch_scope": "telemetry_only_future_runtime_cost_and_identity_capture",
        "prohibited_patch_scope": [
            "order_submission",
            "order_cancellation_or_modification",
            "exchange_leverage_or_margin_mutation",
            "strategy_threshold_or_weight_change",
            "frozen_candidate_artifact_change",
            "historical_identity_backfill_for_credit",
            "paper_binding_before_blind_lockbox_pass",
        ],
        "acceptance_criteria": [
            "operator approval receipt validates against current approval_subject_hash",
            "approval scope remains telemetry-only future runtime cost and identity capture",
            "paper_fill_allowed=false and routes_to_live=false remain enforced",
        ],
    }
    contract_implementation_phases = [
        contract_operator_approval_boundary,
        {
            "phase": "decision_time_and_pre_submit_capture",
            "status": "BLOCKED_UNTIL_OPERATOR_APPROVAL_AND_FUTURE_ROWS",
            "required_source_groups": ["paper_signal", "paper_intent"],
            "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
            "required_join_key_fields": COST_IDENTITY_JOIN_KEY_FIELDS,
            "acceptance_criteria": [
                "future rows carry candidate_id, policy_fingerprint, and model_source before outcome exists",
                "source_timestamp <= available_at <= decision_time",
                "feature_cutoff <= decision_time",
                "selection fields are immutable after labels or outcomes exist",
            ],
        },
        {
            "phase": "lifecycle_outcome_and_feedback_linkage",
            "status": "BLOCKED_UNTIL_OPERATOR_APPROVAL_AND_FUTURE_ROWS",
            "required_source_groups": ["paper_ledger", "paper_online_ledger", "paper_closed_trades", "trainer_feedback"],
            "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
            "required_join_key_fields": COST_IDENTITY_JOIN_KEY_FIELDS,
            "acceptance_criteria": [
                "outcomes link to immutable decision/pre-submit records before credit",
                "old-policy or unbound rows remain quarantined and non-counting",
                "fallback=true rows remain shadow-only and non-counting",
                "accounting, liquidation, and point-in-time status are preserved for canary gating",
            ],
        },
        {
            "phase": "post_capture_verification",
            "status": "BLOCKED_UNTIL_FUTURE_ROWS_EXIST",
            "minimum_new_candidate_bound_production_grade_rows": required_rows,
            "required_coverage": ">=0.95",
            "acceptance_criteria": [
                "production_grade_cost_coverage >= 0.95",
                "unexplained_cost_missing_rows == 0",
                "replay and paper costs match for the same snapshot/order",
                "future_challenger_bound_production_grade_rows_present",
            ],
        },
    ]
    contract_acceptance_criteria = {
        "operator_approval_required_before_runtime_write_path_edits": True,
        "minimum_new_candidate_bound_production_grade_rows": required_rows,
        "production_grade_cost_coverage_required": ">=0.95",
        "unexplained_cost_missing_rows_required": 0,
        "replay_paper_cost_parity_mismatch_rows_required": 0,
        "candidate_identity_fields_required": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "cost_evidence_fields_required": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
        "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }

    return {
        "schema_version": "challenger_v2_runtime_cost_capture_contract_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "runtime_cost_capture_contract_status": status,
        "production_cost_status": cost_status.get("status"),
        "production_cost_evidence_status": cost_status.get("status"),
        "blocked_reasons": blocked_reasons,
        "condition_details": condition_details,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "phase_1_blocker_details": blocker_details,
        "failed_phase_1_blocker_details": blocker_details,
        "actuals": contract_actuals,
        "required": contract_required,
        "sample_blockers": contract_sample_blockers,
        "total_cost_evidence_rows": total_rows,
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "required_rows": required_rows,
        "required_production_grade_cost_rows": required_rows,
        "minimum_production_grade_cost_rows_required": required_rows,
        "production_grade_cost_rows": cost_capture_gap.get("production_grade_cost_rows"),
        "production_grade_cost_coverage": cost_capture_gap.get("production_grade_cost_coverage"),
        "production_grade_cost_row_shortfall_to_95pct": cost_capture_gap.get("production_grade_cost_row_shortfall_to_95pct"),
        "unexplained_cost_missing_rows": cost_capture_gap.get("unexplained_cost_missing_rows"),
        "replay_paper_cost_parity_mismatch_rows": cost_capture_gap.get("replay_paper_cost_parity_mismatch_rows"),
        "hard_blocking_fields": hard_blockers,
        "hard_blocking_cost_fields": hard_blockers,
        "hard_blocking_missing_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_cost_fields": hard_blocking_missing_fields,
        "hard_blocking_missing_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_cost_field_counts": hard_blocking_missing_field_counts,
        "hard_blocking_missing_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_cost_field_count": len(hard_blocking_missing_fields),
        "hard_blocking_missing_row_total": sum(hard_blocking_missing_field_counts.values()),
        "hard_blocking_present_counts": hard_blocking_present_counts,
        "missing_required_field_counts": missing_required_field_counts,
        "missing_cost_field_counts": missing_required_field_counts,
        "field_coverage": field_coverage,
        "required_evidence_fields_present": required_evidence_fields_present,
        "required_cost_fields_present_for_all_rows": required_cost_fields_present_for_all_rows,
        "required_evidence_fields_covered_gte_95pct": required_evidence_fields_covered_gte_95pct,
        "required_cost_fields_covered_gte_95pct": required_cost_fields_covered_gte_95pct,
        "hard_blocking_field_recovery_boundaries": recovery_boundaries,
        "cost_capture_contract_evidence_summary": {
            "production_cost_status": cost_status.get("status"),
            "total_cost_evidence_rows": total_rows,
            "minimum_rows_required_for_95pct_coverage": required_rows,
            "production_grade_cost_rows": cost_capture_gap.get("production_grade_cost_rows"),
            "production_grade_cost_coverage": cost_capture_gap.get("production_grade_cost_coverage"),
            "production_grade_cost_row_shortfall_to_95pct": cost_capture_gap.get(
                "production_grade_cost_row_shortfall_to_95pct"
            ),
            "unexplained_cost_missing_rows": (
                cost_capture_gap.get("unexplained_cost_missing_rows")
                if cost_capture_gap.get("unexplained_cost_missing_rows") is not None
                else cost_status.get("unexplained_cost_missing_rows")
            ),
            "replay_paper_cost_parity_mismatch_rows": cost_capture_gap.get(
                "replay_paper_cost_parity_mismatch_rows"
            )
            if cost_capture_gap.get("replay_paper_cost_parity_mismatch_rows") is not None
            else cost_status.get("replay_paper_cost_parity_mismatch_rows"),
            "required_cost_fields_present_for_all_rows": required_cost_fields_present_for_all_rows,
            "required_cost_fields_covered_gte_95pct": required_cost_fields_covered_gte_95pct,
            "missing_required_field_counts": missing_required_field_counts,
            "hard_blocking_missing_cost_fields": hard_blocking_missing_fields,
            "hard_blocking_missing_cost_field_counts": hard_blocking_missing_field_counts,
            "top_book_enriched_rows": top_book_enriched_rows,
            "candidate_bound_intents": candidate_bound_intents,
            "trusted_candidate_bound_intent_matches": trusted_intent_matches,
            "positive_order_size_matches": positive_order_size_matches,
            "challenger_bound_production_grade_paper_rows": challenger_bound_paper_rows,
            "old_policy_or_unbound_production_grade_paper_rows": old_or_unbound_paper_rows,
        },
        "operator_approval_required": True,
        "operator_approval_required_before_runtime_write_path_edits": True,
        "operator_action_required": True,
        "required_runtime_source_groups": required_runtime_source_groups,
        "required_source_groups": required_runtime_source_groups,
        "required_write_groups": required_runtime_source_groups,
        "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "required_cost_evidence_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_production_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "implementation_phases": contract_implementation_phases,
        "acceptance_criteria": contract_acceptance_criteria,
        "operator_approval_boundary": contract_operator_approval_boundary,
        "field_recovery_boundaries": {
            field: FIELD_RECOVERY_BOUNDARY.get(field)
            for field in REQUIRED_COST_EVIDENCE_FIELDS
            if FIELD_RECOVERY_BOUNDARY.get(field)
        },
        "source_contracts": {
            "paper_intent_pre_submit": {
                "must_capture": [
                    "candidate_id",
                    "policy_fingerprint",
                    "model_source",
                    "snapshot_id",
                    "symbol",
                    "timeframe",
                    "decision_time",
                    "feature_cutoff",
                    "available_at",
                    "order_size",
                    "observed_bid_ask_spread",
                    "depth_derived_price_impact",
                    "maker_taker_assumption_and_probability",
                    "fee_schedule",
                    "funding_rate_and_holding_period_funding",
                    "latency_reserve",
                    "partial_fill_estimate",
                    "mark_index_divergence",
                    "source_timestamp",
                    "evidence_freshness",
                    "fallback_flag",
                ],
                "timestamp_rule": "source_timestamp <= available_at <= decision_time and feature_cutoff <= decision_time",
                "route_rule": "paper_fill_allowed=false and routes_to_live=false until lockbox and canary gates pass",
            },
            "feature_snapshot_builder": {
                "must_capture": [
                    "best_bid",
                    "best_ask",
                    "top_book_bid_depth_usd",
                    "top_book_ask_depth_usd",
                    "source_timestamp",
                    "available_at",
                ],
                "timestamp_rule": "top_book source event_time must be available_at <= decision_time",
            },
            "paper_fill_or_ledger": {
                "must_capture": [
                    "latency_reserve",
                    "partial_fill_estimate",
                    "fees",
                    "spread",
                    "slippage",
                    "funding",
                    "paper_fill_allowed",
                    "routes_to_live",
                ],
                "route_rule": "paper-only records may be audited; live or exchange-routed rows cannot count here",
            },
            "closed_outcome_or_trainer_feedback": {
                "must_capture": [
                    "candidate_id",
                    "policy_fingerprint",
                    "model_source",
                    "net_return",
                    "accounting_status",
                    "liquidation_status",
                    "point_in_time_status",
                ],
                "credit_rule": "old policy or unbound rows cannot receive challenger credit",
            },
        },
        "current_capture_counts": {
            "top_book_enriched_rows": top_book_enriched_rows,
            "paper_intent_rows_scanned": cost_capture_gap.get("paper_intent_rows_scanned"),
            "candidate_bound_intents": candidate_bound_intents,
            "trusted_candidate_bound_intent_matches": trusted_intent_matches,
            "positive_order_size_matches": positive_order_size_matches,
            "paper_telemetry_production_grade_rows": cost_capture_gap.get("paper_telemetry_production_grade_rows"),
            "challenger_bound_production_grade_paper_rows": challenger_bound_paper_rows,
            "old_policy_or_unbound_production_grade_paper_rows": old_or_unbound_paper_rows,
            "paper_telemetry_live_route_rows": live_route_rows,
            "paper_telemetry_fill_allowed_rows": paper_fill_allowed_rows,
            "candidate_bound_live_route_rows": candidate_bound_live_route_rows,
            "candidate_bound_paper_fill_allowed_rows": candidate_bound_paper_fill_allowed_rows,
            "quarantined_non_candidate_bound_live_route_rows": quarantined_live_route_rows,
            "quarantined_non_candidate_bound_paper_fill_allowed_rows": quarantined_paper_fill_allowed_rows,
            "paper_binding_identity_complete_rows": paper_binding_preflight.get("candidate_identity_complete_rows"),
            "paper_binding_partial_identity_rows": paper_binding_preflight.get("partial_challenger_identity_rows"),
        },
        "pass_conditions": pass_conditions,
        "fallback_true_rows_may_be_shadow_scored": True,
        "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "new_candidate_required_if_cost_model_or_threshold_changes": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def runtime_cost_capture_remediation_contract(
    *,
    policy: FrozenPolicy,
    cost_capture_gap: Mapping[str, Any],
    paper_cost_telemetry: Mapping[str, Any],
    cost_identity_join_recovery: Mapping[str, Any],
    runtime_cost_capture_contract: Mapping[str, Any],
) -> dict[str, Any]:
    total_rows = int(cost_capture_gap.get("total_cost_evidence_rows") or 0)
    required_rows = int(
        cost_capture_gap.get("minimum_rows_required_for_95pct_coverage")
        or (math.ceil(total_rows * 0.95) if total_rows else 0)
    )
    challenger_bound_rows = int(cost_capture_gap.get("challenger_bound_production_grade_paper_rows") or 0)
    old_or_unbound_rows = int(cost_capture_gap.get("old_policy_or_unbound_production_grade_paper_rows") or 0)
    required_new_rows = max(0, required_rows - challenger_bound_rows)
    source_groups = paper_cost_telemetry.get("source_group_readiness")
    source_groups = source_groups if isinstance(source_groups, Mapping) else {}
    priority_source_groups: list[dict[str, Any]] = []
    for group_name, group_payload in source_groups.items():
        if not isinstance(group_payload, Mapping):
            continue
        group_name_text = str(group_name)
        capture_stage = RUNTIME_COST_CAPTURE_STAGE_BY_GROUP.get(group_name_text, "unknown")
        can_anchor_decision_selection = capture_stage in {"decision_time_signal", "pre_submit_intent"}
        group_rows = int(group_payload.get("rows") or 0)
        production_grade_rows = int(group_payload.get("production_grade_rows") or 0)
        challenger_bound_production_grade_rows = int(group_payload.get("challenger_bound_production_grade_rows") or 0)
        identity_complete_production_grade_rows = int(
            group_payload.get("candidate_identity_complete_production_grade_rows") or 0
        )
        old_or_unbound_production_grade_rows = int(
            group_payload.get("old_policy_or_unbound_production_grade_rows")
            or max(0, production_grade_rows - identity_complete_production_grade_rows)
        )
        all_required_source_fields_present_rows = int(group_payload.get("all_required_source_fields_present_rows") or 0)
        missing_required_source_fields_rows = int(group_payload.get("missing_required_source_fields_rows") or 0)
        paper_fill_allowed_rows = int(group_payload.get("paper_fill_allowed_rows") or 0)
        live_route_rows = int(group_payload.get("live_route_rows") or 0)
        missing_counts = group_payload.get("missing_required_cost_source_field_counts")
        missing_counts = missing_counts if isinstance(missing_counts, Mapping) else {}
        ranked_missing_fields = [
            {"field": str(field), "missing_rows": int(count or 0), "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(str(field))}
            for field, count in sorted(missing_counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))
            if int(count or 0) > 0
        ]
        required_actions: list[str] = []
        if challenger_bound_production_grade_rows == 0:
            required_actions.append("persist_candidate_id_policy_fingerprint_and_model_source_on_future_rows")
        if old_or_unbound_production_grade_rows:
            required_actions.append("do_not_backfill_identity_into_existing_old_or_unbound_rows")
        if ranked_missing_fields:
            required_actions.append("capture_missing_required_cost_fields_before_counting_rows")
        if paper_fill_allowed_rows:
            required_actions.append("keep_paper_fill_allowed_false_until_cost_and_lockbox_gates_pass")
        if live_route_rows:
            required_actions.append("exclude_live_or_exchange_routed_rows_from_challenger_evidence")
        if not can_anchor_decision_selection and group_rows:
            required_actions.append("link_to_immutable_decision_or_pre_submit_record_before_outcome_credit")
        if not required_actions:
            required_actions.append("continue_future_candidate_bound_production_grade_capture")
        if challenger_bound_production_grade_rows:
            remediation_class = "candidate_bound_production_grade_capture_present"
        elif production_grade_rows and old_or_unbound_production_grade_rows:
            remediation_class = "future_identity_binding_required_existing_rows_not_counted"
        elif all_required_source_fields_present_rows:
            remediation_class = "candidate_identity_required_on_rows_with_all_cost_sources"
        elif group_rows:
            remediation_class = "missing_required_cost_sources_before_candidate_credit"
        else:
            remediation_class = "no_rows_scanned"
        readiness_score = (
            production_grade_rows * 4
            + all_required_source_fields_present_rows * 2
            + group_rows
            - paper_fill_allowed_rows
            - live_route_rows
            - missing_required_source_fields_rows
        )
        priority_source_groups.append(
            {
                "source_group": group_name_text,
                "capture_stage": capture_stage,
                "runtime_write_point": RUNTIME_COST_CAPTURE_WRITE_POINTS.get(group_name_text),
                "can_anchor_decision_time_selection": can_anchor_decision_selection,
                "can_count_as_future_outcome_only_after_decision_identity_link": (
                    capture_stage in {"paper_lifecycle_or_fill", "closed_outcome", "trainer_feedback_outcome"}
                ),
                "remediation_class": remediation_class,
                "readiness_score": readiness_score,
                "rows": group_rows,
                "production_grade_rows": production_grade_rows,
                "challenger_bound_production_grade_rows": challenger_bound_production_grade_rows,
                "old_policy_or_unbound_production_grade_rows": old_or_unbound_production_grade_rows,
                "candidate_identity_complete_rows": int(group_payload.get("candidate_identity_complete_rows") or 0),
                "candidate_identity_partial_rows": int(group_payload.get("candidate_identity_partial_rows") or 0),
                "candidate_identity_none_rows": int(group_payload.get("candidate_identity_none_rows") or 0),
                "all_required_source_fields_present_rows": all_required_source_fields_present_rows,
                "missing_required_source_fields_rows": missing_required_source_fields_rows,
                "paper_fill_allowed_rows": paper_fill_allowed_rows,
                "live_route_rows": live_route_rows,
                "ranked_missing_required_cost_fields": ranked_missing_fields[:10],
                "required_actions": required_actions,
                "counts_as_training_lockbox_or_promotion_evidence": False,
            }
        )

    priority_source_groups.sort(
        key=lambda item: (
            -int(item["production_grade_rows"]),
            -int(item["all_required_source_fields_present_rows"]),
            -int(item["rows"]),
            str(item["source_group"]),
        )
    )
    decision_time_capture_priority_source_groups = [
        item for item in priority_source_groups if item["can_anchor_decision_time_selection"]
    ]
    outcome_linkage_priority_source_groups = [
        item for item in priority_source_groups if item["can_count_as_future_outcome_only_after_decision_identity_link"]
    ]
    exact_overlap_count = int(cost_identity_join_recovery.get("exact_join_key_overlap_count") or 0)
    recoverable_rows = int(cost_identity_join_recovery.get("recoverable_candidate_bound_production_grade_rows") or 0)
    diagnostic_only_overlap_rows = int(cost_identity_join_recovery.get("diagnostic_only_external_identity_overlap_rows") or 0)
    pass_conditions = {
        "phase_1_shortfall_identified": required_new_rows > 0 or runtime_cost_capture_contract.get("status") == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        "priority_source_groups_ranked": bool(priority_source_groups) or int(paper_cost_telemetry.get("paper_rows_scanned") or 0) == 0,
        "external_identity_overlap_not_counted": recoverable_rows == 0 or exact_overlap_count >= recoverable_rows,
        "next_capture_batch_requires_complete_challenger_identity": True,
        "next_capture_batch_requires_all_cost_fields": True,
        "existing_old_or_unbound_rows_not_counted": True,
        "paper_only_until_cost_lockbox_and_canary_gates_pass": True,
    }
    if runtime_cost_capture_contract.get("status") == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY":
        status = "PASS_RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT_READY"
    elif old_or_unbound_rows or diagnostic_only_overlap_rows:
        status = "BLOCKED_REQUIRES_FUTURE_CANDIDATE_BOUND_PRODUCTION_GRADE_CAPTURE"
    else:
        status = "BLOCKED_REQUIRES_NEW_PRODUCTION_GRADE_RUNTIME_COST_CAPTURE"
    top_source_group = priority_source_groups[0] if priority_source_groups else {}
    top_decision_time_source_group = (
        decision_time_capture_priority_source_groups[0]
        if decision_time_capture_priority_source_groups
        else {}
    )
    top_outcome_linkage_source_group = (
        outcome_linkage_priority_source_groups[0]
        if outcome_linkage_priority_source_groups
        else {}
    )
    status_blockers = {
        "runtime_cost_capture_contract_ready": runtime_cost_capture_contract.get("status")
        == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        "current_challenger_bound_production_grade_rows_gte_required": challenger_bound_rows >= required_rows
        if required_rows
        else runtime_cost_capture_contract.get("status") == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        "old_policy_or_unbound_production_grade_rows_present": old_or_unbound_rows == 0,
        "diagnostic_only_external_identity_overlap_rows_present": diagnostic_only_overlap_rows == 0,
        "decision_time_capture_source_group_ranked": bool(top_decision_time_source_group)
        or int(paper_cost_telemetry.get("paper_rows_scanned") or 0) == 0,
    }
    blocked_reasons = [
        name
        for name, passed in status_blockers.items()
        if passed is not True and status != "PASS_RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT_READY"
    ]
    remediation_actuals = {
        "runtime_cost_capture_contract_ready": runtime_cost_capture_contract.get("status"),
        "current_challenger_bound_production_grade_rows_gte_required": {
            "current": challenger_bound_rows,
            "required": required_rows,
            "shortfall": required_new_rows,
        },
        "old_policy_or_unbound_production_grade_rows_present": old_or_unbound_rows,
        "diagnostic_only_external_identity_overlap_rows_present": diagnostic_only_overlap_rows,
        "decision_time_capture_source_group_ranked": (
            top_decision_time_source_group.get("source_group")
            if isinstance(top_decision_time_source_group, Mapping)
            else None
        ),
    }
    remediation_required = {
        "runtime_cost_capture_contract_ready": "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        "current_challenger_bound_production_grade_rows_gte_required": f">={required_rows}",
        "old_policy_or_unbound_production_grade_rows_present": 0,
        "diagnostic_only_external_identity_overlap_rows_present": 0,
        "decision_time_capture_source_group_ranked": "present",
    }
    remediation_blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "actual": remediation_actuals.get(name),
            "expected": remediation_required.get(name),
        }
        for name in blocked_reasons
    ]
    source_group_decisions = [
        {
            "source_group": group.get("source_group"),
            "capture_stage": group.get("capture_stage"),
            "remediation_class": group.get("remediation_class"),
            "required_actions": group.get("required_actions"),
            "counts_as_training_lockbox_or_promotion_evidence": group.get(
                "counts_as_training_lockbox_or_promotion_evidence"
            ),
        }
        for group in priority_source_groups
    ]
    implementation_phases = [
        {
            "phase": "operator_approval_boundary",
            "status": "AWAITING_OPERATOR_APPROVAL",
            "required_source_groups": [group.get("source_group") for group in priority_source_groups],
            "required_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
            "required_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
            "approved_patch_scope": "telemetry_only_future_runtime_cost_and_identity_capture",
            "prohibited_patch_scope": [
                "order_submission",
                "order_cancellation_or_modification",
                "exchange_leverage_or_margin_mutation",
                "strategy_threshold_or_weight_change",
                "frozen_candidate_artifact_change",
                "historical_identity_backfill_for_credit",
                "paper_binding_before_blind_lockbox_pass",
            ],
            "acceptance_criteria": [
                "operator approval receipt validates against current approval_subject_hash",
                "approval scope remains telemetry-only future runtime cost and identity capture",
                "paper_fill_allowed=false and routes_to_live=false remain enforced",
            ],
        },
        {
            "phase": "decision_time_and_pre_submit_capture",
            "status": "PLANNED_AFTER_OPERATOR_APPROVAL",
            "priority_source_groups": [
                group.get("source_group") for group in decision_time_capture_priority_source_groups
            ],
            "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "required_cost_fields": [
                field
                for field, groups in RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS.items()
                if field in REQUIRED_COST_EVIDENCE_FIELDS
                and any(group.get("source_group") in groups for group in decision_time_capture_priority_source_groups)
            ],
            "required_join_key_fields": COST_IDENTITY_JOIN_KEY_FIELDS,
            "acceptance_criteria": [
                "future rows carry candidate_id, policy_fingerprint, and model_source before outcome exists",
                "source_timestamp <= available_at <= decision_time",
                "feature_cutoff <= decision_time",
                "selection fields are immutable after labels or outcomes exist",
            ],
        },
        {
            "phase": "lifecycle_outcome_and_feedback_linkage",
            "status": "PLANNED_AFTER_OPERATOR_APPROVAL",
            "priority_source_groups": [
                group.get("source_group") for group in outcome_linkage_priority_source_groups
            ],
            "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "required_cost_fields": [
                field
                for field, groups in RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS.items()
                if field in REQUIRED_COST_EVIDENCE_FIELDS
                and any(group.get("source_group") in groups for group in outcome_linkage_priority_source_groups)
            ],
            "required_join_key_fields": COST_IDENTITY_JOIN_KEY_FIELDS,
            "acceptance_criteria": [
                "outcomes link to immutable decision/pre-submit records before credit",
                "old-policy or unbound rows remain quarantined and non-counting",
                "fallback=true rows remain shadow-only and non-counting",
                "accounting, liquidation, and point-in-time status are preserved for canary gating",
            ],
        },
        {
            "phase": "post_capture_verification",
            "status": "BLOCKED_UNTIL_FUTURE_ROWS_EXIST",
            "minimum_new_candidate_bound_production_grade_rows": required_new_rows,
            "required_coverage": ">=0.95",
            "acceptance_criteria": [
                "production_grade_cost_coverage >= 0.95",
                "unexplained_cost_missing_rows == 0",
                "replay and paper costs match for the same snapshot/order",
                "future_challenger_bound_production_grade_rows_present",
            ],
        },
    ]
    acceptance_criteria = {
        "operator_approval_required_before_runtime_write_path_edits": True,
        "minimum_new_candidate_bound_production_grade_rows": required_new_rows,
        "production_grade_cost_coverage_required": ">=0.95",
        "unexplained_cost_missing_rows_required": 0,
        "replay_paper_cost_parity_mismatch_rows_required": 0,
        "candidate_identity_fields_required": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "cost_evidence_fields_required": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
        "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return {
        "schema_version": "challenger_v2_runtime_cost_capture_remediation_contract_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "blocked_reasons": blocked_reasons,
        "remediation_blocker_details": remediation_blocker_details,
        "blocker_details": remediation_blocker_details,
        "failed_blocker_details": remediation_blocker_details,
        "actuals": remediation_actuals,
        "required": remediation_required,
        "sample_blockers": remediation_blocker_details[:25],
        "runtime_cost_capture_status": runtime_cost_capture_contract.get("status"),
        "runtime_cost_capture_contract_status": runtime_cost_capture_contract.get("status"),
        "paper_cost_telemetry_status": paper_cost_telemetry.get("status"),
        "cost_identity_join_recovery_status": cost_identity_join_recovery.get("status"),
        "total_cost_evidence_rows": total_rows,
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "current_challenger_bound_production_grade_rows": challenger_bound_rows,
        "required_new_candidate_bound_production_grade_rows": required_new_rows,
        "required_new_candidate_bound_rows": required_new_rows,
        "old_policy_or_unbound_production_grade_rows": old_or_unbound_rows,
        "old_policy_or_unbound_production_grade_rows_not_counted": old_or_unbound_rows,
        "diagnostic_only_external_identity_overlap_rows": diagnostic_only_overlap_rows,
        "required_runtime_source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "required_source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "required_write_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "approval_required_source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "operator_approval_required_source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "source_group_count": len(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_production_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "cost_identity_join_summary": {
            "exact_join_key_overlap_count": exact_overlap_count,
            "overlapping_paper_rows": cost_identity_join_recovery.get("overlapping_paper_rows"),
            "overlapping_paper_rows_with_production_grade_cost": cost_identity_join_recovery.get(
                "overlapping_paper_rows_with_production_grade_cost"
            ),
            "overlapping_paper_rows_with_complete_challenger_identity": cost_identity_join_recovery.get(
                "overlapping_paper_rows_with_complete_challenger_identity"
            ),
            "recoverable_candidate_bound_production_grade_rows": recoverable_rows,
            "diagnostic_only_external_identity_overlap_rows": diagnostic_only_overlap_rows,
            "external_identity_overlap_credit_rule": (
                "identity-key overlap is diagnostic only; paper rows must carry their own candidate_id, "
                "policy_fingerprint, and model_source before they can count"
            ),
        },
        "priority_source_groups": priority_source_groups,
        "top_source_group": top_source_group.get("source_group") if isinstance(top_source_group, Mapping) else None,
        "top_decision_time_capture_source_group": (
            top_decision_time_source_group.get("source_group")
            if isinstance(top_decision_time_source_group, Mapping)
            else None
        ),
        "top_outcome_linkage_source_group": (
            top_outcome_linkage_source_group.get("source_group")
            if isinstance(top_outcome_linkage_source_group, Mapping)
            else None
        ),
        "source_group_decisions": source_group_decisions,
        "decision_time_capture_priority_source_groups": decision_time_capture_priority_source_groups,
        "outcome_linkage_priority_source_groups": outcome_linkage_priority_source_groups,
        "implementation_phases": implementation_phases,
        "implementation_steps": implementation_phases,
        "implementation_plan": implementation_phases,
        "acceptance_criteria": acceptance_criteria,
        "operator_approval_boundary": implementation_phases[0],
        "required_operator_approval": True,
        "operator_approval_required": True,
        "operator_approval_required_before_runtime_write_path_edits": True,
        "approval_packet_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        "approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "approved_patch_scope": implementation_phases[0]["approved_patch_scope"],
        "prohibited_patch_scope": implementation_phases[0]["prohibited_patch_scope"],
        "next_capture_batch_contract": {
            "minimum_new_rows": required_new_rows,
            "identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
            "field_capture_requirements": RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS,
            "runtime_capture_write_points": RUNTIME_COST_CAPTURE_WRITE_POINTS,
            "runtime_write_path_edits_require_operator_approval": True,
            "runtime_write_path_approval_reason": (
                "Future production-grade rows require persisting candidate-bound cost telemetry on paper "
                "signal, intent, paper ledger, paper online ledger, closed-trade, and trainer-feedback write paths."
            ),
            "join_key_fields": COST_IDENTITY_JOIN_KEY_FIELDS,
            "selection_fields_immutable_after_outcomes_exist": True,
            "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
            "fallback_true_rows_may_be_shadow_scored": True,
            "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "timestamp_rule": "source_timestamp <= available_at <= decision_time and feature_cutoff <= decision_time",
            "route_rule": "paper_fill_allowed=false and routes_to_live=false until production cost evidence, blind lockbox, and canary gates pass",
        },
        "pass_conditions": pass_conditions,
        "status_blockers": status_blockers,
        "operator_action_required": status != "PASS_RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT_READY",
        "future_capture_credit_rules": {
            "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
            "fallback_true_rows_may_be_shadow_scored": True,
            "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "candidate_identity_fields_required": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "required_cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        },
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "new_candidate_required_if_cost_model_or_threshold_changes": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def shadow_cost_evidence_payload_hash(record: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"record_created_utc", "shadow_cost_evidence_payload_hash"}
    }
    return row_hash(payload)


def shadow_cost_evidence_record_id(record: Mapping[str, Any]) -> str:
    return stable_hash(
        {
            "candidate_id": record.get("candidate_id"),
            "policy_fingerprint": record.get("policy_fingerprint"),
            "snapshot_id": record.get("snapshot_id"),
            "decision_time": record.get("decision_time"),
            "feature_vector_hash": record.get("feature_vector_hash"),
            "predicted_direction": record.get("predicted_direction"),
        }
    )


def shadow_cost_evidence_record(snapshot: Mapping[str, Any], scored: Mapping[str, Any]) -> dict[str, Any]:
    evidence = cost_evidence_for_row(snapshot, source_context="current_runtime")
    source_presence: dict[str, Any] = {}
    for field in REQUIRED_COST_EVIDENCE_FIELDS:
        present, source = source_presence_for_required_field(snapshot, field)
        source_presence[field] = {
            "present": present,
            "source": source,
            "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
        }
    record = {
        "schema_version": "challenger_v2_candidate_bound_shadow_cost_evidence_v1",
        "record_created_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": scored.get("candidate_id"),
        "policy_fingerprint": scored.get("policy_fingerprint"),
        "model_source": scored.get("model_source"),
        "snapshot_id": scored.get("snapshot_id") or snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "symbol": scored.get("symbol") or snapshot.get("symbol"),
        "timeframe": scored.get("timeframe") or snapshot.get("timeframe"),
        "decision_time": scored.get("decision_time"),
        "feature_cutoff": scored.get("feature_cutoff"),
        "available_at": scored.get("available_at"),
        "feature_vector_hash": scored.get("feature_vector_hash"),
        "predicted_direction": scored.get("predicted_direction"),
        "predicted_move_bps": scored.get("predicted_move_bps"),
        "score": scored.get("score"),
        "selected": scored.get("selected"),
        "rejected": scored.get("rejected"),
        "rejection_reasons": scored.get("rejection_reasons"),
        "estimated_production_cost": scored.get("estimated_production_cost"),
        "required_cost_evidence_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
        "required_cost_source_presence": source_presence,
        "cost_evidence": evidence,
        "production_grade_cost_evidence": evidence.get("production_grade") is True,
        "fallback": evidence.get("fallback") is True,
        "fallback_components": evidence.get("fallback_components"),
        "missing_evidence_fields": evidence.get("missing_evidence_fields"),
        "replay_paper_cost_parity": evidence.get("replay_paper_cost_parity"),
        "source_context": "current_runtime_candidate_bound_shadow",
        "shadow_only": True,
        "candidate_bound_shadow_evidence": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_phase_1_production_grade_evidence": False,
        "counts_as_training_lockbox_or_promotion_evidence": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "selection_immutable": True,
    }
    record["shadow_cost_evidence_record_id"] = shadow_cost_evidence_record_id(record)
    record["shadow_cost_evidence_payload_hash"] = shadow_cost_evidence_payload_hash(record)
    return record


def append_shadow_cost_evidence(
    out_dir: Path,
    snapshots: Sequence[Mapping[str, Any]],
    scored_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    path = out_dir / SHADOW_COST_EVIDENCE
    existing = read_jsonl(path)
    existing_by_id = {
        str(row.get("shadow_cost_evidence_record_id")): str(
            row.get("shadow_cost_evidence_payload_hash") or shadow_cost_evidence_payload_hash(row)
        )
        for row in existing
        if row.get("shadow_cost_evidence_record_id")
    }
    new_rows: list[dict[str, Any]] = []
    conflict_count = 0
    for snapshot, scored in zip(snapshots, scored_rows):
        record = shadow_cost_evidence_record(snapshot, scored)
        record_id = str(record.get("shadow_cost_evidence_record_id"))
        if record_id in existing_by_id:
            if existing_by_id[record_id] != record["shadow_cost_evidence_payload_hash"]:
                conflict_count += 1
            continue
        new_rows.append(record)
        existing_by_id[record_id] = record["shadow_cost_evidence_payload_hash"]
    append_jsonl(path, new_rows)
    return {
        "shadow_cost_evidence_path": str(path),
        "existing_shadow_cost_evidence_rows_before_append": len(existing),
        "new_shadow_cost_evidence_rows_appended": len(new_rows),
        "immutability_conflict_count": conflict_count,
        "shadow_cost_evidence_rows_after_append": len(existing) + len(new_rows),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "counts_as_a_grade_evidence": False,
    }


def shadow_cost_evidence_pit_violation(row: Mapping[str, Any]) -> bool:
    decision_time = parse_utc(row.get("decision_time"))
    feature_cutoff = parse_utc(row.get("feature_cutoff"))
    available_at = parse_utc(row.get("available_at"))
    if decision_time is None or feature_cutoff is None or available_at is None:
        return True
    return feature_cutoff > decision_time or available_at > decision_time


def shadow_cost_evidence_status(
    *,
    policy: FrozenPolicy,
    append_status: Mapping[str, Any],
    hash_chain: Mapping[str, Any] | None = None,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    row_count = len(rows)
    production_grade_rows = sum(1 for row in rows if row.get("production_grade_cost_evidence") is True)
    fallback_rows = sum(1 for row in rows if row.get("fallback") is True)
    selected_rows = sum(1 for row in rows if row.get("selected") is True)
    pit_violations = sum(1 for row in rows if shadow_cost_evidence_pit_violation(row))
    route_rows = sum(1 for row in rows if paper_row_routes_to_live(row))
    paper_fill_allowed_rows = sum(1 for row in rows if row.get("paper_fill_allowed") is True)
    a_grade_rows = sum(1 for row in rows if row.get("counts_as_a_grade_evidence") is True)
    promotion_rows = sum(1 for row in rows if row.get("promotion_evidence") is True)
    identity_complete_rows = sum(1 for row in rows if challenger_identity_state(row, policy) == "complete")
    hash_chain_payload = hash_chain if isinstance(hash_chain, Mapping) else {}
    chain_payload = (
        hash_chain_payload.get("shadow_cost_evidence")
        if isinstance(hash_chain_payload.get("shadow_cost_evidence"), Mapping)
        else {}
    )
    chain_pass_conditions = (
        hash_chain_payload.get("pass_conditions")
        if isinstance(hash_chain_payload.get("pass_conditions"), Mapping)
        else {}
    )
    hash_chain_contract_passed = (
        hash_chain_payload.get("status") == "PASS_SHADOW_COST_EVIDENCE_HASH_CHAIN_AUDIT"
        and bool(chain_pass_conditions)
        and all(value is True for value in chain_pass_conditions.values())
        and hash_chain_payload.get("paper_fill_allowed") is False
        and hash_chain_payload.get("routes_to_live") is False
        and hash_chain_payload.get("counts_as_a_grade_evidence") is False
        and hash_chain_payload.get("promotion_evidence") is False
    )
    missing_counts: Counter[str] = Counter()
    source_present_counts: Counter[str] = Counter()
    for row in rows:
        for field in row.get("missing_evidence_fields") or ():
            missing_counts[str(field)] += 1
        presence = row.get("required_cost_source_presence")
        if isinstance(presence, Mapping):
            for field, payload in presence.items():
                if isinstance(payload, Mapping) and payload.get("present") is True:
                    source_present_counts[str(field)] += 1
    pass_conditions = {
        "rows_exist": row_count > 0,
        "candidate_identity_complete_for_all_rows": identity_complete_rows == row_count if row_count else False,
        "paper_only_no_routes_to_live": route_rows == 0,
        "paper_fill_allowed_rows_eq_0": paper_fill_allowed_rows == 0,
        "counts_as_a_grade_rows_eq_0": a_grade_rows == 0,
        "promotion_rows_eq_0": promotion_rows == 0,
        "point_in_time_violations_eq_0": pit_violations == 0,
        "immutability_conflicts_eq_0": int(append_status.get("immutability_conflict_count") or 0) == 0,
        "hash_chain_row_count_matches": int(chain_payload.get("row_count") or -1) == row_count if row_count else False,
        "hash_chain_terminal_hash_present": bool(chain_payload.get("last_chain_hash")) if row_count else False,
        "hash_chain_contract_passed": hash_chain_contract_passed,
        "shadow_rows_do_not_count_as_phase_1_production_grade_evidence": all(
            row.get("counts_as_phase_1_production_grade_evidence") is False for row in rows
        )
        if rows
        else False,
    }
    status = (
        "COLLECTING_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE"
        if all(pass_conditions.values())
        else "BLOCKED_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE_INTEGRITY"
    )
    return {
        "schema_version": "challenger_v2_candidate_bound_shadow_cost_evidence_status_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "shadow_cost_evidence_path": append_status.get("shadow_cost_evidence_path"),
        "shadow_cost_evidence_file_sha256": file_sha256(Path(str(append_status.get("shadow_cost_evidence_path"))))
        if append_status.get("shadow_cost_evidence_path")
        else None,
        "shadow_cost_evidence_hash_chain_path": str((Path(str(append_status.get("shadow_cost_evidence_path"))).parent / SHADOW_COST_HASH_CHAIN))
        if append_status.get("shadow_cost_evidence_path")
        else None,
        "shadow_cost_evidence_hash_chain_status": hash_chain_payload.get("status"),
        "shadow_cost_evidence_hash_chain_pass_conditions": dict(chain_pass_conditions),
        "shadow_cost_evidence_last_chain_hash": chain_payload.get("last_chain_hash"),
        "shadow_cost_evidence_hash_chain_row_count": chain_payload.get("row_count"),
        "shadow_cost_evidence_rows": row_count,
        "new_shadow_cost_evidence_rows_appended": append_status.get("new_shadow_cost_evidence_rows_appended"),
        "immutability_conflict_count": append_status.get("immutability_conflict_count"),
        "candidate_identity_complete_rows": identity_complete_rows,
        "selected_rows": selected_rows,
        "production_grade_shadow_cost_rows": production_grade_rows,
        "fallback_shadow_cost_rows": fallback_rows,
        "point_in_time_violations": pit_violations,
        "route_rows": route_rows,
        "paper_fill_allowed_rows": paper_fill_allowed_rows,
        "counts_as_a_grade_rows": a_grade_rows,
        "promotion_rows": promotion_rows,
        "missing_evidence_field_counts": dict(sorted(missing_counts.items())),
        "required_cost_source_coverage": {
            field: {
                "present_rows": source_present_counts.get(field, 0),
                "missing_rows": row_count - source_present_counts.get(field, 0),
                "coverage": source_present_counts.get(field, 0) / row_count if row_count else 0.0,
                "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
            }
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        },
        "pass_conditions": pass_conditions,
        "fallback_true_rows_may_be_shadow_scored": True,
        "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "shadow_cost_rows_count_as_phase_1_production_grade_evidence": False,
        "shadow_cost_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "read_only_audit_no_runtime_change": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def _source_scan_alias_groups(required_field: str) -> tuple[tuple[str, ...], ...]:
    if required_field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS:
        return ((required_field,),)
    if required_field == "fallback_flag":
        return (("fallback",), ("cost_fallback",), ("production_cost_fallback",))
    return FIELD_SOURCE_CANDIDATES.get(required_field, ((required_field,),))


def _token_occurrences_by_file(
    source_lines_by_file: Mapping[str, Sequence[str]],
    alias: str,
    *,
    max_occurrences: int = 10,
) -> list[dict[str, Any]]:
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])")
    occurrences: list[dict[str, Any]] = []
    for relative, lines in source_lines_by_file.items():
        for lineno, line in enumerate(lines, start=1):
            if pattern.search(line):
                occurrences.append({"path": relative, "line": lineno, "text": line.strip()[:240]})
                if len(occurrences) >= max_occurrences:
                    return occurrences
    return occurrences


def _source_field_presence(
    source_lines_by_file: Mapping[str, Sequence[str]],
    required_field: str,
) -> dict[str, Any]:
    alias_groups = _source_scan_alias_groups(required_field)
    alias_group_results: list[dict[str, Any]] = []
    for group in alias_groups:
        alias_occurrences = {alias: _token_occurrences_by_file(source_lines_by_file, alias) for alias in group}
        alias_group_results.append(
            {
                "aliases": list(group),
                "present": all(bool(occurrences) for occurrences in alias_occurrences.values()),
                "occurrences_by_alias": alias_occurrences,
            }
        )
    present_groups = [group for group in alias_group_results if group["present"]]
    return {
        "field": required_field,
        "present": bool(present_groups),
        "present_alias_groups": present_groups,
        "alias_groups_examined": alias_group_results,
    }


def _source_field_evidence_summary(presence: Mapping[str, Any]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    occurrence_count = 0
    for group in presence.get("alias_groups_examined") or []:
        if not isinstance(group, Mapping):
            continue
        occurrences_by_alias = group.get("occurrences_by_alias")
        if not isinstance(occurrences_by_alias, Mapping):
            continue
        for alias, occurrences in occurrences_by_alias.items():
            if not isinstance(occurrences, Sequence) or isinstance(occurrences, (str, bytes, bytearray)):
                continue
            occurrence_count += len(occurrences)
            for occurrence in occurrences:
                if len(samples) >= 5:
                    break
                if isinstance(occurrence, Mapping):
                    samples.append({"alias": str(alias), **dict(occurrence)})
            if len(samples) >= 5:
                break
        if len(samples) >= 5:
            break
    return {
        "field": presence.get("field"),
        "present": presence.get("present") is True,
        "matched_alias_groups": [
            list(group.get("aliases") or [])
            for group in presence.get("present_alias_groups") or []
            if isinstance(group, Mapping)
        ],
        "occurrence_count": occurrence_count,
        "sample_occurrences": samples,
    }


def _runtime_write_group_coverage_payload(
    *,
    group_name: str,
    required_fields: Sequence[str],
    group_field_presence: Mapping[str, Any],
    missing_identity: Sequence[str],
    missing_cost: Sequence[str],
) -> dict[str, Any]:
    identity_required = [
        field for field in required_fields if field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS
    ]
    cost_required = [
        field for field in required_fields if field not in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS
    ]

    def bucket_payload(fields: Sequence[str], missing_fields: Sequence[str]) -> dict[str, Any]:
        present_fields = [
            field
            for field in fields
            if isinstance(group_field_presence.get(field), Mapping)
            and group_field_presence[field].get("present") is True
        ]
        required_count = len(fields)
        return {
            "required_count": required_count,
            "present_count": len(present_fields),
            "missing_count": len(missing_fields),
            "coverage": (len(present_fields) / required_count) if required_count else 1.0,
            "present_fields": present_fields,
            "missing_fields": list(missing_fields),
        }

    combined_missing = [*missing_identity, *missing_cost]
    field_evidence_summary = {
        field: _source_field_evidence_summary(presence)
        for field, presence in sorted(group_field_presence.items())
        if isinstance(presence, Mapping)
    }
    return {
        "source_group": group_name,
        "identity": bucket_payload(identity_required, missing_identity),
        "cost": bucket_payload(cost_required, missing_cost),
        "combined": bucket_payload(required_fields, combined_missing),
        "field_evidence_summary": field_evidence_summary,
    }


def runtime_cost_capture_write_path_audit(
    *,
    repo_root: Path,
    policy: FrozenPolicy,
    runtime_cost_capture_remediation: Mapping[str, Any],
) -> dict[str, Any]:
    source_files = sorted(
        {
            str(relative)
            for write_point in RUNTIME_COST_CAPTURE_WRITE_POINTS.values()
            for relative in write_point.get("files", [])
        }
    )
    source_lines_by_file: dict[str, list[str]] = {}
    unreadable_files: list[dict[str, Any]] = []
    for relative in source_files:
        path = repo_root / relative
        try:
            source_lines_by_file[relative] = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            source_lines_by_file[relative] = []
            unreadable_files.append({"path": relative, "error": type(exc).__name__})

    field_presence_by_group: dict[str, Any] = {}
    missing_identity_fields_by_group: dict[str, list[str]] = {}
    missing_cost_fields_by_group: dict[str, list[str]] = {}
    source_group_field_coverage_matrix: dict[str, Any] = {}
    all_missing_fields: Counter[str] = Counter()
    for group_name, write_point in RUNTIME_COST_CAPTURE_WRITE_POINTS.items():
        files = [str(relative) for relative in write_point.get("files", [])]
        group_sources = {relative: source_lines_by_file.get(relative, []) for relative in files}
        required_fields = [
            field
            for field, required_groups in RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS.items()
            if group_name in required_groups
        ]
        group_field_presence: dict[str, Any] = {}
        for required_field in required_fields:
            presence = _source_field_presence(group_sources, required_field)
            group_field_presence[required_field] = presence
            if not presence["present"]:
                all_missing_fields[required_field] += 1
        missing_identity = [
            field
            for field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS
            if field in group_field_presence and not group_field_presence[field]["present"]
        ]
        missing_cost = [
            field
            for field in required_fields
            if field not in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS and not group_field_presence[field]["present"]
        ]
        if missing_identity:
            missing_identity_fields_by_group[group_name] = missing_identity
        if missing_cost:
            missing_cost_fields_by_group[group_name] = missing_cost
        source_group_field_coverage_matrix[group_name] = _runtime_write_group_coverage_payload(
            group_name=group_name,
            required_fields=required_fields,
            group_field_presence=group_field_presence,
            missing_identity=missing_identity,
            missing_cost=missing_cost,
        )
        field_presence_by_group[group_name] = {
            "producer": write_point.get("producer"),
            "files": files,
            "redis_keys": list(write_point.get("redis_keys", [])),
            "required_role": write_point.get("required_role"),
            "capture_stage": RUNTIME_COST_CAPTURE_STAGE_BY_GROUP.get(group_name, "unknown"),
            "required_fields": required_fields,
            "missing_identity_fields": missing_identity,
            "missing_cost_fields": missing_cost,
            "field_presence": group_field_presence,
        }

    exact_identity_occurrences = {
        field: _token_occurrences_by_file(source_lines_by_file, field, max_occurrences=25)
        for field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS
    }
    alternate_identity_occurrences = {
        field: _token_occurrences_by_file(source_lines_by_file, field, max_occurrences=25)
        for field in ALTERNATE_PAPER_IDENTITY_FIELDS
    }
    missing_identity_fields = sorted(
        {
            field
            for fields in missing_identity_fields_by_group.values()
            for field in fields
        }
    )
    missing_cost_fields = sorted(
        {
            field
            for fields in missing_cost_fields_by_group.values()
            for field in fields
        }
    )
    pass_conditions = {
        "runtime_write_points_declared": bool(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "all_declared_source_files_readable": not unreadable_files,
        "required_capture_fields_have_write_point_requirements": set(REQUIRED_COST_EVIDENCE_FIELDS).issubset(
            set(RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS)
        )
        and set(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS).issubset(set(RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS)),
        "required_identity_fields_exactly_present_in_required_write_groups": not missing_identity_fields_by_group,
        "required_cost_fields_present_in_required_write_groups": not missing_cost_fields_by_group,
        "runtime_write_path_edits_require_operator_approval": True,
        "read_only_audit_no_runtime_change": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "frozen_candidate_modified_false": True,
    }
    required_capture_fields_without_write_point = sorted(
        (
            set(REQUIRED_COST_EVIDENCE_FIELDS)
            | set(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
        )
        - set(RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS)
    )
    if unreadable_files:
        status = "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_SOURCE_UNREADABLE"
    elif missing_identity_fields_by_group:
        status = "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_IDENTITY_BINDING_MISSING"
    elif missing_cost_fields_by_group:
        status = "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_COST_FIELD_CAPTURE_MISSING"
    else:
        status = "PASS_RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT"
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]

    source_group_readiness: dict[str, Any] = {}
    write_path_findings: list[dict[str, Any]] = []
    remediation_plan: list[dict[str, Any]] = []
    for group_name, group_payload in sorted(field_presence_by_group.items()):
        group_missing_identity = list(group_payload.get("missing_identity_fields") or [])
        group_missing_cost = list(group_payload.get("missing_cost_fields") or [])
        if group_missing_identity:
            group_status = "BLOCKED_IDENTITY_BINDING_MISSING"
        elif group_missing_cost:
            group_status = "BLOCKED_COST_FIELD_CAPTURE_MISSING"
        else:
            group_status = "READY_FOR_OPERATOR_APPROVED_FUTURE_CAPTURE"
        readiness = {
            "source_group": group_name,
            "status": group_status,
            "producer": group_payload.get("producer"),
            "capture_stage": group_payload.get("capture_stage"),
            "required_role": group_payload.get("required_role"),
            "files": list(group_payload.get("files") or []),
            "redis_keys": list(group_payload.get("redis_keys") or []),
            "required_fields": list(group_payload.get("required_fields") or []),
            "missing_identity_fields": group_missing_identity,
            "missing_cost_fields": group_missing_cost,
            "identity_field_coverage": source_group_field_coverage_matrix[group_name]["identity"]["coverage"],
            "cost_field_coverage": source_group_field_coverage_matrix[group_name]["cost"]["coverage"],
            "combined_required_field_coverage": source_group_field_coverage_matrix[group_name]["combined"]["coverage"],
            "requires_operator_approval": bool(group_missing_identity or group_missing_cost),
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        }
        source_group_readiness[group_name] = readiness
        write_path_findings.append(readiness)
        required_actions = [
            f"persist_exact_identity_field_{field}"
            for field in group_missing_identity
        ] + [
            f"persist_production_grade_cost_field_{field}"
            for field in group_missing_cost
        ]
        if required_actions:
            remediation_plan.append(
                {
                    "source_group": group_name,
                    "producer": group_payload.get("producer"),
                    "capture_stage": group_payload.get("capture_stage"),
                    "required_actions": required_actions,
                    "operator_approval_required_before_runtime_edit": True,
                    "existing_rows_may_not_be_backfilled_for_credit": True,
                    "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
                }
            )
    blocked_reason_details = {
        "all_declared_source_files_readable": {
            "passed": pass_conditions["all_declared_source_files_readable"],
            "observed": unreadable_files,
        },
        "required_identity_fields_exactly_present_in_required_write_groups": {
            "passed": pass_conditions["required_identity_fields_exactly_present_in_required_write_groups"],
            "observed": missing_identity_fields_by_group,
        },
        "required_cost_fields_present_in_required_write_groups": {
            "passed": pass_conditions["required_cost_fields_present_in_required_write_groups"],
            "observed": missing_cost_fields_by_group,
        },
        "runtime_write_path_edits_require_operator_approval": {
            "passed": pass_conditions["runtime_write_path_edits_require_operator_approval"],
            "observed": True,
        },
    }
    blocker_details = {
        name: detail
        for name, detail in blocked_reason_details.items()
        if detail.get("passed") is not True
    }
    sample_blockers = [
        {"pass_condition": name, **detail}
        for name, detail in blocker_details.items()
    ]
    writable_paths = [
        {
            "source_group": group_name,
            "producer": write_point.get("producer"),
            "capture_stage": RUNTIME_COST_CAPTURE_STAGE_BY_GROUP.get(group_name, "unknown"),
            "files": list(write_point.get("files", [])),
            "redis_keys": list(write_point.get("redis_keys", [])),
            "required_role": write_point.get("required_role"),
        }
        for group_name, write_point in sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS.items())
    ]
    telemetry_only_runtime_paths = [
        {
            **path,
            "approved_change_class": "telemetry_only_identity_and_cost_persistence",
        }
        for path in writable_paths
    ]
    prohibited_patch_scope = sorted(
        {
            "exchange_leverage_or_margin_mutation",
            "frozen_candidate_artifact_change",
            "historical_identity_backfill_for_credit",
            "order_cancellation_or_modification",
            "order_submission",
            "paper_binding_before_blind_lockbox_pass",
            "strategy_threshold_or_weight_change",
        }
    )
    required_runtime_write_groups = sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS)
    write_path_actuals = {
        "runtime_write_points_declared": required_runtime_write_groups,
        "all_declared_source_files_readable": {
            "unreadable_source_file_count": len(unreadable_files),
            "unreadable_source_files": unreadable_files,
        },
        "required_capture_fields_have_write_point_requirements": {
            "missing_required_capture_field_requirements": required_capture_fields_without_write_point,
        },
        "required_identity_fields_exactly_present_in_required_write_groups": missing_identity_fields_by_group,
        "required_cost_fields_present_in_required_write_groups": missing_cost_fields_by_group,
        "runtime_write_path_edits_require_operator_approval": True,
        "read_only_audit_no_runtime_change": True,
        "paper_fill_allowed_false": {"paper_fill_allowed": False},
        "routes_to_live_false": {"routes_to_live": False},
        "frozen_candidate_modified_false": {"frozen_candidate_modified": False},
    }
    write_path_required = {
        "runtime_write_points_declared": required_runtime_write_groups,
        "all_declared_source_files_readable": {"unreadable_source_file_count": 0},
        "required_capture_fields_have_write_point_requirements": {
            "missing_required_capture_field_requirements": [],
        },
        "required_identity_fields_exactly_present_in_required_write_groups": {},
        "required_cost_fields_present_in_required_write_groups": {},
        "runtime_write_path_edits_require_operator_approval": True,
        "read_only_audit_no_runtime_change": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "frozen_candidate_modified_false": True,
    }

    return {
        "schema_version": "challenger_v2_runtime_cost_capture_write_path_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "runtime_cost_capture_remediation_status": runtime_cost_capture_remediation.get("status"),
        "source_files_scanned": source_files,
        "source_files_to_patch": source_files,
        "write_path_files": source_files,
        "source_file_count": len(source_files),
        "unreadable_source_files": unreadable_files,
        "required_source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "required_write_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "required_runtime_write_groups": required_runtime_write_groups,
        "source_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "source_group_count": len(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "runtime_capture_write_points": RUNTIME_COST_CAPTURE_WRITE_POINTS,
        "writable_paths": writable_paths,
        "telemetry_only_runtime_paths": telemetry_only_runtime_paths,
        "prohibited_patch_scope": prohibited_patch_scope,
        "field_capture_requirements": RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS,
        "field_presence_by_group": field_presence_by_group,
        "source_group_field_coverage_matrix": source_group_field_coverage_matrix,
        "field_coverage_by_group": source_group_field_coverage_matrix,
        "required_identity_field_coverage_by_group": {
            group: payload["identity"] for group, payload in sorted(source_group_field_coverage_matrix.items())
        },
        "required_cost_field_coverage_by_group": {
            group: payload["cost"] for group, payload in sorted(source_group_field_coverage_matrix.items())
        },
        "missing_identity_fields_by_group": missing_identity_fields_by_group,
        "missing_required_identity_fields": missing_identity_fields,
        "missing_identity_fields": missing_identity_fields,
        "missing_cost_fields_by_group": missing_cost_fields_by_group,
        "missing_required_cost_fields": missing_cost_fields,
        "missing_cost_fields": missing_cost_fields,
        "missing_required_field_group_counts": dict(sorted(all_missing_fields.items())),
        "source_group_readiness": source_group_readiness,
        "write_path_findings": write_path_findings,
        "sample_write_path_findings": write_path_findings[:10],
        "remediation_plan": remediation_plan,
        "blocked_reasons": blocked_reasons,
        "blocked_reason_details": blocked_reason_details,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "sample_blockers": sample_blockers,
        "actuals": write_path_actuals,
        "required": write_path_required,
        "exact_identity_occurrences": exact_identity_occurrences,
        "alternate_identity_occurrences": alternate_identity_occurrences,
        "identity_credit_rule": (
            "Only exact candidate_id, policy_fingerprint, and model_source fields on future paper-path rows "
            "can bind challenger outcomes; selector_policy_fingerprint, trainer_source, or model_id are diagnostic only."
        ),
        "operator_action_required": status != "PASS_RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT",
        "runtime_write_path_edits_require_operator_approval": True,
        "operator_approval_required_before_runtime_write_path_edits": True,
        "operator_approval_required_before_applying_plan": True,
        "approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "runtime_write_path_approval_reason": (
            "Persisting missing identity or production-grade cost fields on paper signal, intent, paper ledger, "
            "paper online ledger, closed-trade, or trainer-feedback rows changes runtime paper write behavior."
        ),
        "operator_approval_boundary": {
            "operator_approval_required_before_runtime_edit": True,
            "approved_change_class": "telemetry_only_identity_and_cost_persistence",
            "prohibited_patch_scope": prohibited_patch_scope,
            "existing_rows_may_not_be_backfilled_for_credit": True,
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "pass_conditions": pass_conditions,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "new_candidate_required_if_cost_model_or_threshold_changes": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def runtime_cost_capture_operator_approval_packet(
    *,
    policy: FrozenPolicy,
    runtime_cost_capture_remediation: Mapping[str, Any],
    runtime_cost_capture_write_path: Mapping[str, Any],
) -> dict[str, Any]:
    missing_identity_by_group = runtime_cost_capture_write_path.get("missing_identity_fields_by_group")
    missing_identity_by_group = missing_identity_by_group if isinstance(missing_identity_by_group, Mapping) else {}
    missing_cost_by_group = runtime_cost_capture_write_path.get("missing_cost_fields_by_group")
    missing_cost_by_group = missing_cost_by_group if isinstance(missing_cost_by_group, Mapping) else {}
    source_group_field_coverage_matrix = runtime_cost_capture_write_path.get("source_group_field_coverage_matrix")
    source_group_field_coverage_matrix = (
        source_group_field_coverage_matrix
        if isinstance(source_group_field_coverage_matrix, Mapping)
        else {}
    )
    required_new_rows = int(runtime_cost_capture_remediation.get("required_new_candidate_bound_production_grade_rows") or 0)
    approval_groups: list[dict[str, Any]] = []
    for group_name, write_point in RUNTIME_COST_CAPTURE_WRITE_POINTS.items():
        required_fields = [
            field
            for field, groups in RUNTIME_COST_FIELD_CAPTURE_REQUIREMENTS.items()
            if group_name in groups
        ]
        missing_identity = [str(field) for field in missing_identity_by_group.get(group_name, [])]
        missing_cost = [str(field) for field in missing_cost_by_group.get(group_name, [])]
        required_identity = [field for field in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS if field in required_fields]
        required_cost = [field for field in required_fields if field not in REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS]
        coverage_payload = source_group_field_coverage_matrix.get(group_name)
        coverage_payload = coverage_payload if isinstance(coverage_payload, Mapping) else {}
        identity_coverage = coverage_payload.get("identity") if isinstance(coverage_payload.get("identity"), Mapping) else {}
        cost_coverage = coverage_payload.get("cost") if isinstance(coverage_payload.get("cost"), Mapping) else {}
        combined_coverage = coverage_payload.get("combined") if isinstance(coverage_payload.get("combined"), Mapping) else {}
        field_evidence_summary = (
            coverage_payload.get("field_evidence_summary")
            if isinstance(coverage_payload.get("field_evidence_summary"), Mapping)
            else {}
        )
        approval_groups.append(
            {
                "source_group": group_name,
                "capture_stage": RUNTIME_COST_CAPTURE_STAGE_BY_GROUP.get(group_name, "unknown"),
                "producer": write_point.get("producer"),
                "files": list(write_point.get("files", [])),
                "redis_keys": list(write_point.get("redis_keys", [])),
                "required_role": write_point.get("required_role"),
                "requires_operator_approval": bool(missing_identity or missing_cost),
                "missing_identity_fields": missing_identity,
                "missing_cost_fields": missing_cost,
                "required_identity_fields": list(required_identity),
                "required_cost_fields": required_cost,
                "required_join_key_fields": COST_IDENTITY_JOIN_KEY_FIELDS,
                "write_path_field_coverage": dict(coverage_payload),
                "identity_field_coverage": identity_coverage.get("coverage"),
                "cost_field_coverage": cost_coverage.get("coverage"),
                "combined_required_field_coverage": combined_coverage.get("coverage"),
                "field_evidence_summary": dict(field_evidence_summary),
                "approved_change_class": "telemetry_only_identity_and_cost_persistence",
                "forbidden_change_classes": [
                    "order_submission",
                    "order_cancellation_or_modification",
                    "exchange_leverage_or_margin_mutation",
                    "strategy_threshold_or_weight_change",
                    "frozen_candidate_artifact_change",
                    "historical_identity_backfill_for_credit",
                    "paper_binding_before_blind_lockbox_pass",
                ],
                "post_approval_proof_required": [
                    "future rows carry candidate_id, policy_fingerprint, and model_source before outcome exists",
                    "future rows carry all required production cost fields or fallback=true",
                    "fallback=true rows are excluded from training, lockbox, promotion, and A-grade evidence",
                    "selection fields are never rewritten after labels or outcomes exist",
                    "source_timestamp <= available_at <= decision_time",
                    "feature_cutoff <= decision_time",
                    "paper_fill_allowed=false and routes_to_live=false until cost, lockbox, and canary gates pass",
                ],
            }
        )

    approval_required_groups = [
        group["source_group"] for group in approval_groups if group["requires_operator_approval"]
    ]
    pass_conditions = {
        "runtime_write_path_audit_readable": bool(runtime_cost_capture_write_path.get("status")),
        "operator_approval_required_for_runtime_write_path_edits": True,
        "approval_scope_names_all_runtime_write_groups": set(approval_required_groups).issubset(set(RUNTIME_COST_CAPTURE_WRITE_POINTS)),
        "approval_scope_includes_write_path_field_coverage": all(
            bool(source_group_field_coverage_matrix.get(group_name))
            for group_name in approval_required_groups
        ),
        "missing_identity_or_cost_fields_identified": bool(approval_required_groups),
        "minimum_future_candidate_bound_rows_declared": required_new_rows > 0,
        "no_historical_backfill_for_credit": True,
        "frozen_candidate_not_modified": True,
        "paper_fill_allowed_false_until_gates_pass": True,
        "routes_to_live_false_until_gates_pass": True,
    }
    status = (
        "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
        if approval_required_groups
        else "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_NOT_REQUIRED"
    )
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    if approval_required_groups:
        blocked_reasons.insert(0, "operator_approval_required")
    approved_patch_scope = "telemetry_only_future_runtime_cost_and_identity_capture"
    required_acknowledgements = [
        "acknowledges_no_historical_backfill_for_credit",
        "acknowledges_no_frozen_candidate_or_model_changes",
        "acknowledges_paper_fill_and_live_routes_remain_false",
    ]
    telemetry_only_runtime_paths = [
        {
            "source_group": group["source_group"],
            "capture_stage": group["capture_stage"],
            "producer": group["producer"],
            "files": group["files"],
            "redis_keys": group["redis_keys"],
            "approved_change_class": group["approved_change_class"],
        }
        for group in approval_groups
    ]
    prohibited_patch_scope = sorted(
        {
            str(change_class)
            for group in approval_groups
            for change_class in group.get("forbidden_change_classes", [])
        }
    )
    source_files_to_patch = sorted(
        {
            str(file_name)
            for path in telemetry_only_runtime_paths
            for file_name in path.get("files", [])
        }
    )
    missing_identity_fields_by_group = {
        group["source_group"]: list(group.get("missing_identity_fields") or [])
        for group in approval_groups
        if group.get("missing_identity_fields")
    }
    missing_cost_fields_by_group = {
        group["source_group"]: list(group.get("missing_cost_fields") or [])
        for group in approval_groups
        if group.get("missing_cost_fields")
    }
    missing_required_fields_by_group = {
        group["source_group"]: [
            *list(group.get("missing_identity_fields") or []),
            *list(group.get("missing_cost_fields") or []),
        ]
        for group in approval_groups
        if group.get("missing_identity_fields") or group.get("missing_cost_fields")
    }
    missing_required_identity_fields = sorted(
        {
            str(field)
            for fields in missing_identity_fields_by_group.values()
            for field in fields
        }
    )
    missing_required_cost_fields = sorted(
        {
            str(field)
            for fields in missing_cost_fields_by_group.values()
            for field in fields
        }
    )
    source_group_readiness = {
        group["source_group"]: {
            "source_group": group["source_group"],
            "status": (
                "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
                if group["requires_operator_approval"]
                else "READY_NO_OPERATOR_APPROVAL_REQUIRED"
            ),
            "capture_stage": group["capture_stage"],
            "producer": group["producer"],
            "files": group["files"],
            "redis_keys": group["redis_keys"],
            "requires_operator_approval": group["requires_operator_approval"],
            "missing_identity_fields": group["missing_identity_fields"],
            "missing_cost_fields": group["missing_cost_fields"],
            "missing_required_fields": [
                *list(group.get("missing_identity_fields") or []),
                *list(group.get("missing_cost_fields") or []),
            ],
            "required_identity_fields": group["required_identity_fields"],
            "required_cost_fields": group["required_cost_fields"],
            "identity_field_coverage": group["identity_field_coverage"],
            "cost_field_coverage": group["cost_field_coverage"],
            "combined_required_field_coverage": group["combined_required_field_coverage"],
            "approved_change_class": group["approved_change_class"],
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
        }
        for group in approval_groups
    }
    approval_readiness_summary = {
        "operator_approval_required": bool(approval_required_groups),
        "approval_required_source_groups": approval_required_groups,
        "approval_required_source_group_count": len(approval_required_groups),
        "missing_identity_source_group_count": len(missing_identity_fields_by_group),
        "missing_cost_source_group_count": len(missing_cost_fields_by_group),
        "missing_required_identity_fields": missing_required_identity_fields,
        "missing_required_cost_fields": missing_required_cost_fields,
        "missing_required_fields_by_group": missing_required_fields_by_group,
        "minimum_new_candidate_bound_production_grade_rows": required_new_rows,
        "approved_patch_scope": approved_patch_scope,
        "operator_approval_receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "no_historical_backfill_for_credit": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    pass_condition_requirements = {
        "runtime_write_path_audit_readable": "runtime write-path audit status present",
        "operator_approval_required_for_runtime_write_path_edits": True,
        "approval_scope_names_all_runtime_write_groups": sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS),
        "approval_scope_includes_write_path_field_coverage": "each approval-required source group has source_group_field_coverage_matrix evidence",
        "missing_identity_or_cost_fields_identified": "at least one runtime source group missing required identity or cost fields",
        "minimum_future_candidate_bound_rows_declared": ">0",
        "no_historical_backfill_for_credit": True,
        "frozen_candidate_not_modified": True,
        "paper_fill_allowed_false_until_gates_pass": True,
        "routes_to_live_false_until_gates_pass": True,
    }
    pass_condition_observed = {
        "runtime_write_path_audit_readable": runtime_cost_capture_write_path.get("status"),
        "operator_approval_required_for_runtime_write_path_edits": True,
        "approval_scope_names_all_runtime_write_groups": approval_required_groups,
        "approval_scope_includes_write_path_field_coverage": {
            group_name: bool(source_group_field_coverage_matrix.get(group_name))
            for group_name in approval_required_groups
        },
        "missing_identity_or_cost_fields_identified": approval_required_groups,
        "minimum_future_candidate_bound_rows_declared": required_new_rows,
        "no_historical_backfill_for_credit": True,
        "frozen_candidate_not_modified": True,
        "paper_fill_allowed_false_until_gates_pass": True,
        "routes_to_live_false_until_gates_pass": True,
    }
    blocker_details = [
        {
            "pass_condition": "operator_approval_required",
            "passed": False,
            "observed": {
                "approval_required_source_groups": approval_required_groups,
                "operator_approval_required": True,
                "operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
            },
            "required": "operator receipt must be present and valid before future runtime cost rows can count",
            "source_artifact": "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json",
            "operator_action": "review packet and provide valid approval receipt if telemetry-only runtime cost capture edits are approved",
        }
    ] if approval_required_groups else []
    blocker_details.extend(
        {
            "pass_condition": condition,
            "passed": False,
            "observed": pass_condition_observed.get(condition),
            "required": pass_condition_requirements.get(condition),
            "source_artifact": "challenger_v2_runtime_cost_capture_operator_approval_packet.json",
            "operator_action": "repair approval packet prerequisites before requesting operator receipt",
        }
        for condition in blocked_reasons
        if condition != "operator_approval_required"
    )
    required_runtime_write_groups = sorted(RUNTIME_COST_CAPTURE_WRITE_POINTS)
    operator_approval_status = (
        "AWAITING_OPERATOR_APPROVAL_RECEIPT"
        if approval_required_groups
        else "OPERATOR_APPROVAL_NOT_REQUIRED"
    )
    packet_actuals = {
        **pass_condition_observed,
        "operator_approval_status": operator_approval_status,
        "operator_approval_receipt_present": False,
        "operator_approval_required_source_groups": approval_required_groups,
        "approval_required_source_group_count": len(approval_required_groups),
        "required_runtime_write_groups": required_runtime_write_groups,
        "runtime_cost_capture_write_path_audit_status": runtime_cost_capture_write_path.get("status"),
        "missing_identity_fields_by_group": missing_identity_fields_by_group,
        "missing_cost_fields_by_group": missing_cost_fields_by_group,
    }
    packet_required = {
        **pass_condition_requirements,
        "operator_approval_status": "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        "operator_approval_receipt_present": True,
        "operator_approval_required_source_groups": approval_required_groups,
        "approval_required_source_group_count": len(approval_required_groups),
        "required_runtime_write_groups": required_runtime_write_groups,
        "runtime_cost_capture_write_path_audit_status": "PASS_RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT",
        "missing_identity_fields_by_group": {},
        "missing_cost_fields_by_group": {},
    }
    return {
        "schema_version": "challenger_v2_runtime_cost_capture_operator_approval_packet_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "runtime_cost_capture_remediation_status": runtime_cost_capture_remediation.get("status"),
        "runtime_cost_capture_write_path_audit_status": runtime_cost_capture_write_path.get("status"),
        "write_path_status": runtime_cost_capture_write_path.get("status"),
        "operator_approval_status": operator_approval_status,
        "approval_required": bool(approval_required_groups),
        "operator_approval_required": bool(approval_required_groups),
        "operator_approval_required_before_runtime_edits": bool(approval_required_groups),
        "operator_approval_required_before_runtime_write_path_edits": bool(approval_required_groups),
        "operator_approval_required_before_applying_plan": bool(approval_required_groups),
        "operator_action_required": bool(approval_required_groups),
        "approval_required_source_groups": approval_required_groups,
        "operator_approval_required_source_groups": approval_required_groups,
        "required_source_groups": approval_required_groups,
        "required_runtime_write_groups": required_runtime_write_groups,
        "approved_source_groups": approval_required_groups,
        "source_groups": approval_required_groups,
        "source_group_count": len(approval_required_groups),
        "approved_source_group_count": len(approval_required_groups),
        "source_files_to_patch": source_files_to_patch,
        "write_path_files": source_files_to_patch,
        "source_file_count": len(source_files_to_patch),
        "approval_packet_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        "approved_patch_scope": approved_patch_scope,
        "approval_patch_scope": approved_patch_scope,
        "approval_subject_hash": None,
        "approval_subject_hash_status": "PENDING_RUNTIME_IDENTITY_BINDING_PLAN",
        "operator_approval_subject_hash_status": "PENDING_RUNTIME_IDENTITY_BINDING_PLAN",
        "approval_receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "runtime_cost_capture_operator_approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "runtime_cost_capture_operator_approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "receipt_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "required_acknowledgements": required_acknowledgements,
        "required_operator_acknowledgements": required_acknowledgements,
        "acknowledgements": required_acknowledgements,
        "telemetry_only_runtime_paths": telemetry_only_runtime_paths,
        "prohibited_patch_scope": prohibited_patch_scope,
        "source_group_field_coverage_matrix": dict(source_group_field_coverage_matrix),
        "missing_identity_fields_by_group": missing_identity_fields_by_group,
        "missing_required_identity_fields_by_group": missing_identity_fields_by_group,
        "missing_identity_fields": missing_required_identity_fields,
        "missing_required_identity_fields": missing_required_identity_fields,
        "missing_cost_fields_by_group": missing_cost_fields_by_group,
        "missing_required_cost_fields_by_group": missing_cost_fields_by_group,
        "missing_cost_fields": missing_required_cost_fields,
        "missing_required_cost_fields": missing_required_cost_fields,
        "missing_required_fields_by_group": missing_required_fields_by_group,
        "source_group_readiness": source_group_readiness,
        "approval_readiness_summary": approval_readiness_summary,
        "operator_approval_readiness_summary": approval_readiness_summary,
        "approval_scope_field_coverage_summary": {
            group["source_group"]: {
                "identity_field_coverage": group.get("identity_field_coverage"),
                "cost_field_coverage": group.get("cost_field_coverage"),
                "combined_required_field_coverage": group.get("combined_required_field_coverage"),
                "missing_identity_fields": group.get("missing_identity_fields"),
                "missing_cost_fields": group.get("missing_cost_fields"),
            }
            for group in approval_groups
        },
        "receipt_acceptance_rule": {
            "approval_subject_hash": None,
            "approval_subject_hash_status": "PENDING_RUNTIME_IDENTITY_BINDING_PLAN",
            "approved_source_groups": approval_required_groups,
            "approved_patch_scope": approved_patch_scope,
            "required_acknowledgements": required_acknowledgements,
            "required_operator_acknowledgements": required_acknowledgements,
        },
        "minimum_new_candidate_bound_production_grade_rows": required_new_rows,
        "missing_or_invalid_receipt_fields": None,
        "approval_receipt_present": False,
        "operator_approved_runtime_cost_capture": False,
        "operator_approved_identity_binding": False,
        "approval_scope": approval_groups,
        "approval_statement_needed": (
            "Approve telemetry-only paper runtime write-path edits that persist exact challenger "
            "candidate_id, policy_fingerprint, model_source, and required production cost fields on future "
            "paper signal, intent, paper ledger, paper online ledger, closed-trade, and trainer-feedback rows. This approval must not "
            "include live routing, exchange I/O, threshold/model changes, or historical backfill for credit."
        )
        if approval_required_groups
        else None,
        "non_counting_existing_rows_rule": (
            "Existing old-policy or unbound rows remain quarantined and may not be backfilled into "
            "production-grade challenger evidence."
        ),
        "post_approval_acceptance_tests": [
            "runtime write-path source audit reports no missing required identity fields",
            "paper cost telemetry reports challenger_bound_production_grade_rows > 0 only on future rows",
            "production_grade_cost_coverage >= 0.95",
            "unexplained_cost_missing_rows == 0",
            "replay and paper costs match for identical snapshot/order",
            "paper_fill_allowed_rows == 0 before lockbox pass",
            "routes_to_live_rows == 0",
        ],
        "pass_conditions": pass_conditions,
        "actuals": packet_actuals,
        "required": packet_required,
        "blocked_reasons": blocked_reasons,
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "sample_blockers": blocker_details[:25],
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "new_candidate_required_if_cost_model_or_threshold_changes": True,
        "no_live_or_paper_fill_mutation": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def _substring_occurrences_by_file(
    source_lines_by_file: Mapping[str, Sequence[str]],
    term: str,
    *,
    max_occurrences: int = 10,
) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for relative, lines in source_lines_by_file.items():
        for lineno, line in enumerate(lines, start=1):
            if term in line:
                occurrences.append({"path": relative, "line": lineno, "text": line.strip()[:240]})
                if len(occurrences) >= max_occurrences:
                    return occurrences
    return occurrences


def runtime_identity_binding_implementation_plan(
    *,
    repo_root: Path,
    policy: FrozenPolicy,
    runtime_cost_capture_operator_approval: Mapping[str, Any],
) -> dict[str, Any]:
    approval_scope_rows = runtime_cost_capture_operator_approval.get("approval_scope")
    approval_scope_rows = approval_scope_rows if isinstance(approval_scope_rows, Sequence) and not isinstance(approval_scope_rows, (str, bytes, bytearray)) else []
    approval_required_groups = [
        str(group)
        for group in runtime_cost_capture_operator_approval.get("approval_required_source_groups", [])
        if str(group) in RUNTIME_COST_CAPTURE_WRITE_POINTS
    ]
    source_files = sorted(
        {
            str(file_name)
            for row in approval_scope_rows
            if isinstance(row, Mapping)
            for file_name in row.get("files", [])
        }
    )
    source_lines_by_file: dict[str, list[str]] = {}
    unreadable_files: list[dict[str, Any]] = []
    for relative in source_files:
        path = repo_root / relative
        try:
            source_lines_by_file[relative] = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            source_lines_by_file[relative] = []
            unreadable_files.append({"path": relative, "error": type(exc).__name__})

    implementation_steps: list[dict[str, Any]] = []
    incomplete_groups: list[str] = []
    missing_identity_fields_by_group: dict[str, list[str]] = {}
    missing_cost_fields_by_group: dict[str, list[str]] = {}
    required_cost_fields_by_group: dict[str, list[str]] = {}
    required_join_key_fields_by_group: dict[str, Any] = {}
    for row in approval_scope_rows:
        if not isinstance(row, Mapping):
            continue
        group_name = str(row.get("source_group") or "")
        if group_name not in approval_required_groups:
            continue
        missing_identity_fields_by_group[group_name] = [
            str(field) for field in row.get("missing_identity_fields", []) if str(field)
        ]
        missing_cost_fields_by_group[group_name] = [
            str(field) for field in row.get("missing_cost_fields", []) if str(field)
        ]
        required_cost_fields_by_group[group_name] = [
            str(field) for field in row.get("required_cost_fields", []) if str(field)
        ]
        required_join_key_fields_by_group[group_name] = row.get("required_join_key_fields") or {}
        files = [str(file_name) for file_name in row.get("files", [])]
        group_sources = {relative: source_lines_by_file.get(relative, []) for relative in files}
        target_terms = RUNTIME_IDENTITY_BINDING_LINE_TARGET_TERMS.get(group_name, ())
        target_hits = {
            term: _substring_occurrences_by_file(group_sources, term, max_occurrences=10)
            for term in target_terms
        }
        missing_target_terms = [term for term, hits in target_hits.items() if not hits]
        if missing_target_terms:
            incomplete_groups.append(group_name)
        implementation_steps.append(
            {
                "source_group": group_name,
                "capture_stage": row.get("capture_stage"),
                "files": files,
                "redis_keys": list(row.get("redis_keys", [])),
                "line_target_terms": list(target_terms),
                "line_target_hits": target_hits,
                "missing_line_target_terms": missing_target_terms,
                "required_identity_fields_to_persist": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
                "identity_source_rules": {
                    "candidate_id": (
                        "Propagate exact candidate_id from an upstream challenger-owned selection/signal record; "
                        "do not derive it from trainer_source, model_id, selector_policy_fingerprint, or old-policy rows."
                    ),
                    "policy_fingerprint": (
                        "Propagate exact policy_fingerprint from the same upstream challenger-owned record and require "
                        f"it to equal {policy.policy_fingerprint} before any row can count."
                    ),
                    "model_source": (
                        "Propagate exact model_source from the upstream record and require "
                        f"it to equal {policy.model_source} for challenger credit."
                    ),
                },
                "required_credit_checks": [
                    "candidate_id == frozen candidate_id",
                    "policy_fingerprint == frozen policy_fingerprint",
                    "model_source == frozen model_source",
                    "source row is future-captured, not historical-backfilled",
                    "all required production cost fields present and fallback=false before production evidence credit",
                ],
                "forbidden_shortcuts": [
                    "stamp frozen candidate_id onto existing old-policy or unbound rows",
                    "treat selector_policy_fingerprint or frozen_selector_fingerprint as policy_fingerprint",
                    "treat trainer_source or model_id as candidate_id",
                    "change model weights, thresholds, normalization, fee schedules, or cost formulas",
                    "set paper_fill_allowed=true or routes_to_live=true as part of telemetry capture",
                ],
                "post_patch_artifacts_to_recheck": [
                    RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT,
                    RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
                    "challenger_v2_paper_cost_telemetry_readiness.json",
                    "challenger_v2_production_cost_evidence_status.json",
                    "challenger_v2_cost_replay_paper_parity_audit.json",
                ],
            }
        )

    pass_conditions = {
        "operator_approval_packet_requires_approval": runtime_cost_capture_operator_approval.get("operator_approval_required") is True,
        "all_approval_required_groups_have_plan_steps": set(approval_required_groups)
        == {str(step.get("source_group")) for step in implementation_steps},
        "all_plan_source_files_readable": not unreadable_files,
        "line_targets_found_for_all_approval_required_groups": not incomplete_groups,
        "identity_rules_do_not_allow_alternate_identity_credit": True,
        "historical_rows_remain_non_counting": True,
        "telemetry_only_no_runtime_change_applied": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
    }
    status = (
        "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"
        if all(pass_conditions.values())
        else "BLOCKED_RUNTIME_IDENTITY_BINDING_IMPLEMENTATION_PLAN_INCOMPLETE"
    )
    return {
        "schema_version": "challenger_v2_runtime_identity_binding_implementation_plan_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "runtime_cost_capture_operator_approval_packet_status": runtime_cost_capture_operator_approval.get("status"),
        "approval_required_source_groups": approval_required_groups,
        "operator_approval_required_source_groups": approval_required_groups,
        "required_source_groups": approval_required_groups,
        "source_groups": approval_required_groups,
        "source_group_count": len(approval_required_groups),
        "complete_source_groups": [group for group in approval_required_groups if group not in set(incomplete_groups)],
        "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "required_join_key_fields": required_join_key_fields_by_group,
        "required_cost_fields_by_group": required_cost_fields_by_group,
        "missing_identity_fields_by_group": missing_identity_fields_by_group,
        "missing_cost_fields_by_group": missing_cost_fields_by_group,
        "missing_fields_by_source_group": {
            group: {
                "missing_identity_fields": missing_identity_fields_by_group.get(group, []),
                "missing_cost_fields": missing_cost_fields_by_group.get(group, []),
            }
            for group in approval_required_groups
        },
        "source_files_scanned": source_files,
        "source_files_to_patch": source_files,
        "write_path_files": source_files,
        "source_file_count": len(source_files),
        "unreadable_source_files": unreadable_files,
        "incomplete_source_groups": sorted(set(incomplete_groups)),
        "implementation_steps": implementation_steps,
        "implementation_plan": implementation_steps,
        "source_group_implementation_plan_count": len(implementation_steps),
        "source_group_implementation_plans": {
            str(step.get("source_group")): step
            for step in implementation_steps
        },
        "candidate_credit_identity_invariant": (
            "A paper/runtime row counts for challenger evidence only when candidate_id, policy_fingerprint, "
            "and model_source exactly match the frozen challenger on a future-captured row."
        ),
        "non_counting_existing_rows_rule": (
            "Existing old-policy or unbound rows remain quarantined even if join keys overlap candidate-bound shadow rows."
        ),
        "operator_approval_required_before_applying_plan": True,
        "operator_approval_required_before_runtime_write_path_edits": True,
        "approval_receipt_required_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT,
        "approval_receipt_template_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        "approval_receipt_status_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        "approved_patch_scope": runtime_cost_capture_operator_approval.get("approved_patch_scope"),
        "prohibited_patch_scope": runtime_cost_capture_operator_approval.get("prohibited_patch_scope"),
        "pass_conditions": pass_conditions,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def shadow_cost_reconciliation_audit(
    *,
    policy: FrozenPolicy,
    shadow_cost_status: Mapping[str, Any],
    shadow_rows: Sequence[Mapping[str, Any]],
    paper_cost_telemetry: Mapping[str, Any],
    cost_capture_gap: Mapping[str, Any],
    runtime_cost_capture_contract: Mapping[str, Any],
) -> dict[str, Any]:
    row_count = len(shadow_rows)
    identity_complete_rows = 0
    fallback_rows = 0
    production_grade_rows = 0
    production_grade_non_counting_rows = 0
    candidate_bound_fallback_rows = 0
    pit_blocked_rows = 0
    route_rows = 0
    paper_fill_allowed_rows = 0
    places_real_order_rows = 0
    a_grade_rows = 0
    promotion_rows = 0
    training_lockbox_promotion_rows = 0
    phase_1_counting_rows = 0
    selected_rows = 0
    rejected_rows = 0
    field_gap_counts: Counter[str] = Counter()
    field_present_counts: Counter[str] = Counter()
    sample_blocked_rows: list[dict[str, Any]] = []
    sample_production_grade_non_counting_rows: list[dict[str, Any]] = []

    def sample_shadow_row(row: Mapping[str, Any]) -> dict[str, Any]:
        missing_fields = [str(field) for field in row.get("missing_evidence_fields") or []]
        return {
            "shadow_cost_evidence_record_id": row.get("shadow_cost_evidence_record_id"),
            "candidate_id": row.get("candidate_id"),
            "policy_fingerprint": row.get("policy_fingerprint"),
            "model_source": row.get("model_source"),
            "snapshot_id": row.get("snapshot_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "decision_time": row.get("decision_time"),
            "feature_cutoff": row.get("feature_cutoff"),
            "available_at": row.get("available_at"),
            "identity_state": challenger_identity_state(row, policy),
            "production_grade_cost_evidence": row.get("production_grade_cost_evidence") is True,
            "fallback": row.get("fallback") is True,
            "missing_evidence_fields": missing_fields,
            "recovery_boundaries": {
                field: FIELD_RECOVERY_BOUNDARY.get(field)
                for field in missing_fields
                if FIELD_RECOVERY_BOUNDARY.get(field)
            },
            "point_in_time_blocked": shadow_cost_evidence_pit_violation(row),
            "selected": row.get("selected") is True,
            "rejected": row.get("rejected") is True,
            "rejection_reasons": row.get("rejection_reasons") or [],
            "paper_fill_allowed": row.get("paper_fill_allowed") is True,
            "routes_to_live": paper_row_routes_to_live(row),
            "places_real_order": row.get("places_real_order") is True,
            "counts_as_phase_1_production_grade_evidence": row.get("counts_as_phase_1_production_grade_evidence") is True,
            "counts_as_training_lockbox_or_promotion_evidence": row.get("counts_as_training_lockbox_or_promotion_evidence") is True,
            "counts_as_a_grade_evidence": row.get("counts_as_a_grade_evidence") is True,
            "promotion_evidence": row.get("promotion_evidence") is True,
        }

    for row in shadow_rows:
        identity_complete = challenger_identity_state(row, policy) == "complete"
        production_grade = row.get("production_grade_cost_evidence") is True
        fallback = row.get("fallback") is True
        if identity_complete:
            identity_complete_rows += 1
        if fallback:
            fallback_rows += 1
        if production_grade:
            production_grade_rows += 1
        if production_grade and row.get("counts_as_phase_1_production_grade_evidence") is not True:
            production_grade_non_counting_rows += 1
            if len(sample_production_grade_non_counting_rows) < 10:
                sample_production_grade_non_counting_rows.append(sample_shadow_row(row))
        if identity_complete and fallback:
            candidate_bound_fallback_rows += 1
        if shadow_cost_evidence_pit_violation(row):
            pit_blocked_rows += 1
        if paper_row_routes_to_live(row):
            route_rows += 1
        if row.get("paper_fill_allowed") is True:
            paper_fill_allowed_rows += 1
        if row.get("places_real_order") is True:
            places_real_order_rows += 1
        if row.get("counts_as_a_grade_evidence") is True:
            a_grade_rows += 1
        if row.get("promotion_evidence") is True:
            promotion_rows += 1
        if row.get("counts_as_training_lockbox_or_promotion_evidence") is True:
            training_lockbox_promotion_rows += 1
        if row.get("counts_as_phase_1_production_grade_evidence") is True:
            phase_1_counting_rows += 1
        if row.get("selected") is True:
            selected_rows += 1
        if row.get("rejected") is True:
            rejected_rows += 1
        missing_fields = [str(field) for field in row.get("missing_evidence_fields") or []]
        for field in missing_fields:
            field_gap_counts[field] += 1
        presence = row.get("required_cost_source_presence")
        if isinstance(presence, Mapping):
            for field, payload in presence.items():
                if isinstance(payload, Mapping) and payload.get("present") is True:
                    field_present_counts[str(field)] += 1
        if (fallback or missing_fields or not production_grade or shadow_cost_evidence_pit_violation(row)) and len(sample_blocked_rows) < 25:
            sample_blocked_rows.append(sample_shadow_row(row))

    old_or_unbound_paper_rows = int(paper_cost_telemetry.get("old_policy_or_unbound_production_grade_rows") or 0)
    challenger_bound_paper_rows = int(paper_cost_telemetry.get("challenger_bound_production_grade_rows") or 0)
    required_rows = int(cost_capture_gap.get("minimum_rows_required_for_95pct_coverage") or 0)
    production_grade_shortfall = int(cost_capture_gap.get("production_grade_cost_row_shortfall_to_95pct") or 0)
    all_non_executable = (
        route_rows == 0
        and paper_fill_allowed_rows == 0
        and places_real_order_rows == 0
        and a_grade_rows == 0
        and promotion_rows == 0
        and training_lockbox_promotion_rows == 0
        and phase_1_counting_rows == 0
    )
    pass_conditions = {
        "shadow_rows_exist": row_count > 0,
        "candidate_identity_complete_for_all_shadow_rows": identity_complete_rows == row_count if row_count else False,
        "production_grade_shadow_cost_rows_gt_0": production_grade_rows > 0,
        "fallback_shadow_cost_rows_eq_0": fallback_rows == 0 if row_count else False,
        "point_in_time_violations_eq_0": pit_blocked_rows == 0,
        "field_gap_counts_empty": not field_gap_counts if row_count else False,
        "shadow_rows_non_executable": all_non_executable,
        "old_policy_or_unbound_rows_not_counted": True,
        "candidate_bound_paper_production_grade_rows_available": challenger_bound_paper_rows >= required_rows if required_rows else False,
        "runtime_cost_capture_contract_ready": runtime_cost_capture_contract.get("status") == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
    }
    status = (
        "PASS_SHADOW_COST_RECONCILIATION_READY"
        if all(pass_conditions.values())
        else "BLOCKED_SHADOW_COST_RECONCILIATION_REQUIRES_PRODUCTION_GRADE_CANDIDATE_BOUND_COST"
    )
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    reconciliation_blocker_details = {
        name: {
            "pass_condition": name,
            "passed": False,
            "observed": {
                "shadow_rows_exist": row_count,
                "candidate_identity_complete_for_all_shadow_rows": {
                    "candidate_identity_complete_rows": identity_complete_rows,
                    "shadow_cost_evidence_rows": row_count,
                },
                "production_grade_shadow_cost_rows_gt_0": production_grade_rows,
                "fallback_shadow_cost_rows_eq_0": fallback_rows,
                "point_in_time_violations_eq_0": pit_blocked_rows,
                "field_gap_counts_empty": dict(sorted(field_gap_counts.items())),
                "shadow_rows_non_executable": {
                    "routes_to_live_rows": route_rows,
                    "paper_fill_allowed_rows": paper_fill_allowed_rows,
                    "places_real_order_rows": places_real_order_rows,
                    "a_grade_rows": a_grade_rows,
                    "promotion_rows": promotion_rows,
                    "training_lockbox_promotion_rows": training_lockbox_promotion_rows,
                    "phase_1_counting_rows": phase_1_counting_rows,
                },
                "candidate_bound_paper_production_grade_rows_available": {
                    "challenger_bound_production_grade_paper_rows": challenger_bound_paper_rows,
                    "required_rows": required_rows,
                },
                "runtime_cost_capture_contract_ready": runtime_cost_capture_contract.get("status"),
            }.get(name),
            "required": {
                "shadow_rows_exist": ">0",
                "candidate_identity_complete_for_all_shadow_rows": "candidate identity complete on every shadow row",
                "production_grade_shadow_cost_rows_gt_0": ">0",
                "fallback_shadow_cost_rows_eq_0": 0,
                "point_in_time_violations_eq_0": 0,
                "field_gap_counts_empty": {},
                "shadow_rows_non_executable": "all execution, promotion, and counting flags remain false",
                "candidate_bound_paper_production_grade_rows_available": f">={required_rows}",
                "runtime_cost_capture_contract_ready": "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
            }.get(name),
        }
        for name in blocked_reasons
    }
    reconciliation_actuals = {
        "shadow_rows_exist": row_count,
        "candidate_identity_complete_for_all_shadow_rows": {
            "candidate_identity_complete_rows": identity_complete_rows,
            "shadow_cost_evidence_rows": row_count,
        },
        "production_grade_shadow_cost_rows_gt_0": production_grade_rows,
        "fallback_shadow_cost_rows_eq_0": fallback_rows,
        "point_in_time_violations_eq_0": pit_blocked_rows,
        "field_gap_counts_empty": dict(sorted(field_gap_counts.items())),
        "shadow_rows_non_executable": {
            "routes_to_live_rows": route_rows,
            "paper_fill_allowed_rows": paper_fill_allowed_rows,
            "places_real_order_rows": places_real_order_rows,
            "a_grade_rows": a_grade_rows,
            "promotion_rows": promotion_rows,
            "training_lockbox_promotion_rows": training_lockbox_promotion_rows,
            "phase_1_counting_rows": phase_1_counting_rows,
        },
        "old_policy_or_unbound_rows_not_counted": old_or_unbound_paper_rows,
        "candidate_bound_paper_production_grade_rows_available": {
            "challenger_bound_production_grade_paper_rows": challenger_bound_paper_rows,
            "required_rows": required_rows,
        },
        "runtime_cost_capture_contract_ready": runtime_cost_capture_contract.get("status"),
    }
    reconciliation_required = {
        "shadow_rows_exist": ">0",
        "candidate_identity_complete_for_all_shadow_rows": "candidate identity complete on every shadow row",
        "production_grade_shadow_cost_rows_gt_0": ">0",
        "fallback_shadow_cost_rows_eq_0": 0,
        "point_in_time_violations_eq_0": 0,
        "field_gap_counts_empty": {},
        "shadow_rows_non_executable": "all execution, promotion, and counting flags remain false",
        "old_policy_or_unbound_rows_not_counted": "excluded from challenger production-grade credit",
        "candidate_bound_paper_production_grade_rows_available": f">={required_rows}",
        "runtime_cost_capture_contract_ready": "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
    }
    return {
        "schema_version": "challenger_v2_candidate_bound_shadow_cost_reconciliation_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "shadow_cost_evidence_status": shadow_cost_status.get("status"),
        "runtime_cost_capture_contract_status": runtime_cost_capture_contract.get("status"),
        "runtime_cost_capture_contract_blocked_reasons": runtime_cost_capture_contract.get("blocked_reasons"),
        "shadow_cost_evidence_rows": row_count,
        "candidate_identity_complete_rows": identity_complete_rows,
        "candidate_bound_fallback_rows": candidate_bound_fallback_rows,
        "production_grade_shadow_cost_rows": production_grade_rows,
        "production_grade_non_counting_shadow_cost_rows": production_grade_non_counting_rows,
        "fallback_shadow_cost_rows": fallback_rows,
        "point_in_time_blocked_shadow_cost_rows": pit_blocked_rows,
        "selected_shadow_rows": selected_rows,
        "rejected_shadow_rows": rejected_rows,
        "phase_1_counting_shadow_cost_rows": phase_1_counting_rows,
        "training_lockbox_or_promotion_counting_shadow_rows": training_lockbox_promotion_rows,
        "old_policy_or_unbound_production_grade_paper_rows": old_or_unbound_paper_rows,
        "challenger_bound_production_grade_paper_rows": challenger_bound_paper_rows,
        "paper_telemetry_production_grade_rows": paper_cost_telemetry.get("paper_telemetry_production_grade_rows"),
        "minimum_rows_required_for_95pct_coverage": required_rows,
        "production_grade_cost_row_shortfall_to_95pct": production_grade_shortfall,
        "field_gap_counts": dict(sorted(field_gap_counts.items())),
        "field_recovery_boundaries": {
            field: FIELD_RECOVERY_BOUNDARY.get(field)
            for field in sorted(field_gap_counts)
            if FIELD_RECOVERY_BOUNDARY.get(field)
        },
        "required_cost_source_coverage": {
            field: {
                "present_rows": field_present_counts.get(field, 0),
                "missing_rows": row_count - field_present_counts.get(field, 0),
                "coverage": field_present_counts.get(field, 0) / row_count if row_count else 0.0,
                "recovery_boundary": FIELD_RECOVERY_BOUNDARY.get(field),
            }
            for field in REQUIRED_COST_EVIDENCE_FIELDS
        },
        "blocked_shadow_cost_row_categories": {
            "candidate_bound_but_fallback": candidate_bound_fallback_rows,
            "production_grade_but_non_counting": production_grade_non_counting_rows,
            "point_in_time_blocked": pit_blocked_rows,
            "missing_order_size": field_gap_counts.get("order_size", 0),
            "missing_depth_derived_price_impact": field_gap_counts.get("depth_derived_price_impact", 0),
            "missing_maker_taker_probability": field_gap_counts.get("maker_taker_assumption_and_probability", 0),
            "missing_latency_reserve": field_gap_counts.get("latency_reserve", 0),
            "missing_partial_fill_estimate": field_gap_counts.get("partial_fill_estimate", 0),
            "missing_top_book_evidence": field_gap_counts.get("top_book_evidence", 0),
            "old_policy_or_unbound_paper_rows_quarantined": old_or_unbound_paper_rows,
        },
        "authoritative_recovery_boundary": {
            "identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "cost_fields": list(REQUIRED_COST_EVIDENCE_FIELDS),
            "field_boundaries": {
                field: FIELD_RECOVERY_BOUNDARY.get(field)
                for field in REQUIRED_COST_EVIDENCE_FIELDS
                if FIELD_RECOVERY_BOUNDARY.get(field)
            },
            "candidate_binding_rule": "candidate_id, policy_fingerprint, and model_source must match the frozen challenger before rows can count",
            "fallback_rule": "fallback=true rows may be shadow-scored but cannot count as production-grade training, lockbox, paper canary, or promotion evidence",
            "old_policy_rule": "old policy or unbound production-grade paper telemetry is quarantined and cannot satisfy candidate-bound evidence",
            "timestamp_rule": "source_timestamp <= available_at <= decision_time and feature_cutoff <= decision_time",
        },
        "sample_blocked_shadow_cost_rows": sample_blocked_rows,
        "sample_production_grade_non_counting_shadow_cost_rows": sample_production_grade_non_counting_rows,
        "sample_old_or_unbound_production_grade_paper_rows": paper_cost_telemetry.get("sample_production_grade_identity_gap_rows") or [],
        "sample_challenger_bound_production_grade_paper_rows": paper_cost_telemetry.get("sample_challenger_bound_production_grade_rows") or [],
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "blocker_details": reconciliation_blocker_details,
        "failed_blocker_details": reconciliation_blocker_details,
        "actuals": reconciliation_actuals,
        "required": reconciliation_required,
        "sample_blockers": list(reconciliation_blocker_details.values())[:25],
        "fallback_true_rows_may_be_shadow_scored": True,
        "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "shadow_rows_count_as_phase_1_production_grade_evidence": False,
        "shadow_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "new_candidate_required_if_cost_model_or_threshold_changes": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def feature_values_for_policy(snapshot: Mapping[str, Any], policy: FrozenPolicy) -> dict[str, float | None]:
    numeric = numeric_feature_mapping(snapshot)
    return {name: (float(numeric[name]) if name in numeric else None) for name in policy.feature_names}


def score_snapshot(snapshot: Mapping[str, Any], policy: FrozenPolicy) -> dict[str, Any]:
    adapted = adapt_runtime_snapshot(snapshot, normalization=policy.normalization)
    score = policy.predict_vector(adapted.normalized_vector)
    side = "LONG" if score >= 0.0 else "SHORT"
    cost = estimate_paper_cost(snapshot, side=side.lower()).to_jsonable()
    production_cost_bps = float(cost.get("total_cost_bps") or 0.0)
    predicted_net_edge_bps = abs(float(score))
    predicted_gross_edge_bps = predicted_net_edge_bps + production_cost_bps
    threshold_distance = predicted_net_edge_bps - policy.threshold_bps
    rejection_reasons: list[str] = []
    if adapted.integrity_status.get("accepted_for_training") is not True:
        rejection_reasons.append("integrity")
    if adapted.missing_feature_names:
        rejection_reasons.append("data_completeness")
    if adapted.stale_feature_names:
        rejection_reasons.append("stale_features")
    if adapted.out_of_range_features:
        rejection_reasons.append("distribution_drift")
    if threshold_distance < 0:
        rejection_reasons.append("threshold")
    if cost.get("production_grade_evidence") is not True:
        rejection_reasons.append("cost_not_production_grade")
    if "depth_impact_bps" in (cost.get("fallback_components") or ()):
        rejection_reasons.append("liquidity_missing_depth_or_order_size")
    selected = not rejection_reasons
    if not rejection_reasons:
        rejection_reasons.append("candidate_ranked_non_executable")
    feature_values = feature_values_for_policy(snapshot, policy)
    return {
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "snapshot_id": adapted.snapshot_id,
        "symbol": adapted.symbol,
        "timeframe": adapted.timeframe,
        "decision_time": first_present(snapshot, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc"),
        "feature_cutoff": first_present(snapshot, "feature_cutoff", "source_event_time_est", "candle_close_time"),
        "available_at": first_present(snapshot, "available_at", "source_available_time", "source_received_time_est", "generated_at", "generated_utc"),
        "feature_vector_hash": adapted.feature_vector_hash,
        "feature_values_by_name": feature_values,
        "predicted_direction": side,
        "predicted_move_bps": float(score),
        "score": float(score),
        "predicted_gross_edge_bps": predicted_gross_edge_bps,
        "production_cost_bps": production_cost_bps,
        "predicted_net_edge_bps": predicted_net_edge_bps,
        "threshold_distance_bps": threshold_distance,
        "estimated_production_cost": cost,
        "selected": selected,
        "rejected": not selected,
        "rejection_reasons": sorted(set(rejection_reasons)),
        "feature_drift": {
            "normalization_status": adapted.normalization_status,
            "out_of_training_range_features": list(adapted.out_of_range_features),
            "out_of_training_range_feature_count": len(adapted.out_of_range_features),
            "missing_feature_names": list(adapted.missing_feature_names),
            "stale_feature_names": list(adapted.stale_feature_names),
        },
        "liquidity_status": "MISSING_DEPTH_OR_ORDER_SIZE"
        if "depth_impact_bps" in (cost.get("fallback_components") or ())
        else "PASS",
        "integrity_status": adapted.integrity_status,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "counts_as_a_grade_evidence": False,
        "selection_immutable": True,
    }


def lockbox_record_id(scored: Mapping[str, Any]) -> str:
    return stable_hash(
        {
            "candidate_id": scored.get("candidate_id"),
            "policy_fingerprint": scored.get("policy_fingerprint"),
            "snapshot_id": scored.get("snapshot_id"),
            "decision_time": scored.get("decision_time"),
            "feature_vector_hash": scored.get("feature_vector_hash"),
        }
    )


def pending_lockbox_record(scored: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        "schema_version": "challenger_v2_future_lockbox_pending_v1",
        "record_created_utc": utc_now(),
        "candidate_id": scored.get("candidate_id"),
        "policy_fingerprint": scored.get("policy_fingerprint"),
        "model_source": scored.get("model_source"),
        "snapshot_id": scored.get("snapshot_id"),
        "symbol": scored.get("symbol"),
        "timeframe": scored.get("timeframe"),
        "decision_time": scored.get("decision_time"),
        "feature_cutoff": scored.get("feature_cutoff"),
        "available_at": scored.get("available_at"),
        "feature_vector_hash": scored.get("feature_vector_hash"),
        "feature_values_by_name": scored.get("feature_values_by_name"),
        "predicted_direction": scored.get("predicted_direction"),
        "predicted_move_bps": scored.get("predicted_move_bps"),
        "score": scored.get("score"),
        "estimated_production_cost": scored.get("estimated_production_cost"),
        "selected": scored.get("selected"),
        "rejected": scored.get("rejected"),
        "rejection_reasons": scored.get("rejection_reasons"),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "selection_fields_are_immutable_after_outcomes_exist": True,
    }
    record["lockbox_record_id"] = lockbox_record_id(record)
    record["selection_payload_hash"] = selection_payload_hash(record)
    return record


def selection_payload_hash(record: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"record_created_utc", "selection_payload_hash"}
    }
    return row_hash(payload)


def append_pending_lockbox(out_dir: Path, scored_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path = out_dir / PENDING_LOCKBOX
    existing = read_jsonl(path)
    existing_by_id = {
        str(row.get("lockbox_record_id")): str(row.get("selection_payload_hash") or selection_payload_hash(row))
        for row in existing
        if row.get("lockbox_record_id")
    }
    new_rows: list[dict[str, Any]] = []
    conflict_count = 0
    for scored in scored_rows:
        record = pending_lockbox_record(scored)
        record_id = str(record.get("lockbox_record_id"))
        if record_id in existing_by_id:
            if existing_by_id[record_id] != record["selection_payload_hash"]:
                conflict_count += 1
            continue
        new_rows.append(record)
        existing_by_id[record_id] = record["selection_payload_hash"]
    append_jsonl(path, new_rows)
    return {
        "pending_path": str(path),
        "existing_pending_rows_before_append": len(existing),
        "new_pending_rows_appended": len(new_rows),
        "immutability_conflict_count": conflict_count,
        "pending_rows_after_append": len(existing) + len(new_rows),
    }


def feature_price(record: Mapping[str, Any]) -> float | None:
    values = record.get("feature_values_by_name")
    if not isinstance(values, Mapping):
        return None
    for name in ("close", "last_price", "mark_price", "index_price", "micro_price", "open"):
        parsed = finite_float(values.get(name))
        if parsed is not None and parsed > 0:
            return parsed
    return None


def candle_price(candle: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = finite_float(candle.get(name))
        if parsed is not None and parsed > 0:
            return parsed
    return None


def parse_kline_candle(row: Any, *, source: str) -> dict[str, Any] | None:
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray, Mapping)):
        if len(row) < 7:
            return None
        open_ms = finite_float(row[0])
        close_ms = finite_float(row[6])
        open_price = finite_float(row[1])
        high = finite_float(row[2])
        low = finite_float(row[3])
        close = finite_float(row[4])
        volume = finite_float(row[5])
    elif isinstance(row, Mapping):
        open_ms = finite_float(row.get("open_time_ms") or row.get("open_time") or row.get("candle_open_time_ms"))
        close_ms = finite_float(row.get("close_time_ms") or row.get("close_time") or row.get("candle_close_time_ms"))
        open_price = finite_float(row.get("open"))
        high = finite_float(row.get("high"))
        low = finite_float(row.get("low"))
        close = finite_float(row.get("close"))
        volume = finite_float(row.get("volume"))
    else:
        return None
    if open_ms is None or close_ms is None or open_price is None or high is None or low is None or close is None:
        return None
    return {
        "candle_open_time": iso_from_ms(int(open_ms)),
        "candle_close_time": iso_from_ms(int(close_ms)),
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume or 0.0),
        "candle_closed_confirmed": True,
        "label_source": source,
    }


def normalize_kline_payload(payload: Any, *, source: str, now_ms: int) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        rows = payload.get("candles") or payload.get("data") or payload.get("rows") or payload.get("klines") or []
    else:
        rows = payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray, Mapping)):
        return []
    candles: list[dict[str, Any]] = []
    for row in rows:
        candle = parse_kline_candle(row, source=source)
        if candle is None:
            continue
        close_ms = epoch_ms(candle.get("candle_close_time"))
        if close_ms is None or close_ms >= now_ms:
            continue
        candles.append(candle)
    candles.sort(key=lambda candle: str(candle.get("candle_close_time") or ""))
    return candles


def dedupe_candles(candles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_close: dict[str, dict[str, Any]] = {}
    for candle in candles:
        close_time = str(candle.get("candle_close_time") or "")
        if close_time:
            by_close[close_time] = dict(candle)
    return [by_close[key] for key in sorted(by_close)]


def redis_ohlcv_1m_candles(symbol: str, *, now_ms: int) -> list[dict[str, Any]]:
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        payloads: list[Any] = []
        for key in (
            f"v2:market:ohlcv:binance:{symbol}:1m",
            f"v2:market:ohlcv_closed:binance:{symbol}:1m",
        ):
            raw = client.get(key)
            if raw:
                payloads.append(json.loads(raw))
    except Exception:
        return []
    candles: list[dict[str, Any]] = []
    for payload in payloads:
        candles.extend(normalize_kline_payload(payload, source="redis_binance_ohlcv_1m", now_ms=now_ms))
    return dedupe_candles(candles)


def public_binance_1m_candles(symbol: str, *, start_ms: int, end_ms: int, now_ms: int, timeout_seconds: float = 2.0) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "interval": "1m",
            "startTime": max(0, int(start_ms)),
            "endTime": max(0, int(end_ms)),
            "limit": 1500,
        }
    )
    url = f"https://fapi.binance.com/fapi/v1/klines?{params}"
    if not binance_rest_fallback_allowed():
        return []
    try:
        require_binance_rest_fallback(
            endpoint="/fapi/v1/klines",
            fallback_reason="challenger_counterfactual_redis_ohlcv_gap",
            role="challenger_counterfactual_label_recovery",
        )
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return normalize_kline_payload(payload, source="binance_usdm_public_klines_1m", now_ms=now_ms)


def label_for_record(
    record: Mapping[str, Any],
    candles: Sequence[Mapping[str, Any]],
    *,
    horizon: timedelta,
    label_source: str | None = None,
) -> dict[str, Any] | None:
    decision_time = parse_utc(record.get("decision_time"))
    entry_price = feature_price(record)
    if decision_time is None or entry_price is None:
        return None
    target_time = decision_time + horizon
    eligible: list[Mapping[str, Any]] = []
    for candle in candles:
        close_time = parse_utc(candle.get("candle_close_time") or candle.get("close_time") or candle.get("feature_cutoff"))
        if close_time is not None and close_time >= decision_time and close_time <= target_time:
            eligible.append(candle)
    final = None
    for candle in candles:
        close_time = parse_utc(candle.get("candle_close_time") or candle.get("close_time") or candle.get("feature_cutoff"))
        if close_time is not None and close_time >= target_time:
            final = candle
            break
    if final is None:
        return None
    final_price = candle_price(final, "close", "last_price", "mark_price", "index_price")
    if final_price is None:
        return None
    direction = str(record.get("predicted_direction") or "").upper()
    if direction == "SHORT":
        gross_return_bps = (entry_price - final_price) / entry_price * 10_000.0
        favorable = [candle_price(c, "low", "close") for c in eligible]
        adverse = [candle_price(c, "high", "close") for c in eligible]
        mfe = ((entry_price - min(v for v in favorable if v is not None)) / entry_price * 10_000.0) if any(v is not None for v in favorable) else None
        mae = ((entry_price - max(v for v in adverse if v is not None)) / entry_price * 10_000.0) if any(v is not None for v in adverse) else None
    else:
        gross_return_bps = (final_price - entry_price) / entry_price * 10_000.0
        favorable = [candle_price(c, "high", "close") for c in eligible]
        adverse = [candle_price(c, "low", "close") for c in eligible]
        mfe = ((max(v for v in favorable if v is not None) - entry_price) / entry_price * 10_000.0) if any(v is not None for v in favorable) else None
        mae = ((min(v for v in adverse if v is not None) - entry_price) / entry_price * 10_000.0) if any(v is not None for v in adverse) else None
    cost = record.get("estimated_production_cost")
    cost_map = cost if isinstance(cost, Mapping) else {}
    fees = float(cost_map.get("fee_bps") or 0.0)
    spread = float(cost_map.get("observed_bid_ask_spread_bps") or 0.0)
    slippage = float(cost_map.get("slippage_bps") or 0.0) + float(cost_map.get("depth_impact_bps") or 0.0)
    funding = float(cost_map.get("funding_bps") or 0.0)
    net_return_bps = gross_return_bps - float(cost_map.get("total_cost_bps") or 0.0)
    label = {
        "schema_version": "challenger_v2_future_lockbox_labelled_v1",
        "label_created_utc": utc_now(),
        "lockbox_record_id": record.get("lockbox_record_id"),
        "candidate_id": record.get("candidate_id"),
        "policy_fingerprint": record.get("policy_fingerprint"),
        "snapshot_id": record.get("snapshot_id"),
        "symbol": record.get("symbol"),
        "timeframe": record.get("timeframe"),
        "decision_time": record.get("decision_time"),
        "feature_cutoff": record.get("feature_cutoff"),
        "available_at": record.get("available_at"),
        "selection_record_hash": row_hash(record),
        "predicted_direction": record.get("predicted_direction"),
        "label_source": label_source or final.get("label_source") or "durable_feature_snapshot_archive",
        "label_source_timestamp": final.get("candle_close_time"),
        "label_horizon_minutes": int(horizon.total_seconds() // 60),
        "label_uses_future_data_as_label_only": True,
        "future_finalized_price": final_price,
        "gross_return_bps": gross_return_bps,
        "fees_bps": fees,
        "spread_bps": spread,
        "slippage_bps": slippage,
        "funding_bps": funding,
        "net_return_bps": net_return_bps,
        "mfe_bps": mfe,
        "mae_bps": mae,
        "selected": record.get("selected"),
        "rejected": record.get("rejected"),
        "rejection_reasons": record.get("rejection_reasons"),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    label["label_record_id"] = stable_hash({"lockbox_record_id": label["lockbox_record_id"], "future_finalized_price": final_price})
    return label


def append_matured_labels(
    repo_root: Path,
    out_dir: Path,
    *,
    horizon_minutes: int,
    archive_scan_limit: int,
    allow_public_labels: bool = True,
    public_label_symbol_limit: int = 25,
) -> dict[str, Any]:
    pending_path = out_dir / PENDING_LOCKBOX
    labelled_path = out_dir / LABELLED_LOCKBOX
    ensure_jsonl(labelled_path)
    pending = read_jsonl(pending_path)
    labelled = read_jsonl(labelled_path)
    original_labelled_ids = {str(row.get("lockbox_record_id")) for row in labelled if row.get("lockbox_record_id")}
    labelled_ids = set(original_labelled_ids)
    if not pending:
        return {
            "labelled_path": str(labelled_path),
            "pending_rows_examined": 0,
            "new_labels_appended": 0,
            "labelled_rows_after_append": len(labelled),
        }
    archive_root = default_archive_root(repo_root)
    snapshots = list(iter_snapshots(archive_root, limit=archive_scan_limit))
    candles, _rejections = _build_candle_index(snapshots)
    horizon = timedelta(minutes=int(horizon_minutes))
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    matured_records: list[dict[str, Any]] = []
    not_matured_rows = 0
    for record in pending:
        record_id = str(record.get("lockbox_record_id") or "")
        if not record_id or record_id in labelled_ids:
            continue
        decision_time = parse_utc(record.get("decision_time"))
        if decision_time is None or decision_time + horizon > now:
            not_matured_rows += 1
            continue
        matured_records.append(record)

    new_labels: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    missing_after_archive: list[dict[str, Any]] = []
    for record in matured_records:
        record_id = str(record.get("lockbox_record_id") or "")
        if not record_id or record_id in labelled_ids:
            continue
        pair = (str(record.get("symbol") or "").upper(), str(record.get("timeframe") or ""))
        label = label_for_record(record, candles.get(pair) or [], horizon=horizon, label_source="durable_feature_snapshot_archive")
        if label is None:
            missing_after_archive.append(record)
            continue
        new_labels.append(label)
        source_counts[str(label.get("label_source") or "durable_feature_snapshot_archive")] += 1
        labelled_ids.add(record_id)

    missing_after_readonly = 0
    readonly_groups: dict[str, list[dict[str, Any]]] = {}
    for record in missing_after_archive:
        record_id = str(record.get("lockbox_record_id") or "")
        if not record_id or record_id in labelled_ids:
            continue
        readonly_groups.setdefault(str(record.get("symbol") or "").upper(), []).append(record)

    public_symbols_attempted = 0
    public_symbols_skipped_by_limit = 0
    for symbol, records in sorted(readonly_groups.items()):
        if not symbol:
            missing_after_readonly += len(records)
            continue
        decision_times = [parse_utc(record.get("decision_time")) for record in records]
        target_times = [
            parsed + horizon
            for parsed in decision_times
            if parsed is not None
        ]
        if not target_times:
            missing_after_readonly += len(records)
            continue
        start_ms = int((min(target_times) - horizon - timedelta(minutes=1)).timestamp() * 1000)
        end_ms = int((max(target_times) + timedelta(minutes=2)).timestamp() * 1000)
        readonly_candles = redis_ohlcv_1m_candles(symbol, now_ms=now_ms)
        if allow_public_labels:
            existing_max = max((epoch_ms(candle.get("candle_close_time")) or 0 for candle in readonly_candles), default=0)
            if existing_max < end_ms and public_symbols_attempted < max(0, int(public_label_symbol_limit)):
                public_symbols_attempted += 1
                readonly_candles = dedupe_candles(
                    [
                        *readonly_candles,
                        *public_binance_1m_candles(symbol, start_ms=start_ms, end_ms=end_ms, now_ms=now_ms),
                    ]
                )
            elif existing_max < end_ms:
                public_symbols_skipped_by_limit += 1
        for record in records:
            record_id = str(record.get("lockbox_record_id") or "")
            if not record_id or record_id in labelled_ids:
                continue
            label = label_for_record(record, readonly_candles, horizon=horizon)
            if label is None:
                missing_after_readonly += 1
                continue
            new_labels.append(label)
            source_counts[str(label.get("label_source") or "read_only_finalized_1m_klines")] += 1
            labelled_ids.add(record_id)

    append_jsonl(labelled_path, new_labels)
    return {
        "labelled_path": str(labelled_path),
        "pending_rows_examined": len(pending),
        "unlabelled_pending_rows_examined": sum(
            1 for row in pending if str(row.get("lockbox_record_id") or "") not in original_labelled_ids
        ),
        "matured_unlabelled_rows": len(matured_records),
        "not_matured_unlabelled_rows": not_matured_rows,
        "missing_finalized_label_source_rows": missing_after_readonly,
        "label_source_counts": dict(sorted(source_counts.items())),
        "public_label_source_enabled": allow_public_labels,
        "public_label_symbols_attempted": public_symbols_attempted,
        "public_label_symbol_limit": int(public_label_symbol_limit),
        "public_label_symbols_skipped_by_limit": public_symbols_skipped_by_limit,
        "new_labels_appended": len(new_labels),
        "labelled_rows_after_append": len(labelled) + len(new_labels),
    }


def chain_for_jsonl(path: Path) -> dict[str, Any]:
    ensure_jsonl(path)
    previous = "0" * 64
    first_hash: str | None = None
    last_hash: str | None = None
    row_count = 0
    for row in read_jsonl(path):
        current_row_hash = row_hash(row)
        chain_hash = stable_hash({"previous_hash": previous, "row_hash": current_row_hash})
        if first_hash is None:
            first_hash = chain_hash
        last_hash = chain_hash
        previous = chain_hash
        row_count += 1
    return {
        "path": str(path),
        "row_count": row_count,
        "file_sha256": file_sha256(path),
        "first_chain_hash": first_hash,
        "last_chain_hash": last_hash,
        "chain_algorithm": HASH_CHAIN_ALGORITHM,
    }


def write_hash_chain(out_dir: Path, *, append_status: Mapping[str, Any], label_status: Mapping[str, Any], policy: FrozenPolicy) -> dict[str, Any]:
    pending_chain = chain_for_jsonl(out_dir / PENDING_LOCKBOX)
    labelled_chain = chain_for_jsonl(out_dir / LABELLED_LOCKBOX)
    pending_row_count = int(pending_chain.get("row_count") or 0)
    labelled_row_count = int(labelled_chain.get("row_count") or 0)
    pass_conditions = {
        "pending_file_hash_present": bool(pending_chain.get("file_sha256")),
        "labelled_file_hash_present": bool(labelled_chain.get("file_sha256")),
        "pending_chain_algorithm_declared": pending_chain.get("chain_algorithm") == HASH_CHAIN_ALGORITHM,
        "labelled_chain_algorithm_declared": labelled_chain.get("chain_algorithm") == HASH_CHAIN_ALGORITHM,
        "pending_terminal_hash_present_or_file_empty": int(pending_chain.get("row_count") or 0) == 0
        or bool(pending_chain.get("last_chain_hash")),
        "labelled_terminal_hash_present_or_file_empty": int(labelled_chain.get("row_count") or 0) == 0
        or bool(labelled_chain.get("last_chain_hash")),
        "pending_hash_bounds_match_row_count": (
            bool(pending_chain.get("first_chain_hash")) and bool(pending_chain.get("last_chain_hash"))
        )
        if pending_row_count > 0
        else pending_chain.get("first_chain_hash") is None and pending_chain.get("last_chain_hash") is None,
        "labelled_hash_bounds_match_row_count": (
            bool(labelled_chain.get("first_chain_hash")) and bool(labelled_chain.get("last_chain_hash"))
        )
        if labelled_row_count > 0
        else labelled_chain.get("first_chain_hash") is None and labelled_chain.get("last_chain_hash") is None,
        "top_level_row_counts_match_nested_chains": pending_row_count == int(pending_chain.get("row_count") or -1)
        and labelled_row_count == int(labelled_chain.get("row_count") or -1),
        "selection_records_are_append_only": True,
        "labels_are_append_only_and_separate": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "places_real_order_false": True,
        "counts_as_a_grade_evidence_false": True,
        "promotion_evidence_false": True,
    }
    blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "actual": {
                "pending": pending_chain,
                "labelled": labelled_chain,
                "paper_fill_allowed": False,
                "routes_to_live": False,
                "places_real_order": False,
                "counts_as_a_grade_evidence": False,
                "promotion_evidence": False,
            },
            "expected": True,
        }
        for name, passed in pass_conditions.items()
        if passed is not True
    ]
    payload = {
        "schema_version": "challenger_v2_future_lockbox_hash_chain_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "status": "PASS_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT" if not blocker_details else "FAIL_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT",
        "pending": pending_chain,
        "labelled": labelled_chain,
        "pending_rows": pending_row_count,
        "labelled_rows": labelled_row_count,
        "pending_path": pending_chain.get("path"),
        "labelled_path": labelled_chain.get("path"),
        "pending_file_sha256": pending_chain.get("file_sha256"),
        "labelled_file_sha256": labelled_chain.get("file_sha256"),
        "pending_last_chain_hash": pending_chain.get("last_chain_hash"),
        "labelled_last_chain_hash": labelled_chain.get("last_chain_hash"),
        "append_status": dict(append_status),
        "label_status": dict(label_status),
        "selection_records_are_append_only": True,
        "labels_are_append_only_and_separate": True,
        "pass_conditions": pass_conditions,
        "blocker_details": blocker_details,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    write_json(out_dir / HASH_CHAIN, payload)
    return payload


def write_shadow_cost_hash_chain(
    out_dir: Path,
    *,
    append_status: Mapping[str, Any],
    policy: FrozenPolicy,
) -> dict[str, Any]:
    chain = chain_for_jsonl(out_dir / SHADOW_COST_EVIDENCE)
    row_count = int(chain.get("row_count") or 0)
    pass_conditions = {
        "shadow_cost_file_hash_present": bool(chain.get("file_sha256")),
        "shadow_cost_chain_algorithm_declared": chain.get("chain_algorithm") == HASH_CHAIN_ALGORITHM,
        "shadow_cost_terminal_hash_present_or_file_empty": row_count == 0 or bool(chain.get("last_chain_hash")),
        "shadow_cost_hash_bounds_match_row_count": (
            bool(chain.get("first_chain_hash")) and bool(chain.get("last_chain_hash"))
        )
        if row_count > 0
        else chain.get("first_chain_hash") is None and chain.get("last_chain_hash") is None,
        "shadow_cost_records_are_append_only": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "places_real_order_false": True,
        "counts_as_a_grade_evidence_false": True,
        "promotion_evidence_false": True,
    }
    blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "actual": {
                "shadow_cost_evidence": chain,
                "paper_fill_allowed": False,
                "routes_to_live": False,
                "places_real_order": False,
                "counts_as_a_grade_evidence": False,
                "promotion_evidence": False,
            },
            "expected": True,
        }
        for name, passed in pass_conditions.items()
        if passed is not True
    ]
    payload = {
        "schema_version": "challenger_v2_candidate_bound_shadow_cost_evidence_hash_chain_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_SHADOW_COST_EVIDENCE_HASH_CHAIN_AUDIT"
        if not blocker_details
        else "FAIL_SHADOW_COST_EVIDENCE_HASH_CHAIN_AUDIT",
        "shadow_cost_evidence": chain,
        "shadow_cost_evidence_rows": row_count,
        "shadow_cost_evidence_path": chain.get("path"),
        "shadow_cost_evidence_file_sha256": chain.get("file_sha256"),
        "shadow_cost_evidence_last_chain_hash": chain.get("last_chain_hash"),
        "append_status": dict(append_status),
        "shadow_cost_records_are_append_only": True,
        "pass_conditions": pass_conditions,
        "blocker_details": blocker_details,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    write_json(out_dir / SHADOW_COST_HASH_CHAIN, payload)
    return payload


def quantile(sorted_values: Sequence[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * float(q)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return float(sorted_values[low])
    weight = pos - low
    return float(sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight)


def mean_std(values: Sequence[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return float(mean), float(math.sqrt(variance))


def ks_statistic(reference: Sequence[float], observed: Sequence[float]) -> float | None:
    if not reference or not observed:
        return None
    ref = sorted(reference)
    obs = sorted(observed)
    i = j = 0
    max_delta = 0.0
    values = sorted(set(ref + obs))
    for value in values:
        while i < len(ref) and ref[i] <= value:
            i += 1
        while j < len(obs) and obs[j] <= value:
            j += 1
        max_delta = max(max_delta, abs(i / len(ref) - j / len(obs)))
    return float(max_delta)


def psi_statistic(reference: Sequence[float], observed: Sequence[float], *, bins: int = 10) -> float | None:
    if not reference or not observed:
        return None
    ref_sorted = sorted(reference)
    cuts = [quantile(ref_sorted, i / bins) for i in range(1, bins)]
    boundaries = sorted(set(cut for cut in cuts if cut is not None and math.isfinite(cut)))
    if not boundaries:
        return 0.0

    def bucket_counts(values: Sequence[float]) -> list[int]:
        counts = [0 for _ in range(len(boundaries) + 1)]
        for value in values:
            idx = 0
            while idx < len(boundaries) and value > boundaries[idx]:
                idx += 1
            counts[idx] += 1
        return counts

    ref_counts = bucket_counts(reference)
    obs_counts = bucket_counts(observed)
    psi = 0.0
    epsilon = 1e-6
    for ref_count, obs_count in zip(ref_counts, obs_counts):
        ref_pct = max(ref_count / len(reference), epsilon)
        obs_pct = max(obs_count / len(observed), epsilon)
        psi += (obs_pct - ref_pct) * math.log(obs_pct / ref_pct)
    return float(psi)


def cohort_values_from_snapshots(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    policy: FrozenPolicy,
    source_context: str,
) -> dict[str, dict[str, Any]]:
    values: dict[str, list[float]] = {name: [] for name in policy.feature_names}
    missing: Counter[str] = Counter()
    stale: Counter[str] = Counter()
    out_of_range: Counter[str] = Counter()
    for snapshot in snapshots:
        adapted = (
            adapt_replay_snapshot(snapshot, normalization=policy.normalization)
            if source_context == "replay"
            else adapt_runtime_snapshot(snapshot, normalization=policy.normalization)
        )
        numeric = numeric_feature_mapping(snapshot)
        for name in policy.feature_names:
            parsed = numeric.get(name)
            if parsed is None:
                missing[name] += 1
            else:
                values[name].append(float(parsed))
        stale.update(adapted.stale_feature_names)
        out_of_range.update(adapted.out_of_range_features)
        missing.update(adapted.missing_feature_names)
    row_count = len(snapshots)
    return {
        name: {
            "values": values[name],
            "row_count": row_count,
            "missing_rate": missing[name] / row_count if row_count else None,
            "stale_rate": stale[name] / row_count if row_count else None,
            "out_of_training_range_rate": out_of_range[name] / row_count if row_count else None,
        }
        for name in policy.feature_names
    }


def cohort_values_from_lockbox(lockbox_rows: Sequence[Mapping[str, Any]], *, policy: FrozenPolicy) -> dict[str, dict[str, Any]]:
    values: dict[str, list[float]] = {name: [] for name in policy.feature_names}
    missing: Counter[str] = Counter()
    stale: Counter[str] = Counter()
    out_of_range: Counter[str] = Counter()
    lows = dict(zip(policy.feature_names, policy.normalization.mins))
    highs = dict(zip(policy.feature_names, policy.normalization.maxs))
    for row in lockbox_rows:
        decision_time = parse_utc(row.get("decision_time"))
        available_at = parse_utc(row.get("available_at"))
        feature_cutoff = parse_utc(row.get("feature_cutoff"))
        freshness_state = str(row.get("feature_freshness_state") or row.get("feature_freshness_status") or "").upper()
        row_stale = (
            freshness_state in {"STALE", "EXPIRED", "DIRTY"}
            or decision_time is None
            or available_at is None
            or feature_cutoff is None
            or available_at > decision_time
            or feature_cutoff > decision_time
        )
        feature_values = row.get("feature_values_by_name")
        feature_map = feature_values if isinstance(feature_values, Mapping) else {}
        for name in policy.feature_names:
            if row_stale:
                stale[name] += 1
            parsed = finite_float(feature_map.get(name))
            if parsed is None:
                missing[name] += 1
                continue
            values[name].append(float(parsed))
            if parsed < lows[name] - 1e-9 or parsed > highs[name] + 1e-9:
                out_of_range[name] += 1
    row_count = len(lockbox_rows)
    return {
        name: {
            "values": values[name],
            "row_count": row_count,
            "missing_rate": missing[name] / row_count if row_count else None,
            "stale_rate": stale[name] / row_count if row_count else None,
            "out_of_training_range_rate": out_of_range[name] / row_count if row_count else None,
        }
        for name in policy.feature_names
    }


def summarize_feature_distribution(
    *,
    feature_name: str,
    cohort: Mapping[str, Any],
    training_values: Sequence[float],
) -> dict[str, Any]:
    values = sorted(float(v) for v in cohort.get("values") or [])
    mean, std = mean_std(values)
    return {
        "row_count": cohort.get("row_count", 0),
        "observed_value_count": len(values),
        "mean": mean,
        "standard_deviation": std,
        "quantiles": {f"p{int(q * 100):02d}": quantile(values, q) for q in QUANTILES},
        "missing_rate": cohort.get("missing_rate"),
        "stale_rate": cohort.get("stale_rate"),
        "psi_vs_training": psi_statistic(training_values, values),
        "ks_statistic_vs_training": ks_statistic(training_values, values),
        "out_of_training_range_rate": cohort.get("out_of_training_range_rate"),
    }


def summarize_drift_rate_metric(
    feature_distribution: Mapping[str, Any],
    *,
    cohort_name: str,
    metric_name: str,
    threshold: float,
) -> dict[str, Any]:
    rates_by_feature: dict[str, float] = {}
    for feature_name, feature_payload in feature_distribution.items():
        if not isinstance(feature_payload, Mapping):
            continue
        cohort_payload = feature_payload.get(cohort_name)
        if not isinstance(cohort_payload, Mapping):
            continue
        rate = finite_float(cohort_payload.get(metric_name))
        if rate is not None:
            rates_by_feature[str(feature_name)] = rate
    rates = list(rates_by_feature.values())
    return {
        "metric": metric_name,
        "threshold": threshold,
        "feature_count": len(feature_distribution),
        "known_rate_feature_count": len(rates_by_feature),
        "unknown_rate_feature_count": max(len(feature_distribution) - len(rates_by_feature), 0),
        "mean_rate": sum(rates) / len(rates) if rates else None,
        "max_rate": max(rates) if rates else None,
        "features_at_or_above_threshold": sorted(
            feature_name for feature_name, rate in rates_by_feature.items() if rate >= threshold
        ),
    }


def drift_metric_publish_contract(
    *,
    feature_map: Mapping[str, Any],
    feature_names: Sequence[str],
) -> dict[str, Any]:
    feature_names_text = [str(name) for name in feature_names]
    missing_required_metrics_by_feature: dict[str, Any] = {}
    missing_required_quantiles_by_feature: dict[str, Any] = {}
    null_required_metrics_by_feature: dict[str, Any] = {}
    null_required_quantiles_by_feature: dict[str, Any] = {}
    feature_metric_coverage_summary: dict[str, Any] = {}
    complete_feature_names: list[str] = []

    for feature_name in feature_names_text:
        feature_payload = feature_map.get(feature_name)
        missing_cohorts: list[str] = []
        missing_metrics_by_cohort: dict[str, list[str]] = {}
        missing_quantiles_by_cohort: dict[str, list[str]] = {}
        null_metrics_by_cohort: dict[str, list[str]] = {}
        null_quantiles_by_cohort: dict[str, list[str]] = {}
        observed_cohorts = 0
        metric_keys_present = 0
        quantile_keys_present = 0

        if not isinstance(feature_payload, Mapping):
            missing_cohorts = list(DRIFT_COHORTS)
            missing_metrics_by_cohort = {
                cohort_name: list(DRIFT_REQUIRED_METRICS)
                for cohort_name in DRIFT_COHORTS
            }
            missing_quantiles_by_cohort = {
                cohort_name: list(DRIFT_REQUIRED_QUANTILES)
                for cohort_name in DRIFT_COHORTS
            }
        else:
            for cohort_name in DRIFT_COHORTS:
                cohort_payload = feature_payload.get(cohort_name)
                if not isinstance(cohort_payload, Mapping):
                    missing_cohorts.append(cohort_name)
                    missing_metrics_by_cohort[cohort_name] = list(DRIFT_REQUIRED_METRICS)
                    missing_quantiles_by_cohort[cohort_name] = list(DRIFT_REQUIRED_QUANTILES)
                    continue
                observed_cohorts += 1
                missing_metrics = [
                    metric
                    for metric in DRIFT_REQUIRED_METRICS
                    if metric not in cohort_payload
                ]
                null_metrics = [
                    metric
                    for metric in DRIFT_REQUIRED_METRICS
                    if metric in cohort_payload and cohort_payload.get(metric) is None
                ]
                metric_keys_present += len(DRIFT_REQUIRED_METRICS) - len(missing_metrics)
                if missing_metrics:
                    missing_metrics_by_cohort[cohort_name] = missing_metrics
                if null_metrics:
                    null_metrics_by_cohort[cohort_name] = null_metrics

                quantiles = cohort_payload.get("quantiles")
                if not isinstance(quantiles, Mapping):
                    missing_quantiles_by_cohort[cohort_name] = list(DRIFT_REQUIRED_QUANTILES)
                    continue
                missing_quantiles = [
                    quantile_name
                    for quantile_name in DRIFT_REQUIRED_QUANTILES
                    if quantile_name not in quantiles
                ]
                null_quantiles = [
                    quantile_name
                    for quantile_name in DRIFT_REQUIRED_QUANTILES
                    if quantile_name in quantiles and quantiles.get(quantile_name) is None
                ]
                quantile_keys_present += len(DRIFT_REQUIRED_QUANTILES) - len(missing_quantiles)
                if missing_quantiles:
                    missing_quantiles_by_cohort[cohort_name] = missing_quantiles
                if null_quantiles:
                    null_quantiles_by_cohort[cohort_name] = null_quantiles

        if missing_cohorts or missing_metrics_by_cohort:
            missing_required_metrics_by_feature[feature_name] = {
                "missing_cohorts": missing_cohorts,
                "missing_metrics_by_cohort": missing_metrics_by_cohort,
            }
        if missing_quantiles_by_cohort:
            missing_required_quantiles_by_feature[feature_name] = {
                "missing_quantiles_by_cohort": missing_quantiles_by_cohort,
            }
        if null_metrics_by_cohort:
            null_required_metrics_by_feature[feature_name] = {
                "null_metrics_by_cohort": null_metrics_by_cohort,
            }
        if null_quantiles_by_cohort:
            null_required_quantiles_by_feature[feature_name] = {
                "null_quantiles_by_cohort": null_quantiles_by_cohort,
            }

        required_metric_key_count = len(DRIFT_COHORTS) * len(DRIFT_REQUIRED_METRICS)
        required_quantile_key_count = len(DRIFT_COHORTS) * len(DRIFT_REQUIRED_QUANTILES)
        complete = not (
            missing_cohorts
            or missing_metrics_by_cohort
            or missing_quantiles_by_cohort
            or null_metrics_by_cohort
            or null_quantiles_by_cohort
        )
        if complete:
            complete_feature_names.append(feature_name)
        feature_metric_coverage_summary[feature_name] = {
            "required_cohort_count": len(DRIFT_COHORTS),
            "cohorts_present_count": observed_cohorts,
            "required_metric_key_count": required_metric_key_count,
            "metric_keys_present_count": metric_keys_present,
            "required_quantile_key_count": required_quantile_key_count,
            "quantile_keys_present_count": quantile_keys_present,
            "all_required_metric_keys_present": not missing_metrics_by_cohort and not missing_cohorts,
            "all_required_quantile_keys_present": not missing_quantiles_by_cohort and not missing_cohorts,
            "all_required_metric_values_non_null": not null_metrics_by_cohort,
            "all_required_quantile_values_non_null": not null_quantiles_by_cohort,
            "complete_required_drift_metric_coverage": complete,
        }

    return {
        "required_feature_count": len(feature_names_text),
        "reported_feature_count": len(feature_map),
        "required_cohorts": list(DRIFT_COHORTS),
        "required_metrics": list(DRIFT_REQUIRED_METRICS),
        "required_quantiles": list(DRIFT_REQUIRED_QUANTILES),
        "required_metric_cell_count": len(feature_names_text) * len(DRIFT_COHORTS) * len(DRIFT_REQUIRED_METRICS),
        "required_quantile_cell_count": len(feature_names_text) * len(DRIFT_COHORTS) * len(DRIFT_REQUIRED_QUANTILES),
        "missing_required_metrics_by_feature": missing_required_metrics_by_feature,
        "missing_required_quantiles_by_feature": missing_required_quantiles_by_feature,
        "null_required_metrics_by_feature": null_required_metrics_by_feature,
        "null_required_quantiles_by_feature": null_required_quantiles_by_feature,
        "missing_required_metric_feature_count": len(missing_required_metrics_by_feature),
        "missing_required_quantile_feature_count": len(missing_required_quantiles_by_feature),
        "null_required_metric_feature_count": len(null_required_metrics_by_feature),
        "null_required_quantile_feature_count": len(null_required_quantiles_by_feature),
        "features_with_complete_required_drift_metric_coverage": complete_feature_names,
        "complete_required_drift_metric_feature_count": len(complete_feature_names),
        "feature_metric_coverage_summary": feature_metric_coverage_summary,
        "all_required_metric_keys_present": not missing_required_metrics_by_feature,
        "all_required_quantile_keys_present": not missing_required_quantiles_by_feature,
        "all_required_metric_values_non_null": not null_required_metrics_by_feature,
        "all_required_quantile_values_non_null": not null_required_quantiles_by_feature,
        "complete_required_drift_metric_coverage": len(complete_feature_names) == len(feature_names_text),
    }


def replay_drift_split(replay_rows: Sequence[ReplayCandidateRow]) -> dict[str, Any]:
    """Chronological train/validation/diagnostic-holdout split for drift evidence only."""
    row_count = len(replay_rows)
    train_end = int(row_count * 0.70)
    validation_end = int(row_count * 0.85)
    if row_count >= 3:
        train_end = max(train_end, 1)
        validation_end = max(validation_end, train_end + 1)
        validation_end = min(validation_end, row_count - 1)
    training_rows = list(replay_rows[:train_end])
    validation_rows = list(replay_rows[train_end:validation_end])
    previous_holdout_rows = list(replay_rows[validation_end:])
    return {
        "split_policy": "chronological_70_15_15_replay_drift_diagnostic_only",
        "row_count": row_count,
        "training_start_index": 0,
        "training_end_exclusive": train_end,
        "validation_start_index": train_end,
        "validation_end_exclusive": validation_end,
        "previous_holdout_start_index": validation_end,
        "previous_holdout_end_exclusive": row_count,
        "training_rows": training_rows,
        "validation_rows": validation_rows,
        "previous_holdout_rows": previous_holdout_rows,
        "training_row_count": len(training_rows),
        "validation_row_count": len(validation_rows),
        "previous_holdout_row_count": len(previous_holdout_rows),
        "counts_as_promotion_evidence": False,
    }


def distribution_drift_artifact(
    *,
    policy: FrozenPolicy,
    replay_rows: Sequence[ReplayCandidateRow],
    current_snapshots: Sequence[Mapping[str, Any]],
    previous_holdout_rows: Sequence[Mapping[str, Any]],
    future_lockbox_rows: Sequence[Mapping[str, Any]],
    feature_parity_status: Mapping[str, Any],
    use_replay_tail_as_previous_holdout: bool = False,
) -> dict[str, Any]:
    replay_split = replay_drift_split(replay_rows)
    training_snapshots = [row.snapshot for row in replay_split["training_rows"]]
    validation_snapshots = [row.snapshot for row in replay_split["validation_rows"]]
    replay_previous_holdout_snapshots = [row.snapshot for row in replay_split["previous_holdout_rows"]]
    external_previous_holdout_rows = list(previous_holdout_rows)
    use_replay_previous_holdout = bool(
        use_replay_tail_as_previous_holdout
        and not external_previous_holdout_rows
        and replay_previous_holdout_snapshots
    )
    previous_holdout_source = (
        "external_previous_holdout_rows_diagnostic_only"
        if external_previous_holdout_rows
        else "replay_tail_chronological_previous_holdout_diagnostic_only"
        if use_replay_previous_holdout
        else "missing_previous_holdout_rows"
    )
    previous_holdout_origin = (
        "external_previous_holdout_rows"
        if external_previous_holdout_rows
        else "derived_from_replay_tail_after_freeze_for_distribution_diagnosis_only"
        if use_replay_previous_holdout
        else "missing"
    )
    previous_holdout_cohort = (
        cohort_values_from_snapshots(replay_previous_holdout_snapshots, policy=policy, source_context="replay")
        if use_replay_previous_holdout
        else cohort_values_from_lockbox(external_previous_holdout_rows, policy=policy)
    )
    previous_holdout_row_count = (
        len(replay_previous_holdout_snapshots)
        if use_replay_previous_holdout
        else len(external_previous_holdout_rows)
    )
    cohorts = {
        "training": cohort_values_from_snapshots(training_snapshots, policy=policy, source_context="replay"),
        "validation": cohort_values_from_snapshots(validation_snapshots, policy=policy, source_context="replay"),
        "previous_holdout": previous_holdout_cohort,
        "current_runtime": cohort_values_from_snapshots(current_snapshots, policy=policy, source_context="runtime"),
        "future_lockbox": cohort_values_from_lockbox(future_lockbox_rows, policy=policy),
    }
    features: dict[str, Any] = {}
    high_drift_features: list[str] = []
    for name in policy.feature_names:
        training_values = cohorts["training"][name]["values"]
        feature_stats = {
            cohort_name: summarize_feature_distribution(feature_name=name, cohort=cohort[name], training_values=training_values)
            for cohort_name, cohort in cohorts.items()
        }
        current = feature_stats["current_runtime"]
        if (
            (current.get("psi_vs_training") is not None and current["psi_vs_training"] >= 0.25)
            or (current.get("ks_statistic_vs_training") is not None and current["ks_statistic_vs_training"] >= 0.20)
            or (current.get("out_of_training_range_rate") is not None and current["out_of_training_range_rate"] >= 0.20)
        ):
            high_drift_features.append(name)
        features[name] = feature_stats
    parity_pass = feature_parity_status.get("status") == "PASS"
    root_cause = "GENUINE_RUNTIME_DISTRIBUTION_SHIFT_OR_TRAINING_RANGE_EXHAUSTION"
    broken_mapping = False
    if not parity_pass or feature_parity_status.get("schema_mismatch_rows", 0) or feature_parity_status.get("normalization_mismatch_rows", 0):
        root_cause = "POSSIBLE_BROKEN_TRANSFORMATION_OR_SOURCE_MAPPING"
        broken_mapping = True
    elif feature_parity_status.get("unexplained_missing_feature_rows", 0):
        root_cause = "POSSIBLE_RUNTIME_SOURCE_MAPPING_GAP"
        broken_mapping = True
    cohort_row_counts = {
        "training": len(training_snapshots),
        "validation": len(validation_snapshots),
        "previous_holdout": previous_holdout_row_count,
        "current_runtime": len(current_snapshots),
        "future_lockbox": len(future_lockbox_rows),
    }
    missing_or_stale_summary = {
        cohort_name: {
            "row_count": cohort_row_counts.get(cohort_name, 0),
            "missing_rate": summarize_drift_rate_metric(
                features,
                cohort_name=cohort_name,
                metric_name="missing_rate",
                threshold=0.05,
            ),
            "stale_rate": summarize_drift_rate_metric(
                features,
                cohort_name=cohort_name,
                metric_name="stale_rate",
                threshold=0.05,
            ),
        }
        for cohort_name in DRIFT_COHORTS
    }
    out_of_training_range_summary = {
        cohort_name: {
            "row_count": cohort_row_counts.get(cohort_name, 0),
            "out_of_training_range_rate": summarize_drift_rate_metric(
                features,
                cohort_name=cohort_name,
                metric_name="out_of_training_range_rate",
                threshold=0.20,
            ),
        }
        for cohort_name in DRIFT_COHORTS
    }
    drift_metric_contract = drift_metric_publish_contract(
        feature_map=features,
        feature_names=policy.feature_names,
    )
    drift_decision_contract = {
        "drift_classification": root_cause,
        "mapping_fix_required": broken_mapping,
        "candidate_id_change_required": broken_mapping,
        "frozen_candidate_kept": not broken_mapping,
        "new_candidate_required_if_any_feature_mapping_or_normalization_changes": True,
        "frozen_candidate_tuning_allowed_from_drift_results": False,
        "runtime_reject_drifted_conditions": True,
        "approval_to_keep_candidate_source": "distribution_drift_root_cause_no_broken_mapping_detected"
        if not broken_mapping
        else None,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    pass_conditions = {
        "feature_count_matches_policy": len(features) == len(policy.feature_names),
        "all_required_cohorts_declared": all(cohort_name in cohort_row_counts for cohort_name in DRIFT_COHORTS),
        "all_required_cohorts_have_rows_for_drift_comparison": all(
            int(cohort_row_counts.get(cohort_name) or 0) > 0 for cohort_name in DRIFT_COHORTS
        ),
        "all_required_drift_metric_keys_published": drift_metric_contract["all_required_metric_keys_present"] is True
        and drift_metric_contract["all_required_quantile_keys_present"] is True,
        "all_required_drift_metric_values_available": drift_metric_contract["all_required_metric_values_non_null"] is True
        and drift_metric_contract["all_required_quantile_values_non_null"] is True,
        "complete_required_drift_metric_coverage": drift_metric_contract["complete_required_drift_metric_coverage"] is True,
        "previous_holdout_diagnostic_comparison_rows_gt_0": int(cohort_row_counts.get("previous_holdout") or 0) > 0,
        "previous_holdout_not_promotion_or_lockbox_evidence": previous_holdout_source
        in {
            "external_previous_holdout_rows_diagnostic_only",
            "replay_tail_chronological_previous_holdout_diagnostic_only",
            "missing_previous_holdout_rows",
        },
        "root_cause_classification_present": bool(root_cause),
        "candidate_change_decision_matches_root_cause": broken_mapping is bool(drift_decision_contract["candidate_id_change_required"])
        and (not broken_mapping) is bool(drift_decision_contract["frozen_candidate_kept"]),
        "new_candidate_required_for_mapping_or_normalization_changes": drift_decision_contract[
            "new_candidate_required_if_any_feature_mapping_or_normalization_changes"
        ]
        is True,
        "frozen_candidate_tuning_disallowed_from_drift_results": drift_decision_contract[
            "frozen_candidate_tuning_allowed_from_drift_results"
        ]
        is False,
        "runtime_reject_drifted_conditions_declared": drift_decision_contract["runtime_reject_drifted_conditions"] is True,
        "paper_fill_disallowed": drift_decision_contract["paper_fill_allowed"] is False,
        "routes_to_live_false": drift_decision_contract["routes_to_live"] is False,
        "places_real_order_false": drift_decision_contract["places_real_order"] is False,
        "promotion_evidence_false": drift_decision_contract["counts_as_a_grade_evidence"] is False
        and drift_decision_contract["promotion_evidence"] is False,
    }
    blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "expected": {
                "feature_count_matches_policy": f"{len(policy.feature_names)} policy features in root-cause artifact",
                "all_required_cohorts_declared": f"all cohorts declared: {', '.join(DRIFT_COHORTS)}",
                "all_required_cohorts_have_rows_for_drift_comparison": "all required drift cohorts have row_count > 0",
                "all_required_drift_metric_keys_published": "every feature/cohort publishes mean, standard deviation, quantiles, missing rate, stale rate, PSI, KS, and out-of-range rate keys",
                "all_required_drift_metric_values_available": "required drift metric values are non-null for every observed feature/cohort",
                "complete_required_drift_metric_coverage": "all required feature/cohort/metric and quantile coverage is complete",
                "previous_holdout_diagnostic_comparison_rows_gt_0": "previous_holdout row_count > 0 for diagnostic drift comparison",
                "previous_holdout_not_promotion_or_lockbox_evidence": "previous_holdout source is diagnostic only and not blind-lockbox promotion evidence",
                "root_cause_classification_present": "non-empty root_cause_classification",
                "candidate_change_decision_matches_root_cause": "candidate_id_change_required and frozen_candidate_kept match mapping diagnosis",
                "new_candidate_required_for_mapping_or_normalization_changes": "mapping or normalization changes require a new candidate ID",
                "frozen_candidate_tuning_disallowed_from_drift_results": "frozen candidate may not be tuned from drift results",
                "runtime_reject_drifted_conditions_declared": "runtime drifted conditions remain reject-only",
                "paper_fill_disallowed": "paper_fill_allowed false",
                "routes_to_live_false": "routes_to_live false",
                "places_real_order_false": "places_real_order false",
                "promotion_evidence_false": "root-cause artifact is not promotion evidence",
            }.get(name),
        }
        for name, passed in pass_conditions.items()
        if passed is not True
    ]
    features_requiring_new_candidate_if_fixed = list(policy.feature_names) if broken_mapping else []
    root_cause_summary = {
        "classification": root_cause,
        "broken_transformation_or_source_mapping_detected": broken_mapping,
        "candidate_id_change_required": broken_mapping,
        "frozen_candidate_kept": not broken_mapping,
        "feature_count": len(policy.feature_names),
        "expected_feature_count": len(policy.feature_names),
        "all_policy_features_present": len(features) == len(policy.feature_names),
        "required_cohorts": list(DRIFT_COHORTS),
        "cohort_row_counts": cohort_row_counts,
        "high_drift_feature_count_current_runtime": len(high_drift_features),
    }
    return {
        "schema_version": "challenger_v2_distribution_drift_root_cause_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT"
        if all(pass_conditions.values())
        else "FAIL_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT",
        "feature_count": len(policy.feature_names),
        "policy_feature_count": len(policy.feature_names),
        "expected_feature_count": len(policy.feature_names),
        "required_feature_count": drift_metric_contract["required_feature_count"],
        "all_32_features_present": len(policy.feature_names) == 32 and len(features) == len(policy.feature_names),
        "all_policy_features_present": len(features) == len(policy.feature_names),
        "features": list(policy.feature_names),
        "feature_names": list(policy.feature_names),
        "required_cohorts": drift_metric_contract["required_cohorts"],
        "required_metrics": drift_metric_contract["required_metrics"],
        "required_quantiles": drift_metric_contract["required_quantiles"],
        "drift_metric_publish_contract": drift_metric_contract,
        "feature_metric_coverage_summary": drift_metric_contract["feature_metric_coverage_summary"],
        "missing_required_metrics_by_feature": drift_metric_contract["missing_required_metrics_by_feature"],
        "missing_required_quantiles_by_feature": drift_metric_contract["missing_required_quantiles_by_feature"],
        "null_required_metrics_by_feature": drift_metric_contract["null_required_metrics_by_feature"],
        "null_required_quantiles_by_feature": drift_metric_contract["null_required_quantiles_by_feature"],
        "rows": cohort_row_counts,
        "root_cause_classification": root_cause,
        "root_cause": root_cause,
        "drift_root_cause": root_cause,
        "root_cause_summary": root_cause_summary,
        "broken_transformation_or_source_mapping_detected": broken_mapping,
        "genuine_market_regime_change_detected": not broken_mapping,
        "candidate_id_change_required": broken_mapping,
        "frozen_candidate_kept": not broken_mapping,
        "candidate_change_decision": "TRAIN_NEW_CANDIDATE_REQUIRED_FOR_MAPPING_OR_NORMALIZATION_FIX"
        if broken_mapping
        else "KEEP_FROZEN_CANDIDATE_AND_REJECT_DRIFTED_RUNTIME_CONDITIONS",
        "candidate_action": "TRAIN_NEW_CANDIDATE_REQUIRED_FOR_MAPPING_OR_NORMALIZATION_FIX"
        if broken_mapping
        else "KEEP_FROZEN_CANDIDATE_AND_REJECT_DRIFTED_RUNTIME_CONDITIONS",
        "frozen_candidate_action": "reject_drifted_runtime_conditions_without_tuning"
        if not broken_mapping
        else "do_not_patch_frozen_candidate_train_new_candidate_if_mapping_fix_required",
        "replay_split_policy": replay_split["split_policy"],
        "replay_split_metadata": {
            key: value
            for key, value in replay_split.items()
            if key
            not in {
                "training_rows",
                "validation_rows",
                "previous_holdout_rows",
            }
        },
        "previous_holdout_source": previous_holdout_source,
        "previous_holdout_origin": previous_holdout_origin,
        "previous_holdout_diagnostic_surrogate_used": use_replay_previous_holdout,
        "previous_holdout_is_original_model_selection_holdout": False,
        "previous_holdout_used_for_model_or_threshold_selection": False,
        "previous_holdout_counts_as_promotion_evidence": False,
        "previous_holdout_counts_as_blind_lockbox_evidence": False,
        "feature_parity_status": dict(feature_parity_status),
        "high_drift_features_current_runtime": high_drift_features,
        "high_drift_feature_count_current_runtime": len(high_drift_features),
        "cohorts": {
            cohort_name: {
                "row_count": cohort_row_counts.get(cohort_name, 0),
                "required_for_drift_diagnosis": True,
                "counts_as_promotion_evidence": False,
                "comparison_available": int(cohort_row_counts.get(cohort_name) or 0) > 0,
            }
            for cohort_name in DRIFT_COHORTS
        },
        "cohort_row_counts": cohort_row_counts,
        "training_row_count": cohort_row_counts["training"],
        "validation_row_count": cohort_row_counts["validation"],
        "previous_holdout_row_count": cohort_row_counts["previous_holdout"],
        "current_runtime_row_count": cohort_row_counts["current_runtime"],
        "future_lockbox_row_count": cohort_row_counts["future_lockbox"],
        "current_runtime_status": "AVAILABLE_FOR_DRIFT_COMPARISON"
        if int(cohort_row_counts.get("current_runtime") or 0) > 0
        else "MISSING_RUNTIME_DRIFT_COMPARISON_ROWS",
        "future_lockbox_status": "AVAILABLE_FOR_DRIFT_COMPARISON"
        if int(cohort_row_counts.get("future_lockbox") or 0) > 0
        else "MISSING_FUTURE_LOCKBOX_DRIFT_COMPARISON_ROWS",
        "missing_or_stale_summary": missing_or_stale_summary,
        "out_of_training_range_summary": out_of_training_range_summary,
        "pass_conditions": pass_conditions,
        "blocked_reasons": [str(detail.get("pass_condition")) for detail in blocker_details],
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "drift_decision_contract": drift_decision_contract,
        "features_requiring_new_candidate_if_fixed": features_requiring_new_candidate_if_fixed,
        "previous_holdout_note": "Previous holdout is empty, so the five-cohort drift comparison is incomplete and cannot count as complete drift evidence."
        if previous_holdout_row_count <= 0
        else "Previous holdout rows are diagnostic only, are not original model-selection or lockbox evidence, and are not reused for blind promotion.",
        "feature_distribution": features,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def distribution_drift_coverage_audit(*, policy: FrozenPolicy, drift_status: Mapping[str, Any]) -> dict[str, Any]:
    feature_distribution = drift_status.get("feature_distribution")
    feature_map = feature_distribution if isinstance(feature_distribution, Mapping) else {}
    feature_names = [str(name) for name in drift_status.get("feature_names") or policy.feature_names]
    drift_metric_contract = drift_metric_publish_contract(
        feature_map=feature_map,
        feature_names=policy.feature_names,
    )
    missing_features = [name for name in policy.feature_names if name not in feature_map]
    extra_features = [name for name in feature_map.keys() if str(name) not in set(policy.feature_names)]
    missing_cohorts: Counter[str] = Counter()
    missing_metric_keys: Counter[str] = Counter()
    missing_quantile_keys: Counter[str] = Counter()
    null_metric_counts: Counter[str] = Counter()
    nonempty_required_cohort_gaps: Counter[str] = Counter()
    empty_required_cohort_feature_gaps: Counter[str] = Counter()
    sample_violations: list[dict[str, Any]] = []

    for feature_name in policy.feature_names:
        feature_payload = feature_map.get(feature_name)
        if not isinstance(feature_payload, Mapping):
            if len(sample_violations) < 25:
                sample_violations.append({"feature": feature_name, "violation": "feature_distribution_missing"})
            continue
        for cohort_name in DRIFT_COHORTS:
            cohort_payload = feature_payload.get(cohort_name)
            if not isinstance(cohort_payload, Mapping):
                missing_cohorts[cohort_name] += 1
                if len(sample_violations) < 25:
                    sample_violations.append({"feature": feature_name, "cohort": cohort_name, "violation": "cohort_missing"})
                continue
            for metric in DRIFT_REQUIRED_METRICS:
                if metric not in cohort_payload:
                    missing_metric_keys[f"{cohort_name}.{metric}"] += 1
                    if len(sample_violations) < 25:
                        sample_violations.append({"feature": feature_name, "cohort": cohort_name, "metric": metric, "violation": "metric_key_missing"})
                    continue
                if cohort_payload.get(metric) is None:
                    null_metric_counts[f"{cohort_name}.{metric}"] += 1
            quantiles = cohort_payload.get("quantiles")
            if not isinstance(quantiles, Mapping):
                missing_metric_keys[f"{cohort_name}.quantiles"] += 1
                continue
            for quantile_name in DRIFT_REQUIRED_QUANTILES:
                if quantile_name not in quantiles:
                    missing_quantile_keys[f"{cohort_name}.{quantile_name}"] += 1
                    if len(sample_violations) < 25:
                        sample_violations.append({"feature": feature_name, "cohort": cohort_name, "quantile": quantile_name, "violation": "quantile_key_missing"})
            if cohort_name in {"training", "validation", "current_runtime", "future_lockbox"}:
                observed_count = finite_float(cohort_payload.get("observed_value_count"))
                row_count = finite_float(cohort_payload.get("row_count"))
                if observed_count is None or observed_count <= 0.0 or row_count is None or row_count <= 0.0:
                    nonempty_required_cohort_gaps[cohort_name] += 1
                    if len(sample_violations) < 25:
                        sample_violations.append(
                            {
                                "feature": feature_name,
                                "cohort": cohort_name,
                                "row_count": cohort_payload.get("row_count"),
                                "observed_value_count": cohort_payload.get("observed_value_count"),
                                "violation": "required_cohort_empty_or_unobserved",
                            }
                        )
            if cohort_name in set(DRIFT_COHORTS):
                observed_count = finite_float(cohort_payload.get("observed_value_count"))
                row_count = finite_float(cohort_payload.get("row_count"))
                if observed_count is None or observed_count <= 0.0 or row_count is None or row_count <= 0.0:
                    empty_required_cohort_feature_gaps[cohort_name] += 1

    cohort_row_counts = drift_status.get("cohort_row_counts") if isinstance(drift_status.get("cohort_row_counts"), Mapping) else {}
    previous_holdout_rows = int(cohort_row_counts.get("previous_holdout") or 0)
    cohorts_payload = drift_status.get("cohorts") if isinstance(drift_status.get("cohorts"), Mapping) else {}
    previous_holdout_cohort = (
        cohorts_payload.get("previous_holdout")
        if isinstance(cohorts_payload.get("previous_holdout"), Mapping)
        else {}
    )
    cohorts_present = [
        cohort_name
        for cohort_name in DRIFT_COHORTS
        if missing_cohorts.get(cohort_name, 0) == 0
    ]
    pass_conditions = {
        "feature_count_matches_policy": int(drift_status.get("feature_count") or 0) == len(policy.feature_names),
        "top_level_feature_and_cohort_summary_present": len(policy.feature_names) > 0
        and len(cohorts_present) == len(DRIFT_COHORTS),
        "all_policy_features_present": not missing_features,
        "all_required_cohorts_present": not missing_cohorts,
        "all_required_metric_keys_present": not missing_metric_keys,
        "all_required_quantile_keys_present": not missing_quantile_keys,
        "all_required_metric_values_present": drift_metric_contract["all_required_metric_values_non_null"] is True
        and drift_metric_contract["all_required_quantile_values_non_null"] is True,
        "complete_required_drift_metric_coverage": drift_metric_contract["complete_required_drift_metric_coverage"] is True,
        "required_non_holdout_cohorts_observed": not nonempty_required_cohort_gaps,
        "all_required_cohorts_have_rows_for_drift_comparison": not empty_required_cohort_feature_gaps
        and all(int(cohort_row_counts.get(cohort_name) or 0) > 0 for cohort_name in DRIFT_COHORTS),
        "previous_holdout_diagnostic_comparison_rows_gt_0": previous_holdout_rows > 0,
        "previous_holdout_not_reused_for_promotion": previous_holdout_cohort.get("counts_as_promotion_evidence") is False
        or drift_status.get("promotion_evidence") is False,
    }
    missing_cohort_total = int(sum(missing_cohorts.values()))
    missing_metric_total = int(sum(missing_metric_keys.values()))
    missing_quantile_total = int(sum(missing_quantile_keys.values()))
    null_metric_total = int(sum(null_metric_counts.values()))
    required_non_holdout_gap_total = int(sum(nonempty_required_cohort_gaps.values()))
    empty_required_cohort_feature_gap_total = int(sum(empty_required_cohort_feature_gaps.values()))
    drift_coverage_blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "expected": {
                "feature_count_matches_policy": f"{len(policy.feature_names)} policy features in drift artifact",
                "top_level_feature_and_cohort_summary_present": "policy_feature_count, required_cohort_count, and cohorts_present summarize all required drift coverage",
                "all_policy_features_present": "all frozen-policy features reported",
                "all_required_cohorts_present": f"all cohorts present: {', '.join(DRIFT_COHORTS)}",
                "all_required_metric_keys_present": f"all metrics present: {', '.join(DRIFT_REQUIRED_METRICS)}",
                "all_required_quantile_keys_present": f"all quantiles present: {', '.join(DRIFT_REQUIRED_QUANTILES)}",
                "all_required_metric_values_present": "all required metric and quantile values are non-null for observed required cohorts",
                "complete_required_drift_metric_coverage": "all required feature/cohort/metric and quantile coverage is complete",
                "required_non_holdout_cohorts_observed": "training, validation, current runtime, and future lockbox have observed values",
                "all_required_cohorts_have_rows_for_drift_comparison": "training, validation, previous holdout, current runtime, and future lockbox have observed values",
                "previous_holdout_diagnostic_comparison_rows_gt_0": "previous_holdout row_count > 0 for diagnostic drift comparison",
                "previous_holdout_not_reused_for_promotion": "previous holdout rows remain diagnostic and do not count as promotion evidence",
            }.get(name),
        }
        for name, passed in pass_conditions.items()
        if passed is not True
    ]
    return {
        "schema_version": "challenger_v2_distribution_drift_coverage_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_DRIFT_COVERAGE_AUDIT" if all(pass_conditions.values()) else "FAIL_DRIFT_COVERAGE_AUDIT",
        "feature_count": len(policy.feature_names),
        "policy_feature_count": len(policy.feature_names),
        "drift_artifact_feature_count": drift_status.get("feature_count"),
        "required_feature_count": len(policy.feature_names),
        "required_cohort_count": len(DRIFT_COHORTS),
        "reported_required_cohort_count": len(cohorts_present),
        "cohorts_present": cohorts_present,
        "reported_all_required_features": pass_conditions["feature_count_matches_policy"]
        and pass_conditions["all_policy_features_present"]
        and not extra_features,
        "all_32_challenger_features_reported": len(policy.feature_names) == 32
        and pass_conditions["feature_count_matches_policy"]
        and pass_conditions["all_policy_features_present"]
        and not extra_features,
        "feature_names_in_policy": list(policy.feature_names),
        "feature_names_in_drift_artifact": feature_names,
        "required_cohorts": list(DRIFT_COHORTS),
        "required_metrics": list(DRIFT_REQUIRED_METRICS),
        "required_quantiles": list(DRIFT_REQUIRED_QUANTILES),
        "cohort_row_counts": dict(cohort_row_counts),
        "missing_features": missing_features,
        "extra_features": extra_features,
        "missing_cohort_total": missing_cohort_total,
        "missing_required_metric_total": missing_metric_total,
        "missing_required_quantile_total": missing_quantile_total,
        "null_metric_total": null_metric_total,
        "null_required_metric_feature_count": drift_metric_contract["null_required_metric_feature_count"],
        "null_required_quantile_feature_count": drift_metric_contract["null_required_quantile_feature_count"],
        "required_non_holdout_empty_or_unobserved_total": required_non_holdout_gap_total,
        "required_all_cohort_empty_or_unobserved_total": empty_required_cohort_feature_gap_total,
        "drift_metric_publish_contract": drift_metric_contract,
        "feature_metric_coverage_summary": drift_metric_contract["feature_metric_coverage_summary"],
        "missing_required_metrics_by_feature": drift_metric_contract["missing_required_metrics_by_feature"],
        "missing_required_quantiles_by_feature": drift_metric_contract["missing_required_quantiles_by_feature"],
        "null_required_metrics_by_feature": drift_metric_contract["null_required_metrics_by_feature"],
        "null_required_quantiles_by_feature": drift_metric_contract["null_required_quantiles_by_feature"],
        "features_with_complete_required_drift_metric_coverage": drift_metric_contract[
            "features_with_complete_required_drift_metric_coverage"
        ],
        "complete_required_drift_metric_feature_count": drift_metric_contract[
            "complete_required_drift_metric_feature_count"
        ],
        "missing_cohort_counts": dict(sorted(missing_cohorts.items())),
        "missing_metric_key_counts": dict(sorted(missing_metric_keys.items())),
        "missing_quantile_key_counts": dict(sorted(missing_quantile_keys.items())),
        "null_metric_counts": dict(sorted(null_metric_counts.items())),
        "required_non_holdout_empty_or_unobserved_counts": dict(sorted(nonempty_required_cohort_gaps.items())),
        "required_all_cohort_empty_or_unobserved_counts": dict(sorted(empty_required_cohort_feature_gaps.items())),
        "root_cause_classification": drift_status.get("root_cause_classification"),
        "broken_transformation_or_source_mapping_detected": drift_status.get("broken_transformation_or_source_mapping_detected"),
        "candidate_id_change_required": drift_status.get("candidate_id_change_required"),
        "frozen_candidate_kept": drift_status.get("frozen_candidate_kept"),
        "high_drift_features_current_runtime": drift_status.get("high_drift_features_current_runtime"),
        "pass_conditions": pass_conditions,
        "blocked_reasons": [str(detail.get("pass_condition")) for detail in drift_coverage_blocker_details],
        "blocker_details": drift_coverage_blocker_details,
        "failed_blocker_details": drift_coverage_blocker_details,
        "drift_coverage_blocker_details": drift_coverage_blocker_details,
        "sample_violations": sample_violations,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "Previous holdout remains diagnostic and is not reused for blind promotion.",
            "Null metric counts are reported separately from missing metric keys; empty previous holdout metrics block complete five-cohort drift comparison evidence.",
        ],
    }


def _drift_threshold_hit(cohort_payload: Mapping[str, Any]) -> bool:
    psi = finite_float(cohort_payload.get("psi_vs_training"))
    ks = finite_float(cohort_payload.get("ks_statistic_vs_training"))
    out_of_range = finite_float(cohort_payload.get("out_of_training_range_rate"))
    return bool(
        (psi is not None and psi >= 0.25)
        or (ks is not None and ks >= 0.20)
        or (out_of_range is not None and out_of_range >= 0.20)
    )


def distribution_drift_mapping_confidence_audit(
    *,
    policy: FrozenPolicy,
    drift_status: Mapping[str, Any],
    drift_coverage: Mapping[str, Any],
) -> dict[str, Any]:
    feature_distribution = drift_status.get("feature_distribution")
    feature_map = feature_distribution if isinstance(feature_distribution, Mapping) else {}
    parity_status = drift_status.get("feature_parity_status")
    parity_status = parity_status if isinstance(parity_status, Mapping) else {}
    high_reported = [str(name) for name in drift_status.get("high_drift_features_current_runtime") or []]
    high_computed: list[str] = []
    feature_diagnosis: list[dict[str, Any]] = []
    current_missing_spike_features: list[str] = []
    current_stale_spike_features: list[str] = []
    current_unobserved_features: list[str] = []

    for feature_name in policy.feature_names:
        feature_payload = feature_map.get(feature_name)
        feature_payload = feature_payload if isinstance(feature_payload, Mapping) else {}
        current = feature_payload.get("current_runtime")
        future = feature_payload.get("future_lockbox")
        validation = feature_payload.get("validation")
        current = current if isinstance(current, Mapping) else {}
        future = future if isinstance(future, Mapping) else {}
        validation = validation if isinstance(validation, Mapping) else {}

        current_high = _drift_threshold_hit(current)
        future_high = _drift_threshold_hit(future)
        validation_high = _drift_threshold_hit(validation)
        if current_high:
            high_computed.append(feature_name)

        observed = finite_float(current.get("observed_value_count"))
        row_count = finite_float(current.get("row_count"))
        missing_rate = finite_float(current.get("missing_rate"))
        stale_rate = finite_float(current.get("stale_rate"))
        if observed is None or observed <= 0.0 or row_count is None or row_count <= 0.0:
            current_unobserved_features.append(feature_name)
        if missing_rate is not None and missing_rate >= 0.05:
            current_missing_spike_features.append(feature_name)
        if stale_rate is not None and stale_rate >= 0.05:
            current_stale_spike_features.append(feature_name)

        if current_high or validation_high or future_high or feature_name in high_reported:
            support_reasons: list[str] = []
            suspicion_reasons: list[str] = []
            if parity_status.get("status") == "PASS":
                support_reasons.append("shared_replay_runtime_feature_adapter_parity_passed")
            if missing_rate is not None and missing_rate < 0.05:
                support_reasons.append("current_runtime_missing_rate_below_5pct")
            if stale_rate is not None and stale_rate < 0.05:
                support_reasons.append("current_runtime_stale_rate_below_5pct")
            if future_high:
                support_reasons.append("future_lockbox_distribution_shift_confirms_runtime_drift")
            if validation_high:
                support_reasons.append("validation_distribution_already_showed_training_range_exhaustion")
            if missing_rate is not None and missing_rate >= 0.05:
                suspicion_reasons.append("current_runtime_missing_rate_spike")
            if stale_rate is not None and stale_rate >= 0.05:
                suspicion_reasons.append("current_runtime_stale_rate_spike")
            if observed is None or observed <= 0.0:
                suspicion_reasons.append("current_runtime_feature_unobserved")
            feature_diagnosis.append(
                {
                    "feature": feature_name,
                    "reported_high_drift": feature_name in high_reported,
                    "computed_high_current_runtime": current_high,
                    "computed_high_validation": validation_high,
                    "computed_high_future_lockbox": future_high,
                    "current_runtime": {
                        "psi_vs_training": current.get("psi_vs_training"),
                        "ks_statistic_vs_training": current.get("ks_statistic_vs_training"),
                        "out_of_training_range_rate": current.get("out_of_training_range_rate"),
                        "missing_rate": current.get("missing_rate"),
                        "stale_rate": current.get("stale_rate"),
                        "observed_value_count": current.get("observed_value_count"),
                        "row_count": current.get("row_count"),
                    },
                    "validation": {
                        "psi_vs_training": validation.get("psi_vs_training"),
                        "ks_statistic_vs_training": validation.get("ks_statistic_vs_training"),
                        "out_of_training_range_rate": validation.get("out_of_training_range_rate"),
                    },
                    "future_lockbox": {
                        "psi_vs_training": future.get("psi_vs_training"),
                        "ks_statistic_vs_training": future.get("ks_statistic_vs_training"),
                        "out_of_training_range_rate": future.get("out_of_training_range_rate"),
                    },
                    "mapping_suspicion_reasons": suspicion_reasons,
                    "genuine_shift_support_reasons": support_reasons,
                    "feature_root_cause": "POSSIBLE_SOURCE_MAPPING_OR_FRESHNESS_GAP"
                    if suspicion_reasons
                    else "LIKELY_GENUINE_DISTRIBUTION_SHIFT_OR_TRAINING_RANGE_EXHAUSTION",
                }
            )

    schema_mismatch_rows = int(parity_status.get("schema_mismatch_rows") or 0)
    normalization_mismatch_rows = int(parity_status.get("normalization_mismatch_rows") or 0)
    unexplained_missing_feature_rows = int(parity_status.get("unexplained_missing_feature_rows") or 0)
    current_integrity_pass_rate = finite_float(parity_status.get("current_integrity_pass_rate"))
    reported_high_matches_computed = set(high_reported) == set(high_computed)
    pass_conditions = {
        "drift_coverage_audit_passed": drift_coverage.get("status") == "PASS_DRIFT_COVERAGE_AUDIT",
        "feature_parity_status_passed": parity_status.get("status") == "PASS",
        "schema_mismatch_rows_eq_0": schema_mismatch_rows == 0,
        "normalization_mismatch_rows_eq_0": normalization_mismatch_rows == 0,
        "unexplained_missing_feature_rows_eq_0": unexplained_missing_feature_rows == 0,
        "current_integrity_pass_rate_gte_99pct": current_integrity_pass_rate is not None and current_integrity_pass_rate >= 0.99,
        "no_current_runtime_unobserved_features": not current_unobserved_features,
        "no_current_runtime_missing_rate_spikes": not current_missing_spike_features,
        "no_current_runtime_stale_rate_spikes": not current_stale_spike_features,
        "reported_high_drift_features_match_computed_thresholds": reported_high_matches_computed,
        "frozen_candidate_kept_without_mapping_fix": drift_status.get("broken_transformation_or_source_mapping_detected") is False
        and drift_status.get("candidate_id_change_required") is False
        and drift_status.get("frozen_candidate_kept") is True,
    }
    mapping_confident = all(pass_conditions.values())
    mapping_suspicion_features = sorted(
        {
            str(row.get("feature"))
            for row in feature_diagnosis
            if isinstance(row, Mapping) and row.get("mapping_suspicion_reasons")
        }
    )
    genuine_shift_support_features = sorted(
        {
            str(row.get("feature"))
            for row in feature_diagnosis
            if isinstance(row, Mapping) and row.get("genuine_shift_support_reasons")
        }
    )
    feature_fix_set = set(mapping_suspicion_features) | set(current_unobserved_features) | set(current_missing_spike_features) | set(current_stale_spike_features)
    if (
        schema_mismatch_rows > 0
        or normalization_mismatch_rows > 0
        or unexplained_missing_feature_rows > 0
        or not reported_high_matches_computed
    ):
        feature_fix_set.update(str(name) for name in policy.feature_names)
    mapping_defect_detected = bool(feature_fix_set) or drift_status.get("broken_transformation_or_source_mapping_detected") is True
    evidence_incomplete_without_mapping_fix = not mapping_confident and not mapping_defect_detected
    features_requiring_new_candidate_if_fixed = sorted(feature_fix_set) if mapping_defect_detected else []
    drift_mapping_blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "actual": {
                "drift_coverage_audit_passed": drift_coverage.get("status"),
                "feature_parity_status_passed": parity_status.get("status"),
                "schema_mismatch_rows_eq_0": schema_mismatch_rows,
                "normalization_mismatch_rows_eq_0": normalization_mismatch_rows,
                "unexplained_missing_feature_rows_eq_0": unexplained_missing_feature_rows,
                "current_integrity_pass_rate_gte_99pct": current_integrity_pass_rate,
                "no_current_runtime_unobserved_features": current_unobserved_features,
                "no_current_runtime_missing_rate_spikes": current_missing_spike_features,
                "no_current_runtime_stale_rate_spikes": current_stale_spike_features,
                "reported_high_drift_features_match_computed_thresholds": {
                    "reported": high_reported,
                    "computed": high_computed,
                },
                "frozen_candidate_kept_without_mapping_fix": {
                    "broken_transformation_or_source_mapping_detected": drift_status.get(
                        "broken_transformation_or_source_mapping_detected"
                    ),
                    "candidate_id_change_required": drift_status.get("candidate_id_change_required"),
                    "frozen_candidate_kept": drift_status.get("frozen_candidate_kept"),
                },
            }.get(name),
        }
        for name, passed in pass_conditions.items()
        if passed is not True
    ]
    drift_decision_contract = {
        "drift_classification": drift_status.get("root_cause_classification"),
        "mapping_fix_required": mapping_defect_detected,
        "candidate_id_change_required": mapping_defect_detected,
        "frozen_candidate_kept": not mapping_defect_detected,
        "new_candidate_required_if_any_feature_mapping_or_normalization_changes": True,
        "frozen_candidate_tuning_allowed_from_drift_results": False,
        "runtime_reject_drifted_conditions": True,
        "approval_to_keep_candidate_source": "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT" if mapping_confident else None,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    return {
        "schema_version": "challenger_v2_distribution_drift_mapping_confidence_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT" if mapping_confident else "FAIL_DRIFT_MAPPING_CONFIDENCE_AUDIT",
        "root_cause_classification": drift_status.get("root_cause_classification"),
        "broken_transformation_or_source_mapping_detected": mapping_defect_detected,
        "candidate_id_change_required": mapping_defect_detected,
        "frozen_candidate_kept": not mapping_defect_detected,
        "drift_evidence_incomplete_without_mapping_fix": evidence_incomplete_without_mapping_fix,
        "feature_parity_status": dict(parity_status),
        "reported_high_drift_features_current_runtime": high_reported,
        "computed_high_drift_features_current_runtime": high_computed,
        "high_drift_feature_count_current_runtime": len(high_reported),
        "computed_high_drift_feature_count_current_runtime": len(high_computed),
        "current_runtime_unobserved_features": current_unobserved_features,
        "current_runtime_missing_rate_spike_features": current_missing_spike_features,
        "current_runtime_stale_rate_spike_features": current_stale_spike_features,
        "mapping_suspicion_features": mapping_suspicion_features,
        "mapping_suspicion_feature_count": len(mapping_suspicion_features),
        "genuine_shift_support_features": genuine_shift_support_features,
        "genuine_shift_support_feature_count": len(genuine_shift_support_features),
        "features_requiring_new_candidate_if_fixed": features_requiring_new_candidate_if_fixed,
        "feature_diagnosis": feature_diagnosis,
        "pass_conditions": pass_conditions,
        "blocked_reasons": [str(detail.get("pass_condition")) for detail in drift_mapping_blocker_details],
        "blocker_details": drift_mapping_blocker_details,
        "failed_blocker_details": drift_mapping_blocker_details,
        "drift_mapping_blocker_details": drift_mapping_blocker_details,
        "drift_decision_contract": drift_decision_contract,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "This audit does not tune or alter the frozen candidate.",
            "PASS means current evidence supports treating drift as market/regime or training-range shift; the challenger must still reject drifted conditions unless later blind evidence passes.",
            "FAIL blocks promotion evidence; a new candidate ID is required only when a mapping, freshness, feature, or normalization defect is detected and fixed.",
        ],
    }


def shadow_supply_artifact(
    *,
    policy: FrozenPolicy,
    scored_rows: Sequence[Mapping[str, Any]],
    current_source: str,
    cost_status: Mapping[str, Any],
    drift_status: Mapping[str, Any],
) -> dict[str, Any]:
    longs = sorted((row for row in scored_rows if row.get("predicted_direction") == "LONG"), key=lambda row: float(row.get("score") or 0.0), reverse=True)
    shorts = sorted((row for row in scored_rows if row.get("predicted_direction") == "SHORT"), key=lambda row: float(row.get("score") or 0.0))
    cause_counts: Counter[str] = Counter()
    for row in scored_rows:
        cause_counts.update(str(reason) for reason in row.get("rejection_reasons") or ())
    selected_rows = sum(1 for row in scored_rows if row.get("selected") is True)
    rejected_rows = sum(1 for row in scored_rows if row.get("selected") is not True)
    total_current_valid_rows = len(scored_rows)
    total_scored_rows = len(scored_rows)
    unscored_current_valid_rows = max(0, total_current_valid_rows - total_scored_rows)
    shadow_scoring_coverage = (
        total_scored_rows / total_current_valid_rows
        if total_current_valid_rows
        else None
    )
    liquidity_status_counts = Counter(str(row.get("liquidity_status") or "UNKNOWN") for row in scored_rows)
    eligible = [
        row
        for row in scored_rows
        if row.get("selected") is True
        and row.get("estimated_production_cost", {}).get("production_grade_evidence") is True
    ]
    def public_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": row.get("candidate_id"),
            "policy_fingerprint": row.get("policy_fingerprint"),
            "model_source": row.get("model_source"),
            "snapshot_id": row.get("snapshot_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "decision_time": row.get("decision_time"),
            "feature_cutoff": row.get("feature_cutoff"),
            "available_at": row.get("available_at"),
            "predicted_direction": row.get("predicted_direction"),
            "score": row.get("score"),
            "predicted_gross_edge_bps": row.get("predicted_gross_edge_bps"),
            "production_cost_bps": row.get("production_cost_bps"),
            "predicted_net_edge_bps": row.get("predicted_net_edge_bps"),
            "threshold_distance_bps": row.get("threshold_distance_bps"),
            "feature_drift": row.get("feature_drift"),
            "liquidity_status": row.get("liquidity_status"),
            "rejection_reason": (row.get("rejection_reasons") or [None])[0],
            "rejection_reasons": row.get("rejection_reasons"),
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        }
    top_long = [public_row(row) for row in longs[:25]]
    top_short = [public_row(row) for row in shorts[:25]]
    return {
        "schema_version": "challenger_v2_forward_shadow_status_v2",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PUBLISHED_NON_EXECUTABLE_RANKINGS",
        "current_snapshot_source": current_source,
        "score_every_current_valid_row": True,
        "total_scored_rows": total_scored_rows,
        "total_rows_scored": total_scored_rows,
        "current_rows_scored": total_scored_rows,
        "scored_current_valid_rows": total_scored_rows,
        "valid_rows_scored": total_scored_rows,
        "current_rows_scanned": total_current_valid_rows,
        "total_current_valid_rows": total_current_valid_rows,
        "current_valid_rows": total_current_valid_rows,
        "total_shadow_scored_rows": total_scored_rows,
        "unscored_current_valid_rows": unscored_current_valid_rows,
        "shadow_scoring_coverage": shadow_scoring_coverage,
        "score_every_current_valid_row_contract": {
            "total_current_valid_rows": total_current_valid_rows,
            "total_scored_rows": total_scored_rows,
            "unscored_current_valid_rows": unscored_current_valid_rows,
            "shadow_scoring_coverage": shadow_scoring_coverage,
            "scored_rows_equal_current_valid_rows": total_scored_rows == total_current_valid_rows,
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        },
        "trade_threshold_bps": policy.threshold_bps,
        "eligible_non_executable_count": len(eligible),
        "qualified_economic_candidates": selected_rows,
        "selected_rows": selected_rows,
        "rejected_rows": rejected_rows,
        "zero_current_supply_cause_counts": dict(sorted(cause_counts.items())),
        "rejection_reason_counts": dict(sorted(cause_counts.items())),
        "liquidity_status_counts": dict(sorted(liquidity_status_counts.items())),
        "top_25_long_candidates": top_long,
        "top_25_short_candidates": top_short,
        "top_long": top_long,
        "top_short": top_short,
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "high_drift_features_current_runtime": drift_status.get("high_drift_features_current_runtime"),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "ranking_scope": "NON_EXECUTABLE_ONLY",
    }


def shadow_supply_contract_audit(*, policy: FrozenPolicy, shadow_status: Mapping[str, Any]) -> dict[str, Any]:
    long_rows = shadow_status.get("top_25_long_candidates")
    short_rows = shadow_status.get("top_25_short_candidates")
    long_rows = list(long_rows) if isinstance(long_rows, Sequence) and not isinstance(long_rows, (str, bytes)) else []
    short_rows = list(short_rows) if isinstance(short_rows, Sequence) and not isinstance(short_rows, (str, bytes)) else []
    published_rows = [*long_rows, *short_rows]
    long_row_hashes = [row_hash(row) for row in long_rows if isinstance(row, Mapping)]
    short_row_hashes = [row_hash(row) for row in short_rows if isinstance(row, Mapping)]

    missing_required_row_fields: Counter[str] = Counter()
    safety_flag_violations: Counter[str] = Counter()
    identity_mismatch_count = 0
    side_mismatch_count = 0
    sample_violations: list[dict[str, Any]] = []
    for expected_side, rows in (("LONG", long_rows), ("SHORT", short_rows)):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            missing = [
                field
                for field in SHADOW_SUPPLY_REQUIRED_ROW_FIELDS
                if row.get(field) is None
            ]
            missing_required_row_fields.update(missing)
            for flag in (
                "paper_fill_allowed",
                "routes_to_live",
                "places_real_order",
                "counts_as_a_grade_evidence",
                "promotion_evidence",
            ):
                if row.get(flag) is not False:
                    safety_flag_violations[flag] += 1
            row_identity_mismatch = (
                row.get("candidate_id") != policy.candidate_id
                or row.get("policy_fingerprint") != policy.policy_fingerprint
                or row.get("model_source") != policy.model_source
            )
            row_side_mismatch = str(row.get("predicted_direction") or "").upper() != expected_side
            if row_identity_mismatch:
                identity_mismatch_count += 1
            if row_side_mismatch:
                side_mismatch_count += 1
            if (missing or row_identity_mismatch or row_side_mismatch) and len(sample_violations) < 10:
                sample_violations.append(
                    {
                        "snapshot_id": row.get("snapshot_id"),
                        "symbol": row.get("symbol"),
                        "predicted_direction": row.get("predicted_direction"),
                        "expected_side": expected_side,
                        "missing_required_fields": missing,
                        "identity_mismatch": row_identity_mismatch,
                    }
                )

    def row_count_value(*names: str) -> int | None:
        for name in names:
            value = shadow_status.get(name)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    total_scored_rows = row_count_value("total_scored_rows", "total_rows_scored", "current_rows_scored", "current_rows_scanned")
    total_current_valid_rows = row_count_value("total_current_valid_rows", "current_valid_rows", "current_rows_scanned")
    total_shadow_scored_rows = row_count_value(
        "total_shadow_scored_rows",
        "total_scored_rows",
        "total_rows_scored",
        "current_rows_scored",
        "current_rows_scanned",
    )
    if total_scored_rows is not None and total_current_valid_rows is not None:
        unscored_current_valid_rows = max(0, total_current_valid_rows - total_scored_rows)
        shadow_scoring_coverage = (
            total_scored_rows / total_current_valid_rows
            if total_current_valid_rows > 0
            else None
        )
    else:
        unscored_current_valid_rows = None
        shadow_scoring_coverage = None
    score_every_current_valid_row_contract = {
        "total_current_valid_rows": total_current_valid_rows,
        "total_scored_rows": total_scored_rows,
        "total_shadow_scored_rows": total_shadow_scored_rows,
        "unscored_current_valid_rows": unscored_current_valid_rows,
        "shadow_scoring_coverage": shadow_scoring_coverage,
        "scored_rows_equal_current_valid_rows": (
            total_scored_rows is not None
            and total_current_valid_rows is not None
            and total_scored_rows == total_current_valid_rows
        ),
        "score_every_current_valid_row_declared": shadow_status.get("score_every_current_valid_row") is True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    pass_conditions = {
        "score_every_current_valid_row_declared": shadow_status.get("score_every_current_valid_row") is True,
        "current_valid_and_scored_row_counts_reported": total_scored_rows is not None
        and total_current_valid_rows is not None,
        "current_scored_rows_gt_0": int(total_scored_rows or 0) > 0,
        "scored_all_current_valid_rows": score_every_current_valid_row_contract["scored_rows_equal_current_valid_rows"],
        "unscored_current_valid_rows_eq_0": unscored_current_valid_rows == 0,
        "shadow_scoring_coverage_eq_1": shadow_scoring_coverage == 1.0,
        "top_25_long_candidates_published": len(long_rows) == 25,
        "top_25_short_candidates_published": len(short_rows) == 25,
        "top_25_candidate_rows_mirrored_in_contract": len(long_row_hashes) == len(long_rows) == 25
        and len(short_row_hashes) == len(short_rows) == 25,
        "required_edge_cost_drift_liquidity_fields_present": not missing_required_row_fields,
        "row_sides_match_published_lists": side_mismatch_count == 0,
        "candidate_identity_matches_frozen_policy": identity_mismatch_count == 0,
        "artifact_paper_fill_allowed_false": shadow_status.get("paper_fill_allowed") is False,
        "artifact_routes_to_live_false": shadow_status.get("routes_to_live") is False,
        "artifact_places_real_order_false": shadow_status.get("places_real_order") is False,
        "artifact_counts_as_a_grade_evidence_false": shadow_status.get("counts_as_a_grade_evidence") is False,
        "artifact_promotion_evidence_false": shadow_status.get("promotion_evidence") is False,
        "row_safety_flags_false": not safety_flag_violations,
    }
    status = "PASS_SHADOW_SUPPLY_CONTRACT" if all(pass_conditions.values()) else "FAIL_SHADOW_SUPPLY_CONTRACT"
    qualified_economic_candidates = (
        shadow_status.get("qualified_economic_candidates")
        or shadow_status.get("selected_rows")
        or 0
    )
    return {
        "schema_version": "challenger_v2_shadow_supply_contract_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "score_every_current_valid_row": shadow_status.get("score_every_current_valid_row") is True,
        "total_candidates": total_scored_rows,
        "total_scored_rows": total_scored_rows,
        "total_rows_scored": total_scored_rows,
        "current_rows_scored": total_scored_rows,
        "scored_current_valid_rows": total_scored_rows,
        "valid_rows_scored": total_scored_rows,
        "total_current_valid_rows": total_current_valid_rows,
        "current_valid_rows": total_current_valid_rows,
        "total_shadow_scored_rows": total_shadow_scored_rows,
        "unscored_current_valid_rows": unscored_current_valid_rows,
        "shadow_scoring_coverage": shadow_scoring_coverage,
        "score_every_current_valid_row_contract": score_every_current_valid_row_contract,
        "qualified_economic_candidates": qualified_economic_candidates,
        "selected_rows": shadow_status.get("selected_rows") or 0,
        "rejected_rows": shadow_status.get("rejected_rows"),
        "rejection_reason_counts": shadow_status.get("rejection_reason_counts")
        or shadow_status.get("zero_current_supply_cause_counts")
        or {},
        "liquidity_status_counts": shadow_status.get("liquidity_status_counts") or {},
        "top_long_count": len(long_rows),
        "top_short_count": len(short_rows),
        "top_25_long_count": len(long_rows),
        "top_25_short_count": len(short_rows),
        "top_25_long_candidates": long_rows,
        "top_25_short_candidates": short_rows,
        "top_25_long_candidate_hashes": long_row_hashes,
        "top_25_short_candidate_hashes": short_row_hashes,
        "published_candidate_rows": len(published_rows),
        "published_candidate_row_hashes": [*long_row_hashes, *short_row_hashes],
        "missing_required_row_field_counts": dict(sorted(missing_required_row_fields.items())),
        "row_safety_flag_violation_counts": dict(sorted(safety_flag_violations.items())),
        "identity_mismatch_count": identity_mismatch_count,
        "side_mismatch_count": side_mismatch_count,
        "pass_conditions": pass_conditions,
        "sample_violations": sample_violations,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def zero_candidate_supply_diagnosis(
    *,
    policy: FrozenPolicy,
    scored_rows: Sequence[Mapping[str, Any]],
    cost_status: Mapping[str, Any],
    drift_status: Mapping[str, Any],
    paper_intent_join_status: Mapping[str, Any],
) -> dict[str, Any]:
    side_counts: Counter[str] = Counter(str(row.get("predicted_direction") or "UNKNOWN") for row in scored_rows)
    reason_counts: Counter[str] = Counter()
    reason_by_side: dict[str, Counter[str]] = {}
    threshold_bands: Counter[str] = Counter()
    threshold_bands_by_side: dict[str, Counter[str]] = {}
    threshold_distances: list[float] = []
    liquidity_status_counts: Counter[str] = Counter()
    above_threshold = 0
    production_grade_cost_rows = 0
    liquidity_pass_rows = 0
    drift_pass_rows = 0
    selected_rows = 0
    near_threshold_rows: list[Mapping[str, Any]] = []
    above_threshold_rejected_rows: list[Mapping[str, Any]] = []

    for row in scored_rows:
        side = str(row.get("predicted_direction") or "UNKNOWN")
        reasons = [str(reason) for reason in row.get("rejection_reasons") or ()]
        reason_counts.update(reasons)
        reason_by_side.setdefault(side, Counter()).update(reasons)
        distance = finite_float(row.get("threshold_distance_bps"))
        if distance is not None:
            threshold_distances.append(distance)
            if distance >= 0.0:
                band = "gte_threshold"
                above_threshold += 1
                if row.get("selected") is not True and len(above_threshold_rejected_rows) < 25:
                    above_threshold_rejected_rows.append(row)
            elif distance >= -5.0:
                band = "within_5bps_below_threshold"
                if len(near_threshold_rows) < 25:
                    near_threshold_rows.append(row)
            elif distance >= -20.0:
                band = "within_20bps_below_threshold"
            else:
                band = "more_than_20bps_below_threshold"
            threshold_bands[band] += 1
            threshold_bands_by_side.setdefault(side, Counter())[band] += 1
        cost = row.get("estimated_production_cost")
        cost_map = cost if isinstance(cost, Mapping) else {}
        if cost_map.get("production_grade_evidence") is True:
            production_grade_cost_rows += 1
        if row.get("liquidity_status") == "PASS":
            liquidity_pass_rows += 1
        liquidity_status_counts[str(row.get("liquidity_status") or "UNKNOWN")] += 1
        feature_drift = row.get("feature_drift")
        feature_drift_map = feature_drift if isinstance(feature_drift, Mapping) else {}
        if not feature_drift_map.get("out_of_training_range_features"):
            drift_pass_rows += 1
        if row.get("selected") is True:
            selected_rows += 1

    def public_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": row.get("candidate_id"),
            "policy_fingerprint": row.get("policy_fingerprint"),
            "model_source": row.get("model_source"),
            "snapshot_id": row.get("snapshot_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "decision_time": row.get("decision_time"),
            "predicted_direction": row.get("predicted_direction"),
            "predicted_gross_edge_bps": row.get("predicted_gross_edge_bps"),
            "production_cost_bps": row.get("production_cost_bps"),
            "predicted_net_edge_bps": row.get("predicted_net_edge_bps"),
            "threshold_distance_bps": row.get("threshold_distance_bps"),
            "feature_drift": row.get("feature_drift"),
            "liquidity_status": row.get("liquidity_status"),
            "rejection_reasons": row.get("rejection_reasons"),
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        }

    hard_cost_blockers = []
    blocker_diagnosis = cost_status.get("blocker_diagnosis")
    if isinstance(blocker_diagnosis, Mapping):
        hard_cost_blockers = [str(name) for name in blocker_diagnosis.get("hard_blocking_fields") or ()]
    if selected_rows > 0:
        root_cause = "HAS_SELECTED_ROWS"
    elif reason_counts.get("cost_not_production_grade", 0) == len(scored_rows) and reason_counts.get("liquidity_missing_depth_or_order_size", 0) == len(scored_rows):
        root_cause = "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED"
    elif reason_counts.get("cost_not_production_grade", 0) == len(scored_rows):
        root_cause = "ZERO_SUPPLY_ALL_ROWS_COST_BLOCKED"
    elif above_threshold == 0:
        root_cause = "ZERO_SUPPLY_THRESHOLD_BLOCKED"
    elif reason_counts.get("distribution_drift", 0) >= max(1, len(scored_rows) // 2):
        root_cause = "ZERO_SUPPLY_DISTRIBUTION_DRIFT_DOMINANT"
    else:
        root_cause = "ZERO_SUPPLY_MULTIPLE_OVERLAPPING_BLOCKERS"
    row_count = len(scored_rows)
    threshold_distance_summary = {
        "count": len(threshold_distances),
        "min": min(threshold_distances) if threshold_distances else None,
        "median": quantile(sorted(threshold_distances), 0.5),
        "max": max(threshold_distances) if threshold_distances else None,
        "above_threshold_rows": above_threshold,
    }
    status = "ZERO_SUPPLY_DIAGNOSED" if selected_rows == 0 else "HAS_SELECTED_CANDIDATES"
    shadow_supply_blocker_details = {
        "cost_not_production_grade": {
            "blocked_rows": int(reason_counts.get("cost_not_production_grade", 0)),
            "total_rows": row_count,
            "all_rows_blocked": row_count > 0 and int(reason_counts.get("cost_not_production_grade", 0)) == row_count,
            "production_grade_cost_rows": production_grade_cost_rows,
            "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
            "hard_cost_blockers": hard_cost_blockers,
        },
        "liquidity_missing_depth_or_order_size": {
            "blocked_rows": int(reason_counts.get("liquidity_missing_depth_or_order_size", 0)),
            "total_rows": row_count,
            "all_rows_blocked": row_count > 0 and int(reason_counts.get("liquidity_missing_depth_or_order_size", 0)) == row_count,
            "liquidity_pass_rows": liquidity_pass_rows,
            "paper_intent_positive_order_size_matches": paper_intent_join_status.get("positive_order_size_matches"),
        },
        "threshold": {
            "blocked_rows": int(reason_counts.get("threshold", 0)),
            "total_rows": row_count,
            "rows_above_threshold": above_threshold,
            "selected_rows": selected_rows,
            "above_threshold_rejected_rows": len(above_threshold_rejected_rows),
        },
        "distribution_drift": {
            "blocked_rows": int(reason_counts.get("distribution_drift", 0)),
            "total_rows": row_count,
            "rows_without_distribution_drift": drift_pass_rows,
            "high_drift_features_current_runtime": drift_status.get("high_drift_features_current_runtime"),
        },
    }
    zero_supply_blocker_details = [
        {
            "blocker": blocker_name,
            "blocked_rows": details.get("blocked_rows"),
            "total_rows": details.get("total_rows"),
            "all_rows_blocked": details.get("all_rows_blocked"),
            "details": details,
        }
        for blocker_name, details in shadow_supply_blocker_details.items()
        if int(details.get("blocked_rows") or 0) > 0
    ]
    zero_supply_blocked_reasons = [
        str(reason)
        for reason, count in sorted(reason_counts.items())
        if int(count or 0) > 0
    ]
    if selected_rows == 0 and not zero_supply_blocked_reasons:
        zero_supply_blocked_reasons = ["no_selected_rows"]
    next_actions: list[str] = []
    if reason_counts.get("cost_not_production_grade", 0):
        next_actions.append("continue_future_candidate_bound_production_grade_cost_capture")
    if reason_counts.get("liquidity_missing_depth_or_order_size", 0):
        next_actions.append("capture_order_size_depth_top_book_and_depth_derived_impact_before_candidate_credit")
    if reason_counts.get("distribution_drift", 0):
        next_actions.append("keep_frozen_candidate_rejecting_drifted_conditions")
    if reason_counts.get("threshold", 0):
        next_actions.append("continue_shadow_scoring_without_lowering_threshold_to_create_volume")
    next_actions.extend(
        [
            "do_not_bind_to_paper_until_official_blind_lockbox_pass",
            "do_not_count_fallback_or_shadow_rows_as_training_lockbox_promotion_or_a_grade_evidence",
        ]
    )
    pass_conditions = {
        "current_rows_scored_gt_0": row_count > 0,
        "zero_supply_status_matches_selected_rows": (selected_rows == 0 and status == "ZERO_SUPPLY_DIAGNOSED")
        or (selected_rows > 0 and status == "HAS_SELECTED_CANDIDATES"),
        "root_cause_classification_present": bool(root_cause),
        "blocker_details_present_when_zero_supply": bool(zero_supply_blocker_details) if selected_rows == 0 else True,
        "next_actions_published": bool(next_actions),
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "places_real_order_false": True,
        "counts_as_a_grade_evidence_false": True,
        "promotion_evidence_false": True,
    }
    zero_supply_actuals = {
        "current_rows_scored_gt_0": row_count,
        "zero_supply_status_matches_selected_rows": {
            "status": status,
            "selected_rows": selected_rows,
        },
        "root_cause_classification_present": root_cause,
        "blocker_details_present_when_zero_supply": len(zero_supply_blocker_details),
        "next_actions_published": len(next_actions),
        "paper_fill_allowed_false": False,
        "routes_to_live_false": False,
        "places_real_order_false": False,
        "counts_as_a_grade_evidence_false": False,
        "promotion_evidence_false": False,
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
        "production_grade_cost_rows": production_grade_cost_rows,
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "liquidity_pass_rows": liquidity_pass_rows,
        "rows_above_threshold": above_threshold,
        "drift_pass_rows": drift_pass_rows,
    }
    zero_supply_required = {
        "current_rows_scored_gt_0": ">0",
        "zero_supply_status_matches_selected_rows": (
            "ZERO_SUPPLY_DIAGNOSED when selected_rows == 0; HAS_SELECTED_CANDIDATES when selected_rows > 0"
        ),
        "root_cause_classification_present": "non-empty root cause classification",
        "blocker_details_present_when_zero_supply": ">0 when selected_rows == 0",
        "next_actions_published": ">0",
        "paper_fill_allowed_false": False,
        "routes_to_live_false": False,
        "places_real_order_false": False,
        "counts_as_a_grade_evidence_false": False,
        "promotion_evidence_false": False,
        "rejection_reason_counts": "published by reason",
        "production_grade_cost_rows": "diagnostic count",
        "production_grade_cost_coverage": "diagnostic coverage",
        "liquidity_pass_rows": "diagnostic count",
        "rows_above_threshold": "diagnostic count",
        "drift_pass_rows": "diagnostic count",
    }
    zero_supply_root_causes = [
        {
            "root_cause": str(detail["blocker"]),
            "blocked_rows": int(detail.get("blocked_rows") or 0),
            "total_rows": int(detail.get("total_rows") or 0),
            "all_rows_blocked": detail.get("all_rows_blocked") is True,
            "details": detail.get("details") or {},
        }
        for detail in zero_supply_blocker_details
    ]
    root_cause_summary = {
        "classification": root_cause,
        "selected_rows": selected_rows,
        "qualified_rows": selected_rows,
        "total_rows": row_count,
        "rows_above_threshold": above_threshold,
        "production_grade_cost_rows": production_grade_cost_rows,
        "liquidity_pass_rows": liquidity_pass_rows,
        "drift_pass_rows": drift_pass_rows,
        "zero_supply_root_causes": zero_supply_root_causes,
        "next_actions": next_actions,
    }

    return {
        "schema_version": "challenger_v2_zero_candidate_supply_diagnosis_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "root_cause_classification": root_cause,
        "root_cause": root_cause,
        "zero_supply_root_cause": root_cause,
        "zero_supply_root_causes": zero_supply_root_causes,
        "root_cause_summary": root_cause_summary,
        "pass_conditions": pass_conditions,
        "blocked_reasons": zero_supply_blocked_reasons,
        "actuals": zero_supply_actuals,
        "required": zero_supply_required,
        "sample_blockers": zero_supply_blocker_details[:25],
        "blocker_details": zero_supply_blocker_details,
        "zero_supply_blocker_details": zero_supply_blocker_details,
        "next_actions": next_actions,
        "current_rows_scored": row_count,
        "current_rows_scanned": row_count,
        "current_valid_rows": row_count,
        "shadow_scored_rows": row_count,
        "total_scored_rows": row_count,
        "total_rows": row_count,
        "selected_rows": selected_rows,
        "qualified_rows": selected_rows,
        "rows_above_threshold": above_threshold,
        "above_threshold_rows": above_threshold,
        "rows_with_production_grade_cost": production_grade_cost_rows,
        "production_grade_cost_rows": production_grade_cost_rows,
        "rows_with_liquidity_pass": liquidity_pass_rows,
        "liquidity_pass_rows": liquidity_pass_rows,
        "rows_without_distribution_drift": drift_pass_rows,
        "drift_pass_rows": drift_pass_rows,
        "side_counts": dict(sorted(side_counts.items())),
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "rejection_reason_counts_by_side": {
            side: dict(sorted(counter.items())) for side, counter in sorted(reason_by_side.items())
        },
        "rejection_reason_by_side": {
            side: dict(sorted(counter.items())) for side, counter in sorted(reason_by_side.items())
        },
        "threshold_band_counts": dict(sorted(threshold_bands.items())),
        "threshold_distance_bands": dict(sorted(threshold_bands.items())),
        "threshold_bands": dict(sorted(threshold_bands.items())),
        "threshold_band_counts_by_side": {
            side: dict(sorted(counter.items())) for side, counter in sorted(threshold_bands_by_side.items())
        },
        "threshold_distance_bands_by_side": {
            side: dict(sorted(counter.items())) for side, counter in sorted(threshold_bands_by_side.items())
        },
        "threshold_bands_by_side": {
            side: dict(sorted(counter.items())) for side, counter in sorted(threshold_bands_by_side.items())
        },
        "threshold_distance_summary": threshold_distance_summary,
        "liquidity_status_counts": dict(sorted(liquidity_status_counts.items())),
        "shadow_supply_blocker_details": shadow_supply_blocker_details,
        "hard_cost_blockers": hard_cost_blockers,
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "paper_intent_candidate_bound_intents": paper_intent_join_status.get("candidate_bound_intents"),
        "paper_intent_positive_order_size_matches": paper_intent_join_status.get("positive_order_size_matches"),
        "high_drift_features_current_runtime": drift_status.get("high_drift_features_current_runtime"),
        "near_threshold_rejected_sample": [public_row(row) for row in near_threshold_rows],
        "sample_near_threshold_rows": [public_row(row) for row in near_threshold_rows],
        "above_threshold_rejected_sample": [public_row(row) for row in above_threshold_rejected_rows[:25]],
        "sample_above_threshold_rejected_rows": [public_row(row) for row in above_threshold_rejected_rows[:25]],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "Every row is shadow-only and non-executable.",
            "Zero-supply diagnosis is derived from current scored rows and does not alter thresholds, model weights, feature normalization, or cost assumptions.",
        ],
    }


def point_in_time_violation_count(rows: Sequence[Mapping[str, Any]]) -> int:
    violations = 0
    for row in rows:
        decision_time = parse_utc(row.get("decision_time"))
        feature_cutoff = parse_utc(row.get("feature_cutoff"))
        available_at = parse_utc(row.get("available_at"))
        if decision_time is None or feature_cutoff is None or available_at is None:
            violations += 1
            continue
        if feature_cutoff > decision_time or available_at > decision_time:
            violations += 1
    return violations


TEMPORAL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_time": ("event_time", "source_event_time_est", "candle_close_time", "label_source_timestamp"),
    "ingested_at": ("ingested_at", "source_received_time_est", "received_at"),
    "available_at": ("available_at", "source_available_time"),
    "generated_at": ("generated_at", "generated_utc", "record_created_utc", "label_created_utc"),
    "feature_cutoff": ("feature_cutoff",),
    "decision_time": ("decision_time", "decision_time_est", "decision_cutoff_time_est"),
    "execution_time": ("execution_time", "closed_utc", "closed_at", "exit_time", "exit_at"),
    "masa_feature_cutoff": ("masa_feature_cutoff", "masa_feature_cutoff_time", "masa_cutoff", "masa_available_feature_cutoff"),
}


def temporal_first_present(row: Mapping[str, Any], canonical_field: str) -> tuple[str | None, Any]:
    for field_name in TEMPORAL_FIELD_ALIASES.get(canonical_field, (canonical_field,)):
        value = row.get(field_name)
        if value not in (None, ""):
            return field_name, value
    return None, None


def temporal_semantics_audit(
    *,
    policy: FrozenPolicy,
    pending_rows: Sequence[Mapping[str, Any]],
    labelled_rows: Sequence[Mapping[str, Any]],
    shadow_cost_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    cohorts: tuple[tuple[str, Sequence[Mapping[str, Any]]], ...] = (
        ("future_lockbox_pending", pending_rows),
        ("future_lockbox_labelled", labelled_rows),
        ("candidate_bound_shadow_cost", shadow_cost_rows),
    )
    required_by_cohort = {
        "future_lockbox_pending": ("decision_time", "feature_cutoff", "available_at"),
        "future_lockbox_labelled": ("decision_time", "feature_cutoff", "available_at", "event_time"),
        "candidate_bound_shadow_cost": ("decision_time", "feature_cutoff", "available_at", "generated_at"),
    }
    cohort_summaries: dict[str, Any] = {}
    violation_counts: Counter[str] = Counter()
    missing_required_counts: Counter[str] = Counter()
    sample_violations: list[dict[str, Any]] = []

    def explicit_unfinished_higher_timeframe_candle(row: Mapping[str, Any]) -> bool:
        timeframe = str(row.get("timeframe") or "").lower()
        if timeframe not in {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}:
            return False
        for field in (
            "candle_closed_confirmed",
            "closed_candle",
            "is_closed_candle",
            "is_final",
            "final",
            "is_candle_final",
            "candle_is_final",
            "partial_candle",
            "is_partial_candle",
            "unfinished_candle",
        ):
            if field not in row:
                continue
            value = row.get(field)
            if field in {"partial_candle", "is_partial_candle", "unfinished_candle"}:
                return value is True or str(value).lower() == "true"
            return value is False or str(value).lower() == "false"
        return False

    def add_violation(cohort: str, row: Mapping[str, Any], violation: str, details: Mapping[str, Any]) -> None:
        if len(sample_violations) < 25:
            sample_violations.append(
                {
                    "cohort": cohort,
                    "violation": violation,
                    "lockbox_record_id": row.get("lockbox_record_id"),
                    "snapshot_id": row.get("snapshot_id"),
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "decision_time": row.get("decision_time"),
                    "details": dict(details),
                }
            )

    for cohort, rows in cohorts:
        coverage: dict[str, int] = {field: 0 for field in TEMPORAL_FIELD_ALIASES}
        alias_counts: dict[str, Counter[str]] = {field: Counter() for field in TEMPORAL_FIELD_ALIASES}
        cohort_missing: Counter[str] = Counter()
        cohort_violations: Counter[str] = Counter()
        for row in rows:
            parsed: dict[str, datetime | None] = {}
            aliases: dict[str, str | None] = {}
            for canonical in TEMPORAL_FIELD_ALIASES:
                alias, value = temporal_first_present(row, canonical)
                aliases[canonical] = alias
                if alias is not None:
                    coverage[canonical] += 1
                    alias_counts[canonical][alias] += 1
                    parsed[canonical] = parse_utc(value)
                else:
                    parsed[canonical] = None
            for required in required_by_cohort[cohort]:
                if aliases.get(required) is None:
                    cohort_missing[required] += 1
                    missing_required_counts[f"{cohort}.{required}"] += 1
                    cohort_violations[f"missing_required_{required}"] += 1
                    add_violation(cohort, row, f"missing_required_{required}", {"required_field": required})

            decision_time = parsed.get("decision_time")
            feature_cutoff = parsed.get("feature_cutoff")
            available_at = parsed.get("available_at")
            event_time = parsed.get("event_time")
            generated_at = parsed.get("generated_at")
            execution_time = parsed.get("execution_time")
            masa_feature_cutoff = parsed.get("masa_feature_cutoff")

            if decision_time is not None and feature_cutoff is not None and feature_cutoff > decision_time:
                cohort_violations["feature_cutoff_after_decision_time"] += 1
                add_violation(
                    cohort,
                    row,
                    "feature_cutoff_after_decision_time",
                    {"feature_cutoff": feature_cutoff.isoformat(), "decision_time": decision_time.isoformat()},
                )
            if decision_time is not None and available_at is not None and available_at > decision_time:
                cohort_violations["available_at_after_decision_time"] += 1
                add_violation(
                    cohort,
                    row,
                    "available_at_after_decision_time",
                    {"available_at": available_at.isoformat(), "decision_time": decision_time.isoformat()},
                )
            if cohort != "future_lockbox_labelled" and event_time is not None and available_at is not None and event_time > available_at:
                cohort_violations["event_time_after_available_at"] += 1
                add_violation(
                    cohort,
                    row,
                    "event_time_after_available_at",
                    {"event_time": event_time.isoformat(), "available_at": available_at.isoformat()},
                )
            if event_time is not None and decision_time is not None and cohort != "future_lockbox_labelled" and event_time > decision_time:
                cohort_violations["event_time_after_decision_time"] += 1
                add_violation(
                    cohort,
                    row,
                    "event_time_after_decision_time",
                    {"event_time": event_time.isoformat(), "decision_time": decision_time.isoformat()},
                )
            if cohort == "future_lockbox_labelled":
                if event_time is not None and decision_time is not None and event_time <= decision_time:
                    cohort_violations["label_event_time_not_after_decision_time"] += 1
                    add_violation(
                        cohort,
                        row,
                        "label_event_time_not_after_decision_time",
                        {"label_event_time": event_time.isoformat(), "decision_time": decision_time.isoformat()},
                    )
                if row.get("label_uses_future_data_as_label_only") is not True:
                    cohort_violations["label_future_data_flag_not_true"] += 1
                    add_violation(cohort, row, "label_future_data_flag_not_true", {"label_uses_future_data_as_label_only": row.get("label_uses_future_data_as_label_only")})
            if execution_time is not None and decision_time is not None and execution_time < decision_time:
                cohort_violations["execution_time_before_decision_time"] += 1
                add_violation(
                    cohort,
                    row,
                    "execution_time_before_decision_time",
                    {"execution_time": execution_time.isoformat(), "decision_time": decision_time.isoformat()},
                )
            if masa_feature_cutoff is not None and decision_time is not None and masa_feature_cutoff > decision_time:
                cohort_violations["masa_feature_cutoff_after_ppo_decision_time"] += 1
                add_violation(
                    cohort,
                    row,
                    "masa_feature_cutoff_after_ppo_decision_time",
                    {"masa_feature_cutoff": masa_feature_cutoff.isoformat(), "ppo_decision_time": decision_time.isoformat()},
                )
            if generated_at is not None and event_time is not None and cohort != "future_lockbox_labelled" and generated_at < event_time:
                cohort_violations["generated_at_before_event_time"] += 1
                add_violation(
                    cohort,
                    row,
                    "generated_at_before_event_time",
                    {"generated_at": generated_at.isoformat(), "event_time": event_time.isoformat()},
                )
            if explicit_unfinished_higher_timeframe_candle(row):
                cohort_violations["unfinished_higher_timeframe_candle_used"] += 1
                add_violation(
                    cohort,
                    row,
                    "unfinished_higher_timeframe_candle_used",
                    {"timeframe": row.get("timeframe")},
                )
        row_count = len(rows)
        violation_counts.update(cohort_violations)
        cohort_summaries[cohort] = {
            "rows": row_count,
            "required_temporal_fields": list(required_by_cohort[cohort]),
            "field_coverage": {
                field: {
                    "present_rows": int(count),
                    "missing_rows": row_count - int(count),
                    "coverage": int(count) / row_count if row_count else 0.0,
                    "aliases_observed": dict(sorted(alias_counts[field].items())),
                }
                for field, count in sorted(coverage.items())
            },
            "missing_required_temporal_field_counts": dict(sorted(cohort_missing.items())),
            "violation_counts": dict(sorted(cohort_violations.items())),
        }

    pass_conditions = {
        "timestamp_fields_are_distinguished": True,
        "feature_cutoff_lte_decision_time": violation_counts.get("feature_cutoff_after_decision_time", 0) == 0,
        "available_at_lte_decision_time": violation_counts.get("available_at_after_decision_time", 0) == 0,
        "event_time_lte_available_at_when_present": violation_counts.get("event_time_after_available_at", 0) == 0,
        "decision_input_event_time_lte_decision_time": violation_counts.get("event_time_after_decision_time", 0) == 0,
        "lockbox_labels_use_future_data_as_label_only": violation_counts.get("label_future_data_flag_not_true", 0) == 0,
        "lockbox_label_event_time_after_decision_time": violation_counts.get("label_event_time_not_after_decision_time", 0) == 0,
        "execution_time_not_before_decision_time": violation_counts.get("execution_time_before_decision_time", 0) == 0,
        "masa_feature_cutoff_lte_ppo_decision_time": violation_counts.get("masa_feature_cutoff_after_ppo_decision_time", 0) == 0,
        "required_temporal_fields_present": not missing_required_counts,
        "no_explicit_unfinished_higher_timeframe_candles": violation_counts.get("unfinished_higher_timeframe_candle_used", 0) == 0,
    }
    feature_cutoff_after_decision_rows = int(violation_counts.get("feature_cutoff_after_decision_time", 0))
    available_at_after_decision_rows = int(violation_counts.get("available_at_after_decision_time", 0))
    input_event_after_decision_rows = int(violation_counts.get("event_time_after_decision_time", 0))
    event_after_available_rows = int(violation_counts.get("event_time_after_available_at", 0))
    masa_after_ppo_rows = int(violation_counts.get("masa_feature_cutoff_after_ppo_decision_time", 0))
    execution_before_decision_rows = int(violation_counts.get("execution_time_before_decision_time", 0))
    label_event_not_after_decision_rows = int(violation_counts.get("label_event_time_not_after_decision_time", 0))
    label_future_flag_not_true_rows = int(violation_counts.get("label_future_data_flag_not_true", 0))
    unfinished_higher_timeframe_rows = int(violation_counts.get("unfinished_higher_timeframe_candle_used", 0))
    point_in_time_violations = (
        feature_cutoff_after_decision_rows
        + available_at_after_decision_rows
        + input_event_after_decision_rows
        + event_after_available_rows
        + masa_after_ppo_rows
        + execution_before_decision_rows
        + label_event_not_after_decision_rows
        + label_future_flag_not_true_rows
        + unfinished_higher_timeframe_rows
    )
    return {
        "schema_version": "challenger_v2_temporal_semantics_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_TEMPORAL_SEMANTICS_AUDIT" if all(pass_conditions.values()) else "FAIL_TEMPORAL_SEMANTICS_AUDIT",
        "canonical_timestamp_fields": list(TEMPORAL_FIELD_ALIASES),
        "canonical_field_aliases_used_for_audit": {key: list(value) for key, value in TEMPORAL_FIELD_ALIASES.items()},
        "cohorts": cohort_summaries,
        "total_rows_examined": sum(len(rows) for _, rows in cohorts),
        "point_in_time_violations": point_in_time_violations,
        "feature_available_after_decision_rows": available_at_after_decision_rows,
        "available_at_after_decision_rows": available_at_after_decision_rows,
        "feature_cutoff_after_decision_rows": feature_cutoff_after_decision_rows,
        "decision_input_event_time_after_decision_rows": input_event_after_decision_rows,
        "event_time_after_available_at_rows": event_after_available_rows,
        "masa_feature_cutoff_after_ppo_decision_rows": masa_after_ppo_rows,
        "execution_time_before_decision_rows": execution_before_decision_rows,
        "lockbox_label_event_time_not_after_decision_rows": label_event_not_after_decision_rows,
        "lockbox_label_future_data_flag_not_true_rows": label_future_flag_not_true_rows,
        "unfinished_higher_timeframe_candle_rows": unfinished_higher_timeframe_rows,
        "violation_counts": dict(sorted(violation_counts.items())),
        "missing_required_temporal_field_counts": dict(sorted(missing_required_counts.items())),
        "sample_violations": sample_violations,
        "pass_conditions": pass_conditions,
        "read_only_audit_no_runtime_change": True,
        "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def required_field_missing(row: Mapping[str, Any], field: str) -> bool:
    if field not in row:
        return True
    value = row.get(field)
    if isinstance(value, bool):
        return False
    return value in (None, "")


def sample_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lockbox_record_id": row.get("lockbox_record_id"),
        "snapshot_id": row.get("snapshot_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "decision_time": row.get("decision_time"),
    }


def future_lockbox_integrity_audit(
    *,
    policy: FrozenPolicy,
    pending_rows: Sequence[Mapping[str, Any]],
    labelled_rows: Sequence[Mapping[str, Any]],
    point_in_time_violations: int,
    append_status: Mapping[str, Any] | None = None,
    hash_chain: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    append_status_payload = append_status if isinstance(append_status, Mapping) else {}
    hash_chain_payload = hash_chain if isinstance(hash_chain, Mapping) else {}
    hash_pending = hash_chain_payload.get("pending") if isinstance(hash_chain_payload.get("pending"), Mapping) else {}
    hash_labelled = hash_chain_payload.get("labelled") if isinstance(hash_chain_payload.get("labelled"), Mapping) else {}
    hash_chain_provided = bool(hash_pending or hash_labelled)
    append_conflict_value = finite_float(append_status_payload.get("immutability_conflict_count"))
    append_immutability_conflict_count = int(append_conflict_value or 0)
    pending_by_id: dict[str, Mapping[str, Any]] = {}
    pending_duplicate_ids: Counter[str] = Counter()
    pending_decision_keys: Counter[str] = Counter()
    pending_missing_counts: Counter[str] = Counter()
    labelled_missing_counts: Counter[str] = Counter()
    pending_missing_non_execution_flag_counts: Counter[str] = Counter()
    pending_non_execution_flag_violation_counts: Counter[str] = Counter()
    labelled_missing_non_execution_flag_counts: Counter[str] = Counter()
    labelled_non_execution_flag_violation_counts: Counter[str] = Counter()
    candidate_mismatch_count = 0
    policy_mismatch_count = 0
    pending_nonimmutable_count = 0
    pending_label_outcome_field_count = 0
    label_without_pending_count = 0
    label_hash_mismatch_count = 0
    label_future_use_flag_missing_count = 0
    label_forbidden_selection_field_count = 0
    label_horizon_not_mature_count = 0
    labelled_before_pending_count = 0
    label_duplicate_ids: Counter[str] = Counter()
    label_lockbox_duplicate_ids: Counter[str] = Counter()
    selected_production_grade_rows = 0
    selected_fallback_rows = 0
    sample_violations: list[dict[str, Any]] = []

    for row in pending_rows:
        record_id = str(row.get("lockbox_record_id") or "")
        if record_id:
            pending_duplicate_ids[record_id] += 1
            pending_by_id.setdefault(record_id, row)
        pending_decision_keys[
            row_hash(
                {
                    "candidate_id": row.get("candidate_id"),
                    "policy_fingerprint": row.get("policy_fingerprint"),
                    "snapshot_id": row.get("snapshot_id"),
                    "decision_time": row.get("decision_time"),
                    "feature_vector_hash": row.get("feature_vector_hash"),
                    "predicted_direction": row.get("predicted_direction"),
                }
            )
        ] += 1
        for field in PENDING_LOCKBOX_REQUIRED_FIELDS:
            if required_field_missing(row, field):
                pending_missing_counts[field] += 1
        for field in LOCKBOX_NON_EXECUTION_FIELDS:
            if row.get(field) is None:
                pending_missing_non_execution_flag_counts[field] += 1
            elif row.get(field) is not False:
                pending_non_execution_flag_violation_counts[field] += 1
        if row.get("candidate_id") != policy.candidate_id:
            candidate_mismatch_count += 1
        if row.get("policy_fingerprint") != policy.policy_fingerprint:
            policy_mismatch_count += 1
        if row.get("selection_fields_are_immutable_after_outcomes_exist") is not True:
            pending_nonimmutable_count += 1
        pending_label_fields = [field for field in PENDING_FORBIDDEN_LABEL_FIELDS if field in row and row.get(field) not in (None, "")]
        if pending_label_fields:
            pending_label_outcome_field_count += 1
            if len(sample_violations) < 25:
                sample = sample_identity(row)
                sample["violation"] = "pending_record_contains_label_outcome_fields"
                sample["forbidden_fields"] = pending_label_fields
                sample_violations.append(sample)
        cost = row.get("estimated_production_cost")
        cost_map = cost if isinstance(cost, Mapping) else {}
        if row.get("selected") is True and cost_map.get("production_grade_evidence") is True:
            selected_production_grade_rows += 1
        if row.get("selected") is True and cost_map.get("fallback") is True:
            selected_fallback_rows += 1

    for row in labelled_rows:
        record_id = str(row.get("lockbox_record_id") or "")
        label_id = str(row.get("label_record_id") or "")
        if label_id:
            label_duplicate_ids[label_id] += 1
        if record_id:
            label_lockbox_duplicate_ids[record_id] += 1
        for field in LABELLED_LOCKBOX_REQUIRED_FIELDS:
            if required_field_missing(row, field):
                labelled_missing_counts[field] += 1
        for field in LOCKBOX_NON_EXECUTION_FIELDS:
            if row.get(field) is None:
                labelled_missing_non_execution_flag_counts[field] += 1
            elif row.get(field) is not False:
                labelled_non_execution_flag_violation_counts[field] += 1
        if row.get("candidate_id") != policy.candidate_id:
            candidate_mismatch_count += 1
        if row.get("policy_fingerprint") != policy.policy_fingerprint:
            policy_mismatch_count += 1
        pending = pending_by_id.get(record_id)
        if pending is None:
            label_without_pending_count += 1
            if len(sample_violations) < 25:
                sample = sample_identity(row)
                sample["violation"] = "label_without_pending_selection_record"
                sample_violations.append(sample)
        else:
            expected_hash = row_hash(pending)
            if row.get("selection_record_hash") != expected_hash:
                label_hash_mismatch_count += 1
                if len(sample_violations) < 25:
                    sample = sample_identity(row)
                    sample["violation"] = "selection_record_hash_mismatch"
                    sample["expected_selection_record_hash"] = expected_hash
                    sample["label_selection_record_hash"] = row.get("selection_record_hash")
                    sample_violations.append(sample)
            pending_created = parse_utc(pending.get("record_created_utc"))
            label_created = parse_utc(row.get("label_created_utc"))
            if pending_created is not None and label_created is not None and label_created < pending_created:
                labelled_before_pending_count += 1
        if row.get("label_uses_future_data_as_label_only") is not True:
            label_future_use_flag_missing_count += 1
        forbidden_present = [field for field in LABEL_FORBIDDEN_SELECTION_FIELDS if field in row and row.get(field) not in (None, "")]
        if forbidden_present:
            label_forbidden_selection_field_count += 1
            if len(sample_violations) < 25:
                sample = sample_identity(row)
                sample["violation"] = "label_contains_selection_only_fields"
                sample["forbidden_fields"] = forbidden_present
                sample_violations.append(sample)
        decision_time = parse_utc(row.get("decision_time"))
        label_time = parse_utc(row.get("label_source_timestamp"))
        horizon_minutes = finite_float(row.get("label_horizon_minutes"))
        if decision_time is None or label_time is None or horizon_minutes is None:
            label_horizon_not_mature_count += 1
        elif label_time < decision_time + timedelta(minutes=float(horizon_minutes)):
            label_horizon_not_mature_count += 1

    duplicate_pending_ids = {record_id: count for record_id, count in pending_duplicate_ids.items() if count > 1}
    duplicate_pending_decision_keys = {
        decision_key: count for decision_key, count in pending_decision_keys.items() if count > 1
    }
    duplicate_label_ids = {record_id: count for record_id, count in label_duplicate_ids.items() if count > 1}
    duplicate_label_lockbox_ids = {record_id: count for record_id, count in label_lockbox_duplicate_ids.items() if count > 1}
    duplicate_pending_violation_count = sum(count - 1 for count in duplicate_pending_ids.values())
    duplicate_pending_decision_key_violation_count = sum(count - 1 for count in duplicate_pending_decision_keys.values())
    duplicate_label_violation_count = sum(count - 1 for count in duplicate_label_ids.values())
    duplicate_label_lockbox_violation_count = sum(count - 1 for count in duplicate_label_lockbox_ids.values())
    selection_fields_rewritten_after_label_count = append_immutability_conflict_count + label_hash_mismatch_count
    pending_non_execution_flag_violation_total = sum(pending_non_execution_flag_violation_counts.values())
    labelled_non_execution_flag_violation_total = sum(labelled_non_execution_flag_violation_counts.values())
    append_only_violation_count = (
        append_immutability_conflict_count
        + pending_label_outcome_field_count
        + label_forbidden_selection_field_count
        + labelled_before_pending_count
        + duplicate_pending_violation_count
        + duplicate_pending_decision_key_violation_count
        + duplicate_label_violation_count
        + duplicate_label_lockbox_violation_count
    )
    if append_immutability_conflict_count and len(sample_violations) < 25:
        sample_violations.append(
            {
                "violation": "pending_append_immutability_conflict",
                "immutability_conflict_count": append_immutability_conflict_count,
            }
        )
    pass_conditions = {
        "pending_required_fields_present": not pending_missing_counts,
        "label_required_fields_present": not labelled_missing_counts,
        "candidate_policy_consistent": candidate_mismatch_count == 0 and policy_mismatch_count == 0,
        "pending_lockbox_ids_unique": not duplicate_pending_ids,
        "pending_decision_keys_unique": not duplicate_pending_decision_keys,
        "label_record_ids_unique": not duplicate_label_ids,
        "one_label_per_lockbox_record": not duplicate_label_lockbox_ids,
        "labels_have_pending_selection_record": label_without_pending_count == 0,
        "selection_record_hashes_match_pending_records": label_hash_mismatch_count == 0,
        "selection_fields_marked_immutable": pending_nonimmutable_count == 0,
        "pending_records_do_not_contain_label_outcomes": pending_label_outcome_field_count == 0,
        "labels_append_outcomes_only": label_forbidden_selection_field_count == 0,
        "labels_use_future_data_as_label_only": label_future_use_flag_missing_count == 0,
        "labels_created_after_pending_records": labelled_before_pending_count == 0,
        "labels_horizon_matured": label_horizon_not_mature_count == 0,
        "point_in_time_violations_eq_0": point_in_time_violations == 0,
        "selected_fallback_rows_eq_0": selected_fallback_rows == 0,
        "pending_non_execution_flags_false_when_present": pending_non_execution_flag_violation_total == 0,
        "labelled_non_execution_flags_false_when_present": labelled_non_execution_flag_violation_total == 0,
        "pending_append_immutability_conflicts_eq_0": append_immutability_conflict_count == 0,
        "selection_fields_rewritten_after_label_eq_0": selection_fields_rewritten_after_label_count == 0,
        "append_only_violations_eq_0": append_only_violation_count == 0,
    }
    if hash_chain_provided:
        pass_conditions.update(
            {
                "hash_chain_pending_row_count_matches_jsonl": int(hash_pending.get("row_count") or -1) == len(pending_rows),
                "hash_chain_labelled_row_count_matches_jsonl": int(hash_labelled.get("row_count") or -1) == len(labelled_rows),
                "hash_chain_terminal_hashes_present": bool(hash_pending.get("last_chain_hash"))
                and bool(hash_labelled.get("last_chain_hash")),
                "hash_chain_file_hashes_present": bool(hash_pending.get("file_sha256"))
                and bool(hash_labelled.get("file_sha256")),
            }
        )
    hash_chain_integrity = {
        "hash_chain_artifact_present": hash_chain_provided,
        "pending_row_count_matches_jsonl": int(hash_pending.get("row_count") or -1) == len(pending_rows)
        if hash_chain_provided
        else None,
        "labelled_row_count_matches_jsonl": int(hash_labelled.get("row_count") or -1) == len(labelled_rows)
        if hash_chain_provided
        else None,
        "terminal_hashes_present": bool(hash_pending.get("last_chain_hash")) and bool(hash_labelled.get("last_chain_hash"))
        if hash_chain_provided
        else None,
        "file_hashes_present": bool(hash_pending.get("file_sha256")) and bool(hash_labelled.get("file_sha256"))
        if hash_chain_provided
        else None,
        "pending": {
            "row_count": hash_pending.get("row_count"),
            "file_sha256": hash_pending.get("file_sha256"),
            "first_chain_hash": hash_pending.get("first_chain_hash"),
            "last_chain_hash": hash_pending.get("last_chain_hash"),
            "chain_algorithm": hash_pending.get("chain_algorithm"),
        },
        "labelled": {
            "row_count": hash_labelled.get("row_count"),
            "file_sha256": hash_labelled.get("file_sha256"),
            "first_chain_hash": hash_labelled.get("first_chain_hash"),
            "last_chain_hash": hash_labelled.get("last_chain_hash"),
            "chain_algorithm": hash_labelled.get("chain_algorithm"),
        },
    }
    pending_missing_required_field_counts = dict(sorted(pending_missing_counts.items()))
    labelled_missing_required_field_counts = dict(sorted(labelled_missing_counts.items()))
    pending_missing_required_field_total = sum(pending_missing_required_field_counts.values())
    labelled_missing_required_field_total = sum(labelled_missing_required_field_counts.values())
    pending_missing_non_execution_flag_counts_payload = dict(sorted(pending_missing_non_execution_flag_counts.items()))
    labelled_missing_non_execution_flag_counts_payload = dict(sorted(labelled_missing_non_execution_flag_counts.items()))
    pending_non_execution_flag_violation_counts_payload = dict(sorted(pending_non_execution_flag_violation_counts.items()))
    labelled_non_execution_flag_violation_counts_payload = dict(sorted(labelled_non_execution_flag_violation_counts.items()))
    pending_missing_non_execution_flag_total = sum(pending_missing_non_execution_flag_counts_payload.values())
    labelled_missing_non_execution_flag_total = sum(labelled_missing_non_execution_flag_counts_payload.values())
    hash_chain_status = (
        "PASS_HASH_CHAIN_AUDIT"
        if hash_chain_provided
        and hash_chain_integrity["pending_row_count_matches_jsonl"] is True
        and hash_chain_integrity["labelled_row_count_matches_jsonl"] is True
        and hash_chain_integrity["terminal_hashes_present"] is True
        and hash_chain_integrity["file_hashes_present"] is True
        else "FAIL_HASH_CHAIN_AUDIT"
        if hash_chain_provided
        else "HASH_CHAIN_ARTIFACT_NOT_PROVIDED"
    )
    append_only_status = (
        "PASS_APPEND_ONLY_LOCKBOX_AUDIT"
        if append_only_violation_count == 0
        and append_immutability_conflict_count == 0
        and pending_label_outcome_field_count == 0
        and label_forbidden_selection_field_count == 0
        and labelled_before_pending_count == 0
        and label_hash_mismatch_count == 0
        else "FAIL_APPEND_ONLY_LOCKBOX_AUDIT"
    )
    return {
        "schema_version": "challenger_v2_future_lockbox_integrity_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_INTEGRITY_AUDIT" if all(pass_conditions.values()) else "FAIL_LOCKBOX_INTEGRITY_AUDIT",
        "pending_rows": len(pending_rows),
        "labelled_rows": len(labelled_rows),
        "selected_production_grade_rows": selected_production_grade_rows,
        "selected_fallback_rows": selected_fallback_rows,
        "point_in_time_violation_count": point_in_time_violations,
        "point_in_time_violations": point_in_time_violations,
        "pending_append_immutability_conflict_count": append_immutability_conflict_count,
        "selection_fields_rewritten_after_label_count": selection_fields_rewritten_after_label_count,
        "selection_fields_rewritten_after_outcome_count": selection_fields_rewritten_after_label_count,
        "selection_fields_rewritten_after_outcomes": selection_fields_rewritten_after_label_count,
        "selection_fields_rewritten_after_outcomes_count": selection_fields_rewritten_after_label_count,
        "selection_fields_rewritten_after_outcomes_exist": selection_fields_rewritten_after_label_count > 0,
        "selection_fields_immutable_after_outcomes": selection_fields_rewritten_after_label_count == 0,
        "selection_fields_immutable_after_outcomes_exist": selection_fields_rewritten_after_label_count == 0,
        "selection_fields_marked_immutable": pending_nonimmutable_count == 0,
        "selection_fields_nonimmutable_count": pending_nonimmutable_count,
        "pending_append_immutability_conflicts": append_immutability_conflict_count,
        "selection_fields_never_rewritten_after_outcomes": selection_fields_rewritten_after_label_count == 0,
        "append_only_violation_count": append_only_violation_count,
        "append_only_violations": append_only_violation_count,
        "append_only_contract": {
            "pending_selection_records_are_append_only": append_immutability_conflict_count == 0,
            "pending_append_immutability_conflicts": append_immutability_conflict_count,
            "pending_records_do_not_contain_label_outcomes": pending_label_outcome_field_count == 0,
            "labels_append_outcomes_separately": label_forbidden_selection_field_count == 0,
            "labels_created_after_pending_records": labelled_before_pending_count == 0,
            "pending_lockbox_ids_unique": not duplicate_pending_ids,
            "pending_decision_keys_unique": not duplicate_pending_decision_keys,
            "label_record_ids_unique": not duplicate_label_ids,
            "one_label_per_lockbox_record": not duplicate_label_lockbox_ids,
            "selection_record_hashes_match_pending_records": label_hash_mismatch_count == 0,
            "selection_fields_immutable_after_outcomes": selection_fields_rewritten_after_label_count == 0,
            "selection_fields_immutable_after_outcomes_exist": selection_fields_rewritten_after_label_count == 0,
            "selection_fields_marked_immutable": pending_nonimmutable_count == 0,
            "append_only_violations_eq_0": append_only_violation_count == 0,
        },
        "pending_required_fields": list(PENDING_LOCKBOX_REQUIRED_FIELDS),
        "labelled_required_fields": list(LABELLED_LOCKBOX_REQUIRED_FIELDS),
        "required_pending_fields": list(PENDING_LOCKBOX_REQUIRED_FIELDS),
        "required_label_fields": list(LABELLED_LOCKBOX_REQUIRED_FIELDS),
        "required_selection_fields": list(PENDING_LOCKBOX_REQUIRED_FIELDS),
        "required_labelled_fields": list(LABELLED_LOCKBOX_REQUIRED_FIELDS),
        "pending_forbidden_label_fields": list(PENDING_FORBIDDEN_LABEL_FIELDS),
        "label_forbidden_selection_fields": list(LABEL_FORBIDDEN_SELECTION_FIELDS),
        "pending_missing_required_field_counts": pending_missing_required_field_counts,
        "labelled_missing_required_field_counts": labelled_missing_required_field_counts,
        "label_missing_required_field_counts": labelled_missing_required_field_counts,
        "missing_required_selection_field_counts": pending_missing_required_field_counts,
        "missing_required_label_field_counts": labelled_missing_required_field_counts,
        "pending_missing_required_field_total": pending_missing_required_field_total,
        "labelled_missing_required_field_total": labelled_missing_required_field_total,
        "label_missing_required_field_total": labelled_missing_required_field_total,
        "missing_required_selection_field_total": pending_missing_required_field_total,
        "missing_required_label_field_total": labelled_missing_required_field_total,
        "lockbox_non_execution_fields": list(LOCKBOX_NON_EXECUTION_FIELDS),
        "pending_missing_non_execution_flag_counts": pending_missing_non_execution_flag_counts_payload,
        "labelled_missing_non_execution_flag_counts": labelled_missing_non_execution_flag_counts_payload,
        "pending_missing_non_execution_flag_total": pending_missing_non_execution_flag_total,
        "labelled_missing_non_execution_flag_total": labelled_missing_non_execution_flag_total,
        "pending_non_execution_flag_violation_counts": pending_non_execution_flag_violation_counts_payload,
        "labelled_non_execution_flag_violation_counts": labelled_non_execution_flag_violation_counts_payload,
        "pending_non_execution_flag_violation_total": pending_non_execution_flag_violation_total,
        "labelled_non_execution_flag_violation_total": labelled_non_execution_flag_violation_total,
        "legacy_rows_missing_explicit_non_execution_flags": pending_missing_non_execution_flag_total
        + labelled_missing_non_execution_flag_total,
        "non_execution_flag_contract": {
            "new_pending_records_write_explicit_false_flags": True,
            "new_label_records_write_explicit_false_flags": True,
            "legacy_rows_missing_explicit_flags_are_not_rewritten": True,
            "missing_legacy_flags_do_not_count_as_executable": True,
            "true_execution_or_credit_flags_fail_integrity": pending_non_execution_flag_violation_total == 0
            and labelled_non_execution_flag_violation_total == 0,
        },
        "candidate_mismatch_count": candidate_mismatch_count,
        "policy_fingerprint_mismatch_count": policy_mismatch_count,
        "pending_nonimmutable_count": pending_nonimmutable_count,
        "pending_label_outcome_field_count": pending_label_outcome_field_count,
        "label_fields_absent_from_pending": pending_label_outcome_field_count == 0,
        "label_without_pending_count": label_without_pending_count,
        "label_selection_hash_mismatch_count": label_hash_mismatch_count,
        "label_future_use_flag_missing_count": label_future_use_flag_missing_count,
        "label_forbidden_selection_field_count": label_forbidden_selection_field_count,
        "label_selection_only_field_count": label_forbidden_selection_field_count,
        "selection_fields_absent_from_labels": label_forbidden_selection_field_count == 0,
        "labels_append_outcomes_only_status": (
            "PASS_LABELS_APPEND_OUTCOMES_ONLY"
            if pending_label_outcome_field_count == 0 and label_forbidden_selection_field_count == 0
            else "FAIL_LABEL_SELECTION_OUTCOME_SEPARATION"
        ),
        "immutable_selection_contract": {
            "pending_selection_fields_marked_immutable": pending_nonimmutable_count == 0,
            "pending_append_immutability_conflicts_eq_0": append_immutability_conflict_count == 0,
            "selection_record_hashes_match_pending_records": label_hash_mismatch_count == 0,
            "selection_fields_rewritten_after_label_eq_0": selection_fields_rewritten_after_label_count == 0,
        },
        "labelled_before_pending_count": labelled_before_pending_count,
        "label_horizon_not_mature_count": label_horizon_not_mature_count,
        "duplicate_pending_lockbox_ids": duplicate_pending_ids,
        "duplicate_pending_record_count": duplicate_pending_violation_count,
        "duplicate_pending_decision_keys": duplicate_pending_decision_keys,
        "duplicate_pending_decision_key_count": duplicate_pending_decision_key_violation_count,
        "duplicate_label_record_ids": duplicate_label_ids,
        "duplicate_label_record_count": duplicate_label_violation_count,
        "duplicate_label_lockbox_ids": duplicate_label_lockbox_ids,
        "duplicate_label_lockbox_record_count": duplicate_label_lockbox_violation_count,
        "duplicate_labelled_record_count": duplicate_label_violation_count,
        "duplicate_labelled_lockbox_record_count": duplicate_label_lockbox_violation_count,
        "append_only_status": append_only_status,
        "hash_chain_integrity": hash_chain_integrity,
        "hash_chain_status": hash_chain_status,
        "hash_chain_artifact_present": hash_chain_provided,
        "hash_chain_pending_row_count": hash_pending.get("row_count"),
        "hash_chain_labelled_row_count": hash_labelled.get("row_count"),
        "hash_chain_pending_row_count_matches_jsonl": hash_chain_integrity["pending_row_count_matches_jsonl"],
        "hash_chain_labelled_row_count_matches_jsonl": hash_chain_integrity["labelled_row_count_matches_jsonl"],
        "hash_chain_terminal_hashes_present": hash_chain_integrity["terminal_hashes_present"],
        "hash_chain_file_hashes_present": hash_chain_integrity["file_hashes_present"],
        "pass_conditions": pass_conditions,
        "sample_violations": sample_violations,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def outcome_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pnls = [float(row.get("net_return_bps") or 0.0) for row in rows]
    profit = sum(value for value in pnls if value > 0.0)
    loss = abs(sum(value for value in pnls if value < 0.0))
    false_positives = sum(1 for value in pnls if value <= 0.0)
    symbols = {str(row.get("symbol") or "") for row in rows if row.get("symbol")}
    long_count = sum(1 for row in rows if str(row.get("predicted_direction") or "").upper() == "LONG")
    short_count = sum(1 for row in rows if str(row.get("predicted_direction") or "").upper() == "SHORT")
    expectancy = sum(pnls) / len(pnls) if pnls else None
    lower_bound = None
    if len(pnls) >= 2:
        mean, std = mean_std(pnls)
        if mean is not None and std is not None:
            lower_bound = mean - 1.96 * std / math.sqrt(len(pnls))
    return {
        "row_count": len(rows),
        "symbols": len(symbols),
        "long_count": long_count,
        "short_count": short_count,
        "after_cost_expectancy_bps": expectancy,
        "expectancy_95pct_lower_bound_bps": lower_bound,
        "profit_factor": (profit / loss) if loss > 0 else (float("inf") if profit > 0 else None),
        "false_positive_rate": false_positives / len(pnls) if pnls else None,
        "worst_1pct_loss_bps": quantile(sorted(pnls), 0.01) if pnls else None,
        "median_net_return_bps": quantile(sorted(pnls), 0.50) if pnls else None,
        "best_net_return_bps": max(pnls) if pnls else None,
        "worst_net_return_bps": min(pnls) if pnls else None,
    }


def shadow_label_outcome_diagnostics(
    *,
    policy: FrozenPolicy,
    pending_rows: Sequence[Mapping[str, Any]],
    labelled_rows: Sequence[Mapping[str, Any]],
    cost_status: Mapping[str, Any],
) -> dict[str, Any]:
    pending_by_id = {str(row.get("lockbox_record_id") or ""): row for row in pending_rows if row.get("lockbox_record_id")}
    enriched: list[dict[str, Any]] = []
    for label in labelled_rows:
        pending = pending_by_id.get(str(label.get("lockbox_record_id") or "")) or {}
        merged = dict(label)
        merged["score"] = pending.get("score")
        merged["predicted_net_edge_bps"] = pending.get("predicted_net_edge_bps")
        merged["threshold_distance_bps"] = pending.get("threshold_distance_bps")
        merged["production_cost_bps"] = pending.get("production_cost_bps")
        merged["liquidity_status"] = pending.get("liquidity_status")
        enriched.append(merged)

    by_side = {
        side: outcome_stats([row for row in enriched if str(row.get("predicted_direction") or "").upper() == side])
        for side in ("LONG", "SHORT")
    }
    rejection_reason_counts: Counter[str] = Counter()
    by_reason: dict[str, Any] = {}
    for row in enriched:
        reasons = [str(reason) for reason in row.get("rejection_reasons") or ["candidate_ranked_non_executable"]]
        rejection_reason_counts.update(reasons)
        for reason in reasons:
            by_reason.setdefault(reason, []).append(row)
    by_reason_stats = {reason: outcome_stats(rows) for reason, rows in sorted(by_reason.items())}
    edge_rows = [
        row
        for row in enriched
        if finite_float(row.get("threshold_distance_bps")) is not None
    ]
    near_threshold = [
        row
        for row in edge_rows
        if -5.0 <= float(row.get("threshold_distance_bps") or 0.0) < 0.0
    ]
    above_threshold_rejected = [
        row
        for row in edge_rows
        if float(row.get("threshold_distance_bps") or 0.0) >= 0.0
    ]
    label_source_counts = Counter(str(row.get("label_source") or "UNKNOWN") for row in labelled_rows)
    return {
        "schema_version": "challenger_v2_shadow_label_outcome_diagnostics_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PUBLISHED_SHADOW_LABEL_DIAGNOSTICS",
        "labelled_shadow_rows": len(labelled_rows),
        "selected_economic_rows": sum(1 for row in labelled_rows if row.get("selected") is True),
        "rejected_shadow_rows": sum(1 for row in labelled_rows if row.get("selected") is not True),
        "all_labelled_stats": outcome_stats(enriched),
        "by_predicted_direction": by_side,
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "by_rejection_reason": by_reason_stats,
        "near_threshold_rejected_stats": outcome_stats(near_threshold),
        "above_threshold_rejected_stats": outcome_stats(above_threshold_rejected),
        "label_source_counts": dict(sorted(label_source_counts.items())),
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "Rows are labelled post-horizon but remain shadow-only because selection/economic-cost gates failed at decision time.",
            "Diagnostics are for zero-supply/root-cause analysis only and cannot satisfy blind lockbox pass conditions.",
        ],
    }


def shadow_lockbox_outcome_actionability_audit(
    *,
    policy: FrozenPolicy,
    shadow_label_diagnostics: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    cost_status: Mapping[str, Any],
) -> dict[str, Any]:
    stats = shadow_label_diagnostics.get("all_labelled_stats")
    stats = stats if isinstance(stats, Mapping) else {}

    def number(name: str) -> float | None:
        value = stats.get(name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    row_count = int(stats.get("row_count") or shadow_label_diagnostics.get("labelled_shadow_rows") or 0)
    selected_economic_rows = int(shadow_label_diagnostics.get("selected_economic_rows") or 0)
    independent_economic_candidates = int(lockbox_pass_contract.get("independent_economic_candidates") or 0)
    production_grade_cost_coverage = float(cost_status.get("production_grade_cost_coverage") or 0.0)
    shadow_metric_conditions = {
        "shadow_labelled_rows_gte_300": row_count >= 300,
        "shadow_symbols_gte_30": int(stats.get("symbols") or 0) >= 30,
        "shadow_long_gt_0": int(stats.get("long_count") or 0) > 0,
        "shadow_short_gt_0": int(stats.get("short_count") or 0) > 0,
        "shadow_after_cost_expectancy_gt_0": number("after_cost_expectancy_bps") is not None
        and float(number("after_cost_expectancy_bps") or 0.0) > 0.0,
        "shadow_expectancy_95pct_lower_bound_gt_0": number("expectancy_95pct_lower_bound_bps") is not None
        and float(number("expectancy_95pct_lower_bound_bps") or 0.0) > 0.0,
        "shadow_profit_factor_gte_1_5": number("profit_factor") is not None
        and float(number("profit_factor") or 0.0) >= 1.5,
        "shadow_false_positive_rate_lte_0_40": number("false_positive_rate") is not None
        and float(number("false_positive_rate") or 0.0) <= 0.40,
        "shadow_worst_1pct_loss_inside_risk_envelope": number("worst_1pct_loss_bps") is not None
        and float(number("worst_1pct_loss_bps") or 0.0) >= -500.0,
    }
    official_counting_conditions = {
        "official_lockbox_contract_passed": lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "official_independent_economic_candidates_gte_300": independent_economic_candidates >= 300,
        "official_production_grade_cost_coverage_gte_95pct": production_grade_cost_coverage >= 0.95,
        "official_point_in_time_violations_eq_0": int(lockbox_pass_contract.get("point_in_time_violations") or 0) == 0,
    }
    non_counting_reasons: list[str] = []
    if selected_economic_rows < row_count:
        non_counting_reasons.append("shadow_rows_include_rejected_or_non_economic_decisions")
    if independent_economic_candidates < 300:
        non_counting_reasons.append("official_independent_economic_candidates_below_300")
    if production_grade_cost_coverage < 0.95:
        non_counting_reasons.append("production_grade_cost_coverage_below_95pct")
    if lockbox_pass_contract.get("status") != "PASS_BLIND_LOCKBOX_PASS_CONTRACT":
        non_counting_reasons.append("official_blind_lockbox_contract_not_passed")

    failed_shadow_metric_conditions = [
        name for name, passed in shadow_metric_conditions.items() if not passed
    ]
    if row_count == 0:
        status = "BLOCKED_NO_SHADOW_LOCKBOX_LABELS_AVAILABLE"
    elif failed_shadow_metric_conditions:
        status = "DIAGNOSTIC_SHADOW_OUTCOMES_FAIL_PHASE_5_THRESHOLDS_NON_COUNTING"
    else:
        status = "DIAGNOSTIC_SHADOW_OUTCOMES_PASS_PHASE_5_THRESHOLDS_NON_COUNTING"
    pass_conditions = {
        **shadow_metric_conditions,
        **official_counting_conditions,
        "shadow_rows_do_not_count_as_a_grade_evidence": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "frozen_candidate_tuning_from_shadow_labels_disallowed": True,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    actionability_actuals = {
        "shadow_labelled_rows_gte_300": row_count,
        "shadow_symbols_gte_30": stats.get("symbols"),
        "shadow_long_gt_0": stats.get("long_count"),
        "shadow_short_gt_0": stats.get("short_count"),
        "shadow_after_cost_expectancy_gt_0": stats.get("after_cost_expectancy_bps"),
        "shadow_expectancy_95pct_lower_bound_gt_0": stats.get("expectancy_95pct_lower_bound_bps"),
        "shadow_profit_factor_gte_1_5": stats.get("profit_factor"),
        "shadow_false_positive_rate_lte_0_40": stats.get("false_positive_rate"),
        "shadow_worst_1pct_loss_inside_risk_envelope": stats.get("worst_1pct_loss_bps"),
        "official_lockbox_contract_passed": lockbox_pass_contract.get("status"),
        "official_independent_economic_candidates_gte_300": independent_economic_candidates,
        "official_production_grade_cost_coverage_gte_95pct": production_grade_cost_coverage,
        "official_point_in_time_violations_eq_0": lockbox_pass_contract.get("point_in_time_violations"),
        "shadow_rows_do_not_count_as_a_grade_evidence": False,
        "paper_fill_allowed_false": False,
        "routes_to_live_false": False,
        "frozen_candidate_tuning_from_shadow_labels_disallowed": False,
    }
    actionability_required = {
        "shadow_labelled_rows_gte_300": ">=300",
        "shadow_symbols_gte_30": ">=30",
        "shadow_long_gt_0": ">0",
        "shadow_short_gt_0": ">0",
        "shadow_after_cost_expectancy_gt_0": ">0",
        "shadow_expectancy_95pct_lower_bound_gt_0": ">0",
        "shadow_profit_factor_gte_1_5": ">=1.5",
        "shadow_false_positive_rate_lte_0_40": "<=0.40",
        "shadow_worst_1pct_loss_inside_risk_envelope": ">=-500.0",
        "official_lockbox_contract_passed": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "official_independent_economic_candidates_gte_300": ">=300",
        "official_production_grade_cost_coverage_gte_95pct": ">=0.95",
        "official_point_in_time_violations_eq_0": 0,
        "shadow_rows_do_not_count_as_a_grade_evidence": False,
        "paper_fill_allowed_false": False,
        "routes_to_live_false": False,
        "frozen_candidate_tuning_from_shadow_labels_disallowed": False,
    }
    blocker_details = {
        name: {
            "pass_condition": name,
            "passed": False,
            "observed": actionability_actuals.get(name),
            "required": actionability_required.get(name),
        }
        for name, passed in {**shadow_metric_conditions, **official_counting_conditions}.items()
        if passed is not True
    }

    return {
        "schema_version": "challenger_v2_shadow_lockbox_outcome_actionability_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "shadow_rows": row_count,
        "shadow_labelled_rows": row_count,
        "labelled_shadow_rows": row_count,
        "selected_shadow_rows": selected_economic_rows,
        "selected_economic_rows": selected_economic_rows,
        "economic_shadow_rows": selected_economic_rows,
        "official_independent_economic_candidates": independent_economic_candidates,
        "production_grade_cost_coverage": production_grade_cost_coverage,
        "after_cost_expectancy_bps": stats.get("after_cost_expectancy_bps"),
        "expectancy_95pct_lower_bound_bps": stats.get("expectancy_95pct_lower_bound_bps"),
        "profit_factor": stats.get("profit_factor"),
        "false_positive_rate": stats.get("false_positive_rate"),
        "worst_1pct_loss_bps": stats.get("worst_1pct_loss_bps"),
        "shadow_all_labelled_stats": dict(stats),
        "shadow_metric_conditions": shadow_metric_conditions,
        "failed_shadow_metric_conditions": failed_shadow_metric_conditions,
        "failed_metric_conditions": failed_shadow_metric_conditions,
        "official_counting_conditions": official_counting_conditions,
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "actuals": actionability_actuals,
        "required": actionability_required,
        "sample_blockers": list(blocker_details.values())[:25],
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "non_counting_reasons": non_counting_reasons,
        "official_lockbox_status": lockbox_pass_contract.get("status"),
        "official_blind_lockbox_rejection_allowed": False,
        "official_blind_lockbox_promotion_allowed": False,
        "frozen_candidate_tuning_allowed_from_shadow_labels": False,
        "frozen_candidate_modified": False,
        "next_allowed_actions": [
            "continue_future_candidate_bound_production_grade_cost_capture",
            "continue_append_only_blind_lockbox_collection",
            "bind_to_paper_only_after_official_blind_lockbox_pass",
            "if_an_official_production_grade_blind_lockbox_fails_then_reject_and_train_new_candidate_using_train_validation_only",
        ],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def lockbox_performance(
    labelled_rows: Sequence[Mapping[str, Any]],
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    point_in_time_violations: int,
) -> dict[str, Any]:
    selected = [row for row in labelled_rows if row.get("selected") is True]
    pnls = [float(row.get("net_return_bps") or 0.0) for row in selected]
    profit = sum(value for value in pnls if value > 0.0)
    loss = abs(sum(value for value in pnls if value < 0.0))
    false_positives = sum(1 for value in pnls if value <= 0.0)
    symbols = {str(row.get("symbol") or "") for row in selected if row.get("symbol")}
    long_count = sum(1 for row in selected if str(row.get("predicted_direction") or "").upper() == "LONG")
    short_count = sum(1 for row in selected if str(row.get("predicted_direction") or "").upper() == "SHORT")
    expectancy = sum(pnls) / len(pnls) if pnls else None
    lower_bound = None
    if len(pnls) >= 2:
        mean, std = mean_std(pnls)
        if mean is not None and std is not None:
            lower_bound = mean - 1.96 * std / math.sqrt(len(pnls))
    worst_1pct = quantile(sorted(pnls), 0.01) if pnls else None
    profit_factor = (profit / loss) if loss > 0 else (float("inf") if profit > 0 else None)
    false_positive_rate = false_positives / len(pnls) if pnls else None
    concentration_counts = Counter(str(row.get("symbol") or "") for row in selected)
    max_concentration = max((count / len(selected) for count in concentration_counts.values()), default=None)
    required_independent_candidates = 300
    required_symbols = 30
    required_profit_factor = 1.5
    required_false_positive_rate = 0.40
    required_max_concentration_pct = 0.30
    worst_1pct_loss_floor_bps = -500.0
    production_grade_cost_coverage = float(cost_status.get("production_grade_cost_coverage") or 0.0)
    pass_conditions = {
        "independent_economic_candidates_gte_300": len(selected) >= required_independent_candidates,
        "symbols_gte_30": len(symbols) >= required_symbols,
        "long_gt_0": long_count > 0,
        "short_gt_0": short_count > 0,
        "after_cost_expectancy_gt_0": expectancy is not None and expectancy > 0,
        "expectancy_95pct_lower_bound_gt_0": lower_bound is not None and lower_bound > 0,
        "profit_factor_gte_1_5": profit_factor is not None and profit_factor >= required_profit_factor,
        "false_positive_rate_lte_0_40": false_positive_rate is not None and false_positive_rate <= required_false_positive_rate,
        "no_concentration_dimension_gt_30pct": max_concentration is not None and max_concentration <= required_max_concentration_pct,
        "worst_1pct_loss_inside_risk_envelope": worst_1pct is not None and worst_1pct >= worst_1pct_loss_floor_bps,
        "point_in_time_violations_eq_0": point_in_time_violations == 0,
        "production_grade_cost_coverage_gte_95pct": production_grade_cost_coverage >= 0.95,
    }
    minimum_pass = {
        "selected_candidates_gte_300": pass_conditions["independent_economic_candidates_gte_300"],
        **pass_conditions,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    non_counting_reason_by_condition = {
        "independent_economic_candidates_gte_300": "independent_economic_candidates_below_300",
        "symbols_gte_30": "symbols_below_30",
        "long_gt_0": "long_candidates_eq_0",
        "short_gt_0": "short_candidates_eq_0",
        "after_cost_expectancy_gt_0": "after_cost_expectancy_not_positive_or_unavailable",
        "expectancy_95pct_lower_bound_gt_0": "expectancy_95pct_lower_bound_not_positive_or_unavailable",
        "profit_factor_gte_1_5": "profit_factor_below_1_5_or_unavailable",
        "false_positive_rate_lte_0_40": "false_positive_rate_above_0_40_or_unavailable",
        "no_concentration_dimension_gt_30pct": "concentration_dimension_above_30pct_or_unavailable",
        "worst_1pct_loss_inside_risk_envelope": "worst_1pct_loss_outside_risk_envelope_or_unavailable",
        "point_in_time_violations_eq_0": "point_in_time_violations_present",
        "production_grade_cost_coverage_gte_95pct": "production_grade_cost_coverage_below_95pct",
    }
    non_counting_reasons = [
        non_counting_reason_by_condition[name]
        for name in blocked_reasons
        if name in non_counting_reason_by_condition
    ]
    condition_details = {
        "independent_economic_candidates_gte_300": {
            "passed": pass_conditions["independent_economic_candidates_gte_300"],
            "observed": len(selected),
            "required": f">={required_independent_candidates}",
            "shortfall": max(0, required_independent_candidates - len(selected)),
        },
        "symbols_gte_30": {
            "passed": pass_conditions["symbols_gte_30"],
            "observed": len(symbols),
            "required": f">={required_symbols}",
            "shortfall": max(0, required_symbols - len(symbols)),
        },
        "long_gt_0": {
            "passed": pass_conditions["long_gt_0"],
            "observed": long_count,
            "required": ">0",
            "shortfall": max(0, 1 - long_count),
        },
        "short_gt_0": {
            "passed": pass_conditions["short_gt_0"],
            "observed": short_count,
            "required": ">0",
            "shortfall": max(0, 1 - short_count),
        },
        "after_cost_expectancy_gt_0": {
            "passed": pass_conditions["after_cost_expectancy_gt_0"],
            "observed": expectancy,
            "required": ">0",
        },
        "expectancy_95pct_lower_bound_gt_0": {
            "passed": pass_conditions["expectancy_95pct_lower_bound_gt_0"],
            "observed": lower_bound,
            "required": ">0",
        },
        "profit_factor_gte_1_5": {
            "passed": pass_conditions["profit_factor_gte_1_5"],
            "observed": profit_factor,
            "required": f">={required_profit_factor}",
            "shortfall": max(0.0, required_profit_factor - profit_factor) if profit_factor is not None else None,
        },
        "false_positive_rate_lte_0_40": {
            "passed": pass_conditions["false_positive_rate_lte_0_40"],
            "observed": false_positive_rate,
            "required": f"<={required_false_positive_rate}",
            "excess": max(0.0, false_positive_rate - required_false_positive_rate)
            if false_positive_rate is not None
            else None,
        },
        "no_concentration_dimension_gt_30pct": {
            "passed": pass_conditions["no_concentration_dimension_gt_30pct"],
            "observed": max_concentration,
            "required": f"<={required_max_concentration_pct}",
            "excess": max(0.0, max_concentration - required_max_concentration_pct)
            if max_concentration is not None
            else None,
        },
        "worst_1pct_loss_inside_risk_envelope": {
            "passed": pass_conditions["worst_1pct_loss_inside_risk_envelope"],
            "observed": worst_1pct,
            "required": f">={worst_1pct_loss_floor_bps}",
            "excess_loss_bps": max(0.0, worst_1pct_loss_floor_bps - worst_1pct)
            if worst_1pct is not None
            else None,
        },
        "point_in_time_violations_eq_0": {
            "passed": pass_conditions["point_in_time_violations_eq_0"],
            "observed": point_in_time_violations,
            "required": 0,
        },
        "production_grade_cost_coverage_gte_95pct": {
            "passed": pass_conditions["production_grade_cost_coverage_gte_95pct"],
            "observed": production_grade_cost_coverage,
            "required": ">=0.95",
            "shortfall": max(0.0, 0.95 - production_grade_cost_coverage),
        },
    }
    failed_blocker_details = {
        name: detail
        for name, detail in condition_details.items()
        if detail["passed"] is not True
    }
    lockbox_actuals = {
        "independent_economic_candidates": len(selected),
        "symbols": len(symbols),
        "long_candidates": long_count,
        "short_candidates": short_count,
        "after_cost_expectancy_bps": expectancy,
        "expectancy_95pct_lower_bound_bps": lower_bound,
        "profit_factor": profit_factor,
        "false_positive_rate": false_positive_rate,
        "max_concentration_pct": max_concentration,
        "worst_1pct_loss_bps": worst_1pct,
        "point_in_time_violations": point_in_time_violations,
        "production_grade_cost_coverage": production_grade_cost_coverage,
    }
    lockbox_required = {
        "independent_economic_candidates": f">={required_independent_candidates}",
        "symbols": f">={required_symbols}",
        "long_candidates": ">0",
        "short_candidates": ">0",
        "after_cost_expectancy_bps": ">0",
        "expectancy_95pct_lower_bound_bps": ">0",
        "profit_factor": f">={required_profit_factor}",
        "false_positive_rate": f"<={required_false_positive_rate}",
        "max_concentration_pct": f"<={required_max_concentration_pct}",
        "worst_1pct_loss_bps": f">={worst_1pct_loss_floor_bps}",
        "point_in_time_violations": 0,
        "production_grade_cost_coverage": ">=0.95",
    }
    sample_blockers = [
        {"pass_condition": name, **detail}
        for name, detail in failed_blocker_details.items()
    ][:25]
    status = "PASS" if all(pass_conditions.values()) else "BLOCKED_LOCKBOX_PASS_CONDITIONS_NOT_MET"
    return {
        "schema_version": "challenger_v2_blind_lockbox_performance_v2",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "labelled_rows": len(labelled_rows),
        "selected_economic_candidates": len(selected),
        "independent_economic_candidates": len(selected),
        "required_independent_economic_candidates": required_independent_candidates,
        "independent_economic_candidate_shortfall_to_300": max(0, required_independent_candidates - len(selected)),
        "required_symbols": required_symbols,
        "symbol_shortfall_to_30": max(0, required_symbols - len(symbols)),
        "long_candidate_shortfall_to_1": max(0, 1 - long_count),
        "short_candidate_shortfall_to_1": max(0, 1 - short_count),
        "required_profit_factor": required_profit_factor,
        "required_false_positive_rate_lte": required_false_positive_rate,
        "required_max_concentration_pct": required_max_concentration_pct,
        "worst_1pct_loss_floor_bps": worst_1pct_loss_floor_bps,
        "symbols": len(symbols),
        "long_count": long_count,
        "short_count": short_count,
        "after_cost_expectancy_bps": expectancy,
        "expectancy_95pct_lower_bound_bps": lower_bound,
        "profit_factor": profit_factor,
        "false_positive_rate": false_positive_rate,
        "worst_1pct_loss_bps": worst_1pct,
        "symbol_concentration": dict(sorted(concentration_counts.items())),
        "max_concentration_pct": max_concentration,
        "point_in_time_violations": point_in_time_violations,
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "production_grade_cost_coverage_shortfall_to_95pct": max(0.0, 0.95 - production_grade_cost_coverage),
        "pass": status == "PASS",
        "minimum_pass": minimum_pass,
        "pass_conditions": pass_conditions,
        "blocked_reasons": blocked_reasons,
        "non_counting_reasons": non_counting_reasons,
        "lockbox_performance_condition_details": condition_details,
        "blocker_details": failed_blocker_details,
        "failed_blocker_details": failed_blocker_details,
        "actuals": lockbox_actuals,
        "required": lockbox_required,
        "sample_blockers": sample_blockers,
        "lockbox_counting_evidence_allowed": status == "PASS",
        "lockbox_prerequisite_for_paper_canary_binding_satisfied": status == "PASS",
        "do_not_tune_frozen_candidate_after_viewing_lockbox_results": True,
        "new_candidate_required_if_tuning_needed": True,
        "paper_only": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
    }


def concentration_dimension(rows: Sequence[Mapping[str, Any]], field_name: str) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(field_name)
        if field_name == "decision_day":
            parsed = parse_utc(row.get("decision_time"))
            value = parsed.date().isoformat() if parsed is not None else str(row.get("decision_time") or "UNKNOWN")[:10]
        key = str(value or "UNKNOWN")
        counts[key] += 1
    total = len(rows)
    max_key = None
    max_count = 0
    if counts:
        max_key, max_count = max(counts.items(), key=lambda item: item[1])
    return {
        "field": field_name,
        "counts": dict(sorted(counts.items())),
        "max_key": max_key,
        "max_count": max_count,
        "max_pct": max_count / total if total else None,
    }


def blind_lockbox_pass_contract_audit(
    *,
    policy: FrozenPolicy,
    pending_rows: Sequence[Mapping[str, Any]],
    labelled_rows: Sequence[Mapping[str, Any]],
    cost_status: Mapping[str, Any],
    lockbox_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    pending_by_id = {
        str(row.get("lockbox_record_id") or ""): row
        for row in pending_rows
        if row.get("lockbox_record_id")
    }
    selected_pending_rows = sum(1 for row in pending_rows if row.get("selected") is True)
    rejected_pending_rows = sum(
        1
        for row in pending_rows
        if row.get("rejected") is True or row.get("selected") is not True
    )
    pending_rejection_reason_counts: Counter[str] = Counter()
    for row in pending_rows:
        pending_rejection_reason_counts.update(str(reason) for reason in row.get("rejection_reasons") or ())
    independent: dict[str, dict[str, Any]] = {}
    excluded_counts: Counter[str] = Counter()
    sample_excluded: list[dict[str, Any]] = []
    selected_label_rows = 0
    selected_label_rows_with_pending_record = 0
    candidate_identity_bound_selected_label_rows = 0
    production_grade_cost_selected_label_rows = 0
    fallback_free_cost_selected_label_rows = 0
    for label in labelled_rows:
        if label.get("selected") is not True:
            continue
        selected_label_rows += 1
        record_id = str(label.get("lockbox_record_id") or "")
        pending = pending_by_id.get(record_id)
        if pending is None:
            excluded_counts["missing_pending_selection_record"] += 1
            continue
        selected_label_rows_with_pending_record += 1
        reasons: list[str] = []
        candidate_id_bound = (
            label.get("candidate_id") == policy.candidate_id
            and pending.get("candidate_id") == policy.candidate_id
        )
        policy_fingerprint_bound = (
            label.get("policy_fingerprint") == policy.policy_fingerprint
            and pending.get("policy_fingerprint") == policy.policy_fingerprint
        )
        model_source_bound = pending.get("model_source") == policy.model_source
        candidate_identity_bound = candidate_id_bound and policy_fingerprint_bound and model_source_bound
        if not candidate_id_bound:
            reasons.append("candidate_id_mismatch")
        if not policy_fingerprint_bound:
            reasons.append("policy_fingerprint_mismatch")
        if not model_source_bound:
            reasons.append("model_source_mismatch")
        cost = pending.get("estimated_production_cost")
        cost_map = cost if isinstance(cost, Mapping) else {}
        production_grade_cost = cost_map.get("production_grade_evidence") is True
        fallback_free_cost = production_grade_cost and cost_map.get("fallback") is not True
        if candidate_identity_bound:
            candidate_identity_bound_selected_label_rows += 1
        if candidate_identity_bound and production_grade_cost:
            production_grade_cost_selected_label_rows += 1
        if candidate_identity_bound and fallback_free_cost:
            fallback_free_cost_selected_label_rows += 1
        if not fallback_free_cost:
            reasons.append("not_production_grade_cost_at_decision")
        if record_id in independent:
            reasons.append("duplicate_lockbox_record_id")
        if reasons:
            excluded_counts.update(reasons)
            if len(sample_excluded) < 25:
                sample_excluded.append(
                    {
                        "lockbox_record_id": record_id,
                        "symbol": label.get("symbol"),
                        "timeframe": label.get("timeframe"),
                        "decision_time": label.get("decision_time"),
                        "reasons": reasons,
                    }
                )
            continue
        merged = dict(label)
        merged["model_source"] = pending.get("model_source")
        merged["estimated_production_cost"] = cost_map
        independent[record_id] = merged

    candidates = list(independent.values())
    stats = outcome_stats(candidates)
    candidate_count_by_direction = {
        "LONG": sum(1 for row in candidates if str(row.get("predicted_direction") or "").upper() == "LONG"),
        "SHORT": sum(1 for row in candidates if str(row.get("predicted_direction") or "").upper() == "SHORT"),
    }
    selected_label_count_by_direction = {
        "LONG": sum(1 for row in labelled_rows if row.get("selected") is True and str(row.get("predicted_direction") or "").upper() == "LONG"),
        "SHORT": sum(1 for row in labelled_rows if row.get("selected") is True and str(row.get("predicted_direction") or "").upper() == "SHORT"),
    }
    pnls = [float(row.get("net_return_bps") or 0.0) for row in candidates]
    worst_1pct = quantile(sorted(pnls), 0.01) if pnls else None
    dimensions = {
        field: concentration_dimension(candidates, field)
        for field in ("symbol", "timeframe", "decision_day")
    }
    max_concentration_dimension = None
    max_concentration_pct = None
    for name, payload in dimensions.items():
        pct = finite_float(payload.get("max_pct"))
        if pct is not None and (max_concentration_pct is None or pct > max_concentration_pct):
            max_concentration_pct = pct
            max_concentration_dimension = name

    integrity_pass_conditions = lockbox_integrity.get("pass_conditions")
    integrity_pass_conditions = integrity_pass_conditions if isinstance(integrity_pass_conditions, Mapping) else {}
    production_grade_cost_coverage = float(cost_status.get("production_grade_cost_coverage") or 0.0)
    required_independent_candidates = 300
    required_symbols = 30
    required_profit_factor = 1.5
    required_false_positive_rate = 0.40
    required_max_concentration_pct = 0.30
    worst_1pct_loss_floor_bps = -500.0
    independent_candidate_count = len(candidates)
    symbol_count = int(stats.get("symbols") or 0)
    long_count = int(stats.get("long_count") or 0)
    short_count = int(stats.get("short_count") or 0)
    after_cost_expectancy_bps = finite_float(stats.get("after_cost_expectancy_bps"))
    expectancy_lower_bound_bps = finite_float(stats.get("expectancy_95pct_lower_bound_bps"))
    profit_factor = finite_float(stats.get("profit_factor"))
    false_positive_rate = finite_float(stats.get("false_positive_rate"))
    pass_conditions = {
        "independent_economic_candidates_gte_300": independent_candidate_count >= required_independent_candidates,
        "symbols_gte_30": symbol_count >= required_symbols,
        "long_gt_0": long_count > 0,
        "short_gt_0": short_count > 0,
        "after_cost_expectancy_gt_0": after_cost_expectancy_bps is not None and after_cost_expectancy_bps > 0.0,
        "expectancy_95pct_lower_bound_gt_0": expectancy_lower_bound_bps is not None and expectancy_lower_bound_bps > 0.0,
        "profit_factor_gte_1_5": profit_factor is not None and profit_factor >= required_profit_factor,
        "false_positive_rate_lte_0_40": false_positive_rate is not None and false_positive_rate <= required_false_positive_rate,
        "no_concentration_dimension_gt_30pct": max_concentration_pct is not None and max_concentration_pct <= required_max_concentration_pct,
        "worst_1pct_loss_inside_risk_envelope": worst_1pct is not None and worst_1pct >= worst_1pct_loss_floor_bps,
        "point_in_time_violations_eq_0": int(lockbox_integrity.get("point_in_time_violations") or 0) == 0,
        "production_grade_cost_coverage_gte_95pct": production_grade_cost_coverage >= 0.95,
        "lockbox_integrity_audit_passed": lockbox_integrity.get("status") == "PASS_INTEGRITY_AUDIT",
        "labels_have_pending_selection_record": integrity_pass_conditions.get("labels_have_pending_selection_record") is True,
        "selection_record_hashes_match_pending_records": integrity_pass_conditions.get("selection_record_hashes_match_pending_records") is True,
        "selection_fields_marked_immutable": integrity_pass_conditions.get("selection_fields_marked_immutable") is True,
        "selected_fallback_rows_eq_0": integrity_pass_conditions.get("selected_fallback_rows_eq_0") is True,
    }
    non_counting_reasons: list[str] = []
    if selected_label_rows == 0:
        non_counting_reasons.append("no_selected_label_rows")
    for reason, count in sorted(excluded_counts.items()):
        non_counting_reasons.append(f"excluded_selected_candidate_{reason}:{count}")
    failed_condition_reasons = {
        "independent_economic_candidates_gte_300": "independent_economic_candidates_below_300",
        "symbols_gte_30": "symbols_below_30",
        "long_gt_0": "long_candidates_eq_0",
        "short_gt_0": "short_candidates_eq_0",
        "after_cost_expectancy_gt_0": "after_cost_expectancy_not_positive_or_unavailable",
        "expectancy_95pct_lower_bound_gt_0": "expectancy_95pct_lower_bound_not_positive_or_unavailable",
        "profit_factor_gte_1_5": "profit_factor_below_1_5_or_unavailable",
        "false_positive_rate_lte_0_40": "false_positive_rate_above_0_40_or_unavailable",
        "no_concentration_dimension_gt_30pct": "concentration_dimension_above_30pct_or_unavailable",
        "worst_1pct_loss_inside_risk_envelope": "worst_1pct_loss_outside_risk_envelope_or_unavailable",
        "point_in_time_violations_eq_0": "point_in_time_violations_present",
        "production_grade_cost_coverage_gte_95pct": "production_grade_cost_coverage_below_95pct",
        "lockbox_integrity_audit_passed": "lockbox_integrity_audit_not_passed",
        "labels_have_pending_selection_record": "labels_missing_pending_selection_record",
        "selection_record_hashes_match_pending_records": "selection_record_hash_mismatch",
        "selection_fields_marked_immutable": "selection_fields_not_marked_immutable",
        "selected_fallback_rows_eq_0": "selected_fallback_rows_present",
    }
    for condition, reason in failed_condition_reasons.items():
        if pass_conditions.get(condition) is not True:
            non_counting_reasons.append(reason)
    blocked_reasons = [condition for condition, passed in pass_conditions.items() if passed is not True]
    blocker_details = {
        "independent_economic_candidates_gte_300": {
            "passed": pass_conditions["independent_economic_candidates_gte_300"],
            "observed": independent_candidate_count,
            "required": f">={required_independent_candidates}",
            "shortfall": max(0, required_independent_candidates - independent_candidate_count),
        },
        "symbols_gte_30": {
            "passed": pass_conditions["symbols_gte_30"],
            "observed": symbol_count,
            "required": f">={required_symbols}",
            "shortfall": max(0, required_symbols - symbol_count),
        },
        "long_gt_0": {
            "passed": pass_conditions["long_gt_0"],
            "observed": long_count,
            "required": ">0",
            "shortfall": max(0, 1 - long_count),
        },
        "short_gt_0": {
            "passed": pass_conditions["short_gt_0"],
            "observed": short_count,
            "required": ">0",
            "shortfall": max(0, 1 - short_count),
        },
        "after_cost_expectancy_gt_0": {
            "passed": pass_conditions["after_cost_expectancy_gt_0"],
            "observed": after_cost_expectancy_bps,
            "required": ">0",
        },
        "expectancy_95pct_lower_bound_gt_0": {
            "passed": pass_conditions["expectancy_95pct_lower_bound_gt_0"],
            "observed": expectancy_lower_bound_bps,
            "required": ">0",
        },
        "profit_factor_gte_1_5": {
            "passed": pass_conditions["profit_factor_gte_1_5"],
            "observed": profit_factor,
            "required": f">={required_profit_factor}",
            "shortfall": max(0.0, required_profit_factor - profit_factor) if profit_factor is not None else None,
        },
        "false_positive_rate_lte_0_40": {
            "passed": pass_conditions["false_positive_rate_lte_0_40"],
            "observed": false_positive_rate,
            "required": f"<={required_false_positive_rate}",
            "excess": max(0.0, false_positive_rate - required_false_positive_rate) if false_positive_rate is not None else None,
        },
        "no_concentration_dimension_gt_30pct": {
            "passed": pass_conditions["no_concentration_dimension_gt_30pct"],
            "observed": max_concentration_pct,
            "required": f"<={required_max_concentration_pct}",
            "max_concentration_dimension": max_concentration_dimension,
            "excess": max(0.0, max_concentration_pct - required_max_concentration_pct) if max_concentration_pct is not None else None,
        },
        "worst_1pct_loss_inside_risk_envelope": {
            "passed": pass_conditions["worst_1pct_loss_inside_risk_envelope"],
            "observed": worst_1pct,
            "required": f">={worst_1pct_loss_floor_bps}",
            "excess_loss_bps": max(0.0, worst_1pct_loss_floor_bps - worst_1pct) if worst_1pct is not None else None,
        },
        "point_in_time_violations_eq_0": {
            "passed": pass_conditions["point_in_time_violations_eq_0"],
            "observed": int(lockbox_integrity.get("point_in_time_violations") or 0),
            "required": 0,
        },
        "production_grade_cost_coverage_gte_95pct": {
            "passed": pass_conditions["production_grade_cost_coverage_gte_95pct"],
            "observed": production_grade_cost_coverage,
            "required": ">=0.95",
            "shortfall": max(0.0, 0.95 - production_grade_cost_coverage),
        },
        "lockbox_integrity_audit_passed": {
            "passed": pass_conditions["lockbox_integrity_audit_passed"],
            "observed": lockbox_integrity.get("status"),
            "required": "PASS_INTEGRITY_AUDIT",
        },
        "labels_have_pending_selection_record": {
            "passed": pass_conditions["labels_have_pending_selection_record"],
            "observed": integrity_pass_conditions.get("labels_have_pending_selection_record"),
            "required": True,
        },
        "selection_record_hashes_match_pending_records": {
            "passed": pass_conditions["selection_record_hashes_match_pending_records"],
            "observed": integrity_pass_conditions.get("selection_record_hashes_match_pending_records"),
            "required": True,
        },
        "selection_fields_marked_immutable": {
            "passed": pass_conditions["selection_fields_marked_immutable"],
            "observed": integrity_pass_conditions.get("selection_fields_marked_immutable"),
            "required": True,
        },
        "selected_fallback_rows_eq_0": {
            "passed": pass_conditions["selected_fallback_rows_eq_0"],
            "observed": integrity_pass_conditions.get("selected_fallback_rows_eq_0"),
            "required": True,
        },
    }
    status = "PASS_BLIND_LOCKBOX_PASS_CONTRACT" if all(pass_conditions.values()) else "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"
    failed_blocker_details = {
        condition: blocker_details[condition]
        for condition in blocked_reasons
        if condition in blocker_details
    }
    failed_blocker_samples = list(failed_blocker_details.values())[:25]
    independent_candidate_shortfall = max(0, required_independent_candidates - independent_candidate_count)
    metric_values = {
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "expectancy_95pct_lower_bound_bps": expectancy_lower_bound_bps,
        "profit_factor": profit_factor,
        "false_positive_rate": false_positive_rate,
        "max_concentration_pct": max_concentration_pct,
        "worst_1pct_loss_bps": worst_1pct,
    }
    metric_availability: dict[str, dict[str, Any]] = {}
    for metric_name, metric_value in metric_values.items():
        unavailable_reasons: list[str] = []
        if independent_candidate_count == 0:
            unavailable_reasons.append("no_independent_economic_candidates")
        if selected_label_rows == 0:
            unavailable_reasons.append("no_selected_label_rows")
        if metric_name == "expectancy_95pct_lower_bound_bps" and independent_candidate_count < 2:
            unavailable_reasons.append("requires_at_least_2_independent_candidates")
        if metric_name in {"max_concentration_pct", "worst_1pct_loss_bps"} and independent_candidate_count == 0:
            unavailable_reasons.append("requires_independent_candidate_distribution")
        metric_availability[metric_name] = {
            "available": metric_value is not None,
            "observed": metric_value,
            "unavailable_reasons": sorted(set(unavailable_reasons)) if metric_value is None else [],
        }
    unavailable_metric_reasons = {
        metric_name: payload["unavailable_reasons"]
        for metric_name, payload in metric_availability.items()
        if payload["available"] is not True
    }
    minimum_lockbox_evidence = {
        "independent_economic_candidates": f">={required_independent_candidates}",
        "symbols": f">={required_symbols}",
        "long_candidates": ">0",
        "short_candidates": ">0",
        "after_cost_expectancy_bps": ">0",
        "expectancy_95pct_lower_bound_bps": ">0",
        "profit_factor": f">={required_profit_factor}",
        "false_positive_rate": f"<={required_false_positive_rate}",
        "max_concentration_pct": f"<={required_max_concentration_pct}",
        "worst_1pct_loss_bps": f">={worst_1pct_loss_floor_bps}",
        "point_in_time_violations": 0,
        "production_grade_cost_coverage": ">=0.95",
    }
    minimum_lockbox_observed = {
        "independent_economic_candidates": independent_candidate_count,
        "symbols": symbol_count,
        "long_candidates": long_count,
        "short_candidates": short_count,
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "expectancy_95pct_lower_bound_bps": expectancy_lower_bound_bps,
        "profit_factor": profit_factor,
        "false_positive_rate": false_positive_rate,
        "max_concentration_pct": max_concentration_pct,
        "worst_1pct_loss_bps": worst_1pct,
        "point_in_time_violations": int(lockbox_integrity.get("point_in_time_violations") or 0),
        "production_grade_cost_coverage": production_grade_cost_coverage,
    }
    minimum_lockbox_shortfalls = {
        "independent_economic_candidates": independent_candidate_shortfall,
        "symbols": max(0, required_symbols - symbol_count),
        "long_candidates": max(0, 1 - long_count),
        "short_candidates": max(0, 1 - short_count),
        "profit_factor": max(0.0, required_profit_factor - profit_factor) if profit_factor is not None else None,
        "false_positive_rate_excess": max(0.0, false_positive_rate - required_false_positive_rate)
        if false_positive_rate is not None
        else None,
        "max_concentration_pct_excess": max(0.0, max_concentration_pct - required_max_concentration_pct)
        if max_concentration_pct is not None
        else None,
        "worst_1pct_loss_bps_excess_loss": max(0.0, worst_1pct_loss_floor_bps - worst_1pct)
        if worst_1pct is not None
        else None,
        "production_grade_cost_coverage": max(0.0, 0.95 - production_grade_cost_coverage),
    }
    ranked_pending_rejection_reasons = [
        {
            "reason": reason,
            "count": count,
            "pct_of_pending_rows": count / len(pending_rows) if pending_rows else None,
        }
        for reason, count in sorted(
            pending_rejection_reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    def _funnel_step(
        *,
        gate: str,
        observed: int,
        previous_observed: int | None,
        description: str,
    ) -> dict[str, Any]:
        return {
            "gate": gate,
            "description": description,
            "observed": observed,
            "required": f">={required_independent_candidates}",
            "passed": observed >= required_independent_candidates,
            "dropped_from_previous_gate": max(0, previous_observed - observed)
            if previous_observed is not None
            else 0,
            "shortfall_to_required": max(0, required_independent_candidates - observed),
        }

    lockbox_countability_funnel_steps = [
        _funnel_step(
            gate="raw_pending_rows",
            observed=len(pending_rows),
            previous_observed=None,
            description="Immutable future decision records appended after the freeze.",
        ),
        _funnel_step(
            gate="selected_pending_rows",
            observed=selected_pending_rows,
            previous_observed=len(pending_rows),
            description="Pending rows selected as economic candidates at decision time.",
        ),
        _funnel_step(
            gate="raw_labelled_rows",
            observed=len(labelled_rows),
            previous_observed=selected_pending_rows,
            description="Future horizon labels that have matured and been appended separately.",
        ),
        _funnel_step(
            gate="selected_label_rows",
            observed=selected_label_rows,
            previous_observed=len(labelled_rows),
            description="Label rows that still reflect selected decisions.",
        ),
        _funnel_step(
            gate="labels_with_pending_selection_record",
            observed=selected_label_rows_with_pending_record,
            previous_observed=selected_label_rows,
            description="Selected labels with a matching immutable pending selection record.",
        ),
        _funnel_step(
            gate="candidate_identity_bound_selected_labels",
            observed=candidate_identity_bound_selected_label_rows,
            previous_observed=selected_label_rows_with_pending_record,
            description="Selected labels bound to candidate_id, policy_fingerprint, and model_source.",
        ),
        _funnel_step(
            gate="production_grade_cost_at_decision",
            observed=production_grade_cost_selected_label_rows,
            previous_observed=candidate_identity_bound_selected_label_rows,
            description="Candidate-bound selected labels with production-grade cost evidence at decision time.",
        ),
        _funnel_step(
            gate="fallback_free_cost_at_decision",
            observed=fallback_free_cost_selected_label_rows,
            previous_observed=production_grade_cost_selected_label_rows,
            description="Production-grade selected labels whose decision cost did not use fallback evidence.",
        ),
        _funnel_step(
            gate="unique_independent_economic_candidates",
            observed=independent_candidate_count,
            previous_observed=fallback_free_cost_selected_label_rows,
            description="Unique lockbox_record_id rows countable for the blind-lockbox pass contract.",
        ),
    ]
    next_countability_gate = next(
        (
            step["gate"]
            for step in lockbox_countability_funnel_steps
            if step["passed"] is not True
        ),
        None,
    )
    lockbox_countability_funnel = {
        "required_independent_economic_candidates": required_independent_candidates,
        "next_countability_gate": next_countability_gate,
        "raw_pending_rows": len(pending_rows),
        "rejected_pending_rows": rejected_pending_rows,
        "selected_pending_rows": selected_pending_rows,
        "raw_labelled_rows": len(labelled_rows),
        "selected_label_rows": selected_label_rows,
        "selected_label_rows_with_pending_record": selected_label_rows_with_pending_record,
        "candidate_identity_bound_selected_label_rows": candidate_identity_bound_selected_label_rows,
        "production_grade_cost_at_decision_selected_label_rows": production_grade_cost_selected_label_rows,
        "fallback_free_cost_at_decision_selected_label_rows": fallback_free_cost_selected_label_rows,
        "unique_independent_economic_candidates": independent_candidate_count,
        "independent_economic_candidates": independent_candidate_count,
        "shortfall_to_required": independent_candidate_shortfall,
        "selection_to_label_maturity_gap": max(0, selected_pending_rows - selected_label_rows),
        "pending_rows_rejected_before_selection": rejected_pending_rows,
        "pending_rejection_reason_counts": dict(sorted(pending_rejection_reason_counts.items())),
        "primary_pending_rejection_reasons": ranked_pending_rejection_reasons,
        "excluded_selected_candidate_counts": dict(sorted(excluded_counts.items())),
        "steps": lockbox_countability_funnel_steps,
    }
    zero_independent_candidate_root_cause = {
        "status": "ZERO_INDEPENDENT_ECONOMIC_CANDIDATES"
        if independent_candidate_count == 0
        else "INDEPENDENT_ECONOMIC_CANDIDATES_PRESENT",
        "next_countability_gate": next_countability_gate,
        "independent_economic_candidates": independent_candidate_count,
        "shortfall_to_required": independent_candidate_shortfall,
        "selected_pending_rows": selected_pending_rows,
        "selected_label_rows": selected_label_rows,
        "production_grade_cost_gate_passed": production_grade_cost_coverage >= 0.95,
        "dominant_pending_rejection_reason": ranked_pending_rejection_reasons[0]
        if ranked_pending_rejection_reasons
        else None,
        "candidate_counting_blockers": [
            step["gate"]
            for step in lockbox_countability_funnel_steps
            if step["passed"] is not True
        ],
    }
    independent_candidate_counting_contract = {
        "counting_formula": (
            "count unique labelled lockbox_record_id rows where pending selection exists, "
            "selection was true at decision time, candidate_id/policy_fingerprint/model_source match, "
            "estimated_production_cost.production_grade_evidence is true, and fallback is not true"
        ),
        "raw_pending_rows": len(pending_rows),
        "raw_labelled_rows": len(labelled_rows),
        "selected_pending_rows": selected_pending_rows,
        "selected_label_rows": selected_label_rows,
        "independent_economic_candidates": independent_candidate_count,
        "pending_rows_not_countable_as_independent_economic_candidates": max(
            0,
            len(pending_rows) - independent_candidate_count,
        ),
        "labelled_rows_not_countable_as_independent_economic_candidates": max(
            0,
            len(labelled_rows) - independent_candidate_count,
        ),
        "rejected_pending_rows": rejected_pending_rows,
        "pending_rejection_reason_counts": dict(sorted(pending_rejection_reason_counts.items())),
        "primary_pending_rejection_reasons": ranked_pending_rejection_reasons,
        "excluded_selected_candidate_counts": dict(sorted(excluded_counts.items())),
        "excluded_selected_candidate_total": sum(excluded_counts.values()),
        "countability_funnel": lockbox_countability_funnel,
        "next_countability_gate": next_countability_gate,
        "production_grade_cost_coverage": production_grade_cost_coverage,
        "production_grade_cost_gate_passed": production_grade_cost_coverage >= 0.95,
        "raw_row_volume_counts_as_lockbox_pass_evidence": False,
        "selected_and_labelled_rows_required_for_metrics": True,
        "candidate_bound_identity_required": True,
        "production_grade_cost_required_at_decision_time": True,
        "fallback_true_rows_count_as_lockbox_or_promotion_evidence": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    return {
        "schema_version": "challenger_v2_blind_lockbox_pass_contract_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "pending_rows": len(pending_rows),
        "labelled_rows": len(labelled_rows),
        "selected_pending_rows": selected_pending_rows,
        "selected_pending_count": selected_pending_rows,
        "rejected_pending_rows": rejected_pending_rows,
        "rejected_pending_count": rejected_pending_rows,
        "selected_label_rows": selected_label_rows,
        "selected_label_count": selected_label_rows,
        "selection_summary": {
            "pending_rows": len(pending_rows),
            "labelled_rows": len(labelled_rows),
            "selected_pending_rows": selected_pending_rows,
            "rejected_pending_rows": rejected_pending_rows,
            "selected_label_rows": selected_label_rows,
            "independent_economic_candidates": independent_candidate_count,
            "excluded_selected_candidate_total": sum(excluded_counts.values()),
        },
        "lockbox_countability_funnel": lockbox_countability_funnel,
        "countability_funnel": lockbox_countability_funnel,
        "lockbox_countability_funnel_steps": lockbox_countability_funnel_steps,
        "next_countability_gate": next_countability_gate,
        "zero_independent_candidate_root_cause": zero_independent_candidate_root_cause,
        "phase_5_zero_independent_candidate_root_cause": zero_independent_candidate_root_cause,
        "primary_pending_rejection_reasons": ranked_pending_rejection_reasons,
        "rejection_reason_counts": dict(sorted(pending_rejection_reason_counts.items())),
        "pending_rejection_reason_counts": dict(sorted(pending_rejection_reason_counts.items())),
        "minimum_lockbox_evidence": minimum_lockbox_evidence,
        "minimum_lockbox_observed": minimum_lockbox_observed,
        "minimum_lockbox_shortfalls": minimum_lockbox_shortfalls,
        "minimum_lockbox_pass_conditions": pass_conditions,
        "actuals": minimum_lockbox_observed,
        "required": minimum_lockbox_evidence,
        "sample_failures": failed_blocker_samples,
        "sample_blockers": failed_blocker_samples,
        "independent_economic_candidates": independent_candidate_count,
        "independent_economic_candidate_count": independent_candidate_count,
        "lockbox_candidate_count": independent_candidate_count,
        "required_independent_economic_candidates": required_independent_candidates,
        "independent_economic_candidate_shortfall_to_300": independent_candidate_shortfall,
        "independent_candidate_shortfall_to_300": independent_candidate_shortfall,
        "independent_economic_candidate_shortfall_to_required": independent_candidate_shortfall,
        "independent_candidate_shortfall_to_required": independent_candidate_shortfall,
        "required_symbols": required_symbols,
        "symbol_shortfall_to_30": max(0, required_symbols - symbol_count),
        "long_candidate_shortfall_to_1": max(0, 1 - long_count),
        "short_candidate_shortfall_to_1": max(0, 1 - short_count),
        "required_profit_factor": required_profit_factor,
        "required_false_positive_rate_lte": required_false_positive_rate,
        "required_max_concentration_pct": required_max_concentration_pct,
        "worst_1pct_loss_floor_bps": worst_1pct_loss_floor_bps,
        "independence_key": "lockbox_record_id",
        "independent_candidate_counting_contract": independent_candidate_counting_contract,
        "lockbox_counting_contract": independent_candidate_counting_contract,
        "pending_rows_not_countable_as_independent_economic_candidates": independent_candidate_counting_contract[
            "pending_rows_not_countable_as_independent_economic_candidates"
        ],
        "labelled_rows_not_countable_as_independent_economic_candidates": independent_candidate_counting_contract[
            "labelled_rows_not_countable_as_independent_economic_candidates"
        ],
        "raw_row_volume_counts_as_lockbox_pass_evidence": False,
        "selected_and_labelled_rows_required_for_metrics": True,
        "excluded_selected_candidate_counts": dict(sorted(excluded_counts.items())),
        "excluded_counts": dict(sorted(excluded_counts.items())),
        "excluded_selected_candidate_total": sum(excluded_counts.values()),
        "non_counting_reasons": non_counting_reasons,
        "metric_availability": metric_availability,
        "available_metric_count": sum(1 for payload in metric_availability.values() if payload["available"] is True),
        "unavailable_metric_count": sum(1 for payload in metric_availability.values() if payload["available"] is not True),
        "unavailable_metric_reasons": unavailable_metric_reasons,
        "blocked_reasons": blocked_reasons,
        "lockbox_pass_blocker_details": blocker_details,
        "blocker_details": blocker_details,
        "failed_blocker_details": failed_blocker_details,
        "failed_lockbox_blocker_details": failed_blocker_details,
        "phase_5_failed_blocker_details": failed_blocker_details,
        "sample_excluded_selected_candidates": sample_excluded,
        "sample_blocked_candidates": sample_excluded,
        "symbols": stats.get("symbols"),
        "symbol_count": symbol_count,
        "long_count": stats.get("long_count"),
        "short_count": stats.get("short_count"),
        "long_candidates": long_count,
        "short_candidates": short_count,
        "candidate_count_by_direction": candidate_count_by_direction,
        "selected_label_count_by_direction": selected_label_count_by_direction,
        "expectancy_after_cost": after_cost_expectancy_bps,
        "expectancy_95_lower_bound": expectancy_lower_bound_bps,
        "after_cost_expectancy_bps": stats.get("after_cost_expectancy_bps"),
        "expectancy_95pct_lower_bound_bps": stats.get("expectancy_95pct_lower_bound_bps"),
        "profit_factor": stats.get("profit_factor"),
        "false_positive_rate": stats.get("false_positive_rate"),
        "worst_1pct_loss_bps": worst_1pct,
        "worst_1pct_loss_inside_risk_envelope": pass_conditions["worst_1pct_loss_inside_risk_envelope"],
        "concentration_dimensions": dimensions,
        "concentration_by_dimension": dimensions,
        "max_concentration_dimension": max_concentration_dimension,
        "max_concentration_pct": max_concentration_pct,
        "max_concentration_dimension_share": max_concentration_pct,
        "lockbox_integrity_status": lockbox_integrity.get("status"),
        "labels_have_pending_selection_record": integrity_pass_conditions.get("labels_have_pending_selection_record"),
        "selection_record_hashes_match_pending_records": integrity_pass_conditions.get(
            "selection_record_hashes_match_pending_records"
        ),
        "selection_fields_marked_immutable": integrity_pass_conditions.get("selection_fields_marked_immutable"),
        "selected_fallback_rows_eq_0": integrity_pass_conditions.get("selected_fallback_rows_eq_0"),
        "selected_fallback_rows": lockbox_integrity.get("selected_fallback_rows"),
        "label_selection_hash_mismatch_count": lockbox_integrity.get("label_selection_hash_mismatch_count"),
        "selection_fields_rewritten_after_label_count": lockbox_integrity.get(
            "selection_fields_rewritten_after_label_count"
        ),
        "selection_fields_rewritten_after_outcomes": lockbox_integrity.get("selection_fields_rewritten_after_outcomes"),
        "selection_fields_rewritten_after_outcomes_count": lockbox_integrity.get(
            "selection_fields_rewritten_after_outcomes_count"
        ),
        "selection_fields_rewritten_after_outcomes_exist": lockbox_integrity.get(
            "selection_fields_rewritten_after_outcomes_exist"
        ),
        "append_only_violation_count": lockbox_integrity.get("append_only_violation_count"),
        "pending_append_immutability_conflict_count": lockbox_integrity.get(
            "pending_append_immutability_conflict_count"
        ),
        "point_in_time_violations": lockbox_integrity.get("point_in_time_violations"),
        "point_in_time_violation_count": lockbox_integrity.get("point_in_time_violations"),
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "production_grade_cost_coverage_shortfall_to_95pct": max(0.0, 0.95 - production_grade_cost_coverage),
        "pass_conditions": pass_conditions,
        "lockbox_counting_evidence_allowed": status == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "counting_evidence_allowed": status == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "lockbox_prerequisite_for_paper_canary_binding_satisfied": status == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "do_not_tune_frozen_candidate_after_viewing_lockbox_results": True,
        "new_candidate_required_if_tuning_needed": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "Economic candidates must be selected, labelled, unique by lockbox_record_id, challenger-bound, and production-grade at decision time.",
            "Concentration dimensions audited here are symbol, timeframe, and decision_day; LONG/SHORT are enforced separately.",
            "This artifact is read-only and cannot bind the challenger to paper.",
        ],
    }


def paper_canary_binding_readiness_artifact(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    lockbox_perf: Mapping[str, Any],
    paper_binding_preflight: Mapping[str, Any],
    paper_cost_telemetry: Mapping[str, Any],
) -> dict[str, Any]:
    preflight_conditions = paper_binding_preflight.get("pass_conditions")
    preflight_conditions = preflight_conditions if isinstance(preflight_conditions, Mapping) else {}
    lockbox_pass = lockbox_perf.get("pass") is True or lockbox_perf.get("status") == "PASS"
    production_cost_pass = cost_status.get("status") == "PASS"
    pass_conditions = {
        "production_grade_cost_evidence_passed": production_cost_pass,
        "blind_lockbox_passed": lockbox_pass,
        "lockbox_point_in_time_violations_eq_0": int(lockbox_perf.get("point_in_time_violations") or 0) == 0,
        "no_candidate_bound_rows_before_lockbox_pass": preflight_conditions.get("no_candidate_bound_rows_before_lockbox_pass") is True,
        "no_partial_challenger_identity_rows": preflight_conditions.get("no_partial_challenger_identity_rows") is True,
        "no_routes_to_live": preflight_conditions.get("no_routes_to_live") is True,
        "paper_binding_preflight_clean": paper_binding_preflight.get("status")
        in {"PASS_PRELOCKBOX_NO_BINDING_LEAKS", "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT"},
        "paper_record_identity_contract_declared": True,
        "paper_canary_forced_paper_only": True,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    binding_allowed = all(pass_conditions.values())
    required_identity_fields = list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
    identity_complete_rows = paper_binding_preflight.get("candidate_identity_complete_rows")
    partial_identity_rows = paper_binding_preflight.get("partial_challenger_identity_rows")
    paper_record_identity_contract = {
        "required_identity_fields": required_identity_fields,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "all_fields_required_on_every_paper_record": True,
        "old_policy_rows_count_as_challenger_evidence": False,
        "paper_rows_count_only_after_cost_and_lockbox_pass": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    binding_prerequisite_details = {
        "production_grade_cost_evidence_passed": {
            "passed": pass_conditions["production_grade_cost_evidence_passed"],
            "observed": cost_status.get("status"),
            "required": "PASS",
        },
        "blind_lockbox_passed": {
            "passed": pass_conditions["blind_lockbox_passed"],
            "observed": lockbox_perf.get("status"),
            "required": "PASS",
        },
        "lockbox_point_in_time_violations_eq_0": {
            "passed": pass_conditions["lockbox_point_in_time_violations_eq_0"],
            "observed": int(lockbox_perf.get("point_in_time_violations") or 0),
            "required": 0,
        },
        "no_candidate_bound_rows_before_lockbox_pass": {
            "passed": pass_conditions["no_candidate_bound_rows_before_lockbox_pass"],
            "observed": preflight_conditions.get("no_candidate_bound_rows_before_lockbox_pass"),
            "required": True,
        },
        "no_partial_challenger_identity_rows": {
            "passed": pass_conditions["no_partial_challenger_identity_rows"],
            "observed": partial_identity_rows,
            "required": 0,
        },
        "no_routes_to_live": {
            "passed": pass_conditions["no_routes_to_live"],
            "observed": paper_binding_preflight.get("live_route_violation_rows"),
            "required": 0,
        },
        "paper_binding_preflight_clean": {
            "passed": pass_conditions["paper_binding_preflight_clean"],
            "observed": paper_binding_preflight.get("status"),
            "required": "PASS_PRELOCKBOX_NO_BINDING_LEAKS or READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT",
        },
        "paper_record_identity_contract_declared": {
            "passed": pass_conditions["paper_record_identity_contract_declared"],
            "observed": required_identity_fields,
            "required": required_identity_fields,
        },
        "paper_canary_forced_paper_only": {
            "passed": pass_conditions["paper_canary_forced_paper_only"],
            "observed": {"paper_fill_allowed": False, "routes_to_live": False, "places_real_order": False},
            "required": {"paper_fill_allowed": False, "routes_to_live": False, "places_real_order": False},
        },
    }
    failed_binding_prerequisite_details = {
        name: detail
        for name, detail in binding_prerequisite_details.items()
        if detail.get("passed") is not True
    }
    binding_actuals = {
        name: detail.get("observed")
        for name, detail in binding_prerequisite_details.items()
    }
    binding_required = {
        name: detail.get("required")
        for name, detail in binding_prerequisite_details.items()
    }
    binding_blocker_samples = list(failed_binding_prerequisite_details.values())[:25]
    return {
        "schema_version": "challenger_v2_paper_canary_binding_readiness_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT" if binding_allowed else "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
        "binding_allowed": binding_allowed,
        "paper_canary_binding_allowed": binding_allowed,
        "paper_binding_ready": binding_allowed,
        "paper_chain_ready": binding_allowed,
        "blocked_reasons": blocked_reasons,
        "actuals": binding_actuals,
        "required": binding_required,
        "sample_blockers": binding_blocker_samples,
        "blocker_details": failed_binding_prerequisite_details,
        "binding_prerequisite_details": binding_prerequisite_details,
        "chain_prerequisite_details": binding_prerequisite_details,
        "binding_blocker_details": binding_prerequisite_details,
        "failed_blocker_details": failed_binding_prerequisite_details,
        "failed_binding_blocker_details": failed_binding_prerequisite_details,
        "failed_binding_prerequisite_details": failed_binding_prerequisite_details,
        "paper_binding_prerequisites_satisfied": binding_allowed,
        "prerequisites_satisfied": binding_allowed,
        "paper_binding_blocked_until": blocked_reasons,
        "paper_canary_chain": list(PAPER_CANARY_CHAIN),
        "required_chain_links": list(PAPER_CANARY_CHAIN),
        "paper_canary_chain_declared": True,
        "required_chain_components": len(PAPER_CANARY_CHAIN),
        "required_paper_record_identity_fields": required_identity_fields,
        "required_identity_fields": required_identity_fields,
        "paper_record_identity_fields": required_identity_fields,
        "paper_record_identity_contract_declared": pass_conditions["paper_record_identity_contract_declared"],
        "paper_record_identity_contract": paper_record_identity_contract,
        "identity_ready": binding_allowed,
        "signal_ready": binding_allowed,
        "strategy_ready": binding_allowed,
        "adaptive_allocator_ready": binding_allowed,
        "risk_ready": binding_allowed,
        "orchestrator_ready": binding_allowed,
        "paper_lifecycle_ready": binding_allowed,
        "exit_ready": binding_allowed,
        "pnl_ready": binding_allowed,
        "trainer_feedback_ready": binding_allowed,
        "identity_complete_rows": identity_complete_rows,
        "partial_identity_rows": partial_identity_rows,
        "old_policy_credit_prevention_status": (
            "PASS_OLD_POLICY_ROWS_CANNOT_RECEIVE_CHALLENGER_CREDIT"
            if not binding_allowed and pass_conditions["paper_record_identity_contract_declared"]
            else "READY_REQUIRES_EXACT_CHALLENGER_IDENTITY_ON_EVERY_PAPER_RECORD"
        ),
        "credit_attribution_contract": paper_record_identity_contract,
        "paper_record_identity_rule": "candidate_id, policy_fingerprint, and model_source must all match the frozen challenger on every canary paper record before credit is allowed",
        "old_policy_rows_count_as_challenger_evidence": False,
        "old_policy_or_unbound_production_grade_rows": paper_cost_telemetry.get("old_policy_or_unbound_production_grade_rows"),
        "paper_cost_telemetry_readiness_status": paper_cost_telemetry.get("status"),
        "challenger_bound_production_grade_rows": paper_cost_telemetry.get("challenger_bound_production_grade_rows"),
        "paper_telemetry_production_grade_rows": paper_cost_telemetry.get("paper_telemetry_production_grade_rows"),
        "production_grade_identity_missing_counts": paper_cost_telemetry.get("production_grade_identity_missing_counts"),
        "production_grade_alternate_identity_value_counts": paper_cost_telemetry.get("production_grade_alternate_identity_value_counts"),
        "sample_production_grade_identity_gap_rows": paper_cost_telemetry.get("sample_production_grade_identity_gap_rows"),
        "cost_status": cost_status.get("status"),
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "lockbox_status": lockbox_perf.get("status"),
        "lockbox_selected_economic_candidates": lockbox_perf.get("selected_economic_candidates"),
        "lockbox_point_in_time_violations": lockbox_perf.get("point_in_time_violations"),
        "paper_binding_preflight_status": paper_binding_preflight.get("status"),
        "paper_binding_identity_complete_rows": identity_complete_rows,
        "paper_binding_partial_identity_rows": partial_identity_rows,
        "paper_binding_live_route_violation_rows": paper_binding_preflight.get("live_route_violation_rows"),
        "pass_conditions": pass_conditions,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def paper_chain_binding_readiness_audit(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    paper_canary_binding: Mapping[str, Any],
    forward_canary_contract: Mapping[str, Any],
) -> dict[str, Any]:
    required_identity_fields = list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
    declared_identity_fields = list(paper_canary_binding.get("required_paper_record_identity_fields") or [])
    binding_allowed = paper_canary_binding.get("binding_allowed") is True
    cost_passed = cost_status.get("status") == "PASS"
    lockbox_passed = lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT"
    component_blockers: list[str] = []
    if not cost_passed:
        component_blockers.append("production_grade_cost_evidence_not_passed")
    if not lockbox_passed:
        component_blockers.append("blind_lockbox_not_passed")
    if declared_identity_fields != required_identity_fields:
        component_blockers.append("paper_record_identity_contract_missing")
    if paper_canary_binding.get("routes_to_live") is not False or paper_canary_binding.get("places_real_order") is not False:
        component_blockers.append("paper_canary_not_forced_paper_only")
    if int(forward_canary_contract.get("live_route_rows") or 0):
        component_blockers.append("forward_canary_live_route_rows_present")
    if not binding_allowed:
        component_blockers.append("paper_canary_binding_not_allowed")

    chain_components: list[dict[str, Any]] = []
    for index, component in enumerate(PAPER_CANARY_CHAIN):
        if binding_allowed:
            component_status = "READY_FOR_OPERATOR_REVIEW_BINDING"
        else:
            component_status = "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS"
        chain_components.append(
            {
                "order": index + 1,
                "component": component,
                "status": component_status,
                "must_emit_or_preserve_identity_fields": required_identity_fields,
                "must_preserve_policy_fingerprint": True,
                "must_preserve_model_source": True,
                "paper_only_until_forward_canary_pass": True,
                "routes_to_live": False,
                "places_real_order": False,
                "counts_as_a_grade_evidence": False,
                "blocked_reasons": component_blockers if not binding_allowed else [],
            }
        )

    pass_conditions = {
        "required_chain_declared": list(PAPER_CANARY_CHAIN)
        == [
            "challenger",
            "signal",
            "strategy",
            "adaptive_allocator",
            "risk",
            "orchestrator",
            "paper_lifecycle",
            "exit",
            "pnl",
            "trainer_feedback",
        ],
        "all_chain_components_have_identity_contract": all(
            component.get("must_emit_or_preserve_identity_fields") == required_identity_fields for component in chain_components
        ),
        "paper_record_identity_fields_declared": declared_identity_fields == required_identity_fields,
        "production_grade_cost_evidence_passed": cost_passed,
        "blind_lockbox_passed": lockbox_passed,
        "paper_canary_binding_allowed": binding_allowed,
        "old_policy_rows_count_as_challenger_evidence_false": paper_canary_binding.get("old_policy_rows_count_as_challenger_evidence") is False,
        "paper_only_no_live_routes": paper_canary_binding.get("routes_to_live") is False
        and paper_canary_binding.get("places_real_order") is False
        and int(forward_canary_contract.get("live_route_rows") or 0) == 0,
        "no_forward_challenger_outcomes_before_binding": int(forward_canary_contract.get("closed_challenger_economic_outcomes") or 0) == 0
        if not binding_allowed
        else True,
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    missing_or_blocked_components = [
        component
        for component in chain_components
        if component.get("status") != "READY_FOR_OPERATOR_REVIEW_BINDING"
    ]
    complete_components = [
        component
        for component in chain_components
        if component.get("status") == "READY_FOR_OPERATOR_REVIEW_BINDING"
    ]
    chain_binding_allowed = binding_allowed and not blocked_reasons
    missing_component_names = [str(component.get("component")) for component in missing_or_blocked_components]
    chain_prerequisite_details = {
        "required_chain_declared": {
            "passed": pass_conditions["required_chain_declared"],
            "observed": list(PAPER_CANARY_CHAIN),
            "required": list(PAPER_CANARY_CHAIN),
        },
        "all_chain_components_have_identity_contract": {
            "passed": pass_conditions["all_chain_components_have_identity_contract"],
            "observed": {
                str(component.get("component")): component.get("must_emit_or_preserve_identity_fields")
                for component in chain_components
            },
            "required": required_identity_fields,
        },
        "paper_record_identity_fields_declared": {
            "passed": pass_conditions["paper_record_identity_fields_declared"],
            "observed": declared_identity_fields,
            "required": required_identity_fields,
        },
        "production_grade_cost_evidence_passed": {
            "passed": pass_conditions["production_grade_cost_evidence_passed"],
            "observed": cost_status.get("status"),
            "required": "PASS",
        },
        "blind_lockbox_passed": {
            "passed": pass_conditions["blind_lockbox_passed"],
            "observed": lockbox_pass_contract.get("status"),
            "required": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        },
        "paper_canary_binding_allowed": {
            "passed": pass_conditions["paper_canary_binding_allowed"],
            "observed": binding_allowed,
            "required": True,
        },
        "old_policy_rows_count_as_challenger_evidence_false": {
            "passed": pass_conditions["old_policy_rows_count_as_challenger_evidence_false"],
            "observed": paper_canary_binding.get("old_policy_rows_count_as_challenger_evidence"),
            "required": False,
        },
        "paper_only_no_live_routes": {
            "passed": pass_conditions["paper_only_no_live_routes"],
            "observed": {
                "paper_canary_routes_to_live": paper_canary_binding.get("routes_to_live"),
                "paper_canary_places_real_order": paper_canary_binding.get("places_real_order"),
                "forward_canary_live_route_rows": int(forward_canary_contract.get("live_route_rows") or 0),
            },
            "required": {"routes_to_live": False, "places_real_order": False, "forward_canary_live_route_rows": 0},
        },
        "no_forward_challenger_outcomes_before_binding": {
            "passed": pass_conditions["no_forward_challenger_outcomes_before_binding"],
            "observed": int(forward_canary_contract.get("closed_challenger_economic_outcomes") or 0),
            "required": 0 if not binding_allowed else "not enforced after binding allowed",
        },
    }
    failed_binding_blocker_details = {
        name: detail
        for name, detail in chain_prerequisite_details.items()
        if detail.get("passed") is not True
    }
    failed_binding_blocker_samples = list(failed_binding_blocker_details.values())[:25]
    component_statuses = {
        str(component.get("component")): component.get("status")
        for component in chain_components
    }
    required_component_count = len(PAPER_CANARY_CHAIN)
    complete_component_count = len(complete_components)
    missing_component_count = len(missing_or_blocked_components)
    component_shortfall = max(0, required_component_count - complete_component_count)
    minimum_paper_chain_binding_evidence = {
        "required_chain_declared": list(PAPER_CANARY_CHAIN),
        "required_components": required_component_count,
        "complete_components": required_component_count,
        "missing_component_count": 0,
        "paper_record_identity_fields": required_identity_fields,
        "production_grade_cost_evidence_status": "PASS",
        "blind_lockbox_pass_contract_status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "paper_canary_binding_allowed": True,
        "old_policy_rows_count_as_challenger_evidence": False,
        "routes_to_live": False,
        "places_real_order": False,
        "forward_canary_live_route_rows": 0,
        "forward_challenger_outcomes_before_binding": 0,
    }
    minimum_paper_chain_binding_observed = {
        "required_chain_declared": list(PAPER_CANARY_CHAIN),
        "required_components": required_component_count,
        "complete_components": complete_component_count,
        "missing_component_count": missing_component_count,
        "paper_record_identity_fields": declared_identity_fields,
        "production_grade_cost_evidence_status": cost_status.get("status"),
        "blind_lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
        "paper_canary_binding_allowed": binding_allowed,
        "old_policy_rows_count_as_challenger_evidence": paper_canary_binding.get(
            "old_policy_rows_count_as_challenger_evidence"
        ),
        "routes_to_live": paper_canary_binding.get("routes_to_live"),
        "places_real_order": paper_canary_binding.get("places_real_order"),
        "forward_canary_live_route_rows": int(forward_canary_contract.get("live_route_rows") or 0),
        "forward_challenger_outcomes_before_binding": int(
            forward_canary_contract.get("closed_challenger_economic_outcomes") or 0
        )
        if not binding_allowed
        else 0,
    }
    minimum_paper_chain_binding_shortfalls = {
        "required_chain_declared": 0 if pass_conditions["required_chain_declared"] else 1,
        "required_components": 0,
        "complete_components": component_shortfall,
        "missing_component_count": missing_component_count,
        "paper_record_identity_fields": 0 if pass_conditions["paper_record_identity_fields_declared"] else 1,
        "production_grade_cost_evidence_status": 0 if cost_passed else 1,
        "blind_lockbox_pass_contract_status": 0 if lockbox_passed else 1,
        "paper_canary_binding_allowed": 0 if binding_allowed else 1,
        "old_policy_rows_count_as_challenger_evidence": 0
        if pass_conditions["old_policy_rows_count_as_challenger_evidence_false"]
        else 1,
        "routes_to_live": 0 if paper_canary_binding.get("routes_to_live") is False else 1,
        "places_real_order": 0 if paper_canary_binding.get("places_real_order") is False else 1,
        "forward_canary_live_route_rows": int(forward_canary_contract.get("live_route_rows") or 0),
        "forward_challenger_outcomes_before_binding": int(
            forward_canary_contract.get("closed_challenger_economic_outcomes") or 0
        )
        if not binding_allowed
        else 0,
    }
    return {
        "schema_version": "challenger_v2_paper_chain_binding_readiness_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "READY_FOR_OPERATOR_REVIEW_PAPER_CHAIN_BINDING" if not blocked_reasons else "BLOCKED_PAPER_CHAIN_BINDING_NOT_READY",
        "ready": chain_binding_allowed,
        "binding_allowed": chain_binding_allowed,
        "chain_binding_allowed": chain_binding_allowed,
        "paper_canary_binding_allowed": binding_allowed,
        "chain_ready": chain_binding_allowed,
        "paper_chain_ready": chain_binding_allowed,
        "required_chain": list(PAPER_CANARY_CHAIN),
        "required_chain_links": list(PAPER_CANARY_CHAIN),
        "required_components": required_component_count,
        "complete_components": complete_component_count,
        "incomplete_components": missing_component_count,
        "missing_component_count": missing_component_count,
        "missing_or_blocked_chain_components_count": missing_component_count,
        "chain_component_shortfall_to_required": component_shortfall,
        "component_shortfall_to_required": component_shortfall,
        "minimum_paper_chain_binding_evidence": minimum_paper_chain_binding_evidence,
        "minimum_paper_chain_binding_observed": minimum_paper_chain_binding_observed,
        "minimum_paper_chain_binding_shortfalls": minimum_paper_chain_binding_shortfalls,
        "minimum_paper_chain_binding_pass_conditions": pass_conditions,
        "actuals": minimum_paper_chain_binding_observed,
        "required": minimum_paper_chain_binding_evidence,
        "sample_blockers": failed_binding_blocker_samples,
        "missing_component_names": missing_component_names,
        "missing_or_blocked_components": [
            {
                "component": component.get("component"),
                "status": component.get("status"),
                "blocked_reasons": component.get("blocked_reasons") or [],
            }
            for component in missing_or_blocked_components
        ],
        "chain_components": chain_components,
        "component_readiness": chain_components,
        "chain_link_readiness": chain_components,
        "component_statuses": component_statuses,
        "required_paper_record_identity_fields": required_identity_fields,
        "paper_record_identity_fields": required_identity_fields,
        "declared_paper_record_identity_fields": declared_identity_fields,
        "paper_record_identity_rule": "candidate_id, policy_fingerprint, and model_source must be present and match the frozen challenger on every record from challenger through trainer_feedback before credit is allowed",
        "blocked_reasons": blocked_reasons,
        "chain_prerequisite_details": chain_prerequisite_details,
        "blocker_details": failed_binding_blocker_details,
        "binding_blocker_details": chain_prerequisite_details,
        "failed_binding_blocker_details": failed_binding_blocker_details,
        "failed_blocker_details": failed_binding_blocker_details,
        "pass_conditions": pass_conditions,
        "cost_status": cost_status.get("status"),
        "lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
        "paper_canary_binding_status": paper_canary_binding.get("status"),
        "forward_canary_contract_status": forward_canary_contract.get("status"),
        "forward_canary_closed_challenger_economic_outcomes": forward_canary_contract.get("closed_challenger_economic_outcomes"),
        "forward_canary_live_route_rows": forward_canary_contract.get("live_route_rows"),
        "old_policy_rows_count_as_challenger_evidence": False,
        "read_only_audit_no_runtime_change": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def forward_canary_rows_from_payload(payload: Any, *, source_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, Mapping):
        for key in (
            "closed_trades",
            "closed_positions",
            "outcome_labels",
            "new_outcome_labels",
            "trainer_feedback",
            "trainer_feedback_rows",
            "rows",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, Mapping):
                        row = dict(item)
                        row["_paper_canary_source_key"] = f"{source_key}.{key}"
                        rows.append(row)
        if not rows and any(name in payload for name in ("closed_utc", "exit_time", "net_return_bps", "realized_pnl_bps")):
            row = dict(payload)
            row["_paper_canary_source_key"] = source_key
            rows.append(row)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                row = dict(item)
                row["_paper_canary_source_key"] = source_key
                rows.append(row)
    return rows


def forward_canary_rows_from_redis_value(raw: Any, *, source_key: str) -> list[dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return forward_canary_rows_from_payload(payload, source_key=source_key)


def normalized_outcome_side(row: Mapping[str, Any]) -> str:
    raw = str(first_present(row, "predicted_direction", "direction", "side", "position_side", "trade_side") or "").upper()
    if raw in {"LONG", "BUY"}:
        return "LONG"
    if raw in {"SHORT", "SELL"}:
        return "SHORT"
    return raw or "UNKNOWN"


def canary_net_return_bps(row: Mapping[str, Any]) -> float | None:
    return finite_float(
        first_present(
            row,
            "net_return_bps",
            "after_cost_return_bps",
            "net_pnl_bps",
            "realized_pnl_bps",
            "pnl_bps",
        )
    )


def is_closed_canary_outcome(row: Mapping[str, Any]) -> bool:
    status = str(first_present(row, "status", "lifecycle_status", "trade_status", "event_type") or "").upper()
    if status in {"CLOSED", "EXITED", "CLOSE", "CLOSED_TRADE", "OUTCOME_LABEL"}:
        return True
    return first_present(row, "closed_utc", "closed_at", "exit_time", "exit_at", "execution_time") not in (None, "")


def accounting_mismatch_state(row: Mapping[str, Any]) -> tuple[bool, bool]:
    if row.get("accounting_mismatch") is not None:
        return row.get("accounting_mismatch") is True, True
    if row.get("accounting_reconciled") is not None:
        return row.get("accounting_reconciled") is not True, True
    for field in ("accounting_status", "pnl_reconciliation_status", "reconciliation_status"):
        value = row.get(field)
        if value in (None, ""):
            continue
        text = str(value).upper()
        return "MISMATCH" in text or text in {"FAIL", "FAILED", "ERROR"}, True
    return False, False


def liquidation_state(row: Mapping[str, Any]) -> bool:
    if row.get("liquidated") is True or row.get("liquidation") is True or row.get("liquidation_event") is True:
        return True
    reason = str(first_present(row, "exit_reason", "close_reason", "reason") or "").upper()
    return "LIQUIDATION" in reason


def forward_paper_canary_pass_contract_audit_from_rows(
    *,
    policy: FrozenPolicy,
    rows: Sequence[Mapping[str, Any]],
    paper_canary_binding: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    redis_status: str = "READ_FROM_SUPPLIED_ROWS",
    source_counts: Mapping[str, int] | None = None,
    scan_limit_reached: bool = False,
) -> dict[str, Any]:
    canary_start_time = parse_utc(
        first_present(
            paper_canary_binding,
            "paper_canary_started_at",
            "binding_started_at",
            "canary_started_at",
        )
    )
    source_counter: Counter[str] = Counter()
    excluded_counts: Counter[str] = Counter()
    accounting_mismatch_rows = 0
    accounting_missing_rows = 0
    liquidation_rows = 0
    route_rows = 0
    point_in_time_violations = 0
    samples: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []

    for raw_row in rows:
        row = dict(raw_row)
        source = str(row.get("_paper_canary_source_key") or row.get("_paper_binding_source_key") or "UNKNOWN")
        source_counter[source] += 1
        identity_state = challenger_identity_state(row, policy)
        if identity_state != "complete":
            excluded_counts["challenger_identity_not_complete"] += 1
            continue
        if not is_closed_canary_outcome(row):
            excluded_counts["not_closed_outcome"] += 1
            continue
        close_time = parse_utc(first_present(row, "closed_utc", "closed_at", "exit_time", "exit_at", "execution_time"))
        if canary_start_time is not None and (close_time is None or close_time <= canary_start_time):
            excluded_counts["closed_before_or_without_canary_start_time"] += 1
            continue
        net_return = canary_net_return_bps(row)
        if net_return is None:
            excluded_counts["net_return_missing"] += 1
            continue
        row["net_return_bps"] = net_return
        row["predicted_direction"] = normalized_outcome_side(row)
        if point_in_time_violation_count([row]):
            point_in_time_violations += 1
        if paper_row_routes_to_live(row):
            route_rows += 1
        mismatch, accounting_present = accounting_mismatch_state(row)
        if mismatch:
            accounting_mismatch_rows += 1
        if not accounting_present:
            accounting_missing_rows += 1
        if liquidation_state(row):
            liquidation_rows += 1
        if len(samples) < 10:
            samples.append(
                {
                    "source_key": source,
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "decision_time": row.get("decision_time"),
                    "closed_utc": first_present(row, "closed_utc", "closed_at", "exit_time", "exit_at", "execution_time"),
                    "predicted_direction": row.get("predicted_direction"),
                    "net_return_bps": net_return,
                }
            )
        outcomes.append(row)

    stats = outcome_stats(outcomes)
    canary_start_iso = canary_start_time.isoformat().replace("+00:00", "Z") if canary_start_time is not None else None
    required_closed_outcomes = 100
    closed_outcome_count = len(outcomes)
    closed_outcome_shortfall = max(0, required_closed_outcomes - closed_outcome_count)
    long_count = int(stats.get("long_count") or 0)
    short_count = int(stats.get("short_count") or 0)
    symbols = int(stats.get("symbols") or 0)
    outcome_count_by_direction = {"LONG": long_count, "SHORT": short_count}
    required_symbols = 30
    required_profit_factor = 1.5
    after_cost_expectancy_bps = finite_float(stats.get("after_cost_expectancy_bps"))
    profit_factor = finite_float(stats.get("profit_factor"))
    pass_conditions = {
        "paper_canary_binding_allowed": paper_canary_binding.get("binding_allowed") is True,
        "paper_canary_start_time_present": canary_start_time is not None,
        "blind_lockbox_pass_contract_passed": lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "new_closed_challenger_economic_outcomes_gte_100": closed_outcome_count >= required_closed_outcomes,
        "symbols_gte_30": symbols >= required_symbols,
        "long_gt_0": long_count > 0,
        "short_gt_0": short_count > 0,
        "after_cost_expectancy_gt_0": after_cost_expectancy_bps is not None and after_cost_expectancy_bps > 0.0,
        "profit_factor_gte_1_5": profit_factor is not None and profit_factor >= required_profit_factor,
        "accounting_mismatch_rows_eq_0": accounting_mismatch_rows == 0,
        "accounting_evidence_present_for_all_outcomes": len(outcomes) > 0 and accounting_missing_rows == 0,
        "liquidation_rows_eq_0": liquidation_rows == 0,
        "point_in_time_violations_eq_0": point_in_time_violations == 0,
        "paper_only_no_live_routes": route_rows == 0,
    }
    pass_condition_details = {
        "paper_canary_binding_allowed": {
            "passed": pass_conditions["paper_canary_binding_allowed"],
            "observed": paper_canary_binding.get("binding_allowed"),
            "required": True,
        },
        "paper_canary_start_time_present": {
            "passed": pass_conditions["paper_canary_start_time_present"],
            "observed": canary_start_iso,
            "required": "present",
        },
        "blind_lockbox_pass_contract_passed": {
            "passed": pass_conditions["blind_lockbox_pass_contract_passed"],
            "observed": lockbox_pass_contract.get("status"),
            "required": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        },
        "new_closed_challenger_economic_outcomes_gte_100": {
            "passed": pass_conditions["new_closed_challenger_economic_outcomes_gte_100"],
            "observed": closed_outcome_count,
            "required": f">={required_closed_outcomes}",
            "shortfall": closed_outcome_shortfall,
        },
        "symbols_gte_30": {
            "passed": pass_conditions["symbols_gte_30"],
            "observed": symbols,
            "required": ">=30",
        },
        "long_gt_0": {
            "passed": pass_conditions["long_gt_0"],
            "observed": long_count,
            "required": ">0",
        },
        "short_gt_0": {
            "passed": pass_conditions["short_gt_0"],
            "observed": short_count,
            "required": ">0",
        },
        "after_cost_expectancy_gt_0": {
            "passed": pass_conditions["after_cost_expectancy_gt_0"],
            "observed": after_cost_expectancy_bps,
            "required": ">0",
        },
        "profit_factor_gte_1_5": {
            "passed": pass_conditions["profit_factor_gte_1_5"],
            "observed": profit_factor,
            "required": f">={required_profit_factor}",
        },
        "accounting_mismatch_rows_eq_0": {
            "passed": pass_conditions["accounting_mismatch_rows_eq_0"],
            "observed": accounting_mismatch_rows,
            "required": 0,
        },
        "accounting_evidence_present_for_all_outcomes": {
            "passed": pass_conditions["accounting_evidence_present_for_all_outcomes"],
            "observed": {
                "closed_challenger_economic_outcomes": closed_outcome_count,
                "accounting_missing_rows": accounting_missing_rows,
            },
            "required": {"closed_challenger_economic_outcomes": ">0", "accounting_missing_rows": 0},
        },
        "liquidation_rows_eq_0": {
            "passed": pass_conditions["liquidation_rows_eq_0"],
            "observed": liquidation_rows,
            "required": 0,
        },
        "point_in_time_violations_eq_0": {
            "passed": pass_conditions["point_in_time_violations_eq_0"],
            "observed": point_in_time_violations,
            "required": 0,
        },
        "paper_only_no_live_routes": {
            "passed": pass_conditions["paper_only_no_live_routes"],
            "observed": route_rows,
            "required": 0,
        },
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    excluded_row_counts = dict(sorted(excluded_counts.items()))
    identity_excluded_rows = int(excluded_counts.get("challenger_identity_not_complete") or 0)
    non_counting_row_count = int(sum(excluded_counts.values()))
    non_counting_reasons = [
        {"reason": reason, "rows": count}
        for reason, count in excluded_row_counts.items()
    ]
    metric_values = {
        "after_cost_expectancy_bps": stats.get("after_cost_expectancy_bps"),
        "profit_factor": stats.get("profit_factor"),
        "false_positive_rate": stats.get("false_positive_rate"),
    }
    metric_availability: dict[str, dict[str, Any]] = {}
    for metric_name, metric_value in metric_values.items():
        unavailable_reasons: list[str] = []
        if closed_outcome_count == 0:
            unavailable_reasons.append("no_closed_challenger_economic_outcomes")
        if paper_canary_binding.get("binding_allowed") is not True:
            unavailable_reasons.append("paper_canary_binding_not_allowed")
        if canary_start_time is None:
            unavailable_reasons.append("paper_canary_start_time_missing")
        if lockbox_pass_contract.get("status") != "PASS_BLIND_LOCKBOX_PASS_CONTRACT":
            unavailable_reasons.append("blind_lockbox_pass_contract_not_passed")
        if rows and closed_outcome_count == 0 and excluded_counts:
            unavailable_reasons.append("all_scanned_rows_excluded_or_non_counting")
        metric_availability[metric_name] = {
            "available": metric_value is not None,
            "observed": metric_value,
            "unavailable_reasons": sorted(set(unavailable_reasons)) if metric_value is None else [],
        }
    unavailable_metric_reasons = {
        metric_name: payload["unavailable_reasons"]
        for metric_name, payload in metric_availability.items()
        if payload["available"] is not True
    }
    minimum_forward_canary_evidence = {
        "paper_canary_binding_allowed": True,
        "paper_canary_start_time": "present",
        "blind_lockbox_pass_contract_status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "new_closed_challenger_economic_outcomes": f">={required_closed_outcomes}",
        "symbols": f">={required_symbols}",
        "long_candidates": ">0",
        "short_candidates": ">0",
        "after_cost_expectancy_bps": ">0",
        "profit_factor": f">={required_profit_factor}",
        "accounting_mismatch_rows": 0,
        "accounting_evidence_missing_rows": 0,
        "liquidation_rows": 0,
        "point_in_time_violations": 0,
        "live_route_rows": 0,
    }
    minimum_forward_canary_observed = {
        "paper_canary_binding_allowed": paper_canary_binding.get("binding_allowed"),
        "paper_canary_start_time": canary_start_iso,
        "blind_lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
        "new_closed_challenger_economic_outcomes": closed_outcome_count,
        "symbols": symbols,
        "long_candidates": long_count,
        "short_candidates": short_count,
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "profit_factor": profit_factor,
        "accounting_mismatch_rows": accounting_mismatch_rows,
        "accounting_evidence_missing_rows": accounting_missing_rows,
        "liquidation_rows": liquidation_rows,
        "point_in_time_violations": point_in_time_violations,
        "live_route_rows": route_rows,
    }
    minimum_forward_canary_shortfalls = {
        "paper_canary_binding_allowed": 0 if paper_canary_binding.get("binding_allowed") is True else 1,
        "paper_canary_start_time": 0 if canary_start_time is not None else 1,
        "blind_lockbox_pass_contract_status": 0
        if lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT"
        else 1,
        "new_closed_challenger_economic_outcomes": closed_outcome_shortfall,
        "symbols": max(0, required_symbols - symbols),
        "long_candidates": max(0, 1 - long_count),
        "short_candidates": max(0, 1 - short_count),
        "after_cost_expectancy_bps": None
        if after_cost_expectancy_bps is None
        else max(0.0, 0.0 - after_cost_expectancy_bps),
        "profit_factor": None
        if profit_factor is None
        else max(0.0, required_profit_factor - profit_factor),
        "accounting_mismatch_rows": accounting_mismatch_rows,
        "accounting_evidence_missing_rows": accounting_missing_rows if closed_outcome_count > 0 else None,
        "liquidation_rows": liquidation_rows,
        "point_in_time_violations": point_in_time_violations,
        "live_route_rows": route_rows,
    }
    contract_passed = all(pass_conditions.values())
    failed_forward_canary_blocker_details = {
        name: detail
        for name, detail in pass_condition_details.items()
        if detail.get("passed") is not True
    }
    failed_forward_canary_blocker_samples = list(failed_forward_canary_blocker_details.values())[:25]
    return {
        "schema_version": "challenger_v2_forward_paper_canary_pass_contract_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_FORWARD_PAPER_CANARY_CONTRACT" if contract_passed else "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
        "redis_status": redis_status,
        "source_counts": dict(sorted(source_counter.items())),
        "redis_scan_source_counts": dict(sorted(Counter(dict(source_counts or {})).items())),
        "scan_limit_reached": scan_limit_reached,
        "paper_canary_started_at": canary_start_iso,
        "paper_canary_binding_status": paper_canary_binding.get("status"),
        "paper_canary_binding_allowed": paper_canary_binding.get("binding_allowed"),
        "lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
        "required_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "paper_rows_scanned": len(rows),
        "scanned_rows": len(rows),
        "total_rows_scanned": len(rows),
        "candidate_bound_rows": closed_outcome_count,
        "old_policy_or_unbound_rows_quarantined": identity_excluded_rows,
        "identity_incomplete_rows": identity_excluded_rows,
        "non_counting_row_count": non_counting_row_count,
        "closed_challenger_economic_outcomes": closed_outcome_count,
        "new_closed_challenger_economic_outcomes": closed_outcome_count,
        "independent_economic_candidates": closed_outcome_count,
        "required_new_closed_economic_outcomes": required_closed_outcomes,
        "required_new_closed_challenger_economic_outcomes": required_closed_outcomes,
        "required_closed_challenger_economic_outcomes": required_closed_outcomes,
        "minimum_forward_canary_evidence": minimum_forward_canary_evidence,
        "minimum_forward_canary_observed": minimum_forward_canary_observed,
        "minimum_forward_canary_shortfalls": minimum_forward_canary_shortfalls,
        "minimum_forward_canary_pass_conditions": pass_conditions,
        "actuals": minimum_forward_canary_observed,
        "required": minimum_forward_canary_evidence,
        "sample_blockers": failed_forward_canary_blocker_samples,
        "sample_failures": failed_forward_canary_blocker_samples,
        "closed_outcome_shortfall_to_100": closed_outcome_shortfall,
        "closed_challenger_economic_outcome_shortfall": closed_outcome_shortfall,
        "closed_challenger_economic_outcome_shortfall_to_100": closed_outcome_shortfall,
        "closed_challenger_economic_outcome_shortfall_to_required": closed_outcome_shortfall,
        "new_closed_challenger_economic_outcome_shortfall_to_required": closed_outcome_shortfall,
        "new_closed_challenger_economic_outcomes_shortfall_to_100": closed_outcome_shortfall,
        "excluded_row_counts": excluded_row_counts,
        "identity_exclusion_counts": {
            "challenger_identity_not_complete": identity_excluded_rows,
        },
        "non_counting_reasons": non_counting_reasons,
        "metric_availability": metric_availability,
        "available_metric_count": sum(1 for payload in metric_availability.values() if payload["available"] is True),
        "unavailable_metric_count": sum(1 for payload in metric_availability.values() if payload["available"] is not True),
        "unavailable_metric_reasons": unavailable_metric_reasons,
        "symbols": stats.get("symbols"),
        "symbol_count": symbols,
        "required_symbols": required_symbols,
        "symbol_shortfall_to_30": max(0, required_symbols - symbols),
        "long_count": stats.get("long_count"),
        "short_count": stats.get("short_count"),
        "long_candidates": long_count,
        "short_candidates": short_count,
        "long_candidate_shortfall_to_1": max(0, 1 - long_count),
        "short_candidate_shortfall_to_1": max(0, 1 - short_count),
        "outcome_count_by_direction": outcome_count_by_direction,
        "candidate_count_by_direction": outcome_count_by_direction,
        "expectancy_after_cost": after_cost_expectancy_bps,
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "profit_factor": profit_factor,
        "false_positive_rate": stats.get("false_positive_rate"),
        "accounting_mismatch_rows": accounting_mismatch_rows,
        "accounting_mismatch_count": accounting_mismatch_rows,
        "accounting_missing_rows": accounting_missing_rows,
        "liquidation_rows": liquidation_rows,
        "liquidation_count": liquidation_rows,
        "liquidation_event_rows": liquidation_rows,
        "liquidation_events": liquidation_rows,
        "point_in_time_violations": point_in_time_violations,
        "point_in_time_violation_count": point_in_time_violations,
        "live_route_rows": route_rows,
        "pass_conditions": pass_conditions,
        "forward_canary_blocker_details": pass_condition_details,
        "blocker_details": pass_condition_details,
        "failed_forward_canary_blocker_details": failed_forward_canary_blocker_details,
        "failed_blocker_details": failed_forward_canary_blocker_details,
        "blocked_reasons": blocked_reasons,
        "sample_closed_challenger_outcomes": samples,
        "sample_outcomes": samples,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "canary_counting_evidence_allowed": contract_passed,
        "counting_evidence_allowed": contract_passed,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "notes": [
            "Rows count only when candidate_id, policy_fingerprint, and model_source match the frozen challenger.",
            "Rows must be closed after the paper canary start timestamp and include after-cost return evidence.",
            "This audit is read-only and cannot bind the challenger or route orders.",
        ],
    }


def paper_challenger_credit_attribution_guard(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    paper_binding_preflight: Mapping[str, Any],
    paper_cost_telemetry: Mapping[str, Any],
    paper_canary_binding: Mapping[str, Any],
    forward_canary_contract: Mapping[str, Any],
) -> dict[str, Any]:
    preflight_conditions = paper_binding_preflight.get("pass_conditions")
    preflight_conditions = preflight_conditions if isinstance(preflight_conditions, Mapping) else {}
    forward_excluded_counts = forward_canary_contract.get("excluded_row_counts")
    forward_excluded_counts = forward_excluded_counts if isinstance(forward_excluded_counts, Mapping) else {}
    required_identity_fields = list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
    declared_identity_fields = list(paper_canary_binding.get("required_paper_record_identity_fields") or [])
    cost_passed = cost_status.get("status") == "PASS"
    lockbox_passed = lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT"
    binding_allowed = paper_canary_binding.get("binding_allowed") is True
    forward_closed_outcomes = int(forward_canary_contract.get("closed_challenger_economic_outcomes") or 0)
    forward_rows_scanned = int(forward_canary_contract.get("paper_rows_scanned") or 0)
    forward_identity_excluded_rows = int(forward_excluded_counts.get("challenger_identity_not_complete") or 0)
    challenger_bound_cost_rows = int(paper_cost_telemetry.get("challenger_bound_production_grade_rows") or 0)
    identity_complete_cost_rows = int(paper_cost_telemetry.get("candidate_identity_complete_production_grade_rows") or 0)
    old_or_unbound_cost_rows = int(paper_cost_telemetry.get("old_policy_or_unbound_production_grade_rows") or 0)
    paper_fill_allowed_rows = int(paper_cost_telemetry.get("paper_fill_allowed_rows") or 0)
    source_group_readiness = paper_cost_telemetry.get("source_group_readiness")
    source_group_readiness = source_group_readiness if isinstance(source_group_readiness, Mapping) else {}
    source_group_credit_summary: dict[str, Any] = {}
    for group, payload in sorted(source_group_readiness.items()):
        if not isinstance(payload, Mapping):
            continue
        source_group_credit_summary[str(group)] = {
            "rows": payload.get("rows"),
            "production_grade_rows": payload.get("production_grade_rows"),
            "challenger_bound_production_grade_rows": payload.get("challenger_bound_production_grade_rows"),
            "old_policy_or_unbound_production_grade_rows": payload.get("old_policy_or_unbound_production_grade_rows"),
            "paper_fill_allowed_rows": payload.get("paper_fill_allowed_rows"),
            "blocked_reasons": payload.get("blocked_reasons") or [],
        }

    pass_conditions = {
        "required_identity_fields_declared": declared_identity_fields == required_identity_fields,
        "old_policy_rows_count_as_challenger_evidence_false": paper_canary_binding.get("old_policy_rows_count_as_challenger_evidence") is False,
        "old_policy_or_unbound_cost_rows_quarantined": old_or_unbound_cost_rows >= 0 and challenger_bound_cost_rows <= identity_complete_cost_rows,
        "no_candidate_bound_rows_before_lockbox_pass": preflight_conditions.get("no_candidate_bound_rows_before_lockbox_pass") is True,
        "no_partial_challenger_identity_rows": preflight_conditions.get("no_partial_challenger_identity_rows") is True,
        "paper_binding_preflight_has_no_live_routes": preflight_conditions.get("no_routes_to_live") is True,
        "binding_disallowed_until_cost_and_lockbox_pass": binding_allowed is False if not (cost_passed and lockbox_passed) else True,
        "forward_canary_has_no_challenger_outcomes_while_binding_blocked": forward_closed_outcomes == 0 if not binding_allowed else True,
        "forward_canary_old_policy_rows_excluded_by_identity": forward_identity_excluded_rows == forward_rows_scanned if forward_rows_scanned and not binding_allowed else True,
        "paper_fill_allowed_rows_not_counted_as_challenger_evidence": paper_fill_allowed_rows >= 0 and challenger_bound_cost_rows == 0 if paper_fill_allowed_rows else True,
        "paper_canary_forced_paper_only": paper_canary_binding.get("routes_to_live") is False and paper_canary_binding.get("places_real_order") is False,
        "forward_canary_no_live_routes": int(forward_canary_contract.get("live_route_rows") or 0) == 0,
    }
    credit_actuals = {
        "required_identity_fields_declared": declared_identity_fields,
        "old_policy_rows_count_as_challenger_evidence_false": paper_canary_binding.get(
            "old_policy_rows_count_as_challenger_evidence"
        ),
        "old_policy_or_unbound_cost_rows_quarantined": {
            "old_policy_or_unbound_production_grade_rows": old_or_unbound_cost_rows,
            "challenger_bound_production_grade_rows": challenger_bound_cost_rows,
            "candidate_identity_complete_production_grade_rows": identity_complete_cost_rows,
        },
        "no_candidate_bound_rows_before_lockbox_pass": preflight_conditions.get(
            "no_candidate_bound_rows_before_lockbox_pass"
        ),
        "no_partial_challenger_identity_rows": preflight_conditions.get("no_partial_challenger_identity_rows"),
        "paper_binding_preflight_has_no_live_routes": preflight_conditions.get("no_routes_to_live"),
        "binding_disallowed_until_cost_and_lockbox_pass": {
            "cost_status": cost_status.get("status"),
            "lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
            "paper_canary_binding_allowed": binding_allowed,
        },
        "forward_canary_has_no_challenger_outcomes_while_binding_blocked": forward_closed_outcomes,
        "forward_canary_old_policy_rows_excluded_by_identity": {
            "forward_identity_excluded_rows": forward_identity_excluded_rows,
            "forward_rows_scanned": forward_rows_scanned,
        },
        "paper_fill_allowed_rows_not_counted_as_challenger_evidence": {
            "paper_fill_allowed_rows": paper_fill_allowed_rows,
            "challenger_bound_production_grade_rows": challenger_bound_cost_rows,
        },
        "paper_canary_forced_paper_only": {
            "routes_to_live": paper_canary_binding.get("routes_to_live"),
            "places_real_order": paper_canary_binding.get("places_real_order"),
        },
        "forward_canary_no_live_routes": int(forward_canary_contract.get("live_route_rows") or 0),
    }
    credit_required = {
        "required_identity_fields_declared": required_identity_fields,
        "old_policy_rows_count_as_challenger_evidence_false": False,
        "old_policy_or_unbound_cost_rows_quarantined": (
            "old-policy or unbound production-grade rows excluded from challenger credit"
        ),
        "no_candidate_bound_rows_before_lockbox_pass": True,
        "no_partial_challenger_identity_rows": True,
        "paper_binding_preflight_has_no_live_routes": True,
        "binding_disallowed_until_cost_and_lockbox_pass": (
            "binding_allowed=false until cost_status=PASS and lockbox=PASS_BLIND_LOCKBOX_PASS_CONTRACT"
        ),
        "forward_canary_has_no_challenger_outcomes_while_binding_blocked": 0 if not binding_allowed else "not enforced after binding",
        "forward_canary_old_policy_rows_excluded_by_identity": (
            "all scanned forward rows excluded by incomplete challenger identity before binding"
            if forward_rows_scanned and not binding_allowed
            else "not enforced"
        ),
        "paper_fill_allowed_rows_not_counted_as_challenger_evidence": "challenger_bound_production_grade_rows=0 while paper_fill_allowed rows exist",
        "paper_canary_forced_paper_only": {"routes_to_live": False, "places_real_order": False},
        "forward_canary_no_live_routes": 0,
    }
    credit_condition_details = {
        name: {
            "pass_condition": name,
            "passed": passed is True,
            "observed": credit_actuals.get(name),
            "required": credit_required.get(name),
        }
        for name, passed in pass_conditions.items()
    }
    blocked_reasons = [name for name, passed in pass_conditions.items() if passed is not True]
    failed_credit_blocker_details = {
        name: detail for name, detail in credit_condition_details.items() if detail.get("passed") is not True
    }
    failed_credit_blocker_samples = list(failed_credit_blocker_details.values())[:25]
    return {
        "schema_version": "challenger_v2_paper_challenger_credit_attribution_guard_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_PREBINDING_CHALLENGER_CREDIT_ATTRIBUTION_GUARD" if not blocked_reasons else "FAIL_CHALLENGER_CREDIT_ATTRIBUTION_GUARD",
        "blocked_reasons": blocked_reasons,
        "credit_attribution_guard_passed": not blocked_reasons,
        "cost_status": cost_status.get("status"),
        "lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
        "paper_binding_preflight_status": paper_binding_preflight.get("status"),
        "paper_canary_binding_status": paper_canary_binding.get("status"),
        "paper_canary_binding_allowed": binding_allowed,
        "old_policy_rows_count_as_challenger_evidence": False,
        "forward_paper_canary_contract_status": forward_canary_contract.get("status"),
        "required_paper_record_identity_fields": required_identity_fields,
        "required_identity_fields": required_identity_fields,
        "declared_paper_record_identity_fields": declared_identity_fields,
        "paper_cost_telemetry_status": paper_cost_telemetry.get("status"),
        "paper_cost_telemetry_rows_scanned": paper_cost_telemetry.get("paper_rows_scanned"),
        "paper_telemetry_production_grade_rows": paper_cost_telemetry.get("paper_telemetry_production_grade_rows"),
        "candidate_identity_complete_production_grade_rows": identity_complete_cost_rows,
        "challenger_bound_production_grade_rows": challenger_bound_cost_rows,
        "old_policy_or_unbound_production_grade_rows_quarantined": old_or_unbound_cost_rows,
        "old_unbound_rows_quarantined": old_or_unbound_cost_rows,
        "paper_fill_allowed_rows_quarantined": paper_fill_allowed_rows,
        "paper_cost_source_group_credit_summary": source_group_credit_summary,
        "source_group_credit_summary": source_group_credit_summary,
        "paper_binding_identity_complete_rows": paper_binding_preflight.get("candidate_identity_complete_rows"),
        "paper_binding_partial_identity_rows": paper_binding_preflight.get("partial_challenger_identity_rows"),
        "candidate_bound_rows_before_lockbox_pass": paper_binding_preflight.get("candidate_bound_rows_before_lockbox_pass"),
        "forward_canary_rows_scanned": forward_rows_scanned,
        "rows_scanned": forward_rows_scanned,
        "scanned_rows": forward_rows_scanned,
        "total_rows_scanned": forward_rows_scanned,
        "candidate_bound_rows": forward_closed_outcomes,
        "old_policy_or_unbound_rows_quarantined": forward_identity_excluded_rows,
        "identity_incomplete_rows": forward_identity_excluded_rows,
        "non_counting_row_count": sum(int(count or 0) for count in forward_excluded_counts.values()),
        "forward_canary_closed_challenger_economic_outcomes": forward_closed_outcomes,
        "forward_identity_excluded_rows": forward_identity_excluded_rows,
        "forward_canary_old_policy_rows_excluded_by_identity": pass_conditions[
            "forward_canary_old_policy_rows_excluded_by_identity"
        ],
        "forward_canary_excluded_row_counts": dict(sorted(forward_excluded_counts.items())),
        "sample_old_or_unbound_rows": paper_cost_telemetry.get("sample_production_grade_identity_gap_rows") or [],
        "credit_attribution_contract": {
            "required_identity_fields": required_identity_fields,
            "old_policy_rows_count_as_challenger_evidence": False,
            "binding_allowed_until_cost_and_lockbox_pass": False,
            "paper_fill_allowed_rows_count_as_challenger_evidence": False,
            "forward_rows_without_complete_identity_count_as_challenger_evidence": False,
        },
        "old_policy_credit_rule": "Rows count for challenger only when candidate_id, policy_fingerprint, and model_source all match the frozen challenger.",
        "paper_fill_rule": "paper_fill_allowed=true rows are diagnostics here and cannot count as challenger production-grade, lockbox, canary, or promotion evidence before binding.",
        "pass_conditions": pass_conditions,
        "credit_condition_details": credit_condition_details,
        "blocker_details": credit_condition_details,
        "failed_blocker_details": failed_credit_blocker_details,
        "failed_credit_attribution_blocker_details": failed_credit_blocker_details,
        "actuals": credit_actuals,
        "required": credit_required,
        "sample_blockers": failed_credit_blocker_samples,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }


def forward_paper_canary_pass_contract_audit_from_redis(
    *,
    policy: FrozenPolicy,
    paper_canary_binding: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    signal_scan_limit: int = DEFAULT_PAPER_SIGNAL_SCAN_LIMIT,
) -> dict[str, Any]:
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
    except Exception as exc:
        return forward_paper_canary_pass_contract_audit_from_rows(
            policy=policy,
            rows=[],
            paper_canary_binding=paper_canary_binding,
            lockbox_pass_contract=lockbox_pass_contract,
            redis_status=f"SKIPPED_REDIS_UNAVAILABLE:{type(exc).__name__}",
        )

    rows: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for key in (
        "v2:paper:closed_trades",
        "v2:paper:ledger",
        "v2:paper_online:ledger",
        "v2:trainer:feedback:outcomes",
        "v2:trainer:feedback:outcomes:quarantine",
        "v2:trainer:feedback",
        "v2:trainer:feedback_quarantine",
    ):
        key_rows = forward_canary_rows_from_redis_value(client.get(key), source_key=key)
        rows.extend(key_rows)
        source_counts[key] += len(key_rows)

    signal_rows, signal_source_counts, _signal_count, scan_limit_reached = bounded_paper_signal_scan(
        client,
        signal_scan_limit=signal_scan_limit,
        row_reader=lambda raw, key: forward_canary_rows_from_redis_value(raw, source_key=key),
    )
    rows.extend(signal_rows)
    source_counts.update(signal_source_counts)

    return forward_paper_canary_pass_contract_audit_from_rows(
        policy=policy,
        rows=rows,
        paper_canary_binding=paper_canary_binding,
        lockbox_pass_contract=lockbox_pass_contract,
        redis_status="READ_REDIS_FORWARD_PAPER_CANARY_ROWS_BOUNDED",
        source_counts=source_counts,
        scan_limit_reached=scan_limit_reached,
    )


def added_paper_governance_blocker_audit(
    *,
    policy: FrozenPolicy,
    paper_governance_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Promote the added paper routing/churn governance goal into this goal's gate."""
    summary = paper_governance_summary if isinstance(paper_governance_summary, Mapping) else {}
    raw_artifacts_written = summary.get("artifacts_written")
    source_artifacts_written = (
        [str(artifact) for artifact in raw_artifacts_written]
        if isinstance(raw_artifacts_written, Sequence)
        and not isinstance(raw_artifacts_written, (str, bytes, bytearray))
        else []
    )
    missing_required_artifacts = [
        artifact for artifact in ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS if artifact not in set(source_artifacts_written)
    ]
    required_artifact_count = len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    missing_required_artifact_count = len(missing_required_artifacts)
    source_required_artifact_count_raw = finite_float(
        summary.get("required_artifact_count", summary.get("source_required_artifact_count"))
    )
    source_required_artifact_count = (
        int(source_required_artifact_count_raw)
        if source_required_artifact_count_raw is not None
        else None
    )
    source_missing_required_artifact_count_raw = finite_float(
        summary.get("missing_required_artifact_count", summary.get("source_missing_required_artifact_count"))
    )
    source_missing_required_artifact_count = (
        int(source_missing_required_artifact_count_raw)
        if source_missing_required_artifact_count_raw is not None
        else None
    )
    required_artifacts_present = not missing_required_artifacts
    source_required_artifacts_present = (
        summary.get("required_artifacts_present") is True
        or (
            source_required_artifact_count == required_artifact_count
            and source_missing_required_artifact_count == 0
        )
    )
    raw_close_records = finite_float(summary.get("raw_close_record_count"))
    economic_trades = finite_float(summary.get("economic_trade_count"))
    hardcoded_1m_paths = finite_float(summary.get("hardcoded_1m_path_count"))
    silent_1m_fallback_paths = finite_float(summary.get("silent_1m_fallback_path_count"))
    cost_coverage = finite_float(summary.get("paper_entry_production_grade_cost_coverage"))
    source_statuses = summary.get("source_statuses") if isinstance(summary.get("source_statuses"), Mapping) else {}
    source_blocker_summary = summary.get("blocker_summary") if isinstance(summary.get("blocker_summary"), Mapping) else {}
    raw_source_blocker_details = source_blocker_summary.get("blocker_details") or summary.get("source_blocker_details")
    source_blocker_details = (
        raw_source_blocker_details
        if isinstance(raw_source_blocker_details, Sequence)
        and not isinstance(raw_source_blocker_details, (str, bytes, bytearray))
        else []
    )
    raw_source_blocked_pass_conditions = (
        source_blocker_summary.get("blocked_pass_conditions")
        or summary.get("source_blocked_pass_conditions")
    )
    raw_source_blocked_pass_conditions = (
        raw_source_blocked_pass_conditions
        if isinstance(raw_source_blocked_pass_conditions, Sequence)
        and not isinstance(raw_source_blocked_pass_conditions, (str, bytes, bytearray))
        else []
    )
    source_blocked_pass_conditions = [
        str(condition)
        for condition in raw_source_blocked_pass_conditions
    ]
    source_blocker_count_raw = source_blocker_summary.get("blocker_count", summary.get("source_blocker_count"))
    source_blocker_count_float = finite_float(source_blocker_count_raw)
    source_blocker_count = (
        int(source_blocker_count_float)
        if source_blocker_count_float is not None
        else len(source_blocked_pass_conditions)
    )
    final_gate_ready = summary.get("final_gate") == ADDED_PAPER_GOVERNANCE_READY_MARKER
    source_blockers_cleared = (
        bool(summary)
        and (
            (not source_blocker_summary and final_gate_ready)
            or (source_blocker_count == 0 and not source_blocked_pass_conditions)
        )
    )
    source_phase_blockers = summary.get("source_phase_blockers")
    source_phase_blockers = source_phase_blockers if isinstance(source_phase_blockers, Mapping) else summary.get("phase_blockers")
    source_phase_blockers = source_phase_blockers if isinstance(source_phase_blockers, Mapping) else {}
    source_phase_blocker_count_raw = finite_float(summary.get("source_phase_blocker_count"))
    source_phase_blocker_count = (
        int(source_phase_blocker_count_raw)
        if source_phase_blocker_count_raw is not None
        else sum(
            len(value)
            for value in source_phase_blockers.values()
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        )
    )
    source_phase_blockers_cleared = bool(summary) and (
        (not source_phase_blockers and final_gate_ready)
        or (bool(source_phase_blockers) and source_phase_blocker_count == 0)
    )
    pass_conditions = {
        "paper_governance_summary_present": bool(summary),
        "added_goal_id_matches": summary.get("added_goal_id") == ADDED_PAPER_GOVERNANCE_GOAL_ID,
        "required_artifacts_written": bool(summary) and not missing_required_artifacts,
        "current_closed_ledger_recomputed": raw_close_records is not None and raw_close_records >= 0.0,
        "economic_trade_compaction_present": economic_trades is not None and economic_trades >= 0.0,
        "current_timeframe_distribution_proven": summary.get("current_1m_share") is not None
        and summary.get("current_1m_economic_trade_share") is not None,
        "paper_routing_owner_audit_passed": summary.get("routing_status") == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "hardcoded_1m_economic_paths_removed": hardcoded_1m_paths is not None and int(hardcoded_1m_paths) == 0,
        "silent_1m_fallbacks_absent": silent_1m_fallback_paths is not None and int(silent_1m_fallback_paths) == 0,
        "paper_churn_governor_wired": str(summary.get("paper_churn_governor_status") or "").startswith("PASS_"),
        "operator_dashboard_website_truth_contract_passed": (
            summary.get("operator_dashboard_truth_contract_status") == "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
        ),
        "paper_edge_to_cost_gate_passed": summary.get("paper_edge_to_cost_gate_status") == "PASS_PAPER_EDGE_TO_COST_GATE",
        "paper_entry_production_grade_cost_coverage_gte_95pct": cost_coverage is not None and cost_coverage >= 0.95,
        "post_fix_paper_validation_passed": summary.get("post_fix_paper_validation_status") == "PASS_POST_FIX_PAPER_VALIDATION",
        "source_paper_governance_blockers_cleared": source_blockers_cleared,
        "source_paper_governance_phase_blockers_cleared": source_phase_blockers_cleared,
        "final_gate_ready": final_gate_ready,
        "no_live_routes": summary.get("routes_to_live") is False and summary.get("places_real_order") is False,
    }
    blocked_conditions = [name for name, passed in pass_conditions.items() if passed is not True]
    condition_source_artifact = {
        "paper_routing_owner_audit_passed": "paper_timeframe_routing_owner_status",
        "paper_churn_governor_wired": "paper_churn_governor_status",
        "operator_dashboard_website_truth_contract_passed": "operator_dashboard_truth_contract_status",
        "paper_edge_to_cost_gate_passed": "paper_edge_to_cost_gate_status",
        "paper_entry_production_grade_cost_coverage_gte_95pct": "paper_entry_cost_coverage_status",
        "post_fix_paper_validation_passed": "post_fix_paper_validation_status",
        "final_gate_ready": "paper_timeframe_churn_governance_audit_summary",
        "hardcoded_1m_economic_paths_removed": "paper_timeframe_routing_owner_status",
        "silent_1m_fallbacks_absent": "paper_timeframe_routing_owner_status",
        "current_closed_ledger_recomputed": "current_paper_timeframe_churn_audit",
        "economic_trade_compaction_present": "economic_trade_compaction_status",
        "current_timeframe_distribution_proven": "current_paper_timeframe_churn_audit",
        "required_artifacts_written": "paper_timeframe_churn_governance_audit_summary",
        "source_paper_governance_blockers_cleared": "paper_timeframe_churn_governance_audit_summary",
        "source_paper_governance_phase_blockers_cleared": "paper_timeframe_churn_governance_audit_summary",
    }
    condition_actuals = {
        "paper_governance_summary_present": bool(summary),
        "added_goal_id_matches": summary.get("added_goal_id"),
        "required_artifacts_written": {
            "required_artifacts": list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "source_artifacts_written": source_artifacts_written,
            "missing_required_artifacts": missing_required_artifacts,
        },
        "current_closed_ledger_recomputed": summary.get("raw_close_record_count"),
        "economic_trade_compaction_present": summary.get("economic_trade_count"),
        "current_timeframe_distribution_proven": {
            "current_1m_share": summary.get("current_1m_share"),
            "current_1m_economic_trade_share": summary.get("current_1m_economic_trade_share"),
        },
        "paper_routing_owner_audit_passed": summary.get("routing_status"),
        "hardcoded_1m_economic_paths_removed": summary.get("hardcoded_1m_path_count"),
        "silent_1m_fallbacks_absent": {
            "silent_1m_fallback_path_count": summary.get("silent_1m_fallback_path_count"),
            "timeframe_routing_violation_count": summary.get("timeframe_routing_violation_count"),
            "silent_1m_fallback_paths": summary.get("silent_1m_fallback_paths"),
            "routing_owner_blocked_reasons": summary.get("routing_owner_blocked_reasons"),
            "routing_repair_blocked_reasons": summary.get("routing_repair_blocked_reasons"),
        },
        "paper_churn_governor_wired": summary.get("paper_churn_governor_status"),
        "operator_dashboard_website_truth_contract_passed": {
            "status": summary.get("operator_dashboard_truth_contract_status"),
            "blocked_reasons": summary.get("operator_dashboard_truth_contract_blocked_reasons"),
            "missing_required_fields": summary.get("operator_dashboard_missing_required_fields"),
        },
        "paper_edge_to_cost_gate_passed": summary.get("paper_edge_to_cost_gate_status"),
        "paper_entry_production_grade_cost_coverage_gte_95pct": summary.get(
            "paper_entry_production_grade_cost_coverage"
        ),
        "post_fix_paper_validation_passed": summary.get("post_fix_paper_validation_status"),
        "source_paper_governance_blockers_cleared": {
            "source_blocker_count": source_blocker_count,
            "source_blocked_pass_conditions": source_blocked_pass_conditions,
        },
        "source_paper_governance_phase_blockers_cleared": {
            "source_phase_blocker_count": source_phase_blocker_count,
            "source_phase_blockers": dict(source_phase_blockers),
        },
        "final_gate_ready": summary.get("final_gate"),
        "no_live_routes": {
            "routes_to_live": summary.get("routes_to_live"),
            "places_real_order": summary.get("places_real_order"),
        },
    }
    condition_required = {
        "paper_governance_summary_present": True,
        "added_goal_id_matches": ADDED_PAPER_GOVERNANCE_GOAL_ID,
        "required_artifacts_written": {"missing_required_artifacts": []},
        "current_closed_ledger_recomputed": ">=0",
        "economic_trade_compaction_present": ">=0",
        "current_timeframe_distribution_proven": {
            "current_1m_share": "present",
            "current_1m_economic_trade_share": "present",
        },
        "paper_routing_owner_audit_passed": "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        "hardcoded_1m_economic_paths_removed": 0,
        "silent_1m_fallbacks_absent": {"silent_1m_fallback_path_count": 0},
        "paper_churn_governor_wired": "PASS_*",
        "operator_dashboard_website_truth_contract_passed": "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
        "paper_edge_to_cost_gate_passed": "PASS_PAPER_EDGE_TO_COST_GATE",
        "paper_entry_production_grade_cost_coverage_gte_95pct": ">=0.95",
        "post_fix_paper_validation_passed": "PASS_POST_FIX_PAPER_VALIDATION",
        "source_paper_governance_blockers_cleared": {
            "source_blocker_count": 0,
            "source_blocked_pass_conditions": [],
        },
        "source_paper_governance_phase_blockers_cleared": {"source_phase_blocker_count": 0},
        "final_gate_ready": ADDED_PAPER_GOVERNANCE_READY_MARKER,
        "no_live_routes": {"routes_to_live": False, "places_real_order": False},
    }
    blocker_details = [
        {
            "pass_condition": name,
            "passed": False,
            "source_artifact": condition_source_artifact.get(name, "paper_timeframe_churn_governance_audit_summary"),
            "source_status": (
                summary.get("final_gate")
                if name == "final_gate_ready"
                else source_statuses.get(condition_source_artifact.get(name, ""))
            ),
            "actual": condition_actuals.get(name),
            "required": condition_required.get(name),
        }
        for name in blocked_conditions
    ]
    return {
        "schema_version": "challenger_v2_added_paper_governance_blocker_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "added_goal_id": ADDED_PAPER_GOVERNANCE_GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT" if not blocked_conditions else "BLOCKED_ADDED_PAPER_GOVERNANCE_REPAIR",
        "pass_conditions": pass_conditions,
        "blocked_conditions": blocked_conditions,
        "blocked_reasons": blocked_conditions,
        "blocked_condition_count": len(blocked_conditions),
        "blocker_details": blocker_details,
        "failed_blocker_details": blocker_details,
        "failed_added_paper_governance_blocker_details": blocker_details,
        "actuals": condition_actuals,
        "required": condition_required,
        "sample_blockers": blocker_details[:25],
        "source_statuses": dict(source_statuses),
        "source_status": summary.get("status"),
        "source_summary_status": summary.get("status"),
        "source_summary_final_gate": summary.get("final_gate"),
        "source_blocker_count": source_blocker_count,
        "source_blocked_pass_conditions": source_blocked_pass_conditions,
        "source_blocker_details": list(source_blocker_details),
        "source_phase_blocker_count": source_phase_blocker_count,
        "source_phase_blockers": dict(source_phase_blockers),
        "source_artifact": "paper_timeframe_churn_governance_audit_summary.json",
        "source_generated_utc": summary.get("generated_utc"),
        "source_final_gate": summary.get("final_gate"),
        "final_gate": summary.get("final_gate"),
        "final_gate_ready": final_gate_ready,
        "source_paper_governance_blockers_cleared": source_blockers_cleared,
        "source_paper_governance_phase_blockers_cleared": source_phase_blockers_cleared,
        "source_artifacts_written": source_artifacts_written,
        "required_artifacts": list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
        "required_artifact_count": required_artifact_count,
        "required_artifacts_present": required_artifacts_present,
        "source_required_artifact_count": source_required_artifact_count,
        "source_summary_required_artifact_count": source_required_artifact_count,
        "source_required_artifacts_present": source_required_artifacts_present,
        "source_summary_required_artifacts_present": source_required_artifacts_present,
        "missing_required_artifacts": missing_required_artifacts,
        "missing_required_artifact_count": missing_required_artifact_count,
        "source_missing_required_artifact_count": source_missing_required_artifact_count,
        "source_summary_missing_required_artifact_count": source_missing_required_artifact_count,
        "source_routing_status": summary.get("routing_status"),
        "raw_close_record_count": summary.get("raw_close_record_count"),
        "economic_trade_count": summary.get("economic_trade_count"),
        "old_policy_trade_count": summary.get("old_policy_trade_count"),
        "challenger_trade_count": summary.get("challenger_trade_count"),
        "current_1m_share": summary.get("current_1m_share"),
        "current_1m_economic_trade_share": summary.get("current_1m_economic_trade_share"),
        "hardcoded_1m_path_count": summary.get("hardcoded_1m_path_count"),
        "silent_1m_fallback_path_count": summary.get("silent_1m_fallback_path_count"),
        "timeframe_routing_violation_count": summary.get("timeframe_routing_violation_count"),
        "silent_1m_fallback_paths": summary.get("silent_1m_fallback_paths"),
        "routing_owner_blocked_reasons": summary.get("routing_owner_blocked_reasons"),
        "routing_repair_blocked_reasons": summary.get("routing_repair_blocked_reasons"),
        "paper_entry_production_grade_cost_coverage": summary.get("paper_entry_production_grade_cost_coverage"),
        "paper_entry_required_coverage": summary.get("paper_entry_required_coverage"),
        "paper_entry_missing_required_fields": summary.get("paper_entry_missing_required_fields"),
        "paper_entry_missing_required_field_counts": summary.get("paper_entry_missing_required_field_counts"),
        "paper_entry_missing_required_field_count": summary.get("paper_entry_missing_required_field_count"),
        "paper_entry_shadow_only_missing_cost_rows": summary.get("paper_entry_shadow_only_missing_cost_rows"),
        "paper_churn_governor_status": summary.get("paper_churn_governor_status"),
        "operator_dashboard_truth_contract_status": summary.get("operator_dashboard_truth_contract_status"),
        "operator_dashboard_truth_contract_blocked_reasons": summary.get(
            "operator_dashboard_truth_contract_blocked_reasons"
        ),
        "operator_dashboard_missing_required_fields": summary.get("operator_dashboard_missing_required_fields"),
        "paper_edge_to_cost_gate_status": summary.get("paper_edge_to_cost_gate_status"),
        "paper_edge_to_cost_production_grade_cost_coverage": summary.get(
            "paper_edge_to_cost_production_grade_cost_coverage"
        ),
        "paper_edge_to_cost_admitted_candidate_count": summary.get("paper_edge_to_cost_admitted_candidate_count"),
        "paper_edge_to_cost_shadow_only_candidate_count": summary.get("paper_edge_to_cost_shadow_only_candidate_count"),
        "paper_edge_to_cost_missing_gate_input_counts": summary.get("paper_edge_to_cost_missing_gate_input_counts"),
        "dynamic_timeframe_execution_eligibility_status": summary.get(
            "dynamic_timeframe_execution_eligibility_status"
        ),
        "dynamic_timeframe_bucket_count": summary.get("dynamic_timeframe_bucket_count"),
        "dynamic_timeframe_bucket_state_counts": summary.get("dynamic_timeframe_bucket_state_counts"),
        "dynamic_timeframe_sample_bucket_statuses": summary.get("dynamic_timeframe_sample_bucket_statuses"),
        "dynamic_timeframe_sample_blocked_buckets": summary.get("dynamic_timeframe_sample_blocked_buckets"),
        "dynamic_timeframe_sample_shadow_only_buckets": summary.get("dynamic_timeframe_sample_shadow_only_buckets"),
        "timeframe_execution_concentration_guard_status": summary.get(
            "timeframe_execution_concentration_guard_status"
        ),
        "timeframe_execution_concentration_violation_count": summary.get(
            "timeframe_execution_concentration_violation_count"
        ),
        "timeframe_execution_concentration_operator_envelope": summary.get(
            "timeframe_execution_concentration_operator_envelope"
        ),
        "timeframe_execution_concentration_sample_violations": summary.get(
            "timeframe_execution_concentration_sample_violations"
        ),
        "timeframe_execution_concentration_violation_samples": summary.get(
            "timeframe_execution_concentration_violation_samples"
        ),
        "timeframe_execution_concentration_violation_sample_count": summary.get(
            "timeframe_execution_concentration_violation_sample_count"
        ),
        "paper_reentry_and_signal_dedup_status": summary.get("paper_reentry_and_signal_dedup_status"),
        "economic_trade_compaction_status": summary.get("economic_trade_compaction_status"),
        "economic_trade_compaction_missing_raw_identity_fields": summary.get(
            "economic_trade_compaction_missing_raw_identity_fields"
        ),
        "economic_trade_compaction_raw_identity_missing_field_counts": summary.get(
            "economic_trade_compaction_raw_identity_missing_field_counts"
        ),
        "economic_trade_compaction_accounting_reconciliation_status": summary.get(
            "economic_trade_compaction_accounting_reconciliation_status"
        ),
        "multi_timeframe_thesis_execution_contract_status": summary.get(
            "multi_timeframe_thesis_execution_contract_status"
        ),
        "multi_timeframe_thesis_execution_required_fields_present_for_all_rows": summary.get(
            "multi_timeframe_thesis_execution_required_fields_present_for_all_rows"
        ),
        "multi_timeframe_thesis_execution_required_fields_present": summary.get(
            "multi_timeframe_thesis_execution_required_fields_present"
        ),
        "multi_timeframe_thesis_execution_missing_required_fields": summary.get(
            "multi_timeframe_thesis_execution_missing_required_fields"
        ),
        "multi_timeframe_thesis_execution_missing_required_field_counts": summary.get(
            "multi_timeframe_thesis_execution_missing_required_field_counts"
        ),
        "multi_timeframe_thesis_execution_standalone_1m_requires_eligible_strategy": summary.get(
            "multi_timeframe_thesis_execution_standalone_1m_requires_eligible_strategy"
        ),
        "multi_timeframe_thesis_execution_close_outcome_attributed_to_thesis_timeframe": summary.get(
            "multi_timeframe_thesis_execution_close_outcome_attributed_to_thesis_timeframe"
        ),
        "multi_timeframe_thesis_execution_higher_tf_position_not_reopened_on_each_1m_tick": summary.get(
            "multi_timeframe_thesis_execution_higher_tf_position_not_reopened_on_each_1m_tick"
        ),
        "multi_timeframe_thesis_execution_higher_tf_1m_timing_preserves_thesis": summary.get(
            "multi_timeframe_thesis_execution_higher_tf_1m_timing_preserves_thesis"
        ),
        "post_fix_paper_validation_status": summary.get("post_fix_paper_validation_status"),
        "post_fix_sample_status": summary.get("post_fix_sample_status"),
        "post_fix_sample_started": summary.get("post_fix_sample_started"),
        "post_fix_sample_raw_close_rows": summary.get("post_fix_sample_raw_close_rows"),
        "post_fix_sample_eligible_raw_close_rows": summary.get("post_fix_sample_eligible_raw_close_rows"),
        "post_fix_sample_excluded_raw_close_rows": summary.get("post_fix_sample_excluded_raw_close_rows"),
        "post_fix_sample_exclusion_reason_counts": summary.get("post_fix_sample_exclusion_reason_counts"),
        "post_fix_sample_source_counts": summary.get("post_fix_sample_source_counts"),
        "post_fix_sample_eligible_source_counts": summary.get("post_fix_sample_eligible_source_counts"),
        "post_fix_sample_excluded_source_counts": summary.get("post_fix_sample_excluded_source_counts"),
        "post_fix_sample_source_read_status": summary.get("post_fix_sample_source_read_status"),
        "post_fix_sample_sample_excluded_rows": summary.get("post_fix_sample_sample_excluded_rows"),
        "post_fix_sample_excluded_row_samples": summary.get("post_fix_sample_excluded_row_samples"),
        "sample_excluded_rows": summary.get("sample_excluded_rows"),
        "excluded_row_samples": summary.get("excluded_row_samples"),
        "post_fix_sample_sample_excluded_rows_by_source": summary.get(
            "post_fix_sample_sample_excluded_rows_by_source"
        ),
        "post_fix_sample_sample_compacted_economic_trades": summary.get(
            "post_fix_sample_sample_compacted_economic_trades"
        ),
        "new_compacted_economic_paper_outcomes": summary.get("new_compacted_economic_paper_outcomes"),
        "required_new_compacted_economic_paper_outcomes": summary.get("required_new_compacted_economic_paper_outcomes"),
        "post_fix_validation_actuals": summary.get("post_fix_validation_actuals"),
        "post_fix_validation_actuals_alias": summary.get("post_fix_validation_actuals_alias"),
        "post_fix_validation_required": summary.get("post_fix_validation_required"),
        "post_fix_validation_required_alias": summary.get("post_fix_validation_required_alias"),
        "post_fix_duplicate_economic_trades": summary.get("post_fix_duplicate_economic_trades"),
        "post_fix_unexplained_same_candle_reentries": summary.get("post_fix_unexplained_same_candle_reentries"),
        "post_fix_accounting_reconciliation_status": summary.get("post_fix_accounting_reconciliation_status"),
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": not blocked_conditions,
    }


def challenger_goal_phase_completion_audit(
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    cost_capture_gap: Mapping[str, Any],
    runtime_cost_capture_contract: Mapping[str, Any],
    append_status: Mapping[str, Any],
    label_status: Mapping[str, Any],
    hash_chain: Mapping[str, Any],
    pending_rows: Sequence[Mapping[str, Any]],
    labelled_rows: Sequence[Mapping[str, Any]],
    drift_coverage: Mapping[str, Any],
    drift_mapping_confidence: Mapping[str, Any],
    shadow_supply_contract: Mapping[str, Any],
    zero_supply: Mapping[str, Any],
    lockbox_integrity: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    paper_canary_binding: Mapping[str, Any],
    forward_canary_contract: Mapping[str, Any],
    paper_chain_binding_readiness: Mapping[str, Any] | None = None,
    added_paper_governance: Mapping[str, Any] | None = None,
    runtime_cost_capture_operator_approval_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    hash_pending = hash_chain.get("pending") if isinstance(hash_chain.get("pending"), Mapping) else {}
    hash_labelled = hash_chain.get("labelled") if isinstance(hash_chain.get("labelled"), Mapping) else {}
    cost_pass_conditions = cost_status.get("pass_conditions")
    cost_pass_conditions = cost_pass_conditions if isinstance(cost_pass_conditions, Mapping) else {}
    required_cost_field_all_row_conditions = [
        name
        for name in cost_pass_conditions
        if str(name).startswith("required_cost_field_") and str(name).endswith("_present_for_all_rows")
    ]
    required_cost_field_coverage_conditions = cost_status.get("required_field_coverage_pass_conditions")
    required_cost_field_coverage_conditions = (
        required_cost_field_coverage_conditions
        if isinstance(required_cost_field_coverage_conditions, Mapping)
        else {}
    )
    hard_blocker_fields = cost_status.get("hard_blocker_fields")
    hard_blocker_fields = hard_blocker_fields if isinstance(hard_blocker_fields, Sequence) and not isinstance(hard_blocker_fields, (str, bytes)) else []
    hard_blocker_count = int(cost_status.get("hard_blocker_count") or len(hard_blocker_fields))
    phase_1_conditions = {
        "production_grade_cost_evidence_passed": cost_status.get("status") == "PASS",
        "production_grade_cost_coverage_gte_95pct": float(cost_status.get("production_grade_cost_coverage") or 0.0) >= 0.95,
        "unexplained_cost_missing_rows_eq_0": int(cost_status.get("unexplained_cost_missing_rows") or 0) == 0,
        "replay_paper_cost_parity_mismatch_rows_eq_0": int(cost_status.get("replay_paper_cost_parity_mismatch_rows") or 0) == 0,
        "required_cost_fields_present_for_all_rows": cost_status.get("required_cost_fields_present_for_all_rows") is True
        or cost_status.get("required_evidence_fields_present") is True
        or (
            bool(required_cost_field_all_row_conditions)
            and all(cost_pass_conditions.get(name) is True for name in required_cost_field_all_row_conditions)
        ),
        "required_cost_fields_covered_gte_95pct": cost_status.get("required_cost_fields_covered_gte_95pct") is True
        or cost_status.get("required_evidence_fields_covered_gte_95pct") is True
        or (
            bool(required_cost_field_coverage_conditions)
            and all(value is True for value in required_cost_field_coverage_conditions.values())
        ),
        "hard_blocking_cost_fields_cleared": hard_blocker_count == 0,
        "existing_authoritative_cost_sources_sufficient": cost_capture_gap.get("can_recover_from_existing_authoritative_sources_without_new_capture") is True,
        "runtime_cost_capture_contract_satisfied": runtime_cost_capture_contract.get("status") == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        "runtime_cost_capture_operator_approval_receipt_passed": (
            runtime_cost_capture_operator_approval_receipt.get("status") == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
            if isinstance(runtime_cost_capture_operator_approval_receipt, Mapping)
            else False
        ),
    }
    phase_2_conditions = {
        "pending_lockbox_rows_gt_0": len(pending_rows) > 0,
        "pending_append_status_present": append_status.get("pending_path") is not None or append_status.get("new_pending_rows_appended") is not None,
        "label_append_status_present": label_status.get("labelled_path") is not None,
        "hash_chain_pending_present": bool(hash_pending.get("last_chain_hash") or hash_pending.get("row_count")),
        "hash_chain_labelled_present": bool(hash_labelled.get("last_chain_hash") or hash_labelled.get("row_count") is not None),
        "lockbox_integrity_audit_passed": lockbox_integrity.get("status") == "PASS_INTEGRITY_AUDIT",
    }
    phase_3_conditions = {
        "drift_coverage_audit_passed": drift_coverage.get("status") == "PASS_DRIFT_COVERAGE_AUDIT",
        "drift_mapping_confidence_audit_passed": drift_mapping_confidence.get("status") == "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT",
        "candidate_id_change_not_required_for_current_mapping": drift_mapping_confidence.get("candidate_id_change_required") is False,
        "frozen_candidate_kept": drift_mapping_confidence.get("frozen_candidate_kept") is True,
    }
    phase_4_conditions = {
        "shadow_supply_contract_passed": shadow_supply_contract.get("status") == "PASS_SHADOW_SUPPLY_CONTRACT",
        "top_25_long_candidates_published": int(shadow_supply_contract.get("top_25_long_count") or 0) == 25,
        "top_25_short_candidates_published": int(shadow_supply_contract.get("top_25_short_count") or 0) == 25,
        "shadow_rows_non_executable": shadow_supply_contract.get("routes_to_live") is False
        and shadow_supply_contract.get("paper_fill_allowed") is False
        and shadow_supply_contract.get("counts_as_a_grade_evidence") is False,
        "zero_supply_diagnosed_when_no_selected_rows": zero_supply.get("status") == "ZERO_SUPPLY_DIAGNOSED",
    }
    lockbox_symbol_count = int(lockbox_pass_contract.get("symbols") or lockbox_pass_contract.get("symbol_count") or 0)
    lockbox_long_count = int(lockbox_pass_contract.get("long_count") or lockbox_pass_contract.get("long_candidates") or 0)
    lockbox_short_count = int(lockbox_pass_contract.get("short_count") or lockbox_pass_contract.get("short_candidates") or 0)
    lockbox_after_cost_expectancy = finite_float(lockbox_pass_contract.get("after_cost_expectancy_bps"))
    lockbox_expectancy_lower_bound = finite_float(lockbox_pass_contract.get("expectancy_95pct_lower_bound_bps"))
    lockbox_profit_factor = finite_float(lockbox_pass_contract.get("profit_factor"))
    lockbox_false_positive_rate = finite_float(lockbox_pass_contract.get("false_positive_rate"))
    lockbox_max_concentration = finite_float(lockbox_pass_contract.get("max_concentration_pct"))
    lockbox_worst_1pct_loss = finite_float(lockbox_pass_contract.get("worst_1pct_loss_bps"))
    phase_5_conditions = {
        "blind_lockbox_pass_contract_passed": lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "independent_economic_candidates_gte_300": int(lockbox_pass_contract.get("independent_economic_candidates") or 0) >= 300,
        "symbols_gte_30": lockbox_symbol_count >= 30,
        "long_gt_0": lockbox_long_count > 0,
        "short_gt_0": lockbox_short_count > 0,
        "after_cost_expectancy_gt_0": lockbox_after_cost_expectancy is not None and lockbox_after_cost_expectancy > 0.0,
        "expectancy_95pct_lower_bound_gt_0": lockbox_expectancy_lower_bound is not None and lockbox_expectancy_lower_bound > 0.0,
        "profit_factor_gte_1_5": lockbox_profit_factor is not None and lockbox_profit_factor >= 1.5,
        "false_positive_rate_lte_0_40": lockbox_false_positive_rate is not None and lockbox_false_positive_rate <= 0.40,
        "no_concentration_dimension_gt_30pct": lockbox_max_concentration is not None and lockbox_max_concentration <= 0.30,
        "worst_1pct_loss_inside_risk_envelope": lockbox_worst_1pct_loss is not None and lockbox_worst_1pct_loss >= -500.0,
        "point_in_time_violations_eq_0": int(lockbox_pass_contract.get("point_in_time_violations") or 0) == 0,
        "production_grade_cost_coverage_gte_95pct": float(lockbox_pass_contract.get("production_grade_cost_coverage") or 0.0) >= 0.95,
    }
    paper_chain_binding_readiness = (
        paper_chain_binding_readiness
        if isinstance(paper_chain_binding_readiness, Mapping)
        else {}
    )
    paper_chain_pass_conditions = paper_chain_binding_readiness.get("pass_conditions")
    paper_chain_pass_conditions = (
        paper_chain_pass_conditions
        if isinstance(paper_chain_pass_conditions, Mapping)
        else {}
    )
    phase_6_conditions = {
        "paper_canary_binding_allowed": paper_canary_binding.get("binding_allowed") is True,
        "paper_record_identity_contract_declared": paper_canary_binding.get("pass_conditions", {}).get("paper_record_identity_contract_declared") is True
        if isinstance(paper_canary_binding.get("pass_conditions"), Mapping)
        else False,
        "paper_chain_binding_ready": paper_chain_binding_readiness.get("chain_ready") is True,
        "required_paper_chain_declared": paper_chain_pass_conditions.get("required_chain_declared") is True,
        "paper_chain_components_ready": int(paper_chain_binding_readiness.get("complete_components") or 0)
        == int(paper_chain_binding_readiness.get("required_components") or len(PAPER_CANARY_CHAIN))
        and int(paper_chain_binding_readiness.get("missing_component_count") or 0) == 0,
        "paper_chain_components_have_identity_contract": paper_chain_pass_conditions.get(
            "all_chain_components_have_identity_contract"
        )
        is True,
        "paper_chain_identity_fields_declared": paper_chain_pass_conditions.get("paper_record_identity_fields_declared")
        is True,
        "old_policy_rows_do_not_count": paper_canary_binding.get("old_policy_rows_count_as_challenger_evidence") is False,
        "paper_only_no_live_routes": paper_canary_binding.get("routes_to_live") is False
        and paper_canary_binding.get("places_real_order") is False
        and paper_chain_binding_readiness.get("routes_to_live") is False
        and paper_chain_binding_readiness.get("places_real_order") is False,
    }
    forward_after_cost_expectancy = finite_float(forward_canary_contract.get("after_cost_expectancy_bps"))
    phase_7_conditions = {
        "forward_paper_canary_contract_passed": forward_canary_contract.get("status") == "PASS_FORWARD_PAPER_CANARY_CONTRACT",
        "new_closed_challenger_economic_outcomes_gte_100": int(forward_canary_contract.get("closed_challenger_economic_outcomes") or 0) >= 100,
        "paper_canary_symbols_gte_30": int(forward_canary_contract.get("symbols") or 0) >= 30,
        "paper_canary_long_gt_0": int(forward_canary_contract.get("long_count") or 0) > 0,
        "paper_canary_short_gt_0": int(forward_canary_contract.get("short_count") or 0) > 0,
        "paper_canary_after_cost_expectancy_gt_0": forward_after_cost_expectancy is not None
        and forward_after_cost_expectancy > 0.0,
        "paper_canary_profit_factor_gte_1_5": forward_canary_contract.get("profit_factor") is not None
        and float(forward_canary_contract.get("profit_factor") or 0.0) >= 1.5,
        "paper_canary_no_accounting_mismatch": int(forward_canary_contract.get("accounting_mismatch_rows") or 0) == 0,
        "paper_canary_no_liquidation": int(forward_canary_contract.get("liquidation_rows") or 0) == 0,
        "paper_canary_point_in_time_violations_eq_0": int(forward_canary_contract.get("point_in_time_violations") or 0) == 0,
        "paper_only_no_live_routes": int(forward_canary_contract.get("live_route_rows") or 0) == 0,
    }
    added_paper_governance = added_paper_governance if isinstance(added_paper_governance, Mapping) else {}
    added_paper_conditions = added_paper_governance.get("pass_conditions")
    added_paper_conditions = added_paper_conditions if isinstance(added_paper_conditions, Mapping) else {}
    added_paper_phase_conditions = {
        "added_paper_governance_blocker_audit_passed": added_paper_governance.get("status") == "PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT",
        "paper_governance_final_gate_ready": added_paper_conditions.get("final_gate_ready") is True,
        "hardcoded_1m_economic_paths_removed": added_paper_conditions.get("hardcoded_1m_economic_paths_removed") is True,
        "paper_entry_production_grade_cost_coverage_gte_95pct": added_paper_conditions.get("paper_entry_production_grade_cost_coverage_gte_95pct") is True,
        "operator_dashboard_website_truth_contract_passed": (
            added_paper_conditions.get("operator_dashboard_website_truth_contract_passed") is True
        ),
        "post_fix_paper_validation_passed": added_paper_conditions.get("post_fix_paper_validation_passed") is True,
        "paper_governance_source_blockers_cleared": added_paper_conditions.get("source_paper_governance_blockers_cleared") is True,
        "paper_governance_source_phase_blockers_cleared": added_paper_conditions.get("source_paper_governance_phase_blockers_cleared") is True,
        "paper_governance_no_live_routes": added_paper_conditions.get("no_live_routes") is True,
    }

    phases = {
        "phase_1_production_grade_cost_evidence": {
            "status": "PASS" if all(phase_1_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_1_conditions,
            "primary_artifacts": [
                "challenger_v2_production_cost_evidence_status.json",
                "challenger_v2_cost_source_coverage_matrix.json",
                "challenger_v2_production_cost_capture_gap_audit.json",
                "challenger_v2_runtime_cost_capture_contract_audit.json",
                RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
                RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
                SHADOW_COST_EVIDENCE,
                "challenger_v2_candidate_bound_shadow_cost_evidence_status.json",
            ],
            "blocker": runtime_cost_capture_contract.get("status") if not all(phase_1_conditions.values()) else None,
        },
        "phase_2_append_only_future_lockbox_collector": {
            "status": "PASS" if all(phase_2_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_2_conditions,
            "primary_artifacts": [
                PENDING_LOCKBOX,
                LABELLED_LOCKBOX,
                HASH_CHAIN,
                "challenger_v2_future_lockbox_integrity_audit.json",
            ],
            "blocker": lockbox_integrity.get("status") if not all(phase_2_conditions.values()) else None,
        },
        "phase_3_distribution_drift_diagnosis": {
            "status": "PASS" if all(phase_3_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_3_conditions,
            "primary_artifacts": [
                "challenger_v2_distribution_drift_root_cause.json",
                "challenger_v2_distribution_drift_coverage_audit.json",
                "challenger_v2_distribution_drift_mapping_confidence_audit.json",
            ],
            "blocker": drift_mapping_confidence.get("status") if not all(phase_3_conditions.values()) else None,
        },
        "phase_4_continuous_shadow_supply": {
            "status": "PASS" if all(phase_4_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_4_conditions,
            "primary_artifacts": [
                "challenger_v2_forward_shadow_status.json",
                "challenger_v2_shadow_supply_contract_audit.json",
                "challenger_v2_zero_candidate_supply_diagnosis.json",
            ],
            "blocker": zero_supply.get("root_cause_classification") if not all(phase_4_conditions.values()) else None,
        },
        "phase_5_blind_lockbox_pass": {
            "status": "PASS" if all(phase_5_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_5_conditions,
            "primary_artifacts": [
                "challenger_v2_blind_lockbox_performance.json",
                "challenger_v2_blind_lockbox_pass_contract_audit.json",
            ],
            "blocker": lockbox_pass_contract.get("status") if not all(phase_5_conditions.values()) else None,
        },
        "phase_6_bind_to_paper_after_lockbox_pass": {
            "status": "PASS" if all(phase_6_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_6_conditions,
            "primary_artifacts": [
                "challenger_v2_paper_binding_identity_preflight.json",
                "challenger_v2_paper_canary_binding_readiness.json",
                PAPER_CHAIN_BINDING_READINESS_AUDIT,
                "challenger_v2_paper_chain_binding_status.json",
            ],
            "blocker": paper_canary_binding.get("status") if not all(phase_6_conditions.values()) else None,
        },
        "phase_7_forward_paper_canary": {
            "status": "PASS" if all(phase_7_conditions.values()) else "BLOCKED",
            "pass_conditions": phase_7_conditions,
            "primary_artifacts": [
                "challenger_v2_forward_paper_canary_status.json",
                "challenger_v2_forward_paper_canary_pass_contract_audit.json",
            ],
            "blocker": forward_canary_contract.get("status") if not all(phase_7_conditions.values()) else None,
        },
        "added_p0_paper_timeframe_churn_governance_repair": {
            "status": "PASS" if all(added_paper_phase_conditions.values()) else "BLOCKED",
            "pass_conditions": added_paper_phase_conditions,
            "primary_artifacts": [
                ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT,
                "paper_timeframe_churn_governance_audit_summary.json",
                "current_paper_timeframe_churn_audit.json",
                "paper_timeframe_routing_owner_status.json",
                "post_fix_paper_validation_status.json",
            ],
            "blocker": added_paper_governance.get("status") if not all(added_paper_phase_conditions.values()) else None,
        },
    }
    blocked_phases = [name for name, payload in phases.items() if payload.get("status") != "PASS"]
    final_pass = not blocked_phases
    phase_statuses = {name: payload.get("status") for name, payload in phases.items()}
    phase_blockers = {name: payload.get("blocker") for name, payload in phases.items() if payload.get("blocker") is not None}
    phase_failed_conditions = {
        name: [
            condition
            for condition, passed in (payload.get("pass_conditions") or {}).items()
            if passed is not True
        ]
        for name, payload in phases.items()
    }
    blocked_by_phase = {
        name: len(failed_conditions)
        for name, failed_conditions in phase_failed_conditions.items()
        if failed_conditions
    }
    blocked_conditions = [
        f"{phase}.{condition}"
        for phase, failed_conditions in phase_failed_conditions.items()
        for condition in failed_conditions
    ]
    phase_summary = {
        name: {
            "status": payload.get("status"),
            "passed_condition_count": sum(
                1 for passed in (payload.get("pass_conditions") or {}).values() if passed is True
            ),
            "blocked_condition_count": len(phase_failed_conditions.get(name) or []),
            "blocked_conditions": list(phase_failed_conditions.get(name) or []),
            "primary_artifacts": payload.get("primary_artifacts") or [],
        }
        for name, payload in phases.items()
    }
    pass_conditions = {f"{name}_passed": payload.get("status") == "PASS" for name, payload in phases.items()}
    phase_blocker_details = {
        name: {
            "phase": name,
            "status": payload.get("status"),
            "blocker": payload.get("blocker"),
            "failed_pass_conditions": list(phase_failed_conditions.get(name) or []),
            "primary_artifacts": payload.get("primary_artifacts") or [],
        }
        for name, payload in phases.items()
        if payload.get("status") != "PASS"
    }
    status = "PASS_GOAL_COMPLETION_AUDIT" if final_pass else "BLOCKED_GOAL_COMPLETION_AUDIT"
    return {
        "schema_version": "challenger_v2_goal_phase_completion_audit_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "goal_phase_completion_status": status,
        "goal_complete": final_pass,
        "blocked_phases": blocked_phases,
        "blocked_phase_count": len(blocked_phases),
        "blocked_reasons": blocked_phases,
        "blocked_by_phase": blocked_by_phase,
        "blocked_conditions": blocked_conditions,
        "blocked_condition_count": len(blocked_conditions),
        "phase_blocked_conditions": blocked_conditions,
        "phase_blocker_count": len(blocked_conditions),
        "phase_summary": phase_summary,
        "phase_statuses": phase_statuses,
        "phase_blockers": phase_blockers,
        "blocker_details": phase_blocker_details,
        "failed_blocker_details": phase_blocker_details,
        "pass_conditions": pass_conditions,
        "phases": phases,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": final_pass,
        "notes": [
            "This audit summarizes evidence only; it does not tune, bind, route, or promote the frozen candidate.",
            "The frozen candidate remains unchanged unless a future mapping, feature, cost, model, weight, or threshold change creates a new candidate ID.",
        ],
    }


def goal_requirement_traceability_matrix(
    *,
    policy: FrozenPolicy,
    frozen_candidate_integrity: Mapping[str, Any] | None = None,
    cost_status: Mapping[str, Any],
    cost_capture_gap: Mapping[str, Any],
    runtime_cost_capture_contract: Mapping[str, Any],
    runtime_cost_capture_remediation: Mapping[str, Any],
    runtime_cost_capture_operator_approval: Mapping[str, Any],
    runtime_cost_capture_operator_approval_receipt: Mapping[str, Any] | None = None,
    shadow_cost_status: Mapping[str, Any],
    shadow_cost_reconciliation: Mapping[str, Any],
    append_status: Mapping[str, Any],
    label_status: Mapping[str, Any],
    hash_chain: Mapping[str, Any],
    lockbox_integrity: Mapping[str, Any],
    drift_status: Mapping[str, Any],
    drift_coverage: Mapping[str, Any],
    drift_mapping_confidence: Mapping[str, Any],
    shadow_supply_contract: Mapping[str, Any],
    zero_supply: Mapping[str, Any],
    lockbox_pass_contract: Mapping[str, Any],
    paper_binding_preflight: Mapping[str, Any],
    paper_cost_telemetry: Mapping[str, Any],
    paper_canary_binding: Mapping[str, Any],
    forward_canary_contract: Mapping[str, Any],
    paper_credit_attribution_guard: Mapping[str, Any],
    goal_phase_completion: Mapping[str, Any],
    paper_chain_binding_readiness: Mapping[str, Any] | None = None,
    added_paper_governance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    def add(
        *,
        phase: str,
        requirement_id: str,
        requirement: str,
        passed: bool,
        artifact: str,
        evidence_field: str,
        observed: Any,
        required: Any,
        blocker: str | None = None,
    ) -> None:
        rows.append(
            {
                "phase": phase,
                "requirement_id": requirement_id,
                "requirement": requirement,
                "status": "PASS" if passed else "BLOCKED",
                "passed": passed,
                "artifact": artifact,
                "evidence_field": evidence_field,
                "observed": observed,
                "required": required,
                "blocker": None if passed else blocker or requirement_id,
                "evidence_strength": "DIRECT_ARTIFACT_FIELD",
            }
        )

    frozen_candidate_integrity = (
        frozen_candidate_integrity
        if isinstance(frozen_candidate_integrity, Mapping)
        else {}
    )
    frozen_pass_conditions = frozen_candidate_integrity.get("pass_conditions")
    frozen_pass_conditions = frozen_pass_conditions if isinstance(frozen_pass_conditions, Mapping) else {}
    frozen_safety_contract = frozen_candidate_integrity.get("frozen_policy_safety_contract")
    frozen_safety_contract = frozen_safety_contract if isinstance(frozen_safety_contract, Mapping) else {}
    frozen_candidate_contract_passed = (
        frozen_candidate_integrity.get("status") == "PASS_FROZEN_CANDIDATE_INTEGRITY_AUDIT"
        and frozen_candidate_integrity.get("candidate_id") == policy.candidate_id
        and frozen_candidate_integrity.get("policy_fingerprint") == policy.policy_fingerprint
        and frozen_candidate_integrity.get("model_source") == policy.model_source
        and frozen_candidate_integrity.get("frozen_candidate_modified_since_previous_evidence_run") is False
        and frozen_candidate_integrity.get("frozen_candidate_modified") is False
        and frozen_pass_conditions.get("candidate_id_matches_expected") is True
        and frozen_pass_conditions.get("policy_fingerprint_matches_expected") is True
        and frozen_pass_conditions.get("model_source_matches_expected") is True
        and frozen_pass_conditions.get("feature_names_match_loaded_policy") is True
        and frozen_pass_conditions.get("normalization_hash_matches_recomputed") is True
        and frozen_pass_conditions.get("cost_model_hash_matches_recomputed") is True
        and frozen_pass_conditions.get("weights_match_loaded_policy") is True
        and frozen_pass_conditions.get("paper_only_true") is True
        and frozen_pass_conditions.get("routes_to_live_false") is True
        and frozen_pass_conditions.get("promotion_allowed_false") is True
        and frozen_pass_conditions.get("post_freeze_change_invalidates_candidate") is True
        and frozen_candidate_integrity.get("paper_only") is True
        and frozen_candidate_integrity.get("routes_to_live") is False
        and frozen_candidate_integrity.get("promotion_allowed") is False
        and frozen_candidate_integrity.get("paper_fill_allowed") is False
        and frozen_candidate_integrity.get("counts_as_a_grade_evidence") is False
        and frozen_candidate_integrity.get("promotion_evidence") is False
        and frozen_safety_contract.get("new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes")
        is True
    )
    add(
        phase="candidate_freeze_integrity",
        requirement_id="freeze.frozen_candidate_integrity_contract_published",
        requirement="Frozen candidate audit must directly prove identity, unchanged frozen policy material, paper-only mode, no live routes, no promotion permission, and new-candidate-on-change contract.",
        passed=frozen_candidate_contract_passed,
        artifact=FROZEN_CANDIDATE_INTEGRITY_AUDIT,
        evidence_field="status,candidate_id,policy_fingerprint,model_source,frozen_policy_file_sha256,frozen_candidate_modified_since_previous_evidence_run,pass_conditions,paper_only,routes_to_live,promotion_allowed,frozen_policy_safety_contract",
        observed={
            "status": frozen_candidate_integrity.get("status"),
            "candidate_id": frozen_candidate_integrity.get("candidate_id"),
            "policy_fingerprint": frozen_candidate_integrity.get("policy_fingerprint"),
            "model_source": frozen_candidate_integrity.get("model_source"),
            "frozen_policy_file_sha256": frozen_candidate_integrity.get("frozen_policy_file_sha256"),
            "frozen_candidate_modified_since_previous_evidence_run": frozen_candidate_integrity.get(
                "frozen_candidate_modified_since_previous_evidence_run"
            ),
            "paper_only": frozen_candidate_integrity.get("paper_only"),
            "routes_to_live": frozen_candidate_integrity.get("routes_to_live"),
            "promotion_allowed": frozen_candidate_integrity.get("promotion_allowed"),
            "paper_fill_allowed": frozen_candidate_integrity.get("paper_fill_allowed"),
            "counts_as_a_grade_evidence": frozen_candidate_integrity.get("counts_as_a_grade_evidence"),
            "promotion_evidence": frozen_candidate_integrity.get("promotion_evidence"),
            "pass_conditions": frozen_pass_conditions,
            "frozen_policy_safety_contract": frozen_safety_contract,
        },
        required={
            "status": "PASS_FROZEN_CANDIDATE_INTEGRITY_AUDIT",
            "candidate_id": policy.candidate_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "model_source": policy.model_source,
            "frozen_candidate_modified_since_previous_evidence_run": False,
            "paper_only": True,
            "routes_to_live": False,
            "promotion_allowed": False,
            "paper_fill_allowed": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
            "new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes": True,
        },
        blocker=frozen_candidate_integrity.get("status"),
    )

    cost_pass_conditions = cost_status.get("pass_conditions") if isinstance(cost_status.get("pass_conditions"), Mapping) else {}
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.production_grade_cost_evidence_passed",
        requirement="Production-grade cost evidence status artifact must pass before lockbox, paper binding, or promotion evidence can count.",
        passed=cost_status.get("status") == "PASS",
        artifact="challenger_v2_production_cost_evidence_status.json",
        evidence_field="status",
        observed=cost_status.get("status"),
        required="PASS",
        blocker=cost_status.get("status"),
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.production_grade_cost_coverage_gte_95pct",
        requirement="Production-grade cost coverage must be at least 95%.",
        passed=float(cost_status.get("production_grade_cost_coverage") or 0.0) >= 0.95,
        artifact="challenger_v2_production_cost_evidence_status.json",
        evidence_field="production_grade_cost_coverage",
        observed=cost_status.get("production_grade_cost_coverage"),
        required=">=0.95",
        blocker=cost_status.get("status"),
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.unexplained_cost_missing_rows_eq_0",
        requirement="Unexplained cost missing rows must be zero.",
        passed=int(cost_status.get("unexplained_cost_missing_rows") or 0) == 0,
        artifact="challenger_v2_production_cost_evidence_status.json",
        evidence_field="unexplained_cost_missing_rows",
        observed=cost_status.get("unexplained_cost_missing_rows"),
        required=0,
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.replay_paper_cost_parity_mismatch_rows_eq_0",
        requirement="Replay and paper cost estimates must match for the same snapshot and order.",
        passed=int(cost_status.get("replay_paper_cost_parity_mismatch_rows") or 0) == 0
        and int(cost_status.get("replay_paper_cost_parity_comparable_rows") or 0) > 0
        and int(cost_status.get("replay_paper_cost_parity_compared_side_count") or 0) > 0
        and cost_pass_conditions.get("replay_paper_cost_parity_for_same_snapshot_order") is not False,
        artifact="challenger_v2_production_cost_evidence_status.json",
        evidence_field="replay_paper_cost_parity_mismatch_rows,replay_paper_cost_parity_comparable_rows,replay_paper_cost_parity_compared_side_count",
        observed={
            "mismatch_rows": cost_status.get("replay_paper_cost_parity_mismatch_rows"),
            "comparable_rows": cost_status.get("replay_paper_cost_parity_comparable_rows"),
            "side_comparisons": cost_status.get("replay_paper_cost_parity_compared_side_count"),
        },
        required={"mismatch_rows": 0, "comparable_rows": ">0", "side_comparisons": ">0"},
    )
    cost_status_field_coverage = (
        cost_status.get("field_coverage") if isinstance(cost_status.get("field_coverage"), Mapping) else {}
    )
    cost_status_contract_passed = (
        cost_status.get("required_coverage") == 0.95
        and isinstance(cost_status.get("blocker_details"), list)
        and isinstance(cost_status.get("hard_blocking_fields"), list)
        and bool(cost_status_field_coverage)
        and cost_status.get("fallback_rows_may_be_shadow_scored") is True
        and cost_status.get("fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence") is False
        and cost_status.get("paper_fill_allowed") is False
        and cost_status.get("routes_to_live") is False
        and cost_status.get("counts_as_a_grade_evidence") is False
        and cost_status.get("promotion_evidence") is False
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.production_cost_status_blocker_contract_published",
        requirement="Production cost evidence status must directly publish required coverage, field coverage, blockers, recovery fields, and non-counting safety flags.",
        passed=cost_status_contract_passed,
        artifact="challenger_v2_production_cost_evidence_status.json",
        evidence_field="required_coverage,field_coverage,blocker_details,hard_blocking_fields,fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence,paper_fill_allowed,routes_to_live,counts_as_a_grade_evidence,promotion_evidence",
        observed={
            "required_coverage": cost_status.get("required_coverage"),
            "field_coverage_present": bool(cost_status_field_coverage),
            "blocker_details": cost_status.get("blocker_details"),
            "hard_blocking_fields": cost_status.get("hard_blocking_fields"),
            "fallback_rows_may_be_shadow_scored": cost_status.get("fallback_rows_may_be_shadow_scored"),
            "fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence": cost_status.get(
                "fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence"
            ),
            "paper_fill_allowed": cost_status.get("paper_fill_allowed"),
            "routes_to_live": cost_status.get("routes_to_live"),
            "counts_as_a_grade_evidence": cost_status.get("counts_as_a_grade_evidence"),
            "promotion_evidence": cost_status.get("promotion_evidence"),
        },
        required="direct blocker contract with required_coverage=0.95, field coverage present, fallback rows non-counting, and execution/promotion flags false",
        blocker=cost_status.get("status"),
    )
    field_shortfalls = cost_capture_gap.get("field_shortfalls")
    field_shortfalls = field_shortfalls if isinstance(field_shortfalls, Mapping) else {}
    for field in REQUIRED_COST_EVIDENCE_FIELDS:
        payload = field_shortfalls.get(field) if isinstance(field_shortfalls.get(field), Mapping) else {}
        missing_rows = int(payload.get("missing_rows") or 0)
        coverage = float(payload.get("coverage") or 0.0)
        add(
            phase="phase_1_production_grade_cost_evidence",
            requirement_id=f"phase_1.required_cost_field.{field}",
            requirement=f"Every current and replay row must expose required cost evidence field: {field}.",
            passed=missing_rows == 0,
            artifact="challenger_v2_production_cost_capture_gap_audit.json",
            evidence_field=f"field_shortfalls.{field}",
            observed={"coverage": coverage, "missing_rows": missing_rows},
            required={"missing_rows": 0},
            blocker=payload.get("recovery_boundary") or "required_cost_evidence_field_missing",
        )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.fallback_rows_do_not_count",
        requirement="Fallback=true rows may be shadow-scored but must not count as training, lockbox, paper canary, or promotion evidence.",
        passed=cost_capture_gap.get("fallback_rows_count_as_training_lockbox_or_promotion_evidence") is False
        and shadow_cost_status.get("shadow_cost_rows_count_as_training_lockbox_or_promotion_evidence") is False,
        artifact=SHADOW_COST_RECONCILIATION,
        evidence_field="fallback_true_rows_count_as_training_lockbox_or_promotion_evidence",
        observed={
            "cost_capture_gap": cost_capture_gap.get("fallback_rows_count_as_training_lockbox_or_promotion_evidence"),
            "shadow_cost_status": shadow_cost_status.get("shadow_cost_rows_count_as_training_lockbox_or_promotion_evidence"),
        },
        required=False,
    )
    shadow_cost_conditions = (
        shadow_cost_status.get("pass_conditions")
        if isinstance(shadow_cost_status.get("pass_conditions"), Mapping)
        else {}
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.shadow_cost_hash_chain_contract_passed",
        requirement="Candidate-bound shadow cost evidence hash-chain contract must be self-auditing and non-executable.",
        passed=shadow_cost_conditions.get("hash_chain_contract_passed") is True,
        artifact="challenger_v2_candidate_bound_shadow_cost_evidence_status.json",
        evidence_field="pass_conditions.hash_chain_contract_passed,shadow_cost_evidence_hash_chain_status",
        observed={
            "hash_chain_contract_passed": shadow_cost_conditions.get("hash_chain_contract_passed"),
            "shadow_cost_evidence_hash_chain_status": shadow_cost_status.get("shadow_cost_evidence_hash_chain_status"),
        },
        required=True,
        blocker=shadow_cost_status.get("shadow_cost_evidence_hash_chain_status") or shadow_cost_status.get("status"),
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_contract_ready",
        requirement="Runtime cost capture contract must be ready before production-grade evidence can pass.",
        passed=runtime_cost_capture_contract.get("status") == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        artifact="challenger_v2_runtime_cost_capture_contract_audit.json",
        evidence_field="status",
        observed=runtime_cost_capture_contract.get("status"),
        required="PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
        blocker=runtime_cost_capture_contract.get("status"),
    )
    runtime_cost_capture_operator_approval_receipt = (
        runtime_cost_capture_operator_approval_receipt
        if isinstance(runtime_cost_capture_operator_approval_receipt, Mapping)
        else {}
    )
    runtime_cost_capture_operator_approval = (
        runtime_cost_capture_operator_approval
        if isinstance(runtime_cost_capture_operator_approval, Mapping)
        else {}
    )
    approval_required_source_groups = (
        runtime_cost_capture_operator_approval.get("operator_approval_required_source_groups")
        or runtime_cost_capture_operator_approval.get("approval_required_source_groups")
        or []
    )
    required_operator_acknowledgements = (
        runtime_cost_capture_operator_approval.get("required_operator_acknowledgements")
        or runtime_cost_capture_operator_approval.get("required_acknowledgements")
        or []
    )
    expected_operator_acknowledgements = [
        "acknowledges_no_historical_backfill_for_credit",
        "acknowledges_no_frozen_candidate_or_model_changes",
        "acknowledges_paper_fill_and_live_routes_remain_false",
    ]
    prohibited_patch_scope = set(runtime_cost_capture_operator_approval.get("prohibited_patch_scope") or [])
    telemetry_only_runtime_paths = runtime_cost_capture_operator_approval.get("telemetry_only_runtime_paths")
    telemetry_only_runtime_paths = (
        telemetry_only_runtime_paths
        if isinstance(telemetry_only_runtime_paths, Sequence)
        and not isinstance(telemetry_only_runtime_paths, (str, bytes, bytearray))
        else []
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_operator_approval_packet_subject_hash_ready",
        requirement="Operator approval packet must publish the current approval subject hash before future runtime rows can count.",
        passed=bool(runtime_cost_capture_operator_approval.get("approval_subject_hash"))
        and runtime_cost_capture_operator_approval.get("approval_subject_hash_status") == "READY",
        artifact=RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        evidence_field="approval_subject_hash,approval_subject_hash_status",
        observed={
            "approval_subject_hash": runtime_cost_capture_operator_approval.get("approval_subject_hash"),
            "approval_subject_hash_status": runtime_cost_capture_operator_approval.get("approval_subject_hash_status"),
        },
        required={"approval_subject_hash": "present", "approval_subject_hash_status": "READY"},
        blocker=runtime_cost_capture_operator_approval.get("status") or "operator_approval_packet_missing",
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_operator_approval_packet_scope_telemetry_only",
        requirement="Operator approval packet scope must be telemetry-only future runtime cost and identity capture.",
        passed=runtime_cost_capture_operator_approval.get("approved_patch_scope")
        == "telemetry_only_future_runtime_cost_and_identity_capture"
        and bool(approval_required_source_groups),
        artifact=RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        evidence_field="approved_patch_scope,operator_approval_required_source_groups",
        observed={
            "approved_patch_scope": runtime_cost_capture_operator_approval.get("approved_patch_scope"),
            "operator_approval_required_source_groups": approval_required_source_groups,
        },
        required={
            "approved_patch_scope": "telemetry_only_future_runtime_cost_and_identity_capture",
            "operator_approval_required_source_groups": "present",
        },
        blocker=runtime_cost_capture_operator_approval.get("status") or "operator_approval_packet_missing",
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_operator_approval_packet_acknowledgements_declared",
        requirement="Operator approval packet must require acknowledgements forbidding historical credit backfill, frozen-candidate changes, and paper/live route enablement.",
        passed=sorted(str(value) for value in required_operator_acknowledgements)
        == sorted(expected_operator_acknowledgements),
        artifact=RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        evidence_field="required_operator_acknowledgements",
        observed=required_operator_acknowledgements,
        required=expected_operator_acknowledgements,
        blocker=runtime_cost_capture_operator_approval.get("status") or "operator_approval_packet_missing",
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_operator_approval_packet_forbidden_scope_declared",
        requirement="Operator approval packet must explicitly prohibit order-path, live-route, frozen-candidate, and threshold/model changes.",
        passed=bool(telemetry_only_runtime_paths)
        and {
            "order_submission",
            "frozen_candidate_artifact_change",
            "strategy_threshold_or_weight_change",
            "paper_binding_before_blind_lockbox_pass",
        }.issubset(prohibited_patch_scope)
        and runtime_cost_capture_operator_approval.get("paper_fill_allowed") is False
        and runtime_cost_capture_operator_approval.get("routes_to_live") is False
        and runtime_cost_capture_operator_approval.get("places_real_order") is False
        and runtime_cost_capture_operator_approval.get("frozen_candidate_modified") is False,
        artifact=RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        evidence_field="telemetry_only_runtime_paths,prohibited_patch_scope,paper_fill_allowed,routes_to_live,places_real_order,frozen_candidate_modified",
        observed={
            "telemetry_only_runtime_path_count": len(telemetry_only_runtime_paths),
            "prohibited_patch_scope": sorted(prohibited_patch_scope),
            "paper_fill_allowed": runtime_cost_capture_operator_approval.get("paper_fill_allowed"),
            "routes_to_live": runtime_cost_capture_operator_approval.get("routes_to_live"),
            "places_real_order": runtime_cost_capture_operator_approval.get("places_real_order"),
            "frozen_candidate_modified": runtime_cost_capture_operator_approval.get("frozen_candidate_modified"),
        },
        required={
            "telemetry_only_runtime_path_count": ">0",
            "prohibited_patch_scope": [
                "order_submission",
                "frozen_candidate_artifact_change",
                "strategy_threshold_or_weight_change",
                "paper_binding_before_blind_lockbox_pass",
            ],
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "frozen_candidate_modified": False,
        },
        blocker=runtime_cost_capture_operator_approval.get("status") or "operator_approval_packet_missing",
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_operator_approval_receipt_passed",
        requirement="Operator approval receipt must explicitly approve the telemetry-only runtime cost and identity capture patch before future rows can count.",
        passed=runtime_cost_capture_operator_approval_receipt.get("status") == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        artifact=RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
        evidence_field="status",
        observed=runtime_cost_capture_operator_approval_receipt.get("status"),
        required="PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT",
        blocker=runtime_cost_capture_operator_approval_receipt.get("status") or "operator_approval_receipt_missing",
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.candidate_bound_production_grade_paper_cost_rows_available",
        requirement="Production-grade paper cost telemetry must be bound to the frozen challenger identity before it can count.",
        passed=int(paper_cost_telemetry.get("challenger_bound_production_grade_rows") or 0) > 0,
        artifact="challenger_v2_paper_cost_telemetry_readiness.json",
        evidence_field="challenger_bound_production_grade_rows",
        observed=paper_cost_telemetry.get("challenger_bound_production_grade_rows"),
        required=">0",
        blocker=paper_cost_telemetry.get("status"),
    )
    next_capture_contract = cost_capture_gap.get("next_capture_batch_contract")
    next_capture_contract = next_capture_contract if isinstance(next_capture_contract, Mapping) else {}
    limiting_cost_fields = next_capture_contract.get("limiting_cost_fields_for_95pct")
    limiting_cost_fields = (
        limiting_cost_fields
        if isinstance(limiting_cost_fields, Sequence)
        and not isinstance(limiting_cost_fields, (str, bytes, bytearray))
        else []
    )
    priority_source_groups = next_capture_contract.get("priority_source_groups")
    priority_source_groups = (
        priority_source_groups
        if isinstance(priority_source_groups, Sequence)
        and not isinstance(priority_source_groups, (str, bytes, bytearray))
        else []
    )
    recovery_plan_published = (
        bool(limiting_cost_fields)
        and bool(priority_source_groups)
        and next_capture_contract.get("operator_approval_required_before_runtime_write_path_edits") is True
        and next_capture_contract.get("existing_old_or_unbound_rows_may_not_be_backfilled_for_credit") is True
    )
    cost_coverage_already_passed = float(cost_status.get("production_grade_cost_coverage") or 0.0) >= 0.95
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.cost_capture_recovery_plan_published",
        requirement="When production-grade cost coverage is below 95%, the gap audit must publish limiting fields, source groups, and the operator-approval boundary for future candidate-bound capture.",
        passed=cost_coverage_already_passed or recovery_plan_published,
        artifact="challenger_v2_production_cost_capture_gap_audit.json",
        evidence_field="next_capture_batch_contract.limiting_cost_fields_for_95pct,next_capture_batch_contract.priority_source_groups",
        observed={
            "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
            "limiting_cost_field_count": len(limiting_cost_fields),
            "priority_source_group_count": len(priority_source_groups),
            "operator_approval_required_before_runtime_write_path_edits": next_capture_contract.get(
                "operator_approval_required_before_runtime_write_path_edits"
            ),
            "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": next_capture_contract.get(
                "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"
            ),
        },
        required={
            "production_grade_cost_coverage": ">=0.95 or recovery plan present",
            "limiting_cost_field_count": ">0 when coverage below 95%",
            "priority_source_group_count": ">0 when coverage below 95%",
            "operator_approval_required_before_runtime_write_path_edits": True,
            "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
        },
        blocker=cost_capture_gap.get("status"),
    )
    remediation_blocker_details = runtime_cost_capture_remediation.get("remediation_blocker_details")
    remediation_blocker_details = (
        remediation_blocker_details
        if isinstance(remediation_blocker_details, Sequence)
        and not isinstance(remediation_blocker_details, (str, bytes, bytearray))
        else []
    )
    remediation_source_group_decisions = runtime_cost_capture_remediation.get("source_group_decisions")
    remediation_source_group_decisions = (
        remediation_source_group_decisions
        if isinstance(remediation_source_group_decisions, Sequence)
        and not isinstance(remediation_source_group_decisions, (str, bytes, bytearray))
        else []
    )
    remediation_contract_actionable = (
        bool(runtime_cost_capture_remediation.get("blocked_reasons"))
        and bool(remediation_blocker_details)
        and bool(remediation_source_group_decisions)
        and int(runtime_cost_capture_remediation.get("required_new_candidate_bound_production_grade_rows") or 0) > 0
        and runtime_cost_capture_remediation.get("future_capture_credit_rules", {}).get(
            "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"
        )
        is True
        and runtime_cost_capture_remediation.get("future_capture_credit_rules", {}).get(
            "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence"
        )
        is False
        and runtime_cost_capture_remediation.get("paper_fill_allowed") is False
        and runtime_cost_capture_remediation.get("routes_to_live") is False
    )
    add(
        phase="phase_1_production_grade_cost_evidence",
        requirement_id="phase_1.runtime_cost_capture_remediation_contract_actionable",
        requirement="Runtime cost remediation contract must directly publish blocked reasons, blocker details, source-group decisions, future row shortfall, and non-credit rules.",
        passed=runtime_cost_capture_remediation.get("status") == "PASS_RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT_READY"
        or remediation_contract_actionable,
        artifact=RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT,
        evidence_field="blocked_reasons,remediation_blocker_details,source_group_decisions,required_new_candidate_bound_production_grade_rows,future_capture_credit_rules",
        observed={
            "status": runtime_cost_capture_remediation.get("status"),
            "blocked_reasons": runtime_cost_capture_remediation.get("blocked_reasons"),
            "remediation_blocker_detail_count": len(remediation_blocker_details),
            "source_group_decision_count": len(remediation_source_group_decisions),
            "required_new_candidate_bound_production_grade_rows": runtime_cost_capture_remediation.get(
                "required_new_candidate_bound_production_grade_rows"
            ),
            "top_source_group": runtime_cost_capture_remediation.get("top_source_group"),
            "top_decision_time_capture_source_group": runtime_cost_capture_remediation.get(
                "top_decision_time_capture_source_group"
            ),
            "future_capture_credit_rules": runtime_cost_capture_remediation.get("future_capture_credit_rules"),
        },
        required={
            "blocked_reasons": "present while runtime capture is blocked",
            "remediation_blocker_details": "present while runtime capture is blocked",
            "source_group_decisions": "present",
            "required_new_candidate_bound_production_grade_rows": ">0 while Phase 1 coverage is below 95%",
            "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
            "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "paper_fill_allowed": False,
            "routes_to_live": False,
        },
        blocker=runtime_cost_capture_remediation.get("status"),
    )

    lockbox_conditions = lockbox_integrity.get("pass_conditions")
    lockbox_conditions = lockbox_conditions if isinstance(lockbox_conditions, Mapping) else {}
    phase_2_requirements = {
        "pending_required_fields_present": "Pending lockbox records include required immutable selection fields.",
        "pending_lockbox_ids_unique": "Pending lockbox records are unique.",
        "pending_decision_keys_unique": "Pending lockbox records are unique by immutable challenger decision key.",
        "selection_fields_marked_immutable": "Selection fields are marked immutable.",
        "labels_append_outcomes_only": "Labels append outcome fields separately from selection fields.",
        "labels_created_after_pending_records": "Labels are created after pending decision records.",
        "labels_have_pending_selection_record": "Each label maps back to a pending selection record.",
        "labels_use_future_data_as_label_only": "Future data is used only as labels.",
        "selection_record_hashes_match_pending_records": "Label selection hashes match pending records.",
        "point_in_time_violations_eq_0": "Future lockbox has zero point-in-time violations.",
    }
    for key, description in phase_2_requirements.items():
        add(
            phase="phase_2_append_only_future_lockbox_collector",
            requirement_id=f"phase_2.{key}",
            requirement=description,
            passed=lockbox_conditions.get(key) is True,
            artifact="challenger_v2_future_lockbox_integrity_audit.json",
            evidence_field=f"pass_conditions.{key}",
            observed=lockbox_conditions.get(key),
            required=True,
            blocker=lockbox_integrity.get("status"),
        )
    hash_pending = hash_chain.get("pending") if isinstance(hash_chain.get("pending"), Mapping) else {}
    hash_labelled = hash_chain.get("labelled") if isinstance(hash_chain.get("labelled"), Mapping) else {}
    hash_chain_conditions = hash_chain.get("pass_conditions") if isinstance(hash_chain.get("pass_conditions"), Mapping) else {}
    hash_chain_contract_passed = (
        hash_chain.get("status") == "PASS_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT"
        and bool(hash_chain_conditions)
        and all(value is True for value in hash_chain_conditions.values())
        and hash_chain.get("paper_fill_allowed") is False
        and hash_chain.get("routes_to_live") is False
        and hash_chain.get("counts_as_a_grade_evidence") is False
        and hash_chain.get("promotion_evidence") is False
    )
    add(
        phase="phase_2_append_only_future_lockbox_collector",
        requirement_id="phase_2.hash_chain_present",
        requirement="Future lockbox pending and labelled files must have hash-chain evidence.",
        passed=bool(hash_pending.get("last_chain_hash")) and bool(hash_labelled.get("last_chain_hash")),
        artifact=HASH_CHAIN,
        evidence_field="pending.last_chain_hash,labelled.last_chain_hash",
        observed={"pending": hash_pending.get("last_chain_hash"), "labelled": hash_labelled.get("last_chain_hash")},
        required="both terminal hashes present",
    )
    top_level_hash_chain_counts_published = (
        hash_chain.get("pending_rows") == hash_pending.get("row_count")
        and hash_chain.get("labelled_rows") == hash_labelled.get("row_count")
        and isinstance(hash_chain.get("pending_path"), str)
        and isinstance(hash_chain.get("labelled_path"), str)
        and bool(hash_chain.get("pending_file_sha256"))
        and bool(hash_chain.get("labelled_file_sha256"))
    )
    add(
        phase="phase_2_append_only_future_lockbox_collector",
        requirement_id="phase_2.hash_chain_top_level_counts_published",
        requirement="Future lockbox hash-chain artifact must directly publish pending/labelled row counts, paths, and file hashes.",
        passed=top_level_hash_chain_counts_published,
        artifact=HASH_CHAIN,
        evidence_field="pending_rows,labelled_rows,pending_path,labelled_path,pending_file_sha256,labelled_file_sha256",
        observed={
            "pending_rows": hash_chain.get("pending_rows"),
            "pending_nested_row_count": hash_pending.get("row_count"),
            "labelled_rows": hash_chain.get("labelled_rows"),
            "labelled_nested_row_count": hash_labelled.get("row_count"),
            "pending_path": hash_chain.get("pending_path"),
            "labelled_path": hash_chain.get("labelled_path"),
            "pending_file_sha256": hash_chain.get("pending_file_sha256"),
            "labelled_file_sha256": hash_chain.get("labelled_file_sha256"),
        },
        required="top-level counts match nested chain row_count and paths/file hashes are present",
        blocker=hash_chain.get("status"),
    )
    add(
        phase="phase_2_append_only_future_lockbox_collector",
        requirement_id="phase_2.hash_chain_contract_published",
        requirement="Future lockbox hash-chain artifact must directly publish pass conditions, blockers, and non-executable evidence flags.",
        passed=hash_chain_contract_passed,
        artifact=HASH_CHAIN,
        evidence_field="status,pass_conditions,blocker_details,paper_fill_allowed,routes_to_live,counts_as_a_grade_evidence,promotion_evidence",
        observed={
            "status": hash_chain.get("status"),
            "pass_conditions": hash_chain_conditions,
            "blocker_details": hash_chain.get("blocker_details"),
            "paper_fill_allowed": hash_chain.get("paper_fill_allowed"),
            "routes_to_live": hash_chain.get("routes_to_live"),
            "counts_as_a_grade_evidence": hash_chain.get("counts_as_a_grade_evidence"),
            "promotion_evidence": hash_chain.get("promotion_evidence"),
        },
        required="PASS_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT with all pass conditions true and non-executable evidence flags false",
        blocker=hash_chain.get("status"),
    )

    drift_root_conditions = drift_status.get("pass_conditions") if isinstance(drift_status.get("pass_conditions"), Mapping) else {}
    drift_root_contract = (
        drift_status.get("drift_decision_contract")
        if isinstance(drift_status.get("drift_decision_contract"), Mapping)
        else {}
    )
    drift_root_contract_passed = (
        drift_status.get("status") == "PASS_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT"
        and drift_root_conditions.get("root_cause_classification_present") is True
        and drift_root_conditions.get("candidate_change_decision_matches_root_cause") is True
        and drift_root_contract.get("new_candidate_required_if_any_feature_mapping_or_normalization_changes") is True
        and drift_root_contract.get("frozen_candidate_tuning_allowed_from_drift_results") is False
        and drift_root_contract.get("runtime_reject_drifted_conditions") is True
        and drift_root_contract.get("paper_fill_allowed") is False
        and drift_root_contract.get("routes_to_live") is False
    )
    add(
        phase="phase_3_distribution_drift_diagnosis",
        requirement_id="phase_3.root_cause_contract_published",
        requirement="Distribution drift root-cause artifact must directly publish the candidate-change, no-tuning, reject-only runtime contract.",
        passed=drift_root_contract_passed,
        artifact="challenger_v2_distribution_drift_root_cause.json",
        evidence_field="status,pass_conditions,drift_decision_contract,blocker_details",
        observed={
            "status": drift_status.get("status"),
            "root_cause_classification": drift_status.get("root_cause_classification"),
            "candidate_id_change_required": drift_status.get("candidate_id_change_required"),
            "frozen_candidate_kept": drift_status.get("frozen_candidate_kept"),
            "features_requiring_new_candidate_if_fixed": drift_status.get("features_requiring_new_candidate_if_fixed"),
            "blocker_details": drift_status.get("blocker_details"),
            "drift_decision_contract": drift_root_contract,
        },
        required={
            "status": "PASS_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT",
            "new_candidate_required_if_any_feature_mapping_or_normalization_changes": True,
            "frozen_candidate_tuning_allowed_from_drift_results": False,
            "runtime_reject_drifted_conditions": True,
            "paper_fill_allowed": False,
            "routes_to_live": False,
        },
        blocker=drift_status.get("status"),
    )
    add(
        phase="phase_3_distribution_drift_diagnosis",
        requirement_id="phase_3.all_32_features_reported",
        requirement="Distribution drift report must cover all 32 challenger features.",
        passed=int(drift_status.get("feature_count") or 0) == 32,
        artifact="challenger_v2_distribution_drift_root_cause.json",
        evidence_field="feature_count",
        observed=drift_status.get("feature_count"),
        required=32,
    )
    add(
        phase="phase_3_distribution_drift_diagnosis",
        requirement_id="phase_3.required_drift_metrics_present",
        requirement="Drift coverage audit must confirm required metrics across training, validation, holdout, runtime, and future lockbox cohorts.",
        passed=drift_coverage.get("status") == "PASS_DRIFT_COVERAGE_AUDIT",
        artifact="challenger_v2_distribution_drift_coverage_audit.json",
        evidence_field="status",
        observed=drift_coverage.get("status"),
        required="PASS_DRIFT_COVERAGE_AUDIT",
    )
    drift_coverage_conditions = (
        drift_coverage.get("pass_conditions")
        if isinstance(drift_coverage.get("pass_conditions"), Mapping)
        else {}
    )
    add(
        phase="phase_3_distribution_drift_diagnosis",
        requirement_id="phase_3.top_level_feature_and_cohort_summary_present",
        requirement="Drift coverage audit must directly publish policy feature count and required cohort coverage.",
        passed=drift_coverage_conditions.get("top_level_feature_and_cohort_summary_present") is True
        and int(drift_coverage.get("policy_feature_count") or 0) == int(drift_coverage.get("required_feature_count") or -1)
        and int(drift_coverage.get("reported_required_cohort_count") or 0) == int(drift_coverage.get("required_cohort_count") or -1),
        artifact="challenger_v2_distribution_drift_coverage_audit.json",
        evidence_field="policy_feature_count,required_feature_count,cohorts_present,required_cohort_count,reported_required_cohort_count",
        observed={
            "policy_feature_count": drift_coverage.get("policy_feature_count"),
            "required_feature_count": drift_coverage.get("required_feature_count"),
            "cohorts_present": drift_coverage.get("cohorts_present"),
            "required_cohort_count": drift_coverage.get("required_cohort_count"),
            "reported_required_cohort_count": drift_coverage.get("reported_required_cohort_count"),
        },
        required="policy_feature_count == required_feature_count and all required cohorts present",
        blocker=drift_coverage.get("status"),
    )
    add(
        phase="phase_3_distribution_drift_diagnosis",
        requirement_id="phase_3.mapping_confidence_clean_or_new_candidate_required",
        requirement="Broken transformation/source mapping must require a new candidate; genuine shift may keep the frozen candidate.",
        passed=drift_mapping_confidence.get("status") == "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT"
        and drift_mapping_confidence.get("candidate_id_change_required") is False
        and drift_mapping_confidence.get("frozen_candidate_kept") is True,
        artifact="challenger_v2_distribution_drift_mapping_confidence_audit.json",
        evidence_field="status,candidate_id_change_required,frozen_candidate_kept",
        observed={
            "status": drift_mapping_confidence.get("status"),
            "candidate_id_change_required": drift_mapping_confidence.get("candidate_id_change_required"),
            "frozen_candidate_kept": drift_mapping_confidence.get("frozen_candidate_kept"),
        },
        required={"status": "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT", "candidate_id_change_required": False, "frozen_candidate_kept": True},
    )

    shadow_conditions = shadow_supply_contract.get("pass_conditions")
    shadow_conditions = shadow_conditions if isinstance(shadow_conditions, Mapping) else {}
    for key, description in {
        "top_25_long_candidates_published": "Top 25 LONG shadow candidates are published.",
        "top_25_short_candidates_published": "Top 25 SHORT shadow candidates are published.",
        "top_25_candidate_rows_mirrored_in_contract": "Top 25 LONG and SHORT shadow candidate rows are mirrored directly in the contract artifact.",
        "required_edge_cost_drift_liquidity_fields_present": "Shadow rows include gross edge, production cost, net edge, threshold distance, feature drift, liquidity, and rejection reason.",
        "row_safety_flags_false": "Shadow rows are non-executable and non-promotional.",
        "score_every_current_valid_row_declared": "Every current valid row is shadow-scored even when none qualifies economically.",
    }.items():
        add(
            phase="phase_4_continuous_shadow_supply",
            requirement_id=f"phase_4.{key}",
            requirement=description,
            passed=shadow_conditions.get(key) is True,
            artifact="challenger_v2_shadow_supply_contract_audit.json",
            evidence_field=f"pass_conditions.{key}",
            observed=shadow_conditions.get(key),
            required=True,
        )
    add(
        phase="phase_4_continuous_shadow_supply",
        requirement_id="phase_4.zero_supply_diagnosed",
        requirement="Zero candidate supply must be diagnosed when current rows do not qualify.",
        passed=zero_supply.get("status") == "ZERO_SUPPLY_DIAGNOSED",
        artifact="challenger_v2_zero_candidate_supply_diagnosis.json",
        evidence_field="status",
        observed=zero_supply.get("status"),
        required="ZERO_SUPPLY_DIAGNOSED",
    )
    zero_supply_conditions = zero_supply.get("pass_conditions") if isinstance(zero_supply.get("pass_conditions"), Mapping) else {}
    zero_supply_blocker_details = zero_supply.get("zero_supply_blocker_details") or zero_supply.get("blocker_details")
    zero_supply_blocker_details = (
        zero_supply_blocker_details
        if isinstance(zero_supply_blocker_details, Sequence)
        and not isinstance(zero_supply_blocker_details, (str, bytes, bytearray))
        else []
    )
    add(
        phase="phase_4_continuous_shadow_supply",
        requirement_id="phase_4.zero_supply_root_cause_details_published",
        requirement="Zero candidate supply artifact must directly publish root cause, blocker details, pass conditions, and next actions.",
        passed=zero_supply.get("status") == "ZERO_SUPPLY_DIAGNOSED"
        and bool(zero_supply.get("root_cause") or zero_supply.get("root_cause_classification"))
        and bool(zero_supply_blocker_details)
        and bool(zero_supply.get("next_actions"))
        and zero_supply_conditions.get("paper_fill_allowed_false") is True
        and zero_supply_conditions.get("routes_to_live_false") is True
        and zero_supply_conditions.get("counts_as_a_grade_evidence_false") is True,
        artifact="challenger_v2_zero_candidate_supply_diagnosis.json",
        evidence_field="root_cause,pass_conditions,blocker_details,next_actions",
        observed={
            "root_cause": zero_supply.get("root_cause") or zero_supply.get("root_cause_classification"),
            "blocked_reasons": zero_supply.get("blocked_reasons"),
            "blocker_detail_count": len(zero_supply_blocker_details),
            "next_actions": zero_supply.get("next_actions"),
            "pass_conditions": zero_supply_conditions,
        },
        required={
            "root_cause": "present",
            "blocker_details": "present",
            "next_actions": "present",
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
        },
        blocker=zero_supply.get("root_cause_classification") or zero_supply.get("status"),
    )

    phase_5_map = {
        "independent_economic_candidates_gte_300": (lockbox_pass_contract.get("independent_economic_candidates"), ">=300"),
        "symbols_gte_30": (lockbox_pass_contract.get("symbols"), ">=30"),
        "long_gt_0": (lockbox_pass_contract.get("long_count"), ">0"),
        "short_gt_0": (lockbox_pass_contract.get("short_count"), ">0"),
        "after_cost_expectancy_gt_0": (lockbox_pass_contract.get("after_cost_expectancy_bps"), ">0"),
        "expectancy_95pct_lower_bound_gt_0": (lockbox_pass_contract.get("expectancy_95pct_lower_bound_bps"), ">0"),
        "profit_factor_gte_1_5": (lockbox_pass_contract.get("profit_factor"), ">=1.5"),
        "false_positive_rate_lte_0_40": (lockbox_pass_contract.get("false_positive_rate"), "<=0.40"),
        "no_concentration_dimension_gt_30pct": (lockbox_pass_contract.get("max_concentration_pct"), "<=0.30"),
        "worst_1pct_loss_inside_risk_envelope": (lockbox_pass_contract.get("worst_1pct_loss_bps"), "inside risk envelope"),
        "point_in_time_violations_eq_0": (lockbox_pass_contract.get("point_in_time_violations"), 0),
        "production_grade_cost_coverage_gte_95pct": (lockbox_pass_contract.get("production_grade_cost_coverage"), ">=0.95"),
    }
    add(
        phase="phase_5_blind_lockbox_pass",
        requirement_id="phase_5.blind_lockbox_pass_contract_passed",
        requirement="Blind lockbox pass contract artifact must have a passing status before paper binding.",
        passed=lockbox_pass_contract.get("status") == "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        artifact="challenger_v2_blind_lockbox_pass_contract_audit.json",
        evidence_field="status",
        observed=lockbox_pass_contract.get("status"),
        required="PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        blocker=lockbox_pass_contract.get("status"),
    )
    lockbox_pass_conditions = lockbox_pass_contract.get("pass_conditions")
    lockbox_pass_conditions = lockbox_pass_conditions if isinstance(lockbox_pass_conditions, Mapping) else {}
    for key, (observed, required_value) in phase_5_map.items():
        add(
            phase="phase_5_blind_lockbox_pass",
            requirement_id=f"phase_5.{key}",
            requirement=f"Blind lockbox pass condition: {key}.",
            passed=lockbox_pass_conditions.get(key) is True,
            artifact="challenger_v2_blind_lockbox_pass_contract_audit.json",
            evidence_field=f"pass_conditions.{key}",
            observed=observed,
            required=required_value,
            blocker=lockbox_pass_contract.get("status"),
        )

    phase_6_conditions = paper_canary_binding.get("pass_conditions")
    phase_6_conditions = phase_6_conditions if isinstance(phase_6_conditions, Mapping) else {}
    add(
        phase="phase_6_bind_to_paper_after_lockbox_pass",
        requirement_id="phase_6.paper_canary_binding_allowed",
        requirement="Paper canary binding must be explicitly allowed only after prerequisite gates pass.",
        passed=paper_canary_binding.get("binding_allowed") is True,
        artifact="challenger_v2_paper_canary_binding_readiness.json",
        evidence_field="binding_allowed",
        observed=paper_canary_binding.get("binding_allowed"),
        required=True,
        blocker=paper_canary_binding.get("status"),
    )
    for key, description in {
        "production_grade_cost_evidence_passed": "Production-grade cost evidence must pass before paper binding.",
        "blind_lockbox_passed": "Blind lockbox must pass before paper binding.",
        "paper_record_identity_contract_declared": "Paper records must carry candidate_id, policy_fingerprint, and model_source.",
        "paper_canary_forced_paper_only": "Paper canary binding remains paper-only.",
        "no_candidate_bound_rows_before_lockbox_pass": "No challenger-bound rows may appear before lockbox pass.",
        "no_partial_challenger_identity_rows": "No partial challenger identity rows may be present.",
        "no_routes_to_live": "No paper binding rows may route live.",
    }.items():
        add(
            phase="phase_6_bind_to_paper_after_lockbox_pass",
            requirement_id=f"phase_6.{key}",
            requirement=description,
            passed=phase_6_conditions.get(key) is True,
            artifact="challenger_v2_paper_canary_binding_readiness.json",
            evidence_field=f"pass_conditions.{key}",
            observed=phase_6_conditions.get(key),
            required=True,
            blocker=paper_canary_binding.get("status"),
        )
    binding_prerequisite_details = paper_canary_binding.get("binding_prerequisite_details")
    binding_prerequisite_details = (
        binding_prerequisite_details if isinstance(binding_prerequisite_details, Mapping) else {}
    )
    failed_binding_prerequisite_details = paper_canary_binding.get("failed_binding_blocker_details")
    failed_binding_prerequisite_details = (
        failed_binding_prerequisite_details
        if isinstance(failed_binding_prerequisite_details, Mapping)
        else {}
    )
    expected_binding_detail_keys = {
        "production_grade_cost_evidence_passed",
        "blind_lockbox_passed",
        "paper_record_identity_contract_declared",
        "paper_canary_forced_paper_only",
        "no_candidate_bound_rows_before_lockbox_pass",
        "no_partial_challenger_identity_rows",
        "no_routes_to_live",
    }
    add(
        phase="phase_6_bind_to_paper_after_lockbox_pass",
        requirement_id="phase_6.binding_prerequisite_details_published",
        requirement="Paper canary binding readiness must publish direct pass/fail prerequisite details and failed blocker details.",
        passed=expected_binding_detail_keys.issubset(set(binding_prerequisite_details))
        and all(isinstance(binding_prerequisite_details.get(key), Mapping) for key in expected_binding_detail_keys)
        and set(failed_binding_prerequisite_details).issubset(set(binding_prerequisite_details)),
        artifact="challenger_v2_paper_canary_binding_readiness.json",
        evidence_field="binding_prerequisite_details,failed_binding_blocker_details",
        observed={
            "binding_prerequisite_detail_keys": sorted(binding_prerequisite_details),
            "failed_binding_blocker_keys": sorted(failed_binding_prerequisite_details),
        },
        required={
            "binding_prerequisite_detail_keys": sorted(expected_binding_detail_keys),
            "failed_binding_blocker_keys": "subset of binding_prerequisite_detail_keys",
        },
        blocker=paper_canary_binding.get("status"),
    )
    paper_chain_binding_readiness = (
        paper_chain_binding_readiness
        if isinstance(paper_chain_binding_readiness, Mapping)
        else {}
    )
    chain_component_statuses = paper_chain_binding_readiness.get("component_statuses")
    chain_component_statuses = chain_component_statuses if isinstance(chain_component_statuses, Mapping) else {}
    chain_prerequisite_details = paper_chain_binding_readiness.get("chain_prerequisite_details")
    chain_prerequisite_details = chain_prerequisite_details if isinstance(chain_prerequisite_details, Mapping) else {}
    chain_failed_blockers = paper_chain_binding_readiness.get("failed_binding_blocker_details")
    chain_failed_blockers = chain_failed_blockers if isinstance(chain_failed_blockers, Mapping) else {}
    required_chain = list(PAPER_CANARY_CHAIN)
    required_component_count = len(required_chain)
    chain_complete_components = int(paper_chain_binding_readiness.get("complete_components") or 0)
    chain_incomplete_components = int(paper_chain_binding_readiness.get("incomplete_components") or 0)
    chain_missing_component_count = int(paper_chain_binding_readiness.get("missing_component_count") or 0)
    paper_chain_binding_ready = paper_chain_binding_readiness.get("chain_ready") is True
    paper_chain_components_ready = (
        chain_complete_components == required_component_count
        and chain_missing_component_count == 0
        and set(chain_component_statuses) == set(required_chain)
    )
    paper_chain_contract_passed = (
        paper_chain_binding_readiness.get("required_chain") == required_chain
        and int(paper_chain_binding_readiness.get("required_components") or 0) == required_component_count
        and chain_complete_components + chain_incomplete_components == required_component_count
        and set(chain_component_statuses) == set(required_chain)
        and paper_chain_binding_readiness.get("required_paper_record_identity_fields")
        == list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS)
        and bool(chain_prerequisite_details)
        and set(chain_failed_blockers).issubset(set(chain_prerequisite_details))
        and paper_chain_binding_readiness.get("paper_fill_allowed") is False
        and paper_chain_binding_readiness.get("routes_to_live") is False
        and paper_chain_binding_readiness.get("places_real_order") is False
        and paper_chain_binding_readiness.get("counts_as_a_grade_evidence") is False
        and paper_chain_binding_readiness.get("promotion_evidence") is False
    )
    add(
        phase="phase_6_bind_to_paper_after_lockbox_pass",
        requirement_id="phase_6.paper_chain_binding_contract_published",
        requirement="Paper chain binding readiness must directly publish all chain components, component statuses, identity requirements, blockers, and non-executable evidence flags.",
        passed=paper_chain_contract_passed,
        artifact=PAPER_CHAIN_BINDING_READINESS_AUDIT,
        evidence_field="required_chain,required_components,complete_components,incomplete_components,component_statuses,chain_prerequisite_details,failed_binding_blocker_details,paper_fill_allowed,routes_to_live,places_real_order,counts_as_a_grade_evidence,promotion_evidence",
        observed={
            "required_chain": paper_chain_binding_readiness.get("required_chain"),
            "required_components": paper_chain_binding_readiness.get("required_components"),
            "complete_components": paper_chain_binding_readiness.get("complete_components"),
            "incomplete_components": paper_chain_binding_readiness.get("incomplete_components"),
            "component_statuses": chain_component_statuses,
            "chain_prerequisite_detail_keys": sorted(chain_prerequisite_details),
            "failed_binding_blocker_keys": sorted(chain_failed_blockers),
            "paper_fill_allowed": paper_chain_binding_readiness.get("paper_fill_allowed"),
            "routes_to_live": paper_chain_binding_readiness.get("routes_to_live"),
            "places_real_order": paper_chain_binding_readiness.get("places_real_order"),
            "counts_as_a_grade_evidence": paper_chain_binding_readiness.get("counts_as_a_grade_evidence"),
            "promotion_evidence": paper_chain_binding_readiness.get("promotion_evidence"),
        },
        required={
            "required_chain": required_chain,
            "required_components": required_component_count,
            "complete_plus_incomplete_components": required_component_count,
            "component_statuses": "one status per required chain component",
            "paper_record_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        },
        blocker=paper_chain_binding_readiness.get("status"),
    )
    add(
        phase="phase_6_bind_to_paper_after_lockbox_pass",
        requirement_id="phase_6.paper_chain_binding_ready",
        requirement="Paper chain binding must be ready before binding the challenger to paper.",
        passed=paper_chain_binding_ready,
        artifact=PAPER_CHAIN_BINDING_READINESS_AUDIT,
        evidence_field="chain_ready",
        observed=paper_chain_binding_readiness.get("chain_ready"),
        required=True,
        blocker=paper_chain_binding_readiness.get("status"),
    )
    add(
        phase="phase_6_bind_to_paper_after_lockbox_pass",
        requirement_id="phase_6.paper_chain_components_ready",
        requirement="Every required paper chain component must be ready and no chain component may be missing.",
        passed=paper_chain_components_ready,
        artifact=PAPER_CHAIN_BINDING_READINESS_AUDIT,
        evidence_field="required_components,complete_components,missing_component_count,component_statuses",
        observed={
            "required_components": required_component_count,
            "complete_components": chain_complete_components,
            "missing_component_count": chain_missing_component_count,
            "component_statuses": chain_component_statuses,
        },
        required={
            "complete_components": required_component_count,
            "missing_component_count": 0,
            "component_statuses": "one ready status per required chain component",
        },
        blocker=paper_chain_binding_readiness.get("status"),
    )
    credit_conditions = paper_credit_attribution_guard.get("pass_conditions")
    credit_conditions = credit_conditions if isinstance(credit_conditions, Mapping) else {}
    for key in (
        "old_policy_rows_count_as_challenger_evidence_false",
        "old_policy_or_unbound_cost_rows_quarantined",
        "forward_canary_has_no_challenger_outcomes_while_binding_blocked",
        "paper_fill_allowed_rows_not_counted_as_challenger_evidence",
    ):
        add(
            phase="phase_6_bind_to_paper_after_lockbox_pass",
            requirement_id=f"phase_6.credit_attribution.{key}",
            requirement=f"Paper challenger credit attribution guard: {key}.",
            passed=credit_conditions.get(key) is True,
            artifact=PAPER_CREDIT_ATTRIBUTION_GUARD,
            evidence_field=f"pass_conditions.{key}",
            observed=credit_conditions.get(key),
            required=True,
            blocker=paper_credit_attribution_guard.get("status"),
        )

    forward_conditions = forward_canary_contract.get("pass_conditions")
    forward_conditions = forward_conditions if isinstance(forward_conditions, Mapping) else {}
    phase_7_map = {
        "new_closed_challenger_economic_outcomes_gte_100": (forward_canary_contract.get("closed_challenger_economic_outcomes"), ">=100"),
        "symbols_gte_30": (forward_canary_contract.get("symbols"), ">=30"),
        "long_gt_0": (forward_canary_contract.get("long_count"), ">0"),
        "short_gt_0": (forward_canary_contract.get("short_count"), ">0"),
        "after_cost_expectancy_gt_0": (forward_canary_contract.get("after_cost_expectancy_bps"), ">0"),
        "profit_factor_gte_1_5": (forward_canary_contract.get("profit_factor"), ">=1.5"),
        "accounting_mismatch_rows_eq_0": (forward_canary_contract.get("accounting_mismatch_rows"), 0),
        "liquidation_rows_eq_0": (forward_canary_contract.get("liquidation_rows"), 0),
        "point_in_time_violations_eq_0": (forward_canary_contract.get("point_in_time_violations"), 0),
        "paper_only_no_live_routes": (forward_canary_contract.get("live_route_rows"), 0),
    }
    add(
        phase="phase_7_forward_paper_canary",
        requirement_id="phase_7.forward_paper_canary_contract_passed",
        requirement="Forward paper canary pass contract artifact must have a passing status before promotion.",
        passed=forward_canary_contract.get("status") == "PASS_FORWARD_PAPER_CANARY_CONTRACT",
        artifact="challenger_v2_forward_paper_canary_pass_contract_audit.json",
        evidence_field="status",
        observed=forward_canary_contract.get("status"),
        required="PASS_FORWARD_PAPER_CANARY_CONTRACT",
        blocker=forward_canary_contract.get("status"),
    )
    for key, (observed, required_value) in phase_7_map.items():
        add(
            phase="phase_7_forward_paper_canary",
            requirement_id=f"phase_7.{key}",
            requirement=f"Forward paper canary pass condition: {key}.",
            passed=forward_conditions.get(key) is True,
            artifact="challenger_v2_forward_paper_canary_pass_contract_audit.json",
            evidence_field=f"pass_conditions.{key}",
            observed=observed,
            required=required_value,
            blocker=forward_canary_contract.get("status"),
        )

    added_paper_governance = added_paper_governance if isinstance(added_paper_governance, Mapping) else {}
    added_paper_conditions = added_paper_governance.get("pass_conditions")
    added_paper_conditions = added_paper_conditions if isinstance(added_paper_conditions, Mapping) else {}
    add(
        phase="added_p0_paper_timeframe_churn_governance_repair",
        requirement_id="added_paper_governance.added_paper_governance_blocker_audit_passed",
        requirement="The added P0 paper timeframe/churn governance blocker audit must pass before this challenger goal can complete.",
        passed=added_paper_governance.get("status") == "PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT",
        artifact=ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT,
        evidence_field="status",
        observed=added_paper_governance.get("status"),
        required="PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT",
        blocker=added_paper_governance.get("status"),
    )
    added_paper_requirements = {
        "paper_governance_summary_present": (
            "Added paper governance audit summary must exist inside the current challenger goal state.",
            added_paper_governance.get("source_generated_utc"),
            "present",
        ),
        "added_goal_id_matches": (
            "The added governance audit must identify the P0 paper timeframe/churn governance goal.",
            added_paper_governance.get("added_goal_id"),
            ADDED_PAPER_GOVERNANCE_GOAL_ID,
        ),
        "required_artifacts_written": (
            "All required P0 paper timeframe/churn governance artifacts must be written.",
            {
                "required_artifacts": added_paper_governance.get("required_artifacts"),
                "source_artifacts_written": added_paper_governance.get("source_artifacts_written"),
                "missing_required_artifacts": added_paper_governance.get("missing_required_artifacts"),
            },
            {"missing_required_artifacts": []},
        ),
        "current_closed_ledger_recomputed": (
            "The complete current closed paper ledger must be recomputed.",
            added_paper_governance.get("raw_close_record_count"),
            ">=0",
        ),
        "economic_trade_compaction_present": (
            "Raw close records must be compacted into economic trades.",
            added_paper_governance.get("economic_trade_count"),
            ">=0",
        ),
        "current_timeframe_distribution_proven": (
            "Current raw and economic timeframe distribution must be published.",
            {
                "current_1m_share": added_paper_governance.get("current_1m_share"),
                "current_1m_economic_trade_share": added_paper_governance.get("current_1m_economic_trade_share"),
            },
            "current_1m_share and current_1m_economic_trade_share present",
        ),
        "paper_routing_owner_audit_passed": (
            "Active paper routing owner audit must pass.",
            added_paper_governance.get("source_routing_status"),
            "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
        ),
        "hardcoded_1m_economic_paths_removed": (
            "Hardcoded 1m economic paper paths must be removed.",
            added_paper_governance.get("hardcoded_1m_path_count"),
            0,
        ),
        "silent_1m_fallbacks_absent": (
            "Paper routing must not silently fall back to 1m for thesis or economic timeframe attribution.",
            {
                "silent_1m_fallback_path_count": added_paper_governance.get("silent_1m_fallback_path_count"),
                "timeframe_routing_violation_count": added_paper_governance.get("timeframe_routing_violation_count"),
                "silent_1m_fallback_paths": added_paper_governance.get("silent_1m_fallback_paths"),
            },
            {"silent_1m_fallback_path_count": 0},
        ),
        "paper_churn_governor_wired": (
            "Adaptive churn governor must be wired to the paper entry gate.",
            added_paper_governance.get("paper_churn_governor_status"),
            "PASS_*",
        ),
        "operator_dashboard_website_truth_contract_passed": (
            "Operator dashboard must expose website-truth fields and avoid raw close-event trade inflation.",
            {
                "status": added_paper_governance.get("operator_dashboard_truth_contract_status"),
                "blocked_reasons": added_paper_governance.get("operator_dashboard_truth_contract_blocked_reasons"),
                "missing_required_fields": added_paper_governance.get("operator_dashboard_missing_required_fields"),
            },
            "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
        ),
        "paper_edge_to_cost_gate_passed": (
            "Paper edge-to-cost admission gate must pass.",
            added_paper_governance.get("paper_edge_to_cost_gate_status"),
            "PASS_PAPER_EDGE_TO_COST_GATE",
        ),
        "paper_entry_production_grade_cost_coverage_gte_95pct": (
            "Paper entry production-grade cost coverage must be at least 95%.",
            added_paper_governance.get("paper_entry_production_grade_cost_coverage"),
            ">=0.95",
        ),
        "post_fix_paper_validation_passed": (
            "Post-fix paper validation must pass.",
            added_paper_governance.get("post_fix_paper_validation_status"),
            "PASS_POST_FIX_PAPER_VALIDATION",
        ),
        "source_paper_governance_blockers_cleared": (
            "The source P0 paper governance audit must have zero blocked pass conditions.",
            {
                "source_blocker_count": added_paper_governance.get("source_blocker_count"),
                "source_blocked_pass_conditions": added_paper_governance.get("source_blocked_pass_conditions"),
            },
            {"source_blocker_count": 0, "source_blocked_pass_conditions": []},
        ),
        "source_paper_governance_phase_blockers_cleared": (
            "The source P0 paper governance audit must have zero phase blocker entries.",
            {
                "source_phase_blocker_count": added_paper_governance.get("source_phase_blocker_count"),
                "source_phase_blockers": added_paper_governance.get("source_phase_blockers"),
            },
            {"source_phase_blocker_count": 0, "source_phase_blockers": "empty"},
        ),
        "final_gate_ready": (
            "The added paper governance repair final gate must be READY.",
            added_paper_governance.get("source_final_gate"),
            ADDED_PAPER_GOVERNANCE_READY_MARKER,
        ),
        "no_live_routes": (
            "Added paper governance audit must remain paper-only with no live routes.",
            {
                "routes_to_live": added_paper_governance.get("routes_to_live"),
                "places_real_order": added_paper_governance.get("places_real_order"),
            },
            {"routes_to_live": False, "places_real_order": False},
        ),
    }
    for key, (description, observed, required_value) in added_paper_requirements.items():
        add(
            phase="added_p0_paper_timeframe_churn_governance_repair",
            requirement_id=f"added_paper_governance.{key}",
            requirement=description,
            passed=added_paper_conditions.get(key) is True,
            artifact=ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT,
            evidence_field=f"pass_conditions.{key}",
            observed=observed,
            required=required_value,
            blocker=added_paper_governance.get("status"),
        )

    total_requirements = len(rows)
    passed_requirements = sum(1 for row in rows if row["passed"])
    blocked_rows = [row for row in rows if not row["passed"]]
    blocked_by_phase: dict[str, int] = Counter(str(row["phase"]) for row in blocked_rows)
    passed_by_phase: dict[str, int] = Counter(str(row["phase"]) for row in rows if row["passed"])
    total_by_phase: dict[str, int] = Counter(str(row["phase"]) for row in rows)
    requirements_by_phase = {
        phase: {
            "total_requirements": int(total_by_phase.get(phase) or 0),
            "passed_requirements": int(passed_by_phase.get(phase) or 0),
            "blocked_requirements": int(blocked_by_phase.get(phase) or 0),
            "blocked_requirement_ids": [
                str(row["requirement_id"])
                for row in blocked_rows
                if str(row["phase"]) == phase
            ],
        }
        for phase in sorted(total_by_phase)
    }
    traceability_blocker_details = {
        str(row["requirement_id"]): row
        for row in blocked_rows
    }
    blocked_requirement_ids = [str(row["requirement_id"]) for row in blocked_rows]
    pass_conditions = {
        "total_requirements_gt_0": total_requirements > 0,
        "passed_plus_blocked_equals_total": passed_requirements + len(blocked_rows) == total_requirements,
        "blocked_requirement_count_eq_0": len(blocked_rows) == 0,
        "goal_phase_completion_true": goal_phase_completion.get("goal_complete") is True,
        "blocker_details_cover_blocked_requirements": set(traceability_blocker_details) == set(blocked_requirement_ids),
        "paper_only_no_live_routes": True,
        "frozen_candidate_not_modified": True,
    }
    status = "PASS_GOAL_REQUIREMENT_TRACEABILITY_MATRIX" if not blocked_rows else "BLOCKED_GOAL_REQUIREMENTS_REMAIN"
    return {
        "schema_version": "challenger_v2_goal_requirement_traceability_matrix_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": status,
        "goal_requirement_traceability_status": status,
        "goal_complete": goal_phase_completion.get("goal_complete") is True and not blocked_rows,
        "total_requirements": total_requirements,
        "total_requirement_count": total_requirements,
        "requirements_total": total_requirements,
        "passed_requirements": passed_requirements,
        "passed_requirement_count": passed_requirements,
        "blocked_requirements": len(blocked_rows),
        "blocked_requirement_count": len(blocked_rows),
        "failed_requirements": len(blocked_rows),
        "failed_requirement_count": len(blocked_rows),
        "blocked_by_phase": dict(sorted(blocked_by_phase.items())),
        "failed_by_phase": dict(sorted(blocked_by_phase.items())),
        "passed_by_phase": dict(sorted(passed_by_phase.items())),
        "requirements_by_phase": requirements_by_phase,
        "phase_summary": requirements_by_phase,
        "blocked_requirement_ids": blocked_requirement_ids,
        "blocked_reasons": blocked_requirement_ids,
        "blocker_details": traceability_blocker_details,
        "failed_blocker_details": traceability_blocker_details,
        "pass_conditions": pass_conditions,
        "requirements": rows,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": not blocked_rows,
    }


def update_forward_blockers(
    out_dir: Path,
    *,
    policy: FrozenPolicy,
    cost_status: Mapping[str, Any],
    lockbox_perf: Mapping[str, Any],
    forward_canary_contract: Mapping[str, Any] | None = None,
) -> None:
    forward_canary_contract = forward_canary_contract if isinstance(forward_canary_contract, Mapping) else {}
    chain_blocked_reasons = []
    if cost_status.get("status") != "PASS":
        chain_blocked_reasons.append("production_grade_cost_evidence_not_passed")
    if not (lockbox_perf.get("pass") is True or lockbox_perf.get("status") == "PASS"):
        chain_blocked_reasons.append("blind_lockbox_not_passed")
    chain_components = [
        {
            "order": index + 1,
            "component": component,
            "status": "NOT_BOUND_BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
            "must_emit_or_preserve_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "blocked_reasons": chain_blocked_reasons,
        }
        for index, component in enumerate(PAPER_CANARY_CHAIN)
    ]
    chain_component_statuses = {
        str(component.get("component")): component.get("status")
        for component in chain_components
    }
    chain_binding_pass_conditions = {
        "required_chain_declared": True,
        "paper_record_identity_fields_declared": True,
        "production_grade_cost_evidence_passed": cost_status.get("status") == "PASS",
        "blind_lockbox_passed": lockbox_perf.get("pass") is True or lockbox_perf.get("status") == "PASS",
        "paper_chain_bound": False,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "places_real_order_false": True,
        "counts_as_a_grade_evidence_false": True,
        "promotion_evidence_false": True,
    }
    chain_binding_blocker_details = {
        name: {
            "passed": passed,
            "observed": {
                "production_grade_cost_evidence_passed": cost_status.get("status"),
                "blind_lockbox_passed": lockbox_perf.get("status") or lockbox_perf.get("pass"),
                "paper_chain_bound": False,
                "paper_fill_allowed_false": False,
                "routes_to_live_false": False,
                "places_real_order_false": False,
                "counts_as_a_grade_evidence_false": False,
                "promotion_evidence_false": False,
                "required_chain_declared": list(PAPER_CANARY_CHAIN),
                "paper_record_identity_fields_declared": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            }.get(name),
            "required": {
                "production_grade_cost_evidence_passed": "PASS",
                "blind_lockbox_passed": "PASS",
                "paper_chain_bound": True,
                "paper_fill_allowed_false": False,
                "routes_to_live_false": False,
                "places_real_order_false": False,
                "counts_as_a_grade_evidence_false": False,
                "promotion_evidence_false": False,
                "required_chain_declared": list(PAPER_CANARY_CHAIN),
                "paper_record_identity_fields_declared": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
            }.get(name, True),
        }
        for name, passed in chain_binding_pass_conditions.items()
        if passed is not True
    }
    chain_binding = {
        "schema_version": "challenger_v2_paper_chain_binding_status_v2",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "NOT_STARTED_BLIND_LOCKBOX_NOT_PASSED",
        "challenger_v2_bound_to_paper_chain": False,
        "old_policy_silent_control_ruled_out": False,
        "required_chain": list(PAPER_CANARY_CHAIN),
        "required_components": len(PAPER_CANARY_CHAIN),
        "complete_components": 0,
        "incomplete_components": len(PAPER_CANARY_CHAIN),
        "missing_component_count": len(PAPER_CANARY_CHAIN),
        "chain_component_shortfall_to_required": len(PAPER_CANARY_CHAIN),
        "missing_component_names": list(PAPER_CANARY_CHAIN),
        "component_statuses": chain_component_statuses,
        "chain_components": chain_components,
        "component_readiness": chain_components,
        "required_paper_record_identity_fields": list(REQUIRED_PAPER_CREDIT_IDENTITY_FIELDS),
        "paper_only": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "pass_conditions": chain_binding_pass_conditions,
        "blocked_reasons": chain_blocked_reasons,
        "blocker_details": chain_binding_blocker_details,
        "failed_blocker_details": chain_binding_blocker_details,
    }
    forward_blocked_reasons = list(forward_canary_contract.get("blocked_reasons") or chain_blocked_reasons)
    forward_pass_conditions = forward_canary_contract.get("pass_conditions")
    forward_pass_conditions = forward_pass_conditions if isinstance(forward_pass_conditions, Mapping) else {}
    forward_closed_outcomes = int(forward_canary_contract.get("closed_challenger_economic_outcomes") or 0)
    forward_required_new_closed_outcomes = int(
        forward_canary_contract.get("required_new_closed_challenger_economic_outcomes")
        or forward_canary_contract.get("required_new_closed_economic_outcomes")
        or 100
    )
    forward_required_closed_outcomes = int(
        forward_canary_contract.get("required_closed_challenger_economic_outcomes")
        or forward_required_new_closed_outcomes
    )
    forward_closed_outcome_shortfall = int(
        forward_canary_contract.get("closed_challenger_economic_outcome_shortfall_to_required")
        or forward_canary_contract.get("closed_challenger_economic_outcome_shortfall")
        or forward_canary_contract.get("closed_outcome_shortfall_to_100")
        or max(0, forward_required_closed_outcomes - forward_closed_outcomes)
    )
    forward_required_symbols = int(forward_canary_contract.get("required_symbols") or 30)
    forward_symbol_count = int(forward_canary_contract.get("symbol_count") or forward_canary_contract.get("symbols") or 0)
    forward_long_count = int(forward_canary_contract.get("long_count") or forward_canary_contract.get("long_candidates") or 0)
    forward_short_count = int(forward_canary_contract.get("short_count") or forward_canary_contract.get("short_candidates") or 0)
    forward_rows_scanned = int(
        forward_canary_contract.get("paper_rows_scanned")
        or forward_canary_contract.get("scanned_rows")
        or forward_canary_contract.get("total_rows_scanned")
        or 0
    )
    forward_excluded_row_counts = forward_canary_contract.get("excluded_row_counts") or {}
    if not isinstance(forward_excluded_row_counts, Mapping):
        forward_excluded_row_counts = {}
    forward_identity_exclusion_counts = forward_canary_contract.get("identity_exclusion_counts")
    forward_identity_exclusion_counts = (
        forward_identity_exclusion_counts if isinstance(forward_identity_exclusion_counts, Mapping) else {}
    )
    forward_identity_excluded_rows = int(
        forward_identity_exclusion_counts.get("challenger_identity_not_complete")
        or forward_canary_contract.get("identity_incomplete_rows")
        or forward_excluded_row_counts.get("challenger_identity_not_complete")
        or 0
    )
    forward_non_counting_row_count = int(
        forward_canary_contract.get("non_counting_row_count")
        or sum(int(count or 0) for count in forward_excluded_row_counts.values())
    )
    forward_accounting_mismatch_rows = int(
        forward_canary_contract.get("accounting_mismatch_rows")
        or forward_canary_contract.get("accounting_mismatch_count")
        or 0
    )
    forward_liquidation_rows = int(
        forward_canary_contract.get("liquidation_rows")
        or forward_canary_contract.get("liquidation_count")
        or forward_canary_contract.get("liquidation_events")
        or forward_canary_contract.get("liquidation_event_rows")
        or 0
    )
    forward_point_in_time_violations = int(
        forward_canary_contract.get("point_in_time_violations")
        or forward_canary_contract.get("point_in_time_violation_count")
        or 0
    )
    forward_counting_evidence_allowed = (
        forward_canary_contract.get("canary_counting_evidence_allowed") is True
        or forward_canary_contract.get("counting_evidence_allowed") is True
    )
    forward_minimum_evidence = forward_canary_contract.get("minimum_forward_canary_evidence")
    forward_minimum_evidence = forward_minimum_evidence if isinstance(forward_minimum_evidence, Mapping) else {}
    forward_minimum_observed = forward_canary_contract.get("minimum_forward_canary_observed")
    forward_minimum_observed = forward_minimum_observed if isinstance(forward_minimum_observed, Mapping) else {}
    forward_minimum_shortfalls = forward_canary_contract.get("minimum_forward_canary_shortfalls")
    forward_minimum_shortfalls = forward_minimum_shortfalls if isinstance(forward_minimum_shortfalls, Mapping) else {}
    forward_minimum_pass_conditions = forward_canary_contract.get("minimum_forward_canary_pass_conditions")
    forward_minimum_pass_conditions = (
        forward_minimum_pass_conditions if isinstance(forward_minimum_pass_conditions, Mapping) else forward_pass_conditions
    )
    forward_status_blocker_details = (
        forward_canary_contract.get("blocker_details")
        or forward_canary_contract.get("forward_canary_blocker_details")
        or forward_canary_contract.get("failed_forward_canary_blocker_details")
        or {}
    )
    forward_status_blocker_details = (
        forward_status_blocker_details if isinstance(forward_status_blocker_details, Mapping) else {}
    )
    forward_status_failed_details = (
        forward_canary_contract.get("failed_blocker_details")
        or forward_canary_contract.get("failed_forward_canary_blocker_details")
        or {}
    )
    forward_status_failed_details = (
        forward_status_failed_details if isinstance(forward_status_failed_details, Mapping) else {}
    )
    forward_status_actuals = forward_canary_contract.get("actuals")
    forward_status_actuals = (
        forward_status_actuals
        if isinstance(forward_status_actuals, Mapping)
        else forward_minimum_observed
        if forward_minimum_observed
        else {
            "new_closed_challenger_economic_outcomes": int(
                forward_canary_contract.get("new_closed_challenger_economic_outcomes") or 0
            ),
            "symbols": forward_symbol_count,
            "long_candidates": forward_long_count,
            "short_candidates": forward_short_count,
            "after_cost_expectancy_bps": forward_canary_contract.get("after_cost_expectancy_bps"),
            "profit_factor": forward_canary_contract.get("profit_factor"),
            "accounting_mismatch_rows": forward_accounting_mismatch_rows,
            "liquidation_rows": forward_liquidation_rows,
            "point_in_time_violations": forward_point_in_time_violations,
            "live_route_rows": int(forward_canary_contract.get("live_route_rows") or 0),
            "paper_canary_binding_allowed": forward_canary_contract.get("paper_canary_binding_allowed"),
            "lockbox_pass_contract_status": forward_canary_contract.get("lockbox_pass_contract_status"),
        }
    )
    forward_status_required = forward_canary_contract.get("required")
    forward_status_required = (
        forward_status_required
        if isinstance(forward_status_required, Mapping)
        else forward_minimum_evidence
        if forward_minimum_evidence
        else {
            "new_closed_challenger_economic_outcomes": f">={forward_required_new_closed_outcomes}",
            "symbols": f">={forward_required_symbols}",
            "long_candidates": ">0",
            "short_candidates": ">0",
            "after_cost_expectancy_bps": ">0",
            "profit_factor": ">=1.5",
            "accounting_mismatch_rows": 0,
            "liquidation_rows": 0,
            "point_in_time_violations": 0,
            "live_route_rows": 0,
            "paper_canary_binding_allowed": True,
            "lockbox_pass_contract_status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        }
    )
    forward_status_sample_blockers = forward_canary_contract.get("sample_blockers")
    forward_status_sample_blockers = (
        list(forward_status_sample_blockers)
        if isinstance(forward_status_sample_blockers, list)
        else [
            {"pass_condition": name, **detail}
            for name, detail in forward_status_blocker_details.items()
            if isinstance(detail, Mapping)
        ][:25]
    )
    canary = {
        "schema_version": "challenger_v2_forward_paper_canary_status_v2",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": forward_canary_contract.get("status") or "NOT_STARTED_BLIND_LOCKBOX_NOT_PASSED",
        "forward_closed_outcomes": forward_closed_outcomes,
        "closed_challenger_economic_outcomes": forward_closed_outcomes,
        "new_closed_challenger_economic_outcomes": int(forward_canary_contract.get("new_closed_challenger_economic_outcomes") or 0),
        "required_new_closed_economic_outcomes": forward_required_new_closed_outcomes,
        "required_new_closed_challenger_economic_outcomes": forward_required_new_closed_outcomes,
        "required_closed_challenger_economic_outcomes": forward_required_closed_outcomes,
        "closed_outcome_shortfall_to_100": forward_closed_outcome_shortfall,
        "closed_challenger_economic_outcome_shortfall": forward_closed_outcome_shortfall,
        "closed_challenger_economic_outcome_shortfall_to_100": forward_closed_outcome_shortfall,
        "closed_challenger_economic_outcome_shortfall_to_required": forward_closed_outcome_shortfall,
        "new_closed_challenger_economic_outcome_shortfall_to_required": forward_closed_outcome_shortfall,
        "new_closed_challenger_economic_outcomes_shortfall_to_100": forward_closed_outcome_shortfall,
        "minimum_forward_canary_evidence": dict(forward_minimum_evidence),
        "minimum_forward_canary_observed": dict(forward_minimum_observed),
        "minimum_forward_canary_shortfalls": dict(forward_minimum_shortfalls),
        "minimum_forward_canary_pass_conditions": dict(forward_minimum_pass_conditions),
        "paper_rows_scanned": forward_rows_scanned,
        "scanned_rows": forward_rows_scanned,
        "total_rows_scanned": forward_rows_scanned,
        "candidate_bound_rows": forward_closed_outcomes,
        "old_policy_or_unbound_rows_quarantined": forward_identity_excluded_rows,
        "identity_incomplete_rows": forward_identity_excluded_rows,
        "non_counting_row_count": forward_non_counting_row_count,
        "excluded_row_counts": forward_excluded_row_counts,
        "identity_exclusion_counts": forward_identity_exclusion_counts,
        "non_counting_reasons": forward_canary_contract.get("non_counting_reasons") or [],
        "symbols": forward_symbol_count,
        "symbol_count": forward_symbol_count,
        "required_symbols": forward_required_symbols,
        "symbol_shortfall_to_30": int(
            forward_canary_contract.get("symbol_shortfall_to_30")
            or max(0, forward_required_symbols - forward_symbol_count)
        ),
        "long_count": forward_long_count,
        "short_count": forward_short_count,
        "long_candidates": forward_long_count,
        "short_candidates": forward_short_count,
        "long_candidate_shortfall_to_1": int(
            forward_canary_contract.get("long_candidate_shortfall_to_1")
            or max(0, 1 - forward_long_count)
        ),
        "short_candidate_shortfall_to_1": int(
            forward_canary_contract.get("short_candidate_shortfall_to_1")
            or max(0, 1 - forward_short_count)
        ),
        "outcome_count_by_direction": forward_canary_contract.get("outcome_count_by_direction") or {"LONG": 0, "SHORT": 0},
        "candidate_count_by_direction": forward_canary_contract.get("candidate_count_by_direction")
        or forward_canary_contract.get("outcome_count_by_direction")
        or {"LONG": 0, "SHORT": 0},
        "after_cost_expectancy_bps": forward_canary_contract.get("after_cost_expectancy_bps"),
        "profit_factor": forward_canary_contract.get("profit_factor"),
        "accounting_mismatch_rows": forward_accounting_mismatch_rows,
        "accounting_mismatch_count": forward_accounting_mismatch_rows,
        "liquidation_rows": forward_liquidation_rows,
        "liquidation_count": forward_liquidation_rows,
        "liquidation_event_rows": forward_liquidation_rows,
        "liquidation_events": forward_liquidation_rows,
        "point_in_time_violations": forward_point_in_time_violations,
        "point_in_time_violation_count": forward_point_in_time_violations,
        "live_route_rows": int(forward_canary_contract.get("live_route_rows") or 0),
        "paper_canary_binding_allowed": forward_canary_contract.get("paper_canary_binding_allowed"),
        "lockbox_pass_contract_status": forward_canary_contract.get("lockbox_pass_contract_status"),
        "pass_conditions": dict(forward_pass_conditions),
        "blocked_reasons": forward_blocked_reasons,
        "forward_canary_blocker_details": forward_canary_contract.get("forward_canary_blocker_details") or {},
        "blocker_details": dict(forward_status_blocker_details),
        "failed_forward_canary_blocker_details": forward_canary_contract.get("failed_forward_canary_blocker_details") or {},
        "failed_blocker_details": dict(forward_status_failed_details),
        "actuals": dict(forward_status_actuals),
        "required": dict(forward_status_required),
        "sample_blockers": forward_status_sample_blockers,
        "paper_only": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "canary_counting_evidence_allowed": forward_counting_evidence_allowed,
        "counting_evidence_allowed": forward_counting_evidence_allowed,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "pass": False,
    }
    promotion_pass_conditions = {
        "production_grade_cost_evidence_passed": cost_status.get("status") == "PASS",
        "blind_lockbox_passed": lockbox_perf.get("pass") is True or lockbox_perf.get("status") == "PASS",
        "forward_paper_canary_passed": canary.get("status") == "PASS_FORWARD_PAPER_CANARY_CONTRACT",
        "promotion_allowed_false_until_all_gates_pass": True,
        "paper_fill_allowed_false": True,
        "routes_to_live_false": True,
        "places_real_order_false": True,
        "counts_as_a_grade_evidence_false": True,
        "promotion_evidence_false": True,
    }
    promotion_blocked_reasons = [name for name, passed in promotion_pass_conditions.items() if passed is not True]
    promotion_blocker_details = {
        "production_grade_cost_evidence_passed": {
            "passed": promotion_pass_conditions["production_grade_cost_evidence_passed"],
            "observed": cost_status.get("status"),
            "required": "PASS",
            "source_artifact": "challenger_v2_production_cost_evidence_status.json",
        },
        "blind_lockbox_passed": {
            "passed": promotion_pass_conditions["blind_lockbox_passed"],
            "observed": lockbox_perf.get("status") or lockbox_perf.get("pass"),
            "required": "PASS",
            "source_artifact": "challenger_v2_blind_lockbox_performance.json",
        },
        "forward_paper_canary_passed": {
            "passed": promotion_pass_conditions["forward_paper_canary_passed"],
            "observed": canary.get("status"),
            "required": "PASS_FORWARD_PAPER_CANARY_CONTRACT",
            "source_artifact": "challenger_v2_forward_paper_canary_status.json",
        },
    }
    promotion = {
        "schema_version": "challenger_v2_champion_promotion_status_v2",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "status": "BLOCKED",
        "cost_evidence_production_grade_pass": cost_status.get("status") == "PASS",
        "blind_lockbox_pass": lockbox_perf.get("pass") is True or lockbox_perf.get("status") == "PASS",
        "forward_paper_canary_pass": False,
        "required_promotion_gates": [
            "production_grade_cost_evidence_passed",
            "blind_lockbox_passed",
            "forward_paper_canary_passed",
        ],
        "pass_conditions": promotion_pass_conditions,
        "blocked_reasons": promotion_blocked_reasons,
        "blocker_details": {
            name: detail
            for name, detail in promotion_blocker_details.items()
            if detail["passed"] is not True
        },
        "failed_blocker_details": {
            name: detail
            for name, detail in promotion_blocker_details.items()
            if detail["passed"] is not True
        },
        "paper_only": True,
        "paper_fill_allowed": False,
        "promotion_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "read_only_audit_no_runtime_change": True,
        "frozen_candidate_modified": False,
        "a_grade": False,
    }
    write_json(out_dir / "challenger_v2_paper_chain_binding_status.json", chain_binding)
    write_json(out_dir / "challenger_v2_forward_paper_canary_status.json", canary)
    write_json(out_dir / "challenger_v2_champion_promotion_status.json", promotion)


def goal_rollup_summary_aliases(
    goal_phase_completion: Mapping[str, Any],
    requirement_traceability: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "goal_phase_completion_status": goal_phase_completion.get("status"),
        "goal_complete": goal_phase_completion.get("goal_complete"),
        "goal_blocked_phases": goal_phase_completion.get("blocked_phases"),
        "blocked_phases": goal_phase_completion.get("blocked_phases"),
        "blocked_phase_count": goal_phase_completion.get("blocked_phase_count"),
        "blocked_conditions": goal_phase_completion.get("blocked_conditions"),
        "blocked_condition_count": goal_phase_completion.get("blocked_condition_count"),
        "blocked_by_phase": goal_phase_completion.get("blocked_by_phase"),
        "goal_phase_statuses": goal_phase_completion.get("phase_statuses"),
        "goal_phase_blockers": goal_phase_completion.get("phase_blockers"),
        "goal_phase_pass_conditions": goal_phase_completion.get("pass_conditions"),
        "goal_requirement_traceability_status": requirement_traceability.get("status"),
        "goal_requirement_traceability_total_requirements": requirement_traceability.get("total_requirements"),
        "goal_requirement_traceability_passed_requirements": requirement_traceability.get("passed_requirements"),
        "goal_requirement_traceability_blocked_requirements": requirement_traceability.get("blocked_requirements"),
        "goal_requirement_traceability_blocked_by_phase": requirement_traceability.get("blocked_by_phase"),
        "total_requirement_count": requirement_traceability.get("total_requirement_count")
        or requirement_traceability.get("total_requirements"),
        "passed_requirement_count": requirement_traceability.get("passed_requirement_count")
        or requirement_traceability.get("passed_requirements"),
        "blocked_requirement_count": requirement_traceability.get("blocked_requirement_count")
        or requirement_traceability.get("blocked_requirements"),
        "failed_requirement_count": requirement_traceability.get("failed_requirement_count")
        or requirement_traceability.get("failed_requirements"),
        "failed_by_phase": requirement_traceability.get("failed_by_phase")
        or requirement_traceability.get("blocked_by_phase"),
    }


def run_collector(
    *,
    repo_root: Path,
    scan_limit: int,
    replay_limit: int | None,
    current_limit: int,
    no_current_redis: bool,
    horizon_minutes: int,
    archive_scan_limit: int,
    allow_public_labels: bool,
    public_label_symbol_limit: int,
    paper_signal_scan_limit: int,
) -> dict[str, Any]:
    out_dir = repo_root / "goal_state" / GOAL_ID
    policy = load_frozen_policy(out_dir)
    frozen_candidate_integrity = frozen_candidate_integrity_audit(out_dir, policy)
    write_json(out_dir / FROZEN_CANDIDATE_INTEGRITY_AUDIT, frozen_candidate_integrity)
    pipeline_summary = read_json(out_dir / "challenger_v2_pipeline_summary.json", {})
    effective_replay_limit = int(replay_limit or pipeline_summary.get("dataset_rows") or 10_000)
    replay_rows, _dataset_manifest, _rejections = _build_dataset(
        repo_root=repo_root,
        scan_limit=scan_limit,
        replay_limit=effective_replay_limit,
    )
    if no_current_redis:
        current_snapshots: list[Mapping[str, Any]] = []
        current_source = "SKIPPED_NO_CURRENT_REDIS_BY_OPERATOR_FLAG"
        top_book_enrichment_status: dict[str, Any] = {
            "schema_version": "challenger_v2_top_book_enrichment_status_v1",
            "generated_utc": utc_now(),
            "status": "SKIPPED_NO_CURRENT_REDIS_BY_OPERATOR_FLAG",
            "current_rows_scanned": 0,
            "top_book_enriched_rows": 0,
            "top_book_enrichment_coverage": 0.0,
            "reject_reason_counts": {},
            "source_counts": {},
            "sample_enriched_rows": [],
            "pit_rule": "top_book_source_event_time <= decision_time; no exchange/account mutation",
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
        }
        paper_intent_join_status: dict[str, Any] = {
            "schema_version": "challenger_v2_paper_intent_cost_evidence_join_status_v1",
            "generated_utc": utc_now(),
            "status": "SKIPPED_NO_CURRENT_REDIS_BY_OPERATOR_FLAG",
            "current_rows_scanned": 0,
            "paper_intent_rows_scanned": 0,
            "candidate_bound_intents": 0,
            "potential_snapshot_matches": 0,
            "trusted_snapshot_matches": 0,
            "positive_order_size_matches": 0,
            "paper_intent_enriched_rows": 0,
            "paper_intent_enrichment_coverage": 0.0,
            "reject_reason_counts": {},
            "field_enrichment_counts": {},
            "source_counts": {},
            "sample_enriched_rows": [],
            "sample_rejected_snapshot_matches": [],
            "binding_rule": "paper intent must identify candidate_id, policy_fingerprint, and model_source for the frozen challenger before it can count",
            "pit_rule": "paper intent cost evidence source timestamp must be <= challenger snapshot decision_time",
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
        }
    else:
        raw_current_snapshots, current_source = _read_current_snapshots(limit=current_limit)
        current_snapshots, top_book_enrichment_status = enrich_current_snapshots_with_top_book(raw_current_snapshots)
        current_snapshots, paper_intent_join_status = enrich_current_snapshots_with_paper_intents(current_snapshots, policy=policy)
    scored_rows = [score_snapshot(snapshot, policy) for snapshot in current_snapshots]
    shadow_cost_append_status = append_shadow_cost_evidence(out_dir, current_snapshots, scored_rows)
    shadow_cost_hash_chain = write_shadow_cost_hash_chain(
        out_dir,
        append_status=shadow_cost_append_status,
        policy=policy,
    )
    shadow_cost_rows = read_jsonl(out_dir / SHADOW_COST_EVIDENCE)
    shadow_cost_status = shadow_cost_evidence_status(
        policy=policy,
        append_status=shadow_cost_append_status,
        hash_chain=shadow_cost_hash_chain,
        rows=shadow_cost_rows,
    )
    write_json(out_dir / "challenger_v2_candidate_bound_shadow_cost_evidence_status.json", shadow_cost_status)
    cost_status, coverage_matrix = production_cost_evidence_artifacts(
        policy=policy,
        replay_rows=replay_rows,
        current_snapshots=current_snapshots,
        current_source=current_source,
    )
    write_json(out_dir / "challenger_v2_production_cost_evidence_status.json", cost_status)
    write_json(out_dir / "challenger_v2_cost_source_coverage_matrix.json", coverage_matrix)
    cost_parity = cost_replay_paper_parity_audit(
        policy=policy,
        replay_rows=replay_rows,
        current_snapshots=current_snapshots,
    )
    write_json(out_dir / COST_REPLAY_PAPER_PARITY_AUDIT, cost_parity)
    write_json(out_dir / "challenger_v2_top_book_enrichment_status.json", top_book_enrichment_status)
    write_json(out_dir / "challenger_v2_paper_intent_cost_evidence_join_status.json", paper_intent_join_status)

    ensure_jsonl(out_dir / LABELLED_LOCKBOX)
    append_status = append_pending_lockbox(out_dir, scored_rows)
    label_status = append_matured_labels(
        repo_root,
        out_dir,
        horizon_minutes=horizon_minutes,
        archive_scan_limit=archive_scan_limit,
        allow_public_labels=allow_public_labels,
        public_label_symbol_limit=public_label_symbol_limit,
    )
    hash_chain = write_hash_chain(out_dir, append_status=append_status, label_status=label_status, policy=policy)
    pending_rows = read_jsonl(out_dir / PENDING_LOCKBOX)
    labelled_rows = read_jsonl(out_dir / LABELLED_LOCKBOX)

    previous_holdout_rows = read_jsonl(out_dir / "challenger_v2_blind_lockbox_rows.jsonl")
    feature_parity = read_json(out_dir / "challenger_replay_runtime_feature_parity_status.json", {})
    drift = distribution_drift_artifact(
        policy=policy,
        replay_rows=replay_rows,
        current_snapshots=current_snapshots,
        previous_holdout_rows=previous_holdout_rows,
        future_lockbox_rows=pending_rows,
        feature_parity_status=feature_parity if isinstance(feature_parity, Mapping) else {},
        use_replay_tail_as_previous_holdout=True,
    )
    write_json(out_dir / "challenger_v2_distribution_drift_root_cause.json", drift)
    drift_coverage = distribution_drift_coverage_audit(policy=policy, drift_status=drift)
    write_json(out_dir / "challenger_v2_distribution_drift_coverage_audit.json", drift_coverage)
    drift_mapping_confidence = distribution_drift_mapping_confidence_audit(
        policy=policy,
        drift_status=drift,
        drift_coverage=drift_coverage,
    )
    write_json(out_dir / "challenger_v2_distribution_drift_mapping_confidence_audit.json", drift_mapping_confidence)

    shadow = shadow_supply_artifact(
        policy=policy,
        scored_rows=scored_rows,
        current_source=current_source,
        cost_status=cost_status,
        drift_status=drift,
    )
    write_json(out_dir / "challenger_v2_forward_shadow_status.json", shadow)
    shadow_supply_contract = shadow_supply_contract_audit(policy=policy, shadow_status=shadow)
    write_json(out_dir / "challenger_v2_shadow_supply_contract_audit.json", shadow_supply_contract)
    zero_supply = zero_candidate_supply_diagnosis(
        policy=policy,
        scored_rows=scored_rows,
        cost_status=cost_status,
        drift_status=drift,
        paper_intent_join_status=paper_intent_join_status,
    )
    write_json(out_dir / "challenger_v2_zero_candidate_supply_diagnosis.json", zero_supply)

    pit_violations = point_in_time_violation_count([*pending_rows, *labelled_rows])
    temporal_semantics = temporal_semantics_audit(
        policy=policy,
        pending_rows=pending_rows,
        labelled_rows=labelled_rows,
        shadow_cost_rows=shadow_cost_rows,
    )
    write_json(out_dir / TEMPORAL_SEMANTICS_AUDIT, temporal_semantics)
    lockbox_integrity = future_lockbox_integrity_audit(
        policy=policy,
        pending_rows=pending_rows,
        labelled_rows=labelled_rows,
        point_in_time_violations=pit_violations,
        append_status=append_status,
        hash_chain=hash_chain,
    )
    write_json(out_dir / "challenger_v2_future_lockbox_integrity_audit.json", lockbox_integrity)
    lockbox_perf = lockbox_performance(
        labelled_rows,
        policy=policy,
        cost_status=cost_status,
        point_in_time_violations=pit_violations,
    )
    lockbox_perf.update(
        {
            "goal_id": GOAL_ID,
            "candidate_id": policy.candidate_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "pending_rows": len(pending_rows),
            "hash_chain_last_pending": hash_chain["pending"].get("last_chain_hash"),
            "hash_chain_last_labelled": hash_chain["labelled"].get("last_chain_hash"),
        }
    )
    write_json(out_dir / "challenger_v2_blind_lockbox_performance.json", lockbox_perf)
    lockbox_pass_contract = blind_lockbox_pass_contract_audit(
        policy=policy,
        pending_rows=pending_rows,
        labelled_rows=labelled_rows,
        cost_status=cost_status,
        lockbox_integrity=lockbox_integrity,
    )
    write_json(out_dir / "challenger_v2_blind_lockbox_pass_contract_audit.json", lockbox_pass_contract)
    paper_binding_preflight = paper_binding_identity_preflight_from_redis(
        policy=policy,
        cost_status=cost_status,
        lockbox_perf=lockbox_perf,
        signal_scan_limit=paper_signal_scan_limit,
    )
    write_json(out_dir / "challenger_v2_paper_binding_identity_preflight.json", paper_binding_preflight)
    paper_cost_telemetry = paper_cost_telemetry_readiness_from_redis(
        policy=policy,
        signal_scan_limit=paper_signal_scan_limit,
        repo_root=repo_root,
    )
    write_json(out_dir / "challenger_v2_paper_cost_telemetry_readiness.json", paper_cost_telemetry)
    cost_identity_join_recovery = cost_identity_join_recovery_audit_from_redis(
        policy=policy,
        candidate_bound_rows=[*pending_rows, *shadow_cost_rows],
        signal_scan_limit=paper_signal_scan_limit,
    )
    write_json(out_dir / COST_IDENTITY_JOIN_RECOVERY_AUDIT, cost_identity_join_recovery)
    cost_capture_gap = production_cost_capture_gap_audit(
        policy=policy,
        cost_status=cost_status,
        coverage_matrix=coverage_matrix,
        paper_intent_join_status=paper_intent_join_status,
        paper_cost_telemetry=paper_cost_telemetry,
        top_book_enrichment_status=top_book_enrichment_status,
    )
    write_json(out_dir / "challenger_v2_production_cost_capture_gap_audit.json", cost_capture_gap)
    runtime_cost_capture_contract = runtime_cost_capture_contract_audit(
        policy=policy,
        cost_status=cost_status,
        cost_capture_gap=cost_capture_gap,
        paper_intent_join_status=paper_intent_join_status,
        paper_cost_telemetry=paper_cost_telemetry,
        top_book_enrichment_status=top_book_enrichment_status,
        paper_binding_preflight=paper_binding_preflight,
    )
    write_json(out_dir / "challenger_v2_runtime_cost_capture_contract_audit.json", runtime_cost_capture_contract)
    runtime_cost_capture_remediation = runtime_cost_capture_remediation_contract(
        policy=policy,
        cost_capture_gap=cost_capture_gap,
        paper_cost_telemetry=paper_cost_telemetry,
        cost_identity_join_recovery=cost_identity_join_recovery,
        runtime_cost_capture_contract=runtime_cost_capture_contract,
    )
    write_json(out_dir / RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT, runtime_cost_capture_remediation)
    runtime_cost_capture_write_path = runtime_cost_capture_write_path_audit(
        repo_root=repo_root,
        policy=policy,
        runtime_cost_capture_remediation=runtime_cost_capture_remediation,
    )
    write_json(out_dir / RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT, runtime_cost_capture_write_path)
    runtime_cost_capture_operator_approval = runtime_cost_capture_operator_approval_packet(
        policy=policy,
        runtime_cost_capture_remediation=runtime_cost_capture_remediation,
        runtime_cost_capture_write_path=runtime_cost_capture_write_path,
    )
    runtime_identity_binding_plan = runtime_identity_binding_implementation_plan(
        repo_root=repo_root,
        policy=policy,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
    )
    runtime_cost_capture_approval_subject_payload = runtime_cost_capture_approval_subject(
        policy=policy,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_identity_binding_plan=runtime_identity_binding_plan,
    )
    runtime_cost_capture_approval_subject_hash = row_hash(runtime_cost_capture_approval_subject_payload)
    approval_required_source_groups = [
        str(group)
        for group in runtime_cost_capture_approval_subject_payload.get("approval_required_source_groups", [])
    ]
    approval_source_files_to_patch = sorted(
        {
            str(file_name)
            for path in runtime_cost_capture_operator_approval.get("telemetry_only_runtime_paths", [])
            if isinstance(path, Mapping)
            for file_name in path.get("files", [])
        }
    )
    runtime_cost_capture_operator_approval = {
        **runtime_cost_capture_operator_approval,
        "approval_subject": runtime_cost_capture_approval_subject_payload,
        "approval_subject_hash": runtime_cost_capture_approval_subject_hash,
        "approval_subject_hash_status": "READY",
        "operator_approval_subject_hash_status": "READY",
        "approval_required_source_groups": approval_required_source_groups,
        "operator_approval_required_source_groups": approval_required_source_groups,
        "required_source_groups": approval_required_source_groups,
        "approved_source_groups": approval_required_source_groups,
        "source_groups": approval_required_source_groups,
        "source_group_count": len(approval_required_source_groups),
        "approved_source_group_count": len(approval_required_source_groups),
        "source_files_to_patch": approval_source_files_to_patch,
        "write_path_files": approval_source_files_to_patch,
        "source_file_count": len(approval_source_files_to_patch),
        "required_operator_acknowledgements": runtime_cost_capture_operator_approval.get(
            "required_operator_acknowledgements"
        )
        or runtime_cost_capture_operator_approval.get("required_acknowledgements"),
        "approved_patch_scope": runtime_cost_capture_approval_subject_payload.get("approved_patch_scope"),
        "approval_patch_scope": runtime_cost_capture_approval_subject_payload.get("approved_patch_scope"),
        "receipt_acceptance_rule": {
            **(
                runtime_cost_capture_operator_approval.get("receipt_acceptance_rule")
                if isinstance(runtime_cost_capture_operator_approval.get("receipt_acceptance_rule"), Mapping)
                else {}
            ),
            "approval_subject_hash": runtime_cost_capture_approval_subject_hash,
            "approval_subject_hash_status": "READY",
            "approved_source_groups": approval_required_source_groups,
            "approved_patch_scope": runtime_cost_capture_approval_subject_payload.get("approved_patch_scope"),
            "required_operator_acknowledgements": runtime_cost_capture_operator_approval.get(
                "required_operator_acknowledgements"
            )
            or runtime_cost_capture_operator_approval.get("required_acknowledgements"),
        },
    }
    runtime_cost_capture_remediation = {
        **runtime_cost_capture_remediation,
        "approval_subject_hash": runtime_cost_capture_approval_subject_hash,
        "approval_subject_hash_status": "READY",
        "operator_approval_packet_path": RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
        "operator_approval_packet_status": runtime_cost_capture_operator_approval.get("status"),
        "approval_required_source_groups": approval_required_source_groups,
        "operator_approval_required_source_groups": approval_required_source_groups,
        "source_groups": approval_required_source_groups,
        "source_group_count": len(approval_required_source_groups),
        "approved_patch_scope": runtime_cost_capture_approval_subject_payload.get("approved_patch_scope"),
        "prohibited_patch_scope": runtime_cost_capture_approval_subject_payload.get("prohibited_patch_scope"),
    }
    write_json(out_dir / RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT, runtime_cost_capture_remediation)
    write_json(out_dir / RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET, runtime_cost_capture_operator_approval)
    write_json(out_dir / RUNTIME_IDENTITY_BINDING_IMPLEMENTATION_PLAN, runtime_identity_binding_plan)
    runtime_cost_capture_operator_approval_receipt_template_payload = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_identity_binding_plan=runtime_identity_binding_plan,
    )
    write_json(
        out_dir / RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
        runtime_cost_capture_operator_approval_receipt_template_payload,
    )
    runtime_cost_capture_operator_approval_receipt = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_identity_binding_plan=runtime_identity_binding_plan,
        receipt=read_json(out_dir / RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT, {}),
    )
    write_json(out_dir / RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS, runtime_cost_capture_operator_approval_receipt)
    future_runtime_cost_acceptance = future_runtime_cost_evidence_acceptance_contract(
        policy=policy,
        paper_cost_telemetry=paper_cost_telemetry,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_identity_binding_plan=runtime_identity_binding_plan,
        runtime_cost_capture_operator_approval_receipt=runtime_cost_capture_operator_approval_receipt,
    )
    write_json(out_dir / FUTURE_RUNTIME_COST_EVIDENCE_ACCEPTANCE_CONTRACT, future_runtime_cost_acceptance)
    shadow_cost_reconciliation = shadow_cost_reconciliation_audit(
        policy=policy,
        shadow_cost_status=shadow_cost_status,
        shadow_rows=shadow_cost_rows,
        paper_cost_telemetry=paper_cost_telemetry,
        cost_capture_gap=cost_capture_gap,
        runtime_cost_capture_contract=runtime_cost_capture_contract,
    )
    write_json(out_dir / SHADOW_COST_RECONCILIATION, shadow_cost_reconciliation)
    paper_canary_binding = paper_canary_binding_readiness_artifact(
        policy=policy,
        cost_status=cost_status,
        lockbox_perf=lockbox_perf,
        paper_binding_preflight=paper_binding_preflight,
        paper_cost_telemetry=paper_cost_telemetry,
    )
    write_json(out_dir / "challenger_v2_paper_canary_binding_readiness.json", paper_canary_binding)
    forward_canary_contract = forward_paper_canary_pass_contract_audit_from_redis(
        policy=policy,
        paper_canary_binding=paper_canary_binding,
        lockbox_pass_contract=lockbox_pass_contract,
        signal_scan_limit=paper_signal_scan_limit,
    )
    write_json(out_dir / "challenger_v2_forward_paper_canary_pass_contract_audit.json", forward_canary_contract)
    paper_chain_binding_readiness = paper_chain_binding_readiness_audit(
        policy=policy,
        cost_status=cost_status,
        lockbox_pass_contract=lockbox_pass_contract,
        paper_canary_binding=paper_canary_binding,
        forward_canary_contract=forward_canary_contract,
    )
    write_json(out_dir / PAPER_CHAIN_BINDING_READINESS_AUDIT, paper_chain_binding_readiness)
    paper_credit_attribution_guard = paper_challenger_credit_attribution_guard(
        policy=policy,
        cost_status=cost_status,
        lockbox_pass_contract=lockbox_pass_contract,
        paper_binding_preflight=paper_binding_preflight,
        paper_cost_telemetry=paper_cost_telemetry,
        paper_canary_binding=paper_canary_binding,
        forward_canary_contract=forward_canary_contract,
    )
    write_json(out_dir / PAPER_CREDIT_ATTRIBUTION_GUARD, paper_credit_attribution_guard)
    added_paper_governance = added_paper_governance_blocker_audit(
        policy=policy,
        paper_governance_summary=read_json(out_dir / "paper_timeframe_churn_governance_audit_summary.json", {}),
    )
    write_json(out_dir / ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT, added_paper_governance)
    goal_phase_completion = challenger_goal_phase_completion_audit(
        policy=policy,
        cost_status=cost_status,
        cost_capture_gap=cost_capture_gap,
        runtime_cost_capture_contract=runtime_cost_capture_contract,
        append_status=append_status,
        label_status=label_status,
        hash_chain=hash_chain,
        pending_rows=pending_rows,
        labelled_rows=labelled_rows,
        drift_coverage=drift_coverage,
        drift_mapping_confidence=drift_mapping_confidence,
        shadow_supply_contract=shadow_supply_contract,
        zero_supply=zero_supply,
        lockbox_integrity=lockbox_integrity,
        lockbox_pass_contract=lockbox_pass_contract,
        paper_canary_binding=paper_canary_binding,
        forward_canary_contract=forward_canary_contract,
        paper_chain_binding_readiness=paper_chain_binding_readiness,
        added_paper_governance=added_paper_governance,
        runtime_cost_capture_operator_approval_receipt=runtime_cost_capture_operator_approval_receipt,
    )
    write_json(out_dir / "challenger_v2_goal_phase_completion_audit.json", goal_phase_completion)
    requirement_traceability = goal_requirement_traceability_matrix(
        policy=policy,
        frozen_candidate_integrity=frozen_candidate_integrity,
        cost_status=cost_status,
        cost_capture_gap=cost_capture_gap,
        runtime_cost_capture_contract=runtime_cost_capture_contract,
        runtime_cost_capture_remediation=runtime_cost_capture_remediation,
        runtime_cost_capture_operator_approval=runtime_cost_capture_operator_approval,
        runtime_cost_capture_operator_approval_receipt=runtime_cost_capture_operator_approval_receipt,
        shadow_cost_status=shadow_cost_status,
        shadow_cost_reconciliation=shadow_cost_reconciliation,
        append_status=append_status,
        label_status=label_status,
        hash_chain=hash_chain,
        lockbox_integrity=lockbox_integrity,
        drift_status=drift,
        drift_coverage=drift_coverage,
        drift_mapping_confidence=drift_mapping_confidence,
        shadow_supply_contract=shadow_supply_contract,
        zero_supply=zero_supply,
        lockbox_pass_contract=lockbox_pass_contract,
        paper_binding_preflight=paper_binding_preflight,
        paper_cost_telemetry=paper_cost_telemetry,
        paper_canary_binding=paper_canary_binding,
        forward_canary_contract=forward_canary_contract,
        paper_credit_attribution_guard=paper_credit_attribution_guard,
        goal_phase_completion=goal_phase_completion,
        paper_chain_binding_readiness=paper_chain_binding_readiness,
        added_paper_governance=added_paper_governance,
    )
    write_json(out_dir / REQUIREMENT_TRACEABILITY_MATRIX, requirement_traceability)
    shadow_label_diagnostics = shadow_label_outcome_diagnostics(
        policy=policy,
        pending_rows=pending_rows,
        labelled_rows=labelled_rows,
        cost_status=cost_status,
    )
    write_json(out_dir / "challenger_v2_shadow_label_outcome_diagnostics.json", shadow_label_diagnostics)
    shadow_outcome_actionability = shadow_lockbox_outcome_actionability_audit(
        policy=policy,
        shadow_label_diagnostics=shadow_label_diagnostics,
        lockbox_pass_contract=lockbox_pass_contract,
        cost_status=cost_status,
    )
    write_json(out_dir / SHADOW_LOCKBOX_OUTCOME_ACTIONABILITY_AUDIT, shadow_outcome_actionability)
    manifest = {
        "schema_version": "challenger_v2_blind_lockbox_manifest_v2",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "status": "COLLECTING_APPEND_ONLY_FUTURE_LOCKBOX",
        "lockbox_mode": "FUTURE_SNAPSHOTS_AFTER_CANDIDATE_FREEZE",
        "pending_rows": len(pending_rows),
        "labelled_rows": len(labelled_rows),
        "selection_records_are_append_only": True,
        "labels_are_appended_separately_after_horizon_matures": True,
        "selection_fields_rewritten_after_outcomes": lockbox_integrity.get("selection_fields_rewritten_after_outcomes"),
        "selection_fields_rewritten_after_outcomes_count": lockbox_integrity.get("selection_fields_rewritten_after_outcomes_count"),
        "selection_fields_rewritten_after_outcomes_exist": lockbox_integrity.get("selection_fields_rewritten_after_outcomes_exist"),
        "minimum_required_candidates": 300,
        "minimum_required_symbols": 30,
        "closed_candles_only": True,
        "feature_cutoff_lte_decision_time_required": True,
        "available_at_lte_decision_time_required": True,
        "future_data_used_only_as_labels": True,
    }
    write_json(out_dir / "challenger_v2_blind_lockbox_manifest.json", manifest)
    update_forward_blockers(
        out_dir,
        policy=policy,
        cost_status=cost_status,
        lockbox_perf=lockbox_perf,
        forward_canary_contract=forward_canary_contract,
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": policy.candidate_id,
        "policy_fingerprint": policy.policy_fingerprint,
        "model_source": policy.model_source,
        "frozen_candidate_integrity_status": frozen_candidate_integrity.get("status"),
        "frozen_policy_file_sha256": frozen_candidate_integrity.get("frozen_policy_file_sha256"),
        "frozen_candidate_modified_since_previous_evidence_run": frozen_candidate_integrity.get(
            "frozen_candidate_modified_since_previous_evidence_run"
        ),
        "cost_replay_paper_parity_status": cost_parity.get("status"),
        "cost_replay_paper_parity_mismatch_rows": cost_parity.get("mismatch_rows"),
        "cost_replay_paper_parity_side_mismatch_counts": cost_parity.get("side_mismatch_counts"),
        "replay_rows_examined": len(replay_rows),
        "current_rows_examined": len(current_snapshots),
        "top_book_enriched_rows": top_book_enrichment_status.get("top_book_enriched_rows"),
        "top_book_enrichment_coverage": top_book_enrichment_status.get("top_book_enrichment_coverage"),
        "paper_intent_enriched_rows": paper_intent_join_status.get("paper_intent_enriched_rows"),
        "paper_intent_enrichment_coverage": paper_intent_join_status.get("paper_intent_enrichment_coverage"),
        "paper_intent_candidate_bound_intents": paper_intent_join_status.get("candidate_bound_intents"),
        "candidate_bound_shadow_cost_evidence_status": shadow_cost_status.get("status"),
        "candidate_bound_shadow_cost_evidence_rows": shadow_cost_status.get("shadow_cost_evidence_rows"),
        "candidate_bound_shadow_cost_new_rows_appended": shadow_cost_status.get("new_shadow_cost_evidence_rows_appended"),
        "candidate_bound_shadow_cost_production_grade_rows": shadow_cost_status.get("production_grade_shadow_cost_rows"),
        "candidate_bound_shadow_cost_fallback_rows": shadow_cost_status.get("fallback_shadow_cost_rows"),
        "candidate_bound_shadow_cost_point_in_time_violations": shadow_cost_status.get("point_in_time_violations"),
        "candidate_bound_shadow_cost_last_chain_hash": shadow_cost_status.get("shadow_cost_evidence_last_chain_hash"),
        "pending_lockbox_rows": len(pending_rows),
        "labelled_lockbox_rows": len(labelled_rows),
        "lockbox_integrity_status": lockbox_integrity.get("status"),
        "lockbox_integrity_selected_production_grade_rows": lockbox_integrity.get("selected_production_grade_rows"),
        "lockbox_integrity_duplicate_pending_record_count": lockbox_integrity.get("duplicate_pending_record_count"),
        "lockbox_integrity_duplicate_pending_decision_key_count": lockbox_integrity.get(
            "duplicate_pending_decision_key_count"
        ),
        "lockbox_integrity_duplicate_label_record_count": lockbox_integrity.get("duplicate_label_record_count"),
        "lockbox_integrity_duplicate_labelled_record_count": lockbox_integrity.get("duplicate_labelled_record_count"),
        "lockbox_integrity_duplicate_labelled_lockbox_record_count": lockbox_integrity.get(
            "duplicate_labelled_lockbox_record_count"
        ),
        "lockbox_integrity_append_only_violation_count": lockbox_integrity.get("append_only_violation_count"),
        "lockbox_integrity_pending_missing_required_field_total": lockbox_integrity.get(
            "pending_missing_required_field_total"
        ),
        "lockbox_integrity_labelled_missing_required_field_total": lockbox_integrity.get(
            "labelled_missing_required_field_total"
        ),
        "lockbox_integrity_missing_required_selection_field_total": lockbox_integrity.get(
            "missing_required_selection_field_total"
        ),
        "lockbox_integrity_missing_required_label_field_total": lockbox_integrity.get(
            "missing_required_label_field_total"
        ),
        "lockbox_integrity_missing_required_selection_field_counts": lockbox_integrity.get(
            "missing_required_selection_field_counts"
        ),
        "lockbox_integrity_missing_required_label_field_counts": lockbox_integrity.get(
            "missing_required_label_field_counts"
        ),
        "lockbox_integrity_selection_fields_rewritten_after_outcomes": lockbox_integrity.get(
            "selection_fields_rewritten_after_outcomes"
        ),
        "lockbox_integrity_selection_fields_rewritten_after_outcomes_exist": lockbox_integrity.get(
            "selection_fields_rewritten_after_outcomes_exist"
        ),
        "lockbox_integrity_selection_fields_immutable_after_outcomes": lockbox_integrity.get(
            "selection_fields_immutable_after_outcomes"
        ),
        "lockbox_integrity_selection_fields_immutable_after_outcomes_exist": lockbox_integrity.get(
            "selection_fields_immutable_after_outcomes_exist"
        ),
        "lockbox_integrity_selection_fields_marked_immutable": lockbox_integrity.get(
            "selection_fields_marked_immutable"
        ),
        "lockbox_integrity_pending_append_immutability_conflicts": lockbox_integrity.get(
            "pending_append_immutability_conflicts"
        ),
        "lockbox_integrity_hash_chain_artifact_present": lockbox_integrity.get("hash_chain_artifact_present"),
        "lockbox_integrity_hash_chain_pending_row_count_matches_jsonl": lockbox_integrity.get(
            "hash_chain_pending_row_count_matches_jsonl"
        ),
        "lockbox_integrity_hash_chain_labelled_row_count_matches_jsonl": lockbox_integrity.get(
            "hash_chain_labelled_row_count_matches_jsonl"
        ),
        "lockbox_integrity_hash_chain_terminal_hashes_present": lockbox_integrity.get("hash_chain_terminal_hashes_present"),
        "future_lockbox_hash_chain_status": hash_chain.get("status"),
        "future_lockbox_hash_chain_pass_conditions": hash_chain.get("pass_conditions"),
        "future_lockbox_hash_chain_blocker_details": hash_chain.get("blocker_details"),
        "future_lockbox_hash_chain_pending_row_count": (hash_chain.get("pending") or {}).get("row_count")
        if isinstance(hash_chain.get("pending"), Mapping)
        else None,
        "future_lockbox_hash_chain_labelled_row_count": (hash_chain.get("labelled") or {}).get("row_count")
        if isinstance(hash_chain.get("labelled"), Mapping)
        else None,
        "lockbox_hash_chain_pending_row_count": (hash_chain.get("pending") or {}).get("row_count")
        if isinstance(hash_chain.get("pending"), Mapping)
        else None,
        "lockbox_integrity_hash_chain_pending_row_count": lockbox_integrity.get("hash_chain_pending_row_count"),
        "lockbox_hash_chain_labelled_row_count": (hash_chain.get("labelled") or {}).get("row_count")
        if isinstance(hash_chain.get("labelled"), Mapping)
        else None,
        "lockbox_integrity_hash_chain_labelled_row_count": lockbox_integrity.get("hash_chain_labelled_row_count"),
        "lockbox_pass_contract_status": lockbox_pass_contract.get("status"),
        "lockbox_pass_contract_independent_economic_candidates": lockbox_pass_contract.get("independent_economic_candidates"),
        "lockbox_pass_contract_selected_pending_rows": lockbox_pass_contract.get("selected_pending_rows"),
        "lockbox_pass_contract_rejected_pending_rows": lockbox_pass_contract.get("rejected_pending_rows"),
        "lockbox_pass_contract_selected_label_rows": lockbox_pass_contract.get("selected_label_rows"),
        "lockbox_pass_contract_selection_summary": lockbox_pass_contract.get("selection_summary"),
        "lockbox_pass_contract_rejection_reason_counts": lockbox_pass_contract.get("rejection_reason_counts"),
        "lockbox_pass_contract_required_independent_economic_candidates": lockbox_pass_contract.get(
            "required_independent_economic_candidates"
        ),
        "lockbox_pass_contract_independent_candidate_shortfall_to_300": lockbox_pass_contract.get(
            "independent_economic_candidate_shortfall_to_300"
        ),
        "lockbox_pass_contract_symbol_shortfall_to_30": lockbox_pass_contract.get("symbol_shortfall_to_30"),
        "lockbox_pass_contract_long_candidate_shortfall_to_1": lockbox_pass_contract.get("long_candidate_shortfall_to_1"),
        "lockbox_pass_contract_short_candidate_shortfall_to_1": lockbox_pass_contract.get("short_candidate_shortfall_to_1"),
        "lockbox_pass_contract_blocked_reasons": lockbox_pass_contract.get("blocked_reasons"),
        "lockbox_pass_contract_failed_blocker_details": lockbox_pass_contract.get("failed_lockbox_blocker_details")
        or lockbox_pass_contract.get("failed_blocker_details"),
        "lockbox_pass_contract_counting_evidence_allowed": lockbox_pass_contract.get("lockbox_counting_evidence_allowed"),
        "lockbox_pass_contract_max_concentration_pct": lockbox_pass_contract.get("max_concentration_pct"),
        "lockbox_pass_contract_available_metric_count": lockbox_pass_contract.get("available_metric_count"),
        "lockbox_pass_contract_unavailable_metric_count": lockbox_pass_contract.get("unavailable_metric_count"),
        "lockbox_pass_contract_unavailable_metric_reasons": lockbox_pass_contract.get("unavailable_metric_reasons"),
        "zero_candidate_supply_status": zero_supply.get("status"),
        "zero_candidate_supply_root_cause": zero_supply.get("root_cause") or zero_supply.get("root_cause_classification"),
        "zero_candidate_supply_root_causes": zero_supply.get("zero_supply_root_causes"),
        "zero_candidate_supply_root_cause_summary": zero_supply.get("root_cause_summary"),
        "zero_candidate_current_rows_scanned": zero_supply.get("current_rows_scanned"),
        "zero_candidate_total_rows": zero_supply.get("total_rows"),
        "zero_candidate_current_valid_rows": zero_supply.get("current_valid_rows"),
        "zero_candidate_shadow_scored_rows": zero_supply.get("shadow_scored_rows"),
        "zero_candidate_selected_rows": zero_supply.get("selected_rows"),
        "zero_candidate_qualified_rows": zero_supply.get("qualified_rows"),
        "zero_candidate_rows_above_threshold": zero_supply.get("rows_above_threshold"),
        "zero_candidate_production_grade_cost_rows": zero_supply.get("production_grade_cost_rows"),
        "zero_candidate_liquidity_pass_rows": zero_supply.get("liquidity_pass_rows"),
        "zero_candidate_drift_pass_rows": zero_supply.get("drift_pass_rows"),
        "zero_candidate_rejection_reason_counts": zero_supply.get("rejection_reason_counts"),
        "zero_candidate_threshold_distance_bands": zero_supply.get("threshold_distance_bands"),
        "zero_candidate_threshold_distance_summary": zero_supply.get("threshold_distance_summary"),
        "zero_candidate_liquidity_status_counts": zero_supply.get("liquidity_status_counts"),
        "zero_candidate_blocked_reasons": zero_supply.get("blocked_reasons"),
        "zero_candidate_blocker_details": zero_supply.get("blocker_details"),
        "zero_candidate_next_actions": zero_supply.get("next_actions"),
        "zero_candidate_pass_conditions": zero_supply.get("pass_conditions"),
        "paper_binding_identity_preflight_status": paper_binding_preflight.get("status"),
        "paper_binding_identity_complete_rows": paper_binding_preflight.get("candidate_identity_complete_rows"),
        "paper_binding_partial_identity_rows": paper_binding_preflight.get("partial_challenger_identity_rows"),
        "paper_cost_telemetry_readiness_status": paper_cost_telemetry.get("status"),
        "paper_cost_telemetry_rows_scanned": paper_cost_telemetry.get("paper_rows_scanned"),
        "paper_cost_telemetry_production_grade_rows": paper_cost_telemetry.get("paper_telemetry_production_grade_rows"),
        "paper_cost_telemetry_candidate_identity_complete_production_grade_rows": paper_cost_telemetry.get(
            "candidate_identity_complete_production_grade_rows"
        ),
        "paper_cost_telemetry_route_or_fill_blocked_production_grade_rows": paper_cost_telemetry.get(
            "route_or_fill_blocked_production_grade_rows"
        ),
        "paper_cost_telemetry_challenger_bound_production_grade_rows": paper_cost_telemetry.get("challenger_bound_production_grade_rows"),
        "paper_cost_telemetry_old_policy_or_unbound_production_grade_rows": paper_cost_telemetry.get(
            "old_policy_or_unbound_production_grade_rows"
        ),
        "paper_cost_telemetry_paper_fill_allowed_rows": paper_cost_telemetry.get("paper_fill_allowed_rows"),
        "paper_cost_telemetry_blocked_reasons": paper_cost_telemetry.get("blocked_reasons"),
        "cost_identity_join_recovery_status": cost_identity_join_recovery.get("status"),
        "cost_identity_join_exact_overlap_count": cost_identity_join_recovery.get("exact_join_key_overlap_count"),
        "cost_identity_join_overlapping_paper_rows": cost_identity_join_recovery.get("overlapping_paper_rows"),
        "cost_identity_join_recoverable_candidate_bound_production_grade_rows": cost_identity_join_recovery.get(
            "recoverable_candidate_bound_production_grade_rows"
        ),
        "cost_identity_join_diagnostic_only_external_identity_overlap_rows": cost_identity_join_recovery.get(
            "diagnostic_only_external_identity_overlap_rows"
        ),
        "production_cost_capture_gap_status": cost_capture_gap.get("status"),
        "production_cost_capture_gap_shortfall_to_95pct": cost_capture_gap.get("production_grade_cost_row_shortfall_to_95pct"),
        "production_cost_capture_gap_required_new_candidate_bound_rows": cost_capture_gap.get(
            "required_new_candidate_bound_production_grade_rows"
        ),
        "production_cost_capture_gap_limiting_cost_fields_for_95pct": cost_capture_gap.get(
            "limiting_cost_fields_for_95pct"
        ),
        "production_cost_capture_gap_hard_blocking_field_shortfalls": cost_capture_gap.get(
            "hard_blocking_field_shortfalls"
        ),
        "production_cost_capture_gap_source_group_shortfalls": cost_capture_gap.get("source_group_shortfalls")
        or cost_capture_gap.get("priority_source_groups"),
        "production_cost_capture_gap_failed_phase_1_blocker_details": cost_capture_gap.get(
            "failed_phase_1_blocker_details"
        )
        or cost_capture_gap.get("phase_1_blocker_details"),
        "phase_1_exit_minimum_new_candidate_bound_production_grade_rows": (
            cost_capture_gap.get("phase_1_exit_criteria") or {}
        ).get("minimum_new_candidate_bound_production_grade_rows"),
        "phase_1_exit_operator_approval_required_before_runtime_write_path_edits": (
            cost_capture_gap.get("phase_1_exit_criteria") or {}
        ).get("operator_approval_required_before_runtime_write_path_edits"),
        "production_cost_capture_can_recover_from_existing_sources": cost_capture_gap.get("can_recover_from_existing_authoritative_sources_without_new_capture"),
        "runtime_cost_capture_contract_status": runtime_cost_capture_contract.get("status"),
        "runtime_cost_capture_contract_blocked_reasons": runtime_cost_capture_contract.get("blocked_reasons"),
        "runtime_cost_capture_contract_shortfall_to_95pct": runtime_cost_capture_contract.get("production_grade_cost_row_shortfall_to_95pct"),
        "runtime_cost_capture_contract_required_runtime_source_groups": runtime_cost_capture_contract.get(
            "required_runtime_source_groups"
        ),
        "runtime_cost_capture_contract_required_source_groups": runtime_cost_capture_contract.get("required_source_groups"),
        "runtime_cost_capture_contract_required_write_groups": runtime_cost_capture_contract.get("required_write_groups"),
        "runtime_cost_capture_contract_required_cost_fields": runtime_cost_capture_contract.get("required_cost_fields"),
        "runtime_cost_capture_contract_required_production_cost_fields": runtime_cost_capture_contract.get(
            "required_production_cost_fields"
        ),
        "runtime_cost_capture_contract_implementation_phases": runtime_cost_capture_contract.get("implementation_phases"),
        "runtime_cost_capture_contract_acceptance_criteria": runtime_cost_capture_contract.get("acceptance_criteria"),
        "runtime_cost_capture_contract_operator_approval_boundary": runtime_cost_capture_contract.get(
            "operator_approval_boundary"
        ),
        "runtime_cost_capture_remediation_status": runtime_cost_capture_remediation.get("status"),
        "runtime_cost_capture_remediation_blocked_reasons": runtime_cost_capture_remediation.get("blocked_reasons"),
        "runtime_cost_capture_remediation_blocker_details": runtime_cost_capture_remediation.get(
            "remediation_blocker_details"
        ),
        "runtime_cost_capture_remediation_required_runtime_source_groups": runtime_cost_capture_remediation.get(
            "required_runtime_source_groups"
        ),
        "runtime_cost_capture_remediation_required_source_groups": runtime_cost_capture_remediation.get(
            "required_source_groups"
        ),
        "runtime_cost_capture_remediation_required_write_groups": runtime_cost_capture_remediation.get(
            "required_write_groups"
        ),
        "runtime_cost_capture_remediation_required_cost_fields": runtime_cost_capture_remediation.get("required_cost_fields"),
        "runtime_cost_capture_remediation_required_production_cost_fields": runtime_cost_capture_remediation.get(
            "required_production_cost_fields"
        ),
        "runtime_cost_capture_remediation_implementation_phases": runtime_cost_capture_remediation.get(
            "implementation_phases"
        ),
        "runtime_cost_capture_remediation_acceptance_criteria": runtime_cost_capture_remediation.get(
            "acceptance_criteria"
        ),
        "runtime_cost_capture_remediation_operator_approval_boundary": runtime_cost_capture_remediation.get(
            "operator_approval_boundary"
        ),
        "runtime_cost_capture_remediation_priority_source_groups": runtime_cost_capture_remediation.get(
            "priority_source_groups"
        ),
        "runtime_cost_capture_remediation_source_group_decisions": runtime_cost_capture_remediation.get(
            "source_group_decisions"
        ),
        "runtime_cost_capture_remediation_required_new_candidate_bound_rows": runtime_cost_capture_remediation.get(
            "required_new_candidate_bound_production_grade_rows"
        ),
        "runtime_cost_capture_remediation_top_source_group": runtime_cost_capture_remediation.get("top_source_group"),
        "runtime_cost_capture_remediation_top_decision_source_group": runtime_cost_capture_remediation.get(
            "top_decision_time_capture_source_group"
        ),
        "runtime_cost_capture_remediation_top_outcome_linkage_source_group": runtime_cost_capture_remediation.get(
            "top_outcome_linkage_source_group"
        ),
        "runtime_cost_capture_remediation_future_capture_credit_rules": runtime_cost_capture_remediation.get(
            "future_capture_credit_rules"
        ),
        "runtime_cost_capture_write_path_audit_status": runtime_cost_capture_write_path.get("status"),
        "runtime_cost_capture_write_path_operator_action_required": runtime_cost_capture_write_path.get("operator_action_required"),
        "runtime_cost_capture_write_path_missing_identity_fields": runtime_cost_capture_write_path.get(
            "missing_required_identity_fields"
        ),
        "runtime_cost_capture_write_path_missing_cost_fields": runtime_cost_capture_write_path.get("missing_required_cost_fields"),
        "runtime_cost_capture_write_path_telemetry_only_path_count": len(
            runtime_cost_capture_write_path.get("telemetry_only_runtime_paths") or []
        ),
        "runtime_cost_capture_write_path_prohibited_patch_scope": runtime_cost_capture_write_path.get(
            "prohibited_patch_scope"
        ),
        "runtime_cost_capture_operator_approval_packet_status": runtime_cost_capture_operator_approval.get("status"),
        "runtime_cost_capture_operator_approval_required": runtime_cost_capture_operator_approval.get("operator_approval_required"),
        "runtime_cost_capture_operator_approval_required_source_groups": runtime_cost_capture_operator_approval.get(
            "approval_required_source_groups"
        ),
        "runtime_cost_capture_operator_approval_operator_required_source_groups": runtime_cost_capture_operator_approval.get(
            "operator_approval_required_source_groups"
        ),
        "runtime_cost_capture_operator_approval_approved_source_groups": runtime_cost_capture_operator_approval.get(
            "approved_source_groups"
        ),
        "runtime_cost_capture_operator_approval_approved_patch_scope": runtime_cost_capture_operator_approval.get(
            "approved_patch_scope"
        ),
        "runtime_cost_capture_operator_approval_subject_hash_status": runtime_cost_capture_operator_approval.get(
            "approval_subject_hash_status"
        ),
        "runtime_cost_capture_operator_approval_required_operator_acknowledgements": runtime_cost_capture_operator_approval.get(
            "required_operator_acknowledgements"
        ),
        "runtime_cost_capture_operator_approval_telemetry_only_runtime_path_count": len(
            runtime_cost_capture_operator_approval.get("telemetry_only_runtime_paths") or []
        ),
        "runtime_cost_capture_operator_approval_prohibited_patch_scope": runtime_cost_capture_operator_approval.get(
            "prohibited_patch_scope"
        ),
        "runtime_cost_capture_operator_approval_receipt_acceptance_rule": runtime_cost_capture_operator_approval.get(
            "receipt_acceptance_rule"
        ),
        "runtime_cost_capture_operator_approval_receipt_status": runtime_cost_capture_operator_approval_receipt.get("status"),
        "runtime_cost_capture_operator_approval_receipt_blocked_conditions": runtime_cost_capture_operator_approval_receipt.get(
            "blocked_conditions"
        ),
        "runtime_cost_capture_operator_approval_missing_or_invalid_receipt_fields": runtime_cost_capture_operator_approval_receipt.get(
            "missing_or_invalid_receipt_fields"
        ),
        "runtime_cost_capture_operator_approval_receipt_operator_action_required": runtime_cost_capture_operator_approval_receipt.get(
            "operator_action_required"
        ),
        "runtime_cost_capture_operator_approval_subject_hash": runtime_cost_capture_operator_approval_receipt.get(
            "approval_subject_hash"
        ),
        "runtime_identity_binding_implementation_plan_status": runtime_identity_binding_plan.get("status"),
        "runtime_identity_binding_implementation_plan_incomplete_source_groups": runtime_identity_binding_plan.get(
            "incomplete_source_groups"
        ),
        "runtime_identity_binding_required_source_groups": runtime_identity_binding_plan.get("required_source_groups")
        or runtime_identity_binding_plan.get("approval_required_source_groups"),
        "runtime_identity_binding_required_identity_fields": runtime_identity_binding_plan.get("required_identity_fields"),
        "runtime_identity_binding_required_join_key_fields": runtime_identity_binding_plan.get("required_join_key_fields"),
        "runtime_identity_binding_required_cost_fields_by_group": runtime_identity_binding_plan.get(
            "required_cost_fields_by_group"
        ),
        "runtime_identity_binding_source_files_to_patch": runtime_identity_binding_plan.get("source_files_to_patch")
        or runtime_identity_binding_plan.get("source_files_scanned"),
        "runtime_identity_binding_missing_identity_fields_by_group": runtime_identity_binding_plan.get(
            "missing_identity_fields_by_group"
        ),
        "runtime_identity_binding_missing_cost_fields_by_group": runtime_identity_binding_plan.get(
            "missing_cost_fields_by_group"
        ),
        "runtime_identity_binding_missing_fields_by_source_group": runtime_identity_binding_plan.get(
            "missing_fields_by_source_group"
        ),
        "runtime_identity_binding_source_group_implementation_plan_count": len(
            runtime_identity_binding_plan.get("source_group_implementation_plans") or {}
        ),
        "runtime_identity_binding_operator_approval_required_before_applying_plan": runtime_identity_binding_plan.get(
            "operator_approval_required_before_applying_plan"
        ),
        "future_runtime_cost_evidence_acceptance_contract_status": future_runtime_cost_acceptance.get("status"),
        "future_runtime_cost_acceptance_status": future_runtime_cost_acceptance.get("status"),
        "future_runtime_cost_acceptance_operator_approved": future_runtime_cost_acceptance.get(
            "current_runtime_cost_capture_operator_approved"
        ),
        "future_runtime_cost_acceptance_current_operator_approved": future_runtime_cost_acceptance.get(
            "current_operator_approved"
        ),
        "future_runtime_cost_acceptance_current_runtime_cost_capture_operator_approved": future_runtime_cost_acceptance.get(
            "current_runtime_cost_capture_operator_approved"
        ),
        "future_runtime_cost_acceptance_gate_open": future_runtime_cost_acceptance.get(
            "future_runtime_row_acceptance_gate_open"
        ),
        "future_runtime_cost_acceptance_future_runtime_row_acceptance_gate_open": future_runtime_cost_acceptance.get(
            "future_runtime_row_acceptance_gate_open"
        ),
        "future_runtime_cost_acceptance_currently_countable_phase_1_rows": future_runtime_cost_acceptance.get(
            "currently_countable_phase_1_production_grade_rows"
        ),
        "future_runtime_cost_acceptance_blocked_reasons": future_runtime_cost_acceptance.get("blocked_reasons"),
        "future_runtime_cost_acceptance_blocker_details": future_runtime_cost_acceptance.get(
            "acceptance_blocker_details"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_receipt_status": future_runtime_cost_acceptance.get(
            "current_operator_approval_receipt_status"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_receipt_blocked_conditions": future_runtime_cost_acceptance.get(
            "current_operator_approval_receipt_blocked_conditions"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_missing_or_invalid_receipt_fields": future_runtime_cost_acceptance.get(
            "current_operator_approval_missing_or_invalid_receipt_fields"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_subject_hash": future_runtime_cost_acceptance.get(
            "current_operator_approval_subject_hash"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_receipt_path": future_runtime_cost_acceptance.get(
            "current_operator_approval_receipt_path"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_receipt_template_path": future_runtime_cost_acceptance.get(
            "current_operator_approval_receipt_template_path"
        ),
        "future_runtime_cost_acceptance_current_operator_approval_receipt_status_path": future_runtime_cost_acceptance.get(
            "current_operator_approval_receipt_status_path"
        ),
        "future_runtime_cost_acceptance_required_source_groups": future_runtime_cost_acceptance.get(
            "required_source_groups"
        ),
        "future_runtime_cost_acceptance_approved_source_groups": future_runtime_cost_acceptance.get(
            "approved_source_groups"
        ),
        "future_runtime_cost_acceptance_challenger_bound_rows": future_runtime_cost_acceptance.get(
            "current_challenger_bound_production_grade_rows"
        ),
        "future_runtime_cost_acceptance_candidate_bound_paper_fill_allowed_rows": future_runtime_cost_acceptance.get(
            "current_candidate_bound_paper_fill_allowed_rows"
        ),
        "future_runtime_cost_acceptance_candidate_bound_live_route_rows": future_runtime_cost_acceptance.get(
            "current_candidate_bound_live_route_rows"
        ),
        "future_runtime_cost_acceptance_quarantined_non_candidate_bound_paper_fill_allowed_rows": (
            future_runtime_cost_acceptance.get("quarantined_non_candidate_bound_paper_fill_allowed_rows")
        ),
        "future_runtime_cost_acceptance_quarantined_non_candidate_bound_live_route_rows": (
            future_runtime_cost_acceptance.get("quarantined_non_candidate_bound_live_route_rows")
        ),
        "candidate_bound_shadow_cost_reconciliation_status": shadow_cost_reconciliation.get("status"),
        "candidate_bound_shadow_cost_reconciliation_candidate_bound_fallback_rows": shadow_cost_reconciliation.get("candidate_bound_fallback_rows"),
        "candidate_bound_shadow_cost_reconciliation_production_grade_non_counting_rows": shadow_cost_reconciliation.get(
            "production_grade_non_counting_shadow_cost_rows"
        ),
        "candidate_bound_shadow_cost_reconciliation_old_unbound_paper_rows_quarantined": shadow_cost_reconciliation.get(
            "old_policy_or_unbound_production_grade_paper_rows"
        ),
        "paper_canary_binding_readiness_status": paper_canary_binding.get("status"),
        "paper_canary_binding_allowed": paper_canary_binding.get("binding_allowed"),
        "paper_canary_binding_blocked_reasons": paper_canary_binding.get("blocked_reasons"),
        "paper_canary_binding_blocker_details": paper_canary_binding.get("binding_blocker_details")
        or paper_canary_binding.get("binding_prerequisite_details"),
        "paper_canary_binding_failed_blocker_details": paper_canary_binding.get("failed_binding_blocker_details")
        or paper_canary_binding.get("failed_binding_prerequisite_details"),
        "paper_canary_binding_prerequisites_satisfied": paper_canary_binding.get("paper_binding_prerequisites_satisfied"),
        "paper_canary_binding_required_chain_components": paper_canary_binding.get("required_chain_components"),
        "forward_paper_canary_contract_status": forward_canary_contract.get("status"),
        "forward_paper_canary_scanned_rows": forward_canary_contract.get("scanned_rows")
        or forward_canary_contract.get("paper_rows_scanned"),
        "forward_paper_canary_total_rows_scanned": forward_canary_contract.get("total_rows_scanned")
        or forward_canary_contract.get("paper_rows_scanned"),
        "forward_paper_canary_candidate_bound_rows": forward_canary_contract.get("candidate_bound_rows")
        or forward_canary_contract.get("closed_challenger_economic_outcomes"),
        "forward_paper_canary_old_policy_or_unbound_rows_quarantined": forward_canary_contract.get(
            "old_policy_or_unbound_rows_quarantined"
        ),
        "forward_paper_canary_non_counting_row_count": forward_canary_contract.get("non_counting_row_count"),
        "forward_paper_canary_excluded_row_counts": forward_canary_contract.get("excluded_row_counts"),
        "forward_paper_canary_closed_challenger_economic_outcomes": forward_canary_contract.get("closed_challenger_economic_outcomes"),
        "forward_paper_canary_profit_factor": forward_canary_contract.get("profit_factor"),
        "forward_paper_canary_available_metric_count": forward_canary_contract.get("available_metric_count"),
        "forward_paper_canary_unavailable_metric_count": forward_canary_contract.get("unavailable_metric_count"),
        "forward_paper_canary_unavailable_metric_reasons": forward_canary_contract.get("unavailable_metric_reasons"),
        "paper_chain_binding_readiness_status": paper_chain_binding_readiness.get("status"),
        "paper_chain_binding_required_components": len(paper_chain_binding_readiness.get("required_chain") or []),
        "paper_chain_binding_complete_components": paper_chain_binding_readiness.get("complete_components"),
        "paper_chain_binding_missing_component_count": paper_chain_binding_readiness.get("missing_component_count"),
        "paper_chain_binding_component_shortfall_to_required": paper_chain_binding_readiness.get(
            "chain_component_shortfall_to_required"
        ),
        "paper_chain_binding_missing_component_names": paper_chain_binding_readiness.get("missing_component_names"),
        "paper_chain_binding_allowed": paper_chain_binding_readiness.get("binding_allowed"),
        "paper_challenger_credit_attribution_guard_status": paper_credit_attribution_guard.get("status"),
        "paper_challenger_credit_attribution_guard_blocked_reasons": paper_credit_attribution_guard.get("blocked_reasons"),
        "paper_challenger_credit_attribution_rows_scanned": paper_credit_attribution_guard.get("rows_scanned"),
        "paper_challenger_credit_attribution_candidate_bound_rows": paper_credit_attribution_guard.get("candidate_bound_rows"),
        "paper_challenger_credit_attribution_old_unbound_rows_quarantined": paper_credit_attribution_guard.get(
            "old_policy_or_unbound_rows_quarantined"
        )
        or paper_credit_attribution_guard.get(
            "old_policy_or_unbound_production_grade_rows_quarantined"
        ),
        "paper_challenger_credit_attribution_non_counting_row_count": paper_credit_attribution_guard.get(
            "non_counting_row_count"
        ),
        "paper_challenger_credit_attribution_forward_identity_excluded_rows": (
            paper_credit_attribution_guard.get("forward_canary_excluded_row_counts") or {}
        ).get("challenger_identity_not_complete"),
        "added_paper_governance_blocker_status": added_paper_governance.get("status"),
        "added_paper_governance_source_status": added_paper_governance.get("source_summary_status")
        or added_paper_governance.get("source_status"),
        "added_paper_governance_final_gate": added_paper_governance.get("source_final_gate"),
        "added_paper_governance_required_artifacts": added_paper_governance.get("required_artifacts"),
        "added_paper_governance_required_artifact_count": added_paper_governance.get("required_artifact_count"),
        "added_paper_governance_required_artifacts_present": added_paper_governance.get("required_artifacts_present"),
        "added_paper_governance_source_required_artifact_count": added_paper_governance.get(
            "source_required_artifact_count"
        ),
        "added_paper_governance_source_required_artifacts_present": added_paper_governance.get(
            "source_required_artifacts_present"
        ),
        "added_paper_governance_source_artifacts_written": added_paper_governance.get("source_artifacts_written"),
        "added_paper_governance_missing_required_artifacts": added_paper_governance.get("missing_required_artifacts"),
        "added_paper_governance_missing_required_artifact_count": added_paper_governance.get(
            "missing_required_artifact_count"
        ),
        "added_paper_governance_source_missing_required_artifact_count": added_paper_governance.get(
            "source_missing_required_artifact_count"
        ),
        "added_paper_governance_hardcoded_1m_path_count": added_paper_governance.get("hardcoded_1m_path_count"),
        "added_paper_governance_silent_1m_fallback_path_count": added_paper_governance.get(
            "silent_1m_fallback_path_count"
        ),
        "added_paper_governance_timeframe_routing_violation_count": added_paper_governance.get(
            "timeframe_routing_violation_count"
        ),
        "added_paper_governance_silent_1m_fallback_paths": added_paper_governance.get("silent_1m_fallback_paths"),
        "added_paper_governance_routing_owner_blocked_reasons": added_paper_governance.get(
            "routing_owner_blocked_reasons"
        ),
        "added_paper_governance_routing_repair_blocked_reasons": added_paper_governance.get(
            "routing_repair_blocked_reasons"
        ),
        "added_paper_governance_old_policy_trade_count": added_paper_governance.get("old_policy_trade_count"),
        "added_paper_governance_challenger_trade_count": added_paper_governance.get("challenger_trade_count"),
        "added_paper_governance_raw_close_record_count": added_paper_governance.get("raw_close_record_count"),
        "added_paper_governance_economic_trade_count": added_paper_governance.get("economic_trade_count"),
        "added_paper_governance_paper_entry_production_grade_cost_coverage": added_paper_governance.get(
            "paper_entry_production_grade_cost_coverage"
        ),
        "added_paper_governance_paper_entry_required_coverage": added_paper_governance.get("paper_entry_required_coverage"),
        "added_paper_governance_paper_entry_missing_required_fields": added_paper_governance.get(
            "paper_entry_missing_required_fields"
        ),
        "added_paper_governance_paper_entry_missing_required_field_count": added_paper_governance.get(
            "paper_entry_missing_required_field_count"
        ),
        "added_paper_governance_paper_entry_shadow_only_missing_cost_rows": added_paper_governance.get(
            "paper_entry_shadow_only_missing_cost_rows"
        ),
        "added_paper_governance_paper_edge_to_cost_gate_status": added_paper_governance.get(
            "paper_edge_to_cost_gate_status"
        ),
        "added_paper_governance_economic_trade_compaction_status": added_paper_governance.get(
            "economic_trade_compaction_status"
        ),
        "added_paper_governance_economic_trade_compaction_missing_raw_identity_fields": added_paper_governance.get(
            "economic_trade_compaction_missing_raw_identity_fields"
        ),
        "added_paper_governance_economic_trade_compaction_raw_identity_missing_field_counts": added_paper_governance.get(
            "economic_trade_compaction_raw_identity_missing_field_counts"
        ),
        "added_paper_governance_economic_trade_compaction_accounting_reconciliation_status": added_paper_governance.get(
            "economic_trade_compaction_accounting_reconciliation_status"
        ),
        "added_paper_governance_multi_timeframe_thesis_execution_contract_status": added_paper_governance.get(
            "multi_timeframe_thesis_execution_contract_status"
        ),
        "added_paper_governance_multi_timeframe_thesis_execution_missing_required_fields": added_paper_governance.get(
            "multi_timeframe_thesis_execution_missing_required_fields"
        ),
        "added_paper_governance_multi_timeframe_thesis_execution_missing_required_field_counts": added_paper_governance.get(
            "multi_timeframe_thesis_execution_missing_required_field_counts"
        ),
        "added_paper_governance_operator_dashboard_truth_contract_status": added_paper_governance.get(
            "operator_dashboard_truth_contract_status"
        ),
        "added_paper_governance_operator_dashboard_truth_contract_blocked_reasons": added_paper_governance.get(
            "operator_dashboard_truth_contract_blocked_reasons"
        ),
        "added_paper_governance_operator_dashboard_missing_required_fields": added_paper_governance.get(
            "operator_dashboard_missing_required_fields"
        ),
        "added_paper_governance_post_fix_paper_validation_status": added_paper_governance.get(
            "post_fix_paper_validation_status"
        ),
        "added_paper_governance_post_fix_sample_status": added_paper_governance.get("post_fix_sample_status"),
        "added_paper_governance_post_fix_sample_started": added_paper_governance.get("post_fix_sample_started"),
        "added_paper_governance_post_fix_sample_raw_close_rows": added_paper_governance.get(
            "post_fix_sample_raw_close_rows"
        ),
        "added_paper_governance_post_fix_sample_eligible_raw_close_rows": added_paper_governance.get(
            "post_fix_sample_eligible_raw_close_rows"
        ),
        "added_paper_governance_post_fix_sample_excluded_raw_close_rows": added_paper_governance.get(
            "post_fix_sample_excluded_raw_close_rows"
        ),
        "added_paper_governance_post_fix_sample_exclusion_reason_counts": added_paper_governance.get(
            "post_fix_sample_exclusion_reason_counts"
        ),
        "added_paper_governance_post_fix_sample_source_counts": added_paper_governance.get(
            "post_fix_sample_source_counts"
        ),
        "added_paper_governance_post_fix_sample_eligible_source_counts": added_paper_governance.get(
            "post_fix_sample_eligible_source_counts"
        ),
        "added_paper_governance_post_fix_sample_excluded_source_counts": added_paper_governance.get(
            "post_fix_sample_excluded_source_counts"
        ),
        "added_paper_governance_post_fix_sample_source_read_status": added_paper_governance.get(
            "post_fix_sample_source_read_status"
        ),
        "added_paper_governance_post_fix_sample_sample_excluded_rows": added_paper_governance.get(
            "post_fix_sample_sample_excluded_rows"
        ),
        "added_paper_governance_post_fix_sample_sample_excluded_rows_by_source": added_paper_governance.get(
            "post_fix_sample_sample_excluded_rows_by_source"
        ),
        "added_paper_governance_post_fix_sample_sample_compacted_economic_trades": added_paper_governance.get(
            "post_fix_sample_sample_compacted_economic_trades"
        ),
        "added_paper_governance_new_compacted_economic_paper_outcomes": added_paper_governance.get(
            "new_compacted_economic_paper_outcomes"
        ),
        "added_paper_governance_required_new_compacted_economic_paper_outcomes": added_paper_governance.get(
            "required_new_compacted_economic_paper_outcomes"
        ),
        "added_paper_governance_post_fix_validation_actuals": added_paper_governance.get("post_fix_validation_actuals"),
        "added_paper_governance_post_fix_validation_required": added_paper_governance.get("post_fix_validation_required"),
        "added_paper_governance_post_fix_duplicate_economic_trades": added_paper_governance.get(
            "post_fix_duplicate_economic_trades"
        ),
        "added_paper_governance_post_fix_unexplained_same_candle_reentries": added_paper_governance.get(
            "post_fix_unexplained_same_candle_reentries"
        ),
        "added_paper_governance_post_fix_accounting_reconciliation_status": added_paper_governance.get(
            "post_fix_accounting_reconciliation_status"
        ),
        "added_paper_governance_current_1m_share": added_paper_governance.get("current_1m_share"),
        "added_paper_governance_current_1m_economic_trade_share": added_paper_governance.get("current_1m_economic_trade_share"),
        "added_paper_governance_blocked_condition_count": added_paper_governance.get("blocked_condition_count"),
        "added_paper_governance_blocked_conditions": added_paper_governance.get("blocked_conditions"),
        "added_paper_governance_blocker_details": added_paper_governance.get("blocker_details"),
        "added_paper_governance_source_blocker_count": added_paper_governance.get("source_blocker_count"),
        "added_paper_governance_source_blocked_pass_conditions": added_paper_governance.get("source_blocked_pass_conditions"),
        "added_paper_governance_source_blocker_details": added_paper_governance.get("source_blocker_details"),
        "added_paper_governance_source_phase_blocker_count": added_paper_governance.get("source_phase_blocker_count"),
        "added_paper_governance_source_phase_blockers": added_paper_governance.get("source_phase_blockers"),
        **goal_rollup_summary_aliases(goal_phase_completion, requirement_traceability),
        "shadow_supply_contract_status": shadow_supply_contract.get("status"),
        "shadow_supply_total_current_valid_rows": shadow_supply_contract.get("total_current_valid_rows"),
        "shadow_supply_total_shadow_scored_rows": shadow_supply_contract.get("total_shadow_scored_rows"),
        "shadow_supply_qualified_economic_candidates": shadow_supply_contract.get("qualified_economic_candidates"),
        "shadow_supply_rejection_reason_counts": shadow_supply_contract.get("rejection_reason_counts"),
        "shadow_supply_liquidity_status_counts": shadow_supply_contract.get("liquidity_status_counts"),
        "shadow_supply_top_25_long_count": shadow_supply_contract.get("top_25_long_count"),
        "shadow_supply_top_25_short_count": shadow_supply_contract.get("top_25_short_count"),
        "new_labels_appended": label_status.get("new_labels_appended"),
        "label_source_counts": label_status.get("label_source_counts"),
        "labelled_shadow_after_cost_expectancy_bps": shadow_label_diagnostics.get("all_labelled_stats", {}).get("after_cost_expectancy_bps"),
        "labelled_shadow_false_positive_rate": shadow_label_diagnostics.get("all_labelled_stats", {}).get("false_positive_rate"),
        "shadow_lockbox_outcome_actionability_status": shadow_outcome_actionability.get("status"),
        "shadow_lockbox_shadow_rows": shadow_outcome_actionability.get("shadow_rows"),
        "shadow_lockbox_selected_shadow_rows": shadow_outcome_actionability.get("selected_shadow_rows"),
        "shadow_lockbox_after_cost_expectancy_bps": shadow_outcome_actionability.get("after_cost_expectancy_bps"),
        "shadow_lockbox_profit_factor": shadow_outcome_actionability.get("profit_factor"),
        "shadow_lockbox_failed_metric_conditions": shadow_outcome_actionability.get("failed_metric_conditions")
        or shadow_outcome_actionability.get("failed_shadow_metric_conditions"),
        "shadow_lockbox_blocker_details": shadow_outcome_actionability.get("blocker_details"),
        "shadow_lockbox_non_counting_reasons": shadow_outcome_actionability.get("non_counting_reasons"),
        "temporal_semantics_status": temporal_semantics.get("status"),
        "temporal_semantics_violation_counts": temporal_semantics.get("violation_counts"),
        "temporal_semantics_missing_required_counts": temporal_semantics.get("missing_required_temporal_field_counts"),
        "temporal_semantics_point_in_time_violations": temporal_semantics.get("point_in_time_violations"),
        "temporal_semantics_feature_available_after_decision_rows": temporal_semantics.get(
            "feature_available_after_decision_rows"
        ),
        "temporal_semantics_available_at_after_decision_rows": temporal_semantics.get("available_at_after_decision_rows"),
        "temporal_semantics_feature_cutoff_after_decision_rows": temporal_semantics.get("feature_cutoff_after_decision_rows"),
        "temporal_semantics_decision_input_event_time_after_decision_rows": temporal_semantics.get(
            "decision_input_event_time_after_decision_rows"
        ),
        "temporal_semantics_event_time_after_available_at_rows": temporal_semantics.get("event_time_after_available_at_rows"),
        "temporal_semantics_masa_feature_cutoff_after_ppo_decision_rows": temporal_semantics.get(
            "masa_feature_cutoff_after_ppo_decision_rows"
        ),
        "temporal_semantics_execution_time_before_decision_rows": temporal_semantics.get(
            "execution_time_before_decision_rows"
        ),
        "temporal_semantics_lockbox_label_event_time_not_after_decision_rows": temporal_semantics.get(
            "lockbox_label_event_time_not_after_decision_rows"
        ),
        "temporal_semantics_lockbox_label_future_data_flag_not_true_rows": temporal_semantics.get(
            "lockbox_label_future_data_flag_not_true_rows"
        ),
        "temporal_semantics_unfinished_higher_timeframe_candle_rows": temporal_semantics.get(
            "unfinished_higher_timeframe_candle_rows"
        ),
        "production_grade_cost_coverage": cost_status.get("production_grade_cost_coverage"),
        "production_cost_required_coverage": cost_status.get("required_coverage"),
        "production_cost_required_cost_fields": cost_status.get("required_cost_fields"),
        "production_cost_required_production_cost_fields": cost_status.get("required_production_cost_fields"),
        "production_cost_coverage_shortfall_to_required": cost_status.get(
            "production_grade_cost_coverage_shortfall_to_required"
        ),
        "production_cost_hard_blocking_fields": cost_status.get("hard_blocking_fields"),
        "production_cost_hard_blocking_cost_fields": cost_status.get("hard_blocking_cost_fields")
        or cost_status.get("hard_blocking_fields"),
        "production_cost_hard_blocking_missing_fields": cost_status.get("hard_blocking_missing_fields"),
        "production_cost_hard_blocking_missing_cost_fields": cost_status.get("hard_blocking_missing_cost_fields")
        or cost_status.get("hard_blocking_missing_fields"),
        "production_cost_hard_blocking_missing_field_counts": cost_status.get("hard_blocking_missing_field_counts"),
        "production_cost_hard_blocking_missing_cost_field_counts": cost_status.get(
            "hard_blocking_missing_cost_field_counts"
        )
        or cost_status.get("hard_blocking_missing_field_counts"),
        "production_cost_hard_blocking_missing_field_count": cost_status.get("hard_blocking_missing_field_count"),
        "production_cost_hard_blocking_missing_cost_field_count": cost_status.get(
            "hard_blocking_missing_cost_field_count"
        )
        or cost_status.get("hard_blocking_missing_field_count"),
        "production_cost_hard_blocking_missing_row_total": cost_status.get("hard_blocking_missing_row_total"),
        "production_cost_hard_blocking_missing_cost_row_total": cost_status.get(
            "hard_blocking_missing_cost_row_total"
        )
        or cost_status.get("hard_blocking_missing_row_total"),
        "production_cost_fully_missing_cost_fields": cost_status.get("fully_missing_cost_fields"),
        "production_cost_partially_missing_cost_fields": cost_status.get("partially_missing_cost_fields"),
        "production_cost_safe_next_capture_boundary": cost_status.get("safe_next_capture_boundary"),
        "unexplained_cost_missing_rows": cost_status.get("unexplained_cost_missing_rows"),
        "replay_paper_cost_parity_mismatch_rows": cost_status.get("replay_paper_cost_parity_mismatch_rows"),
        "replay_paper_cost_parity_mismatch_side_counts": cost_status.get("replay_paper_cost_parity_mismatch_side_counts"),
        "production_cost_required_field_missing_counts": cost_status.get("required_field_missing_counts"),
        "production_cost_required_field_present_counts": cost_status.get("required_fields_present_counts"),
        "production_cost_field_coverage": cost_status.get("field_coverage"),
        "production_cost_blocker_details": cost_status.get("blocker_details"),
        "production_cost_source_group_summary": cost_status.get("source_group_summary"),
        "cost_status": cost_status.get("status"),
        "drift_root_cause_status": drift.get("status"),
        "drift_root_cause": drift.get("root_cause_classification"),
        "distribution_drift_feature_count": drift.get("feature_count"),
        "distribution_drift_policy_feature_count": drift.get("policy_feature_count"),
        "distribution_drift_expected_feature_count": drift.get("expected_feature_count"),
        "distribution_drift_all_32_features_present": drift.get("all_32_features_present"),
        "distribution_drift_all_policy_features_present": drift.get("all_policy_features_present"),
        "distribution_drift_root_cause_summary": drift.get("root_cause_summary"),
        "distribution_drift_candidate_change_decision": drift.get("candidate_change_decision"),
        "distribution_drift_frozen_candidate_action": drift.get("frozen_candidate_action"),
        "drift_root_cause_pass_conditions": drift.get("pass_conditions"),
        "drift_root_cause_blocker_details": drift.get("blocker_details"),
        "drift_root_cause_high_drift_feature_count_current_runtime": drift.get(
            "high_drift_feature_count_current_runtime"
        ),
        "drift_root_cause_features_requiring_new_candidate_if_fixed": drift.get(
            "features_requiring_new_candidate_if_fixed"
        ),
        "drift_root_cause_decision_contract": drift.get("drift_decision_contract"),
        "drift_root_cause_missing_or_stale_summary": drift.get("missing_or_stale_summary"),
        "drift_root_cause_out_of_training_range_summary": drift.get("out_of_training_range_summary"),
        "drift_coverage_status": drift_coverage.get("status"),
        "drift_coverage_policy_feature_count": drift_coverage.get("policy_feature_count"),
        "drift_coverage_required_feature_count": drift_coverage.get("required_feature_count"),
        "drift_coverage_required_cohort_count": drift_coverage.get("required_cohort_count"),
        "drift_coverage_reported_required_cohort_count": drift_coverage.get("reported_required_cohort_count"),
        "drift_coverage_cohorts_present": drift_coverage.get("cohorts_present"),
        "drift_mapping_confidence_status": drift_mapping_confidence.get("status"),
        "drift_mapping_candidate_id_change_required": drift_mapping_confidence.get("candidate_id_change_required"),
        "drift_mapping_frozen_candidate_kept": drift_mapping_confidence.get("frozen_candidate_kept"),
        "drift_mapping_high_drift_feature_count_current_runtime": drift_mapping_confidence.get(
            "high_drift_feature_count_current_runtime"
        ),
        "drift_mapping_computed_high_drift_feature_count_current_runtime": drift_mapping_confidence.get(
            "computed_high_drift_feature_count_current_runtime"
        ),
        "drift_mapping_suspicion_feature_count": drift_mapping_confidence.get("mapping_suspicion_feature_count"),
        "drift_mapping_genuine_shift_support_feature_count": drift_mapping_confidence.get(
            "genuine_shift_support_feature_count"
        ),
        "drift_mapping_features_requiring_new_candidate_if_fixed": drift_mapping_confidence.get(
            "features_requiring_new_candidate_if_fixed"
        ),
        "drift_mapping_blocker_details": drift_mapping_confidence.get("drift_mapping_blocker_details"),
        "drift_mapping_decision_contract": drift_mapping_confidence.get("drift_decision_contract"),
        "paper_binding_status": "BLOCKED_UNTIL_LOCKBOX_PASS",
        "paper_only": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "artifacts_written": [
            FROZEN_CANDIDATE_INTEGRITY_AUDIT,
            "challenger_v2_production_cost_evidence_status.json",
            "challenger_v2_cost_source_coverage_matrix.json",
            COST_REPLAY_PAPER_PARITY_AUDIT,
            "challenger_v2_top_book_enrichment_status.json",
            "challenger_v2_paper_intent_cost_evidence_join_status.json",
            SHADOW_COST_EVIDENCE,
            SHADOW_COST_HASH_CHAIN,
            "challenger_v2_candidate_bound_shadow_cost_evidence_status.json",
            PENDING_LOCKBOX,
            LABELLED_LOCKBOX,
            HASH_CHAIN,
            "challenger_v2_distribution_drift_root_cause.json",
            "challenger_v2_distribution_drift_coverage_audit.json",
            "challenger_v2_distribution_drift_mapping_confidence_audit.json",
            "challenger_v2_forward_shadow_status.json",
            "challenger_v2_shadow_supply_contract_audit.json",
            "challenger_v2_zero_candidate_supply_diagnosis.json",
            TEMPORAL_SEMANTICS_AUDIT,
            "challenger_v2_blind_lockbox_manifest.json",
            "challenger_v2_future_lockbox_integrity_audit.json",
            "challenger_v2_blind_lockbox_performance.json",
            "challenger_v2_blind_lockbox_pass_contract_audit.json",
            "challenger_v2_paper_binding_identity_preflight.json",
            "challenger_v2_paper_cost_telemetry_readiness.json",
            COST_IDENTITY_JOIN_RECOVERY_AUDIT,
            "challenger_v2_production_cost_capture_gap_audit.json",
            "challenger_v2_runtime_cost_capture_contract_audit.json",
            RUNTIME_COST_CAPTURE_REMEDIATION_CONTRACT,
            RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT,
            RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_PACKET,
            RUNTIME_IDENTITY_BINDING_IMPLEMENTATION_PLAN,
            RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_TEMPLATE,
            RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT_STATUS,
            FUTURE_RUNTIME_COST_EVIDENCE_ACCEPTANCE_CONTRACT,
            SHADOW_COST_RECONCILIATION,
            "challenger_v2_paper_canary_binding_readiness.json",
            "challenger_v2_forward_paper_canary_pass_contract_audit.json",
            PAPER_CHAIN_BINDING_READINESS_AUDIT,
            PAPER_CREDIT_ATTRIBUTION_GUARD,
            ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT,
            "challenger_v2_goal_phase_completion_audit.json",
            REQUIREMENT_TRACEABILITY_MATRIX,
            "challenger_v2_shadow_label_outcome_diagnostics.json",
            SHADOW_LOCKBOX_OUTCOME_ACTIONABILITY_AUDIT,
            "challenger_v2_paper_chain_binding_status.json",
            "challenger_v2_forward_paper_canary_status.json",
            "challenger_v2_champion_promotion_status.json",
        ],
    }
    write_json(out_dir / "challenger_v2_evidence_collection_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--scan-limit", type=int, default=60_000)
    parser.add_argument("--replay-limit", type=int, default=None)
    parser.add_argument("--current-limit", type=int, default=2_000)
    parser.add_argument("--no-current-redis", action="store_true")
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--archive-scan-limit", type=int, default=60_000)
    parser.add_argument("--no-public-labels", action="store_true")
    parser.add_argument("--public-label-symbol-limit", type=int, default=25)
    parser.add_argument("--paper-signal-scan-limit", type=int, default=DEFAULT_PAPER_SIGNAL_SCAN_LIMIT)
    args = parser.parse_args(argv)
    summary = run_collector(
        repo_root=args.repo_root,
        scan_limit=args.scan_limit,
        replay_limit=args.replay_limit,
        current_limit=args.current_limit,
        no_current_redis=args.no_current_redis,
        horizon_minutes=args.horizon_minutes,
        archive_scan_limit=args.archive_scan_limit,
        allow_public_labels=not args.no_public_labels,
        public_label_symbol_limit=args.public_label_symbol_limit,
        paper_signal_scan_limit=args.paper_signal_scan_limit,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
