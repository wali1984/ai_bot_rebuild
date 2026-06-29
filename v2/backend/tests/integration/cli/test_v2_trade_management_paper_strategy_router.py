from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {
            "v2:live_gate:state": json.dumps({"live_gate": "blocked_human_only"}),
        }
        self.expiries: dict[str, int | None] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.expiries[key] = ex
        return True

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        if match is None:
            yield from list(self.store.keys())
            return
        prefix = match.rstrip("*")
        for key in list(self.store.keys()):
            if match.endswith("*"):
                if key.startswith(prefix):
                    yield key
            elif key == match:
                yield key

    def type(self, key: str) -> str:
        return "string" if key in self.store else "none"

    def ttl(self, key: str) -> int:  # noqa: ARG002
        return 300


def _audit_quality_fields() -> dict:
    return {
        "actual_observed_spread_entry_bps": 1.4,
        "actual_observed_spread_exit_bps": 1.6,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "expected_slippage_bps": 0.9,
        "expected_slippage_usd": 0.01,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_modeled": True,
        "realized_slippage_bps": 1.0,
        "realized_slippage_usd": 0.01,
        "implementation_shortfall_usd": 0.0,
        "squeeze_evidence_score": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "squeeze_evidence_components": {"spread_stress": 0.0},
        "mfe_bps": 20.0,
        "mfe_usd": 1.0,
        "mae_bps": 5.0,
        "mae_usd": 0.25,
        "intra_trade_high_price": 101.0,
        "intra_trade_low_price": 99.5,
        "trailing_stop_history": [],
    }


def _utc_now_for_test() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ms(iso_value: str) -> int:
    return int(datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def _closed_candles_from_returns(symbol: str, returns: list[float], *, start_ms: int) -> list[dict]:
    close = 100.0
    rows = []
    close_time = start_ms
    rows.append({
        "symbol": symbol,
        "timeframe": "1m",
        "close": close,
        "close_time": close_time,
        "candle_close_time": close_time,
        "available_at": close_time + 1,
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "is_closed": True,
        "feature_eligible": True,
    })
    for index, return_value in enumerate(returns, start=1):
        close *= 1.0 + return_value
        close_time = start_ms + index * 60_000
        rows.append({
            "symbol": symbol,
            "timeframe": "1m",
            "close": close,
            "close_time": close_time,
            "candle_close_time": close_time,
            "available_at": close_time + 1,
            "candle_closed_confirmed": True,
            "closed_candle": True,
            "is_closed": True,
            "feature_eligible": True,
        })
    return rows


def _fresh_paper_signal_and_prediction(
    *,
    symbol: str,
    timeframe: str,
    side: str = "long",
    expected_move_after_cost_bps: float = 80.0,
    confidence_calibrated: float = 0.72,
) -> tuple[dict, dict]:
    generated_utc = _utc_now_for_test()
    prediction_id = f"prediction-{symbol.lower()}-{timeframe}"
    signal = {
        "signal_id": f"signal-{symbol.lower()}-{timeframe}",
        "prediction_id": prediction_id,
        "risk_decision_id": f"risk-{symbol.lower()}-{timeframe}",
        "orchestrator_decision_id": f"orch-{symbol.lower()}-{timeframe}",
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "selected_action": side,
        "source_prediction_status": "PRESENT_CURRENT",
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "confidence_calibrated": confidence_calibrated,
        "market_state_id": f"mstate-{symbol.lower()}-{timeframe}",
        "market_state_integrity_score": 95.0,
        "valid_for_paper": True,
        "market_state_reject_reasons": [],
        "paper_fill_allowed": True,
        "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
        "generated_utc": generated_utc,
    }
    prediction = {
        "prediction_id": prediction_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_action": side,
        "status": "PRESENT_CURRENT",
        "confidence_calibrated": confidence_calibrated,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "feature_cutoff": "2026-06-15T16:59:59Z",
        "decision_time": generated_utc,
        "generated_utc": generated_utc,
        "market_state_id": signal["market_state_id"],
        "market_state_integrity_score": signal["market_state_integrity_score"],
    }
    return signal, prediction


def test_paper_loop_process_lock_refuses_second_holder(tmp_path) -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    lock_path = tmp_path / "paper-loop.lock"

    first_handle = paper._try_acquire_loop_lock(lock_path)  # noqa: SLF001
    assert first_handle is not None
    try:
        lock_payload = json.loads(lock_path.read_text())
        assert lock_payload["classification"] == "V2_TRADE_MANAGEMENT_PAPER_LOOP_LOCK_HELD"
        assert lock_payload["paper_only"] is True
        assert lock_payload["places_real_order"] is False
        assert lock_payload["writes_legacy_redis"] is False

        second_handle = paper._try_acquire_loop_lock(lock_path)  # noqa: SLF001
        assert second_handle is None
    finally:
        first_handle.close()

    released_handle = paper._try_acquire_loop_lock(lock_path)  # noqa: SLF001
    assert released_handle is not None
    released_handle.close()


def test_paper_audit_entry_gate_does_not_static_block_native_5m(monkeypatch) -> None:
    fake = FakeRedis()
    signal, prediction = _fresh_paper_signal_and_prediction(
        symbol="BTCUSDT",
        timeframe="5m",
    )
    fake.store["v2:signals:paper"] = json.dumps([signal])
    fake.store["v2:prediction:BTCUSDT:5m"] = json.dumps(prediction)
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(
        {"ticker_24hr": {"lastPrice": "100.0"}, "fetched_utc": _utc_now_for_test()}
    )
    fake.store["v2:paper:ledger"] = json.dumps({"accepted": [], "open_positions": []})
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})
    monkeypatch.setattr(paper, "_read_accepted_fill_state_file", lambda *a, **kw: {})

    status = paper.run_once()

    assert status["paper_audit_entry_gate_status"]["timeframe_policy"] == (
        "DYNAMIC_OUTCOME_MEMORY_NATIVE_TIMEFRAMES"
    )
    assert status["paper_audit_entry_gate_status"]["blocked_entry_timeframes"] == []
    assert "5m" in status["paper_audit_entry_gate_status"]["allowed_entry_timeframes"]
    assert status["paper_audit_entry_gate_status"]["audit_timeframe_block_count"] == 0
    assert not any(
        str(reason).startswith("TIMEFRAME_BLOCKED:5m")
        for reason in status["paper_audit_entry_gate_status"]["block_reason_counts"]
    )
    assert status["paper_audit_entry_gate_status"]["live_path_changed"] is False


def test_paper_audit_entry_gate_blocks_degraded_5m_outcome_memory(monkeypatch) -> None:
    fake = FakeRedis()
    signal, prediction = _fresh_paper_signal_and_prediction(
        symbol="BTCUSDT",
        timeframe="5m",
    )
    fake.store["v2:signals:paper"] = json.dumps([signal])
    fake.store["v2:prediction:BTCUSDT:5m"] = json.dumps(prediction)
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(
        {"ticker_24hr": {"lastPrice": "100.0"}, "fetched_utc": _utc_now_for_test()}
    )
    fake.store["v2:paper:outcome_memory:__ALL__:5m"] = json.dumps(
        {
            "symbol": "__ALL__",
            "timeframe": "5m",
            "trade_count": 25,
            "rolling_ev_bps": -6.0,
            "drawdown_contribution_usd": -12.0,
            "degraded": True,
            "block_reason": "ROLLING_EV_DEGRADED:-6.00bps<-5.00bps",
            "trust_evidence_status": "TRUSTED_OUTCOME_MEMORY",
            "outcome_memory_can_block_entries": True,
            "trusted_trade_count": 25,
        }
    )
    fake.store["v2:paper:ledger"] = json.dumps({"accepted": [], "open_positions": []})
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})
    monkeypatch.setattr(paper, "_read_accepted_fill_state_file", lambda *a, **kw: {})

    status = paper.run_once()
    ledger = json.loads(fake.store["v2:paper:ledger"])
    blocked = [row for row in ledger["blocked"] if row.get("signal_id") == signal["signal_id"]]

    assert status["intents_accepted"] == 0
    assert len(blocked) == 1
    assert blocked[0]["paper_fill_block_reason"] == "P0_ENTRY_GATE_BLOCKED"
    assert (
        "OUTCOME_MEMORY_BLOCK:ROLLING_EV_DEGRADED:-6.00bps<-5.00bps:"
        "source=REDIS_TIMEFRAME_AGGREGATE"
    ) in blocked[0]["entry_gate_block_reasons"]
    assert status["paper_audit_entry_gate_status"]["audit_timeframe_block_count"] == 0
    assert status["paper_audit_entry_gate_status"]["live_path_changed"] is False
    assert all(row.get("signal_id") != signal["signal_id"] for row in ledger["accepted"])


def test_paper_audit_entry_gate_blocks_explicit_no_go_symbol(monkeypatch) -> None:
    fake = FakeRedis()
    signal, prediction = _fresh_paper_signal_and_prediction(
        symbol="TRUMPUSDT",
        timeframe="1h",
    )
    fake.store["v2:signals:paper"] = json.dumps([signal])
    fake.store["v2:prediction:TRUMPUSDT:1h"] = json.dumps(prediction)
    fake.store["v2:market:prices:TRUMPUSDT"] = json.dumps(
        {"ticker_24hr": {"lastPrice": "10.0"}, "fetched_utc": _utc_now_for_test()}
    )
    fake.store["v2:paper:ledger"] = json.dumps({"accepted": [], "open_positions": []})
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})
    monkeypatch.setattr(paper, "_read_accepted_fill_state_file", lambda *a, **kw: {})

    status = paper.run_once()
    ledger = json.loads(fake.store["v2:paper:ledger"])
    blocked = [row for row in ledger["blocked"] if row.get("signal_id") == signal["signal_id"]]

    assert status["intents_accepted"] == 0
    assert len(blocked) == 1
    assert blocked[0]["paper_fill_block_reason"] == "P0_ENTRY_GATE_BLOCKED"
    assert "SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:TRUMPUSDT" in blocked[0]["entry_gate_block_reasons"]
    assert status["paper_audit_entry_gate_status"]["audit_symbol_block_count"] == 1
    assert status["paper_audit_entry_gate_status"]["live_path_changed"] is False
    assert all(row.get("signal_id") != signal["signal_id"] for row in ledger["accepted"])


