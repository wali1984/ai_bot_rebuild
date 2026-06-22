from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
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

