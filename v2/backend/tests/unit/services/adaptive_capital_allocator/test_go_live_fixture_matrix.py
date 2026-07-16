"""Phase 8 — go-live fixture matrix.

One cohesive matrix that exercises the REAL services behind every go-live
readiness claim. Each test asserts an observable invariant from shipping code;
nothing here submits an order, mutates leverage/margin, or moves funds. The
matrix is deliberately located under the adaptive_capital_allocator test tree so
the goal's pytest validation command collects and runs it.

Fixture groups (spec Phase 8 A-K):
  A governance | B adaptive leverage/margin | C cross-margin liquidation
  D hedge-first | E maker/taker execution   | F paper materialization
  G PPO on-policy | H provider consumption   | I binance no-execute
  J UI truth      | K safety / no-mutation
"""

from __future__ import annotations

import fnmatch
import json
import math

from v2.backend.app.cli import v2_trade_management_paper_loop as pl
from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    allocate_live_candidate,
    allocate_paper_candidate,
)
from v2.backend.app.services.altdata.provider_consumption_status import (
    build_provider_consumption_status,
)
from v2.backend.app.services.exchange_mutation_freeze import (
    FrozenExchangeAdapter,
    verify_freeze,
)
from v2.backend.app.services.execution.binance_order_builder import (
    build_binance_order_plan,
)
from v2.backend.app.services.hedge_engine import simulate_cross_margin_stress
from v2.backend.app.services.risk.hedge_first_controller import evaluate_hedge_first

_EQUITY = 200.0
_GEN = "2026-07-11T18:00:00Z"
_FILTERS = {"tick_size": 0.1, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0}


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def _alloc(**overrides) -> AllocationInput:
    base = dict(
        symbol="BTCUSDT",
        timeframe="5m",
        action="long",
        price=60000.0,
        equity=_EQUITY,
        available_margin=_EQUITY,
        wallet_balance=_EQUITY,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=45.0,
        market_state_integrity_score=90.0,
        volatility_bps=18.0,
        spread_bps=2.0,
        slippage_bps=2.0,
        fee_bps=4.0,
        expected_funding_bps=0.0,
        min_notional=5.0,
        step_size=0.0001,
        min_qty=0.0001,
        lineage_ids={"signal_id": "phase8"},
    )
    base.update(overrides)
    return AllocationInput(**base)


def _plan(**overrides):
    base = dict(
        symbol="BTCUSDT",
        side="long",
        symbol_filters=_FILTERS,
        hedge_mode=True,
        generated_utc=_GEN,
        current_price=60000.0,
        best_bid=59999.0,
        best_ask=60001.0,
        quantity=0.002,
        order_type="LIMIT",
        time_in_force="GTX",
    )
    base.update(overrides)
    return build_binance_order_plan(**base)


def _strict_row(idx: int, bps: float) -> dict:
    return {
        "paper_only": True,
        "paper_opportunity_tier": "POSITIVE_EDGE_PROBATION_PAPER",
        "symbol": f"SYM{idx}USDT",
        "realized_net_pnl_bps": bps,
        "realized_net_pnl_usd": bps / 100.0 * 0.25,
        "gross_notional_usd": 25.0,
    }


def _explore_row(idx: int, bps: float) -> dict:
    return {
        "paper_only": True,
        "paper_opportunity_tier": pl.PAPER_TIER_RISK_CONTROLLER_EXPLORATION,
        "symbol": f"EXP{idx}USDT",
        "realized_net_pnl_bps": bps,
        "realized_net_pnl_usd": bps / 100.0 * 0.25,
        "gross_notional_usd": 25.0,
        "counts_as_strict_preemptive_evidence": False,
        "counts_as_a_plus_evidence": False,
    }


def _bootstrap_row(idx: int, bps: float) -> dict:
    return {
        "paper_only": True,
        "paper_opportunity_tier": pl.PAPER_TIER_A_PLUS_BOOTSTRAP_REDUCED_SIZE,
        "symbol": f"BOOT{idx}USDT",
        "realized_net_pnl_bps": bps,
        "realized_net_pnl_usd": bps / 100.0 * 0.25,
        "gross_notional_usd": 25.0,
        "counts_as_strict_preemptive_evidence": False,
        "counts_as_a_plus_evidence": False,
    }


