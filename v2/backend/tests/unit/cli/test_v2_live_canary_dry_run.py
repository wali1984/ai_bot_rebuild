from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.cli.v2_live_canary_dry_run import _candidate_from_args, build_dry_run_packet


class FakeRedis:
    def __init__(
        self,
        *,
        signed_read: bool = False,
        websocket_signed_read: bool = False,
        websocket_dual_side_position: bool | None = False,
        websocket_position_sides: list[str] | None = None,
    ) -> None:
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
        if websocket_signed_read:
            self.data["v2:binance:websocket_signed_read_status"] = {
                "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "signed_read_overall_status": "WEBSOCKET_PRIMARY_READY",
                "signed_ws_read_results": {
                    "account.status": {
                        "status": "SIGNED_WS_READ_EXECUTED",
                        "response_summary": {
                            "availableBalance": "875.5",
                            "totalWalletBalance": "1000",
                            "totalMarginBalance": "990",
                            "dualSidePosition": websocket_dual_side_position,
                        },
                    },
                    "account.balance": {
                        "status": "SIGNED_WS_READ_EXECUTED",
                        "response_summary": {
                            "usdt_balance": "1000",
                            "usdt_cross_wallet_balance": "990",
                            "usdt_cross_unrealized_pnl": "-10",
                            "usdt_available_balance": "875.5",
                            "total_available_balance_usd_equivalent": 875.5,
                            "assets_present_count": 2,
                        },
                    },
                    "account.position": {
                        "status": "SIGNED_WS_READ_EXECUTED",
                        "response_summary": {
                            "nonzero_position_count": 0,
                            "position_sides_present": websocket_position_sides or [],
                        },
                    },
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


def test_live_canary_dry_run_derives_quantity_from_notional_and_price(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate.pop("quantity")
    candidate["target_notional_usd"] = 50.0
    candidate["current_price"] = 25.0

    status = build_dry_run_packet(
        client=FakeRedis(signed_read=True),
        candidate=candidate,
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    pre_submit = status["live_pre_submit_dry_run_status"]
    assert pre_submit["candidate"]["quantity"] == 2.0
    assert "CANDIDATE_QUANTITY_NOT_POSITIVE" not in pre_submit["blockers"]
    assert "MIN_EXECUTABLE:MARK_PRICE_MISSING_OR_INVALID" not in pre_submit["blockers"]


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


def test_live_canary_dry_run_rejects_position_without_liquidation_buffer(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate.pop("expected_liquidation_buffer_usd")

    status = build_dry_run_packet(
        client=FakeRedis(signed_read=True),
        candidate=candidate,
        output_dir=tmp_path,
        generated_utc="2026-07-11T10:00:00Z",
    )

    pre_submit = status["live_pre_submit_dry_run_status"]
    assert "LIQUIDATION_BUFFER_MISSING" in pre_submit["blockers"]
    assert pre_submit["pass_conditions"]["liquidation_buffer_present"] is False
    assert pre_submit["order_submitted"] is False
    assert pre_submit["test_order_submitted"] is False


def test_live_canary_dry_run_emits_maker_first_no_execute_preview(tmp_path: Path) -> None:
    status = build_dry_run_packet(
        client=FakeRedis(signed_read=True),
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-11T10:00:00Z",
    )

    pre_submit = status["live_pre_submit_dry_run_status"]
    packet = status["first_live_canary_operator_packet"]
    preview = pre_submit["execution_payload_preview"]
    assert preview["local_payload_only"] is True
    assert preview["exchange_endpoint"] is None
    assert preview["time_in_force"] == "GTX"
    assert preview["post_only"] is True
    assert preview["maker_first"] is True
    assert preview["taker_fallback_allowed_without_operator"] is False
    assert preview["internal_stop_management"] is True
    assert preview["reduce_only_emergency_supported"] is True
    assert preview["order_submitted"] is False
    assert preview["test_order_submitted"] is False
    assert packet["execution_payload_preview"] == preview


def test_live_canary_dry_run_uses_aggregate_symbol_filter_cache(tmp_path: Path) -> None:
    redis = FakeRedis(signed_read=True)
    redis.data.pop("v2:symbol_filters:BTCUSDT")
    redis.data["v2:exchange:symbol_filters"] = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "filters": [
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                ],
            }
        ]
    }

    status = build_dry_run_packet(
        client=redis,
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    packet = status["first_live_canary_operator_packet"]
    assert packet["symbol_min_notional"] == "5"
    assert packet["symbol_step_size"] == "0.001"
    assert packet["symbol_tick_size"] == "0.10"
    assert packet["symbol_filter_status"]["transport"] == "websocket_cache_primary"
    assert packet["symbol_filter_status"]["rest_fallback_used"] is False


def test_live_canary_dry_run_uses_public_metadata_fallback_when_cache_missing(tmp_path: Path) -> None:
    redis = FakeRedis(signed_read=True)
    redis.data.pop("v2:symbol_filters:BTCUSDT")

    class PublicMetadataTransport:
        def fetch_symbol_filters(self, symbol: str) -> dict[str, object]:
            assert symbol == "BTCUSDT"
            return {
                "ok": True,
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "min_qty": "0.001",
                "step_size": "0.001",
                "tick_size": "0.10",
                "min_notional": "5",
                "endpoint": "GET /fapi/v1/exchangeInfo",
                "source": "binance_public_rest_metadata_fallback",
                "transport": "rest_fallback",
                "rest_fallback_used": True,
                "rest_fallback_reason": "exchangeInfo_symbol_filters_metadata",
                "rest_used_as_primary": False,
            }

    status = build_dry_run_packet(
        client=redis,
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
        symbol_filter_transport=PublicMetadataTransport(),
    )

    packet = status["first_live_canary_operator_packet"]
    assert packet["symbol_min_notional"] == "5"
    assert packet["symbol_step_size"] == "0.001"
    assert packet["symbol_tick_size"] == "0.10"
    assert packet["symbol_filter_status"]["source"] == "binance_public_rest_metadata_fallback"
    assert packet["symbol_filter_status"]["rest_fallback_used"] is True
    assert packet["order_submitted"] is False
    assert packet["test_order_submitted"] is False


def test_live_canary_dry_run_reports_exact_public_metadata_fallback_blocker(tmp_path: Path) -> None:
    redis = FakeRedis(signed_read=True)
    redis.data.pop("v2:symbol_filters:BTCUSDT")

    class BlockedPublicMetadataTransport:
        def fetch_symbol_filters(self, symbol: str) -> dict[str, object]:
            return {
                "ok": False,
                "symbol": symbol,
                "error_type": "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY:BINANCE_REST_FALLBACK_ALLOWED_not_true",
                "endpoint": "GET /fapi/v1/exchangeInfo",
                "required_env": "BINANCE_REST_FALLBACK_ALLOWED=true",
                "transport": "rest_fallback_blocked_websocket_primary",
                "rest_fallback_used": False,
                "rest_fallback_reason": "exchangeInfo_symbol_filters_metadata",
                "rest_used_as_primary": False,
            }

    status = build_dry_run_packet(
        client=redis,
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
        symbol_filter_transport=BlockedPublicMetadataTransport(),
    )

    packet = status["first_live_canary_operator_packet"]
    assert packet["symbol_filter_status"]["error_type"].startswith(
        "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"
    )
    assert packet["symbol_filter_status"]["required_env"] == "BINANCE_REST_FALLBACK_ALLOWED=true"
    assert packet["symbol_min_notional"] is None
    assert packet["live_ready"] is False
    assert packet["order_submitted"] is False
    assert packet["test_order_submitted"] is False


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


def test_live_canary_dry_run_uses_websocket_signed_account_proof(tmp_path: Path) -> None:
    status = build_dry_run_packet(
        client=FakeRedis(signed_read=False, websocket_signed_read=True),
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    packet = status["first_live_canary_operator_packet"]
    assert packet["signed_account_read_status"] == "PASS"
    assert packet["available_balance_usd"] == 875.5
    assert packet["open_orders_count"] == 0
    assert packet["open_positions_count"] == 0
    assert packet["order_submitted"] is False


def test_live_canary_dry_run_uses_websocket_balance_summary_when_account_status_omits_balance(tmp_path: Path) -> None:
    redis = FakeRedis(signed_read=False, websocket_signed_read=True)
    status_summary = redis.data["v2:binance:websocket_signed_read_status"]["signed_ws_read_results"]["account.status"]["response_summary"]
    status_summary["availableBalance"] = None
    status_summary["totalWalletBalance"] = None
    status_summary["totalMarginBalance"] = None

    status = build_dry_run_packet(
        client=redis,
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    pre_submit = status["live_pre_submit_dry_run_status"]
    packet = status["first_live_canary_operator_packet"]
    assert packet["signed_account_read_status"] == "PASS"
    assert packet["available_balance_usd"] == 875.5
    assert pre_submit["available_balance_usd"] == 875.5
    assert pre_submit["order_submitted"] is False
    assert pre_submit["test_order_submitted"] is False


def test_live_canary_dry_run_infers_hedge_mode_from_websocket_position_sides(tmp_path: Path) -> None:
    status = build_dry_run_packet(
        client=FakeRedis(
            signed_read=False,
            websocket_signed_read=True,
            websocket_dual_side_position=None,
            websocket_position_sides=["BOTH"],
        ),
        candidate=_candidate(),
        output_dir=tmp_path,
        generated_utc="2026-07-08T21:00:00Z",
    )

    pre_submit = status["live_pre_submit_dry_run_status"]
    reconciliation = pre_submit["position_reconciliation_status"]
    assert pre_submit["signed_account_read_status"] == "PASS"
    assert "HEDGE_MODE_UNKNOWN" not in reconciliation["blockers"]


def test_inventory_selection_prefers_accepted_positive_near_a_plus_candidate(tmp_path: Path) -> None:
    inventory_dir = tmp_path / "inventory"
    inventory_dir.mkdir()
    rows = [
        {
            "candidate_id": "blocked-symbol-first",
            "symbol": "PENGUUSDT",
            "expected_net_pnl_usd": 1.25,
            "allocator_decision": "PASS",
            "risk_decision": "PASS",
            "orchestrator_decision": "PASS",
        },
        {
            "candidate_id": "accepted-symbol-second",
            "symbol": "PAXGUSDT",
            "expected_net_pnl_usd": 0.90,
            "allocator_decision": "PASS",
            "risk_decision": "PASS",
            "orchestrator_decision": "PASS",
        },
    ]
    (inventory_dir / "near_a_plus_candidate_rows.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    selected = _candidate_from_args(
        candidate_file=None,
        inventory_dir=inventory_dir,
        accepted_symbols={"PAXGUSDT"},
    )

    assert selected["candidate_id"] == "accepted-symbol-second"
    assert selected["symbol"] == "PAXGUSDT"