def test_no_trade_mode_never_submits_new_paper_fill(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:signals:paper"] = json.dumps(
        [
            {
                "signal_id": "signal-short",
                "prediction_id": "prediction-short",
                "risk_decision_id": "risk-short",
                "orchestrator_decision_id": "orch-short",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "side": "short",
                "expected_move_after_cost_bps": -20.0,
                "confidence_calibrated": 0.78,
                "market_state_id": "mstate_btc_1m",
                "market_state_integrity_score": 95.0,
                "valid_for_paper": True,
                "market_state_reject_reasons": [],
                "paper_fill_allowed": True,
                "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
            }
        ]
    )
    fake.store["v2:prediction:BTCUSDT:1m"] = json.dumps(
        {
            "prediction_id": "prediction-short",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "short",
            "confidence_calibrated": 0.78,
            "expected_move_after_cost_bps": -20.0,
            "feature_cutoff": "2026-06-10T10:00:00Z",
        }
    )
    fake.store["v2:prediction:BTCUSDT:15m"] = json.dumps(
        {
            "prediction_id": "prediction-short-15m",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "selected_action": "short",
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": -30.0,
            "feature_cutoff": "2026-06-10T10:00:00Z",
        }
    )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(
        {
            "ticker_24hr": {"lastPrice": "100.0"},
            "fetched_utc": "2026-06-10T10:00:00Z",
        }
    )
    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "accepted_count": 1,
            "blocked_count": 0,
            "shadow_observation_count": 0,
            "accepted": [
                {
                    "fill_id": "existing-long",
                    "ledger_row_id": "existing-long",
                    "signal_id": "signal-long",
                    "prediction_id": "prediction-long",
                    "risk_decision_id": "risk-long",
                    "orchestrator_decision_id": "orch-long",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_price": 100.0,
                    "fill_price": 100.0,
                    "quantity": 0.25,
                    "notional": 25.0,
                    "notional_usdt": 25.0,
                    "entry_price_utc": "2026-06-10T09:59:00Z",
                    "fill_price_utc": "2026-06-10T09:59:00Z",
                    "generated_utc": "2026-06-10T09:59:00Z",
                    "paper_fill_allowed": True,
                }
            ],
            "open_positions": [
                {
                    "position_id": "paper_pos_BTCUSDT",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "net_quantity": 0.25,
                    "position_state": "OPEN_POSITION",
                }
            ],
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})
    monkeypatch.setattr(paper, "_read_accepted_fill_state_file", lambda *a, **kw: {})

    status = paper.run_once()

    ledger = json.loads(fake.store["v2:paper:ledger"])
    blocked_short = [
        row for row in ledger["blocked"] if row.get("signal_id") == "signal-short"
    ]
    assert status["intents_accepted"] == 0
    assert status["intents_blocked"] >= 1
    assert ledger["current_cycle_accepted_count"] == 0
    assert ledger["blocked_count"] >= 1
    assert len(blocked_short) == 1
    assert blocked_short[0]["strategy_selected_mode"] == "no_trade_mode"
    assert blocked_short[0]["strategy_router_block_reason"] == "POSITION_STATE_CONFLICT_BLOCK"
    assert not any(
        "EXPECTED_MOVE" in str(reason)
        for reason in blocked_short[0].get("entry_gate_block_reasons", [])
    )
    assert all(row["signal_id"] != "signal-short" for row in ledger["accepted"])


def test_strategy_router_position_state_uses_open_positions_not_historical_accepted() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "accepted": [
            {
                "fill_id": "old-short-fill",
                "symbol": "BTCUSDT",
                "side": "short",
                "position_state": "OPEN_POSITION",
                "net_quantity": 1.0,
            }
        ],
        "closed_trades": [
            {
                "source_fill_ids": ["old-short-fill"],
                "symbol": "BTCUSDT",
                "side": "short",
                "realized_pnl_usd": -1.0,
            }
        ],
        "open_positions": [],
    }

    assert paper._derive_position_state(ledger, "BTCUSDT") == "FLAT"  # noqa: SLF001


def test_strategy_router_position_state_fails_closed_on_conflicting_open_positions() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "open_positions": [
            {
                "position_id": "paper_pos_BTCUSDT_long",
                "symbol": "BTCUSDT",
                "side": "long",
                "net_quantity": 0.2,
                "position_state": "OPEN_POSITION",
            },
            {
                "position_id": "paper_pos_BTCUSDT_short",
                "symbol": "BTCUSDT",
                "side": "short",
                "net_quantity": 0.1,
                "position_state": "OPEN_POSITION",
            },
        ],
    }

    assert (
        paper._derive_position_state(ledger, "BTCUSDT")  # noqa: SLF001
        == "INVALID_CONFLICTING_OPEN_POSITIONS"
    )


def test_paper_loop_builds_enriched_trainer_feedback_rows() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    close_event = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": "BTCUSDT",
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "signal_id": "sig_1",
        "entry_signal_id": "sig_1",
        "feature_snapshot_id": "feat_1",
        "entry_feature_snapshot_id": "feat_1",
        "market_state_id": "ms_1",
        "entry_market_state_id": "ms_1",
        "timeframe": "1m",
        "action": "long",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl": 1.0,
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following_v1",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "realized_pnl_bps": 18.0,
        "hold_time_seconds": 300,
        "exit_time": "2026-06-11T10:05:00Z",
        "market_regime": "TREND",
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"liquidity": "normal"},
        "liquidity_context": {"liquidity": "normal"},
        "liquidation_distance_context": {"distance_bps": 240.0},
        "microstructure_context": {"spread_bps": 1.2},
        "oi_funding_context": {"source": "test"},
        "public_intel_context": {"source": "test"},
        "major_move_context": {"source": "test", "status": "not_major_move_trade"},
        "future_window_label_source": "closed_trade_outcome",
        "drawdown_at_entry": 0.0,
        **_audit_quality_fields(),
    }
    outcome_label = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "realized_pnl_bps": 18.0,
    }
    prediction = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "decision_id": "decision_1",
        "feature_cutoff": "2026-06-11T10:00:00Z",
        "available_at": "2026-06-11T10:00:01Z",
        "decision_time": "2026-06-11T10:00:02Z",
        "model_version": "native_cuda_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": {"feature_vector_hash": "hash_feat_1"},
    }

    rows = paper._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={"pred_1": prediction},
    )

    assert len(rows) == 1
    assert rows[0]["trainer_consumable"] is True
    assert rows[0]["strategy_id"] == "trend_following_v1"
    assert rows[0]["missing_feedback_fields"] == []


def test_accepted_fill_backfill_requires_dereferenceable_feature_snapshot() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    row = {
        "fill_id": "fill_1",
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_feature_snapshot_id": "feat_1",
    }
    prediction = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "decision_id": "decision_1",
        "feature_cutoff": "2026-06-11T10:00:00Z",
        "available_at": "2026-06-11T10:00:01Z",
        "decision_time": "2026-06-11T10:00:02Z",
        "model_version": "native_cuda_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": {"feature_vector_hash": "hash_feat_1"},
    }

    rows = paper._backfill_fill_lineage_from_predictions(  # noqa: SLF001
        [row],
        {"pred_1": prediction},
        feature_snapshots_by_id={},
        require_feature_snapshot_deref=True,
    )

    assert rows[0]["trust_reconstructed"] is False
    assert "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND" in rows[0]["trust_reconstruction_rejection_reasons"]


def test_accepted_fill_backfill_reconstructs_with_exact_feature_snapshot() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    row = {
        "fill_id": "fill_1",
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_feature_snapshot_id": "feat_1",
    }
    prediction = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "decision_id": "decision_1",
        "feature_cutoff": "2026-06-11T10:00:00Z",
        "available_at": "2026-06-11T10:00:01Z",
        "decision_time": "2026-06-11T10:00:02Z",
        "model_version": "native_cuda_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": {"feature_vector_hash": "hash_feat_1"},
    }
    snapshot = {
        "feature_snapshot_id": "feat_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-06-11T10:00:01Z",
        "feature_cutoff": "2026-06-11T10:00:00Z",
        "features": {"close_price": 100.0},
    }

    rows = paper._backfill_fill_lineage_from_predictions(  # noqa: SLF001
        [row],
        {"pred_1": prediction},
        feature_snapshots_by_id={"feat_1": snapshot},
        require_feature_snapshot_deref=True,
    )

    assert rows[0]["trust_reconstructed"] is True
    assert rows[0]["decision_id"] == "decision_1"
    assert rows[0]["trust_source_ids"]["entry_feature_snapshot_id"] == "feat_1"


