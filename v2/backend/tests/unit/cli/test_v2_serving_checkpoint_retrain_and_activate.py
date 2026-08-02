"""Gate semantics for the serving-checkpoint retrain/activate orchestrator.

The orchestrator must never activate a serving checkpoint that the registry
would reject, and must name the blocking proof for the operator report.
"""

from __future__ import annotations

import pytest

from v2.backend.app.cli.v2_serving_checkpoint_retrain_and_activate import (
    ECONOMIC_COHORT_KEY,
    LEGACY_COHORT_KEY,
    REQUIRED_SMOKE_PROOFS,
    _gate_reasons,
    cohort_binding_reasons,
)


def _passing_smoke() -> dict[str, object]:
    smoke: dict[str, object] = {proof: True for proof in REQUIRED_SMOKE_PROOFS}
    smoke["serving_smoke_positive_directional_edge_rate"] = 0.75
    smoke["directional_net_edge_model_valid"] = True
    return smoke


def test_fully_proven_smoke_has_no_gate_reasons() -> None:
    assert _gate_reasons(_passing_smoke()) == []


@pytest.mark.parametrize("proof", REQUIRED_SMOKE_PROOFS)
def test_each_missing_proof_blocks_and_is_named(proof: str) -> None:
    smoke = _passing_smoke()
    smoke[proof] = False
    reasons = _gate_reasons(smoke)
    assert f"SMOKE_{proof.upper()}_NOT_PROVEN" in reasons


@pytest.mark.parametrize("rate", [0.0, -0.1, None, "not-a-number"])
def test_non_positive_directional_edge_rate_blocks_activation(rate: object) -> None:
    smoke = _passing_smoke()
    smoke["serving_smoke_positive_directional_edge_rate"] = rate
    assert "SMOKE_POSITIVE_DIRECTIONAL_EDGE_RATE_NOT_POSITIVE" in _gate_reasons(smoke)


def test_missing_edge_rate_key_blocks_activation() -> None:
    smoke = _passing_smoke()
    del smoke["serving_smoke_positive_directional_edge_rate"]
    assert "SMOKE_POSITIVE_DIRECTIONAL_EDGE_RATE_NOT_POSITIVE" in _gate_reasons(smoke)


def test_invalid_directional_net_edge_model_blocks_activation() -> None:
    smoke = _passing_smoke()
    smoke["directional_net_edge_model_valid"] = False
    assert "SMOKE_DIRECTIONAL_NET_EDGE_MODEL_INVALID" in _gate_reasons(smoke)


def test_empty_smoke_blocks_on_every_proof() -> None:
    reasons = _gate_reasons({})
    for proof in REQUIRED_SMOKE_PROOFS:
        assert f"SMOKE_{proof.upper()}_NOT_PROVEN" in reasons
    assert "SMOKE_POSITIVE_DIRECTIONAL_EDGE_RATE_NOT_POSITIVE" in reasons


# --------------------------------------------------------------------------- #
# Cohort binding: the serving runtime rejects every prediction whose checkpoint
# the governed cohort records do not name (COHORT_CHECKPOINT_MISMATCH), which
# takes publication to zero.  Activation must fail closed instead.
# --------------------------------------------------------------------------- #
CHECKPOINT = "SERVING_ABI_V2_PAPER_deadbeefdeadbeefdeadbeef"


def _bound_cohorts(checkpoint_id: str = CHECKPOINT) -> dict[str, object]:
    return {
        ECONOMIC_COHORT_KEY: {"checkpoint_id": checkpoint_id},
        LEGACY_COHORT_KEY: {"checkpoint_id": checkpoint_id},
    }


def test_cohort_bound_to_checkpoint_does_not_block() -> None:
    assert cohort_binding_reasons(_bound_cohorts(), CHECKPOINT) == []


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (ECONOMIC_COHORT_KEY, "ECONOMIC_COHORT_DOES_NOT_BIND_CHECKPOINT"),
        (LEGACY_COHORT_KEY, "LEGACY_COHORT_DOES_NOT_BIND_CHECKPOINT"),
    ],
)
def test_cohort_bound_to_a_different_checkpoint_blocks(key: str, expected: str) -> None:
    cohorts = _bound_cohorts()
    cohorts[key] = {"checkpoint_id": "SERVING_ABI_V2_PAPER_someotherincumbent"}
    assert expected in cohort_binding_reasons(cohorts, CHECKPOINT)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (ECONOMIC_COHORT_KEY, "ECONOMIC_COHORT_RECORD_MISSING"),
        (LEGACY_COHORT_KEY, "LEGACY_COHORT_RECORD_MISSING"),
    ],
)
def test_missing_cohort_record_blocks(key: str, expected: str) -> None:
    cohorts = _bound_cohorts()
    cohorts[key] = None
    assert expected in cohort_binding_reasons(cohorts, CHECKPOINT)


def test_no_cohort_records_at_all_blocks_both() -> None:
    reasons = cohort_binding_reasons({}, CHECKPOINT)
    assert "ECONOMIC_COHORT_RECORD_MISSING" in reasons
    assert "LEGACY_COHORT_RECORD_MISSING" in reasons
