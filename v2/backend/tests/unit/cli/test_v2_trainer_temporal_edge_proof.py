"""Smoke test for the WI-1 temporal edge-proof (tiny synthetic data, CPU)."""
from __future__ import annotations

from types import SimpleNamespace

from app.cli.v2_trainer_temporal_edge_proof import run_edge_proof
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (
    build_example_windows,
)


def _ex(t, feat, action, move):
    return SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=f"2026-07-12T00:{t // 60:02d}:{t % 60:02d}Z",
        label_action_index=action,
        label_expected_move_after_cost_bps=move,
        tensor=SimpleNamespace(model_vector=(float(feat),)),
    )


def test_edge_proof_runs_and_emits_verdict() -> None:
    # A tiny separable signal: feature > 0 -> long wins, feature < 0 -> short wins.
    exs = []
    for t in range(120):
        feat = 1.0 if t % 2 == 0 else -1.0
        action = 1 if feat > 0 else 2
        move = 20.0 if feat > 0 else -20.0
        exs.append(_ex(t, feat, action, move))
    windows = build_example_windows(exs, seq_len=4)
    report = run_edge_proof(
        windows=windows,
        seq_len=4,
        feature_dim=1,
        epochs=2,
        batch_size=32,
        learning_rate=1e-2,
        hidden=8,
        eval_fraction=0.3,
        device="cpu",
    )
    assert report["verdict"] in {
        "TEMPORAL_ENCODER_IMPROVES_EDGE_INTEGRATE",
        "TEMPORAL_ENCODER_NO_EDGE_GAIN_DO_NOT_INTEGRATE",
    }
    assert report["offline_only"] is True
    assert report["writes_live_checkpoint"] is False
    assert report["live_gate"] == "blocked_human_only"
    # Both probes evaluated on the same held-out window count.
    assert report["eval_windows"] > 0
    assert report["temporal_gru"]["trades"] is not None