def test_exact_entry_feature_snapshot_rejects_unfinished_candle() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    fake = FakeRedis()
    fake.store["v2:features:snapshot:feat_1"] = json.dumps(
        {
            "feature_snapshot_id": "feat_1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_freshness_state": "CURRENT",
            "available_at": "2026-06-11T10:00:01Z",
            "generated_at": "2026-06-11T10:00:01Z",
            "feature_cutoff": "2026-06-11T10:00:00Z",
            "candle_closed_confirmed": False,
            "features": {"close_price": 100.0},
        }
    )

    snapshot = paper._read_v2_feature_snapshot_by_id(  # noqa: SLF001
        fake,
        "feat_1",
        decision_time="2026-06-11T10:00:02Z",
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert snapshot["features"] == {}
    assert snapshot["unavailable_reason"] == "UNFINISHED_CANDLE_FEATURE_SNAPSHOT_REJECTED"


def test_exact_entry_feature_snapshot_accepts_same_second_millisecond_decision() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    fake = FakeRedis()
    fake.store["v2:features:snapshot:feat_1"] = json.dumps(
        {
            "feature_snapshot_id": "feat_1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_freshness_state": "CURRENT",
            "available_at": "2026-06-11T10:00:01.250Z",
            "generated_at": "2026-06-11T10:00:01.250Z",
            "feature_cutoff": "2026-06-11T10:00:00.999Z",
            "candle_closed_confirmed": True,
            "features": {"close_price": 100.0},
        }
    )

    snapshot = paper._read_v2_feature_snapshot_by_id(  # noqa: SLF001
        fake,
        "feat_1",
        decision_time="2026-06-11T10:00:01.500Z",
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert snapshot["features"] == {"close_price": 100.0}
    assert snapshot["available_at"] == "2026-06-11T10:00:01.250Z"


def test_stale_predictions_excluded_from_paper_candidates() -> None:
    fake = FakeRedis()
    fake.store["v2:prediction:BTCUSDT:1m"] = json.dumps(
        {
            "prediction_id": "stale-pred",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "status": "STALE_TF_PREDICTION",
            "selected_action": "long",
            "confidence_calibrated": 0.90,
            "expected_move_after_cost_bps": 50.0,
            "generated_utc": "2026-01-01T00:00:00Z",
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    rows = paper._scan_prediction_rows(fake)  # noqa: SLF001

    assert rows == []


def test_strategy_mode_collapse_guard_blocks_majority_mode_only() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "closed_trades": [
            {"side": "long" if idx % 2 == 0 else "short", "strategy_selected_mode": "trend_mode"}
            for idx in range(60)
        ]
    }

    trend_guard = paper._paper_strategy_mode_collapse_guard(ledger, "trend_mode")
    mean_reversion_guard = paper._paper_strategy_mode_collapse_guard(
        ledger,
        "mean_reversion_mode",
    )

    assert trend_guard["allowed"] is False
    assert trend_guard["block_reason"] == paper.STRATEGY_MODE_COLLAPSE_BLOCK_REASON
    assert trend_guard["top_mode"] == "trend_mode"
    assert trend_guard["top_mode_share"] == 1.0
    assert mean_reversion_guard["allowed"] is True


def test_strategy_mode_collapse_guard_switches_to_active_policy_cohort() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    legacy_trend_rows = [
        {"strategy_selected_mode": "trend_mode", "side": "long" if idx % 2 == 0 else "short"}
        for idx in range(80)
    ]
    active_reduce_size_rows = [
        {
            "strategy_selected_mode": "reduce_size_mode",
            "side": "short",
            "paper_exit_policy_version": paper.PAPER_EXIT_POLICY_VERSION,
        }
        for _ in range(45)
    ]
    active_mean_reversion_rows = [
        {
            "strategy_selected_mode": "mean_reversion_mode",
            "side": "long",
            "paper_exit_policy_version": paper.PAPER_EXIT_POLICY_VERSION,
        }
        for _ in range(5)
    ]
    ledger = {
        "closed_trades": legacy_trend_rows + active_reduce_size_rows + active_mean_reversion_rows
    }

    reduce_size_guard = paper._paper_strategy_mode_collapse_guard(  # noqa: SLF001
        ledger,
        "reduce_size_mode",
    )
    trend_guard = paper._paper_strategy_mode_collapse_guard(ledger, "trend_mode")  # noqa: SLF001

    assert reduce_size_guard["allowed"] is False
    assert reduce_size_guard["block_reason"] == paper.STRATEGY_MODE_COLLAPSE_BLOCK_REASON
    assert reduce_size_guard["evidence_scope"] == "active_policy"
    assert reduce_size_guard["policy_version_filter_enabled"] is True
    assert reduce_size_guard["closed_trade_count"] == 50
    assert reduce_size_guard["unfiltered_closed_trade_count"] == 130
    assert reduce_size_guard["filtered_out_closed_trade_count"] == 80
    assert reduce_size_guard["historical_mode_counts"] == {
        "mean_reversion_mode": 5,
        "reduce_size_mode": 45,
        "trend_mode": 80,
    }
    assert reduce_size_guard["active_policy_mode_counts"] == {
        "mean_reversion_mode": 5,
        "reduce_size_mode": 45,
    }
    assert reduce_size_guard["top_mode"] == "reduce_size_mode"
    assert reduce_size_guard["top_mode_share"] == 0.9
    assert trend_guard["allowed"] is True


def test_strategy_mode_collapse_guard_uses_history_until_active_policy_sample_ready() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "closed_trades": [
            {"strategy_selected_mode": "trend_mode", "side": "long"}
            for _ in range(80)
        ]
        + [
            {
                "strategy_selected_mode": "reduce_size_mode",
                "side": "short",
                "paper_exit_policy_version": paper.PAPER_EXIT_POLICY_VERSION,
            }
            for _ in range(10)
        ]
    }

    trend_guard = paper._paper_strategy_mode_collapse_guard(ledger, "trend_mode")  # noqa: SLF001
    reduce_size_guard = paper._paper_strategy_mode_collapse_guard(  # noqa: SLF001
        ledger,
        "reduce_size_mode",
    )

    assert trend_guard["allowed"] is False
    assert trend_guard["evidence_scope"] == "all_history_until_active_policy_min_sample"
    assert trend_guard["policy_version_filter_enabled"] is False
    assert trend_guard["active_policy_closed_trade_count"] == 10
    assert trend_guard["active_policy_sample_ready"] is False
    assert reduce_size_guard["allowed"] is True


def test_paper_audit_strategy_mode_preserves_underlying_reduce_size_regime() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    router = {
        "selected_mode": "reduce_size_mode",
        "regime_labels": ["MODEL_DISAGREEMENT", "RANGE"],
    }

    assert paper._paper_audit_strategy_mode(router) == "mean_reversion_mode"  # noqa: SLF001
    assert paper._paper_strategy_size_adjustment_mode(router) == "reduce_size_mode"  # noqa: SLF001


def test_paper_audit_strategy_mode_preserves_breakout_priority() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    router = {
        "selected_mode": "reduce_size_mode",
        "regime_labels": ["BREAKOUT", "TREND", "HIGH_VOLATILITY"],
    }

    assert paper._paper_audit_strategy_mode(router) == "breakout_mode"  # noqa: SLF001


def test_paper_sizing_fails_closed_for_legacy_unversioned_adaptive_allocation() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "side": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "quantity": 1.0,
        "notional": 100.0,
    }
    legacy_allocation = {
        "allocation_id": "alloc_legacy",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 100.0,
        "target_quantity": 1.0,
        "final_size_reason": "adaptive_allocation_from_legacy_payload",
    }

    paper._attach_paper_sizing(intent, legacy_allocation)  # noqa: SLF001
    paper._apply_strategy_size_multiplier(intent, 0.5)  # noqa: SLF001

    assert intent["paper_sizing_source"] == "V2_ADAPTIVE_ALLOCATOR_INCOMPLETE_ATTRIBUTION"
    assert intent["paper_sizing_complete"] is False
    assert intent["paper_allocation_block_reason"] == paper.ADAPTIVE_ALLOCATION_ATTRIBUTION_BLOCK_REASON
    assert "adaptive_capital_policy_version" in intent["paper_allocation_missing_fields"]
    assert "risk_budget_usd" in intent["paper_allocation_missing_fields"]
    assert intent["strategy_size_multiplier_skipped_reason"] == "ADAPTIVE_ALLOCATION_BLOCKED_OR_INCOMPLETE"
    assert intent["quantity"] == 1.0
    assert intent["notional"] == 100.0


def test_paper_sizing_fails_closed_without_selection_model_input_attribution() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "side": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "generated_utc": "2026-06-20T01:00:00Z",
    }
    allocation = {
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "allocation_id": "alloc_missing_selection_attribution",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 100.0,
        "target_quantity": 1.0,
        "risk_budget_usd": 1.0,
        "gross_notional_usd": 100.0,
        "allocated_margin_usd": 100.0,
        "recommended_leverage": 1.0,
        "effective_leverage": 1.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 100.0,
        "liquidation_price_estimate": 1.0,
        "liquidation_buffer_bps": 500.0,
        "expected_fees_usd": 0.04,
        "expected_slippage_usd": 0.02,
        "expected_funding_usd": 0.0,
        "expected_net_pnl_usd": 0.8,
        "expected_shortfall_usd": 1.5,
        "hedge_budget_usd": 0.0,
        "capital_allocation_reason": "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        "model_inputs": {},
    }

    paper._attach_paper_sizing(intent, allocation)  # noqa: SLF001

    assert intent["paper_sizing_source"] == "V2_ADAPTIVE_ALLOCATOR_INCOMPLETE_ATTRIBUTION"
    assert intent["paper_sizing_complete"] is False
    assert intent["paper_allocation_block_reason"] == paper.ADAPTIVE_ALLOCATION_ATTRIBUTION_BLOCK_REASON
    assert intent["paper_allocation_missing_fields"] == [
        "leverage_selection_model_input",
        "margin_mode_selection_model_input",
        "hedge_budget_selection_model_input",
    ]


def test_paper_sizing_backfills_margin_mode_attribution_from_recommended_mode() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "side": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "generated_utc": "2026-06-20T01:00:00Z",
        "allocator_liquidity_score": 0.65,
        "allocator_liquidity_score_source": "market_microstructure.orderbook_depth_usd+spread_bps",
        "allocator_liquidity_score_reason": "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD",
        "allocator_regime_score": 0.75,
        "allocator_regime_score_source": "strategy_router_regime_labels",
        "allocator_regime_score_reason": "REGIME_LABEL_CHOP_RANGE",
    }
    allocation = {
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "allocation_id": "alloc_sparse_margin_attribution",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 100.0,
        "target_quantity": 1.0,
        "risk_budget_usd": 1.0,
        "gross_notional_usd": 100.0,
        "allocated_margin_usd": 100.0,
        "recommended_leverage": 1.0,
        "effective_leverage": 1.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 100.0,
        "liquidation_price_estimate": 1.0,
        "liquidation_buffer_bps": 500.0,
        "expected_fees_usd": 0.04,
        "expected_slippage_usd": 0.02,
        "expected_funding_usd": 0.0,
        "expected_net_pnl_usd": 0.8,
        "expected_shortfall_usd": 1.5,
        "hedge_budget_usd": 0.0,
        "capital_allocation_reason": "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        "model_inputs": {
            "selected_leverage": 1.0,
            "leverage_selection_reason": "after_cost_edge_too_small_for_dynamic_leverage",
            "selected_hedge_budget_pct_of_risk": 0.0,
            "hedge_budget_selection_reason": "hedge_budget_not_required_for_current_risk",
        },
    }

    paper._attach_paper_sizing(intent, allocation)  # noqa: SLF001

    assert intent["paper_sizing_complete"] is True
    assert intent["paper_sizing_source"] == paper.PAPER_SIZING_SOURCE_ADAPTIVE
    assert "paper_allocation_missing_fields" not in intent
    assert allocation["model_inputs"]["selected_margin_mode"] == "isolated_paper_simulated"
    assert (
        allocation["model_inputs"]["margin_mode_selection_reason"]
        == "isolated_limits_tail_contagion_for_current_risk"
    )


