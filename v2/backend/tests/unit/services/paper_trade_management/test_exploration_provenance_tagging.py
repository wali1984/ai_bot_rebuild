"""Change 3 fixtures: bounded information-gain exploration provenance is carried
onto the closed-trade / outcome record so exploration stays separately
attributable from exploitation and is never counted as live profit.
"""

from __future__ import annotations

from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.position_state import (
    PaperNetPosition,
)

BOUNDED = "bounded_information_seeking_exploration"
CHAMPION = "champion_exploitation"


def _position(**overrides: object) -> PaperNetPosition:
    base: dict[str, object] = dict(
        position_id="paper_pos_test",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-14T00:00:00Z",
        source_signal_id="signal_test",
        prediction_id="pred_test",
        market_state_id="market_state_test",
        timeframe="1m",
        feature_snapshot_id="feature_snapshot_test",
        entry_market_state_id="market_state_test",
        strategy_id="trend_following",
        strategy_family="trend_following",
        strategy_selected_mode="trend_following",
        hedge_state="NO_HEDGE",
        hedge_reason="NO_HEDGE_CONTEXT",
        drawdown_at_entry=0.0,
        market_regime_at_entry="trend",
        best_favorable_price=100.0,
        intra_trade_high_price=100.0,
        intra_trade_low_price=100.0,
        last_mark_price=100.0,
        last_mark_est="2026-06-14T00:00:00Z",
        fill_ids=["fill_test"],
        decision_id="decision_test",
        mtf_snapshot_id="mtf_test",
        feature_cutoff="2026-06-13T23:59:59Z",
        decision_time="2026-06-14T00:00:00Z",
        available_at="2026-06-14T00:00:00Z",
        selected_action="long",
        model_version="v2_test",
        checkpoint_id="checkpoint_test",
        source_hashes={"model": "abc123", "feature": "def456"},
        adaptive_policy_authoritative=True,
        adaptive_policy_action_id="apa2_test",
    )
    base.update(overrides)
    return PaperNetPosition(**base)


def _close(position: PaperNetPosition) -> dict:
    close_event, _outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=102.0,
        exit_time="2026-06-14T00:01:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
    )
    return close_event


def test_exploration_close_carries_bounded_information_seeking_provenance() -> None:
    close_event = _close(
        _position(adaptive_policy_action_policy_mode=BOUNDED)
    )

    assert close_event["policy_mode"] == BOUNDED
    assert close_event["adaptive_policy_action_policy_mode"] == BOUNDED
    assert close_event["exploration_provenance"] is True
    assert close_event["counts_as_training_feedback"] is True
    assert close_event["counts_as_live_profit"] is False


def test_exploitation_close_is_separately_attributable() -> None:
    close_event = _close(
        _position(adaptive_policy_action_policy_mode=CHAMPION)
    )

    assert close_event["policy_mode"] == CHAMPION
    # Exploitation is NOT tagged as exploration provenance -> separately
    # attributable from bounded information-gain exploration.
    assert close_event["exploration_provenance"] is False
    assert close_event["counts_as_training_feedback"] is True
    assert close_event["counts_as_live_profit"] is False


def test_position_payload_persists_policy_mode_for_reload() -> None:
    position = _position(adaptive_policy_action_policy_mode=BOUNDED)
    payload = position.to_payload(generated_utc="2026-06-14T00:01:00Z")
    assert payload["adaptive_policy_action_policy_mode"] == BOUNDED