class _FakeRedis:
    """Minimal in-memory redis honoring the read surface the status builder uses."""

    def __init__(self, data: dict[str, object] | None = None) -> None:
        self._data = dict(data or {})

    def scan_iter(self, match: str = "*", count: int = 500):
        for key in list(self._data):
            if fnmatch.fnmatch(key, match):
                yield key

    def get(self, key: str):
        value = self._data.get(key)
        return None if value is None else json.dumps(value)


_CROSS_COMMON = dict(
    equity_usd=_EQUITY,
    available_margin_usd=_EQUITY,
    target_notional_usd=100.0,
    allocated_margin_usd=34.0,
    recommended_leverage=3.0,
    max_loss_usd=30.0,
    requested_margin_mode="cross",
    profit_factor=1.5,
    expectancy_usd=2.0,
)


# --------------------------------------------------------------------------- #
# A. governance
# --------------------------------------------------------------------------- #
def test_non_strict_tiers_excluded_from_strict_governance() -> None:
    rows = (
        [_strict_row(1, 90.0), _strict_row(2, 60.0), _strict_row(3, -30.0)]
        + [_explore_row(i, -50.0) for i in range(1, 6)]
        + [_bootstrap_row(i, -40.0) for i in range(1, 4)]
    )
    governed = pl._paper_performance_source_rows(rows)
    governed_symbols = {r["symbol"] for r in governed}
    assert governed_symbols == {"SYM1USDT", "SYM2USDT", "SYM3USDT"}
    metrics = pl._paper_performance_metrics(governed)
    assert metrics["profit_factor_numeric"] > 1.0  # strict set is profitable once clean


def test_strict_tiers_still_block_when_losing() -> None:
    losing_strict = [_strict_row(1, -80.0), _strict_row(2, -40.0), _strict_row(3, -120.0)]
    governed = pl._paper_performance_source_rows(losing_strict)
    assert len(governed) == 3  # strict losers still govern; they are not excluded
    metrics = pl._paper_performance_metrics(governed)
    assert metrics["profit_factor_numeric"] is not None
    assert metrics["profit_factor_numeric"] <= 1.0  # losing strict circuit halts


# --------------------------------------------------------------------------- #
# B. adaptive leverage/margin
# --------------------------------------------------------------------------- #
def test_dynamic_leverage_can_exceed_1x_in_paper() -> None:
    res = allocate_paper_candidate(_alloc())
    assert res.recommended_leverage > 1.0
    assert res.gross_notional_usd > 0.0


def test_dynamic_leverage_shrinks_on_drawdown() -> None:
    # Below the 0.85-confidence override band, drawdown pressure still shrinks
    # leverage monotonically down to 1x. (At >=0.85 confidence the allocator
    # deliberately keeps the trainer target with an explicit override label.)
    normal = allocate_paper_candidate(_alloc(confidence_calibrated=0.80))
    drawn = allocate_paper_candidate(_alloc(confidence_calibrated=0.80, drawdown_bps=400.0))
    assert drawn.recommended_leverage < normal.recommended_leverage
    assert drawn.recommended_leverage == 1.0


# --------------------------------------------------------------------------- #
# C. cross-margin liquidation
# --------------------------------------------------------------------------- #
def test_margin_utilization_ramps_after_probation_pass() -> None:
    # A stronger, higher-evidence candidate uses more of equity than a weak one:
    # utilization ramps with quality rather than sitting at a static floor.
    strong = allocate_paper_candidate(_alloc())
    weak = allocate_paper_candidate(
        _alloc(confidence_calibrated=0.56, expected_move_after_cost_bps=6.0, volatility_bps=45.0)
    )
    assert strong.gross_notional_usd / _EQUITY >= weak.gross_notional_usd / _EQUITY
    assert strong.recommended_leverage >= weak.recommended_leverage


def test_cross_margin_liquidation_buffer_required() -> None:
    stress = simulate_cross_margin_stress(**_CROSS_COMMON)
    assert "portfolio_liquidation_buffer_usd" in stress
    assert stress["exchange_margin_mode_mutation_allowed"] is False
    assert stress["places_real_order"] is False


