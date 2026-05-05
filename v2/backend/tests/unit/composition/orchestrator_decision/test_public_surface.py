def test_public_surface() -> None:
    from v2.backend.app.composition import orchestrator_decision

    assert orchestrator_decision.__all__ == (
        "build_orchestrator_decision_evaluator",
        "OrchestratorDecisionEvaluator",
        "OrchestratorDecisionCompositionError",
    )
    assert callable(orchestrator_decision.build_orchestrator_decision_evaluator)
    assert isinstance(orchestrator_decision.OrchestratorDecisionCompositionError, type)
    assert issubclass(orchestrator_decision.OrchestratorDecisionCompositionError, Exception)
    assert not issubclass(orchestrator_decision.OrchestratorDecisionCompositionError, ValueError)
    assert orchestrator_decision.OrchestratorDecisionEvaluator is not None
