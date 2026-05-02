"""Public surface test for the trainer_parity package."""

from __future__ import annotations

import inspect

import v2.backend.app.domain.trainer_parity as trainer_parity


_EXPECTED: frozenset[str] = frozenset(
    {
        "FeatureFreshnessEnvelope",
        "FeatureStatusFlags",
        "FreshnessMetadata",
        "StageATrainerRecord",
        "StageBTrainerRecord",
        "TrainerParityLineageError",
        "validate_stage_a_explainability",
        "validate_stage_a_lineage",
        "validate_stage_b_lineage",
    }
)


def test_all_matches_expected() -> None:
    assert set(trainer_parity.__all__) == set(_EXPECTED)
    assert len(trainer_parity.__all__) == 9
    assert len(set(trainer_parity.__all__)) == 9


def test_each_exported_name_exists_and_is_class_or_function() -> None:
    for name in _EXPECTED:
        obj = getattr(trainer_parity, name)
        assert inspect.isclass(obj) or inspect.isfunction(obj), name


def test_confidence_explainability_not_in_all() -> None:
    assert "ConfidenceExplainability" not in trainer_parity.__all__


def test_errors_submodule_not_in_all() -> None:
    assert "errors" not in trainer_parity.__all__


def test_no_allowed_constants_in_all() -> None:
    for name in trainer_parity.__all__:
        assert not name.startswith("_ALLOWED_"), name
