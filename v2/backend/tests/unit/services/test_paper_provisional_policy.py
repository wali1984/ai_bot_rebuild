from __future__ import annotations

from v2.backend.app.services.paper_provisional.policy_v1 import (
    PAPER_PROVISIONAL_CHECKPOINT_CLASSIFICATION,
    STRICT_CHAMPION_MIN_TRAIN_ROWS,
    PaperProvisionalCheckpointPolicyV1,
    cohort_identity,
    load_paper_provisional_policy_v1,
)


def test_gate_passes_at_100_and_default_is_100():
    p = PaperProvisionalCheckpointPolicyV1()
    assert p.minimum_paper_provisional_train_rows == 100
    g = p.gate(train_rows=272)
    assert g["paper_provisional_gate_satisfied"] is True
    assert g["paper_min_train_rows"] == 100
    assert g["display"] == "paper checkpoint: 272/100 PASS"
    assert p.gate(train_rows=55)["paper_provisional_gate_satisfied"] is False
    assert p.gate(train_rows=None)["paper_provisional_gate_satisfied"] is False


def test_strict_gate_never_lowered_by_this_policy():
    p = load_paper_provisional_policy_v1({"PAPER_MIN_TRAIN_ROWS": "100"})
    assert p.strict_champion_min_train_rows == STRICT_CHAMPION_MIN_TRAIN_ROWS == 1000
    # Env cannot lower the strict gate through this policy.
    p2 = load_paper_provisional_policy_v1(
        {"PAPER_MIN_TRAIN_ROWS": "100", "STRICT_CHAMPION_MIN_TRAIN_ROWS": "0"}
    )
    assert p2.strict_champion_min_train_rows == 1000


def test_classification_and_eligibility_are_paper_only_never_live():
    p = PaperProvisionalCheckpointPolicyV1()
    assert p.classify(train_rows=272) == PAPER_PROVISIONAL_CHECKPOINT_CLASSIFICATION
    assert p.classify(train_rows=55) == "PAPER_PROVISIONAL_TRAIN_ROWS_PENDING"
    tags = p.eligibility_tags(train_rows=272)
    assert tags["paper_eligible"] is True
    assert tags["paper_provisional_checkpoint"] is True
    assert tags["engineering_canary"] is False
    assert tags["requires_per_trade_economic_exception"] is False
    # Never-live safety anchors always present.
    assert tags["checkpoint_promotable"] is False
    assert tags["non_promotable"] is True
    assert tags["live_eligible"] is False
    assert tags["routes_to_live"] is False
    assert tags["places_real_order"] is False
    assert tags["economic_certification"] == "PROVISIONAL"
    assert tags["live_gate"] == "blocked_human_only"


def test_eligibility_false_below_gate():
    p = PaperProvisionalCheckpointPolicyV1()
    tags = p.eligibility_tags(train_rows=55)
    assert tags["paper_eligible"] is False
    assert tags["paper_provisional_checkpoint"] is False
    # Safety anchors still never-live even when not yet eligible.
    assert tags["live_eligible"] is False


def test_provisional_limits_are_tight_paper_controls():
    p = PaperProvisionalCheckpointPolicyV1()
    lim = p.limits.to_dict()
    assert lim["maximum_concurrent_positions"] == 1
    assert lim["maximum_notional_per_position_usd"] == 100.0  # operator cap, not hardcoded $10
    assert lim["maximum_total_exposure_usd"] == 100.0
    assert lim["lowest_permitted_leverage"] == 1.0
    assert lim["mandatory_stop"] is True
    assert lim["reduce_only_close"] is True
    assert lim["pyramiding"] is False
    assert lim["averaging_down"] is False
    assert lim["automatic_hedging"] is False


def test_cohort_identity_is_fresh_and_never_relabels_history():
    c = cohort_identity(
        checkpoint_id="paper_recovery_ck_abc",
        activation_time_utc="2026-07-25T18:00:00Z",
        initial_paper_equity_usd=2985.59,
    )
    assert c["paper_strategy_cohort_id"] == (
        "paper_provisional:paper_recovery_ck_abc:2026-07-25T18:00:00Z"
    )
    assert c["paper_cohort_initial_equity_usd"] == 2985.59
    assert c["live_eligible"] is False


def test_exposure_cap_is_not_hardcoded_ten_and_env_configurable():
    from v2.backend.app.services.paper_provisional.policy_v1 import (
        DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD,
        load_paper_provisional_policy_v1,
    )
    p = load_paper_provisional_policy_v1({})
    assert p.limits.maximum_notional_per_position_usd == DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD
    assert p.limits.maximum_notional_per_position_usd > 10.0  # not the old hardcoded $10
    p2 = load_paper_provisional_policy_v1({"PAPER_PROVISIONAL_MAX_NOTIONAL_USD": "60"})
    assert p2.limits.maximum_notional_per_position_usd == 60.0


def test_minimum_valid_notional_accounts_for_reduce_size_haircut():
    from v2.backend.app.services.paper_provisional.policy_v1 import minimum_valid_notional
    # venue min $5, REDUCE_SIZE 0.35 -> request must be 5/0.35 ~= 14.29
    v = minimum_valid_notional(
        venue_minimum_notional_usd=5.0, microstructure_liquidity_multiplier=0.35
    )
    assert round(v, 2) == 14.29


def test_provisional_notional_plan_fits_and_rejects():
    from v2.backend.app.services.paper_provisional.policy_v1 import provisional_notional_plan
    ok = provisional_notional_plan(
        venue_minimum_notional_usd=5.0, minimum_quantity=0.001, mark_price_usd=3000.0,
        microstructure_liquidity_multiplier=0.35, exposure_cap_usd=100.0,
        free_margin_usd=2900.0, effective_leverage=1.0,
    )
    assert ok["fits_within_cohort_exposure_cap"] is True
    assert ok["request_notional_usd"] >= ok["minimum_valid_notional_usd"]
    assert ok["reject_reason"] is None
    # A too-tight cap rejects rather than forcing a fit above budget.
    bad = provisional_notional_plan(
        venue_minimum_notional_usd=100.0, minimum_quantity=0.001, mark_price_usd=3000.0,
        microstructure_liquidity_multiplier=0.35, exposure_cap_usd=10.0,
        free_margin_usd=2900.0, effective_leverage=1.0,
    )
    assert bad["fits_within_cohort_exposure_cap"] is False
    assert bad["request_notional_usd"] is None
    assert "CHOOSE_ANOTHER_SYMBOL" in bad["reject_reason"]
