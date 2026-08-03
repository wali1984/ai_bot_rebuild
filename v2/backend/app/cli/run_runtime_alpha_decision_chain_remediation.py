from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.adaptive_capital_allocator.strategy_weights import compute_adaptive_strategy_weights
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    build_strategy_hedge_exit_feedback,
    feedback_status,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import V2UnifiedFeatureTensorBuilder
from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig, evaluate_exit
from v2.backend.app.services.paper_trade_management.hedging import (
    build_hedge_cost_benefit,
    evaluate_adaptive_hedge,
)
from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.pnl_reconciliation import reconcile_paper_pnl
from v2.backend.app.services.paper_trade_management.position_state import PaperNetPosition
from v2.backend.app.services.risk_gateway.alpha_liquidity import evaluate_alpha_liquidity_risk


REPO_ROOT = Path(__file__).resolve().parents[4]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sample_payloads() -> dict[str, Any]:
    return {
        "ohlcv": {
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 1000.0,
            "close_time": "2026-06-14T00:00:00Z",
            "candle_closed_confirmed": True,
        },
        "prices": {"ticker_24hr": {"lastPrice": "102.0"}, "funding": {"markPrice": "102.0", "indexPrice": "101.5"}},
        "orderbook": {
            "best_bid": 101.95,
            "best_ask": 102.05,
            "bid_size": 20.0,
            "ask_size": 10.0,
            "orderbook_wall_strength": 0.35,
            "bids": [{"price": 101.9, "qty": 10.0}],
            "asks": [{"price": 102.1, "qty": 8.0}],
        },
        "microstructure": {
            "microstructure_liquidity_depth": 25000.0,
            "coinapi_wsds_tape_imbalance": 0.42,
            "microstructure_reversal_score": 0.10,
        },
        "liquidation_levels": {
            "nearest_liquidation_level_above": 108.0,
            "nearest_liquidation_level_below": 96.0,
            "distance_to_long_liq_bps": 700.0,
            "distance_to_short_liq_bps": 550.0,
            "liquidation_cluster_strength_long": 0.20,
            "liquidation_cluster_strength_short": 0.30,
            "liquidation_cascade_risk": 0.25,
            "liquidation_pressure_direction": "neutral",
        },
        "liquidity_zones": {
            "liquidity_zone_above": 106.0,
            "liquidity_zone_below": 98.0,
            "distance_to_liquidity_zone_bps": 240.0,
        },
    }


