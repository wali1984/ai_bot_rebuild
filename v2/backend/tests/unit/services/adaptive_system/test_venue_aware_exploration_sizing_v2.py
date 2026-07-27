from __future__ import annotations

from v2.backend.app.services.adaptive_system.venue_aware_exploration_sizing_v2 import (
    EXECUTABLE,
    SELECT_ANOTHER,
    propose_exploration_size,
)


def test_smallest_venue_executable_size_within_envelope():
    # OPUSDT-like: mark 0.63, 2% stop, $5 venue min. Smallest exec size = ~$5 notional,
    # bounded loss ~$0.10 — comfortably inside a $25 catastrophic per-trade loss ceiling.
    p = propose_exploration_size(
        mark_price=0.63,
        stop_distance_fraction=0.02,
        venue_min_notional=5.0,
        venue_min_qty=1.0,
        venue_qty_step=1.0,
        catastrophic_max_loss_usd=25.0,
        catastrophic_max_notional_usd=1500.0,
    )
    assert p.decision == EXECUTABLE
    assert p.executable is True
    assert p.final_notional_usd >= 5.0
    assert p.max_loss_if_stop_usd <= 25.0


def test_qty_rounds_up_to_valid_step():
    p = propose_exploration_size(
        mark_price=0.63,
        stop_distance_fraction=0.02,
        venue_min_notional=5.0,
        venue_min_qty=1.0,
        venue_qty_step=1.0,
        catastrophic_max_loss_usd=25.0,
        catastrophic_max_notional_usd=1500.0,
    )
    # 5/0.63 = 7.94 -> rounds up to 8 whole units
    assert p.final_quantity == 8.0


def test_venue_minimum_exceeds_notional_ceiling_selects_another():
    # tiny catastrophic notional ceiling below the venue minimum -> do NOT force
    p = propose_exploration_size(
        mark_price=0.63,
        stop_distance_fraction=0.02,
        venue_min_notional=5.0,
        venue_min_qty=1.0,
        venue_qty_step=1.0,
        catastrophic_max_loss_usd=25.0,
        catastrophic_max_notional_usd=3.0,
    )
    assert p.decision == SELECT_ANOTHER
    assert p.executable is False
    assert p.reason == "VENUE_MINIMUM_EXCEEDS_CATASTROPHIC_NOTIONAL_CEILING"


def test_bounded_loss_exceeds_loss_ceiling_selects_another():
    # wide stop makes even the venue-minimum bounded loss exceed the loss ceiling
    p = propose_exploration_size(
        mark_price=0.63,
        stop_distance_fraction=0.50,  # absurd 50% stop
        venue_min_notional=5.0,
        venue_min_qty=1.0,
        venue_qty_step=1.0,
        catastrophic_max_loss_usd=1.0,
        catastrophic_max_notional_usd=1500.0,
    )
    assert p.decision == SELECT_ANOTHER
    assert p.reason == "VENUE_MINIMUM_BOUNDED_LOSS_EXCEEDS_CATASTROPHIC_LOSS_CEILING"


def test_never_raises_risk_reported_loss_bounded_when_executable():
    p = propose_exploration_size(
        mark_price=100.0,
        stop_distance_fraction=0.01,
        venue_min_notional=5.0,
        venue_min_qty=0.001,
        venue_qty_step=0.001,
        catastrophic_max_loss_usd=25.0,
        catastrophic_max_notional_usd=1500.0,
    )
    if p.executable:
        assert p.max_loss_if_stop_usd <= 25.0
        assert p.final_notional_usd <= 1500.0


def test_invalid_input_selects_another():
    p = propose_exploration_size(
        mark_price=0.0,  # invalid
        stop_distance_fraction=0.02,
        venue_min_notional=5.0,
        venue_min_qty=1.0,
        venue_qty_step=1.0,
        catastrophic_max_loss_usd=25.0,
        catastrophic_max_notional_usd=1500.0,
    )
    assert p.decision == SELECT_ANOTHER
    assert p.reason.startswith("INVALID_INPUT")
