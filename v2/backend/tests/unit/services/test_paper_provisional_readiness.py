from __future__ import annotations

from v2.backend.app.services.paper_provisional.readiness_v1 import (
    READINESS_DIMENSIONS,
    compute_readiness,
    readiness_summary,
)


def test_live_submission_ready_is_never_true():
    r = compute_readiness(
        recovery_checkpoint_train_rows=272,
        paper_loop_running=True,
        provisional_gate_wired=True,
        dry_run_no_submit_proven=True,
        accounting_reconciled=True,
        economic_edge_proven=True,  # even if claimed
        natural_closes=1000,  # even with many closes
    )
    assert r["live_submission_ready"] is False
    assert r["places_real_order"] is False
    assert r["live_gate"] == "blocked_human_only"


def test_first_three_dimensions_can_pass_this_pass():
    r = compute_readiness(
        recovery_checkpoint_train_rows=272,
        paper_loop_running=True,
        provisional_gate_wired=True,
        dry_run_no_submit_proven=True,
        accounting_reconciled=True,
        economic_edge_proven=False,
        natural_closes=0,
    )
    assert r["paper_checkpoint_ready"] is True
    assert r["paper_runtime_ready"] is True
    assert r["execution_dry_run_ready"] is True
    assert r["accounting_ready"] is True
    # economic not proven -> false; no aggregate hides it
    assert r["economic_ready"] is False


def test_checkpoint_not_ready_below_100():
    r = compute_readiness(
        recovery_checkpoint_train_rows=55,
        paper_loop_running=True,
        provisional_gate_wired=True,
        dry_run_no_submit_proven=True,
        accounting_reconciled=True,
        economic_edge_proven=False,
        natural_closes=0,
    )
    assert r["paper_checkpoint_ready"] is False
    assert r["operational_ready"] is False


def test_summary_lists_all_dimensions():
    r = compute_readiness(
        recovery_checkpoint_train_rows=272, paper_loop_running=True,
        provisional_gate_wired=True, dry_run_no_submit_proven=True,
        accounting_reconciled=True, economic_edge_proven=False, natural_closes=0,
    )
    s = readiness_summary(r)
    for dim in READINESS_DIMENSIONS:
        assert dim in s
    assert "live_submission_ready=N" in s
