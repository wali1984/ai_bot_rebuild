from __future__ import annotations

import pytest

from v2.backend.app.services.market_state_integrity import (
    EventTimeAligner,
    build_market_state_envelope_from_snapshot,
    coerce_market_state_envelope,
    hash_market_state_envelope,
)


def test_event_time_aligner_rejects_unfinished_higher_timeframe() -> None:
    envelope = build_market_state_envelope_from_snapshot(
        {
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "decision_time": "2026-06-11T00:01:05Z",
            "generated_at": "2026-06-11T00:01:05Z",
            "timeframe": "1m",
            "feature_cutoff": "2026-06-11T00:01:00Z",
            "timeframe_cutoffs": {
                "1m": "2026-06-11T00:01:00Z",
                "5m": "2026-06-11T00:05:00Z",
            },
            "feature_hash": "aligner_hash",
            "data_quality_score": 0.95,
            "is_final_candle": True,
        }
    )
    result = EventTimeAligner().evaluate(envelope=envelope)
    assert result.accepted is False
    assert "mixed_timeframe_cutoff:5m" in result.reject_reasons


def test_market_state_envelope_preserves_fractional_clock_precision() -> None:
    snapshot = {
        "symbol": "BTCUSDT",
        "exchange": "binance",
        "decision_time": "2026-06-11T00:01:05.299Z",
        "generated_at": "2026-06-11T00:01:05.299Z",
        "timeframe": "1m",
        "feature_cutoff": "2026-06-11T00:00:59.999Z",
        "event_time": "2026-06-11T00:00:59.099Z",
        "ingested_at": "2026-06-11T00:00:59.199Z",
        "available_at": "2026-06-11T00:00:59.299Z",
        "feature_hash": "precision_hash",
        "data_quality_score": 1.0,
        "is_final_candle": True,
    }

    envelope = build_market_state_envelope_from_snapshot(snapshot)
    coerced = coerce_market_state_envelope(envelope.to_dict())

    assert envelope.event_time == "2026-06-11T00:00:59.099Z"
    assert envelope.ingested_at == "2026-06-11T00:00:59.199Z"
    assert envelope.available_at == "2026-06-11T00:00:59.299Z"
    assert envelope.feature_cutoff == "2026-06-11T00:00:59.999Z"
    assert envelope.decision_time == "2026-06-11T00:01:05.299Z"
    assert coerced == envelope
    assert hash_market_state_envelope(coerced) == hash_market_state_envelope(
        envelope
    )


def test_exact_native_snapshot_requires_postcommit_feature_availability() -> None:
    with pytest.raises(
        ValueError,
        match="exact_feature_availability_required",
    ):
        build_market_state_envelope_from_snapshot(
            {
                "schema_version": "v2_native_feature_snapshot_v2",
                "worker_id": "v2_feature_pipeline_native_loop",
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "decision_time": "2026-06-11T00:01:05.299Z",
                "timeframe": "1m",
                "feature_cutoff": "2026-06-11T00:00:59.999Z",
                "event_time": "2026-06-11T00:00:59.099Z",
                "ingested_at": "2026-06-11T00:00:59.199Z",
                "source_available_at": "2026-06-11T00:00:59.299Z",
                "available_at_est": "2026-06-11T00:01:05.299Z",
                "exact_source_clock_valid": True,
                "exact_feature_availability_valid": False,
                "market_state_envelope": {
                    "symbol": "BTCUSDT",
                    "exchange": "binance",
                    "decision_time": "2026-06-11T00:01:05.299Z",
                    "event_time": "2026-06-11T00:00:59.099Z",
                    "available_at": "2026-06-11T00:01:05.299Z",
                    "ingested_at": "2026-06-11T00:00:59.199Z",
                    "timeframe_cutoffs": {
                        "1m": "2026-06-11T00:00:59.999Z"
                    },
                    "feature_cutoff": "2026-06-11T00:00:59.999Z",
                    "feature_version": "forged_embedded_envelope",
                    "feature_hash": "forged_hash",
                    "data_quality_score": 1.0,
                },
                "features": {},
            }
        )


