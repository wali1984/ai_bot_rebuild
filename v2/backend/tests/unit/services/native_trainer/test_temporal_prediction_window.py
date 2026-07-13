"""WI-1 Step 4c: online rolling-window buffer for the PREDICTION path.

Training builds no-lookahead windows from the batch; live/paper inference sees one
frame at a time. These lock in that V2HybridPolicyModel.forward() folds each frame
into a per-(symbol,timeframe) rolling window when the GRU is enabled -- deduped by
frame id (the live loop re-presents the same latest snapshot across cycles) -- and
that the single-frame path is byte-identical when temporal is off.
"""
from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)

torch = pytest.importorskip("torch")


def _rec(idx: int, snapshot_id: str, *, symbol: str = "BTCUSDT", timeframe: str = "1m") -> FeatureTensorRecord:
    # 1 feature value -> model_vector = value + missing + stale + source = 4 dims.
    return FeatureTensorRecord(
        tensor_id=f"tensor_{idx}",
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=snapshot_id,
        values=(float(idx),),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )


def _temporal_model(monkeypatch, *, seq_len: int = 4):
    monkeypatch.setenv("V2_TRAINER_TEMPORAL_ENCODER", "gru")
    monkeypatch.setenv("V2_TRAINER_TEMPORAL_SEQ_LEN", str(seq_len))
    monkeypatch.setenv("V2_TRAINER_TEMPORAL_HIDDEN", "32")
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "64")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    m = V2HybridPolicyModel(input_dim=4)
    if not m.torch_available:
        pytest.skip("torch unavailable")
    return m


def test_window_slides_dedupes_and_stays_causal(monkeypatch) -> None:
    m = _temporal_model(monkeypatch, seq_len=4)
    key = ("BTCUSDT", "1m")

    # First frame -> buffer has exactly 1 real frame; window is left-padded to seq_len.
    out0 = m.forward(_rec(0, "snap0"))
    assert out0 is not None and isinstance(out0.selected_action, str) and out0.selected_action
    buf = m._temporal_predict_buffers[key]
    assert len(buf) == 1
    win0 = m._temporal_predict_window(_rec(0, "snap0"), [float(v) for v in _rec(0, "snap0").model_vector])
    assert len(win0) == 4  # left-padded to seq_len
    assert win0[0] == win0[1]  # padding repeats the oldest real frame

    # Re-presenting the SAME snapshot must NOT append (dedupe by frame id).
    m.forward(_rec(0, "snap0"))
    assert len(buf) == 1

    # New frames slide the window; it caps at seq_len and keeps the newest last.
    for i in range(1, 6):
        m.forward(_rec(i, f"snap{i}"))
    assert len(buf) == 4  # capped at maxlen=seq_len
    assert buf[-1][0] == 5.0  # newest frame is the current one (causal: current last)
    assert buf[0][0] == 2.0   # oldest retained is frame 2 (0,1 evicted)


def test_distinct_symbols_get_separate_windows(monkeypatch) -> None:
    m = _temporal_model(monkeypatch, seq_len=4)
    m.forward(_rec(0, "a0", symbol="BTCUSDT"))
    m.forward(_rec(1, "b0", symbol="ETHUSDT"))
    assert set(m._temporal_predict_buffers) == {("BTCUSDT", "1m"), ("ETHUSDT", "1m")}
    assert len(m._temporal_predict_buffers[("BTCUSDT", "1m")]) == 1
    assert len(m._temporal_predict_buffers[("ETHUSDT", "1m")]) == 1


def test_temporal_off_keeps_single_frame_path(monkeypatch) -> None:
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "64")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    m = V2HybridPolicyModel(input_dim=4)
    if not m.torch_available:
        pytest.skip("torch unavailable")
    assert m.temporal_encoder_enabled is False
    assert m._temporal_predict_window(_rec(0, "snap0"), [0.0, 0.0, 0.0, 0.0]) is None
    m.forward(_rec(0, "snap0"))
    assert m._temporal_predict_buffers == {}  # no buffering when temporal is off
