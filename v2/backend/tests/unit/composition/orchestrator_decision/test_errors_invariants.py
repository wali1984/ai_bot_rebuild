import pytest


def test_errors_invariants() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        OrchestratorDecisionCompositionError,
    )

    error = OrchestratorDecisionCompositionError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    with pytest.raises(TypeError):
        OrchestratorDecisionCompositionError("some_code")