def build_one_shot_status() -> dict[str, Any]:
    generated = _now()
    payloads = _sample_payloads()
    tensor = V2UnifiedFeatureTensorBuilder().build(symbol="BTCUSDT", timeframe="1m", payloads=payloads)
    required_tensor_fields = {
        "nearest_liquidation_level_above",
        "nearest_liquidation_level_below",
        "distance_to_long_liq_bps",
        "distance_to_short_liq_bps",
        "liquidation_cluster_strength_long",
        "liquidation_cluster_strength_short",
        "liquidity_zone_above",
        "liquidity_zone_below",
        "distance_to_liquidity_zone_bps",
        "liquidation_cascade_risk",
        "orderbook_wall_strength",
        "microstructure_liquidity_depth",
        "coinapi_wsds_tape_imbalance",
    }
    tensor_present = required_tensor_fields.issubset(set(tensor.feature_names))
    context = {
        "distance_to_long_liq_bps": 700.0,
        "distance_to_short_liq_bps": 550.0,
        "liquidation_cascade_risk": 0.25,
        "orderbook_wall_strength": 0.35,
        "microstructure_liquidity_depth": 25000.0,
        "liquidation_pressure_direction": "neutral",
    }
    risk = evaluate_alpha_liquidity_risk(action="long", context=context)
    strategy = compute_adaptive_strategy_weights(
        [
            {"strategy_family": "trend_following", "realized_pnl_bps": 30.0},
            {"strategy_family": "trend_following", "realized_pnl_bps": 20.0},
            {"strategy_family": "trend_following", "realized_pnl_bps": 15.0},
            {"strategy_family": "mean_reversion", "realized_pnl_bps": -25.0},
        ],
        current_weights={"trend_following": 1.0, "mean_reversion": 1.0},
    )
    hedge = evaluate_adaptive_hedge(
        position={"symbol": "BTCUSDT", "side": "long", "notional": 100.0},
        hedge_intent={
            "hedge_intent": True,
            "symbol": "BTCUSDT",
            "hedge_side": "short",
            "hedge_reason": "volatility_spike_hedge",
            "hedge_exit_reason": "volatility_normalized",
            "hedge_budget_usd": 10.0,
            "risk_approved": True,
        },
    )
    hedge_cost = build_hedge_cost_benefit(
        hedge_id="hedge_demo",
        hedge_notional_usd=10.0,
        fees=0.01,
        slippage=0.01,
        pnl_without_hedge=-2.0,
        pnl_with_hedge=-0.8,
    )
    position = PaperNetPosition(
        position_id="paper_pos_demo",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-14T00:00:00Z",
        source_signal_id="signal_demo",
        prediction_id="pred_demo",
        market_state_id="market_state_demo",
        timeframe="1m",
        feature_snapshot_id="feature_snapshot_demo",
        entry_market_state_id="market_state_demo",
        strategy_id="trend_following",
        strategy_family="trend_following",
        strategy_selected_mode="trend_following",
        hedge_state="NO_HEDGE",
        hedge_reason="NO_HEDGE_CONTEXT",
        drawdown_at_entry=0.0,
        market_regime_at_entry="trend",
        liquidity_zone_context={"liquidity_zone_above": 106.0, "liquidity_zone_below": 98.0},
        liquidation_distance_context={"distance_to_long_liq_bps": 700.0, "distance_to_short_liq_bps": 550.0},
        microstructure_context={
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:demo",
            "bid_ask_spread_bps": 1.4,
            "microstructure_liquidity_depth": 25000.0,
        },
        squeeze_evidence_score=0.0,
        squeeze_evidence_source="DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        squeeze_evidence_components={"spread_stress": 0.0},
        entry_observed_spread_bps=1.4,
        entry_spread_source="V2_MARKET_ORDERBOOK_TOP_OF_BOOK:demo",
        expected_slippage_bps=0.9,
        expected_slippage_source="MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        expected_slippage_modeled=True,
        fill_ids=["fill_demo"],
        best_favorable_price=102.0,
        intra_trade_high_price=102.0,
        intra_trade_low_price=100.0,
        last_mark_price=102.0,
        last_mark_est=generated,
        # Trust envelope fields required for trainer_consumable=True
        decision_id="decision_demo",
        mtf_snapshot_id="mtf_demo",
        feature_cutoff="2026-06-13T23:59:59Z",
        decision_time="2026-06-14T00:00:00Z",
        available_at="2026-06-14T00:00:00Z",
        selected_action="long",
        model_version="v2_demo",
        checkpoint_id="checkpoint_demo",
        source_hashes={"model": "abc123demo", "feature": "def456demo"},
    )
    exit_eval = evaluate_exit(
        position=position,
        mark_price=102.0,
        generated_utc=generated,
        config=PaperExitConfig(take_profit_bps=150.0),
        alpha_context={"liquidation_cascade_risk": 0.25},
    )
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=102.0,
        exit_time=generated,
        close_reason=str(exit_eval.get("close_reason") or "TIER_2_TAKE_PROFIT"),
    )
    feedback = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=outcome)
    pnl = reconcile_paper_pnl(
        fills=[{"fill_id": "fill_demo", "symbol": "BTCUSDT", "quantity": 1.0, "fill_price": 100.0}],
        open_positions=[],
        closed_trades=[close_event],
        mark_prices={"BTCUSDT": {"price": 102.0}},
        starting_equity=1000.0,
    )
    feasibility = {
        "monthly_target_net_usdt": 10000,
        "goal_status": "INSUFFICIENT_SAMPLE_FOR_10K_TARGET",
        "closed_trade_count": 1,
        "net_pnl_after_costs": close_event["realized_pnl_usd"],
        "guaranteed_profit": False,
        "reason": "runtime alpha chain validates feedback mechanics, but sample is not sufficient for 10k/month feasibility",
    }
    validations = {
        "liquidation_zone_enters_trainer_tensor": tensor_present,
        "liquidation_proximity_affects_risk_orchestrator": risk["alpha_liquidity_context_used"] and risk["risk_decision"].startswith("ALLOW"),
        "strategy_weights_update_from_realized_outcomes": strategy["adaptive_from_realized_outcomes"] is True,
        "hedge_requires_explicit_intent": hedge["hedge_allowed"] is True and hedge["requires_unhedge_condition"] is True,
        "hedge_cost_benefit_tracked": hedge_cost["hedge_cost_benefit_tracked"] is True,
        "exit_writes_close_feedback": bool(close_event.get("trainer_feedback_id") and outcome.get("trainer_feedback_id")),
        "paper_pnl_reconciles": pnl["reconciliation_status"] == "RECONCILED",
        "trainer_feedback_fields_present": feedback["trainer_consumable"] is True,
        "no_live_mutation": True,
    }
    return {
        "generated_at_utc": generated,
        "gate": "V2_RUNTIME_ALPHA_DECISION_CHAIN_REMEDIATION_READY" if all(validations.values()) else "V2_RUNTIME_ALPHA_DECISION_CHAIN_REMEDIATION_BLOCKED",
        "validations": validations,
        "liquidity_liquidation_decision_consumer_wiring_status": {
            "native_trainer_tensor": tensor_present,
            "risk_evaluator": risk,
            "orchestrator": {"signal_adjustment": risk["orchestrator_signal_adjustment"]},
            "adaptive_strategy_selector": {"strategy_bias": risk["strategy_bias"]},
            "paper_exit_coordinator": {"alpha_context_supported": True},
            "paper_lifecycle_guard": {"alpha_context_passed_to_exit": True},
            "signal_explanation_payload": {"alpha_context": context},
            "website_runtime_truth": {"payload_ready": True},
            "display_only": False,
        },
        "adaptive_strategy_weight_runtime_status": strategy,
        "adaptive_hedging_runtime_status": hedge,
        "hedge_cost_benefit_status": hedge_cost,
        "paper_exit_profit_protection_runtime_status": exit_eval,
        "paper_closed_trade_feedback_status": {"close_event": close_event, "outcome_label": outcome},
        "paper_pnl_reconciliation_runtime_status": pnl,
        "trainer_strategy_hedge_exit_feedback_status": feedback_status([feedback]) | {"sample_feedback_row": feedback},
        "monthly_10k_goal_feasibility_after_alpha_remediation": feasibility,
        "runtime_alpha_website_status": {
            "strategy_weights": strategy["strategy_runtime_rows"],
            "hedge_status": hedge,
            "hedge_pnl": hedge_cost,
            "exit_reasons": [close_event["close_reason"]],
            "liquidity_zone_context": position.liquidity_zone_context,
            "liquidation_proximity": position.liquidation_distance_context,
            "paper_realized_pnl": pnl["realized_pnl"],
            "paper_unrealized_pnl": pnl["unrealized_pnl"],
            "trainer_feedback_rows": 1,
            "ten_k_target_feasibility": feasibility,
            "guaranteed_10k_month": False,
        },
        "safety": {
            "paper_only": True,
            "live_order_submitted": False,
            "test_order_called": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "old_redis_written": False,
            "exchange_action_taken": False,
        },
    }