def test_strategy_size_multiplier_rescales_adaptive_capital_accounting() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "side": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "generated_utc": "2026-06-20T01:00:00Z",
        "allocator_liquidity_score": 0.65,
        "allocator_liquidity_score_source": "market_microstructure.orderbook_depth_usd+spread_bps",
        "allocator_liquidity_score_reason": "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD",
        "allocator_regime_score": 0.75,
        "allocator_regime_score_source": "strategy_router_regime_labels",
        "allocator_regime_score_reason": "REGIME_LABEL_CHOP_RANGE",
    }
    allocation = {
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "allocation_id": "alloc_rescale",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 1000.0,
        "target_quantity": 10.0,
        "risk_budget_usd": 20.0,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "recommended_leverage": 2.0,
        "effective_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 100.0,
        "liquidation_price_estimate": 50.0,
        "liquidation_buffer_bps": 4500.0,
        "expected_fees_usd": 0.4,
        "expected_slippage_usd": 0.2,
        "expected_funding_usd": 0.1,
        "expected_net_pnl_usd": 8.0,
        "expected_shortfall_usd": 30.0,
        "hedge_budget_usd": 6.0,
        "capital_allocation_reason": "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        "model_inputs": {
            "selected_leverage": 2.0,
            "leverage_selection_reason": "test",
            "selected_margin_mode": "isolated_paper_simulated",
            "margin_mode_selection_reason": "test",
            "selected_hedge_budget_pct_of_risk": 0.2,
            "hedge_budget_selection_reason": "test",
            "expected_funding_bps": 1.0,
            "funding_interval_seconds": 3600.0,
        },
    }

    paper._attach_paper_sizing(intent, allocation)  # noqa: SLF001
    paper._apply_strategy_size_multiplier(intent, 0.5)  # noqa: SLF001

    assert intent["paper_sizing_complete"] is True
    assert intent["policy_activated_at"] == "2026-06-20T01:00:00Z"
    assert intent["adaptive_allocation"]["policy_activated_at"] == "2026-06-20T01:00:00Z"
    assert intent["expected_funding_bps"] == 1.0
    assert intent["funding_rate"] == 0.0001
    assert intent["funding_interval_seconds"] == 3600.0
    assert intent["adaptive_allocation"]["expected_funding_bps"] == 1.0
    assert intent["adaptive_allocation"]["model_inputs"]["funding_rate"] == 0.0001
    assert intent["adaptive_allocation"]["allocator_liquidity_score"] == 0.65
    assert intent["adaptive_allocation"]["allocator_liquidity_score_source"] == (
        "market_microstructure.orderbook_depth_usd+spread_bps"
    )
    assert intent["adaptive_allocation"]["allocator_liquidity_score_reason"] == (
        "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD"
    )
    assert intent["adaptive_allocation"]["allocator_regime_score"] == 0.75
    assert intent["adaptive_allocation"]["allocator_regime_score_source"] == (
        "strategy_router_regime_labels"
    )
    assert intent["adaptive_allocation"]["allocator_regime_score_reason"] == "REGIME_LABEL_CHOP_RANGE"
    assert intent["adaptive_allocation"]["model_inputs"]["allocator_liquidity_score"] == 0.65
    assert intent["adaptive_allocation"]["model_inputs"]["allocator_regime_score"] == 0.75
    assert intent["quantity"] == 5.0
    assert intent["notional"] == 500.0
    assert intent["gross_notional_usd"] == 500.0
    assert intent["allocated_margin_usd"] == 250.0
    assert intent["effective_leverage"] == 2.0
    assert intent["risk_budget_usd"] == 10.0
    assert intent["expected_fees_usd"] == 0.2
    assert intent["expected_slippage_usd"] == 0.1
    assert intent["expected_funding_usd"] == 0.05
    assert intent["expected_net_pnl_usd"] == 4.0
    assert intent["expected_shortfall_usd"] == 15.0
    assert intent["hedge_budget_usd"] == 3.0
    assert intent["adaptive_capital_accounting_adjusted_to_actual_notional"] is True
    assert intent["adaptive_capital_accounting_adjustment_ratio"] == 0.5
    assert intent["adaptive_allocation"]["target_notional_usdt"] == 500.0
    assert intent["adaptive_allocation"]["target_quantity"] == 5.0
    assert intent["adaptive_allocation"]["gross_notional_usd"] == 500.0
    assert intent["adaptive_allocation"]["allocated_margin_usd"] == 250.0
    assert intent["adaptive_allocation"]["risk_budget_usd"] == 10.0
    assert intent["adaptive_allocation"]["expected_fees_usd"] == 0.2
    assert intent["adaptive_allocation"]["expected_slippage_usd"] == 0.1
    assert intent["adaptive_allocation"]["expected_funding_usd"] == 0.05
    assert intent["adaptive_allocation"]["expected_net_pnl_usd"] == 4.0
    assert intent["adaptive_allocation"]["expected_shortfall_usd"] == 15.0
    assert intent["adaptive_allocation"]["hedge_budget_usd"] == 3.0
    assert intent["adaptive_allocation"]["model_inputs"]["selected_allocated_margin_usd"] == 250.0


def test_build_allocation_input_uses_explicit_fee_and_funding_from_entry_features() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "generated_utc": "2026-06-20T01:00:00Z",
        "entry_feature_source": "v2:features:latest:BTCUSDT:1m",
    }
    signal = {
        "price_target": 100.0,
        "market_state_integrity_score": 92.0,
        "regime_score": 1.0,
    }
    prediction = {
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 55.0,
        "features": {
            "expected_slippage_bps": 0.7,
            "taker_fee_bps": "3.5",
            "funding_rate": "0.00012",
        },
    }

    row = paper._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction=prediction,
        portfolio_context={
            "equity": 1000.0,
            "available_margin": 900.0,
            "wallet_balance": 1000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "entry_spread_available_at": "2026-06-20T00:59:59Z",
            "entry_spread_decision_time": "2026-06-20T01:00:00Z",
            "bid_depth_usd": 50_000.0,
            "ask_depth_usd": 45_000.0,
            "orderbook_depth_usd": 45_000.0,
        },
    )

    assert row.fee_bps == 3.5
    assert row.slippage_bps == 0.7
    assert round(row.expected_funding_bps, 8) == 1.2
    assert intent["fee_bps"] == 3.5
    assert intent["fee_bps_source"] == "v2:features:latest:BTCUSDT:1m.taker_fee_bps"
    assert intent["fee_bps_fallback"] is False
    assert intent["expected_funding_bps"] == 1.2
    assert intent["expected_funding_bps_source"] == "v2:features:latest:BTCUSDT:1m.funding_rate"
    assert intent["expected_funding_bps_conversion"] == "funding_rate_to_bps"
    assert intent["expected_funding_bps_fallback"] is False
    assert intent["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert intent["market_cost_evidence_missing_fields"] == []
    assert intent["market_cost_evidence_pit_reject_reasons"] == []
    assert intent["market_cost_evidence_source_fields"] == {
        "actual_observed_spread_entry_bps": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "expected_funding_bps": "v2:features:latest:BTCUSDT:1m.funding_rate",
        "expected_slippage_bps": "v2:features:latest:BTCUSDT:1m.expected_slippage_bps",
        "fee_bps": "v2:features:latest:BTCUSDT:1m.taker_fee_bps",
        "orderbook_depth_usd": "orderbook_depth_usd",
    }
    lineage = intent["market_cost_evidence_source_lineage"]
    assert lineage == {
        "source": "paper_loop_decision_time_market_cost_capture",
        "decision_time": lineage["decision_time"],
        "model_decision_time": "2026-06-20T01:00:00Z",
        "signal_id": None,
        "prediction_id": None,
        "feature_snapshot_id": None,
        "feature_source": "v2:features:latest:BTCUSDT:1m",
        "feature_available_at": None,
        "feature_generated_at": None,
        "feature_cutoff": None,
        "entry_spread_available_at": "2026-06-20T00:59:59Z",
        "entry_spread_captured_at": lineage["entry_spread_captured_at"],
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "orderbook_depth_source": None,
        "fee_bps_source": "v2:features:latest:BTCUSDT:1m.taker_fee_bps",
        "expected_funding_bps_source": "v2:features:latest:BTCUSDT:1m.funding_rate",
        "expected_slippage_source": "v2:features:latest:BTCUSDT:1m.expected_slippage_bps",
    }
    assert lineage["decision_time"] == intent["entry_spread_captured_at"]
    assert lineage["entry_spread_captured_at"] == intent["entry_spread_captured_at"]


def test_build_allocation_input_derives_liquidity_and_regime_scores_from_context() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "generated_utc": "2026-06-20T01:00:00Z",
        "entry_feature_source": "v2:features:latest:BTCUSDT:1m",
        "strategy_regime_labels": ["CHOP", "RANGE"],
        "strategy_router_selected_mode": "mean_reversion",
    }
    signal = {
        "price_target": 100.0,
        "market_state_integrity_score": 92.0,
    }
    prediction = {
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 55.0,
        "features": {
            "expected_slippage_bps": 0.7,
            "taker_fee_bps": "3.5",
            "funding_rate": "0.00002",
        },
    }

    row = paper._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction=prediction,
        portfolio_context={
            "equity": 1000.0,
            "available_margin": 900.0,
            "wallet_balance": 1000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "entry_spread_available_at": "2026-06-20T00:59:59Z",
            "entry_spread_decision_time": "2026-06-20T01:00:00Z",
            "bid_depth_usd": 30_000.0,
            "ask_depth_usd": 35_000.0,
            "orderbook_depth_usd": 30_000.0,
        },
    )

    assert row.liquidity_score == 0.65
    assert row.regime_score == 0.75
    assert intent["allocator_liquidity_score"] == 0.65
    assert intent["allocator_liquidity_score_source"] == "market_microstructure.orderbook_depth_usd+spread_bps"
    assert intent["allocator_liquidity_score_reason"] == "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD"
    assert intent["allocator_regime_score"] == 0.75
    assert intent["allocator_regime_score_source"] == "strategy_router_regime_labels"
    assert intent["allocator_regime_score_reason"] == "REGIME_LABEL_CHOP_RANGE"


