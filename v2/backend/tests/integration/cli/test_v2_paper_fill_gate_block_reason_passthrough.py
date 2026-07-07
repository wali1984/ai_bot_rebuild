"""Tests for the strict P0.2F paper-fill gate block-reason passthrough:
prediction -> orchestrator decision -> paper intent -> comparator.

Loop spec: ensure SOLUSDT (and any gate-blocked symbol) surfaces its exact
block reasons through every layer without changing gate behavior, without
loosening thresholds, and without producing fills.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any


class FakeRedis:
    """Minimal in-memory stand-in for the small subset of redis-py we use:
    get/set/scan_iter. Keys are strings; values are strings.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {
            "v2:live_gate:state": json.dumps({"live_gate": "blocked_human_only"})
        }

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        # ex (ttl) is ignored in the in-memory fake.
        self.store[key] = value
        return True

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        if match is None:
            yield from list(self.store.keys())
            return
        # Trivial glob support for "v2:prediction:*"
        prefix = match.rstrip("*")
        for k in list(self.store.keys()):
            if match.endswith("*"):
                if k.startswith(prefix):
                    yield k
            elif k == match:
                yield k

    def type(self, key: str) -> str:
        return "string" if key in self.store else "none"

    def ttl(self, key: str) -> int:  # noqa: ARG002
        return 300


def _patch_connect(monkeypatch, module_path: str, fake: FakeRedis) -> None:
    mod = importlib.import_module(module_path)
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)


