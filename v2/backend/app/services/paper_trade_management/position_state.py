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
    risk_decision_id: str | None = None
    orchestrator_decision_id: str | None = None
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
    source_hashes: dict[str, Any] | None = None
    entry_market_state_id: str | None = None
    strategy_id: str | None = None
    strategy_family: str | None = None
    strategy_selected_mode: str | None = None
    hedge_state: str | None = None
    hedge_reason: str | None = None
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
    entry_observed_spread_bps: float | None = None
    entry_spread_source: str | None = None
    entry_spread_unavailable_reason: str | None = None
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
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "net_quantity": round(self.net_quantity, 12),
            "avg_entry_price": self.avg_entry_price,
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
            "opened_est": self.opened_est,
            "last_mark_est": self.last_mark_est,
            "last_mark_price": self.last_mark_price,
            "unrealized_pnl": self.unrealized_pnl(),
            "unrealized_pnl_bps": self.unrealized_pnl_bps(),
            "realized_pnl": self.realized_pnl,
            "source_signal_id": self.source_signal_id,
            "prediction_id": self.prediction_id,
            "risk_decision_id": self.risk_decision_id,
            "orchestrator_decision_id": self.orchestrator_decision_id,
            "market_state_id": self.market_state_id,
            "entry_market_state_id": self.entry_market_state_id or self.market_state_id,
            "trainer_source": self.trainer_source,
            "timeframe": self.timeframe,
            "feature_snapshot_id": self.feature_snapshot_id,
            "decision_id": self.decision_id,
            "mtf_snapshot_id": self.mtf_snapshot_id,
            "feature_cutoff": self.feature_cutoff,
            "decision_time": self.decision_time,
            "available_at": self.available_at,
            "selected_action": self.selected_action or self.side,
            "model_version": self.model_version,
            "checkpoint_id": self.checkpoint_id,
            "source_hashes": self.source_hashes,
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_selected_mode": self.strategy_selected_mode,
            "hedge_state": self.hedge_state,
            "hedge_reason": self.hedge_reason,
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
            "entry_spread_source": self.entry_spread_source,
            "entry_spread_unavailable_reason": self.entry_spread_unavailable_reason,
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
            "source_fill_ids": list(self.fill_ids),
            "best_favorable_price": self.best_favorable_price,
            "worst_adverse_price": self.worst_adverse_price,
            "position_age_seconds": seconds_between(self.opened_est, generated_utc),
            "position_state": "OPEN_POSITION",
            "paper_fill_allowed": True,
            "decision": "ACCEPTED_PAPER_FILL",
            "paper_only": True,
            "places_real_order": False,
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
    return PaperNetPosition(
        position_id=f"paper_pos_{symbol}",
        symbol=symbol,
        side=side,
        net_quantity=quantity,
        avg_entry_price=price,
        opened_est=opened,
        source_signal_id=fill.get("signal_id"),
        prediction_id=fill.get("prediction_id") or fill.get("source_prediction_id"),
        risk_decision_id=fill.get("risk_decision_id"),
        orchestrator_decision_id=fill.get("orchestrator_decision_id"),
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
        source_hashes=source_hashes or None,
        entry_market_state_id=fill.get("market_state_id"),
        strategy_id=fill.get("strategy_id") or fill.get("strategy_selected_mode"),
        strategy_family=fill.get("strategy_family") or fill.get("strategy_selected_mode"),
        strategy_selected_mode=fill.get("strategy_selected_mode"),
        hedge_state=fill.get("hedge_state") or "NO_HEDGE",
        hedge_reason=fill.get("hedge_reason") or "NO_HEDGE_CONTEXT",
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
        entry_observed_spread_bps=entry_spread,
        entry_spread_source=(
            str(first_present(fill.get("entry_spread_source"), micro.get("source"), "V2_ENTRY_MICROSTRUCTURE_CONTEXT"))
            if entry_spread is not None
            else None
        ),
        entry_spread_unavailable_reason=(
            None if entry_spread is not None else "MISSING_ENTRY_OBSERVED_SPREAD_BPS"
        ),
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
        expected_move_after_cost_bps=first_number(fill.get("expected_move_after_cost_bps")),
        decision_latency_ms=first_number(fill.get("decision_latency_ms"), fill.get("latency_ms")),
        fill_ids=[fill_id],
        best_favorable_price=price,
        worst_adverse_price=price,
        intra_trade_high_price=price,
        intra_trade_low_price=price,
        last_mark_price=price,
        last_mark_est=opened,  # initial mark uses same EST-converted open time
    )