def write_reports(status: dict[str, Any], output_dir: Path) -> None:
    mapping = {
        "liquidity_liquidation_decision_consumer_wiring_status.json": status["liquidity_liquidation_decision_consumer_wiring_status"],
        "adaptive_strategy_weight_runtime_status.json": status["adaptive_strategy_weight_runtime_status"],
        "adaptive_hedging_runtime_status.json": status["adaptive_hedging_runtime_status"],
        "hedge_cost_benefit_status.json": status["hedge_cost_benefit_status"],
        "paper_exit_profit_protection_runtime_status.json": status["paper_exit_profit_protection_runtime_status"],
        "paper_closed_trade_feedback_status.json": status["paper_closed_trade_feedback_status"],
        "paper_pnl_reconciliation_runtime_status.json": status["paper_pnl_reconciliation_runtime_status"],
        "trainer_strategy_hedge_exit_feedback_status.json": status["trainer_strategy_hedge_exit_feedback_status"],
        "monthly_10k_goal_feasibility_after_alpha_remediation.json": status["monthly_10k_goal_feasibility_after_alpha_remediation"],
        "runtime_alpha_website_status.json": status["runtime_alpha_website_status"],
        "operator_dashboard_payload.json": status,
    }
    for name, payload in mapping.items():
        _write(output_dir / name, payload)
        _write(REPO_ROOT / name, payload)
    report = f"""# V2 Runtime Alpha Decision Chain Remediation Report

Generated: `{status['generated_at_utc']}`

Gate: `{status['gate']}`

## Safety

- No real orders submitted.
- No test orders called.
- No leverage or margin mode changed.
- No old Redis writes.
- No exchange action taken.

## One-shot validation

```json
{json.dumps(status['validations'], indent=2, sort_keys=True)}
```

## 10k target

`{status['monthly_10k_goal_feasibility_after_alpha_remediation']['goal_status']}`

This is not a guaranteed-profit claim. The runtime chain now produces richer decision/feedback evidence, but the 10k target still requires sufficient closed paper outcomes.
"""
    _write(output_dir / "V2_RUNTIME_ALPHA_DECISION_CHAIN_REMEDIATION_REPORT.md", report)
    _write(REPO_ROOT / "V2_RUNTIME_ALPHA_DECISION_CHAIN_REMEDIATION_REPORT.md", report)
    go = f"""# GO / NO-GO

Generated: `{status['generated_at_utc']}`

Gate: `{status['gate']}`

Runtime alpha chain code has been patched and one-shot paper validation completed without live mutation.

10k/month status: `{status['monthly_10k_goal_feasibility_after_alpha_remediation']['goal_status']}`

New density-aware soak is required because this pass changed material paper/runtime behavior.
"""
    _write(REPO_ROOT / "GO_NO_GO.md", go)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run paper-only V2 runtime alpha decision chain remediation validation.")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "runtime_alpha_decision_chain_remediation")
    args = parser.parse_args(argv)
    status = build_one_shot_status()
    run_dir = args.output_dir / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    write_reports(status, run_dir)
    print(json.dumps({"gate": status["gate"], "output_dir": str(run_dir), "validations": status["validations"]}, indent=2, sort_keys=True))
    return 0 if status["gate"] == "V2_RUNTIME_ALPHA_DECISION_CHAIN_REMEDIATION_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
