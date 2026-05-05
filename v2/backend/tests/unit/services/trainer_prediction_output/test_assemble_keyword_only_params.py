import pytest

from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record


def test_assemble_keyword_only_params() -> None:
    with pytest.raises(TypeError):
        assemble_prediction_record(
            "pred-1",
            "snapshot-1",
            "BTCUSDT",
            "model-v1",
            "checkpoint-1",
            "long",
            0.7,
            0.65,
            "worker-1",
            "HEALTHY",
            "fresh",
            250,
            ("alpha",),
            ("beta",),
            lambda: 1,
        )
