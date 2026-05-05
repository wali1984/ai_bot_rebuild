def test_prediction_freshness_constants() -> None:
    from v2.backend.app.domain.trainer_prediction_output import (
        PREDICTION_FRESHNESS_FRESH,
        PREDICTION_FRESHNESS_MISSING,
        PREDICTION_FRESHNESS_STALE,
    )

    assert PREDICTION_FRESHNESS_FRESH == "fresh"
    assert PREDICTION_FRESHNESS_STALE == "stale"
    assert PREDICTION_FRESHNESS_MISSING == "missing"