def test_exact_native_snapshot_rejects_self_asserted_publication_receipt() -> None:
    with pytest.raises(
        ValueError,
        match="verified_feature_publication_receipt_required",
    ):
        build_market_state_envelope_from_snapshot(
            {
                "schema_version": "v2_native_feature_snapshot_v2",
                "worker_id": "v2_feature_pipeline_native_loop",
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "decision_time": "2026-06-11T00:01:05.499Z",
                "timeframe": "1m",
                "feature_cutoff": "2026-06-11T00:00:59.999Z",
                "event_time": "2026-06-11T00:00:59.099Z",
                "ingested_at": "2026-06-11T00:00:59.199Z",
                "source_available_at": "2026-06-11T00:00:59.199Z",
                "feature_available_at": "2026-06-11T00:01:05.399Z",
                "available_at_est": "2026-06-11T00:01:05.299Z",
                "exact_source_clock_valid": True,
                "exact_feature_availability_valid": True,
                "candle_closed_confirmed": True,
                "market_state_envelope": {
                    "symbol": "BTCUSDT",
                    "exchange": "binance",
                    "decision_time": "2026-06-11T00:01:05.499Z",
                    "event_time": "2026-06-11T00:00:59.099Z",
                    "available_at": "2026-06-11T00:01:05.399Z",
                    "ingested_at": "2026-06-11T00:00:59.199Z",
                    "timeframe_cutoffs": {
                        "1m": "2026-06-11T00:00:59.999Z"
                    },
                    "feature_cutoff": "2026-06-11T00:00:59.999Z",
                    "feature_version": "forged_embedded_envelope",
                    "feature_hash": "forged_hash",
                    "data_quality_score": 1.0,
                },
                "features": {"ret_pct": 0.001},
            }
        )


@pytest.mark.parametrize(
    "invalid_feature_available_at",
    [float("nan"), float("inf"), float("-inf"), 10**100, True],
)
def test_exact_native_snapshot_fails_closed_on_invalid_availability_clock(
    invalid_feature_available_at,
) -> None:
    with pytest.raises(
        ValueError,
        match="feature_available_at_missing_or_invalid",
    ):
        build_market_state_envelope_from_snapshot(
            {
                "schema_version": "v2_native_feature_snapshot_v2",
                "worker_id": "v2_feature_pipeline_native_loop",
                "exact_source_clock_valid": True,
                "exact_feature_availability_valid": True,
                "feature_available_at": invalid_feature_available_at,
            }
        )


@pytest.mark.parametrize("schema_version", [None, "v2_native_feature_snapshot_v1"])
def test_native_feature_worker_rejects_schema_downgrade(schema_version) -> None:
    with pytest.raises(
        ValueError,
        match="native_feature_snapshot_schema_downgrade_rejected",
    ):
        build_market_state_envelope_from_snapshot(
            {
                "schema_version": schema_version,
                "worker_id": "v2_feature_pipeline_native_loop",
                "symbol": "BTCUSDT",
                "decision_time": "2026-06-11T00:01:05Z",
                "generated_at": "2026-06-11T00:01:05Z",
                "feature_cutoff": "2026-06-11T00:00:59.999Z",
                "market_state_envelope": {
                    "symbol": "BTCUSDT",
                    "exchange": "binance",
                    "decision_time": "2026-06-11T00:01:05Z",
                    "event_time": "2026-06-11T00:00:59Z",
                    "available_at": "2026-06-11T00:01:05Z",
                    "ingested_at": "2026-06-11T00:01:00Z",
                    "timeframe_cutoffs": {
                        "1m": "2026-06-11T00:00:59.999Z"
                    },
                    "feature_cutoff": "2026-06-11T00:00:59.999Z",
                    "feature_version": "downgraded",
                    "feature_hash": "forged_hash",
                    "data_quality_score": 1.0,
                },
            }
        )


def test_active_native_reader_rejects_schema_and_worker_downgrade() -> None:
    with pytest.raises(
        ValueError,
        match="active_native_feature_snapshot_v2_required",
    ):
        build_market_state_envelope_from_snapshot(
            {
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "decision_time": "2026-06-11T00:01:05Z",
                "generated_at": "2026-06-11T00:01:05Z",
                "timeframe": "1m",
                "feature_cutoff": "2026-06-11T00:00:59.999Z",
                "event_time": "2026-06-11T00:00:59Z",
                "available_at": "2026-06-11T00:01:05Z",
                "ingested_at": "2026-06-11T00:01:00Z",
                "features": {},
            },
            require_verified_native_snapshot=True,
        )
