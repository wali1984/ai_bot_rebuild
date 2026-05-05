import dataclasses

import v2.backend.app.domain.orchestrator_decision as subject


def test_public_surface_matches_spec_order_and_objects():
    expected = (
        "OrchestratorDecisionDomainError",
        "OrchestratorDecisionRecord",
        "DECISION_ACTION_OPEN_LONG",
        "DECISION_ACTION_OPEN_SHORT",
        "DECISION_ACTION_HOLD",
        "DECISION_ACTION_ABSTAIN",
        "DECISION_REASON_PROCEED_LONG",
        "DECISION_REASON_PROCEED_SHORT",
        "DECISION_REASON_HOLD_FLAT_DIRECTION",
        "DECISION_REASON_ABSTAIN_LOW_CONFIDENCE",
        "DECISION_REASON_ABSTAIN_FRESHNESS_STALE",
        "DECISION_REASON_ABSTAIN_FRESHNESS_MISSING",
        "DECISION_REASON_ABSTAIN_WORKER_DEGRADED",
        "DECISION_REASON_ABSTAIN_WORKER_CRITICAL",
        "DECISION_REASON_ABSTAIN_WORKER_UNKNOWN",
    )
    assert subject.__all__ == expected
    assert issubclass(subject.OrchestratorDecisionDomainError, ValueError)
    assert dataclasses.is_dataclass(subject.OrchestratorDecisionRecord)
    assert subject.OrchestratorDecisionRecord.__dataclass_params__.frozen is True
    for name in expected[2:]:
        assert isinstance(getattr(subject, name), str)
