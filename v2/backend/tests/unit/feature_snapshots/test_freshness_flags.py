from v2.backend.app.domain.features.freshness import assess_freshness


def test_freshness_marks_stale_source_by_age():
    result = assess_freshness(
        "binance_price",
        "2026-05-02T05:59:00+00:00",
        "2026-05-02T06:00:00+00:00",
        5_000,
    )

    assert result.stale is True
    assert result.missing is False
    assert result.age_ms == 60_000


def test_freshness_marks_missing_source():
    result = assess_freshness("coinank", None, "2026-05-02T06:00:00+00:00", 10_000)

    assert result.missing is True
    assert result.stale is False

