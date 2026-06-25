"""Tests proving missing feature snapshots stay quarantined.

Closed paper trades without a real feature_snapshot_id must not become
trainer-consumable.  Synthetic IDs such as synth_fsid_{prediction_id} fabricate
lineage and can let dirty samples into training, so enrichment preserves only
explicit snapshot ids and otherwise reports the missing field.
"""
from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.feedback_enrichment import (
    REQUIRED_FEEDBACK_FIELDS,
    build_strategy_hedge_exit_feedback,
)
from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.position_state import (
    PaperNetPosition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_position(
    *,
    symbol: str = "ALICEUSDT",
    side: str = "short",
    timeframe: str = "1m",
    feature_snapshot_id: str | None = None,
    prediction_id: str | None = "v2h_abc123",
    signal_id: str | None = "sig_xyz456",
    strategy_id: str = "mean_reversion_mode",
) -> PaperNetPosition:
    return PaperNetPosition(
        position_id=f"paper_pos_{symbol}",
        symbol=symbol,
        side=side,
        net_quantity=100.0,
        avg_entry_price=0.1038,
        opened_est="2026-06-18T14:00:00-04:00",
        source_signal_id=signal_id,
        prediction_id=prediction_id,
        market_state_id="mstate_e83314e957253c60002e",
        timeframe=timeframe,
        feature_snapshot_id=feature_snapshot_id,
        decision_id="decision_unit",
        mtf_snapshot_id="mtf_unit",
        feature_cutoff="2026-06-18T17:59:59Z",
        decision_time="2026-06-18T18:00:00Z",
        available_at="2026-06-18T17:59:30Z",
        selected_action=side,
        model_version="unit_model",
        checkpoint_id="unit_checkpoint",
        source_hashes={"feature_vector_hash": "unit_hash"},
        strategy_id=strategy_id,
        strategy_family=strategy_id,
        strategy_selected_mode=strategy_id,
        hedge_state="NO_HEDGE",
        hedge_reason="NO_HEDGE_CONTEXT",
        market_regime_at_entry="range",
        fill_ids=[signal_id or "fill_1"],
    )


def _build_feedback(position: PaperNetPosition) -> dict:
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=position.net_quantity,
        exit_price=0.1022,
        exit_time="2026-06-18T15:09:09Z",
        close_reason="TIER_2_PROFIT_BANK",
    )
    if not close_event.get("squeeze_evidence_score"):
        close_event["squeeze_evidence_score"] = 0.3
    if not close_event.get("squeeze_evidence_source"):
        close_event["squeeze_evidence_source"] = "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT"
    if not close_event.get("actual_observed_spread_entry_bps"):
        close_event["actual_observed_spread_entry_bps"] = 2.5
    if not close_event.get("entry_spread_source"):
        close_event["entry_spread_source"] = "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test"
    if not close_event.get("expected_slippage_source"):
        close_event["expected_slippage_source"] = "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY"
    if close_event.get("intra_trade_high_price") is None:
        close_event["intra_trade_high_price"] = float(position.avg_entry_price) * 1.005
    if close_event.get("intra_trade_low_price") is None:
        close_event["intra_trade_low_price"] = float(position.avg_entry_price) * 0.995
    return build_strategy_hedge_exit_feedback(
        close_event=close_event,
        outcome_label=outcome,
    )


# ---------------------------------------------------------------------------
# Core fix: no synthetic feature snapshot fallback
# ---------------------------------------------------------------------------

class TestMissingFeatureSnapshotQuarantine:
    def test_quarantined_when_prediction_id_present_but_feature_snapshot_missing(self) -> None:
        """A prediction id is not a substitute for feature snapshot lineage."""
        position = _minimal_position(feature_snapshot_id=None, prediction_id="v2h_9ae0fbed")
        row = _build_feedback(position)

        assert row["trainer_consumable"] is False
        assert row["feature_snapshot_id"] is None
        assert row["entry_feature_snapshot_id"] is None
        assert row["missing_feedback_fields"] == ["feature_snapshot_id"]
        assert "missing_feature_snapshot_id" in row["quarantine_reason"]

    def test_missing_feature_snapshot_is_not_synthesized_from_prediction_id(self) -> None:
        position = _minimal_position(feature_snapshot_id=None, prediction_id="v2h_abc999")
        row = _build_feedback(position)

        assert row["feature_snapshot_id"] is None
        assert row["entry_feature_snapshot_id"] is None
        assert "feature_snapshot_id" in row["missing_feedback_fields"]

    def test_missing_feature_snapshot_is_not_synthesized_from_signal_id(self) -> None:
        position = _minimal_position(
            feature_snapshot_id=None,
            prediction_id=None,
            signal_id="sig_fallback123",
        )
        row = _build_feedback(position)

        assert row["feature_snapshot_id"] is None
        assert row["entry_feature_snapshot_id"] is None
        assert "feature_snapshot_id" in row["missing_feedback_fields"]
        assert "prediction_id" in row["missing_feedback_fields"]

    def test_missing_feature_snapshot_quarantines_all_symbols(self) -> None:
        for symbol in ["ALICEUSDT", "1000PEPEUSDT", "FARTCOINUSDT", "XRPUSDT", "LTCUSDT", "LINKUSDT"]:
            position = _minimal_position(
                symbol=symbol,
                feature_snapshot_id=None,
                prediction_id=f"v2h_pred_{symbol}",
            )
            row = _build_feedback(position)
            assert row["trainer_consumable"] is False
            assert row["feature_snapshot_id"] is None
            assert "feature_snapshot_id" in row["missing_feedback_fields"]

    def test_missing_feature_snapshot_quarantines_all_timeframes(self) -> None:
        for tf in ["1m", "5m", "15m", "1h", "4h"]:
            position = _minimal_position(
                feature_snapshot_id=None,
                prediction_id=f"v2h_pred_{tf}",
                timeframe=tf,
            )
            row = _build_feedback(position)
            assert row["trainer_consumable"] is False
            assert row["feature_snapshot_id"] is None
            assert "feature_snapshot_id" in row["missing_feedback_fields"]


