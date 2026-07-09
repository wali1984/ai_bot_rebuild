from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.cli.v2_live_canary_dry_run import build_dry_run_packet


class FakeRedis:
    def __init__(self, *, signed_read: bool = False) -> None:
        account = (
            {
                "signed_account_read_ok": True,
                "available_balance_usd": 900.0,
                "available_margin": 900.0,
                "local_position": {"symbol": "BTCUSDT", "side": "flat", "quantity": 0.0},
                "exchange_position": {"symbol": "BTCUSDT", "side": "flat", "quantity": 0.0},
                "current_positions": [],
                "open_orders": [],
                "hedge_mode": False,
                "margin_mode": "cross",
                "signed_read_ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            }
            if signed_read
            else {}
        )
        self.data = {
            "v2:live_gate:state": {
                "live_gate": "blocked_human_only",
                "release_mode": "NON_LIVE",
                "operator_approved": False,
                "kill_switch_enabled": True,
                "kill_switch_active": False,
                "places_real_order": False,
                "exchange_action_taken": False,
                "live_canary_config": {
                    "live_canary_enabled": False,
                    "allowed_symbols": ["BTCUSDT"],
                    "max_notional_usd": 1_000.0,
                    "max_open_positions": 1,
                    "require_human_operator_arm": False,
                },
            },
            "v2:live_order_transport:status": account,
            "v2:symbol_filters:BTCUSDT": {
                "ok": True,
                "symbol": "BTCUSDT",
                "min_qty": "0.0001",
                "step_size": "0.0001",
                "tick_size": "0.10",
                "min_notional": "5",
            },
        }

    def get(self, key: str):
        value = self.data.get(key)
        return json.dumps(value) if value is not None else None


def _candidate() -> dict[str, object]:
    return {
        "A_plus_candidate": True,
        "allocator_decision_id": "allocsim-live",
        "candidate_id": "cand-live",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "quantity": 0.01,
        "target_notional_usd": 500.0,
        "allocated_margin_usd": 250.0,
        "expected_net_pnl_usd": 4.0,
        "expected_max_loss_usd": 6.0,
        "expected_liquidation_buffer_usd": 100.0,
        "recommended_leverage": 2.0,
        "recommended_leverage_source": "adaptive_simulation",
        "recommended_margin_mode": "isolated_paper_simulated",
        "recommended_margin_mode_source": "adaptive_simulation",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "allocator_block_reasons": [],
        "preemptive_decision_id": "pec-live",
        "preemptive_action": "ALLOW_A_PLUS_CANDIDATE",
        "pre_trade_loss_probability": 0.35,
        "advanced_indicator_features_present": True,
    }


def test_live_canary_dry_run_blocks_without_signed_read_and_writes_packet(tmp_path: Path) -> None:
    status = build_dry_run_packet(
        client=FakeRedis(signed_read=False),
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    packet = status["first_live_canary_operator_packet"]
    assert packet["signed_account_read_status"] == "BLOCKED_OPERATOR_KEY_REQUIRED"
    assert packet["live_ready"] is False
    assert packet["allocator_decision_id"] == "allocsim-live"
    assert packet["allocator_block_reasons"] == []
    assert packet["max_loss_usd"] == 6.0
    assert packet["liquidation_buffer_usd"] == 100.0
    assert packet["symbol_min_notional"] == "5"
    assert packet["symbol_step_size"] == "0.0001"
    assert packet["symbol_tick_size"] == "0.10"
    assert packet["reduce_only_supported"] is True
    assert packet["order_submitted"] is False
    assert packet["test_order_submitted"] is False
    assert (tmp_path / "first_live_canary_operator_packet.json").exists()
    assert (tmp_path / "v2_live_canary_dry_run_status.json").exists()


def test_live_canary_dry_run_preserves_signed_account_values_when_present(tmp_path: Path) -> None:
    status = build_dry_run_packet(
        client=FakeRedis(signed_read=True),
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    packet = status["first_live_canary_operator_packet"]
    assert packet["signed_account_read_status"] == "PASS"
    assert packet["allocator_decision_id"] == "allocsim-live"
    assert packet["available_balance_usd"] == 900.0
    assert packet["open_orders_count"] == 0
    assert packet["open_positions_count"] == 0
    assert packet["live_ready"] is False