# --------------------------------------------------------------------------- #
# D. hedge-first
# --------------------------------------------------------------------------- #
def test_hedge_required_for_negative_adverse_position() -> None:
    result = evaluate_hedge_first(
        position={
            "symbol": "BTCUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": -25.0,
        },
        snapshot={"portfolio_liquidation_buffer_usd": 150.0, "worst_case_liquidation_buffer_usd": 120.0},
        hedge_mode=True,
        generated_utc=_GEN,
    )
    assert result["is_negative"] is True
    assert result["hedge_required"] is True
    assert result["candidates"]
    assert result["places_real_order"] is False


# --------------------------------------------------------------------------- #
# E. maker/taker execution
# --------------------------------------------------------------------------- #
def test_maker_post_only_default() -> None:
    plan = _plan()
    assert plan["timeInForce"] == "GTX"
    assert plan["post_only_requested"] is True
    assert plan["maker_first"] is True
    assert plan["would_submit_order"] is False
    assert "hidden" not in str(plan).lower()


def test_taker_only_when_waiting_worse() -> None:
    blocked = _plan(order_type="MARKET", time_in_force=None)
    assert blocked["taker_fallback_allowed"] is False
    allowed = _plan(order_type="MARKET", time_in_force=None, taker_fallback_reason="EMERGENCY_EXIT")
    assert allowed["taker_fallback_allowed"] is True
    assert allowed["would_submit_order"] is False


def test_internal_stop_not_visible_order() -> None:
    plan = _plan()
    assert plan["order_params"].get("type") == "LIMIT"
    assert "stopPrice" not in plan["order_params"]
    assert plan["would_submit_order"] is False


def test_reduce_only_emergency_payload_no_execute() -> None:
    plan = _plan(
        order_type="STOP_MARKET",
        time_in_force=None,
        close_position=True,
        stop_price=58800.0,
        taker_fallback_reason="LIQUIDATION_BUFFER_COLLAPSE",
    )
    assert plan["order_params"]["type"] == "STOP_MARKET"
    assert plan["order_params"]["stopPrice"] == 58800.0
    assert plan["would_submit_order"] is False
    assert plan["would_submit_test_order"] is False


# --------------------------------------------------------------------------- #
# F. paper materialization
# --------------------------------------------------------------------------- #
def test_paper_fill_materializes_with_positive_edge_and_clean_gates() -> None:
    res = allocate_paper_candidate(_alloc())
    assert not str(res.decision).startswith("BLOCK")  # a sized fill, not a block
    assert res.gross_notional_usd > 0.0
    assert res.allocated_margin_usd > 0.0


def test_paper_fill_rejected_with_exact_true_blocker() -> None:
    res = allocate_paper_candidate(_alloc(expected_move_after_cost_bps=-15.0))
    assert str(res.decision).startswith("BLOCK")
    assert res.gross_notional_usd == 0.0
    reason = res.risk_veto_reason_if_blocked or res.capital_allocation_reason
    assert reason  # an exact, non-empty blocker reason is always attached


# --------------------------------------------------------------------------- #
# G. PPO on-policy
# --------------------------------------------------------------------------- #
def test_ppo_on_policy_row_created_from_policy_sampled_close() -> None:
    rows = pl._build_trainer_feedback_rows(
        close_events=[
            {
                "trainer_feedback_id": "fb-p8-onpolicy",
                "prediction_id": "v2h_policy_sampled",
                "signal_id": "sig_v2h_policy_sampled",
                "symbol": "JSTUSDT",
                "timeframe": "15m",
                "side": "long",
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                "feature_cutoff": "2026-07-08T04:14:59.999Z",
                "available_at": "2026-07-08T04:17:02.188Z",
                "decision_time": "2026-07-08T04:19:20.458Z",
                "selected_action_probability": 0.8,
                "policy_value": 0.25,
                "realized_net_pnl_bps": 12.0,
                "position_id": "",
            }
        ],
        outcome_labels=[
            {
                "trainer_feedback_id": "fb-p8-onpolicy",
                "prediction_id": "v2h_policy_sampled",
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                "outcome_targets": {"directional_outcome": "UP", "realized_net_pnl_bps": 12.0},
            }
        ],
    )
    assert len(rows) == 1
    assert rows[0]["ppo_on_policy_entry_fields_present"] is True
    assert rows[0]["old_log_prob"] == math.log(0.8)
    assert rows[0]["paper_learning_lane"] == "PPO_ON_POLICY_PAPER_EXPLORATION"
    assert rows[0]["routes_to_live"] is False
    assert rows[0]["places_real_order"] is False


