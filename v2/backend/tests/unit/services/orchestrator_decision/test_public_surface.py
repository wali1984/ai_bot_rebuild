def test_public_surface() -> None:
    import v2.backend.app.services.orchestrator_decision as module

    assert module.__all__ == (
        "assemble_orchestrator_decision_record",
        "OrchestratorDecisionServiceError",
    )
    assert callable(module.assemble_orchestrator_decision_record)
    assert issubclass(module.OrchestratorDecisionServiceError, ValueError)