def test_build_allocation_input_normalizes_short_downside_edge_for_allocator_contract() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "short",
        "entry_price": 2500.0,
        "generated_utc": "2026-06-20T01:00:00Z",
        "entry_feature_source": "v2:features:latest:ETHUSDT:5m",
    }
    signal = {
        "side": "short",
        "price_target": 2500.0,
        "market_state_integrity_score": 94.0,
        "regime_score": 1.0,
    }
    prediction = {
        "confidence_calibrated": 0.88,
        "expected_move_after_cost_bps": -70.0,
        "features": {
            "expected_slippage_bps": 0.8,
            "taker_fee_bps": 3.5,
            "funding_rate": -0.00004,
        },
    }

    row = paper._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction=prediction,
        portfolio_context={
            "equity": 1000.0,
            "available_margin": 900.0,
            "wallet_balance": 1000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.4,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "entry_spread_available_at": "2026-06-20T00:59:59Z",
            "entry_spread_decision_time": "2026-06-20T01:00:00Z",
            "bid_depth_usd": 30_000.0,
            "ask_depth_usd": 35_000.0,
            "orderbook_depth_usd": 30_000.0,
        },
    )

    assert row.action == "short"
    assert row.expected_move_after_cost_bps == -70.0
    assert intent["paper_allocation_signed_edge_normalized"] is True
    assert intent["paper_allocation_signed_expected_move_after_cost_bps"] == -70.0
    assert "paper_allocation_signed_edge_mismatch" not in intent
    assert intent["entry_orderbook_depth_side"] == "bid"
    assert intent["expected_funding_bps"] == -0.4


def test_build_allocation_input_keeps_missing_fee_and_funding_out_of_intent() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "generated_utc": "2026-06-20T01:00:00Z",
        "entry_feature_source": "v2:features:latest:BTCUSDT:1m",
    }
    signal = {
        "price_target": 100.0,
        "market_state_integrity_score": 92.0,
        "regime_score": 1.0,
    }
    prediction = {
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 55.0,
        "features": {"expected_slippage_bps": 0.7},
    }

    row = paper._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction=prediction,
        portfolio_context={
            "equity": 1000.0,
            "available_margin": 900.0,
            "wallet_balance": 1000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "entry_spread_available_at": "2026-06-20T00:59:59Z",
            "entry_spread_decision_time": "2026-06-20T01:00:00Z",
        },
    )

    configured_fee = paper._configured_paper_fee_bps()  # noqa: SLF001
    assert row.fee_bps == configured_fee
    assert row.expected_funding_bps == 0.0
    # Configured fee is production-grade: fee_bps IS recorded, not marked as fallback.
    assert intent["fee_bps"] == configured_fee
    assert intent["fee_bps_source"] == paper.PAPER_CONFIGURED_FEE_SCHEDULE_SOURCE  # noqa: SLF001
    assert intent["fee_bps_fallback"] is False
    assert intent["fee_bps_for_allocator"] == configured_fee
    assert "expected_funding_bps" not in intent
    assert intent["expected_funding_bps_fallback"] is True
    assert intent["expected_funding_bps_for_allocator"] is None


def test_runtime_market_evidence_blocks_missing_entry_feature_temporal_labels() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "entry_price_provenance_present": True,
        "actual_observed_spread_entry_bps": 1.2,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "test",
        "generated_utc": "2026-06-20T01:00:00Z",
    }

    reasons = paper._paper_runtime_market_evidence_rejection_reasons(intent)  # noqa: SLF001

    assert "MISSING_ENTRY_FEATURE_AVAILABLE_AT" in reasons
    assert "MISSING_ENTRY_FEATURE_GENERATED_AT" in reasons
    assert "MISSING_ENTRY_FEATURE_CUTOFF" in reasons
    assert "ENTRY_FEATURE_CANDLE_NOT_CONFIRMED_CLOSED" in reasons


def test_runtime_market_evidence_blocks_future_feature_temporal_labels() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "entry_price_provenance_present": True,
        "actual_observed_spread_entry_bps": 1.2,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "test",
        "entry_feature_decision_time": "2026-06-20T01:00:00Z",
        "entry_feature_available_at": "2026-06-20T01:01:00Z",
        "entry_feature_generated_at": "2026-06-20T01:02:00Z",
        "entry_feature_cutoff": "2026-06-20T01:03:00Z",
        "entry_feature_candle_closed_confirmed": True,
    }

    reasons = paper._paper_runtime_market_evidence_rejection_reasons(intent)  # noqa: SLF001

    assert "ENTRY_FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME" in reasons
    assert "ENTRY_FEATURE_GENERATED_AT_AFTER_DECISION_TIME" in reasons
    assert "ENTRY_FEATURE_CUTOFF_AFTER_DECISION_TIME" in reasons


def test_runtime_market_evidence_allows_complete_entry_feature_temporal_labels() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "entry_price_provenance_present": True,
        "actual_observed_spread_entry_bps": 1.2,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "test",
        "entry_feature_decision_time": "2026-06-20T01:00:00Z",
        "entry_feature_available_at": "2026-06-20T00:59:00Z",
        "entry_feature_generated_at": "2026-06-20T00:58:00Z",
        "entry_feature_cutoff": "2026-06-20T00:55:00Z",
        "entry_feature_candle_closed_confirmed": True,
    }

    reasons = paper._paper_runtime_market_evidence_rejection_reasons(intent)  # noqa: SLF001

    assert reasons == []


def test_paper_drawdown_recovery_allows_clean_minority_side_reduce_size() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "closed_trades": [
            {"side": "short", "strategy_selected_mode": "trend_mode"}
            for _ in range(60)
        ],
        "open_positions": [],
    }
    router = {
        "selected_mode": "no_trade_mode",
        "allowed_actions": ["hold"],
        "action_mask": {"hold": True, "long": False, "short": False, "close": False},
        "size_multiplier": 1.0,
        "block_reason": "DRAWDOWN_LIMIT_BLOCK",
        "reason_codes": ["DRAWDOWN_LIMIT_BLOCK"],
        "regime_labels": ["no_trade"],
        "explanation": {"current_drawdown_bps": 300.0},
    }

    recovered, guard = paper._paper_drawdown_recovery_router_result(  # noqa: SLF001
        existing_ledger=ledger,
        strategy_router=router,
        candidate_side="long",
        current_position_state="FLAT",
        paper_fill_allowed_upstream=True,
        expected_move_after_cost_bps=25.0,
        confidence_calibrated=0.66,
        live_gate="blocked_human_only",
    )

    assert guard["allowed"] is True
    assert guard["recovered"] is True
    assert guard["directional_guard"]["minority_side"] == "long"
    assert recovered["selected_mode"] == "reduce_size_mode"
    assert recovered["block_reason"] is None
    assert recovered["action_mask"]["long"] is True
    assert "long" in recovered["allowed_actions"]
    assert recovered["size_multiplier"] == paper.PAPER_DRAWDOWN_RECOVERY_SIZE_MULTIPLIER
    assert paper.PAPER_DRAWDOWN_RECOVERY_REASON in recovered["reason_codes"]


def test_paper_drawdown_recovery_allows_clean_short_downside_edge() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "closed_trades": [
            {"side": "long", "strategy_selected_mode": "trend_mode"}
            for _ in range(60)
        ],
        "open_positions": [],
    }
    router = {
        "selected_mode": "no_trade_mode",
        "allowed_actions": ["hold"],
        "action_mask": {"hold": True, "long": False, "short": False, "close": False},
        "size_multiplier": 1.0,
        "block_reason": "DRAWDOWN_LIMIT_BLOCK",
        "reason_codes": ["DRAWDOWN_LIMIT_BLOCK"],
        "regime_labels": ["no_trade"],
        "explanation": {"current_drawdown_bps": 300.0},
    }

    recovered, guard = paper._paper_drawdown_recovery_router_result(  # noqa: SLF001
        existing_ledger=ledger,
        strategy_router=router,
        candidate_side="short",
        current_position_state="FLAT",
        paper_fill_allowed_upstream=True,
        expected_move_after_cost_bps=-25.0,
        confidence_calibrated=0.66,
        live_gate="blocked_human_only",
    )

    assert guard["allowed"] is True
    assert guard["recovered"] is True
    assert guard["expected_move_after_cost_favorable_for_side"] is True
    assert guard["directional_guard"]["minority_side"] == "short"
    assert recovered["selected_mode"] == "reduce_size_mode"
    assert recovered["action_mask"]["short"] is True
    assert "short" in recovered["allowed_actions"]


def test_paper_drawdown_recovery_blocks_same_side_open_position() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    ledger = {
        "closed_trades": [
            {"side": "short", "strategy_selected_mode": "trend_mode"}
            for _ in range(60)
        ],
        "open_positions": [{"symbol": "ETHUSDT", "side": "long", "net_quantity": 1.0}],
    }
    router = {
        "selected_mode": "no_trade_mode",
        "allowed_actions": ["hold"],
        "action_mask": {"hold": True, "long": False, "short": False, "close": False},
        "size_multiplier": 1.0,
        "block_reason": "DRAWDOWN_LIMIT_BLOCK",
        "reason_codes": ["DRAWDOWN_LIMIT_BLOCK"],
        "regime_labels": ["no_trade"],
        "explanation": {"current_drawdown_bps": 300.0},
    }

    unchanged, guard = paper._paper_drawdown_recovery_router_result(  # noqa: SLF001
        existing_ledger=ledger,
        strategy_router=router,
        candidate_side="long",
        current_position_state="LONG",
        paper_fill_allowed_upstream=True,
        expected_move_after_cost_bps=25.0,
        confidence_calibrated=0.66,
        live_gate="blocked_human_only",
    )

    assert unchanged == router
    assert guard["allowed"] is False
    assert guard["recovered"] is False
    assert guard["block_reason"] == "CURRENT_POSITION_NOT_FLAT"


