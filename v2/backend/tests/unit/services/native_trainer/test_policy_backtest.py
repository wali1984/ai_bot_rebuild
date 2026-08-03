from __future__ import annotations

from types import SimpleNamespace

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.policy_backtest import (
    run_policy_archive_backtest,
)


def _example(
    index: int,
    *,
    label: float | None = 4.0,
    vector: list[float] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=f"2026-07-18T00:{index:02d}:00Z",
        label_available_at=f"2026-07-18T00:{index:02d}:30Z",
        label_expected_move_after_cost_bps=label,
        tensor=SimpleNamespace(
            tensor_id=f"tensor-{index}",
            feature_snapshot_id=f"snapshot-{index}",
            model_vector=vector if vector is not None else [0.1, 0.2, 0.3, 0.4],
        ),
    )


def _model() -> V2HybridPolicyModel:
    model = V2HybridPolicyModel(input_dim=4, seed=7)
    if not model.torch_available:
        pytest.skip("policy backtest requires torch")
    return model


def test_backtest_requires_untouched_forward_partition_proof() -> None:
    report = run_policy_archive_backtest(
        model=_model(),
        examples=[_example(2)],
        excluded_training_examples=[_example(1)],
    )

    assert report["status"] == "BLOCKED_UNTOUCHED_FORWARD_PARTITION_NOT_PROVEN"
    assert report["counts_as_A_plus"] is False
    assert report["counts_as_live_ready"] is False


def test_backtest_rejects_training_overlap_and_duplicate_forward_rows() -> None:
    shared = _example(2)
    overlap = run_policy_archive_backtest(
        model=_model(),
        examples=[shared],
        excluded_training_examples=[shared],
        untouched_forward_partition_proven=True,
    )
    duplicate = run_policy_archive_backtest(
        model=_model(),
        examples=[shared, shared],
        untouched_forward_partition_proven=True,
    )

    assert overlap["status"] == "BLOCKED_FORWARD_PARTITION_IDENTITY_OVERLAP"
    assert overlap["partition_overlap_count"] == 1
    assert duplicate["status"] == "BLOCKED_FORWARD_PARTITION_IDENTITY_OVERLAP"
    assert duplicate["duplicate_forward_row_count"] == 1


@pytest.mark.parametrize(
    "row",
    [
        _example(2, label=None),
        _example(2, label=float("nan")),
        _example(2, vector=[0.1, float("inf"), 0.3, 0.4]),
    ],
)
def test_backtest_rejects_missing_or_nonfinite_forward_evidence(
    row: SimpleNamespace,
) -> None:
    report = run_policy_archive_backtest(
        model=_model(),
        examples=[row],
        excluded_training_examples=[_example(1)],
        untouched_forward_partition_proven=True,
    )

    assert report["status"] == "BLOCKED_INVALID_FORWARD_ROW"
    assert report["invalid_forward_row_count"] == 1


def test_valid_forward_diagnostic_never_claims_readiness_or_fictional_leverage() -> None:
    report = run_policy_archive_backtest(
        model=_model(),
        examples=[_example(2), _example(3, label=-3.0)],
        excluded_training_examples=[_example(1)],
        untouched_forward_partition_proven=True,
    )

    assert report["status"] == "OK_UNTOUCHED_FORWARD_DIAGNOSTIC_ONLY"
    assert report["evidence_class"] == "UNTOUCHED_FORWARD_DIAGNOSTIC_NOT_READINESS"
    assert report["a_plus_readiness_signal"] is False
    assert report["counts_as_A_plus"] is False
    assert report["counts_as_live_ready"] is False
    assert report["leverage_margin_exploration"]["status"] == (
        "NOT_EVALUATED_MISSING_EVIDENCE_BOUND_PAPER_RISK_INPUTS"
    )
    assert report["leverage_margin_exploration"][
        "fictional_stop_equity_notional_inputs_used"
    ] is False
