from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    apply_trainer_feedback_field_contract,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)


def _tensor() -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id="tensor",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="feat",
        values=(0.0,),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ema_12",),
        source_labels=("test",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )


def test_loader_skips_non_consumable_strategy_hedge_feedback_row() -> None:
    loader = V2HybridTrainerDataLoader()

    label = loader._label_from_closed_trade_outcome(  # noqa: SLF001
        payloads={
            "trainer_feedback_outcomes": [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "entry_prediction_id": "pred",
                    "exit_time": "2026-06-11T10:00:00Z",
                    "realized_pnl_bps": 12.5,
                    "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
                    "trainer_consumable": False,
                    "missing_feedback_fields": ["strategy_id", "market_regime_at_entry"],
                }
            ]
        },
        tensor=_tensor(),
    )

    assert label is None


class _FakeIO:
    def __init__(self, payloads: dict[str, object]):
        self.payloads = payloads

    def get_json(self, key: str):
        return self.payloads.get(key)


class _FakeTensorBuilder:
    def build(self, **kwargs):  # noqa: ANN001
        return _tensor()


def _context(name: str) -> dict[str, str]:
    return {"context_type": name, "source": "unit", "status": "available"}


def _paper_exploration_snapshot() -> dict[str, object]:
    return {
        "feature_snapshot_id": "paper-explore-feat",
        "symbol": "ORDIUSDT",
        "timeframe": "15m",
        "available_at": "2026-07-09T11:59:30Z",
        "generated_at": "2026-07-09T11:59:30Z",
        "feature_cutoff": "2026-07-09T11:45:00Z",
        "candle_close_time": "2026-07-09T11:45:00Z",
        "candle_closed_confirmed": True,
        "features": {"ema_12": 1.0, "close": 100.0},
    }


def _paper_exploration_feedback(**overrides: object) -> dict[str, object]:
    snapshot = _paper_exploration_snapshot()
    feedback: dict[str, object] = {
        "trainer_feedback_source": "PAPER_RISK_CONTROLLER_EXPLORATION_CLOSED_WINDOW",
        "feedback_type": "PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_CLOSED",
        "exploration_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
        "trainer_feedback_id": "paper-explore-closed-1",
        "paper_exploration_candidate_id": "hyp-paper-explore-1",
        "prediction_id": "hyp-paper-explore-1",
        "signal_id": "hyp-paper-explore-1",
        "decision_id": "dec-hyp-paper-explore-1",
        "feature_snapshot_id": "paper-explore-feat",
        "entry_feature_snapshot_id": "paper-explore-feat",
        "entry_feature_snapshot": snapshot,
        "mtf_snapshot_id": "mtf-paper-explore-1",
        "timeframe": "15m",
        "symbol": "ORDIUSDT",
        "side": "long",
        "action": "long",
        "selected_action": "long",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl_usd": 1.0,
        "realized_net_pnl_usd": 0.8,
        "realized_pnl_bps": 100.0,
        "realized_net_pnl_bps": 80.0,
        "expected_net_pnl_usd": 0.5,
        "expected_max_loss_usd": 1.0,
        "feature_cutoff": "2026-07-09T11:45:00Z",
        "decision_time": "2026-07-09T12:00:00Z",
        "available_at": "2026-07-09T11:59:30Z",
        "generated_at": "2026-07-09T12:00:00Z",
        "model_version": "paper_exploration_materialization",
        "checkpoint_id": "paper_exploration_materialization_closed",
        "source_hashes": {"features": "hash"},
        "provider_hashes": {"latest": "provider-hash"},
        "trainer_consumable": True,
        "future_label_pending": False,
        "counterfactual_label_pending": False,
        "counts_as_a_plus": False,
        "counts_as_A_plus": False,
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "routes_to_live": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "paper_only": True,
    }
    feedback.update(overrides)
    return feedback