def test_run_once_strategy_mode_collapse_blocks_majority_mode_fill(monkeypatch) -> None:
    fake = FakeRedis()
    generated_utc = _utc_now_for_test()
    fake.store["v2:signals:paper"] = json.dumps(
        [
            {
                "signal_id": "signal-trend-long",
                "prediction_id": "prediction-trend-long",
                "risk_decision_id": "risk-trend-long",
                "orchestrator_decision_id": "orch-trend-long",
                "winner_proposal_id": "intent-trend-long",
                "symbol": "ETHUSDT",
                "timeframe": "15m",
                "side": "long",
                "expected_move_after_cost_bps": 35.0,
                "confidence_calibrated": 0.82,
                "feature_cutoff": "2026-06-19T03:15:00Z",
                "decision_time": generated_utc,
                "available_at": generated_utc,
                "generated_utc": generated_utc,
                "market_state_id": "mstate_eth_15m",
                "market_state_integrity_score": 96.0,
                "valid_for_paper": True,
                "market_state_reject_reasons": [],
                "paper_fill_allowed": True,
                "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
            }
        ]
    )
    fake.store["v2:prediction:ETHUSDT:15m"] = json.dumps(
        {
            "prediction_id": "prediction-trend-long",
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "selected_action": "long",
            "confidence_calibrated": 0.82,
            "expected_move_after_cost_bps": 35.0,
            "feature_cutoff": "2026-06-19T03:15:00Z",
            "decision_time": generated_utc,
            "available_at": generated_utc,
            "generated_utc": generated_utc,
            "market_state_integrity_score": 96.0,
        }
    )
    fake.store["v2:market:prices:ETHUSDT"] = json.dumps(
        {
            "ticker_24hr": {"lastPrice": "2500.0"},
            "fetched_utc": "2026-06-19T03:30:00Z",
        }
    )
    fake.store["v2:market:orderbook:ETHUSDT"] = json.dumps(
        {
            "E": 1781834577407,
            "bids": [["2499.80", "4.0"]],
            "asks": [["2500.20", "2.0"]],
        }
    )
    fake.store["v2:portfolio:state"] = json.dumps(
        {
            "equity": 10_000.0,
            "available_margin": 10_000.0,
            "wallet_balance": 10_000.0,
        }
    )
    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "closed_trades": [
                {
                    "side": "long" if idx % 2 == 0 else "short",
                    "strategy_selected_mode": "trend_mode",
                    "realized_pnl_usdt": 0.1,
                }
                for idx in range(60)
            ],
            "accepted": [],
            "open_positions": [],
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})
    monkeypatch.setattr(paper, "_read_accepted_fill_state_file", lambda *a, **kw: {})

    status = paper.run_once()
    ledger = json.loads(fake.store["v2:paper:ledger"])
    blocked = [
        row for row in ledger["blocked"] if row.get("signal_id") == "signal-trend-long"
    ]

    assert status["intents_accepted"] == 0
    assert ledger["current_cycle_accepted_count"] == 0
    assert len(blocked) == 1
    assert blocked[0]["paper_fill_block_reason"] == paper.STRATEGY_MODE_COLLAPSE_BLOCK_REASON
    assert "paper_strategy_mode_collapse_guard" not in blocked[0]
    assert f"strategy_mode_collapse_guard:{paper.STRATEGY_MODE_COLLAPSE_BLOCK_REASON}" in blocked[0][
        "local_block_reasons"
    ]
    assert (
        status["paper_strategy_mode_collapse_guard_status"]["blocked_majority_mode_fill_count"]
        == 1
    )
    assert status["paper_directional_collapse_guard_status"]["blocked_majority_side_fill_count"] == 0


def test_quarantined_feedback_reports_exact_missing_field() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    close_event = {
        "trainer_feedback_id": "fb_missing",
        "outcome_label_id": "out_missing",
        "position_id": "pos_missing",
        "symbol": "BTCUSDT",
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following_v1",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "realized_pnl_bps": 18.0,
        "hold_time_seconds": 300,
        "market_regime": "TREND",
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"source": "test"},
        "liquidity_context": {"source": "test"},
        "liquidation_distance_context": {"source": "test"},
        "microstructure_context": {"source": "test"},
        "oi_funding_context": {"source": "test"},
        "public_intel_context": {"source": "test"},
        "major_move_context": {"source": "test"},
        "future_window_label_source": "closed_trade_outcome",
        "drawdown_at_entry": 0.0,
    }

    rows = paper._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[dict(close_event)],
    )

    assert rows[0]["trainer_consumable"] is False
    assert "missing_prediction_id" in rows[0]["missing_feedback_classifications"]
    assert "missing_entry_price" in rows[0]["missing_feedback_classifications"]


def test_paper_loop_recovers_feedback_context_from_source_entry_fill() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    close_event = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": "BTCUSDT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "realized_pnl_bps": 18.0,
        "hold_time_seconds": 300,
        "source_fill_ids": ["fill_1"],
    }
    outcome_label = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "realized_pnl_bps": 18.0,
    }
    entry_context = {
        "fill_id": "fill_1",
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "signal_id": "sig_1",
        "entry_signal_id": "sig_1",
        "feature_snapshot_id": "feat_1",
        "entry_feature_snapshot_id": "feat_1",
        "market_state_id": "ms_1",
        "entry_market_state_id": "ms_1",
        "timeframe": "1m",
        "action": "long",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl": 1.0,
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following",
        "entry_reason": "trend_following",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "drawdown_at_entry": 0.0,
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"source": "entry_liquidity"},
        "liquidity_context": {"source": "entry_liquidity"},
        "liquidation_distance_context": {"source": "entry_liquidation"},
        "microstructure_context": {"source": "entry_microstructure"},
        "oi_funding_context": {"source": "entry_oi_funding"},
        "public_intel_context": {"source": "entry_public_intel"},
        "major_move_context": {"source": "test", "status": "not_major_move_trade"},
        "future_window_label_source": "closed_trade_outcome",
        **_audit_quality_fields(),
    }
    prediction = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "decision_id": "decision_1",
        "feature_cutoff": "2026-06-11T10:00:00Z",
        "available_at": "2026-06-11T10:00:01Z",
        "decision_time": "2026-06-11T10:00:02Z",
        "model_version": "native_cuda_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": {"feature_vector_hash": "hash_feat_1"},
    }

    rows = paper._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        entry_context_rows=[entry_context],
        predictions_by_id={"pred_1": prediction},
    )

    assert len(rows) == 1
    assert rows[0]["trainer_consumable"] is True
    assert rows[0]["strategy_id"] == "trend_following_v1"
    assert rows[0]["market_regime_at_exit"] == "TREND"
    assert rows[0]["liquidity_zone_context"] == {"source": "entry_liquidity"}
    assert rows[0]["missing_feedback_fields"] == []


def test_replay_snapshot_lineage_reconstructs_existing_feedback_with_checkpoint_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "CHECKPOINT_DIR", tmp_path)
    checkpoint_id = "v2_hybrid_ckpt_legacy"
    (tmp_path / f"{checkpoint_id}.json").write_text(
        json.dumps(
            {
                "checkpoint_id": checkpoint_id,
                "model_id": "v2_hybrid_policy_legacy",
                "weight_blob_written": True,
            }
        ),
        encoding="utf-8",
    )
    fake = FakeRedis()
    fake.store["v2:replay:snapshots:pred_legacy"] = json.dumps(
        {
            "prediction_id": "pred_legacy",
            "symbol": "DOGEUSDT",
            "timeframe": "5m",
            "ppo_action": "short",
            "decision_id": "decision_legacy",
            "mtf_snapshot_id": "mtf_legacy",
            "ppo_feature_cutoff": "2026-06-11T10:00:00Z",
            "decision_time": "2026-06-11T10:00:02Z",
            "generated_at": "2026-06-11T10:00:02Z",
            "feature_vector_hash": "tensor_hash_legacy",
            "missing_mask_hash": "missing_hash_legacy",
            "stale_mask_hash": "stale_hash_legacy",
            "replay_snapshot_id": "replay_legacy",
        }
    )
    close_event = {
        "trainer_feedback_id": "fb_legacy",
        "outcome_label_id": "out_legacy",
        "position_id": "pos_legacy",
        "symbol": "DOGEUSDT",
        "prediction_id": "pred_legacy",
        "entry_prediction_id": "pred_legacy",
        "signal_id": "sig_legacy",
        "entry_signal_id": "sig_legacy",
        "feature_snapshot_id": "feat_legacy",
        "entry_feature_snapshot_id": "feat_legacy",
        "market_state_id": "ms_legacy",
        "entry_market_state_id": "ms_legacy",
        "timeframe": "5m",
        "action": "short",
        "selected_action": "short",
        "entry_price": 0.20,
        "exit_price": 0.19,
        "realized_pnl": 0.21,
        "realized_pnl_bps": 53.8,
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following_v1",
        "entry_reason": "trend_following",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "hold_time_seconds": 300,
        "exit_time": "2026-06-11T10:05:00Z",
        "market_regime": "TREND",
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"source": "entry_liquidity"},
        "liquidity_context": {"source": "entry_liquidity"},
        "liquidation_distance_context": {"source": "entry_liquidation"},
        "microstructure_context": {"source": "entry_microstructure"},
        "oi_funding_context": {"source": "entry_oi_funding"},
        "public_intel_context": {"source": "entry_public_intel"},
        "major_move_context": {"source": "test", "status": "not_major_move_trade"},
        "future_window_label_source": "closed_trade_outcome",
        "drawdown_at_entry": 0.0,
        "checkpoint_id": checkpoint_id,
        **_audit_quality_fields(),
    }
    outcome_label = {
        "trainer_feedback_id": "fb_legacy",
        "outcome_label_id": "out_legacy",
        "position_id": "pos_legacy",
        "symbol": "DOGEUSDT",
        "timeframe": "5m",
        "realized_pnl_bps": 53.8,
    }
    contexts = paper._lineage_context_by_prediction_id([close_event], [outcome_label])  # noqa: SLF001
    replay_predictions = paper._read_replay_snapshot_predictions(fake, contexts)  # noqa: SLF001

    rows = paper._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id=replay_predictions,
        feature_snapshots_by_id={
            "feat_legacy": {
                "feature_snapshot_id": "feat_legacy",
                "symbol": "DOGEUSDT",
                "timeframe": "5m",
                "available_at": "2026-06-11T10:00:01Z",
                "feature_cutoff": "2026-06-11T10:00:00Z",
                "features": {"ret_pct": -0.01},
            }
        },
    )

    assert rows[0]["trainer_consumable"] is True
    assert rows[0]["trust_reconstructed"] is True
    assert rows[0]["decision_id"] == "decision_legacy"
    assert rows[0]["mtf_snapshot_id"] == "mtf_legacy"
    assert rows[0]["feature_cutoff"] == "2026-06-11T10:00:00Z"
    assert rows[0]["available_at"] == "2026-06-11T10:00:02Z"
    assert rows[0]["model_version"] == "v2_hybrid_policy_legacy"
    assert rows[0]["checkpoint_id"] == checkpoint_id
    assert rows[0]["source_hashes"]["feature_vector_hash"] == "tensor_hash_legacy"


