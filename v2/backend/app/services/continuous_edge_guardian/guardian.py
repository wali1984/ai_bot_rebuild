"""Resident paper/replay A-grade edge guardian.

This service publishes truth artifacts and a V2-only paper admission gate. It
does not submit orders, cancel orders, mutate exchange leverage or margin mode,
write legacy Redis keys, trim Redis, or touch live transport.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


GOAL_ID = "V2_CONTINUOUS_90P_A_GRADE_EDGE_ZERO_LIQUIDATION_AND_1000X_COMPOUNDING_RELEASE"
READY_MARKER = f"{GOAL_ID}_READY"
BLOCKED_MARKER = f"{GOAL_ID}_BLOCKED"
SCHEMA_VERSION = "continuous_edge_guardian_v1"
MODEL_QUALITY_BUCKET_SNAPSHOT_LIMIT = 200
CAPITAL_RECOMMENDATION_SAMPLE_LIMIT = 25
HEDGE_ENGINE_SAMPLE_LIMIT = 25
STRATEGY_BRAIN_BUCKET_SNAPSHOT_LIMIT = 300
ZERO_LIQUIDATION_SAMPLE_LIMIT = 25

REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_REL = Path("operator_runtime/v2_continuous_edge_guardian/latest")
WORKLOG_REL = Path("claude_worklog/final_readiness/v2_continuous_edge_guardian/latest")
ADAPTIVE_REL = Path("operator_runtime/v2_adaptive_capital_productivity/latest")
TRAINER_REL = Path("v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard/latest")
PAPER_TRADE_MANAGEMENT_REL = Path("operator_runtime/v2_paper_trade_management/latest")
PAPER_TRADE_LIVE_REL = Path("operator_runtime/v2_trade_management_paper/live/latest")
SHADOW_OUTCOME_METRICS_REL = Path("v2_shadow_observation_outcome_metrics/latest/operator_dashboard_payload.json")

A_GRADE_EXECUTION_GATE_REDIS_KEY = "v2:continuous_edge_guardian:a_grade_execution_gate"
STATUS_REDIS_KEY = "v2:continuous_edge_guardian:status"
REDIS_TTL_SECONDS = 180
A_GRADE_EXECUTION_TIER = "A_GRADE_EXECUTION_PAPER"
B_GRADE_EXPLORATION_TIER = "B_GRADE_EXPLORATION_PAPER"
SHADOW_ONLY_TIER = "SHADOW_ONLY"
NO_TRADE_TIER = "NO_TRADE"

STRATEGY_BRAIN_STATES = (
    "ACTIVE",
    "REDUCED_SIZE",
    "B_GRADE_ONLY",
    "SHADOW_ONLY",
    "COOLDOWN",
    "QUARANTINED",
    "REEVALUATION",
)
REQUIRED_STRATEGY_EXPERTS = (
    "trend",
    "mean_reversion",
    "breakout",
    "momentum",
    "squeeze",
    "liquidation_cascade",
    "funding_oi_divergence",
    "orderbook_imbalance",
    "microstructure_reversal",
    "volatility_expansion",
    "public_intelligence",
    "hedged_protection",
    "no_trade",
)
RARE_EVENT_STRESS_SCENARIOS = (
    "gap_shock",
    "spread_explosion",
    "depth_collapse",
    "funding_spike",
    "correlated_portfolio_shock",
    "long_squeeze",
    "short_squeeze",
    "double_sided_liquidation_cascade",
    "mark_index_divergence",
    "exchange_api_delay",
)
RARE_EVENT_BUFFER_COMPONENTS = (
    "execution_uncertainty_bps",
    "correlation_stress_bps",
    "maintenance_margin_uncertainty_bps",
)

PHASES = {
    "phase_0_readiness_semantics": "Correct all readiness semantics",
    "phase_1_90p_target_contract": "Define the 90% target precisely",
    "phase_2_continuous_edge_guardian": "Build the Continuous Edge Guardian",
    "phase_3_untouched_holdout_evidence": "Untouched out-of-sample evidence",
    "phase_4_realtime_a_grade_paper_evidence": "Realtime A-grade paper evidence",
    "phase_5_adaptive_a_grade_selector": "Adaptive A-grade selector",
    "phase_6_model_quality_improvement_loop": "Model quality improvement loop",
    "phase_7_adaptive_strategy_brain": "Adaptive strategy brain",
    "phase_8_adaptive_capital_leverage_margin": "Adaptive capital, leverage and margin",
    "phase_9_zero_liquidation_architecture": "Zero-liquidation architecture",
    "phase_10_adaptive_hedge_engine": "Adaptive hedge engine",
    "phase_11_1000x_trajectory_contract": "1000x trajectory contract",
    "phase_12_anti_gaming_validation": "Anti-gaming validation",
    "phase_13_runtime_website_truth": "Runtime website truth",
}
VALID_PHASE_STATES = {"NOT_STARTED", "RUNNING", "PASS", "BLOCKED"}

REQUIRED_GOAL_FILES = (
    "GOAL_LOCK.json",
    "PHASE_LEDGER.json",
    "FINDING_BURNDOWN.json",
    "COMMANDS_RUN.md",
    "FILES_CHANGED.md",
    "VALIDATION_LEDGER.json",
    "CURRENT_BLOCKERS.json",
    "EVIDENCE_MANIFEST.json",
    "GO_NO_GO.md",
)

REQUIRED_COST_FIELDS = (
    "fees",
    "fees_usd",
    "fee_bps",
    "expected_fees_usd",
    "slippage",
    "slippage_usd",
    "expected_slippage_usd",
    "expected_slippage_bps",
    "funding",
    "funding_pnl_usd",
    "expected_funding_usd",
    "expected_funding_bps",
)
OBSERVED_EXECUTION_FIELDS = (
    "actual_observed_spread_entry_bps",
    "observed_bid_ask_spread_bps",
    "entry_orderbook_depth_usd",
    "orderbook_depth_usd",
    "entry_spread_source",
)
PIT_DECISION_FIELDS = (
    "decision_time",
    "available_at",
    "feature_cutoff",
)
TRUST_ENVELOPE_FIELD_ALIASES = {
    "prediction_id": ("prediction_id", "entry_prediction_id"),
    "signal_id": ("signal_id", "entry_signal_id"),
    "decision_id": ("decision_id",),
    "feature_snapshot_id": ("feature_snapshot_id", "entry_feature_snapshot_id"),
    "mtf_snapshot_id": ("mtf_snapshot_id",),
    "feature_cutoff": ("feature_cutoff", "entry_feature_cutoff"),
    "decision_time": ("decision_time", "entry_feature_decision_time"),
    "available_at": ("available_at", "entry_feature_available_at"),
    "symbol": ("symbol",),
    "timeframe": ("timeframe",),
    "selected_action": ("selected_action", "action", "side", "direction"),
    "model_version": ("model_version",),
    "checkpoint_id": ("checkpoint_id",),
    "source_hashes": ("source_hashes",),
}
OUTCOME_TARGET_FIELD_ALIASES = {
    "realized_net_pnl_bps": ("realized_net_pnl_bps", "realized_pnl_bps", "net_pnl_bps", "pnl_bps"),
    "realized_net_pnl_usd": ("realized_net_pnl_usd", "realized_pnl_usd", "net_pnl_usd", "pnl_usd"),
    "directional_outcome": ("directional_outcome",),
    "trade_outcome": ("trade_outcome", "outcome"),
    "selected_action": ("selected_action", "action", "side", "direction"),
    "action_was_profitable": ("action_was_profitable",),
    "holding_period": ("holding_period", "hold_time_seconds", "holding_period_seconds"),
    "fees": ("fees", "fees_usd", "fee_bps", "expected_fees_usd"),
    "slippage": ("slippage", "slippage_usd", "expected_slippage_usd", "expected_slippage_bps"),
    "funding": ("funding", "funding_pnl_usd", "expected_funding_usd", "expected_funding_bps"),
    "MFE": ("MFE", "mfe_bps", "mfe_usd"),
    "MAE": ("MAE", "mae_bps", "mae_usd"),
    "exit_reason": ("exit_reason",),
}
HEDGE_REQUIRED_FIELD_ALIASES = {
    "hedge_parent_id": ("hedge_parent_id",),
    "hedge_child_id": ("hedge_child_id",),
    "hedge_intent": ("hedge_intent",),
    "hedge_ratio": ("hedge_ratio",),
    "hedge_budget": ("hedge_budget", "hedge_budget_usd"),
    "expected_shortfall_before": ("expected_shortfall_before", "expected_shortfall_before_usd"),
    "expected_shortfall_after": ("expected_shortfall_after", "expected_shortfall_after_usd"),
    "maximum_duration": ("maximum_duration", "maximum_duration_seconds", "hedge_maximum_duration_seconds"),
    "unwind_plan": ("unwind_plan", "hedge_unwind_plan"),
    "pair_net_pnl": ("pair_net_pnl", "pair_net_pnl_usd"),
}
MAKER_TAKER_FIELDS = (
    "maker_probability",
    "taker_probability",
    "maker_taker_probability",
    "maker_taker_probabilities",
    "maker_taker_probability_source",
)
LATENCY_FIELDS = (
    "latency_ms",
    "paper_fill_latency_ms",
    "fill_latency_ms",
    "execution_latency_ms",
    "simulated_latency_ms",
)
PARTIAL_FILL_FIELDS = (
    "partial_fill_count",
    "partial_fills",
    "fill_count",
    "all_partial_fills",
    "partial_fill_plan",
)
MARK_INDEX_DIVERGENCE_FIELDS = (
    "mark_index_divergence_bps",
    "mark_price",
    "index_price",
    "mark_index_divergence",
)
DEPTH_FIELDS = (
    "entry_orderbook_depth_usd",
    "orderbook_depth_usd",
    "bid_depth_usd",
    "ask_depth_usd",
)


@dataclass(frozen=True)
class ContinuousEdgeGuardianPaths:
    repo_root: Path = REPO_ROOT

    @property
    def public_root(self) -> Path:
        return self.repo_root / "v2/frontend/public"

    @property
    def public_dir(self) -> Path:
        return self.public_root / PUBLIC_REL

    @property
    def worklog_dir(self) -> Path:
        return self.repo_root / WORKLOG_REL

    @property
    def goal_dir(self) -> Path:
        return self.repo_root / "goal_state" / GOAL_ID

    @property
    def adaptive_dir(self) -> Path:
        return self.public_root / ADAPTIVE_REL

    @property
    def trainer_dir(self) -> Path:
        return self.public_root / TRAINER_REL

    @property
    def paper_trade_management_dir(self) -> Path:
        return self.public_root / PAPER_TRADE_MANAGEMENT_REL

    @property
    def paper_trade_live_dir(self) -> Path:
        return self.public_root / PAPER_TRADE_LIVE_REL

    @property
    def holdout_rows_path(self) -> Path:
        return self.adaptive_dir / "out_of_sample_holdout_reverify_rows.jsonl"

    @property
    def holdout_rejected_path(self) -> Path:
        return self.adaptive_dir / "out_of_sample_holdout_reverify_rejected.jsonl"

    @property
    def holdout_manifest_path(self) -> Path:
        return self.adaptive_dir / "out_of_sample_holdout_reverify_rows.jsonl.manifest.json"

    @property
    def holdout_window_registry_path(self) -> Path:
        return self.adaptive_dir / "out_of_sample_holdout_window_registry.json"

    @property
    def holdout_window_candidate_audit_path(self) -> Path:
        return self.adaptive_dir / "out_of_sample_holdout_window_candidate_audit.json"

    @property
    def realtime_rows_path(self) -> Path:
        return self.adaptive_dir / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    @property
    def paper_adaptive_sizing_path(self) -> Path:
        return self.paper_trade_management_dir / "paper_adaptive_sizing_runtime_status.json"

    @property
    def paper_live_status_path(self) -> Path:
        return self.paper_trade_live_dir / "v2_trade_management_paper_live_status.json"

    @property
    def trainer_feedback_outcomes_path(self) -> Path:
        return self.paper_trade_management_dir / "trainer_feedback_outcomes.json"

    @property
    def paper_b_grade_model_quality_path(self) -> Path:
        return self.paper_trade_management_dir / "paper_b_grade_model_quality_status.json"

    @property
    def paper_b_grade_bucket_promotion_readiness_path(self) -> Path:
        return self.paper_trade_management_dir / "paper_b_grade_bucket_promotion_readiness_status.json"

    @property
    def paper_shadow_outcome_metrics_path(self) -> Path:
        return self.public_root / SHADOW_OUTCOME_METRICS_REL


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(dict(row), sort_keys=True, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )
    tmp.replace(path)


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
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def read_jsonl_rejection_summary(path: Path, *, sample_limit: int = 25) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    row_count = 0
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return {
            "row_count": 0,
            "rows_rejected_by_reason": {},
            "sample_rejections": [],
            "source_path": str(path),
            "source_present": False,
        }
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, Mapping):
                continue
            row_count += 1
            reasons = payload.get("reasons")
            if not isinstance(reasons, list):
                reasons = []
            normalized_reasons = sorted({str(reason) for reason in reasons if reason not in (None, "")})
            for reason in normalized_reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if len(samples) < sample_limit:
                samples.append(
                    {
                        "symbol": payload.get("symbol"),
                        "timeframe": payload.get("timeframe"),
                        "side": payload.get("side"),
                        "decision_time": payload.get("decision_time"),
                        "source_row_identity": payload.get("source_row_identity"),
                        "candidate_identity": payload.get("candidate_identity"),
                        "reasons": normalized_reasons,
                    }
                )
    return {
        "row_count": row_count,
        "rows_rejected_by_reason": {key: reason_counts[key] for key in sorted(reason_counts)},
        "sample_rejections": samples,
        "source_path": str(path),
        "source_present": True,
    }


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


def integer_count(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def mapping_rows(value: Any, *, limit: int = MODEL_QUALITY_BUCKET_SNAPSHOT_LIMIT) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, Mapping):
            rows.append(dict(item))
    return rows


def all_mapping_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def increment_count(counter: dict[str, int], value: Any) -> None:
    key = str(value) if value not in (None, "") else "UNKNOWN"
    counter[key] = counter.get(key, 0) + 1


def count_candidate_field(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        increment_count(counts, row.get(field))
    return {key: counts[key] for key in sorted(counts)}


def sum_finite_field(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    total = 0.0
    for row in rows:
        value = finite_float(row.get(field))
        if value is not None:
            total += value
    return total


def first_finite_from_sources(rows: Iterable[Mapping[str, Any]], *fields: str) -> float | None:
    for row in rows:
        sources: list[Mapping[str, Any]] = [row]
        model_inputs = row.get("model_inputs")
        if isinstance(model_inputs, Mapping):
            sources.append(model_inputs)
        for source in sources:
            for field in fields:
                value = finite_float(source.get(field))
                if value is not None:
                    return value
    return None


def has_any_field(row: Mapping[str, Any], fields: Iterable[str]) -> bool:
    return any(row.get(field) not in (None, "") for field in fields)


def first_field(row: Mapping[str, Any], fields: Iterable[str]) -> Any:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def aliased_field(row: Mapping[str, Any], aliases: Mapping[str, tuple[str, ...]], field: str) -> Any:
    return first_field(row, aliases.get(field, (field,)))


def normalized_action(row: Mapping[str, Any]) -> str:
    return str(
        first_present(
            row.get("selected_action"),
            row.get("action"),
            row.get("side"),
            row.get("direction"),
        )
        or ""
    ).strip().upper()


def is_no_trade(row: Mapping[str, Any]) -> bool:
    action = normalized_action(row)
    return action in {"NO_TRADE", "HOLD", "FLAT", "NONE", "ABSTAIN"}


def normalized_side(row: Mapping[str, Any]) -> str | None:
    action = normalized_action(row).lower()
    if action in {"long", "buy", "open_long", "proceed_long"} or action.endswith("_long"):
        return "LONG"
    if action in {"short", "sell", "open_short", "proceed_short"} or action.endswith("_short"):
        return "SHORT"
    return None


def normalized_symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "").strip().upper()


def normalized_timeframe(row: Mapping[str, Any]) -> str:
    return str(row.get("timeframe") or "").strip()


def normalized_tier(row: Mapping[str, Any]) -> str:
    return str(
        first_present(
            row.get("paper_opportunity_tier"),
            row.get("explicit_paper_opportunity_tier"),
            row.get("candidate_selection_tier"),
            row.get("admission_tier"),
            row.get("candidate_tier"),
        )
        or ""
    ).strip().upper()


def pre_guardian_a_grade_halted(row: Mapping[str, Any]) -> bool:
    tier = normalized_tier(row)
    pre_guardian_tier = str(row.get("pre_guardian_paper_opportunity_tier") or "").strip().upper()
    tier_reason = str(row.get("paper_opportunity_tier_reason") or "").strip().upper()
    fill_source = str(row.get("paper_fill_allowed_source") or "").strip().upper()
    return (
        tier == "SHADOW_ONLY"
        and pre_guardian_tier == A_GRADE_EXECUTION_TIER
        and (
            row.get("continuous_edge_guardian_forced_shadow_only") is True
            or tier_reason == "CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED"
            or fill_source == "CONTINUOUS_EDGE_GUARDIAN_BLOCKED_NEW_A_GRADE_ENTRIES"
        )
    )


def feedback_tier_rejection_reason(row: Mapping[str, Any]) -> str | None:
    tier = normalized_tier(row)
    if tier == B_GRADE_EXPLORATION_TIER:
        return "FEEDBACK_TIER_B_GRADE_EXPLORATION_PAPER_NOT_A_GRADE_EVIDENCE"
    if tier == SHADOW_ONLY_TIER:
        return "FEEDBACK_TIER_SHADOW_ONLY_NOT_A_GRADE_EVIDENCE"
    if tier == NO_TRADE_TIER:
        return "FEEDBACK_TIER_NO_TRADE_NOT_ECONOMIC_A_GRADE_EVIDENCE"
    if not tier:
        return "FEEDBACK_TIER_MISSING_NOT_A_GRADE_EVIDENCE"
    if tier != A_GRADE_EXECUTION_TIER:
        return "FEEDBACK_TIER_NOT_A_GRADE_EVIDENCE"
    return None


def selector_fingerprint(row: Mapping[str, Any]) -> str:
    return str(
        first_present(
            row.get("selector_policy_fingerprint"),
            row.get("frozen_selector_fingerprint"),
            row.get("policy_fingerprint"),
        )
        or ""
    ).strip()


def is_lifecycle_or_no_trade_strategy(row: Mapping[str, Any]) -> bool:
    strategy = str(
        first_present(
            row.get("strategy"),
            row.get("strategy_id"),
            row.get("strategy_family"),
            row.get("strategy_selected_mode"),
            row.get("strategy_router_selected_mode"),
        )
        or ""
    ).strip().lower()
    return any(token in strategy for token in ("reduce", "close", "exit", "no_trade"))


def normalized_strategy(row: Mapping[str, Any]) -> str:
    return str(
        first_present(
            row.get("strategy"),
            row.get("strategy_id"),
            row.get("strategy_family"),
            row.get("strategy_selected_mode"),
            row.get("strategy_router_selected_mode"),
        )
        or "UNKNOWN"
    ).strip()


def normalized_regime(row: Mapping[str, Any]) -> str:
    return str(
        first_present(
            row.get("regime"),
            row.get("market_regime"),
            row.get("market_regime_at_entry"),
            row.get("regime_id"),
        )
        or "UNKNOWN"
    ).strip()


def normalized_confidence_bucket(row: Mapping[str, Any]) -> str:
    explicit = first_present(row.get("confidence_bucket"), row.get("calibration_confidence_bucket"))
    if explicit not in (None, ""):
        return str(explicit).strip()
    confidence = finite_float(
        first_present(
            row.get("confidence_calibrated"),
            row.get("selected_action_probability"),
            row.get("confidence"),
            row.get("model_confidence"),
            row.get("prediction_confidence"),
            row.get("confidence_raw"),
        )
    )
    if confidence is None:
        return "UNKNOWN"
    confidence = min(max(confidence, 0.0), 0.999999)
    bucket_min = math.floor(confidence * 10.0) / 10.0
    bucket_max = min(bucket_min + 0.1, 1.0)
    return f"{bucket_min:.1f}-{bucket_max:.1f}"


def strategy_bucket_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        normalized_symbol(row),
        normalized_timeframe(row),
        str(first_present(row.get("side"), normalized_side(row), row.get("selected_action"), row.get("action")) or "UNKNOWN")
        .strip()
        .lower(),
        normalized_strategy(row),
        normalized_regime(row),
        normalized_confidence_bucket(row),
    )


def is_a_grade_candidate(row: Mapping[str, Any]) -> bool:
    return normalized_tier(row) == A_GRADE_EXECUTION_TIER


def maximum_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return max_drawdown


def tail_loss(values: list[float], *, percentile: float = 0.01) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    count = max(1, math.ceil(len(sorted_values) * percentile))
    return sum(sorted_values[:count]) / count


def stress_suite_mapping(row: Mapping[str, Any]) -> Mapping[str, Any]:
    suite = row.get("pre_entry_stress_tests")
    if isinstance(suite, Mapping):
        return suite
    suite = row.get("rare_event_stress_suite")
    if isinstance(suite, Mapping):
        return suite
    suite = row.get("stress_tests")
    if isinstance(suite, Mapping):
        return suite
    return {}


def stress_scenario_value(row: Mapping[str, Any], scenario: str) -> float | None:
    suite = stress_suite_mapping(row)
    value = suite.get(scenario)
    if isinstance(value, Mapping):
        value = first_present(
            value.get("required_buffer_bps"),
            value.get("adverse_move_bps"),
            value.get("shock_bps"),
            value.get("stress_bps"),
            value.get("bps"),
        )
    direct = finite_float(value)
    if direct is not None:
        return abs(direct)
    field_candidates = (
        f"{scenario}_bps",
        f"stress_{scenario}_bps",
        f"rare_event_{scenario}_bps",
        f"{scenario}_required_buffer_bps",
    )
    for field in field_candidates:
        direct = finite_float(row.get(field))
        if direct is not None:
            return abs(direct)
    return None


def stress_component_value(row: Mapping[str, Any], component: str) -> float | None:
    suite = stress_suite_mapping(row)
    value = first_present(
        suite.get(component),
        row.get(component),
        row.get(f"rare_event_{component}"),
        row.get(f"stress_{component}"),
    )
    direct = finite_float(value)
    return abs(direct) if direct is not None else None


def numeric_field_present(row: Mapping[str, Any], fields: Iterable[str]) -> bool:
    return any(finite_float(row.get(field)) is not None for field in fields)


def has_positive_depth(row: Mapping[str, Any]) -> bool:
    for field in DEPTH_FIELDS:
        value = finite_float(row.get(field))
        if value is not None and value > 0.0:
            return True
    bid = finite_float(row.get("bid_depth_usd"))
    ask = finite_float(row.get("ask_depth_usd"))
    return bool(bid is not None and bid > 0.0 and ask is not None and ask > 0.0)


def spread_is_fallback(row: Mapping[str, Any]) -> bool:
    if row.get("bid_ask_spread_bps_fallback") is True:
        return True
    spread_sources = (
        row.get("entry_spread_source"),
        row.get("actual_observed_spread_source"),
        row.get("observed_spread_source"),
    )
    if any("FALLBACK" in str(source or "").upper() for source in spread_sources):
        return True
    spread = finite_float(first_present(row.get("actual_observed_spread_entry_bps"), row.get("observed_bid_ask_spread_bps")))
    return bool(spread == 2.0 and any(str(source or "").upper().startswith("FALLBACK") for source in spread_sources))


def has_observed_spread(row: Mapping[str, Any]) -> bool:
    spread = finite_float(first_present(row.get("actual_observed_spread_entry_bps"), row.get("observed_bid_ask_spread_bps")))
    return bool(spread is not None and spread > 0.0 and not spread_is_fallback(row))


def has_mark_index_divergence(row: Mapping[str, Any]) -> bool:
    if has_any_field(row, ("mark_index_divergence_bps", "mark_index_divergence")):
        return True
    return row.get("mark_price") not in (None, "") and row.get("index_price") not in (None, "")


def economic_trade_id(row: Mapping[str, Any], fallback_index: int) -> str:
    return str(
        first_present(
            row.get("economic_trade_id"),
            row.get("parent_economic_trade_id"),
            row.get("hedge_parent_id"),
            row.get("parent_trade_id"),
            row.get("position_id"),
            row.get("trade_id"),
            row.get("trainer_feedback_id"),
            row.get("fill_id"),
            f"row_{fallback_index}",
        )
    )


def realized_pnl_usd(row: Mapping[str, Any]) -> float | None:
    return finite_float(
        first_present(
            row.get("realized_net_pnl_usd"),
            row.get("realized_pnl_usd"),
            row.get("net_pnl_usd"),
            row.get("pair_net_pnl"),
            row.get("pair_net_pnl_usd"),
            row.get("pnl_usd"),
        )
    )


def realized_pnl_bps(row: Mapping[str, Any]) -> float | None:
    direct = finite_float(
        first_present(
            row.get("realized_net_pnl_bps"),
            row.get("realized_pnl_bps"),
            row.get("net_pnl_bps"),
            row.get("pnl_bps"),
        )
    )
    if direct is not None:
        return direct
    usd = realized_pnl_usd(row)
    notional = finite_float(
        first_present(
            row.get("gross_notional_usd"),
            row.get("notional_usdt"),
            row.get("notional"),
            row.get("target_notional_usdt"),
        )
    )
    if usd is None or notional is None or notional <= 0.0:
        return None
    return (usd / notional) * 10000.0


def outcome_is_win(row: Mapping[str, Any], pnl_usd: float | None, pnl_bps: float | None) -> bool:
    outcome = str(row.get("trade_outcome") or row.get("outcome") or "").strip().upper()
    if outcome == "WIN":
        return True
    if outcome in {"LOSS", "BREAKEVEN"}:
        return False
    value = pnl_usd if pnl_usd is not None else pnl_bps
    return bool(value is not None and value > 0.0)


def close_sort_key(row: Mapping[str, Any], fallback_index: int) -> tuple[datetime, int]:
    for field in ("close_time", "exit_time", "closed_at", "generated_at", "decision_time"):
        parsed = parse_time(row.get(field))
        if parsed is not None:
            return parsed, fallback_index
    return datetime.fromtimestamp(0, tz=timezone.utc), fallback_index


def wilson_lower_bound(successes: int, total: int, z: float = 1.959963984540054) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1.0 + (z * z / total)
    centre = p + (z * z / (2.0 * total))
    margin = z * math.sqrt((p * (1.0 - p) + (z * z / (4.0 * total))) / total)
    return (centre - margin) / denom


def mean_lower_confidence_bound(values: list[float], z: float = 1.959963984540054) -> float | None:
    if not values:
        return None
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean
    std = statistics.pstdev(values)
    return mean - z * (std / math.sqrt(len(values)))


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.floor(q * (len(ordered) - 1))))
    return ordered[index]


def pit_violations_for_row(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    decision_time = parse_time(row.get("decision_time") or row.get("entry_feature_decision_time"))
    available_at = parse_time(row.get("available_at") or row.get("entry_feature_available_at"))
    feature_cutoff = parse_time(row.get("feature_cutoff") or row.get("entry_feature_cutoff"))
    if decision_time is None:
        reasons.append("MISSING_DECISION_TIME")
    if available_at is None:
        reasons.append("MISSING_AVAILABLE_AT")
    if feature_cutoff is None:
        reasons.append("MISSING_FEATURE_CUTOFF")
    if decision_time is not None and available_at is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if decision_time is not None and feature_cutoff is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    return reasons


def nested_value(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def extract_json_rows(
    path: Path,
    list_paths: Iterable[str],
    *,
    source_role: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = read_json(path, {})
    if not isinstance(payload, Mapping):
        return [], {
            "source_path": str(path),
            "source_role": source_role,
            "exists": path.exists(),
            "row_count": 0,
            "list_counts": {},
        }
    source_paper_only = payload.get("paper_only")
    source_places_real_order = payload.get("places_real_order")
    rows: list[dict[str, Any]] = []
    list_counts: dict[str, int] = {}
    for list_path in list_paths:
        source_rows = nested_value(payload, list_path)
        if not isinstance(source_rows, list):
            list_counts[list_path] = 0
            continue
        list_counts[list_path] = len(source_rows)
        for row in source_rows:
            if not isinstance(row, Mapping):
                continue
            normalized = dict(row)
            if source_paper_only not in (None, ""):
                normalized.setdefault("paper_only", source_paper_only)
            if source_places_real_order not in (None, ""):
                normalized.setdefault("places_real_order", source_places_real_order)
            normalized["_guardian_source_path"] = str(path)
            normalized["_guardian_source_list"] = list_path
            normalized["_guardian_source_role"] = source_role
            rows.append(normalized)
    return rows, {
        "source_path": str(path),
        "source_role": source_role,
        "exists": path.exists(),
        "row_count": len(rows),
        "list_counts": list_counts,
        "paper_only": source_paper_only,
        "places_real_order": source_places_real_order,
    }


def source_identity_aliases(row: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    fields = (
        "prediction_id",
        "entry_prediction_id",
        "source_prediction_id",
        "signal_id",
        "entry_signal_id",
        "decision_id",
        "allocation_id",
        "feature_snapshot_id",
        "entry_feature_snapshot_id",
        "position_id",
        "trade_id",
    )
    for field in fields:
        value = row.get(field)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text:
            continue
        aliases.add(text)
        if text.startswith("sig_"):
            aliases.add(text[4:])
        if text.startswith("signal_"):
            aliases.add(text[7:])
    return aliases


def build_candidate_index(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for alias in source_identity_aliases(row):
            index.setdefault(alias, []).append(row)
    return index


def candidate_matches_for_outcome(
    outcome: Mapping[str, Any],
    candidate_index: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[int] = set()
    for alias in source_identity_aliases(outcome):
        for candidate in candidate_index.get(alias, []):
            identity = id(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            matches.append(candidate)
    return matches


def missing_required_groups(row: Mapping[str, Any], required: Mapping[str, tuple[str, ...]]) -> list[str]:
    missing: list[str] = []
    for group, aliases in required.items():
        value = first_field(row, aliases)
        if group == "source_hashes":
            if not isinstance(value, Mapping) or not value:
                missing.append(group)
            continue
        if value in (None, ""):
            missing.append(group)
    return missing


def validation_record(outcome: Mapping[str, Any], candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    combined = dict(candidate or {})
    combined.update({key: value for key, value in outcome.items() if not str(key).startswith("_guardian_")})
    if candidate is not None:
        for field in (
            "paper_opportunity_tier",
            "explicit_paper_opportunity_tier",
            "candidate_selection_tier",
            "selector_policy_fingerprint",
            "frozen_selector_fingerprint",
            "policy_fingerprint",
            "candidate_selected_before_outcome",
            "candidate_selected_after_outcome",
            "allocation_id",
        ):
            if candidate.get(field) not in (None, ""):
                combined[field] = candidate.get(field)
    return combined


def close_time_for_row(row: Mapping[str, Any]) -> datetime | None:
    for field in ("close_time", "exit_time", "closed_at", "generated_at", "generated_utc"):
        parsed = parse_time(row.get(field))
        if parsed is not None:
            return parsed
    return None


def validate_realtime_evidence_row(
    outcome: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any] | None,
    generated_utc: str,
) -> list[str]:
    reasons: list[str] = []
    combined = validation_record(outcome, candidate)

    if outcome.get("trainer_consumable") is False:
        reasons.append("TRAINER_FEEDBACK_ROW_NOT_CONSUMABLE")
    if is_no_trade(combined):
        reasons.append("NO_TRADE_CANNOT_BE_RELEASE_ECONOMIC_WIN")
    if is_lifecycle_or_no_trade_strategy(combined):
        reasons.append("LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE")
    if normalized_side(combined) not in {"LONG", "SHORT"}:
        reasons.append("NON_DIRECTIONAL_ENTRY_ACTION")

    for source_name, source_row in (("candidate", candidate), ("outcome", outcome)):
        if source_row is None:
            continue
        if source_row.get("paper_only") is not True:
            reasons.append(f"{source_name.upper()}_PAPER_ONLY_FLAG_MISSING_OR_FALSE")
        if source_row.get("places_real_order") is not False:
            reasons.append(f"{source_name.upper()}_REAL_ORDER_FLAG_MISSING_OR_NOT_FALSE")
        if source_row.get("places_real_order") is True or source_row.get("live_order") is True:
            reasons.append(f"{source_name.upper()}_REAL_ORDER_FLAG_TRUE")
        if source_row.get("test_order") is True or source_row.get("test_orders") is True:
            reasons.append(f"{source_name.upper()}_TEST_ORDER_FLAG_TRUE")
        if source_row.get("leverage_mutation") is True:
            reasons.append(f"{source_name.upper()}_LEVERAGE_MUTATION_TRUE")
        if source_row.get("margin_mode_mutation") is True:
            reasons.append(f"{source_name.upper()}_MARGIN_MODE_MUTATION_TRUE")
        if source_row.get("legacy_redis_write") is True or source_row.get("writes_legacy_redis") is True:
            reasons.append(f"{source_name.upper()}_OLD_REDIS_WRITE_TRUE")

    if candidate is not None:
        if candidate.get("candidate_selected_before_outcome") is not True:
            reasons.append("CANDIDATE_NOT_MARKED_SELECTED_BEFORE_OUTCOME")
        if candidate.get("candidate_selected_after_outcome") is True or candidate.get("post_outcome_candidate_selection") is True:
            reasons.append("POST_OUTCOME_CANDIDATE_SELECTION")
        if normalized_tier(candidate) != A_GRADE_EXECUTION_TIER:
            if pre_guardian_a_grade_halted(candidate):
                reasons.append("A_GRADE_HALTED_BY_CONTINUOUS_EDGE_GUARDIAN")
            else:
                reasons.append("SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING")
        allocator_decision = str(candidate.get("allocator_decision") or "").strip().upper()
        if allocator_decision.startswith("BLOCK_"):
            reasons.append("ALLOCATOR_BLOCKED_CANDIDATE")
        candidate_decision_time = parse_time(candidate.get("decision_time") or candidate.get("entry_feature_decision_time"))
        outcome_close_time = close_time_for_row(outcome)
        if candidate_decision_time is not None and outcome_close_time is not None and candidate_decision_time > outcome_close_time:
            reasons.append("CANDIDATE_DECISION_AFTER_OUTCOME_CLOSE")
        candidate_symbol = normalized_symbol(candidate)
        outcome_symbol = normalized_symbol(outcome)
        if candidate_symbol and outcome_symbol and candidate_symbol != outcome_symbol:
            reasons.append("SYMBOL_MISMATCH_BETWEEN_CANDIDATE_AND_OUTCOME")
        candidate_timeframe = normalized_timeframe(candidate)
        outcome_timeframe = normalized_timeframe(outcome)
        if candidate_timeframe and outcome_timeframe and candidate_timeframe != outcome_timeframe:
            reasons.append("TIMEFRAME_MISMATCH_BETWEEN_CANDIDATE_AND_OUTCOME")
        candidate_side = normalized_side(candidate)
        outcome_side = normalized_side(outcome)
        if candidate_side and outcome_side and candidate_side != outcome_side:
            reasons.append("ACTION_MISMATCH_BETWEEN_CANDIDATE_AND_OUTCOME")
        candidate_feature_snapshot = first_present(candidate.get("entry_feature_snapshot_id"), candidate.get("feature_snapshot_id"))
        outcome_feature_snapshot = first_present(outcome.get("entry_feature_snapshot_id"), outcome.get("feature_snapshot_id"))
        if candidate_feature_snapshot and outcome_feature_snapshot and str(candidate_feature_snapshot) != str(outcome_feature_snapshot):
            reasons.append("FEATURE_SNAPSHOT_ID_MISMATCH")

    fingerprint = selector_fingerprint(combined)
    if not fingerprint:
        reasons.append("SOURCE_SELECTOR_POLICY_FINGERPRINT_MISSING")

    missing_envelope = missing_required_groups(combined, TRUST_ENVELOPE_FIELD_ALIASES)
    reasons.extend(f"MISSING_TRUST_ENVELOPE_{field.upper()}" for field in missing_envelope)
    missing_targets = missing_required_groups(combined, OUTCOME_TARGET_FIELD_ALIASES)
    reasons.extend(f"MISSING_OUTCOME_TARGET_{field.upper()}" for field in missing_targets)
    reasons.extend(pit_violations_for_row(combined))

    generated_time = parse_time(generated_utc)
    available_at = parse_time(combined.get("available_at") or combined.get("entry_feature_available_at"))
    if generated_time is not None and available_at is not None and available_at > generated_time:
        reasons.append("AVAILABLE_AT_AFTER_GUARDIAN_RUN_TIME")
    if combined.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABEL_USED_AS_DECISION_FEATURE")

    if not has_observed_spread(combined):
        reasons.append("MISSING_REAL_OBSERVED_SPREAD")
    if spread_is_fallback(combined):
        reasons.append("FALLBACK_COST_REPORTED_AS_MARKET_OBSERVED")
    if not has_positive_depth(combined):
        reasons.append("MISSING_DEPTH_DERIVED_PRICE_IMPACT_EVIDENCE")
    if not has_any_field(combined, MAKER_TAKER_FIELDS):
        reasons.append("MISSING_MAKER_TAKER_PROBABILITY")
    if not numeric_field_present(combined, LATENCY_FIELDS):
        reasons.append("MISSING_EXECUTION_LATENCY")
    if not has_any_field(combined, PARTIAL_FILL_FIELDS):
        reasons.append("MISSING_PARTIAL_FILL_EVIDENCE")
    if not has_mark_index_divergence(combined):
        reasons.append("MISSING_MARK_INDEX_DIVERGENCE")

    return sorted(set(reasons))


def admitted_realtime_record(outcome: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    final = validation_record(outcome, candidate)
    final["realtime_a_grade_release_evidence"] = True
    final["realtime_paper_reverify"] = True
    final["paper_only"] = True
    final["places_real_order"] = False
    final["candidate_selected_before_outcome"] = True
    final["post_outcome_candidate_selection"] = False
    final["trust_source_ids"] = {
        "candidate_source_path": candidate.get("_guardian_source_path"),
        "candidate_source_list": candidate.get("_guardian_source_list"),
        "outcome_source_path": outcome.get("_guardian_source_path"),
        "outcome_source_list": outcome.get("_guardian_source_list"),
        "prediction_id": first_present(final.get("prediction_id"), final.get("entry_prediction_id")),
        "signal_id": first_present(final.get("signal_id"), final.get("entry_signal_id")),
        "decision_id": final.get("decision_id"),
        "feature_snapshot_id": first_present(final.get("feature_snapshot_id"), final.get("entry_feature_snapshot_id")),
        "allocation_id": final.get("allocation_id"),
    }
    return final


def validate_standalone_reverify_row(row: Mapping[str, Any], *, generated_utc: str) -> list[str]:
    reasons = validate_realtime_evidence_row(row, candidate=None, generated_utc=generated_utc)
    if row.get("realtime_paper_reverify") is not True and row.get("realtime_a_grade_release_evidence") is not True:
        reasons.append("STANDALONE_REVERIFY_PROOF_FLAG_MISSING")
    if row.get("candidate_selected_before_outcome") is not True:
        reasons.append("CANDIDATE_NOT_MARKED_SELECTED_BEFORE_OUTCOME")
    if normalized_tier(row) != A_GRADE_EXECUTION_TIER:
        if pre_guardian_a_grade_halted(row):
            reasons.append("A_GRADE_HALTED_BY_CONTINUOUS_EDGE_GUARDIAN")
        else:
            reasons.append("SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING")
    return sorted(set(reasons))


def load_candidate_source_rows(paths: ContinuousEdgeGuardianPaths) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for source_rows, source_status in (
        extract_json_rows(
            paths.paper_adaptive_sizing_path,
            ("candidate_allocations", "sample_allocations"),
            source_role="paper_adaptive_sizing_runtime",
        ),
        extract_json_rows(
            paths.paper_live_status_path,
            (
                "paper_adaptive_sizing_runtime_status.candidate_allocations",
                "paper_adaptive_sizing_runtime_status.sample_allocations",
                "shadow_observations",
            ),
            source_role="paper_live_status",
        ),
    ):
        rows.extend(source_rows)
        statuses.append(source_status)
    return rows, statuses


def load_closed_feedback_rows(paths: ContinuousEdgeGuardianPaths) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, status = extract_json_rows(
        paths.trainer_feedback_outcomes_path,
        ("trainer_feedback_outcomes",),
        source_role="trainer_feedback_outcomes",
    )
    return rows, [status]


def acquire_realtime_a_grade_evidence(
    *,
    paths: ContinuousEdgeGuardianPaths,
    existing_reverify_rows: list[dict[str, Any]],
    generated_utc: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidate_rows, candidate_source_statuses = load_candidate_source_rows(paths)
    feedback_rows, feedback_source_statuses = load_closed_feedback_rows(paths)
    candidate_index = build_candidate_index(candidate_rows)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    rejected_by_reason: dict[str, int] = {}
    rejected_by_source_kind: dict[str, int] = {}
    rejected_by_feedback_tier: dict[str, int] = {}
    rejected_by_feedback_candidate_selected_before_outcome: dict[str, int] = {}
    rejected_by_feedback_counts_as_a_grade_evidence: dict[str, int] = {}
    feedback_tier_counts: dict[str, int] = {}
    feedback_pre_guardian_tier_counts: dict[str, int] = {}
    feedback_candidate_selected_before_outcome_counts: dict[str, int] = {}
    feedback_counts_as_a_grade_evidence_counts: dict[str, int] = {}
    feedback_trade_outcome_counts: dict[str, int] = {}

    for row in feedback_rows:
        increment_count(feedback_tier_counts, normalized_tier(row) or "__missing__")
        increment_count(
            feedback_pre_guardian_tier_counts,
            row.get("pre_guardian_paper_opportunity_tier") or "__missing__",
        )
        increment_count(
            feedback_candidate_selected_before_outcome_counts,
            row.get("candidate_selected_before_outcome"),
        )
        increment_count(
            feedback_counts_as_a_grade_evidence_counts,
            row.get("counts_as_a_grade_evidence"),
        )
        increment_count(feedback_trade_outcome_counts, row.get("trade_outcome"))

    def reject(row: Mapping[str, Any], reasons: list[str], *, source_kind: str) -> None:
        nonlocal rejected
        sorted_reasons = sorted(set(reasons))
        for reason in sorted_reasons:
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
        increment_count(rejected_by_source_kind, source_kind)
        increment_count(rejected_by_feedback_tier, normalized_tier(row) or "__missing__")
        increment_count(
            rejected_by_feedback_candidate_selected_before_outcome,
            row.get("candidate_selected_before_outcome"),
        )
        increment_count(
            rejected_by_feedback_counts_as_a_grade_evidence,
            row.get("counts_as_a_grade_evidence"),
        )
        rejected.append({
            "source_kind": source_kind,
            "source_path": row.get("_guardian_source_path"),
            "source_list": row.get("_guardian_source_list"),
            "prediction_id": first_present(row.get("prediction_id"), row.get("entry_prediction_id")),
            "signal_id": first_present(row.get("signal_id"), row.get("entry_signal_id")),
            "decision_id": row.get("decision_id"),
            "symbol": normalized_symbol(row),
            "timeframe": normalized_timeframe(row),
            "selected_action": normalized_action(row),
            "paper_opportunity_tier": normalized_tier(row) or None,
            "pre_guardian_paper_opportunity_tier": row.get("pre_guardian_paper_opportunity_tier"),
            "candidate_selected_before_outcome": row.get("candidate_selected_before_outcome"),
            "counts_as_a_grade_evidence": row.get("counts_as_a_grade_evidence"),
            "trade_outcome": row.get("trade_outcome"),
            "reasons": sorted_reasons,
        })

    for row in existing_reverify_rows:
        reasons = validate_standalone_reverify_row(row, generated_utc=generated_utc)
        if reasons:
            reject(row, reasons, source_kind="existing_reverify_row")
            continue
        accepted.append(dict(row))

    for outcome in feedback_rows:
        matches = candidate_matches_for_outcome(outcome, candidate_index)
        if not matches:
            reasons = ["MISSING_PRE_OUTCOME_A_GRADE_CANDIDATE"]
            tier_reason = feedback_tier_rejection_reason(outcome)
            if tier_reason:
                reasons.append(tier_reason)
            reject(
                outcome,
                reasons,
                source_kind="trainer_feedback_outcome",
            )
            continue
        best_candidate: dict[str, Any] | None = None
        best_reasons: list[str] | None = None
        for candidate in matches:
            reasons = validate_realtime_evidence_row(outcome, candidate=candidate, generated_utc=generated_utc)
            if not reasons:
                best_candidate = candidate
                best_reasons = []
                break
            if best_reasons is None or len(reasons) < len(best_reasons):
                best_candidate = candidate
                best_reasons = reasons
        if best_candidate is not None and best_reasons == []:
            accepted.append(admitted_realtime_record(outcome, best_candidate))
            continue
        reject(
            outcome,
            best_reasons or ["NO_VERIFIED_PRE_OUTCOME_A_GRADE_CANDIDATE_MATCH"],
            source_kind="trainer_feedback_outcome",
        )

    accepted_outcomes, accepted_audit = dedupe_economic_outcomes(accepted)
    candidate_tier_counts: dict[str, int] = {}
    candidate_allocator_counts: dict[str, int] = {}
    for row in candidate_rows:
        tier = normalized_tier(row) or "__missing__"
        candidate_tier_counts[tier] = candidate_tier_counts.get(tier, 0) + 1
        allocator = str(row.get("allocator_decision") or "__missing__").strip().upper()
        candidate_allocator_counts[allocator] = candidate_allocator_counts.get(allocator, 0) + 1
    fingerprints = sorted({selector_fingerprint(row) for row in accepted if selector_fingerprint(row)})
    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "PASSED" if accepted else "BLOCKED_NO_VERIFIED_REALTIME_A_GRADE_EVIDENCE",
        "policy": "closed outcomes count only after matching a pre-outcome A_GRADE_EXECUTION_PAPER candidate with complete PIT, cost, and execution evidence",
        "paper_only": True,
        "post_outcome_selection_allowed": False,
        "prediction_id_alone_sufficient_trust_evidence": False,
        "existing_reverify_row_count": len(existing_reverify_rows),
        "candidate_snapshot_row_count": len(candidate_rows),
        "candidate_index_alias_count": len(candidate_index),
        "closed_feedback_row_count": len(feedback_rows),
        "admitted_row_count": len(accepted),
        "admitted_economic_outcome_count": len(accepted_outcomes),
        "admitted_economic_outcome_audit": accepted_audit,
        "rejected_row_count": len(rejected),
        "rows_rejected_by_reason": {
            key: rejected_by_reason[key] for key in sorted(rejected_by_reason)
        },
        "rejected_by_source_kind": {
            key: rejected_by_source_kind[key] for key in sorted(rejected_by_source_kind)
        },
        "rejected_by_feedback_paper_opportunity_tier": {
            key: rejected_by_feedback_tier[key] for key in sorted(rejected_by_feedback_tier)
        },
        "rejected_by_feedback_candidate_selected_before_outcome": {
            key: rejected_by_feedback_candidate_selected_before_outcome[key]
            for key in sorted(rejected_by_feedback_candidate_selected_before_outcome)
        },
        "rejected_by_feedback_counts_as_a_grade_evidence": {
            key: rejected_by_feedback_counts_as_a_grade_evidence[key]
            for key in sorted(rejected_by_feedback_counts_as_a_grade_evidence)
        },
        "sample_rejections": rejected[:25],
        "feedback_paper_opportunity_tier_counts": {
            key: feedback_tier_counts[key] for key in sorted(feedback_tier_counts)
        },
        "feedback_pre_guardian_paper_opportunity_tier_counts": {
            key: feedback_pre_guardian_tier_counts[key]
            for key in sorted(feedback_pre_guardian_tier_counts)
        },
        "feedback_candidate_selected_before_outcome_counts": {
            key: feedback_candidate_selected_before_outcome_counts[key]
            for key in sorted(feedback_candidate_selected_before_outcome_counts)
        },
        "feedback_counts_as_a_grade_evidence_counts": {
            key: feedback_counts_as_a_grade_evidence_counts[key]
            for key in sorted(feedback_counts_as_a_grade_evidence_counts)
        },
        "feedback_trade_outcome_counts": {
            key: feedback_trade_outcome_counts[key] for key in sorted(feedback_trade_outcome_counts)
        },
        "candidate_tier_counts": {
            key: candidate_tier_counts[key] for key in sorted(candidate_tier_counts)
        },
        "candidate_allocator_decision_counts": {
            key: candidate_allocator_counts[key] for key in sorted(candidate_allocator_counts)
        },
        "selector_fingerprints_in_admitted_rows": fingerprints,
        "candidate_source_statuses": candidate_source_statuses,
        "feedback_source_statuses": feedback_source_statuses,
        "required_trust_envelope_fields": sorted(TRUST_ENVELOPE_FIELD_ALIASES),
        "required_outcome_targets": sorted(OUTCOME_TARGET_FIELD_ALIASES),
        "required_execution_evidence": [
            "real_observed_spread",
            "depth_derived_price_impact",
            "maker_taker_probability",
            "fees",
            "slippage",
            "funding",
            "latency",
            "partial_fills",
            "mark_index_divergence",
        ],
    }
    return accepted, status


def build_holdout_evidence_acquisition_status(
    *,
    paths: ContinuousEdgeGuardianPaths,
    holdout_rows: list[dict[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    manifest = read_json(paths.holdout_manifest_path, {})
    registry = read_json(paths.holdout_window_registry_path, {})
    candidate_audit = read_json(paths.holdout_window_candidate_audit_path, {})
    rejected_summary = read_jsonl_rejection_summary(paths.holdout_rejected_path)
    accepted_count = len(holdout_rows)
    rejected_count = int(rejected_summary.get("row_count") or 0)
    manifest_status = str(manifest.get("status") or "MISSING_HOLDOUT_REVERIFY_MANIFEST")
    registry_status = str(registry.get("status") or "MISSING_HOLDOUT_WINDOW_REGISTRY")
    candidate_audit_status = str(candidate_audit.get("status") or "MISSING_HOLDOUT_WINDOW_CANDIDATE_AUDIT")
    prediction_coverage = mapping_or_empty(
        manifest.get("holdout_prediction_coverage_status")
    )
    prediction_count = integer_count(
        prediction_coverage.get("point_in_time_valid_prediction_count")
    )
    registry_windows = [
        window
        for window in registry.get("windows") or []
        if isinstance(window, dict)
    ]
    forward_window_count = sum(
        1
        for window in registry_windows
        if window.get("forward_pre_registered") is True
        or (
            isinstance(window.get("exclusion_proof"), dict)
            and window.get("exclusion_proof", {}).get("status")
            == "PASSED_UNTOUCHED_FORWARD_PRE_REGISTRATION"
        )
    )

    blockers: list[dict[str, Any]] = []
    if accepted_count <= 0:
        blockers.append(
            {
                "reason": "NO_COUNTABLE_UNTOUCHED_HOLDOUT_ROWS",
                "observed": {
                    "accepted_a_grade_holdout_row_count": accepted_count,
                    "point_in_time_valid_prediction_count": prediction_count,
                },
                "required": "accepted pre-outcome A-grade holdout rows before release",
            }
        )
    if manifest_status not in {"PASSED", "PASSED_HOLDOUT_REVERIFY_ROWS"}:
        blockers.append(
            {
                "reason": "HOLDOUT_REVERIFY_MANIFEST_NOT_PASSED",
                "observed": manifest_status,
                "required": "PASSED",
            }
        )
    if registry_status not in {"PASSED", "COUNTABLE_UNTOUCHED_WINDOW_REGISTRY"}:
        blockers.append(
            {
                "reason": "HOLDOUT_WINDOW_REGISTRY_NOT_COUNTABLE",
                "observed": registry_status,
                "required": "COUNTABLE_UNTOUCHED_WINDOW_REGISTRY",
            }
        )
    if "NOT_COUNTABLE" in candidate_audit_status:
        blockers.append(
            {
                "reason": "HOLDOUT_WINDOW_CANDIDATES_NOT_COUNTABLE",
                "observed": candidate_audit_status,
                "required": "COUNTABLE_UNTOUCHED_WINDOW_CANDIDATES",
            }
        )
    reason_counts = rejected_summary.get("rows_rejected_by_reason") or {}
    if rejected_count > 0 and accepted_count <= 0:
        blockers.append(
            {
                "reason": "ALL_HOLDOUT_CANDIDATES_REJECTED",
                "observed": rejected_count,
                "required": "accepted untouched holdout rows",
                "rows_rejected_by_reason": reason_counts,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "PASSED" if accepted_count > 0 and not blockers else "BLOCKED_NO_COUNTABLE_UNTOUCHED_HOLDOUT_EVIDENCE",
        "policy": "holdout rows count only after pre-registered untouched window proof and pre-outcome A-grade candidate selection",
        "accepted_row_count": accepted_count,
        "rejected_row_count": rejected_count,
        "point_in_time_valid_prediction_count": prediction_count,
        "holdout_prediction_coverage_status": dict(prediction_coverage)
        if prediction_coverage
        else None,
        "rows_rejected_by_reason": reason_counts,
        "sample_rejections": rejected_summary.get("sample_rejections") or [],
        "source_paths": {
            "accepted_rows": str(paths.holdout_rows_path),
            "rejected_rows": str(paths.holdout_rejected_path),
            "manifest": str(paths.holdout_manifest_path),
            "window_registry": str(paths.holdout_window_registry_path),
            "window_candidate_audit": str(paths.holdout_window_candidate_audit_path),
        },
        "source_statuses": {
            "manifest_status": manifest_status,
            "window_registry_status": registry_status,
            "window_candidate_audit_status": candidate_audit_status,
            "forward_pre_registered_window_count": forward_window_count,
            "forward_pre_registration_armed": forward_window_count > 0,
        },
        "registered_window_count": registry.get("registered_window_count"),
        "forward_pre_registered_window_count": forward_window_count,
        "candidate_window_count": len(candidate_audit.get("windows") or [])
        if isinstance(candidate_audit.get("windows"), list)
        else None,
        "blockers": blockers,
        "post_outcome_candidate_selection_allowed": False,
        "future_labels_used_as_decision_features_allowed": False,
    }


def dedupe_economic_outcomes(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    no_trade_rows = 0
    for index, row in enumerate(rows):
        if is_no_trade(row):
            no_trade_rows += 1
            continue
        grouped.setdefault(economic_trade_id(row, index), []).append(row)

    outcomes: list[dict[str, Any]] = []
    hedge_leg_group_count = 0
    for trade_id, members in grouped.items():
        if len(members) > 1:
            hedge_leg_group_count += 1
        base = dict(members[0])
        pnl_usd_values = [realized_pnl_usd(member) for member in members]
        pnl_bps_values = [realized_pnl_bps(member) for member in members]
        usd_values = [value for value in pnl_usd_values if value is not None]
        bps_values = [value for value in pnl_bps_values if value is not None]
        if usd_values:
            base["realized_net_pnl_usd"] = sum(usd_values)
        if bps_values:
            base["realized_net_pnl_bps"] = sum(bps_values)
        base["economic_trade_id"] = trade_id
        base["economic_outcome_member_count"] = len(members)
        base["hedge_structure_counted_as_one_outcome"] = len(members) > 1
        outcomes.append(base)

    outcomes.sort(key=lambda row: close_sort_key(row, 0))
    audit = {
        "input_row_count": len(rows),
        "economic_outcome_count": len(outcomes),
        "no_trade_rows_excluded_from_win_count": no_trade_rows,
        "hedged_structures_counted_as_single_outcome": hedge_leg_group_count,
    }
    return outcomes, audit


def compute_economic_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes, audit = dedupe_economic_outcomes(rows)
    pnl_usd: list[float] = []
    pnl_bps: list[float] = []
    wins = 0
    side_counts = {"LONG": 0, "SHORT": 0}
    symbols: set[str] = set()
    timeframes: set[str] = set()
    strategy_regime: set[tuple[str, str]] = set()
    pit_violations: list[dict[str, Any]] = []
    accounting_errors: list[dict[str, Any]] = []
    liquidation_events = 0
    fallback_cost_rows = 0

    for index, row in enumerate(outcomes):
        usd = realized_pnl_usd(row)
        bps = realized_pnl_bps(row)
        if usd is not None:
            pnl_usd.append(usd)
        if bps is not None:
            pnl_bps.append(bps)
        if outcome_is_win(row, usd, bps):
            wins += 1
        side = normalized_side(row)
        if side in side_counts:
            side_counts[side] += 1
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if symbol:
            symbols.add(symbol)
        if timeframe:
            timeframes.add(timeframe)
        strategy = str(first_present(row.get("strategy"), row.get("strategy_id"), row.get("strategy_family"), "UNKNOWN"))
        regime = str(first_present(row.get("regime"), row.get("market_regime"), row.get("market_regime_at_entry"), "UNKNOWN"))
        strategy_regime.add((strategy, regime))
        reasons = pit_violations_for_row(row)
        if reasons:
            pit_violations.append({
                "economic_trade_id": row.get("economic_trade_id"),
                "reasons": reasons,
            })
        missing_costs = []
        if not has_any_field(row, REQUIRED_COST_FIELDS):
            missing_costs.append("MISSING_FEES_SLIPPAGE_OR_FUNDING_ACCOUNTING")
        if not has_any_field(row, OBSERVED_EXECUTION_FIELDS):
            missing_costs.append("MISSING_OBSERVED_EXECUTION_COST_EVIDENCE")
        if missing_costs:
            accounting_errors.append({
                "economic_trade_id": row.get("economic_trade_id"),
                "reasons": missing_costs,
            })
        if (
            row.get("bid_ask_spread_bps_fallback") is True
            or str(row.get("entry_spread_source") or "").upper().startswith("FALLBACK")
            or finite_float(row.get("actual_observed_spread_entry_bps")) == 2.0
            and str(row.get("actual_observed_spread_source") or "").upper().startswith("FALLBACK")
        ):
            fallback_cost_rows += 1
        if row.get("liquidation_event") is True or "LIQUIDATION" in str(row.get("exit_reason") or "").upper():
            liquidation_events += 1

    total = len(outcomes)
    win_rate = (wins / total) if total else None
    rolling: dict[str, Any] = {}
    for window in (100, 300, 1000):
        selected = outcomes[-window:]
        selected_count = len(selected)
        selected_wins = sum(
            1
            for row in selected
            if outcome_is_win(row, realized_pnl_usd(row), realized_pnl_bps(row))
        )
        rolling[f"rolling_{window}_trade_count"] = selected_count
        rolling[f"rolling_{window}_trade_win_rate"] = (
            selected_wins / selected_count if selected_count else None
        )

    profit = sum(value for value in pnl_usd if value > 0.0)
    loss = abs(sum(value for value in pnl_usd if value < 0.0))
    if not pnl_usd and pnl_bps:
        profit = sum(value for value in pnl_bps if value > 0.0)
        loss = abs(sum(value for value in pnl_bps if value < 0.0))
    profit_factor = None
    if profit > 0.0 and loss == 0.0:
        profit_factor = math.inf
    elif loss > 0.0:
        profit_factor = profit / loss

    expectancy_bps = statistics.fmean(pnl_bps) if pnl_bps else None
    expectancy_lcb_bps = mean_lower_confidence_bound(pnl_bps)
    worst_one_percent_loss_bps = quantile(pnl_bps, 0.01)
    drawdown_source = pnl_usd if pnl_usd else pnl_bps

    return {
        **audit,
        "closed_economic_trade_count": total,
        "win_count": wins,
        "loss_or_breakeven_count": max(0, total - wins),
        "win_rate": win_rate,
        "overall_95pct_lower_confidence_bound_win_rate": wilson_lower_bound(wins, total),
        **rolling,
        "after_cost_expectancy_bps": expectancy_bps,
        "expectancy_95pct_lower_bound_bps": expectancy_lcb_bps,
        "profit_factor": profit_factor,
        "worst_1_percent_loss_bps": worst_one_percent_loss_bps,
        "maximum_drawdown": max_drawdown(drawdown_source),
        "liquidation_event_count": liquidation_events,
        "accounting_reconciliation_errors": len(accounting_errors),
        "point_in_time_violations": len(pit_violations),
        "fallback_cost_rows": fallback_cost_rows,
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "symbols": sorted(symbols),
        "timeframes": sorted(timeframes),
        "side_counts": side_counts,
        "strategy_regime_combo_count": len(strategy_regime),
        "pit_violation_samples": pit_violations[:25],
        "accounting_error_samples": accounting_errors[:25],
    }


def apply_holdout_prediction_coverage(
    metrics: dict[str, Any],
    holdout_acquisition_status: Mapping[str, Any],
) -> dict[str, Any]:
    coverage = mapping_or_empty(
        holdout_acquisition_status.get("holdout_prediction_coverage_status")
    )
    prediction_count = integer_count(coverage.get("point_in_time_valid_prediction_count"))
    symbol_count = integer_count(coverage.get("symbol_count"))
    timeframe_count = integer_count(coverage.get("timeframe_count"))
    if prediction_count <= 0:
        metrics.setdefault(
            "point_in_time_valid_prediction_count",
            metrics.get("closed_economic_trade_count", 0),
        )
        metrics.setdefault("holdout_prediction_symbol_count", metrics.get("symbol_count", 0))
        metrics.setdefault("holdout_prediction_timeframe_count", metrics.get("timeframe_count", 0))
        metrics.setdefault("holdout_prediction_coverage_status", coverage or None)
        return metrics

    metrics["point_in_time_valid_prediction_count"] = prediction_count
    metrics["holdout_prediction_symbol_count"] = symbol_count
    metrics["holdout_prediction_timeframe_count"] = timeframe_count
    metrics["holdout_prediction_selected_policy_action_counts"] = dict(
        mapping_or_empty(coverage.get("selected_policy_action_counts"))
    )
    metrics["holdout_prediction_symbols"] = list(coverage.get("symbols") or [])
    metrics["holdout_prediction_timeframes"] = list(coverage.get("timeframes") or [])
    metrics["holdout_prediction_coverage_status"] = coverage
    metrics["holdout_prediction_coverage_counts_as_a_grade_evidence"] = False
    metrics["holdout_prediction_coverage_counts_no_trade_as_win"] = False
    return metrics


def phase3_holdout_prediction_coverage_snapshot(
    holdout_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    contract = build_acceptance_contract()
    minimum = contract["minimum_untouched_holdout_evidence"]
    required_timeframes = [str(item) for item in minimum["timeframes"]]
    required_actions = ["LONG", "SHORT", "NO_TRADE"]
    coverage = mapping_or_empty(holdout_metrics.get("holdout_prediction_coverage_status"))
    action_counts = mapping_or_empty(
        holdout_metrics.get("holdout_prediction_selected_policy_action_counts")
    )
    observed_timeframes = {
        str(item) for item in holdout_metrics.get("holdout_prediction_timeframes") or []
    }
    if not observed_timeframes:
        observed_timeframes = {str(item) for item in holdout_metrics.get("timeframes") or []}
    missing_timeframes = [
        timeframe for timeframe in required_timeframes if timeframe not in observed_timeframes
    ]
    missing_actions = [
        action for action in required_actions if integer_count(action_counts.get(action)) <= 0
    ]
    prediction_count = integer_count(
        holdout_metrics.get("point_in_time_valid_prediction_count")
    )
    symbol_count = integer_count(holdout_metrics.get("holdout_prediction_symbol_count"))

    blockers: list[dict[str, Any]] = []
    if prediction_count < minimum["point_in_time_valid_predictions"]:
        blockers.append(
            {
                "reason": "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS",
                "observed": prediction_count,
                "required": minimum["point_in_time_valid_predictions"],
            }
        )
    if symbol_count < minimum["symbols_where_available"]:
        blockers.append(
            {
                "reason": "INSUFFICIENT_UNTOUCHED_HOLDOUT_SYMBOL_COVERAGE",
                "observed": symbol_count,
                "required": minimum["symbols_where_available"],
            }
        )
    if missing_timeframes:
        blockers.append(
            {
                "reason": "INSUFFICIENT_UNTOUCHED_HOLDOUT_TIMEFRAME_COVERAGE",
                "observed_missing_timeframes": missing_timeframes,
                "required_timeframes": required_timeframes,
            }
        )
    if missing_actions:
        blockers.append(
            {
                "reason": "INSUFFICIENT_UNTOUCHED_HOLDOUT_ACTION_COVERAGE",
                "observed_selected_policy_action_counts": dict(action_counts),
                "required_selected_policy_actions": required_actions,
            }
        )

    return {
        "schema_version": "continuous_edge_guardian_phase3_holdout_prediction_coverage_v1",
        "status": (
            "READY_PHASE3_HOLDOUT_PREDICTION_COVERAGE"
            if not blockers
            else "BLOCKED_PHASE3_HOLDOUT_PREDICTION_COVERAGE"
        ),
        "policy": (
            "Counts point-in-time-valid frozen-policy holdout predictions for "
            "Phase 3 coverage only. It does not admit A-grade economic evidence."
        ),
        "source_status": coverage.get("status"),
        "point_in_time_valid_prediction_count": prediction_count,
        "required_point_in_time_valid_prediction_count": minimum["point_in_time_valid_predictions"],
        "symbol_count": symbol_count,
        "required_symbol_count": minimum["symbols_where_available"],
        "timeframe_count": integer_count(holdout_metrics.get("holdout_prediction_timeframe_count")),
        "required_timeframes": required_timeframes,
        "observed_timeframes": sorted(observed_timeframes),
        "missing_timeframes": missing_timeframes,
        "selected_policy_action_counts": dict(action_counts),
        "required_selected_policy_actions": required_actions,
        "missing_selected_policy_actions": missing_actions,
        "closed_economic_trade_count": integer_count(
            holdout_metrics.get("closed_economic_trade_count")
        ),
        "counts_as_a_grade_evidence": False,
        "counts_no_trade_as_win": False,
        "no_trade_counted_as_economic_win": False,
        "paper_only": True,
        "places_real_order": False,
        "blockers": blockers,
    }


def build_acceptance_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "target_scope": "closed_economic_a_grade_trades",
        "economic_trade_definition": [
            "entry",
            "all_partial_fills",
            "all_reductions",
            "all_hedge_legs",
            "all_fees",
            "all_slippage",
            "all_funding",
            "final_close",
        ],
        "hedged_structure_outcome_counting": "parent_and_all_hedges_count_as_one_economic_outcome",
        "continuous_gates": {
            "rolling_100_trade_win_rate_min": 0.90,
            "rolling_300_trade_win_rate_min": 0.90,
            "rolling_1000_trade_win_rate_min_when_available": 0.90,
            "overall_95pct_lower_confidence_bound_win_rate_min": 0.90,
            "after_cost_expectancy_bps_min_exclusive": 0.0,
            "expectancy_95pct_lower_bound_bps_min_exclusive": 0.0,
            "profit_factor_min": 2.0,
            "liquidation_event_count_max": 0,
            "accounting_reconciliation_errors_max": 0,
            "point_in_time_violations_max": 0,
        },
        "minimum_realtime_evidence": {
            "closed_a_grade_economic_trades": 1000,
            "active_symbols": 50,
            "long_outcomes": 250,
            "short_outcomes": 250,
            "strategy_regime_combinations": 10,
        },
        "minimum_untouched_holdout_evidence": {
            "point_in_time_valid_predictions": 50000,
            "symbols_where_available": 100,
            "timeframes": ["1m", "5m", "15m", "1h", "4h"],
        },
        "bucket_rule": {
            "minimum_evidence_count_required": "configured_per_bucket",
            "point_win_rate_min": 0.90,
            "positive_after_cost_expectancy_required": True,
            "positive_lower_confidence_bound_required": True,
            "failing_bucket_execution_tier": "SHADOW_ONLY",
            "permanent_symbol_blacklists_allowed": False,
        },
        "live_boundary": {
            "paper_and_replay_only_during_goal": True,
            "real_order_execution_allowed": False,
            "exchange_leverage_mutation_allowed": False,
            "exchange_margin_mode_mutation_allowed": False,
        },
    }


def gate_failures(metrics: Mapping[str, Any], *, realtime: bool) -> list[dict[str, Any]]:
    contract = build_acceptance_contract()
    gates = contract["continuous_gates"]
    minimum = contract["minimum_realtime_evidence"] if realtime else contract["minimum_untouched_holdout_evidence"]
    failures: list[dict[str, Any]] = []

    def add(reason: str, observed: Any, required: Any) -> None:
        failures.append({"reason": reason, "observed": observed, "required": required})

    if realtime:
        if metrics["closed_economic_trade_count"] < minimum["closed_a_grade_economic_trades"]:
            add(
                "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES",
                metrics["closed_economic_trade_count"],
                minimum["closed_a_grade_economic_trades"],
            )
        if metrics["symbol_count"] < minimum["active_symbols"]:
            add("INSUFFICIENT_REALTIME_SYMBOL_COVERAGE", metrics["symbol_count"], minimum["active_symbols"])
        if metrics["side_counts"]["LONG"] < minimum["long_outcomes"]:
            add("INSUFFICIENT_REALTIME_LONG_OUTCOMES", metrics["side_counts"]["LONG"], minimum["long_outcomes"])
        if metrics["side_counts"]["SHORT"] < minimum["short_outcomes"]:
            add("INSUFFICIENT_REALTIME_SHORT_OUTCOMES", metrics["side_counts"]["SHORT"], minimum["short_outcomes"])
        if metrics["strategy_regime_combo_count"] < minimum["strategy_regime_combinations"]:
            add(
                "INSUFFICIENT_REALTIME_STRATEGY_REGIME_COVERAGE",
                metrics["strategy_regime_combo_count"],
                minimum["strategy_regime_combinations"],
            )
    else:
        pit_prediction_count = integer_count(
            metrics.get("point_in_time_valid_prediction_count")
        ) or integer_count(metrics.get("closed_economic_trade_count"))
        holdout_symbol_count = integer_count(
            metrics.get("holdout_prediction_symbol_count")
        ) or integer_count(metrics.get("symbol_count"))
        if pit_prediction_count < minimum["point_in_time_valid_predictions"]:
            add(
                "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS",
                pit_prediction_count,
                minimum["point_in_time_valid_predictions"],
            )
        if holdout_symbol_count < minimum["symbols_where_available"]:
            add(
                "INSUFFICIENT_UNTOUCHED_HOLDOUT_SYMBOL_COVERAGE",
                holdout_symbol_count,
                minimum["symbols_where_available"],
            )
        holdout_timeframes = {
            str(item)
            for item in (
                metrics.get("holdout_prediction_timeframes")
                or metrics.get("timeframes")
                or []
            )
        }
        missing_timeframes = [
            str(timeframe)
            for timeframe in minimum["timeframes"]
            if str(timeframe) not in holdout_timeframes
        ]
        if missing_timeframes:
            add(
                "INSUFFICIENT_UNTOUCHED_HOLDOUT_TIMEFRAME_COVERAGE",
                missing_timeframes,
                minimum["timeframes"],
            )
        action_counts = mapping_or_empty(
            metrics.get("holdout_prediction_selected_policy_action_counts")
        )
        missing_actions = [
            action
            for action in ("LONG", "SHORT", "NO_TRADE")
            if integer_count(action_counts.get(action)) <= 0
        ]
        if missing_actions:
            add(
                "INSUFFICIENT_UNTOUCHED_HOLDOUT_ACTION_COVERAGE",
                missing_actions,
                ["LONG", "SHORT", "NO_TRADE"],
            )

    for window in (100, 300, 1000):
        key = f"rolling_{window}_trade_win_rate"
        observed = metrics.get(key)
        required = gates["rolling_1000_trade_win_rate_min_when_available"] if window == 1000 else gates[f"rolling_{window}_trade_win_rate_min"]
        available = metrics.get(f"rolling_{window}_trade_count", 0) >= window
        if window == 1000 and not available:
            continue
        if window in {100, 300} and metrics.get(f"rolling_{window}_trade_count", 0) < window:
            add(f"INSUFFICIENT_ROLLING_{window}_TRADE_WINDOW", metrics.get(f"rolling_{window}_trade_count"), window)
        elif observed is None or observed < required:
            add(f"ROLLING_{window}_WIN_RATE_BELOW_90P", observed, required)

    lcb = metrics.get("overall_95pct_lower_confidence_bound_win_rate")
    if lcb is None or lcb < gates["overall_95pct_lower_confidence_bound_win_rate_min"]:
        add("OVERALL_95PCT_LCB_WIN_RATE_BELOW_90P", lcb, gates["overall_95pct_lower_confidence_bound_win_rate_min"])
    expectancy = metrics.get("after_cost_expectancy_bps")
    if expectancy is None or expectancy <= gates["after_cost_expectancy_bps_min_exclusive"]:
        add("AFTER_COST_EXPECTANCY_NOT_POSITIVE", expectancy, "> 0")
    expectancy_lcb = metrics.get("expectancy_95pct_lower_bound_bps")
    if expectancy_lcb is None or expectancy_lcb <= gates["expectancy_95pct_lower_bound_bps_min_exclusive"]:
        add("EXPECTANCY_95PCT_LCB_NOT_POSITIVE", expectancy_lcb, "> 0")
    pf = metrics.get("profit_factor")
    if pf is None or pf < gates["profit_factor_min"]:
        add("PROFIT_FACTOR_BELOW_2", pf, gates["profit_factor_min"])
    if metrics.get("liquidation_event_count", 0) > 0:
        add("LIQUIDATION_EVENT_COUNT_NONZERO", metrics.get("liquidation_event_count"), 0)
    if metrics.get("accounting_reconciliation_errors", 0) > 0:
        add("ACCOUNTING_RECONCILIATION_ERRORS_NONZERO", metrics.get("accounting_reconciliation_errors"), 0)
    if metrics.get("point_in_time_violations", 0) > 0:
        add("POINT_IN_TIME_VIOLATIONS_NONZERO", metrics.get("point_in_time_violations"), 0)
    if metrics.get("fallback_cost_rows", 0) > 0:
        add("FALLBACK_COSTS_REPORTED_IN_EVIDENCE", metrics.get("fallback_cost_rows"), 0)
    return failures


def guardian_status_from_failures(metrics: Mapping[str, Any], failures: list[Mapping[str, Any]]) -> str:
    reasons = {str(item.get("reason") or "") for item in failures}
    if metrics.get("liquidation_event_count", 0) > 0:
        return "A_GRADE_HALTED_LIQUIDATION_RISK"
    if any("POINT_IN_TIME" in reason or "ACCOUNTING" in reason for reason in reasons):
        return "A_GRADE_HALTED_DATA_INTEGRITY"
    if any("FALLBACK_COST" in reason for reason in reasons):
        return "A_GRADE_HALTED_EXECUTION_COST"
    if any("DRAWDOWN" in reason for reason in reasons):
        return "A_GRADE_HALTED_DRAWDOWN"
    if any("TAIL" in reason for reason in reasons):
        return "A_GRADE_HALTED_TAIL_RISK"
    return "A_GRADE_HALTED_PERFORMANCE" if failures else "A_GRADE_ACTIVE"


def build_goal_lock(started_utc: str) -> dict[str, Any]:
    return {
        "goal_id": GOAL_ID,
        "started_utc": started_utc,
        "single_goal": True,
        "continuous_runtime_guard_required": True,
        "live_execution_allowed": False,
        "exchange_mutation_allowed": False,
        "fixed_sizing_allowed": False,
        "martingale_allowed": False,
        "evidence_reset_allowed": False,
    }


def build_readiness_truth(
    *,
    trainer_learning: Mapping[str, Any],
    realtime_failures: list[Mapping[str, Any]],
    holdout_failures: list[Mapping[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    learning_ready = bool(
        first_present(
            trainer_learning.get("trainer_learning_ready"),
            trainer_learning.get("WEIGHTS_UPDATING"),
            trainer_learning.get("weights_updating"),
        )
    )
    optimizer_steps = finite_float(
        first_present(
            trainer_learning.get("optimizer_steps_last_hour"),
            trainer_learning.get("optimizer_steps_total"),
            trainer_learning.get("optimizer_steps_this_cycle"),
        )
    )
    weights_updating = bool(learning_ready or (optimizer_steps is not None and optimizer_steps > 0.0))
    edge_proven = not realtime_failures and not holdout_failures
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "trainer_process_status": "PROCESS_ACTIVE",
        "cuda_inference_status": "INFERENCE_ACTIVE",
        "prediction_publication_status": "INFERENCE_ACTIVE",
        "PROCESS_ACTIVE": True,
        "INFERENCE_ACTIVE": True,
        "WEIGHTS_UPDATING": weights_updating,
        "CALIBRATION_ACTIVE": bool(trainer_learning.get("CALIBRATION_ACTIVE") or trainer_learning.get("calibration_active") or weights_updating),
        "EDGE_PROVEN": edge_proven,
        "A_GRADE_EXECUTION_READY": False if not edge_proven else True,
        "ZERO_LIQUIDATION_READY": edge_proven,
        "1000X_TRAJECTORY_READY": False,
        "LIVE_READY": False,
        "online_learning_status": (
            "WEIGHTS_UPDATING_A_GRADE_EDGE_NOT_PROVEN"
            if weights_updating else "BLOCKED_NO_VERIFIED_WEIGHT_UPDATE"
        ),
        "effective_trainer_mode": first_present(
            trainer_learning.get("effective_trainer_mode"),
            "REPLAY_AND_ONLINE_LEARNING" if weights_updating else "INFERENCE_ONLY",
        ),
        "last_successful_weight_update_at": trainer_learning.get("last_successful_weight_update_at"),
        "readiness_invariant": {
            "trainer_learning_activity_does_not_imply_a_grade_execution_ready": True,
            "a_grade_execution_ready_requires_all_performance_and_safety_gates": True,
            "live_ready_requires_operator_approval_account_readiness_and_live_pre_submit_parity": True,
            "generic_ready_suppressed_while_accuracy_near_30_percent": True,
        },
    }


def build_model_quality_snapshot(
    *,
    trainer_quality: Mapping[str, Any],
    paper_b_grade_quality: Mapping[str, Any],
    paper_b_grade_bucket_readiness: Mapping[str, Any],
    paper_shadow_outcome_metrics: Mapping[str, Any] | None = None,
    source_paths: Mapping[str, str],
) -> dict[str, Any]:
    trainer_quality = mapping_or_empty(trainer_quality)
    paper_b_grade_quality = mapping_or_empty(paper_b_grade_quality)
    paper_b_grade_bucket_readiness = mapping_or_empty(paper_b_grade_bucket_readiness)
    paper_shadow_outcome_metrics = mapping_or_empty(paper_shadow_outcome_metrics)
    shadow_summary = mapping_or_empty(paper_shadow_outcome_metrics.get("shadow_outcome_summary"))
    bucket_metrics = mapping_rows(
        paper_b_grade_quality.get("metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket")
    )
    confidence_reliability_buckets = mapping_rows(paper_b_grade_quality.get("confidence_reliability_buckets"))
    promotion_buckets = mapping_rows(paper_b_grade_bucket_readiness.get("buckets"))
    shadow_metric_safe = (
        paper_shadow_outcome_metrics.get("counted_as_fill") is False
        and paper_shadow_outcome_metrics.get("affects_pnl_ledger") is False
        and paper_shadow_outcome_metrics.get("opens_paper_fill_gate") is False
        and paper_shadow_outcome_metrics.get("writes_legacy_redis") is False
        and paper_shadow_outcome_metrics.get("writes_exchange_orders") is False
    )
    shadow_classified_count = int(
        finite_float(
            first_present(
                shadow_summary.get("classified_outcome_count"),
                paper_shadow_outcome_metrics.get("classified_shadow_outcome_count"),
            )
        )
        or 0
    )
    shadow_false_block_count = int(
        finite_float(
            first_present(
                shadow_summary.get("false_block_candidate_count"),
                paper_shadow_outcome_metrics.get("shadow_false_block_candidate_count"),
            )
        )
        or 0
    )
    shadow_no_trade_correct_count = int(
        finite_float(
            first_present(
                shadow_summary.get("no_trade_correct_count"),
                paper_shadow_outcome_metrics.get("shadow_no_trade_correct_count"),
            )
        )
        or 0
    )
    shadow_outcome_count = int(
        finite_float(first_present(shadow_summary.get("outcome_count"), paper_shadow_outcome_metrics.get("outcome_count")))
        or 0
    )
    trade_outcome_counts = mapping_or_empty(paper_b_grade_quality.get("trade_outcome_counts"))
    executed_profitable_count = int(finite_float(trade_outcome_counts.get("WIN")) or 0)
    shadow_recall_denominator = executed_profitable_count + shadow_false_block_count
    shadow_opportunity_recall = None
    shadow_opportunity_false_negative_rate = None
    if shadow_metric_safe and shadow_classified_count > 0 and shadow_recall_denominator > 0:
        shadow_opportunity_recall = executed_profitable_count / shadow_recall_denominator
        shadow_opportunity_false_negative_rate = shadow_false_block_count / shadow_recall_denominator
    recall_value = first_present(
        paper_b_grade_quality.get("recall"),
        shadow_opportunity_recall,
        trainer_quality.get("recall"),
    )
    false_negative_rate_value = first_present(
        paper_b_grade_quality.get("false_negative_rate"),
        shadow_opportunity_false_negative_rate,
        trainer_quality.get("false_negative_rate"),
    )
    snapshot = {
        "schema_version": "continuous_edge_guardian_model_quality_snapshot_v1",
        "generated_utc": first_present(
            paper_b_grade_quality.get("generated_utc"),
            trainer_quality.get("generated_utc"),
        ),
        "status": first_present(
            paper_b_grade_quality.get("status"),
            trainer_quality.get("status"),
            "MODEL_QUALITY_NOT_PUBLISHED",
        ),
        "scope": first_present(
            paper_b_grade_quality.get("scope"),
            "TRAINER_RUNTIME_ACCURACY_CALIBRATION_ONLY",
        ),
        "primary_source": (
            "paper_b_grade_model_quality_status"
            if paper_b_grade_quality
            else "trainer_accuracy_calibration_runtime_status"
        ),
        "paper_only": True,
        "places_real_order": False,
        "source_counts_as_a_grade_evidence": paper_b_grade_quality.get("counts_as_a_grade_evidence"),
        "source_a_grade_promotion_allowed": paper_b_grade_quality.get("a_grade_promotion_allowed"),
        "source_live_ready_implication": paper_b_grade_quality.get("live_ready_implication"),
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "quality_activity_does_not_imply_a_grade_execution_ready": True,
        "directional_accuracy": first_present(
            paper_b_grade_quality.get("directional_accuracy"),
            trainer_quality.get("directional_accuracy"),
            trainer_quality.get("overall_directional_accuracy"),
        ),
        "expected_move_mae": first_present(
            paper_b_grade_quality.get("expected_move_mae"),
            trainer_quality.get("expected_move_mae"),
            trainer_quality.get("expected_move_mae_bps"),
        ),
        "brier_score": first_present(
            paper_b_grade_quality.get("brier_score"),
            trainer_quality.get("brier_score"),
        ),
        "ece": first_present(
            paper_b_grade_quality.get("ece"),
            trainer_quality.get("ece"),
            trainer_quality.get("expected_calibration_error"),
        ),
        "precision": first_present(
            paper_b_grade_quality.get("precision"),
            paper_b_grade_quality.get("directional_up_precision"),
            trainer_quality.get("precision"),
        ),
        "directional_up_precision": paper_b_grade_quality.get("directional_up_precision"),
        "recall": recall_value,
        "directional_up_recall": paper_b_grade_quality.get("directional_up_recall"),
        "recall_unavailable_reason": (
            None
            if recall_value is not None
            else first_present(
                paper_b_grade_quality.get("recall_unavailable_reason"),
                trainer_quality.get("recall_unavailable_reason"),
            )
        ),
        "recall_source": (
            "paper_b_grade_quality_direct"
            if paper_b_grade_quality.get("recall") is not None
            else "shadow_outcome_false_block_candidates"
            if shadow_opportunity_recall is not None
            else "trainer_quality_direct"
            if trainer_quality.get("recall") is not None
            else None
        ),
        "false_positive_rate": first_present(
            paper_b_grade_quality.get("false_positive_rate"),
            paper_b_grade_quality.get("directional_up_false_positive_rate"),
            trainer_quality.get("false_positive_rate"),
        ),
        "directional_up_false_positive_rate": paper_b_grade_quality.get("directional_up_false_positive_rate"),
        "false_negative_rate": false_negative_rate_value,
        "directional_up_false_negative_rate": paper_b_grade_quality.get("directional_up_false_negative_rate"),
        "false_negative_rate_unavailable_reason": (
            None
            if false_negative_rate_value is not None
            else first_present(
                paper_b_grade_quality.get("false_negative_rate_unavailable_reason"),
                trainer_quality.get("false_negative_rate_unavailable_reason"),
            )
        ),
        "false_negative_rate_source": (
            "paper_b_grade_quality_direct"
            if paper_b_grade_quality.get("false_negative_rate") is not None
            else "shadow_outcome_false_block_candidates"
            if shadow_opportunity_false_negative_rate is not None
            else "trainer_quality_direct"
            if trainer_quality.get("false_negative_rate") is not None
            else None
        ),
        "shadow_opportunity_recall": shadow_opportunity_recall,
        "shadow_opportunity_false_negative_rate": shadow_opportunity_false_negative_rate,
        "shadow_opportunity_metric_scope": "PAPER_ONLY_NON_FILL_NO_PNL_SHADOW_OUTCOMES",
        "shadow_opportunity_metrics_counted_as_a_grade_evidence": False,
        "shadow_opportunity_metrics_a_grade_promotion_allowed": False,
        "shadow_opportunity_metrics_live_ready_implication": False,
        "shadow_opportunity_metrics_accepted_for_model_quality": bool(
            shadow_metric_safe and shadow_classified_count > 0
        ),
        "shadow_outcome_count": shadow_outcome_count,
        "shadow_classified_outcome_count": shadow_classified_count,
        "shadow_no_trade_correct_count": shadow_no_trade_correct_count,
        "shadow_false_block_candidate_count": shadow_false_block_count,
        "shadow_executed_profitable_b_grade_count": executed_profitable_count,
        "shadow_recall_denominator": (
            shadow_recall_denominator
            if shadow_metric_safe and shadow_classified_count > 0
            else None
        ),
        "after_cost_expectancy_bps": paper_b_grade_quality.get("after_cost_expectancy_bps"),
        "expectancy_95pct_lower_confidence_bound_bps": paper_b_grade_quality.get(
            "expectancy_95pct_lower_confidence_bound_bps"
        ),
        "profit_factor": paper_b_grade_quality.get("profit_factor"),
        "profit_factor_numeric": paper_b_grade_quality.get("profit_factor_numeric"),
        "win_rate_after_cost": paper_b_grade_quality.get("win_rate_after_cost"),
        "win_rate_95pct_lower_confidence_bound": paper_b_grade_quality.get(
            "win_rate_95pct_lower_confidence_bound"
        ),
        "directional_sample_count": paper_b_grade_quality.get("directional_sample_count"),
        "calibration_sample_count": paper_b_grade_quality.get("calibration_sample_count"),
        "expected_move_mae_sample_count": paper_b_grade_quality.get("expected_move_mae_sample_count"),
        "b_grade_closed_outcome_count": paper_b_grade_quality.get("b_grade_closed_outcome_count"),
        "source_feedback_row_count": paper_b_grade_quality.get("source_feedback_row_count"),
        "trade_outcome_counts": paper_b_grade_quality.get("trade_outcome_counts", {}),
        "rows_rejected_by_reason": paper_b_grade_quality.get("rows_rejected_by_reason", {}),
        "confidence_reliability_buckets": confidence_reliability_buckets,
        "confidence_reliability_bucket_count": len(confidence_reliability_buckets),
        "metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket": bucket_metrics,
        "bucket_metric_count": len(bucket_metrics),
        "bucket_metric_snapshot_limit": MODEL_QUALITY_BUCKET_SNAPSHOT_LIMIT,
        "required_phase6_dimensions": [
            "symbol",
            "timeframe",
            "side",
            "strategy",
            "regime",
            "confidence_bucket",
        ],
        "bucket_promotion_readiness": {
            "schema_version": paper_b_grade_bucket_readiness.get("schema_version"),
            "generated_utc": paper_b_grade_bucket_readiness.get("generated_utc"),
            "status": first_present(
                paper_b_grade_bucket_readiness.get("status"),
                "B_GRADE_BUCKET_PROMOTION_READINESS_NOT_PUBLISHED",
            ),
            "scope": paper_b_grade_bucket_readiness.get("scope"),
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
            "live_ready_implication": False,
            "source_b_grade_closed_outcome_count": paper_b_grade_bucket_readiness.get(
                "source_b_grade_closed_outcome_count"
            ),
            "source_bucket_count": paper_b_grade_bucket_readiness.get("source_bucket_count"),
            "metric_ready_bucket_count": paper_b_grade_bucket_readiness.get("metric_ready_bucket_count"),
            "a_grade_promotable_bucket_count": paper_b_grade_bucket_readiness.get(
                "a_grade_promotable_bucket_count"
            ),
            "blocker_counts": paper_b_grade_bucket_readiness.get("blocker_counts", {}),
            "thresholds": paper_b_grade_bucket_readiness.get("thresholds", {}),
            "buckets": promotion_buckets,
            "published_bucket_count": len(promotion_buckets),
            "bucket_snapshot_limit": MODEL_QUALITY_BUCKET_SNAPSHOT_LIMIT,
        },
        "source_paths": dict(source_paths),
    }
    required_metrics = [
        "directional_accuracy",
        "expected_move_mae",
        "brier_score",
        "ece",
        "precision",
        "recall",
        "false_positive_rate",
        "false_negative_rate",
        "after_cost_expectancy_bps",
    ]
    snapshot["missing_required_metrics"] = [
        field for field in required_metrics if snapshot.get(field) is None
    ]
    return snapshot


def build_strategy_brain_status(
    *,
    paper_b_grade_quality: Mapping[str, Any],
    paper_b_grade_bucket_readiness: Mapping[str, Any],
    feedback_rows: list[dict[str, Any]],
    edge_ready: bool,
    generated_utc: str,
    source_paths: Mapping[str, str],
) -> dict[str, Any]:
    paper_b_grade_quality = mapping_or_empty(paper_b_grade_quality)
    paper_b_grade_bucket_readiness = mapping_or_empty(paper_b_grade_bucket_readiness)
    thresholds = mapping_or_empty(paper_b_grade_bucket_readiness.get("thresholds"))
    minimum_bucket_sample_count = int(
        first_present(thresholds.get("minimum_bucket_sample_count"), 30) or 30
    )

    merged_buckets: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for row in all_mapping_rows(
        paper_b_grade_quality.get("metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket")
    ):
        merged_buckets[strategy_bucket_key(row)] = {
            **row,
            "source_quality_bucket_present": True,
            "source_promotion_bucket_present": False,
        }
    for row in all_mapping_rows(paper_b_grade_bucket_readiness.get("buckets")):
        existing = merged_buckets.get(strategy_bucket_key(row), {})
        merged_buckets[strategy_bucket_key(row)] = {
            **existing,
            **row,
            "source_quality_bucket_present": bool(existing),
            "source_promotion_bucket_present": True,
        }

    realized_by_key: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in feedback_rows:
        if is_no_trade(row):
            continue
        pnl = realized_pnl_bps(row)
        if pnl is None:
            continue
        realized_by_key.setdefault(strategy_bucket_key(row), []).append(row)

    bucket_statuses: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    eligibility_counts: dict[str, int] = {}
    strategy_summaries: dict[str, dict[str, Any]] = {}

    for key in sorted(merged_buckets):
        row = merged_buckets[key]
        symbol, timeframe, side, strategy, regime, confidence_bucket = key
        sample_count = int(
            first_present(row.get("closed_economic_outcome_count"), row.get("sample_count"), 0) or 0
        )
        win_rate = finite_float(first_present(row.get("point_win_rate_after_cost"), row.get("win_rate_after_cost")))
        win_rate_lcb = finite_float(row.get("win_rate_95pct_lower_confidence_bound"))
        expectancy_bps = finite_float(row.get("after_cost_expectancy_bps"))
        expectancy_lcb_bps = finite_float(row.get("expectancy_95pct_lower_confidence_bound_bps"))
        profit_factor_numeric = finite_float(row.get("profit_factor_numeric"))
        profit_factor_raw = row.get("profit_factor")
        profit_factor_passes = bool(row.get("profit_factor_is_infinite")) or (
            profit_factor_numeric is not None and profit_factor_numeric >= 2.0
        )
        sample_count_passes = bool(row.get("sample_count_passes")) or sample_count >= minimum_bucket_sample_count
        point_win_rate_passes = bool(row.get("point_win_rate_passes")) or (
            win_rate is not None and win_rate >= 0.90
        )
        win_rate_lcb_passes = bool(row.get("win_rate_lcb_passes")) or (
            win_rate_lcb is not None and win_rate_lcb >= 0.90
        )
        expectancy_after_cost_passes = bool(row.get("expectancy_after_cost_passes")) or (
            expectancy_bps is not None and expectancy_bps > 0.0
        )
        expectancy_lcb_passes = bool(row.get("expectancy_lcb_passes")) or (
            expectancy_lcb_bps is not None and expectancy_lcb_bps > 0.0
        )
        metric_conditions_pass = bool(row.get("bucket_metric_conditions_pass")) or all(
            (
                sample_count_passes,
                point_win_rate_passes,
                win_rate_lcb_passes,
                expectancy_after_cost_passes,
                expectancy_lcb_passes,
                profit_factor_passes,
            )
        )
        promotion_allowed = bool(row.get("a_grade_promotion_allowed"))
        lifecycle_strategy = is_lifecycle_or_no_trade_strategy(row)
        losing_bucket = (
            (expectancy_bps is not None and expectancy_bps <= 0.0)
            or (win_rate is not None and win_rate < 0.50)
            or (profit_factor_numeric is not None and profit_factor_numeric < 1.0)
        )

        blocker_reasons = sorted(
            {
                str(reason)
                for reason in [
                    *(
                        row.get("metric_blocker_reasons")
                        if isinstance(row.get("metric_blocker_reasons"), list)
                        else []
                    ),
                    *(
                        row.get("promotion_blocker_reasons")
                        if isinstance(row.get("promotion_blocker_reasons"), list)
                        else []
                    ),
                ]
                if reason not in (None, "")
            }
        )
        if lifecycle_strategy:
            blocker_reasons.append("LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_STRATEGY")
            state = "QUARANTINED"
            execution_tier = SHADOW_ONLY_TIER
        elif losing_bucket:
            blocker_reasons.append("LOSING_BUCKET_LOSES_EXECUTION_ELIGIBILITY")
            state = "SHADOW_ONLY"
            execution_tier = SHADOW_ONLY_TIER
        elif promotion_allowed and metric_conditions_pass and edge_ready:
            state = "ACTIVE"
            execution_tier = A_GRADE_EXECUTION_TIER
        elif not sample_count_passes:
            state = "REEVALUATION"
            execution_tier = B_GRADE_EXPLORATION_TIER
        elif metric_conditions_pass:
            state = "B_GRADE_ONLY"
            execution_tier = B_GRADE_EXPLORATION_TIER
        elif expectancy_after_cost_passes or expectancy_lcb_passes:
            state = "B_GRADE_ONLY"
            execution_tier = B_GRADE_EXPLORATION_TIER
        else:
            state = "SHADOW_ONLY"
            execution_tier = SHADOW_ONLY_TIER

        realized_rows = sorted(
            realized_by_key.get(key, []),
            key=lambda item: str(first_present(item.get("decision_time"), item.get("exit_time"), item.get("close_time"), "")),
        )
        realized_values = [
            value
            for value in (realized_pnl_bps(item) for item in realized_rows)
            if value is not None
        ]
        drawdown_bps = maximum_drawdown(realized_values)
        tail_loss_bps = tail_loss(realized_values)
        posterior_edge_bps = first_present(expectancy_lcb_bps, expectancy_bps)
        win_rate_uncertainty = (
            win_rate - win_rate_lcb
            if win_rate is not None and win_rate_lcb is not None
            else None
        )
        expectancy_uncertainty_bps = (
            expectancy_bps - expectancy_lcb_bps
            if expectancy_bps is not None and expectancy_lcb_bps is not None
            else None
        )
        a_grade_execution_eligible = state == "ACTIVE"
        paper_exploration_eligible = state in {"B_GRADE_ONLY", "REEVALUATION"}
        capital_weight = 1.0 if a_grade_execution_eligible else 0.0
        learning_weight = 1.0 if paper_exploration_eligible else 0.0

        increment_count(state_counts, state)
        increment_count(eligibility_counts, execution_tier)
        bucket_payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "strategy": strategy,
            "regime": regime,
            "confidence_bucket": confidence_bucket,
            "sample_count": sample_count,
            "posterior_edge_bps": posterior_edge_bps,
            "posterior_edge_method": "expectancy_lcb_from_realized_bucket_else_point_expectancy",
            "uncertainty": {
                "win_rate_minus_lcb": win_rate_uncertainty,
                "expectancy_minus_lcb_bps": expectancy_uncertainty_bps,
            },
            "win_rate": win_rate,
            "win_rate_95pct_lower_confidence_bound": win_rate_lcb,
            "expectancy_bps": expectancy_bps,
            "expectancy_95pct_lower_confidence_bound_bps": expectancy_lcb_bps,
            "profit_factor": profit_factor_raw,
            "profit_factor_numeric": profit_factor_numeric,
            "drawdown_bps": drawdown_bps,
            "tail_loss_bps": tail_loss_bps,
            "risk_metrics_source": (
                "exact_feedback_bucket"
                if realized_values else "unavailable_for_exact_confidence_bucket"
            ),
            "weight": capital_weight,
            "capital_weight": capital_weight,
            "learning_weight": learning_weight,
            "state": state,
            "eligibility": execution_tier,
            "a_grade_execution_eligible": a_grade_execution_eligible,
            "paper_exploration_eligible": paper_exploration_eligible,
            "live_routeable": False,
            "counts_as_a_grade_evidence": False,
            "blocker_reasons": sorted(set(blocker_reasons)),
            "metric_conditions_pass": metric_conditions_pass,
            "promotion_allowed_by_source": promotion_allowed,
            "source_quality_bucket_present": bool(row.get("source_quality_bucket_present")),
            "source_promotion_bucket_present": bool(row.get("source_promotion_bucket_present")),
        }
        bucket_statuses.append(bucket_payload)

        summary = strategy_summaries.setdefault(
            strategy,
            {
                "strategy": strategy,
                "sample_count": 0,
                "bucket_count": 0,
                "active_bucket_count": 0,
                "b_grade_only_bucket_count": 0,
                "shadow_only_bucket_count": 0,
                "quarantined_bucket_count": 0,
                "reevaluation_bucket_count": 0,
                "weighted_win_rate_numerator": 0.0,
                "weighted_expectancy_numerator": 0.0,
                "posterior_edge_values": [],
                "tail_loss_values": [],
                "drawdown_values": [],
                "state": "SHADOW_ONLY",
                "eligibility": SHADOW_ONLY_TIER,
                "weight": 0.0,
            },
        )
        summary["sample_count"] += sample_count
        summary["bucket_count"] += 1
        if state == "ACTIVE":
            summary["active_bucket_count"] += 1
        elif state == "B_GRADE_ONLY":
            summary["b_grade_only_bucket_count"] += 1
        elif state == "SHADOW_ONLY":
            summary["shadow_only_bucket_count"] += 1
        elif state == "QUARANTINED":
            summary["quarantined_bucket_count"] += 1
        elif state == "REEVALUATION":
            summary["reevaluation_bucket_count"] += 1
        if win_rate is not None and sample_count > 0:
            summary["weighted_win_rate_numerator"] += win_rate * sample_count
        if expectancy_bps is not None and sample_count > 0:
            summary["weighted_expectancy_numerator"] += expectancy_bps * sample_count
        if posterior_edge_bps is not None:
            summary["posterior_edge_values"].append(float(posterior_edge_bps))
        if tail_loss_bps is not None:
            summary["tail_loss_values"].append(tail_loss_bps)
        if drawdown_bps is not None:
            summary["drawdown_values"].append(drawdown_bps)

    strategy_payloads: list[dict[str, Any]] = []
    for strategy in sorted(strategy_summaries):
        summary = strategy_summaries[strategy]
        sample_count = summary["sample_count"]
        if summary["active_bucket_count"] > 0:
            state = "ACTIVE"
            eligibility = A_GRADE_EXECUTION_TIER
            weight = 1.0
        elif summary["b_grade_only_bucket_count"] > 0:
            state = "B_GRADE_ONLY"
            eligibility = B_GRADE_EXPLORATION_TIER
            weight = 0.0
        elif summary["reevaluation_bucket_count"] > 0:
            state = "REEVALUATION"
            eligibility = B_GRADE_EXPLORATION_TIER
            weight = 0.0
        elif summary["quarantined_bucket_count"] == summary["bucket_count"]:
            state = "QUARANTINED"
            eligibility = SHADOW_ONLY_TIER
            weight = 0.0
        else:
            state = "SHADOW_ONLY"
            eligibility = SHADOW_ONLY_TIER
            weight = 0.0
        strategy_payloads.append(
            {
                "strategy": strategy,
                "sample_count": sample_count,
                "bucket_count": summary["bucket_count"],
                "posterior_edge_bps": (
                    statistics.mean(summary["posterior_edge_values"])
                    if summary["posterior_edge_values"] else None
                ),
                "uncertainty": {
                    "source": "bucket_lower_confidence_bounds",
                    "active_bucket_count": summary["active_bucket_count"],
                    "shadow_only_bucket_count": summary["shadow_only_bucket_count"],
                    "quarantined_bucket_count": summary["quarantined_bucket_count"],
                    "reevaluation_bucket_count": summary["reevaluation_bucket_count"],
                },
                "win_rate": (
                    summary["weighted_win_rate_numerator"] / sample_count
                    if sample_count > 0 else None
                ),
                "expectancy_bps": (
                    summary["weighted_expectancy_numerator"] / sample_count
                    if sample_count > 0 else None
                ),
                "profit_factor": None,
                "drawdown_bps": min(summary["drawdown_values"]) if summary["drawdown_values"] else None,
                "tail_loss_bps": min(summary["tail_loss_values"]) if summary["tail_loss_values"] else None,
                "weight": weight,
                "state": state,
                "eligibility": eligibility,
                "a_grade_execution_eligible": state == "ACTIVE",
                "paper_exploration_eligible": state in {"B_GRADE_ONLY", "REEVALUATION"},
                "live_routeable": False,
            }
        )

    active_count = state_counts.get("ACTIVE", 0)
    status = (
        "ACTIVE_A_GRADE_STRATEGY_BRAIN"
        if active_count > 0 and edge_ready
        else "BLOCKED_NO_A_GRADE_STRATEGY_ELIGIBILITY"
    )
    evidence_fragmentation = mapping_or_empty(
        paper_b_grade_bucket_readiness.get("evidence_fragmentation_status")
    )
    label_collection_priority = all_mapping_rows(
        paper_b_grade_bucket_readiness.get("paper_only_label_collection_priority_buckets")
    )
    return {
        "schema_version": "continuous_edge_guardian_strategy_brain_status_v1",
        "generated_utc": generated_utc,
        "status": status,
        "paper_only": True,
        "places_real_order": False,
        "live_routeable": False,
        "edge_ready_dependency_passed": edge_ready,
        "required_strategy_experts": list(REQUIRED_STRATEGY_EXPERTS),
        "state_allowed_values": list(STRATEGY_BRAIN_STATES),
        "execution_tier_allowed_values": [
            A_GRADE_EXECUTION_TIER,
            B_GRADE_EXPLORATION_TIER,
            SHADOW_ONLY_TIER,
            NO_TRADE_TIER,
        ],
        "bucket_count": len(bucket_statuses),
        "published_bucket_count": min(len(bucket_statuses), STRATEGY_BRAIN_BUCKET_SNAPSHOT_LIMIT),
        "bucket_snapshot_limit": STRATEGY_BRAIN_BUCKET_SNAPSHOT_LIMIT,
        "strategy_count": len(strategy_payloads),
        "a_grade_active_bucket_count": active_count,
        "b_grade_only_bucket_count": state_counts.get("B_GRADE_ONLY", 0),
        "reevaluation_bucket_count": state_counts.get("REEVALUATION", 0),
        "shadow_only_bucket_count": state_counts.get("SHADOW_ONLY", 0),
        "quarantined_bucket_count": state_counts.get("QUARANTINED", 0),
        "state_counts": {key: state_counts.get(key, 0) for key in STRATEGY_BRAIN_STATES},
        "eligibility_counts": {key: eligibility_counts[key] for key in sorted(eligibility_counts)},
        "thresholds": dict(thresholds),
        "minimum_bucket_sample_count": minimum_bucket_sample_count,
        "promotion_blocker_counts": {
            key: int(value)
            for key, value in sorted(
                mapping_or_empty(paper_b_grade_bucket_readiness.get("blocker_counts")).items()
            )
        },
        "blocker_counts": {
            key: int(value)
            for key, value in sorted(
                mapping_or_empty(paper_b_grade_bucket_readiness.get("blocker_counts")).items()
            )
        },
        "bucket_promotion_readiness": {
            "schema_version": paper_b_grade_bucket_readiness.get("schema_version"),
            "generated_utc": paper_b_grade_bucket_readiness.get("generated_utc"),
            "status": paper_b_grade_bucket_readiness.get("status"),
            "scope": paper_b_grade_bucket_readiness.get("scope"),
            "source_b_grade_closed_outcome_count": paper_b_grade_bucket_readiness.get(
                "source_b_grade_closed_outcome_count"
            ),
            "source_bucket_count": paper_b_grade_bucket_readiness.get("source_bucket_count"),
            "metric_ready_bucket_count": paper_b_grade_bucket_readiness.get(
                "metric_ready_bucket_count"
            ),
            "a_grade_promotable_bucket_count": paper_b_grade_bucket_readiness.get(
                "a_grade_promotable_bucket_count"
            ),
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
            "live_ready_implication": False,
        },
        "b_grade_evidence_fragmentation_status": {
            **dict(evidence_fragmentation),
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
            "live_ready_implication": False,
        } if evidence_fragmentation else {},
        "paper_only_label_collection_priority_buckets": [
            {
                **bucket,
                "counts_as_a_grade_evidence": False,
                "a_grade_promotion_allowed": False,
                "live_ready_implication": False,
            }
            for bucket in label_collection_priority[:STRATEGY_BRAIN_BUCKET_SNAPSHOT_LIMIT]
        ],
        "paper_only_label_collection_priority_bucket_count": len(label_collection_priority),
        "new_a_grade_entries_allowed": bool(active_count > 0 and edge_ready),
        "losing_strategies_lose_execution_eligibility": True,
        "profitable_strategies_gain_capital_only_after_confidence_bounds_pass": True,
        "lifecycle_actions_cannot_be_entry_strategies": True,
        "universal_confidence_threshold_used": False,
        "strategy_summaries": strategy_payloads,
        "buckets": bucket_statuses[:STRATEGY_BRAIN_BUCKET_SNAPSHOT_LIMIT],
        "source_paths": dict(source_paths),
    }


def build_zero_liquidation_status(
    *,
    paper_sizing: Mapping[str, Any],
    realtime_metrics: Mapping[str, Any],
    holdout_metrics: Mapping[str, Any],
    generated_utc: str,
    source_paths: Mapping[str, str],
) -> dict[str, Any]:
    paper_sizing = mapping_or_empty(paper_sizing)
    candidates = all_mapping_rows(paper_sizing.get("candidate_allocations"))
    a_grade_candidates = [row for row in candidates if is_a_grade_candidate(row)]
    blocker_counts: dict[str, int] = {}
    candidate_samples: list[dict[str, Any]] = []
    passed_candidates = 0

    realtime_liquidations = int(realtime_metrics.get("liquidation_event_count") or 0)
    holdout_liquidations = int(holdout_metrics.get("liquidation_event_count") or 0)
    if realtime_liquidations > 0:
        increment_count(blocker_counts, "REALTIME_LIQUIDATION_EVENT_RECORDED")
    if holdout_liquidations > 0:
        increment_count(blocker_counts, "REPLAY_OR_HOLDOUT_LIQUIDATION_EVENT_RECORDED")

    for row in a_grade_candidates:
        stress_status = str(
            first_present(
                row.get("rare_event_stress_status"),
                row.get("stress_test_status"),
                mapping_or_empty(row.get("pre_entry_stress_tests")).get("status"),
                mapping_or_empty(row.get("rare_event_stress_suite")).get("status"),
            )
            or ""
        ).strip().upper()
        complete_stress_status = stress_status in {
            "COMPLETE_RARE_EVENT_STRESS_SUITE",
            "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE",
            "PASSED_RARE_EVENT_STRESS_SUITE",
        }
        if not complete_stress_status:
            increment_count(blocker_counts, "RARE_EVENT_STRESS_STATUS_NOT_COMPLETE")
        missing_scenarios: list[str] = []
        scenario_values: dict[str, float] = {}
        for scenario in RARE_EVENT_STRESS_SCENARIOS:
            value = stress_scenario_value(row, scenario)
            if value is None:
                missing_scenarios.append(scenario)
                increment_count(blocker_counts, f"MISSING_STRESS_SCENARIO_{scenario.upper()}")
            else:
                scenario_values[scenario] = value

        missing_components: list[str] = []
        component_values: dict[str, float] = {}
        for component in RARE_EVENT_BUFFER_COMPONENTS:
            value = stress_component_value(row, component)
            if value is None:
                missing_components.append(component)
                increment_count(blocker_counts, f"MISSING_BUFFER_COMPONENT_{component.upper()}")
            else:
                component_values[component] = value

        liquidation_buffer_bps = finite_float(row.get("liquidation_buffer_bps"))
        if liquidation_buffer_bps is None or liquidation_buffer_bps <= 0.0:
            increment_count(blocker_counts, "MISSING_POSITIVE_LIQUIDATION_BUFFER_BPS")

        modeled_999_adverse_move_bps = max(scenario_values.values()) if scenario_values else None
        required_buffer_bps = None
        if modeled_999_adverse_move_bps is not None and len(component_values) == len(RARE_EVENT_BUFFER_COMPONENTS):
            required_buffer_bps = modeled_999_adverse_move_bps + sum(component_values.values())
            if liquidation_buffer_bps is not None and liquidation_buffer_bps < required_buffer_bps:
                increment_count(blocker_counts, "LIQUIDATION_BUFFER_BELOW_RARE_EVENT_REQUIREMENT")

        martingale_flag = bool(row.get("martingale") or row.get("martingale_enabled"))
        unlimited_grid_flag = bool(row.get("unlimited_grid") or row.get("grid_unbounded"))
        hedge_lock_flag = "HEDGELOCK" in str(
            first_present(row.get("hedge_intent"), row.get("hedge_state"), row.get("strategy"), "")
        ).upper()
        cross_delay_flag = bool(row.get("cross_margin_used_to_delay_liquidation"))
        if martingale_flag:
            increment_count(blocker_counts, "MARTINGALE_NOT_ALLOWED")
        if unlimited_grid_flag:
            increment_count(blocker_counts, "UNLIMITED_GRID_NOT_ALLOWED")
        if hedge_lock_flag:
            increment_count(blocker_counts, "UNBOUNDED_HEDGELOCK_NOT_ALLOWED")
        if cross_delay_flag:
            increment_count(blocker_counts, "CROSS_MARGIN_USED_TO_DELAY_LIQUIDATION_NOT_ALLOWED")

        candidate_passed = (
            not missing_scenarios
            and not missing_components
            and complete_stress_status
            and liquidation_buffer_bps is not None
            and liquidation_buffer_bps > 0.0
            and required_buffer_bps is not None
            and liquidation_buffer_bps >= required_buffer_bps
            and not any((martingale_flag, unlimited_grid_flag, hedge_lock_flag, cross_delay_flag))
        )
        if candidate_passed:
            passed_candidates += 1
        if len(candidate_samples) < ZERO_LIQUIDATION_SAMPLE_LIMIT:
            candidate_samples.append(
                {
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "side": first_present(row.get("side"), row.get("selected_action"), row.get("action")),
                    "paper_opportunity_tier": row.get("paper_opportunity_tier"),
                    "allocator_decision": row.get("allocator_decision"),
                    "recommended_leverage": row.get("recommended_leverage"),
                    "recommended_margin_mode": row.get("recommended_margin_mode"),
                    "liquidation_buffer_bps": liquidation_buffer_bps,
                    "modeled_999_adverse_move_bps": modeled_999_adverse_move_bps,
                    "execution_uncertainty_bps": component_values.get("execution_uncertainty_bps"),
                    "correlation_stress_bps": component_values.get("correlation_stress_bps"),
                    "maintenance_margin_uncertainty_bps": component_values.get(
                        "maintenance_margin_uncertainty_bps"
                    ),
                    "required_liquidation_buffer_bps": required_buffer_bps,
                    "rare_event_stress_status": stress_status or None,
                    "missing_stress_scenarios": missing_scenarios,
                    "missing_buffer_components": missing_components,
                    "scenario_values_bps": scenario_values,
                    "rare_event_stress_passed": candidate_passed,
                    "paper_only": row.get("paper_only"),
                    "places_real_order": row.get("places_real_order"),
                }
            )

    if realtime_liquidations > 0 or holdout_liquidations > 0:
        status = "BLOCKED_LIQUIDATION_EVENT_RECORDED"
    elif not a_grade_candidates:
        status = "BLOCKED_NO_A_GRADE_CANDIDATES_STRESS_VERIFIED"
    elif blocker_counts:
        status = "BLOCKED_RARE_EVENT_STRESS_SUITE_INCOMPLETE"
    else:
        status = "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE"

    return {
        "schema_version": "continuous_edge_guardian_zero_liquidation_status_v1",
        "generated_utc": generated_utc,
        "status": status,
        "paper_only": True,
        "places_real_order": False,
        "live_routeable": False,
        "release_ready": status == "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE",
        "new_a_grade_entries_allowed": status == "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE",
        "accepted_contract": {
            "zero_tolerated_paper_liquidation_events": True,
            "zero_tolerated_replay_liquidation_events": True,
            "automatic_de_risking_before_liquidation_required": True,
            "dynamic_liquidation_buffer_formula": (
                "modeled_99_9pct_adverse_move + execution_uncertainty + "
                "correlation_stress + maintenance_margin_uncertainty"
            ),
            "martingale_allowed": False,
            "unlimited_averaging_allowed": False,
            "unbounded_hedgelock_allowed": False,
            "cross_margin_to_delay_liquidation_allowed": False,
        },
        "required_pre_entry_stress_scenarios": list(RARE_EVENT_STRESS_SCENARIOS),
        "required_buffer_components": list(RARE_EVENT_BUFFER_COMPONENTS),
        "runtime_actions_on_failure": ["reduce_exposure", "close", "hedge_if_expected_shortfall_improves", "halt_entries"],
        "candidate_count": len(candidates),
        "a_grade_candidate_count": len(a_grade_candidates),
        "passed_a_grade_candidate_count": passed_candidates,
        "realtime_liquidation_event_count": realtime_liquidations,
        "replay_or_holdout_liquidation_event_count": holdout_liquidations,
        "blocker_counts": {key: blocker_counts[key] for key in sorted(blocker_counts)},
        "candidate_samples": candidate_samples,
        "candidate_sample_limit": ZERO_LIQUIDATION_SAMPLE_LIMIT,
        "source_paths": dict(source_paths),
    }


def build_capital_allocation_snapshot(
    *,
    paper_sizing: Mapping[str, Any],
    edge_ready: bool,
    source_path: Path,
) -> dict[str, Any]:
    paper_sizing = mapping_or_empty(paper_sizing)
    candidates = all_mapping_rows(paper_sizing.get("candidate_allocations"))
    candidate_count = int(first_present(paper_sizing.get("candidate_allocation_count"), len(candidates)) or 0)
    accepted_count = int(first_present(paper_sizing.get("accepted_allocation_count"), 0) or 0)
    blocked_count = int(first_present(paper_sizing.get("blocked_allocation_count"), 0) or 0)
    allocator_decision_counts = paper_sizing.get("allocator_decision_counts")
    if not isinstance(allocator_decision_counts, Mapping):
        allocator_decision_counts = count_candidate_field(candidates, "allocator_decision")

    original_decision_counts = count_candidate_field(candidates, "original_allocator_decision_before_paper_tier_block")
    paper_tier_counts = count_candidate_field(candidates, "paper_opportunity_tier")
    leverage_counts = count_candidate_field(candidates, "recommended_leverage")
    margin_mode_counts = count_candidate_field(candidates, "recommended_margin_mode")

    equity = finite_float(
        first_present(
            paper_sizing.get("total_equity_usd"),
            paper_sizing.get("equity"),
            first_finite_from_sources(candidates, "equity", "wallet_balance"),
        )
    )
    available_margin = finite_float(
        first_present(
            paper_sizing.get("available_equity_usd"),
            paper_sizing.get("available_margin_usd"),
            paper_sizing.get("available_margin"),
            first_finite_from_sources(candidates, "available_margin", "available_margin_usd"),
        )
    )
    wallet_balance = finite_float(
        first_present(
            paper_sizing.get("wallet_balance"),
            first_finite_from_sources(candidates, "wallet_balance"),
        )
    )
    existing_portfolio_exposure_usd = finite_float(
        first_present(
            paper_sizing.get("total_exposure_usdt"),
            paper_sizing.get("total_exposure_usd"),
            first_finite_from_sources(candidates, "total_exposure_usdt", "total_exposure_usd"),
        )
    )

    allocated_margin_usd = sum_finite_field(candidates, "allocated_margin_usd")
    gross_notional_usd = sum_finite_field(candidates, "gross_notional_usd")
    risk_budget_usd = sum_finite_field(candidates, "risk_budget_usd")
    hedge_budget_usd = sum_finite_field(candidates, "hedge_budget_usd")
    expected_net_pnl_usd = sum_finite_field(candidates, "expected_net_pnl_usd")
    expected_shortfall_usd = sum_finite_field(candidates, "expected_shortfall_usd")

    a_grade_candidates = [
        row for row in candidates
        if str(row.get("paper_opportunity_tier") or "") == A_GRADE_EXECUTION_TIER
    ]
    accepted_a_grade_candidates = [
        row for row in a_grade_candidates
        if str(row.get("allocator_decision") or "").startswith("ALLOW")
        and (finite_float(row.get("allocated_margin_usd")) or 0.0) > 0.0
    ]
    underfunded_a_grade_candidates = [
        row for row in a_grade_candidates
        if str(row.get("original_allocator_decision_before_paper_tier_block") or row.get("allocator_decision") or "").startswith("ALLOW")
        and (
            (finite_float(row.get("allocated_margin_usd")) or 0.0) <= 0.0
            or (finite_float(row.get("gross_notional_usd")) or 0.0) <= 0.0
        )
    ]

    no_edge_count = 0
    below_grade_count = 0
    risk_constrained_count = 0
    allowed_before_tier_block_count = 0
    for row in candidates:
        text = " ".join(
            str(value or "")
            for value in (
                row.get("allocator_decision"),
                row.get("original_allocator_decision_before_paper_tier_block"),
                row.get("allocator_reason"),
                row.get("paper_opportunity_tier"),
                row.get("paper_opportunity_tier_reason"),
                row.get("risk_veto_reason_if_blocked"),
                row.get("final_size_reason"),
            )
        ).upper()
        if "ALLOW_WITH_SIZE" in text and "NON_EXECUTABLE_PAPER_TIER" in text:
            allowed_before_tier_block_count += 1
        has_no_edge = "NO_EDGE" in text or "NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE" in text
        has_below_grade = (
            "LOW_CONFIDENCE" in text
            or "NON_EXECUTABLE_PAPER_TIER" in text
            or "NO_TRADE" in text
            or "BELOW_GRADE" in text
        )
        has_risk_constraint = (
            "SPREAD" in text
            or "SLIPPAGE" in text
            or "RISK" in text
            or "LIQUIDATION" in text
            or "DRAWDOWN" in text
            or "CONCENTRATION" in text
            or "CORRELATION" in text
        )
        if has_no_edge:
            no_edge_count += 1
        elif has_risk_constraint:
            risk_constrained_count += 1
        elif has_below_grade:
            below_grade_count += 1

    denominator = candidate_count if candidate_count > 0 else len(candidates)
    available_idle_capital_usd = None
    if available_margin is not None:
        available_idle_capital_usd = max(available_margin - allocated_margin_usd, 0.0)

    def idle_slice(count: int) -> float | None:
        if available_idle_capital_usd is None or denominator <= 0:
            return None
        return available_idle_capital_usd * (count / denominator)

    idle_capital_allocator_bug_usd = (
        available_idle_capital_usd if underfunded_a_grade_candidates and available_idle_capital_usd is not None else 0.0
    )
    classified_idle = sum(
        value or 0.0
        for value in (
            idle_slice(no_edge_count),
            idle_slice(below_grade_count),
            idle_slice(risk_constrained_count),
            idle_capital_allocator_bug_usd,
        )
    )
    unclassified_idle_capital_usd = None
    if available_idle_capital_usd is not None:
        unclassified_idle_capital_usd = max(available_idle_capital_usd - classified_idle, 0.0)

    if underfunded_a_grade_candidates:
        capital_classification = "ALLOCATOR_UNDERDEPLOYMENT"
    elif allowed_before_tier_block_count > 0:
        capital_classification = "POSITIVE_EDGE_BELOW_A_GRADE_IDLE"
    elif no_edge_count >= max(1, denominator // 2):
        capital_classification = "NO_EDGE_IDLE"
    elif risk_constrained_count > 0:
        capital_classification = "RISK_CONSTRAINED_IDLE"
    else:
        capital_classification = "BELOW_GRADE_IDLE"

    sample_recommendations: list[dict[str, Any]] = []
    for row in candidates[:CAPITAL_RECOMMENDATION_SAMPLE_LIMIT]:
        sample_recommendations.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": first_present(row.get("side"), row.get("selected_action"), row.get("action")),
                "paper_opportunity_tier": row.get("paper_opportunity_tier"),
                "allocator_decision": row.get("allocator_decision"),
                "original_allocator_decision_before_paper_tier_block": row.get(
                    "original_allocator_decision_before_paper_tier_block"
                ),
                "allocator_reason": row.get("allocator_reason"),
                "risk_budget_usd": row.get("risk_budget_usd"),
                "gross_notional_usd": row.get("gross_notional_usd"),
                "allocated_margin_usd": row.get("allocated_margin_usd"),
                "recommended_leverage": row.get("recommended_leverage"),
                "recommended_margin_mode": row.get("recommended_margin_mode"),
                "stop_distance_bps": row.get("stop_distance_bps"),
                "take_profit_plan": first_present(row.get("take_profit_plan"), row.get("take_profit_structure")),
                "liquidation_buffer_bps": row.get("liquidation_buffer_bps"),
                "hedge_budget_usd": row.get("hedge_budget_usd"),
                "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
                "expected_shortfall_usd": row.get("expected_shortfall_usd"),
                "paper_only": row.get("paper_only"),
                "places_real_order": row.get("places_real_order"),
                "leverage_mutation": row.get("leverage_mutation"),
                "margin_mode_mutation": row.get("margin_mode_mutation"),
            }
        )

    capital_utilization_pct = gross_notional_usd / equity if equity and equity > 0 else None
    margin_utilization_pct = allocated_margin_usd / equity if equity and equity > 0 else None
    portfolio_exposure_utilization_pct = (
        existing_portfolio_exposure_usd / equity if equity and equity > 0 and existing_portfolio_exposure_usd is not None else None
    )
    status = (
        "A_GRADE_CAPITAL_READY"
        if edge_ready and accepted_a_grade_candidates
        else "BLOCKED_UNTIL_A_GRADE_EDGE_PROVEN"
        if not edge_ready
        else "BLOCKED_NO_A_GRADE_ALLOCATIONS"
    )
    return {
        "schema_version": "continuous_edge_guardian_capital_allocation_snapshot_v1",
        "generated_utc": paper_sizing.get("generated_utc"),
        "status": status,
        "capital_utilization_classification": capital_classification,
        "paper_only": True,
        "places_real_order": False,
        "live_execution_allowed": False,
        "exchange_leverage_mutation_allowed": False,
        "exchange_margin_mode_mutation_allowed": False,
        "fixed_runtime_notional_removed": bool(paper_sizing.get("fixed_runtime_notional_removed")),
        "paper_sizing_source_path": str(source_path),
        "candidate_allocation_count": candidate_count,
        "accepted_allocation_count": accepted_count,
        "blocked_allocation_count": blocked_count,
        "a_grade_candidate_count": len(a_grade_candidates),
        "accepted_a_grade_candidate_count": len(accepted_a_grade_candidates),
        "underfunded_a_grade_candidate_count": len(underfunded_a_grade_candidates),
        "allowed_before_non_executable_tier_block_count": allowed_before_tier_block_count,
        "allocator_decision_counts": dict(allocator_decision_counts),
        "original_allocator_decision_counts": original_decision_counts,
        "paper_opportunity_tier_counts": paper_tier_counts,
        "recommended_leverage_counts": leverage_counts,
        "recommended_margin_mode_counts": margin_mode_counts,
        "total_equity_usd": equity,
        "wallet_balance_usd": wallet_balance,
        "available_margin_usd": available_margin,
        "existing_portfolio_exposure_usd": existing_portfolio_exposure_usd,
        "current_candidate_allocated_margin_usd": allocated_margin_usd,
        "current_candidate_gross_notional_usd": gross_notional_usd,
        "current_candidate_risk_budget_usd": risk_budget_usd,
        "current_candidate_hedge_budget_usd": hedge_budget_usd,
        "current_candidate_expected_net_pnl_usd": expected_net_pnl_usd,
        "current_candidate_expected_shortfall_usd": expected_shortfall_usd,
        "capital_utilization_pct": capital_utilization_pct,
        "margin_utilization_pct": margin_utilization_pct,
        "portfolio_exposure_utilization_pct": portfolio_exposure_utilization_pct,
        "available_idle_capital_usd": available_idle_capital_usd,
        "idle_capital_no_edge_usd": idle_slice(no_edge_count),
        "idle_capital_below_grade_usd": idle_slice(below_grade_count),
        "idle_capital_risk_constrained_usd": idle_slice(risk_constrained_count),
        "idle_capital_allocator_bug_usd": idle_capital_allocator_bug_usd,
        "idle_capital_unclassified_usd": unclassified_idle_capital_usd,
        "diagnostic_count_basis": {
            "no_edge_candidate_count": no_edge_count,
            "below_grade_candidate_count": below_grade_count,
            "risk_constrained_candidate_count": risk_constrained_count,
            "denominator_candidate_count": denominator,
        },
        "leverage_and_margin_recommendation": {
            "status": status,
            "paper_only": True,
            "live_exchange_mutation_allowed": False,
            "select_lowest_safe_leverage_required": True,
            "recommended_leverage_counts": leverage_counts,
            "recommended_margin_mode_counts": margin_mode_counts,
            "sample_recommendations": sample_recommendations,
            "sample_limit": CAPITAL_RECOMMENDATION_SAMPLE_LIMIT,
        },
    }


def hedge_candidate_is_active(row: Mapping[str, Any]) -> bool:
    hedge_budget = finite_float(aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_budget"))
    if row.get("hedge_enabled") is True or (hedge_budget is not None and hedge_budget > 0.0):
        return True
    return any(
        aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, field) not in (None, "")
        for field in (
            "hedge_parent_id",
            "hedge_child_id",
            "hedge_intent",
            "hedge_ratio",
        )
    )


def hedge_cost_usd(row: Mapping[str, Any]) -> float:
    explicit_cost = finite_float(row.get("hedge_cost_usd"))
    if explicit_cost is not None:
        return abs(explicit_cost)
    total = 0.0
    for field in (
        "hedge_cost_usd",
        "hedge_fees_usd",
        "hedge_spread_usd",
        "hedge_slippage_usd",
        "hedge_funding_usd",
        "hedge_basis_risk_usd",
        "hedge_model_uncertainty_usd",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
    ):
        value = finite_float(row.get(field))
        if value is not None:
            total += abs(value)
    return total


def hedge_group_id(row: Mapping[str, Any], fallback_index: int) -> str:
    return str(
        first_present(
            row.get("economic_trade_id"),
            row.get("hedge_parent_id"),
            row.get("parent_trade_id"),
            row.get("position_id"),
            row.get("trade_id"),
            f"hedge-row-{fallback_index}",
        )
    )


def build_hedge_engine_status(
    *,
    paper_sizing: Mapping[str, Any],
    feedback_rows: list[dict[str, Any]],
    generated_utc: str,
    source_paths: Mapping[str, str],
) -> dict[str, Any]:
    paper_sizing = mapping_or_empty(paper_sizing)
    candidates = all_mapping_rows(paper_sizing.get("candidate_allocations"))
    active_candidates = [row for row in candidates if hedge_candidate_is_active(row)]
    blocker_counts: dict[str, int] = {}
    accepted_candidates: list[dict[str, Any]] = []
    candidate_samples: list[dict[str, Any]] = []
    required_admission_fields = [
        field for field in HEDGE_REQUIRED_FIELD_ALIASES
        if field != "pair_net_pnl"
    ]

    for row in active_candidates:
        missing_fields = [
            field for field in required_admission_fields
            if aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, field) in (None, "")
        ]
        for field in missing_fields:
            increment_count(blocker_counts, f"MISSING_{field.upper()}")

        expected_shortfall_before = finite_float(
            aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "expected_shortfall_before")
        )
        expected_shortfall_after = finite_float(
            aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "expected_shortfall_after")
        )
        cost = hedge_cost_usd(row)
        shortfall_reduction = None
        if expected_shortfall_before is not None and expected_shortfall_after is not None:
            shortfall_reduction = expected_shortfall_before - expected_shortfall_after
            if shortfall_reduction <= cost:
                increment_count(blocker_counts, "EXPECTED_SHORTFALL_REDUCTION_NOT_GREATER_THAN_COSTS")
        else:
            increment_count(blocker_counts, "EXPECTED_SHORTFALL_REDUCTION_UNVERIFIED")

        maximum_duration = aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "maximum_duration")
        unwind_plan = aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "unwind_plan")
        if maximum_duration in (None, "") or unwind_plan in (None, ""):
            increment_count(blocker_counts, "HEDGE_EXIT_PLAN_NOT_BOUNDED")
        if "HEDGELOCK" in str(first_present(row.get("hedge_intent"), row.get("strategy"), row.get("strategy_id"), "")).upper():
            increment_count(blocker_counts, "INDEFINITE_HEDGELOCK_NOT_ALLOWED")

        candidate_ready = (
            not missing_fields
            and shortfall_reduction is not None
            and shortfall_reduction > cost
            and maximum_duration not in (None, "")
            and unwind_plan not in (None, "")
        )
        if candidate_ready:
            accepted_candidates.append(dict(row))
        if len(candidate_samples) < HEDGE_ENGINE_SAMPLE_LIMIT:
            candidate_samples.append(
                {
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "side": first_present(row.get("side"), row.get("selected_action"), row.get("action")),
                    "paper_opportunity_tier": row.get("paper_opportunity_tier"),
                    "hedge_parent_id": aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_parent_id"),
                    "hedge_child_id": aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_child_id"),
                    "hedge_intent": aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_intent"),
                    "hedge_ratio": aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_ratio"),
                    "hedge_budget": aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_budget"),
                    "expected_shortfall_before": expected_shortfall_before,
                    "expected_shortfall_after": expected_shortfall_after,
                    "shortfall_reduction_usd": shortfall_reduction,
                    "hedge_cost_usd": cost,
                    "maximum_duration": maximum_duration,
                    "unwind_plan": unwind_plan,
                    "missing_required_fields": missing_fields,
                    "accepted_by_bounded_hedge_contract": candidate_ready,
                }
            )

    hedged_outcome_rows = [
        row for row in feedback_rows
        if row.get("hedge_parent_id") not in (None, "")
        or row.get("hedge_child_id") not in (None, "")
        or row.get("hedge_intent") not in (None, "")
        or row.get("pair_net_pnl") not in (None, "")
        or row.get("pair_net_pnl_usd") not in (None, "")
    ]
    hedged_groups: dict[str, list[dict[str, Any]]] = {}
    outcome_missing_pair_net_pnl = 0
    for index, row in enumerate(hedged_outcome_rows):
        hedged_groups.setdefault(hedge_group_id(row, index), []).append(row)
        if aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "pair_net_pnl") in (None, ""):
            outcome_missing_pair_net_pnl += 1

    if not active_candidates:
        status = "NO_ACTIVE_HEDGES_SELECTED"
    elif blocker_counts:
        status = "BLOCKED_HEDGE_CONTRACT_INCOMPLETE"
    else:
        status = "PASSED_BOUNDED_HEDGE_ADMISSION_CONTRACT"

    return {
        "schema_version": "continuous_edge_guardian_hedge_engine_status_v1",
        "generated_utc": generated_utc,
        "status": status,
        "paper_only": True,
        "places_real_order": False,
        "live_routeable": False,
        "counts_as_a_grade_evidence": False,
        "release_ready": status == "PASSED_BOUNDED_HEDGE_ADMISSION_CONTRACT" and bool(hedged_groups),
        "new_hedges_allowed": status == "PASSED_BOUNDED_HEDGE_ADMISSION_CONTRACT",
        "required_admission_contract": {
            "expected_shortfall_reduction_must_exceed_costs": True,
            "bounded_exit_plan_required": True,
            "indefinite_hedgelock_allowed": False,
            "parent_and_hedge_legs_count_as_one_economic_outcome": True,
            "required_fields": list(HEDGE_REQUIRED_FIELD_ALIASES),
        },
        "candidate_count": len(candidates),
        "active_hedge_candidate_count": len(active_candidates),
        "accepted_bounded_hedge_candidate_count": len(accepted_candidates),
        "hedge_enabled_candidate_count": sum(1 for row in candidates if row.get("hedge_enabled") is True),
        "positive_hedge_budget_candidate_count": sum(
            1 for row in candidates
            if (finite_float(aliased_field(row, HEDGE_REQUIRED_FIELD_ALIASES, "hedge_budget")) or 0.0) > 0.0
        ),
        "blocker_counts": {key: blocker_counts[key] for key in sorted(blocker_counts)},
        "candidate_samples": candidate_samples,
        "candidate_sample_limit": HEDGE_ENGINE_SAMPLE_LIMIT,
        "hedged_feedback_row_count": len(hedged_outcome_rows),
        "hedged_economic_outcome_group_count": len(hedged_groups),
        "hedged_outcome_rows_missing_pair_net_pnl": outcome_missing_pair_net_pnl,
        "hedged_structures_counted_as_single_outcome": True,
        "source_paths": dict(source_paths),
    }


def build_anti_metric_gaming_status(rows: list[dict[str, Any]], metrics: Mapping[str, Any], generated_utc: str) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    for index, row in enumerate(rows):
        trade_id = economic_trade_id(row, index)
        seen_ids[trade_id] = seen_ids.get(trade_id, 0) + 1
        if is_no_trade(row) and outcome_is_win(row, realized_pnl_usd(row), realized_pnl_bps(row)):
            violations.append({"reason": "NO_TRADE_COUNTED_AS_WIN_ATTEMPT", "economic_trade_id": trade_id})
        if row.get("candidate_selected_after_outcome") is True or row.get("post_outcome_candidate_selection") is True:
            violations.append({"reason": "POST_OUTCOME_CANDIDATE_SELECTION", "economic_trade_id": trade_id})
        if row.get("future_labels_used_as_features") is True:
            violations.append({"reason": "FUTURE_LABEL_USED_AS_DECISION_FEATURE", "economic_trade_id": trade_id})
        if row.get("evidence_window_reset_after_loss") is True:
            violations.append({"reason": "EVIDENCE_WINDOW_RESET_AFTER_LOSS", "economic_trade_id": trade_id})
        if row.get("bid_ask_spread_bps_fallback") is True or (
            finite_float(row.get("actual_observed_spread_entry_bps")) == 2.0
            and "FALLBACK" in str(row.get("actual_observed_spread_source") or "").upper()
        ):
            violations.append({"reason": "FALLBACK_COST_REPORTED_AS_MARKET_OBSERVED", "economic_trade_id": trade_id})
        for reason in pit_violations_for_row(row):
            if reason in {"AVAILABLE_AT_AFTER_DECISION_TIME", "FEATURE_CUTOFF_AFTER_DECISION_TIME"}:
                violations.append({"reason": "FUTURE_LEAKAGE", "detail": reason, "economic_trade_id": trade_id})

    duplicate_hedge_groups = {
        trade_id: count
        for trade_id, count in seen_ids.items()
        if count > 1
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "PASSED" if not violations else "BLOCKED",
        "paper_and_replay_only": True,
        "no_trade_rows_excluded_from_win_count": metrics.get("no_trade_rows_excluded_from_win_count", 0),
        "hedged_structures_counted_as_single_outcome": metrics.get("hedged_structures_counted_as_single_outcome", 0),
        "duplicate_economic_trade_groups_seen": duplicate_hedge_groups,
        "violations": violations[:100],
        "fail_rules": [
            "losses_removed_from_evidence",
            "hedge_legs_counted_separately",
            "partial_exits_counted_as_separate_wins",
            "NO_TRADE_counted_as_win",
            "thresholds_adjusted_after_holdout_outcomes",
            "replay_selector_tuned_on_own_evaluation_window",
            "symbol_universe_shrunk_without_dynamic_eligibility_evidence",
            "evidence_window_reset_after_losses",
            "future_leakage",
            "fallback_costs_reported_as_market_observed",
            "paper_and_live_pre_submit_use_different_decision_logic",
        ],
    }


def build_trajectory_status(
    *,
    generated_utc: str,
    target_multiple: float = 1000.0,
    horizon_years: float = 5.0,
    dependency_ready: bool = False,
) -> dict[str, Any]:
    days = horizon_years * 365.0
    months = horizon_years * 12.0
    required_daily = target_multiple ** (1.0 / days) - 1.0
    required_monthly = target_multiple ** (1.0 / months) - 1.0
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "target_equity_multiple": target_multiple,
        "target_horizon_years": horizon_years,
        "required_daily_geometric_return": required_daily,
        "required_monthly_geometric_return": required_monthly,
        "actual_1d_return": None,
        "actual_7d_return": None,
        "actual_30d_return": None,
        "actual_90d_return": None,
        "lower_confidence_bound_growth_rate": None,
        "drawdown_adjusted_growth_rate": None,
        "days_ahead_or_behind_target": None,
        "required_capital": None,
        "required_edge": None,
        "status": "ON_1000X_TRAJECTORY" if dependency_ready else "INSUFFICIENT_EVIDENCE",
        "leverage_increase_allowed_because_behind": False,
        "guaranteed_profit_claim": False,
    }


def fingerprint_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def phase_ledger(*, generated_utc: str, blocked: bool) -> dict[str, Any]:
    phases: dict[str, Any] = {}
    for index, (phase_id, title) in enumerate(PHASES.items()):
        if index <= 2:
            status = "RUNNING"
        else:
            status = "BLOCKED" if blocked else "RUNNING"
        phases[phase_id] = {
            "title": title,
            "status": status,
            "status_allowed_values": sorted(VALID_PHASE_STATES),
            "pass_from_synthetic_tests_alone_allowed": False,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "phases": phases,
    }


def build_guardian_payloads(
    *,
    paths: ContinuousEdgeGuardianPaths,
    holdout_rows: list[dict[str, Any]],
    realtime_rows: list[dict[str, Any]],
    holdout_acquisition_status: Mapping[str, Any] | None = None,
    realtime_acquisition_status: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
    started_utc: str | None = None,
) -> dict[str, Any]:
    generated_utc = generated_utc or utc_now()
    started_utc = started_utc or generated_utc
    trainer_learning = read_json(paths.trainer_dir / "online_learning_global_readiness_override.json", {})
    trainer_quality = read_json(paths.trainer_dir / "trainer_accuracy_calibration_runtime_status.json", {})
    trainer_feedback_payload = read_json(paths.trainer_feedback_outcomes_path, {})
    trainer_feedback_rows = all_mapping_rows(mapping_or_empty(trainer_feedback_payload).get("trainer_feedback_outcomes"))
    paper_sizing = read_json(paths.paper_adaptive_sizing_path, {})
    paper_b_grade_quality = read_json(paths.paper_b_grade_model_quality_path, {})
    if not isinstance(paper_b_grade_quality, Mapping) or not paper_b_grade_quality:
        paper_b_grade_quality = mapping_or_empty(
            mapping_or_empty(trainer_feedback_payload).get("paper_b_grade_model_quality_status")
        )
    paper_b_grade_bucket_readiness = read_json(paths.paper_b_grade_bucket_promotion_readiness_path, {})
    if not isinstance(paper_b_grade_bucket_readiness, Mapping) or not paper_b_grade_bucket_readiness:
        paper_b_grade_bucket_readiness = mapping_or_empty(
            mapping_or_empty(trainer_feedback_payload).get("paper_b_grade_bucket_promotion_readiness_status")
        )
    paper_shadow_outcome_metrics = read_json(paths.paper_shadow_outcome_metrics_path, {})
    holdout_acquisition_status = dict(holdout_acquisition_status or {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "NOT_RUN_BUILD_PAYLOADS_DIRECT_CALL",
        "accepted_row_count": len(holdout_rows),
        "rejected_row_count": 0,
        "rows_rejected_by_reason": {},
        "blockers": [],
    })
    realtime_acquisition_status = dict(realtime_acquisition_status or {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "NOT_RUN_BUILD_PAYLOADS_DIRECT_CALL",
        "admitted_row_count": len(realtime_rows),
        "admitted_economic_outcome_count": compute_economic_metrics(realtime_rows)["closed_economic_trade_count"],
        "rows_rejected_by_reason": {},
    })
    holdout_metrics = apply_holdout_prediction_coverage(
        compute_economic_metrics(holdout_rows),
        holdout_acquisition_status,
    )
    phase3_prediction_coverage = phase3_holdout_prediction_coverage_snapshot(
        holdout_metrics
    )
    realtime_metrics = compute_economic_metrics(realtime_rows)
    holdout_failures = gate_failures(holdout_metrics, realtime=False)
    realtime_failures = gate_failures(realtime_metrics, realtime=True)
    all_failures = holdout_failures + realtime_failures
    guardian_status = guardian_status_from_failures(realtime_metrics, realtime_failures)
    edge_ready = not holdout_failures and not realtime_failures
    trajectory = build_trajectory_status(generated_utc=generated_utc, dependency_ready=edge_ready)
    capital_allocation = build_capital_allocation_snapshot(
        paper_sizing=paper_sizing,
        edge_ready=edge_ready,
        source_path=paths.paper_adaptive_sizing_path,
    )
    hedge_engine = build_hedge_engine_status(
        paper_sizing=paper_sizing,
        feedback_rows=trainer_feedback_rows,
        generated_utc=generated_utc,
        source_paths={
            "paper_adaptive_sizing_runtime_status": str(paths.paper_adaptive_sizing_path),
            "trainer_feedback_outcomes": str(paths.trainer_feedback_outcomes_path),
        },
    )
    strategy_brain = build_strategy_brain_status(
        paper_b_grade_quality=paper_b_grade_quality,
        paper_b_grade_bucket_readiness=paper_b_grade_bucket_readiness,
        feedback_rows=trainer_feedback_rows,
        edge_ready=edge_ready,
        generated_utc=generated_utc,
        source_paths={
            "paper_b_grade_model_quality_status": str(paths.paper_b_grade_model_quality_path),
            "paper_b_grade_bucket_promotion_readiness_status": str(
                paths.paper_b_grade_bucket_promotion_readiness_path
            ),
            "trainer_feedback_outcomes": str(paths.trainer_feedback_outcomes_path),
        },
    )
    zero_liquidation = build_zero_liquidation_status(
        paper_sizing=paper_sizing,
        realtime_metrics=realtime_metrics,
        holdout_metrics=holdout_metrics,
        generated_utc=generated_utc,
        source_paths={
            "paper_adaptive_sizing_runtime_status": str(paths.paper_adaptive_sizing_path),
            "realtime_a_grade_economic_outcomes": str(paths.realtime_rows_path),
            "untouched_holdout_rows": str(paths.holdout_rows_path),
        },
    )
    hedge_engine_blocked = hedge_engine["status"] == "BLOCKED_HEDGE_CONTRACT_INCOMPLETE"
    strategy_brain_ready = strategy_brain["status"] == "ACTIVE_A_GRADE_STRATEGY_BRAIN"
    zero_liquidation_ready = zero_liquidation["status"] == "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE"
    execution_ready = edge_ready and not hedge_engine_blocked and strategy_brain_ready and zero_liquidation_ready

    gate = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": (
            "A_GRADE_HALTED_TAIL_RISK"
            if edge_ready and hedge_engine_blocked
            else "A_GRADE_HALTED_LIQUIDATION_RISK"
            if edge_ready and not zero_liquidation_ready
            else "A_GRADE_HALTED_PERFORMANCE"
            if edge_ready and not strategy_brain_ready
            else guardian_status
        ),
        "a_grade_new_entries_allowed": execution_ready,
        "allowed_runtime_actions": ["reduce", "close", "emergency_de_risk"],
        "new_candidate_tier_override": None if execution_ready else "SHADOW_ONLY",
        "block_all_new_a_grade_entries": not execution_ready,
        "preserve_current_exits_and_emergency_controls": True,
        "paper_only": True,
        "live_path_changed": False,
        "places_real_order": False,
        "failure_reasons": [
            *all_failures,
            *(
                [{
                    "reason": "HEDGE_ENGINE_CONTRACT_BLOCKED",
                    "observed": hedge_engine["status"],
                    "required": "PASSED_BOUNDED_HEDGE_ADMISSION_CONTRACT_OR_NO_ACTIVE_HEDGES",
                    "blocker_counts": hedge_engine["blocker_counts"],
                    "active_hedge_candidate_count": hedge_engine["active_hedge_candidate_count"],
                }]
                if hedge_engine_blocked else []
            ),
            *(
                [{
                    "reason": "ADAPTIVE_STRATEGY_BRAIN_BLOCKED",
                    "observed": strategy_brain["status"],
                    "required": "ACTIVE_A_GRADE_STRATEGY_BRAIN",
                    "state_counts": strategy_brain["state_counts"],
                    "eligibility_counts": strategy_brain["eligibility_counts"],
                }]
                if not strategy_brain_ready else []
            ),
            *(
                [{
                    "reason": "ZERO_LIQUIDATION_STRESS_SUITE_BLOCKED",
                    "observed": zero_liquidation["status"],
                    "required": "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE",
                    "blocker_counts": zero_liquidation["blocker_counts"],
                    "a_grade_candidate_count": zero_liquidation["a_grade_candidate_count"],
                    "passed_a_grade_candidate_count": zero_liquidation["passed_a_grade_candidate_count"],
                }]
                if not zero_liquidation_ready else []
            ),
        ],
    }
    effective_guardian_status = gate["status"]
    readiness = build_readiness_truth(
        trainer_learning=trainer_learning,
        realtime_failures=realtime_failures,
        holdout_failures=holdout_failures,
        generated_utc=generated_utc,
    )
    if hedge_engine_blocked:
        readiness["A_GRADE_EXECUTION_READY"] = False
        readiness["readiness_invariant"]["a_grade_execution_ready_requires_bounded_hedge_contract"] = True
    readiness["ZERO_LIQUIDATION_READY"] = zero_liquidation_ready
    if not zero_liquidation_ready:
        readiness["A_GRADE_EXECUTION_READY"] = False
        readiness["readiness_invariant"]["a_grade_execution_ready_requires_zero_liquidation_stress_suite"] = True
    readiness["trainer_quality_snapshot"] = build_model_quality_snapshot(
        trainer_quality=trainer_quality,
        paper_b_grade_quality=paper_b_grade_quality,
        paper_b_grade_bucket_readiness=paper_b_grade_bucket_readiness,
        paper_shadow_outcome_metrics=paper_shadow_outcome_metrics,
        source_paths={
            "trainer_accuracy_calibration_runtime_status": str(
                paths.trainer_dir / "trainer_accuracy_calibration_runtime_status.json"
            ),
            "paper_b_grade_model_quality_status": str(paths.paper_b_grade_model_quality_path),
            "paper_b_grade_bucket_promotion_readiness_status": str(
                paths.paper_b_grade_bucket_promotion_readiness_path
            ),
            "paper_shadow_outcome_metrics": str(paths.paper_shadow_outcome_metrics_path),
            "trainer_feedback_outcomes": str(paths.trainer_feedback_outcomes_path),
        },
    )
    contract = build_acceptance_contract()
    anti_gaming = build_anti_metric_gaming_status(realtime_rows + holdout_rows, realtime_metrics, generated_utc)
    frozen_fingerprint_source = {
        "acceptance_contract_hash": fingerprint_payload(contract),
        "selector_policy": "continuous_guardian_requires_pre_outcome_selection",
        "paper_replay_only": True,
    }
    frozen_policy_fingerprint = fingerprint_payload(frozen_fingerprint_source)

    blockers = [
        *(
            [{
                "reason": "HOLDOUT_EVIDENCE_ACQUISITION_BLOCKED",
                "observed": holdout_acquisition_status.get("status"),
                "required": "PASSED",
                "rows_rejected_by_reason": holdout_acquisition_status.get("rows_rejected_by_reason"),
                "source_statuses": holdout_acquisition_status.get("source_statuses"),
                "blockers": holdout_acquisition_status.get("blockers"),
            }]
            if holdout_acquisition_status.get("status") != "PASSED" else []
        ),
        *holdout_failures,
        *realtime_failures,
        *(
            [{
                "reason": "REALTIME_A_GRADE_EVIDENCE_ACQUISITION_BLOCKED",
                "observed": realtime_acquisition_status.get("status"),
                "required": "PASSED",
                "rows_rejected_by_reason": realtime_acquisition_status.get("rows_rejected_by_reason"),
            }]
            if realtime_acquisition_status.get("status") != "PASSED" else []
        ),
        *(
            [{
                "reason": "HEDGE_ENGINE_CONTRACT_BLOCKED",
                "observed": hedge_engine["status"],
                "required": "PASSED_BOUNDED_HEDGE_ADMISSION_CONTRACT_OR_NO_ACTIVE_HEDGES",
                "blocker_counts": hedge_engine["blocker_counts"],
                "active_hedge_candidate_count": hedge_engine["active_hedge_candidate_count"],
            }]
            if hedge_engine_blocked else []
        ),
        *(
            [{
                "reason": "ADAPTIVE_STRATEGY_BRAIN_BLOCKED",
                "observed": strategy_brain["status"],
                "required": "ACTIVE_A_GRADE_STRATEGY_BRAIN",
                "state_counts": strategy_brain["state_counts"],
                "eligibility_counts": strategy_brain["eligibility_counts"],
            }]
            if strategy_brain["status"] != "ACTIVE_A_GRADE_STRATEGY_BRAIN" else []
        ),
        *(
            [{
                "reason": "ZERO_LIQUIDATION_STRESS_SUITE_BLOCKED",
                "observed": zero_liquidation["status"],
                "required": "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE",
                "blocker_counts": zero_liquidation["blocker_counts"],
                "a_grade_candidate_count": zero_liquidation["a_grade_candidate_count"],
                "passed_a_grade_candidate_count": zero_liquidation["passed_a_grade_candidate_count"],
            }]
            if not zero_liquidation_ready else []
        ),
        *(
            [{"reason": "ANTI_METRIC_GAMING_STATUS_BLOCKED", "observed": anti_gaming["status"], "required": "PASSED"}]
            if anti_gaming["status"] != "PASSED" else []
        ),
        {"reason": "1000X_TRAJECTORY_NOT_PROVEN", "observed": trajectory["status"], "required": "ON_1000X_TRAJECTORY"},
    ]
    go_no_go = READY_MARKER if execution_ready and anti_gaming["status"] == "PASSED" and trajectory["status"] == "ON_1000X_TRAJECTORY" else BLOCKED_MARKER

    status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "overall_status": "READY" if go_no_go == READY_MARKER else "BLOCKED",
        "go_no_go": go_no_go,
        "guardian_status": effective_guardian_status,
        "current_truth": {
            "trainer_learning_can_be_active_without_execution_readiness": True,
            "website_must_show": "WEIGHTS_UPDATING" if readiness["WEIGHTS_UPDATING"] else "INFERENCE_ONLY",
            "a_grade_execution_ready": execution_ready,
            "live_ready": False,
        },
        "untouched_holdout_metrics": holdout_metrics,
        "phase3_holdout_prediction_coverage": phase3_prediction_coverage,
        "untouched_holdout_failures": holdout_failures,
        "realtime_a_grade_metrics": realtime_metrics,
        "realtime_a_grade_failures": realtime_failures,
        "a_grade_execution_gate": gate,
        "readiness_truth": readiness,
        "frozen_policy_fingerprint": frozen_policy_fingerprint,
        "frozen_policy_fingerprint_source": frozen_fingerprint_source,
        "anti_metric_gaming_status": anti_gaming,
        "holdout_evidence_acquisition_status": holdout_acquisition_status,
        "realtime_a_grade_evidence_acquisition_status": realtime_acquisition_status,
        "capital_allocation_status": capital_allocation,
        "hedge_engine_status": hedge_engine,
        "strategy_brain_status": strategy_brain,
        "zero_liquidation_status": zero_liquidation,
        "trajectory_status": trajectory,
        "non_negotiable_safety": {
            "real_orders_allowed": False,
            "test_orders_allowed": False,
            "exchange_order_cancel_modify_allowed": False,
            "exchange_leverage_mutation_allowed": False,
            "exchange_margin_mode_mutation_allowed": False,
            "old_redis_writes_allowed": False,
            "redis_trim_allowed": False,
            "fixed_runtime_sizing_allowed": False,
            "fixed_static_leverage_policy_allowed": False,
            "martingale_allowed": False,
            "guaranteed_profit_or_1000x_claim_allowed": False,
        },
    }

    payloads = {
        "GOAL_LOCK.json": build_goal_lock(started_utc),
        "PHASE_LEDGER.json": phase_ledger(generated_utc=generated_utc, blocked=go_no_go != READY_MARKER),
        "FINDING_BURNDOWN.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "open_findings": blockers,
            "closed_findings": [],
        },
        "VALIDATION_LEDGER.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "required_validation": {
                "full_backend_test_suite": "NOT_RUN",
                "focused_guardian_tests": "NOT_RUN",
                "frontend_typecheck": "NOT_RUN",
                "frontend_build": "NOT_RUN",
                "local_route_crawl": "NOT_RUN",
                "production_semantic_crawl": "NOT_RUN",
                "point_in_time_leakage_scan": "NOT_RUN",
                "checkpoint_mutation_reload_proof": "DEPENDENCY_ALREADY_PUBLISHED_NOT_RELEASE_SUFFICIENT",
                "paper_live_pre_submit_parity": "NOT_RUN",
                "rare_event_stress_suite": zero_liquidation["status"],
                "accounting_reconciliation": "BLOCKED_INSUFFICIENT_REALTIME_EVIDENCE",
                "old_redis_scan": "NOT_RUN",
                "exchange_mutation_scan": "NOT_RUN",
                "raw_secret_scan": "NOT_RUN",
                "fixed_sizing_scan": "NOT_RUN",
                "martingale_grid_scan": "NOT_RUN",
                "metric_gaming_scan": anti_gaming["status"],
            },
        },
        "CURRENT_BLOCKERS.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "goal_status": "BLOCKED" if go_no_go == BLOCKED_MARKER else "READY",
            "blockers": blockers,
        },
        "EVIDENCE_MANIFEST.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "required_goal_files": list(REQUIRED_GOAL_FILES),
            "published_artifacts": [
                "readiness_truth_override.json",
                "a_grade_90p_acceptance_contract.json",
                "continuous_edge_guardian_status.json",
                "a_grade_execution_gate.json",
                "untouched_holdout_performance.json",
                "untouched_holdout_evidence_acquisition_status.json",
                "untouched_holdout_rows.jsonl",
                "untouched_holdout_hash_chain.json",
                "realtime_a_grade_economic_outcomes.jsonl",
                "realtime_a_grade_performance_status.json",
                "realtime_a_grade_evidence_acquisition_status.json",
                "anti_metric_gaming_status.json",
                "capital_allocation_status.json",
                "hedge_engine_status.json",
                "strategy_brain_status.json",
                "zero_liquidation_status.json",
                "one_thousand_x_trajectory_status.json",
            ],
            "holdout_rows_source": str(paths.holdout_rows_path),
            "holdout_acquisition_sources": {
                "accepted_rows": str(paths.holdout_rows_path),
                "rejected_rows": str(paths.holdout_rejected_path),
                "manifest": str(paths.holdout_manifest_path),
                "window_registry": str(paths.holdout_window_registry_path),
                "window_candidate_audit": str(paths.holdout_window_candidate_audit_path),
            },
            "realtime_rows_source": str(paths.realtime_rows_path),
            "realtime_acquisition_sources": {
                "existing_reverify_rows": str(paths.realtime_rows_path),
                "paper_candidate_snapshots": [
                    str(paths.paper_adaptive_sizing_path),
                    str(paths.paper_live_status_path),
                ],
                "closed_feedback_outcomes": str(paths.trainer_feedback_outcomes_path),
            },
            "model_quality_sources": readiness["trainer_quality_snapshot"]["source_paths"],
            "capital_allocation_sources": {
                "paper_adaptive_sizing_runtime_status": str(paths.paper_adaptive_sizing_path),
            },
            "hedge_engine_sources": hedge_engine["source_paths"],
            "strategy_brain_sources": strategy_brain["source_paths"],
            "zero_liquidation_sources": zero_liquidation["source_paths"],
            "guardian_redis_keys": [STATUS_REDIS_KEY, A_GRADE_EXECUTION_GATE_REDIS_KEY],
            "old_redis_writes": False,
        },
        "GO_NO_GO.md": go_no_go,
        "COMMANDS_RUN.md": (
            "# Commands Run\n\n"
            "- Generated by `python -m v2.backend.app.cli.v2_continuous_edge_guardian` when the guardian runs.\n"
            "- Codex shell command history is reported in the final response for this task.\n"
        ),
        "FILES_CHANGED.md": (
            "# Files Changed\n\n"
            "Generated guardian files are listed in `EVIDENCE_MANIFEST.json`. Code changes are reported by Codex.\n"
        ),
        "readiness_truth_override.json": readiness,
        "a_grade_90p_acceptance_contract.json": contract,
        "continuous_edge_guardian_status.json": status,
        "a_grade_execution_gate.json": gate,
        "untouched_holdout_performance.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "status": "PASSED" if not holdout_failures else "BLOCKED",
            "frozen_policy_fingerprint": frozen_policy_fingerprint,
            "candidate_selection_before_outcome_labels": True,
            "phase3_holdout_prediction_coverage": phase3_prediction_coverage,
            "holdout_prediction_coverage_status": (
                holdout_metrics.get("holdout_prediction_coverage_status")
            ),
            "point_in_time_valid_prediction_count": (
                phase3_prediction_coverage["point_in_time_valid_prediction_count"]
            ),
            "holdout_prediction_coverage_counts_as_a_grade_evidence": False,
            "holdout_prediction_coverage_counts_no_trade_as_win": False,
            "metrics": holdout_metrics,
            "failures": holdout_failures,
            "evidence_acquisition_status": holdout_acquisition_status,
        },
        "untouched_holdout_evidence_acquisition_status.json": holdout_acquisition_status,
        "untouched_holdout_hash_chain.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "frozen_policy_fingerprint": frozen_policy_fingerprint,
            "row_count": len(holdout_rows),
            "hash_chain_tip": hash_rows(holdout_rows),
        },
        "realtime_a_grade_performance_status.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "status": "PASSED" if not realtime_failures else "BLOCKED",
            "guardian_status": effective_guardian_status,
            "metrics": realtime_metrics,
            "failures": realtime_failures,
            "evidence_acquisition_status": realtime_acquisition_status,
        },
        "realtime_a_grade_evidence_acquisition_status.json": realtime_acquisition_status,
        "anti_metric_gaming_status.json": anti_gaming,
        "capital_allocation_status.json": capital_allocation,
        "hedge_engine_status.json": hedge_engine,
        "strategy_brain_status.json": strategy_brain,
        "zero_liquidation_status.json": zero_liquidation,
        "one_thousand_x_trajectory_status.json": trajectory,
        "operator_dashboard_payload.json": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated_utc,
            "goal_id": GOAL_ID,
            "overall_status": status["overall_status"],
            "guardian_status": effective_guardian_status,
            "trainer_learning_status": readiness["online_learning_status"],
            "trusted_rows": trainer_learning.get("trusted_rows_loaded"),
            "optimizer_steps": first_present(
                trainer_learning.get("optimizer_steps_total"),
                trainer_learning.get("optimizer_steps_last_hour"),
            ),
            "model_quality": readiness["trainer_quality_snapshot"],
            "a_grade_gate_state": effective_guardian_status,
            "untouched_holdout_evidence_acquisition": holdout_acquisition_status,
            "phase3_holdout_prediction_coverage": phase3_prediction_coverage,
            "realtime_a_grade_evidence_acquisition": realtime_acquisition_status,
            "rolling_100_trade_win_rate": realtime_metrics["rolling_100_trade_win_rate"],
            "rolling_300_trade_win_rate": realtime_metrics["rolling_300_trade_win_rate"],
            "rolling_1000_trade_win_rate": realtime_metrics["rolling_1000_trade_win_rate"],
            "expectancy_bps": realtime_metrics["after_cost_expectancy_bps"],
            "profit_factor": realtime_metrics["profit_factor"],
            "drawdown": realtime_metrics["maximum_drawdown"],
            "tail_risk": realtime_metrics["worst_1_percent_loss_bps"],
            "liquidation_risk": realtime_metrics["liquidation_event_count"],
            "capital_utilization": capital_allocation["capital_utilization_pct"],
            "capital_utilization_diagnostics": capital_allocation,
            "leverage_and_margin_recommendation": capital_allocation["leverage_and_margin_recommendation"],
            "leverage_and_margin_recommendation_status": capital_allocation[
                "leverage_and_margin_recommendation"
            ]["status"],
            "hedge_engine_status": hedge_engine,
            "hedge_engine_state": hedge_engine["status"],
            "strategy_brain_status": strategy_brain,
            "adaptive_strategy_brain_state": strategy_brain["status"],
            "zero_liquidation_status": zero_liquidation,
            "zero_liquidation_state": zero_liquidation["status"],
            "rare_event_stress_suite": zero_liquidation,
            "trajectory_1000x": trajectory["status"],
            "exact_blocker": blockers[0] if blockers else None,
            "generic_ready_display_allowed": False if status["overall_status"] != "READY" else True,
        },
    }
    return payloads


def hash_rows(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_payloads(paths: ContinuousEdgeGuardianPaths, payloads: Mapping[str, Any]) -> None:
    for filename, payload in payloads.items():
        if filename in {"untouched_holdout_rows.jsonl", "realtime_a_grade_economic_outcomes.jsonl"}:
            continue
        if filename in REQUIRED_GOAL_FILES:
            if filename.endswith(".md"):
                write_text(paths.goal_dir / filename, str(payload))
            else:
                write_json(paths.goal_dir / filename, payload)
            continue
        if filename.endswith(".md"):
            write_text(paths.public_dir / filename, str(payload))
            write_text(paths.worklog_dir / filename, str(payload))
        else:
            write_json(paths.public_dir / filename, payload)
            write_json(paths.worklog_dir / filename, payload)


def publish_row_artifacts(
    paths: ContinuousEdgeGuardianPaths,
    *,
    holdout_rows: list[dict[str, Any]],
    realtime_rows: list[dict[str, Any]],
) -> None:
    write_jsonl(paths.public_dir / "untouched_holdout_rows.jsonl", holdout_rows)
    write_jsonl(paths.worklog_dir / "untouched_holdout_rows.jsonl", holdout_rows)
    write_jsonl(paths.public_dir / "realtime_a_grade_economic_outcomes.jsonl", realtime_rows)
    write_jsonl(paths.worklog_dir / "realtime_a_grade_economic_outcomes.jsonl", realtime_rows)


def publish_redis_gate(payloads: Mapping[str, Any]) -> dict[str, Any]:
    gate = payloads.get("a_grade_execution_gate.json")
    status = payloads.get("continuous_edge_guardian_status.json")
    if not isinstance(gate, Mapping) or not isinstance(status, Mapping):
        return {"redis_publish_status": "SKIPPED_INVALID_PAYLOAD"}
    try:
        import redis  # type: ignore
    except Exception as exc:
        return {"redis_publish_status": "SKIPPED_REDIS_IMPORT_FAILED", "error": str(exc)}
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
        client.setex(A_GRADE_EXECUTION_GATE_REDIS_KEY, REDIS_TTL_SECONDS, json.dumps(gate, sort_keys=True, default=str))
        client.setex(STATUS_REDIS_KEY, REDIS_TTL_SECONDS, json.dumps(status, sort_keys=True, default=str))
    except Exception as exc:
        return {"redis_publish_status": "FAILED", "error": str(exc)}
    return {
        "redis_publish_status": "PASSED",
        "redis_keys": [A_GRADE_EXECUTION_GATE_REDIS_KEY, STATUS_REDIS_KEY],
        "ttl_seconds": REDIS_TTL_SECONDS,
        "old_redis_writes": False,
    }


def run_once(
    *,
    repo_root: Path = REPO_ROOT,
    publish_redis: bool = True,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    paths = ContinuousEdgeGuardianPaths(repo_root=repo_root)
    generated = generated_utc or utc_now()
    existing_lock = read_json(paths.goal_dir / "GOAL_LOCK.json", {})
    started_utc = str(existing_lock.get("started_utc") or generated)
    holdout_rows = read_jsonl(paths.holdout_rows_path)
    holdout_acquisition_status = build_holdout_evidence_acquisition_status(
        paths=paths,
        holdout_rows=holdout_rows,
        generated_utc=generated,
    )
    raw_realtime_rows = read_jsonl(paths.realtime_rows_path)
    realtime_rows, realtime_acquisition_status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=raw_realtime_rows,
        generated_utc=generated,
    )
    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=holdout_rows,
        realtime_rows=realtime_rows,
        holdout_acquisition_status=holdout_acquisition_status,
        realtime_acquisition_status=realtime_acquisition_status,
        generated_utc=generated,
        started_utc=started_utc,
    )
    write_payloads(paths, payloads)
    publish_row_artifacts(paths, holdout_rows=holdout_rows, realtime_rows=realtime_rows)
    redis_status = publish_redis_gate(payloads) if publish_redis else {"redis_publish_status": "SKIPPED_BY_CALLER"}
    status = dict(payloads["continuous_edge_guardian_status.json"])
    status["redis_publish"] = redis_status
    write_json(paths.public_dir / "continuous_edge_guardian_status.json", status)
    write_json(paths.worklog_dir / "continuous_edge_guardian_status.json", status)
    return status


def run_forever(
    *,
    repo_root: Path = REPO_ROOT,
    interval_seconds: float = 60.0,
    publish_redis: bool = True,
) -> None:
    while True:
        run_once(repo_root=repo_root, publish_redis=publish_redis)
        time.sleep(max(1.0, float(interval_seconds)))
