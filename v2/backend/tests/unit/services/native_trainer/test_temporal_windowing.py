"""WI-1 Step 1 tests: no-lookahead temporal windowing."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (
    build_example_windows,
    model_batch_tensor,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)


def _ex(symbol, timeframe, decision_time, value):
    # model_vector encodes its own frame id (value) so we can assert ordering.
    return SimpleNamespace(
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        tensor=SimpleNamespace(model_vector=(float(value),)),
    )


def test_window_is_causal_no_lookahead() -> None:
    # Frames at t=1..5 for one symbol/timeframe. Each window must contain ONLY
    # frames at or before its own frame (newest last).
    exs = [_ex("BTCUSDT", "1m", f"2026-07-12T00:0{t}:00Z", t) for t in range(1, 6)]
    out = build_example_windows(exs, seq_len=3)
    assert len(out) == 5
    for w in out:
        own = w.window[-1][0]  # newest frame == the example's own frame
        # No frame in the window may be newer than the example's own frame.
        assert all(frame[0] <= own for frame in w.window)
    # The 5th example's window is [3,4,5] (seq_len=3, newest last).
    assert [f[0] for f in out[4].window] == [3.0, 4.0, 5.0]


def test_left_padding_for_short_history() -> None:
    exs = [_ex("BTCUSDT", "1m", f"2026-07-12T00:0{t}:00Z", t) for t in range(1, 3)]
    out = build_example_windows(exs, seq_len=4)
    first = out[0]  # only 1 real frame -> 3 pads of the oldest (itself)
    assert [f[0] for f in first.window] == [1.0, 1.0, 1.0, 1.0]
    assert first.pad_mask == (0, 0, 0, 1)
    assert first.real_frame_count == 1
    second = out[1]  # 2 real frames [1,2] -> pad to [1,1,1,2]
    assert [f[0] for f in second.window] == [1.0, 1.0, 1.0, 2.0]
    assert second.pad_mask == (0, 0, 1, 1)


def test_groups_are_independent_per_symbol_timeframe() -> None:
    exs = [
        _ex("BTCUSDT", "1m", "2026-07-12T00:01:00Z", 1),
        _ex("ETHUSDT", "1m", "2026-07-12T00:01:00Z", 100),
        _ex("BTCUSDT", "1m", "2026-07-12T00:02:00Z", 2),
        _ex("BTCUSDT", "5m", "2026-07-12T00:02:00Z", 500),
    ]
    out = build_example_windows(exs, seq_len=2)
    by_own = {w.window[-1][0]: w for w in out}
    # BTC 1m t=2 window is [1,2]; it must NOT pull in ETH or the BTC 5m frame.
    assert [f[0] for f in by_own[2.0].window] == [1.0, 2.0]
    # ETH 1m has only its own frame -> padded with itself.
    assert [f[0] for f in by_own[100.0].window] == [100.0, 100.0]
    # BTC 5m is a separate series.
    assert [f[0] for f in by_own[500.0].window] == [500.0, 500.0]


def test_missing_decision_time_fails_closed_instead_of_using_input_order() -> None:
    exs = [_ex("BTCUSDT", "1m", None, t) for t in range(1, 4)]
    out = build_example_windows(exs, seq_len=2)
    assert out == []


@pytest.mark.parametrize(
    "decision_time",
    ("not-a-time", "2026-07-12T00:01:00", float("nan"), float("inf"), True),
)
def test_unparseable_decision_time_fails_closed(decision_time: object) -> None:
    assert build_example_windows(
        [_ex("BTCUSDT", "1m", decision_time, 1)],
        seq_len=2,
    ) == []


def test_temporal_batch_rejects_row_missing_from_causal_lookup() -> None:
    row = _ex("BTCUSDT", "1m", None, 1)
    with pytest.raises(ValueError, match="TEMPORAL_WINDOW_MISSING_PARSEABLE_DECISION_TIME"):
        model_batch_tensor(
            object(),
            [row],
            temporal=True,
            seq_len=2,
            window_lookup={},
        )


def _real_training_example(*, minute: int, value: float) -> TrainingExample:
    decision_time = f"2026-07-12T00:{minute:02d}:00Z"
    tensor = FeatureTensorRecord(
        tensor_id=f"tensor-{minute}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"snapshot-{minute}",
        values=(value,),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("close",),
        source_labels=("ohlcv",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=(f"snapshot-{minute}",),
        row_classification="TRAINABLE",
        trust_row={"decision_time": decision_time},
    )


def test_real_training_example_reversed_input_uses_contract_decision_time() -> None:
    # Production TrainingExample has no caller-supplied top-level time here: it
    # must resolve and freeze the actual trust contract's decision_time.
    newest = _real_training_example(minute=3, value=3.0)
    oldest = _real_training_example(minute=1, value=1.0)
    middle = _real_training_example(minute=2, value=2.0)
    original_decision_time = newest.decision_time
    assert original_decision_time == "2026-07-12T00:03:00.000000Z"
    assert newest.trust_row is not None
    newest.trust_row["decision_time"] = "2099-01-01T00:00:00Z"
    assert newest.decision_time == original_decision_time

    out = build_example_windows([newest, oldest, middle], seq_len=3)

    assert len(out) == 3
    # Output stays in caller order, while the newest row's history is rebuilt
    # from t1,t2,t3. The old input-order proxy produced [3,3,3] here.
    assert [frame[0] for frame in out[0].window] == [1.0, 2.0, 3.0]
    assert [frame[0] for frame in out[1].window] == [1.0, 1.0, 1.0]
    assert [frame[0] for frame in out[2].window] == [1.0, 1.0, 2.0]


def test_skips_examples_without_model_vector() -> None:
    exs = [
        _ex("BTCUSDT", "1m", "2026-07-12T00:01:00Z", 1),
        SimpleNamespace(symbol="BTCUSDT", timeframe="1m",
                        decision_time="2026-07-12T00:02:00Z",
                        tensor=SimpleNamespace(model_vector=None)),
    ]
    out = build_example_windows(exs, seq_len=2)
    assert len(out) == 1
    assert out[0].window[-1][0] == 1.0


def test_output_preserves_input_order_of_kept_examples() -> None:
    exs = [
        _ex("BTCUSDT", "1m", "2026-07-12T00:03:00Z", 3),
        _ex("ETHUSDT", "1m", "2026-07-12T00:01:00Z", 10),
        _ex("BTCUSDT", "1m", "2026-07-12T00:01:00Z", 1),
    ]
    out = build_example_windows(exs, seq_len=2)
    # Order follows the original input index, not the per-group time sort.
    assert [w.window[-1][0] for w in out] == [3.0, 10.0, 1.0]
