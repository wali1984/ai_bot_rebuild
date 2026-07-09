"""Alt-data confluence consumption invariants for preemptive edge control.

Proves: alt-data can block / demote to reduce-size / require hedge, its
absence never blocks, and it can never promote a decision toward ALLOW.
"""

from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.decision import evaluate_candidate

from .test_decision_hard_rules import GUARDIAN_ALLOW, _candidate, _winning_history


def _confluence(features: dict, present: bool = True) -> dict:
    return {
        "schema_version": "altdata_confluence_v1",
        "actual_payload_present": present,
        "providers_present": ["coinglass", "moralis"],
        "feature_cutoff": "2026-07-09T00:00:00+00:00",
        "features": features,
    }


def _allowed_decision(**kwargs):
    return evaluate_candidate(
        _candidate(),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
        **kwargs,
    )


def test_baseline_candidate_allows_without_altdata():
    decision = _allowed_decision()
    assert decision["preemptive_decision"] == "ALLOW"
    assert decision["altdata_confluence_present"] is False


def test_missing_altdata_never_blocks():
    decision = _allowed_decision(altdata_confluence=None)
    assert decision["preemptive_decision"] == "ALLOW"
    assert "ALTDATA_TRADE_BLOCK_SCORE_HIGH" not in decision["preemptive_decision_reasons"]


def test_high_block_score_forces_no_trade():
    decision = _allowed_decision(
        altdata_confluence=_confluence({"altdata_trade_block_score": 0.85})
    )
    assert decision["preemptive_decision"] == "NO_TRADE"
    assert "ALTDATA_TRADE_BLOCK_SCORE_HIGH" in decision["preemptive_decision_reasons"]
    assert decision["altdata_trade_block_score"] == 0.85
    assert decision["altdata_can_approve_alone"] is False


def test_reduce_score_demotes_allow_to_reduce_size():
    decision = _allowed_decision(
        altdata_confluence=_confluence({"altdata_reduce_size_score": 0.65})
    )
    assert decision["preemptive_decision"] == "REDUCE_SIZE_PAPER_ONLY"
    assert "ALTDATA_REDUCE_SIZE_SCORE_ELEVATED" in decision["preemptive_decision_reasons"]


def test_wallet_distribution_conflict_demotes_long():
    decision = _allowed_decision(
        altdata_confluence=_confluence({"altdata_wallet_distribution_score": 0.75})
    )
    assert decision["preemptive_decision"] == "REDUCE_SIZE_PAPER_ONLY"
    assert (
        "ALTDATA_WALLET_DISTRIBUTION_CONFLICTS_LONG"
        in decision["preemptive_decision_reasons"]
    )


def test_hedge_required_flag_carried_without_promotion():
    decision = _allowed_decision(
        altdata_confluence=_confluence({"altdata_hedge_required_score": 0.8})
    )
    assert decision["altdata_hedge_required"] is True
    assert "ALTDATA_HEDGE_REQUIRED" in decision["preemptive_decision_reasons"]
    # Hedge requirement alone does not block a healthy candidate.
    assert decision["preemptive_decision"] == "ALLOW"


def test_good_altdata_cannot_rescue_blocked_candidate():
    decision = evaluate_candidate(
        _candidate(expected_move_after_cost_bps=-5.0),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
        altdata_confluence=_confluence(
            {
                "altdata_confluence_long_score": 0.95,
                "altdata_trade_block_score": 0.0,
                "altdata_reduce_size_score": 0.0,
            }
        ),
    )
    assert decision["preemptive_decision"] == "NO_TRADE"


def test_heartbeat_only_payload_is_ignored():
    decision = _allowed_decision(
        altdata_confluence=_confluence({"altdata_trade_block_score": 0.99}, present=False)
    )
    assert decision["preemptive_decision"] == "ALLOW"
    assert decision["altdata_confluence_present"] is False