def test_embedded_replay_feature_snapshot_reconstructs_fill_lineage() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    fill = {
        "fill_id": "fill_1",
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_feature_snapshot_id": "feat_1",
    }
    replay_snapshot = {
        "prediction_id": "pred_1",
        "signal_id": "sig_pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "feature_snapshot_id": "feat_1",
        "feature_snapshot": {
            "feature_snapshot_id": "feat_1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "available_at": "2026-06-11T10:00:01Z",
            "feature_cutoff": "2026-06-11T10:00:00Z",
            "features": {"ret_pct": 0.01},
        },
        "decision_id": "decision_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": "2026-06-11T10:00:00Z",
        "available_at": "2026-06-11T10:00:01Z",
        "decision_time": "2026-06-11T10:00:02Z",
        "model_version": "native_cuda_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": {"feature_vector_hash": "hash_feat_1"},
    }
    context = paper._lineage_context_by_prediction_id([fill])  # noqa: SLF001
    prediction = paper._prediction_from_replay_snapshot(  # noqa: SLF001
        replay_snapshot,
        context["pred_1"],
    )
    feature_snapshots = paper._feature_snapshots_from_replay_predictions(  # noqa: SLF001
        {"pred_1": prediction}
    )

    rows = paper._backfill_fill_lineage_from_predictions(  # noqa: SLF001
        [fill],
        {"pred_1": prediction},
        feature_snapshots_by_id=feature_snapshots,
        require_feature_snapshot_deref=True,
    )

    assert rows[0]["trust_reconstructed"] is True
    assert rows[0]["decision_id"] == "decision_1"
    assert rows[0]["entry_feature_snapshot_id"] == "feat_1"
    assert rows[0]["trust_source_ids"]["entry_feature_snapshot_id"] == "feat_1"


def test_mismatched_embedded_replay_feature_snapshot_is_not_trust_evidence() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    replay_prediction = {
        "prediction_id": "pred_1",
        "feature_snapshot_id": "feat_expected",
        "feature_snapshot": {
            "feature_snapshot_id": "feat_other",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "features": {"ret_pct": 0.01},
        },
    }

    assert paper._feature_snapshots_from_replay_predictions(  # noqa: SLF001
        {"pred_1": replay_prediction}
    ) == {}


def test_pre_remediation_fill_missing_feature_snapshot_is_noncritical_stale_lineage() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    close_event = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": "BTCUSDT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "realized_pnl_bps": 18.0,
        "hold_time_seconds": 300,
        "source_fill_ids": ["fill_1"],
    }
    outcome_label = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "realized_pnl_bps": 18.0,
    }
    entry_context = {
        "fill_id": "fill_1",
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "signal_id": "sig_1",
        "entry_signal_id": "sig_1",
        "market_state_id": "ms_1",
        "entry_market_state_id": "ms_1",
        "timeframe": "1m",
        "action": "long",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl": 1.0,
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following",
        "entry_reason": "trend_following",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "drawdown_at_entry": 0.0,
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"source": "entry_liquidity"},
        "liquidity_context": {"source": "entry_liquidity"},
        "liquidation_distance_context": {"source": "entry_liquidation"},
        "microstructure_context": {"source": "entry_microstructure"},
        "oi_funding_context": {"source": "entry_oi_funding"},
        "public_intel_context": {"source": "entry_public_intel"},
        "major_move_context": {"source": "test", "status": "not_major_move_trade"},
        "future_window_label_source": "closed_trade_outcome",
        "paper_fill_persistence_status": "EXISTING_FILL_IMMUTABLE_FIELDS_PRESERVED",
        "original_fill_utc": "2026-06-15T21:51:58Z",
        **_audit_quality_fields(),
    }

    rows = paper._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        entry_context_rows=[entry_context],
    )

    assert rows[0]["trainer_consumable"] is False
    assert rows[0]["missing_feedback_fields"] == ["feature_snapshot_id"]
    assert "stale_lineage" in rows[0]["missing_feedback_classifications"]
    assert "trust:missing_trust_feature_snapshot_id" in rows[0]["missing_feedback_classifications"]
    assert "trust:trust_reconstruction:entry_prediction_not_found" in rows[0]["missing_feedback_classifications"]
    assert rows[0]["quarantine_non_critical"] is False
    assert rows[0]["non_critical_quarantine_reason"] is None


def test_execution_success_metrics_use_closed_trade_outcomes_before_blocked_candidates(
    monkeypatch,
) -> None:
    fake = FakeRedis()

    def complete_outcome(*, winner: bool, realized_pnl_bps: float) -> dict:
        return {
            "winner": winner,
            "realized_pnl_bps": realized_pnl_bps,
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "prediction_id": "pred_outcome",
            "entry_prediction_id": "pred_outcome",
            "signal_id": "sig_outcome",
            "entry_signal_id": "sig_outcome",
            "feature_snapshot_id": "feat_outcome",
            "entry_feature_snapshot_id": "feat_outcome",
            "market_state_id": "ms_outcome",
            "entry_market_state_id": "ms_outcome",
            "action": "long" if winner else "short",
            "entry_price": 100.0,
            "exit_price": 101.0 if winner else 99.0,
            "realized_pnl": realized_pnl_bps / 10000.0,
            "strategy_id": "trend_following_v1",
            "strategy_family": "trend_following",
            "strategy_subtype": "trend_following",
            "entry_reason": "trend_following",
            "hedge_state": "NO_HEDGE",
            "hedge_reason": "NO_HEDGE_CONTEXT",
            "exit_reason": "TIER_2_TAKE_PROFIT" if winner else "STOP_LOSS",
            "hold_time_seconds": 300,
            "market_regime_at_entry": "TREND",
            "market_regime_at_exit": "TREND",
            "market_regime": "TREND",
            "liquidity_zone_context": {"liquidity": "normal"},
            "liquidity_context": {"liquidity": "normal"},
            "liquidation_distance_context": {"distance_bps": 240.0},
            "microstructure_context": {"spread_bps": 1.2},
            "oi_funding_context": {"source": "test"},
            "public_intel_context": {"source": "test"},
            "major_move_context": {"source": "test", "status": "not_major_move_trade"},
            "future_window_label_source": "closed_trade_outcome",
            "drawdown_at_entry": 0.0,
            **_audit_quality_fields(),
        }

    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "accepted_count": 20,
            "blocked_count": 80,
            "shadow_observation_count": 0,
            "outcome_labels": [
                complete_outcome(winner=True, realized_pnl_bps=12.0),
                complete_outcome(winner=False, realized_pnl_bps=-5.0),
                complete_outcome(winner=True, realized_pnl_bps=8.0),
            ],
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})

    metrics = paper._read_recent_execution_metrics(fake)  # noqa: SLF001

    assert metrics["execution_success_probability"] == 0.666667
    assert metrics["execution_success_metric_source"] == "V2_PAPER_CLOSED_TRADE_OUTCOMES_ALPHA_COMPLETE"
    assert metrics["execution_success_sample_status"] == "ALPHA_COMPLETE_OUTCOME_SAMPLE"
    assert metrics["closed_trade_outcome_count"] == 3
    assert metrics["clean_closed_trade_outcome_count"] == 3
    assert metrics["dirty_closed_trade_outcome_count"] == 0
    assert metrics["raw_closed_trade_outcome_count"] == 3


def test_execution_success_metrics_quarantine_incomplete_closed_outcomes(
    monkeypatch,
) -> None:
    fake = FakeRedis()
    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "accepted_count": 20,
            "blocked_count": 80,
            "shadow_observation_count": 0,
            "outcome_labels": [
                {
                    "winner": True,
                    "realized_pnl_bps": 12.0,
                    "strategy_id": None,
                    "strategy_family": None,
                    "market_regime_at_entry": None,
                }
            ],
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})

    metrics = paper._read_recent_execution_metrics(fake)  # noqa: SLF001

    assert metrics["execution_success_probability"] is None
    assert metrics["execution_success_metric_source"] == "INSUFFICIENT_ALPHA_FEEDBACK_OUTCOMES"
    assert metrics["execution_success_sample_status"] == "DIRTY_OUTCOMES_QUARANTINED"
    assert metrics["closed_trade_outcome_count"] == 0
    assert metrics["clean_closed_trade_outcome_count"] == 0
    assert metrics["dirty_closed_trade_outcome_count"] == 1
    assert metrics["raw_closed_trade_outcome_count"] == 1


