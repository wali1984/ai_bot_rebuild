from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.risk_metrics import (
    cvar,
    downside_deviation,
    risk_adjusted_summary,
    sortino_ratio,
)


def test_risk_metrics_report_signed_tail_loss_and_sortino() -> None:
    returns = [10.0, 6.0, 2.0, -4.0, -20.0]

    summary = risk_adjusted_summary(returns, cvar_alpha=0.4)

    assert summary["count"] == 5
    assert summary["win_rate"] == 0.6
    assert summary["cvar"] == -12.0
    assert summary["worst_return"] == -20.0
    assert summary["sortino_ratio"] == sortino_ratio(returns)
    assert cvar(returns, alpha=0.4) == -12.0


def test_sortino_none_when_empty_or_losing_with_no_downside() -> None:
    # Empty series -> undefined.
    assert sortino_ratio([]) is None
    # Non-positive mean with zero downside (all exactly at target) -> undefined,
    # must NOT read as a passable ratio in the gate.
    assert sortino_ratio([0.0, 0.0, 0.0]) is None


def test_sortino_unbounded_upside_returns_large_finite() -> None:
    # Positive mean with no downside -> large finite sentinel so gates compare.
    ratio = sortino_ratio([3.0, 5.0, 1.0])
    assert ratio == 1e6


def test_downside_deviation_only_counts_below_target() -> None:
    # Upside is ignored; deviation driven purely by the -6 observation.
    dd = downside_deviation([10.0, 10.0, -6.0])
    assert round(dd, 6) == round((36.0 / 3.0) ** 0.5, 6)


def test_cvar_and_summary_none_on_empty() -> None:
    assert cvar([]) is None
    summary = risk_adjusted_summary([])
    assert summary["count"] == 0
    assert summary["sortino_ratio"] is None
    assert summary["cvar"] is None
    assert summary["mean_return"] is None