# ---------------------------------------------------------------------------
# Non-regression: rows that already have a real feature_snapshot_id
# ---------------------------------------------------------------------------

class TestRealFeatureSnapshotIdUnchanged:
    def test_real_fsid_not_overwritten(self) -> None:
        position = _minimal_position(feature_snapshot_id="feat_real_id_from_signal_pipeline")
        row = _build_feedback(position)

        assert row["feature_snapshot_id"] == "feat_real_id_from_signal_pipeline"
        assert row["trainer_consumable"] is True

    def test_new_fill_post_remediation_untouched(self) -> None:
        """Existing explicit ids are preserved verbatim."""
        position = _minimal_position(
            feature_snapshot_id="synth_fsid_v2h_already_set",
            prediction_id="v2h_already_set",
        )
        row = _build_feedback(position)

        assert row["feature_snapshot_id"] == "synth_fsid_v2h_already_set"


# ---------------------------------------------------------------------------
# Rows without any lineage: must still be quarantined (correct behavior)
# ---------------------------------------------------------------------------

class TestNoLineageStillQuarantined:
    def test_no_prediction_no_signal_no_fsid_quarantined(self) -> None:
        close_event = {
            "symbol": "XRPUSDT",
            "timeframe": "1m",
            "action": "long",
            "side": "long",
            "prediction_id": None,
            "signal_id": None,
            "feature_snapshot_id": None,
            "market_state_id": "mstate_001",
            "entry_price": 0.5,
            "exit_price": 0.51,
            "realized_pnl_usd": 0.01,
            "realized_pnl": 0.01,
            "realized_pnl_bps": 20.0,
            "exit_reason": "STOP_LOSS",
            "strategy_id": None,
            "strategy_family": None,
            "hedge_state": "NO_HEDGE",
            "market_regime_at_entry": "range",
            "hold_time_seconds": 100,
            "paper_only": True,
            "places_real_order": False,
        }
        row = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label={})

        assert row["trainer_consumable"] is False
        assert row["feature_snapshot_id"] is None
        assert "prediction_id" in row["missing_feedback_fields"]

    def test_latency_aliases_reconstructed_from_legacy_latency_ms(self) -> None:
        close_event = {
            "symbol": "XRPUSDT",
            "timeframe": "1m",
            "action": "long",
            "side": "long",
            "prediction_id": None,
            "signal_id": None,
            "feature_snapshot_id": None,
            "market_state_id": "mstate_001",
            "entry_price": 0.5,
            "exit_price": 0.51,
            "realized_pnl_usd": 0.01,
            "realized_pnl": 0.01,
            "realized_pnl_bps": 20.0,
            "exit_reason": "STOP_LOSS",
            "strategy_id": None,
            "strategy_family": None,
            "hedge_state": "NO_HEDGE",
            "market_regime_at_entry": "range",
            "hold_time_seconds": 100,
            "latency_ms": 42.0,
            "paper_only": True,
            "places_real_order": False,
        }
        row = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label={})

        assert row["latency_ms"] == pytest.approx(42.0)
        assert row["paper_fill_latency_ms"] == pytest.approx(42.0)
        assert row["fill_latency_ms"] == pytest.approx(42.0)
        assert row["execution_latency_ms"] == pytest.approx(42.0)
        assert row["simulated_latency_ms"] == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# Full required-fields check: feature_snapshot_id remains required
# ---------------------------------------------------------------------------

class TestAllRequiredFieldsPresent:
    def test_missing_feature_snapshot_is_the_only_required_lineage_gap(self) -> None:
        position = _minimal_position(
            symbol="BTCUSDT",
            side="long",
            timeframe="15m",
            feature_snapshot_id=None,
            prediction_id="v2h_d232e3abe6ef918204cfdfb893e17c1b",
            signal_id="sig_850ee0daed4b555c98793838",
        )
        row = _build_feedback(position)

        for field in REQUIRED_FEEDBACK_FIELDS:
            if field == "feature_snapshot_id":
                assert row.get(field) is None
            else:
                assert row.get(field) not in (None, ""), (
                    f"Required field '{field}' unexpectedly missing in feedback row"
                )
        assert row["missing_feedback_fields"] == ["feature_snapshot_id"]
        assert row["trainer_consumable"] is False


# ---------------------------------------------------------------------------
# Build_close_event → build_strategy_hedge_exit_feedback integration
# ---------------------------------------------------------------------------

class TestClosedTradeMissingFeatureSnapshotQuarantine:
    """End-to-end: paper position closes -> feedback enrichment -> quarantine."""

    def test_long_position_close_quarantined_without_feature_snapshot(self) -> None:
        position = _minimal_position(
            symbol="SOLUSDT",
            side="long",
            feature_snapshot_id=None,
            prediction_id="v2h_sol_long_1",
        )
        row = _build_feedback(position)
        assert row["trainer_consumable"] is False
        assert row["feature_snapshot_id"] is None
        assert "feature_snapshot_id" in row["missing_feedback_fields"]
        assert row["symbol"] == "SOLUSDT"

    def test_short_position_close_quarantined_without_feature_snapshot(self) -> None:
        position = _minimal_position(
            symbol="ETHUSDT",
            side="short",
            feature_snapshot_id=None,
            prediction_id="v2h_eth_short_1",
        )
        row = _build_feedback(position)
        assert row["trainer_consumable"] is False
        assert row["missing_feedback_fields"] == ["feature_snapshot_id"]
