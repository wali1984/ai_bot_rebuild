"""FreshnessMetadata invariant tests."""

from __future__ import annotations

import dataclasses

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.freshness_metadata import FreshnessMetadata


def test_valid_metadata_constructs(valid_freshness_metadata: FreshnessMetadata) -> None:
    assert len(valid_freshness_metadata.per_feature_status) == 2


def test_duplicate_in_per_feature_last_update_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", 100), ("a", 200)),
            per_feature_age_ms=(("a", 1),),
            per_feature_status=(("a", "fresh"),),
        )


def test_duplicate_in_per_feature_age_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", 100),),
            per_feature_age_ms=(("a", 1), ("a", 2)),
            per_feature_status=(("a", "fresh"),),
        )


def test_duplicate_in_per_feature_status_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", 100),),
            per_feature_age_ms=(("a", 1),),
            per_feature_status=(("a", "fresh"), ("a", "fresh")),
        )


def test_mismatched_feature_set_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", 100), ("b", 200)),
            per_feature_age_ms=(("a", 1), ("b", 2)),
            per_feature_status=(("a", "fresh"),),
        )


def test_empty_feature_name_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("", 100),),
            per_feature_age_ms=(("", 1),),
            per_feature_status=(("", "fresh"),),
        )


def test_negative_last_update_ts_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", -1),),
            per_feature_age_ms=(("a", 1),),
            per_feature_status=(("a", "fresh"),),
        )


def test_negative_age_ms_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", 100),),
            per_feature_age_ms=(("a", -1),),
            per_feature_status=(("a", "fresh"),),
        )


def test_status_outside_allowed_set_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(("a", 100),),
            per_feature_age_ms=(("a", 1),),
            per_feature_status=(("a", "weird"),),
        )


def test_all_three_empty_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FreshnessMetadata(
            per_feature_last_update_ms=(),
            per_feature_age_ms=(),
            per_feature_status=(),
        )


def test_frozen(valid_freshness_metadata: FreshnessMetadata) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        valid_freshness_metadata.per_feature_status = ()  # type: ignore[misc]
