"""FeatureFreshnessEnvelope invariant tests."""

from __future__ import annotations

import dataclasses

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.feature_status_flags import (
    FeatureFreshnessEnvelope,
)


def test_valid_envelope_constructs() -> None:
    env = FeatureFreshnessEnvelope(
        per_source_freshness_ms=(("a", 100), ("b", 200)),
        oldest_source_age_ms=200,
        oldest_source_name="b",
    )
    assert env.oldest_source_age_ms == 200


def test_negative_oldest_source_age_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureFreshnessEnvelope(
            per_source_freshness_ms=(("a", 100),),
            oldest_source_age_ms=-1,
            oldest_source_name="a",
        )


def test_empty_oldest_source_name_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureFreshnessEnvelope(
            per_source_freshness_ms=(("a", 100),),
            oldest_source_age_ms=100,
            oldest_source_name="",
        )


def test_duplicate_source_name_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureFreshnessEnvelope(
            per_source_freshness_ms=(("a", 100), ("a", 200)),
            oldest_source_age_ms=200,
            oldest_source_name="a",
        )


def test_negative_freshness_ms_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureFreshnessEnvelope(
            per_source_freshness_ms=(("a", -1),),
            oldest_source_age_ms=0,
            oldest_source_name="a",
        )


def test_oldest_age_mismatch_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureFreshnessEnvelope(
            per_source_freshness_ms=(("a", 100), ("b", 200)),
            oldest_source_age_ms=999,
            oldest_source_name="b",
        )


def test_oldest_name_mismatch_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureFreshnessEnvelope(
            per_source_freshness_ms=(("a", 100), ("b", 200)),
            oldest_source_age_ms=200,
            oldest_source_name="a",
        )


def test_frozen() -> None:
    env = FeatureFreshnessEnvelope(
        per_source_freshness_ms=(("a", 100),),
        oldest_source_age_ms=100,
        oldest_source_name="a",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        env.oldest_source_age_ms = 0  # type: ignore[misc]
