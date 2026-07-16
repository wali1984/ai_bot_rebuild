from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .accounting import coerce_float, pnl_bps, pnl_usd


ADAPTIVE_CAPITAL_POLICY_VERSION = "ADAPTIVE_CAPITAL_ALLOCATOR_V1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_iso_from_any(value: Any) -> str | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_to_est_iso(value: Any) -> str | None:
    """Convert any ISO timestamp (UTC or offset-aware) to Eastern Time with -04:00/-05:00 offset.

    Passing an already-EST string is safe — result is idempotent.
    Returns None if value cannot be parsed.
    """
    dt = parse_utc(value)
    if dt is None:
        return None
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
    except ImportError:
        try:
            from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
        except ImportError:
            return None
    return dt.astimezone(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def seconds_between(start_iso: Any, end_iso: str) -> int:
    start = parse_utc(start_iso)
    end = parse_utc(end_iso)
    if start is None or end is None:
        return 0
    return max(0, int((end - start).total_seconds()))


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def first_number(*values: Any) -> float | None:
    for value in values:
        parsed = coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def atr_bps_from_payloads(*payloads: dict[str, Any] | None, price: Any = None) -> float | None:
    bps_keys = ("entry_atr_bps", "atr_bps", "true_range_bps", "natr_bps")
    pct_keys = ("atr_pct", "true_range_pct", "ta_NATR", "ta_NATR_14")
    price_keys = ("atr_14", "ta_ATR", "ta_ATR_14", "ATR", "TRANGE", "ta_TRANGE")

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        parsed = first_number(*(payload.get(key) for key in bps_keys))
        if parsed is not None:
            return abs(parsed)

    # Current feature pct fields are percent-units: 0.05 means 0.05%, or 5 bps.
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        parsed = first_number(*(payload.get(key) for key in pct_keys))
        if parsed is not None:
            return abs(parsed) * 100.0

    reference_price = first_number(price)
    if reference_price is not None and reference_price > 0:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            parsed = first_number(*(payload.get(key) for key in price_keys))
            if parsed is not None:
                return abs(parsed) / reference_price * 10000.0
    return None


def _nested_first_number(mapping: dict[str, Any] | None, *keys: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    return first_number(*(mapping.get(key) for key in keys))


def _liquidation_estimate(*, side: str, entry_price: float, leverage: float | None, maintenance_rate: float) -> float | None:
    if entry_price <= 0 or leverage is None or leverage <= 0:
        return None
    # Paper-only futures approximation. At 1x there is effectively no useful
    # liquidation estimate for long cash-like exposure, so clamp at zero.
    if side == "long":
        return max(0.0, entry_price * (1.0 - (1.0 / leverage) + maintenance_rate))
    return entry_price * (1.0 + (1.0 / leverage) - maintenance_rate)


@dataclass
class PaperNetPosition:
    position_id: str
    symbol: str
    side: str
    net_quantity: float
    avg_entry_price: float
    opened_est: str
    source_signal_id: str | None = None
    prediction_id: str | None = None
    preemptive_decision_id: str | None = None
    risk_decision_id: str | None = None
    orchestrator_decision_id: str | None = None
    allocator_decision_id: str | None = None
    materialization_queue_id: str | None = None
    materialization_queue_accepted_at: str | None = None
    materialization_queue_expires_at: str | None = None
    market_state_id: str | None = None
    trainer_source: str | None = None
    timeframe: str | None = None
    feature_snapshot_id: str | None = None
    decision_id: str | None = None
    mtf_snapshot_id: str | None = None
    feature_cutoff: str | None = None
    decision_time: str | None = None
    available_at: str | None = None
    selected_action: str | None = None
    model_version: str | None = None
    checkpoint_id: str | None = None
    checkpoint_id_source: str | None = None
    entry_prediction_snapshot: dict[str, Any] | None = None
    risk_decision_record_key: str | None = None
    risk_decision_record_hash: str | None = None
    risk_decision_record_resolved: bool | None = None
    risk_decision_source: str | None = None
    orchestrator_decision_record_key: str | None = None
    orchestrator_decision_record_hash: str | None = None
    orchestrator_decision_record_resolved: bool | None = None
    orchestrator_decision_source: str | None = None
    decision_record_missing_reasons: list[Any] | None = None
    source_hashes: dict[str, Any] | None = None
    feature_vector_hash: str | None = None
    provider_hashes: dict[str, Any] | None = None
    confidence_raw: float | None = None
    confidence_calibrated: float | None = None
    confidence_executable_trade: float | None = None
    dynamic_exploration_floor: float | None = None
    dynamic_exploration_floor_formula: str | None = None
    exploration_floor_inputs: dict[str, Any] | None = None
    paper_risk_controller_exploration_above_floor: bool | None = None
    paper_risk_controller_exploration_eligible: bool | None = None
    bootstrap_exploration: bool | None = None
    bootstrap_overridden_blockers: list[Any] | None = None
    selected_action_probability: float | None = None
    expected_move_bps: float | None = None
    action_probabilities: Any | None = None
    policy_value: float | None = None
    value_baseline: float | None = None
    selected_action_log_prob: float | None = None
    old_log_prob: float | None = None
    old_value: float | None = None
    rollout_id: str | None = None
    trajectory_index: int | None = None
    ppo_on_policy_entry_fields_present: bool | None = None
    entry_policy_fields_source: str | None = None
    paper_learning_lane: str | None = None
    prediction_score_source: str | None = None
    prediction_score_missing_reason: str | None = None
    candidate_id: str | None = None
    paper_policy_owner: str | None = None
    policy_fingerprint: str | None = None
    model_source: str | None = None
    selector_policy_fingerprint: str | None = None
    frozen_selector_fingerprint: str | None = None
    candidate_selected_before_outcome: bool | None = None
    candidate_selected_after_outcome: bool | None = None
    post_outcome_candidate_selection: bool | None = None
    future_labels_used_as_features: bool | None = None
    paper_opportunity_tier: str | None = None
    paper_opportunity_tier_reason: str | None = None
    explicit_paper_opportunity_tier: str | None = None
    paper_fill_allowed_source: str | None = None
    strict_paper_fill_allowed_upstream: bool | None = None
    calibration_label_purpose: str | None = None
    entry_market_state_id: str | None = None
    strategy_id: str | None = None
    strategy_family: str | None = None
    strategy_selected_mode: str | None = None
    hedge_state: str | None = None
    hedge_reason: str | None = None
    # Adaptive hedging pair linkage (2026-07-16): a hedge child position keys
    # under "{symbol}::HEDGE" and carries its parent's position id; the parent
    # carries the child fill id while hedged.
    hedge_parent_id: str | None = None
    hedge_child_id: str | None = None
    hedge_ratio: float | None = None
    hedge_entry_parent_pnl_bps: float | None = None
    drawdown_at_entry: float | None = None
    market_regime_at_entry: str | None = None
    liquidity_zone_context: dict[str, Any] | None = None
    liquidation_distance_context: dict[str, Any] | None = None
    microstructure_context: dict[str, Any] | None = None
    oi_funding_context: dict[str, Any] | None = None
    public_intel_context: dict[str, Any] | None = None
    major_move_signal_id: str | None = None
    squeeze_evidence_score: float | None = None
    squeeze_evidence_source: str | None = None
    squeeze_evidence_components: dict[str, Any] | None = None
    squeeze_evidence_unavailable_reason: str | None = None
    future_window_label_source: str | None = None
    adaptive_allocation: dict[str, Any] | None = None
    adaptive_capital_policy_version: str | None = None
    policy_activated_at: str | None = None
    gross_notional_usd: float | None = None
    allocated_margin_usd: float | None = None
    effective_leverage: float | None = None
    recommended_leverage: float | None = None
    recommended_margin_mode: str | None = None
    margin_mode_simulated: str | None = None
    maintenance_margin_estimate: float | None = None
    liquidation_price_estimate: float | None = None
    liquidation_buffer_bps: float | None = None
    risk_budget_usd: float | None = None
    risk_budget_source: str | None = None
    stop_distance_bps: float | None = None
    expected_fees_usd: float | None = None
    expected_funding_bps: float | None = None
    funding_rate: float | None = None
    funding_interval_seconds: float | None = None
    expected_funding_usd: float | None = None
    expected_net_pnl_usd: float | None = None
    expected_max_loss_usd: float | None = None
    expected_shortfall_usd: float | None = None
    hedge_budget_usd: float | None = None
    capital_allocation_reason: str | None = None
    entry_atr_bps: float | None = None
    entry_feature_available_at: str | None = None
    entry_feature_generated_at: str | None = None
    entry_feature_cutoff: str | None = None
    entry_feature_decision_time: str | None = None
    entry_feature_source: str | None = None
    entry_feature_candle_closed_confirmed: bool | None = None
    entry_feature_unavailable_reason: str | None = None
    entry_feature_snapshot: dict[str, Any] | None = None
    entry_observed_spread_bps: float | None = None
    entry_spread_source: str | None = None
    entry_spread_unavailable_reason: str | None = None
    observed_bid: float | None = None
    observed_ask: float | None = None
    observed_spread_bps: float | None = None
    order_size: float | None = None
    order_size_usd: float | None = None
    top_book_bid_depth_usd: float | None = None
    top_book_ask_depth_usd: float | None = None
    depth_derived_price_impact_bps: float | None = None
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    orderbook_depth_usd: float | None = None
    entry_orderbook_depth_usd: float | None = None
    entry_orderbook_depth_side: str | None = None
    top_of_book_depth_usd: float | None = None
    market_depth_usd: float | None = None
    orderbook_depth_source: str | None = None
    depth_utilization_pct: float | None = None
    depth_price_impact_bps: float | None = None
    depth_price_impact_source: str | None = None
    depth_price_impact_model: str | None = None
    depth_price_impact_side: str | None = None
    depth_price_impact_quantity: float | None = None
    depth_price_impact_filled_quantity: float | None = None
    depth_price_impact_fill_complete: bool | None = None
    depth_price_impact_vwap: float | None = None
    depth_price_impact_touch_price: float | None = None
    expected_slippage_bps: float | None = None
    expected_slippage_usd: float | None = None
    expected_slippage_source: str | None = None
    expected_slippage_modeled: bool | None = None
    expected_slippage_unavailable_reason: str | None = None
    correlation_exposure_pct: float | None = None
    correlation_input_source: str | None = None
    correlation_input_status: str | None = None
    correlation_pair_count: int | None = None
    correlation_diagnostics: dict[str, Any] | None = None
    expected_move_after_cost_bps: float | None = None
    realized_slippage_bps: float | None = None
    realized_slippage_usd: float | None = None
    decision_latency_ms: float | None = None
    latency_source: str | None = None
    latency_reserve_bps: float | None = None
    latency_reserve_source: str | None = None
    maker_taker_assumption: str | None = None
    maker_probability: float | None = None
    taker_probability: float | None = None
    maker_taker_probability: float | None = None
    maker_taker_probability_detail: dict[str, Any] | None = None
    maker_taker_probabilities: dict[str, Any] | None = None
    maker_taker_probability_source: str | None = None
    fee_schedule: dict[str, Any] | None = None
    fee_bps: float | None = None
    fee_bps_source: str | None = None
    fee_bps_configured_schedule: bool | None = None
    holding_period_funding_bps: float | None = None
    holding_period_funding_source: str | None = None
    partial_fill_count: int | None = None
    partial_fill_estimate: dict[str, Any] | None = None
    partial_fill_probability: float | None = None
    partial_fill_adjustment_bps: float | None = None
    partial_fills: list[dict[str, Any]] | None = None
    fill_count: int | None = None
    all_partial_fills: list[dict[str, Any]] | None = None
    partial_fill_plan: dict[str, Any] | list[dict[str, Any]] | None = None
    execution_probability: float | None = None
    mark_index_divergence_bps: float | None = None
    mark_index_divergence: float | None = None
    mark_index_source: str | None = None
    mark_index_available_at: str | None = None
    mark_price: float | None = None
    index_price: float | None = None
    cost_source: str | None = None
    cost_source_timestamp: str | None = None
    source_timestamp: str | None = None
    cost_evidence_freshness_ms: float | None = None
    cost_evidence_source_fields: dict[str, Any] | None = None
    runtime_cost_capture_source: str | None = None
    runtime_cost_capture_status: str | None = None
    runtime_cost_capture_required_fields: list[str] | None = None
    runtime_cost_capture_missing_fields: list[str] | None = None
    runtime_cost_capture_explained_missing_fields: list[str] | None = None
    runtime_cost_capture_unexplained_missing_fields: list[str] | None = None
    runtime_cost_capture_order_cost_applicable: bool | None = None
    runtime_cost_capture_no_order_reason: str | None = None
    runtime_cost_capture_temporal_reject_reasons: list[str] | None = None
    fallback_cost_flag: bool | None = None
    fallback: bool | None = None
    production_grade_cost_flag: bool | None = None
    production_grade_cost_evidence: bool | None = None
    estimated_production_cost: float | None = None
    estimated_production_cost_bps: float | None = None
    counts_as_production_grade_training_evidence: bool | None = None
    fill_ids: list[str] = field(default_factory=list)
    best_favorable_price: float | None = None
    worst_adverse_price: float | None = None
    intra_trade_high_price: float | None = None
    intra_trade_low_price: float | None = None
    mfe_bps: float = 0.0
    mae_bps: float = 0.0
    mfe_usd: float = 0.0
    mae_usd: float = 0.0
    trailing_activation_price: float | None = None
    trailing_activation_time: str | None = None
    trailing_stop_price: float | None = None
    trailing_stop_history: list[dict[str, Any]] = field(default_factory=list)
    last_mark_price: float | None = None
    last_mark_est: str | None = None
    realized_pnl: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.net_quantity * self.avg_entry_price)

    def apply_same_side_fill(self, *, fill_id: str, quantity: float, price: float) -> None:
        prior_qty = self.net_quantity
        new_qty = prior_qty + quantity
        if new_qty <= 0:
            return
        self.avg_entry_price = ((self.avg_entry_price * prior_qty) + (price * quantity)) / new_qty
        self.net_quantity = new_qty
        if fill_id not in self.fill_ids:
            self.fill_ids.append(fill_id)

    def update_mark(self, *, mark_price: float | None, mark_time: str) -> None:
        if mark_price is None or mark_price <= 0:
            return
        self.last_mark_price = mark_price
        self.last_mark_est = utc_to_est_iso(mark_time) or mark_time
        self.intra_trade_high_price = max(self.intra_trade_high_price or self.avg_entry_price, mark_price)
        self.intra_trade_low_price = min(self.intra_trade_low_price or self.avg_entry_price, mark_price)
        if self.best_favorable_price is None:
            self.best_favorable_price = self.avg_entry_price
        if self.worst_adverse_price is None:
            self.worst_adverse_price = self.avg_entry_price
        if self.side == "long":
            self.best_favorable_price = max(self.best_favorable_price, mark_price)
            self.worst_adverse_price = min(self.worst_adverse_price, mark_price)
            favorable_delta = max(0.0, (self.intra_trade_high_price or self.avg_entry_price) - self.avg_entry_price)
            adverse_delta = max(0.0, self.avg_entry_price - (self.intra_trade_low_price or self.avg_entry_price))
        else:
            self.best_favorable_price = min(self.best_favorable_price, mark_price)
            self.worst_adverse_price = max(self.worst_adverse_price, mark_price)
            favorable_delta = max(0.0, self.avg_entry_price - (self.intra_trade_low_price or self.avg_entry_price))
            adverse_delta = max(0.0, (self.intra_trade_high_price or self.avg_entry_price) - self.avg_entry_price)
        if self.avg_entry_price > 0:
            self.mfe_bps = max(self.mfe_bps, favorable_delta / self.avg_entry_price * 10000.0)
            self.mae_bps = max(self.mae_bps, adverse_delta / self.avg_entry_price * 10000.0)
        self.mfe_usd = max(self.mfe_usd, favorable_delta * self.net_quantity)
        self.mae_usd = max(self.mae_usd, adverse_delta * self.net_quantity)

    def record_trailing_state(
        self,
        *,
        activation_price: float,
        activation_time: str,
        stop_price: float,
        reason: str,
    ) -> None:
        if self.trailing_activation_price is None:
            self.trailing_activation_price = activation_price
            self.trailing_activation_time = activation_time
        self.trailing_stop_price = stop_price
        event = {
            "generated_utc": activation_time,
            "activation_price": activation_price,
            "trailing_stop_price": stop_price,
            "reason": reason,
        }
        if not self.trailing_stop_history or self.trailing_stop_history[-1] != event:
            self.trailing_stop_history.append(event)

    def unrealized_pnl(self) -> float:
        if self.last_mark_price is None:
            return 0.0
        return pnl_usd(
            side=self.side,
            entry_price=self.avg_entry_price,
            exit_price=self.last_mark_price,
            quantity=self.net_quantity,
        )

    def unrealized_pnl_bps(self) -> float:
        if self.last_mark_price is None:
            return 0.0
        return pnl_bps(
            side=self.side,
            entry_price=self.avg_entry_price,
            exit_price=self.last_mark_price,
        )

    def to_payload(self, *, generated_utc: str) -> dict[str, Any]:
        allocation = self.adaptive_allocation if isinstance(self.adaptive_allocation, dict) else {}
        adaptive_capital_policy_version = first_present(
            self.adaptive_capital_policy_version,
            allocation.get("adaptive_capital_policy_version"),
        )
        policy_activated_at = first_present(
            self.policy_activated_at,
            allocation.get("policy_activated_at"),
        )
        allocation_id = first_present(
            allocation.get("allocation_id"),
            allocation.get("allocator_decision_id"),
        )
        allocator_decision_id = first_present(self.allocator_decision_id, allocation_id)
        allocator_decision_id_source = (
            "paper_position.allocator_decision_id"
            if self.allocator_decision_id not in (None, "")
            else "adaptive_allocation.allocation_id"
            if allocation_id not in (None, "")
            else None
        )
        provider_hashes = self.provider_hashes
        if not provider_hashes and isinstance(self.source_hashes, dict):
            provider_hashes = {
                key: value
                for key, value in self.source_hashes.items()
                if key not in {"feature_vector_hash", "prediction_hash", "source_lineage_hash"}
                and value not in (None, "")
            } or None
        feature_vector_hash = first_present(
            self.feature_vector_hash,
            self.source_hashes.get("feature_vector_hash") if isinstance(self.source_hashes, dict) else None,
        )
        raw_safety_fields = {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "test_order": False,
            "live_order": False,
            "counts_as_A_plus": False,
            "counts_as_final_A_plus": False,
            "counts_as_live_ready": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
        invariant_checks = {
            "paper_only_is_true": True,
            "routes_to_live_is_false": True,
            "places_real_order_is_false": True,
            "test_order_is_false": True,
            "live_order_is_false": True,
            "counts_as_A_plus_is_false": True,
            "counts_as_final_A_plus_is_false": True,
            "counts_as_live_ready_is_false": True,
            "order_submitted_is_false": True,
            "test_order_submitted_is_false": True,
            "leverage_mutated_is_false": True,
            "margin_mutated_is_false": True,
        }
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "net_quantity": round(self.net_quantity, 12),
            "avg_entry_price": self.avg_entry_price,
            "entry_price": self.avg_entry_price,
            "entry_price_source": "accepted_paper_fill.avg_entry_price",
            "entry_fill_id": self.fill_ids[0] if self.fill_ids else self.position_id,
            "entry_time": self.opened_est,
            "notional": self.notional,
            "gross_notional": self.notional,
            "adaptive_allocation": self.adaptive_allocation,
            "adaptive_capital_policy_version": adaptive_capital_policy_version,
            "policy_activated_at": policy_activated_at,
            "gross_notional_usd": self.gross_notional_usd if self.gross_notional_usd is not None else self.notional,
            "allocated_margin_usd": self.allocated_margin_usd,
            "effective_leverage": self.effective_leverage,
            "recommended_leverage": self.recommended_leverage,
            "recommended_margin_mode": self.recommended_margin_mode,
            "margin_mode_simulated": self.margin_mode_simulated,
            "maintenance_margin_estimate": self.maintenance_margin_estimate,
            "liquidation_price_estimate": self.liquidation_price_estimate,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "risk_budget_usd": self.risk_budget_usd,
            "risk_budget_source": self.risk_budget_source,
            "stop_distance_bps": self.stop_distance_bps,
            "expected_fees_usd": self.expected_fees_usd,
            "expected_funding_bps": self.expected_funding_bps,
            "funding_rate": self.funding_rate,
            "funding_interval_seconds": self.funding_interval_seconds,
            "expected_funding_usd": self.expected_funding_usd,
            "expected_net_pnl_usd": self.expected_net_pnl_usd,
            "expected_max_loss_usd": self.expected_max_loss_usd,
            "expected_shortfall_usd": self.expected_shortfall_usd,
            "hedge_budget_usd": self.hedge_budget_usd,
            "capital_allocation_reason": self.capital_allocation_reason,
            "entry_atr_bps": self.entry_atr_bps,
            "atr_bps": self.entry_atr_bps,
            "entry_feature_available_at": self.entry_feature_available_at,
            "entry_feature_generated_at": self.entry_feature_generated_at,
            "entry_feature_cutoff": self.entry_feature_cutoff,
            "entry_feature_decision_time": self.entry_feature_decision_time,
            "entry_feature_source": self.entry_feature_source,
            "entry_feature_candle_closed_confirmed": self.entry_feature_candle_closed_confirmed,
            "entry_feature_unavailable_reason": self.entry_feature_unavailable_reason,
            "entry_feature_snapshot": self.entry_feature_snapshot,
            "opened_est": self.opened_est,
            "last_mark_est": self.last_mark_est,
            "last_mark_price": self.last_mark_price,
            "unrealized_pnl": self.unrealized_pnl(),
            "unrealized_pnl_bps": self.unrealized_pnl_bps(),
            "realized_pnl": self.realized_pnl,
            "source_signal_id": self.source_signal_id,
            "signal_id": self.source_signal_id,
            "entry_signal_id": self.source_signal_id,
            "prediction_id": self.prediction_id,
            "entry_prediction_id": self.prediction_id,
            "preemptive_decision_id": self.preemptive_decision_id,
            "risk_decision_id": self.risk_decision_id,
            "orchestrator_decision_id": self.orchestrator_decision_id,
            "allocator_decision_id": allocator_decision_id,
            "allocator_decision_id_source": allocator_decision_id_source,
            "allocation_id": allocation_id,
            "materialization_queue_id": self.materialization_queue_id,
            "materialization_queue_accepted_at": self.materialization_queue_accepted_at,
            "materialization_queue_expires_at": self.materialization_queue_expires_at,
            "market_state_id": self.market_state_id,
            "entry_market_state_id": self.entry_market_state_id or self.market_state_id,
            "trainer_source": self.trainer_source,
            "timeframe": self.timeframe,
            "feature_snapshot_id": self.feature_snapshot_id,
            "entry_feature_snapshot_id": self.feature_snapshot_id,
            "decision_id": self.decision_id,
            "mtf_snapshot_id": self.mtf_snapshot_id,
            "feature_cutoff": self.feature_cutoff,
            "decision_time": self.decision_time,
            "available_at": self.available_at,
            "selected_action": self.selected_action or self.side,
            "model_version": self.model_version,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_id_source": self.checkpoint_id_source,
            "entry_prediction_snapshot": self.entry_prediction_snapshot,
            "risk_decision_record_key": self.risk_decision_record_key,
            "risk_decision_record_hash": self.risk_decision_record_hash,
            "risk_decision_record_resolved": self.risk_decision_record_resolved,
            "risk_decision_source": self.risk_decision_source,
            "orchestrator_decision_record_key": self.orchestrator_decision_record_key,
            "orchestrator_decision_record_hash": self.orchestrator_decision_record_hash,
            "orchestrator_decision_record_resolved": self.orchestrator_decision_record_resolved,
            "orchestrator_decision_source": self.orchestrator_decision_source,
            "decision_record_missing_reasons": self.decision_record_missing_reasons,
            "source_hashes": self.source_hashes,
            "feature_vector_hash": feature_vector_hash,
            "provider_hashes": provider_hashes,
            "confidence_raw": self.confidence_raw,
            "confidence_calibrated": self.confidence_calibrated,
            "confidence_executable_trade": self.confidence_executable_trade,
            "dynamic_exploration_floor": self.dynamic_exploration_floor,
            "dynamic_exploration_floor_formula": self.dynamic_exploration_floor_formula,
            "exploration_floor_inputs": self.exploration_floor_inputs,
            "paper_risk_controller_exploration_above_floor": (
                self.paper_risk_controller_exploration_above_floor
            ),
            "paper_risk_controller_exploration_eligible": (
                self.paper_risk_controller_exploration_eligible
            ),
            "bootstrap_exploration": self.bootstrap_exploration,
            "bootstrap_overridden_blockers": self.bootstrap_overridden_blockers,
            "selected_action_probability": self.selected_action_probability,
            "expected_move_bps": self.expected_move_bps,
            "expected_move_after_cost_bps": self.expected_move_after_cost_bps,
            "action_probabilities": self.action_probabilities,
            "policy_value": self.policy_value,
            "value_baseline": self.value_baseline,
            "selected_action_log_prob": self.selected_action_log_prob,
            "old_log_prob": self.old_log_prob,
            "old_value": self.old_value,
            "rollout_id": self.rollout_id,
            "trajectory_index": self.trajectory_index,
            "ppo_on_policy_entry_fields_present": (
                self.ppo_on_policy_entry_fields_present
            ),
            "entry_policy_fields_source": self.entry_policy_fields_source,
            "paper_learning_lane": self.paper_learning_lane,
            "prediction_score_source": self.prediction_score_source,
            "prediction_score_missing_reason": self.prediction_score_missing_reason,
            "candidate_id": self.candidate_id,
            "paper_policy_owner": self.paper_policy_owner,
            "policy_fingerprint": self.policy_fingerprint,
            "model_source": self.model_source,
            "selector_policy_fingerprint": self.selector_policy_fingerprint,
            "frozen_selector_fingerprint": self.frozen_selector_fingerprint,
            "candidate_selected_before_outcome": self.candidate_selected_before_outcome,
            "candidate_selected_after_outcome": self.candidate_selected_after_outcome,
            "post_outcome_candidate_selection": self.post_outcome_candidate_selection,
            "future_labels_used_as_features": self.future_labels_used_as_features,
            "paper_opportunity_tier": self.paper_opportunity_tier,
            "tier": (
                self.paper_opportunity_tier
                if str(self.paper_opportunity_tier or "").strip().upper()
                == "PAPER_RISK_CONTROLLER_EXPLORATION"
                else None
            ),
            "exploration_tier": (
                self.paper_opportunity_tier
                if str(self.paper_opportunity_tier or "").strip().upper()
                == "PAPER_RISK_CONTROLLER_EXPLORATION"
                else None
            ),
            "paper_exploration_tier": (
                self.paper_opportunity_tier
                if str(self.paper_opportunity_tier or "").strip().upper()
                == "PAPER_RISK_CONTROLLER_EXPLORATION"
                else None
            ),
            "paper_opportunity_tier_reason": self.paper_opportunity_tier_reason,
            "explicit_paper_opportunity_tier": self.explicit_paper_opportunity_tier,
            "paper_fill_allowed_source": self.paper_fill_allowed_source,
            "strict_paper_fill_allowed_upstream": self.strict_paper_fill_allowed_upstream,
            "calibration_label_purpose": self.calibration_label_purpose,
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_selected_mode": self.strategy_selected_mode,
            "hedge_state": self.hedge_state,
            "hedge_reason": self.hedge_reason,
            "hedge_parent_id": self.hedge_parent_id,
            "hedge_child_id": self.hedge_child_id,
            "hedge_ratio": self.hedge_ratio,
            "hedge_entry_parent_pnl_bps": self.hedge_entry_parent_pnl_bps,
            "drawdown_at_entry": self.drawdown_at_entry,
            "market_regime_at_entry": self.market_regime_at_entry,
            "liquidity_zone_context": self.liquidity_zone_context,
            "liquidation_distance_context": self.liquidation_distance_context,
            "microstructure_context": self.microstructure_context,
            "oi_funding_context": self.oi_funding_context,
            "public_intel_context": self.public_intel_context,
            "major_move_signal_id": self.major_move_signal_id,
            "squeeze_evidence_score": self.squeeze_evidence_score,
            "squeeze_evidence_source": self.squeeze_evidence_source,
            "squeeze_evidence_components": self.squeeze_evidence_components,
            "squeeze_evidence_unavailable_reason": self.squeeze_evidence_unavailable_reason,
            "future_window_label_source": self.future_window_label_source,
            "mfe_bps": self.mfe_bps,
            "mfe_usd": self.mfe_usd,
            "mae_bps": self.mae_bps,
            "mae_usd": self.mae_usd,
            "intra_trade_high_price": self.intra_trade_high_price,
            "intra_trade_low_price": self.intra_trade_low_price,
            "trailing_activation_price": self.trailing_activation_price,
            "trailing_activation_time": self.trailing_activation_time,
            "trailing_stop_price": self.trailing_stop_price,
            "trailing_stop_history": list(self.trailing_stop_history),
            "actual_observed_spread_entry_bps": self.entry_observed_spread_bps,
            "observed_bid": self.observed_bid,
            "observed_ask": self.observed_ask,
            "observed_spread_bps": self.observed_spread_bps,
            "order_size": self.order_size,
            "order_size_usd": self.order_size_usd,
            "entry_spread_source": self.entry_spread_source,
            "entry_spread_unavailable_reason": self.entry_spread_unavailable_reason,
            "top_book_bid_depth_usd": self.top_book_bid_depth_usd,
            "top_book_ask_depth_usd": self.top_book_ask_depth_usd,
            "bid_depth_usd": self.bid_depth_usd,
            "ask_depth_usd": self.ask_depth_usd,
            "orderbook_depth_usd": self.orderbook_depth_usd,
            "entry_orderbook_depth_usd": self.entry_orderbook_depth_usd,
            "entry_orderbook_depth_side": self.entry_orderbook_depth_side,
            "top_of_book_depth_usd": self.top_of_book_depth_usd,
            "market_depth_usd": self.market_depth_usd,
            "orderbook_depth_source": self.orderbook_depth_source,
            "depth_utilization_pct": self.depth_utilization_pct,
            "depth_price_impact_bps": self.depth_price_impact_bps,
            "depth_derived_price_impact_bps": self.depth_derived_price_impact_bps,
            "depth_price_impact_source": self.depth_price_impact_source,
            "depth_price_impact_model": self.depth_price_impact_model,
            "depth_price_impact_side": self.depth_price_impact_side,
            "depth_price_impact_quantity": self.depth_price_impact_quantity,
            "depth_price_impact_filled_quantity": self.depth_price_impact_filled_quantity,
            "depth_price_impact_fill_complete": self.depth_price_impact_fill_complete,
            "depth_price_impact_vwap": self.depth_price_impact_vwap,
            "depth_price_impact_touch_price": self.depth_price_impact_touch_price,
            "expected_slippage_bps": self.expected_slippage_bps,
            "expected_slippage_usd": self.expected_slippage_usd,
            "expected_slippage_source": self.expected_slippage_source,
            "expected_slippage_modeled": self.expected_slippage_modeled,
            "expected_slippage_unavailable_reason": self.expected_slippage_unavailable_reason,
            "correlation_exposure_pct": self.correlation_exposure_pct,
            "correlation_input_source": self.correlation_input_source,
            "correlation_input_status": self.correlation_input_status,
            "correlation_pair_count": self.correlation_pair_count,
            "correlation_diagnostics": self.correlation_diagnostics,
            "realized_slippage_bps": self.realized_slippage_bps,
            "realized_slippage_usd": self.realized_slippage_usd,
            "decision_latency_ms": self.decision_latency_ms,
            "latency_ms": self.decision_latency_ms,
            "paper_fill_latency_ms": self.decision_latency_ms,
            "fill_latency_ms": self.decision_latency_ms,
            "execution_latency_ms": self.decision_latency_ms,
            "simulated_latency_ms": self.decision_latency_ms,
            "latency_source": self.latency_source,
            "latency_reserve_bps": self.latency_reserve_bps,
            "latency_reserve_source": self.latency_reserve_source,
            "maker_taker_assumption": self.maker_taker_assumption,
            "maker_probability": self.maker_probability,
            "taker_probability": self.taker_probability,
            "maker_taker_probability": self.maker_taker_probability,
            "maker_taker_probability_detail": self.maker_taker_probability_detail,
            "maker_taker_probabilities": self.maker_taker_probabilities,
            "maker_taker_probability_source": self.maker_taker_probability_source,
            "fee_schedule": self.fee_schedule,
            "fee_bps": self.fee_bps,
            "fee_bps_source": self.fee_bps_source,
            "fee_bps_configured_schedule": self.fee_bps_configured_schedule,
            "holding_period_funding_bps": self.holding_period_funding_bps,
            "holding_period_funding_source": self.holding_period_funding_source,
            "partial_fill_count": self.partial_fill_count,
            "partial_fill_estimate": self.partial_fill_estimate,
            "partial_fill_probability": self.partial_fill_probability,
            "partial_fill_adjustment_bps": self.partial_fill_adjustment_bps,
            "partial_fills": self.partial_fills,
            "fill_count": self.fill_count,
            "all_partial_fills": self.all_partial_fills,
            "partial_fill_plan": self.partial_fill_plan,
            "execution_probability": self.execution_probability,
            "mark_index_divergence_bps": self.mark_index_divergence_bps,
            "mark_index_divergence": self.mark_index_divergence,
            "mark_index_source": self.mark_index_source,
            "mark_index_available_at": self.mark_index_available_at,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "cost_source": self.cost_source,
            "cost_source_timestamp": self.cost_source_timestamp,
            "source_timestamp": self.source_timestamp,
            "cost_evidence_freshness_ms": self.cost_evidence_freshness_ms,
            "cost_evidence_source_fields": self.cost_evidence_source_fields,
            "runtime_cost_capture_source": self.runtime_cost_capture_source,
            "runtime_cost_capture_status": self.runtime_cost_capture_status,
            "runtime_cost_capture_required_fields": self.runtime_cost_capture_required_fields,
            "runtime_cost_capture_missing_fields": self.runtime_cost_capture_missing_fields,
            "runtime_cost_capture_explained_missing_fields": self.runtime_cost_capture_explained_missing_fields,
            "runtime_cost_capture_unexplained_missing_fields": self.runtime_cost_capture_unexplained_missing_fields,
            "runtime_cost_capture_order_cost_applicable": self.runtime_cost_capture_order_cost_applicable,
            "runtime_cost_capture_no_order_reason": self.runtime_cost_capture_no_order_reason,
            "runtime_cost_capture_temporal_reject_reasons": self.runtime_cost_capture_temporal_reject_reasons,
            "fallback_cost_flag": self.fallback_cost_flag,
            "fallback": self.fallback,
            "production_grade_cost_flag": self.production_grade_cost_flag,
            "production_grade_cost_evidence": self.production_grade_cost_evidence,
            "estimated_production_cost": self.estimated_production_cost,
            "estimated_production_cost_bps": self.estimated_production_cost_bps,
            "counts_as_production_grade_training_evidence": self.counts_as_production_grade_training_evidence,
            "source_fill_ids": list(self.fill_ids),
            "best_favorable_price": self.best_favorable_price,
            "worst_adverse_price": self.worst_adverse_price,
            "position_age_seconds": seconds_between(self.opened_est, generated_utc),
            "position_state": "OPEN_POSITION",
            "paper_fill_allowed": True,
            "decision": "ACCEPTED_PAPER_FILL",
            "account_scope": "PAPER_SIM_ACCOUNT",
            "source_type": "paper_sim_valid_economic_fill",
            "paper_or_live": "paper",
            "contains_simulated_positions": True,
            "contains_live_positions": False,
            "contains_quarantined_positions": False,
            "equity_trusted": True,
            "pnl_trusted": True,
            "reason_if_untrusted": None,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "live_order": False,
            "test_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "counts_as_A_plus": False,
            "counts_as_final_A_plus": False,
            "counts_as_final_a_plus": False,
            "counts_as_live_ready": False,
            "raw_safety_fields": raw_safety_fields,
            "invariant_checks": invariant_checks,
        }


def position_from_fill(fill: dict[str, Any], *, fill_id: str, side: str, quantity: float, price: float) -> PaperNetPosition:
    symbol = str(fill.get("symbol") or "").upper()
    entry_time_utc = (
        utc_iso_from_any(fill.get("fill_price_utc"))
        or utc_iso_from_any(fill.get("generated_utc"))
        or utc_iso_from_any(fill.get("entry_price_utc"))
        or utc_iso_from_any(fill.get("fill_time_est"))
        or utc_now_iso()
    )
    # Convert all candidate timestamp sources to Eastern Time before storing in _est field.
    # fill_time_est may already carry an EST offset — utc_to_est_iso is idempotent for those.
    opened = (
        utc_to_est_iso(fill.get("fill_time_est"))
        or utc_to_est_iso(entry_time_utc)
        or entry_time_utc
    )
    allocation = fill.get("adaptive_allocation") if isinstance(fill.get("adaptive_allocation"), dict) else {}
    leverage_recommendation = (
        fill.get("leverage_recommendation")
        if isinstance(fill.get("leverage_recommendation"), dict)
        else {}
    )
    gross_notional = abs(quantity * price)
    recommended_leverage = first_number(
        fill.get("recommended_leverage"),
        allocation.get("recommended_leverage"),
        leverage_recommendation.get("recommended_leverage"),
        leverage_recommendation.get("leverage"),
        1.0,
    )
    effective_leverage = first_number(
        fill.get("effective_leverage"),
        fill.get("leverage"),
        recommended_leverage,
        1.0,
    )
    effective_leverage = max(1.0, effective_leverage or 1.0)
    allocated_margin = first_number(fill.get("allocated_margin_usd"), allocation.get("allocated_margin_usd"))
    if allocated_margin is None and effective_leverage > 0:
        allocated_margin = gross_notional / effective_leverage
    maintenance_rate = first_number(fill.get("maintenance_margin_rate"), allocation.get("maintenance_margin_rate"), 0.005) or 0.005
    maintenance_margin = first_number(fill.get("maintenance_margin_estimate"), allocation.get("maintenance_margin_estimate"))
    if maintenance_margin is None:
        maintenance_margin = gross_notional * max(0.0, maintenance_rate)
    risk_budget_pct = first_number(allocation.get("risk_budget_pct_of_equity"), allocation.get("risk_budget_pct"))
    allocation_equity = _nested_first_number(allocation.get("model_inputs"), "equity")
    risk_budget = first_number(fill.get("risk_budget_usd"), allocation.get("risk_budget_usd"))
    risk_budget_source = None
    if risk_budget is None and risk_budget_pct is not None and allocation_equity is not None:
        risk_budget = allocation_equity * risk_budget_pct
        risk_budget_source = "adaptive_allocation.risk_budget_pct_of_equity"
    micro = fill.get("microstructure_context") if isinstance(fill.get("microstructure_context"), dict) else {}
    features = fill.get("features") if isinstance(fill.get("features"), dict) else {}
    entry_spread = first_number(
        fill.get("actual_observed_spread_entry_bps"),
        fill.get("bid_ask_spread_bps"),
        micro.get("bid_ask_spread_bps"),
        micro.get("spread_bps"),
        micro.get("ob_spread_bps"),
    )
    expected_slippage_bps = first_number(fill.get("expected_slippage_bps"), fill.get("slippage_bps"))
    expected_slippage_usd = first_number(fill.get("expected_slippage_usd"))
    if expected_slippage_usd is None and expected_slippage_bps is not None:
        expected_slippage_usd = gross_notional * max(0.0, expected_slippage_bps) / 10000.0
    allocation_model_inputs = allocation.get("model_inputs") if isinstance(allocation.get("model_inputs"), dict) else {}
    expected_fees_usd = first_number(fill.get("expected_fees_usd"), allocation.get("expected_fees_usd"))
    expected_funding_bps = first_number(
        fill.get("expected_funding_bps"),
        fill.get("funding_bps"),
        fill.get("funding_rate_bps"),
        allocation.get("expected_funding_bps"),
        allocation_model_inputs.get("expected_funding_bps"),
        allocation_model_inputs.get("funding_bps"),
        allocation_model_inputs.get("funding_rate_bps"),
    )
    funding_rate = first_number(fill.get("funding_rate"), allocation_model_inputs.get("funding_rate"))
    if funding_rate is None and expected_funding_bps is not None:
        funding_rate = expected_funding_bps / 10000.0
    if expected_funding_bps is None and funding_rate is not None:
        expected_funding_bps = funding_rate * 10000.0
    funding_interval_seconds = first_number(
        fill.get("funding_interval_seconds"),
        allocation_model_inputs.get("funding_interval_seconds"),
        28800.0,
    )
    expected_funding_usd = first_number(fill.get("expected_funding_usd"), allocation.get("expected_funding_usd"))
    expected_net_pnl_usd = first_number(fill.get("expected_net_pnl_usd"), allocation.get("expected_net_pnl_usd"))
    expected_shortfall_usd = first_number(fill.get("expected_shortfall_usd"), allocation.get("expected_shortfall_usd"))
    hedge_budget_usd = first_number(fill.get("hedge_budget_usd"), allocation.get("hedge_budget_usd"))
    correlation_exposure_pct = first_number(
        fill.get("correlation_exposure_pct"),
        allocation.get("correlation_exposure_pct"),
        allocation_model_inputs.get("correlation_exposure_pct"),
    )
    correlation_input_source = first_present(
        fill.get("correlation_input_source"),
        allocation.get("correlation_input_source"),
        allocation_model_inputs.get("correlation_input_source"),
        "ADAPTIVE_ALLOCATION_MODEL_INPUTS" if correlation_exposure_pct is not None else None,
    )
    correlation_input_status = first_present(
        fill.get("correlation_input_status"),
        allocation.get("correlation_input_status"),
        allocation_model_inputs.get("correlation_input_status"),
        "READY" if correlation_exposure_pct is not None else None,
    )
    correlation_pair_count_float = first_number(
        fill.get("correlation_pair_count"),
        allocation.get("correlation_pair_count"),
        allocation_model_inputs.get("correlation_pair_count"),
    )
    correlation_pair_count = (
        int(correlation_pair_count_float)
        if correlation_pair_count_float is not None and correlation_pair_count_float >= 0
        else None
    )
    recommended_margin_mode = str(
        first_present(
            fill.get("recommended_margin_mode"),
            allocation.get("recommended_margin_mode"),
            "isolated_paper_simulated",
        )
    )
    adaptive_capital_policy_version = first_present(
        fill.get("adaptive_capital_policy_version"),
        allocation.get("adaptive_capital_policy_version"),
    )
    policy_activated_at = (
        first_present(
            fill.get("policy_activated_at"),
            allocation.get("policy_activated_at"),
            entry_time_utc,
        )
        if adaptive_capital_policy_version
        else None
    )
    squeeze_score = first_number(fill.get("squeeze_evidence_score"))
    source_hashes = fill.get("source_hashes") if isinstance(fill.get("source_hashes"), dict) else {}
    if not source_hashes:
        source_hashes = {
            key: value
            for key, value in {
                "feature_vector_hash": first_present(
                    fill.get("feature_vector_hash"),
                    fill.get("input_feature_hash"),
                ),
                "prediction_hash": fill.get("prediction_hash"),
                "source_lineage_hash": fill.get("source_lineage_hash"),
            }.items()
            if value not in (None, "")
        }
    action_probabilities = first_present(
        fill.get("action_probabilities"),
        fill.get("policy_action_probabilities"),
        allocation.get("action_probabilities"),
        allocation_model_inputs.get("action_probabilities"),
    )
    if not isinstance(action_probabilities, (dict, list, tuple)):
        action_probabilities = None
    provider_hashes = (
        fill.get("provider_hashes")
        if isinstance(fill.get("provider_hashes"), dict)
        else allocation.get("provider_hashes")
        if isinstance(allocation.get("provider_hashes"), dict)
        else None
    )
    if not provider_hashes and isinstance(source_hashes, dict):
        provider_hashes = {
            key: value
            for key, value in source_hashes.items()
            if key not in {"feature_vector_hash", "prediction_hash", "source_lineage_hash"}
            and value not in (None, "")
        } or None
    feature_vector_hash = first_present(
        fill.get("feature_vector_hash"),
        fill.get("input_feature_hash"),
        source_hashes.get("feature_vector_hash") if isinstance(source_hashes, dict) else None,
        allocation.get("feature_vector_hash"),
    )
    candidate_id = first_present(fill.get("candidate_id"), allocation.get("candidate_id"))
    paper_opportunity_tier = first_present(fill.get("paper_opportunity_tier"), allocation.get("paper_opportunity_tier"))
    materialization_queue_id = first_present(
        fill.get("materialization_queue_id"),
        allocation.get("materialization_queue_id"),
    )
    if (
        materialization_queue_id in (None, "")
        and str(paper_opportunity_tier or "").strip().upper() == "PAPER_RISK_CONTROLLER_EXPLORATION"
        and first_present(candidate_id, fill.get("prediction_id"), fill.get("signal_id")) not in (None, "")
    ):
        materialization_queue_id = (
            "paper_exploration_materialize_"
            + str(first_present(candidate_id, fill.get("prediction_id"), fill.get("signal_id")))
        )
    allocator_decision_id = first_present(
        fill.get("allocator_decision_id"),
        allocation.get("allocator_decision_id"),
    )
    confidence_raw = first_number(
        fill.get("confidence_raw"),
        allocation.get("confidence_raw"),
        allocation_model_inputs.get("confidence_raw"),
    )
    confidence_calibrated = first_number(
        fill.get("confidence_calibrated"),
        fill.get("confidence"),
        allocation.get("confidence_calibrated"),
        allocation.get("confidence"),
        allocation_model_inputs.get("confidence_calibrated"),
        allocation_model_inputs.get("confidence"),
    )
    confidence_executable_trade = first_number(
        fill.get("confidence_executable_trade"),
        allocation.get("confidence_executable_trade"),
        allocation_model_inputs.get("confidence_executable_trade"),
    )
    dynamic_exploration_floor = first_number(
        fill.get("dynamic_exploration_floor"),
        allocation.get("dynamic_exploration_floor"),
        allocation_model_inputs.get("dynamic_exploration_floor"),
    )
    exploration_floor_inputs = first_present(
        fill.get("exploration_floor_inputs"),
        fill.get("floor_inputs"),
        allocation.get("exploration_floor_inputs"),
        allocation.get("floor_inputs"),
        allocation_model_inputs.get("exploration_floor_inputs"),
        allocation_model_inputs.get("floor_inputs"),
    )
    if not isinstance(exploration_floor_inputs, dict):
        exploration_floor_inputs = None
    bootstrap_overridden_blockers = first_present(
        fill.get("bootstrap_overridden_blockers"),
        allocation.get("bootstrap_overridden_blockers"),
        allocation_model_inputs.get("bootstrap_overridden_blockers"),
    )
    if not isinstance(bootstrap_overridden_blockers, list):
        bootstrap_overridden_blockers = None
    expected_move_bps = first_number(
        fill.get("expected_move_bps"),
        fill.get("price_target_bps"),
        allocation.get("expected_move_bps"),
        allocation.get("price_target_bps"),
        allocation_model_inputs.get("expected_move_bps"),
        allocation_model_inputs.get("price_target_bps"),
    )
    expected_move_after_cost_bps = first_number(
        fill.get("expected_move_after_cost_bps"),
        allocation.get("expected_move_after_cost_bps"),
        allocation.get("expected_net_edge_bps"),
        allocation_model_inputs.get("expected_move_after_cost_bps"),
        allocation_model_inputs.get("expected_net_edge_bps"),
    )
    selected_action_probability = first_number(
        fill.get("selected_action_probability"),
        fill.get("action_probability"),
        fill.get("probability_selected_action"),
        allocation.get("selected_action_probability"),
        allocation_model_inputs.get("selected_action_probability"),
    )
    policy_value = first_number(
        fill.get("policy_value"),
        fill.get("value_estimate"),
        allocation.get("policy_value"),
        allocation_model_inputs.get("policy_value"),
    )
    value_baseline = first_number(
        fill.get("value_baseline"),
        allocation.get("value_baseline"),
        allocation_model_inputs.get("value_baseline"),
    )
    # PPO on-policy entry lineage: each field is recovered only under its own
    # name from the entry fill record; no cross-field backfill here (the
    # feedback builder owns its own eligibility fallbacks).
    selected_action_log_prob = first_number(
        fill.get("selected_action_log_prob"),
        allocation.get("selected_action_log_prob"),
        allocation_model_inputs.get("selected_action_log_prob"),
    )
    old_log_prob = first_number(
        fill.get("old_log_prob"),
        allocation.get("old_log_prob"),
        allocation_model_inputs.get("old_log_prob"),
    )
    old_value = first_number(
        fill.get("old_value"),
        allocation.get("old_value"),
        allocation_model_inputs.get("old_value"),
    )
    rollout_id = first_present(
        fill.get("rollout_id"),
        allocation.get("rollout_id"),
        allocation_model_inputs.get("rollout_id"),
    )
    trajectory_index_raw = first_number(
        fill.get("trajectory_index"),
        allocation.get("trajectory_index"),
        allocation_model_inputs.get("trajectory_index"),
    )
    ppo_on_policy_entry_fields_present = first_present(
        fill.get("ppo_on_policy_entry_fields_present"),
        allocation.get("ppo_on_policy_entry_fields_present"),
        allocation_model_inputs.get("ppo_on_policy_entry_fields_present"),
    )
    entry_policy_fields_source = first_present(
        fill.get("entry_policy_fields_source"),
        allocation.get("entry_policy_fields_source"),
        allocation_model_inputs.get("entry_policy_fields_source"),
    )
    paper_learning_lane = first_present(
        fill.get("paper_learning_lane"),
        allocation.get("paper_learning_lane"),
        allocation_model_inputs.get("paper_learning_lane"),
    )
    missing_score_fields = [
        field
        for field, value in (
            ("confidence_calibrated", confidence_calibrated),
            ("expected_move_after_cost_bps", expected_move_after_cost_bps),
        )
        if value is None
    ]
    prediction_score_source = (
        "ENTRY_FILL_VERIFIED_PREDICTION_SCORE_FIELDS"
        if not missing_score_fields
        else None
    )
    prediction_score_missing_reason = (
        None
        if not missing_score_fields
        else "MISSING_ENTRY_PREDICTION_SCORE_FIELDS:" + ",".join(missing_score_fields)
    )
    is_hedge_child = bool(fill.get("hedge_intent") is True and fill.get("hedge_parent_id"))
    return PaperNetPosition(
        position_id=f"paper_pos_{symbol}_hedge" if is_hedge_child else f"paper_pos_{symbol}",
        symbol=symbol,
        side=side,
        net_quantity=quantity,
        avg_entry_price=price,
        opened_est=opened,
        source_signal_id=fill.get("signal_id"),
        prediction_id=fill.get("prediction_id") or fill.get("source_prediction_id"),
        preemptive_decision_id=first_present(
            fill.get("preemptive_decision_id"),
            fill.get("runtime_revalidated_preemptive_decision_id"),
            allocation.get("preemptive_decision_id"),
            allocation.get("runtime_revalidated_preemptive_decision_id"),
            allocation_model_inputs.get("preemptive_decision_id"),
            allocation_model_inputs.get("runtime_revalidated_preemptive_decision_id"),
        ),
        risk_decision_id=fill.get("risk_decision_id"),
        orchestrator_decision_id=fill.get("orchestrator_decision_id"),
        allocator_decision_id=allocator_decision_id,
        materialization_queue_id=materialization_queue_id,
        materialization_queue_accepted_at=first_present(
            fill.get("materialization_queue_accepted_at"),
            allocation.get("materialization_queue_accepted_at"),
        ),
        materialization_queue_expires_at=first_present(
            fill.get("materialization_queue_expires_at"),
            allocation.get("materialization_queue_expires_at"),
        ),
        market_state_id=fill.get("market_state_id"),
        trainer_source=fill.get("trainer_source"),
        timeframe=fill.get("timeframe"),
        feature_snapshot_id=(
            fill.get("feature_snapshot_id")
            or fill.get("entry_feature_snapshot_id")
        ),
        decision_id=fill.get("decision_id") or fill.get("orchestrator_decision_id"),
        mtf_snapshot_id=fill.get("mtf_snapshot_id"),
        feature_cutoff=first_present(fill.get("feature_cutoff"), fill.get("entry_feature_cutoff")),
        decision_time=first_present(fill.get("decision_time"), fill.get("entry_feature_decision_time")),
        available_at=first_present(fill.get("available_at"), fill.get("entry_feature_available_at")),
        selected_action=fill.get("selected_action") or fill.get("side") or side,
        model_version=first_present(fill.get("model_version"), fill.get("model_source"), fill.get("model_id")),
        checkpoint_id=fill.get("checkpoint_id"),
        checkpoint_id_source=fill.get("checkpoint_id_source"),
        entry_prediction_snapshot=fill.get("entry_prediction_snapshot")
        if isinstance(fill.get("entry_prediction_snapshot"), dict)
        else None,
        risk_decision_record_key=fill.get("risk_decision_record_key"),
        risk_decision_record_hash=fill.get("risk_decision_record_hash"),
        risk_decision_record_resolved=(
            fill.get("risk_decision_record_resolved")
            if isinstance(fill.get("risk_decision_record_resolved"), bool)
            else None
        ),
        risk_decision_source=fill.get("risk_decision_source"),
        orchestrator_decision_record_key=fill.get("orchestrator_decision_record_key"),
        orchestrator_decision_record_hash=fill.get("orchestrator_decision_record_hash"),
        orchestrator_decision_record_resolved=(
            fill.get("orchestrator_decision_record_resolved")
            if isinstance(fill.get("orchestrator_decision_record_resolved"), bool)
            else None
        ),
        orchestrator_decision_source=fill.get("orchestrator_decision_source"),
        decision_record_missing_reasons=(
            list(fill.get("decision_record_missing_reasons"))
            if isinstance(fill.get("decision_record_missing_reasons"), list)
            else None
        ),
        source_hashes=source_hashes or None,
        feature_vector_hash=feature_vector_hash,
        provider_hashes=dict(provider_hashes) if provider_hashes else None,
        confidence_raw=confidence_raw,
        confidence_calibrated=confidence_calibrated,
        confidence_executable_trade=confidence_executable_trade,
        dynamic_exploration_floor=dynamic_exploration_floor,
        dynamic_exploration_floor_formula=first_present(
            fill.get("dynamic_exploration_floor_formula"),
            allocation.get("dynamic_exploration_floor_formula"),
            allocation_model_inputs.get("dynamic_exploration_floor_formula"),
        ),
        exploration_floor_inputs=exploration_floor_inputs,
        paper_risk_controller_exploration_above_floor=first_present(
            fill.get("paper_risk_controller_exploration_above_floor"),
            fill.get("above_dynamic_floor"),
            allocation.get("paper_risk_controller_exploration_above_floor"),
            allocation.get("above_dynamic_floor"),
            allocation_model_inputs.get("paper_risk_controller_exploration_above_floor"),
            allocation_model_inputs.get("above_dynamic_floor"),
        ),
        paper_risk_controller_exploration_eligible=first_present(
            fill.get("paper_risk_controller_exploration_eligible"),
            allocation.get("paper_risk_controller_exploration_eligible"),
            allocation_model_inputs.get("paper_risk_controller_exploration_eligible"),
        ),
        bootstrap_exploration=first_present(
            fill.get("bootstrap_exploration"),
            allocation.get("bootstrap_exploration"),
            allocation_model_inputs.get("bootstrap_exploration"),
        ),
        bootstrap_overridden_blockers=bootstrap_overridden_blockers,
        selected_action_probability=selected_action_probability,
        expected_move_bps=expected_move_bps,
        action_probabilities=(
            list(action_probabilities)
            if isinstance(action_probabilities, tuple)
            else action_probabilities
        ),
        policy_value=policy_value,
        value_baseline=value_baseline,
        selected_action_log_prob=selected_action_log_prob,
        old_log_prob=old_log_prob,
        old_value=old_value,
        rollout_id=str(rollout_id) if rollout_id is not None else None,
        trajectory_index=(
            int(trajectory_index_raw) if trajectory_index_raw is not None else None
        ),
        ppo_on_policy_entry_fields_present=(
            bool(ppo_on_policy_entry_fields_present)
            if ppo_on_policy_entry_fields_present is not None
            else None
        ),
        entry_policy_fields_source=entry_policy_fields_source,
        paper_learning_lane=paper_learning_lane,
        prediction_score_source=prediction_score_source,
        prediction_score_missing_reason=prediction_score_missing_reason,
        candidate_id=candidate_id,
        paper_policy_owner=first_present(
            fill.get("paper_policy_owner"),
            allocation.get("paper_policy_owner"),
            fill.get("current_allowed_paper_owner"),
            allocation.get("current_allowed_paper_owner"),
        ),
        policy_fingerprint=first_present(
            fill.get("policy_fingerprint"),
            allocation.get("policy_fingerprint"),
            fill.get("selector_policy_fingerprint"),
            allocation.get("selector_policy_fingerprint"),
            fill.get("frozen_selector_fingerprint"),
            allocation.get("frozen_selector_fingerprint"),
        ),
        model_source=first_present(
            fill.get("model_source"),
            allocation.get("model_source"),
            fill.get("model_version"),
            allocation.get("model_version"),
            fill.get("model_id"),
            allocation.get("model_id"),
        ),
        selector_policy_fingerprint=first_present(
            fill.get("selector_policy_fingerprint"),
            allocation.get("selector_policy_fingerprint"),
            allocation_model_inputs.get("selector_policy_fingerprint"),
        ),
        frozen_selector_fingerprint=first_present(
            fill.get("frozen_selector_fingerprint"),
            allocation.get("frozen_selector_fingerprint"),
            allocation_model_inputs.get("frozen_selector_fingerprint"),
        ),
        candidate_selected_before_outcome=fill.get("candidate_selected_before_outcome")
        if isinstance(fill.get("candidate_selected_before_outcome"), bool)
        else allocation.get("candidate_selected_before_outcome")
        if isinstance(allocation.get("candidate_selected_before_outcome"), bool)
        else None,
        candidate_selected_after_outcome=fill.get("candidate_selected_after_outcome")
        if isinstance(fill.get("candidate_selected_after_outcome"), bool)
        else allocation.get("candidate_selected_after_outcome")
        if isinstance(allocation.get("candidate_selected_after_outcome"), bool)
        else None,
        post_outcome_candidate_selection=fill.get("post_outcome_candidate_selection")
        if isinstance(fill.get("post_outcome_candidate_selection"), bool)
        else allocation.get("post_outcome_candidate_selection")
        if isinstance(allocation.get("post_outcome_candidate_selection"), bool)
        else None,
        future_labels_used_as_features=fill.get("future_labels_used_as_features")
        if isinstance(fill.get("future_labels_used_as_features"), bool)
        else allocation.get("future_labels_used_as_features")
        if isinstance(allocation.get("future_labels_used_as_features"), bool)
        else None,
        paper_opportunity_tier=paper_opportunity_tier,
        paper_opportunity_tier_reason=first_present(
            fill.get("paper_opportunity_tier_reason"),
            allocation.get("paper_opportunity_tier_reason"),
        ),
        explicit_paper_opportunity_tier=first_present(
            fill.get("explicit_paper_opportunity_tier"),
            allocation.get("explicit_paper_opportunity_tier"),
        ),
        paper_fill_allowed_source=first_present(
            fill.get("paper_fill_allowed_source"),
            allocation.get("paper_fill_allowed_source"),
        ),
        strict_paper_fill_allowed_upstream=fill.get("strict_paper_fill_allowed_upstream")
        if isinstance(fill.get("strict_paper_fill_allowed_upstream"), bool)
        else allocation.get("strict_paper_fill_allowed_upstream")
        if isinstance(allocation.get("strict_paper_fill_allowed_upstream"), bool)
        else None,
        calibration_label_purpose=first_present(fill.get("calibration_label_purpose"), allocation.get("calibration_label_purpose")),
        entry_market_state_id=fill.get("market_state_id"),
        strategy_id=fill.get("strategy_id") or fill.get("strategy_selected_mode"),
        strategy_family=fill.get("strategy_family") or fill.get("strategy_selected_mode"),
        strategy_selected_mode=fill.get("strategy_selected_mode"),
        hedge_state=fill.get("hedge_state") or "NO_HEDGE",
        hedge_reason=fill.get("hedge_reason") or "NO_HEDGE_CONTEXT",
        hedge_parent_id=(
            str(fill.get("hedge_parent_id"))
            if fill.get("hedge_intent") is True and fill.get("hedge_parent_id")
            else None
        ),
        hedge_child_id=(
            str(fill.get("hedge_child_id"))
            if fill.get("hedge_intent") is True and fill.get("hedge_child_id")
            else None
        ),
        hedge_ratio=(
            coerce_float(fill.get("hedge_ratio"))
            if fill.get("hedge_intent") is True
            else None
        ),
        hedge_entry_parent_pnl_bps=(
            coerce_float(fill.get("hedge_entry_parent_pnl_bps"))
            if fill.get("hedge_intent") is True
            else None
        ),
        drawdown_at_entry=first_present(fill.get("drawdown_at_entry"), fill.get("drawdown_bps")),
        market_regime_at_entry=",".join(str(item) for item in fill.get("strategy_regime_labels") or [])
        if isinstance(fill.get("strategy_regime_labels"), list)
        else fill.get("market_regime_at_entry"),
        liquidity_zone_context=fill.get("liquidity_zone_context"),
        liquidation_distance_context=fill.get("liquidation_distance_context"),
        microstructure_context=fill.get("microstructure_context"),
        oi_funding_context=fill.get("oi_funding_context"),
        public_intel_context=fill.get("public_intel_context"),
        major_move_signal_id=fill.get("major_move_signal_id"),
        squeeze_evidence_score=squeeze_score,
        squeeze_evidence_source=fill.get("squeeze_evidence_source"),
        squeeze_evidence_components=fill.get("squeeze_evidence_components")
        if isinstance(fill.get("squeeze_evidence_components"), dict)
        else None,
        squeeze_evidence_unavailable_reason=(
            fill.get("squeeze_evidence_unavailable_reason")
            if fill.get("squeeze_evidence_unavailable_reason")
            else (None if squeeze_score is not None else "MISSING_ENTRY_SQUEEZE_EVIDENCE_SCORE")
        ),
        future_window_label_source=fill.get("future_window_label_source"),
        adaptive_allocation=dict(allocation) if allocation else None,
        adaptive_capital_policy_version=adaptive_capital_policy_version,
        policy_activated_at=policy_activated_at,
        gross_notional_usd=gross_notional,
        allocated_margin_usd=allocated_margin,
        effective_leverage=effective_leverage,
        recommended_leverage=recommended_leverage,
        recommended_margin_mode=recommended_margin_mode,
        margin_mode_simulated=str(
            first_present(
                fill.get("margin_mode_simulated"),
                recommended_margin_mode,
                "isolated_paper_simulated",
            )
        ),
        maintenance_margin_estimate=maintenance_margin,
        liquidation_price_estimate=first_number(
            fill.get("liquidation_price_estimate"),
            allocation.get("liquidation_price_estimate"),
            _liquidation_estimate(
                side=side,
                entry_price=price,
                leverage=effective_leverage,
                maintenance_rate=max(0.0, maintenance_rate),
            ),
        ),
        liquidation_buffer_bps=first_number(fill.get("liquidation_buffer_bps"), allocation.get("liquidation_buffer_bps")),
        risk_budget_usd=risk_budget,
        risk_budget_source=risk_budget_source or ("provided" if risk_budget is not None else None),
        stop_distance_bps=first_number(fill.get("stop_distance_bps"), allocation.get("stop_distance_bps")),
        expected_fees_usd=expected_fees_usd,
        expected_funding_bps=expected_funding_bps,
        funding_rate=funding_rate,
        funding_interval_seconds=funding_interval_seconds,
        expected_funding_usd=expected_funding_usd,
        expected_net_pnl_usd=expected_net_pnl_usd,
        expected_max_loss_usd=first_number(
            fill.get("expected_max_loss_usd"),
            fill.get("max_loss_if_stop_hit"),
            allocation.get("expected_max_loss_usd"),
            allocation.get("max_loss_if_stop_hit"),
        ),
        expected_shortfall_usd=expected_shortfall_usd,
        hedge_budget_usd=hedge_budget_usd,
        capital_allocation_reason=first_present(
            fill.get("capital_allocation_reason"),
            allocation.get("capital_allocation_reason"),
            allocation.get("final_size_reason"),
        ),
        entry_atr_bps=atr_bps_from_payloads(fill, features, price=price),
        entry_feature_available_at=fill.get("entry_feature_available_at"),
        entry_feature_generated_at=fill.get("entry_feature_generated_at"),
        entry_feature_cutoff=fill.get("entry_feature_cutoff"),
        entry_feature_decision_time=fill.get("entry_feature_decision_time"),
        entry_feature_source=fill.get("entry_feature_source"),
        entry_feature_candle_closed_confirmed=(
            fill.get("entry_feature_candle_closed_confirmed")
            if isinstance(fill.get("entry_feature_candle_closed_confirmed"), bool)
            else None
        ),
        entry_feature_unavailable_reason=fill.get("entry_feature_unavailable_reason"),
        entry_feature_snapshot=fill.get("entry_feature_snapshot")
        if isinstance(fill.get("entry_feature_snapshot"), dict)
        else None,
        entry_observed_spread_bps=entry_spread,
        entry_spread_source=(
            str(first_present(fill.get("entry_spread_source"), micro.get("source"), "V2_ENTRY_MICROSTRUCTURE_CONTEXT"))
            if entry_spread is not None
            else None
        ),
        entry_spread_unavailable_reason=(
            None if entry_spread is not None else "MISSING_ENTRY_OBSERVED_SPREAD_BPS"
        ),
        observed_bid=first_number(fill.get("observed_bid"), fill.get("best_bid")),
        observed_ask=first_number(fill.get("observed_ask"), fill.get("best_ask")),
        observed_spread_bps=first_number(fill.get("observed_spread_bps"), entry_spread),
        order_size=first_number(fill.get("order_size"), fill.get("notional"), fill.get("notional_usdt")),
        order_size_usd=first_number(fill.get("order_size_usd"), fill.get("order_size"), fill.get("notional")),
        top_book_bid_depth_usd=first_number(fill.get("top_book_bid_depth_usd"), fill.get("bid_depth_usd")),
        top_book_ask_depth_usd=first_number(fill.get("top_book_ask_depth_usd"), fill.get("ask_depth_usd")),
        depth_derived_price_impact_bps=first_number(
            fill.get("depth_derived_price_impact_bps"),
            fill.get("depth_price_impact_bps"),
        ),
        bid_depth_usd=first_number(fill.get("bid_depth_usd")),
        ask_depth_usd=first_number(fill.get("ask_depth_usd")),
        orderbook_depth_usd=first_number(fill.get("orderbook_depth_usd")),
        entry_orderbook_depth_usd=first_number(fill.get("entry_orderbook_depth_usd")),
        entry_orderbook_depth_side=fill.get("entry_orderbook_depth_side"),
        top_of_book_depth_usd=first_number(fill.get("top_of_book_depth_usd")),
        market_depth_usd=first_number(fill.get("market_depth_usd")),
        orderbook_depth_source=fill.get("orderbook_depth_source"),
        depth_utilization_pct=first_number(fill.get("depth_utilization_pct")),
        depth_price_impact_bps=first_number(fill.get("depth_price_impact_bps")),
        depth_price_impact_source=fill.get("depth_price_impact_source"),
        depth_price_impact_model=fill.get("depth_price_impact_model"),
        depth_price_impact_side=fill.get("depth_price_impact_side"),
        depth_price_impact_quantity=first_number(fill.get("depth_price_impact_quantity")),
        depth_price_impact_filled_quantity=first_number(fill.get("depth_price_impact_filled_quantity")),
        depth_price_impact_fill_complete=fill.get("depth_price_impact_fill_complete")
        if isinstance(fill.get("depth_price_impact_fill_complete"), bool)
        else None,
        depth_price_impact_vwap=first_number(fill.get("depth_price_impact_vwap")),
        depth_price_impact_touch_price=first_number(fill.get("depth_price_impact_touch_price")),
        expected_slippage_bps=expected_slippage_bps,
        expected_slippage_usd=expected_slippage_usd,
        expected_slippage_source=fill.get("expected_slippage_source"),
        expected_slippage_modeled=fill.get("expected_slippage_modeled")
        if isinstance(fill.get("expected_slippage_modeled"), bool)
        else None,
        expected_slippage_unavailable_reason=fill.get("expected_slippage_unavailable_reason"),
        correlation_exposure_pct=correlation_exposure_pct,
        correlation_input_source=correlation_input_source,
        correlation_input_status=correlation_input_status,
        correlation_pair_count=correlation_pair_count,
        correlation_diagnostics=fill.get("correlation_diagnostics")
        if isinstance(fill.get("correlation_diagnostics"), dict)
        else None,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
        decision_latency_ms=first_number(fill.get("decision_latency_ms"), fill.get("latency_ms")),
        latency_source=fill.get("latency_source"),
        latency_reserve_bps=first_number(fill.get("latency_reserve_bps")),
        latency_reserve_source=fill.get("latency_reserve_source"),
        maker_taker_assumption=fill.get("maker_taker_assumption"),
        maker_probability=first_number(fill.get("maker_probability")),
        taker_probability=first_number(fill.get("taker_probability")),
        maker_taker_probability=first_number(fill.get("maker_taker_probability")),
        maker_taker_probability_detail=fill.get("maker_taker_probability_detail")
        if isinstance(fill.get("maker_taker_probability_detail"), dict)
        else None,
        maker_taker_probabilities=fill.get("maker_taker_probabilities")
        if isinstance(fill.get("maker_taker_probabilities"), dict)
        else None,
        maker_taker_probability_source=fill.get("maker_taker_probability_source"),
        fee_schedule=fill.get("fee_schedule") if isinstance(fill.get("fee_schedule"), dict) else None,
        fee_bps=first_number(fill.get("fee_bps")),
        fee_bps_source=fill.get("fee_bps_source"),
        fee_bps_configured_schedule=fill.get("fee_bps_configured_schedule")
        if isinstance(fill.get("fee_bps_configured_schedule"), bool)
        else None,
        holding_period_funding_bps=first_number(fill.get("holding_period_funding_bps")),
        holding_period_funding_source=fill.get("holding_period_funding_source"),
        partial_fill_count=int(first_number(fill.get("partial_fill_count"), fill.get("fill_count")) or 0)
        if first_number(fill.get("partial_fill_count"), fill.get("fill_count")) is not None
        else None,
        partial_fill_estimate=fill.get("partial_fill_estimate")
        if isinstance(fill.get("partial_fill_estimate"), dict)
        else None,
        partial_fill_probability=first_number(fill.get("partial_fill_probability")),
        partial_fill_adjustment_bps=first_number(fill.get("partial_fill_adjustment_bps")),
        partial_fills=fill.get("partial_fills") if isinstance(fill.get("partial_fills"), list) else None,
        fill_count=int(first_number(fill.get("fill_count"), fill.get("partial_fill_count")) or 0)
        if first_number(fill.get("fill_count"), fill.get("partial_fill_count")) is not None
        else None,
        all_partial_fills=fill.get("all_partial_fills") if isinstance(fill.get("all_partial_fills"), list) else None,
        partial_fill_plan=fill.get("partial_fill_plan")
        if isinstance(fill.get("partial_fill_plan"), (dict, list))
        else None,
        execution_probability=first_number(fill.get("execution_probability")),
        mark_index_divergence_bps=first_number(fill.get("mark_index_divergence_bps")),
        mark_index_divergence=first_number(fill.get("mark_index_divergence")),
        mark_index_source=fill.get("mark_index_source"),
        mark_index_available_at=fill.get("mark_index_available_at"),
        mark_price=first_number(fill.get("mark_price")),
        index_price=first_number(fill.get("index_price")),
        cost_source=fill.get("cost_source"),
        cost_source_timestamp=fill.get("cost_source_timestamp"),
        source_timestamp=fill.get("source_timestamp"),
        cost_evidence_freshness_ms=first_number(fill.get("cost_evidence_freshness_ms")),
        cost_evidence_source_fields=fill.get("cost_evidence_source_fields")
        if isinstance(fill.get("cost_evidence_source_fields"), dict)
        else None,
        runtime_cost_capture_source=fill.get("runtime_cost_capture_source"),
        runtime_cost_capture_status=fill.get("runtime_cost_capture_status"),
        runtime_cost_capture_required_fields=list(fill.get("runtime_cost_capture_required_fields"))
        if isinstance(fill.get("runtime_cost_capture_required_fields"), list)
        else None,
        runtime_cost_capture_missing_fields=list(fill.get("runtime_cost_capture_missing_fields"))
        if isinstance(fill.get("runtime_cost_capture_missing_fields"), list)
        else None,
        runtime_cost_capture_explained_missing_fields=list(fill.get("runtime_cost_capture_explained_missing_fields"))
        if isinstance(fill.get("runtime_cost_capture_explained_missing_fields"), list)
        else None,
        runtime_cost_capture_unexplained_missing_fields=list(fill.get("runtime_cost_capture_unexplained_missing_fields"))
        if isinstance(fill.get("runtime_cost_capture_unexplained_missing_fields"), list)
        else None,
        runtime_cost_capture_order_cost_applicable=fill.get("runtime_cost_capture_order_cost_applicable")
        if isinstance(fill.get("runtime_cost_capture_order_cost_applicable"), bool)
        else None,
        runtime_cost_capture_no_order_reason=fill.get("runtime_cost_capture_no_order_reason"),
        runtime_cost_capture_temporal_reject_reasons=list(fill.get("runtime_cost_capture_temporal_reject_reasons"))
        if isinstance(fill.get("runtime_cost_capture_temporal_reject_reasons"), list)
        else None,
        fallback_cost_flag=fill.get("fallback_cost_flag")
        if isinstance(fill.get("fallback_cost_flag"), bool)
        else None,
        fallback=fill.get("fallback") if isinstance(fill.get("fallback"), bool) else None,
        production_grade_cost_flag=fill.get("production_grade_cost_flag")
        if isinstance(fill.get("production_grade_cost_flag"), bool)
        else None,
        production_grade_cost_evidence=fill.get("production_grade_cost_evidence")
        if isinstance(fill.get("production_grade_cost_evidence"), bool)
        else None,
        estimated_production_cost=first_number(fill.get("estimated_production_cost")),
        estimated_production_cost_bps=first_number(fill.get("estimated_production_cost_bps")),
        counts_as_production_grade_training_evidence=fill.get("counts_as_production_grade_training_evidence")
        if isinstance(fill.get("counts_as_production_grade_training_evidence"), bool)
        else None,
        fill_ids=[fill_id],
        best_favorable_price=price,
        worst_adverse_price=price,
        intra_trade_high_price=price,
        intra_trade_low_price=price,
        last_mark_price=price,
        last_mark_est=opened,  # initial mark uses same EST-converted open time
    )
