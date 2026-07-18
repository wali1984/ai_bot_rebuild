from __future__ import annotations

import json

from v2.backend.app.services.a_plus_trade_gate.service import A_PLUS_GATE_STATUS_REDIS_KEY
from v2.backend.app.services.native_trainer.a_plus_phase9_one_flip_readiness import (
    DIAGNOSTIC_PACKET_COMPLETE,
    PAPER_INTENTS_REDIS_KEY,
    build_phase9_one_flip_readiness_packet,
    write_phase9_one_flip_readiness_packet,
)


class FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str) -> str | None:
        value = self._values.get(key)
        if value is None:
            return None
        return json.dumps(value)


def _phase8_matrix() -> dict[str, object]:
    return {
        "accepted_candidates": [
            {
                "label": "synthetic_a_plus_candidate",
                "symbol": "BTCUSDT",
                "side": "long",
                "a_plus": True,
            }
        ]
    }


def _runtime_status(*, row: dict[str, object] | None = None) -> dict[str, object]:
    rows = [] if row is None else [row]
    return {
        "schema_version": "v2_paper_a_plus_gate_status_v1",
        "generated_utc": "2026-07-06T20:20:00Z",
        "evaluated_candidates": len(rows),
        "a_plus_candidates": len(rows),
        "candidate_matrix": rows,
        "fail_closed": True,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "writes_legacy_redis": False,
    }


def _a_plus_status_row() -> dict[str, object]:
    return {
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "long",
        "strategy_id": "trend_mode",
        "bucket_key": "ETHUSDT|5m|trend_mode|long",
        "a_plus": True,
        "failed_checks": [],
        "missing_evidence_checks": [],
        "passed_check_count": 13,
        "check_count": 13,
    }


def test_phase9_no_runtime_a_plus_candidate_blocks_and_does_not_use_synthetic() -> None:
    packet = build_phase9_one_flip_readiness_packet(
        redis_client=FakeRedis({A_PLUS_GATE_STATUS_REDIS_KEY: _runtime_status()}),
        phase8_candidate_matrix=_phase8_matrix(),
    )

    assert packet["status"] == "BLOCKED_NO_CURRENT_REAL_A_PLUS_CANDIDATE"
    assert packet["selected_A_plus_candidate"] is None
    assert packet["phase8_synthetic_candidate_reference"]["accepted_candidate_count"] == 1
    assert packet["phase8_synthetic_candidate_reference"]["used_as_real_live_candidate"] is False
    assert packet["order_submitted"] is False
    assert packet["test_order_submitted"] is False
    assert packet["exchange_leverage_mutated"] is False
    assert packet["exchange_margin_mutated"] is False
    assert packet["live_gate"] == "blocked_human_only"
    assert packet["canonical_current_cycle_contract_consumed"] is False
    assert packet["canonical_runtime_ready"] is False
    assert packet["serving_authorized"] is False
    assert packet["a_plus_authorized"] is False
    assert packet["paper_authorized"] is False
    assert packet["live_authorized"] is False
    assert packet["operator_flip_sufficient"] is False
    assert packet["artifact_ttl_enforced"] is False


def test_phase9_runtime_candidate_missing_sizing_blocks_fail_closed() -> None:
    packet = build_phase9_one_flip_readiness_packet(
        redis_client=FakeRedis({A_PLUS_GATE_STATUS_REDIS_KEY: _runtime_status(row=_a_plus_status_row())}),
        phase8_candidate_matrix=_phase8_matrix(),
    )

    assert packet["status"] == "BLOCKED_A_PLUS_CANDIDATE_MISSING_EXECUTION_SIZING_OR_EXIT_PLAN"
    assert packet["selected_A_plus_candidate"]["symbol"] == "ETHUSDT"
    assert packet["selected_A_plus_candidate_source"] == A_PLUS_GATE_STATUS_REDIS_KEY
    assert "qty" in packet["missing_required_fields"]
    assert "stop_plan" in packet["missing_required_fields"]
    assert packet["diagnostic_conditions"]["execution_and_exit_fields_complete"] is False
    assert packet["order_submitted"] is False