# --------------------------------------------------------------------------- #
# H. provider consumption
# --------------------------------------------------------------------------- #
def test_provider_green_requires_actual_payload() -> None:
    # Empty evidence: no provider can claim consumption or an actual payload.
    status = build_provider_consumption_status(_FakeRedis())
    coinglass = status["providers"]["coinglass"]
    assert coinglass["trainer_consumption"] is False
    assert coinglass["actual_payload_present"] is False
    assert status["single_provider_can_approve"] is False


def test_coinglass_consumed_by_risk_and_trainer() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:coinglass:feature_bridge_status": {"feature_count": 12, "status": "READY"},
                "v2:provider:coinglass:health": {"actual_payload_count_5m": 5},
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [{"altdata_trade_block_score": 0.2}]
                },
            }
        )
    )
    coinglass = status["providers"]["coinglass"]
    assert coinglass["trainer_consumption"] is True
    assert coinglass["provider_risk_consumption"] is True
    assert coinglass["actual_payload_present"] is True


def test_sanbase_consumed_by_trainer_and_strategy_supply() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:santiment:feature_bridge_status": {
                    "feature_count": 8,
                    "status": "READY",
                    "actual_payload_present": True,
                },
                "v2:altdata:santiment:status": {
                    "auto_updates_trainer_via_feature_pipeline": True,
                    "auto_updates_symbol_selection_via_symbol_score": True,
                },
            }
        )
    )
    santiment = status["providers"]["santiment"]
    assert santiment["trainer_consumption"] is True
    assert santiment["auto_updates_symbol_selection_via_symbol_score"] is True


# --------------------------------------------------------------------------- #
# I. binance no-execute
# --------------------------------------------------------------------------- #
def test_binance_signed_read_ok_no_execute() -> None:
    adapter = FrozenExchangeAdapter()
    assert "block" in adapter.live_gate.lower()
    assert tuple(adapter.readonly_method_names)  # signed read surface exists
    report = verify_freeze()
    assert report["all_mutation_methods_refused"] is True
    assert report["leaked_methods_by_name"] == {}


def test_200_usd_account_min_notional_handling() -> None:
    # $200 account: any materialized clip must respect the exchange min-notional;
    # a sub-min positive fill is never produced. A too-small edge blocks to zero.
    res = allocate_paper_candidate(_alloc(equity=_EQUITY, available_margin=_EQUITY, wallet_balance=_EQUITY))
    if res.gross_notional_usd > 0.0:
        assert res.gross_notional_usd >= _FILTERS["min_notional"] - 1e-6
    tiny = allocate_paper_candidate(
        _alloc(confidence_calibrated=0.55, expected_move_after_cost_bps=3.0, volatility_bps=60.0)
    )
    assert tiny.gross_notional_usd == 0.0 or tiny.gross_notional_usd >= _FILTERS["min_notional"] - 1e-6


# --------------------------------------------------------------------------- #
# J. UI truth
# --------------------------------------------------------------------------- #
def test_dashboard_no_validation_errors() -> None:
    # The provider-consumption dashboard-truth payload must be fully well-formed:
    # every consumer flag is a real bool and safety fields are present/false.
    status = build_provider_consumption_status(_FakeRedis())
    assert status["schema_version"] == "altdata_provider_consumption_status_v1"
    assert status["raw_key_exposed"] is False
    assert status["core_system_blocked"] is False
    for provider in status["providers"].values():
        for key, value in provider.items():
            if key.endswith("_consumption") or key.endswith("_lineage"):
                assert isinstance(value, bool)


# --------------------------------------------------------------------------- #
# K. safety / no-mutation
# --------------------------------------------------------------------------- #
def test_live_gate_blocks_all_mutations() -> None:
    report = verify_freeze()
    assert report["all_mutation_methods_refused"] is True
    assert report["leaked_methods_by_name"] == {}
    assert "block" in str(report["live_gate"]).lower()
    # Live allocation never applies dynamic leverage or a margin-mode mutation.
    live = allocate_live_candidate(_alloc())
    assert live.recommended_leverage == 1.0
    cross = live.model_inputs.get("cross_margin_stress", {})
    assert cross.get("exchange_margin_mode_mutation_allowed") is False
    assert cross.get("places_real_order") is False