def test_loader_consumes_mature_counterfactual_feedback_key() -> None:
    snapshot = {
        "feature_snapshot_id": "feat",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-07-09T11:59:30Z",
        "generated_at": "2026-07-09T11:59:30Z",
        "feature_cutoff": "2026-07-09T11:59:00Z",
        "candle_close_time": "2026-07-09T11:59:00Z",
        "candle_closed_confirmed": True,
        "features": {"ema_12": 1.0, "close": 100.0},
    }
    feedback = {
        "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
        "trainer_feedback_source": "V2_CONTINUOUS_EDGE_FACTORY_COUNTERFACTUAL_CLOSED_WINDOW",
        "trainer_feedback_id": "cf-1",
        "trainer_feedback_source_key": "v2:trainer:feedback:counterfactuals",
        "prediction_id": "pred",
        "signal_id": "sig",
        "decision_id": "dec",
        "feature_snapshot_id": "feat",
        "entry_feature_snapshot_id": "feat",
        "entry_feature_snapshot": snapshot,
        "mtf_snapshot_id": "mtf",
        "market_state_id": "mstate",
        "timeframe": "1m",
        "symbol": "BTCUSDT",
        "action": "long",
        "selected_action": "long",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl": 1.0,
        "realized_pnl_usd": 1.0,
        "realized_net_pnl_usd": 1.0,
        "realized_pnl_bps": 100.0,
        "realized_net_pnl_bps": 100.0,
        "strategy_id": "trend",
        "strategy_family": "trend",
        "strategy_subtype": "pullback",
        "hedge_state": "not_hedged",
        "hedge_reason": "none",
        "entry_reason": "counterfactual",
        "exit_reason": "closed_candle_future_window_elapsed",
        "hold_time_seconds": 900,
        "market_regime_at_entry": "trend",
        "market_regime_at_exit": "trend",
        "liquidity_zone_context": _context("liquidity_zone"),
        "liquidation_distance_context": _context("liquidation"),
        "microstructure_context": _context("microstructure"),
        "oi_funding_context": _context("oi_funding"),
        "public_intel_context": _context("public_intel"),
        "liquidity_context": _context("liquidity"),
        "major_move_context": _context("major_move"),
        "market_regime": "trend",
        "future_window_label_source": "continuous_edge_factory_counterfactual_closed_candle",
        "drawdown_at_entry": 0.0,
        "feature_cutoff": "2026-07-09T11:59:00Z",
        "decision_time": "2026-07-09T12:00:00Z",
        "available_at": "2026-07-09T11:59:30Z",
        "model_version": "edge_factory",
        "checkpoint_id": "edge_factory_counterfactual",
        "source_hashes": {"features": "hash"},
        "trainer_consumable": True,
        "missing_feedback_fields": [],
        "counterfactual_label_pending": False,
        "counterfactual_label_matured": True,
        "counts_as_a_plus": False,
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    loader = V2HybridTrainerDataLoader(
        io=_FakeIO(
            {
                "v2:trainer:feedback:outcomes": [],
                "v2:trainer:feedback:counterfactuals": [feedback],
                "v2:features:snapshot:feat": snapshot,
            }
        ),
        tensor_builder=_FakeTensorBuilder(),
    )

    examples = loader.load_training_examples(
        symbols=["BTCUSDT"],
        timeframes=["1m"],
        trusted_only=True,
        closed_trade_only=True,
    )

    assert len(examples) == 1
    assert examples[0].trust_row["trainer_feedback_source_key"] == "v2:trainer:feedback:counterfactuals"
    assert examples[0].trust_row["counts_as_final_a_plus"] is False
    assert examples[0].trust_row["counts_as_live_ready"] is False


def test_loader_consumes_mature_paper_exploration_materialization_feedback_key() -> None:
    snapshot = _paper_exploration_snapshot()
    feedback = _paper_exploration_feedback()
    source_key = "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
    loader = V2HybridTrainerDataLoader(
        io=_FakeIO(
            {
                "v2:trainer:feedback:outcomes": [],
                "v2:trainer:feedback:counterfactuals": [],
                source_key: [feedback],
                "v2:features:snapshot:paper-explore-feat": snapshot,
            }
        ),
        tensor_builder=_FakeTensorBuilder(),
    )

    examples = loader.load_training_examples(
        symbols=["ORDIUSDT"],
        timeframes=["15m"],
        trusted_only=True,
        closed_trade_only=True,
    )

    assert len(examples) == 1
    assert examples[0].trust_row["trainer_feedback_source_key"] == source_key
    assert examples[0].trust_row["exploration_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert examples[0].trust_row["counts_as_A_plus"] is False
    assert examples[0].trust_row["counts_as_live_ready"] is False
    assert examples[0].trust_row["routes_to_live"] is False
    assert examples[0].trust_row["places_real_order"] is False


def test_loader_skips_pending_paper_exploration_no_fill_feedback() -> None:
    source_key = "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
    pending_feedback = _paper_exploration_feedback(
        feedback_type="PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_NO_FILL",
        future_label_pending=True,
        trainer_consumable=False,
        trainer_consumable_block_reason="FUTURE_LABEL_PENDING_NO_PAPER_FILL_OPENED",
        realized_pnl_usd=None,
        realized_net_pnl_usd=None,
        realized_pnl_bps=None,
        realized_net_pnl_bps=None,
        block_reason_if_rejected="ROW_EXPIRED_BEFORE_PAPER_LOOP",
    )
    loader = V2HybridTrainerDataLoader(
        io=_FakeIO(
            {
                "v2:trainer:feedback:outcomes": [],
                "v2:trainer:feedback:counterfactuals": [],
                source_key: [pending_feedback],
                "v2:features:snapshot:paper-explore-feat": _paper_exploration_snapshot(),
            }
        ),
        tensor_builder=_FakeTensorBuilder(),
    )

    examples = loader.load_training_examples(
        symbols=["ORDIUSDT"],
        timeframes=["15m"],
        trusted_only=True,
        closed_trade_only=True,
    )

    assert examples == []


def test_paper_exploration_feedback_contract_forces_paper_only_non_live_flags() -> None:
    row = apply_trainer_feedback_field_contract(
        {
            "paper_risk_controller_exploration": True,
            "counts_as_a_grade_evidence": True,
            "counts_as_A_plus": True,
            "counts_as_final_a_plus": True,
            "counts_as_live_ready": True,
            "routes_to_live": True,
            "places_real_order": True,
            "paper_only": False,
        }
    )

    assert row["allow_paper_risk_controller_exploration"] is True
    assert row["counts_as_a_grade_evidence"] is False
    assert row["counts_as_A_plus"] is False
    assert row["counts_as_final_a_plus"] is False
    assert row["counts_as_live_ready"] is False
    assert row["routes_to_live"] is False
    assert row["places_real_order"] is False
    assert row["paper_only"] is True
    assert row["calibration_label_purpose"] == "paper_risk_controller_exploration_outcome"