def test_phase9_complete_legacy_candidate_is_diagnostic_and_never_runtime_ready() -> None:
    status_row = _a_plus_status_row()
    intent = {
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "long",
        "strategy_selected_mode": "trend_mode",
        "a_plus_gate": {"a_plus": True},
        "quantity": 0.01,
        "target_notional_usdt": 600.0,
        "allocated_margin_usd": 200.0,
        "recommended_leverage": 3.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "liquidation_buffer_bps": 1500.0,
        "max_loss_if_stop_hit": 6.0,
        "stop_distance_bps": 100.0,
        "take_profit_bps": 180.0,
        "take_profit_structure": "one_r_two_r_grid",
    }
    packet = build_phase9_one_flip_readiness_packet(
        redis_client=FakeRedis(
            {
                A_PLUS_GATE_STATUS_REDIS_KEY: _runtime_status(row=status_row),
                PAPER_INTENTS_REDIS_KEY: [intent],
            }
        ),
        phase8_candidate_matrix=_phase8_matrix(),
    )

    assert packet["status"] == DIAGNOSTIC_PACKET_COMPLETE
    assert packet["selected_A_plus_candidate_source"] == PAPER_INTENTS_REDIS_KEY
    assert packet["symbol"] == "ETHUSDT"
    assert packet["side"] == "long"
    assert packet["qty"] == 0.01
    assert packet["notional"] == 600.0
    assert packet["margin"] == 200.0
    assert packet["recommended_leverage"] == 3.0
    assert packet["recommended_margin_mode"] == "isolated_paper_simulated"
    assert packet["liquidation_buffer"]["liquidation_buffer_bps"] == 1500.0
    assert packet["max_loss"] == 6.0
    assert packet["stop_plan"]["status"] == "DIAGNOSTIC_FIELDS_COMPLETE"
    assert packet["take_profit_reduce_plan"]["status"] == "DIAGNOSTIC_FIELDS_COMPLETE"
    assert packet["operator_flip_required"] is True
    assert packet["order_submitted"] is False
    assert packet["test_order_submitted"] is False
    assert packet["exchange_leverage_mutated"] is False
    assert packet["exchange_margin_mutated"] is False
    assert packet["why_allowed"] == []
    assert packet["diagnostic_observations"]
    assert packet["operator_flip_required"] is True
    assert packet["operator_flip_sufficient"] is False
    assert packet["canonical_current_cycle_contract_consumed"] is False
    assert packet["canonical_current_cycle_contract_verified"] is False
    assert packet["canonical_runtime_ready"] is False
    assert packet["serving_authorized"] is False
    assert packet["a_plus_authorized"] is False
    assert packet["paper_authorized"] is False
    assert packet["live_authorized"] is False
    assert packet["live_execution_authorized"] is False
    assert packet["routes_to_live"] is False
    assert packet["selected_A_plus_candidate"]["canonical_a_plus_authorized"] is False
    assert packet["selected_A_plus_candidate"]["eligible_as_runtime_candidate"] is False
    assert "a_plus" not in packet["selected_A_plus_candidate"]


def test_phase9_packet_written_to_goal_and_public_dirs(tmp_path) -> None:
    goal_dir = tmp_path / "goal"
    public_dir = tmp_path / "public"

    packet = write_phase9_one_flip_readiness_packet(
        goal_dir=goal_dir,
        public_dir=public_dir,
        redis_client=FakeRedis({A_PLUS_GATE_STATUS_REDIS_KEY: _runtime_status()}),
        phase8_candidate_matrix=_phase8_matrix(),
    )

    for directory in (goal_dir, public_dir):
        payload = json.loads((directory / "real_trader_one_flip_readiness_packet.json").read_text())
        assert payload["status"] == packet["status"]
        assert payload["goal_id"] == packet["goal_id"]
        assert payload["canonical_runtime_ready"] is False
        assert payload["artifact_freshness_authoritative"] is False
