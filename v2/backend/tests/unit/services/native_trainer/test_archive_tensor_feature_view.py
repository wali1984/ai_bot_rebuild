"""Archive completeness: the prediction publisher must archive the tensor's OWN
feature view, not just the trust-row flat dict.

Root cause of the dead replay families (fvg/vwap/cvd/structure/moralis/confluence/
micro-trust ~135 features 0%-populated in training examples): the archived snapshot
stored only trust_row["features"] (the pipeline's ~380-field dict) while the live
prediction tensor had resolved the full FEATURE_SPEC. These lock in the merge and the
replay round-trip: a feature the live tensor saw survives archive -> replay rebuild.
"""
from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
    V2UnifiedFeatureTensorBuilder,
)

_NAMES = [n for n, _ in FEATURE_SPEC]
DECISION_TIME = "2026-07-18T12:00:00Z"
AVAILABLE_AT = "2026-07-18T11:59:59Z"


def _causal(payload: dict) -> dict:
    return {**payload, "available_at": AVAILABLE_AT}


def _live_payloads() -> dict:
    """Payloads mimicking the LIVE prediction path (families read from Redis)."""
    return {
        "fvg": _causal({"fvg_size_bps": 42.0, "fvg_fill_percent": 0.25}),
        "vwap_features": _causal({"vwap_slope": 0.5}),
        "cvd_features": _causal({"cvd_slope": -1.5}),
        "market_structure": _causal({"structure_trend_state": 1.0}),
        "features_ta_full": _causal(
            {"indicators": {"ta_ADX": 27.5, "rsi_14": 61.0}}
        ),
    }


def test_tensor_view_round_trips_through_archive_features() -> None:
    b = V2UnifiedFeatureTensorBuilder()
    live = b.build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads=_live_payloads(),
    )

    # What the publisher now archives: tensor view merged under trust-row features.
    tensor_view = {
        name: value
        for name, value, missing in zip(live.feature_names, live.values, live.missing_mask, strict=False)
        if not missing
    }
    archived_features = {**tensor_view, "rsi_14": 61.0}  # trust-row style raw field kept

    # Replay-side rebuild: _payloads_from_feature_snapshot passes the flat archived
    # dict as every payload; mimic the ones the extraction digs into.
    flat = dict(archived_features)
    replay_payloads = {
        "features_latest": _causal({"features": flat}),
        "fvg": _causal(flat),
        "vwap_features": _causal(flat),
        "cvd_features": _causal(flat),
        "market_structure": _causal(flat),
        "features_ta": _causal({"indicators": flat}),
        "features_ta_full": _causal({"features": flat}),
    }
    replayed = b.build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads=replay_payloads,
    )

    for feature, expected in (
        ("fvg_size_bps", 42.0),
        ("fvg_fill_percent", 0.25),
        ("vwap_slope", 0.5),
        ("cvd_slope", -1.5),
        ("taf_ta_adx", 27.5),
        ("taf_rsi_14", 61.0),
    ):
        idx = _NAMES.index(feature)
        assert live.missing_mask[idx] == 0, f"{feature} should be present on the LIVE tensor"
        assert replayed.missing_mask[idx] == 0, f"{feature} lost in archive round-trip"
        assert replayed.model_vector[idx] == expected, f"{feature} value corrupted in round-trip"


def test_publisher_merges_tensor_view_into_snapshot_features() -> None:
    # Direct check on the publisher's snapshot builder.
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
        TrainingExample,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
        _trusted_replay_snapshot,
    )

    b = V2UnifiedFeatureTensorBuilder()
    tensor = b.build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads=_live_payloads(),
    )
    example = TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=(),
        row_classification="TRAINABLE",
        trust_row={},
    )
    from types import SimpleNamespace

    def _model_output_stub():
        return SimpleNamespace(
            selected_action="hold",
            action_probabilities=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            expected_move_bps=0.0,
            confidence_calibrated=0.5,
            confidence_raw=0.5,
            policy_value=0.0,
            model_id="unit_model",
            masa_score=0.0,
            logits=(0.0,) * 7,
            calibration={},
        )

    snapshot, _reasons = _trusted_replay_snapshot(
        prediction_id="p1",
        signal_id="s1",
        example=example,
        model_output=_model_output_stub(),
        trust_row={"features": {"rsi_14": 61.0}},
        checkpoint=None,
        source_hashes={},
    )
    feats = snapshot["feature_snapshot"]["features"]
    assert feats["fvg_size_bps"] == 42.0               # tensor-view name archived
    assert feats["vwap_slope"] == 0.5
    assert feats["rsi_14"] == 61.0                     # trust-row field preserved
