"""Fast-path adaptation receipts (operator directive 2026-07-31 §6-7).

The paper policy-state version stamped on the intent at entry must flow
through the position row into the close event, and every close event must
declare its maturation/consumption lifecycle explicitly.
"""

from __future__ import annotations

from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.position_state import (
    PaperNetPosition,
    position_from_fill,
)


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


def _fill(**extra: object) -> dict:
    row: dict[str, object] = {
        "fill_id": "f1",
        "ledger_row_id": "f1",
        "intent_id": "f1",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-07-16T10:00:00Z",
        "generated_utc": "2026-07-16T10:00:00Z",
        "signal_id": "sig_f1",
        "prediction_id": "pred_f1",
        "risk_decision_id": "risk_f1",
        "orchestrator_decision_id": "orch_f1",
        "decision_id": "orch_f1",
        "market_state_id": "ms_f1",
        "feature_snapshot_id": "feat_f1",
        "mtf_snapshot_id": "mtf_f1",
        "feature_cutoff": "2026-07-16T09:59:00Z",
        "decision_time": "2026-07-16T10:00:00Z",
        "available_at": "2026-07-16T09:59:30Z",
        "selected_action": "long",
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_f1",
        "source_hashes": {"feature_vector_hash": "hash_f1"},
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "timeframe": "1m",
        "paper_fill_allowed": True,
    }
    row.update(extra)
    return row


def test_close_event_carries_entry_policy_state_version() -> None:
    close_event = _close(_position(policy_state_version=7))

    assert close_event["entry_policy_state_version"] == 7
    assert close_event["maturation_status"] == "PENDING_DECISION_HORIZON_MATURATION"
    assert close_event["training_consumption_status"] == "NOT_YET_CONSUMED"


def test_close_event_entry_policy_state_version_none_when_absent() -> None:
    close_event = _close(_position())

    # Missing lineage is recorded honestly as None, never invented.
    assert close_event["entry_policy_state_version"] is None
    assert close_event["maturation_status"] == "PENDING_DECISION_HORIZON_MATURATION"
    assert close_event["training_consumption_status"] == "NOT_YET_CONSUMED"


def test_position_from_fill_passes_policy_state_version_through() -> None:
    position = position_from_fill(
        _fill(policy_state_version=11),
        fill_id="f1",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    assert position.policy_state_version == 11
    assert (
        position.to_payload(generated_utc="2026-07-16T10:00:01Z")[
            "policy_state_version"
        ]
        == 11
    )


def test_position_from_fill_rejects_non_int_policy_state_version() -> None:
    for invalid in (True, "7", 7.0, {"v": 7}):
        position = position_from_fill(
            _fill(policy_state_version=invalid),
            fill_id="f1",
            side="long",
            quantity=1.0,
            price=100.0,
        )
        assert position.policy_state_version is None