def test_paper_loop_quarantines_incomplete_trainer_feedback_rows(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:paper:ledger"] = json.dumps(
        {
            "closed_trades": [
                {
                    "trainer_feedback_id": "fb_incomplete",
                    "outcome_label_id": "out_incomplete",
                    "position_id": "pos_incomplete",
                    "symbol": "BTCUSDT",
                    "realized_pnl_bps": 4.2,
                    "hold_time_seconds": 120,
                    "exit_reason": "TIER_2_TAKE_PROFIT",
                }
            ],
            "outcome_labels": [
                {
                    "trainer_feedback_id": "fb_incomplete",
                    "outcome_label_id": "out_incomplete",
                    "position_id": "pos_incomplete",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "entry_prediction_id": "pred",
                    "exit_time": "2026-06-11T10:00:00Z",
                    "realized_pnl_bps": 4.2,
                }
            ],
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    monkeypatch.setattr(paper, "_connect_redis", lambda: fake)
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda *a, **kw: {})

    status = paper.run_once()

    trainer_rows = json.loads(fake.store["v2:trainer:feedback:outcomes"])
    quarantine_rows = json.loads(fake.store["v2:trainer:feedback:outcomes:quarantine"])
    ledger = json.loads(fake.store["v2:paper:ledger"])

    assert status["trainer_feedback_row_count"] == 0
    assert status["trainer_feedback_quarantined_row_count"] == 1
    assert trainer_rows == []
    assert len(quarantine_rows) == 1
    assert "strategy_id" in quarantine_rows[0]["missing_feedback_fields"]
    assert ledger["trainer_feedback_row_count"] == 0
    assert ledger["trainer_feedback_quarantined_row_count"] == 1
    assert ledger["paper_closed_trade_outcome_label_status"]["trainer_feedback_total_rows"] == 1
    assert ledger["paper_closed_trade_outcome_label_status"]["trainer_feedback_rows_ready"] == 0
    assert ledger["paper_closed_trade_outcome_label_status"]["trainer_feedback_consumable_rows"] == 0
    assert ledger["paper_closed_trade_outcome_label_status"]["trainer_feedback_quarantined_rows"] == 1

    trade_management_status = json.loads(fake.store["v2:paper:trade_management:status"])
    outcome_status = trade_management_status["paper_closed_trade_outcome_label_status"]
    assert outcome_status["trainer_feedback_total_rows"] == 1
    assert outcome_status["trainer_feedback_rows_ready"] == 0
    assert outcome_status["trainer_feedback_consumable_rows"] == 0
    assert outcome_status["trainer_feedback_quarantined_rows"] == 1

    evidence_ttl = paper.PAPER_TRAINING_EVIDENCE_TTL_SECONDS
    transient_ttl = paper.PAPER_RUNTIME_TRANSIENT_TTL_SECONDS
    heartbeat_ttl = paper.PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS
    assert fake.expiries["v2:paper:ledger"] == evidence_ttl
    assert fake.expiries["v2:paper:positions"] == evidence_ttl
    assert fake.expiries["v2:paper:closed_trades"] == evidence_ttl
    assert fake.expiries["v2:paper:outcome_labels"] == evidence_ttl
    assert fake.expiries["v2:trainer:feedback:outcomes"] == evidence_ttl
    assert fake.expiries["v2:trainer:feedback:outcomes:quarantine"] == evidence_ttl
    assert fake.expiries["v2:paper:intents"] == transient_ttl
    assert fake.expiries["v2:paper:trade_management:status"] == heartbeat_ttl
    assert fake.expiries["v2:paper:heartbeat"] == heartbeat_ttl
    assert status["cycle_state"] == "COMPLETED_CYCLE"
    assert status["heartbeat_ttl_seconds"] == heartbeat_ttl
    assert status["paper_only"] is True
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["writes_legacy_redis"] is False


def test_paper_loop_attaches_trainer_feedback_entry_context() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
    }
    prediction = {
        "source_labels": [
            "v2:market:orderbook",
            "v2:market:microstructure",
            "v2:market:liquidation_levels",
        ],
        "market_state_source_lineage": {
            "missing_feature_names": ["nearest_bid_wall_distance_bps", "liquidation_count_5m"]
        },
    }
    strategy_router = {
        "selected_mode": "trend_following",
        "regime_labels": ["TREND", "MOMENTUM"],
        "explanation": {"liquidity_score": 0.82, "bid_ask_spread_bps": 1.4},
    }
    allocation = {"model_inputs": {"liquidity_score": 0.75, "spread_bps": 3.35}}

    paper._attach_trainer_feedback_entry_context(  # noqa: SLF001
        intent=intent,
        prediction=prediction,
        strategy_router=strategy_router,
        allocation=allocation,
        portfolio_context={"drawdown_bps": 0.0},
    )

    assert intent["strategy_id"] == "trend_following"
    assert intent["strategy_family"] == "trend_following"
    assert intent["hedge_state"] == "NO_HEDGE"
    assert intent["hedge_reason"] == "NO_HEDGE_CONTEXT"
    assert intent["drawdown_at_entry"] == 0.0
    assert intent["market_regime_at_entry"] == "TREND,MOMENTUM"
    assert intent["liquidity_zone_context"]["liquidity_score"] == 0.82
    assert "v2:market:orderbook" in intent["liquidity_zone_context"]["source_labels"]
    assert "v2:market:liquidation_levels" in intent["liquidation_distance_context"]["source_labels"]
    assert "v2:market:microstructure" in intent["microstructure_context"]["source_labels"]


def test_candidate_correlation_context_uses_fresh_ohlcv_returns_against_open_symbols() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    fake = FakeRedis()
    returns_candidate = [0.001, -0.001, 0.001, -0.001] * 10
    returns_open = [0.001, -0.001, 0.001, -0.001] * 10
    start_ms = _ms("2026-06-20T00:30:00Z")
    fake.store["v2:market:ohlcv_closed:binance:ALPHAUSDT:1m"] = json.dumps(
        _closed_candles_from_returns("ALPHAUSDT", returns_candidate, start_ms=start_ms)
    )
    fake.store["v2:market:ohlcv_closed:binance:BETAUSDT:1m"] = json.dumps(
        _closed_candles_from_returns("BETAUSDT", returns_open, start_ms=start_ms)
    )

    contexts = paper._derive_candidate_correlation_contexts(  # noqa: SLF001
        fake,
        candidate_symbols=["ALPHAUSDT"],
        open_symbols=["BETAUSDT"],
        generated_utc="2026-06-20T02:00:00Z",
    )

    assert contexts["ALPHAUSDT"]["correlation_input_status"] == "READY"
    assert contexts["ALPHAUSDT"]["correlation_input_source"] == "MARKET_OHLCV_RETURN_CORRELATION"
    assert contexts["ALPHAUSDT"]["correlation_pair_count"] == 1
    assert contexts["ALPHAUSDT"]["correlation_exposure_pct"] == 1.0


def test_candidate_correlation_context_fails_closed_when_candidate_candles_are_stale() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    fake = FakeRedis()
    stale_returns = [0.001, -0.0005, 0.0007, -0.0002] * 10
    fresh_returns = [0.001, -0.001, 0.001, -0.001] * 10
    fake.store["v2:market:ohlcv_closed:binance:ALPHAUSDT:1m"] = json.dumps(
        _closed_candles_from_returns("ALPHAUSDT", stale_returns, start_ms=_ms("2026-06-15T16:00:00Z"))
    )
    fake.store["v2:market:ohlcv_closed:binance:BETAUSDT:1m"] = json.dumps(
        _closed_candles_from_returns("BETAUSDT", fresh_returns, start_ms=_ms("2026-06-20T00:30:00Z"))
    )

    contexts = paper._derive_candidate_correlation_contexts(  # noqa: SLF001
        fake,
        candidate_symbols=["ALPHAUSDT"],
        open_symbols=["BETAUSDT"],
        generated_utc="2026-06-20T02:00:00Z",
    )

    assert contexts["ALPHAUSDT"]["correlation_exposure_pct"] == 1.0
    assert contexts["ALPHAUSDT"]["correlation_input_status"] == "STALE_LAST_CANDLE"
    assert contexts["ALPHAUSDT"]["correlation_input_source"] == "MISSING_CANDIDATE_RETURNS_FAIL_CLOSED"


def test_market_state_envelope_prefers_prediction_decision_time_over_stale_signal_time() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    envelope = paper._build_market_state_envelope(  # noqa: SLF001
        signal={
            "symbol": "BTCUSDT",
            "generated_utc": "2026-06-14T08:00:00Z",
            "confidence_calibrated": 0.7,
        },
        prediction={
            "symbol": "BTCUSDT",
            "decision_time": "2026-06-14T08:55:00Z",
            "feature_cutoff": "2026-06-14T08:54:59Z",
            "generated_at": "2026-06-14T08:55:01Z",
            "confidence_calibrated": 0.72,
        },
    )

    assert envelope["decision_time"] == "2026-06-14T08:55:00Z"


def test_future_cutoff_offenders_report_timeframe_rows_after_decision_time() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    offenders = paper._future_cutoff_offenders(  # noqa: SLF001
        market_state_envelope={"decision_time": "2026-06-14T09:02:40Z"},
        timeframe_rows=[
            {
                "symbol": "ARUSDT",
                "timeframe": "1m",
                "prediction_id": "pred_1m",
                "feature_cutoff": "2026-06-14T09:03:59Z",
                "decision_time": "2026-06-14T09:04:01Z",
            },
            {
                "symbol": "ARUSDT",
                "timeframe": "15m",
                "prediction_id": "pred_15m",
                "feature_cutoff": "2026-06-14T08:59:59Z",
            },
        ],
    )

    assert offenders == [
        {
            "symbol": "ARUSDT",
            "timeframe": "1m",
            "prediction_id": "pred_1m",
            "feature_cutoff": "2026-06-14T09:03:59Z",
            "decision_time": "2026-06-14T09:02:40Z",
            "row_decision_time": "2026-06-14T09:04:01Z",
        }
    ]


def test_point_in_time_timeframe_rows_excludes_later_sibling_predictions() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    envelope = {"decision_time": "2026-06-14T09:02:40Z"}
    rows = [
        {
            "symbol": "ARUSDT",
            "timeframe": "1m",
            "prediction_id": "future_pred",
            "feature_cutoff": "2026-06-14T09:03:59Z",
            "decision_time": "2026-06-14T09:04:01Z",
        },
        {
            "symbol": "ARUSDT",
            "timeframe": "15m",
            "prediction_id": "pit_pred",
            "feature_cutoff": "2026-06-14T08:59:59Z",
            "decision_time": "2026-06-14T09:02:00Z",
        },
        {
            "symbol": "ARUSDT",
            "timeframe": "5m",
            "prediction_id": "missing_time_pred",
            "feature_cutoff": "2026-06-14T08:59:59Z",
        },
    ]

    filtered = paper._point_in_time_timeframe_rows(  # noqa: SLF001
        market_state_envelope=envelope,
        timeframe_rows=rows,
    )
    offenders = paper._future_cutoff_offenders(  # noqa: SLF001
        market_state_envelope=envelope,
        timeframe_rows=filtered,
    )

    assert [row["prediction_id"] for row in filtered] == ["pit_pred"]
    assert offenders == []


def test_point_in_time_timeframe_rows_preserves_true_future_cutoff_offenders() -> None:
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    envelope = {"decision_time": "2026-06-14T09:02:40Z"}
    filtered = paper._point_in_time_timeframe_rows(  # noqa: SLF001
        market_state_envelope=envelope,
        timeframe_rows=[
            {
                "symbol": "ARUSDT",
                "timeframe": "1m",
                "prediction_id": "dirty_pred",
                "feature_cutoff": "2026-06-14T09:03:59Z",
                "available_at": "2026-06-14T09:02:00Z",
                "decision_time": "2026-06-14T09:02:00Z",
            },
        ],
    )
    offenders = paper._future_cutoff_offenders(  # noqa: SLF001
        market_state_envelope=envelope,
        timeframe_rows=filtered,
    )

    assert [row["prediction_id"] for row in filtered] == ["dirty_pred"]
    assert offenders == [
        {
            "symbol": "ARUSDT",
            "timeframe": "1m",
            "prediction_id": "dirty_pred",
            "feature_cutoff": "2026-06-14T09:03:59Z",
            "decision_time": "2026-06-14T09:02:40Z",
            "row_decision_time": "2026-06-14T09:02:00Z",
        }
    ]
