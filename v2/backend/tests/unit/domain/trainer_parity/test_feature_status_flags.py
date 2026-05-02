"""FeatureStatusFlags invariant tests."""

from __future__ import annotations

import dataclasses

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.feature_status_flags import (
    FeatureStatusFlags,
)


def test_valid_flags_construct() -> None:
    flags = FeatureStatusFlags(
        stale=("stale_a",),
        missing=("missing_a",),
        unused=("unused_a",),
    )
    assert flags.stale == ("stale_a",)


def test_duplicate_inside_stale_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureStatusFlags(stale=("a", "a"), missing=(), unused=())


def test_duplicate_inside_missing_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureStatusFlags(stale=(), missing=("a", "a"), unused=())


def test_duplicate_inside_unused_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureStatusFlags(stale=(), missing=(), unused=("a", "a"))


def test_feature_in_stale_and_missing_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureStatusFlags(stale=("x",), missing=("x",), unused=())


def test_feature_in_stale_and_unused_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureStatusFlags(stale=("x",), missing=(), unused=("x",))


def test_feature_in_missing_and_unused_raises() -> None:
    with pytest.raises(TrainerParityLineageError):
        FeatureStatusFlags(stale=(), missing=("x",), unused=("x",))


def test_frozen() -> None:
    flags = FeatureStatusFlags(stale=("a",), missing=("b",), unused=("c",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        flags.stale = ("changed",)  # type: ignore[misc]