def _make_blocked_prediction(symbol: str, block_reasons: list[str]) -> dict[str, Any]:
    return {
        "prediction_id": f"pred_{symbol}",
        "feature_snapshot_id": f"fs_{symbol}",
        "symbol": symbol,
        "timeframe": "1m",
        "trainer_source": "v2_native_policy_cpu_forward_v1",
        "checkpoint_id": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        "expected_move_bps": -3.0,
        "expected_move_after_cost_bps": -5.0,
        "confidence_raw": 0.4,
        "confidence_calibrated": 0.4,
        "feature_freshness_state": "fresh",
        "routes_to_orchestrator": True,
        "selected_action": "hold",
        "policy_action_probabilities": [0.5, 0.1, 0.1, 0.2, 0.1],
        "hedge_action_classification": "no_hedge",
        "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
        "paper_fill_allowed": False,
        "paper_fill_gate_block_reasons": list(block_reasons),
        "generated_utc": "2026-05-17T05:00:00Z",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


class _MarketStateOk:
    def to_dict(self) -> dict[str, Any]:
        return {
            "market_state_id": "ms_routeable",
            "market_state_integrity_score": 95.0,
            "valid_for_prediction": True,
            "valid_for_risk": True,
            "valid_for_orchestrator": True,
            "valid_for_paper": True,
            "valid_for_live": False,
            "reject_reasons": [],
        }


def _make_routeable_prediction(symbol: str) -> dict[str, Any]:
    return {
        "prediction_id": f"pred_{symbol}",
        "decision_id": f"decision_{symbol}",
        "feature_snapshot_id": f"fs_{symbol}",
        "mtf_snapshot_id": f"mtf_{symbol}",
        "feature_cutoff": "2026-05-17T04:59:00Z",
        "decision_time": "2026-05-17T05:00:00Z",
        "available_at": "2026-05-17T04:59:30Z",
        "symbol": symbol,
        "timeframe": "1m",
        "selected_action": "long",
        "model_version": "model_v1",
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "model_id": "model_v1",
        "checkpoint_id": "ckpt_v1",
        "source_hashes": {"feature_vector_hash": "hash_feat"},
        "feature_vector_hash": "hash_feat",
        "input_feature_hash": "hash_feat",
        "all_tf_candle_timestamps": [1_780_000_000_000],
        "all_source_event_times": [1_780_000_000_000],
        "replay_snapshot_id": f"replay_{symbol}",
        "replay_snapshot_key": f"v2:replay:snapshots:pred_{symbol}",
        "replay_snapshot_write_success": True,
        "expected_move_bps": 12.0,
        "expected_move_after_cost_bps": 8.0,
        "confidence_raw": 0.72,
        "confidence_calibrated": 0.72,
        "routes_to_orchestrator": True,
        "paper_fill_allowed": True,
        "paper_fill_gate_status": "PAPER_SHADOW_GATE_OPEN",
        "paper_fill_gate_block_reasons": [],
        "generated_utc": "2026-05-17T05:00:00Z",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def test_orchestrator_emits_held_by_paper_fill_gate_with_reasons(monkeypatch) -> None:
    fake = FakeRedis()
    reasons = ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"]
    fake.store["v2:prediction:SOLUSDT:1m"] = json.dumps(
        _make_blocked_prediction("SOLUSDT", reasons)
    )
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    monkeypatch.setattr(orch, "_prediction_age_seconds", lambda _prediction: 5.0)
    status = orch.run_once()
    # Held passthrough is reflected in heartbeat status.
    assert status["predictions_held_by_paper_fill_gate"] == 1
    held = status["held_by_paper_fill_gate"]
    assert len(held) == 1
    assert held[0]["symbol"] == "SOLUSDT"
    assert held[0]["decision"] == "HELD_BY_PAPER_FILL_GATE"
    assert reasons[0] in held[0]["paper_fill_gate_block_reasons"]
    assert held[0]["places_real_order"] is False
    # The Redis-emitted decisions payload mirrors the same reasons.
    decisions = json.loads(fake.store["v2:orchestrator:decisions"])
    assert decisions["held_by_paper_fill_gate_count"] == 1
    assert reasons[0] in decisions["held_by_paper_fill_gate"][0]["paper_fill_gate_block_reasons"]
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["writes_legacy_redis"] is False


def test_orchestrator_preserves_trust_envelope_on_routeable_signal(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:prediction:BTCUSDT:1m"] = json.dumps(_make_routeable_prediction("BTCUSDT"))
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    monkeypatch.setattr(orch, "_prediction_age_seconds", lambda _prediction: 5.0)
    monkeypatch.setattr(orch, "score_market_state", lambda _row: _MarketStateOk())

    status = orch.run_once()

    assert status["bucket_winners_count"] == 1
    decisions = json.loads(fake.store["v2:orchestrator:decisions"])
    winner = decisions["bucket_winners"][0]
    signal = json.loads(fake.store["v2:signals:paper"])[0]
    for row in (winner, signal):
        assert row["prediction_id"] == "pred_BTCUSDT"
        assert row["decision_id"] == "decision_BTCUSDT"
        assert row["feature_snapshot_id"] == "fs_BTCUSDT"
        assert row["mtf_snapshot_id"] == "mtf_BTCUSDT"
        assert row["feature_cutoff"] == "2026-05-17T04:59:00Z"
        assert row["decision_time"] == "2026-05-17T05:00:00Z"
        assert row["available_at"] == "2026-05-17T04:59:30Z"
        assert row["selected_action"] == "long"
        assert row["model_version"] == "model_v1"
        assert row["checkpoint_id"] == "ckpt_v1"
        assert row["source_hashes"] == {"feature_vector_hash": "hash_feat"}


def test_orchestrator_holds_low_microstructure_trust_prediction(monkeypatch) -> None:
    fake = FakeRedis()
    prediction = _make_routeable_prediction("BTCUSDT")
    prediction.update(
        {
            "microstructure_trust_score": 0.2,
            "orderbook_trust_score": 0.2,
            "microstructure_action": "NO_TRADE",
            "sweep_risk_score": 0.8,
        }
    )
    fake.store["v2:prediction:BTCUSDT:1m"] = json.dumps(prediction)
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    monkeypatch.setattr(orch, "_prediction_age_seconds", lambda _prediction: 5.0)
    monkeypatch.setattr(orch, "score_market_state", lambda _row: _MarketStateOk())

    status = orch.run_once()

    assert status["bucket_winners_count"] == 0
    assert status["predictions_held_by_paper_fill_gate"] == 1
    held = status["held_by_paper_fill_gate"][0]
    assert held["decision"] == "HELD_BY_MICROSTRUCTURE_TRUST_GATE"
    assert held["risk_state"] == "NOT_ROUTED_TO_RISK_GATEWAY_BECAUSE_MICROSTRUCTURE_TRUST_BLOCKED"
    assert "MICROSTRUCTURE_ACTION_NO_TRADE" in held["paper_fill_gate_block_reasons"]
    assert "MICROSTRUCTURE_SWEEP_RISK_BLOCK" in held["paper_fill_gate_block_reasons"]
    assert held["microstructure_trust_score"] == 0.2
    assert held["places_real_order"] is False


def test_orchestrator_ignores_rl_core_sidecar_predictions_for_primary_paper_signals(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:prediction:rl_core:BTCUSDT:1m"] = json.dumps(
        {
            "prediction_id": "rl_core_sidecar_btc",
            "feature_snapshot_id": "fs_rl_core_btc",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "trainer_source": "V2_NATIVE_RL_CORE",
            "checkpoint_id": "rl_core_ckpt",
            "expected_move_bps": 100.0,
            "expected_move_after_cost_bps": 80.0,
            "confidence_raw": 0.8,
            "confidence_calibrated": 0.8,
            "routes_to_orchestrator": True,
            "selected_action": "long",
            "paper_fill_allowed": True,
            "generated_utc": "2026-05-17T05:00:00Z",
        }
    )
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    monkeypatch.setattr(orch, "_prediction_age_seconds", lambda _prediction: 5.0)

    status = orch.run_once()

    assert status["proposals_arbitrated"] == 0
    assert status["bucket_winners_count"] == 0
    assert json.loads(fake.store["v2:signals:paper"]) == []


def test_paper_loop_emits_held_intent_without_fill(monkeypatch) -> None:
    fake = FakeRedis()
    reasons = [
        "BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST",
        "BLOCK_FEATURE_FRESHNESS_NOT_CURRENT",
    ]
    # Seed orchestrator decisions with the held entry the paper loop reads.
    fake.store["v2:orchestrator:decisions"] = json.dumps({
        "schema_version": "v2_orchestrator_decisions_v2",
        "generated_utc": "2026-05-17T05:00:00Z",
        "considered_count": 0,
        "bucket_winners": [],
        "stale_proposal_ids": [],
        "held_by_paper_fill_gate": [{
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "prediction_id": "pred_SOLUSDT",
            "feature_snapshot_id": "fs_SOLUSDT",
            "selected_action": "hold",
            "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
            "paper_fill_gate_block_reasons": reasons,
            "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
            "decision": "HELD_BY_PAPER_FILL_GATE",
            "places_real_order": False,
            "generated_utc": "2026-05-17T05:00:00Z",
        }],
        "held_by_paper_fill_gate_count": 1,
    })
    # No paper signals -> no fills attempted.
    fake.store["v2:signals:paper"] = json.dumps([])
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_trade_management_paper_loop", fake)
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    status = paper.run_once()
    assert status["intents_held_by_paper_fill_gate"] == 1
    held_intent = status["held_by_paper_fill_gate"][0]
    assert held_intent["symbol"] == "SOLUSDT"
    assert held_intent["paper_fill_gate_block_reasons"] == reasons
    assert held_intent["places_real_order"] is False
    assert held_intent["decision"] == "HELD_BY_PAPER_FILL_GATE"
    # Confirm Redis got the held-intents key under v2:* and no positions
    # were created for the held symbol.
    held_raw = fake.store["v2:paper:intents_held_by_paper_fill_gate"]
    assert json.loads(held_raw)[0]["paper_fill_gate_block_reasons"] == reasons
    positions = json.loads(fake.store["v2:paper:positions"])
    assert positions == []
    assert status["places_real_order"] is False
    assert status["writes_legacy_redis"] is False
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_paper_loop_reads_per_symbol_paper_signal_keys(monkeypatch) -> None:
    fake = FakeRedis()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    generated_utc = now.isoformat().replace("+00:00", "Z")
    available_at = (now - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    feature_cutoff = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    # Orderbook timestamp 30s ago (epoch ms) — required for cost_source_timestamp /
    # cost_evidence_freshness_ms which the production-grade cost capture gate checks.
    orderbook_event_ms = int((now - timedelta(seconds=30)).timestamp() * 1000)
    fake.store["v2:signals:paper"] = json.dumps([])
    fake.store["v2:signals:paper:BTCUSDT:1m"] = json.dumps(
        {
            "signal_id": "signal-btc-1m",
            "prediction_id": "prediction-btc-1m",
            "feature_snapshot_id": "fs-btc-1m",
            "risk_decision_id": "risk-btc-1m",
            "orchestrator_decision_id": "orch-btc-1m",
            "decision_id": "decision-btc-1m",
            "mtf_snapshot_id": "mtf-btc-1m",
            "feature_cutoff": feature_cutoff,
            "decision_time": generated_utc,
            "available_at": available_at,
            "generated_utc": generated_utc,
            "model_version": "model-v1",
            "checkpoint_id": "ckpt-v1",
            "source_hashes": {"feature_vector_hash": "hash-btc-1m"},
            "feature_vector_hash": "hash-btc-1m",
            "input_feature_hash": "hash-btc-1m",
            "source_prediction_status": "CURRENT_RUNTIME_PAPER_SIGNAL",
            "symbol": "BTCUSDT",
            "timeframe": "15m",  # Phase 3 entry gate allows 15m/1h/4h; 1m blocked by default
            "side": "long",
            "selected_action": "long",
            "expected_move_after_cost_bps": 20.0,
            "confidence_calibrated": 0.66,
            "bid_ask_spread_bps": 1.2,
            "slippage_bps": 0.8,
            "expected_slippage_bps": 0.8,
            "expected_slippage_source": "TEST_SIGNAL_FIXTURE",
            "fee_bps": 5.0,
            "funding_rate": 0.0001,
            "maker_taker_assumption": "taker",
            "maker_taker_probability": 0.8,
            "latency_reserve_bps": 0.5,
            "market_state_id": "mstate_btc_1m",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "market_state_reject_reasons": [],
            "paper_fill_allowed": True,
            "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
            # Allow allocation: tier must be A_GRADE_EXECUTION_PAPER for the
            # allocator to proceed (otherwise it sets allocator_decision=BLOCK_NON_EXECUTABLE_PAPER_TIER
            # which leaves order_size and depth_derived_price_impact_bps unset).
            "paper_opportunity_tier": "A_GRADE_EXECUTION_PAPER",
            # Allow route_strategy to return breakout_mode instead of mean_reversion_mode:
            # without MASA predictions, route_strategy defaults to RANGE/mean_reversion_mode
            # which is blocked for long by entry_gate.blocked_side_mode_combinations.
            "paper_major_move_candidate": True,
            "major_move_evidence_score": 0.75,
            "trend_strength": 0.74,
            "range_chop_score": 0.21,
            "volatility_expansion": 0.03,
            "atr_percentile": 0.64,
            "fakeout_reversal_probability": 0.08,
            "cross_asset_btc_eth_sol_regime": "btc_eth_sol_risk_on",
            "market_wide_risk": "risk_on",
            "liquidity_context": {
                "orderbook_depth_usd": 250_000.0,
                "depth_imbalance": 0.2,
            },
            "liquidation_context": {
                "liquidation_sweep_target_short_distance_bps": 80.0,
                "liquidation_sweep_target_long_distance_bps": 120.0,
            },
            "oi_funding_context": {
                "funding_bps": 0.1,
                "oi_change_pct": 1.2,
                "long_short_ratio": 0.9,
            },
            "public_intel_context": {"market_breadth_score": 0.67},
            "microstructure_trust_score": 0.82,
            "orderbook_trust_score": 0.82,
            "orderbook_trust_tier": "HIGH_TRUST",
            "microstructure_action": "ALLOW",
            "sweep_risk_score": 0.1,
            "cross_venue_confirmation_score": 0.8,
            "trade_tape_confirmation_score": 0.8,
            "microstructure_context": {
                "microstructure_trust_score": 0.82,
                "orderbook_trust_score": 0.82,
                "microstructure_action": "ALLOW",
                "sweep_risk_score": 0.1,
                "cross_venue_confirmation_score": 0.8,
                "trade_tape_confirmation_score": 0.8,
                "post_sweep_reversal_probability": 0.1,
                "spread_bps": 1.2,
                "orderbook_depth_usd": 250_000.0,
                "orderbook_imbalance": 0.2,
                "order_flow_imbalance": 0.12,
            },
        }
    )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(
        {
            "ticker_24hr": {"lastPrice": "100.0"},
            "markPrice": "100.02",
            "indexPrice": "100.00",
            "fetched_utc": "2026-06-08T21:00:00Z",
        }
    )
    # Orderbook provides observed_bid/ask, depth, and levels for depth-impact
    # calculation — all required by the production-grade cost-capture contract.
    fake.store["v2:market:orderbook:BTCUSDT"] = json.dumps(
        {
            "best_bid": 99.99,
            "best_ask": 100.01,
            "bids": [
                {"price": 99.99, "quantity": 500.0},
                {"price": 99.98, "quantity": 500.0},
                {"price": 99.97, "quantity": 500.0},
                {"price": 99.96, "quantity": 500.0},
                {"price": 99.95, "quantity": 500.0},
            ],
            "asks": [
                {"price": 100.01, "quantity": 500.0},
                {"price": 100.02, "quantity": 500.0},
                {"price": 100.03, "quantity": 500.0},
                {"price": 100.04, "quantity": 500.0},
                {"price": 100.05, "quantity": 500.0},
            ],
            "E": orderbook_event_ms,
        }
    )
    fake.store["v2:microstructure:trust_score:BTCUSDT:15m"] = json.dumps(
        {
            "microstructure_trust_score": 0.82,
            "orderbook_trust_score": 0.82,
            "orderbook_trust_tier": "HIGH_TRUST",
            "microstructure_action": "ALLOW",
            "adaptive_minimum": 0.65,
            "orderbook_latency_ms": 40.0,
            "book_sequence_gap": False,
            "book_depth_persistence_score": 0.9,
            "book_cancel_pressure_score": 0.1,
            "trade_tape_confirmation_score": 0.8,
            "cross_venue_confirmation_score": 0.8,
            "liquidation_zone_risk_score": 0.1,
            "sweep_risk_score": 0.1,
            "decision_time": generated_utc,
            "available_at": available_at,
        }
    )
    fake.store["v2:portfolio:state"] = json.dumps(
        {
            "equity": 10_000.0,
            "available_margin": 10_000.0,
            "wallet_balance": 10_000.0,
        }
    )
    fake.store["v2:features:snapshot:fs-btc-1m"] = json.dumps(
        {
            "feature_snapshot_id": "fs-btc-1m",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "feature_freshness_state": "CURRENT",
            "available_at": available_at,
            "generated_at": available_at,
            "feature_cutoff": feature_cutoff,
            "candle_closed_confirmed": True,
            "features": {"close_price": 100.0, "atr_bps": 50.0},
        }
    )
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_trade_management_paper_loop", fake)
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    # Isolate from on-disk state files: lifecycle state contains real open
    # positions whose correlation drives correlation_exposure_pct=1.0 → budget=0.
    monkeypatch.setattr(paper, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(paper, "_read_accepted_fill_state_file", lambda path=None: {})
    # The on-disk continuous-edge-guardian gate file blocks A_GRADE entries;
    # return empty dict so the gate is treated as absent for this unit test.
    monkeypatch.setattr(paper, "_read_continuous_edge_guardian_gate", lambda r: {})

    status = paper.run_once()

    assert status["paper_signals_seen"] == 1
    assert status["intents_built"] == 1
    assert status["intents_accepted"] == 1
    ledger = json.loads(fake.store["v2:paper:ledger"])
    assert ledger["accepted_count"] == 1
    assert ledger["accepted"][0]["signal_id"] == "signal-btc-1m"
    assert ledger["accepted"][0]["prediction_id"] == "prediction-btc-1m"
    assert ledger["accepted"][0]["intent_id"] == "signal-btc-1m"
    assert ledger["accepted"][0]["source_intent_id"] == "signal-btc-1m"
    assert ledger["accepted"][0]["risk_decision_id"] == "risk-btc-1m"
    assert ledger["accepted"][0]["orchestrator_decision_id"] == "orch-btc-1m"
    assert ledger["accepted"][0]["paper_fill_allowed"] is True
    risk_decisions = json.loads(fake.store["v2:risk:decisions"])
    assert risk_decisions[0]["prediction_id"] == "prediction-btc-1m"
    assert risk_decisions[0]["expected_move_after_cost_bps"] == 20.0
    assert risk_decisions[0]["expected_net_edge_bps"] == 20.0
    assert risk_decisions[0]["confidence_calibrated"] == 0.66
    latest_risk_decision = json.loads(fake.store["v2:risk:decisions:latest"])
    assert latest_risk_decision == risk_decisions[0]
    assert latest_risk_decision["decision_id"] == "decision-btc-1m"
    assert latest_risk_decision["mtf_snapshot_id"] == "mtf-btc-1m"
    assert latest_risk_decision["feature_cutoff"] == feature_cutoff
    assert latest_risk_decision["decision_time"] == generated_utc
    assert latest_risk_decision["available_at"] == available_at
    assert latest_risk_decision["model_version"] == "model-v1"
    assert latest_risk_decision["checkpoint_id"] == "ckpt-v1"
    assert latest_risk_decision["source_hashes"] == {"feature_vector_hash": "hash-btc-1m"}
    assert ledger["accepted"][0]["places_real_order"] is False
    assert status["places_real_order"] is False
    assert status["writes_legacy_redis"] is False


def test_paper_loop_skips_stale_per_symbol_paper_signal_keys() -> None:
    fake = FakeRedis()
    fake.store["v2:signals:paper"] = json.dumps([])
    fake.store["v2:signals:paper:BTCUSDT:1m"] = json.dumps(
        {
            "signal_id": "signal-stale-btc-1m",
            "prediction_id": "prediction-stale-btc-1m",
            "feature_snapshot_id": "fs-stale-btc-1m",
            "risk_decision_id": "risk-stale-btc-1m",
            "orchestrator_decision_id": "orch-stale-btc-1m",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "expected_move_after_cost_bps": 20.0,
            "confidence_calibrated": 0.66,
            "market_state_id": "mstate_stale_btc_1m",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_fill_allowed": True,
            "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
            "generated_est": "2000-01-01T00:00:00-05:00",
        }
    )
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    assert paper._read_paper_signals(fake) == []


def test_paper_loop_dedupes_aggregate_and_per_symbol_signal_by_prediction_id() -> None:
    fake = FakeRedis()
    aggregate = {
        "signal_id": "signal-aggregate",
        "prediction_id": "prediction-shared",
        "risk_decision_id": "risk-shared",
        "orchestrator_decision_id": "orch-shared",
        "winner_proposal_id": "winner-shared",
        "feature_snapshot_id": "fs-shared",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "expected_move_after_cost_bps": 20.0,
        "confidence_calibrated": 0.66,
        "market_state_id": "mstate-shared",
        "market_state_integrity_score": 95.0,
        "valid_for_paper": True,
        "paper_fill_allowed": True,
        "paper_fill_gate_status": "PAPER_FILL_ALLOWED",
        "generated_utc": "2026-06-19T10:00:00Z",
    }
    per_symbol = {
        **aggregate,
        "signal_id": "signal-per-symbol",
        "winner_proposal_id": None,
    }
    fake.store["v2:signals:paper"] = json.dumps([aggregate])
    fake.store["v2:signals:paper:BTCUSDT:1m"] = json.dumps(per_symbol)
    paper = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")

    rows = paper._read_paper_signals(fake)  # noqa: SLF001

    assert len(rows) == 1
    assert rows[0]["prediction_id"] == "prediction-shared"
    assert rows[0]["signal_id"] == "signal-aggregate"


def test_comparator_attaches_passthrough_integrity_note() -> None:
    comp = importlib.import_module("v2.backend.app.cli.v2_production_equivalence_comparator")
    reasons = ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"]
    per_symbol = [{
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "legacy": {"exists": True, "action": "open_long"},
        "v2": {
            "exists": True,
            "selected_action": "hold",
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": reasons,
        },
        "match": False,
        "notes": [],
    }]
    orch_held = [{
        "symbol": "SOLUSDT",
        "paper_fill_gate_block_reasons": reasons,
    }]
    paper_held = [{
        "symbol": "SOLUSDT",
        "paper_fill_gate_block_reasons": reasons,
    }]
    comp._attach_held_passthrough(per_symbol, orch_held, paper_held)
    notes = per_symbol[0]["notes"]
    passthrough_note = next(
        (n for n in notes if n.startswith("block_reasons_passthrough:")), None
    )
    assert passthrough_note is not None
    body = json.loads(passthrough_note.split("block_reasons_passthrough:", 1)[1])
    assert body["prediction"] == reasons
    assert body["orchestrator_held"] == reasons
    assert body["paper_intent_held"] == reasons
    assert body["orchestrator_matches_prediction"] is True
    assert body["paper_intent_matches_prediction"] is True


def test_comparator_flags_missing_passthrough_when_layer_drops_reasons() -> None:
    comp = importlib.import_module("v2.backend.app.cli.v2_production_equivalence_comparator")
    reasons = ["BLOCK_FEATURE_FRESHNESS_NOT_CURRENT"]
    per_symbol = [{
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "legacy": {"exists": True, "action": "open_long"},
        "v2": {
            "exists": True,
            "selected_action": "hold",
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": reasons,
        },
        "match": False,
        "notes": [],
    }]
    # Orchestrator did NOT pass through any held entry.
    comp._attach_held_passthrough(per_symbol, [], [])
    body = json.loads(per_symbol[0]["notes"][-1].split("block_reasons_passthrough:", 1)[1])
    assert body["prediction"] == reasons
    assert body["orchestrator_emitted"] is False
    assert body["paper_intent_emitted"] is False
    assert body["orchestrator_matches_prediction"] is False
    assert body["paper_intent_matches_prediction"] is False


def test_no_old_redis_writes_in_held_passthrough(monkeypatch) -> None:
    fake = FakeRedis()
    fake.store["v2:prediction:SOLUSDT:1m"] = json.dumps(
        _make_blocked_prediction("SOLUSDT", ["BLOCK_LIVE_GATE_NOT_BLOCKED"])
    )
    _patch_connect(monkeypatch, "v2.backend.app.cli.v2_orchestrator_arbitration_loop", fake)
    orch = importlib.import_module("v2.backend.app.cli.v2_orchestrator_arbitration_loop")
    orch.run_once()
    # All new keys must be under v2: namespace.
    for k in fake.store.keys():
        assert k.startswith("v2:"), f"Unexpected non-v2 redis write: {k}"


def test_gate_block_reasons_in_continuous_remediation_gap_matrix(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[5]
    path = root / "claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py"
    spec = importlib.util.spec_from_file_location("v2_cont_remed_mod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    enriched = {
        "per_symbol": [{
            "symbol": "SOLUSDT",
            "mismatch_causes_classified": ["v2_paper_fill_gate_blocked"],
            "match": False,
            "v2_action": "hold",
            "v2_paper_fill_allowed": False,
            "v2_paper_fill_gate_block_reasons": ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"],
            "legacy_redis_action": "OPEN_LONG",
            "legacy_log_action": None,
        }]
    }
    gaps = mod._classify_gaps(enriched)
    assert len(gaps) == 1
    assert gaps[0]["cause"] == "v2_paper_fill_gate_blocked"
    assert gaps[0]["gap_id"] == "paper_fill_gate_blocked_with_reason"
    assert gaps[0]["paper_fill_gate_block_reasons"] == ["BLOCK_NEGATIVE_EXPECTED_MOVE_AFTER_COST"]
    assert gaps[0]["severity"] == "NO_ACTION_REQUIRED_SAFE_BLOCK"
