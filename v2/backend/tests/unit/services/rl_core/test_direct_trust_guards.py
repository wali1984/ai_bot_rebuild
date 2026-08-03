from __future__ import annotations

import pytest

from v2.backend.app.services.market_state_integrity import (
    TrustGateRejectedError,
    clear_decision_replays,
    get_decision_replay,
)
from v2.backend.app.services.rl_core.masa_adapter import V2MASAAdapter
from v2.backend.app.services.rl_core.observation_builder import (
    build_observation_from_snapshot,
)


def _clean_snapshot() -> dict[str, object]:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "feature_snapshot_id": "snap_direct_trust",
        "generated_at": "2026-06-11T00:01:05Z",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "features": {
            "ret_pct": 0.001,
            "log_return": 0.001,
            "range_pct": 0.005,
            "body_pct": 0.002,
            "true_range_pct": 0.004,
            "gap_pct": 0.0,
            "ema_12": 100.5,
            "ema_26": 100.1,
            "rsi_14": 56.0,
            "macd": 0.04,
            "macd_signal": 0.03,
            "macd_hist": 0.01,
            "bb_width_pct": 0.01,
            "htf_ret_pct": 0.002,
            "htf_rsi_14": 60.0,
            "bid_ask_spread_bps": 4.0,
            "depth_imbalance": 0.1,
            "micro_price": 100.2,
            "toxicity_proxy": 0.1,
            "funding_rate": 0.0001,
            "oi_change_pct": 0.02,
            "last_liq_bps_24h": 5.0,
            "paper_position_present": 0.0,
        },
        "feature_count": 23,
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "feature_freshness_state": "CURRENT",
        "market_state_envelope": {
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "decision_time": "2026-06-11T00:01:05Z",
            "event_time": "2026-06-11T00:01:00Z",
            "available_at": "2026-06-11T00:01:00Z",
            "ingested_at": "2026-06-11T00:01:01Z",
            "timeframe_cutoffs": {
                "1m": "2026-06-11T00:01:00Z",
                "5m": "2026-06-11T00:00:00Z",
            },
            "feature_cutoff": "2026-06-11T00:01:00Z",
            "feature_version": "v2_native_feature_snapshot_v1",
            "feature_hash": "hash_direct_trust",
            "data_quality_score": 0.98,
            "data_quality_flags": [],
            "is_backfilled": False,
            "is_final_candle": True,
            "missing_candle_count": 0,
            "duplicate_event_count": 0,
            "out_of_order_event_count": 0,
            "source_disagreement_score": 0.0,
            "latency_ms": 5000,
            "decision_id": "dec_direct_trust",
        },
    }


def test_observation_builder_rejects_dirty_snapshot_on_direct_call() -> None:
    clear_decision_replays()
    snapshot = _clean_snapshot()
    snapshot["market_state_envelope"] = {
        **dict(snapshot["market_state_envelope"]),  # type: ignore[arg-type]
        "is_final_candle": False,
    }
    with pytest.raises(TrustGateRejectedError) as exc_info:
        build_observation_from_snapshot(snapshot)
    replay = get_decision_replay(exc_info.value.decision_id)
    assert replay is not None
    assert replay["block_reason"] == "trust_gate_rejected"


def test_observation_builder_rejects_future_feature_cutoff() -> None:
    snapshot = _clean_snapshot()
    snapshot["market_state_envelope"] = {
        **dict(snapshot["market_state_envelope"]),  # type: ignore[arg-type]
        "feature_cutoff": "2026-06-11T00:02:00Z",
    }
    with pytest.raises(TrustGateRejectedError):
        build_observation_from_snapshot(snapshot)


def test_observation_builder_rejects_mixed_timeframe_data() -> None:
    snapshot = _clean_snapshot()
    snapshot["market_state_envelope"] = {
        **dict(snapshot["market_state_envelope"]),  # type: ignore[arg-type]
        "timeframe_cutoffs": {
            "1m": "2026-06-11T00:01:00Z",
            "5m": "2026-06-11T00:05:00Z",
        },
    }
    with pytest.raises(TrustGateRejectedError):
        build_observation_from_snapshot(snapshot)


def test_masa_adapter_rejects_without_trust_contract() -> None:
    with pytest.raises(ValueError):
        V2MASAAdapter().get_action_and_value([0.0] * 26, feature_snapshot_id="snap")


def test_masa_adapter_rejects_future_cutoff() -> None:
    snapshot = _clean_snapshot()
    obs = build_observation_from_snapshot(snapshot)
    bad_envelope = {
        **dict(snapshot["market_state_envelope"]),  # type: ignore[arg-type]
        "feature_cutoff": "2026-06-11T00:02:00Z",
    }
    with pytest.raises(TrustGateRejectedError):
        V2MASAAdapter().get_action_and_value(
            obs.tensor,
            feature_snapshot_id=obs.feature_snapshot_id,
            market_state_envelope=bad_envelope,
        )
