def test_prediction_direction_constants() -> None:
    from v2.backend.app.domain.trainer_prediction_output import (
        PREDICTION_DIRECTION_FLAT,
        PREDICTION_DIRECTION_LONG,
        PREDICTION_DIRECTION_SHORT,
    )

    assert PREDICTION_DIRECTION_LONG == "long"
    assert PREDICTION_DIRECTION_SHORT == "short"
    assert PREDICTION_DIRECTION_FLAT == "flat"
